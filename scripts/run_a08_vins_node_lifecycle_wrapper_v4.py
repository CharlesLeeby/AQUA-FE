#!/usr/bin/python3.8
"""Bounded lifecycle wrapper for the identity-pinned A08 VINS process.

The frozen recovered-July shell backgrounds ``VINS_NODE_BIN`` and later sends
SIGTERM followed by an unbounded ``wait``.  The real VINS binary masks SIGTERM
in the observed environment.  This wrapper remains signal-responsive, starts
the exact real binary once, and on the overlay's TERM request performs bounded
SIGINT -> SIGTERM -> SIGKILL escalation followed by an explicit reap.

Importing this module is inert.  It never starts ROS, VINS, or another process.
"""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import signal
import stat
import subprocess
import sys
import time
from typing import Any, Mapping, Optional, Sequence


SCHEMA_START = "aqua-fe-a08-vins-lifecycle-wrapper-start-v4"
SCHEMA_TERMINAL = "aqua-fe-a08-vins-lifecycle-wrapper-terminal-v4"
SIGINT_GRACE_SECONDS = 1.0
SIGTERM_GRACE_SECONDS = 0.5
SIGKILL_REAP_TIMEOUT_SECONDS = 2.0
POLL_SECONDS = 0.05
ALLOWED_ITEMS = {"KLT_R03", "KLT_R04", "KLT_R05"}

SCIENTIFIC_ENV_KEYS = (
    "AQUALOC_BODY_T_CAM0_MODE",
    "VINS_MULTIPLE_THREAD",
    "VINS_TD",
    "VINS_ESTIMATE_TD",
    "VINS_MAX_SOLVER_TIME",
    "VINS_MAX_NUM_ITERATIONS",
    "OMP_NUM_THREADS",
    "OPENBLAS_NUM_THREADS",
    "MKL_NUM_THREADS",
    "NUMEXPR_NUM_THREADS",
    "ROS_MASTER_URI",
    "ROS_HOSTNAME",
)


class LifecycleError(RuntimeError):
    pass


def require(condition: bool, code: str) -> None:
    if not condition:
        raise LifecycleError(code)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def compact_sha256(value: Any) -> str:
    raw = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def identity(path: Path, *, require_canonical: bool = True) -> dict[str, Any]:
    path = Path(path).absolute()
    require(path.exists() and not path.is_symlink(), f"IDENTITY_KIND:{path}")
    observed = path.lstat()
    require(stat.S_ISREG(observed.st_mode), f"IDENTITY_NOT_REGULAR:{path}")
    if require_canonical:
        require(path.resolve(strict=True) == path, f"IDENTITY_NOT_CANONICAL:{path}")
    digest = hashlib.sha256()
    with path.open("rb", buffering=0) as stream:
        while True:
            block = stream.read(8 * 1024 * 1024)
            if not block:
                break
            digest.update(block)
    return {
        "path": str(path),
        "size_bytes": observed.st_size,
        "sha256": digest.hexdigest(),
    }


def atomic_publish(path: Path, value: Mapping[str, Any]) -> dict[str, Any]:
    path = Path(path).absolute()
    require(path.parent.is_dir() and not path.parent.is_symlink(),
            f"MANIFEST_PARENT:{path.parent}")
    require(not path.exists() and not path.is_symlink(), f"MANIFEST_EXISTS:{path}")
    data = (json.dumps(value, indent=2, sort_keys=True) + "\n").encode("utf-8")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_CLOEXEC", 0)
    descriptor = os.open(str(path), flags, 0o444)
    try:
        view = memoryview(data)
        while view:
            written = os.write(descriptor, view)
            if written <= 0:
                raise LifecycleError("MANIFEST_WRITE_NO_PROGRESS")
            view = view[written:]
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    directory = os.open(str(path.parent), os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)
    return identity(path)


def process_start_ticks(pid: int) -> int:
    raw = Path(f"/proc/{pid}/stat").read_text(encoding="ascii")
    marker = raw.rfind(") ")
    require(marker > 0, "PROC_STAT_LAYOUT")
    fields_after_comm = raw[marker + 2:].split()
    require(len(fields_after_comm) >= 20, "PROC_STAT_FIELDS")
    # fields_after_comm[0] is field 3 (state); index 19 is field 22.
    return int(fields_after_comm[19])


