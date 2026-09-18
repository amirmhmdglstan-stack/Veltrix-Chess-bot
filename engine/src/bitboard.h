// Veltrix 1.0 - bitboard infrastructure with runtime-generated magic bitboards
// Copyright (C) 2026 Veltrix Project
// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once

#include "types.h"
#include <string>

namespace Veltrix {

namespace BB {

// file / rank boards
constexpr U64 FILE_A = 0x0101010101010101ULL;
constexpr U64 FILE_H = 0x8080808080808080ULL;
constexpr U64 RANK_1 = 0x00000000000000FFULL;
constexpr U64 RANK_2 = 0x000000000000FF00ULL;
constexpr U64 RANK_3 = 0x0000000000FF0000ULL;
constexpr U64 RANK_4 = 0x00000000FF000000ULL;
constexpr U64 RANK_5 = 0x000000FF00000000ULL;
constexpr U64 RANK_6 = 0x0000FF0000000000ULL;
constexpr U64 RANK_7 = 0x00FF000000000000ULL;
constexpr U64 RANK_8 = 0xFF00000000000000ULL;

inline U64 square_bb(int sq) { return 1ULL << sq; }

#if defined(__GNUC__)
inline int popcnt(U64 b) { return __builtin_popcountll(b); }
inline int lsb(U64 b) { return __builtin_ctzll(b); }       // b must be non-zero
inline int msb(U64 b) { return 63 - __builtin_clzll(b); }
#else
// portable fallbacks
inline int popcnt(U64 b) {
    b = b - ((b >> 1) & 0x5555555555555555ULL);
    b = (b & 0x3333333333333333ULL) + ((b >> 2) & 0x3333333333333333ULL);
    b = (b + (b >> 4)) & 0x0F0F0F0F0F0F0F0FULL;
    return int((b * 0x0101010101010101ULL) >> 56);
}
constexpr int DEBRUIJN64 = 0; // marker
inline int lsb(U64 b) {
    static const int index[64] = {
        0, 47,  1, 56, 48, 27,  2, 60,
       57, 49, 41, 37, 28, 16,  3, 61,
       54, 58, 35, 52, 50, 42, 21, 44,
       38, 32, 29, 23, 17, 11,  4, 62,
       46, 55, 26, 59, 40, 36, 15, 53,
       34, 51, 20, 43, 31, 22, 10, 45,
       25, 39, 14, 33, 19, 30,  9, 24,
       13, 18,  8, 12,  7,  6,  5, 63 };
    return index[((b ^ (b - 1)) * 0x03f79d71b4cb0a89ULL) >> 58];
}
inline int msb(U64 b) {
    b |= b >> 1; b |= b >> 2; b |= b >> 4; b |= b >> 8; b |= b >> 16; b |= b >> 32;
    return lsb(b ^ (b >> 1));
}
#endif

inline U64 pop_lsb(U64& b) { U64 ret = b & (~b + 1); b &= b - 1; return ret; }
inline int pop_lsb_sq(U64& b) { int s = lsb(b); b &= b - 1; return s; }
inline bool more_than_one(U64 b) { return (b & (b - 1)) != 0; }

// directional shifts (wrap-safe)
inline U64 shift_n(U64 b)  { return b << 8; }
inline U64 shift_s(U64 b)  { return b >> 8; }
inline U64 shift_e(U64 b)  { return (b & ~FILE_H) << 1; }
inline U64 shift_w(U64 b)  { return (b & ~FILE_A) >> 1; }
inline U64 shift_ne(U64 b) { return (b & ~FILE_H) << 9; }
inline U64 shift_nw(U64 b) { return (b & ~FILE_A) << 7; }
inline U64 shift_se(U64 b) { return (b & ~FILE_H) >> 7; }
inline U64 shift_sw(U64 b) { return (b & ~FILE_A) >> 9; }

} // namespace BB

// ------------------------------------------------------------------- tables --
struct Magic {
    U64* ptr;    // pointer into the shared attack table
    U64 mask;    // relevant occupancy
    U64 magic;   // magic multiplier
    int shift;   // 64 - bits
};

extern U64 PawnAttacks[COLOR_NB][64];
extern U64 KnightAttacks[64];
extern U64 KingAttacks[64];
extern Magic RookMagics[64];
extern Magic BishopMagics[64];
extern U64 RookAttackTable[102400];
extern U64 BishopAttackTable[5248];
extern U64 BetweenBB[64][64];   // squares strictly between two aligned squares (0 otherwise)
extern U64 LineBB[64][64];      // the full line through two aligned squares incl. both
extern U64 PseudoAttacks[PT_NB][64];   // occupancy-independent attacks (sliders = unlimited rays)
extern U64 SquareBB[64];

void init_bitboards();

inline U64 pawn_attacks(Color c, int sq) { return PawnAttacks[c][sq]; }
inline U64 knight_attacks(int sq) { return KnightAttacks[sq]; }
inline U64 king_attacks(int sq) { return KingAttacks[sq]; }

inline U64 rook_attacks(U64 occ, int sq) {
    const Magic& m = RookMagics[sq];
    return m.ptr[((occ & m.mask) * m.magic) >> m.shift];
}
inline U64 bishop_attacks(U64 occ, int sq) {
    const Magic& m = BishopMagics[sq];
    return m.ptr[((occ & m.mask) * m.magic) >> m.shift];
}

inline U64 attacks_bb(PieceType pt, int sq, U64 occ) {
    switch (pt) {
    case KNIGHT: return KnightAttacks[sq];
    case BISHOP: return bishop_attacks(occ, sq);
    case ROOK:   return rook_attacks(occ, sq);
    case QUEEN:  return bishop_attacks(occ, sq) | rook_attacks(occ, sq);
    case KING:   return KingAttacks[sq];
    default:     return 0;
    }
}

inline U64 file_bb(int f) { return BB::FILE_A << f; }
inline U64 rank_bb(int r) { return BB::RANK_1 << (r * 8); }
inline U64 adjacent_files_bb(int f) {
    U64 b = 0;
    if (f > 0) b |= file_bb(f - 1);
    if (f < 7) b |= file_bb(f + 1);
    return b;
}

// ranks in front of the square (for passed-pawn masks), from side c's view
U64 forward_ranks_bb(Color c, int r);   // ranks strictly ahead
U64 forward_file_bb(Color c, int sq);   // file ahead of square (excl. square)

} // namespace Veltrix
