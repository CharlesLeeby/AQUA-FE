#!/usr/bin/env python3
"""Rewrite VINS feature quality for sidecar-triggered recovery windows.

The script keeps the feature set and timestamps unchanged.  It compares a
proposed feature bag against a no-sidecar control bag, marks frames containing
observations absent from the control as learned/LoFTR sidecar triggers, and
applies a calibrated backend q schedule only for a short window after each
trigger.  All other frames can be forced to q=1 so the KLT backbone is not
globally down-weighted.
"""

from __future__ import annotations

import argparse
import csv
import math
from pathlib import Path

import numpy as np
import rosbag
from sensor_msgs.msg import ChannelFloat32


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--proposed-bag", required=True)
    parser.add_argument("--control-bag", required=True)
    parser.add_argument("--output-bag", required=True)
    parser.add_argument("--stats-csv", required=True)
    parser.add_argument("--feature-topic", default="/feature_tracker/feature")
    parser.add_argument("--hold-frames", type=int, default=12)
    parser.add_argument("--active-mode", choices=("blend", "const", "raw"), default="blend")
    parser.add_argument("--active-alpha", type=float, default=0.85)
    parser.add_argument("--inactive-mode", choices=("const", "raw", "blend"), default="const")
    parser.add_argument("--inactive-alpha", type=float, default=0.85)
    parser.add_argument(
        "--pretrigger-inactive-mode",
        choices=("const", "raw", "blend"),
        default=None,
        help="Optional inactive q mode before the first sidecar trigger; defaults to --inactive-mode.",
    )
    parser.add_argument(
        "--pretrigger-inactive-alpha",
        type=float,
        default=None,
        help="Optional inactive blend alpha before the first sidecar trigger.",
    )
    parser.add_argument(
        "--pretrigger-max-frames",
        type=int,
        default=None,
        help=(
            "Use the pretrigger inactive mode only for the first N feature "
            "frames before a sidecar trigger. After N frames without a trigger, "
            "fall back to --no-trigger-inactive-mode."
        ),
    )
    parser.add_argument(
        "--no-trigger-inactive-mode",
        choices=("const", "raw", "blend"),
        default=None,
        help=(
            "Inactive q mode for frames before any sidecar trigger after "
            "--pretrigger-max-frames expires; defaults to pretrigger mode."
        ),
    )
    parser.add_argument(
        "--no-trigger-inactive-alpha",
        type=float,
        default=None,
        help="Optional no-trigger inactive blend alpha.",
    )
    parser.add_argument(
        "--posttrigger-inactive-mode",
        choices=("const", "raw", "blend"),
        default=None,
        help="Optional inactive q mode after a sidecar trigger; defaults to --inactive-mode.",
    )
    parser.add_argument(
        "--posttrigger-inactive-alpha",
        type=float,
        default=None,
        help="Optional inactive blend alpha after a sidecar trigger.",
    )
    parser.add_argument("--sidecar-min-count", type=int, default=1)
    parser.add_argument("--min-q", type=float, default=0.05)
    args = parser.parse_args()

    control_ids = _load_control_ids(Path(args.control_bag), args.feature_topic)
    stats = _rewrite(
        proposed_bag=Path(args.proposed_bag),
        output_bag=Path(args.output_bag),
        control_ids=control_ids,
        feature_topic=args.feature_topic,
        hold_frames=max(0, int(args.hold_frames)),
        active_mode=str(args.active_mode),
        active_alpha=float(args.active_alpha),
        inactive_mode=str(args.inactive_mode),
        inactive_alpha=float(args.inactive_alpha),
        pretrigger_inactive_mode=(
            str(args.pretrigger_inactive_mode)
            if args.pretrigger_inactive_mode is not None
            else str(args.inactive_mode)
        ),
        pretrigger_inactive_alpha=(
            float(args.pretrigger_inactive_alpha)
            if args.pretrigger_inactive_alpha is not None
            else float(args.inactive_alpha)
        ),
        pretrigger_max_frames=(
            None if args.pretrigger_max_frames is None else int(args.pretrigger_max_frames)
        ),
        no_trigger_inactive_mode=(
            str(args.no_trigger_inactive_mode)
            if args.no_trigger_inactive_mode is not None
            else (
                str(args.pretrigger_inactive_mode)
                if args.pretrigger_inactive_mode is not None
                else str(args.inactive_mode)
            )
        ),
        no_trigger_inactive_alpha=(
            float(args.no_trigger_inactive_alpha)
            if args.no_trigger_inactive_alpha is not None
            else (
                float(args.pretrigger_inactive_alpha)
                if args.pretrigger_inactive_alpha is not None
                else float(args.inactive_alpha)
            )
        ),
        posttrigger_inactive_mode=(
            str(args.posttrigger_inactive_mode)
            if args.posttrigger_inactive_mode is not None
            else str(args.inactive_mode)
        ),
        posttrigger_inactive_alpha=(
            float(args.posttrigger_inactive_alpha)
            if args.posttrigger_inactive_alpha is not None
            else float(args.inactive_alpha)
        ),
        sidecar_min_count=max(1, int(args.sidecar_min_count)),
        min_q=float(args.min_q),
    )
    stats.update(
        {
            "proposed_bag": str(Path(args.proposed_bag)),
            "control_bag": str(Path(args.control_bag)),
            "output_bag": str(Path(args.output_bag)),
            "hold_frames": int(args.hold_frames),
            "active_mode": str(args.active_mode),
            "active_alpha": float(args.active_alpha),
            "inactive_mode": str(args.inactive_mode),
            "inactive_alpha": float(args.inactive_alpha),
            "pretrigger_inactive_mode": (
                str(args.pretrigger_inactive_mode)
                if args.pretrigger_inactive_mode is not None
                else str(args.inactive_mode)
            ),
            "pretrigger_inactive_alpha": (
                float(args.pretrigger_inactive_alpha)
                if args.pretrigger_inactive_alpha is not None
                else float(args.inactive_alpha)
            ),
            "pretrigger_max_frames": (
                "" if args.pretrigger_max_frames is None else int(args.pretrigger_max_frames)
            ),
            "no_trigger_inactive_mode": (
                str(args.no_trigger_inactive_mode)
                if args.no_trigger_inactive_mode is not None
                else (
                    str(args.pretrigger_inactive_mode)
                    if args.pretrigger_inactive_mode is not None
                    else str(args.inactive_mode)
                )
            ),
            "no_trigger_inactive_alpha": (
                float(args.no_trigger_inactive_alpha)
                if args.no_trigger_inactive_alpha is not None
                else (
                    float(args.pretrigger_inactive_alpha)
                    if args.pretrigger_inactive_alpha is not None
                    else float(args.inactive_alpha)
                )
            ),
            "posttrigger_inactive_mode": (
                str(args.posttrigger_inactive_mode)
                if args.posttrigger_inactive_mode is not None
                else str(args.inactive_mode)
            ),
            "posttrigger_inactive_alpha": (
                float(args.posttrigger_inactive_alpha)
                if args.posttrigger_inactive_alpha is not None
                else float(args.inactive_alpha)
            ),
            "sidecar_min_count": int(args.sidecar_min_count),
        }
    )
    _write_stats(Path(args.stats_csv), stats)
    print(f"wrote {args.output_bag}")
    print(
        "feature_frames={feature_frames} trigger_frames={trigger_frames} "
        "active_frames={active_frames} sidecar_observations={sidecar_observations} "
        "backend_q_median={backend_q_median:.6f}".format(**stats)
    )
    return 0


