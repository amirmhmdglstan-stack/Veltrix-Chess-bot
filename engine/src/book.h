// Veltrix 1.0 - Polyglot opening-book support
// Copyright (C) 2026 Veltrix Project
// SPDX-License-Identifier: GPL-3.0-or-later
//
// Implements Polyglot book reading (the interoperable binary book format
// pioneered by Fabien Letouzey's Polyglot/Fruit). Book probing uses the
// standard 781-entry Polyglot Zobrist array (see polyglot_random.h) which is
// required verbatim for format compatibility. File format:
//   repeating 16-byte records, big-endian: key u64, move u16, weight u16, learn u32
//   move encoding: bits 0-5 to, 6-11 from, 12-14 promotion (none=0, N=1..Q=4)
//   records sorted by key. Written independently from the public spec.
#pragma once

#include "position.h"
#include <string>
#include <vector>

namespace Veltrix {

struct BookEntry {
    U64 key;
    U16 move;
    U16 weight;
    U32 learn;
};

class Book {
public:
    bool open(const std::string& path);   // returns false if unusable
    void close();
    bool is_open() const { return !entries.empty(); }
    size_t size() const { return entries.size(); }

    // weighted-random book move for the position, or MOVE_NONE
    Move probe(const Position& pos, U64& rngState) const;

    static U64 polyglot_key(const Position& pos);
    // alias used by the UCI 'bookkey' debug command
    U64 polyglot_key_for(const Position& pos) const { return polyglot_key(pos); }

private:
    std::vector<BookEntry> entries;
};

} // namespace Veltrix
