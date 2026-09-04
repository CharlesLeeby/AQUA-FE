#!/usr/bin/env python3
"""Online adaptive KLT candidate-pool merger for VINS PointCloud features.

The node keeps the normal VINS frontend as the base stream.  A denser KLT
stream stays hidden until both the base tracks collapse and DVL support is
weak.  Candidate tracks are admitted slowly into a fixed backend budget.
"""

from __future__ import annotations

import argparse
import bisect
import copy
import csv
import json
import math
import threading
from collections import deque
from dataclasses import dataclass
from itertools import zip_longest
from pathlib import Path

import numpy as np
import rosbag
from sensor_msgs.msg import PointCloud


FEATURE_ID_NAMES = ("feature_id", "id")
U_NAMES = ("u", "p_u")
V_NAMES = ("v", "p_v")
FLOAT32_EXACT_INT_LIMIT = 16_777_216


@dataclass(frozen=True)
class PoolConfig:
    backend_cap: int = 180
    max_rescue_tracks: int = 8
    max_new_rescue_per_frame: int = 1
    candidate_min_age: int = 3
    mature_age: int = 4
    min_separation_px: float = 8.0
    enable_after_rel_sec: float = 30.0
    enter_overlap: int = 80
    enter_mature: int = 40
    enter_frames: int = 3
    exit_overlap: int = 120
    exit_mature: int = 80
    exit_frames: int = 10
    min_rescue_frames: int = 20
    remap_id_base: int = 5_000_000


class TrackAger:
    def __init__(self) -> None:
        self.ages: dict[int, int] = {}
        self.previous_ids: set[int] = set()

    def update(self, ids: list[int]) -> tuple[dict[int, int], int, bool]:
        current = set(ids)
        overlap = len(current & self.previous_ids) if self.previous_ids else 0
        reset = (
            len(current) >= 20
            and len(self.previous_ids) >= 20
            and overlap / float(min(len(current), len(self.previous_ids))) < 0.05
        )
        if reset:
            self.ages.clear()
            overlap = 0
        self.ages = {
            feature_id: self.ages.get(feature_id, 0) + 1
            for feature_id in current
        }
        self.previous_ids = current
        return dict(self.ages), overlap, reset


class DvlSupportGate:
    """Bounded, causal proxy for backend DVL interval coverage.

    In ROS mode only samples already delivered to this object can be used.
    The timestamp tolerance mirrors the backend's t1+0.1 support window.
    """

    def __init__(self, tolerance_sec: float = 0.10, history_sec: float = 10.0) -> None:
        self.tolerance_sec = float(tolerance_sec)
        self.history_sec = float(history_sec)
        self._valid_stamps: deque[float] = deque()
        self._latest_stamp: float | None = None
        self._lock = threading.Lock()

    def observe(self, stamp: float, valid: bool) -> None:
        stamp = float(stamp)
        if not math.isfinite(stamp):
            return
        with self._lock:
            if self._latest_stamp is not None and stamp < self._latest_stamp - 1.0:
                self._valid_stamps.clear()
            self._latest_stamp = stamp
            if valid:
                self._valid_stamps.append(stamp)
            cutoff = stamp - self.history_sec
            while self._valid_stamps and self._valid_stamps[0] < cutoff:
                self._valid_stamps.popleft()

    def query(self, feature_stamp: float) -> tuple[bool, float | None]:
        with self._lock:
            stamps = list(self._valid_stamps)
        if not stamps:
            return True, None
        index = bisect.bisect_left(stamps, feature_stamp)
        distances = [
            abs(stamps[i] - feature_stamp)
            for i in (index - 1, index)
            if 0 <= i < len(stamps)
        ]
        distance = min(distances) if distances else None
        weak = distance is None or distance > self.tolerance_sec
        return weak, distance


