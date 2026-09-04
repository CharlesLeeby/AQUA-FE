#!/usr/bin/env python3
"""Freeze P07 split identity, run allocation, and RPE analysis contracts."""

from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import re
from collections import Counter, defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BUNDLE = ROOT / "papers/ieee_sensors_journal_experiments"
P07 = BUNDLE / "p07"
MANIFEST = BUNDLE / "dataset_manifest_v4.csv"
HISTORY = BUNDLE / "history_exclusion_manifest.csv"
METHOD_LOCK = BUNDLE / "method_lock.json"
PROTOCOL = BUNDLE / "protocol_v1_nativeq_v3.md"
ARM_ORDER = BUNDLE / "arm_order.csv"
EVALUATOR = BUNDLE / "evaluator_protocol_v1.md"
FAILURE_TAXONOMY = BUNDLE / "failure_taxonomy_v1.yaml"
EXPORT_QUEUE = P07 / "frontend_export_queue_v1.csv"
D_QUEUE = P07 / "d_applicability_queue_v1.csv"
QUEUE_LOCK = P07 / "frontend_queue_lock_v1.json"
QUEUE_VALIDATION = P07 / "frontend_queue_validation_v1.json"

SPLIT_CSV = P07 / "split_role_audit_v1.csv"
SPLIT_JSON = P07 / "split_role_audit_v1.json"
ALLOCATION_CSV = P07 / "frontend_run_allocation_v1.csv"
ANALYSIS_LOCK = P07 / "preoutcome_analysis_lock_v1.json"

SCHEMA = "isj-p07-preoutcome-governance-v1"
ALLOCATION_TIME = "2026-08-06T16:45:00+08:00"
ALLOCATION_STAMP_UTC = "20260806T084500Z"
OUTCOME_BOUNDARY = "FROZEN_BEFORE_P07_FRONTEND_OR_TRAJECTORY_OUTCOME"

B1 = "B1_klt_nativeq_v3"
P_ARM = "P_legacy_nativeq_xfeat_seedchain_v3"
M_ARM = "M_xfeat_pairwise_nativeq_v1"
D_ARM = "D_legacy_exact_lineage_drop_v3"

SPLIT_FIELDS = [
    "schema_version",
    "window_id",
    "dataset_family",
    "data_domain",
    "sequence",
    "window_start_s",
    "window_end_s",
    "texture_stratum",
    "selection_tier",
    "manifest_split_role",
    "sequence_history_rows",
    "prior_learned_seen",
    "prior_vins_seen",
    "prior_parameter_use",
    "selected_interval_overlaps_history",
    "corrected_split_role",
    "external_held_out",
    "reporting_claim",
]

ALLOCATION_FIELDS = [
    "schema_version",
    "queue_index",
    "run_id",
    "allocated_at",
    "window_id",
    "dataset_family",
    "sequence",
    "window_start",
    "window_end",
    "window_unit",
    "texture_stratum",
    "selection_tier",
    "arm",
    "frontend_seed",
    "backend_replay",
    "tag",
    "command_sha256",
    "command_source",
    "expected_run_root",
    "expected_feature_bag",
    "status",
    "queue_lock_hash",
    "outcome_boundary",
]


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        fields = list(reader.fieldnames or [])
        if not fields or len(fields) != len(set(fields)):
            raise ValueError(f"invalid CSV header: {path}")
        rows = list(reader)
    if any(None in row for row in rows):
        raise ValueError(f"ragged CSV: {path}")
    return rows


def sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def file_record(path: Path) -> dict[str, object]:
    return {
        "path": path.relative_to(ROOT).as_posix(),
        "sha256": sha256(path),
        "size_bytes": path.stat().st_size,
    }


def content_record(path: Path, content: bytes) -> dict[str, object]:
    return {
        "path": path.relative_to(ROOT).as_posix(),
        "sha256": sha256_bytes(content),
        "size_bytes": len(content),
    }


def render_csv(fields: list[str], rows: list[dict[str, object]]) -> bytes:
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=fields)
    writer.writeheader()
    writer.writerows(rows)
    return stream.getvalue().encode("utf-8")


def json_bytes(payload: dict[str, object]) -> bytes:
    return (json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=True) + "\n").encode(
        "utf-8"
    )


def truth(value: str) -> bool:
    return value.strip().lower() == "true"


