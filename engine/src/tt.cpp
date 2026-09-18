// Veltrix 1.0 - transposition table
// Copyright (C) 2026 Veltrix Project
// SPDX-License-Identifier: GPL-3.0-or-later
#include "tt.h"
#include <cstdlib>
#include <cstring>
#include <algorithm>

namespace Veltrix {

TranspositionTable gTT;

TranspositionTable::TranspositionTable()
    : table(nullptr), clusterCount(0), totalMB(0), generation(0) {
    hits = misses = stores = 0;
}

TranspositionTable::~TranspositionTable() { std::free(table); }

void TranspositionTable::resize(size_t megabytes) {
    std::free(table);
    table = nullptr;
    clusterCount = 0;
    totalMB = 0;

    if (megabytes == 0) megabytes = 1;
    size_t bytes = megabytes * 1024 * 1024;
    size_t clusters = bytes / (sizeof(TTEntry) * TT_CLUSTER_SIZE);
    // round down to a power of two for fast masking
    size_t pow2 = 1;
    while (pow2 * 2 <= clusters) pow2 *= 2;
    clusters = pow2;
    if (clusters == 0) clusters = 1;

    table = static_cast<TTEntry*>(std::malloc(clusters * TT_CLUSTER_SIZE * sizeof(TTEntry)));
    if (!table) {
        // fall back to a small table
        clusters = 1024;
        table = static_cast<TTEntry*>(std::malloc(clusters * TT_CLUSTER_SIZE * sizeof(TTEntry)));
        if (!table) { clusterCount = 0; return; }
    }
    clusterCount = clusters;
    totalMB = (clusterCount * TT_CLUSTER_SIZE * sizeof(TTEntry)) / (1024 * 1024);
    clear();
}

void TranspositionTable::clear() {
    if (table)
        std::memset(table, 0, clusterCount * TT_CLUSTER_SIZE * sizeof(TTEntry));
    generation = 0;
}

void TranspositionTable::clear_stats() { hits = misses = stores = 0; }

TTEntry* TranspositionTable::probe(U64 key, bool& hit) {
    TTEntry* cluster = table + (static_cast<size_t>(key) & (clusterCount - 1)) * TT_CLUSTER_SIZE;
    const U32 k32 = static_cast<U32>(key >> 32);

    for (int i = 0; i < TT_CLUSTER_SIZE; ++i) {
        if (cluster[i].key32 == k32) { hit = true; ++hits; return &cluster[i]; }
        if (cluster[i].bound == 0 && cluster[i].depth == 0 && cluster[i].move == 0 && cluster[i].key32 == 0) {
            // definitely empty slot
            hit = false; ++misses; return &cluster[i];
        }
    }

    // replacement: prefer shallow entries or entries from old generations
    TTEntry* best = &cluster[0];
    int bestScore = best->depth - ((best->bound & TT_GEN_MASK) == generation ? 8 : 0);
    for (int i = 1; i < TT_CLUSTER_SIZE; ++i) {
        int s = cluster[i].depth - ((cluster[i].bound & TT_GEN_MASK) == generation ? 8 : 0);
        if (s < bestScore) { bestScore = s; best = &cluster[i]; }
    }
    hit = false; ++misses;
    return best;
}

void TranspositionTable::store(U64 key, Move move, Value score, Value staticeval,
                               int depth, Bound bound) {
    bool hit;
    TTEntry* e = probe(key, hit);
    ++stores;
    // preserve the old move only when updating the entry for the same position
    if (move == MOVE_NONE && hit) move = e->move;
    e->key32 = static_cast<U32>(key >> 32);
    e->move = move;
    e->score = static_cast<I16>(score);
    e->eval = static_cast<I16>(staticeval);
    e->depth = static_cast<U8>(std::min(255, std::max(0, depth)));
    e->bound = static_cast<U8>(bound | (generation & TT_GEN_MASK));
}

} // namespace Veltrix
