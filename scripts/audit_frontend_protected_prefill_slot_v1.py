#!/usr/bin/env python3
"""Audit the frozen protected pre-refill slot v1 frontend matrix."""

from __future__ import annotations

from collections import Counter
import csv
import io
import json
from pathlib import Path
from typing import Any

import numpy as np
import rosbag

import audit_frontend_coverage_monotone_router_v2_actions as common


ROOT = Path("/home/ma/AQUA-FE_WS")
PAPER = ROOT / "papers/frontend_protected_prefill_slot_v1"
RUNTIME = Path(
    "/media/ma/Data/AQUA-FE_WS_storage_offload/"
    "frontend_protected_prefill_slot_v1"
)
SHADOW = RUNTIME / "shadow_root"
FEATURE_TOPIC = "/feature_tracker/feature"


def run_dir(window: dict[str, str], arm: dict[str, str]) -> Path:
    log_family = {
        "aqualoc_archaeology": "aqualoc_archaeo_vins",
        "aqualoc_harbor": "aqualoc_real_vins",
        "afrl": "afrl_cave_v31",
    }[window["family"]]
    return SHADOW / "logs" / log_family / (
        f"external_{arm['method']}_every{window['every_n']}_"
        f"ppsv1_{window['run_slug']}_{arm['arm']}"
    )


def integer(row: dict[str, str], key: str, default: int = 0) -> int:
    try:
        return int(float(row.get(key, str(default)) or default))
    except (TypeError, ValueError):
        return default


def message_bytes(message: Any) -> bytes:
    stream = io.BytesIO()
    message.serialize(stream)
    return stream.getvalue()


def load_frames(path: Path) -> list[dict[str, Any]]:
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
                    "channels": channels,
                    "bytes": message_bytes(message),
                }
            )
    return frames


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


def observation_equal(
    baseline: dict[str, Any], baseline_index: int,
    output: dict[str, Any], output_index: int,
) -> bool:
    if list(baseline["channels"]) != list(output["channels"]):
        return False
    for name in baseline["channels"]:
        left = baseline["channels"][name]
        right = output["channels"][name]
        if not np.array_equal(left[baseline_index], right[output_index]):
            return False
    return True


