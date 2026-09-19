# Veltrix 1.0 — Step-by-Step Tutorial for Beginners

This tutorial assumes **zero prior experience** with chess engines or
compilers. Follow the steps in order. Windows is the primary path; Linux/macOS
notes are marked with 🐧.

You will need:

- A Windows 10/11 PC (or Linux/macOS machine)
- Admin rights *only* if you choose to install a compiler/Python
- About 15 minutes

---

## Step 1 — Get the Veltrix files

You already have this folder (`Veltrix-Chess-bot`). Keep it somewhere easy,
e.g. `C:\Veltrix` or your Desktop. We'll call it "your Veltrix folder".

## Step 2 — Install Python (needed for the GUI and tools)

1. Go to <https://www.python.org/downloads/> and click **Download Python 3.x**.
2. Run the installer. **Important:** on the first screen tick
   **"Add python.exe to PATH"**, then click *Install Now*.
3. Verify: press **Win+R**, type `cmd`, press Enter, then type:

   ```bat
   python --version
   ```

   You should see `Python 3.9` or newer. If it says "'python' is not
   recognized", reinstall and make sure the PATH box was ticked.

> 🐧 Linux: `sudo apt install python3 python3-tk` (Debian/Ubuntu) or the
> equivalent — macOS: install from python.org (tkinter is included).

## Step 3 — Build the engine (`veltrix.exe`)

The engine is written in C++ and must be **compiled** once. You need one
C++ compiler. Pick ONE of the options below.

### Option A — MSYS2/MinGW (recommended, free)

1. Press **Win+R**, type `cmd`, Enter, then run:

   ```bat
   winget install -e --id MSYS2.MSYS2
   ```

2. Open the app **"MSYS2 UCRT64"** (Start menu) and type:

   ```sh
   pacman -S --noconfirm mingw-w64-ucrt-x86_64-gcc
   ```

3. Still in the "MSYS2 UCRT64" window, go to your Veltrix folder and build:

   ```sh
   cd /c/Veltrix        # adjust path!
   ./build.sh
   ```

   *(Or, in an ordinary `cmd` window where `g++` is on PATH, run `build.bat`.)*

### Option B — Visual Studio Build Tools

1. Install "Build Tools for Visual Studio" from
   <https://visualstudio.microsoft.com/visual-cpp-build-tools/>
   (select the *Desktop development with C++* workload).
2. From the Start menu open **"x64 Native Tools Command Prompt for VS 2022"**.
3. In that window:

   ```bat
   cd /d C:\Veltrix
   build.bat
   ```

### What success looks like

```
SUCCESS: engine\veltrix.exe
        (also copied to veltrix.exe and bin\veltrix.exe)
```

**Test it:** in the same folder, run `veltrix.exe`, then type `uci` and press
Enter. It answers with `id name Veltrix 1.0`, a list of options, and
`uciok`. Type `quit` to exit. **The engine is built!** 🎉

