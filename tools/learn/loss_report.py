#!/usr/bin/env python3
"""
loss_report.py - auto-generate WHY-DID-VELTRIX-LOSE reports (spec Phase 7).

Input: analysis.jsonl from analyze_teacher.py + the games file.
Output: markdown and plain-text report with the mandated per-game structure:

  GAME RESULT / CRITICAL POSITION / MOVE made / EVALUATION (before→after,
  own eval vs teacher judgement) / STOCKFISH (teacher) BEST MOVE +
  evaluation / CATEGORY (fixed list) / WHY / PV / LIKELY ROOT CAUSE /
  LEARNING ACTION.

Root-cause inference is honest: it combines the heuristic root_hint with the
teacher category and marks its confidence. Manual review is always possible -
the report is data, decisions stay with gates.
"""
import argparse
import json
import os
import sys
from collections import Counter

FIXED_CATEGORIES = [
    "TACTICAL_BLUNDER", "MISSED_MATE", "MISSED_CHECK", "MISSED_TACTIC",
    "MISSED_CAPTURE", "KING_SAFETY", "ENDGAME_MISPLAY", "TIME_MANAGEMENT",
    "SEARCH_HORIZON", "MOVE_ORDERING_ERROR", "PRUNING_ERROR",
    "QUIESCENCE_ERROR", "EVALUATION_ERROR", "UNKNOWN",
]


def learning_action(cat, root):
    if cat in ("MISSED_MATE", "MISSED_CHECK", "MISSED_CAPTURE", "TACTICAL_BLUNDER"):
        return ("Add position to tests/loss_regression.epd (done automatically) "
                "and emit weighted teacher-labelled training row (done). "
                "If regression EPD grows on this category, inspect SEE/quiet "
                "checks in quiescence before touching eval.")
    if cat == "EVALUATION_ERROR" or root == "EVALUATION_ERROR":
        return ("Emit teacher-labelled row with high weight (done). These rows "
                "steer the NNUE toward the missed static feature without "
                "hardcoding the move.")
    if root == "TIME_MANAGEMENT":
        return "Do NOT train eval on this row; re-check time allocation formula."
    if root == "SEARCH_HORIZON":
        return ("Search-side issue: prefer depth/SEE diagnostics over retraining; "
                "row emitted at low weight as a tiebreak sample only.")
    return "Row emitted with moderate weight; monitor category counts."


def why_text(c):
    delta = c.get("teacher_delta", 0)
    if delta >= 250:
        base = (f"Teacher refutes the played move outright: its best line leaves "
                f"us {delta}cp worse than the alternative. Single-position collapse "
                f"- our own eval ({c['eval_before']}cp) did not foresee it.")
    elif delta >= 90:
        base = (f"Teacher prefers {c.get('teacher_best')} by {delta}cp over the "
                f"played {c['move']}; our scoring underestimated the reply.")
    else:
        base = (f"Disagreement is small ({delta}cp) but the game still collapsed "
                f"from here; likely cumulative pressure or a search artifact.")
    return base


def root_cause(c):
    hints = []
    if abs(c.get("eval_before", 0)) < 60 and c.get("category") == "EVALUATION_ERROR":
        hints.append(("EVALUATION / NNUE missing feature", "high"))
    if c.get("ms_played", 999) < 60:
        hints.append(("time allocation (move played in <60ms)", "medium"))
    if c.get("depth", 99) <= 10 and c.get("category", "").startswith("MISSED"):
        hints.append(("search shallow at critical point vs teacher", "medium"))
        hints.append(("quiescence / SEE threshold too lax for forcing lines", "low"))
    if not hints:
        hints.append(("unknown - needs manual review", "low"))
    return hints


def render(recs, games_map):
    lines = []
    per_game = {}
    for c in recs:
        per_game.setdefault(c["game"], []).append(c)
    cat_counts = Counter(c.get("category", "UNKNOWN") for c in recs)
    lines.append("# Veltrix Loss Report")
    lines.append("")
    lines.append(f"Analysed {len(per_game)} games with critical positions, "
                 f"{len(recs)} critical plies. Teacher: "
                 f"{recs[0].get('teacher', 'n/a') if recs else 'n/a'}")
    lines.append("")
    lines.append("## Category totals")
    for cat in FIXED_CATEGORIES:
        if cat_counts.get(cat):
            lines.append(f"- **{cat}**: {cat_counts[cat]}")
    lines.append("")
    for g, cs in sorted(per_game.items()):
        grec = games_map.get(g, {})
        lines.append(f"## Game {g} — result {cs[0].get('gresult')} ({cs[0].get('reason')})")
        lines.append("")
        for c in sorted(cs, key=lambda x: x["ply"])[:4]:
            cat = c.get("category", "UNKNOWN")
            if cat not in FIXED_CATEGORIES:
                cat = "UNKNOWN"
            lines.append(f"### ply {c['ply']} ({c['phase']})")
            lines.append(f"- CRITICAL POSITION: `{c['fen']}`")
            lines.append(f"- MOVE: `{c['move']}` (stm: {c['stm']})")
            lines.append(f"- EVALUATION: own {c['eval_before']} → {c['eval_after']} cp "
                         f"| teacher: best {c.get('teacher_cp')} cp, "
                         f"after our move {c.get('teacher_after_cp')} cp")
            lines.append(f"- TEACHER BEST: `{c.get('teacher_best')}` "
                         f"(depth {c.get('teacher_depth')})")
            lines.append(f"- CATEGORY: **{cat}**")
            lines.append(f"- WHY: {why_text(c)}")
            if c.get("teacher_pv"):
                lines.append(f"- PV: `{' '.join(c['teacher_pv'][:8])}`")
            rc = root_cause(c)
            lines.append(f"- LIKELY ROOT CAUSE: " + "; ".join(f"{h} ({p})" for h, p in rc))
            # search-vs-eval attribution line
            attrib = ("eval-first (train)" if cat == "EVALUATION_ERROR" and
                      rc[0][1] == "high" else
                      "search-time-first (diagnose search before training heavily)")
            lines.append(f"- ATTRIBUTION: {attrib}")
            lines.append(f"- LEARNING ACTION: {learning_action(cat, c.get('root_hint'))}")
            lines.append("")
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--analysis", required=True)
    ap.add_argument("--games", required=True)
    ap.add_argument("--out", default="")
    args = ap.parse_args()
    recs = [json.loads(l) for l in open(args.analysis, encoding="utf-8") if l.strip()]
    games_map = {}
    for l in open(args.games, encoding="utf-8"):
        if l.strip():
            g = json.loads(l)
            games_map[g["game"]] = g
    out = args.out or os.path.splitext(args.analysis)[0] + "_report.md"
    txt = render(recs, games_map)
    open(out, "w", encoding="utf-8").write(txt)
    print(f"[report] wrote {out} ({len(recs)} critical plies)")


if __name__ == "__main__":
    main()
