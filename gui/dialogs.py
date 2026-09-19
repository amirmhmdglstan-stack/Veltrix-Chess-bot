"""dialogs.py - modal dialogs for the Veltrix GUI (tkinter only)."""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from config_store import PRESET_TIME_CONTROLS


class Modal(tk.Toplevel):
    def __init__(self, parent, title):
        super().__init__(parent)
        self.withdraw()
        self.title(title)
        self.resizable(False, False)
        self.transient(parent.winfo_toplevel())
        self.result = None
        self.bind("<Escape>", lambda e: self._cancel())
        self.protocol("WM_DELETE_WINDOW", self._cancel)

    def _cancel(self):
        self.result = None
        self.grab_release()
        self.destroy()

    def show(self):
        self.deiconify()
        self.update_idletasks()
        px = self.master.winfo_rootx() + (self.master.winfo_width() - self.winfo_width()) // 2
        py = self.master.winfo_rooty() + (self.master.winfo_height() - self.winfo_height()) // 2
        self.geometry(f"+{max(px, 0)}+{max(py, 0)}")
        self.grab_set()
        self.wait_window(self)
        return self.result


UNICODE_PIECES = {
    "K": "\u2654", "Q": "\u2655", "R": "\u2656", "B": "\u2657", "N": "\u2658", "P": "\u2659",
    "k": "\u265a", "q": "\u265b", "r": "\u265c", "b": "\u265d", "n": "\u265e", "p": "\u265f",
}


class PromotionDialog(Modal):
    """Ask which piece to promote to. Returns 'q','r','b','n' or None."""

    def __init__(self, parent, white: bool):
        super().__init__(parent, "Promotion")
        ttk.Label(self, text="Promote pawn to:", padding=8).pack()
        frame = ttk.Frame(self, padding=4)
        frame.pack()
        letters = ("Q", "R", "B", "N") if white else ("q", "r", "b", "n")
        for i, letter in enumerate(letters):
            b = tk.Button(frame, text=UNICODE_PIECES[letter], font=("Segoe UI Symbol", 26),
                          width=3, command=lambda l=letter.lower(): self._pick(l))
            b.grid(row=0, column=i, padx=4, pady=4)

    def _pick(self, piece):
        self.result = piece
        self.grab_release()
        self.destroy()


class TimeControlDialog(Modal):
    """
    Returns a tuple:
      ("preset", name, minutes, increment_seconds)           for presets incl. unlimited
      ("custom", w_minutes, w_inc, b_minutes, b_inc)          for custom per-side clocks
    None on cancel.
    """

    def __init__(self, parent, current):
        super().__init__(parent, "Time control")
        self.columnconfigure(0, weight=1)
        ttk.Label(self, text="Choose a time control:", padding=(10, 8, 10, 2)).grid(
            row=0, column=0, columnspan=2, sticky="w")
        self.lb = tk.Listbox(self, height=len(PRESET_TIME_CONTROLS), width=30,
                             exportselection=False)
        for name, _, _ in PRESET_TIME_CONTROLS:
            self.lb.insert(tk.END, name)
        self.lb.grid(row=1, column=0, columnspan=2, padx=10, pady=4, sticky="ew")
        self.lb.selection_set(0)
        cur_name = current[0] if current else ""
        for i, (name, _, _) in enumerate(PRESET_TIME_CONTROLS):
            if name == cur_name:
                self.lb.selection_clear(0, tk.END)
                self.lb.selection_set(i)
                self.lb.see(i)
                break
        self.lb.bind("<Double-Button-1>", lambda e: self._accept())

        custom = ttk.LabelFrame(self, text="Custom (used when 'custom…' is selected)",
                                padding=6)
        custom.grid(row=2, column=0, columnspan=2, padx=10, pady=6, sticky="ew")
        self.vars = {
            "wm": tk.StringVar(value="5"), "wi": tk.StringVar(value="2"),
            "bm": tk.StringVar(value="5"), "bi": tk.StringVar(value="2"),
        }
        for rr, (label, key_m, key_i) in enumerate(
                (("White minutes / inc", "wm", "wi"),
                 ("Black minutes / inc", "bm", "bi"))):
            ttk.Label(custom, text=label).grid(row=rr, column=0, sticky="w", padx=2)
            ttk.Entry(custom, textvariable=self.vars[key_m], width=6).grid(
                row=rr, column=1, padx=2)
            ttk.Entry(custom, textvariable=self.vars[key_i], width=6).grid(
                row=rr, column=2, padx=2)
        ttk.Label(custom, text="minutes").grid(row=0, column=3, sticky="w")
        ttk.Label(custom, text="inc (sec)").grid(row=0, column=4, sticky="w")

        row = ttk.Frame(self, padding=8)
        row.grid(row=3, column=0, columnspan=2)
        ttk.Button(row, text="OK", command=self._accept).pack(side=tk.LEFT, padx=4)
        ttk.Button(row, text="Cancel", command=self._cancel).pack(side=tk.LEFT, padx=4)

    def _accept(self):
        sel = self.lb.curselection()
        if not sel:
            return
        name, minutes, inc = PRESET_TIME_CONTROLS[sel[0]]
        if minutes == "custom":
            try:
                wm = float(self.vars["wm"].get()); wi = float(self.vars["wi"].get())
                bm = float(self.vars["bm"].get()); bi = float(self.vars["bi"].get())
            except ValueError:
                return
            self.result = ("custom", wm, wi, bm, bi)
        elif minutes is None:
            self.result = ("unlimited", name, None, None)
        else:
            self.result = ("preset", name, minutes, inc)
        self.grab_release()
        self.destroy()


