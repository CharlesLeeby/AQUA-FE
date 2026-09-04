#!/usr/bin/env python3
"""Write a compact status report for long-running dataset downloads."""

from __future__ import annotations

import csv
import subprocess
from pathlib import Path


ROOT = Path("/mnt/data/AQUA-FE_WS/datasets/full_downloads")
LOGS = ROOT / "logs"
OUT = LOGS / "dataset_download_status.md"


def sh(command: str) -> str:
    return subprocess.run(
        command,
        shell=True,
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    ).stdout.strip()


def csv_summary(path: Path) -> str:
    if not path.exists():
        return "status CSV not found"
    rows = list(csv.DictReader(path.open()))
    if not rows:
        return "no rows"
    complete = sum(r.get("status") == "complete" for r in rows)
    partial = sum(r.get("status") == "partial" for r in rows)
    failed = sum(r.get("status") == "failed" for r in rows)
    local = sum(int(r.get("size_local", 0)) for r in rows)
    last = rows[-1]
    key = last.get("file_path") or last.get("path") or last.get("name")
    return (
        f"rows={len(rows)}, complete={complete}, partial={partial}, failed={failed}, "
        f"recorded_local={local / 1e9:.3f} GB, last={key}"
    )


def pid_status(pid_file: Path) -> str:
    if not pid_file.exists():
        return "pid file not found"
    pid = pid_file.read_text().strip()
    if not pid:
        return "empty pid file"
    ps = sh(f"ps -p {pid} -o pid,etime,pcpu,pmem,cmd --no-headers 2>/dev/null")
    return ps or f"pid {pid} not running"


def main() -> None:
    LOGS.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Dataset Download Status",
        "",
        "Root: `/mnt/data/AQUA-FE_WS/datasets/full_downloads`",
        "",
        "## Disk",
        "```",
        sh("df -h /mnt/data /home/ma/AQUA-FE_WS 2>/dev/null || true"),
        "```",
        "",
        "## Running Jobs",
        f"- AQUALOC: `{pid_status(LOGS / 'aqualoc_full_download.pid')}`",
        f"- AFRL HF mirror: `{pid_status(LOGS / 'afrl_hf_mirror_download.pid')}`",
        f"- NTNU HF mirror: `{pid_status(LOGS / 'ntnu_hf_mirror_download.pid')}`",
        f"- UVVID Figshare: `{pid_status(LOGS / 'uvvid_figshare_download.pid')}`",
        f"- Tank short_test.zip: `{pid_status(LOGS / 'tank_short_zip_gdown.pid')}`",
        f"- Tank short_test.bag: `{pid_status(LOGS / 'tank_short_bag_download.pid')}`",
        "",
        "## CSV Summaries",
        f"- AQUALOC: {csv_summary(LOGS / 'aqualoc_download_status.csv')}",
        f"- AFRL HF mirror: {csv_summary(LOGS / 'afrl_hf_mirror_download_status.csv')}",
        f"- NTNU HF mirror: {csv_summary(LOGS / 'ntnu_hf_mirror_download_status.csv')}",
        f"- UVVID Figshare: {csv_summary(LOGS / 'uvvid_figshare_download_status.csv')}",
        "",
        "## Directory Sizes",
        "```",
        sh(f"du -sh {ROOT}/* 2>/dev/null | sort -h"),
        "```",
        "",
        "## Source Notes",
        "- AQUALOC: public Seafile direct links work, but this network path is slow. The downloader uses parallel Range chunks and is resumable.",
        "- AFRL/NTNU: direct HuggingFace access was unreliable, but `hf-mirror.com` file URLs work and are being downloaded with `wget -c`.",
        "- UVVID: with the local proxy, Figshare API works. The all-in-one article zip hits an AWS WAF challenge, so individual Figshare file URLs are being downloaded instead.",
        "- Tank Dataset: with the local proxy, public `short_test` Google Drive files are downloadable. Full data still requires the official request form.",
        "",
        "## Useful Resume Commands",
        "```bash",
        "python3 scripts/download_aqualoc_full.py --order raw-first --connections 8 --chunk-mb 16 --parallel-threshold-mb 32 --timeout 90 --tries 8",
        "python3 scripts/download_hf_mirror_dataset.py --tsv /mnt/data/AQUA-FE_WS/datasets/full_downloads/afrl_hf/hf_filelist_with_sizes.tsv --output-root /mnt/data/AQUA-FE_WS/datasets/full_downloads/afrl_hf --status-csv /mnt/data/AQUA-FE_WS/datasets/full_downloads/logs/afrl_hf_mirror_download_status.csv --timeout 180 --tries 30",
        "python3 scripts/download_hf_mirror_dataset.py --tsv /mnt/data/AQUA-FE_WS/datasets/full_downloads/ntnu_hf/hf_filelist_with_sizes.tsv --output-root /mnt/data/AQUA-FE_WS/datasets/full_downloads/ntnu_hf --status-csv /mnt/data/AQUA-FE_WS/datasets/full_downloads/logs/ntnu_hf_mirror_download_status.csv --timeout 180 --tries 30",
        "HTTP_PROXY=http://127.0.0.1:7897 HTTPS_PROXY=http://127.0.0.1:7897 python3 scripts/download_uvvid_figshare.py --timeout 180 --tries 20",
        "```",
        "",
    ]
    OUT.write_text("\n".join(lines))
    print(OUT)


if __name__ == "__main__":
    main()
