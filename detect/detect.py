#!/usr/bin/env python3
"""Your own anomaly detector (kNN) over the Omega Encoder agent's embeddings.

    python detect/detect.py select                    # Stage 5: choose the settings on validation, freeze them
    python detect/detect.py test                      # Stage 6: score test once (batch embeddings)
    python detect/detect.py deliver                   # Stage 7: score the delivery afterwards (batch embeddings)
    python detect/detect.py deliver --source serving  # the same, from Stage 8's served embeddings

The protocol, fixed before anything was scored:
- An operation (1,024 rows) is embedded as 1,024/W consecutive windows of W rows. Each
  window's joint state is its channels' 768-d embeddings, each L2-normalised, concatenated;
  optionally PCA, fitted on the library's windows.
- A window's score is its mean distance to the k nearest library windows: any library window
  (match "any"), or only those at the same position in their operation (match "position";
  operations are aligned, 256 rows before the torque rises). An operation's score is its
  worst window.
- `select` tries every window size embedded for both library and validation, every channel
  group, PCA, k and match, keeps the best validation AUROC (normal vs. every anomaly), then
  sets the threshold to a FAR_TARGET (5%) false-alarm rate on validation's normal operations:
  data the library has not seen. Thresholds for 1% and 2% are set the same way and reported
  beside it. All of it is frozen in eval_out/settings.json.
- `test` and `deliver` read settings.json and never change it. They report, per anomaly type,
  the detection rate at each frozen threshold and AUROC against the role's normal
  operations; and the false-alarm rate on its normal operations.

Labels come from data/roles/labels/<role>.json, read only by the command that scores that role.
"""
from __future__ import annotations

import argparse
import itertools
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "prep"))
from common import CANDIDATE_WINDOWS as WINDOWS  # noqa: E402

ROLES = REPO / "data" / "roles"
EVAL = REPO / "eval_out"
SERVED = REPO / "out" / "serve"
FAR_TARGET = 0.05
FAR_REPORTED = (0.01, 0.02, 0.05)
GRID = {"pca": [16, 32, 64, 0], "k": [1, 3, 5, 10]}
# Channel groups, by what they measure. The anomalies act on the screw, so the screwdriver's
# own torque may carry them better than the robot arm's motion, which varies from hole to hole.
GROUPS = {
    "screwdriver": ["torque_current", "torque_achieved"],
    "screwdriver+tool": ["torque_current", "torque_achieved", "tcp_force_z", "tool_acc_x", "tool_acc_y", "tool_acc_z"],
    "all": None,                                      # every channel in the manifest
}
CHANNELS = json.loads((ROLES / "manifest.json").read_text())["channels"]


def batch_dir(window: int) -> Path:
    """Where embed/embed.py --window W writes its batch embeddings."""
    return REPO / "out" / "embed" / f"w{window}"


def joint(emb: np.ndarray, group: str) -> np.ndarray:
    """[operations, windows, channels, 768] (or [operations, channels, 768] for one window)
    -> joint states [operations, windows, d]."""
    e = emb[:, None] if emb.ndim == 3 else emb
    e = e[:, :, [CHANNELS.index(c) for c in (GROUPS[group] or CHANNELS)]]
    e = e / np.maximum(np.linalg.norm(e, axis=3, keepdims=True), 1e-8)
    return e.reshape(e.shape[0], e.shape[1], -1)


def load(role: str, window: int, group: str = "all", source: str = "batch") -> tuple[list[str], np.ndarray]:
    path = (SERVED / f"w{window}" if source == "serving" else batch_dir(window)) / f"{role}.npz"
    if not path.exists():
        hint = ("serve/serve.py" if source == "serving"
                else f"embed/embed.py{'' if window == 1024 else f' --window {window}'} --roles {role}")
        sys.exit(f"{path.relative_to(REPO)} not found: run {hint}")
    z = np.load(path)
    got = int(z["window"]) if "window" in z else 1024
    if got != window:
        sys.exit(f"{path.relative_to(REPO)} was embedded at window {got}, the settings say {window}")
    return [str(f) for f in z["files"]], joint(z["emb"], group)


def labels(role: str, files: list[str]) -> np.ndarray:
    lab = {o["file"]: o["class"] for o in json.loads((ROLES / "labels" / f"{role}.json").read_text())["operations"]}
    return np.asarray([lab[f] for f in files])


