#!/usr/bin/env python3
"""Download the public AQUALOC share with resume and size checks."""

from __future__ import annotations

import argparse
import concurrent.futures
import csv
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Iterable
from urllib.parse import quote
from urllib.request import Request, urlopen


TOKEN = "79b03788f29148ca84e5"
BASE_URL = f"https://seafile.lirmm.fr/d/{TOKEN}/files/"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--file-list",
        default="/mnt/data/AQUA-FE_WS/datasets/full_downloads/aqualoc/file_list.csv",
        help="CSV exported from the Seafile share listing.",
    )
    parser.add_argument(
        "--output-root",
        default="/mnt/data/AQUA-FE_WS/datasets/full_downloads/aqualoc",
        help="Directory where the AQUALOC directory tree will be written.",
    )
    parser.add_argument(
        "--status-csv",
        default="/mnt/data/AQUA-FE_WS/datasets/full_downloads/logs/aqualoc_download_status.csv",
        help="Download status CSV updated after every file.",
    )
    parser.add_argument("--max-files", type=int, default=0, help="Limit for smoke tests.")
    parser.add_argument(
        "--only-raw",
        action="store_true",
        help="Download only *_raw_data.tar.gz archives and small metadata files.",
    )
    parser.add_argument(
        "--order",
        choices=("raw-first", "small-first", "as-listed"),
        default="raw-first",
        help="Download order. raw-first gets usable evaluation archives earliest.",
    )
    parser.add_argument("--timeout", type=int, default=60)
    parser.add_argument("--tries", type=int, default=5)
    parser.add_argument(
        "--connections",
        type=int,
        default=8,
        help="Parallel Range connections per large file. Use 1 for wget.",
    )
    parser.add_argument(
        "--chunk-mb",
        type=int,
        default=16,
        help="Range chunk size in MiB for parallel downloads.",
    )
    parser.add_argument(
        "--parallel-threshold-mb",
        type=int,
        default=32,
        help="Use parallel Range downloading for files at least this large.",
    )
    return parser.parse_args()


def wanted(row: dict[str, str], only_raw: bool) -> bool:
    if not only_raw:
        return True
    path = row["file_path"]
    small = int(row["size"]) < 5_000_000
    return path.endswith("_raw_data.tar.gz") or small


def file_url(path: str) -> str:
    return f"{BASE_URL}?p={quote(path, safe='')}&dl=1"


def row_priority(row: dict[str, str], order: str) -> tuple[int, int, str]:
    path = row["file_path"]
    size = int(row["size"])
    if order == "as-listed":
        return (0, 0, path)
    if order == "small-first":
        return (0 if size < 10_000_000 else 1, size, path)

    # raw-first: obtain directly evaluable image/IMU archives before duplicate
    # ROS bag archives, while keeping calibration and ground-truth near the front.
    if path.endswith("_raw_data.tar.gz"):
        return (0, size, path)
    if size < 10_000_000:
        return (1, size, path)
    if path.endswith("_bag.tar.gz"):
        return (3, size, path)
    return (2, size, path)


def load_rows(file_list: Path, only_raw: bool, order: str) -> list[dict[str, str]]:
    with file_list.open(newline="") as f:
        rows = [r for r in csv.DictReader(f) if wanted(r, only_raw)]
    rows.sort(key=lambda r: row_priority(r, order))
    return rows


def write_status(status_csv: Path, records: list[dict[str, str]]) -> None:
    status_csv.parent.mkdir(parents=True, exist_ok=True)
    tmp = status_csv.with_suffix(status_csv.suffix + ".tmp")
    fields = [
        "file_path",
        "size_expected",
        "size_local",
        "status",
        "return_code",
        "seconds",
        "output_path",
    ]
    with tmp.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(records)
    tmp.replace(status_csv)


def local_path(output_root: Path, file_path: str) -> Path:
    rel = file_path.lstrip("/")
    return output_root / rel


def is_complete(path: Path, expected: int) -> bool:
    return path.exists() and path.stat().st_size == expected


def run_wget(url: str, out: Path, timeout: int, tries: int) -> int:
    out.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "wget",
        "-c",
        "--max-redirect=10",
        f"--timeout={timeout}",
        f"--tries={tries}",
        "--retry-connrefused",
        "--waitretry=5",
        "-O",
        str(out),
        url,
    ]
    return subprocess.run(cmd).returncode


def ranges(size: int, chunk_size: int) -> Iterable[tuple[int, int, int]]:
    part_idx = 0
    for start in range(0, size, chunk_size):
        end = min(size - 1, start + chunk_size - 1)
        yield part_idx, start, end
        part_idx += 1


