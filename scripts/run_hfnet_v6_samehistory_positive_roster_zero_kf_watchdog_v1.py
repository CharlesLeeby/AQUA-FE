#!/usr/bin/env python3
"""Prospective zero-keyframe save-hang watchdog for the nine remaining v2 cases.

This is deliberately an external liveness supervisor.  It does not import,
patch, or replace the frozen v2 runner, estimator binary, case specification,
or result logic.  It invokes the existing runner entry exactly once and waits
passively except for one narrowly authorized action: after the complete known
terminal signature has remained true for a fixed grace period, send SIGTERM
through a Linux pidfd to the exact validated HFNet child.  There is no retry,
no process-group signal, no SIGKILL, and no signal for any other condition.

The authorization token is read from a non-echoing terminal prompt or stdin.
It is carried to an in-memory ``runpy`` bootstrap over an anonymous pipe, so it
never appears in an OS argv, environment variable, log, or watchdog receipt.
"""

from __future__ import annotations

import argparse
import ctypes
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import errno
import getpass
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import tempfile
import time
from typing import Any, Callable, Mapping, Sequence, TextIO


ROOT = Path(__file__).resolve().parents[1]
SUPERVISOR = Path(__file__).resolve()
RUNNER = ROOT / "scripts/run_hfnet_v6_samehistory_positive_roster_v2.py"
ROSTER_ROOT = Path(
    "/mnt/data/AQUA-FE_WS/logs/published_hfnet_slam_v6/"
    "samehistory_old_positive_roster_v2"
)
PUBLICATION_POINTER = Path(
    "/mnt/data/AQUA-FE_WS/locks/"
    "hfnet_v6_samehistory_positive_roster_execution_lock_v2.json"
)
PREFREEZE_SEAL = Path(
    "/mnt/data/AQUA-FE_WS/locks/"
    "hfnet_v6_samehistory_positive_accuracy_prefreeze_seal_v1.json"
)
WATCHDOG_ROOT = ROSTER_ROOT / "_zero_kf_save_hang_watchdog_v1"

RUNNER_PIN = {
    "path": str(RUNNER),
    "size_bytes": 7_639,
    "sha256": "ec1afff8b1f7a8fdac0e7d395648bd4aa4b47b107bd3c2871a034eb49ba83bbb",
}
POINTER_PIN = {
    "path": str(PUBLICATION_POINTER),
    "size_bytes": 5_296,
    "sha256": "f9b44e9c126e68d151368c84a562aef5f9b06e1200b6f5dd1b6fe55d33430df1",
}
SEAL_PIN = {
    "path": str(PREFREEZE_SEAL),
    "size_bytes": 98_877,
    "sha256": "67f2ae286d0e0e3f19a7b490711318e9f7b059c12949e3efe297bbbe5151c6b5",
}

# a05 was already consumed before this prospective supervisor existed.
REMAINING_CASE_IDS = (
    "a07_10800_11200",
    "a08_4500_4660",
    "a09_6000_6200",
    "fjord1_s83_d10",
    "mclab1_s60_d15",
    "cirs_s575_d30",
    "cirs_s900_d30",
    "a02_7600_8000",
    "mclab2_s110_d10",
)

SIGNATURE_GRACE_SECONDS = 30.0
POLL_SECONDS = 0.25
PIDFD_OPEN_SYSCALL_X86_64 = 434
PIDFD_SEND_SIGNAL_SYSCALL_X86_64 = 424

POINTER_SCHEMA = "aqua-fe-hfnet-v6-samehistory-roster-publication-pointer-v1"
CASE_SCHEMA = "aqua-fe-hfnet-v6-samehistory-positive-case-v2"
PREPARED_SCHEMA = "aqua-fe-hfnet-v6-samehistory-positive-prepared-v2"
RECEIPT_SCHEMA = "aqua-fe-hfnet-v6-zero-kf-save-hang-watchdog-receipt-v1"


class WatchdogContractError(RuntimeError):
    """A prospective watchdog safety contract was violated."""


@dataclass(frozen=True)
class ChildIdentity:
    pid: int
    ppid: int
    starttime_ticks: int
    executable: str
    argv: tuple[str, ...]


@dataclass
class ChildHandle:
    identity: ChildIdentity
    pidfd: int


