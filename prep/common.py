"""Constants shared by the prep stages: the quickstart subset (option S), channels, windowing."""
from __future__ import annotations

from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
RAW = REPO / "data" / "raw" / "AURSAD.h5"
PREPARED = REPO / "data" / "prepared"
ROLES = REPO / "data" / "roles"

WINDOW = 1024            # rows per operation (10.24 s at 100 Hz): one file
CANDIDATE_WINDOWS = [1024, 512, 256]   # window sizes Stage 5 chooses from (each divides WINDOW)
PRE_ONSET = 256          # the window starts this many rows (2.56 s) before the screwdriver's torque rises
TORQUE_ON = 0.05         # Nm: "the screwdriver is acting" (current torque above this)
SEED = 20260502          # fixes which operations are drawn
SESSION_OFFSET_S = 100_000  # timestamps restart in every recording session; t + session * this keeps them unique
MAX_STEP_S = 0.1         # a window whose recorded timestamps jump further (or go back) is not one take; draw another

LABELS = {0: "normal", 1: "damaged_screw", 2: "extra_component", 3: "missing_screw"}
ANOMALIES = ["damaged_screw", "extra_component", "missing_screw"]

# Source column -> the name used in the role files.
CHANNELS = {
    "output_double_register_25": "torque_current",
    "output_double_register_24": "torque_achieved",
    "actual_current_0": "joint_current_0",
    "actual_current_1": "joint_current_1",
    "actual_current_2": "joint_current_2",
    "actual_current_3": "joint_current_3",
    "actual_current_4": "joint_current_4",
    "actual_current_5": "joint_current_5",
    "actual_TCP_force_2": "tcp_force_z",
    "actual_tool_accelerometer_0": "tool_acc_x",
    "actual_tool_accelerometer_1": "tool_acc_y",
    "actual_tool_accelerometer_2": "tool_acc_z",
}

# Roles by recording session (time), and how many operations of each class to draw (option S).
ROLE_SESSIONS = {
    "library": range(0, 5),
    "validation": range(5, 9),
    "test": range(9, 14),
    "delivery": range(14, 19),
}
SUBSET = {
    "library": {"normal": 150},
    "validation": {"normal": 60, "damaged_screw": 15, "extra_component": 15, "missing_screw": 15},
    "test": {"normal": 60, "damaged_screw": 15, "extra_component": 8, "missing_screw": 15},  # 8 = every usable one
    "delivery": {"normal": 60, "damaged_screw": 15, "missing_screw": 15},
}
SCORED = ("validation", "test", "delivery")


class Report:
    """PASS / WARN / FAIL / INFO lines; exit non-zero only on FAIL."""

    def __init__(self, title: str):
        self.rows = []
        print(f"== {title}")

    def add(self, level: str, check: str, detail: str) -> None:
        self.rows.append(level)
        print(f"  {level:<4}  {check:<30} {detail}")

    def finish(self) -> int:
        counts = {k: self.rows.count(k) for k in ("PASS", "WARN", "FAIL", "INFO")}
        print("  " + ", ".join(f"{v} {k}" for k, v in counts.items()))
        return 1 if counts["FAIL"] else 0
