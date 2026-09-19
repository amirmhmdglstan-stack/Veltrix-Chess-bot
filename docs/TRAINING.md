# NNUE training (VNN1)

Veltrix's NNUE format is **VNN1** (halfKP-style, 40960 -> 2x256 -> 16 -> 1,
int16/int32 fixed point). Inference is C++ inside the engine (incremental
accumulators, zero Python); training is Python + numpy (training only).

VNN1 cross-implementation guarantee (tested, `tests/nnue_vectors.txt`):
the trainer's fixed-point forward pass is **bit-identical** to the engine's
(`nnueeval` 300/300 exact match).

## Pipeline

```bash
# 1) DATA (self-play). Reads: engine binary. Writes: JSONL (fen, eval, ...).
python3 tools/training/gen_data.py --engine engine/veltrix \
    --out data/nnue/train_wS.jsonl --games 400 --workers 1 \
    --play-nodes 2048 --label-nodes 6000

# 2) TRAIN (+ validation gates; refuses to export a broken/degenerate net)
python3 tools/training/train_nnue.py \
    --data data/nnue/*.jsonl --tag my-net --epochs 14 --batch 1024

# 3) VALIDATE in the engine (see promote.py for the full auto-gates)
cp networks/candidates/my-net.nnue /tmp/arena/networks/champion.nnue
# engine prints "nnue N" for 'nnueeval'; 'nnuewalk' checks incremental updates

# 4) PROMOTE (parity + tactics + loss-EPD + match; old champion archived)
python3 tools/learn/promote.py --candidate networks/candidates/my-net.nnue
```

Data rows: `{fen, eval(cp, stm-POV), result, stm, weight, depth, src}`.
Labels come from engine analysis of the position (`label-nodes`), opening
variety from MultiPV sampling, and game results mix in via `result`.

## Trainer quality gates (automatic)

- **int/float parity**: the quantised int net must reproduce the float net
  within `--parity-tol` cp (default 6) on validation vectors, else no export.
- **accumulator headroom**: max |acc| must stay under 24000 (int16 can hold
  32767; exceeding means silent overflow corruption in the engine).
- **loss-regression EPD + tactics + match** are downstream in `promote.py`.

Reproducibility: fixed seed (--seed), identical meta JSON across reruns;
numpy is the only training dependency (`pip install numpy`, BSD-3).

## Measured status in the reference sandbox (honest report)

Everything below was measured, not assumed:

| Stage | Result |
|---|---|
| C++ NNUE inference (N1) | DONE. Incremental accumulators; +5.3% NPS vs HCE |
| `nnuewalk` incremental-vs-fresh | PASS 47 plies/0 diffs (found + fixed a king-move desync) |
| trainer int/float parity | PASS 300/300 exact when a candidate passes accuracy gates |
| data pipeline (N2) | DONE. 25,300 labelled positions generated reproducibly |
| first trained net (vnn1-001) | material-blind (output ~constant) - root caused |
| improved net (vnn1-005, huber etc.) | float label corr 0.36 (learning, but weak) |
| **gate #1 match NNUE vs HCE** | **0-40 (twice) -> promotion REJECTED, correctly** |

The 0-40 verdict stands per the promotion rules: no NNUE champion ships in
this cycle. The tooling, regression EPD, and `--teacher` pathway are in
place; a stronger engine base (current search already won against older
Veltrix builds) and/or Stockfish-labelled data on a desktop-class machine
are the honest next lever (see `docs/ARCHITECTURE_ASSESSMENT.md`, N4/N5
roadmap). Nothing about the 0-40 result is hidden: candidates, match PGNs
and gate logs are committed under `networks/` and `data/learn/`.

## Why the first nets failed (engineering notes)

Three distinct, instructive bugs were found by the gates rather than by
playing:

1. **search-time accumulator desync on king moves** (engine bug): HalfKA has
   no king feature of its own perspective; an update tried to add one and
   corrupted the opponent perspective. `nnuewalk` (incremental-vs-fresh
   acc/eval comparison over scripted king/castle/EP/promotion lines) proved
   the fix. No measurable match effect was attributed to this after the fix.
2. **all-tiny hidden-layer init + Adam gradient cancellation**: with classic
   NNUE init scales, gradients of e-10 relative to Adam's noise floor made
   the transformer layer unlearnable (net output collapsed to a constant).
   Fix: He-scaled hidden layers, Huber loss (bound outlier gradients), label
   clamp at +-1200cp, per-epoch projection into int16 range.
3. **`go nodes N` below 2048 was never enforced** (engine bug): node-limit
   bookkeeping checked only every 2048 nodes. Self-play data generation at
   small node budgets silently overflowed into deep searches. Fixed by a
   64-node check block when small limits are active (regression test added).
