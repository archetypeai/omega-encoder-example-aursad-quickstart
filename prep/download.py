#!/usr/bin/env python3
"""Stage 0: download AURSAD.h5 (6.4 GB) from Zenodo in parallel byte ranges, and verify it.

    python prep/download.py              # 8 parallel ranges into data/raw/AURSAD.h5
    python prep/download.py --parts 16   # more ranges

Zenodo throttles each connection (~0.8 MB/s measured), not the total, so N ranges
fetched at once are about N times faster (8 ranges: ~34 MB/s). Each range is written
to its own part file and resumed where it stopped, so a rerun after an interruption
fetches only what is missing. The parts are joined, the md5 is checked against
Zenodo's, and only then is the file moved into place.

Only the .h5 is fetched: the .pkl holds the same data, and unpickling a downloaded
file can run arbitrary code.
"""
from __future__ import annotations

import argparse
import hashlib
import shutil
import sys
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

URL = "https://zenodo.org/records/4487073/files/AURSAD.h5?download=1"
SIZE = 6_417_816_949
MD5 = "08e4706cf15144761a12cb86bd071d72"
RAW = Path(__file__).resolve().parents[1] / "data" / "raw"
OUT = RAW / "AURSAD.h5"
CHUNK = 1 << 20

_done = 0
_lock = threading.Lock()


def fetch(part: Path, start: int, end: int, retries: int = 6) -> None:
    """Fetch bytes [start, end] into `part`, resuming from what it already holds."""
    global _done
    want = end - start + 1
    for attempt in range(retries + 1):
        have = part.stat().st_size if part.exists() else 0
        if have >= want:
            return
        req = urllib.request.Request(URL, headers={"Range": f"bytes={start + have}-{end}"})
        try:
            with urllib.request.urlopen(req, timeout=120) as r, open(part, "ab") as f:
                while chunk := r.read(CHUNK):
                    f.write(chunk)
                    with _lock:
                        _done += len(chunk)
            return
        except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as e:
            if attempt == retries:
                raise SystemExit(f"{part.name}: failed after {retries + 1} attempts: {e}")
            time.sleep(5 * (attempt + 1))


def md5(path: Path) -> str:
    h = hashlib.md5()
    with open(path, "rb") as f:
        while block := f.read(1 << 24):
            h.update(block)
    return h.hexdigest()


def main() -> int:
    global _done
    ap = argparse.ArgumentParser()
    ap.add_argument("--parts", type=int, default=8)
    args = ap.parse_args()
    if OUT.exists() and OUT.stat().st_size == SIZE:
        print(f"{OUT.relative_to(RAW.parents[1])} already present; checking md5 ...")
        ok = md5(OUT) == MD5
        print("md5 OK" if ok else "md5 MISMATCH: delete the file and rerun")
        return 0 if ok else 1
    if shutil.disk_usage(RAW.parent if RAW.exists() else RAW.parents[1]).free < SIZE * 1.1:
        sys.exit("not enough free disk space for 6.4 GB")
    RAW.mkdir(parents=True, exist_ok=True)
    parts_dir = RAW / "AURSAD.h5.parts"
    parts_dir.mkdir(exist_ok=True)
    step = -(-SIZE // args.parts)
    ranges = [(parts_dir / f"part_{i:02d}", i * step, min((i + 1) * step, SIZE) - 1) for i in range(args.parts)]
    _done = sum(p.stat().st_size for p, _, _ in ranges if p.exists())
    print(f"downloading {SIZE / 1e9:.2f} GB in {args.parts} ranges ({_done / 1e9:.2f} GB already here)")

    t0, start_done = time.time(), _done
    with ThreadPoolExecutor(args.parts) as pool:
        futures = [pool.submit(fetch, *r) for r in ranges]
        while not all(f.done() for f in futures):
            time.sleep(5)
            rate = (_done - start_done) / max(time.time() - t0, 1e-9)
            eta = (SIZE - _done) / rate if rate else float("inf")
            print(f"  {_done / 1e9:5.2f} / {SIZE / 1e9:.2f} GB  {rate / 1e6:5.1f} MB/s  ~{eta / 60:4.1f} min left",
                  flush=True)
        for f in futures:
            f.result()

    tmp = RAW / "AURSAD.h5.tmp"
    with open(tmp, "wb") as out:
        for p, _, _ in ranges:
            with open(p, "rb") as src:
                shutil.copyfileobj(src, out, 1 << 24)
    if tmp.stat().st_size != SIZE:
        sys.exit(f"joined file is {tmp.stat().st_size:,} bytes, expected {SIZE:,}")
    got = md5(tmp)
    if got != MD5:
        sys.exit(f"md5 {got} does not match Zenodo's {MD5}: delete {parts_dir} and rerun")
    tmp.replace(OUT)
    shutil.rmtree(parts_dir)
    print(f"wrote {OUT.relative_to(RAW.parents[1])} ({SIZE / 1e9:.2f} GB), md5 OK, "
          f"{(time.time() - t0) / 60:.1f} min")
    return 0


if __name__ == "__main__":
    sys.exit(main())
