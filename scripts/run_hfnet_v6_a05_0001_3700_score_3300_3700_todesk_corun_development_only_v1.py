#!/usr/bin/env python3
"""Additive A05 HFNet co-run overlay for ToDesk/ROS/VINS coexistence.

This module leaves the frozen A05 controller and its input untouched.  It
changes only the project-local resource-isolation policy and publishes into a
fresh co-run namespace.  ToDesk and unrelated CPU/ROS/VINS processes are
allowed, but a competing HFNet/ORB/learned-baseline process is not.  The exact
GTX 1650 must still expose at least 3072 MiB free immediately before the sole
HFNet Popen.  That floor is the frozen formal A09 gate that preceded a
successful 4401-frame run (3204 MiB was observed by its successful lock).

All input, code, model, configuration, timeout, score adjudication, exactly-once
Popen, no-retry, child-reaping, and terminal O_EXCL behavior is delegated to
the frozen A05 controller.  The result is development runability evidence
only; accuracy, ranking, runtime, realtime, and paper claims are prohibited.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import stat
import subprocess
import sys
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import (  # noqa: E402
    run_hfnet_v6_a05_0001_3700_score_3300_3700_warmstart_v1 as formal,
)


base = formal.inherited.profile.base
RUNNER = Path(__file__).resolve()
FORMAL_RUNNER = Path(formal.__file__).resolve()
FORMAL_RUNNER_SIZE = 69_153
FORMAL_RUNNER_SHA256 = "240e4f219c1ef86f9ebb78077ec14ede3cb09002773f00f26747745ad10eab3d"
FORMAL_RUNNER_FREEZE = (
    ROOT / "papers/hfnet_v6_a05_0001_3700_score_3300_3700_runner_freeze_v1.json"
)
FORMAL_RUNNER_FREEZE_SIZE = 5_006
FORMAL_RUNNER_FREEZE_SHA256 = (
    "ae8d65c0991a47df960e29141d0074e5213477f17e2da0d04f3e94601c76ce5e"
)
RUNNER_TEST = (
    ROOT
    / "scripts/tests/"
    "test_run_hfnet_v6_a05_0001_3700_score_3300_3700_todesk_corun_"
    "development_only_v1.py"
)
# Filled only after the process-free test file is final.  Execution stays
# fail-closed until both values are frozen.
RUNNER_TEST_SIZE = 11_348
RUNNER_TEST_SHA256 = "b0a67850f2c744a4ed745dbf0b4a0ccf7d273a9305c7257bb58cd50389cbd691"
RUNNER_TEST_PIN_READY = True

A09_SUCCESS_LOCK = (
    ROOT
    / "papers/hfnet_v6_a09_0000_4400_score_4000_4400_"
    "warmstart_execution_lock_v2.json"
)
A09_SUCCESS_LOCK_SIZE = 5_203
A09_SUCCESS_LOCK_SHA256 = (
    "7200df40e0e28eec0a50f2e46efd45d3076c94ea31258105b870904e793f4217"
)
A09_SUCCESS_FREEZE = (
    ROOT
    / "papers/hfnet_v6_a09_0000_4400_score_4000_4400_"
    "warmstart_terminal_outcome_freeze_v1.json"
)
A09_SUCCESS_FREEZE_SIZE = 6_762
A09_SUCCESS_FREEZE_SHA256 = (
    "0645080a46e0e6110210cc387693c98b23dc0860c853cbef3d2c6c98ce589d69"
)

INPUT_ROOT = formal.INPUT_ROOT
INPUT_MANIFEST = formal.INPUT_MANIFEST
INPUT_AUDIT = formal.INPUT_AUDIT
INPUT_PAYLOAD_SHA256 = formal.INPUT_PAYLOAD_SHA256
ATTEMPT = Path(
    "/mnt/data/AQUA-FE_WS/logs/published_hfnet_slam_v6/corun/"
    "old_frozen_positive_windows/"
    "a05_0001_3700_score_3300_3700_todesk_corun_development_only/attempt_001"
)

TIMEOUT_SECONDS = formal.TIMEOUT_SECONDS
MIN_GPU_FREE_MIB = 3_072
EXPECTED_GPU_TOTAL_MIB = 4_096
EXPECTED_GPU_MODEL_TOKEN = "GTX 1650"
GPU_INFORMATION = Path("/proc/driver/nvidia/gpus/0000:26:00.0/information")
A09_SUCCESS_OBSERVED_FREE_MIB = 3_204

AUTHORIZATION_TOKEN = (
    "HFNET_V6_A05_0001_3700_SCORE_3300_3700_"
    "TODESK_CORUN_DEVELOPMENT_ONLY_ATTEMPT_001_START_EXACTLY_ONCE"
)
SCHEMA = (
    "aqua-fe-hfnet-v6-a05-0001-3700-score-3300-3700-"
    "todesk-corun-development-only-result-v1"
)
PREPARED_SCHEMA = (
    "aqua-fe-hfnet-v6-a05-0001-3700-score-3300-3700-"
    "todesk-corun-development-only-prepared-v1"
)
CLAIM_SCHEMA = (
    "aqua-fe-hfnet-v6-a05-0001-3700-score-3300-3700-"
    "todesk-corun-development-only-claim-v1"
)
CHECK_SCHEMA = (
    "aqua-fe-hfnet-v6-a05-0001-3700-score-3300-3700-"
    "todesk-corun-development-only-check-v1"
)
ADJUDICATION_SCHEMA = (
    "aqua-fe-hfnet-v6-a05-0001-3700-score-3300-3700-"
    "todesk-corun-development-only-adjudication-v1"
)
SCIENTIFIC_ROLE = (
    "TODESK_CORUN_DEVELOPMENT_ONLY_HFNET_NATURAL_HISTORY_RUNABILITY_"
    "ON_JULY14_OLD_FROZEN_POSITIVE_WINDOW"
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

_FORMAL_VALIDATE_CODE = formal.validate_code_authority
_FORMAL_EXPECTED_SELECTION = formal._expected_prepared_selection
_FORMAL_EXPECTED_COMPARISON_BOUNDARY = formal._expected_comparison_boundary
_FORMAL_PROFILE_ATOMIC_JSON = formal.profile_atomic_json
_FORMAL_VALIDATE_PREPARED_LAUNCH = formal._validate_prepared_launch
_FORMAL_FINALIZE_RESULT = formal._finalize_result_total
_FORMAL_MINIMAL_FAILURE = formal._minimal_terminal_failure
_FORMAL_RUN_ONCE = formal.run_once
_FORMAL_WARM_RUN_WITH_WATCHDOG = formal.warm_run_with_watchdog


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
    """Bind the GPU floor to the formal A09 success, not the unrun 2800-MiB draft."""
    lock_pin = _require_file(
        A09_SUCCESS_LOCK,
        A09_SUCCESS_LOCK_SIZE,
        A09_SUCCESS_LOCK_SHA256,
        "A09_SUCCESS_EXECUTION_LOCK",
    )
    freeze_pin = _require_file(
        A09_SUCCESS_FREEZE,
        A09_SUCCESS_FREEZE_SIZE,
        A09_SUCCESS_FREEZE_SHA256,
        "A09_SUCCESS_TERMINAL_FREEZE",
    )
    lock = json.loads(A09_SUCCESS_LOCK.read_text(encoding="utf-8"))
    freeze = json.loads(A09_SUCCESS_FREEZE.read_text(encoding="utf-8"))
    runner_check = lock.get("fresh_ready_evidence", {}).get("runner_check", {})
    snapshot = lock.get("fresh_ready_evidence", {}).get("immediate_snapshot", {})
    execution = freeze.get("execution", {})
    adjudication = freeze.get("score_adjudication", {})
    if (
        lock.get("status")
        != "AUTHORIZED_EXACTLY_ONE_HFNET_ELF_START_ATTEMPT_001_NO_RETRY_V2"
        or runner_check.get("ready") is not True
        or runner_check.get("minimum_free_mib") != MIN_GPU_FREE_MIB
        or runner_check.get("free_mib") != A09_SUCCESS_OBSERVED_FREE_MIB
        or snapshot.get("gpu_total_mib") != EXPECTED_GPU_TOTAL_MIB
        or freeze.get("status") != "SEALED_TERMINAL_PASS_NO_RETRY"
        or execution.get("official_hfnet_elf_popen_invocations") != 1
        or execution.get("raw_returncode") != 0
        or execution.get("timed_out") is not False
        or execution.get("retry_performed") is not False
        or adjudication.get("passed") is not True
        or adjudication.get("pose_count") != 401
    ):
        raise base.ContractError("A09_SUCCESS_GPU_FLOOR_PRECEDENT_MISMATCH")
    return {
        "execution_lock": lock_pin,
        "terminal_outcome_freeze": freeze_pin,
        "gpu_total_mib": EXPECTED_GPU_TOTAL_MIB,
        "minimum_free_mib": MIN_GPU_FREE_MIB,
        "observed_success_lock_free_mib": A09_SUCCESS_OBSERVED_FREE_MIB,
    }


def validate_code_authority() -> dict[str, object]:
    value = dict(_FORMAL_VALIDATE_CODE())
    value["frozen_a05_controller"] = _require_file(
        FORMAL_RUNNER,
        FORMAL_RUNNER_SIZE,
        FORMAL_RUNNER_SHA256,
        "FROZEN_A05_CONTROLLER",
    )
    value["frozen_a05_controller_receipt"] = _require_file(
        FORMAL_RUNNER_FREEZE,
        FORMAL_RUNNER_FREEZE_SIZE,
        FORMAL_RUNNER_FREEZE_SHA256,
        "FROZEN_A05_CONTROLLER_RECEIPT",
    )
    value["a09_success_gpu_floor_precedent"] = validate_a09_success_precedent()
    if not RUNNER_TEST_PIN_READY:
        raise base.ContractError("CORUN_OVERLAY_TEST_IDENTITY_PIN_PENDING")
    value["corun_overlay_test"] = _require_file(
        RUNNER_TEST,
        RUNNER_TEST_SIZE,
        RUNNER_TEST_SHA256,
        "CORUN_OVERLAY_TEST",
    )
    return value


def _expected_selection() -> dict[str, Any]:
    value = dict(_FORMAL_EXPECTED_SELECTION())
    value["execution_profile"] = "TODESK_CORUN_DEVELOPMENT_ONLY"
    value["resource_isolation"] = False
    return value


def _expected_comparison_boundary() -> dict[str, Any]:
    return {
        "runability_only": True,
        "accuracy_gate_open": False,
        "ranking_authorized": False,
        "runtime_or_realtime_claim_permitted": False,
        "historical_accuracy_values_are_provenance_only": True,
        "resource_isolation": False,
        "reason": (
            "HFNet receives source history 1..3299 while the historical learned-plus-KLT "
            "and pure-KLT positives cold-start at source 3300; this co-run profile also "
            "permits nonbaseline resource users, so it supports development runability only"
        ),
    }


def _baseline_reason(name: str) -> str | None:
    normalized = Path(name.strip()).name.lower().replace(" ", "_")
    exact = {
        "mono_inertial_euroc_headless_v3",
        "mono_inertial_euroc",
        "stereo_inertial_euroc",
    }
    if normalized in exact or "hfnet_slam" in normalized or normalized.startswith("run_hfnet_"):
        return "HFNET_PROCESS"
    if any(token in normalized for token in ("orb_slam", "orb-slam", "orbslam")):
        return "ORB_SLAM_PROCESS"
    if any(
        token in normalized
        for token in (
            "droid_slam",
            "droid-slam",
            "dpvo",
            "lightglue",
            "superpoint",
            "loftr",
            "xfeat",
        )
    ):
        return "LEARNED_BASELINE_PROCESS"
    return None


def _ancestor_pids(pid: int) -> set[int]:
    ancestors = {pid}
    current = pid
    while current > 1:
        try:
            fields = (Path("/proc") / str(current) / "stat").read_text(
                encoding="ascii", errors="replace"
            ).split()
            parent = int(fields[3])
        except (OSError, ValueError, IndexError):
            break
        if parent in ancestors or parent <= 0:
            break
        ancestors.add(parent)
        current = parent
    return ancestors


def scan_forbidden_processes(proc_root: Path = Path("/proc")) -> list[dict[str, object]]:
    """Ignore ToDesk/ROS/VINS; reject only competing learned-system programs."""
    conflicts: list[dict[str, object]] = []
    ignored = _ancestor_pids(os.getpid()) if proc_root == Path("/proc") else {os.getpid()}
    try:
        entries = list(proc_root.iterdir())
    except OSError as error:
        raise base.ContractError(f"PROC_SCAN_FAILED:{error}") from error
    for entry in entries:
        if not entry.name.isdigit():
            continue
        pid = int(entry.name)
        if pid in ignored:
            continue
        executable = ""
        arguments: list[str] = []
        try:
            executable = Path(os.readlink(entry / "exe")).name
        except OSError:
            pass
        try:
            arguments = [
                item.decode("utf-8", "replace")
                for item in (entry / "cmdline").read_bytes().split(b"\0")
                if item
            ]
        except OSError:
            pass
        reason = _baseline_reason(executable)
        matched = executable
        if reason is None:
            for argument in arguments[1:]:
                candidate = Path(argument).name
                reason = _baseline_reason(candidate)
                if reason is not None:
                    matched = candidate
                    break
        if reason is not None:
            conflicts.append(
                {
                    "pid": pid,
                    "reason": reason,
                    "matched_name": matched,
                    "executable": executable,
                }
            )
    return sorted(conflicts, key=lambda row: int(row["pid"]))


def _parse_compute_rows(payload: str) -> tuple[list[dict[str, object]], list[str]]:
    rows: list[dict[str, object]] = []
    errors: list[str] = []
    for line_number, raw in enumerate(payload.splitlines(), start=1):
        if not raw.strip():
            continue
        fields = [item.strip() for item in raw.split(",")]
        if len(fields) != 3:
            errors.append(f"GPU_COMPUTE_ROW_{line_number}_INVALID")
            continue
        try:
            pid = int(fields[0])
            used_mib = int(fields[2])
        except ValueError:
            errors.append(f"GPU_COMPUTE_ROW_{line_number}_INVALID")
            continue
        rows.append(
            {
                "pid": pid,
                "process_name": fields[1],
                "used_memory_mib": used_mib,
                "forbidden_reason": _baseline_reason(fields[1]),
            }
        )
    return rows, errors


def _gpu_model(information_path: Path) -> str | None:
    try:
        mode = os.stat(information_path, follow_symlinks=False).st_mode
        if not stat.S_ISREG(mode):
            return None
        for line in information_path.read_text(encoding="utf-8", errors="replace").splitlines():
            if line.startswith("Model:"):
                return line.split(":", 1)[1].strip()
    except OSError:
        return None
    return None


def resource_gate(
    minimum_free_mib: int = MIN_GPU_FREE_MIB,
    *,
    proc_root: Path = Path("/proc"),
    gpu_information: Path = GPU_INFORMATION,
) -> dict[str, Any]:
    """Allow nonbaseline co-users only when the proven GPU floor remains."""
    if minimum_free_mib != MIN_GPU_FREE_MIB:
        raise base.ContractError("CORUN_GPU_FLOOR_NOT_FROZEN_3072_MIB")
    memory = subprocess.run(
        [
            "nvidia-smi",
            "--query-gpu=memory.total,memory.used,memory.free",
            "--format=csv,noheader,nounits",
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )
    compute = subprocess.run(
        [
            "nvidia-smi",
            "--query-compute-apps=pid,process_name,used_memory",
            "--format=csv,noheader,nounits",
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )
    errors: list[str] = []
    total_mib: int | None = None
    used_mib: int | None = None
    free_mib: int | None = None
    rows = [row for row in memory.stdout.splitlines() if row.strip()]
    if memory.returncode != 0 or len(rows) != 1:
        errors.append("GPU_MEMORY_QUERY_INVALID")
    else:
        try:
            total_mib, used_mib, free_mib = [
                int(item.strip()) for item in rows[0].split(",")
            ]
        except (ValueError, TypeError):
            errors.append("GPU_MEMORY_ROW_INVALID")
    gpu_model = _gpu_model(gpu_information)
    if gpu_model is None or EXPECTED_GPU_MODEL_TOKEN not in gpu_model:
        errors.append("GPU_MODEL_NOT_FROZEN_GTX1650")
    if total_mib != EXPECTED_GPU_TOTAL_MIB:
        errors.append("GPU_TOTAL_MEMORY_NOT_FROZEN_4096_MIB")
    if free_mib is None or free_mib < minimum_free_mib:
        errors.append("GPU_FREE_MEMORY_BELOW_FORMAL_A09_SUCCESS_FLOOR")

    compute_rows, compute_errors = _parse_compute_rows(compute.stdout)
    if compute.returncode != 0:
        errors.append("GPU_COMPUTE_QUERY_INVALID")
    errors.extend(compute_errors)
    forbidden_compute = [
        row for row in compute_rows if row.get("forbidden_reason") is not None
    ]
    allowed_compute = [
        row for row in compute_rows if row.get("forbidden_reason") is None
    ]
    if forbidden_compute:
        errors.append("FORBIDDEN_HFNET_OR_ORB_OR_LEARNED_COMPUTE_APP_PRESENT")
    try:
        forbidden_processes = scan_forbidden_processes(proc_root)
    except base.ContractError as error:
        forbidden_processes = []
        errors.append(str(error))
    if forbidden_processes:
        errors.append("FORBIDDEN_HFNET_OR_ORB_OR_LEARNED_PROCESS_PRESENT")
    errors = list(dict.fromkeys(errors))
    return {
        "ready": not errors,
        "errors": errors,
        "resource_isolation": False,
        "todesk_corun": True,
        "gpu_platform": {
            "model": gpu_model,
            "required_model_token": EXPECTED_GPU_MODEL_TOKEN,
            "total_mib": total_mib,
            "required_total_mib": EXPECTED_GPU_TOTAL_MIB,
            "used_mib": used_mib,
            "free_mib": free_mib,
            "minimum_free_mib": minimum_free_mib,
            "floor_basis": "FORMAL_A09_SUCCESS_GATE_3072_MIB",
            "a09_success_lock_observed_free_mib": A09_SUCCESS_OBSERVED_FREE_MIB,
        },
        "allowed_compute_applications": allowed_compute,
        "forbidden_compute_applications": forbidden_compute,
        "forbidden_baseline_processes": forbidden_processes,
        "cpu_ros_vins_processes_permitted": True,
        "runtime_or_realtime_claim_permitted": False,
    }


def profile_atomic_json(path: Path, value: object, exclusive: bool = False) -> None:
    if path == formal.paths()["prepared"] and isinstance(value, dict):
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
        raise base.ContractError("CORUN_PREPARED_RESOURCE_CONTRACT_MISMATCH")


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


def check() -> dict[str, object]:
    formal.inherited.profile.configure_base()
    base.resource_gate = resource_gate
    value = base.check(require_unclaimed=True)
    value["schema_version"] = CHECK_SCHEMA
    value["resource_policy"] = dict(RESOURCE_POLICY)
    return value


def configure_overlay() -> None:
    """Install additive bindings only; do not validate, prepare, check, or run."""
    formal.RUNNER = RUNNER
    formal.ATTEMPT = ATTEMPT
    formal.AUTHORIZATION_TOKEN = AUTHORIZATION_TOKEN
    formal.SCHEMA = SCHEMA
    formal.PREPARED_SCHEMA = PREPARED_SCHEMA
    formal.CLAIM_SCHEMA = CLAIM_SCHEMA
    formal.CHECK_SCHEMA = CHECK_SCHEMA
    formal.ADJUDICATION_SCHEMA = ADJUDICATION_SCHEMA
    formal.SCIENTIFIC_ROLE = SCIENTIFIC_ROLE
    formal.validate_code_authority = validate_code_authority
    formal._expected_prepared_selection = _expected_selection
    formal._expected_comparison_boundary = _expected_comparison_boundary
    formal.profile_atomic_json = profile_atomic_json
    formal._validate_prepared_launch = _validate_prepared_launch
    formal._finalize_result_total = _finalize_result_total
    formal._minimal_terminal_failure = _minimal_terminal_failure
    formal.check = check
    base.MIN_GPU_FREE_MIB = MIN_GPU_FREE_MIB
    base.resource_gate = resource_gate


def main() -> int:
    configure_overlay()
    return formal.main()


if __name__ == "__main__":
    raise SystemExit(main())
