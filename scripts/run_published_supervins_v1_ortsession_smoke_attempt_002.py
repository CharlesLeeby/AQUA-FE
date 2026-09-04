#!/usr/bin/env python3
"""Fresh attempt-002 SuperVINS session smoke with empty roscore and PTY logs.

The unchanged pinned node is started at most once.  No input publisher, bag,
dataset, or inference is permitted.  Dedicated pseudo-terminals make the stock
ROS_WARN console line observable without changing the executable or argv.
"""

from __future__ import annotations

import argparse
import errno
import hashlib
import importlib.util
import json
import os
import pty
import select
import signal
import socket
import subprocess
import sys
import time
import xmlrpc.client
from datetime import datetime
from pathlib import Path


ROOT = Path("/home/ma/AQUA-FE_WS")
BASE_RUNNER = ROOT / "scripts/run_published_supervins_v1_ortsession_smoke_v1.py"
SPEC = importlib.util.spec_from_file_location("supervins_session_smoke_attempt_001", BASE_RUNNER)
BASE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(BASE)

PROTOCOL = ROOT / "papers/supervins_v1_ortsession_construction_smoke_attempt_002_freeze_v1.json"
LOCK = ROOT / "papers/supervins_v1_ortsession_construction_smoke_attempt_002_execution_lock_v1.json"
TESTS = ROOT / "scripts/tests/test_run_published_supervins_v1_ortsession_smoke_attempt_002.py"
ADOPTION = ROOT / "papers/supervins_v1_ortsession_smoke_attempt_001_failure_adoption_v1.json"
OLD_FREEZE = ROOT / "papers/supervins_v1_ortsession_construction_smoke_freeze_v1.json"
EVIDENCE = ROOT / "experiments/published_supervins_v1_ortsession_smoke_20260816_r2"
ATTEMPT = EVIDENCE / "attempt_002"

MASTER_HOST = "127.0.0.1"
MASTER_PORT = 11552
MASTER_URI = "http://127.0.0.1:11552"
MASTER_COMMAND = ["/opt/ros/noetic/bin/roscore", "-p", "11552"]
MASTER_READY_TIMEOUT = 12.0
NODE_TIMEOUT = 45.0
TERM_GRACE_SECONDS = 3.0
AUTHORIZATION_TOKEN = "SUPERVINS_V1_ORTSESSION_SMOKE_ATTEMPT_002_START_ONCE"
NODE_COMMAND = [str(BASE.BINARY), str(BASE.CONFIG)]
SUCCESS_MARKER = "waiting for image and imu..."
FORBIDDEN_INFERENCE_MARKERS = ["extract feature time", "matches.size()"]
INPUT_TOPICS = [
    "/imu0",
    "/cam0/image_raw",
    "/cam1/image_raw",
    "/feature_tracker/feature",
    "/vins_restart",
    "/vins_imu_switch",
    "/vins_cam_switch",
]
PASS_STATUS = "PASS_DEVELOPMENT_ORTSESSION_CONSTRUCTION_ONLY_ATTEMPT_002"
CALLER_ID = "/aqua_fe_supervins_session_smoke_controller"


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


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def canonical_json_bytes(value):
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def write_json_exclusive(path, value, mode=0o444):
    path = Path(path)
    payload = canonical_json_bytes(value)
    fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode)
    try:
        view = memoryview(payload)
        while view:
            view = view[os.write(fd, view):]
        os.fsync(fd)
    finally:
        os.close(fd)
    return file_identity(path)


def check_identity(path, expected):
    try:
        observed = file_identity(path)
        return observed == expected, observed
    except OSError as exc:
        return False, {"error": type(exc).__name__ + ":" + str(exc)[:500]}


def port_is_bound():
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(0.2)
    try:
        return sock.connect_ex((MASTER_HOST, MASTER_PORT)) == 0
    finally:
        sock.close()


