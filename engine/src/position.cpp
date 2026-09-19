// Veltrix 1.0 - position implementation
// Copyright (C) 2026 Veltrix Project
// SPDX-License-Identifier: GPL-3.0-or-later
#include "position.h"
#include <sstream>
#include <cstring>
#include <algorithm>

namespace Veltrix {

// ZobristPiece is indexed with the Piece enum, which deliberately contains
// the NO_PIECE sentinel (= 12, == PIECE_NB). All call sites use real pieces
// (0..11) and put_piece()/remove_piece() explicitly guard on NO_PIECE, so
// rows 12..15 are never *intended* to be touched. They are nonetheless kept
// zero-filled on purpose:
//   * an accidental sentinel lookup becomes a defined hash NO-OP (xor 0)
//     instead of undefined behaviour via an out-of-bounds read, and
//   * the compiler can therefore prove every access in-bounds instead of
//     warning about it (-Warray-bounds with the sentinel in the enum range).
U64 ZobristPiece[16][64];
U64 ZobristSide;
static_assert(NO_PIECE < 16, "ZobristPiece must cover the NO_PIECE sentinel");
U64 ZobristCastling[16];
U64 ZobristEp[8];
int CastlingMask[64];

namespace {
struct SplitMix {
    U64 s;
    explicit SplitMix(U64 seed) : s(seed) {}
    U64 next() {
        U64 z = (s += 0x9E3779B97F4A7C15ULL);
        z = (z ^ (z >> 30)) * 0xBF58476D1CE4E5B9ULL;
        z = (z ^ (z >> 27)) * 0x94D049BB133111EBULL;
        return z ^ (z >> 31);
    }
};
} // namespace

void init_zobrist() {
    static bool done = false;
    if (done) return;
    done = true;
    SplitMix rng(0x600DF00DCAFEBABEULL);
    for (int p = 0; p < PIECE_NB; ++p)
        for (int s = 0; s < 64; ++s)
            ZobristPiece[p][s] = rng.next();
    ZobristSide = rng.next();
    for (int i = 0; i < 16; ++i) ZobristCastling[i] = rng.next();
    for (int i = 0; i < 8; ++i) ZobristEp[i] = rng.next();
}

void init_castling_masks() {
    static bool done = false;
    if (done) return;
    done = true;
    for (int i = 0; i < 64; ++i) CastlingMask[i] = ALL_CASTLING;
    CastlingMask[4]  &= ~int(WHITE_OO | WHITE_OOO);   // e1
    CastlingMask[0]  &= ~int(WHITE_OOO);              // a1
    CastlingMask[7]  &= ~int(WHITE_OO);               // h1
    CastlingMask[60] &= ~int(BLACK_OO | BLACK_OOO);   // e8
    CastlingMask[56] &= ~int(BLACK_OOO);              // a8
    CastlingMask[63] &= ~int(BLACK_OO);               // h8
}

// ------------------------------------------------------------------ helpers --
void Position::put_piece(Piece p, int sq) {
    if (p == NO_PIECE) return;
    board[sq] = p;
    U64 b = BB::square_bb(sq);
    byPieceBB[p] |= b;
    byColorBB[color_of(p)] |= b;
    ++pieceCount[p];
    if (ptype_of(p) == KING) kingSquare[color_of(p)] = sq;
}

void Position::remove_piece(int sq) {
    Piece p = board[sq];
    if (p == NO_PIECE) return;
    U64 b = BB::square_bb(sq);
    byPieceBB[p] &= ~b;
    byColorBB[color_of(p)] &= ~b;
    --pieceCount[p];
    board[sq] = NO_PIECE;
}

void Position::move_piece(int from, int to) {
    Piece p = board[from];
    if (p == NO_PIECE || p == board[to]) return;
    U64 b = BB::square_bb(from) | BB::square_bb(to);
    byPieceBB[p] ^= b;
    byColorBB[color_of(p)] ^= b;
    board[from] = NO_PIECE;
    board[to] = p;
    if (ptype_of(p) == KING) kingSquare[color_of(p)] = to;
}

// ---------------------------------------------------------------------- FEN --
void Position::set_startpos() { set_fen(STARTPOS_FEN); }

bool Position::set_fen(const std::string& fen) {
    for (int i = 0; i < 64; ++i) board[i] = NO_PIECE;
    std::memset(byPieceBB, 0, sizeof(byPieceBB));
    std::memset(byColorBB, 0, sizeof(byColorBB));
    std::memset(pieceCount, 0, sizeof(pieceCount));
    kingSquare[WHITE] = kingSquare[BLACK] = SQ_NONE;
    stIdx = 0;
    StateInfo& st = stateStack[0];
    st = StateInfo();

    std::istringstream iss(fen);
    std::string boardPart, sidePart, castlingPart, epPart;
    int halfmove = 0, fullmove = 1;
    if (!(iss >> boardPart)) return false;
    if (!(iss >> sidePart)) sidePart = "w";
    if (!(iss >> castlingPart)) castlingPart = "-";
    if (!(iss >> epPart)) epPart = "-";
    if (!(iss >> halfmove)) halfmove = 0;
    if (!(iss >> fullmove)) fullmove = 1;

    int rank = 7, file = 0;
    int kings = 0;
    for (char c : boardPart) {
        if (c == '/') {
            if (file != 8) return false;
            file = 0;
            --rank;
            if (rank < 0) return false;
        } else if (c >= '1' && c <= '8') {
            file += c - '0';
            if (file > 8) return false;
        } else {
            int p = piece_from_char(c);
            if (p == NO_PIECE || file > 7 || rank < 0) return false;
            if ((ptype_of(Piece(p)) == PAWN) && (rank == 0 || rank == 7)) return false;
            if (ptype_of(Piece(p)) == KING) ++kings;
            put_piece(Piece(p), make_square(file, rank));
            ++file;
        }
    }
    if (rank != 0 || file != 8 || kings != 2) return false;
    if (kingSquare[WHITE] == SQ_NONE || kingSquare[BLACK] == SQ_NONE) return false;

    sideToMove = (sidePart == "b" || sidePart == "B") ? BLACK : (sidePart == "w" || sidePart == "W") ? WHITE : WHITE;
    if (sidePart != "w" && sidePart != "b") return false;

    int cr = NO_CASTLING;
    if (castlingPart != "-") {
        for (char c : castlingPart) {
            if (c == 'K') cr |= WHITE_OO;
            else if (c == 'Q') cr |= WHITE_OOO;
            else if (c == 'k') cr |= BLACK_OO;
            else if (c == 'q') cr |= BLACK_OOO;
            else return false;
        }
    }
    st.castlingRights = cr;

    int epSq = SQ_NONE;
    if (epPart != "-") {
        epSq = sq_from_str(epPart);
        if (epSq == SQ_NONE) return false;
        int er = rank_of(epSq);
        if (!((sideToMove == BLACK && er == 2) || (sideToMove == WHITE && er == 5)))
            return false;
    }
    st.epSquare = epSq;
    st.halfmoveClock = std::max(0, halfmove);
    st.fullmoveNumber = std::max(1, fullmove);
    st.captured = NO_PIECE;

    st.key = 0;
    for (int s = 0; s < 64; ++s)
        if (board[s] != NO_PIECE)
            st.key ^= ZobristPiece[board[s]][s];
    st.pawnKey = 0;
    for (int s = 0; s < 64; ++s) {
        Piece p = board[s];
        if (p != NO_PIECE && ptype_of(p) == PAWN)
            st.pawnKey ^= ZobristPiece[p][s];
    }
    if (sideToMove == BLACK) st.key ^= ZobristSide;
    st.key ^= ZobristCastling[cr];
    if (epSq != SQ_NONE) {
        // hash ep file only if a capture is pseudo-possible (same rule as do_move)
        if (PawnAttacks[~sideToMove][epSq] & byPieceBB[make_piece(sideToMove, PAWN)])
            st.key ^= ZobristEp[file_of(epSq)];
    }

    st.checkersBB = attackers_to(kingSquare[sideToMove]) & byColorBB[~sideToMove];

    // a position with the side NOT to move in check is illegal
    if (attackers_to(kingSquare[~sideToMove]) & byColorBB[sideToMove])
        return false;

    return true;
}

std::string Position::fen() const {
    std::ostringstream os;
    for (int r = 7; r >= 0; --r) {
        int empty = 0;
        for (int f = 0; f < 8; ++f) {
            Piece p = board[make_square(f, r)];
            if (p == NO_PIECE) {
                ++empty;
            } else {
                if (empty) { os << empty; empty = 0; }
                os << piece_char(p);
            }
        }
        if (empty) os << empty;
        if (r) os << '/';
    }
    os << (sideToMove == WHITE ? " w " : " b ");
    int cr = st().castlingRights;
    if (cr == NO_CASTLING) os << '-';
    else {
        if (cr & WHITE_OO) os << 'K';
        if (cr & WHITE_OOO) os << 'Q';
        if (cr & BLACK_OO) os << 'k';
        if (cr & BLACK_OOO) os << 'q';
    }
    os << ' ';
    if (st().epSquare != SQ_NONE) os << sq_to_str(st().epSquare);
    else os << '-';
    os << ' ' << st().halfmoveClock << ' ' << st().fullmoveNumber;
    return os.str();
}

// ------------------------------------------------------------------ attacks --
U64 Position::attackers_to(int sq, U64 occupied) const {
    U64 a = (PawnAttacks[BLACK][sq] & byPieceBB[W_PAWN])
          | (PawnAttacks[WHITE][sq] & byPieceBB[B_PAWN])
          | (KnightAttacks[sq] & (byPieceBB[W_KNIGHT] | byPieceBB[B_KNIGHT]))
          | (KingAttacks[sq] & (byPieceBB[W_KING] | byPieceBB[B_KING]))
          | (bishop_attacks(occupied, sq) &
             (byPieceBB[W_BISHOP] | byPieceBB[B_BISHOP] | byPieceBB[W_QUEEN] | byPieceBB[B_QUEEN]))
          | (rook_attacks(occupied, sq) &
             (byPieceBB[W_ROOK] | byPieceBB[B_ROOK] | byPieceBB[W_QUEEN] | byPieceBB[B_QUEEN]));
    return a & occupied;
}

U64 Position::pinned_pieces(Color c) const {
    U64 pinned = 0;
    int ksq = kingSquare[c];
    Color them = ~c;
    U64 snipers =
        ((PseudoAttacks[ROOK][ksq] & (pieces(them, ROOK) | pieces(them, QUEEN))) |
         (PseudoAttacks[BISHOP][ksq] & (pieces(them, BISHOP) | pieces(them, QUEEN))));
    U64 own = pieces(c);
    while (snipers) {
        int s = BB::pop_lsb_sq(snipers);
        U64 b = BetweenBB[ksq][s] & own;
        if (b && !BB::more_than_one(b)) pinned |= b;
    }
    return pinned;
}

// ---------------------------------------------------------------- make moves --
void Position::do_move(Move m) {
    StateInfo& cur = stateStack[stIdx];
    StateInfo& ns = stateStack[stIdx + 1];
    ns = cur;
    ++stIdx;

    const int from = from_sq(m);
    const int to = to_sq(m);
    const Color us = sideToMove;
    const Color them = ~us;
    const Piece pc = board[from];
    const PieceType pt = ptype_of(pc);
    const MoveFlag fl = flag_of(m);
    const Piece captured = (fl == MF_ENPASSANT) ? make_piece(them, PAWN) : board[to];

    ns.captured = captured;
    ns.epSquare = SQ_NONE;
    ns.halfmoveClock = cur.halfmoveClock + 1;
    if (us == BLACK) ns.fullmoveNumber = cur.fullmoveNumber + 1;

    U64 k = cur.key ^ ZobristSide;
    U64 pk = cur.pawnKey;

    // remove old ep hash if it had been included (same rule as the add)
    if (cur.epSquare != SQ_NONE) {
        if (PawnAttacks[them][cur.epSquare] & byPieceBB[make_piece(us, PAWN)])
            k ^= ZobristEp[file_of(cur.epSquare)];
    }

    // castling rights
    const int newCR = cur.castlingRights & CastlingMask[from] & CastlingMask[to];
    if (newCR != cur.castlingRights)
        k ^= ZobristCastling[cur.castlingRights] ^ ZobristCastling[newCR];
    ns.castlingRights = newCR;

    // captured piece
    if (captured != NO_PIECE) {
        int capsq = (fl == MF_ENPASSANT) ? (us == WHITE ? to - 8 : to + 8) : to;
        remove_piece(capsq);
        k ^= ZobristPiece[captured][capsq];
        if (ptype_of(captured) == PAWN) pk ^= ZobristPiece[captured][capsq];
        ns.halfmoveClock = 0;
    }
    if (pt == PAWN) ns.halfmoveClock = 0;

    // move the piece
    remove_piece(from);
    k ^= ZobristPiece[pc][from];
    if (pt == PAWN) pk ^= ZobristPiece[pc][from];

    if (fl == MF_CASTLING) {
        int rfrom, rto;
        if (to > from) { rfrom = ROOK_FROM_OO[us]; rto = ROOK_TO_OO[us]; }
        else           { rfrom = ROOK_FROM_OOO[us]; rto = ROOK_TO_OOO[us]; }
        move_piece(rfrom, rto);
        const Piece rook = make_piece(us, ROOK);
        k ^= ZobristPiece[rook][rfrom] ^ ZobristPiece[rook][rto];
    }

    const Piece placed = (fl == MF_PROMOTION) ? make_piece(us, promo_type(m)) : pc;
    put_piece(placed, to);
    k ^= ZobristPiece[placed][to];
    if (pt == PAWN && ptype_of(placed) == PAWN) pk ^= ZobristPiece[placed][to];

    // new en-passant square after double push
    if (pt == PAWN && (to ^ from) == 16) {
        int epsq = (us == WHITE) ? from + 8 : from - 8;
        ns.epSquare = epsq;
        if (PawnAttacks[us][epsq] & byPieceBB[make_piece(them, PAWN)])
            k ^= ZobristEp[file_of(epsq)];
    }

    ns.pawnKey = pk;
    ns.key = k;
    sideToMove = them;
    ns.checkersBB = attackers_to(kingSquare[them], pieces()) & byColorBB[us];
}

void Position::undo_move(Move m) {
    sideToMove = ~sideToMove;
    const Color us = sideToMove;
    const int from = from_sq(m);
    const int to = to_sq(m);
    const MoveFlag fl = flag_of(m);
    const StateInfo& ns = stateStack[stIdx];

    // move the moved piece back
    const Piece pcMoved = board[to];
    remove_piece(to);
    const Piece orig = (fl == MF_PROMOTION) ? make_piece(us, PAWN) : pcMoved;
    put_piece(orig, from);

    if (fl == MF_CASTLING) {
        int rfrom, rto;
        if (to > from) { rfrom = ROOK_FROM_OO[us]; rto = ROOK_TO_OO[us]; }
        else           { rfrom = ROOK_FROM_OOO[us]; rto = ROOK_TO_OOO[us]; }
        move_piece(rto, rfrom);
    }

    if (ns.captured != NO_PIECE) {
        int capsq = (fl == MF_ENPASSANT) ? (us == WHITE ? to - 8 : to + 8) : to;
        put_piece(ns.captured, capsq);
    }
    --stIdx;
}

void Position::do_null_move() {
    StateInfo& cur = stateStack[stIdx];
    StateInfo& ns = stateStack[stIdx + 1];
    ns = cur;
    ++stIdx;
    const Color us = sideToMove;
    ns.captured = NO_PIECE;
    ns.halfmoveClock = cur.halfmoveClock + 1;
    if (us == BLACK) ns.fullmoveNumber = cur.fullmoveNumber + 1;
    U64 k = cur.key ^ ZobristSide;
    if (cur.epSquare != SQ_NONE) {
        const Color them = ~us;
        if (PawnAttacks[them][cur.epSquare] & byPieceBB[make_piece(us, PAWN)])
            k ^= ZobristEp[file_of(cur.epSquare)];
    }
    ns.epSquare = SQ_NONE;
    ns.key = k;
    sideToMove = ~us;
    ns.checkersBB = 0;  // passing can never give check
}

void Position::undo_null_move() {
    sideToMove = ~sideToMove;
    --stIdx;
}

// ------------------------------------------------------------ move validation --
bool Position::is_legal_move(Move m) const {
    if (m == MOVE_NONE || m == MOVE_NULL) return false;
    const int from = from_sq(m);
    const int to = to_sq(m);
    if (from == to || from < 0 || from > 63 || to < 0 || to > 63) return false;
    const Piece pc = board[from];
    if (pc == NO_PIECE || color_of(pc) != sideToMove) return false;
    const Piece target = board[to];
    const Color us = sideToMove;
    const MoveFlag fl = flag_of(m);
    const PieceType pt = ptype_of(pc);

    if (fl == MF_CASTLING) {
        if (pt != KING || us != sideToMove) return false;
        if (from != CASTLE_KING_FROM[us]) return false;
        if (in_check()) return false;
        U64 occ = pieces();
        if (us == WHITE) {
            if (to == 6 && (st().castlingRights & WHITE_OO)) {
                if (board[7] != W_ROOK) return false;
                if (occ & (BB::square_bb(5) | BB::square_bb(6))) return false;
                if (attacked_by(5, BLACK) || attacked_by(6, BLACK)) return false;
                return true;
            }
            if (to == 2 && (st().castlingRights & WHITE_OOO)) {
                if (board[0] != W_ROOK) return false;
                if (occ & (BB::square_bb(1) | BB::square_bb(2) | BB::square_bb(3))) return false;
                if (attacked_by(3, BLACK) || attacked_by(2, BLACK)) return false;
                return true;
            }
            return false;
        } else {
            if (to == 62 && (st().castlingRights & BLACK_OO)) {
                if (board[63] != B_ROOK) return false;
                if (occ & (BB::square_bb(61) | BB::square_bb(62))) return false;
                if (attacked_by(61, WHITE) || attacked_by(62, WHITE)) return false;
                return true;
            }
            if (to == 58 && (st().castlingRights & BLACK_OOO)) {
                if (board[56] != B_ROOK) return false;
                if (occ & (BB::square_bb(57) | BB::square_bb(58) | BB::square_bb(59))) return false;
                if (attacked_by(59, WHITE) || attacked_by(58, WHITE)) return false;
                return true;
            }
            return false;
        }
    }

    if (target != NO_PIECE && color_of(target) == us) return false;

    if (pt == PAWN) {
        const int dir = (us == WHITE) ? 8 : -8;
        const int startRank = (us == WHITE) ? 1 : 6;
        const int promoRank = (us == WHITE) ? 7 : 0;
        const bool reachesPromo = rank_of(to) == promoRank;
        if (fl == MF_PROMOTION) {
            if (!reachesPromo) return false;
        } else if (reachesPromo) {
            return false;  // a pawn reaching the last rank must promote
        }
        const int df = file_of(to) - file_of(from);
        if (fl == MF_ENPASSANT) {
            if (st().epSquare == SQ_NONE || to != st().epSquare) return false;
            if (std::abs(df) != 1 || to != from + dir + df) return false;
            int capsq = (us == WHITE) ? to - 8 : to + 8;
            if (board[capsq] != make_piece(~us, PAWN)) return false;
        } else if (to == from + dir) {
            if (target != NO_PIECE) return false;
        } else if (to == from + 2 * dir) {
            if (rank_of(from) != startRank || target != NO_PIECE || board[from + dir] != NO_PIECE)
                return false;
        } else {
            // diagonal capture
            if (std::abs(df) != 1 || to != from + dir + df) return false;
            if (target == NO_PIECE) return false;
        }
    } else {
        if (fl != MF_NORMAL) return false;
        U64 at = attacks_bb(pt, from, pieces());
        if (!(at & BB::square_bb(to))) return false;
    }

    // pseudo-legal; now test for own-king safety
    Position tmp = *this;
    tmp.do_move(m);
    return !tmp.attacked_by(tmp.kingSquare[us], ~us);
}

// ------------------------------------------------------------------- SEE ----
bool Position::see_ge(Move m, int threshold) const {
    if (m == MOVE_NONE || m == MOVE_NULL) return true;

    static const int v[7] = { 100, 320, 330, 500, 950, 10000, 0 };
    const int from = from_sq(m);
    const int to = to_sq(m);
    const MoveFlag fl = flag_of(m);

    // value of the captured piece (en passant handled)
    int victimVal;
    if (fl == MF_ENPASSANT)
        victimVal = v[PAWN];
    else
        victimVal = (board[to] == NO_PIECE) ? 0 : v[ptype_of(board[to])];
    if (fl == MF_PROMOTION) victimVal += v[promo_type(m)] - v[PAWN];

    int swap = victimVal - threshold;
    if (swap < 0) return false;

    if (board[from] == NO_PIECE) return true;  // defensive; callers pass generated moves
    int attackerVal = v[ptype_of(board[from])];
    if (fl == MF_PROMOTION) attackerVal = v[promo_type(m)];

    swap = attackerVal - swap;
    if (swap <= 0) return true;

    U64 occ = pieces() | BB::square_bb(to);
    occ &= ~BB::square_bb(from);
    if (fl == MF_ENPASSANT)
        occ &= ~BB::square_bb(sideToMove == WHITE ? to - 8 : to + 8);

    U64 attackers = attackers_to(to, occ);
    Color stm = sideToMove;  // pre-flipped by the loop; the opponent recaptures first
    bool res = true;

    for (;;) {
        stm = ~stm;                    // side that attempts to (re)capture
        attackers &= occ;
        U64 stmAttackers = attackers & byColorBB[stm];
        if (!stmAttackers) break;      // cannot recapture: previous capture stands
        res = !res;

        // least valuable attacker of stm moves first; the king is tried last
        PieceType pt = KING;
        U64 bb = 0;
        for (int p = PAWN; p <= QUEEN; ++p) {
            bb = stmAttackers & pieces(PieceType(p));
            if (bb) { pt = PieceType(p); break; }
        }

        if (pt == KING) {
            // The king may only capture if the square is not still defended by
            // the other side (a king can never capture into a defended square).
            return (attackers & occ & byColorBB[~stm]) ? !res : res;
        }

        swap = v[pt] - swap;
        if (swap < res) break;

        // remove the attacker from the occupancy and reveal X-ray attackers
        occ &= ~BB::square_bb(BB::lsb(bb));
        if (pt == PAWN || pt == BISHOP || pt == QUEEN)
            attackers |= bishop_attacks(occ, to) & (pieces(BISHOP) | pieces(QUEEN));
        if (pt == ROOK || pt == QUEEN)
            attackers |= rook_attacks(occ, to) & (pieces(ROOK) | pieces(QUEEN));
    }
    return res;
}

// ------------------------------------------------------------------ draws ---
bool Position::is_repetition() const {
    int limit = stIdx - st().halfmoveClock;
    if (limit < 0) limit = 0;
    for (int i = stIdx - 2; i >= limit; i -= 2)
        if (stateStack[i].key == st().key)
            return true;
    return false;
}

bool Position::insufficient_material() const {
    if (pieces(PAWN) || pieces(ROOK) || pieces(QUEEN)) return false;
    int wn = count(W_KNIGHT), wb = count(W_BISHOP);
    int bn = count(B_KNIGHT), bb = count(B_BISHOP);
    if (wn + wb <= 1 && bn + bb <= 1) return true;
    if (wn == 0 && bn == 0 && wb == 1 && bb == 1) {
        int wsq = BB::lsb(pieces(W_BISHOP));
        int bsq = BB::lsb(pieces(B_BISHOP));
        if (((wsq + rank_of(wsq)) & 1) == ((bsq + rank_of(bsq)) & 1)) return true;
    }
    return false;
}

bool Position::is_draw(int /*ply*/) const {
    if (st().halfmoveClock >= 100 && !in_check())
        return true;  // claimable; if in check the search's leaf mate test refines it
    if (insufficient_material()) return true;
    if (is_repetition()) return true;
    return false;
}

Value Position::material_value() const {
    static const int mv[PT_NB] = { 100, 320, 330, 500, 950, 0 };
    Value s = 0;
    for (int pt = PAWN; pt <= QUEEN; ++pt)
        s += mv[pt] * (count(WHITE, PieceType(pt)) - count(BLACK, PieceType(pt)));
    return sideToMove == WHITE ? s : -s;
}

// ----------------------------------------------------------------- hashing ---
U64 Position::key_from_scratch() const {
    U64 k = 0;
    for (int s = 0; s < 64; ++s)
        if (board[s] != NO_PIECE) k ^= ZobristPiece[board[s]][s];
    if (sideToMove == BLACK) k ^= ZobristSide;
    k ^= ZobristCastling[st().castlingRights];
    if (st().epSquare != SQ_NONE)
        if (PawnAttacks[~sideToMove][st().epSquare] & pieces(sideToMove, PAWN))
            k ^= ZobristEp[file_of(st().epSquare)];
    return k;
}

U64 Position::pawn_key_from_scratch() const {
    U64 k = 0;
    for (int s = 0; s < 64; ++s) {
        Piece p = board[s];
        if (p != NO_PIECE && ptype_of(p) == PAWN) k ^= ZobristPiece[p][s];
    }
    return k;
}

bool Position::pos_is_ok() const {
    if (key() != key_from_scratch()) return false;
    if (pawn_key() != pawn_key_from_scratch()) return false;
    for (int p = 0; p < PIECE_NB; ++p)
        if (pieceCount[p] != BB::popcnt(byPieceBB[p])) return false;
    for (int s = 0; s < 64; ++s) {
        Piece p = board[s];
        if (p != NO_PIECE && !(byPieceBB[p] & BB::square_bb(s))) return false;
    }
    if ((byColorBB[WHITE] & byColorBB[BLACK]) != 0) return false;
    return true;
}

std::string Position::pretty() const {
    std::ostringstream os;
    os << "\n  +---+---+---+---+---+---+---+---+\n";
    for (int r = 7; r >= 0; --r) {
        os << r + 1 << " |";
        for (int f = 0; f < 8; ++f)
            os << ' ' << piece_char(board[make_square(f, r)]) << " |";
        os << "\n  +---+---+---+---+---+---+---+---+\n";
    }
    os << "    a   b   c   d   e   f   g   h\n\n";
    os << "FEN: " << fen() << "\n";
    os << "Key: " << std::hex << key() << std::dec << "\n";
    if (in_check()) os << (sideToMove == WHITE ? "White" : "Black") << " is in check\n";
    return os.str();
}

} // namespace Veltrix
