#!/usr/bin/env python3
"""Read-only attribution audit for historical XFeat/KLT replacement runs.

The script never writes into any source run.  It reads frozen metrics and ROS
bags, reconstructs backend-visible track lifetimes, and writes a compact
analysis bundle below a caller-provided output directory.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import math
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import rosbag


ROOT = Path("/home/ma/AQUA-FE_WS")
MAIN = Path("/mnt/data/AQUA-FE_WS/logs/aqualoc_archaeo_vins")
SUPP = ROOT / "artifacts/frontend_same_backend_comparison_supplement/shadow_root/logs"


@dataclass(frozen=True)
class Case:
    window: str
    group: str
    outcome: str
    mechanism: str
    profile: str
    exporter_sha256: str
    klt_dir: Path
    xfeat_dir: Path
    ape_klt: float
    ape_xfeat: float
    rpe_klt: float
    rpe_xfeat: float
    matching: str


CASES = (
    Case(
        "a09_6000_6800",
        "positive",
        "XFEAT_CONVERGED_KLT_SCALE_DIVERGED",
        "shared_tracker_birth_replacement_and_downstream_state_perturbation",
        "lineage_early_seed_scan / P_legacy_nativeq_xfeat_seedchain_v3",
        "68453b035037d04087dbad3e512c602b4ef6967b2a8cf6d14e34a14750f2312d",
        MAIN / "external_klt_every2_fsbcv1_a09_6000_6800_klt_r1",
        MAIN / "external_hybrid_xfeat_every2_fsbcv1_a09_6000_6800_xfeat_seed_r1",
        1234.1315792872176,
        0.7148936232242529,
        150.0564940756865,
        0.07081541873007002,
        "exact_pixel_coordinate",
    ),
    Case(
        "a06_s045_d045",
        "positive",
        "XFEAT_LOWER_APE_AND_RPE",
        "legacy_final_mirror_one_for_one_replacement",
        "lineage_early_seed_scan / P_legacy_nativeq_xfeat_seedchain_v3",
        "fdb624f24d97fe032c1cdcf0600dd07b370e498f32806ac6eba25467d8020c04",
        SUPP / "aqualoc_archaeo_vins/external_klt_every2_fsbcsupp_a06_s045_d045_klt_frontend",
        SUPP / "aqualoc_archaeo_vins/external_hybrid_xfeat_every2_fsbcsupp_a06_s045_d045_xfeat_seed_frontend",
        0.25771463408599476,
        0.20648331871430678,
        0.031055992115549422,
        0.024420155234299735,
        "exact_track_id",
    ),
    Case(
        "a06_s000_d045",
        "harm_or_mixed",
        "APE_HARM_RPE_SLIGHT_HELP",
        "legacy_final_mirror_one_for_one_replacement",
        "lineage_early_seed_scan / P_legacy_nativeq_xfeat_seedchain_v3",
        "fdb624f24d97fe032c1cdcf0600dd07b370e498f32806ac6eba25467d8020c04",
        SUPP / "aqualoc_archaeo_vins/external_klt_every2_fsbcsupp_a06_s000_d045_klt_frontend",
        SUPP / "aqualoc_archaeo_vins/external_hybrid_xfeat_every2_fsbcsupp_a06_s000_d045_xfeat_seed_frontend",
        2.6427389543053867,
        2.848403916327577,
        0.33859072809666557,
        0.32222805375282554,
        "exact_track_id",
    ),
    Case(
        "h07_s000_d050",
        "harm_or_mixed",
        "XFEAT_HIGHER_APE_AND_RPE",
        "legacy_final_mirror_one_for_one_replacement",
        "lineage_early_seed_scan / P_legacy_nativeq_xfeat_seedchain_v3",
        "fdb624f24d97fe032c1cdcf0600dd07b370e498f32806ac6eba25467d8020c04",
        SUPP / "aqualoc_real_vins/external_klt_every2_fsbcsupp_h07_s000_d050_klt_frontend",
        SUPP / "aqualoc_real_vins/external_hybrid_xfeat_every2_fsbcsupp_h07_s000_d050_xfeat_seed_frontend",
        1.2296692243162102,
        1.3346982067197466,
        0.21984797092151956,
        0.25010674336110894,
        "exact_track_id",
    ),
)

INIT_FINISH_SIM_TIME = {
    "a09_6000_6800": 1542889047.427871611,
    "a06_s045_d045": 1542883359.157235736,
    "a06_s000_d045": 1542883316.437856660,
    "h07_s000_d050": 1523387547.441761370,
}


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def finite_float(value: Any) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return float("nan")
    return out


def as_int(value: Any, default: int = 0) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def write_csv(path: Path, rows: list[dict[str, Any]], fields: Iterable[str] | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if fields is None:
        fields = rows[0].keys() if rows else []
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(fields), extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def load_metrics(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as stream:
        return list(csv.DictReader(stream))


def load_feature_bag(path: Path) -> list[dict[str, Any]]:
    frames: list[dict[str, Any]] = []
    with rosbag.Bag(str(path), "r") as bag:
        for _, msg, record_time in bag.read_messages(topics=["/feature_tracker/feature"]):
            channels = {item.name: np.asarray(item.values) for item in msg.channels}
            frames.append(
                {
                    "header_seq": int(msg.header.seq),
                    "stamp_ns": int(msg.header.stamp.to_nsec()),
                    "frame_id": str(msg.header.frame_id),
                    "record_ns": int(record_time.to_nsec()),
                    "channels": channels,
                    "channel_order": tuple(item.name for item in msg.channels),
                    "points": np.asarray(
                        [(point.x, point.y, point.z) for point in msg.points],
                        dtype=np.float64,
                    ),
                    "ids": np.rint(channels["id"]).astype(np.int64),
                    "source": np.rint(channels["source_code"]).astype(np.int64),
                    "learned": channels["is_learned"] > 0.5,
                    "uv": np.column_stack([channels["p_u"], channels["p_v"]]),
                    "quality": channels["quality"].astype(np.float64),
                    "message": msg,
                }
            )
    return frames


def track_appearances(frames: list[dict[str, Any]], learned: bool) -> dict[int, list[int]]:
    out: dict[int, list[int]] = defaultdict(list)
    for frame_i, frame in enumerate(frames):
        for track_id, is_learned in zip(frame["ids"], frame["learned"]):
            if bool(is_learned) == learned:
                out[int(track_id)].append(frame_i)
    return out


def streak_at(sequence: list[int], frame_i: int) -> tuple[int, int, int, bool, bool]:
    pos = sequence.index(frame_i)
    left = pos
    while left > 0 and sequence[left - 1] == sequence[left] - 1:
        left -= 1
    right = pos
    while right + 1 < len(sequence) and sequence[right + 1] == sequence[right] + 1:
        right += 1
    return (
        pos - left + 1,
        right - pos + 1,
        right - left + 1,
        sequence[left] == 0,
        sequence[right] == sequence[-1],
    )


def exact_pixel_missing(klt: dict[str, Any], hybrid: dict[str, Any]) -> list[int]:
    """Return KLT indices absent from hybrid classical output by exact (u,v).

    The a09 frozen bags have 348/349/346 classical observations that are
    bit-exact coordinate matches to the KLT arm, so no analysis tolerance is
    needed and no matching threshold is introduced.
    """

    hybrid_counter = Counter(
        (float(u), float(v)) for u, v in hybrid["uv"][~hybrid["learned"]]
    )
    missing: list[int] = []
    for index, (u, v) in enumerate(klt["uv"]):
        key = (float(u), float(v))
        if hybrid_counter[key] > 0:
            hybrid_counter[key] -= 1
        else:
            missing.append(index)
    if any(hybrid_counter.values()):
        raise RuntimeError("a09 hybrid contains unmatched classical coordinates")
    return missing


def exact_id_missing(klt: dict[str, Any], hybrid: dict[str, Any]) -> list[int]:
    hybrid_ids = set(int(value) for value in hybrid["ids"][~hybrid["learned"]])
    return [i for i, value in enumerate(klt["ids"]) if int(value) not in hybrid_ids]


def message_bytes(msg: Any) -> bytes:
    stream = io.BytesIO()
    msg.serialize(stream)
    return stream.getvalue()


def bag_message_stream_digest(path: Path) -> tuple[str, int]:
    """Hash the backend-visible ROS message stream, independent of bag metadata."""

    h = hashlib.sha256()
    count = 0
    with rosbag.Bag(str(path), "r") as bag:
        for topic, msg, record_time in bag.read_messages():
            topic_bytes = topic.encode("utf-8")
            payload = message_bytes(msg)
            h.update(len(topic_bytes).to_bytes(4, "little"))
            h.update(topic_bytes)
            h.update(int(record_time.to_nsec()).to_bytes(8, "little", signed=True))
            h.update(len(payload).to_bytes(8, "little"))
            h.update(payload)
            count += 1
    return h.hexdigest(), count


def summary(values: list[float], prefix: str) -> dict[str, Any]:
    arr = np.asarray(values, dtype=np.float64)
    if len(arr) == 0:
        return {f"{prefix}_{name}": "" for name in ("n", "median", "q1", "q3", "min", "max", "mean")}
    return {
        f"{prefix}_n": int(len(arr)),
        f"{prefix}_median": float(np.median(arr)),
        f"{prefix}_q1": float(np.quantile(arr, 0.25)),
        f"{prefix}_q3": float(np.quantile(arr, 0.75)),
        f"{prefix}_min": float(np.min(arr)),
        f"{prefix}_max": float(np.max(arr)),
        f"{prefix}_mean": float(np.mean(arr)),
    }


def probability_superiority(xfeat: list[float], victim: list[float]) -> float:
    if not xfeat or not victim:
        return float("nan")
    comparisons = [float(x > v) + 0.5 * float(x == v) for x in xfeat for v in victim]
    return float(np.mean(comparisons))


def audit_july_ablation() -> dict[str, Any]:
    source = MAIN / "external_hybrid_xfeat_every2_jul07_morelong_a09_6000_6800_probe_oldcontract_densecap/features.bag"
    dropped = MAIN / "jul07_filtered_featurebags/a09_6000_6800_drop_source20.bag"
    full_replay = MAIN / "external_hybrid_xfeat_every2_jul07_morelong_a09_6000_6800_full_from_export"
    drop_replay = MAIN / "external_hybrid_xfeat_every2_jul07_morelong_a09_6000_6800_drop_source20"
    source_frames = load_feature_bag(source)
    drop_frames = load_feature_bag(dropped)
    removed: list[tuple[int, int]] = []
    frame_count_equal = len(source_frames) == len(drop_frames)
    header_equal = frame_count_equal
    record_time_equal = frame_count_equal
    channel_schema_equal = frame_count_equal
    point_fields_equal = frame_count_equal
    all_channel_values_equal = frame_count_equal
    for frame_i, (full, control) in enumerate(zip(source_frames, drop_frames)):
        full_keep = np.flatnonzero(full["source"] != 20)
        removed.extend((frame_i, int(full["ids"][i])) for i in np.flatnonzero(full["source"] == 20))
        header_equal &= (
            full["header_seq"] == control["header_seq"]
            and full["stamp_ns"] == control["stamp_ns"]
            and full["frame_id"] == control["frame_id"]
        )
        record_time_equal &= full["record_ns"] == control["record_ns"]
        channel_schema_equal &= full["channel_order"] == control["channel_order"]
        point_fields_equal &= np.array_equal(
            full["points"][full_keep], control["points"], equal_nan=True
        )
        if full["channel_order"] == control["channel_order"]:
            for name in full["channel_order"]:
                all_channel_values_equal &= np.array_equal(
                    full["channels"][name][full_keep],
                    control["channels"][name],
                    equal_nan=True,
                )
        else:
            all_channel_values_equal = False
    residual_equal = bool(
        frame_count_equal
        and header_equal
        and record_time_equal
        and channel_schema_equal
        and point_fields_equal
        and all_channel_values_equal
    )
    return {
        "window": "a09_6000_6800",
        "ablation_epoch": "2026-07-07 historical existing-bag replay",
        "removed_source_code": 20,
        "removed_observations": len(removed),
        "removed_frames_zero_based": ";".join(str(frame) for frame, _ in removed),
        "feature_frame_count_equal": frame_count_equal,
        "headers_equal": bool(header_equal),
        "record_times_equal": bool(record_time_equal),
        "channel_schema_and_order_equal": bool(channel_schema_equal),
        "remaining_point_fields_equal": bool(point_fields_equal),
        "all_remaining_channel_values_equal": bool(all_channel_values_equal),
        "all_remaining_feature_fields_equal": residual_equal,
        "full_feature_bag": str(source),
        "full_feature_bag_sha256": sha256(source),
        "drop_feature_bag": str(dropped),
        "drop_feature_bag_sha256": sha256(dropped),
        "full_replay_ape_report": str(full_replay / "ape.txt"),
        "drop_replay_ape_report": str(drop_replay / "ape.txt"),
        "full_ape_rmse_m": 0.578979,
        "full_rpe_rmse_m": 0.080426,
        "drop_ape_rmse_m": 1072.548468,
        "drop_rpe_rmse_m": 127.180419,
        "interpretation": "source20 observations necessary for convergence in this historical quality-weight epoch",
        "epoch_boundary": "do_not_pool_absolute_metrics_with_2026-08-30_formal_run",
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--safe-v4-dir", type=Path)
    args = parser.parse_args()
    output = args.output.resolve()
    figures = output / "analysis-output/figures"
    figures.mkdir(parents=True, exist_ok=True)

    window_rows: list[dict[str, Any]] = []
    frame_rows: list[dict[str, Any]] = []
    victim_rows: list[dict[str, Any]] = []
    xfeat_rows: list[dict[str, Any]] = []
    summary_rows: list[dict[str, Any]] = []
    timing_rows: list[dict[str, Any]] = []
    manifest_paths: set[Path] = set()
    plot_data: dict[str, dict[str, list[float]]] = {}

    for case in CASES:
        klt_bag = case.klt_dir / "features.bag"
        xfeat_bag = case.xfeat_dir / "features.bag"
        klt_metrics = case.klt_dir / "frontend_metrics.csv"
        xfeat_metrics = case.xfeat_dir / "frontend_metrics.csv"
        for path in (klt_bag, xfeat_bag, klt_metrics, xfeat_metrics):
            if not path.is_file():
                raise FileNotFoundError(path)
            manifest_paths.add(path)
        for run_dir in (case.klt_dir, case.xfeat_dir):
            for name in (
                "fsbc_command.txt",
                "fsbc_cell_complete.json",
                "replay_manifest.txt",
                "supplement_frontend_receipt.json",
            ):
                candidate = run_dir / name
                if candidate.is_file():
                    manifest_paths.add(candidate)
        klt_frames = load_feature_bag(klt_bag)
        xfeat_frames = load_feature_bag(xfeat_bag)
        if [x["stamp_ns"] for x in klt_frames] != [x["stamp_ns"] for x in xfeat_frames]:
            raise RuntimeError(f"timestamp mismatch: {case.window}")
        metrics = load_metrics(xfeat_metrics)
        by_selected = {as_int(row.get("selected_feature_index"), -1): row for row in metrics}
        klt_tracks = track_appearances(klt_frames, learned=False)
        xfeat_tracks = track_appearances(xfeat_frames, learned=True)
        victim_unique: dict[int, dict[str, Any]] = {}
        xfeat_unique: dict[int, dict[str, Any]] = {}
        different_messages = []

        for frame_i, (klt, xfeat) in enumerate(zip(klt_frames, xfeat_frames)):
            if message_bytes(klt["message"]) != message_bytes(xfeat["message"]):
                different_messages.append(frame_i)
            learned_indices = np.flatnonzero(xfeat["learned"])
            if len(learned_indices) == 0:
                continue
            missing = (
                exact_pixel_missing(klt, xfeat)
                if case.matching == "exact_pixel_coordinate"
                else exact_id_missing(klt, xfeat)
            )
            metric = by_selected.get(frame_i, {})
            victim_lifetimes: list[int] = []
            xfeat_lifetimes: list[int] = []
            for index in missing:
                track_id = int(klt["ids"][index])
                age, future, lifetime, left_censored, right_censored = streak_at(
                    klt_tracks[track_id], frame_i
                )
                row = {
                    "window": case.window,
                    "group": case.group,
                    "event_frame_zero_based": frame_i,
                    "metric_frame_index": metric.get("frame_index", ""),
                    "timestamp_ns": klt["stamp_ns"],
                    "track_id": track_id,
                    "source_code": int(klt["source"][index]),
                    "source_label": {1: "klt", 2: "gftt"}.get(int(klt["source"][index]), "other"),
                    "backend_visible_age_at_event": age,
                    "backend_visible_future_including_event": future,
                    "backend_visible_full_lifetime": lifetime,
                    "quality_at_event": float(klt["quality"][index]),
                    "u": float(klt["uv"][index, 0]),
                    "v": float(klt["uv"][index, 1]),
                    "left_censored": left_censored,
                    "right_censored": right_censored,
                    "matching": case.matching,
                }
                victim_rows.append(row)
                victim_lifetimes.append(lifetime)
                victim_unique.setdefault(track_id, row)
            for index in learned_indices:
                track_id = int(xfeat["ids"][index])
                age, future, lifetime, left_censored, right_censored = streak_at(
                    xfeat_tracks[track_id], frame_i
                )
                row = {
                    "window": case.window,
                    "group": case.group,
                    "event_frame_zero_based": frame_i,
                    "metric_frame_index": metric.get("frame_index", ""),
                    "timestamp_ns": xfeat["stamp_ns"],
                    "track_id": track_id,
                    "source_code": int(xfeat["source"][index]),
                    "backend_visible_age_at_event": age,
                    "backend_visible_future_including_event": future,
                    "backend_visible_full_lifetime": lifetime,
                    "quality_at_event": float(xfeat["quality"][index]),
                    "u": float(xfeat["uv"][index, 0]),
                    "v": float(xfeat["uv"][index, 1]),
                    "left_censored": left_censored,
                    "right_censored": right_censored,
                }
                xfeat_rows.append(row)
                xfeat_lifetimes.append(lifetime)
                xfeat_unique.setdefault(track_id, row)
            histogram = metric.get("export_source_histogram", "")
            gftt_hist = 0
            for token in histogram.split(";"):
                if token.startswith("gftt:"):
                    gftt_hist = as_int(token.split(":", 1)[1])
            frame_rows.append(
                {
                    "window": case.window,
                    "group": case.group,
                    "event_frame_zero_based": frame_i,
                    "metric_frame_index": metric.get("frame_index", ""),
                    "selected_feature_index": metric.get("selected_feature_index", ""),
                    "timestamp": metric.get("timestamp", ""),
                    "exported_features": metric.get("exported_features", ""),
                    "exported_xfeat_features": metric.get("exported_xfeat_features", ""),
                    "sidecars_kept": metric.get("final_mirror_kept_sidecars", metric.get("exported_xfeat_features", "")),
                    "classical_dropped_for_sidecars": metric.get("final_mirror_dropped_classical_for_cap", len(missing)),
                    "bag_reconstructed_missing_klt_observations": len(missing),
                    "exported_xfeat_median_age_raw_frames": metric.get("exported_xfeat_median_age", ""),
                    "exported_xfeat_median_visible_streak_recorded": metric.get("exported_xfeat_median_visible_streak", ""),
                    "xfeat_backend_visible_streak_median_derived": float(np.median([streak_at(xfeat_tracks[int(xfeat['ids'][i])], frame_i)[0] for i in learned_indices])),
                    "victim_backend_visible_age_median_derived": float(np.median([streak_at(klt_tracks[int(klt['ids'][i])], frame_i)[0] for i in missing])),
                    "victim_full_lifetime_median_hindsight": float(np.median(victim_lifetimes)),
                    "xfeat_full_lifetime_median_hindsight": float(np.median(xfeat_lifetimes)),
                    "exported_classical_gftt_features_recorded": metric.get("exported_classical_gftt_features", ""),
                    "export_histogram_gftt_count": gftt_hist,
                    "classical_track_count": metric.get("classical_track_count", ""),
                    "learned_export_gate_reason": metric.get("learned_export_gate_reason", ""),
                    "export_source_histogram": histogram,
                }
            )

        case_frame_rows = [row for row in frame_rows if row["window"] == case.window]
        event_times = [finite_float(row["timestamp"]) for row in case_frame_rows]
        init_finish = INIT_FINISH_SIM_TIME[case.window]
        timing_rows.append(
            {
                "window": case.window,
                "group": case.group,
                "replacement_event_count_frames": len(case_frame_rows),
                "replacement_raw_frame_indices": ";".join(
                    str(row["metric_frame_index"]) for row in case_frame_rows
                ),
                "replacement_selected_frame_indices": ";".join(
                    str(row["selected_feature_index"]) for row in case_frame_rows
                ),
                "replacement_first_sim_time": min(event_times),
                "replacement_last_sim_time": max(event_times),
                "backend_init_finish_sim_time_repeat1": init_finish,
                "last_replacement_minus_init_finish_s": max(event_times) - init_finish,
                "temporal_relation": (
                    "PRE_INIT_HISTORY"
                    if max(event_times) < init_finish
                    else "POST_INIT_PERTURBATION"
                ),
                "interpretation": (
                    "replacement altered the initialization history"
                    if max(event_times) < init_finish
                    else "replacement perturbed an already initialized trajectory"
                ),
            }
        )

        victim_life = [int(row["backend_visible_full_lifetime"]) for row in victim_unique.values()]
        xfeat_life = [int(row["backend_visible_full_lifetime"]) for row in xfeat_unique.values()]
        victim_age = [int(row["backend_visible_age_at_event"]) for row in victim_unique.values()]
        xfeat_age = [int(row["backend_visible_age_at_event"]) for row in xfeat_unique.values()]
        victim_quality = [float(row["quality_at_event"]) for row in victim_unique.values()]
        xfeat_quality = [float(row["quality_at_event"]) for row in xfeat_unique.values()]
        victim_source = Counter(str(row["source_label"]) for row in victim_unique.values())
        lifetime_direction = (
            "XFEAT_GREATER"
            if np.median(xfeat_life) > np.median(victim_life)
            else "KLT_GREATER"
            if np.median(xfeat_life) < np.median(victim_life)
            else "TIE"
        )
        summary_row = {
            "window": case.window,
            "group": case.group,
            "outcome": case.outcome,
            "mechanism": case.mechanism,
            "displaced_klt_observations": sum(1 for row in victim_rows if row["window"] == case.window),
            "displaced_klt_unique_tracks": len(victim_unique),
            "displaced_source_histogram_unique": ";".join(f"{k}:{v}" for k, v in sorted(victim_source.items())),
            "xfeat_observations": sum(1 for row in xfeat_rows if row["window"] == case.window),
            "xfeat_unique_tracks": len(xfeat_unique),
            **summary(victim_life, "victim_lifetime"),
            **summary(xfeat_life, "xfeat_lifetime"),
            **summary(victim_age, "victim_age_at_first_displacement"),
            **summary(xfeat_age, "xfeat_backend_age_at_first_export"),
            **summary(victim_quality, "victim_quality_at_first_displacement"),
            **summary(xfeat_quality, "xfeat_quality_at_first_export"),
            "probability_xfeat_lifetime_gt_victim_with_half_ties": probability_superiority(xfeat_life, victim_life),
            "median_lifetime_direction": lifetime_direction,
            "hypothesis_window_direction_consistent": (
                (case.group == "positive" and lifetime_direction == "XFEAT_GREATER")
                or (case.group == "harm_or_mixed" and lifetime_direction == "KLT_GREATER")
            ),
            "ape_klt_m": case.ape_klt,
            "ape_xfeat_m": case.ape_xfeat,
            "ape_change_pct": (case.ape_xfeat / case.ape_klt - 1.0) * 100.0,
            "rpe_klt_m": case.rpe_klt,
            "rpe_xfeat_m": case.rpe_xfeat,
            "rpe_change_pct": (case.rpe_xfeat / case.rpe_klt - 1.0) * 100.0,
        }
        summary_rows.append(summary_row)
        plot_data[case.window] = {"Displaced KLT": victim_life, "Inserted XFeat": xfeat_life}
        window_rows.append(
            {
                "window": case.window,
                "group": case.group,
                "frozen_outcome": case.outcome,
                "profile_and_config": case.profile,
                "exporter_sha256": case.exporter_sha256,
                "replacement_path": case.mechanism,
                "matching_method": case.matching,
                "klt_command_or_receipt": str(case.klt_dir / ("fsbc_command.txt" if (case.klt_dir / "fsbc_command.txt").exists() else "supplement_frontend_receipt.json")),
                "xfeat_command_or_receipt": str(case.xfeat_dir / ("fsbc_command.txt" if (case.xfeat_dir / "fsbc_command.txt").exists() else "supplement_frontend_receipt.json")),
                "klt_feature_bag": str(klt_bag),
                "klt_feature_bag_sha256": sha256(klt_bag),
                "xfeat_feature_bag": str(xfeat_bag),
                "xfeat_feature_bag_sha256": sha256(xfeat_bag),
                "different_feature_messages": len(different_messages),
                "different_feature_message_indices": ";".join(map(str, different_messages)),
                "identical_three_arm_exclusion": False,
            }
        )

    write_csv(output / "window_lineage_and_outcome.csv", window_rows)
    write_csv(output / "frontend_frame_evidence.csv", frame_rows)
    write_csv(output / "displaced_klt_observations.csv", victim_rows)
    write_csv(output / "inserted_xfeat_observations.csv", xfeat_rows)
    write_csv(output / "track_persistence_comparison.csv", summary_rows)
    write_csv(output / "replacement_closed_loop_timing.csv", timing_rows)
    july = audit_july_ablation()
    write_csv(output / "existing_bag_causal_ablation.csv", [july])
    manifest_paths.update(
        [
            Path(july["full_feature_bag"]),
            Path(july["drop_feature_bag"]),
            Path(july["full_replay_ape_report"]),
            Path(july["drop_replay_ape_report"]),
        ]
    )
    for evidence in (
        ROOT / "papers/frontend_same_backend_comparison/accuracy.csv",
        ROOT / "papers/frontend_same_backend_comparison/accuracy_repeats.csv",
        ROOT / "papers/frontend_same_backend_comparison/report.md",
        ROOT / "papers/frontend_same_backend_comparison_supplement/accuracy.csv",
        ROOT / "papers/frontend_same_backend_comparison_supplement/accuracy_repeats.csv",
        ROOT / "papers/frontend_same_backend_comparison_supplement/report.md",
        ROOT / "scripts/run_frontend_same_backend_comparison_supplement.py",
        ROOT / "scripts/run_aqualoc_archaeo_vins_eval.sh",
        ROOT / "scripts/learned_seedchain_env.sh",
        ROOT / "scripts/analyze_xfeat_replacement_attribution.py",
        ROOT / "uw_frontend/configs/experiments/low_texture_xfeat_seedchain_frontend.yaml",
        ROOT / "uw_frontend/ros/export_vins_features.py",
        ROOT / "artifacts/frontend_xfeat_replacement_attribution_v1/inputs/archaeo09_6000_6800.bag",
        Path("/mnt/data/AQUA-FE_WS/datasets/aqualoc/rosbags/archaeo09_6000_6800.bag"),
        CASES[0].xfeat_dir / "vins.log",
        ROOT / "artifacts/frontend_same_backend_comparison_supplement/replays/a06_s000_d045/xfeat_seed/repeat1/vins.log",
        ROOT / "artifacts/frontend_same_backend_comparison_supplement/replays/a06_s045_d045/xfeat_seed/repeat1/vins.log",
        ROOT / "artifacts/frontend_same_backend_comparison_supplement/replays/h07_s000_d050/xfeat_seed/repeat1/vins.log",
    ):
        if evidence.is_file():
            manifest_paths.add(evidence)

    roster_rows = [
        {"candidate": "a09_6000_6800", "status": "INCLUDED_POSITIVE", "reason": "formal all-arm common-support PASS; distinct bags; actual max 350"},
        {"candidate": "a06_s045_d045", "status": "INCLUDED_POSITIVE", "reason": "frozen supplement common-support PASS; XFeat lower APE and RPE"},
        {"candidate": "a06_s000_d045", "status": "INCLUDED_HARM_OR_MIXED", "reason": "frozen supplement; APE worse but RPE slightly lower"},
        {"candidate": "h07_s000_d050", "status": "INCLUDED_HARM", "reason": "frozen supplement; APE and RPE worse"},
        {"candidate": "a09_4000_4400", "status": "EXCLUDED_FROM_POSITIVE_GROUP", "reason": "formal runability not all-repeat PASS and learned budget exceeded 350"},
        {"candidate": "a10_2400_2800", "status": "EXCLUDED_FROM_POSITIVE_GROUP", "reason": "XFeat runability FAIL and learned budget exceeded 350"},
        {"candidate": "a10_4800_5200", "status": "EXCLUDED_FROM_POSITIVE_GROUP", "reason": "only 16 common poses, below frozen 30-pose gate"},
        {"candidate": "A10_samehistory_v4", "status": "EXCLUDED_FROM_POSITIVE_GROUP", "reason": "formal APE gate closed; KLT execution-integrity failure; winner explicitly forbidden"},
        {"candidate": "a02_4500_6300", "status": "EXCLUDED_IDENTICAL_INPUT", "reason": "KLT=SP+LG=XFeat feature bags byte-identical"},
        {"candidate": "afrl_fl_s180_d045", "status": "NEUTRAL_NOT_H_TEST", "reason": "near tie; old runner did not activate independent mirror, so no displacement accounting"},
    ]
    write_csv(output / "historical_window_roster.csv", roster_rows)

    # Figure 1: full backend-visible streaks by window and source.  Individual
    # tracks are descriptive repeated observations, not independent windows.
    fig, axes = plt.subplots(1, len(CASES), figsize=(10.5, 3.2), sharey=True)
    colors = {"Displaced KLT": "#0072B2", "Inserted XFeat": "#E69F00"}
    rng = np.random.default_rng(0)
    for axis, case in zip(axes, CASES):
        for pos, label in enumerate(("Displaced KLT", "Inserted XFeat"), start=1):
            values = np.asarray(plot_data[case.window][label], dtype=float)
            jitter = rng.uniform(-0.08, 0.08, len(values))
            axis.scatter(np.full(len(values), pos) + jitter, values, s=18, alpha=0.75, color=colors[label], edgecolors="none")
            axis.hlines(np.median(values), pos - 0.24, pos + 0.24, color="black", linewidth=1.6)
        axis.set_xticks([1, 2], ["KLT\nvictim", "XFeat"])
        axis.set_title(case.window.replace("_", "\n"), fontsize=9)
        axis.grid(axis="y", alpha=0.25)
        axis.set_yscale("log")
        axis.set_ylim(0.8, 80)
    axes[0].set_ylabel("Full backend-visible streak (published frames, log scale)")
    fig.tight_layout()
    fig.savefig(figures / "figure-01-track-lifetime-contrast.pdf", bbox_inches="tight")
    fig.savefig(figures / "figure-01-track-lifetime-contrast.png", dpi=600, bbox_inches="tight")
    plt.close(fig)

    # Figure 2: event timing and replacement count.
    fig, axes = plt.subplots(len(CASES), 1, figsize=(7.0, 6.2), constrained_layout=True)
    for axis, case in zip(axes, CASES):
        rows = [row for row in frame_rows if row["window"] == case.window]
        x = np.arange(len(rows))
        counts = np.asarray([int(row["exported_xfeat_features"]) for row in rows])
        axis.bar(x, counts, color="#E69F00", width=0.7)
        axis.set_xticks(x, [str(row["metric_frame_index"]) for row in rows])
        axis.set_ylabel("obs.")
        axis.set_title(case.window, fontsize=9, loc="left")
        axis.grid(axis="y", alpha=0.25)
    axes[-1].set_xlabel("Raw frontend frame_index (only replacement-active frames shown)")
    fig.savefig(figures / "figure-02-replacement-timeline.pdf", bbox_inches="tight")
    fig.savefig(figures / "figure-02-replacement-timeline.png", dpi=600, bbox_inches="tight")
    plt.close(fig)

    if args.safe_v4_dir:
        v4_dir = args.safe_v4_dir.resolve()
        v4_bag = v4_dir / "features.bag"
        v4_metrics = v4_dir / "frontend_metrics.csv"
        if v4_bag.is_file() and v4_metrics.is_file():
            baseline = CASES[0].klt_dir / "features.bag"
            rows = load_metrics(v4_metrics)
            v4_stream_sha, v4_message_count = bag_message_stream_digest(v4_bag)
            klt_stream_sha, klt_message_count = bag_message_stream_digest(baseline)
            stream_equal = (
                v4_message_count == klt_message_count
                and v4_stream_sha == klt_stream_sha
            )
            counterfactual = {
                "window": "a09_6000_6800",
                "profile": "lineage_early_seed_noharm_v4",
                "v4_feature_bag": str(v4_bag),
                "v4_feature_bag_sha256": sha256(v4_bag),
                "klt_feature_bag": str(baseline),
                "klt_feature_bag_sha256": sha256(baseline),
                "whole_bag_byte_identical": sha256(v4_bag) == sha256(baseline),
                "v4_backend_message_stream_sha256": v4_stream_sha,
                "klt_backend_message_stream_sha256": klt_stream_sha,
                "v4_backend_message_count": v4_message_count,
                "klt_backend_message_count": klt_message_count,
                "backend_message_stream_byte_identical": stream_equal,
                "xfeat_candidates_sum": sum(as_int(row.get("learned_candidate_count")) for row in rows),
                "xfeat_confirmed_sum": sum(as_int(row.get("learned_confirmed_xfeat_count")) for row in rows),
                "finalizer_input_sidecars_sum": sum(as_int(row.get("final_mirror_input_sidecars")) for row in rows),
                "finalizer_kept_sidecars_sum": sum(as_int(row.get("final_mirror_kept_sidecars")) for row in rows),
                "exported_xfeat_sum": sum(as_int(row.get("exported_xfeat_features")) for row in rows),
                "counterfactual_backend_source": "three existing frozen KLT replays; no new backend run",
                "counterfactual_ape_median_m": CASES[0].ape_klt,
                "counterfactual_ape_range_m": "1230.939397-1296.253955",
                "counterfactual_rpe_median_m": CASES[0].rpe_klt,
                "counterfactual_rpe_range_m": "149.678915-156.964956",
                "historical_xfeat_ape_median_m": CASES[0].ape_xfeat,
                "historical_xfeat_rpe_median_m": CASES[0].rpe_xfeat,
                "positive_disappears_under_exact_input_equivalence": stream_equal,
            }
            write_csv(output / "safe_v4_counterfactual.csv", [counterfactual])
            manifest_paths.update([v4_bag, v4_metrics])
            for name in ("counterfactual_command.txt", "aqualoc_archaeo09_pinhole.yaml"):
                candidate = v4_dir / name
                if candidate.is_file():
                    manifest_paths.add(candidate)

    source_manifest = [
        {"sha256": sha256(path), "bytes": path.stat().st_size, "path": str(path)}
        for path in sorted(manifest_paths, key=str)
    ]
    write_csv(output / "source_artifacts.sha256.csv", source_manifest)


if __name__ == "__main__":
    main()
