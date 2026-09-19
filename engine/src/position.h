// Veltrix 1.0 - chess position representation
// Copyright (C) 2026 Veltrix Project
// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once

#include "types.h"
#include "bitboard.h"
#include <string>
#include <vector>

namespace Veltrix {

constexpr int MAX_GAME_PLIES = 2100;

struct StateInfo {
    U64 key = 0;
    U64 pawnKey = 0;
    int halfmoveClock = 0;
    int fullmoveNumber = 1;
    int epSquare = SQ_NONE;
    int castlingRights = NO_CASTLING;
    Piece captured = NO_PIECE;
    U64 checkersBB = 0;
};

class Position {
public:
    Position() { set_startpos(); }

    // ---------------------------------------------------------------- setup
    void set_startpos();
    bool set_fen(const std::string& fen);
    std::string fen() const;

    // -------------------------------------------------------------- queries
    Color side_to_move() const { return sideToMove; }
    int game_ply() const { return stIdx; }

    U64 pieces() const { return byColorBB[WHITE] | byColorBB[BLACK]; }
    U64 pieces(Color c) const { return byColorBB[c]; }
    U64 pieces(Piece p) const { return byPieceBB[p]; }
    U64 pieces(Color c, PieceType pt) const { return byPieceBB[make_piece(c, pt)]; }
    U64 pieces(PieceType pt) const { return byPieceBB[make_piece(WHITE, pt)] | byPieceBB[make_piece(BLACK, pt)]; }
    template <typename... Ts> U64 pieces(Color c, PieceType pt, Ts... pts) const {
        return pieces(c, pt) | pieces(c, pts...);
    }
    Piece piece_on(int sq) const { return board[sq]; }
    bool empty(int sq) const { return board[sq] == NO_PIECE; }
    int count(Piece p) const { return pieceCount[p]; }
    int count(Color c, PieceType pt) const { return pieceCount[make_piece(c, pt)]; }
    int king_sq(Color c) const { return kingSquare[c]; }

    U64 attackers_to(int sq) const { return attackers_to(sq, pieces()); }
    U64 attackers_to(int sq, U64 occupied) const;
    bool attacked_by(int sq, Color c) const { return (attackers_to(sq) & byColorBB[c]) != 0; }
    bool attacked_by(int sq, Color c, U64 occupied) const {
        return (attackers_to(sq, occupied) & byColorBB[c]) != 0;
    }
    bool in_check() const { return st().checkersBB != 0; }
    U64 checkers() const { return st().checkersBB; }

    const StateInfo& st() const { return stateStack[stIdx]; }
    U64 key() const { return st().key; }
    U64 pawn_key() const { return st().pawnKey; }
    int rule50() const { return st().halfmoveClock; }
    int castling_rights() const { return st().castlingRights; }
    int ep_square() const { return st().epSquare; }
    bool can_castle(CastlingRight cr) const { return (st().castlingRights & cr) != 0; }

    // ------------------------------------------------------------ move exec
    void do_move(Move m);
    void undo_move(Move m);
    void do_null_move();
    void undo_null_move();

    bool is_capture(Move m) const {
        return (m != MOVE_NULL && m != MOVE_NONE) &&
               (board[to_sq(m)] != NO_PIECE || flag_of(m) == MF_ENPASSANT);
    }
    bool is_capture_or_promotion(Move m) const {
        return is_capture(m) || is_promotion(m);
    }
    Piece moved_piece(Move m) const { return board[from_sq(m)]; }

    bool is_legal_move(Move m) const;   // full legality check of an arbitrary move

    // -------------------------------------------------------------- status
    bool is_repetition() const;   // 2-fold within the game (for search)
    bool is_draw(int ply) const;  // repetition, 50-move, insufficient material
    bool insufficient_material() const;
    bool see_ge(Move m, int threshold) const;
    bool non_pawn_material(Color c) const {
        return count(c, KNIGHT) + count(c, BISHOP) + count(c, ROOK) + count(c, QUEEN) > 0;
    }
    bool non_pawn_material() const { return non_pawn_material(WHITE) || non_pawn_material(BLACK); }

    // eval helpers
    U64 pinned_pieces(Color c) const;   // pieces of c absolutely pinned to their king
    Value material_value() const;       // crude material balance (for rules)



    U64 key_from_scratch() const;
    U64 pawn_key_from_scratch() const;
    bool pos_is_ok() const;

    std::string pretty() const;

private:
    template <bool Do> void do_castle_move(int kingFrom, int kingTo);

    Piece board[64];
    U64 byPieceBB[PIECE_NB];
    U64 byColorBB[COLOR_NB];
    int pieceCount[PIECE_NB];
    int kingSquare[COLOR_NB];
    Color sideToMove;
    StateInfo stateStack[MAX_GAME_PLIES + MAX_PLY + 64];
    int stIdx;

    void put_piece(Piece p, int sq);
    void remove_piece(int sq);
    void move_piece(int from, int to);
};

// Zobrist random numbers (deterministic build, fixed seed generation)
extern U64 ZobristPiece[16][64];  // rows 12..15 zero-filled sentinel guards (see position.cpp)
extern U64 ZobristSide;
extern U64 ZobristCastling[16];
extern U64 ZobristEp[8];
void init_zobrist();

// castling-rights removal mask indexed by "from/to" square
extern int CastlingMask[64];
void init_castling_masks();

const std::string STARTPOS_FEN = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1";

} // namespace Veltrix
