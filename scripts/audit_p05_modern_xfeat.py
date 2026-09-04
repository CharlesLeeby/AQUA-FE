#!/usr/bin/env python3
"""Audit P05 XFeat export-only probes against the frozen fairness contract."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from collections import Counter
from pathlib import Path
from statistics import median

import rosbag


FEATURE_TOPIC = "/feature_tracker/feature"
REQUIRED_CHANNELS = {
    "id",
    "camera_id",
    "p_u",
    "p_v",
    "velocity_x",
    "velocity_y",
    "gx",
    "gy",
    "gz",
    "quality",
    "sigma",
    "source_code",
    "is_learned",
}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--probe",
        action="append",
        required=True,
        metavar="LABEL=RUN_DIR",
        help="Development export-only run to audit; repeat for multiple probes.",
    )
    parser.add_argument(
        "--determinism-pair",
        action="append",
        default=[],
        metavar="LABEL_A=LABEL_B",
    )
    parser.add_argument("--feature-topic", default=FEATURE_TOPIC)
    parser.add_argument("--max-features", type=int, default=350)
    parser.add_argument("--expected-source-code", type=int, default=20)
    parser.add_argument("--q-floor", type=float, default=0.80)
    parser.add_argument("--output-csv", required=True)
    parser.add_argument("--output-json", required=True)
    args = parser.parse_args()

    probes = dict(parse_assignment(value, "probe") for value in args.probe)
    rows = [
        audit_probe(
            label,
            run_dir,
            feature_topic=args.feature_topic,
            max_features=args.max_features,
            expected_source_code=args.expected_source_code,
            q_floor=args.q_floor,
        )
        for label, run_dir in probes.items()
    ]
    row_by_label = {row["label"]: row for row in rows}

    determinism = []
    for value in args.determinism_pair:
        left, right = parse_assignment(value, "determinism pair")
        if left not in probes or right not in probes:
            raise ValueError(f"unknown determinism label: {left}={right}")
        result = audit_determinism(left, probes[left], right, probes[right])
        determinism.append(result)
        if not result["pass"]:
            row_by_label[left]["status"] = "FAIL"
            row_by_label[right]["status"] = "FAIL"
            row_by_label[left]["issues"].append("determinism_pair_failed")
            row_by_label[right]["issues"].append("determinism_pair_failed")

    output_csv = Path(args.output_csv)
    output_csv.parent.mkdir(parents=True, exist_ok=True)
    write_csv(output_csv, rows)

    overall_pass = all(row["status"] == "PASS" for row in rows) and all(
        item["pass"] for item in determinism
    )
    payload = {
        "schema_version": "isj-p05-xfeat-fairness-audit-v1",
        "status": "PASS" if overall_pass else "FAIL",
        "contract": {
            "feature_topic": args.feature_topic,
            "max_features": args.max_features,
            "expected_source_code": args.expected_source_code,
            "q_floor": args.q_floor,
            "scientific_role": "controlled_same_backend_modern_baseline",
            "backend_quality": "native_vins_safe",
        },
        "probes": rows,
        "determinism": determinism,
    }
    output_json = Path(args.output_json)
    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(
        f"P05_XFEAT_AUDIT_{payload['status']} probes={len(rows)} "
        f"determinism_pairs={len(determinism)}"
    )
    print(f"wrote {output_csv}")
    print(f"wrote {output_json}")
    return 0 if overall_pass else 1


def parse_assignment(value: str, kind: str) -> tuple[str, Path | str]:
    if "=" not in value:
        raise ValueError(f"{kind} must use NAME=VALUE: {value}")
    left, right = value.split("=", 1)
    if not left or not right:
        raise ValueError(f"invalid {kind}: {value}")
    if kind == "probe":
        return left, Path(right).resolve()
    return left, right


def audit_probe(
    label: str,
    run_dir: Path,
    *,
    feature_topic: str,
    max_features: int,
    expected_source_code: int,
    q_floor: float,
) -> dict[str, object]:
    bag_path = run_dir / "features.bag"
    metrics_path = run_dir / "frontend_metrics.csv"
    issues: list[str] = []
    if not bag_path.is_file():
        issues.append("missing_features_bag")
    if not metrics_path.is_file():
        issues.append("missing_frontend_metrics")
    if issues:
        return empty_row(label, run_dir, bag_path, metrics_path, issues)

    topic_counts: Counter[str] = Counter()
    source_codes: Counter[int] = Counter()
    counts: list[int] = []
    stamps: list[float] = []
    quality_values: list[float] = []
    sigma_values: list[float] = []
    observation_count = 0
    duplicate_id_frames = 0
    invalid_channel_frames = 0
    non_integer_id_frames = 0
    nonfinite_geometry_values = 0
    invalid_camera_id_frames = 0
    invalid_learned_flag_frames = 0
    nonfinite_channel_geometry_frames = 0

    with rosbag.Bag(str(bag_path), "r") as bag:
        for topic, msg, _record_stamp in bag.read_messages():
            topic_counts[topic] += 1
            if topic != feature_topic:
                continue
            count = len(msg.points)
            counts.append(count)
            observation_count += count
            stamps.append(float(msg.header.stamp.to_sec()))
            channels = {channel.name: list(channel.values) for channel in msg.channels}
            if not REQUIRED_CHANNELS.issubset(channels):
                invalid_channel_frames += 1
                continue
            if any(len(values) != count for values in channels.values()):
                invalid_channel_frames += 1
                continue

            raw_ids = channels["id"]
            ids = [int(round(value)) for value in raw_ids]
            if any(abs(float(raw) - ident) > 1e-4 for raw, ident in zip(raw_ids, ids)):
                non_integer_id_frames += 1
            if len(ids) != len(set(ids)):
                duplicate_id_frames += 1

            source_codes.update(int(round(value)) for value in channels["source_code"])
            quality_values.extend(float(value) for value in channels["quality"])
            sigma_values.extend(float(value) for value in channels["sigma"])
            if any(int(round(value)) != 0 for value in channels["camera_id"]):
                invalid_camera_id_frames += 1
            if any(int(round(value)) != 1 for value in channels["is_learned"]):
                invalid_learned_flag_frames += 1
            coordinate_channels = (
                "p_u",
                "p_v",
                "velocity_x",
                "velocity_y",
                "gx",
                "gy",
                "gz",
            )
            if any(
                not math.isfinite(float(value))
                for name in coordinate_channels
                for value in channels[name]
            ):
                nonfinite_channel_geometry_frames += 1
            for point in msg.points:
                if not all(math.isfinite(float(value)) for value in (point.x, point.y, point.z)):
                    nonfinite_geometry_values += 1

    metrics_rows = list(csv.DictReader(metrics_path.open(newline="", encoding="utf-8")))
    metrics_counts = [int(float(row["exported_features"])) for row in metrics_rows]
    metrics_sources = Counter(row.get("export_source_histogram", "") for row in metrics_rows)

    feature_frames = len(counts)
    copied_messages = sum(topic_counts.values()) - feature_frames
    if feature_frames == 0:
        issues.append("no_feature_frames")
    if copied_messages == 0:
        issues.append("no_copied_sensor_messages")
    zero_feature_frames = sum(count == 0 for count in counts)
    noninitial_zero_frames = sum(count == 0 for count in counts[1:])
    if counts and max(counts) > max_features:
        issues.append("feature_budget_violation")
    if noninitial_zero_frames:
        issues.append("noninitial_zero_feature_frame")
    if not strictly_increasing(stamps):
        issues.append("non_monotonic_feature_timestamps")
    if invalid_channel_frames:
        issues.append("feature_channel_schema_violation")
    if duplicate_id_frames:
        issues.append("duplicate_ids_within_frame")
    if non_integer_id_frames:
        issues.append("non_integer_feature_ids")
    if nonfinite_geometry_values:
        issues.append("nonfinite_geometry")
    if nonfinite_channel_geometry_frames:
        issues.append("nonfinite_coordinate_channels")
    if invalid_camera_id_frames:
        issues.append("unexpected_camera_id")
    if invalid_learned_flag_frames:
        issues.append("unexpected_is_learned_flag")
    if set(source_codes) != {expected_source_code}:
        issues.append("unexpected_source_code")
    if not quality_values or min(quality_values) + 1e-6 < q_floor or max(quality_values) > 1.0 + 1e-6:
        issues.append("quality_contract_violation")
    if not sigma_values or min(sigma_values) <= 0 or not all(map(math.isfinite, sigma_values)):
        issues.append("sigma_contract_violation")
    if len(metrics_rows) != feature_frames:
        issues.append("metrics_frame_count_mismatch")
    if metrics_counts != counts:
        issues.append("metrics_export_count_mismatch")
    if any(value and not value.startswith("xfeat:") for value in metrics_sources):
        issues.append("metrics_source_histogram_violation")

    return {
        "label": label,
        "status": "PASS" if not issues else "FAIL",
        "run_dir": str(run_dir),
        "bag_path": str(bag_path),
        "metrics_path": str(metrics_path),
        "bag_sha256": sha256_file(bag_path),
        "metrics_sha256": sha256_file(metrics_path),
        "feature_frames": feature_frames,
        "copied_sensor_messages": copied_messages,
        "observation_count": observation_count,
        "zero_feature_frames": zero_feature_frames,
        "noninitial_zero_feature_frames": noninitial_zero_frames,
        "min_features_per_frame": min(counts) if counts else None,
        "median_features_per_frame": median(counts) if counts else None,
        "max_features_per_frame": max(counts) if counts else None,
        "feature_span_s": stamps[-1] - stamps[0] if len(stamps) > 1 else 0.0,
        "source_codes": dict(sorted(source_codes.items())),
        "q_min": min(quality_values) if quality_values else None,
        "q_max": max(quality_values) if quality_values else None,
        "sigma_min": min(sigma_values) if sigma_values else None,
        "sigma_max": max(sigma_values) if sigma_values else None,
        "duplicate_id_frames": duplicate_id_frames,
        "invalid_channel_frames": invalid_channel_frames,
        "invalid_camera_id_frames": invalid_camera_id_frames,
        "invalid_learned_flag_frames": invalid_learned_flag_frames,
        "nonfinite_channel_geometry_frames": nonfinite_channel_geometry_frames,
        "topic_counts": dict(sorted(topic_counts.items())),
        "issues": issues,
    }


def audit_determinism(
    left_label: str,
    left_dir: Path,
    right_label: str,
    right_dir: Path,
) -> dict[str, object]:
    left_bag = left_dir / "features.bag"
    right_bag = right_dir / "features.bag"
    left_metrics = left_dir / "frontend_metrics.csv"
    right_metrics = right_dir / "frontend_metrics.csv"
    bag_equal = left_bag.is_file() and right_bag.is_file() and sha256_file(left_bag) == sha256_file(right_bag)
    metrics_equal = (
        left_metrics.is_file()
        and right_metrics.is_file()
        and sha256_file(left_metrics) == sha256_file(right_metrics)
    )
    return {
        "left": left_label,
        "right": right_label,
        "bag_byte_identical": bag_equal,
        "metrics_byte_identical": metrics_equal,
        "pass": bag_equal and metrics_equal,
    }


def empty_row(
    label: str,
    run_dir: Path,
    bag_path: Path,
    metrics_path: Path,
    issues: list[str],
) -> dict[str, object]:
    return {
        "label": label,
        "status": "FAIL",
        "run_dir": str(run_dir),
        "bag_path": str(bag_path),
        "metrics_path": str(metrics_path),
        "bag_sha256": None,
        "metrics_sha256": None,
        "feature_frames": 0,
        "copied_sensor_messages": 0,
        "observation_count": 0,
        "zero_feature_frames": 0,
        "noninitial_zero_feature_frames": 0,
        "min_features_per_frame": None,
        "median_features_per_frame": None,
        "max_features_per_frame": None,
        "feature_span_s": None,
        "source_codes": {},
        "q_min": None,
        "q_max": None,
        "sigma_min": None,
        "sigma_max": None,
        "duplicate_id_frames": 0,
        "invalid_channel_frames": 0,
        "invalid_camera_id_frames": 0,
        "invalid_learned_flag_frames": 0,
        "nonfinite_channel_geometry_frames": 0,
        "topic_counts": {},
        "issues": issues,
    }


def strictly_increasing(values: list[float]) -> bool:
    return bool(values) and all(right > left for left, right in zip(values, values[1:]))


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    fieldnames = [
        "label",
        "status",
        "run_dir",
        "bag_path",
        "metrics_path",
        "bag_sha256",
        "metrics_sha256",
        "feature_frames",
        "copied_sensor_messages",
        "observation_count",
        "zero_feature_frames",
        "noninitial_zero_feature_frames",
        "min_features_per_frame",
        "median_features_per_frame",
        "max_features_per_frame",
        "feature_span_s",
        "source_codes",
        "q_min",
        "q_max",
        "sigma_min",
        "sigma_max",
        "duplicate_id_frames",
        "invalid_channel_frames",
        "invalid_camera_id_frames",
        "invalid_learned_flag_frames",
        "nonfinite_channel_geometry_frames",
        "topic_counts",
        "issues",
    ]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            out = dict(row)
            for key in ("source_codes", "topic_counts"):
                out[key] = json.dumps(out[key], sort_keys=True, separators=(",", ":"))
            out["issues"] = ";".join(out["issues"])
            writer.writerow(out)


if __name__ == "__main__":
    raise SystemExit(main())