def runtime_environment(ros_home):
    env = BASE.runtime_environment(ros_home)
    env["ROS_MASTER_URI"] = MASTER_URI
    env["ROS_HOSTNAME"] = MASTER_HOST
    env["ROS_HOME"] = str(ros_home)
    env["ROS_LOG_DIR"] = str(Path(ros_home) / "log")
    return env


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
    state = response[2]
    labels = ("publishers", "subscribers", "services")
    parsed = {}
    for label, entries in zip(labels, state):
        parsed[label] = {name: sorted(nodes) for name, nodes in entries}
    nodes = sorted(
        {
            node
            for group in parsed.values()
            for node_list in group.values()
            for node in node_list
        }
    )
    input_publishers = {
        topic: parsed["publishers"].get(topic, [])
        for topic in INPUT_TOPICS
        if parsed["publishers"].get(topic)
    }
    return {"state": parsed, "nodes": nodes, "input_publishers": input_publishers}


def get_system_state():
    try:
        return {"ok": True, **parse_system_state(master_call("getSystemState"))}
    except (OSError, socket.timeout, xmlrpc.client.Error, ValueError) as exc:
        return {"ok": False, "error": type(exc).__name__ + ":" + str(exc)[:500]}


def process_pids_by_comm(comm):
    return BASE.process_pids_by_comm(comm)


def port_processes():
    found = []
    for path in Path("/proc").glob("[0-9]*/cmdline"):
        try:
            parts = [part.decode("utf-8", "replace") for part in path.read_bytes().split(b"\0") if part]
        except OSError:
            continue
        joined = " ".join(parts)
        executable_names = {Path(part).name for part in parts[:3]}
        is_ros_master_stack = bool(executable_names & {"roscore", "rosmaster", "roslaunch"})
        if "11552" in parts and is_ros_master_stack:
            found.append({"pid": int(path.parent.name), "argv": parts})
    return sorted(found, key=lambda item: item["pid"])


def terminate_and_reap(proc):
    events = []
    if proc is None:
        return {"events": events, "returncode": None, "sigkill_used": False, "reaped": True}
    if proc.poll() is None:
        try:
            os.killpg(proc.pid, signal.SIGTERM)
            events.append({"at": now_iso(), "signal": "SIGTERM_PROCESS_GROUP"})
        except ProcessLookupError:
            events.append({"at": now_iso(), "signal": "SIGTERM_ALREADY_GONE"})
    try:
        rc = proc.wait(timeout=TERM_GRACE_SECONDS)
        events.append({"at": now_iso(), "event": "REAPED_AFTER_TERM_OR_PRIOR_EXIT"})
        return {"events": events, "returncode": rc, "sigkill_used": False, "reaped": True}
    except subprocess.TimeoutExpired:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
            events.append({"at": now_iso(), "signal": "SIGKILL_PROCESS_GROUP"})
        except ProcessLookupError:
            events.append({"at": now_iso(), "signal": "SIGKILL_ALREADY_GONE"})
        rc = proc.wait(timeout=5)
        events.append({"at": now_iso(), "event": "REAPED_AFTER_KILL"})
        return {"events": events, "returncode": rc, "sigkill_used": True, "reaped": True}


def snapshot_open_fds(pid):
    return BASE.snapshot_open_fds(pid)


def all_protocol_pins(protocol, old_freeze):
    pins = {}
    pins[protocol["attempt_001_adoption"]["path"]] = {
        "sha256": protocol["attempt_001_adoption"]["sha256"],
        "size_bytes": protocol["attempt_001_adoption"]["size_bytes"],
    }
    pins[protocol["adopted_stack_freeze"]["path"]] = {
        "sha256": protocol["adopted_stack_freeze"]["sha256"],
        "size_bytes": protocol["adopted_stack_freeze"]["size_bytes"],
    }
    pins.update(protocol["attempt_001_controller_pins"])
    pins.update(protocol["ros_infrastructure_pins"])
    pins.update(old_freeze["pinned_r1_governance"])
    pins.update(old_freeze["pinned_runtime_artifacts"])
    return pins


