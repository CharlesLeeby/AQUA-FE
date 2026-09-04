#!/usr/bin/env python3
"""Additive A09 HFNet co-run overlay for ToDesk/ROS/VINS coexistence.

The frozen A09 controller owns the scientific input, source/local index
mapping, 201-frame score adjudication, one-Popen/no-retry supervisor, child
reaping, and terminal sealing.  This module changes only the project-local
resource-isolation policy and publishes into a fresh co-run namespace.

ToDesk and unrelated CPU/ROS/VINS work are allowed, but another HFNet,
ORB-SLAM, or learned-baseline process is not.  The exact GTX 1650 must expose
at least 3072 MiB free immediately before the sole process-start claim.  This
is development runability evidence only: accuracy, ranking, runtime,
realtime, and paper claims remain prohibited.
"""

from __future__ import annotations

import os
from pathlib import Path
import sys
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import (  # noqa: E402
    run_hfnet_v6_a09_0000_6200_score_6000_6200_warmstart_v1 as formal,
)
from scripts import (  # noqa: E402
    run_hfnet_v6_a08_0000_4660_score_4500_4660_todesk_corun_development_only_v1
    as proven_resource,
)


base = formal.hardened.inherited.profile.base
RUNNER = Path(__file__).resolve()
FORMAL_RUNNER = Path(formal.__file__).resolve()
FORMAL_RUNNER_SIZE = 42_404
FORMAL_RUNNER_SHA256 = "f0f27f8783d2669cdcfa15420c31225743c465a4e75c517fd17f23cb86062f62"
FORMAL_RUNNER_TEST = (
    ROOT
    / "scripts/tests/test_run_hfnet_v6_a09_0000_6200_score_6000_6200_warmstart_v1.py"
)
FORMAL_RUNNER_TEST_SIZE = 18_476
FORMAL_RUNNER_TEST_SHA256 = (
    "995ed80ed34172f410d759b35c4df24608b3b3322154006a4b71a6c51fba0974"
)
FORMAL_RUNNER_FREEZE = (
    ROOT / "papers/hfnet_v6_a09_0000_6200_score_6000_6200_runner_freeze_v1.json"
)
FORMAL_RUNNER_FREEZE_SIZE = 6_771
FORMAL_RUNNER_FREEZE_SHA256 = (
    "6d7bb6ce45d1f83a45ddd40051d96790500fdee6ba8d27bec87fe9778c2cb3aa"
)

# Reuse the fully frozen A08 overlay as the resource-policy helper.  Its
# configure_overlay()/main() are never called here; its own frozen chain pins
# the exercised A05 resource scanner and A09-success GPU-floor precedent.
RESOURCE_HELPER = Path(proven_resource.__file__).resolve()
RESOURCE_HELPER_SIZE = 15_434
RESOURCE_HELPER_SHA256 = (
    "f5a6931ba3419ff5d84a2805c0b8c9be946a4513371f786df4606bfdaa257ca7"
)
RESOURCE_HELPER_TEST = (
    ROOT
    / "scripts/tests/"
    "test_run_hfnet_v6_a08_0000_4660_score_4500_4660_todesk_corun_"
    "development_only_v1.py"
)
RESOURCE_HELPER_TEST_SIZE = 17_403
RESOURCE_HELPER_TEST_SHA256 = (
    "6232f6f7b3bf2d63c2f4e8838bb80f020f93baa952be29a9aa205d31dd3d4108"
)
RESOURCE_HELPER_FREEZE = (
    ROOT
    / "papers/"
    "hfnet_v6_a08_0000_4660_score_4500_4660_todesk_corun_overlay_freeze_v1.json"
)
RESOURCE_HELPER_FREEZE_SIZE = 5_265
RESOURCE_HELPER_FREEZE_SHA256 = (
    "8d918093c0374452d924c55ad945cad500565d71d17bc07d95b6a14435e8b0e7"
)

