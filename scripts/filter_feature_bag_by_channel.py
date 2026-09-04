#!/usr/bin/env python3
"""Filter VINS PointCloud feature observations by exported channel values."""

from __future__ import annotations

import argparse
import csv
from pathlib import Path

import rosbag


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-bag", required=True)
    parser.add_argument("--output-bag", required=True)
    parser.add_argument("--stats-csv", required=True)
    parser.add_argument("--feature-topic", default="/feature_tracker/feature")
    parser.add_argument("--drop-learned", action="store_true")
    parser.add_argument(
        "--drop-learned-track-lineage",
        action="store_true",
        help=(
            "Drop every observation belonging to a feature id that appears "
            "as learned/LoFTR at least once, including later LK propagation."
        ),
    )
    parser.add_argument(
        "--keep-learned-selected-indices",
        default="",
        help=(
            "Comma-separated selected feature frame indices whose learned "
            "observations should be kept. With --drop-learned, learned "
            "observations in all other selected frames are removed."
        ),
    )
    parser.add_argument("--drop-source-code", action="append", type=int, default=[])
    parser.add_argument(
        "--drop-learned-camera-id",
        action="append",
        type=int,
        default=[],
        help=(
            "Drop learned observations only for the selected camera id. "
            "Repeat for multiple cameras. This isolates temporal cam0 "
            "learned tracks from same-frame stereo cam1 seeds."
        ),
    )
    parser.add_argument(
        "--learned-id-min",
        type=int,
        default=0,
        help=(
            "Treat feature ids >= this value as learned observations. This is "
            "needed for older exported bags that predate is_learned/source_code "
            "channels. A value of 0 disables id-based learned detection."
        ),
    )
    parser.add_argument(
        "--learned-min-total-observations",
        type=int,
        default=0,
        help=(
            "Diagnostic offline gate: keep learned feature ids only when they "
            "appear at least this many times in the whole bag."
        ),
    )
    parser.add_argument(
        "--learned-max-observations",
        type=int,
        default=0,
        help=(
            "Diagnostic offline gate: keep only the first N learned observations "
            "in feature-frame order. A value of 0 disables the budget."
        ),
    )
    parser.add_argument(
        "--learned-max-per-frame",
        type=int,
        default=0,
        help=(
            "Diagnostic offline gate: keep at most N learned observations in "
            "each feature frame. A value of 0 disables the per-frame budget."
        ),
    )
    parser.add_argument(
        "--keep-learned-id",
        action="append",
        type=int,
        default=[],
        help=(
            "Diagnostic offline gate: when provided, keep learned observations "
            "only for these feature ids. Repeat the option for multiple ids."
        ),
    )
    parser.add_argument(
        "--keep-learned-track-lineage-id",
        action="append",
        type=int,
        default=[],
        help=(
            "Diagnostic offline gate: keep complete learned-seeded track "
            "lineages only for these feature ids, including later LK "
            "observations whose source code is no longer learned. Repeat "
            "the option for multiple ids."
        ),
    )
    args = parser.parse_args()

    keep_learned_indices = {
        int(item.strip())
        for item in str(args.keep_learned_selected_indices).split(",")
        if item.strip()
    }
    stats = filter_bag(
        input_bag=Path(args.input_bag),
        output_bag=Path(args.output_bag),
        feature_topic=str(args.feature_topic),
        drop_learned=bool(args.drop_learned),
        drop_learned_track_lineage=bool(args.drop_learned_track_lineage),
        keep_learned_selected_indices=keep_learned_indices,
        drop_source_codes={int(code) for code in args.drop_source_code},
        drop_learned_camera_ids={
            int(camera_id) for camera_id in args.drop_learned_camera_id
        },
        learned_id_min=int(args.learned_id_min),
        learned_min_total_observations=int(args.learned_min_total_observations),
        learned_max_observations=int(args.learned_max_observations),
        learned_max_per_frame=int(args.learned_max_per_frame),
        keep_learned_ids={int(feature_id) for feature_id in args.keep_learned_id},
        keep_learned_track_lineage_ids={
            int(feature_id) for feature_id in args.keep_learned_track_lineage_id
        },
    )
    stats.update(
        {
            "input_bag": str(args.input_bag),
            "output_bag": str(args.output_bag),
            "feature_topic": str(args.feature_topic),
            "drop_learned": int(bool(args.drop_learned)),
            "drop_learned_track_lineage": int(bool(args.drop_learned_track_lineage)),
            "keep_learned_selected_indices": ",".join(
                str(idx) for idx in sorted(keep_learned_indices)
            ),
            "drop_source_code": ",".join(str(code) for code in sorted(args.drop_source_code)),
            "drop_learned_camera_id": ",".join(
                str(camera_id) for camera_id in sorted(args.drop_learned_camera_id)
            ),
            "learned_id_min": int(args.learned_id_min),
            "learned_min_total_observations": int(args.learned_min_total_observations),
            "learned_max_observations": int(args.learned_max_observations),
            "learned_max_per_frame": int(args.learned_max_per_frame),
            "keep_learned_ids": ",".join(
                str(feature_id) for feature_id in sorted(args.keep_learned_id)
            ),
            "keep_learned_track_lineage_ids": ",".join(
                str(feature_id)
                for feature_id in sorted(args.keep_learned_track_lineage_id)
            ),
        }
    )
    write_stats(Path(args.stats_csv), stats)
    print(f"wrote {args.output_bag}")
    print(
        "feature_frames={feature_frames} frames_with_drops={frames_with_drops} "
        "dropped_observations={dropped_observations} kept_observations={kept_observations}".format(
            **stats
        )
    )
    return 0