def validate_lock(pins):
    observed = {"path": str(LOCK)}
    try:
        lock = read_json(LOCK)
        observed["identity"] = file_identity(LOCK)
    except (OSError, ValueError) as exc:
        observed["error"] = type(exc).__name__ + ":" + str(exc)[:500]
        return False, observed
    pin_digest = hashlib.sha256(canonical_json_bytes(pins)).hexdigest()
    expected_special = {
        "protocol": file_identity(PROTOCOL),
        "runner": file_identity(Path(__file__).resolve()),
        "tests": file_identity(TESTS),
    }
    ok = all(
        (
            lock.get("schema_version") == "aqua-fe-published-supervins-v1-ortsession-smoke-attempt-002-execution-lock-v1",
            lock.get("status") == "LOCKED_FOR_EXACTLY_ONE_EMPTY_MASTER_AND_ONE_NODE_START",
            lock.get("authorization_token") == AUTHORIZATION_TOKEN,
            lock.get("master_command") == MASTER_COMMAND,
            lock.get("node_command") == NODE_COMMAND,
            lock.get("master_uri") == MASTER_URI,
            lock.get("maximum_roscore_starts") == 1,
            lock.get("maximum_node_starts") == 1,
            lock.get("master_ready_timeout_seconds") == 12,
            lock.get("node_marker_timeout_seconds") == 45,
            lock.get("protocol") == expected_special["protocol"],
            lock.get("runner") == expected_special["runner"],
            lock.get("tests") == expected_special["tests"],
            lock.get("pinned_file_count") == len(pins),
            lock.get("pinned_files_canonical_sha256") == pin_digest,
            lock.get("fresh_evidence_root") == str(EVIDENCE),
        )
    )
    observed.update(
        {
            "status": lock.get("status"),
            "special_identities": {key: {"expected": value, "observed": lock.get(key)} for key, value in expected_special.items()},
            "pinned_file_count": lock.get("pinned_file_count"),
            "pinned_files_canonical_sha256": lock.get("pinned_files_canonical_sha256"),
        }
    )
    return ok, observed


