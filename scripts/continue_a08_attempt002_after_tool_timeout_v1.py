#!/usr/bin/env python3
"""Audit-only continuation for the already-running A08 KLT attempt002 export.

This program never starts an exporter.  It anchors the one exporter that was
already launched by the frozen attempt002 runner, waits for that exact process
session to finish, and acts only if the original Python supervisor was lost to
the enclosing tool wall-time limit.
"""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys
import time
from typing import Any


WORKSPACE = Path("/home/ma/AQUA-FE_WS")
EXPERIMENT = Path("/mnt/data/AQUA-FE_WS/experiments/a08_history_matched_controls_v1")
FRONTEND_ROOT = EXPERIMENT / "frontends_v1"
OVERLAY = EXPERIMENT / "recovered_july_core_overlay_v1"
RUN_DIR = OVERLAY / (
    "logs/aqualoc_archaeo_vins/"
    "external_klt_every2_"
    "a08_recoveredjuly_hist0000_4660_klt_export_attempt002_rosseed_v1"
)
RAW_BAG = EXPERIMENT / "raw/archaeo08_0000_4660.bag"
BASE_RUNNER = WORKSPACE / "scripts/run_a08_recovered_july_natural_history_frontends_v1.py"
WRAPPER = WORKSPACE / "scripts/run_a08_recovered_july_natural_history_frontends_attempt002_v1.py"
CLAIM = FRONTEND_ROOT / "klt_attempt002_process_start_claim_v1.json"
RECEIPT = FRONTEND_ROOT / "klt_attempt002_export_receipt_v1.json"
FAILURE = FRONTEND_ROOT / "klt_attempt002_export_failure_v1.json"
LOG = FRONTEND_ROOT / "klt_attempt002_supervisor_process.log"
ANCHOR = FRONTEND_ROOT / "klt_attempt002_same_exporter_continuation_anchor_v1.json"
OUTCOME = FRONTEND_ROOT / "klt_attempt002_same_exporter_continuation_outcome_v1.json"

EXPECTED_BASE = (48_196, "9ce1bcd18db77821a86c090381174316ac84a77dafe0842c0a1bb6d6eafea900")
EXPECTED_WRAPPER = (21_010, "cdf9cd24914d96be4fa779e0509bad2a7996136eb7f2b4b6ef2ab86f743fc89e")

PIDS = {
    "outer_tool_shell": 2478165,
    "original_python_supervisor": 2478166,
    "original_output_summarizer": 2478167,
    "export_session_leader": 2478925,
    "dataset_runner_shell": 2478926,
    "exporter": 2478973,
}


class ContinuationError(RuntimeError):
    pass


def require(value: bool, code: str) -> None:
    if not value:
        raise ContinuationError(code)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def identity(path: Path) -> dict[str, Any]:
    stat_result = path.lstat()
    require(path.is_file() and not path.is_symlink(), f"NOT_REGULAR:{path}")
    return {
        "path": str(path),
        "size_bytes": stat_result.st_size,
        "sha256": sha256(path),
    }


def require_identity(path: Path, expected: tuple[int, str]) -> dict[str, Any]:
    result = identity(path)
    require((result["size_bytes"], result["sha256"]) == expected, f"IDENTITY:{path}")
    return result


def write_exclusive(path: Path, value: Any) -> None:
    payload = (json.dumps(value, sort_keys=True, indent=2) + "\n").encode("utf-8")
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o444)
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(payload)
        stream.flush()
        os.fsync(stream.fileno())


def proc_stat(pid: int) -> dict[str, Any] | None:
    path = Path(f"/proc/{pid}/stat")
    try:
        raw = path.read_text(encoding="utf-8")
    except (FileNotFoundError, ProcessLookupError):
        return None
    close = raw.rfind(")")
    require(close > 0, f"PROC_STAT_PARSE:{pid}")
    fields = raw[close + 2 :].split()
    return {
        "state": fields[0],
        "ppid": int(fields[1]),
        "pgid": int(fields[2]),
        "sid": int(fields[3]),
        "starttime_ticks": int(fields[19]),
    }


def readlink_or_none(path: Path) -> str | None:
    try:
        return os.readlink(path)
    except (FileNotFoundError, PermissionError, ProcessLookupError):
        return None


