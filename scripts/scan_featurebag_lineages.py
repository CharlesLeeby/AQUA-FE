#!/usr/bin/env python3
"""Audit learned-seeded lineages in existing frontend feature bags.

The scanner is read-only. It uses ``frontend_metrics.csv`` to skip runs that
did not export the requested learned source, then measures lineage lifetime,
novelty to the run's classical backbone, and motion consistency.
"""

from __future__ import annotations

import argparse
import csv
import math
import statistics
from pathlib import Path

import rosbag


LEARNED_SOURCE_CODES = {10, 20, 30}
FLOAT32_EXACT_INT_LIMIT = 16_777_216


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--family-root",
        action="append",
        required=True,
        metavar="NAME=PATH",
        help="Family name and log root. Repeat for multiple families.",
    )
    parser.add_argument("--output-csv", required=True)
    parser.add_argument("--feature-topic", default="/feature_tracker/feature")
    parser.add_argument("--source-code", type=int, default=20)
    parser.add_argument("--metrics-column", default="exported_xfeat_features")
    parser.add_argument("--min-observations", type=int, default=5)
    parser.add_argument("--rank-observations", type=int, default=5)
    parser.add_argument("--min-median-distance-px", type=float, default=40.0)
    parser.add_argument("--max-median-motion-ratio", type=float, default=1.5)
    parser.add_argument("--learned-id-min", type=int, default=10_000_000)
    args = parser.parse_args()

    family_roots = _parse_family_roots(args.family_root)
    rows: list[dict[str, object]] = []
    for family, root in family_roots.items():
        bags = _active_feature_bags(root, args.metrics_column)
        print(f"{family}: scanning {len(bags)} XFeat-active bags", flush=True)
        for index, (bag_path, metrics_total) in enumerate(bags, start=1):
            try:
                rows.extend(
                    _scan_bag(
                        family=family,
                        bag_path=bag_path,
                        metrics_total=metrics_total,
                        feature_topic=args.feature_topic,
                        source_code=args.source_code,
                        min_observations=args.min_observations,
                        rank_observations=args.rank_observations,
                        min_median_distance_px=args.min_median_distance_px,
                        max_median_motion_ratio=args.max_median_motion_ratio,
                        learned_id_min=args.learned_id_min,
                    )
                )
            except Exception as exc:  # Keep a broad historical scan moving.
                print(f"warning: failed to scan {bag_path}: {exc}", flush=True)
            if index % 50 == 0:
                print(f"{family}: {index}/{len(bags)}", flush=True)

    rows.sort(key=_sort_key)
    output_path = Path(args.output_csv)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    _write_rows(output_path, rows)
    print(f"wrote {output_path}")
    for family in family_roots:
        family_rows = [row for row in rows if row["family"] == family]
        passed = [row for row in family_rows if row["passes_same_rule"]]
        print(
            f"{family}: lineages_ge{args.min_observations}={len(family_rows)} "
            f"passed={len(passed)}"
        )
        for row in passed[:12]:
            print(
                "  post={post_confirmation_observations} "
                "dist={median_nearest_classical_px:.3f} "
                "ratio={median_motion_ratio_to_classical:.3f} "
                "id={feature_id} {run_dir}".format(**row)
            )
    return 0


def _parse_family_roots(values: list[str]) -> dict[str, Path]:
    roots: dict[str, Path] = {}
    for value in values:
        if "=" not in value:
            raise ValueError(f"expected NAME=PATH, got {value!r}")
        name, raw_path = value.split("=", 1)
        path = Path(raw_path).expanduser().resolve()
        if not name or not path.is_dir():
            raise ValueError(f"invalid family root: {value!r}")
        roots[name] = path
    return roots


def _active_feature_bags(root: Path, metrics_column: str) -> list[tuple[Path, int]]:
    bags: list[tuple[Path, int]] = []
    for metrics_path in root.rglob("frontend_metrics.csv"):
        total = 0
        try:
            with metrics_path.open(newline="", errors="replace") as stream:
                for row in csv.DictReader(stream):
                    total += _safe_int(row.get(metrics_column, 0), 0)
        except (OSError, csv.Error):
            continue
        bag_path = metrics_path.with_name("features.bag")
        if total > 0 and bag_path.is_file():
            bags.append((bag_path, total))
    return sorted(bags, key=lambda item: str(item[0]))


