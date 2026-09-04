#!/usr/bin/env python3
"""Summarize MIMIR-UW health-profile runs without hiding rejected windows."""

from __future__ import annotations

import argparse
import csv
import re
from pathlib import Path


def key_values(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if "=" in line:
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip()
    return values


def count_lines(path: Path) -> int:
    if not path.exists():
        return 0
    with path.open(encoding="utf-8", errors="replace") as handle:
        return sum(1 for line in handle if line.strip())


def count_text(path: Path, needle: str) -> int:
    if not path.exists():
        return 0
    return path.read_text(encoding="utf-8", errors="replace").count(needle)


def infer_window(run_dir: Path) -> dict[str, str]:
    match = re.search(
        r"_(oceanfloor|sandpipe|seafloor)_"
        r"(track\d+(?:_(?:dark|light))?)_s([0-9p]+)_d([0-9p]+)_",
        run_dir.name.lower(),
    )
    if not match:
        return {}
    environment = {
        "oceanfloor": "OceanFloor",
        "sandpipe": "SandPipe",
        "seafloor": "SeaFloor",
    }[match.group(1)]
    return {
        "environment": environment,
        "track": match.group(2),
        "start_offset": match.group(3).replace("p", "."),
        "duration": match.group(4).replace("p", "."),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-dir", action="append", required=True)
    parser.add_argument("--output-csv", required=True)
    args = parser.parse_args()

    rows: list[dict[str, object]] = []
    for run_arg in args.run_dir:
        run_dir = Path(run_arg)
        if not run_dir.is_dir():
            raise RuntimeError(f"run directory does not exist or is not a directory: {run_dir}")
        manifest = key_values(run_dir / "replay_manifest.txt")
        inferred = infer_window(run_dir)
        metrics = key_values(run_dir / "ape.txt")
        log = run_dir / "vins.log"
        pose_lines = count_lines(run_dir / "vins_output" / "vio.csv")
        init_finishes = count_text(log, "Initialization finish!")
        rejection_count = count_text(log, "reject initialization:")
        failfast_count = count_text(log, "failure detection!")
        coverage = float(metrics.get("output_coverage_ratio", "0") or 0)
        metric_init_success = int(float(metrics.get("init_success", "0") or 0))
        accepted = bool(metric_init_success and coverage >= 0.5 and failfast_count == 0)
        if accepted:
            status = "accepted"
        elif pose_lines == 0:
            status = "rejected_before_publish"
        else:
            status = "failfast_partial"
        rows.append(
            {
                "environment": manifest.get("environment", inferred.get("environment", "")),
                "track": manifest.get("track", inferred.get("track", "")),
                "start_offset_s": manifest.get(
                    "start_offset", inferred.get("start_offset", "")
                ),
                "duration_s": manifest.get("duration", inferred.get("duration", "")),
                "status": status,
                "accepted": int(accepted),
                "output_poses": metrics.get("output_poses", pose_lines),
                "coverage_ratio": metrics.get("output_coverage_ratio", "0"),
                "se3_ape_rmse_m": metrics.get("se3_ape_rmse_m", ""),
                "rpe_1s_rmse_m": metrics.get("rpe_trans_rmse_m", ""),
                "initialization_finishes": init_finishes,
                "initialization_rejections": rejection_count,
                "failfast_events": failfast_count,
                "run_dir": str(run_dir),
            }
        )

    output = Path(args.output_csv)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    accepted_count = sum(int(row["accepted"]) for row in rows)
    print(f"wrote {len(rows)} rows to {output}; accepted={accepted_count}/{len(rows)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
