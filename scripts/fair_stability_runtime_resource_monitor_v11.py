#!/usr/bin/python3
"""Continuous resource-exclusivity evidence for fair-stability v11 runs.

The runner must construct :class:`RuntimeResourceMonitor` immediately after
its single supervised ``Popen``.  Monitoring is observational: an intrusion is
recorded and invalidates the attempt, but never terminates the estimator.
Lifecycle methods keep sampling active through normal wait/timeout cleanup and
until the supervised process group and all known owned descendants are empty.
The fresh ownership scan that closes coverage is itself the final proc sample:
it starts only after ordinary reservations drain and is published before the
coverage-end clock is read.
"""

from __future__ import annotations

import csv
from datetime import datetime, timezone
import errno
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import signal
import socket
import subprocess
import threading
import time
from typing import Any, Callable, Iterable, Mapping, Sequence


SCHEMA_VERSION = "aqua-fe-fair-stability-runtime-resource-monitor-v11"
EXPERIMENT_ID = "fair-stability-positive-roster-openloop-runtimeexcl-v11"
PROC_TARGET_INTERVAL_SECONDS = 0.20
PROC_MAX_START_GAP_SECONDS = 0.25
ORDINARY_PROC_PROBE_ROLE = "ordinary"
CLOSING_PROC_PROBE_ROLE = "coverage_close_ownership_recheck"
GPU_TARGET_INTERVAL_SECONDS = 0.75
GPU_MAX_START_GAP_SECONDS = 1.00
GPU_QUERY_TIMEOUT_SECONDS = 0.65
MIN_EXPERIMENT_FREE_BYTES = 5 * 1024**3
MIN_WORKSPACE_FREE_BYTES = 512 * 1024**2
PRESTART_RESOURCE_GATE_SCHEMA = (
    "aqua-fe-fair-stability-prestart-resource-gate-v11"
)
PRESTART_RESOURCE_GATE_FIELDS = frozenset(
    {
        "schema_version",
        "experiment_id",
        "checked_at_utc",
        "probe_started_monotonic_ns",
        "probe_finished_monotonic_ns",
        "ready",
        "errors",
        "proc_probe_errors",
        "conflicting_processes",
        "gpu_query",
        "compute_applications",
        "competing_compute_applications",
        "external_gpu_todesk_exemption",
        "port",
        "port_available",
        "experiment_disk_probe",
        "experiment_free_bytes",
        "workspace_disk_probe",
        "workspace_free_bytes",
        "runtime_claim_allowed",
    }
)
_EXPECTED_PORT_UNSET = object()

FORBIDDEN_PROCESS_NAMES = frozenset(
    {
        "mono_inertial_euroc_headless_v3",
        "mono_inertial_euroc",
        "stereo_inertial_euroc",
        "vins_node",
        "roscore",
        "rosmaster",
        "roslaunch",
        "rosbag",
        "rosrun",
        "rosparam",
        "cc1",
        "cc1plus",
        "cc",
        "c++",
        "gcc",
        "g++",
        "clang",
        "clang++",
        "clang-cl",
        "nvcc",
        "ld",
        "collect2",
        "cmake",
        "make",
        "ninja",
        "catkin",
        "catkin_make",
        "colcon",
    }
)
FORBIDDEN_COMMAND_FRAGMENTS = (
    "uw_frontend.ros.export_vins_features",
    "export_vins_features.py",
    "catkin build",
    "catkin_make",
    "catkin build_isolated",
    "colcon build",
    "run_mimir_selected_ours_vins.sh",
    "run_mimir_selected_klt_vins.sh",
    "run_frozen_positive_replay_regression.sh",
    "run_learned_seedchain_eval.sh",
    "run_existing_featurebag_vins_replay_only",
)

