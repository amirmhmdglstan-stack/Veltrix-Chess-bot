// Veltrix 1.0 - Polyglot opening-book implementation
// Copyright (C) 2026 Veltrix Project
// SPDX-License-Identifier: GPL-3.0-or-later
#include "book.h"
#include "movegen.h"
#include "polyglot_random.h"

#include <algorithm>
#include <cstdio>
#include <cstring>

namespace Veltrix {

// Polyglot piece index: black = ptype*2, white = ptype*2 + 1
// (note the opposite of the engine's WHITE=0 / BLACK=1 enum).
static int poly_piece_index(Piece p) {
    return int(ptype_of(p)) * 2 + (color_of(p) == WHITE ? 1 : 0);
}

U64 Book::polyglot_key(const Position& pos) {
    U64 key = 0;
    for (int sq = 0; sq < 64; ++sq) {
        Piece p = pos.piece_on(sq);
        if (p != NO_PIECE)
            key ^= POLYGLOT_RANDOM[64 * poly_piece_index(p) + sq];
    }
    U64 bb;
    // castling rights (king/rook squares must also be plausible, matching the
    // spirit of the format: rights bits are used as-is)
    int cr = pos.castling_rights();
    if (cr & WHITE_OO)  key ^= POLYGLOT_RANDOM[768];
    if (cr & WHITE_OOO) key ^= POLYGLOT_RANDOM[769];
    if (cr & BLACK_OO)  key ^= POLYGLOT_RANDOM[770];
    if (cr & BLACK_OOO) key ^= POLYGLOT_RANDOM[771];
    // en passant file, only if a side-to-move pawn can actually capture onto it
    if (pos.ep_square() != SQ_NONE) {
        int f = file_of(pos.ep_square());
        Color stm = pos.side_to_move();
        bb = pos.pieces(stm, PAWN);
        U64 captureSquares = pos.ep_square() >= 8 && pos.ep_square() < 56
                                 ? (stm == WHITE ? (BB::square_bb(pos.ep_square() - 8))
                                                 : (BB::square_bb(pos.ep_square() + 8)))
                                 : 0;
        U64 adjacent = BB::shift_e(captureSquares) | BB::shift_w(captureSquares);
        if (adjacent & bb) key ^= POLYGLOT_RANDOM[772 + f];
    }
    if (pos.side_to_move() == WHITE) key ^= POLYGLOT_RANDOM[780];
    return key;
}

bool Book::open(const std::string& path) {
    entries.clear();
    FILE* f = std::fopen(path.c_str(), "rb");
    if (!f) return false;
    std::fseek(f, 0, SEEK_END);
    long sz = std::ftell(f);
    std::fseek(f, 0, SEEK_SET);
    if (sz <= 0 || sz % 16 != 0) { std::fclose(f); return false; }
    size_t n = size_t(sz / 16);
    entries.resize(n);
    bool ok = true;
    for (size_t i = 0; i < n; ++i) {
        U8 b[16];
        if (std::fread(b, 1, 16, f) != 16) { ok = false; break; }
        U64 key = 0;
        for (int j = 0; j < 8; ++j) key = (key << 8) | b[j];
        U16 mv = U16((b[8] << 8) | b[9]);
        U16 wt = U16((b[10] << 8) | b[11]);
        U32 ln = 0;
        for (int j = 12; j < 16; ++j) ln = (ln << 8) | b[j];
        entries[i] = BookEntry{key, mv, wt, ln};
    }
    std::fclose(f);
    if (!ok) entries.clear();
    return ok && !entries.empty();
}

void Book::close() { entries.clear(); }

Move Book::probe(const Position& pos, U64& rngState) const {
    if (entries.empty()) return MOVE_NONE;
    const U64 key = polyglot_key(pos);

    // binary search for the first entry with this key
    size_t lo = 0, hi = entries.size();
    while (lo < hi) {
        size_t mid = (lo + hi) / 2;
        if (entries[mid].key < key) lo = mid + 1;
        else hi = mid;
    }
    if (lo >= entries.size() || entries[lo].key != key) return MOVE_NONE;
    size_t first = lo, last = lo;
    while (last < entries.size() && entries[last].key == key) ++last;

    // collect legal book moves with weights
    struct Cand { Move move; int weight; };
    Cand cands[64];
    int nc = 0;
    int totalW = 0;
    for (size_t i = first; i < last; ++i) {
        const BookEntry& e = entries[i];
        int to = e.move & 63;
        int from = (e.move >> 6) & 63;
        int promo = (e.move >> 12) & 7;   // 0 none, 1 N, 2 B, 3 R, 4 Q
        // normalize to an internal legal move
        Move wanted = MOVE_NONE;
        std::string uci = sq_to_str(from) + sq_to_str(to);
        if (promo) uci += "nbrq"[promo - 1];
        Position tmp = pos;
        Move m = move_from_uci(tmp, uci);
        // Polyglot represents castling as the king move itself (e1g1 etc.)
        if (m == MOVE_NONE) continue;
        wanted = m;
        int w = e.weight;
        if (w > 0) {
            cands[nc++] = Cand{wanted, w};
            totalW += w;
        }
    }
    if (nc == 0 || totalW == 0) return MOVE_NONE;

    U64 rnd = rngState * 6364136223846793005ULL + 1442695040888963407ULL;
    rngState = rnd;
    int pick = int((rnd >> 33) % U64(totalW));
    for (int i = 0; i < nc; ++i) {
        if (pick < cands[i].weight) return cands[i].move;
        pick -= cands[i].weight;
    }
    return cands[nc - 1].move;
}

} // namespace Veltrix
