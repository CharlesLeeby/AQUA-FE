#!/usr/bin/env python3
"""Keep learned observations only when seeded by coverage gain.

This diagnostic filter is used to test an online policy:

1. learned observations in frames whose export benefit is
   ``accepted_coverage_gain`` are allowed and their feature ids become seeded;
2. learned observations in continuation frames such as weak-cell rescue are
   allowed only if the same id was already seeded by a previous coverage-gain
   frame;
3. all other learned observations are dropped.

Classical observations and non-feature topics are preserved.
"""

from __future__ import annotations

import argparse
import csv
from pathlib import Path

import rosbag


LEARNED_SOURCE_CODES = {10, 20, 30}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-bag", required=True)
    parser.add_argument("--frontend-metrics", required=True)
    parser.add_argument("--output-bag", required=True)
    parser.add_argument("--stats-csv", required=True)
    parser.add_argument("--feature-topic", default="/feature_tracker/feature")
    parser.add_argument(
        "--continuation-reasons",
        default="accepted_weak_cell_rescue,sidecar_observation_budget_partial,sidecar_observation_budget",
        help="Comma-separated benefit reasons that may keep only seeded learned ids.",
    )
    parser.add_argument(
        "--learned-id-min",
        type=int,
        default=10000000,
        help="Treat ids >= this value as learned when source channels are absent.",
    )
    parser.add_argument(
        "--continuation-max-age",
        type=float,
        default=float("inf"),
        help="Maximum frontend median track age for seeded continuation frames.",
    )
    parser.add_argument(
        "--continuation-max-motion",
        type=float,
        default=float("inf"),
        help="Maximum classical motion in pixels for seeded continuation frames.",
    )
    args = parser.parse_args()

    continuation_reasons = {
        item.strip()
        for item in str(args.continuation_reasons).split(",")
        if item.strip()
    }
    frame_metrics = load_frame_metrics(Path(args.frontend_metrics))
    stats = filter_bag(
        input_bag=Path(args.input_bag),
        output_bag=Path(args.output_bag),
        feature_topic=str(args.feature_topic),
        frame_metrics=frame_metrics,
        continuation_reasons=continuation_reasons,
        learned_id_min=int(args.learned_id_min),
        continuation_max_age=float(args.continuation_max_age),
        continuation_max_motion=float(args.continuation_max_motion),
    )
    stats.update(
        {
            "input_bag": str(args.input_bag),
            "frontend_metrics": str(args.frontend_metrics),
            "output_bag": str(args.output_bag),
            "feature_topic": str(args.feature_topic),
            "continuation_reasons": ",".join(sorted(continuation_reasons)),
            "learned_id_min": int(args.learned_id_min),
            "continuation_max_age": float(args.continuation_max_age),
            "continuation_max_motion": float(args.continuation_max_motion),
        }
    )
    write_stats(Path(args.stats_csv), stats)
    print(f"wrote {args.output_bag}")
    print(
        "feature_frames={feature_frames} seeded_frames={seeded_frames} "
        "continuation_frames={continuation_frames} kept_learned={kept_learned_observations} "
        "dropped_learned={dropped_learned_observations}".format(**stats)
    )
    return 0


def load_frame_metrics(path: Path) -> dict[int, dict[str, float | str]]:
    metrics: dict[int, dict[str, float | str]] = {}
    with path.open(newline="", encoding="utf-8") as handle:
        for fallback_index, row in enumerate(csv.DictReader(handle)):
            idx_raw = row.get("selected_feature_index") or row.get("frame_index") or fallback_index
            try:
                idx = int(round(float(idx_raw)))
            except (TypeError, ValueError):
                idx = fallback_index
            metrics[idx] = {
                "reason": str(row.get("learned_export_benefit_reason") or ""),
                "median_track_age": _safe_float(row.get("median_track_age"), float("inf")),
                "classical_motion_px": _safe_float(row.get("classical_motion_px"), float("inf")),
            }
    return metrics


