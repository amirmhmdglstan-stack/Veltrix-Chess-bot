#!/usr/bin/env python3
"""
promote.py - the ONLY place where a candidate may become champion.

Gate order (all must pass; old champion is never deleted):
  1. engine-level int parity: candidate net loaded into the engine via the
     arena layout, `nnueeval` outputs compared exactly against
     tests/nnue_vectors.txt produced by the trainer.
  2. regression tactics: engine passes tests/tactics.py AND solves the
     learned loss_regression.epd to at least the previous champion's score.
  3. match: candidate vs champion under positive control; promotion requires
     winning (score >= threshold) or SPRT acceptance when --sprt is used.

Arena layout (created/kept here):
  learn/arena/champion/veltrix  + networks/champion.nnue
  learn/arena/learner/veltrix   + networks/champion.nnue  (the candidate)
Engine auto-loads networks/champion.nnue relative to the executable, so both
sides run unmodified.

Writes networks/CHAMPION.json lineage and archives superseded champions to
networks/history/.
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import time

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ARENA = os.path.join(REPO, "tools", "learn", "arena")
ENG_SRC = os.path.join(REPO, "engine", "veltrix")


def arena_setup(candidate_net):
    champ_net = os.path.join(REPO, "networks", "champion.nnue")
    for side in ("champion", "learner"):
        d = os.path.join(ARENA, side, "networks")
        os.makedirs(d, exist_ok=True)
        shutil.copy2(ENG_SRC, os.path.join(ARENA, side, "veltrix"))
    if os.path.isfile(champ_net):
        shutil.copy2(champ_net, os.path.join(ARENA, "champion", "networks", "champion.nnue"))
    shutil.copy2(candidate_net, os.path.join(ARENA, "learner", "networks", "champion.nnue"))
    return (os.path.join(ARENA, "champion", "veltrix"),
            os.path.join(ARENA, "learner", "veltrix"),
            os.path.isfile(champ_net))


def parity_gate(engine_binary, vectors):
    """Exact-match the engine's nnueeval against the trainer's golden ints."""
    p = subprocess.Popen([engine_binary], stdin=subprocess.PIPE,
                         stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                         text=True, bufsize=1)
    bad = tot = 0
    for line in open(vectors, encoding="utf-8"):
        fen, expect = line.rstrip("\n").split("\t")
        p.stdin.write(f"position fen {fen}\nnnueeval\n")
        p.stdin.flush()
        while True:
            out = p.stdout.readline()
            if not out:
                break
            if out.startswith("nnue "):
                got = int(out.split()[1])
                tot += 1
                if got != int(expect):
                    bad += 1
                break
    p.stdin.write("quit\n")
    p.stdin.flush()
    p.wait(timeout=10)
    return tot, bad


def epd_score(engine_binary, epd_path, movetime=200):
    """fraction of `bm`-most-likely-matched moves over the EPD file"""
    e = subprocess.Popen([engine_binary], stdin=subprocess.PIPE,
                         stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                         text=True, bufsize=1)
    ok = tot = 0
    for line in open(epd_path, encoding="utf-8"):
        line = line.strip()
        if not line or " bm " not in line:
            continue
        fen = line.split(" bm ")[0]
        bm = line.split(" bm ")[1].rstrip(";").split()[0]
        e.stdin.write(f"position fen {fen}\ngo movetime {movetime}\n")
        e.stdin.flush()
        got = None
        while True:
            out = e.stdout.readline()
            if out.startswith("bestmove"):
                got = out.split()[1]
                break
            if out == "":
                break
        tot += 1
        ok += (got == bm)
    e.stdin.write("quit\n")
    e.stdin.flush()
    e.wait(timeout=10)
    return ok, tot


def run(cmd, timeout=7200):
    print("[gate]$ " + " ".join(cmd), flush=True)
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--candidate", required=True)
    ap.add_argument("--metrics", default="")
    ap.add_argument("--vectors", default=os.path.join(REPO, "tests", "nnue_vectors.txt"))
    ap.add_argument("--epd", default=os.path.join(REPO, "tests", "loss_regression.epd"))
    ap.add_argument("--tactics", default=os.path.join(REPO, "tests", "tactics.py"))
    ap.add_argument("--match-games", type=int, default=60)
    ap.add_argument("--match-movetime", type=int, default=200)
    ap.add_argument("--promote-threshold", type=float, default=0.525,
                    help="learner score share required for promotion")
    ap.add_argument("--sprt", action="store_true",
                    help="use tools/sprt.py instead of fixed-game match")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    t0 = time.time()
    champ_bin, learn_bin, has_champ = arena_setup(args.candidate)
    log = {"candidate": args.candidate, "gates": {}}

    # gate 1: exact UCI parity against golden vectors -----------------------
    if os.path.isfile(args.vectors):
        tot, bad = parity_gate(learn_bin, args.vectors)
        log["gates"]["parity"] = {"total": tot, "mismatch": bad}
        print(f"[gate] UCI parity: {tot - bad}/{tot} exact", flush=True)
        if bad:
            log["verdict"] = "REJECT (engine/trainer int mismatch)"
            return finish(log)
    else:
        print("[gate] no vector file - parity gate skipped", flush=True)

    # gate 2: tactics + loss-regression EPD ---------------------------------
    r = run([sys.executable, args.tactics, learn_bin])
    tac_ok = "PASS" in r.stdout and "FAIL" not in r.stdout
    log["gates"]["tactics"] = {"pass": tac_ok, "tail": r.stdout[-400:]}
    print(f"[gate] tactics: {'PASS' if tac_ok else 'FAIL'}", flush=True)
    if not tac_ok:
        log["verdict"] = "REJECT (tactics regression)"
        return finish(log)
    if os.path.isfile(args.epd) and os.path.getsize(args.epd) > 0:
        c_ok = l_ok = tot = 0
        l_ok, tot = epd_score(learn_bin, args.epd)
        if has_champ:
            c_ok, _ = epd_score(champ_bin, args.epd)
        log["gates"]["loss_epd"] = {"learner": f"{l_ok}/{tot}", "champion": f"{c_ok}/{tot}"}
        print(f"[gate] loss EP  learner {l_ok}/{tot} vs champion {c_ok}/{tot}", flush=True)
        if l_ok < c_ok:
            log["verdict"] = "REJECT (loss regression worse than champion)"
            return finish(log)

    # gate 3: match ----------------------------------------------------------
    # (no champion net yet => champion binary runs HCE; the match still runs,
    #  which is exactly the first-strength-gate for the NNUE rollout)
    if True:
        if args.sprt:
            r = run([sys.executable, os.path.join(REPO, "tools", "sprt.py"),
                     "--base", champ_bin, "--test", learn_bin,
                     "--tc", f"0+{args.match_movetime / 1000:.3f}",
                     "--max-games", str(max(args.match_games, 100))])
            accepted = "SPRT ACCEPTED H1" in r.stdout
            log["gates"]["match"] = {"mode": "sprt", "accepted": accepted,
                                     "tail": r.stdout[-600:]}
        else:
            r = run([sys.executable, os.path.join(REPO, "tools", "match.py"),
                     "--engines", champ_bin, learn_bin,
                     "--games", str(args.match_games),
                     "--movetime", str(args.match_movetime),
                     "--options", "UseNNUE=true",
                     "--pgn", os.path.join(REPO, "data", "learn", "gate_match.pgn")],
                    timeout=max(7200, args.match_games * args.match_movetime * 0.004 + 600))
            # match.py prints "  <path>: <points>" and "  draws (count): <n>"
            pts = {}
            draws = 0
            for ln in r.stdout.splitlines():
                ls = ln.strip()
                for p in (champ_bin, learn_bin):
                    if ls.startswith(p + ":"):
                        pts[p] = float(ls.split(":")[1].strip())
                if ls.startswith("draws (count):"):
                    draws = int(ls.split(":")[1])
            n = max(1, draws + sum(int(pts.get(p, 0)) for p in (champ_bin, learn_bin)))
            learn_pts = pts.get(learn_bin, 0.0)
            champ_pts = pts.get(champ_bin, 0.0)
            share = learn_pts / max(1e-9, learn_pts + champ_pts)
            accepted = share >= args.promote_threshold
            log["gates"]["match"] = {"mode": "fixed", "learner_points": learn_pts,
                                     "champion_points": champ_pts, "games": args.match_games,
                                     "share": round(share, 3), "accepted": accepted,
                                     "tail": r.stdout[-400:]}
        print(f"[gate] match accepted: {accepted}", flush=True)
        if not log["gates"]["match"].get("accepted"):
            log["verdict"] = "REJECT (not stronger in match)"
            return finish(log)
    # PROMOTE ---------------------------------------------------------------
    if args.dry_run:
        log["verdict"] = "WOULD PROMOTE (dry-run)"
        return finish(log)
    nets = os.path.join(REPO, "networks")
    hist = os.path.join(nets, "history")
    os.makedirs(hist, exist_ok=True)
    stamp = time.strftime("%Y%m%d_%H%M%S")
    champ = os.path.join(nets, "champion.nnue")
    if os.path.isfile(champ):
        shutil.copy2(champ, os.path.join(hist, f"champion_{stamp}.nnue"))
    shutil.copy2(args.candidate, champ)
    lineage = {"promoted_at": stamp, "candidate": args.candidate,
               "metrics": args.metrics, "gates": log["gates"]}
    linp = os.path.join(nets, "CHAMPION.json")
    old = {}
    if os.path.isfile(linp):
        old = json.load(open(linp))
    old.setdefault("history", []).append(lineage)
    json.dump(old, open(linp, "w"), indent=1)
    log["verdict"] = "PROMOTED"
    finish(log)
    print(f"[promote] {args.candidate} -> networks/champion.nnue (old archived)")


def finish(log):
    print(json.dumps(log, indent=1))
    os.makedirs(os.path.join(REPO, "data", "learn"), exist_ok=True)
    with open(os.path.join(REPO, "data", "learn", "promote_log.jsonl"), "a",
              encoding="utf-8") as f:
        f.write(json.dumps(log) + "\n")
    raise SystemExit(0 if "PROMOTE" in log.get("verdict", "") else 1)


if __name__ == "__main__":
    main()
