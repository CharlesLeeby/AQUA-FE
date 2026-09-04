#!/usr/bin/env python3
"""Compare two raw VIO trajectories on one frozen tilted-wall normal."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference", type=Path, required=True)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--normal-summary", type=Path, required=True)
    parser.add_argument("--cutoff-ns", type=int)
    parser.add_argument("--output-json", type=Path, required=True)
    return parser.parse_args()


def load_trajectory(path: Path) -> tuple[np.ndarray, np.ndarray]:
    rows: list[list[float]] = []
    stamps: list[int] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        parts = line.split(",")
        try:
            stamps.append(int(parts[0]))
            rows.append([float(parts[1]), float(parts[2]), float(parts[3])])
        except (IndexError, ValueError) as exc:
            raise ValueError(f"invalid trajectory row {path}:{line_number}") from exc
    stamp_array = np.asarray(stamps, dtype=np.int64)
    position_array = np.asarray(rows, dtype=np.float64)
    if len(stamp_array) == 0 or np.any(np.diff(stamp_array) <= 0):
        raise ValueError(f"trajectory is empty or non-monotonic: {path}")
    return stamp_array, position_array


def metrics(stamps: np.ndarray, positions: np.ndarray, normal: np.ndarray) -> dict[str, object]:
    projection = positions @ normal
    centered = projection - np.mean(projection)
    steps = np.linalg.norm(np.diff(positions, axis=0), axis=1)
    return {
        "samples": int(len(stamps)),
        "first_stamp_ns": int(stamps[0]),
        "last_stamp_ns": int(stamps[-1]),
        "path_length_m": float(np.sum(steps)),
        "max_step_m": float(np.max(steps)) if len(steps) else 0.0,
        "step_rms_m": float(np.sqrt(np.mean(steps * steps))) if len(steps) else 0.0,
        "fixed_tilted_wall": {
            "centered_residual_rms_m": float(np.sqrt(np.mean(centered * centered))),
            "centered_residual_p50_abs_m": float(np.percentile(np.abs(centered), 50)),
            "centered_residual_p90_abs_m": float(np.percentile(np.abs(centered), 90)),
            "thickness_m": float(np.max(projection) - np.min(projection)),
        },
    }


def flatten(prefix: str, value: object, output: dict[str, float]) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            flatten(f"{prefix}.{key}" if prefix else key, child, output)
    elif isinstance(value, (int, float)) and not isinstance(value, bool):
        output[prefix] = float(value)


def main() -> int:
    args = parse_args()
    ref_stamps, ref_positions = load_trajectory(args.reference)
    cand_stamps, cand_positions = load_trajectory(args.candidate)
    if not np.array_equal(ref_stamps, cand_stamps):
        raise SystemExit("reference and candidate timestamp grids differ")
    normal_document = json.loads(args.normal_summary.read_text(encoding="utf-8"))
    normal = np.asarray(normal_document["wall_normal"], dtype=np.float64)
    normal /= np.linalg.norm(normal)
    included = np.ones(len(ref_stamps), dtype=bool)
    if args.cutoff_ns is not None:
        included = ref_stamps <= args.cutoff_ns
    if not np.any(included):
        raise SystemExit("cutoff excludes every trajectory sample")
    ref = metrics(ref_stamps[included], ref_positions[included], normal)
    cand = metrics(cand_stamps[included], cand_positions[included], normal)
    ref_flat: dict[str, float] = {}
    cand_flat: dict[str, float] = {}
    flatten("", ref, ref_flat)
    flatten("", cand, cand_flat)
    excluded_keys = {"samples", "first_stamp_ns", "last_stamp_ns"}
    delta_percent = {
        key: 100.0 * (cand_flat[key] - value) / value
        for key, value in ref_flat.items()
        if key not in excluded_keys and value != 0.0 and key in cand_flat
    }
    result = {
        "schema": "fixed_tilted_wall_pair_v1",
        "status": "PASS",
        "reference": str(args.reference.resolve()),
        "candidate": str(args.candidate.resolve()),
        "timestamp_grid_exact": True,
        "trajectory_rows": int(len(ref_stamps)),
        "included_rows": int(np.count_nonzero(included)),
        "excluded_after_cutoff_rows": int(np.count_nonzero(~included)),
        "cutoff_ns": args.cutoff_ns,
        "normal_summary": str(args.normal_summary.resolve()),
        "normal_summary_sha256": hashlib.sha256(args.normal_summary.read_bytes()).hexdigest(),
        "fixed_wall_normal": normal.tolist(),
        "tilt_from_strict_vertical_deg": float(
            np.degrees(np.arcsin(np.clip(abs(normal[2]), 0.0, 1.0)))
        ),
        "arms": {"reference": ref, "candidate": cand},
        "candidate_delta_percent": delta_percent,
    }
    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
