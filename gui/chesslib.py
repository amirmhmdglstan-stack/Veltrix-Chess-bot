"""
chesslib.py - small pure-Python chess rules library for Veltrix 1.0.

Zero external dependencies. Used by the GUI, the match runner, the SPRT
runner and the EPD suite runner. Supports:

    * FEN parsing / generation
    * fully legal move generation (checks handled)
    * UCI <-> SAN conversion (with full disambiguation and +/# suffixes)
    * make / undo with stacks (push / pop)
    * game-end detection: checkmate, stalemate, 50-move rule,
      threefold repetition, insufficient material
    * PGN export

Board encoding: list of 64 chars, a1 = 0 .. h8 = 63, pieces as FEN letters
('P','N','B','R','Q','K','p','n','b','r','q','k', '.' = empty).

This code is original to the Veltrix project (GPL-3.0).
"""
from __future__ import annotations

STARTPOS_FEN = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"

FILES = "abcdefgh"
KNIGHT_OFFS = [(1, 2), (2, 1), (2, -1), (1, -2), (-1, -2), (-2, -1), (-2, 1), (-1, 2)]
KING_OFFS = [(1, 0), (1, 1), (0, 1), (-1, 1), (-1, 0), (-1, -1), (0, -1), (1, -1)]
BISHOP_DIRS = [(1, 1), (1, -1), (-1, 1), (-1, -1)]
ROOK_DIRS = [(1, 0), (-1, 0), (0, 1), (0, -1)]
QUEEN_DIRS = KING_OFFS
PIECE_VALS = {"P": 100, "N": 320, "B": 330, "R": 500, "Q": 900, "K": 0}


