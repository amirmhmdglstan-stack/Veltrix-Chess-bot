#!/usr/bin/env python3
"""
sprt.py - Sequential Probability Ratio Test between two engines.

Plays games until a statistical decision is reached that the candidate
engine is stronger (H1, default +Elo margin) or not stronger (H0, 0 Elo),
with standard alpha/beta error bounds. Uses the well-known SPRT
approximation for Win/Draw/Loss (same as cutechess-cli's method).

Example:
    python tools/sprt.py --base engine-old/veltrix --test engine/veltrix \
        --tc 2+0.02 --elo0 0 --elo1 20
"""
from __future__ import annotations

import argparse
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "gui"))

from match import play_game, parse_tc, DEFAULT_OPENINGS   # noqa: E402
from engine_driver import UCIEngine                        # noqa: E402
from chesslib import game_pgn                              # noqa: E402


def llr_win_draw_loss(wins: int, draws: int, losses: int, s0: float, s1: float) -> float:
    n = wins + draws + losses
    if n == 0:
        return 0.0
    s = (wins + 0.5 * draws) / n
    # variance of a single game's result (0, 0.5, 1)
    var = (wins * (1 - s) ** 2 + draws * (0.5 - s) ** 2 + losses * (0 - s) ** 2) / n
    if var <= 1e-9:
        # all games identical outcome
        if s == s1:
            return 0.0
        return float("inf") if s > s1 else float("-inf") if s < s1 else 0.0
    return (s1 - s0) * (2 * s - s0 - s1) / (2 * var) * n


def expected_score(elo: float) -> float:
    return 1.0 / (1.0 + 10.0 ** (-elo / 400.0))


def main():
    ap = argparse.ArgumentParser(description="SPRT between two engines")
    ap.add_argument("--base", required=True)
    ap.add_argument("--test", required=True)
    ap.add_argument("--elo0", type=float, default=0.0)
    ap.add_argument("--elo1", type=float, default=15.0)
    ap.add_argument("--alpha", type=float, default=0.05)
    ap.add_argument("--beta", type=float, default=0.05)
    ap.add_argument("--tc", default="2+0.02")
    ap.add_argument("--max-games", type=int, default=500)
    ap.add_argument("--concurrency", type=int, default=1, help="(reserved; games are sequential)")
    ap.add_argument("--base-options", action="append", default=[])
    ap.add_argument("--test-options", action="append", default=[])
    ap.add_argument("--pgn", default="sprt_games.pgn")
    args = ap.parse_args()

    tc = parse_tc(args.tc)
    s0, s1 = expected_score(args.elo0), expected_score(args.elo1)
    lower = math.log(args.beta / (1 - args.alpha))
    upper = math.log((1 - args.beta) / args.alpha)

    def opts_of(lst):
        d = {}
        for o in lst:
            if "=" in o:
                k, v = o.split("=", 1)
                d[k] = v
        return d

    base_opts, test_opts = opts_of(args.base_options), opts_of(args.test_options)
    wins = draws = losses = 0
    pgn = open(args.pgn, "a")
    print(f"SPRT: H0 elo={args.elo0} (s0={s0:.3f})  H1 elo={args.elo1} (s1={s1:.3f})")
    print(f"bounds: [{lower:.3f}, {upper:.3f}], max games {args.max_games}\n")

    for g in range(args.max_games):
        # alternate colours
        base_white = (g % 2 == 0)
        e_white = UCIEngine(args.base if base_white else args.test,
                            options=base_opts if base_white else test_opts)
        e_black = UCIEngine(args.test if base_white else args.base,
                            options=test_opts if base_white else base_opts)
        e_white.new_game()
        e_black.new_game()
        opening = DEFAULT_OPENINGS[(g // 2) % len(DEFAULT_OPENINGS)]
        res, reason, sans = play_game(e_white, e_black, opening, tc, 0, 0)
        pgn.write(game_pgn(opening[0], sans,
                           e_white.id_name or "white", e_black.id_name or "black", res,
                           event="Veltrix SPRT") + "\n")
        pgn.flush()
        e_white.quit()
        e_black.quit()
        # score from TEST engine's perspective
        test_white = not base_white
        if res == "1-0":
            wins += 1 if test_white else 0
            losses += 0 if test_white else 1
        elif res == "0-1":
            wins += 0 if test_white else 1
            losses += 1 if test_white else 0
        else:
            draws += 1
        llr = llr_win_draw_loss(wins, draws, losses, s0, s1)
        n = wins + draws + losses
        score = (wins + 0.5 * draws) / n
        print(f"game {n:4d}: {res:7s} ({reason:18s})  W{wins}/D{draws}/L{losses} "
              f" score={score:.3f}  LLR={llr:+.3f}")
        if n >= 2 and llr >= upper:
            print(f"\nSPRT ACCEPTED H1: test engine is likely stronger "
                  f"(LLR {llr:.2f} >= {upper:.2f}) after {n} games")
            return 0
        if n >= 2 and llr <= lower:
            print(f"\nSPRT ACCEPTED H0: test engine is NOT clearly stronger "
                  f"(LLR {llr:.2f} <= {lower:.2f}) after {n} games")
            return 0
    print(f"\nSPRT inconclusive after {args.max_games} games "
          f"(W{wins}/D{draws}/L{losses})")
    return 1


if __name__ == "__main__":
    sys.exit(main())