def filter_bag(
    *,
    input_bag: Path,
    output_bag: Path,
    feature_topic: str,
    drop_learned: bool,
    drop_learned_track_lineage: bool,
    keep_learned_selected_indices: set[int],
    drop_source_codes: set[int],
    drop_learned_camera_ids: set[int],
    learned_id_min: int,
    learned_min_total_observations: int,
    learned_max_observations: int,
    learned_max_per_frame: int,
    keep_learned_ids: set[int],
    keep_learned_track_lineage_ids: set[int],
) -> dict[str, int]:
    output_bag.parent.mkdir(parents=True, exist_ok=True)
    learned_total_counts = (
        _count_learned_observations_by_id(input_bag, feature_topic, learned_id_min)
        if learned_min_total_observations > 0
        else {}
    )
    learned_track_ids = (
        _learned_track_ids(input_bag, feature_topic, learned_id_min)
        if drop_learned_track_lineage or keep_learned_track_lineage_ids
        else set()
    )
    feature_frames = 0
    frames_with_drops = 0
    dropped_observations = 0
    dropped_short_learned_observations = 0
    dropped_budget_learned_observations = 0
    dropped_per_frame_learned_observations = 0
    dropped_nonselected_learned_observations = 0
    dropped_camera_learned_observations = 0
    kept_learned_observations = 0
    kept_observations = 0

    with rosbag.Bag(str(input_bag), "r") as in_bag, rosbag.Bag(
        str(output_bag), "w", compression=rosbag.Compression.LZ4
    ) as out_bag:
        for topic, msg, stamp in in_bag.read_messages():
            if topic == feature_topic:
                selected_index = feature_frames
                feature_frames += 1
                n = len(msg.points)
                is_learned = _optional_channel_values(msg, "is_learned", n, 0.0)
                source_code = _optional_channel_values(msg, "source_code", n, 0.0)
                ids = _optional_channel_values(msg, "id", n, float("nan"))
                camera_ids = _optional_channel_values(msg, "camera_id", n, 0.0)
                keep: list[bool] = []
                kept_learned_this_frame = 0
                for idx in range(n):
                    code = int(round(float(source_code[idx])))
                    feature_id = _safe_int(ids[idx], -1)
                    learned = _is_learned_observation(
                        is_learned=float(is_learned[idx]),
                        source_code=code,
                        feature_id=feature_id,
                        learned_id_min=learned_id_min,
                    )
                    remove = False
                    if drop_learned and learned and selected_index not in keep_learned_selected_indices:
                        remove = True
                    if (
                        drop_learned_track_lineage
                        and feature_id in learned_track_ids
                        and selected_index not in keep_learned_selected_indices
                    ):
                        remove = True
                    if (
                        keep_learned_track_lineage_ids
                        and feature_id in learned_track_ids
                        and feature_id not in keep_learned_track_lineage_ids
                    ):
                        remove = True
                    if (
                        learned
                        and learned_min_total_observations > 0
                        and learned_total_counts.get(feature_id, 0)
                        < learned_min_total_observations
                    ):
                        remove = True
                        dropped_short_learned_observations += 1
                    if learned and keep_learned_ids and feature_id not in keep_learned_ids:
                        remove = True
                        dropped_nonselected_learned_observations += 1
                    if (
                        learned
                        and int(learned_max_observations) > 0
                        and kept_learned_observations >= int(learned_max_observations)
                    ):
                        remove = True
                        dropped_budget_learned_observations += 1
                    if (
                        learned
                        and not remove
                        and int(learned_max_per_frame) > 0
                        and kept_learned_this_frame >= int(learned_max_per_frame)
                    ):
                        remove = True
                        dropped_per_frame_learned_observations += 1
                    if code in drop_source_codes:
                        remove = True
                    if (
                        learned
                        and _safe_int(camera_ids[idx], 0) in drop_learned_camera_ids
                    ):
                        if not remove:
                            dropped_camera_learned_observations += 1
                        remove = True
                    if learned and not remove:
                        kept_learned_observations += 1
                        kept_learned_this_frame += 1
                    keep.append(not remove)
                dropped = len(keep) - sum(1 for item in keep if item)
                if dropped:
                    frames_with_drops += 1
                    dropped_observations += dropped
                    _filter_channels(msg, keep)
                kept_observations += sum(1 for item in keep if item)
            out_bag.write(topic, msg, stamp)

    return {
        "feature_frames": feature_frames,
        "frames_with_drops": frames_with_drops,
        "dropped_observations": dropped_observations,
        "dropped_short_learned_observations": dropped_short_learned_observations,
        "dropped_budget_learned_observations": dropped_budget_learned_observations,
        "dropped_per_frame_learned_observations": dropped_per_frame_learned_observations,
        "dropped_nonselected_learned_observations": dropped_nonselected_learned_observations,
        "dropped_camera_learned_observations": dropped_camera_learned_observations,
        "kept_learned_observations": kept_learned_observations,
        "learned_track_ids": len(learned_track_ids),
        "kept_observations": kept_observations,
    }


