#!/usr/bin/env python3
"""
gen_data.py - Veltrix NNUE training-data generator (bootstrap, self-play).

Plays Veltrix vs Veltrix games, samples positions, and labels each sampled
position with a deeper search evaluation. Output is JSONL, one position per
line, matching the schema in docs/NNUE.md:

  {fen, eval, stm, depth, result, phase, weight, src, seq}

  fen    : position FEN
  eval   : teacher centipawn eval relative to side to move (clamped export)
  stm    : "w" or "b"
  result : game result from stm POV: 1 win / 0 draw / -1 loss (adjudicated)
  depth  : nominal search info of the label ("nodes 8000")
  phase  : "open" (<24 plies), "mid", "end" (<=12 non-king pieces)
  weight : training weight (failure packs raise this; self-play uses 1.0)
  src    : source tag for filtering/dedup/split stability
  seq    : running index per worker

Design rules (project policy):
- Broad coverage: every game type is kept (wins, draws, losses); the loss-
  learning pipeline in tools/learn/ adds HIGH-WEIGHT samples on top later.
- Determinism: --seed fully reproduces a shard (same games, same samples),
  given the same deterministic engine build.
- Positions are played from varied openings: MultiPV opening sampling with
  temperature for the first `rand_plies`, then normal engine moves.

Example:
  python tools/training/gen_data.py --engine engine/veltrix --games 400 \
      --out data/nnue/shard0.jsonl --seed 1 --workers 2
"""
import argparse
import json
import os
import random
import sys
import time

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(REPO, "gui"))
sys.path.insert(0, os.path.join(REPO, "tools"))

import chesslib                      # noqa: E402
from engine_driver import UCIEngine  # noqa: E402

# same opening set as tools/match.py for familiarity, plus playout variety
OPENINGS = [
    [], ["e2e4", "e7e5"], ["e2e4", "c7c5"], ["d2d4", "d7d5"], ["d2d4", "g8f6"],
    ["c2c4", "e7e5"], ["e2e4", "e7e6"], ["e2e4", "c7c6"], ["g1f3", "d7d5"],
    ["e2e3", "e7e5"], ["e2e4", "d7d5"], ["d2d4", "e7e6"], ["g2g3"],
]


class EngineProbe:
    """One long-lived engine instance for playing + labelling."""

    def __init__(self, path, hash_mb=32):
        self.e = UCIEngine(path, options={"Hash": hash_mb, "Threads": 1,
                                          "UseBook": "false", "UseNNUE": "false"})

    def _go(self, fen, nodes=None, movetime=None, multipv=1):
        if multipv > 1:
            self.e.setoption("MultiPV", multipv)
        self.e.send("position fen %s" % fen)
        limited = "nodes %d" % nodes if nodes else "movetime %d" % movetime
        self.e.send("go %s" % limited)
        lines = self.e.wait_for("bestmove", 120)
        if multipv > 1:
            self.e.setoption("MultiPV", 1)
        best, evals = None, {}
        for ln in lines:
            if ln.startswith("info ") and " multipv " in ln and " pv " in ln:
                t = ln.split()
                try:
                    mi, si, vi = t.index("multipv"), t.index("score"), t.index("pv")
                    idx = int(t[mi + 1])
                    if t[si + 1] == "mate":
                        n = int(t[si + 2])
                        sc = 100000 - abs(n) if n >= 0 else -100000 + abs(n)
                    else:
                        sc = int(t[si + 2])
                    evals[idx] = (t[vi + 1], sc)
                except (ValueError, IndexError):
                    pass
            elif ln.startswith("bestmove"):
                best = ln.split()[1]
        table = [evals[k] for k in sorted(evals)]
        return best, table

    def quit(self):
        try:
            self.e.quit()
        except Exception:
            pass


def material_count(board):
    return sum(1 for p in board.board if p != "." and p not in "Kk")


def phase_of(board, ply):
    if ply < 24:
        return "open"
    return "end" if material_count(board) <= 12 else "mid"


def play_game(probe, rng, args, game_id):
    """Play one game; yield labelled sample dicts."""
    board = chesslib.Board()
    for u in rng.choice(OPENINGS):
        board.push(board.parse_uci(u))
    samples, evals_hist, resign_run, draw_run = [], [], 0, 0
    result = 0
    plies = 0
    while plies < args.max_plies:
        fen = board.fen()
        stm = board.stm
        # ---- choose the move (randomized openings, engine afterwards) ----
        if plies < args.rand_plies:
            _, table = probe._go(fen, nodes=args.play_nodes, multipv=args.rand_multipv)
            cands = [mv for mv, sc in table if table and abs(table[0][1] - sc) <= args.rand_band]
            if not cands:
                _, table = probe._go(fen, nodes=args.play_nodes)
            move = rng.choice(cands) if cands else (table[0][0] if table else None)
        else:
            best, table = probe._go(fen, nodes=args.play_nodes)
            move = best if best not in (None, "0000") else (table[0][0] if table else None)
        cur_eval = table[0][1] if table else 0
        evals_hist.append(cur_eval)
        # ---- sample + label the pre-move position ----
        if move and rng.random() < args.sample_rate and len(samples) < args.max_samples_per_game:
            _, label_tbl = probe._go(fen, nodes=args.label_nodes)
            if label_tbl:
                samples.append({
                    "fen": fen, "eval": label_tbl[0][1], "stm": stm,
                    "depth": "nodes %d" % args.label_nodes, "result": 0,
                    "phase": phase_of(board, plies), "weight": 1.0,
                    "src": args.src, "seq": 0, "ply": plies,
                })
        # ---- adjudication ----
        if cur_eval >= args.resign_cp:
            resign_run += 1
            draw_run = 0
        elif cur_eval <= -args.resign_cp:
            resign_run += 1
            draw_run = 0
        elif abs(cur_eval) <= args.draw_cp and plies > 40:
            draw_run += 1
        else:
            resign_run = 0
            draw_run = 0
        if move is None:
            break
        board.push(board.parse_uci(move))
        plies += 1
        outc = board.outcome()
        if outc is not None:
            wres = {"1-0": 1, "0-1": -1, "1/2-1/2": 0}[outc[0]]
            result = wres                     # white-relative
            break
        if resign_run >= args.resign_count:
            # side to move is `stm` (pre-push); its eval sign decides
            stm_rel = -1 if cur_eval < 0 else 1
            result = stm_rel if stm == "w" else -stm_rel
            break
        if draw_run >= args.draw_count:
            result = 0
            break
    else:
        result = 0
    # convert white-relative result to each sample's stm POV
    for s in samples:
        s["result"] = result if s["stm"] == "w" else -result
        s.pop("ply", None)
        s["seq"] = game_id
    return samples, plies


