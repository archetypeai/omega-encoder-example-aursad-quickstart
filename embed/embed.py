#!/usr/bin/env python3
"""Embed role files in batch with the Omega Encoder agent (Agent Lifecycle 2.0, developer key).

    python embed/embed.py --roles library --window 1024 512 256       # Stage 4
    python embed/embed.py --roles validation --window 1024 512 256    # Stage 5 (then detect/detect.py select)
    python embed/embed.py --roles test --window frozen                # Stage 6 (then detect/detect.py test)
    python embed/embed.py --roles delivery --window frozen            # Stage 7 (then detect/detect.py deliver)

One project; per window size W, one copy of `omega-embeddings` with window_size and step_size
set to W at copy time (`omega-aursad` for 1,024, as shipped; `omega-aursad-wW` otherwise),
one package and one batch deployment; then one batch session per role over that role's
files. Each file is one operation of 1,024 rows, so it yields 1024/W windows, matched back to
the file by their start timestamps (unique per file, checked in Stage 3). `frozen` is the
window detect/detect.py select froze in eval_out/settings.json.

Writes out/embed/wW/<role>.npz: files, emb [operations, windows, channels, 768]. Ids
(project, uploads, and per window the blueprint, package, deployment and sessions) are kept
in out/embed/state.json, so a rerun reuses everything it can and an unchanged role is not
embedded again. The uploads are shared by every window size.
`python scripts/cleanup.py` removes the platform objects.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
import atai_api as A  # noqa: E402

OUT = REPO / "out" / "embed"
STATE = OUT / "state.json"
PROJECT = "AURSAD Omega quickstart"
OPERATION_ROWS = 1024
_LOCK = threading.Lock()


def log(msg: str) -> None:
    print(f"{time.strftime('%H:%M:%S')} {msg}", flush=True)


def blueprint_key(window: int) -> str:
    return "omega-aursad" if window == OPERATION_ROWS else f"omega-aursad-w{window}"


def identity() -> str:
    """A fingerprint of the key and endpoint (never the key itself)."""
    return hashlib.sha256(f"{A.api_base()}|{os.environ['ATAI_API_KEY']}".encode()).hexdigest()[:12]


def load_state() -> dict:
    """Saved ids, or a fresh start when the key or endpoint changed: another account's
    project, uploads and embeddings are not this one's to reuse."""
    st = json.loads(STATE.read_text()) if STATE.exists() else {}
    if st and st.get("identity") != identity():
        log("API key or endpoint changed since the last run: starting fresh (old ids and embeddings discarded)")
        for old in OUT.glob("w*/*.npz"):
            old.unlink()
        st = {}
    st["identity"] = identity()
    st.setdefault("windows", {})
    return st


def save_state(st: dict) -> None:
    with _LOCK:
        OUT.mkdir(parents=True, exist_ok=True)
        STATE.write_text(json.dumps(st, indent=1))


def ensure_project(st: dict) -> str:
    if "project" not in st:
        found = [p for p in A.request("GET", f"{A.api_base()}/projects?limit=1000")["data"] if p["name"] == PROJECT]
        st["project"] = found[0]["id"] if found else A.request(
            "POST", f"{A.api_base()}/projects",
            body={"name": PROJECT, "description": "Omega Encoder agent + kNN anomaly detection on AURSAD"})["id"]
        save_state(st); log(f"project {st['project']}")
    return st["project"]


def ensure_package(st: dict, window: int) -> dict:
    """The window's blueprint copy and its package, reusing what exists."""
    ws = st["windows"].setdefault(str(window), {})
    key = blueprint_key(window)
    if "blueprint" not in ws:
        project = ensure_project(st)
        found = A.request("GET", f"{A.agents_base()}/blueprints?project_id={project}&key={key}")["data"]
        body = {"project_id": project, "blueprint_key": key}
        if window != OPERATION_ROWS:
            body["overrides"] = {"values": {"window_size": window, "step_size": window}}
        bp = found[0] if found else A.request("POST", f"{A.agents_base()}/blueprints/omega-embeddings/copy", body=body)
        ws["blueprint"] = bp["id"]; save_state(st); log(f"blueprint {key} {bp['id']}")
    values = A.request("GET", f"{A.agents_base()}/blueprints/{ws['blueprint']}")["document"]["values"]
    if (values["window_size"], values["step_size"]) != (window, window):
        sys.exit(f"blueprint {key} has window {values['window_size']}, step {values['step_size']}; expected {window}")
    pkg = ws.get("package")
    if not pkg or A.request("GET", A.packages_url(pkg))["status"] != "ready":
        ws["package"] = A.create_package(ws["blueprint"], key)["id"]; save_state(st); log(f"package {ws['package']}")
    return ws


def ensure_batch(st: dict, window: int) -> dict:
    ws = ensure_package(st, window)
    dpl = ws.get("deployment")
    if not dpl or A.request("GET", A.deployments_url(dpl))["status"] != "ready":
        ws["deployment"] = A.deploy(ws["package"], "batch")["id"]; save_state(st)
        log(f"batch deployment {ws['deployment']} (window {window})")
    return ws


def cache_key(p: Path) -> str:
    """Path plus content hash: a rebuilt role file is uploaded again, never reused stale."""
    return f"{p.relative_to(REPO)}:{hashlib.sha1(p.read_bytes()).hexdigest()[:12]}"