def selected_interval_in_history_unit(
    selected: dict[str, str], unit: str
) -> tuple[float, float]:
    start = float(selected["window_start_s"])
    end = float(selected["window_end_s"])
    if unit == "second":
        return start, end
    if unit == "frame" and selected["dataset_family"].startswith("aqualoc_"):
        return round(start * 20.0), round(end * 20.0)
    raise ValueError(
        f"unsupported history unit {unit!r} for {selected['dataset_family']}"
    )


def intervals_overlap(left: tuple[float, float], right: tuple[float, float]) -> bool:
    return max(left[0], right[0]) < min(left[1], right[1])


def build_split_rows() -> tuple[list[dict[str, object]], dict[str, object]]:
    manifest = read_csv(MANIFEST)
    history = read_csv(HISTORY)
    history_by_sequence: dict[tuple[str, str], list[dict[str, str]]] = defaultdict(list)
    for row in history:
        history_by_sequence[(row["dataset_family"], row["sequence"])].append(row)

    rows: list[dict[str, object]] = []
    for selected in sorted(manifest, key=lambda row: row["window_id"]):
        key = (selected["dataset_family"], selected["sequence"])
        prior_rows = history_by_sequence[key]
        overlaps = []
        for prior in prior_rows:
            selected_interval = selected_interval_in_history_unit(
                selected, prior["window_unit"]
            )
            prior_interval = (float(prior["start"]), float(prior["end"]))
            if intervals_overlap(selected_interval, prior_interval):
                overlaps.append(prior)
        sequence_unseen = not prior_rows
        corrected = (
            "SEQUENCE_UNSEEN_OUTCOME_BLIND_WINDOW"
            if sequence_unseen
            else "HISTORY_EXCLUDED_WINDOW_WITHIN_DEVELOPMENT_EXPOSED_SEQUENCE"
        )
        rows.append(
            {
                "schema_version": "isj-p07-split-role-audit-v1",
                "window_id": selected["window_id"],
                "dataset_family": selected["dataset_family"],
                "data_domain": selected["data_domain"],
                "sequence": selected["sequence"],
                "window_start_s": selected["window_start_s"],
                "window_end_s": selected["window_end_s"],
                "texture_stratum": selected["texture_stratum"],
                "selection_tier": selected["selection_tier"],
                "manifest_split_role": selected["split_role"],
                "sequence_history_rows": len(prior_rows),
                "prior_learned_seen": str(
                    any(truth(row["prior_learned_seen"]) for row in prior_rows)
                ).lower(),
                "prior_vins_seen": str(
                    any(truth(row["prior_vins_seen"]) for row in prior_rows)
                ).lower(),
                "prior_parameter_use": str(
                    any(truth(row["prior_parameter_use"]) for row in prior_rows)
                ).lower(),
                "selected_interval_overlaps_history": str(bool(overlaps)).lower(),
                "corrected_split_role": corrected,
                "external_held_out": "false",
                "reporting_claim": (
                    "single_sequence_unseen_normal_window"
                    if sequence_unseen
                    else "outcome_blind_exact_history_excluded_window"
                ),
            }
        )
    if len(rows) != 20:
        raise ValueError(f"expected 20 selected windows, found {len(rows)}")
    if any(row["selected_interval_overlaps_history"] == "true" for row in rows):
        raise ValueError("selected manifest overlaps an excluded history interval")
    role_counts = Counter(str(row["corrected_split_role"]) for row in rows)
    unseen_sequences = {
        (str(row["dataset_family"]), str(row["sequence"]))
        for row in rows
        if row["corrected_split_role"] == "SEQUENCE_UNSEEN_OUTCOME_BLIND_WINDOW"
    }
    summary: dict[str, object] = {
        "schema_version": "isj-p07-split-role-audit-summary-v1",
        "status": "PASS_WITH_REPORTING_IDENTITY_CORRECTION",
        "selected_windows": len(rows),
        "selected_sequences": len(
            {(str(row["dataset_family"]), str(row["sequence"])) for row in rows}
        ),
        "corrected_role_counts": dict(sorted(role_counts.items())),
        "sequence_unseen_sequences": [
            {"dataset_family": family, "sequence": sequence}
            for family, sequence in sorted(unseen_sequences)
        ],
        "sequence_unseen_low_windows": sum(
            row["texture_stratum"] == "low"
            and row["corrected_split_role"] == "SEQUENCE_UNSEEN_OUTCOME_BLIND_WINDOW"
            for row in rows
        ),
        "sequence_unseen_normal_windows": sum(
            row["texture_stratum"] == "normal"
            and row["corrected_split_role"] == "SEQUENCE_UNSEEN_OUTCOME_BLIND_WINDOW"
            for row in rows
        ),
        "external_held_out_windows": 0,
        "selected_history_overlap_count": 0,
        "manifest_split_role_disposition": (
            "PRESERVED_FROZEN_BYTES_SUPERSEDED_FOR_REPORTING_BY_THIS_AUDIT"
        ),
        "allowed_claim": (
            "outcome-blind, exact-history-excluded multi-sequence window matrix"
        ),
        "forbidden_claims": [
            "the low/degraded stratum is sequence-held-out",
            "all 15 selected sequences are sequence-held-out",
            "the current matrix contains an external-held-out domain",
            "the current matrix alone demonstrates cross-domain generalization",
        ],
        "trajectory_outcome_read": False,
        "outcome_boundary": OUTCOME_BOUNDARY,
    }
    return rows, summary


