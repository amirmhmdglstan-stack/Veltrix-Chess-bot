#!/usr/bin/env python3
"""
benchmark.py - standardized Veltrix benchmark (NPS over the built-in set).

Usage:
    python tools/benchmark.py [depth] [engine]
"""
import os
import subprocess
import sys


def main():
    depth = sys.argv[1] if len(sys.argv) > 1 else "13"
    engine = sys.argv[2] if len(sys.argv) > 2 else None
    if engine is None:
        here = os.path.dirname(os.path.abspath(__file__))
        for cand in (os.path.join(here, "..", "engine", "veltrix.exe"),
                     os.path.join(here, "..", "engine", "veltrix"),
                     os.path.join(here, "..", "bin", "veltrix.exe"),
                     os.path.join(here, "..", "bin", "veltrix")):
            if os.path.isfile(cand):
                engine = cand
                break
        else:
            raise SystemExit("engine not found")
    print(f"benchmark: {engine} (depth {depth})")
    p = subprocess.run([engine], input=f"bench {depth}\nquit\n", text=True,
                       capture_output=True, timeout=600)
    out = p.stdout
    total_time = total_nodes = None
    for line in out.splitlines():
        if line.startswith("Total time"):
            total_time = line.split(":")[1].strip()
        if line.startswith("Total nodes"):
            total_nodes = line.split(":")[1].strip()
        if line.startswith("Nodes/second"):
            pass
    nps = [l for l in out.splitlines() if l.startswith("Nodes/second")]
    print(out.strip())
    if nps:
        print(f"\n==> {nps[-1]}")
    # machine-readable line for changelog/CI comparisons
    try:
        nps_val = int(nps[-1].split(":")[1].replace(",", "").strip())
        print(f"BENCH depth={depth} nodes={total_nodes} time={total_time} nps={nps_val}")
    except Exception:
        pass


if __name__ == "__main__":
    main()
