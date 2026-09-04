#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import math
from collections import Counter
from pathlib import Path

import numpy as np
import rosbag


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Compare two VINS-Fusion external feature bags at the PointCloud level."
    )
    parser.add_argument("--base", required=True, help="Baseline feature bag.")
    parser.add_argument("--candidate", required=True, help="Candidate feature bag.")
    parser.add_argument("--topic", default="/feature_tracker/feature")
    parser.add_argument("--output-csv", default=None)
    parser.add_argument("--output-md", default=None)
    args = parser.parse_args()

    base_frames = load_feature_frames(Path(args.base), args.topic)
    cand_frames = load_feature_frames(Path(args.candidate), args.topic)
    summary, rows = compare_frames(base_frames, cand_frames)

    print(render_summary(summary))
    if args.output_csv:
        output = Path(args.output_csv)
        output.parent.mkdir(parents=True, exist_ok=True)
        with output.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()) if rows else ["index"])
            writer.writeheader()
            writer.writerows(rows)
        print(f"wrote {output}")
    if args.output_md:
        output = Path(args.output_md)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(render_markdown(summary, rows), encoding="utf-8")
        print(f"wrote {output}")
    return 0


def load_feature_frames(path: Path, topic: str) -> list[dict[str, object]]:
    frames: list[dict[str, object]] = []
    with rosbag.Bag(str(path), "r") as bag:
        for _topic, msg, _stamp in bag.read_messages(topics=[topic]):
            channels = {channel.name: list(channel.values) for channel in msg.channels}
            ids = np.asarray(channels.get("id", []), dtype=np.int64)
            quality = np.asarray(channels.get("quality", []), dtype=np.float32)
            sigma = np.asarray(channels.get("sigma", []), dtype=np.float32)
            frames.append(
                {
                    "stamp": float(msg.header.stamp.to_sec()),
                    "count": int(len(msg.points)),
                    "ids": ids,
                    "quality": quality,
                    "sigma": sigma,
                    "channels": sorted(channels),
                }
            )
    return frames


def compare_frames(
    base: list[dict[str, object]],
    cand: list[dict[str, object]],
) -> tuple[dict[str, object], list[dict[str, object]]]:
    rows: list[dict[str, object]] = []
    n = min(len(base), len(cand))
    stamp_diffs: list[float] = []
    count_diffs: list[int] = []
    overlap_ratios: list[float] = []
    quality_diffs: list[float] = []
    sigma_diffs: list[float] = []
    exact_id_frames = 0
    exact_count_frames = 0
    for idx in range(n):
        b = base[idx]
        c = cand[idx]
        b_ids = np.asarray(b["ids"], dtype=np.int64)
        c_ids = np.asarray(c["ids"], dtype=np.int64)
        b_set = set(int(x) for x in b_ids)
        c_set = set(int(x) for x in c_ids)
        common = len(b_set & c_set)
        union = max(1, len(b_set | c_set))
        overlap = common / float(union)
        stamp_diff = abs(float(c["stamp"]) - float(b["stamp"]))
        count_diff = int(c["count"]) - int(b["count"])
        q_diff = median(c["quality"]) - median(b["quality"])
        s_diff = median(c["sigma"]) - median(b["sigma"])
        stamp_diffs.append(stamp_diff)
        count_diffs.append(count_diff)
        overlap_ratios.append(overlap)
        quality_diffs.append(q_diff)
        sigma_diffs.append(s_diff)
        if count_diff == 0:
            exact_count_frames += 1
        if np.array_equal(b_ids, c_ids):
            exact_id_frames += 1
        rows.append(
            {
                "index": idx,
                "base_stamp": f"{float(b['stamp']):.9f}",
                "candidate_stamp": f"{float(c['stamp']):.9f}",
                "stamp_diff_s": f"{stamp_diff:.9f}",
                "base_count": int(b["count"]),
                "candidate_count": int(c["count"]),
                "count_diff": count_diff,
                "id_jaccard": f"{overlap:.6f}",
                "median_quality_diff": format_float(q_diff),
                "median_sigma_diff": format_float(s_diff),
            }
        )
    summary = {
        "base_frames": len(base),
        "candidate_frames": len(cand),
        "paired_frames": n,
        "frame_count_diff": len(cand) - len(base),
        "exact_count_frames": exact_count_frames,
        "exact_id_frames": exact_id_frames,
        "max_stamp_diff_s": max(stamp_diffs) if stamp_diffs else float("nan"),
        "median_count_diff": median(count_diffs),
        "max_abs_count_diff": max((abs(x) for x in count_diffs), default=float("nan")),
        "median_id_jaccard": median(overlap_ratios),
        "min_id_jaccard": min(overlap_ratios) if overlap_ratios else float("nan"),
        "median_quality_diff": median(quality_diffs),
        "median_sigma_diff": median(sigma_diffs),
        "base_channel_sets": compact_channel_sets(base),
        "candidate_channel_sets": compact_channel_sets(cand),
    }
    return summary, rows


def compact_channel_sets(frames: list[dict[str, object]]) -> str:
    counter = Counter(",".join(frame["channels"]) for frame in frames)
    return ";".join(f"{key}:{value}" for key, value in counter.most_common(4))


def median(values: object) -> float:
    arr = np.asarray(values, dtype=np.float64)
    arr = arr[np.isfinite(arr)]
    if arr.size == 0:
        return float("nan")
    return float(np.median(arr))


def format_float(value: float) -> str:
    if not math.isfinite(float(value)):
        return ""
    return f"{float(value):.6f}"


def render_summary(summary: dict[str, object]) -> str:
    lines = ["feature bag comparison"]
    for key, value in summary.items():
        if isinstance(value, float):
            value = format_float(value)
        lines.append(f"{key}={value}")
    return "\n".join(lines)


def render_markdown(summary: dict[str, object], rows: list[dict[str, object]]) -> str:
    out = ["# Feature Bag Comparison", "", "## Summary", ""]
    for key, value in summary.items():
        if isinstance(value, float):
            value = format_float(value)
        out.append(f"- `{key}`: {value}")
    out.extend(["", "## First Frames", ""])
    if rows:
        head = rows[:12]
        headers = list(head[0])
        out.append("| " + " | ".join(headers) + " |")
        out.append("| " + " | ".join("---" for _ in headers) + " |")
        for row in head:
            out.append("| " + " | ".join(str(row[key]) for key in headers) + " |")
    return "\n".join(out) + "\n"


if __name__ == "__main__":
    raise SystemExit(main())