def number(value: str | float) -> str:
    parsed = float(value)
    return str(int(parsed)) if parsed.is_integer() else format(parsed, ".9g")


def slug(value: str) -> str:
    normalized = re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip("-")
    if not normalized:
        raise ValueError(f"cannot slug empty value: {value!r}")
    return normalized


def allocation_bounds(window: dict[str, str]) -> tuple[str, str, str]:
    if window["dataset_family"].startswith("aqualoc_"):
        return (
            str(round(float(window["window_start_s"]) * 20.0)),
            str(round(float(window["window_end_s"]) * 20.0)),
            "frame",
        )
    return number(window["window_start_s"]), number(window["window_end_s"]), "second"


def build_allocation_rows() -> tuple[list[dict[str, object]], str]:
    queue_lock = json.loads(QUEUE_LOCK.read_text(encoding="utf-8"))
    queue = read_csv(EXPORT_QUEUE)
    manifest = {row["window_id"]: row for row in read_csv(MANIFEST)}
    queue_lock_hash = str(queue_lock["queue_lock_hash"])
    rows: list[dict[str, object]] = []
    arm_short = {B1: "B1", P_ARM: "P", M_ARM: "M"}
    for item in queue:
        window = manifest[item["window_id"]]
        start, end, unit = allocation_bounds(window)
        short = arm_short[item["arm"]]
        run_id = (
            f"isj-nativeq-v3_P07_{slug(item['dataset_family'])}-{slug(item['sequence'])}_"
            f"{slug(start)}-{slug(end)}_{short}_f0_b00_{ALLOCATION_STAMP_UTC}"
        )
        rows.append(
            {
                "schema_version": "isj-p07-frontend-run-allocation-v1",
                "queue_index": item["queue_index"],
                "run_id": run_id,
                "allocated_at": ALLOCATION_TIME,
                "window_id": item["window_id"],
                "dataset_family": item["dataset_family"],
                "sequence": item["sequence"],
                "window_start": start,
                "window_end": end,
                "window_unit": unit,
                "texture_stratum": item["texture_stratum"],
                "selection_tier": item["selection_tier"],
                "arm": item["arm"],
                "frontend_seed": "0",
                "backend_replay": "b00",
                "tag": item["tag"],
                "command_sha256": item["command_sha256"],
                "command_source": (
                    "papers/ieee_sensors_journal_experiments/p07/"
                    f"frontend_export_queue_v1.csv#queue_index={item['queue_index']}"
                ),
                "expected_run_root": item["expected_run_root"],
                "expected_feature_bag": item["expected_feature_bag"],
                "status": "PLANNED",
                "queue_lock_hash": queue_lock_hash,
                "outcome_boundary": "FRONTEND_EXPORT_ONLY_NO_VINS_APE_RPE_TRAJECTORY",
            }
        )
    if len(rows) != 60 or len({row["run_id"] for row in rows}) != 60:
        raise ValueError("frontend allocation must contain 60 unique run IDs")
    if Counter(row["arm"] for row in rows) != {B1: 20, P_ARM: 20, M_ARM: 20}:
        raise ValueError("frontend allocation arm counts mismatch")
    return rows, queue_lock_hash


