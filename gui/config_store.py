"""
config_store.py - GUI configuration persistence for Veltrix 1.0.

Stores everything the user can customize (theme, board size, coordinates,
flipping, highlights, options, engine path, time control) as JSON in the
user's config directory:

    Windows : %APPDATA%\\Veltrix\\config.json
    other   : ~/.config/veltrix/config.json
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field, asdict


def config_dir() -> str:
    if os.name == "nt":
        root = os.environ.get("APPDATA", os.path.expanduser("~"))
        return os.path.join(root, "Veltrix")
    root = os.environ.get("XDG_CONFIG_HOME", os.path.expanduser("~/.config"))
    return os.path.join(root, "veltrix")


CONFIG_PATH = os.path.join(config_dir(), "config.json")

PRESET_TIME_CONTROLS = [
    ("1 min bullet", 1, 0), ("1+1 bullet", 1, 1),
    ("3 min blitz", 3, 0), ("3+2 blitz", 3, 2),
    ("5 min blitz", 5, 0), ("5+3 blitz", 5, 3),
    ("10 min rapid", 10, 0), ("10+5 rapid", 10, 5),
    ("15+10 rapid", 15, 10), ("30 min classical", 30, 0),
    ("unlimited", None, None), ("custom…", "custom", "custom"),
]


@dataclass
class Config:
    engine_path: str = ""               # empty = auto-detect
    limit_strength: bool = False
    engine_elo: int = 2600
    multipv: int = 1
    hash_mb: int = 64
    threads: int = 1
    move_time_ms: int = 500             # engine move time for "unlimited/very fast" modes
    time_control: tuple = ("10 min rapid", 10, 0)
    # white/black can have individual base+inc when custom
    custom_minutes_white: float = 5.0
    custom_inc_white: float = 2.0
    custom_minutes_black: float = 5.0
    custom_inc_black: float = 2.0
    theme: str = "Classic"
    light_sq: str = "#f0d9b5"
    dark_sq: str = "#b58863"
    board_size: int = 480
    show_coords: bool = True
    flip_board: bool = False
    highlight_last_move: bool = True
    highlight_check: bool = True
    highlight_legal_targets: bool = True
    show_captured: bool = True
    show_engine_lines: bool = True
    animation_ms: int = 120
    window_geometry: str = "1100x640"

    def to_json(self) -> str:
        d = asdict(self)
        d["time_control"] = list(self.time_control)
        return json.dumps(d, indent=2)

    @staticmethod
    def from_dict(d: dict) -> "Config":
        cfg = Config()
        for k, v in d.items():
            if hasattr(cfg, k):
                setattr(cfg, k, v)
        cfg.time_control = tuple(cfg.time_control)
        return cfg

    @staticmethod
    def load() -> "Config":
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                return Config.from_dict(json.load(f))
        except Exception:
            return Config()

    def save(self):
        try:
            os.makedirs(config_dir(), exist_ok=True)
            with open(CONFIG_PATH, "w", encoding="utf-8") as f:
                f.write(self.to_json())
        except Exception as exc:  # config saving must never crash the app
            print("could not save config:", exc)
