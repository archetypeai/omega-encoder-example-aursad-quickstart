# Omega AURSAD Monitor, served from the platform

A live monitoring workbench for the quickstart's detector. Stage 7's delivery is replayed one
screwdriving operation at a time, as if the robot cell were running now. Each tightening goes to a
**serving session of the Omega Encoder agent** on the Archetype AI platform, and the bridge scores
the embeddings with the **kNN detector Stage 5 froze**. The answers appear as the 12 live channels,
the operation's window scores, an embedding space, and the delivery's scores so far.

> **It holds a serving deployment while it runs,** and ends it when you stop it. On dev
> (2026-11-06) the deployment was ready in ~5 s, a tightening was answered in ~1.3 s (median),
> and the whole delivery took ~3 min at 16×. It also runs on staging (2026-11-09).

## Architecture

```
  data/roles/delivery/*.csv                                                     repo .env: ATAI_API_KEY
            │                                                                              │
            ▼                                                                              ▼
┌──────────────────────────┐   aursad/raw (blocks of rows)   ┌──────────────────────────────────────┐
│ replayer (node)          │────────────────────────────────▶│ serving bridge (node)                │
│ one tightening at a time,│   aursad/op (start / end)       │ the API key stays here;              │  POST /query: 12 × 1,024
│ in recording order,      │                                 │ buffers the operation, sends it      │────────────────────────┐
│ at 1×, 4× or 16×;        │◀────────────────────────────────│ whole when it ends                   │                        ▼
│ waits for each answer    │   omega/results (paces it)      │                                      │   ┌────────────────────────────────────┐
└──────────────────────────┘                                 │ kNN detector (frozen, from out/app/) │   │ serving session (window = frozen)  │
  pub │ aursad/status, aursad/labels (retained)              │ scores the 4 windows it gets back    │◀──│ of a serving deployment of the     │
  sub ▲ aursad/control                                       └──────────────────────────────────────┘   │ shipped omega-aursad package       │
      │                                                        pub │ omega/results, omega/history,      └────────────────────────────────────┘
      │                                                            │ omega/agent (retained)                 4 records × 12 channels × 768
┌─────────────────────────────────────────────────────────────────────────────────────────────┐
│                         mosquitto · TCP :1893 · WebSockets :9011                            │
└─────────────────────────────────────────────────────────────────────────────────────────────┘
          sub ▼ everything above                       pub ▲ aursad/control (play, pause, restart, reveal, pace)
                web app (SvelteKit, :5183, mqtt.js over ws): 12 channels · operation · embedding space · alarms · score
```

- **The same lifecycle as Stage 8** (`serve/serve.py`). The bridge deploys the shipped copy's
  package (`omega-aursad`, window 1,024) as **serving**. It then opens one serving session whose
  `values` set `window_size` and `step_size` to the window Stage 5 froze (256).
- **The detector runs in the bridge.** The agent returns embeddings only: one record per window,
  with `channel_0..11` (the file's column order) mapped to 768 numbers each.
  `scripts/detector.js` is `detect.py`'s frozen kNN in JavaScript. It matches Python to about
  1e-7 on the same embeddings.
- **Every score is checked against Stage 7.** The export includes each delivery operation's
  batch score. The bridge logs the relative difference for every operation (at most 6.5e-4 over
  the delivery), and the page shows it under the window bars.
- **A query is one operation.** A served session keeps nothing between queries, so the bridge
  buffers the operation's 1,024 rows and sends them as one query when the replayer says the
  operation has ended. That is a whole number of windows, and never fewer rows than one window
  (fewer gets a 503).
- **Labels are held back, as in Stage 7.** They go out on `aursad/labels` only when you click
  Reveal labels in Settings, or when the delivery has played to the end. They never colour a
  score: a false alarm looks like one.
- **The API key never reaches the browser.** The bridge reads `ATAI_API_ENDPOINT` and
  `ATAI_API_KEY` from the repo's `.env`, the same file the Python stages use. As in
  `atai_api.py`, those lines win over anything exported in the shell. An `ATAI_*` line in
  `app-serving/.env` is ignored.
- **It holds the deployment for as long as it runs, and says what it's doing.** Starting
  retries (15 s, doubling to 2 min) while no serving worker is free. On dev, a session closes after
  30 idle minutes and a deployment stops after 20. If that happens during a long pause, the bridge
  replaces both on the next operation. The phase (starting, waiting, running, replacing, stopped)
  goes out on `omega/agent`, retained, and shows in the menubar badge and in Settings. An MQTT
  will clears a stale "running" if the bridge is killed.

## The detector and the embedding space: exported, not recomputed

```sh
python app-serving/scripts/export_detector.py     # from the repo root, venv active; no platform call
```

It reads `eval_out/settings.json` (Stage 5) and `out/embed/w<W>/library.npz` (Stage 4), and
writes:
- **`out/app/detector.{json,bin}`**, for the bridge: the library's 600 windows (150 normal
  tightenings × 4) at the frozen window, already normalised and projected the way `detect.py`
  does it, plus k, match, the thresholds, and every delivery operation's Stage 7 score for the
  check. 11 MB, not committed.
