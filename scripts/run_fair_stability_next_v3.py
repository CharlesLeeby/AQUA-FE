#!/usr/bin/python3
"""Single ordinal dispatcher for the runtime-exclusive v3 experiment."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
from typing import Any, Mapping, Sequence
import uuid


ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from fair_stability_ordinal_common_v3 import (  # noqa: E402
    AUTOMATIC_RETRY_PIPELINE_FAILURES,
    EXPERIMENT_ID,
    MAX_ATTEMPTS_PER_CELL,
    MAX_REPLACEMENT_ATTEMPTS_PER_CELL,
    PIPELINE_EVIDENCE_NAMES,
    SCHEDULE_SHA256,
    TERMINAL_STATUSES,
    canonical_json,
    identity,
    load_attempt_matrix,
    load_schedule,
    next_state,
    attempt_root as common_attempt_root,
)


EXPERIMENT_ROOT = Path(
    "/mnt/data/AQUA-FE_WS/experiments/fair_stability_positive_roster_openloop_v3"
)
VINS_ROOT = EXPERIMENT_ROOT / "vins_dev_nativeq_schedfix_runtimeexcl_v3"
BACKEND_FREEZE = VINS_ROOT / "backend_freeze.json"
MATRIX_FREEZE = EXPERIMENT_ROOT / "attempt_matrix_freeze_v3.json"
HFNET_RUNNER = ROOT / "scripts/run_fair_stability_hfnet_openloop_v3.py"
VINS_RUNNER = ROOT / "scripts/run_fair_stability_vins_replay_v3.py"
CONTROLLER = Path(__file__).resolve()

class ControllerError(RuntimeError):
    pass


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def write_exclusive(path: Path, payload: bytes, mode: int = 0o444) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            descriptor = -1
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def verify_control_freeze() -> dict[str, Any]:
    if not BACKEND_FREEZE.is_file():
        raise ControllerError("VINS_BACKEND_AND_CONTROL_FREEZE_MISSING")
    freeze = json.loads(BACKEND_FREEZE.read_text(encoding="utf-8"))
    if freeze.get("status") != "FROZEN_BEFORE_NEW_VINS_REPLAY":
        raise ControllerError("BACKEND_FREEZE_STATUS_INVALID")
    frozen_controls = freeze.get("controls", {})
    for path in (CONTROLLER, HFNET_RUNNER, SCRIPT_DIR / "fair_stability_ordinal_common_v3.py"):
        expected = frozen_controls.get(path.name)
        observed = identity(path)
        if not isinstance(expected, Mapping) or (
            observed["size_bytes"], observed["sha256"]
        ) != (expected.get("size_bytes"), expected.get("sha256")):
            raise ControllerError(f"CONTROL_NOT_FROZEN_OR_DRIFTED:{path.name}")
    expected_vins_runner = freeze.get("runner")
    observed_vins_runner = identity(VINS_RUNNER)
    if not isinstance(expected_vins_runner, Mapping) or (
        observed_vins_runner["size_bytes"], observed_vins_runner["sha256"]
    ) != (
        expected_vins_runner.get("size_bytes"), expected_vins_runner.get("sha256")
    ):
        raise ControllerError("VINS_RUNNER_NOT_FROZEN_OR_DRIFTED")
    backend = freeze.get("backend", {})
    for key in ("vins_node", "libvins_lib", "libcamera_models", "hfnet_binary", "hfnet_official_library"):
        expected = backend.get(key)
        if not isinstance(expected, Mapping):
            raise ControllerError(f"BACKEND_IDENTITY_MISSING:{key}")
        observed = identity(Path(str(expected.get("path", ""))))
        if (observed["size_bytes"], observed["sha256"]) != (
            expected.get("size_bytes"), expected.get("sha256")
        ):
            raise ControllerError(f"BACKEND_IDENTITY_DRIFT:{key}")
    for key in ("vins_ldd_closure", "hfnet_ldd_closure"):
        closure = backend.get(key)
        if not isinstance(closure, Mapping) or not isinstance(closure.get("resolved_files"), list):
            raise ControllerError(f"DYNAMIC_CLOSURE_MISSING:{key}")
        for expected in closure["resolved_files"]:
            if not isinstance(expected, Mapping):
                raise ControllerError(f"DYNAMIC_CLOSURE_ROW_INVALID:{key}")
            observed = identity(Path(str(expected.get("path", ""))))
            if (observed["size_bytes"], observed["sha256"]) != (
                expected.get("size_bytes"), expected.get("sha256")
            ):
                raise ControllerError(f"DYNAMIC_CLOSURE_DRIFT:{key}:{expected.get('path')}")
    dynamic_check = subprocess.run(
        ["/usr/bin/python3", str(VINS_RUNNER), "verify-freeze"],
        cwd=str(ROOT), check=False, capture_output=True, text=True,
    )
    if dynamic_check.returncode != 0:
        raise ControllerError(
            "FULL_BACKEND_FREEZE_REVERIFICATION_FAILED:"
            + dynamic_check.stderr[-2000:]
        )
    try:
        dynamic_value = json.loads(dynamic_check.stdout)
    except json.JSONDecodeError as error:
        raise ControllerError("FULL_BACKEND_FREEZE_REVERIFICATION_NOT_JSON") from error
    if dynamic_value.get("status") != "VERIFIED":
        raise ControllerError("FULL_BACKEND_FREEZE_REVERIFICATION_STATUS_INVALID")
    return freeze


def runner_argv(state: Mapping[str, Any], command: str) -> list[str]:
    cell = state["cell"]
    attempt_index = int(state["attempt_index"])
    common = [
        "--case", str(cell["case_id"]), "--repeat", str(cell["repeat"]),
        "--attempt-index", str(attempt_index),
    ]
    arm = str(cell["arm"])
    if arm.startswith("hfnet_openloop_"):
        return [
            "/usr/bin/python3", str(HFNET_RUNNER), command,
            *common, "--budget", arm.rsplit("_", 1)[1],
        ]
    return [
        "/usr/bin/python3", str(VINS_RUNNER), command,
        *common, "--arm", arm,
    ]


def run_command(argv: Sequence[str], environment: Mapping[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        list(argv), cwd=str(ROOT), env=dict(environment) if environment else None,
        check=False, capture_output=True, text=True,
    )


def parse_runner_json(command: subprocess.CompletedProcess[str]) -> dict[str, Any]:
    try:
        value = json.loads(command.stdout)
    except json.JSONDecodeError as error:
        raise ControllerError(
            f"RUNNER_STDOUT_NOT_JSON:rc={command.returncode}:stderr={command.stderr[-1000:]}"
        ) from error
    if not isinstance(value, dict):
        raise ControllerError("RUNNER_JSON_NOT_OBJECT")
    return value


def prepare_state(state: Mapping[str, Any]) -> dict[str, Any]:
    command = run_command(runner_argv(state, "prepare"))
    if command.returncode != 0:
        raise ControllerError(f"PREPARE_FAILED:{command.stderr[-2000:]}")
    parse_runner_json(command)
    updated = next_state(EXPERIMENT_ROOT)
    if updated.get("state") != "READY":
        raise ControllerError(f"PREPARE_DID_NOT_PRODUCE_READY:{updated.get('state')}")
    return updated


def adopt_terminal(state: Mapping[str, Any]) -> dict[str, Any]:
    verify_control_freeze()
    if state.get("state") != "TERMINAL_UNADOPTED":
        raise ControllerError("ADOPT_REQUIRES_TERMINAL_UNADOPTED")
    cell = state["cell"]
    root = Path(state["attempt_root"])
    result = state["result"]
    if result.get("status") not in TERMINAL_STATUSES:
        raise ControllerError("ADOPT_STATUS_NOT_TERMINAL")
    payload = {
        "schema_version": "aqua-fe-fair-stability-ordinal-terminal-v3",
        "experiment_id": EXPERIMENT_ID,
        "adopted_at_utc": now_utc(),
        "planned_ordinal": int(cell["ordinal"]),
        "case_id": str(cell["case_id"]),
        "arm": str(cell["arm"]),
        "repeat": int(cell["repeat"]),
        "accepted_attempt_index": int(state["attempt_index"]),
        "terminal_status": str(result["status"]),
        "clean_success": bool(result.get("clean_success")),
        "run_result": identity(root / "run_result.json"),
        "start_claim": identity(root / "start_claim.json"),
        "attempt_manifest": identity(root / "attempt_manifest.json"),
        "ordinal_dispatch_claim": identity(root / "ordinal_dispatch_claim.json"),
        "invalid_attempt_chain": state.get("invalid_chain", []),
        "schedule_sha256": SCHEDULE_SHA256,
        "controller": identity(CONTROLLER),
        "control_freeze": identity(BACKEND_FREEZE),
        "attempt_matrix_freeze": identity(MATRIX_FREEZE),
    }
    target = Path(state["terminal_receipt"])
    write_exclusive(target, canonical_json(payload))
    return payload


def automatic_retry_codes(state: Mapping[str, Any]) -> list[str]:
    """Fail closed unless this is a novel, explicitly external transient fault."""
    result = state["result"]
    raw_codes = result.get("pipeline_failure_codes")
    if (
        not isinstance(raw_codes, list)
        or not raw_codes
        or any(not isinstance(value, str) or not value for value in raw_codes)
        or len(set(raw_codes)) != len(raw_codes)
    ):
        raise ControllerError("PIPELINE_INVALID_WITHOUT_PIPELINE_FAILURE_CODE")
    codes = list(raw_codes)
    persistent_or_control = sorted(
        code for code in codes if code not in AUTOMATIC_RETRY_PIPELINE_FAILURES
    )
    if persistent_or_control:
        raise ControllerError(
            "PERSISTENT_OR_CONTROL_PIPELINE_FAILURE_HALT_MANUAL_ABANDONMENT_REQUIRED:"
            f"{persistent_or_control}"
        )
    attempt_index = int(state.get("attempt_index", 0))
    if attempt_index >= MAX_ATTEMPTS_PER_CELL:
        raise ControllerError(
            "REPLACEMENT_LIMIT_EXHAUSTED_HALT_MANUAL_ABANDONMENT_REQUIRED:"
            f"{MAX_REPLACEMENT_ATTEMPTS_PER_CELL}"
        )
    prior_codes = {
        str(code)
        for entry in state.get("invalid_chain", [])
        if isinstance(entry, Mapping)
        for code in entry.get("pipeline_failure_codes", [])
    }
    repeated = sorted(prior_codes.intersection(codes))
    if repeated:
        raise ControllerError(
            "REPEATED_PIPELINE_FAILURE_CODE_HALT_MANUAL_ABANDONMENT_REQUIRED:"
            f"{repeated}"
        )
    return codes


def adjudicate_pipeline_invalid(state: Mapping[str, Any]) -> dict[str, Any]:
    verify_control_freeze()
    if state.get("state") != "PIPELINE_INVALID_UNADJUDICATED":
        raise ControllerError("ADJUDICATION_STATE_INVALID")
    result = state["result"]
    codes = automatic_retry_codes(state)
    root = Path(state["attempt_root"])
    evidence: dict[str, object] = {}
    for name in PIPELINE_EVIDENCE_NAMES:
        path = root / name
        if path.is_file() and not path.is_symlink():
            evidence[name] = identity(path)
    payload = {
        "schema_version": "aqua-fe-fair-stability-pipeline-invalid-adjudication-v3",
        "experiment_id": EXPERIMENT_ID,
        "adjudicated_at_utc": now_utc(),
        "accepted_as_external_pipeline_fault": True,
        "automatic_retry_policy": "EXPLICIT_EXTERNAL_TRANSIENT_ONLY_V3",
        "maximum_replacement_attempts_per_planned_cell": (
            MAX_REPLACEMENT_ATTEMPTS_PER_CELL
        ),
        "case_id": state["cell"]["case_id"],
        "arm": state["cell"]["arm"],
        "repeat": state["cell"]["repeat"],
        "planned_ordinal": state["cell"]["ordinal"],
        "attempt_index": state["attempt_index"],
        "pipeline_failure_codes": codes,
        "algorithm_failure_codes_observed_but_excluded_with_invalid_attempt": result.get(
            "algorithm_failure_codes", []
        ),
        "run_result": identity(root / "run_result.json"),
        "evidence": evidence,
        "schedule_sha256": SCHEDULE_SHA256,
        "controller": identity(CONTROLLER),
        "control_freeze": identity(BACKEND_FREEZE),
        "attempt_matrix_freeze": identity(MATRIX_FREEZE),
    }
    write_exclusive(root / "pipeline_invalid_receipt.json", canonical_json(payload))
    return payload


def dispatch_claim(state: Mapping[str, Any]) -> tuple[dict[str, Any], str]:
    root = Path(state["attempt_root"])
    path = root / "ordinal_dispatch_claim.json"
    if path.is_file():
        claim = json.loads(path.read_text(encoding="utf-8"))
        token = str(claim.get("dispatch_token", ""))
        if not token:
            raise ControllerError("EXISTING_DISPATCH_TOKEN_MISSING")
        if claim.get("controller", {}).get("sha256") != identity(CONTROLLER)["sha256"]:
            raise ControllerError("EXISTING_DISPATCH_CONTROLLER_DRIFT")
        return claim, token
    token = secrets.token_hex(32)
    cell = state["cell"]
    claim = {
        "schema_version": "aqua-fe-fair-stability-ordinal-dispatch-v3",
        "experiment_id": EXPERIMENT_ID,
        "created_at_utc": now_utc(),
        "planned_ordinal": int(cell["ordinal"]),
        "case_id": str(cell["case_id"]), "arm": str(cell["arm"]),
        "repeat": int(cell["repeat"]), "attempt_index": int(state["attempt_index"]),
        "attempt_manifest": identity(root / "attempt_manifest.json"),
        "schedule_sha256": SCHEDULE_SHA256,
        "controller": identity(CONTROLLER),
        "control_freeze": identity(BACKEND_FREEZE),
        "attempt_matrix_freeze": identity(MATRIX_FREEZE),
        "dispatch_token": token,
        "token_sha256": hashlib.sha256(token.encode("ascii")).hexdigest(),
    }
    write_exclusive(path, canonical_json(claim), 0o400)
    return claim, token


def dispatch(state: Mapping[str, Any]) -> dict[str, Any]:
    check = run_command(runner_argv(state, "check"))
    check_value = parse_runner_json(check)
    if check_value.get("ready") is not True:
        return {
            "outcome": "RESOURCE_BLOCKED_NO_START",
            "next": state,
            "resource_gate": check_value.get("resource_gate"),
            "runner_returncode": check.returncode,
        }
    claim, token = dispatch_claim(state)
    environment = dict(os.environ)
    environment["FAIR_STABILITY_DISPATCH_TOKEN"] = token
    command = run_command(runner_argv(state, "run"), environment)
    root = Path(state["attempt_root"])
    existing = sorted(root.glob("controller_dispatch_execution_*.json"))
    index = len(existing) + 1
    stdout_path = root / f"controller_dispatch_{index:03d}.stdout.log"
    stderr_path = root / f"controller_dispatch_{index:03d}.stderr.log"
    write_exclusive(stdout_path, command.stdout.encode("utf-8"))
    write_exclusive(stderr_path, command.stderr.encode("utf-8"))
    execution = {
        "schema_version": "aqua-fe-fair-stability-controller-dispatch-execution-v3",
        "experiment_id": EXPERIMENT_ID,
        "recorded_at_utc": now_utc(), "dispatch_index": index,
        "argv": runner_argv(state, "run"), "returncode": command.returncode,
        "stdout": identity(stdout_path), "stderr": identity(stderr_path),
        "dispatch_claim": identity(root / "ordinal_dispatch_claim.json"),
        "controller": identity(CONTROLLER),
        "attempt_matrix_freeze": identity(MATRIX_FREEZE),
    }
    write_exclusive(
        root / f"controller_dispatch_execution_{index:03d}.json",
        canonical_json(execution),
    )
    verify_control_freeze()
    if not (root / "run_result.json").is_file():
        if not (root / "start_claim.json").is_file():
            return {
                "outcome": "PRESTART_DISPATCH_BLOCKED_NO_ESTIMATOR_START",
                "dispatch_execution": execution,
                "runner_stderr_tail": command.stderr[-2000:],
            }
        return {
            "outcome": "ADJUDICATION_REQUIRED_STARTED_OR_DISPATCH_FAILED_WITHOUT_RESULT",
            "dispatch_execution": execution,
            "runner_stderr_tail": command.stderr[-2000:],
        }
    updated = next_state(EXPERIMENT_ROOT)
    if updated.get("state") == "TERMINAL_UNADOPTED":
        receipt = adopt_terminal(updated)
        return {
            "outcome": "TERMINAL_ADOPTED", "terminal_receipt": receipt,
            "runner_returncode": command.returncode,
        }
    if updated.get("state") == "PIPELINE_INVALID_UNADJUDICATED":
        return {
            "outcome": "PIPELINE_INVALID_REQUIRES_ADJUDICATION",
            "state": updated, "runner_returncode": command.returncode,
        }
    raise ControllerError(f"UNEXPECTED_STATE_AFTER_DISPATCH:{updated.get('state')}")


def freeze_attempt_matrix() -> dict[str, Any]:
    """Freeze the 120 pristine attempt manifests after both prepare-all passes."""
    verify_control_freeze()
    if MATRIX_FREEZE.exists() or MATRIX_FREEZE.is_symlink():
        raise ControllerError(f"ATTEMPT_MATRIX_FREEZE_EXISTS:{MATRIX_FREEZE}")
    schedule = load_schedule(EXPERIMENT_ROOT)
    rows: list[dict[str, Any]] = []
    forbidden = {
        "ordinal_dispatch_claim.json", "start_claim.json", "run_result.json",
        "pipeline_invalid_receipt.json", "runtime_resource_monitor.json",
    }
    for cell in schedule:
        root = common_attempt_root(EXPERIMENT_ROOT, cell, 1)
        manifest = root / "attempt_manifest.json"
        if root.is_symlink() or not root.is_dir() or not manifest.is_file():
            raise ControllerError(f"ATTEMPT_NOT_PREPARED:{cell['ordinal']}:{root}")
        present = sorted(name for name in forbidden if (root / name).exists())
        if present:
            raise ControllerError(
                f"ATTEMPT_ALREADY_STARTED:{cell['ordinal']}:{present}"
            )
        value = json.loads(manifest.read_text(encoding="utf-8"))
        expected_schema = (
            "aqua-fe-fair-stability-hfnet-attempt-v3"
            if str(cell["arm"]).startswith("hfnet_openloop_")
            else "aqua-fe-fair-stability-vins-attempt-v3"
        )
        expected = [
            expected_schema, EXPERIMENT_ID, str(cell["case_id"]), str(cell["arm"]),
            int(cell["repeat"]), 1,
        ]
        observed_arm = value.get("arm")
        if observed_arm is None and type(value.get("budget")) is int:
            observed_arm = f"hfnet_openloop_{value['budget']}"
        observed = [
            value.get("schema_version"), value.get("experiment_id"),
            value.get("case_id"), observed_arm,
            value.get("repeat"), value.get("attempt_index"),
        ]
        if observed != expected:
            raise ControllerError(
                f"ATTEMPT_MANIFEST_COORDINATE_MISMATCH:{cell['ordinal']}:{observed}"
            )
        rows.append(
            {
                "ordinal": int(cell["ordinal"]),
                "case_id": str(cell["case_id"]),
                "arm": str(cell["arm"]),
                "repeat": int(cell["repeat"]),
                "attempt_index": 1,
                "attempt_root": str(root),
                "maximum_replacement_attempts": MAX_REPLACEMENT_ATTEMPTS_PER_CELL,
                "maximum_total_attempts": MAX_ATTEMPTS_PER_CELL,
                "attempt_manifest": identity(manifest),
            }
        )
    receipts = EXPERIMENT_ROOT / "ordinal_receipts"
    if receipts.exists() and any(receipts.iterdir()):
        raise ControllerError("ORDINAL_RECEIPTS_EXIST_BEFORE_MATRIX_FREEZE")
    payload = {
        "schema_version": "aqua-fe-fair-stability-attempt-matrix-freeze-v3",
        "experiment_id": EXPERIMENT_ID,
        "status": "FROZEN_BEFORE_ANY_V3_ESTIMATOR_START",
        "frozen_at_utc": now_utc(),
        "experiment_manifest": identity(EXPERIMENT_ROOT / "experiment_manifest.json"),
        "planned_schedule": identity(EXPERIMENT_ROOT / "planned_schedule.json"),
        "backend_freeze": identity(BACKEND_FREEZE),
        "replacement_policy": {
            "automatic_retry_pipeline_failure_codes": sorted(
                AUTOMATIC_RETRY_PIPELINE_FAILURES
            ),
            "maximum_replacement_attempts_per_planned_cell": (
                MAX_REPLACEMENT_ATTEMPTS_PER_CELL
            ),
            "maximum_total_attempts_per_planned_cell": MAX_ATTEMPTS_PER_CELL,
            "same_pipeline_failure_code_may_repeat": False,
        },
        "attempts": rows,
        "claims": {
            "attempt_count": len(rows),
            "v1_results_imported": False,
            "v2_results_imported": False,
            "dispatch_claim_count": 0,
            "start_claim_count": 0,
            "run_result_count": 0,
            "terminal_receipt_count": 0,
        },
    }
    write_exclusive(MATRIX_FREEZE, canonical_json(payload))
    load_attempt_matrix(EXPERIMENT_ROOT)
    return payload


def run_next() -> dict[str, Any]:
    verify_control_freeze()
    lock_path = EXPERIMENT_ROOT / ".ordinal_controller.lock"
    lock_path.touch(exist_ok=True)
    with lock_path.open("r+b") as lock_stream:
        fcntl.flock(lock_stream.fileno(), fcntl.LOCK_EX)
        state = next_state(EXPERIMENT_ROOT)
        while state.get("state") == "TERMINAL_UNADOPTED":
            adopt_terminal(state)
            state = next_state(EXPERIMENT_ROOT)
        if state.get("state") == "COMPLETE":
            return {"outcome": "EXPERIMENT_COMPLETE", "state": state}
        if state.get("state") == "STARTED_WITHOUT_RESULT":
            return {"outcome": "ADJUDICATION_REQUIRED_STARTED_WITHOUT_RESULT", "state": state}
        if state.get("state") == "PIPELINE_INVALID_UNADJUDICATED":
            receipt = adjudicate_pipeline_invalid(state)
            prepared = prepare_state(next_state(EXPERIMENT_ROOT))
            return {
                "outcome": "PIPELINE_INVALID_ADJUDICATED_REPLENISHMENT_PREPARED",
                "invalid_receipt": receipt, "next": prepared,
            }
        if state.get("state") == "NEEDS_PREPARATION":
            state = prepare_state(state)
        if state.get("state") != "READY":
            raise ControllerError(f"NEXT_STATE_NOT_DISPATCHABLE:{state.get('state')}")
        return dispatch(state)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("freeze-matrix", "status", "run-next"))
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        if args.command == "freeze-matrix":
            result = freeze_attempt_matrix()
        elif args.command == "status":
            result = next_state(EXPERIMENT_ROOT)
        else:
            result = run_next()
        print(json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False))
        if result.get("outcome") in {
            "RESOURCE_BLOCKED_NO_START",
            "PRESTART_DISPATCH_BLOCKED_NO_ESTIMATOR_START",
        }:
            return 75
        if str(result.get("outcome", "")).startswith("ADJUDICATION_REQUIRED"):
            return 4
        return 0
    except BaseException as error:
        print(f"{type(error).__name__}:{error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
