#!/usr/bin/env python3
"""Audit preregistered persistence-conditioned feature bags against frozen KLT."""

from __future__ import annotations

import csv
import hashlib
import io
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import rosbag


ROOT = Path("/home/ma/AQUA-FE_WS")
EXPERIMENT = ROOT / "artifacts/frontend_persistence_conditioned_replacement_v1"
OUTPUT = ROOT / "papers/frontend_persistence_conditioned_replacement_v1"


@dataclass(frozen=True)
class Case:
    window: str
    expected_frames: int
    run_dir: Path
    klt_dir: Path


CASES = (
    Case(
        "a09_6000_6800",
        400,
        EXPERIMENT
        / "shadow_root/logs/aqualoc_archaeo_vins/external_hybrid_xfeat_every2_pcrv1_a09_6000_6800",
        Path("/mnt/data/AQUA-FE_WS/logs/aqualoc_archaeo_vins/external_klt_every2_fsbcv1_a09_6000_6800_klt_r1"),
    ),
    Case(
        "a06_s045_d045",
        450,
        EXPERIMENT
        / "shadow_root/logs/aqualoc_archaeo_vins/external_hybrid_xfeat_every2_pcrv1_a06_s045_d045",
        ROOT
        / "artifacts/frontend_same_backend_comparison_supplement/shadow_root/logs/aqualoc_archaeo_vins/external_klt_every2_fsbcsupp_a06_s045_d045_klt_frontend",
    ),
    Case(
        "a06_s000_d045",
        450,
        EXPERIMENT
        / "shadow_root/logs/aqualoc_archaeo_vins/external_hybrid_xfeat_every2_pcrv1_a06_s000_d045",
        ROOT
        / "artifacts/frontend_same_backend_comparison_supplement/shadow_root/logs/aqualoc_archaeo_vins/external_klt_every2_fsbcsupp_a06_s000_d045_klt_frontend",
    ),
    Case(
        "h07_s000_d050",
        500,
        EXPERIMENT
        / "shadow_root/logs/aqualoc_real_vins/external_hybrid_xfeat_every2_pcrv1_h07_s000_d050",
        ROOT
        / "artifacts/frontend_same_backend_comparison_supplement/shadow_root/logs/aqualoc_real_vins/external_klt_every2_fsbcsupp_h07_s000_d050_klt_frontend",
    ),
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def message_bytes(message: Any) -> bytes:
    stream = io.BytesIO()
    message.serialize(stream)
    return stream.getvalue()


def load_features(path: Path) -> list[dict[str, Any]]:
    rows = []
    with rosbag.Bag(str(path), "r") as bag:
        for _, message, record_time in bag.read_messages(topics=["/feature_tracker/feature"]):
            channels = {channel.name: np.asarray(channel.values) for channel in message.channels}
            rows.append(
                {
                    "stamp_ns": int(message.header.stamp.to_nsec()),
                    "record_ns": int(record_time.to_nsec()),
                    "ids": np.rint(channels["id"]).astype(np.int64),
                    "source": np.rint(channels["source_code"]).astype(np.int64),
                    "learned": channels["is_learned"] > 0.5,
                    "quality": channels["quality"].astype(np.float64),
                    "message_bytes": message_bytes(message),
                }
            )
    return rows


def appearances(frames: list[dict[str, Any]]) -> dict[int, list[int]]:
    output: dict[int, list[int]] = defaultdict(list)
    for frame_index, frame in enumerate(frames):
        for track_id in frame["ids"]:
            output[int(track_id)].append(frame_index)
    return output


def streak(sequence: list[int], frame_index: int) -> tuple[int, int]:
    position = sequence.index(frame_index)
    left = position
    while left > 0 and sequence[left - 1] == sequence[left] - 1:
        left -= 1
    right = position
    while right + 1 < len(sequence) and sequence[right + 1] == sequence[right] + 1:
        right += 1
    return position - left + 1, right - left + 1


def integer(row: dict[str, str], name: str) -> int:
    try:
        return int(float(row.get(name, "0") or 0))
    except ValueError:
        return 0


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = list(rows[0]) if rows else []
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    validation_rows = []
    event_rows = []
    victim_rows = []
    manifest_rows = []
    for case in CASES:
        feature_bag = case.run_dir / "features.bag"
        metric_path = case.run_dir / "frontend_metrics.csv"
        klt_bag = case.klt_dir / "features.bag"
        for path in (feature_bag, metric_path, klt_bag):
            if not path.is_file():
                raise FileNotFoundError(path)
            manifest_rows.append(
                {"window": case.window, "sha256": sha256(path), "bytes": path.stat().st_size, "path": str(path)}
            )
        new = load_features(feature_bag)
        klt = load_features(klt_bag)
        with metric_path.open(newline="", encoding="utf-8") as handle:
            metrics = list(csv.DictReader(handle))
        by_selected = {integer(row, "selected_feature_index"): row for row in metrics}
        if [row["stamp_ns"] for row in new] != [row["stamp_ns"] for row in klt]:
            timestamp_equal = False
        else:
            timestamp_equal = True
        klt_tracks = appearances(klt)
        differing = []
        learned_after_horizon = 0
        missing_source_codes: list[int] = []
        reconstructed_missing = 0
        for frame_index, (baseline, candidate) in enumerate(zip(klt, new)):
            if baseline["message_bytes"] != candidate["message_bytes"]:
                differing.append(frame_index)
            learned_indices = np.flatnonzero(candidate["learned"])
            if frame_index > 4:
                learned_after_horizon += len(learned_indices)
            baseline_ids = {int(value): index for index, value in enumerate(baseline["ids"])}
            candidate_classical_ids = {
                int(value) for value in candidate["ids"][~candidate["learned"]]
            }
            missing = [
                (track_id, index)
                for track_id, index in baseline_ids.items()
                if track_id not in candidate_classical_ids
            ]
            if not missing and len(learned_indices) == 0:
                continue
            metric = by_selected.get(frame_index, {})
            reconstructed_missing += len(missing)
            sources = [int(baseline["source"][index]) for _, index in missing]
            missing_source_codes.extend(sources)
            event_rows.append(
                {
                    "window": case.window,
                    "selected_feature_index": frame_index,
                    "raw_frame_index": metric.get("frame_index", ""),
                    "timestamp_ns": baseline["stamp_ns"],
                    "published_xfeat": len(learned_indices),
                    "reconstructed_missing_klt": len(missing),
                    "metric_replaced_gftt": integer(metric, "final_mirror_persistence_replaced_gftt"),
                    "metric_eligible_gftt": integer(metric, "final_mirror_persistence_eligible_gftt"),
                    "metric_eligible_sidecars": integer(metric, "final_mirror_persistence_eligible_sidecars"),
                    "metric_horizon_blocked": integer(metric, "final_mirror_persistence_horizon_blocked"),
                    "exported_xfeat_median_age": metric.get("exported_xfeat_median_age", ""),
                    "export_source_histogram": metric.get("export_source_histogram", ""),
                }
            )
            for track_id, index in missing:
                age, full_lifetime = streak(klt_tracks[track_id], frame_index)
                victim_rows.append(
                    {
                        "window": case.window,
                        "selected_feature_index": frame_index,
                        "track_id": track_id,
                        "source_code": int(baseline["source"][index]),
                        "age_at_replacement": age,
                        "full_klt_counterfactual_lifetime": full_lifetime,
                        "backend_quality": float(baseline["quality"][index]),
                    }
                )
        metric_replaced = sum(
            integer(row, "final_mirror_persistence_replaced_gftt") for row in metrics
        )
        metric_kept = sum(integer(row, "final_mirror_kept_sidecars") for row in metrics)
        profile_active_frames = sum(
            integer(row, "final_mirror_persistence_replacement_active") for row in metrics
        )
        max_features = max(len(frame["ids"]) for frame in new) if new else 0
        source_rule_ok = all(code == 2 for code in missing_source_codes)
        count_rule_ok = metric_replaced == reconstructed_missing
        valid = bool(
            len(new) == case.expected_frames
            and len(new) == len(klt)
            and timestamp_equal
            and max_features <= 350
            and source_rule_ok
            and count_rule_ok
            and learned_after_horizon == 0
            and profile_active_frames == len(new)
        )
        identical = sha256(feature_bag) == sha256(klt_bag)
        if case.window == "h07_s000_d050":
            valid &= identical
        validation_rows.append(
            {
                "window": case.window,
                "status": "PASS" if valid else "FAIL",
                "feature_frames": len(new),
                "expected_feature_frames": case.expected_frames,
                "timestamps_equal_klt": timestamp_equal,
                "max_features": max_features,
                "profile_active_frames": profile_active_frames,
                "published_xfeat_observations": metric_kept,
                "reconstructed_missing_klt_observations": reconstructed_missing,
                "metric_replaced_gftt": metric_replaced,
                "all_victims_source_gftt": source_rule_ok,
                "learned_after_selected_frame_4": learned_after_horizon,
                "differing_feature_messages": len(differing),
                "differing_feature_message_indices": ";".join(map(str, differing)),
                "whole_bag_byte_identical_to_klt": identical,
                "feature_bag_sha256": sha256(feature_bag),
                "klt_bag_sha256": sha256(klt_bag),
            }
        )
    write_csv(OUTPUT / "frontend_validation.csv", validation_rows)
    write_csv(OUTPUT / "replacement_events.csv", event_rows)
    write_csv(OUTPUT / "replacement_victims.csv", victim_rows)
    write_csv(OUTPUT / "frontend_source_artifacts.sha256.csv", manifest_rows)
    return 0 if all(row["status"] == "PASS" for row in validation_rows) else 1


if __name__ == "__main__":
    raise SystemExit(main())
