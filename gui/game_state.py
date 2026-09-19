"""
game_state.py - single authoritative game state for the Veltrix GUI.

Owns: initial position, full move history (+SAN), the play cursor, result.
The current board is ALWAYS derived from initial_fen + moves[:cursor]
(cached, invalidated on mutation) - there is exactly one source of truth
and no hidden parallel position can diverge from it.

Every play operation (human input, engine bestmove, undo, redo, goto,
load, new game) MUST flow through this object. Radical simplification that
fixes the old '"previous action" only rewound a view while the engine kept
playing from the future' class of bugs:

  undo(n)  - step the cursor back n plies; moves stay in history so...
  redo(n)  - ...they can be replayed forward.
  push(m)  - apply a move; if the cursor was mid-history (after undo),
             the abandoned future is truncated (normal takeback semantics
             on lichess/chess.com).

Clocks are intentionally NOT part of this object (elapsed time is never
refunded on takeback; the app owns clocks).

The state is UI-free and unit-testable without tkinter.
"""
from __future__ import annotations

from chesslib import Board, Move, STARTPOS_FEN


class GameState:
    def __init__(self, fen: str = STARTPOS_FEN):
        self.reset(fen)

    # ---------------------------------------------------------------- core
    def reset(self, fen: str = STARTPOS_FEN):
        self.initial_fen = fen
        self.moves: list[Move] = []
        self.sans: list[str] = []
        self.cursor = 0                    # play position = moves[:cursor]
        self.result: tuple[str, str] | None = None
        self._cached_cursor = -1
        self._cached_board: Board | None = None
        # monotonically increasing; every mutation bumps it. The engine
        # client echoes this and stale bestmoves can be recognised.
        self.serial = 0

    def _touch(self):
        self.serial += 1
        self._cached_cursor = -1

    # ---------------------------------------------------------------- board
    @property
    def board(self) -> Board:
        """Board at the play cursor (cached). NEVER mutate the result."""
        if self._cached_cursor != self.cursor or self._cached_board is None:
            nb = Board(self.initial_fen)
            for m in self.moves[:self.cursor]:
                nb.push(m)
            self._cached_board = nb
            self._cached_cursor = self.cursor
        return self._cached_board

    @property
    def at_end(self) -> bool:
        return self.cursor >= len(self.moves)

    @property
    def undo_available(self) -> bool:
        return self.cursor > 0

    @property
    def redo_available(self) -> bool:
        return self.cursor < len(self.moves)

    # ---------------------------------------------------------------- moves
    def push(self, m: Move, san: str | None = None) -> str:
        """Apply a move at the cursor; truncates any abandoned future."""
        if not self.at_end:
            self.moves = self.moves[:self.cursor]
            self.sans = self.sans[:self.cursor]
        if san is None:
            san = self.board.san(m)
        self.moves.append(m)
        self.sans.append(san)
        self.cursor += 1
        if self.result is not None:
            self.result = None              # playing again after takeback
        self._touch()
        return san

    def undo(self, n: int = 1) -> int:
        steps = min(n, self.cursor)
        if steps:
            self.cursor -= steps
            if self.result is not None:
                self.result = None
            self._touch()
        return steps

    def undo_all(self) -> int:
        return self.undo(self.cursor)

    def redo(self, n: int = 1) -> int:
        steps = min(n, len(self.moves) - self.cursor)
        if steps:
            self.cursor += steps
            self._touch()
        return steps

    def redo_all(self) -> int:
        return self.redo(len(self.moves) - self.cursor)

    def goto(self, ply: int) -> int:
        ply = max(0, min(ply, len(self.moves)))
        if ply == self.cursor:
            return 0
        if self.result is not None and ply < self.cursor:
            self.result = None
        self.cursor = ply
        self._touch()
        return 1

    # -------- live-prefix views (what pre-refactor consumers expect) -----
    def hist_moves(self) -> list:
        return list(self.moves[:self.cursor])

    def hist_sans(self) -> list:
        return list(self.sans[:self.cursor])

    def set_live_sans(self, v):
        """Replace the live sans (PGN-edit style callers used to own a flat
        list). Keeps undo/redo bookkeeping consistent for sane input."""
        if len(v) == self.cursor:
            self.sans[:self.cursor] = list(v)
        else:
            tail = self.sans[self.cursor:]
            self.sans = list(v) + tail
            self.cursor = min(self.cursor, len(v))
        self._touch()

    @property
    def redo_count(self) -> int:
        return len(self.moves) - self.cursor

    # ---------------------------------------------------------------- util
    def hist_uci(self) -> list[str]:
        return [m.uci() for m in self.moves[:self.cursor]]

    def live_uci_history(self) -> list[str]:
        return [m.uci() for m in self.moves]

    def load_moves(self, moves: list[Move], sans: list[str]):
        assert len(moves) == len(sans)
        self.moves = list(moves)
        self.sans = list(sans)
        self.cursor = len(self.moves)
        self.result = None
        self._touch()

    def fen_at(self, ply: int) -> str:
        nb = Board(self.initial_fen)
        for m in self.moves[:ply]:
            nb.push(m)
        return nb.fen()
