// Veltrix 1.0 - hand-crafted evaluation
// Copyright (C) 2026 Veltrix Project
// SPDX-License-Identifier: GPL-3.0-or-later
//
// A tapered (mg/eg) evaluation: material + piece-square tables (PeSTO, CC0),
// mobility, pawn structure (hash-cached), passed/isolated/doubled/backward
// pawns, king safety via king-ring attack units, king shelter, rooks on
// open/semi-open files and the 7th rank, knight outposts, bishop pair, tempo,
// endgame mop-up, and drawish-endgame scaling.
#include "evaluate.h"
#include "psqt.h"
#include "bitboard.h"
#include <sstream>
#include <cstring>

namespace Veltrix {
namespace Eval {

namespace {

// --------------------------------------------------------------------------
// Evaluation tuning constants (mg, eg). Centipawns, from White's perspective.
// --------------------------------------------------------------------------
struct S { int mg, eg; };

constexpr S makeS(int mg, int eg) { return S{mg, eg}; }

// mobility bonus per attacked (non-own) square
constexpr S MOBILITY[6] = { S{0,0}, S{4,8}, S{5,9}, S{2,7}, S{3,8}, S{0,0} };
// rook on open / semi-open file
constexpr S ROOK_OPEN     = makeS(20, 10);
constexpr S ROOK_SEMI     = makeS(10, 5);
constexpr S ROOK_7TH      = makeS(8, 13);
// knight outpost (bonus doubled when defended by own pawn)
constexpr S OUTPOST       = makeS(18, 12);
// bishop pair
constexpr S BISHOP_PAIR   = makeS(20, 45);
// pawn structure
constexpr S ISOLATED      = makeS(-8, -12);
constexpr S DOUBLED       = makeS(-6, -12);
constexpr S BACKWARD      = makeS(-9, -12);
// passed pawn by relative rank (index = rel. rank 0..7)
constexpr S PASSED[8] = { S{0,0}, S{0,5}, S{5,12}, S{15,25}, S{30,50}, S{55,85}, S{90,130}, S{0,0} };

constexpr int TEMPO = 15;

// king-safety danger table (indexed by accumulated attack units)
int DangerTable[64];
void init_danger_table() {
    static bool done = false;
    if (done) return;
    done = true;
    for (int i = 0; i < 64; ++i) {
        int v = (i * i) / 3;
        DangerTable[i] = v > 512 ? 512 : v;
    }
}

// --------------------------------------------------------------------------
// Pawn-structure cache
// --------------------------------------------------------------------------
struct PawnEntry {
    U64 key = 0;
    int mg = 0, eg = 0;
};
constexpr size_t PAWN_CACHE_SIZE = 1 << 16;
PawnEntry pawnCache[PAWN_CACHE_SIZE];

// score the pawn structure from White's perspective (cached by pawn key)
PawnEntry eval_pawns(const Position& pos) {
    const U64 key = pos.pawn_key();
    PawnEntry& e = pawnCache[key & (PAWN_CACHE_SIZE - 1)];
    if (e.key == key) return e;

    PawnEntry res;
    res.key = key;
    res.mg = res.eg = 0;
    int mg = 0, eg = 0;

    for (int c = 0; c < 2; ++c) {
        const Color us = Color(c);
        const Color them = ~us;
        int sign = (us == WHITE) ? 1 : -1;
        U64 pawns = pos.pieces(us, PAWN);
        U64 enemyPawns = pos.pieces(them, PAWN);
        U64 bb = pawns;
        while (bb) {
            int sq = BB::pop_lsb_sq(bb);
            const int f = file_of(sq);
            const int relRank = relative_rank(us, sq);
            const U64 adj = adjacent_files_bb(f);
            // isolated: no friendly pawn on adjacent files
            if (!(adj & pawns)) { mg += sign * ISOLATED.mg; eg += sign * ISOLATED.eg; }
            // doubled: another own pawn ahead on the same file
            if (forward_file_bb(us, sq) & pawns) { mg += sign * DOUBLED.mg; eg += sign * DOUBLED.eg; }
            // passed: no enemy pawn on the same or adjacent files in front
            U64 front = forward_ranks_bb(us, rank_of(sq)) & (file_bb(f) | adj);
            if (!(front & enemyPawns)) {
                mg += sign * PASSED[relRank].mg;
                eg += sign * PASSED[relRank].eg;
            } else {
                // backward: neighbours behind, and the stop square is enemy-pawn controlled
                U64 rearNeighbours = adj & pawns & ~forward_ranks_bb(us, rank_of(sq));
                if (!rearNeighbours) {
                    int stop = (us == WHITE) ? sq + 8 : sq - 8;
                    U64 stoppers = PawnAttacks[us][stop] & enemyPawns;
                    if (stoppers && !(pos.pieces(them) & BB::square_bb(stop))) {
                        mg += sign * BACKWARD.mg; eg += sign * BACKWARD.eg;
                    }
                }
            }
        }
    }
    res.mg = mg; res.eg = eg;
    e = res;
    return res;
}

// --------------------------------------------------------------------------
// King shelter: own pawns directly in front of the king (mg only)
// --------------------------------------------------------------------------
template <Color Us>
int king_shelter(const Position& pos) {
    constexpr Color Them = ~Us;
    const int ksq = pos.king_sq(Us);
    const int kf = file_of(ksq);
    const int kr = rank_of(ksq);
    int mg = 0;
    U64 ownPawns = pos.pieces(Us, PAWN);
    for (int df = -1; df <= 1; ++df) {
        int f = kf + df;
        if (f < 0 || f > 7) continue;
        U64 ahead = file_bb(f);
        int best = 64;  // relative distance of the nearest shelter pawn
        U64 pawnsOnFile = ownPawns & ahead;
        while (pawnsOnFile) {
            int sq = BB::pop_lsb_sq(pawnsOnFile);
            int r = rank_of(sq);
            int dist = (Us == WHITE) ? (r - kr) : (kr - r);
            if (dist > 0 && dist < best) best = dist;
        }
        if (best == 1) mg += 12;
        else if (best == 2) mg += 7;
        else if (best == 3) mg += 2;
        else mg -= 12;  // no pawn shield on this file
    }
    (void)0;
    return mg;
}

// --------------------------------------------------------------------------
// drawish-endgame scaling (factor in 1/128ths, from the winner's viewpoint)
// --------------------------------------------------------------------------
int scale_factor(const Position& pos, int winnerColor) {
    const Color w = Color(winnerColor);
    // completely bare king of the loser
    int loserNpmCount = 0;
    for (int pt = KNIGHT; pt <= QUEEN; ++pt) loserNpmCount += pos.count(~w, PieceType(pt));
    if (pos.count(~w, PAWN) != 0 || loserNpmCount != 0) {
        // opposite-coloured bishops ending: only bishops and pawns on the board,
        // bishops on different colours
        int totalMajorsEtc = 0;
        for (int pt = KNIGHT; pt <= QUEEN; ++pt)
            if (pt != BISHOP) totalMajorsEtc += pos.count(WHITE, PieceType(pt)) + pos.count(BLACK, PieceType(pt));
        if (totalMajorsEtc == 0 && pos.count(W_BISHOP) == 1 && pos.count(B_BISHOP) == 1) {
            int wsq = BB::lsb(pos.pieces(W_BISHOP));
            int bsq = BB::lsb(pos.pieces(B_BISHOP));
            if ((((wsq + rank_of(wsq)) & 1) != ((bsq + rank_of(bsq)) & 1))) {
                int pdiff = pos.count(w, PAWN) - pos.count(~w, PAWN);
                if (pdiff >= 0 && pdiff <= 2) return 64;  // half value
                if (pdiff >= 0) return 80;
            }
        }
        return 128;
    }
    // loser has a bare king
    if (pos.count(w, PAWN) != 0) return 128;
    int minors[2] = {0,0};
    int npm = 0;
    for (int pt = KNIGHT; pt <= QUEEN; ++pt) {
        int cnt = pos.count(w, PieceType(pt));
        minors[0] += (pt == KNIGHT || pt == BISHOP) ? cnt : 0;
        npm += cnt * MG_VALUE[pt];
    }
    (void)minors;
    if (npm <= MG_VALUE[BISHOP] + MG_VALUE[KNIGHT] - 10) {
        // KNN vs K and KB+KN-vs-K type material with no pawns fail to win
        int knights = pos.count(w, KNIGHT);
        int bishops = pos.count(w, BISHOP);
        int rooks = pos.count(w, ROOK);
        int queens = pos.count(w, QUEEN);
        if (rooks == 0 && queens == 0) {
            if (knights + bishops <= 1) return 0;     // single minor: insufficient
            if (knights == 2 && bishops == 0) return 4;  // KNN vs K: cannot mate
            if (knights == 1 && bishops == 1) return 128; // KBN + ...: wins
            if (bishops == 2 && knights == 0) {
                // KBB vs K wins only with opposite-coloured bishops
                U64 bb = pos.pieces(w, BISHOP);
                int s1 = BB::lsb(bb); int s2 = BB::msb(bb);
                if ((((s1 + rank_of(s1)) & 1)) == (((s2 + rank_of(s2)) & 1))) return 0;
                return 128;
            }
        }
    }
    return 128;
}

// --------------------------------------------------------------------------
// endgame mop-up: drive the bare king into a corner
// --------------------------------------------------------------------------
template <bool Traced>
int mop_up_bonus(const Position& pos, int phase, std::ostringstream* os) {
    // lone king against a mating material set
    for (int w = 0; w < 2; ++w) {
        Color strong = Color(w);
        Color weak = ~strong;
        int weakCnt = pos.count(weak, PAWN) + pos.count(weak, KNIGHT) + pos.count(weak, BISHOP) +
                      pos.count(weak, ROOK) + pos.count(weak, QUEEN);
        if (weakCnt != 0) continue;
        int strongNpm = 0;
        for (int pt = KNIGHT; pt <= QUEEN; ++pt) strongNpm += pos.count(strong, PieceType(pt)) * MG_VALUE[pt];
        // lone knight/bishop cannot mate; a rook (or more) can.
        if (strongNpm < MG_VALUE[ROOK]) continue;
        // almost pure endgame
        if (phase > 6) continue;
        int wk = pos.king_sq(weak);
        int sk = pos.king_sq(strong);
        int cmd = std::abs(2 * file_of(wk) - 7) + std::abs(2 * rank_of(wk) - 7);      // centre distance
        int md = std::abs(file_of(wk) - file_of(sk)) + std::abs(rank_of(wk) - rank_of(sk)); // kings' distance
        int bonus = cmd * 20 + (14 - md) * 18;
        // shepherding: a rook/queen whose rank or file separates the two kings
        // forms the "box" used to shepherd the bare king to the edge.
        U64 sliders = pos.pieces(strong, ROOK) | pos.pieces(strong, QUEEN);
        while (sliders) {
            int r = BB::pop_lsb(sliders);
            int rf = file_of(r), rr = rank_of(r);
            int t;
            t = (rank_of(wk) - rr) * (rank_of(sk) - rr);
            if (t < 0) bonus += 30;  // rook rank lies strictly between the kings' ranks
            t = (file_of(wk) - rf) * (file_of(sk) - rf);
            if (t < 0) bonus += 30;  // rook file lies strictly between the kings' files
        }
        if (Traced && os) {
            *os << "mopup " << (strong == WHITE ? "white" : "black") << ": " << bonus << "\n";
        }
        return strong == WHITE ? bonus : -bonus;
    }
    return 0;
}

// --------------------------------------------------------------------------
// main evaluation body
// --------------------------------------------------------------------------
template <bool Traced>
Value evaluate_impl(const Position& pos, std::ostringstream* os) {
    int mg = 0, eg = 0;   // from White's perspective
    int phase = 0;

    U64 occ = pos.pieces();
    U64 kingZone[2];
    int kingUnits[2] = {0, 0};
    for (int c = 0; c < 2; ++c) {
        int ks = pos.king_sq(Color(c));
        kingZone[c] = KingAttacks[ks] | BB::square_bb(ks);
    }

    static const int UNIT_W[6] = { 0, 2, 2, 3, 5, 0 };

    for (int sq = 0; sq < 64; ++sq) {
        Piece p = pos.piece_on(sq);
        if (p == NO_PIECE) continue;
        const PieceType pt = ptype_of(p);
        const Color c = color_of(p);
        const int idx = (c == WHITE) ? (sq ^ 56) : sq;
        const int sign = (c == WHITE) ? 1 : -1;

        mg += sign * (MG_VALUE[pt] + PST[pt]->mg[idx]);
        eg += sign * (EG_VALUE[pt] + PST[pt]->eg[idx]);
        phase += PHASE_VALUE[pt];

        // mobility + attacks on the enemy king zone (minor and major pieces)
        if (pt >= KNIGHT && pt <= QUEEN) {
            U64 att = attacks_bb(pt, sq, occ);
            int mobCount = BB::popcnt(att & ~pos.pieces(c));
            mg += sign * MOBILITY[pt].mg * mobCount;
            eg += sign * MOBILITY[pt].eg * mobCount;
            kingUnits[c ^ 1] += UNIT_W[pt] * BB::popcnt(att & kingZone[c ^ 1]);

            if (pt == ROOK) {
                // open / semi-open files
                int f = file_of(sq);
                U64 fp = file_bb(f) & pos.pieces(PAWN);
                bool own = file_bb(f) & pos.pieces(c, PAWN);
                if (!fp)      { mg += sign * ROOK_OPEN.mg; eg += sign * ROOK_OPEN.eg; }
                else if (!own) { mg += sign * ROOK_SEMI.mg; eg += sign * ROOK_SEMI.eg; }
                // rook on 7th rank
                if (relative_rank(c, sq) == 6) { mg += sign * ROOK_7TH.mg; eg += sign * ROOK_7TH.eg; }
            } else if (pt == KNIGHT) {
                // outpost: ranks 3-5 (relative), not attackable by enemy pawns
                int rr = relative_rank(c, sq);
                if (rr >= 3 && rr <= 5) {
                    U64 enemyRelevant = pos.pieces(~c, PAWN) &
                                        adjacent_files_bb(file_of(sq)) &
                                        forward_ranks_bb(c, rank_of(sq));
                    if (!enemyRelevant) {
                        int bonus = (PawnAttacks[c][sq] & pos.pieces(c, PAWN)) ? 2 : 1;
                        mg += sign * OUTPOST.mg * bonus;
                        eg += sign * OUTPOST.eg * bonus;
                    }
                }
            }
        }
    }

    // bishop pair
    if (pos.count(W_BISHOP) >= 2) { mg += BISHOP_PAIR.mg; eg += BISHOP_PAIR.eg; }
    if (pos.count(B_BISHOP) >= 2) { mg -= BISHOP_PAIR.mg; eg -= BISHOP_PAIR.eg; }

    // pawn structure (cached)
    PawnEntry pe = eval_pawns(pos);
    mg += pe.mg; eg += pe.eg;

    // king shelter (middlegame only, applied via mg half)
    mg += king_shelter<WHITE>(pos);
    mg -= king_shelter<BLACK>(pos);

    // king safety via attack units (mg only)
    mg -= DangerTable[std::min(63, kingUnits[WHITE])];
    mg += DangerTable[std::min(63, kingUnits[BLACK])];

    if (phase > 24) phase = 24;
    Value v = (mg * phase + eg * (24 - phase)) / 24;

    // endgame mop-up bonus
    v += mop_up_bonus<Traced>(pos, phase, os);

    // drawish-endgame scaling
    if (v > 0)  v = v * scale_factor(pos, WHITE) / 128;
    if (v < 0)  v = v * scale_factor(pos, BLACK) / 128;

    v = (pos.side_to_move() == WHITE) ? v : -v;
    v += TEMPO;

    if (Traced && os) {
        *os << "phase: " << phase << "\n";
        *os << "mg: " << mg << " eg: " << eg << "\n";
        *os << "pawnStruct: " << pe.mg << " / " << pe.eg << "\n";
        *os << "kingUnits W/B: " << kingUnits[WHITE] << " / " << kingUnits[BLACK] << "\n";
        *os << "total (stm): " << v << "\n";
    }
    return v > VALUE_MATE_IN_MAX_PLY ? VALUE_MATE_IN_MAX_PLY
         : v < -VALUE_MATE_IN_MAX_PLY ? -VALUE_MATE_IN_MAX_PLY : v;
}

} // anonymous namespace

Value evaluate(const Position& pos) {
    init_danger_table();
    return evaluate_impl<false>(pos, nullptr);
}

/// Human-readable breakdown -> now routed over UCI ('debug trace') instead of
/// raw prints (previous behaviour collided with the protocol channel).
std::string trace(const Position& pos) {
    init_danger_table();
    std::ostringstream os;
    os << pos.pretty();
    evaluate_impl<true>(pos, &os);
    return os.str();
}

} // namespace Eval
} // namespace Veltrix
