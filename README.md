# Omega Encoder agent quickstart: screwdriving anomalies (AURSAD)

Get Omega 1.5 embeddings from the **Omega Encoder agent** (the `omega-embeddings` blueprint) through **Agent Lifecycle
2.0**: project → blueprint → **package** → deployment → session. Then build **your own anomaly detector (kNN)** on them.
Every step uses a **developer** key; no admin role is needed.

The data is [AURSAD](https://doi.org/10.5281/zenodo.4487073) (CC BY 4.0): a UR3e collaborative robot with an OnRobot
screwdriver, recorded at 100 Hz, with labelled normal and faulty tightenings. The role files are committed under
`data/roles/`, so you can start at Stage 3 without the 6.4 GB download ([attribution and changes](data/roles/NOTICE.md)).

## The scenario

- **A robot cell has normal screwdriving on record and no labelled fault library**: 150 normal tightenings from its first
  recording sessions (the **library**).
- **Settings are chosen on a record of normal and faulty operations** (**validation**).
- **We report how the detector does on operations it has never seen** (the **test**), once.
- **We then run it over later operations** (the **delivery**), with labels hidden until afterwards, and score how many
  faulty screws it catches and how often it flags a good one.

One operation is one tightening: **1,024 rows (10.24 s)** around the screwdriver's action. That is exactly one window of
the Omega Encoder agent as shipped, so **one file = one window = one operation**. The roles are split by recording
session (time), and no operation or session is in two roles.

| Role | Sessions | Files | Mix | Used in |
|---|---|---|---|---|
| library | 0–4 | 150 | 150 normal | Stage 4: the reference for normal |
| validation | 5–8 | 105 | 60 normal, 15 damaged screw, 15 extra component, 15 missing screw | Stage 5: chooses the settings |
| test | 9–13 | 98 | 60 normal, 15 damaged screw, 8 extra component, 15 missing screw | Stage 6: scored once |
| delivery | 14–18 | 90 | 60 normal, 15 damaged screw, 15 missing screw | Stage 7: scored afterwards |

The anomalies, as the dataset's authors made them:
- **damaged screw:** the thread filed down;
- **extra assembly component:** a washer placed on the hole;
- **missing screw:** the screwdriver tightens without having picked one up.

Test has 8 extra-component operations because that is every usable one in sessions 9–13. Delivery has none because none
were recorded in sessions 14–18. Labels are never in a role file: they're held back in `data/roles/labels/<role>.json`
and read only by the stage that scores that role.

## The lifecycle, as this example uses it

```
project ──► blueprint ──────────────► package ─────────► deployment ──────► session ──────────► results
"AURSAD      copy of the canonical     the blueprint with  kind: batch         one per role, over   JSONL, one row
 Omega       omega-embeddings,         its model resolved  (ready at once)     that role's files    per window (one
 quickstart" as shipped                (Omega 1.5), frozen                     (Stages 4-7)         per operation)
```

| Object | Call | Here |
|---|---|---|
| project | `POST /api/projects` | `AURSAD Omega quickstart`, reused on reruns |
| blueprint | `POST /api/agents/blueprints/omega-embeddings/copy` | `omega-aursad`. The copy takes no values, so it runs as shipped: window 1024, step 1024, every numeric column, the first column as timestamp. |
| package | `POST /api/agents/packages` (`target: platform`) | Freezes the blueprint and its model (`newton-omega-1-5-safetensors`). |
| deployment | `POST /api/agents/deployments` (`kind: batch`) | One deployment, reused by Stages 4–7 |
| session | `POST /api/agents/sessions` with `connectors.source` = file ids | One per role, 90–150 files each |
| results | `GET /api/agents/sessions/{id}/results` | **Paged** (100 per page; follow `next_cursor`): one output per input file |

What a developer key can and can't do with the Omega Encoder agent (dev, 2026-11-02): batch deployment and sessions work.
Window, step and columns can't be set: the copy takes no values, registering a blueprint needs admin, and a `values`
field on a session is accepted but silently ignored. Serving fails without explicit columns.

## Setup

```sh
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
source .venv/bin/activate          # every command below assumes the venv is active
cat > .env <<EOF
ATAI_API_KEY=sk_...
ATAI_API_ENDPOINT=https://platform.dev.u1.archetypeai.app/api
EOF
```

Every command below runs as `python ...` in the activated venv. `.env` overrides anything exported in your shell, and
every script that calls the platform prints the endpoint it uses first. Stages 0–3 need no API key.

| Stage | What | Time |
|---|---|---|
| 0 | download AURSAD (6.4 GB) | ~4 min |
| 1a–1c | inspect the file, extract the subset, check it | ~5 min |
| 2–3 | build the role files, and check them against the agent's rules | ~1 min |
| 4 | **library**: embed in batch (the reference for normal) | ~1.5 min |
| 5 | **validation**: embed in batch, choose the settings, freeze them | ~2 min |
| 6 | **test**: embed in batch, score once | ~1.5 min |
| 7 | **delivery**: embed in batch, score afterwards | ~1.5 min |

**Shortcut:** the role files are committed. To skip the download, start at Stage 3.

## The stages

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
python prep/extract.py               # 1b: draw the subset, cut one 1,024-row window per operation
python prep/preflight_prepared.py    # 1c: check what 1b wrote, read-only
```

**1a** finds a pandas "fixed" frame of plain numeric blocks (no pickled objects): 6,249,074 rows, 134 columns, 100 Hz.
- **4,094 samples**, with the paper's class counts exactly: 1,420 normal, 221 damaged screw, 183 extra component, 218
  missing screw, 3 damaged thread, 2,049 loosening. Each labelled sample is one tightening, median ~1,400–1,550 rows.
- **The screwdriver acts** from about row 600 to row 1,100 of a sample, in every sample of every class.
- **19 recording sessions**: timestamps restart in each. Anomaly types were recorded in campaigns, so the mix shifts
  across sessions (extra-component faults early, missing-screw faults late).

**1b** draws the subset (seed `20260502`, the counts in `prep/common.py`).
- **Window:** for each operation, 1,024 consecutive recording rows starting 256 rows before its torque rises.
- **Channels:** 12, renamed: current and achieved screwdriver torque, the 6 joint currents, the tool Z force, and the
  3-axis tool accelerometer.
- **Continuity:** a window whose recorded timestamps jump by more than 0.1 s is not one take, and the next candidate is
  drawn instead. One session break shows only as a 4,193 s jump forward.
- **Timestamps:** re-gridded to an exact 10 ms step. The recording repeats and jitters them.

**Expect:** `skipped 2 windows that are not one continuous take` and `wrote 443 operations`.

**1c** re-reads what 1b wrote: counts per role and class, 1,024 rows each, the exact 10 ms grid, no NaN, torque in every
window, all channels varying. **Expect:** `8 PASS, 1 WARN, 0 FAIL, 2 INFO`. The WARN is real: in 15 windows (3%) a long
screwdriver action runs past the window's end.

### Stage 2: build the role files

```sh
python prep/build_roles.py
```

- **Z-scoring:** every channel, with the **library's** mean and std.
- **Files:** one per operation, `data/roles/<role>/<role>_<sample_nr>.csv`: a `timestamp`, then the 12 channels, and
  nothing else. The agent embeds every numeric column, so a label column would be embedded as a sensor.
- **Labels:** held back in `data/roles/labels/`.
- **Attribution:** `NOTICE.md`.

**Expect:** library 150, validation 105, test 98 and delivery 90 files, 48 MB in all.

### Stage 3: check the role files against the agent's rules

```sh
python prep/preflight_roles.py
```

It checks:
- each file is exactly `timestamp` + the 12 channels, 1,024 rows, on the 10 ms grid, and matches the manifest;
- upload names are distinct, and window start times are unique (outputs are matched back to files by start time);
- labels cover every scored file, the library has none, and no session is in two roles;
- `NOTICE.md` is present.

**Expect:** `10 PASS, 0 WARN, 0 FAIL` over 2,215 file checks.

### Stage 4: library: embed in batch

```sh
python embed/embed.py --roles library
```

The first run creates the project, copies `omega-embeddings` into it as `omega-aursad`, packages it and deploys the
package as batch; later stages reuse all of it. Then it uploads the 150 files, opens one session over them, waits, and
downloads every page of results.

**Expect:** `library: 150 windows (150, 12, 768)`.

### Stage 5: validation: embed in batch, choose the settings, freeze them

```sh
python embed/embed.py --roles validation
python detect/detect.py select
```

**The detector (kNN):**
- **Joint state:** each channel's 768-d embedding is L2-normalised, and a channel group's channels are concatenated;
  optionally PCA, fitted on the library.
- **Score:** the mean distance to the k nearest library operations.
- **Threshold:** a **5% false-alarm rate on validation's normal operations**, which are data the library hasn't seen.
  Thresholds for 1% and 2% are set the same way and reported beside it.

`select` tries 48 settings on validation and keeps the best AUROC (normal against every anomaly):
- channel groups: `screwdriver` (2 torque channels), `screwdriver+tool` (plus force and accelerometer), `all` (12);
- PCA {16, 32, 64, none} × k {1, 3, 5, 10}.

Everything is frozen in `eval_out/settings.json`; Stages 6 and 7 read it and never change it.

**Expect:**

```
  best for screwdriver        AUROC 0.718  (PCA 32, k 3)
  best for screwdriver+tool   AUROC 0.765  (PCA 32, k 3)
  best for all                AUROC 0.725  (PCA none, k 1)
chosen and frozen: channels screwdriver+tool, PCA 32, k 3 (validation AUROC 0.765); threshold 0.9157 = 5% false alarms on validation's normal operations
```

The channel groups are there because the robot arm's motion varies from hole to hole: using every channel can dilute
the screwdriver's own signal.

### Stage 6: test: embed in batch, score once

```sh
python embed/embed.py --roles test
python detect/detect.py test
```

### Stage 7: delivery: embed in batch, score afterwards

```sh
python embed/embed.py --roles delivery
python detect/detect.py deliver
```

Each writes `eval_out/<role>.json`, `scores_<role>.csv` and a plot `scores_<role>.png` (one point per operation, by
class, with the threshold).

## Results (dev, developer key, 2026-11-02)

Detection rate per anomaly type at the frozen thresholds, and AUROC against the role's normal operations:

| | validation (chooses) | test (once) | delivery (afterwards) |
|---|---|---|---|
| **missing screw** | 40% · AUROC 0.837 | **100% · AUROC 0.992** | **87% · AUROC 0.940** |
| damaged screw | 13% · 0.717 | 7% · 0.534 | 20% · 0.786 |
| extra component | 7% · 0.740 | 0% · 0.590 | (none recorded) |
| all anomalies | 20% · 0.765 | 42% · 0.727 | 53% · 0.863 |
| **false alarms on normal** | 5.0% (set) | **3.3%** | **1.7%** |

Detection is at the 5% threshold. At the 1% threshold, missing screws are still caught 80% of the time in both test and
delivery.

Reading it:
- **Missing screws are caught reliably,** with false alarms under the 5% target on unseen operations. Without a screw the
  torque profile is short and flat (median 233 rows of action against 490 for a normal tightening), which the embeddings
  separate clearly.
- **Damaged screws and extra components are mostly missed.** Their torque changes are subtle. The dataset's authors note
  strong variation within each class, and a check with hand-made torque features (peak, mean, action length) did worse
  on validation (AUROC 0.51–0.62 against 0.765). These faults need more than a distance to normal, for example labelled
  examples and a classifier (the Rare Event Detection agent's setting).
- **The thresholds held.** False alarms on test and delivery (3.3%, 1.7%) stayed at or under the 5% set on validation.
  Calibrating on held-out normal operations, rather than on the library's own scores, avoided the too-high threshold
  seen in the MetroPT-3 example.
- **The sample is small:** 15 operations per type, 8 extra components in test. A rate of 7% is one operation, so treat
  the subtle types' numbers as rough. Option M in `prep/common.py` (more operations per role) is the next step for firmer
  numbers.

## Attribution

AURSAD: Universal Robot Screwdriving Anomaly Detection Dataset, by Błażej Leporowski, Daniella Tola, Casper Hansen and
Alexandros Iosifidis (Aarhus University; Technicon ApS), [doi:10.5281/zenodo.4487073](https://doi.org/10.5281/zenodo.4487073),
[arXiv:2102.01409](https://arxiv.org/abs/2102.01409), licensed
[CC BY 4.0](https://creativecommons.org/licenses/by/4.0/). The files in `data/roles/` are derived from it; every change
is listed in [data/roles/NOTICE.md](data/roles/NOTICE.md).

## License

The code is licensed under the [Apache License 2.0](LICENSE). The data in `data/roles/` is derived from AURSAD and
licensed under [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/); see [data/roles/NOTICE.md](data/roles/NOTICE.md).

## Cleanup

```sh
python scripts/cleanup.py          # what would be deleted
python scripts/cleanup.py --yes    # sessions -> deployments -> packages -> blueprints -> project
```

A deployment must go before its package, and a package before its blueprint, or the delete returns 409. Uploaded files are
kept.
