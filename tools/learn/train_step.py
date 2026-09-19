#!/usr/bin/env python3
"""
train_step.py - train an NNUE *candidate* from the base corpus + loss packs,
seeded from the current champion net (not from scratch).

Wraps tools/training/train_nnue.py:
  - discovers base data (data/nnue/*.jsonl) and losspack data
    (data/learn/*_losspack.jsonl) automatically, combine order kept stable
  - initialises from networks/champion.nnue when it exists (continual
    learning instead of retraining)
  - writes candidate to networks/candidates/<tag>.nnue (never overwrites the
    champion; promotion is a separate gate in promote.py)
  - saves the metrics JSON next to the candidate

The trainer's built-in quality gates (int/float parity, accumulator headroom)
still refuse to write a broken net.
"""
import argparse
import glob
import json
import os
import subprocess
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--base-glob", default=os.path.join(REPO, "data", "nnue", "*.jsonl"))
    ap.add_argument("--losspack-glob", default=os.path.join(REPO, "data", "learn",
                                                            "*_losspack.jsonl"))
    ap.add_argument("--tag", default="candidate")
    ap.add_argument("--epochs", type=int, default=3)
    ap.add_argument("--lr", type=float, default=None)
    ap.add_argument("--init-from", default=os.path.join(REPO, "networks", "champion.nnue"))
    ap.add_argument("--out-dir", default=os.path.join(REPO, "networks", "candidates"))
    ap.add_argument("--trainer-args", default="",
                    help="extra args passed verbatim to train_nnue.py")
    args = ap.parse_args()

    data = sorted(glob.glob(args.base_glob)) + sorted(glob.glob(args.losspack_glob))
    data = [d for d in data if os.path.getsize(d) > 0]
    if not data:
        raise SystemExit("[train-step] no training data found")
    os.makedirs(args.out_dir, exist_ok=True)
    cmd = [sys.executable, os.path.join(REPO, "tools", "training", "train_nnue.py"),
           "--data", *data, "--tag", args.tag, "--epochs", str(args.epochs),
           "--out", args.out_dir]
    if os.path.isfile(args.init_from):
        cmd += ["--init-from", args.init_from]
    if args.lr is not None:
        cmd += ["--lr", str(args.lr)]
    if args.trainer_args:
        cmd += args.trainer_args.split()
    print("[train-step] running:", " ".join(cmd), flush=True)
    t0 = __import__("time").time()
    r = subprocess.run(cmd, capture_output=True, text=True)
    sys.stdout.write(r.stdout[-4000:])
    sys.stderr.write(r.stderr[-2000:])
    cand = os.path.join(args.out_dir, args.tag + ".nnue")
    metrics = os.path.join(args.out_dir, args.tag + ".json")
    ok = r.returncode == 0 and os.path.isfile(cand)
    summary = {"ok": ok, "candidate": cand if ok else None, "metrics": metrics,
               "seconds": round(__import__("time").time() - t0, 1),
               "data_hint": f"{len(data)} files"}
    print("[train-step] " + json.dumps(summary), flush=True)
    raise SystemExit(0 if ok else 1)


if __name__ == "__main__":
    main()
