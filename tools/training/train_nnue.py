#!/usr/bin/env python3
"""
train_nnue.py - Veltrix NNUE (VNN1) trainer.

Trains the exact architecture implemented in engine/src/nnue.cpp:

    per perspective: 40960 sparse features -> 256-int16 accumulator (bias+rows)
    act  = clipReLU([acc_stm ; acc_enemy], 0..127)          (512)
    act2 = clipReLU((fc1Bias + W1 @ act) >> 6, 0..127)      (16)
    cp   = (outBias + W2 @ act2) >> 6                       (centipawns, stm POV)

Training is float32 (MSE vs teacher cp, per-sample weights, Adam); export is
exactly quantised (FT x127, hidden x64) and verified by an int-precision
emulation that mirrors engine/src/nnue.cpp bit-for-bit (max |int-float|
reported; export refuses to proceed above --parity-tol cp).

Inputs : JSONL files from gen_data.py / tools/learn/ (fen,eval,stm,weight,src)
Outputs: networks/candidates/<tag>.nnue + tests/nnue_vectors.txt parity set
         + training metrics printed as JSON line for the pipeline logs.

Requires numpy (only training dependency; the engine itself never needs it).
"""
import argparse
import glob
import json
import os
import struct
import sys
import time

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(REPO, "gui"))

import numpy as np                   # noqa: E402
import chesslib                      # noqa: E402

NUM_INPUTS, H1, H2 = 40960, 256, 16
# Fixed-point scheme (float train -> exact int inference):
#   acc_i      = 127 * acc_f            (ft weights x127, clamped 0..127)
#   act_i      = 127 * act_f
#   y1_i       = 8128 * y1_f            (fc1 bias x8128, fc1 weights x64,
#                                        because act_i is 127*act_f)
#   act2_i     = (y1_i >> 6) clamped    = 127 * act2_f
#   out_i>>6   = cp                     (out bias x64*x600, out weights
#                                        x64*x600/127)
FT_SCALE = 127.0
FC1_SCALE, FC1_BIAS_SCALE = 64.0, 64.0 * 127.0
OUT_SCALE, OUT_BIAS_SCALE = 64.0 * 600.0 / 127.0, 64.0 * 600.0
ACT_MAX_INT = 127
ACT_MAX = 1.0          # float-space activation clamp (== 127/127)
EVAL_NORM = 600.0
MAX_CP = 1200.0   # bounded: cp-mate outliers poison batch statistics
MAX_FC_WEIGHT = 8192  # mirrors the engine load-time clamp


# ----------------------------------------------------------- data loading ----
PTYPE = {"P": 0, "N": 1, "B": 2, "R": 3, "Q": 4, "K": 5,
         "p": 0, "n": 1, "b": 2, "r": 3, "q": 4, "k": 5}


def features_from_board(board, stm):
    """(feat_us, feat_them) sparse feature lists mirroring engine nnue.cpp."""
    squares = board.board
    ksq = {"w": None, "b": None}
    pieces = []
    for sq, pc in enumerate(squares):
        if pc == ".":
            continue
        if pc == "K":
            ksq["w"] = sq
        elif pc == "k":
            ksq["b"] = sq
        else:
            pieces.append((pc, sq))
    feats = [[], []]  # index by pov 0=white,1=black
    for pov in (0, 1):
        povc = "w" if pov == 0 else "b"
        k = ksq[povc] if pov == 0 else ksq["b"] ^ 63
        for pc, sq in pieces:
            color = "w" if pc.isupper() else "b"
            cls = (0 if color == povc else 5) + PTYPE[pc]
            s = sq if pov == 0 else sq ^ 63
            feats[pov].append(k * 640 + cls * 64 + s)
    us = 0 if stm == "w" else 1
    return feats[us], feats[us ^ 1]


def load_rows(paths, max_rows=0):
    rows = []
    for pat in paths:
        for p in sorted(glob.glob(pat)):
            with open(p, "r", encoding="utf-8") as f:
                for ln in f:
                    ln = ln.strip()
                    if not ln:
                        continue
                    rows.append(json.loads(ln))
                    if max_rows and len(rows) >= max_rows:
                        return rows
    return rows


