#!/usr/bin/env python3
"""Create an immutable, timestamp-consistent ORB-SLAM3 seed probe window."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def nonempty_lines(path: Path) -> list[str]:
    return [line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def timestamp(line: str, path: Path) -> str:
    value = line.split()[0]
    try:
        int(value)
    except ValueError as exc:
        raise SystemExit(f"invalid timestamp in {path}: {line}") from exc
    return value


def subset_seed_lines(
    path: Path, selected_timestamps: set[str], source_timestamps: set[str]
) -> tuple[list[str], int]:
    output: list[str] = []
    rows = 0
    for line in nonempty_lines(path):
        if line.startswith("#"):
            output.append(line)
            continue
        stamp = timestamp(line, path)
        if stamp not in source_timestamps:
            raise SystemExit(f"seed timestamp is absent from image times: {stamp} in {path}")
        if stamp in selected_timestamps:
            output.append(line)
            rows += 1
    return output, rows


def write_lines(path: Path, lines: list[str]) -> None:
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image-times", required=True, type=Path)
    parser.add_argument("--full-seeds", required=True, type=Path)
    parser.add_argument("--drop-seeds", required=True, type=Path)
    parser.add_argument("--first-frame", required=True, type=int)
    parser.add_argument("--last-frame", required=True, type=int)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()

    inputs = (args.image_times, args.full_seeds, args.drop_seeds)
    for path in inputs:
        if not path.is_file():
            raise SystemExit(f"missing input: {path}")
    if args.output_dir.exists():
        raise SystemExit(f"refusing existing output directory: {args.output_dir}")

    time_lines = nonempty_lines(args.image_times)
    time_stamps = [timestamp(line, args.image_times) for line in time_lines]
    if len(time_stamps) != len(set(time_stamps)):
        raise SystemExit(f"duplicate image timestamp in {args.image_times}")
    if not 0 <= args.first_frame <= args.last_frame < len(time_lines):
        raise SystemExit(
            f"frame range [{args.first_frame}, {args.last_frame}] is outside "
            f"[0, {len(time_lines) - 1}]"
        )

    selected_times = time_lines[args.first_frame : args.last_frame + 1]
    selected_stamps = set(time_stamps[args.first_frame : args.last_frame + 1])
    source_stamps = set(time_stamps)
    full_lines, full_rows = subset_seed_lines(
        args.full_seeds, selected_stamps, source_stamps
    )
    drop_lines, drop_rows = subset_seed_lines(
        args.drop_seeds, selected_stamps, source_stamps
    )

    args.output_dir.mkdir(parents=True)
    output_times = args.output_dir / "cam0_times.txt"
    output_full = args.output_dir / "full_seeds.txt"
    output_drop = args.output_dir / "drop_seeds.txt"
    write_lines(output_times, selected_times)
    write_lines(output_full, full_lines)
    write_lines(output_drop, drop_lines)

    manifest = {
        "schema_version": 1,
        "first_frame": args.first_frame,
        "last_frame": args.last_frame,
        "selected_frames": len(selected_times),
        "selected_full_seed_rows": full_rows,
        "selected_drop_seed_rows": drop_rows,
        "inputs": {
            str(path.resolve()): sha256(path) for path in inputs
        },
        "outputs": {
            output_times.name: sha256(output_times),
            output_full.name: sha256(output_full),
            output_drop.name: sha256(output_drop),
        },
    }
    (args.output_dir / "subset_manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(
        f"wrote {len(selected_times)} frames, {full_rows} full seeds, "
        f"and {drop_rows} drop seeds to {args.output_dir.resolve()}"
    )


if __name__ == "__main__":
    main()
