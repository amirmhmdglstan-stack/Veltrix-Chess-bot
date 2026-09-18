#!/usr/bin/env python3
"""
make_book.py - build books/veltrix.bin (Polyglot format) from curated lines.

Usage:
    python tools/make_book.py [engine_path] [output_path]

The script plays each opening line from the starting position through the
*engine itself* (using the `bookkey` diagnostic command), so every entry has
a correctly-formed Polyglot key. Weights: deeper/main lines get high weight;
sidelines lower.
"""
import os
import struct
import subprocess
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "gui"))
DEFAULT_OUT = os.path.join(REPO, "books", "veltrix.bin")


def validate_lines():
    """Every curated line must be a sequence of legal moves from the
    initial position - reject the whole book otherwise (uses our own
    chesslib, no third-party dependency)."""
    import chesslib
    errors = 0
    for moves, weight in LINES:
        if not weight:
            continue
        b = chesslib.Board()
        for u in moves:
            try:
                m = b.parse_uci(u)
            except Exception:
                print(f"[make_book] ILLEGAL move {u} at {b.fen()}")
                errors += 1
                break
            b.push(m)
    if errors:
        raise SystemExit(f"[make_book] {errors} invalid opening line(s) - book NOT written")

# (line as UCI moves, weight) - weight applies to every move in the line;
# earlier lines win ties via weight ordering during probe selection anyway.
LINES = [
    # 1.e4 e5 - main lines
    ("e2e4 e7e5 g1f3 b8c6 f1b5 a7a6 b5a4 g8f6 e1g1 f8e7 f1e1 b7b5 a4b3 d7d6".split(), 120),
    ("e2e4 e7e5 g1f3 b8c6 f1b5 a7a6 b5a4 g8f6 e1g1 f6e4".split(), 90),          # Berlin-ish (open)
    ("e2e4 e7e5 g1f3 b8c6 f1b5 g8f6".split(), 95),                              # Berlin
    ("e2e4 e7e5 g1f3 b8c6 d2d4 e5d4 f3d4 g8f6 d4c6 b7c6 e4e5 d8e7".split(), 85), # Scotch
    ("e2e4 e7e5 g1f3 b8c6 f1c4 f8c5 c2c3 g8f6 d2d3 d7d6".split(), 100),         # Italian
    ("e2e4 e7e5 g1f3 b8c6 f1c4 g8f6 d2d3 f8c5".split(), 95),                    # Giuoco
    ("e2e4 e7e5 g1f3 b8c6 f1c4 f8c5 c2c3 g8f6 d2d4 e5d4 c3d4 c5b4".split(), 80),
    # 1.e4 - big defences
    ("e2e4 c7c5 g1f3 d7d6 d2d4 c5d4 f3d4 g8f6 b1c3 a7a6 f1e2 e7e5 d4b3 f8e7".split(), 110),  # Najdorf
    ("e2e4 c7c5 g1f3 d7d6 d2d4 c5d4 f3d4 g8f6 b1c3 a7a6 c1g5 e7e6 f2f4 d8b6".split(), 90),
    ("e2e4 c7c5 g1f3 b8c6 d2d4 c5d4 f3d4 g8f6".split(), 90),
    ("e2e4 c7c5 c2c3 d7d5 e4d5 d8d5 d2d4 g8f6".split(), 80),                    # Alapin
    ("e2e4 c7c6 d2d4 d7d5 b1c3 d5e4 c3e4 b8d7 g1f3 g8f6".split(), 105),         # Caro
    ("e2e4 c7c6 d2d4 d7d5 e4d5 c6d5 c2c4 g8f6 b1c3 e7e6 g1f3 f8e7".split(), 85),  # Caro exchange
    ("e2e4 e7e6 d2d4 d7d5 b1c3 f8b4 e4e5 c7c5 a2a3 b4c3 b2c3 d8c7".split(), 100), # French Winawer
    ("e2e4 e7e6 d2d4 d7d5 b1d2 g8f6 e4e5 f6d7 f1d3 c7c5".split(), 85),
    ("e2e4 e7e6 d2d4 d7d5 e4e5 c7c5 c2c3 b8c6 g1f3 d8b6".split(), 90),          # French advance
    ("e2e4 d7d6 d2d4 g8f6 b1c3 g7g6 g1f3 f8g7 f1e2 e8g8".split(), 80),          # Pirc classical
    ("e2e4 g7g6 d2d4 f8g7 b1c3 d7d6 f2f4".split(), 70),                         # Modern Austrian
    ("e2e4 b8c6 d2d4 d7d5 b1c3 d5e4 d4d5".split(), 60),                         # Nimzowitsch defence
    ("e2e4 c7c5 g1f3 e7e6 d2d4 c5d4 f3d4 g8f6 b1c3 d7d6".split(), 90),          # Scheveningen
    # 1.d4
    ("d2d4 d7d5 c2c4 e7e6 b1c3 g8f6 c4d5 e6d5 c1g5 f8e7".split(), 105),         # QGD exchange
    ("d2d4 d7d5 c2c4 e7e6 b1c3 f8e7 g1f3 g8f6".split(), 90),
    ("d2d4 d7d5 c2c4 c7c6 b1c3 g8f6 g1f3".split(), 100),                        # Slav
    ("d2d4 d7d5 c2c4 d5c4 g1f3 g8f6 e2e3 e7e6 f1c4 c7c5".split(), 80),          # QGA
    ("d2d4 g8f6 c2c4 g7g6 b1c3 f8g7 e2e4 d7d6 g1f3 e8g8 f1e2".split(), 100),    # KID
    ("d2d4 g8f6 c2c4 e7e6 b1c3 f8b4 e2e3 e8g8 f1d3 d7d5".split(), 100),         # Nimzo
    ("d2d4 g8f6 c2c4 e7e6 g1f3 b7b6 g2g3 c8b7 f1g2".split(), 85),               # QID
    ("d2d4 g8f6 c2c4 e7e6 g1f3 d7d5 b1c3".split(), 85),
    ("d2d4 d7d5 g1f3 g8f6 c2c4".split(), 60),
    # 1.c4 / Reti moderns
    ("c2c4 e7e5 b1c3 g8f6 g1f3 b8c6 g2g3".split(), 80),                         # English reversed Sicilian
    ("c2c4 c7c5 g1f3 g8f6 b1c3 b8c6".split(), 75),                              # English sym
    ("g1f3 d7d5 g2g3 g8f6 f1g2 e7e6".split(), 70),                              # Reti
    ("d2d4 f7f5 g1f3 g8f6 c2c4 e7e6 g2g3".split(), 60),                         # Dutch
    # Deep main-line follow-ups
]