def main() -> int:
    windows = common.read_csv(PAPER / "development_windows.csv")
    arms = common.read_csv(PAPER / "arms.csv")
    klt_arm = next(row for row in arms if row["arm"] == "klt")
    learned_arms = [row for row in arms if row["arm"] != "klt"]
    frontend_rows: list[dict[str, object]] = []
    action_rows: list[dict[str, object]] = []
    fallback_rows: list[dict[str, object]] = []

    for window in windows:
        klt_directory = run_dir(window, klt_arm)
        klt_bag = klt_directory / "features.bag"
        klt_receipt = json.loads(
            (klt_directory / "frontend_receipt.json").read_text(encoding="utf-8")
        )
        klt_frames = load_frames(klt_bag)
        klt_inventory = common.bag_inventory(klt_bag)
        frontend_rows.append(
            {
                "window_id": window["window_id"],
                "run_slug": window["run_slug"],
                "role": window["role"],
                "arm": "klt",
                "method": "klt",
                "cell_status": "COMPLETE",
                "integrity_pass": bool(klt_receipt["integrity_pass"]),
                "feature_messages": len(klt_frames),
                "frontend_coverage": klt_receipt["frontend_coverage"],
                "max_features": klt_receipt["max_features"],
                "action_frames": 0,
                "admitted_sidecars": 0,
                "omitted_newborns": 0,
                "carried_observation_mismatches": 0,
                "structural_pass": bool(klt_receipt["integrity_pass"]),
                "byte_identical_to_klt": True,
                "feature_bag": str(klt_bag),
                "feature_bag_sha256": klt_inventory["sha256"],
            }
        )

        for arm in learned_arms:
            directory = run_dir(window, arm)
            bag_path = directory / "features.bag"
            metrics_path = directory / "frontend_metrics.csv"
            receipt = json.loads(
                (directory / "frontend_receipt.json").read_text(encoding="utf-8")
            )
            metrics = common.read_csv(metrics_path)
            frames = load_frames(bag_path)
            inventory = common.bag_inventory(bag_path)
            if len(frames) != len(klt_frames) or len(metrics) != len(frames):
                raise RuntimeError(
                    f"frame-count mismatch: {window['run_slug']} {arm['arm']}"
                )
            if [row["stamp_ns"] for row in frames] != [
                row["stamp_ns"] for row in klt_frames
            ]:
                raise RuntimeError(
                    f"timestamp mismatch: {window['run_slug']} {arm['arm']}"
                )

            action_frames = 0
            admitted_total = 0
            omitted_total = 0
            carried_mismatches = 0
            nonbirth_omissions = 0
            extra_classical = 0
            source_violations = 0
            age_violations = 0
            action_frame_violations = 0
            count_violations = 0
            max_admitted = 0
            source_counts: Counter[int] = Counter()

            for index, (baseline, output, metric) in enumerate(
                zip(klt_frames, frames, metrics)
            ):
                if integer(metric, "selected_feature_index", -1) != index:
                    raise RuntimeError(
                        f"metrics order mismatch: {window['run_slug']} "
                        f"{arm['arm']} frame {index}"
                    )
                baseline_by_id = {
                    int(track_id): idx
                    for idx, track_id in enumerate(baseline["ids"])
                }
                output_by_id = {
                    int(track_id): idx
                    for idx, track_id in enumerate(output["ids"])
                }
                output_classical_ids = {
                    int(track_id)
                    for track_id, learned in zip(output["ids"], output["learned"])
                    if not bool(learned)
                }
                missing_ids = [
                    track_id
                    for track_id in baseline_by_id
                    if track_id not in output_classical_ids
                ]
                missing_sources = [
                    int(baseline["sources"][baseline_by_id[track_id]])
                    for track_id in missing_ids
                ]
                output_baseline_ids = {
                    int(track_id)
                    for track_id in output_classical_ids
                    if int(track_id) in baseline_by_id
                }
                extra_classical += len(output_classical_ids - output_baseline_ids)

                carried_ids = [
                    int(track_id)
                    for track_id, source in zip(
                        baseline["ids"], baseline["sources"]
                    )
                    if int(source) != 2
                ]
                frame_carried_mismatches = 0
                for track_id in carried_ids:
                    if track_id not in output_by_id:
                        frame_carried_mismatches += 1
                        continue
                    if not observation_equal(
                        baseline,
                        baseline_by_id[track_id],
                        output,
                        output_by_id[track_id],
                    ):
                        frame_carried_mismatches += 1
                carried_mismatches += frame_carried_mismatches
                frame_nonbirth = sum(code != 2 for code in missing_sources)
                nonbirth_omissions += frame_nonbirth

                learned_indices = np.flatnonzero(output["learned"])
                learned_ids = [int(output["ids"][idx]) for idx in learned_indices]
                learned_sources = [
                    int(output["sources"][idx]) for idx in learned_indices
                ]
                source_counts.update(learned_sources)
                admitted = integer(
                    metric, "final_mirror_prefill_slot_admitted_sidecars"
                )
                omitted = integer(
                    metric, "final_mirror_prefill_slot_omitted_newborns"
                )
                expected_omitted = max(
                    0, len(baseline["ids"]) + admitted - 350
                )
                frame_count_violation = int(
                    len(learned_ids) != admitted
                    or len(missing_ids) != omitted
                    or omitted != expected_omitted
                    or len(output["ids"]) > 350
                )
                count_violations += frame_count_violation
                frame_source_violation = sum(code not in {10, 20} for code in learned_sources)
                source_violations += frame_source_violation
                median_age = float(metric.get("exported_learned_median_age") or "nan")
                frame_age_violation = int(
                    admitted > 0 and (not np.isfinite(median_age) or median_age < 3)
                )
                age_violations += frame_age_violation
                frame_action_violation = int(admitted > 0 and not (0 <= index <= 4))
                action_frame_violations += frame_action_violation

                if admitted > 0 or omitted > 0:
                    action_frames += 1
                    admitted_total += admitted
                    omitted_total += omitted
                    max_admitted = max(max_admitted, admitted)
                    action_rows.append(
                        {
                            "window_id": window["window_id"],
                            "run_slug": window["run_slug"],
                            "role": window["role"],
                            "arm": arm["arm"],
                            "method": arm["method"],
                            "selected_feature_index": index,
                            "timestamp_ns": baseline["stamp_ns"],
                            "baseline_feature_count": len(baseline["ids"]),
                            "output_feature_count": len(output["ids"]),
                            "carried_observations": integer(
                                metric,
                                "final_mirror_prefill_slot_carried_observations",
                            ),
                            "baseline_newborns": integer(
                                metric,
                                "final_mirror_prefill_slot_baseline_newborns",
                            ),
                            "pre_refill_vacant_capacity": integer(
                                metric,
                                "final_mirror_prefill_slot_vacant_capacity",
                            ),
                            "eligible_sidecars": integer(
                                metric,
                                "final_mirror_prefill_slot_eligible_sidecars",
                            ),
                            "admitted_sidecars": admitted,
                            "admitted_ids_json": json.dumps(learned_ids),
                            "admitted_source_codes_json": json.dumps(learned_sources),
                            "admitted_median_raw_age": median_age,
                            "omitted_newborns": omitted,
                            "omitted_ids_json": json.dumps(missing_ids),
                            "omitted_source_codes_json": json.dumps(missing_sources),
                            "carried_observation_mismatches": frame_carried_mismatches,
                            "nonbirth_omissions": frame_nonbirth,
                            "extra_classical_observations": len(
                                output_classical_ids - output_baseline_ids
                            ),
                            "count_contract_violation": frame_count_violation,
                            "source_contract_violation": frame_source_violation,
                            "age_contract_violation": frame_age_violation,
                            "frame_contract_violation": frame_action_violation,
                            "structural_pass": not any(
                                (
                                    frame_carried_mismatches,
                                    frame_nonbirth,
                                    frame_count_violation,
                                    frame_source_violation,
                                    frame_age_violation,
                                    frame_action_violation,
                                )
                            ),
                        }
                    )

            byte_identical = inventory["sha256"] == klt_inventory["sha256"]
            structural_pass = bool(
                receipt["integrity_pass"]
                and carried_mismatches == 0
                and nonbirth_omissions == 0
                and extra_classical == 0
                and source_violations == 0
                and age_violations == 0
                and action_frame_violations == 0
                and count_violations == 0
                and max_admitted <= 6
                and (admitted_total > 0 or byte_identical)
            )
            frontend_rows.append(
                {
                    "window_id": window["window_id"],
                    "run_slug": window["run_slug"],
                    "role": window["role"],
                    "arm": arm["arm"],
                    "method": arm["method"],
                    "cell_status": "COMPLETE",
                    "integrity_pass": bool(receipt["integrity_pass"]),
                    "feature_messages": len(frames),
                    "frontend_coverage": receipt["frontend_coverage"],
                    "max_features": receipt["max_features"],
                    "action_frames": action_frames,
                    "admitted_sidecars": admitted_total,
                    "omitted_newborns": omitted_total,
                    "carried_observation_mismatches": carried_mismatches,
                    "nonbirth_omissions": nonbirth_omissions,
                    "extra_classical_observations": extra_classical,
                    "source_violations": source_violations,
                    "age_violations": age_violations,
                    "action_frame_violations": action_frame_violations,
                    "count_violations": count_violations,
                    "max_admitted_per_frame": max_admitted,
                    "published_source_counts_json": json.dumps(
                        dict(sorted(source_counts.items())), sort_keys=True
                    ),
                    "structural_pass": structural_pass,
                    "byte_identical_to_klt": byte_identical,
                    "feature_bag": str(bag_path),
                    "feature_bag_sha256": inventory["sha256"],
                }
            )
            fallback_rows.append(
                {
                    "window_id": window["window_id"],
                    "run_slug": window["run_slug"],
                    "arm": arm["arm"],
                    "admitted_sidecars": admitted_total,
                    "byte_identical_to_klt": byte_identical,
                    "eligible_exact_fallback": admitted_total == 0 and byte_identical,
                    "klt_sha256": klt_inventory["sha256"],
                    "candidate_sha256": inventory["sha256"],
                }
            )

    write_csv(PAPER / "frontend_audit.csv", frontend_rows)
    if action_rows:
        write_csv(PAPER / "action_audit.csv", action_rows)
    write_csv(PAPER / "exact_fallback.csv", fallback_rows)
    learned_rows = [row for row in frontend_rows if row["arm"] != "klt"]
    active = [row for row in learned_rows if int(row["admitted_sidecars"]) > 0]
    safety = {
        "all_18_cells_complete_and_integrity_pass": (
            len(frontend_rows) == 18
            and all(bool(row["integrity_pass"]) for row in frontend_rows)
        ),
        "all_carried_observations_exact": all(
            int(row["carried_observation_mismatches"]) == 0
            for row in learned_rows
        ),
        "only_age1_gftt_births_omitted": all(
            int(row["nonbirth_omissions"]) == 0 for row in learned_rows
        ),
        "no_extra_classical_observations": all(
            int(row["extra_classical_observations"]) == 0
            for row in learned_rows
        ),
        "actions_only_frames_0_4": all(
            int(row["action_frame_violations"]) == 0 for row in learned_rows
        ),
        "confirmed_non_loftr_sources_only": all(
            int(row["source_violations"]) == 0 for row in learned_rows
        ),
        "candidate_age_at_least_3": all(
            int(row["age_violations"]) == 0 for row in learned_rows
        ),
        "strict_count_contract_and_cap": all(
            int(row["count_violations"]) == 0
            and int(row["max_features"]) <= 350
            and int(row["max_admitted_per_frame"]) <= 6
            for row in learned_rows
        ),
        "zero_action_exact_klt": all(
            int(row["admitted_sidecars"]) > 0
            or bool(row["byte_identical_to_klt"])
            for row in learned_rows
        ),
    }
    decision = (
        "REJECT_FRONTEND"
        if not all(safety.values())
        else ("SAFE_NULL" if not active else "PENDING_MATCHED_CONTROL")
    )
    summary = {
        "schema_version": "aqua-fe-protected-prefill-slot-v1-frontend-v1",
        "experiment_id": "EXP-20260906-009",
        "cells_expected": 18,
        "cells_present": len(frontend_rows),
        "learned_arm_windows": len(learned_rows),
        "active_arm_windows": len(active),
        "active_cells": [
            f"{row['run_slug']}:{row['arm']}" for row in active
        ],
        "safety_checks": safety,
        "decision": decision,
    }
    (PAPER / "decision.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    lines = [
        "# Protected pre-refill slot v1: frontend result",
        "",
        "Experiment: `EXP-20260906-009`",
        "",
        f"Decision: `{decision}`.",
        "",
        "Outcome-known six-window development controls only; backend is Not evaluated here.",
        "",
        f"- Complete cells: {len(frontend_rows)}/18.",
        f"- Action-positive learned arm-windows: {len(active)}/12.",
        f"- Active cells: {', '.join(summary['active_cells']) or 'none'}.",
        "",
        "## Frozen frontend checks",
        "",
    ]
    lines.extend(
        f"- `{key}`: {'PASS' if value else 'FAIL'}"
        for key, value in safety.items()
    )
    lines += [
        "",
        "Candidates consume possible newborn-GFTT capacity; this is not a free or guaranteed no-harm intervention.",
        "No frontend action count is interpreted as backend success.",
    ]
    (PAPER / "export_only_report.md").write_text(
        "\n".join(lines) + "\n", encoding="utf-8"
    )
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0 if decision in {"PENDING_MATCHED_CONTROL", "SAFE_NULL"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