- **`static/library-view.json`**, for the page: PCA 1–2 of those 600 windows in the detector's
  space, whitened, about 37% of the variance. Each live window goes through the same projection
  in the bridge.

Unlike the AD TEP app, there's nothing to recompute on the platform: Stage 4 already has the
library's embeddings, because embeddings are what the Omega Encoder agent returns. Run the export
again only after `select` freezes different settings.

## Run it

Prerequisites: Node 20+, `brew install mosquitto`, and Stages 4–7 run with the key in the repo's
`.env`. Stage 7's delivery embeddings are only needed for the check. Then, from the repo root:

```sh
python app-serving/scripts/export_detector.py     # once (writes out/app/ and static/library-view.json)
cd app-serving
npm install
npm run dev                                       # broker + serving bridge + replayer + web
open http://localhost:5183
```

Press **Run agent**. The badge reads `platform · serving` once the bridge's session is running,
about 5–10 s after start. When you're done, stop it and check it cleaned up: see
[Stop and clean up](#stop-and-clean-up).

**Expect** in the `npm run dev` terminal: one line per tightening, against Stage 7:

```
bridge: serving deployment dpl_… (package pkg_…), session ses_… at window 256: running
bridge: delivery_3444.csv  score 2.0798  ALARM  (Stage 7 batch 2.0799, rel. diff 4.3e-5)  1514 ms
bridge: delivery_3452.csv  score 1.9425  ALARM  (Stage 7 batch 1.9423, rel. diff 6.0e-5)  1278 ms
bridge: delivery_3472.csv  score 1.3503  (Stage 7 batch 1.3503, rel. diff 4.6e-5)  1352 ms
…
replayer: all 90 delivery operations played; labels revealed
```

At the end, the totals under the score chart read **Alarms 24, Caught 19 / 30, False alarms
5 / 60**: Stage 7's delivery result (93% of missing screws and 33% of damaged screws caught,
8.3% false alarms).

### What's on the page

The same workbench as the sibling monitors (AD TEP, OSM LARCO, RED pump): what goes into the
agent on the left, what comes out on the right.

| Where | What |
|---|---|
| **Input** (left) | The session selector (sessions 14–18, or one of them) in the caption. **Tightening:** the current tightening's 12 channels as it's replayed, labelled by the agent's 4 windows (before · driving · finishing · after). Traces are in library sigmas, with the latest value in engineering units, and the window that set the score is shaded once it's scored. The Arm channels are muted: the agent embeds them, but the frozen detector doesn't compare them. **Replay:** the tightening count, the position in the replay and the pace. |
| **Robot cell** (default view) | The cell as a line drawing: the arm, the screwdriver and the workpiece plate, with callouts 1–4 (screwdriver torque, tool force, tool accelerometer, joint currents) and their live values in the key. The bit turns while the torque is on, and the screw takes the last call's colour. |
| **Embedding space** | The 600 library windows (grey), the last tightening's 4 windows (numbered, joined in order) and the 12 before it as a fading trail. Two of 4,608 dimensions: a window far from the cloud here is far from it, but one inside it can still be far in the others. |
| **Alarms** | One row per alarmed tightening, newest first, with its worst window. Once revealed, the label column turns false alarms into "normal (false alarm)". |
| **Detection state** | **Current:** the call on the last tightening (normal / alarm) with its score against the threshold; **Alarms:** how many so far. Then that tightening's 4 window scores, and a strip with one chip per tightening of the replay, oldest left, green or red by the detector's call. Once revealed, a faulty tightening is underlined, so a red chip with no line is a false alarm and a green one with a line was missed. Totals: scored, caught, false alarms, time per tightening. |
| **Settings** (gear) | **Agent:** the phase, the serving session and deployment, the package and session values, and the detector's settings. **Pace** and **Restart the replay**. **Labels:** reveal. **This replay:** scored, alarms, errors (and caught / false alarms once revealed). **Live data flow:** each topic's rate as this tab sees it, and the processes between them. |

