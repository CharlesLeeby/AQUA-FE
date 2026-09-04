#!/usr/bin/env python3
"""Build a causal VINS feature bag with a hidden dense KLT candidate pool.

The base feature bag is passed through unchanged while it is healthy.  After
the warm-up interval, sustained base-track collapse activates rescue mode.
Mature, spatially novel tracks from a denser candidate bag then replace the
youngest base observations, while the backend-facing message remains capped.
No future observations are used by the admission decision.
"""

from __future__ import annotations

import argparse
import copy
import csv
import json
import math
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import rosbag


FEATURE_ID_NAMES = ("feature_id", "id")
U_NAMES = ("u", "p_u")
V_NAMES = ("v", "p_v")
FLOAT32_EXACT_INT_LIMIT = 16_777_216


@dataclass
class TrackAger:
    ages: dict[int, int]
    previous_ids: set[int]

    def __init__(self) -> None:
        self.ages = {}
        self.previous_ids = set()

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
        self.ages = {feature_id: self.ages.get(feature_id, 0) + 1 for feature_id in current}
        self.previous_ids = current
        return dict(self.ages), overlap, reset


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-bag", type=Path, required=True)
    parser.add_argument("--candidate-bag", type=Path, required=True)
    parser.add_argument("--output-bag", type=Path, required=True)
    parser.add_argument("--stats-csv", type=Path, required=True)
    parser.add_argument("--receipt-json", type=Path, required=True)
    parser.add_argument("--feature-topic", default="/feature_tracker/feature")
    parser.add_argument("--backend-cap", type=int, default=180)
    # Conservative defaults selected by the 172529 paired backend probe. A
    # larger batch helped feature counts more, but perturbed the estimator
    # after DVL recovered; slow admission preserved the no-harm behavior.
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
    parser.add_argument("--match-tolerance-sec", type=float, default=1e-6)
    parser.add_argument("--dvl-debug-csv", type=Path)
    parser.add_argument("--require-dvl-weak", action="store_true")
    parser.add_argument("--dvl-weak-coverage-max", type=float, default=0.5)
    return parser.parse_args()


def channel(msg, aliases: tuple[str, ...]) -> tuple[str, list[float]]:
    for name in aliases:
        for item in msg.channels:
            if item.name == name:
                if len(item.values) != len(msg.points):
                    raise ValueError(f"channel {name!r} length mismatch")
                return name, list(item.values)
    raise ValueError(f"none of the required channels {aliases!r} is present")


def feature_ids(msg) -> tuple[str, list[int]]:
    name, values = channel(msg, FEATURE_ID_NAMES)
    return name, [int(round(float(value))) for value in values]


def pixels(msg) -> np.ndarray:
    _u_name, u = channel(msg, U_NAMES)
    _v_name, v = channel(msg, V_NAMES)
    return np.column_stack([u, v]).astype(np.float64)


def grid_coverage(points: np.ndarray, rows: int = 6, cols: int = 8) -> float:
    if len(points) == 0:
        return 0.0
    x = np.clip((points[:, 0] / (1280.0 / cols)).astype(int), 0, cols - 1)
    y = np.clip((points[:, 1] / (720.0 / rows)).astype(int), 0, rows - 1)
    return len(set(zip(y.tolist(), x.tolist()))) / float(rows * cols)


def spatially_novel(point: np.ndarray, references: np.ndarray, min_distance: float) -> bool:
    if len(references) == 0:
        return True
    delta = references - point.reshape(1, 2)
    return bool(np.all(np.einsum("ij,ij->i", delta, delta) >= min_distance * min_distance))


def subset_and_merge(
    base,
    candidate,
    base_indices: list[int],
    candidate_indices: list[int],
    candidate_id_map: dict[int, int],
    remap_id_base: int,
):
    output = copy.deepcopy(base)
    output.points = [copy.deepcopy(base.points[index]) for index in base_indices]
    base_channels = {item.name: item for item in base.channels}
    candidate_channels = {item.name: item for item in candidate.channels}
    candidate_id_name, candidate_ids = feature_ids(candidate)

    for item in output.channels:
        source = base_channels[item.name].values
        item.values = [float(source[index]) for index in base_indices]

    output_channels = {item.name: item for item in output.channels}

    def candidate_source(name: str):
        source = candidate_channels.get(name)
        if source is not None:
            return source
        aliases: tuple[str, ...] = ()
        if name in FEATURE_ID_NAMES:
            aliases = FEATURE_ID_NAMES
        elif name in U_NAMES:
            aliases = U_NAMES
        elif name in V_NAMES:
            aliases = V_NAMES
        for alias in aliases:
            source = candidate_channels.get(alias)
            if source is not None:
                return source
        return None

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

    expected = len(output.points)
    for item in output.channels:
        if len(item.values) != expected:
            raise ValueError(f"output channel {item.name!r} length mismatch")
    return output


def load_messages(path: Path, topic: str) -> list[object]:
    with rosbag.Bag(str(path), "r") as bag:
        return [msg for _topic, msg, _stamp in bag.read_messages(topics=[topic])]


