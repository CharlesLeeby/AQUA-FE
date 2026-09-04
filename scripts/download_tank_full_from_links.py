#!/usr/bin/env python3
"""Download Tank full sequences from user-provided links.

The public Tank page only exposes the short_test sample directly. Full
sequence links are request-gated, so this script expects a TSV created from
the email response.
"""

from __future__ import annotations

import argparse
import csv
import os
import re
import subprocess
from pathlib import Path


def drive_id(url: str) -> str | None:
    patterns = [
        r"drive\.google\.com/file/d/([^/]+)",
        r"[?&]id=([^&]+)",
    ]
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    return None


def safe_name(text: str) -> str:
    text = text.strip().replace(" ", "_")
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", text).strip("_") or "unknown"


def download(url: str, output: Path, proxy: bool) -> int:
    output.parent.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    if proxy:
        env.setdefault("HTTP_PROXY", "http://127.0.0.1:7897")
        env.setdefault("HTTPS_PROXY", "http://127.0.0.1:7897")

    gid = drive_id(url)
    if gid:
        cmd = ["gdown", "--fuzzy", url, "-O", str(output), "--continue"]
    else:
        cmd = ["wget", "-c", "-O", str(output), url]
    print("$", " ".join(cmd), flush=True)
    return subprocess.call(cmd, env=env)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--links", required=True, help="TSV with sequence,kind,url columns")
    ap.add_argument(
        "--output-root",
        default="/mnt/data/AQUA-FE_WS/datasets/full_downloads/tank/full_sequences",
    )
    ap.add_argument("--proxy", action="store_true", help="Use local HTTP proxy")
    args = ap.parse_args()

    links = Path(args.links)
    out_root = Path(args.output_root)
    status = out_root / "download_status.csv"
    out_root.mkdir(parents=True, exist_ok=True)

    with links.open(newline="") as f, status.open("w", newline="") as sf:
        reader = csv.DictReader(f, delimiter="\t")
        writer = csv.DictWriter(
            sf,
            fieldnames=["sequence", "kind", "url", "output", "returncode"],
        )
        writer.writeheader()
        for row in reader:
            sequence = safe_name(row.get("sequence", "unknown"))
            kind = safe_name(row.get("kind", "bag"))
            url = (row.get("url") or "").strip()
            if not url:
                continue
            suffix = ".bag" if kind == "bag" else Path(url.split("?")[0]).suffix
            if not suffix or len(suffix) > 8:
                suffix = ".dat"
            output = out_root / sequence / f"{sequence}_{kind}{suffix}"
            rc = download(url, output, args.proxy)
            writer.writerow(
                {
                    "sequence": sequence,
                    "kind": kind,
                    "url": url,
                    "output": str(output),
                    "returncode": rc,
                }
            )
            sf.flush()
    print(f"wrote {status}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
