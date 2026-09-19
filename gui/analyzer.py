"""
analyzer.py - whole-game analysis backend (PART 12).

Runs an engine (Veltrix or any registered external UCI engine) over every
position of a played game and produces:

* per-ply eval (white POV), best move and PV (as UCI and SAN strings)
* move classification with CONFIGURABLE thresholds (blunder / mistake /
  inaccuracy), computed strictly from the mover-side eval drop
* eval-graph data (white-POV series for plot)
* critical-moment list and condensed summary

Eval math (kept explicitly honest):
  * engine `score cp` is side-to-move POV; we store white-POV everywhere.
  * mate scores are clamped to +/- 10000 - 10*|mate| (bounded graph).
  * loss_L(player) = whitePOV(P) - whitePOV(P') for white, negated for
    black - i.e. exactly how much the moved side gave away.
  * already-lost/ won positions are excluded from blame: if the mover was
    below -800 or above +800 before the move (matter decided), a further
    drop is not classified (only big swings between ok/even bands count).
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..",
                                "tools"))

from chesslib import Board, STARTPOS_FEN          # noqa: E402
from engine_driver import UCIEngine               # noqa: E402

MATE_CAP = 10000


def cp_of(info_line: str):
    """score from an info line -> (cp, mate) with cp stm-POV capped."""
    if " score " not in info_line:
        return None, None
    parts = info_line.split()
    i = parts.index("score")
    kind = parts[i + 1]
    if kind == "cp":
        return int(parts[i + 2]), None
    if kind == "mate":
        m = int(parts[i + 2])
        return (MATE_CAP - 10 * abs(m)) * (1 if m > 0 else -1), m
    return None, None


def classify(loss: int, mover_eval_before: int, thr) -> str:
    if loss is None:
        return ""
    if abs(mover_eval_before) > 800:     # already decided; no fresh blame
        return ""
    if loss >= thr["blunder"]:
        return "blunder"
    if loss >= thr["mistake"]:
        return "mistake"
    if loss >= thr["inaccuracy"]:
        return "inaccuracy"
    return ""


KLASS_GLYPH = {"blunder": "??", "mistake": "?", "inaccuracy": "?!", "": ""}


class AnalysisReport:
    def __init__(self, initial_fen, moves_uci, sans):
        self.initial_fen = initial_fen
        self.moves_uci = list(moves_uci)
        self.sans = list(sans)
        self.entries = []          # dicts; one per ply
        self.analyser = ""
        self.budget_nodes = 0

    @property
    def graph_w(self) -> list[int]:
        return [e["ev_w"] for e in self.entries if e["ev_w"] is not None]

    @property
    def critical(self) -> list[dict]:
        return [e for e in self.entries if e["klass"]]

    def summary(self) -> str:
        n = len(self.entries)
        crit = self.critical
        blunder = sum(1 for e in crit if e["klass"] == "blunder")
        mistake = sum(1 for e in crit if e["klass"] == "mistake")
        inacc = sum(1 for e in crit if e["klass"] == "inaccuracy")
        biggest = max(crit, key=lambda e: e["loss"], default=None)
        b = (f"; biggest: move {biggest['no']} {biggest['san']} (-{biggest['loss']} cp)"
             if biggest else "")
        return (f"{n} plies analyzed by {self.analyser} "
                f"(budget {self.budget_nodes:,} nodes/position): "
                f"{blunder} blunders, {mistake} mistakes, {inacc} inaccuracies{b}")


def analyze_game(initial_fen: str, moves_uci: list[str],
                 engine_path: str, engine_options: dict | None = None,
                 nodes: int = 32_000, thresholds: dict | None = None,
                 progress_cb=None, cancel=None) -> AnalysisReport | None:
    """Blocking whole-game analysis (run it in a worker thread).

    Returns the report, or None when cancelled/failed to start. progress_cb
    is called after each ply with (done_plies, total_plies).
    """
    thr = {"blunder": 300, "mistake": 200, "inaccuracy": 100}
    thr.update(thresholds or {})
    board = Board(initial_fen)
    sans = []
    for u in moves_uci:
        m = board.parse_uci(u)
        sans.append(board.san(m))
        board.push(m)
    board = Board(initial_fen)

    eng = UCIEngine(engine_path, options=dict(engine_options or {}),
                    cwd=None)
    report = AnalysisReport(initial_fen, moves_uci, sans)
    report.budget_nodes = nodes
    try:
        report.analyser = eng.id_name or "engine"
        total = len(moves_uci)
        for i, uci_m in enumerate(moves_uci):
            if cancel is not None and cancel.is_set():
                return None
            fen_before = board.fen()
            stm = board.stm
            hist = moves_uci[:i]
            bm, ponder, infos = eng.analyze(initial_fen, hist, nodes=nodes)
            ev_cp, mate = None, None
            pv = []
            for line in reversed(infos):
                c, mm = cp_of(line)
                if c is not None:
                    ev_cp, mate = c, mm
                    toks = line.split()
                    if "pv" in toks:
                        pv = toks[toks.index("pv") + 1:]
                    break
            ev_w = ev_cp if stm == "w" or ev_cp is None else -ev_cp
            # SAN for the principal variation
            pv_san = []
            pv_b = Board(initial_fen)
            for u in hist:
                pv_b.push(pv_b.parse_uci(u))
            for u in pv[:8]:
                try:
                    m2 = pv_b.parse_uci(u)
                    pv_san.append(pv_b.san(m2))
                    pv_b.push(m2)
                except ValueError:
                    break
            m = board.parse_uci(uci_m)
            board.push(m)
            report.entries.append({
                "ply": i + 1,
                "no": f"{i // 2 + 1}{'.' if stm == 'w' else '...'}",
                "uci": uci_m, "san": sans[i], "stm": stm,
                "ev_w": ev_w, "mate": mate,
                "best": bm if bm not in (None, "0000") else "",
                "pv": pv_san,
                "klass": "", "loss": 0,
            })
            if progress_cb:
                progress_cb(i + 1, total)
        # second pass: mover-relative loss & classification
        for i in range(len(report.entries) - 1):
            e = report.entries[i]
            nxt = report.entries[i + 1]
            if e["ev_w"] is None or nxt["ev_w"] is None or e["mate"]:
                continue
            # drop attributed to the mover of THIS ply:
            # mover changed the position from ev(P_i) to ev(P_{i+1}) with the
            # pick of the played move vs the engine's best
            if e["stm"] == "w":
                loss = e["ev_w"] - nxt["ev_w"]
            else:
                loss = nxt["ev_w"] - e["ev_w"]
            mover_ev = e["ev_w"] if e["stm"] == "w" else -e["ev_w"]
            e["loss"] = max(0, loss)
            e["klass"] = classify(max(0, loss), mover_ev, thr)
        return report
    finally:
        eng.quit()
