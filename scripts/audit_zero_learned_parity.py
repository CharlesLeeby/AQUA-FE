#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
from pathlib import Path

import numpy as np
import rosbag


LEARNED_SOURCE_CODES = {10, 20, 30}
LOFTR_SOURCE_CODE = 30
HIGH_ID_LEARNED_THRESHOLD = 10_000_000


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Audit whether a candidate VINS feature bag preserves a KLT/no-learned bag."
    )
    parser.add_argument("--base", required=True, help="Baseline feature bag.")
    parser.add_argument("--candidate", required=True, help="Candidate feature bag.")
    parser.add_argument("--topic", default="/feature_tracker/feature")
    parser.add_argument("--output-csv", default=None)
    parser.add_argument("--output-md", default=None)
    parser.add_argument(
        "--allow-learned",
        action="store_true",
        help="Do not fail the audit when candidate contains learned observations.",
    )
    args = parser.parse_args()

    base = load_frames(Path(args.base), args.topic)
    candidate = load_frames(Path(args.candidate), args.topic)
    summary, rows = audit(base, candidate, require_zero_learned=not args.allow_learned)

    print(render_summary(summary))
    if args.output_csv:
        output = Path(args.output_csv)
        output.parent.mkdir(parents=True, exist_ok=True)
        with output.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0]) if rows else ["index"])
            writer.writeheader()
            writer.writerows(rows)
        print(f"wrote {output}")
    if args.output_md:
        output = Path(args.output_md)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(render_markdown(summary, rows), encoding="utf-8")
        print(f"wrote {output}")
    return 0 if summary["audit_pass"] else 1


def load_frames(path: Path, topic: str) -> list[dict[str, object]]:
    frames: list[dict[str, object]] = []
    with rosbag.Bag(str(path), "r") as bag:
        for _topic, msg, _stamp in bag.read_messages(topics=[topic]):
            channels = {channel.name: np.asarray(channel.values) for channel in msg.channels}
            points = np.asarray([[p.x, p.y, p.z] for p in msg.points], dtype=np.float64)
            frames.append(
                {
                    "stamp": float(msg.header.stamp.to_sec()),
                    "points": points,
                    "channels": channels,
                }
            )
    return frames


def audit(
    base: list[dict[str, object]],
    candidate: list[dict[str, object]],
    *,
    require_zero_learned: bool,
) -> tuple[dict[str, object], list[dict[str, object]]]:
    rows: list[dict[str, object]] = []
    paired = min(len(base), len(candidate))
    exact_frames = 0
    exact_id_frames = 0
    exact_count_frames = 0
    changed_frames = 0
    learned_obs = 0
    loftr_obs = 0
    high_id_obs = 0
    learned_frames = 0
    high_id_frames = 0
    max_abs_count_diff = 0
    max_stamp_diff_s = 0.0

    for idx in range(paired):
        b = base[idx]
        c = candidate[idx]
        b_channels = b["channels"]
        c_channels = c["channels"]
        b_count = len(b["points"])
        c_count = len(c["points"])
        count_diff = c_count - b_count
        max_abs_count_diff = max(max_abs_count_diff, abs(count_diff))
        stamp_diff = abs(float(c["stamp"]) - float(b["stamp"]))
        max_stamp_diff_s = max(max_stamp_diff_s, stamp_diff)

        candidate_high_id = count_high_id(c_channels, c_count)
        candidate_learned = count_learned(c_channels, c_count)
        candidate_loftr = count_loftr(c_channels, c_count)
        learned_obs += candidate_learned
        loftr_obs += candidate_loftr
        high_id_obs += candidate_high_id
        if candidate_learned:
            learned_frames += 1
        if candidate_high_id:
            high_id_frames += 1

        ids_exact = array_equal(channel(b_channels, "id", b_count), channel(c_channels, "id", c_count))
        frame_exact = feature_frame_equal(b, c)
        if count_diff == 0:
            exact_count_frames += 1
        if ids_exact:
            exact_id_frames += 1
        if frame_exact:
            exact_frames += 1
        else:
            changed_frames += 1
        rows.append(
            {
                "index": idx,
                "base_stamp": f"{float(b['stamp']):.9f}",
                "candidate_stamp": f"{float(c['stamp']):.9f}",
                "stamp_diff_s": f"{stamp_diff:.9f}",
                "base_count": b_count,
                "candidate_count": c_count,
                "count_diff": count_diff,
                "ids_exact": int(ids_exact),
                "feature_frame_exact": int(frame_exact),
                "candidate_learned_obs": candidate_learned,
                "candidate_loftr_obs": candidate_loftr,
                "candidate_high_id_obs": candidate_high_id,
            }
        )

    audit_pass = (
        len(base) == len(candidate)
        and exact_frames == paired
        and (learned_obs == 0 or not require_zero_learned)
    )
    summary = {
        "audit_pass": audit_pass,
        "require_zero_learned": require_zero_learned,
        "base_frames": len(base),
        "candidate_frames": len(candidate),
        "paired_frames": paired,
        "frame_count_diff": len(candidate) - len(base),
        "exact_feature_frames": exact_frames,
        "changed_feature_frames": changed_frames,
        "exact_count_frames": exact_count_frames,
        "exact_id_frames": exact_id_frames,
        "max_abs_count_diff": max_abs_count_diff,
        "max_stamp_diff_s": max_stamp_diff_s,
        "candidate_learned_observations": learned_obs,
        "candidate_loftr_observations": loftr_obs,
        "candidate_high_id_observations": high_id_obs,
        "candidate_learned_frames": learned_frames,
        "candidate_high_id_frames": high_id_frames,
    }
    return summary, rows


