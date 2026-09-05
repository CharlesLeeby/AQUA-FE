#!/usr/bin/env python3
"""Build and audit the preregistered A02 donor-delete-only control bag."""

from __future__ import annotations

import copy
import csv
import hashlib
import io
import itertools
import json
from collections import Counter
from pathlib import Path

import rosbag


ROOT = Path("/home/ma/AQUA-FE_WS")
PAPER = ROOT / "papers/frontend_coverage_monotone_router_v2_donor_delete_diagnostic"
CONTRACT = PAPER / "contract.json"
RUNTIME = Path(
    "/media/ma/Data/AQUA-FE_WS_storage_offload/"
    "frontend_coverage_monotone_router_v2_donor_delete_diagnostic"
)
OUTPUT = RUNTIME / "a02_0_900/features_donor_delete_only.bag"
STATS = PAPER / "bag_structural_audit.json"
DELETIONS_CSV = PAPER / "deleted_observations.csv"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def serialize(message: object) -> bytes:
    stream = io.BytesIO()
    message.serialize(stream)
    return stream.getvalue()


def feature_ids(message: object) -> list[int]:
    channels = {channel.name: channel for channel in message.channels}
    if "id" not in channels:
        raise RuntimeError("feature message lacks id channel")
    return [int(round(value)) for value in channels["id"].values]


def remove_indices(message: object, indices: list[int]) -> None:
    point_count = len(message.points)
    for channel in message.channels:
        if len(channel.values) != point_count:
            raise RuntimeError(
                f"non-per-feature channel {channel.name}: "
                f"{len(channel.values)} != {point_count}"
            )
    keep = [index for index in range(point_count) if index not in set(indices)]
    message.points = [message.points[index] for index in keep]
    for channel in message.channels:
        channel.values = [channel.values[index] for index in keep]


def verify_contract(contract: dict[str, object]) -> Path:
    for item in contract["inputs"]:
        path = Path(item["path"])
        if not path.is_file() or sha256(path) != item["sha256"]:
            raise RuntimeError(f"frozen input identity failure: {path}")
    source = next(
        Path(item["path"])
        for item in contract["inputs"]
        if item["role"] == "fresh_klt_bag"
    )
    return source


def expected_feature_message(
    source_message: object,
    deletions: dict[int, set[int]],
) -> tuple[object, list[int]]:
    expected = copy.deepcopy(source_message)
    timestamp_ns = int(expected.header.stamp.to_nsec())
    ids = feature_ids(expected)
    targets = deletions.get(timestamp_ns, set())
    indices = [index for index, feature_id in enumerate(ids) if feature_id in targets]
    found = [ids[index] for index in indices]
    if targets and Counter(found) != Counter(targets):
        raise RuntimeError(
            f"target multiplicity mismatch at {timestamp_ns}: "
            f"expected={sorted(targets)} found={sorted(found)}"
        )
    remove_indices(expected, indices)
    return expected, found


def build(source: Path, topic: str, deletions: dict[int, set[int]]) -> list[dict[str, object]]:
    if OUTPUT.exists():
        raise RuntimeError(f"refusing to overwrite existing diagnostic bag: {OUTPUT}")
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    deleted_rows: list[dict[str, object]] = []
    with rosbag.Bag(str(source), "r") as source_bag, rosbag.Bag(
        str(OUTPUT), "w"
    ) as output_bag:
        for record in source_bag.read_messages(return_connection_header=True):
            record_topic, message, stamp, connection_header = record
            if record_topic == topic:
                timestamp_ns = int(message.header.stamp.to_nsec())
                expected, removed = expected_feature_message(message, deletions)
                for feature_id in removed:
                    deleted_rows.append(
                        {
                            "timestamp_ns": timestamp_ns,
                            "feature_id": feature_id,
                            "source_feature_count": len(message.points),
                            "derived_feature_count": len(expected.points),
                        }
                    )
                message = expected
            output_bag.write(
                record_topic,
                message,
                stamp,
                connection_header=connection_header,
            )
    expected_pairs = Counter(
        (timestamp_ns, feature_id)
        for timestamp_ns, ids in deletions.items()
        for feature_id in ids
    )
    actual_pairs = Counter(
        (int(row["timestamp_ns"]), int(row["feature_id"])) for row in deleted_rows
    )
    if actual_pairs != expected_pairs:
        raise RuntimeError(
            f"deleted observation set mismatch: expected={expected_pairs} "
            f"actual={actual_pairs}"
        )
    return deleted_rows


