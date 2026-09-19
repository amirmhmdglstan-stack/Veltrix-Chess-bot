// Veltrix 1.0 - UCI protocol loop
// Copyright (C) 2026 Veltrix Project
// SPDX-License-Identifier: GPL-3.0-or-later
#include "uci.h"
#include "bitboard.h"
#include "book.h"
#include "evaluate.h"
#include "movegen.h"
#include "nnue.h"
#include "search.h"
#include "tt.h"

#include <algorithm>
#ifdef _WIN32
#  include <windows.h>
#else
#  include <unistd.h>
#endif
#include <cctype>
#include <chrono>
#include <cstdio>
#include <cstring>
#include <iostream>
#include <sstream>
#include <string>
#include <vector>

namespace Veltrix {
namespace UCI {

namespace {
Position& gPos() {
    static Position* p = nullptr;
    if (!p) p = new Position();   // lazy: after table init
    return *p;
}
Book gBook;
bool gUseBook = true;    // UseBook default: enabled (auto-detects a nearby book)
bool gWantNnue = true;   // UseNNUE option state (UCI layer; search uses cfg.useNnue)
std::string gBookPath;
U64 gBookRng = 0x243F6A8885A308D3ULL;

void info_string(const std::string& s);   // defined below

// --- engine location detection (for zero-config book/network discovery) ---
static std::string exe_dir() {
#ifdef _WIN32
    char buf[4096];
    DWORD n = GetModuleFileNameA(nullptr, buf, sizeof(buf));
    if (n == 0 || n >= sizeof(buf)) return ".";
    std::string s(buf, buf + n);
    size_t p = s.find_last_of("\\/");
    return (p == std::string::npos) ? std::string(".") : s.substr(0, p);
#else
    char buf[4096];
    ssize_t n = ::readlink("/proc/self/exe", buf, sizeof(buf) - 1);
    if (n <= 0) return ".";
    buf[n] = '\0';
    std::string s(buf);
    size_t p = s.find_last_of('/');
    return (p == std::string::npos) ? std::string(".") : s.substr(0, p);
#endif
}

static bool joinable_file(const std::string& path) {
    std::FILE* f = std::fopen(path.c_str(), "rb");
    if (f) { std::fclose(f); return true; }
    return false;
}

// Probe a Polyglot book next to the executable / in ../books etc.
static void auto_open_book() {
    if (!gBookPath.empty() || gBook.is_open()) return;
    static const char* cand[] = {
        "/veltrix.bin",          // next to the exe
        "/books/veltrix.bin",    // exe in repo root
        "/../books/veltrix.bin", // exe in engine/ or bin/
        "/../../books/veltrix.bin"
    };
    const std::string d = exe_dir();
    for (const char* c : cand) {
        std::string p = d + c;
        if (joinable_file(p) && gBook.open(p)) {
            gBookPath = p;
            info_string("book auto-loaded from " + p + " (" +
                        std::to_string(gBook.size()) + " entries)");
            return;
        }
    }
    // fall back to CWD-relative once
    if (joinable_file("books/veltrix.bin") && gBook.open("books/veltrix.bin")) {
        gBookPath = "books/veltrix.bin";
        info_string("book auto-loaded from books/veltrix.bin (" +
                    std::to_string(gBook.size()) + " entries)");
    }
}

static void auto_load_net() {
    if (NNUE::loaded() || !gWantNnue) return;
    static const char* cand[] = {
        "/champion.nnue",            // next to the exe
        "/networks/champion.nnue",   // exe in repo root
        "/../networks/champion.nnue", // exe in engine/ or bin/
        "/../../networks/champion.nnue"
    };
    const std::string d = exe_dir();
    for (const char* c : cand) {
        std::string p = d + c;
        if (joinable_file(p) && NNUE::load_file(p.c_str())) {
            info_string("NNUE net auto-loaded from " + p);
            return;
        }
    }
    if (joinable_file("networks/champion.nnue") &&
        NNUE::load_file("networks/champion.nnue"))
        info_string("NNUE net auto-loaded from networks/champion.nnue");
}

std::string trim(const std::string& s) {
    size_t a = s.find_first_not_of(" \t\r\n");
    size_t b = s.find_last_not_of(" \t\r\n");
    return (a == std::string::npos) ? "" : s.substr(a, b - a + 1);
}

std::vector<std::string> split_ws(const std::string& s) {
    std::istringstream is(s);
    std::vector<std::string> out;
    std::string t;
    while (is >> t) out.push_back(t);
    return out;
}

std::string lower(std::string s) {
    for (auto& c : s) c = char(std::tolower((unsigned char)c));
    return s;
}

void info_string(const std::string& s) {
    std::printf("info string %s\n", s.c_str());
    std::fflush(stdout);
}

void print_options() {
    SearchConfig& c = Search::config();
    std::printf("option name Hash type spin default %d min 1 max 8192\n", int(c.hashMB));
    std::printf("option name Threads type spin default 1 min 1 max 64\n");
    std::printf("option name MultiPV type spin default 1 min 1 max 128\n");
    std::printf("option name Ponder type check default false\n");
    std::printf("option name Move Overhead type spin default 30 min 0 max 1000\n");
    // Both spellings are accepted: spec-driven `UseBook` and the Cute Chess
    // convention `OwnBook`.
    std::printf("option name UseBook type check default true\n");
    std::printf("option name UseNNUE type check default true\n");
    std::printf("option name EvalFile type string default <empty>\n");
    std::printf("option name BookFile type string default <empty>\n");
    std::printf("option name SyzygyPath type string default <empty>\n");
    std::printf("option name UCI_LimitStrength type check default false\n");
    std::printf("option name UCI_Elo type spin default 2600 min 1350 max 2850\n");
}

void on_uci() {
    auto_open_book();
    auto_load_net();
    std::printf("id name Veltrix 1.0\n");
    std::printf("id author Veltrix Project\n");
    print_options();
    std::printf("uciok\n");
    std::fflush(stdout);
}

void on_isready() { std::printf("readyok\n"); std::fflush(stdout); }

void on_setoption(const std::vector<std::string>& tokens) {
    // syntax: setoption name <name..> [value <value..>]
    std::string name, value;
    size_t i = 1;
    while (i < tokens.size() && tokens[i] != "name") ++i;
    if (i < tokens.size()) ++i;
    while (i < tokens.size() && tokens[i] != "value") { name += (name.empty() ? "" : " ") + tokens[i]; ++i; }
    if (i < tokens.size()) ++i;
    while (i < tokens.size()) { value += (value.empty() ? "" : " ") + tokens[i]; ++i; }

    std::string lname = lower(name);
    SearchConfig cfg = Search::config();
    auto as_int = [&](long def) -> long {
        std::string v = trim(value);
        if (v.empty()) return def;
        char* endp = nullptr;
        long x = std::strtol(v.c_str(), &endp, 10);
        return (endp && *endp == '\0') ? x : def;
    };

    if (lname == "hash") {
        cfg.hashMB = size_t(std::max(1L, std::min(8192L, as_int(long(cfg.hashMB)))));
        Search::configure(cfg);
    } else if (lname == "threads") {
        cfg.threads = int(std::max(1L, std::min(64L, as_int(cfg.threads))));
        Search::configure(cfg);
    } else if (lname == "multipv") {
        cfg.multiPV = int(std::max(1L, std::min(128L, as_int(cfg.multiPV))));
        Search::configure(cfg);
    } else if (lname == "move overhead") {
        cfg.moveOverhead = std::max(0L, std::min(1000L, as_int(cfg.moveOverhead)));
        Search::configure(cfg);
    } else if (lname == "ponder") {
        // stored for completeness; pondering is driven by "go ponder"
    } else if (lname == "ownbook" || lname == "usebook") {
        gUseBook = lower(trim(value)) == "true" || trim(value) == "1";
    } else if (lname == "syzygypath") {
        // Tablebase probing is not built into Veltrix 1.0. Accept the option
        // proviced by GUIs and keep working gracefully without it.
        std::string p = trim(value);
        if (!p.empty() && p != "<empty>")
            info_string("SyzygyPath accepted ('" + p + "') but tablebase probing "
                        "is not available in Veltrix 1.0; search continues without TB.");
        SearchConfig c2 = Search::config();
        c2.syzygyPath = p;
        Search::configure(c2);
    } else if (lname == "bookfile") {
        gBookPath = trim(value);
        if (!gBookPath.empty() && gBookPath != "<empty>") {
            if (gBook.open(gBookPath))
                info_string("book loaded, " + std::to_string(gBook.size()) + " entries");
            else
                info_string("could not open book file: " + gBookPath);
        }
    } else if (lname == "uci_limitstrength") {
        cfg.limitStrength = lower(trim(value)) == "true" || trim(value) == "1";
        Search::configure(cfg);
    } else if (lname == "uci_elo") {
        cfg.elo = int(std::max(1350L, std::min(2850L, as_int(cfg.elo))));
        cfg.limitStrength = true;
        Search::configure(cfg);
    } else if (lname == "usennue") {
        gWantNnue = lower(trim(value)) == "true" || trim(value) == "1";
        cfg.useNnue = gWantNnue;
        Search::configure(cfg);
        if (gWantNnue && !NNUE::loaded()) auto_load_net();
    } else if (lname == "evalfile") {
        std::string p = trim(value);
        cfg.evalFile = p;
        Search::configure(cfg);
        if (!p.empty() && p != "<empty>") {
            if (NNUE::load_file(p.c_str()))
                info_string("NNUE net loaded: " + p);
            else
                info_string("could not load NNUE net: " + p +
                            " (handcrafted eval remains active)");
        }
    } else if (!name.empty()) {
        info_string("unknown option: " + name);
    }
}

void cmd_position(const std::vector<std::string>& tokens) {
    // position [startpos | fen <fen...>] [moves <m1> <m2> ...]
    size_t i = 1;
    if (i >= tokens.size()) return;
    if (tokens[i] == "startpos") {
        gPos().set_startpos();
        ++i;
        if (i < tokens.size() && tokens[i] == "moves") ++i;
    } else if (tokens[i] == "fen") {
        ++i;
        std::string fen;
        while (i < tokens.size() && tokens[i] != "moves") {
            fen += tokens[i] + " ";
            ++i;
        }
        if (!gPos().set_fen(trim(fen))) {
            info_string("invalid FEN: " + fen);
            gPos().set_startpos();
            return;
        }
        if (i < tokens.size() && tokens[i] == "moves") ++i;
    }
    for (; i < tokens.size(); ++i) {
        Move m = move_from_uci(gPos(), tokens[i]);
        if (m == MOVE_NONE) break;
        gPos().do_move(m);
    }
}

bool try_book(SearchLimits& lim) {
    if (!gUseBook || !gBook.is_open()) return false;
    // never book when given explicit constraints beyond plain search
    if (!lim.searchmoves.empty()) return false;
    Move m = gBook.probe(gPos(), gBookRng);
    if (m == MOVE_NONE) return false;
    std::printf("info string book move %s\n", move_to_str(m).c_str());
    std::printf("bestmove %s\n", move_to_str(m).c_str());
    std::fflush(stdout);
    return true;
}

void cmd_go(const std::vector<std::string>& tokens) {
    if (Search::searching()) {
        info_string("already searching; ignoring go");
        return;
    }
    SearchLimits lim;
    for (size_t i = 1; i < tokens.size(); ++i) {
        const std::string& t = tokens[i];
        if (t == "depth" && i + 1 < tokens.size()) lim.depth = std::atoi(tokens[++i].c_str());
        else if (t == "movetime" && i + 1 < tokens.size()) lim.movetime = std::atol(tokens[++i].c_str());
        else if (t == "wtime" && i + 1 < tokens.size()) lim.time[WHITE] = std::atol(tokens[++i].c_str());
        else if (t == "btime" && i + 1 < tokens.size()) lim.time[BLACK] = std::atol(tokens[++i].c_str());
        else if (t == "winc" && i + 1 < tokens.size()) lim.inc[WHITE] = std::atol(tokens[++i].c_str());
        else if (t == "binc" && i + 1 < tokens.size()) lim.inc[BLACK] = std::atol(tokens[++i].c_str());
        else if (t == "movestogo" && i + 1 < tokens.size()) lim.movestogo = std::atoi(tokens[++i].c_str());
        else if (t == "nodes" && i + 1 < tokens.size()) lim.nodes = (U64)std::strtoull(tokens[++i].c_str(), nullptr, 10);
        else if (t == "mate" && i + 1 < tokens.size()) lim.mate = std::atoi(tokens[++i].c_str());
        else if (t == "infinite") lim.infinite = true;
        else if (t == "ponder") lim.ponder = true;
        else if (t == "searchmoves") {
            while (i + 1 < tokens.size() && tokens[i + 1] != "wtime" && tokens[i + 1] != "btime" &&
                   tokens[i + 1] != "depth" && tokens[i + 1] != "movetime" &&
                   tokens[i + 1] != "nodes" && tokens[i + 1] != "infinite" &&
                   tokens[i + 1] != "mate" && tokens[i + 1] != "winc" &&
                   tokens[i + 1] != "binc" && tokens[i + 1] != "movestogo" &&
                   tokens[i + 1] != "ponder") {
                Move m = move_from_uci(gPos(), tokens[i + 1]);
                if (m != MOVE_NONE) lim.searchmoves.push_back(m);
                ++i;
            }
        }
    }
    if (try_book(lim)) return;

    // If the position is already decided, emit bestmove 0000 immediately if there
    // are no legal moves (engine GUIs expect a bestmove response).
    ExtMove buf[MAX_MOVES];
    if (generate_legal(gPos(), buf) == 0) {
        std::printf("bestmove 0000\n");
        std::fflush(stdout);
        return;
    }
    Search::start(gPos(), lim);
}

std::string bench_fens[] = {
    "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1",
    "r3k2r/p1ppqpb1/bn2pnp1/3PN3/1p2P3/2N2Q1p/PPPBBPPP/R3K2R w KQkq - 0 1",
    "8/2p5/3p4/KP5r/1R3p1k/8/4P1P1/8 w - - 0 1",
    "r3k2r/Pppp1ppp/1b3nbN/nP6/BBP1P3/q4N2/Pp1P2PP/R2Q1RK1 w kq - 0 1",
    "rnbq1k1r/pp1Pbppp/2p5/8/2B5/8/PPP1NnPP/RNBQK2R w KQ - 1 7",
    "r4rk1/1pp1qppp/p1np1n2/2b1p1B1/2B1P1b1/P1NP1N2/1PP1QPPP/R4RK1 w - - 0 1",
    "2r3k1/1q1nbppp/r3p3/3pP3/pBpP4/P1Q1BPPP/1B3P2/R4RK1 w - - 0 1",
    "r1bq1rk1/pp1p1ppp/2n1pn2/2b5/2BPP3/2N1PN2/PP3PPP/R1BQ1RK1 w - - 0 1",
    "4rrk1/pp1n1ppp/2p2nq1/3p4/3P4/2PBPQ2/PP1N1PPP/R3R1K1 w - - 0 1",
    "rn2k2r/pp2qppp/2p2n2/4p1B1/2B1P3/8/PPP2PPP/RNB2RK1 w kq - 0 1",
    "3r1rk1/p1q2ppp/1p2pn2/n2p4/2pP4/2P1PN2/PP1B1PPP/R2Q1RK1 w - - 0 1",
    "r3k2r/ppqb1ppp/2n1pn2/3p4/3P4/2NBPN2/PPQ2PPP/R1B1K2R w KQkq - 0 1",
    "8/6k1/8/8/8/1K6/8/8 w - - 0 1",
    "8/8/1k6/8/8/2K5/8/8 w - - 0 1",
    "k7/8/2K5/8/8/8/8/QR6 w - - 0 1",
    "6k1/6p1/8/8/8/8/1r6/3K4 w - - 0 1",
    "r1b2rk1/pp1q1ppp/2n2n2/2bp4/4P3/2NB1N2/PP2BPPP/R1BQK2R w KQ - 0 1",
    "1kr4r/ppp2ppp/2nbpn2/3q4/3P4/P1N1PN2/1PP2PPP/R1BQKB1R w KQ - 0 1",
    "r4r1k/1b1n1ppp/2pqpn2/pp6/3P4/1BN1PN2/PPQ2PPP/R1B2RK1 w - - 0 1",
    "2rq1rk1/3nbppp/p2pbn2/1p2p3/3PP3/2N1BN2/PPQ2PPP/R1B2RK1 w - - 0 1",
    "5k2/1b2rpp1/2rq1n1p/pp2pP2/4P2P/1P2BN2/P1P3P1/1K1R4 w - - 0 1",
    "8/2r2pk1/3b2p1/1p2p2p/3pP3/5P1P/PR4P1/4R1K1 w - - 0 1",
    "6k1/p1p2pp1/1p1p3p/8/2PP4/6P1/P2Q1P1P/4R1K1 w - - 0 1",
    "r7/4k3/P4p2/2p1pP1p/2P1P3/8/K7/3R4 w - - 0 1",
};

void cmd_bench(const std::vector<std::string>& tokens) {
    int depth = 13;
    if (tokens.size() >= 2) depth = std::atoi(tokens[1].c_str());
    depth = std::max(1, depth);

    SearchConfig& cfg = Search::config();
    std::printf("Veltrix 1.0 bench: depth %d, threads %d, hash %zu MB\n",
                depth, cfg.threads, gTT.size_mb());
    std::fflush(stdout);

    U64 totalNodes = 0;
    auto t0 = std::chrono::steady_clock::now();
    SearchConfig silent = Search::config();
    silent.showInfo = false;
    Search::configure(silent);

    for (const std::string& fen : bench_fens) {
        Position pos;
        if (!pos.set_fen(fen)) { info_string("bad bench fen"); continue; }
        SearchLimits lim;
        lim.depth = depth;
        auto p0 = std::chrono::steady_clock::now();
        Move bm = Search::think_sync(pos, lim, nullptr);
        auto p1 = std::chrono::steady_clock::now();
        U64 n = Search::nodes_total();
        totalNodes += n;
        // duration::rep is int64_t; store/print as long long (lossless implicit
        // conversion) so the code is well-typed on LP64 AND LLP64 (Windows).
        const long long ms =
            std::chrono::duration_cast<std::chrono::milliseconds>(p1 - p0).count();
        std::printf("%-72s bestmove %-5s nodes %12llu time %6lld ms\n",
                    fen.substr(0, 60).c_str(), move_to_str(bm).c_str(),
                    (unsigned long long)n, ms);
        std::fflush(stdout);
    }
    auto t1 = std::chrono::steady_clock::now();
    // std::max<T> explicitly over duration rep (int64_t == long long on LLP64
    // Windows, long on LP64 Linux) - deduction used to fail on MSYS2/MSVC.
    const long long totalMs = std::max<long long>(
        1LL, std::chrono::duration_cast<std::chrono::milliseconds>(t1 - t0).count());
    SearchConfig show = Search::config();
    show.showInfo = true;
    Search::configure(show);
    std::printf("===========================\n");
    std::printf("Total time : %lld ms\n", totalMs);
    std::printf("Total nodes: %llu\n", (unsigned long long)totalNodes);
    std::printf("Nodes/second: %llu\n", (unsigned long long)(totalNodes * 1000ULL / static_cast<U64>(totalMs)));
    std::fflush(stdout);
}

void cmd_compiler() {
#if defined(__clang__)
    info_string("compiled by Clang " __clang_version__);
#elif defined(_MSC_VER)
    info_string("compiled by MSVC");
#elif defined(__GNUC__)
    info_string("compiled by GCC " __VERSION__);
#else
    info_string("unknown compiler");
#endif
}

} // namespace

void loop() {
    init_bitboards();
    init_zobrist();
    init_castling_masks();
    Eval::evaluate(Position());  // triggers eval tables init
    Search::init(Search::config().hashMB, Search::config().threads);

    std::string line;
    while (std::getline(std::cin, line)) {
        line = trim(line);
        if (line.empty()) continue;
        std::vector<std::string> tokens = split_ws(line);
        const std::string& cmd = tokens[0];

        if (cmd == "uci") on_uci();
        else if (cmd == "isready") on_isready();
        else if (cmd == "ucinewgame") {
            Search::stop_and_join();
            Search::new_game();
        } else if (cmd == "setoption") on_setoption(tokens);
        else if (cmd == "position") cmd_position(tokens);
        else if (cmd == "go") cmd_go(tokens);
        else if (cmd == "stop") Search::stop_and_join();
        else if (cmd == "ponderhit") Search::ponderhit();
        else if (cmd == "quit") { Search::stop_and_join(); return; }
        else if (cmd == "d") { std::printf("%s\n", gPos().pretty().c_str()); std::fflush(stdout); }
        else if (cmd == "key") { std::printf("key: %016llx\n", (unsigned long long)gPos().key()); std::fflush(stdout); }
        else if (cmd == "nnueeval") {
            if (NNUE::loaded() && Search::config().useNnue) {
                std::printf("nnue %d\n", int(NNUE::evaluate_fresh(gPos())));
                std::fflush(stdout);
            } else {
                std::printf("nnue off\n");
                std::fflush(stdout);
            }
        }
        else if (cmd == "bookkey") { std::printf("bookkey: %016llx\n", (unsigned long long)gBook.polyglot_key_for(gPos())); std::fflush(stdout); }
        else if (cmd == "perft" && tokens.size() >= 2) {
            int d = std::atoi(tokens[1].c_str());
            perft_root(gPos(), d);
            std::fflush(stdout);
        } else if (cmd == "moves") {
            ExtMove buf[MAX_MOVES];
            int n = generate_legal(gPos(), buf);
            std::printf("moves:");
            for (int i = 0; i < n; ++i) std::printf(" %s", move_to_str(buf[i].move).c_str());
            std::printf("\n");
            std::fflush(stdout);
        } else if (cmd == "eval") {
            std::string t = Eval::trace(gPos());
            std::printf("%s\n", t.c_str());
            std::fflush(stdout);
        } else if (cmd == "bench") cmd_bench(tokens);
        else if (cmd == "compiler") cmd_compiler();
        else {
            // unknown commands are ignored (UCI tolerance)
        }
    }
    // stdin closed (pipe ended / GUI went away without sending "quit"):
    // shut down just as cleanly - an abandoned async search thread racing
    // process teardown must not crash.
    Search::stop_and_join();
}

} // namespace UCI
} // namespace Veltrix
