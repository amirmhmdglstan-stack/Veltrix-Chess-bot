#!/usr/bin/env python3
"""
find_critical.py - identify critical positions in recorded games.

Reads games.jsonl (selfplay.py). For each DECISIVE game, examines the LOSER's
moves and flags positions where the position collapsed:

  swing:         drop of >= --swing cp in own eval across the move
  mate swing:    crossing into a forced-mate-against (eval < -90000 scale)
  WDL flip:      eval crossing a win/draw band boundary (|eval| thresholds)
  instability:   eval oscillation > 150cp in consecutive own plies (SEARCH
                 instability hint)

Every critical record contains exactly the fields the spec asks to keep:
  {game, ply, fen, move(the move played), stm, eval_before, eval_after,
   swing_cp, depth, seldepth, nodes, ms_played, phase, category_guess,
   root_hint, version}

Categories guessed here are HEURISTICS; analyze_teacher.py refines them with
a real teacher. `root_hint` is the first-pass subsystem attribution:
  TIME_MANAGEMENT (very little time spent for a big swing)
  SEARCH_HORIZON  (normal depth, immediate collapse <-> tactic one move deep)
  EVALUATION_ERROR (swing visible only via teacher; eval_before ~ 0)
  UNKNOWN

Writes critical.jsonl (one line per critical position).
"""
import argparse
import json
import os
import sys


def phase_of(fen):
    pieces = sum(1 for c in fen.split()[0] if c.isalpha() and c not in "Kk")
    ply = int(fen.split()[-1]) * 2 if fen.split()[-1].isdigit() else 40
    if ply < 30:
        return "open"
    return "end" if pieces <= 12 else "mid"


def find_in_game(rec, swing_thr):
    out = []
    if rec["result"] not in ("1-0", "0-1"):
        return out
    loser = "w" if rec["result"] == "0-1" else "b"
    moves = rec["moves"]
    prev_eval = {}
    for i, mv in enumerate(moves):
        stm = mv["stm"]
        ev = mv.get("eval")
        if ev is None:
            continue
        pe = prev_eval.get(stm)
        prev_eval[stm] = ev
        if stm != loser or pe is None:
            continue
        swing = pe - ev  # stm-relative eval; positive = our position got worse
        if abs(ev) > 90000 or abs(pe) > 90000:
            swing = max(swing, 500)
        if swing < swing_thr:
            continue
        # locate the FEN the losing move was played FROM and the reply
        fen_before = moves[i - 1]["fen"] if i >= 1 else None
        played = moves[i - 1]["move"] if i >= 1 else None
        my_depth = moves[i - 1]["depth"] if i >= 1 else 0
        ms = moves[i - 1].get("ms", 0) if i >= 1 else 0
        # category guess ------------------------------------------------------
        mate_jump = abs(pe) < 90000 and abs(ev) >= 90000
        wdl_flip = (abs(pe) < 150 <= abs(ev)) or (pe > -80 <= -ev * -1)
        unstable = (i >= 3 and abs(prev_change(moves, i, stm)) > 150)
        if ms < 60:
            root_hint = "TIME_MANAGEMENT"
        elif my_depth <= 10 and mate_jump:
            root_hint = "SEARCH_HORIZON"
        elif abs(pe) < 60:
            root_hint = "EVALUATION_ERROR"
        else:
            root_hint = "UNKNOWN"
        cat = ("TACTICAL_BLUNDER" if mate_jump or swing >= 250
               else "MISSED_TACTIC" if swing >= swing_thr * 2
               else "UNKNOWN")
        out.append({
            "game": rec["game"], "ply": i, "stm": stm,
            "fen": fen_before, "move": played,
            "eval_before": pe, "eval_after": ev, "swing_cp": swing,
            "depth": my_depth, "seldepth": moves[i - 1].get("seldepth", 0) if i >= 1 else 0,
            "nodes": moves[i - 1].get("nodes", 0) if i >= 1 else 0,
            "ms_played": ms, "phase": phase_of(fen_before or rec["moves"][0]["fen"]),
            "category_guess": cat, "root_hint": root_hint,
            "mate_swing": mate_jump, "wdl_flip": bool(wdl_flip), "unstable": unstable,
            "gresult": rec["result"], "reason": rec["reason"],
            "engine": rec.get("black" if stm == "b" else "white", {}),
        })
    return out


def prev_change(moves, i, stm):
    vals = [m["eval"] for m in moves[max(0, i - 3):i + 1]
            if m["stm"] == stm and m.get("eval") is not None]
    return (vals[-1] - vals[0]) if len(vals) >= 2 else 0


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--games", default=os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                                    "..", "..", "data", "learn", "games.jsonl"))
    ap.add_argument("--out", default="")
    ap.add_argument("--swing", type=int, default=90)
    args = ap.parse_args()
    out_path = args.out or os.path.splitext(args.games)[0].replace("games", "critical") + ".jsonl"
    n_games = n_crit = 0
    with open(args.games, encoding="utf-8") as f, \
            open(out_path, "w", encoding="utf-8") as o:
        for ln in f:
            ln = ln.strip()
            if not ln:
                continue
            n_games += 1
            for c in find_in_game(json.loads(ln), args.swing):
                o.write(json.dumps(c) + "\n")
                n_crit += 1
    print(f"[critical] {n_games} games -> {n_crit} critical positions -> {out_path}")


if __name__ == "__main__":
    main()