RUNNER_TEST = (
    ROOT
    / "scripts/tests/"
    "test_run_hfnet_v6_a09_0000_6200_score_6000_6200_todesk_corun_"
    "development_only_v1.py"
)
# Frozen after the process-free test file was finalized.  Authority validation
# remains fail-closed if either identity later drifts.
RUNNER_TEST_SIZE = 18_486
RUNNER_TEST_SHA256 = "e2f443464487c5a30f2e3561e28e678650ac30ab302f01b8b3195a26544a43ef"
RUNNER_TEST_PIN_READY = True

INPUT_ROOT = formal.INPUT_ROOT
INPUT_MANIFEST = formal.INPUT_MANIFEST
INPUT_AUDIT = formal.INPUT_AUDIT
INPUT_PAYLOAD_SHA256 = formal.INPUT_PAYLOAD_SHA256
ATTEMPT = Path(
    "/mnt/data/AQUA-FE_WS/logs/published_hfnet_slam_v6/corun/"
    "old_frozen_positive_windows/"
    "a09_0000_6200_score_6000_6200_todesk_corun_development_only/attempt_001"
)

TIMEOUT_SECONDS = formal.TIMEOUT_SECONDS
MIN_GPU_FREE_MIB = proven_resource.MIN_GPU_FREE_MIB
EXPECTED_GPU_TOTAL_MIB = proven_resource.EXPECTED_GPU_TOTAL_MIB
EXPECTED_GPU_MODEL_TOKEN = proven_resource.EXPECTED_GPU_MODEL_TOKEN
GPU_INFORMATION = proven_resource.GPU_INFORMATION
A09_SUCCESS_OBSERVED_FREE_MIB = proven_resource.A09_SUCCESS_OBSERVED_FREE_MIB

AUTHORIZATION_TOKEN = (
    "HFNET_V6_A09_0000_6200_SCORE_6000_6200_"
    "TODESK_CORUN_DEVELOPMENT_ONLY_ATTEMPT_001_START_EXACTLY_ONCE"
)
SCHEMA = (
    "aqua-fe-hfnet-v6-a09-0000-6200-score-6000-6200-"
    "todesk-corun-development-only-result-v1"
)
PREPARED_SCHEMA = (
    "aqua-fe-hfnet-v6-a09-0000-6200-score-6000-6200-"
    "todesk-corun-development-only-prepared-v1"
)
CLAIM_SCHEMA = (
    "aqua-fe-hfnet-v6-a09-0000-6200-score-6000-6200-"
    "todesk-corun-development-only-claim-v1"
)
CHECK_SCHEMA = (
    "aqua-fe-hfnet-v6-a09-0000-6200-score-6000-6200-"
    "todesk-corun-development-only-check-v1"
)
ADJUDICATION_SCHEMA = (
    "aqua-fe-hfnet-v6-a09-0000-6200-score-6000-6200-"
    "todesk-corun-development-only-adjudication-v1"
)
SCIENTIFIC_ROLE = (
    "TODESK_CORUN_DEVELOPMENT_ONLY_HFNET_NATURAL_HISTORY_RUNABILITY_"
    "ON_JULY14_A09_OLD_FROZEN_POSITIVE_WINDOW"
)

RESOURCE_POLICY: dict[str, Any] = {
    "resource_isolation": False,
    "todesk_corun": True,
    "minimum_prestart_free_gpu_mib": MIN_GPU_FREE_MIB,
    "gpu_total_mib": EXPECTED_GPU_TOTAL_MIB,
    "gpu_model_token": EXPECTED_GPU_MODEL_TOKEN,
    "memory_floor_basis": {
        "formal_a09_success_gate_minimum_free_mib": MIN_GPU_FREE_MIB,
        "formal_a09_success_lock_observed_free_mib": A09_SUCCESS_OBSERVED_FREE_MIB,
    },
    "todesk_compute_app_permitted": True,
    "unrelated_cpu_ros_vins_processes_permitted": True,
    "unrelated_nonbaseline_compute_apps_permitted_only_if_memory_floor_met": True,
    "competing_hfnet_orb_or_learned_baseline_process_permitted": False,
    "runtime_or_realtime_claim_permitted": False,
}

