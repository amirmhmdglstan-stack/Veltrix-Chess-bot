// Veltrix 1.0 - search interface
// Copyright (C) 2026 Veltrix Project
// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once

#include "position.h"
#include <vector>
#include <string>
#include <cstddef>

namespace Veltrix {

struct SearchLimits {
    int depth = 0;              // 0 = unlimited
    long movetime = 0;          // ms
    long time[2] = {0, 0};      // ms remaining (white, black)
    long inc[2] = {0, 0};       // ms increment
    int movestogo = 0;
    U64 nodes = 0;              // 0 = unlimited
    int mate = 0;               // mate in N moves (0 = none)
    bool infinite = false;
    bool ponder = false;
    std::vector<Move> searchmoves;
};

struct SearchConfig {
    int threads = 1;
    int multiPV = 1;
    bool limitStrength = false;
    int elo = 2600;
    size_t hashMB = 64;
    long moveOverhead = 30;
    bool showInfo = true;       // print UCI info lines (disabled during bench matches if wanted)
    bool useBook = false;       // probed by the UCI layer; kept here for reference
    std::string bookFile;
    std::string syzygyPath;     // accepted gracefully; TB probing not built in (yet)
};

namespace Search {

void init(size_t hashMB, int threads);
void configure(const SearchConfig& cfg);
SearchConfig& config();
void new_game();

// start a background search; prints "bestmove ... [ponder ...]" when finished
void start(const Position& rootPos, const SearchLimits& lim);
// request stop and wait for the search to finish emitting bestmove
void stop_and_join();
bool searching();
void ponderhit();

U64 nodes_total();
U64 last_completed_depth_nodes();

// synchronous search (used by bench/tests); returns best move
Move think_sync(const Position& rootPos, const SearchLimits& lim, Move* ponderOut = nullptr);

} // namespace Search
} // namespace Veltrix