> Antivirus caution: compiling your own exe sometimes triggers a Defender
> warning for unsigned files. The sources are in `engine\src\` for inspection;
> mark `veltrix.exe` as safe in your AV if needed.

> 🐧 Linux/macOS: `chmod +x build.sh && ./build.sh` (or
> `make -C engine -j"$(nproc)" NATIVE=1` for a max-speed build).

## Step 4 — Play your first game against the engine

1. Open `cmd` in your Veltrix folder (Explorer address bar → type `cmd`).
2. Run:

   ```bat
   python gui\veltrix_gui.py
   ```

3. The window opens with a board, clocks, move list and status bar.
   **You are White; Veltrix is Black** and already connected (see the status
   bar: "Engine: Veltrix 1.0").
4. **Move by clicking:** click your piece (it lights up and legal destination
   squares show dots), then click the destination square.
   Illegal moves are simply ignored.
5. If a pawn reaches the last rank, a small dialog asks which piece to
   promote to.
6. When you lose: **File → New game** starts over instantly.

Useful menu items while playing:

- **Game → New game as Black** — the engine plays White.
- **Game → Engine vs Engine** — two Veltrix instances play each other; great
  for learning openings. Click **Stop** to end.
- **Game → Flip board** (short: toolbar button ⟳).
- **File → Load FEN** — paste a position from anywhere.
- **File → Save PGN / Load PGN** — archive and review games.

## Step 5 — Match the engine to your level

Default Veltrix is far too strong for a beginner. Turn it down:

1. Menu **Settings → Engine…**
2. Tick **Limit strength (UCI_LimitStrength)** and slide **Elo** to, say,
   `900`. Press OK.
3. New game. You'll notice level-appropriate mistakes — beatable play.

Gradually raise the slider. The setting is saved, so it survives restarts.

## Step 6 — Clocks and time controls

Menu **Game → Time control…** offers presets:

| Preset | Meaning |
|---|---|
| 1+0 / 1+1 | bullet: 1 minute (the second adds 1 s per move) |
| 3+0 / 3+2 | blitz |
| 5+0 / 5+3 | fast blitz |
| 10+0 / 10+5 / 15+10 / 30+0 | slow play |
| **Custom…** | different clocks for White and Black — e.g. give yourself 30 min and the engine 1 min to equalize chances! |
| **Unlimited** | engine moves after a fixed think time (Settings → Engine → Move time, ms) |

The engines in Engine-vs-Engine mode use the same clocks.

## Step 7 — Reviewing your game

- The **move list** on the right: click any move to jump to that position on
  the board; `<`/`>` buttons (or the list itself) step through the game.
- **Utils → Copy FEN** copies the current position; send it to friends or to
  a website analyzer.
- **File → Save PGN** writes a standard `.pgn` file readable by every chess
  program (Lichess, ChessBase, chess.com import…).

## Step 8 — Make it pretty

Menu **Settings → Appearance…**:

- 8 board themes (Classic wood, Blue Grey, Forest, Sand, Slate, Rosewood,
  Mono, Night) — or paint your own light/dark square colors.
- Board size, show/hide coordinates, last-move/check/target highlights.

## Step 9 — (Optional) Run the test suite

Feeling nerdy? In `cmd` from your Veltrix folder:

```bat
python tests\run_tests.py
```

You should finish with `RESULT: 53 passed, 0 failed`. This verifies the engine
never makes illegal moves (perft), speaks perfect UCI, converts forced mates,
and runs the benchmark.

## Troubleshooting

| Symptom | Fix |
|---|---|
| `python` not recognized | Re-run the Python installer with "Add to PATH" ticked |
| GUI says "engine not found" | Build step 3 first; check that `veltrix.exe` sits in the repo root, `bin\` or `engine\`. Or set the path manually: Settings → Engine… |
| GUI window opens but engine never moves | Settings → Engine… → use the built-in "auto-detect" result; check the status-bar text |
| `build.bat` says "No C++ compiler found" | Complete Step 3 Option A or B exactly |
| Antivirus quarantines `veltrix.exe` | Restore/allow it; source code is in `engine\src\` |
| Engine plays too strongly | Settings → Engine → Limit strength + lower Elo |

## Where to go next

- `README.md` — full feature list, UCI options, strength statement.
- `tools/epd_test.py` — feed the engine tactical puzzles.
- `tools/match.py` / `tools/sprt.py` — compare two engine builds.
- `engine/src/` — the engine source code, commented for study.

## The learning loop (optional, for the curious)

Veltrix can review its own games, figure out *why* it lost, and train an
improved evaluation from the verdicts — with Stockfish as the teacher if you
have one installed (any UCI engine works):

```bash
python3 tools/learn/learn_loop.py --iters 4 --games 32 --movetime 200 \
    --teacher /path/to/stockfish
```

Read `docs/LEARNING_LOOP.md` first. The loop can only promote a new
evaluation after it passes regression tests *and* wins matches against the
current engine - a weaker candidate is always rejected, and your champion is
never overwritten without proof.
