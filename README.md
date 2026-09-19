# Veltrix 1.0

A complete, free chess project:

- **`veltrix` / `veltrix.exe`** — a real, from-scratch **UCI chess engine** in
  C++17 (bitboards, alpha-beta search with modern pruning, tapered hand-crafted
  evaluation, multi-threading, opening book, pondering).
- **`veltrix_gui.py`** — a separate **Python/tkinter GUI** that talks to the
  engine over UCI only (no chess algorithm in the GUI other than rule display).

The engine is original code — it is **not** a renamed Stockfish, contains no
copied engine code, and its strength claims in this document are measured, not
assumed (see *Strength* below).

License: **GPL-3.0-or-later** (see `LICENSE`). Third-party material:
`THIRD_PARTY_NOTICES.md`.

---

## Quick start (Windows, zero-config)

1. **Build the engine** — open a terminal in this folder and run:

   ```bat
   build.bat
   ```

   `build.bat` auto-detects `g++` (MinGW-w64/MSYS2), `clang++`, or MSVC Build
   Tools, compiles with full optimization, and drops `veltrix.exe` into
   `engine\`, `bin\`, and the repo root. Use `build.bat native` for a
   fastest-possible build tuned to your CPU.

   > No compiler yet? Either `winget install -e --id MSYS2.MSYS2` then
   > `pacman -S mingw-w64-ucrt-x86_64-gcc`, or grab "Build Tools for Visual
   > Studio" and run `build.bat` from an *x64 Native Tools Command Prompt*.

2. **Play** — double-click **`run-Veltrix.bat`** (opens the GUI like a normal
   app, no command prompt), or from a terminal:

   ```bat
   python gui\veltrix_gui.py
   ```

   The GUI auto-detects `veltrix.exe` next to itself, then in `engine\` and
   `bin\`. Done — you are playing White against Veltrix.

Step-by-step with screenshots-level detail: **docs/TUTORIAL.md** (recommended
for beginners).

## Quick start (Linux / macOS)

```sh
./build.sh            # or: make -C engine -j$(nproc)  (portable x86-64-v2 + LTO)
python3 gui/veltrix_gui.py
```

Build variants (PART 16 matrix; all defaults stay portable):

| make            | what you get |
|-----------------|--------------|
| `make`          | portable default: `x86-64-v2` (SSE4.2/POPCNT) + LTO + -O3 |
| `make AVX2=1`   | `x86-64-v3` (AVX2/BMI2) for 2015+ CPUs |
| `make NATIVE=1` | `-march=native`, max speed on this machine |
| `make pgo`      | host profile-guided rebuild on top of the portable default; instrument-train-reuse; measured +5-6% NPS with bench node counts identical |
| `make LTO=0`    | developer builds, faster compile |

Windows: `build.bat` / MSYS2 `g++` both work; never assumes AVX2.

## Project layout

```
Veltrix-Chess-bot/
├── engine/               C++17 engine
│   ├── src/              all engine sources (bitboards .. uci)
│   ├── Makefile          POSIX build (g++/clang/clang-cl)
│   └── veltrix           built engine (ELF on Linux; veltrix.exe on Windows)
├── gui/                  Python GUI (UCI client only — no chess search inside)
│   ├── veltrix_gui.py    launcher
│   └── app.py, board_widget.py, dialogs.py, chesslib.py, engine_client.py,
│       config_store.py, theme.py
├── tools/                engine-side utilities
│   ├── match.py          run matches between two engine builds
│   ├── sprt.py           SPRT (elo) test wrapper over match.py
│   ├── epd_test.py       tactical EPD suite runner
│   ├── benchmark.py      nodes/sec benchmark
│   └── engine_driver.py  UCI driver shared by the tools and tests
├── tests/
│   ├── run_tests.py      engine test suite (perft, UCI protocol, playout, ...)
│   ├── tactics.epd       deterministic tactical regression suite
│   ├── gui_headless_test.py  drives the full GUI without a display (tk stub)
│   └── tk_stub.py        headless tkinter replacement used by the test above
├── books/veltrix.bin     small Polyglot opening book (works out of the box)
├── networks/             reserved for NNUE networks (see networks/README.md)
├── build.bat             Windows build (auto-detects compiler)
├── build.sh              Linux/macOS build
├── LICENSE               GPL-3.0-or-later
└── THIRD_PARTY_NOTICES.md
```

## Engine

**Implemented** (all of these were exercised by the test suite — see *Testing*):

- Full UCI: `uci`, `isready`, `ucinewgame`, `setoption`, `position startpos/fen
  ... moves ...`, `go depth|movetime|wtime|btime|winc|binc|movestogo|mate|nodes|
  infinite|searchmoves|ponder`, `stop`, `ponderhit`, `quit`. Debug extras:
  `d`, `perft N`, `eval`, `bench`, `moves`, `key`, `compiler`.
- Search: iterative deepening, PVS, aspiration windows, hash transposition
  table (generation-aged buckets), quiescence (with stand-pat, delta prune,
  checks at low depth), null-move pruning, late move reductions, late move
  pruning, futility/reverse-futility (razoring), SEE pruning in QS and main
  search, check extensions, singular extensions, mate-distance pruning,
  killer/history/countermove ordering, MVV-LVA capture ordering, aspiration
  re-search widening, Multipv, precise mate-score output (`score mate N`).
- Repetition and 50-move-rule aware scores, draw detection.
- Lazy-SMP multithreading (`Threads` up to 64) with thread-unsafe-free
  split of iterative-deepening and shared aging TT.
- Time management: soft/hard limits from remaining time + increment,
  `Move Overhead` accounting, move-time mode, true `infinite`/ponder mode
  with `ponderhit` transition.
- Strength limiting: `UCI_LimitStrength` + `UCI_Elo` (300–2600): depth cap +
  multipv suboptimal-move selection so humans of any level can beat it.
- Hand-crafted evaluation (tapered mg/eg): material, piece-square tables,
  bishop pair, rook open/semi files, passed/isolated/doubled/backward pawns,
  pawn-hash, king-safety scoring with pawn shields + attack units, mobility,
  knight/bishop outposts, space.
- Opening book (`UseBook`, `BookFile`, Polyglot `.bin`), selection *without*
  hashing the book each move (incremental polyglot key), works identically in
  the GUI. Built by `tools/build_opening_book.py`, which merges three sources:
  hand-curated main lines, the engine's own MultiPV-verified expansion over
  plausible human replies, and (optionally) any external ECO/opening TSV files
  you supply via `--eco-tsv` (e.g. the CC0 lichess-org/chess-openings corpus,
  which you can download separately - SAN is parsed and legality-checked by
  the project's own chesslib, so nothing dubious enters the book).
- `SyzygyPath` is accepted with a friendly `info string` note as a graceful
  no-op (tablebase probing is intentionally out of scope; the option is there
  so guis/scripts that always send it keep working).

Additional niche UCI extensions: `go mate N`, `go nodes N`, `go searchmoves`.

### UCI options

| Option | Type | Default | Notes |
|---|---|---|---|
| `Hash` | spin 1–8192 | 128 | transposition table, MB |
| `Threads` | spin 1–64 | 1 | search threads (lazy SMP) |
| `MultiPV` | spin 1–128 | 1 | principal variations displayed |
| `Ponder` | check | false | pondering on opponent's time |
| `Move Overhead` | spin 0–1000 | 30 | ms safety buffer per move |
| `UseBook` | check | true | use the opening book (`OwnBook` accepted as an alias). With no explicit `BookFile`, the engine auto-loads a Polyglot `.bin` found next to the executable / in `../books/` |
| `BookFile` | string | (empty) | Polyglot `.bin`; overrides auto-detection |
| `SyzygyPath` | string | (empty) | accepted, graceful no-op with a note |
| `UCI_LimitStrength` | check | false | enable the Elo limiter |
| `UCI_Elo` | spin 1350–2850 | 2600 | capped strength when limiting |

## GUI

- Click-to-move with legal-target hints, last-move and check highlights,
  move-list clock, captured-pieces tray, promotion dialog, score graph*.\* *(
  score graph shown if engine info enabled.)*
- Modes: White / Black / Random vs engine, and **Engine vs Engine**.
- Clocks: 1+0, 1+1, 3+0, 3+2, 5+0, 5+3, 10+0, 10+5, 15+10, 30+0, **custom
  per-side** (separate minutes/increments for White and Black) and
  **unlimited** (fixed engine move time instead).
- FEN copy/paste, PGN save/load, navigation through the game, flip board,
  coordinates toggle, board size and color themes (8 presets), highlight
  toggles, engine path auto-detect with manual override in Settings → Engine.
- Settings persist to `%APPDATA%\Veltrix\config.json` (Windows) or
  `~/.config/veltrix/config.json` (Linux/macOS).
- The engine is shut down cleanly (`quit`) when the window closes.

The GUI contains **no search algorithm** — the only chess logic inside it is
rules/move-legality for display purposes; all play strength comes from
`veltrix.exe` over UCI.

### Engine path configuration

The GUI auto-detects the engine in this order (first hit wins):
`gui/veltrix(.exe)` → repo-root `veltrix(.exe)` → `bin/` → `engine/` →
`$PATH`. Override with menu **Settings → Engine…** (stored in the config
file), or set `VELTRIX_ENGINE=/path/to/veltrix`.

## Tools (all runnable with any Python 3.9+, engine built)

```bat
python tools\benchmark.py                        :: nodes/sec benchmark
python tools\epd_test.py --file tests\tactics.epd --depth 12
python tools\match.py --engines engine\veltrix "build-prior\veltrix.exe" --games 40 --tc 40/0.3
python tools\sprt.py --help                      :: Elo test between builds
```

## Testing

```bat
python tests\run_tests.py            :: engine suite: perft, UCI, mates, playout, options, bench
python tests\gui_headless_test.py    :: drives the real GUI logic (display-free tkinter stub)
```

Last run (Linux dev container, 2026-09): **53/53 engine tests passed**,
**41/41 GUI checks passed** (incl. flip-mapping, board-size application and
two-tone piece rendering), tactical regression suite **7/7 deterministic**
at depth 12, opening book **1650 entries** (curated + engine-verified
expansion).

> Note: the GUI itself was validated *logically* via a headless tkinter stub
> in CI; visual look-and-feel must be eyeballed on a real machine (it is
> deliberately plain tkinter and renders identically on Windows/Linux/macOS).

## Strength — measured, not assumed

What was actually measured (Linux x86-64 sandbox, **2 CPU cores**, GCC,
`-O3 -march=x86-64-v2`, 2026-09):

- **Perft**: all reference node counts pass exactly (startpos d6 =
  119,060,324; Kiwipete d5 = 193,690,690; ep/pins, promotion and
  semi-open-trick suites) — the move generator has never produced an illegal
  move in these tests, nor in several hundred self-play games during
  development.
- **Tactics**: the shipped regression suite (`tests/tactics.epd`, depth 12)
  passes 7/7 **deterministically**, including forced-mate conversions (K+R,
  K+R+R, K+Q+R always delivered within strict ply bounds, verified by playing
  the engine against itself from an advantage).
- **Benchmark (`bench 12`)**: ~1.79 Mnps on 1 thread, ~3.28 Mnps on 4
  logical cores of this low-end sandbox host (nps scales nearly linearly
  with hardware; on a modern desktop CPU expect several Mnps/core).
- **SPRT tooling**: verified mechanically (games play out, W/D/L statistics,
  LLR, alternating colours, PGN logging) — use it to compare YOUR builds:

  ```sh
  python tools/sprt.py --base engine-prior --test engine-now --tc 120/0.2 --max-games 400
  python tools/match.py --engines engine/veltrix other-build/veltrix --games 40 --tc 40/0.3
  ```

What we deliberately **don't** claim: **an Elo number.** No CCRL/CEGT rating
exists for Veltrix, and we refuse to print a guessed one. If you need a
ballpark, run an SPRT against a rated reference engine on your own hardware
and share the result.

## Experimental / unfinished

- NNUE evaluation (VNN1): implemented in C++ with incremental accumulators
  (+5.3% NPS), UCI options `UseNNUE` + `EvalFile`, auto-load of
  `networks/champion.nnue`. **No champion net ships yet**: the first trained
  candidates were measured and honestly REJECTED by the strength gate (see
  `docs/TRAINING.md` and `docs/LEARNING_LOOP.md` for the full pipeline,
  measured results, and how to retrain on your PC incl. Stockfish teacher
  support). Without a net, Veltrix runs pure HCE exactly as before.
- `SyzygyPath` — accepted but unprobed (see UCI options above).
- MultiPV is limited to 5 PVs; `go mate`/`nodes` are convenience extras.

## License & credits

GPL-3.0-or-later — see `LICENSE`. Third-party constants (Polyglot table,
PeSTO-derived PSTs, public-domain search techniques) are documented in
`THIRD_PARTY_NOTICES.md`. Copyright (C) 2026 Veltrix Project.