def _scan_bag(
    *,
    family: str,
    bag_path: Path,
    metrics_total: int,
    feature_topic: str,
    source_code: int,
    min_observations: int,
    rank_observations: int,
    min_median_distance_px: float,
    max_median_motion_ratio: float,
    learned_id_min: int,
) -> list[dict[str, object]]:
    frames: list[list[tuple[int, int, bool, float, float, float, float]]] = []
    seed_ids: set[int] = set()
    seed_counts: dict[int, int] = {}
    with rosbag.Bag(str(bag_path), "r") as bag:
        for _topic, msg, _stamp in bag.read_messages(topics=[feature_topic]):
            count = len(msg.points)
            ids = _channel_values(msg, "id", count, -1.0)
            sources = _channel_values(msg, "source_code", count, 0.0)
            learned = _channel_values(msg, "is_learned", count, 0.0)
            p_u = _channel_values(msg, "p_u", count, float("nan"))
            p_v = _channel_values(msg, "p_v", count, float("nan"))
            velocity_x = _channel_values(msg, "velocity_x", count, float("nan"))
            velocity_y = _channel_values(msg, "velocity_y", count, float("nan"))
            observations = []
            seen_ids: set[int] = set()
            for index in range(count):
                feature_id = _safe_int(ids[index], -1)
                if feature_id < 0 or feature_id in seen_ids:
                    continue
                seen_ids.add(feature_id)
                observation_source = _safe_int(sources[index], 0)
                is_learned = _safe_bool(learned[index])
                observations.append(
                    (
                        feature_id,
                        observation_source,
                        is_learned,
                        float(p_u[index]),
                        float(p_v[index]),
                        float(velocity_x[index]),
                        float(velocity_y[index]),
                    )
                )
                if observation_source == source_code:
                    seed_ids.add(feature_id)
                    seed_counts[feature_id] = seed_counts.get(feature_id, 0) + 1
            frames.append(observations)

    tracks: dict[int, list[tuple[int, float, float, float, float, int]]] = {
        feature_id: [] for feature_id in seed_ids
    }
    classical_pixels: list[list[tuple[float, float]]] = []
    classical_speeds: list[float | None] = []
    for frame_index, observations in enumerate(frames):
        pixels: list[tuple[float, float]] = []
        speeds: list[float] = []
        for feature_id, observation_source, is_learned, u, v, vx, vy in observations:
            belongs_to_learned_lineage = feature_id in seed_ids
            is_classical = not (
                is_learned
                or observation_source in LEARNED_SOURCE_CODES
                or feature_id >= learned_id_min
                or belongs_to_learned_lineage
            )
            if is_classical:
                if math.isfinite(u) and math.isfinite(v):
                    pixels.append((u, v))
                if math.isfinite(vx) and math.isfinite(vy):
                    speeds.append(math.hypot(vx, vy))
            if belongs_to_learned_lineage:
                tracks[feature_id].append(
                    (frame_index, u, v, vx, vy, observation_source)
                )
        classical_pixels.append(pixels)
        classical_speeds.append(statistics.median(speeds) if speeds else None)

    rows = []
    for feature_id, observations in tracks.items():
        if len(observations) < min_observations:
            continue
        first_observations = observations[:rank_observations]
        distances: list[float] = []
        motion_ratios: list[float] = []
        for frame_index, u, v, vx, vy, _source in first_observations:
            frame_pixels = classical_pixels[frame_index]
            if frame_pixels and math.isfinite(u) and math.isfinite(v):
                distances.append(
                    min(
                        math.hypot(u - classical_u, v - classical_v)
                        for classical_u, classical_v in frame_pixels
                    )
                )
            base_speed = classical_speeds[frame_index]
            if (
                base_speed is not None
                and base_speed > 1e-9
                and math.isfinite(vx)
                and math.isfinite(vy)
            ):
                motion_ratios.append(math.hypot(vx, vy) / base_speed)

        distance_score = (
            float(statistics.median(distances))
            if len(distances) == rank_observations
            else float("nan")
        )
        motion_score = (
            float(statistics.median(motion_ratios))
            if len(motion_ratios) == rank_observations
            else float("nan")
        )
        passes = (
            math.isfinite(distance_score)
            and distance_score >= min_median_distance_px
            and math.isfinite(motion_score)
            and motion_score <= max_median_motion_ratio
        )
        rows.append(
            {
                "family": family,
                "run_dir": str(bag_path.parent),
                "feature_id": feature_id,
                "lineage_observations": len(observations),
                "seed_observations": seed_counts.get(feature_id, 0),
                "first_frame": observations[0][0],
                "confirmation_frame": observations[rank_observations - 1][0],
                "last_frame": observations[-1][0],
                "post_confirmation_observations": max(
                    0, len(observations) - rank_observations + 1
                ),
                "median_nearest_classical_px": distance_score,
                "median_motion_ratio_to_classical": motion_score,
                "passes_same_rule": int(passes),
                "causal_selected": 0,
                "feature_frames": len(frames),
                "metrics_exported_source_total": metrics_total,
            }
        )
    eligible_rows = [row for row in rows if row["passes_same_rule"]]
    if eligible_rows:
        selected_row = min(
            eligible_rows,
            key=lambda row: (
                int(row["confirmation_frame"]),
                -float(row["median_nearest_classical_px"]),
                int(row["feature_id"]),
            ),
        )
        selected_row["causal_selected"] = 1
    return rows


def _channel_values(msg, name: str, count: int, default: float) -> list[float]:
    for channel in msg.channels:
        if channel.name != name:
            continue
        values = list(channel.values[:count])
        if len(values) < count:
            values.extend([default] * (count - len(values)))
        return values
    return [default] * count


def _safe_int(value: object, default: int) -> int:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return default
    if not math.isfinite(numeric):
        return default
    result = int(round(numeric))
    if abs(result) >= FLOAT32_EXACT_INT_LIMIT:
        return default
    return result


def _safe_bool(value: object) -> bool:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return False
    return math.isfinite(numeric) and bool(round(numeric))


def _sort_key(row: dict[str, object]) -> tuple[object, ...]:
    distance = float(row["median_nearest_classical_px"])
    finite_distance = distance if math.isfinite(distance) else -1.0
    return (
        -int(row["passes_same_rule"]),
        -int(row["post_confirmation_observations"]),
        -finite_distance,
        str(row["family"]),
        str(row["run_dir"]),
        int(row["feature_id"]),
    )


def _write_rows(output_path: Path, rows: list[dict[str, object]]) -> None:
    fieldnames = [
        "family",
        "run_dir",
        "feature_id",
        "lineage_observations",
        "seed_observations",
        "first_frame",
        "confirmation_frame",
        "last_frame",
        "post_confirmation_observations",
        "median_nearest_classical_px",
        "median_motion_ratio_to_classical",
        "passes_same_rule",
        "causal_selected",
        "feature_frames",
        "metrics_exported_source_total",
    ]
    with output_path.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


if __name__ == "__main__":
    raise SystemExit(main())