def wait_bounded(child: subprocess.Popen[bytes], seconds: float) -> Optional[int]:
    deadline = time.monotonic() + seconds
    while True:
        code = child.poll()
        if code is not None:
            return code
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return None
        try:
            return child.wait(timeout=min(POLL_SECONDS, remaining))
        except subprocess.TimeoutExpired:
            continue


def selected_child_environment(environment: Mapping[str, str]) -> dict[str, str]:
    return {key: environment[key] for key in SCIENTIFIC_ENV_KEYS if key in environment}


def blocked_signal_numbers() -> list[int]:
    """Return the current thread mask without changing it."""
    current = signal.pthread_sigmask(signal.SIG_BLOCK, set())
    return sorted(int(value) for value in current)


def validate_contract(argv: Sequence[str]) -> dict[str, Any]:
    environment = os.environ
    require(environment.get("A08_VINS_LIFECYCLE_WRAPPER_V4") == "1",
            "WRAPPER_AUTHORIZATION")
    item_id = environment.get("A08_ITEM_ID", "")
    require(item_id in ALLOWED_ITEMS, "WRAPPER_ITEM")
    require(len(argv) == 1, "REAL_VINS_ARG_COUNT")

    output = Path(environment["A08_ITEM_OUTPUT_DIR"]).absolute()
    workspace = Path(environment["A08_WORKSPACE_LINK"]).absolute()
    require(output.is_dir() and not output.is_symlink(), "OUTPUT_KIND")
    require(workspace.is_symlink() and workspace.resolve(strict=True) == output,
            "WORKSPACE_BINDING")

    wrapper = Path(environment["A08_VINS_LIFECYCLE_WRAPPER_PATH"]).absolute()
    require(wrapper == Path(__file__).absolute(), "WRAPPER_PATH")
    wrapper_identity = identity(wrapper)
    require(
        wrapper_identity["size_bytes"]
        == int(environment["A08_VINS_LIFECYCLE_WRAPPER_SIZE_BYTES"])
        and wrapper_identity["sha256"]
        == environment["A08_VINS_LIFECYCLE_WRAPPER_SHA256"],
        "WRAPPER_IDENTITY",
    )

    real = Path(environment["A08_REAL_VINS_NODE_BIN"]).absolute()
    real_identity = identity(real)
    require(os.access(real, os.X_OK), "REAL_VINS_NOT_EXECUTABLE")
    require(
        real_identity["size_bytes"] == int(environment["A08_REAL_VINS_SIZE_BYTES"])
        and real_identity["sha256"] == environment["A08_REAL_VINS_SHA256"],
        "REAL_VINS_IDENTITY",
    )

    invoked_config = Path(argv[0]).absolute()
    expected_config = workspace / "vins_aqualoc_archaeo_external.yaml"
    require(invoked_config == expected_config, "REAL_VINS_CONFIG_ARGUMENT")
    canonical_config = invoked_config.resolve(strict=True)
    require(canonical_config == output / expected_config.name, "REAL_VINS_CONFIG_BINDING")
    config_identity = identity(canonical_config)

    start_manifest = Path(environment["A08_VINS_LIFECYCLE_START_MANIFEST"]).absolute()
    terminal_manifest = Path(
        environment["A08_VINS_LIFECYCLE_TERMINAL_MANIFEST"]
    ).absolute()
    require(start_manifest == output / "vins_lifecycle_start_manifest_v4.json",
            "START_MANIFEST_PATH")
    require(terminal_manifest == output / "vins_lifecycle_terminal_manifest_v4.json",
            "TERMINAL_MANIFEST_PATH")
    require(not start_manifest.exists() and not start_manifest.is_symlink(),
            "START_MANIFEST_PREEXISTING")
    require(not terminal_manifest.exists() and not terminal_manifest.is_symlink(),
            "TERMINAL_MANIFEST_PREEXISTING")
    return {
        "item_id": item_id,
        "output": output,
        "workspace": workspace,
        "wrapper_identity": wrapper_identity,
        "real": real,
        "real_identity": real_identity,
        "invoked_config": invoked_config,
        "config_identity": config_identity,
        "start_manifest": start_manifest,
        "terminal_manifest": terminal_manifest,
    }


