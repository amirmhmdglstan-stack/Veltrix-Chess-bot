#!/usr/bin/env python3
"""
match.py - engine-vs-engine match runner for Veltrix 1.0.

Plays a set of games between two UCI engines (or the same engine with
different options), alternating colours, with time control, opening
variation, and PGN output.

Examples:
    python tools/match.py --games 20 --tc 5+0.1
    python tools/match.py --engines engine/veltrix other/stockfish --games 40 --tc 10+0.2
    python tools/match.py --self --games 10 --depth 6
"""
from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "gui"))

from engine_driver import UCIEngine, find_engine            # noqa: E402
from chesslib import Board, STARTPOS_FEN, game_pgn          # noqa: E402

# A small set of balanced test openings (positions after the listed moves)
DEFAULT_OPENINGS = [
    (STARTPOS_FEN, []),
    (STARTPOS_FEN, ["e2e4", "e7e5"]),
    (STARTPOS_FEN, ["e2e4", "c7c5"]),
    (STARTPOS_FEN, ["d2d4", "d7d5"]),
    (STARTPOS_FEN, ["d2d4", "g8f6"]),
    (STARTPOS_FEN, ["c2c4", "e7e5"]),
    (STARTPOS_FEN, ["e2e4", "e7e6"]),
    (STARTPOS_FEN, ["e2e4", "c7c6"]),
    (STARTPOS_FEN, ["g1f3", "d7d5"]),
    (STARTPOS_FEN, ["e2e3", "e7e5"]),
]


def parse_tc(tc: str):
    """Parse a time control.

    Accepted forms:
      '5+0.2'   -> (300.0, 0.2)  minutes + increment seconds
      '5'       -> (300.0, 0.0)  minutes, no increment
      '60/0.2'  -> (60.0, 0.2)   explicit seconds ('base/inc', c-cutechess style)
    """
    if "/" in tc:
        base, inc = tc.split("/", 1)
        return float(base.replace("m", "")) * (60.0 if base.endswith("m") else 1.0), float(inc)
    if "+" in tc:
        base, inc = tc.split("+", 1)
        return float(base) * 60.0, float(inc)
    return float(tc) * 60.0, 0.0


def play_game(white: UCIEngine, black: UCIEngine, opening, tc, depth, movetime,
              max_plies=400, resign_cp=1200, resign_count=4, pgn_names=None):
    base, inc = tc
    fen0, moves0 = opening
    board = Board(fen0)
    for u in moves0:
        board.push(board.parse_uci(u))
    san_moves = []
    clocks = {"w": base, "b": base}
    resign_streak = {"w": 0, "b": 0}
    names = pgn_names or (white.name, black.name)

    for ply in range(max_plies):
        out = board.outcome()
        if out:
            return out[0], out[1], san_moves
        eng = white if board.stm == "w" else black
        fen_moves = fen0, moves0 + [m.uci() for m in board.move_stack[len(moves0):]]
        t_before = time_left = clocks[board.stm]
        import time as _t
        t0 = _t.time()
        if depth:
            bm, ponder, infos = eng.analyze(fen_moves[0], fen_moves[1], depth=depth)
        elif movetime:
            bm, ponder, infos = eng.analyze(fen_moves[0], fen_moves[1], movetime=movetime)
        else:
            bm, ponder, infos = eng.analyze(
                fen_moves[0], fen_moves[1],
                wtime=clocks["w"] * 1000, btime=clocks["b"] * 1000,
                winc=inc * 1000, binc=inc * 1000)
        elapsed = _t.time() - t0
        if not depth and not movetime:
            clocks[board.stm] = clocks[board.stm] - elapsed + inc
            if clocks[board.stm] < 0:
                return ("0-1" if board.stm == "w" else "1-0"), "time forfeit", san_moves
        if not bm or bm == "0000":
            # engine declares no move -> mate/stalemate also caught by board.outcome()
            return ("0-1" if board.stm == "w" else "1-0"), "no move (lost)", san_moves
        try:
            m = board.parse_uci(bm)
        except ValueError:
            return ("0-1" if board.stm == "w" else "1-0"), f"illegal move {bm}", san_moves
        # resignation adjudication by own eval
        if not (depth or movetime):
            pass
        san_moves.append(board.san(m))
        board.push(m)
        # early resignation adjudication (own score says lost for several moves)
        if resign_cp:
            score = None
            for line in reversed(infos):
                if " score cp " in line or " score mate " in line:
                    parts = line.split()
                    i = parts.index("score")
                    if parts[i + 1] == "cp":
                        score = int(parts[i + 2])
                    elif parts[i + 1] == "mate" and int(parts[i + 2]) < 0:
                        score = -100000
                    break
            mover = "b" if board.stm == "w" else "w"
            if score is not None and score <= -resign_cp:
                resign_streak[mover] += 1
            else:
                resign_streak[mover] = 0
            if resign_streak[mover] >= resign_count:
                return ("0-1" if mover == "w" else "1-0"), "resignation", san_moves
    out = board.outcome()
    if out:
        return out[0], out[1], san_moves
    return "1/2-1/2", "move limit", san_moves


