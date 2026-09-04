#!/usr/bin/env python3
"""One-shot A02 full-history controller over the sealed HFNet v6 stack.

Canonical source cameras 1..6300 are fed sequentially.  Source camera 0 is
honestly trimmed because no shifted-IMU predecessor exists; no synthetic IMU
is allowed.  Only source cameras 4500..6300 form the score window shared with
the already produced GFTT/XFeat VINS development evidence.

The old A02 cold-start, result-informed extension, and P07 artifacts are pinned
read-only.  This additive namespace can start the official learned system at
most once, never retries, and requires an exact authorization token.
"""

from __future__ import annotations

import argparse
import importlib.util
from pathlib import Path
import subprocess
import sys
from typing import Any, Dict, List, Mapping, Optional, Sequence


ROOT = Path(__file__).resolve().parents[1]
WRAPPER = Path(__file__).resolve()
REUSED_A06_CONTROLLER = ROOT / "scripts/run_hfnet_v6_a06_0000_2460_exact_window_v1.py"
RUNNER_TEST = ROOT / "scripts/tests/test_run_hfnet_v6_a02_0001_6300_score_4500_6300_v1.py"


def _load(path: Path):
    specification = importlib.util.spec_from_file_location("hfnet_v6_a02_reused_a06_controller", str(path))
    if specification is None or specification.loader is None:
        raise RuntimeError("REUSED_A06_CONTROLLER_IMPORT_FAILED")
    module = importlib.util.module_from_spec(specification)
    sys.modules[specification.name] = module
    specification.loader.exec_module(module)
    return module


base = _load(REUSED_A06_CONTROLLER)
engine = base.engine

REUSED_A06_CONTROLLER_EXPECTED = {
    "size_bytes": 16_636,
    "sha256": "4f61848cfb7a46e7a3f2c829ba3bc6225257cdc878759a3d82feb6873313ee68",
}

ROLE = "HFNET_V6_A02_FULL_HISTORY_EXTERNAL_LEARNED_SYSTEM_DEVELOPMENT_ONLY"
DEPENDENCY_SCHEMA = "aqua-fe-hfnet-v6-a02-0001-6300-dependency-inventory-v1"
PREFLIGHT_SCHEMA = "aqua-fe-hfnet-v6-a02-0001-6300-preflight-v1"
PREPARED_SCHEMA = "aqua-fe-hfnet-v6-a02-0001-6300-prepared-v1"
LOCK_SCHEMA = "aqua-fe-hfnet-v6-a02-0001-6300-execution-lock-v1"
CHECK_SCHEMA = "aqua-fe-hfnet-v6-a02-0001-6300-prestart-check-v1"
CLAIM_SCHEMA = "aqua-fe-hfnet-v6-a02-0001-6300-process-start-claim-v1"
RESULT_SCHEMA = "aqua-fe-hfnet-v6-a02-0001-6300-run-result-v1"

AUTHORIZATION_TOKEN = "HFNET_V6_A02_0001_6300_SCORE_4500_6300_ATTEMPT_001_START_EXACTLY_ONCE"

CAMERA_COUNT = 6_300
CAMERA_WIDTH = 968
CAMERA_HEIGHT = 608
PREROLL_FIRST_INDEX = 0
PREROLL_LAST_INDEX = 4_498
SCORE_FIRST_INDEX = 4_499
SCORE_LAST_INDEX = 6_299
MIN_LAST_CAMERA_INDEX = 4_499
MIN_SCORE_POSES = 20
MIN_CONTIGUOUS_SCORE_POSES = 20
MIN_SCORE_KEYFRAMES = 1
MIN_GPU_FREE_MIB = 3_072

