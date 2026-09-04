#!/usr/bin/env python3
"""Persist learned sidecar observations for a few following feature frames.

This is a diagnostic bag rewrite used to test whether VINS initialization is
sensitive to missing a short learned/LoFTR support burst by one frame.  It keeps
the original feature messages intact and only appends learned observations from
recent source frames to later feature messages.
"""

from __future__ import annotations

import argparse
import copy
import csv
from collections import deque
from pathlib import Path
from typing import Any

import rosbag
from sensor_msgs.msg import ChannelFloat32


DEFAULT_LEARNED_SOURCE_CODES = {10, 20, 30}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-bag", required=True)
    parser.add_argument("--output-bag", required=True)
    parser.add_argument("--stats-csv", required=True)
    parser.add_argument("--feature-topic", default="/feature_tracker/feature")
    parser.add_argument("--hold-frames", type=int, default=1)
    parser.add_argument("--learned-id-min", type=int, default=10000000)
    parser.add_argument(
        "--source-code",
        action="append",
        type=int,
        default=[],
        help="Only persist these learned source_code values. Default: 10,20,30 or high-id/is_learned.",
    )
    parser.add_argument(
        "--source-frame-index",
        action="append",
        type=int,
        default=[],
        help="Only persist learned observations from these zero-based feature frame indices. Repeatable.",
    )
    parser.add_argument("--max-per-source-frame", type=int, default=0)
    parser.add_argument("--max-total-added", type=int, default=0)
    parser.add_argument(
        "--no-extrapolate",
        action="store_true",
        help="Keep copied coordinates unchanged instead of propagating by velocity_x/y.",
    )
    args = parser.parse_args()

    stats, rows = persist_sidecars(
        input_bag=Path(args.input_bag),
        output_bag=Path(args.output_bag),
        feature_topic=str(args.feature_topic),
        hold_frames=max(0, int(args.hold_frames)),
        learned_id_min=int(args.learned_id_min),
        source_codes={int(code) for code in args.source_code},
        source_frame_indices={int(index) for index in args.source_frame_index},
        max_per_source_frame=max(0, int(args.max_per_source_frame)),
        max_total_added=max(0, int(args.max_total_added)),
        extrapolate=not bool(args.no_extrapolate),
    )
    stats.update(
        {
            "input_bag": str(args.input_bag),
            "output_bag": str(args.output_bag),
            "feature_topic": str(args.feature_topic),
            "hold_frames": max(0, int(args.hold_frames)),
            "learned_id_min": int(args.learned_id_min),
            "source_codes": ",".join(str(code) for code in sorted(args.source_code)),
            "source_frame_indices": ",".join(str(index) for index in sorted(args.source_frame_index)),
            "max_per_source_frame": max(0, int(args.max_per_source_frame)),
            "max_total_added": max(0, int(args.max_total_added)),
            "extrapolate": int(not bool(args.no_extrapolate)),
        }
    )
    write_stats(Path(args.stats_csv), stats, rows)
    print(f"wrote {args.output_bag}")
    print(
        "feature_frames={feature_frames} source_frames={source_frames} "
        "target_frames={target_frames} added_observations={added_observations}".format(**stats)
    )
    return 0


