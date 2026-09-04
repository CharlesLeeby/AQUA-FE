#!/usr/bin/env python3
"""Audit the P07 backend execution envelope without evaluating APE/RPE values."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any, Mapping

try:
    from scripts import check_p07_backend_replay_input_v1 as input_checker
    from scripts import p07_backend_replay_common_v1 as common
    from scripts import run_p07_backend_replay_adapter_v1 as adapter
except ModuleNotFoundError:  # Direct ``python3 scripts/...`` execution.
    import check_p07_backend_replay_input_v1 as input_checker  # type: ignore
    import p07_backend_replay_common_v1 as common  # type: ignore
    import run_p07_backend_replay_adapter_v1 as adapter  # type: ignore


SCHEMA_VERSION = "isj-p07-backend-replay-audit-v1"


class AuditViolation(common.BackendReplayViolation):
    """Backend replay evidence is incomplete, inconsistent, or unsafe."""


def _json_object(path: Path, *, label: str) -> dict[str, Any]:
    if not path.is_file():
        raise AuditViolation(f"missing {label}: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise AuditViolation(f"invalid {label} JSON: {path}") from error
    if not isinstance(value, dict):
        raise AuditViolation(f"{label} is not a JSON object")
    return value


def _key_value_manifest(path: Path, *, label: str) -> dict[str, str]:
    if not path.is_file():
        raise AuditViolation(f"missing {label}: {path}")
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line or "=" not in line:
            raise AuditViolation(f"malformed {label} line")
        key, value = line.split("=", 1)
        if not key or key in values:
            raise AuditViolation(f"duplicate/empty {label} key")
        values[key] = value
    return values


def _validate_replay_manifest(
    row: Mapping[str, str], *, root: Path, run_dir: Path, require_success: bool
) -> dict[str, str]:
    replay_manifest = _key_value_manifest(
        run_dir / "backend_replay_manifest.txt",
        label="backend replay-only manifest",
    )
    if (
        replay_manifest.get("schema_version")
        != "isj-p07-backend-replay-manifest-v1"
        or replay_manifest.get("family") != row["dataset_family"]
        or replay_manifest.get("mode") != row["runner_mode"]
        or replay_manifest.get("run_dir") != os.fspath(run_dir)
        or replay_manifest.get("vins_config")
        != os.fspath(adapter.vins_config_path(row, root=root))
        or replay_manifest.get("numeric_evaluation") != "DISABLED_SEPARATE_G0"
    ):
        raise AuditViolation("backend replay-only manifest identity/policy mismatch")
    if require_success and (
        replay_manifest.get("rosbag_exit_code") != "0"
        or replay_manifest.get("vins_alive_after_replay") != "true"
    ):
        raise AuditViolation("backend replay-only manifest is not an exact PASS")
    return replay_manifest


def _identity(row: Mapping[str, str], payload: Mapping[str, Any], label: str) -> None:
    expected = {
        "queue_index": int(row["queue_index"]),
        "run_id": row["run_id"],
        "arm": row["arm"],
    }
    differences = {
        key: {"expected": value, "observed": payload.get(key)}
        for key, value in expected.items()
        if payload.get(key) != value
    }
    if differences:
        raise AuditViolation(f"{label} identity mismatch: {differences}")


def _file_record(root: Path, path: Path) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise AuditViolation(f"audit evidence is not a plain file: {path}")
    return {
        "path": common.display_path(root, path),
        "sha256": common.sha256(path),
        "size_bytes": path.stat().st_size,
    }


def _output_structure(run_dir: Path) -> dict[str, Any]:
    paths = {
        "vins_log": run_dir / "vins.log",
        "vins_environment": run_dir / "vins_env_manifest.txt",
        "trajectory": run_dir / "vins_output/vio.csv",
        "backend_replay_manifest": run_dir / "backend_replay_manifest.txt",
        "preparation_manifest": run_dir / "replay_manifest.txt",
        "ape_report": run_dir / "ape.txt",
        "rpe_report": run_dir / "rpe.txt",
        "ape_rpe_report": run_dir / "ape_rpe.json",
    }
    return {
        key: {
            "path": os.fspath(path),
            "exists": path.is_file(),
            "size_bytes": path.stat().st_size if path.is_file() else None,
        }
        for key, path in paths.items()
    }


def _b0_identity_record(attempt_dir: Path, *, root: Path) -> dict[str, Any]:
    decision_dir = attempt_dir / "b0_contract_decisions"
    decisions = sorted(decision_dir.glob("*.json")) if decision_dir.is_dir() else []
    if len(decisions) != 1:
        raise AuditViolation(
            f"B0 attempt requires exactly one identity decision, got {len(decisions)}"
        )
    path = decisions[0]
    payload = _json_object(path, label="B0 origin identity decision")
    if (
        payload.get("schema_version")
        != "aqua-fe-b0-vins-origin-identity-decision-v1"
        or payload.get("contract_pass") is not True
        or payload.get("action") != "ALLOW_B0_NATIVE"
        or payload.get("result_label") != "B0_NATIVE_VINS_ORIGIN_V1"
        or payload.get("counts_as_b0") is not True
        or payload.get("contract_hash") != input_checker.NATIVEQ_CONTRACT_HASH
        or payload.get("vins_workspace") != os.fspath(common.VINS_ORIGIN)
        or payload.get("backend_root")
        != os.fspath(common.VINS_ORIGIN / "src/VINS-Fusion-master")
        or payload.get("binary")
        != os.fspath(common.VINS_ORIGIN / "devel/lib/vins/vins_node")
        or payload.get("reasons") != []
        or payload.get("outcome_boundary")
        != "EXECUTION_IDENTITY_ONLY_NO_FRONTEND_OR_TRAJECTORY_OUTCOME"
    ):
        raise AuditViolation("B0 origin identity decision is not an exact PASS")
    return {
        "path": common.display_path(root, path),
        "sha256": common.sha256(path),
        "size_bytes": path.stat().st_size,
        "contract_hash": payload.get("contract_hash"),
    }


def _validate_consumer_decision(
    row: Mapping[str, str], payload: Mapping[str, Any], *, root: Path
) -> None:
    feature_path = payload.get("feature_bag")
    attestation_path = payload.get("bag_attestation")
    if not isinstance(feature_path, str) or not feature_path.startswith(
        "/proc/self/fd/"
    ):
        raise AuditViolation("consumer decision did not use the sealed fd path")
    try:
        expected_attestation = common.workspace_path(
            root, row["attestation_path"], label="expected attestation"
        )
        observed_attestation = common.workspace_path(
            root, str(attestation_path or ""), label="decision attestation"
        )
    except common.BackendReplayViolation as error:
        raise AuditViolation("consumer decision attestation path is invalid") from error
    if not os.path.samefile(expected_attestation, observed_attestation):
        raise AuditViolation("consumer decision names a different attestation")

    backend_root = os.fspath(common.VINS_ORIGIN / "src/VINS-Fusion-master")
    binary = os.fspath(common.VINS_ORIGIN / "devel/lib/vins/vins_node")
    if row["arm"] in common.NATIVEQ_ARMS:
        if (
            payload.get("schema_version")
            != "aqua-fe-nativeq-backend-guard-decision-v1"
            or payload.get("contract_pass") is not True
            or payload.get("action") != "ALLOW_LEARNED"
            or payload.get("counts_as_proposed_result") is not True
            or payload.get("contract_hash") != input_checker.NATIVEQ_CONTRACT_HASH
            or payload.get("backend_root") != backend_root
            or payload.get("binary") != binary
            or payload.get("reasons") != []
        ):
            raise AuditViolation("native-q consumer decision is not an exact PASS")
    elif row["arm"] == common.M_ARM:
        expected_frame_offset = 0 if row["dataset_family"] == "afrl" else 1
        if (
            payload.get("schema_version")
            != "aqua-fe-p05-xfeat-backend-guard-decision-v1"
            or payload.get("contract_pass") is not True
            or payload.get("action") != "ALLOW_M_XFEAT"
            or payload.get("counts_as_modern_baseline") is not True
            or payload.get("contract_hash") != input_checker.M_CONTRACT_HASH
            or payload.get("workspace_root") != os.fspath(root)
            or payload.get("vins_workspace") != os.fspath(common.VINS_ORIGIN)
            or payload.get("backend_root") != backend_root
            or payload.get("binary") != binary
            or payload.get("family") != row["dataset_family"]
            or payload.get("every_n") != int(row["runner_every_n"])
            or payload.get("frame_offset") != expected_frame_offset
            or payload.get("run_vins") is not True
            or payload.get("feature_bag_sha256") != row["feature_bag_sha256"]
            or payload.get("reasons") != []
        ):
            raise AuditViolation("M consumer decision is not an exact PASS")
    else:
        raise AuditViolation("unexpected arm for reused-bag consumer decision")


def build_audit(
    row: Mapping[str, str],
    *,
    root: Path,
    attempt_dir: Path,
    command_log: Path,
) -> dict[str, Any]:
    common.validate_queue_row(row)
    expected_attempt = common.output_path(
        root, row["expected_attempt_dir"], label="expected attempt dir"
    )
    if common.lexical_absolute(attempt_dir) != expected_attempt:
        raise AuditViolation("auditor attempt directory differs from frozen queue")
    if not command_log.is_file():
        raise AuditViolation("backend command log is missing")

    input_report = _json_object(attempt_dir / "input_check.json", label="input check")
    authority = _json_object(
        attempt_dir / "job_authority_v1.json", label="job authority"
    )
    command = _json_object(attempt_dir / "adapter_command.json", label="adapter command")
    result = _json_object(attempt_dir / "adapter_result.json", label="adapter result")
    if result.get("status") in {"FAIL_INPUT_IMMUTABILITY", "FAIL_GOVERNANCE"}:
        raise AuditViolation(
            f"adapter failed its governance envelope: {result.get('status')}"
        )
    data_preflight_path = attempt_dir / "data_identity_preflight.json"
    data_before_path = attempt_dir / "data_identity_adapter_before.json"
    data_pre_replay_path = attempt_dir / "data_identity_pre_replay.json"
    data_after_path = attempt_dir / "data_identity_adapter_after.json"
    data_preflight = _json_object(data_preflight_path, label="data-identity preflight")
    data_before = _json_object(data_before_path, label="data-identity adapter entry")
    data_pre_replay = _json_object(
        data_pre_replay_path, label="data-identity pre-replay"
    )
    data_after = _json_object(data_after_path, label="data-identity post-replay")
    _identity(row, input_report, "input check")
    _identity(row, command, "adapter command")
    _identity(row, result, "adapter result")
    if input_report.get("status") != "PASS":
        raise AuditViolation("backend input check did not PASS")
    if (
        authority.get("schema_version") != adapter.JOB_AUTHORITY_SCHEMA_VERSION
        or authority.get("queue_index") != int(row["queue_index"])
        or authority.get("run_id") != row["run_id"]
        or authority.get("row_sha256") != adapter._row_sha256(row)
        or authority.get("outcome_boundary")
        != "JOB_AUTHORITY_ONLY_NO_TRAJECTORY_OR_EVALUATION_OUTCOME"
    ):
        raise AuditViolation("job authority identity/boundary mismatch")
    execution_lock_path = common.workspace_path(
        root,
        str(authority.get("execution_lock_path", "")),
        label="authority execution lock",
    )
    if common.sha256(execution_lock_path) != authority.get("execution_lock_sha256"):
        raise AuditViolation("job authority execution-lock artifact drift")
    execution_lock = _json_object(execution_lock_path, label="backend execution lock")
    g0_authority = execution_lock.get(
        common.g0_governance.EXECUTION_LOCK_BINDING_KEY
    )
    if not isinstance(g0_authority, dict) or not isinstance(
        g0_authority.get("evaluation_lock"), dict
    ):
        raise AuditViolation("backend execution lock lacks G0 authority")
    try:
        g0_authority_hash = (
            common.g0_governance.validate_execution_authority_binding(
                g0_authority, root=root
            )
        )
    except common.g0_governance.G0GovernanceError as error:
        raise AuditViolation(f"backend G0 authority validation failed: {error}") from error
    if (
        authority.get("g0_execution_authority_hash") != g0_authority_hash
        or authority.get("g0_evaluation_lock_hash")
        != g0_authority["evaluation_lock"].get("evaluation_lock_hash")
    ):
        raise AuditViolation("job authority G0 lock binding mismatch")
    identity_hash = authority.get("data_identity_snapshot_hash")
    if (
        not isinstance(identity_hash, str)
        or len(identity_hash) != 64
        or authority.get("data_identity_preflight_sha256")
        != common.sha256(data_preflight_path)
        or any(
            report.get("schema_version")
            != "isj-p07-backend-data-identity-runtime-check-v1"
            or report.get("status") != "PASS"
            or report.get("data_identity_snapshot_hash") != identity_hash
            or report.get("trajectory_values_read") is not False
            or report.get("content_values_interpreted") is not False
            for report in (
                data_preflight,
                data_before,
                data_pre_replay,
                data_after,
            )
        )
        or [
            data_preflight.get("phase"),
            data_before.get("phase"),
            data_pre_replay.get("phase"),
            data_after.get("phase"),
        ]
        != ["JOB_PREFLIGHT", "ADAPTER_ENTRY", "PRE_REPLAY_LAUNCH", "POST_REPLAY"]
        or result.get("data_identity_before") != data_before
        or result.get("data_identity_pre_replay") != data_pre_replay
        or result.get("data_identity_after") != data_after
        or result.get("data_identity_unchanged") is not True
    ):
        raise AuditViolation("runtime data-identity evidence/binding mismatch")
    intent_path = common.workspace_path(
        root, str(authority.get("attempt_intent_path", "")), label="attempt intent"
    )
    intent = _json_object(intent_path, label="attempt intent")
    if (
        common.sha256(intent_path) != authority.get("attempt_intent_sha256")
        or intent.get("attempt_intent_hash") != authority.get("attempt_intent_hash")
        or intent.get("attempt_intent_hash")
        != common.canonical_json_hash(intent, "attempt_intent_hash")
        or intent.get("queue_index") != int(row["queue_index"])
        or intent.get("run_id") != row["run_id"]
        or intent.get("row_sha256") != adapter._row_sha256(row)
        or intent.get("replay_started") is not False
        or intent.get("algorithmic_slot_consumed") is not False
        or intent.get("g0_execution_authority_hash")
        != authority.get("g0_execution_authority_hash")
        or intent.get("g0_evaluation_lock_hash")
        != authority.get("g0_evaluation_lock_hash")
    ):
        raise AuditViolation("durable attempt-intent binding mismatch")
    state_journal = common.output_path(
        root, str(authority.get("attempt_state_journal", "")), label="attempt state journal"
    )
    state_events = common.read_hash_chain_jsonl(state_journal)
    if not state_events or state_events[-1].get("state") != "ADAPTER_RETURNED":
        raise AuditViolation("attempt-state journal lacks adapter terminal handoff")
    try:
        state_analysis = common.analyze_attempt_state_events(
            state_events,
            queue_index=int(row["queue_index"]),
            run_id=row["run_id"],
        )
    except common.BackendReplayViolation as error:
        raise AuditViolation(f"attempt-state semantic drift: {error}") from error
    if (
        not state_analysis["boundary_may_have_been_crossed"]
        or state_analysis["unpaired_launch_pending"]
        or state_analysis["active_processes"]
    ):
        raise AuditViolation("attempt-state journal lacks one closed replay boundary")
    if command.get("schema_version") != adapter.COMMAND_SCHEMA_VERSION:
        raise AuditViolation("unexpected adapter command schema")
    if result.get("schema_version") != adapter.SCHEMA_VERSION:
        raise AuditViolation("unexpected adapter result schema")
    if command.get("vins_workspace") != os.fspath(common.VINS_ORIGIN):
        raise AuditViolation("adapter did not bind VINS-Fusion-origin")
    if (
        command.get("run_vins") is not True
        or command.get("preparation_run_vins") is not False
        or command.get("replay_only_runner") is not True
        or command.get("evaluation_invoked") is not False
        or command.get("force_export") is not False
        or command.get("export_features") is not False
        or command.get("feature_bag_path_disclosed_to_runner") is not False
        or result.get("export_wrapper_invoked") is not False
        or result.get("trajectory_metrics_read_by_adapter") is not False
        or result.get("evaluation_invoked") is not False
        or result.get("ape_rpe_artifacts_created") is not False
        or result.get("direct_eval_runner_used_for_replay") is not False
    ):
        raise AuditViolation("adapter execution boundary differs from backend-only policy")
    expected_transport = (
        "sealed_memfd_byte_exact_copy"
        if row["arm"] in common.FEATURE_BAG_ARMS
        else "none"
    )
    if command.get("feature_bag_transport") != expected_transport:
        raise AuditViolation("adapter feature-bag transport is not the frozen safe mode")
    prepare_argv = command.get("preparation_argv")
    config_argv = command.get("config_argv")
    replay_argv = command.get("replay_argv")
    if any(
        not isinstance(argv, list)
        or any(not isinstance(item, str) for item in argv)
        for argv in (prepare_argv, config_argv, replay_argv)
    ):
        raise AuditViolation("invalid adapter phase argv evidence")
    if prepare_argv != adapter.build_prepare_argv(row, root=root):
        raise AuditViolation("adapter preparation argv differs from frozen family runner")
    if config_argv != adapter.build_config_argv(row, root=root):
        raise AuditViolation("adapter config argv differs from frozen helper")
    if len(replay_argv) != 8:
        raise AuditViolation("adapter replay-only argv has unexpected shape")
    play_bag = replay_argv[4]
    frozen_b0_play_bag = None
    if row["arm"] == common.B0_ARM:
        b0_pre_replay_for_argv = _json_object(
            attempt_dir / "b0_play_input_pre_replay.json",
            label="B0 pre-replay play input",
        )
        identity_for_argv = b0_pre_replay_for_argv.get("path_identity")
        if not isinstance(identity_for_argv, dict):
            raise AuditViolation("B0 pre-replay report lacks path identity")
        frozen_b0_play_bag = common.workspace_path(
            root,
            str(identity_for_argv.get("path", "")),
            label="B0 frozen play input",
        )
    expected_replay_argv = adapter.build_backend_argv(
        row,
        root=root,
        play_bag=play_bag,
        frozen_b0_play_bag=frozen_b0_play_bag,
    )
    if replay_argv != expected_replay_argv or command.get("argv") != replay_argv:
        raise AuditViolation("adapter ROS replay argv is not the replay-only runner")
    for name, argv in (
        ("preparation", prepare_argv),
        ("config", config_argv),
        ("replay", replay_argv),
    ):
        expected_hash = common.sha256_bytes(
            json.dumps(argv, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
        )
        if command.get(f"{name}_argv_sha256") != expected_hash:
            raise AuditViolation(f"adapter {name} argv evidence hash mismatch")
    if command.get("argv_sha256") != command.get("replay_argv_sha256"):
        raise AuditViolation("adapter replay argv compatibility hash mismatch")

    status = result.get("status")
    if status in {"FAIL_INPUT_IMMUTABILITY", "FAIL_GOVERNANCE"}:
        raise AuditViolation(f"adapter failed its governance envelope: {status}")
    if status not in {"PASS_EXECUTION_ENVELOPE", "TERMINAL_PROCESS_FAILURE"}:
        raise AuditViolation(f"unrecognized adapter terminal status: {status}")
    if result.get("input_feature_bag_unchanged") is not True:
        raise AuditViolation("adapter did not prove input immutability")
    if row["arm"] in common.FEATURE_BAG_ARMS:
        if result.get("consumer_feature_bag_sealed_readonly") is not True:
            raise AuditViolation("consumer feature bag was not kernel write-sealed")
        before = result.get("input_feature_bag_before")
        after = result.get("input_feature_bag_after")
        if (
            not isinstance(before, dict)
            or before != after
            or before.get("sha256") != row["feature_bag_sha256"]
        ):
            raise AuditViolation("feature-bag pre/post snapshot mismatch")
        attestation_before = result.get("input_attestation_before")
        input_audit_before = result.get("input_audit_before")
        if (
            not isinstance(attestation_before, dict)
            or attestation_before != result.get("input_attestation_after")
            or attestation_before.get("sha256") != row["attestation_sha256"]
            or not isinstance(input_audit_before, dict)
            or input_audit_before != result.get("input_audit_after")
            or input_audit_before.get("sha256") != row["input_audit_sha256"]
        ):
            raise AuditViolation("attestation/input-audit pre/post snapshot mismatch")
        decision_path = result.get("backend_consumer_contract_decision")
        if not isinstance(decision_path, str):
            raise AuditViolation("feature replay lacks a consumer contract decision")
        decision = _json_object(
            common.workspace_path(root, decision_path, label="consumer decision"),
            label="consumer decision",
        )
        _validate_consumer_decision(row, decision, root=root)
    elif (
        result.get("input_feature_bag_before") is not None
        or result.get("consumer_feature_bag_sealed_readonly") is not None
    ):
        raise AuditViolation("B0 unexpectedly opened a reused feature bag")
    if row["arm"] == common.B0_ARM:
        origin_before = result.get("origin_play_bag_before")
        origin_after = result.get("origin_play_bag_after")
        b0_preflight_path = attempt_dir / "b0_play_input_preflight.json"
        b0_before_path = attempt_dir / "b0_play_input_adapter_before.json"
        b0_pre_replay_path = attempt_dir / "b0_play_input_pre_replay.json"
        b0_after_path = attempt_dir / "b0_play_input_after.json"
        b0_preflight = _json_object(b0_preflight_path, label="B0 play-input preflight")
        b0_before = _json_object(b0_before_path, label="B0 play-input adapter entry")
        b0_pre_replay = _json_object(
            b0_pre_replay_path, label="B0 play-input pre-replay"
        )
        b0_after = _json_object(b0_after_path, label="B0 play-input post-replay")
        if (
            not isinstance(origin_before, dict)
            or not isinstance(origin_after, dict)
            or origin_before != b0_pre_replay
            or origin_after != b0_after
            or b0_preflight.get("content_sha256_reverified") is not False
            or b0_before.get("content_sha256_reverified") is not False
            or b0_pre_replay.get("content_sha256_reverified") is not True
            or b0_after.get("content_sha256_reverified") is not True
            or any(
                report.get("status") != "PASS"
                or report.get("queue_index") != int(row["queue_index"])
                or report.get("run_id") != row["run_id"]
                or report.get("source_provenance_hash")
                != row["source_provenance_hash"]
                or report.get("trajectory_values_read") is not False
                or report.get("content_values_interpreted") is not False
                for report in (b0_preflight, b0_before, b0_pre_replay, b0_after)
            )
            or b0_pre_replay.get("play_input_id") != b0_after.get("play_input_id")
            or b0_pre_replay.get("path_identity") != b0_after.get("path_identity")
            or b0_pre_replay.get("derivation_hash")
            != b0_after.get("derivation_hash")
            or authority.get("b0_play_input_preflight_sha256")
            != common.sha256(b0_preflight_path)
        ):
            raise AuditViolation("B0 frozen play-input evidence changed during replay")

    config_before = result.get("vins_config_before")
    if not isinstance(config_before, dict) or config_before != result.get(
        "vins_config_after"
    ):
        raise AuditViolation("prepared VINS config changed during replay")
    if (
        result.get("preparation_completed") is not True
        or result.get("config_completed") is not True
        or result.get("replay_started") is not True
        or result.get("preparation_runner_invoked_with_run_vins_zero") is not True
        or result.get("replay_only_runner_invoked") is not True
    ):
        raise AuditViolation("adapter did not complete the governed replay-only phases")

    b0_identity = (
        _b0_identity_record(attempt_dir, root=root)
        if row["arm"] == common.B0_ARM
        else None
    )

    run_dir = common.output_path(root, row["expected_run_dir"], label="expected run dir")
    structure = _output_structure(run_dir) if run_dir.is_dir() else {}
    forbidden_evaluation_outputs: list[str] = []
    if run_dir.is_dir():
        forbidden_names = {
            "ape.txt",
            "rpe.txt",
            "ape_rpe.json",
            "ape_report.txt",
            "rpe_report.txt",
        }
        forbidden_evaluation_outputs = [
            common.display_path(root, path)
            for path in run_dir.rglob("*")
            if path.is_file() and path.name.lower() in forbidden_names
        ]
    if forbidden_evaluation_outputs:
        raise AuditViolation(
            "replay phase created forbidden APE/RPE artifacts: "
            f"{forbidden_evaluation_outputs}"
        )
    returncode = result.get("returncode")
    timed_out = result.get("timed_out")
    failure_code: str | None = None
    numeric_evaluation_candidate = False
    if status == "TERMINAL_PROCESS_FAILURE":
        if timed_out is True and result.get("failure_stage") == "REPLAY_ONLY":
            failure_code = "TIMEOUT"
        elif (
            isinstance(returncode, int)
            and returncode != 0
            and result.get("failure_stage") == "REPLAY_ONLY"
            and run_dir.is_dir()
            and (run_dir / "backend_replay_manifest.txt").is_file()
        ):
            # A structured terminal manifest proves ROS/VINS/rosbag replay
            # reached its terminal boundary; frozen taxonomy therefore owns
            # the nonzero outcome.  A pre-manifest launch failure is left to
            # the job's infrastructure replacement path.
            _validate_replay_manifest(
                row, root=root, run_dir=run_dir, require_success=False
            )
            failure_code = "NONZERO_EXIT"
        else:
            raise AuditViolation(
                "terminal process failure lacks replay-terminal evidence"
            )
    else:
        if returncode != 0 or timed_out is not False or not run_dir.is_dir():
            raise AuditViolation("successful adapter result lacks a successful run directory")
        required_metadata = (
            "vins_log",
            "vins_environment",
            "backend_replay_manifest",
        )
        if any(not structure[name]["exists"] for name in required_metadata):
            raise AuditViolation("successful replay lacks mandatory backend metadata/log evidence")
        _validate_replay_manifest(
            row, root=root, run_dir=run_dir, require_success=True
        )
        trajectory = structure["trajectory"]
        if not trajectory["exists"] or int(trajectory["size_bytes"] or 0) == 0:
            failure_code = "EMPTY_TRAJECTORY"
        else:
            numeric_evaluation_candidate = True

    forbidden_export_outputs: list[str] = []
    if run_dir.is_dir() and row["arm"] in common.FEATURE_BAG_ARMS:
        for path in run_dir.rglob("*"):
            if path.is_file() and path.name in {
                "features.bag",
                "frontend_metrics.csv",
                "arbitration_summary.txt",
            }:
                forbidden_export_outputs.append(common.display_path(root, path))
    if forbidden_export_outputs:
        raise AuditViolation(
            f"backend-only run created frontend export artifacts: {forbidden_export_outputs}"
        )

    return {
        "schema_version": SCHEMA_VERSION,
        "status": "PASS",
        "queue_index": int(row["queue_index"]),
        "run_id": row["run_id"],
        "window_id": row["window_id"],
        "arm": row["arm"],
        "replay_index": int(row["replay_index"]),
        "terminal": True,
        "terminal_process_status": status,
        "failure_code": failure_code,
        "replay_hard_failure": failure_code
        in {"TIMEOUT", "NONZERO_EXIT", "EMPTY_TRAJECTORY"},
        "numeric_evaluation_candidate": numeric_evaluation_candidate,
        "g0_evaluation_pending": numeric_evaluation_candidate,
        "run_dir": common.display_path(root, run_dir),
        "command_log": {
            "path": common.display_path(root, command_log),
            "sha256": common.sha256(command_log),
            "size_bytes": command_log.stat().st_size,
        },
        "output_structure": structure,
        "b0_identity_decision": b0_identity,
        "attempt_intent": _file_record(root, intent_path),
        "attempt_state_journal": _file_record(root, state_journal),
        "data_identity_runtime_evidence": {
            "preflight": _file_record(root, data_preflight_path),
            "adapter_entry": _file_record(root, data_before_path),
            "pre_replay": _file_record(root, data_pre_replay_path),
            "post_replay": _file_record(root, data_after_path),
            "snapshot_hash": identity_hash,
        },
        "checks": {
            "job_only_governed_adapter": True,
            "job_authority_manifest_valid": True,
            "legacy_dataset_runner_preparation_only_run_vins_zero": True,
            "independent_replay_only_runner": True,
            "evaluation_during_replay_forbidden": True,
            "ape_rpe_artifacts_absent": True,
            "no_export_wrapper": True,
            "consumer_feature_bag_kernel_write_sealed": (
                row["arm"] in common.FEATURE_BAG_ARMS
            ),
            "feature_bag_pre_post_sha_exact": True,
            "attestation_and_input_audit_pre_post_sha_exact": True,
            "data_identity_manifest_link_target_revalidated": True,
            "durable_attempt_intent_and_state_chain_valid": True,
            "b0_frozen_play_input_pre_post_sha_exact": (
                row["arm"] == common.B0_ARM
            ),
            "expected_run_no_clobber": True,
            "trajectory_values_read": False,
            "ape_rpe_values_read": False,
        },
        "outcome_boundary": "BACKEND_EXECUTION_ENVELOPE_ONLY_G0_EVALUATION_SEPARATE",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--queue-index", type=int, required=True)
    parser.add_argument("--root", type=Path, default=common.ROOT)
    parser.add_argument("--queue", type=Path, default=common.DEFAULT_QUEUE)
    parser.add_argument("--allocation", type=Path, default=common.DEFAULT_ALLOCATION)
    parser.add_argument("--attempt-dir", type=Path)
    parser.add_argument("--command-log", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    row, _allocation = input_checker.load_bound_row(
        args.queue_index,
        root=args.root,
        queue_path=args.queue,
        allocation_path=args.allocation,
    )
    attempt = args.attempt_dir or common.output_path(
        args.root, row["expected_attempt_dir"], label="expected attempt dir"
    )
    command_log = args.command_log or attempt / "command.log"
    output = args.output or attempt / "audit_v1.json"
    payload = build_audit(
        row,
        root=args.root,
        attempt_dir=attempt,
        command_log=command_log,
    )
    common.write_json_exclusive(output, payload)
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