def filter_bag(
    *,
    input_bag: Path,
    output_bag: Path,
    feature_topic: str,
    frame_metrics: dict[int, dict[str, float | str]],
    continuation_reasons: set[str],
    learned_id_min: int,
    continuation_max_age: float,
    continuation_max_motion: float,
) -> dict[str, int]:
    output_bag.parent.mkdir(parents=True, exist_ok=True)
    seeded_ids: set[int] = set()
    feature_frames = 0
    seeded_frames = 0
    continuation_frames = 0
    dropped_frames = 0
    kept_observations = 0
    kept_learned_observations = 0
    dropped_learned_observations = 0
    coverage_seeded_observations = 0
    continuation_seeded_observations = 0

    with rosbag.Bag(str(input_bag), "r") as in_bag, rosbag.Bag(str(output_bag), "w") as out_bag:
        for topic, msg, stamp in in_bag.read_messages():
            if topic == feature_topic:
                selected_index = feature_frames
                feature_frames += 1
                metric = frame_metrics.get(selected_index, {})
                reason = str(metric.get("reason", ""))
                median_age = float(metric.get("median_track_age", float("inf")))
                motion_px = float(metric.get("classical_motion_px", float("inf")))
                continuation_allowed = (
                    median_age <= float(continuation_max_age)
                    and motion_px <= float(continuation_max_motion)
                )
                n = len(msg.points)
                ids = _optional_channel_values(msg, "id", n, float("nan"))
                is_learned = _optional_channel_values(msg, "is_learned", n, 0.0)
                source_code = _optional_channel_values(msg, "source_code", n, 0.0)
                keep: list[bool] = []
                frame_seeded = 0
                frame_continued = 0
                frame_dropped = 0
                for idx in range(n):
                    feature_id = _safe_int(ids[idx], -1)
                    learned = _is_learned(
                        is_learned=float(is_learned[idx]),
                        source_code=int(round(float(source_code[idx]))),
                        feature_id=feature_id,
                        learned_id_min=learned_id_min,
                    )
                    remove = False
                    if learned and reason == "accepted_coverage_gain":
                        seeded_ids.add(feature_id)
                        frame_seeded += 1
                        coverage_seeded_observations += 1
                    elif (
                        learned
                        and reason in continuation_reasons
                        and continuation_allowed
                        and feature_id in seeded_ids
                    ):
                        frame_continued += 1
                        continuation_seeded_observations += 1
                    elif learned:
                        remove = True
                        frame_dropped += 1
                        dropped_learned_observations += 1

                    if learned and not remove:
                        kept_learned_observations += 1
                    keep.append(not remove)

                if frame_seeded:
                    seeded_frames += 1
                if frame_continued:
                    continuation_frames += 1
                if frame_dropped:
                    dropped_frames += 1
                    _filter_channels(msg, keep)
                kept_observations += sum(1 for item in keep if item)
            out_bag.write(topic, msg, stamp)

    return {
        "feature_frames": feature_frames,
        "seeded_frames": seeded_frames,
        "continuation_frames": continuation_frames,
        "dropped_frames": dropped_frames,
        "kept_observations": kept_observations,
        "kept_learned_observations": kept_learned_observations,
        "dropped_learned_observations": dropped_learned_observations,
        "coverage_seeded_observations": coverage_seeded_observations,
        "continuation_seeded_observations": continuation_seeded_observations,
        "seeded_track_ids": len(seeded_ids),
    }


def _is_learned(
    *,
    is_learned: float,
    source_code: int,
    feature_id: int,
    learned_id_min: int,
) -> bool:
    if float(is_learned) > 0.5:
        return True
    if int(source_code) in LEARNED_SOURCE_CODES:
        return True
    return int(learned_id_min) > 0 and int(feature_id) >= int(learned_id_min)


def _optional_channel_values(msg, name: str, length: int, default: float) -> list[float]:
    for channel in msg.channels:
        if channel.name == name and len(channel.values) == length:
            return list(channel.values)
    return [float(default)] * length


def _safe_int(value: float, default: int) -> int:
    try:
        return int(round(float(value)))
    except (TypeError, ValueError, OverflowError):
        return default


def _safe_float(value: object, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError, OverflowError):
        return default


def _filter_channels(msg, keep: list[bool]) -> None:
    if len(msg.points) == len(keep):
        msg.points = [point for point, keep_value in zip(msg.points, keep) if keep_value]
    for channel in msg.channels:
        if len(channel.values) == len(keep):
            channel.values = [float(value) for value, keep_value in zip(channel.values, keep) if keep_value]


def write_stats(path: Path, row: dict[str, int | str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(row.keys()))
        writer.writeheader()
        writer.writerow(row)


if __name__ == "__main__":
    raise SystemExit(main())
