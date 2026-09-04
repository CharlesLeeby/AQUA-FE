#!/usr/bin/env python3
"""PRESTART-gated one-shot full MH01 trajectory controller for SuperVINS.

The default ``prestart`` action is strictly read-only with respect to ROS and
the fresh evidence namespace.  ``run`` additionally requires a separate root
execution-authority file that is intentionally absent from this PRESTART
delivery.  No ground truth, APE/RPE, loop fusion, or comparison is performed.
"""

from __future__ import annotations

import argparse
import csv
import errno
import functools
import hashlib
import importlib.util
import json
import math
import os
import pty
import re
import select
import signal
import socket
import subprocess
import sys
import time
import traceback
import xmlrpc.client
from datetime import datetime
from pathlib import Path

import cv2


ROOT = Path("/home/ma/AQUA-FE_WS")
RUNNER_PATH = ROOT / "scripts/run_published_supervins_v1_official_euroc_mh01_full_trajectory_v1.py"
STAGE2_RUNNER = ROOT / "scripts/run_published_supervins_v1_ortsession_smoke_attempt_002.py"
SPEC = importlib.util.spec_from_file_location("supervins_stage2_attempt_002", STAGE2_RUNNER)
STAGE2 = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(STAGE2)
BASE = STAGE2.BASE

PROTOCOL = ROOT / "papers/supervins_v1_official_euroc_mh01_full_trajectory_prestart_freeze_v1.json"
LOCK = ROOT / "papers/supervins_v1_official_euroc_mh01_full_trajectory_execution_lock_v1.json"
TESTS = ROOT / "scripts/tests/test_run_published_supervins_v1_official_euroc_mh01_full_trajectory_v1.py"
AUTHORITY = ROOT / "papers/supervins_v1_official_euroc_mh01_full_trajectory_execution_authority_v1.json"
MANIFEST = ROOT / "papers/supervins_v1_official_euroc_mh01_full_input_manifest_v1.json"
PUBLISHER = ROOT / "scripts/publish_supervins_euroc_mh01_full_v1.py"
ADAPTED_CONFIG = ROOT / "papers/supervins_v1_official_euroc_mh01_full_trajectory_config_v1/euroc_mono_imu_config.yaml"
ADAPTED_CALIB = ADAPTED_CONFIG.parent / "cam0_mei.yaml"
ORIGINAL_CONFIG = BASE.CONFIG
ORIGINAL_CALIB = BASE.PRIVATE / "config/euroc/cam0_mei.yaml"
STAGE2_FREEZE = ROOT / "papers/supervins_v1_ortsession_construction_smoke_freeze_v1.json"

EVIDENCE = ROOT / "experiments/published_supervins_v1_official_euroc_mh01_full_trajectory_20260817_r1"
ATTEMPT = EVIDENCE / "attempt_001"
NODE_CWD = EVIDENCE
TRAJECTORY_DIR = ATTEMPT / "trajectory_output"
TRAJECTORY = TRAJECTORY_DIR / "vio.csv"
EXTRINSIC = TRAJECTORY_DIR / "extrinsic_parameter.csv"
BACKEND_TIMES = EVIDENCE / "time_consumption/backend_optimization.txt"
FEATURE_TIMES = EVIDENCE / "time_consumption/feature_extraction_matching.txt"
DURATION_TIMES = EVIDENCE / "duration.txt"
PROJECT_SOURCE_DIR = Path("/home/ma/SLAM/SuperVINS-v1-devrepair-ws-20260816-r1/src")
CONFIGURED_OUTPUT_PATH = "../../../AQUA-FE_WS/experiments/published_supervins_v1_official_euroc_mh01_full_trajectory_20260817_r1/attempt_001/trajectory_output"

MASTER_HOST = "127.0.0.1"
MASTER_PORT = 11555
MASTER_URI = "http://127.0.0.1:11555"
MASTER_COMMAND = ["/opt/ros/noetic/bin/roscore", "-p", "11555"]
NODE_COMMAND = [str(BASE.BINARY), str(ADAPTED_CONFIG)]
PUBLISHER_COMMAND = [
    "/usr/bin/python3", "-B", str(PUBLISHER), "--action", "run",
    "--authorization-token", "SUPERVINS_STAGE4_MH01_FULL_PUBLISH_ONCE",
]
PUBLISHER_PREFLIGHT_COMMAND = ["/usr/bin/python3", "-B", str(PUBLISHER), "--action", "preflight"]
AUTHORIZATION_TOKEN = "SUPERVINS_STAGE4_MH01_FULL_TRAJECTORY_ATTEMPT_001_START_ONCE"
AUTHORIZATION_TOKEN_SHA256 = hashlib.sha256(AUTHORIZATION_TOKEN.encode()).hexdigest()
CONTROLLER_COMMAND = [
    "/usr/bin/python3", "-B", str(RUNNER_PATH), "--action", "run",
    "--authorization-token", AUTHORIZATION_TOKEN,
]
CALLER_ID = "/aqua_fe_supervins_full_trajectory_controller"
NODE_NAME = "/supervins_estimator"
PUBLISHER_NODE = "/aqua_fe_euroc_mh01_full_publisher"
INPUT_TOPICS = ["/imu0", "/cam0/image_raw"]
OUTPUT_TOPICS = ["/supervins_estimator/odometry", "/supervins_estimator/path"]

CAMERA_COUNT = 3682
IMU_COUNT = 36820
EVENT_COUNT = 40502
BACKEND_COUNT = 1841
LAST_CAMERA_SECONDS = 1403636763813555456 / 1e9
LAST_CAMERA_FIXED6_TEXT = f"{LAST_CAMERA_SECONDS:.6f}"
SESSION_MARKER = "waiting for image and imu..."
INIT_MARKER = "Initialization finish!"
EXTRACT_MARKER = "extract feature time"
MATCH_RE = re.compile(r"matches\.size\(\)\s*=\s*(-?\d+)", re.IGNORECASE)
FRAME_TIMESTAMP_RE = re.compile(rb"(?m)^(1[0-9]{9}\.[0-9]{9})\r?$")
FRAME_TIMESTAMP_SHA256 = "b7e4e9b485f86d7af386d67affa2b40d1f63698e0562a6b4d30f89b9a77e5dfe"
EVEN_FRAME_TIMESTAMP_SHA256 = "6da29c0921ba91d269610da981268d6f9a24dc47c6d2880d8a432eec57001bd9"
FIRST_FRAME_TIMESTAMP_TEXT = "1403636579.763555527"
LAST_FRAME_TIMESTAMP_TEXT = "1403636763.813555479"
FIRST_EVENT_NS = 1403636579758555392
LAST_EVENT_NS = 1403636763853555456
SOURCE_SPAN_SECONDS = (LAST_EVENT_NS - FIRST_EVENT_NS) / 1e9
EXPECTED_WALL_PUBLISH_SPAN_SECONDS = SOURCE_SPAN_SECONDS / 0.2
CAMERA_CSV = Path("/mnt/data/AQUA-FE_WS/datasets/official_euroc_v1/MH01/MH_01_easy/mav0/cam0/data.csv")

MASTER_READY_TIMEOUT = 12.0
NODE_READY_TIMEOUT = 15.0
SUBSCRIPTION_TIMEOUT = 12.0
PUBLISHER_REGISTRATION_TIMEOUT = 120.0
PUBLISHER_COMPLETION_TIMEOUT = 1200.0
DRAIN_TIMEOUT = 300.0
TERM_GRACE_SECONDS = 3.0
PASS_STATUS = "PASS_DEVELOPMENT_OFFICIAL_MH01_FULL_TRAJECTORY_GENERATION"

ACTIVE_PROCESSES = {"roscore": None, "node": None, "publisher": None}
RUN_GUARD_STATE = {
    "namespace_owned": False,
    "starts": {"roscore_start_count": 0, "node_start_count": 0, "publisher_start_count": 0},
    "terminal_result_committed": False,
    "terminal_return_code": None,
}
CONTROLLED_SIGNALS = tuple(sig for sig in (signal.SIGTERM, signal.SIGHUP, signal.SIGINT) if sig is not None)
TERMINATION_SIGNAL_STATE = {"in_progress": False, "pending_signum": None}


class ControlledTermination(BaseException):
    def __init__(self, signum):
        self.signum = signum
        super().__init__(f"controlled_termination_signal:{signum}:{signal.Signals(signum).name}")


def raise_controlled_termination(signum, _frame):
    if TERMINATION_SIGNAL_STATE["in_progress"]:
        return
    if TERMINATION_SIGNAL_STATE["pending_signum"] is None:
        TERMINATION_SIGNAL_STATE["pending_signum"] = signum


def raise_if_termination_pending():
    pending_signum = TERMINATION_SIGNAL_STATE["pending_signum"]
    if pending_signum is None or TERMINATION_SIGNAL_STATE["in_progress"]:
        return
    TERMINATION_SIGNAL_STATE["pending_signum"] = None
    TERMINATION_SIGNAL_STATE["in_progress"] = True
    raise ControlledTermination(pending_signum)


def tracked_popen(process_name, start_count_key, command, **kwargs):
    raise_if_termination_pending()
    proc = subprocess.Popen(command, **kwargs)
    ACTIVE_PROCESSES[process_name] = proc
    RUN_GUARD_STATE["starts"][start_count_key] = 1
    raise_if_termination_pending()
    return proc


def create_owned_evidence_root(path):
    raise_if_termination_pending()
    path.mkdir(mode=0o755, parents=False, exist_ok=False)
    RUN_GUARD_STATE["namespace_owned"] = True
    raise_if_termination_pending()


def now_iso():
    return datetime.now().astimezone().isoformat(timespec="seconds")


def sha256_file(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def file_identity(path):
    path = Path(path)
    return {"sha256": sha256_file(path), "size_bytes": path.stat().st_size}


def check_identity(path, expected):
    try:
        observed = file_identity(path)
        return observed == expected, observed
    except OSError as exc:
        return False, {"error": type(exc).__name__ + ":" + str(exc)[:500]}


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def canonical_json_bytes(value):
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def emit_json(value):
    try:
        print(json.dumps(value, sort_keys=True))
        return True
    except (BrokenPipeError, OSError):
        return False


def write_json_exclusive(path, value, mode=0o444):
    path = Path(path)
    payload = canonical_json_bytes(value)
    fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode)
    try:
        offset = 0
        while offset < len(payload):
            offset += os.write(fd, payload[offset:])
        os.fsync(fd)
    finally:
        try:
            os.close(fd)
        except OSError:
            pass
    return {"sha256": hashlib.sha256(payload).hexdigest(), "size_bytes": len(payload)}


