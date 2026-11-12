#!/usr/bin/env python3
"""Stage 1c: check the extracted operations before building role files. Read-only.

    python prep/preflight_prepared.py

Reads what Stage 1b wrote (never its in-memory state): the counts per role and class
against prep/common.py SUBSET, each window's length, timestamps, NaNs and screwdriver
action, the channels' variation, and that no sample or session is in two roles.
Exit status is non-zero only on FAIL.
"""
from __future__ import annotations

import sys

import numpy as np
import pandas as pd

from common import CHANNELS, PREPARED, PRE_ONSET, ROLE_SESSIONS, SUBSET, TORQUE_ON, WINDOW, Report


def main() -> int:
    r = Report("Stage 1c: prepared preflight (data/prepared/)")
    ops = pd.read_csv(PREPARED / "ops.csv")
    got = ops.groupby(["role", "class"]).size().to_dict()
    want = {(role, c): n for role, d in SUBSET.items() for c, n in d.items()}
    r.add("PASS" if got == want else "FAIL", "counts per role and class",
          f"{len(ops)} operations, as in SUBSET" if got == want else f"got {got}")
    dup = int(ops["sample_nr"].duplicated().sum())
    r.add("FAIL" if dup else "PASS", "no operation in two roles", f"{dup} repeated" if dup else "every sample_nr once")
    wrong = ops[[s not in ROLE_SESSIONS[role] for s, role in zip(ops.session, ops.role)]]
    r.add("FAIL" if len(wrong) else "PASS", "sessions match roles",
          f"{len(wrong)} outside their role's sessions" if len(wrong) else
          ", ".join(f"{k} {v.start}-{v.stop - 1}" for k, v in ROLE_SESSIONS.items()))

    bad_len, bad_ts, nan, no_act, act_cut, early = [], [], [], [], [], []
    stds = []
    for op in ops.itertuples():
        w = pd.read_csv(PREPARED / "ops" / f"{op.sample_nr:04d}.csv")
        if len(w) != WINDOW:
            bad_len.append(op.sample_nr)
        dt = np.round(np.diff(w["timestamp"].to_numpy()), 4)
        if not (dt == 0.01).all():
            bad_ts.append(op.sample_nr)
        if w.isna().any().any():
            nan.append(op.sample_nr)
        act = np.flatnonzero(w["torque_current"].to_numpy() > TORQUE_ON)
        if not len(act):
            no_act.append(op.sample_nr)
        else:
            if act[-1] >= WINDOW - 1:
                act_cut.append(op.sample_nr)
            if act[0] < PRE_ONSET - 1:
                early.append(op.sample_nr)
        stds.append(w[list(CHANNELS.values())].std().to_numpy())
    r.add("FAIL" if bad_len else "PASS", f"{WINDOW} rows each", f"{len(bad_len)} wrong" if bad_len else "every window")
    r.add("FAIL" if bad_ts else "PASS", "exact 10 ms timestamp grid",
          f"{len(bad_ts)} windows off the grid" if bad_ts else "every window")
    r.add("FAIL" if nan else "PASS", "no NaN", f"{len(nan)} windows" if nan else "none")
    r.add("FAIL" if no_act else "PASS", "screwdriver acts in each window",
          f"{len(no_act)} windows without torque > {TORQUE_ON} Nm" if no_act else f"torque > {TORQUE_ON} Nm in every window")
    r.add("WARN" if act_cut else "PASS", "action ends inside the window",
          f"{len(act_cut)} windows where the action runs past row {WINDOW} (longer than {WINDOW - PRE_ONSET} rows)"
          if act_cut else "in every window")
    r.add("INFO", "torque before the onset", f"{len(early)} windows open on torque from the motion before "
          f"(the screwdriver started under {PRE_ONSET} rows into its sample)")

    stds = np.array(stds)
    flat = [name for name, col in zip(CHANNELS.values(), stds.T) if np.median(col) == 0]
    r.add("WARN" if flat else "PASS", "channels vary within a window",
          f"constant in most windows: {flat}" if flat else f"all {len(CHANNELS)} channels")
    span = ops["t_off"] - ops["t_on"]
    r.add("INFO", "screwdriver action length", " ".join(
        f"{c} {int(v)}" for c, v in span.groupby(ops["class"]).median().items()) + " rows (median)")
    return r.finish()


if __name__ == "__main__":
    sys.exit(main())