def proc_identity(pid: int) -> dict[str, Any]:
    stat_value = proc_stat(pid)
    require(stat_value is not None, f"PROCESS_MISSING:{pid}")
    proc = Path(f"/proc/{pid}")
    cmdline = (proc / "cmdline").read_bytes().split(b"\0")
    command = [item.decode("utf-8", errors="surrogateescape") for item in cmdline if item]
    return {
        "pid": pid,
        **stat_value,
        "cmdline": command,
        "exe": readlink_or_none(proc / "exe"),
        "cwd": readlink_or_none(proc / "cwd"),
        "stdin": readlink_or_none(proc / "fd/0"),
        "stdout": readlink_or_none(proc / "fd/1"),
        "stderr": readlink_or_none(proc / "fd/2"),
    }


def same_process(anchor: dict[str, Any]) -> bool:
    current = proc_stat(int(anchor["pid"]))
    return current is not None and current["starttime_ticks"] == anchor["starttime_ticks"]


def live_session_members(sid: int) -> list[int]:
    members: list[int] = []
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        try:
            value = proc_stat(int(entry.name))
        except (OSError, ContinuationError, ValueError):
            continue
        if value is not None and value["sid"] == sid:
            members.append(int(entry.name))
    return sorted(members)


def terminal_outcome(status: str, anchor_identity: dict[str, Any], **extra: Any) -> None:
    if OUTCOME.exists() or OUTCOME.is_symlink():
        return
    value = {
        "schema_version": "aqua-fe-a08-attempt002-same-exporter-continuation-outcome-v1",
        "status": status,
        "recorded_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "anchor": anchor_identity,
        "exporter_restarted": False,
        "additional_exporter_popen_count": 0,
        "vins_or_accuracy_executed": False,
        **extra,
    }
    write_exclusive(OUTCOME, value)


def success_sentinels() -> list[str]:
    expected = [
        f"RUN_VINS=0, skipping VINS for {RUN_DIR}",
        f"run_dir={RUN_DIR}",
        f"raw_bag={RAW_BAG}",
        f"play_bag={RUN_DIR / 'features.bag'}",
    ]
    text = LOG.read_text(encoding="utf-8", errors="replace")
    offset = 0
    for line in expected:
        found = text.find(line, offset)
        require(found >= 0, f"SUCCESS_SENTINEL_MISSING:{line}")
        offset = found + len(line)
    return expected


