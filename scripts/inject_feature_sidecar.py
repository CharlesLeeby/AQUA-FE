#!/usr/bin/env python3
"""Inject learned sidecar observations into a complete VINS feature bag.

The script keeps every base PointCloud feature message intact and only appends
selected observations from a prefix/sidecar bag. This is useful for isolating
whether learned observations help VINS without replacing the KLT/GFTT backbone.
"""

from __future__ import annotations

import argparse
import copy
import csv
import math
import statistics
import struct
from pathlib import Path

import rosbag
from sensor_msgs.msg import ChannelFloat32


LEARNED_SOURCE_CODES = {10, 20, 30}
FLOAT32_EXACT_INT_LIMIT = 16_777_216


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-bag", required=True, help="Complete bag with IMU/GT and backbone features.")
    parser.add_argument("--sidecar-bag", required=True, help="Bag containing learned sidecar candidates.")
    parser.add_argument("--output-bag", required=True)
    parser.add_argument("--stats-csv", required=True)
    parser.add_argument("--feature-topic", default="/feature_tracker/feature")
    parser.add_argument("--max-frames", type=int, default=0, help="Only read this many feature frames from sidecar.")
    parser.add_argument("--learned-id-min", type=int, default=10000000)
    parser.add_argument(
        "--source-code",
        action="append",
        type=int,
        default=[],
        help="Only inject these source_code values. Repeatable. Default: any learned/high-id observation.",
    )
    parser.add_argument("--max-per-frame", type=int, default=0, help="Cap injected observations per frame.")
    parser.add_argument("--max-total", type=int, default=0, help="Cap total injected observations.")
    parser.add_argument(
        "--min-track-observations",
        type=int,
        default=0,
        help=(
            "Only inject learned sidecar tracks that appear at least this many "
            "times in the sidecar bag after source filtering. A value of 0 "
            "disables this offline diagnostic filter."
        ),
    )
    parser.add_argument(
        "--remap-learned-ids",
        action="store_true",
        help=(
            "Map injected learned feature ids into a separate high-id namespace. "
            "This preserves sidecar track continuity while preventing collisions "
            "with the KLT/GFTT backbone."
        ),
    )
    parser.add_argument("--remap-id-base", type=int, default=10000000)
    parser.add_argument(
        "--include-learned-track-lineage",
        action="store_true",
        help=(
            "After identifying learned seed ids, also inject their later "
            "KLT-propagated observations. Source-code filters select the seed "
            "source; they do not remove later observations from that lineage."
        ),
    )
    parser.add_argument(
        "--max-track-lineages",
        type=int,
        default=0,
        help=(
            "Keep at most this many learned lineages, ranked by their median "
            "pixel distance from the base KLT tracks. A value of 0 disables "
            "the lineage-count cap."
        ),
    )
    parser.add_argument(
        "--lineage-rank-observations",
        type=int,
        default=5,
        help="Use only the first N lineage observations for the KLT-distance score.",
    )
    parser.add_argument(
        "--lineage-min-median-base-distance-px",
        type=float,
        default=0.0,
        help=(
            "Reject lineages whose first-N median distance from the nearest "
            "base KLT observation is below this pixel threshold."
        ),
    )
    parser.add_argument(
        "--causal-lineage-selection",
        action="store_true",
        help=(
            "Simulate online admission: accumulate observations in frame order, "
            "select a lineage only after it reaches --min-track-observations, "
            "and publish from that confirmation frame onward without backfill."
        ),
    )
    parser.add_argument(
        "--causal-online-seed-discovery",
        action="store_true",
        help=(
            "Discover learned seed ids while streaming frames instead of "
            "pre-scanning the sidecar bag. This removes future seed-id "
            "knowledge from causal shadow evaluation."
        ),
    )
    parser.add_argument(
        "--causal-lineage-rank-before-motion-gate",
        action="store_true",
        help=(
            "Rank newly ready lineages by novelty before applying motion "
            "bounds. A motion-rejected top candidate does not let a lower-"
            "ranked candidate fill the same single-lineage slot."
        ),
    )
    parser.add_argument(
        "--causal-lineage-min-motion-ratio",
        type=float,
        default=0.0,
        help=(
            "For causal lineage selection, reject a lineage when the median "
            "of its first-N speed ratios to the same-frame base KLT median "
            "speed is below this value. A value of 0 disables this gate."
        ),
    )
    parser.add_argument(
        "--causal-lineage-max-motion-ratio",
        type=float,
        default=0.0,
        help=(
            "For causal lineage selection, reject a lineage when the median "
            "of its first-N speed ratios to the same-frame base KLT median "
            "speed exceeds this value. A value of 0 disables this gate."
        ),
    )
    parser.add_argument(
        "--match-tolerance",
        type=float,
        default=0.02,
        help="Warn when base and sidecar feature timestamps differ by more than this many seconds.",
    )
    args = parser.parse_args()

    stats = inject_sidecar(
        base_bag=Path(args.base_bag),
        sidecar_bag=Path(args.sidecar_bag),
        output_bag=Path(args.output_bag),
        feature_topic=str(args.feature_topic),
        max_frames=int(args.max_frames),
        learned_id_min=int(args.learned_id_min),
        source_codes={int(code) for code in args.source_code},
        max_per_frame=int(args.max_per_frame),
        max_total=int(args.max_total),
        min_track_observations=int(args.min_track_observations),
        remap_learned_ids=bool(args.remap_learned_ids),
        remap_id_base=int(args.remap_id_base),
        include_learned_track_lineage=bool(args.include_learned_track_lineage),
        max_track_lineages=int(args.max_track_lineages),
        lineage_rank_observations=int(args.lineage_rank_observations),
        lineage_min_median_base_distance_px=float(
            args.lineage_min_median_base_distance_px
        ),
        causal_lineage_selection=bool(args.causal_lineage_selection),
        causal_online_seed_discovery=bool(args.causal_online_seed_discovery),
        causal_lineage_rank_before_motion_gate=bool(
            args.causal_lineage_rank_before_motion_gate
        ),
        causal_lineage_min_motion_ratio=float(
            args.causal_lineage_min_motion_ratio
        ),
        causal_lineage_max_motion_ratio=float(
            args.causal_lineage_max_motion_ratio
        ),
        match_tolerance=float(args.match_tolerance),
    )
    stats.update(
        {
            "base_bag": str(args.base_bag),
            "sidecar_bag": str(args.sidecar_bag),
            "output_bag": str(args.output_bag),
            "feature_topic": str(args.feature_topic),
            "max_frames": int(args.max_frames),
            "learned_id_min": int(args.learned_id_min),
            "source_code_filter": ",".join(str(code) for code in sorted(args.source_code)),
            "max_per_frame": int(args.max_per_frame),
            "max_total": int(args.max_total),
            "min_track_observations": int(args.min_track_observations),
            "remap_learned_ids": int(bool(args.remap_learned_ids)),
            "remap_id_base": int(args.remap_id_base),
            "include_learned_track_lineage": int(
                bool(args.include_learned_track_lineage)
            ),
            "max_track_lineages": int(args.max_track_lineages),
            "lineage_rank_observations": int(args.lineage_rank_observations),
            "lineage_min_median_base_distance_px": float(
                args.lineage_min_median_base_distance_px
            ),
            "causal_lineage_selection": int(bool(args.causal_lineage_selection)),
            "causal_online_seed_discovery": int(
                bool(args.causal_online_seed_discovery)
            ),
            "causal_lineage_rank_before_motion_gate": int(
                bool(args.causal_lineage_rank_before_motion_gate)
            ),
            "causal_lineage_min_motion_ratio": float(
                args.causal_lineage_min_motion_ratio
            ),
            "causal_lineage_max_motion_ratio": float(
                args.causal_lineage_max_motion_ratio
            ),
            "match_tolerance": float(args.match_tolerance),
        }
    )
    write_stats(Path(args.stats_csv), stats)
    print(f"wrote {args.output_bag}")
    print(
        "base_feature_frames={base_feature_frames} sidecar_feature_frames={sidecar_feature_frames} "
        "frames_with_injection={frames_with_injection} injected_observations={injected_observations}".format(
            **stats
        )
    )
    return 0