def persist_sidecars(
    *,
    input_bag: Path,
    output_bag: Path,
    feature_topic: str,
    hold_frames: int,
    learned_id_min: int,
    source_codes: set[int],
    source_frame_indices: set[int],
    max_per_source_frame: int,
    max_total_added: int,
    extrapolate: bool,
) -> tuple[dict[str, int], list[dict[str, object]]]:
    active: deque[dict[str, Any]] = deque()
    output_bag.parent.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, object]] = []
    feature_frames = 0
    non_feature_messages = 0
    source_frames = 0
    target_frames = 0
    added_observations = 0

    learned_filter = source_codes or DEFAULT_LEARNED_SOURCE_CODES

    with rosbag.Bag(str(input_bag), "r") as in_bag, rosbag.Bag(str(output_bag), "w") as out_bag:
        for topic, msg, stamp in in_bag.read_messages():
            if topic != feature_topic:
                non_feature_messages += 1
                out_bag.write(topic, msg, stamp)
                continue

            frame_index = feature_frames
            feature_frames += 1
            current_stamp = float(msg.header.stamp.to_sec())
            current_ids = set(_ids(msg))
            original_sources = _select_learned_observations(
                msg,
                source_codes=learned_filter,
                learned_id_min=learned_id_min,
                max_count=max_per_source_frame,
            )

            while active and int(active[0]["expires_after"]) < frame_index:
                active.popleft()

            additions: list[dict[str, object]] = []
            for packet in active:
                if int(packet["source_frame_index"]) == frame_index:
                    continue
                for observation in packet["observations"]:
                    obs_id = int(observation["id"])
                    if obs_id in current_ids:
                        continue
                    if max_total_added > 0 and added_observations + len(additions) >= max_total_added:
                        break
                    propagated = _propagate_observation(
                        observation,
                        target_stamp=current_stamp,
                        extrapolate=extrapolate,
                    )
                    additions.append(propagated)
                    current_ids.add(obs_id)
                    rows.append(
                        {
                            "target_frame_index": frame_index,
                            "target_stamp": f"{current_stamp:.9f}",
                            "source_frame_index": int(packet["source_frame_index"]),
                            "source_stamp": f"{float(packet['source_stamp']):.9f}",
                            "feature_id": obs_id,
                            "source_code": int(round(float(observation["channels"].get("source_code", 0.0)))),
                            "dt_s": f"{current_stamp - float(packet['source_stamp']):.9f}",
                        }
                    )
                if max_total_added > 0 and added_observations + len(additions) >= max_total_added:
                    break

            if additions:
                _append_observations(msg, additions)
                added_observations += len(additions)
                target_frames += 1

            allowed_source_frame = not source_frame_indices or frame_index in source_frame_indices
            if original_sources and hold_frames > 0 and allowed_source_frame:
                source_frames += 1
                active.append(
                    {
                        "source_frame_index": frame_index,
                        "source_stamp": current_stamp,
                        "expires_after": frame_index + hold_frames,
                        "observations": original_sources,
                    }
                )

            out_bag.write(topic, msg, stamp)

    return (
        {
            "feature_frames": feature_frames,
            "non_feature_messages": non_feature_messages,
            "source_frames": source_frames,
            "target_frames": target_frames,
            "added_observations": added_observations,
        },
        rows,
    )


def _select_learned_observations(
    msg,
    *,
    source_codes: set[int],
    learned_id_min: int,
    max_count: int,
) -> list[dict[str, object]]:
    channel_names = [channel.name for channel in msg.channels]
    count = len(msg.points)
    ids = _channel_values(msg, "id", count, -1.0)
    source = _channel_values(msg, "source_code", count, 0.0)
    learned = _channel_values(msg, "is_learned", count, 0.0)
    observations: list[dict[str, object]] = []
    for index in range(count):
        feature_id = int(round(float(ids[index])))
        source_code = int(round(float(source[index])))
        is_learned = (
            bool(round(float(learned[index])))
            or source_code in source_codes
            or (learned_id_min > 0 and feature_id >= learned_id_min)
        )
        if not is_learned:
            continue
        if source_codes and source_code not in source_codes and feature_id < learned_id_min:
            continue
        channels = {
            name: float(msg.channels[channel_index].values[index])
            for channel_index, name in enumerate(channel_names)
        }
        observations.append(
            {
                "id": feature_id,
                "source_stamp": float(msg.header.stamp.to_sec()),
                "point": copy.deepcopy(msg.points[index]),
                "channels": channels,
                "pixel_model": _estimate_pixel_model(msg),
            }
        )
        if max_count > 0 and len(observations) >= max_count:
            break
    return observations