def load_wrapper() -> Any:
    spec = importlib.util.spec_from_file_location("a08_attempt002_continuation_target", WRAPPER)
    require(spec is not None and spec.loader is not None, "WRAPPER_IMPORT_SPEC")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def recover(anchor_value: dict[str, Any], runner_lost_at: str) -> None:
    anchor_id = identity(ANCHOR)
    if RECEIPT.exists():
        terminal_outcome("NOOP_ORIGINAL_RECEIPT_PRESENT", anchor_id, receipt=identity(RECEIPT))
        return
    if FAILURE.exists():
        terminal_outcome("TERMINAL_ORIGINAL_FAILURE_PRESENT", anchor_id, failure=identity(FAILURE))
        return

    module = load_wrapper()
    base = module.BASE
    claim = json.loads(CLAIM.read_text(encoding="utf-8"))
    require(claim.get("stage") == "klt", "CLAIM_STAGE")
    require(claim.get("status") == "CLAIMED_BEFORE_SINGLE_POPEN_NO_AUTOMATIC_RETRY", "CLAIM_STATUS")
    command, environment = base.command_for("klt")
    require(claim.get("command") == command, "CLAIM_COMMAND")
    require(claim.get("environment") == environment, "CLAIM_ENVIRONMENT")

    sentinels = success_sentinels()
    raw = base.raw_contract()
    audit = base.audit_feature_bag(base.KLT_RUN, raw, "klt", None)
    post_tree = base.verify_execution_tree()
    require(post_tree == claim["execution_tree"], "TREE_CHANGED_DURING_RUN")
    post_environment = base.environment_fingerprint()
    require(post_environment == claim["environment_fingerprint"], "ENVIRONMENT_CHANGED_DURING_RUN")
    post_inputs = base.fixed_inputs()
    require(post_inputs == claim["inputs"], "INPUTS_CHANGED_DURING_RUN")

    require(not RECEIPT.exists() and not RECEIPT.is_symlink(), "RECEIPT_RACE")
    require(not FAILURE.exists() and not FAILURE.is_symlink(), "FAILURE_RACE")
    receipt = {
        "schema_version": "aqua-fe-a08-recovered-july-natural-history-frontend-receipt-v1",
        "status": "PASS_FRONTEND_EXPORT_ACCEPTED",
        "stage": "klt",
        "started_at_utc": claim["claimed_at_utc"],
        "started_time_source": "process_start_claim",
        "ended_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "wall_time_seconds_nonbenchmark": None,
        "terminal_process": {
            "return_code": None,
            "return_code_observed_by_original_supervisor": False,
            "successful_shell_completion_sentinel_observed": True,
            "success_inferred_under_set_euo_pipefail": True,
            "pid": PIDS["export_session_leader"],
            "pid_starttime_ticks": anchor_value["processes"]["export_session_leader"]["starttime_ticks"],
            "original_single_supervisor_popen": True,
            "additional_exporter_popen_count": 0,
            "method_native_planned_export_count": 1,
            "automatic_retry_count": 0,
        },
        "process_start_claim": base.identity(base.KLT_CLAIM),
        "supervisor_log": base.identity(base.KLT_LOG),
        "command": claim["command"],
        "environment": claim["environment"],
        "inputs_before": claim["inputs"],
        "inputs_after": post_inputs,
        "execution_tree_before": claim["execution_tree"],
        "execution_tree_after": post_tree,
        "environment_before": claim["environment_fingerprint"],
        "environment_after": post_environment,
        "raw_contract": raw,
        "artifact_audit": audit,
        "claim_boundary": {
            "export_only": True,
            "vins_or_slam_executed": False,
            "ape_or_rpe_computed": False,
            "runtime_claim_permitted": False,
            "ambient_desktop_and_unrelated_jobs_allowed_by_user_waiver": True,
            "complete_july_environment_reproduction": False,
            "method_label": "recovered seven-file July core plus newly frozen transitive closure",
            "zero_learned_action_is_accepted": True,
            "rearm_at_source_4000_or_4500": False,
        },
        "supervisor_continuation_recovery": {
            "schema_version": "aqua-fe-a08-attempt002-same-exporter-audit-continuation-v1",
            "classification": "SAME_EXPORTER_ARTIFACT_AUDIT_AFTER_TOOL_WALL_TIMEOUT",
            "original_runner_lost_at_utc": runner_lost_at,
            "anchor": anchor_id,
            "recovery_script": identity(Path(__file__).resolve()),
            "original_runner_return_not_observed": True,
            "exporter_restarted": False,
            "exporter_invocation_count": 1,
            "additional_exporter_popen_count": 0,
            "audit_only": True,
            "successful_shell_completion_sentinels": sentinels,
            "no_vins_or_accuracy": True,
        },
    }
    base.write_exclusive(base.KLT_RECEIPT, receipt)
    terminal_outcome(
        "PASS_SAME_EXPORTER_AUDIT_CONTINUATION",
        anchor_id,
        receipt=identity(RECEIPT),
        artifact_status=audit.get("status"),
    )