def lifecycle_policy() -> dict[str, Any]:
    return {
        "overlay_signal_received_by_wrapper": "SIGTERM",
        "first_real_child_signal": "SIGINT",
        "sigint_grace_seconds": SIGINT_GRACE_SECONDS,
        "second_real_child_signal": "SIGTERM",
        "sigterm_grace_seconds": SIGTERM_GRACE_SECONDS,
        "final_real_child_signal": "SIGKILL",
        "sigkill_reap_timeout_seconds": SIGKILL_REAP_TIMEOUT_SECONDS,
        "maximum_shutdown_seconds": (
            SIGINT_GRACE_SECONDS
            + SIGTERM_GRACE_SECONDS
            + SIGKILL_REAP_TIMEOUT_SECONDS
        ),
        "real_child_must_be_reaped_before_wrapper_exit": True,
        "automatic_restart_count": 0,
    }


def controlled_shutdown(
    child: subprocess.Popen[bytes], start_identity: Mapping[str, Any],
    contract: Mapping[str, Any], received_signals: Sequence[int],
) -> int:
    stages: list[dict[str, Any]] = []
    for signum, name, grace in (
        (signal.SIGINT, "SIGINT", SIGINT_GRACE_SECONDS),
        (signal.SIGTERM, "SIGTERM", SIGTERM_GRACE_SECONDS),
    ):
        if child.poll() is not None:
            break
        child.send_signal(signum)
        code = wait_bounded(child, grace)
        stages.append({
            "signal": name,
            "sent": True,
            "grace_seconds": grace,
            "child_return_code_after_grace": code,
        })
    if child.poll() is None:
        child.kill()
        code = wait_bounded(child, SIGKILL_REAP_TIMEOUT_SECONDS)
        stages.append({
            "signal": "SIGKILL",
            "sent": True,
            "reap_timeout_seconds": SIGKILL_REAP_TIMEOUT_SECONDS,
            "child_return_code_after_wait": code,
        })
    final_code = child.poll()
    child_reaped = final_code is not None
    if stages and final_code is not None:
        final_key = (
            "child_return_code_after_wait"
            if stages[-1]["signal"] == "SIGKILL"
            else "child_return_code_after_grace"
        )
        if stages[-1].get(final_key) is None:
            stages[-1][final_key] = final_code
    controlled_child = bool(stages)
    terminal = {
        "schema_version": SCHEMA_TERMINAL,
        "status": (
            "PASS_OVERLAY_TERM_RECEIVED_REAL_VINS_REAPED"
            if child_reaped and controlled_child
            else (
                "FAIL_REAL_VINS_EXITED_BEFORE_CONTROL_SIGNAL_REACHED_CHILD_NO_RESTART"
                if child_reaped else "FAIL_REAL_VINS_NOT_REAPED_WITHIN_BOUND"
            )
        ),
        "item_id": contract["item_id"],
        "ended_at_utc": utc_now(),
        "wrapper_pid": os.getpid(),
        "real_child_pid": child.pid,
        "received_wrapper_signals": list(received_signals),
        "expected_overlay_term_received": signal.SIGTERM in received_signals,
        "shutdown_stages": stages,
        "real_child_return_code": final_code,
        "real_child_reaped": child_reaped,
        "start_manifest": dict(start_identity),
        "real_vins_binary": contract["real_identity"],
        "config": contract["config_identity"],
        "lifecycle_policy": lifecycle_policy(),
        "wrapper_exit_code": 0 if child_reaped and controlled_child else 70,
    }
    terminal["contract_sha256"] = compact_sha256(terminal)
    atomic_publish(contract["terminal_manifest"], terminal)
    return 0 if child_reaped and controlled_child else 70