class AdaptiveCandidatePool:
    def __init__(self, config: PoolConfig) -> None:
        if config.backend_cap <= 0:
            raise ValueError("backend_cap must be positive")
        if config.remap_id_base <= 0 or config.remap_id_base >= FLOAT32_EXACT_INT_LIMIT:
            raise ValueError("remap_id_base is outside the exact float32 integer range")
        self.config = config
        self.base_ager = TrackAger()
        self.candidate_ager = TrackAger()
        self.candidate_id_map: dict[int, int] = {}
        self.active_candidate_ids: set[int] = set()
        self.first_stamp: float | None = None
        self.frame_index = 0
        self.rescue = False
        self.enter_count = 0
        self.exit_count = 0
        self.rescue_age = 0

    def process(
        self,
        base: PointCloud,
        candidate: PointCloud,
        *,
        dvl_weak: bool,
        dvl_support_distance: float | None = None,
    ) -> tuple[PointCloud, dict[str, object]]:
        cfg = self.config
        stamp = float(base.header.stamp.to_sec())
        candidate_stamp = float(candidate.header.stamp.to_sec())
        if abs(stamp - candidate_stamp) > 0.02:
            raise ValueError(
                f"base/candidate timestamp mismatch: {stamp:.9f} vs {candidate_stamp:.9f}"
            )
        if self.first_stamp is None or stamp < self.first_stamp - 1.0:
            self.first_stamp = stamp
        rel_sec = stamp - self.first_stamp

        base_ids = feature_ids(base)
        candidate_ids = feature_ids(candidate)
        base_ages, base_overlap, base_reset = self.base_ager.update(base_ids)
        candidate_ages, _candidate_overlap, candidate_reset = self.candidate_ager.update(
            candidate_ids
        )
        if candidate_reset:
            self.active_candidate_ids.clear()
            self.candidate_id_map.clear()

        base_mature = sum(
            base_ages[feature_id] >= cfg.mature_age for feature_id in base_ids
        )
        enabled = rel_sec >= cfg.enable_after_rel_sec and not base_reset and dvl_weak
        enter_bad = base_overlap < cfg.enter_overlap and base_mature < cfg.enter_mature
        exit_good = base_overlap >= cfg.exit_overlap and base_mature >= cfg.exit_mature
        if not self.rescue:
            self.enter_count = self.enter_count + 1 if enabled and enter_bad else 0
            if self.enter_count >= cfg.enter_frames:
                self.rescue = True
                self.rescue_age = 0
                self.exit_count = 0
        else:
            self.rescue_age += 1
            self.exit_count = self.exit_count + 1 if exit_good else 0
            if not dvl_weak or (
                self.rescue_age >= cfg.min_rescue_frames
                and self.exit_count >= cfg.exit_frames
            ):
                self.rescue = False
                self.active_candidate_ids.clear()
                self.enter_count = 0
                self.exit_count = 0

        base_points = pixels(base)
        candidate_points = pixels(candidate)
        candidate_index = {
            feature_id: index for index, feature_id in enumerate(candidate_ids)
        }
        selected_candidate_ids: list[int] = []
        retired_candidate_count = 0
        new_candidate_count = 0

        if self.rescue:
            previous_active_count = len(self.active_candidate_ids)
            self.active_candidate_ids.intersection_update(candidate_index)
            retired_candidate_count = previous_active_count - len(
                self.active_candidate_ids
            )
            selected_candidate_ids.extend(
                sorted(
                    self.active_candidate_ids,
                    key=lambda feature_id: (-candidate_ages[feature_id], feature_id),
                )
            )
            references = base_points.copy()
            if selected_candidate_ids:
                references = np.vstack(
                    [
                        references,
                        candidate_points[
                            [candidate_index[x] for x in selected_candidate_ids]
                        ],
                    ]
                )
            candidate_order = sorted(
                (
                    feature_id
                    for feature_id in candidate_ids
                    if feature_id not in self.active_candidate_ids
                    and candidate_ages[feature_id] >= cfg.candidate_min_age
                ),
                key=lambda feature_id: (-candidate_ages[feature_id], feature_id),
            )
            for feature_id in candidate_order:
                if len(selected_candidate_ids) >= cfg.max_rescue_tracks:
                    break
                if new_candidate_count >= cfg.max_new_rescue_per_frame:
                    break
                index = candidate_index[feature_id]
                if not spatially_novel(
                    candidate_points[index], references, cfg.min_separation_px
                ):
                    continue
                selected_candidate_ids.append(feature_id)
                self.active_candidate_ids.add(feature_id)
                new_candidate_count += 1
                references = np.vstack([references, candidate_points[index]])

        selected_candidate_ids = selected_candidate_ids[
            : min(cfg.max_rescue_tracks, cfg.backend_cap)
        ]
        candidate_indices = [
            candidate_index[feature_id] for feature_id in selected_candidate_ids
        ]
        base_budget = max(0, cfg.backend_cap - len(candidate_indices))
        base_indices = sorted(
            range(len(base_ids)),
            key=lambda index: (-base_ages[base_ids[index]], index),
        )[:base_budget]
        base_indices.sort()
        output = subset_and_merge(
            base,
            candidate,
            base_indices,
            candidate_indices,
            self.candidate_id_map,
            cfg.remap_id_base,
        )
        decision = {
            "frame_index": self.frame_index,
            "stamp": f"{stamp:.9f}",
            "rel_sec": f"{rel_sec:.6f}",
            "rescue": int(self.rescue),
            "base_overlap": base_overlap,
            "base_mature": base_mature,
            "base_count": len(base_ids),
            "candidate_count": len(candidate_ids),
            "admitted_candidate": len(candidate_indices),
            "new_candidate": new_candidate_count,
            "retired_candidate": retired_candidate_count,
            "admitted_base": len(base_indices),
            "output_count": len(output.points),
            "dvl_weak": int(dvl_weak),
            "dvl_support_distance": (
                "" if dvl_support_distance is None else f"{dvl_support_distance:.6f}"
            ),
            "enter_count": self.enter_count,
            "exit_count": self.exit_count,
        }
        self.frame_index += 1
        return output, decision