def count_learned(channels: dict[str, np.ndarray], count: int) -> int:
    learned = channel(channels, "is_learned", count)
    source = channel(channels, "source_code", count)
    ids = channel(channels, "id", count)
    flags = np.zeros(count, dtype=bool)
    if learned.size == count:
        flags |= learned.astype(np.float64) > 0.5
    if source.size == count:
        flags |= np.isin(source.astype(np.int64), list(LEARNED_SOURCE_CODES))
    if ids.size == count:
        flags |= ids.astype(np.int64) >= HIGH_ID_LEARNED_THRESHOLD
    return int(flags.sum())


def count_high_id(channels: dict[str, np.ndarray], count: int) -> int:
    ids = channel(channels, "id", count)
    if ids.size != count:
        return 0
    return int((ids.astype(np.int64) >= HIGH_ID_LEARNED_THRESHOLD).sum())


def count_loftr(channels: dict[str, np.ndarray], count: int) -> int:
    source = channel(channels, "source_code", count)
    if source.size != count:
        return 0
    return int((source.astype(np.int64) == LOFTR_SOURCE_CODE).sum())


def feature_frame_equal(a: dict[str, object], b: dict[str, object]) -> bool:
    if abs(float(a["stamp"]) - float(b["stamp"])) > 1e-9:
        return False
    a_points = np.asarray(a["points"])
    b_points = np.asarray(b["points"])
    if not np.array_equal(a_points, b_points):
        return False
    a_channels = a["channels"]
    b_channels = b["channels"]
    if set(a_channels) != set(b_channels):
        return False
    for name in a_channels:
        if not array_equal(np.asarray(a_channels[name]), np.asarray(b_channels[name])):
            return False
    return True


def channel(channels: dict[str, np.ndarray], name: str, count: int) -> np.ndarray:
    values = channels.get(name)
    if values is None:
        return np.asarray([], dtype=np.float64)
    if len(values) != count:
        return np.asarray([], dtype=np.float64)
    return np.asarray(values)


def array_equal(a: np.ndarray, b: np.ndarray) -> bool:
    if a.shape != b.shape:
        return False
    return bool(np.array_equal(a, b))


def render_summary(summary: dict[str, object]) -> str:
    return "\n".join(f"{key}={value}" for key, value in summary.items())


def render_markdown(summary: dict[str, object], rows: list[dict[str, object]]) -> str:
    out = ["# Zero-Learned Parity Audit", "", "## Summary", ""]
    for key, value in summary.items():
        out.append(f"- `{key}`: {value}")
    changed = [row for row in rows if not row["feature_frame_exact"] or row["candidate_learned_obs"]]
    out.extend(["", "## Changed Or Learned Frames", ""])
    if changed:
        head = changed[:40]
        headers = list(head[0])
        out.append("| " + " | ".join(headers) + " |")
        out.append("| " + " | ".join("---" for _ in headers) + " |")
        for row in head:
            out.append("| " + " | ".join(str(row[key]) for key in headers) + " |")
    else:
        out.append("No changed or learned frames.")
    return "\n".join(out) + "\n"


if __name__ == "__main__":
    raise SystemExit(main())
