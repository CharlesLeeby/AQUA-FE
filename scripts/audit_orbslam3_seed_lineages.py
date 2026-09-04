#!/usr/bin/env python3
"""Summarize lineage lifetimes from ORB-SLAM3 external seed files."""

from __future__ import annotations

import argparse
import csv
import statistics
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class LineageStats:
    feature_id: int
    frame_indices: set[int] = field(default_factory=set)
    timestamps_ns: list[int] = field(default_factory=list)
    qualities: list[float] = field(default_factory=list)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--group",
        action="append",
        required=True,
        metavar="NAME=SEEDS,TIMES",
        help="Seed file and native image timestamp file for one experiment group.",
    )
    parser.add_argument("--output-csv", required=True)
    return parser.parse_args()


def load_image_frames(path: Path) -> dict[int, int]:
    frames: dict[int, int] = {}
    for line in path.read_text(encoding="ascii").splitlines():
        line = line.strip()
        if not line:
            continue
        timestamp_ns = int(line)
        if timestamp_ns in frames:
            raise ValueError(f"duplicate image timestamp {timestamp_ns} in {path}")
        frames[timestamp_ns] = len(frames)
    if not frames:
        raise ValueError(f"empty image timestamp file: {path}")
    return frames


def audit_group(name: str, seeds_path: Path, times_path: Path) -> list[dict[str, object]]:
    image_frames = load_image_frames(times_path)
    lineages: dict[int, LineageStats] = {}
    unmapped: set[int] = set()

    with seeds_path.open(encoding="ascii") as handle:
        for line_number, raw_line in enumerate(handle, 1):
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            fields = line.split()
            if len(fields) < 5:
                raise ValueError(f"malformed seed row at {seeds_path}:{line_number}")
            timestamp_ns = int(fields[0])
            feature_id = int(fields[3])
            quality = float(fields[4])
            frame_index = image_frames.get(timestamp_ns)
            if frame_index is None:
                unmapped.add(timestamp_ns)
                continue
            stats = lineages.setdefault(feature_id, LineageStats(feature_id))
            stats.frame_indices.add(frame_index)
            stats.timestamps_ns.append(timestamp_ns)
            stats.qualities.append(quality)

    if unmapped:
        examples = ", ".join(str(value) for value in sorted(unmapped)[:3])
        raise ValueError(
            f"{len(unmapped)} seed timestamps from {seeds_path} are absent from "
            f"{times_path}; examples: {examples}"
        )
    if not lineages:
        return []

    rows: list[dict[str, object]] = []
    for feature_id in sorted(lineages):
        stats = lineages[feature_id]
        frame_indices = sorted(stats.frame_indices)
        timestamps_ns = sorted(stats.timestamps_ns)
        rows.append(
            {
                "group": name,
                "feature_id": feature_id,
                "observations": len(stats.timestamps_ns),
                "unique_frames": len(frame_indices),
                "first_frame": frame_indices[0],
                "last_frame": frame_indices[-1],
                "frame_span": frame_indices[-1] - frame_indices[0] + 1,
                "first_timestamp_ns": timestamps_ns[0],
                "last_timestamp_ns": timestamps_ns[-1],
                "duration_s": (timestamps_ns[-1] - timestamps_ns[0]) * 1e-9,
                "quality_median": statistics.median(stats.qualities),
                "quality_min": min(stats.qualities),
                "quality_max": max(stats.qualities),
                "seed_file": str(seeds_path),
                "image_times_file": str(times_path),
            }
        )
    return rows


def parse_group(value: str) -> tuple[str, Path, Path]:
    if "=" not in value or "," not in value:
        raise ValueError(f"invalid --group {value!r}; expected NAME=SEEDS,TIMES")
    name, paths = value.split("=", 1)
    seeds, times = paths.split(",", 1)
    seeds_path = Path(seeds).resolve()
    times_path = Path(times).resolve()
    if not name:
        raise ValueError("group name must not be empty")
    if not seeds_path.is_file():
        raise ValueError(f"missing seed file: {seeds_path}")
    if not times_path.is_file():
        raise ValueError(f"missing image timestamp file: {times_path}")
    return name, seeds_path, times_path


def main() -> int:
    args = parse_args()
    rows: list[dict[str, object]] = []
    for value in args.group:
        name, seeds_path, times_path = parse_group(value)
        rows.extend(audit_group(name, seeds_path, times_path))
    if not rows:
        raise SystemExit("no seed lineages found")

    output = Path(args.output_csv).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    print(f"wrote {len(rows)} lineages to {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
