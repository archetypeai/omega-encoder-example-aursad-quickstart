#!/usr/bin/env python3
"""Stage 1a (part 1): walk AURSAD.h5's structure. Read-only, and nothing is unpickled.

    python prep/inspect_h5.py

The release is a pandas HDF5 file. pandas can store object columns as pickled blobs,
and unpickling a downloaded file can run arbitrary code, so this opens the file with
h5py only, prints every group and dataset (shape, dtype, size), decodes column-name
arrays when they are plain strings, and flags any dataset with an opaque or
variable-length object dtype instead of reading it.
"""
from __future__ import annotations

import sys
from pathlib import Path

import h5py

RAW = Path(__file__).resolve().parents[1] / "data" / "raw" / "AURSAD.h5"


def safe_names(ds: h5py.Dataset) -> list[str] | None:
    """Decode a 1-D array of fixed-length byte strings (pandas' axis/items arrays)."""
    if ds.ndim == 1 and ds.dtype.kind == "S" and ds.shape[0] <= 1000:
        return [x.decode("utf-8", "replace") for x in ds[()]]
    return None


def main() -> int:
    if not RAW.exists():
        sys.exit(f"{RAW} not found: run the Stage 0 download")
    print(f"{RAW.name}: {RAW.stat().st_size / 1e9:.2f} GB")
    flagged = []
    with h5py.File(RAW, "r") as f:
        def visit(name, obj):
            depth = name.count("/")
            pad = "  " * depth
            if isinstance(obj, h5py.Group):
                attrs = {k: obj.attrs[k] for k in obj.attrs if k in ("pandas_type", "pandas_version", "nblocks")}
                print(f"{pad}{name}/  {attrs if attrs else ''}")
                return
            kind = obj.dtype.kind
            risky = kind in ("O", "V") and obj.dtype.names is None
            print(f"{pad}{name}  shape={obj.shape} dtype={obj.dtype} {obj.nbytes / 1e6:,.1f} MB"
                  + ("  <- opaque/object: NOT read" if risky else ""))
            if risky:
                flagged.append(name)
            names = None if risky else safe_names(obj)
            if names:
                print(f"{pad}  {len(names)} names: {names[:12]}{' ...' if len(names) > 12 else ''}")
            if obj.dtype.names:
                print(f"{pad}  compound fields: {list(obj.dtype.names)[:20]}")
        f.visititems(visit)
    if flagged:
        print(f"\n{len(flagged)} opaque/object datasets left unread: {flagged}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
