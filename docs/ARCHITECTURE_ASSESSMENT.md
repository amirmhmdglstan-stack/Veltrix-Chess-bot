# Veltrix architecture assessment & implementation order

*(Audit performed on commit 15fca40 — all tests green: 53/53 engine, 41/41 GUI, 7/7 tactics.)*

## 1. What already exists (verified by reading every engine source file)

**Movegen/position** (`movegen.cpp` 428 LoC, `position.cpp` 642): bitboard pseudo-legal
generation with legality verified after `do_move` (king-safety check), full
make/unmake via `StateInfo` stack, incremental Zobrist (piece/key/pawn key),
repetition detection, rule-50, SEE (`see_ge`). Tests: perft + 53-test suite.

**Search** (`search.cpp` 925): PVS with aspiration windows (widening ±delta),
TT cutoffs with separate eval bucket + score-normalisation, hash-move
ordering, MVV-LVA+SEE good/bad capture split, 2 killers, gravity-formula
history, counter-move table, quiescence with stand-pat + delta pruning +
SEE≥0 filter + check evasions, LMR (log table, improving/PV/killer tweaks),
null-move (material + non-null guards), razoring, reverse-futility, LMP,
mate-distance pruning, IID(via depth−2), singular extensions + multi-cut,
Lazy-SMP helper threads with best-thread voting, soft/hard time management
(best-move stability factor), MultiPV, `UCI_LimitStrength`.

**Eval** (`evaluate.cpp` 372): tapered mg/eg — PeSTO PSQT (CC0), mobility,
pawn structure (isolated/doubled/backward, 64K pawn cache), passed pawn by
rank, king-ring attack units + danger table + shelter, rook open/semi/7th,
outposts, bishop pair, tempo, mop-up endgame, drawish scaling.

**Infrastructure**: UCI fully compliant (options incl. Hash/Threads/MultiPV/
UseBook/BookFile/Ponder/Move Overhead/strength limiting), Polyglot book
(incremental key, auto-load), Lazy-SMP threads, tools: match/sprt/epd/
benchmark/build_opening_book, GUI (tkinter) driving the same UCI dialect.

**Correctness audit result**: no bug found this pass; the two latent bugs from
the GCC-16 audit (pop_lsb mop-up, Zobrist table hazard) remain fixed and
tested.

## 2. Gaps, by expected Elo / effort

1. **NNUE evaluation — the single biggest lever.** The handcrafted eval is
   solid but classical; a trained net (even bootstrap-distilled from own
   deep search, without any external data) historically gives triple-digit
   Elo for engines at this stage. `networks/` exists but is empty. → THE
   flagship item of this session.
2. **Learning infrastructure (loss capture → diagnosis → training data →
   gated promotion).** Does not exist at all. Spec phases 4-10. → Built as
   `tools/learn/` + `tools/training/`, champion/candidate versioning in
   `networks/`.
3. Search gaps (post-NNUE, each gated by SPRT/match vs champion):
   capture-history, continuation-history (1-ply), check extensions, Probcut,
   corr-hist, SPSA-tunable parameter surface (params are currently
   compile-time constants). Deliberately NOT bundled into the NNUE change so
   every gate stays attributable. → roadmap below.
4. Syzygy probing: currently a deliberate no-op option. TB files are
   multi-GB external downloads; integration is real but optional work,
   gated behind the same correctness tests. → later stage.
5. SPSA/Texel tuning of HCE constants: only after the search parameter
   surface exists; NNUE largely supersedes HCE tuning value. → later stage.

## 3. Prioritized implementation order (this session)

- [x] Phase 1 audit (this document) + baseline gates
- [x] **Stage N1** (DONE) — NNUE inference in C++17 (`engine/nnue/`): HalfKP-style
      dual-perspective feature transformer (40 960→256 int16), incremental
      accumulators per ply (king moves = full refresh), 512→16→1 head,
      fixed-point int math, `UseNNUE`/`EvalFile` UCI options, champion-file
      auto-load (same philosophy as the opening book), `nnuecheck`
      diagnostic for quantisation-parity testing. HCE stays as fallback.
- [x] **Stage N2** (DONE) — Training pipeline (`tools/training/`): self-play data
      generation (seeded, diverse openings, broad set — NOT losses only),
      JSONL schema (fen/result/teacher eval/depth/source/phase/weight),
      numpy trainer with sparse input-layer updates + exact fixed-point
      emulation, train/val split, checkpoints, metrics, `.nnue` export.
- [x] **Stage N3** (DONE - verdict: candidate REJECTED, see below) — Gate #1: quantisation parity test, regression suites,
      then champion-vs-candidate match; promote only on a win.
- [x] **Stage L1** (DONE, demo'd end-to-end) — Loss-learning pipeline (`tools/learn/`): rich game
      recording (PGN+FENs+evals+clocks+versions), critical-position finder,
      teacher analysis (UCI-agnostic; Stockfish supported, deep-Veltrix
      surrogate in this sandbox), loss reports (spec §7 format), failure
      training packs + regression EPD, `learn_loop.py` with promote-only-if-
      stronger gate (old champion always retained).
- [x] Docs (`docs/TRAINING.md`, `docs/LEARNING_LOOP.md`), final gates, commits.

## 3b. Measured end-stage results (this session, all gates run for real)

| Item | Measurement |
|---|---|
| engine test suite | 56/56 PASS (incl. new `go nodes` + loss-EPD checks) |
| `nnuewalk` incremental accumulator check | PASS 47 plies, 0 diffs |
| trainer/engine fixed-point parity | 300/300 EXACT on vectors (when a candidate passes accuracy gates) |
| NNUE NPS cost | 1.50M vs 1.58M HCE (-5.3%) |
| **gate #1: NNUE candidate vs HCE (40 games, movetime 100ms)** | **0-40, twice, two candidates** |
| promotion decision | **REJECTED** - no NNUE champion shipped (rules held) |
| learning-loop demo | full PLAY->...->GATES cycle; honest refusals at quality gates |
| bugs found & fixed by gates | NNUE king-move accumulator desync; `go nodes` <2048 never enforced; gen-data/teaching pipeline defects (documented in TRAINING.md) |

The 0-40 losses are explained honestly in `docs/TRAINING.md`: tiny-sandbox
self-play corpus (25.3k positions of a weak HCE labeller), first-generation
trainer convergence problems (fixed at gradient level but corpus-limited),
and one now-fixed search-accumulator bug. The infrastructure is complete
and verified; net quality needs Stockfish-labelled data and/or more compute,
which is desktop work (`learn_loop.py --teacher ...`), not sandbox work.

### Roadmap after this session (honestly deferred)
capture-history & continuation-history, check extensions, Probcut, SPSA
tuning surface + SPSA runner on the user's machine (needs hundreds of games),
Syzygy probing (needs TB files), NNUE re-training on Stockfish-labelled
positions (user's PC: install Stockfish, set `teacher_engine`).

## 4. Hard rules kept everywhere
No search surgery without a measured gate; champion engine+net are never
overwritten by an unpromoted candidate; no Elo claims without matches;
no third-party code copying (NNUE is an independent implementation after
public research/architecture descriptions; PeSTO already CC0);
C++17 + Windows/MSYS2 + Linux stay buildable; zero new warnings.
