#!/usr/bin/env python3
"""Fail-closed one-shot HFNet controller for H07 feed 0001..1720.

The official learned SLAM stack and H03 execution engine are reused without
algorithm retuning.  H07 source frames 0001..1659 are preroll and 1660..1720
are the exact score window shared with existing AQUA-FE development evidence.
Frame zero is excluded before execution because calibrated shifted IMU has no
predecessor there and the author EuRoC entry would decrement first_imu to -1.
No synthetic IMU is allowed.  Running requires the exact authorization token,
an immutable execution lock, at least 3 GiB free GPU memory, zero CUDA compute
applications, and no conflicting HFNet/VINS/ORB/detector/evaluator process.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
from typing import Any, Dict, List, Mapping, Optional, Sequence


ROOT = Path(__file__).resolve().parents[1]
WRAPPER = Path(__file__).resolve()
ENGINE = ROOT / "scripts/run_hfnet_v6_phase_f_h03_1800_3600_v1.py"
RUNNER_TEST = ROOT / "scripts/tests/test_run_hfnet_v6_h07_0001_1720_exact_window_v1.py"


def _load_engine(path: Path):
    specification = importlib.util.spec_from_file_location("hfnet_v6_h07_reused_h03_engine", str(path))
    if specification is None or specification.loader is None:
        raise RuntimeError("SEALED_H03_ENGINE_IMPORT_SPEC_FAILED")
    module = importlib.util.module_from_spec(specification)
    sys.modules[specification.name] = module
    specification.loader.exec_module(module)
    return module


engine = _load_engine(ENGINE)
ENGINE_EXPECTED = {
    "size_bytes": 60_508,
    "sha256": "36b570d223b4718aed658d4333466ef2788fcc8ea14ee1db50cc06ae5b0424a7",
}

ROLE = "HFNET_V6_H07_EXACT_WINDOW_EXTERNAL_LEARNED_SYSTEM_DEVELOPMENT_ONLY"
DEPENDENCY_SCHEMA = "aqua-fe-hfnet-v6-h07-0001-1720-dependency-inventory-v1"
PREFLIGHT_SCHEMA = "aqua-fe-hfnet-v6-h07-0001-1720-preflight-v1"
PREPARED_SCHEMA = "aqua-fe-hfnet-v6-h07-0001-1720-prepared-v1"
LOCK_SCHEMA = "aqua-fe-hfnet-v6-h07-0001-1720-execution-lock-v1"
CHECK_SCHEMA = "aqua-fe-hfnet-v6-h07-0001-1720-prestart-check-v1"
CLAIM_SCHEMA = "aqua-fe-hfnet-v6-h07-0001-1720-process-start-claim-v1"
RESULT_SCHEMA = "aqua-fe-hfnet-v6-h07-0001-1720-run-result-v1"

AUTHORIZATION_TOKEN = "HFNET_V6_H07_0001_1720_ATTEMPT_001_START_EXACTLY_ONCE"

CAMERA_COUNT = 1_720
CAMERA_WIDTH = 640
CAMERA_HEIGHT = 512
PREROLL_FIRST_INDEX = 0
PREROLL_LAST_INDEX = 1_658
SCORE_FIRST_INDEX = 1_659
SCORE_LAST_INDEX = 1_719
MIN_LAST_CAMERA_INDEX = 1_659
MIN_SCORE_POSES = 20
MIN_CONTIGUOUS_SCORE_POSES = 20
MIN_SCORE_KEYFRAMES = 1
MIN_GPU_FREE_MIB = 3_072

CONFIG = ROOT / "configs/published_baselines/hfnet_slam_aqualoc_h07_0001_1720_exact_window_v1.yaml"
SELECTOR = ROOT / "papers/hfnet_v6_h07_0001_1720_exact_window_selector_freeze_v1.json"
MATERIALIZER = ROOT / "scripts/materialize_hfnet_v6_h07_0001_1720_exact_window_v1.py"
MATERIALIZER_TEST = ROOT / "scripts/tests/test_materialize_hfnet_v6_h07_0001_1720_exact_window_v1.py"
INPUT_AUDITOR = ROOT / "scripts/audit_hfnet_v6_h07_0001_1720_exact_window_input_v1.py"
PREPARATION_AUDIT = ROOT / "papers/hfnet_v6_h07_0001_1720_exact_window_preparation_audit_v1.json"
INPUT_ROOT = Path(
    "/mnt/data/AQUA-FE_WS/datasets/hfnet_v6_h07_exact_window_v1/"
    "aqualoc_harbor_h07_0001_1720"
)
ATTEMPT = Path(
    "/mnt/data/AQUA-FE_WS/logs/published_hfnet_slam_v6/fresh_underwater/"
    "aqualoc_harbor_h07_0001_1720/attempt_001"
)
DEPENDENCY_INVENTORY = ROOT / "papers/hfnet_v6_h07_0001_1720_exact_window_dependency_inventory_v1.json"
EXECUTION_LOCK = ROOT / "papers/hfnet_v6_h07_0001_1720_exact_window_execution_lock_v1.json"

EXPECTED_FULL_INPUT = {
    "file_count": 1_724,
    "total_bytes": 280_725_559,
    "tree_sha256": "925c5d3478a63bf84b4ddd96f2a64f240c3e1d3f23d7b8b0901e600516d7d5cf",
    "tree_crc32": "9fd8d477",
}

EXPECTED_IDENTITIES: Mapping[str, Mapping[str, object]] = {
    "passed_stack_lock": {
        "size_bytes": 8_111,
        "sha256": "cb826526a28f28e77f546d4647e16fd19426494e9a15ab01108301136cbfadad",
    },
    "selector": {
        "size_bytes": 6_108,
        "sha256": "51430c83aa7b9870e1c1106f453cd527005c8adcd84990b544fecdea84294387",
    },
    "materializer": {
        "size_bytes": 16_880,
        "sha256": "09eaf20d2d151ee4d08e41157c841f558f32c04b86ea69b2300d3696a4e06247",
    },
    "materializer_test": {
        "size_bytes": 6_288,
        "sha256": "c37c23b4b7df818d93c7570705a794d91efac18011b423046ed37eef0d754d6e",
    },
    "input_auditor": {
        "size_bytes": 19_930,
        "sha256": "2afe567c6f11c5c7494c81222eafbee30dc31a498f26a9714e7b86364b316336",
    },
    "preparation_audit": {
        "size_bytes": 4_388,
        "sha256": "fd54bf547b4487d17fc440b525111d8b97a7cc125b2959b297f118a69ebcf1ec",
    },
    "config": {
        "size_bytes": 2_150,
        "sha256": "97ff0f0e9e2dab17f87ddcb603265a67d841c509d4ffc225ba3695b54a1444e3",
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
_base_audit_stack = engine.audit_stack
_base_build_execution_lock = engine.build_execution_lock
_base_scan_processes = engine.scan_processes
_base_run = engine.run
_base_write_exclusive = engine.write_exclusive


def _query_gpu_resource_gate() -> Dict[str, Any]:
    environment = engine.runtime_environment(DEFAULT_SPEC)
    try:
        memory = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.total,memory.used,memory.free", "--format=csv,noheader,nounits"],
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            universal_newlines=True,
            timeout=10,
            env=environment,
        )
        compute = subprocess.run(
            ["nvidia-smi", "--query-compute-apps=pid,process_name,used_memory", "--format=csv,noheader,nounits"],
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
        conflicts.append({
            "pid": -(index + 1),
            "comm": "RESOURCE_GATE:%s" % error,
            "exact_phase_f_elf": False,
        })
    return sorted(conflicts, key=lambda row: int(row["pid"]))


def derive_runtime_config(source: str, model_dir: Path) -> str:
    if source.count(BASE_MODEL_PATH_LINE) != 1:
        raise engine.ContractError("BASE_CONFIG_MODEL_PATH_LINE_MISMATCH")
    replacement = 'Extractor.modelPath: "%s/"' % engine.absolute(model_dir)
    derived = source.replace(BASE_MODEL_PATH_LINE, replacement)
    before = source.splitlines(keepends=True)
    after = derived.splitlines(keepends=True)
    changed = [index for index, pair in enumerate(zip(before, after)) if pair[0] != pair[1]]
    if len(before) != len(after) or len(changed) != 1:
        raise engine.ContractError("RUNTIME_CONFIG_NOT_EXACTLY_ONE_LINE_CHANGE")
    required = (
        'Camera.type: "KannalaBrandt8"',
        "Camera.width: 640",
        "Camera.height: 512",
        "Camera.fps: 20",
        "IMU.NoiseGyro: 0.001",
        "IMU.NoiseAcc: 0.02",
        "IMU.GyroWalk: 0.00005",
        "IMU.AccWalk: 0.001",
        "IMU.Frequency: 200.0",
        'Extractor.type: "HFNetRT"',
        "Extractor.scaleFactor: 1.2",
        "Extractor.nLevels: 4",
        "Extractor.nFeatures: 675",
        "Extractor.threshold: 0.01",
        "loopClosing: 1",
    )
    if any(source.count(token) != 1 or derived.count(token) != 1 for token in required):
        raise engine.ContractError("RUNTIME_CONFIG_FROZEN_TOKEN_DRIFT")
    return derived


def audit_stack(spec) -> Dict[str, Any]:
    value = _base_audit_stack(spec)
    value["identities"]["reused_h03_engine"] = engine.require_identity(
        ENGINE, ENGINE_EXPECTED, "reused_h03_engine"
    )
    value["identities"]["h07_wrapper"] = engine.file_identity(WRAPPER)
    value["identities"]["runner_test"] = engine.file_identity(RUNNER_TEST)
    value["reuse_boundary"] = {
        "engine_changed": False,
        "dataset_contract_overridden_by_wrapper": True,
        "algorithm_parameters_retuned": False,
    }
    return value


def synchronization_boundary() -> Dict[str, Any]:
    return {
        "source_frame_zero_excluded_before_result": True,
        "camera0_timestamp_ns": 1_523_387_546_122_930_336,
        "earliest_shifted_imu_timestamp_ns": 1_523_387_546_153_594_095,
        "camera0_has_shifted_imu_predecessor": False,
        "feed_first_source_frame": 1,
        "feed_first_frame_reader_bracket_valid": True,
        "official_entry_first_imu_risk": "with frame zero, first_imu-- reaches -1 and later access is out of bounds",
        "synthetic_or_extrapolated_imu_used": False,
        "post_result_window_change": False,
    }


def build_execution_lock(spec, prepared: Mapping[str, Any], locked_at: str) -> Dict[str, Any]:
    value = _base_build_execution_lock(spec, prepared, locked_at)
    identities = prepared["profile"]["preparation_and_stack"]["identities"]
    value["reused_h03_engine"] = identities["reused_h03_engine"]
    value["h07_wrapper"] = identities["h07_wrapper"]
    value["resource_gate"] = {
        "minimum_gpu_free_mib": MIN_GPU_FREE_MIB,
        "no_nvidia_compute_applications": True,
        "no_matching_hfnet_vins_orb_detector_evaluator_processes": True,
        "checked_again_immediately_before_start": True,
    }
    value["synchronization_boundary"] = synchronization_boundary()
    value["claim_boundary"] = {
        "external_learned_system_trajectory_only": True,
        "development_exposed_window": True,
        "accuracy_claimed_by_run_controller": False,
        "superiority_claimed": False,
        "comparison_requires_common_support_evaluation": True,
        "native_reference_pose_count_in_score_window": 13,
        "formal_minimum_30_native_pose_accuracy_ranking_met": False,
    }
    return value


def collect_profile(spec) -> Dict[str, Any]:
    stack = audit_stack(spec)
    return {
        "scientific_role": ROLE,
        "preparation_and_stack": stack,
        "dependencies": engine.audit_dependencies(spec),
        "input": engine.audit_input(spec),
        "selection": {
            "sequence": "AQUALOC harbor_sequence_07",
            "source_frame_indices_inclusive": [1, 1720],
            "camera_count": CAMERA_COUNT,
            "preroll_relative_indices_inclusive": [PREROLL_FIRST_INDEX, PREROLL_LAST_INDEX],
            "preroll_source_indices_inclusive": [1, 1659],
            "score_relative_indices_inclusive": [SCORE_FIRST_INDEX, SCORE_LAST_INDEX],
            "score_source_indices_inclusive": [1660, 1720],
            "preroll_nominal_seconds": 82.95,
            "score_nominal_seconds": 3.05,
            "shared_existing_aqua_fe_window_source_indices_inclusive": [1660, 1720],
            "synchronization_boundary": synchronization_boundary(),
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
write_exclusive = _base_write_exclusive
file_identity = engine.file_identity
read_canonical_json = engine.read_canonical_json
_contiguous_metrics = engine._contiguous_metrics
parse_trajectory = engine.parse_trajectory
snapshot_dependencies = engine.snapshot_dependencies
preflight = engine.preflight
prepare = engine.prepare
lock_execution = engine.lock_execution
check = engine.check


def _seal_h07_result(path: Path, payload: bytes) -> None:
    """Inject H07 source-index/synchronization facts before O_EXCL sealing."""
    value = json.loads(payload.decode("utf-8"))
    value["execution"]["inference_basis"] = "official entry returned after its sequential 1720-image feed loop"
    value["source_index_mapping"] = {
        "feed_relative_zero_is_source_frame": 1,
        "score_relative_indices_inclusive": [1659, 1719],
        "score_source_indices_inclusive": [1660, 1720],
    }
    value["synchronization_boundary"] = synchronization_boundary()
    value["claim_boundary"].update({
        "development_exposed_window": True,
        "source_frame_zero_excluded_before_result": True,
        "synthetic_or_extrapolated_imu_used": False,
        "native_reference_pose_count_in_score_window": 13,
        "formal_minimum_30_native_pose_accuracy_ranking_met": False,
    })
    _base_write_exclusive(path, canonical_json(value))


def run(spec: Spec = DEFAULT_SPEC, *, authorization_token: str = "") -> Dict[str, Any]:
    original = engine.write_exclusive

    def intercept(path: Path, payload: bytes) -> None:
        if Path(path) == spec.run_result:
            _seal_h07_result(Path(path), payload)
        else:
            _base_write_exclusive(Path(path), payload)

    engine.write_exclusive = intercept
    try:
        result = _base_run(spec, authorization_token=authorization_token)
    finally:
        engine.write_exclusive = original
    if spec.run_result.exists() and spec.run_result.is_file():
        sealed = json.loads(spec.run_result.read_text(encoding="utf-8"))
        sealed["run_result"] = engine.file_identity(spec.run_result)
        sealed["sealed"] = True
        return sealed
    return result


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