def audit(
    source: Path,
    topic: str,
    deletions: dict[int, set[int]],
    deleted_rows: list[dict[str, object]],
) -> dict[str, object]:
    source_counts: Counter[str] = Counter()
    output_counts: Counter[str] = Counter()
    records = 0
    feature_records = 0
    changed_feature_records = 0
    retained_feature_observations = 0
    learned_flags = 0
    source_iter = rosbag.Bag(str(source), "r")
    output_iter = rosbag.Bag(str(OUTPUT), "r")
    try:
        source_records = source_iter.read_messages(return_connection_header=True)
        output_records = output_iter.read_messages(return_connection_header=True)
        sentinel = object()
        for source_record, output_record in itertools.zip_longest(
            source_records, output_records, fillvalue=sentinel
        ):
            if source_record is sentinel or output_record is sentinel:
                raise RuntimeError("source/output message-count mismatch")
            source_topic, source_message, source_stamp, _ = source_record
            output_topic, output_message, output_stamp, _ = output_record
            records += 1
            source_counts[source_topic] += 1
            output_counts[output_topic] += 1
            if source_topic != output_topic or source_stamp.to_nsec() != output_stamp.to_nsec():
                raise RuntimeError(f"topic or bag timestamp drift at record {records}")
            if source_topic != topic:
                if serialize(source_message) != serialize(output_message):
                    raise RuntimeError(f"non-feature message drift at record {records}")
                continue
            feature_records += 1
            expected, removed = expected_feature_message(source_message, deletions)
            if serialize(expected) != serialize(output_message):
                raise RuntimeError(f"feature message drift at record {records}")
            if int(source_message.header.stamp.to_nsec()) != int(
                output_message.header.stamp.to_nsec()
            ):
                raise RuntimeError(f"feature header timestamp drift at record {records}")
            if removed:
                changed_feature_records += 1
            retained_feature_observations += len(output_message.points)
            channels = {channel.name: channel for channel in output_message.channels}
            if "is_learned" in channels:
                learned_flags += sum(value > 0.5 for value in channels["is_learned"].values)
    finally:
        source_iter.close()
        output_iter.close()
    if source_counts != output_counts:
        raise RuntimeError("per-topic message counts changed")
    if changed_feature_records != len(deletions):
        raise RuntimeError(
            f"edited feature-frame mismatch: {changed_feature_records} != {len(deletions)}"
        )
    if learned_flags:
        raise RuntimeError(f"derived KLT control contains {learned_flags} learned flags")
    return {
        "schema_version": "aqua-fe-v2-donor-delete-bag-audit-v1",
        "status": "PASS",
        "source_bag": str(source),
        "source_bag_sha256": sha256(source),
        "output_bag": str(OUTPUT),
        "output_bag_sha256": sha256(OUTPUT),
        "total_messages": records,
        "feature_messages": feature_records,
        "changed_feature_messages": changed_feature_records,
        "deleted_observations": len(deleted_rows),
        "retained_feature_observations": retained_feature_observations,
        "learned_flags_in_output": learned_flags,
        "topic_message_counts": dict(sorted(source_counts.items())),
        "checks": {
            "registered_observation_set_exact": True,
            "targets_unique_in_source": True,
            "retained_feature_serialization_exact": True,
            "non_feature_serialization_exact": True,
            "topic_counts_exact": True,
            "bag_timestamps_exact": True,
            "feature_header_timestamps_exact": True,
            "no_learned_feature_introduced": True
        }
    }


def main() -> int:
    contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
    source = verify_contract(contract)
    topic = str(contract["feature_topic"])
    deletions = {
        int(timestamp): {int(feature_id) for feature_id in feature_ids}
        for timestamp, feature_ids in contract["deletions"].items()
    }
    deleted_rows = build(source, topic, deletions)
    audit_result = audit(source, topic, deletions, deleted_rows)
    with DELETIONS_CSV.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(deleted_rows[0]))
        writer.writeheader()
        writer.writerows(deleted_rows)
    STATS.write_text(json.dumps(audit_result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(audit_result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
