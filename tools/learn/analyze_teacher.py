#!/usr/bin/env python3
"""
analyze_teacher.py - teacher analysis of critical positions.

Usage model (spec compliant):
  - Stockfish (or any strong UCI engine) is ONLY a teacher/analyzer.
  - It never plays in the learner. Its output becomes (fen, eval, weight)
    training rows and explanation material for the loss report.
  - If no teacher is configured, use Veltrix itself at DEEP time as a weak
    surrogate teacher (--self-teacher). This keeps the loop runnable; rows
    are labelled src=self-teacher and weighted lower.

For each critical record:
  1. teacher best move + eval at the position
  2. teacher eval of the ACTUAL line (position after our played move)
  3. delta = t_best - t_actual (teacher-PVS gap, stm-corrected); if delta <
     --agree cp, the disagreement is minor -> record dropped from the pack
  4. category refinement from teacher best-move properties
     (check = MISSED_CHECK, capture = MISSED_CAPTURE, both visible to all
     legality already; mate = TACTICAL_BLUNDER)

Outputs:
  --losspack   jsonl rows {fen, eval, stm, result(0.5), weight, depth, src,
                           category, teacher, game, ply}
  --analysis   json lines with full teacher verdicts (for loss_report.py)
  --epd        tests/loss_regression.epd lines: fen bm <teacherbest> weight
"""
import argparse
import json
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(REPO, "gui"))
sys.path.insert(0, os.path.join(REPO, "tools"))

import chesslib                      # noqa: E402
from engine_driver import UCIEngine  # noqa: E402


def teacher_eval(e, fen, movetime):
    """(best_uci, cp_from_stm, mate, pv, depth) using teacher analysis."""
    e.send("position fen %s" % fen)
    e.send("go movetime %d" % movetime)
    lines = e.wait_for("bestmove", 120)
    best, cp, mate, pv, dep = None, 0, None, [], 0
    for ln in lines:
        if ln.startswith("info ") and " score " in ln and " pv " in ln:
            t = ln.split()
            try:
                si = t.index("score")
                if t[si + 1] == "mate":
                    m = int(t[si + 2])
                    mate = m
                    cp = 100000 - abs(m) if m >= 0 else -(100000 - abs(m))
                else:
                    cp = int(t[si + 2])
                pv = t[t.index("pv") + 1:]
                dep = int(t[t.index("depth") + 1]) if "depth" in t else 0
            except (ValueError, IndexError):
                pass
        elif ln.startswith("bestmove"):
            best = ln.split()[1]
    return best, cp, mate, pv, dep


def refine_category(best, played, fen, delta, mate):
    if mate is not None and mate > 0 and best != played:
        return "MISSED_MATE"
    try:
        b = chesslib.Board(fen)
        mv = b.parse_uci(best)
        if b.gives_check(mv):
            return "MISSED_CHECK"
        if b.board[mv.to] is not None:
            return "MISSED_CAPTURE" if delta >= 200 else "MISSED_TACTIC"
    except Exception:
        pass
    return "TACTICAL_BLUNDER" if delta >= 250 else "EVALUATION_ERROR" if delta < 90 else "UNKNOWN"


def genepd_line(fen, bm):
    fields = fen.split()
    return " ".join(fields[:4]) + " bm %s;" % bm


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--critical", required=True)
    ap.add_argument("--teacher", default="",
                    help="path to Stockfish (or any UCI engine). Empty = self-teacher")
    ap.add_argument("--self-teacher-engine", default=os.path.join(REPO, "engine", "veltrix"))
    ap.add_argument("--teacher-movetime", type=int, default=700)
    ap.add_argument("--self-teacher-movetime", type=int, default=1500)
    ap.add_argument("--agree", type=int, default=30)
    ap.add_argument("--losspack", default="")
    ap.add_argument("--analysis", default="")
    ap.add_argument("--epd", default=os.path.join(REPO, "tests", "loss_regression.epd"))
    ap.add_argument("--max", type=int, default=400)
    args = ap.parse_args()

    is_self = not args.teacher
    tpath = args.self_teacher_engine if is_self else args.teacher
    tname = "self-teacher" if is_self else os.path.basename(args.teacher)
    tmt = args.self_teacher_movetime if is_self else args.teacher_movetime
    t = UCIEngine(tpath, options={"Hash": 128, "Threads": 1})
    ck = os.path.splitext(args.critical)[0]
    losspack = args.losspack or ck + "_losspack.jsonl"
    analysis = args.analysis or ck + "_analysis.jsonl"

    crits = [json.loads(l) for l in open(args.critical, encoding="utf-8") if l.strip()]
    crits = sorted(crits, key=lambda c: -c["swing_cp"])[:args.max]
    kept = rows = 0
    with open(losspack, "a", encoding="utf-8") as lp, \
            open(analysis, "a", encoding="utf-8") as an, \
            open(args.epd, "a", encoding="utf-8") as ep:
        for c in crits:
            try:
                best, t_best, mate, pv, dep = teacher_eval(t, c["fen"], tmt)
                b2 = chesslib.Board(c["fen"])
                b2.push(b2.parse_uci(c["move"]))
                _, t_after, mate2, _, _ = teacher_eval(t, b2.fen(), tmt)
                t_after = -t_after   # back to original stm perspective
                delta = t_best - t_after
            except Exception as ex:
                print(f"[teacher] skip (error: {ex})", flush=True)
                continue
            cat = refine_category(best, c["move"], c["fen"], delta, mate)
            # the teacher AGREEING with our move (best==played, or teacher
            # thinks the position improved) means there is nothing to blame:
            # skip entirely - it was not the losing point
            if best == c["move"] and delta > -args.agree:
                continue
            rec = dict(c)
            rec.update({"teacher": tname, "teacher_best": best,
                        "teacher_cp": t_best, "teacher_after_cp": t_after,
                        "teacher_delta": delta, "teacher_mate": mate,
                        "teacher_pv": pv[:12], "teacher_depth": dep,
                        "category": cat if cat != "UNKNOWN" else c["category_guess"]})
            an.write(json.dumps(rec) + "\n")
            if delta < args.agree and c["swing_cp"] < 200:
                continue  # normal disagreement, nothing learnable
            kept += 1
            ep.write(genepd_line(c["fen"], best) + "\n")
            # training row: teacher label on the POSITION, weight by severity
            w = min(6.0, 1.0 + abs(delta) / 80.0) * (0.6 if is_self else 1.0)
            lp.write(json.dumps({
                "fen": c["fen"], "eval": max(-2500, min(2500, t_best)),
                "stm": c["stm"], "result": 0.5, "weight": round(w, 2),
                "depth": tmt, "src": "self-teacher" if is_self else "stockfish-teacher",
                "category": rec["category"], "game": c["game"], "ply": c["ply"]}) + "\n")
            rows += 1
    print(f"[teacher] analysed {len(crits)} critical, kept {kept}, "
          f"losspack rows {rows} -> {losspack} (+ EPD {args.epd})", flush=True)


if __name__ == "__main__":
    main()
