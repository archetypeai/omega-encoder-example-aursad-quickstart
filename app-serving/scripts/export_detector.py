#!/usr/bin/env python3
"""Export the frozen kNN detector for the app's serving bridge, and the library cloud for the page.

    python app-serving/scripts/export_detector.py      # from the repo root, venv active

Reads eval_out/settings.json (Stage 5) and out/embed/w<W>/library.npz (Stage 4): no platform
call. The Omega Encoder agent returns embeddings only, so the detector runs in the bridge, and
this is the detector detect/detect.py froze, written out for JavaScript:

- out/app/detector.{json,bin}: the library's joint states at the frozen window, already
  normalised and projected (mean, then PCA if the settings use it), with k, match and the
  thresholds. Plus, as a check, every delivery operation's score from Stage 7's batch
  embeddings: the bridge compares its own score for the same operation against it.
- app-serving/static/library-view.json: PCA 1-2 of the library's windows in the detector's
  space, for the embedding view, and the two axes to project live windows onto.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "detect"))
import detect as D  # noqa: E402

OUT = REPO / "out" / "app"
VIEW = REPO / "app-serving" / "static" / "library-view.json"


def main() -> None:
    cfg = D.settings()
    window, group = cfg["window"], cfg["group"]
    files, lib = D.load("library", window, group)                  # [n, w, d], each channel L2-normalised
    det = D.Detector(lib, cfg["pca"], cfg["k"], cfg["match"])
    proj = det.lib.astype(np.float32)                              # [n, w, p]
    n, w, p = proj.shape

    flat = proj.reshape(-1, p)
    view_mean = flat.mean(0)
    _, sv, vt = np.linalg.svd(flat - view_mean, full_matrices=False)
    axes = vt[:2]                                                  # [2, p]
    coords = (flat - view_mean) @ axes.T
    scale = coords.std(0)
    coords /= scale                                                # whitened: unit spread per axis

    expected = {}
    batch = D.batch_dir(window) / "delivery.npz"
    if batch.exists():
        dfiles, x = D.load("delivery", window, group)
        expected = {f: round(float(s), 6) for f, s in zip(dfiles, det.score(x))}

    blobs = {"mean": det.mean.astype(np.float32), "library": proj,
             "view_mean": view_mean.astype(np.float32), "view_axes": (axes / scale[:, None]).astype(np.float32)}
    if det.proj is not None:
        blobs["proj"] = det.proj.astype(np.float32)                # [d, p]
    layout, offset, parts = {}, 0, []
    for name, a in blobs.items():
        a = np.ascontiguousarray(a, dtype="<f4")
        layout[name] = {"offset": offset, "shape": list(a.shape)}
        parts.append(a.tobytes())
        offset += a.nbytes
    channels = cfg["channels"]
    manifest = json.loads((REPO / "data" / "roles" / "manifest.json").read_text())
    meta = {"window": window, "windows_per_operation": w, "group": group, "channels": channels,
            "channel_index": [manifest["channels"].index(c) for c in channels], "embedding_dim": 768,
            "dim": int(det.mean.shape[0]), "projected_dim": p, "k": cfg["k"], "match": cfg["match"],
            "pca": cfg["pca"], "threshold": cfg["threshold"], "thresholds": cfg["thresholds"],
            "far_target": cfg["far_target"], "validation_auroc": cfg["validation_auroc"],
            "library_operations": n, "layout": layout, "expected_delivery_scores": expected}
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "detector.bin").write_bytes(b"".join(parts))
    (OUT / "detector.json").write_text(json.dumps(meta, indent=1))

    view = {"window": window, "windows_per_operation": w, "group": group,
            "explained": [round(float(v), 4) for v in (sv[:2] ** 2 / (sv ** 2).sum())],
            "points": [[round(float(a), 4), round(float(b), 4), i % w] for i, (a, b) in enumerate(coords)]}
    VIEW.write_text(json.dumps(view))
    print(f"detector: window {window}, {group}, PCA {cfg['pca'] or 'none'}, k {cfg['k']}, match {cfg['match']}, "
          f"threshold {cfg['threshold']:.4f}; library {n} operations x {w} windows, {p}-d")
    print(f"wrote out/app/detector.json, detector.bin ({offset / 1e6:.1f} MB)"
          + (f", with {len(expected)} delivery scores to check against" if expected else
             "; no Stage 7 delivery embeddings, so the bridge has nothing to check its scores against"))
    print(f"wrote app-serving/static/library-view.json: {n * w} library windows in PCA 1-2 "
          f"({view['explained'][0]:.0%} + {view['explained'][1]:.0%} of the variance)")


if __name__ == "__main__":
    main()
