#!/usr/bin/env python3
"""
build_opening_book.py - hybrid opening-book builder for Veltrix.

Merges up to three knowledge sources into books/veltrix.bin (Polyglot
format, one best entry per position, highest weight wins):

  1. curated main lines (LINES from tools/make_book.py)      weight ~60000
  2. external ECO corpus  (--eco-tsc file.tsv ...)           weight ~30000
     Any TSV with columns "eco <TAB> name <TAB> moves in SAN", e.g. the
     CC0 lichess-org/chess-openings files (a.tsv..e.tsv). SAN is resolved
     through our own chesslib, so malformed lines are skipped safely.
  3. engine-verified expansion                               weight ~20000
     Breadth-first walk over plausible human replies. Every node is
     probed with the ENGINE ITSELF (MultiPV), the top reply is entered
     into the book, and candidates within --delta cp of the best are
     expanded. Nodes that are already clearly won/lost are left to the
     search. This grows book coverage (as White AND as Black) deep into
     the early middlegame without trusting any unverified source.

Usage:
    python tools/build_opening_book.py [engine] [-o books/veltrix.bin]
           [--eco-tsv a.tsv b.tsv ...] [--nodes 1500] [--movetime 120]
           [--max-ply 12] [--multipv 4] [--delta 45]

Reproducibility: step 3 is deterministic given the same engine binary
(Threads=1, fixed movetime). Step 2 needs no network - point it at TSV
files you downloaded separately.
"""
import argparse
import os

import struct
import subprocess
import sys
import time
from collections import deque

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "gui"))
sys.path.insert(0, os.path.join(REPO, "tools"))

import chesslib                       # noqa: E402
import make_book                      # noqa: E402  (curated LINES)

STARTFEN = chesslib.STARTPOS_FEN
W_CURATED_BASE = 60000               # curated: 60000 + original weight
W_ECO = 30000                        # external corpus lines
W_ENGINE = 20000                     # engine-verified, decays with ply


# ---------------------------------------------------------------- engine io
class Engine:
    """Small resilient UCI driver.

    Every read has a deadline; on a stall the engine process is replaced
    (guards against protocol desyncs / async-search stragglers which would
    otherwise hang the builder forever). An `isready` handshake after every
    search keeps command/response strictly in step.
    """

    def __init__(self, path, timeout=30.0):
        self.path = path
        self.timeout = timeout
        self.restarts = 0
        self.q = None
        self.start()

    def start(self):
        p = subprocess.Popen([self.path], stdin=subprocess.PIPE,
                             stdout=subprocess.PIPE, text=True, bufsize=1)
        self.p = p
        # dedicated pumper thread: python's buffered reader can hide data
        # from select(), so blocking reads must not be mixed with select()
        import queue, threading
        self.q = queue.Queue()

        def pump():
            for line in iter(p.stdout.readline, ""):
                self.q.put(line.rstrip("\n"))
            self.q.put(None)                      # EOF

        self._pump = threading.Thread(target=pump, daemon=True)
        self._pump.start()
        # UseBook=false is essential: otherwise in-book positions are
        # answered instantly (no `info ... pv` lines) and probing stops.
        p.stdin.write("uci\nsetoption name Threads value 1\n"
                      "setoption name Hash value 16\n"
                      "setoption name UseBook value false\n")
        p.stdin.flush()
        while True:
            line = self._readline("uci handshake")
            if "uciok" in line:
                return

    def _readline(self, what):
        try:
            line = self.q.get(timeout=self.timeout)
        except Exception:
            raise TimeoutError("timeout waiting for engine (%s)" % what)
        if line is None:
            raise RuntimeError("engine died (%s)" % what)
        return line.strip()

    def _attempt(self, fn):
        try:
            return fn()
        except (TimeoutError, RuntimeError, BrokenPipeError, ValueError) as e:
            self.restarts += 1
            print(f"[book] engine hiccup ({e}); restarting engine "
                  f"(restart #{self.restarts})", flush=True)
            try:
                self.p.kill()
            except Exception:
                pass
            self.start()
            return None

    def bookkey_at(self, fen):
        def op():
            self.p.stdin.write("position fen %s\nbookkey\n" % fen)
            self.p.stdin.flush()
            line = self._readline("bookkey")
            if not line.startswith("bookkey"):
                raise RuntimeError("unexpected reply: " + line)
            return int(line.split()[1], 16)
        return self._attempt(op)

    def probe_multipv(self, fen, k, movetime):
        """[(uci_move, cp_score)] best-first; None on a recovered hiccup."""
        def op():
            self.p.stdin.write("position fen %s\nsetoption name MultiPV value %d\n"
                               "go movetime %d\n" % (fen, k, movetime))
            self.p.stdin.flush()
            found = {}
            while True:
                line = self._readline("search")
                if line.startswith("bestmove"):
                    break
                if (not line.startswith("info ") or " multipv " not in line
                        or " pv " not in line):
                    continue
                tok = line.split()
                try:
                    mi = tok.index("multipv")
                    si = tok.index("score")
                    vi = tok.index("pv")
                except ValueError:
                    continue
                idx = int(tok[mi + 1])
                if tok[si + 1] == "mate":
                    n = int(tok[si + 2])
                    score = 100000 - abs(n) if n >= 0 else -100000 + abs(n)
                else:
                    score = int(tok[si + 2])
                found[idx] = (tok[vi + 1], score)   # deepest iteration wins
            # strict command/response discipline: make sure no search thread
            # stragglers can desync the next batch of commands
            self.p.stdin.write("isready\n")
            self.p.stdin.flush()
            while "readyok" not in self._readline("isready"):
                pass
            return [found[i] for i in sorted(found)]
        return self._attempt(op)

    def quit(self):
        try:
            self.p.stdin.write("quit\n")
            self.p.stdin.flush()
            self.p.wait(timeout=5)
        except Exception:
            try:
                self.p.kill()
            except Exception:
                pass


