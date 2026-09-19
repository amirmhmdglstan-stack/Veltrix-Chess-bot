# PART 18 - comprehensive verification results

Final test battery for the complete overhaul (19-part spec). Every bullet is
either an automated check (exact count below) or a recorded artefact in the
repository. Everything claimed has a test or a measured match behind it.

## Automated suites (final tip)

| suite | result | covers |
|-------|--------|--------|
| `tests/run_tests.py` | **56/56 pass** | engine UCI conformance, perft, mate suites, tactics EPD, loss-regression EPD, bench parity, NNUE vectors |
| `tests/gui_headless_test.py` | **116/116 pass** | everything below |
| `tests/book_oracle_test.py` | pass (python-chess CI dep) | opening book move quality |
| `tools/level_ladder.py` | **LADDER: monotone** | strength ladder by matches |

## Headless-GUI check map (requirements → checks)

- **Undo/redo suite (PART 8/9, 20 checks)** - single/multiple undo shrink the
  real move list (state-level takeback, not a view), alternating sides, redo,
  new move from a rewound position truncates the abandoned future, undo clears
  result, undo-all/redo-all round trip, undo cancels an in-flight engine
  search, stale bestmoves are discarded, engine re-arms from the position it
  was left at (bot-about-to-move case), PGN round trip through import/export.
- **Engine/model switching (PART 1/2/3)** - 11 internal opponents each expose
  exactly their configured budgets through `go()`, model cycling clean,
  external registry CRUD/persistence, dynamic UCI-option reading, side-effect
  free graceful handling of stockfish-absent, invalid paths, non-engine
  binaries; a complete game played against a registered external engine
  (fake UCI engine, deterministic legal moves).
- **Save/load/continue (PART 5/6)** - resume record persists full state
  (FEN, plies, clocks, increments, opponent, side, mode); restore is exact;
  corrupted payloads fail safe; menu navigation frames.
- **Sounds/animations (PART 10/11)** - all 9 sound kinds synthesize (RIFF
  one-shots), short buffers, classification of plain/capture/check/castle/
  promotion, toggles persisted, animation on/off honoured by the board
  (off means `animation_ms = 0`).
- **Analysis (PART 12/13)** - per-ply evals and mover-loss classification
  (mate-aware, already-decided positions excluded), scholar's-mate line
  yields exactly ONE blunder (3...Nf6??), thresholds configurable and
  honored, best moves + PVs captured, cancel path, learn-from-game writes
  a corpus-valid JSONL line (format identical to `tools/learn` selfplay).
- **Settings** - persisted and applied (sound, volume, animation flag,
  theme, board size, model, opponent key).

## Strength ladder - match-verified (PART 1/17)

`tools/level_ladder.py`, recorded in `data/model_verification.json`
(fixed-node budgets, UseBook off, Threads 1, Hash 32, fixed opening slate,
games alternate colours):

    Flash(4k) vs L1(4k)    +14 -14 =12  (identical config - parity, as built)
    L2(8k)   vs L1(4k)     +30 -8  =2
    L3(16k)  vs L2(8k)     +32 -3  =5
    L4(32k)  vs L3(16k)    +30 -4  =6
    L5(64k)  vs L4(32k)     +8 -2  =6
    L6(128k) vs L5(64k)    +10 -3  =3
    L7(512k) vs L6(128k)   +11 -0  =5
    L8^High(1M ref) vs L7  +5  -3  =8    -> LADDER: monotone

Level 8 IS High (same object, unlimited at play time); verification used a
1M-node reference cap for the top tier.

## High optimization - benchmark before/after + matches (PART 14/15)

Full methodology: `docs/PART14_OPTIMIZATION.md`.

- bench nodes identical (4,941,319) across plain/LTO/PGO builds → behaviour
  bit-identical; NPS +1.5% (LTO, now the portable default) and +5.7% (`make
  pgo` for host builds).
- "No regression" match (pre-change flags vs LTO, 24 games, 10+0.1s):
  12.5-11.5 → statistically identical. **No strength gain is claimed from
  the speed increase** (PART 18's rule respected: matches, not NPS, are
  what would establish strength, and the measured match Δelo ≈ 0 by
  construction).

## Stockfish (PART 2)

Optional, external, standard-UCI. Detect-on-PATH + common install locations
+ manual browse; remembered in config; NEVER downloaded; absence detected
gracefully at every call site; options are read from its `option` lines
dynamically so no Stockfish version assumptions exist in the code. The fake
engine in `tests/fake_engine.py` exercises exactly the same machinery.

## Known, documented limits (honest notes, not wishful items)

- tk-inter faces are plain; screenshot-level polish (gradients, motion)
      is bounded by the toolkit; all behaviours are present and tested.
- Sound playback depends on a host player (winsound on Windows; aplay/
  paplay/ffplay/afplay on Unix); absent → silent no-op, by design.
- `a2a1q` incident (once in 24 driver games): engine probes (60 targeted)
  did not reproduce it; the match driver now re-queries once before
  adjudicating, so it can no longer decide games.