CLAIM_BOUNDARY: dict[str, Any] = {
    "development_only": True,
    "runability_only": True,
    "accuracy_evaluated": False,
    "accuracy_claim_authorized": False,
    "ranking_authorized": False,
    "superiority_claimed": False,
    "formal_paper_claim_authorized": False,
    "fair_head_to_head": False,
    "runtime_or_realtime_claim_authorized": False,
    "resource_isolation": False,
    "retry_permitted": False,
}

# Capture the frozen formal behavior before configure_overlay() changes any
# module bindings.  The A09 installer deliberately restores strict functions;
# _install_overlay_profile() therefore rebinds the additive resource/finalizer
# functions *after every formal installation*.
_FORMAL_INSTALL = formal._install_hardened_profile
_FORMAL_VALIDATE_CODE = formal.validate_code_authority
_FORMAL_EXPECTED_SELECTION = formal._expected_prepared_selection
_FORMAL_EXPECTED_COMPARISON_BOUNDARY = formal._expected_comparison_boundary
_FORMAL_PROFILE_ATOMIC_JSON = formal.profile_atomic_json
_FORMAL_VALIDATE_PREPARED_LAUNCH = formal._validate_prepared_launch
_FORMAL_FINALIZE_RESULT = formal._STRICT_FINALIZE_RESULT
_FORMAL_MINIMAL_FAILURE = formal._STRICT_MINIMAL_TERMINAL_FAILURE
_FORMAL_RUN_ONCE = formal.run_once
_FORMAL_WARM_RUN_WITH_WATCHDOG = formal.warm_run_with_watchdog
_FORMAL_MAIN = formal.main


def _sha256(path: Path) -> str:
    return formal._sha256(path)


def _identity(path: Path) -> dict[str, object]:
    if path.is_symlink() or not path.is_file():
        raise base.ContractError(f"NOT_REGULAR_NONSYMLINK_FILE:{path}")
    return {
        "path": str(path.resolve()),
        "size_bytes": path.stat().st_size,
        "sha256": _sha256(path),
    }


def _require_file(path: Path, size: int, sha256: str, label: str) -> dict[str, object]:
    value = _identity(path)
    if value["size_bytes"] != size or value["sha256"] != sha256:
        raise base.ContractError(f"{label}_IDENTITY_MISMATCH")
    return value


def validate_a09_success_precedent() -> dict[str, object]:
    return proven_resource.validate_a09_success_precedent()


def scan_forbidden_processes(proc_root: Path = Path("/proc")) -> list[dict[str, object]]:
    return proven_resource.scan_forbidden_processes(proc_root)


def resource_gate(
    minimum_free_mib: int = MIN_GPU_FREE_MIB,
    *,
    proc_root: Path = Path("/proc"),
    gpu_information: Path = GPU_INFORMATION,
) -> dict[str, Any]:
    return proven_resource.resource_gate(
        minimum_free_mib,
        proc_root=proc_root,
        gpu_information=gpu_information,
    )