CONFIG = ROOT / "configs/published_baselines/hfnet_slam_aqualoc_a02_0001_6300_score_4500_6300_v1.yaml"
SELECTOR = ROOT / "papers/hfnet_v6_a02_0001_6300_score_4500_6300_selector_freeze_v1.json"
MATERIALIZER = ROOT / "scripts/materialize_hfnet_v6_a02_0001_6300_score_4500_6300_v1.py"
MATERIALIZER_TEST = ROOT / "scripts/tests/test_materialize_hfnet_v6_a02_0001_6300_score_4500_6300_v1.py"
INPUT_AUDITOR = ROOT / "scripts/audit_hfnet_v6_a02_0001_6300_score_4500_6300_input_v1.py"
PREPARATION_AUDIT = ROOT / "papers/hfnet_v6_a02_0001_6300_score_4500_6300_preparation_audit_v1.json"
INPUT_ROOT = Path(
    "/mnt/data/AQUA-FE_WS/datasets/hfnet_v6_a02_full_history_v1/"
    "aqualoc_archaeology_a02_0001_6300"
)
ATTEMPT = Path(
    "/mnt/data/AQUA-FE_WS/logs/published_hfnet_slam_v6/fresh_underwater/"
    "aqualoc_archaeology_a02_feed_0001_6300_score_4500_6300/attempt_001"
)
DEPENDENCY_INVENTORY = ROOT / "papers/hfnet_v6_a02_0001_6300_dependency_inventory_v1.json"
EXECUTION_LOCK = ROOT / "papers/hfnet_v6_a02_0001_6300_score_4500_6300_execution_lock_v1.json"

LEGACY_READ_ONLY = {
    "cold_start_4500_6300_result": {
        "path": Path(
            "/mnt/data/AQUA-FE_WS/logs/published_hfnet_slam_v4/post_stop_a02_long1801_headless/"
            "drivers/aqualoc_a02_4500_6300_headless_r1/run_result.json"
        ),
        "size_bytes": 4_966,
        "sha256": "b7c911ca364a9d9233fa9b7cf0c6f245b83e89b129882628075fd8e759c6cb73",
    },
    "result_informed_4500_7200_result": {
        "path": Path(
            "/mnt/data/AQUA-FE_WS/logs/published_hfnet_slam_v5/result_informed_a02_4500_7200/"
            "drivers/aqualoc_a02_4500_7200_headless_r1/run_result.json"
        ),
        "size_bytes": 93_240,
        "sha256": "96d195115c7d706fc1897b3d92ca17627106a030f00303fb5080c35917603a10",
    },
    "p07_result_receipt": {
        "path": ROOT / (
            "papers/litcmp_a02_4500_6300_common_support/"
            "formal900_r4_xfeatbirth_vs_gfttbirth_r3/result_receipt_v1.json"
        ),
        "size_bytes": 3_265,
        "sha256": "250ac0db2a58e498543c1f7030461671f62c90a6543075d8597686eaa66c1aa0",
    },
    "existing_common_support_summary": {
        "path": ROOT / (
            "papers/litcmp_a02_4500_6300_common_support/"
            "formal900_r4_xfeatbirth_vs_gfttbirth_r3/primary/common_support_summary.json"
        ),
        "size_bytes": 3_760,
        "sha256": "4b4f6f9ea2d90e30bc6e9ba2c4a5087f814e369826a5c23bf9c3d96d43cb8cc1",
    },
}

EXPECTED_FULL_INPUT = {
    "file_count": 6_304,
    "total_bytes": 1_536_808_518,
    "tree_sha256": "e14f62462366063e334ebcb3d3b8c889c68682d81ef6cdfb728e65447a3d65a3",
    "tree_crc32": "0150a4a4",
}

EXPECTED_IDENTITIES: Mapping[str, Mapping[str, object]] = {
    "passed_stack_lock": dict(engine.EXPECTED_IDENTITIES["passed_stack_lock"]),
    "selector": {
        "size_bytes": 3_320,
        "sha256": "54e1340a4fe655be30b971d89178e8c588b1b973a93e4287b6ed6dd39feb7505",
    },
    "materializer": {
        "size_bytes": 12_335,
        "sha256": "522a09c8d6586e9bdafbd0a57f4329b020e132bcfad49a648852060f5b320abc",
    },
    "materializer_test": {
        "size_bytes": 6_387,
        "sha256": "d2645bad821ded516759eb181b9072f9e8744b5d4dc1d2ed31c4be22b42074a2",
    },
    "input_auditor": {
        "size_bytes": 14_982,
        "sha256": "14fbb99d1c26d382de09cec6761d02ca25225449403716ad4ec824871ee916bc",
    },
    "preparation_audit": {
        "size_bytes": 4_488,
        "sha256": "8de706487a1bd4168d796c0957fbaa078142fa29def0d09f3989db0a52199747",
    },
    "config": {
        "size_bytes": 2_024,
        "sha256": "b08c38d73347e4a506a43b3114b014a445d03df9fd76d01f75a1a9300de99b23",
    },
    "binary": dict(engine.EXPECTED_IDENTITIES["binary"]),
    "build_manifest": dict(engine.EXPECTED_IDENTITIES["build_manifest"]),
    "official_library": dict(engine.EXPECTED_IDENTITIES["official_library"]),
    "official_entry": dict(engine.EXPECTED_IDENTITIES["official_entry"]),
    "headless_source": dict(engine.EXPECTED_IDENTITIES["headless_source"]),
    "onnx": dict(engine.EXPECTED_IDENTITIES["onnx"]),
    "cache": dict(engine.EXPECTED_IDENTITIES["cache"]),
}

