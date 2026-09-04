#!/usr/bin/python3
"""Durable systemd-user supervision for one fair-stability v5 ordinal.

Formal estimator starts are submit-only transient services.  ``submit`` returns
after systemd has accepted the service; ``poll`` is read-only; ``adopt`` writes
one audit receipt only after the unit's frozen ``ExecStopPost`` collector has
published terminal evidence.  The service uses ``KillMode=control-group`` so a
detached estimator session cannot survive loss of the controller process.

This module never uses nohup, tmux, a scope unit, ``--wait``, or ``--collect``.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import subprocess
import sys
import tempfile
import time
from typing import Any, Mapping, Sequence


SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from fair_stability_ordinal_common_v5 import (  # noqa: E402
    EXPERIMENT_ID,
    FIXED_SERVICE_ENVIRONMENT,
    ROS_PYTHONPATH,
    canonical_json,
    identity,
    next_state,
    strict_json_equal,
    SYSTEMD_CHAIN_FILES,
    validate_systemd_chain,
)


ROOT = Path(__file__).resolve().parents[1]
SUPERVISOR = Path(__file__).resolve()
CONTROLLER = ROOT / "scripts/run_fair_stability_next_v5.py"
EXPERIMENT_ROOT = Path(
    "/mnt/data/AQUA-FE_WS/experiments/fair_stability_positive_roster_openloop_v5"
)
VINS_ROOT = EXPERIMENT_ROOT / "vins_dev_nativeq_schedfix_runtimeexcl_v5"
BACKEND_FREEZE = VINS_ROOT / "backend_freeze.json"
MATRIX_FREEZE = EXPERIMENT_ROOT / "attempt_matrix_freeze_v5.json"
SUPERVISION_ROOT = EXPERIMENT_ROOT / "systemd_supervision"
SYSTEMD_RUN = Path("/usr/bin/systemd-run")
SYSTEMCTL = Path("/usr/bin/systemctl")
LOGINCTL = Path("/usr/bin/loginctl")
PYTHON = Path("/usr/bin/python3")

RUNNER_TIMEOUT_SECONDS = 1800
RUNTIME_MAX_SECONDS = 2400
TIMEOUT_STOP_SECONDS = 120
SUBMISSION_RECEIPT_WAIT_SECONDS = 30
UNIT_PREFIX = "aqua-fe-fair-stability-v5"

SUBMISSION_SCHEMA = "aqua-fe-fair-stability-systemd-submission-v5"
SUBMIT_RECEIPT_SCHEMA = "aqua-fe-fair-stability-systemd-submit-receipt-v5"
START_RECEIPT_SCHEMA = "aqua-fe-fair-stability-systemd-start-receipt-v5"
EXECUTION_SCHEMA = "aqua-fe-fair-stability-systemd-execution-v5"
TERMINAL_SCHEMA = "aqua-fe-fair-stability-systemd-terminal-v5"
ADOPTION_CLAIM_SCHEMA = "aqua-fe-fair-stability-systemd-adoption-claim-v5"
ADOPTION_SCHEMA = "aqua-fe-fair-stability-systemd-adoption-v5"

SHOW_PROPERTIES = (
    "Id",
    "LoadState",
    "ActiveState",
    "SubState",
    "Result",
    "Type",
    "KillMode",
    "RuntimeMaxUSec",
    "TimeoutStopUSec",
    "SendSIGKILL",
    "KillSignal",
    "MainPID",
    "ControlGroup",
    "InvocationID",
    "ExecMainCode",
    "ExecMainStatus",
    "NRestarts",
    "Transient",
    "RemainAfterExit",
    "Restart",
    "UMask",
)


class SystemdSupervisorError(RuntimeError):
    pass


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def write_exclusive(path: Path, payload: bytes, mode: int = 0o440) -> None:
    """Publish complete bytes with hard-link no-replace semantics on FUSE."""
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.publish-", dir=str(path.parent)
    )
    temporary = Path(temporary_name)
    published = False
    try:
        os.fchmod(descriptor, mode)
        with os.fdopen(descriptor, "wb") as stream:
            descriptor = -1
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(temporary, path, follow_symlinks=False)
        except FileExistsError as error:
            raise SystemdSupervisorError(f"RECEIPT_ALREADY_EXISTS:{path}") from error
        published = True
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass
        if published:
            _fsync_directory(path.parent)


def create_empty_exclusive(path: Path, mode: int = 0o600) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode)
    os.close(descriptor)


def load_json(path: Path, schema: str | None = None) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise SystemdSupervisorError(f"JSON_REGULAR_FILE_REQUIRED:{path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise SystemdSupervisorError(
            f"JSON_INVALID:{path}:{type(error).__name__}"
        ) from error
    if not isinstance(value, dict):
        raise SystemdSupervisorError(f"JSON_OBJECT_REQUIRED:{path}")
    if schema is not None and value.get("schema_version") != schema:
        raise SystemdSupervisorError(f"JSON_SCHEMA_INVALID:{path}")
    if value.get("experiment_id") != EXPERIMENT_ID:
        raise SystemdSupervisorError(f"JSON_EXPERIMENT_ID_INVALID:{path}")
    return value


def require_descendant(path: Path, root: Path) -> None:
    anchor = Path(os.path.abspath(root))
    target = Path(os.path.abspath(path))
    try:
        relative = target.relative_to(anchor)
    except ValueError as error:
        raise SystemdSupervisorError(f"PATH_OUTSIDE_ROOT:{target}") from error
    candidate = anchor
    if candidate.is_symlink():
        raise SystemdSupervisorError(f"SYMLINK_COMPONENT:{candidate}")
    for part in relative.parts:
        candidate /= part
        if candidate.is_symlink():
            raise SystemdSupervisorError(f"SYMLINK_COMPONENT:{candidate}")


def parse_key_values(text: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in text.splitlines():
        if not line or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key] = value
    return values


def run_checked(
    argv: Sequence[str], *, timeout: float = 30.0, environment: Mapping[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        list(argv),
        cwd=str(ROOT),
        env=dict(environment) if environment is not None else None,
        check=False,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def verify_fixed_service_environment(
    environment: Mapping[str, str],
) -> dict[str, str]:
    observed = {
        key: environment.get(key) for key in FIXED_SERVICE_ENVIRONMENT
    }
    if not strict_json_equal(observed, FIXED_SERVICE_ENVIRONMENT):
        raise SystemdSupervisorError("SERVICE_ENTRY_FIXED_ENVIRONMENT_DRIFT")
    return {key: str(value) for key, value in observed.items()}


def host_preflight() -> dict[str, object]:
    manager = run_checked([str(SYSTEMCTL), "--user", "is-system-running"])
    login = run_checked(
        [
            str(LOGINCTL),
            "show-user",
            str(os.getuid()),
            "--property=State",
            "--property=Sessions",
            "--property=Linger",
            "--no-page",
        ]
    )
    systemd_version = run_checked([str(SYSTEMD_RUN), "--version"])
    rosbag_probe = run_checked(
        [
            str(PYTHON),
            "-c",
            (
                "import pathlib, rosbag, site; "
                "assert site.ENABLE_USER_SITE is False; "
                "print(pathlib.Path(rosbag.__file__).resolve())"
            ),
        ],
        environment=FIXED_SERVICE_ENVIRONMENT,
    )
    login_values = parse_key_values(login.stdout)
    sessions = [value for value in login_values.get("Sessions", "").split() if value]
    session_snapshots: list[dict[str, object]] = []
    for session in sessions:
        observed = run_checked(
            [
                str(LOGINCTL),
                "show-session",
                session,
                "--property=Id",
                "--property=Active",
                "--property=State",
                "--property=Type",
                "--property=Class",
                "--property=Remote",
                "--no-page",
            ]
        )
        session_snapshots.append(
            {
                "session": session,
                "returncode": observed.returncode,
                "properties": parse_key_values(observed.stdout),
                "stderr": observed.stderr,
            }
        )
    active_sessions = [
        snapshot
        for snapshot in session_snapshots
        if snapshot["returncode"] == 0
        and snapshot["properties"].get("Active") == "yes"
        and snapshot["properties"].get("State") == "active"
    ]
    errors: list[str] = []
    if manager.returncode != 0 or manager.stdout.strip() != "running":
        errors.append("SYSTEMD_USER_MANAGER_NOT_RUNNING")
    if login.returncode != 0:
        errors.append("LOGINCTL_USER_QUERY_FAILED")
    if login_values.get("State") != "active" or not active_sessions:
        errors.append("NO_ACTIVE_LOGIN_SESSION_FOR_NONLINGERING_USER_MANAGER")
    if systemd_version.returncode != 0:
        errors.append("SYSTEMD_VERSION_QUERY_FAILED")
    expected_rosbag_module = f"{ROS_PYTHONPATH}/rosbag/__init__.py"
    if (
        rosbag_probe.returncode != 0
        or rosbag_probe.stdout.strip() != expected_rosbag_module
    ):
        errors.append("FIXED_ENV_ROSBAG_IMPORT_FAILED")
    return {
        "schema_version": "aqua-fe-fair-stability-systemd-host-preflight-v5",
        "experiment_id": EXPERIMENT_ID,
        "checked_at_utc": now_utc(),
        "ready": not errors,
        "errors": errors,
        "user_manager": {
            "returncode": manager.returncode,
            "state": manager.stdout.strip(),
            "stderr": manager.stderr,
        },
        "login": {
            "query_returncode": login.returncode,
            "state": login_values.get("State"),
            "sessions": sessions,
            "session_snapshots": session_snapshots,
            "active_session_count": len(active_sessions),
            "linger": login_values.get("Linger"),
            "limitation": (
                "LAST_LOGIN_SESSION_EXIT_MAY_STOP_USER_MANAGER_AND_INVALIDATE_V5"
                if login_values.get("Linger") != "yes"
                else None
            ),
        },
        "systemd_version_first_line": (
            systemd_version.stdout.splitlines()[0] if systemd_version.stdout else None
        ),
        "fixed_environment_rosbag_probe": {
            "argv": [
                str(PYTHON),
                "-c",
                (
                    "import pathlib, rosbag, site; "
                    "assert site.ENABLE_USER_SITE is False; "
                    "print(pathlib.Path(rosbag.__file__).resolve())"
                ),
            ],
            "environment": dict(FIXED_SERVICE_ENVIRONMENT),
            "expected_module": expected_rosbag_module,
            "returncode": rosbag_probe.returncode,
            "stdout": rosbag_probe.stdout,
            "stderr": rosbag_probe.stderr,
            "valid": (
                rosbag_probe.returncode == 0
                and rosbag_probe.stdout.strip() == expected_rosbag_module
            ),
        },
        "contract": {
            "runner_timeout_seconds": RUNNER_TIMEOUT_SECONDS,
            "runtime_max_seconds": RUNTIME_MAX_SECONDS,
            "timeout_stop_seconds": TIMEOUT_STOP_SECONDS,
            "runtime_max_strictly_after_runner_timeout": (
                RUNTIME_MAX_SECONDS > RUNNER_TIMEOUT_SECONDS
            ),
            "linger_required": False,
            "active_session_required_when_linger_is_not_yes": True,
            "last_session_exit_is_fail_stop_not_retryable": True,
        },
    }


def query_unit(unit: str) -> dict[str, object]:
    argv = [str(SYSTEMCTL), "--user", "show", unit, "--no-page"]
    for name in SHOW_PROPERTIES:
        argv.append(f"--property={name}")
    command = run_checked(argv)
    return {
        "queried_at_utc": now_utc(),
        "argv": argv,
        "returncode": command.returncode,
        "properties": parse_key_values(command.stdout),
        "stderr": command.stderr,
    }


def parse_systemd_usec(value: str) -> int | None:
    match = re.fullmatch(r"([0-9]+(?:\.[0-9]+)?)(us|ms|s|min|h)", value)
    if not match:
        return None
    factors = {"us": 1, "ms": 1_000, "s": 1_000_000, "min": 60_000_000, "h": 3_600_000_000}
    return int(float(match.group(1)) * factors[match.group(2)])


def verify_unit_contract(
    unit: str,
    query: Mapping[str, object],
    *,
    require_live_main: bool,
    expected_invocation_id: str | None = None,
) -> dict[str, object]:
    properties = query.get("properties")
    if query.get("returncode") != 0 or not isinstance(properties, Mapping):
        raise SystemdSupervisorError("SYSTEMD_UNIT_QUERY_FAILED")
    expected = {
        "Id": unit,
        "LoadState": "loaded",
        "Type": "exec",
        "KillMode": "control-group",
        "SendSIGKILL": "yes",
        "NRestarts": "0",
        "Transient": "yes",
        "RemainAfterExit": "no",
        "Restart": "no",
        "UMask": "0077",
    }
    for key, value in expected.items():
        if properties.get(key) != value:
            raise SystemdSupervisorError(
                f"SYSTEMD_UNIT_PROPERTY_MISMATCH:{key}:{properties.get(key)}:{value}"
            )
    if parse_systemd_usec(str(properties.get("RuntimeMaxUSec", ""))) != RUNTIME_MAX_SECONDS * 1_000_000:
        raise SystemdSupervisorError("SYSTEMD_RUNTIME_MAX_MISMATCH")
    if parse_systemd_usec(str(properties.get("TimeoutStopUSec", ""))) != TIMEOUT_STOP_SECONDS * 1_000_000:
        raise SystemdSupervisorError("SYSTEMD_TIMEOUT_STOP_MISMATCH")
    if str(properties.get("KillSignal", "")) not in {"15", "SIGTERM"}:
        raise SystemdSupervisorError("SYSTEMD_KILL_SIGNAL_MISMATCH")
    invocation_id = str(properties.get("InvocationID", ""))
    if not re.fullmatch(r"[0-9a-f]{32}", invocation_id):
        raise SystemdSupervisorError("SYSTEMD_INVOCATION_ID_INVALID")
    if expected_invocation_id is not None and invocation_id != expected_invocation_id:
        raise SystemdSupervisorError("SYSTEMD_INVOCATION_ID_MISMATCH")
    main_pid = int(str(properties.get("MainPID", "0")) or "0")
    if require_live_main:
        if properties.get("ActiveState") not in {"activating", "active"} or main_pid <= 1:
            raise SystemdSupervisorError("SYSTEMD_MAIN_NOT_ACTIVE")
    return {
        "unit": unit,
        "invocation_id": invocation_id,
        "main_pid": main_pid,
        "control_group": str(properties.get("ControlGroup", "")),
        "properties": dict(properties),
    }


def process_identity(pid: int) -> dict[str, object]:
    proc = Path("/proc") / str(pid)
    raw = (proc / "stat").read_text(encoding="ascii")
    close = raw.rfind(")")
    fields = raw[close + 2 :].split()
    if close < 0 or len(fields) < 20:
        raise SystemdSupervisorError("PROC_STAT_INVALID")
    cmdline = (proc / "cmdline").read_bytes()
    return {
        "pid": pid,
        "ppid": int(fields[1]),
        "pgid": int(fields[2]),
        "session": int(fields[3]),
        "start_ticks": int(fields[19]),
        "executable": os.path.realpath(os.readlink(proc / "exe")),
        "cmdline_sha256": sha256_bytes(cmdline),
        "cgroup_paths": [
            line.split(":", 2)[2]
            for line in (proc / "cgroup").read_text(encoding="ascii").splitlines()
            if line.count(":") >= 2
        ],
    }


def verify_process_in_unit(identity_record: Mapping[str, object], control_group: str) -> None:
    paths = identity_record.get("cgroup_paths")
    if not control_group or not isinstance(paths, list) or control_group not in paths:
        raise SystemdSupervisorError("SERVICE_PROCESS_NOT_IN_RECORDED_CONTROL_GROUP")


def freeze_context() -> dict[str, object]:
    freeze = load_json(BACKEND_FREEZE)
    if freeze.get("status") != "FROZEN_BEFORE_NEW_VINS_REPLAY":
        raise SystemdSupervisorError("BACKEND_FREEZE_STATUS_INVALID")
    controls = freeze.get("controls")
    if not isinstance(controls, Mapping):
        raise SystemdSupervisorError("BACKEND_FREEZE_CONTROLS_INVALID")
    for path in (SUPERVISOR, CONTROLLER):
        if not strict_json_equal(controls.get(path.name), identity(path)):
            raise SystemdSupervisorError(f"FROZEN_CONTROL_DRIFT:{path.name}")
    return {
        "backend_freeze": identity(BACKEND_FREEZE),
        "attempt_matrix_freeze": identity(MATRIX_FREEZE),
        "controller": identity(CONTROLLER),
        "supervisor": identity(SUPERVISOR),
    }


def submission_directories() -> list[Path]:
    if not SUPERVISION_ROOT.exists():
        return []
    require_descendant(SUPERVISION_ROOT, EXPERIMENT_ROOT)
    directories: list[Path] = []
    for ordinal_root in SUPERVISION_ROOT.iterdir():
        if ordinal_root.is_symlink() or not ordinal_root.is_dir() or not re.fullmatch(
            r"ordinal_[0-9]{3}", ordinal_root.name
        ):
            raise SystemdSupervisorError(
                f"SYSTEMD_ORDINAL_DIRECTORY_INVALID:{ordinal_root}"
            )
        for path in ordinal_root.iterdir():
            if path.is_symlink() or not path.is_dir() or not re.fullmatch(
                r"submission_[0-9]{3}", path.name
            ):
                raise SystemdSupervisorError(
                    f"SYSTEMD_SUBMISSION_DIRECTORY_INVALID:{path}"
                )
            directories.append(path)
    return sorted(directories)


def validate_final_adoption(directory: Path) -> dict[str, Any]:
    """Validate the complete finalized chain before treating a submission as closed."""
    require_descendant(directory, SUPERVISION_ROOT)
    receipt_path = directory / "systemd_adoption_receipt.json"
    receipt = load_json(receipt_path, ADOPTION_SCHEMA)
    claim = load_json(directory / "submission_claim.json", SUBMISSION_SCHEMA)
    adoption_claim_path = directory / "systemd_adoption_claim.json"
    adoption_claim = load_json(adoption_claim_path, ADOPTION_CLAIM_SCHEMA)
    chain_records = {key: receipt.get(key) for key in SYSTEMD_CHAIN_FILES}
    chain = validate_systemd_chain(EXPERIMENT_ROOT, chain_records, directory)
    if (
        receipt.get("unit") != claim.get("unit")
        or adoption_claim.get("unit") != claim.get("unit")
        or not strict_json_equal(
            receipt.get("systemd_adoption_claim"), identity(adoption_claim_path)
        )
        or any(
            not strict_json_equal(adoption_claim.get(key), record)
            for key, record in chain_records.items()
        )
        or adoption_claim.get("controller_returncode")
        != chain["systemd_execution_receipt"].get("controller_returncode")
        or receipt.get("controller_returncode")
        != chain["systemd_execution_receipt"].get("controller_returncode")
        or receipt.get("controller_outcome") != adoption_claim.get("controller_outcome")
    ):
        raise SystemdSupervisorError(
            f"SYSTEMD_ADOPTION_RECEIPT_BINDING_INVALID:{receipt_path}"
        )
    ordinal_record = receipt.get("ordinal_terminal_receipt")
    if ordinal_record is not None:
        if not isinstance(ordinal_record, Mapping):
            raise SystemdSupervisorError(
                f"SYSTEMD_ORDINAL_TERMINAL_IDENTITY_INVALID:{receipt_path}"
            )
        ordinal_path = Path(str(ordinal_record.get("path", "")))
        require_descendant(ordinal_path, EXPERIMENT_ROOT / "ordinal_receipts")
        if not strict_json_equal(ordinal_record, identity(ordinal_path)):
            raise SystemdSupervisorError(
                f"SYSTEMD_ORDINAL_TERMINAL_IDENTITY_DRIFT:{ordinal_path}"
            )
        ordinal = load_json(ordinal_path)
        if not strict_json_equal(
            ordinal.get("systemd_adoption_claim"), identity(adoption_claim_path)
        ):
            raise SystemdSupervisorError(
                f"SYSTEMD_ORDINAL_TERMINAL_REVERSE_BINDING_DRIFT:{ordinal_path}"
            )
    return receipt


def unadopted_submissions() -> list[Path]:
    pending: list[Path] = []
    for path in submission_directories():
        receipt_path = path / "systemd_adoption_receipt.json"
        if receipt_path.is_symlink() or (
            receipt_path.exists() and not receipt_path.is_file()
        ):
            raise SystemdSupervisorError(
                f"SYSTEMD_ADOPTION_RECEIPT_INVALID:{receipt_path}"
            )
        if not receipt_path.is_file():
            pending.append(path)
            continue
        validate_final_adoption(path)
    return pending


def unit_name(
    ordinal: int, attempt_index: int, submission_index: int, nonce: str
) -> str:
    value = (
        f"{UNIT_PREFIX}-o{ordinal:03d}-a{attempt_index:03d}-"
        f"s{submission_index:03d}-{nonce}.service"
    )
    if not re.fullmatch(r"[a-z0-9_.@-]+\.service", value):
        raise SystemdSupervisorError("SYSTEMD_UNIT_NAME_INVALID")
    return value


def service_argv(unit: str, directory: Path, post: bool = False) -> list[str]:
    command = "service-post" if post else "service-entry"
    return [
        str(PYTHON),
        str(SUPERVISOR),
        command,
        "--unit",
        unit,
        "--submission-dir",
        str(directory),
    ]


def systemd_run_argv(unit: str, directory: Path) -> list[str]:
    post_command = " ".join(service_argv(unit, directory, True))
    return [
        str(SYSTEMD_RUN),
        "--user",
        f"--unit={unit}",
        "--service-type=exec",
        "--property=KillMode=control-group",
        f"--property=RuntimeMaxSec={RUNTIME_MAX_SECONDS}s",
        f"--property=TimeoutStopSec={TIMEOUT_STOP_SECONDS}s",
        "--property=KillSignal=SIGTERM",
        "--property=SendSIGKILL=yes",
        "--property=Restart=no",
        "--property=RemainAfterExit=no",
        "--property=UMask=0077",
        f"--property=StandardOutput=append:{directory / 'systemd.stdout.log'}",
        f"--property=StandardError=append:{directory / 'systemd.stderr.log'}",
        f"--property=ExecStopPost={post_command}",
        f"--description=AQUA-FE fair-stability v5 one ordinal {unit}",
        f"--working-directory={ROOT}",
        *[
            f"--setenv={key}={value}"
            for key, value in FIXED_SERVICE_ENVIRONMENT.items()
        ],
        *service_argv(unit, directory, False),
    ]


def submit() -> dict[str, object]:
    preflight = host_preflight()
    if preflight["ready"] is not True:
        raise SystemdSupervisorError(f"SYSTEMD_HOST_PREFLIGHT_FAILED:{preflight['errors']}")
    context = freeze_context()
    state = next_state(EXPERIMENT_ROOT)
    if state.get("state") not in {
        "READY",
        "PIPELINE_INVALID_UNADJUDICATED",
        "NEEDS_PREPARATION",
    }:
        raise SystemdSupervisorError(f"ORDINAL_STATE_NOT_SUBMITTABLE:{state.get('state')}")
    lock_path = EXPERIMENT_ROOT / ".systemd_submit.lock"
    require_descendant(lock_path, EXPERIMENT_ROOT)
    if lock_path.is_symlink() or (lock_path.exists() and not lock_path.is_file()):
        raise SystemdSupervisorError(f"SYSTEMD_SUBMIT_LOCK_INVALID:{lock_path}")
    lock_descriptor = os.open(
        lock_path,
        os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0),
        0o600,
    )
    with os.fdopen(lock_descriptor, "r+b") as lock_stream:
        fcntl.flock(lock_stream.fileno(), fcntl.LOCK_EX)
        pending = unadopted_submissions()
        if pending:
            raise SystemdSupervisorError(f"UNADOPTED_SYSTEMD_SUBMISSION:{pending[-1]}")
        ordinal = int(state["cell"]["ordinal"])
        attempt_index = int(state["attempt_index"])
        if SUPERVISION_ROOT.is_symlink() or (
            SUPERVISION_ROOT.exists() and not SUPERVISION_ROOT.is_dir()
        ):
            raise SystemdSupervisorError(
                f"SYSTEMD_SUPERVISION_ROOT_INVALID:{SUPERVISION_ROOT}"
            )
        SUPERVISION_ROOT.mkdir(mode=0o700, exist_ok=True)
        require_descendant(SUPERVISION_ROOT, EXPERIMENT_ROOT)
        ordinal_root = SUPERVISION_ROOT / f"ordinal_{ordinal:03d}"
        if ordinal_root.is_symlink() or (
            ordinal_root.exists() and not ordinal_root.is_dir()
        ):
            raise SystemdSupervisorError(
                f"SYSTEMD_ORDINAL_ROOT_INVALID:{ordinal_root}"
            )
        ordinal_root.mkdir(mode=0o700, exist_ok=True)
        require_descendant(ordinal_root, EXPERIMENT_ROOT)
        prior = sorted(ordinal_root.glob("submission_*")) if ordinal_root.exists() else []
        index = len(prior) + 1
        directory = ordinal_root / f"submission_{index:03d}"
        directory.mkdir(mode=0o700, exist_ok=False)
        require_descendant(directory, EXPERIMENT_ROOT)
        create_empty_exclusive(directory / "systemd.stdout.log")
        create_empty_exclusive(directory / "systemd.stderr.log")
        unit = unit_name(ordinal, attempt_index, index, secrets.token_hex(6))
        argv = systemd_run_argv(unit, directory)
        claim = {
            "schema_version": SUBMISSION_SCHEMA,
            "experiment_id": EXPERIMENT_ID,
            "created_at_utc": now_utc(),
            "unit": unit,
            "planned_ordinal": ordinal,
            "attempt_index": attempt_index,
            "attempt_root": str(state["attempt_root"]),
            "submission_index": index,
            "submission_directory": str(directory),
            "ordinal_state_before_submit": state,
            "host_preflight": preflight,
            "frozen_context": context,
            "systemd_run_argv": argv,
            "service_entry_argv": service_argv(unit, directory, False),
            "service_post_argv": service_argv(unit, directory, True),
            "submit_only": True,
            "forbidden_launch_modes": ["nohup", "tmux", "scope", "wait", "collect", "pipe"],
            "systemd_contract": {
                "type": "exec",
                "kill_mode": "control-group",
                "runtime_max_seconds": RUNTIME_MAX_SECONDS,
                "timeout_stop_seconds": TIMEOUT_STOP_SECONDS,
                "send_sigkill": True,
                "restart": False,
                "remain_after_exit": False,
                "transient": True,
                "minimum_fixed_environment": dict(FIXED_SERVICE_ENVIRONMENT),
            },
        }
        write_exclusive(directory / "submission_claim.json", canonical_json(claim))
        command = run_checked(argv, timeout=60.0)
        write_exclusive(directory / "submit.stdout.log", command.stdout.encode("utf-8"))
        write_exclusive(directory / "submit.stderr.log", command.stderr.encode("utf-8"))
        unit_observation = query_unit(unit)
        receipt = {
            "schema_version": SUBMIT_RECEIPT_SCHEMA,
            "experiment_id": EXPERIMENT_ID,
            "recorded_at_utc": now_utc(),
            "unit": unit,
            "submission_claim": identity(directory / "submission_claim.json"),
            "systemd_run": {
                "returncode": command.returncode,
                "stdout": identity(directory / "submit.stdout.log"),
                "stderr": identity(directory / "submit.stderr.log"),
            },
            "unit_observation_after_submit": unit_observation,
            "accepted": command.returncode == 0,
        }
        write_exclusive(directory / "submission_receipt.json", canonical_json(receipt))
        if command.returncode != 0:
            raise SystemdSupervisorError(
                f"SYSTEMD_RUN_SUBMISSION_FAILED:{directory}:rc={command.returncode}"
            )
        return receipt


def wait_for_submit_receipt(directory: Path) -> dict[str, Any]:
    deadline = time.monotonic() + SUBMISSION_RECEIPT_WAIT_SECONDS
    path = directory / "submission_receipt.json"
    while time.monotonic() < deadline:
        if path.is_file() and not path.is_symlink():
            receipt = load_json(path, SUBMIT_RECEIPT_SCHEMA)
            if receipt.get("accepted") is not True:
                raise SystemdSupervisorError("SYSTEMD_SUBMISSION_NOT_ACCEPTED")
            return receipt
        time.sleep(0.05)
    raise SystemdSupervisorError("SYSTEMD_SUBMISSION_RECEIPT_TIMEOUT")


def service_entry(unit: str, directory: Path) -> int:
    require_descendant(directory, SUPERVISION_ROOT)
    claim = load_json(directory / "submission_claim.json", SUBMISSION_SCHEMA)
    if claim.get("unit") != unit or claim.get("submission_directory") != str(directory):
        raise SystemdSupervisorError("SERVICE_ENTRY_SUBMISSION_BINDING_INVALID")
    submit_receipt = wait_for_submit_receipt(directory)
    invocation_id = os.environ.get("INVOCATION_ID", "")
    if not re.fullmatch(r"[0-9a-f]{32}", invocation_id):
        raise SystemdSupervisorError("SERVICE_ENTRY_INVOCATION_ID_MISSING")
    observed_fixed_environment = verify_fixed_service_environment(os.environ)
    preflight = host_preflight()
    if preflight["ready"] is not True:
        raise SystemdSupervisorError("SERVICE_ENTRY_HOST_PREFLIGHT_FAILED")
    context = freeze_context()
    if not strict_json_equal(context, claim.get("frozen_context")):
        raise SystemdSupervisorError("SERVICE_ENTRY_FROZEN_CONTEXT_DRIFT")
    state = next_state(EXPERIMENT_ROOT)
    if not strict_json_equal(state, claim.get("ordinal_state_before_submit")):
        raise SystemdSupervisorError("SERVICE_ENTRY_ORDINAL_STATE_DRIFT")
    observation = query_unit(unit)
    verified = verify_unit_contract(
        unit, observation, require_live_main=True, expected_invocation_id=invocation_id
    )
    own_identity = process_identity(os.getpid())
    if int(verified["main_pid"]) != os.getpid():
        raise SystemdSupervisorError("SERVICE_ENTRY_IS_NOT_SYSTEMD_MAIN_PID")
    verify_process_in_unit(own_identity, str(verified["control_group"]))
    start_receipt = {
        "schema_version": START_RECEIPT_SCHEMA,
        "experiment_id": EXPERIMENT_ID,
        "started_at_utc": now_utc(),
        "unit": unit,
        "invocation_id": invocation_id,
        "submission_claim": identity(directory / "submission_claim.json"),
        "submission_receipt": identity(directory / "submission_receipt.json"),
        "service_process": own_identity,
        "verified_unit": verified,
        "host_preflight": preflight,
        "fixed_service_environment": observed_fixed_environment,
        "frozen_context": context,
        "controller_argv": [str(PYTHON), str(CONTROLLER), "run-next"],
    }
    start_path = directory / "systemd_start_receipt.json"
    write_exclusive(start_path, canonical_json(start_receipt))
    environment = dict(os.environ)
    environment["FAIR_STABILITY_SYSTEMD_START_RECEIPT"] = str(start_path)
    command = subprocess.run(
        [str(PYTHON), str(CONTROLLER), "run-next"],
        cwd=str(ROOT),
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )
    write_exclusive(directory / "controller.stdout.log", command.stdout.encode("utf-8"))
    write_exclusive(directory / "controller.stderr.log", command.stderr.encode("utf-8"))
    try:
        controller_result: object = json.loads(command.stdout)
    except json.JSONDecodeError:
        controller_result = None
    execution = {
        "schema_version": EXECUTION_SCHEMA,
        "experiment_id": EXPERIMENT_ID,
        "ended_at_utc": now_utc(),
        "unit": unit,
        "invocation_id": invocation_id,
        "systemd_start_receipt": identity(start_path),
        "controller": identity(CONTROLLER),
        "controller_returncode": command.returncode,
        "controller_stdout": identity(directory / "controller.stdout.log"),
        "controller_stderr": identity(directory / "controller.stderr.log"),
        "controller_result": controller_result,
        "ordinal_state_after_controller": next_state(EXPERIMENT_ROOT),
    }
    write_exclusive(directory / "systemd_execution_receipt.json", canonical_json(execution))
    return int(command.returncode)


def service_post(unit: str, directory: Path) -> int:
    require_descendant(directory, SUPERVISION_ROOT)
    claim = load_json(directory / "submission_claim.json", SUBMISSION_SCHEMA)
    if claim.get("unit") != unit:
        raise SystemdSupervisorError("SERVICE_POST_UNIT_BINDING_INVALID")
    terminal_path = directory / "systemd_terminal_receipt.json"
    if terminal_path.exists() or terminal_path.is_symlink():
        raise SystemdSupervisorError("SYSTEMD_TERMINAL_RECEIPT_ALREADY_EXISTS")
    observation = query_unit(unit)
    invocation_id = os.environ.get("INVOCATION_ID", "")
    verified_unit = verify_unit_contract(
        unit,
        observation,
        require_live_main=False,
        expected_invocation_id=invocation_id,
    )
    properties = observation.get("properties", {})
    terminal = {
        "schema_version": TERMINAL_SCHEMA,
        "experiment_id": EXPERIMENT_ID,
        "recorded_at_utc": now_utc(),
        "unit": unit,
        "invocation_id_environment": invocation_id,
        "service_result_environment": os.environ.get("SERVICE_RESULT"),
        "exit_code_environment": os.environ.get("EXIT_CODE"),
        "exit_status_environment": os.environ.get("EXIT_STATUS"),
        "systemd_observation_during_exec_stop_post": observation,
        "verified_unit_contract_during_exec_stop_post": verified_unit,
        "observed_tuple": {
            "Result": properties.get("Result") if isinstance(properties, Mapping) else None,
            "ExecMainCode": properties.get("ExecMainCode") if isinstance(properties, Mapping) else None,
            "ExecMainStatus": properties.get("ExecMainStatus") if isinstance(properties, Mapping) else None,
            "ActiveState": properties.get("ActiveState") if isinstance(properties, Mapping) else None,
            "SubState": properties.get("SubState") if isinstance(properties, Mapping) else None,
        },
        "submission_claim": identity(directory / "submission_claim.json"),
        "submission_receipt": (
            identity(directory / "submission_receipt.json")
            if (directory / "submission_receipt.json").is_file()
            else None
        ),
        "systemd_start_receipt": (
            identity(directory / "systemd_start_receipt.json")
            if (directory / "systemd_start_receipt.json").is_file()
            else None
        ),
        "systemd_execution_receipt": (
            identity(directory / "systemd_execution_receipt.json")
            if (directory / "systemd_execution_receipt.json").is_file()
            else None
        ),
        "systemd_stdout": identity(directory / "systemd.stdout.log"),
        "systemd_stderr": identity(directory / "systemd.stderr.log"),
        "authorized_stop_request_present": False,
        "timeout_or_signal_is_fail_stop_not_retryable": True,
    }
    write_exclusive(terminal_path, canonical_json(terminal))
    return 0


def latest_submission() -> Path:
    directories = submission_directories()
    if not directories:
        raise SystemdSupervisorError("NO_SYSTEMD_SUBMISSION")
    return directories[-1]


def poll(directory: Path | None = None) -> dict[str, object]:
    selected = latest_submission() if directory is None else directory
    require_descendant(selected, SUPERVISION_ROOT)
    claim = load_json(selected / "submission_claim.json", SUBMISSION_SCHEMA)
    return {
        "schema_version": "aqua-fe-fair-stability-systemd-poll-v5",
        "experiment_id": EXPERIMENT_ID,
        "polled_at_utc": now_utc(),
        "submission_directory": str(selected),
        "unit": claim["unit"],
        "unit_observation": query_unit(str(claim["unit"])),
        "receipts": poll_receipts(selected),
        "ordinal_state": next_state(EXPERIMENT_ROOT),
    }


def poll_receipts(directory: Path) -> dict[str, dict[str, object] | None]:
    receipts: dict[str, dict[str, object] | None] = {}
    for name in (
        "submission_claim.json",
        "submission_receipt.json",
        "systemd_start_receipt.json",
        "systemd_execution_receipt.json",
        "systemd_terminal_receipt.json",
        "systemd_adoption_claim.json",
        "systemd_adoption_receipt.json",
    ):
        path = directory / name
        if path.is_symlink() or (path.exists() and not path.is_file()):
            raise SystemdSupervisorError(f"SYSTEMD_RECEIPT_PATH_INVALID:{path}")
        receipts[name] = identity(path) if path.is_file() else None
    return receipts


def adopt(directory: Path | None = None) -> dict[str, object]:
    selected = latest_submission() if directory is None else directory
    require_descendant(selected, SUPERVISION_ROOT)
    final_path = selected / "systemd_adoption_receipt.json"
    if final_path.exists() or final_path.is_symlink():
        raise SystemdSupervisorError("SYSTEMD_SUBMISSION_ALREADY_ADOPTED")
    claim = load_json(selected / "submission_claim.json", SUBMISSION_SCHEMA)
    terminal = load_json(selected / "systemd_terminal_receipt.json", TERMINAL_SCHEMA)
    if terminal.get("unit") != claim.get("unit"):
        raise SystemdSupervisorError("SYSTEMD_TERMINAL_UNIT_MISMATCH")
    execution_path = selected / "systemd_execution_receipt.json"
    if not execution_path.is_file():
        raise SystemdSupervisorError("SYSTEMD_EXECUTION_RECEIPT_MISSING_FAIL_STOP")
    execution = load_json(execution_path, EXECUTION_SCHEMA)
    if execution.get("unit") != claim.get("unit"):
        raise SystemdSupervisorError("SYSTEMD_EXECUTION_UNIT_MISMATCH")
    start_path = selected / "systemd_start_receipt.json"
    start = load_json(start_path, START_RECEIPT_SCHEMA)
    submission_receipt_path = selected / "submission_receipt.json"
    load_json(submission_receipt_path, SUBMIT_RECEIPT_SCHEMA)
    chain_records = {
        "submission_claim": identity(selected / "submission_claim.json"),
        "submission_receipt": identity(submission_receipt_path),
        "systemd_start_receipt": identity(start_path),
        "systemd_execution_receipt": identity(execution_path),
        "systemd_terminal_receipt": identity(
            selected / "systemd_terminal_receipt.json"
        ),
    }
    validate_systemd_chain(EXPERIMENT_ROOT, chain_records, selected)
    for key, path in (
        ("submission_claim", selected / "submission_claim.json"),
        ("submission_receipt", submission_receipt_path),
        ("systemd_start_receipt", start_path),
        ("systemd_execution_receipt", execution_path),
    ):
        if not strict_json_equal(terminal.get(key), identity(path)):
            raise SystemdSupervisorError(
                f"SYSTEMD_TERMINAL_EMBEDDED_IDENTITY_DRIFT:{key}"
            )
    invocation_ids = {
        str(start.get("invocation_id", "")),
        str(execution.get("invocation_id", "")),
        str(terminal.get("invocation_id_environment", "")),
    }
    if len(invocation_ids) != 1 or not re.fullmatch(
        r"[0-9a-f]{32}", next(iter(invocation_ids))
    ):
        raise SystemdSupervisorError("SYSTEMD_INVOCATION_CHAIN_MISMATCH")
    service_result = terminal.get("service_result_environment")
    exit_code = terminal.get("exit_code_environment")
    exit_status = str(terminal.get("exit_status_environment") or "")
    observed_tuple = terminal.get("observed_tuple")
    if not isinstance(observed_tuple, Mapping):
        raise SystemdSupervisorError("SYSTEMD_TERMINAL_OBSERVED_TUPLE_MISSING")
    code_numbers = {"exited": "1", "killed": "2", "dumped": "3"}
    if (
        observed_tuple.get("Result") != service_result
        or code_numbers.get(str(exit_code)) != str(observed_tuple.get("ExecMainCode"))
        or exit_status != str(observed_tuple.get("ExecMainStatus"))
    ):
        raise SystemdSupervisorError("SYSTEMD_TERMINAL_ENVIRONMENT_TUPLE_MISMATCH")
    returncode = int(execution.get("controller_returncode", -1))
    if service_result == "timeout" or exit_code in {"killed", "dumped"}:
        raise SystemdSupervisorError("SYSTEMD_TIMEOUT_OR_SIGNAL_FAIL_STOP_ABANDON_V5")
    if exit_code != "exited" or not exit_status.isdigit() or int(exit_status) != returncode:
        raise SystemdSupervisorError("SYSTEMD_TERMINAL_TUPLE_EXECUTION_MISMATCH")
    if returncode not in {0, 4, 75}:
        raise SystemdSupervisorError(f"CONTROLLER_RETURN_CODE_NOT_ADOPTABLE:{returncode}")
    state = next_state(EXPERIMENT_ROOT)
    if state.get("state") == "STARTED_WITHOUT_RESULT":
        raise SystemdSupervisorError("STARTED_WITHOUT_RESULT_FAIL_STOP_ABANDON_V5")
    controller_result = execution.get("controller_result")
    if not isinstance(controller_result, Mapping):
        raise SystemdSupervisorError("CONTROLLER_RESULT_NOT_JSON_OBJECT")
    authority = controller_result.get("systemd_authority")
    if (
        not isinstance(authority, Mapping)
        or authority.get("path") != str(start_path)
        or not strict_json_equal(authority.get("identity"), identity(start_path))
        or not strict_json_equal(authority.get("receipt"), start)
    ):
        raise SystemdSupervisorError("CONTROLLER_SYSTEMD_AUTHORITY_BINDING_INVALID")
    if state.get("state") not in {
        "TERMINAL_UNADOPTED",
        "PIPELINE_INVALID_UNADJUDICATED",
        "READY",
        "NEEDS_PREPARATION",
    }:
        raise SystemdSupervisorError(
            f"ORDINAL_STATE_NOT_SYSTEMD_ADOPTABLE:{state.get('state')}"
        )
    adoption_claim = {
        "schema_version": ADOPTION_CLAIM_SCHEMA,
        "experiment_id": EXPERIMENT_ID,
        "created_at_utc": now_utc(),
        "unit": claim["unit"],
        "planned_ordinal": int(claim["planned_ordinal"]),
        "attempt_index": int(claim["attempt_index"]),
        "attempt_root": str(claim["attempt_root"]),
        "ordinal_state_before_adoption": state,
        "submission_claim": identity(selected / "submission_claim.json"),
        "submission_receipt": identity(submission_receipt_path),
        "systemd_start_receipt": identity(start_path),
        "systemd_execution_receipt": identity(execution_path),
        "systemd_terminal_receipt": identity(
            selected / "systemd_terminal_receipt.json"
        ),
        "controller_returncode": returncode,
        "controller_outcome": controller_result.get("outcome"),
        "timeout_or_signal_observed": False,
        "estimator_retry_authorized": False,
    }
    adoption_claim_path = selected / "systemd_adoption_claim.json"
    write_exclusive(adoption_claim_path, canonical_json(adoption_claim))
    ordinal_terminal_identity: dict[str, object] | None = None
    if state.get("state") == "TERMINAL_UNADOPTED":
        from run_fair_stability_next_v5 import adopt_terminal

        adopt_terminal(state, adoption_claim_path)
        ordinal_terminal_identity = identity(Path(str(state["terminal_receipt"])))
    state_after = next_state(EXPERIMENT_ROOT)
    receipt = {
        "schema_version": ADOPTION_SCHEMA,
        "experiment_id": EXPERIMENT_ID,
        "adopted_at_utc": now_utc(),
        "unit": claim["unit"],
        "submission_claim": identity(selected / "submission_claim.json"),
        "submission_receipt": identity(submission_receipt_path),
        "systemd_start_receipt": identity(start_path),
        "systemd_execution_receipt": identity(execution_path),
        "systemd_terminal_receipt": identity(selected / "systemd_terminal_receipt.json"),
        "systemd_adoption_claim": identity(adoption_claim_path),
        "ordinal_terminal_receipt": ordinal_terminal_identity,
        "controller_returncode": returncode,
        "controller_outcome": controller_result.get("outcome"),
        "ordinal_state_before_final_adoption_receipt": state_after,
        "estimator_retry_authorized": False,
        "next_submission_requires_new_submit": True,
    }
    write_exclusive(final_path, canonical_json(receipt))
    return validate_final_adoption(selected)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("preflight")
    sub.add_parser("submit")
    for name in ("poll", "adopt"):
        child = sub.add_parser(name)
        child.add_argument("--submission-dir", type=Path)
    for name in ("service-entry", "service-post"):
        child = sub.add_parser(name)
        child.add_argument("--unit", required=True)
        child.add_argument("--submission-dir", required=True, type=Path)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        if args.command == "preflight":
            result = host_preflight()
            returncode = 0 if result["ready"] is True else 2
        elif args.command == "submit":
            result = submit()
            returncode = 0
        elif args.command == "poll":
            result = poll(args.submission_dir)
            returncode = 0
        elif args.command == "adopt":
            result = adopt(args.submission_dir)
            returncode = 0
        elif args.command == "service-entry":
            return service_entry(args.unit, args.submission_dir)
        elif args.command == "service-post":
            return service_post(args.unit, args.submission_dir)
        else:  # pragma: no cover
            raise SystemdSupervisorError("UNKNOWN_COMMAND")
        print(json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False))
        return returncode
    except BaseException as error:
        print(f"{type(error).__name__}:{error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