def inject_sidecar(
    *,
    base_bag: Path,
    sidecar_bag: Path,
    output_bag: Path,
    feature_topic: str,
    max_frames: int,
    learned_id_min: int,
    source_codes: set[int],
    max_per_frame: int,
    max_total: int,
    min_track_observations: int,
    remap_learned_ids: bool,
    remap_id_base: int,
    include_learned_track_lineage: bool,
    max_track_lineages: int,
    lineage_rank_observations: int,
    lineage_min_median_base_distance_px: float,
    causal_lineage_selection: bool,
    causal_online_seed_discovery: bool,
    causal_lineage_rank_before_motion_gate: bool,
    causal_lineage_min_motion_ratio: float,
    causal_lineage_max_motion_ratio: float,
    match_tolerance: float,
) -> dict[str, object]:
    ranking_requested = (
        causal_lineage_selection
        or max_track_lineages > 0
        or lineage_min_median_base_distance_px > 0.0
    )
    if ranking_requested and not include_learned_track_lineage:
        raise ValueError(
            "lineage ranking requires --include-learned-track-lineage"
        )
    if lineage_rank_observations <= 0:
        raise ValueError("--lineage-rank-observations must be positive")
    if causal_lineage_selection and min_track_observations <= 0:
        raise ValueError(
            "--causal-lineage-selection requires positive --min-track-observations"
        )
    if causal_online_seed_discovery and not causal_lineage_selection:
        raise ValueError(
            "--causal-online-seed-discovery requires "
            "--causal-lineage-selection"
        )
    if causal_lineage_rank_before_motion_gate and not causal_lineage_selection:
        raise ValueError(
            "--causal-lineage-rank-before-motion-gate requires "
            "--causal-lineage-selection"
        )
    if causal_lineage_min_motion_ratio < 0.0:
        raise ValueError("--causal-lineage-min-motion-ratio cannot be negative")
    if causal_lineage_max_motion_ratio < 0.0:
        raise ValueError("--causal-lineage-max-motion-ratio cannot be negative")
    if (
        causal_lineage_max_motion_ratio > 0.0
        and causal_lineage_min_motion_ratio > causal_lineage_max_motion_ratio
    ):
        raise ValueError(
            "--causal-lineage-min-motion-ratio cannot exceed "
            "--causal-lineage-max-motion-ratio"
        )
    if causal_lineage_min_motion_ratio > 0.0 and not causal_lineage_selection:
        raise ValueError(
            "--causal-lineage-min-motion-ratio requires "
            "--causal-lineage-selection"
        )
    if causal_lineage_max_motion_ratio > 0.0 and not causal_lineage_selection:
        raise ValueError(
            "--causal-lineage-max-motion-ratio requires "
            "--causal-lineage-selection"
        )
    base_frame_pixels = (
        _load_base_frame_pixels(
            base_bag=base_bag,
            feature_topic=feature_topic,
            max_frames=max_frames,
        )
        if ranking_requested
        else None
    )
    base_frame_median_speeds = (
        _load_base_frame_median_speeds(
            base_bag=base_bag,
            feature_topic=feature_topic,
            max_frames=max_frames,
        )
        if (
            causal_lineage_min_motion_ratio > 0.0
            or causal_lineage_max_motion_ratio > 0.0
        )
        else None
    )
    sidecar_frames, lineage_selection = _load_sidecar_frames(
        sidecar_bag=sidecar_bag,
        feature_topic=feature_topic,
        max_frames=max_frames,
        learned_id_min=learned_id_min,
        source_codes=source_codes,
        max_per_frame=max_per_frame,
        min_track_observations=min_track_observations,
        remap_learned_ids=remap_learned_ids,
        remap_id_base=remap_id_base,
        include_learned_track_lineage=include_learned_track_lineage,
        base_frame_pixels=base_frame_pixels,
        max_track_lineages=max_track_lineages,
        lineage_rank_observations=lineage_rank_observations,
        lineage_min_median_base_distance_px=lineage_min_median_base_distance_px,
        causal_lineage_selection=causal_lineage_selection,
        causal_online_seed_discovery=causal_online_seed_discovery,
        causal_lineage_rank_before_motion_gate=(
            causal_lineage_rank_before_motion_gate
        ),
        causal_lineage_min_motion_ratio=causal_lineage_min_motion_ratio,
        causal_lineage_max_motion_ratio=causal_lineage_max_motion_ratio,
        base_frame_median_speeds=base_frame_median_speeds,
    )

    output_bag.parent.mkdir(parents=True, exist_ok=True)
    base_feature_frames = 0
    base_non_feature_messages = 0
    frames_with_injection = 0
    injected_observations = 0
    timestamp_mismatch_count = 0
    max_timestamp_delta = 0.0
    sidecar_frames_used = 0
    max_total_reached = False

    with rosbag.Bag(str(base_bag), "r") as in_bag, rosbag.Bag(str(output_bag), "w") as out_bag:
        for topic, msg, stamp in in_bag.read_messages():
            if topic == feature_topic:
                frame_index = base_feature_frames
                base_feature_frames += 1
                if frame_index < len(sidecar_frames) and not max_total_reached:
                    sidecar = sidecar_frames[frame_index]
                    sidecar_frames_used += 1
                    delta = abs(float(stamp.to_sec()) - float(sidecar["stamp"]))
                    max_timestamp_delta = max(max_timestamp_delta, delta)
                    if delta > match_tolerance:
                        timestamp_mismatch_count += 1
                    candidates = list(sidecar["observations"])
                    if max_total > 0:
                        remaining = max(0, max_total - injected_observations)
                        candidates = candidates[:remaining]
                        if remaining <= 0:
                            max_total_reached = True
                    if candidates:
                        _append_observations(msg, candidates, context=f"feature frame {frame_index}")
                        injected_observations += len(candidates)
                        frames_with_injection += 1
                        if max_total > 0 and injected_observations >= max_total:
                            max_total_reached = True
            else:
                base_non_feature_messages += 1
            out_bag.write(topic, msg, stamp)

    return {
        "base_feature_frames": base_feature_frames,
        "base_non_feature_messages": base_non_feature_messages,
        "sidecar_feature_frames": len(sidecar_frames),
        "sidecar_frames_used": sidecar_frames_used,
        "frames_with_injection": frames_with_injection,
        "injected_observations": injected_observations,
        "remapped_track_count": max(
            [int(frame.get("remapped_track_count", 0)) for frame in sidecar_frames] or [0]
        ),
        "selected_lineage_count": len(lineage_selection["selected_ids"]),
        "selected_lineage_ids": ",".join(
            str(feature_id) for feature_id in lineage_selection["selected_ids"]
        ),
        "lineage_base_distance_scores_px": ";".join(
            f"{feature_id}:{lineage_selection['scores'][feature_id]:.6f}"
            for feature_id in sorted(lineage_selection["scores"])
        ),
        "lineage_activation_frames": ";".join(
            f"{feature_id}:{lineage_selection['activation_frames'][feature_id]}"
            for feature_id in sorted(lineage_selection["activation_frames"])
        ),
        "lineage_motion_ratios": ";".join(
            f"{feature_id}:{lineage_selection['motion_ratios'][feature_id]:.6f}"
            for feature_id in sorted(lineage_selection["motion_ratios"])
        ),
        "timestamp_mismatch_count": timestamp_mismatch_count,
        "max_timestamp_delta": max_timestamp_delta,
    }


