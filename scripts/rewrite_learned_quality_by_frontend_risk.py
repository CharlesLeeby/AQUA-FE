#!/usr/bin/env python3
"""Rewrite learned feature q/sigma with frontend-risk-conditioned values.

This is a diagnostic bridge between exported feature bags and the formal
exporter.  It keeps the same PointCloud observations and only changes the
backend-facing quality/sigma channels for learned/high-id tracks in feature
frames whose frontend metrics match a risk policy.
"""

from __future__ import annotations

import argparse
import csv
import math
import re
from dataclasses import dataclass
from pathlib import Path

import rosbag
from sensor_msgs.msg import ChannelFloat32


@dataclass(frozen=True)
class FrameRisk:
    selected_index: int
    risky: bool
    reason: str
    gftt_count: int
    learned_observations: int
    new_cells: float
    grid_gain: float
    classical_motion_px: float


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-bag", required=True)
    parser.add_argument("--output-bag", required=True)
    parser.add_argument("--frontend-metrics", required=True)
    parser.add_argument("--stats-csv", required=True)
    parser.add_argument("--feature-topic", default="/feature_tracker/feature")
    parser.add_argument("--id-min", type=int, default=10_000_000)
    parser.add_argument("--base-quality", type=float, default=0.30)
    parser.add_argument("--risk-quality", type=float, default=0.20)
    parser.add_argument("--min-quality", type=float, default=0.05)
    parser.add_argument(
        "--risk-policy",
        default="gftt_latch",
        choices=[
            "gftt_any",
            "gftt_latch",
            "probation_gftt_latch",
            "gftt_or_zero_gain",
            "low_motion_zero_gain",
            "global_gftt_latch",
        ],
    )
    parser.add_argument("--min-gftt", type=int, default=1)
    parser.add_argument(
        "--latch-gftt-total",
        type=int,
        default=30,
        help="Latch risk once cumulative GFTT in learned-export frames reaches this count.",
    )
    parser.add_argument("--max-new-cells", type=float, default=0.0)
    parser.add_argument("--max-grid-gain", type=float, default=0.0)
    parser.add_argument("--max-motion-px", type=float, default=6.0)
    parser.add_argument(
        "--probation-learned-frames",
        type=int,
        default=12,
        help=(
            "For probation_gftt_latch, keep learned observations soft for the "
            "first N learned-export frames, then promote unless GFTT risk latches."
        ),
    )
    args = parser.parse_args()

    risks = load_frame_risks(
        Path(args.frontend_metrics),
        policy=str(args.risk_policy),
        min_gftt=int(args.min_gftt),
        latch_gftt_total=int(args.latch_gftt_total),
        max_new_cells=float(args.max_new_cells),
        max_grid_gain=float(args.max_grid_gain),
        max_motion_px=float(args.max_motion_px),
        probation_learned_frames=int(args.probation_learned_frames),
    )
    stats = rewrite(
        input_bag=Path(args.input_bag),
        output_bag=Path(args.output_bag),
        feature_topic=str(args.feature_topic),
        id_min=int(args.id_min),
        base_quality=float(args.base_quality),
        risk_quality=float(args.risk_quality),
        min_quality=float(args.min_quality),
        risks=risks,
    )
    policy_counts: dict[str, int] = {}
    for risk in risks.values():
        if risk.risky:
            policy_counts[risk.reason] = policy_counts.get(risk.reason, 0) + 1
    stats.update(
        {
            "input_bag": str(args.input_bag),
            "output_bag": str(args.output_bag),
            "frontend_metrics": str(args.frontend_metrics),
            "risk_policy": str(args.risk_policy),
            "base_quality": float(args.base_quality),
            "risk_quality": float(args.risk_quality),
            "id_min": int(args.id_min),
            "risk_reason_counts": ";".join(
                f"{key}:{policy_counts[key]}" for key in sorted(policy_counts)
            ),
        }
    )
    write_stats(Path(args.stats_csv), stats)
    print(f"wrote {args.output_bag}")
    print(
        "feature_frames={feature_frames} learned_observations={learned_observations} "
        "risk_learned_observations={risk_learned_observations} "
        "base_learned_observations={base_learned_observations}".format(**stats)
    )
    return 0


