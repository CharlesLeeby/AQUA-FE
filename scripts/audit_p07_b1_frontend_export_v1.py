#!/usr/bin/env python3
"""Audit one frozen P07 B1 export without reading trajectory outcomes."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import re
from collections import Counter
from pathlib import Path

import rosbag

try:
    from scripts import build_p07_preoutcome_governance_v1 as governance
except ModuleNotFoundError:  # Direct ``python3 scripts/...`` execution.
    import build_p07_preoutcome_governance_v1 as governance  # type: ignore


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
FORBIDDEN_OUTCOME_NAMES = {
    "ape.txt",
    "rpe.txt",
    "vio.csv",
    "vins.log",
    "replay_manifest.txt",
    "common_support_summary.json",
    "common_support_metrics.csv",
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def queue_row(index: int) -> dict[str, str]:
    rows = governance.read_csv(governance.EXPORT_QUEUE)
    matches = [row for row in rows if int(row["queue_index"]) == index]
    if len(matches) != 1:
        raise ValueError(f"expected one queue row for index {index}")
    row = matches[0]
    if row["arm"] != governance.B1:
        raise ValueError(f"B1 auditor cannot audit arm {row['arm']}")
    if hashlib.sha256(row["command"].encode("utf-8")).hexdigest() != row["command_sha256"]:
        raise ValueError("queue command hash mismatch")
    return row


def allocation_row(index: int) -> dict[str, str]:
    rows = governance.read_csv(governance.ALLOCATION_CSV)
    matches = [row for row in rows if int(row["queue_index"]) == index]
    if len(matches) != 1:
        raise ValueError(f"expected one allocation row for index {index}")
    return matches[0]


def manifest_row(window_id: str) -> dict[str, str]:
    matches = [
        row
        for row in governance.read_csv(governance.MANIFEST)
        if row["window_id"] == window_id
    ]
    if len(matches) != 1:
        raise ValueError(f"expected one manifest row for {window_id}")
    return matches[0]


def parse_guard_path(command_log: Path) -> Path:
    text = command_log.read_text(encoding="utf-8", errors="replace")
    matches = re.findall(r"\bdecision=([^\s]+_decision\.json)", text)
    unique = list(dict.fromkeys(matches))
    if len(unique) != 1:
        raise ValueError(f"expected one guard decision in command log, found {unique}")
    path = Path(unique[0])
    if not path.is_absolute():
        path = governance.ROOT / path
    return path.resolve()


def channels(message) -> dict[str, list[float]]:
    names = [channel.name for channel in message.channels]
    if len(names) != len(set(names)):
        raise ValueError("duplicate feature channel")
    return {channel.name: list(channel.values) for channel in message.channels}


def audit_feature_bag(path: Path, *, expected_frames: int) -> dict[str, object]:
    if not path.is_file() or path.stat().st_size == 0:
        raise ValueError(f"missing/empty feature bag: {path}")
    topic_counts: Counter[str] = Counter()
    source_counts: Counter[int] = Counter()
    feature_counts: list[int] = []
    feature_stamps: list[float] = []
    q_min = float("inf")
    q_max = float("-inf")
    sigma_min = float("inf")
    sigma_max = float("-inf")
    observations = 0
    with rosbag.Bag(str(path), "r") as bag:
        for topic, message, _record_stamp in bag.read_messages():
            topic_counts[topic] += 1
            if topic != FEATURE_TOPIC:
                continue
            count = len(message.points)
            if count <= 0 or count > 350:
                raise ValueError(f"invalid B1 feature count: {count}")
            feature_counts.append(count)
            feature_stamps.append(float(message.header.stamp.to_sec()))
            values = channels(message)
            if set(values) != REQUIRED_CHANNELS:
                raise ValueError(
                    f"B1 feature channel set mismatch: {sorted(set(values) ^ REQUIRED_CHANNELS)}"
                )
            if any(len(values[name]) != count for name in REQUIRED_CHANNELS):
                raise ValueError("B1 feature channel length mismatch")
            raw_ids = values["id"]
            ids = [int(round(value)) for value in raw_ids]
            if any(abs(float(raw) - ident) > 1e-4 for raw, ident in zip(raw_ids, ids)):
                raise ValueError("B1 contains non-integer feature ID")
            if len(ids) != len(set(ids)):
                raise ValueError("B1 contains duplicate feature ID within a frame")
            if any(int(round(value)) != 0 for value in values["camera_id"]):
                raise ValueError("B1 requires camera_id=0")
            if any(int(round(value)) != 0 for value in values["is_learned"]):
                raise ValueError("B1 contains learned-marked observations")
            for raw_source, raw_q, raw_sigma in zip(
                values["source_code"], values["quality"], values["sigma"]
            ):
                source = int(round(raw_source))
                q = float(raw_q)
                sigma = float(raw_sigma)
                if source not in {1, 2}:
                    raise ValueError(f"B1 contains non-classical source code {source}")
                if not math.isfinite(q) or q < 0.8 - 1e-6 or q > 1.0 + 1e-6:
                    raise ValueError(f"B1 quality outside [0.8,1]: {q}")
                if not math.isfinite(sigma) or not math.isclose(
                    sigma, 1.0 / math.sqrt(q), rel_tol=0.0, abs_tol=2e-6
                ):
                    raise ValueError("B1 sigma is inconsistent with native q")
                source_counts[source] += 1
                observations += 1
                q_min = min(q_min, q)
                q_max = max(q_max, q)
                sigma_min = min(sigma_min, sigma)
                sigma_max = max(sigma_max, sigma)
    if len(feature_counts) != expected_frames:
        raise ValueError(
            f"B1 feature frame count mismatch: {len(feature_counts)} != {expected_frames}"
        )
    if any(right <= left for left, right in zip(feature_stamps, feature_stamps[1:])):
        raise ValueError("B1 feature timestamps are not strictly increasing")
    if topic_counts["/rtimulib_node/imu"] <= 0:
        raise ValueError("B1 feature bag has no copied AQUALOC IMU")
    if topic_counts["/aqualoc/colmap_gt"] <= 0:
        raise ValueError("B1 feature bag has no copied AQUALOC reference")
    return {
        "path": path.relative_to(governance.ROOT).as_posix(),
        "sha256": sha256(path),
        "size_bytes": path.stat().st_size,
        "topic_counts": dict(sorted(topic_counts.items())),
        "feature_frames": len(feature_counts),
        "feature_observations": observations,
        "min_features_per_frame": min(feature_counts),
        "max_features_per_frame": max(feature_counts),
        "source_counts": {str(key): value for key, value in sorted(source_counts.items())},
        "quality_min": q_min,
        "quality_max": q_max,
        "sigma_min": sigma_min,
        "sigma_max": sigma_max,
        "feature_start_stamp": feature_stamps[0],
        "feature_end_stamp": feature_stamps[-1],
    }


def audit_metrics(path: Path, feature_bag_stats: dict[str, object]) -> dict[str, object]:
    with path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    expected = int(feature_bag_stats["feature_frames"])
    if len(rows) != expected:
        raise ValueError(f"metrics row count mismatch: {len(rows)} != {expected}")
    counts = [int(float(row["exported_features"])) for row in rows]
    if sum(counts) != int(feature_bag_stats["feature_observations"]):
        raise ValueError("metrics exported feature total does not match bag")
    learned_columns = [
        "exported_learned_features",
        "exported_non_loftr_learned_features",
        "exported_sp_lg_features",
        "exported_xfeat_features",
        "exported_loftr_features",
    ]
    for name in learned_columns:
        if name in rows[0] and any(int(float(row.get(name) or 0)) != 0 for row in rows):
            raise ValueError(f"B1 metrics report learned export in {name}")
    return {
        "path": path.relative_to(governance.ROOT).as_posix(),
        "sha256": sha256(path),
        "size_bytes": path.stat().st_size,
        "rows": len(rows),
        "exported_feature_observations": sum(counts),
    }


def audit_raw_bag(path: Path, *, expected_images: int) -> dict[str, object]:
    if not path.is_file() or path.stat().st_size == 0:
        raise ValueError(f"missing/empty derived raw bag: {path}")
    with rosbag.Bag(str(path), "r") as bag:
        info = bag.get_type_and_topic_info().topics
        counts = {topic: int(value.message_count) for topic, value in info.items()}
    if counts.get("/camera/image_raw") != expected_images:
        raise ValueError(
            f"raw image count mismatch: {counts.get('/camera/image_raw')} != {expected_images}"
        )
    if counts.get("/rtimulib_node/imu", 0) <= 0 or counts.get("/aqualoc/colmap_gt", 0) <= 0:
        raise ValueError("derived raw bag lacks IMU/reference messages")
    return {
        "path": path.relative_to(governance.ROOT).as_posix(),
        "sha256": sha256(path),
        "size_bytes": path.stat().st_size,
        "topic_counts": dict(sorted(counts.items())),
    }


def forbidden_outcomes(run_dir: Path) -> list[str]:
    return sorted(
        path.relative_to(governance.ROOT).as_posix()
        for path in run_dir.rglob("*")
        if path.is_file() and path.name.lower() in FORBIDDEN_OUTCOME_NAMES
    )


def build_audit(*, index: int, command_log: Path, attestation: Path) -> dict[str, object]:
    queue = queue_row(index)
    allocation = allocation_row(index)
    manifest = manifest_row(queue["window_id"])
    if queue["dataset_family"] != "aqualoc_archaeology":
        raise ValueError("B1 audit v1 smoke currently supports AQUALOC archaeology only")
    feature_bag = governance.ROOT / queue["expected_feature_bag"]
    run_dir = feature_bag.parent
    metrics = run_dir / "frontend_metrics.csv"
    sequence_number = int(queue["sequence"][1:])
    start = allocation["window_start"]
    end = allocation["window_end"]
    raw_bag = governance.ROOT / f"datasets/aqualoc/rosbags/archaeo{sequence_number:02d}_{start}_{end}.bag"
    expected_images = int(end) - int(start) + 1
    expected_feature_frames = int(manifest["input_frame_count"]) // 2

    guard_path = parse_guard_path(command_log)
    guard = json.loads(guard_path.read_text(encoding="utf-8"))
    if (
        guard.get("schema_version") != "aqua-fe-b1-klt-nativeq-guard-decision-v1"
        or guard.get("action") != "ALLOW_B1_KLT_NATIVEQ"
        or guard.get("contract_pass") is not True
        or guard.get("reasons") != []
        or guard.get("contract_hash")
        != "39eaea6d26e6f5a881ef2b17b898cbda75c7aba8087ce447fe897e2fe0bdfce0"
    ):
        raise ValueError("B1 guard decision is not an exact frozen PASS")

    raw = audit_raw_bag(raw_bag, expected_images=expected_images)
    feature = audit_feature_bag(feature_bag, expected_frames=expected_feature_frames)
    metrics_audit = audit_metrics(metrics, feature)
    if not attestation.is_file():
        raise ValueError(f"missing B1 native-q attestation: {attestation}")
    attested = json.loads(attestation.read_text(encoding="utf-8"))
    if (
        attested.get("contract_pass") is not True
        or attested.get("feature_bag_sha256") != feature["sha256"]
        or int(attested.get("learned_observations", -1)) != 0
    ):
        raise ValueError("B1 native-q attestation mismatch")
    forbidden = forbidden_outcomes(run_dir)
    if forbidden:
        raise ValueError(f"trajectory outcome artifact found in export-only run: {forbidden}")

    return {
        "schema_version": "isj-p07-b1-frontend-export-audit-v1",
        "status": "PASS",
        "queue_index": index,
        "run_id": allocation["run_id"],
        "window_id": queue["window_id"],
        "arm": queue["arm"],
        "command_sha256": queue["command_sha256"],
        "checks": {
            "queue_and_allocation_exact": True,
            "guard_exact_pass": True,
            "derived_raw_bag_readable": True,
            "feature_schema_and_native_q_pass": True,
            "metrics_match_bag": True,
            "classical_only_zero_learned": True,
            "sensor_and_reference_topics_copied": True,
            "nativeq_attestation_bound": True,
            "no_trajectory_outcome_artifacts": True,
        },
        "guard": {
            "path": guard_path.relative_to(governance.ROOT).as_posix(),
            "sha256": sha256(guard_path),
            "action": guard["action"],
            "contract_hash": guard["contract_hash"],
        },
        "raw_bag": raw,
        "feature_bag": feature,
        "frontend_metrics": metrics_audit,
        "attestation": {
            "path": attestation.relative_to(governance.ROOT).as_posix(),
            "sha256": sha256(attestation),
            "schema_version": attested["schema_version"],
        },
        "forbidden_outcome_artifacts": [],
        "outcome_boundary": "FRONTEND_EXPORT_ONLY_NO_VINS_APE_RPE_TRAJECTORY",
        "held_out_frontend_outcome_read": True,
        "held_out_trajectory_outcome_read": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--queue-index", type=int, required=True)
    parser.add_argument("--command-log", type=Path, required=True)
    parser.add_argument("--attestation", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError(args.output)
    payload = build_audit(
        index=args.queue_index,
        command_log=args.command_log,
        attestation=args.attestation,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=True) + "\n",
        encoding="utf-8",
    )
    print(
        f"P07_B1_FRONTEND_EXPORT_AUDIT_PASS queue_index={args.queue_index} "
        f"frames={payload['feature_bag']['feature_frames']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