def _learned_track_ids(
    input_bag: Path,
    feature_topic: str,
    learned_id_min: int,
) -> set[int]:
    learned_ids: set[int] = set()
    with rosbag.Bag(str(input_bag), "r") as bag:
        for _topic, msg, _stamp in bag.read_messages(topics=[feature_topic]):
            n = len(msg.points)
            is_learned = _optional_channel_values(msg, "is_learned", n, 0.0)
            source_code = _optional_channel_values(msg, "source_code", n, 0.0)
            ids = _optional_channel_values(msg, "id", n, float("nan"))
            for idx in range(n):
                feature_id = _safe_int(ids[idx], -1)
                source_is_learned = int(round(float(source_code[idx]))) in {10, 20, 30}
                if source_is_learned or _is_learned_observation(
                    is_learned=float(is_learned[idx]),
                    source_code=int(round(float(source_code[idx]))),
                    feature_id=feature_id,
                    learned_id_min=learned_id_min,
                ):
                    learned_ids.add(feature_id)
    return learned_ids


def _count_learned_observations_by_id(
    input_bag: Path,
    feature_topic: str,
    learned_id_min: int,
) -> dict[int, int]:
    counts: dict[int, int] = {}
    with rosbag.Bag(str(input_bag), "r") as bag:
        for _topic, msg, _stamp in bag.read_messages(topics=[feature_topic]):
            n = len(msg.points)
            is_learned = _optional_channel_values(msg, "is_learned", n, 0.0)
            source_code = _optional_channel_values(msg, "source_code", n, 0.0)
            ids = _optional_channel_values(msg, "id", n, float("nan"))
            for idx in range(n):
                feature_id = _safe_int(ids[idx], -1)
                if _is_learned_observation(
                    is_learned=float(is_learned[idx]),
                    source_code=int(round(float(source_code[idx]))),
                    feature_id=feature_id,
                    learned_id_min=learned_id_min,
                ):
                    counts[feature_id] = counts.get(feature_id, 0) + 1
    return counts


def _is_learned_observation(
    *,
    is_learned: float,
    source_code: int,
    feature_id: int,
    learned_id_min: int,
) -> bool:
    if float(is_learned) > 0.5:
        return True
    if int(source_code) in {10, 20, 30}:
        return True
    return int(learned_id_min) > 0 and int(feature_id) >= int(learned_id_min)


def _safe_int(value: float, default: int) -> int:
    try:
        return int(round(float(value)))
    except (TypeError, ValueError, OverflowError):
        return default


def _optional_channel_values(msg, name: str, length: int, default: float) -> list[float]:
    for channel in msg.channels:
        if channel.name == name and len(channel.values) == length:
            return list(channel.values)
    return [float(default)] * length


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
