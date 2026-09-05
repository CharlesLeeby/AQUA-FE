#!/usr/bin/env python3
"""Build the compact v2 learned-lineage and donor-loss diagnostic.

Run with ROS Noetic's system Python after sourcing ROS so ``rosbag`` and the
PointCloud message classes are available.  The script is read-only with
respect to frozen bags/metrics and writes one paper CSV.
"""

from __future__ import annotations

import csv
import json
from collections import defaultdict
from pathlib import Path

import rosbag


ROOT = Path("/home/ma/AQUA-FE_WS")
PAPER = ROOT / "papers/frontend_coverage_monotone_router_v2"
ACTION_AUDIT = PAPER / "action_audit.csv"
BACKEND_PLAN = PAPER / "backend_smoke_plan.csv"
OUTPUT = PAPER / "lineage_diagnostic.csv"
FEATURE_TOPIC = "/feature_tracker/feature"


FIELDS = [
    "record_type",
    "window_id",
    "run_slug",
    "arm",
    "source",
    "feature_id",
    "action_selected_feature_index",
    "action_raw_frame_index",
    "action_timestamp_ns",
    "internal_candidate_birth",
    "internal_candidate_last_survival",
    "internal_identity_evidence",
    "first_published_selected_feature_index",
    "last_published_selected_feature_index",
    "published_selected_feature_indices_json",
    "first_published_raw_frame_index",
    "last_published_raw_frame_index",
    "first_published_timestamp_ns",
    "last_published_timestamp_ns",
    "published_observations",
    "longest_consecutive_published_observations",
    "feature_bag_observations_available_to_backend",
    "backend_replay_received_observations",
    "backend_actual_feature_set_or_residual_use",
    "initializer_triangulation_eligible_by_observation_count",
    "nonlinear_residual_eligible_by_observation_count",
    "publication_termination_evidence",
    "next_output_selected_feature_index",
    "next_output_tracker_learned_count",
    "next_output_pre_gate_sidecars",
    "next_output_final_input_sidecars",
    "next_output_horizon_blocked",
    "next_output_benefit_reason",
    "run_pre_final_sidecars_consuming_budget",
    "run_published_learned_observations",
    "run_pre_final_minus_published",
    "feature_id_collision_in_any_message",
    "baseline_observations_for_donor_id",
    "v2_observations_for_donor_id",
    "baseline_selected_feature_indices_json",
    "v2_selected_feature_indices_json",
    "actual_missing_observations_vs_klt",
    "missing_selected_feature_indices_json",
    "donor_reappeared_after_action",
    "first_reappearance_selected_feature_index",
    "v2_donor_contiguous_after_first_appearance",
    "klt_counterfactual_future_frames_from_action_audit",
    "candidate_observations_added_on_action_frame",
    "notes",
]


def integer(value: object, default: int = 0) -> int:
    try:
        return int(float(str(value)))
    except (TypeError, ValueError):
        return default


def parse_json_list(value: str) -> list[int]:
    if not value:
        return []
    return [int(item) for item in json.loads(value)]


def longest_consecutive(values: list[int]) -> int:
    if not values:
        return 0
    best = current = 1
    for previous, current_value in zip(values, values[1:]):
        current = current + 1 if current_value == previous + 1 else 1
        best = max(best, current)
    return best


def read_feature_bag(path: Path) -> tuple[list[dict[str, object]], bool]:
    frames: list[dict[str, object]] = []
    collision = False
    with rosbag.Bag(str(path), "r") as bag:
        for _, message, _ in bag.read_messages(topics=[FEATURE_TOPIC]):
            names = [channel.name for channel in message.channels]
            channel = {name: idx for idx, name in enumerate(names)}
            ids = [int(round(value)) for value in message.channels[channel["id"]].values]
            sources = [
                int(round(value))
                for value in message.channels[channel["source_code"]].values
            ]
            learned = [
                bool(round(value))
                for value in message.channels[channel["is_learned"]].values
            ]
            collision = collision or len(ids) != len(set(ids))
            frames.append(
                {
                    "timestamp_ns": int(message.header.stamp.to_nsec()),
                    "ids": ids,
                    "sources": sources,
                    "learned": learned,
                }
            )
    return frames, collision


def source_name(code: int) -> str:
    return {10: "superpoint_lightglue", 20: "xfeat"}.get(code, f"code_{code}")


def metric_learned_count(row: dict[str, str] | None) -> int:
    if row is None:
        return 0
    histogram = row.get("tracker_source_histogram", "")
    total = 0
    for token in histogram.split(";"):
        if ":" not in token:
            continue
        name, count = token.rsplit(":", 1)
        if "xfeat" in name or "superpoint" in name or "lightglue" in name:
            total += integer(count)
    return total


