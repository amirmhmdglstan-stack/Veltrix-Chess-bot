# Veltrix Learning Loop

Veltrix has an **automated learning loop** (`tools/learn/`) that follows this
cycle, end to end, without any manual steps:

```
PLAY  -> games vs itself (every ply recorded: fen, move, eval, depth, time)
LOSS  -> decisive games are isolated
SAVE  -> games.jsonl kept forever (append-only, resumable)
CRITICAL -> find the plies where the loser's eval collapsed
ANALYSIS -> a teacher engine judges the critical positions
DIAGNOSE -> markdown report: WHY the game was lost (spec format)
TRAIN DATA -> teacher-labelled, severity-weighted NNUE training rows
TRAIN  -> a candidate net (never overwrites the champion)
REGRESSION -> engine parity + tactics + past-loss EPD must pass
MATCHES -> candidate vs champion under time control
PROMOTE -> ONLY if the candidate wins; old champion archived, never deleted
```

## What is learned automatically vs. manual

| Automatic | Manual (never automated) |
|---|---|
| game generation, critical-position mining | changing engine code |
| teacher labelling + severity weights | editing training data by hand |
| NNUE training (data -> candidate net) | promoting a net to champion |
| regression EPD (`tests/loss_regression.epd`) | search surgery (has own gates) |
| loss report generation | final promotion decision (gates decide) |

Veltrix never trains on *memorised moves*. The loop records **positions with a
target evaluation** (teacher's judgement) and a weight - the NNUE learns the
static features of the position, which generalises to other positions. A FEN
to move database is explicitly NOT used for playing.

## Teacher engine

Stockfish (or any strong UCI engine) is a **teacher/analyser only**:
it labels losses, never plays for Veltrix, and its code/binary is never
shipped as part of Veltrix. Configure it as:

```bash
python3 tools/learn/learn_loop.py --teacher /path/to/stockfish --iters 4
```

If no teacher is given, the loop uses **Veltrix itself at a much longer
think** as a weak surrogate ("self-teacher"), clearly labelled in the data.
Self-teacher rows are weighted 40% lower and exist so the loop can run on an
offline PC; they are a fallback, not a substitute for Stockfish analysis.

## One command

```bash
# Windows (MSYS2 UCRT64) or Linux:
python3 tools/learn/learn_loop.py \
    --iters 4 --games 32 --movetime 200 \
    --teacher /path/to/stockfish \
    --match-games 80
```

Each iteration takes roughly (games x movetime x ~90 plies) for self-play,
~1 min for analysis, ~1-4 min for training, and (match-games x movetime x 90)
for the gate match.

The loop is resumable and safe to Ctrl-C: everything lives in
`data/learn/` + `networks/`, and a partially finished iteration just restarts.

## Outputs to read

- `data/learn/loss_report_iterNNN.md` - per-loss "why" report
  (critical position, evaluation before/after, teacher best + PV, category
  from a fixed list, likely root cause, learning action).
- `tests/loss_regression.epd` - positions from real losses. The engine must
  not repeat the same losing move here forever; `tests/run_tests.py` and the
  promotion gate both consume it.
- `data/learn/promote_log.jsonl` - every gate run: parity, tactics, EPD,
  match score, verdict (PROMOTED / REJECT reason + gate that failed).
- `networks/CHAMPION.json` - promotion lineage (what was promoted when, with
  which metrics and gate results).
- `networks/history/` - archived old champions (roll back = copy any file
  over `networks/champion.nnue`).

## Gates (why a candidate can be refused)

`tools/learn/promote.py` refuses promotion unless ALL of these hold:

1. **Exact parity**: the engine computes the trainer's fixed-point forward
   pass bit-identically on `tests/nnue_vectors.txt` (300 vectors).
2. **Tactics**: `tests/run_tests.py` tactical suite stays green, and the
   loss-regression EPD does not get worse than the champion.
3. **Strength**: candidate vs champion match (fixed games or `--sprt`).
   Promotion requires score >= 52.5% (or SPRT H1 acceptance).

A candidate that fails any gate is documented + kept in
`networks/candidates/`; the champion binary/net are not touched.
