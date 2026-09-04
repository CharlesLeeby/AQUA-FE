#!/usr/bin/env python3
"""Recover exact per-frame lineage statistics from an existing feature bag.

This is intentionally read-only: it does not run the frontend or VINS and it
does not write a ROS bag.  It complements the stage-level KLT probe CSVs by
recovering the exact births, deaths, active ages, and complete/censored
lifetimes that were present in an already-exported feature bag.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import statistics
from collections import Counter, defaultdict
from pathlib import Path

import rosbag


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--feature-bag", required=True)
    parser.add_argument("--metrics-csv", required=True)
    parser.add_argument("--sequence", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--feature-topic", default="/feature_tracker/feature")
    return parser.parse_args()


def channel(message, name: str, default: float = 0.0) -> list[float]:
    for item in message.channels:
        if item.name == name:
            return list(item.values)
    return [default] * len(message.points)


def family(code: int) -> str:
    if code == 20:
        return "xfeat_seed"
    if code in {10, 30}:
        return "other_learned"
    return "gftt_klt"


def percentile(counter: Counter[int], quantile: float) -> float:
    total = sum(counter.values())
    if not total:
        return float("nan")
    rank = quantile * (total - 1)
    cumulative = 0
    for value in sorted(counter):
        cumulative += counter[value]
        if rank < cumulative:
            return float(value)
    return float(max(counter))


def finite(value: str | float | int, default: float = float("nan")) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default
    return result if math.isfinite(result) else default


def main() -> int:
    args = parse_args()
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    metrics = list(csv.DictReader(Path(args.metrics_csv).open(encoding="utf-8")))

    active: dict[int, dict[str, int | str]] = {}
    hist: dict[str, Counter[int]] = defaultdict(Counter)
    censored: dict[str, Counter[int]] = defaultdict(Counter)
    rows: list[dict[str, object]] = []
    previous_ids: set[int] = set()

    with rosbag.Bag(args.feature_bag, "r") as bag:
        messages = bag.read_messages(topics=[args.feature_topic])
        for frame_index, (_topic, message, _bag_stamp) in enumerate(messages):
            ids = [int(round(value)) for value in channel(message, "id")]
            codes = [int(round(value)) for value in channel(message, "source_code")]
            sources = {track_id: family(code) for track_id, code in zip(ids, codes)}
            current_ids = set(ids)
            births = current_ids - previous_ids
            deaths = previous_ids - current_ids
            for track_id in deaths:
                meta = active.pop(track_id)
                hist[str(meta["source"])][int(meta["observations"])] += 1
            for track_id in ids:
                if track_id in active:
                    active[track_id]["observations"] = int(active[track_id]["observations"]) + 1
                    if sources[track_id] == "xfeat_seed":
                        active[track_id]["source"] = "xfeat_seed"
                else:
                    active[track_id] = {"source": sources[track_id], "observations": 1}

            metric = metrics[frame_index] if frame_index < len(metrics) else {}
            ages = [int(active[track_id]["observations"]) for track_id in ids]
            source_counts = Counter(sources.values())
            birth_sources = Counter(sources[track_id] for track_id in births)
            rows.append(
                {
                    "sequence": args.sequence,
                    "frame_index": frame_index,
                    "timestamp": f"{message.header.stamp.to_sec():.9f}",
                    "output_tracks": len(ids),
                    "output_gftt_klt": source_counts["gftt_klt"],
                    "output_xfeat": source_counts["xfeat_seed"],
                    "output_other_learned": source_counts["other_learned"],
                    "births_total": len(births),
                    "births_gftt_klt": birth_sources["gftt_klt"],
                    "births_xfeat": birth_sources["xfeat_seed"],
                    "births_other_learned": birth_sources["other_learned"],
                    "deaths_total": len(deaths),
                    "median_active_age_selected_frames": statistics.median(ages) if ages else float("nan"),
                    "active_age_ge5_ratio": sum(age >= 5 for age in ages) / len(ages) if ages else 0.0,
                    "frontend_reported_median_track_age": finite(metric.get("median_track_age", "nan")),
                    "dropout_ratio": finite(metric.get("dropout_ratio", "nan")),
                    "flat_region_ratio": finite(metric.get("flat_region_ratio", "nan")),
                    "degradation_score": finite(metric.get("degradation_score", "nan")),
                    "grid_coverage": finite(metric.get("grid_coverage", "nan")),
                    "learned_candidates": int(finite(metric.get("learned_candidate_count", 0), 0)),
                    "xfeat_confirmed": int(finite(metric.get("learned_confirmed_xfeat_count", 0), 0)),
                    "klt_stage_counts_available": 0,
                    "klt_stage_counts_note": "see paired baseline probe CSV; old feature bag stores output lineage, not LK internal masks",
                }
            )
            previous_ids = current_ids

    for meta in active.values():
        censored[str(meta["source"])][int(meta["observations"])] += 1

    per_frame_path = output_dir / "per_frame_lineage.csv"
    with per_frame_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)

    histogram_path = output_dir / "lifetime_histogram.csv"
    with histogram_path.open("w", newline="", encoding="utf-8") as handle:
        fields = ("sequence", "profile", "lineage", "lifetime_selected_frames", "track_count", "right_censored_count")
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for lineage in sorted(set(hist) | set(censored)):
            for lifetime in sorted(set(hist[lineage]) | set(censored[lineage])):
                writer.writerow(
                    {
                        "sequence": args.sequence,
                        "profile": "original_feature_bag",
                        "lineage": lineage,
                        "lifetime_selected_frames": lifetime,
                        "track_count": hist[lineage][lifetime],
                        "right_censored_count": censored[lineage][lifetime],
                    }
                )

    complete_all: Counter[int] = Counter()
    for counter in hist.values():
        complete_all.update(counter)
    summary = {
        "sequence": args.sequence,
        "profile": "original_feature_bag",
        "feature_bag": str(Path(args.feature_bag).resolve()),
        "metrics_csv": str(Path(args.metrics_csv).resolve()),
        "frames": len(rows),
        "complete_track_count": sum(complete_all.values()),
        "complete_lifetime_median_selected_frames": percentile(complete_all, 0.5),
        "complete_lifetime_p75_selected_frames": percentile(complete_all, 0.75),
        "complete_lifetime_p90_selected_frames": percentile(complete_all, 0.9),
        "lifetime_one_fraction": complete_all[1] / max(1, sum(complete_all.values())),
        "gftt_klt_complete_track_count": sum(hist["gftt_klt"].values()),
        "gftt_klt_lifetime_median_selected_frames": percentile(hist["gftt_klt"], 0.5),
        "gftt_klt_lifetime_p75_selected_frames": percentile(hist["gftt_klt"], 0.75),
        "gftt_klt_lifetime_p90_selected_frames": percentile(hist["gftt_klt"], 0.9),
        "gftt_klt_lifetime_one_fraction": hist["gftt_klt"][1] / max(1, sum(hist["gftt_klt"].values())),
        "xfeat_complete_track_count": sum(hist["xfeat_seed"].values()),
        "xfeat_lifetime_median_selected_frames": percentile(hist["xfeat_seed"], 0.5),
        "xfeat_lifetime_p75_selected_frames": percentile(hist["xfeat_seed"], 0.75),
        "xfeat_lifetime_p90_selected_frames": percentile(hist["xfeat_seed"], 0.9),
        "selected_median_births": statistics.median(int(row["births_total"]) for row in rows),
        "selected_mean_births": statistics.fmean(int(row["births_total"]) for row in rows),
        "selected_median_deaths": statistics.median(int(row["deaths_total"]) for row in rows),
        "selected_median_active_age": statistics.median(float(row["median_active_age_selected_frames"]) for row in rows),
        "selected_median_dropout_ratio": statistics.median(float(row["dropout_ratio"]) for row in rows if math.isfinite(float(row["dropout_ratio"]))),
        "right_censored_track_count": sum(sum(counter.values()) for counter in censored.values()),
        "per_frame_csv": str(per_frame_path.resolve()),
        "lifetime_histogram_csv": str(histogram_path.resolve()),
    }
    (output_dir / "summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(summary, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
