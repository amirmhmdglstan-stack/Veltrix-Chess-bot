// Veltrix 1.0 - bitboard tables and deterministic runtime magic generation
// Copyright (C) 2026 Veltrix Project
// SPDX-License-Identifier: GPL-3.0-or-later
//
// Magics are generated at program startup using a fixed-seed PRNG, so no
// precomputed third-party magic tables are required. The resulting numbers
// are deterministic for a given build.
#include "bitboard.h"
#include <cstring>

namespace Veltrix {

U64 PawnAttacks[COLOR_NB][64];
U64 KnightAttacks[64];
U64 KingAttacks[64];
Magic RookMagics[64];
Magic BishopMagics[64];
U64 RookAttackTable[102400];
U64 BishopAttackTable[5248];
U64 BetweenBB[64][64];
U64 LineBB[64][64];
U64 PseudoAttacks[PT_NB][64];
U64 SquareBB[64];

namespace {

// deterministic PRNG (xorshift64*)
struct XorShift {
    U64 s;
    explicit XorShift(U64 seed) : s(seed) {}
    U64 next() {
        s ^= s >> 12; s ^= s << 25; s ^= s >> 27;
        return s * 2685821657736338717ULL;
    }
    U64 next_sparse() { return next() & next() & next(); }
};

U64 ray_attack(int sq, const int* deltas, int nd, U64 occ) {
    U64 attacks = 0;
    for (int i = 0; i < nd; ++i) {
        int d = deltas[i];
        for (int s = sq + d; s >= 0 && s < 64; s += d) {
            // guard against file wrap-around
            int fdiff = (s & 7) - ((s - d) & 7);
            if (fdiff < -1 || fdiff > 1) break;
            attacks |= BB::square_bb(s);
            if (occ & BB::square_bb(s)) break;
        }
    }
    return attacks;
}

const int ROOK_DIRS[4] = { NORTH, SOUTH, EAST, WEST };
const int BISHOP_DIRS[4] = { NORTH_EAST, NORTH_WEST, SOUTH_EAST, SOUTH_WEST };

U64 slider_mask_rook(int sq) {
    U64 mask = ray_attack(sq, ROOK_DIRS, 4, 0);
    // remove edge squares not needed by the hash
    int f = file_of(sq), r = rank_of(sq);
    if (f != 0) mask &= ~BB::FILE_A;
    if (f != 7) mask &= ~BB::FILE_H;
    if (r != 0) mask &= ~BB::RANK_1;
    if (r != 7) mask &= ~BB::RANK_8;
    return mask;
}

U64 slider_mask_bishop(int sq) {
    U64 mask = ray_attack(sq, BISHOP_DIRS, 4, 0);
    mask &= ~(BB::FILE_A | BB::FILE_H | BB::RANK_1 | BB::RANK_8);
    return mask;
}

void init_magics(Magic magics[64], U64* table, const int* dirs, bool isRook, XorShift& rng) {
    U64 occupancy[4096], reference[4096];
    int offset = 0;
    for (int sq = 0; sq < 64; ++sq) {
        Magic& m = magics[sq];
        m.mask = isRook ? slider_mask_rook(sq) : slider_mask_bishop(sq);
        int bits = BB::popcnt(m.mask);
        m.shift = 64 - bits;
        m.ptr = table + offset;

        // enumerate all subsets of the relevant occupancy
        int n = 0;
        U64 b = 0;
        do {
            occupancy[n] = b;
            reference[n] = ray_attack(sq, dirs, 4, b);
            ++n;
            b = (b - m.mask) & m.mask;
        } while (b);
        int size = 1 << bits;

        if (size != n) { // sanity; cannot happen
            // fallback: enlarge later
        }

        // search for a magic number
        static U64 used[4096];
        for (int attempt = 0; attempt < 100000000; ++attempt) {
            U64 magic = rng.next_sparse();
            if (BB::popcnt((m.mask * magic) & 0xFF00000000000000ULL) < 6)
                continue;
            std::memset(used, 0, sizeof(U64) * size);
            bool fail = false;
            for (int i = 0; i < n && !fail; ++i) {
                int j = int(((occupancy[i] * magic) >> m.shift) & (size - 1));
                if (used[j] == 0)
                    used[j] = reference[i];
                else if (used[j] != reference[i])
                    fail = true;
            }
            if (!fail) {
                m.magic = magic;
                // fill the shared attack table
                for (int i = 0; i < n; ++i) {
                    int j = int(((occupancy[i] * magic) >> m.shift) & (size - 1));
                    m.ptr[j] = reference[i];
                }
                break;
            }
        }
        offset += size;
    }
}

} // namespace

void init_bitboards() {
    static bool done = false;
    if (done) return;
    done = true;

    for (int sq = 0; sq < 64; ++sq)
        SquareBB[sq] = BB::square_bb(sq);

    // pawn attacks
    for (int sq = 0; sq < 64; ++sq) {
        U64 b = BB::square_bb(sq);
        PawnAttacks[WHITE][sq] = BB::shift_ne(b) | BB::shift_nw(b);
        PawnAttacks[BLACK][sq] = BB::shift_se(b) | BB::shift_sw(b);
    }
    // knight
    const int KDELTA[8][2] = { {1,2},{2,1},{2,-1},{1,-2},{-1,-2},{-2,-1},{-2,1},{-1,2} };
    for (int sq = 0; sq < 64; ++sq) {
        U64 b = 0;
        int f = file_of(sq), r = rank_of(sq);
        for (auto& d : KDELTA) {
            int nf = f + d[0], nr = r + d[1];
            if (nf >= 0 && nf < 8 && nr >= 0 && nr < 8)
                b |= BB::square_bb(make_square(nf, nr));
        }
        KnightAttacks[sq] = b;
    }
    // king
    for (int sq = 0; sq < 64; ++sq) {
        U64 b = BB::square_bb(sq);
        U64 a = BB::shift_n(b) | BB::shift_s(b) | BB::shift_e(b) | BB::shift_w(b) |
                BB::shift_ne(b) | BB::shift_nw(b) | BB::shift_se(b) | BB::shift_sw(b);
        KingAttacks[sq] = a;
    }

    // pseudo attacks (unlimited rays for sliders)
    for (int sq = 0; sq < 64; ++sq) {
        PseudoAttacks[PAWN][sq] = 0;
        PseudoAttacks[KNIGHT][sq] = KnightAttacks[sq];
        PseudoAttacks[KING][sq] = KingAttacks[sq];
        PseudoAttacks[BISHOP][sq] = ray_attack(sq, BISHOP_DIRS, 4, 0);
        PseudoAttacks[ROOK][sq] = ray_attack(sq, ROOK_DIRS, 4, 0);
        PseudoAttacks[QUEEN][sq] = PseudoAttacks[BISHOP][sq] | PseudoAttacks[ROOK][sq];
    }

    // magic bitboards (deterministic seed)
    XorShift rng(0x9E3779B97F4A7C15ULL);
    init_magics(RookMagics, RookAttackTable, ROOK_DIRS, true, rng);
    init_magics(BishopMagics, BishopAttackTable, BISHOP_DIRS, false, rng);

    // between / line tables
    for (int s1 = 0; s1 < 64; ++s1)
        for (int s2 = 0; s2 < 64; ++s2) {
            BetweenBB[s1][s2] = 0;
            LineBB[s1][s2] = 0;
            if (s1 == s2) continue;
            U64 direct = (PseudoAttacks[BISHOP][s1] | PseudoAttacks[ROOK][s1]) & BB::square_bb(s2);
            if (!direct) continue;
            U64 occ1 = BB::square_bb(s2);
            U64 occ2 = BB::square_bb(s1);
            U64 a1 = attacks_bb(QUEEN, s1, occ1);  // ray from s1 stopping at (and incl.) s2
            U64 a2 = attacks_bb(QUEEN, s2, occ2);  // ray from s2 stopping at (and incl.) s1
            LineBB[s1][s2] = a1 | a2;              // entire line through the two squares
            BetweenBB[s1][s2] = a1 & a2;           // squares strictly between them
        }

}

U64 forward_ranks_bb(Color c, int r) {
    if (c == WHITE) {
        U64 b = 0;
        for (int rr = r + 1; rr < 8; ++rr) b |= rank_bb(rr);
        return b;
    } else {
        U64 b = 0;
        for (int rr = 0; rr < r; ++rr) b |= rank_bb(rr);
        return b;
    }
}

U64 forward_file_bb(Color c, int sq) {
    return forward_ranks_bb(c, rank_of(sq)) & file_bb(file_of(sq));
}

} // namespace Veltrix