def main():
    ap = argparse.ArgumentParser(description="Veltrix match runner")
    ap.add_argument("--engines", nargs="+", default=[],
                    help="1 or 2 engine paths (default: veltrix vs itself)")
    ap.add_argument("--games", type=int, default=10)
    ap.add_argument("--tc", default="1+0.1", help="time control min+inc-sec (e.g. 5+0.1)")
    ap.add_argument("--depth", type=int, default=0, help="fixed depth per move (overrides tc)")
    ap.add_argument("--movetime", type=int, default=0, help="ms per move (overrides tc)")
    ap.add_argument("--concurrency", type=int, default=1)
    ap.add_argument("--pgn", default="match.pgn", help="PGN output file ('-' for stdout only)")
    ap.add_argument("--options", action="append", default=[],
                    help="engine option as Name=Value (applied to BOTH engines)")
    ap.add_argument("--openings", default="", help="file with FEN lines for openings")
    args = ap.parse_args()

    paths = args.engines or [find_engine()]
    if len(paths) == 1:
        paths = paths * 2
    tc = parse_tc(args.tc)
    opts = {}
    for o in args.options:
        if "=" in o:
            k, v = o.split("=", 1)
            opts[k] = v

    openings = list(DEFAULT_OPENINGS)
    if args.openings and os.path.isfile(args.openings):
        openings = [(l.split(" moves ")[0].strip(),
                     (l.split(" moves ")[1].split() if " moves " in l else []))
                    for l in open(args.openings) if l.strip() and not l.startswith("#")]

    results = {paths[0]: 0.0, paths[1]: 0.0, "draw": 0}
    pgn_out = sys.stdout if args.pgn == "-" else open(args.pgn, "a")

    for g in range(args.games):
        wpath, bpath = paths if g % 2 == 0 else (paths[1], paths[0])
        opening = openings[g % len(openings)]
        w = UCIEngine(wpath, options=opts)
        b = UCIEngine(bpath, options=opts)
        w.new_game()
        b.new_game()
        res, reason, sans = play_game(
            w, b, opening, tc, args.depth, args.movetime,
            pgn_names=(w.id_name or w.name, b.id_name or b.name))
        wname = w.id_name or w.name
        bname = b.id_name or b.name
        if res == "1-0":
            results[wpath] += 1.0
        elif res == "0-1":
            results[bpath] += 1.0
        else:
            results["draw"] += 1
            results[wpath] += 0.5
            results[bpath] += 0.5
        print(f"game {g + 1:3d}: {wname} (w) vs {bname}: {res} ({reason}) "
              f"[{len(sans) // 2} moves]")
        pgn_out.write(game_pgn(opening[0] if opening[0] != STARTPOS_FEN or opening[1]
                               else STARTPOS_FEN, sans, wname, bname, res) + "\n")
        pgn_out.flush()
        w.quit()
        b.quit()

    if args.pgn != "-":
        pgn_out.close()
    print("\nfinal score:")
    for p in paths:
        print(f"  {p}: {results[p]}")
    print(f"  draws (count): {results['draw']}")

    # rough elo estimate of paths[1] vs paths[0]
    import math
    n = args.games
    for target in (paths[1],):
        sw = results[paths[1] if target == paths[1] else paths[0]]
        score = sw / n
        if 0 < score < 1:
            elo = 400 * math.log10(score / (1 - score))
            print(f"elo difference ({os.path.basename(paths[1])} - {os.path.basename(paths[0])}): "
                  f"{elo:+.0f} (sample size {n} - error bars are huge)")


if __name__ == "__main__":
    import time  # noqa
    main()