def sq_name(sq: int) -> str:
    return FILES[sq % 8] + str(sq // 8 + 1)


def parse_sq(name: str) -> int:
    return FILES.index(name[0]) + (int(name[1]) - 1) * 8


def color_of(p: str) -> str:
    return "w" if p.isupper() else "b"


class Move:
    __slots__ = ("frm", "to", "promo", "ep", "castle")

    def __init__(self, frm: int, to: int, promo: str = "", ep: bool = False, castle: bool = False):
        self.frm, self.to, self.promo, self.ep, self.castle = frm, to, promo, ep, castle

    def uci(self) -> str:
        return sq_name(self.frm) + sq_name(self.to) + self.promo

    def __eq__(self, o):
        return isinstance(o, Move) and (self.frm, self.to, self.promo) == (o.frm, o.to, o.promo)

    def __hash__(self):
        return hash((self.frm, self.to, self.promo))

    def __repr__(self):
        return f"Move({self.uci()})"


class Board:
    def __init__(self, fen: str = STARTPOS_FEN):
        self.set_fen(fen)

    # ------------------------------------------------------------------ fen
    def set_fen(self, fen: str):
        parts = fen.strip().split()
        if len(parts) < 4:
            raise ValueError("bad FEN: " + fen)
        self.board = ["."] * 64
        rows = parts[0].split("/")
        if len(rows) != 8:
            raise ValueError("bad FEN ranks: " + fen)
        for ri, row in enumerate(rows):
            f = 0
            for ch in row:
                if ch.isdigit():
                    f += int(ch)
                elif ch in "PNBRQKpnbrqk":
                    self.board[(7 - ri) * 8 + f] = ch
                    f += 1
                else:
                    raise ValueError("bad FEN char: " + ch)
            if f != 8:
                raise ValueError("bad FEN row length")
        self.stm = parts[1]
        self.castling = parts[2]
        self.ep = -1 if parts[3] == "-" else parse_sq(parts[3])
        self.halfmove = int(parts[4]) if len(parts) > 4 else 0
        self.fullmove = int(parts[5]) if len(parts) > 5 else 1
        # move history stacks
        self._undo = []            # (move, captured, castling, ep, halfmove)
        self._keys = [self.pos_key()]

    def fen(self) -> str:
        rows = []
        for r in range(7, -1, -1):
            row, empty = "", 0
            for f in range(8):
                p = self.board[r * 8 + f]
                if p == ".":
                    empty += 1
                else:
                    if empty:
                        row += str(empty)
                        empty = 0
                    row += p
            if empty:
                row += str(empty)
            rows.append(row)
        return ("/".join(rows) + f" {self.stm} {self.castling} "
                f"{sq_name(self.ep) if self.ep >= 0 else '-'} {self.halfmove} {self.fullmove}")

    def pos_key(self):
        return (tuple(self.board), self.stm, self.castling, self.ep)

    def moves_uci(self):
        return [m.uci() for m in self._undo_moves()] if False else None

    # -------------------------------------------------------------- helpers
    def king_sq(self, c: str) -> int:
        k = "K" if c == "w" else "k"
        return self.board.index(k)

    def is_attacked(self, sq: int, by_color: str) -> bool:
        f, r = sq % 8, sq // 8
        b = self.board
        dr = 1 if by_color == "w" else -1
        pchar = "P" if by_color == "w" else "p"
        for df in (-1, 1):
            ff, rr = f + df, r - dr
            if 0 <= ff < 8 and 0 <= rr < 8 and b[rr * 8 + ff] == pchar:
                return True
        nchar = "N" if by_color == "w" else "n"
        for df, dr2 in KNIGHT_OFFS:
            ff, rr = f + df, r + dr2
            if 0 <= ff < 8 and 0 <= rr < 8 and b[rr * 8 + ff] == nchar:
                return True
        kchar = "K" if by_color == "w" else "k"
        for df, dr2 in KING_OFFS:
            ff, rr = f + df, r + dr2
            if 0 <= ff < 8 and 0 <= rr < 8 and b[rr * 8 + ff] == kchar:
                return True
        for dirs, chars in ((BISHOP_DIRS, "BQ" if by_color == "w" else "bq"),
                            (ROOK_DIRS, "RQ" if by_color == "w" else "rq")):
            for df, dr2 in dirs:
                ff, rr = f + df, r + dr2
                while 0 <= ff < 8 and 0 <= rr < 8:
                    p = b[rr * 8 + ff]
                    if p != ".":
                        if p in chars:
                            return True
                        break
                    ff += df
                    rr += dr2
        return False

    def in_check(self, c: str = "") -> bool:
        c = c or self.stm
        return self.is_attacked(self.king_sq(c), "b" if c == "w" else "w")

    # --------------------------------------------------------------- movegen
    def _pseudo(self):
        b = self.board
        stm = self.stm
        mine = (lambda p: p.isupper()) if stm == "w" else (lambda p: p.islower())
        theirs = (lambda p: p.islower()) if stm == "w" else (lambda p: p.isupper())
        for sq in range(64):
            p = b[sq]
            if p == "." or not mine(p):
                continue
            f, r = sq % 8, sq // 8
            pt = p.upper()
            if pt == "P":
                dr, start_rank, promo_rank = (1, 1, 6) if stm == "w" else (-1, 6, 1)
                t = sq + dr * 8
                if b[t] == ".":
                    if r == promo_rank:
                        for pro in "qrbn":
                            yield Move(sq, t, pro)
                    else:
                        yield Move(sq, t)
                        if r == start_rank and b[t + dr * 8] == ".":
                            yield Move(sq, t + dr * 8)
                for df in (-1, 1):
                    ff = f + df
                    if 0 <= ff < 8:
                        tt = sq + dr * 8 + df
                        tp = b[tt]
                        if tp != "." and theirs(tp):
                            if r == promo_rank:
                                for pro in "qrbn":
                                    yield Move(sq, tt, pro)
                            else:
                                yield Move(sq, tt)
                        if tt == self.ep:
                            yield Move(sq, tt, ep=True)
            elif pt == "N":
                for df, dr2 in KNIGHT_OFFS:
                    ff, rr = f + df, r + dr2
                    if 0 <= ff < 8 and 0 <= rr < 8:
                        t = rr * 8 + ff
                        if b[t] == "." or theirs(b[t]):
                            yield Move(sq, t)
            elif pt == "K":
                for df, dr2 in KING_OFFS:
                    ff, rr = f + df, r + dr2
                    if 0 <= ff < 8 and 0 <= rr < 8:
                        t = rr * 8 + ff
                        if b[t] == "." or theirs(b[t]):
                            yield Move(sq, t)
                if stm == "w" and sq == 4:
                    if "K" in self.castling and b[5] == b[6] == "." and \
                            not self.is_attacked(4, "b") and not self.is_attacked(5, "b") and \
                            not self.is_attacked(6, "b"):
                        yield Move(4, 6, castle=True)
                    if "Q" in self.castling and b[1] == b[2] == b[3] == "." and \
                            not self.is_attacked(4, "b") and not self.is_attacked(3, "b") and \
                            not self.is_attacked(2, "b"):
                        yield Move(4, 2, castle=True)
                if stm == "b" and sq == 60:
                    if "k" in self.castling and b[61] == b[62] == "." and \
                            not self.is_attacked(60, "w") and not self.is_attacked(61, "w") and \
                            not self.is_attacked(62, "w"):
                        yield Move(60, 62, castle=True)
                    if "q" in self.castling and b[57] == b[58] == b[59] == "." and \
                            not self.is_attacked(60, "w") and not self.is_attacked(59, "w") and \
                            not self.is_attacked(58, "w"):
                        yield Move(60, 58, castle=True)
            else:
                dirs = BISHOP_DIRS if pt == "B" else ROOK_DIRS if pt == "R" else QUEEN_DIRS
                for df, dr2 in dirs:
                    ff, rr = f + df, r + dr2
                    while 0 <= ff < 8 and 0 <= rr < 8:
                        t = rr * 8 + ff
                        if b[t] == ".":
                            yield Move(sq, t)
                        else:
                            if theirs(b[t]):
                                yield Move(sq, t)
                            break
                        ff += df
                        rr += dr2

    def legal_moves(self):
        out = []
        for m in self._pseudo():
            self.push(m)
            if not self.in_check(self.stm == "w" and "b" or "w"):
                out.append(m)
            self.pop()
        return out

    # -------------------------------------------------------------- make/undo
    def push(self, m: Move):
        b = self.board
        piece = b[m.frm]
        captured = b[m.to]
        self._undo.append((m, captured, self.castling, self.ep, self.halfmove))
        was_cap = captured != "." or m.ep
        b[m.frm] = "."
        if m.promo:
            b[m.to] = m.promo.upper() if self.stm == "w" else m.promo.lower()
        else:
            b[m.to] = piece
        if m.ep:
            b[m.to - 8 if self.stm == "w" else m.to + 8] = "."
        if piece in "Kk":
            self.castling = (self.castling.replace("K", "").replace("Q", "")
                             if self.stm == "w" else
                             self.castling.replace("k", "").replace("q", ""))
        for sq, letter in ((0, "Q"), (7, "K"), (56, "q"), (63, "k")):
            if m.frm == sq or m.to == sq:
                self.castling = self.castling.replace(letter, "")
        if not self.castling:
            self.castling = "-"
        if m.castle:
            if m.to == 6:
                b[5], b[7] = "R", "."
            elif m.to == 2:
                b[3], b[0] = "R", "."
            elif m.to == 62:
                b[61], b[63] = "r", "."
            elif m.to == 58:
                b[59], b[56] = "r", "."
        self.ep = -1
        if piece.upper() == "P" and abs(m.to - m.frm) == 16:
            self.ep = (m.to + m.frm) // 2
        self.halfmove = 0 if (was_cap or piece.upper() == "P") else self.halfmove + 1
        if self.stm == "b":
            self.fullmove += 1
        self.stm = "b" if self.stm == "w" else "w"
        self._keys.append(self.pos_key())

    def pop(self):
        m, captured, self.castling, self.ep, self.halfmove = self._undo.pop()
        b = self.board
        self.stm = "b" if self.stm == "w" else "w"
        if self.stm == "b":
            self.fullmove -= 1
        piece = b[m.to]
        if m.promo:
            piece = "P" if self.stm == "w" else "p"
        b[m.frm] = piece
        b[m.to] = captured
        if m.ep:
            b[m.to] = "."
            b[m.to - 8 if self.stm == "w" else m.to + 8] = "p" if self.stm == "w" else "P"
        if m.castle:
            if m.to == 6:
                b[7], b[5] = "R", "."
            elif m.to == 2:
                b[0], b[3] = "R", "."
            elif m.to == 62:
                b[63], b[61] = "r", "."
            elif m.to == 58:
                b[56], b[59] = "r", "."
        self._keys.pop()

    @property
    def move_stack(self):
        return [u[0] for u in self._undo]

    # ------------------------------------------------------------------- SAN
    def san(self, m: Move) -> str:
        piece = self.board[m.frm]
        pt = piece.upper()
        cap = self.board[m.to] != "." or m.ep
        disamb = ""
        if pt not in "PK":
            others = [o for o in self.legal_moves()
                      if o.to == m.to and o.frm != m.frm and self.board[o.frm].upper() == pt]
            if others:
                same_file = any(o.frm % 8 == m.frm % 8 for o in others)
                same_rank = any(o.frm // 8 == m.frm // 8 for o in others)
                if not same_file:
                    disamb = FILES[m.frm % 8]
                elif not same_rank:
                    disamb = str(m.frm // 8 + 1)
                else:
                    disamb = sq_name(m.frm)
        dest = sq_name(m.to)
        if pt == "P":
            s = (FILES[m.frm % 8] + "x" if cap else "") + dest
            if m.promo:
                s += "=" + m.promo.upper()
        elif m.castle:
            s = "O-O" if m.to % 8 == 6 else "O-O-O"
        else:
            s = pt + disamb + ("x" if cap else "") + dest
        self.push(m)
        chk = self.in_check(self.stm)
        n = len(self.legal_moves())
        self.pop()
        if n == 0 and chk:
            s += "#"
        elif chk:
            s += "+"
        return s

    def parse_uci(self, uci: str) -> Move:
        for m in self.legal_moves():
            if m.uci() == uci:
                return m
        raise ValueError("illegal uci move: " + uci + " in " + self.fen())

    # -------------------------------------------------------------- game end
    def insufficient_material(self) -> bool:
        pieces = [p for p in self.board if p != "." and p.upper() != "K"]
        if not pieces:
            return True
        if all(p.upper() in "BN" for p in pieces):
            if len(pieces) == 1:
                return True
            wb = [i for i, p in enumerate(self.board) if p == "B"]
            bb_ = [i for i, p in enumerate(self.board) if p == "b"]
            if wb and bb_ and len(pieces) == 2 and not any(p.upper() == "N" for p in pieces):
                if ((wb[0] // 8 + wb[0] % 8) & 1) == ((bb_[0] // 8 + bb_[0] % 8) & 1):
                    return True
        return False

    def outcome(self):
        """Return (result, reason) or None if the game goes on."""
        legal = self.legal_moves()
        if not legal:
            if self.in_check(self.stm):
                return ("0-1" if self.stm == "w" else "1-0", "checkmate")
            return ("1/2-1/2", "stalemate")
        if self.insufficient_material():
            return ("1/2-1/2", "insufficient material")
        if self.halfmove >= 100:
            return ("1/2-1/2", "fifty-move rule")
        cur = self.pos_key()
        if sum(1 for k in self._keys if k == cur) >= 3:
            return ("1/2-1/2", "threefold repetition")
        return None

    def copy(self) -> "Board":
        nb = Board.__new__(Board)
        nb.set_fen(self.fen())
        return nb


def perft(board: Board, depth: int) -> int:
    if depth == 0:
        return 1
    n = 0
    for m in board._pseudo():
        board.push(m)
        if not board.in_check("b" if board.stm == "w" else "w"):
            n += perft(board, depth - 1)
        board.pop()
    return n


def game_pgn(fen_initial: str, moves_san, white: str, black: str, result: str,
             date: str = "", event: str = "Veltrix match") -> str:
    from datetime import datetime
    if not date:
        date = datetime.now().strftime("%Y.%m.%d")
    headers = (f'[Event "{event}"]\n[Site "local"]\n[Date "{date}"]\n'
               f'[White "{white}"]\n[Black "{black}"]\n[Result "{result}"]')
    if fen_initial != STARTPOS_FEN:
        headers += f'\n[SetUp "1"]\n[FEN "{fen_initial}"]'
    parts = []
    for i, s in enumerate(moves_san):
        if i % 2 == 0:
            parts.append(f"{i // 2 + 1}.")
        parts.append(s)
    parts.append(result)
    lines, cur = [], ""
    for tok in parts:
        if len(cur) + len(tok) + 1 > 79:
            lines.append(cur)
            cur = tok
        else:
            cur += (" " if cur else "") + tok
    if cur:
        lines.append(cur)
    return headers + "\n\n" + "\n".join(lines) + "\n"


if __name__ == "__main__":
    b = Board()
    for d, expect in [(1, 20), (2, 400), (3, 8902), (4, 197281), (5, 4865609)]:
        got = perft(b, d)
        assert got == expect, (d, got, expect)
        print(f"perft({d}) = {got} OK")
    b2 = Board("r3k2r/p1ppqpb1/bn2pnp1/3PN3/1p2P3/2N2Q1p/PPPBBPPP/R3K2R w KQkq - 0 1")
    for d, expect in [(1, 48), (2, 2039), (3, 97862), (4, 4085603)]:
        got = perft(b2, d)
        assert got == expect, (d, got, expect)
        print(f"kiwipete perft({d}) = {got} OK")
    # SAN sanity
    b3 = Board()
    san_line = []
    for u in ["e2e4", "e7e5", "g1f3", "b8c6", "f1b5", "a7a6", "e1g1", "g8f6", "f1e1"]:
        m = b3.parse_uci(u)
        san_line.append(b3.san(m))
        b3.push(m)
    assert san_line == ["e4", "e5", "Nf3", "Nc6", "Bb5", "a6", "O-O", "Nf6", "Re1"], san_line
    print("SAN:", " ".join(san_line))
    # mate detection
    b4 = Board("r1bqkbnr/pppp1ppp/2n5/4p2Q/2B1P3/8/PPPP1PPP/RNB1K1NR w KQkq - 0 1")
    m = b4.parse_uci("h5f7")
    assert b4.san(m) == "Qxf7#", b4.san(m)
    b4.push(m)
    assert b4.outcome() == ("0-1" if b4.stm == "w" else "1-0", "checkmate")
    print("SAN mate detection OK:", b4.outcome())
    print("chesslib self-test OK")
