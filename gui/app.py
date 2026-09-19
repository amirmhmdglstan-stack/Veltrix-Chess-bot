"""
app.py - Veltrix 1.0 chess GUI application (tkinter).

The GUI owns game flow, clocks, rendering and UCI plumbing only. All chess
rules come from chesslib.py and all calculation comes from the external
engine process - the GUI never evaluates or searches positions itself.
"""
from __future__ import annotations

import os
import time
import random
import sys
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog, ttk

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from chesslib import Board, Move, STARTPOS_FEN, game_pgn, sq_name, parse_sq   # noqa: E402
import config_store                                                          # noqa: E402
from config_store import Config, PRESET_TIME_CONTROLS                        # noqa: E402
from engine_client import UCIClient, find_engine                             # noqa: E402
from dialogs import PromotionDialog, TimeControlDialog, ColorsDialog, \
    EngineSettingsDialog                                                    # noqa: E402
from board_widget import BoardCanvas, UNICODE_PIECES                         # noqa: E402
from theme import THEMES                                                     # noqa: E402
from game_state import GameState                                             # noqa: E402
import models                                                                # noqa: E402
import ext_engines                                                           # noqa: E402
import sounds                                                                # noqa: E402
import threading                                                             # noqa: E402
import analyzer                                                              # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
VERSION = "Veltrix 1.0"


