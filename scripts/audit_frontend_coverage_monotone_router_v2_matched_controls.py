#!/usr/bin/env python3
"""Audit v2 matched-GFTT bags against their learned target bags."""

from __future__ import annotations

import csv
import io
import json
from pathlib import Path
from typing import Any

import rosbag

from audit_frontend_coverage_monotone_router_v2_actions import bag_inventory, sha256


ROOT = Path("/home/ma/AQUA-FE_WS")
PAPER = ROOT / "papers/frontend_coverage_monotone_router_v2"
FEATURE_TOPIC = "/feature_tracker/feature"


def serialized(message: Any) -> bytes:
    stream = io.BytesIO()
    message.serialize(stream)
    return stream.getvalue()


def feature_messages(path: Path) -> list[Any]:
    with rosbag.Bag(str(path), "r") as bag:
        return [
            message for _topic, message, _stamp in bag.read_messages(
                topics=[FEATURE_TOPIC]
            )
        ]


def channels(message: Any) -> dict[str, list[float]]:
    return {channel.name: list(channel.values) for channel in message.channels}


def nonfeature_equal(left: Path, right: Path) -> tuple[bool, int]:
    def load(path: Path) -> list[tuple[str, str, int, bytes]]:
        rows: list[tuple[str, str, int, bytes]] = []
        with rosbag.Bag(str(path), "r") as bag:
            for topic, message, stamp in bag.read_messages():
                if topic == FEATURE_TOPIC:
                    continue
                rows.append(
                    (str(topic), str(message._type), int(stamp.to_nsec()), serialized(message))
                )
        return rows

    left_rows = load(left)
    right_rows = load(right)
    return left_rows == right_rows, len(left_rows)


def main() -> int:
    plan = json.loads((PAPER / "matched_control_plan.json").read_text(encoding="utf-8"))
    output: list[dict[str, object]] = []
    all_pass = True
    for cell in plan["cells"]:
        evidence = PAPER / "matched_controls" / cell["run_slug"] / cell["arm"]
        stats_path = evidence / "stats.json"
        stats = json.loads(stats_path.read_text(encoding="utf-8"))
        target_path = Path(stats["target_bag"])
        control_path = Path(stats["output_bag"])
        target = feature_messages(target_path)
        control = feature_messages(control_path)
        target_ids = {int(value) for value in stats["target_ids"]}
        frame_count_equal = len(target) == len(control)
        timestamp_equal = frame_count_equal and all(
            left.header.stamp == right.header.stamp
            for left, right in zip(target, control)
        )
        point_count_equal = frame_count_equal and all(
            len(left.points) == len(right.points)
            for left, right in zip(target, control)
        )
        id_order_equal = True
        non_target_exact = True
        target_frame_identity = True
        target_quality_sigma_equal = True
        target_source_is_control = True
        original_target_observations = 0
        control_target_observations = 0
        original_target_frames: dict[int, list[int]] = {
            value: [] for value in sorted(target_ids)
        }
        control_target_frames: dict[int, list[int]] = {
            value: [] for value in sorted(target_ids)
        }
        unexpected_learned = 0

        for frame_index, (left, right) in enumerate(zip(target, control)):
            left_channels = channels(left)
            right_channels = channels(right)
            left_ids = [int(round(value)) for value in left_channels["id"]]
            right_ids = [int(round(value)) for value in right_channels["id"]]
            id_order_equal &= left_ids == right_ids
            if len(left_ids) != len(right_ids):
                non_target_exact = False
                continue
            for index, feature_id in enumerate(left_ids):
                if feature_id in target_ids:
                    original_target_observations += 1
                    control_target_observations += int(right_ids[index] == feature_id)
                    original_target_frames[feature_id].append(frame_index)
                    if right_ids[index] == feature_id:
                        control_target_frames[feature_id].append(frame_index)
                    target_quality_sigma_equal &= all(
                        left_channels[name][index] == right_channels[name][index]
                        for name in ("quality", "sigma")
                    )
                    target_source_is_control &= (
                        int(round(right_channels["source_code"][index])) == 0
                        and float(right_channels["is_learned"][index]) <= 0.5
                    )
                    continue
                if left.points[index] != right.points[index]:
                    non_target_exact = False
                for name, values in left_channels.items():
                    if values[index] != right_channels[name][index]:
                        non_target_exact = False
            unexpected_learned += sum(
                float(value) > 0.5 for value in right_channels["is_learned"]
            )

        target_frame_identity &= original_target_frames == control_target_frames
        nonfeature_messages_equal, nonfeature_messages = nonfeature_equal(
            target_path, control_path
        )
        target_inventory = bag_inventory(target_path)
        control_inventory = bag_inventory(control_path)
        topic_identity_equal = (
            target_inventory["topic_identity_json"]
            == control_inventory["topic_identity_json"]
        )
        stages = stats["stages"]
        stage_hashes_pass = all(
            sha256(Path(stage["stage_stats"])) == stage["stage_stats_sha256"]
            for stage in stages
        )
        status = bool(
            stats["status"] == "MATCHED"
            and sha256(target_path) == stats["target_bag_sha256"]
            and sha256(control_path) == stats["output_bag_sha256"]
            and stats["matched_lineages"] == stats["target_lineages"]
            and stats["inserted_observations"] == stats["removed_observations"]
            and original_target_observations == stats["removed_observations"]
            and control_target_observations == stats["inserted_observations"]
            and frame_count_equal
            and timestamp_equal
            and point_count_equal
            and id_order_equal
            and non_target_exact
            and target_frame_identity
            and target_quality_sigma_equal
            and target_source_is_control
            and unexpected_learned == 0
            and nonfeature_messages_equal
            and topic_identity_equal
            and stage_hashes_pass
        )
        all_pass &= status
        output.append(
            {
                "run_slug": cell["run_slug"],
                "arm": cell["arm"],
                "status": "PASS" if status else "FAIL",
                "target_lineages": stats["target_lineages"],
                "matched_lineages": stats["matched_lineages"],
                "removed_observations": stats["removed_observations"],
                "inserted_observations": stats["inserted_observations"],
                "feature_frames": len(control),
                "feature_frame_count_equal": frame_count_equal,
                "feature_timestamps_equal": timestamp_equal,
                "point_count_equal_per_frame": point_count_equal,
                "feature_id_order_equal": id_order_equal,
                "target_frame_identity_equal": target_frame_identity,
                "target_quality_sigma_equal": target_quality_sigma_equal,
                "target_source_code_zero_and_not_learned": target_source_is_control,
                "unexpected_learned_observations": unexpected_learned,
                "non_target_feature_fields_exact": non_target_exact,
                "nonfeature_messages": nonfeature_messages,
                "nonfeature_messages_exact": nonfeature_messages_equal,
                "topic_identity_equal": topic_identity_equal,
                "stage_stats_hashes_pass": stage_hashes_pass,
                "target_bag_sha256": target_inventory["sha256"],
                "control_bag_sha256": control_inventory["sha256"],
                "target_bag": str(target_path),
                "control_bag": str(control_path),
                "stats": str(stats_path),
            }
        )

    path = PAPER / "matched_control_audit.csv"
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(output[0]))
        writer.writeheader()
        writer.writerows(output)
    return 0 if all_pass else 1


if __name__ == "__main__":
    raise SystemExit(main())