def build_analysis_lock(
    *,
    split_content: bytes,
    split_summary_content: bytes,
    allocation_content: bytes,
    split_summary: dict[str, object],
    queue_lock_hash: str,
) -> dict[str, object]:
    method = json.loads(METHOD_LOCK.read_text(encoding="utf-8"))
    return {
        "schema_version": "isj-p07-preoutcome-rpe-analysis-lock-v1",
        "status": "FROZEN_BEFORE_P07_OUTCOMES",
        "scientific_method_identity": method["scientific_method_identity"],
        "method_lock_hash": method["method_lock_hash"],
        "queue_lock_hash": queue_lock_hash,
        "outcome_boundary": OUTCOME_BOUNDARY,
        "held_out_frontend_outcome_read": False,
        "held_out_trajectory_outcome_read": False,
        "split_identity": {
            "core_matrix": (
                "outcome-blind exact-history-excluded windows; 19/20 are within "
                "development-exposed sequences"
            ),
            "sequence_unseen_windows": split_summary["sequence_unseen_normal_windows"],
            "sequence_unseen_low_windows": split_summary["sequence_unseen_low_windows"],
            "external_held_out_windows": 0,
            "submission_ceiling_without_new_protocol_supplement": (
                "CONDITIONAL_MULTI_SEQUENCE_VINS_PRIMARY"
            ),
        },
        "arms": {
            "required": [
                "B0_native_vins_origin_v1",
                B1,
                P_ARM,
                M_ARM,
            ],
            "conditional": [D_ARM],
            "retired_no_slots": [
                "C_legacy_independent_classical_v3",
                "B2_all_eligible",
            ],
        },
        "execution": {
            "phase_order": [
                "allocate_registry_and_pending_D_slots",
                "complete_and_attest_all_60_frontend_exports",
                "resolve_all_20_D_slots_before_any_trajectory_metric",
                "derive_and_exact-drop-audit_every_applicable_D_bag",
                "freeze_backend_queue_in_Williams_arm_order",
                "run_all_backend_replays_serially",
                "evaluate_without_changing_method_window_or_evaluator",
            ],
            "base_backend_replays": 240,
            "conditional_D_replays_per_applicable_window": 3,
            "maximum_backend_replays": 300,
            "algorithmic_replays_per_window_arm": 3,
            "minimum_evaluable_replays": 2,
            "numeric_reducer": "median_over_evaluable_replays",
            "scientific_unit": "sequence_not_replay",
            "one_ros_vins_instance_at_a_time": True,
            "parent_P_failure_D_resolution": "UNRESOLVABLE_PARENT_FAILURE_AND_D_BLOCKED",
        },
        "metrics": {
            "primary": "G0_common_support_exact_1s_translation_RPE_RMSE",
            "secondary": "G0_common_support_SE3_APE_RMSE_only_when_APE_valid",
            "support": {
                "rpe_minimum_exact_pairs": 10,
                "ape_minimum_common_grid_poses": 30,
                "ape_minimum_span_s": 10,
                "ape_minimum_common_coverage": 0.70,
            },
            "lower_is_better": True,
        },
        "reducer_and_inference": {
            "window_arm_numeric": "median_of_at_least_2_of_3_evaluable_replays",
            "window_effect": "log(RPE_proposed/RPE_comparator)",
            "sequence_effect": "median_window_effect_within_sequence",
            "overall_effect": "equal_weight_median_over_sequences",
            "bootstrap": {
                "type": "hierarchical_percentile_sequence_then_window",
                "iterations": 10000,
                "seed": 20260730,
                "confidence": 0.95,
            },
            "small_sample_test": "exact_two_sided_sign_test_on_sequence_effects",
            "replays_are_not_independent_samples": True,
        },
        "hypotheses": {
            "H1_low_degraded_P_vs_B1": {
                "role": "sole_primary_effectiveness_contrast",
                "denominator": "all_10_preregistered_low_or_degraded_windows",
                "practical_gate": "sequence_equal_median_RPE_improvement_at_least_5_percent",
                "adequacy": {
                    "minimum_numeric_windows": 8,
                    "minimum_sequences": 6,
                },
                "inference_gate": "bootstrap_CI_lower_gt_0_or_exact_sign_p_lt_0p05",
                "safety_gate": "zero_proposed_only_window_arm_hard_failures",
            },
            "H2_source_specificity": {
                "status": "NOT_APPLICABLE_CARRIER_FEEDBACK",
                "reason": "C_legacy is non-identifiable under frozen native-q v3",
            },
            "H3_direct_backend_exposure_P_vs_D": {
                "role": "conditional_mechanistic_contrast_not_complete_frontend_removal",
                "practical_gate": "sequence_equal_median_RPE_improvement_at_least_3_percent",
                "adequacy": {
                    "minimum_low_windows": 6,
                    "minimum_sequences": 3,
                    "minimum_domains": 2,
                },
                "required": "PASS_EXACT_WHOLE_LINEAGE_DROP_for_every_included_window",
            },
            "H4a_overall_normal_no_harm_P_vs_B1": {
                "denominator": "all_10_preregistered_normal_windows",
                "window_gate": "at_least_9_of_10_have_RPE_degradation_at_most_5_percent",
                "sequence_gate": "at_least_80_percent_have_sequence_RPE_ratio_at_most_1p05",
                "coverage_gate": "sequence_median_coverage_loss_at_most_2_percentage_points",
                "failure_gate": "zero_proposed_only_window_arm_hard_failures",
                "solver_gate": "proposed_solver_risk_event_rate_does_not_increase",
            },
            "H4b_active_normal_no_harm": {
                "activity_gate": "at_least_3_active_normal_windows_across_at_least_2_sequences",
                "otherwise": "INCONCLUSIVE_ACTIVITY",
                "window_gate": "every_active_normal_window_RPE_degradation_at_most_5_percent",
            },
            "M_controlled_modern_baseline": {
                "status_rule": "PASS_means_complete_fair_comparison_not_P_superiority",
                "report": "P_vs_M_effect_failure_coverage_and_runtime_without_win_requirement",
            },
        },
        "failure_denominator": {
            "all_preregistered_windows_remain": True,
            "proposed_only_hard_failure": "automatic_proposed_loss",
            "B1_only_hard_failure": "proposed_failure_win",
            "both_hard_failure": "failure_tie",
            "insufficient_common_support": "INCONCLUSIVE_PAIR_retained_in_denominator",
            "solver_risk": "any_of_3",
            "any_repeat_hard_failure": "any_of_3",
        },
        "mandatory_strata": {
            "ABSOLUTE_LOW": 3,
            "RELATIVE_Q80_FALLBACK": 7,
            "STRICT_NORMAL": 10,
        },
        "claim_boundary": {
            "allowed": [
                "outcome-blind exact-history-excluded multi-sequence window evaluation",
                "VINS-primary controlled comparison under a frozen native-q consumer",
                "operational normal-texture no-harm only if H4a passes",
            ],
            "forbidden": [
                "external-held-out or cross-domain validation from the current matrix",
                "sequence-held-out low-texture validation from the current matrix",
                "learned features are uniformly superior",
                "D removes the complete learned frontend",
                "real-time without P08 PROFILED_REAL_TIME evidence",
            ],
        },
        "artifacts": [
            file_record(path)
            for path in (
                METHOD_LOCK,
                PROTOCOL,
                MANIFEST,
                ARM_ORDER,
                EVALUATOR,
                FAILURE_TAXONOMY,
                EXPORT_QUEUE,
                D_QUEUE,
                QUEUE_LOCK,
                QUEUE_VALIDATION,
                ROOT / "scripts/build_p07_preoutcome_governance_v1.py",
            )
        ]
        + [
            content_record(SPLIT_CSV, split_content),
            content_record(SPLIT_JSON, split_summary_content),
            content_record(ALLOCATION_CSV, allocation_content),
        ],
    }


