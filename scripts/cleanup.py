#!/usr/bin/env python3
"""Delete everything embed/embed.py made on the platform.

    python scripts/cleanup.py            # list what would be deleted
    python scripts/cleanup.py --yes      # delete it

Works from the project, not just the state file, so it also finds what a killed run
left behind: each package's deployments and their sessions, then the packages, the
blueprint copy and the project. A second run finds nothing left. Uploaded files are kept.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
import atai_api as A  # noqa: E402

STATE = REPO / "out" / "embed" / "state.json"
PROJECT = "AURSAD Omega quickstart"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--yes", action="store_true", help="actually delete")
    args = ap.parse_args()
    A.load_dotenv(str(REPO / ".env"))
    projects = [p["id"] for p in A.request("GET", f"{A.api_base()}/projects?limit=1000")["data"] if p["name"] == PROJECT]
    if not projects:
        print("nothing left")
        return
    for prj in projects:
        packages = A.request("GET", f"{A.packages_url()}?project_id={prj}&limit=1000")["data"]
        deployments = A.request("GET", f"{A.deployments_url()}?project_id={prj}&limit=1000")["data"]
        sessions = []
        for d in deployments:
            sessions += A.request("GET", f"{A.sessions_url()}?deployment_id={d['id']}&limit=1000")["data"]
        blueprints = A.request("GET", f"{A.agents_base()}/blueprints?project_id={prj}&limit=1000")["data"]
        blueprints = [b for b in blueprints if b.get("project_id") == prj]
        print(f"project {prj}: {len(sessions)} sessions, {len(deployments)} deployments, "
              f"{len(packages)} packages, {len(blueprints)} blueprints")
        if not args.yes:
            continue
        failed = []

        def attempt(label: str, fn) -> None:
            try:
                fn()
            except SystemExit as e:                   # atai_api exits on an HTTP error
                failed.append(f"{label}: {str(e)[:200]}")

        for s in sessions:
            attempt(f"session {s['id']}", lambda: A.end_session(s["id"]))
        for d in deployments:
            attempt(f"deployment {d['id']}", lambda: A.end_deployment(d["id"]))
        for p in packages:
            attempt(f"package {p['id']}", lambda: A.request("DELETE", A.packages_url(p["id"]), raw=True))
        # Promoted blueprints first: a copy can't go while a blueprint promoted from it remains.
        for b in sorted(blueprints, key=lambda b: "-otr_" not in b["blueprint_key"]):
            attempt(f"blueprint {b['blueprint_key']}", lambda: A.request(
                "DELETE", f"{A.agents_base()}/blueprints/{b['id']}", raw=True))
        attempt(f"project {prj}", lambda: A.request("DELETE", f"{A.api_base()}/projects/{prj}", raw=True))
        if failed:
            print(f"project {prj}: {len(failed)} objects could not be deleted:")
            for f in failed:
                print(f"  {f}")
            print("  Delete what is listed, or ask an org admin if it is a promoted blueprint.")
        else:
            print(f"deleted project {prj} and everything in it")
    if args.yes and STATE.exists():
        st = json.loads(STATE.read_text())
        STATE.write_text(json.dumps({"uploads": st.get("uploads", {})}, indent=1))   # keep upload cache
    if not args.yes:
        print("dry run; pass --yes to delete")


if __name__ == "__main__":
    main()