def _load_sidecar_frames(
    *,
    sidecar_bag: Path,
    feature_topic: str,
    max_frames: int,
    learned_id_min: int,
    source_codes: set[int],
    max_per_frame: int,
    min_track_observations: int,
    remap_learned_ids: bool,
    remap_id_base: int,
    include_learned_track_lineage: bool,
    base_frame_pixels: list[list[tuple[float, float]]] | None,
    max_track_lineages: int,
    lineage_rank_observations: int,
    lineage_min_median_base_distance_px: float,
    causal_lineage_selection: bool,
    causal_online_seed_discovery: bool,
    causal_lineage_rank_before_motion_gate: bool,
    causal_lineage_min_motion_ratio: float,
    causal_lineage_max_motion_ratio: float,
    base_frame_median_speeds: list[float | None] | None,
) -> tuple[list[dict[str, object]], dict[str, object]]:
    frames: list[dict[str, object]] = []
    id_map: dict[int, int] = {}
    lineage_ids = (
        set()
        if include_learned_track_lineage
        and causal_lineage_selection
        and causal_online_seed_discovery
        else _learned_seed_ids(
            sidecar_bag=sidecar_bag,
            feature_topic=feature_topic,
            learned_id_min=learned_id_min,
            source_codes=source_codes,
            max_frames=max_frames,
        )
        if include_learned_track_lineage
        else None
    )
    if causal_lineage_selection:
        if lineage_ids is None or base_frame_pixels is None:
            raise ValueError(
                "causal lineage selection requires learned lineages and base pixels"
            )
        return _load_causal_lineage_frames(
            sidecar_bag=sidecar_bag,
            feature_topic=feature_topic,
            max_frames=max_frames,
            learned_id_min=learned_id_min,
            source_codes=source_codes,
            max_per_frame=max_per_frame,
            min_track_observations=min_track_observations,
            remap_learned_ids=remap_learned_ids,
            remap_id_base=remap_id_base,
            seed_ids=lineage_ids,
            online_seed_discovery=causal_online_seed_discovery,
            base_frame_pixels=base_frame_pixels,
            max_track_lineages=max_track_lineages,
            lineage_rank_observations=lineage_rank_observations,
            lineage_min_median_base_distance_px=(
                lineage_min_median_base_distance_px
            ),
            rank_before_motion_gate=causal_lineage_rank_before_motion_gate,
            min_motion_ratio=causal_lineage_min_motion_ratio,
            max_motion_ratio=causal_lineage_max_motion_ratio,
            base_frame_median_speeds=base_frame_median_speeds,
        )
    if lineage_ids is not None and min_track_observations > 0:
        lineage_counts = _track_observation_counts(
            sidecar_bag=sidecar_bag,
            feature_topic=feature_topic,
            max_frames=max_frames,
        )
        lineage_ids = {
            feature_id
            for feature_id in lineage_ids
            if lineage_counts.get(feature_id, 0) >= min_track_observations
        }
    lineage_scores: dict[int, float] = {}
    if lineage_ids is not None and base_frame_pixels is not None:
        lineage_scores = _lineage_base_distance_scores(
            sidecar_bag=sidecar_bag,
            feature_topic=feature_topic,
            lineage_ids=lineage_ids,
            base_frame_pixels=base_frame_pixels,
            rank_observations=lineage_rank_observations,
            max_frames=max_frames,
        )
        lineage_ids = {
            feature_id
            for feature_id in lineage_ids
            if lineage_scores.get(feature_id, float("-inf"))
            >= lineage_min_median_base_distance_px
        }
        if max_track_lineages > 0:
            ranked_ids = sorted(
                lineage_ids,
                key=lambda feature_id: (-lineage_scores[feature_id], feature_id),
            )
            lineage_ids = set(ranked_ids[:max_track_lineages])
    allowed_ids = (
        _allowed_track_ids(
            sidecar_bag=sidecar_bag,
            feature_topic=feature_topic,
            learned_id_min=learned_id_min,
            source_codes=source_codes,
            min_track_observations=min_track_observations,
            max_frames=max_frames,
        )
        if min_track_observations > 0
        and not include_learned_track_lineage
        else None
    )
    with rosbag.Bag(str(sidecar_bag), "r") as bag:
        for _topic, msg, stamp in bag.read_messages(topics=[feature_topic]):
            observations = _select_sidecar_observations(
                msg=msg,
                learned_id_min=learned_id_min,
                source_codes=source_codes,
                allowed_ids=allowed_ids,
                max_per_frame=max_per_frame,
                remap_learned_ids=remap_learned_ids,
                remap_id_base=remap_id_base,
                id_map=id_map,
                lineage_ids=lineage_ids,
            )
            frames.append(
                {
                    "stamp": float(stamp.to_sec()),
                    "observations": observations,
                    "remapped_track_count": len(id_map),
                }
            )
            if max_frames > 0 and len(frames) >= max_frames:
                break
    selected_ids = sorted(lineage_ids or [])
    return frames, {
        "selected_ids": selected_ids,
        "scores": lineage_scores,
        "activation_frames": {},
        "motion_ratios": {},
    }


