#!/usr/bin/env python3
"""Replace learned sidecar observations in selected feature frames.

This is a diagnostic utility for VINS external-feature bags. It keeps the
target bag intact, removes learned/high-id observations from selected feature
frames, and appends the learned/high-id observations from a reference bag at
the same frame indices. Non-feature topics and all non-selected feature frames
are copied unchanged.
"""

from __future__ import annotations

import argparse
import copy
import csv
from pathlib import Path

import rosbag


DEFAULT_LEARNED_SOURCE_CODES = {10, 20, 30}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target-bag", required=True, help="Bag to rewrite.")
    parser.add_argument("--reference-bag", required=True, help="Bag providing learned observations.")
    parser.add_argument("--output-bag", required=True)
    parser.add_argument("--stats-csv", required=True)
    parser.add_argument("--feature-topic", default="/feature_tracker/feature")
    parser.add_argument(
        "--frame-index",
        action="append",
        type=int,
        required=True,
        help="Selected feature-frame index to replace. Repeatable.",
    )
    parser.add_argument("--learned-id-min", type=int, default=10_000_000)
    parser.add_argument(
        "--reference-source-code",
        type=int,
        default=30,
        help="source_code value assigned when the reference bag lacks this channel.",
    )
    args = parser.parse_args()

    stats = replace_observations(
        target_bag=Path(args.target_bag),
        reference_bag=Path(args.reference_bag),
        output_bag=Path(args.output_bag),
        feature_topic=str(args.feature_topic),
        frame_indices={int(item) for item in args.frame_index},
        learned_id_min=int(args.learned_id_min),
        reference_source_code=int(args.reference_source_code),
    )
    stats.update(
        {
            "target_bag": str(args.target_bag),
            "reference_bag": str(args.reference_bag),
            "output_bag": str(args.output_bag),
            "feature_topic": str(args.feature_topic),
            "frame_indices": ",".join(str(idx) for idx in sorted(set(args.frame_index))),
            "learned_id_min": int(args.learned_id_min),
            "reference_source_code": int(args.reference_source_code),
        }
    )
    write_stats(Path(args.stats_csv), stats)
    print(f"wrote {args.output_bag}")
    print(
        "feature_frames={feature_frames} replaced_frames={replaced_frames} "
        "removed_target={removed_target_observations} inserted_reference={inserted_reference_observations}".format(
            **stats
        )
    )
    return 0


def replace_observations(
    *,
    target_bag: Path,
    reference_bag: Path,
    output_bag: Path,
    feature_topic: str,
    frame_indices: set[int],
    learned_id_min: int,
    reference_source_code: int,
) -> dict[str, int]:
    reference = load_reference_observations(
        reference_bag=reference_bag,
        feature_topic=feature_topic,
        frame_indices=frame_indices,
        learned_id_min=learned_id_min,
    )
    output_bag.parent.mkdir(parents=True, exist_ok=True)

    feature_frames = 0
    replaced_frames = 0
    removed_target_observations = 0
    inserted_reference_observations = 0
    missing_reference_frames = 0
    non_feature_messages = 0

    with rosbag.Bag(str(target_bag), "r") as in_bag, rosbag.Bag(str(output_bag), "w") as out_bag:
        for topic, msg, stamp in in_bag.read_messages():
            if topic == feature_topic:
                frame_index = feature_frames
                feature_frames += 1
                if frame_index in frame_indices:
                    observations = reference.get(frame_index, [])
                    if not observations:
                        missing_reference_frames += 1
                    before = len(msg.points)
                    remove_learned_observations(msg, learned_id_min=learned_id_min)
                    after = len(msg.points)
                    removed_target_observations += before - after
                    append_reference_observations(
                        msg,
                        observations,
                        reference_source_code=reference_source_code,
                    )
                    inserted_reference_observations += len(observations)
                    replaced_frames += 1
            else:
                non_feature_messages += 1
            out_bag.write(topic, msg, stamp)

    return {
        "feature_frames": feature_frames,
        "non_feature_messages": non_feature_messages,
        "requested_frames": len(frame_indices),
        "replaced_frames": replaced_frames,
        "missing_reference_frames": missing_reference_frames,
        "removed_target_observations": removed_target_observations,
        "inserted_reference_observations": inserted_reference_observations,
    }


