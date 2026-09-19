// Veltrix 1.0 - transposition table (4-way set associative, 16-byte entries)
// Copyright (C) 2026 Veltrix Project
// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once

#include "types.h"
#include <vector>
#include <cstddef>

namespace Veltrix {

struct TTEntry {
    U32 key32;
    U32 move;
    I16 score;   // search score (mate-distance adjusted for the stored ply)
    I16 eval;    // static evaluation (VALUE_NONE if none)
    U8  depth;
    U8  bound;   // Bound | generation bits: low 2 bits bound, high 6 bits generation
};
static_assert(sizeof(TTEntry) == 16, "TTEntry must be 16 bytes");

constexpr int TT_CLUSTER_SIZE = 4;
constexpr int TT_GEN_MASK = 0xFC;   // generation stored in high bits of 'bound'
constexpr int TT_BOUND_MASK = 0x03;

class TranspositionTable {
public:
    TranspositionTable();
    ~TranspositionTable();

    void resize(size_t megabytes);
    void clear();
    void clear_stats();
    size_t size_mb() const { return totalMB; }

    // probe: returns pointer to an entry with matching key or to the best
    // replacement slot (never nullptr). 'hit' reflects an exact key match.
    TTEntry* probe(U64 key, bool& hit);

    void store(U64 key, Move move, Value score, Value staticeval, int depth, Bound bound);
    void increment_generation() { generation = (generation + 4) & TT_GEN_MASK; }

    // statistics (approximate):
    U64 hits, misses, stores;

private:
    TTEntry* table;
    size_t clusterCount;
    size_t totalMB;
    U8 generation;
};

extern TranspositionTable gTT;

// helpers for mate-distance-correct TT values
inline I16 to_tt_score(Value v, int ply) {
    if (v >= VALUE_MATE_IN_MAX_PLY) return I16(v + ply);
    if (v <= -VALUE_MATE_IN_MAX_PLY) return I16(v - ply);
    return I16(v);
}
inline Value from_tt_score(I16 v, int ply) {
    if (v >= VALUE_MATE_IN_MAX_PLY) return Value(v) - ply;
    if (v <= -VALUE_MATE_IN_MAX_PLY) return Value(v) + ply;
    return Value(v);
}

} // namespace Veltrix