def download_range(
    url: str,
    part_path: Path,
    start: int,
    end: int,
    timeout: int,
    tries: int,
) -> tuple[bool, str]:
    expected = end - start + 1
    if part_path.exists() and part_path.stat().st_size == expected:
        return True, "cached"
    part_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = part_path.with_suffix(part_path.suffix + ".tmp")
    resume_from = tmp.stat().st_size if tmp.exists() else 0
    if resume_from > expected:
        tmp.unlink()
        resume_from = 0

    for attempt in range(1, tries + 1):
        req_start = start + resume_from
        headers = {
            "Range": f"bytes={req_start}-{end}",
            "User-Agent": "Mozilla/5.0",
        }
        req = Request(url, headers=headers)
        try:
            with urlopen(req, timeout=timeout) as response, tmp.open("ab") as f:
                while True:
                    block = response.read(1024 * 128)
                    if not block:
                        break
                    f.write(block)
            if tmp.stat().st_size == expected:
                tmp.replace(part_path)
                return True, f"downloaded:{attempt}"
            resume_from = tmp.stat().st_size
            if resume_from > expected:
                tmp.unlink()
                resume_from = 0
        except Exception as exc:  # noqa: BLE001 - report and retry transient network errors.
            if attempt == tries:
                return False, f"{type(exc).__name__}: {exc}"
            time.sleep(min(30, 2 * attempt))
    return False, "exhausted"


def assemble_parts(out: Path, part_dir: Path, expected: int, chunk_size: int) -> bool:
    tmp = out.with_suffix(out.suffix + ".assemble")
    with tmp.open("wb") as f:
        for part_idx, start, end in ranges(expected, chunk_size):
            part = part_dir / f"part_{part_idx:05d}_{start}_{end}"
            if not part.exists() or part.stat().st_size != end - start + 1:
                tmp.unlink(missing_ok=True)
                return False
            with part.open("rb") as pf:
                while True:
                    block = pf.read(1024 * 1024)
                    if not block:
                        break
                    f.write(block)
    if tmp.stat().st_size != expected:
        tmp.unlink(missing_ok=True)
        return False
    tmp.replace(out)
    return True


def run_parallel_range(
    url: str,
    out: Path,
    expected: int,
    timeout: int,
    tries: int,
    connections: int,
    chunk_size: int,
) -> int:
    out.parent.mkdir(parents=True, exist_ok=True)
    part_root = out.parent / ".parts" / out.name
    tasks = []
    for part_idx, start, end in ranges(expected, chunk_size):
        part = part_root / f"part_{part_idx:05d}_{start}_{end}"
        tasks.append((part, start, end))

    failed: list[str] = []
    t0 = time.time()
    with concurrent.futures.ThreadPoolExecutor(max_workers=connections) as executor:
        future_map = {
            executor.submit(download_range, url, part, start, end, timeout, tries): (part, start, end)
            for part, start, end in tasks
        }
        done_bytes = 0
        for future in concurrent.futures.as_completed(future_map):
            part, start, end = future_map[future]
            ok, msg = future.result()
            if ok:
                done_bytes += end - start + 1
                mb = done_bytes / (1024 * 1024)
                elapsed = max(time.time() - t0, 1e-6)
                print(
                    f"  part ok {part.name} {msg}; finished_parts_mb={mb:.1f}; "
                    f"avg_kbps={done_bytes / 1024 / elapsed:.1f}",
                    flush=True,
                )
            else:
                failed.append(f"{part.name}: {msg}")

    if failed:
        print("  failed parts:", "; ".join(failed[:5]), flush=True)
        return 1
    return 0 if assemble_parts(out, part_root, expected, chunk_size) else 2


def run_download(
    url: str,
    out: Path,
    expected: int,
    args: argparse.Namespace,
) -> int:
    use_parallel = (
        args.connections > 1
        and expected >= args.parallel_threshold_mb * 1024 * 1024
    )
    if use_parallel:
        return run_parallel_range(
            url=url,
            out=out,
            expected=expected,
            timeout=args.timeout,
            tries=args.tries,
            connections=args.connections,
            chunk_size=args.chunk_mb * 1024 * 1024,
        )
    return run_wget(url, out, args.timeout, args.tries)


def main() -> int:
    args = parse_args()
    file_list = Path(args.file_list)
    output_root = Path(args.output_root)
    status_csv = Path(args.status_csv)
    rows = load_rows(file_list, args.only_raw, args.order)
    if args.max_files:
        rows = rows[: args.max_files]

    records: list[dict[str, str]] = []
    total = len(rows)
    for idx, row in enumerate(rows, 1):
        fp = row["file_path"]
        expected = int(row["size"])
        out = local_path(output_root, fp)
        t0 = time.time()
        rc = 0
        if is_complete(out, expected):
            status = "complete"
        else:
            print(f"[{idx}/{total}] downloading {fp} ({expected / 1e9:.2f} GB)", flush=True)
            rc = run_download(file_url(fp), out, expected, args)
            if is_complete(out, expected):
                status = "complete"
            elif out.exists():
                status = "partial"
            else:
                status = "failed"
        local_size = out.stat().st_size if out.exists() else 0
        records.append(
            {
                "file_path": fp,
                "size_expected": str(expected),
                "size_local": str(local_size),
                "status": status,
                "return_code": str(rc),
                "seconds": f"{time.time() - t0:.1f}",
                "output_path": str(out),
            }
        )
        write_status(status_csv, records)
        print(
            f"[{idx}/{total}] {status}: {fp} local={local_size} expected={expected}",
            flush=True,
        )

    failed = [r for r in records if r["status"] != "complete"]
    print(f"completed {total - len(failed)}/{total}; failed_or_partial={len(failed)}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