### Pace

The replayer sends a tightening at a chosen speed, then waits for its answer before the next.

| Pace | A tightening takes | The delivery (90) takes |
|---|---|---|
| real time | 10.24 s + ~1.3 s for the answer | ~17 min |
| **4×** (default) | 2.6 s + ~1.3 s | ~6 min |
| 16× | 0.6 s + ~1.3 s | ~3 min |

A tightening scores the same at any pace: the pace only decides how fast its rows are sent.

## Stop and clean up

A running app holds a serving deployment, and so a serving worker, until the bridge ends it or
the platform stops it after 20 idle minutes (dev). Closing the browser tab doesn't stop it.

1. **Stop the app.** Press Ctrl-C **once** in the `npm run dev` terminal and wait for
   `bridge: ended session ses_… and deployment dpl_…`; a second Ctrl-C can cut that short. Or,
   from `app-serving/` in any terminal:

   ```sh
   npm run stop      # SIGTERM to the bridge, waits up to 60 s for it, stops the rest, checks the ports
   ```

   It ends with `all ports free (1893 · 9011 · 5183)`. A port still held names its process.

2. **If something was left** (the bridge was killed with `kill -9`, the machine slept, or it
   printed `not everything was ended`), the ids are in `out/app_serving_state.json`. The next
   `npm run dev` ends them before it starts. Or, from the repo root, `python scripts/cleanup.py`
   lists every serving deployment of the project that still holds a worker (`--yes` deletes the
   whole project; see the [repo README](../README.md#clean-up-the-platform)).

## Ports

| MQTT TCP | MQTT WS | Web |
|---|---|---|
| 1893 | 9011 | 5183 |

They follow the canonical-agent apps' allocation, past the AD TEP served app (1890 / 9008 /
5180) and the two slots after it, so they can run side by side. To change them, copy
`.env.example` to `.env`.

## Layout

| Path | What |
|---|---|
| `scripts/export_detector.py` | Writes the frozen detector for the bridge (`out/app/`) and the library view for the page (`static/library-view.json`). |
| `scripts/detector.js` | `detect.py`'s frozen kNN in JavaScript: joint states, window scores, operation score, view projection. |
| `scripts/serving-bridge.js` | The agent's local end: the serving deployment and session, one query per tightening, scoring, the check against Stage 7. |
| `scripts/replayer.js` | Replays Stage 7's delivery one tightening at a time, paced by the agent, with the labels held back. |
| `scripts/common.js` | The repo, the two `.env` files. |
| `scripts/run-broker.sh`, `scripts/stop.sh`, `mosquitto/` | The broker on 1893 / 9011, and stopping everything (matched by `--app=aursad-serving`, so other demos are left alone). |
| `src/` | The SvelteKit workbench on the Archetype AI design system (0.19): the labs Menubar, Pane captions, segmented Tabs, Table, Progress, Dialog. |
| `CLAUDE.md`, `ds-manifest.json` | The design system's rules and component catalogue for a coding agent, from the AD TEP app. |

## Licence and data

The same as the repo: code under the [Apache License 2.0](../LICENSE); the data is derived from
AURSAD (CC BY 4.0), see [data/roles/NOTICE.md](../data/roles/NOTICE.md).
