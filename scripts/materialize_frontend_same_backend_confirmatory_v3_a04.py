#!/usr/bin/env python3
"""Materialize the preregistered A04 window from its root-layout archive.

The public A04 archive is the one AQUALOC archaeology tar whose CSV/image
members are at archive root rather than under ``raw_data``.  This fixes only
the data adapter path and does not change a frontend or evaluation setting.
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

import rosbag


ROOT = Path("/home/ma/AQUA-FE_WS")
RUNTIME = Path(
    "/media/ma/Data/AQUA-FE_WS_storage_offload/"
    "frontend_same_backend_confirmatory_v3"
)
ARCHIVE = ROOT / (
    "datasets/full_downloads/aqualoc/Archaeological_site_sequences/"
    "archaeo_sequence_4_raw_data.tar.gz"
)
REFERENCE = ROOT / (
    "datasets/full_downloads/aqualoc/Archaeological_site_sequences/"
    "archaeo_groundtruth_files/new_archaeo_colmap_traj_sequence_04.txt"
)
OUTPUT_DIR = RUNTIME / "prepared/a04_5400_6300"
OUTPUT = OUTPUT_DIR / "input.bag"
RECEIPT = OUTPUT_DIR / "materialization_receipt.json"
ARCHIVE_SHA256 = "b81d03e63a112e6d9bc3f7ae9855f3e183c93c7897b87deb136e705bb574109e"
REFERENCE_SHA256 = "7b6242a9046e5894143f39e2d60b98dcddfd33f8ff2a13d3157ba88ceda878d5"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def audit(path: Path) -> dict[str, object]:
    counts: Counter[str] = Counter()
    first: dict[str, int] = {}
    last: dict[str, int] = {}
    with rosbag.Bag(str(path), "r") as bag:
        for topic, message, stamp in bag.read_messages():
            counts[topic] += 1
            header = getattr(message, "header", None)
            stamp_ns = int(
                header.stamp.to_nsec() if header is not None else stamp.to_nsec()
            )
            first.setdefault(topic, stamp_ns)
            last[topic] = stamp_ns
    return {
        "topic_counts": dict(sorted(counts.items())),
        "topic_first_ns": dict(sorted(first.items())),
        "topic_last_ns": dict(sorted(last.items())),
    }


def atomic_json(path: Path, payload: dict[str, object]) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    temporary.replace(path)


def main() -> int:
    if sha256(ARCHIVE) != ARCHIVE_SHA256:
        raise RuntimeError("A04 archive hash mismatch")
    if sha256(REFERENCE) != REFERENCE_SHA256:
        raise RuntimeError("A04 proxy hash mismatch")
    if OUTPUT.is_file() and RECEIPT.is_file():
        saved = json.loads(RECEIPT.read_text(encoding="utf-8"))
        if saved["output_sha256"] != sha256(OUTPUT):
            raise RuntimeError("existing A04 materialization hash mismatch")
        print(f"resume {OUTPUT}")
        return 0
    if OUTPUT.exists() or RECEIPT.exists():
        raise RuntimeError("partial A04 materialization exists; manual audit required")
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    temporary = OUTPUT_DIR / f"input.partial.{os.getpid()}.bag"
    command = [
        sys.executable,
        "-m",
        "uw_frontend.datasets.aqualoc_raw_to_rosbag",
        "--input",
        str(ARCHIVE),
        "--output-bag",
        str(temporary),
        "--sequence-name",
        "archaeo_sequence_4",
        "--raw-root",
        "",
        "--image-dir",
        "images_sequence_4",
        "--image-csv",
        "img_sequence_4.csv",
        "--imu-csv",
        "imu_sequence_4.csv",
        "--gt-txt",
        str(REFERENCE),
        "--start-index",
        "5400",
        "--end-index",
        "6300",
        "--image-topic",
        "/camera/image_raw",
        "--imu-topic",
        "/rtimulib_node/imu",
        "--gt-topic",
        "/aqualoc/colmap_gt",
    ]
    try:
        subprocess.run(command, cwd=ROOT, check=True)
        observed = audit(temporary)
        counts = observed["topic_counts"]
        if counts.get("/camera/image_raw") != 901:
            raise RuntimeError(f"unexpected A04 image count: {counts}")
        if counts.get("/rtimulib_node/imu", 0) <= 0:
            raise RuntimeError(f"missing A04 IMU: {counts}")
        if counts.get("/aqualoc/colmap_gt", 0) < 40:
            raise RuntimeError(f"insufficient A04 proxy poses: {counts}")
        temporary.replace(OUTPUT)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
    payload: dict[str, object] = {
        "schema_version": "aqua-fe-confirmatory-v3-a04-root-layout-materialization-v1",
        "completed_at": datetime.now(timezone.utc).isoformat(),
        "rationale": "A04 archive members are at root; frontend/evaluation contracts unchanged",
        "archive": str(ARCHIVE),
        "archive_sha256": ARCHIVE_SHA256,
        "reference": str(REFERENCE),
        "reference_sha256": REFERENCE_SHA256,
        "command": command,
        "output": str(OUTPUT),
        "output_size_bytes": OUTPUT.stat().st_size,
        "output_sha256": sha256(OUTPUT),
        "audit": observed,
    }
    atomic_json(RECEIPT, payload)
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
