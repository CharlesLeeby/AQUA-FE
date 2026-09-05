#!/usr/bin/env python3
"""Build the two preregistered positive-window donor-delete-only bags."""

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
PAPER = ROOT / "papers/frontend_v2_positive_delete_diagnostic"
V2_PAPER = ROOT / "papers/frontend_coverage_monotone_router_v2"
RUNTIME = Path(
    "/media/ma/Data/AQUA-FE_WS_storage_offload/"
    "frontend_v2_positive_delete_diagnostic"
)
PROTOCOL = PAPER / "preregistration.md"
CONTRACT = PAPER / "contract.json"
BUILD_RECEIPT = PAPER / "build_receipt.json"
DELETIONS_CSV = PAPER / "deleted_observations.csv"

WINDOWS = (
    {
        "window_id": "aqualoc_archaeology:A09:historical_6000_6800",
        "run_slug": "a09_6000_6800",
        "deletions": {
            1542889046271565680: {944},
            1542889046371444368: {1086},
            1542889046471564144: {1320},
        },
    },
    {
        "window_id": "afrl:bus_outside:0004",
        "run_slug": "afrl_bus_s180_d045",
        "deletions": {1494876660116016699: {487, 500}},
    },
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as stream:
        return list(csv.DictReader(stream))


def write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


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
    removed = set(indices)
    keep = [index for index in range(point_count) if index not in removed]
    message.points = [message.points[index] for index in keep]
    for channel in message.channels:
        channel.values = [channel.values[index] for index in keep]


def expected_feature_message(
    source_message: object, deletions: dict[int, set[int]]
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


def resolve_v2_inputs(spec: dict[str, object]) -> dict[str, object]:
    slug = str(spec["run_slug"])
    plan = read_csv(V2_PAPER / "backend_smoke_plan.csv")
    by_cell = {
        row["cell_id"]: row
        for row in plan
        if row["run_slug"] == slug and row["repeat"] == "1"
    }
    required = ("klt", "router_xfeat", "matched_gftt_for_router_xfeat")
    if any(cell not in by_cell for cell in required):
        raise RuntimeError(f"missing v2 inputs for {slug}")
    return {
        "fresh_klt_bag": by_cell["klt"]["feature_bag"],
        "fresh_klt_bag_sha256": by_cell["klt"]["feature_bag_sha256"],
        "learned_bag": by_cell["router_xfeat"]["feature_bag"],
        "learned_bag_sha256": by_cell["router_xfeat"]["feature_bag_sha256"],
        "matched_bag": by_cell["matched_gftt_for_router_xfeat"]["feature_bag"],
        "matched_bag_sha256": by_cell["matched_gftt_for_router_xfeat"]["feature_bag_sha256"],
        "canonical_config": by_cell["klt"]["canonical_config"],
        "canonical_config_sha256": by_cell["klt"]["canonical_config_sha256"],
        "camera_config": by_cell["klt"]["camera_config"],
        "camera_config_sha256": by_cell["klt"]["camera_config_sha256"],
    }


def verify_registered_actions() -> None:
    rows = read_csv(V2_PAPER / "action_audit.csv")
    actual: dict[str, Counter[tuple[int, int]]] = {}
    for row in rows:
        if row["arm"] != "router_xfeat" or not row["timestamp_ns"]:
            continue
        ids = json.loads(row["deleted_track_ids_json"] or "[]")
        if ids:
            actual.setdefault(row["run_slug"], Counter()).update(
                (int(row["timestamp_ns"]), int(feature_id)) for feature_id in ids
            )
    for spec in WINDOWS:
        expected = Counter(
            (timestamp, feature_id)
            for timestamp, ids in spec["deletions"].items()
            for feature_id in ids
        )
        if actual.get(str(spec["run_slug"])) != expected:
            raise RuntimeError(f"action-audit deletion mismatch for {spec['run_slug']}")


def freeze_contract() -> dict[str, object]:
    if CONTRACT.exists() or BUILD_RECEIPT.exists():
        raise RuntimeError("refusing to overwrite existing frozen contract/receipt")
    verify_registered_actions()
    files = (
        PROTOCOL,
        V2_PAPER / "action_audit.csv",
        V2_PAPER / "backend_smoke_plan.csv",
        V2_PAPER / "backend_results_repeats.csv",
        V2_PAPER / "accuracy_repeats.csv",
        ROOT / "scripts/build_frontend_v2_positive_delete_controls.py",
        ROOT / "scripts/run_frontend_v2_positive_delete_backend.py",
        ROOT / "scripts/run_frontend_v2_positive_delete_backend_cell.sh",
        ROOT / "scripts/analyze_frontend_v2_positive_delete_backend.py",
        ROOT / "scripts/evaluate_vins_common_support_dual_scale.py",
    )
    for path in files:
        if not path.is_file():
            raise RuntimeError(f"missing frozen file: {path}")
    contract_windows = []
    for spec in WINDOWS:
        inputs = resolve_v2_inputs(spec)
        for key in ("fresh_klt_bag", "learned_bag", "matched_bag", "canonical_config", "camera_config"):
            path = Path(str(inputs[key]))
            if not path.is_file() or sha256(path) != inputs[f"{key}_sha256"]:
                raise RuntimeError(f"v2 identity drift: {path}")
        contract_windows.append(
            {
                "window_id": spec["window_id"],
                "run_slug": spec["run_slug"],
                "proxy_topic": (
                    "/afrl/colmap_gt"
                    if str(spec["window_id"]).startswith("afrl:")
                    else "/aqualoc/colmap_gt"
                ),
                "deletions": {
                    str(timestamp): sorted(ids)
                    for timestamp, ids in spec["deletions"].items()
                },
                **inputs,
            }
        )
    vins_node = Path("/home/ma/SLAM/VINS-Fusion-origin/devel/lib/vins/vins_node")
    vins_lib = Path("/home/ma/SLAM/VINS-Fusion-origin/devel/lib/libvins_lib.so")
    contract = {
        "schema_version": "aqua-fe-v2-positive-delete-contract-v1",
        "frozen_at": "2026-09-05T22:31:00+08:00",
        "outcomes_observed_before_freeze": False,
        "feature_topic": "/feature_tracker/feature",
        "new_replay_order": [
            f"{spec['run_slug']}:repeat{repeat}"
            for spec in WINDOWS for repeat in (1, 2, 3)
        ],
        "windows": contract_windows,
        "files": [{"path": str(path), "sha256": sha256(path)} for path in files],
        "vins_node": str(vins_node),
        "vins_node_sha256": sha256(vins_node),
        "vins_lib": str(vins_lib),
        "vins_lib_sha256": sha256(vins_lib),
        "gates": {"coverage": 0.70, "common_poses": 30, "common_span_s": 10, "rpe_pairs": 10},
        "primary_alignment": "proper fixed-scale SE(3)",
        "diagnostic_alignment": "Sim(3)",
    }
    CONTRACT.write_text(json.dumps(contract, indent=2) + "\n", encoding="utf-8")
    return contract


def build_and_audit(window: dict[str, object], topic: str) -> tuple[dict[str, object], list[dict[str, object]]]:
    slug = str(window["run_slug"])
    source = Path(str(window["fresh_klt_bag"]))
    output = RUNTIME / slug / "features_donor_delete_only.bag"
    if output.exists():
        raise RuntimeError(f"refusing to overwrite derived bag: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    deletions = {
        int(timestamp): {int(feature_id) for feature_id in ids}
        for timestamp, ids in dict(window["deletions"]).items()
    }
    deleted_rows: list[dict[str, object]] = []
    with rosbag.Bag(str(source), "r") as source_bag, rosbag.Bag(str(output), "w") as output_bag:
        for record_topic, message, stamp, connection_header in source_bag.read_messages(
            return_connection_header=True
        ):
            if record_topic == topic:
                original_count = len(message.points)
                expected, removed = expected_feature_message(message, deletions)
                for feature_id in removed:
                    deleted_rows.append(
                        {
                            "window_id": window["window_id"],
                            "run_slug": slug,
                            "timestamp_ns": int(message.header.stamp.to_nsec()),
                            "feature_id": feature_id,
                            "source_feature_count": original_count,
                            "derived_feature_count": len(expected.points),
                        }
                    )
                message = expected
            output_bag.write(record_topic, message, stamp, connection_header=connection_header)
    expected_pairs = Counter(
        (timestamp, feature_id) for timestamp, ids in deletions.items() for feature_id in ids
    )
    actual_pairs = Counter(
        (int(row["timestamp_ns"]), int(row["feature_id"])) for row in deleted_rows
    )
    if actual_pairs != expected_pairs:
        raise RuntimeError(f"deleted set mismatch for {slug}")

    total = feature_messages = changed = retained = learned_flags = 0
    source_counts: Counter[str] = Counter()
    output_counts: Counter[str] = Counter()
    with rosbag.Bag(str(source), "r") as source_bag, rosbag.Bag(str(output), "r") as output_bag:
        sentinel = object()
        for source_record, output_record in itertools.zip_longest(
            source_bag.read_messages(return_connection_header=True),
            output_bag.read_messages(return_connection_header=True),
            fillvalue=sentinel,
        ):
            if source_record is sentinel or output_record is sentinel:
                raise RuntimeError(f"message-count mismatch for {slug}")
            source_topic, source_message, source_stamp, _ = source_record
            output_topic, output_message, output_stamp, _ = output_record
            total += 1
            source_counts[source_topic] += 1
            output_counts[output_topic] += 1
            if source_topic != output_topic or source_stamp.to_nsec() != output_stamp.to_nsec():
                raise RuntimeError(f"topic/timestamp drift for {slug} record {total}")
            if source_topic != topic:
                if serialize(source_message) != serialize(output_message):
                    raise RuntimeError(f"non-feature drift for {slug} record {total}")
                continue
            feature_messages += 1
            expected, removed = expected_feature_message(source_message, deletions)
            if serialize(expected) != serialize(output_message):
                raise RuntimeError(f"feature drift for {slug} record {total}")
            changed += int(bool(removed))
            retained += len(output_message.points)
            channels = {channel.name: channel for channel in output_message.channels}
            learned_flags += sum(value > 0.5 for value in channels.get("is_learned", []).values) if "is_learned" in channels else 0
    if source_counts != output_counts or changed != len(deletions) or learned_flags:
        raise RuntimeError(f"structural audit failure for {slug}")
    audit = {
        "schema_version": "aqua-fe-v2-positive-delete-bag-audit-v1",
        "status": "PASS",
        "window_id": window["window_id"],
        "run_slug": slug,
        "source_bag": str(source),
        "source_bag_sha256": sha256(source),
        "output_bag": str(output),
        "output_bag_sha256": sha256(output),
        "total_messages": total,
        "feature_messages": feature_messages,
        "changed_feature_messages": changed,
        "deleted_observations": len(deleted_rows),
        "retained_feature_observations": retained,
        "learned_flags_in_output": learned_flags,
        "checks": {
            "registered_observation_set_exact": True,
            "retained_feature_serialization_exact": True,
            "non_feature_serialization_exact": True,
            "topic_counts_and_bag_timestamps_exact": True,
            "no_learned_feature_introduced": True,
        },
    }
    audit_path = PAPER / f"bag_structural_audit_{slug}.json"
    audit_path.write_text(json.dumps(audit, indent=2) + "\n", encoding="utf-8")
    return audit, deleted_rows


def main() -> int:
    PAPER.mkdir(parents=True, exist_ok=True)
    contract = freeze_contract()
    audits = []
    rows: list[dict[str, object]] = []
    for window in contract["windows"]:
        audit, deleted = build_and_audit(window, str(contract["feature_topic"]))
        audits.append(audit)
        rows.extend(deleted)
    write_csv(DELETIONS_CSV, rows)
    receipt = {
        "schema_version": "aqua-fe-v2-positive-delete-build-receipt-v1",
        "status": "PASS",
        "contract_sha256": sha256(CONTRACT),
        "windows": audits,
    }
    BUILD_RECEIPT.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": "PASS", "bags": len(audits), "deleted": len(rows)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
