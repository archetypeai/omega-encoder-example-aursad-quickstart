#!/usr/bin/env python3
"""Your own anomaly detector (kNN) over the Omega Encoder agent's embeddings, one per operation.

    python detect/detect.py select     # Stage 5: choose PCA and k on validation, set the threshold, freeze
    python detect/detect.py test       # Stage 6: score test once, with the frozen settings
    python detect/detect.py deliver    # Stage 7: score the delivery afterwards

The protocol, fixed before anything was scored:
- Joint state per operation: each channel's 768-d embedding is L2-normalised and the 12
  channels are concatenated (9,216-d); optionally PCA, fitted on the library.
- Score: the mean distance to the k nearest library operations.
- Stage 5 picks the channel group (GROUPS), PCA and k by validation AUROC (normal vs. every
  anomaly), then sets the
  threshold to a FAR_TARGET (5%) false-alarm rate on validation's normal operations:
  data the library has not seen. Thresholds for 1% and 2% are set the same way and
  reported beside it. All of it is frozen in eval_out/settings.json.
- Stages 6 and 7 read settings.json and never change it. They report, per anomaly type,
  the detection rate at each frozen threshold and AUROC against the role's normal
  operations; and the false-alarm rate on its normal operations.

Labels come from data/roles/labels/<role>.json, read only by the command that scores
that role.
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
EMB = REPO / "out" / "embed"
ROLES = REPO / "data" / "roles"
EVAL = REPO / "eval_out"
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


def load(role: str, group: str = "all") -> tuple[list[str], np.ndarray]:
    """Files and joint states (the group's channels, each L2-normalised, concatenated)."""
    path = EMB / f"{role}.npz"
    if not path.exists():
        sys.exit(f"{path.relative_to(REPO)} not found: run embed/embed.py --roles {role}")
    z = np.load(path)
    keep = [CHANNELS.index(c) for c in (GROUPS[group] or CHANNELS)]
    e = z["emb"][:, keep]
    e = e / np.maximum(np.linalg.norm(e, axis=2, keepdims=True), 1e-8)
    return [str(f) for f in z["files"]], e.reshape(len(e), -1)


def labels(role: str, files: list[str]) -> np.ndarray:
    lab = {o["file"]: o["class"] for o in json.loads((ROLES / "labels" / f"{role}.json").read_text())["operations"]}
    return np.asarray([lab[f] for f in files])


class Detector:
    def __init__(self, lib: np.ndarray, pca: int, k: int):
        self.mean = lib.mean(0)
        self.proj = np.linalg.svd(lib - self.mean, full_matrices=False)[2][:pca].T if pca else None
        self.lib, self.k = self._project(lib), k

    def _project(self, x: np.ndarray) -> np.ndarray:
        x = x - self.mean
        return x @ self.proj if self.proj is not None else x

    def score(self, x: np.ndarray) -> np.ndarray:
        x = self._project(x)
        d = np.sqrt(np.maximum((x ** 2).sum(1)[:, None] + (self.lib ** 2).sum(1)[None] - 2 * x @ self.lib.T, 0))
        return np.sort(d, axis=1)[:, :self.k].mean(1)


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


def cmd_select() -> None:
    trials = []
    for group in GROUPS:
        lib_files, lib = load("library", group)
        files, x = load("validation", group)
        cls = labels("validation", files)
        for pca, k in itertools.product(GRID["pca"], GRID["k"]):
            if pca and pca >= min(lib.shape):
                continue
            s = Detector(lib, pca, k).score(x)
            trials.append({"group": group, "pca": pca, "k": k, "auroc": auroc(s[cls != "normal"], s[cls == "normal"])})
    best = max(trials, key=lambda t: t["auroc"])
    lib_files, lib = load("library", best["group"])
    files, x = load("validation", best["group"])
    s = Detector(lib, best["pca"], best["k"]).score(x)
    normal = s[cls == "normal"]
    thresholds = {f"far_{int(f * 100)}pct": float(np.quantile(normal, 1 - f)) for f in FAR_REPORTED}
    settings = {"chosen_on": "validation", "group": best["group"], "channels": GROUPS[best["group"]] or CHANNELS,
                "pca": best["pca"], "k": best["k"], "validation_auroc": round(best["auroc"], 4),
                "far_target": FAR_TARGET, "threshold": thresholds[f"far_{int(FAR_TARGET * 100)}pct"],
                "thresholds": thresholds, "library_operations": len(lib_files)}
    EVAL.mkdir(exist_ok=True)
    (EVAL / "settings.json").write_text(json.dumps(settings, indent=1))
    (EVAL / "selection.json").write_text(json.dumps(trials, indent=1))
    r = report(cls, s, thresholds)
    (EVAL / "validation.json").write_text(json.dumps({"settings": settings, **r}, indent=1))
    print(f"library {len(lib_files)} operations, validation {len(files)}; {len(trials)} settings tried")
    for g in GROUPS:
        b = max((t for t in trials if t["group"] == g), key=lambda t: t["auroc"])
        print(f"  best for {g:<18} AUROC {b['auroc']:.3f}  (PCA {b['pca'] or 'none'}, k {b['k']})")
    print(f"chosen and frozen: channels {best['group']}, PCA {best['pca'] or 'none'}, k {best['k']} "
          f"(validation AUROC {best['auroc']:.3f}); "
          f"threshold {settings['threshold']:.4f} = {FAR_TARGET:.0%} false alarms on validation's normal operations")
    show("validation", r)
    pd.DataFrame({"file": files, "class": cls, "score": s}).to_csv(EVAL / "scores_validation.csv", index=False)
    print("wrote eval_out/settings.json")


def cmd_score(role: str) -> None:
    p = EVAL / "settings.json"
    if not p.exists():
        sys.exit("eval_out/settings.json not found: run Stage 5 (detect/detect.py select) first")
    cfg = json.loads(p.read_text())
    _, lib = load("library", cfg["group"])
    files, x = load(role, cfg["group"])
    cls = labels(role, files)
    s = Detector(lib, cfg["pca"], cfg["k"]).score(x)
    r = report(cls, s, cfg["thresholds"])
    (EVAL / f"{role}.json").write_text(json.dumps({"settings": cfg, **r}, indent=1))
    pd.DataFrame({"file": files, "class": cls, "score": s}).to_csv(EVAL / f"scores_{role}.csv", index=False)
    print(f"settings (frozen in Stage 5): channels {cfg['group']}, PCA {cfg['pca'] or 'none'}, k {cfg['k']}, "
          f"threshold {cfg['threshold']:.4f}")
    show(role, r)
    plot(role, cls, s, cfg)


def plot(role: str, cls: np.ndarray, s: np.ndarray, cfg: dict) -> None:
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
    ax.set_ylabel("kNN distance to library")
    ax.set_title(f"{role}: one point per screwdriving operation", fontsize=10)
    ax.legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(EVAL / f"scores_{role}.png", dpi=120)
    print(f"wrote eval_out/scores_{role}.png")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", choices=["select", "test", "deliver"])
    args = ap.parse_args()
    if args.command == "select":
        cmd_select()
    else:
        cmd_score("test" if args.command == "test" else "delivery")


if __name__ == "__main__":
    main()