def channel(msg: PointCloud, aliases: tuple[str, ...]) -> list[float]:
    for name in aliases:
        for item in msg.channels:
            if item.name == name:
                if len(item.values) != len(msg.points):
                    raise ValueError(f"channel {name!r} length mismatch")
                return list(item.values)
    raise ValueError(f"none of the required channels {aliases!r} is present")


def feature_ids(msg: PointCloud) -> list[int]:
    return [int(round(float(value))) for value in channel(msg, FEATURE_ID_NAMES)]


def pixels(msg: PointCloud) -> np.ndarray:
    return np.column_stack([channel(msg, U_NAMES), channel(msg, V_NAMES)]).astype(
        np.float64
    )


def spatially_novel(
    point: np.ndarray, references: np.ndarray, min_distance: float
) -> bool:
    if len(references) == 0:
        return True
    delta = references - point.reshape(1, 2)
    return bool(
        np.all(
            np.einsum("ij,ij->i", delta, delta) >= min_distance * min_distance
        )
    )


def subset_and_merge(
    base: PointCloud,
    candidate: PointCloud,
    base_indices: list[int],
    candidate_indices: list[int],
    candidate_id_map: dict[int, int],
    remap_id_base: int,
) -> PointCloud:
    output = copy.deepcopy(base)
    output.points = [copy.deepcopy(base.points[index]) for index in base_indices]
    base_channels = {item.name: item for item in base.channels}
    candidate_channels = {item.name: item for item in candidate.channels}
    candidate_ids = feature_ids(candidate)
    for item in output.channels:
        item.values = [float(base_channels[item.name].values[i]) for i in base_indices]
    output_channels = {item.name: item for item in output.channels}

    def candidate_source(name: str):
        source = candidate_channels.get(name)
        if source is not None:
            return source
        aliases = FEATURE_ID_NAMES if name in FEATURE_ID_NAMES else ()
        aliases = U_NAMES if name in U_NAMES else aliases
        aliases = V_NAMES if name in V_NAMES else aliases
        return next(
            (candidate_channels[alias] for alias in aliases if alias in candidate_channels),
            None,
        )

    for index in candidate_indices:
        output.points.append(copy.deepcopy(candidate.points[index]))
        raw_id = candidate_ids[index]
        mapped_id = candidate_id_map.get(raw_id)
        if mapped_id is None:
            mapped_id = remap_id_base + len(candidate_id_map)
            if mapped_id >= FLOAT32_EXACT_INT_LIMIT:
                raise ValueError("candidate feature id exceeds exact float32 integer range")
            candidate_id_map[raw_id] = mapped_id
        for name, target in output_channels.items():
            source = candidate_source(name)
            value = float(source.values[index]) if source is not None else 0.0
            if name in FEATURE_ID_NAMES:
                value = float(mapped_id)
            target.values.append(value)
    return output


