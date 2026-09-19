"""
engine_driver.py - UCI engine subprocess driver for Veltrix tools.

Provides a robust synchronous wrapper: start an engine, speak UCI, send
moves, request analysis with time/depth control, and parse info/bestmove.
"""
from __future__ import annotations

import os
import queue
import subprocess
import threading
import time


class UCIEngine:
    def __init__(self, path: str, name: str = "", options: dict | None = None,
                 cwd: str | None = None):
        self.path = os.path.abspath(path)
        self.name = name or os.path.basename(path)
        self.p = subprocess.Popen(
            [self.path], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT, text=True, bufsize=1,
            cwd=cwd or os.path.dirname(self.path) or ".")
        self._q: queue.Queue[str] = queue.Queue()
        self._reader = threading.Thread(target=self._read_loop, daemon=True)
        self._reader.start()
        self.send("uci")
        lines = self.wait_for("uciok", 15)
        self.id_name = ""
        for l in lines:
            if l.startswith("id name"):
                self.id_name = l[len("id name"):].strip()
        opts = {"Hash": 64, "Threads": 1}
        opts.update(options or {})
        for k, v in opts.items():
            self.setoption(k, v)
        self.send("isready")
        self.wait_for("readyok", 15)

    # ------------------------------------------------------------------ io
    def _read_loop(self):
        try:
            for line in self.p.stdout:
                self._q.put(line.rstrip("\r\n"))
        except (ValueError, OSError):
            pass
        self._q.put(None)  # EOF marker

    def send(self, s: str):
        try:
            self.p.stdin.write(s + "\n")
            self.p.stdin.flush()
        except (BrokenPipeError, OSError):
            pass

    def read_line(self, timeout: float) -> str | None:
        try:
            return self._q.get(timeout=timeout)
        except queue.Empty:
            return "*TIMEOUT*"

    def wait_for(self, token: str, timeout: float):
        out = []
        t0 = time.time()
        while time.time() - t0 < timeout:
            line = self.read_line(timeout - (time.time() - t0))
            if line is None or line == "*TIMEOUT*":
                break
            out.append(line)
            if token in line:
                break
        return out

    def setoption(self, name, value):
        self.send(f"setoption name {name} value {value}")

    def new_game(self):
        self.send("ucinewgame")
        self.send("isready")
        self.wait_for("readyok", 15)

    # --------------------------------------------------------------- search
    def analyze(self, fen: str, moves: list[str], *, depth=None, nodes=None,
                movetime=None, wtime=None, btime=None, winc=0, binc=0, movestogo=None,
                multipv=1, silent=False):
        pos = "startpos" if fen in ("startpos", "") else f"fen {fen}"
        cmd = f"position {pos}" + (" moves " + " ".join(moves) if moves else "")
        self.send(cmd)
        go = "go"
        if depth:
            go += f" depth {depth}"
        if nodes:
            go += f" nodes {int(nodes)}"
        if movetime:
            go += f" movetime {int(movetime)}"
        if wtime is not None:
            go += f" wtime {int(wtime)} btime {int(btime)} winc {int(winc)} binc {int(binc)}"
        if movestogo:
            go += f" movestogo {movestogo}"
        self.send(go)
        bestmove, ponder = None, None
        infos, t0 = [], time.time()
        hard_timeout = max(30.0, ((movetime or 0) + (wtime or 0) + 10000) / 1000.0)
        while time.time() - t0 < hard_timeout:
            line = self.read_line(hard_timeout - (time.time() - t0))
            if line in (None, "*TIMEOUT*"):
                break
            if line.startswith("info") and not silent:
                infos.append(line)
            elif line.startswith("bestmove"):
                parts = line.split()
                bestmove = parts[1] if len(parts) > 1 else "0000"
                if "ponder" in parts:
                    pi = parts.index("ponder")
                    if pi + 1 < len(parts):
                        ponder = parts[pi + 1]
                break
        return bestmove, ponder, infos

    def eval_cp(self, fen: str, moves: list[str] | None = None, depth: int = 8):
        """Convenience: return (bestmove, score-in-cp-from-side-to-move, mate-in or None)."""
        bm, _, infos = self.analyze(fen, moves or [], depth=depth)
        score, mate = None, None
        for line in reversed(infos):
            if "score" in line:
                parts = line.split()
                i = parts.index("score")
                if parts[i + 1] == "cp":
                    score = int(parts[i + 2])
                elif parts[i + 1] == "mate":
                    mate = int(parts[i + 2])
                break
        return bm, score, mate

    def perft(self, fen: str, depth: int) -> int:
        self.send("position " + ("startpos" if fen == "startpos" else f"fen {fen}"))
        lines = self.send_and_wait(f"perft {depth}", "Total:")
        for l in lines:
            if l.startswith("Total:"):
                return int(l.split(":")[1].strip())
        raise RuntimeError("no perft total")

    def send_and_wait(self, cmd: str, token: str, timeout: float = 60):
        self.send(cmd)
        return self.wait_for(token, timeout)

    def quit(self):
        try:
            self.send("quit")
            self.p.wait(timeout=5)
        except Exception:
            self.p.kill()


def find_engine(explicit: str = "") -> str:
    """Resolve an engine path: explicit arg → env → common repo locations."""
    if explicit:
        return explicit
    env = os.environ.get("VELTRIX_ENGINE")
    if env:
        return env
    here = os.path.dirname(os.path.abspath(__file__))
    repo = os.path.dirname(here)
    for cand in (os.path.join(repo, "engine", "veltrix.exe"),
                 os.path.join(repo, "engine", "veltrix"),
                 os.path.join(repo, "bin", "veltrix.exe"),
                 os.path.join(repo, "bin", "veltrix"),
                 os.path.join(repo, "veltrix.exe")):
        if os.path.isfile(cand):
            return cand
    raise SystemExit("engine binary not found - pass a path or build first")