def upload_all(st: dict, paths: list[Path], jobs: int = 4) -> list[str]:
    cache = st.setdefault("uploads", {})
    keys = {p: cache_key(p) for p in paths}
    todo = [p for p in paths if keys[p] not in cache]
    if todo:
        log(f"uploading {len(todo)} files")
        with ThreadPoolExecutor(jobs) as pool:
            for key, fid in pool.map(lambda p: (keys[p], A.upload_file(str(p))["file_id"]), todo):
                with _LOCK:
                    cache[key] = fid
                save_state(st)                  # each finished upload survives a later failure
    return [cache[keys[p]] for p in paths]


def fetch_all_results(session_id: str, expected: int, settle_s: int = 600) -> list[dict]:
    """Every output of the session, re-fetched until the window count is exactly `expected`
    (a completed session can briefly return a partial artifact)."""
    deadline = time.time() + settle_s
    while True:
        # /results pages (100 by default): one output per input file, so follow next_cursor.
        items, cursor = [], None
        while True:
            page = A.request("GET", f"{A.sessions_url(session_id)}/results?limit=1000"
                             + (f"&after={cursor}" if cursor else ""))
            items += page.get("data", [])
            cursor = page.get("next_cursor")
            if not page.get("has_more") or not cursor:
                break
        rows = []
        for it in items:
            ref = (it.get("data") or {}).get("ref") or it.get("ref")
            payload = A._download(ref) if ref else None
            if payload:
                rows += [json.loads(line) for line in payload.decode().splitlines() if line.strip()]
        if len(rows) == expected:
            return rows
        if time.time() > deadline:
            sys.exit(f"{session_id}: {len(rows)} windows after {settle_s}s, expected {expected}")
        log(f"  {session_id}: {len(rows)}/{expected} windows; waiting")
        time.sleep(15)


def run_role(st: dict, window: int, role: str, m: dict) -> None:
    files = [f for f in m["files"] if f["role"] == role]
    paths = [REPO / f["path"] for f in files]
    out_path = OUT / f"w{window}" / f"{role}.npz"
    per_file = OPERATION_ROWS // window
    expected = len(files) * per_file
    run_key = hashlib.sha1("|".join(sorted(cache_key(p) for p in paths)).encode()).hexdigest()[:16]
    if out_path.exists() and str(np.load(out_path)["run_key"]) == run_key:
        log(f"{role} @ {window}: already embedded ({expected} windows)")
        return
    ws = ensure_batch(st, window)
    fids = upload_all(st, paths)
    key = f"{role}:{run_key}"
    sid = ws.setdefault("sessions", {}).get(key)
    if not sid:
        sid = A.open_session(ws["deployment"], fids)["id"]
        ws["sessions"][key] = sid; save_state(st)
        log(f"{role} @ {window}: batch session {sid} over {len(fids)} files, {expected} windows expected")
    t = time.time()
    status = A.poll_session(sid, timeout_s=6 * 3600, interval_s=20)
    if status != "completed":
        sys.exit(f"{role} @ {window}: session {sid} ended {status}")
    rows = fetch_all_results(sid, expected)
    by_start = {round(r["start_timestamp"], 2): r for r in rows}
    # Window k of a file starts k * window rows (10 ms each) after the file's first timestamp.
    starts = {Path(f["path"]).name: [round(f["start"] + k * window * m["step_s"], 2) for k in range(per_file)]
              for f in files}
    missing = [n for n, ss in starts.items() if any(s not in by_start for s in ss)]
    if missing:
        sys.exit(f"{role} @ {window}: windows missing at the expected start times of: {missing[:5]}")
    emb = np.asarray([[[by_start[s][c] for c in m["channels"]] for s in starts[Path(f["path"]).name]]
                      for f in files], dtype=np.float32)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(out_path, files=np.asarray([Path(f["path"]).name for f in files]), emb=emb,
                        run_key=np.asarray(run_key), window=np.asarray(window))
    log(f"{role} @ {window}: {expected} windows {emb.shape} in {time.time() - t:.0f}s -> {out_path.relative_to(REPO)}")


def windows_arg(values: list[str]) -> list[int]:
    out = []
    for v in values:
        if v == "frozen":
            p = REPO / "eval_out" / "settings.json"
            if not p.exists():
                sys.exit("--window frozen needs eval_out/settings.json: run detect/detect.py select first")
            out.append(int(json.loads(p.read_text())["window"]))
        elif v.isdigit() and int(v) > 0 and OPERATION_ROWS % int(v) == 0:
            out.append(int(v))
        else:
            sys.exit(f"--window takes divisors of {OPERATION_ROWS} or 'frozen' (got {v})")
    return list(dict.fromkeys(out))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--roles", nargs="+", required=True, choices=["library", "validation", "test", "delivery"])
    ap.add_argument("--window", nargs="+", default=["1024"],
                    help="window (and step) sizes, divisors of 1,024, or 'frozen' (default 1024)")
    args = ap.parse_args()
    windows = windows_arg(args.window)
    A.load_dotenv(str(REPO / ".env"))
    m = json.loads((REPO / "data" / "roles" / "manifest.json").read_text())
    log(f"endpoint {A.api_base()}")
    st = load_state()
    save_state(st)
    for window in windows:
        for role in args.roles:
            run_role(st, window, role, m)


if __name__ == "__main__":
    main()
