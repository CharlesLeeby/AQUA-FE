#!/usr/bin/env python3
"""Evaluate repeated seeded ORB-SLAM3 monocular runs with a common protocol."""

from __future__ import annotations

import argparse
import csv
import json
import math
import re
import subprocess
from pathlib import Path


INSTRUMENTATION_COUNT_FIELDS = (
    "loaded_seed_observations",
    "attempted_seed_observations",
    "accepted_seed_observations",
    "seed_lineages_loaded",
    "seed_lineages_accepted",
    "seed_lineages_with_mappoint",
    "seed_lineages_surviving",
    "accepted_observations_with_mappoint",
    "distinct_mappoints",
    "keyframe_observations",
    "distinct_keyframes",
    "event_capacity",
    "events_recorded",
    "events_overflowed",
    "related_mappoint_capacity",
    "related_mappoint_overflowed",
    "loaded_seed_rows",
    "phase_attempted",
    "phase_skipped",
    "extractor_accepted",
    "extractor_rejected_border",
    "extractor_rejected_native_duplicate",
    "extractor_rejected_seed_duplicate",
    "frame_accepted",
    "raw_association_events",
    "frame_final",
    "related_mappoints",
    "lineages",
)

INSTRUMENTATION_NULLABLE_NUMBER_FIELDS = (
    "mappoint_observations_median",
    "mappoint_observations_max",
    "mappoint_found_ratio_median",
    "max_covisibility_weight",
)

INSTRUMENTATION_BOOLEAN_FIELDS = (
    "phase_conservation",
    "extractor_conservation",
    "accepted_conservation",
    "valid_tokens",
    "mappoint_pointer_consistency",
    "per_token_conservation",
    "mappoint_pointer_key_consistency",
    "atlas_snapshot_available",
)

INSTRUMENTATION_DERIVED_FIELDS = (
    "instrumentation_overflowed",
    "instrumentation_conservation_ok",
)

INSTRUMENTATION_SUMMARY_FIELDS = (
    "schema_version",
    "complete",
    *INSTRUMENTATION_COUNT_FIELDS,
    *INSTRUMENTATION_NULLABLE_NUMBER_FIELDS,
    *INSTRUMENTATION_BOOLEAN_FIELDS,
    *INSTRUMENTATION_DERIVED_FIELDS,
)

