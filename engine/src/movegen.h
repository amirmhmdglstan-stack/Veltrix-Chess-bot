// Veltrix 1.0 - move generation
// Copyright (C) 2026 Veltrix Project
// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once

#include "position.h"

namespace Veltrix {

// generate pseudo-legal moves (all of them)
ExtMove* generate_pseudo(const Position& pos, ExtMove* out);
// generate pseudo-legal captures + queen promotions (for quiescence)
ExtMove* generate_pseudo_captures(const Position& pos, ExtMove* out);
// generate fully legal moves; returns count
int generate_legal(const Position& pos, ExtMove* out);
int generate_legal(const Position& pos, Move* out);
bool has_legal_move(const Position& pos);

// perft: exact node counting (correctness testing)
U64 perft(Position& pos, int depth);
U64 perft_root(Position& pos, int depth);   // prints divide info, returns total

Move move_from_uci(Position& pos, const std::string& s);
std::string move_to_san(const Position& pos, Move m);

} // namespace Veltrix
