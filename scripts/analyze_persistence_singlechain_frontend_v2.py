#!/usr/bin/env python3
"""Audit persistence single-chain v2 bags against frozen KLT and v1."""

from __future__ import annotations

import argparse
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
RUNTIME = ROOT / "artifacts/frontend_persistence_singlechain_v2"
V1 = ROOT / "artifacts/frontend_persistence_conditioned_replacement_v1"
PAPER = ROOT / "papers/frontend_persistence_singlechain_v2"


@dataclass(frozen=True)
class Case:
    window: str
    frames: int
    family: str
    klt_bag: Path
    v1_bag: Path

    @property
    def run_dir(self) -> Path:
        return RUNTIME / "shadow_root/logs" / self.family / (
            f"external_hybrid_xfeat_every2_pscv2_{self.window}"
        )


CASES = (
    Case(
        "a06_s000_d045", 450, "aqualoc_archaeo_vins",
        ROOT / "artifacts/frontend_same_backend_comparison_supplement/shadow_root/logs/aqualoc_archaeo_vins/external_klt_every2_fsbcsupp_a06_s000_d045_klt_frontend/features.bag",
        V1 / "shadow_root/logs/aqualoc_archaeo_vins/external_hybrid_xfeat_every2_pcrv1_a06_s000_d045/features.bag",
    ),
    Case(
        "a09_6000_6800", 400, "aqualoc_archaeo_vins",
        Path("/mnt/data/AQUA-FE_WS/logs/aqualoc_archaeo_vins/external_klt_every2_fsbcv1_a09_6000_6800_klt_r1/features.bag"),
        V1 / "shadow_root/logs/aqualoc_archaeo_vins/external_hybrid_xfeat_every2_pcrv1_a09_6000_6800/features.bag",
    ),
    Case(
        "a06_s045_d045", 450, "aqualoc_archaeo_vins",
        ROOT / "artifacts/frontend_same_backend_comparison_supplement/shadow_root/logs/aqualoc_archaeo_vins/external_klt_every2_fsbcsupp_a06_s045_d045_klt_frontend/features.bag",
        V1 / "shadow_root/logs/aqualoc_archaeo_vins/external_hybrid_xfeat_every2_pcrv1_a06_s045_d045/features.bag",
    ),
    Case(
        "h07_s000_d050", 500, "aqualoc_real_vins",
        ROOT / "artifacts/frontend_same_backend_comparison_supplement/shadow_root/logs/aqualoc_real_vins/external_klt_every2_fsbcsupp_h07_s000_d050_klt_frontend/features.bag",
        V1 / "shadow_root/logs/aqualoc_real_vins/external_hybrid_xfeat_every2_pcrv1_h07_s000_d050/features.bag",
    ),
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def message_bytes(message: Any) -> bytes:
    stream = io.BytesIO()
    message.serialize(stream)
    return stream.getvalue()


def load(path: Path) -> list[dict[str, Any]]:
    rows = []
    with rosbag.Bag(str(path)) as bag:
        for _, message, _ in bag.read_messages(topics=["/feature_tracker/feature"]):
            channels = {channel.name: np.asarray(channel.values) for channel in message.channels}
            rows.append(
                {
                    "stamp": int(message.header.stamp.to_nsec()),
                    "ids": np.rint(channels["id"]).astype(np.int64),
                    "sources": np.rint(channels["source_code"]).astype(np.int64),
                    "learned": channels["is_learned"] > 0.5,
                    "u": channels["p_u"].astype(float), "v": channels["p_v"].astype(float),
                    "bytes": message_bytes(message),
                }
            )
    return rows


def integer(row: dict[str, str], key: str) -> int:
    try:
        return int(float(row.get(key, "0") or 0))
    except ValueError:
        return 0


def write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    fields: list[str] = []
    for row in rows:
        for key in row:
            if key not in fields:
                fields.append(key)
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--window", default="")
    args = parser.parse_args()
    validation = []
    events = []
    victims = []
    selected_cases = [case for case in CASES if not args.window or case.window == args.window]
    if not selected_cases:
        raise SystemExit(f"unknown window: {args.window}")
    for case in selected_cases:
        bag = case.run_dir / "features.bag"
        metrics_path = case.run_dir / "frontend_metrics.csv"
        for path in (bag, metrics_path, case.klt_bag, case.v1_bag):
            if not path.is_file():
                raise FileNotFoundError(path)
        new = load(bag)
        klt = load(case.klt_bag)
        with metrics_path.open(newline="", encoding="utf-8") as stream:
            metrics = list(csv.DictReader(stream))
        by_selected = {integer(row, "selected_feature_index"): row for row in metrics}
        learned_ids: set[int] = set()
        max_learned_per_frame = 0
        learned_after_horizon = 0
        missing_sources: list[int] = []
        different = []
        pixel_rows = []
        for frame, (baseline, candidate) in enumerate(zip(klt, new)):
            if baseline["bytes"] != candidate["bytes"]:
                different.append(frame)
            learned_idx = np.flatnonzero(candidate["learned"])
            max_learned_per_frame = max(max_learned_per_frame, len(learned_idx))
            learned_ids.update(int(candidate["ids"][idx]) for idx in learned_idx)
            if frame > 4:
                learned_after_horizon += len(learned_idx)
            baseline_by_id = {int(value): idx for idx, value in enumerate(baseline["ids"])}
            classical_ids = {int(value) for value in candidate["ids"][~candidate["learned"]]}
            missing = [(track_id, idx) for track_id, idx in baseline_by_id.items() if track_id not in classical_ids]
            missing_sources.extend(int(baseline["sources"][idx]) for _, idx in missing)
            row = by_selected.get(frame, {})
            if learned_idx.size or missing:
                events.append(
                    {
                        "window": case.window, "selected_feature_index": frame,
                        "raw_frame_index": row.get("frame_index", ""),
                        "published_xfeat": len(learned_idx), "missing_klt": len(missing),
                        "eligible_xfeat": integer(row, "final_mirror_persistence_eligible_sidecars"),
                        "eligible_gftt": integer(row, "final_mirror_persistence_eligible_gftt"),
                        "replaced_gftt": integer(row, "final_mirror_persistence_replaced_gftt"),
                        "single_chain_suppressed": integer(row, "final_mirror_persistence_single_chain_suppressed"),
                        "committed_sidecar_id": integer(row, "final_mirror_persistence_committed_sidecar_id"),
                        "export_source_histogram": row.get("export_source_histogram", ""),
                    }
                )
            for track_id, idx in missing:
                victims.append(
                    {
                        "window": case.window, "selected_feature_index": frame,
                        "track_id": track_id, "source_code": int(baseline["sources"][idx]),
                        "p_u": float(baseline["u"][idx]), "p_v": float(baseline["v"][idx]),
                    }
                )
            for idx in learned_idx:
                pixel_rows.append((frame, float(candidate["u"][idx]), float(candidate["v"][idx])))
        active_frames = sum(integer(row, "final_mirror_persistence_single_chain_active") for row in metrics)
        metric_replaced = sum(integer(row, "final_mirror_persistence_replaced_gftt") for row in metrics)
        valid = bool(
            len(new) == case.frames and len(klt) == case.frames
            and [row["stamp"] for row in new] == [row["stamp"] for row in klt]
            and max((len(row["ids"]) for row in new), default=0) <= 350
            and len(learned_ids) <= 1 and max_learned_per_frame <= 1
            and learned_after_horizon == 0 and all(source == 2 for source in missing_sources)
            and metric_replaced == len(missing_sources) and active_frames == case.frames
        )
        identical_klt = sha256(bag) == sha256(case.klt_bag)
        identical_v1 = sha256(bag) == sha256(case.v1_bag)
        if case.window == "a09_6000_6800":
            valid &= identical_v1 and len(pixel_rows) == 3
        if case.window == "h07_s000_d050":
            valid &= identical_klt
        validation.append(
            {
                "window": case.window, "status": "PASS" if valid else "FAIL",
                "feature_frames": len(new), "expected_frames": case.frames,
                "timestamps_equal_klt": [row["stamp"] for row in new] == [row["stamp"] for row in klt],
                "max_features": max((len(row["ids"]) for row in new), default=0),
                "single_chain_active_frames": active_frames,
                "published_xfeat_observations": sum(np.count_nonzero(row["learned"]) for row in new),
                "unique_xfeat_ids": len(learned_ids), "max_xfeat_per_frame": max_learned_per_frame,
                "replaced_gftt": metric_replaced, "all_victims_gftt": all(source == 2 for source in missing_sources),
                "learned_after_frame_4": learned_after_horizon,
                "differing_messages_vs_klt": len(different),
                "differing_indices": ";".join(map(str, different)),
                "byte_identical_klt": identical_klt, "byte_identical_v1": identical_v1,
                "feature_bag_sha256": sha256(bag), "klt_bag_sha256": sha256(case.klt_bag),
            }
        )
    write_csv(PAPER / "frontend_validation.csv", validation)
    write_csv(PAPER / "singlechain_events.csv", events)
    write_csv(PAPER / "replacement_victims.csv", victims)
    return 0 if all(row["status"] == "PASS" for row in validation) else 1


if __name__ == "__main__":
    raise SystemExit(main())
