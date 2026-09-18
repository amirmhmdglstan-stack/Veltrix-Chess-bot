// Veltrix 1.0 - core type definitions
// Copyright (C) 2026 Veltrix Project
// SPDX-License-Identifier: GPL-3.0-or-later
//
// This program is free software: you can redistribute it and/or modify
// it under the terms of the GNU General Public License as published by
// the Free Software Foundation, either version 3 of the License, or
// (at your option) any later version.
#pragma once

#include <cstdint>
#include <cstdlib>
#include <string>

namespace Veltrix {

using U64 = uint64_t;
using U32 = uint32_t;
using U16 = uint16_t;
using U8 = uint8_t;
using I64 = int64_t;
using I32 = int32_t;
using I16 = int16_t;
using Clock = I64;  // milliseconds

constexpr int MAX_PLY   = 128;   // max search depth + safety margin
constexpr int MAX_MOVES = 256;   // max legal moves in a position

// ---------------------------------------------------------------- colors ---
enum Color : int { WHITE = 0, BLACK = 1, COLOR_NB = 2, NO_COLOR = 2 };
constexpr Color operator~(Color c) { return Color(c ^ BLACK); }

// ---------------------------------------------------------------- pieces ---
enum PieceType : int {
    PAWN = 0, KNIGHT = 1, BISHOP = 2, ROOK = 3, QUEEN = 4, KING = 5,
    PT_NB = 6, NO_PTYPE = 7
};

enum Piece : int {
    W_PAWN = 0, W_KNIGHT, W_BISHOP, W_ROOK, W_QUEEN, W_KING,
    B_PAWN = 6, B_KNIGHT, B_BISHOP, B_ROOK, B_QUEEN, B_KING,
    NO_PIECE = 12, PIECE_NB = 12
};

inline Piece make_piece(Color c, PieceType pt) { return Piece(c * 6 + pt); }
inline PieceType ptype_of(Piece p) { return p == NO_PIECE ? NO_PTYPE : PieceType(p % 6); }
inline Color color_of(Piece p) { return p == NO_PIECE ? NO_COLOR : Color(p / 6); }

constexpr char PIECE_CHARS[13] = { 'P', 'N', 'B', 'R', 'Q', 'K',
                                   'p', 'n', 'b', 'r', 'q', 'k', '.' };
inline char piece_char(Piece p) { return PIECE_CHARS[p]; }
inline int piece_from_char(char c) {
    switch (c) {
    case 'P': return W_PAWN; case 'N': return W_KNIGHT; case 'B': return W_BISHOP;
    case 'R': return W_ROOK; case 'Q': return W_QUEEN;  case 'K': return W_KING;
    case 'p': return B_PAWN; case 'n': return B_KNIGHT; case 'b': return B_BISHOP;
    case 'r': return B_ROOK; case 'q': return B_QUEEN;  case 'k': return B_KING;
    default:  return NO_PIECE;
    }
}

// ---------------------------------------------------------------- squares ---
// A1 = 0, B1 = 1, ..., H1 = 7, A2 = 8, ..., H8 = 63
enum Square : int { SQ_NONE = 64, SQ_NB = 64 };
inline int file_of(int sq) { return sq & 7; }
inline int rank_of(int sq) { return sq >> 3; }
inline int make_square(int f, int r) { return r * 8 + f; }
inline bool is_ok(int sq) { return sq >= 0 && sq < 64; }
inline Square relative_sq(Color c, int sq) { return Square(c == WHITE ? sq : sq ^ 56); }
inline int relative_rank(Color c, int sq) { return c == WHITE ? rank_of(sq) : 7 - rank_of(sq); }
inline std::string sq_to_str(int sq) {
    if (sq < 0 || sq >= 64) return "-";
    std::string s;
    s += char('a' + file_of(sq));
    s += char('1' + rank_of(sq));
    return s;
}
inline int sq_from_str(const std::string& s) {
    if (s.size() < 2) return SQ_NONE;
    int f = s[0] - 'a', r = s[1] - '1';
    if (f < 0 || f > 7 || r < 0 || r > 7) return SQ_NONE;
    return make_square(f, r);
}

// direction deltas valid for a "compass rose" over the 8x8 board
constexpr int NORTH = 8, SOUTH = -8, EAST = 1, WEST = -1;
constexpr int NORTH_EAST = 9, NORTH_WEST = 7, SOUTH_EAST = -7, SOUTH_WEST = -9;

// ------------------------------------------------------------------ moves ---
// 32-bit move encoding:
//   bits  0.. 5 : origin square
//   bits  6..11 : destination square
//   bits 12..13 : promotion piece type - KNIGHT (only when PROMOTION flag set)
//   bits 14..15 : move flag
enum MoveFlag : int {
    MF_NORMAL    = 0 << 14,
    MF_PROMOTION = 1 << 14,
    MF_ENPASSANT = 2 << 14,
    MF_CASTLING  = 3 << 14,
    MF_MASK      = 3 << 14
};

using Move = U32;
constexpr Move MOVE_NONE = 0;
constexpr Move MOVE_NULL = 65;  // from=1,to=1  (like "b1b1")

inline Move make_move(int from, int to, MoveFlag flag = MF_NORMAL, PieceType promo = KNIGHT) {
    return Move(from | (to << 6) | ((promo - KNIGHT) << 12) | flag);
}
inline int from_sq(Move m) { return m & 63; }
inline int to_sq(Move m) { return (m >> 6) & 63; }
inline MoveFlag flag_of(Move m) { return MoveFlag(m & MF_MASK); }
inline bool is_promotion(Move m) { return flag_of(m) == MF_PROMOTION; }
inline PieceType promo_type(Move m) { return PieceType(((m >> 12) & 3) + KNIGHT); }
inline std::string move_to_str(Move m) {
    if (m == MOVE_NONE || m == MOVE_NULL) return "0000";
    std::string s = sq_to_str(from_sq(m)) + sq_to_str(to_sq(m));
    if (is_promotion(m)) {
        const char* pc = "nbrq";
        s += pc[promo_type(m) - KNIGHT];
    }
    return s;
}

// A move together with its ordering score.
struct ExtMove {
    Move move;
    int score;
    operator Move() const { return move; }
    bool operator==(const ExtMove& o) const { return move == o.move; }
    bool operator!=(const ExtMove& o) const { return move != o.move; }
};

// --------------------------------------------------------- castling rights ---
enum CastlingRight : int {
    NO_CASTLING = 0,
    WHITE_OO = 1, WHITE_OOO = 2,
    BLACK_OO = 4, BLACK_OOO = 8,
    ALL_CASTLING = 15
};
inline CastlingRight operator&(CastlingRight a, CastlingRight b) {
    return CastlingRight(int(a) & int(b));
}

// squares occupied/transited for each castle
constexpr int CASTLE_KING_FROM[COLOR_NB] = { 4 /*e1*/, 60 /*e8*/ };

// rooks' home squares for castling
constexpr int ROOK_FROM_OO[COLOR_NB]  = { 7 /*h1*/, 63 /*h8*/ };
constexpr int ROOK_FROM_OOO[COLOR_NB] = { 0 /*a1*/, 56 /*a8*/ };
constexpr int KING_TO_OO[COLOR_NB]  = { 6 /*g1*/, 62 /*g8*/ };
constexpr int KING_TO_OOO[COLOR_NB] = { 2 /*c1*/, 58 /*c8*/ };
constexpr int ROOK_TO_OO[COLOR_NB]  = { 5 /*f1*/, 61 /*f8*/ };
constexpr int ROOK_TO_OOO[COLOR_NB] = { 3 /*d1*/, 59 /*d8*/ };

// --------------------------------------------------------------- evaluation --
using Value = int;
constexpr Value VALUE_NONE      = 32002;
constexpr Value VALUE_MAX       = 32000;
constexpr Value VALUE_MATE      = 31000;
constexpr Value VALUE_MATE_IN_MAX_PLY   = VALUE_MATE - MAX_PLY;
constexpr Value VALUE_MATED_IN_MAX_PLY  = -VALUE_MATE + MAX_PLY;
constexpr Value VALUE_ZERO      = 0;
constexpr Value VALUE_DRAW      = 0;
constexpr Value VALUE_TB_WIN    = 0;  // placeholder if tablebases added

inline bool is_win(Value v)  { return v >= VALUE_MATE_IN_MAX_PLY; }
inline bool is_loss(Value v) { return v <= -VALUE_MATE_IN_MAX_PLY; }
inline Value mate_in(int ply)  { return VALUE_MATE - ply; }
inline Value mated_in(int ply) { return -VALUE_MATE + ply; }
// clamp TT-style values relative to ply when storing/probing
inline Value value_to_tt(Value v, int ply) {
    return v >= VALUE_MATE_IN_MAX_PLY  ? v + ply
         : v <= -VALUE_MATE_IN_MAX_PLY ? v - ply : v;
}
inline Value value_from_tt(Value v, int ply) {
    return v >= VALUE_MATE_IN_MAX_PLY  ? v - ply
         : v <= -VALUE_MATE_IN_MAX_PLY ? v + ply : v;
}

// mate distance in plies for UCI "score mate N" (N = moves, positive = winning)
inline int value_to_mate_ply(Value v) {
    if (v >= VALUE_MATE_IN_MAX_PLY)  return (VALUE_MATE - v);
    if (v <= -VALUE_MATE_IN_MAX_PLY) return -(VALUE_MATE + v);
    return 0;
}

enum Bound : U8 { BOUND_NONE = 0, BOUND_UPPER = 1, BOUND_LOWER = 2, BOUND_EXACT = 3 };

} // namespace Veltrix