BASE_MODEL_PATH_LINE = engine.BASE_MODEL_PATH_LINE
_base_audit_stack = base._base_audit_stack
_base_build_execution_lock = base._base_build_execution_lock
_base_scan_processes = base._base_scan_processes


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
            "errors": [f"NVIDIA_SMI_QUERY_FAILED:{type(error).__name__}"],
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
        errors.append(f"GPU_FREE_MEMORY_BELOW_{MIN_GPU_FREE_MIB}_MIB")
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
                "comm": f"RESOURCE_GATE:{error}",
                "exact_phase_f_elf": False,
            }
        )
    return sorted(conflicts, key=lambda row: int(row["pid"]))


derive_runtime_config = base.derive_runtime_config


def audit_stack(spec) -> Dict[str, Any]:
    value = _base_audit_stack(spec)
    value["identities"]["reused_a06_controller"] = engine.require_identity(
        REUSED_A06_CONTROLLER,
        REUSED_A06_CONTROLLER_EXPECTED,
        "reused_a06_controller",
    )
    value["identities"]["a02_wrapper"] = engine.file_identity(WRAPPER)
    value["identities"]["runner_test"] = engine.file_identity(RUNNER_TEST)
    value["legacy_read_only_pins"] = {
        name: engine.require_identity(record["path"], record, name)
        for name, record in LEGACY_READ_ONLY.items()
    }
    value["reuse_boundary"] = {
        "a06_controller_changed": False,
        "dataset_contract_overridden_by_a02_wrapper": True,
        "algorithm_parameters_retuned": False,
        "legacy_or_p07_artifact_modified": False,
    }
    return value


def build_execution_lock(spec, prepared: Mapping[str, Any], locked_at: str) -> Dict[str, Any]:
    value = _base_build_execution_lock(spec, prepared, locked_at)
    identities = prepared["profile"]["preparation_and_stack"]["identities"]
    value["reused_a06_controller"] = identities["reused_a06_controller"]
    value["a02_wrapper"] = identities["a02_wrapper"]
    value["legacy_read_only_pins"] = prepared["profile"]["preparation_and_stack"]["legacy_read_only_pins"]
    value["resource_gate"] = {
        "minimum_gpu_free_mib": MIN_GPU_FREE_MIB,
        "no_nvidia_compute_applications": True,
        "no_matching_hfnet_vins_orb_detector_evaluator_processes": True,
        "checked_again_immediately_before_start": True,
    }
    value["claim_boundary"] = {
        "external_learned_system_trajectory_only": True,
        "development_exposed_window": True,
        "full_history_protocol_is_additive_not_a_rewrite_of_old_a02": True,
        "p07_backfill_forbidden": True,
        "reference_is_image_derived_proxy_not_independent_ground_truth": True,
        "accuracy_claimed_by_run_controller": False,
        "superiority_claimed": False,
        "comparison_requires_common_support_evaluation": True,
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
            "preroll_nominal_seconds": 224.913015072,
            "score_nominal_seconds": 89.9870752,
            "score_camera_count": 1801,
            "score_reference_proxy_pose_count": 91,
            "shared_existing_vins_window_source_indices_inclusive": [4500, 6300],
            "existing_gftt_vio": str(
                ROOT / "logs/aqualoc_archaeo_vins/external_klt_every2_litcmp_a02_4500_6300_preroll_matchedbirth_formal900_r4_gftt_vins_r1/vins_output/vio.csv"
            ),
            "existing_xfeat_vio": str(
                ROOT / "logs/aqualoc_archaeo_vins/external_klt_every2_litcmp_a02_4500_6300_preroll_matchedbirth_formal900_r4_xfeat_vins_r1/vins_output/vio.csv"
            ),
        },
    }


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
prepare = engine.prepare
lock_execution = engine.lock_execution
check = engine.check
run = engine.run


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