class Detector:
    """kNN over library windows; an operation scores as its worst window."""

    def __init__(self, lib: np.ndarray, pca: int, k: int, match: str = "any"):
        flat = lib.reshape(-1, lib.shape[-1])
        self.mean = flat.mean(0)
        self.proj = np.linalg.svd(flat - self.mean, full_matrices=False)[2][:pca].T if pca else None
        self.lib, self.k, self.match = self._project(lib), k, match

    @classmethod
    def frozen(cls, cfg: dict) -> "Detector":
        _, lib = load("library", cfg["window"], cfg["group"])
        return cls(lib, cfg["pca"], cfg["k"], cfg["match"])

    def _project(self, x: np.ndarray) -> np.ndarray:
        x = x - self.mean
        return x @ self.proj if self.proj is not None else x

    @staticmethod
    def _knn(x: np.ndarray, ref: np.ndarray, k: int) -> np.ndarray:
        d = np.sqrt(np.maximum((x ** 2).sum(1)[:, None] + (ref ** 2).sum(1)[None] - 2 * x @ ref.T, 0))
        return np.sort(d, axis=1)[:, :k].mean(1)

    def window_scores(self, x: np.ndarray) -> np.ndarray:
        x = self._project(x)
        n, w, _ = x.shape
        if self.match == "position":
            return np.stack([self._knn(x[:, j], self.lib[:, j], self.k) for j in range(w)], 1)
        return self._knn(x.reshape(n * w, -1), self.lib.reshape(-1, self.lib.shape[-1]), self.k).reshape(n, w)

    def score(self, x: np.ndarray) -> np.ndarray:
        return self.window_scores(x).max(1)


def settings() -> dict:
    p = EVAL / "settings.json"
    if not p.exists():
        sys.exit("eval_out/settings.json not found: run Stage 5 (detect/detect.py select) first")
    return json.loads(p.read_text())


def auroc(pos: np.ndarray, neg: np.ndarray) -> float:
    if not len(pos) or not len(neg):
        return float("nan")
    ranks = pd.Series(np.concatenate([pos, neg])).rank().to_numpy()
    return float((ranks[:len(pos)].sum() - len(pos) * (len(pos) + 1) / 2) / (len(pos) * len(neg)))


def report(cls: np.ndarray, score: np.ndarray, thresholds: dict) -> dict:
    normal = score[cls == "normal"]
    out = {"normal_operations": int(len(normal)),
           "false_alarm_rate": {k: round(float((normal > t).mean()), 4) for k, t in thresholds.items()}, "types": {}}
    anomalous = cls != "normal"
    out["overall"] = {"operations": int(anomalous.sum()), "auroc": round(auroc(score[anomalous], normal), 4),
                      "detected": {k: round(float((score[anomalous] > t).mean()), 4) for k, t in thresholds.items()}}
    for c in sorted(set(cls) - {"normal"}):
        s = score[cls == c]
        out["types"][c] = {"operations": int(len(s)), "auroc": round(auroc(s, normal), 4),
                           "detected": {k: round(float((s > t).mean()), 4) for k, t in thresholds.items()}}
    return out


def show(role: str, r: dict) -> None:
    head = " ".join(f"{k:>8}" for k in r["false_alarm_rate"])
    print(f"{role}: thresholds set on validation for {head}")
    print(f"  {'false alarms (normal)':<26}{r['normal_operations']:>4} ops " +
          " ".join(f"{v:>8.1%}" for v in r["false_alarm_rate"].values()))
    for name, t in [("all anomalies", r["overall"]), *r["types"].items()]:
        print(f"  {name:<26}{t['operations']:>4} ops " + " ".join(f"{v:>8.1%}" for v in t["detected"].values())
              + f"   AUROC {t['auroc']:.3f}")


def describe(cfg: dict) -> str:
    return (f"window {cfg['window']}, channels {cfg['group']}, PCA {cfg['pca'] or 'none'}, k {cfg['k']}"
            + (f", match {cfg['match']}" if cfg["window"] < 1024 else ""))


