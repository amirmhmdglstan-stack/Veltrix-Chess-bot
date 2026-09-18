#!/usr/bin/env python3
"""
Veltrix 1.0 - automated test suite (engine process + UCI protocol level).

Usage:
    python3 tests/run_tests.py [path-to-engine-binary]

Tests:
    * UCI handshake / options / readiness
    * perft (exact node counts for known positions)
    * FEN round-trip
    * Zobrist key consistency (moves-applied vs FEN-set)
    * legal move listing size
    * search smoke tests (bestmove legality, info lines)
    * checkmate-in-N detection (score mate + bestmove)
    * stop handling on infinite search
    * MultiPV
    * bench / eval command sanity
    * stalemate / mate reporting via bestmove 0000
"""
import os
import shutil
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(ROOT)


def find_engine():
    if len(sys.argv) > 1:
        p = sys.argv[1]
        if os.path.isfile(p):
            return p
        print(f"engine not found at {p}")
        sys.exit(1)
    env = os.environ.get("VELTRIX_ENGINE")
    if env and os.path.isfile(env):
        return env
    cands = [
        os.path.join(REPO, "engine", "veltrix.exe"),
        os.path.join(REPO, "engine", "veltrix"),
        os.path.join(REPO, "bin", "veltrix.exe"),
        os.path.join(REPO, "bin", "veltrix"),
        os.path.join(REPO, "veltrix.exe"),
        shutil.which("veltrix") or "",
    ]
    for c in cands:
        if c and os.path.isfile(c):
            return c
    print("No engine binary found. Build first (build.sh / build.bat).")
    sys.exit(1)


ENGINE = find_engine()
PASS = 0
FAIL = 0
FAILURES = []


class Engine:
    """Small synchronous-ish UCI driver for testing."""

    def __init__(self, path):
        self.p = subprocess.Popen(
            [path], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT, text=True, bufsize=1)

    def send(self, s):
        self.p.stdin.write(s + "\n")
        self.p.stdin.flush()

    def read_until(self, predicates, timeout=10.0):
        """Read lines until one of the predicates matches a line."""
        if isinstance(predicates, str):
            predicates = [predicates]
        out = []
        t0 = time.time()
        self.p.stdout.flush()
        while time.time() - t0 < timeout:
            line = self.p.stdout.readline()
            if line == "":
                time.sleep(0.01)
                continue
            line = line.strip()
            out.append(line)
            if any(pred in line for pred in predicates):
                return out
        raise TimeoutError(f"timeout waiting for {predicates}; got: {out[-15:]}")

    def cmd(self, s, wait=None, timeout=10.0):
        self.send(s)
        if wait is None:
            return []
        return self.read_until(wait, timeout)

    def close(self):
        try:
            self.send("quit")
            self.p.wait(timeout=3)
        except Exception:
            self.p.kill()


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  [PASS] {name}")
    else:
        FAIL += 1
        FAILURES.append((name, detail))
        print(f"  [FAIL] {name}   {detail}")


