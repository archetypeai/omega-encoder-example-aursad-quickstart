#!/usr/bin/env python3
"""Stage 1a (part 2): measure every AURSAD sample. Read-only, h5py only.

    python prep/inspect_samples.py

Reads sample_nr, label, timestamp and the screwdriver's current torque in row chunks,
and reports per sample: its length, its label, its recording session (timestamps restart
in every session), and where the screwdriver acts within it (current torque above 0.05
Nm). The questions it answers: does one 1,024-row window hold a whole operation, for
every class, and which anomaly types were recorded in which sessions?

Writes data/prepared/samples.csv (one row per sample) for Stage 1b.
"""
from __future__ import annotations

from pathlib import Path

import h5py
import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[1]
RAW = REPO / "data" / "raw" / "AURSAD.h5"
OUT = REPO / "data" / "prepared"
CHUNK = 500_000
WINDOW = 1024
TORQUE_ON = 0.05
LABELS = {0: "normal", 1: "damaged_screw", 2: "extra_component", 3: "missing_screw",
          4: "damaged_thread", 5: "loosening"}


def col(f: h5py.Group, name: str) -> tuple[str, int]:
    for b in range(4):
        items = [x.decode() for x in f[f"block{b}_items"][()]]
        if name in items:
            return f"block{b}_values", items.index(name)
    raise KeyError(name)


def main() -> None:
    with h5py.File(RAW, "r") as h:
        f = h["complete_data"]
        n = f["axis1"].shape[0]
        where = {k: col(f, k) for k in ("sample_nr", "label", "timestamp", "output_double_register_25")}
        parts = []
        for a in range(0, n, CHUNK):
            b = min(a + CHUNK, n)
            parts.append(pd.DataFrame({k: f[ds][a:b, i] for k, (ds, i) in where.items()}))
            print(f"  read rows {b:,} / {n:,}", end="\r", flush=True)
    df = pd.concat(parts, ignore_index=True)
    print(f"\n{len(df):,} rows; timestamp {df.timestamp.iloc[0]:.2f} .. {df.timestamp.iloc[-1]:.2f}")
    dt = np.diff(df["timestamp"].to_numpy())
    print(f"timestamp step: median {np.median(dt):.4f} s; {np.mean(np.abs(dt - np.median(dt)) > 1e-3):.1%} off it; "
          f"{(dt <= 0).sum()} non-increasing")

    # A sample is a run of one sample_nr value; a session starts wherever the timestamp goes back.
    t = df["timestamp"].to_numpy()
    resets = np.r_[0, np.flatnonzero(np.diff(t) < 0) + 1]
    df["session"] = np.searchsorted(resets, np.arange(len(df)), side="right") - 1
    act = (df["output_double_register_25"] > TORQUE_ON).to_numpy()
    run = (df["sample_nr"] != df["sample_nr"].shift()).cumsum()
    rows_idx = pd.Series(np.arange(len(df)))
    g = df.groupby(run)
    first = rows_idx.groupby(run.to_numpy()).first().to_numpy()
    s = pd.DataFrame({"sample_nr": g["sample_nr"].first().to_numpy(), "first_row": first,
                      "rows": g.size().to_numpy(), "label": g["label"].first().to_numpy(),
                      "label_values": g["label"].nunique().to_numpy(),
                      "session": g["session"].first().to_numpy(),
                      "sessions_spanned": g["session"].nunique().to_numpy()})
    on = pd.Series(np.where(act, rows_idx, np.nan)).groupby(run.to_numpy()).agg(["min", "max"])
    s["t_on"] = (on["min"].to_numpy() - first)
    s["t_off"] = (on["max"].to_numpy() - first)
    s["class"] = s["label"].map(LABELS)
    print(f"{len(s):,} samples (runs of sample_nr); sample_nr {s.sample_nr.min()}..{s.sample_nr.max()}, "
          f"repeated values: {s.sample_nr.duplicated().sum()}")
    print(f"samples with more than one label value: {(s.label_values > 1).sum()}; "
          f"spanning a session boundary: {(s.sessions_spanned > 1).sum()}")
    print(f"{len(resets)} recording sessions")
    stats = s.groupby("class").agg(samples=("rows", "size"), rows_median=("rows", "median"), rows_min=("rows", "min"),
                                   torque_on_median=("t_on", "median"), torque_off_median=("t_off", "median"),
                                   no_torque=("t_on", lambda x: int(x.isna().sum())))
    stats["rows_ge_1024"] = s.groupby("class")["rows"].apply(lambda r: int((r >= WINDOW).sum()))
    print(stats.to_string())
    print("\nsamples per session and class:")
    print(pd.crosstab(s["session"], s["class"]).to_string())
    OUT.mkdir(parents=True, exist_ok=True)
    s.to_csv(OUT / "samples.csv", index=False)
    print(f"wrote {(OUT / 'samples.csv').relative_to(REPO)}")


if __name__ == "__main__":
    main()