# ------------------------------------------------------------------- net -----
class Net:
    def __init__(self, rng, label_mean=0.0):
        self.ftB = np.zeros(H1, np.float32)
        self.ftW = (rng.standard_normal((NUM_INPUTS, H1)) * 0.01).astype(np.float32)
        self.fc1B = np.zeros(H2, np.float32)
        # larger-than-He init on the hidden layers: with tiny init the chain of
        # sigmas (outW ~0.01 x fc1W ~0.06) leaves the FT layer with e-10-scale
        # gradients, which Adam can never turn into directional signal
        self.fc1W = (rng.standard_normal((H2, 2 * H1)) * 0.25).astype(np.float32)
        self.outB = np.float32(label_mean)   # pre-fit the (big) mean offset
        self.outW = (rng.standard_normal(H2) * 0.35).astype(np.float32)


class Adam:
    def __init__(self, params, lr=1e-3, beta1=0.9, beta2=0.999, eps=1e-8):
        self.p = params
        self.m = [np.zeros_like(x) for x in params]
        self.v = [np.zeros_like(x) for x in params]
        self.lr, self.b1, self.b2, self.eps, self.t = lr, beta1, beta2, eps, 0

    def step(self, grads, clip=None):
        self.t += 1
        for i, (p, g) in enumerate(zip(self.p, grads)):
            if clip is not None:
                np.clip(g, -clip, clip, out=g)
            self.m[i] = self.b1 * self.m[i] + (1 - self.b1) * g
            self.v[i] = self.b2 * self.v[i] + (1 - self.b2) * (g * g)
            mh = self.m[i] / (1 - self.b1 ** self.t)
            vh = self.v[i] / (1 - self.b2 ** self.t)
            p -= self.lr * mh / (np.sqrt(vh) + self.eps)


def quantize(net):
    """Exact fixed-point conversion mirroring engine/src/nnue.cpp."""
    q = {}
    q["ftB"] = np.clip(np.round(net.ftB * FT_SCALE), -32768, 32767).astype(np.int16)
    q["ftW"] = np.clip(np.round(net.ftW * FT_SCALE), -32768, 32767).astype(np.int16)
    q["fc1B"] = np.clip(np.round(net.fc1B * FC1_BIAS_SCALE), -2**31, 2**31 - 1).astype(np.int32)
    q["fc1W"] = np.clip(np.round(net.fc1W * FC1_SCALE), -MAX_FC_WEIGHT, MAX_FC_WEIGHT).astype(np.int16)
    q["outB"] = np.int32(np.clip(np.round(float(net.outB) * OUT_BIAS_SCALE), -2**31, 2**31 - 1))
    q["outW"] = np.clip(np.round(net.outW * OUT_SCALE), -MAX_FC_WEIGHT, MAX_FC_WEIGHT).astype(np.int16)
    return q


def int_eval(q, f_us, f_them, wrap_i16):
    """Bit-faithful emulation of NNUE::evaluate (int16 accum + >>6 shifts)."""
    acc0 = wrap_i16(q["ftB"].astype(np.int64) + q["ftW"][f_us].sum(axis=0).astype(np.int64))
    acc1 = wrap_i16(q["ftB"].astype(np.int64) + q["ftW"][f_them].sum(axis=0).astype(np.int64))
    act = np.concatenate([np.clip(acc0, 0, ACT_MAX_INT), np.clip(acc1, 0, ACT_MAX_INT)]).astype(np.int64)
    y1 = q["fc1B"].astype(np.int64) + (q["fc1W"].astype(np.int64) @ act)
    act2 = np.clip(y1 >> 6, 0, ACT_MAX_INT)
    out = int(q["outB"]) + int((q["outW"].astype(np.int64) @ act2))
    return out >> 6


def wrap16(x):
    return ((x + 2 ** 15) % 2 ** 16) - 2 ** 15