INSTRUMENTATION_JSON_FIELDS = (
    "schema_version",
    "complete",
    *INSTRUMENTATION_COUNT_FIELDS,
    *INSTRUMENTATION_NULLABLE_NUMBER_FIELDS,
    *INSTRUMENTATION_BOOLEAN_FIELDS,
    "status",
    "output_directory",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runs-root", required=True)
    parser.add_argument("--gt-tum", required=True)
    parser.add_argument("--image-times", required=True)
    parser.add_argument("--max-time-diff", type=float, required=True)
    parser.add_argument("--rpe-delta-frames", type=int, required=True)
    parser.add_argument("--output-csv", required=True)
    parser.add_argument(
        "--trajectory-kind",
        choices=("reconstructed", "online"),
        default="reconstructed",
        help="Evaluate the final-map reconstructed trajectory or the saved online poses.",
    )
    parser.add_argument(
        "--require-instrumentation",
        action="store_true",
        help="Reject runs without a complete instrumentation/seed_summary.json.",
    )
    return parser.parse_args()


def convert_euroc_ns_to_tum(source: Path, target: Path) -> list[float]:
    timestamps: list[float] = []
    with source.open(encoding="ascii") as src, target.open("w", encoding="ascii") as dst:
        for line in src:
            fields = line.split()
            if len(fields) != 8:
                continue
            timestamp = float(fields[0]) * 1e-9
            timestamps.append(timestamp)
            dst.write(f"{timestamp:.9f} " + " ".join(fields[1:]) + "\n")
    return timestamps


def run_evo(command: list[str], output: Path) -> None:
    result = subprocess.run(command, check=True, text=True, capture_output=True)
    output.write_text(result.stdout, encoding="utf-8")


def metric_stats(path: Path) -> dict[str, float]:
    text = path.read_text(encoding="utf-8", errors="ignore")
    stats: dict[str, float] = {}
    for key in ("rmse", "median", "max"):
        match = re.search(rf"^\s*{key}\s+([0-9.eE+-]+)\s*$", text, re.MULTILINE)
        if not match:
            raise RuntimeError(f"missing {key} in {path}")
        stats[key] = float(match.group(1))
    return stats


def seed_stats(log_text: str) -> tuple[int, int, int]:
    match = re.search(r"External seed summary: frames=(\d+) attempted=(\d+) accepted=(\d+)", log_text)
    if not match:
        raise RuntimeError("missing external seed summary in ORB log")
    return tuple(int(value) for value in match.groups())


def optional_log_value(log_text: str, pattern: str) -> str:
    match = re.search(pattern, log_text, re.MULTILINE)
    return match.group(1) if match else ""


def instrumentation_summary(
    run_dir: Path, require_instrumentation: bool = False
) -> dict[str, object]:
    """Load optional seed instrumentation without fabricating legacy zeros."""
    instrumentation_dir = run_dir / "instrumentation"
    summary_path = instrumentation_dir / "seed_summary.json"
    if not summary_path.is_file():
        if require_instrumentation:
            raise SystemExit(f"missing required seed instrumentation: {summary_path}")
        result = {field: "" for field in INSTRUMENTATION_SUMMARY_FIELDS}
        if instrumentation_dir.exists():
            result["complete"] = 0
        return result

    try:
        data = json.loads(summary_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid seed instrumentation JSON: {summary_path}") from exc
    if not isinstance(data, dict):
        raise ValueError(f"seed instrumentation must be a JSON object: {summary_path}")

    missing = [field for field in INSTRUMENTATION_JSON_FIELDS if field not in data]
    if missing:
        raise ValueError(
            f"seed instrumentation missing fields {missing}: {summary_path}"
        )
    if type(data["schema_version"]) is not int or data["schema_version"] != 1:
        raise ValueError(
            f"seed instrumentation schema_version must be integer 1: {summary_path}"
        )
    if not isinstance(data["complete"], bool):
        raise ValueError(
            f"seed instrumentation complete must be boolean: {summary_path}"
        )

    for field in INSTRUMENTATION_COUNT_FIELDS:
        value = data[field]
        if type(value) is not int or value < 0:
            raise ValueError(
                f"seed instrumentation {field} must be a non-negative integer: "
                f"{summary_path}"
            )
    for field in INSTRUMENTATION_NULLABLE_NUMBER_FIELDS:
        value = data[field]
        if value is None:
            continue
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(value)
            or value < 0
        ):
            raise ValueError(
                f"seed instrumentation {field} must be null or a finite "
                f"non-negative number: {summary_path}"
            )
    for field in INSTRUMENTATION_BOOLEAN_FIELDS:
        if not isinstance(data[field], bool):
            raise ValueError(
                f"seed instrumentation {field} must be boolean: {summary_path}"
            )

    output_directory = data["output_directory"]
    expected_directory = (run_dir / "instrumentation").resolve()
    if not isinstance(output_directory, str) or not output_directory:
        raise ValueError(
            f"seed instrumentation output_directory must be a non-empty string: "
            f"{summary_path}"
        )
    if Path(output_directory).resolve() != expected_directory:
        raise ValueError(
            "seed instrumentation output_directory mismatch: "
            f"json={Path(output_directory).resolve()} expected={expected_directory}"
        )
    expected_status = "ok" if data["complete"] else "invalid"
    if data["status"] != expected_status:
        raise ValueError(
            f"seed instrumentation status must be {expected_status!r}: {summary_path}"
        )

    duplicate_pairs = (
        ("loaded_seed_observations", "loaded_seed_rows"),
        ("attempted_seed_observations", "phase_attempted"),
        ("accepted_seed_observations", "extractor_accepted"),
        ("seed_lineages_loaded", "lineages"),
        ("distinct_mappoints", "related_mappoints"),
    )
    for summary_field, diagnostic_field in duplicate_pairs:
        if data[summary_field] != data[diagnostic_field]:
            raise ValueError(
                "seed instrumentation duplicate counters disagree: "
                f"{summary_field}={data[summary_field]} "
                f"{diagnostic_field}={data[diagnostic_field]} in {summary_path}"
            )

    computed_conservation = {
        "phase_conservation": data["loaded_seed_rows"]
        == data["phase_attempted"] + data["phase_skipped"],
        "extractor_conservation": data["phase_attempted"]
        == data["extractor_accepted"]
        + data["extractor_rejected_border"]
        + data["extractor_rejected_native_duplicate"]
        + data["extractor_rejected_seed_duplicate"],
        "accepted_conservation": data["extractor_accepted"]
        == data["frame_accepted"],
    }
    for field, computed in computed_conservation.items():
        if data[field] is not computed:
            raise ValueError(
                f"seed instrumentation {field} disagrees with its counters: "
                f"{summary_path}"
            )
    if data["events_recorded"] > data["event_capacity"]:
        raise ValueError(
            f"seed instrumentation events_recorded exceeds capacity: {summary_path}"
        )
    if data["related_mappoints"] > data["related_mappoint_capacity"]:
        raise ValueError(
            f"seed instrumentation related_mappoints exceeds capacity: {summary_path}"
        )

    overflowed = bool(
        data["events_overflowed"] or data["related_mappoint_overflowed"]
    )
    conservation_ok = all(computed_conservation.values())
    known_integrity_ok = (
        not overflowed
        and conservation_ok
        and data["valid_tokens"]
        and data["mappoint_pointer_consistency"]
    )
    if data["complete"] and not known_integrity_ok:
        raise ValueError(
            f"complete seed instrumentation has failed integrity diagnostics: "
            f"{summary_path}"
        )

    result = {
        field: "" if data[field] is None else data[field]
        for field in INSTRUMENTATION_SUMMARY_FIELDS
        if field not in INSTRUMENTATION_DERIVED_FIELDS
    }
    result["complete"] = int(data["complete"])
    for field in INSTRUMENTATION_BOOLEAN_FIELDS:
        result[field] = int(data[field])
    result["instrumentation_overflowed"] = int(overflowed)
    result["instrumentation_conservation_ok"] = int(conservation_ok)
    if require_instrumentation and not data["complete"]:
        raise SystemExit(f"incomplete required seed instrumentation: {summary_path}")
    return result


def validate_run_instrumentation(
    summary: dict[str, object], role: str, attempted: int, accepted: int, run_dir: Path
) -> None:
    """Cross-check instrumentation against the executable log and triplet role."""
    if summary["schema_version"] == "":
        return
    if summary["attempted_seed_observations"] != attempted:
        raise ValueError(
            "instrumentation/log attempted count mismatch: "
            f"json={summary['attempted_seed_observations']} log={attempted} in {run_dir}"
        )
    if summary["accepted_seed_observations"] != accepted:
        raise ValueError(
            "instrumentation/log accepted count mismatch: "
            f"json={summary['accepted_seed_observations']} log={accepted} in {run_dir}"
        )
    if role in ("orb_only", "drop") and summary["loaded_seed_observations"] != 0:
        raise ValueError(
            f"{role} instrumentation loaded_seed_observations must be zero: "
            f"{summary['loaded_seed_observations']} in {run_dir}"
        )


def instrumentation_aware_status(
    normal_status: str, summary: dict[str, object]
) -> str:
    if summary["complete"] == 0:
        return "instrumentation_incomplete"
    return normal_status


def phase_gate_stats(log_text: str) -> dict[str, object]:
    """Extract phase-gate statistics without treating absent legacy logs as zero."""
    phase_summary = re.search(
        r"External seed phase summary: phase=(\w+)"
        r" pre_attempted=(\d+) pre_accepted=(\d+)"
        r" post_attempted=(\d+) post_accepted=(\d+) phase_skipped=(\d+)",
        log_text,
        re.MULTILINE,
    )
    result: dict[str, object] = {
        "seed_phase": optional_log_value(log_text, r"^External seed phase: (\w+)\s*$"),
        "seed_min_consecutive_ok_frames": optional_log_value(
            log_text, r"^External seed minimum consecutive OK frames: (\d+)\s*$"
        ),
        "seed_phase_summary_logged": int(phase_summary is not None),
        "pre_init_attempted_seeds": "",
        "pre_init_accepted_seeds": "",
        "post_init_attempted_seeds": "",
        "post_init_accepted_seeds": "",
        "phase_skipped_seeds": "",
        # The current ORB executable only emits aggregate counts.  Keep these
        # blank rather than fabricating frame-level timing from the seed file.
        "first_injection_frame": "",
        "last_injection_frame": "",
        "max_consecutive_ok_frames": "",
        "seed_event_frames_logged": 0,
    }
    if phase_summary:
        (
            summary_phase,
            pre_attempted,
            pre_accepted,
            post_attempted,
            post_accepted,
            skipped,
        ) = phase_summary.groups()
        if result["seed_phase"] and result["seed_phase"] != summary_phase:
            raise RuntimeError("conflicting external seed phase entries in ORB log")
        result.update(
            {
                "seed_phase": summary_phase,
                "pre_init_attempted_seeds": pre_attempted,
                "pre_init_accepted_seeds": pre_accepted,
                "post_init_attempted_seeds": post_attempted,
                "post_init_accepted_seeds": post_accepted,
                "phase_skipped_seeds": skipped,
            }
        )
    return result


def role_and_repeat(path: Path) -> tuple[str, int]:
    match = re.fullmatch(
        r"(orb_only|drop|full_bridge_off|full_lineage_no_grace|full_unbounded|full)_r(\d+)",
        path.name,
    )
    if not match:
        raise ValueError(path.name)
    return match.group(1), int(match.group(2))


def main() -> int:
    args = parse_args()
    runs_root = Path(args.runs_root).resolve()
    gt_tum = Path(args.gt_tum).resolve()
    image_times = [int(line) * 1e-9 for line in Path(args.image_times).read_text().splitlines() if line.strip()]
    if not image_times:
        raise SystemExit("empty image time list")

    run_dirs = []
    for path in runs_root.iterdir():
        try:
            role, repeat = role_and_repeat(path)
        except ValueError:
            continue
        run_dirs.append(
            (
                repeat,
                (
                    "orb_only",
                    "drop",
                    "full_bridge_off",
                    "full_lineage_no_grace",
                    "full_unbounded",
                    "full",
                ).index(role),
                role,
                path,
            )
        )
    run_dirs.sort()
    if not run_dirs:
        raise SystemExit(f"no triplet run directories under {runs_root}")

    rows: list[dict[str, object]] = []
    for repeat, _, role, run_dir in run_dirs:
        log_text = (run_dir / "orbslam3_run.log").read_text(encoding="utf-8", errors="ignore")
        seeded_frames, attempted, accepted = seed_stats(log_text)
        seed_instrumentation = instrumentation_summary(
            run_dir, args.require_instrumentation
        )
        validate_run_instrumentation(
            seed_instrumentation, role, attempted, accepted, run_dir
        )
        common_row: dict[str, object] = {
            "role": role,
            "repeat": repeat,
            "trajectory_kind": args.trajectory_kind,
            "input_frames": len(image_times),
            "map_resets": log_text.count("SYSTEM-> Reseting active map")
            + log_text.count("SYSTEM-> Resetting active map"),
            "relocalizations": log_text.count("Relocalized!!"),
            "seeded_frames": seeded_frames,
            "attempted_seeds": attempted,
            "accepted_seeds": accepted,
            **phase_gate_stats(log_text),
            **seed_instrumentation,
        }
        trajectory_glob = (
            "online_f_*.txt" if args.trajectory_kind == "online" else "f_*.txt"
        )
        trajectories = [
            path
            for path in run_dir.glob(trajectory_glob)
            if not path.name.endswith("_sec.txt")
        ]
        if len(trajectories) > 1:
            raise SystemExit(
                f"expected at most one {args.trajectory_kind} trajectory in "
                f"{run_dir}, found {len(trajectories)}"
            )
        if not trajectories:
            rows.append(
                {
                    **common_row,
                    "output_poses": 0,
                    "coverage_ratio": 0.0,
                    "first_output_delay_s": "",
                    "continuous_span_s": 0.0,
                    "terminal_drop_s": image_times[-1] - image_times[0],
                    "ape_rmse_m": "",
                    "ape_median_m": "",
                    "ape_max_m": "",
                    "rpe_rmse_m": "",
                    "rpe_median_m": "",
                    "rpe_max_m": "",
                    "status": instrumentation_aware_status(
                        "empty_trajectory", seed_instrumentation
                    ),
                    "run_dir": str(run_dir),
                }
            )
            continue
        trajectory = trajectories[0]
        trajectory_sec = trajectory.with_name(trajectory.stem + "_sec.txt")
        timestamps = convert_euroc_ns_to_tum(trajectory, trajectory_sec)
        if not timestamps:
            rows.append(
                {
                    **common_row,
                    "output_poses": 0,
                    "coverage_ratio": 0.0,
                    "first_output_delay_s": "",
                    "continuous_span_s": 0.0,
                    "terminal_drop_s": image_times[-1] - image_times[0],
                    "ape_rmse_m": "",
                    "ape_median_m": "",
                    "ape_max_m": "",
                    "rpe_rmse_m": "",
                    "rpe_median_m": "",
                    "rpe_max_m": "",
                    "status": instrumentation_aware_status(
                        "empty_trajectory", seed_instrumentation
                    ),
                    "run_dir": str(run_dir),
                }
            )
            continue

        report_prefix = "online_" if args.trajectory_kind == "online" else ""
        ape_report = run_dir / f"{report_prefix}ape_trans.txt"
        rpe_report = run_dir / (
            f"{report_prefix}rpe_trans_{args.rpe_delta_frames}f.txt"
        )
        common = [
            "tum",
            str(gt_tum),
            str(trajectory_sec),
            "-r",
            "trans_part",
            "-a",
            "-s",
            "--t_max_diff",
            str(args.max_time_diff),
            "--no_warnings",
        ]
        run_evo(["evo_ape", *common], ape_report)
        run_evo(
            [
                "evo_rpe",
                *common,
                "-d",
                str(args.rpe_delta_frames),
                "-u",
                "f",
                "--all_pairs",
            ],
            rpe_report,
        )

        ape = metric_stats(ape_report)
        rpe = metric_stats(rpe_report)
        rows.append(
            {
                **common_row,
                "output_poses": len(timestamps),
                "coverage_ratio": len(timestamps) / len(image_times),
                "first_output_delay_s": timestamps[0] - image_times[0],
                "continuous_span_s": timestamps[-1] - timestamps[0],
                "terminal_drop_s": image_times[-1] - timestamps[-1],
                "ape_rmse_m": ape["rmse"],
                "ape_median_m": ape["median"],
                "ape_max_m": ape["max"],
                "rpe_rmse_m": rpe["rmse"],
                "rpe_median_m": rpe["median"],
                "rpe_max_m": rpe["max"],
                "status": instrumentation_aware_status("ok", seed_instrumentation),
                "run_dir": str(run_dir),
            }
        )

    output = Path(args.output_csv).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    print(f"wrote {len(rows)} runs to {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
