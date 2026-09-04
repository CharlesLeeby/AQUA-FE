#!/usr/bin/env python3
"""Download UVVID files from Figshare metadata.

The all-in-one DTU/Figshare article downloader can trigger a WAF challenge on
some networks. The public Figshare API exposes per-file download URLs, which are
more robust and resumable.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--metadata",
        default="/mnt/data/AQUA-FE_WS/datasets/full_downloads/uvvid/figshare_api_article_proxy_probe.json",
    )
    parser.add_argument(
        "--output-root",
        default="/mnt/data/AQUA-FE_WS/datasets/full_downloads/uvvid/files",
    )
    parser.add_argument(
        "--file-list",
        default="/mnt/data/AQUA-FE_WS/datasets/full_downloads/uvvid/uvvid_file_list.tsv",
    )
    parser.add_argument(
        "--status-csv",
        default="/mnt/data/AQUA-FE_WS/datasets/full_downloads/logs/uvvid_figshare_download_status.csv",
    )
    parser.add_argument("--pattern", action="append", default=[])
    parser.add_argument("--max-files", type=int, default=0)
    parser.add_argument("--timeout", type=int, default=180)
    parser.add_argument("--tries", type=int, default=20)
    return parser.parse_args()


def safe_name(text: str) -> str:
    text = text.strip().replace("\\", "_").replace("/", "_")
    text = re.sub(r"[^A-Za-z0-9._ ()+-]+", "_", text)
    return text or "unnamed"


def load_rows(metadata_path: Path, output_root: Path, patterns: list[str]) -> list[dict[str, str]]:
    data = json.loads(metadata_path.read_text())
    folders = data.get("folder_structure") or {}
    rows: list[dict[str, str]] = []
    for item in data["files"]:
        file_id = str(item["id"])
        folder = folders.get(file_id, "") or "root"
        name = item["name"]
        rel = Path(folder) / f"{file_id}_{safe_name(name)}"
        rel_s = str(rel)
        if patterns and not any(p in rel_s for p in patterns):
            continue
        rows.append(
            {
                "id": file_id,
                "name": name,
                "folder": folder,
                "size": str(item["size"]),
                "md5": item.get("computed_md5") or item.get("supplied_md5") or "",
                "url": item["download_url"],
                "output_path": str(output_root / rel),
            }
        )
    rows.sort(key=lambda r: (r["folder"], r["name"], int(r["id"])))
    return rows


def write_file_list(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=["id", "name", "folder", "size", "md5", "url", "output_path"],
            delimiter="\t",
        )
        writer.writeheader()
        writer.writerows(rows)


def write_status(path: Path, records: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=["id", "name", "size_expected", "size_local", "status", "return_code", "seconds", "output_path"],
        )
        writer.writeheader()
        writer.writerows(records)
    tmp.replace(path)


def is_complete(path: Path, expected: int) -> bool:
    return path.exists() and path.stat().st_size == expected


def run_wget(url: str, output: Path, timeout: int, tries: int) -> int:
    output.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "wget",
        "-c",
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


def main() -> int:
    args = parse_args()
    rows = load_rows(Path(args.metadata), Path(args.output_root), args.pattern)
    if args.max_files:
        rows = rows[: args.max_files]
    write_file_list(Path(args.file_list), rows)
    records: list[dict[str, str]] = []
    for idx, row in enumerate(rows, 1):
        out = Path(row["output_path"])
        expected = int(row["size"])
        t0 = time.time()
        rc = 0
        if is_complete(out, expected):
            status = "complete"
        else:
            print(
                f"[{idx}/{len(rows)}] downloading {row['folder']}/{row['name']} "
                f"({expected / 1e9:.2f} GB)",
                flush=True,
            )
            rc = run_wget(row["url"], out, args.timeout, args.tries)
            status = "complete" if is_complete(out, expected) else ("partial" if out.exists() else "failed")
        local = out.stat().st_size if out.exists() else 0
        records.append(
            {
                "id": row["id"],
                "name": row["name"],
                "size_expected": str(expected),
                "size_local": str(local),
                "status": status,
                "return_code": str(rc),
                "seconds": f"{time.time() - t0:.1f}",
                "output_path": str(out),
            }
        )
        write_status(Path(args.status_csv), records)
        print(f"[{idx}/{len(rows)}] {status}: {row['name']} local={local} expected={expected}", flush=True)
    return 1 if any(r["status"] != "complete" for r in records) else 0


if __name__ == "__main__":
    sys.exit(main())
