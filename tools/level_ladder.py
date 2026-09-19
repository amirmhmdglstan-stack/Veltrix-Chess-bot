#!/usr/bin/env python3
"""
level_ladder.py - verify that Veltrix's difficulty ladder is monotone.

Plays fixed-node-budget matches between adjacent entries of the ladder
defined in gui/models.py (PART 1/17 acceptance: parameters verified by
TESTING, not assumed):

    Flash ~ Level 1 (same config, parity expected)
    Level 2 > Level 1 > ... > Level 7
    High/Level 8 (reference node cap for the unlimited tiers) > Level 7

Every game is played engine-vs-engine with alternating colours over a
fixed opening slate, UseBook off, Threads 1, Hash 32. The *only* per-move
budget is the node cap of each tier, exactly the knob the GUI mounts.

Usage:
    python3 tools/level_ladder.py --games 16 --workers 6 \
        --out data/model_verification.json
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "gui"))

from engine_driver import UCIEngine, find_engine       # noqa: E402
from chesslib import Board, STARTPOS_FEN              # noqa: E402
import models                                          # noqa: E402
from match import DEFAULT_OPENINGS                    # noqa: E402

# reference node budget to stand in for the unlimited tiers in a
# fixed-node match (this does NOT change shipped behaviour; High stays
# unlimited at play time)
REF_UNLIMITED_NODES = 1_000_000
BASE_OPTS = {"UseBook": "false", "Threads": 1, "Hash": 32}
ADJUDICATE_CP = 1500
ADJUDICATE_STREAK = 6
MAX_PLIES = 220


def tier_nodes(p) -> int:
    return REF_UNLIMITED_NODES if p.unlimited else p.nodes


def play_nodes_game(path, nodes_w, nodes_b, opening, name_w, name_b):
    """One fixed-nodes game. Returns (result, reason, plies)."""
    w = UCIEngine(path, name=name_w, options=dict(BASE_OPTS))
    b = UCIEngine(path, name=name_b, options=dict(BASE_OPTS))
    fen0, moves0 = opening
    board = Board(fen0)
    for u in moves0:
        board.push(board.parse_uci(u))
    streak = {"w": 0, "b": 0}
    plies = 0
    try:
        w.new_game()
        b.new_game()
        for _ in range(MAX_PLIES):
            out = board.outcome()
            if out:
                return out[0], out[1], plies
            eng = w if board.stm == "w" else b
            nodes = nodes_w if board.stm == "w" else nodes_b
            hist = moves0 + [m.uci() for m in board.move_stack[len(moves0):]]
            bm, _, infos = eng.analyze(fen0, hist, nodes=nodes)
            if not bm or bm == "0000":
                return ("0-1" if board.stm == "w" else "1-0"), "no move", plies
            try:
                m = board.parse_uci(bm)
            except ValueError:
                return ("0-1" if board.stm == "w" else "1-0"), f"illegal {bm}", plies
            board.push(m)
            plies += 1
            score = None
            for line in reversed(infos):
                if " score " in line:
                    parts = line.split()
                    i = parts.index("score")
                    if parts[i + 1] == "cp":
                        score = int(parts[i + 2])
                    elif parts[i + 1] == "mate" and int(parts[i + 2]) < 0:
                        score = -100000
                    break
            mover = "b" if board.stm == "w" else "w"
            if score is not None and score <= -ADJUDICATE_CP:
                streak[mover] += 1
            else:
                streak[mover] = 0
            if streak[mover] >= ADJUDICATE_STREAK:
                return ("0-1" if mover == "w" else "1-0"), "adjudicated", plies
    finally:
        w.quit()
        b.quit()
    return "1/2-1/2", "ply limit", plies


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--games", type=int, default=16)
    ap.add_argument("--games-low", type=int, default=40,
                    help="games for the cheap low-tier pairs (noise-resistant)")
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--out", default="data/model_verification.json")
    args = ap.parse_args()
    path = os.environ.get("VELTRIX_ENGINE") or find_engine()
    assert path and os.path.isfile(path), "engine binary not found"

    pairs = [("Flash", "Level 1")] + \
            [(f"Level {i}", f"Level {i - 1}") for i in range(2, 9)]
    report = {"engine": path, "games_per_pair": args.games,
              "ref_unlimited_nodes": REF_UNLIMITED_NODES, "pairs": []}
    exe = ThreadPoolExecutor(max_workers=args.workers)
    for kh, kl in pairs:
        ph, pl = models.profile(kh), models.profile(kl)
        nh, nl = tier_nodes(ph), tier_nodes(pl)
        pts_hi, wins_hi, wins_lo, draws = 0.0, 0, 0, 0
        futs, t0 = [], time.time()
        n_games = (args.games_low if nh and nh <= 32000 and nl and nl <= 32000
                   else args.games)
        for g in range(n_games):
            opening = DEFAULT_OPENINGS[(g // 2) % len(DEFAULT_OPENINGS)]
            hi_white = (g % 2 == 0)
            if hi_white:
                futs.append(exe.submit(play_nodes_game, path, nh, nl,
                                       opening, kh, kl))
            else:
                futs.append(exe.submit(play_nodes_game, path, nl, nh,
                                       opening, kl, kh))
        for g, fut in enumerate(futs):   # iterate in submission order (jobs equal-size)
            r, why, plies = fut.result()
            hi_white = (g % 2 == 0)
            hi_won = (r == "1-0") if hi_white else (r == "0-1")
            if hi_won:
                pts_hi += 1.0
                wins_hi += 1
            elif r == "1/2-1/2":
                pts_hi += 0.5
                draws += 1
            else:
                wins_lo += 1
        same = (nh == nl)
        row = {"hi": kh, "lo": kl, "nodes_hi": nh, "nodes_lo": nl,
               "wins_hi": wins_hi, "wins_lo": wins_lo, "draws": draws,
               "score_hi": pts_hi, "games": n_games, "same_config": same,
               "seconds": round(time.time() - t0, 1)}
        report["pairs"].append(row)
        print(f"{kh:9s}({nh:>9,} nodes) vs {kl:9s}({nl:>9,}): "
              f"+{wins_hi} -{wins_lo} ={draws}  score {pts_hi:.1f}/{n_games}"
              f"  ({row['seconds']}s)")
    exe.shutdown()
    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    json.dump(report, open(args.out, "w"), indent=1)
    print(f"\nreport written to {args.out}")
    # verdict
    ok = True
    for row in report["pairs"]:
        if row["same_config"]:
            continue
        if not (row["wins_hi"] >= 2 and row["wins_hi"] > row["wins_lo"]):
            ok = False
            print(f"!! ladder failure: {row['hi']} did not outscore {row['lo']}")
    print("LADDER:", "monotone" if ok else "BROKEN")
    return 0 if ok else 2


if __name__ == "__main__":
    sys.exit(main())