def load_frame_risks(
    path: Path,
    *,
    policy: str,
    min_gftt: int,
    latch_gftt_total: int,
    max_new_cells: float,
    max_grid_gain: float,
    max_motion_px: float,
    probation_learned_frames: int,
) -> dict[int, FrameRisk]:
    rows = list(csv.DictReader(path.open(newline="", encoding="utf-8")))
    cumulative_gftt = 0
    latch_active = False
    total_gftt_in_learned_frames = 0
    if policy == "global_gftt_latch":
        for row in rows:
            learned = _as_int(row.get("exported_learned_features"))
            if learned > 0:
                total_gftt_in_learned_frames += _gftt_count(row.get("export_source_histogram", ""))
        latch_active = total_gftt_in_learned_frames >= int(latch_gftt_total)

    risks: dict[int, FrameRisk] = {}
    learned_frame_count = 0
    for row in rows:
        selected_index = _as_int(row.get("selected_feature_index"), default=-1)
        if selected_index < 0:
            continue
        learned = _as_int(row.get("exported_learned_features"))
        gftt = _gftt_count(row.get("export_source_histogram", ""))
        new_cells = _as_float(row.get("learned_export_new_cells"))
        grid_gain = _as_float(row.get("learned_export_grid_gain"))
        motion = _as_float(row.get("classical_motion_px"))
        if learned > 0:
            learned_frame_count += 1
            cumulative_gftt += gftt

        risky = False
        reason = "none"
        if policy == "gftt_any":
            risky = learned > 0 and gftt >= min_gftt
            reason = "gftt_any" if risky else reason
        elif policy == "gftt_latch":
            if learned > 0 and cumulative_gftt >= latch_gftt_total:
                latch_active = True
            risky = learned > 0 and latch_active
            reason = "gftt_latch" if risky else reason
        elif policy == "global_gftt_latch":
            risky = learned > 0 and latch_active
            reason = "global_gftt_latch" if risky else reason
        elif policy == "probation_gftt_latch":
            if learned > 0 and cumulative_gftt >= latch_gftt_total:
                latch_active = True
            in_probation = learned > 0 and learned_frame_count <= max(0, probation_learned_frames)
            risky = learned > 0 and (in_probation or latch_active)
            if risky:
                reason = "gftt_latch" if latch_active and not in_probation else "probation"
        elif policy == "gftt_or_zero_gain":
            has_gftt = learned > 0 and gftt >= min_gftt
            zero_gain = learned > 0 and new_cells <= max_new_cells and grid_gain <= max_grid_gain
            risky = has_gftt or zero_gain
            reason = "gftt_or_zero_gain" if risky else reason
        elif policy == "low_motion_zero_gain":
            risky = (
                learned > 0
                and motion <= max_motion_px
                and new_cells <= max_new_cells
                and grid_gain <= max_grid_gain
            )
            reason = "low_motion_zero_gain" if risky else reason

        risks[selected_index] = FrameRisk(
            selected_index=selected_index,
            risky=bool(risky),
            reason=reason,
            gftt_count=gftt,
            learned_observations=learned,
            new_cells=new_cells,
            grid_gain=grid_gain,
            classical_motion_px=motion,
        )
    return risks


