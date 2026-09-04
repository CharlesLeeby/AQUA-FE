#!/usr/bin/env python3
"""Evaluate fixed frame segments of repeated ORB-SLAM3 trajectories."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import re
import shutil
import subprocess
import sys
from pathlib import Path


ROLE_ORDER = (
    "orb_only",
    "drop",
    "full_bridge_off",
    "full_lineage_no_grace",
    "full_unbounded",
    "full",
)
REQUIRED_ROLES = ("orb_only", "drop", "full")


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def role_and_repeat(path: Path) -> tuple[str, int]:
    match = re.fullmatch(
        r"(orb_only|drop|full_bridge_off|full_lineage_no_grace|full_unbounded|full)_r(\d+)",
        path.name,
    )
    if not match:
        raise ValueError(path.name)
    return match.group(1), int(match.group(2))


def discover_runs(root: Path) -> list[tuple[str, int, Path]]:
    indexed: dict[tuple[str, int], Path] = {}
    for path in root.iterdir():
        if not path.is_dir():
            continue
        try:
            role, repeat = role_and_repeat(path)
        except ValueError:
            continue
        key = (role, repeat)
        if key in indexed:
            raise SystemExit(f"duplicate run role/repeat {key}: {root}")
        indexed[key] = path

    repeat_sets = {
        role: {repeat for candidate, repeat in indexed if candidate == role}
        for role in REQUIRED_ROLES
    }
    expected_repeats = repeat_sets["full"]
    if not expected_repeats or any(
        repeats != expected_repeats for repeats in repeat_sets.values()
    ):
        raise SystemExit(f"incomplete required run matrix: {root}")
    for role in ("full_bridge_off", "full_lineage_no_grace", "full_unbounded"):
        repeats = {repeat for candidate, repeat in indexed if candidate == role}
        if repeats and repeats != expected_repeats:
            raise SystemExit(f"incomplete optional run matrix for {role}: {root}")

    return [
        (role, repeat, path)
        for (role, repeat), path in sorted(
            indexed.items(), key=lambda item: (item[0][1], ROLE_ORDER.index(item[0][0]))
        )
    ]


def parse_segment(value: str, frame_count: int) -> tuple[str, int, int]:
    fields = value.split(":")
    if len(fields) != 3 or not fields[0]:
        raise argparse.ArgumentTypeError(
            f"invalid segment {value!r}; expected NAME:FIRST_FRAME:LAST_FRAME"
        )
    name = fields[0]
    if not re.fullmatch(r"[A-Za-z0-9_.-]+", name):
        raise argparse.ArgumentTypeError(f"invalid segment name {name!r}")
    try:
        first = int(fields[1])
        last = int(fields[2])
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"invalid segment frame in {value!r}") from exc
    if not 0 <= first <= last < frame_count:
        raise argparse.ArgumentTypeError(
            f"segment {value!r} is outside frame range [0, {frame_count - 1}]"
        )
    return name, first, last


def metric_stats(text: str) -> dict[str, float]:
    result: dict[str, float] = {}
    for key in ("rmse", "median", "max"):
        match = re.search(rf"^\s*{key}\s+([0-9.eE+-]+)\s*$", text, re.MULTILINE)
        if not match:
            raise RuntimeError(f"missing {key} in evo output")
        value = float(match.group(1))
        if not math.isfinite(value):
            raise RuntimeError(f"non-finite {key} in evo output")
        result[key] = value
    return result


def run_evo(command: list[str]) -> dict[str, float]:
    result = subprocess.run(
        command,
        check=True,
        text=True,
        capture_output=True,
        timeout=120,
    )
    return metric_stats(result.stdout)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs-root", required=True, type=Path)
    parser.add_argument("--gt-tum", required=True, type=Path)
    parser.add_argument("--image-times", required=True, type=Path)
    parser.add_argument(
        "--segment",
        action="append",
        required=True,
        help="Segment as NAME:FIRST_FRAME:LAST_FRAME; may be repeated.",
    )
    parser.add_argument("--max-time-diff", required=True, type=float)
    parser.add_argument("--rpe-delta-frames", required=True, type=int)
    parser.add_argument(
        "--trajectory-kind",
        choices=("reconstructed", "online"),
        default="reconstructed",
        help="Evaluate final-map reconstructed poses or saved online poses.",
    )
    parser.add_argument("--output-csv", required=True, type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    runs_root = args.runs_root.resolve()
    gt_tum = args.gt_tum.resolve()
    image_times_path = args.image_times.resolve()
    output = args.output_csv.resolve()
    manifest_path = output.with_name(output.name + ".manifest.json")
    for path in (runs_root, gt_tum, image_times_path):
        if not path.exists():
            raise SystemExit(f"missing input: {path}")
    if not runs_root.is_dir() or not gt_tum.is_file() or not image_times_path.is_file():
        raise SystemExit("runs root, GT, or image-times input has the wrong type")
    if output.exists() or manifest_path.exists():
        raise SystemExit(f"refusing existing output or manifest: {output}")
    if not math.isfinite(args.max_time_diff) or args.max_time_diff <= 0:
        raise SystemExit("--max-time-diff must be finite and positive")
    if args.rpe_delta_frames <= 0:
        raise SystemExit("--rpe-delta-frames must be positive")

    image_ns = [
        int(line)
        for line in image_times_path.read_text(encoding="ascii").splitlines()
        if line.strip()
    ]
    if not image_ns or image_ns != sorted(set(image_ns)):
        raise SystemExit(f"image timestamps must be nonempty, unique, and sorted: {image_times_path}")
    image_times = [value * 1e-9 for value in image_ns]
    segments = [parse_segment(value, len(image_times)) for value in args.segment]
    names = [segment[0] for segment in segments]
    if len(names) != len(set(names)):
        raise SystemExit("segment names must be unique")

    runs = discover_runs(runs_root)
    trajectory_hashes: dict[str, str] = {}
    rows: list[dict[str, object]] = []
    for role, repeat, run_dir in runs:
        trajectory_glob = (
            "online_f_*_sec.txt"
            if args.trajectory_kind == "online"
            else "f_*_sec.txt"
        )
        trajectories = list(run_dir.glob(trajectory_glob))
        if len(trajectories) != 1:
            raise SystemExit(
                f"expected one {args.trajectory_kind} seconds trajectory in "
                f"{run_dir}, found {len(trajectories)}"
            )
        trajectory = trajectories[0].resolve()
        trajectory_hashes[str(trajectory)] = file_sha256(trajectory)
        trajectory_stamps = [
            float(line.split()[0])
            for line in trajectory.read_text(encoding="ascii").splitlines()
            if len(line.split()) == 8
        ]
        for name, first, last in segments:
            start = image_times[first]
            end = image_times[last]
            common = [
                "tum",
                str(gt_tum),
                str(trajectory),
                "-r",
                "trans_part",
                "-a",
                "-s",
                "--t_max_diff",
                str(args.max_time_diff),
                "--t_start",
                str(start),
                "--t_end",
                str(end),
                "--no_warnings",
            ]
            ape = run_evo(["evo_ape", *common])
            rpe = run_evo(
                [
                    "evo_rpe",
                    *common,
                    "-d",
                    str(args.rpe_delta_frames),
                    "-u",
                    "f",
                    "--all_pairs",
                ]
            )
            rows.append(
                {
                    "role": role,
                    "repeat": repeat,
                    "trajectory_kind": args.trajectory_kind,
                    "segment": name,
                    "first_frame": first,
                    "last_frame": last,
                    "trajectory_poses": sum(start <= stamp <= end for stamp in trajectory_stamps),
                    "ape_rmse_m": ape["rmse"],
                    "ape_median_m": ape["median"],
                    "ape_max_m": ape["max"],
                    "rpe_rmse_m": rpe["rmse"],
                    "rpe_median_m": rpe["median"],
                    "rpe_max_m": rpe["max"],
                    "status": "ok",
                    "run_dir": str(run_dir),
                    "trajectory": str(trajectory),
                }
            )

    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)

    script_path = Path(__file__).resolve()
    tool_paths = {
        name: Path(shutil.which(name) or "").resolve() for name in ("evo_ape", "evo_rpe")
    }
    if any(not path.is_file() for path in tool_paths.values()):
        raise SystemExit("could not resolve evo_ape/evo_rpe executable paths")
    manifest_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "command": [str(script_path), *sys.argv[1:]],
                "analyzer_sha256": file_sha256(script_path),
                "runs_root": str(runs_root),
                "gt_tum": str(gt_tum),
                "gt_tum_sha256": file_sha256(gt_tum),
                "image_times": str(image_times_path),
                "image_times_sha256": file_sha256(image_times_path),
                "trajectory_kind": args.trajectory_kind,
                "segments": [
                    {"name": name, "first_frame": first, "last_frame": last}
                    for name, first, last in segments
                ],
                "trajectory_sha256": trajectory_hashes,
                "tools": {
                    name: {"path": str(path), "sha256": file_sha256(path)}
                    for name, path in tool_paths.items()
                },
                "output_csv": str(output),
                "output_csv_sha256": file_sha256(output),
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"wrote {len(rows)} segment evaluations to {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
