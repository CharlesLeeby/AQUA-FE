#!/usr/bin/env python3
"""One-shot strict70 A02 full-history controller over the sealed HFNet stack.

The official learned system receives source cameras 1..6300 sequentially.
Source camera 0 is honestly trimmed because it has no shifted-IMU predecessor;
no synthetic IMU sample is introduced.  Source cameras 4500..6300 form this
external producer's 1801-camera score window.  A usable producer result needs
at least ceil(0.70 * 1801) = 1261 score poses and a contiguous run of at least
1261 score poses, plus every inherited execution and immutability gate.

The existing adopted GFTT/XFeat evidence scores source cameras 5400..6300 and
uses feed/history 4500..6300.  Thus 5400..6300 is only possible common score
support, not a fair accuracy comparison: HFNet uses history 1..6300.  Accuracy
head-to-head remains blocked until all arms share one frozen history.  The old
v1 prepared-only namespace is pinned as abandoned and is never reused.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from typing import Any, Dict, List, Mapping, Optional, Sequence


ROOT = Path(__file__).resolve().parents[1]
WRAPPER = Path(__file__).resolve()
REUSED_V1_CONTROLLER = ROOT / "scripts/run_hfnet_v6_a02_0001_6300_score_4500_6300_v1.py"
RUNNER_TEST = ROOT / "scripts/tests/test_run_hfnet_v6_a02_0001_6300_score_4500_6300_strict70_v2.py"
STRICT70_PROTOCOL = ROOT / "papers/hfnet_v6_a02_0001_6300_score_4500_6300_strict70_protocol_v2.json"
V1_ABANDONMENT_RECEIPT = ROOT / "papers/hfnet_v6_a02_0001_6300_v1_prepared_abandoned_gate_correction_v1.json"
DEPENDENCY_V2_SUPERSESSION_RECEIPT = (
    ROOT / "papers/hfnet_v6_a02_0001_6300_dependency_inventory_v2_superseded_preprepare_v1.json"
)


def _load(path: Path):
    specification = importlib.util.spec_from_file_location("hfnet_v6_a02_reused_v1_controller", str(path))
    if specification is None or specification.loader is None:
        raise RuntimeError("REUSED_A02_V1_CONTROLLER_IMPORT_FAILED")
    module = importlib.util.module_from_spec(specification)
    sys.modules[specification.name] = module
    specification.loader.exec_module(module)
    return module


base = _load(REUSED_V1_CONTROLLER)
engine = base.engine

# These must remain absent at every v2 profile, lock, check, and post-run audit.
V1_FORBIDDEN_TERMINAL_PATHS = {
    "execution_lock": base.EXECUTION_LOCK,
    "process_start_claim": base.ATTEMPT / "process_start_claim.json",
    "run_result": base.ATTEMPT / "run_result.json",
    "result_directory": base.ATTEMPT / "result",
}

REUSED_V1_CONTROLLER_EXPECTED = {
    "size_bytes": 17_260,
    "sha256": "0a3969a8471078ceb5724d14f7f33af0486741035bce49786618ad8114b4a258",
}
STRICT70_PROTOCOL_EXPECTED = {
    "size_bytes": 5_429,
    "sha256": "7647db1a251480534b393bb3547f7fcb4cfa5e7209bcf64f8d1faa3ff972521b",
}
V1_ABANDONMENT_RECEIPT_EXPECTED = {
    "size_bytes": 3_547,
    "sha256": "918f2ec1dcf9b0d1952176282caeb7c07b55e6e9ed935038eab20f120beae237",
}
DEPENDENCY_V2_SUPERSESSION_RECEIPT_EXPECTED = {
    "size_bytes": 1_529,
    "sha256": "01871c27e9f7558ff4882c2b824e520e9642686fc54c17285296db1c8edc09a0",
}

ADOPTED_READ_ONLY = {
    "b1_constq_vio": {
        "path": ROOT / (
            "logs/aqualoc_archaeo_vins/"
            "external_klt_every2_litcmp_a02_4500_6300_preroll_b1_constq_vins_post_incident_v2_3_r1/"
            "vins_output/vio.csv"
        ),
        "size_bytes": 93_578,
        "sha256": "59c505704e9e82c050abe2c3e2edb83517b7044828beb694780646ff7a2bea92",
    },
    "xfeatbirth_rawlk_vio": {
        "path": ROOT / (
            "logs/aqualoc_archaeo_vins/"
            "external_klt_every2_litcmp_a02_4500_6300_preroll_xfeatbirth_rawlkcarrier_v1_vins_post_incident_v2_4_r1/"
            "vins_output/vio.csv"
        ),
        "size_bytes": 91_884,
        "sha256": "d6d8742753e96d7fa6243b469337c2bebaa28aac1ba9f47bcaa43971e8e88b00",
    },
    "common_support_summary": {
        "path": ROOT / (
            "papers/litcmp_a02_4500_6300_common_support/"
            "b1_constq_vs_xfeatbirth_adopted_v2_5_r1/common_support_summary.json"
        ),
        "size_bytes": 3_738,
        "sha256": "4641d2498fed5be8188f25d153fa11b76289de18afd7c8aeedea5106f1567d65",
    },
    "evaluator_process_receipt": {
        "path": ROOT / (
            "papers/litcmp_a02_4500_6300_common_support/"
            "b1_constq_vs_xfeatbirth_adopted_v2_5_r1/evaluator_process_receipt_v2_5.json"
        ),
        "size_bytes": 1_702,
        "sha256": "5637e2ad33e3bfaf00ffff9b8f18d7a5a609f826f60eaa824cf9f92f49618778",
    },
}

ROLE = "HFNET_V6_A02_FULL_HISTORY_STRICT70_EXTERNAL_LEARNED_SYSTEM_DEVELOPMENT_ONLY"
DEPENDENCY_SCHEMA = "aqua-fe-hfnet-v6-a02-0001-6300-strict70-dependency-inventory-v2-1"
PREFLIGHT_SCHEMA = "aqua-fe-hfnet-v6-a02-0001-6300-strict70-preflight-v2"
PREPARED_SCHEMA = "aqua-fe-hfnet-v6-a02-0001-6300-strict70-prepared-v2"
LOCK_SCHEMA = "aqua-fe-hfnet-v6-a02-0001-6300-strict70-execution-lock-v2"
CHECK_SCHEMA = "aqua-fe-hfnet-v6-a02-0001-6300-strict70-prestart-check-v2"
CLAIM_SCHEMA = "aqua-fe-hfnet-v6-a02-0001-6300-strict70-process-start-claim-v2"
RESULT_SCHEMA = "aqua-fe-hfnet-v6-a02-0001-6300-strict70-run-result-v2"

AUTHORIZATION_TOKEN = "HFNET_V6_A02_0001_6300_SCORE_4500_6300_STRICT70_ATTEMPT_001_START_EXACTLY_ONCE"

CAMERA_COUNT = 6_300
CAMERA_WIDTH = 968
CAMERA_HEIGHT = 608
PREROLL_FIRST_INDEX = 0
PREROLL_LAST_INDEX = 4_498
SCORE_FIRST_INDEX = 4_499
SCORE_LAST_INDEX = 6_299
SCORE_CAMERA_COUNT = SCORE_LAST_INDEX - SCORE_FIRST_INDEX + 1
MIN_LAST_CAMERA_INDEX = SCORE_FIRST_INDEX
MIN_SCORE_POSES = 1_261
MIN_CONTIGUOUS_SCORE_POSES = 1_261
MIN_SCORE_KEYFRAMES = 1
MIN_GPU_FREE_MIB = 3_072

CONFIG = base.CONFIG
SELECTOR = base.SELECTOR
MATERIALIZER = base.MATERIALIZER
MATERIALIZER_TEST = base.MATERIALIZER_TEST
INPUT_AUDITOR = base.INPUT_AUDITOR
PREPARATION_AUDIT = base.PREPARATION_AUDIT
INPUT_ROOT = base.INPUT_ROOT
ATTEMPT = Path(
    "/mnt/data/AQUA-FE_WS/logs/published_hfnet_slam_v6/fresh_underwater/"
    "aqualoc_archaeology_a02_feed_0001_6300_score_4500_6300_strict70/attempt_001"
)
DEPENDENCY_INVENTORY = ROOT / "papers/hfnet_v6_a02_0001_6300_dependency_inventory_v2_1.json"
EXECUTION_LOCK = ROOT / "papers/hfnet_v6_a02_0001_6300_score_4500_6300_strict70_execution_lock_v2.json"

EXPECTED_FULL_INPUT = dict(base.EXPECTED_FULL_INPUT)
EXPECTED_IDENTITIES: Mapping[str, Mapping[str, object]] = {
    name: dict(value) for name, value in base.EXPECTED_IDENTITIES.items()
}
BASE_MODEL_PATH_LINE = engine.BASE_MODEL_PATH_LINE

# Preserve the sealed implementations before patching their module globals.
_base_build_execution_lock = base._base_build_execution_lock
_base_scan_processes = base._base_scan_processes
derive_runtime_config = base.derive_runtime_config


def _query_gpu_resource_gate() -> Dict[str, Any]:
    environment = engine.runtime_environment(DEFAULT_SPEC)
    try:
        memory = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=memory.total,memory.used,memory.free",
                "--format=csv,noheader,nounits",
            ],
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            universal_newlines=True,
            timeout=10,
            env=environment,
        )
        compute = subprocess.run(
            [
                "nvidia-smi",
                "--query-compute-apps=pid,process_name,used_memory",
                "--format=csv,noheader,nounits",
            ],
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            universal_newlines=True,
            timeout=10,
            env=environment,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        return {
            "ready": False,
            "errors": ["NVIDIA_SMI_QUERY_FAILED:%s" % type(error).__name__],
            "minimum_free_mib": MIN_GPU_FREE_MIB,
        }
    errors: List[str] = []
    rows = [row.strip() for row in memory.stdout.splitlines() if row.strip()]
    if memory.returncode != 0 or len(rows) != 1:
        errors.append("GPU_MEMORY_QUERY_INVALID")
        total_mib = used_mib = free_mib = None
    else:
        try:
            total_mib, used_mib, free_mib = [int(value.strip()) for value in rows[0].split(",")]
        except (ValueError, TypeError):
            total_mib = used_mib = free_mib = None
            errors.append("GPU_MEMORY_ROW_INVALID")
    applications = [row.strip() for row in compute.stdout.splitlines() if row.strip()]
    if compute.returncode != 0:
        errors.append("GPU_COMPUTE_APPS_QUERY_INVALID")
    if applications:
        errors.append("GPU_COMPUTE_APPLICATION_PRESENT")
    if free_mib is None or free_mib < MIN_GPU_FREE_MIB:
        errors.append("GPU_FREE_MEMORY_BELOW_%d_MIB" % MIN_GPU_FREE_MIB)
    return {
        "ready": not errors,
        "errors": errors,
        "minimum_free_mib": MIN_GPU_FREE_MIB,
        "memory": {"total_mib": total_mib, "used_mib": used_mib, "free_mib": free_mib},
        "compute_applications": applications,
    }


def scan_processes(spec) -> List[Dict[str, object]]:
    conflicts = list(_base_scan_processes(spec))
    resource = _query_gpu_resource_gate()
    for index, error in enumerate(resource.get("errors", [])):
        conflicts.append(
            {
                "pid": -(index + 1),
                "comm": "RESOURCE_GATE:%s" % error,
                "exact_phase_f_elf": False,
            }
        )
    return sorted(conflicts, key=lambda row: int(row["pid"]))


def audit_v1_abandoned_live_absence() -> Dict[str, Any]:
    """Fail closed if the abandoned v1 namespace ever crosses a terminal boundary."""
    observations: Dict[str, Any] = {}
    for label, path in V1_FORBIDDEN_TERMINAL_PATHS.items():
        exists = path.exists()
        symlink = path.is_symlink()
        observations[label] = {
            "path": str(engine.absolute(path)),
            "exists": exists,
            "is_symlink": symlink,
        }
        if exists or symlink:
            raise engine.ContractError("ABANDONED_V1_TERMINAL_PATH_APPEARED:%s" % label)
    return {
        "status": "PASS_V1_REMAINS_PREPARED_ONLY_PRELOCK_UNSTARTED",
        "all_forbidden_terminal_paths_absent": True,
        "observations": observations,
    }


def audit_stack(spec) -> Dict[str, Any]:
    value = base.audit_stack(spec)
    identities = value["identities"]
    identities["reused_v1_controller"] = engine.require_identity(
        REUSED_V1_CONTROLLER, REUSED_V1_CONTROLLER_EXPECTED, "reused_v1_controller"
    )
    identities["strict70_v2_controller"] = engine.file_identity(WRAPPER)
    identities["strict70_protocol"] = engine.require_identity(
        STRICT70_PROTOCOL, STRICT70_PROTOCOL_EXPECTED, "strict70_protocol"
    )
    identities["v1_abandonment_receipt"] = engine.require_identity(
        V1_ABANDONMENT_RECEIPT,
        V1_ABANDONMENT_RECEIPT_EXPECTED,
        "v1_abandonment_receipt",
    )
    identities["dependency_v2_supersession_receipt"] = engine.require_identity(
        DEPENDENCY_V2_SUPERSESSION_RECEIPT,
        DEPENDENCY_V2_SUPERSESSION_RECEIPT_EXPECTED,
        "dependency_v2_supersession_receipt",
    )
    value["adopted_b1_constq_xfeatbirth_read_only_pins"] = {
        name: engine.require_identity(record["path"], record, name)
        for name, record in ADOPTED_READ_ONLY.items()
    }
    value["reuse_boundary"].update(
        {
            "v1_controller_execution_reused": False,
            "v1_controller_implementation_reused_and_pinned": True,
            "v1_prepared_attempt_reused": False,
            "strict70_gate_is_additive_v2": True,
            "legacy_formal900_pins_are_context_only_not_the_adopted_5400_score_family": True,
        }
    )
    value["gate_correction_boundary"] = {
        "v1_prepared_only_abandoned": True,
        "v1_hfnet_started": False,
        "v1_execution_lock_absent": True,
        "score_camera_count": SCORE_CAMERA_COUNT,
        "minimum_score_poses": MIN_SCORE_POSES,
        "minimum_contiguous_score_poses": MIN_CONTIGUOUS_SCORE_POSES,
        "threshold_calculation": "ceil(0.70 * 1801) = 1261",
    }
    value["v1_abandoned_live_absence"] = audit_v1_abandoned_live_absence()
    value["adopted_evidence_family_boundary"] = {
        "family": "B1_CONSTQ_V2_3_VS_XFEATBIRTH_RAWLK_V2_4_POST_INCIDENT_V2_5",
        "feed_history_source_indices_inclusive": [4500, 6300],
        "score_source_indices_inclusive": [5400, 6300],
        "formal900_r4_paths_used_as_adopted_5400_score_evidence": False,
    }
    return value


def build_execution_lock(spec, prepared: Mapping[str, Any], locked_at: str) -> Dict[str, Any]:
    value = _base_build_execution_lock(spec, prepared, locked_at)
    identities = prepared["profile"]["preparation_and_stack"]["identities"]
    value["reused_v1_controller"] = identities["reused_v1_controller"]
    value["strict70_v2_controller"] = identities["strict70_v2_controller"]
    value["strict70_protocol"] = identities["strict70_protocol"]
    value["v1_abandonment_receipt"] = identities["v1_abandonment_receipt"]
    value["dependency_v2_supersession_receipt"] = identities[
        "dependency_v2_supersession_receipt"
    ]
    value["adopted_b1_constq_xfeatbirth_read_only_pins"] = prepared["profile"][
        "preparation_and_stack"
    ]["adopted_b1_constq_xfeatbirth_read_only_pins"]
    value["v1_abandoned_live_absence"] = prepared["profile"]["preparation_and_stack"][
        "v1_abandoned_live_absence"
    ]
    value["resource_gate"] = {
        "minimum_gpu_free_mib": MIN_GPU_FREE_MIB,
        "no_nvidia_compute_applications": True,
        "no_matching_hfnet_vins_orb_detector_evaluator_processes": True,
        "checked_again_immediately_before_start": True,
    }
    value["strict70_primary_gate"] = {
        "score_camera_count": SCORE_CAMERA_COUNT,
        "minimum_score_poses": MIN_SCORE_POSES,
        "minimum_score_coverage_fraction": 0.70,
        "minimum_contiguous_score_poses": MIN_CONTIGUOUS_SCORE_POSES,
        "minimum_longest_contiguous_fraction": 0.70,
        "minimum_score_keyframes": MIN_SCORE_KEYFRAMES,
        "integer_threshold_rule": "ceil(0.70 * 1801) = 1261",
    }
    value["comparison_window_boundary"] = {
        "external_hfnet_feed_history_source_indices_inclusive": [1, 6300],
        "external_hfnet_score_source_indices_inclusive": [4500, 6300],
        "existing_adopted_evidence_family": "B1_CONSTQ_V2_3_VS_XFEATBIRTH_RAWLK_V2_4_POST_INCIDENT_V2_5",
        "existing_adopted_b1_constq_xfeatbirth_feed_history_source_indices_inclusive": [4500, 6300],
        "existing_adopted_b1_constq_xfeatbirth_score_source_indices_inclusive": [5400, 6300],
        "exact_score_window_match": False,
        "feed_history_match": False,
        "possible_common_score_support_source_indices_inclusive": [5400, 6300],
        "fair_direct_accuracy_comparison_permitted": False,
        "accuracy_head_to_head_status": "BLOCKED_HISTORY_MISMATCH",
        "unblock_requirement": "rerun every compared arm with the same frozen feed/history and score support",
    }
    value["claim_boundary"] = {
        "external_learned_system_trajectory_only": True,
        "development_exposed_window": True,
        "full_history_protocol_is_additive_not_a_rewrite_of_old_a02": True,
        "v1_prepared_attempt_reuse_forbidden": True,
        "p07_backfill_forbidden": True,
        "reference_is_image_derived_proxy_not_independent_ground_truth": True,
        "accuracy_claimed_by_run_controller": False,
        "superiority_claimed": False,
        "possible_common_score_support_does_not_remove_history_mismatch": True,
        "fair_accuracy_head_to_head_claimed": False,
        "identical_score_window_with_existing_adopted_b1_constq_xfeatbirth_claimed": False,
    }
    return value


def collect_profile(spec) -> Dict[str, Any]:
    return {
        "scientific_role": ROLE,
        "preparation_and_stack": audit_stack(spec),
        "dependencies": engine.audit_dependencies(spec),
        "input": engine.audit_input(spec),
        "selection": {
            "sequence": "AQUALOC archaeology_sequence_02",
            "source_frame_indices_inclusive": [1, 6300],
            "camera_count": CAMERA_COUNT,
            "source_camera_zero_trimmed_for_missing_shifted_imu_predecessor": True,
            "synthetic_imu_samples_added": False,
            "preroll_relative_indices_inclusive": [PREROLL_FIRST_INDEX, PREROLL_LAST_INDEX],
            "preroll_source_indices_inclusive": [1, 4499],
            "score_relative_indices_inclusive": [SCORE_FIRST_INDEX, SCORE_LAST_INDEX],
            "score_source_indices_inclusive": [4500, 6300],
            "score_camera_count": SCORE_CAMERA_COUNT,
            "score_reference_proxy_pose_count": 91,
            "score_reference_kind": "image-derived COLMAP proxy",
            "strict70_minimum_score_poses": MIN_SCORE_POSES,
            "strict70_minimum_contiguous_score_poses": MIN_CONTIGUOUS_SCORE_POSES,
            "experiment_and_window_selection_is_development_result_informed": True,
            "legacy_failures_and_existing_results_were_visible": True,
            "strict70_threshold_correction_is_pre_v2_result_outcome_blind": True,
            "external_hfnet_feed_history_source_indices_inclusive": [1, 6300],
            "existing_adopted_evidence_family": "B1_CONSTQ_V2_3_VS_XFEATBIRTH_RAWLK_V2_4_POST_INCIDENT_V2_5",
            "existing_adopted_b1_constq_xfeatbirth_feed_history_source_indices_inclusive": [4500, 6300],
            "existing_adopted_b1_constq_xfeatbirth_score_source_indices_inclusive": [5400, 6300],
            "exact_score_window_match_with_existing_adopted_b1_constq_xfeatbirth": False,
            "feed_history_match_with_existing_adopted_b1_constq_xfeatbirth": False,
            "possible_common_score_support_source_indices_inclusive": [5400, 6300],
            "accuracy_head_to_head_status": "BLOCKED_HISTORY_MISMATCH",
            "fair_direct_accuracy_comparison_permitted": False,
            "existing_adopted_b1_constq_vio": str(ADOPTED_READ_ONLY["b1_constq_vio"]["path"]),
            "existing_adopted_xfeatbirth_rawlk_vio": str(
                ADOPTED_READ_ONLY["xfeatbirth_rawlk_vio"]["path"]
            ),
            "existing_adopted_common_support_summary": str(
                ADOPTED_READ_ONLY["common_support_summary"]["path"]
            ),
            "existing_adopted_evaluator_window_start_s": 1542829061.6926866,
            "existing_adopted_evaluator_window_end_s": 1542829106.6875105,
        },
    }


def prepare_strict70(spec):
    """Prepare a fresh attempt with the honest development/outcome boundary."""
    decision = engine.preflight(spec)
    if not decision["ready"]:
        decision.update({"status": "PREPARE_BLOCKED", "return_code": engine.RC_BLOCKED})
        return decision
    temporary = None
    try:
        parent = spec.attempt.parent
        parent.mkdir(parents=True, exist_ok=True)
        if spec.attempt.exists() or spec.attempt.is_symlink():
            raise engine.ContractError("ATTEMPT_NAMESPACE_RACE_OR_CLOBBER")
        temporary = Path(tempfile.mkdtemp(prefix=".%s.prepare." % spec.attempt.name, dir=str(parent)))
        temp_model = temporary / "run_local_model/HFNet-RT"
        temp_model.mkdir(parents=True)
        temp_onnx = temp_model / "HF-Net.onnx"
        temp_cache = temp_model / "HF-Net.cache"
        shutil.copyfile(str(spec.onnx), str(temp_onnx))
        shutil.copyfile(str(spec.cache), str(temp_cache))
        os.chmod(str(temp_onnx), 0o444)
        os.chmod(str(temp_cache), 0o644)
        local_onnx = engine.file_identity(temp_onnx, recorded_path=spec.local_onnx)
        local_cache = engine.file_identity(temp_cache, recorded_path=spec.local_cache)
        if engine.content_identity(temp_onnx) != engine.content_identity(spec.onnx):
            raise engine.ContractError("RUN_LOCAL_ONNX_COPY_MISMATCH")
        if engine.content_identity(temp_cache) != engine.content_identity(spec.cache):
            raise engine.ContractError("RUN_LOCAL_CACHE_COPY_MISMATCH")
        config_bytes = derive_runtime_config(
            spec.config.read_text(encoding="utf-8"), spec.model_dir
        ).encode("utf-8")
        temp_config = temporary / spec.runtime_config.name
        engine.write_exclusive(temp_config, config_bytes)
        runtime_config = engine.file_identity(temp_config, recorded_path=spec.runtime_config)
        manifest = {
            "schema_version": PREPARED_SCHEMA,
            "status": "PREPARED_UNSTARTED_FRESH_ATTEMPT_001",
            "scientific_role": ROLE,
            "prepared_at_utc": engine.now_utc(),
            "namespace": str(engine.absolute(spec.attempt)),
            "frozen_profile": decision["profile"],
            "frozen_profile_sha256": engine.profile_sha256(decision["profile"]),
            "run_local": {
                "onnx": local_onnx,
                "cache_seed": local_cache,
                "runtime_config": runtime_config,
            },
            "shared_cache_preparation_identity": engine.file_identity(spec.cache),
            "launch": engine._launch_contract(spec),
            "policy": {
                "one_shot": True,
                "retry": False,
                "result_conditioned_selection": True,
                "experiment_and_window_selection_is_development_result_informed": True,
                "legacy_failures_and_existing_results_were_visible": True,
                "strict70_threshold_correction_is_pre_v2_result_outcome_blind": True,
                "strict70_threshold_frozen_before_v2_elf_start": True,
            },
            "claims": {
                "hfnet_started": False,
                "trajectory_observed": False,
                "superiority_claimed": False,
            },
        }
        engine.write_exclusive(temporary / spec.prepared_manifest.name, engine.canonical_json(manifest))
        engine.fsync_dir(temp_model)
        engine.fsync_dir(temp_model.parent)
        engine.fsync_dir(temporary)
        if engine.file_identity(spec.cache) != manifest["shared_cache_preparation_identity"]:
            raise engine.ContractError("SHARED_CACHE_CHANGED_DURING_PREPARE")
        os.rename(str(temporary), str(spec.attempt))
        temporary = None
        engine.fsync_dir(parent)
        return {
            "schema_version": PREPARED_SCHEMA,
            "status": "PREPARED_UNSTARTED_FRESH_ATTEMPT_001",
            "ready_for_lock": True,
            "return_code": engine.RC_OK,
            "prepared_manifest": engine.file_identity(spec.prepared_manifest),
            "claims": {"hfnet_started": False},
        }
    except (engine.ContractError, OSError, ValueError, UnicodeError, json.JSONDecodeError) as error:
        if temporary is not None and temporary.exists():
            shutil.rmtree(str(temporary))
        return {
            "schema_version": PREPARED_SCHEMA,
            "status": "PREPARE_BLOCKED",
            "ready_for_lock": False,
            "return_code": engine.RC_BLOCKED,
            "errors": [str(error)],
            "claims": {"hfnet_started": False},
        }


def strict70_trajectory_adjudication(trajectory: Mapping[str, Any]) -> Dict[str, Any]:
    """Apply both integer and explicit fractional forms of the frozen gate."""
    score = trajectory.get("score", {})
    count = int(score.get("count", 0) or 0)
    longest = int(score.get("longest_contiguous_run", 0) or 0)
    reported_coverage = score.get("coverage_fraction")
    derived_coverage = count / float(SCORE_CAMERA_COUNT)
    longest_fraction = longest / float(SCORE_CAMERA_COUNT)
    coverage_consistent = isinstance(reported_coverage, (int, float)) and abs(
        float(reported_coverage) - derived_coverage
    ) <= 1e-15
    last_index = trajectory.get("overall", {}).get("last_index")
    gate = bool(
        trajectory.get("valid")
        and last_index is not None
        and int(last_index) >= MIN_LAST_CAMERA_INDEX
        and count >= MIN_SCORE_POSES
        and longest >= MIN_CONTIGUOUS_SCORE_POSES
        and coverage_consistent
        and float(reported_coverage) >= 0.70
        and longest_fraction >= 0.70
    )
    return {
        "pass": gate,
        "score_camera_count": SCORE_CAMERA_COUNT,
        "score_pose_count": count,
        "score_coverage_fraction_reported": reported_coverage,
        "score_coverage_fraction_derived": derived_coverage,
        "score_coverage_fraction_consistent": coverage_consistent,
        "minimum_score_coverage_fraction": 0.70,
        "longest_contiguous_score_poses": longest,
        "longest_contiguous_score_fraction": longest_fraction,
        "minimum_longest_contiguous_score_fraction": 0.70,
        "minimum_score_poses": MIN_SCORE_POSES,
        "minimum_contiguous_score_poses": MIN_CONTIGUOUS_SCORE_POSES,
        "last_local_camera_index": last_index,
        "minimum_last_local_camera_index": MIN_LAST_CAMERA_INDEX,
    }


def run_strict70(spec, *, authorization_token: str = "") -> Dict[str, Any]:
    """Launch once and seal a truthful 6300-image, explicit-fraction result."""
    if authorization_token != AUTHORIZATION_TOKEN:
        return {
            "schema_version": RESULT_SCHEMA,
            "status": "RUN_NOT_AUTHORIZED",
            "return_code": engine.RC_BLOCKED,
            "errors": ["EXACT_ONE_SHOT_AUTHORIZATION_TOKEN_REQUIRED"],
            "execution": {"popen_invocations": 0, "process_started": False, "retry": False},
        }
    try:
        checked = engine.check(spec)
        if not checked["ready"]:
            raise engine.ContractError("PRESTART_CHECK_NOT_GO:%s" % checked["errors"])
        prepared = checked["audit"]
        profile_pre = prepared["profile"]
        local_pre = {
            "onnx": engine.file_identity(spec.local_onnx),
            "cache": engine.file_identity(spec.local_cache),
            "runtime_config": engine.file_identity(spec.runtime_config),
            "shared_cache": engine.file_identity(spec.cache),
        }
        claim = engine.build_start_claim(spec, prepared)
        engine.write_exclusive(spec.start_claim, engine.canonical_json(claim))
        claim_identity = engine.file_identity(spec.start_claim)
    except (engine.ContractError, OSError, ValueError, UnicodeError, json.JSONDecodeError) as error:
        return {
            "schema_version": RESULT_SCHEMA,
            "status": "RUN_CONTRACT_BLOCKED",
            "return_code": engine.RC_BLOCKED,
            "errors": [str(error)],
            "execution": {"popen_invocations": 0, "process_started": False, "retry": False},
        }

    started_at = engine.now_utc()
    try:
        execution = engine.launch_once(spec)
    except Exception as error:
        execution = engine.Execution(
            1,
            False,
            None,
            None,
            False,
            True,
            0.0,
            error="LAUNCH_SUPERVISOR_EXCEPTION:%s:%s" % (type(error).__name__, error),
        )
    ended_at = engine.now_utc()

    post_errors: List[str] = []
    try:
        profile_post = collect_profile(spec)
    except Exception as error:
        profile_post = None
        post_errors.append("POST_FULL_PROFILE_FAILED:%s:%s" % (type(error).__name__, error))

    def safe_identity(path: Path, label: str):
        try:
            return engine.file_identity(path)
        except Exception as error:
            post_errors.append("POST_IDENTITY_FAILED:%s:%s" % (label, error))
            return None

    local_post = {
        "onnx": safe_identity(spec.local_onnx, "local_onnx"),
        "cache": safe_identity(spec.local_cache, "local_cache"),
        "runtime_config": safe_identity(spec.runtime_config, "runtime_config"),
        "shared_cache": safe_identity(spec.cache, "shared_cache"),
    }
    try:
        camera_ns = engine.parse_camera_timestamps(spec.input_root / "cam0_times.txt")
    except Exception as error:
        camera_ns = []
        post_errors.append("CAMERA_TIMESTAMPS_POST_PARSE_FAILED:%s" % error)
    trajectory = (
        engine.parse_trajectory(spec.result_dir / "trajectory.txt", camera_ns, keyframes=False)
        if camera_ns
        else {"valid": False, "errors": ["NO_CAMERA_GRID"]}
    )
    keyframes = (
        engine.parse_trajectory(spec.result_dir / "trajectory_keyframe.txt", camera_ns, keyframes=True)
        if camera_ns
        else {"valid": False, "errors": ["NO_CAMERA_GRID"]}
    )
    try:
        result_tree = engine.result_tree_identity(spec.result_dir)
    except Exception as error:
        result_tree = None
        post_errors.append("RESULT_TREE_AUDIT_FAILED:%s" % error)
    stdout_identity = safe_identity(spec.stdout_log, "stdout")
    stderr_identity = safe_identity(spec.stderr_log, "stderr")
    warnings = {
        "stdout": engine.summarize_warnings(spec.stdout_log),
        "stderr": engine.summarize_warnings(spec.stderr_log),
    }
    profile_unchanged = profile_post == profile_pre
    immutable_local_exact = (
        local_post["onnx"] == local_pre["onnx"]
        and local_post["runtime_config"] == local_pre["runtime_config"]
    )
    shared_cache_exact = local_post["shared_cache"] == local_pre["shared_cache"]
    trajectory_adjudication = strict70_trajectory_adjudication(trajectory)
    trajectory_gate = bool(trajectory_adjudication["pass"])
    keyframe_gate = bool(
        keyframes.get("valid")
        and keyframes.get("score", {}).get("count", 0) >= MIN_SCORE_KEYFRAMES
    )
    execution_gate = bool(
        execution.popen_invocations == 1
        and execution.process_started
        and execution.returncode == 0
        and not execution.timed_out
        and execution.synchronously_reaped
    )
    usability_pass = bool(
        execution_gate
        and trajectory_gate
        and keyframe_gate
        and profile_unchanged
        and immutable_local_exact
        and shared_cache_exact
        and not post_errors
    )
    errors = list(post_errors)
    if not execution_gate:
        errors.append("EXECUTION_GATE_FAILED")
    if not trajectory_gate:
        errors.append("FRAME_TRAJECTORY_STRICT70_USABILITY_GATE_FAILED")
    if not keyframe_gate:
        errors.append("KEYFRAME_SCORE_SUPPORT_GATE_FAILED")
    if not profile_unchanged:
        errors.append("FULL_FROZEN_PROFILE_PRE_POST_MISMATCH")
    if not immutable_local_exact:
        errors.append("RUN_LOCAL_ONNX_OR_CONFIG_CHANGED")
    if not shared_cache_exact:
        errors.append("SHARED_CACHE_CHANGED")
    result = {
        "schema_version": RESULT_SCHEMA,
        "status": (
            "PASS_EXPLORATORY_UNDERWATER_USABILITY"
            if usability_pass
            else "FAIL_EXPLORATORY_UNDERWATER_USABILITY"
        ),
        "return_code": engine.RC_OK if usability_pass else engine.RC_FAILED,
        "scientific_role": ROLE,
        "errors": errors,
        "execution": {
            "popen_invocations": execution.popen_invocations,
            "process_started": execution.process_started,
            "pid": execution.pid,
            "raw_returncode": execution.returncode,
            "timed_out": execution.timed_out,
            "timeout_seconds": spec.timeout_seconds,
            "synchronously_reaped": execution.synchronously_reaped,
            "duration_seconds": execution.duration_seconds,
            "termination_signals": list(execution.termination_signals),
            "supervisor_error": execution.error,
            "started_at_utc": started_at,
            "ended_at_utc": ended_at,
            "retry_performed": False,
            "retry_permitted": False,
            "inferred_images_consumed": (
                CAMERA_COUNT if execution.returncode == 0 and not execution.timed_out else None
            ),
            "inference_basis": "official entry returned after its sequential 6300-image loop over source cameras 1..6300",
        },
        "pins": {
            "runner": engine.file_identity(WRAPPER),
            "execution_lock": prepared["execution_lock"]["identity"],
            "prepared_manifest": prepared["prepared_manifest"],
            "process_start_claim": claim_identity,
            "stdout": stdout_identity,
            "stderr": stderr_identity,
            "run_local_pre": local_pre,
            "run_local_post": local_post,
            "run_local_cache_mutation_recorded_not_assumed_immutable": (
                local_pre["cache"] != local_post["cache"]
            ),
        },
        "pre_post": {
            "full_profile_pre_sha256": engine.profile_sha256(profile_pre),
            "full_profile_post_sha256": (
                engine.profile_sha256(profile_post) if profile_post is not None else None
            ),
            "full_profile_exact": profile_unchanged,
            "input_full_tree_pre": profile_pre["input"]["full_tree"],
            "input_full_tree_post": (
                profile_post["input"]["full_tree"] if profile_post is not None else None
            ),
            "resolved_dependencies_pre": profile_pre["dependencies"]["core"],
            "resolved_dependencies_post": (
                profile_post["dependencies"]["core"] if profile_post is not None else None
            ),
            "post_audit_errors": post_errors,
        },
        "support": {
            "frozen_windows": profile_pre["selection"],
            "trajectory": trajectory,
            "keyframes": keyframes,
            "strict70_trajectory_adjudication": trajectory_adjudication,
            "result_tree": result_tree,
            "warnings": warnings,
        },
        "gate": {
            "execution": execution_gate,
            "trajectory_score_count_at_least_1261": (
                trajectory_adjudication["score_pose_count"] >= MIN_SCORE_POSES
            ),
            "trajectory_score_coverage_fraction_at_least_0_70": (
                trajectory_adjudication["score_coverage_fraction_consistent"]
                and trajectory_adjudication["score_coverage_fraction_derived"] >= 0.70
            ),
            "trajectory_longest_contiguous_count_at_least_1261": (
                trajectory_adjudication["longest_contiguous_score_poses"]
                >= MIN_CONTIGUOUS_SCORE_POSES
            ),
            "trajectory_longest_contiguous_fraction_at_least_0_70": (
                trajectory_adjudication["longest_contiguous_score_fraction"] >= 0.70
            ),
            "trajectory_score_strict70": trajectory_gate,
            "keyframe_score_support": keyframe_gate,
            "full_pre_post_profile_exact": profile_unchanged,
            "run_local_onnx_and_config_exact": immutable_local_exact,
            "shared_cache_exact": shared_cache_exact,
            "exploratory_underwater_usability_strict70": usability_pass,
        },
        "claim_boundary": {
            "exploratory_underwater_usability_only": True,
            "experiment_and_window_selection_is_development_result_informed": True,
            "strict70_threshold_correction_is_pre_v2_result_outcome_blind": True,
            "accuracy_evaluated": False,
            "ground_truth_evaluator_started": False,
            "other_learning_system_compared": False,
            "accuracy_head_to_head_status": "BLOCKED_HISTORY_MISMATCH",
            "possible_common_score_support_source_indices_inclusive": [5400, 6300],
            "fair_direct_accuracy_comparison_permitted": False,
            "superiority_claimed": False,
            "formal_paper_claim_authorized": False,
        },
        "sealing_contract": {
            "target": str(engine.absolute(spec.run_result)),
            "write_mode": "O_EXCL_then_fsync_then_chmod_0444",
            "terminal_after_any_started_attempt": True,
            "retry_after_pass_or_fail": False,
        },
    }
    try:
        engine.write_exclusive(spec.run_result, engine.canonical_json(result))
        result["run_result"] = engine.file_identity(spec.run_result)
        result["sealed"] = True
    except Exception as error:
        result["sealed"] = False
        result["errors"].append(
            "RUN_RESULT_SEAL_FAILED:%s:%s" % (type(error).__name__, error)
        )
        result["return_code"] = engine.RC_FAILED
    return result


for _name, _value in {
    "__file__": str(WRAPPER),
    "ROLE": ROLE,
    "DEPENDENCY_SCHEMA": DEPENDENCY_SCHEMA,
    "PREFLIGHT_SCHEMA": PREFLIGHT_SCHEMA,
    "PREPARED_SCHEMA": PREPARED_SCHEMA,
    "LOCK_SCHEMA": LOCK_SCHEMA,
    "CHECK_SCHEMA": CHECK_SCHEMA,
    "CLAIM_SCHEMA": CLAIM_SCHEMA,
    "RESULT_SCHEMA": RESULT_SCHEMA,
    "AUTHORIZATION_TOKEN": AUTHORIZATION_TOKEN,
    "CAMERA_COUNT": CAMERA_COUNT,
    "CAMERA_WIDTH": CAMERA_WIDTH,
    "CAMERA_HEIGHT": CAMERA_HEIGHT,
    "PREROLL_FIRST_INDEX": PREROLL_FIRST_INDEX,
    "PREROLL_LAST_INDEX": PREROLL_LAST_INDEX,
    "SCORE_FIRST_INDEX": SCORE_FIRST_INDEX,
    "SCORE_LAST_INDEX": SCORE_LAST_INDEX,
    "MIN_LAST_CAMERA_INDEX": MIN_LAST_CAMERA_INDEX,
    "MIN_SCORE_POSES": MIN_SCORE_POSES,
    "MIN_CONTIGUOUS_SCORE_POSES": MIN_CONTIGUOUS_SCORE_POSES,
    "MIN_SCORE_KEYFRAMES": MIN_SCORE_KEYFRAMES,
    "CONFIG": CONFIG,
    "SELECTOR": SELECTOR,
    "MATERIALIZER": MATERIALIZER,
    "MATERIALIZER_TEST": MATERIALIZER_TEST,
    "INPUT_AUDITOR": INPUT_AUDITOR,
    "PREPARATION_AUDIT": PREPARATION_AUDIT,
    "RUNNER_TEST": RUNNER_TEST,
    "INPUT_ROOT": INPUT_ROOT,
    "ATTEMPT": ATTEMPT,
    "DEPENDENCY_INVENTORY": DEPENDENCY_INVENTORY,
    "EXECUTION_LOCK": EXECUTION_LOCK,
    "EXPECTED_IDENTITIES": EXPECTED_IDENTITIES,
    "EXPECTED_FULL_INPUT": EXPECTED_FULL_INPUT,
    "derive_runtime_config": derive_runtime_config,
    "scan_processes": scan_processes,
    "audit_stack": audit_stack,
    "build_execution_lock": build_execution_lock,
    "collect_profile": collect_profile,
    "prepare": prepare_strict70,
    "run": run_strict70,
}.items():
    setattr(engine, _name, _value)

DEFAULT_SPEC = engine.Spec(
    config=CONFIG,
    selector=SELECTOR,
    materializer=MATERIALIZER,
    materializer_test=MATERIALIZER_TEST,
    input_auditor=INPUT_AUDITOR,
    preparation_audit=PREPARATION_AUDIT,
    input_root=INPUT_ROOT,
    attempt=ATTEMPT,
    dependency_inventory=DEPENDENCY_INVENTORY,
    execution_lock=EXECUTION_LOCK,
    expected=EXPECTED_IDENTITIES,
)
engine.DEFAULT_SPEC = DEFAULT_SPEC

ContractError = engine.ContractError
Spec = engine.Spec
replace = engine.replace
canonical_json = engine.canonical_json
write_exclusive = engine.write_exclusive
file_identity = engine.file_identity
read_canonical_json = engine.read_canonical_json
_contiguous_metrics = engine._contiguous_metrics
parse_trajectory = engine.parse_trajectory
snapshot_dependencies = engine.snapshot_dependencies
preflight = engine.preflight
prepare = prepare_strict70
lock_execution = engine.lock_execution
check = engine.check
run = run_strict70


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(description=__doc__)
    value.add_argument(
        "--action",
        choices=("snapshot-deps", "preflight", "prepare", "lock", "check", "run"),
        default="preflight",
    )
    value.add_argument("--attempt", type=Path, default=ATTEMPT)
    value.add_argument("--authorization-token", default="")
    return value


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parser().parse_args(argv)
    spec = engine.replace(DEFAULT_SPEC, attempt=args.attempt)
    if args.action == "snapshot-deps":
        decision = snapshot_dependencies(spec)
    elif args.action == "preflight":
        decision = preflight(spec)
    elif args.action == "prepare":
        decision = prepare(spec)
    elif args.action == "lock":
        decision = lock_execution(spec)
    elif args.action == "check":
        decision = check(spec)
        decision["gpu_resource_gate"] = _query_gpu_resource_gate()
    else:
        decision = run(spec, authorization_token=args.authorization_token)
    sys.stdout.buffer.write(canonical_json(decision))
    return int(decision["return_code"])


if __name__ == "__main__":
    raise SystemExit(main())
