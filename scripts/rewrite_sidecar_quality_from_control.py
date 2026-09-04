#!/usr/bin/env python3
"""Rewrite q/sigma only for observations absent from a no-sidecar control bag."""

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
    parser.add_argument("--sidecar-details-csv")
    parser.add_argument("--feature-topic", default="/feature_tracker/feature")
    parser.add_argument("--classical-q", type=float, default=1.0)
    parser.add_argument("--sidecar-q", type=float, default=0.80)
    parser.add_argument("--sidecar-early-q", type=float)
    parser.add_argument("--sidecar-late-q", type=float)
    parser.add_argument(
        "--early-frame-count",
        type=int,
        default=0,
        help="Use sidecar-early-q for this many feature frames, then sidecar-late-q.",
    )
    parser.add_argument("--min-q", type=float, default=0.05)
    args = parser.parse_args()

    control_ids = load_control_ids(Path(args.control_bag), args.feature_topic)
    stats = rewrite(
        proposed_bag=Path(args.proposed_bag),
        output_bag=Path(args.output_bag),
        control_ids=control_ids,
        feature_topic=args.feature_topic,
        classical_q=float(args.classical_q),
        sidecar_q=float(args.sidecar_q),
        sidecar_early_q=args.sidecar_early_q,
        sidecar_late_q=args.sidecar_late_q,
        early_frame_count=int(args.early_frame_count),
        min_q=float(args.min_q),
        sidecar_details_csv=Path(args.sidecar_details_csv) if args.sidecar_details_csv else None,
    )
    stats.update(
        {
            "proposed_bag": str(Path(args.proposed_bag)),
            "control_bag": str(Path(args.control_bag)),
            "output_bag": str(Path(args.output_bag)),
        "classical_q": float(args.classical_q),
        "sidecar_q": float(args.sidecar_q),
        "sidecar_early_q": args.sidecar_early_q,
        "sidecar_late_q": args.sidecar_late_q,
        "early_frame_count": int(args.early_frame_count),
    }
    )
    write_stats(Path(args.stats_csv), stats)
    print(f"wrote {args.output_bag}")
    print(
        "feature_frames={feature_frames} sidecar_observations={sidecar_observations} "
        "classical_observations={classical_observations}".format(**stats)
    )
    return 0


def load_control_ids(path: Path, feature_topic: str) -> dict[int, set[int]]:
    out: dict[int, set[int]] = {}
    with rosbag.Bag(str(path), "r") as bag:
        for topic, msg, _ in bag.read_messages(topics=[feature_topic]):
            key = stamp_key(msg.header.stamp.to_sec())
            ids = channel_values(msg, "id")
            out[key] = {int(round(item)) for item in ids}
    return out


def rewrite(
    proposed_bag: Path,
    output_bag: Path,
    control_ids: dict[int, set[int]],
    feature_topic: str,
    classical_q: float,
    sidecar_q: float,
    sidecar_early_q: float | None,
    sidecar_late_q: float | None,
    early_frame_count: int,
    min_q: float,
    sidecar_details_csv: Path | None,
) -> dict[str, float | int]:
    output_bag.parent.mkdir(parents=True, exist_ok=True)
    classical_q = float(np.clip(classical_q, min_q, 1.0))
    sidecar_q = float(np.clip(sidecar_q, min_q, 1.0))
    if sidecar_early_q is not None:
        sidecar_early_q = float(np.clip(sidecar_early_q, min_q, 1.0))
    if sidecar_late_q is not None:
        sidecar_late_q = float(np.clip(sidecar_late_q, min_q, 1.0))

    feature_frames = 0
    missing_control_frames = 0
    sidecar_observations = 0
    classical_observations = 0
    points_per_frame: list[int] = []
    sidecars_per_frame: list[int] = []
    detail_rows: list[dict[str, float | int]] = []

    with rosbag.Bag(str(proposed_bag), "r") as in_bag, rosbag.Bag(str(output_bag), "w") as out_bag:
        for topic, msg, stamp in in_bag.read_messages():
            if topic == feature_topic:
                feature_frames += 1
                key = stamp_key(msg.header.stamp.to_sec())
                frame_control_ids = control_ids.get(key)
                if frame_control_ids is None:
                    missing_control_frames += 1
                    frame_control_ids = set()
                ids = [int(round(item)) for item in channel_values(msg, "id")]
                q_values = []
                sigma_values = []
                frame_sidecars = 0
                for feature_id in ids:
                    is_sidecar = feature_id not in frame_control_ids
                    q = classical_q
                    if is_sidecar:
                        q = scheduled_sidecar_q(
                            default_q=sidecar_q,
                            early_q=sidecar_early_q,
                            late_q=sidecar_late_q,
                            early_frame_count=early_frame_count,
                            frame_index=feature_frames - 1,
                        )
                    q_values.append(q)
                    sigma_values.append(1.0 / math.sqrt(max(min_q, q)))
                    if is_sidecar:
                        sidecar_observations += 1
                        frame_sidecars += 1
                        detail_rows.append(
                            {
                                "frame_index": feature_frames - 1,
                                "stamp_s": msg.header.stamp.to_sec(),
                                "feature_id": feature_id,
                                "q": q,
                                "points_in_frame": len(ids),
                            }
                        )
                    else:
                        classical_observations += 1
                set_channel(msg, "quality", q_values)
                set_channel(msg, "sigma", sigma_values)
                points_per_frame.append(len(ids))
                sidecars_per_frame.append(frame_sidecars)
            out_bag.write(topic, msg, stamp)

    if sidecar_details_csv is not None:
        write_rows(sidecar_details_csv, detail_rows)

    return {
        "feature_frames": feature_frames,
        "missing_control_frames": missing_control_frames,
        "classical_observations": classical_observations,
        "sidecar_observations": sidecar_observations,
        "points_per_frame_median": finite_stat(points_per_frame, np.median),
        "sidecars_per_frame_max": finite_stat(sidecars_per_frame, np.max),
        "sidecars_per_frame_sum": int(sum(sidecars_per_frame)),
    }


def scheduled_sidecar_q(
    default_q: float,
    early_q: float | None,
    late_q: float | None,
    early_frame_count: int,
    frame_index: int,
) -> float:
    if early_q is None and late_q is None:
        return default_q
    if early_frame_count > 0 and frame_index < early_frame_count:
        return early_q if early_q is not None else default_q
    return late_q if late_q is not None else default_q


def stamp_key(stamp_s: float) -> int:
    return int(round(float(stamp_s) * 1e9))


def channel_values(msg, name: str) -> list[float]:
    for channel in msg.channels:
        if channel.name == name:
            return list(channel.values)
    raise ValueError(f"missing channel {name}")


def set_channel(msg, name: str, values: list[float]) -> None:
    for channel in msg.channels:
        if channel.name == name:
            channel.values = [float(item) for item in values]
            return
    channel = ChannelFloat32(name=name)
    channel.values = [float(item) for item in values]
    msg.channels.append(channel)


def finite_stat(values: list[int], fn) -> float:
    if not values:
        return float("nan")
    arr = np.asarray(values, dtype=np.float64)
    return float(fn(arr))


def write_stats(path: Path, row: dict[str, float | int | str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(row.keys()))
        writer.writeheader()
        writer.writerow(row)


def write_rows(path: Path, rows: list[dict[str, float | int]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = ["frame_index", "stamp_s", "feature_id", "q", "points_in_frame"]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


if __name__ == "__main__":
    raise SystemExit(main())