def publish_natural_exit(
    child: subprocess.Popen[bytes], start_identity: Mapping[str, Any],
    contract: Mapping[str, Any], received_signals: Sequence[int], code: int,
) -> int:
    terminal = {
        "schema_version": SCHEMA_TERMINAL,
        "status": "FAILED_REAL_VINS_EXITED_BEFORE_OVERLAY_TERM_NO_RESTART",
        "item_id": contract["item_id"],
        "ended_at_utc": utc_now(),
        "wrapper_pid": os.getpid(),
        "real_child_pid": child.pid,
        "received_wrapper_signals": list(received_signals),
        "expected_overlay_term_received": False,
        "shutdown_stages": [],
        "real_child_return_code": code,
        "real_child_reaped": True,
        "start_manifest": dict(start_identity),
        "real_vins_binary": contract["real_identity"],
        "config": contract["config_identity"],
        "lifecycle_policy": lifecycle_policy(),
        "wrapper_exit_code": 70,
    }
    terminal["contract_sha256"] = compact_sha256(terminal)
    atomic_publish(contract["terminal_manifest"], terminal)
    return 70


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    contract = validate_contract(args)
    received_signals: list[int] = []

    def record_signal(signum: int, _frame: Any) -> None:
        received_signals.append(signum)

    blocked_before = blocked_signal_numbers()
    signal.pthread_sigmask(
        signal.SIG_UNBLOCK, {signal.SIGHUP, signal.SIGTERM, signal.SIGINT}
    )
    blocked_after = blocked_signal_numbers()
    require(
        not ({int(signal.SIGHUP), int(signal.SIGINT), int(signal.SIGTERM)}
             & set(blocked_after)),
        "WRAPPER_CONTROL_SIGNALS_STILL_BLOCKED",
    )
    signal.signal(signal.SIGTERM, record_signal)
    signal.signal(signal.SIGINT, record_signal)

    child_environment = dict(os.environ)
    child_environment["VINS_NODE_BIN"] = str(contract["real"])
    child: Optional[subprocess.Popen[bytes]] = None
    start_identity: Optional[dict[str, Any]] = None
    try:
        child = subprocess.Popen(
            [str(contract["real"]), *args],
            env=child_environment,
            close_fds=True,
        )
        start = {
            "schema_version": SCHEMA_START,
            "status": "PASS_REAL_VINS_STARTED_ONCE_BEFORE_REPLAY",
            "item_id": contract["item_id"],
            "started_at_utc": utc_now(),
            "wrapper_pid": os.getpid(),
            "wrapper_parent_pid": os.getppid(),
            "wrapper_process_group": os.getpgrp(),
            "wrapper_session": os.getsid(0),
            "wrapper_blocked_signals_before_unblock": blocked_before,
            "wrapper_blocked_signals_after_unblock": blocked_after,
            "wrapper": contract["wrapper_identity"],
            "real_child_pid": child.pid,
            "real_child_start_ticks": process_start_ticks(child.pid),
            "real_child_process_group": os.getpgid(child.pid),
            "real_child_session": os.getsid(child.pid),
            "real_vins_binary": contract["real_identity"],
            "config": contract["config_identity"],
            "argv": [str(contract["real"]), *args],
            "working_directory": os.getcwd(),
            "scientific_environment": selected_child_environment(child_environment),
            "scientific_environment_sha256": compact_sha256(
                selected_child_environment(child_environment)
            ),
            "lifecycle_policy": lifecycle_policy(),
            "real_child_popen_count": 1,
            "automatic_restart_count": 0,
        }
        start["contract_sha256"] = compact_sha256(start)
        start_identity = atomic_publish(contract["start_manifest"], start)
        while True:
            if received_signals:
                return controlled_shutdown(child, start_identity, contract, received_signals)
            code = child.poll()
            if code is not None:
                return publish_natural_exit(
                    child, start_identity, contract, received_signals, code
                )
            time.sleep(POLL_SECONDS)
    except BaseException:
        if child is not None and child.poll() is None:
            child.kill()
            try:
                child.wait(timeout=SIGKILL_REAP_TIMEOUT_SECONDS)
            except subprocess.TimeoutExpired:
                pass
        raise


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (KeyError, OSError, ValueError, LifecycleError) as error:
        print(f"A08_VINS_LIFECYCLE_V4_ERROR:{type(error).__name__}:{error}", file=sys.stderr)
        raise SystemExit(70)
