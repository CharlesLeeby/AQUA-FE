#!/usr/bin/env python3
"""Summarize the read-only AnyFeature ORB32 monocular-initialization audit.

This consumes the CSV emitted by ``anyfeature_orb_init_audit_v1.cpp``.  It does
not launch SLAM, alter the official checkout, or propose a replacement
initializer.  The Fundamental branch results are diagnostic counterfactuals:
the official state machine does not execute that branch when RH > 0.4.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import statistics
import subprocess
from collections import Counter
from pathlib import Path
from typing import Iterable


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def identity(path: Path) -> dict[str, object]:
    resolved = path.resolve(strict=True)
    return {
        "path": str(resolved),
        "size_bytes": resolved.stat().st_size,
        "sha256": sha256_file(resolved),
    }


def git(repo: Path, *args: str) -> str:
    return subprocess.check_output(
        ["git", "-C", str(repo), *args], text=True
    ).strip()


def integer_stats(values: Iterable[int]) -> dict[str, float | int]:
    rows = list(values)
    return {
        "min": min(rows),
        "median": statistics.median(rows),
        "mean": statistics.fmean(rows),
        "max": max(rows),
    }


def float_stats(values: Iterable[float]) -> dict[str, float]:
    rows = list(values)
    return {
        "min": min(rows),
        "median": statistics.median(rows),
        "mean": statistics.fmean(rows),
        "max": max(rows),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--csv", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--harness", required=True, type=Path)
    parser.add_argument("--repo", required=True, type=Path)
    parser.add_argument("--sequence", required=True, type=Path)
    parser.add_argument("--settings", required=True, type=Path)
    parser.add_argument("--library", required=True, type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    with args.csv.open(newline="", encoding="utf-8") as stream:
        rows = list(csv.DictReader(stream))

    matched = [row for row in rows if int(row["nmatches"]) >= 0]
    geometry = [row for row in rows if int(row["nmatches"]) >= 100]
    f_exact = [row for row in geometry if int(row["official_F_reconstruct"]) == 1]
    event_counts = Counter(row["event"] for row in rows)

    if len(rows) != 901:
        raise RuntimeError(f"expected 901 rows, got {len(rows)}")
    if len(geometry) != 596:
        raise RuntimeError(f"expected 596 geometry attempts, got {len(geometry)}")
    if any(int(row["initializer_success"]) for row in geometry):
        raise RuntimeError("unexpected initializer success")
    if any(float(row["official_RH"]) <= 0.4 for row in geometry):
        raise RuntimeError("not every geometry attempt selected Homography")
    if any(int(row["official_H_reconstruct"]) for row in geometry):
        raise RuntimeError("unexpected exact Homography reconstruction success")
    if any(int(row["official_H_relaxed00"]) for row in geometry):
        raise RuntimeError("unexpected relaxed Homography reconstruction success")
    if any(int(row["H_ambiguity_ok"]) for row in geometry):
        raise RuntimeError("unexpected Homography ambiguity-gate pass")

    source_names = [
        "include/Tracking.h",
        "src/Tracking.cc",
        "include/Initializer.h",
        "src/Initializer.cc",
        "include/FeatureMatcher.h",
        "src/FeatureMatcher.cc",
        "include/FeatureExtractor.h",
        "src/FeatureExtractor.cpp",
        "src/Feature_orb32.cpp",
        "src/Frame.cc",
        "src/Image.cpp",
        "include/Utils.h",
        "src/Utils.cpp",
    ]
    source_identities = {
        name: identity(args.repo / name) for name in source_names
    }

    rgb_lines = (args.sequence / "rgb.txt").read_text(encoding="utf-8").splitlines()
    timestamp_values = [float(line.split()[0]) for line in rgb_lines if line.strip()]
    timestamp_deltas = [b - a for a, b in zip(timestamp_values, timestamp_values[1:])]

    h_ratios = [
        int(row["H_second_good"]) / int(row["H_best_good"])
        for row in geometry
    ]
    result = {
        "schema": "aqua-fe-anyfeature-orb-init-readonly-audit-v1",
        "status": "PASS_ROOT_CAUSE_LOCALIZED",
        "scope": {
            "official_slam_rerun": False,
            "official_source_modified": False,
            "diagnostic_only": True,
            "counterfactual_fundamental_branch_changes_algorithm": True,
        },
        "identities": {
            "harness": identity(args.harness),
            "audit_csv": identity(args.csv),
            "official_library": identity(args.library),
            "official_settings": identity(args.settings),
            "sequence_rgb_txt": identity(args.sequence / "rgb.txt"),
            "sequence_calibration": identity(args.sequence / "calibration.yaml"),
            "sequence_conversion_manifest": identity(
                args.sequence / "conversion_manifest.json"
            ),
            "official_source": {
                "repo": str(args.repo.resolve(strict=True)),
                "commit": git(args.repo, "rev-parse", "HEAD"),
                "tree": git(args.repo, "rev-parse", "HEAD^{tree}"),
                "tracked_diff_empty": git(args.repo, "diff", "--exit-code") == "",
                "staged_diff_empty": git(
                    args.repo, "diff", "--cached", "--exit-code"
                ) == "",
                "files": source_identities,
            },
        },
        "input_contract": {
            "frame_count": len(rgb_lines),
            "timestamp_strict": all(delta > 0 for delta in timestamp_deltas),
            "span_seconds": timestamp_values[-1] - timestamp_values[0],
            "delta_seconds": float_stats(timestamp_deltas),
            "image_contract": "mono8 PNG, 968x608; audited by frozen adapter manifest",
        },
        "state_machine": {
            "rows": len(rows),
            "event_counts": dict(sorted(event_counts.items())),
            "matching_attempts": len(matched),
            "matches_below_100": sum(int(row["nmatches"]) < 100 for row in matched),
            "geometry_attempts_matches_ge_100": len(geometry),
            "initializer_successes": sum(
                int(row["initializer_success"]) for row in geometry
            ),
        },
        "features_and_motion": {
            "all_keypoints": integer_stats(int(row["keypoints"]) for row in rows),
            "octave0_keypoints": integer_stats(int(row["octave0"]) for row in rows),
            "official_initializer_matches": integer_stats(
                int(row["nmatches"]) for row in matched
            ),
            "matched_displacement_median_px": float_stats(
                float(row["disp_median_px"]) for row in matched
            ),
        },
        "model_selection": {
            "source_rule": "RH=SH/(SH+SF); RH>0.4 selects ReconstructH, otherwise ReconstructF",
            "rh": float_stats(float(row["official_RH"]) for row in geometry),
            "homography_selected": sum(
                float(row["official_RH"]) > 0.4 for row in geometry
            ),
            "fundamental_selected": sum(
                float(row["official_RH"]) <= 0.4 for row in geometry
            ),
            "fallback_after_selected_model_failure": False,
        },
        "homography_reconstruction": {
            "exact_successes": sum(
                int(row["official_H_reconstruct"]) for row in geometry
            ),
            "relaxed_min_parallax_0_min_triangulated_0_successes": sum(
                int(row["official_H_relaxed00"]) for row in geometry
            ),
            "svd_gate_passes": sum(int(row["H_svd_ok"]) for row in geometry),
            "ambiguity_gate_passes": sum(
                int(row["H_ambiguity_ok"]) for row in geometry
            ),
            "parallax_1deg_gate_passes": sum(
                int(row["H_parallax_ok"]) for row in geometry
            ),
            "min_good_50_gate_passes": sum(
                int(row["H_min_good_ok"]) for row in geometry
            ),
            "good_fraction_0_9_gate_passes": sum(
                int(row["H_fraction_ok"]) for row in geometry
            ),
            "second_best_over_best_good": float_stats(h_ratios),
            "required_second_best_over_best": "<0.75",
            "best_parallax_degrees": float_stats(
                float(row["H_best_parallax_deg"]) for row in geometry
            ),
        },
        "fundamental_counterfactual_diagnostic": {
            "officially_executed_by_state_machine": False,
            "exact_success_count_this_frozen_rng_realization": len(f_exact),
            "exact_success_rows": [
                {
                    "index": int(row["index"]),
                    "reference_index": int(row["reference_index"]),
                    "matches": int(row["nmatches"]),
                    "median_displacement_px": float(row["disp_median_px"]),
                    "rh": float(row["official_RH"]),
                }
                for row in f_exact
            ],
            "rng_warning": (
                "Official RandomIntegerGenerator seeds mt19937 from random_device; "
                "the exact counterfactual count can vary across diagnostic processes."
            ),
        },
        "root_cause": {
            "primary": (
                "All 596 viable pairs are routed to Homography; all fail the "
                "Homography unique-solution ambiguity gate, and the implementation "
                "does not fall back to Fundamental."
            ),
            "confidence": "high",
            "ruled_out_as_primary": [
                "missing or unread images",
                "too few ORB keypoints",
                "all pairs below the 100-match gate",
                "timestamp order or nominal-rate error",
                "image size/channel mismatch",
                "the post-save thread-destruction abort",
            ],
        },
        "allowed_next_path": {
            "without_algorithm_change": (
                "Use an outcome-blind predeclared sequence/window whose natural startup "
                "produces RH<=0.4 or a uniquely reconstructable H, preserving official code."
            ),
            "forbidden_under_current_comparison_rule": (
                "Adding H-to-F fallback, changing RH=0.4, weakening the 0.75 ambiguity "
                "gate, forcing Fundamental, or changing feature/matcher thresholds."
            ),
        },
    }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