def runtime_environment(ros_home):
    env = BASE.runtime_environment(ros_home)
    attempt_root = Path(ros_home).parent
    env.update({
        "ROS_MASTER_URI": MASTER_URI,
        "ROS_HOSTNAME": MASTER_HOST,
        "ROS_HOME": str(ros_home),
        "ROS_LOG_DIR": str(Path(ros_home) / "log"),
        "CUDA_CACHE_PATH": str(attempt_root / "runtime_cache/cuda"),
        "XDG_CACHE_HOME": str(attempt_root / "runtime_cache/xdg"),
        "TMPDIR": str(attempt_root / "runtime_cache/tmp"),
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONUNBUFFERED": "1",
    })
    return env


def port_is_bound():
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(0.2)
    try:
        return sock.connect_ex((MASTER_HOST, MASTER_PORT)) == 0
    finally:
        sock.close()


def is_master_cmdline(parts):
    names = {Path(part).name for part in parts[:3]}
    return "11555" in parts and bool(names & {"roscore", "rosmaster", "roslaunch"})


def relevant_processes():
    found = []
    publisher_path = str(PUBLISHER)
    for path in Path("/proc").glob("[0-9]*/cmdline"):
        try:
            parts = [part.decode("utf-8", "replace") for part in path.read_bytes().split(b"\0") if part]
        except OSError:
            continue
        names = {Path(part).name for part in parts[:3]}
        attempt_scoped = any(str(EVIDENCE) in part for part in parts)
        if publisher_path in parts or "supervins_node" in names or is_master_cmdline(parts) or attempt_scoped:
            found.append({"pid": int(path.parent.name), "argv": parts})
    return sorted(found, key=lambda item: item["pid"])


def master_call(method):
    previous = socket.getdefaulttimeout()
    socket.setdefaulttimeout(0.6)
    try:
        proxy = xmlrpc.client.ServerProxy(MASTER_URI, allow_none=True)
        return getattr(proxy, method)(CALLER_ID)
    finally:
        socket.setdefaulttimeout(previous)


def master_ready():
    try:
        response = master_call("getUri")
        return isinstance(response, (list, tuple)) and len(response) == 3 and response[0] == 1
    except (OSError, socket.timeout, xmlrpc.client.Error):
        return False


def parse_system_state(response):
    if not isinstance(response, (list, tuple)) or len(response) != 3 or response[0] != 1:
        raise ValueError("invalid getSystemState response")
    labels = ("publishers", "subscribers", "services")
    parsed = {label: {topic: sorted(nodes) for topic, nodes in entries} for label, entries in zip(labels, response[2])}
    nodes = sorted({node for group in parsed.values() for values in group.values() for node in values})
    return {
        "state": parsed,
        "nodes": nodes,
        "input_publishers": {topic: parsed["publishers"].get(topic, []) for topic in INPUT_TOPICS if parsed["publishers"].get(topic)},
        "input_subscribers": {topic: parsed["subscribers"].get(topic, []) for topic in INPUT_TOPICS if parsed["subscribers"].get(topic)},
        "trajectory_publishers": {topic: parsed["publishers"].get(topic, []) for topic in OUTPUT_TOPICS if parsed["publishers"].get(topic)},
    }


def get_system_state():
    try:
        return {"ok": True, **parse_system_state(master_call("getSystemState"))}
    except (OSError, socket.timeout, xmlrpc.client.Error, ValueError) as exc:
        return {"ok": False, "error": type(exc).__name__ + ":" + str(exc)[:500]}


def subscriptions_ready(state):
    return bool(
        state and state.get("ok")
        and all(state["input_subscribers"].get(topic) == [NODE_NAME] for topic in INPUT_TOPICS)
        and not state["input_publishers"]
        and all(state["trajectory_publishers"].get(topic) == [NODE_NAME] for topic in OUTPUT_TOPICS)
    )


def publisher_graph_ready(state):
    return bool(
        state and state.get("ok")
        and all(state["input_subscribers"].get(topic) == [NODE_NAME] for topic in INPUT_TOPICS)
        and all(state["input_publishers"].get(topic) == [PUBLISHER_NODE] for topic in INPUT_TOPICS)
        and all(state["trajectory_publishers"].get(topic) == [NODE_NAME] for topic in OUTPUT_TOPICS)
    )


def new_graph_monitor():
    return {
        "sample_count": 0,
        "ready_count": 0,
        "unavailable_count": 0,
        "identity_violation_count": 0,
        "process_liveness_violation_count": 0,
        "first_state": None,
        "last_state": None,
        "violation_examples": [],
    }


def update_graph_monitor(monitor, state, master_alive, node_alive):
    monitor["sample_count"] += 1
    monitor["first_state"] = monitor["first_state"] or state
    monitor["last_state"] = state
    if not state or not state.get("ok"):
        monitor["unavailable_count"] += 1
        reason = "master_state_unavailable"
    elif not publisher_graph_ready(state):
        monitor["identity_violation_count"] += 1
        reason = "topic_identity_violation"
    else:
        monitor["ready_count"] += 1
        reason = None
    if not master_alive or not node_alive:
        monitor["process_liveness_violation_count"] += 1
        reason = reason or "master_or_node_not_alive"
    if reason and len(monitor["violation_examples"]) < 3:
        monitor["violation_examples"].append({
            "reason": reason,
            "master_alive": bool(master_alive),
            "node_alive": bool(node_alive),
            "state": state,
        })
    return reason is None


def update_quiescence(previous_snapshot, stable_since, current_snapshot, now, minimum_stable_seconds=1.0):
    if current_snapshot != previous_snapshot:
        return current_snapshot, now, False
    if stable_since is None:
        return current_snapshot, now, False
    return current_snapshot, stable_since, now - stable_since >= minimum_stable_seconds


def poll_state(predicate, timeout_seconds, interval=0.05):
    started = time.monotonic()
    deadline = started + timeout_seconds
    states = []
    while time.monotonic() < deadline:
        raise_if_termination_pending()
        state = get_system_state()
        states.append(state)
        if predicate(state):
            return {"ready": True, "elapsed_seconds": time.monotonic() - started, "poll_count": len(states), "state": state}
        time.sleep(interval)
    return {"ready": False, "elapsed_seconds": time.monotonic() - started, "poll_count": len(states), "state": states[-1] if states else None}


def terminate_and_reap(proc):
    events = []
    if proc is None:
        return {"events": events, "returncode": None, "sigkill_used": False, "reaped": True}
    try:
        running = proc.poll() is None
    except Exception as exc:
        running = True
        events.append({"at": now_iso(), "event": "POLL_DIAGNOSTIC_FAILED_ASSUME_RUNNING", "error": type(exc).__name__ + ":" + str(exc)[:500]})
    if running:
        try:
            os.killpg(proc.pid, signal.SIGTERM)
            events.append({"at": now_iso(), "signal": "SIGTERM_PROCESS_GROUP"})
        except Exception as exc:
            events.append({"at": now_iso(), "signal": "SIGTERM_NOT_DELIVERED", "error": type(exc).__name__})
    try:
        rc = proc.wait(timeout=TERM_GRACE_SECONDS)
        events.append({"at": now_iso(), "event": "REAPED_AFTER_TERM_OR_PRIOR_EXIT"})
        return {"events": events, "returncode": rc, "sigkill_used": False, "reaped": True}
    except subprocess.TimeoutExpired:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
            events.append({"at": now_iso(), "signal": "SIGKILL_PROCESS_GROUP"})
        except Exception as exc:
            events.append({"at": now_iso(), "signal": "SIGKILL_NOT_DELIVERED", "error": type(exc).__name__})
        try:
            rc = proc.wait(timeout=5)
            events.append({"at": now_iso(), "event": "REAPED_AFTER_KILL"})
            return {"events": events, "returncode": rc, "sigkill_used": True, "reaped": True}
        except (subprocess.TimeoutExpired, OSError) as exc:
            events.append({"at": now_iso(), "event": "REAP_FAILED_AFTER_KILL", "error": type(exc).__name__ + ":" + str(exc)[:500]})
            try:
                returncode = proc.poll()
            except Exception:
                returncode = None
            return {"events": events, "returncode": returncode, "sigkill_used": True, "reaped": False}
    except OSError as exc:
        events.append({"at": now_iso(), "event": "REAP_OSERROR", "error": type(exc).__name__ + ":" + str(exc)[:500]})
        try:
            returncode = proc.poll()
        except Exception:
            returncode = None
        return {"events": events, "returncode": returncode, "sigkill_used": False, "reaped": False}


def drain_pty(master_fds, streams, buffers, wait_seconds=0.0):
    if not master_fds:
        return
    readable, _, _ = select.select(master_fds, [], [], wait_seconds)
    for fd in list(readable):
        try:
            chunk = os.read(fd, 65536)
        except OSError as exc:
            if exc.errno == errno.EIO:
                master_fds.remove(fd)
                continue
            raise
        if not chunk:
            master_fds.remove(fd)
            continue
        streams[fd].write(chunk)
        streams[fd].flush()
        buffers[fd].extend(chunk)


def classify_node_output(stdout_bytes, stderr_bytes):
    combined = stdout_bytes + b"\n" + stderr_bytes
    text = combined.decode("utf-8", "replace")
    values = [int(value) for value in MATCH_RE.findall(text)]
    frame_timestamps = [value.decode("ascii") for value in FRAME_TIMESTAMP_RE.findall(combined)]
    frame_payload = "".join(value + "\n" for value in frame_timestamps).encode("ascii")
    even_payload = "".join(value + "\n" for value in frame_timestamps[1::2]).encode("ascii")
    lower = text.lower()
    return {
        "session_marker_count": lower.count(SESSION_MARKER.lower()),
        "extract_feature_time_count": lower.count(EXTRACT_MARKER.lower()),
        "matches_size_count": len(values),
        "matches_size_values": values,
        "initialization_finish_count": lower.count(INIT_MARKER.lower()),
        "failure_detection_count": lower.count("failure detection!"),
        "system_reboot_count": lower.count("system reboot!"),
        "frame_timestamp_count": len(frame_timestamps),
        "frame_timestamp_first": frame_timestamps[0] if frame_timestamps else None,
        "frame_timestamp_last": frame_timestamps[-1] if frame_timestamps else None,
        "frame_timestamp_sha256_lf": hashlib.sha256(frame_payload).hexdigest(),
        "even_frame_timestamp_count": len(frame_timestamps[1::2]),
        "even_frame_timestamp_sha256_lf": hashlib.sha256(even_payload).hexdigest(),
    }