def validate_code_authority() -> dict[str, object]:
    value = dict(_FORMAL_VALIDATE_CODE())
    value["frozen_a09_controller"] = _require_file(
        FORMAL_RUNNER,
        FORMAL_RUNNER_SIZE,
        FORMAL_RUNNER_SHA256,
        "FROZEN_A09_CONTROLLER",
    )
    value["frozen_a09_controller_test"] = _require_file(
        FORMAL_RUNNER_TEST,
        FORMAL_RUNNER_TEST_SIZE,
        FORMAL_RUNNER_TEST_SHA256,
        "FROZEN_A09_CONTROLLER_TEST",
    )
    value["frozen_a09_controller_receipt"] = _require_file(
        FORMAL_RUNNER_FREEZE,
        FORMAL_RUNNER_FREEZE_SIZE,
        FORMAL_RUNNER_FREEZE_SHA256,
        "FROZEN_A09_CONTROLLER_RECEIPT",
    )
    value["proven_corun_resource_helper"] = _require_file(
        RESOURCE_HELPER,
        RESOURCE_HELPER_SIZE,
        RESOURCE_HELPER_SHA256,
        "PROVEN_CORUN_RESOURCE_HELPER",
    )
    value["proven_corun_resource_helper_test"] = _require_file(
        RESOURCE_HELPER_TEST,
        RESOURCE_HELPER_TEST_SIZE,
        RESOURCE_HELPER_TEST_SHA256,
        "PROVEN_CORUN_RESOURCE_HELPER_TEST",
    )
    value["proven_corun_resource_helper_receipt"] = _require_file(
        RESOURCE_HELPER_FREEZE,
        RESOURCE_HELPER_FREEZE_SIZE,
        RESOURCE_HELPER_FREEZE_SHA256,
        "PROVEN_CORUN_RESOURCE_HELPER_RECEIPT",
    )
    value["a09_success_gpu_floor_precedent"] = validate_a09_success_precedent()
    if not RUNNER_TEST_PIN_READY:
        raise base.ContractError("A09_CORUN_OVERLAY_TEST_IDENTITY_PIN_PENDING")
    value["corun_overlay_test"] = _require_file(
        RUNNER_TEST,
        RUNNER_TEST_SIZE,
        RUNNER_TEST_SHA256,
        "A09_CORUN_OVERLAY_TEST",
    )
    return value


def paths() -> dict[str, Path]:
    return {
        "subset_times": ATTEMPT / "cam0_times_source_0000_6200_local_0000_6200.txt",
        "runtime_config": ATTEMPT / "runtime_config_model_path_only.yaml",
        "local_model": ATTEMPT / "run_local_model/HFNet-RT/HF-Net.onnx",
        "local_cache": ATTEMPT / "run_local_model/HFNet-RT/HF-Net.cache",
        "prepared": ATTEMPT / "prepared_manifest.json",
        "claim": ATTEMPT / "process_start_claim.json",
        "result": ATTEMPT / "run_result.json",
        "stdout": ATTEMPT / "headless.stdout.log",
        "stderr": ATTEMPT / "headless.stderr.log",
        "result_dir": ATTEMPT / "result",
        "score_trajectory": ATTEMPT / "result/trajectory_score_source_6000_6200.txt",
    }


def _expected_selection() -> dict[str, Any]:
    value = dict(_FORMAL_EXPECTED_SELECTION())
    value["execution_profile"] = "TODESK_CORUN_DEVELOPMENT_ONLY"
    value["resource_isolation"] = False
    return value


def _expected_comparison_boundary() -> dict[str, Any]:
    value = dict(_FORMAL_EXPECTED_COMPARISON_BOUNDARY())
    value.update(
        {
            "runability_only": True,
            "accuracy_gate_open": False,
            "ranking_authorized": False,
            "runtime_or_realtime_claim_permitted": False,
            "timeout_is_safety_ceiling_not_runtime_measurement": True,
            "timeout_seconds": TIMEOUT_SECONDS,
            "formal_resource_contract_relaxed_for_todesk_or_unrelated_ros": True,
            "resource_isolation": False,
            "todesk_corun": True,
            "historical_accuracy_values_are_provenance_only": True,
            "reason": (
                "HFNet receives source history 0..5999 while historical learned-plus-KLT "
                "and pure-KLT controls cold-start at source 6000; the user-waived co-run "
                "profile also permits nonbaseline resource users, so this remains "
                "development runability evidence only"
            ),
        }
    )
    return value


def _decorate_terminal(value: Mapping[str, Any]) -> dict[str, Any]:
    result = dict(value)
    boundary = dict(result.get("claim_boundary", {}))
    boundary.update(CLAIM_BOUNDARY)
    result["claim_boundary"] = boundary
    result["resource_context"] = {
        "resource_isolation": False,
        "todesk_corun": True,
        "minimum_prestart_free_gpu_mib": MIN_GPU_FREE_MIB,
        "runtime_or_realtime_claim_permitted": False,
    }
    return result