def worker(args, worker_id):
    rng = random.Random(args.seed + worker_id * 7919)
    probe = EngineProbe(args.engine, hash_mb=args.hash)
    if getattr(args, "shard_id", -1) >= 0:
        out_path = args.out  # parent already injected the shard name
    else:
        out_path = args.out
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    total = t0 = 0
    t_start = time.time()
    with open(out_path, "w", encoding="utf-8") as f:
        for g in range(args.games):
            try:
                samples, plies = play_game(probe, rng, args, g)
            except Exception as e:
                print(f"[w{worker_id}] game {g} crashed: {e}", flush=True)
                continue
            for s in samples:
                f.write(json.dumps(s) + "\n")
            total += len(samples)
            if g % 10 == 0:
                rate = total / max(1, time.time() - t_start)
                print(f"[w{worker_id}] game {g}: {plies} plies, {len(samples)} samples "
                      f"(total {total}, {rate:.1f}/s)", flush=True)
            if args.max_positions and total >= args.max_positions:
                break
    probe.quit()
    print(f"[w{worker_id}] done: {total} positions -> {out_path}", flush=True)


def _worker_entry(t):
    worker(t[0], t[1])


def _spawn_workers(args):
    """Spawn plain child processes (robust: in-process forking deadlocked
    reliably on the second child in sandboxed environments)."""
    import subprocess as sp
    cmd_base = [sys.executable, os.path.abspath(__file__)]
    procs = []
    for i in range(args.workers):
        cmd = cmd_base + ["--engine", args.engine, "--out", args.out,
                          "--games", str(args.games), "--workers", "1",
                          "--seed", str(args.seed + i * 7919),
                          "--max-positions", str(args.max_positions),
                          "--rand-plies", str(args.rand_plies),
                          "--rand-multipv", str(args.rand_multipv),
                          "--rand-band", str(args.rand_band),
                          "--play-nodes", str(args.play_nodes),
                          "--label-nodes", str(args.label_nodes),
                          "--sample-rate", str(args.sample_rate),
                          "--max-samples-per-game", str(args.max_samples_per_game),
                          "--max-plies", str(args.max_plies),
                          "--resign-cp", str(args.resign_cp),
                          "--resign-count", str(args.resign_count),
                          "--draw-cp", str(args.draw_cp),
                          "--draw-count", str(args.draw_count),
                          "--src", args.src, "--shard-id", str(i)]
        # single-worker children must not truncate each other: force shards
        if args.workers > 1:
            child_out = args.out.replace(".jsonl", f".w{i}.jsonl")
            cmd[cmd.index(args.out)] = child_out
        procs.append(sp.Popen(cmd))
    rc = 0
    for p in procs:
        rc = max(rc, p.wait())
    return rc


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--engine", default=os.path.join(REPO, "engine", "veltrix"))
    ap.add_argument("--out", default=os.path.join(REPO, "data", "nnue", "train.jsonl"))
    ap.add_argument("--games", type=int, default=400)
    ap.add_argument("--workers", type=int, default=1)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--max-positions", type=int, default=0)
    ap.add_argument("--hash", type=int, default=32)
    ap.add_argument("--rand-plies", type=int, default=10)
    ap.add_argument("--rand-multipv", type=int, default=5)
    ap.add_argument("--rand-band", type=int, default=60)
    ap.add_argument("--play-nodes", type=int, default=1500)
    ap.add_argument("--label-nodes", type=int, default=8000)
    ap.add_argument("--sample-rate", type=float, default=0.30)
    ap.add_argument("--max-samples-per-game", type=int, default=30)
    ap.add_argument("--max-plies", type=int, default=200)
    ap.add_argument("--resign-cp", type=int, default=1300)
    ap.add_argument("--resign-count", type=int, default=4)
    ap.add_argument("--draw-cp", type=int, default=8)
    ap.add_argument("--draw-count", type=int, default=12)
    ap.add_argument("--src", default="selfplay-vnn1-1")
    ap.add_argument("--shard-id", type=int, default=-1)
    args = ap.parse_args()

    if args.workers > 1:
        raise SystemExit(_spawn_workers(args))
    else:
        worker(args, args.shard_id if args.shard_id >= 0 else 0)


if __name__ == "__main__":
    main()