def build_outputs() -> dict[Path, bytes]:
    split_rows, split_summary = build_split_rows()
    allocations, queue_lock_hash = build_allocation_rows()
    split_content = render_csv(SPLIT_FIELDS, split_rows)
    split_summary["split_csv"] = content_record(SPLIT_CSV, split_content)
    split_summary["source_manifest"] = file_record(MANIFEST)
    split_summary["source_history"] = file_record(HISTORY)
    split_summary_content = json_bytes(split_summary)
    allocation_content = render_csv(ALLOCATION_FIELDS, allocations)
    analysis = build_analysis_lock(
        split_content=split_content,
        split_summary_content=split_summary_content,
        allocation_content=allocation_content,
        split_summary=split_summary,
        queue_lock_hash=queue_lock_hash,
    )
    return {
        SPLIT_CSV: split_content,
        SPLIT_JSON: split_summary_content,
        ALLOCATION_CSV: allocation_content,
        ANALYSIS_LOCK: json_bytes(analysis),
    }


def write_outputs() -> None:
    outputs = build_outputs()
    existing = [str(path) for path in outputs if path.exists()]
    if existing:
        raise FileExistsError(f"refusing to overwrite preoutcome artifacts: {existing}")
    temporary = {
        path: path.with_name(f"{path.name}.partial.{os.getpid()}") for path in outputs
    }
    for path, content in outputs.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary[path].write_bytes(content)
    for path in outputs:
        os.replace(temporary[path], path)
    print(
        "P07_PREOUTCOME_GOVERNANCE_FROZEN "
        "windows=20 sequence_unseen=1 allocations=60 primary=RPE"
    )


if __name__ == "__main__":
    write_outputs()