def _load_causal_lineage_frames(
    *,
    sidecar_bag: Path,
    feature_topic: str,
    max_frames: int,
    learned_id_min: int,
    source_codes: set[int],
    max_per_frame: int,
    min_track_observations: int,
    remap_learned_ids: bool,
    remap_id_base: int,
    seed_ids: set[int],
    online_seed_discovery: bool,
    base_frame_pixels: list[list[tuple[float, float]]],
    max_track_lineages: int,
    lineage_rank_observations: int,
    lineage_min_median_base_distance_px: float,
    rank_before_motion_gate: bool,
    min_motion_ratio: float,
    max_motion_ratio: float,
    base_frame_median_speeds: list[float | None] | None,
) -> tuple[list[dict[str, object]], dict[str, object]]:
    frames: list[dict[str, object]] = []
    id_map: dict[int, int] = {}
    observation_counts: dict[int, int] = {feature_id: 0 for feature_id in seed_ids}
    distances: dict[int, list[float]] = {feature_id: [] for feature_id in seed_ids}
    speed_ratios: dict[int, list[float]] = {
        feature_id: [] for feature_id in seed_ids
    }
    scores: dict[int, float] = {}
    motion_ratio_scores: dict[int, float] = {}
    selected_ids: set[int] = set()
    evaluated_ids: set[int] = set()
    activation_frames: dict[int, int] = {}

    with rosbag.Bag(str(sidecar_bag), "r") as bag:
        for frame_index, (_topic, msg, stamp) in enumerate(
            bag.read_messages(topics=[feature_topic])
        ):
            if frame_index >= len(base_frame_pixels):
                break
            n = len(msg.points)
            ids = _channel_values(msg, "id", n, -1.0)
            is_learned = _channel_values(msg, "is_learned", n, 0.0)
            source = _channel_values(msg, "source_code", n, 0.0)
            p_u = _channel_values(msg, "p_u", n, float("nan"))
            p_v = _channel_values(msg, "p_v", n, float("nan"))
            velocity_x = _channel_values(msg, "velocity_x", n, float("nan"))
            velocity_y = _channel_values(msg, "velocity_y", n, float("nan"))
            base_pixels = base_frame_pixels[frame_index]
            if online_seed_discovery:
                for index in range(n):
                    feature_id = _safe_int(ids[index], -1)
                    source_code = _safe_int(source[index], 0)
                    learned = (
                        bool(round(float(is_learned[index])))
                        or source_code in LEARNED_SOURCE_CODES
                        or (learned_id_min > 0 and feature_id >= learned_id_min)
                    )
                    if not learned:
                        continue
                    if source_codes and source_code not in source_codes:
                        continue
                    if feature_id in seed_ids:
                        continue
                    seed_ids.add(feature_id)
                    observation_counts[feature_id] = 0
                    distances[feature_id] = []
                    speed_ratios[feature_id] = []
            seen_this_frame: set[int] = set()
            for index in range(n):
                feature_id = _safe_int(ids[index], -1)
                if feature_id not in seed_ids:
                    continue
                if feature_id in seen_this_frame:
                    continue
                seen_this_frame.add(feature_id)
                observation_counts[feature_id] += 1
                values = distances[feature_id]
                u = float(p_u[index])
                v = float(p_v[index])
                if (
                    len(values) < lineage_rank_observations
                    and base_pixels
                    and math.isfinite(u)
                    and math.isfinite(v)
                ):
                    values.append(
                        min(
                            math.hypot(u - base_u, v - base_v)
                            for base_u, base_v in base_pixels
                        )
                    )
                ratios = speed_ratios[feature_id]
                if (
                    (min_motion_ratio > 0.0 or max_motion_ratio > 0.0)
                    and len(ratios) < lineage_rank_observations
                    and base_frame_median_speeds is not None
                    and frame_index < len(base_frame_median_speeds)
                ):
                    base_speed = base_frame_median_speeds[frame_index]
                    vx = float(velocity_x[index])
                    vy = float(velocity_y[index])
                    if (
                        base_speed is not None
                        and base_speed > 1e-9
                        and math.isfinite(vx)
                        and math.isfinite(vy)
                    ):
                        ratios.append(math.hypot(vx, vy) / base_speed)

            novelty_ready_ids: list[int] = []
            motion_ok_by_id: dict[int, bool] = {}
            for feature_id in sorted(seen_this_frame):
                if feature_id in evaluated_ids:
                    continue
                if observation_counts[feature_id] < min_track_observations:
                    continue
                values = distances[feature_id]
                if len(values) < lineage_rank_observations:
                    continue
                ratios = speed_ratios[feature_id]
                if (
                    (min_motion_ratio > 0.0 or max_motion_ratio > 0.0)
                    and len(ratios) < lineage_rank_observations
                ):
                    continue
                score = float(statistics.median(values[:lineage_rank_observations]))
                scores[feature_id] = score
                if min_motion_ratio > 0.0 or max_motion_ratio > 0.0:
                    motion_ratio_scores[feature_id] = float(
                        statistics.median(ratios[:lineage_rank_observations])
                    )
                evaluated_ids.add(feature_id)
                motion_ok = (
                    (
                        min_motion_ratio <= 0.0
                        or motion_ratio_scores[feature_id] >= min_motion_ratio
                    )
                    and (
                        max_motion_ratio <= 0.0
                        or motion_ratio_scores[feature_id] <= max_motion_ratio
                    )
                )
                motion_ok_by_id[feature_id] = motion_ok
                if score >= lineage_min_median_base_distance_px:
                    novelty_ready_ids.append(feature_id)

            if novelty_ready_ids:
                remaining = len(novelty_ready_ids)
                if max_track_lineages > 0:
                    remaining = max(0, max_track_lineages - len(selected_ids))
                ranked_ready = sorted(
                    novelty_ready_ids,
                    key=lambda feature_id: (-scores[feature_id], feature_id),
                )
                if rank_before_motion_gate:
                    considered_ids = ranked_ready[:remaining]
                else:
                    considered_ids = [
                        feature_id
                        for feature_id in ranked_ready
                        if motion_ok_by_id[feature_id]
                    ][:remaining]
                for feature_id in considered_ids:
                    if not motion_ok_by_id[feature_id]:
                        continue
                    selected_ids.add(feature_id)
                    activation_frames[feature_id] = frame_index

            observations = _select_sidecar_observations(
                msg=msg,
                learned_id_min=learned_id_min,
                source_codes=source_codes,
                allowed_ids=None,
                max_per_frame=max_per_frame,
                remap_learned_ids=remap_learned_ids,
                remap_id_base=remap_id_base,
                id_map=id_map,
                lineage_ids=selected_ids,
            )
            frames.append(
                {
                    "stamp": float(stamp.to_sec()),
                    "observations": observations,
                    "remapped_track_count": len(id_map),
                }
            )
            if max_frames > 0 and len(frames) >= max_frames:
                break

    return frames, {
        "selected_ids": sorted(selected_ids),
        "scores": scores,
        "activation_frames": activation_frames,
        "motion_ratios": motion_ratio_scores,
    }