def main():
    print(f"Veltrix test suite - engine: {ENGINE}\n")
    e = Engine(ENGINE)

    # ------------------------------------------------------------ UCI basics
    print("== UCI handshake ==")
    lines = e.cmd("uci", wait="uciok")
    flat = "\n".join(lines)
    check("id name Veltrix 1.0", "id name Veltrix 1.0" in flat, flat)
    check("uciok", "uciok" in flat)
    for opt in ["Hash", "Threads", "MultiPV", "Move Overhead", "UseBook",
                "UCI_LimitStrength", "UCI_Elo", "Ponder", "BookFile",
                "SyzygyPath"]:
        check(f"option advertised: {opt}", f"option name {opt}" in flat)
    check("readyok", "readyok" in "\n".join(e.cmd("isready", wait="readyok")))

    # ------------------------------------------------------------ perft
    print("== perft exact counts ==")
    perft_tests = [
        ("startpos", "position startpos", 5, 4865609),
        ("kiwipete", "position fen r3k2r/p1ppqpb1/bn2pnp1/3PN3/1p2P3/2N2Q1p/PPPBBPPP/R3K2R w KQkq - 0 1", 4, 4085603),
        ("pos3-ep-pins", "position fen 8/2p5/3p4/KP5r/1R3p1k/8/4P1P1/8 w - - 0 1", 5, 674624),
        ("pos4-promos", "position fen r3k2r/Pppp1ppp/1b3nbN/nP6/BBP1P3/q4N2/Pp1P2PP/R2Q1RK1 w kq - 0 1", 4, 422333),
        ("pos5", "position fen rnbq1k1r/pp1Pbppp/2p5/8/2B5/8/PPP1NnPP/RNBQK2R w KQ - 1 7", 4, 2103487),
        ("pos6", "position fen r4rk1/1pp1qppp/p1np1n2/2b1p1B1/2B1P1b1/P1NP1N2/1PP1QPPP/R4RK1 w - - 0 1", 4, 3894594),
    ]
    for name, setcmd, depth, expect in perft_tests:
        e.send(setcmd)
        lines = e.cmd(f"perft {depth}", wait="Total:")
        total = None
        for ln in lines:
            if ln.startswith("Total:"):
                total = int(ln.split(":")[1].strip())
        check(f"perft {name} d{depth} == {expect}", total == expect,
              f"got {total}")

    # ------------------------------------------------------------ FEN round trip
    print("== FEN round-trip ==")
    fen_tests = [
        "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1",
        "r3k2r/p1ppqpb1/bn2pnp1/3PN3/1p2P3/2N2Q1p/PPPBBPPP/R3K2R w KQkq - 3 7",
        "8/2p5/3p4/KP5r/1R3p1k/8/4P1P1/8 w - - 17 42",
        "rnbq1k1r/pp1Pbppp/2p5/8/2B5/8/PPP1NnPP/RNBQK2R w KQ - 1 7",
        "4k3/8/8/3pP3/8/8/8/4K3 w - d6 0 12",
    ]
    for fen in fen_tests:
        e.cmd(f"position fen {fen}")
        lines = e.cmd("d", wait="Key:")
        got = None
        for ln in lines:
            if ln.startswith("FEN:"):
                got = ln[4:].strip()
        check(f"fen round-trip: {fen[:40]}...", got is not None and
              " ".join(got.split()) == " ".join(fen.split()),
              f"got {got}")

    # ------------------------------------------------------------ zobrist consistency
    print("== zobrist key consistency ==")
    seqs = [
        "e2e4 e7e5 g1f3 b8c6 f1b5 a7a6 e1g1",
        "d2d4 d7d5 c2c4 e7e6 b1c3 g8f6 c1f4 f8b4 a2a3 b4c3 b2c3",
        "e2e4 c7c5 g1f3 d7d6 d2d4 c5d4 f3d4 g8f6 b1c3 a7a6",
    ]
    for moves in seqs:
        e.cmd("ucinewgame")
        e.cmd("position startpos moves " + moves)
        k1 = None
        for ln in e.cmd("key", wait="key:"):
            if ln.startswith("key:"):
                k1 = ln.split()[1]
        # set the same position by FEN derived from the engine itself
        lines = e.cmd("d", wait="Key:")
        fen = None
        for ln in lines:
            if ln.startswith("FEN:"):
                fen = ln[4:].strip()
        e.cmd("ucinewgame")
        e.cmd("position fen " + fen)
        k2 = None
        for ln in e.cmd("key", wait="key:"):
            if ln.startswith("key:"):
                k2 = ln.split()[1]
        check(f"zobrist stable for: {moves[:30]}...", k1 is not None and k1 == k2,
              f"{k1} vs {k2}")

    # en passant key rule: keys must differ whether ep is set or not only when
    # a pawn can capture; plus undo consistency implicitly covered by move tests
    e.cmd("ucinewgame")
    e.cmd("position fen 4k3/8/8/8/8/8/3P4/4K3 w - - 0 1 moves d2d4")
    lines = e.cmd("key", wait="key:")
    e.cmd("position fen 4k3/8/8/8/3P4/8/8/4K3 b - d3 0 1")
    lines2 = e.cmd("key", wait="key:")
    check("ep key consistent (no adjacent pawn, ep not hashed)",
          lines2[0].split()[1] == lines[0].split()[1],
          f"{lines2} vs {lines}")

    # ------------------------------------------------------------ legal moves listing
    print("== legal move counts ==")
    e.cmd("position startpos")
    e.send("moves")
    out = e.read_until("moves:", timeout=5)
    check("startpos has 20 moves", len(out[0].split()) - 1 == 20, str(out[:2]))

    # search tests run with the opening book disabled (a "bestmove" arriving
    # instantly from the book without info lines would fail these assertions);
    # the book itself gets a dedicated test further down.
    print("== search smoke (book disabled) ==")
    e.cmd("setoption name UseBook value false")
    e.cmd("ucinewgame")
    e.cmd("position startpos")
    lines = e.cmd("go depth 10", wait="bestmove", timeout=20)
    info = [l for l in lines if l.startswith("info depth")]
    bm = [l for l in lines if l.startswith("bestmove")][0].split()[1]
    check("search produced >= 8 info lines", len(info) >= 8, f"{len(info)}")
    check("bestmove is long-algebraic", len(bm) >= 4, bm)
    e.send("moves")
    legal = e.read_until("moves:", timeout=5)
    check("bestmove is legal", bm in legal[0].split(), f"{bm} / {legal[0][:80]}")

    # deep search sanity with a position score sign
    e.cmd("position fen rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq e3 0 1")
    lines = e.cmd("go depth 7", wait="bestmove", timeout=20)
    bm = [l.split()[1] for l in lines if l.startswith("bestmove")][0]
    check("normal reply to 1.e4", bm != "0000", bm)

    # ------------------------------------------------------------ mates
    print("== mate detection ==")
    mate_tests = [
        ("scholar-style", "r1bqkbnr/pppp1ppp/2n5/4p2Q/2B1P3/8/PPPP1PPP/RNB1K1NR w KQkq - 0 1",
         "h5f7", 1),
        ("back-rank", "6k1/5ppp/8/8/8/8/8/R5K1 w - - 0 1", "a1a8", 1),
        ("mate in 2 (rook ladder, 1.Rb7! Kg8 2.Ra8#)",
         "7k/8/8/8/8/8/1R6/R5K1 w - - 0 1", "b2b7", 2),
    ]
    for name, fen, expect_move, mate_in in mate_tests:
        e.cmd("ucinewgame")
        e.cmd(f"position fen {fen}")
        lines = e.cmd(f"go depth {mate_in * 2 + 2}", wait="bestmove", timeout=20)
        bm = [l.split()[1] for l in lines if l.startswith("bestmove")][0]
        mate_seen = any(f"score mate {mate_in}" in l for l in lines if l.startswith("info"))
        if expect_move:
            check(f"{name}: bestmove == {expect_move}", bm == expect_move, bm)
        check(f"{name}: announces mate in {mate_in}", mate_seen,
              "\n".join(l for l in lines if l.startswith("info"))[-200:])

    # forced-mate conversion playout: the engine plays BOTH sides at shallow
    # depth; must deliver mate within the bound (robust to PV flexibility)
    print("== forced mate playout (engine vs engine) ==")
    playout_tests = [
        ("KR vs K (white mates)", "4k3/8/8/8/8/8/8/R3K3 w - - 0 1", 32),
        ("KRR vs K (white mates)", "7k/8/8/8/8/8/1R6/R5K1 w - - 0 1", 8),
        ("KQ vs K (white mates)", "4k3/8/8/8/8/8/8/3QK3 w - - 0 1", 22),
    ]
    for name, fen, max_plies in playout_tests:
        e.cmd("ucinewgame")
        moves = []
        mated = False
        for ply in range(max_plies):
            e.cmd(f"position fen {fen} moves {' '.join(moves)}" if moves
                  else f"position fen {fen}")
            out = e.cmd("go depth 9", wait="bestmove", timeout=15)
            mv = [l.split()[1] for l in out if l.startswith("bestmove")][0]
            if mv == "0000":
                mated = True
                break
            moves.append(mv)
        check(f"{name} in <= {max_plies} plies", mated,
              f"no mate in {max_plies}; moves: {' '.join(moves)}")

    # no-legal-move positions
    e.cmd("position fen 7k/5Q2/6K1/8/8/8/8/8 b - - 0 1")  # black mated
    lines = e.cmd("go depth 2", wait="bestmove", timeout=10)
    check("mated side emits bestmove 0000", any("bestmove 0000" in l for l in lines), str(lines))
    e.cmd("position fen 7k/8/8/8/8/8/5Q2/6K1 b - - 0 1")   # stalemate? verify no moves => 0000 or legal
    lines = e.cmd("go depth 2", wait="bestmove", timeout=10)
    check("stalemate-ish position handled", any(l.startswith("bestmove") for l in lines), str(lines))

    # ------------------------------------------------------------ stop & infinite
    print("== stop handling ==")
    e.cmd("ucinewgame")
    e.cmd("position startpos")
    e.send("go infinite")
    time.sleep(1.0)
    lines = e.cmd("stop", wait="bestmove", timeout=10)
    check("stop produced bestmove", any(l.startswith("bestmove") and
          len(l.split()) >= 2 for l in lines), str(lines[-3:]))

    # ------------------------------------------------------------ MultiPV
    print("== MultiPV ==")
    e.cmd("setoption name MultiPV value 3")
    e.cmd("position startpos")
    lines = e.cmd("go depth 6", wait="bestmove", timeout=20)
    mpv = [l for l in lines if "multipv 3" in l and l.startswith("info")]
    check("MultiPV emits multipv 3 line", len(mpv) >= 1, str(lines[-4:]))
    e.cmd("setoption name MultiPV value 1")

    # ------------------------------------------------------------ options
    print("== options ==")
    e.cmd("setoption name Hash value 32")
    e.cmd("setoption name Threads value 2")
    e.cmd("ucinewgame")
    e.cmd("position startpos")
    lines = e.cmd("go depth 5", wait="bestmove", timeout=20)
    check("works with Threads=2 Hash=32", any(l.startswith("bestmove") for l in lines))
    e.cmd("setoption name Threads value 1")
    e.cmd("setoption name Hash value 64")
    e.cmd("setoption name UCI_LimitStrength value true")
    e.cmd("setoption name UCI_Elo value 1500")
    e.cmd("position startpos")
    lines = e.cmd("go depth 6", wait="bestmove", timeout=20)
    check("limited strength returns a bestmove", any(l.startswith("bestmove") for l in lines))
    e.cmd("setoption name UCI_LimitStrength value false")

    # ------------------------------------------------------------ opening book
    print("== opening book ==")
    import os as _os
    book = _os.path.join(REPO, "books", "veltrix.bin")
    if _os.path.isfile(book):
        e.cmd(f"setoption name BookFile value {book}")
        e.cmd("setoption name UseBook value true")
        e.cmd("ucinewgame")
        e.cmd("position startpos")
        lines = e.cmd("go depth 8", wait="bestmove", timeout=10)
        bm = [l.split()[1] for l in lines if l.startswith("bestmove")][0]
        info = "\n".join(lines)
        check("book move used at startpos", "book move" in info and
              bm in ("e2e4", "d2d4", "g1f3"), bm + " / " + info[-160:])
        e.cmd("setoption name UseBook value false")
    else:
        check("book file present (books/veltrix.bin)", False)

    # ------------------------------------------------------------ tactical suite
    print("== tactical regression suite (depth 12) ==")
    suite = _os.path.join(ROOT, "tactics.epd")
    if _os.path.isfile(suite):
        import re as _re
        items = []
        for line in open(suite):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            mbm = _re.search(r"\bbm\s+([^;]+);", line)
            if not mbm:
                continue
            fields = line.split("bm")[0].strip().split()
            fen6 = " ".join(fields[:4] + (fields[4:6] if len(fields) >= 6
                            and fields[4].lstrip("-").isdigit() else ["0", "1"]))
            items.append((fen6, mbm.group(1).split()))
        ok = 0
        for fen6, bms in items:
            e.cmd("ucinewgame")
            e.cmd("position fen " + fen6)
            lines = e.cmd("go depth 12", wait="bestmove", timeout=30)
            bm = [l.split()[1] for l in lines if l.startswith("bestmove")][0]
            ok += bm in bms
        check(f"tactical suite solved ({ok}/{len(items)})", ok == len(items))
    else:
        check("tactical suite present (tests/tactics.epd)", False)

    # ------------------------------------------------------------ misc commands
    print("== misc ==")
    lines = e.cmd("compiler", wait="info string")
    check("compiler command", any("info string" in l for l in lines))
    e.cmd("position startpos")
    lines = e.cmd("eval", wait="total")
    check("eval trace runs", any("total" in l for l in lines))
    print("== bench ==")
    t0 = time.time()
    lines = e.cmd("bench 6", wait="Nodes/second", timeout=90)
    flat = "\n".join(lines)
    check("bench completes with NPS", "Nodes/second" in flat)
    print(f"    (bench d6 took {time.time()-t0:.1f}s)")

    e.close()

    print("\n=================================================")
    print(f"RESULT: {PASS} passed, {FAIL} failed")
    if FAILURES:
        print("failures:")
        for n, d in FAILURES:
            print(f"  - {n}: {d[:100]}")
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
