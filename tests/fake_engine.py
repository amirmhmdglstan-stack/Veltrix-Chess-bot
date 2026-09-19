#!/usr/bin/env python3
"""
fake_engine.py - a tiny stand-alone UCI engine for the GUI tests.

Answers uci/isready/position/go/quit correctly (real random-but-deterministic
legal moves via the project's own chesslib) so the external-engine
integration can be tested end-to-end without shipping or downloading a
real third-party engine.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "gui"))

from chesslib import Board, STARTPOS_FEN   # noqa: E402

board = Board()
dwd = {}


def main():
    global board
    for line in sys.stdin:
        t = line.strip()
        if t == "uci":
            print("id name FakeFish 1.0")
            print("option name Skill Level type spin default 20 min 0 max 20")
            print("option name SlowThinking type check default false")
            print("uciok", flush=True)
        elif t.startswith("setoption"):
            bits = t.split()
            if "name" in bits and "value" in bits:
                ni, vi = bits.index("name"), bits.index("value")
                dwd[" ".join(bits[ni + 1:vi])] = " ".join(bits[vi + 1:])
            dwd["__count__"] = dwd.get("__count__", 0) + 1
        elif t == "isready":
            print(f"info string setoptions {dwd.get('__count__', 0)}", flush=True)
            print("readyok", flush=True)
        elif t == "ucinewgame":
            board = Board()
        elif t.startswith("position"):
            toks = t.split()
            fen = STARTPOS_FEN
            mv = []
            if toks[1] == "fen":
                mi = toks.index("moves") if "moves" in toks else len(toks)
                fen = " ".join(toks[2:mi])
                mv = toks[mi + 1:] if mi < len(toks) else []
            elif "moves" in toks:
                mv = toks[toks.index("moves") + 1:]
            board = Board(fen)
            for u in mv:
                board.push(board.parse_uci(u))
        elif t.startswith("go"):
            legal = board.legal_moves()
            if not legal:
                print("bestmove 0000", flush=True)
                continue
            # deterministic: first legal move
            m = legal[0]
            skill = dwd.get("Skill Level", "20")
            print(f"info depth 1 nodes {len(legal)} score cp 0 skill {skill} pv {m.uci()}",
                  flush=True)
            print(f"bestmove {m.uci()}", flush=True)
        elif t == "stop":
            pass
        elif t == "quit":
            return


if __name__ == "__main__":
    main()