# --------------------------------------------------------------- training ----
def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data", nargs="+", required=True, help="JSONL files/globs")
    ap.add_argument("--tag", default="vnn1-net")
    ap.add_argument("--out-dir", default=os.path.join(REPO, "networks", "candidates"))
    ap.add_argument("--epochs", type=int, default=5)
    ap.add_argument("--batch", type=int, default=8192)
    ap.add_argument("--lr", type=float, default=1e-3)
    ap.add_argument("--l2", type=float, default=1e-7, help="hidden layers only")
    ap.add_argument("--huber", type=float, default=0.5,
                    help="Huber delta in normalised units (0.5 = 300cp)")
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--val-frac", type=float, default=0.05)
    ap.add_argument("--max-rows", type=int, default=0)
    ap.add_argument("--parity-tol", type=float, default=6.0,
                    help="max allowed mean |int-float| cp before export")
    ap.add_argument("--vectors", type=int, default=200)
    ap.add_argument("--init-from", default="", help="resume from a .nnue file")
    args = ap.parse_args()

    rng = np.random.default_rng(args.seed)
    rows = load_rows(args.data, args.max_rows)
    if not rows:
        raise SystemExit("no training rows found")
    print(f"[train] {len(rows)} rows loaded", flush=True)

    # featurise (CSR: flat feature index arrays + per-row offsets) ------------
    t0 = time.time()
    F_us, F_them, E, Wt = [], [], [], []
    for r in rows:
        b = chesslib.Board(r["fen"])
        us, them = features_from_board(b, r.get("stm", b.stm))
        F_us.append(us)
        F_them.append(them)
        E.append(np.clip(float(r["eval"]), -MAX_CP, MAX_CP))
        Wt.append(float(r.get("weight", 1.0)))
    E = np.array(E, np.float32)
    Wt = np.array(Wt, np.float32)
    # CSR form lets both forward and backward run with a single np.add.at
    u_cnt = np.array([len(x) for x in F_us], np.int64)
    t_cnt = np.array([len(x) for x in F_them], np.int64)
    u_ptr = np.concatenate([[0], np.cumsum(u_cnt)])
    t_ptr = np.concatenate([[0], np.cumsum(t_cnt)])
    u_flat = np.array([f for x in F_us for f in x], np.int64)
    t_flat = np.array([f for x in F_them for f in x], np.int64)
    print(f"[train] featurised in {time.time() - t0:.1f}s", flush=True)

    idx = np.arange(len(rows))
    rng.shuffle(idx)
    nval = int(len(rows) * args.val_frac)
    val_i, tr_i = idx[:nval], idx[nval:]

    # net + optimizer ---------------------------------------------------------
    net = Net(rng, label_mean=float(E.mean()) / EVAL_NORM)
    if args.init_from:
        q = load_nnue(args.init_from)
        net.ftB = q["ftB"].astype(np.float32) / FT_SCALE
        net.ftW = q["ftW"].astype(np.float32) / FT_SCALE
        net.fc1B = q["fc1B"].astype(np.float32) / FC_SCALE
        net.fc1W = q["fc1W"].astype(np.float32) / FC_SCALE
        net.outB = np.float32(q["outB"]) / FC_SCALE
        net.outW = q["outW"].astype(np.float32) / FC_SCALE
        print(f"[train] warm start from {args.init_from}", flush=True)

    params = [net.ftB, net.ftW, net.fc1B, net.fc1W,
              np.atleast_1d(net.outB), net.outW]
    opt = Adam(params, lr=args.lr)
    params[4] = params[4]

    def csr_select(ptr, flat, ii):
        """(seg_row_in_batch, flat_feature_idx) for rows ii of CSR storage."""
        starts = ptr[ii]
        lens = ptr[ii + 1] - starts
        seg = np.repeat(np.arange(len(ii)), lens)
        ar = np.arange(int(lens.sum()))
        rowoff = np.cumsum(lens) - lens      # each row's offset in the concat
        offs = ar - rowoff[seg]              # position within own row
        return seg, flat[starts[seg] + offs]

    def forward_batch(ii):
        acc = np.zeros((len(ii), 2 * H1), np.float32)
        seg, fid = csr_select(u_ptr, u_flat, ii)
        acc[:, :H1] = net.ftB
        np.add.at(acc[:, :H1], seg, net.ftW[fid])
        acc[:, H1:] = net.ftB
        seg2, fid2 = csr_select(t_ptr, t_flat, ii)
        np.add.at(acc[:, H1:], seg2, net.ftW[fid2])
        act = np.clip(acc, 0.0, ACT_MAX)
        y1 = net.fc1B[None, :] + act @ net.fc1W.T
        act2 = np.clip(y1, 0.0, ACT_MAX)
        out = params[4][0] + act2 @ net.outW   # params[4] is the Adam-live copy
        return out, act, act2, acc, y1

    nb = max(1, len(tr_i) // args.batch)
    step = 0
    for ep in range(args.epochs):
        ep_perm = rng.permutation(tr_i)
        ep_loss = 0.0
        for bno in range(nb):
            ii = ep_perm[bno * args.batch:(bno + 1) * args.batch]
            out, act, act2, acc, y1 = forward_batch(ii)
            tgt = (E[ii] / EVAL_NORM)[:, None]
            w = (Wt[ii] / Wt[ii].mean())[:, None]
            err = (out[:, None] / EVAL_NORM - tgt)
            # Huber loss (delta in normalised units): quadratic in-delta,
            # linear outside. Without this, the clamped mate-ish labels
            # (+-MAX_CP outliers) dominate every batch and the running
            # gradient means cancel: Adam then just wanders around init.
            huber = args.huber
            ae = np.abs(err)
            quad = ae <= huber
            loss_f = float((w * np.where(quad, err ** 2,
                                         huber * (2 * ae - huber))).mean())
            ep_loss += loss_f
            gerr = np.where(quad, err, huber * np.sign(err))   # dL/dout units

            # ------- backward (float, mirror of the forward clip masks) ------
            b = len(ii)
            d_out = (1.0 / (EVAL_NORM * b)) * w * gerr         # b,1
            g_outW = (d_out * act2).mean(axis=0) * b
            g_outB = np.atleast_1d(d_out.mean() * b).astype(np.float32)
            d_act2 = d_out @ net.outW[None, :]
            d_y1 = d_act2 * (y1 > 0) * (y1 < ACT_MAX)
            g_fc1W = (d_y1.T @ act) / b + args.l2 * net.fc1W
            g_fc1B = d_y1.mean(axis=0) * b
            d_act = d_y1 @ net.fc1W
            d_acc = d_act * (acc > 0) * (acc < ACT_MAX)
            g_ftB = d_acc[:, :H1].mean(axis=0) * b + d_acc[:, H1:].mean(axis=0) * b
            g_ftW = np.zeros_like(net.ftW)  # filled sparsely below
            lr_now = args.lr * (1.0 - 0.7 * (step / max(1, nb * args.epochs)))
            opt.lr = lr_now
            # sparse FTW gradient: one vectorised scatter-add per perspective
            seg_u, fid_u = csr_select(u_ptr, u_flat, ii)
            np.add.at(g_ftW, fid_u, d_acc[seg_u, :H1])
            seg_t, fid_t = csr_select(t_ptr, t_flat, ii)
            np.add.at(g_ftW, fid_t, d_acc[seg_t, H1:])
            g_ftW /= b
            opt.step([g_ftB, g_ftW, g_fc1B, g_fc1W, g_outB, g_outW], clip=5.0)
            step += 1
        print(f"[train] epoch {ep + 1}/{args.epochs} loss {ep_loss / nb:.5f} "
              f"lr {opt.lr:.2e}", flush=True)
        # write updated references back into `net`, projecting fc layers to
        # the int16-representable range so float training cannot ever drift
        # into values the exported quantisation would clip
        net.ftB, net.ftW, net.fc1B, net.fc1W = params[0], params[1], params[2], params[3]
        fc_lim = MAX_FC_WEIGHT / FC1_SCALE      # float range for fc1 weights
        np.clip(net.fc1W, -fc_lim, fc_lim, out=net.fc1W)
        outw_lim = MAX_FC_WEIGHT / OUT_SCALE
        np.clip(params[5], -outw_lim, outw_lim, out=params[5])
        net.outB = np.float32(params[4][0])
        net.outW = params[5]

    # ---------------- validation: float + int-parity + metrics ----------------
    out, *_ = forward_batch(val_i)
    mae_f = float(np.abs(out * EVAL_NORM - E[val_i]).mean())
    q = quantize(net)
    ints, floats = [], []
    vmax = 0.0
    for j in val_i[: max(args.vectors, 400)]:
        ints.append(int_eval(q, F_us[j], F_them[j], wrap16))
    floats = list(out[: len(ints)] * EVAL_NORM)   # cp scale, like ints
    d = np.abs(np.array(ints) - np.array(floats))
    # accumulator headroom check (int16 wrap would corrupt evals)
    maxacc = 0.0
    for j in val_i[:2000]:
        m = max(max_abs_acc(q, F_us[j]), max_abs_acc(q, F_them[j]))
        maxacc = max(maxacc, m)
    fv = np.abs(np.array(floats) - E[val_i[: len(floats)]])
    ex = E[val_i[: len(floats)]] - E[val_i[: len(floats)]].mean()
    ey = np.array(floats) - np.mean(floats)
    corr = float((ex * ey).mean() / (ex.std() * ey.std() + 1e-9))
    print(f"[train] val corr(float-label) {corr:.3f}", flush=True)
    print(f"[train] val MAE(float) {mae_f:.1f} cp | int-parity mean {d.mean():.2f} cp "
          f"max {d.max():.1f} cp | max|acc| {maxacc:.0f} (int16 limit 32767)", flush=True)
    if d.mean() > args.parity_tol:
        raise SystemExit(f"[train] PARITY FAIL: mean int-float diff {d.mean():.2f} cp "
                         f"> {args.parity_tol} - not exporting")
    if maxacc > 24000:
        raise SystemExit(f"[train] accumulator headroom fail ({maxacc:.0f}); "
                         "reduce FT scale or weights - not exporting")

    # ---------------- export --------------------------------------------------
    os.makedirs(args.out_dir, exist_ok=True)
    out_path = os.path.join(args.out_dir, args.tag + ".nnue")
    export_nnue(q, out_path)
    vec_path = os.path.join(REPO, "tests", "nnue_vectors.txt")
    with open(vec_path, "w", encoding="utf-8") as f:
        for k, j in enumerate(val_i[: args.vectors]):
            f.write(f"{rows[j]['fen']}\t{ints[k]}\n")
    print(f"[train] wrote {out_path} ({os.path.getsize(out_path)} bytes), "
          f"{args.vectors} parity vectors -> {vec_path}", flush=True)
    metrics = {"tag": args.tag, "rows": len(rows), "epochs": args.epochs,
               "val_mae_cp": mae_f, "val_corr": corr,
               "parity_mean_cp": float(d.mean()), "parity_max_cp": float(d.max()),
               "max_acc": maxacc, "parity_tol": args.parity_tol, "file": out_path,
               "huber": args.huber, "batch": args.batch, "seed": args.seed,
               "data": [os.path.basename(p) for p in args.data]}
    with open(out_path.replace(".nnue", ".json"), "w", encoding="utf-8") as mjf:
        json.dump(metrics, mjf, indent=1)
    print(json.dumps(metrics))


def max_abs_acc(q, feats):
    acc = q["ftB"].astype(np.int64) + q["ftW"][feats].sum(axis=0).astype(np.int64)
    return float(np.abs(acc).max())


def export_nnue(q, path):
    with open(path, "wb") as f:
        f.write(b"VNN1")
        f.write(struct.pack("<HHHH", 1, NUM_INPUTS, H1, H2))
        q["ftB"].astype("<i2").tofile(f)
        q["ftW"].astype("<i2").tofile(f)
        q["fc1B"].astype("<i4").tofile(f)
        q["fc1W"].astype("<i2").tofile(f)
        f.write(struct.pack("<i", int(q["outB"])))
        q["outW"].astype("<i2").tofile(f)


def load_nnue(path):
    q = {}
    with open(path, "rb") as f:
        magic = f.read(4)
        assert magic == b"VNN1", "bad magic"
        ver, inputs, h1, h2 = struct.unpack("<HHHH", f.read(8))
        assert (ver, inputs, h1, h2) == (1, NUM_INPUTS, H1, H2)
        q["ftB"] = np.frombuffer(f.read(2 * H1), "<i2").copy()
        q["ftW"] = np.frombuffer(f.read(2 * NUM_INPUTS * H1), "<i2").reshape(NUM_INPUTS, H1).copy()
        q["fc1B"] = np.frombuffer(f.read(4 * H2), "<i4").copy()
        q["fc1W"] = np.frombuffer(f.read(2 * H2 * 2 * H1), "<i2").reshape(H2, 2 * H1).copy()
        q["outB"] = np.int32(struct.unpack("<i", f.read(4))[0])
        q["outW"] = np.frombuffer(f.read(2 * H2), "<i2").copy()
    return q


if __name__ == "__main__":
    main()
