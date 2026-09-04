#!/usr/bin/env python3
"""Bind a native-q ROS feature bag to the frozen backend contract."""

from __future__ import annotations

import argparse
import json
import math
import os
from collections import Counter
from pathlib import Path

import rosbag

try:
    from scripts.build_nativeq_backend_contract import payload_hash, sha256
except ModuleNotFoundError:  # Direct `python3 scripts/...` execution.
    from build_nativeq_backend_contract import payload_hash, sha256


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONTRACT = (
    ROOT / "papers/ieee_sensors_journal_experiments/backend_quality_contract_v1.json"
)


def channels(msg) -> dict[str, list[float]]:
    names = [channel.name for channel in msg.channels]
    if len(names) != len(set(names)):
        raise ValueError("duplicate feature channel")
    return {channel.name: list(channel.values) for channel in msg.channels}


def audit_bag(path: Path, *, floor: float, topic: str) -> dict[str, object]:
    feature_frames = 0
    feature_observations = 0
    learned_observations = 0
    total_messages = 0
    source_counts: Counter[int] = Counter()
    q_min = float("inf")
    q_max = float("-inf")
    with rosbag.Bag(str(path), "r") as bag:
        for message_topic, msg, _stamp in bag.read_messages():
            total_messages += 1
            if message_topic != topic:
                continue
            feature_frames += 1
            values = channels(msg)
            required = {"quality", "sigma", "source_code"}
            if not required.issubset(values):
                raise ValueError(f"missing native-q channels at frame {feature_frames - 1}")
            count = len(msg.points)
            for name in required:
                if len(values[name]) != count:
                    raise ValueError(f"channel length mismatch for {name}")
            is_learned = values.get("is_learned", [0.0] * count)
            if len(is_learned) != count:
                raise ValueError("is_learned channel length mismatch")
            for q, sigma, raw_source, learned in zip(
                values["quality"], values["sigma"], values["source_code"], is_learned
            ):
                q = float(q)
                sigma = float(sigma)
                source = int(round(raw_source))
                if not math.isfinite(q) or q < floor - 1e-6 or q > 1.0 + 1e-6:
                    raise ValueError(f"quality outside [{floor},1]: {q}")
                expected_sigma = 1.0 / math.sqrt(q)
                if not math.isclose(sigma, expected_sigma, rel_tol=0.0, abs_tol=2e-6):
                    raise ValueError("sigma is inconsistent with quality")
                source_counts[source] += 1
                learned_observations += int(source in {10, 20, 30} or round(learned) != 0)
                feature_observations += 1
                q_min = min(q_min, q)
                q_max = max(q_max, q)
    if feature_frames == 0 or feature_observations == 0:
        raise ValueError("bag has no feature observations")
    return {
        "total_messages": total_messages,
        "feature_frames": feature_frames,
        "feature_observations": feature_observations,
        "learned_observations": learned_observations,
        "source_counts": {str(key): value for key, value in sorted(source_counts.items())},
        "quality_min": q_min,
        "quality_max": q_max,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--feature-bag", type=Path, required=True)
    parser.add_argument("--contract", type=Path, default=DEFAULT_CONTRACT)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--feature-topic", default="/feature_tracker/feature")
    args = parser.parse_args()
    contract = json.loads(args.contract.read_text(encoding="utf-8"))
    if payload_hash(contract) != contract.get("contract_hash"):
        raise ValueError("backend contract hash mismatch")
    runtime = contract["expected_runtime"]
    stats = audit_bag(
        args.feature_bag,
        floor=float(runtime["backend_quality_floor"]),
        topic=args.feature_topic,
    )
    payload = {
        "schema_version": "aqua-fe-nativeq-bag-attestation-v1",
        "contract_pass": True,
        "backend_contract": str(args.contract),
        "backend_contract_hash": contract["contract_hash"],
        "feature_bag": str(args.feature_bag.resolve()),
        "feature_bag_sha256": sha256(args.feature_bag),
        "feature_topic": args.feature_topic,
        "runtime_quality_contract": runtime,
        **stats,
    }
    if args.output.exists():
        raise FileExistsError(args.output)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_name(f"{args.output.name}.partial.{os.getpid()}")
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    os.replace(temporary, args.output)
    print(
        "NATIVEQ_BAG_ATTESTATION PASS "
        f"frames={stats['feature_frames']} observations={stats['feature_observations']} "
        f"learned={stats['learned_observations']} output={args.output}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