def _load_base_frame_pixels(
    *,
    base_bag: Path,
    feature_topic: str,
    max_frames: int,
) -> list[list[tuple[float, float]]]:
    frames: list[list[tuple[float, float]]] = []
    with rosbag.Bag(str(base_bag), "r") as bag:
        for frame_index, (_topic, msg, _stamp) in enumerate(
            bag.read_messages(topics=[feature_topic])
        ):
            n = len(msg.points)
            p_u = _channel_values(msg, "p_u", n, float("nan"))
            p_v = _channel_values(msg, "p_v", n, float("nan"))
            pixels = [
                (float(u), float(v))
                for u, v in zip(p_u, p_v)
                if math.isfinite(float(u)) and math.isfinite(float(v))
            ]
            frames.append(pixels)
            if max_frames > 0 and frame_index + 1 >= max_frames:
                break
    return frames


def _load_base_frame_median_speeds(
    *,
    base_bag: Path,
    feature_topic: str,
    max_frames: int,
) -> list[float | None]:
    frame_speeds: list[float | None] = []
    with rosbag.Bag(str(base_bag), "r") as bag:
        for frame_index, (_topic, msg, _stamp) in enumerate(
            bag.read_messages(topics=[feature_topic])
        ):
            n = len(msg.points)
            velocity_x = _channel_values(msg, "velocity_x", n, float("nan"))
            velocity_y = _channel_values(msg, "velocity_y", n, float("nan"))
            speeds = [
                math.hypot(float(vx), float(vy))
                for vx, vy in zip(velocity_x, velocity_y)
                if math.isfinite(float(vx)) and math.isfinite(float(vy))
            ]
            frame_speeds.append(
                float(statistics.median(speeds)) if speeds else None
            )
            if max_frames > 0 and frame_index + 1 >= max_frames:
                break
    return frame_speeds


