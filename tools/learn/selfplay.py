#!/usr/bin/env python3
"""
selfplay.py - play Veltrix games with FULL recording for the learning loop.

Every game is saved as one JSON object per line with complete ply records:
  { game, white, black, result, reason, plies, tc, seed, opening,
    engine: {w: {name, path, net}, b: {...}}, cfg,
    moves: [ {fen, move, stm, eval, depth, seldepth, nodes, ms, clock_ms, pv0} ] }

This is the single source of truth for loss analysis:
  - losses of the LOSER side are identified later by find_critical.py
  - evals come from each side's OWN info lines (real engine output, not
    re-estimated) and clocks are captured so TIME_MANAGEMENT failures are
    diagnosable.

Teacher engines are out of scope here (see analyze_teacher.py).
"""
import argparse
import json
import os
import random
import sys
import time

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(REPO, "gui"))
sys.path.insert(0, os.path.join(REPO, "tools"))

import chesslib                      # noqa: E402
from engine_driver import UCIEngine  # noqa: E402

OPENINGS = [
    [], ["e2e4", "e7e5"], ["e2e4", "c7c5"], ["d2d4", "d7d5"], ["d2d4", "g8f6"],
    ["c2c4", "e7e5"], ["e2e4", "e7e6"], ["e2e4", "c7c6"], ["g1f3", "d7d5"],
    ["e2e3", "e7e5"], ["e2e4", "d7d5"], ["d2d4", "e7e6"],
]


def net_label(path):
    try:
        st = os.stat(path)
        return f"{os.path.basename(path)}@{st.st_mtime_ns}"
    except OSError:
        return os.path.basename(path)


class Side:
    def __init__(self, path, options):
        self.e = UCIEngine(path, options=options)
        self.path = path

    def probe(self, fen, movetime):
        self.e.send("position fen %s" % fen)
        self.e.send("go movetime %d" % movetime)
        lines = self.e.wait_for("bestmove", 60)
        best, ev, dep, sd, nodes, pv0 = None, None, 0, 0, 0, ""
        for ln in lines:
            if ln.startswith("info ") and " score " in ln and " pv " in ln:
                t = ln.split()
                try:
                    si = t.index("score")
                    if t[si + 1] == "mate":
                        n = int(t[si + 2])
                        ev = 100000 - abs(n) if n >= 0 else -100000 + abs(n)
                    else:
                        ev = int(t[si + 2])
                    dep = int(t[t.index("depth") + 1])
                    sd = int(t[t.index("seldepth") + 1]) if "seldepth" in t else 0
                    nodes = int(t[t.index("nodes") + 1]) if "nodes" in t else 0
                    pv0 = " ".join(t[t.index("pv") + 1: t.index("pv") + 6])
                except (ValueError, IndexError):
                    pass
            elif ln.startswith("bestmove"):
                best = ln.split()[1]
        return best, ev, dep, sd, nodes, pv0


def play_game(rng, w, b, opening, args, game_id):
    board = chesslib.Board()
    for u in opening:
        board.push(board.parse_uci(u))
    rec = {"game": game_id,
           "white": {"name": w.e.id_name or "", "path": w.path, "net": net_label(w.path)},
           "black": {"name": b.e.id_name or "", "path": b.path, "net": net_label(b.path)},
           "result": "*", "reason": "", "plies": 0, "tc": args.movetime,
           "seed": args.seed, "opening": opening, "cfg": "movetime", "moves": []}
    clocks = {w: args.movetime, b: args.movetime}
    resign_run = {"w": 0, "b": 0}
    wh = [w, b]
    names = {id(w): "w", id(b): "w"}
    while board.outcome() is None and rec["plies"] < args.max_plies:
        side = w if board.stm == "w" else b
        fen = board.fen()
        t0 = time.time()
        best, ev, dep, sd, nodes, pv0 = side.probe(fen, args.movetime)
        ms = int((time.time() - t0) * 1000)
        rec["moves"].append({"fen": fen, "move": best, "stm": board.stm,
                             "eval": ev, "depth": dep, "seldepth": sd,
                             "nodes": nodes, "ms": ms, "pv0": pv0})
        rec["plies"] += 1
        if best is None or best == "0000":
            rec["result"] = "0-1" if board.stm == "w" else "1-0"
            rec["reason"] = "no move"
            return rec
        if ev is not None and abs(ev) > args.resign_cp:
            st = board.stm
            resign_run[st] += 1
            if resign_run[st] >= args.resign_count and ev < 0:
                rec["result"] = "0-1" if st == "w" else "1-0"
                rec["reason"] = "resign"
                return rec
        else:
            resign_run[board.stm] = 0
        board.push(board.parse_uci(best))
    outc = board.outcome()
    rec["result"] = outc[0] if outc else "1/2-1/2"
    rec["reason"] = outc[1] if outc else "max plies"
    return rec


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--engine-w", default=os.path.join(REPO, "engine", "veltrix"))
    ap.add_argument("--engine-b", default=os.path.join(REPO, "engine", "veltrix"))
    ap.add_argument("--games", type=int, default=20)
    ap.add_argument("--movetime", type=int, default=200)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--out", default=os.path.join(REPO, "data", "learn", "games.jsonl"))
    ap.add_argument("--hash", type=int, default=64)
    ap.add_argument("--options", action="append", default=[],
                    help="Name=Value applied to BOTH engines")
    ap.add_argument("--max-plies", type=int, default=220)
    ap.add_argument("--resign-cp", type=int, default=1400)
    ap.add_argument("--resign-count", type=int, default=4)
    args = ap.parse_args()

    opts = {"Hash": args.hash, "Threads": 1}
    for o in args.options:
        k, v = o.split("=", 1)
        opts[k] = v
    rng = random.Random(args.seed)
    w = Side(args.engine_w, dict(opts))
    b = Side(args.engine_b, dict(opts))
    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    losses = 0
    with open(args.out, "a", encoding="utf-8") as f:
        for g in range(args.games):
            opening = rng.choice(OPENINGS)
            ww, bb = (w, b) if g % 2 == 0 else (b, w)
            rec = play_game(rng, ww, bb, opening, args, g)
            f.write(json.dumps(rec) + "\n")
            if rec["result"] != "1/2-1/2":
                losses += 1
            print(f"[selfplay] game {g}: {rec['result']} ({rec['reason']}) "
                  f"[{rec['plies']} plies]", flush=True)
    print(f"[selfplay] done: {args.games} games, {losses} decisive -> {args.out}")


if __name__ == "__main__":
    main()