def main() -> int:
    FRONTEND_ROOT.mkdir(parents=True, exist_ok=True)
    require_identity(BASE_RUNNER, EXPECTED_BASE)
    require_identity(WRAPPER, EXPECTED_WRAPPER)
    require(CLAIM.is_file() and not CLAIM.is_symlink(), "CLAIM_MISSING")
    require(not RECEIPT.exists() and not RECEIPT.is_symlink(), "RECEIPT_ALREADY_EXISTS")
    require(not FAILURE.exists() and not FAILURE.is_symlink(), "FAILURE_ALREADY_EXISTS")
    require(not ANCHOR.exists() and not ANCHOR.is_symlink(), "ANCHOR_ALREADY_EXISTS")
    require(not OUTCOME.exists() and not OUTCOME.is_symlink(), "OUTCOME_ALREADY_EXISTS")

    processes = {name: proc_identity(pid) for name, pid in PIDS.items()}
    require(processes["original_python_supervisor"]["ppid"] == PIDS["outer_tool_shell"], "RUNNER_PARENT")
    require(processes["export_session_leader"]["ppid"] == PIDS["original_python_supervisor"], "SESSION_PARENT")
    require(processes["export_session_leader"]["pgid"] == PIDS["export_session_leader"], "SESSION_PGID")
    require(processes["export_session_leader"]["sid"] == PIDS["export_session_leader"], "SESSION_SID")
    require(processes["dataset_runner_shell"]["ppid"] == PIDS["export_session_leader"], "INNER_PARENT")
    require(processes["exporter"]["ppid"] == PIDS["dataset_runner_shell"], "EXPORTER_PARENT")
    require(processes["exporter"]["pgid"] == PIDS["export_session_leader"], "EXPORTER_PGID")
    require(processes["exporter"]["sid"] == PIDS["export_session_leader"], "EXPORTER_SID")
    exporter_command = processes["exporter"]["cmdline"]
    joined = "\0".join(exporter_command)
    for token in (
        "uw_frontend.ros.export_vins_features",
        str(RAW_BAG),
        str(RUN_DIR / "features.bag"),
        str(RUN_DIR / "frontend_metrics.csv"),
        "\0".join(("--method", "klt")),
        "\0".join(("--every-n", "2")),
        "\0".join(("--frame-offset", "1")),
        "--process-skipped-frames",
    ):
        require(token in joined, f"EXPORTER_COMMAND:{token}")
    for name in ("export_session_leader", "dataset_runner_shell", "exporter"):
        require(processes[name]["stdout"] == str(LOG), f"LOG_STDOUT:{name}")
        require(processes[name]["stderr"] == str(LOG), f"LOG_STDERR:{name}")

    anchor_value = {
        "schema_version": "aqua-fe-a08-attempt002-same-exporter-continuation-anchor-v1",
        "status": "ANCHORED_EXISTING_EXPORTER_NO_NEW_POPEN",
        "anchored_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "boot_id": Path("/proc/sys/kernel/random/boot_id").read_text(encoding="utf-8").strip(),
        "processes": processes,
        "process_start_claim": identity(CLAIM),
        "base_runner": identity(BASE_RUNNER),
        "attempt002_runner": identity(WRAPPER),
        "continuation_script": identity(Path(__file__).resolve()),
        "exporter_restarted": False,
        "additional_exporter_popen_count": 0,
        "vins_or_accuracy_executed": False,
    }
    write_exclusive(ANCHOR, anchor_value)
    anchor_id = identity(ANCHOR)

    deadline = time.monotonic() + 8 * 60 * 60
    runner_anchor = processes["original_python_supervisor"]
    runner_lost_at: str | None = None
    session_sid = PIDS["export_session_leader"]
    while time.monotonic() < deadline:
        if RECEIPT.exists():
            terminal_outcome("NOOP_ORIGINAL_RECEIPT_PRESENT", anchor_id, receipt=identity(RECEIPT))
            return 0
        if FAILURE.exists():
            terminal_outcome("TERMINAL_ORIGINAL_FAILURE_PRESENT", anchor_id, failure=identity(FAILURE))
            return 2
        if runner_lost_at is None and not same_process(runner_anchor):
            runner_lost_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        members = live_session_members(session_sid)
        if not members:
            if runner_lost_at is None:
                # Let an intact original supervisor finish its own audit and receipt.
                for _ in range(120):
                    if RECEIPT.exists():
                        terminal_outcome("NOOP_ORIGINAL_RECEIPT_PRESENT", anchor_id, receipt=identity(RECEIPT))
                        return 0
                    if FAILURE.exists():
                        terminal_outcome("TERMINAL_ORIGINAL_FAILURE_PRESENT", anchor_id, failure=identity(FAILURE))
                        return 2
                    if not same_process(runner_anchor):
                        runner_lost_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
                        break
                    time.sleep(5)
            if runner_lost_at is not None:
                time.sleep(30)
                require(not live_session_members(session_sid), "EXPORT_SESSION_REAPPEARED")
                recover(anchor_value, runner_lost_at)
                return 0
        time.sleep(5)
    raise ContinuationError("WATCH_TIMEOUT_WITHOUT_TERMINAL_STATE")


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except BaseException as error:
        if isinstance(error, SystemExit):
            raise
        details = {
            "schema_version": "aqua-fe-a08-attempt002-same-exporter-continuation-crash-v1",
            "status": "CONTINUATION_CRASH_NO_EXPORTER_RETRY",
            "failed_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "error_type": type(error).__name__,
            "error": str(error),
            "exporter_restarted": False,
            "additional_exporter_popen_count": 0,
            "vins_or_accuracy_executed": False,
        }
        crash_path = FRONTEND_ROOT / "klt_attempt002_same_exporter_continuation_crash_v1.json"
        if not crash_path.exists() and not crash_path.is_symlink():
            write_exclusive(crash_path, details)
        print(f"CONTINUATION_ERROR:{type(error).__name__}:{error}", file=sys.stderr)
        raise