def termination_evidence(
    published: list[int],
    next_metric: dict[str, str] | None,
) -> str:
    if next_metric is None:
        return "end_of_export_or_no_next_output"
    benefit = next_metric.get("learned_export_benefit_reason", "")
    if integer(next_metric.get("final_mirror_persistence_horizon_blocked")):
        return "final_router_horizon_blocked_aggregate; exact_same_identity=Unknown"
    if "online_seed_budget" in benefit:
        return "upstream_sequence_observation_budget; exact_same_identity=Unknown"
    if "online_seed_microburst_no_extend" in benefit:
        return "upstream_microburst_no_extend; exact_same_identity=Unknown"
    if metric_learned_count(next_metric) == 0:
        return "no_learned_track_at_next_output; exact_internal_termination=Unknown"
    if integer(next_metric.get("final_mirror_input_sidecars")) == 0:
        return "learned_tracks_remain_aggregate_but_stop_before_final_router; exact_same_identity=Unknown"
    return "not_republished_despite_aggregate_sidecars; exact_same_identity_and_gate=Unknown"


def main() -> int:
    actions = list(csv.DictReader(ACTION_AUDIT.open(encoding="utf-8")))
    actions = [row for row in actions if integer(row.get("promoted_observations")) > 0]
    backend_rows = list(csv.DictReader(BACKEND_PLAN.open(encoding="utf-8")))
    klt_bag_by_run = {
        row["run_slug"]: Path(row["feature_bag"])
        for row in backend_rows
        if row["cell_id"] == "klt" and row["repeat"] == "1"
    }

    run_actions: dict[tuple[str, str], list[dict[str, str]]] = defaultdict(list)
    for row in actions:
        run_actions[(row["run_slug"], row["arm"])].append(row)

    output_rows: list[dict[str, object]] = []
    for (run_slug, arm), grouped_actions in sorted(run_actions.items()):
        exemplar = grouped_actions[0]
        run_dir = Path(exemplar["run_dir"])
        learned_frames, learned_collision = read_feature_bag(run_dir / "features.bag")
        klt_frames, klt_collision = read_feature_bag(klt_bag_by_run[run_slug])
        if len(learned_frames) != len(klt_frames):
            raise RuntimeError(f"feature frame count mismatch for {run_slug}/{arm}")
        metrics = list(csv.DictReader((run_dir / "frontend_metrics.csv").open(encoding="utf-8")))
        metric_by_selected = {
            integer(row["selected_feature_index"], -1): row for row in metrics
        }

        learned_occurrences: dict[tuple[int, int], list[int]] = defaultdict(list)
        for selected, frame in enumerate(learned_frames):
            for track_id, code, is_learned in zip(
                frame["ids"], frame["sources"], frame["learned"]
            ):
                if is_learned:
                    learned_occurrences[(int(track_id), int(code))].append(selected)

        run_pre_final = sum(integer(row["final_mirror_input_sidecars"]) for row in metrics)
        run_published = sum(integer(row["exported_learned_features"]) for row in metrics)

        for (track_id, code), published in sorted(learned_occurrences.items()):
            first, last = published[0], published[-1]
            first_metric = metric_by_selected.get(first)
            last_metric = metric_by_selected.get(last)
            next_selected = last + 1
            next_metric = metric_by_selected.get(next_selected)
            output_rows.append(
                {
                    "record_type": "learned_lineage",
                    "window_id": exemplar["window_id"],
                    "run_slug": run_slug,
                    "arm": arm,
                    "source": source_name(code),
                    "feature_id": track_id,
                    "internal_candidate_birth": "Unknown (per-ID internal state not instrumented)",
                    "internal_candidate_last_survival": "Unknown (per-ID internal state not instrumented)",
                    "internal_identity_evidence": (
                        "Only aggregate tracker/source-provenance counts exist after the final published frame"
                    ),
                    "first_published_selected_feature_index": first,
                    "last_published_selected_feature_index": last,
                    "published_selected_feature_indices_json": json.dumps(published),
                    "first_published_raw_frame_index": (
                        integer(first_metric.get("frame_index"), -1)
                        if first_metric
                        else "Unknown"
                    ),
                    "last_published_raw_frame_index": (
                        integer(last_metric.get("frame_index"), -1)
                        if last_metric
                        else "Unknown"
                    ),
                    "first_published_timestamp_ns": (
                        int(learned_frames[first]["timestamp_ns"])
                    ),
                    "last_published_timestamp_ns": (
                        int(learned_frames[last]["timestamp_ns"])
                    ),
                    "published_observations": len(published),
                    "longest_consecutive_published_observations": longest_consecutive(published),
                    "feature_bag_observations_available_to_backend": len(published),
                    "backend_replay_received_observations": (
                        "Unknown (no per-ID backend receipt; containing feature message "
                        "was replayed in 3/3 completed backend runs)"
                    ),
                    "backend_actual_feature_set_or_residual_use": (
                        "Unknown (locked backend has no per-ID feature-set/residual receipt)"
                    ),
                    "initializer_triangulation_eligible_by_observation_count": len(published) >= 2,
                    "nonlinear_residual_eligible_by_observation_count": len(published) >= 4,
                    "publication_termination_evidence": termination_evidence(published, next_metric),
                    "next_output_selected_feature_index": (
                        next_selected if next_metric is not None else ""
                    ),
                    "next_output_tracker_learned_count": metric_learned_count(next_metric),
                    "next_output_pre_gate_sidecars": (
                        integer(next_metric.get("pre_gate_sidecar_total")) if next_metric else ""
                    ),
                    "next_output_final_input_sidecars": (
                        integer(next_metric.get("final_mirror_input_sidecars")) if next_metric else ""
                    ),
                    "next_output_horizon_blocked": (
                        integer(next_metric.get("final_mirror_persistence_horizon_blocked"))
                        if next_metric
                        else ""
                    ),
                    "next_output_benefit_reason": (
                        next_metric.get("learned_export_benefit_reason", "") if next_metric else ""
                    ),
                    "run_pre_final_sidecars_consuming_budget": run_pre_final,
                    "run_published_learned_observations": run_published,
                    "run_pre_final_minus_published": run_pre_final - run_published,
                    "feature_id_collision_in_any_message": learned_collision,
                    "notes": (
                        "Processed-frame age is not lineage lifetime. Published IDs are exact bag observations. "
                        "The locked backend accepts all received IDs, can triangulate >=2-observation tracks "
                        "during initialization, and requires >=4 stored observations for nonlinear visual residuals."
                    ),
                }
            )

        learned_id_sets = [set(frame["ids"]) for frame in learned_frames]
        klt_id_sets = [set(frame["ids"]) for frame in klt_frames]
        for action in sorted(
            grouped_actions, key=lambda row: integer(row["selected_feature_index"])
        ):
            selected = integer(action["selected_feature_index"])
            donors = parse_json_list(action["deleted_track_ids_json"])
            future = parse_json_list(
                action["deleted_track_klt_counterfactual_future_frames_json"]
            )
            if len(donors) != integer(action["promoted_observations"]):
                raise RuntimeError(
                    f"donor/promotion dose mismatch for {run_slug}/{arm}/"
                    f"selected-{selected}: {len(donors)} != "
                    f"{action['promoted_observations']}"
                )
            for donor_index, donor_id in enumerate(donors):
                klt_occ = [i for i, ids in enumerate(klt_id_sets) if donor_id in ids]
                learned_occ = [i for i, ids in enumerate(learned_id_sets) if donor_id in ids]
                missing = sorted(set(klt_occ) - set(learned_occ))
                later = [i for i in learned_occ if i > selected]
                output_rows.append(
                    {
                        "record_type": "donor_event",
                        "window_id": action["window_id"],
                        "run_slug": run_slug,
                        "arm": arm,
                        "source": "gftt",
                        "feature_id": donor_id,
                        "action_selected_feature_index": selected,
                        "action_raw_frame_index": action["raw_frame_index"],
                        "action_timestamp_ns": action["timestamp_ns"],
                        "backend_replay_received_observations": (
                            "Unknown (no per-ID backend receipt; containing feature message "
                            "was replayed in 3/3 completed backend runs)"
                        ),
                        "backend_actual_feature_set_or_residual_use": (
                            "Unknown (locked backend has no per-ID feature-set/residual receipt)"
                        ),
                        "feature_id_collision_in_any_message": (
                            learned_collision or klt_collision
                        ),
                        "baseline_observations_for_donor_id": len(klt_occ),
                        "v2_observations_for_donor_id": len(learned_occ),
                        "baseline_selected_feature_indices_json": json.dumps(klt_occ),
                        "v2_selected_feature_indices_json": json.dumps(learned_occ),
                        "actual_missing_observations_vs_klt": len(missing),
                        "missing_selected_feature_indices_json": json.dumps(missing),
                        "donor_reappeared_after_action": bool(later),
                        "first_reappearance_selected_feature_index": later[0] if later else "",
                        "v2_donor_contiguous_after_first_appearance": (
                            longest_consecutive(learned_occ) == len(learned_occ)
                        ),
                        "klt_counterfactual_future_frames_from_action_audit": (
                            future[donor_index] if donor_index < len(future) else ""
                        ),
                        # Each row is one exact donor-for-candidate exchange.  Keep
                        # this additive so column sums recover the true 21-observation
                        # intervention dose rather than repeating the frame dose once
                        # for every donor on that frame.
                        "candidate_observations_added_on_action_frame": 1,
                        "notes": (
                            "Future KLT visibility is an offline counterfactual, not online information. "
                            "Missing count is computed from the actual fresh-KLT and v2 bags."
                        ),
                    }
                )

    lineage_count = sum(row["record_type"] == "learned_lineage" for row in output_rows)
    donor_count = sum(row["record_type"] == "donor_event" for row in output_rows)
    if lineage_count != 14 or donor_count != 21:
        raise RuntimeError(
            f"expected 14 lineages and 21 donor events, got {lineage_count}/{donor_count}"
        )
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(output_rows)
    print(
        json.dumps(
            {
                "output": str(OUTPUT),
                "learned_lineages": lineage_count,
                "donor_events": donor_count,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
