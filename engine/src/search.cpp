// Veltrix 1.0 - alpha-beta search (PVS, TT, Lazy-SMP threads, Null-move, LMR,
// futility, razoring, static-null pruning, SEE pruning, LMP, singular
// extensions, aspiration windows, time management, MultiPV, strength limiting)
// Copyright (C) 2026 Veltrix Project
// SPDX-License-Identifier: GPL-3.0-or-later
#include "search.h"
#include "evaluate.h"
#include "movegen.h"
#include "tt.h"

#include <algorithm>
#include <atomic>
#include <chrono>
#include <cmath>
#include <cstdio>
#include <cstring>
#include <mutex>
#include <thread>
#include <vector>

namespace Veltrix {
namespace Search {
namespace {

// ------------------------------------------------------------------ globals --
std::mutex ioMutex;
#define SYNC_PRINT(...) do { std::lock_guard<std::mutex> lk(ioMutex); std::printf(__VA_ARGS__); std::fflush(stdout); } while (0)

std::atomic<bool> gStop{false};
std::atomic<U64> gTotalNodes{0};
std::atomic<bool> gSearching{false};

using TimePoint = std::chrono::steady_clock::time_point;

long now_ms_since(const TimePoint& start) {
    return std::chrono::duration_cast<std::chrono::milliseconds>(
               std::chrono::steady_clock::now() - start).count();
}

struct SearchStack {
    Move pv[MAX_PLY + 1];
    int pvLen = 0;
    Move killers[2] = {MOVE_NONE, MOVE_NONE};
    Value staticEval = VALUE_NONE;
    Move currentMove = MOVE_NONE;
};

struct RootMove {
    Move move = MOVE_NONE;
    Value score = -VALUE_MAX;
    Value prevScore = -VALUE_MAX;
    std::vector<Move> pv;
};

int value_of_pt(PieceType pt) {
    static const int v[7] = { 100, 320, 330, 500, 950, 10000, 0 };
    return v[pt];
}

struct SearchThread {
    Position pos;
    SearchStack stack[MAX_PLY + 16];
    std::vector<RootMove> rootMoves;
    U64 nodes = 0;
    int id = 0;
    int selDepth = 0;
    int completedDepth = 0;
    Value rootScore = -VALUE_MAX;
    Move bestMove = MOVE_NONE;
    Move ponderMove = MOVE_NONE;
    std::vector<Move> bestPV;
    int32_t history[2][64][64];
    Move counterMove[PIECE_NB][64];
    U64 rng = 0x9E3779B97F4A7C15ULL;
    std::thread th;

    void clear_state() {
        std::memset(history, 0, sizeof(history));
        for (int p = 0; p < PIECE_NB; ++p)
            for (int s = 0; s < 64; ++s) counterMove[p][s] = MOVE_NONE;
        nodes = 0;
    }
    U64 rand64() { rng ^= rng >> 12; rng ^= rng << 25; rng ^= rng >> 27; rng *= 2685821657736338717ULL; rng += 0x9E3779B97F4A7C15ULL + id; return rng; }
};

std::vector<std::unique_ptr<SearchThread>> gThreads;
SearchConfig gCfg;
SearchLimits gLim;

int LMR_TABLE[64][64];
void init_lmr() {
    static bool done = false;
    if (done) return;
    done = true;
    for (int d = 1; d < 64; ++d)
        for (int m = 1; m < 64; ++m)
            LMR_TABLE[d][m] = int(0.75 + std::log(d) * std::log(m) / 2.25);
}

// ---------------------------------------------------------------- time mgmt --
struct TimeMan {
    TimePoint start;
    long softMs = -1, hardMs = -1;
    U64 maxNodes = 0;
    int maxDepth = 0;
    bool ponderMode = false;
    bool active = false;

    long elapsed() const { return active ? now_ms_since(start) : 0; }