def _lineage_base_distance_scores(
    *,
    sidecar_bag: Path,
    feature_topic: str,
    lineage_ids: set[int],
    base_frame_pixels: list[list[tuple[float, float]]],
    rank_observations: int,
    max_frames: int,
) -> dict[int, float]:
    distances: dict[int, list[float]] = {feature_id: [] for feature_id in lineage_ids}
    with rosbag.Bag(str(sidecar_bag), "r") as bag:
        for frame_index, (_topic, msg, _stamp) in enumerate(
            bag.read_messages(topics=[feature_topic])
        ):
            if frame_index >= len(base_frame_pixels):
                break
            base_pixels = base_frame_pixels[frame_index]
            if base_pixels:
                n = len(msg.points)
                ids = _channel_values(msg, "id", n, -1.0)
                p_u = _channel_values(msg, "p_u", n, float("nan"))
                p_v = _channel_values(msg, "p_v", n, float("nan"))
                for index in range(n):
                    feature_id = _safe_int(ids[index], -1)
                    values = distances.get(feature_id)
                    if values is None or len(values) >= rank_observations:
                        continue
                    u = float(p_u[index])
                    v = float(p_v[index])
                    if not math.isfinite(u) or not math.isfinite(v):
                        continue
                    values.append(
                        min(math.hypot(u - base_u, v - base_v) for base_u, base_v in base_pixels)
                    )
            if max_frames > 0 and frame_index + 1 >= max_frames:
                break
    return {
        feature_id: float(statistics.median(values))
        for feature_id, values in distances.items()
        if values
    }