def config_from_args(args: argparse.Namespace) -> PoolConfig:
    names = PoolConfig.__dataclass_fields__.keys()
    return PoolConfig(**{name: getattr(args, name) for name in names})


def feature_messages(path: Path, topic: str) -> list[PointCloud]:
    with rosbag.Bag(str(path), "r") as bag:
        return [msg for _topic, msg, _stamp in bag.read_messages(topics=[topic])]


def run_bag(args: argparse.Namespace) -> int:
    pool = AdaptiveCandidatePool(config_from_args(args))
    gate = DvlSupportGate(args.dvl_support_tolerance_sec, history_sec=1e9)
    dvl_samples: list[tuple[float, bool]] = []
    with rosbag.Bag(args.dvl_bag, "r") as bag:
        for _topic, msg, _stamp in bag.read_messages(topics=[args.dvl_topic]):
            dvl_samples.append((float(msg.header.stamp.to_sec()), bool(msg.velocity_valid)))

    base_messages = feature_messages(Path(args.base_bag), args.base_topic)
    candidate_messages = feature_messages(Path(args.candidate_bag), args.candidate_topic)
    output_messages: list[PointCloud] = []
    decisions: list[dict[str, object]] = []
    dvl_index = 0
    for frame_index, pair in enumerate(zip_longest(base_messages, candidate_messages)):
        base, candidate = pair
        if base is None or candidate is None:
            raise ValueError("base and candidate feature-frame counts differ")
        available_t = base.header.stamp.to_sec() + args.dvl_available_lead_sec
        while dvl_index < len(dvl_samples) and dvl_samples[dvl_index][0] <= available_t:
            gate.observe(*dvl_samples[dvl_index])
            dvl_index += 1
        weak, distance = gate.query(base.header.stamp.to_sec())
        output, decision = pool.process(
            base, candidate, dvl_weak=weak, dvl_support_distance=distance
        )
        output_messages.append(output)
        decisions.append(decision)

    output_path = Path(args.output_bag)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    feature_index = 0
    with rosbag.Bag(args.base_bag, "r") as source, rosbag.Bag(
        str(output_path), "w", compression=rosbag.Compression.LZ4
    ) as output:
        for topic, msg, stamp in source.read_messages():
            if topic == args.base_topic:
                msg = output_messages[feature_index]
                feature_index += 1
            output.write(topic, msg, stamp)
    stats_path = Path(args.stats_csv)
    stats_path.parent.mkdir(parents=True, exist_ok=True)
    with stats_path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(decisions[0]))
        writer.writeheader()
        writer.writerows(decisions)
    rescue_rows = [row for row in decisions if int(row["rescue"])]
    print(
        json.dumps(
            {
                "frames": len(decisions),
                "rescue_frames": len(rescue_rows),
                "first_rescue_rel_sec": (
                    float(rescue_rows[0]["rel_sec"]) if rescue_rows else None
                ),
                "last_rescue_rel_sec": (
                    float(rescue_rows[-1]["rel_sec"]) if rescue_rows else None
                ),
                "max_admitted_candidate": max(
                    (int(row["admitted_candidate"]) for row in decisions), default=0
                ),
            },
            indent=2,
        )
    )
    return 0