    void begin(const SearchLimits& lim, Color stm, long overhead) {
        start = std::chrono::steady_clock::now();
        active = true;
        softMs = hardMs = -1;
        maxNodes = lim.nodes;
        maxDepth = lim.depth;
        ponderMode = lim.ponder;
        if (lim.mate > 0 && lim.depth == 0) maxDepth = lim.mate * 2 + 2;
        if (lim.infinite || lim.ponder) return;
        if (lim.movetime > 0) {
            hardMs = std::max(1L, lim.movetime - overhead / 2);
            softMs = std::max(1L, hardMs * 2 / 3);
            return;
        }
        const long t = lim.time[stm];
        if (t <= 0) return;
        const long inc = lim.inc[stm];
        const long avail = std::max(0L, t - overhead);
        if (lim.movestogo > 0) {
            softMs = avail / lim.movestogo + inc * 3 / 4;
            softMs = std::min(softMs, avail * 4 / 5);
            hardMs = std::min(avail, softMs * 3);
        } else {
            softMs = avail / 25 + inc * 4 / 5;
            softMs = std::min(softMs, avail * 3 / 5);
            hardMs = std::min(avail, softMs * 3);
        }
        softMs = std::max(1L, softMs);
        hardMs = std::max(2L, hardMs);
    }
};

TimeMan gTime;

inline void bump_nodes_and_check(SearchThread& th) {
    th.nodes++;
    if ((th.nodes & 2047) == 0) {
        gTotalNodes.fetch_add(2048 + (th.nodes & 2047) * 0, std::memory_order_relaxed);
        if (gTime.hardMs >= 0 && !gTime.ponderMode && gTime.elapsed() >= gTime.hardMs)
            gStop = true;
        if (gTime.maxNodes && gTotalNodes.load(std::memory_order_relaxed) >= gTime.maxNodes)
            gStop = true;
    }
}
inline bool stopped() { return gStop.load(std::memory_order_relaxed); }
inline void flush_nodes(SearchThread& th) {
    U64 rem = th.nodes & 2047;
    if (rem) gTotalNodes.fetch_add(rem, std::memory_order_relaxed);
}

void update_pv(SearchStack* ss, Move m) {
    ss->pv[0] = m;
    SearchStack* next = ss + 1;
    for (int i = 0; i < next->pvLen; ++i) ss->pv[i + 1] = next->pv[i];
    ss->pvLen = next->pvLen + 1;
}

void update_history(SearchThread& th, Color stm, Move m, int bonus) {
    int32_t& h = th.history[stm][from_sq(m)][to_sq(m)];
    int clamped = std::max(-16384, std::min(16384, bonus));
    h += clamped - h * std::abs(clamped) / 16384;
}

std::string pv_string(Position pos, const Move* pv, int n) {
    std::string out;
    for (int i = 0; i < n; ++i) {
        if (i) out += ' ';
        out += move_to_str(pv[i]);
        // validate before executing so a corrupt PV never corrupts the print
        Move legal = move_from_uci(pos, move_to_str(pv[i]));
        if (legal != pv[i]) break;
        pos.do_move(pv[i]);
    }
    return out;
}

std::string score_str(Value v) {
    char buf[32];
    if (v >= VALUE_MATE_IN_MAX_PLY)
        std::snprintf(buf, sizeof(buf), "mate %d", (VALUE_MATE - v + 1) / 2);
    else if (v <= -VALUE_MATE_IN_MAX_PLY)
        std::snprintf(buf, sizeof(buf), "mate %d", -(VALUE_MATE + v + 1) / 2);
    else
        std::snprintf(buf, sizeof(buf), "cp %d", v);
    return buf;
}

int hashfull() {
    int used = 0;
    for (int i = 0; i < 250; ++i) {
        bool hit;
        TTEntry* e = gTT.probe(U64(i) * 0x9E3779B97F4A7C15ULL, hit);
        (void)hit;
        if (e->depth != 0) ++used;
    }
    return used * 4;
}

// --------------------------------------------------------------- move picker --
constexpr int SCORE_TT      = 100'000'000;
constexpr int SCORE_GOODCAP = 8'000'000;
constexpr int SCORE_PROMO   = 7'500'000;
constexpr int SCORE_KILLER1 = 6'100'000;
constexpr int SCORE_KILLER2 = 6'000'000;
constexpr int SCORE_COUNTER = 5'900'000;
constexpr int SCORE_BADCAP  = -1'000'000;

void score_moves(SearchThread& th, const Position& pos, ExtMove* moves, int n,
                 Move ttMove, SearchStack* ss, bool capturesOnly) {
    const Color stm = pos.side_to_move();
    Move counter = MOVE_NONE;
    if (ss > th.stack) {
        Move prevMove = (ss - 1)->currentMove;
        if (prevMove != MOVE_NONE && prevMove != MOVE_NULL) {
            Piece prevPc = pos.piece_on(to_sq(prevMove));
            if (prevPc != NO_PIECE) counter = th.counterMove[prevPc][to_sq(prevMove)];
        }
    }
    for (int i = 0; i < n; ++i) {
        Move m = moves[i].move;
        if (m == ttMove) { moves[i].score = SCORE_TT; continue; }
        const bool isCap = pos.is_capture(m);
        if (is_promotion(m)) {
            int bonus = promo_type(m) == QUEEN ? 2000 : (promo_type(m) == KNIGHT ? 100 : -4000);
            moves[i].score = SCORE_PROMO + bonus + (isCap ? 5000 : 0);
            continue;
        }
        if (isCap) {
            Piece victim = pos.piece_on(to_sq(m));
            int vVal = (flag_of(m) == MF_ENPASSANT) ? 100 : value_of_pt(ptype_of(victim));
            int aVal = value_of_pt(ptype_of(pos.piece_on(from_sq(m))));
            bool good = pos.see_ge(m, 0);
            moves[i].score = (good ? SCORE_GOODCAP : SCORE_BADCAP) + vVal * 64 - aVal;
            continue;
        }
        if (capturesOnly) { moves[i].score = -100'000'000; continue; }
        if (ss && m == ss->killers[0]) { moves[i].score = SCORE_KILLER1; continue; }
        if (ss && m == ss->killers[1]) { moves[i].score = SCORE_KILLER2; continue; }
        if (m == counter) { moves[i].score = SCORE_COUNTER; continue; }
        moves[i].score = th.history[stm][from_sq(m)][to_sq(m)];
    }
}

Move pick_move(ExtMove* moves, int n, int idx) {
    int best = idx;
    for (int i = idx + 1; i < n; ++i)
        if (moves[i].score > moves[best].score) best = i;
    std::swap(moves[idx], moves[best]);
    return moves[idx].move;
}

// ------------------------------------------------------------------ qsearch --
Value qsearch(SearchThread& th, SearchStack* ss, Value alpha, Value beta, int depth) {
    Position& pos = th.pos;
    bump_nodes_and_check(th);
    const int ply = int(ss - th.stack);
    if (ply > th.selDepth) th.selDepth = ply;
    if (stopped()) return alpha;
    if (ss->pvLen > 0) ss->pvLen = 0;
    if (ply >= MAX_PLY) return Eval::evaluate(pos);

    if (pos.is_repetition() || pos.insufficient_material() ||
        (pos.rule50() >= 100 && !pos.in_check()))
        return VALUE_DRAW;

    const bool inCheck = pos.in_check();
    const U64 key = pos.key();

    bool ttHit;
    TTEntry* tte = gTT.probe(key, ttHit);
    Move ttMove = MOVE_NONE;
    Value ttValue = VALUE_NONE;
    if (ttHit) {
        ttMove = static_cast<Move>(tte->move);
        ttValue = from_tt_score(tte->score, ply);
        Bound b = Bound(tte->bound & TT_BOUND_MASK);
        if ((b == BOUND_EXACT) || (b == BOUND_LOWER && ttValue >= beta) ||
            (b == BOUND_UPPER && ttValue <= alpha))
            return ttValue;
    }

    Value bestValue;
    Value rawStatic = VALUE_NONE;
    if (!inCheck) {
        Value staticEval;
        if (ttHit && Value(tte->eval) != VALUE_NONE)
            staticEval = Value(tte->eval);
        else
            staticEval = Eval::evaluate(pos);
        rawStatic = staticEval;
        if (staticEval >= beta) {
            gTT.store(key, MOVE_NONE, to_tt_score(staticEval, ply), I16(staticEval), 0, BOUND_LOWER);
            return staticEval;
        }
        bestValue = staticEval;
        if (staticEval > alpha) alpha = staticEval;
    } else {
        bestValue = mated_in(ply);
    }

    ExtMove moves[MAX_MOVES];
    int n;
    if (inCheck) n = generate_legal(pos, moves);
    else {
        ExtMove* end = generate_pseudo_captures(pos, moves);
        n = int(end - moves);
    }
    score_moves(th, pos, moves, n, ttMove, ss, !inCheck);

    const Value alphaOrig = alpha;
    Move bestMove = MOVE_NONE;
    const Value futilityBase = inCheck ? 0 : bestValue + 135;

    for (int i = 0; i < n; ++i) {
        Move m = pick_move(moves, n, i);
        if (m == MOVE_NONE) continue;
        if (!inCheck) {
            // losing captures are skipped once the stand-pat bound exists
            if (!pos.see_ge(m, 0)) continue;
            Piece victim = pos.piece_on(to_sq(m));
            int vVal = (flag_of(m) == MF_ENPASSANT) ? 100
                                                    : (victim == NO_PIECE ? 0 : value_of_pt(ptype_of(victim)));
            if (is_promotion(m) && promo_type(m) == QUEEN) vVal += 850;
            if (futilityBase + vVal <= alpha) continue;  // delta pruning
        }
        ss->currentMove = m;
        pos.do_move(m);
        if (pos.attacked_by(pos.king_sq(~pos.side_to_move()), pos.side_to_move())) {
            pos.undo_move(m);
            continue;
        }
        Value v = -qsearch(th, ss + 1, -beta, -alpha, depth - 1);
        pos.undo_move(m);
        if (stopped()) return alpha;

        if (v > bestValue) {
            bestValue = v;
            bestMove = m;
            if (v > alpha) {
                alpha = v;
                if (alpha >= beta) break;
            }
        }
    }

    if (inCheck && bestMove == MOVE_NONE) return mated_in(ply);

    Bound bnd = (bestValue >= beta) ? BOUND_LOWER : (bestValue > alphaOrig ? BOUND_EXACT : BOUND_UPPER);
    gTT.store(key, bestMove, to_tt_score(bestValue, ply),
              I16(rawStatic == VALUE_NONE ? Eval::evaluate(pos) : rawStatic), 0, bnd);
    return bestValue;
}

// ------------------------------------------------------------------ negamax --
Value negamax(SearchThread& th, SearchStack* ss, Value alpha, Value beta, int depth,
              bool pvNode, bool cutNode, Move excludedMove) {
    Position& pos = th.pos;
    bump_nodes_and_check(th);
    const int ply = int(ss - th.stack);
    if (ply > th.selDepth) th.selDepth = ply;
    (ss + 1)->pvLen = 0;
    ss->currentMove = excludedMove;

    if (depth <= 0) return qsearch(th, ss, alpha, beta, 0);
    if (stopped()) return alpha;
    if (ply >= MAX_PLY) return Eval::evaluate(pos);

    if (ply > 0) {
        if (pos.is_repetition() || pos.insufficient_material()) return VALUE_DRAW;
        if (pos.rule50() >= 100 && (!pos.in_check() || has_legal_move(pos))) return VALUE_DRAW;
        alpha = std::max(alpha, mated_in(ply));
        beta = std::min(beta, mate_in(ply + 1));
        if (alpha >= beta) return alpha;
    }

    const bool inCheck = pos.in_check();
    const Color us = pos.side_to_move();
    const U64 key = pos.key();

    bool ttHit;
    TTEntry* tte = gTT.probe(key, ttHit);
    Move ttMove = MOVE_NONE;
    Value ttValue = VALUE_NONE;
    int ttDepth = 0;
    Bound ttBound = BOUND_NONE;
    if (ttHit) {
        ttMove = static_cast<Move>(tte->move);
        ttValue = from_tt_score(tte->score, ply);
        ttDepth = int(tte->depth);
        ttBound = Bound(tte->bound & TT_BOUND_MASK);
        if (!pvNode && excludedMove == MOVE_NONE && ttDepth >= depth &&
            ((ttBound == BOUND_EXACT) || (ttBound == BOUND_LOWER && ttValue >= beta) ||
             (ttBound == BOUND_UPPER && ttValue <= alpha)))
            return ttValue;
    }

    Value staticEval;
    if (inCheck) staticEval = VALUE_NONE;
    else if (ttHit && Value(tte->eval) != VALUE_NONE) staticEval = Value(tte->eval);
    else staticEval = Eval::evaluate(pos);
    ss->staticEval = staticEval;

    const bool improving = !inCheck && ply >= 2 && (ss - 2)->staticEval != VALUE_NONE &&
                           staticEval > (ss - 2)->staticEval;

    // ---- whole-node pruning (non-PV, not in check, not excluded) -------------
    if (ply > 0 && !pvNode && !inCheck && excludedMove == MOVE_NONE) {
        const Value eval = staticEval;

        // razoring
        if (depth <= 3 && eval + 240 * depth <= alpha) {
            Value v = qsearch(th, ss, alpha - 1, alpha, 0);
            if (v <= alpha) return v;
        }

        // static null (reverse futility) pruning
        int rfpMargin = 85 * depth - (improving ? 40 : 0);
        if (depth <= 8 && eval - rfpMargin >= beta && beta > -VALUE_MATE_IN_MAX_PLY &&
            eval < VALUE_MATE_IN_MAX_PLY)
            return eval - rfpMargin;

        // null-move pruning
        if (depth >= 3 && eval >= beta && beta < VALUE_MATE_IN_MAX_PLY &&
            pos.non_pawn_material(us) && (ss - 1)->currentMove != MOVE_NULL &&
            (ss - 1)->currentMove != MOVE_NONE) {
            int R = 3 + depth / 6 + std::min(3, int(eval - beta) / 220);
            R = std::min(R, depth - 1);
            ss->currentMove = MOVE_NULL;   // the child sees the null as the previous move
            pos.do_null_move();
            Value v = -negamax(th, ss + 1, -beta, -beta + 1, depth - R - 1, false, !cutNode, MOVE_NONE);
            pos.undo_null_move();
            ss->currentMove = excludedMove;   // restore frame bookkeeping
            if (stopped()) return alpha;
            if (v >= beta) {
                if (is_win(v)) v = beta;
                return v;
            }
        }
    }

    // internal iterative deepening
    if (pvNode && depth >= 5 && ttMove == MOVE_NONE) depth -= 2;

    // ---- move loop ------------------------------------------------------------
    ExtMove moves[MAX_MOVES];
    ExtMove* end = generate_pseudo(pos, moves);
    const int n = int(end - moves);
    score_moves(th, pos, moves, n, ttMove, ss, false);

    const Value alphaOrig = alpha;
    Value bestValue = mated_in(ply);
    Move bestMove = MOVE_NONE;
    int moveCount = 0;
    Move quietsTried[64];
    int quietCount = 0;

    for (int i = 0; i < n; ++i) {
        Move m = pick_move(moves, n, i);
        if (m == excludedMove) continue;
        const bool isCap = pos.is_capture(m);
        const bool isQuiet = !isCap && !is_promotion(m);
        ++moveCount;

        // SEE outcomes must be computed in the pre-move position
        bool seeQuietOK = true, seeCapOK = true;
        if (ply > 0) {
            if (isQuiet && depth <= 6) seeQuietOK = pos.see_ge(m, -35 * depth);
            if (isCap && depth <= 7) seeCapOK = pos.see_ge(m, -95 * depth);
        }

        // -------- singular extensions --------------------------------------
        int extension = 0;
        if (ply > 0 && depth >= 7 && m == ttMove && ttHit && excludedMove == MOVE_NONE &&
            ttDepth >= depth - 3 && ttBound != BOUND_UPPER && ttBound != BOUND_NONE &&
            !is_win(ttValue) && !is_loss(ttValue)) {
            Value singularBeta = std::max(ttValue - 2 * depth, mated_in(ply));
            int singularDepth = std::max(1, depth / 2);
            Value v = negamax(th, ss, singularBeta - 1, singularBeta, singularDepth,
                              false, true, m);
            ss->currentMove = excludedMove;  // restore this frame's bookkeeping
            if (stopped()) return alpha;
            if (v < singularBeta) extension = 1;
            else if (singularBeta >= beta) return singularBeta;  // multi-cut
        }

        ss->currentMove = m;
        pos.do_move(m);
        // pseudo-legal move generation: drop moves that leave our king in check
        if (pos.attacked_by(pos.king_sq(~pos.side_to_move()), pos.side_to_move())) {
            pos.undo_move(m);
            --moveCount;  // only legal moves count toward move-count heuristics
            ss->currentMove = excludedMove;
            continue;
        }
        // -------- pre-search pruning (must be check-aware) -------------------
        if (ply > 0 && bestMove != MOVE_NONE && bestValue > VALUE_MATED_IN_MAX_PLY) {
            if (isQuiet) {
                const bool givesCheckNow = pos.in_check();
                int lmpThresh = improving ? (4 + depth * depth) : (3 + depth * depth) / 2;
                if (!inCheck && !givesCheckNow && depth <= 6 && moveCount > lmpThresh) {
                    pos.undo_move(m);
                    ss->currentMove = excludedMove;
                    break;
                }
                if (!inCheck && !givesCheckNow && depth <= 7 &&
                    alpha < VALUE_MATE_IN_MAX_PLY && staticEval != VALUE_NONE &&
                    staticEval + 135 * depth <= alpha) {
                    pos.undo_move(m);
                    ss->currentMove = excludedMove;
                    continue;
                }
                if (!givesCheckNow && depth <= 6 && !seeQuietOK) {
                    pos.undo_move(m);
                    ss->currentMove = excludedMove;
                    continue;
                }
            } else {
                if (depth <= 7 && !seeCapOK) {
                    pos.undo_move(m);
                    ss->currentMove = excludedMove;
                    continue;
                }
            }
        }
        const bool givesCheck = pos.in_check();
        const int newDepth = std::max(0, depth - 1 + extension);

        Value value;
        if (moveCount == 1) {
            value = -negamax(th, ss + 1, -beta, -alpha, newDepth, pvNode, false, MOVE_NONE);
        } else {
            int r = 0;
            if (depth >= 3 && moveCount >= 2 && isQuiet && !inCheck && !givesCheck) {
                r = LMR_TABLE[std::min(63, depth)][std::min(63, moveCount)];
                if (!improving) ++r;
                if (pvNode) --r;
                if (m == ss->killers[0] || m == ss->killers[1]) --r;
                r = std::max(0, std::min(newDepth, r));
            }
            value = -negamax(th, ss + 1, -alpha - 1, -alpha, newDepth - r, false, true, MOVE_NONE);
            if (!stopped() && r > 0 && value > alpha)
                value = -negamax(th, ss + 1, -alpha - 1, -alpha, newDepth, false, !cutNode, MOVE_NONE);
            if (!stopped() && pvNode && value > alpha && value < beta)
                value = -negamax(th, ss + 1, -beta, -alpha, newDepth, true, false, MOVE_NONE);
        }
        pos.undo_move(m);
        ss->currentMove = excludedMove;   // restore
        if (stopped()) return alpha;

        if (value > bestValue) {
            bestValue = value;
            bestMove = m;
            if (value > alpha) {
                if (value >= beta) {
                    if (isQuiet) {
                        if (m != ss->killers[0]) { ss->killers[1] = ss->killers[0]; ss->killers[0] = m; }
                        int bonus = std::min(2000, depth * depth + depth);
                        update_history(th, us, m, bonus);
                        for (int q = 0; q < quietCount; ++q)
                            update_history(th, us, quietsTried[q], -bonus);
                        Move prevMove = (ss - 1)->currentMove;
                        if (prevMove != MOVE_NONE && prevMove != MOVE_NULL) {
                            Piece prevPc = pos.piece_on(to_sq(prevMove));
                            if (prevPc != NO_PIECE)
                                th.counterMove[prevPc][to_sq(prevMove)] = m;
                        }
                    }
                    break;
                }
                alpha = value;
                update_pv(ss, m);
            } else if (isQuiet && quietCount < 64) {
                quietsTried[quietCount++] = m;
            }
        } else if (isQuiet && quietCount < 64) {
            quietsTried[quietCount++] = m;
        }
    }

    if (moveCount == 0) {
        if (excludedMove != MOVE_NONE) return alpha;
        if (inCheck) return mated_in(ply);
        return VALUE_DRAW;
    }

    if (excludedMove == MOVE_NONE) {
        Bound bnd;
        if (bestValue >= beta) bnd = BOUND_LOWER;
        else if (bestValue > alphaOrig) bnd = BOUND_EXACT;
        else bnd = BOUND_UPPER;
        Value evalOut = (staticEval == VALUE_NONE) ? Eval::evaluate(pos) : staticEval;
        gTT.store(key, bestMove, to_tt_score(bestValue, ply), I16(evalOut),
                  std::max(0, depth - (inCheck && bestValue < alphaOrig ? 1 : 0)), bnd);
    }
    return bestValue;
}

// ------------------------------------------------------------- root search ----
Value root_search(SearchThread& th, int depth, Value alpha, Value beta, int pvIdx) {
    Position& pos = th.pos;
    SearchStack* ss = th.stack;
    (ss + 1)->pvLen = 0;
    ss->currentMove = MOVE_NONE;

    Value bestValue = -VALUE_MAX;
    int searched = 0;

    for (size_t i = size_t(pvIdx); i < th.rootMoves.size(); ++i) {
        Move m = th.rootMoves[i].move;
        ss->currentMove = m;
        pos.do_move(m);
        Value value;
        if (searched == 0) {
            value = -negamax(th, ss + 1, -beta, -alpha, depth - 1, true, false, MOVE_NONE);
        } else {
            value = -negamax(th, ss + 1, -alpha - 1, -alpha, depth - 1, false, true, MOVE_NONE);
            if (!stopped() && value > alpha && value < beta)
                value = -negamax(th, ss + 1, -beta, -alpha, depth - 1, true, false, MOVE_NONE);
        }
        pos.undo_move(m);
        ++searched;
        if (stopped()) break;

        th.rootMoves[i].score = value;
        if (value > bestValue) {
            bestValue = value;
            if (value > alpha) {
                alpha = value;
                th.rootMoves[i].pv.clear();
                th.rootMoves[i].pv.push_back(m);
                for (int j = 0; j < th.stack[1].pvLen; ++j)
                    th.rootMoves[i].pv.push_back(th.stack[1].pv[j]);
            }
        }
    }

    if (searched > 0)
        std::stable_sort(th.rootMoves.begin(), th.rootMoves.end(),
                         [](const RootMove& a, const RootMove& b) { return a.score > b.score; });
    return bestValue == -VALUE_MAX ? mated_in(0) : bestValue;
}

// print UCI info for completed iteration `depth` (main thread only)
void print_info(SearchThread& th, int depth, int multiPVCount) {
    const long t = std::max(1L, gTime.elapsed());
    const U64 nodes = gTotalNodes.load(std::memory_order_relaxed) + (th.nodes & 2047);
    const U64 nps = nodes * 1000 / U64(t);
    const int hf = hashfull();
    for (int k = 0; k < multiPVCount && k < int(th.rootMoves.size()); ++k) {
        const RootMove& rm = th.rootMoves[k];
        std::string pv = pv_string(th.pos, rm.pv.data(), int(rm.pv.size()));
        SYNC_PRINT("info depth %d seldepth %d multipv %d score %s nodes %llu nps %llu "
                   "hashfull %d time %ld pv %s\n",
                   depth, th.selDepth, k + 1, score_str(rm.score).c_str(),
                   (unsigned long long)nodes, (unsigned long long)nps, hf, t, pv.c_str());
    }
}

// --------------------------------------------------------- iterative loop ----
void id_loop(SearchThread& th, bool mainThread) {
    Position& pos = th.pos;
    ExtMove buf[MAX_MOVES];
    int n = generate_legal(pos, buf);

    th.rootMoves.clear();
    if (!gLim.searchmoves.empty()) {
        for (Move m : gLim.searchmoves) {
            for (int i = 0; i < n; ++i)
                if (buf[i].move == m) { th.rootMoves.push_back(RootMove{m}); break; }
        }
    } else {
        for (int i = 0; i < n; ++i) th.rootMoves.push_back(RootMove{buf[i].move});
    }
    if (th.rootMoves.empty()) { return; }

    // seed ordering (MVV-LVA style via score_moves at a fake stack)
    {
        ExtMove sm[MAX_MOVES];
        for (size_t i = 0; i < th.rootMoves.size(); ++i) sm[i] = ExtMove{th.rootMoves[i].move, 0};
        score_moves(th, pos, sm, int(th.rootMoves.size()), MOVE_NONE, th.stack, false);
        for (size_t i = 0; i < th.rootMoves.size(); ++i) th.rootMoves[i].score = sm[i].score;
        std::stable_sort(th.rootMoves.begin(), th.rootMoves.end(),
                         [](const RootMove& a, const RootMove& b) { return a.score > b.score; });
        for (auto& rm : th.rootMoves) rm.score = -VALUE_MAX;
    }

    th.bestMove = th.rootMoves[0].move;
    th.bestPV.clear();
    th.bestPV.push_back(th.bestMove);

    int maxDepth = gTime.maxDepth ? gTime.maxDepth : (MAX_PLY - 8);
    if (gCfg.limitStrength) {
        maxDepth = std::min(maxDepth, 3 + std::max(0, (gCfg.elo - 1350)) / 200);
    }
    if (!mainThread) maxDepth = MAX_PLY - 8;  // helpers just fill TT until stopped

    Value prevScore = -VALUE_MAX;
    Move prevBest = MOVE_NONE;
    int bestUnchanged = 0;

    for (int depth = 1; depth <= maxDepth; ++depth) {
        th.selDepth = 0;
        for (auto& rm : th.rootMoves) { rm.prevScore = rm.score; rm.pv.clear(); }

        const int multiPV = std::min(gCfg.multiPV, int(th.rootMoves.size()));
        Value lastBest = VALUE_NONE;

        for (int pvIdx = 0; pvIdx < multiPV; ++pvIdx) {
            Value alpha = -VALUE_MAX, beta = VALUE_MAX;
            if (multiPV == 1 && depth >= 5 && prevScore != -VALUE_MAX) {
                alpha = std::max(prevScore - 12, -VALUE_MAX);
                beta = std::min(prevScore + 12, VALUE_MAX);
            }
            int delta = 16;
            for (;;) {
                Value v = root_search(th, depth, alpha, beta, pvIdx);
                if (stopped()) break;
                if (pvIdx == 0) lastBest = v;
                if (v <= alpha) {
                    beta = (alpha + beta) / 2;
                    alpha = std::max(v - delta, -VALUE_MAX);
                    delta += delta / 2 + 1;
                    continue;
                }
                if (v >= beta) {
                    beta = std::min(v + delta, VALUE_MAX);
                    delta += delta / 2 + 1;
                    continue;
                }
                break;
            }
            if (stopped()) break;
        }
        if (stopped()) break;

        th.completedDepth = depth;
        th.rootScore = th.rootMoves[0].score;
        th.bestMove = th.rootMoves[0].move;
        th.bestPV = th.rootMoves[0].pv;
        th.ponderMove = th.bestPV.size() > 1 ? th.bestPV[1] : MOVE_NONE;

        if (mainThread && gCfg.showInfo) print_info(th, depth, multiPV);

        // clock-based soft stop with stability adjustment
        if (mainThread && gTime.softMs >= 0 && !gTime.ponderMode) {
            if (th.bestMove == prevBest) ++bestUnchanged; else bestUnchanged = 0;
            prevBest = th.bestMove;
            double factor = 1.0;
            if (bestUnchanged >= 2) factor = 0.82;
            else if (bestUnchanged == 0 && prevScore != -VALUE_MAX &&
                     th.rootScore < prevScore - 25)
                factor = 1.2;
            if (gTime.elapsed() >= long(gTime.softMs * factor)) gStop = true;
        }
        prevScore = th.rootScore;

        if (mainThread && gTime.maxDepth && depth >= gTime.maxDepth) { gStop = true; break; }
        (void)lastBest;
    }
    if (mainThread) gStop = true;
}

// choose final result across threads (Lazy SMP voting)
void choose_best_and_print(SearchThread& main) {
    SearchThread* best = &main;
    for (auto& ptr : gThreads) {
        if (ptr->id == 0) continue;
        if (ptr->completedDepth > best->completedDepth + 1 &&
            ptr->rootScore > best->rootScore - 45) {
            best = ptr.get();
        }
    }

    // strength limiting: choose a suboptimal move from the main thread's root
    if (gCfg.limitStrength && !main.rootMoves.empty()) {
        std::stable_sort(main.rootMoves.begin(), main.rootMoves.end(),
                         [](const RootMove& a, const RootMove& b) { return a.score > b.score; });
        const Value best = main.rootMoves[0].score;
        const int budget = std::max(15, (2850 - gCfg.elo) / 4);   // cp of slack
        std::vector<const RootMove*> cands;
        for (const auto& rm : main.rootMoves) {
            if (rm.move != MOVE_NONE && rm.score >= best - budget && rm.score > mated_in(0))
                cands.push_back(&rm);
        }
        if (!cands.empty()) {
            const RootMove* pick = cands[main.rand64() % cands.size()];
            SYNC_PRINT("bestmove %s%s\n", move_to_str(pick->move).c_str(),
                       pick->pv.size() > 1 ? (std::string(" ponder ") + move_to_str(pick->pv[1])).c_str() : "");
            return;
        }
    }

    if (best->bestMove == MOVE_NONE) {
        SYNC_PRINT("bestmove 0000\n");
        return;
    }
    std::string extra;
    if (best->ponderMove != MOVE_NONE) extra = " ponder " + move_to_str(best->ponderMove);
    SYNC_PRINT("bestmove %s%s\n", move_to_str(best->bestMove).c_str(), extra.c_str());
}

void run_thread(SearchThread* t, bool mainThread) {
    id_loop(*t, mainThread);
    flush_nodes(*t);
}

} // anonymous namespace

// ------------------------------------------------------------------ API -------
void init(size_t hashMB, int threads) {
    init_lmr();
    gCfg.hashMB = hashMB;
    gCfg.threads = std::max(1, std::min(64, threads));
    gTT.resize(hashMB);
    gThreads.clear();
    for (int i = 0; i < gCfg.threads; ++i) {
        auto t = std::make_unique<SearchThread>();
        t->id = i;
        t->clear_state();
        gThreads.push_back(std::move(t));
    }
}

void configure(const SearchConfig& cfg) {
    bool rebuild = cfg.threads != gCfg.threads || cfg.hashMB != gCfg.hashMB;
    gCfg = cfg;
    if (gThreads.empty() || rebuild) init(cfg.hashMB, cfg.threads);
}

SearchConfig& config() { return gCfg; }

void new_game() {
    gTT.clear();  // full clear: games should be independent and reproducible
    for (auto& t : gThreads) t->clear_state();
}

void start(const Position& rootPos, const SearchLimits& lim) {
    if (gSearching.load()) return;
    gLim = lim;
    // strength limiting short-circuits pondering limits
    gTime.begin(lim, rootPos.side_to_move(), gCfg.moveOverhead);

    for (auto& t : gThreads) {
        t->pos = rootPos;
        t->nodes = 0;
        t->completedDepth = 0;
        t->selDepth = 0;
        t->rootScore = -VALUE_MAX;
        t->bestMove = MOVE_NONE;
        t->ponderMove = MOVE_NONE;
        t->bestPV.clear();
    }

    gStop = false;
    gTotalNodes = 0;
    gSearching = true;

    std::thread driver([&rootPos]() {
        // helpers
        for (size_t i = 1; i < gThreads.size(); ++i)
            gThreads[i]->th = std::thread(run_thread, gThreads[i].get(), false);
        // main
        run_thread(gThreads[0].get(), true);
        gStop = true;
        for (size_t i = 1; i < gThreads.size(); ++i)
            if (gThreads[i]->th.joinable()) gThreads[i]->th.join();
        choose_best_and_print(*gThreads[0]);
        gSearching = false;
    });
    driver.detach();
    (void)rootPos;
}

void stop_and_join() {
    gStop = true;
    while (gSearching.load()) std::this_thread::sleep_for(std::chrono::milliseconds(1));
}

bool searching() { return gSearching.load(); }

void ponderhit() {
    if (!gSearching.load()) return;
    // switch from ponder mode to clocked search using the original clock info
    gTime.ponderMode = false;
    long elapsed = gTime.elapsed();
    SearchLimits lim = gLim;
    Color stm = gThreads[0]->pos.side_to_move();
    lim.ponder = false;
    if (lim.time[stm] > 0) lim.time[stm] = std::max(1L, lim.time[stm] - elapsed);
    TimeMan fresh;
    fresh.begin(lim, stm, gCfg.moveOverhead);
    fresh.ponderMode = false;
    fresh.start = std::chrono::steady_clock::now();
    gTime = fresh;
}

U64 nodes_total() { return gTotalNodes.load(std::memory_order_relaxed); }

Move think_sync(const Position& rootPos, const SearchLimits& lim, Move* ponderOut) {
    start(rootPos, lim);
    while (gSearching.load()) std::this_thread::sleep_for(std::chrono::milliseconds(2));
    Move bm = gThreads[0]->bestMove;
    if (ponderOut) *ponderOut = gThreads[0]->ponderMove;
    return bm;
}

U64 last_completed_depth_nodes() { return gTotalNodes.load(); }

} // namespace Search
} // namespace Veltrix
