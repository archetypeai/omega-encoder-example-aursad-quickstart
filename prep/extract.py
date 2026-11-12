#!/usr/bin/env python3
"""Stage 1b: draw the quickstart subset and cut one 1,024-row window per operation.

    python prep/extract.py

From Stage 1a's data/prepared/samples.csv:
1. Candidates per role: the role's sessions (prep/common.py ROLE_SESSIONS), the class, a
   sample inside one session, and a window that stays inside that session.
2. Draw SUBSET[role][class] operations per role and class, seeded (SEED), so anyone
   rebuilds the same subset.
3. Each operation's window: 1,024 consecutive rows of the recording, starting PRE_ONSET
   rows before the screwdriver's torque rises. It holds the whole screwdriver action
   (about 470 rows) with the approach before and the retract after; a short sample's
   window runs on into the next movement, which is recorded data, not padding.
4. Read only the channels in CHANNELS (and timestamp), in raw units. A window whose
   recorded timestamps go back or jump more than MAX_STEP_S is not one continuous take
   (the recording has session breaks that only show as a jump forward); it is skipped and
   the next candidate in the seeded order is taken instead.
5. Timestamps: the recording repeats and jitters them around its 10 ms step, so each
   window is re-gridded to an exact 10 ms step from its first recorded timestamp, plus
   session * SESSION_OFFSET_S (timestamps restart in every session; this keeps every
   window's timestamps unique).

Writes data/prepared/ops/<sample_nr>.csv and data/prepared/ops.csv (one row per op).
"""
from __future__ import annotations

import sys

import h5py
import numpy as np
import pandas as pd

from common import (CHANNELS, MAX_STEP_S, PREPARED, PRE_ONSET, RAW, ROLE_SESSIONS, SEED, SESSION_OFFSET_S,
                    SUBSET, WINDOW)


def columns(f: h5py.Group) -> tuple[list[str], list[int]]:
    items = [x.decode() for x in f["block1_items"][()]]
    names = ["timestamp", *CHANNELS]
    missing = [n for n in names if n not in items]
    if missing:
        sys.exit(f"not in block1 (float columns): {missing}")
    return names, [items.index(n) for n in names]


def main() -> None:
    s = pd.read_csv(PREPARED / "samples.csv")
    starts = s.groupby("session")["first_row"].min()
    ends = s.assign(last=s.first_row + s.rows).groupby("session")["last"].max()
    s["win_start"] = (s["first_row"] + s["t_on"] - PRE_ONSET).astype("Int64")
    s["win_end"] = s["win_start"] + WINDOW
    ok = ((s["sessions_spanned"] == 1) & s["t_on"].notna()
          & (s["win_start"] >= s["session"].map(starts)) & (s["win_end"] <= s["session"].map(ends)))
    rng = np.random.default_rng(SEED)
    out = PREPARED / "ops"
    out.mkdir(parents=True, exist_ok=True)
    for old in out.glob("*.csv"):
        old.unlink()
    picked, skipped = [], 0
    with h5py.File(RAW, "r") as h:
        f = h["complete_data"]
        names, idx = columns(f)
        ranks = np.argsort(np.argsort(idx))           # h5py needs increasing columns; map back to `names` order
        for role, wants in SUBSET.items():
            for cls, n in wants.items():
                pool = s[ok & (s["class"] == cls) & s["session"].isin(list(ROLE_SESSIONS[role]))]
                taken = []
                for i in rng.permutation(len(pool)):   # seeded order; continuity failures are skipped
                    r = pool.iloc[i]
                    block = f["block1_values"][int(r.win_start):int(r.win_end), sorted(idx)][:, ranks]
                    dt = np.diff(block[:, 0])
                    if dt.max() > MAX_STEP_S or dt.min() < -MAX_STEP_S:   # a break, not jitter or a repeat
                        skipped += 1
                        continue
                    w = pd.DataFrame(block, columns=names).rename(columns=CHANNELS)
                    c0 = int(round((block[0, 0] + r.session * SESSION_OFFSET_S) * 100))   # whole centiseconds
                    w["timestamp"] = [f"{(c0 + k) / 100:.2f}" for k in range(WINDOW)]
                    w.to_csv(out / f"{int(r.sample_nr):04d}.csv", index=False, float_format="%.6g")
                    taken.append(r)
                    if len(taken) == n:
                        break
                if len(taken) < n:
                    sys.exit(f"{role}/{cls}: only {len(taken)} continuous windows of {len(pool)} candidates, {n} wanted")
                picked.append(pd.DataFrame(taken).assign(role=role))
                print(f"{role:<10} {cls:<16} {n:>3} of {len(pool):>4} candidates")
    ops = pd.concat(picked).sort_values("first_row").reset_index(drop=True)
    print(f"skipped {skipped} windows that are not one continuous take")
    keep = ["sample_nr", "role", "class", "session", "first_row", "rows", "t_on", "t_off", "win_start", "win_end"]
    ops[keep].to_csv(PREPARED / "ops.csv", index=False)
    print(f"wrote {len(ops)} operations to data/prepared/ops/ and data/prepared/ops.csv")


if __name__ == "__main__":
    main()
