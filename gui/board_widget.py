"""
board_widget.py - chess board canvas widget for the Veltrix GUI.

Renders the position, coordinates, last-move/check highlights, legal-target
hints and move-animation. Emits callbacks for clicks; move legality is the
caller's concern (chesslib).
"""
from __future__ import annotations

import tkinter as tk

from chesslib import Board, Move, sq_name

UNICODE_PIECES = {
    "K": "\u2654", "Q": "\u2655", "R": "\u2656", "B": "\u2657", "N": "\u2658", "P": "\u2659",
    "k": "\u265a", "q": "\u265b", "r": "\u265c", "b": "\u265d", "n": "\u265e", "p": "\u265f",
}
FILES = "abcdefgh"


class BoardCanvas(tk.Canvas):
    def __init__(self, master, size=480, light="#f0d9b5", dark="#b58863",
                 show_coords=True, flipped=False, animation_ms=120, **kw):
        super().__init__(master, width=size, height=size,
                         highlightthickness=0, **kw)
        self.light, self.dark = light, dark
        self.show_coords = show_coords
        self.flipped = flipped
        self.animation_ms = animation_ms
        self.highlight_last = True
        self.highlight_check = True
        self.highlight_targets = True
        self.selected = None            # square index or None
        self.targets = []               # legal target squares of selected
        self.last_move = None           # (from, to)
        self.check_sq = None
        self.board = Board()
        self.on_square_click = None     # callback(square)
        self.on_right_click = None      # callback()
        self.bind("<Button-1>", self._click)
        self.bind("<Button-3>", lambda e: self.on_right_click and self.on_right_click())
        self.bind("<Configure>", lambda e: self.redraw())
        self._anim = None

    # ------------------------------------------------------------- mapping
    def sq_to_xy(self, sq):
        f, r = sq % 8, sq // 8
        if self.flipped:
            f, r = 7 - f, 7 - r
        else:
            r = 7 - r
        return f, r

    def xy_to_sq(self, x, y):
        s = self.cell()
        f, r = x // s, y // s
        if not (0 <= f < 8 and 0 <= r < 8):
            return None
        if self.flipped:
            f, r = 7 - f, 7 - r
        else:
            r = 7 - r
        return r * 8 + f

    def cell(self):
        return max(24, min(self.winfo_width(), self.winfo_height()) // 8)

    def size_side(self):
        return self.cell() * 8

    # ------------------------------------------------------------ drawing
    def redraw(self):
        self.delete("all")
        s = self.cell()
        side = s * 8
        self.config(width=side, height=side)
        # squares
        for r in range(8):
            for f in range(8):
                sq = (7 - r) * 8 + f if not self.flipped else r * 8 + (7 - f)
                x0, y0 = f * s, r * s
                col = self.light if (sq // 8 + sq % 8) % 2 == 1 else self.dark
                self.create_rectangle(x0, y0, x0 + s, y0 + s, fill=col, outline=col,
                                      tags="sq")
        # highlights below pieces
        if self.highlight_last and self.last_move:
            for sq in self.last_move:
                self._hl(sq, "#c9e37f" if ((sq // 8 + sq % 8) % 2 == 1) else "#acc64f")
        if self.highlight_check and self.check_sq is not None and self.check_sq >= 0:
            self._hl(self.check_sq, "#ff6961")
        if self.selected is not None:
            self._hl(self.selected, "#7fb6e3")
        # target hints
        if self.highlight_targets:
            for sq in self.targets:
                f, r = self.sq_to_xy(sq)
                cx, cy = f * s + s / 2, r * s + s / 2
                occupied = self.board.board[sq] != "."
                if occupied:
                    self.create_oval(cx - s * 0.46, cy - s * 0.46, cx + s * 0.46,
                                     cy + s * 0.46, outline="#d9534f", width=3,
                                     tags="hint")
                else:
                    self.create_oval(cx - s * 0.16, cy - s * 0.16, cx + s * 0.16,
                                     cy + s * 0.16, fill="#3a6f3a", outline="",
                                     stipple="gray50", tags="hint")
        # pieces
        fs = max(12, int(s * 0.72))
        for sq in range(64):
            p = self.board.board[sq]
            if p == ".":
                continue
            f, r = self.sq_to_xy(sq)
            self.create_text(f * s + s / 2, r * s + s / 2 + s * 0.03,
                             text=UNICODE_PIECES[p], font=("Segoe UI Symbol", fs),
                             fill="#181818" if p.islower() else "#f8f8f8",
                             tags=("piece", f"pc{sq}"))
        # coordinates: rank numbers on the left edge, file letters on the
        # bottom edge; colour contrasts with the underlying square
        if self.show_coords:
            small = max(8, s // 6)
            for i in range(8):
                # rank label at the left of row i (top=0)
                rank = str((8 - i) if not self.flipped else i + 1)
                sq_col0 = (7 - i) * 8 + 0 if not self.flipped else i * 8 + 7
                baseL = self.light if (sq_col0 // 8 + sq_col0 % 8) % 2 == 1 else self.dark
                label_col = self.dark if baseL == self.light else self.light
                self.create_text(3, i * s + small + 2, text=rank,
                                 font=("TkDefaultFont", small), fill=label_col,
                                 tags="coord", anchor="w")
                # file label at the bottom of column i
                name_f = FILES[i if not self.flipped else 7 - i]
                sq_row7 = 0 * 8 + i if not self.flipped else 7 * 8 + (7 - i)
                baseB = self.light if (sq_row7 // 8 + sq_row7 % 8) % 2 == 1 else self.dark
                label_col2 = self.dark if baseB == self.light else self.light
                self.create_text(i * s + s - 4, 8 * s - small - 2, text=name_f,
                                 font=("TkDefaultFont", small), fill=label_col2,
                                 tags="coord", anchor="e")

    def _hl(self, sq, color):
        s = self.cell()
        f, r = self.sq_to_xy(sq)
        x0, y0 = f * s, r * s
        base = self.light if (sq // 8 + sq % 8) % 2 == 1 else self.dark
        blend = self._mix(base, color, 0.45)
        self.create_rectangle(x0, y0, x0 + s, y0 + s, fill=blend, outline=blend,
                              tags="hl")

    @staticmethod
    def _mix(c1, c2, t):
        def rgb(c):
            return tuple(int(c[i:i + 2], 16) for i in (1, 3, 5))
        a, b = rgb(c1), rgb(c2)
        return "#%02x%02x%02x" % tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))

    # --------------------------------------------------------------- input
    def _click(self, ev):
        sq = self.xy_to_sq(ev.x, ev.y)
        if sq is not None and self.on_square_click:
            self.on_square_click(sq)

    def select(self, sq, targets):
        self.selected = sq
        self.targets = list(targets)
        self.redraw()

    def deselect(self):
        self.selected = None
        self.targets = []
        self.redraw()

    def set_position(self, board: Board, *, last_move=None, check_sq=None,
                     animate_move: Move | None = None):
        old = self.board
        self.board = board
        self.last_move = last_move
        self.check_sq = check_sq
        self.selected = None
        self.targets = []
        self.redraw()
        if animate_move and self.animation_ms > 0:
            self._animate(old, animate_move)

    def _animate(self, old_board, move: Move):
        """Slide the moving piece from its source square."""
        try:
            piece = old_board.board[move.frm]
            if piece == ".":
                return
            self.delete(f"pc{move.to}")
            s = self.cell()
            f0, r0 = self.sq_to_xy(move.frm)
            f1, r1 = self.sq_to_xy(move.to)
            x0, y0 = f0 * s + s / 2, r0 * s + s / 2 + s * 0.03
            x1, y1 = f1 * s + s / 2, r1 * s + s / 2 + s * 0.03
            steps = max(4, self.animation_ms // 20)
            fs = max(12, int(s * 0.72))
            item = self.create_text(x0, y0, text=UNICODE_PIECES[piece],
                                    font=("Segoe UI Symbol", fs),
                                    fill="#181818" if piece.islower() else "#f8f8f8",
                                    tags="anim")
            self.tag_raise(item)

            def step(i):
                if i >= steps:
                    self.delete(item)
                    self.redraw()
                    return
                t = (i + 1) / steps
                self.coords(item, x0 + (x1 - x0) * t, y0 + (y1 - y0) * t)
                self._anim = self.after(16, lambda: step(i + 1))

            step(0)
        except tk.TclError:
            pass