def _learned_seed_ids(
    *,
    sidecar_bag: Path,
    feature_topic: str,
    learned_id_min: int,
    source_codes: set[int],
    max_frames: int,
) -> set[int]:
    feature_ids: set[int] = set()
    with rosbag.Bag(str(sidecar_bag), "r") as bag:
        for frame_index, (_topic, msg, _stamp) in enumerate(
            bag.read_messages(topics=[feature_topic])
        ):
            n = len(msg.points)
            ids = _channel_values(msg, "id", n, -1.0)
            is_learned = _channel_values(msg, "is_learned", n, 0.0)
            source = _channel_values(msg, "source_code", n, 0.0)
            for index in range(n):
                feature_id = _safe_int(ids[index], -1)
                source_code = _safe_int(source[index], 0)
                learned = (
                    bool(round(float(is_learned[index])))
                    or source_code in LEARNED_SOURCE_CODES
                    or (learned_id_min > 0 and feature_id >= learned_id_min)
                )
                if not learned:
                    continue
                if source_codes and source_code not in source_codes:
                    continue
                feature_ids.add(feature_id)
            if max_frames > 0 and frame_index + 1 >= max_frames:
                break
    return feature_ids


def _track_observation_counts(
    *,
    sidecar_bag: Path,
    feature_topic: str,
    max_frames: int,
) -> dict[int, int]:
    counts: dict[int, int] = {}
    with rosbag.Bag(str(sidecar_bag), "r") as bag:
        for frame_index, (_topic, msg, _stamp) in enumerate(
            bag.read_messages(topics=[feature_topic])
        ):
            n = len(msg.points)
            ids = _channel_values(msg, "id", n, -1.0)
            for raw_id in ids:
                feature_id = _safe_int(raw_id, -1)
                if feature_id >= 0:
                    counts[feature_id] = counts.get(feature_id, 0) + 1
            if max_frames > 0 and frame_index + 1 >= max_frames:
                break
    return counts


def _allowed_track_ids(
    *,
    sidecar_bag: Path,
    feature_topic: str,
    learned_id_min: int,
    source_codes: set[int],
    min_track_observations: int,
    max_frames: int,
) -> set[int]:
    counts: dict[int, int] = {}
    with rosbag.Bag(str(sidecar_bag), "r") as bag:
        for frame_index, (_topic, msg, _stamp) in enumerate(bag.read_messages(topics=[feature_topic])):
            n = len(msg.points)
            ids = _channel_values(msg, "id", n, -1.0)
            is_learned = _channel_values(msg, "is_learned", n, 0.0)
            source = _channel_values(msg, "source_code", n, 0.0)
            for index in range(n):
                feature_id = _safe_int(ids[index], -1)
                source_code = _safe_int(source[index], 0)
                learned = (
                    bool(round(float(is_learned[index])))
                    or source_code in LEARNED_SOURCE_CODES
                    or (learned_id_min > 0 and feature_id >= learned_id_min)
                )
                if not learned:
                    continue
                if source_codes and source_code not in source_codes:
                    continue
                counts[feature_id] = counts.get(feature_id, 0) + 1
            if max_frames > 0 and frame_index + 1 >= max_frames:
                break
    return {feature_id for feature_id, count in counts.items() if count >= min_track_observations}


