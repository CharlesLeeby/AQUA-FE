#!/usr/bin/env python3
"""Build an ID-level audit of the frozen coverage-monotone v2 feature bags.

This is a read-only post-hoc reducer.  It does not participate in the frozen
export path.  Raw candidate IDs and processed-frame ages were not emitted by
the v2 exporter, so the corresponding output fields are explicitly marked
Not available instead of being reconstructed from a different quantity.
"""

from __future__ import annotations

from collections import Counter, defaultdict
import csv
import hashlib
import io
import json
from pathlib import Path
from typing import Any

import numpy as np
import rosbag
import yaml


ROOT = Path("/home/ma/AQUA-FE_WS")
PAPER = ROOT / "papers/frontend_coverage_monotone_router_v2"
RUNTIME = Path(
    "/media/ma/Data/AQUA-FE_WS_storage_offload/"
    "frontend_coverage_monotone_router_v2"
)
SHADOW = RUNTIME / "shadow_root"
FEATURE_TOPIC = "/feature_tracker/feature"
SOURCE_NAMES = {
    0: "unknown",
    1: "klt",
    2: "gftt",
    4: "orb",
    5: "lk_recovery",
    6: "homography_recovery",
    10: "superpoint_lightglue",
    20: "xfeat",
    21: "classical_gftt",
    30: "loftr",
}


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as stream:
        return list(csv.DictReader(stream))


def write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    if not rows:
        raise RuntimeError(f"refusing to write empty audit: {path}")
    fields: list[str] = []
    for row in rows:
        for key in row:
            if key not in fields:
                fields.append(key)
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def integer(row: dict[str, str], key: str, default: int = 0) -> int:
    try:
        return int(float(row.get(key, str(default)) or default))
    except (TypeError, ValueError):
        return default


def real(row: dict[str, str], key: str) -> float | str:
    try:
        return float(row.get(key, "nan") or "nan")
    except (TypeError, ValueError):
        return "Not available"


def message_bytes(message: Any) -> bytes:
    stream = io.BytesIO()
    message.serialize(stream)
    return stream.getvalue()


def load_feature_frames(path: Path) -> list[dict[str, Any]]:
    frames: list[dict[str, Any]] = []
    with rosbag.Bag(str(path), "r") as bag:
        for _topic, message, record_time in bag.read_messages(
            topics=[FEATURE_TOPIC]
        ):
            channels = {
                channel.name: np.asarray(channel.values)
                for channel in message.channels
            }
            frames.append(
                {
                    "stamp_ns": int(message.header.stamp.to_nsec()),
                    "record_ns": int(record_time.to_nsec()),
                    "ids": np.rint(channels["id"]).astype(np.int64),
                    "sources": np.rint(channels["source_code"]).astype(np.int64),
                    "learned": channels["is_learned"] > 0.5,
                    "u": channels["p_u"].astype(np.float64),
                    "v": channels["p_v"].astype(np.float64),
                    "bytes": message_bytes(message),
                }
            )
    return frames


def bag_inventory(path: Path) -> dict[str, object]:
    topics: Counter[tuple[str, str]] = Counter()
    with rosbag.Bag(str(path), "r") as bag:
        for topic, message, _stamp in bag.read_messages():
            topics[(str(topic), str(message._type))] += 1
    topic_rows = [
        {"topic": topic, "type": type_name, "messages": count}
        for (topic, type_name), count in sorted(topics.items())
    ]
    return {
        "bytes": path.stat().st_size,
        "sha256": sha256(path),
        "messages": sum(topics.values()),
        "feature_messages": sum(
            count for (topic, _type), count in topics.items()
            if topic == FEATURE_TOPIC
        ),
        "topic_identity_json": json.dumps(topic_rows, sort_keys=True),
    }


def run_dir(window: dict[str, str], arm: dict[str, str]) -> Path:
    log_family = {
        "aqualoc_archaeology": "aqualoc_archaeo_vins",
        "aqualoc_harbor": "aqualoc_real_vins",
        "afrl": "afrl_cave_v31",
    }[window["family"]]
    return SHADOW / "logs" / log_family / (
        f"external_{arm['method']}_every{window['every_n']}_"
        f"gmrv2_{window['run_slug']}_{arm['arm']}"
    )


