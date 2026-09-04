#!/usr/bin/env python3
"""Download HuggingFace dataset files from a TSV of mirror URLs."""

from __future__ import annotations

import argparse
import concurrent.futures
import csv
import subprocess
import sys
import time
from pathlib import Path
from typing import Iterable
from urllib.request import Request, urlopen


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tsv", required=True)
    parser.add_argument("--output-root", required=True)
    parser.add_argument("--status-csv", required=True)
    parser.add_argument(
        "--pattern",
        action="append",
        default=[],
        help="Substring filter; may be repeated. Empty means all files.",
    )
    parser.add_argument("--skip-pattern", action="append", default=[])
    parser.add_argument("--max-files", type=int, default=0)
    parser.add_argument("--timeout", type=int, default=120)
    parser.add_argument("--tries", type=int, default=20)
    parser.add_argument("--connections", type=int, default=8)
    parser.add_argument("--chunk-mb", type=int, default=64)
    parser.add_argument("--parallel-threshold-mb", type=int, default=256)
    return parser.parse_args()


def load_rows(path: Path, patterns: list[str], skip_patterns: list[str]) -> list[dict[str, str]]:
    with path.open(newline="") as f:
        rows = list(csv.DictReader(f, delimiter="\t"))
    out = []
    for row in rows:
        rel = row["path"]
        if patterns and not any(p in rel for p in patterns):
            continue
        if skip_patterns and any(p in rel for p in skip_patterns):
            continue
        out.append(row)
    out.sort(key=lambda r: (int(r["size_bytes"]), r["path"]))
    return out


def is_complete(path: Path, size: int) -> bool:
    if not path.exists():
        return False
    local = path.stat().st_size
    if local == size:
        return True
    # Some HF mirror HEAD probes report compressed text size (often 20 bytes)
    # while wget stores the decompressed body. For small metadata files, a
    # successful non-empty download is good enough; large bag/db3 files remain
    # strict because they drive disk usage and evaluation.
    return size < 10_000_000 and local > 0


def write_status(path: Path, records: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = ["path", "size_expected", "size_local", "status", "return_code", "seconds", "url"]
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(records)
    tmp.replace(path)


def run_wget(url: str, output: Path, timeout: int, tries: int) -> int:
    output.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "wget",
        "-c",
        "--content-disposition",
        "--max-redirect=20",
        f"--timeout={timeout}",
        f"--tries={tries}",
        "--retry-connrefused",
        "--waitretry=10",
        "-O",
        str(output),
        url,
    ]
    return subprocess.run(cmd).returncode


def ranges(size: int, chunk_size: int) -> Iterable[tuple[int, int, int]]:
    for part_idx, start in enumerate(range(0, size, chunk_size)):
        end = min(size - 1, start + chunk_size - 1)
        yield part_idx, start, end


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
        req = Request(
            url,
            headers={
                "Range": f"bytes={start + resume_from}-{end}",
                "User-Agent": "Mozilla/5.0",
            },
        )
        try:
            with urlopen(req, timeout=timeout) as response, tmp.open("ab") as f:
                while True:
                    block = response.read(1024 * 256)
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
        except Exception as exc:  # noqa: BLE001
            if attempt == tries:
                return False, f"{type(exc).__name__}: {exc}"
            time.sleep(min(30, 2 * attempt))
    return False, "exhausted"


def assemble(output: Path, part_root: Path, expected: int, chunk_size: int) -> bool:
    tmp = output.with_suffix(output.suffix + ".assemble")
    with tmp.open("wb") as f:
        for part_idx, start, end in ranges(expected, chunk_size):
            part = part_root / f"part_{part_idx:05d}_{start}_{end}"
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
    tmp.replace(output)
    return True


def run_parallel_range(
    url: str,
    output: Path,
    expected: int,
    timeout: int,
    tries: int,
    connections: int,
    chunk_size: int,
) -> int:
    output.parent.mkdir(parents=True, exist_ok=True)
    part_root = output.parent / ".parts" / output.name
    tasks = []
    for part_idx, start, end in ranges(expected, chunk_size):
        part = part_root / f"part_{part_idx:05d}_{start}_{end}"
        tasks.append((part, start, end))
    failed: list[str] = []
    done = 0
    t0 = time.time()
    with concurrent.futures.ThreadPoolExecutor(max_workers=connections) as executor:
        futures = {
            executor.submit(download_range, url, part, start, end, timeout, tries): (part, start, end)
            for part, start, end in tasks
        }
        for future in concurrent.futures.as_completed(futures):
            part, start, end = futures[future]
            ok, msg = future.result()
            if ok:
                done += end - start + 1
                elapsed = max(time.time() - t0, 1e-6)
                print(
                    f"  part ok {part.name} {msg}; "
                    f"finished_mb={done / 1024 / 1024:.1f}; "
                    f"avg_kbps={done / 1024 / elapsed:.1f}",
                    flush=True,
                )
            else:
                failed.append(f"{part.name}: {msg}")
    if failed:
        print("  failed parts:", "; ".join(failed[:5]), flush=True)
        return 1
    return 0 if assemble(output, part_root, expected, chunk_size) else 2


def run_download(row: dict[str, str], output: Path, args: argparse.Namespace) -> int:
    size = int(row["size_bytes"])
    if args.connections > 1 and size >= args.parallel_threshold_mb * 1024 * 1024:
        return run_parallel_range(
            row["url"],
            output,
            size,
            args.timeout,
            args.tries,
            args.connections,
            args.chunk_mb * 1024 * 1024,
        )
    return run_wget(row["url"], output, args.timeout, args.tries)


def main() -> int:
    args = parse_args()
    rows = load_rows(Path(args.tsv), args.pattern, args.skip_pattern)
    if args.max_files:
        rows = rows[: args.max_files]
    root = Path(args.output_root)
    records: list[dict[str, str]] = []
    for idx, row in enumerate(rows, 1):
        rel = row["path"]
        size = int(row["size_bytes"])
        out = root / rel
        t0 = time.time()
        rc = 0
        if is_complete(out, size):
            status = "complete"
        else:
            print(f"[{idx}/{len(rows)}] downloading {rel} ({size / 1e9:.2f} GB)", flush=True)
            rc = run_download(row, out, args)
            if is_complete(out, size):
                status = "complete"
            elif out.exists():
                status = "partial"
            else:
                status = "failed"
        local = out.stat().st_size if out.exists() else 0
        records.append(
            {
                "path": rel,
                "size_expected": str(size),
                "size_local": str(local),
                "status": status,
                "return_code": str(rc),
                "seconds": f"{time.time() - t0:.1f}",
                "url": row["url"],
            }
        )
        write_status(Path(args.status_csv), records)
        print(f"[{idx}/{len(rows)}] {status}: {rel} local={local} expected={size}", flush=True)
    failed = [r for r in records if r["status"] != "complete"]
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