def collect_preflight():
    checks = {}
    failures = []

    def add(name, ok, expected, observed):
        checks[name] = {"ok": bool(ok), "expected": expected, "observed": observed}
        if not ok:
            failures.append(name)

    try:
        protocol = read_json(PROTOCOL)
        old_freeze = read_json(OLD_FREEZE)
        pins = all_protocol_pins(protocol, old_freeze)
        semantics_ok = (
            protocol.get("status") == "FROZEN_BEFORE_ATTEMPT_002_MASTER_OR_NODE_START"
            and protocol.get("claim_boundary", {}).get("ort_session_construction_authorized") is True
            and protocol.get("claim_boundary", {}).get("model_inference_authorized") is False
            and protocol.get("claim_boundary", {}).get("ros_input_publisher_authorized") is False
            and protocol.get("one_shot_authority", {}).get("maximum_roscore_starts") == 1
            and protocol.get("one_shot_authority", {}).get("maximum_supervins_node_starts") == 1
            and protocol.get("pinned_node_command") == NODE_COMMAND
            and protocol.get("isolated_ros_master", {}).get("command") == MASTER_COMMAND
            and protocol.get("capture_contract", {}).get("stdout_transport") == "DEDICATED_PSEUDO_TERMINAL"
        )
        add("protocol_semantics", semantics_ok, True, protocol.get("claim_boundary"))
    except (OSError, ValueError, KeyError) as exc:
        protocol, old_freeze, pins = {}, {}, {}
        add("protocol_semantics", False, True, type(exc).__name__ + ":" + str(exc)[:500])

    for path_text, expected in pins.items():
        ok, observed = check_identity(path_text, expected)
        add("pin:" + path_text, ok, expected, observed)

    lock_ok, lock_observed = validate_lock(pins) if pins else (False, {})
    add("execution_lock", lock_ok, True, lock_observed)

    try:
        adoption = read_json(ADOPTION)
        adoption_ok = (
            adoption.get("status") == "ADOPTED_TERMINAL_FAIL_CLOSED_NO_RETRY"
            and adoption.get("formal_verdict", {}).get("namespace_reuse_or_retry_authorized") is False
            and adoption.get("observed_runtime_facts", {}).get("node_reaped") is True
        )
        adoption_observed = {
            "status": adoption.get("status"),
            "formal_verdict": adoption.get("formal_verdict"),
        }
    except (OSError, ValueError) as exc:
        adoption_ok = False
        adoption_observed = {"error": type(exc).__name__ + ":" + str(exc)[:500]}
    add("attempt_001_terminal_failure_adopted", adoption_ok, True, adoption_observed)

    old_result_path = ROOT / "experiments/published_supervins_v1_ortsession_smoke_20260816_r1/attempt_001/run_result.json"
    try:
        old_result = read_json(old_result_path)
        old_result_ok = (
            old_result.get("status") == "FAIL_DEVELOPMENT_ORTSESSION_CONSTRUCTION_NO_RETRY"
            and old_result.get("authorization", {}).get("node_start_count") == 1
            and old_result.get("authorization", {}).get("retry_authorized") is False
            and old_result.get("runtime", {}).get("termination", {}).get("reaped") is True
        )
        old_result_observed = {"status": old_result.get("status"), "authorization": old_result.get("authorization")}
    except (OSError, ValueError) as exc:
        old_result_ok = False
        old_result_observed = {"error": type(exc).__name__ + ":" + str(exc)[:500]}
    add("attempt_001_result_terminal_and_immutable", old_result_ok, True, old_result_observed)

    official_head = BASE.git(BASE.OFFICIAL, "rev-parse", "HEAD")
    official_tree = BASE.git(BASE.OFFICIAL, "rev-parse", "HEAD^{tree}")
    official_status = BASE.git(BASE.OFFICIAL, "status", "--porcelain=v1", "--untracked-files=all", "--ignore-submodules=none")
    source_observed = {
        "head": official_head["stdout"].strip(),
        "tree": official_tree["stdout"].strip(),
        "status": official_status["stdout"].splitlines(),
    }
    add(
        "official_source_clean",
        source_observed == {"head": BASE.COMMIT, "tree": BASE.TREE, "status": []},
        {"head": BASE.COMMIT, "tree": BASE.TREE, "status": []},
        source_observed,
    )
    private_diff = BASE.git(BASE.PRIVATE, "diff", "--no-ext-diff", "--no-color", binary=True)
    diff_bytes = private_diff["stdout"] if isinstance(private_diff["stdout"], bytes) else b""
    diff_sha = hashlib.sha256(diff_bytes).hexdigest()
    add("private_repair_diff", diff_sha == BASE.DIFF_SHA256, BASE.DIFF_SHA256, diff_sha)

    runtime_env = runtime_environment(ROOT / ".attempt_002_preflight_ros_home_not_created")
    binary_ldd = BASE.command(["ldd", BASE.BINARY], env=runtime_env)
    provider_ldd = BASE.command(["ldd", BASE.ORT / "lib/libonnxruntime_providers_cuda.so"], env=runtime_env)
    missing = [line.strip() for text in (binary_ldd["stdout"], provider_ldd["stdout"]) for line in text.splitlines() if "not found" in line]
    add(
        "runtime_link_closure",
        binary_ldd["returncode"] == 0 and provider_ldd["returncode"] == 0 and not missing,
        [],
        missing,
    )
    gpu = BASE.command(["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader"])
    add("gpu_visible", gpu["returncode"] == 0 and bool(gpu["stdout"].strip()), "at_least_one_gpu", gpu["stdout"].splitlines())

    nodes = process_pids_by_comm("supervins_node")
    add("no_preexisting_supervins_node", not nodes, [], nodes)
    master_processes = port_processes()
    add("no_preexisting_attempt_002_master_process", not master_processes, [], master_processes)
    bound = port_is_bound()
    add("attempt_002_master_port_unbound", not bound, False, bound)
    add("fresh_attempt_002_namespace", not EVIDENCE.exists(), "ABSENT", "PRESENT" if EVIDENCE.exists() else "ABSENT")
    try:
        master_fd, slave_fd = pty.openpty()
        os.close(master_fd)
        os.close(slave_fd)
        pty_ok = True
        pty_observed = "openpty_close_ok"
    except OSError as exc:
        pty_ok = False
        pty_observed = type(exc).__name__ + ":" + str(exc)[:500]
    add("pseudo_terminal_available", pty_ok, True, pty_observed)

    return {
        "schema_version": "aqua-fe-published-supervins-v1-ortsession-smoke-attempt-002-preflight-v1",
        "checked_at": now_iso(),
        "status": "GO_EXACTLY_ONE_EMPTY_MASTER_AND_ONE_NODE_START" if not failures else "BLOCKED_NO_MASTER_OR_NODE_START",
        "ready": not failures,
        "failures": failures,
        "checks": checks,
        "boundary": {
            "roscore_started": False,
            "supervins_node_started": False,
            "ort_session_created": False,
            "model_inference_run": False,
            "ros_input_messages_published": False,
        },
    }