def image_shape(directory: Path) -> tuple[int, int]:
    for path in sorted(directory.glob("*.yaml")):
        if path.name.startswith("vins_"):
            continue
        text = path.read_text(encoding="utf-8")
        if text.startswith("%YAML:1.0"):
            text = text.replace("%YAML:1.0", "%YAML 1.1", 1)
        data = yaml.safe_load(text) or {}
        if "image_width" in data and "image_height" in data:
            return int(data["image_height"]), int(data["image_width"])
    raise RuntimeError(f"camera image shape unavailable in {directory}")


def cell_of(u: float, v: float, shape: tuple[int, int]) -> tuple[int, int]:
    height, width = shape
    col = min(5, max(0, int(np.floor(float(u) * 6.0 / max(1, width)))))
    row = min(3, max(0, int(np.floor(float(v) * 4.0 / max(1, height)))))
    return row, col


def cell_counts(frame: dict[str, Any], shape: tuple[int, int]) -> Counter[tuple[int, int]]:
    return Counter(
        cell_of(float(u), float(v), shape)
        for u, v in zip(frame["u"], frame["v"])
    )


def appearances(frames: list[dict[str, Any]]) -> dict[int, list[int]]:
    output: dict[int, list[int]] = defaultdict(list)
    for frame_index, frame in enumerate(frames):
        for track_id in frame["ids"]:
            output[int(track_id)].append(frame_index)
    return output


def visible_streak(
    track_frames: dict[int, list[int]], track_id: int, frame_index: int
) -> tuple[int, int, int]:
    sequence = track_frames[int(track_id)]
    position = sequence.index(frame_index)
    left = position
    while left > 0 and sequence[left - 1] == sequence[left] - 1:
        left -= 1
    right = position
    while right + 1 < len(sequence) and sequence[right + 1] == sequence[right] + 1:
        right += 1
    age = position - left + 1
    full = right - left + 1
    future = right - position
    return age, full, future


def persistent_cells(
    frame: dict[str, Any],
    track_frames: dict[int, list[int]],
    frame_index: int,
    minimum_age: int,
    shape: tuple[int, int],
) -> set[tuple[int, int]]:
    output: set[tuple[int, int]] = set()
    for index, track_id_value in enumerate(frame["ids"]):
        track_id = int(track_id_value)
        age, _full, _future = visible_streak(track_frames, track_id, frame_index)
        if age >= minimum_age:
            output.add(
                cell_of(float(frame["u"][index]), float(frame["v"][index]), shape)
            )
    return output


def json_values(values: list[object]) -> str:
    return json.dumps(values, separators=(",", ":"), sort_keys=True)


