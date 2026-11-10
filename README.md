# Omega Encoder agent quickstart: screwdriving anomalies (AURSAD)

## TL;DR

- **What:** a detector that watches a robot screwdriver's 12 signals and scores how far each tightening is from normal.
  It is fitted on **normal operation only**: no fault is labelled, collected or shown to it before deployment. Each
  tightening is embedded by the **Omega Encoder agent** (the `omega-embeddings` blueprint, Omega 1.5), and **your own
  anomaly detector (kNN)** scores the embeddings.
- **Both ways to run the agent, through Agent Lifecycle 2.0** (project → blueprint → **package** → deployment → session):
  - **batch** for the roles on record (library, validation, test, delivery): upload files, run a session, download.
  - **serving** for live use: the agent stays loaded and answers one tightening per query, about 1.5 s each. Its answers
    are checked against batch.
- **Developer key only:** no admin role. The window size is set when the blueprint is copied (batch) or per serving
  session.
- **Verified on dev and staging:** the same results on both, file for file (see [Results](#results-and-they-reproduce)).
- **Data:** [AURSAD](https://doi.org/10.5281/zenodo.4487073) (CC BY 4.0): a UR3e cobot with an OnRobot screwdriver,
  100 Hz, labelled normal and faulty tightenings. The role files are committed, so you can skip the 6.4 GB download.

| Stage | What happens | Time |
|---|---|---|
| 0 | download AURSAD (6.4 GB) | ~4 min |
| 1a–1c | inspect the file, extract the subset, check it | ~5 min |
| 2–3 | build the role files, check them | ~1 min |
| 4 | **library** in batch at window 1,024, 512 and 256 (the reference for normal) | ~7 min |
| 5 | **validation** in batch at the same windows; choose the settings, freeze them | ~6 min |
| 6 | **test** in batch at the frozen window, scored once | ~2 min |
| 7 | **delivery** in batch at the frozen window, scored afterwards | ~2 min |
| 8 | **serve:** each delivery tightening as one query, checked against Stage 7 | ~3 min |
| 9 | optional: **watch it live**, the delivery replayed through a serving session ([`app-serving/`](app-serving/README.md)) | ~3–6 min a replay |

Stages 3–8 take about **20 minutes**, nearly all of it on the platform. Platform times vary with load.

## The scenario

- **A robot cell has normal screwdriving on record and no labelled fault library:** the faults that will happen have
  not happened yet. Here that record is 150 normal tightenings from the cell's first recording sessions.
- **Settings are chosen on the cell's incident record** (validation): normal tightenings and a few of each fault.
- **We report how the detector does on tightenings it has never seen** (the test), once.
- **We then run it over later operation** (the delivery), with labels hidden, and score the outputs afterwards: how many
  faulty screws it catches, and how often it flags a good one. Then **we serve it**, one tightening per query, as the
  cell would ask right after each tightening, and check every answer against the batch delivery.

### The robot and its faults

A UR3e collaborative robot drives screws into an aluminium plate with an OnRobot screwdriver. The dataset's authors
recorded 4,094 tightenings in 19 sessions, and made the faults themselves:
- **damaged screw:** the thread filed down;
- **extra assembly component:** a washer placed on the hole;
- **missing screw:** the screwdriver tightens without having picked one up.

This example uses 12 of the 134 columns, renamed: current and achieved screwdriver torque, the 6 joint currents, the
tool's Z force and its 3-axis accelerometer. The faults act on the screw, so the screwdriver's torque is where they
should show first. The arm's motion varies from hole to hole.

### The operations, and what each role's files are

One operation is one tightening: **1,024 rows (10.24 s)**, from 256 rows before the screwdriver's torque rises. Anomaly
types were recorded in campaigns, so the **recording session** is the unit that no two roles share.

| Role | Sessions | Files | Operations (normal / anomaly) | Labels | Used in |
|---|---|---|---|---|---|
| library | 0–4 | 150 | 150 / 0 | none: all normal | 4: the reference for normal |
| validation | 5–8 | 105 | 60 / 15 damaged, 15 extra component, 15 missing | `labels/validation.json` | 5: chooses the settings, sets the threshold |
| test | 9–13 | 98 | 60 / 15 damaged, 8 extra component, 15 missing | `labels/test.json` | 6: scored once |
| delivery | 14–18 | 90 | 60 / 15 damaged, 15 missing | `labels/delivery.json`, read only afterwards | 7: scored afterwards; 8: served |

- **One file per operation:** a batch session embeds each file separately, and a serving query is one operation. Every
  window then belongs to exactly one operation and is matched back to it by start time (batch) or by its query
  (serving).
- **1,024 rows:** it covers the screwdriver's action (median ~490 rows) with room around it, and it is a whole number
  of windows at every size Stage 5 tries (1, 2 or 4). A serving query is therefore never shorter than its window.
- **150 library operations:** at window 256 that is 600 reference windows, which is plenty for k ≤ 10 neighbours, and
  they come from five sessions, so "normal" isn't one session's quirks.
- **Test has 8 extra components** because that is every usable one in sessions 9–13. **Delivery has none** because
  none were recorded in sessions 14–18.
- **Labels are never in a role file:** the agent embeds every numeric column, so a label column would be embedded as a
  sensor. They are held back in `data/roles/labels/`, and each is read only by the command that scores that role.

## The lifecycle, batch and serving

```
                         ┌─ copy omega-aursad      (as shipped, 1024) ─► package ─┬─► batch deployment ─► sessions: library, validation, test, delivery
project ─► blueprints ───┼─ copy omega-aursad-w512 (window 512)       ─► package ─┼─► batch deployment ─► sessions: library, validation
                         └─ copy omega-aursad-w256 (window 256)       ─► package ─┘─► batch deployment ─► sessions: library, validation, ...
                                                                                   
                            package of omega-aursad ─► serving deployment ─► session, values {window_size, step_size} = the frozen window
                                                                                  └─► POST /query, one per delivery operation (Stage 8)
```

| Object | Call | Here |
|---|---|---|
| project | `POST /api/projects` | `Omega Encoder AURSAD quickstart`, reused on reruns |
| blueprint | `POST /api/agents/blueprints/omega-embeddings/copy` | One copy per window size. `omega-aursad` runs as shipped (window 1,024, step 1,024). The others set the window at copy time: `"overrides": {"values": {"window_size": 256, "step_size": 256}}`. |
| package | `POST /api/agents/packages` (`target: platform`) | Freezes a copy and its model (`newton-omega-1-5-safetensors`). |
| deployment | `POST /api/agents/deployments` | `kind: batch`, one per window size, reused by Stages 4–7. `kind: serving` (Stage 8) is created and ended by `serve/serve.py`: while it runs it holds a worker. |
| session (batch) | `POST /api/agents/sessions` with `connectors.source` = file ids | One per role and window, 90–150 files each. Results are **paged** (100 per page; follow `next_cursor`). |
| session (serving) | `POST /api/agents/sessions` with `values` | Sets the window for this session only, over the shipped package: one serving deployment can serve any window. |
| query | `POST /api/agents/sessions/{id}/query` | One operation: 12 lists of 1,024 numbers. Returns one record per window, `channel_0..11` (the file's column order), 768 numbers each. |

What a developer key can do with the Omega Encoder agent (dev 2026-11-06, staging 2026-11-09): everything above. Session `values` work on
serving sessions only. A batch session refuses them (`422 values_not_supported`), so batch sets the window on the
blueprint copy instead. A query shorter than its session's window gets a `503` rather than a clear error, which is one
more reason for whole windows per operation.

## Setup

```sh
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
source .venv/bin/activate          # every command below assumes the venv is active
cat > .env <<EOF
ATAI_API_KEY=sk_...
ATAI_API_ENDPOINT=https://platform.dev.u1.archetypeai.app/api
EOF
```

For staging, use `https://platform.stage.u1.archetypeai.app/api`. Values may be quoted (`KEY="..."`).

Every command below runs as `python ...` in the activated venv. `.env` overrides anything exported in your shell, and
every script that calls the platform prints the endpoint it uses first. Stages 0–3 need no API key.

**Shortcut:** the role files are committed. To skip the download, start at Stage 3.

## The stages

Every script runs from the repo root and is safe to rerun: `out/embed/state.json` keeps the ids, and a role already
embedded at a window is not embedded again. A run with a different key or endpoint starts fresh. **To run again from
scratch,** move `out/` and `eval_out/` aside.

### Stage 0: download

```sh
python prep/download.py
```

Fetches `AURSAD.h5` from Zenodo in 8 parallel byte ranges. Zenodo throttles each connection (~0.8 MB/s); 8 together
measured ~34 MB/s. Each range resumes where it stopped, and the joined file is checked against Zenodo's md5 before it is
moved into place. Only the `.h5` is fetched, never the `.pkl`: unpickling a downloaded file can run arbitrary code.

**Expect:** `wrote data/raw/AURSAD.h5 (6.42 GB), md5 OK`.

### Stage 1: inspect, extract, check

```sh
python prep/inspect_h5.py            # 1a: the file's structure, read-only (h5py, nothing unpickled)
python prep/inspect_samples.py       # 1a: every sample: length, class, session, where the screwdriver acts
python prep/extract.py               # 1b: draw the subset, cut one 1,024-row operation each
python prep/preflight_prepared.py    # 1c: check what 1b wrote, read-only
```

**1a** finds a pandas "fixed" frame of plain numeric blocks (no pickled objects): 6,249,074 rows, 134 columns, 100 Hz.
- **4,094 samples**, with the paper's class counts exactly: 1,420 normal, 221 damaged screw, 183 extra component, 218
  missing screw, 3 damaged thread, 2,049 loosening. Each labelled sample is one tightening, median ~1,400–1,550 rows.
- **The screwdriver acts** from about row 600 to row 1,100 of a sample, in every sample of every class.
- **19 recording sessions**: timestamps restart in each. Anomaly types were recorded in campaigns, so the mix shifts
  across sessions (extra-component faults early, missing-screw faults late).

**1b** draws the subset (seed `20260502`, the counts in `prep/common.py`).
- **Operation:** 1,024 consecutive recording rows starting 256 rows before the torque rises.
- **Channels:** the 12 above, renamed.
- **Continuity:** an operation whose recorded timestamps jump by more than 0.1 s is not one take, and the next
  candidate is drawn instead. One session break shows only as a 4,193 s jump forward.
- **Timestamps:** re-gridded to an exact 10 ms step. The recording repeats and jitters them.

**Expect:** `skipped 2 windows that are not one continuous take` and `wrote 443 operations`.

**1c** re-reads what 1b wrote: counts per role and class, 1,024 rows each, the exact 10 ms grid, no NaN, torque in every
operation, all channels varying. **Expect:** `8 PASS, 1 WARN, 0 FAIL, 2 INFO`. The WARN is real: in 15 operations (3%) a
long screwdriver action runs past the end.

### Stage 2: build the role files

```sh
python prep/build_roles.py
```

- **Z-scoring:** every channel, with the **library's** mean and std.
- **Files:** one per operation, `data/roles/<role>/<role>_<sample_nr>.csv`: a `timestamp`, then the 12 channels, and
  nothing else.
- **Labels:** held back in `data/roles/labels/`.
- **Attribution:** `NOTICE.md`.

**Expect:** library 150, validation 105, test 98 and delivery 90 files, 48 MB in all.

### Stage 3: check the role files against the agent's rules

```sh
python prep/preflight_roles.py
```

It checks:
- each file is exactly `timestamp` + the 12 channels, 1,024 rows, on the 10 ms grid, and matches the manifest;
- upload names are distinct, and start times are unique (batch outputs are matched back to files by start time);
- every candidate window (1,024, 512, 256) divides 1,024: whole windows in batch, no short serving query;
- labels cover every scored file, the library has none, and no session is in two roles;
- `NOTICE.md` is present.

**Expect:** `11 PASS, 0 WARN, 0 FAIL` over 2,215 file checks.

### Stage 4: library, in batch, at three window sizes

```sh
python embed/embed.py --roles library --window 1024 512 256
```

The first run creates the project. Then, for each window size, it copies `omega-embeddings` (window and step set at
copy time; 1,024 is as shipped), packages the copy and deploys the package as batch. It uploads the 150 files once,
since every window size shares the uploads, and opens one batch session per window.

**Expect:** `library @ 1024: 150 windows (150, 1, 12, 768)`, `library @ 512: 300 windows (150, 2, 12, 768)`,
`library @ 256: 600 windows (150, 4, 12, 768)`.

### Stage 5: validation, in batch; choose the settings, freeze them

```sh
python embed/embed.py --roles validation --window 1024 512 256
python detect/detect.py select
```

**The detector (kNN):**
- **Joint state of a window:** each channel's 768-d embedding, L2-normalised; a channel group's channels concatenated;
  optionally PCA, fitted on the library's windows.
- **Window score:** the mean distance to the k nearest library windows. Either any library window (`match any`), or
  only those at the same position in their operation (`match position`): operations are aligned to the torque rise,
  so window 2 of 4 is always the tightening itself.
- **Operation score:** its worst window.
- **Threshold:** a **5% false-alarm rate on validation's normal operations**, which are data the library hasn't seen.
  Thresholds for 1% and 2% are set the same way and reported beside it.

`select` tries 240 settings on validation and keeps the best AUROC (normal against every anomaly):
- window {1,024, 512, 256};
- channel groups: `screwdriver` (2 torque channels), `screwdriver+tool` (plus force and accelerometer), `all` (12);
- PCA {16, 32, 64, none}, k {1, 3, 5, 10}, and match {any, position} below 1,024.

Everything is frozen in `eval_out/settings.json`; Stages 6–8 read it and never change it.

**Expect:**

```
  window 1024  screwdriver+tool   best AUROC 0.765  (PCA 32, k 3)
  window  512  screwdriver+tool   best AUROC 0.736  (PCA none, k 1, match position)
  window  256  screwdriver+tool   best AUROC 0.821  (PCA none, k 1, match position)
chosen and frozen: window 256, channels screwdriver+tool, PCA none, k 1, match position (validation AUROC 0.821); threshold 1.5704 = 5% false alarms on validation's normal operations
```

### Stage 6: test, in batch, scored once

```sh
python embed/embed.py --roles test --window frozen
python detect/detect.py test
```

`--window frozen` reads the window from `eval_out/settings.json`.

### Stage 7: delivery, in batch, scored afterwards

```sh
python embed/embed.py --roles delivery --window frozen
python detect/detect.py deliver
```

Each writes `eval_out/<role>.json`, `scores_<role>.csv` and a plot `scores_<role>.png` (one point per operation, by
class, with the threshold).

### Stage 8: serve it, one operation per query

```sh
python serve/serve.py                # every delivery operation, in recording order (--limit N for the first N)
python detect/detect.py deliver --source serving
```

Stage 7 embeds in batch: upload, run a session, download when it is done. **Serving** keeps the agent loaded and answers
one tightening in one round trip, with no upload, queue or polling: what the cell would ask right after each tightening.

1. **The shipped copy's package** (`omega-aursad`, window 1,024), deployed as **serving**.
2. **A serving session with `values`** setting `window_size` and `step_size` to the frozen window. One deployment can serve
   any window, per session, with no new blueprint.
3. **Each delivery operation, in recording order,** sent as one query: 12 lists of 1,024 numbers. The answer is one record
   per window (4 at window 256). It is scored at once by the frozen detector against the batch library, and flagged if
   it crosses the threshold. Labels are not read.
4. **Every answer checked against Stage 7:** each window's embedding, each operation's score, each alarm.
5. **Cleanup:** the session and deployment are ended however the run ends (Ctrl-C and SIGTERM included).

**Expect** (dev, 2026-11-06):

```
Stage 8: 90 delivery operations served in 90 queries, window 256 (4 per operation); 24 alarm(s)
  latency per query: median 1507 ms, p95 1570 ms, max 1621 ms
  against Stage 7 (batch): embeddings cosine min 0.999923 (median 1.000000) over 4320 window-channels; alarm identical in 90/90; score max relative difference 6.5e-04
```

- **The served agent gives the batch delivery's answers:** every alarm, and the same detection and false-alarm rates
  when `detect.py deliver --source serving` scores them. A library built in batch is therefore safe to use with live
  queries.
- **About 1.5 s per tightening** at window 256 (4 windows), against 10.24 s for the tightening itself; ~0.6 s at 1,024.
  Staging (2026-11-09): median 1.35 s, with the same 24 alarms and scores as dev.

**Writes:** `eval_out/serving/delivery.{csv,json}` (a row per operation: score, alarm, latency, and batch's score and
alarm) and `out/serve/w256/delivery.npz`.

### Stage 9 (optional): watch it live, served from the platform

```sh
python app-serving/scripts/export_detector.py     # the frozen detector and the library view, from Stages 4–7
cd app-serving && npm install
npm run dev                                       # broker + serving bridge + replayer + web
open http://localhost:5183
```

[`app-serving/`](app-serving/README.md) replays Stage 7's delivery one tightening at a time, as if
the cell were running now. Each tightening goes to a serving session of the Omega Encoder agent at
the frozen window, and the bridge scores the answer with the frozen kNN, checked against Stage 7.
The page shows the 12 channels, each tightening's window scores, the embedding space and the
delivery's score so far. A full replay ends at Stage 7's result: 24 alarms, 19 of 30 faults
caught, 5 of 60 false alarms. It holds a serving deployment while it runs; `npm run stop` ends it.

## Results, and they reproduce

Dev, developer key, 2026-11-06; reproduced on staging, 2026-11-09.

Detection rate per anomaly type at the frozen 5% threshold, and AUROC against the role's normal operations. **Window
256** is what `select` froze. **Window 1,024** is the same protocol limited to the shipped window
(`--window 1024` in Stages 4–5), for comparison.

| | validation (chooses) | | test (once) | | delivery (afterwards) | |
|---|---|---|---|---|---|---|
| window | 1,024 | **256** | 1,024 | **256** | 1,024 | **256** |
| **missing screw** | 40% · 0.837 | 67% · 0.851 | 100% · 0.992 | 93% · 0.991 | 87% · 0.940 | 93% · 0.981 |
| damaged screw | 13% · 0.717 | 40% · 0.846 | 7% · 0.534 | 7% · 0.587 | 20% · 0.786 | 33% · 0.722 |
| extra component | 7% · 0.740 | 40% · 0.764 | 0% · 0.590 | 12.5% · 0.608 | (none) | (none) |
| all anomalies | 20% · 0.765 | 49% · 0.821 | 42% · 0.727 | 42% · 0.751 | 53% · 0.863 | 63% · 0.852 |
| **false alarms on normal** | 5.0% (set) | 5.0% (set) | 3.3% | **13.3%** | 1.7% | 8.3% |

Reading it:
- **Missing screws are caught reliably at either window:** 87–100% on unseen operations. Without a screw the torque
  profile is short and flat, which the embeddings separate clearly.
- **A shorter window helps the subtle faults on validation, and only partly beyond it.** At 256, validation catches 40%
  of damaged screws and extra components, against 13% and 7%. On delivery, damaged screws rise from 20% to 33%. On test
  they don't move (7%), and extra components rise to only 12.5%.
- **The 256 threshold didn't hold:** false alarms on test (13.3%) and delivery (8.3%) are above the 5% set on validation.
  At 1,024 they stayed under it. The chosen setting (k 1, no PCA) is the most flexible in the grid. It won on 45
  validation anomalies out of 240 settings tried, and a k = 1 score moves with whichever single library window is
  nearest. Expect some of its validation lead to be selection luck.
- **The sample is small:** 15 operations per type, 8 extra components in test. One operation is 7% (13% of the 8), so
  treat the subtle types' numbers as rough. Option M in `prep/common.py` (more operations per role) is the way to firmer
  numbers.
- **Batch and serving agree,** so the choice between them is about the deployment, not the result.

**Reproduce:** the 1,024 path ran from scratch three times with two developer keys (2026-11-02 and 11-06), and every
role file, selection and validation number was identical. The 1,024 test and delivery columns are from 11-02. The 256
path ran on dev on 11-06 and from scratch on staging on 11-09: the same frozen settings, the same test and
delivery results, and serving scores identical to dev's. Kept locally in `out/` and `eval_out/` (not committed): this run's ids, embeddings and outputs.

## Repo layout

| Path | What it is |
|---|---|
| `prep/download.py` | Stage 0: the Zenodo download, 8 parallel ranges, md5-checked |
| `prep/inspect_h5.py`, `prep/inspect_samples.py`, `prep/extract.py`, `prep/preflight_prepared.py` | Stage 1 |
| `prep/build_roles.py`, `prep/preflight_roles.py`, `prep/common.py` | Stages 2–3; counts, channels, candidate windows |
| `atai_api.py` | stdlib platform helpers: requests, uploads, packages, deployments, sessions, polling |
| `embed/embed.py` | Stages 4–7: batch embedding per role and window |
| `detect/detect.py` | Stages 5–7: the kNN detector; `select`, `test`, `deliver` |
| `serve/serve.py` | Stage 8: the delivery served one operation per query, checked against Stage 7 |
| `app-serving/` | Stage 9: the live monitor, served from the platform ([README](app-serving/README.md)) |
| `scripts/cleanup.py` | delete what the stages made on the platform |
| `data/roles/` | Stage 2's output: role files, held-back labels, manifest, `NOTICE.md` (committed) |
| `out/`, `eval_out/` | this run: ids, embeddings, settings, scores, plots |

## Clean up the platform

```sh
python scripts/cleanup.py          # what would be deleted, and any serving deployment still holding a worker
python scripts/cleanup.py --yes    # sessions -> deployments -> packages -> blueprints -> project
```

`serve/serve.py` and the app's bridge end their own serving session and deployment. Run cleanup if it was killed hard, and don't run cleanup
while it is running. A deployment must go before its package, and a package before its blueprint, or the delete returns
409. Uploaded files are kept.

## Licence

The code is licensed under the [Apache License 2.0](LICENSE). The data in `data/roles/` is derived from AURSAD and
licensed under [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/); see [data/roles/NOTICE.md](data/roles/NOTICE.md).

## Data attribution

AURSAD: Universal Robot Screwdriving Anomaly Detection Dataset, by Błażej Leporowski, Daniella Tola, Casper Hansen and
Alexandros Iosifidis (Aarhus University; Technicon ApS), [doi:10.5281/zenodo.4487073](https://doi.org/10.5281/zenodo.4487073),
[arXiv:2102.01409](https://arxiv.org/abs/2102.01409), licensed
[CC BY 4.0](https://creativecommons.org/licenses/by/4.0/). The files in `data/roles/` are derived from it; every change
is listed in [data/roles/NOTICE.md](data/roles/NOTICE.md).