def engine_start(path):
    p = subprocess.Popen([path], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                         text=True, bufsize=1)
    p.stdin.write("uci\n"); p.stdin.flush()
    while True:
        line = p.stdout.readline()
        if "uciok" in line: break
    return p


def bookkey(p, fen, moves, bonus_halfmove):
    cmd = "position fen " + fen + (" moves " + " ".join(moves) if moves else "") + "\n"
    p.stdin.write(cmd); p.stdin.flush()
    p.stdin.write("bookkey\n"); p.stdin.flush()
    line = p.stdout.readline().strip()
    if not line.startswith("bookkey"):
        raise RuntimeError("unexpected reply: " + line)
    return int(line.split()[1], 16)


def polyglot_move(uci_move):
    frm = "abcdefgh".index(uci_move[0]) + 8 * (int(uci_move[1]) - 1)
    to = "abcdefgh".index(uci_move[2]) + 8 * (int(uci_move[3]) - 1)
    promo = 0
    if len(uci_move) == 5:
        promo = {"n": 1, "b": 2, "r": 3, "q": 4}[uci_move[4]]
    return to | (frm << 6) | (promo << 12)


def main():
    validate_lines()
    engine = sys.argv[1] if len(sys.argv) > 1 else os.path.join(REPO, "engine", "veltrix")
    out = sys.argv[2] if len(sys.argv) > 2 else DEFAULT_OUT
    p = engine_start(engine)
    entries = {}
    startfen = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"
    total_lines = 0
    for moves, weight in LINES:
        if not weight:
            continue
        board_moves = []
        for mv in moves:
            key = bookkey(p, startfen, board_moves, 0)
            pm = polyglot_move(mv)
            # duplicate keys: keep the best-weighted / earlier entry
            if key not in entries or weight > entries[key][0]:
                entries[key] = (weight, pm)
            board_moves.append(mv)
        total_lines += 1
    p.stdin.write("quit\n"); p.stdin.flush()
    p.wait(timeout=5)

    # write polyglot binary: (key u64, move u16, weight u16, learn u32) big-endian
    blob = b""
    for key in sorted(entries):
        weight, pm = entries[key]
        blob += struct.pack(">QHHI", key, pm, weight, 0)
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "wb") as f:
        f.write(blob)
    print(f"wrote {out}: {len(entries)} entries from {total_lines} lines "
          f"({len(blob)} bytes)")


if __name__ == "__main__":
    main()
