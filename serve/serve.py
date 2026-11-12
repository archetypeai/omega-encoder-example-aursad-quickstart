#!/usr/bin/env python3
"""Stage 8: serve the Omega Encoder agent, one operation per query, checked against Stage 7.

    python serve/serve.py              # every delivery operation, in recording order
    python serve/serve.py --limit 10   # the first 10

Stage 7 embeds the delivery in batch: upload, run a session, download when it is done.
Here the agent stays loaded and answers each operation in one round trip, as a robot cell
would ask right after a tightening:

1. The shipped copy's package (`omega-aursad`, window 1,024), deployed as **serving**.
2. A serving session whose `values` set window_size and step_size to the window
   detect/detect.py select froze: one deployment serves any window, per session.
3. Each delivery operation, in recording order, sent as one `/query` (its 1,024 rows of the
   12 channels, one list per channel). The answer is one record per window, `channel_0..11`
   in the file's column order, 768 numbers each. It is scored at once by the frozen
   detector against the batch library, and flagged if it crosses the frozen threshold.
4. Every answer checked against Stage 7: each window's embedding (cosine), each operation's
   score, and each alarm decision.
5. The session and the deployment are ended however the run ends (Ctrl-C and SIGTERM
   included): a serving deployment holds a worker until it is ended.

Labels are not read here: `python detect/detect.py deliver --source serving` scores the
served embeddings against them afterwards.

Writes out/serve/wW/delivery.npz (same layout as Stage 7's) and eval_out/serving/delivery.{csv,json}.
"""
from __future__ import annotations

import argparse
import json
import signal
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "embed"))
sys.path.insert(0, str(REPO / "detect"))
import atai_api as A  # noqa: E402
import detect as D  # noqa: E402
import embed as E  # noqa: E402

OUT = REPO / "eval_out" / "serving"


def log(msg: str) -> None:
    print(f"{time.strftime('%H:%M:%S')} {msg}", flush=True)


def query_body(df: pd.DataFrame, channels: list[str]) -> dict:
    return {"query": "", "events": [{"type": "data.numeric_array",
            "event_data": {"contents": [df[c].astype(float).tolist() for c in channels]}}]}


