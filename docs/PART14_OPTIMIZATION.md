# High optimization (PART 14/15/16) - what was done, with numbers

Goal per the spec: optimize the engine's **High** configuration
**aggressively without ANY intentional strength sacrifice**: no depth,
node, evaluation or extension reductions; verify by benchmark AND matches;
don't weaken anything to gain speed. Only implementation/build-level
optimizations were applied.

## What changed (behaviour-identical by construction and by measurement)

1. **LTO default** - whole-program optimization on by default
   (`LTO ?= 1`, `-flto=auto` + link-time `-O3`). `make LTO=0` for dev.
2. **PGO build target** - `make pgo` (instrument → train on the bench +
   a middlegame workload → rebuild with the profile; portable ISA,
   same chess behaviour).
3. **Build matrix documented** (PART 16) - default stays portable
   (x86-64-v2 = SSE4.2/POPCNT), `AVX2=1`, `NATIVE=1`, `pgo`. Windows
   build (build.bat / MSYS2 g++) never assumes AVX2 and is unaffected.
4. **Rejected on measurement:** `-Ofast` (slower: 1,478,551 median;
   FP-vectorization gains are irrelevant to the integer search core),
   `-funroll-loops -falign-loops=32` (inside noise; rejected).

## Measurements (this sandbox, taskset-pinned single thread)

Bench workload is the engine's own `bench` command; its node count is the
strict behaviour fingerprint and was **identical in every build**:

| build   | bench nodes | median NPS (5 runs) | min         | max         |
|---------|-------------|--------------------|-------------|-------------|
| plain   | 4,941,319   | 1,483,434          | 1,363,122   | 1,559,759   |
| LTO     | 4,941,319   | 1,505,123          | 1,462,361   | 1,535,524   |
| PGO     | 4,941,319   | 1,568,174          | 1,490,144   | 1,590,382   |

Net: **+1.5% NPS LTO (default for everyone), +5.7% NPS with `make pgo`
(host builds; recommended for playing from source)**. All tests green on
the LTO default (56/56) and PGO config (bench nodes locked).

## "No strength sacrifice" evidence

- **Bench node-parity**: identical 4,941,319 nodes in every build - the
  search tree is bit-for-bit the same (same depths, same move choices).
- **Match (PART 15 requirement):** pre-change-flags binary vs LTO binary
  played 24 games (10s+0.1s, UseBook off, Hash 32, opening slate):
  **12.5 - 11.5 (Δelo ≈ -14, error bars huge)** - statistically identical,
  as expected from bit-identical search behaviour. No regression.
- The 56/56 engine suite (tactics EPs, loss-regression EPs, perft, UCI,
  mate suites) passes unchanged on the optimized binary.

## Claims deliberately NOT made

Speed ≠ strength. The numbers above only document *throughput* gains with
behaviour preserved; no Elo improvement is asserted from them (per PART 18,
strength claims require engine matches - the measured match result is
statistically 0, i.e. "same engine, faster").

## Incidental fix shipped alongside

`tools/match.py` now survives a single stale/garbled bestmove glitch
(re-queries once before adjudicating). Root cause of the one observed
"a2a1q" incident could not be reproduced in 60 targeted engine probes;
the driver no longer lets it cost a game either way.
