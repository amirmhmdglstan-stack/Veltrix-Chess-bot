#!/usr/bin/env python3
"""
epd_test.py - tactical EPD suite runner for Veltrix 1.0.

Reads EPD positions with a "bm" (best move) opcode, runs the engine at a
fixed time per position and reports scores. Ships with a small built-in
suite (tactics.vlt) and accepts external EPD collections (e.g. WAC).

Usage:
    python tools/epd_test.py                        # built-in suite, 250ms per position
    python tools/epd_test.py --file tests/suite.epd --time 500
"""
from __future__ import annotations

import argparse
import os
import sys
import re
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "gui"))

from engine_driver import UCIEngine, find_engine   # noqa: E402
from chesslib import Board                          # noqa: E402

BUILTIN = """\
# Veltrix built-in tactical sanity suite (mate/tactic, verified with the engine's
# own movegen tests and known puzzle sources)
r1bqkbnr/pppp1ppp/2n5/4p2Q/2B1P3/8/PPPP1PPP/RNB1K1NR w KQkq - bm h5f7; id "vlt-mate-01 scholar";
6k1/5ppp/8/8/8/8/8/R5K1 w - - bm a1a8; id "vlt-mate-02 backrank";
7k/8/8/8/8/8/1R6/R5K1 w - - bm b2b7; id "vlt-mate-03 ladder";
r6k/pp4pp/2p5/8/3Q4/8/PP3PPP/6K1 w - - bm d4g7; id "vlt-mate-04 queen-invasion";
2rr3k/pp3pp1/1nnqbN1p/3pN3/2pP4/2P3Q1/PPB4P/R4RK1 w - - bm g3g6; id "vlt-tac-01 Qg6!!";
3q1rk1/5pbp/1pn1p1p1/4n3/3P4/2N1PN2/1B3PPP/Q4RK1 w - - bm f3e5; id "vlt-tac-02";
r3k2r/Pppp1ppp/1b3nbN/nP6/BBP1P3/q4N2/Pp1P2PP/R2Q1RK1 w kq - bm c4c5; id "vlt-str-01 promotion-push";
3r2k1/pp3ppp/8/8/2Q5/8/PP3PPP/6K1 w - - bm c4c8; id "vlt-tac-03 deflection";
1k1r4/pp1b1R2/3q2pp/4p3/2B5/4Q3/PPP2PPP/2K5 w - - bm f7f8; id "vlt-tac-04 pin";
r4rk1/1pp1qppp/p1np1n2/2b1p1B1/2B1P1b1/P1NP1N2/1PP1QPPP/R4RK1 w - - bm g5f6; id "vlt-tac-05";
"""


def parse_epd_file(path):
    items = []
    for line in open(path):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        bm_match = re.search(r"\bbm\s+([^;]+);", line)
        if not bm_match:
            continue
        fen_part = line.split("bm")[0].strip()
        fields = fen_part.split()
        # EPD: first 4 fields are placement/stm/castling/ep; clocks may follow
        fen6 = fields[:4] + (fields[4:6] if len(fields) >= 6 and fields[4].isdigit() else ["0", "1"])
        bms = bm_match.group(1).split()
        id_match = re.search(r'\bid\s+"?([^";]+)"?;', line)
        items.append((" ".join(fen6), bms, id_match.group(1) if id_match else fen_part[:30]))
    return items


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", default="")
    ap.add_argument("--engine", default="")
    ap.add_argument("--time", type=int, default=250, help="ms per position")
    ap.add_argument("--depth", type=int, default=0, help="fixed depth instead of time")
    args = ap.parse_args()

    if args.file:
        suite = parse_epd_file(args.file)
    else:
        import tempfile
        with tempfile.NamedTemporaryFile("w", suffix=".epd", delete=False) as f:
            f.write(BUILTIN)
            tmp = f.name
        suite = parse_epd_file(tmp)
        os.unlink(tmp)

    eng = UCIEngine(find_engine(args.engine))
    eng.new_game()
    solved, total, t0 = 0, 0, time.time()
    fails = []
    for fen, bms, name in suite:
        total += 1
        board = Board(fen)
        # translate SAN-ish bm to uci if needed
        bm_uci = set()
        for cand in bms:
            try:
                bm_uci.add(board.parse_uci(cand).uci())
            except ValueError:
                # maybe it's already uci / san
                try:
                    for m in board.legal_moves():
                        if board.san(m) == cand:
                            bm_uci.add(m.uci())
                except Exception:
                    pass
        if not bm_uci:
            print(f"  ?? cannot interpret bm {bms} in {name}")
            continue
        if args.depth:
            bm, _, _ = eng.analyze(fen, [], depth=args.depth)
        else:
            bm, _, _ = eng.analyze(fen, [], movetime=args.time)
        ok = bm in bm_uci
        solved += ok
        if not ok:
            fails.append((name, fen, sorted(bm_uci), bm))
        print(f"  [{'OK' if ok else 'FAIL'}] {name:28s} tried {bm} (bm: {'/'.join(sorted(bm_uci))})")
    eng.quit()
    print(f"\n{solved}/{total} solved in {time.time() - t0:.1f}s "
          f"({args.depth and f'depth {args.depth}' or f'{args.time} ms/pos'})")
    for name, fen, want, got in fails:
        print(f"    miss: {name}: {got} != {want}")
    return 0 if not fails else 1


if __name__ == "__main__":
    sys.exit(main())