def _propagate_observation(
    observation: dict[str, object],
    *,
    target_stamp: float,
    extrapolate: bool,
) -> dict[str, object]:
    propagated = {
        "point": copy.deepcopy(observation["point"]),
        "channels": dict(observation["channels"]),
    }
    if not extrapolate:
        return propagated
    channels = propagated["channels"]
    point = propagated["point"]
    dt = max(0.0, float(target_stamp) - float(observation["source_stamp"]))
    vx = float(channels.get("velocity_x", 0.0))
    vy = float(channels.get("velocity_y", 0.0))
    point.x = float(point.x) + vx * dt
    point.y = float(point.y) + vy * dt
    model = observation.get("pixel_model")
    if isinstance(model, tuple):
        fx, cx, fy, cy = model
        channels["p_u"] = float(fx * point.x + cx)
        channels["p_v"] = float(fy * point.y + cy)
    return propagated


def _estimate_pixel_model(msg) -> tuple[float, float, float, float] | None:
    count = len(msg.points)
    if count < 8:
        return None
    p_u = _channel_values(msg, "p_u", count, float("nan"))
    p_v = _channel_values(msg, "p_v", count, float("nan"))
    x_rows = []
    y_rows = []
    for index, point in enumerate(msg.points):
        if _finite(point.x) and _finite(point.y) and _finite(p_u[index]) and _finite(p_v[index]):
            x_rows.append((float(point.x), float(p_u[index])))
            y_rows.append((float(point.y), float(p_v[index])))
    if len(x_rows) < 8 or len(y_rows) < 8:
        return None
    fx, cx = _fit_line(x_rows)
    fy, cy = _fit_line(y_rows)
    return fx, cx, fy, cy


def _fit_line(rows: list[tuple[float, float]]) -> tuple[float, float]:
    n = float(len(rows))
    sx = sum(row[0] for row in rows)
    sy = sum(row[1] for row in rows)
    sxx = sum(row[0] * row[0] for row in rows)
    sxy = sum(row[0] * row[1] for row in rows)
    denom = n * sxx - sx * sx
    if abs(denom) < 1e-9:
        return 1.0, 0.0
    slope = (n * sxy - sx * sy) / denom
    intercept = (sy - slope * sx) / n
    return float(slope), float(intercept)


def _append_observations(msg, observations: list[dict[str, object]]) -> None:
    msg.points = list(msg.points)
    for channel in msg.channels:
        channel.values = list(channel.values)
    channel_map = {channel.name: channel for channel in msg.channels}
    existing_count = len(msg.points)
    for observation in observations:
        msg.points.append(copy.deepcopy(observation["point"]))
    for observation in observations:
        values = observation["channels"]
        for name, value in values.items():
            if name not in channel_map:
                channel = ChannelFloat32(name=name)
                channel.values = [0.0] * existing_count
                msg.channels.append(channel)
                channel_map[name] = channel
            channel_map[name].values.append(float(value))
    expected = len(msg.points)
    for channel in msg.channels:
        if len(channel.values) < expected:
            channel.values.extend([0.0] * (expected - len(channel.values)))
        elif len(channel.values) > expected:
            raise ValueError(f"channel {channel.name!r} length exceeds point count")


def _ids(msg) -> list[int]:
    values = _channel_values(msg, "id", len(msg.points), -1.0)
    return [int(round(float(value))) for value in values]


def _channel_values(msg, name: str, count: int, default: float) -> list[float]:
    for channel in msg.channels:
        if channel.name == name:
            if len(channel.values) != count:
                raise ValueError(f"channel {name!r} length {len(channel.values)} != point count {count}")
            return list(channel.values)
    return [float(default)] * count


def _finite(value: float) -> bool:
    return value == value and abs(value) < float("inf")


def write_stats(path: Path, summary: dict[str, object], rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    summary_path = path.with_name(path.stem + "_summary.csv")
    with summary_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(summary.keys()))
        writer.writeheader()
        writer.writerow(summary)
    fieldnames = [
        "target_frame_index",
        "target_stamp",
        "source_frame_index",
        "source_stamp",
        "feature_id",
        "source_code",
        "dt_s",
    ]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


if __name__ == "__main__":
    raise SystemExit(main())
