# networks/ — NNUE hook (experimental, not shipped)

Veltrix 1.0 ships with a pure **hand-crafted evaluation (HCE)**. This folder
is reserved for a future compact NNUE network; nothing here is required to
build or run the engine.

## Current state

- `engine/src/evaluate.cpp` contains the whole evaluation; it is purely
  hand-crafted (material, PSTs, pawn structure, king safety, mobility, etc.).
- There is **no network loader** compiled in. An early experiment tried a
  hybrid "NNUE as one eval term" approach with a tiny scalar probe; it was
  removed because a genuinely useful NNUE requires incremental accumulators
  (halfkp-style), which is planned for a later release.
- The UCI option schema intentionally does **not** expose an `EvalFile`
  option yet, so no GUI sends one.

## Drop-in later

When a network appears, it will be a small file in this folder, e.g.
`veltrix-XXXXX.nnue`, referenced by an `EvalFile` UCI option, and
auto-detected next to the executable (same pattern as `books/veltrix.bin`).
Whatever arrives, it will:

1. never be required (HCE stays the fallback),
2. be covered by the same perft/tactics regression tests, and
3. carry its own license note in `THIRD_PARTY_NOTICES.md` unless trained
   entirely from Veltrix self-play with GPL-compatible tooling.
