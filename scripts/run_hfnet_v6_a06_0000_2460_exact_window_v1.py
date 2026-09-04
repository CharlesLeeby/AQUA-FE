#!/usr/bin/env python3
"""Fail-closed A06 exact-window controller over the sealed H03 HFNet engine.

This wrapper configures the already exercised Phase-F one-shot engine for the
AQUALOC Archaeology sequence 06 feed at source frames 0000..2460.  Frames
0000..2209 are initialization/preroll only; source frames 2210..2460 are the
frozen score window shared with the existing AQUA-FE development evidence.

The wrapper intentionally does not weaken the engine's O_EXCL start claim,
single-Popen, no-retry, synchronous-reap, immutable-input, dependency-closure,
or terminal-result contracts.  It adds a fail-closed GPU/process resource gate
and pins the reused engine in the execution lock.  Running still requires the
exact A06 authorization token; preparation actions never start HFNet.
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
ENGINE = ROOT / "scripts/run_hfnet_v6_phase_f_h03_1800_3600_v1.py"
RUNNER_TEST = ROOT / "scripts/tests/test_run_hfnet_v6_a06_0000_2460_exact_window_v1.py"


def _load_engine(path: Path):
    specification = importlib.util.spec_from_file_location("hfnet_v6_a06_reused_h03_engine", str(path))
    if specification is None or specification.loader is None:
        raise RuntimeError("SEALED_H03_ENGINE_IMPORT_SPEC_FAILED")
    module = importlib.util.module_from_spec(specification)
    sys.modules[specification.name] = module
    specification.loader.exec_module(module)
    return module


engine = _load_engine(ENGINE)

# A direct, non-circular pin of the unchanged implementation engine.  The A06
# wrapper itself is captured by the prepared profile and immutable execution
# lock, so any later wrapper drift invalidates check/run.
ENGINE_EXPECTED = {
    "size_bytes": 60_508,
    "sha256": "36b570d223b4718aed658d4333466ef2788fcc8ea14ee1db50cc06ae5b0424a7",
}

ROLE = "HFNET_V6_A06_EXACT_WINDOW_EXTERNAL_LEARNED_SYSTEM_DEVELOPMENT_ONLY"
DEPENDENCY_SCHEMA = "aqua-fe-hfnet-v6-a06-0000-2460-dependency-inventory-v1"
PREFLIGHT_SCHEMA = "aqua-fe-hfnet-v6-a06-0000-2460-preflight-v1"
PREPARED_SCHEMA = "aqua-fe-hfnet-v6-a06-0000-2460-prepared-v1"
LOCK_SCHEMA = "aqua-fe-hfnet-v6-a06-0000-2460-execution-lock-v1"
CHECK_SCHEMA = "aqua-fe-hfnet-v6-a06-0000-2460-prestart-check-v1"
CLAIM_SCHEMA = "aqua-fe-hfnet-v6-a06-0000-2460-process-start-claim-v1"
RESULT_SCHEMA = "aqua-fe-hfnet-v6-a06-0000-2460-run-result-v1"

AUTHORIZATION_TOKEN = "HFNET_V6_A06_0000_2460_ATTEMPT_001_START_EXACTLY_ONCE"

CAMERA_COUNT = 2_461
CAMERA_WIDTH = 968
CAMERA_HEIGHT = 608
PREROLL_FIRST_INDEX = 0
PREROLL_LAST_INDEX = 2_209
SCORE_FIRST_INDEX = 2_210
SCORE_LAST_INDEX = 2_460
MIN_LAST_CAMERA_INDEX = 2_210
MIN_SCORE_POSES = 20
MIN_CONTIGUOUS_SCORE_POSES = 20
MIN_SCORE_KEYFRAMES = 1
MIN_GPU_FREE_MIB = 3_072

CONFIG = ROOT / "configs/published_baselines/hfnet_slam_aqualoc_a06_0000_2460_exact_window_v1.yaml"
SELECTOR = ROOT / "papers/hfnet_v6_a06_0000_2460_exact_window_selector_freeze_v1.json"
MATERIALIZER = ROOT / "scripts/materialize_hfnet_v6_a06_0000_2460_exact_window_v1.py"
MATERIALIZER_TEST = ROOT / "scripts/tests/test_materialize_hfnet_v6_a06_0000_2460_exact_window_v1.py"
INPUT_AUDITOR = ROOT / "scripts/audit_hfnet_v6_a06_0000_2460_exact_window_input_v1.py"
PREPARATION_AUDIT = ROOT / "papers/hfnet_v6_a06_0000_2460_exact_window_preparation_audit_v1.json"
INPUT_ROOT = Path(
    "/mnt/data/AQUA-FE_WS/datasets/hfnet_v6_a06_exact_window_v1/"
    "aqualoc_archaeology_a06_0000_2460"
)
ATTEMPT = Path(
    "/mnt/data/AQUA-FE_WS/logs/published_hfnet_slam_v6/fresh_underwater/"
    "aqualoc_archaeology_a06_0000_2460/attempt_001"
)
DEPENDENCY_INVENTORY = ROOT / "papers/hfnet_v6_a06_0000_2460_exact_window_dependency_inventory_v1.json"
EXECUTION_LOCK = ROOT / "papers/hfnet_v6_a06_0000_2460_exact_window_execution_lock_v1.json"

EXPECTED_FULL_INPUT = {
    "file_count": 2_465,
    "total_bytes": 548_733_078,
    "tree_sha256": "86176048bfa6c9c9f3cf1a2e9771b7143d88dd079deaac91f90c2d48cde34e93",
    "tree_crc32": "2d47fa4b",
}

EXPECTED_IDENTITIES: Mapping[str, Mapping[str, object]] = {
    "passed_stack_lock": {
        "size_bytes": 8_111,
        "sha256": "cb826526a28f28e77f546d4647e16fd19426494e9a15ab01108301136cbfadad",
    },
    "selector": {
        "size_bytes": 8_273,
        "sha256": "1d0937320c087cb73911db7a5c55d8cde40d0bf0c800c4cf42aba68342b72b15",
    },
    "materializer": {
        "size_bytes": 16_321,
        "sha256": "2ac7025c70a7aac48783b0ee37e9586aae43c00927a1183304a88ad05f796264",
    },
    "materializer_test": {
        "size_bytes": 6_823,
        "sha256": "2dcdafadc3572ff2122d373e62596d6cb1757549e5023147261f7fde2589f6aa",
    },
    "input_auditor": {
        "size_bytes": 17_765,
        "sha256": "b41412233b3c403d0ca8fb2841374a3c97484cce7bbe260bb4be8c780a46d3a2",
    },
    "preparation_audit": {
        "size_bytes": 3_697,
        "sha256": "9fc48aef5c8ac2ec54cfd7652d2ea6fb99d21bc796441a28ddb039a239915242",
    },
    "config": {
        "size_bytes": 2_037,
        "sha256": "37ec8f0f274818b3a8f952a535d9be87dae0f8d0436ce05503381791ace69db6",
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

# Preserve the reused implementations before patching their module globals.
_base_audit_stack = engine.audit_stack
_base_build_execution_lock = engine.build_execution_lock
_base_scan_processes = engine.scan_processes


def _query_gpu_resource_gate() -> Dict[str, Any]:
    """Return a deterministic fail-closed snapshot of the sole CUDA device."""
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
    """Combine the engine's scoped /proc audit with a fail-closed GPU gate."""
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