def main() -> int:
    windows = read_csv(PAPER / "development_windows.csv")
    arms = read_csv(PAPER / "arms.csv")
    klt_arm = next(arm for arm in arms if arm["arm"] == "klt")
    learned_arms = [arm for arm in arms if arm["arm"] != "klt"]
    action_rows: list[dict[str, object]] = []
    opportunity_rows: list[dict[str, object]] = []
    fallback_rows: list[dict[str, object]] = []

    for window in windows:
        klt_directory = run_dir(window, klt_arm)
        klt_bag = klt_directory / "features.bag"
        klt_frames = load_feature_frames(klt_bag)
        klt_tracks = appearances(klt_frames)
        shape = image_shape(klt_directory)
        klt_inventory = bag_inventory(klt_bag)

        for arm in learned_arms:
            directory = run_dir(window, arm)
            bag_path = directory / "features.bag"
            metrics_path = directory / "frontend_metrics.csv"
            receipt_path = directory / "frontend_receipt.json"
            metrics = read_csv(metrics_path)
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            frames = load_feature_frames(bag_path)
            learned_tracks = appearances(frames)
            inventory = bag_inventory(bag_path)
            if len(frames) != len(klt_frames) or len(metrics) != len(frames):
                raise RuntimeError(
                    f"frame-count mismatch for {window['run_slug']} {arm['arm']}"
                )
            if [frame["stamp_ns"] for frame in frames] != [
                frame["stamp_ns"] for frame in klt_frames
            ]:
                raise RuntimeError(
                    f"feature timestamp mismatch for {window['run_slug']} {arm['arm']}"
                )

            raw_candidates = 0
            survived_candidates = 0
            eligible_candidates = 0
            promoted_observations = 0
            promoted_ids: set[int] = set()
            action_frames = 0
            deleted_ids: set[int] = set()
            promoted_full_lifetimes: list[int] = []
            deleted_full_lifetimes: list[int] = []
            deleted_future_lifetimes: list[int] = []
            persistent_deltas = {2: [], 3: [], 5: []}

            for frame_index, (baseline, output, metric) in enumerate(
                zip(klt_frames, frames, metrics)
            ):
                if integer(metric, "selected_feature_index", -1) != frame_index:
                    raise RuntimeError(
                        "metrics/feature order mismatch for "
                        f"{window['run_slug']} {arm['arm']} frame {frame_index}"
                    )
                raw_candidates += integer(metric, "learned_candidate_count")
                survived_candidates += integer(metric, "learned_confirmed_count")
                eligible_candidates += integer(
                    metric, "final_mirror_persistence_source_eligible_sidecars"
                )

                learned_indices = np.flatnonzero(output["learned"])
                published_ids = [int(output["ids"][idx]) for idx in learned_indices]
                published_sources = [
                    int(output["sources"][idx]) for idx in learned_indices
                ]
                baseline_by_id = {
                    int(track_id): index
                    for index, track_id in enumerate(baseline["ids"])
                }
                output_classical_ids = {
                    int(value) for value in output["ids"][~output["learned"]]
                }
                missing = [
                    (track_id, index)
                    for track_id, index in baseline_by_id.items()
                    if track_id not in output_classical_ids
                ]
                metric_promoted = integer(metric, "final_mirror_kept_sidecars")
                metric_deleted = integer(
                    metric, "final_mirror_persistence_replaced_gftt"
                )
                if len(learned_indices) != metric_promoted:
                    raise RuntimeError(
                        f"published/promoted mismatch for {window['run_slug']} "
                        f"{arm['arm']} frame {frame_index}"
                    )
                if len(missing) != metric_deleted:
                    raise RuntimeError(
                        f"deleted/replaced mismatch for {window['run_slug']} "
                        f"{arm['arm']} frame {frame_index}"
                    )
                if not learned_indices.size and not missing:
                    continue

                action_frames += 1
                promoted_observations += len(published_ids)
                promoted_ids.update(published_ids)
                deleted_ids.update(track_id for track_id, _index in missing)
                before_counts = cell_counts(baseline, shape)
                after_counts = cell_counts(output, shape)
                promoted_cells = [
                    cell_of(float(output["u"][idx]), float(output["v"][idx]), shape)
                    for idx in learned_indices
                ]
                donor_cells = [
                    cell_of(
                        float(baseline["u"][index]),
                        float(baseline["v"][index]),
                        shape,
                    )
                    for _track_id, index in missing
                ]
                promoted_ages: list[int] = []
                promoted_lifetimes: list[int] = []
                promoted_future: list[int] = []
                for track_id in published_ids:
                    age, full, future = visible_streak(
                        learned_tracks, track_id, frame_index
                    )
                    promoted_ages.append(age)
                    promoted_lifetimes.append(full)
                    promoted_future.append(future)
                    promoted_full_lifetimes.append(full)
                donor_visible_ages: list[int] = []
                donor_lifetimes: list[int] = []
                donor_future: list[int] = []
                donor_sources: list[int] = []
                for track_id, index in missing:
                    age, full, future = visible_streak(
                        klt_tracks, track_id, frame_index
                    )
                    donor_visible_ages.append(age)
                    donor_lifetimes.append(full)
                    donor_future.append(future)
                    donor_sources.append(int(baseline["sources"][index]))
                    deleted_full_lifetimes.append(full)
                    deleted_future_lifetimes.append(future)

                persistent_values: dict[str, object] = {}
                for minimum_age in (2, 3, 5):
                    before_cells = persistent_cells(
                        baseline, klt_tracks, frame_index, minimum_age, shape
                    )
                    after_cells = persistent_cells(
                        output, learned_tracks, frame_index, minimum_age, shape
                    )
                    delta = len(after_cells) - len(before_cells)
                    persistent_deltas[minimum_age].append(delta)
                    persistent_values.update(
                        {
                            f"output_visible_age{minimum_age}_cells_before": len(before_cells),
                            f"output_visible_age{minimum_age}_cells_after": len(after_cells),
                            f"output_visible_age{minimum_age}_cell_delta": delta,
                        }
                    )

                action_rows.append(
                    {
                        "window_id": window["window_id"],
                        "run_slug": window["run_slug"],
                        "role": window["role"],
                        "arm": arm["arm"],
                        "method": arm["method"],
                        "selected_feature_index": frame_index,
                        "raw_frame_index": metric.get("frame_index", ""),
                        "timestamp_ns": baseline["stamp_ns"],
                        "raw_candidate_observations": integer(
                            metric, "learned_candidate_count"
                        ),
                        "raw_candidate_distinct_ids": "Not available",
                        "candidate_survived_observations": integer(
                            metric, "learned_confirmed_count"
                        ),
                        "candidate_eligible_observations": integer(
                            metric,
                            "final_mirror_persistence_source_eligible_sidecars",
                        ),
                        "promoted_observations": len(published_ids),
                        "promoted_distinct_ids": len(set(published_ids)),
                        "promoted_ids_json": json_values(published_ids),
                        "promoted_source_codes_json": json_values(published_sources),
                        "promoted_sources_json": json_values(
                            [SOURCE_NAMES.get(code, f"code_{code}") for code in published_sources]
                        ),
                        "promoted_raw_processed_frame_age": real(
                            metric, "exported_learned_median_age"
                        ),
                        "promoted_output_visible_age_json": json_values(promoted_ages),
                        "promoted_output_visible_full_streak_json": json_values(
                            promoted_lifetimes
                        ),
                        "promoted_output_visible_future_frames_json": json_values(
                            promoted_future
                        ),
                        "deleted_track_count": len(missing),
                        "deleted_track_ids_json": json_values(
                            [track_id for track_id, _index in missing]
                        ),
                        "deleted_track_source_codes_json": json_values(donor_sources),
                        "deleted_track_sources_json": json_values(
                            [SOURCE_NAMES.get(code, f"code_{code}") for code in donor_sources]
                        ),
                        "deleted_track_raw_age_max": integer(
                            metric,
                            "final_mirror_persistence_replaced_gftt_max_age",
                            -1,
                        ),
                        "deleted_track_per_id_raw_age": "Not available",
                        "deleted_track_output_visible_age_json": json_values(
                            donor_visible_ages
                        ),
                        "deleted_track_klt_counterfactual_full_streak_json": json_values(
                            donor_lifetimes
                        ),
                        "deleted_track_klt_counterfactual_future_frames_json": json_values(
                            donor_future
                        ),
                        "donor_cells_json": json_values(donor_cells),
                        "candidate_cells_json": json_values(promoted_cells),
                        "donor_cell_occupancy_before_json": json_values(
                            [before_counts[cell] for cell in donor_cells]
                        ),
                        "donor_cell_occupancy_after_json": json_values(
                            [after_counts[cell] for cell in donor_cells]
                        ),
                        "candidate_cell_occupancy_before_json": json_values(
                            [before_counts[cell] for cell in promoted_cells]
                        ),
                        "candidate_cell_occupancy_after_json": json_values(
                            [after_counts[cell] for cell in promoted_cells]
                        ),
                        "raw_grid_cells_before_reconstructed": len(before_counts),
                        "raw_grid_cells_after_reconstructed": len(after_counts),
                        "raw_grid_cell_delta_reconstructed": len(after_counts) - len(before_counts),
                        "raw_grid_cells_before_metric": integer(
                            metric,
                            "final_mirror_persistence_grid_cells_before",
                            -1,
                        ),
                        "raw_grid_cells_after_metric": integer(
                            metric,
                            "final_mirror_persistence_grid_cells_after",
                            -1,
                        ),
                        "donor_cell_min_remaining_metric": integer(
                            metric,
                            "final_mirror_persistence_donor_cell_min_remaining",
                            -1,
                        ),
                        **persistent_values,
                        "feature_count_before": len(baseline["ids"]),
                        "feature_count_after": len(output["ids"]),
                        "feature_cap": 350,
                        "published_to_feature_bag": True,
                        "actually_visible_to_vins_if_replayed": True,
                        "backend_replayed_in_v2": False,
                        "profile": receipt["profile"],
                        "runner_schema": receipt["schema_version"],
                        "run_dir": str(directory),
                    }
                )

            if action_frames == 0:
                action_rows.append(
                    {
                        "window_id": window["window_id"],
                        "run_slug": window["run_slug"],
                        "role": window["role"],
                        "arm": arm["arm"],
                        "method": arm["method"],
                        "selected_feature_index": -1,
                        "raw_frame_index": "",
                        "timestamp_ns": "",
                        "raw_candidate_observations": raw_candidates,
                        "raw_candidate_distinct_ids": "Not available",
                        "candidate_survived_observations": survived_candidates,
                        "candidate_eligible_observations": eligible_candidates,
                        "promoted_observations": 0,
                        "promoted_distinct_ids": 0,
                        "deleted_track_count": 0,
                        "raw_grid_cell_delta_reconstructed": 0,
                        "feature_cap": 350,
                        "published_to_feature_bag": False,
                        "actually_visible_to_vins_if_replayed": False,
                        "backend_replayed_in_v2": False,
                        "profile": receipt["profile"],
                        "runner_schema": receipt["schema_version"],
                        "run_dir": str(directory),
                        "notes": "zero-action arm-window summary sentinel",
                    }
                )

            opportunity_rows.append(
                {
                    "window_id": window["window_id"],
                    "run_slug": window["run_slug"],
                    "role": window["role"],
                    "arm": arm["arm"],
                    "candidate_source": (
                        "xfeat" if arm["arm"] == "router_xfeat"
                        else "superpoint_lightglue"
                    ),
                    "raw_candidate_observations": raw_candidates,
                    "raw_candidate_distinct_ids": "Not available",
                    "survived_candidate_observations": survived_candidates,
                    "source_eligible_candidate_observations": eligible_candidates,
                    "action_frames": action_frames,
                    "promoted_observations": promoted_observations,
                    "promoted_distinct_ids": len(promoted_ids),
                    "promoted_id_max_output_observations": max(
                        promoted_full_lifetimes, default=0
                    ),
                    "deleted_distinct_ids": len(deleted_ids),
                    "deleted_klt_counterfactual_full_streak_max": max(
                        deleted_full_lifetimes, default=0
                    ),
                    "deleted_klt_counterfactual_future_frames_max": max(
                        deleted_future_lifetimes, default=0
                    ),
                    "output_visible_age2_cell_delta_max": max(
                        persistent_deltas[2], default=0
                    ),
                    "output_visible_age3_cell_delta_max": max(
                        persistent_deltas[3], default=0
                    ),
                    "output_visible_age5_cell_delta_max": max(
                        persistent_deltas[5], default=0
                    ),
                    "feature_bag": str(bag_path),
                    "feature_bag_sha256": inventory["sha256"],
                    "frontend_metrics": str(metrics_path),
                    "frontend_metrics_sha256": sha256(metrics_path),
                    "receipt": str(receipt_path),
                    "receipt_profile": receipt["profile"],
                    "receipt_schema": receipt["schema_version"],
                }
            )

            zero_action = promoted_observations == 0
            fallback_rows.append(
                {
                    "window_id": window["window_id"],
                    "run_slug": window["run_slug"],
                    "arm": arm["arm"],
                    "zero_action": zero_action,
                    "comparison_applicable": zero_action,
                    "klt_file_bytes": klt_inventory["bytes"],
                    "candidate_file_bytes": inventory["bytes"],
                    "file_size_equal": klt_inventory["bytes"] == inventory["bytes"],
                    "klt_total_messages": klt_inventory["messages"],
                    "candidate_total_messages": inventory["messages"],
                    "total_message_count_equal": klt_inventory["messages"] == inventory["messages"],
                    "klt_feature_messages": klt_inventory["feature_messages"],
                    "candidate_feature_messages": inventory["feature_messages"],
                    "feature_message_count_equal": klt_inventory["feature_messages"] == inventory["feature_messages"],
                    "klt_topic_identity_json": klt_inventory["topic_identity_json"],
                    "candidate_topic_identity_json": inventory["topic_identity_json"],
                    "topic_identity_equal": klt_inventory["topic_identity_json"] == inventory["topic_identity_json"],
                    "klt_sha256": klt_inventory["sha256"],
                    "candidate_sha256": inventory["sha256"],
                    "byte_identical": klt_inventory["sha256"] == inventory["sha256"],
                    "exact_fallback_pass": (
                        (klt_inventory["sha256"] == inventory["sha256"])
                        if zero_action else "Not applicable: action-positive"
                    ),
                    "klt_feature_bag": str(klt_bag),
                    "candidate_feature_bag": str(bag_path),
                }
            )

    write_csv(PAPER / "action_audit.csv", action_rows)
    write_csv(PAPER / "opportunity_audit.csv", opportunity_rows)
    write_csv(PAPER / "exact_fallback.csv", fallback_rows)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
