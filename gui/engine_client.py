"""
engine_client.py - asynchronous UCI engine client for the Veltrix GUI.

Runs the engine in a subprocess, reads stdout on a background thread, and
delivers parsed events (info lines, bestmove) to the Tk main thread via a
queue polled with after(). No engine logic lives here beyond UCI plumbing.
"""
from __future__ import annotations

import os
import queue
import subprocess
import sys
import threading
import time


def find_engine(search_dir: str = "", extra_candidates=None) -> str | None:
    """
    Auto-detect the engine binary next to the GUI, in ./bin, ./engine and ../engine.
    Returns a path or None.
    """
    names = ["veltrix.exe", "veltrix"]
    roots = []
    if search_dir:
        roots.append(search_dir)
    try:
        roots.append(os.path.dirname(os.path.abspath(sys.argv[0])))
    except Exception:
        pass
    here = os.path.dirname(os.path.abspath(__file__))
    roots += [here, os.getcwd(),
              os.path.join(here, "bin"), os.path.join(here, "engine"),
              os.path.join(here, "..", "engine"), os.path.join(here, "..", "bin"),
              os.path.join(here, "..")]
    if extra_candidates:
        roots += extra_candidates
    for root in roots:
        for name in names:
            cand = os.path.join(root, name)
            if os.path.isfile(cand) and os.access(cand, os.X_OK):
                return cand
    return None


class EngineEvent:
    __slots__ = ("kind", "data")

    def __init__(self, kind, data):
        self.kind, self.data = kind, data

    def __repr__(self):
        return f"EngineEvent({self.kind}, {self.data})"


class UCIClient:
    def __init__(self, path: str):
        self.path = path
        self.proc: subprocess.Popen | None = None
        self.q: queue.Queue[EngineEvent] = queue.Queue()
        self._reader: threading.Thread | None = None
        self.alive = False
        self.id_name = os.path.basename(path)

    # ------------------------------------------------------------ lifecycle
    def start(self) -> bool:
        if self.alive:
            return True
        try:
            self.proc = subprocess.Popen(
                [self.path], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT, text=True, bufsize=1,
                cwd=os.path.dirname(os.path.abspath(self.path)))
        except OSError as exc:
            self.q.put(EngineEvent("error", f"could not start engine: {exc}"))
            return False
        self.alive = True
        self._reader = threading.Thread(target=self._read_loop, daemon=True)
        self._reader.start()
        self.send("uci")
        return True

    def _read_loop(self):
        assert self.proc and self.proc.stdout
        try:
            for raw in self.proc.stdout:
                line = raw.strip()
                if not line:
                    continue
                ev = self._parse(line)
                if ev:
                    self.q.put(ev)
        except Exception as exc:                               # noqa: BLE001
            self.q.put(EngineEvent("error", f"reader died: {exc}"))
        self.q.put(EngineEvent("engine_exited", None))
        self.alive = False

    @staticmethod
    def _parse(line: str) -> EngineEvent | None:
        if line.startswith("info string"):
            return EngineEvent("log", line[len("info string"):].strip())
        if line.startswith("info depth"):
            parts = line.split()
            info = {"raw": line}
            try:
                info["depth"] = int(parts[parts.index("depth") + 1])
                if "seldepth" in parts:
                    info["seldepth"] = int(parts[parts.index("seldepth") + 1])
                if "multipv" in parts:
                    info["multipv"] = int(parts[parts.index("multipv") + 1])
                if "score" in parts:
                    i = parts.index("score")
                    if parts[i + 1] == "cp":
                        info["score"] = ("cp", int(parts[i + 2]))
                    elif parts[i + 1] == "mate":
                        info["score"] = ("mate", int(parts[i + 2]))
                if "nodes" in parts:
                    info["nodes"] = int(parts[parts.index("nodes") + 1])
                if "nps" in parts:
                    info["nps"] = int(parts[parts.index("nps") + 1])
                if "time" in parts:
                    info["time"] = int(parts[parts.index("time") + 1])
                if "pv" in parts:
                    info["pv"] = parts[parts.index("pv") + 1:]
            except (ValueError, IndexError):
                pass
            return EngineEvent("info", info)
        if line.startswith("bestmove"):
            parts = line.split()
            bm = parts[1] if len(parts) > 1 else "0000"
            ponder = None
            if "ponder" in parts and parts.index("ponder") + 1 < len(parts):
                ponder = parts[parts.index("ponder") + 1]
            return EngineEvent("bestmove", {"move": bm, "ponder": ponder})
        if line == "readyok":
            return EngineEvent("readyok", None)
        if line == "uciok":
            return EngineEvent("uciok", None)
        if line.startswith("option name"):
            return EngineEvent("option", line[len("option name "):])
        if line.startswith("id name"):
            return EngineEvent("id", line[len("id name"):].strip())
        return EngineEvent("raw", line)

    # ---------------------------------------------------------------- verbs
    def send(self, cmd: str):
        if not self.alive or not self.proc or not self.proc.stdin:
            return
        try:
            self.proc.stdin.write(cmd + "\n")
            self.proc.stdin.flush()
        except (BrokenPipeError, OSError):
            self.q.put(EngineEvent("engine_exited", None))
            self.alive = False

    def set_option(self, name: str, value):
        self.send(f"setoption name {name} value {value}")

    def new_game(self):
        self.send("ucinewgame")

    def set_position(self, fen: str, moves=()):
        cmd = "position startpos" if fen in ("startpos", "") else f"position fen {fen}"
        if moves:
            cmd += " moves " + " ".join(moves)
        self.send(cmd)

    def go(self, *, depth=None, movetime=None, wtime=None, btime=None,
           winc=0, binc=0, movestogo=None, infinite=False):
        cmd = "go"
        if infinite:
            cmd += " infinite"
        if depth:
            cmd += f" depth {depth}"
        if movetime:
            cmd += f" movetime {int(movetime)}"
        if wtime is not None:
            cmd += f" wtime {int(wtime)} btime {int(btime)} winc {int(winc)} binc {int(binc)}"
        if movestogo:
            cmd += f" movestogo {movestogo}"
        self.send(cmd)

    def stop(self):
        if self.alive:
            self.send("stop")

    def quit(self, timeout: float = 4.0):
        """Clean shutdown: stop any search, send quit, wait, kill if stuck."""
        if not self.alive:
            return
        self.stop()
        self.send("quit")
        try:
            self.proc.wait(timeout=timeout)
        except Exception:
            try:
                self.proc.kill()
            except Exception:
                pass
        self.alive = False

    # events are consumed by the GUI with poll()
    def poll(self):
        """Return list of pending EngineEvent."""
        out = []
        try:
            while True:
                out.append(self.q.get_nowait())
        except queue.Empty:
            return out