def fmt_clock(sec: float) -> str:
    sec = max(0.0, sec)
    m = int(sec // 60)
    s = sec - m * 60
    if m >= 1:
        return f"{m}:{s:04.1f}" if s < 10 else f"{m}:{s:02.0f}"
    return f"{s:.1f}"


class VeltrixApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.cfg = Config.load()
        root.title(VERSION + " - chess gui")
        try:
            root.geometry(self.cfg.window_geometry)
        except tk.TclError:
            pass

        # ---------------- model (single authoritative state) ----------------
        self.initial_fen = STARTPOS_FEN
        self.state = GameState(STARTPOS_FEN)
        self._go_serial: dict = {}      # engine client -> state serial at 'go'
        self.mode = "human_vs_engine"   # or "engine_vs_engine" / "human_vs_human"
        self.human_color = "w"
        self.engine_thinking = False
        self.analyzing = False
        self.clocks = {"w": 600.0, "b": 600.0}
        self.incs = {"w": 0.0, "b": 0.0}
        self.clock_active = False
        self.tc_kind = "preset"
        self.tc_name = "10 min rapid"
        self._tick_job = None
        self.game_started_at = None

        # ---------------- engine ----------------
        self.engine: UCIClient | None = None
        self.engine2: UCIClient | None = None
        self.engine_path = self.cfg.engine_path or find_engine(HERE) or ""
        self.model = models.profile(self.cfg.model
                                    if self.cfg.model in models.ALL else "High")
        self.registry = ext_engines.EngineRegistry(self.cfg)
        self.soundboard = sounds.SoundBoard(self.cfg)
        try:
            ext_engines.detect_stockfish(self.cfg)   # optional, never fatal
        except Exception:
            pass
        if not str(self.cfg.opponent_key or "").startswith("engine:"):
            self.cfg.opponent_key = "model:" + self.model.key
        self._connect_engine()

        self.TIME_CONTROLS = PRESET_TIME_CONTROLS
        self.analysis = {"report": None, "running": False,
                         "cancel": threading.Event(), "worker": None}
        # ---------------- UI ----------------
        self._build_menu()          # native menubar (fallback & shortcuts)
        self._build_layout()        # the game screen (frame)
        self._build_menu_screen()   # the main menu (frame)
        self._build_config_screen() # the new-game configuration (frame)
        self._build_analysis_screen() # post-game analysis (frame, PART 12)
        self.apply_cfg_visual()
        self.new_game(keep_setup=True, silent=True)
        self.show_frame("menu")
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)
        self._tick()

    # ---------------- state delegations (single source of truth lives in
    # self.state; these exist so the rest of the app/tests stay readable)
    @property
    def board(self) -> Board:
        return self.state.board

    @property
    def moves(self) -> list:
        # live game only - the abandoned redo trail is GameState's business
        return self.state.hist_moves()

    @property
    def sans(self) -> list:
        return self.state.hist_sans()

    @sans.setter
    def sans(self, v):
        self.state.set_live_sans(v)

    @property
    def view(self) -> int:
        return self.state.cursor

    @view.setter
    def view(self, v: int):
        self.state.cursor = v

    @property
    def result(self):
        return self.state.result

    @result.setter
    def result(self, v):
        self.state.result = v

    # ============================================================ engine
    def _connect_engine(self):
        if self.engine:
            self.engine.quit()
        self.engine = UCIClient(self.engine_path) if self.engine_path else None
        if self.engine and self.engine.start():
            self._apply_engine_options(self.engine)
        self.engine_thinking = False

    @property
    def opponent_uses_external(self) -> bool:
        return str(self.cfg.opponent_key or "").startswith("engine:")

    def opponent_name(self) -> str:
        if self.opponent_uses_external:
            return self.cfg.opponent_key[len("engine:"):]
        return self.model.key

    def set_opponent(self, key: str, friendly: str = ""):
        """Central opponent switch: 'model:<key>' or 'engine:<name>'."""
        self.cfg.opponent_key = key
        if key.startswith("model:"):
            self.set_model(key[len("model:"):])
        else:
            self.disconnect_ext_client()
            self.status(f"opponent: external engine {friendly or key[len('engine:'):]}")

    def _ext_engine_entry(self):
        if not self.opponent_uses_external:
            return None
        name = self.cfg.opponent_key[len("engine:"):]
        for e in self.registry.list():
            if e.name == name and e.enabled:
                return e
        return None

    def ext_client(self, ent):
        """Live client for the chosen external engine (re)spawned on change."""
        cur = getattr(self, "_ext_client", None)
        if cur and getattr(cur, "_ext_path", None) != ent.path:
            self.disconnect_ext_client()
            cur = None
        if cur is None:
            c = UCIClient(ent.path)
            if not c.start():
                self.status(f"could not start {ent.name}")
                return None
            c._ext_path = ent.path
            self._apply_engine_options(c)
            for k, v in (ent.options or {}).items():
                c.set_option(k, v)
            self._ext_client = c
        return self._ext_client

    def disconnect_ext_client(self):
        c = getattr(self, "_ext_client", None)
        if c:
            try:
                c.quit()
            except Exception:
                pass
            self._ext_client = None

    def set_model(self, key: str):
        if key in models.ALL:
            self.model = models.profile(key)
            self.cfg.model = key
            self.status(f"opponent model: {self.model.key} - {self.model.budget_summary()}")

    def _apply_engine_options(self, client: UCIClient):
        if not client:
            return
        client.set_option("Hash", self.cfg.hash_mb)
        threads = self.cfg.threads
        if threads <= 0:  # zero-config: auto-detect (capped so the GUI stays snappy)
            threads = max(1, min(4, (os.cpu_count() or 2)))
        client.set_option("Threads", threads)
        client.set_option("MultiPV", self.cfg.multipv if self.cfg.show_engine_lines else 1)
        models.apply_options(client, self.model, use_book=True)
        if self.cfg.limit_strength:
            client.set_option("UCI_LimitStrength", "true")
            client.set_option("UCI_Elo", self.cfg.engine_elo)
        else:
            client.set_option("UCI_LimitStrength", "false")

    def engine_color(self):
        if self.mode == "engine_vs_engine":
            return None
        return "b" if self.human_color == "w" else "w"

    def side_is_engine(self, color):
        if self.mode == "engine_vs_engine":
            return True
        if self.mode == "human_vs_engine":
            return color == self.engine_color()
        return False

    # ============================================================ UI build
    def _build_menu(self):
        m = tk.Menu(self.root)
        g = tk.Menu(m, tearoff=0)
        g.add_command(label="New game vs engine…", accelerator="Ctrl+N",
                      command=self.dialog_new_game)
        g.add_command(label="Engine vs Engine", command=self.start_eve)
        g.add_command(label="Stop Engine vs Engine", command=self.stop_eve)
        g.add_command(label="Human vs Human", command=self.start_hvh)
        g.add_separator()
        self.flip_var = tk.BooleanVar(value=self.cfg.flip_board)
        g.add_checkbutton(label="Flip board", variable=self.flip_var,
                          command=self.toggle_flip)
        g.add_separator()
        g.add_command(label="Quit", command=self.on_close)
        m.add_cascade(label="Game", menu=g)

        p = tk.Menu(m, tearoff=0)
        p.add_command(label="Copy FEN", command=self.copy_fen)
        p.add_command(label="Paste FEN…", command=self.paste_fen)
        p.add_command(label="Set up start position", command=lambda: self.set_initial(STARTPOS_FEN))
        m.add_cascade(label="Position", menu=p)

        pgn = tk.Menu(m, tearoff=0)
        pgn.add_command(label="Save game as PGN…", command=self.save_pgn)
        pgn.add_command(label="Load game from PGN…", command=self.load_pgn)
        m.add_cascade(label="PGN", menu=pgn)

        e = tk.Menu(m, tearoff=0)
        e.add_command(label="Engine path…", command=self.pick_engine)
        e.add_command(label="Engine options…", command=self.dialog_engine_options)
        e.add_command(label="Analyze this position (toggle)",
                      command=self.toggle_analysis)
        m.add_cascade(label="Engine", menu=e)

        v = tk.Menu(m, tearoff=0)
        v.add_command(label="Colors & theme…", command=self.dialog_colors)
        v.add_command(label="Board size…", command=self.dialog_size)
        self.coords_var = tk.BooleanVar(value=self.cfg.show_coords)
        v.add_checkbutton(label="Coordinates", variable=self.coords_var,
                          command=self.toggle_coords)
        self.hl_last_var = tk.BooleanVar(value=self.cfg.highlight_last_move)
        v.add_checkbutton(label="Highlight last move", variable=self.hl_last_var,
                          command=self.apply_hl_options)
        self.hl_check_var = tk.BooleanVar(value=self.cfg.highlight_check)
        v.add_checkbutton(label="Highlight check", variable=self.hl_check_var,
                          command=self.apply_hl_options)
        self.hl_targets_var = tk.BooleanVar(value=self.cfg.highlight_legal_targets)
        v.add_checkbutton(label="Highlight legal targets", variable=self.hl_targets_var,
                          command=self.apply_hl_options)
        self.elines_var = tk.BooleanVar(value=self.cfg.show_engine_lines)
        v.add_checkbutton(label="Show engine lines", variable=self.elines_var,
                          command=self.apply_engine_lines_toggle)
        m.add_cascade(label="View", menu=v)

        h = tk.Menu(m, tearoff=0)
        h.add_command(label="Tutorial", command=self.open_tutorial)
        h.add_command(label="About", command=lambda: messagebox.showinfo(
            "About", VERSION + "\nUCI chess engine + GUI\nsee docs/TUTORIAL.md"))
        m.add_cascade(label="Help", menu=h)
        self.root.config(menu=m)

    def _build_layout(self):
        self.game_frame = ttk.Frame(self.root)
        main = ttk.Frame(self.game_frame)
        main.pack(fill=tk.BOTH, expand=True)

        left = ttk.Frame(main, padding=6)
        left.pack(side=tk.LEFT, fill=tk.Y)
        self.lbl_top_player = ttk.Label(left, text="Black", font=("TkDefaultFont", 11, "bold"))
        self.lbl_top_player.pack(anchor="w")
        self.lbl_top_clock = ttk.Label(left, text="10:00", font=("TkDefaultFont", 16))
        self.lbl_top_clock.pack(anchor="w", pady=(0, 4))
        self.lbl_top_captured = tk.Label(left, text="", font=("Segoe UI Symbol", 13),
                                         justify=tk.LEFT, anchor="w", wraplength=140)
        self.lbl_top_captured.pack(anchor="w", pady=(0, 10))
        self.lbl_bottom_captured = tk.Label(left, text="", font=("Segoe UI Symbol", 13),
                                            justify=tk.LEFT, anchor="w", wraplength=140)
        self.lbl_bottom_captured.pack(anchor="w", side=tk.BOTTOM, pady=(10, 0))
        self.lbl_bottom_player = ttk.Label(left, text="White", font=("TkDefaultFont", 11, "bold"))
        self.lbl_bottom_player.pack(anchor="w", side=tk.BOTTOM)
        self.lbl_bottom_clock = ttk.Label(left, text="10:00", font=("TkDefaultFont", 16))
        self.lbl_bottom_clock.pack(anchor="w", side=tk.BOTTOM, pady=(4, 0))

        center = ttk.Frame(main, padding=4)
        center.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.canvas = BoardCanvas(center, size=self.cfg.board_size)
        self.canvas.pack(anchor="center", expand=True)
        self.canvas.on_square_click = self.on_square_click
        self.canvas.on_right_click = self.canvas.deselect

        btns = ttk.Frame(center, padding=2)
        btns.pack(fill=tk.X)
        for text, cmd, in (("◀◀", self.undo_all_plies), ("◀", lambda: self.undo_plies(1)),
                           ("▶", lambda: self.redo_plies(1)), ("▶▶", self.redo_all_plies),
                           ("Flip", self.toggle_flip_menu)):
            ttk.Button(btns, text=text, width=5, command=cmd).pack(side=tk.LEFT, padx=2)
        ttk.Button(btns, text="Resign", width=7, command=self.resign).pack(side=tk.RIGHT, padx=2)
        ttk.Button(btns, text="New", width=6, command=self.dialog_new_game).pack(side=tk.RIGHT, padx=2)
        ttk.Button(btns, text="Menu", width=6, command=self.menu_button).pack(side=tk.RIGHT, padx=2)

        right = ttk.Frame(main, padding=6)
        right.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True)
        ttk.Label(right, text="Moves", font=("TkDefaultFont", 10, "bold")).pack(anchor="w")
        mv_frame = ttk.Frame(right)
        mv_frame.pack(fill=tk.BOTH, expand=True)
        self.moves_list = tk.Text(mv_frame, width=34, height=16, state="disabled",
                                  wrap="word", cursor="arrow")
        sb = ttk.Scrollbar(mv_frame, command=self.moves_list.yview)
        self.moves_list.configure(yscrollcommand=sb.set)
        self.moves_list.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        sb.pack(side=tk.RIGHT, fill=tk.Y)
        self.moves_list.bind("<Button-1>", self.on_moves_click)

        ttk.Label(right, text="Engine", font=("TkDefaultFont", 10, "bold")).pack(
            anchor="w", pady=(6, 0))
        self.engine_box = tk.Text(right, width=34, height=7, state="disabled",
                                  wrap="word", font=("TkFixedFont", 9))
        self.engine_box.pack(fill=tk.X)
        self.status_var = tk.StringVar(value="ready")
        ttk.Label(right, textvariable=self.status_var, wraplength=300).pack(
            anchor="w", pady=(6, 0))
        self.tc_lbl = ttk.Label(right, text="")
        self.tc_lbl.pack(anchor="w")
        self.lbl_model = ttk.Label(right, text="", foreground="#5a6a7a")
        self.lbl_model.pack(anchor="w")

    # ===================================================== frame navigation
    def show_frame(self, name: str):
        """Top-level navigation between Menu / Config / Game screens."""
        for frame in (getattr(self, "menu_frame", None),
                      getattr(self, "config_frame", None),
                      getattr(self, "game_frame", None),
                      getattr(self, "analysis_frame", None)):
            if frame is not None:
                frame.pack_forget()
        if name == "menu":
            self._refresh_menu()
            self.menu_frame.pack(fill=tk.BOTH, expand=True)
        elif name == "config":
            self.config_frame.pack(fill=tk.BOTH, expand=True)
        elif name == "analysis":
            self.analysis_frame.pack(fill=tk.BOTH, expand=True)
        else:
            self.game_frame.pack(fill=tk.BOTH, expand=True)
        self._active_frame = name

    def _build_menu_screen(self):
        self.menu_frame = ttk.Frame(self.root, padding=28)
        brand = ttk.Frame(self.menu_frame)
        brand.pack(pady=(30, 24))
        tk.Label(brand, text="\u265e", font=("Segoe UI Symbol", 44)).pack()
        ttk.Label(brand, text="VELTRIX",
                  font=("TkDefaultFont", 26, "bold")).pack()
        ttk.Label(brand, text="Chess, honestly. Play, learn, improve.",
                  font=("TkDefaultFont", 11)).pack(pady=(2, 0))
        col = ttk.Frame(self.menu_frame)
        col.pack()
        self._menu_btns = {}
        entries = [
            ("continue", "Continue", self.menu_continue),
            ("new", "New Game", lambda: self.show_frame("config")),
            ("analyze", "Analyze", self.menu_analyze),
            ("settings", "Settings", self.dialog_settings),
            ("engines", "Engines", self.dialog_engines),
            ("about", "About", self.dialog_about),
            ("quit", "Quit", self.on_close),
        ]
        for i, (key, text, cmd) in enumerate(entries):
            b = ttk.Button(col, text=text, command=cmd,
                           width=22 if key != "continue" else 24)
            b.pack(pady=4)
            self._menu_btns[key] = b

    def _build_config_screen(self):
        """PART-6 game-configuration screen."""
        f = ttk.Frame(self.root, padding=24)
        self.config_frame = f
        ttk.Label(f, text="New Game", font=("TkDefaultFont", 18, "bold")).pack(
            anchor="w", pady=(10, 12))
        grid = ttk.Frame(f)
        grid.pack(anchor="w")

        ttk.Label(grid, text="Play as:").grid(row=0, column=0, sticky="w", pady=4)
        self.cfg_side_var = tk.StringVar(value="w")
        sf = ttk.Frame(grid)
        sf.grid(row=0, column=1, sticky="w")
        for t, v in (("White", "w"), ("Black", "b"), ("Random", "r")):
            ttk.Radiobutton(sf, text=t, value=v, variable=self.cfg_side_var
                            ).pack(side=tk.LEFT, padx=4)

        ttk.Label(grid, text="Opponent:").grid(row=1, column=0, sticky="w", pady=4)
        self.cfg_opp_var = tk.StringVar(value=self.cfg.opponent_key)
        self.cfg_opp_cb = ttk.Combobox(grid, textvariable=self.cfg_opp_var,
                                       state="readonly", width=20,
                                       values=self._opponent_choices())
        self.cfg_opp_cb.grid(row=1, column=1, sticky="w", padx=4)
        ttk.Button(grid, text="ⓘ", width=3,
                   command=lambda: self.show_opponent_info(self.cfg_opp_var.get())
                   ).grid(row=1, column=2, padx=2)
        ttk.Button(grid, text="Engines…",
                   command=self.dialog_engines).grid(row=1, column=3, padx=6)

        ttk.Label(grid, text="Time control:").grid(row=2, column=0, sticky="w",
                                                    pady=4)
        self.cfg_tc_var = tk.StringVar(value=self.cfg.time_control[0])
        tc_names = [n for n, _b, _i in self.TIME_CONTROLS]
        ttk.Combobox(grid, textvariable=self.cfg_tc_var, state="readonly",
                     values=tc_names, width=18).grid(row=2, column=1, sticky="w",
                                                     padx=4)

        ttk.Label(grid, text="Position FEN (optional):").grid(row=3, column=0,
                                                               sticky="w", pady=4)
        self.cfg_fen_var = tk.StringVar(value="")
        ttk.Entry(grid, textvariable=self.cfg_fen_var, width=44).grid(
            row=3, column=1, columnspan=3, sticky="w", padx=4)

        self.cfg_book_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(grid, text="Veltrix uses its opening book",
                        variable=self.cfg_book_var).grid(row=4, column=1,
                                                         sticky="w", pady=4)

        row = ttk.Frame(f)
        row.pack(anchor="w", pady=18)
        ttk.Button(row, text="Start Game", command=self._config_start).pack(
            side=tk.LEFT)
        ttk.Button(row, text="Back", command=lambda: self.show_frame("menu")
                   ).pack(side=tk.LEFT, padx=8)

    def _opponent_choices(self):
        vals = ["model:" + k for k in models.menu_choices()]
        vals += ["engine:" + e.name for e in self.registry.playable()]
        return vals

    def _config_start(self):
        side = self.cfg_side_var.get()
        self.set_opponent(self.cfg_opp_var.get())
        for n, b, i in self.TIME_CONTROLS:
            if n == self.cfg_tc_var.get():
                self.cfg.time_control = (n, b, i)
                break
        fen = self.cfg_fen_var.get().strip()
        if fen:
            try:
                Board(fen)   # validates
            except ValueError:
                self.status("invalid FEN - starting from the normal position")
                fen = ""
        if self.engine:
            self.engine.set_option("UseBook", "true" if self.cfg_book_var.get()
                                   else "false")
        self.cfg.save()
        self.initial_fen = fen or STARTPOS_FEN
        if side == "r":
            side = random.choice("wb")
        self.human_color = side
        self.mode = "human_vs_engine"
        self.new_game(side=side)
        self.show_frame("game")

    def _refresh_menu(self):
        can_continue = (self.state.moves != [] and not self.result) or \
            bool(self.cfg.resume_game)
        st = "normal" if can_continue else "disabled"
        try:
            self._menu_btns["continue"].configure(state=st)
        except Exception:
            pass

    def menu_continue(self):
        """Back to the game screen; restore persisted game if not in memory."""
        if self.state.moves == [] and self.cfg.resume_game:
            self.restore_saved_game()
        self.show_frame("game")

    def menu_analyze(self):
        if not self.state.moves:
            self.status("no game to analyze yet - play or load one first")
            self.show_frame("game")
            return
        self._analysis_refresh_info()
        self.show_frame("analysis")

    # -------------------------------------------------- resume (PART 5)
    def save_resume_state(self):
        """Persist the in-progress game so the next launch offers Continue."""
        if not self.state.moves or self.result:
            self.cfg.resume_game = None
            return
        self.cfg.resume_game = {
            "initial_fen": self.initial_fen,
            "moves": self.state.hist_uci(),
            "sans": self.state.hist_sans(),
            "clocks": {k: (v if v != float("inf") else "inf")
                       for k, v in self.clocks.items()},
            "incs": self.incs,
            "opponent_key": self.cfg.opponent_key,
            "human_color": self.human_color,
            "mode": self.mode,
        }

    def restore_saved_game(self) -> bool:
        rg = self.cfg.resume_game
        if not rg:
            return False
        try:
            moves = []
            b = Board(rg["initial_fen"])
            for u in rg["moves"]:
                m = b.parse_uci(u)
                moves.append(m)
                b.push(m)
        except (ValueError, KeyError, TypeError):
            self.cfg.resume_game = None
            return False
        self.initial_fen = rg["initial_fen"]
        self.mode = rg.get("mode", "human_vs_engine")
        self.human_color = rg.get("human_color", "w")
        self.set_opponent(rg.get("opponent_key", "model:High"))
        self.state.reset(self.initial_fen)
        self.state.load_moves(moves, rg.get("sans") or [])
        self.clocks = {k: (float("inf") if v == "inf" else float(v))
                       for k, v in rg.get("clocks", {}).items()} or \
            {"w": float("inf"), "b": float("inf")}
        self.incs = rg.get("incs", {"w": 0, "b": 0})
        self.clock_active = self.clocks["w"] != float("inf")
        self.result = None
        self._sync_board_widget()
        self.move_list_update()
        self.status(f"resumed saved game ({len(rg['moves'])} plies)")
        self.maybe_engine_move()
        return True

    def dialog_engines(self):
        """External-engine registry manager: list/add/remove/enable/options;
        Stockfish row honours PART 2 (absent is fine, nothing downloads)."""
        dlg = tk.Toplevel(self.root)
        dlg.title("External engines")
        dlg.geometry("560x380")
        sf_path = self.cfg.stockfish_path
        sf_runs = ext_engines._runnable(sf_path) if sf_path else False
        tk.Label(dlg, text=("Stockfish: " + (sf_path if sf_runs
                 else "not found - use Browse to add it")),
                 justify="left").pack(anchor="w", padx=10, pady=6)
        row = tk.Frame(dlg)
        row.pack(fill="x", padx=10)
        tk.Button(row, text="Detect",
                  command=lambda: self._stockfish_detect(dlg)).pack(side="left")
        tk.Button(row, text="Browse…",
                  command=lambda: self._stockfish_browse(dlg)).pack(side="left",
                                                                    padx=6)
        tk.Label(dlg, text="Registered engines:").pack(anchor="w", padx=10,
                                                       pady=(10, 2))
        lb = tk.Listbox(dlg, height=6)
        lb.pack(fill="both", expand=True, padx=10)
        for e in self.registry.list():
            mark = "[on]" if e.enabled else "[off]"
            role = " (stockfish)" if e.role == "stockfish" else ""
            lb.insert("end", f"{mark} {e.name}{role} - {e.path}")
        brow = tk.Frame(dlg)
        brow.pack(fill="x", padx=10, pady=6)

        def _sel():
            sel = lb.curselection()
            ents = self.registry.list()
            return ents[sel[0]] if sel and sel[0] < len(ents) else None
        tk.Button(brow, text="Add…",
                  command=lambda: self._engine_add(dlg)).pack(side="left")
        tk.Button(brow, text="Toggle",
                  command=lambda: self._engine_toggle(dlg, _sel())).pack(
            side="left", padx=4)
        tk.Button(brow, text="Options…",
                  command=lambda: self._engine_options(dlg, _sel())).pack(
            side="left", padx=4)
        tk.Button(brow, text="Remove",
                  command=lambda: self._engine_remove(dlg, _sel())).pack(
            side="left", padx=4)
        tk.Button(dlg, text="Close", command=dlg.destroy).pack(pady=6)

    def _stockfish_detect(self, dlg):
        path = ext_engines.detect_stockfish(self.cfg)
        self.status("Stockfish detected: " + path if path
                    else "no Stockfish found on PATH or usual locations")
        dlg.destroy()
        self.dialog_engines()

    def _stockfish_browse(self, dlg):
        from tkinter import filedialog
        p = filedialog.askopenfilename(title="Choose Stockfish executable")
        if not p:
            return
        if not ext_engines._runnable(p):
            self.status(f"'{p}' did not start with the UCI handshake - ignored")
            return
        self.cfg.stockfish_path = p
        self.registry.add_probed(p, role="stockfish")
        self.status("Stockfish registered: " + p)
        dlg.destroy()
        self.dialog_engines()

    def _engine_add(self, dlg):
        from tkinter import filedialog
        p = filedialog.askopenfilename(title="Choose a UCI engine executable")
        if not p:
            return
        res, err = self.registry.add_probed(p)
        if err:
            self.status(err)
            return
        self.status(f"added engine {res[0].name}")
        dlg.destroy()
        self.dialog_engines()

    def _engine_toggle(self, dlg, ent):
        if ent:
            ent.enabled = not ent.enabled
            self.registry.save_entry(ent)
            self.disconnect_ext_client()
            dlg.destroy()
            self.dialog_engines()

    def _engine_remove(self, dlg, ent):
        if ent:
            self.registry.remove(ent.name)
            try:
                self.cfg.save()
            except Exception:
                pass
            dlg.destroy()
            self.dialog_engines()

    def _engine_options(self, dlg, ent):
        if not ent:
            return
        _id, specs = ext_engines.probe(ent.path)
        if not specs and _id is None:
            self.status(f"engine {ent.name} unreachable - options unknown")
            return
        ed = tk.Toplevel(dlg)
        ed.title(f"{ent.name} options")
        vars_ = {}
        for i, s in enumerate(specs):
            if s.type == "button":
                continue
            tk.Label(ed, text=s.name, anchor="w").grid(row=i, column=0,
                                                       sticky="w", padx=8, pady=2)
            v = tk.StringVar(value=str(ent.options.get(s.name, s.default)))
            tk.Entry(ed, textvariable=v, width=14).grid(row=i, column=1, padx=6)
            tk.Label(ed, text=s.summary, fg="#777").grid(row=i, column=2,
                                                         sticky="w")
            vars_[s.name] = v

        def _save():
            for k, v in vars_.items():
                if v.get():
                    ent.options[k] = v.get()
            self.registry.save_entry(ent)
            self.disconnect_ext_client()
            ed.destroy()

        tk.Button(ed, text="Save", command=_save).grid(row=len(specs), column=0,
                                                       pady=8)
        tk.Button(ed, text="Cancel", command=ed.destroy).grid(row=len(specs),
                                                              column=1)

    def dialog_settings(self):
        """PART-5 settings hub (modal preferences window)."""
        mb = tk.Toplevel(self.root)
        mb.title("Settings")
        mb.transient(self.root)

        f = ttk.Frame(mb, padding=16)
        f.pack(fill=tk.BOTH, expand=True)
        ttk.Label(f, text="Settings", font=("TkDefaultFont", 15, "bold")).pack(
            anchor="w", pady=(0, 10))

        # ---- presentation ------------------------------------------------
        pres = ttk.LabelFrame(f, text="board", padding=8)
        pres.pack(fill=tk.X, pady=4)
        ttk.Button(pres, text="Colors & theme\u2026",
                   command=self.dialog_colors).grid(row=0, column=0,
                                                    sticky="w", pady=2, padx=4)
        ttk.Button(pres, text="Board size\u2026",
                   command=self.dialog_size).grid(row=0, column=1,
                                                  sticky="w", pady=2, padx=4)
        ttk.Checkbutton(pres, text="highlight last move", variable=self.hl_last_var,
                        command=self.apply_hl_options).grid(row=1, column=0,
                                                            sticky="w", padx=4)
        ttk.Checkbutton(pres, text="highlight check", variable=self.hl_check_var,
                        command=self.apply_hl_options).grid(row=1, column=1,
                                                            sticky="w", padx=4)
        ttk.Checkbutton(pres, text="show legal targets", variable=self.hl_targets_var,
                        command=self.apply_hl_options).grid(row=2, column=0,
                                                            sticky="w", padx=4)

        anim_var = tk.BooleanVar(value=self.cfg.animations)
        def _anim():
            self.cfg.animations = bool(anim_var.get())
            self.apply_cfg_visual()
            self.cfg.save()
        ttk.Checkbutton(pres, text="piece-move animation", variable=anim_var,
                        command=_anim).grid(row=2, column=1, sticky="w", padx=4)

        # ---- sound (PART-10/11 toggles; engine for playback lands next) --
        snd = ttk.LabelFrame(f, text="sound", padding=8)
        snd.pack(fill=tk.X, pady=4)
        snd_var = tk.BooleanVar(value=self.cfg.sound_on)
        vol_var = tk.IntVar(value=self.cfg.sound_volume)
        def _snd():
            self.cfg.sound_on = bool(snd_var.get())
            self.cfg.sound_volume = max(0, min(100, int(vol_var.get())))
            self.cfg.save()
        ttk.Checkbutton(snd, text="play move sounds", variable=snd_var,
                        command=_snd).grid(row=0, column=0, sticky="w", padx=4)
        ttk.Scale(snd, from_=0, to=100, variable=vol_var,
                  command=lambda _v: _snd()).grid(row=0, column=1, sticky="ew",
                                                  padx=8)
        snd.columnconfigure(1, weight=1)

        # ---- engine / time -----------------------------------------------
        eng = ttk.LabelFrame(f, text="engine & time", padding=8)
        eng.pack(fill=tk.X, pady=4)
        ttk.Button(eng, text="Time control\u2026",
                   command=self.dialog_time_control).grid(row=0, column=0,
                                                          sticky="w", padx=4)
        ttk.Button(eng, text="Engine options\u2026",
                   command=self.dialog_engine_options).grid(row=1, column=0,
                                                            sticky="w", padx=4)
        ttk.Button(eng, text="Engines\u2026",
                   command=self.dialog_engines).grid(row=1, column=1,
                                                     sticky="w", padx=4)

        ttk.Button(f, text="Close", command=mb.destroy).pack(anchor="e", pady=8)

    def dialog_about(self):
        mb = tk.Toplevel(self.root)
        mb.title("About Veltrix")
        tk.Label(mb, text=(
            "Veltrix 1.0\n\nAn open chess engine and trainer built around the\n"
            "Veltrix C++ engine - honest play, honest evaluation, honest\n"
            "claims: what you see is what the code actually does.\n\n"
            "Levels and models change only real search budgets (positions\n"
            "per move), verified by engine-vs-engine matches in tools/.\n"
            "Veltrix never pretends to be other than it is."),
            justify="left", padx=16, pady=12).pack()
        tk.Button(mb, text="OK", command=mb.destroy).pack(pady=8)

    # ============================================================ visuals
    def apply_cfg_visual(self):
        light, dark = THEMES.get(self.cfg.theme, (self.cfg.light_sq, self.cfg.dark_sq))
        if self.cfg.light_sq and self.cfg.dark_sq:
            light, dark = self.cfg.light_sq, self.cfg.dark_sq
        self.canvas.light, self.canvas.dark = light, dark
        self.canvas.show_coords = self.cfg.show_coords
        self.canvas.flipped = self.cfg.flip_board
        self.canvas.animation_ms = self.cfg.animation_ms if self.cfg.animations else 0
        self.canvas.set_size(self.cfg.board_size)
        self.apply_hl_options()
        self.canvas.redraw()

    def apply_hl_options(self):
        self.cfg.highlight_last_move = self.hl_last_var.get()
        self.cfg.highlight_check = self.hl_check_var.get()
        self.cfg.highlight_legal_targets = self.hl_targets_var.get()
        self.canvas.highlight_last = self.cfg.highlight_last_move
        self.canvas.highlight_check = self.cfg.highlight_check
        self.canvas.highlight_targets = self.cfg.highlight_legal_targets
        self.canvas.redraw()

    def apply_engine_lines_toggle(self):
        self.cfg.show_engine_lines = self.elines_var.get()
        if self.engine:
            self._apply_engine_options(self.engine)
        self.engine_box_update()

    # ============================================================ game setup
    def current_tc_seconds(self):
        """((w_base, w_inc), (b_base, b_inc)) in seconds."""
        name, minutes, inc = self.cfg.time_control
        if minutes == "custom":
            return ((self.cfg.custom_minutes_white * 60, self.cfg.custom_inc_white),
                    (self.cfg.custom_minutes_black * 60, self.cfg.custom_inc_black))
        if minutes is None:  # unlimited
            return ((None, 0), (None, 0))
        return ((minutes * 60, inc), (minutes * 60, inc))

    def new_game(self, side="w", keep_setup=False, silent=False):
        if not keep_setup:
            self.initial_fen = self.current_fen_base()
        # reset state (single authoritative object)
        self.cancel_engine_search()
        self.state.reset(self.initial_fen)
        self._go_serial.clear()
        self.human_color = side
        (wb, wi), (bb, bi) = self.current_tc_seconds()
        self.clocks = {"w": wb if wb is not None else float("inf"),
                       "b": bb if bb is not None else float("inf")}
        self.incs = {"w": wi or 0, "b": bi or 0}
        self.clock_active = True
        if self.mode != "engine_vs_engine":
            self.mode = "human_vs_engine"
        if self.engine:
            self.engine.new_game()
        if self.engine2:
            self.engine2.new_game()
        self._sync_board_widget()
        self.move_list_update()
        if not silent:
            self.soundboard.play("start")
            self.status(f"new game - you are {'White' if side == 'w' else 'Black'}")
        self.maybe_engine_move()

    def current_fen_base(self):
        return self.initial_fen

    def set_initial(self, fen):
        self.initial_fen = fen
        self.new_game(side=self.human_color, keep_setup=True)

    def dialog_new_game(self):
        dlg = tk.Toplevel(self.root)
        dlg.title("New game")
        dlg.transient(self.root)
        dlg.grab_set()
        side_var = tk.StringVar(value="w")
        ttk.Label(dlg, text="Play as:").grid(row=0, column=0, padx=8, pady=8, sticky="w")
        for i, (t, v) in enumerate((("White", "w"), ("Black", "b"), ("Random", "r"))):
            ttk.Radiobutton(dlg, text=t, value=v, variable=side_var).grid(
                row=0, column=1 + i, padx=6)
        ttk.Label(dlg, text="Opponent:").grid(row=1, column=0, padx=8, sticky="w")
        opp_values = ["model:" + k for k in models.menu_choices()]
        opp_values += ["engine:" + e.name for e in self.registry.playable()]
        cur = self.cfg.opponent_key if self.cfg.opponent_key in opp_values \
            else "model:" + self.model.key
        model_var = tk.StringVar(value=cur)
        ttk.Combobox(dlg, textvariable=model_var, values=opp_values,
                     state="readonly", width=16).grid(row=1, column=1, columnspan=2,
                                                      padx=6, sticky="w")
        ttk.Button(dlg, text="\u24d8", width=3,
                   command=lambda: self.show_opponent_info(model_var.get())).grid(
            row=1, column=3, padx=2)
        def _start():
            self.set_opponent(model_var.get())
            dlg.destroy()
            self._start_chosen(side_var.get())
        ttk.Button(dlg, text="Engines\u2026",
                   command=self.dialog_engines).grid(row=3, column=0, columnspan=2,
                                                     pady=4)
        ttk.Button(dlg, text="Start", command=_start).grid(
            row=2, column=0, columnspan=4, pady=8)
        dlg.wait_window()

    def show_opponent_info(self, key: str):
        if key.startswith("engine:"):
            ent = {e.name: e for e in self.registry.list()}.get(key[len("engine:"):])
            detail = (ent.path if ent else key) +                 ("\ncustom options: " + str(ent.options) if ent and ent.options else "")
            self.status("external engine: " + (ent.name if ent else key))
        else:
            self.show_model_info(key[len("model:"):])
            return
        mb = tk.Toplevel(self.root)
        mb.title("External engine")
        tk.Label(mb, text="External UCI engine - options are read from the "
                 "engine itself.\n\n" + detail,
                 justify="left", wraplength=380, padx=14, pady=12).pack()
        tk.Button(mb, text="OK", command=mb.destroy).pack(pady=6)

    # ============================================== post-game analysis
    def _build_analysis_screen(self):
        """PART-12/13 analysis screen: whole-game engine review."""
        f = ttk.Frame(self.root, padding=14)
        self.analysis_frame = f
        top = ttk.Frame(f)
        top.pack(fill=tk.X, pady=(0, 8))
        ttk.Label(top, text="Game Analysis", font=("TkDefaultFont", 17, "bold")
                  ).pack(side=tk.LEFT)
        ttk.Button(top, text="Back to game",
                   command=lambda: self.show_frame("game")).pack(side=tk.RIGHT)
        bar = ttk.Frame(f)
        bar.pack(fill=tk.X, pady=4)
        ttk.Label(bar, text="Analyser:").pack(side=tk.LEFT)
        self.analysis_engine_var = tk.StringVar()
        self.analysis_engine_cb = ttk.Combobox(
            bar, textvariable=self.analysis_engine_var, state="readonly",
            width=20, values=self._analyser_choices())
        self.analysis_engine_cb.pack(side=tk.LEFT, padx=4)
        self.analysis_engine_var.set("zel")
        ttk.Label(bar, text="nodes/position:").pack(side=tk.LEFT, padx=(8, 0))
        self.analysis_nodes_var = tk.StringVar(value=str(self.cfg.analysis_nodes))
        ttk.Entry(bar, textvariable=self.analysis_nodes_var, width=9).pack(
            side=tk.LEFT, padx=4)
        ttk.Button(bar, text="Thresholds\u2026",
                   command=self.dialog_thresholds).pack(side=tk.LEFT, padx=6)
        self.analysis_start_btn = ttk.Button(bar, text="Analyze game",
                                             command=self.analysis_start)
        self.analysis_start_btn.pack(side=tk.LEFT, padx=6)
        self.analysis_cancel_btn = ttk.Button(bar, text="Cancel",
                                              command=self.analysis_cancel,
                                              state="disabled")
        self.analysis_cancel_btn.pack(side=tk.LEFT)

        self.analysis_prog = tk.StringVar(value="")
        ttk.Label(f, textvariable=self.analysis_prog).pack(anchor="w")
        mid = ttk.Frame(f)
        mid.pack(fill=tk.BOTH, expand=True, pady=6)
        left = ttk.Frame(mid)
        left.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.analysis_list = tk.Text(left, width=46, height=20, state="disabled",
                                     font=("TkFixedFont", 9), wrap="none")
        self.analysis_list.pack(fill=tk.BOTH, expand=True)
        right = ttk.Frame(mid, padding=(10, 0))
        right.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.analysis_graph = tk.Canvas(right, width=180, height=150,
                                        background="#1b222b",
                                        highlightthickness=0)
        self.analysis_graph.pack(fill=tk.X)
        self.analysis_crit = tk.Text(right, width=26, height=8, state="disabled",
                                     wrap="word", font=("TkDefaultFont", 9))
        self.analysis_crit.pack(fill=tk.X, pady=6)
        self.learn_btn = ttk.Button(
            right, text="Learn From This Game", state="disabled",
            command=self.learn_from_this_game)
        self.learn_btn.pack(fill=tk.X)
        self.learn_note = tk.Label(right, text="", fg="#7a8a96",
                                   justify="left", wraplength=180,
                                   font=("TkDefaultFont", 8))
        self.learn_note.pack(anchor="w", pady=(4, 0))

    def _analyser_choices(self):
        vals = ["Veltrix"]
        vals += ["engine:" + e.name for e in self.registry.list() if e.enabled]
        return vals

    def _analysis_refresh_info(self):
        self.analysis_engine_cb.configure(values=self._analyser_choices())
        if self.analysis_engine_var.get() not in self._analyser_choices():
            self.analysis_engine_var.set("Veltrix")
        n = len(self.state.hist_uci())
        decisive = bool(self.result and self.result[0] in ("1-0", "0-1"))
        engine_lost = (decisive and self.mode == "human_vs_engine"
                       and ((self.result[0] == "1-0") == (self.human_color == "w")))
        can_learn = bool(n and decisive and not self.opponent_uses_external
                         and engine_lost)
        self.learn_btn.configure(state=("normal" if can_learn else "disabled"))
        self.learn_note.configure(text=(
            "Veltrix lost this game - it can be folded into its training"
            " corpus." if can_learn else
            "available after a decisive Veltrix loss"))
        self.analysis_prog.set(f"{n} plies ready. Choose an analyser and run.")

    def dialog_thresholds(self):
        mb = tk.Toplevel(self.root)
        mb.title("Classification thresholds (cp)")
        vars_ = {}
        for i, (k, lab) in enumerate((("analysis_inaccuracy_cp", "inaccuracy"),
                                      ("analysis_mistake_cp", "mistake"),
                                      ("analysis_blunder_cp", "blunder"))):
            tk.Label(mb, text=lab + " ≥").grid(row=i, column=0, sticky="w",
                                                   padx=8, pady=4)
            v = tk.StringVar(value=str(getattr(self.cfg, k)))
            tk.Entry(mb, textvariable=v, width=8).grid(row=i, column=1)
            vars_[k] = v

        def _save():
            try:
                self.cfg.analysis_inaccuracy_cp = max(20, int(vars_["analysis_inaccuracy_cp"].get()))
                self.cfg.analysis_mistake_cp = max(self.cfg.analysis_inaccuracy_cp,
                                                   int(vars_["analysis_mistake_cp"].get()))
                self.cfg.analysis_blunder_cp = max(self.cfg.analysis_mistake_cp,
                                                   int(vars_["analysis_blunder_cp"].get()))
                self.cfg.save()
            except ValueError:
                self.status("thresholds must be integers")
            mb.destroy()
        tk.Button(mb, text="OK", command=_save).grid(row=3, column=0, pady=8)
        tk.Button(mb, text="Cancel", command=mb.destroy).grid(row=3, column=1)

    def analysis_start(self):
        if self.analysis["running"]:
            return
        if not self.state.hist_uci():
            return
        try:
            nodes = max(4000, int(self.analysis_nodes_var.get()))
        except ValueError:
            nodes = self.cfg.analysis_nodes
        self.cfg.analysis_nodes = nodes
        choice = self.analysis_engine_var.get()
        if choice.startswith("engine:"):
            ent = {e.name: e for e in self.registry.list()}.get(choice[len("engine:"):])
            if not ent:
                self.status("chosen external engine not available")
                return
            path, opts = ent.path, dict(ent.options or {})
        else:
            path, opts = self.engine_path, {"UseBook": "false", "Threads": 2,
                                            "Hash": 128}
        self.analysis["running"] = True
        self.analysis["cancel"] = threading.Event()
        self.analysis_start_btn.configure(state="disabled")
        self.analysis_cancel_btn.configure(state="normal")
        moves = self.state.hist_uci()
        fen0 = self.initial_fen
        thr = {"blunder": self.cfg.analysis_blunder_cp,
               "mistake": self.cfg.analysis_mistake_cp,
               "inaccuracy": self.cfg.analysis_inaccuracy_cp}

        def _work():
            rep = analyzer.analyze_game(
                fen0, moves, path, engine_options=opts, nodes=nodes,
                thresholds=thr,
                progress_cb=lambda d, t: self.root.after(
                    0, lambda: self.analysis_prog.set(f"analyzing {d}/{t}")),
                cancel=self.analysis["cancel"])
            self.root.after(0, lambda: self._analysis_done(rep))

        self.analysis["worker"] = threading.Thread(target=_work, daemon=True)
        self.analysis["worker"].start()

    def analysis_cancel(self):
        self.analysis["cancel"].set()

    def _analysis_done(self, rep):
        self.analysis["running"] = False
        self.analysis_start_btn.configure(state="normal")
        self.analysis_cancel_btn.configure(state="disabled")
        if rep is None:
            self.analysis_prog.set("analysis cancelled")
            return
        self.analysis["report"] = rep
        # fill the move list
        self.analysis_list.configure(state="normal")
        self.analysis_list.delete("1.0", tk.END)
        for e in rep.entries:
            glyph = analyzer.KLASS_GLYPH.get(e["klass"], "")
            ev = "" if e["ev_w"] is None else f"{e['ev_w'] / 100:+.2f}"
            best = f"  best: {e['best']}" if glyph or e["loss"] else ""
            pv = f" [{' '.join(e['pv'][:4])}\u2026]" if glyph else ""
            self.analysis_list.insert(
                tk.END, f"{e['no']:6s} {e['san']:8s}{glyph:2s} {ev:>7s}"
                        f"{(' -' + str(e['loss']) + 'cp') if e['loss'] else ''}"
                        f"{best}{pv}\n")
        self.analysis_list.configure(state="disabled")
        # critical moments
        self.analysis_crit.configure(state="normal")
        self.analysis_crit.delete("1.0", tk.END)
        self.analysis_crit.insert(
            tk.END, rep.summary() + "\n\n"
            + "\n".join(f"{e['no']} {e['san']} {analyzer.KLASS_GLYPH[e['klass']]}"
                        f"  ({e['klass']}, -{e['loss']} cp; best {e['best']})"
                        for e in rep.critical))
        self.analysis_crit.configure(state="disabled")
        self._draw_eval_graph(rep)
        self.analysis_prog.set(rep.summary())

    def _draw_eval_graph(self, rep):
        c = self.analysis_graph
        c.delete("all")
        vals = rep.graph_w
        if len(vals) < 2:
            return
        w = int(c.cget("width")); h = int(c.cget("height"))
        pad = 6
        c.create_line(pad, h // 2, w - pad, h // 2, fill="#3a4653")
        sc = (h - 2 * pad) / (2 * 1600.0)
        n = len(vals)
        pts = []
        for i, v in enumerate(vals):
            x = pad + (w - 2 * pad) * i / (n - 1)
            y = h // 2 - max(-1600, min(1600, v)) * sc
            pts.append((x, y))
        for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
            c.create_line(x0, y0, x1, y1, fill="#e8b64c", width=1.5)
        for e in rep.critical:
            i = e["ply"] - 1
            x, y = pts[i]
            c.create_oval(x - 2, y - 2, x + 2, y + 2, fill="#d44", outline="")
        midh = h // 2
        c.create_text(pad, midh - 8, text="+", anchor="sw", fill="#7a8a96")
        c.create_text(pad, midh + 8, text="-", anchor="nw", fill="#7a8a96")

    # -------------------------------------------- learn-from-this-game
    def learn_from_this_game(self, corpus_path=None, log_path=None):
        """PART 13: fold a decisive Veltrix loss into the learning corpus.

        Honest by construction: writes a record in the same JSONL format the
        learning loop's selfplay produces (data/learn/games.jsonl, eval fields
        null - teacher analysis fills them later) plus a short note. Nothing
        here claims the engine will get stronger; promotion is the gates
        problem (tools/learn/promote.py).
        """
        import json as _json
        corpus_path = corpus_path or "data/learn/games.jsonl"
        log_path = log_path or "data/learn/gui_imports_log.md"
        os.makedirs(os.path.dirname(corpus_path) or ".", exist_ok=True)
        if os.path.dirname(log_path):
            os.makedirs(os.path.dirname(log_path), exist_ok=True)
        moves = self.state.hist_uci()
        sans = self.state.hist_sans()
        from chesslib import Board as _B
        b = _B(self.initial_fen)
        plies = []
        for i, (u, s) in enumerate(zip(moves, sans)):
            plies.append({"fen": b.fen(), "move": u, "stm": b.stm,
                          "san": s, "eval": None, "depth": None,
                          "seldepth": None, "nodes": None, "ms": None,
                          "clock_ms": None, "pv0": ""})
            b.push(b.parse_uci(u))
        title = ("human" if self.mode == "human_vs_engine" else "way") + "@" + \
            self.opponent_name()
        rec = {
            "game": f"gui-{time.strftime('%Y%m%d-%H%M%S')}",
            "source": "gui-learn-button",
            "white": ("Player" if self.human_color == "w" else title),
            "black": ("Veltrix" if self.human_color == "w" else
                      ("Player" if self.mode == "human_vs_human" else "Veltrix")),
            "result": self.result[0] if self.result else "*",
            "reason": self.result[1] if self.result else "",
            "plies": len(plies),
            "tc": str(self.cfg.time_control[0]),
            "opening": self.initial_fen,
            "engine": {"w": {"name": "TBD", "path": ""},
                       "b": {"name": "TBD", "path": ""}},
            "moves": plies,
            "note": "submitted via the GUI Learn From This Game button",
        }
        with open(corpus_path, "a", encoding="utf-8") as f:
            f.write(_json.dumps(rec) + "\n")
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(f"\n## {rec['game']} - {rec['result']} ({rec['reason']}), "
                    f"{len(plies)} plies, opponent={title}\n"
                    f"imported via Learn From This Game; will be considered by "
                    f"the next training cycle of tools/learn/learn_loop.py; "
                    f"promotion remains subject to the champion gates.\n")
        self.status("game added to the learning corpus (data/learn/games.jsonl)")
        self.learn_btn.configure(state="disabled")
        self.learn_note.configure(
            text="recorded in data/learn/games.jsonl. The next training cycle "
                 "will consider it; no strength promise until the gates pass.")

    def menu_button(self):
        self.save_resume_state()
        try:
            self.cfg.save()
        except Exception:
            pass
        self.show_frame("menu")

    def show_model_info(self, key: str):
        """The \u24d8 button next to each model: factual description only."""
        p = models.profile(key)
        self.status(f"{p.key}: {p.blurb} [{p.budget_summary()}]")
        mb = tk.Toplevel(self.root)
        mb.title(f"About {p.key}")
        tk.Label(mb, text=p.blurb + "\n\n" + p.budget_summary(),
                 justify="left", wraplength=380, padx=14, pady=12).pack()
        tk.Button(mb, text="OK", command=mb.destroy).pack(pady=6)

    def _start_chosen(self, side):
        if side == "r":
            side = random.choice("wb")
        self.human_color = side
        self.mode = "human_vs_engine"
        self.new_game(side=side)

    def start_hvh(self):
        self.mode = "human_vs_human"
        self.new_game(side=self.human_color)
        self.status("human vs human")

    def start_eve(self):
        if not self.engine_path:
            self.pick_engine()
            if not self.engine_path:
                return
        if not self.engine2:
            self.engine2 = UCIClient(self.engine_path)
            self.engine2.start()
            self._apply_engine_options(self.engine2)
        self.mode = "engine_vs_engine"
        self.new_game(side=self.human_color)
        self.status("engine vs engine - use Game > Stop to end")

    def stop_eve(self):
        if self.mode == "engine_vs_engine":
            self.mode = "human_vs_engine"
        if self.engine:
            self.engine.stop()
        if self.engine2:
            self.engine2.stop()
        self.engine_thinking = False
        self.status("engine vs engine stopped")

    # ============================================================ play flow
    def live_board(self) -> Board:
        return self.state.board

    def view_board(self) -> Board:
        return self.state.board

    def cancel_engine_search(self, note=None):
        """Abort any in-flight search and make sure late bestmoves are
        discarded (the go-serial check handles that). Must run BEFORE any
        undo/redo/goto/new-game state change."""
        for c in (self.engine, self.engine2):
            if c and c.alive:
                self._go_serial.pop(c, None)
                c.stop()
        if self.engine_thinking:
            self.engine_thinking = False
            if note:
                self.status(note)

    def on_state_changed(self, redraw=True):
        """Unified resync after GameState mutations."""
        if redraw:
            self._sync_board_widget()
        self.move_list_update()
        self.save_resume_state()

    def undo_plies(self, n=1):
        """PART 8 semantics: take back n plies from the REAL game state -
        engine search cancelled, position/history/eval recomputed, and if
        the restored position is the engine's turn it plays from HERE."""
        if self.analyzing:
            self.toggle_analysis()
        if not self.state.undo_available:
            return
        self.cancel_engine_search()
        self.state.undo(n)
        self.soundboard.play("undo")
        self.on_state_changed()
        self.status("takeback - position rewound"
                    + ("; it is the engine's turn" if self.side_is_engine(self.board.stm)
                       and self.mode == "human_vs_engine" else ""))
        self.maybe_engine_move()

    def undo_all_plies(self):
        self.undo_plies(self.state.cursor)

    def redo_plies(self, n=1):
        if self.analyzing:
            self.toggle_analysis()
        if not self.state.redo_available:
            return
        self.cancel_engine_search()
        self.state.redo(n)
        self.on_state_changed()
        self.maybe_engine_move()

    def redo_all_plies(self):
        self.redo_plies(self.state.redo_count)

    def _sync_board_widget(self, animate=None):
        vb = self.view_board()
        last = None
        if self.moves and self.view > 0:
            m = self.moves[self.view - 1]
            last = (m.frm, m.to)
        check_sq = None
        if vb.in_check(vb.stm):
            check_sq = vb.king_sq(vb.stm)
        self.canvas.set_position(vb, last_move=last, check_sq=check_sq,
                                 animate_move=animate)
        self._update_captured()
        self.move_list_update()
        self._update_clock_labels()

    def _update_captured(self):
        start_counts = {}
        for ch in "PNBRQpnbrq":
            start_counts[ch] = 8 if ch.upper() == "P" else 2 if ch.upper() in "NBR" else 1
        cur = start_counts.copy()
        for p in self.board.board:
            if p != ".":
                if p in cur:
                    cur[p] -= 1
                else:  # e.g. puzzle positions with extra pieces / kings
                    cur[p] = cur.get(p, 1) - 1
        lost_w = "".join(UNICODE_PIECES[c] * n for c, n in cur.items() if c.isupper() and n > 0)
        lost_b = "".join(UNICODE_PIECES[c] * n for c, n in cur.items() if c.islower() and n > 0)
        from chesslib import PIECE_VALS
        mat = sum(PIECE_VALS[p.upper()] * (1 if p.isupper() else -1) for p in self.board.board if p != ".")
        sign = f"+{mat//100}.{abs(mat)%100:02d}" if mat > 0 else (f"-{-mat//100}.{abs(mat)%100:02d}" if mat < 0 else "")
        white_is_bottom = not self.canvas.flipped
        bottom = lost_b + ("  " + sign if mat > 0 else "")   # white sees black's lost pieces
        top = lost_w + ("  " + sign if mat < 0 else "")
        self.lbl_bottom_captured.configure(text=bottom if white_is_bottom else top)
        self.lbl_top_captured.configure(text=top if white_is_bottom else bottom)

    def on_square_click(self, sq):
        if self.result or self.mode == "engine_vs_engine":
            return
        vb = self.view_board()
        if self.mode == "human_vs_engine" and vb.stm != self.human_color:
            return
        # selecting
        if self.canvas.selected is None:
            piece = vb.board[sq]
            if piece != "." and ("w" if piece.isupper() else "b") == vb.stm:
                targets = [m.to for m in vb.legal_moves() if m.frm == sq]
                self.canvas.select(sq, targets)
            return
        frm = self.canvas.selected
        if frm == sq:
            self.canvas.deselect()
            return
        cand = [m for m in vb.legal_moves() if m.frm == frm and m.to == sq]
        if not cand:
            piece = vb.board[sq]
            if piece != "." and ("w" if piece.isupper() else "b") == vb.stm:
                targets = [m.to for m in vb.legal_moves() if m.frm == sq]
                self.canvas.select(sq, targets)
            else:
                self.soundboard.play("illegal")
                self.canvas.deselect()
            return
        m = cand[0]
        if len(cand) > 1:  # promotion choices
            promo = PromotionDialog(self.canvas, vb.stm == "w").show()
            if not promo:
                self.canvas.deselect()
                return
            m = next(mm for mm in cand if mm.promo == promo)
        self.canvas.deselect()
        self.play_move(m, mover="human")

    def _move_sound_kind(self, m: Move, san: str, before: Board) -> str:
        if m.promo:
            return "promote"
        if m.castle:
            return "castle"
        if san.endswith(("+", "#")):
            return "check"
        if before.board[m.to] != "." or m.ep:
            return "capture"
        return "move"

    def play_move(self, m: Move, mover="human"):
        before_board = self.state.board.copy()
        moved_color = self.state.board.stm
        if not self.state.at_end:
            # playing from a rewound position: engine "future" is abandoned
            self._go_serial.clear()
        san = self.state.push(m)
        self.soundboard.play(self._move_sound_kind(m, san, before_board))
        # apply increment to the side that just moved
        if self.clocks[moved_color] != float("inf"):
            self.clocks[moved_color] += self.incs[moved_color]
        self._sync_board_widget(animate=m)
        self.check_game_end()
        self.maybe_engine_move()

    def maybe_engine_move(self):
        if self.result or self.analyzing:
            return
        stm = self.board.stm
        if not self.side_is_engine(stm):
            return
        is_kind_my_engine = (self.mode == "human_vs_engine" and not self.opponent_uses_external)
        client = self.engine if (is_kind_my_engine or stm == "w" and
                                 self.mode != "human_vs_engine") else self.engine2
        if self.mode == "human_vs_engine" and self.opponent_uses_external:
            ent = self._ext_engine_entry()
            client = self.ext_client(ent) if ent else None
        if client is None:
            client = self.engine
        if client is None or not client.alive:
            return
        client.set_position("startpos" if self.initial_fen == STARTPOS_FEN else self.initial_fen,
                            self.state.hist_uci())
        self._go_serial[client] = self.state.serial
        prof = self.model
        if self.mode == "human_vs_engine" and self.opponent_uses_external:
            prof = models.profile("High")  # externals: full clock, own opts
        client.go(**models.go_kwargs(prof, stm, self.clocks, self.incs,
                                     self.cfg.move_time_ms))
        self.engine_thinking = True
        self.status(f"engine thinking as {'white' if stm == 'w' else 'black'}…")

    def on_engine_bestmove(self, client, data):
        expect_serial = self._go_serial.pop(client, None)
        # any bestmove that does not belong to a go issued for the CURRENT
        # state is stale (e.g. undo pressed while thinking): discard it and
        # re-arm the engine from the present position if it its turn
        if expect_serial is None or expect_serial != self.state.serial:
            self.engine_thinking = False
            if not self.result and not self.analyzing and self.board and \
                    self.side_is_engine(self.board.stm) and self.mode != "human_vs_human":
                self.maybe_engine_move()
            return
        self.engine_thinking = False
        if self.result or self.analyzing:
            return
        bm = data["move"]
        if bm == "0000":
            self.check_game_end(force=True)
            return
        try:
            m = self.board.parse_uci(bm)
        except ValueError:
            self.status(f"engine produced illegal move {bm} - game aborted")
            self.result = ("1/2-1/2", "engine error")
            self.check_game_end(force=True)
            return
        self.play_move(m, mover="engine")

    def check_game_end(self, force=False):
        out = self.board.outcome()
        if out:
            self.result = out
            self.soundboard.play("end")
            self.status(f"game over: {out[0]} - {out[1]}")
            self.clock_active = False
            if self.mode == "engine_vs_engine":
                self.root.after(1200, self._eve_next)
        elif force:
            self.status("game stopped")

    def _eve_next(self):
        if self.mode == "engine_vs_engine":
            self.new_game(side=self.human_color)

    def resign(self):
        if self.result or self.mode == "engine_vs_engine":
            return
        if self.mode == "human_vs_engine" or self.mode == "human_vs_human":
            winner = "0-1" if self.board.stm == "w" else "1-0"
            self.result = (winner, "resignation")
            self.soundboard.play("end")
            self.status(f"game over: {winner} - resignation")
            self.clock_active = False
            self._sync_board_widget()

    # ============================================================ clock
    def _tick(self):
        now = tk_current_ms()
        prev = getattr(self, "_last_tick", now)
        self._last_tick = now
        dt = (now - prev) / 1000.0
        if dt >= 10:        # suspend/resume guard
            dt = 0
        if self.clock_active and not self.result:
            stm = self.board.stm
            if self.clocks[stm] != float("inf"):
                self.clocks[stm] -= dt
                if self.clocks[stm] <= 0:
                    self.clocks[stm] = 0
                    winner = "0-1" if stm == "w" else "1-0"
                    self.result = (winner, "time out")
                    self.soundboard.play("end")
                    self.status(f"game over: {winner} - flag fall")
                    self.clock_active = False
                    self._sync_board_widget()
        self._update_clock_labels()
        self._tick_job = self.root.after(100, self._tick)
        self._pump_engine_events()

    def _update_clock_labels(self):
        wl = fmt_clock(self.clocks["w"]) if self.clocks["w"] != float("inf") else "∞"
        bl = fmt_clock(self.clocks["b"]) if self.clocks["b"] != float("inf") else "∞"
        white_bottom = not self.canvas.flipped
        white_to_move = self.board.stm == "w"
        # bold side to move
        wtxt, btxt = wl, bl
        self.lbl_bottom_clock.configure(text=wtxt if white_bottom else btxt)
        self.lbl_top_clock.configure(text=btxt if white_bottom else wtxt)
        wname = "White" + (" (you)" if self.mode != "engine_vs_engine" and self.human_color == "w" else " (engine)" if self.side_is_engine("w") else "")
        bname = "Black" + (" (you)" if self.mode != "engine_vs_engine" and self.human_color == "b" else " (engine)" if self.side_is_engine("b") else "")
        self.lbl_bottom_player.configure(text=(wname if white_bottom else bname) + (" ←" if white_to_move == white_bottom else ""))
        self.lbl_top_player.configure(text=(bname if white_bottom else wname) + (" ←" if white_to_move != white_bottom else ""))

    def _pump_engine_events(self):
        ext = getattr(self, "_ext_client", None)
        for client in (self.engine, self.engine2, ext):
            if not client:
                continue
            for ev in client.poll():
                if ev.kind == "bestmove":
                    self.on_engine_bestmove(client, ev.data)
                elif ev.kind == "info":
                    self.on_engine_info(client, ev.data)
                elif ev.kind == "error":
                    self.status(str(ev.data))
                elif ev.kind == "engine_exited":
                    self.status("engine process exited")
                elif ev.kind == "id":
                    client.id_name = ev.data

    _last_info_lines: dict = {}

    def on_engine_info(self, client, info):
        if "depth" not in info or not self.cfg.show_engine_lines:
            return
        key = info.get("multipv", 1)
        if not hasattr(self, "_info_lines"):
            self._info_lines = {}
        score_txt = ""
        if "score" in info:
            kind, val = info["score"]
            if kind == "cp":
                score_txt = f"{val / 100:+.2f}"
            else:
                score_txt = f"M{val:+d}"
        pv_txt = ""
        if "pv" in info and info["pv"]:
            nb = self.view_board().copy()
            san_list = []
            for u in info["pv"][:12]:
                try:
                    m = nb.parse_uci(u)
                    san_list.append(nb.san(m))
                    nb.push(m)
                except ValueError:
                    break
            pv_txt = " ".join(san_list)
        nps = info.get("nps", 0)
        line = f"d{info['depth']:2d} {score_txt:8s} {nps / 1e6:6.2f}M  {pv_txt}"
        self._info_lines[key] = line
        self.engine_box_update()

    def engine_box_update(self):
        lines = getattr(self, "_info_lines", {})
        self.engine_box.configure(state="normal")
        self.engine_box.delete("1.0", tk.END)
        for k in sorted(lines):
            self.engine_box.insert(tk.END, lines[k] + "\n")
        name = self.engine.id_name if self.engine else "no engine"
        self.engine_box.insert(tk.END, f"— {name}\n")
        self.engine_box.configure(state="disabled")
        self.engine_box.see(tk.END)

    # ============================================================ navigation
    def navigate(self, idx):
        idx = max(0, min(idx, len(self.state.moves)))
        if idx == self.view:
            return
        if self.analyzing:
            self.toggle_analysis()
        self.cancel_engine_search()
        self.state.goto(idx)
        vb = self.state.board
        self._sync_board_widget()
        remainder = len(self.moves) - idx
        self.status("browsing history - ▶ to redo; any move continues from here"
                    if remainder else "live position")
        self.maybe_engine_move()

    def on_moves_click(self, ev):
        index = self.moves_list.index(f"@{ev.x},{ev.y}")
        # figure out which move number was clicked: parse "3." style tags is
        # overkill; approximate by line (we write two moves per line)
        row = int(index.split(".")[0]) - 1
        target = max(0, min(row * 2 + 1, len(self.moves)))
        if target != self.view:
            self.navigate(target)

    def move_list_update(self):
        self.moves_list.configure(state="normal")
        self.moves_list.delete("1.0", tk.END)
        for i, s in enumerate(self.sans):
            if i % 2 == 0:
                self.moves_list.insert(tk.END, f"{i // 2 + 1}. ")
            self.moves_list.insert(tk.END, s + "  ")
            if i % 2 == 1:
                self.moves_list.insert(tk.END, "\n")
        if self.result:
            self.moves_list.insert(tk.END, "\n" + self.result[0])
        self.moves_list.configure(state="disabled")
        self.moves_list.see(tk.END)

    # ============================================================ FEN / PGN
    def copy_fen(self):
        self.root.clipboard_clear()
        self.root.clipboard_append(self.view_board().fen())
        self.status("FEN copied to clipboard")

    def paste_fen(self):
        fen = simpledialog.askstring("Paste FEN", "FEN:", parent=self.root)
        if not fen:
            return
        try:
            b = Board(fen.strip())
        except ValueError as exc:
            messagebox.showerror("Invalid FEN", str(exc))
            return
        self.initial_fen = b.fen()
        self.new_game(side=self.human_color)
        self.status("position loaded from FEN")

    def save_pgn(self):
        result = self.result[0] if self.result else "*"
        if self.mode == "engine_vs_engine":
            wname = bname = self.engine.id_name if self.engine else "Veltrix"
        else:
            wname = "Player" if self.human_color == "w" else (self.engine.id_name if self.engine else "Veltrix")
            bname = "Player" if self.human_color == "b" else (self.engine.id_name if self.engine else "Veltrix")
        path = filedialog.asksaveasfilename(
            defaultextension=".pgn", filetypes=[("PGN files", "*.pgn"), ("All files", "*.*")])
        if not path:
            return
        with open(path, "w", encoding="utf-8") as f:
            f.write(game_pgn(self.initial_fen, self.sans, wname, bname, result))
        self.status(f"PGN saved: {path}")

    def load_pgn(self):
        path = filedialog.askopenfilename(
            filetypes=[("PGN files", "*.pgn"), ("All files", "*.*")])
        if not path:
            return
        try:
            text = open(path, encoding="utf-8", errors="replace").read()
        except OSError as exc:
            messagebox.showerror("Load PGN", str(exc))
            return
        ok, msg = self._import_pgn(text)
        if not ok:
            messagebox.showerror("Load PGN", msg)
        else:
            self.status(msg)

    def _import_pgn(self, text: str):
        import re
        fen = STARTPOS_FEN
        m = re.search(r'\[FEN "([^"]+)"\]', text)
        if m:
            fen = m.group(1)
        body = re.sub(r"\[[^\]]*\]", "", text)
        body = re.sub(r"\{[^}]*\}", " ", body)           # comments
        body = re.sub(r"\$\d+", " ", body)               # NAGs
        body = re.sub(r"\([^)]*\)", " ", body)           # variations (shallow)
        tokens = re.split(r"\s+", body)
        b = Board(fen)
        moves, sans = [], []
        for tok in tokens:
            tok = tok.strip()
            if not tok or tok in ("1-0", "0-1", "1/2-1/2", "*"):
                continue
            if re.match(r"^\d+\.(\.\.)?$", tok):
                continue
            tok = tok.split(".", 1)[-1]
            if not tok:
                continue
            found = None
            for mv in b.legal_moves():
                if b.san(mv) == tok:
                    found = mv
                    break
            if found is None:
                return False, f"could not parse move '{tok}'"
            sans.append(b.san(found))
            b.push(found)
            moves.append(found)
        self.initial_fen = fen
        self.new_game(side=self.human_color)
        self.state.load_moves(moves, sans)
        self._sync_board_widget()
        return True, f"loaded {len(moves)} moves from PGN"

    # ============================================================ settings
    def pick_engine(self):
        path = filedialog.askopenfilename(
            title="Locate veltrix engine binary",
            filetypes=[("Engine", "veltrix.exe veltrix *"), ("All files", "*.*")])
        if path:
            self.engine_path = path
            self.cfg.engine_path = path
            self._connect_engine()
            self.status(f"engine: {path}")

    def dialog_engine_options(self):
        res = EngineSettingsDialog(self.root, self.cfg).show()
        if not res:
            return
        self.cfg.limit_strength = bool(res["limit"])
        self.cfg.engine_elo = int(res["elo"])
        self.cfg.multipv = int(res["multipv"])
        self.cfg.hash_mb = int(res["hash"])
        self.cfg.threads = int(res["threads"])
        self.cfg.move_time_ms = int(res["movetime"])
        for c in (self.engine, self.engine2):
            if c:
                self._apply_engine_options(c)
        self.status("engine options applied")
        self.cfg.save()

    def dialog_time_control(self):
        res = TimeControlDialog(self.root, self.cfg.time_control).show()
        if not res:
            return
        if res[0] == "custom":
            _, wm, wi, bm, bi = res
            self.cfg.custom_minutes_white, self.cfg.custom_inc_white = wm, wi
            self.cfg.custom_minutes_black, self.cfg.custom_inc_black = bm, bi
            self.cfg.time_control = ("custom…", "custom", "custom")
        elif res[0] == "unlimited":
            self.cfg.time_control = (res[1], None, None)
        else:
            self.cfg.time_control = (res[1], res[2], res[3])
        self.tc_lbl.configure(text=f"time control: {self.cfg.time_control[0]}")
        self.status(f"time control: {self.cfg.time_control[0]}")
        self.cfg.save()

    def dialog_colors(self):
        res = ColorsDialog(self.root, self.cfg.theme, self.cfg.light_sq, self.cfg.dark_sq).show()
        if not res:
            return
        self.cfg.theme, self.cfg.light_sq, self.cfg.dark_sq = res
        self.apply_cfg_visual()
        self.cfg.save()

    def dialog_size(self):
        v = simpledialog.askinteger("Board size", "pixels (360-1600):",
                                    initialvalue=self.cfg.board_size,
                                    minvalue=360, maxvalue=1600, parent=self.root)
        if v:
            self.cfg.board_size = v
            self.apply_cfg_visual()
            self.cfg.save()

    def toggle_coords(self):
        self.cfg.show_coords = self.coords_var.get()
        self.canvas.show_coords = self.cfg.show_coords
        self.canvas.redraw()
        self.cfg.save()

    def toggle_flip(self):
        self.cfg.flip_board = self.flip_var.get()
        self.canvas.flipped = self.cfg.flip_board
        self._sync_board_widget()
        self.cfg.save()

    def toggle_flip_menu(self):
        self.flip_var.set(not self.flip_var.get())
        self.toggle_flip()

    def toggle_analysis(self):
        if not self.engine or not self.engine.alive:
            return
        self.analyzing = not self.analyzing
        if self.analyzing:
            self.engine.set_position(
                "startpos" if self.initial_fen == STARTPOS_FEN else self.initial_fen,
                self.state.hist_uci())
            self.engine.go(infinite=True)
            self.status("analysis mode on - engine thinking until toggled off")
        else:
            self.engine.stop()
            self.status("analysis mode off")
            self.maybe_engine_move()

    def open_tutorial(self):
        path = os.path.join(HERE, "..", "docs", "TUTORIAL.md")
        if os.path.isfile(path):
            if os.name == "nt":
                os.startfile(path)  # noqa
            else:
                import subprocess
                subprocess.Popen(["xdg-open", path])
        else:
            messagebox.showinfo("Tutorial", "docs/TUTORIAL.md was not found in the repo.")

    def status(self, msg):
        self.status_var.set(msg)

    # ============================================================ shutdown
    def on_close(self):
        self.cancel_engine_search()
        self.save_resume_state()
        try:
            self.cfg.save()
        except Exception:
            pass
        self.disconnect_ext_client()
        self.status("shutting down engines…")
        try:
            self.cfg.flip_board = self.flip_var.get()
            self.cfg.window_geometry = self.root.geometry()
            self.cfg.save()
        except Exception:
            pass
        for c in (self.engine, self.engine2):
            if c:
                c.quit()
        self.root.after(100, self.root.destroy)


def tk_current_ms():
    import time
    return time.time() * 1000


def main():
    root = tk.Tk()
    app = VeltrixApp(root)
    # time-control menu entry (needs app)
    m = root.nametowidget(root["menu"])
    for label in ("Game",):
        idx = m.index(label)
        sub = m.nametowidget(m.entrycget(idx, "menu"))
        sub.insert_command(1, label="Time control…", command=app.dialog_time_control)
    root.mainloop()


if __name__ == "__main__":
    main()