def polyglot_move(uci_move):
    return make_book.polyglot_move(uci_move)


def put(entries, key, move, weight):
    cur = entries.get(key)
    if cur is None or weight > cur[0]:
        entries[key] = (weight, move)


# ------------------------------------------------------------- source 1+2
def add_curated(p, entries):
    n = 0
    for moves, weight in make_book.LINES:
        if not weight:
            continue
        b = chesslib.Board()
        w = min(65535, W_CURATED_BASE + weight)
        for u in moves:
            k = p.bookkey_at(b.fen())
            if k is not None:
                put(entries, k, polyglot_move(u), w)
            b.push(b.parse_uci(u))
        n += 1
    return n


def _norm_san(s):
    return (s.replace("0", "O").replace("+", "").replace("#", "")
             .replace("!", "").replace("?", "").replace("e.p.", ""))


def san_to_uci(board, san):
    """Resolve a SAN token to UCI by matching against generated legal moves."""
    want = _norm_san(san)
    for m in board.legal_moves():
        if _norm_san(board.san(m)) == want:
            return m.uci()
    return None


def add_eco_tsv(p, entries, paths):
    """Parse eco<TAB>name<TAB>SAN-moves TSV files into the book."""
    n_lines = n_moves = 0
    for path in paths:
        with open(path, "r", encoding="utf-8") as f:
            for raw in f:
                raw = raw.rstrip("\n")
                if not raw or raw.startswith("eco\t"):
                    continue
                parts = raw.split("\t")
                if len(parts) < 3:
                    continue
                b = chesslib.Board()
                ok = True
                for tok in parts[2].split():
                    if tok.endswith(".") or tok in ("1-0", "0-1", "1/2-1/2", "*"):
                        continue
                    u = san_to_uci(b, tok)
                    if u is None:
                        ok = False
                        break
                    k = p.bookkey_at(b.fen())
                    if k is not None:
                        put(entries, k, polyglot_move(u), W_ECO)
                    n_moves += 1
                    b.push(b.parse_uci(u))
                if ok:
                    n_lines += 1
        print(f"[book] eco-tsv {os.path.basename(path)}: total lines {n_lines}, "
              f"entries {n_moves}")
    return n_lines


# ------------------------------------------------------------- source 3
def add_engine_expansion(p, entries, nodes, movetime, max_ply, k, delta):
    seen = set()
    q = deque([(STARTFEN, 0)])
    used = 0
    while q and used < nodes:
        fen, ply = q.popleft()
        key = p.bookkey_at(fen)
        if key is None:
            continue
        if key in seen:
            continue
        seen.add(key)
        cands = p.probe_multipv(fen, k, movetime)
        if not cands:
            continue
        used += 1
        best = cands[0][1]
        if abs(best) > 30000:          # mate score -> theory pointless
            continue
        w = max(1, W_ENGINE - ply * 400)
        put(entries, key, polyglot_move(cands[0][0]), w)
        if abs(best) > 300 or ply >= max_ply:
            continue                   # decided position / deep enough
        keepmax = 3 if ply < 4 else (2 if ply < 8 else 1)
        kept = 0
        for mv, sc in cands:
            if kept >= keepmax or best - sc > delta:
                break
            b = chesslib.Board(fen)
            try:
                b.push(b.parse_uci(mv))
            except Exception:
                continue
            q.append((b.fen(), ply + 1))
            kept += 1
        if used % 100 == 0:
            print(f"[book] engine-verified: {used} positions probed, "
                  f"queue {len(q)}, entries {len(entries)}")
    return used


# -------------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("engine", nargs="?",
                    default=os.path.join(REPO, "engine", "veltrix"))
    ap.add_argument("-o", "--out", default=os.path.join(REPO, "books", "veltrix.bin"))
    ap.add_argument("--eco-tsv", nargs="*", default=[])
    ap.add_argument("--no-engine-expand", action="store_true")
    ap.add_argument("--nodes", type=int, default=1500)
    ap.add_argument("--movetime", type=int, default=120)
    ap.add_argument("--max-ply", type=int, default=12)
    ap.add_argument("--multipv", type=int, default=4)
    ap.add_argument("--delta", type=int, default=45)
    args = ap.parse_args()

    p = Engine(args.engine)
    entries = {}

    n = add_curated(p, entries)
    print(f"[book] curated main lines: {n} lines, {len(entries)} entries")

    if args.eco_tsv:
        add_eco_tsv(p, entries, args.eco_tsv)

    if not args.no_engine_expand:
        used = add_engine_expansion(p, entries, args.nodes, args.movetime,
                                    args.max_ply, args.multipv, args.delta)
        print(f"[book] engine-verified expansion: {used} positions probed")

    p.quit()

    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with open(args.out, "wb") as f:
        for key in sorted(entries):
            weight, move = entries[key]
            f.write(struct.pack(">QHHI", key, move, min(65535, weight), 0))
    print(f"[book] wrote {args.out}: {len(entries)} entries "
          f"({os.path.getsize(args.out)} bytes)")


if __name__ == "__main__":
    main()
