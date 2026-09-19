// Veltrix NNUE - dual-perspective HalfKP-style evaluation network (VNN1)
// Copyright (C) 2026 Veltrix Project
// SPDX-License-Identifier: GPL-3.0-or-later
//
// Independent implementation after public research on efficiently-updatable
// neural-network evaluation (NNUE / N.N. 2018, Yu & Nasu; Stockfish NNUE
// papers/wiki documentation). No third-party code is used.
//
// Architecture (see docs/NNUE.md for the full spec + trainer mirror):
//
//   features (per perspective): king square (64 buckets)
//       x 10 piece classes (friend/foe x P,N,B,R,Q) x 64 squares  = 40 960
//   per perspective:   40 960 -> int16 accumulator of width H1 (bias + rows)
//   forward: [us_acc(256) | them_acc(256)] clipReLU(0..127)
//            -> FC1 512->H2 (int16 weights, >>6, clipReLU) -> OUT H2->1 (>>6)
//   output: centipawns relative to side to move (usual engine convention)
//
// Kings are not piece-features; a KING move only forces a full refresh of the
// moving side's own perspective (enemy-POV features never reference the
// friendly king). All other moves are 2-4 sparse row add/removes.
//
// The network file is produced by tools/training/train_nnue.py; the win/loss-
// gate for promotion lives in tools/learn/. If no file is loaded the engine
// silently keeps using the handcrafted evaluator.
#pragma once

#include "types.h"

namespace Veltrix {
class Position;
}

namespace Veltrix {
namespace NNUE {

// ---------------- architecture constants (shared with the trainer) ----------
constexpr int NUM_INPUTS = 40960;      // 64 king buckets x 640
constexpr int H1 = 256;                // accumulator width per perspective
constexpr int H2 = 16;                 // hidden layer width
constexpr int FT_SHIFT = 7;            // int16 weights == float * 127
constexpr int FC_SHIFT = 6;            // int16 weights == float * 64
constexpr int ACT_MAX = 127;           // clipped ReLU ceiling
constexpr int MAX_FC_WEIGHT = 8192;    // load-time clamp (int32-overflow guard)

// one accumulator for both perspectives (per-ply copies in the search stack)
struct Accumulator {
    int16_t v[2][H1];
    bool computed = false;
};

// lifecycle ------------------------------------------------------------------
bool load_file(const char* path);       // false => HCE fallback (with info)
bool loaded();
const char* loaded_path();
void unload();

// state -----------------------------------------------------------------------
// full recomputation of both perspectives (search root)
void refresh(Accumulator& acc, const Position& pos);
// recompute ONE perspective in the given (post-move) position
void refresh_side(Accumulator& acc, const Position& pos, Color side);
// true when `m` moves a king (that side's perspective must be refreshed)
bool needs_king_refresh(const Position& pos, Move m, Color& sideOut);
// incremental update: next = cur + delta implied by `m` played in `pos`
// (pos must be the pre-move position). Perspectives needing a king refresh
// are skipped; the caller must run refresh_side() for them after do_move.
void push(const Accumulator& cur, Accumulator& next, const Position& pos, Move m);

// inference -------------------------------------------------------------------
// centipawns from side-to-move's perspective; cur must be computed
Value evaluate(const Accumulator& cur, Color stm);
// convenience: full compute + eval (root, diagnostics, HCE-comparison tests)
Value evaluate_fresh(const Position& pos);

// feature mapping (exposed for the parity checker and the trainer docs) -------
// perspective: WHITE = board as-is; BLACK = board rotated 180 degrees
// (square XOR 63, colours swapped). King square belongs to the perspective's
// own side. Piece class: 0..4 own P..Q, 5..9 enemy P..Q.
int feature_index(int ksq, Piece pc, int sq, Color perspective);

} // namespace NNUE
} // namespace Veltrix
