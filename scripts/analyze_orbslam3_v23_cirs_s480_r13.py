#!/usr/bin/env python3
"""Build the R13 CIRS s480,d30 ORB-v23 action-evidence bundle.

This builder is fail closed.  ``--preflight`` validates only the frozen
frontend/source, exact-drop, current-B1, prior-roster, and completed discovery
smoke artifacts.  That branch returns before any formal result path is read.

The default mode additionally requires a complete deterministic five-role by
four-repeat formal grid and both evaluator CSVs.  The CIRS reference carried on
``/cirs/odometry_gt`` is explicitly an official odometry trajectory proxy and
is non-independent.  Therefore evaluator values are descriptive proxy
alignment only and can never promote this window into a project-strict,
all-control-strict, no-harm, or metric-accuracy denominator.
"""

from __future__ import annotations

import argparse
import bisect
import csv
import json
import math
import os
import shutil
import statistics
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
    WORKSPACE / "papers/orb_v23_cirs_s480_r13_20260808/analysis-output"
)
PRIOR_ROSTER = (
    WORKSPACE
    / "papers/orb_v23_a01_16200_r12_20260808/analysis-output/window_roster.csv"
)
REPORT_RELATIVE = (
    "papers/orb_v23_cirs_s480_r13_20260808/analysis-output/analysis-report.md"
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
SMOKE_ROLE_ORDER = "orb_only drop full"
ROLES = ("orb_only", "drop", "full_bridge_off", "full_unbounded", "full")
REPEATS = (1, 2, 3, 4)
TRAJECTORY_PATTERNS = {
    "reconstructed": "f_*.txt",
    "online": "online_f_*.txt",
    "keyframe": "kf_*.txt",
}

SEARCH_ROOT = WORKSPACE / ".orbslam3_seeded_cirs_s480_d30_20260808"
CURRENT_B1_ROOT = WORKSPACE / ".crossdataset_cirs_s480_current_b1_20260808"
CLEAN_ROOT = (
    WORKSPACE
    / ".online_positive_search_cirs_s480_d30_20260808/"
    "clean_ignore0_frozen_20260808_prep_v2"
)
SELECTOR_ROOT = SEARCH_ROOT / "n3_d14_min8_ignore0_clean_selector_v2"
SEED_ROOT = SEARCH_ROOT / "assets_n3_d14_min8_ignore0_clean"
EXACT_DROP_PATH = SEARCH_ROOT / "audit_exact_drop/selector_whole_lineage_audit.json"
SMOKE_ROOT = SEARCH_ROOT / SMOKE_SUFFIX
FORMAL_ROOT = SEARCH_ROOT / FORMAL_SUFFIX
DATASET_ROOT = (
    WORKSPACE / ".orbslam3_validation_cirs_s480_d30_20260808/dataset"
)
RAW_BAG = (
    DATA_ROOT
    / "logs/cirs_caves_vins/"
    "external_hybrid_xfeat_every1_jul15screen_cirs_s480_d30_probe/"
    "raw_segment.bag"
)
LEGACY_BASE_BAG = (
    DATA_ROOT
    / "logs/cirs_caves_vins/"
    "external_klt_every1_jun22_cirs_s480_d30_klt_every1_shift_probe/"
    "features.bag"
)
ORB_CONFIG = DATA_ROOT / "logs/orbslam3_validation/cirs_cala_viuda_mono_5hz.yaml"
ORB_ROOT = Path("/home/ma/SLAM/orb_slam3_lineage_ws/src/ORB_SLAM3-lineage")
ORB_BINARY = ORB_ROOT / "Examples_old/Monocular/mono_euroc_old"
ORB_LIBRARY = ORB_ROOT / "lib/libORB_SLAM3.so"

REFERENCE_KIND = "official CIRS odometry trajectory proxy; non-independent"
REFERENCE_TOPIC = "/cirs/odometry_gt"
METRIC_SCOPE = "descriptive_proxy_alignment_only"
ASSOCIATION_S = 0.06
RPE_DELTA_ASSOCIATED_POSES = 5
EVO_VERSION = "1.31.1"

SIDECAR_CONFIG_CHAIN: tuple[tuple[str, Path, str, str | None], ...] = (
    (
        "cirs_xfeat_seedchain_klt_probe",
        WORKSPACE / "uw_frontend/configs/experiments/cirs_xfeat_seedchain_klt_probe.yaml",
        "c98df8dcf6a58261798d06433f52a8bf02bf39968a52fe85475284f845229d38",
        "cirs_identity_churn_xfeat_probe.yaml",
    ),
    (
        "cirs_identity_churn_xfeat_probe",
        WORKSPACE / "uw_frontend/configs/experiments/cirs_identity_churn_xfeat_probe.yaml",
        "9e16c2b2377d95d2a855b05733a2bc37d77defc1ed101ea8ba88afc8e7c1db91",
        "low_texture_active_xfeat_sidecar.yaml",
    ),
    (
        "low_texture_active_xfeat_sidecar",
        WORKSPACE / "uw_frontend/configs/experiments/low_texture_active_xfeat_sidecar.yaml",
        "2a61f1c57a77df4ed6bf2d85c080c7e6bd754a2ff47171e526e0643a3d617a25",
        "paper_vins_safe_learned_sidecar.yaml",
    ),
    (
        "paper_vins_safe_learned_sidecar",
        WORKSPACE / "uw_frontend/configs/experiments/paper_vins_safe_learned_sidecar.yaml",
        "4500894ee15f4515881de6322e5780ce7f2381b2a1ce7fba4bd3d958e11264ce",
        "loftr_extreme_only_frontend.yaml",
    ),
    (
        "loftr_extreme_only_frontend",
        WORKSPACE / "uw_frontend/configs/experiments/loftr_extreme_only_frontend.yaml",
        "d5927fb412de869cfe9dd6275dfb81a566fc33e4149160bafc0e8fa933b27eed",
        "three_layer_source_aware_frontend.yaml",
    ),
    (
        "three_layer_source_aware_frontend",
        WORKSPACE / "uw_frontend/configs/experiments/three_layer_source_aware_frontend.yaml",
        "236e5173611731ffefd3acdd3b9f69429633dac16ae66429690d609fab0dd5d7",
        "../backend_strict_frontend.yaml",
    ),
    (
        "backend_strict_frontend",
        WORKSPACE / "uw_frontend/configs/backend_strict_frontend.yaml",
        "908351d3d9547b98f917ffd059efdc7b279ee7f9199887688cda48e178a4855a",
        None,
    ),
)

CONFIG: dict[str, Any] = {
    "window_id": "CIRS_s480_d30",
    "dataset": "CIRS",
    "sequence": "Cala-Viuda",
    "window": "s480_d30",
    "level": "action_positive_proxy_metric_descriptive_non_strict",
    "selector_name": "n3_d14_min8_ignore0_clean",
    "texture_profile": (
        "operational degraded/identity-churn, high-grid; sparse base-KLT"
    ),
    "base_klt_profile": (
        "212-252, median 227, mean 228.033557; grid 1.0 in 149/149; "
        "dropout mean 0.463998, max 0.995690"
    ),
    "operational_low_texture": True,
    "sparse_base_klt_low_texture": True,
}

PRIOR_COUNTS = {
    "action_positive": 19,
    "project_strict": 6,
    "all_control_strict": 3,
    "operational_low_grid": 12,
    "strict_operational_low_grid": 4,
    "sparse_base_klt": 0,
}
EXPECTED_COUNTS = {
    "action_positive": 20,
    "project_strict": 6,
    "all_control_strict": 3,
    "operational_low_grid": 13,
    "strict_operational_low_grid": 4,
    "sparse_base_klt": 1,
}

SHA = {
    "raw_bag": "f4f0547833c4043348bb4b78da4c1c13f48e428c5d86b9633a7e82981f9750e8",
    "base_bag": "8a68544c4aec11b5d8253436cdae62504076e68b9633419e51d220786206db4d",
    "native_q": "0c5da5e3d8718e553bdff0126c65f79ae16d20c28f5da2ca62e78cdc9e670b38",
    "b1_guard": "1de97e057d6fc222c091d5601c13ec8d797256ce41643d6217bfeaf44363fe36",
    "frontend_metrics": "ff77d3f5d34a25cbf98b81733156550f0a0813c2000e5b4a3c861638a3a15b39",
    "camera": "0cb83c90816f64058948754af3f13e2f65f8c86e4c0d94dcd0580a59c58aa586",
    "orb_config": "dc702d1ddb4eccfa16bce75091aa39aeb01ee0e74931e3473f165fafa0886fdf",
    "sidecar": "03b674375ed00da99f65840c3e72b6338023b9a0d46ae6c011e8f7354afca538",
    "sidecar_stats": "85b11b5f279c7c2c763c469bb2b82ff407996afefd6d8937e5a15facce29a665",
    "sidecar_source": "9afc6f7083f76bf1f7c6b7c19f79f02a98160663c945479b51492fa19cb3ace7",
    "sidecar_config": "c98df8dcf6a58261798d06433f52a8bf02bf39968a52fe85475284f845229d38",
    "full_bag": "7c39c8b35883fa306527d6b584ed7ad4223eff4bd93d7090dc53849a9e2e408d",
    "selector_manifest": "4697e5865a2ba756a6c51af473fc1af0e2dc227ffde67b39f8f33a175d5fbae9",
    "selector_lineages": "80354edcf32936bd795cc531706df5ad82b67c3e01419a638935f32e82851963",
    "full_seeds": "af8d54922670f4bde2fd2672f38f5a450fc5997e7fdce93ad80dbffc7a824f91",
    "drop_seeds": "4d77d35c290b73157b0db402c185f1750e64409418f1d79d3e2de06b94daa919",
    "feature_times": "260ae75d4ca36bb0fdfefe4477aa89a3e6d4c71bc45216d6875bdd9468b878c2",
    "seed_export": "f6bd45f3b85f321d82618d4d609ca37c62bb84b1c0a982bdec3997e927037661",
    "exact_drop": "d4a2de8fb9457ad47fdbb8d0e6673269dc3025a4ec1ef066882a8f349aed291f",
    "dataset_times": "260ae75d4ca36bb0fdfefe4477aa89a3e6d4c71bc45216d6875bdd9468b878c2",
    "proxy_tum": "e33890d78979a84f76692b8aeddb3cd68cf62714693d278197d2820ae24f91e8",
    "dataset_metadata": "ba6f8a7760aba1961f1ec9357ae8f099ed6be2eab885b8972bd36f9b48c2fd38",
    "evaluator": "98dfa04854da97ddd44721ac8eb03261bf54b4d760f8c560e55cacc861e31b60",
    "exact_drop_auditor": "bf6ccbf47d3b6b1e4fdad8b9e8b49d17f9545b312ce64970b61ed6c56cdf71b4",
    "runner": "6ffedc001ae51b6b80a391c4dad3a6cbd917037968a1e94e582f98e78a4c4c77",
    "orb_binary": "cebeeedb862a469f9b4928fc0712fd0fd93766d4a4b5faa09e7de5a0f19083fc",
    "orb_library": "05a7b3cc8aa7aaefec38ce995de9fbf808662c051f1ce1f0f35925f2e6093af8",
    "evaluation_reconstructed_delta5": "2461fd21e0b4ed2bc3dc59e10927dd9da49f7f664864142309c7a653a04cd218",
    "evaluation_online_delta5": "3a2ac6c47f1c4f0f56e4cd622e39edd259bde51ed8c71542f59f81b21327120b",
    "evaluation_reconstructed_delta1": "fe3aa19d53239d7c19f4dc79666ba54ad182e0076de7808024b5e5bc2a325c27",
    "evaluation_online_delta1": "8fd6f6e8af651b7c0bb7932379ecc392cdd9d0c53564ba9f6016d0f23182b3c0",
}

CONSERVATION_FIELDS = (
    "phase_conservation",
    "extractor_conservation",
    "accepted_conservation",
    "per_token_conservation",
    "reference_lineage_decision_conservation",
    "lineage_cull_grace_conservation",
    "valid_tokens",
    "mappoint_pointer_consistency",
    "mappoint_pointer_key_consistency",
    "atlas_snapshot_available",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Validate and package CIRS s480,d30 ORB-v23 R13 evidence."
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--replace", action="store_true")
    parser.add_argument(
        "--preflight",
        action="store_true",
        help=(
            "validate frozen non-formal inputs and discovery smoke only; "
            "do not read any formal outcome"
        ),
    )
    return parser.parse_args()


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        raise RuntimeError(f"refusing empty CSV: {path}")
    with path.open("w", newline="", encoding="ascii") as handle:
        writer = csv.DictWriter(
            handle, fieldnames=list(rows[0]), lineterminator="\n"
        )
        writer.writeheader()
        writer.writerows(rows)


def require_sha(path: Path, expected: str, label: str) -> None:
    observed = r08.sha256(path)
    if observed != expected:
        raise RuntimeError(f"{label} SHA-256 mismatch: {observed}")


def require_close(observed: float, expected: float, label: str) -> None:
    if not math.isclose(observed, expected, rel_tol=0.0, abs_tol=1e-12):
        raise RuntimeError(f"{label} mismatch: {observed} != {expected}")


def one_csv_row(path: Path) -> dict[str, str]:
    rows = read_csv(path)
    if len(rows) != 1:
        raise RuntimeError(f"expected one row in {path}, got {len(rows)}")
    return rows[0]


def action_record(run: Path, summary: dict[str, Any]) -> dict[str, int]:
    lineages = read_csv(run / "instrumentation/seed_lineages.csv")
    return {
        "loaded": int(summary["loaded_seed_observations"]),
        "attempted": int(summary["attempted_seed_observations"]),
        "accepted": int(summary["accepted_seed_observations"]),
        "pre_init_attempted": sum(int(row["pre_init_attempted"]) for row in lineages),
        "post_init_attempted": sum(int(row["post_init_attempted"]) for row in lineages),
        "post_init_accepted": sum(int(row["post_init_accepted"]) for row in lineages),
        "mappoint_lineages": int(summary["seed_lineages_with_mappoint"]),
        "distinct_mappoints": int(summary["distinct_mappoints"]),
        "matches": int(summary["lineage_assisted_matches_consumed"]),
        "outliers": int(summary["lineage_assisted_outliers_observed"]),
        "pre_kf_observed": int(summary["lineage_pre_kf_assisted_outliers_observed"]),
        "pre_kf_purged": int(summary["lineage_pre_kf_assisted_outliers_purged"]),
        "scans": int(summary["lineage_pre_kf_outlier_purge_scans"]),
    }


ACTION_FIELDS = (
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


def action_signature(action: dict[str, int]) -> tuple[int, ...]:
    return tuple(action[field] for field in ACTION_FIELDS)


def require_summary_health(summary: dict[str, Any], label: str) -> None:
    if summary.get("schema_version") != 1:
        raise RuntimeError(f"{label} has unexpected summary schema")
    if summary.get("complete") is not True or summary.get("status") != "ok":
        raise RuntimeError(f"{label} instrumentation is incomplete/non-ok")
    if int(summary.get("event_capacity", -1)) != 131072:
        raise RuntimeError(f"{label} has wrong event capacity")
    if int(summary.get("related_mappoint_capacity", -1)) != 131072:
        raise RuntimeError(f"{label} has wrong related-MapPoint capacity")
    if int(summary.get("events_overflowed", -1)) != 0:
        raise RuntimeError(f"{label} event audit overflowed")
    if int(summary.get("related_mappoint_overflowed", -1)) != 0:
        raise RuntimeError(f"{label} related-MapPoint audit overflowed")
    missing = [field for field in CONSERVATION_FIELDS if summary.get(field) is not True]
    if missing:
        raise RuntimeError(f"{label} failed health/conservation checks: {missing}")


def require_pure_post_init(action: dict[str, int], label: str) -> None:
    if action["pre_init_attempted"] != 0:
        raise RuntimeError(f"{label} includes pre-init attempts: {action}")
    if action["post_init_attempted"] != action["attempted"]:
        raise RuntimeError(f"{label} phase accounting mismatch: {action}")
    if action["post_init_accepted"] != action["accepted"]:
        raise RuntimeError(f"{label} acceptance accounting mismatch: {action}")


def require_action_positive(action: dict[str, int], label: str) -> None:
    require_pure_post_init(action, label)
    required = (
        "mappoint_lineages",
        "distinct_mappoints",
        "matches",
        "outliers",
        "pre_kf_observed",
        "pre_kf_purged",
    )
    missing = [field for field in required if action[field] <= 0]
    if missing:
        raise RuntimeError(f"{label} does not close action chain {missing}: {action}")
    if action["pre_kf_purged"] > action["pre_kf_observed"]:
        raise RuntimeError(f"{label} purge accounting mismatch: {action}")


def audit_exact_drop_contract() -> dict[str, Any]:
    require_sha(EXACT_DROP_PATH, SHA["exact_drop"], "exact-drop audit")
    audit = json.loads(EXACT_DROP_PATH.read_text(encoding="utf-8"))
    if audit.get("schema_version") != "aqua-fe-whole-lineage-exact-drop-audit-v1":
        raise RuntimeError("unexpected exact-drop schema")
    if audit.get("contract_pass") is not True:
        raise RuntimeError("exact-drop contract did not pass")
    if audit.get("decision") != "PASS_EXACT_WHOLE_LINEAGE_DROP":
        raise RuntimeError("unexpected exact-drop decision")
    if audit.get("forbidden_outcomes_accessed") != []:
        raise RuntimeError("exact-drop audit crossed its outcome boundary")
    if audit.get("outcome_boundary") != "FRONTEND_BAG_ONLY_NO_VINS_APE_RPE_TRAJECTORY":
        raise RuntimeError("wrong exact-drop outcome boundary")
    checks = audit["checks"]
    required_true = (
        "drop_feature_payload_equals_filtered_proposed_payload_byte_for_byte",
        "feature_header_and_record_timestamps_exact",
        "learned_births_and_all_lineage_continuations_absent_from_drop",
        "message_count_order_topic_type_md5_record_timestamp_exact",
        "non_dropped_observation_order_fields_channels_exact",
        "nonfeature_serialized_bytes_exact",
    )
    if any(checks.get(field) is not True for field in required_true):
        raise RuntimeError(f"exact-drop payload check failed: {checks}")
    if checks.get("producer_stats_contract_exact") is not False:
        raise RuntimeError("unexpected producer-stats exact-drop flag")
    if audit.get("producer_stats") is not None:
        raise RuntimeError("selector audit unexpectedly carries producer stats")
    if audit["inputs"].get("drop_bag_sha256") != SHA["base_bag"]:
        raise RuntimeError("exact-drop control hash mismatch")
    if audit["inputs"].get("proposed_bag_sha256") != SHA["full_bag"]:
        raise RuntimeError("exact-drop proposed hash mismatch")
    expected_summary = {
        "drop_observations": 33977,
        "dropped_observations": 11,
        "feature_frames": 149,
        "frames_with_drops": 9,
        "klt_source_code_1_continuation_observations": 0,
        "learned_birth_observations": 3,
        "learned_lineages": 3,
        "learned_marked_observations": 11,
        "nonfeature_messages": 659,
        "proposed_observations": 33988,
        "total_messages": 808,
        "unmarked_continuation_observations": 0,
    }
    if audit.get("summary") != expected_summary:
        raise RuntimeError(f"exact-drop summary mismatch: {audit.get('summary')}")
    lineage_lengths = sorted(
        int(item["total_observations"]) for item in audit["learned_lineages"]
    )
    if lineage_lengths != [1, 1, 9]:
        raise RuntimeError(f"unexpected selected lineage lengths: {lineage_lengths}")
    return {
        "contract_pass": True,
        "decision": audit["decision"],
        "audit_sha256": SHA["exact_drop"],
        "summary": expected_summary,
        "selected_lineage_lengths": lineage_lengths,
        "path": str(EXACT_DROP_PATH),
    }


def audit_texture_contract() -> dict[str, Any]:
    path = CURRENT_B1_ROOT / "frontend_metrics.csv"
    rows = read_csv(path)
    if len(rows) != 149:
        raise RuntimeError(f"current-B1 frontend frame count mismatch: {len(rows)}")
    tracks = [float(row["num_features"]) for row in rows]
    grid = [float(row["grid_coverage"]) for row in rows]
    dropout = [float(row["dropout_ratio"]) for row in rows]
    degradation = [float(row["degradation_score"]) for row in rows]
    observed = {
        "frames": len(rows),
        "track_min": min(tracks),
        "track_median": statistics.median(tracks),
        "track_mean": statistics.mean(tracks),
        "track_max": max(tracks),
        "tracks_below_350_frames": sum(value < 350 for value in tracks),
        "grid_min": min(grid),
        "grid_median": statistics.median(grid),
        "grid_mean": statistics.mean(grid),
        "grid_max": max(grid),
        "grid_equal_1_frames": sum(value == 1.0 for value in grid),
        "dropout_min": min(dropout),
        "dropout_median": statistics.median(dropout),
        "dropout_mean": statistics.mean(dropout),
        "dropout_max": max(dropout),
        "degradation_min": min(degradation),
        "degradation_median": statistics.median(degradation),
        "degradation_mean": statistics.mean(degradation),
        "degradation_max": max(degradation),
    }
    exact = {
        "track_min": 212.0,
        "track_median": 227.0,
        "track_mean": 228.03355704697987,
        "track_max": 252.0,
        "grid_min": 1.0,
        "grid_median": 1.0,
        "grid_mean": 1.0,
        "grid_max": 1.0,
        "dropout_min": 0.0,
        "dropout_median": 0.44841269841269843,
        "dropout_mean": 0.46399764379611647,
        "dropout_max": 0.9956896551724138,
        "degradation_min": 0.1490193258543404,
        "degradation_median": 0.19396124793910374,
        "degradation_mean": 0.1927336811903014,
        "degradation_max": 0.23520655074158914,
    }
    for field, expected in exact.items():
        require_close(float(observed[field]), expected, f"texture {field}")
    if observed["tracks_below_350_frames"] != 149:
        raise RuntimeError("window is not uniformly below the 350-feature cap")
    if observed["grid_equal_1_frames"] != 149:
        raise RuntimeError("high-grid texture contract changed")
    observed.update(
        {
            "classification": CONFIG["texture_profile"],
            "operational_low_texture": True,
            "operational_basis": "low_base_tracks+identity_churn",
            "low_grid": False,
            "sparse_base_klt": True,
            "sparse_definition": "base KLT clearly below 350-feature cap",
        }
    )
    return observed


def audit_source_contract() -> dict[str, Any]:
    config_chain: list[dict[str, Any]] = []
    for name, path, expected_sha, expected_parent in SIDECAR_CONFIG_CHAIN:
        require_sha(path, expected_sha, f"sidecar config chain {name}")
        extends = [
            line.split(":", 1)[1].strip()
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.startswith("extends:")
        ]
        if expected_parent is None:
            if extends:
                raise RuntimeError(f"terminal sidecar config unexpectedly extends: {path}")
        elif extends != [expected_parent]:
            raise RuntimeError(
                f"sidecar config inheritance mismatch: {path}: {extends}"
            )
        config_chain.append(
            {
                "name": name,
                "path": str(path),
                "sha256": expected_sha,
                "extends": expected_parent,
            }
        )

    static_hashes = (
        (RAW_BAG, SHA["raw_bag"], "raw segment"),
        (LEGACY_BASE_BAG, SHA["base_bag"], "legacy frozen base"),
        (CURRENT_B1_ROOT / "features.bag", SHA["base_bag"], "current B1 bag"),
        (CURRENT_B1_ROOT / "features.bag.quality-contract.json", SHA["native_q"], "native-q attestation"),
        (CURRENT_B1_ROOT / "b1_guard_decision.json", SHA["b1_guard"], "B1 guard"),
        (CURRENT_B1_ROOT / "frontend_metrics.csv", SHA["frontend_metrics"], "current B1 metrics"),
        (CURRENT_B1_ROOT / "cirs_cam0_pinhole.yaml", SHA["camera"], "current B1 camera"),
        (CLEAN_ROOT / "base_drop.bag", SHA["base_bag"], "clean base"),
        (CLEAN_ROOT / "sidecar.bag", SHA["sidecar"], "sidecar bag"),
        (CLEAN_ROOT / "stats.csv", SHA["sidecar_stats"], "sidecar stats"),
        (CLEAN_ROOT / "provenance/xfeat_seed_sidecar_node_9afc.py", SHA["sidecar_source"], "frozen sidecar source"),
        (CLEAN_ROOT / "provenance/cirs_xfeat_seedchain_klt_probe_snapshot.yaml", SHA["sidecar_config"], "frozen sidecar config snapshot"),
        (SELECTOR_ROOT / "manifest.txt", SHA["selector_manifest"], "selector manifest"),
        (SELECTOR_ROOT / "lineage_selection.csv", SHA["selector_lineages"], "selector lineage log"),
        (SELECTOR_ROOT / "drop_whole_lineage.bag", SHA["base_bag"], "selector drop bag"),
        (SELECTOR_ROOT / "full_merged.bag", SHA["full_bag"], "selector full bag"),
        (SEED_ROOT / "full_seeds.txt", SHA["full_seeds"], "full seeds"),
        (SEED_ROOT / "drop_seeds.txt", SHA["drop_seeds"], "drop seeds"),
        (SEED_ROOT / "feature_times.txt", SHA["feature_times"], "feature times"),
        (SEED_ROOT / "seed_export_stats.json", SHA["seed_export"], "seed export stats"),
        (DATASET_ROOT / "cam0_times.txt", SHA["dataset_times"], "dataset times"),
        (DATASET_ROOT / "groundtruth_tum.txt", SHA["proxy_tum"], "odometry proxy TUM"),
        (DATASET_ROOT / "export_metadata.json", SHA["dataset_metadata"], "dataset metadata"),
        (ORB_CONFIG, SHA["orb_config"], "ORB camera config"),
        (WORKSPACE / "scripts/evaluate_orbslam3_seeded_runs.py", SHA["evaluator"], "evaluator"),
        (WORKSPACE / "scripts/audit_whole_lineage_exact_drop_v1.py", SHA["exact_drop_auditor"], "exact-drop auditor"),
        (WORKSPACE / "scripts/run_orbslam3_seeded_triplet.sh", SHA["runner"], "ORB runner"),
        (WORKSPACE / "uw_frontend/configs/experiments/cirs_xfeat_seedchain_klt_probe.yaml", SHA["sidecar_config"], "active sidecar config"),
        (ORB_BINARY, SHA["orb_binary"], "ORB binary"),
        (ORB_LIBRARY, SHA["orb_library"], "ORB library"),
    )
    for path, expected, label in static_hashes:
        require_sha(path, expected, label)

    base = one_csv_row(CLEAN_ROOT / "base_drop_stats.csv")
    expected_base = {
        "feature_frames": "149",
        "frames_with_drops": "0",
        "dropped_observations": "0",
        "kept_learned_observations": "0",
        "learned_track_ids": "0",
        "kept_observations": "33977",
        "drop_learned": "0",
        "drop_learned_track_lineage": "1",
        "learned_id_min": "10000000",
    }
    for field, expected in expected_base.items():
        if base.get(field) != expected:
            raise RuntimeError(f"clean base mismatch: {field}={base.get(field)}")

    native_q = json.loads(
        (CURRENT_B1_ROOT / "features.bag.quality-contract.json").read_text(
            encoding="utf-8"
        )
    )
    expected_native_q = {
        "schema_version": "aqua-fe-nativeq-bag-attestation-v1",
        "contract_pass": True,
        "feature_bag_sha256": SHA["base_bag"],
        "feature_frames": 149,
        "feature_observations": 33977,
        "learned_observations": 0,
        "source_counts": {"1": 18019, "2": 15958},
    }
    for field, expected in expected_native_q.items():
        if native_q.get(field) != expected:
            raise RuntimeError(f"native-q attestation mismatch: {field}")
    guard = json.loads(
        (CURRENT_B1_ROOT / "b1_guard_decision.json").read_text(encoding="utf-8")
    )
    expected_guard = {
        "schema_version": "aqua-fe-b1-klt-nativeq-guard-decision-v1",
        "action": "ALLOW_B1_KLT_NATIVEQ",
        "contract_pass": True,
        "counts_as_b1": True,
        "counts_as_proposed_result": False,
        "outcome_boundary": "B1_EXECUTION_CONTRACT_ONLY_NO_TRAJECTORY_OUTCOME",
        "result_label": "B1_KLT_NATIVEQ_V3",
    }
    for field, expected in expected_guard.items():
        if guard.get(field) != expected:
            raise RuntimeError(f"B1 guard mismatch: {field}")

    selector = r08.parse_manifest(SELECTOR_ROOT / "manifest.txt")
    expected_selector = {
        "max_lineages": "3",
        "min_distance_px": "14",
        "ignore_zero_base_speeds": "0",
        "min_observations": "8",
        "rearm_absent_frames": "0",
        "drop_bag_sha256": SHA["base_bag"],
        "full_bag_sha256": SHA["full_bag"],
    }
    for field, expected in expected_selector.items():
        if selector.get(field) != expected:
            raise RuntimeError(f"selector mismatch: {field}={selector.get(field)}")

    sidecar_stats = read_csv(CLEAN_ROOT / "stats.csv")
    triggers = [row for row in sidecar_stats if row["triggered"] == "1"]
    trigger_frames = [int(row["frame_index"]) for row in triggers]
    trigger_added = [int(row["added_seeds"]) for row in triggers]
    trigger_reasons = [row["trigger_reason"] for row in triggers]
    if len(sidecar_stats) != 149 or trigger_frames != [8, 20, 32]:
        raise RuntimeError("sidecar frame/trigger contract mismatch")
    if trigger_added != [50, 50, 50]:
        raise RuntimeError(f"sidecar trigger-dose mismatch: {trigger_added}")
    if trigger_reasons != ["low_base_tracks+identity_churn"] * 3:
        raise RuntimeError(f"sidecar trigger-reason mismatch: {trigger_reasons}")

    seed_export = json.loads(
        (SEED_ROOT / "seed_export_stats.json").read_text(encoding="utf-8")
    )
    expected_seed_export = {
        "source_messages": 149,
        "mapped_feature_frames": 149,
        "seed_ids": 3,
        "seed_frames": 9,
        "seed_observations": 11,
        "max_timestamp_difference_ns": 0,
        "rejected_nonfinite": 0,
        "rejected_out_of_bounds": 0,
        "rejected_by_stride": 0,
        "rejected_by_lineage_maturity": 0,
        "source_code": 20,
    }
    for field, expected in expected_seed_export.items():
        if seed_export.get(field) != expected:
            raise RuntimeError(f"seed export mismatch: {field}={seed_export.get(field)}")
    seed_rows = [
        line.split()
        for line in (SEED_ROOT / "full_seeds.txt")
        .read_text(encoding="ascii")
        .splitlines()
        if line and not line.startswith("#")
    ]
    if len(seed_rows) != 11 or len({int(row[3]) for row in seed_rows}) != 3:
        raise RuntimeError("full seed row/lineage count mismatch")
    qualities = [float(row[4]) for row in seed_rows]
    if any(not math.isfinite(value) or value < 0.9 for value in qualities):
        raise RuntimeError("full seeds violate finite q>=0.9 gate")

    metadata = json.loads(
        (DATASET_ROOT / "export_metadata.json").read_text(encoding="utf-8")
    )
    expected_metadata = {
        "requested_image_count": 149,
        "kept_images": 149,
        "image_width": 384,
        "image_height": 288,
        "imu_count": 310,
        "gt_count": 349,
        "gt_topic": REFERENCE_TOPIC,
        "gt_bag": None,
        "skipped_duplicate_gt": 0,
        "skipped_duplicate_images": 0,
        "skipped_duplicate_imu": 0,
        "skipped_images_before_imu": 0,
        "source_image_encoding": "mono8",
    }
    for field, expected in expected_metadata.items():
        if metadata.get(field) != expected:
            raise RuntimeError(f"dataset metadata mismatch: {field}")
    proxy_rows = [
        line for line in (DATASET_ROOT / "groundtruth_tum.txt").read_text(
            encoding="ascii"
        ).splitlines() if line.strip() and not line.startswith("#")
    ]
    if len(proxy_rows) != 349:
        raise RuntimeError(f"odometry proxy pose count mismatch: {len(proxy_rows)}")

    expected_native_bag = {
        "frames": 149,
        "observations": 33977,
        "unique_ids": 15958,
        "high_id_observations": 0,
        "source_codes": {1: 18019, 2: 15958},
        "learned_codes": {0: 33977},
        "out_of_bounds": 0,
    }
    current_b1_bag = r11.audit_feature_bag(
        CURRENT_B1_ROOT / "features.bag", "/feature_tracker/feature", 384, 288
    )
    clean_bag = r11.audit_feature_bag(
        CLEAN_ROOT / "base_drop.bag", "/feature_tracker/feature", 384, 288
    )
    drop_bag = r11.audit_feature_bag(
        SELECTOR_ROOT / "drop_whole_lineage.bag",
        "/feature_tracker/feature",
        384,
        288,
    )
    for label, observed in (
        ("current B1", current_b1_bag),
        ("clean base", clean_bag),
        ("selector drop", drop_bag),
    ):
        if observed != expected_native_bag:
            raise RuntimeError(f"{label} bag audit mismatch: {observed}")
    sidecar_bag = r11.audit_feature_bag(
        CLEAN_ROOT / "sidecar.bag", "/feature_tracker/sidecar", 384, 288
    )
    expected_sidecar_bag = {
        "frames": 149,
        "observations": 754,
        "unique_ids": 150,
        "high_id_observations": 0,
        "source_codes": {20: 754},
        "learned_codes": {1: 754},
        "out_of_bounds": 0,
    }
    if sidecar_bag != expected_sidecar_bag:
        raise RuntimeError(f"sidecar bag audit mismatch: {sidecar_bag}")
    full_bag = r11.audit_feature_bag(
        SELECTOR_ROOT / "full_merged.bag", "/feature_tracker/feature", 384, 288
    )
    expected_full_bag = {
        "frames": 149,
        "observations": 33988,
        "unique_ids": 15961,
        "high_id_observations": 11,
        "source_codes": {1: 18019, 2: 15958, 20: 11},
        "learned_codes": {0: 33977, 1: 11},
        "out_of_bounds": 0,
    }
    if full_bag != expected_full_bag:
        raise RuntimeError(f"selector full bag audit mismatch: {full_bag}")

    texture = audit_texture_contract()
    exact_drop = audit_exact_drop_contract()
    return {
        "fresh_current_b1": True,
        "fresh_b1_equals_frozen_base_byte_for_byte": True,
        "native_q_contract_pass": True,
        "b1_guard_action": guard["action"],
        "base_frames": 149,
        "base_observations": 33977,
        "base_learned_observations": 0,
        "sidecar_frames": 149,
        "sidecar_triggers": 3,
        "sidecar_trigger_frames": trigger_frames,
        "sidecar_trigger_reasons": trigger_reasons,
        "sidecar_candidates": sum(trigger_added),
        "sidecar_observations": 754,
        "seed_ids": 3,
        "seed_frames": 9,
        "seed_observations": 11,
        "seed_quality_min": min(qualities),
        "seed_quality_max": max(qualities),
        "seed_quality_below_0p9": sum(value < 0.9 for value in qualities),
        "seed_max_timestamp_difference_ns": 0,
        "image_count": 149,
        "image_width": 384,
        "image_height": 288,
        "imu_count": 310,
        "proxy_pose_count": 349,
        "reference_kind": REFERENCE_KIND,
        "reference_topic": REFERENCE_TOPIC,
        "reference_independent": False,
        "counts_as_metric_accuracy": False,
        "sidecar_config_inheritance_chain": config_chain,
        "sidecar_config_snapshot_scope": (
            "child snapshot is stored in PREP provenance; parent configs are "
            "anchored here by current paths and SHA-256, not flattened copies"
        ),
        "texture": texture,
        "current_b1_bag_audit": current_b1_bag,
        "sidecar_bag_audit": sidecar_bag,
        "selected_drop_bag_audit": drop_bag,
        "selected_full_bag_audit": full_bag,
        "exact_drop": exact_drop,
    }


def audit_smoke_contract() -> dict[str, Any]:
    expected_actions = {
        "orb_only": (0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0),
        "drop": (0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0),
        "full": (11, 11, 9, 0, 11, 9, 1, 2, 5, 1, 1, 1, 80),
    }
    actions: dict[str, dict[str, int]] = {}
    snapshot_entries = 0
    snapshot_counts: Counter[int] = Counter()
    for role in ("orb_only", "drop", "full"):
        run = SMOKE_ROOT / f"{role}_r1"
        manifest = r08.parse_manifest(run / "run_manifest.txt")
        if manifest.get("role") != role or manifest.get("repeat") != "1":
            raise RuntimeError(f"wrong smoke role/repeat manifest: {run}")
        if manifest.get("role_order") != SMOKE_ROLE_ORDER:
            raise RuntimeError(f"wrong smoke role order: {run}")
        if manifest.get("binary_sha256") != SHA["orb_binary"]:
            raise RuntimeError(f"wrong smoke binary: {run}")
        if manifest.get("liborbslam3_sha256") != SHA["orb_library"]:
            raise RuntimeError(f"wrong smoke library: {run}")
        if manifest.get("runner_sha256") != SHA["runner"]:
            raise RuntimeError(f"wrong smoke runner: {run}")
        if manifest.get("config_sha256") != SHA["orb_config"]:
            raise RuntimeError(f"wrong smoke config: {run}")
        if manifest.get("times_sha256") != SHA["feature_times"]:
            raise RuntimeError(f"wrong smoke times: {run}")
        expected_seed = {
            "orb_only": "",
            "drop": SHA["drop_seeds"],
            "full": SHA["full_seeds"],
        }[role]
        if manifest.get("seed_sha256", "") != expected_seed:
            raise RuntimeError(f"wrong smoke seed hash: {run}")
        summary = json.loads(
            (run / "instrumentation/seed_summary.json").read_text(encoding="utf-8")
        )
        require_summary_health(summary, f"smoke {role}")
        action = action_record(run, summary)
        if action_signature(action) != expected_actions[role]:
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
        "pure_post_init": True,
        "action_positive": True,
        "snapshot_manifests": 3,
        "snapshot_manifests_verified": 3,
        "snapshot_entries": snapshot_entries,
        "snapshot_entries_verified": snapshot_entries,
        "actions": actions,
        "root": str(SMOKE_ROOT),
    }


def audit_prior_roster() -> list[dict[str, str]]:
    prior = read_csv(PRIOR_ROSTER)
    if len(prior) != 19 or len({row["window_id"] for row in prior}) != 19:
        raise RuntimeError("prior R12 roster is not 19 unique windows")
    counts = r09.roster_counts(prior)
    if counts != PRIOR_COUNTS:
        raise RuntimeError(f"prior R12 denominator mismatch: {counts}")
    if any(row["window_id"] == CONFIG["window_id"] for row in prior):
        raise RuntimeError("CIRS s480,d30 already exists in prior roster")
    return prior


def summary_signature(summary: dict[str, Any]) -> str:
    stable = {
        key: value
        for key, value in summary.items()
        if key not in {"output_directory"}
    }
    return json.dumps(stable, sort_keys=True, separators=(",", ":"))


def verify_evaluation_row(
    row: dict[str, str], kind: str, role: str, repeat: int, run: Path,
    summary: dict[str, Any], action: dict[str, int]
) -> None:
    if row.get("trajectory_kind") != kind:
        raise RuntimeError(f"wrong evaluator trajectory kind: {run}")
    if row.get("status") != "ok":
        raise RuntimeError(f"non-ok evaluator row: {run}")
    if Path(row.get("run_dir", "")).resolve() != run.resolve():
        raise RuntimeError(f"evaluator run path mismatch: {run}")
    if int(row["input_frames"]) != 149:
        raise RuntimeError(f"evaluator input-frame mismatch: {run}")
    if int(row["output_poses"]) < 2:
        raise RuntimeError(f"too few associated output poses: {run}")
    expected_counts = {
        "loaded_seed_observations": action["loaded"],
        "attempted_seed_observations": action["attempted"],
        "accepted_seed_observations": action["accepted"],
        "pre_init_attempted_seeds": action["pre_init_attempted"],
        "post_init_attempted_seeds": action["post_init_attempted"],
        "post_init_accepted_seeds": action["post_init_accepted"],
        "events_overflowed": 0,
        "related_mappoint_overflowed": 0,
    }
    for field, expected in expected_counts.items():
        if int(row[field]) != expected:
            raise RuntimeError(f"evaluator/instrumentation mismatch {field}: {run}")
    if row.get("complete") != "1":
        raise RuntimeError(f"evaluator did not ingest complete instrumentation: {run}")
    for field in (
        "instrumentation_conservation_ok",
        "phase_conservation",
        "extractor_conservation",
        "accepted_conservation",
        "per_token_conservation",
        "valid_tokens",
        "mappoint_pointer_consistency",
        "mappoint_pointer_key_consistency",
        "atlas_snapshot_available",
    ):
        if row.get(field) != "1":
            raise RuntimeError(f"evaluator health flag failed {field}: {run}")
    if row.get("instrumentation_overflowed") != "0":
        raise RuntimeError(f"evaluator reports overflow: {run}")
    for field in ("ape_rmse_m", "ape_median_m", "ape_max_m", "rpe_rmse_m", "rpe_median_m", "rpe_max_m"):
        value = float(row[field])
        if not math.isfinite(value) or value < 0:
            raise RuntimeError(f"invalid descriptive proxy metric {field}: {run}")
    if summary.get("complete") is not True:
        raise RuntimeError(f"summary changed during evaluator audit: {run}")


def improvement(control: float, full_value: float) -> float:
    if control <= 0:
        raise RuntimeError("cannot compute descriptive improvement from nonpositive metric")
    return (control - full_value) / control * 100.0


def trajectory_timestamps_ns(path: Path) -> list[float]:
    timestamps: list[float] = []
    for line in path.read_text(encoding="ascii").splitlines():
        fields = line.split()
        if len(fields) != 8:
            continue
        timestamps.append(float(fields[0]) * 1e-9)
    if not timestamps:
        raise RuntimeError(f"empty trajectory timestamps: {path}")
    return timestamps


def association_support(
    trajectory_path: Path, proxy_timestamps: list[float]
) -> dict[str, Any]:
    """Reproduce evo 1.31.1 nearest-time association support semantics.

    The estimate is shorter than the CIRS proxy in this experiment.  evo's
    matching_time_indices iterates the shorter timestamps independently and
    permits reuse of a proxy index; the duplicate count is therefore an
    evidence caveat rather than an error.
    """
    estimate = trajectory_timestamps_ns(trajectory_path)
    proxy_indices: list[int] = []
    absolute_differences: list[float] = []
    for timestamp in estimate:
        index = bisect.bisect_left(proxy_timestamps, timestamp)
        candidates = [
            candidate
            for candidate in (index - 1, index)
            if 0 <= candidate < len(proxy_timestamps)
        ]
        if not candidates:
            continue
        best = min(candidates, key=lambda candidate: abs(proxy_timestamps[candidate] - timestamp))
        difference = abs(proxy_timestamps[best] - timestamp)
        if difference <= ASSOCIATION_S:
            proxy_indices.append(best)
            absolute_differences.append(difference)
    if not proxy_indices:
        raise RuntimeError(f"no odometry-proxy associations: {trajectory_path}")

    def spans(delta: int) -> list[float]:
        return [
            proxy_timestamps[proxy_indices[index + delta]]
            - proxy_timestamps[proxy_indices[index]]
            for index in range(len(proxy_indices) - delta)
        ]

    delta5 = spans(5)
    delta1 = spans(1)
    return {
        "trajectory_poses": len(estimate),
        "associated_poses": len(proxy_indices),
        "unique_proxy_samples": len(set(proxy_indices)),
        "reused_proxy_associations": len(proxy_indices) - len(set(proxy_indices)),
        "adjacent_reused_proxy_associations": sum(
            left == right for left, right in zip(proxy_indices, proxy_indices[1:])
        ),
        "max_abs_time_difference_s": max(absolute_differences),
        "delta5_pairs": len(delta5),
        "delta5_physical_span_min_s": min(delta5),
        "delta5_physical_span_median_s": statistics.median(delta5),
        "delta5_physical_span_max_s": max(delta5),
        "delta1_pairs": len(delta1),
        "delta1_physical_span_min_s": min(delta1),
        "delta1_physical_span_median_s": statistics.median(delta1),
        "delta1_physical_span_max_s": max(delta1),
    }


def support_signature(support: dict[str, Any]) -> str:
    return json.dumps(support, sort_keys=True, separators=(",", ":"))


def audit_formal_outcomes(smoke: dict[str, Any]) -> dict[str, Any]:
    """First formal-outcome access in this program."""
    require_sha(
        FORMAL_ROOT / "evaluation_reconstructed.csv",
        SHA["evaluation_reconstructed_delta5"],
        "delta5 reconstructed evaluation",
    )
    require_sha(
        FORMAL_ROOT / "evaluation_online.csv",
        SHA["evaluation_online_delta5"],
        "delta5 online evaluation",
    )
    require_sha(
        FORMAL_ROOT / "evaluation_reconstructed_delta1_sensitivity.csv",
        SHA["evaluation_reconstructed_delta1"],
        "delta1 reconstructed sensitivity evaluation",
    )
    require_sha(
        FORMAL_ROOT / "evaluation_online_delta1_sensitivity.csv",
        SHA["evaluation_online_delta1"],
        "delta1 online sensitivity evaluation",
    )
    evaluations: dict[str, dict[tuple[str, int], dict[str, str]]] = {}
    sensitivity_evaluations: dict[
        str, dict[tuple[str, int], dict[str, str]]
    ] = {}
    expected_grid = {(role, repeat) for role in ROLES for repeat in REPEATS}
    for kind in ("reconstructed", "online"):
        rows = read_csv(FORMAL_ROOT / f"evaluation_{kind}.csv")
        lookup = {(row["role"], int(row["repeat"])): row for row in rows}
        if len(rows) != 20 or len(lookup) != 20 or set(lookup) != expected_grid:
            raise RuntimeError(f"incomplete/duplicate {kind} evaluator grid")
        evaluations[kind] = lookup
        sensitivity_rows = read_csv(
            FORMAL_ROOT / f"evaluation_{kind}_delta1_sensitivity.csv"
        )
        sensitivity_lookup = {
            (row["role"], int(row["repeat"])): row
            for row in sensitivity_rows
        }
        if (
            len(sensitivity_rows) != 20
            or len(sensitivity_lookup) != 20
            or set(sensitivity_lookup) != expected_grid
        ):
            raise RuntimeError(
                f"incomplete/duplicate delta1 {kind} sensitivity grid"
            )
        sensitivity_evaluations[kind] = sensitivity_lookup

    action_signatures = {role: set() for role in ROLES}
    counter_signatures = {role: set() for role in ROLES}
    trajectory_hashes = {
        kind: {role: set() for role in ROLES}
        for kind in TRAJECTORY_PATTERNS
    }
    support_signatures = {
        kind: {role: set() for role in ROLES}
        for kind in ("reconstructed", "online")
    }
    support_by_kind_role: dict[str, dict[str, dict[str, Any]]] = {
        kind: {} for kind in ("reconstructed", "online")
    }
    proxy_timestamps = [
        float(line.split()[0])
        for line in (DATASET_ROOT / "groundtruth_tum.txt")
        .read_text(encoding="ascii")
        .splitlines()
        if line.strip() and not line.startswith("#")
    ]
    actions_by_repeat: dict[str, dict[str, dict[str, int]]] = {}
    snapshot_entries = 0
    snapshot_counts: Counter[int] = Counter()

    for repeat in REPEATS:
        repeat_actions: dict[str, dict[str, int]] = {}
        for role in ROLES:
            run = FORMAL_ROOT / f"{role}_r{repeat}"
            manifest = r08.parse_manifest(run / "run_manifest.txt")
            expected_manifest = {
                "role": role,
                "repeat": str(repeat),
                "role_order": FORMAL_ROLE_ORDER,
                "binary_sha256": SHA["orb_binary"],
                "liborbslam3_sha256": SHA["orb_library"],
                "runner_sha256": SHA["runner"],
                "config_sha256": SHA["orb_config"],
                "times_sha256": SHA["feature_times"],
                "cpu_affinity": "2",
                "scheduler_mode": "single_cpu",
                "synchronize_local_mapping": "1",
                "synchronize_loop_closing": "1",
                "deterministic_background_gate": "1",
                "disable_aslr": "1",
                "export_online_trajectory": "1",
                "seed_phase": "all",
                "seed_min_ok_frames": "0",
                "seed_audit_enabled": "1",
                "seed_audit_max_events": "131072",
                "external_lineage_min_quality": "0.9",
                "external_lineage_max_projection_error_px": "4",
                "external_lineage_max_descriptor_distance": "100",
            }
            for field, expected in expected_manifest.items():
                if manifest.get(field) != expected:
                    raise RuntimeError(
                        f"formal manifest mismatch {field}: {run}: {manifest.get(field)!r}"
                    )
            expected_seed = "" if role == "orb_only" else (
                SHA["drop_seeds"] if role == "drop" else SHA["full_seeds"]
            )
            if manifest.get("seed_sha256", "") != expected_seed:
                raise RuntimeError(f"formal seed hash mismatch: {run}")
            if role == "full_bridge_off":
                if manifest.get("external_lineage_bridge_enabled") != "0":
                    raise RuntimeError(f"bridge-off role enabled bridge: {run}")
            elif manifest.get("external_lineage_bridge_enabled") != "1":
                raise RuntimeError(f"formal bridge unexpectedly disabled: {run}")
            purge_scan_expected = "1" if role in {"full_unbounded", "full"} else "0"
            purge_enforce_expected = "1" if role == "full" else "0"
            if manifest.get("external_lineage_pre_kf_outlier_purge") != purge_scan_expected:
                raise RuntimeError(f"formal purge role mismatch: {run}")
            if manifest.get("external_lineage_pre_kf_outlier_purge_enforce") != purge_enforce_expected:
                raise RuntimeError(f"formal purge-enforce role mismatch: {run}")

            summary = json.loads(
                (run / "instrumentation/seed_summary.json").read_text(
                    encoding="utf-8"
                )
            )
            require_summary_health(summary, f"formal {role} r{repeat}")
            action = action_record(run, summary)
            action_signatures[role].add(action_signature(action))
            counter_signatures[role].add(summary_signature(summary))
            repeat_actions[role] = action

            expected_loaded = 0 if role in {"orb_only", "drop"} else 11
            if action["loaded"] != expected_loaded:
                raise RuntimeError(f"formal loaded-seed mismatch: {run}: {action}")
            if action["attempted"] > 0:
                require_pure_post_init(action, f"formal {role} r{repeat}")
            if role in {"orb_only", "drop"}:
                if action_signature(action) != (0,) * len(ACTION_FIELDS):
                    raise RuntimeError(f"control role has action: {run}: {action}")
            else:
                if (action["attempted"], action["accepted"]) != (11, 9):
                    raise RuntimeError(f"seeded attempt/accept contract changed: {run}")
            if role == "full_bridge_off":
                zero_fields = ("matches", "outliers", "pre_kf_observed", "pre_kf_purged", "scans")
                if any(action[field] != 0 for field in zero_fields):
                    raise RuntimeError(f"bridge-off role consumed lineage action: {run}")
            if role == "full_unbounded":
                required_positive = ("mappoint_lineages", "distinct_mappoints", "matches", "outliers", "pre_kf_observed")
                if any(action[field] <= 0 for field in required_positive):
                    raise RuntimeError(f"unbounded role lacks expected natural chain: {run}")
                if action["pre_kf_purged"] != 0 or action["scans"] <= 0:
                    raise RuntimeError(f"unbounded role unexpectedly purged: {run}")
            if role == "full":
                require_action_positive(action, f"formal full r{repeat}")
                if action_signature(action) != action_signature(smoke["actions"]["full"]):
                    raise RuntimeError(f"formal full does not reproduce frozen smoke: {run}")

            for kind, pattern in TRAJECTORY_PATTERNS.items():
                trajectory_path = r08.one_file(run, pattern)
                trajectory_hashes[kind][role].add(r08.sha256(trajectory_path))
                if kind in support_signatures:
                    support = association_support(
                        trajectory_path, proxy_timestamps
                    )
                    support_signatures[kind][role].add(
                        support_signature(support)
                    )
                    if repeat == 1:
                        support_by_kind_role[kind][role] = support
            count = r08.verify_snapshot(run / "provenance/snapshot_sha256.txt")
            snapshot_entries += count
            snapshot_counts[count] += 1
            for kind in ("reconstructed", "online"):
                verify_evaluation_row(
                    evaluations[kind][(role, repeat)],
                    kind,
                    role,
                    repeat,
                    run,
                    summary,
                    action,
                )
                verify_evaluation_row(
                    sensitivity_evaluations[kind][(role, repeat)],
                    kind,
                    role,
                    repeat,
                    run,
                    summary,
                    action,
                )
                main_row = evaluations[kind][(role, repeat)]
                sensitivity_row = sensitivity_evaluations[kind][(role, repeat)]
                if float(main_row["ape_rmse_m"]) != float(
                    sensitivity_row["ape_rmse_m"]
                ):
                    raise RuntimeError(
                        f"delta1 sensitivity changed APE: {kind}/{role}/r{repeat}"
                    )
                if int(main_row["output_poses"]) != int(
                    sensitivity_row["output_poses"]
                ):
                    raise RuntimeError(
                        f"delta1 sensitivity changed support: {kind}/{role}/r{repeat}"
                    )
        actions_by_repeat[str(repeat)] = repeat_actions

    action_signature_counts = {
        role: len(items) for role, items in action_signatures.items()
    }
    counter_signature_counts = {
        role: len(items) for role, items in counter_signatures.items()
    }
    if any(count != 1 for count in action_signature_counts.values()):
        raise RuntimeError(f"formal action nondeterminism: {action_signature_counts}")
    if any(count != 1 for count in counter_signature_counts.values()):
        raise RuntimeError(f"formal counter nondeterminism: {counter_signature_counts}")
    trajectory_hash_counts = {
        kind: {role: len(items) for role, items in roles.items()}
        for kind, roles in trajectory_hashes.items()
    }
    for kind, roles in trajectory_hash_counts.items():
        if any(count != 1 for count in roles.values()):
            raise RuntimeError(f"formal {kind} trajectory nondeterminism: {roles}")
    support_signature_counts = {
        kind: {role: len(items) for role, items in roles.items()}
        for kind, roles in support_signatures.items()
    }
    for kind, roles in support_signature_counts.items():
        if any(count != 1 for count in roles.values()):
            raise RuntimeError(f"formal {kind} support nondeterminism: {roles}")
    expected_support = {
        "orb_only": (43, 28, 15, 15, 38, 42),
        "drop": (43, 28, 15, 15, 38, 42),
        "full_bridge_off": (57, 42, 15, 15, 52, 56),
        "full_unbounded": (62, 47, 15, 15, 57, 61),
        "full": (62, 47, 15, 15, 57, 61),
    }
    for role, expected in expected_support.items():
        reconstructed_support = support_by_kind_role["reconstructed"][role]
        online_support = support_by_kind_role["online"][role]
        if reconstructed_support != online_support:
            raise RuntimeError(f"reconstructed/online support differs: {role}")
        observed = (
            reconstructed_support["associated_poses"],
            reconstructed_support["unique_proxy_samples"],
            reconstructed_support["reused_proxy_associations"],
            reconstructed_support["adjacent_reused_proxy_associations"],
            reconstructed_support["delta5_pairs"],
            reconstructed_support["delta1_pairs"],
        )
        if observed != expected:
            raise RuntimeError(
                f"role-dependent proxy support changed: {role}: {observed}"
            )
        if (
            reconstructed_support["trajectory_poses"]
            != reconstructed_support["associated_poses"]
        ):
            raise RuntimeError(f"unassociated trajectory pose: {role}")
        if reconstructed_support["max_abs_time_difference_s"] > ASSOCIATION_S:
            raise RuntimeError(f"association tolerance exceeded: {role}")
        if reconstructed_support["delta5_physical_span_min_s"] != 0.0:
            raise RuntimeError(f"expected duplicated delta5 proxy support: {role}")
        if reconstructed_support["delta1_physical_span_min_s"] != 0.0:
            raise RuntimeError(f"expected duplicated delta1 proxy support: {role}")
    if snapshot_entries != 576 or snapshot_counts != Counter({29: 16, 28: 4}):
        raise RuntimeError(
            f"unexpected formal snapshot contract: {snapshot_entries}, {snapshot_counts}"
        )

    metrics: dict[str, dict[str, dict[str, float]]] = {}
    output_poses: dict[str, dict[str, int]] = {}
    for kind, lookup in evaluations.items():
        metrics[kind] = {}
        output_poses[kind] = {}
        for role in ROLES:
            rows = [lookup[(role, repeat)] for repeat in REPEATS]
            ape = {float(row["ape_rmse_m"]) for row in rows}
            rpe = {float(row["rpe_rmse_m"]) for row in rows}
            poses = {int(row["output_poses"]) for row in rows}
            if len(ape) != 1 or len(rpe) != 1 or len(poses) != 1:
                raise RuntimeError(f"formal descriptive metric nondeterminism: {kind}/{role}")
            metrics[kind][role] = {"ape": ape.pop(), "rpe": rpe.pop()}
            output_poses[kind][role] = poses.pop()

    sensitivity_metrics: dict[str, dict[str, dict[str, float]]] = {}
    expected_delta1_rpe = {
        "reconstructed": {
            "orb_only": 0.061071,
            "drop": 0.061071,
            "full_bridge_off": 0.071060,
            "full_unbounded": 0.092469,
            "full": 0.092826,
        },
        "online": {
            "orb_only": 0.072369,
            "drop": 0.072369,
            "full_bridge_off": 0.069333,
            "full_unbounded": 0.094319,
            "full": 0.094411,
        },
    }
    for kind, lookup in sensitivity_evaluations.items():
        sensitivity_metrics[kind] = {}
        for role in ROLES:
            rows = [lookup[(role, repeat)] for repeat in REPEATS]
            ape = {float(row["ape_rmse_m"]) for row in rows}
            rpe = {float(row["rpe_rmse_m"]) for row in rows}
            if len(ape) != 1 or len(rpe) != 1:
                raise RuntimeError(
                    f"delta1 sensitivity nondeterminism: {kind}/{role}"
                )
            observed_ape = ape.pop()
            observed_rpe = rpe.pop()
            if observed_ape != metrics[kind][role]["ape"]:
                raise RuntimeError(f"delta1 APE mismatch: {kind}/{role}")
            if observed_rpe != expected_delta1_rpe[kind][role]:
                raise RuntimeError(f"delta1 RPE mismatch: {kind}/{role}")
            sensitivity_metrics[kind][role] = {
                "ape": observed_ape,
                "rpe": observed_rpe,
            }

    improvements: dict[str, dict[str, float]] = {}
    improvement_counts: dict[str, int] = {}
    for control in ("orb_only", "drop", "full_bridge_off", "full_unbounded"):
        changes: dict[str, float] = {}
        for kind in ("reconstructed", "online"):
            for metric in ("ape", "rpe"):
                changes[f"{kind}_{metric}"] = improvement(
                    metrics[kind][control][metric], metrics[kind]["full"][metric]
                )
        improvements[control] = changes
        improvement_counts[control] = sum(value > 0 for value in changes.values())

    return {
        "formal_runs": 20,
        "formal_runs_ok": 20,
        "pure_post_init": True,
        "action_positive": True,
        "formal_role_order": FORMAL_ROLE_ORDER,
        "repeat4_order_swapped": False,
        "action_signature_counts": action_signature_counts,
        "counter_signature_counts": counter_signature_counts,
        "trajectory_hash_counts": trajectory_hash_counts,
        "support_signature_counts": support_signature_counts,
        "association_support": support_by_kind_role["reconstructed"],
        "role_dependent_support": True,
        "common_support": False,
        "proxy_sample_reuse_present": True,
        "actions_by_repeat": actions_by_repeat,
        "action": actions_by_repeat["1"],
        "metrics": metrics,
        "delta1_sensitivity_metrics": sensitivity_metrics,
        "output_poses": output_poses,
        "improvements": improvements,
        "improvement_counts": improvement_counts,
        "snapshot_manifests": 20,
        "snapshot_manifests_verified": 20,
        "snapshot_entries": snapshot_entries,
        "snapshot_entries_verified": snapshot_entries,
        "reference_kind": REFERENCE_KIND,
        "reference_independent": False,
        "metric_scope": METRIC_SCOPE,
        "counts_as_metric_accuracy": False,
        "counts_as_project_strict": False,
        "counts_as_all_control_strict": False,
        "counts_as_no_harm": False,
        "association_s": ASSOCIATION_S,
        "rpe_delta_associated_poses": RPE_DELTA_ASSOCIATED_POSES,
        "evo_version": EVO_VERSION,
        "root": str(FORMAL_ROOT),
    }


def roster_row(formal: dict[str, Any]) -> dict[str, Any]:
    full = formal["action"]["full"]
    return {
        "window_id": CONFIG["window_id"],
        "dataset": CONFIG["dataset"],
        "sequence": CONFIG["sequence"],
        "window": CONFIG["window"],
        "level": CONFIG["level"],
        "independent_window": "true",
        "primary_selector": CONFIG["selector_name"],
        "accepted_post_init": f"{full['post_init_accepted']}/{full['post_init_attempted']}",
        "seed_lineages_with_mappoint": full["mappoint_lineages"],
        "assisted_matches": full["matches"],
        "assisted_outliers": full["outliers"],
        "pre_kf_purged": f"{full['pre_kf_purged']}/{full['pre_kf_observed']}",
        "texture_profile": CONFIG["texture_profile"],
        "base_klt_profile": CONFIG["base_klt_profile"],
        "operational_low_texture": "true",
        "sparse_base_klt_low_texture": "true",
        "source_report": REPORT_RELATIVE,
        "formal_root": str(FORMAL_ROOT),
    }


def format_metric(formal: dict[str, Any], role: str, kind: str) -> str:
    metric = formal["metrics"][kind][role]
    return f"{metric['ape']:.6f} / {metric['rpe']:.6f}"


def formal_summary(formal: dict[str, Any], source: dict[str, Any]) -> dict[str, Any]:
    full = formal["action"]["full"]
    unbounded = formal["action"]["full_unbounded"]
    texture = source["texture"]
    counts = formal["improvement_counts"]
    return {
        "window_id": CONFIG["window_id"],
        "selector": CONFIG["selector_name"],
        "level": CONFIG["level"],
        "formal_runs_ok": "20/20",
        "post_init_accepted": f"{full['post_init_accepted']}/{full['post_init_attempted']}",
        "map_point_lineages": full["mappoint_lineages"],
        "distinct_mappoints": full["distinct_mappoints"],
        "assisted_matches": full["matches"],
        "assisted_outliers": full["outliers"],
        "pre_kf_purged": f"{full['pre_kf_purged']}/{full['pre_kf_observed']}",
        "pre_kf_scans": full["scans"],
        "unbounded_matches": unbounded["matches"],
        "unbounded_outliers": unbounded["outliers"],
        "unbounded_pre_kf_observed": unbounded["pre_kf_observed"],
        "unbounded_pre_kf_purged": unbounded["pre_kf_purged"],
        "reference_kind": REFERENCE_KIND,
        "reference_independent": "false",
        "metric_scope": METRIC_SCOPE,
        "counts_as_metric_accuracy": "false",
        "counts_as_project_strict": "false",
        "counts_as_all_control_strict": "false",
        "counts_as_no_harm": "false",
        "reconstructed_native_proxy_ape_m": formal["metrics"]["reconstructed"]["orb_only"]["ape"],
        "reconstructed_native_proxy_rpe_m": formal["metrics"]["reconstructed"]["orb_only"]["rpe"],
        "reconstructed_full_proxy_ape_m": formal["metrics"]["reconstructed"]["full"]["ape"],
        "reconstructed_full_proxy_rpe_m": formal["metrics"]["reconstructed"]["full"]["rpe"],
        "online_native_proxy_ape_m": formal["metrics"]["online"]["orb_only"]["ape"],
        "online_native_proxy_rpe_m": formal["metrics"]["online"]["orb_only"]["rpe"],
        "online_full_proxy_ape_m": formal["metrics"]["online"]["full"]["ape"],
        "online_full_proxy_rpe_m": formal["metrics"]["online"]["full"]["rpe"],
        "full_vs_native_descriptive_improvements": f"{counts['orb_only']}/4",
        "full_vs_drop_descriptive_improvements": f"{counts['drop']}/4",
        "full_vs_bridge_off_descriptive_improvements": f"{counts['full_bridge_off']}/4",
        "full_vs_unbounded_descriptive_improvements": f"{counts['full_unbounded']}/4",
        "association_s": ASSOCIATION_S,
        "rpe_delta_associated_poses": RPE_DELTA_ASSOCIATED_POSES,
        "role_dependent_support": "true",
        "common_support": "false",
        "proxy_sample_reuse_present": "true",
        "native_associated_poses": formal["association_support"]["orb_only"]["associated_poses"],
        "native_unique_proxy_samples": formal["association_support"]["orb_only"]["unique_proxy_samples"],
        "native_delta5_pairs": formal["association_support"]["orb_only"]["delta5_pairs"],
        "full_associated_poses": formal["association_support"]["full"]["associated_poses"],
        "full_unique_proxy_samples": formal["association_support"]["full"]["unique_proxy_samples"],
        "full_reused_proxy_associations": formal["association_support"]["full"]["reused_proxy_associations"],
        "full_delta5_pairs": formal["association_support"]["full"]["delta5_pairs"],
        "full_delta5_physical_span_median_s": f"{formal['association_support']['full']['delta5_physical_span_median_s']:.9f}",
        "delta1_sensitivity_scope": "irregular_associated-pose_sensitivity_not_1s",
        "reconstructed_full_delta1_sensitivity_rpe_m": formal["delta1_sensitivity_metrics"]["reconstructed"]["full"]["rpe"],
        "online_full_delta1_sensitivity_rpe_m": formal["delta1_sensitivity_metrics"]["online"]["full"]["rpe"],
        "texture_profile": CONFIG["texture_profile"],
        "base_track_min": f"{texture['track_min']:.0f}",
        "base_track_median": f"{texture['track_median']:.0f}",
        "base_track_mean": f"{texture['track_mean']:.6f}",
        "base_track_max": f"{texture['track_max']:.0f}",
        "base_grid_min": f"{texture['grid_min']:.6f}",
        "base_grid_mean": f"{texture['grid_mean']:.6f}",
        "base_grid_max": f"{texture['grid_max']:.6f}",
        "dropout_median": f"{texture['dropout_median']:.6f}",
        "dropout_mean": f"{texture['dropout_mean']:.6f}",
        "dropout_max": f"{texture['dropout_max']:.6f}",
        "degradation_mean": f"{texture['degradation_mean']:.6f}",
        "degradation_max": f"{texture['degradation_max']:.6f}",
        "sparse_base_klt": "true",
        "formal_root": str(FORMAL_ROOT),
    }


def build_report(
    formal: dict[str, Any], source: dict[str, Any], smoke: dict[str, Any],
    counts: dict[str, int]
) -> str:
    action = formal["action"]
    full = action["full"]
    unbounded = action["full_unbounded"]
    texture = source["texture"]
    improvements = formal["improvement_counts"]
    lines = [
        "# ORB-SLAM3 v23 CIRS s480,d30 evidence closure R13",
        "",
        "Date: 2026-08-08",
        "",
        "## Decision",
        "",
        "CIRS Cala-Viuda `s480,d30` is a new independent pure-post-init",
        "mechanism/action-positive cross-dataset window.  It is the first rostered",
        "action-positive whose current-B1 base KLT is clearly sparse below the",
        "350-feature cap in every frame.",
        "",
        f"The evaluation reference is `{REFERENCE_KIND}` from `{REFERENCE_TOPIC}`.",
        "It is not independent ground truth.  All APE/RPE values below are",
        "descriptive proxy alignment only; they do not support metric accuracy,",
        "trajectory-positive, no-harm, project-strict, or all-control-strict claims.",
        "",
        "No selector, bridge, dose, phase, binary, library, runner, camera,",
        "reference, association, or RPE-delta threshold was changed after outcome.",
        "",
        "## Frozen formal validation",
        "",
        "All `20/20` formal runs have status `ok`. R1-R4 use the same frozen",
        f"`{FORMAL_ROLE_ORDER}` order. Each role has one complete counter/action,",
        "reconstructed, online, and keyframe signature across four repeats.",
        f"All 20 provenance manifests and all `{formal['snapshot_entries']}/{formal['snapshot_entries']}`",
        "listed entries pass SHA-256 verification; all conservation, token,",
        "MapPoint-pointer, atlas, and overflow checks pass.",
        "",
        "| Role | Post-init accepted | MP lineages / MPs | Matches | Outliers | pre-KF observed / purged | Scans |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
        f"| Bridge off | {action['full_bridge_off']['post_init_accepted']}/{action['full_bridge_off']['post_init_attempted']} | {action['full_bridge_off']['mappoint_lineages']} / {action['full_bridge_off']['distinct_mappoints']} | {action['full_bridge_off']['matches']} | {action['full_bridge_off']['outliers']} | {action['full_bridge_off']['pre_kf_observed']} / {action['full_bridge_off']['pre_kf_purged']} | {action['full_bridge_off']['scans']} |",
        f"| Unbounded | {unbounded['post_init_accepted']}/{unbounded['post_init_attempted']} | {unbounded['mappoint_lineages']} / {unbounded['distinct_mappoints']} | {unbounded['matches']} | {unbounded['outliers']} | {unbounded['pre_kf_observed']} / {unbounded['pre_kf_purged']} | {unbounded['scans']} |",
        f"| Frozen v23 | {full['post_init_accepted']}/{full['post_init_attempted']} | {full['mappoint_lineages']} / {full['distinct_mappoints']} | {full['matches']} | {full['outliers']} | {full['pre_kf_observed']} / {full['pre_kf_purged']} | {full['scans']} |",
        "",
        "The full arm exactly reproduces the discovery-smoke action signature in",
        "all four repeats: 11/11 attempts are post-init, 9 are accepted, one",
        "lineage forms two MapPoints, five assisted matches are consumed, one",
        "natural assisted outlier is observed, and enforced purge removes 1/1.",
        "",
        "## Descriptive odometry-proxy alignment",
        "",
        f"Association is `{ASSOCIATION_S:.2f} s`; RPE delta is",
        f"`{RPE_DELTA_ASSOCIATED_POSES}` associated poses. Reference independence is `false`.",
        "",
        "The role support sets are not common: native/drop have 43 associated",
        "poses, bridge-off has 57, and unbounded/full have 62. evo 1.31.1",
        "matches each shorter-trajectory timestamp to its nearest proxy timestamp",
        "and permits proxy-sample reuse. Every role has 15 reused (also adjacent)",
        "proxy associations. Thus even role-to-role descriptive comparisons mix",
        "different supports and duplicated proxy samples.",
        "",
        "| Role | Associated / unique proxy | Reused | |dt| max (s) | delta5 pairs | delta5 physical span min / median / max (s) |",
        "| --- | ---: | ---: | ---: | ---: | --- |",
        f"| Native / drop | {formal['association_support']['orb_only']['associated_poses']} / {formal['association_support']['orb_only']['unique_proxy_samples']} | {formal['association_support']['orb_only']['reused_proxy_associations']} | {formal['association_support']['orb_only']['max_abs_time_difference_s']:.6f} | {formal['association_support']['orb_only']['delta5_pairs']} | {formal['association_support']['orb_only']['delta5_physical_span_min_s']:.6f} / {formal['association_support']['orb_only']['delta5_physical_span_median_s']:.6f} / {formal['association_support']['orb_only']['delta5_physical_span_max_s']:.6f} |",
        f"| Bridge off | {formal['association_support']['full_bridge_off']['associated_poses']} / {formal['association_support']['full_bridge_off']['unique_proxy_samples']} | {formal['association_support']['full_bridge_off']['reused_proxy_associations']} | {formal['association_support']['full_bridge_off']['max_abs_time_difference_s']:.6f} | {formal['association_support']['full_bridge_off']['delta5_pairs']} | {formal['association_support']['full_bridge_off']['delta5_physical_span_min_s']:.6f} / {formal['association_support']['full_bridge_off']['delta5_physical_span_median_s']:.6f} / {formal['association_support']['full_bridge_off']['delta5_physical_span_max_s']:.6f} |",
        f"| Unbounded / full | {formal['association_support']['full']['associated_poses']} / {formal['association_support']['full']['unique_proxy_samples']} | {formal['association_support']['full']['reused_proxy_associations']} | {formal['association_support']['full']['max_abs_time_difference_s']:.6f} | {formal['association_support']['full']['delta5_pairs']} | {formal['association_support']['full']['delta5_physical_span_min_s']:.6f} / {formal['association_support']['full']['delta5_physical_span_median_s']:.6f} / {formal['association_support']['full']['delta5_physical_span_max_s']:.6f} |",
        "",
        "| Role | Reconstructed proxy APE / RPE | Online proxy APE / RPE |",
        "| --- | --- | --- |",
        f"| Native ORB | `{format_metric(formal, 'orb_only', 'reconstructed')}` | `{format_metric(formal, 'orb_only', 'online')}` |",
        f"| Empty drop | `{format_metric(formal, 'drop', 'reconstructed')}` | `{format_metric(formal, 'drop', 'online')}` |",
        f"| Bridge off | `{format_metric(formal, 'full_bridge_off', 'reconstructed')}` | `{format_metric(formal, 'full_bridge_off', 'online')}` |",
        f"| Unbounded | `{format_metric(formal, 'full_unbounded', 'reconstructed')}` | `{format_metric(formal, 'full_unbounded', 'online')}` |",
        f"| Frozen v23 | `{format_metric(formal, 'full', 'reconstructed')}` | `{format_metric(formal, 'full', 'online')}` |",
        "",
        "Descriptive full-arm improvement counts are",
        f"native `{improvements['orb_only']}/4`, drop `{improvements['drop']}/4`,",
        f"bridge-off `{improvements['full_bridge_off']}/4`, and unbounded",
        f"`{improvements['full_unbounded']}/4`. These counts are not entered into",
        "any strict or metric-accuracy denominator.",
        "",
        "The predeclared delta1 associated-pose sensitivity is not a 1-second",
        "metric. Its physical spans are irregular (median about 0.163-0.200 s,",
        "minimum 0 because of proxy reuse), and it uses the same role-dependent",
        "supports. It changes only the RPE delta; APE is identical to delta5.",
        "",
        "| Role | Reconstructed delta1 proxy RPE | Online delta1 proxy RPE |",
        "| --- | ---: | ---: |",
        f"| Native / drop | {formal['delta1_sensitivity_metrics']['reconstructed']['orb_only']['rpe']:.6f} | {formal['delta1_sensitivity_metrics']['online']['orb_only']['rpe']:.6f} |",
        f"| Bridge off | {formal['delta1_sensitivity_metrics']['reconstructed']['full_bridge_off']['rpe']:.6f} | {formal['delta1_sensitivity_metrics']['online']['full_bridge_off']['rpe']:.6f} |",
        f"| Unbounded | {formal['delta1_sensitivity_metrics']['reconstructed']['full_unbounded']['rpe']:.6f} | {formal['delta1_sensitivity_metrics']['online']['full_unbounded']['rpe']:.6f} |",
        f"| Frozen v23 | {formal['delta1_sensitivity_metrics']['reconstructed']['full']['rpe']:.6f} | {formal['delta1_sensitivity_metrics']['online']['full']['rpe']:.6f} |",
        "",
        "## Frozen source and exact-drop contract",
        "",
        "The freshly rebuilt current-B1 bag is byte-identical to the frozen base",
        f"(`{SHA['base_bag']}`): 149 frames, 33,977 native observations, zero",
        "learned/high-ID contamination, and a passing native-q/B1 guard contract.",
        "The frozen sidecar triggers at frames 8, 20, and 32 for",
        "`low_base_tracks+identity_churn`, producing 150 candidates and 754",
        "sidecar observations. The unchanged selector exports three IDs, 11",
        "observations over nine frames, with zero timestamp error and finite q>=0.9.",
        "",
        "The independent exact whole-lineage audit passes byte-for-byte feature",
        "payload, timestamps, message topology, non-feature messages, and lineage",
        "removal. It removes lineage lengths 1/1/9 (11 observations total) while",
        "retaining all 33,977 native observations in the drop control.",
        "",
        "The PREP provenance stores a snapshot of the child CIRS config but does",
        "not flatten its inherited parents. This bundle therefore anchors the full",
        "seven-file live inheritance chain by exact path and SHA-256 in",
        "`provenance.csv`; that distinction is retained as a provenance caveat.",
        "",
        "## Texture and denominator",
        "",
        f"Current-B1 tracks min/median/mean/max are `{texture['track_min']:.0f} / {texture['track_median']:.0f} / {texture['track_mean']:.6f} / {texture['track_max']:.0f}`;",
        "all `149/149` frames are below the 350-feature cap. Grid coverage is",
        "`1.0` in all 149 frames, so this is explicitly high-grid, not low-grid.",
        f"Dropout median/mean/max are `{texture['dropout_median']:.6f} / {texture['dropout_mean']:.6f} / {texture['dropout_max']:.6f}`;",
        f"degradation mean/max are `{texture['degradation_mean']:.6f} / {texture['degradation_max']:.6f}`.",
        "The operational category is entered because of low base-track count plus",
        "identity churn, not because of low grid coverage.",
        "",
        f"- mechanism/action-positive: `{counts['action_positive']}`",
        f"- project strict: `{counts['project_strict']}`",
        f"- all-control repeatwise strict: `{counts['all_control_strict']}`",
        f"- operational degraded/planar/low-grid OR-category: `{counts['operational_low_grid']}/{counts['action_positive']}`",
        f"- operational category among project strict: `{counts['strict_operational_low_grid']}/{counts['project_strict']}`",
        f"- sparse base-KLT positives: `{counts['sparse_base_klt']}/{counts['action_positive']}`",
        "",
        "## Claim boundary",
        "",
        "- Count CIRS `s480,d30` once as development mechanism/action evidence.",
        "- Count it once as sparse-base-KLT and operational degraded/identity-churn evidence.",
        "- Do not call its high-grid texture low-grid.",
        "- Do not count proxy APE/RPE toward project-strict, all-control-strict,",
        "  no-harm, held-out accuracy, or metric-accuracy evidence.",
        "- The window is not untouched confirmatory evidence.",
        "",
        f"Formal root: `{FORMAL_ROOT}`",
        f"Smoke root: `{SMOKE_ROOT}`",
        f"Exact-drop audit: `{EXACT_DROP_PATH}`",
        f"Reference file: `{DATASET_ROOT / 'groundtruth_tum.txt'}`",
        "",
    ]
    return "\n".join(lines)


def provenance_artifacts() -> list[tuple[str, Path]]:
    artifacts: list[tuple[str, Path]] = [
        ("analysis_builder", Path(__file__).resolve()),
        ("analysis_core_r08", WORKSPACE / "scripts/analyze_orbslam3_v23_continued_search_r08.py"),
        ("roster_counter_r09", WORKSPACE / "scripts/analyze_orbslam3_v23_a01_r09.py"),
        ("feature_bag_auditor_r11", WORKSPACE / "scripts/analyze_orbslam3_v23_afrl_cemetery_fr_r11.py"),
        ("prior_roster", PRIOR_ROSTER),
        ("raw_bag", RAW_BAG),
        ("legacy_frozen_base", LEGACY_BASE_BAG),
        ("current_b1_bag", CURRENT_B1_ROOT / "features.bag"),
        ("current_b1_metrics", CURRENT_B1_ROOT / "frontend_metrics.csv"),
        ("current_b1_native_q", CURRENT_B1_ROOT / "features.bag.quality-contract.json"),
        ("current_b1_guard", CURRENT_B1_ROOT / "b1_guard_decision.json"),
        ("current_b1_camera", CURRENT_B1_ROOT / "cirs_cam0_pinhole.yaml"),
        ("orb_config", ORB_CONFIG),
        ("orb_binary", ORB_BINARY),
        ("orb_library", ORB_LIBRARY),
        ("runner", WORKSPACE / "scripts/run_orbslam3_seeded_triplet.sh"),
        ("evaluator", WORKSPACE / "scripts/evaluate_orbslam3_seeded_runs.py"),
        ("exact_drop_auditor", WORKSPACE / "scripts/audit_whole_lineage_exact_drop_v1.py"),
        ("sidecar_generator_frozen", CLEAN_ROOT / "provenance/xfeat_seed_sidecar_node_9afc.py"),
        ("sidecar_config_snapshot", CLEAN_ROOT / "provenance/cirs_xfeat_seedchain_klt_probe_snapshot.yaml"),
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
        ("dataset_odometry_proxy", DATASET_ROOT / "groundtruth_tum.txt"),
        ("evaluation_reconstructed", FORMAL_ROOT / "evaluation_reconstructed.csv"),
        ("evaluation_online", FORMAL_ROOT / "evaluation_online.csv"),
        ("evaluation_reconstructed_delta1_sensitivity", FORMAL_ROOT / "evaluation_reconstructed_delta1_sensitivity.csv"),
        ("evaluation_online_delta1_sensitivity", FORMAL_ROOT / "evaluation_online_delta1_sensitivity.csv"),
    ]
    for name, path, _, _ in SIDECAR_CONFIG_CHAIN:
        artifacts.append((f"sidecar_config_chain_{name}", path))
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
    for repeat in REPEATS:
        for role in ROLES:
            run = FORMAL_ROOT / f"{role}_r{repeat}"
            prefix = f"formal_{role}_r{repeat}"
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
                    "expected_formal_role_order": FORMAL_ROLE_ORDER,
                    "expected_formal_grid": "5 roles x 4 repeats = 20",
                    "formal_root_not_read": str(FORMAL_ROOT),
                    "reference_kind": REFERENCE_KIND,
                    "metric_scope": METRIC_SCOPE,
                    "counts_as_project_strict": False,
                    "counts_as_metric_accuracy": False,
                    "expected_post_closure_counts": EXPECTED_COUNTS,
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 0

    output = args.output.resolve()
    if output.exists() and not args.replace:
        raise SystemExit(f"output exists; pass --replace: {output}")

    # This is deliberately the first formal-outcome access in the program.
    formal = audit_formal_outcomes(smoke)
    roster = prior + [roster_row(formal)]
    if len(roster) != 20 or len({row["window_id"] for row in roster}) != 20:
        raise RuntimeError("R13 roster is not 20 unique windows")
    counts = r09.roster_counts(roster)
    if counts != EXPECTED_COUNTS:
        raise RuntimeError(f"unexpected R13 roster counts: {counts}")

    output.parent.mkdir(parents=True, exist_ok=True)
    temp = Path(tempfile.mkdtemp(prefix=f".{output.name}.", dir=output.parent))
    try:
        write_csv(temp / "formal_summary.csv", [formal_summary(formal, source)])
        write_csv(temp / "window_roster.csv", roster)
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
        write_csv(temp / "provenance.csv", provenance_rows)
        validation = {
            "schema_version": 7,
            "date": "2026-08-08",
            "added_windows": 1,
            "roster_rows": len(roster),
            "roster_unique_windows": len({row["window_id"] for row in roster}),
            "updated_counts": counts,
            "snapshot_manifests": 23,
            "snapshot_manifests_verified": 23,
            "snapshot_entries": formal["snapshot_entries"] + smoke["snapshot_entries"],
            "snapshot_entries_verified": formal["snapshot_entries"] + smoke["snapshot_entries"],
            "source_contract": source,
            "smoke_contract": smoke,
            "reference_contract": {
                "kind": REFERENCE_KIND,
                "topic": REFERENCE_TOPIC,
                "independent": False,
                "metric_scope": METRIC_SCOPE,
                "counts_as_metric_accuracy": False,
                "counts_as_project_strict": False,
                "counts_as_all_control_strict": False,
                "counts_as_no_harm": False,
                "association_s": ASSOCIATION_S,
                "rpe_delta_associated_poses": RPE_DELTA_ASSOCIATED_POSES,
                "evaluator_sha256": SHA["evaluator"],
                "evo_version": EVO_VERSION,
                "role_dependent_support": True,
                "common_support": False,
                "proxy_sample_reuse_present": True,
                "evo_sync_semantics": (
                    "nearest proxy sample per shorter-trajectory timestamp; "
                    "proxy index reuse permitted"
                ),
                "delta5_evaluation_sha256": {
                    "reconstructed": SHA["evaluation_reconstructed_delta5"],
                    "online": SHA["evaluation_online_delta5"],
                },
                "delta1_sensitivity_evaluation_sha256": {
                    "reconstructed": SHA["evaluation_reconstructed_delta1"],
                    "online": SHA["evaluation_online_delta1"],
                },
            },
            "windows": {
                CONFIG["window_id"]: {
                    "action_positive": True,
                    "pure_post_init": True,
                    "level": CONFIG["level"],
                    "project_strict": False,
                    "all_control_strict": False,
                    "no_harm": False,
                    "metric_accuracy": False,
                    "reference_independent": False,
                    "formal_role_order": FORMAL_ROLE_ORDER,
                    "formal_runs": 20,
                    "formal_runs_ok": 20,
                    "repeat4_order_swapped": False,
                    "action_signature_counts": formal["action_signature_counts"],
                    "counter_signature_counts": formal["counter_signature_counts"],
                    "trajectory_hash_counts": formal["trajectory_hash_counts"],
                    "support_signature_counts": formal["support_signature_counts"],
                    "association_support": formal["association_support"],
                    "role_dependent_support": True,
                    "common_support": False,
                    "proxy_sample_reuse_present": True,
                    "formal_actions_by_repeat": formal["actions_by_repeat"],
                    "descriptive_proxy_improvement_counts": formal["improvement_counts"],
                    "delta1_sensitivity_metrics": formal["delta1_sensitivity_metrics"],
                    "operational_low_texture": True,
                    "operational_basis": "low_base_tracks+identity_churn",
                    "low_grid": False,
                    "sparse_base_klt": True,
                    "texture": source["texture"],
                    "snapshot_manifests": 20,
                    "snapshot_manifests_verified": 20,
                    "snapshot_entries": formal["snapshot_entries"],
                    "snapshot_entries_verified": formal["snapshot_entries"],
                    "formal_root": str(FORMAL_ROOT),
                }
            },
        }
        (temp / "validation_summary.json").write_text(
            json.dumps(validation, indent=2, sort_keys=True) + "\n",
            encoding="ascii",
        )
        (temp / "analysis-report.md").write_text(
            build_report(formal, source, smoke, counts), encoding="ascii"
        )
        if output.exists():
            shutil.rmtree(output)
        os.replace(temp, output)
    except Exception:
        shutil.rmtree(temp, ignore_errors=True)
        raise
    print(f"wrote validated R13 CIRS s480,d30 bundle to {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