@dataclass(frozen=True)
class CaseContract:
    case_id: str
    case_spec: Path
    case_spec_identity: Mapping[str, object]
    prepared_manifest: Path
    prepared_manifest_identity: Mapping[str, object]
    attempt_root: Path
    stdout_log: Path
    trajectory: Path
    run_result: Path
    receipt: Path
    expected_hfnet_argv: tuple[str, ...]
    expected_hfnet_executable: str
    expected_hfnet_binary_identity: Mapping[str, object]
    authorization_token: str


@dataclass
class MonitorOutcome:
    runner_returncode: int | None
    runner_reaped: bool
    child: ChildIdentity | None
    child_discovered_at_utc: str | None
    signature_first_observed_at_utc: str | None
    signature_evidence: Mapping[str, object] | None
    signal_attempted: bool
    sigterm_sent: bool
    sigterm_sent_at_utc: str | None
    signal_delivery: str | None
    post_signal_identity_state: str | None
    runner_popen_invocations: int
    monitoring_errors: list[str]


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def canonical_json(value: object) -> bytes:
    return (
        json.dumps(
            value,
            indent=2,
            sort_keys=True,
            ensure_ascii=False,
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def identity(path: Path) -> dict[str, object]:
    if path.is_symlink() or not path.is_file():
        raise WatchdogContractError(f"REGULAR_FILE_REQUIRED:{path}")
    return {
        "path": str(path),
        "size_bytes": path.stat().st_size,
        "sha256": _sha256(path),
    }


def safe_identity(path: Path) -> dict[str, object] | None:
    try:
        return identity(path)
    except (OSError, WatchdogContractError):
        return None


def _require_identity(path: Path, expected: Mapping[str, object], label: str) -> None:
    if identity(path) != dict(expected):
        raise WatchdogContractError(f"IDENTITY_MISMATCH:{label}")


def _load_json(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise WatchdogContractError(f"JSON_INVALID:{label}:{type(error).__name__}") from error
    if not isinstance(value, dict):
        raise WatchdogContractError(f"JSON_OBJECT_REQUIRED:{label}")
    return value


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _ensure_plain_directory(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    if path.is_symlink() or not path.is_dir():
        raise WatchdogContractError(f"DIRECTORY_MISSING_OR_SYMLINK:{path}")


def publish_exclusive(path: Path, payload: bytes, mode: int = 0o444) -> None:
    """Publish complete bytes on FUSE using hard-link no-replace semantics."""

    _ensure_plain_directory(path.parent)
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
            raise WatchdogContractError(f"RECEIPT_ALREADY_EXISTS:{path}") from error
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


def _exact_path_from_pin(value: Mapping[str, object], label: str) -> Path:
    try:
        path = Path(str(value["path"]))
        size = int(value["size_bytes"])
        digest = str(value["sha256"])
    except (KeyError, TypeError, ValueError) as error:
        raise WatchdogContractError(f"IDENTITY_PIN_INVALID:{label}") from error
    if not path.is_absolute() or size < 0 or not re.fullmatch(r"[0-9a-f]{64}", digest):
        raise WatchdogContractError(f"IDENTITY_PIN_INVALID:{label}")
    return path


def load_case_contract(case_spec: Path) -> CaseContract:
    """Bind the watchdog to the sealed v2 roster and one remaining case."""

    if not case_spec.is_absolute() or case_spec.is_symlink():
        raise WatchdogContractError("CASE_SPEC_MUST_BE_ABSOLUTE_REGULAR_FILE")
    _require_identity(RUNNER, RUNNER_PIN, "FROZEN_V2_RUNNER")
    _require_identity(PUBLICATION_POINTER, POINTER_PIN, "V2_ROSTER_POINTER")
    _require_identity(PREFREEZE_SEAL, SEAL_PIN, "ACCURACY_PREFREEZE_SEAL")

    pointer = _load_json(PUBLICATION_POINTER, "V2_ROSTER_POINTER")
    seal = _load_json(PREFREEZE_SEAL, "ACCURACY_PREFREEZE_SEAL")
    if pointer.get("schema_version") != POINTER_SCHEMA or pointer.get("status") != "FROZEN_READY_FOR_EXECUTION":
        raise WatchdogContractError("V2_ROSTER_POINTER_STATUS_INVALID")
    if seal.get("authorities", {}).get("prepared_runner") != RUNNER_PIN:
        raise WatchdogContractError("SEAL_RUNNER_PIN_MISMATCH")
    if seal.get("authorities", {}).get("whole_roster_pointer") != POINTER_PIN:
        raise WatchdogContractError("SEAL_POINTER_PIN_MISMATCH")

    pointer_rows = pointer.get("cases")
    seal_rows = seal.get("cases")
    if not isinstance(pointer_rows, list) or not isinstance(seal_rows, list):
        raise WatchdogContractError("ROSTER_CASE_ROWS_INVALID")
    pointer_by_id = {str(row.get("case_id")): row for row in pointer_rows if isinstance(row, dict)}
    seal_by_id = {str(row.get("case_id")): row for row in seal_rows if isinstance(row, dict)}

    spec = _load_json(case_spec, "CASE_SPEC")
    case_id = str(spec.get("case_id", ""))
    if case_id not in REMAINING_CASE_IDS:
        raise WatchdogContractError(f"CASE_NOT_IN_REMAINING_NINE:{case_id}")
    if case_id not in pointer_by_id or case_id not in seal_by_id:
        raise WatchdogContractError(f"CASE_NOT_IN_SEALED_ROSTER:{case_id}")
    if spec.get("schema_version") != CASE_SCHEMA or spec.get("status") != "FROZEN_READY_FOR_ONE_SHOT_COLDSTART":
        raise WatchdogContractError("CASE_SPEC_STATUS_INVALID")
    if spec.get("retry_permitted") is not False:
        raise WatchdogContractError("CASE_RETRY_MUST_REMAIN_FALSE")

    spec_identity = identity(case_spec)
    pointer_spec_pin = pointer_by_id[case_id].get("spec")
    seal_spec_pin = seal_by_id[case_id].get("case_spec")
    if spec_identity != pointer_spec_pin or spec_identity != seal_spec_pin:
        raise WatchdogContractError("CASE_SPEC_NOT_EXACT_SEALED_POINTER_MEMBER")
    if str(case_spec) != str(pointer_spec_pin.get("path")):
        raise WatchdogContractError("CASE_SPEC_PATH_ALIAS_FORBIDDEN")

    attempt_root = ROSTER_ROOT / case_id / "attempt_001"
    if spec.get("attempt_root") != str(attempt_root):
        raise WatchdogContractError("ATTEMPT_ROOT_NOT_CANONICAL")
    prepared_path = attempt_root / "prepared_manifest.json"
    prepared_identity = identity(prepared_path)
    if prepared_identity != seal_by_id[case_id].get("prepared_manifest"):
        raise WatchdogContractError("PREPARED_MANIFEST_NOT_SEALED")
    prepared = _load_json(prepared_path, "PREPARED_MANIFEST")
    if prepared.get("schema_version") != PREPARED_SCHEMA or prepared.get("status") != "PREPARED_NOT_STARTED":
        raise WatchdogContractError("PREPARED_MANIFEST_STATUS_INVALID")
    if prepared.get("case_id") != case_id or prepared.get("case_spec") != spec_identity:
        raise WatchdogContractError("PREPARED_MANIFEST_CASE_BINDING_INVALID")
    if prepared.get("runner") != RUNNER_PIN:
        raise WatchdogContractError("PREPARED_MANIFEST_RUNNER_PIN_MISMATCH")

    launch = prepared.get("launch")
    stack = prepared.get("stack")
    if not isinstance(launch, dict) or not isinstance(stack, dict):
        raise WatchdogContractError("PREPARED_LAUNCH_OR_STACK_INVALID")
    argv = launch.get("argv")
    binary_pin = stack.get("binary")
    if not isinstance(argv, list) or not argv or not all(isinstance(item, str) for item in argv):
        raise WatchdogContractError("HFNET_LAUNCH_ARGV_INVALID")
    if launch.get("cwd") != str(attempt_root) or launch.get("maximum_popen_invocations") != 1:
        raise WatchdogContractError("HFNET_LAUNCH_BOUNDARY_INVALID")
    if not isinstance(binary_pin, dict) or argv[0] != binary_pin.get("path"):
        raise WatchdogContractError("HFNET_BINARY_LAUNCH_PIN_INVALID")
    binary_path = _exact_path_from_pin(binary_pin, "HFNET_BINARY")
    _require_identity(binary_path, binary_pin, "HFNET_BINARY")
    result_dir = attempt_root / "result"
    if len(argv) < 3 or argv[2] != str(result_dir) + "/":
        raise WatchdogContractError("HFNET_RESULT_DIRECTORY_ARG_INVALID")

    token = spec.get("authorization_token")
    if not isinstance(token, str) or not re.fullmatch(r"[0-9a-f]{64}", token):
        raise WatchdogContractError("AUTHORIZATION_TOKEN_FORMAT_INVALID")
    receipt = WATCHDOG_ROOT / f"{case_id}.json"
    if receipt.exists() or receipt.is_symlink():
        raise WatchdogContractError(f"WATCHDOG_RECEIPT_ALREADY_EXISTS:{receipt}")

    return CaseContract(
        case_id=case_id,
        case_spec=case_spec,
        case_spec_identity=spec_identity,
        prepared_manifest=prepared_path,
        prepared_manifest_identity=prepared_identity,
        attempt_root=attempt_root,
        stdout_log=attempt_root / "headless.stdout.log",
        trajectory=result_dir / "trajectory.txt",
        run_result=attempt_root / "run_result.json",
        receipt=receipt,
        expected_hfnet_argv=tuple(argv),
        expected_hfnet_executable=os.path.realpath(str(binary_path)),
        expected_hfnet_binary_identity=dict(binary_pin),
        authorization_token=token,
    )


def read_authorization_token(stream: TextIO | None = None) -> str:
    """Read one 64-hex token without placing it in argv or the environment."""

    source = sys.stdin if stream is None else stream
    if stream is None and source.isatty():
        token = getpass.getpass("HFNet one-shot authorization token: ")
    else:
        token = source.read(4097)
        if len(token) > 4096:
            raise WatchdogContractError("AUTHORIZATION_TOKEN_INPUT_TOO_LARGE")
        token = token.rstrip("\r\n")
    if not re.fullmatch(r"[0-9a-f]{64}", token):
        raise WatchdogContractError("AUTHORIZATION_TOKEN_FORMAT_INVALID")
    return token


RUNNER_BOOTSTRAP = (
    "import os,runpy,sys;"
    "fd=int(sys.argv[1]);runner=sys.argv[2];case_spec=sys.argv[3];"
    "parts=[];"
    "\nwhile True:\n"
    " b=os.read(fd,4096)\n"
    " if not b: break\n"
    " parts.append(b)\n"
    "\nos.close(fd);token=b''.join(parts).decode('ascii');"
    "sys.argv=[runner,'run','--case-spec',case_spec,'--authorization-token',token];"
    "del parts,token;runpy.run_path(runner,run_name='__main__')"
)


def runner_bootstrap_argv(read_fd: int, case_spec: Path) -> list[str]:
    """Return an OS argv that intentionally contains no authorization token."""

    return [
        sys.executable,
        "-c",
        RUNNER_BOOTSTRAP,
        str(read_fd),
        str(RUNNER),
        str(case_spec),
    ]


def runner_environment() -> dict[str, str]:
    """Use a small fixed environment; no caller secret is inherited."""

    return {
        "HOME": "/home/ma",
        "USER": "ma",
        "LOGNAME": "ma",
        "LANG": "C",
        "LC_ALL": "C",
        "PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
        "PYTHONUNBUFFERED": "1",
    }


def _write_all(descriptor: int, payload: bytes) -> None:
    view = memoryview(payload)
    while view:
        written = os.write(descriptor, view)
        if written <= 0:
            raise OSError("short write to authorization pipe")
        view = view[written:]


def launch_runner_once(
    case_spec: Path,
    token: str,
    *,
    popen: Callable[..., Any] = subprocess.Popen,
) -> tuple[Any, str | None]:
    """Popen one secure bootstrap and deliver the token over an anonymous pipe."""

    read_fd, write_fd = os.pipe()
    process: Any | None = None
    delivery_error: str | None = None
    try:
        process = popen(
            runner_bootstrap_argv(read_fd, case_spec),
            env=runner_environment(),
            pass_fds=(read_fd,),
            close_fds=True,
            start_new_session=True,
        )
        os.close(read_fd)
        read_fd = -1
        try:
            _write_all(write_fd, token.encode("ascii"))
        except OSError as error:
            delivery_error = f"ANONYMOUS_TOKEN_PIPE_DELIVERY_FAILED:{type(error).__name__}:{error.errno}"
    finally:
        if read_fd >= 0:
            os.close(read_fd)
        os.close(write_fd)
    if process is None:
        raise WatchdogContractError("RUNNER_POPEN_FAILED")
    return process, delivery_error


def _read_proc_identity(proc_root: Path, pid: int) -> ChildIdentity | None:
    root = proc_root / str(pid)
    try:
        stat = (root / "stat").read_text(encoding="ascii")
        close = stat.rfind(")")
        if close < 0:
            return None
        fields = stat[close + 2 :].split()
        if len(fields) < 20:
            return None
        ppid = int(fields[1])
        starttime = int(fields[19])
        executable = os.readlink(root / "exe")
        raw = (root / "cmdline").read_bytes()
        argv = tuple(
            token.decode("utf-8", errors="strict")
            for token in raw.split(b"\0")
            if token
        )
    except (OSError, UnicodeDecodeError, ValueError):
        return None
    return ChildIdentity(
        pid=pid,
        ppid=ppid,
        starttime_ticks=starttime,
        executable=os.path.realpath(executable),
        argv=argv,
    )


def _child_is_exact(
    observed: ChildIdentity,
    runner_pid: int,
    contract: CaseContract,
) -> bool:
    return bool(
        observed.ppid == runner_pid
        and observed.executable == contract.expected_hfnet_executable
        and observed.argv == contract.expected_hfnet_argv
    )


def _direct_child_pids(proc_root: Path, runner_pid: int) -> list[int]:
    try:
        text = (proc_root / str(runner_pid) / "task" / str(runner_pid) / "children").read_text(encoding="ascii")
        values = [int(value) for value in text.split()]
    except (OSError, ValueError):
        return []
    return values


def _libc_syscall(number: int, *arguments: object) -> int:
    libc = ctypes.CDLL(None, use_errno=True)
    value = int(libc.syscall(number, *arguments))
    if value < 0:
        error_number = ctypes.get_errno()
        raise OSError(error_number, os.strerror(error_number))
    return value


def pidfd_open(pid: int) -> int:
    return _libc_syscall(PIDFD_OPEN_SYSCALL_X86_64, pid, 0)


def pidfd_send_sigterm(pidfd: int) -> None:
    _libc_syscall(
        PIDFD_SEND_SIGNAL_SYSCALL_X86_64,
        pidfd,
        signal.SIGTERM,
        ctypes.c_void_p(0),
        0,
    )


def discover_exact_child(
    proc_root: Path,
    runner_pid: int,
    contract: CaseContract,
    *,
    open_pidfd: Callable[[int], int] = pidfd_open,
    close_fd: Callable[[int], None] = os.close,
) -> ChildHandle | None:
    """Capture one exact direct child and bind it to a pidfd against PID reuse."""

    matches: list[ChildIdentity] = []
    for pid in _direct_child_pids(proc_root, runner_pid):
        observed = _read_proc_identity(proc_root, pid)
        if observed is not None and _child_is_exact(observed, runner_pid, contract):
            matches.append(observed)
    if len(matches) != 1:
        return None
    first = matches[0]
    try:
        descriptor = open_pidfd(first.pid)
    except OSError:
        return None
    second = _read_proc_identity(proc_root, first.pid)
    if second != first:
        close_fd(descriptor)
        return None
    return ChildHandle(identity=first, pidfd=descriptor)


def parse_zero_kf_save_hang_signature(
    stdout_log: Path,
    trajectory: Path,
) -> dict[str, object]:
    """Recognize only the complete ordered terminal zero-KF save-hang signature."""

    evidence: dict[str, object] = {
        "confirmed": False,
        "shutdown_observed": False,
        "saving_trajectory_observed": False,
        "complete_atlas_rows_observed": False,
        "every_reported_atlas_map_zero_keyframes": False,
        "trajectory_absent": not (trajectory.exists() or trajectory.is_symlink()),
        "end_of_saving_absent": True,
    }
    if stdout_log.is_symlink() or not stdout_log.is_file():
        return evidence
    try:
        lines = stdout_log.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return evidence
    saving_prefix = f"Saving trajectory to {trajectory}"
    saving_index = max(
        (index for index, line in enumerate(lines) if line.startswith(saving_prefix)),
        default=-1,
    )
    if saving_index < 0:
        return evidence
    shutdown_indices = [
        index for index, line in enumerate(lines[:saving_index]) if line.strip() == "Shutdown"
    ]
    evidence["saving_trajectory_observed"] = True
    evidence["saving_line_index_zero_based"] = saving_index
    evidence["shutdown_observed"] = bool(shutdown_indices)
    if shutdown_indices:
        evidence["shutdown_line_index_zero_based"] = shutdown_indices[-1]
    if not shutdown_indices:
        return evidence

    tail = lines[saving_index + 1 :]
    atlas_index = -1
    atlas_count: int | None = None
    for relative_index, line in enumerate(tail):
        match = re.fullmatch(r"\s*There are (\d+) maps in (?:the )?atlas\s*", line)
        if match:
            atlas_index = saving_index + 1 + relative_index
            atlas_count = int(match.group(1))
    if atlas_index < 0 or atlas_count is None or atlas_count < 1:
        return evidence
    evidence["atlas_line_index_zero_based"] = atlas_index
    evidence["atlas_map_count"] = atlas_count

    map_rows: list[tuple[int, int]] = []
    end_observed = False
    for line in lines[atlas_index + 1 :]:
        if line.startswith("End of saving trajectory to "):
            end_observed = True
            break
        match = re.fullmatch(r"\s*Map (\d+) has (\d+) KFs\s*", line)
        if match:
            map_rows.append((int(match.group(1)), int(match.group(2))))
    complete = bool(
        len(map_rows) == atlas_count
        and {row[0] for row in map_rows} == set(range(atlas_count))
    )
    all_zero = bool(complete and all(keyframes == 0 for _, keyframes in map_rows))
    trajectory_absent = not (trajectory.exists() or trajectory.is_symlink())
    evidence.update(
        {
            "map_keyframes_by_id": [[map_id, keyframes] for map_id, keyframes in map_rows],
            "complete_atlas_rows_observed": complete,
            "every_reported_atlas_map_zero_keyframes": all_zero,
            "trajectory_absent": trajectory_absent,
            "end_of_saving_absent": not end_observed,
            "confirmed": bool(complete and all_zero and trajectory_absent and not end_observed),
        }
    )
    return evidence


def send_sigterm_to_exact_child(
    handle: ChildHandle,
    runner_pid: int,
    contract: CaseContract,
    *,
    proc_root: Path = Path("/proc"),
    send_pidfd: Callable[[int], None] = pidfd_send_sigterm,
) -> tuple[bool, str, str]:
    """Revalidate, signal via pidfd once, then audit post-signal PID state."""

    before = _read_proc_identity(proc_root, handle.identity.pid)
    if before != handle.identity or not _child_is_exact(before, runner_pid, contract):
        return False, "PRE_SIGNAL_EXACT_CHILD_REVALIDATION_FAILED", "NOT_OBSERVED"
    try:
        send_pidfd(handle.pidfd)
    except OSError as error:
        if error.errno in (errno.ESRCH, errno.EBADF):
            return False, f"PIDFD_SIGNAL_TARGET_GONE:{error.errno}", "NOT_OBSERVED"
        return False, f"PIDFD_SIGTERM_FAILED:{error.errno}", "NOT_OBSERVED"
    after = _read_proc_identity(proc_root, handle.identity.pid)
    if after is None:
        post_state = "EXACT_CHILD_EXITED_OR_PROC_ENTRY_GONE_AFTER_SIGTERM"
    elif after == handle.identity and _child_is_exact(after, runner_pid, contract):
        post_state = "SAME_EXACT_CHILD_STILL_OBSERVED_IMMEDIATELY_AFTER_SIGTERM"
    else:
        post_state = "PID_IDENTITY_CHANGED_AFTER_PIDFD_SIGTERM"
    return True, "SIGTERM_SENT_VIA_PIDFD_TO_EXACT_VALIDATED_HFNET_CHILD", post_state


def monitor_runner(
    process: Any,
    contract: CaseContract,
    *,
    proc_root: Path = Path("/proc"),
    grace_seconds: float = SIGNATURE_GRACE_SECONDS,
    poll_seconds: float = POLL_SECONDS,
    monotonic: Callable[[], float] = time.monotonic,
    sleeper: Callable[[float], None] = time.sleep,
    discover: Callable[..., ChildHandle | None] = discover_exact_child,
    signature_parser: Callable[[Path, Path], dict[str, object]] = parse_zero_kf_save_hang_signature,
    signal_sender: Callable[..., tuple[bool, str, str]] = send_sigterm_to_exact_child,
    close_fd: Callable[[int], None] = os.close,
) -> MonitorOutcome:
    """Wait for the runner; only the continuously confirmed signature can signal."""

    handle: ChildHandle | None = None
    child_discovered_at: str | None = None
    signature_since: float | None = None
    signature_first_at: str | None = None
    last_signature: Mapping[str, object] | None = None
    signal_attempted = False
    sigterm_sent = False
    sigterm_at: str | None = None
    delivery: str | None = None
    post_state: str | None = None
    errors: list[str] = []
    runner_returncode: int | None = None
    runner_reaped = False
    try:
        while True:
            runner_returncode = process.poll()
            if runner_returncode is not None:
                try:
                    runner_returncode = process.wait(timeout=0)
                    runner_reaped = True
                except (OSError, subprocess.SubprocessError) as error:
                    errors.append(
                        f"RUNNER_REAP_FAILED:{type(error).__name__}:{error}"
                    )
                break
            if handle is None:
                try:
                    handle = discover(proc_root, process.pid, contract)
                except (OSError, WatchdogContractError) as error:
                    message = f"CHILD_DISCOVERY_ERROR:{type(error).__name__}:{error}"
                    if message not in errors:
                        errors.append(message)
                if handle is not None:
                    child_discovered_at = now_utc()

            try:
                observed_signature = signature_parser(contract.stdout_log, contract.trajectory)
            except (OSError, WatchdogContractError) as error:
                observed_signature = {"confirmed": False}
                message = f"SIGNATURE_READ_ERROR:{type(error).__name__}:{error}"
                if message not in errors:
                    errors.append(message)
            current = monotonic()
            if observed_signature.get("confirmed") is True and not signal_attempted:
                last_signature = dict(observed_signature)
                if signature_since is None:
                    signature_since = current
                    signature_first_at = now_utc()
                elif current - signature_since >= grace_seconds and handle is not None:
                    signal_attempted = True
                    sent, delivery, post_state = signal_sender(
                        handle,
                        process.pid,
                        contract,
                        proc_root=proc_root,
                    )
                    if sent:
                        sigterm_sent = True
                        sigterm_at = now_utc()
                    elif delivery not in errors:
                        errors.append(delivery)
            elif not signal_attempted:
                signature_since = None
                signature_first_at = None
                last_signature = None
            sleeper(poll_seconds)
    finally:
        if handle is not None:
            try:
                close_fd(handle.pidfd)
            except OSError as error:
                errors.append(f"PIDFD_CLOSE_FAILED:{error.errno}")
    return MonitorOutcome(
        runner_returncode=runner_returncode,
        runner_reaped=runner_reaped,
        child=handle.identity if handle is not None else None,
        child_discovered_at_utc=child_discovered_at,
        signature_first_observed_at_utc=signature_first_at,
        signature_evidence=last_signature,
        signal_attempted=signal_attempted,
        sigterm_sent=sigterm_sent,
        sigterm_sent_at_utc=sigterm_at,
        signal_delivery=delivery,
        post_signal_identity_state=post_state,
        runner_popen_invocations=1,
        monitoring_errors=errors,
    )


def build_receipt(
    contract: CaseContract,
    outcome: MonitorOutcome,
    *,
    started_at_utc: str,
    token_pipe_delivery_error: str | None,
    supervisor_pre: Mapping[str, object],
) -> dict[str, object]:
    monitoring_errors = list(outcome.monitoring_errors)
    if token_pipe_delivery_error is not None:
        monitoring_errors.append(token_pipe_delivery_error)
    if not outcome.runner_reaped:
        monitoring_errors.append("RUNNER_NOT_REAPED")
    if monitoring_errors:
        status = "WATCHDOG_SUPERVISION_ERROR_FAIL_CLOSED"
    elif outcome.sigterm_sent:
        status = "SIGTERM_SENT_FOR_CONFIRMED_ZERO_KF_SAVE_HANG"
    else:
        status = "PASSIVE_RUNNER_EXIT_WITHOUT_WATCHDOG_SIGNAL"
    child = asdict(outcome.child) if outcome.child is not None else None
    if child is not None:
        child["argv"] = list(child["argv"])
    return {
        "schema_version": RECEIPT_SCHEMA,
        "status": status,
        "case_id": contract.case_id,
        "started_at_utc": started_at_utc,
        "ended_at_utc": now_utc(),
        "fixed_signature_grace_seconds": SIGNATURE_GRACE_SECONDS,
        "signature_contract": {
            "ordered_shutdown_before_saving": True,
            "complete_reported_atlas_map_id_set_required": True,
            "every_reported_atlas_map_zero_keyframes_required": True,
            "trajectory_must_remain_absent": str(contract.trajectory),
            "end_of_saving_must_remain_absent": True,
            "continuous_for_fixed_grace": True,
        },
        "execution": {
            "runner_entry": str(RUNNER),
            "runner_action": "run",
            "case_spec": str(contract.case_spec),
            "authorization_transport": "ANONYMOUS_PIPE_TO_IN_MEMORY_RUNPY_ARGV",
            "authorization_token_in_os_argv": False,
            "authorization_token_in_environment": False,
            "authorization_token_serialized_in_receipt": False,
            "runner_popen_invocations": outcome.runner_popen_invocations,
            "hfnet_popen_authority_remains_with_frozen_runner": True,
            "retry_performed": False,
            "retry_permitted": False,
            "runner_returncode": outcome.runner_returncode,
            "runner_reaped": outcome.runner_reaped,
        },
        "watchdog_action": {
            "sigterm_sent": outcome.sigterm_sent,
            "sigterm_sent_at_utc": outcome.sigterm_sent_at_utc,
            "signal_attempt_count": 1 if outcome.signal_attempted else 0,
            "signal_count": 1 if outcome.sigterm_sent else 0,
            "signal": "SIGTERM" if outcome.sigterm_sent else None,
            "signal_scope": "PIDFD_EXACT_CHILD_ONLY" if outcome.sigterm_sent else None,
            "process_group_signaled": False,
            "sigkill_sent": False,
            "other_process_signaled": False,
            "signal_delivery": outcome.signal_delivery,
            "post_signal_identity_state": outcome.post_signal_identity_state,
        },
        "observations": {
            "child_discovered_at_utc": outcome.child_discovered_at_utc,
            "exact_hfnet_child": child,
            "signature_first_observed_at_utc": outcome.signature_first_observed_at_utc,
            "signature_evidence": outcome.signature_evidence,
            "monitoring_errors": monitoring_errors,
        },
        "pins": {
            "supervisor_pre": dict(supervisor_pre),
            "supervisor_post": safe_identity(SUPERVISOR),
            "frozen_runner": identity(RUNNER),
            "roster_pointer": identity(PUBLICATION_POINTER),
            "accuracy_prefreeze_seal": identity(PREFREEZE_SEAL),
            "case_spec": identity(contract.case_spec),
            "prepared_manifest": identity(contract.prepared_manifest),
            "hfnet_binary": identity(Path(contract.expected_hfnet_binary_identity["path"])),
            "stdout_log_at_receipt": safe_identity(contract.stdout_log),
            "trajectory_at_receipt": safe_identity(contract.trajectory),
            "runner_result_at_receipt": safe_identity(contract.run_result),
        },
        "terminal_contract": {
            "receipt_path": str(contract.receipt),
            "receipt_outside_attempt_directory": True,
            "receipt_publication": "TEMP_FSYNC_HARDLINK_NOREPLACE_DIRECTORY_FSYNC",
            "watchdog_retry_after_receipt": False,
            "watchdog_never_fabricates_or_edits_runner_outputs": True,
        },
    }


def supervise(case_spec: Path, token: str) -> tuple[dict[str, object], int]:
    contract = load_case_contract(case_spec)
    if not hmac.compare_digest(token, contract.authorization_token):
        raise WatchdogContractError("AUTHORIZATION_TOKEN_MISMATCH")
    supervisor_pre = identity(SUPERVISOR)
    started_at = now_utc()
    process, delivery_error = launch_runner_once(case_spec, token)
    # Drop the caller-supplied token reference before the long-running monitor.
    token = ""
    outcome = monitor_runner(process, contract)
    receipt = build_receipt(
        contract,
        outcome,
        started_at_utc=started_at,
        token_pipe_delivery_error=delivery_error,
        supervisor_pre=supervisor_pre,
    )
    publish_exclusive(contract.receipt, canonical_json(receipt))
    effective_returncode = (
        2
        if receipt["status"] == "WATCHDOG_SUPERVISION_ERROR_FAIL_CLOSED"
        else int(outcome.runner_returncode if outcome.runner_returncode is not None else 2)
    )
    return receipt, effective_returncode


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case-spec", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        # Contract checks happen before the secret is requested or a child starts.
        contract = load_case_contract(args.case_spec)
        token = read_authorization_token()
        if not hmac.compare_digest(token, contract.authorization_token):
            raise WatchdogContractError("AUTHORIZATION_TOKEN_MISMATCH")
        receipt, runner_returncode = supervise(args.case_spec, token)
        print(json.dumps(receipt, indent=2, sort_keys=True, ensure_ascii=False))
        return runner_returncode
    except (OSError, WatchdogContractError, subprocess.SubprocessError) as error:
        print(f"WATCHDOG_REFUSED:{type(error).__name__}:{error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
