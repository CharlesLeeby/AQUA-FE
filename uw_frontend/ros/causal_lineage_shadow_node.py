#!/usr/bin/env python3
"""Online causal learned-lineage selector and ROS shadow postprocessor."""

from __future__ import annotations

import argparse
import copy
import csv
import math
import statistics
from dataclasses import dataclass, field
from itertools import zip_longest
from pathlib import Path

import rosbag
from sensor_msgs.msg import ChannelFloat32, PointCloud


LEARNED_SOURCE_CODES = {10, 20, 30}


@dataclass(frozen=True)
class ShadowConfig:
    source_code: int = 20
    min_observations: int = 5
    rank_observations: int = 5
    min_distance_px: float = 40.0
    min_motion_ratio: float = 0.6
    max_motion_ratio: float = 1.5
    max_lineages: int = 1
    remap_id_base: int = 10_000_000
    ignore_zero_base_speeds: bool = False
    rearm_absent_frames: int = 0


@dataclass
class _LineageState:
    count: int = 0
    distances: list[float] = field(default_factory=list)
    motion_ratios: list[float] = field(default_factory=list)


class CausalLineageShadow:
    def __init__(self, config: ShadowConfig) -> None:
        self.config = config
        self.frame_index = 0
        self.lineages: dict[int, _LineageState] = {}
        self.evaluated_ids: set[int] = set()
        self.selected_ids: set[int] = set()
        self.active_ids: set[int] = set()
        self.admissible_ids: set[int] = set()
        self.last_seen_frames: dict[int, int] = {}
        self.activation_frames: dict[int, int] = {}
        self.scores: dict[int, float] = {}
        self.motion_ratios: dict[int, float] = {}
        self.id_map: dict[int, int] = {}

    def process(self, base: PointCloud, sidecar: PointCloud) -> tuple[PointCloud, dict[str, object]]:
        base_pixels = _pixels(base)
        base_speed = _median_speed(
            base,
            ignore_zeros=self.config.ignore_zero_base_speeds,
        )
        count = len(sidecar.points)
        ids = _channel_values(sidecar, "id", count, -1.0)
        source = _channel_values(sidecar, "source_code", count, 0.0)
        learned = _channel_values(sidecar, "is_learned", count, 0.0)
        p_u = _channel_values(sidecar, "p_u", count, float("nan"))
        p_v = _channel_values(sidecar, "p_v", count, float("nan"))
        velocity_x = _channel_values(sidecar, "velocity_x", count, float("nan"))
        velocity_y = _channel_values(sidecar, "velocity_y", count, float("nan"))

        discovered: list[int] = []
        for index in range(count):
            feature_id = _safe_int(ids[index], -1)
            source_code = _safe_int(source[index], 0)
            is_seed = (
                bool(round(float(learned[index])))
                or source_code in LEARNED_SOURCE_CODES
                or feature_id >= self.config.remap_id_base
            )
            if not is_seed or source_code != self.config.source_code:
                continue
            if feature_id not in self.lineages:
                self.lineages[feature_id] = _LineageState()
                discovered.append(feature_id)

        seen: set[int] = set()
        for index in range(count):
            feature_id = _safe_int(ids[index], -1)
            state = self.lineages.get(feature_id)
            if state is None or feature_id in seen:
                continue
            seen.add(feature_id)
            self.last_seen_frames[feature_id] = self.frame_index
            state.count += 1
            u, v = float(p_u[index]), float(p_v[index])
            if (
                len(state.distances) < self.config.rank_observations
                and base_pixels
                and math.isfinite(u)
                and math.isfinite(v)
            ):
                state.distances.append(
                    min(math.hypot(u - bu, v - bv) for bu, bv in base_pixels)
                )
            vx, vy = float(velocity_x[index]), float(velocity_y[index])
            if (
                len(state.motion_ratios) < self.config.rank_observations
                and base_speed is not None
                and base_speed > 1e-9
                and math.isfinite(vx)
                and math.isfinite(vy)
            ):
                state.motion_ratios.append(math.hypot(vx, vy) / base_speed)

        novelty_ready: list[int] = []
        motion_ok: dict[int, bool] = {}
        evaluated_now: list[int] = []
        for feature_id in sorted(seen):
            if feature_id in self.evaluated_ids:
                continue
            state = self.lineages[feature_id]
            if state.count < self.config.min_observations:
                continue
            if len(state.distances) < self.config.rank_observations:
                continue
            if len(state.motion_ratios) < self.config.rank_observations:
                continue
            score = float(statistics.median(state.distances[: self.config.rank_observations]))
            ratio = float(statistics.median(state.motion_ratios[: self.config.rank_observations]))
            self.scores[feature_id] = score
            self.motion_ratios[feature_id] = ratio
            self.evaluated_ids.add(feature_id)
            evaluated_now.append(feature_id)
            motion_ok[feature_id] = self.config.min_motion_ratio <= ratio <= self.config.max_motion_ratio
            if score >= self.config.min_distance_px:
                novelty_ready.append(feature_id)

        activated: list[int] = []
        retired: list[int] = []
        if self.config.rearm_absent_frames > 0:
            for feature_id in sorted(self.active_ids):
                last_seen = self.last_seen_frames.get(feature_id, -1)
                if self.frame_index - last_seen >= self.config.rearm_absent_frames:
                    self.active_ids.remove(feature_id)
                    retired.append(feature_id)
            self.admissible_ids.update(
                feature_id
                for feature_id in novelty_ready
                if motion_ok[feature_id]
            )
            remaining = max(0, self.config.max_lineages - len(self.active_ids))
            candidates = sorted(
                (
                    feature_id
                    for feature_id in self.admissible_ids
                    if feature_id in seen and feature_id not in self.active_ids
                ),
                key=lambda feature_id: (-self.scores[feature_id], feature_id),
            )
            for feature_id in candidates[:remaining]:
                self.active_ids.add(feature_id)
                self.selected_ids.add(feature_id)
                self.activation_frames.setdefault(feature_id, self.frame_index)
                activated.append(feature_id)
        elif novelty_ready:
            remaining = max(0, self.config.max_lineages - len(self.selected_ids))
            ranked = sorted(novelty_ready, key=lambda feature_id: (-self.scores[feature_id], feature_id))
            for feature_id in ranked[:remaining]:
                if not motion_ok[feature_id]:
                    continue
                self.selected_ids.add(feature_id)
                self.activation_frames[feature_id] = self.frame_index
                activated.append(feature_id)

        injection_ids = (
            self.active_ids
            if self.config.rearm_absent_frames > 0
            else self.selected_ids
        )
        selected_indices = [
            index
            for index, raw_id in enumerate(ids)
            if _safe_int(raw_id, -1) in injection_ids
        ]
        merged = _merge(base, sidecar, selected_indices, self.id_map, self.config.remap_id_base)
        decision = {
            "frame_index": self.frame_index,
            "stamp": float(base.header.stamp.to_sec()),
            "discovered_ids": _join_ids(discovered),
            "evaluated_ids": _join_ids(evaluated_now),
            "activated_ids": _join_ids(activated),
            "retired_ids": _join_ids(retired),
            "active_ids": _join_ids(sorted(injection_ids)),
            "selected_ids": _join_ids(sorted(self.selected_ids)),
            "injected_observations": len(selected_indices),
        }
        self.frame_index += 1
        return merged, decision