def load_reference_observations(
    *,
    reference_bag: Path,
    feature_topic: str,
    frame_indices: set[int],
    learned_id_min: int,
) -> dict[int, list[dict[str, object]]]:
    out: dict[int, list[dict[str, object]]] = {}
    with rosbag.Bag(str(reference_bag), "r") as bag:
        for frame_index, (_topic, msg, _stamp) in enumerate(bag.read_messages(topics=[feature_topic])):
            if frame_index not in frame_indices:
                continue
            channels = channel_map(msg)
            observations: list[dict[str, object]] = []
            for obs_index in learned_indices(msg, learned_id_min=learned_id_min):
                values = {
                    name: float(channel.values[obs_index])
                    for name, channel in channels.items()
                    if len(channel.values) == len(msg.points)
                }
                observations.append(
                    {
                        "point": copy.deepcopy(msg.points[obs_index]),
                        "channels": values,
                    }
                )
            out[frame_index] = observations
    return out


def remove_learned_observations(msg, *, learned_id_min: int) -> None:
    keep = [True] * len(msg.points)
    for idx in learned_indices(msg, learned_id_min=learned_id_min):
        keep[idx] = False
    filter_observations(msg, keep)


def append_reference_observations(
    msg,
    observations: list[dict[str, object]],
    *,
    reference_source_code: int,
) -> None:
    if not observations:
        return
    channels = channel_map(msg)
    for observation in observations:
        msg.points.append(copy.deepcopy(observation["point"]))
        values = observation["channels"]
        for channel in msg.channels:
            if channel.name in values:
                channel.values.append(float(values[channel.name]))
            elif channel.name == "source_code":
                channel.values.append(float(reference_source_code))
            elif channel.name == "is_learned":
                channel.values.append(1.0)
            else:
                channel.values.append(0.0)
    # Add explicit learned/source channels if the target bag did not have them.
    if "source_code" not in channels:
        add_channel(msg, "source_code", len(msg.points) - len(observations), float(reference_source_code))
    if "is_learned" not in channels:
        add_channel(msg, "is_learned", len(msg.points) - len(observations), 1.0)


def add_channel(msg, name: str, old_count: int, learned_value: float) -> None:
    from sensor_msgs.msg import ChannelFloat32

    channel = ChannelFloat32(name=name)
    channel.values = [0.0] * old_count + [float(learned_value)] * (len(msg.points) - old_count)
    msg.channels.append(channel)


def learned_indices(msg, *, learned_id_min: int) -> list[int]:
    channels = channel_map(msg)
    ids = list(channels.get("id", empty_channel()).values)
    source = list(channels.get("source_code", empty_channel()).values)
    is_learned = list(channels.get("is_learned", empty_channel()).values)
    out: list[int] = []
    for idx in range(len(msg.points)):
        feature_id = safe_int(ids[idx], -1) if idx < len(ids) else -1
        source_code = safe_int(source[idx], 0) if idx < len(source) else 0
        learned_flag = float(is_learned[idx]) > 0.5 if idx < len(is_learned) else False
        if (
            feature_id >= int(learned_id_min)
            or source_code in DEFAULT_LEARNED_SOURCE_CODES
            or learned_flag
        ):
            out.append(idx)
    return out


def filter_observations(msg, keep: list[bool]) -> None:
    if len(msg.points) == len(keep):
        msg.points = [point for point, keep_value in zip(msg.points, keep) if keep_value]
    for channel in msg.channels:
        if len(channel.values) == len(keep):
            channel.values = [float(value) for value, keep_value in zip(channel.values, keep) if keep_value]


def channel_map(msg) -> dict[str, object]:
    return {channel.name: channel for channel in getattr(msg, "channels", [])}


class empty_channel:
    values: list[float] = []


def safe_int(value: object, default: int) -> int:
    try:
        return int(round(float(value)))
    except (TypeError, ValueError, OverflowError):
        return int(default)


def write_stats(path: Path, row: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(row.keys()))
        writer.writeheader()
        writer.writerow(row)


if __name__ == "__main__":
    raise SystemExit(main())