def cmd_select() -> None:
    windows = [w for w in WINDOWS if all((batch_dir(w) / f"{r}.npz").exists() for r in ("library", "validation"))]
    if not windows:
        sys.exit("no window has both library and validation embedded: run Stages 4 and 5's embed commands")
    trials = []
    for window, group in itertools.product(windows, GROUPS):
        _, lib = load("library", window, group)
        files, x = load("validation", window, group)
        cls = labels("validation", files)
        for pca, k, match in itertools.product(GRID["pca"], GRID["k"], ["any", "position"] if window < 1024 else ["any"]):
            if pca and pca >= min(lib.shape[0] * lib.shape[1], lib.shape[2]):
                continue
            s = Detector(lib, pca, k, match).score(x)
            trials.append({"window": window, "group": group, "pca": pca, "k": k, "match": match,
                           "auroc": auroc(s[cls != "normal"], s[cls == "normal"])})
    best = max(trials, key=lambda t: t["auroc"])
    lib_files, lib = load("library", best["window"], best["group"])
    files, x = load("validation", best["window"], best["group"])
    s = Detector(lib, best["pca"], best["k"], best["match"]).score(x)
    normal = s[cls == "normal"]
    thresholds = {f"far_{int(f * 100)}pct": float(np.quantile(normal, 1 - f)) for f in FAR_REPORTED}
    cfg = {"chosen_on": "validation", "window": best["window"], "group": best["group"],
           "channels": GROUPS[best["group"]] or CHANNELS, "pca": best["pca"], "k": best["k"], "match": best["match"],
           "validation_auroc": round(best["auroc"], 4), "far_target": FAR_TARGET,
           "threshold": thresholds[f"far_{int(FAR_TARGET * 100)}pct"], "thresholds": thresholds,
           "library_operations": len(lib_files), "windows_tried": windows}
    EVAL.mkdir(exist_ok=True)
    (EVAL / "settings.json").write_text(json.dumps(cfg, indent=1))
    (EVAL / "selection.json").write_text(json.dumps(trials, indent=1))
    r = report(cls, s, thresholds)
    (EVAL / "validation.json").write_text(json.dumps({"settings": cfg, **r}, indent=1))
    print(f"library {len(lib_files)} operations, validation {len(files)}; windows {windows}; {len(trials)} settings tried")
    for w, g in itertools.product(windows, GROUPS):
        b = max((t for t in trials if t["window"] == w and t["group"] == g), key=lambda t: t["auroc"])
        print(f"  window {w:>4}  {g:<18} best AUROC {b['auroc']:.3f}  ({describe(b).split(', ', 2)[2]})")
    print(f"chosen and frozen: {describe(cfg)} (validation AUROC {best['auroc']:.3f}); "
          f"threshold {cfg['threshold']:.4f} = {FAR_TARGET:.0%} false alarms on validation's normal operations")
    show("validation", r)
    pd.DataFrame({"file": files, "class": cls, "score": s}).to_csv(EVAL / "scores_validation.csv", index=False)
    print("wrote eval_out/settings.json")


def cmd_score(role: str, source: str) -> None:
    cfg = settings()
    files, x = load(role, cfg["window"], cfg["group"], source)
    cls = labels(role, files)
    s = Detector.frozen(cfg).score(x)
    r = report(cls, s, cfg["thresholds"])
    name = role if source == "batch" or role != "delivery" else "delivery_serving"
    (EVAL / f"{name}.json").write_text(json.dumps({"settings": cfg, "source": source, **r}, indent=1))
    pd.DataFrame({"file": files, "class": cls, "score": s}).to_csv(EVAL / f"scores_{name}.csv", index=False)
    print(f"settings (frozen by select): {describe(cfg)}, threshold {cfg['threshold']:.4f}; embeddings from {source}")
    show(role, r)
    plot(name, cls, s, cfg)


def plot(name: str, cls: np.ndarray, s: np.ndarray, cfg: dict) -> None:
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        return
    order = ["normal", *sorted(set(cls) - {"normal"})]
    fig, ax = plt.subplots(figsize=(8, 3.6))
    ax.boxplot([s[cls == c] for c in order], showfliers=False)
    for i, c in enumerate(order, 1):
        y = s[cls == c]
        ax.scatter(np.random.default_rng(0).normal(i, 0.06, len(y)), y, s=10, alpha=0.6,
                   color="#2c5d9e" if c == "normal" else "#c0392b")
    ax.set_xticks(range(1, len(order) + 1), [c.replace("_", " ") for c in order])
    ax.axhline(cfg["threshold"], color="#666", ls="--", lw=0.8, label=f"threshold ({cfg['far_target']:.0%} FAR on validation)")
    ax.set_ylabel("kNN distance to library (worst window)")
    ax.set_title(f"{name}: one point per screwdriving operation (window {cfg['window']})", fontsize=10)
    ax.legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(EVAL / f"scores_{name}.png", dpi=120)
    print(f"wrote eval_out/scores_{name}.png")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", choices=["select", "test", "deliver"])
    ap.add_argument("--source", choices=["serving", "batch"],
                    help="where the scored embeddings come from (default: batch)")
    args = ap.parse_args()
    if args.command == "select":
        cmd_select()
    elif args.command == "test":
        cmd_score("test", args.source or "batch")
    else:
        cmd_score("delivery", args.source or "batch")


if __name__ == "__main__":
    main()