def rewrite(
    *,
    input_bag: Path,
    output_bag: Path,
    feature_topic: str,
    id_min: int,
    base_quality: float,
    risk_quality: float,
    min_quality: float,
    risks: dict[int, FrameRisk],
) -> dict[str, int]:
    output_bag.parent.mkdir(parents=True, exist_ok=True)
    base_q = _clip_quality(base_quality, min_quality)
    risk_q = _clip_quality(risk_quality, min_quality)
    base_sigma = 1.0 / math.sqrt(base_q)
    risk_sigma = 1.0 / math.sqrt(risk_q)

    feature_frames = 0
    learned_observations = 0
    risk_learned_observations = 0
    base_learned_observations = 0
    frames_with_risk_learned = 0
    frames_with_base_learned = 0

    with rosbag.Bag(str(input_bag), "r") as in_bag, rosbag.Bag(str(output_bag), "w") as out_bag:
        for topic, msg, stamp in in_bag.read_messages():
            if topic == feature_topic:
                selected_index = feature_frames
                feature_frames += 1
                n = len(msg.points)
                ids = _channel_values_or_default(msg, "id", float("nan"), n)
                is_learned = _channel_values_or_default(msg, "is_learned", 0.0, n)
                q_values = _channel_values_or_default(msg, "quality", 1.0, n)
                sigma_values = _channel_values_or_default(msg, "sigma", 1.0, n)
                risk = risks.get(selected_index)
                frame_risky = bool(risk.risky) if risk is not None else False
                frame_risk_rewrites = 0
                frame_base_rewrites = 0
                for idx in range(n):
                    feature_id = _safe_int(ids[idx], -1)
                    learned = float(is_learned[idx]) > 0.5 or feature_id >= int(id_min)
                    if not learned:
                        continue
                    learned_observations += 1
                    if frame_risky:
                        q_values[idx] = risk_q
                        sigma_values[idx] = risk_sigma
                        risk_learned_observations += 1
                        frame_risk_rewrites += 1
                    else:
                        q_values[idx] = base_q
                        sigma_values[idx] = base_sigma
                        base_learned_observations += 1
                        frame_base_rewrites += 1
                if frame_risk_rewrites:
                    frames_with_risk_learned += 1
                if frame_base_rewrites:
                    frames_with_base_learned += 1
                _set_channel(msg, "quality", q_values)
                _set_channel(msg, "sigma", sigma_values)
            out_bag.write(topic, msg, stamp)

    return {
        "feature_frames": feature_frames,
        "learned_observations": learned_observations,
        "risk_learned_observations": risk_learned_observations,
        "base_learned_observations": base_learned_observations,
        "frames_with_risk_learned": frames_with_risk_learned,
        "frames_with_base_learned": frames_with_base_learned,
    }


def _gftt_count(histogram: str) -> int:
    match = re.search(r"(?:^|;)gftt:(\d+)(?:;|$)", str(histogram))
    return int(match.group(1)) if match else 0


def _as_float(value: str | None, default: float = math.nan) -> float:
    try:
        return float(value) if value not in (None, "") else float(default)
    except ValueError:
        return float(default)


def _as_int(value: str | None, default: int = 0) -> int:
    try:
        return int(round(float(value))) if value not in (None, "") else int(default)
    except ValueError:
        return int(default)


def _clip_quality(value: float, min_quality: float) -> float:
    return max(float(min_quality), min(1.0, float(value)))


def _channel_values_or_default(msg, name: str, default: float, size: int) -> list[float]:
    for channel in msg.channels:
        if channel.name == name:
            return list(channel.values)
    return [float(default)] * int(size)


def _set_channel(msg, name: str, values: list[float]) -> None:
    for channel in msg.channels:
        if channel.name == name:
            channel.values = [float(item) for item in values]
            return
    channel = ChannelFloat32(name=name)
    channel.values = [float(item) for item in values]
    msg.channels.append(channel)


def _safe_int(value: float, default: int) -> int:
    try:
        if not math.isfinite(float(value)):
            return int(default)
        return int(round(float(value)))
    except (TypeError, ValueError):
        return int(default)


def write_stats(path: Path, row: dict[str, int | float | str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(row.keys()))
        writer.writeheader()
        writer.writerow(row)


if __name__ == "__main__":
    raise SystemExit(main())