def _load_control_ids(path: Path, feature_topic: str) -> dict[int, set[int]]:
    frames: dict[int, set[int]] = {}
    with rosbag.Bag(str(path), "r") as bag:
        for topic, msg, _stamp in bag.read_messages(topics=[feature_topic]):
            key = _stamp_key(msg.header.stamp.to_sec())
            frames[key] = {int(round(item)) for item in _channel_values(msg, "id")}
    return frames


def _rewrite(
    proposed_bag: Path,
    output_bag: Path,
    control_ids: dict[int, set[int]],
    feature_topic: str,
    hold_frames: int,
    active_mode: str,
    active_alpha: float,
    inactive_mode: str,
    inactive_alpha: float,
    pretrigger_inactive_mode: str,
    pretrigger_inactive_alpha: float,
    pretrigger_max_frames: int | None,
    no_trigger_inactive_mode: str,
    no_trigger_inactive_alpha: float,
    posttrigger_inactive_mode: str,
    posttrigger_inactive_alpha: float,
    sidecar_min_count: int,
    min_q: float,
) -> dict[str, float | int]:
    output_bag.parent.mkdir(parents=True, exist_ok=True)
    feature_frames = 0
    trigger_frames = 0
    active_frames = 0
    missing_control_frames = 0
    sidecar_observations = 0
    classical_observations = 0
    active_until = 0
    recovery_seen = False
    backend_q_values: list[float] = []
    raw_q_values: list[float] = []
    sidecars_per_frame: list[int] = []
    active_frame_indices: list[int] = []
    trigger_frame_indices: list[int] = []

    with rosbag.Bag(str(proposed_bag), "r") as in_bag, rosbag.Bag(str(output_bag), "w") as out_bag:
        for topic, msg, stamp in in_bag.read_messages():
            if topic == feature_topic and hasattr(msg, "channels"):
                frame_index = feature_frames
                feature_frames += 1
                channels = {channel.name: channel for channel in msg.channels}
                raw_q = np.asarray(_channel_values(msg, "quality"), dtype=np.float32)
                raw_q = np.clip(raw_q, min_q, 1.0)
                ids = [int(round(item)) for item in _channel_values(msg, "id")]
                key = _stamp_key(msg.header.stamp.to_sec())
                frame_control_ids = control_ids.get(key)
                if frame_control_ids is None:
                    missing_control_frames += 1
                    frame_control_ids = set()
                sidecar_mask = np.asarray(
                    [feature_id not in frame_control_ids for feature_id in ids],
                    dtype=bool,
                )
                sidecar_count = int(np.count_nonzero(sidecar_mask))
                if sidecar_count >= int(sidecar_min_count):
                    trigger_frames += 1
                    trigger_frame_indices.append(frame_index)
                    active_until = max(active_until, frame_index + max(1, int(hold_frames)))
                    recovery_seen = True
                active = frame_index < active_until
                if active:
                    active_frames += 1
                    active_frame_indices.append(frame_index)
                    backend_q = _map_quality(raw_q, active_mode, active_alpha, min_q)
                elif recovery_seen:
                    backend_q = _map_quality(
                        raw_q,
                        posttrigger_inactive_mode,
                        posttrigger_inactive_alpha,
                        min_q,
                    )
                elif (
                    pretrigger_max_frames is not None
                    and frame_index >= max(0, int(pretrigger_max_frames))
                ):
                    backend_q = _map_quality(
                        raw_q,
                        no_trigger_inactive_mode,
                        no_trigger_inactive_alpha,
                        min_q,
                    )
                else:
                    backend_q = _map_quality(
                        raw_q,
                        pretrigger_inactive_mode,
                        pretrigger_inactive_alpha,
                        min_q,
                    )
                sigma = 1.0 / np.sqrt(np.maximum(min_q, backend_q))
                channels["quality"].values = [float(item) for item in backend_q]
                sigma_channel = channels.get("sigma")
                if sigma_channel is None:
                    sigma_channel = ChannelFloat32(name="sigma")
                    msg.channels.append(sigma_channel)
                sigma_channel.values = [float(item) for item in sigma]
                raw_q_values.extend(float(item) for item in raw_q)
                backend_q_values.extend(float(item) for item in backend_q)
                sidecar_observations += sidecar_count
                classical_observations += max(0, len(ids) - sidecar_count)
                sidecars_per_frame.append(sidecar_count)
            out_bag.write(topic, msg, stamp)

    raw_arr = np.asarray(raw_q_values, dtype=np.float64)
    backend_arr = np.asarray(backend_q_values, dtype=np.float64)
    return {
        "feature_frames": feature_frames,
        "trigger_frames": trigger_frames,
        "active_frames": active_frames,
        "missing_control_frames": missing_control_frames,
        "sidecar_observations": sidecar_observations,
        "classical_observations": classical_observations,
        "sidecars_per_frame_max": _finite_stat(sidecars_per_frame, np.max),
        "raw_q_median": _finite_stat(raw_arr, np.median),
        "raw_q_mean": _finite_stat(raw_arr, np.mean),
        "backend_q_median": _finite_stat(backend_arr, np.median),
        "backend_q_mean": _finite_stat(backend_arr, np.mean),
        "backend_q_min": _finite_stat(backend_arr, np.min),
        "backend_q_max": _finite_stat(backend_arr, np.max),
        "trigger_frame_first": trigger_frame_indices[0] if trigger_frame_indices else -1,
        "trigger_frame_last": trigger_frame_indices[-1] if trigger_frame_indices else -1,
        "active_frame_first": active_frame_indices[0] if active_frame_indices else -1,
        "active_frame_last": active_frame_indices[-1] if active_frame_indices else -1,
    }


def _map_quality(q: np.ndarray, mode: str, alpha: float, min_q: float) -> np.ndarray:
    q = np.clip(q.astype(np.float32), min_q, 1.0)
    if mode == "raw":
        return q
    if mode == "const":
        return np.ones_like(q, dtype=np.float32)
    if mode == "blend":
        a = float(np.clip(alpha, 0.0, 1.0))
        return np.clip(a + (1.0 - a) * q, min_q, 1.0).astype(np.float32)
    raise ValueError(mode)


def _channel_values(msg, name: str) -> list[float]:
    for channel in msg.channels:
        if channel.name == name:
            return list(channel.values)
    raise ValueError(f"missing channel {name}")


def _stamp_key(stamp_s: float) -> int:
    return int(round(float(stamp_s) * 1e9))


def _finite_stat(values, fn) -> float:
    arr = np.asarray(values, dtype=np.float64)
    arr = arr[np.isfinite(arr)]
    if arr.size == 0:
        return float("nan")
    return float(fn(arr))


def _write_stats(path: Path, row: dict[str, float | int | str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(row.keys()))
        writer.writeheader()
        writer.writerow(row)


if __name__ == "__main__":
    raise SystemExit(main())
