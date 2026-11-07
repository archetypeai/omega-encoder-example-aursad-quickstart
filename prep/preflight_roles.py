#!/usr/bin/env python3
"""Stage 3: check the role files against the Omega Encoder agent's rules. Read-only.

    python prep/preflight_roles.py

The agent takes the first column as timestamp and embeds every other numeric column. So
each file must be exactly `timestamp` + the manifest's channels (no label or index column,
which would be embedded as a sensor), exactly 1,024 rows (one operation), on the 10 ms
grid, with a filename no other upload shares. Batch outputs are matched back to files by
window start time, so start times must be unique. Each candidate window size must divide
1,024: a file is then whole windows in batch, and a serving query is never shorter than
its session's window (which the platform answers with a 503). Labels must cover every scored file and nothing else,
the library must have none, and no session may be in two roles.
Exit status is non-zero only on FAIL.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from common import CANDIDATE_WINDOWS, REPO, ROLES, SCORED, SUBSET, WINDOW, Report


def main() -> int:
    r = Report("Stage 3: role preflight (data/roles/)")
    m = json.loads((ROLES / "manifest.json").read_text())
    cols = ["timestamp", *m["channels"]]
    problems, checks = [], 0
    for f in m["files"]:
        df = pd.read_csv(REPO / f["path"])
        checks += 5
        if list(df.columns) != cols:
            problems.append(f"{f['path']}: columns {list(df.columns)[:4]}...")
        if len(df) != WINDOW:
            problems.append(f"{f['path']}: {len(df)} rows")
        if df.isna().any().any():
            problems.append(f"{f['path']}: NaN")
        if not (np.round(np.diff(df["timestamp"].to_numpy()), 4) == 0.01).all():
            problems.append(f"{f['path']}: off the 10 ms grid")
        if not np.isclose(df["timestamp"].iloc[0], f["start"]):
            problems.append(f"{f['path']}: does not match the manifest")
    r.add("FAIL" if problems else "PASS", "file format",
          "; ".join(problems[:3]) if problems else
          f"{len(m['files'])} files: timestamp + {len(m['channels'])} channels, {WINDOW} rows, 10 ms grid, match manifest")

    names = [Path(f["path"]).name for f in m["files"]]
    on_disk = sorted(p.name for p in ROLES.glob("*/*.csv"))
    r.add("PASS" if sorted(names) == on_disk else "FAIL", "manifest matches disk",
          f"{len(on_disk)} files" if sorted(names) == on_disk else "files on disk differ from the manifest")
    dup = len(names) - len(set(names))
    r.add("FAIL" if dup else "PASS", "unique upload names", f"{dup} duplicates" if dup else f"{len(names)} distinct")

    starts = {f["start"] for f in m["files"]}
    r.add("PASS" if len(starts) == len(m["files"]) else "FAIL", "unique window start times",
          "every window starts at a different time (outputs map back to files by time)"
          if len(starts) == len(m["files"]) else "two windows share a start time")

    bad = [w for w in CANDIDATE_WINDOWS if WINDOW % w]
    r.add("FAIL" if bad else "PASS", "whole windows per operation",
          f"windows {bad} do not divide {WINDOW}" if bad else
          ", ".join(f"{w}: {WINDOW // w}" for w in CANDIDATE_WINDOWS) + " window(s) per operation, no remainder")

    sessions = {}
    for role in SCORED:
        lab = json.loads((ROLES / "labels" / f"{role}.json").read_text())["operations"]
        files = {Path(f["path"]).name for f in m["files"] if f["role"] == role}
        labelled = {o["file"] for o in lab}
        counts = pd.Series([o["class"] for o in lab]).value_counts().to_dict()
        ok = labelled == files and counts == SUBSET[role]
        r.add("PASS" if ok else "FAIL", f"labels: {role}",
              ", ".join(f"{k} {v}" for k, v in counts.items()) if ok else
              f"labels {len(labelled)} vs files {len(files)}; counts {counts}")
        sessions[role] = {o["session"] for o in lab}
    r.add("FAIL" if (ROLES / "labels" / "library.json").exists() else "PASS", "library is normal-only",
          "no labels file: every library operation is normal")
    overlap = [f"{a}/{b}" for a in sessions for b in sessions if a < b and sessions[a] & sessions[b]]
    r.add("FAIL" if overlap else "PASS", "no session in two roles", f"{overlap}" if overlap else "disjoint")
    r.add("PASS" if (ROLES / "NOTICE.md").exists() else "FAIL", "attribution", "NOTICE.md present (CC BY 4.0)")
    print(f"  {checks} file checks")
    return r.finish()


if __name__ == "__main__":
    sys.exit(main())
