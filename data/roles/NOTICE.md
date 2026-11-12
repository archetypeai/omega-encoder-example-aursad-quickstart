# AURSAD role files: attribution and changes

These files are derived from the **AURSAD: Universal Robot Screwdriving Anomaly Detection
Dataset** by Błażej Leporowski, Daniella Tola, Casper Hansen and Alexandros Iosifidis
(Aarhus University; Technicon ApS), version 1.1 on Zenodo:
https://doi.org/10.5281/zenodo.4487073. Paper: arXiv:2102.01409.

The original dataset and these derived files are licensed under the
**Creative Commons Attribution 4.0 International License (CC BY 4.0)**:
https://creativecommons.org/licenses/by/4.0/. The code in this repository is licensed
under the Apache License 2.0 (see `LICENSE`).

## Changes made to the original data

- **Subset:** 443 of the 2,042 labelled tightenings in the four classes kept (seed 20260502), drawn per
  role and class as in `prep/common.py` (`SUBSET`). Classes kept: normal, damaged screw,
  extra assembly component, missing screw. The dataset's other classes, 3 damaged-plate-thread samples and all
  loosening samples, are not included.
- **Roles by recording session:** library sessions 0-4, validation 5-8, test 9-13,
  delivery 14-18 (the original file's timestamps restart in each of its 19 sessions).
- **Windows:** each operation is 1,024 consecutive rows (10.24 s at 100 Hz) of the original
  recording, starting 256 rows before the screwdriver's current torque first exceeds
  0.05 Nm in that sample. A window can include rows of the neighbouring robot motion.
  Windows whose original timestamps jump by more than 0.1 s were not used.
- **Channels:** 12 of the dataset's 125 features (its file has 134 columns), renamed: `output_double_register_25` → `torque_current`, `output_double_register_24` → `torque_achieved`, `actual_current_0` → `joint_current_0`, `actual_current_1` → `joint_current_1`, `actual_current_2` → `joint_current_2`, `actual_current_3` → `joint_current_3`, `actual_current_4` → `joint_current_4`, `actual_current_5` → `joint_current_5`, `actual_TCP_force_2` → `tcp_force_z`, `actual_tool_accelerometer_0` → `tool_acc_x`, `actual_tool_accelerometer_1` → `tool_acc_y`, `actual_tool_accelerometer_2` → `tool_acc_z`.
- **Values:** z-scored per channel with the library operations' mean and std
  (`manifest.json` holds both, to undo it).
- **Timestamps:** re-gridded to an exact 10 ms step from each window's first original
  timestamp (the original repeats and jitters timestamps), plus 100,000 s × session
  number, so timestamps are unique across sessions.
- **Labels:** moved out of the data files into `labels/<role>.json`.
