#!/usr/bin/env python3
"""Bind a P05 XFeat feature bag to its frozen producer/consumer contract."""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
from collections import Counter
from pathlib import Path

import rosbag

try:
    from scripts.build_nativeq_backend_contract import payload_hash, sha256
    from scripts.check_p05_xfeat_backend_contract_v1 import (
        attestation_payload_hash,
        producer_identity,
    )
except ModuleNotFoundError:  # Direct ``python3 scripts/...`` execution.
    from build_nativeq_backend_contract import payload_hash, sha256  # type: ignore
    from check_p05_xfeat_backend_contract_v1 import (  # type: ignore
        attestation_payload_hash,
        producer_identity,
    )


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONTRACT = (
    ROOT
    / "papers/ieee_sensors_journal_experiments/p05/backend_consumer_contract_xfeat_v1.json"
)
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


def _channels(msg) -> dict[str, list[float]]:
    names = [channel.name for channel in msg.channels]
    if len(names) != len(set(names)):
        raise ValueError("duplicate feature channel")
    return {channel.name: list(channel.values) for channel in msg.channels}


def audit_bag(
    bag_path: Path,
    metrics_path: Path,
    *,
    feature_topic: str,
    max_features: int,
    q_floor: float,
    expected_source_code: int,
) -> dict[str, object]:
    if not bag_path.is_file():
        raise FileNotFoundError(bag_path)
    if not metrics_path.is_file():
        raise FileNotFoundError(metrics_path)

    total_messages = 0
    nonfeature_messages = 0
    feature_counts: list[int] = []
    feature_stamps: list[float] = []
    observation_count = 0
    source_counts: Counter[int] = Counter()
    q_min = float("inf")
    q_max = float("-inf")
    sigma_min = float("inf")
    sigma_max = float("-inf")

    with rosbag.Bag(str(bag_path), "r") as bag:
        for topic, msg, _record_stamp in bag.read_messages():
            total_messages += 1
            if topic != feature_topic:
                nonfeature_messages += 1
                continue
            count = len(msg.points)
            if count > max_features:
                raise ValueError(f"feature cap exceeded: {count}>{max_features}")
            feature_counts.append(count)
            stamp = float(msg.header.stamp.to_sec())
            if not math.isfinite(stamp):
                raise ValueError("non-finite feature timestamp")
            feature_stamps.append(stamp)

            values = _channels(msg)
            missing = REQUIRED_CHANNELS.difference(values)
            if missing:
                raise ValueError(f"missing P05 feature channels: {sorted(missing)}")
            if any(len(values[name]) != count for name in REQUIRED_CHANNELS):
                raise ValueError("P05 feature channel length mismatch")

            raw_ids = values["id"]
            ids = [int(round(value)) for value in raw_ids]
            if any(abs(float(raw) - ident) > 1e-4 for raw, ident in zip(raw_ids, ids)):
                raise ValueError("non-integer feature id")
            if len(ids) != len(set(ids)):
                raise ValueError("duplicate feature id within frame")
            if any(int(round(value)) != 0 for value in values["camera_id"]):
                raise ValueError("P05 baseline requires camera_id=0")
            if any(int(round(value)) != 1 for value in values["is_learned"]):
                raise ValueError("P05 baseline requires is_learned=1")

            finite_names = (
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
                for name in finite_names
                for value in values[name]
            ):
                raise ValueError("non-finite P05 coordinate channel")
            if any(
                not all(math.isfinite(float(value)) for value in (point.x, point.y, point.z))
                for point in msg.points
            ):
                raise ValueError("non-finite P05 point geometry")

            for raw_source, raw_q, raw_sigma in zip(
                values["source_code"], values["quality"], values["sigma"]
            ):
                source = int(round(raw_source))
                q = float(raw_q)
                sigma = float(raw_sigma)
                if source != expected_source_code:
                    raise ValueError(f"unexpected P05 source code: {source}")
                if not math.isfinite(q) or q < q_floor - 1e-6 or q > 1.0 + 1e-6:
                    raise ValueError(f"quality outside [{q_floor},1]: {q}")
                if not math.isfinite(sigma) or not math.isclose(
                    sigma, 1.0 / math.sqrt(q), rel_tol=0.0, abs_tol=2e-6
                ):
                    raise ValueError("sigma is inconsistent with native quality")
                source_counts[source] += 1
                observation_count += 1
                q_min = min(q_min, q)
                q_max = max(q_max, q)
                sigma_min = min(sigma_min, sigma)
                sigma_max = max(sigma_max, sigma)

    if not feature_counts or observation_count == 0:
        raise ValueError("bag has no P05 feature observations")
    if nonfeature_messages == 0:
        raise ValueError("bag has no copied non-feature sensor messages")
    if any(right <= left for left, right in zip(feature_stamps, feature_stamps[1:])):
        raise ValueError("feature timestamps are not strictly increasing")
    if any(count == 0 for count in feature_counts[1:]):
        raise ValueError("P05 bag has a non-initial zero-feature frame")
    if set(source_counts) != {expected_source_code}:
        raise ValueError("P05 bag source set mismatch")

    metrics_rows = list(csv.DictReader(metrics_path.open(newline="", encoding="utf-8")))
    if len(metrics_rows) != len(feature_counts):
        raise ValueError("frontend metrics frame count mismatch")
    metrics_counts = [int(float(row["exported_features"])) for row in metrics_rows]
    if metrics_counts != feature_counts:
        raise ValueError("frontend metrics feature counts do not match bag")
    if any(
        value and not value.startswith("xfeat:")
        for value in (row.get("export_source_histogram", "") for row in metrics_rows)
    ):
        raise ValueError("frontend metrics contain a non-XFeat source histogram")

    return {
        "status": "PASS",
        "feature_topic": feature_topic,
        "total_messages": total_messages,
        "nonfeature_messages": nonfeature_messages,
        "feature_frames": len(feature_counts),
        "feature_observations": observation_count,
        "zero_feature_frames": sum(count == 0 for count in feature_counts),
        "min_features_per_frame": min(feature_counts),
        "max_features_per_frame": max(feature_counts),
        "source_counts": {str(key): value for key, value in sorted(source_counts.items())},
        "quality_min": q_min,
        "quality_max": q_max,
        "sigma_min": sigma_min,
        "sigma_max": sigma_max,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--feature-bag", type=Path, required=True)
    parser.add_argument("--frontend-metrics", type=Path)
    parser.add_argument("--contract", type=Path, default=DEFAULT_CONTRACT)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    contract = json.loads(args.contract.read_text(encoding="utf-8"))
    if contract.get("schema_version") != "aqua-fe-p05-xfeat-backend-consumer-contract-v1":
        raise ValueError("P05 backend contract schema mismatch")
    if contract.get("status") != "FROZEN_DEVELOPMENT_P05_CONSUMER_CONTRACT":
        raise ValueError("P05 backend contract status mismatch")
    if payload_hash(contract) != contract.get("contract_hash"):
        raise ValueError("P05 backend contract hash mismatch")

    metrics_path = args.frontend_metrics or args.feature_bag.parent / "frontend_metrics.csv"
    reused = contract["reused_bag"]
    frontend = contract["frontend"]
    backend_runtime = contract["backend_runtime"]
    frontend_runtime = frontend["runtime"]
    stats = audit_bag(
        args.feature_bag,
        metrics_path,
        feature_topic=str(reused["feature_topic"]),
        max_features=int(frontend_runtime["export_max_features"]),
        q_floor=float(backend_runtime["backend_quality_floor"]),
        expected_source_code=int(reused["required_source_code"]),
    )
    payload: dict[str, object] = {
        "schema_version": reused["attestation_schema"],
        "status": "PASS",
        "contract_pass": True,
        "baseline_id": contract["baseline_id"],
        "backend_contract": str(args.contract.resolve()),
        "backend_contract_hash": contract["contract_hash"],
        "feature_bag": str(args.feature_bag.resolve()),
        "feature_bag_sha256": sha256(args.feature_bag),
        "feature_bag_size_bytes": args.feature_bag.stat().st_size,
        "frontend_metrics": str(metrics_path.resolve()),
        "frontend_metrics_sha256": sha256(metrics_path),
        "frontend_metrics_size_bytes": metrics_path.stat().st_size,
        "backend_runtime": backend_runtime,
        "frontend_runtime": frontend_runtime,
        "producer_identity": producer_identity(contract),
        "bag_audit": stats,
    }
    payload["attestation_hash"] = attestation_payload_hash(payload)
    if args.output.exists():
        raise FileExistsError(args.output)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_name(f"{args.output.name}.partial.{os.getpid()}")
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    os.replace(temporary, args.output)
    print(
        "P05_XFEAT_BAG_ATTESTATION PASS "
        f"frames={stats['feature_frames']} observations={stats['feature_observations']} "
        f"output={args.output}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