def _merge(
    base: PointCloud,
    sidecar: PointCloud,
    indices: list[int],
    id_map: dict[int, int],
    remap_id_base: int,
) -> PointCloud:
    output = copy.deepcopy(base)
    output.points = list(output.points)
    for channel in output.channels:
        channel.values = list(channel.values)
    channel_map = {channel.name: channel for channel in output.channels}
    sidecar_channels = {channel.name: channel for channel in sidecar.channels}
    sidecar_ids = _channel_values(sidecar, "id", len(sidecar.points), -1.0)
    existing_count = len(output.points)
    for index in indices:
        output.points.append(copy.deepcopy(sidecar.points[index]))
        feature_id = _safe_int(sidecar_ids[index], -1)
        if feature_id not in id_map:
            id_map[feature_id] = remap_id_base + len(id_map)
        for name, source_channel in sidecar_channels.items():
            if name not in channel_map:
                target = ChannelFloat32(name=name)
                target.values = [0.0] * existing_count
                output.channels.append(target)
                channel_map[name] = target
            value = float(source_channel.values[index])
            if name == "id":
                value = float(id_map[feature_id])
            elif name == "is_learned":
                value = 1.0
            channel_map[name].values.append(value)
    expected = len(output.points)
    for channel in output.channels:
        if len(channel.values) < expected:
            channel.values.extend([0.0] * (expected - len(channel.values)))
    return output