def parse_json_lines(path):
    records = []
    if not Path(path).exists():
        return records
    for line in Path(path).read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            records.append(value)
    return records


def count_finite_timing_rows(path):
    if not Path(path).exists():
        return {"exists": False, "line_count": 0, "all_finite_nonnegative": False}
    values = []
    invalid = []
    for index, line in enumerate(Path(path).read_text(encoding="utf-8", errors="replace").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            value = float(line.strip())
        except ValueError:
            invalid.append(index)
            continue
        values.append(value)
        if not math.isfinite(value) or value < 0:
            invalid.append(index)
    return {"exists": True, "line_count": len(values), "invalid_lines": invalid, "all_finite_nonnegative": not invalid}


@functools.lru_cache(maxsize=1)
def expected_camera_rows():
    with CAMERA_CSV.open("r", encoding="utf-8", newline="") as stream:
        rows = [row for row in csv.reader(stream) if row and not row[0].startswith("#")]
    return tuple((index, int(row[0]), row[1]) for index, row in enumerate(rows))


@functools.lru_cache(maxsize=1)
def expected_even_camera_timestamp_sequence_fixed6():
    return tuple(f"{timestamp_ns / 1e9:.6f}" for index, timestamp_ns, _ in expected_camera_rows() if index % 2 == 1)


def publisher_camera_sequence_audit(records):
    expected = expected_camera_rows()
    observed = tuple((record.get("index"), record.get("timestamp_ns"), record.get("filename")) for record in records)
    exact = observed == expected
    return {
        "exact": exact,
        "record_count": len(observed),
        "expected_count": len(expected),
        "first": list(observed[0]) if observed else None,
        "last": list(observed[-1]) if observed else None,
        "every_record_has_decoded_sha256": all(
            isinstance(record.get("decoded_sha256"), str) and re.fullmatch(r"[0-9a-f]{64}", record["decoded_sha256"])
            for record in records
        ),
    }


def trajectory_audit(path=TRAJECTORY, enforce_even_camera_membership=False):
    result = {
        "exists": Path(path).exists(), "valid_row_count": 0, "invalid_lines": [],
        "timestamps_strictly_increasing": False, "all_values_finite": False,
        "quaternion_norm_in_range": False, "timestamps_are_even_camera_subset": False, "first_timestamp": None,
        "timestamps_are_contiguous_even_camera_suffix": False, "timestamp_text_format_fixed6": False,
        "last_timestamp": None, "last_timestamp_text": None, "source_span_seconds": None, "tail_gap_seconds": None,
    }
    if not result["exists"]:
        return result
    rows = []
    timestamp_texts = []
    for index, line in enumerate(Path(path).read_text(encoding="utf-8", errors="replace").splitlines(), start=1):
        if not line.strip():
            continue
        parts = line.split()
        if len(parts) != 8:
            result["invalid_lines"].append(index)
            continue
        try:
            values = [float(value) for value in parts]
        except ValueError:
            result["invalid_lines"].append(index)
            continue
        if not all(math.isfinite(value) for value in values):
            result["invalid_lines"].append(index)
            continue
        rows.append(values)
        timestamp_texts.append(parts[0])
    result["valid_row_count"] = len(rows)
    result["all_values_finite"] = bool(rows) and not result["invalid_lines"]
    if not rows:
        return result
    timestamps = [row[0] for row in rows]
    norms = [math.sqrt(sum(value * value for value in row[4:8])) for row in rows]
    expected_sequence = expected_even_camera_timestamp_sequence_fixed6()
    expected_set = frozenset(expected_sequence)
    timestamp_membership = all(timestamp in expected_set for timestamp in timestamp_texts)
    contiguous_suffix = len(timestamp_texts) <= len(expected_sequence) and tuple(timestamp_texts) == expected_sequence[-len(timestamp_texts):]
    result.update({
        "timestamps_strictly_increasing": all(b > a for a, b in zip(timestamps, timestamps[1:])),
        "quaternion_norm_in_range": all(0.9 <= norm <= 1.1 for norm in norms),
        "timestamps_are_even_camera_subset": timestamp_membership if enforce_even_camera_membership else True,
        "timestamps_are_contiguous_even_camera_suffix": contiguous_suffix if enforce_even_camera_membership else True,
        "timestamp_text_format_fixed6": all(re.fullmatch(r"[0-9]{10}\.[0-9]{6}", value) for value in timestamp_texts),
        "even_camera_membership_enforced": enforce_even_camera_membership,
        "quaternion_norm_min": min(norms), "quaternion_norm_max": max(norms),
        "first_timestamp": timestamps[0], "last_timestamp": timestamps[-1], "last_timestamp_text": timestamp_texts[-1],
        "source_span_seconds": timestamps[-1] - timestamps[0],
        "tail_gap_seconds": LAST_CAMERA_SECONDS - timestamps[-1],
    })
    return result


def extrinsic_audit(path=EXTRINSIC):
    result = {
        "exists": Path(path).is_file(), "size_bytes": 0, "body_T_cam0_shape": None,
        "all_values_finite": False, "last_row_max_abs_error": None,
        "rotation_orthonormal_max_abs_error": None, "rotation_determinant": None,
        "is_finite_se3": False,
    }
    if not result["exists"]:
        return result
    result["size_bytes"] = Path(path).stat().st_size
    storage = cv2.FileStorage(str(path), cv2.FILE_STORAGE_READ)
    try:
        if not storage.isOpened():
            return result
        matrix = storage.getNode("body_T_cam0").mat()
        if matrix is None:
            return result
        values = [[float(value) for value in row] for row in matrix.tolist()]
        result["body_T_cam0_shape"] = list(matrix.shape)
        result["all_values_finite"] = all(math.isfinite(value) for row in values for value in row)
        if result["body_T_cam0_shape"] == [4, 4] and result["all_values_finite"]:
            rotation = [row[:3] for row in values[:3]]
            last_row_expected = [0.0, 0.0, 0.0, 1.0]
            last_error = max(abs(value - expected) for value, expected in zip(values[3], last_row_expected))
            orthonormal_error = max(
                abs(sum(rotation[k][i] * rotation[k][j] for k in range(3)) - (1.0 if i == j else 0.0))
                for i in range(3) for j in range(3)
            )
            determinant = (
                rotation[0][0] * (rotation[1][1] * rotation[2][2] - rotation[1][2] * rotation[2][1])
                - rotation[0][1] * (rotation[1][0] * rotation[2][2] - rotation[1][2] * rotation[2][0])
                + rotation[0][2] * (rotation[1][0] * rotation[2][1] - rotation[1][1] * rotation[2][0])
            )
            result.update({
                "last_row_max_abs_error": last_error,
                "rotation_orthonormal_max_abs_error": orthonormal_error,
                "rotation_determinant": determinant,
                "is_finite_se3": last_error <= 1e-6 and orthonormal_error <= 1e-3 and abs(determinant - 1.0) <= 1e-3,
            })
    finally:
        storage.release()
    return result


CONFIG_KEYS = [
    "imu", "num_of_cam", "imu_topic", "image0_topic", "image1_topic", "cam0_calib", "cam1_calib",
    "image_width", "image_height", "estimate_extrinsic", "multiple_thread", "max_cnt", "min_dist",
    "matche_score_threshold", "ransacReprojThreshold", "freq", "F_threshold", "show_track", "flow_back",
    "max_solver_time", "max_num_iterations", "keyframe_parallax", "acc_n", "gyr_n", "acc_w", "gyr_w",
    "g_norm", "estimate_td", "td", "output_path", "load_previous_pose_graph", "pose_graph_save_path",
    "save_image", "extractor_weight_path", "matcher_weight_path", "voc_relative_path",
]


def config_semantics(path):
    storage = cv2.FileStorage(str(path), cv2.FILE_STORAGE_READ)
    if not storage.isOpened():
        raise ValueError("cannot_open_config:" + str(path))
    values = {}
    for key in CONFIG_KEYS:
        node = storage.getNode(key)
        values[key] = node.string() if node.isString() else node.real()
    matrix = storage.getNode("body_T_cam0").mat()
    values["body_T_cam0"] = matrix.tolist() if matrix is not None else None
    storage.release()
    return values


def config_delta_check():
    original = config_semantics(ORIGINAL_CONFIG)
    adapted = config_semantics(ADAPTED_CONFIG)
    changed = {key: {"original": original[key], "adapted": adapted[key]} for key in original if original[key] != adapted[key]}
    node_resolution = (NODE_CWD / CONFIGURED_OUTPUT_PATH).resolve()
    project_resolution = (PROJECT_SOURCE_DIR / CONFIGURED_OUTPUT_PATH).resolve()
    return {
        "changed": changed,
        "only_output_path_changed": set(changed) == {"output_path"},
        "adapted_output_path_exact": adapted["output_path"] == CONFIGURED_OUTPUT_PATH,
        "node_cwd_resolution": str(node_resolution),
        "project_source_resolution": str(project_resolution),
        "both_resolve_to_trajectory_dir": node_resolution == TRAJECTORY_DIR and project_resolution == TRAJECTORY_DIR,
        "calibration_byte_identical": ADAPTED_CALIB.read_bytes() == ORIGINAL_CALIB.read_bytes(),
    }


def source_state_snapshot():
    official_head = BASE.git(BASE.OFFICIAL, "rev-parse", "HEAD")
    official_tree = BASE.git(BASE.OFFICIAL, "rev-parse", "HEAD^{tree}")
    official_status = BASE.git(BASE.OFFICIAL, "status", "--porcelain=v1", "--untracked-files=all", "--ignore-submodules=none")
    private_diff = BASE.git(BASE.PRIVATE, "diff", "--no-ext-diff", "--no-color", binary=True)
    diff_bytes = private_diff["stdout"] if isinstance(private_diff["stdout"], bytes) else b""
    return {
        "official_head": official_head["stdout"].strip(),
        "official_tree": official_tree["stdout"].strip(),
        "official_status": official_status["stdout"].splitlines(),
        "private_repair_diff_sha256": hashlib.sha256(diff_bytes).hexdigest(),
    }


def expected_source_state():
    return {
        "official_head": BASE.COMMIT,
        "official_tree": BASE.TREE,
        "official_status": [],
        "private_repair_diff_sha256": BASE.DIFF_SHA256,
    }


def available_bytes(path):
    stats = os.statvfs(str(path))
    return stats.f_bavail * stats.f_frsize


def gpu_runtime_snapshot():
    memory = BASE.command([
        "nvidia-smi", "--query-gpu=index,name,memory.total,memory.free",
        "--format=csv,noheader,nounits",
    ])
    apps = BASE.command([
        "nvidia-smi", "--query-compute-apps=pid,process_name,used_gpu_memory",
        "--format=csv,noheader,nounits",
    ])
    rows = [line.strip() for line in memory["stdout"].splitlines() if line.strip()]
    parsed = []
    for row in rows:
        parts = [part.strip() for part in row.split(",")]
        if len(parts) == 4:
            try:
                parsed.append({"index": int(parts[0]), "name": parts[1], "memory_total_mib": int(parts[2]), "memory_free_mib": int(parts[3])})
            except ValueError:
                pass
    compute_apps = [line.strip() for line in apps["stdout"].splitlines() if line.strip() and "No running processes found" not in line]
    gpu0 = next((item for item in parsed if item["index"] == 0), None)
    return {
        "ready": memory["returncode"] == 0 and apps["returncode"] == 0 and gpu0 is not None and gpu0["memory_free_mib"] >= 3072 and not compute_apps,
        "minimum_gpu0_free_mib": 3072,
        "gpus": parsed,
        "compute_apps": compute_apps,
        "memory_returncode": memory["returncode"],
        "compute_apps_returncode": apps["returncode"],
    }


def run_full_input_preflight():
    result = BASE.command(PUBLISHER_PREFLIGHT_COMMAND, timeout=300)
    parsed = None
    for line in result["stdout"].splitlines():
        try:
            candidate = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(candidate, dict):
            parsed = candidate
    return {"command": PUBLISHER_PREFLIGHT_COMMAND, **result, "parsed": parsed}


def all_frozen_pins(protocol, stage2_freeze, manifest, adjudication):
    pins = {}
    for item in protocol["adopted_evidence"].values():
        pins[item["path"]] = {"sha256": item["sha256"], "size_bytes": item["size_bytes"]}
    for item in (protocol["input"]["manifest"], protocol["input"]["publisher"]):
        pins[item["path"]] = {"sha256": item["sha256"], "size_bytes": item["size_bytes"]}
    pins.update(protocol["publisher_runtime_pins"])
    pins[protocol["adapted_config"]["path"]] = {"sha256": protocol["adapted_config"]["sha256"], "size_bytes": protocol["adapted_config"]["size_bytes"]}
    pins[protocol["adapted_config"]["original_path"]] = {"sha256": protocol["adapted_config"]["original_sha256"], "size_bytes": protocol["adapted_config"]["original_size_bytes"]}
    calib = protocol["adapted_config"]["cam0_calibration_copy"]
    pins[calib["path"]] = {"sha256": calib["sha256"], "size_bytes": calib["size_bytes"]}
    pins[calib["original_path"]] = {
        "sha256": calib["original_sha256"],
        "size_bytes": calib["original_size_bytes"],
    }
    for item in protocol["exact_supervins_runtime"].values():
        if isinstance(item, dict) and "path" in item:
            pins[item["path"]] = {"sha256": item["sha256"], "size_bytes": item["size_bytes"]}
    pins.update(protocol["existing_source_trajectory_pre_pins"])
    pins.update(stage2_freeze["pinned_r1_governance"])
    pins.update(stage2_freeze["pinned_runtime_artifacts"])
    pins.update(manifest["source_metadata_pins"])
    adoption = manifest["official_source_adoption"]
    pins[adoption["path"]] = {"sha256": adoption["sha256"], "size_bytes": adoption["size_bytes"]}
    for key in ("download_manifest", "full_extracted_inventory"):
        item = adoption[key]
        pins[item["path"]] = {"sha256": item["sha256"], "size_bytes": item["size_bytes"]}
    pins.update(adjudication["controller_and_input_pins"])
    artifact_root = Path(adjudication["attempt_artifact_root"])
    for relative, expected in adjudication["attempt_artifact_pins"].items():
        pins[str(artifact_root / relative)] = expected
    return pins


def validate_lock(pins):
    observed = {"path": str(LOCK)}
    try:
        lock = read_json(LOCK)
        observed["identity"] = file_identity(LOCK)
    except (OSError, ValueError) as exc:
        observed["error"] = type(exc).__name__ + ":" + str(exc)[:500]
        return False, observed
    special = {
        "protocol": file_identity(PROTOCOL), "runner": file_identity(Path(__file__).resolve()),
        "tests": file_identity(TESTS), "publisher": file_identity(PUBLISHER), "input_manifest": file_identity(MANIFEST),
        "adapted_config": file_identity(ADAPTED_CONFIG), "adapted_calibration": file_identity(ADAPTED_CALIB),
    }
    pin_digest = hashlib.sha256(canonical_json_bytes(pins)).hexdigest()
    ok = all((
        lock.get("schema_version") == "aqua-fe-published-supervins-v1-official-euroc-mh01-full-trajectory-execution-lock-v1",
        lock.get("status") == "LOCKED_PRESTART_AWAITING_SEPARATE_ROOT_EXECUTION_AUTHORITY",
        lock.get("master_uri") == MASTER_URI, lock.get("master_command") == MASTER_COMMAND,
        lock.get("node_command") == NODE_COMMAND, lock.get("publisher_command") == PUBLISHER_COMMAND,
        lock.get("controller_command") == CONTROLLER_COMMAND,
        lock.get("authorization_token") == AUTHORIZATION_TOKEN,
        lock.get("maximum_roscore_starts") == 1, lock.get("maximum_node_starts") == 1,
        lock.get("maximum_publisher_starts") == 1, lock.get("retry_authorized") is False,
        lock.get("protocol") == special["protocol"], lock.get("runner") == special["runner"],
        lock.get("tests") == special["tests"], lock.get("publisher") == special["publisher"],
        lock.get("input_manifest") == special["input_manifest"], lock.get("adapted_config") == special["adapted_config"],
        lock.get("adapted_calibration") == special["adapted_calibration"],
        lock.get("pinned_file_count") == len(pins), lock.get("pinned_files_canonical_sha256") == pin_digest,
        lock.get("fresh_evidence_root") == str(EVIDENCE), lock.get("execution_authority_file") == str(AUTHORITY),
    ))
    observed.update({"special_identities": special, "pinned_file_count": len(pins), "pinned_files_canonical_sha256": pin_digest})
    return ok, observed


def validate_execution_authority():
    observed = {"path": str(AUTHORITY), "exists": AUTHORITY.exists()}
    if not AUTHORITY.exists():
        return False, observed
    try:
        value = read_json(AUTHORITY)
        observed["identity"] = file_identity(AUTHORITY)
        lock_identity = file_identity(LOCK)
        expected = {
            "protocol": file_identity(PROTOCOL), "lock": lock_identity,
            "runner": file_identity(Path(__file__).resolve()), "tests": file_identity(TESTS),
        }
        ok = all((
            value.get("schema_version") == "aqua-fe-supervins-mh01-full-trajectory-root-execution-authority-v1",
            value.get("status") == "AUTHORIZED_EXACTLY_ONE_FULL_TRAJECTORY_ATTEMPT_001_START",
            value.get("root_confirmation") is True,
            value.get("authorization_token_sha256") == AUTHORIZATION_TOKEN_SHA256,
            value.get("fresh_evidence_root") == str(EVIDENCE),
            value.get("controller_command") == CONTROLLER_COMMAND,
            value.get("protocol") == expected["protocol"], value.get("lock") == expected["lock"],
            value.get("runner") == expected["runner"], value.get("tests") == expected["tests"],
            value.get("maximum_roscore_starts") == 1, value.get("maximum_node_starts") == 1,
            value.get("maximum_publisher_starts") == 1, value.get("retry_authorized") is False,
        ))
        observed["expected_identities"] = expected
        observed["status"] = value.get("status")
        return ok, observed
    except (OSError, ValueError) as exc:
        observed["error"] = type(exc).__name__ + ":" + str(exc)[:500]
        return False, observed


def collect_prestart(require_authority=False):
    checks = {}
    failures = []

    def add(name, ok, expected, observed):
        checks[name] = {"ok": bool(ok), "expected": expected, "observed": observed}
        if not ok:
            failures.append(name)

    try:
        protocol = read_json(PROTOCOL)
        stage2_freeze = read_json(STAGE2_FREEZE)
        manifest = read_json(MANIFEST)
        adjudication = read_json(protocol["adopted_evidence"]["stage_3_immutable_adjudication"]["path"])
        pins = all_frozen_pins(protocol, stage2_freeze, manifest, adjudication)
        semantics_ok = (
            protocol.get("status") == "FROZEN_PRESTART_AWAITING_SEPARATE_ROOT_EXECUTION_CONFIRMATION"
            and protocol.get("relationship", {}).get("automatic_execution_authorized_by_this_freeze") is False
            and protocol.get("input", {}).get("camera_count") == CAMERA_COUNT
            and protocol.get("input", {}).get("imu_count") == IMU_COUNT
            and protocol.get("input", {}).get("source_time_per_wall_time") == 0.2
            and protocol.get("claim_boundary", {}).get("ape_rpe_or_accuracy_authorized") is False
            and protocol.get("claim_boundary", {}).get("network_model_threshold_or_backend_change_authorized") is False
            and protocol.get("ros", {}).get("master_command") == MASTER_COMMAND
            and protocol.get("ros", {}).get("node_command") == NODE_COMMAND
            and protocol.get("ros", {}).get("publisher_command") == PUBLISHER_COMMAND
            and protocol.get("one_shot_authority", {}).get("exact_controller_command") == CONTROLLER_COMMAND
            and protocol.get("output_path_resolution_contract", {}).get(
                "trajectory_output_directory_precreated_before_any_process_start"
            ) is True
            and protocol.get("success_contract", {}).get("node_camera_timestamp_lf_sha256_exact") == FRAME_TIMESTAMP_SHA256
            and protocol.get("success_contract", {}).get("node_even_camera_timestamp_lf_sha256_exact") == EVEN_FRAME_TIMESTAMP_SHA256
            and protocol.get("claim_boundary", {}).get("exact_all_imu_subscriber_callback_receipt_claim_authorized") is False
        )
        add("protocol_semantics", semantics_ok, True, protocol.get("claim_boundary"))
    except (OSError, ValueError, KeyError) as exc:
        protocol, stage2_freeze, manifest, adjudication, pins = {}, {}, {}, {}, {}
        add("protocol_load", False, True, type(exc).__name__ + ":" + str(exc)[:500])

    for path_text, expected in pins.items():
        ok, observed = check_identity(path_text, expected)
        add("pin:" + path_text, ok, expected, observed)
    lock_ok, lock_observed = validate_lock(pins) if pins else (False, {})
    add("execution_lock", lock_ok, True, lock_observed)

    authority_ok, authority_observed = validate_execution_authority()
    if require_authority:
        add("separate_root_execution_authority_present_and_valid", authority_ok, True, authority_observed)
    else:
        add("execution_authority_absent_prestart", not AUTHORITY.exists(), "ABSENT", authority_observed)

    try:
        seal = read_json(protocol["adopted_evidence"]["stage_2_pass_seal"]["path"])
        stage2_ok = seal.get("status") == "SEALED_PASS_DEVELOPMENT_ORTSESSION_CONSTRUCTION_ONLY"
        stage2_observed = seal.get("status")
    except (OSError, ValueError, KeyError) as exc:
        stage2_ok, stage2_observed = False, type(exc).__name__ + ":" + str(exc)[:500]
    add("stage2_session_construction_pass_adopted", stage2_ok, True, stage2_observed)
    stage3_ok = bool(
        adjudication and adjudication.get("status") == "SEALED_FORMAL_FAIL_WITH_RUNTIME_INFERENCE_GATES_RECONSTRUCTED"
        and adjudication.get("adjudicated_verdict", {}).get("formal_attempt_002_status_remains_fail") is True
        and adjudication.get("adjudicated_verdict", {}).get("extractor_inference_gate_materially_observed") is True
        and adjudication.get("adjudicated_verdict", {}).get("matcher_inference_gate_materially_observed") is True
    )
    add("stage3_adjudication_adopted_without_overriding_formal_fail", stage3_ok, True, adjudication.get("status") if adjudication else None)

    try:
        delta = config_delta_check()
        delta_ok = delta["only_output_path_changed"] and delta["adapted_output_path_exact"] and delta["both_resolve_to_trajectory_dir"] and delta["calibration_byte_identical"]
    except Exception as exc:
        delta_ok, delta = False, {"error": type(exc).__name__ + ":" + str(exc)[:500]}
    add("config_only_output_path_semantically_changed", delta_ok, True, delta)

    input_preflight = run_full_input_preflight()
    summary = input_preflight.get("parsed") or {}
    input_ok = (
        input_preflight["returncode"] == 0 and summary.get("status") == "READY_FULL_INPUT_NO_ROS_STARTED"
        and summary.get("ready") is True and summary.get("ros_started") is False
        and summary.get("camera_count") == CAMERA_COUNT and summary.get("imu_count") == IMU_COUNT
        and summary.get("event_count") == EVENT_COUNT and summary.get("source_time_per_wall_time") == 0.2
        and summary.get("digests") == {
            key: value["sha256"] for key, value in manifest.get("selected_content_digests", {}).items()
        }
    )
    add("full_input_no_ros_preflight", input_ok, True, input_preflight)

    source_observed = source_state_snapshot()
    add("source_and_private_repair_state", source_observed == expected_source_state(), expected_source_state(), source_observed)

    try:
        camera_rows = expected_camera_rows()
        camera_selection_ok = (
            len(camera_rows) == CAMERA_COUNT
            and camera_rows[0][1] == 1403636579763555584
            and camera_rows[-1][1] == 1403636763813555456
        )
    except (OSError, ValueError, IndexError) as exc:
        camera_rows, camera_selection_ok = (), False
        camera_selection_observed = type(exc).__name__ + ":" + str(exc)[:500]
    else:
        camera_selection_observed = {"count": len(camera_rows), "first": list(camera_rows[0]), "last": list(camera_rows[-1])}
    add("controller_camera_sequence_snapshot", camera_selection_ok, True, camera_selection_observed)

    runtime_env = runtime_environment(ROOT / ".full_trajectory_prestart_ros_home_not_created")
    binary_ldd = BASE.command(["ldd", BASE.BINARY], env=runtime_env)
    provider_ldd = BASE.command(["ldd", BASE.ORT / "lib/libonnxruntime_providers_cuda.so"], env=runtime_env)
    missing = [line.strip() for text in (binary_ldd["stdout"], provider_ldd["stdout"]) for line in text.splitlines() if "not found" in line]
    add("runtime_link_closure", binary_ldd["returncode"] == 0 and provider_ldd["returncode"] == 0 and not missing, [], missing)
    gpu = gpu_runtime_snapshot()
    add("gpu0_free_memory_and_no_compute_apps", gpu["ready"], {"gpu0_free_mib_minimum": 3072, "compute_apps": []}, gpu)
    isolated_env_ok = (
        runtime_env.get("PYTHONDONTWRITEBYTECODE") == "1"
        and runtime_env.get("CUDA_CACHE_PATH", "").endswith("/runtime_cache/cuda")
        and runtime_env.get("XDG_CACHE_HOME", "").endswith("/runtime_cache/xdg")
        and runtime_env.get("TMPDIR", "").endswith("/runtime_cache/tmp")
    )
    add("runtime_persistent_cache_roots_isolated", isolated_env_ok, True, {
        key: runtime_env.get(key) for key in ("ROS_HOME", "ROS_LOG_DIR", "CUDA_CACHE_PATH", "XDG_CACHE_HOME", "TMPDIR", "PYTHONDONTWRITEBYTECODE")
    })
    free_bytes = available_bytes(EVIDENCE.parent)
    add("fresh_evidence_filesystem_free_space", free_bytes >= 2 * 1024 ** 3, ">=2GiB", free_bytes)

    processes = relevant_processes()
    add("no_preexisting_relevant_process", not processes, [], processes)
    bound = port_is_bound()
    add("master_port_11555_unbound", not bound, False, bound)
    add("fresh_evidence_root", not EVIDENCE.exists(), "ABSENT", "PRESENT" if EVIDENCE.exists() else "ABSENT")
    required_absent = [ATTEMPT / name for name in ("roscore_start_claim.json", "node_start_claim.json", "publisher_start_claim.json")]
    required_absent += [TRAJECTORY_DIR, TRAJECTORY, EXTRINSIC, BACKEND_TIMES, FEATURE_TIMES, DURATION_TIMES]
    present = [str(path) for path in required_absent if path.exists()]
    add("fresh_claims_outputs_and_timing_artifacts_absent", not present, [], present)
    decoy = ROOT / "AQUA-FE_WS"
    add("no_duplicate_workspace_decoy_path", not decoy.exists(), "ABSENT", str(decoy) if decoy.exists() else "ABSENT")
    try:
        master_fd, slave_fd = pty.openpty(); os.close(master_fd); os.close(slave_fd)
        pty_ok, pty_observed = True, "openpty_close_ok"
    except OSError as exc:
        pty_ok, pty_observed = False, type(exc).__name__ + ":" + str(exc)[:500]
    add("pseudo_terminal_available", pty_ok, True, pty_observed)

    source_text = (BASE.PRIVATE / "supervins_estimator/src/utility/visualization.cpp").read_text(encoding="utf-8")
    estimator_text = (BASE.PRIVATE / "supervins_estimator/src/estimator/estimator.cpp").read_text(encoding="utf-8")
    output_source_ok = (
        'advertise<nav_msgs::Path>("path"' in source_text and 'advertise<nav_msgs::Odometry>("odometry"' in source_text
        and "ofstream foutC(VINS_RESULT_PATH, ios::app)" in source_text
        and 'ROS_INFO("Initialization finish!")' in estimator_text
        and "if (inputImageCnt % 2 == 0)" in estimator_text
    )
    add("source_output_initialization_and_even_frame_contract", output_source_ok, True, {"expected_backend_count": CAMERA_COUNT // 2})

    special_identity_snapshot = {
        "protocol": file_identity(PROTOCOL) if PROTOCOL.exists() else None,
        "lock": file_identity(LOCK) if LOCK.exists() else None,
        "authority": file_identity(AUTHORITY) if AUTHORITY.exists() else None,
        "runner": file_identity(RUNNER_PATH),
        "tests": file_identity(TESTS) if TESTS.exists() else None,
        "publisher": file_identity(PUBLISHER),
        "input_manifest": file_identity(MANIFEST),
        "adapted_config": file_identity(ADAPTED_CONFIG),
        "adapted_calibration": file_identity(ADAPTED_CALIB),
    }
    ready = not failures
    return {
        "schema_version": "aqua-fe-published-supervins-v1-official-euroc-mh01-full-trajectory-prestart-v1",
        "checked_at": now_iso(),
        "status": ("GO_PRESTART_ONLY_AWAITING_ROOT_EXECUTION_AUTHORITY" if ready and not require_authority else "GO_EXACTLY_ONE_FULL_TRAJECTORY_START" if ready else "BLOCKED_NO_PROCESS_START"),
        "ready": ready, "require_authority": require_authority, "failures": failures, "checks": checks,
        "frozen_pin_snapshot": pins,
        "special_identity_snapshot": special_identity_snapshot,
        "source_state_snapshot": source_observed,
        "boundary": {"roscore_started": False, "supervins_node_started": False, "publisher_started": False, "trajectory_created": False, "groundtruth_consumed": False, "ape_rpe_run": False},
    }


def post_pin_audit(preflight):
    pins = dict(preflight["frozen_pin_snapshot"])
    special_paths = {
        "protocol": PROTOCOL,
        "lock": LOCK,
        "authority": AUTHORITY,
        "runner": RUNNER_PATH,
        "tests": TESTS,
        "publisher": PUBLISHER,
        "input_manifest": MANIFEST,
        "adapted_config": ADAPTED_CONFIG,
        "adapted_calibration": ADAPTED_CALIB,
    }
    pins.update({str(path): preflight["special_identity_snapshot"][key] for key, path in special_paths.items()})
    outcomes = {}
    for path_text, expected in pins.items():
        ok, observed = check_identity(path_text, expected)
        outcomes[path_text] = {"ok": ok, "expected": expected, "observed": observed}
    return outcomes


def _run_once_impl(token):
    if token != AUTHORIZATION_TOKEN:
        emit_json({"status": "BLOCKED_INVALID_AUTHORIZATION_TOKEN_NO_START", "return_code": 2})
        return 2
    authority_ok, authority_observed = validate_execution_authority()
    if not authority_ok:
        emit_json({"status": "BLOCKED_ROOT_EXECUTION_AUTHORITY_ABSENT_OR_INVALID_NO_START", "return_code": 3, "authority": authority_observed})
        return 3
    preflight = collect_prestart(require_authority=True)
    if not preflight["ready"]:
        emit_json({"status": "BLOCKED_RUN_PREFLIGHT_NO_START", "return_code": 4, "preflight": preflight})
        return 4
    raise_if_termination_pending()

    protocol = read_json(PROTOCOL)
    stage2_freeze = read_json(STAGE2_FREEZE)
    manifest = read_json(MANIFEST)
    adjudication = read_json(protocol["adopted_evidence"]["stage_3_immutable_adjudication"]["path"])
    create_owned_evidence_root(EVIDENCE)
    ATTEMPT.mkdir(mode=0o755, exist_ok=False)
    TRAJECTORY_DIR.mkdir(mode=0o755, exist_ok=False)
    (EVIDENCE / "time_consumption").mkdir(mode=0o755, exist_ok=False)
    ros_home = ATTEMPT / "ros_home"
    (ros_home / "log").mkdir(mode=0o755, parents=True, exist_ok=False)
    for path in (ATTEMPT / "runtime_cache/cuda", ATTEMPT / "runtime_cache/xdg", ATTEMPT / "runtime_cache/tmp"):
        path.mkdir(mode=0o700, parents=True, exist_ok=False)
    namespace_setup = {
        "evidence_root": str(EVIDENCE),
        "attempt": str(ATTEMPT),
        "trajectory_directory": str(TRAJECTORY_DIR),
        "trajectory_directory_is_empty": not any(TRAJECTORY_DIR.iterdir()),
        "trajectory_directory_resolved_from_node_cwd": str((NODE_CWD / CONFIGURED_OUTPUT_PATH).resolve()),
        "trajectory_directory_resolved_from_project_source_dir": str((PROJECT_SOURCE_DIR / CONFIGURED_OUTPUT_PATH).resolve()),
        "prepared_before_any_process_start": True,
    }
    if not (
        TRAJECTORY_DIR.is_dir()
        and namespace_setup["trajectory_directory_is_empty"]
        and namespace_setup["trajectory_directory_resolved_from_node_cwd"] == str(TRAJECTORY_DIR)
        and namespace_setup["trajectory_directory_resolved_from_project_source_dir"] == str(TRAJECTORY_DIR)
    ):
        raise RuntimeError("trajectory_output_directory_preparation_contract_failed_before_any_process_start")
    preflight_identity = write_json_exclusive(ATTEMPT / "preflight_result.json", preflight)
    env = runtime_environment(ros_home)

    starts = RUN_GUARD_STATE["starts"]
    artifacts = {"preflight_result": preflight_identity, "execution_authority": file_identity(AUTHORITY)}
    master_proc = node_proc = publisher_proc = None
    master_termination = node_termination = publisher_termination = None
    master_launch_error = node_launch_error = publisher_launch_error = None
    state_before_node = subscription_witness = publisher_graph_witness = None
    gpu_before_node = None
    session_marker_elapsed = publisher_elapsed = drain_elapsed = None
    graph_monitor = new_graph_monitor()
    publisher_completed_naturally = False
    drain_quiescence_confirmed = False
    drain_completion_snapshot = None
    drain_snapshot_stable_since = None
    node_alive_before_controller_teardown = False
    master_alive_before_controller_teardown = False
    stdout_buffer, stderr_buffer = bytearray(), bytearray()

    master_stdout_path, master_stderr_path = ATTEMPT / "roscore.stdout.log", ATTEMPT / "roscore.stderr.log"
    node_stdout_path, node_stderr_path = ATTEMPT / "node.stdout.log", ATTEMPT / "node.stderr.log"
    publisher_stdout_path, publisher_stderr_path = ATTEMPT / "publisher.stdout.log", ATTEMPT / "publisher.stderr.log"

    raise_if_termination_pending()
    master_claim = {
        "schema_version": "aqua-fe-supervins-full-trajectory-roscore-start-claim-v1", "created_at": now_iso(),
        "authorization_token_sha256": AUTHORIZATION_TOKEN_SHA256, "command": MASTER_COMMAND,
        "maximum_roscore_starts": 1, "roscore_start_count_before_claim": 0,
        "execution_lock": file_identity(LOCK), "execution_authority": file_identity(AUTHORITY), "preflight_result": preflight_identity,
    }
    artifacts["roscore_start_claim"] = write_json_exclusive(ATTEMPT / "roscore_start_claim.json", master_claim)
    master_out = master_stdout_path.open("xb"); master_err = master_stderr_path.open("xb")
    try:
        try:
            master_proc = tracked_popen("roscore", "roscore_start_count", MASTER_COMMAND, cwd=str(ATTEMPT), env=env, stdin=subprocess.DEVNULL, stdout=master_out, stderr=master_err, start_new_session=True)
            write_json_exclusive(ATTEMPT / "roscore_process_started.json", {"started_at": now_iso(), "pid": master_proc.pid, "command": MASTER_COMMAND, "roscore_start_count": 1})
        except OSError as exc:
            master_launch_error = type(exc).__name__ + ":" + str(exc)[:500]
        deadline = time.monotonic() + MASTER_READY_TIMEOUT
        while master_proc and master_proc.poll() is None and time.monotonic() < deadline and not master_ready():
            raise_if_termination_pending()
            time.sleep(0.05)
        raise_if_termination_pending()
        if master_proc and master_ready():
            state_before_node = get_system_state()

        master_stage_ok = bool(master_proc and master_launch_error is None and state_before_node and state_before_node.get("ok") and not state_before_node.get("input_publishers") and set(state_before_node.get("nodes", [])) <= {"/rosout"})
        if master_stage_ok:
            gpu_before_node = gpu_runtime_snapshot()
        if master_stage_ok and gpu_before_node["ready"]:
            node_claim = {
                "schema_version": "aqua-fe-supervins-full-trajectory-node-start-claim-v1", "created_at": now_iso(),
                "authorization_token_sha256": AUTHORIZATION_TOKEN_SHA256, "command": NODE_COMMAND,
                "cwd": str(NODE_CWD), "maximum_node_starts": 1, "node_start_count_before_claim": 0,
                "master_pid": master_proc.pid, "master_state_before_node": state_before_node,
                "roscore_start_claim": artifacts["roscore_start_claim"], "trajectory_pre_state": "ABSENT",
                "namespace_setup": namespace_setup,
                "gpu_immediately_before_node_start": gpu_before_node,
            }
            artifacts["node_start_claim"] = write_json_exclusive(ATTEMPT / "node_start_claim.json", node_claim)
            stdout_master, stdout_slave = pty.openpty(); stderr_master, stderr_slave = pty.openpty()
            os.set_blocking(stdout_master, False); os.set_blocking(stderr_master, False)
            master_fds = [stdout_master, stderr_master]
            buffers = {stdout_master: stdout_buffer, stderr_master: stderr_buffer}
            node_out = node_stdout_path.open("xb"); node_err = node_stderr_path.open("xb")
            streams = {stdout_master: node_out, stderr_master: node_err}
            try:
                node_started = time.monotonic()
                try:
                    node_proc = tracked_popen("node", "node_start_count", NODE_COMMAND, cwd=str(NODE_CWD), env=env, stdin=subprocess.DEVNULL, stdout=stdout_slave, stderr=stderr_slave, start_new_session=True, close_fds=True)
                    write_json_exclusive(ATTEMPT / "node_process_started.json", {"started_at": now_iso(), "pid": node_proc.pid, "command": NODE_COMMAND, "cwd": str(NODE_CWD), "node_start_count": 1, "capture": "two_dedicated_ptys"})
                except OSError as exc:
                    node_launch_error = type(exc).__name__ + ":" + str(exc)[:500]
                os.close(stdout_slave); stdout_slave = -1; os.close(stderr_slave); stderr_slave = -1
                marker_deadline = node_started + NODE_READY_TIMEOUT
                while node_proc and node_proc.poll() is None and time.monotonic() < marker_deadline:
                    raise_if_termination_pending()
                    drain_pty(master_fds, streams, buffers, 0.05)
                    if classify_node_output(bytes(stdout_buffer), bytes(stderr_buffer))["session_marker_count"] >= 1:
                        session_marker_elapsed = time.monotonic() - node_started
                        break
                if session_marker_elapsed is not None:
                    subscription_witness = poll_state(subscriptions_ready, SUBSCRIPTION_TIMEOUT)

                if subscription_witness and subscription_witness["ready"]:
                    publisher_claim = {
                        "schema_version": "aqua-fe-supervins-full-trajectory-publisher-start-claim-v1", "created_at": now_iso(),
                        "authorization_token_sha256": AUTHORIZATION_TOKEN_SHA256, "command": PUBLISHER_COMMAND,
                        "maximum_publisher_starts": 1, "publisher_start_count_before_claim": 0,
                        "node_pid": node_proc.pid, "node_graph_before_publisher": subscription_witness,
                        "node_start_claim": artifacts["node_start_claim"],
                    }
                    artifacts["publisher_start_claim"] = write_json_exclusive(ATTEMPT / "publisher_start_claim.json", publisher_claim)
                    publisher_out = publisher_stdout_path.open("xb"); publisher_err = publisher_stderr_path.open("xb")
                    try:
                        try:
                            publisher_proc = tracked_popen("publisher", "publisher_start_count", PUBLISHER_COMMAND, cwd=str(ATTEMPT), env=env, stdin=subprocess.DEVNULL, stdout=publisher_out, stderr=publisher_err, start_new_session=True)
                            write_json_exclusive(ATTEMPT / "publisher_process_started.json", {"started_at": now_iso(), "pid": publisher_proc.pid, "command": PUBLISHER_COMMAND, "publisher_start_count": 1})
                        except OSError as exc:
                            publisher_launch_error = type(exc).__name__ + ":" + str(exc)[:500]
                        if publisher_proc:
                            registration_started = time.monotonic()
                            registration_deadline = registration_started + PUBLISHER_REGISTRATION_TIMEOUT
                            while publisher_proc.poll() is None and time.monotonic() < registration_deadline:
                                raise_if_termination_pending()
                                drain_pty(master_fds, streams, buffers, 0.05)
                                state = get_system_state()
                                if publisher_graph_ready(state):
                                    publisher_graph_witness = {"ready": True, "elapsed_seconds": time.monotonic() - registration_started, "state": state}
                                    update_graph_monitor(graph_monitor, state, master_proc.poll() is None, node_proc.poll() is None)
                                    break
                            completion_started = time.monotonic()
                            completion_deadline = completion_started + PUBLISHER_COMPLETION_TIMEOUT
                            next_graph_poll = completion_started + 2.0
                            while publisher_proc.poll() is None and time.monotonic() < completion_deadline:
                                raise_if_termination_pending()
                                drain_pty(master_fds, streams, buffers, 0.10)
                                now = time.monotonic()
                                master_alive = master_proc.poll() is None
                                node_alive = node_proc.poll() is None
                                if now >= next_graph_poll:
                                    update_graph_monitor(graph_monitor, get_system_state(), master_alive, node_alive)
                                    next_graph_poll = now + 2.0
                                if not master_alive or not node_alive:
                                    break
                            publisher_elapsed = time.monotonic() - completion_started
                            publisher_completed_naturally = publisher_proc.poll() is not None
                            publisher_termination = terminate_and_reap(publisher_proc)

                            drain_started = time.monotonic()
                            drain_deadline = drain_started + DRAIN_TIMEOUT
                            while node_proc.poll() is None and time.monotonic() < drain_deadline:
                                raise_if_termination_pending()
                                drain_pty(master_fds, streams, buffers, 0.10)
                                classification = classify_node_output(bytes(stdout_buffer), bytes(stderr_buffer))
                                backend = count_finite_timing_rows(BACKEND_TIMES)
                                trajectory = trajectory_audit(enforce_even_camera_membership=True)
                                extrinsic_now = extrinsic_audit()
                                completion_ready = (
                                    classification["extract_feature_time_count"] >= CAMERA_COUNT
                                    and classification["frame_timestamp_count"] >= CAMERA_COUNT
                                    and backend["line_count"] == BACKEND_COUNT
                                    and trajectory["valid_row_count"] >= 920
                                    and trajectory["last_timestamp_text"] == LAST_CAMERA_FIXED6_TEXT
                                    and trajectory["timestamps_are_contiguous_even_camera_suffix"]
                                    and extrinsic_now["is_finite_se3"]
                                )
                                if completion_ready:
                                    snapshot = (
                                        backend["line_count"], BACKEND_TIMES.stat().st_size,
                                        trajectory["valid_row_count"], TRAJECTORY.stat().st_size,
                                        trajectory["last_timestamp_text"], EXTRINSIC.stat().st_size,
                                    )
                                    now = time.monotonic()
                                    drain_completion_snapshot, drain_snapshot_stable_since, drain_quiescence_confirmed = update_quiescence(
                                        drain_completion_snapshot, drain_snapshot_stable_since, snapshot, now
                                    )
                                    if drain_quiescence_confirmed:
                                        break
                                else:
                                    drain_completion_snapshot = None
                                    drain_snapshot_stable_since = None
                            drain_elapsed = time.monotonic() - drain_started
                    finally:
                        publisher_termination = publisher_termination or terminate_and_reap(publisher_proc)
                        publisher_out.flush(); publisher_err.flush(); os.fsync(publisher_out.fileno()); os.fsync(publisher_err.fileno())
                        publisher_out.close(); publisher_err.close()
            finally:
                node_alive_before_controller_teardown = bool(node_proc and node_proc.poll() is None)
                for slave in (stdout_slave, stderr_slave):
                    if slave >= 0:
                        os.close(slave)
                publisher_termination = publisher_termination or terminate_and_reap(publisher_proc)
                node_termination = terminate_and_reap(node_proc)
                drain_deadline = time.monotonic() + 1.0
                while master_fds and time.monotonic() < drain_deadline:
                    drain_pty(master_fds, streams, buffers, 0.05)
                for fd in (stdout_master, stderr_master):
                    try: os.close(fd)
                    except OSError: pass
                node_out.flush(); node_err.flush(); os.fsync(node_out.fileno()); os.fsync(node_err.fileno())
                node_out.close(); node_err.close()
    finally:
        master_alive_before_controller_teardown = bool(master_proc and master_proc.poll() is None)
        publisher_termination = publisher_termination or terminate_and_reap(publisher_proc)
        node_termination = node_termination or terminate_and_reap(node_proc)
        master_termination = terminate_and_reap(master_proc)
        master_out.flush(); master_err.flush(); os.fsync(master_out.fileno()); os.fsync(master_err.fileno())
        master_out.close(); master_err.close()

    raise_if_termination_pending()
    classification = classify_node_output(bytes(stdout_buffer), bytes(stderr_buffer))
    publisher_records = parse_json_lines(publisher_stdout_path)
    camera_records = [record for record in publisher_records if record.get("event") == "CAMERA_PUBLISHED"]
    camera_sequence = publisher_camera_sequence_audit(camera_records)
    terminals = [record for record in publisher_records if record.get("status") == "PUBLISH_COMPLETE"]
    terminal = terminals[-1] if terminals else {}
    expected_digests = {key: value["sha256"] for key, value in manifest["selected_content_digests"].items()}
    wall_span = terminal.get("wall_publish_span_seconds")
    publisher_complete = (
        len(terminals) == 1 and len(camera_records) == CAMERA_COUNT
        and camera_sequence["exact"] and camera_sequence["every_record_has_decoded_sha256"]
        and terminal.get("camera_count") == CAMERA_COUNT and terminal.get("imu_count") == IMU_COUNT
        and terminal.get("event_count") == EVENT_COUNT and terminal.get("digests") == expected_digests
        and terminal.get("first_timestamp_ns") == FIRST_EVENT_NS and terminal.get("last_timestamp_ns") == LAST_EVENT_NS
        and terminal.get("source_span_seconds") == SOURCE_SPAN_SECONDS
        and terminal.get("source_time_per_wall_time") == 0.2
        and isinstance(wall_span, (int, float)) and EXPECTED_WALL_PUBLISH_SPAN_SECONDS - 3 <= wall_span <= 1200.0
        and terminal.get("publisher_transport") == "synchronous_rospy_queue_size_none"
        and terminal.get("image_connections_at_end", 0) >= 1 and terminal.get("imu_connections_at_end", 0) >= 1
        and terminal.get("digests_match_frozen_manifest") is True and terminal.get("rosbag_used") is False
        and terminal.get("groundtruth_published") is False and terminal.get("cam1_published") is False
        and publisher_completed_naturally and publisher_termination.get("returncode") == 0
    )
    backend = count_finite_timing_rows(BACKEND_TIMES)
    trajectory = trajectory_audit(enforce_even_camera_membership=True)
    extrinsic = extrinsic_audit()
    post_pins = post_pin_audit(preflight)
    changed_pins = [path for path, item in post_pins.items() if not item["ok"]]
    source_trajectory_paths = set(protocol["existing_source_trajectory_pre_pins"])
    changed_source_trajectory = [path for path in changed_pins if path in source_trajectory_paths]
    post_source_state = source_state_snapshot()
    post_processes = relevant_processes(); post_port_bound = port_is_bound()
    decoy_exists = (ROOT / "AQUA-FE_WS").exists()

    pass_conditions = {
        "run_preflight_go": preflight["ready"], "one_roscore_start": starts["roscore_start_count"] == 1,
        "trajectory_directory_precreated_before_any_process_start": namespace_setup["prepared_before_any_process_start"] and namespace_setup["trajectory_directory_is_empty"],
        "one_node_start": starts["node_start_count"] == 1, "one_publisher_start": starts["publisher_start_count"] == 1,
        "launch_errors_absent": master_launch_error is None and node_launch_error is None and publisher_launch_error is None,
        "gpu_revalidated_immediately_before_node_start": bool(gpu_before_node and gpu_before_node["ready"]),
        "session_marker_observed": classification["session_marker_count"] >= 1,
        "subscriptions_ready_before_publisher": bool(subscription_witness and subscription_witness["ready"]),
        "exact_publisher_and_trajectory_topic_graph_observed": publisher_graph_witness is not None,
        "continuous_graph_and_process_monitor_clean": graph_monitor["sample_count"] >= 2 and graph_monitor["unavailable_count"] == 0 and graph_monitor["identity_violation_count"] == 0 and graph_monitor["process_liveness_violation_count"] == 0,
        "publisher_complete_exact_full_input": publisher_complete,
        "extractor_processed_every_camera": classification["extract_feature_time_count"] == CAMERA_COUNT,
        "node_received_exact_frozen_camera_timestamp_sequence": classification["frame_timestamp_count"] == CAMERA_COUNT and classification["frame_timestamp_first"] == FIRST_FRAME_TIMESTAMP_TEXT and classification["frame_timestamp_last"] == LAST_FRAME_TIMESTAMP_TEXT and classification["frame_timestamp_sha256_lf"] == FRAME_TIMESTAMP_SHA256 and classification["even_frame_timestamp_count"] == BACKEND_COUNT and classification["even_frame_timestamp_sha256_lf"] == EVEN_FRAME_TIMESTAMP_SHA256,
        "estimator_process_measurement_record_for_every_even_camera": backend["line_count"] == BACKEND_COUNT and backend["all_finite_nonnegative"],
        "initialization_exactly_once": classification["initialization_finish_count"] == 1,
        "no_failure_detection_or_reboot": classification["failure_detection_count"] == 0 and classification["system_reboot_count"] == 0,
        "trajectory_minimum_rows": trajectory["valid_row_count"] >= 920,
        "trajectory_valid_timestamps_and_values": trajectory["timestamps_strictly_increasing"] and trajectory["all_values_finite"] and trajectory["quaternion_norm_in_range"] and trajectory["timestamp_text_format_fixed6"] and trajectory["timestamps_are_even_camera_subset"] and trajectory["timestamps_are_contiguous_even_camera_suffix"],
        "trajectory_minimum_source_span": trajectory.get("source_span_seconds") is not None and trajectory["source_span_seconds"] >= 92.0,
        "trajectory_reaches_exact_final_even_camera": trajectory["last_timestamp_text"] == LAST_CAMERA_FIXED6_TEXT and trajectory.get("tail_gap_seconds") is not None and 0 <= trajectory["tail_gap_seconds"] <= 1e-5,
        "post_completion_outputs_quiescent_before_node_termination": drain_quiescence_confirmed,
        "optimized_extrinsic_output_is_finite_se3_in_fresh_directory": extrinsic["exists"] and extrinsic["size_bytes"] > 0 and extrinsic["is_finite_se3"],
        "publisher_exited_normally": publisher_completed_naturally and publisher_termination["returncode"] == 0,
        "node_and_roscore_alive_until_controller_teardown": node_alive_before_controller_teardown and master_alive_before_controller_teardown,
        "publisher_reaped": publisher_termination["reaped"], "node_reaped": node_termination["reaped"], "roscore_reaped": master_termination["reaped"],
        "no_post_process_or_bound_port": not post_processes and not post_port_bound,
        "all_frozen_pins_unchanged": not changed_pins, "source_trajectory_artifacts_unchanged": not changed_source_trajectory,
        "source_and_private_repair_state_unchanged": post_source_state == preflight["source_state_snapshot"] == expected_source_state(),
        "no_duplicate_workspace_decoy_write": not decoy_exists,
    }
    passed = all(pass_conditions.values())
    status = PASS_STATUS if passed else "FAIL_DEVELOPMENT_OFFICIAL_MH01_FULL_TRAJECTORY_NO_RETRY"
    artifact_paths = [
        "preflight_result.json", "roscore_start_claim.json", "node_start_claim.json", "publisher_start_claim.json",
        "roscore_process_started.json", "node_process_started.json", "publisher_process_started.json",
        "roscore.stdout.log", "roscore.stderr.log", "node.stdout.log", "node.stderr.log", "publisher.stdout.log", "publisher.stderr.log",
    ]
    for name in artifact_paths:
        path = ATTEMPT / name
        artifacts[name] = file_identity(path) if path.exists() else None
    if TRAJECTORY.exists(): artifacts["trajectory_output/vio.csv"] = file_identity(TRAJECTORY)
    if EXTRINSIC.exists(): artifacts["trajectory_output/extrinsic_parameter.csv"] = file_identity(EXTRINSIC)
    for path in (BACKEND_TIMES, FEATURE_TIMES, DURATION_TIMES):
        if path.exists(): artifacts[str(path.relative_to(EVIDENCE))] = file_identity(path)
    for path in sorted((ATTEMPT / "ros_home").rglob("*")):
        if path.is_file():
            artifacts[str(path.relative_to(ATTEMPT))] = file_identity(path)
    fresh_namespace_inventory = {
        str(path.relative_to(EVIDENCE)): file_identity(path)
        for path in sorted(EVIDENCE.rglob("*"))
        if path.is_file()
    }

    result = {
        "schema_version": "aqua-fe-published-supervins-v1-official-euroc-mh01-full-trajectory-result-v1",
        "status": status, "return_code": 0 if passed else 1, "evaluable": True,
        "authorization": {**starts, "retry_authorized": False, "root_execution_authority": file_identity(AUTHORITY)},
        "namespace_setup": namespace_setup,
        "input": {"sequence": "official MH_01_easy full cam0+imu0; not V2_01", "camera_count": CAMERA_COUNT, "imu_count": IMU_COUNT, "event_count": EVENT_COUNT, "source_time_per_wall_time": 0.2},
        "master": {"command": MASTER_COMMAND, "launch_error": master_launch_error, "state_before_node": state_before_node, "gpu_immediately_before_node_start": gpu_before_node, "alive_before_controller_teardown": master_alive_before_controller_teardown, "termination": master_termination},
        "node": {"command": NODE_COMMAND, "cwd": str(NODE_CWD), "launch_error": node_launch_error, "session_marker_elapsed_seconds": session_marker_elapsed, "subscription_witness": subscription_witness, "alive_before_controller_teardown": node_alive_before_controller_teardown, "termination": node_termination, "classification": classification},
        "publisher": {"command": PUBLISHER_COMMAND, "launch_error": publisher_launch_error, "graph_witness": publisher_graph_witness, "continuous_graph_monitor": graph_monitor, "completion_elapsed_seconds": publisher_elapsed, "completed_naturally": publisher_completed_naturally, "terminal": terminal, "camera_sequence": camera_sequence, "termination": publisher_termination},
        "processing_drain": {"elapsed_seconds": drain_elapsed, "quiescence_confirmed": drain_quiescence_confirmed, "stable_snapshot": list(drain_completion_snapshot) if drain_completion_snapshot else None, "estimator_process_measurement_records": backend}, "trajectory": trajectory, "optimized_extrinsic_output": extrinsic,
        "pass_conditions": pass_conditions,
        "post_pin_audit": {"changed_pins": changed_pins, "changed_source_trajectory_artifacts": changed_source_trajectory, "checks": post_pins},
        "post_source_state": post_source_state,
        "post_process_audit": {"processes": post_processes, "port_11555_bound": post_port_bound, "duplicate_workspace_decoy_exists": decoy_exists},
        "artifacts": artifacts,
        "fresh_namespace_file_inventory_before_result": fresh_namespace_inventory,
        "claim_boundary": {"trajectory_file_present": TRAJECTORY.exists(), "full_trajectory_passed": passed, "groundtruth_consumed": False, "ape_rpe_or_accuracy_run": False, "loop_fusion_run": False, "formal_v2_01_baseline": False, "underwater_or_comparative_claim": False},
        "next_stage_automatically_authorized": False,
    }
    raise_if_termination_pending()
    result_identity = write_json_exclusive(ATTEMPT / "run_result.json", result)
    terminal_return_code = 0 if passed else 1
    RUN_GUARD_STATE["terminal_result_committed"] = True
    RUN_GUARD_STATE["terminal_return_code"] = terminal_return_code
    emit_json({"status": status, "return_code": terminal_return_code, "run_result_identity": result_identity})
    return terminal_return_code


def emergency_terminal_closeout(exc):
    command_by_name = {"publisher": PUBLISHER_COMMAND, "node": NODE_COMMAND, "roscore": MASTER_COMMAND}
    active_snapshot = {}
    for name, proc in ACTIVE_PROCESSES.items():
        if proc is None:
            active_snapshot[name] = None
            continue
        try:
            poll_value, poll_error = proc.poll(), None
        except Exception as poll_exc:
            poll_value, poll_error = None, type(poll_exc).__name__ + ":" + str(poll_exc)[:500]
        try:
            pid, pid_error = proc.pid, None
        except Exception as pid_exc:
            pid, pid_error = None, type(pid_exc).__name__ + ":" + str(pid_exc)[:500]
        active_snapshot[name] = {
            "pid": pid, "pid_error": pid_error, "command": command_by_name[name],
            "poll_before_closeout": poll_value, "poll_error": poll_error,
        }
    terminations = {}
    for name in ("publisher", "node", "roscore"):
        terminations[name] = terminate_and_reap(ACTIVE_PROCESSES.get(name))
    try:
        inventory = {
            str(path.relative_to(EVIDENCE)): file_identity(path)
            for path in sorted(EVIDENCE.rglob("*"))
            if path.is_file() and path.name not in {"run_result.json", "emergency_closeout.json"}
        } if EVIDENCE.exists() else {}
    except Exception as inventory_exc:
        inventory = {"inventory_error": type(inventory_exc).__name__ + ":" + str(inventory_exc)[:500]}
    try:
        post_processes, post_process_error = relevant_processes(), None
    except Exception as process_exc:
        post_processes, post_process_error = [], type(process_exc).__name__ + ":" + str(process_exc)[:500]
    try:
        post_port_bound, post_port_error = port_is_bound(), None
    except Exception as port_exc:
        post_port_bound, post_port_error = None, type(port_exc).__name__ + ":" + str(port_exc)[:500]
    closeout = {
        "schema_version": "aqua-fe-published-supervins-v1-official-euroc-mh01-full-trajectory-emergency-result-v1",
        "status": "FAIL_CONTROLLER_EXCEPTION_TERMINAL_NO_RETRY",
        "return_code": 5,
        "closed_at": now_iso(),
        "exception": {
            "type": type(exc).__name__,
            "message": str(exc)[:1000],
            "traceback": "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))[-12000:],
        },
        "authorization": {**RUN_GUARD_STATE["starts"], "retry_authorized": False},
        "active_process_snapshot_before_closeout": active_snapshot,
        "process_terminations": terminations,
        "post_process_audit": {"processes": post_processes, "process_scan_error": post_process_error, "port_11555_bound": post_port_bound, "port_scan_error": post_port_error},
        "fresh_namespace_file_inventory_before_result": inventory,
        "claim_boundary": {"groundtruth_consumed": False, "ape_rpe_or_accuracy_run": False, "automatic_retry": False},
    }
    identity = None
    error = None
    if RUN_GUARD_STATE.get("namespace_owned"):
        try:
            ATTEMPT.mkdir(mode=0o755, exist_ok=True)
            target = ATTEMPT / "run_result.json"
            if target.exists():
                target = ATTEMPT / "emergency_closeout.json"
            identity = write_json_exclusive(target, closeout)
            closeout["persisted_path"] = str(target)
        except Exception as write_exc:
            error = type(write_exc).__name__ + ":" + str(write_exc)[:500]
    closeout["persisted_identity"] = identity
    closeout["persistence_error"] = error
    return closeout


def run_once(token):
    for name in ACTIVE_PROCESSES:
        ACTIVE_PROCESSES[name] = None
    RUN_GUARD_STATE["namespace_owned"] = False
    RUN_GUARD_STATE["starts"] = {"roscore_start_count": 0, "node_start_count": 0, "publisher_start_count": 0}
    RUN_GUARD_STATE["terminal_result_committed"] = False
    RUN_GUARD_STATE["terminal_return_code"] = None
    TERMINATION_SIGNAL_STATE["in_progress"] = False
    TERMINATION_SIGNAL_STATE["pending_signum"] = None
    previous_handlers = {}
    previous_mask = None
    try:
        for signum in CONTROLLED_SIGNALS:
            previous_handlers[signum] = signal.getsignal(signum)
            signal.signal(signum, raise_controlled_termination)
        return _run_once_impl(token)
    except BaseException as exc:
        TERMINATION_SIGNAL_STATE["in_progress"] = True
        if hasattr(signal, "pthread_sigmask"):
            try:
                previous_mask = signal.pthread_sigmask(signal.SIG_BLOCK, set(CONTROLLED_SIGNALS))
            except (OSError, ValueError):
                previous_mask = None
        if RUN_GUARD_STATE["terminal_result_committed"]:
            for name in ("publisher", "node", "roscore"):
                terminate_and_reap(ACTIVE_PROCESSES.get(name))
            emit_json({
                "status": "EXISTING_TERMINAL_RESULT_PRESERVED_AFTER_NONFATAL_EMISSION_ERROR",
                "return_code": RUN_GUARD_STATE["terminal_return_code"],
                "run_result_path": str(ATTEMPT / "run_result.json"),
            })
            return RUN_GUARD_STATE["terminal_return_code"]
        closeout = emergency_terminal_closeout(exc)
        emit_json(closeout)
        return 5
    finally:
        if previous_mask is not None:
            for signum in previous_handlers:
                try:
                    signal.signal(signum, signal.SIG_IGN)
                except (OSError, ValueError):
                    pass
            try:
                signal.pthread_sigmask(signal.SIG_SETMASK, previous_mask)
            except (OSError, ValueError):
                pass
        for signum, handler in previous_handlers.items():
            try:
                signal.signal(signum, handler)
            except (OSError, ValueError):
                pass
        TERMINATION_SIGNAL_STATE["in_progress"] = False
        TERMINATION_SIGNAL_STATE["pending_signum"] = None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--action", choices=("prestart", "run"), required=True)
    parser.add_argument("--authorization-token")
    args = parser.parse_args()
    if args.action == "prestart":
        result = collect_prestart(require_authority=False)
        emit_json(result)
        return 0 if result["ready"] else 1
    return run_once(args.authorization_token)


if __name__ == "__main__":
    sys.exit(main())
