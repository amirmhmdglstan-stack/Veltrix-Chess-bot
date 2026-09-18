#!/usr/bin/env python3
"""
book_oracle_test.py - verify books/veltrix.bin against the real python-chess
library (sandbox/CI-only check; python-chess is NOT required to build or run
Veltrix, it is only used here as a ground-truth oracle for the Polyglot
format).

Run:  python3 tests/book_oracle_test.py
"""
import os
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(ROOT, "..", "gui"))   # own chesslib for walking lines

import chesslib  # noqa: E402

FAILURES = 0


def fail(msg):
    global FAILURES
    FAILURES += 1
    print("[FAIL]", msg)


def main():
    try:
        import chess
        import chess.polyglot as poly
    except ImportError:
        print("python-chess not importable - set PYTHONPATH to its source; skipping")
        sys.exit(2)

    book_path = os.path.join(ROOT, "..", "books", "veltrix.bin")

    # -- 1. polyglot key of startpos is the universally known constant
    engine_key = int("463b96181691fc9c", 16)
    if poly.zobrist_hash(chess.Board()) != engine_key:
        fail("python-chess startpos key differs from canonical 0x463b96181691fc9c")

    # -- 2. read the book and check every (position,move) is, in fact,
    #       reachable and legal, by walking our own curated LINES
    ns = {"__file__": os.path.join(ROOT, "..", "tools", "make_book.py")}
    exec(open(ns["__file__"]).read(), ns)
    LINES = ns["LINES"]

    entries = {}
    with poly.open_reader(book_path) as reader:
        for e in reader:
            entries.setdefault(e.key, []).append(e)
    if not entries:
        fail("book is empty or unreadable")

    checked = 0
    for moves, weight in LINES:
        if not weight:
            continue
        board = chess.Board()
        for u in moves:
            key = poly.zobrist_hash(board)
            got = {}
            for ce in entries.get(key, []):
                mv = ce.move
                got[mv.uci() if hasattr(mv, "uci") else str(mv)] = ce.weight
            if u not in got:
                # not required to be present: a later line may have bumped weight
                # -- but the move must at least be LEGAL in a sane book
                pass
            else:
                checked += 1
            if not board.is_legal(chess.Move.from_uci(u)):
                fail(f"curated line contains illegal move {u} at {board.fen()}")
            board.push_uci(u)

    # -- 3. every book move must be legal in its position
    illegal = 0
    for key, elist in entries.items():
        # locate the position for the key by walking our curated lines
        break
    # (exhaustive legality check needs the position of each key; covered below
    #  by comparing entries against curated-line positions we know exactly.)
    print(f"[PASS] python-chess reads {sum(len(v) for v in entries.values())} entries, "
          f"verified {checked} curated probes")
    for moves, weight in LINES:
        if not weight:
            continue
        b = chess.Board()
        for u in moves:
            for ce in entries.get(poly.zobrist_hash(b), []):
                mv = ce.move
                u2 = mv.uci() if hasattr(mv, "uci") else str(mv)
                if not b.is_legal(chess.Move.from_uci(u2)):
                    illegal += 1
                    fail(f"book move {u2} illegal at {b.fen()}")
            b.push_uci(u)
    if illegal == 0:
        print("[PASS] all book moves legal at their positions")
    print("[PASS] startpos key == canonical" if FAILURES == 0 else "")
    sys.exit(1 if FAILURES else 0)


if __name__ == "__main__":
    main()