def load_dvl_coverage(path: Path | None) -> dict[int, float]:
    if path is None:
        return {}
    result: dict[int, float] = {}
    with path.open(newline="", encoding="utf-8") as stream:
        for row in csv.DictReader(stream):
            try:
                result[int(row["header_stamp_ns"])] = float(row["coverage"])
            except (KeyError, TypeError, ValueError):
                continue
    return result


def main() -> int:
    args = parse_args()
    if (
        args.backend_cap <= 0
        or args.max_rescue_tracks < 0
        or args.max_new_rescue_per_frame < 0
    ):
        raise SystemExit("feature caps must be non-negative and backend cap must be positive")
    if args.remap_id_base <= 0 or args.remap_id_base >= FLOAT32_EXACT_INT_LIMIT:
        raise SystemExit("--remap-id-base must be a positive exactly representable float32 integer")

    base_messages = load_messages(args.base_bag, args.feature_topic)
    candidate_messages = load_messages(args.candidate_bag, args.feature_topic)
    dvl_coverage_by_stamp = load_dvl_coverage(args.dvl_debug_csv)
    if args.require_dvl_weak and not dvl_coverage_by_stamp:
        raise ValueError("--require-dvl-weak needs a non-empty --dvl-debug-csv")
    if len(base_messages) != len(candidate_messages):
        raise ValueError("base and candidate feature-frame counts differ")
    if not base_messages:
        raise ValueError("no feature messages found")

    base_ager = TrackAger()
    candidate_ager = TrackAger()
    candidate_id_map: dict[int, int] = {}
    active_candidate_ids: set[int] = set()
    output_messages: list[object] = []
    rows: list[dict[str, object]] = []
    first_stamp = float(base_messages[0].header.stamp.to_sec())
    rescue = False
    enter_count = 0
    exit_count = 0
    rescue_age = 0

    for frame_index, (base, candidate) in enumerate(zip(base_messages, candidate_messages)):
        stamp = float(base.header.stamp.to_sec())
        candidate_stamp = float(candidate.header.stamp.to_sec())
        if abs(stamp - candidate_stamp) > args.match_tolerance_sec:
            raise ValueError(f"frame {frame_index} timestamp mismatch: {stamp} vs {candidate_stamp}")
        rel_sec = stamp - first_stamp
        dvl_coverage = dvl_coverage_by_stamp.get(base.header.stamp.to_nsec())
        dvl_weak = (
            not args.require_dvl_weak
            or (
                dvl_coverage is not None
                and math.isfinite(dvl_coverage)
                and dvl_coverage < args.dvl_weak_coverage_max
            )
        )

        base_id_name, base_ids = feature_ids(base)
        _candidate_id_name, candidate_ids = feature_ids(candidate)
        base_ages, base_overlap, base_reset = base_ager.update(base_ids)
        candidate_ages, _candidate_overlap, candidate_reset = candidate_ager.update(candidate_ids)
        if candidate_reset:
            active_candidate_ids.clear()
            candidate_id_map.clear()
        base_mature = sum(base_ages[feature_id] >= args.mature_age for feature_id in base_ids)

        enabled = rel_sec >= args.enable_after_rel_sec and not base_reset and dvl_weak
        enter_bad = base_overlap < args.enter_overlap and base_mature < args.enter_mature
        exit_good = base_overlap >= args.exit_overlap and base_mature >= args.exit_mature
        if not rescue:
            enter_count = enter_count + 1 if enabled and enter_bad else 0
            if enter_count >= args.enter_frames:
                rescue = True
                rescue_age = 0
                exit_count = 0
        else:
            rescue_age += 1
            exit_count = exit_count + 1 if exit_good else 0
            dvl_recovered = args.require_dvl_weak and not dvl_weak
            if dvl_recovered or (
                rescue_age >= args.min_rescue_frames and exit_count >= args.exit_frames
            ):
                rescue = False
                active_candidate_ids.clear()
                enter_count = 0
                exit_count = 0

        base_points = pixels(base)
        candidate_points = pixels(candidate)
        candidate_index = {feature_id: index for index, feature_id in enumerate(candidate_ids)}
        selected_candidate_ids: list[int] = []
        retired_candidate_count = 0
        new_candidate_count = 0

        if rescue:
            previous_active_count = len(active_candidate_ids)
            active_candidate_ids.intersection_update(candidate_index)
            retired_candidate_count = previous_active_count - len(active_candidate_ids)
            selected_candidate_ids.extend(
                sorted(active_candidate_ids, key=lambda feature_id: (-candidate_ages[feature_id], feature_id))
            )
            references = base_points.copy()
            if selected_candidate_ids:
                references = np.vstack(
                    [references, candidate_points[[candidate_index[x] for x in selected_candidate_ids]]]
                )
            candidate_order = sorted(
                (
                    feature_id
                    for feature_id in candidate_ids
                    if feature_id not in active_candidate_ids
                    and candidate_ages[feature_id] >= args.candidate_min_age
                ),
                key=lambda feature_id: (-candidate_ages[feature_id], feature_id),
            )
            for feature_id in candidate_order:
                if len(selected_candidate_ids) >= args.max_rescue_tracks:
                    break
                if new_candidate_count >= args.max_new_rescue_per_frame:
                    break
                index = candidate_index[feature_id]
                if not spatially_novel(candidate_points[index], references, args.min_separation_px):
                    continue
                selected_candidate_ids.append(feature_id)
                active_candidate_ids.add(feature_id)
                new_candidate_count += 1
                references = np.vstack([references, candidate_points[index]])

        selected_candidate_ids = selected_candidate_ids[: min(args.max_rescue_tracks, args.backend_cap)]
        candidate_indices = [candidate_index[feature_id] for feature_id in selected_candidate_ids]
        base_budget = max(0, args.backend_cap - len(candidate_indices))
        base_indices = sorted(
            range(len(base_ids)), key=lambda index: (-base_ages[base_ids[index]], index)
        )[:base_budget]
        base_indices.sort()
        output = subset_and_merge(
            base,
            candidate,
            base_indices,
            candidate_indices,
            candidate_id_map,
            args.remap_id_base,
        )
        output_messages.append(output)
        output_points = pixels(output)
        rows.append(
            {
                "frame_index": frame_index,
                "stamp": f"{stamp:.9f}",
                "rel_sec": f"{rel_sec:.6f}",
                "rescue": int(rescue),
                "base_overlap": base_overlap,
                "base_mature": base_mature,
                "base_count": len(base_ids),
                "candidate_mature": sum(
                    candidate_ages[feature_id] >= args.mature_age for feature_id in candidate_ids
                ),
                "candidate_count": len(candidate_ids),
                "admitted_candidate": len(candidate_indices),
                "new_candidate": new_candidate_count,
                "retired_candidate": retired_candidate_count,
                "admitted_base": len(base_indices),
                "output_count": len(output.points),
                "output_grid_coverage": f"{grid_coverage(output_points):.6f}",
                "dvl_coverage": "" if dvl_coverage is None else f"{dvl_coverage:.6f}",
                "dvl_weak": int(dvl_weak),
                "enter_count": enter_count,
                "exit_count": exit_count,
            }
        )

    args.output_bag.parent.mkdir(parents=True, exist_ok=True)
    feature_index = 0
    with rosbag.Bag(str(args.base_bag), "r") as source, rosbag.Bag(
        str(args.output_bag), "w", compression=rosbag.Compression.LZ4
    ) as output:
        for topic, msg, stamp in source.read_messages():
            if topic == args.feature_topic:
                msg = output_messages[feature_index]
                feature_index += 1
            output.write(topic, msg, stamp)

    args.stats_csv.parent.mkdir(parents=True, exist_ok=True)
    with args.stats_csv.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)

    rescue_rows = [row for row in rows if int(row["rescue"]) == 1]
    receipt = {
        "schema": "adaptive_klt_candidate_pool_bag_v1",
        "base_bag": str(args.base_bag.resolve()),
        "candidate_bag": str(args.candidate_bag.resolve()),
        "output_bag": str(args.output_bag.resolve()),
        "feature_topic": args.feature_topic,
        "frame_count": len(rows),
        "first_stamp": first_stamp,
        "last_stamp": float(base_messages[-1].header.stamp.to_sec()),
        "backend_cap": args.backend_cap,
        "max_rescue_tracks": args.max_rescue_tracks,
        "max_new_rescue_per_frame": args.max_new_rescue_per_frame,
        "candidate_min_age": args.candidate_min_age,
        "mature_age": args.mature_age,
        "min_separation_px": args.min_separation_px,
        "require_dvl_weak": bool(args.require_dvl_weak),
        "dvl_debug_csv": (
            str(args.dvl_debug_csv.resolve()) if args.dvl_debug_csv is not None else None
        ),
        "dvl_weak_coverage_max": args.dvl_weak_coverage_max,
        "enable_after_rel_sec": args.enable_after_rel_sec,
        "enter_gate": {
            "overlap_lt": args.enter_overlap,
            "mature_lt": args.enter_mature,
            "frames": args.enter_frames,
        },
        "exit_gate": {
            "overlap_ge": args.exit_overlap,
            "mature_ge": args.exit_mature,
            "frames": args.exit_frames,
            "min_rescue_frames": args.min_rescue_frames,
        },
        "rescue_frame_count": len(rescue_rows),
        "first_rescue_rel_sec": (
            float(rescue_rows[0]["rel_sec"]) if rescue_rows else None
        ),
        "last_rescue_rel_sec": (
            float(rescue_rows[-1]["rel_sec"]) if rescue_rows else None
        ),
        "max_admitted_candidate": max(
            (int(row["admitted_candidate"]) for row in rows), default=0
        ),
        "mean_admitted_candidate_during_rescue": (
            float(np.mean([int(row["admitted_candidate"]) for row in rescue_rows]))
            if rescue_rows
            else 0.0
        ),
    }
    args.receipt_json.parent.mkdir(parents=True, exist_ok=True)
    args.receipt_json.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(receipt, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