def drain_pty(master_fds, streams, buffers, wait_seconds=0.0):
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


def classify_output(stdout_bytes, stderr_bytes):
    text = (stdout_bytes + b"\n" + stderr_bytes).decode("utf-8", "replace")
    lower = text.lower()
    return {
        "success_marker": SUCCESS_MARKER,
        "success_marker_count": lower.count(SUCCESS_MARKER.lower()),
        "forbidden_inference_markers_found": [marker for marker in FORBIDDEN_INFERENCE_MARKERS if marker.lower() in lower],
    }


def post_pin_audit(protocol, old_freeze):
    pins = all_protocol_pins(protocol, old_freeze)
    lock = read_json(LOCK)
    pins.update({str(PROTOCOL): lock["protocol"], str(Path(__file__).resolve()): lock["runner"], str(TESTS): lock["tests"]})
    outcomes = {}
    for path_text, expected in pins.items():
        ok, observed = check_identity(path_text, expected)
        outcomes[path_text] = {"ok": ok, "expected": expected, "observed": observed}
    return outcomes


def terminal_result_without_node(preflight, master_proc, master_termination, reason, master_artifacts):
    result = {
        "schema_version": "aqua-fe-published-supervins-v1-ortsession-smoke-attempt-002-result-v1",
        "status": "FAIL_ATTEMPT_002_MASTER_STAGE_NO_NODE_START_NO_RETRY",
        "return_code": 1,
        "reason": reason,
        "preflight_ready": preflight["ready"],
        "authorization": {"roscore_start_count": 1 if master_proc else 0, "node_start_count": 0, "retry_authorized": False},
        "master_termination": master_termination,
        "artifacts": master_artifacts,
        "claim_boundary": {"ort_sessions_constructed": False, "model_inference_run": False, "ros_input_messages_published": False},
        "next_stage_automatically_authorized": False,
    }
    identity = write_json_exclusive(ATTEMPT / "run_result.json", result)
    result["run_result_identity"] = identity
    print(json.dumps(result, sort_keys=True))
    return 1