def windows_of(answer: dict, n_channels: int) -> np.ndarray:
    """[windows, channels, 768] from one answer, in window order."""
    records = (answer.get("response") or {}).get("data")
    if not isinstance(records, list) or not records:
        sys.exit(f"unexpected answer: {str(answer)[:300]}")
    records = sorted(records, key=lambda r: r.get("start_timestamp", 0))
    return np.asarray([[r[f"channel_{c}"] for c in range(n_channels)] for r in records], dtype=np.float32)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, help="serve only the first N delivery operations")
    args = ap.parse_args()
    cfg = D.settings()
    window = cfg["window"]
    A.load_dotenv(str(REPO / ".env"))
    log(f"endpoint {A.api_base()}")
    m = json.loads((REPO / "data" / "roles" / "manifest.json").read_text())
    files = sorted((f for f in m["files"] if f["role"] == "delivery"), key=lambda f: f["start"])[:args.limit]
    detector = D.Detector.frozen(cfg)
    log(f"frozen settings: {D.describe(cfg)}, threshold {cfg['threshold']:.4f}")

    st = E.load_state()
    left = st.get("serving") or {}
    for label, ident, fn in (("session", left.get("session"), A.end_session),
                             ("deployment", left.get("deployment"), A.end_deployment)):
        if ident:                             # a serving replay killed before its cleanup
            log(f"ending the serving {label} {ident} an earlier run left")
            fn(ident)
    st.pop("serving", None); E.save_state(st)
    ws = E.ensure_package(st, E.OPERATION_ROWS)          # the shipped copy, window 1,024
    signal.signal(signal.SIGTERM, lambda *_: (_ for _ in ()).throw(KeyboardInterrupt()))
    dpl = sid = None
    rows, embs = [], []
    try:
        dpl = A.request("POST", A.deployments_url(), body={
            "package_id": ws["package"], "kind": "serving", "sessions": {"max": 2}})["id"]
        st["serving"] = {"deployment": dpl}; E.save_state(st)
        A.deployment_ready(dpl)
        log(f"serving deployment {dpl} of {ws['package']} (omega-aursad, window 1,024) ready")
        sid = A.request("POST", A.sessions_url(), body={
            "deployment_id": dpl, "values": {"window_size": window, "step_size": window}})["id"]
        st["serving"]["session"] = sid; E.save_state(st)
        A.wait_running(sid)
        log(f"serving session {sid} with values window_size={window}, step_size={window}: running")
        for i, f in enumerate(files, 1):
            df = pd.read_csv(REPO / f["path"])
            t = time.time()
            answer = A.request("POST", f"{A.sessions_url(sid)}/query", body=query_body(df, m["channels"]),
                               idempotent=True)   # a repeated query only asks again
            latency = time.time() - t
            emb = windows_of(answer, len(m["channels"]))
            if len(emb) != E.OPERATION_ROWS // window:
                sys.exit(f"{f['path']}: {len(emb)} windows, expected {E.OPERATION_ROWS // window}")
            score = float(detector.score(D.joint(emb[None], cfg["group"]))[0])
            alarm = score > cfg["threshold"]
            name = Path(f["path"]).name
            rows.append({"file": name, "score": score, "alarm": alarm, "latency_s": round(latency, 3)})
            embs.append(emb)
            log(f"  {i:>3}/{len(files)} {name:<22} {len(emb)} window(s)  score {score:.4f}"
                f"{'  ALARM' if alarm else ''}  ({latency * 1000:.0f} ms)")
    except KeyboardInterrupt:
        log("interrupted")
    finally:
        ended = True
        for label, fn in (("session", lambda: A.end_session(sid)), ("deployment", lambda: A.end_deployment(dpl))):
            if (sid if label == "session" else dpl):
                try:
                    fn()
                except BaseException as e:
                    ended = False
                    log(f"could not end the serving {label}: {str(e)[:200]} (run scripts/cleanup.py)")
        if ended:                             # otherwise the ids stay for the next run and cleanup.py
            st.pop("serving", None); E.save_state(st)
        if dpl:
            log(f"ended serving session {sid} and deployment {dpl}")
    if not rows:
        return

    served = pd.DataFrame(rows)
    names = served["file"].tolist()
    emb = np.asarray(embs)
    out = REPO / "out" / "serve" / f"w{window}"
    out.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(out / "delivery.npz", files=np.asarray(names), emb=emb, window=np.asarray(window))
    OUT.mkdir(parents=True, exist_ok=True)
    lat = served["latency_s"].to_numpy()
    summary = {"window": window, "operations": len(served), "alarms": int(served["alarm"].sum()),
               "latency_s": {"median": float(np.median(lat)), "p95": float(np.quantile(lat, 0.95)),
                             "max": float(lat.max())}}
    print(f"\nStage 8: {len(served)} delivery operations served in {len(served)} queries, window {window} "
          f"({emb.shape[1]} per operation); {summary['alarms']} alarm(s)")
    print(f"  latency per query: median {summary['latency_s']['median'] * 1000:.0f} ms, "
          f"p95 {summary['latency_s']['p95'] * 1000:.0f} ms, max {summary['latency_s']['max'] * 1000:.0f} ms")

    batch_path = D.batch_dir(window) / "delivery.npz"
    if batch_path.exists():
        z = np.load(batch_path)
        idx = {str(n): i for i, n in enumerate(z["files"])}
        b = z["emb"][[idx[n] for n in names]]
        b = b[:, None] if b.ndim == 3 else b
        cos = (b * emb).sum(-1) / np.linalg.norm(b, axis=-1) / np.linalg.norm(emb, axis=-1)
        bscore = detector.score(D.joint(b, cfg["group"]))
        balarm = bscore > cfg["threshold"]
        same = int((balarm == served["alarm"].to_numpy()).sum())
        rel = np.abs(bscore - served["score"].to_numpy()) / np.abs(bscore)
        served["batch_score"], served["batch_alarm"] = bscore, balarm
        summary["against_batch"] = {"cosine_min": float(cos.min()), "cosine_median": float(np.median(cos)),
                                    "alarm_agreement": same, "score_max_relative_difference": float(rel.max())}
        print(f"  against Stage 7 (batch): embeddings cosine min {cos.min():.6f} (median {np.median(cos):.6f}) "
              f"over {cos.size} window-channels; alarm identical in {same}/{len(served)}; "
              f"score max relative difference {rel.max():.1e}")
    else:
        print(f"  {batch_path.relative_to(REPO)} not found: run Stage 7 to check serving against batch")
    served.to_csv(OUT / "delivery.csv", index=False)
    (OUT / "delivery.json").write_text(json.dumps(summary, indent=1))
    print("wrote eval_out/serving/delivery.csv, delivery.json and out/serve/"
          f"w{window}/delivery.npz (score it: python detect/detect.py deliver --source serving)")


if __name__ == "__main__":
    main()
