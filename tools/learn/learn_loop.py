#!/usr/bin/env python3
"""
learn_loop.py - Veltrix's automated learning loop (spec Phase 8).

One iteration:
  PLAY      selfplay.py          -> data/learn/games.jsonl      (full records)
  LOSS      (keep decisive games only, handled by find_critical)
  SAVE      games + analysis kept under data/learn/ (append-only, resumable)
  CRITICAL  find_critical.py     -> critical.jsonl
  ANALYSIS  analyze_teacher.py   -> analysis.jsonl + losspack + regression EPD
  DIAGNOSE  loss_report.py       -> report.md (why, root cause, attribution)
  TRAIN     train_step.py        -> networks/candidates/learn-<tag>.nnue
  GATES     promote.py           -> parity + tactics + loss-EPD + match/SPRT
  PROMOTE   only on full pass; old champion archived, lineage recorded.

Design rules honoured:
  - human-visible Why/RootCause/LearningAction at every step (report file)
  - champion is NEVER overwritten by an untested candidate
  - everything resumable: state in data/learn/loop_state.json
  - reproducible: loop config echoed into each artefact line
"""
import argparse
import json
import os
import subprocess
import sys
import time

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
LEARN = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(REPO, "data", "learn")


def sh(cmd, timeout=7200):
    print("[loop]$ " + " ".join(cmd), flush=True)
    t0 = time.time()
    r = subprocess.run(cmd, timeout=timeout)
    print(f"[loop]  -> exit {r.returncode} ({time.time() - t0:.0f}s)", flush=True)
    return r.returncode


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--iters", type=int, default=1)
    ap.add_argument("--engine", default=os.path.join(REPO, "engine", "veltrix"))
    ap.add_argument("--teacher", default="",
                    help="Stockfish path; empty = self-teacher mode (documented)")
    ap.add_argument("--games", type=int, default=24)
    ap.add_argument("--movetime", type=int, default=200)
    ap.add_argument("--match-games", type=int, default=60)
    ap.add_argument("--epochs", type=int, default=2)
    ap.add_argument("--options", action="append", default=[])
    ap.add_argument("--dry-run", action="store_true",
                    help="stop before promotion (gates still run)")
    args = ap.parse_args()

    os.makedirs(DATA, exist_ok=True)
    state_f = os.path.join(DATA, "loop_state.json")
    state = json.load(open(state_f)) if os.path.isfile(state_f) else {"iter": 0}
    py = sys.executable

    for it in range(state["iter"], state["iter"] + args.iters):
        tag = f"iter{it:03d}"
        print(f"\n================ LEARN ITER {it} ================", flush=True)

        # PLAY --------------------------------------------------------------
        games = os.path.join(DATA, "games.jsonl")
        rc = sh([py, os.path.join(LEARN, "selfplay.py"),
                 "--engine-w", args.engine, "--engine-b", args.engine,
                 "--games", str(args.games), "--movetime", str(args.movetime),
                 "--seed", str(1000 + it), "--out", games] +
                [o for o in sum((["--options", x] for x in args.options), [])])
        if rc != 0:
            print("[loop] selfplay failed - abort iter", flush=True)
            break

        # CRITICAL ----------------------------------------------------------
        crit = os.path.join(DATA, "critical.jsonl")
        sh([py, os.path.join(LEARN, "find_critical.py"), "--games", games,
            "--out", crit])
        if not os.path.isfile(crit) or os.path.getsize(crit) == 0:
            print("[loop] no critical positions - nothing to learn this round",
                  flush=True)
            continue

        # ANALYSIS ----------------------------------------------------------
        ana = os.path.join(DATA, "analysis.jsonl")
        pack = os.path.join(DATA, "iter_losspack.jsonl")
        if os.path.isfile(pack):
            os.remove(pack)
        cmd = [py, os.path.join(LEARN, "analyze_teacher.py"),
               "--critical", crit, "--losspack", pack, "--analysis", ana]
        if args.teacher:
            cmd += ["--teacher", args.teacher]
        sh(cmd, timeout=max(3600, 2 * 60 * 120))

        # DIAGNOSE ----------------------------------------------------------
        rep = os.path.join(DATA, f"loss_report_{tag}.md")
        sh([py, os.path.join(LEARN, "loss_report.py"), "--analysis", ana,
            "--games", games, "--out", rep])

        # TRAIN -------------------------------------------------------------
        if not os.path.isfile(pack) or os.path.getsize(pack) == 0:
            print("[loop] teacher found nothing learnable - skip training",
                  flush=True)
            continue
        rc = sh([py, os.path.join(LEARN, "train_step.py"),
                 "--tag", f"learn-{tag}", "--epochs", str(args.epochs),
                 "--losspack-glob", os.path.join(DATA, "*losspack.jsonl")])
        if rc != 0:
            print("[loop] trainer failed/refused - abort", flush=True)
            break

        # GATES + PROMOTE ---------------------------------------------------
        cand = os.path.join(REPO, "networks", "candidates", f"learn-{tag}.nnue")
        metrics = cand.replace(".nnue", ".json")
        cmd = [py, os.path.join(LEARN, "promote.py"), "--candidate", cand,
               "--metrics", metrics, "--match-games", str(args.match_games),
               "--match-movetime", str(args.movetime)]
        if args.dry_run:
            cmd.append("--dry-run")
        rc = sh(cmd, timeout=max(7200, args.games * args.movetime * 0.1 + 3600))
        state["iter"] = it + 1
        json.dump(state, open(state_f, "w"), indent=1)
        print(f"[loop] iteration {it} complete; promote exit={rc}", flush=True)

    print("[loop] done.")


if __name__ == "__main__":
    main()