def derive_runtime_config(source: str, model_dir: Path) -> str:
    """Permit exactly the attempt-local HFNet modelPath substitution."""
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
        'Camera.type: "PinHole"',
        "Camera.width: 968",
        "Camera.height: 608",
        "Camera.fps: 20",
        "IMU.NoiseGyro: 0.003",
        "IMU.NoiseAcc: 0.05",
        "IMU.GyroWalk: 0.0001",
        "IMU.AccWalk: 0.0015",
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
    value["identities"]["a06_wrapper"] = engine.file_identity(WRAPPER)
    value["identities"]["runner_test"] = engine.file_identity(RUNNER_TEST)
    value["reuse_boundary"] = {
        "engine_changed": False,
        "dataset_contract_overridden_by_wrapper": True,
        "algorithm_parameters_retuned": False,
    }
    return value


def build_execution_lock(spec, prepared: Mapping[str, Any], locked_at: str) -> Dict[str, Any]:
    value = _base_build_execution_lock(spec, prepared, locked_at)
    identities = prepared["profile"]["preparation_and_stack"]["identities"]
    value["reused_h03_engine"] = identities["reused_h03_engine"]
    value["a06_wrapper"] = identities["a06_wrapper"]
    value["resource_gate"] = {
        "minimum_gpu_free_mib": MIN_GPU_FREE_MIB,
        "no_nvidia_compute_applications": True,
        "no_matching_hfnet_vins_orb_detector_evaluator_processes": True,
        "checked_again_immediately_before_start": True,
    }
    value["claim_boundary"] = {
        "external_learned_system_trajectory_only": True,
        "development_exposed_window": True,
        "accuracy_claimed_by_run_controller": False,
        "superiority_claimed": False,
        "comparison_requires_common_support_evaluation": True,
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
            "sequence": "AQUALOC archaeology_sequence_06",
            "source_frame_indices_inclusive": [0, 2_460],
            "camera_count": CAMERA_COUNT,
            "preroll_relative_indices_inclusive": [PREROLL_FIRST_INDEX, PREROLL_LAST_INDEX],
            "score_relative_indices_inclusive": [SCORE_FIRST_INDEX, SCORE_LAST_INDEX],
            "preroll_nominal_seconds": 110.5,
            "score_nominal_seconds": 12.55,
            "shared_existing_aqua_fe_window_source_indices_inclusive": [2_210, 2_460],
        },
    }


# Configure every global consumed by functions implemented in the engine.  Its
# functions retain their engine-module globals, hence assignment is explicit.
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

# Public API aliases used by tests and by the CLI below.
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
