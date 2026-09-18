// Veltrix 1.0 - hand-crafted position evaluation (tapered)
// Copyright (C) 2026 Veltrix Project
// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once

#include "position.h"

namespace Veltrix {

namespace Eval {

// static evaluation from the perspective of the side to move
Value evaluate(const Position& pos);

// detailed textual breakdown (for the UCI "eval" command)
std::string trace(const Position& pos);

} // namespace Eval
} // namespace Veltrix
