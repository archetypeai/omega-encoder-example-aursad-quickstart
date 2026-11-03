#!/usr/bin/env python3
"""Stage 2: build the role files the Omega Encoder agent receives.

    python prep/build_roles.py

From Stage 1b's operations (data/prepared/ops/):
- Every channel is z-scored with the library's mean and std (no other role's).
- One file per operation: data/roles/<role>/<role>_<sample_nr>.csv, 1,024 rows: a
  `timestamp` (seconds, exact 10 ms grid), then the 12 channels, and nothing else. The
  agent embeds every numeric column, so a label column would be embedded as a sensor.
  One file is exactly one window at the agent's fixed window and step of 1,024.
- Labels never go into a role file. Each scored role's labels are in
  data/roles/labels/<role>.json (file -> class), read only by the stage that scores it.
- data/roles/manifest.json lists every file and the z-score; it carries no labels.
- data/roles/NOTICE.md: attribution and the changes made to the AURSAD data (CC BY 4.0).
"""
from __future__ import annotations

import json

import pandas as pd

from common import ANOMALIES, CHANNELS, PREPARED, ROLE_SESSIONS, ROLES, SCORED, SEED, SUBSET, WINDOW

NOTICE = """# AURSAD role files: attribution and changes

These files are derived from the **AURSAD: Universal Robot Screwdriving Anomaly Detection
Dataset** by Błażej Leporowski, Daniella Tola, Casper Hansen and Alexandros Iosifidis
(Aarhus University; Technicon ApS), version 1.1 on Zenodo:
https://doi.org/10.5281/zenodo.4487073. Paper: arXiv:2102.01409.

The original dataset and these derived files are licensed under the
**Creative Commons Attribution 4.0 International License (CC BY 4.0)**:
https://creativecommons.org/licenses/by/4.0/. The code in this repository is licensed
under the Apache License 2.0 (see `LICENSE`).

## Changes made to the original data

- **Subset:** {n_ops} of the 2,042 labelled tightening samples (seed {seed}), drawn per
  role and class as in `prep/common.py` (`SUBSET`). Classes kept: normal, damaged screw,
  extra assembly component, missing screw. The 3 damaged-plate-thread samples and all
  loosening samples are not included.
- **Roles by recording session:** library sessions 0-4, validation 5-8, test 9-13,
  delivery 14-18 (the original file's timestamps restart in each of its 19 sessions).
- **Windows:** each operation is 1,024 consecutive rows (10.24 s at 100 Hz) of the original
  recording, starting 256 rows before the screwdriver's current torque first exceeds
  0.05 Nm in that sample. A window can include rows of the neighbouring robot motion.
  Windows whose original timestamps jump by more than 0.1 s were not used.
- **Channels:** 12 of the 125 features, renamed: {channel_map}.
- **Values:** z-scored per channel with the library operations' mean and std
  (`manifest.json` holds both, to undo it).
- **Timestamps:** re-gridded to an exact 10 ms step from each window's first original
  timestamp (the original repeats and jitters timestamps), plus 100,000 s × session
  number, so timestamps are unique across sessions.
- **Labels:** moved out of the data files into `labels/<role>.json`.
"""


def main() -> None:
    ops = pd.read_csv(PREPARED / "ops.csv")
    chans = list(CHANNELS.values())
    lib = pd.concat(pd.read_csv(PREPARED / "ops" / f"{n:04d}.csv")[chans]
                    for n in ops.loc[ops.role == "library", "sample_nr"])
    mean, std = lib.mean(), lib.std().replace(0, 1.0)

    for old in ROLES.glob("**/*.csv"):
        old.unlink()
    files, labels = [], {r: [] for r in SCORED}
    for op in ops.itertuples():
        w = pd.read_csv(PREPARED / "ops" / f"{op.sample_nr:04d}.csv", dtype={"timestamp": str})
        z = ((w[chans] - mean) / std).astype("float32")
        z.insert(0, "timestamp", w["timestamp"])
        name = f"{op.role}_{op.sample_nr:04d}.csv"
        path = ROLES / op.role / name
        path.parent.mkdir(parents=True, exist_ok=True)
        z.to_csv(path, index=False, float_format="%.5g")
        files.append({"role": op.role, "path": f"data/roles/{op.role}/{name}", "rows": len(z),
                      "start": float(w["timestamp"].iloc[0]), "end": float(w["timestamp"].iloc[-1])})
        if op.role in labels:
            labels[op.role].append({"file": name, "sample_nr": int(op.sample_nr), "class": op._3,
                                    "session": int(op.session)})

    (ROLES / "labels").mkdir(parents=True, exist_ok=True)
    for role, rows in labels.items():
        (ROLES / "labels" / f"{role}.json").write_text(json.dumps({"role": role, "operations": rows}, indent=1))
    for role in SUBSET:
        n = sum(f["role"] == role for f in files)
        mix = ", ".join(f"{c} {k}" for c, k in SUBSET[role].items())
        print(f"{role:<10} {n:>3} files  ({mix})")

    manifest = {"dataset": "AURSAD v1.1 (Zenodo 10.5281/zenodo.4487073), CC BY 4.0, derived; see NOTICE.md",
                "window": WINDOW, "step_s": 0.01, "channels": chans,
                "source_columns": {v: k for k, v in CHANNELS.items()},
                "role_sessions": {k: [v.start, v.stop - 1] for k, v in ROLE_SESSIONS.items()},
                "classes": ["normal", *ANOMALIES],
                "zscore": {"mean": mean.round(6).to_dict(), "std": std.round(6).to_dict()}, "files": files}
    (ROLES / "manifest.json").write_text(json.dumps(manifest, indent=1))
    (ROLES / "NOTICE.md").write_text(NOTICE.format(
        n_ops=len(ops), seed=SEED,
        channel_map=", ".join(f"`{k}` → `{v}`" for k, v in CHANNELS.items())))
    print(f"wrote data/roles/ ({len(files)} files), labels/, manifest.json, NOTICE.md")


if __name__ == "__main__":
    main()