def _select_sidecar_observations(
    *,
    msg,
    learned_id_min: int,
    source_codes: set[int],
    allowed_ids: set[int] | None,
    max_per_frame: int,
    remap_learned_ids: bool,
    remap_id_base: int,
    id_map: dict[int, int],
    lineage_ids: set[int] | None,
) -> list[dict[str, object]]:
    channel_names = [channel.name for channel in msg.channels]
    n = len(msg.points)
    ids = _channel_values(msg, "id", n, -1.0)
    is_learned = _channel_values(msg, "is_learned", n, 0.0)
    source = _channel_values(msg, "source_code", n, 0.0)

    observations: list[dict[str, object]] = []
    for index in range(n):
        feature_id = _safe_int(ids[index], -1)
        source_code = _safe_int(source[index], 0)
        learned_seed = (
            bool(round(float(is_learned[index])))
            or source_code in LEARNED_SOURCE_CODES
            or (learned_id_min > 0 and feature_id >= learned_id_min)
        )
        seed_source_allowed = not source_codes or source_code in source_codes
        lineage_observation = lineage_ids is not None and feature_id in lineage_ids
        if lineage_ids is not None:
            if not lineage_observation:
                continue
        elif not (learned_seed and seed_source_allowed):
            continue
        if allowed_ids is not None and feature_id not in allowed_ids:
            continue
        channel_values = {
            name: float(msg.channels[channel_idx].values[index])
            for channel_idx, name in enumerate(channel_names)
        }
        if remap_learned_ids:
            if feature_id not in id_map:
                next_id = int(remap_id_base) + len(id_map)
                _ensure_float32_exact_track_id(next_id, context="remapped learned id")
                id_map[feature_id] = next_id
            channel_values["id"] = float(id_map[feature_id])
            channel_values["is_learned"] = 1.0
            channel_values["source_code"] = float(source_code)
        observations.append(
            {
                "point": copy.deepcopy(msg.points[index]),
                "channels": channel_values,
            }
        )
        if max_per_frame > 0 and len(observations) >= max_per_frame:
            break
    return observations


def _append_observations(msg, observations: list[dict[str, object]], *, context: str) -> None:
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
            raise ValueError(
                f"channel {channel.name!r} length {len(channel.values)} exceeds point count {expected}"
            )
    _assert_unique_float32_feature_ids(msg, context=context)


def _channel_values(msg, name: str, count: int, default: float) -> list[float]:
    for channel in msg.channels:
        if channel.name == name:
            if len(channel.values) != count:
                raise ValueError(f"channel {name!r} length {len(channel.values)} does not match {count}")
            return list(channel.values)
    return [float(default)] * count


def _safe_int(value: float, default: int) -> int:
    try:
        return int(round(float(value)))
    except (TypeError, ValueError, OverflowError):
        return default


def _float32_roundtrip(value: float) -> float:
    return struct.unpack("!f", struct.pack("!f", float(value)))[0]


def _ensure_float32_exact_track_id(feature_id: int, *, context: str) -> None:
    if feature_id < 0:
        return
    if feature_id > FLOAT32_EXACT_INT_LIMIT:
        raise ValueError(
            f"{context} {feature_id} exceeds {FLOAT32_EXACT_INT_LIMIT}; "
            "sensor_msgs/ChannelFloat32 cannot preserve consecutive integer ids above this range. "
            "Use a lower --remap-id-base."
        )
    if _safe_int(_float32_roundtrip(float(feature_id)), -1) != int(feature_id):
        raise ValueError(
            f"{context} {feature_id} is not exactly representable after float32 serialization. "
            "Use a lower --remap-id-base."
        )


def _assert_unique_float32_feature_ids(msg, *, context: str) -> None:
    count = len(msg.points)
    ids = _channel_values(msg, "id", count, -1.0)
    seen: dict[int, int] = {}
    for index, raw_value in enumerate(ids):
        rounded_value = _float32_roundtrip(float(raw_value))
        feature_id = _safe_int(rounded_value, -1)
        if feature_id < 0:
            raise ValueError(f"missing or invalid feature id at {context}, index={index}")
        previous = seen.get(feature_id)
        if previous is not None:
            raise ValueError(
                f"duplicate feature id {feature_id} at {context} after float32 serialization "
                f"(indices {previous} and {index}). Lower --remap-id-base or filter sidecar ids."
            )
        seen[feature_id] = index


def write_stats(path: Path, stats: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(stats.keys()))
        writer.writeheader()
        writer.writerow(stats)


if __name__ == "__main__":
    raise SystemExit(main())
