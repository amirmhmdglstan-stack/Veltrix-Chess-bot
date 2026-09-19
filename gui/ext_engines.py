"""
ext_engines.py - external UCI engine registry + Stockfish integration.

PART 2/3 of the spec:
* Stockfish is an OPTIONAL external opponent: auto-detected if present,
  fully manual path config, remembered between runs, and the app behaves
  identically (never crashes, no dead menu entries) when it is absent.
* A generic registry keeps any number of external UCI engines with a
  name, executable path, enabled flag and a map of option values the user
  configured. Options are not hardcoded per engine: they are READ from
  the engine (`uci` -> `option name ...` lines) when it is registered or
  inspected, so any UCI conformant engine works, including Stockfish's
  ever-changing option list. Nothing is ever downloaded automatically.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from dataclasses import dataclass, field, asdict

STOCKFISH_NAMES = ("stockfish", "stockfish.exe", "stockfish-windows-x86-64")


# ------------------------------------------------------------------ datatypes
@dataclass
class EngineOptionSpec:
    """One option as the ENGINE advertises it (uci 'option' line)."""
    name: str
    type: str = "string"           # check|spin|combo|string|button
    default: str = ""
    min: str = ""
    max: str = ""
    var: tuple = ()

    @property
    def summary(self) -> str:
        bits = [self.type]
        if self.default != "":
            bits.append(f"default {self.default}")
        if self.min or self.max:
            bits.append(f"[{self.min}..{self.max}]")
        return " ".join(bits)


@dataclass
class ExternalEngine:
    name: str
    path: str
    enabled: bool = True
    options: dict = field(default_factory=dict)   # user-set values, engine-quoted
    role: str = "engine"                          # "engine" | "stockfish"

    def to_json(self) -> dict:
        return asdict(self)


# ------------------------------------------------------------------ detection
def detect_stockfish(cfg) -> str:
    """Return a working Stockfish path or ''. Order: remembered setting,
    PATH lookup, a few conventional locations. No downloads, ever."""
    if cfg.stockfish_path and _runnable(cfg.stockfish_path):
        return cfg.stockfish_path
    for name in STOCKFISH_NAMES:
        found = shutil.which(name)
        if found and _runnable(found):
            cfg.stockfish_path = found
            return found
    for cand in (r"C:\\Program Files\\Stockfish\\stockfish.exe",
                 r"C:\\Stockfish\\stockfish.exe",
                 "/usr/local/bin/stockfish"):
        if _runnable(cand):
            cfg.stockfish_path = cand
            return cand
    return ""


def _runnable(path: str) -> bool:
    try:
        p = subprocess.Popen([path], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                             stderr=subprocess.DEVNULL, text=True)
        p.stdin.write("uci\nisready\nquit\n")
        p.stdin.flush()
        out, _ = p.communicate(timeout=8)
        return "uciok" in out
    except (OSError, subprocess.SubprocessError, ValueError):
        return False


def probe(path: str, timeout: float = 8.0):
    """Hand the engine 'uci' and return (id_name, [EngineOptionSpec,...]).

    Returns (None, []) for anything that fails to conform; callers turn that
    into a friendly error, not a crash.
    """
    if not path:
        return None, []
    try:
        p = subprocess.Popen([path], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                             stderr=subprocess.DEVNULL, text=True, bufsize=1)
    except (OSError, ValueError):
        return None, []
    name, specs, seen_ok = None, [], False
    try:
        p.stdin.write("uci\n")
        p.stdin.flush()
        import time
        t0 = time.time()
        buf = ""
        while time.time() - t0 < timeout and not seen_ok:
            ch = p.stdout.read(1)
            if not ch:
                break
            buf += ch
            if ch == "\n":
                line, buf = buf.strip(), ""
                if line.startswith("id name"):
                    name = line[len("id name"):].strip()
                elif line.startswith("option name "):
                    spec = _parse_option(line)
                    if spec:
                        specs.append(spec)
                elif line == "uciok":
                    seen_ok = True
    except (OSError, ValueError):
        pass
    try:
        p.stdin.write("quit\n")
        p.stdin.flush()
        p.wait(timeout=3)
    except (OSError, subprocess.SubprocessError, ValueError):
        p.kill()
    return (name, specs) if seen_ok else (None, [])


def _parse_option(line: str):
    # UCI: option name X type check default true
    #      option name MultiPV type spin default 1 min 1 max 500
    #      option name Threads type spin ...
    #      option name EvalFile type string default <empty>
    try:
        rest = line[len("option name "):]
        parts = rest.split()
        ti = parts.index("type")
        name = " ".join(parts[:ti])
        spec = EngineOptionSpec(name=name, type=parts[ti + 1])
        i = ti + 2
        while i < len(parts):
            if parts[i] == "default" and i + 1 < len(parts):
                spec.default = parts[i + 1]
                i += 2
            elif parts[i] == "min" and i + 1 < len(parts):
                spec.min = parts[i + 1]
                i += 2
            elif parts[i] == "max" and i + 1 < len(parts):
                spec.max = parts[i + 1]
                i += 2
            elif parts[i] == "var" and i + 1 < len(parts):
                spec.var = spec.var + (parts[i + 1],)
                i += 2
            else:
                i += 1
        return spec
    except (ValueError, IndexError):
        return None


# ------------------------------------------------------------------ registry
class EngineRegistry:
    """Mutable view of Config.external_engines with probing helpers."""

    def __init__(self, cfg):
        self.cfg = cfg
        if getattr(cfg, "external_engines", None) is None:
            cfg.external_engines = []

    def list(self) -> list[ExternalEngine]:
        out = []
        for d in self.cfg.external_engines or []:
            try:
                out.append(ExternalEngine(**{k: d[k] for k in
                                             ("name", "path", "enabled",
                                              "options", "role")
                                             if k in d}))
            except (TypeError, KeyError):
                continue
        return out

    def save_entry(self, eng: ExternalEngine):
        entries = [ExternalEngine(**{k: d[k] for k in
                                     ("name", "path", "enabled", "options", "role")
                                     if k in d})
                   for d in (self.cfg.external_engines or [])]
        entries = [e for e in entries if e.name != eng.name]
        entries.append(eng)
        self.cfg.external_engines = [e.to_json() for e in entries]

    def remove(self, name: str):
        self.cfg.external_engines = [
            d for d in (self.cfg.external_engines or []) if d.get("name") != name]

    def add_probed(self, path: str, role: str = "engine"):
        """Friendly add/refresh: probe, refuse nonengines, remember."""
        name, specs = probe(path)
        if not name:
            return None, f"'{path}' did not answer with a UCI id - " \
                         "is it really a UCI chess engine?"
        cur = {e.name: e for e in self.list()}
        base = cur.get(name)
        eng = ExternalEngine(name=name, path=path,
                             enabled=base.enabled if base else True,
                             options=base.options if base else {},
                             role=role or (base.role if base else "engine"))
        self.save_entry(eng)
        return (eng, specs), None

    def stockfish(self) -> ExternalEngine | None:
        if not self.cfg.stockfish_path:
            return None
        for e in self.list():
            if e.role == "stockfish" or e.path == self.cfg.stockfish_path:
                return e
        # remembered but not yet registered: probe now (cheap, cached by OS)
        if not _runnable(self.cfg.stockfish_path):
            return None
        res, _err = self.add_probed(self.cfg.stockfish_path, role="stockfish")
        return res[0] if res else None

    def playable(self) -> list[ExternalEngine]:
        return [e for e in self.list() if e.enabled and _runnable(e.path)]