def _pixels(msg: PointCloud) -> list[tuple[float, float]]:
    count = len(msg.points)
    p_u = _channel_values(msg, "p_u", count, float("nan"))
    p_v = _channel_values(msg, "p_v", count, float("nan"))
    return [
        (float(u), float(v))
        for u, v in zip(p_u, p_v)
        if math.isfinite(float(u)) and math.isfinite(float(v))
    ]


def _median_speed(msg: PointCloud, *, ignore_zeros: bool = False) -> float | None:
    count = len(msg.points)
    vx = _channel_values(msg, "velocity_x", count, float("nan"))
    vy = _channel_values(msg, "velocity_y", count, float("nan"))
    speeds = []
    for x, y in zip(vx, vy):
        if not math.isfinite(float(x)) or not math.isfinite(float(y)):
            continue
        speed = math.hypot(float(x), float(y))
        if ignore_zeros and speed <= 1e-9:
            continue
        speeds.append(speed)
    return float(statistics.median(speeds)) if speeds else None


def _channel_values(msg: PointCloud, name: str, count: int, default: float) -> list[float]:
    for channel in msg.channels:
        if channel.name == name:
            if len(channel.values) != count:
                raise ValueError(f"channel {name!r} length mismatch")
            return list(channel.values)
    return [float(default)] * count


def _safe_int(value: object, default: int) -> int:
    try:
        return int(round(float(value)))
    except (TypeError, ValueError, OverflowError):
        return default


def _join_ids(values: list[int] | set[int]) -> str:
    return ";".join(str(value) for value in values)


def run_bag(args: argparse.Namespace) -> int:
    selector = CausalLineageShadow(_config_from_args(args))
    base_messages = _feature_messages(Path(args.base_bag), args.base_topic)
    sidecar_messages = _feature_messages(Path(args.sidecar_bag), args.sidecar_topic)
    merged_messages: list[PointCloud] = []
    decisions: list[dict[str, object]] = []
    for pair_index, pair in enumerate(zip_longest(base_messages, sidecar_messages)):
        base_msg, sidecar_msg = pair
        if base_msg is None or sidecar_msg is None:
            raise ValueError("base and sidecar feature-frame counts differ")
        delta = abs(base_msg.header.stamp.to_sec() - sidecar_msg.header.stamp.to_sec())
        if delta > args.match_tolerance:
            raise ValueError(f"feature frame {pair_index} timestamp delta {delta:.6f}s")
        merged, decision = selector.process(base_msg, sidecar_msg)
        merged_messages.append(merged)
        decisions.append(decision)

    output_path = Path(args.output_bag)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    feature_index = 0
    with rosbag.Bag(str(args.base_bag), "r") as source, rosbag.Bag(str(output_path), "w") as output:
        for topic, msg, stamp in source.read_messages():
            if topic == args.base_topic:
                msg = merged_messages[feature_index]
                feature_index += 1
            output.write(topic, msg, stamp)
    _write_decisions(Path(args.stats_csv), decisions)
    print(
        f"frames={len(decisions)} selected={_join_ids(sorted(selector.selected_ids))} "
        f"injected={sum(int(row['injected_observations']) for row in decisions)}"
    )
    return 0


