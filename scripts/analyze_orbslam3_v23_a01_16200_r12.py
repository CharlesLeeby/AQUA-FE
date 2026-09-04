#!/usr/bin/env python3
"""Build the R12 evidence bundle for AQUALOC A01 16200-17100.

The default mode is deliberately fail-closed: it only emits a bundle after the
entire five-role by four-repeat formal grid, both evaluations, deterministic
action/trajectory checks, provenance snapshots, the discovery smoke, and the
frontend exact-drop contract all validate.  ``--preflight`` checks only the
already-frozen frontend/source and smoke artifacts and never reads formal
outcomes.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import shutil
import tempfile
from collections import Counter
from pathlib import Path
from typing import Any

import analyze_orbslam3_v23_a01_r09 as r09
import analyze_orbslam3_v23_afrl_cemetery_fr_r11 as r11
import analyze_orbslam3_v23_continued_search_r08 as r08


WORKSPACE = Path("/home/ma/AQUA-FE_WS")
DATA_ROOT = Path("/mnt/data/AQUA-FE_WS")
DEFAULT_OUTPUT = (
    WORKSPACE / "papers/orb_v23_a01_16200_r12_20260808/analysis-output"
)
PRIOR_ROSTER = (
    WORKSPACE
    / "papers/orb_v23_afrl_cemetery_fr_r11_20260807/analysis-output/"
    "window_roster.csv"
)
REPORT_RELATIVE = (
    "papers/orb_v23_a01_16200_r12_20260808/analysis-output/analysis-report.md"
)
FORMAL_SUFFIX = (
    "formal_n3_d14_min8_ignore0_clean_v23_lineagefirst_lateenforce_"
    "dualgateack_equalruntime_singlecpu2_noaslr_fivearm_h100_q09"
)
SMOKE_SUFFIX = (
    "smoke_n3_d14_min8_ignore0_clean_v23_lineagefirst_lateenforce_"
    "dualgateack_equalruntime_singlecpu2_noaslr_threearm_h100_q09"
)
FORMAL_ROLE_ORDER = "orb_only drop full_bridge_off full_unbounded full"

KLT_FEATURES_SHA256 = (
    "fee3985a7a3a9e960e71d26b825582756633c431fa849414ebe995818f12879b"
)
SIDECAR_SHA256 = (
    "b719f001e5e5ea9c229b5504a97449d682fe9bf96fea6c0e976d8215186ba888"
)
FULL_MERGED_SHA256 = (
    "b7dfb376d0cba0f658a2a6664a414c39df2e3c20c3b73407e6cf859cbc12864f"
)
FULL_SEEDS_SHA256 = (
    "bb1c301fe3b17b4be0961fd2e7c6849282743843d9d2027bc9120bb640be7fc9"
)
DROP_SEEDS_SHA256 = (
    "4d77d35c290b73157b0db402c185f1750e64409418f1d79d3e2de06b94daa919"
)
FEATURE_TIMES_SHA256 = (
    "abd199725fdf587fdf4ab2c95562cca38fdd5880063cfbb27ff90136e89a49bb"
)
EXACT_DROP_AUDIT_SHA256 = (
    "27e086f27d740ac255d2fd5f91fba909cbfd8f777b268f68d01884dcdb78c038"
)
KLT_CAMERA_SHA256 = (
    "045505013a5dbfb629bad8d3463bbbdacad965ebdcf3c590598121bd884e50a5"
)
ORB_CAMERA_SHA256 = (
    "d4434cedb15c5861887a80f4d2527ddd2d924e74a4e3c424c028137a0f1ee8e9"
)
FROZEN_SIDECAR_SOURCE_SHA256 = (
    "9afc6f7083f76bf1f7c6b7c19f79f02a98160663c945479b51492fa19cb3ace7"
)
EXACT_DROP_AUDITOR_SHA256 = (
    "bf6ccbf47d3b6b1e4fdad8b9e8b49d17f9545b312ce64970b61ed6c56cdf71b4"
)
RUNNER_SHA256 = (
    "6ffedc001ae51b6b80a391c4dad3a6cbd917037968a1e94e582f98e78a4c4c77"
)
ORB_BINARY_SHA256 = (
    "cebeeedb862a469f9b4928fc0712fd0fd93766d4a4b5faa09e7de5a0f19083fc"
)
ORB_LIBRARY_SHA256 = (
    "05a7b3cc8aa7aaefec38ce995de9fbf808662c051f1ce1f0f35925f2e6093af8"
)


def data(path: str) -> Path:
    return DATA_ROOT / path


KLT_ROOT = data(
    "logs/aqualoc_archaeo_vins/"
    "external_klt_every2_isj_p07_aqualoc_archaeology_a01_0018_b1_attempt01"
)
CLEAN_ROOT = data(
    "online_positive_search_20260808/aqualoc_a01_16200_17100/"
    "clean_ignore0_frozen_20260808"
)
SELECTOR_ROOT = data(
    "orbslam3_seeded_validation/multilineage/aqualoc_a01_16200_17100/"
    "n3_d14_min8_ignore0_clean_20260808"
)
SEARCH_ROOT = data(
    "orbslam3_seeded_validation/postinit_candidate_search_20260808/"
    "aqualoc_a01_16200_17100"
)
SEED_ROOT = SEARCH_ROOT / "assets_n3_d14_min8_ignore0_clean"
SMOKE_ROOT = SEARCH_ROOT / SMOKE_SUFFIX
FORMAL_ROOT = SEARCH_ROOT / FORMAL_SUFFIX
EXACT_DROP_PATH = SEARCH_ROOT / "audit_exact_drop/selector_whole_lineage_audit.json"
DATASET_ROOT = data(
    "orbslam3_validation/aqualoc_a01_16200_17100_clean_20260808/dataset"
)
ORB_ROOT = Path(
    "/home/ma/SLAM/orb_slam3_lineage_ws/src/ORB_SLAM3-lineage"
)
ORB_BINARY = ORB_ROOT / "Examples_old/Monocular/mono_euroc_old"
ORB_LIBRARY = ORB_ROOT / "lib/libORB_SLAM3.so"

CONFIG: dict[str, Any] = {
    "window_id": "A01_16200_17100",
    "dataset": "AQUALOC",
    "sequence": "A01",
    "window": "16200-17100",
    # Replaced only after the complete formal grid determines the classification.
    "level": "pending_complete_formal_classification",
    "selector_name": "n3_d14_min8_ignore0_clean",
    "texture_profile": "operational degraded/low-grid",
    "base_klt_profile": "350 saturated; frozen gate grid mean 0.597654",
    "operational_low_texture": True,
    "sparse_base_klt_low_texture": False,
    "formal_root": FORMAL_ROOT,
    "smoke_root": SMOKE_ROOT,
    "exact_drop": EXACT_DROP_PATH,
    "clean_root": CLEAN_ROOT,
    "stats": CLEAN_ROOT / "stats.csv",
    "selector_root": SELECTOR_ROOT,
    "seed_root": SEED_ROOT,
    "dataset_root": DATASET_ROOT,
    "raw_bag": data("datasets/aqualoc/rosbags/archaeo01_16200_17100.bag"),
    "fresh_klt_bag": KLT_ROOT / "features.bag",
    "camera_config": KLT_ROOT / "aqualoc_archaeo01_pinhole.yaml",
    "orb_config": WORKSPACE / "logs/orbslam3_validation/aqualoc_archaeo_mono.yaml",
    "rpe_delta": 1,
    "rpe_label": "1-associated-pose",
    "association_s": 0.06,
}

PRIOR_COUNTS = {
    "action_positive": 18,
    "project_strict": 6,
    "all_control_strict": 3,
    "operational_low_grid": 11,
    "strict_operational_low_grid": 4,
    "sparse_base_klt": 0,
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Validate and package the AQUALOC A01 16200-17100 ORB-v23 R12 "
            "evidence bundle."
        )
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--replace", action="store_true")
    parser.add_argument(
        "--preflight",
        action="store_true",
        help=(
            "validate only frozen source, exact-drop, prior-roster, and completed "
            "smoke contracts; do not inspect formal outcomes or write a bundle"
        ),
    )
    return parser.parse_args()


def one_csv_row(path: Path) -> dict[str, str]:
    rows = r08.read_csv(path)
    if len(rows) != 1:
        raise RuntimeError(f"expected one CSV row in {path}, got {len(rows)}")
    return rows[0]


def require_sha(path: Path, expected: str, label: str) -> None:
    observed = r08.sha256(path)
    if observed != expected:
        raise RuntimeError(f"{label} SHA-256 mismatch: {observed}")


def action_record(run: Path, summary: dict[str, Any]) -> dict[str, int]:
    lineages = r08.read_csv(run / "instrumentation/seed_lineages.csv")
    return {
        "loaded": int(summary["loaded_seed_observations"]),
        "attempted": int(summary["attempted_seed_observations"]),
        "accepted": int(summary["accepted_seed_observations"]),
        "pre_init_attempted": sum(
            int(row["pre_init_attempted"]) for row in lineages
        ),
        "post_init_attempted": sum(
            int(row["post_init_attempted"]) for row in lineages
        ),
        "post_init_accepted": sum(
            int(row["post_init_accepted"]) for row in lineages
        ),
        "mappoint_lineages": int(summary["seed_lineages_with_mappoint"]),
        "distinct_mappoints": int(summary["distinct_mappoints"]),
        "matches": int(summary["lineage_assisted_matches_consumed"]),
        "outliers": int(summary["lineage_assisted_outliers_observed"]),
        "pre_kf_observed": int(
            summary["lineage_pre_kf_assisted_outliers_observed"]
        ),
        "pre_kf_purged": int(
            summary["lineage_pre_kf_assisted_outliers_purged"]
        ),
        "scans": int(summary["lineage_pre_kf_outlier_purge_scans"]),
    }


def action_signature(action: dict[str, int]) -> tuple[int, ...]:
    fields = (
        "loaded",
        "attempted",
        "accepted",
        "pre_init_attempted",
        "post_init_attempted",
        "post_init_accepted",
        "mappoint_lineages",
        "distinct_mappoints",
        "matches",
        "outliers",
        "pre_kf_observed",
        "pre_kf_purged",
        "scans",
    )
    return tuple(action[field] for field in fields)


def require_action_positive(action: dict[str, int], label: str) -> None:
    if action["pre_init_attempted"] != 0:
        raise RuntimeError(f"{label} is mixed/pre-init: {action}")
    if action["post_init_attempted"] != action["attempted"]:
        raise RuntimeError(f"{label} phase accounting mismatch: {action}")
    if action["post_init_accepted"] != action["accepted"]:
        raise RuntimeError(f"{label} acceptance accounting mismatch: {action}")
    required_positive = (
        "mappoint_lineages",
        "distinct_mappoints",
        "matches",
        "outliers",
        "pre_kf_observed",
        "pre_kf_purged",
    )
    missing = [field for field in required_positive if action[field] <= 0]
    if missing:
        raise RuntimeError(f"{label} does not close the action chain {missing}: {action}")
    if action["pre_kf_purged"] > action["pre_kf_observed"]:
        raise RuntimeError(f"{label} purge accounting mismatch: {action}")


def audit_smoke_contract() -> dict[str, Any]:
    expected = {
        "orb_only": (0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0),
        "drop": (0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0),
        "full": (153, 153, 150, 0, 153, 150, 2, 8, 103, 8, 6, 6, 288),
    }
    actions: dict[str, dict[str, int]] = {}
    snapshot_entries = 0
    snapshot_counts: Counter[int] = Counter()
    for role in ("orb_only", "drop", "full"):
        run = SMOKE_ROOT / f"{role}_r1"
        manifest = r08.parse_manifest(run / "run_manifest.txt")
        if manifest.get("role_order") != "orb_only drop full":
            raise RuntimeError(f"wrong smoke role order: {run}")
        summary = json.loads(
            (run / "instrumentation/seed_summary.json").read_text(
                encoding="utf-8"
            )
        )
        if summary.get("complete") is not True or summary.get("status") != "ok":
            raise RuntimeError(f"incomplete smoke audit: {run}")
        action = action_record(run, summary)
        if action_signature(action) != expected[role]:
            raise RuntimeError(f"unexpected smoke action for {role}: {action}")
        actions[role] = action
        count = r08.verify_snapshot(run / "provenance/snapshot_sha256.txt")
        snapshot_entries += count
        snapshot_counts[count] += 1
    if snapshot_entries != 86 or snapshot_counts != Counter({29: 2, 28: 1}):
        raise RuntimeError(
            f"unexpected smoke snapshot contract: {snapshot_entries}, {snapshot_counts}"
        )
    require_action_positive(actions["full"], "discovery smoke full")
    return {
        "runs": 3,
        "runs_ok": 3,
        "snapshot_manifests": 3,
        "snapshot_manifests_verified": 3,
        "snapshot_entries": snapshot_entries,
        "snapshot_entries_verified": snapshot_entries,
        "actions": actions,
        "root": str(SMOKE_ROOT),
    }


def audit_exact_drop_contract() -> dict[str, Any]:
    require_sha(EXACT_DROP_PATH, EXACT_DROP_AUDIT_SHA256, "exact-drop audit")
    audit = json.loads(EXACT_DROP_PATH.read_text(encoding="utf-8"))
    if audit.get("schema_version") != "aqua-fe-whole-lineage-exact-drop-audit-v1":
        raise RuntimeError("unexpected exact-drop audit schema")
    if audit.get("contract_pass") is not True:
        raise RuntimeError("exact-drop audit did not pass")
    if audit.get("decision") != "PASS_EXACT_WHOLE_LINEAGE_DROP":
        raise RuntimeError(f"unexpected exact-drop decision: {audit.get('decision')}")
    if audit.get("forbidden_outcomes_accessed") != []:
        raise RuntimeError("exact-drop audit crossed the outcome boundary")
    if audit.get("outcome_boundary") != "FRONTEND_BAG_ONLY_NO_VINS_APE_RPE_TRAJECTORY":
        raise RuntimeError("unexpected exact-drop outcome boundary")

    checks = audit["checks"]
    required_true = (
        "drop_feature_payload_equals_filtered_proposed_payload_byte_for_byte",
        "feature_header_and_record_timestamps_exact",
        "learned_births_and_all_lineage_continuations_absent_from_drop",
        "message_count_order_topic_type_md5_record_timestamp_exact",
        "non_dropped_observation_order_fields_channels_exact",
        "nonfeature_serialized_bytes_exact",
    )
    if any(checks.get(key) is not True for key in required_true):
        raise RuntimeError(f"exact-drop payload check failed: {checks}")
    # This selector audit intentionally has no separate producer-stats input.
    if checks.get("producer_stats_contract_exact") is not False:
        raise RuntimeError(f"unexpected selector producer-stats flag: {checks}")
    if audit.get("producer_stats") is not None:
        raise RuntimeError("selector exact-drop audit unexpectedly has producer stats")

    inputs = audit["inputs"]
    if inputs.get("drop_bag_sha256") != KLT_FEATURES_SHA256:
        raise RuntimeError("exact-drop control hash mismatch")
    if inputs.get("proposed_bag_sha256") != FULL_MERGED_SHA256:
        raise RuntimeError("exact-drop proposed hash mismatch")
    expected_summary = {
        "drop_observations": 157500,
        "dropped_observations": 153,
        "feature_frames": 450,
        "frames_with_drops": 78,
        "klt_source_code_1_continuation_observations": 0,
        "learned_birth_observations": 3,
        "learned_lineages": 3,
        "learned_marked_observations": 153,
        "nonfeature_messages": 9139,
        "proposed_observations": 157653,
        "total_messages": 9589,
        "unmarked_continuation_observations": 0,
    }
    if audit.get("summary") != expected_summary:
        raise RuntimeError(f"exact-drop summary mismatch: {audit.get('summary')}")
    return {
        "contract_pass": True,
        "decision": audit["decision"],
        "audit_sha256": EXACT_DROP_AUDIT_SHA256,
        "summary": audit["summary"],
        "path": str(EXACT_DROP_PATH),
    }


def audit_source_contract() -> dict[str, Any]:
    base = one_csv_row(CLEAN_ROOT / "base_drop_stats.csv")
    expected_base = {
        "feature_frames": "450",
        "frames_with_drops": "0",
        "dropped_observations": "0",
        "kept_learned_observations": "0",
        "learned_track_ids": "0",
        "kept_observations": "157500",
        "drop_learned": "0",
        "drop_learned_track_lineage": "1",
        "learned_id_min": "10000000",
    }
    for key, expected in expected_base.items():
        if base.get(key) != expected:
            raise RuntimeError(f"clean base contract mismatch: {key}={base.get(key)}")

    selector = r08.parse_manifest(SELECTOR_ROOT / "manifest.txt")
    expected_selector = {
        "max_lineages": "3",
        "min_distance_px": "14",
        "ignore_zero_base_speeds": "0",
        "min_observations": "8",
        "rearm_absent_frames": "0",
        "drop_bag_sha256": KLT_FEATURES_SHA256,
        "full_bag_sha256": FULL_MERGED_SHA256,
    }
    for key, expected in expected_selector.items():
        if selector.get(key) != expected:
            raise RuntimeError(f"selector contract mismatch: {key}={selector.get(key)}")

    sidecar_stats = r08.read_csv(CLEAN_ROOT / "stats.csv")
    triggers = [row for row in sidecar_stats if row["triggered"] == "1"]
    trigger_frames = [int(row["frame_index"]) for row in triggers]
    trigger_added = [int(row["added_seeds"]) for row in triggers]
    if len(sidecar_stats) != 450 or trigger_frames != [157, 169, 181]:
        raise RuntimeError(
            f"sidecar trigger contract mismatch: {len(sidecar_stats)}, {trigger_frames}"
        )
    if trigger_added != [50, 46, 34]:
        raise RuntimeError(f"sidecar trigger dose mismatch: {trigger_added}")

    seed_export = json.loads(
        (SEED_ROOT / "seed_export_stats.json").read_text(encoding="utf-8")
    )
    expected_seed_export = {
        "source_messages": 450,
        "mapped_feature_frames": 450,
        "seed_ids": 3,
        "seed_frames": 78,
        "seed_observations": 153,
        "max_timestamp_difference_ns": 0,
        "rejected_nonfinite": 0,
        "rejected_out_of_bounds": 0,
        "rejected_by_stride": 0,
        "rejected_by_lineage_maturity": 0,
        "source_code": 20,
    }
    for key, expected in expected_seed_export.items():
        if seed_export.get(key) != expected:
            raise RuntimeError(f"seed export contract mismatch: {key}={seed_export.get(key)}")

    seed_rows = [
        line.split()
        for line in (SEED_ROOT / "full_seeds.txt")
        .read_text(encoding="ascii")
        .splitlines()
        if line and not line.startswith("#")
    ]
    if len(seed_rows) != 153 or len({int(row[3]) for row in seed_rows}) != 3:
        raise RuntimeError("full seed row/lineage count mismatch")
    seed_qualities = [float(row[4]) for row in seed_rows]
    if any(not math.isfinite(value) or value < 0.9 for value in seed_qualities):
        raise RuntimeError("full seeds violate the frozen finite q>=0.9 gate")

    metadata = json.loads(
        (DATASET_ROOT / "export_metadata.json").read_text(encoding="utf-8")
    )
    expected_metadata = {
        "requested_image_count": 450,
        "kept_images": 450,
        "image_width": 968,
        "image_height": 608,
        "imu_count": 9093,
        "gt_count": 46,
        "skipped_duplicate_gt": 0,
        "skipped_duplicate_images": 0,
        "skipped_duplicate_imu": 0,
        "skipped_images_before_imu": 0,
        "source_image_encoding": "mono8",
    }
    for key, expected in expected_metadata.items():
        if metadata.get(key) != expected:
            raise RuntimeError(f"dataset export mismatch: {key}={metadata.get(key)}")

    require_sha(KLT_ROOT / "features.bag", KLT_FEATURES_SHA256, "fresh KLT bag")
    require_sha(CLEAN_ROOT / "base_drop.bag", KLT_FEATURES_SHA256, "clean base")
    require_sha(CLEAN_ROOT / "sidecar.bag", SIDECAR_SHA256, "sidecar")
    require_sha(
        SELECTOR_ROOT / "drop_whole_lineage.bag",
        KLT_FEATURES_SHA256,
        "selector drop bag",
    )
    require_sha(
        SELECTOR_ROOT / "full_merged.bag", FULL_MERGED_SHA256, "selector full bag"
    )
    require_sha(SEED_ROOT / "full_seeds.txt", FULL_SEEDS_SHA256, "full seeds")
    require_sha(SEED_ROOT / "drop_seeds.txt", DROP_SEEDS_SHA256, "drop seeds")
    require_sha(SEED_ROOT / "feature_times.txt", FEATURE_TIMES_SHA256, "feature times")
    require_sha(DATASET_ROOT / "cam0_times.txt", FEATURE_TIMES_SHA256, "dataset times")
    require_sha(CONFIG["camera_config"], KLT_CAMERA_SHA256, "KLT camera")
    require_sha(CONFIG["orb_config"], ORB_CAMERA_SHA256, "ORB camera")
    require_sha(
        CLEAN_ROOT / "provenance/xfeat_seed_sidecar_node_9afc.py",
        FROZEN_SIDECAR_SOURCE_SHA256,
        "frozen sidecar source",
    )
    require_sha(
        WORKSPACE / "scripts/audit_whole_lineage_exact_drop_v1.py",
        EXACT_DROP_AUDITOR_SHA256,
        "exact-drop auditor",
    )
    require_sha(
        WORKSPACE / "scripts/run_orbslam3_seeded_triplet.sh",
        RUNNER_SHA256,
        "frozen ORB runner",
    )
    require_sha(ORB_BINARY, ORB_BINARY_SHA256, "frozen ORB binary")
    require_sha(ORB_LIBRARY, ORB_LIBRARY_SHA256, "frozen ORB library")

    fresh_bag = r11.audit_feature_bag(
        KLT_ROOT / "features.bag", "/feature_tracker/feature", 968, 608
    )
    expected_fresh_bag = {
        "frames": 450,
        "observations": 157500,
        "unique_ids": 5803,
        "high_id_observations": 0,
        "source_codes": {1: 153309, 2: 4191},
        "learned_codes": {0: 157500},
        "out_of_bounds": 0,
    }
    if fresh_bag != expected_fresh_bag:
        raise RuntimeError(f"fresh KLT bag audit mismatch: {fresh_bag}")

    sidecar_bag = r11.audit_feature_bag(
        CLEAN_ROOT / "sidecar.bag", "/feature_tracker/sidecar", 968, 608
    )
    expected_sidecar_bag = {
        "frames": 450,
        "observations": 4042,
        "unique_ids": 130,
        "high_id_observations": 0,
        "source_codes": {20: 4042},
        "learned_codes": {1: 4042},
        "out_of_bounds": 0,
    }
    if sidecar_bag != expected_sidecar_bag:
        raise RuntimeError(f"sidecar bag audit mismatch: {sidecar_bag}")

    drop_bag = r11.audit_feature_bag(
        SELECTOR_ROOT / "drop_whole_lineage.bag",
        "/feature_tracker/feature",
        968,
        608,
    )
    if drop_bag != expected_fresh_bag:
        raise RuntimeError(f"selected drop bag audit mismatch: {drop_bag}")

    full_bag = r11.audit_feature_bag(
        SELECTOR_ROOT / "full_merged.bag",
        "/feature_tracker/feature",
        968,
        608,
    )
    expected_full_bag = {
        "frames": 450,
        "observations": 157653,
        "unique_ids": 5806,
        "high_id_observations": 153,
        "source_codes": {1: 153309, 2: 4191, 20: 153},
        "learned_codes": {0: 157500, 1: 153},
        "out_of_bounds": 0,
    }
    if full_bag != expected_full_bag:
        raise RuntimeError(f"selected full bag audit mismatch: {full_bag}")

    exact_drop = audit_exact_drop_contract()
    return {
        "fresh_klt_frames": int(base["feature_frames"]),
        "fresh_klt_observations": int(base["kept_observations"]),
        "learned_observations_removed_from_base": int(base["dropped_observations"]),
        "sidecar_frames": len(sidecar_stats),
        "sidecar_triggers": len(triggers),
        "sidecar_trigger_frames": trigger_frames,
        "sidecar_candidates": sum(trigger_added),
        "seed_ids": seed_export["seed_ids"],
        "seed_frames": seed_export["seed_frames"],
        "seed_observations": seed_export["seed_observations"],
        "seed_quality_min": min(seed_qualities),
        "seed_quality_max": max(seed_qualities),
        "seed_quality_below_0p9": sum(value < 0.9 for value in seed_qualities),
        "seed_max_timestamp_difference_ns": seed_export[
            "max_timestamp_difference_ns"
        ],
        "image_count": metadata["kept_images"],
        "image_width": metadata["image_width"],
        "image_height": metadata["image_height"],
        "imu_count": metadata["imu_count"],
        "gt_count": metadata["gt_count"],
        "klt_features_sha256": KLT_FEATURES_SHA256,
        "sidecar_sha256": SIDECAR_SHA256,
        "full_bag_sha256": FULL_MERGED_SHA256,
        "full_seeds_sha256": FULL_SEEDS_SHA256,
        "feature_times_sha256": FEATURE_TIMES_SHA256,
        "fresh_bag_audit": fresh_bag,
        "sidecar_bag_audit": sidecar_bag,
        "selected_drop_bag_audit": drop_bag,
        "selected_full_bag_audit": full_bag,
        "exact_drop": exact_drop,
    }


def audit_formal_action(
    result: dict[str, Any], seed_observations: int
) -> dict[str, Any]:
    signatures: dict[str, set[tuple[int, ...]]] = {
        role: set() for role in r08.ROLES
    }
    actions_by_repeat: dict[str, dict[str, dict[str, int]]] = {}
    for repeat in r08.REPEATS:
        repeat_actions: dict[str, dict[str, int]] = {}
        for role in r08.ROLES:
            run = FORMAL_ROOT / f"{role}_r{repeat}"
            summary = json.loads(
                (run / "instrumentation/seed_summary.json").read_text(
                    encoding="utf-8"
                )
            )
            action = action_record(run, summary)
            signatures[role].add(action_signature(action))
            repeat_actions[role] = action
            expected_loaded = 0 if role in {"orb_only", "drop"} else seed_observations
            if action["loaded"] != expected_loaded:
                raise RuntimeError(
                    f"formal {role} r{repeat} loaded {action['loaded']}, "
                    f"expected {expected_loaded}"
                )
            if action["attempted"] > 0:
                if action["pre_init_attempted"] != 0:
                    raise RuntimeError(
                        f"formal {role} r{repeat} contains pre-init attempts: {action}"
                    )
                if action["post_init_attempted"] != action["attempted"]:
                    raise RuntimeError(
                        f"formal {role} r{repeat} phase mismatch: {action}"
                    )
                if action["post_init_accepted"] != action["accepted"]:
                    raise RuntimeError(
                        f"formal {role} r{repeat} acceptance mismatch: {action}"
                    )
        actions_by_repeat[str(repeat)] = repeat_actions

    observed_signature_counts = {
        role: len(items) for role, items in signatures.items()
    }
    if any(count != 1 for count in observed_signature_counts.values()):
        raise RuntimeError(
            f"formal lineage-phase/action nondeterminism: {observed_signature_counts}"
        )
    full = actions_by_repeat["1"]["full"]
    require_action_positive(full, "formal full")
    core_full = result["action"]["full"]
    shared_fields = (
        "attempted",
        "accepted",
        "pre_init_attempted",
        "post_init_attempted",
        "post_init_accepted",
        "mappoint_lineages",
        "distinct_mappoints",
        "matches",
        "outliers",
        "pre_kf_observed",
        "pre_kf_purged",
        "scans",
    )
    if any(full[field] != core_full[field] for field in shared_fields):
        raise RuntimeError("formal action helper disagrees with core evaluator")
    return {
        "action_positive": True,
        "pure_post_init": True,
        "role_action_signatures": observed_signature_counts,
        "actions_by_repeat": actions_by_repeat,
    }


def evaluate_formal_window(config: dict[str, Any]) -> dict[str, Any]:
    """Run the shared evaluator under this R12 grid's frozen uniform order.

    The older R08 helper encodes a swapped R4 order for an earlier experiment.
    This window instead freezes the same five-role order for R1-R4.  Validate all
    20 manifests locally, then scope the helper's order table to this contract
    for the duration of the call; restore it even if validation fails.
    """
    expected_orders = {
        repeat: FORMAL_ROLE_ORDER for repeat in r08.REPEATS
    }
    for repeat in r08.REPEATS:
        for role in r08.ROLES:
            run = FORMAL_ROOT / f"{role}_r{repeat}"
            observed = r08.parse_manifest(run / "run_manifest.txt").get(
                "role_order"
            )
            if observed != FORMAL_ROLE_ORDER:
                raise RuntimeError(
                    f"wrong R12 formal role order: {run}: {observed!r}"
                )

    prior_orders = r08.EXPECTED_ORDERS
    try:
        r08.EXPECTED_ORDERS = expected_orders
        return r08.evaluate_window(config)
    finally:
        r08.EXPECTED_ORDERS = prior_orders


def classify_trajectory(result: dict[str, Any]) -> dict[str, Any]:
    improvement_counts = {
        control: sum(value > 0 for value in changes.values())
        for control, changes in result["improvements"].items()
    }
    project_strict = (
        improvement_counts["orb_only"] == 4
        and improvement_counts["drop"] == 4
    )
    all_control_strict = project_strict and all(
        improvement_counts[role] == 4
        for role in ("full_bridge_off", "full_unbounded")
    )
    if all_control_strict:
        level = "repeatwise_strict"
    elif project_strict:
        caveats = [
            name
            for name in ("full_bridge_off", "full_unbounded")
            if improvement_counts[name] != 4
        ]
        suffix = "_and_".join(name[5:] for name in caveats)
        level = f"project_strict_{suffix}_caveat"
    elif improvement_counts["orb_only"] == 0:
        if all(value == 0 for value in improvement_counts.values()):
            level = "action_positive_metric_negative_native_negative_non_strict"
        else:
            level = "action_positive_metric_mixed_native_negative_non_strict"
    else:
        level = "action_positive_metric_mixed_non_strict"
    return {
        "level": level,
        "improvement_counts": improvement_counts,
        "project_strict": project_strict,
        "all_control_strict": all_control_strict,
        "native_negative": improvement_counts["orb_only"] == 0,
        "non_strict": not project_strict,
    }


def roster_row(result: dict[str, Any], classification: dict[str, Any]) -> dict[str, Any]:
    full = result["action"]["full"]
    return {
        "window_id": CONFIG["window_id"],
        "dataset": CONFIG["dataset"],
        "sequence": CONFIG["sequence"],
        "window": CONFIG["window"],
        "level": classification["level"],
        "independent_window": "true",
        "primary_selector": CONFIG["selector_name"],
        "accepted_post_init": (
            f"{full['post_init_accepted']}/{full['post_init_attempted']}"
        ),
        "seed_lineages_with_mappoint": full["mappoint_lineages"],
        "assisted_matches": full["matches"],
        "assisted_outliers": full["outliers"],
        "pre_kf_purged": f"{full['pre_kf_purged']}/{full['pre_kf_observed']}",
        "texture_profile": CONFIG["texture_profile"],
        "base_klt_profile": CONFIG["base_klt_profile"],
        "operational_low_texture": "true",
        "sparse_base_klt_low_texture": "false",
        "source_report": REPORT_RELATIVE,
        "formal_root": str(FORMAL_ROOT),
    }


def decision_text(classification: dict[str, Any]) -> list[str]:
    counts = classification["improvement_counts"]
    if classification["all_control_strict"]:
        return [
            "AQUALOC A01 `16200-17100` is a new independent repeatwise-strict",
            "action and trajectory-positive window. Frozen v23 improves reconstructed",
            "and online APE/RPE against native ORB, empty drop, bridge-off, and",
            "unbounded controls in all comparisons.",
        ]
    if classification["project_strict"]:
        return [
            "AQUALOC A01 `16200-17100` is a new independent project-strict action",
            "and trajectory-positive window against native ORB and empty drop.",
            "It is not all-control strict; the bridge-off/unbounded comparison counts",
            f"are `{counts['full_bridge_off']}/4` and `{counts['full_unbounded']}/4`.",
        ]
    return [
        "AQUALOC A01 `16200-17100` is a new independent mechanism/action-positive",
        "window, but the complete deterministic formal grid is not project strict.",
        f"The full-vs-native comparison improves `{counts['orb_only']}/4` metrics;",
        "retain it only in the mechanism/action roster and exclude it from strict",
        "and no-harm denominators.",
    ]


def build_report(
    result: dict[str, Any],
    source: dict[str, Any],
    smoke: dict[str, Any],
    classification: dict[str, Any],
    counts: dict[str, int],
) -> str:
    action = result["action"]
    full = action["full"]
    unbounded = action["full_unbounded"]
    changes = result["improvements"]
    improvement_counts = classification["improvement_counts"]
    claim_lines = [
        "- Count A01 `16200-17100` once as development evidence.",
        "- It is not an untouched confirmatory window.",
    ]
    if classification["all_control_strict"]:
        claim_lines.insert(
            1,
            "- It is project strict and all-control repeatwise strict under this frozen grid.",
        )
    elif classification["project_strict"]:
        claim_lines.insert(
            1,
            "- It is project strict, with the reported all-control caveats; do not call it all-control strict.",
        )
    else:
        claim_lines.insert(
            1,
            "- Do not call it trajectory-positive, no-harm, project strict, or all-control strict.",
        )

    lines = [
        "# ORB-SLAM3 v23 AQUALOC A01 16200-17100 evidence closure R12",
        "",
        "Date: 2026-08-08",
        "",
        "## Decision",
        "",
        *decision_text(classification),
        "",
        "No selector, bridge, dose, phase, binary, library, runner, camera, or",
        "evaluator threshold was changed after observing the outcome.",
        "",
        "## Frozen validation",
        "",
        "All `20/20` formal runs have status `ok`. Each role has one counter,",
        "lineage-phase/action, reconstructed, online, and keyframe signature across",
        "four repeats. R1-R4 all use the frozen `orb_only drop full_bridge_off",
        "full_unbounded full` order. All 20 snapshot",
        f"manifests and all `{result['snapshot_entries']}/{result['snapshot_entries']}` entries pass SHA-256 verification.",
        "",
        f"Classification: `{classification['level']}`. Evaluation uses a `0.06 s`",
        "association threshold and 1-associated-pose RPE.",
        "",
        "| Role | Post-init accepted | MP lineages / MPs | Matches | Outliers | pre-KF observed / purged | Scans |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
        f"| Bridge off | {action['full_bridge_off']['post_init_accepted']}/{action['full_bridge_off']['post_init_attempted']} | {action['full_bridge_off']['mappoint_lineages']} / {action['full_bridge_off']['distinct_mappoints']} | {action['full_bridge_off']['matches']} | {action['full_bridge_off']['outliers']} | {action['full_bridge_off']['pre_kf_observed']} / {action['full_bridge_off']['pre_kf_purged']} | {action['full_bridge_off']['scans']} |",
        f"| Unbounded | {unbounded['post_init_accepted']}/{unbounded['post_init_attempted']} | {unbounded['mappoint_lineages']} / {unbounded['distinct_mappoints']} | {unbounded['matches']} | {unbounded['outliers']} | {unbounded['pre_kf_observed']} / {unbounded['pre_kf_purged']} | {unbounded['scans']} |",
        f"| Frozen v23 | {full['post_init_accepted']}/{full['post_init_attempted']} | {full['mappoint_lineages']} / {full['distinct_mappoints']} | {full['matches']} | {full['outliers']} | {full['pre_kf_observed']} / {full['pre_kf_purged']} | {full['scans']} |",
        "",
        "| Role | Reconstructed APE / RPE | Online APE / RPE |",
        "| --- | --- | --- |",
        f"| Native ORB | `{r08.format_metric(result, 'orb_only', 'reconstructed')}` | `{r08.format_metric(result, 'orb_only', 'online')}` |",
        f"| Empty drop | `{r08.format_metric(result, 'drop', 'reconstructed')}` | `{r08.format_metric(result, 'drop', 'online')}` |",
        f"| Bridge off | `{r08.format_metric(result, 'full_bridge_off', 'reconstructed')}` | `{r08.format_metric(result, 'full_bridge_off', 'online')}` |",
        f"| Unbounded | `{r08.format_metric(result, 'full_unbounded', 'reconstructed')}` | `{r08.format_metric(result, 'full_unbounded', 'online')}` |",
        f"| Frozen v23 | `{r08.format_metric(result, 'full', 'reconstructed')}` | `{r08.format_metric(result, 'full', 'online')}` |",
        "",
        "Frozen v23 change versus native (positive is better):",
        "",
        f"- reconstructed APE/RPE: `{changes['orb_only']['reconstructed_ape']:.3f}% / {changes['orb_only']['reconstructed_rpe']:.3f}%`",
        f"- online APE/RPE: `{changes['orb_only']['online_ape']:.3f}% / {changes['orb_only']['online_rpe']:.3f}%`",
        f"- improved metrics: native `{improvement_counts['orb_only']}/4`; drop `{improvement_counts['drop']}/4`; bridge-off `{improvement_counts['full_bridge_off']}/4`; unbounded `{improvement_counts['full_unbounded']}/4`",
        "",
        "## Discovery smoke and phase gate",
        "",
        f"The completed three-arm smoke passes `{smoke['runs_ok']}/{smoke['runs']}` runs and all `{smoke['snapshot_entries']}` snapshot entries.",
        "Its full role attempts all 153 seed observations post-init, accepts 150,",
        "creates 2 MapPoint lineages / 8 distinct MapPoints, consumes 103 assisted",
        "matches, observes 8 natural outliers, and purges 6/6 pre-KF outliers.",
        "The formal grid is independently required to remain pure post-init and",
        "action-positive in every repeat; smoke evidence is not substituted for it.",
        "",
        "## Frozen source and exact-drop contract",
        "",
        f"The clean rebuild contains {source['fresh_klt_frames']} feature frames and",
        f"{source['fresh_klt_observations']} native observations, with zero historical",
        "learned observations removed from the base. Coordinates, exported images,",
        f"and both camera files use the 968x608 AQUALOC archaeology contract.",
        "",
        f"The frozen sidecar triggers {source['sidecar_triggers']} times at frames",
        f"{source['sidecar_trigger_frames']} and proposes {source['sidecar_candidates']}",
        f"candidates. The selector exports {source['seed_ids']} IDs over",
        f"{source['seed_frames']} frames and {source['seed_observations']} observations",
        f"with {source['seed_max_timestamp_difference_ns']} ns maximum timestamp error.",
        "No exported seed is non-finite or out of bounds.",
        "",
        "The independent exact whole-lineage audit passes byte-for-byte payload,",
        "timestamp, message-topology, non-feature, and learned-lineage removal checks:",
        "153 learned observations from 3 lineages are removed and all 157500 native",
        "observations remain in the drop control.",
        "",
        "## Texture and denominator",
        "",
        f"Tracks min/mean/max are `{result['base_track_min']:.0f} / {result['base_track_mean']:.3f} / {result['base_track_max']:.0f}`;",
        f"grid min/mean/max are `{result['base_grid_min']:.6f} / {result['base_grid_mean']:.6f} / {result['base_grid_max']:.6f}`;",
        f"`{result['low_grid_frames']}/{result['frontend_frames']}` frames are at or below `0.80`.",
        "",
        f"- mechanism/action-positive: `{counts['action_positive']}`",
        f"- project strict: `{counts['project_strict']}`",
        f"- all-control repeatwise strict: `{counts['all_control_strict']}`",
        f"- operational degraded/low-grid: `{counts['operational_low_grid']}/{counts['action_positive']}`",
        f"- operational low-grid among project strict: `{counts['strict_operational_low_grid']}/{counts['project_strict']}`",
        f"- sparse base-KLT positives: `{counts['sparse_base_klt']}/{counts['action_positive']}`",
        "",
        "## Claim boundary",
        "",
        *claim_lines,
        "",
        f"Formal root: `{FORMAL_ROOT}`",
        f"Smoke root: `{SMOKE_ROOT}`",
        f"Exact-drop audit: `{EXACT_DROP_PATH}`",
        "",
    ]
    return "\n".join(lines)


def provenance_artifacts() -> list[tuple[str, Path]]:
    artifacts: list[tuple[str, Path]] = [
        ("analysis_builder", Path(__file__).resolve()),
        (
            "analysis_core_r08",
            WORKSPACE / "scripts/analyze_orbslam3_v23_continued_search_r08.py",
        ),
        ("roster_counter_r09", WORKSPACE / "scripts/analyze_orbslam3_v23_a01_r09.py"),
        (
            "feature_bag_auditor_r11",
            WORKSPACE / "scripts/analyze_orbslam3_v23_afrl_cemetery_fr_r11.py",
        ),
        ("prior_roster", PRIOR_ROSTER),
        ("orb_binary", ORB_BINARY),
        ("orb_library", ORB_LIBRARY),
        ("runner", WORKSPACE / "scripts/run_orbslam3_seeded_triplet.sh"),
        ("dataset_exporter", WORKSPACE / "scripts/prepare_orbslam3_aqualoc_bag.py"),
        ("seed_exporter", WORKSPACE / "scripts/export_orbslam3_confirmed_seeds.py"),
        ("clean_filter", WORKSPACE / "scripts/filter_feature_bag_by_channel.py"),
        ("selector_runner", WORKSPACE / "scripts/prepare_causal_multilineage_bag.sh"),
        ("selector_node", WORKSPACE / "uw_frontend/ros/causal_lineage_shadow_node.py"),
        (
            "sidecar_generator_frozen",
            CLEAN_ROOT / "provenance/xfeat_seed_sidecar_node_9afc.py",
        ),
        (
            "sidecar_config",
            WORKSPACE
            / "uw_frontend/configs/experiments/cirs_xfeat_seedchain_klt_probe.yaml",
        ),
        ("exact_drop_auditor", WORKSPACE / "scripts/audit_whole_lineage_exact_drop_v1.py"),
        ("evaluator", WORKSPACE / "scripts/evaluate_orbslam3_seeded_runs.py"),
        ("raw_bag", CONFIG["raw_bag"]),
        ("fresh_klt_bag", KLT_ROOT / "features.bag"),
        ("fresh_klt_metrics", KLT_ROOT / "frontend_metrics.csv"),
        ("fresh_klt_quality_contract", KLT_ROOT / "features.bag.quality-contract.json"),
        ("fresh_klt_camera", CONFIG["camera_config"]),
        ("orb_camera", CONFIG["orb_config"]),
        ("clean_base_stats", CLEAN_ROOT / "base_drop_stats.csv"),
        ("clean_base_bag", CLEAN_ROOT / "base_drop.bag"),
        ("sidecar_stats", CLEAN_ROOT / "stats.csv"),
        ("sidecar_bag", CLEAN_ROOT / "sidecar.bag"),
        ("selector_manifest", SELECTOR_ROOT / "manifest.txt"),
        ("selector_lineages", SELECTOR_ROOT / "lineage_selection.csv"),
        ("selector_drop_bag", SELECTOR_ROOT / "drop_whole_lineage.bag"),
        ("selector_full_bag", SELECTOR_ROOT / "full_merged.bag"),
        ("exact_drop_audit", EXACT_DROP_PATH),
        ("full_seeds", SEED_ROOT / "full_seeds.txt"),
        ("drop_seeds", SEED_ROOT / "drop_seeds.txt"),
        ("feature_times", SEED_ROOT / "feature_times.txt"),
        ("seed_export_stats", SEED_ROOT / "seed_export_stats.json"),
        ("dataset_metadata", DATASET_ROOT / "export_metadata.json"),
        ("dataset_times", DATASET_ROOT / "cam0_times.txt"),
        ("dataset_groundtruth", DATASET_ROOT / "groundtruth_tum.txt"),
        ("evaluation_reconstructed", FORMAL_ROOT / "evaluation_reconstructed.csv"),
        ("evaluation_online", FORMAL_ROOT / "evaluation_online.csv"),
    ]
    for role in ("orb_only", "drop", "full"):
        run = SMOKE_ROOT / f"{role}_r1"
        prefix = f"smoke_{role}"
        artifacts.extend(
            [
                (f"{prefix}_manifest", run / "run_manifest.txt"),
                (f"{prefix}_summary", run / "instrumentation/seed_summary.json"),
                (f"{prefix}_lineages", run / "instrumentation/seed_lineages.csv"),
                (f"{prefix}_snapshot", run / "provenance/snapshot_sha256.txt"),
                (f"{prefix}_reconstructed", r08.one_file(run, "f_*.txt")),
                (f"{prefix}_online", r08.one_file(run, "online_f_*.txt")),
                (f"{prefix}_keyframe", r08.one_file(run, "kf_*.txt")),
            ]
        )
    return artifacts


def audit_prior_roster() -> list[dict[str, str]]:
    prior = r08.read_csv(PRIOR_ROSTER)
    if len(prior) != 18 or len({row["window_id"] for row in prior}) != 18:
        raise RuntimeError("prior R11 roster is not 18 unique windows")
    if r09.roster_counts(prior) != PRIOR_COUNTS:
        raise RuntimeError(
            f"prior R11 denominator mismatch: {r09.roster_counts(prior)}"
        )
    if any(row["window_id"] == CONFIG["window_id"] for row in prior):
        raise RuntimeError("A01 16200-17100 already exists in the prior roster")
    return prior


def main() -> int:
    args = parse_args()
    source = audit_source_contract()
    smoke = audit_smoke_contract()
    prior = audit_prior_roster()

    if args.preflight:
        print(
            json.dumps(
                {
                    "status": "preflight_ok_no_formal_outcomes_accessed",
                    "window_id": CONFIG["window_id"],
                    "prior_roster_rows": len(prior),
                    "source_contract": source,
                    "smoke_contract": smoke,
                    "formal_root_not_read": str(FORMAL_ROOT),
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 0

    output = args.output.resolve()
    if output.exists() and not args.replace:
        raise SystemExit(f"output exists; pass --replace: {output}")

    # This is the first formal-outcome access in the program.  It fails closed
    # unless both 20-row evaluation grids and all 20 formal run contracts exist.
    result = evaluate_formal_window(CONFIG)
    formal_action = audit_formal_action(result, source["seed_observations"])
    classification = classify_trajectory(result)
    CONFIG["level"] = classification["level"]
    result["config"]["level"] = classification["level"]

    roster = prior + [roster_row(result, classification)]
    if len(roster) != 19 or len({row["window_id"] for row in roster}) != 19:
        raise RuntimeError("R12 roster is not 19 unique windows")
    counts = r09.roster_counts(roster)
    expected_counts = {
        "action_positive": 19,
        "project_strict": PRIOR_COUNTS["project_strict"]
        + int(classification["project_strict"]),
        "all_control_strict": PRIOR_COUNTS["all_control_strict"]
        + int(classification["all_control_strict"]),
        "operational_low_grid": 12,
        "strict_operational_low_grid": PRIOR_COUNTS["strict_operational_low_grid"]
        + int(classification["project_strict"]),
        "sparse_base_klt": 0,
    }
    if counts != expected_counts:
        raise RuntimeError(f"unexpected R12 roster counts: {counts}")

    output.parent.mkdir(parents=True, exist_ok=True)
    temp = Path(tempfile.mkdtemp(prefix=f".{output.name}.", dir=output.parent))
    try:
        r08.write_csv(temp / "formal_summary.csv", [r08.formal_summary(result)])
        r08.write_csv(temp / "window_roster.csv", roster)

        provenance_rows = []
        for name, path in provenance_artifacts():
            resolved = path.resolve()
            if not resolved.is_file():
                raise RuntimeError(f"missing provenance artifact: {resolved}")
            provenance_rows.append(
                {
                    "artifact": name,
                    "sha256": r08.sha256(resolved),
                    "path": str(resolved),
                }
            )
        r08.write_csv(temp / "provenance.csv", provenance_rows)

        improvement_counts = classification["improvement_counts"]
        validation = {
            "schema_version": 6,
            "date": "2026-08-08",
            "added_windows": 1,
            "roster_rows": len(roster),
            "roster_unique_windows": len({row["window_id"] for row in roster}),
            "updated_counts": counts,
            "snapshot_manifests": 23,
            "snapshot_manifests_verified": 23,
            "snapshot_entries": result["snapshot_entries"]
            + smoke["snapshot_entries"],
            "snapshot_entries_verified": result["snapshot_entries"]
            + smoke["snapshot_entries"],
            "source_contract": source,
            "smoke_contract": smoke,
            "windows": {
                CONFIG["window_id"]: {
                    "action_positive": True,
                    "pure_post_init": True,
                    "level": classification["level"],
                    "native_negative": classification["native_negative"],
                    "non_strict": classification["non_strict"],
                    "project_strict": classification["project_strict"],
                    "all_control_strict": classification["all_control_strict"],
                    "repeat4_order_swapped": False,
                    "formal_role_order": FORMAL_ROLE_ORDER,
                    "formal_runs": 20,
                    "formal_runs_ok": 20,
                    "full_vs_native_improvements": improvement_counts["orb_only"],
                    "full_vs_drop_improvements": improvement_counts["drop"],
                    "full_vs_bridge_off_improvements": improvement_counts[
                        "full_bridge_off"
                    ],
                    "full_vs_unbounded_improvements": improvement_counts[
                        "full_unbounded"
                    ],
                    "operational_low_grid": True,
                    "sparse_base_klt": False,
                    "low_grid_frames_le_0p80": result["low_grid_frames"],
                    "frontend_frames": result["frontend_frames"],
                    "seed_quality_min": result["seed_quality_min"],
                    "seed_quality_below_0p9": result["seed_quality_below_0p9"],
                    "role_counter_signatures": result["counter_signatures"],
                    "role_action_signatures": formal_action[
                        "role_action_signatures"
                    ],
                    "role_reconstructed_hashes": result["trajectory_hashes"][
                        "reconstructed"
                    ],
                    "role_online_hashes": result["trajectory_hashes"]["online"],
                    "role_keyframe_hashes": result["trajectory_hashes"]["keyframe"],
                    "formal_actions_by_repeat": formal_action["actions_by_repeat"],
                    "snapshot_manifests": 20,
                    "snapshot_manifests_verified": 20,
                    "snapshot_entries": result["snapshot_entries"],
                    "snapshot_entries_verified": result["snapshot_entries"],
                    "formal_root": str(FORMAL_ROOT),
                }
            },
        }
        (temp / "validation_summary.json").write_text(
            json.dumps(validation, indent=2, sort_keys=True) + "\n",
            encoding="ascii",
        )
        (temp / "analysis-report.md").write_text(
            build_report(result, source, smoke, classification, counts),
            encoding="ascii",
        )

        if output.exists():
            shutil.rmtree(output)
        os.replace(temp, output)
    except Exception:
        shutil.rmtree(temp, ignore_errors=True)
        raise
    print(f"wrote validated R12 A01 16200-17100 bundle to {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
