// Veltrix 1.0 - entry point
// Copyright (C) 2026 Veltrix Project
// SPDX-License-Identifier: GPL-3.0-or-later
#include "bitboard.h"
#include "position.h"
#include "movegen.h"
#include "uci.h"

#include <cstdio>
#include <string>

int main(int argc, char** argv) {
    Veltrix::init_bitboards();
    Veltrix::init_zobrist();
    Veltrix::init_castling_masks();

    // convenience command-line modes (headless testing)
    if (argc >= 3 && std::string(argv[1]) == "perft") {
        Veltrix::Position pos;
        int depth = std::atoi(argv[2]);
        if (argc >= 4 && !pos.set_fen(argv[3])) {
            std::printf("bad fen\n");
            return 1;
        }
        Veltrix::perft_root(pos, depth);
        return 0;
    }
    if (argc >= 2 && std::string(argv[1]) == "bench-cmd") {
        // handled by the UCI "bench" command; this alias helps scripting
    }

    // standard UCI loop
    std::setvbuf(stdout, nullptr, _IONBF, 0);
    Veltrix::UCI::loop();
    return 0;
}