class ColorsDialog(Modal):
    """Board colour / theme customization. Returns (theme_name, light, dark) or None."""

    def __init__(self, parent, theme, light, dark):
        super().__init__(parent, "Board colors")
        self.light = light
        self.dark = dark
        from theme import THEMES
        ttk.Label(self, text="Theme:", padding=6).grid(row=0, column=0, sticky="w")
        self.theme_var = tk.StringVar(value=theme)
        box = ttk.Combobox(self, textvariable=self.theme_var, state="readonly",
                           values=sorted(THEMES.keys()))
        box.grid(row=0, column=1, padx=6, pady=6)
        box.bind("<<ComboboxSelected>>", lambda e: self._apply_theme())
        for i, (label, attr) in enumerate((("Light squares", "light"), ("Dark squares", "dark"))):
            ttk.Label(self, text=label + ":", padding=6).grid(row=1 + i, column=0, sticky="w")
            sw = tk.Label(self, text=getattr(self, attr), bg=getattr(self, attr),
                          width=18, relief="groove", cursor="hand2")
            sw.grid(row=1 + i, column=1, padx=6, pady=4, sticky="w")
            sw.bind("<Button-1>", lambda e, a=attr, w=sw: self._pick(a, w))
        row = ttk.Frame(self, padding=8)
        row.grid(row=3, column=0, columnspan=2)
        ttk.Button(row, text="OK", command=self._ok).pack(side=tk.LEFT, padx=4)
        ttk.Button(row, text="Cancel", command=self._cancel).pack(side=tk.LEFT, padx=4)

    def _apply_theme(self):
        from theme import THEMES
        l, d = THEMES[self.theme_var.get()]
        self.light, self.dark = l, d
        self._refresh()

    def _refresh(self):
        for w in self.grid_slaves():
            if isinstance(w, tk.Label) and w.cget("cursor") == "hand2":
                pass

    def _pick(self, attr, widget):
        from tkinter import colorchooser
        c = colorchooser.askcolor(getattr(self, attr), parent=self)
        if c and c[1]:
            setattr(self, attr, c[1])
            widget.configure(bg=c[1], text=c[1])

    def _ok(self):
        self.result = (self.theme_var.get(), self.light, self.dark)
        self.grab_release()
        self.destroy()


class EngineSettingsDialog(Modal):
    """Engine strength / options dialog."""

    def __init__(self, parent, cfg):
        super().__init__(parent, "Engine options")
        self.vars = {
            "limit": tk.BooleanVar(value=cfg.limit_strength),
            "elo": tk.IntVar(value=cfg.engine_elo),
            "multipv": tk.IntVar(value=cfg.multipv),
            "hash": tk.IntVar(value=cfg.hash_mb),
            "threads": tk.IntVar(value=cfg.threads),
            "movetime": tk.IntVar(value=cfg.move_time_ms),
        }
        r = 0
        ttk.Checkbutton(self, text="Limit strength (UCI_LimitStrength)",
                        variable=self.vars["limit"]).grid(
            row=r, column=0, columnspan=2, sticky="w", padx=8, pady=4)
        r += 1
        for label, key, lo, hi in (
                ("Engine Elo (when limited)", "elo", 1350, 2850),
                ("MultiPV lines", "multipv", 1, 4),
                ("Hash (MB)", "hash", 1, 4096),
                ("Threads (0 = auto)", "threads", 0, 64),
                ("Move time in unlimited mode (ms)", "movetime", 50, 60000)):
            ttk.Label(self, text=label + ":").grid(row=r, column=0, sticky="w", padx=8)
            tk.Spinbox(self, from_=lo, to=hi, textvariable=self.vars[key],
                        width=8).grid(row=r, column=1, padx=8, pady=2, sticky="w")
            r += 1
        row = ttk.Frame(self, padding=8)
        row.grid(row=r, column=0, columnspan=2)
        ttk.Button(row, text="OK", command=self._ok).pack(side=tk.LEFT, padx=4)
        ttk.Button(row, text="Cancel", command=self._cancel).pack(side=tk.LEFT, padx=4)

    def _ok(self):
        self.result = {k: v.get() for k, v in self.vars.items()}
        self.grab_release()
        self.destroy()