def run_once(token):
    if token != AUTHORIZATION_TOKEN:
        print(json.dumps({"status": "BLOCKED_INVALID_AUTHORIZATION_TOKEN_NO_START", "return_code": 2}, sort_keys=True))
        return 2
    preflight = collect_preflight()
    if not preflight["ready"]:
        print(json.dumps({"status": "BLOCKED_PREFLIGHT_NO_START", "return_code": 3, "preflight": preflight}, sort_keys=True))
        return 3

    protocol = read_json(PROTOCOL)
    old_freeze = read_json(OLD_FREEZE)
    EVIDENCE.mkdir(mode=0o755, parents=False, exist_ok=False)
    ATTEMPT.mkdir(mode=0o755, exist_ok=False)
    ros_home = ATTEMPT / "ros_home"
    (ros_home / "log").mkdir(mode=0o755, parents=True, exist_ok=False)
    preflight_identity = write_json_exclusive(ATTEMPT / "preflight_result.json", preflight)

    master_claim = {
        "schema_version": "aqua-fe-published-supervins-v1-attempt-002-roscore-start-claim-v1",
        "created_at": now_iso(),
        "authorization_token_sha256": hashlib.sha256(token.encode()).hexdigest(),
        "command": MASTER_COMMAND,
        "maximum_roscore_starts": 1,
        "roscore_start_count_before_claim": 0,
        "preflight_result": preflight_identity,
        "execution_lock": file_identity(LOCK),
    }
    master_claim_identity = write_json_exclusive(ATTEMPT / "roscore_start_claim.json", master_claim)
    master_stdout_path = ATTEMPT / "roscore.stdout.log"
    master_stderr_path = ATTEMPT / "roscore.stderr.log"
    master_proc = None
    master_launch_error = None
    master_ready_observed = False
    master_state_before_node = None
    master_started_at = now_iso()
    with master_stdout_path.open("xb") as master_stdout, master_stderr_path.open("xb") as master_stderr:
        try:
            master_proc = subprocess.Popen(
                MASTER_COMMAND,
                cwd=str(ATTEMPT),
                env=runtime_environment(ros_home),
                stdin=subprocess.DEVNULL,
                stdout=master_stdout,
                stderr=master_stderr,
                start_new_session=True,
            )
            write_json_exclusive(
                ATTEMPT / "roscore_process_started.json",
                {"started_at": master_started_at, "pid": master_proc.pid, "process_group": master_proc.pid, "command": MASTER_COMMAND, "roscore_start_count": 1},
            )
            deadline = time.monotonic() + MASTER_READY_TIMEOUT
            while time.monotonic() < deadline:
                if master_ready():
                    master_ready_observed = True
                    master_state_before_node = get_system_state()
                    break
                if master_proc.poll() is not None:
                    break
                time.sleep(0.10)
        except OSError as exc:
            master_launch_error = type(exc).__name__ + ":" + str(exc)[:500]
        master_stdout.flush()
        master_stderr.flush()
        os.fsync(master_stdout.fileno())
        os.fsync(master_stderr.fileno())

    master_preconditions = {
        "launch_error_absent": master_launch_error is None,
        "master_ready": master_ready_observed,
        "system_state_query_ok": bool(master_state_before_node and master_state_before_node.get("ok")),
        "no_input_publishers_before_node": bool(master_state_before_node and master_state_before_node.get("ok") and not master_state_before_node.get("input_publishers")),
        "only_core_nodes_before_node": bool(master_state_before_node and master_state_before_node.get("ok") and set(master_state_before_node.get("nodes", [])) <= {"/rosout"}),
    }
    if not all(master_preconditions.values()):
        master_termination = terminate_and_reap(master_proc)
        artifacts = {
            "roscore_start_claim": master_claim_identity,
            "roscore_stdout": file_identity(master_stdout_path),
            "roscore_stderr": file_identity(master_stderr_path),
        }
        return terminal_result_without_node(
            preflight,
            master_proc,
            master_termination,
            {"master_launch_error": master_launch_error, "master_preconditions": master_preconditions, "state": master_state_before_node},
            artifacts,
        )

    node_claim = {
        "schema_version": "aqua-fe-published-supervins-v1-attempt-002-node-start-claim-v1",
        "created_at": now_iso(),
        "authorization_token_sha256": hashlib.sha256(token.encode()).hexdigest(),
        "command": NODE_COMMAND,
        "maximum_node_starts": 1,
        "node_start_count_before_claim": 0,
        "master_pid": master_proc.pid,
        "master_state_before_node": master_state_before_node,
        "roscore_start_claim": master_claim_identity,
    }
    node_claim_identity = write_json_exclusive(ATTEMPT / "node_start_claim.json", node_claim)

    stdout_path = ATTEMPT / "node.stdout.log"
    stderr_path = ATTEMPT / "node.stderr.log"
    stdout_master, stdout_slave = pty.openpty()
    stderr_master, stderr_slave = pty.openpty()
    os.set_blocking(stdout_master, False)
    os.set_blocking(stderr_master, False)
    master_fds = [stdout_master, stderr_master]
    stdout_buffer = bytearray()
    stderr_buffer = bytearray()
    buffers = {stdout_master: stdout_buffer, stderr_master: stderr_buffer}
    node_proc = None
    node_launch_error = None
    marker_observed = False
    marker_elapsed = None
    state_at_marker = None
    fd_snapshot = []
    node_started_at = now_iso()
    node_start_monotonic = time.monotonic()
    node_termination = {"events": [], "returncode": None, "sigkill_used": False, "reaped": False}

    with stdout_path.open("xb") as stdout_stream, stderr_path.open("xb") as stderr_stream:
        streams = {stdout_master: stdout_stream, stderr_master: stderr_stream}
        try:
            node_proc = subprocess.Popen(
                NODE_COMMAND,
                cwd=str(ATTEMPT),
                env=runtime_environment(ros_home),
                stdin=subprocess.DEVNULL,
                stdout=stdout_slave,
                stderr=stderr_slave,
                start_new_session=True,
                close_fds=True,
            )
            os.close(stdout_slave)
            os.close(stderr_slave)
            stdout_slave = stderr_slave = -1
            write_json_exclusive(
                ATTEMPT / "node_process_started.json",
                {"started_at": node_started_at, "pid": node_proc.pid, "process_group": node_proc.pid, "command": NODE_COMMAND, "node_start_count": 1, "capture": "two_dedicated_ptys"},
            )
            deadline = node_start_monotonic + NODE_TIMEOUT
            while time.monotonic() < deadline:
                drain_pty(master_fds, streams, buffers, 0.10)
                classification = classify_output(bytes(stdout_buffer), bytes(stderr_buffer))
                if classification["success_marker_count"] >= 1:
                    marker_observed = True
                    marker_elapsed = time.monotonic() - node_start_monotonic
                    fd_snapshot = snapshot_open_fds(node_proc.pid)
                    state_at_marker = get_system_state()
                    break
                if node_proc.poll() is not None:
                    break
        except OSError as exc:
            node_launch_error = type(exc).__name__ + ":" + str(exc)[:500]
        finally:
            for slave in (stdout_slave, stderr_slave):
                if slave >= 0:
                    os.close(slave)
            node_termination = terminate_and_reap(node_proc)
            drain_deadline = time.monotonic() + 0.5
            while master_fds and time.monotonic() < drain_deadline:
                drain_pty(master_fds, streams, buffers, 0.05)
            for fd in (stdout_master, stderr_master):
                try:
                    os.close(fd)
                except OSError:
                    pass
            stdout_stream.flush()
            stderr_stream.flush()
            os.fsync(stdout_stream.fileno())
            os.fsync(stderr_stream.fileno())

    master_termination = terminate_and_reap(master_proc)
    time.sleep(0.10)
    classification = classify_output(bytes(stdout_buffer), bytes(stderr_buffer))
    dataset_fds = [item for item in fd_snapshot if "/datasets/" in item["target"] or item["target"].lower().endswith(".bag")]
    input_publishers_at_marker = (
        state_at_marker.get("input_publishers", {})
        if state_at_marker and state_at_marker.get("ok")
        else {"state_query": ["failed"]}
    )
    post_pins = post_pin_audit(protocol, old_freeze)
    changed_pins = [path for path, item in post_pins.items() if not item["ok"]]
    post_nodes = process_pids_by_comm("supervins_node")
    post_master_processes = port_processes()
    post_port_bound = port_is_bound()

    pass_conditions = {
        "preflight_go": preflight["ready"],
        "master_start_count_exactly_one": master_proc is not None,
        "master_ready_before_node": master_ready_observed,
        "no_input_publishers_before_node": not master_state_before_node.get("input_publishers"),
        "node_start_count_exactly_one": node_proc is not None,
        "node_launch_error_absent": node_launch_error is None,
        "success_marker_observed_before_timeout": marker_observed and marker_elapsed is not None and marker_elapsed <= NODE_TIMEOUT,
        "success_marker_persisted": classification["success_marker_count"] >= 1,
        "inference_markers_absent": not classification["forbidden_inference_markers_found"],
        "no_input_publishers_at_marker": not input_publishers_at_marker,
        "no_dataset_or_bag_fd_at_marker": not dataset_fds,
        "node_reaped": node_termination["reaped"],
        "roscore_reaped": master_termination["reaped"],
        "no_post_supervins_process": not post_nodes,
        "no_post_attempt_002_master_process": not post_master_processes,
        "master_port_unbound_post": not post_port_bound,
        "all_pins_unchanged_post": not changed_pins,
    }
    passed = all(pass_conditions.values())
    status = PASS_STATUS if passed else "FAIL_ATTEMPT_002_SESSION_SMOKE_NO_RETRY"
    artifacts = {
        "preflight_result": preflight_identity,
        "roscore_start_claim": master_claim_identity,
        "node_start_claim": node_claim_identity,
        "roscore_stdout": file_identity(master_stdout_path),
        "roscore_stderr": file_identity(master_stderr_path),
        "node_stdout": file_identity(stdout_path),
        "node_stderr": file_identity(stderr_path),
        "roscore_process_started": file_identity(ATTEMPT / "roscore_process_started.json"),
        "node_process_started": file_identity(ATTEMPT / "node_process_started.json"),
    }
    result = {
        "schema_version": "aqua-fe-published-supervins-v1-ortsession-smoke-attempt-002-result-v1",
        "status": status,
        "return_code": 0 if passed else 1,
        "evaluable": True,
        "authorization": {
            "attempt": "attempt_002",
            "roscore_start_count": 1 if master_proc else 0,
            "node_start_count": 1 if node_proc else 0,
            "retry_authorized": False,
        },
        "master": {
            "command": MASTER_COMMAND,
            "pid": master_proc.pid if master_proc else None,
            "ready": master_ready_observed,
            "state_before_node": master_state_before_node,
            "termination": master_termination,
            "post_port_bound": post_port_bound,
            "post_master_processes": post_master_processes,
        },
        "node": {
            "command": NODE_COMMAND,
            "pid": node_proc.pid if node_proc else None,
            "launch_error": node_launch_error,
            "marker_elapsed_seconds": marker_elapsed,
            "termination": node_termination,
            "post_supervins_pids": post_nodes,
            "capture": {"stdout": "DEDICATED_PTY", "stderr": "DEDICATED_PTY"},
        },
        "session_witness": {**classification, "marker_observed_during_run": marker_observed, "causal_interpretation": "Pinned source returns from extractor and matcher OrtSession construction before emitting the persisted marker."},
        "no_data_evidence": {
            "input_publishers_before_node": master_state_before_node.get("input_publishers"),
            "input_publishers_at_marker": input_publishers_at_marker,
            "rosbag_processes_started_by_runner": 0,
            "input_publisher_processes_started_by_runner": 0,
            "dataset_paths_opened_by_runner": 0,
            "open_fd_snapshot_at_marker": fd_snapshot,
            "dataset_or_bag_fd_targets": dataset_fds,
        },
        "pass_conditions": pass_conditions,
        "post_pin_audit": {"changed_pins": changed_pins, "checks": post_pins},
        "artifacts": artifacts,
        "claim_boundary": {
            "accuracy_claim_authorized": False,
            "formal_baseline_authorized": False,
            "model_inference_run": False,
            "ort_sessions_constructed": passed,
            "ros_input_messages_published": False,
            "trajectory_run": False,
        },
        "next_stage_automatically_authorized": False,
    }
    result_identity = write_json_exclusive(ATTEMPT / "run_result.json", result)
    result["run_result_identity"] = result_identity
    print(json.dumps(result, sort_keys=True))
    return 0 if passed else 1


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--action", required=True, choices=("preflight", "run"))
    parser.add_argument("--authorization-token")
    args = parser.parse_args()
    if args.action == "preflight":
        result = collect_preflight()
        print(json.dumps(result, sort_keys=True))
        return 0 if result["ready"] else 1
    return run_once(args.authorization_token)


if __name__ == "__main__":
    sys.exit(main())