def _feature_messages(path: Path, topic: str) -> list[PointCloud]:
    with rosbag.Bag(str(path), "r") as bag:
        return [msg for _topic, msg, _stamp in bag.read_messages(topics=[topic])]


def _write_decisions(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]) if rows else ["frame_index"])
        writer.writeheader()
        writer.writerows(rows)


def run_ros(args: argparse.Namespace) -> int:
    import message_filters
    import rospy

    selector = CausalLineageShadow(_config_from_args(args))
    publisher = rospy.Publisher(args.output_topic, PointCloud, queue_size=10)

    def callback(base_msg: PointCloud, sidecar_msg: PointCloud) -> None:
        merged, _decision = selector.process(base_msg, sidecar_msg)
        publisher.publish(merged)

    rospy.init_node("causal_lineage_shadow")
    base_sub = message_filters.Subscriber(args.base_topic, PointCloud)
    sidecar_sub = message_filters.Subscriber(args.sidecar_topic, PointCloud)
    synchronizer = message_filters.ApproximateTimeSynchronizer(
        [base_sub, sidecar_sub], queue_size=args.sync_queue, slop=args.match_tolerance
    )
    synchronizer.registerCallback(callback)
    rospy.spin()
    return 0


def _config_from_args(args: argparse.Namespace) -> ShadowConfig:
    return ShadowConfig(
        source_code=args.source_code,
        min_observations=args.min_observations,
        rank_observations=args.rank_observations,
        min_distance_px=args.min_distance_px,
        min_motion_ratio=args.min_motion_ratio,
        max_motion_ratio=args.max_motion_ratio,
        max_lineages=args.max_lineages,
        remap_id_base=args.remap_id_base,
        ignore_zero_base_speeds=args.ignore_zero_base_speeds,
        rearm_absent_frames=args.rearm_absent_frames,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="mode", required=True)
    for name in ("bag", "ros"):
        child = subparsers.add_parser(name)
        child.add_argument("--base-topic", default="/feature_tracker/base")
        child.add_argument("--sidecar-topic", default="/feature_tracker/sidecar")
        child.add_argument("--source-code", type=int, default=20)
        child.add_argument("--min-observations", type=int, default=5)
        child.add_argument("--rank-observations", type=int, default=5)
        child.add_argument("--min-distance-px", type=float, default=40.0)
        child.add_argument("--min-motion-ratio", type=float, default=0.6)
        child.add_argument("--max-motion-ratio", type=float, default=1.5)
        child.add_argument("--max-lineages", type=int, default=1)
        child.add_argument("--remap-id-base", type=int, default=10_000_000)
        child.add_argument("--ignore-zero-base-speeds", action="store_true")
        child.add_argument(
            "--rearm-absent-frames",
            type=int,
            default=0,
            help=(
                "Release an active lineage slot after this many consecutive "
                "absent frames; 0 preserves the cumulative lineage cap."
            ),
        )
        child.add_argument("--match-tolerance", type=float, default=0.02)
    bag = subparsers.choices["bag"]
    bag.add_argument("--base-bag", required=True)
    bag.add_argument("--sidecar-bag", required=True)
    bag.add_argument("--output-bag", required=True)
    bag.add_argument("--stats-csv", required=True)
    ros = subparsers.choices["ros"]
    ros.add_argument("--output-topic", default="/feature_tracker/feature")
    ros.add_argument("--sync-queue", type=int, default=20)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    return run_bag(args) if args.mode == "bag" else run_ros(args)


if __name__ == "__main__":
    raise SystemExit(main())
