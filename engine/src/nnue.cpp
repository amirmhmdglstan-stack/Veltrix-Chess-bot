// Veltrix NNUE - implementation of the VNN1 evaluator (see nnue.h / docs/NNUE.md)
// Copyright (C) 2026 Veltrix Project
// SPDX-License-Identifier: GPL-3.0-or-later
#include "nnue.h"
#include "position.h"

#include <cstdio>
#include <cstring>
#include <algorithm>

namespace Veltrix {
namespace NNUE {
namespace {

// ------------------------------ network storage ------------------------------
// File layout (little-endian, fixed size, magic-guarded):
//   char magic[4] = "VNN1"
//   u16 version = 1, u16 inputs, u16 h1, u16 h2
//   i16 ftBias[H1]
//   i16 ftWeight[NUM_INPUTS][H1]      (row-major: input feature first)
//   i32 fc1Bias[H2]
//   i16 fc1Weight[H2][2*H1]           (output-major for cheap dot products)
//   i32 outBias
//   i16 outWeight[H2]
struct Net {
    int16_t  ftBias[H1];
    int16_t* ftWeight = nullptr;      // NUM_INPUTS * H1
    int32_t  fc1Bias[H2];
    int16_t  fc1Weight[H2][2 * H1];
    int32_t  outBias = 0;
    int16_t  outWeight[H2];
    std::string path;
};

Net gNet;
bool gLoaded = false;

bool read_exact(FILE* f, void* dst, size_t bytes) {
    return std::fread(dst, 1, bytes, f) == bytes;
}

// keep every int32 dot product safely in range even for a corrupted file
int16_t clamp_fc(int16_t w) {
    return int16_t(std::max(-MAX_FC_WEIGHT, std::min(MAX_FC_WEIGHT, int(w))));
}

// ------------------------------- features ------------------------------------
// black perspective = board rotated 180 degrees: square XOR 63, colours swap
inline int xsq(int sq, Color pov)  { return pov == WHITE ? sq : (sq ^ 63); }

// class 0..4: P,N,B,R,Q of the perspective colour; 5..9: enemy pieces
inline int findex(int ksqPov, Piece pc, int sqPov, Color pov) {
    const int cls = (color_of(pc) == pov ? 0 : 5) + ptype_of(pc);
    return ksqPov * 640 + cls * 64 + sqPov;
}

inline void add_feature(Accumulator& acc, int pov, int ksqT, Piece pc, int sq) {
    const int16_t* w = gNet.ftWeight + size_t(findex(ksqT, pc, xsq(sq, Color(pov)), Color(pov))) * H1;
    int16_t* a = acc.v[pov];
    for (int i = 0; i < H1; ++i) a[i] = int16_t(a[i] + w[i]);
}

inline void sub_feature(Accumulator& acc, int pov, int ksqT, Piece pc, int sq) {
    const int16_t* w = gNet.ftWeight + size_t(findex(ksqT, pc, xsq(sq, Color(pov)), Color(pov))) * H1;
    int16_t* a = acc.v[pov];
    for (int i = 0; i < H1; ++i) a[i] = int16_t(a[i] - w[i]);
}

} // anonymous namespace

int feature_index(int ksq, Piece pc, int sq, Color pov) {
    return findex(xsq(ksq, pov), pc, xsq(sq, pov), pov);
}

// -------------------------------- lifecycle ----------------------------------
bool load_file(const char* path) {
    FILE* f = std::fopen(path, "rb");
    if (!f) return false;
    char magic[4] = { 0, 0, 0, 0 };
    uint16_t ver = 0, inputs = 0, h1 = 0, h2 = 0;
    bool ok = std::fread(magic, 1, 4, f) == 4 && std::memcmp(magic, "VNN1", 4) == 0 &&
              read_exact(f, &ver, 2) && read_exact(f, &inputs, 2) &&
              read_exact(f, &h1, 2) && read_exact(f, &h2, 2) &&
              ver == 1 && inputs == NUM_INPUTS && h1 == H1 && h2 == H2;
    int16_t* ftw = nullptr;
    if (ok) {
        ftw = new int16_t[size_t(NUM_INPUTS) * H1];
        ok = read_exact(f, gNet.ftBias, sizeof(gNet.ftBias)) &&
             read_exact(f, ftw, size_t(NUM_INPUTS) * H1 * 2) &&
             read_exact(f, gNet.fc1Bias, sizeof(gNet.fc1Bias)) &&
             read_exact(f, gNet.fc1Weight, sizeof(gNet.fc1Weight)) &&
             read_exact(f, &gNet.outBias, 4) &&
             read_exact(f, gNet.outWeight, sizeof(gNet.outWeight));
    }
    std::fclose(f);
    if (!ok) { delete[] ftw; return false; }
    for (int o = 0; o < H2; ++o)
        for (int i = 0; i < 2 * H1; ++i) gNet.fc1Weight[o][i] = clamp_fc(gNet.fc1Weight[o][i]);
    for (int i = 0; i < H2; ++i) gNet.outWeight[i] = clamp_fc(gNet.outWeight[i]);
    delete[] gNet.ftWeight;
    gNet.ftWeight = ftw;
    gNet.path = path;
    gLoaded = true;
    return true;
}

bool loaded() { return gLoaded; }
const char* loaded_path() { return gLoaded ? gNet.path.c_str() : ""; }

void unload() {
    delete[] gNet.ftWeight;
    gNet.ftWeight = nullptr;
    gLoaded = false;
}

// ------------------------------ recomputation --------------------------------
void refresh(Accumulator& acc, const Position& pos) {
    for (int pov = 0; pov < 2; ++pov)
        refresh_side(acc, pos, Color(pov));
    acc.computed = true;
}

void refresh_side(Accumulator& acc, const Position& pos, Color side) {
    const int pov = int(side);
    std::memcpy(acc.v[pov], gNet.ftBias, sizeof(int16_t) * H1);
    const int ksqT = xsq(pos.king_sq(side), side);
    U64 bb = pos.pieces();
    while (bb) {
        const int sq = BB::pop_lsb_sq(bb);
        const Piece pc = pos.piece_on(sq);
        if (ptype_of(pc) != KING) add_feature(acc, pov, ksqT, pc, sq);
    }
    acc.computed = true;
}

bool needs_king_refresh(const Position& pos, Move m, Color& sideOut) {
    const Piece mover = pos.piece_on(from_sq(m));
    if (ptype_of(mover) == KING) {
        sideOut = color_of(mover);
        return true;
    }
    return false;
}

// ------------------------------ incremental ----------------------------------
// Applies all NON-king feature changes of `m` onto `next`, for perspectives
// that do NOT need a king refresh (those are left as copied garbage and must
// be fixed with refresh_side() once the post-move position exists; the search
// wrapper does exactly that). Uses pre-move king buckets, which are valid for
// the un-refreshed perspectives only.
void push(const Accumulator& cur, Accumulator& next, const Position& pos, Move m) {
    next = cur;

    const Color us = pos.side_to_move();
    const int from = from_sq(m), to = to_sq(m);
    const Piece mover = pos.piece_on(from);
    const bool kingMove = ptype_of(mover) == KING;

    // collect (piece, from, to) changes; from/to == -1 means leave/enter board
    Piece chgPc[4]; int chgFrom[4], chgTo[4];
    int n = 0;
    if (!kingMove) {
        chgPc[n] = mover; chgFrom[n] = from; chgTo[n] = -1; ++n;
        if (is_promotion(m)) {
            chgPc[n] = make_piece(us, promo_type(m)); chgFrom[n] = -1; chgTo[n] = to; ++n;
        } else {
            chgPc[n] = mover; chgFrom[n] = -1; chgTo[n] = to; ++n;
        }
    } else {
        // king move: HalfKA has NO king features (refresh_side skips kings
        // too), so there is nothing to increment here. Our own perspective
        // is rebuilt by the caller via refresh_side after do_move; the
        // opponent perspective does not change (their king-relative view of
        // our king does not exist in the feature set).
    }
    if (flag_of(m) == MF_ENPASSANT) {
        const int capSq = to + (us == WHITE ? -8 : 8);
        chgPc[n] = pos.piece_on(capSq); chgFrom[n] = capSq; chgTo[n] = -1; ++n;
    } else if (pos.is_capture(m)) {
        chgPc[n] = pos.piece_on(to); chgFrom[n] = to; chgTo[n] = -1; ++n;
    }
    if (flag_of(m) == MF_CASTLING) {
        const bool ks = to > from;
        const int rFrom = us == WHITE ? (ks ? 7 : 0) : (ks ? 63 : 56);
        const int rTo   = us == WHITE ? (ks ? 5 : 3) : (ks ? 61 : 59);
        const Piece rook = pos.piece_on(rFrom);
        chgPc[n] = rook; chgFrom[n] = rFrom; chgTo[n] = -1; ++n;
        chgPc[n] = rook; chgFrom[n] = -1;  chgTo[n] = rTo; ++n;
    }

    const Color kside = kingMove ? us : NO_COLOR;    // pov to skip & refresh later
    for (int pov = 0; pov < 2; ++pov) {
        if (int(kside) == pov) continue;
        const int ksqT = xsq(pos.king_sq(Color(pov)), Color(pov));
        for (int i = 0; i < n; ++i) {
            if (chgFrom[i] >= 0) sub_feature(next, pov, ksqT, chgPc[i], chgFrom[i]);
            if (chgTo[i] >= 0)   add_feature(next, pov, ksqT, chgPc[i], chgTo[i]);
        }
    }
    next.computed = true;
}

// ------------------------------ inference ------------------------------------
Value evaluate(const Accumulator& acc, Color stm) {
    const int16_t* us = acc.v[int(stm)];
    const int16_t* them = acc.v[int(~stm)];
    int act[2 * H1];
    for (int i = 0; i < H1; ++i) {
        const int a = us[i], b = them[i];
        act[i]      = a < 0 ? 0 : (a > ACT_MAX ? ACT_MAX : a);
        act[H1 + i] = b < 0 ? 0 : (b > ACT_MAX ? ACT_MAX : b);
    }
    int act2[H2];
    for (int o = 0; o < H2; ++o) {
        int32_t s = gNet.fc1Bias[o];
        const int16_t* w = gNet.fc1Weight[o];
        for (int i = 0; i < 2 * H1; ++i) s += int32_t(w[i]) * act[i];
        s >>= FC_SHIFT;
        act2[o] = s < 0 ? 0 : (s > ACT_MAX ? ACT_MAX : int(s));
    }
    int32_t out = gNet.outBias;
    for (int i = 0; i < H2; ++i) out += int32_t(gNet.outWeight[i]) * act2[i];
    return Value(out >> FC_SHIFT);
}

Value evaluate_fresh(const Position& pos) {
    Accumulator acc;
    refresh(acc, pos);
    return evaluate(acc, pos.side_to_move());
}

} // namespace NNUE
} // namespace Veltrix