def run_ros(args: argparse.Namespace) -> int:
    import message_filters
    import rospy
    from dvl_msgs.msg import DvlData
    from std_msgs.msg import String

    pool = AdaptiveCandidatePool(config_from_args(args))
    gate = DvlSupportGate(args.dvl_support_tolerance_sec)
    publisher = rospy.Publisher(args.output_topic, PointCloud, queue_size=10)
    decision_publisher = rospy.Publisher(args.decision_topic, String, queue_size=10)

    def dvl_callback(msg: DvlData) -> None:
        gate.observe(msg.header.stamp.to_sec(), bool(msg.velocity_valid))

    def feature_callback(base: PointCloud, candidate: PointCloud) -> None:
        weak, distance = gate.query(base.header.stamp.to_sec())
        output, decision = pool.process(
            base, candidate, dvl_weak=weak, dvl_support_distance=distance
        )
        publisher.publish(output)
        decision_publisher.publish(String(data=json.dumps(decision, separators=(",", ":"))))

    rospy.init_node("adaptive_klt_candidate_pool")
    rospy.Subscriber(args.dvl_topic, DvlData, dvl_callback, queue_size=200)
    # Keep the transport queues as deep as the synchronizer queue.  The
    # default rospy queue is too small for accelerated rosbag validation and
    # can drop one half of an otherwise exact timestamp pair.
    base_sub = message_filters.Subscriber(
        args.base_topic, PointCloud, queue_size=args.sync_queue
    )
    candidate_sub = message_filters.Subscriber(
        args.candidate_topic, PointCloud, queue_size=args.sync_queue
    )
    synchronizer = message_filters.ApproximateTimeSynchronizer(
        [base_sub, candidate_sub],
        queue_size=args.sync_queue,
        slop=args.match_tolerance_sec,
    )
    synchronizer.registerCallback(feature_callback)
    rospy.spin()
    return 0


def add_common_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--base-topic", default="/feature_tracker/base")
    parser.add_argument("--candidate-topic", default="/feature_tracker/candidate")
    parser.add_argument("--dvl-topic", default="/dvl/data")
    parser.add_argument("--backend-cap", type=int, default=180)
    parser.add_argument("--max-rescue-tracks", type=int, default=8)
    parser.add_argument("--max-new-rescue-per-frame", type=int, default=1)
    parser.add_argument("--candidate-min-age", type=int, default=3)
    parser.add_argument("--mature-age", type=int, default=4)
    parser.add_argument("--min-separation-px", type=float, default=8.0)
    parser.add_argument("--enable-after-rel-sec", type=float, default=30.0)
    parser.add_argument("--enter-overlap", type=int, default=80)
    parser.add_argument("--enter-mature", type=int, default=40)
    parser.add_argument("--enter-frames", type=int, default=3)
    parser.add_argument("--exit-overlap", type=int, default=120)
    parser.add_argument("--exit-mature", type=int, default=80)
    parser.add_argument("--exit-frames", type=int, default=10)
    parser.add_argument("--min-rescue-frames", type=int, default=20)
    parser.add_argument("--remap-id-base", type=int, default=5_000_000)
    parser.add_argument("--dvl-support-tolerance-sec", type=float, default=0.10)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_subparsers(dest="mode", required=True)
    bag = modes.add_parser("bag")
    ros = modes.add_parser("ros")
    add_common_args(bag)
    add_common_args(ros)
    bag.add_argument("--base-bag", required=True)
    bag.add_argument("--candidate-bag", required=True)
    bag.add_argument("--dvl-bag", required=True)
    bag.add_argument("--output-bag", required=True)
    bag.add_argument("--stats-csv", required=True)
    bag.add_argument(
        "--dvl-available-lead-sec",
        type=float,
        default=0.0,
        help="DVL header lead already available when a feature callback occurs.",
    )
    ros.add_argument("--output-topic", default="/feature_tracker/feature")
    ros.add_argument("--decision-topic", default="/aqua_fe/adaptive_klt_decision")
    ros.add_argument("--sync-queue", type=int, default=30)
    ros.add_argument("--match-tolerance-sec", type=float, default=0.02)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    return run_bag(args) if args.mode == "bag" else run_ros(args)


if __name__ == "__main__":
    raise SystemExit(main())
