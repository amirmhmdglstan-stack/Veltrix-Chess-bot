// Veltrix 1.0 - move generation
// Copyright (C) 2026 Veltrix Project
// SPDX-License-Identifier: GPL-3.0-or-later
#include "movegen.h"
#include <cstdio>

namespace Veltrix {

namespace {

template <Color Us>
ExtMove* gen_pawn_moves(const Position& pos, ExtMove* out) {
    constexpr Color Them = ~Us;
    constexpr int Dir = (Us == WHITE) ? 8 : -8;
    constexpr U64 RelRank7 = (Us == WHITE) ? BB::RANK_7 : BB::RANK_2;
    constexpr U64 RelBackRank = (Us == WHITE) ? BB::RANK_8 : BB::RANK_1;
    constexpr U64 DblRank = (Us == WHITE) ? BB::RANK_4 : BB::RANK_5;

    const U64 pawns = pos.pieces(Us, PAWN);
    const U64 empty = ~pos.pieces();
    const U64 enemy = pos.pieces(Them);

    // single pushes (excluding promotions)
    U64 push1 = (Us == WHITE ? BB::shift_n(pawns & ~RelRank7) : BB::shift_s(pawns & ~RelRank7)) & empty;
    // double pushes (two empty squares in a row, landing on the side's 4th rank)
    U64 push2 = (Us == WHITE ? BB::shift_n(push1) : BB::shift_s(push1)) & empty & DblRank;
    while (push1) {
        int to = BB::pop_lsb_sq(push1);
        *out++ = ExtMove{ make_move(to - Dir, to), 0 };
    }
    while (push2) {
        int to = BB::pop_lsb_sq(push2);
        *out++ = ExtMove{ make_move(to - 2 * Dir, to), 0 };
    }

    // promotions by push
    U64 ppush = (Us == WHITE ? BB::shift_n(pawns & RelRank7) : BB::shift_s(pawns & RelRank7)) & empty;
    while (ppush) {
        int to = BB::pop_lsb_sq(ppush);
        int from = to - Dir;
        *out++ = ExtMove{ make_move(from, to, MF_PROMOTION, QUEEN), 0 };
        *out++ = ExtMove{ make_move(from, to, MF_PROMOTION, ROOK), 0 };
        *out++ = ExtMove{ make_move(from, to, MF_PROMOTION, BISHOP), 0 };
        *out++ = ExtMove{ make_move(from, to, MF_PROMOTION, KNIGHT), 0 };
    }

    // captures (including en passant and capture-promotions)
    U64 capTargets = enemy;
    if (pos.ep_square() != SQ_NONE) capTargets |= BB::square_bb(pos.ep_square());

    U64 left = (Us == WHITE ? BB::shift_nw(pawns) : BB::shift_sw(pawns)) & capTargets;
    U64 right = (Us == WHITE ? BB::shift_ne(pawns) : BB::shift_se(pawns)) & capTargets;
    while (left) {
        int to = BB::pop_lsb_sq(left);
        int from = to - (Us == WHITE ? 7 : -9);
        if (BB::square_bb(to) & RelBackRank) {
            *out++ = ExtMove{ make_move(from, to, MF_PROMOTION, QUEEN), 0 };
            *out++ = ExtMove{ make_move(from, to, MF_PROMOTION, ROOK), 0 };
            *out++ = ExtMove{ make_move(from, to, MF_PROMOTION, BISHOP), 0 };
            *out++ = ExtMove{ make_move(from, to, MF_PROMOTION, KNIGHT), 0 };
        } else if (to == pos.ep_square()) {
            *out++ = ExtMove{ make_move(from, to, MF_ENPASSANT), 0 };
        } else {
            *out++ = ExtMove{ make_move(from, to), 0 };
        }
    }
    while (right) {
        int to = BB::pop_lsb_sq(right);
        int from = to - (Us == WHITE ? 9 : -7);
        if (BB::square_bb(to) & RelBackRank) {
            *out++ = ExtMove{ make_move(from, to, MF_PROMOTION, QUEEN), 0 };
            *out++ = ExtMove{ make_move(from, to, MF_PROMOTION, ROOK), 0 };
            *out++ = ExtMove{ make_move(from, to, MF_PROMOTION, BISHOP), 0 };
            *out++ = ExtMove{ make_move(from, to, MF_PROMOTION, KNIGHT), 0 };
        } else if (to == pos.ep_square()) {
            *out++ = ExtMove{ make_move(from, to, MF_ENPASSANT), 0 };
        } else {
            *out++ = ExtMove{ make_move(from, to), 0 };
        }
    }
    return out;
}

template <Color Us>
ExtMove* gen_piece_moves(const Position& pos, ExtMove* out) {
    constexpr Color Them = ~Us;
    const U64 own = pos.pieces(Us);
    const U64 occ = pos.pieces();
    const U64 targets = ~own;

    // knights
    U64 kn = pos.pieces(Us, KNIGHT);
    while (kn) {
        int from = BB::pop_lsb_sq(kn);
        U64 at = KnightAttacks[from] & targets;
        while (at) { int to = BB::pop_lsb_sq(at); *out++ = ExtMove{ make_move(from, to), 0 }; }
    }
    // bishops
    U64 b = pos.pieces(Us, BISHOP);
    while (b) {
        int from = BB::pop_lsb_sq(b);
        U64 at = bishop_attacks(occ, from) & targets;
        while (at) { int to = BB::pop_lsb_sq(at); *out++ = ExtMove{ make_move(from, to), 0 }; }
    }
    // rooks
    U64 r = pos.pieces(Us, ROOK);
    while (r) {
        int from = BB::pop_lsb_sq(r);
        U64 at = rook_attacks(occ, from) & targets;
        while (at) { int to = BB::pop_lsb_sq(at); *out++ = ExtMove{ make_move(from, to), 0 }; }
    }
    // queens
    U64 q = pos.pieces(Us, QUEEN);
    while (q) {
        int from = BB::pop_lsb_sq(q);
        U64 at = (bishop_attacks(occ, from) | rook_attacks(occ, from)) & targets;
        while (at) { int to = BB::pop_lsb_sq(at); *out++ = ExtMove{ make_move(from, to), 0 }; }
    }
    // king
    {
        int from = pos.king_sq(Us);
        U64 at = KingAttacks[from] & targets;
        while (at) { int to = BB::pop_lsb_sq(at); *out++ = ExtMove{ make_move(from, to), 0 }; }
    }
    (void)Them;
    return out;
}

template <Color Us>
ExtMove* gen_castles(const Position& pos, ExtMove* out) {
    constexpr Color Them = ~Us;
    const U64 occ = pos.pieces();
    const int kr = (Us == WHITE) ? 0 : 7;
    const int kfrom = make_square(4, kr);
    if (pos.in_check()) return out;
    // king side
    CastlingRight crKS = (Us == WHITE) ? WHITE_OO : BLACK_OO;
    if (pos.can_castle(crKS)) {
        int rfrom = make_square(7, kr);
        if (pos.piece_on(rfrom) == make_piece(Us, ROOK)) {
            int kto = make_square(6, kr);
            int rto = make_square(5, kr);
            if (!(occ & (BB::square_bb(kto) | BB::square_bb(rto))) &&
                !pos.attacked_by(rto, Them) && !pos.attacked_by(kto, Them)) {
                *out++ = ExtMove{ make_move(kfrom, kto, MF_CASTLING), 0 };
            }
        }
    }
    // queen side
    CastlingRight crQS = (Us == WHITE) ? WHITE_OOO : BLACK_OOO;
    if (pos.can_castle(crQS)) {
        int rfrom = make_square(0, kr);
        if (pos.piece_on(rfrom) == make_piece(Us, ROOK)) {
            int kto = make_square(2, kr);
            int rto = make_square(3, kr);
            int b1 = make_square(1, kr);
            if (!(occ & (BB::square_bb(b1) | BB::square_bb(kto) | BB::square_bb(rto))) &&
                !pos.attacked_by(rto, Them) && !pos.attacked_by(kto, Them)) {
                *out++ = ExtMove{ make_move(kfrom, kto, MF_CASTLING), 0 };
            }
        }
    }
    return out;
}

template <Color Us>
ExtMove* gen_all_impl(const Position& pos, ExtMove* out) {
    out = gen_pawn_moves<Us>(pos, out);
    out = gen_piece_moves<Us>(pos, out);
    out = gen_castles<Us>(pos, out);
    return out;
}

template <Color Us>
ExtMove* gen_captures_impl(const Position& pos, ExtMove* out) {
    constexpr Color Them = ~Us;
    constexpr int Dir = (Us == WHITE) ? 8 : -8;
    constexpr U64 RelRank7 = (Us == WHITE) ? BB::RANK_7 : BB::RANK_2;
    constexpr U64 RelBackRank = (Us == WHITE) ? BB::RANK_8 : BB::RANK_1;

    const U64 pawns = pos.pieces(Us, PAWN);
    const U64 empty = ~pos.pieces();
    const U64 occ = pos.pieces();
    const U64 enemy = pos.pieces(Them);
    const U64 targets = enemy;

    // pawn captures
    U64 capTargets = enemy;
    if (pos.ep_square() != SQ_NONE) capTargets |= BB::square_bb(pos.ep_square());
    U64 left = (Us == WHITE ? BB::shift_nw(pawns) : BB::shift_sw(pawns)) & capTargets;
    U64 right = (Us == WHITE ? BB::shift_ne(pawns) : BB::shift_se(pawns)) & capTargets;
    while (left) {
        int to = BB::pop_lsb_sq(left);
        int from = to - (Us == WHITE ? 7 : -9);
        if (BB::square_bb(to) & RelBackRank) {
            *out++ = ExtMove{ make_move(from, to, MF_PROMOTION, QUEEN), 0 };
        } else if (to == pos.ep_square()) {
            *out++ = ExtMove{ make_move(from, to, MF_ENPASSANT), 0 };
        } else {
            *out++ = ExtMove{ make_move(from, to), 0 };
        }
    }
    while (right) {
        int to = BB::pop_lsb_sq(right);
        int from = to - (Us == WHITE ? 9 : -7);
        if (BB::square_bb(to) & RelBackRank) {
            *out++ = ExtMove{ make_move(from, to, MF_PROMOTION, QUEEN), 0 };
        } else if (to == pos.ep_square()) {
            *out++ = ExtMove{ make_move(from, to, MF_ENPASSANT), 0 };
        } else {
            *out++ = ExtMove{ make_move(from, to), 0 };
        }
    }
    // queen promotions by push
    U64 ppush = (Us == WHITE ? BB::shift_n(pawns & RelRank7) : BB::shift_s(pawns & RelRank7)) & empty;
    while (ppush) {
        int to = BB::pop_lsb_sq(ppush);
        *out++ = ExtMove{ make_move(to - Dir, to, MF_PROMOTION, QUEEN), 0 };
    }

    const U64 targetBB = targets;
    U64 kn = pos.pieces(Us, KNIGHT);
    while (kn) {
        int from = BB::pop_lsb_sq(kn);
        U64 at = KnightAttacks[from] & targetBB;
        while (at) { int to = BB::pop_lsb_sq(at); *out++ = ExtMove{ make_move(from, to), 0 }; }
    }
    U64 b = pos.pieces(Us, BISHOP);
    while (b) {
        int from = BB::pop_lsb_sq(b);
        U64 at = bishop_attacks(occ, from) & targetBB;
        while (at) { int to = BB::pop_lsb_sq(at); *out++ = ExtMove{ make_move(from, to), 0 }; }
    }
    U64 r = pos.pieces(Us, ROOK);
    while (r) {
        int from = BB::pop_lsb_sq(r);
        U64 at = rook_attacks(occ, from) & targetBB;
        while (at) { int to = BB::pop_lsb_sq(at); *out++ = ExtMove{ make_move(from, to), 0 }; }
    }
    U64 q = pos.pieces(Us, QUEEN);
    while (q) {
        int from = BB::pop_lsb_sq(q);
        U64 at = (bishop_attacks(occ, from) | rook_attacks(occ, from)) & targetBB;
        while (at) { int to = BB::pop_lsb_sq(at); *out++ = ExtMove{ make_move(from, to), 0 }; }
    }
    {
        int from = pos.king_sq(Us);
        U64 at = KingAttacks[from] & targetBB;
        while (at) { int to = BB::pop_lsb_sq(at); *out++ = ExtMove{ make_move(from, to), 0 }; }
    }
    return out;
}

} // anonymous namespace

ExtMove* generate_pseudo(const Position& pos, ExtMove* out) {
    return pos.side_to_move() == WHITE ? gen_all_impl<WHITE>(pos, out)
                                       : gen_all_impl<BLACK>(pos, out);
}

ExtMove* generate_pseudo_captures(const Position& pos, ExtMove* out) {
    return pos.side_to_move() == WHITE ? gen_captures_impl<WHITE>(pos, out)
                                       : gen_captures_impl<BLACK>(pos, out);
}

int generate_legal(const Position& cpos, ExtMove* out) {
    Position pos = cpos;
    ExtMove buf[MAX_MOVES];
    ExtMove* end = generate_pseudo(pos, buf);
    int n = 0;
    const Color us = pos.side_to_move();
    const Color them = ~us;
    for (ExtMove* p = buf; p != end; ++p) {
        pos.do_move(p->move);
        if (!pos.attacked_by(pos.king_sq(us), them)) out[n++] = *p;
        pos.undo_move(p->move);
    }
    return n;
}

int generate_legal(const Position& pos, Move* out) {
    ExtMove buf[MAX_MOVES];
    int n = generate_legal(pos, buf);
    for (int i = 0; i < n; ++i) out[i] = buf[i].move;
    return n;
}

bool has_legal_move(const Position& cpos) {
    Position pos = cpos;
    ExtMove buf[MAX_MOVES];
    ExtMove* end = generate_pseudo(pos, buf);
    const Color us = pos.side_to_move();
    const Color them = ~us;
    for (ExtMove* p = buf; p != end; ++p) {
        pos.do_move(p->move);
        bool ok = !pos.attacked_by(pos.king_sq(us), them);
        pos.undo_move(p->move);
        if (ok) return true;
    }
    return false;
}

// ------------------------------------------------------------------- perft ---
static U64 perft_rec(Position& pos, int depth) {
    if (depth == 0) return 1;
    ExtMove buf[MAX_MOVES];
    ExtMove* end = generate_pseudo(pos, buf);
    if (depth == 1) {
        // bulk counting
        U64 n = 0;
        const Color us = pos.side_to_move();
        const Color them = ~us;
        for (ExtMove* p = buf; p != end; ++p) {
            pos.do_move(p->move);
            if (!pos.attacked_by(pos.king_sq(us), them)) ++n;
            pos.undo_move(p->move);
        }
        return n;
    }
    U64 nodes = 0;
    const Color us = pos.side_to_move();
    const Color them = ~us;
    for (ExtMove* p = buf; p != end; ++p) {
        pos.do_move(p->move);
        if (!pos.attacked_by(pos.king_sq(us), them))
            nodes += perft_rec(pos, depth - 1);
        pos.undo_move(p->move);
    }
    return nodes;
}

U64 perft(Position& pos, int depth) { return perft_rec(pos, depth); }

U64 perft_root(Position& pos, int depth) {
    ExtMove buf[MAX_MOVES];
    ExtMove* end = generate_pseudo(pos, buf);
    U64 total = 0;
    const Color us = pos.side_to_move();
    const Color them = ~us;
    for (ExtMove* p = buf; p != end; ++p) {
        pos.do_move(p->move);
        if (!pos.attacked_by(pos.king_sq(us), them)) {
            U64 n = perft_rec(pos, depth - 1);
            std::printf("%s: %llu\n", move_to_str(p->move).c_str(), (unsigned long long)n);
            total += n;
        }
        pos.undo_move(p->move);
    }
    std::printf("Total: %llu\n", (unsigned long long)total);
    return total;
}

// --------------------------------------------------------------------- uci ---
Move move_from_uci(Position& pos, const std::string& s) {
    if (s == "0000") return MOVE_NULL;
    if (s.size() < 4) return MOVE_NONE;
    int from = sq_from_str(s.substr(0, 2));
    int to = sq_from_str(s.substr(2, 2));
    if (from == SQ_NONE || to == SQ_NONE) return MOVE_NONE;
    PieceType promo = NO_PTYPE;
    if (s.size() >= 5) {
        switch (s[4]) {
        case 'n': promo = KNIGHT; break;
        case 'b': promo = BISHOP; break;
        case 'r': promo = ROOK; break;
        case 'q': promo = QUEEN; break;
        default: return MOVE_NONE;
        }
    }
    ExtMove buf[MAX_MOVES];
    int n = generate_legal(pos, buf);
    for (int i = 0; i < n; ++i) {
        Move m = buf[i].move;
        if (from_sq(m) == from && to_sq(m) == to) {
            if (is_promotion(m))
                return promo_type(m) == promo ? m : MOVE_NONE;
            if (promo == NO_PTYPE) return m;
        }
    }
    return MOVE_NONE;
}

std::string move_to_san(const Position& cpos, Move m) {
    Position pos = cpos;
    if (m == MOVE_NULL) return "null";
    const Color us = pos.side_to_move();
    const Piece pc = pos.piece_on(from_sq(m));
    const PieceType pt = ptype_of(pc);
    std::string san;
    if (flag_of(m) == MF_CASTLING) {
        san = (to_sq(m) > from_sq(m)) ? "O-O" : "O-O-O";
    } else {
        if (pt == PAWN) {
            if (pos.is_capture(m)) san += char('a' + file_of(from_sq(m)));
        } else {
            san += char("PNBRQK"[pt]);
            // disambiguation
            ExtMove buf[MAX_MOVES];
            int n = generate_legal(cpos, buf);
            bool sameFile = false, sameRank = false, other = false;
            for (int i = 0; i < n; ++i) {
                Move om = buf[i].move;
                if (om == m) continue;
                if (to_sq(om) == to_sq(m) && pos.piece_on(from_sq(om)) == pc) {
                    other = true;
                    if (file_of(from_sq(om)) == file_of(from_sq(m))) sameFile = true;
                    if (rank_of(from_sq(om)) == rank_of(from_sq(m))) sameRank = true;
                }
            }
            if (other) {
                if (!sameFile) san += char('a' + file_of(from_sq(m)));
                else if (!sameRank) san += char('1' + rank_of(from_sq(m)));
                else { san += char('a' + file_of(from_sq(m))); san += char('1' + rank_of(from_sq(m))); }
            }
        }
        if (pos.is_capture(m)) san += 'x';
        san += sq_to_str(to_sq(m));
        if (is_promotion(m)) {
            san += '=';
            san += char(" PNBRQK"[promo_type(m)]);
        }
    }
    pos.do_move(m);
    if (pos.in_check()) san += pos.side_to_move() == us ? "" : (has_legal_move(pos) ? "+" : "#");
    return san;
}

} // namespace Veltrix
