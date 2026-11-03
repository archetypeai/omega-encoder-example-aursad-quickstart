#!/usr/bin/env python3
"""Embed role files with the Omega Encoder agent (Agent Lifecycle 2.0, developer key).

    python embed/embed.py --roles library       # Stage 4
    python embed/embed.py --roles validation    # Stage 5 (then detect/detect.py select)
    python embed/embed.py --roles test          # Stage 6 (then detect/detect.py test)
    python embed/embed.py --roles delivery      # Stage 7 (then detect/detect.py deliver)

project -> copy of `omega-embeddings` (as shipped: window 1024, step 1024, every numeric
column, first column = timestamp) -> package -> batch deployment -> one session per role
over that role's files. Each file is one operation of exactly 1,024 rows, so the agent
returns exactly one window per file; windows are matched back to files by their start
timestamp (unique per file, checked in Stage 3).

Writes out/embed/<role>.npz: files, emb [n, channels, 768]. State (project, package,
deployment, uploads, sessions) is kept in out/embed/state.json, so a rerun reuses
everything it can; an unchanged role is not embedded again.
`python scripts/cleanup.py` removes the platform objects.
"""
from __future__ import annotations

import argparse
import hashlib
import json
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
KEY = "omega-aursad"
_LOCK = threading.Lock()


def log(msg: str) -> None:
    print(f"{time.strftime('%H:%M:%S')} {msg}", flush=True)


def identity() -> str:
    """A fingerprint of the key and endpoint (never the key itself)."""
    import os
    return hashlib.sha256(f"{A.api_base()}|{os.environ['ATAI_API_KEY']}".encode()).hexdigest()[:12]


def load_state() -> dict:
    """Saved ids, or a fresh start when the key or endpoint changed: another account's
    project, uploads and embeddings are not this one's to reuse."""
    st = json.loads(STATE.read_text()) if STATE.exists() else {}
    if st and st.get("identity") != identity():
        log("API key or endpoint changed since the last run: starting fresh (old ids and embeddings discarded)")
        for old in OUT.glob("*.npz"):
            old.unlink()
        st = {}
    st["identity"] = identity()
    return st


def save_state(st: dict) -> None:
    with _LOCK:
        OUT.mkdir(parents=True, exist_ok=True)
        STATE.write_text(json.dumps(st, indent=1))


def ensure_agent(st: dict) -> None:
    """Project, blueprint copy, package and batch deployment, reusing what exists."""
    if "project" not in st:
        found = [p for p in A.request("GET", f"{A.api_base()}/projects?limit=1000")["data"] if p["name"] == PROJECT]
        st["project"] = found[0]["id"] if found else A.request(
            "POST", f"{A.api_base()}/projects",
            body={"name": PROJECT, "description": "Omega Encoder agent + kNN anomaly detection on AURSAD"})["id"]
        save_state(st); log(f"project {st['project']}")
    if "blueprint" not in st:
        found = A.request("GET", f"{A.agents_base()}/blueprints?project_id={st['project']}&key={KEY}")["data"]
        bp = found[0] if found else A.request(
            "POST", f"{A.agents_base()}/blueprints/omega-embeddings/copy",
            body={"project_id": st["project"], "blueprint_key": KEY})
        st["blueprint"] = bp["id"]; save_state(st); log(f"blueprint {KEY} {bp['id']}")
    pkg = st.get("package")
    if not pkg or A.request("GET", A.packages_url(pkg))["status"] != "ready":
        st["package"] = A.create_package(st["blueprint"], KEY)["id"]; save_state(st); log(f"package {st['package']}")
    dpl = st.get("deployment")
    if not dpl or A.request("GET", A.deployments_url(dpl))["status"] != "ready":
        st["deployment"] = A.deploy(st["package"], "batch")["id"]; save_state(st); log(f"batch deployment {st['deployment']}")


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


def run_role(st: dict, role: str, m: dict) -> None:
    files = [f for f in m["files"] if f["role"] == role]
    paths = [REPO / f["path"] for f in files]
    out_path = OUT / f"{role}.npz"
    run_key = hashlib.sha1("|".join(sorted(cache_key(p) for p in paths)).encode()).hexdigest()[:16]
    if out_path.exists() and str(np.load(out_path)["run_key"]) == run_key:
        log(f"{role}: already embedded ({len(files)} windows)")
        return
    fids = upload_all(st, paths)
    key = f"{role}:{run_key}"
    sid = st.setdefault("sessions", {}).get(key)
    if not sid:
        sid = A.open_session(st["deployment"], fids)["id"]
        st["sessions"][key] = sid; save_state(st)
        log(f"{role}: session {sid} over {len(fids)} files, {len(files)} windows expected")
    t = time.time()
    status = A.poll_session(sid, timeout_s=6 * 3600, interval_s=20)
    if status != "completed":
        sys.exit(f"{role}: session {sid} ended {status}")
    rows = fetch_all_results(sid, len(files))
    by_start = {round(r["start_timestamp"], 2): r for r in rows}
    missing = [Path(f["path"]).name for f in files if round(f["start"], 2) not in by_start]
    if missing:
        sys.exit(f"{role}: no window starting at these files' first timestamp: {missing[:5]}")
    emb = np.asarray([[by_start[round(f["start"], 2)][c] for c in m["channels"]] for f in files], dtype=np.float32)
    np.savez_compressed(out_path, files=np.asarray([Path(f["path"]).name for f in files]), emb=emb,
                        run_key=np.asarray(run_key))
    log(f"{role}: {len(files)} windows {emb.shape} in {time.time() - t:.0f}s -> {out_path.relative_to(REPO)}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--roles", nargs="+", required=True, choices=["library", "validation", "test", "delivery"])
    args = ap.parse_args()
    A.load_dotenv(str(REPO / ".env"))
    m = json.loads((REPO / "data" / "roles" / "manifest.json").read_text())
    log(f"endpoint {A.api_base()}")
    st = load_state()
    save_state(st)
    ensure_agent(st)
    for role in args.roles:
        run_role(st, role, m)


if __name__ == "__main__":
    main()