def _finalize_result_total(raw: Mapping[str, Any]) -> dict[str, Any]:
    return _decorate_terminal(_FORMAL_FINALIZE_RESULT(raw))


def _minimal_terminal_failure(
    raw: Mapping[str, Any], error: BaseException
) -> dict[str, Any]:
    return _decorate_terminal(_FORMAL_MINIMAL_FAILURE(raw, error))


def _install_overlay_profile() -> None:
    """Install A09 first, then rebind the additive resource delta every time."""
    _FORMAL_INSTALL()
    base.resource_gate = resource_gate
    formal.hardened._finalize_result_total = _finalize_result_total
    formal.hardened._minimal_terminal_failure = _minimal_terminal_failure


def profile_atomic_json(path: Path, value: object, exclusive: bool = False) -> None:
    _install_overlay_profile()
    if path == paths()["prepared"] and isinstance(value, dict):
        value["claim_boundary"] = dict(CLAIM_BOUNDARY)
        value["resource_policy"] = dict(RESOURCE_POLICY)
        value.setdefault("launch", {})["minimum_prestart_free_gpu_mib"] = (
            MIN_GPU_FREE_MIB
        )
    _FORMAL_PROFILE_ATOMIC_JSON(path, value, exclusive=exclusive)


def _validate_prepared_launch(prepared: Mapping[str, Any]) -> None:
    _FORMAL_VALIDATE_PREPARED_LAUNCH(prepared)
    if (
        prepared.get("claim_boundary") != CLAIM_BOUNDARY
        or prepared.get("resource_policy") != RESOURCE_POLICY
        or prepared.get("launch", {}).get("minimum_prestart_free_gpu_mib")
        != MIN_GPU_FREE_MIB
    ):
        raise base.ContractError("A09_CORUN_PREPARED_RESOURCE_CONTRACT_MISMATCH")


def check() -> dict[str, object]:
    # formal._install_hardened_profile() restores the strict gate by design;
    # this installer must therefore run first and rebind the co-run gate last.
    _install_overlay_profile()
    base.resource_gate = resource_gate
    value = formal._HARDENED_CHECK()
    value["schema_version"] = CHECK_SCHEMA
    value["resource_policy"] = dict(RESOURCE_POLICY)
    return value


def configure_overlay() -> None:
    """Install additive in-memory bindings only; never validate/prepare/run."""
    formal.RUNNER = RUNNER
    formal.ATTEMPT = ATTEMPT
    formal.AUTHORIZATION_TOKEN = AUTHORIZATION_TOKEN
    formal.SCHEMA = SCHEMA
    formal.PREPARED_SCHEMA = PREPARED_SCHEMA
    formal.CLAIM_SCHEMA = CLAIM_SCHEMA
    formal.CHECK_SCHEMA = CHECK_SCHEMA
    formal.ADJUDICATION_SCHEMA = ADJUDICATION_SCHEMA
    formal.SCIENTIFIC_ROLE = SCIENTIFIC_ROLE
    formal.TIMEOUT_SECONDS = TIMEOUT_SECONDS
    formal.paths = paths
    formal.validate_code_authority = validate_code_authority
    formal._expected_prepared_selection = _expected_selection
    formal._expected_comparison_boundary = _expected_comparison_boundary
    formal.profile_atomic_json = profile_atomic_json
    formal._validate_prepared_launch = _validate_prepared_launch
    formal.check = check
    formal._install_hardened_profile = _install_overlay_profile
    base.MIN_GPU_FREE_MIB = MIN_GPU_FREE_MIB
    base.resource_gate = resource_gate


def main() -> int:
    configure_overlay()
    return _FORMAL_MAIN()


if __name__ == "__main__":
    raise SystemExit(main())
