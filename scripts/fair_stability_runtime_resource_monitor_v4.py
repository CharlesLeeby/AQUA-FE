#!/usr/bin/python3
"""Continuous resource-exclusivity evidence for fair-stability v4 runs.

The runner must construct :class:`RuntimeResourceMonitor` immediately after
its single supervised ``Popen``.  Monitoring is observational: an intrusion is
recorded and invalidates the attempt, but never terminates the estimator.
Lifecycle methods keep sampling active through normal wait/timeout cleanup and
until the supervised process group and all known owned descendants are empty.
"""

from __future__ import annotations

import csv
from datetime import datetime, timezone
import errno
import hashlib
import json
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


SCHEMA_VERSION = "aqua-fe-fair-stability-runtime-resource-monitor-v4"
EXPERIMENT_ID = "fair-stability-positive-roster-openloop-runtimeexcl-v4"
PROC_TARGET_INTERVAL_SECONDS = 0.20
PROC_MAX_START_GAP_SECONDS = 0.25
GPU_TARGET_INTERVAL_SECONDS = 0.75
GPU_MAX_START_GAP_SECONDS = 1.00
GPU_QUERY_TIMEOUT_SECONDS = 0.65
MIN_EXPERIMENT_FREE_BYTES = 5 * 1024**3
MIN_WORKSPACE_FREE_BYTES = 512 * 1024**2

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
        return None, []
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
    if isinstance(cmdline, Sequence) and not isinstance(cmdline, (str, bytes)):
        names.update(Path(str(token)).name.lower() for token in cmdline)
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
        return {
            "returncode": None,
            "stdout": error.stdout or "",
            "stderr": error.stderr or "",
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
    active_owned_pids = {pid for pid, _start in active_owned}
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
            exact_group = owned_pgid is not None and int(proc["pgid"]) == owned_pgid
            direct_descendant = int(proc["ppid"]) in active_owned_pids
            if (
                identity in active_owned
                or identity in known_owned
                or exact_group
                or direct_descendant
            ):
                row["classification"] = "CURRENT_EXACT_KNOWN_OWNED_GPU_PROCESS"
                current_owned.append(row)
                discovered_owned.append(
                    {"pid": identity[0], "start_ticks": identity[1]}
                )
                continue
            row["classification"] = "EXTERNAL_GPU_PROCESS_EXACT_IDENTITY_NOT_OWNED"
        elif isinstance(pid, int) and pid in known_by_pid:
            row["classification"] = "STALE_OWNED_GPU_ROW_PROC_ABSENT"
            row["known_owned_start_ticks_for_pid"] = sorted(known_by_pid[pid])
            stale_owned.append(row)
            continue
        else:
            row["classification"] = "EXTERNAL_GPU_PROCESS_PROC_IDENTITY_UNPROVEN"
        # Deliberately no ToDesk or desktop-process exemption in v4.
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
    """Run the strict v4 pre-start exclusivity gate.

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
        "schema_version": "aqua-fe-fair-stability-prestart-resource-gate-v4",
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


def _sampling_gap_report(
    samples: Sequence[Mapping[str, object]],
    coverage_start_ns: int,
    coverage_end_ns: int,
    target_seconds: float,
    maximum_seconds: float,
) -> dict[str, object]:
    starts = [int(sample["probe_started_monotonic_ns"]) for sample in samples]
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
        "proven": bool(samples) and not violations and not tail_violation,
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
        self._stop = threading.Event()
        self._proc_samples: list[dict[str, object]] = []
        self._gpu_samples: list[dict[str, object]] = []
        self._monitor_errors: list[str] = []
        # ``_known_owned`` is immutable identity history; ``_active_owned`` is
        # its currently live subset.  Keeping both is required to distinguish
        # a stale NVIDIA row from a reused numeric PID.
        self._known_owned: set[tuple[int, int]] = set()
        self._active_owned: set[tuple[int, int]] = set()
        self._latest_proc_records: list[dict[str, object]] = []
        self._cleanup_actions: list[dict[str, object]] = []
        self._final_receipt: dict[str, object] | None = None
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
        current = {_process_identity(record): record for record in records}
        alive = {identity for identity in self._active_owned if identity in current}
        alive.update(identity for identity in self._known_owned if identity in current)
        if self.pgid is not None:
            alive.update(
                identity
                for identity, record in current.items()
                if int(record["pgid"]) == self.pgid
            )
        changed = True
        while changed:
            changed = False
            owned_pids = {pid for pid, _start in alive}
            for identity, record in current.items():
                if identity not in alive and int(record["ppid"]) in owned_pids:
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
            if self.process.returncode is None or not self._owned_empty(records):
                return False
            self.coverage_end_monotonic_ns = time.monotonic_ns()
            self.coverage_ended_at_utc = _utc_now()
            self._stop.set()
            return True

    def _proc_probe(self, sequence: int) -> dict[str, object]:
        started_ns = time.monotonic_ns()
        started_utc = _utc_now()
        records, errors = _scan_processes()
        with self._lock:
            owned = self._refresh_owned(records)
            self._latest_proc_records = [dict(record) for record in records]
            conflicts = _external_process_conflicts(
                records, owned, {self.supervisor_pid, os.getpid()}
            )
        finished_ns = time.monotonic_ns()
        sample: dict[str, object] = {
            "sequence": sequence,
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
            "process_group_members": sorted(
                int(record["pid"])
                for record in records
                if self.pgid is not None and int(record["pgid"]) == self.pgid
            ),
            "external_conflicting_processes": conflicts,
            "probe_errors": errors,
        }
        return sample

    def _gpu_probe(self, sequence: int) -> dict[str, object]:
        started_ns = time.monotonic_ns()
        started_utc = _utc_now()
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
        return {
            "sequence": sequence,
            "probe_started_at_utc": started_utc,
            "probe_started_monotonic_ns": started_ns,
            "probe_finished_monotonic_ns": finished_ns,
            "duration_seconds": (finished_ns - started_ns) / 1e9,
            "query_returncode": query.get("returncode"),
            "query_stderr": query.get("stderr"),
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
            try:
                sample = self._proc_probe(sequence)
            except BaseException as error:  # evidence must survive unexpected probe faults
                now_ns = time.monotonic_ns()
                sample = {
                    "sequence": sequence,
                    "probe_started_at_utc": _utc_now(),
                    "probe_started_monotonic_ns": now_ns,
                    "probe_finished_monotonic_ns": now_ns,
                    "duration_seconds": 0.0,
                    "process_count": None,
                    "owned_identities": [],
                    "supervised_pgid": self.pgid,
                    "process_group_members": [],
                    "external_conflicting_processes": [],
                    "probe_errors": [f"PROC_PROBE_EXCEPTION:{type(error).__name__}:{error}"],
                }
            with self._lock:
                self._proc_samples.append(sample)
                self._monitor_errors.extend(str(value) for value in sample["probe_errors"])
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
            try:
                sample = self._gpu_probe(sequence)
            except BaseException as error:  # evidence must survive unexpected probe faults
                now_ns = time.monotonic_ns()
                sample = {
                    "sequence": sequence,
                    "probe_started_at_utc": _utc_now(),
                    "probe_started_monotonic_ns": now_ns,
                    "probe_finished_monotonic_ns": now_ns,
                    "duration_seconds": 0.0,
                    "query_returncode": None,
                    "query_stderr": "",
                    "compute_applications": [],
                    "external_compute_applications": [],
                    "stale_owned_gpu_rows": [],
                    "current_owned_gpu_rows": [],
                    "discovered_owned_identities": [],
                    "external_gpu_todesk_exemption": False,
                    "probe_errors": [f"GPU_PROBE_EXCEPTION:{type(error).__name__}:{error}"],
                }
            with self._lock:
                self._gpu_samples.append(sample)
                self._monitor_errors.extend(str(value) for value in sample["probe_errors"])
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
        if self.process.poll() is not None:
            errors.append("SUPERVISED_LEADER_ALREADY_EXITED")
        if self.pgid != self.pid or self.leader_identity is None:
            errors.append("SUPERVISED_LEADER_PGID_OR_IDENTITY_INVALID")
        group = [
            record
            for record in records
            if self.pgid is not None and int(record["pgid"]) == self.pgid
        ]
        leaders = [record for record in group if int(record["pid"]) == self.pid]
        if len(leaders) != 1:
            errors.append(f"EXACT_GROUP_LEADER_COUNT:{len(leaders)}")
        elif (
            _process_identity(leaders[0]) != self.leader_identity
            or int(leaders[0]["pgid"]) != self.pid
            or int(leaders[0]["session"]) != self.pid
            or leaders[0].get("executable") != expected_executable
            or list(leaders[0].get("cmdline", []))
            != [str(value) for value in expected_argv]
        ):
            errors.append("EXACT_GROUP_LEADER_IDENTITY_OR_ARGV_MISMATCH")
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
            immutable = (
                "pid", "start_ticks", "pgid", "session", "executable",
                "cmdline_sha256", "cmdline",
            )
            if current is None or any(
                current.get(key) != record.get(key) for key in immutable
            ):
                errors.append(f"GROUP_MEMBER_IDENTITY_RECHECK_MISMATCH:{pid}")
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
                    "executable": current.get("executable"),
                    "cmdline_sha256": current.get("cmdline_sha256"),
                }
            )
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
            "expected_argv": [str(value) for value in expected_argv],
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
        sample_started_monotonic: float,
        maximum_observation_gap_seconds: float,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> dict[str, object]:
        """Attempt SIGTERM once after two proofs and before the fixed deadline."""
        if self._watchdog_signal_attempted:
            return {
                "signal_attempted": False,
                "signal_sent": False,
                "errors": ["WATCHDOG_SIGNAL_ALREADY_ATTEMPTED"],
            }
        self._watchdog_signal_attempted = True
        first = self.watchdog_exact_group_snapshot(
            expected_executable, expected_argv
        )
        second = self.watchdog_exact_group_snapshot(
            expected_executable, expected_argv
        )
        first_members = first.get("members")
        second_members = second.get("members")
        errors = [
            *[str(value) for value in first.get("errors", [])],
            *[str(value) for value in second.get("errors", [])],
        ]
        if first.get("proven") is not True or second.get("proven") is not True:
            errors.append("FINAL_EXACT_GROUP_PROOF_FAILED")
        if (
            not isinstance(first_members, list)
            or not first_members
            or first_members != second_members
        ):
            errors.append("FINAL_EXACT_GROUP_MEMBERSHIP_CHANGED")
        leader_returncode = self.process.poll()
        pre_signal_monotonic = float(monotonic())
        if pre_signal_monotonic >= float(deadline_monotonic):
            errors.append("WATCHDOG_DEADLINE_REACHED_BEFORE_SIGNAL")
        if (
            pre_signal_monotonic - float(sample_started_monotonic)
            > float(maximum_observation_gap_seconds)
        ):
            errors.append("WATCHDOG_POLL_WINDOW_EXCEEDED_BEFORE_SIGNAL")
        sent = False
        signal_error: str | None = None
        if not errors and self.pgid == self.pid and leader_returncode is None:
            try:
                os.killpg(self.pid, signal.SIGTERM)
                sent = True
            except OSError as error:
                signal_error = f"{type(error).__name__}:{error.errno}"
                errors.append(f"WATCHDOG_KILLPG_FAILED:{error.errno}")
        elif leader_returncode is not None:
            errors.append("LEADER_EXITED_BEFORE_WATCHDOG_SIGNAL")
        action = {
            "at_utc": _utc_now(),
            "monotonic_ns": time.monotonic_ns(),
            "deadline_monotonic": float(deadline_monotonic),
            "sample_started_monotonic": float(sample_started_monotonic),
            "maximum_observation_gap_seconds": float(
                maximum_observation_gap_seconds
            ),
            "pre_signal_monotonic": pre_signal_monotonic,
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
        safe_group_member = False
        if self.pgid == self.pid and group_members:
            for record in group_members:
                identity = _process_identity(record)
                current, recheck_errors = _read_process_record(identity[0])
                for error in recheck_errors:
                    self._append_error(
                        f"OWNED_GROUP_IDENTITY_RECHECK_FAILED:{identity[0]}:{error}"
                    )
                if (
                    current is not None
                    and _process_identity(current) == identity
                    and int(current["pgid"]) == self.pgid
                    and identity in owned
                ):
                    safe_group_member = True
                    break
        if self.pgid == self.pid and safe_group_member:
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
                if self.coverage_end_monotonic_ns is None:
                    self.coverage_end_monotonic_ns = time.monotonic_ns()
                    self.coverage_ended_at_utc = _utc_now()
                self._stop.set()
        self._proc_thread.join(timeout=3.0)
        self._gpu_thread.join(timeout=3.0)
        if self._proc_thread.is_alive():
            self._append_error("PROC_MONITOR_THREAD_DID_NOT_STOP")
        if self._gpu_thread.is_alive():
            self._append_error("GPU_MONITOR_THREAD_DID_NOT_STOP")

        with self._lock:
            end_ns = int(self.coverage_end_monotonic_ns or time.monotonic_ns())
            proc_samples = list(self._proc_samples)
            gpu_samples = list(self._gpu_samples)
            monitor_errors = sorted(set(self._monitor_errors))
            known_owned = sorted(self._known_owned)
            active_owned = sorted(self._active_owned)
            cleanup_actions = list(self._cleanup_actions)
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
                    "supervised process group and known owned descendants empty"
                    if clean
                    else "forced monitor finalization before ownership domain was proven empty"
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
    "EXPERIMENT_ID",
    "GPU_MAX_START_GAP_SECONDS",
    "GPU_TARGET_INTERVAL_SECONDS",
    "PROC_MAX_START_GAP_SECONDS",
    "PROC_TARGET_INTERVAL_SECONDS",
    "RuntimeResourceMonitor",
    "resource_gate",
]