# Compiler drivers are commonly installed with a target-triple prefix and/or
# a version suffix (for example ``x86_64-linux-gnu-g++-12``).  Exact basename
# matching alone would miss those processes during the exclusivity window.
FORBIDDEN_COMPILER_NAME = re.compile(
    r"^(?:(?:[a-z0-9_+.]+-)*)(?:cc|c\+\+|gcc|g\+\+|clang|clang\+\+|clang-cl|nvcc)"
    r"(?:-[0-9]+(?:\.[0-9]+)*)?$"
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def _canonical_json(value: object) -> bytes:
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


EMPTY_CMDLINE_SHA256 = hashlib.sha256(b"").hexdigest()
WATCHDOG_GROUP_PROOF_KEYS = frozenset(
    {
        "observed_at_utc",
        "observed_monotonic_ns",
        "proven",
        "errors",
        "leader_pid",
        "leader_start_ticks",
        "expected_executable",
        "expected_argv",
        "pgid",
        "session",
        "members",
    }
)
WATCHDOG_GROUP_MEMBER_KEYS = frozenset(
    {
        "pid",
        "start_ticks",
        "pgid",
        "session",
        "state",
        "executable",
        "cmdline_sha256",
    }
)


def _watchdog_stable_member_projection(
    members: object,
) -> list[dict[str, object]] | None:
    if not isinstance(members, list):
        return None
    projected: list[dict[str, object]] = []
    for member in members:
        if not isinstance(member, Mapping):
            return None
        projected.append(
            {
                key: member.get(key)
                for key in WATCHDOG_GROUP_MEMBER_KEYS
                if key != "state"
            }
        )
    return projected


def watchdog_exact_teardown_candidate(proof: object) -> bool:
    """Recognize the sole frozen leader in the empty-identity teardown race.

    Linux ``stat``, ``exe``, and ``cmdline`` are separate reads.  The sampled
    state can therefore still be ``R`` (or another recorded state) after the
    address-space identity has disappeared.  State is evidence only: it never
    authorizes this candidate.  The candidate requires the unique leader's
    complete frozen identity, an empty executable/cmdline, and *only* the
    expected empty-identity mismatch marker.  It is neither a live proof nor
    authority to signal; the caller must still reap the same ``Popen`` child.
    """

    if (
        not isinstance(proof, Mapping)
        or set(proof) != WATCHDOG_GROUP_PROOF_KEYS
        or proof.get("proven") is not False
    ):
        return False
    leader_pid = proof.get("leader_pid")
    leader_start_ticks = proof.get("leader_start_ticks")
    members = proof.get("members")
    if (
        type(leader_pid) is not int
        or int(leader_pid) <= 0
        or type(leader_start_ticks) is not int
        or int(leader_start_ticks) <= 0
        or proof.get("pgid") != leader_pid
        or proof.get("session") != leader_pid
        or not isinstance(members, list)
    ):
        return False
    if (
        proof.get("errors")
        != ["EXACT_GROUP_LEADER_IDENTITY_OR_ARGV_MISMATCH"]
        or len(members) != 1
        or not isinstance(members[0], Mapping)
        or set(members[0]) != WATCHDOG_GROUP_MEMBER_KEYS
    ):
        return False
    member = members[0]
    return bool(
        member.get("pid") == leader_pid
        and member.get("start_ticks") == leader_start_ticks
        and member.get("pgid") == leader_pid
        and member.get("session") == leader_pid
        and isinstance(member.get("state"), str)
        and bool(member.get("state"))
        and member.get("executable") is None
        and member.get("cmdline_sha256") == EMPTY_CMDLINE_SHA256
    )


def watchdog_clean_disappearance_candidate(proof: object) -> bool:
    """Recognize the pre-existing clean exact-group disappearance shape."""

    if (
        not isinstance(proof, Mapping)
        or set(proof) != WATCHDOG_GROUP_PROOF_KEYS
        or proof.get("proven") is not False
        or proof.get("errors")
        not in (
            ["EXACT_GROUP_LEADER_COUNT:0"],
            ["EXACT_GROUP_LEADER_DISAPPEARED_DURING_RECHECK"],
        )
        or proof.get("members") != []
    ):
        return False
    leader_pid = proof.get("leader_pid")
    leader_start_ticks = proof.get("leader_start_ticks")
    return bool(
        type(leader_pid) is int
        and int(leader_pid) > 0
        and type(leader_start_ticks) is int
        and int(leader_start_ticks) > 0
        and proof.get("pgid") == leader_pid
        and proof.get("session") == leader_pid
    )


def watchdog_terminal_transition_candidate(proof: object) -> bool:
    """Return a state-only candidate; exact same-child reap remains mandatory."""

    return bool(
        watchdog_exact_teardown_candidate(proof)
        or watchdog_clean_disappearance_candidate(proof)
    )


def _write_exclusive(path: Path, value: object, mode: int = 0o444) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            descriptor = -1
            stream.write(_canonical_json(value))
            stream.flush()
            os.fsync(stream.fileno())
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def _parse_proc_stat(raw: str, expected_pid: int) -> dict[str, object]:
    close = raw.rfind(")")
    open_ = raw.find("(")
    if open_ <= 0 or close <= open_:
        raise ValueError("malformed /proc stat")
    if int(raw[:open_].strip()) != expected_pid:
        raise ValueError("pid mismatch in /proc stat")
    tail = raw[close + 1 :].split()
    if len(tail) < 20:
        raise ValueError("short /proc stat")
    return {
        "pid": expected_pid,
        "comm": raw[open_ + 1 : close],
        "state": tail[0],
        "ppid": int(tail[1]),
        "pgid": int(tail[2]),
        "session": int(tail[3]),
        "start_ticks": int(tail[19]),
    }


def _read_process_record(pid: int) -> tuple[dict[str, object] | None, list[str]]:
    root = Path("/proc") / str(pid)
    errors: list[str] = []
    try:
        before = _parse_proc_stat((root / "stat").read_text(), pid)
    except OSError as error:
        if error.errno in (errno.ENOENT, errno.ESRCH):
            return None, []
        return None, [f"PROC_STAT_READ_FAILED:{pid}:{error.errno}"]
    except (ValueError, IndexError) as error:
        return None, [f"PROC_STAT_PARSE_FAILED:{pid}:{type(error).__name__}"]

    executable: str | None
    try:
        executable = os.readlink(root / "exe")
    except OSError as error:
        executable = None
        if error.errno not in (errno.ENOENT, errno.ESRCH):
            errors.append(f"EXECUTABLE_UNREADABLE:{error.errno}")
    try:
        raw_cmdline = (root / "cmdline").read_bytes()
    except OSError as error:
        raw_cmdline = b""
        if error.errno not in (errno.ENOENT, errno.ESRCH):
            errors.append(f"CMDLINE_UNREADABLE:{error.errno}")
    tokens = [
        token.decode("utf-8", errors="replace")
        for token in raw_cmdline.split(b"\0")
        if token
    ]
    try:
        after = _parse_proc_stat((root / "stat").read_text(), pid)
    except OSError as error:
        if error.errno in (errno.ENOENT, errno.ESRCH):
            return None, []
        return None, [f"PROC_STAT_RECHECK_FAILED:{pid}:{error.errno}"]
    except (ValueError, IndexError) as error:
        return None, [f"PROC_STAT_RECHECK_PARSE_FAILED:{pid}:{type(error).__name__}"]
    if before["start_ticks"] != after["start_ticks"]:
        return None, [
            "PROC_IDENTITY_CHANGED_DURING_READ:"
            f"{pid}:{before['start_ticks']}:{after['start_ticks']}"
        ]
    record = dict(after)
    record.update(
        {
            "executable": executable,
            "cmdline": tokens,
            "command": " ".join(tokens),
            "cmdline_sha256": hashlib.sha256(raw_cmdline).hexdigest(),
            "read_errors": errors,
        }
    )
    return record, []


def _scan_processes() -> tuple[list[dict[str, object]], list[str]]:
    try:
        pids = sorted(
            int(entry.name) for entry in Path("/proc").iterdir() if entry.name.isdigit()
        )
    except OSError as error:
        return [], [f"PROC_ENUMERATION_FAILED:{error.errno}"]
    records: list[dict[str, object]] = []
    errors: list[str] = []
    for pid in pids:
        record, record_errors = _read_process_record(pid)
        errors.extend(record_errors)
        if record is not None:
            records.append(record)
    return records, errors


def _process_identity(record: Mapping[str, object]) -> tuple[int, int]:
    return int(record["pid"]), int(record["start_ticks"])


def _is_forbidden_process(record: Mapping[str, object]) -> bool:
    names = {
        str(record.get("comm") or "").lower(),
        Path(str(record.get("executable") or "")).name.lower(),
    }
    cmdline = record.get("cmdline")
    tokens: list[str] = []
    if isinstance(cmdline, Sequence) and not isinstance(cmdline, (str, bytes)):
        tokens = [str(token) for token in cmdline]
    elif isinstance(record.get("command"), str):
        # ``_offender_record`` intentionally stores the stable flattened
        # command rather than the raw argv vector.  This fallback keeps the
        # validator and producer classification aligned for ordinary paths.
        tokens = str(record["command"]).split()
    if tokens:
        names.add(Path(tokens[0]).name.lower())
        # A script name is executable identity only when it immediately
        # follows a recognised interpreter.  Scanning every argv token made
        # a harmless command such as ``sleep 1 vins_node`` look like an
        # estimator and could trigger an unnecessary replacement attempt.
        interpreter = Path(tokens[0]).name.lower()
        if interpreter in {
            "python", "python2", "python3", "python3.8",
            "bash", "dash", "sh", "zsh",
        } and len(tokens) > 1:
            names.add(Path(tokens[1]).name.lower())
    command = str(record.get("command") or "").lower()
    return (
        bool(names & FORBIDDEN_PROCESS_NAMES)
        or any(FORBIDDEN_COMPILER_NAME.fullmatch(name) for name in names)
        or any(
        fragment in command for fragment in FORBIDDEN_COMMAND_FRAGMENTS
        )
    )


def _offender_record(record: Mapping[str, object]) -> dict[str, object]:
    """Return the stable identity fields mandated by the addendum."""
    return {
        "pid": int(record["pid"]),
        "start_ticks": int(record["start_ticks"]),
        "ppid": int(record["ppid"]),
        "pgid": int(record["pgid"]),
        "executable": record.get("executable"),
        "comm": record.get("comm"),
        "command": record.get("command"),
        "cmdline_sha256": record.get("cmdline_sha256"),
        "read_errors": list(record.get("read_errors") or []),
    }


def _external_process_conflicts(
    records: Iterable[Mapping[str, object]],
    owned: set[tuple[int, int]],
    excluded_pids: set[int] | None = None,
) -> list[dict[str, object]]:
    excluded = excluded_pids or set()
    return [
        _offender_record(record)
        for record in records
        if int(record["pid"]) not in excluded
        and _process_identity(record) not in owned
        and _is_forbidden_process(record)
    ]


def _run_gpu_compute_query() -> dict[str, object]:
    argv = [
        "nvidia-smi",
        "--query-compute-apps=pid,process_name,used_memory",
        "--format=csv,noheader,nounits",
    ]
    try:
        result = subprocess.run(
            argv,
            check=False,
            capture_output=True,
            text=True,
            timeout=GPU_QUERY_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as error:
        stdout = error.stdout or ""
        stderr = error.stderr or ""
        if isinstance(stdout, bytes):
            stdout = stdout.decode("utf-8", errors="replace")
        if isinstance(stderr, bytes):
            stderr = stderr.decode("utf-8", errors="replace")
        return {
            "returncode": None,
            "stdout": stdout,
            "stderr": stderr,
            "error": "GPU_COMPUTE_QUERY_TIMEOUT",
        }
    except (OSError, subprocess.SubprocessError) as error:
        return {
            "returncode": None,
            "stdout": "",
            "stderr": "",
            "error": f"GPU_COMPUTE_QUERY_EXCEPTION:{type(error).__name__}:{error}",
        }
    return {
        "returncode": result.returncode,
        "stdout": result.stdout,
        "stderr": result.stderr,
        "error": None if result.returncode == 0 else f"GPU_COMPUTE_QUERY_RETURN_CODE:{result.returncode}",
    }


def _parse_gpu_applications(stdout: str) -> list[dict[str, object]]:
    applications: list[dict[str, object]] = []
    for row in csv.reader(stdout.splitlines()):
        if not row or not any(field.strip() for field in row):
            continue
        fields = [field.strip() for field in row]
        parse_errors: list[str] = []
        if len(fields) != 3:
            parse_errors.append(f"GPU_COMPUTE_ROW_FIELD_COUNT:{len(fields)}")
        pid: int | None = (
            int(fields[0]) if fields and fields[0].isdigit() and int(fields[0]) > 0 else None
        )
        if pid is None:
            parse_errors.append("GPU_COMPUTE_ROW_PID_INVALID")
        applications.append(
            {
                "pid": pid,
                "process_name": fields[1] if len(fields) > 1 else None,
                "used_memory_mib": fields[2] if len(fields) > 2 else None,
                "raw": ", ".join(fields),
                "parse_errors": parse_errors,
            }
        )
    return applications


def _external_gpu_applications(
    applications: Iterable[Mapping[str, object]],
    owned: set[tuple[int, int]],
) -> list[dict[str, object]]:
    return _classify_gpu_applications(applications, owned, owned)["external"]


def _classify_gpu_applications(
    applications: Iterable[Mapping[str, object]],
    active_owned: set[tuple[int, int]],
    known_owned: set[tuple[int, int]],
    owned_pgid: int | None = None,
) -> dict[str, list[dict[str, object]]]:
    """Classify GPU rows without inheriting ownership across PID reuse.

    NVIDIA may retain a just-exited compute PID for one query.  A missing
    ``/proc`` PID is accepted only when that numeric PID belongs to an identity
    already proved owned by this attempt.  If ``/proc`` exists, start ticks
    must match an exact known-owned identity; a reused PID is external.
    """
    known_by_pid: dict[int, list[int]] = {}
    for pid, start in known_owned:
        known_by_pid.setdefault(pid, []).append(start)
    external: list[dict[str, object]] = []
    stale_owned: list[dict[str, object]] = []
    current_owned: list[dict[str, object]] = []
    discovered_owned: list[dict[str, object]] = []
    # GPU observation can confirm an already-known exact identity, but can
    # never create ownership from numeric PID/PGID/PPID relationships. The
    # faster /proc monitor is the sole authority that grows ownership through
    # an exact live parent identity.
    _ = owned_pgid
    for source in applications:
        row = dict(source)
        pid = row.get("pid")
        proc: dict[str, object] | None = None
        proc_read_errors: list[str] = []
        if isinstance(pid, int):
            proc, proc_read_errors = _read_process_record(pid)
        if proc_read_errors:
            row["proc_identity_read_errors"] = proc_read_errors
        if proc is not None:
            row["process"] = _offender_record(proc)
            identity = _process_identity(proc)
            if identity in active_owned or identity in known_owned:
                row["classification"] = "CURRENT_EXACT_KNOWN_OWNED_GPU_PROCESS"
                current_owned.append(row)
                discovered_owned.append(
                    {"pid": identity[0], "start_ticks": identity[1]}
                )
                continue
            row["classification"] = "EXTERNAL_GPU_PROCESS_EXACT_IDENTITY_NOT_OWNED"
        elif (
            isinstance(pid, int)
            and pid in known_by_pid
            and not proc_read_errors
        ):
            row["classification"] = "STALE_OWNED_GPU_ROW_PROC_ABSENT"
            row["known_owned_start_ticks_for_pid"] = sorted(known_by_pid[pid])
            stale_owned.append(row)
            continue
        else:
            row["classification"] = "EXTERNAL_GPU_PROCESS_PROC_IDENTITY_UNPROVEN"
        # Deliberately no ToDesk or desktop-process exemption in v11.
        external.append(row)
    return {
        "external": external,
        "stale_owned": stale_owned,
        "current_owned": current_owned,
        "discovered_owned_identities": discovered_owned,
    }


def _existing_ancestor(path: Path) -> Path:
    candidate = path
    while not candidate.exists() and candidate != candidate.parent:
        candidate = candidate.parent
    return candidate


def resource_gate(
    port: int | None,
    experiment_root: Path,
    workspace_root: Path,
) -> dict[str, object]:
    """Run the strict v11 pre-start exclusivity gate.

    ``port`` is ``None`` for HFNet and the planned ROS master port for VINS.
    No GPU compute process, including ToDesk, is exempt.
    """
    started_ns = time.monotonic_ns()
    records, proc_errors = _scan_processes()
    conflicts = _external_process_conflicts(records, set(), {os.getpid()})
    gpu = _run_gpu_compute_query()
    applications = _parse_gpu_applications(str(gpu.get("stdout") or ""))
    competing = _external_gpu_applications(applications, set())
    errors: list[str] = []
    if proc_errors:
        errors.append("PROC_RESOURCE_GATE_PROBE_FAILED")
    if conflicts:
        errors.append("CONFLICTING_ESTIMATOR_EXPORTER_ROS_OR_COMPILER_PROCESS")
    if gpu.get("error"):
        errors.append("GPU_COMPUTE_QUERY_FAILED")
    elif any(row.get("parse_errors") for row in applications):
        errors.append("GPU_COMPUTE_QUERY_PARSE_FAILED")
    elif competing:
        errors.append("COMPETING_GPU_COMPUTE_APPLICATION")

    port_available: bool | None = None
    if port is not None:
        port_available = True
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            try:
                probe.bind(("127.0.0.1", int(port)))
            except OSError:
                port_available = False
                errors.append("ROS_PORT_UNAVAILABLE")

    experiment_probe = _existing_ancestor(Path(experiment_root))
    workspace_probe = _existing_ancestor(Path(workspace_root))
    experiment_free = shutil.disk_usage(experiment_probe).free
    workspace_free = shutil.disk_usage(workspace_probe).free
    if experiment_free < MIN_EXPERIMENT_FREE_BYTES:
        errors.append("EXPERIMENT_FREE_SPACE_BELOW_5_GIB")
    if workspace_free < MIN_WORKSPACE_FREE_BYTES:
        errors.append("WORKSPACE_FREE_SPACE_BELOW_512_MIB")
    ended_ns = time.monotonic_ns()
    return {
        "schema_version": PRESTART_RESOURCE_GATE_SCHEMA,
        "experiment_id": EXPERIMENT_ID,
        "checked_at_utc": _utc_now(),
        "probe_started_monotonic_ns": started_ns,
        "probe_finished_monotonic_ns": ended_ns,
        "ready": not errors,
        "errors": sorted(set(errors)),
        "proc_probe_errors": proc_errors,
        "conflicting_processes": conflicts,
        "gpu_query": gpu,
        "compute_applications": applications,
        "competing_compute_applications": competing,
        "external_gpu_todesk_exemption": False,
        "port": port,
        "port_available": port_available,
        "experiment_disk_probe": str(experiment_probe),
        "experiment_free_bytes": experiment_free,
        "workspace_disk_probe": str(workspace_probe),
        "workspace_free_bytes": workspace_free,
        "runtime_claim_allowed": False,
    }


def _strict_json_equal(left: object, right: object) -> bool:
    try:
        return json.dumps(
            left,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ) == json.dumps(
            right,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
    except (TypeError, ValueError):
        return False


def _valid_offender_record(value: object) -> bool:
    if not isinstance(value, Mapping) or set(value) != {
        "pid",
        "start_ticks",
        "ppid",
        "pgid",
        "executable",
        "comm",
        "command",
        "cmdline_sha256",
        "read_errors",
    }:
        return False
    return bool(
        type(value.get("pid")) is int
        and int(value["pid"]) > 0
        and type(value.get("start_ticks")) is int
        and int(value["start_ticks"]) > 0
        and type(value.get("ppid")) is int
        and int(value["ppid"]) >= 0
        and type(value.get("pgid")) is int
        and isinstance(value.get("executable"), (str, type(None)))
        and isinstance(value.get("comm"), (str, type(None)))
        and isinstance(value.get("command"), (str, type(None)))
        and isinstance(value.get("cmdline_sha256"), str)
        and re.fullmatch(r"[0-9a-f]{64}", str(value["cmdline_sha256"]))
        and isinstance(value.get("read_errors"), list)
        and all(isinstance(error, str) for error in value["read_errors"])
    )


def _valid_competing_gpu_partition(
    applications: object, competing: object
) -> bool:
    if not isinstance(applications, list) or not isinstance(competing, list):
        return False
    if len(applications) != len(competing):
        return False
    base_fields = {
        "pid",
        "process_name",
        "used_memory_mib",
        "raw",
        "parse_errors",
    }
    for application, row in zip(applications, competing):
        if not isinstance(application, Mapping) or not isinstance(row, Mapping):
            return False
        if not all(
            key in row and _strict_json_equal(row.get(key), application.get(key))
            for key in base_fields
        ):
            return False
        allowed = base_fields | {
            "classification",
            "process",
            "proc_identity_read_errors",
        }
        if not set(row).issubset(allowed):
            return False
        classification = row.get("classification")
        process = row.get("process")
        probe_errors = row.get("proc_identity_read_errors")
        if classification not in {
            "EXTERNAL_GPU_PROCESS_EXACT_IDENTITY_NOT_OWNED",
            "EXTERNAL_GPU_PROCESS_PROC_IDENTITY_UNPROVEN",
        }:
            return False
        if (
            classification == "EXTERNAL_GPU_PROCESS_EXACT_IDENTITY_NOT_OWNED"
            and (
                not _valid_offender_record(process)
                or not isinstance(process, Mapping)
                or process.get("pid") != application.get("pid")
            )
        ) or (
            classification == "EXTERNAL_GPU_PROCESS_PROC_IDENTITY_UNPROVEN"
            and process is not None
        ):
            return False
        if probe_errors is not None and (
            not isinstance(probe_errors, list)
            or not probe_errors
            or not all(isinstance(error, str) for error in probe_errors)
        ):
            return False
    return True


def prestart_resource_gate_contract_valid(
    value: object,
    *,
    expected_ready: bool | None = None,
    expected_port: object = _EXPECTED_PORT_UNSET,
) -> bool:
    """Validate the complete producer contract for ready and blocked gates."""

    if (
        not isinstance(value, Mapping)
        or set(value) != PRESTART_RESOURCE_GATE_FIELDS
        or value.get("schema_version") != PRESTART_RESOURCE_GATE_SCHEMA
        or value.get("experiment_id") != EXPERIMENT_ID
    ):
        return False
    checked_at = value.get("checked_at_utc")
    if not isinstance(checked_at, str) or not checked_at:
        return False
    try:
        checked = datetime.fromisoformat(checked_at.replace("Z", "+00:00"))
    except ValueError:
        return False
    started = value.get("probe_started_monotonic_ns")
    finished = value.get("probe_finished_monotonic_ns")
    ready = value.get("ready")
    errors = value.get("errors")
    proc_errors = value.get("proc_probe_errors")
    conflicts = value.get("conflicting_processes")
    gpu = value.get("gpu_query")
    applications = value.get("compute_applications")
    competing = value.get("competing_compute_applications")
    port = value.get("port")
    port_available = value.get("port_available")
    experiment_free = value.get("experiment_free_bytes")
    workspace_free = value.get("workspace_free_bytes")
    if (
        checked.tzinfo is None
        or checked.utcoffset() is None
        or checked.utcoffset().total_seconds() != 0
        or type(started) is not int
        or int(started) < 0
        or type(finished) is not int
        or int(finished) < int(started)
        or type(ready) is not bool
        or (expected_ready is not None and ready is not expected_ready)
        or not isinstance(errors, list)
        or errors != sorted(set(errors))
        or not all(isinstance(error, str) and error for error in errors)
        or not isinstance(proc_errors, list)
        or not all(isinstance(error, str) and error for error in proc_errors)
        or not isinstance(conflicts, list)
        or not all(
            _valid_offender_record(row) and _is_forbidden_process(row)
            for row in conflicts
        )
        or not isinstance(gpu, Mapping)
        or set(gpu) != {"returncode", "stdout", "stderr", "error"}
        or type(gpu.get("returncode")) not in {int, type(None)}
        or isinstance(gpu.get("returncode"), bool)
        or not isinstance(gpu.get("stdout"), str)
        or not isinstance(gpu.get("stderr"), str)
        or not isinstance(gpu.get("error"), (str, type(None)))
        or not isinstance(applications, list)
        or not _strict_json_equal(
            applications, _parse_gpu_applications(str(gpu.get("stdout")))
        )
        or not _valid_competing_gpu_partition(applications, competing)
        or value.get("external_gpu_todesk_exemption") is not False
        or value.get("runtime_claim_allowed") is not False
        or not isinstance(value.get("experiment_disk_probe"), str)
        or not value.get("experiment_disk_probe")
        or not Path(str(value.get("experiment_disk_probe"))).is_absolute()
        or type(experiment_free) is not int
        or int(experiment_free) < 0
        or not isinstance(value.get("workspace_disk_probe"), str)
        or not value.get("workspace_disk_probe")
        or not Path(str(value.get("workspace_disk_probe"))).is_absolute()
        or type(workspace_free) is not int
        or int(workspace_free) < 0
    ):
        return False
    gpu_returncode = gpu.get("returncode")
    gpu_error = gpu.get("error")
    if (
        (gpu_returncode == 0 and gpu_error is not None)
        or (
            type(gpu_returncode) is int
            and gpu_returncode != 0
            and gpu_error
            != f"GPU_COMPUTE_QUERY_RETURN_CODE:{gpu_returncode}"
        )
        or (
            gpu_returncode is None
            and (
                not isinstance(gpu_error, str)
                or not gpu_error.startswith("GPU_COMPUTE_QUERY_")
            )
        )
    ):
        return False
    if port is None:
        if port_available is not None:
            return False
    elif (
        type(port) is not int
        or not 1 <= int(port) <= 65535
        or type(port_available) is not bool
    ):
        return False
    if expected_port is not _EXPECTED_PORT_UNSET and not _strict_json_equal(
        port, expected_port
    ):
        return False
    expected_errors: list[str] = []
    if proc_errors:
        expected_errors.append("PROC_RESOURCE_GATE_PROBE_FAILED")
    if conflicts:
        expected_errors.append(
            "CONFLICTING_ESTIMATOR_EXPORTER_ROS_OR_COMPILER_PROCESS"
        )
    if gpu_error:
        expected_errors.append("GPU_COMPUTE_QUERY_FAILED")
    elif any(
        isinstance(row, Mapping) and bool(row.get("parse_errors"))
        for row in applications
    ):
        expected_errors.append("GPU_COMPUTE_QUERY_PARSE_FAILED")
    elif competing:
        expected_errors.append("COMPETING_GPU_COMPUTE_APPLICATION")
    if port is not None and port_available is False:
        expected_errors.append("ROS_PORT_UNAVAILABLE")
    if int(experiment_free) < MIN_EXPERIMENT_FREE_BYTES:
        expected_errors.append("EXPERIMENT_FREE_SPACE_BELOW_5_GIB")
    if int(workspace_free) < MIN_WORKSPACE_FREE_BYTES:
        expected_errors.append("WORKSPACE_FREE_SPACE_BELOW_512_MIB")
    expected_errors = sorted(set(expected_errors))
    return bool(errors == expected_errors and ready is (not expected_errors))


def _sampling_gap_report(
    samples: Sequence[Mapping[str, object]],
    coverage_start_ns: int,
    coverage_end_ns: int,
    target_seconds: float,
    maximum_seconds: float,
) -> dict[str, object]:
    starts = [int(sample["probe_started_monotonic_ns"]) for sample in samples]
    finishes = [int(sample["probe_finished_monotonic_ns"]) for sample in samples]
    sample_start_contract_violations: list[dict[str, object]] = []
    sample_finish_contract_violations: list[dict[str, object]] = []
    if coverage_end_ns < coverage_start_ns:
        sample_start_contract_violations.append(
            {
                "label": "coverage_interval_reversed",
                "coverage_start_monotonic_ns": coverage_start_ns,
                "coverage_end_monotonic_ns": coverage_end_ns,
            }
        )
    for index, start_ns in enumerate(starts):
        if start_ns < coverage_start_ns or start_ns > coverage_end_ns:
            sample_start_contract_violations.append(
                {
                    "label": "probe_start_outside_coverage_interval",
                    "sample_index": index,
                    "probe_started_monotonic_ns": start_ns,
                }
            )
        finish_ns = finishes[index]
        if finish_ns < start_ns:
            sample_finish_contract_violations.append(
                {
                    "label": "probe_finish_before_probe_start",
                    "sample_index": index,
                    "probe_started_monotonic_ns": start_ns,
                    "probe_finished_monotonic_ns": finish_ns,
                }
            )
        if finish_ns < coverage_start_ns or finish_ns > coverage_end_ns:
            sample_finish_contract_violations.append(
                {
                    "label": "probe_finish_outside_coverage_interval",
                    "sample_index": index,
                    "probe_finished_monotonic_ns": finish_ns,
                }
            )
        if index and start_ns <= starts[index - 1]:
            sample_start_contract_violations.append(
                {
                    "label": "probe_starts_not_strictly_increasing",
                    "sample_index": index,
                    "previous_probe_started_monotonic_ns": starts[index - 1],
                    "probe_started_monotonic_ns": start_ns,
                }
            )
    start_gaps: list[float] = []
    gap_labels: list[str] = []
    if starts:
        start_gaps.append((starts[0] - coverage_start_ns) / 1e9)
        gap_labels.append("coverage_start_to_first_probe_start")
        for index, (left, right) in enumerate(zip(starts, starts[1:]), 1):
            start_gaps.append((right - left) / 1e9)
            gap_labels.append(f"probe_start_{index - 1}_to_{index}")
        tail_gap = max(0.0, (coverage_end_ns - starts[-1]) / 1e9)
    else:
        tail_gap = max(0.0, (coverage_end_ns - coverage_start_ns) / 1e9)
    violations = [
        {"label": label, "gap_seconds": gap}
        for label, gap in zip(gap_labels, start_gaps)
        if gap > maximum_seconds
    ]
    tail_violation = tail_gap > maximum_seconds
    coverage_gaps = start_gaps + [tail_gap]
    return {
        "target_interval_seconds": target_seconds,
        "maximum_allowed_start_gap_seconds": maximum_seconds,
        "sample_count": len(samples),
        "maximum_observed_start_gap_seconds": max(start_gaps) if start_gaps else None,
        "tail_coverage_gap_seconds": tail_gap,
        "maximum_observed_coverage_gap_seconds": max(coverage_gaps) if coverage_gaps else None,
        "start_gap_violations": violations,
        "tail_coverage_gap_violation": tail_violation,
        "sample_start_contract_violations": sample_start_contract_violations,
        "sample_finish_contract_violations": sample_finish_contract_violations,
        "proven": (
            bool(samples)
            and not violations
            and not tail_violation
            and not sample_start_contract_violations
            and not sample_finish_contract_violations
        ),
    }


class RuntimeResourceMonitor:
    """Continuously monitor one exact supervised process ownership domain."""

    def __init__(
        self,
        process: subprocess.Popen[bytes],
        output_path: Path,
        supervisor_pid: int = os.getpid(),
    ) -> None:
        self.process = process
        self.output_path = Path(output_path)
        self.supervisor_pid = int(supervisor_pid)
        self.pid = int(process.pid)
        self.coverage_start_monotonic_ns = time.monotonic_ns()
        self.coverage_started_at_utc = _utc_now()
        self.coverage_end_monotonic_ns: int | None = None
        self.coverage_ended_at_utc: str | None = None
        self._lock = threading.RLock()
        self._probe_condition = threading.Condition(self._lock)
        self._stop = threading.Event()
        self._coverage_phase = "OPEN"
        self._coverage_close_recheck_in_progress = False
        self._active_probe_reservations: dict[
            tuple[str, int], tuple[int, str]
        ] = {}
        self._resolved_probe_reservations: set[tuple[str, int]] = set()
        self._proc_samples: list[dict[str, object]] = []
        self._gpu_samples: list[dict[str, object]] = []
        self._monitor_errors: list[str] = []
        # ``_known_owned`` is immutable identity history; ``_active_owned`` is
        # its currently live subset.  Keeping both is required to distinguish
        # a stale NVIDIA row from a reused numeric PID.
        self._known_owned: set[tuple[int, int]] = set()
        self._active_owned: set[tuple[int, int]] = set()
        self._ownership_discovery_history: list[dict[str, object]] = []
        self._latest_proc_records: list[dict[str, object]] = []
        self._cleanup_actions: list[dict[str, object]] = []
        self._final_receipt: dict[str, object] | None = None
        self._watchdog_gate_entered = False
        self._watchdog_signal_attempted = False

        leader, errors = _read_process_record(self.pid)
        self._monitor_errors.extend(errors)
        self.leader_identity: tuple[int, int] | None = None
        self.leader_record: dict[str, object] | None = None
        self.pgid: int | None = None
        if leader is None:
            self._monitor_errors.append("SUPERVISED_LEADER_IDENTITY_UNREADABLE_AT_MONITOR_START")
        else:
            self.leader_record = _offender_record(leader)
            self.leader_identity = _process_identity(leader)
            self.pgid = int(leader["pgid"])
            self._known_owned.add(self.leader_identity)
            self._active_owned.add(self.leader_identity)
            self._ownership_discovery_history.append(
                {
                    "sequence": 0,
                    "observed_monotonic_ns": self.coverage_start_monotonic_ns,
                    "source": "LEADER_AT_MONITOR_START",
                    "identity": {
                        "pid": self.leader_identity[0],
                        "start_ticks": self.leader_identity[1],
                    },
                    "parent_identity": None,
                }
            )
            if self.pgid != self.pid:
                self._monitor_errors.append("SUPERVISED_PROCESS_GROUP_IS_NOT_LEADER_PID")

        self._proc_thread = threading.Thread(
            target=self._proc_loop,
            name=f"fair-stability-proc-monitor-{self.pid}",
            daemon=True,
        )
        self._gpu_thread = threading.Thread(
            target=self._gpu_loop,
            name=f"fair-stability-gpu-monitor-{self.pid}",
            daemon=True,
        )
        self._proc_thread.start()
        self._gpu_thread.start()

    def _append_error(self, error: str) -> None:
        with self._lock:
            self._monitor_errors.append(error)

    def _refresh_owned(
        self, records: Sequence[Mapping[str, object]]
    ) -> set[tuple[int, int]]:
        # This helper is called both from locked monitor probes and from final
        # reap/finalize paths.  Own the lock here so GPU/proc monitor threads
        # cannot mutate either ownership set during iteration or publication.
        with self._lock:
            current = {_process_identity(record): record for record in records}
            alive = {
                identity for identity in self._active_owned if identity in current
            }
            alive.update(
                identity for identity in self._known_owned if identity in current
            )
            # Ownership grows only through an exact currently-owned parent
            # identity. Numeric PGID/PID reuse after a parent exits must never
            # turn an unrelated process into a cleanup target. Previously
            # observed exact identities remain owned while that same
            # (pid,start_ticks) is live.
            changed = True
            while changed:
                changed = False
                owned_pids = {pid for pid, _start in alive}
                for identity, record in current.items():
                    parent_pid = int(record["ppid"])
                    if identity in alive or parent_pid not in owned_pids:
                        continue
                    parent_identities = [
                        candidate for candidate in alive if candidate[0] == parent_pid
                    ]
                    if len(parent_identities) != 1:
                        continue
                    expected_parent = parent_identities[0]
                    parent_now, parent_errors = _read_process_record(parent_pid)
                    child_now, child_errors = _read_process_record(identity[0])
                    for error in parent_errors:
                        self._append_error(
                            "OWNERSHIP_PARENT_RECHECK_FAILED:"
                            f"{parent_pid}:{error}"
                        )
                    for error in child_errors:
                        self._append_error(
                            "OWNERSHIP_CHILD_RECHECK_FAILED:"
                            f"{identity[0]}:{error}"
                        )
                    if (
                        parent_now is None
                        or _process_identity(parent_now) != expected_parent
                    ):
                        continue
                    child_live_and_exact = bool(
                        child_now is not None
                        and _process_identity(child_now) == identity
                        and int(child_now["ppid"]) == parent_pid
                    )
                    child_stably_scanned_then_exited = bool(
                        child_now is None and not child_errors
                    )
                    if not child_live_and_exact and not child_stably_scanned_then_exited:
                        continue
                    if identity not in self._known_owned:
                        self._ownership_discovery_history.append(
                            {
                                "sequence": len(self._ownership_discovery_history),
                                "observed_monotonic_ns": time.monotonic_ns(),
                                "source": (
                                    "EXACT_LIVE_PARENT_RECHECK"
                                    if child_live_and_exact
                                    else "STABLE_SCAN_CHILD_EXITED_AFTER_PARENT_RECHECK"
                                ),
                                "identity": {
                                    "pid": identity[0],
                                    "start_ticks": identity[1],
                                },
                                "parent_identity": {
                                    "pid": expected_parent[0],
                                    "start_ticks": expected_parent[1],
                                },
                            }
                        )
                        self._known_owned.add(identity)
                    if child_live_and_exact:
                        alive.add(identity)
                        changed = True
            self._known_owned.update(alive)
            self._active_owned = alive
            return set(self._active_owned)

    def _owned_empty(self, records: Sequence[Mapping[str, object]]) -> bool:
        owned = self._refresh_owned(records)
        group_present = self.pgid is not None and any(
            int(record["pgid"]) == self.pgid for record in records
        )
        return not owned and not group_present

    def _mark_coverage_end_if_empty(
        self, records: Sequence[Mapping[str, object]]
    ) -> bool:
        with self._lock:
            if self.coverage_end_monotonic_ns is not None:
                return True
            if self._coverage_phase == "OPEN":
                if self.process.returncode is None:
                    return False
                try:
                    ownership_empty = self._owned_empty(records)
                except BaseException as error:
                    self._monitor_errors.append(
                        "COVERAGE_CLOSE_OWNERSHIP_PRECHECK_EXCEPTION:"
                        f"{type(error).__name__}:{error}"
                    )
                    return False
                if not ownership_empty:
                    return False
                self._coverage_phase = "CLOSE_PENDING"
                self._stop.set()
            close_ready = not self._active_probe_reservations
        if close_ready:
            self._complete_coverage_close_if_ready()
        return True

    def _closing_proc_probe(
        self,
        sequence: int,
        started_ns: int,
        started_utc: str,
    ) -> tuple[dict[str, object], bool]:
        """Run one fresh closing scan and return its sample and proof result."""

        records, scan_errors = _scan_processes()
        errors = list(scan_errors)
        with self._lock:
            error_count_before_refresh = len(self._monitor_errors)
            owned = self._refresh_owned(records)
            refresh_errors = self._monitor_errors[error_count_before_refresh:]
            errors.extend(
                str(error) for error in refresh_errors if str(error) not in errors
            )
            known_owned = set(self._known_owned)
            self._latest_proc_records = [dict(record) for record in records]
            conflicts = _external_process_conflicts(
                records,
                known_owned,
                {self.supervisor_pid, os.getpid()},
            )
            group_records = [
                record
                for record in records
                if self.pgid is not None and int(record["pgid"]) == self.pgid
            ]
            unowned_group = [
                _process_identity(record)
                for record in group_records
                if _process_identity(record) not in self._known_owned
            ]
            errors.extend(
                f"UNOWNED_PROCESS_IN_SUPERVISED_GROUP:{pid}:{start_ticks}"
                for pid, start_ticks in unowned_group
            )
            ownership_empty = not owned and not group_records

        if not ownership_empty:
            errors.append("COVERAGE_CLOSE_OWNERSHIP_EMPTY_RECHECK_FAILED")
        closing_recheck_proven = bool(ownership_empty and not errors)
        finished_ns = time.monotonic_ns()
        sample: dict[str, object] = {
            "sequence": sequence,
            "probe_role": CLOSING_PROC_PROBE_ROLE,
            "probe_started_at_utc": started_utc,
            "probe_started_monotonic_ns": started_ns,
            "probe_finished_monotonic_ns": finished_ns,
            "duration_seconds": (finished_ns - started_ns) / 1e9,
            "process_count": len(records),
            "owned_identities": [
                {"pid": pid, "start_ticks": start}
                for pid, start in sorted(owned)
            ],
            "supervised_pgid": self.pgid,
            "process_group_members": [
                {"pid": pid, "start_ticks": start_ticks}
                for pid, start_ticks in sorted(
                    _process_identity(record) for record in group_records
                )
            ],
            "external_conflicting_processes": conflicts,
            "coverage_close_ownership_empty": ownership_empty,
            "coverage_close_recheck_proven": closing_recheck_proven,
            "probe_errors": errors,
        }
        return sample, closing_recheck_proven

    def _closing_exception_sample(
        self,
        sequence: int,
        started_ns: int,
        started_utc: str,
        error: BaseException,
    ) -> dict[str, object]:
        """Create the mandatory closing row when the fresh scan raises."""

        clock_errors: list[str] = []
        try:
            finished_ns = time.monotonic_ns()
        except BaseException as clock_error:  # pragma: no cover - platform fault
            finished_ns = started_ns
            clock_errors.append(
                "COVERAGE_CLOSE_FINISH_CLOCK_EXCEPTION:"
                f"{type(clock_error).__name__}:{clock_error}"
            )
        return {
            "sequence": sequence,
            "probe_role": CLOSING_PROC_PROBE_ROLE,
            "probe_started_at_utc": started_utc,
            "probe_started_monotonic_ns": started_ns,
            "probe_finished_monotonic_ns": finished_ns,
            "duration_seconds": (finished_ns - started_ns) / 1e9,
            "process_count": None,
            "owned_identities": [],
            "supervised_pgid": self.pgid,
            "process_group_members": [],
            "external_conflicting_processes": [],
            "coverage_close_ownership_empty": None,
            "coverage_close_recheck_proven": False,
            "probe_errors": [
                "COVERAGE_CLOSE_PROC_PROBE_EXCEPTION:"
                f"{type(error).__name__}:{error}",
                *clock_errors,
            ],
        }

    def _complete_coverage_close_if_ready(self) -> bool:
        """Publish one dedicated closing proc sample, then commit coverage end."""

        with self._lock:
            if self.coverage_end_monotonic_ns is not None:
                return True
            if (
                self._coverage_phase != "CLOSE_PENDING"
                or self._active_probe_reservations
                or self._coverage_close_recheck_in_progress
                or getattr(self, "_coverage_close_recheck_attempted", False)
            ):
                return False
            # CLOSE_PENDING prevents every ordinary reservation. Mark this
            # unique closing attempt under the reservation/coverage lock.
            self._coverage_close_recheck_in_progress = True
            self._coverage_close_recheck_attempted = True
            sequence = len(self._proc_samples)
            if any(
                sample.get("sequence") != index
                for index, sample in enumerate(self._proc_samples)
            ):
                self._monitor_errors.append(
                    "COVERAGE_CLOSE_PROC_SEQUENCE_PRECONDITION_FAILED"
                )

        try:
            started_ns = time.monotonic_ns()
            started_utc = _utc_now()
        except BaseException as error:
            with self._lock:
                self._coverage_close_recheck_in_progress = False
                self._monitor_errors.append(
                    "COVERAGE_CLOSE_START_TIMESTAMP_EXCEPTION:"
                    f"{type(error).__name__}:{error}"
                )
                self._probe_condition.notify_all()
            return False

        try:
            sample, closing_recheck_proven = self._closing_proc_probe(
                sequence,
                started_ns,
                started_utc,
            )
        except BaseException as error:
            sample = self._closing_exception_sample(
                sequence,
                started_ns,
                started_utc,
                error,
            )
            closing_recheck_proven = False

        # The evidence row must exist before the end-clock is sampled. This
        # makes closing work part of the covered proc sampling population.
        with self._lock:
            self._coverage_close_recheck_in_progress = False
            self._proc_samples.append(sample)
            self._monitor_errors.extend(
                str(value) for value in sample.get("probe_errors", [])
            )

            state_valid = bool(
                self.coverage_end_monotonic_ns is None
                and self._coverage_phase == "CLOSE_PENDING"
                and not self._active_probe_reservations
            )
            process_reaped = self.process.returncode is not None
            if not state_valid:
                self._monitor_errors.append(
                    "COVERAGE_CLOSE_STATE_OR_RESERVATION_RECHECK_FAILED"
                )
            if not process_reaped:
                self._monitor_errors.append(
                    "COVERAGE_CLOSE_SUPERVISED_PROCESS_NOT_REAPED"
                )
            if not closing_recheck_proven:
                self._monitor_errors.append(
                    "COVERAGE_CLOSE_OWNERSHIP_RECHECK_UNPROVEN"
                )
            if not (state_valid and process_reaped and closing_recheck_proven):
                self._probe_condition.notify_all()
                return False

            try:
                end_ns = time.monotonic_ns()
                ended_at_utc = _utc_now()
            except BaseException as error:
                self._monitor_errors.append(
                    "COVERAGE_CLOSE_END_TIMESTAMP_EXCEPTION:"
                    f"{type(error).__name__}:{error}"
                )
                self._probe_condition.notify_all()
                return False
            if end_ns < int(sample["probe_finished_monotonic_ns"]):
                self._monitor_errors.append(
                    "COVERAGE_CLOSE_END_BEFORE_CLOSING_PROBE_FINISH"
                )
                self._probe_condition.notify_all()
                return False

            self._coverage_close_recheck_succeeded = True
            self.coverage_end_monotonic_ns = end_ns
            self.coverage_ended_at_utc = ended_at_utc
            self._coverage_phase = "CLOSED"
            self._stop.set()
            self._probe_condition.notify_all()
            return True

    def _reserve_probe_start(
        self,
        stream: str,
        sequence: int,
    ) -> tuple[str, int] | None:
        """Reserve one imminent probe under the coverage-close lock."""
        token = (stream, sequence)
        with self._lock:
            if (
                stream not in {"proc", "gpu"}
                or sequence < 0
                or self._coverage_phase != "OPEN"
                or self.coverage_end_monotonic_ns is not None
                or self._stop.is_set()
            ):
                return None
            if (
                token in self._active_probe_reservations
                or token in self._resolved_probe_reservations
            ):
                self._monitor_errors.append(
                    f"DUPLICATE_PROBE_RESERVATION:{stream}:{sequence}"
                )
                return None
            self._active_probe_reservations[token] = (
                time.monotonic_ns(),
                _utc_now(),
            )
            return token

    def _resolve_probe_reservation(
        self,
        token: tuple[str, int],
        sample: dict[str, object],
    ) -> None:
        """Publish exactly one normal/error row, then consume its reservation."""
        stream, sequence = token
        with self._lock:
            reservation = self._active_probe_reservations.get(token)
            if reservation is None or token in self._resolved_probe_reservations:
                self._monitor_errors.append(
                    f"PROBE_RESERVATION_RESOLUTION_INVALID:{stream}:{sequence}"
                )
                return
            if (
                sample.get("sequence") != sequence
                or stream not in {"proc", "gpu"}
            ):
                self._monitor_errors.append(
                    f"PROBE_RESERVATION_SAMPLE_BINDING_INVALID:{stream}:{sequence}"
                )
            target = self._proc_samples if stream == "proc" else self._gpu_samples
            target.append(sample)
            self._monitor_errors.extend(
                str(value) for value in sample.get("probe_errors", [])
            )
            del self._active_probe_reservations[token]
            self._resolved_probe_reservations.add(token)
            close_ready = bool(
                self._coverage_phase == "CLOSE_PENDING"
                and not self._active_probe_reservations
            )
            self._probe_condition.notify_all()
        if close_ready:
            self._complete_coverage_close_if_ready()

    def _proc_probe(
        self,
        sequence: int,
        started_ns: int,
        started_utc: str,
    ) -> dict[str, object]:
        records, errors = _scan_processes()
        with self._lock:
            owned = self._refresh_owned(records)
            known_owned = set(self._known_owned)
            self._latest_proc_records = [dict(record) for record in records]
            conflicts = _external_process_conflicts(
                records, known_owned, {self.supervisor_pid, os.getpid()}
            )
            group_records = [
                record
                for record in records
                if self.pgid is not None and int(record["pgid"]) == self.pgid
            ]
            unowned_group = [
                _process_identity(record)
                for record in group_records
                if _process_identity(record) not in self._known_owned
            ]
            errors.extend(
                f"UNOWNED_PROCESS_IN_SUPERVISED_GROUP:{pid}:{start_ticks}"
                for pid, start_ticks in unowned_group
            )
        finished_ns = time.monotonic_ns()
        sample: dict[str, object] = {
            "sequence": sequence,
            "probe_role": ORDINARY_PROC_PROBE_ROLE,
            "probe_started_at_utc": started_utc,
            "probe_started_monotonic_ns": started_ns,
            "probe_finished_monotonic_ns": finished_ns,
            "duration_seconds": (finished_ns - started_ns) / 1e9,
            "process_count": len(records),
            "owned_identities": [
                {"pid": pid, "start_ticks": start}
                for pid, start in sorted(owned)
            ],
            "supervised_pgid": self.pgid,
            "process_group_members": [
                {"pid": pid, "start_ticks": start_ticks}
                for pid, start_ticks in sorted(
                    _process_identity(record) for record in group_records
                )
            ],
            "external_conflicting_processes": conflicts,
            "probe_errors": errors,
        }
        return sample

    def _gpu_probe(
        self,
        sequence: int,
        started_ns: int,
        started_utc: str,
    ) -> dict[str, object]:
        query = _run_gpu_compute_query()
        applications = _parse_gpu_applications(str(query.get("stdout") or ""))
        with self._lock:
            active_owned = set(self._active_owned)
            known_owned = set(self._known_owned)
        classified = _classify_gpu_applications(
            applications, active_owned, known_owned, self.pgid
        )
        discovered = {
            (int(row["pid"]), int(row["start_ticks"]))
            for row in classified["discovered_owned_identities"]
        }
        with self._lock:
            self._known_owned.update(discovered)
            self._active_owned.update(discovered)
        finished_ns = time.monotonic_ns()
        errors = [str(query["error"])] if query.get("error") else []
        errors.extend(
            str(error)
            for row in applications
            for error in row.get("parse_errors", [])
        )
        errors.extend(
            str(error)
            for category in ("external", "stale_owned", "current_owned")
            for row in classified[category]
            for error in row.get("proc_identity_read_errors", [])
        )
        return {
            "sequence": sequence,
            "probe_started_at_utc": started_utc,
            "probe_started_monotonic_ns": started_ns,
            "probe_finished_monotonic_ns": finished_ns,
            "duration_seconds": (finished_ns - started_ns) / 1e9,
            "query_returncode": query.get("returncode"),
            "query_stdout": query.get("stdout"),
            "query_stderr": query.get("stderr"),
            "query_error": query.get("error"),
            "compute_applications": applications,
            "external_compute_applications": classified["external"],
            "stale_owned_gpu_rows": classified["stale_owned"],
            "current_owned_gpu_rows": classified["current_owned"],
            "discovered_owned_identities": classified[
                "discovered_owned_identities"
            ],
            "external_gpu_todesk_exemption": False,
            "probe_errors": errors,
        }

    def _proc_loop(self) -> None:
        sequence = 0
        next_start = time.monotonic()
        while True:
            token = self._reserve_probe_start("proc", sequence)
            if token is None:
                break
            started_ns = time.monotonic_ns()
            started_utc = _utc_now()
            try:
                sample = self._proc_probe(sequence, started_ns, started_utc)
            except BaseException as error:  # evidence must survive unexpected probe faults
                finished_ns = time.monotonic_ns()
                sample = {
                    "sequence": sequence,
                    "probe_role": ORDINARY_PROC_PROBE_ROLE,
                    "probe_started_at_utc": started_utc,
                    "probe_started_monotonic_ns": started_ns,
                    "probe_finished_monotonic_ns": finished_ns,
                    "duration_seconds": (finished_ns - started_ns) / 1e9,
                    "process_count": None,
                    "owned_identities": [],
                    "supervised_pgid": self.pgid,
                    "process_group_members": [],
                    "external_conflicting_processes": [],
                    "probe_errors": [f"PROC_PROBE_EXCEPTION:{type(error).__name__}:{error}"],
                }
            self._resolve_probe_reservation(token, sample)
            with self._lock:
                records = list(self._latest_proc_records)
            if self._mark_coverage_end_if_empty(records):
                break
            if self._stop.is_set():
                break
            sequence += 1
            next_start += PROC_TARGET_INTERVAL_SECONDS
            delay = max(0.0, next_start - time.monotonic())
            if self._stop.wait(delay):
                break

    def _gpu_loop(self) -> None:
        sequence = 0
        next_start = time.monotonic()
        while True:
            token = self._reserve_probe_start("gpu", sequence)
            if token is None:
                break
            started_ns = time.monotonic_ns()
            started_utc = _utc_now()
            try:
                sample = self._gpu_probe(sequence, started_ns, started_utc)
            except BaseException as error:  # evidence must survive unexpected probe faults
                finished_ns = time.monotonic_ns()
                sample = {
                    "sequence": sequence,
                    "probe_started_at_utc": started_utc,
                    "probe_started_monotonic_ns": started_ns,
                    "probe_finished_monotonic_ns": finished_ns,
                    "duration_seconds": (finished_ns - started_ns) / 1e9,
                    "query_returncode": None,
                    "query_stdout": "",
                    "query_stderr": "",
                    "query_error": None,
                    "compute_applications": [],
                    "external_compute_applications": [],
                    "stale_owned_gpu_rows": [],
                    "current_owned_gpu_rows": [],
                    "discovered_owned_identities": [],
                    "external_gpu_todesk_exemption": False,
                    "probe_errors": [f"GPU_PROBE_EXCEPTION:{type(error).__name__}:{error}"],
                }
            self._resolve_probe_reservation(token, sample)
            if self._stop.is_set():
                break
            sequence += 1
            next_start += GPU_TARGET_INTERVAL_SECONDS
            delay = max(0.0, next_start - time.monotonic())
            if self._stop.wait(delay):
                break

    def wait(self, timeout: float | None) -> tuple[int | None, bool, bool]:
        """Wait for the leader without killing on timeout.

        Returns ``(returncode, leader_reaped, timed_out)``.  Monitoring remains
        active after return until the complete ownership domain is empty.
        """
        try:
            returncode = self.process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            returncode = self.process.poll()
            return returncode, returncode is not None, returncode is None
        records, errors = _scan_processes()
        for error in errors:
            self._append_error(error)
        self._mark_coverage_end_if_empty(records)
        return returncode, True, False

    def watchdog_exact_group_snapshot(
        self,
        expected_executable: str,
        expected_argv: Sequence[str],
    ) -> dict[str, object]:
        """Prove the exact live HFNet session/process group without signaling it."""
        records, scan_errors = _scan_processes()
        errors = [f"GROUP_SCAN:{value}" for value in scan_errors]

        def add_error(value: str) -> None:
            if value not in errors:
                errors.append(value)

        expected_tokens = [str(value) for value in expected_argv]
        if self.pgid != self.pid or self.leader_identity is None:
            add_error("SUPERVISED_LEADER_PGID_OR_IDENTITY_INVALID")
        globally_visible_leaders = [
            record for record in records if int(record["pid"]) == self.pid
        ]
        if len(globally_visible_leaders) > 1:
            add_error(
                f"GLOBAL_NUMERIC_LEADER_COUNT_INVALID:{len(globally_visible_leaders)}"
            )
        elif len(globally_visible_leaders) == 1:
            global_leader = globally_visible_leaders[0]
            for value in global_leader.get("read_errors", []):
                add_error(f"GLOBAL_LEADER_READ:{self.pid}:{value}")
            if (
                _process_identity(global_leader) != self.leader_identity
                or int(global_leader["pgid"]) != self.pid
                or int(global_leader["session"]) != self.pid
            ):
                add_error("GLOBAL_FROZEN_LEADER_STABLE_IDENTITY_DRIFT")
            if (
                (
                    global_leader.get("executable") != expected_executable
                    or list(global_leader.get("cmdline", [])) != expected_tokens
                )
                and (
                    global_leader.get("executable") is not None
                    or bool(global_leader.get("cmdline", []))
                )
            ):
                add_error("GLOBAL_FROZEN_LEADER_WRONG_NONEMPTY_IDENTITY_OBSERVED")
        group = [
            record
            for record in records
            if self.pgid is not None and int(record["pgid"]) == self.pgid
        ]
        leaders = [record for record in group if int(record["pid"]) == self.pid]
        if len(leaders) != 1:
            add_error(f"EXACT_GROUP_LEADER_COUNT:{len(leaders)}")
        else:
            initial_leader = leaders[0]
            if (
                _process_identity(initial_leader) != self.leader_identity
                or int(initial_leader["pgid"]) != self.pid
                or int(initial_leader["session"]) != self.pid
                or initial_leader.get("executable") != expected_executable
                or list(initial_leader.get("cmdline", [])) != expected_tokens
            ):
                add_error("EXACT_GROUP_LEADER_IDENTITY_OR_ARGV_MISMATCH")
                if (
                    initial_leader.get("executable") is not None
                    or bool(initial_leader.get("cmdline", []))
                ):
                    add_error("EXACT_GROUP_LEADER_WRONG_NONEMPTY_IDENTITY_OBSERVED")
        member_rows: list[dict[str, object]] = []
        for record in sorted(group, key=lambda value: int(value["pid"])):
            pid = int(record["pid"])
            errors.extend(
                f"GROUP_MEMBER_READ:{pid}:{value}"
                for value in record.get("read_errors", [])
            )
            if int(record["session"]) != self.pid:
                errors.append(f"GROUP_MEMBER_OUTSIDE_LEADER_SESSION:{pid}")
            current, recheck_errors = _read_process_record(pid)
            errors.extend(
                f"GROUP_MEMBER_RECHECK:{pid}:{value}" for value in recheck_errors
            )
            immutable = ("pid", "start_ticks", "pgid", "session")
            if current is None:
                if (
                    not recheck_errors
                    and len(group) == 1
                    and pid == self.pid
                    and _process_identity(record) == self.leader_identity
                    and int(record["pgid"]) == self.pid
                    and int(record["session"]) == self.pid
                ):
                    add_error("EXACT_GROUP_LEADER_DISAPPEARED_DURING_RECHECK")
                    if (
                        record.get("state") == "Z"
                        and record.get("executable") is None
                        and record.get("cmdline_sha256") == EMPTY_CMDLINE_SHA256
                    ):
                        member_rows.append(
                            {
                                "pid": pid,
                                "start_ticks": int(record["start_ticks"]),
                                "pgid": int(record["pgid"]),
                                "session": int(record["session"]),
                                "state": record.get("state"),
                                "executable": record.get("executable"),
                                "cmdline_sha256": record.get("cmdline_sha256"),
                            }
                        )
                else:
                    add_error(f"GROUP_MEMBER_IDENTITY_RECHECK_MISMATCH:{pid}")
                continue
            if any(current.get(key) != record.get(key) for key in immutable):
                add_error(f"GROUP_MEMBER_IDENTITY_RECHECK_MISMATCH:{pid}")
                continue
            errors.extend(
                f"GROUP_MEMBER_RECHECK_READ:{pid}:{value}"
                for value in current.get("read_errors", [])
            )
            member_rows.append(
                {
                    "pid": pid,
                    "start_ticks": int(current["start_ticks"]),
                    "pgid": int(current["pgid"]),
                    "session": int(current["session"]),
                    "state": current.get("state"),
                    "executable": current.get("executable"),
                    "cmdline_sha256": current.get("cmdline_sha256"),
                }
            )
            if pid == self.pid and (
                _process_identity(current) != self.leader_identity
                or int(current["pgid"]) != self.pid
                or int(current["session"]) != self.pid
                or current.get("executable") != expected_executable
                or list(current.get("cmdline", [])) != expected_tokens
            ):
                add_error("EXACT_GROUP_LEADER_IDENTITY_OR_ARGV_MISMATCH")
                if (
                    current.get("executable") is not None
                    or bool(current.get("cmdline", []))
                ):
                    add_error("EXACT_GROUP_LEADER_WRONG_NONEMPTY_IDENTITY_OBSERVED")
            if current.get("state") == "Z" and not (
                pid == self.pid
                and current.get("executable") is None
                and current.get("cmdline_sha256") == EMPTY_CMDLINE_SHA256
            ):
                add_error(f"GROUP_MEMBER_NOT_LIVE_STATE:{pid}:Z")
        return {
            "observed_at_utc": _utc_now(),
            "observed_monotonic_ns": time.monotonic_ns(),
            "proven": not errors and bool(group),
            "errors": errors,
            "leader_pid": self.pid,
            "leader_start_ticks": (
                self.leader_identity[1] if self.leader_identity is not None else None
            ),
            "expected_executable": expected_executable,
            "expected_argv": expected_tokens,
            "pgid": self.pgid,
            "session": self.pid,
            "members": member_rows,
        }

    def watchdog_sigterm_exact_group(
        self,
        expected_executable: str,
        expected_argv: Sequence[str],
        *,
        deadline_monotonic: float,
        final_gate_started_monotonic: float,
        maximum_final_gate_duration_seconds: float,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> dict[str, object]:
        """Attempt SIGTERM once after two proofs and before the fixed deadline.

        The final gate has its own bounded clock.  Its anchor is the completion
        of the immediately preceding final signature revalidation, not the
        beginning of the ordinary watchdog sample that led to that
        revalidation.  The caller separately proves that ordinary sample's
        latency.  Keeping the two phases independent prevents the same work
        from being charged to both bounds while retaining a 0.25 s fail-closed
        limit on each phase.
        """

        gate_started = float(final_gate_started_monotonic)
        maximum_gate_duration = float(maximum_final_gate_duration_seconds)
        deadline = float(deadline_monotonic)

        def complete_gate(
            candidate: Mapping[str, object],
            *,
            observed_monotonic: float | None = None,
        ) -> dict[str, object]:
            observed = (
                float(monotonic())
                if observed_monotonic is None
                else float(observed_monotonic)
            )
            elapsed = observed - gate_started
            gate_errors = [str(value) for value in candidate.get("errors", [])]
            if not all(
                math.isfinite(value)
                for value in (
                    observed,
                    gate_started,
                    maximum_gate_duration,
                    deadline,
                )
            ) or maximum_gate_duration < 0.0:
                gate_errors.append("WATCHDOG_FINAL_GATE_TIMING_INVALID")
            elif elapsed < 0.0:
                gate_errors.append("WATCHDOG_FINAL_GATE_CLOCK_REGRESSION")
            elif elapsed > maximum_gate_duration:
                gate_errors.append("WATCHDOG_FINAL_GATE_DURATION_EXCEEDED")
            result = dict(candidate)
            result.update(
                {
                    "deadline_monotonic": deadline,
                    "final_gate_started_monotonic": gate_started,
                    "maximum_final_gate_duration_seconds": maximum_gate_duration,
                    "pre_signal_monotonic": observed,
                    "final_gate_elapsed_seconds": elapsed,
                    "errors": list(dict.fromkeys(gate_errors)),
                }
            )
            return result

        with self._lock:
            if (
                getattr(self, "_watchdog_gate_entered", False)
                or self._watchdog_signal_attempted
            ):
                return complete_gate(
                    {
                        "classification": "SIGNAL_ALREADY_ATTEMPTED",
                        "signal_attempted": False,
                        "signal_sent": False,
                        "errors": ["WATCHDOG_SIGNAL_ALREADY_ATTEMPTED"],
                    }
                )
            self._watchdog_gate_entered = True

        def passive(
            phase: str,
            poll_returncode: int,
            poll_observed_monotonic_ns: int,
        ) -> dict[str, object]:
            """Classify passive only after this monitor's exact Popen is reaped."""

            reap_started = time.monotonic_ns()
            try:
                wait_returncode = self.process.wait(timeout=0)
            except (OSError, subprocess.SubprocessError) as error:
                return {
                    "classification": "LIVE_OR_UNKNOWN_GROUP_UNPROVEN",
                    "phase": phase,
                    "leader_returncode": int(poll_returncode),
                    "signal_attempted": False,
                    "signal_sent": False,
                    "errors": [
                        "SAME_POPEN_REAP_FAILED:"
                        f"{type(error).__name__}:{error}"
                    ],
                }
            reap_completed = time.monotonic_ns()
            frozen_identity = (
                {
                    "pid": self.pid,
                    "start_ticks": self.leader_identity[1],
                    "pgid": self.pgid,
                    "session": self.pid,
                }
                if self.leader_identity is not None
                else None
            )
            if (
                type(poll_returncode) is not int
                or type(wait_returncode) is not int
                or wait_returncode != poll_returncode
                or self.leader_identity is None
                or self.leader_identity[0] != self.pid
                or self.pgid != self.pid
            ):
                return {
                    "classification": "LIVE_OR_UNKNOWN_GROUP_UNPROVEN",
                    "phase": phase,
                    "leader_returncode": (
                        int(poll_returncode)
                        if type(poll_returncode) is int
                        else None
                    ),
                    "signal_attempted": False,
                    "signal_sent": False,
                    "errors": ["SAME_POPEN_REAP_IDENTITY_OR_RETURN_CODE_UNPROVEN"],
                }
            reap = {
                "schema_version": "aqua-fe-fair-stability-same-popen-reap-v11",
                "source": "FINAL_GATE_POLL_THEN_WAIT_ZERO",
                "same_popen": True,
                "frozen_process_identity": frozen_identity,
                "poll_observed_monotonic_ns": int(poll_observed_monotonic_ns),
                "poll_returncode": int(poll_returncode),
                "wait_started_monotonic_ns": int(reap_started),
                "wait_completed_monotonic_ns": int(reap_completed),
                "wait_timeout_seconds": 0.0,
                "wait_returncode": int(wait_returncode),
            }
            return {
                "classification": "LEADER_REAPED_BEFORE_SIGNAL",
                "phase": phase,
                "observed_at_utc": _utc_now(),
                "observed_monotonic_ns": time.monotonic_ns(),
                "leader_returncode": int(wait_returncode),
                "reaped_before_next_sample": True,
                "reap": reap,
                "signal_attempted": False,
                "signal_sent": False,
                "errors": [],
            }

        initial_returncode = self.process.poll()
        initial_poll_monotonic_ns = time.monotonic_ns()
        if initial_returncode is not None:
            return complete_gate(
                passive(
                    "BEFORE_FIRST_FINAL_GROUP_PROOF",
                    initial_returncode,
                    initial_poll_monotonic_ns,
                )
            )
        first = self.watchdog_exact_group_snapshot(
            expected_executable, expected_argv
        )
        first_returncode = self.process.poll()
        first_poll_monotonic_ns = time.monotonic_ns()
        if first_returncode is not None:
            if (
                first.get("proven") is True
                or watchdog_terminal_transition_candidate(first)
            ):
                result = passive(
                    "AFTER_FIRST_FINAL_GROUP_PROOF",
                    first_returncode,
                    first_poll_monotonic_ns,
                )
                result["terminal_transition_snapshot"] = first
                return complete_gate(result)
            return complete_gate(
                {
                    "classification": "LIVE_OR_UNKNOWN_GROUP_UNPROVEN",
                    "phase": "AFTER_FIRST_FINAL_GROUP_PROOF",
                    "leader_returncode": int(first_returncode),
                    "terminal_transition_snapshot": first,
                    "signal_attempted": False,
                    "signal_sent": False,
                    "errors": [str(value) for value in first.get("errors", [])]
                    or ["FINAL_EXACT_GROUP_PROOF_FAILED"],
                }
            )
        if first.get("proven") is not True:
            return complete_gate(
                {
                    "classification": (
                        "TERMINAL_TRANSITION_PENDING_REAP"
                        if watchdog_terminal_transition_candidate(first)
                        else "LIVE_OR_UNKNOWN_GROUP_UNPROVEN"
                    ),
                    "phase": "FIRST_FINAL_GROUP_PROOF",
                    "terminal_transition_snapshot": first,
                    "signal_attempted": False,
                    "signal_sent": False,
                    "errors": [str(value) for value in first.get("errors", [])]
                    or ["FINAL_EXACT_GROUP_PROOF_FAILED"],
                }
            )
        second = self.watchdog_exact_group_snapshot(
            expected_executable, expected_argv
        )
        second_returncode = self.process.poll()
        second_poll_monotonic_ns = time.monotonic_ns()
        if second_returncode is not None:
            if (
                second.get("proven") is True
                or watchdog_terminal_transition_candidate(second)
            ):
                result = passive(
                    "AFTER_SECOND_FINAL_GROUP_PROOF",
                    second_returncode,
                    second_poll_monotonic_ns,
                )
                result["first_exact_group_proof"] = first
                result["terminal_transition_snapshot"] = second
                return complete_gate(result)
            return complete_gate(
                {
                    "classification": "LIVE_OR_UNKNOWN_GROUP_UNPROVEN",
                    "phase": "AFTER_SECOND_FINAL_GROUP_PROOF",
                    "leader_returncode": int(second_returncode),
                    "first_exact_group_proof": first,
                    "terminal_transition_snapshot": second,
                    "signal_attempted": False,
                    "signal_sent": False,
                    "errors": [str(value) for value in second.get("errors", [])]
                    or ["FINAL_EXACT_GROUP_PROOF_FAILED"],
                }
            )
        if second.get("proven") is not True:
            return complete_gate(
                {
                    "classification": (
                        "TERMINAL_TRANSITION_PENDING_REAP"
                        if watchdog_terminal_transition_candidate(second)
                        else "LIVE_OR_UNKNOWN_GROUP_UNPROVEN"
                    ),
                    "phase": "SECOND_FINAL_GROUP_PROOF",
                    "first_exact_group_proof": first,
                    "terminal_transition_snapshot": second,
                    "signal_attempted": False,
                    "signal_sent": False,
                    "errors": [str(value) for value in second.get("errors", [])]
                    or ["FINAL_EXACT_GROUP_PROOF_FAILED"],
                }
            )
        first_members = first.get("members")
        second_members = second.get("members")
        errors: list[str] = []
        if (
            not isinstance(first_members, list)
            or not first_members
            or _watchdog_stable_member_projection(first_members)
            != _watchdog_stable_member_projection(second_members)
        ):
            errors.append("FINAL_EXACT_GROUP_MEMBERSHIP_CHANGED")
        leader_returncode = self.process.poll()
        leader_poll_monotonic_ns = time.monotonic_ns()
        if leader_returncode is not None:
            if errors:
                return complete_gate(
                    {
                        "classification": "LIVE_OR_UNKNOWN_GROUP_UNPROVEN",
                        "phase": "BEFORE_KILLPG",
                        "leader_returncode": int(leader_returncode),
                        "first_exact_group_proof": first,
                        "final_exact_group_proof": second,
                        "signal_attempted": False,
                        "signal_sent": False,
                        "errors": errors,
                    }
                )
            result = passive(
                "BEFORE_KILLPG",
                leader_returncode,
                leader_poll_monotonic_ns,
            )
            result["first_exact_group_proof"] = first
            result["final_exact_group_proof"] = second
            return complete_gate(result)
        pre_signal_monotonic = float(monotonic())
        if pre_signal_monotonic >= deadline:
            errors.append("WATCHDOG_DEADLINE_REACHED_BEFORE_SIGNAL")
        final_gate_elapsed = pre_signal_monotonic - gate_started
        if not all(
            math.isfinite(value)
            for value in (
                pre_signal_monotonic,
                gate_started,
                maximum_gate_duration,
                deadline,
            )
        ) or maximum_gate_duration < 0.0:
            errors.append("WATCHDOG_FINAL_GATE_TIMING_INVALID")
        elif final_gate_elapsed < 0.0:
            errors.append("WATCHDOG_FINAL_GATE_CLOCK_REGRESSION")
        elif final_gate_elapsed > maximum_gate_duration:
            errors.append("WATCHDOG_FINAL_GATE_DURATION_EXCEEDED")
        if errors or self.pgid != self.pid:
            if self.pgid != self.pid:
                errors.append("FINAL_EXACT_GROUP_PGID_INVALID")
            return complete_gate(
                {
                    "classification": "LIVE_OR_UNKNOWN_GROUP_UNPROVEN",
                    "phase": "FINAL_PRE_SIGNAL_GATE",
                    "first_exact_group_proof": first,
                    "final_exact_group_proof": second,
                    "signal_attempted": False,
                    "signal_sent": False,
                    "errors": errors,
                },
                observed_monotonic=pre_signal_monotonic,
            )

        self._watchdog_signal_attempted = True
        sent = False
        signal_error: str | None = None
        try:
            os.killpg(self.pid, signal.SIGTERM)
            sent = True
        except OSError as error:
            signal_error = f"{type(error).__name__}:{error.errno}"
            errors.append(f"WATCHDOG_KILLPG_FAILED:{error.errno}")
        action = {
            "classification": (
                "SIGTERM_SENT" if sent else "SIGNAL_DELIVERY_FAILED"
            ),
            "at_utc": _utc_now(),
            "monotonic_ns": time.monotonic_ns(),
            "label": "confirmed_zero_kf_post_shutdown_watchdog",
            "signal": int(signal.SIGTERM),
            "signal_scope": "EXACT_REVALIDATED_PROCESS_GROUP",
            "signal_attempted": True,
            "signal_sent": sent,
            "group_sent": sent,
            "group_error": signal_error,
            "individual_identities_sent": [],
            "first_exact_group_proof": first,
            "final_exact_group_proof": second,
            "errors": errors,
        }
        action = complete_gate(
            action,
            observed_monotonic=pre_signal_monotonic,
        )
        with self._lock:
            self._cleanup_actions.append(action)
        return action

    def _signal_current_owned(self, signum: int, label: str) -> None:
        records, errors = _scan_processes()
        for error in errors:
            self._append_error(error)
        with self._lock:
            owned = self._refresh_owned(records)
        group_members = [
            record for record in records
            if self.pgid is not None and int(record["pgid"]) == self.pgid
        ]
        group_sent = False
        group_error: str | None = None
        safe_group_leader = False
        leader_identity = getattr(self, "leader_identity", None)
        if (
            self.pgid == self.pid
            and isinstance(leader_identity, tuple)
            and len(leader_identity) == 2
            and leader_identity in owned
        ):
            leader_records = [
                record
                for record in group_members
                if _process_identity(record) == leader_identity
                and int(record["pid"]) == self.pid
            ]
            if len(leader_records) == 1:
                current, recheck_errors = _read_process_record(self.pid)
                for error in recheck_errors:
                    self._append_error(
                        f"OWNED_GROUP_IDENTITY_RECHECK_FAILED:{self.pid}:{error}"
                    )
                safe_group_leader = bool(
                    current is not None
                    and _process_identity(current) == leader_identity
                    and int(current["pgid"]) == self.pid
                    and int(current["session"]) == self.pid
                )
        if self.pgid == self.pid and safe_group_leader:
            try:
                os.killpg(self.pgid, signum)
                group_sent = True
            except ProcessLookupError:
                pass
            except OSError as error:
                group_error = f"{type(error).__name__}:{error}"
                self._append_error(f"OWNED_GROUP_SIGNAL_FAILED:{label}:{error.errno}")
        individually_sent: list[dict[str, int]] = []
        for identity in sorted(owned):
            if identity[0] == os.getpid():
                continue
            current, recheck_errors = _read_process_record(identity[0])
            for error in recheck_errors:
                self._append_error(
                    f"OWNED_PID_IDENTITY_RECHECK_FAILED:{label}:{identity[0]}:{error}"
                )
            if current is None or _process_identity(current) != identity:
                continue
            if group_sent and int(current["pgid"]) == self.pgid:
                continue
            try:
                os.kill(identity[0], signum)
                individually_sent.append({"pid": identity[0], "start_ticks": identity[1]})
            except ProcessLookupError:
                pass
            except OSError as error:
                self._append_error(f"OWNED_PID_SIGNAL_FAILED:{label}:{identity[0]}:{error.errno}")
        with self._lock:
            self._cleanup_actions.append(
                {
                    "at_utc": _utc_now(),
                    "monotonic_ns": time.monotonic_ns(),
                    "label": label,
                    "signal": signum,
                    "group_sent": group_sent,
                    "group_error": group_error,
                    "individual_identities_sent": individually_sent,
                }
            )

    def terminate(self) -> tuple[int | None, bool]:
        """Terminate only exact currently owned identities; never on intrusion."""
        if self.process.poll() is None:
            self._signal_current_owned(signal.SIGTERM, "terminate")
            try:
                returncode = self.process.wait(timeout=10.0)
                return returncode, True
            except subprocess.TimeoutExpired:
                self._signal_current_owned(signal.SIGKILL, "kill_after_terminate_timeout")
        try:
            returncode = self.process.wait(timeout=10.0)
            return returncode, True
        except subprocess.TimeoutExpired:
            returncode = self.process.poll()
            return returncode, returncode is not None

    def reap_process_group(self) -> bool:
        """Drain the supervised group/known descendants and keep monitoring active."""
        if self.process.poll() is None:
            self.terminate()
        deadline = time.monotonic() + 30.0
        term_sent = False
        while True:
            records, errors = _scan_processes()
            for error in errors:
                self._append_error(error)
            if self.process.returncode is not None and self._owned_empty(records):
                self._mark_coverage_end_if_empty(records)
                return True
            if not term_sent:
                self._signal_current_owned(signal.SIGTERM, "reap_term")
                term_sent = True
            elif time.monotonic() + 25.0 >= deadline:
                self._signal_current_owned(signal.SIGKILL, "reap_kill")
            if time.monotonic() >= deadline:
                self._append_error("SUPERVISED_PROCESS_GROUP_NOT_EMPTY_AFTER_REAP")
                return False
            time.sleep(0.05)

    def finalize(self) -> dict[str, object]:
        """Stop after cleanup, classify evidence, and exclusively write the receipt."""
        with self._lock:
            if self._final_receipt is not None:
                return self._final_receipt
        records, errors = _scan_processes()
        for error in errors:
            self._append_error(error)
        clean = self.process.returncode is not None and self._owned_empty(records)
        if clean:
            self._mark_coverage_end_if_empty(records)
        else:
            self._append_error("MONITOR_FINALIZED_BEFORE_PROCESS_GROUP_EMPTY")
            with self._lock:
                if self._coverage_phase == "OPEN":
                    self._coverage_phase = "CLOSE_PENDING"
                    self._stop.set()
        self._proc_thread.join(timeout=3.0)
        self._gpu_thread.join(timeout=3.0)
        if self._proc_thread.is_alive():
            self._append_error("PROC_MONITOR_THREAD_DID_NOT_STOP")
        if self._gpu_thread.is_alive():
            self._append_error("GPU_MONITOR_THREAD_DID_NOT_STOP")

        with self._lock:
            unresolved_reservations = sorted(self._active_probe_reservations)
        if unresolved_reservations:
            self._append_error(
                "UNRESOLVED_PROBE_RESERVATIONS_AT_FINALIZE:"
                + ",".join(
                    f"{stream}:{sequence}"
                    for stream, sequence in unresolved_reservations
                )
            )
        if (
            self._proc_thread.is_alive()
            or self._gpu_thread.is_alive()
            or unresolved_reservations
        ):
            raise RuntimeError("RUNTIME_MONITOR_RESERVATION_DRAIN_UNPROVEN")

        if self.coverage_end_monotonic_ns is None and clean:
            self._complete_coverage_close_if_ready()

        with self._lock:
            closing_indices = [
                index
                for index, sample in enumerate(self._proc_samples)
                if sample.get("probe_role") == CLOSING_PROC_PROBE_ROLE
            ]
            closing_contract_proven = bool(
                clean
                and getattr(self, "_coverage_close_recheck_succeeded", False)
                and self.coverage_end_monotonic_ns is not None
                and self._coverage_phase == "CLOSED"
                and closing_indices == [len(self._proc_samples) - 1]
                and all(
                    sample.get("probe_role") == ORDINARY_PROC_PROBE_ROLE
                    for sample in self._proc_samples[:-1]
                )
                and self._proc_samples[-1].get("coverage_close_ownership_empty")
                is True
                and self._proc_samples[-1].get("coverage_close_recheck_proven")
                is True
                and self._proc_samples[-1].get("probe_errors") == []
                and int(
                    self._proc_samples[-1]["probe_finished_monotonic_ns"]
                )
                <= int(self.coverage_end_monotonic_ns)
            )
            if not closing_contract_proven:
                self._monitor_errors.append("CLEAN_COVERAGE_CLOSE_UNPROVEN")
                self._stop.set()
                self._probe_condition.notify_all()
                close_errors = sorted(set(self._monitor_errors))
                raise RuntimeError(
                    "CLEAN_COVERAGE_CLOSE_UNPROVEN:"
                    + "|".join(close_errors)
                )

        with self._lock:
            end_ns = int(self.coverage_end_monotonic_ns)
            proc_samples = list(self._proc_samples)
            gpu_samples = list(self._gpu_samples)
            monitor_errors = sorted(set(self._monitor_errors))
            known_owned = sorted(self._known_owned)
            active_owned = sorted(self._active_owned)
            cleanup_actions = list(self._cleanup_actions)
            ownership_discovery_history = [
                dict(event) for event in self._ownership_discovery_history
            ]
        proc_sampling = _sampling_gap_report(
            proc_samples,
            self.coverage_start_monotonic_ns,
            end_ns,
            PROC_TARGET_INTERVAL_SECONDS,
            PROC_MAX_START_GAP_SECONDS,
        )
        gpu_sampling = _sampling_gap_report(
            gpu_samples,
            self.coverage_start_monotonic_ns,
            end_ns,
            GPU_TARGET_INTERVAL_SECONDS,
            GPU_MAX_START_GAP_SECONDS,
        )
        proc_intrusions = [
            dict(row)
            for sample in proc_samples
            for row in sample.get("external_conflicting_processes", [])
        ]
        gpu_intrusions = [
            dict(row)
            for sample in gpu_samples
            for row in sample.get("external_compute_applications", [])
        ]
        stale_owned_gpu_rows = [
            dict(row)
            for sample in gpu_samples
            for row in sample.get("stale_owned_gpu_rows", [])
        ]
        intrusion_detected = bool(proc_intrusions or gpu_intrusions)
        monitor_proven = bool(
            clean
            and closing_contract_proven
            and not monitor_errors
            and proc_sampling["proven"]
            and gpu_sampling["proven"]
        )
        reason_codes: list[str] = []
        if intrusion_detected:
            reason_codes.append("MIDRUN_EXTERNAL_RESOURCE_INTRUSION")
        if not monitor_proven:
            reason_codes.append("RUNTIME_RESOURCE_MONITOR_UNPROVEN")
        receipt: dict[str, object] = {
            "schema_version": SCHEMA_VERSION,
            "experiment_id": EXPERIMENT_ID,
            "created_at_utc": _utc_now(),
            "coverage": {
                "started_at_utc": self.coverage_started_at_utc,
                "start_monotonic_ns": self.coverage_start_monotonic_ns,
                "start_semantics": "RuntimeResourceMonitor constructed immediately after supervised Popen",
                "ended_at_utc": self.coverage_ended_at_utc,
                "end_monotonic_ns": end_ns,
                "end_semantics": (
                    "supervised process group and known owned descendants empty and all probe reservations settled"
                    if clean
                    else "forced monitor finalization before clean coverage closure was proven"
                ),
                "duration_seconds": (end_ns - self.coverage_start_monotonic_ns) / 1e9,
                "process_group_empty": clean,
            },
            "supervised_process": {
                "pid": self.pid,
                "leader_identity": (
                    None
                    if self.leader_identity is None
                    else {"pid": self.leader_identity[0], "start_ticks": self.leader_identity[1]}
                ),
                "leader_process_record_at_monitor_start": self.leader_record,
                "pgid": self.pgid,
                "supervisor_pid": self.supervisor_pid,
                "returncode": self.process.returncode,
                "known_owned_identity_history": [
                    {"pid": pid, "start_ticks": start} for pid, start in known_owned
                ],
                "ownership_discovery_history": ownership_discovery_history,
                "active_owned_identities_at_finalize": [
                    {"pid": pid, "start_ticks": start} for pid, start in active_owned
                ],
            },
            "sampling_contract": {
                "proc": proc_sampling,
                "gpu": gpu_sampling,
            },
            "probe_errors": monitor_errors,
            "pre_samples": {
                "proc": proc_samples[0] if proc_samples else None,
                "gpu": gpu_samples[0] if gpu_samples else None,
            },
            "post_samples": {
                "proc": proc_samples[-1] if proc_samples else None,
                "gpu": gpu_samples[-1] if gpu_samples else None,
            },
            "samples": {"proc": proc_samples, "gpu": gpu_samples},
            "observed_intrusions": {
                "proc_occurrences": proc_intrusions,
                "gpu_occurrences": gpu_intrusions,
                "stale_owned_gpu_rows": stale_owned_gpu_rows,
                "external_gpu_todesk_exemption": False,
            },
            "cleanup_actions": cleanup_actions,
            "intrusion_detected": intrusion_detected,
            "monitor_proven": monitor_proven,
            "pipeline_valid": not reason_codes,
            "pipeline_failure_reasons": reason_codes,
            "required_attempt_classification": (
                "PIPELINE_INVALID" if reason_codes else "NO_RESOURCE_MONITOR_INVALIDATION"
            ),
            "runtime_measurements_eligible_for_performance_claims": False,
        }
        _write_exclusive(self.output_path, receipt)
        with self._lock:
            self._final_receipt = receipt
        return receipt


__all__ = [
    "CLOSING_PROC_PROBE_ROLE",
    "EXPERIMENT_ID",
    "GPU_MAX_START_GAP_SECONDS",
    "GPU_TARGET_INTERVAL_SECONDS",
    "ORDINARY_PROC_PROBE_ROLE",
    "PROC_MAX_START_GAP_SECONDS",
    "PROC_TARGET_INTERVAL_SECONDS",
    "RuntimeResourceMonitor",
    "resource_gate",
]
