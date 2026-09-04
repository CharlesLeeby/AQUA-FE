#!/usr/bin/env python3
"""Prepend frames from an adjacent ORB-SLAM3 dataset without changing suffix data."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import shutil
from pathlib import Path


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def parse_times(path: Path) -> list[int]:
    if not path.is_file():
        raise SystemExit(f"missing image times: {path}")
    try:
        times = [int(line) for line in path.read_text(encoding="ascii").splitlines() if line]
    except ValueError as exc:
        raise SystemExit(f"invalid timestamp in {path}: {exc}") from exc
    if not times:
        raise SystemExit(f"empty image times: {path}")
    if any(current <= previous for previous, current in zip(times, times[1:])):
        raise SystemExit(f"image timestamps are not strictly increasing: {path}")
    return times


def load_times(dataset: Path, selected_times_path: Path | None = None) -> list[int]:
    path = dataset / "cam0_times.txt"
    dataset_times = parse_times(path)
    times = dataset_times
    if selected_times_path is not None:
        selected_times_path = selected_times_path.resolve()
        times = parse_times(selected_times_path)
        dataset_time_set = set(dataset_times)
        missing_from_dataset = [stamp for stamp in times if stamp not in dataset_time_set]
        if missing_from_dataset:
            raise SystemExit(
                f"{len(missing_from_dataset)} selected timestamps are absent from {path}"
            )
    image_dir = dataset / "mav0/cam0/data"
    missing = [stamp for stamp in times if not (image_dir / f"{stamp}.png").is_file()]
    if missing:
        raise SystemExit(f"missing {len(missing)} timestamped images in {image_dir}")
    return times


def load_csv_rows(path: Path) -> tuple[list[str], dict[int, list[str]]]:
    if not path.is_file():
        raise SystemExit(f"missing CSV input: {path}")
    with path.open(newline="", encoding="ascii") as handle:
        reader = csv.reader(handle)
        try:
            header = next(reader)
        except StopIteration as exc:
            raise SystemExit(f"empty CSV input: {path}") from exc
        rows: dict[int, list[str]] = {}
        for row in reader:
            if not row:
                continue
            try:
                stamp = int(row[0])
            except ValueError as exc:
                raise SystemExit(f"invalid CSV timestamp in {path}: {row[0]!r}") from exc
            previous = rows.get(stamp)
            if previous is not None and previous != row:
                raise SystemExit(f"conflicting duplicate timestamp {stamp} in {path}")
            rows[stamp] = row
    return header, rows


def merge_csv(
    prefix_path: Path,
    suffix_path: Path,
    output_path: Path,
    first_stamp: int,
    last_stamp: int,
) -> int:
    prefix_header, prefix_rows = load_csv_rows(prefix_path)
    suffix_header, suffix_rows = load_csv_rows(suffix_path)
    if prefix_header != suffix_header:
        raise SystemExit(f"CSV headers differ: {prefix_path} vs {suffix_path}")
    merged = dict(prefix_rows)
    for stamp, row in suffix_rows.items():
        previous = merged.get(stamp)
        if previous is not None and previous != row:
            raise SystemExit(
                f"conflicting timestamp {stamp} across {prefix_path} and {suffix_path}"
            )
        merged[stamp] = row
    selected = [merged[stamp] for stamp in sorted(merged) if first_stamp <= stamp <= last_stamp]
    if not selected:
        raise SystemExit(f"no rows selected for {output_path}")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", newline="", encoding="ascii") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(prefix_header)
        writer.writerows(selected)
    return len(selected)


def load_tum_rows(path: Path) -> dict[int, str]:
    if not path.is_file():
        raise SystemExit(f"missing TUM input: {path}")
    rows: dict[int, str] = {}
    for raw_line in path.read_text(encoding="ascii").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        fields = line.split()
        if len(fields) < 8:
            raise SystemExit(f"invalid TUM row in {path}: {line}")
        try:
            stamp = int(round(float(fields[0]) * 1e9))
        except ValueError as exc:
            raise SystemExit(f"invalid TUM timestamp in {path}: {fields[0]!r}") from exc
        previous = rows.get(stamp)
        if previous is not None and previous != line:
            raise SystemExit(f"conflicting duplicate TUM timestamp {stamp} in {path}")
        rows[stamp] = line
    return rows


def merge_tum(
    prefix_path: Path,
    suffix_path: Path,
    output_path: Path,
    first_stamp: int,
    last_stamp: int,
) -> int:
    merged = load_tum_rows(prefix_path)
    for stamp, row in load_tum_rows(suffix_path).items():
        previous = merged.get(stamp)
        if previous is not None and previous != row:
            raise SystemExit(
                f"conflicting TUM timestamp {stamp} across {prefix_path} and {suffix_path}"
            )
        merged[stamp] = row
    selected = [merged[stamp] for stamp in sorted(merged) if first_stamp <= stamp <= last_stamp]
    if not selected:
        raise SystemExit("no ground-truth poses overlap the composed dataset")
    output_path.write_text("".join(f"{row}\n" for row in selected), encoding="ascii")
    return len(selected)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prefix-dataset", required=True, type=Path)
    parser.add_argument("--suffix-dataset", required=True, type=Path)
    parser.add_argument(
        "--prefix-times",
        type=Path,
        help="Optional strictly increasing subset of the prefix dataset timestamps.",
    )
    parser.add_argument(
        "--suffix-times",
        type=Path,
        help="Optional strictly increasing subset of the suffix dataset timestamps.",
    )
    parser.add_argument("--prefix-frames", required=True, type=int)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--imu-margin-ns", type=int, default=500_000_000)
    parser.add_argument("--gt-margin-ns", type=int, default=600_000_000)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    prefix = args.prefix_dataset.resolve()
    suffix = args.suffix_dataset.resolve()
    output = args.output_dir.resolve()
    if args.prefix_frames < 1:
        raise SystemExit("--prefix-frames must be positive")
    if args.imu_margin_ns < 0 or args.gt_margin_ns < 0:
        raise SystemExit("time margins cannot be negative")
    if output.exists():
        raise SystemExit(f"refusing existing output directory: {output}")

    prefix_selection = args.prefix_times.resolve() if args.prefix_times else None
    suffix_selection = args.suffix_times.resolve() if args.suffix_times else None
    prefix_times = load_times(prefix, prefix_selection)
    suffix_times = load_times(suffix, suffix_selection)
    eligible_prefix = [stamp for stamp in prefix_times if stamp < suffix_times[0]]
    if len(eligible_prefix) < args.prefix_frames:
        raise SystemExit(
            f"only {len(eligible_prefix)} prefix frames precede suffix start; "
            f"requested {args.prefix_frames}"
        )
    selected_prefix = eligible_prefix[-args.prefix_frames :]
    output_times = selected_prefix + suffix_times
    if any(current <= previous for previous, current in zip(output_times, output_times[1:])):
        raise SystemExit("composed image timestamps are not strictly increasing")

    output_image_dir = output / "mav0/cam0/data"
    output_image_dir.mkdir(parents=True)
    image_records: list[dict[str, object]] = []
    for role, dataset, times in (
        ("prefix", prefix, selected_prefix),
        ("suffix", suffix, suffix_times),
    ):
        source_dir = dataset / "mav0/cam0/data"
        for stamp in times:
            source = source_dir / f"{stamp}.png"
            destination = output_image_dir / source.name
            shutil.copy2(source, destination)
            source_hash = sha256(source)
            output_hash = sha256(destination)
            if source_hash != output_hash:
                raise SystemExit(f"image hash mismatch after copy: {source}")
            image_records.append(
                {
                    "role": role,
                    "timestamp_ns": stamp,
                    "source": str(source),
                    "sha256": source_hash,
                }
            )

    times_path = output / "cam0_times.txt"
    times_path.write_text("".join(f"{stamp}\n" for stamp in output_times), encoding="ascii")
    first_image = output_times[0]
    last_image = output_times[-1]
    imu_count = merge_csv(
        prefix / "mav0/imu0/data.csv",
        suffix / "mav0/imu0/data.csv",
        output / "mav0/imu0/data.csv",
        first_image - args.imu_margin_ns,
        last_image,
    )
    gt_csv_count = merge_csv(
        prefix / "mav0/state_groundtruth_estimate0/data.csv",
        suffix / "mav0/state_groundtruth_estimate0/data.csv",
        output / "mav0/state_groundtruth_estimate0/data.csv",
        first_image - args.gt_margin_ns,
        last_image + args.gt_margin_ns,
    )
    gt_tum_count = merge_tum(
        prefix / "groundtruth_tum.txt",
        suffix / "groundtruth_tum.txt",
        output / "groundtruth_tum.txt",
        first_image - args.gt_margin_ns,
        last_image + args.gt_margin_ns,
    )
    if gt_csv_count != gt_tum_count:
        raise SystemExit(
            f"ground-truth count mismatch: CSV={gt_csv_count} TUM={gt_tum_count}"
        )

    artifact_paths = [
        times_path,
        output / "groundtruth_tum.txt",
        output / "mav0/imu0/data.csv",
        output / "mav0/state_groundtruth_estimate0/data.csv",
    ]
    manifest = {
        "schema_version": 1,
        "composite": True,
        "prefix_dataset": str(prefix),
        "suffix_dataset": str(suffix),
        "prefix_times": str(prefix_selection) if prefix_selection else None,
        "suffix_times": str(suffix_selection) if suffix_selection else None,
        "prefix_frames_requested": args.prefix_frames,
        "prefix_frames_selected": len(selected_prefix),
        "suffix_frames": len(suffix_times),
        "image_count": len(output_times),
        "first_image_ns": first_image,
        "last_image_ns": last_image,
        "imu_count": imu_count,
        "gt_csv_count": gt_csv_count,
        "gt_tum_count": gt_tum_count,
        "suffix_times_exact": output_times[-len(suffix_times) :] == suffix_times,
        "suffix_images_exact": all(
            record["role"] != "suffix"
            or sha256(output_image_dir / f"{record['timestamp_ns']}.png") == record["sha256"]
            for record in image_records
        ),
        "source_time_sha256": {
            "prefix": sha256(prefix / "cam0_times.txt"),
            "suffix": sha256(suffix / "cam0_times.txt"),
        },
        "selection_time_sha256": {
            "prefix": sha256(prefix_selection) if prefix_selection else None,
            "suffix": sha256(suffix_selection) if suffix_selection else None,
        },
        "output_artifact_sha256": {str(path.relative_to(output)): sha256(path) for path in artifact_paths},
        "images": image_records,
    }
    metadata_path = output / "export_metadata.json"
    metadata_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="ascii"
    )
    print(
        json.dumps(
            {
                key: manifest[key]
                for key in (
                    "prefix_frames_selected",
                    "suffix_frames",
                    "image_count",
                    "imu_count",
                    "gt_tum_count",
                    "suffix_times_exact",
                    "suffix_images_exact",
                )
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
