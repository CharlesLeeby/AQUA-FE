#!/usr/bin/env python3
"""One-shot SuperVINS extractor/matcher smoke on frozen official EuRoC data.

This DEVELOPMENT-ONLY controller starts one isolated roscore, one unchanged
SuperVINS node, and one minimal raw cam0+imu0 publisher.  The selected data are
the frozen first two seconds of official MH_01_easy, *not* the V2_01 sequence
recommended by the SuperVINS README.  No bag, cam1, ground truth, trajectory
assessment, APE/RPE, or formal baseline conclusion is permitted here.
"""

from __future__ import annotations

import argparse
import errno
import hashlib
import importlib.util
import json
import os
import pty
import re
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
STAGE2_RUNNER = ROOT / "scripts/run_published_supervins_v1_ortsession_smoke_attempt_002.py"
SPEC = importlib.util.spec_from_file_location("supervins_stage2_attempt_002", STAGE2_RUNNER)
STAGE2 = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(STAGE2)
BASE = STAGE2.BASE

PROTOCOL = ROOT / "papers/supervins_v1_official_euroc_mh01_first2s_inference_smoke_freeze_v1.json"
LOCK = ROOT / "papers/supervins_v1_official_euroc_mh01_first2s_inference_smoke_execution_lock_v1.json"
TESTS = ROOT / "scripts/tests/test_run_published_supervins_v1_official_euroc_mh01_first2s_inference_smoke_v1.py"
INPUT_MANIFEST = ROOT / "papers/supervins_v1_official_euroc_mh01_first2s_input_manifest_v1.json"
PUBLISHER = ROOT / "scripts/publish_supervins_euroc_mh01_first2s_v1.py"
STAGE2_FREEZE = ROOT / "papers/supervins_v1_ortsession_construction_smoke_freeze_v1.json"

EVIDENCE = ROOT / "experiments/published_supervins_v1_official_euroc_mh01_first2s_inference_smoke_20260816_r1"
ATTEMPT = EVIDENCE / "attempt_001"

MASTER_HOST = "127.0.0.1"
MASTER_PORT = 11553
MASTER_URI = "http://127.0.0.1:11553"
MASTER_COMMAND = ["/opt/ros/noetic/bin/roscore", "-p", "11553"]
NODE_COMMAND = [str(BASE.BINARY), str(BASE.CONFIG)]
PUBLISHER_COMMAND = [
    "/usr/bin/python3",
    "-B",
    str(PUBLISHER),
    "--action",
    "run",
    "--authorization-token",
    "SUPERVINS_STAGE3_MH01_FIRST2S_PUBLISH_ONCE",
]
PUBLISHER_PREFLIGHT_COMMAND = ["/usr/bin/python3", "-B", str(PUBLISHER), "--action", "preflight"]

AUTHORIZATION_TOKEN = "SUPERVINS_STAGE3_MH01_FIRST2S_ATTEMPT_001_START_ONCE"
CALLER_ID = "/aqua_fe_supervins_stage3_controller"
NODE_NAME = "/supervins_estimator"
PUBLISHER_NODE = "/aqua_fe_euroc_mh01_first2s_publisher"
INPUT_TOPICS = ["/imu0", "/cam0/image_raw"]
EXPECTED_TOPIC_TYPES = {"/imu0": "sensor_msgs/Imu", "/cam0/image_raw": "sensor_msgs/Image"}
SESSION_MARKER = "waiting for image and imu..."
EXTRACT_MARKER = "extract feature time"
MATCH_RE = re.compile(r"matches\.size\(\)\s*=\s*(-?\d+)", re.IGNORECASE)

MASTER_READY_TIMEOUT = 12.0
NODE_READY_TIMEOUT = 15.0
PUBLISHER_CONNECTION_TIMEOUT = 12.0
INFERENCE_TIMEOUT = 90.0
TERM_GRACE_SECONDS = 3.0
PASS_STATUS = "PASS_DEVELOPMENT_OFFICIAL_MH01_FIRST2S_EXTRACTOR_MATCHER_INFERENCE"


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
        offset = 0
        while offset < len(payload):
            offset += os.write(fd, payload[offset:])
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


def runtime_environment(ros_home):
    env = BASE.runtime_environment(ros_home)
    env.update(
        {
            "ROS_MASTER_URI": MASTER_URI,
            "ROS_HOSTNAME": MASTER_HOST,
            "ROS_HOME": str(ros_home),
            "ROS_LOG_DIR": str(Path(ros_home) / "log"),
            "PYTHONUNBUFFERED": "1",
        }
    )
    return env


def port_is_bound():
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(0.2)
    try:
        return sock.connect_ex((MASTER_HOST, MASTER_PORT)) == 0
    finally:
        sock.close()


def is_attempt_master_cmdline(parts):
    executables = {Path(part).name for part in parts[:3]}
    return "11553" in parts and bool(executables & {"roscore", "rosmaster", "roslaunch"})


def port_processes():
    found = []
    for path in Path("/proc").glob("[0-9]*/cmdline"):
        try:
            parts = [p.decode("utf-8", "replace") for p in path.read_bytes().split(b"\0") if p]
        except OSError:
            continue
        if is_attempt_master_cmdline(parts):
            found.append({"pid": int(path.parent.name), "argv": parts})
    return sorted(found, key=lambda item: item["pid"])


def publisher_processes():
    found = []
    target = str(PUBLISHER)
    for path in Path("/proc").glob("[0-9]*/cmdline"):
        try:
            parts = [p.decode("utf-8", "replace") for p in path.read_bytes().split(b"\0") if p]
        except OSError:
            continue
        if target in parts:
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
    }


def get_system_state():
    try:
        return {"ok": True, **parse_system_state(master_call("getSystemState"))}
    except (OSError, socket.timeout, xmlrpc.client.Error, ValueError) as exc:
        return {"ok": False, "error": type(exc).__name__ + ":" + str(exc)[:500]}


def input_connection_contract(state, publisher_required):
    if not state or not state.get("ok"):
        return False
    subscribers = state["input_subscribers"]
    publishers = state["input_publishers"]
    subscribers_ok = all(subscribers.get(topic) == [NODE_NAME] for topic in INPUT_TOPICS)
    if publisher_required:
        publishers_ok = all(publishers.get(topic) == [PUBLISHER_NODE] for topic in INPUT_TOPICS)
    else:
        publishers_ok = not publishers
    return subscribers_ok and publishers_ok


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
    text = (stdout_bytes + b"\n" + stderr_bytes).decode("utf-8", "replace")
    values = [int(value) for value in MATCH_RE.findall(text)]
    return {
        "session_marker_count": text.lower().count(SESSION_MARKER.lower()),
        "extract_feature_time_count": text.lower().count(EXTRACT_MARKER.lower()),
        "matches_size_count": len(values),
        "matches_size_values": values,
    }


def parse_publisher_output(stdout_bytes):
    records = []
    for line in stdout_bytes.decode("utf-8", "replace").splitlines():
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            records.append(value)
    terminals = [record for record in records if record.get("status") == "PUBLISH_COMPLETE"]
    cameras = [record for record in records if record.get("event") == "CAMERA_PUBLISHED"]
    return {"records": records, "terminal_records": terminals, "camera_records": cameras}


def run_publisher_preflight():
    result = BASE.command(PUBLISHER_PREFLIGHT_COMMAND, timeout=60)
    parsed = None
    for line in result["stdout"].splitlines():
        try:
            candidate = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(candidate, dict):
            parsed = candidate
    return {"command": PUBLISHER_PREFLIGHT_COMMAND, **result, "parsed": parsed}


def all_frozen_pins(protocol, stage2_freeze, manifest):
    pins = {}
    for item in protocol["adopted_stage_2"].values():
        pins[item["path"]] = {"sha256": item["sha256"], "size_bytes": item["size_bytes"]}
    for item in (protocol["input"]["manifest"], protocol["input"]["publisher"]):
        pins[item["path"]] = {"sha256": item["sha256"], "size_bytes": item["size_bytes"]}
    pins.update(protocol["publisher_runtime_pins"])
    for item in protocol["exact_supervins_runtime_selection"].values():
        pins[item["path"]] = {"sha256": item["sha256"], "size_bytes": item["size_bytes"]}
    pins.update(protocol["trajectory_artifact_pre_pins"])
    pins.update(stage2_freeze["pinned_r1_governance"])
    pins.update(stage2_freeze["pinned_runtime_artifacts"])
    pins.update(manifest["source_metadata_pins"])
    adoption = manifest["official_source_adoption"]
    pins[adoption["path"]] = {"sha256": adoption["sha256"], "size_bytes": adoption["size_bytes"]}
    download = adoption["download_manifest"]
    pins[download["path"]] = {"sha256": download["sha256"], "size_bytes": download["size_bytes"]}
    inventory = adoption["full_extracted_inventory"]
    pins[inventory["path"]] = {"sha256": inventory["sha256"], "size_bytes": inventory["size_bytes"]}
    return pins


def validate_lock(pins):
    observed = {"path": str(LOCK)}
    try:
        lock = read_json(LOCK)
        observed["identity"] = file_identity(LOCK)
    except (OSError, ValueError) as exc:
        observed["error"] = type(exc).__name__ + ":" + str(exc)[:500]
        return False, observed
    expected_special = {
        "protocol": file_identity(PROTOCOL),
        "runner": file_identity(Path(__file__).resolve()),
        "tests": file_identity(TESTS),
        "publisher": file_identity(PUBLISHER),
        "input_manifest": file_identity(INPUT_MANIFEST),
    }
    pin_digest = hashlib.sha256(canonical_json_bytes(pins)).hexdigest()
    ok = all(
        (
            lock.get("schema_version") == "aqua-fe-published-supervins-v1-official-euroc-mh01-first2s-inference-smoke-execution-lock-v1",
            lock.get("status") == "LOCKED_FOR_EXACTLY_ONE_MASTER_ONE_NODE_ONE_PUBLISHER_START",
            lock.get("authorization_token") == AUTHORIZATION_TOKEN,
            lock.get("master_uri") == MASTER_URI,
            lock.get("master_command") == MASTER_COMMAND,
            lock.get("node_command") == NODE_COMMAND,
            lock.get("publisher_command") == PUBLISHER_COMMAND,
            lock.get("maximum_roscore_starts") == 1,
            lock.get("maximum_node_starts") == 1,
            lock.get("maximum_publisher_starts") == 1,
            lock.get("retry_authorized") is False,
            lock.get("protocol") == expected_special["protocol"],
            lock.get("runner") == expected_special["runner"],
            lock.get("tests") == expected_special["tests"],
            lock.get("publisher") == expected_special["publisher"],
            lock.get("input_manifest") == expected_special["input_manifest"],
            lock.get("pinned_file_count") == len(pins),
            lock.get("pinned_files_canonical_sha256") == pin_digest,
            lock.get("fresh_evidence_root") == str(EVIDENCE),
        )
    )
    observed.update({"special_identities": expected_special, "pinned_file_count": len(pins), "pinned_files_canonical_sha256": pin_digest})
    return ok, observed


def topic_contract(protocol, manifest):
    config_text = Path(protocol["exact_supervins_runtime_selection"]["config"]["path"]).read_text(encoding="utf-8")
    mapping = manifest["ros_mapping"]
    observed = {
        "manifest_topics_and_types": {
            mapping["imu_topic"]: mapping["imu_message_type"],
            mapping["camera_topic"]: mapping["camera_message_type"],
        },
        "config_has_imu_topic": 'imu_topic: "/imu0"' in config_text,
        "config_has_camera_topic": 'image0_topic: "/cam0/image_raw"' in config_text,
        "publisher_imports_image": "from sensor_msgs.msg import Image, Imu" in PUBLISHER.read_text(encoding="utf-8"),
    }
    ok = (
        observed["manifest_topics_and_types"] == EXPECTED_TOPIC_TYPES
        and observed["config_has_imu_topic"]
        and observed["config_has_camera_topic"]
        and observed["publisher_imports_image"]
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
        stage2_freeze = read_json(STAGE2_FREEZE)
        manifest = read_json(INPUT_MANIFEST)
        pins = all_frozen_pins(protocol, stage2_freeze, manifest)
        semantics_ok = (
            protocol.get("status") == "FROZEN_BEFORE_STAGE_3_MASTER_NODE_OR_PUBLISHER_START"
            and protocol.get("sequence_boundary", {}).get("input_is_readme_recommended_sequence") is False
            and protocol.get("claim_boundary", {}).get("feature_extractor_inference_authorized") is True
            and protocol.get("claim_boundary", {}).get("matcher_inference_authorized") is True
            and protocol.get("claim_boundary", {}).get("full_vio_or_trajectory_run_authorized") is False
            and protocol.get("claim_boundary", {}).get("ape_rpe_authorized") is False
            and protocol.get("one_shot_authority", {}).get("maximum_roscore_starts") == 1
            and protocol.get("one_shot_authority", {}).get("maximum_node_starts") == 1
            and protocol.get("one_shot_authority", {}).get("maximum_publisher_starts") == 1
            and protocol.get("ros", {}).get("master_command") == MASTER_COMMAND
            and protocol.get("ros", {}).get("node_command") == NODE_COMMAND
            and protocol.get("ros", {}).get("publisher_command") == PUBLISHER_COMMAND
        )
        add("protocol_semantics", semantics_ok, True, protocol.get("claim_boundary"))
        add(
            "manifest_semantics",
            manifest.get("status") == "FROZEN_BEFORE_STAGE_3_ROS_OR_MODEL_START"
            and manifest.get("sequence_disclosure", {}).get("selected_sequence_is_readme_recommended_v2_01") is False
            and manifest.get("selection", {}).get("camera_count") == 41
            and manifest.get("selection", {}).get("imu_count") == 401
            and manifest.get("selection", {}).get("event_count") == 442,
            True,
            {"status": manifest.get("status"), "selection": manifest.get("selection")},
        )
    except (OSError, ValueError, KeyError) as exc:
        protocol, stage2_freeze, manifest, pins = {}, {}, {}, {}
        add("protocol_and_manifest_load", False, True, type(exc).__name__ + ":" + str(exc)[:500])

    for path_text, expected in pins.items():
        ok, observed = check_identity(path_text, expected)
        add("pin:" + path_text, ok, expected, observed)

    lock_ok, lock_observed = validate_lock(pins) if pins else (False, {})
    add("execution_lock", lock_ok, True, lock_observed)

    if protocol and manifest:
        compatible, observed = topic_contract(protocol, manifest)
        add("topic_message_type_contract", compatible, EXPECTED_TOPIC_TYPES, observed)

    publisher_preflight = run_publisher_preflight()
    publisher_summary = publisher_preflight.get("parsed") or {}
    publisher_ok = (
        publisher_preflight["returncode"] == 0
        and publisher_summary.get("status") == "READY_NO_ROS_STARTED"
        and publisher_summary.get("ready") is True
        and publisher_summary.get("ros_started") is False
        and publisher_summary.get("camera_count") == 41
        and publisher_summary.get("imu_count") == 401
        and publisher_summary.get("event_count") == 442
    )
    add("publisher_no_ros_input_preflight", publisher_ok, True, publisher_preflight)

    try:
        stage2_result = read_json(protocol["adopted_stage_2"]["run_result"]["path"])
        stage2_seal = read_json(protocol["adopted_stage_2"]["pass_seal"]["path"])
        stage2_ok = stage2_result.get("status") == STAGE2.PASS_STATUS and stage2_seal.get("status") == "SEALED_PASS_DEVELOPMENT_ORTSESSION_CONSTRUCTION_ONLY"
        stage2_observed = {"result": stage2_result.get("status"), "seal": stage2_seal.get("status")}
    except (OSError, ValueError, KeyError) as exc:
        stage2_ok = False
        stage2_observed = {"error": type(exc).__name__ + ":" + str(exc)[:500]}
    add("stage2_pass_adopted", stage2_ok, True, stage2_observed)

    official_head = BASE.git(BASE.OFFICIAL, "rev-parse", "HEAD")
    official_tree = BASE.git(BASE.OFFICIAL, "rev-parse", "HEAD^{tree}")
    official_status = BASE.git(BASE.OFFICIAL, "status", "--porcelain=v1", "--untracked-files=all", "--ignore-submodules=none")
    source_observed = {"head": official_head["stdout"].strip(), "tree": official_tree["stdout"].strip(), "status": official_status["stdout"].splitlines()}
    add("official_source_clean", source_observed == {"head": BASE.COMMIT, "tree": BASE.TREE, "status": []}, {"head": BASE.COMMIT, "tree": BASE.TREE, "status": []}, source_observed)
    private_diff = BASE.git(BASE.PRIVATE, "diff", "--no-ext-diff", "--no-color", binary=True)
    diff_bytes = private_diff["stdout"] if isinstance(private_diff["stdout"], bytes) else b""
    diff_sha = hashlib.sha256(diff_bytes).hexdigest()
    add("private_repair_diff", diff_sha == BASE.DIFF_SHA256, BASE.DIFF_SHA256, diff_sha)

    runtime_env = runtime_environment(ROOT / ".stage3_preflight_ros_home_not_created")
    binary_ldd = BASE.command(["ldd", BASE.BINARY], env=runtime_env)
    provider_ldd = BASE.command(["ldd", BASE.ORT / "lib/libonnxruntime_providers_cuda.so"], env=runtime_env)
    missing = [line.strip() for text in (binary_ldd["stdout"], provider_ldd["stdout"]) for line in text.splitlines() if "not found" in line]
    add("runtime_link_closure", binary_ldd["returncode"] == 0 and provider_ldd["returncode"] == 0 and not missing, [], missing)
    gpu = BASE.command(["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader"])
    add("gpu_visible", gpu["returncode"] == 0 and bool(gpu["stdout"].strip()), "at_least_one_gpu", gpu["stdout"].splitlines())

    node_pids = BASE.process_pids_by_comm("supervins_node")
    add("no_preexisting_supervins_node", not node_pids, [], node_pids)
    publisher_pids = publisher_processes()
    add("no_preexisting_stage3_publisher", not publisher_pids, [], publisher_pids)
    masters = port_processes()
    add("no_preexisting_stage3_master", not masters, [], masters)
    bound = port_is_bound()
    add("stage3_master_port_unbound", not bound, False, bound)
    add("fresh_stage3_namespace", not EVIDENCE.exists(), "ABSENT", "PRESENT" if EVIDENCE.exists() else "ABSENT")
    claims = [ATTEMPT / name for name in ("roscore_start_claim.json", "node_start_claim.json", "publisher_start_claim.json")]
    present_claims = [str(path) for path in claims if path.exists()]
    add("all_stage3_start_claims_absent", not present_claims, [], present_claims)
    try:
        master_fd, slave_fd = pty.openpty()
        os.close(master_fd)
        os.close(slave_fd)
        pty_ok, pty_observed = True, "openpty_close_ok"
    except OSError as exc:
        pty_ok, pty_observed = False, type(exc).__name__ + ":" + str(exc)[:500]
    add("pseudo_terminal_available", pty_ok, True, pty_observed)

    return {
        "schema_version": "aqua-fe-published-supervins-v1-official-euroc-mh01-first2s-inference-smoke-preflight-v1",
        "checked_at": now_iso(),
        "status": "GO_EXACTLY_ONE_MASTER_ONE_NODE_ONE_PUBLISHER_START" if not failures else "BLOCKED_NO_PROCESS_START",
        "ready": not failures,
        "failures": failures,
        "checks": checks,
        "boundary": {"roscore_started": False, "supervins_node_started": False, "publisher_started": False, "model_inference_run": False, "trajectory_or_ape_rpe_run": False},
    }


def post_pin_audit(protocol, stage2_freeze, manifest):
    pins = all_frozen_pins(protocol, stage2_freeze, manifest)
    lock = read_json(LOCK)
    pins.update(
        {
            str(PROTOCOL): lock["protocol"],
            str(Path(__file__).resolve()): lock["runner"],
            str(TESTS): lock["tests"],
            str(PUBLISHER): lock["publisher"],
            str(INPUT_MANIFEST): lock["input_manifest"],
        }
    )
    outcomes = {}
    for path_text, expected in pins.items():
        ok, observed = check_identity(path_text, expected)
        outcomes[path_text] = {"ok": ok, "expected": expected, "observed": observed}
    return outcomes


def write_terminal_result(status, reason, preflight_identity, starts, terminations, artifacts):
    result = {
        "schema_version": "aqua-fe-published-supervins-v1-official-euroc-mh01-first2s-inference-smoke-result-v1",
        "status": status,
        "return_code": 1,
        "reason": reason,
        "authorization": {**starts, "retry_authorized": False},
        "terminations": terminations,
        "artifacts": {"preflight_result": preflight_identity, **artifacts},
        "claim_boundary": {"development_only": True, "model_inference_gate_passed": False, "trajectory_or_ape_rpe_run": False, "formal_baseline_authorized": False},
        "next_stage_automatically_authorized": False,
    }
    identity = write_json_exclusive(ATTEMPT / "run_result.json", result)
    print(json.dumps({**result, "run_result_identity": identity}, sort_keys=True))
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
    stage2_freeze = read_json(STAGE2_FREEZE)
    manifest = read_json(INPUT_MANIFEST)
    EVIDENCE.mkdir(mode=0o755, parents=False, exist_ok=False)
    ATTEMPT.mkdir(mode=0o755, exist_ok=False)
    ros_home = ATTEMPT / "ros_home"
    (ros_home / "log").mkdir(mode=0o755, parents=True, exist_ok=False)
    (ATTEMPT / "time_consumption").mkdir(mode=0o755, exist_ok=False)
    preflight_identity = write_json_exclusive(ATTEMPT / "preflight_result.json", preflight)
    env = runtime_environment(ros_home)

    master_proc = node_proc = publisher_proc = None
    master_termination = node_termination = publisher_termination = None
    starts = {"roscore_start_count": 0, "node_start_count": 0, "publisher_start_count": 0}
    artifacts = {}

    master_claim = {
        "schema_version": "aqua-fe-supervins-stage3-roscore-start-claim-v1",
        "created_at": now_iso(), "authorization_token_sha256": hashlib.sha256(token.encode()).hexdigest(),
        "command": MASTER_COMMAND, "maximum_roscore_starts": 1, "roscore_start_count_before_claim": 0,
        "execution_lock": file_identity(LOCK), "preflight_result": preflight_identity,
    }
    artifacts["roscore_start_claim"] = write_json_exclusive(ATTEMPT / "roscore_start_claim.json", master_claim)
    master_stdout_path = ATTEMPT / "roscore.stdout.log"
    master_stderr_path = ATTEMPT / "roscore.stderr.log"
    master_launch_error = None
    with master_stdout_path.open("xb") as out, master_stderr_path.open("xb") as err:
        try:
            master_proc = subprocess.Popen(MASTER_COMMAND, cwd=str(ATTEMPT), env=env, stdin=subprocess.DEVNULL, stdout=out, stderr=err, start_new_session=True)
            starts["roscore_start_count"] = 1
            write_json_exclusive(ATTEMPT / "roscore_process_started.json", {"started_at": now_iso(), "pid": master_proc.pid, "command": MASTER_COMMAND, "roscore_start_count": 1})
        except OSError as exc:
            master_launch_error = type(exc).__name__ + ":" + str(exc)[:500]
        deadline = time.monotonic() + MASTER_READY_TIMEOUT
        while master_proc and time.monotonic() < deadline and master_proc.poll() is None and not master_ready():
            time.sleep(0.05)
        master_ready_observed = bool(master_proc and master_ready())
        state_before_node = get_system_state() if master_ready_observed else None
    if not (master_launch_error is None and master_ready_observed and state_before_node and state_before_node.get("ok") and not state_before_node.get("input_publishers") and set(state_before_node.get("nodes", [])) <= {"/rosout"}):
        master_termination = terminate_and_reap(master_proc)
        artifacts.update({"roscore_stdout": file_identity(master_stdout_path), "roscore_stderr": file_identity(master_stderr_path)})
        return write_terminal_result("FAIL_STAGE3_MASTER_NO_NODE_OR_PUBLISHER_START_NO_RETRY", {"launch_error": master_launch_error, "ready": master_ready_observed, "state": state_before_node}, preflight_identity, starts, {"master": master_termination}, artifacts)

    node_claim = {
        "schema_version": "aqua-fe-supervins-stage3-node-start-claim-v1", "created_at": now_iso(),
        "authorization_token_sha256": hashlib.sha256(token.encode()).hexdigest(), "command": NODE_COMMAND,
        "maximum_node_starts": 1, "node_start_count_before_claim": 0, "master_pid": master_proc.pid,
        "master_state_before_node": state_before_node, "roscore_start_claim": artifacts["roscore_start_claim"],
    }
    artifacts["node_start_claim"] = write_json_exclusive(ATTEMPT / "node_start_claim.json", node_claim)
    node_stdout_path = ATTEMPT / "node.stdout.log"
    node_stderr_path = ATTEMPT / "node.stderr.log"
    stdout_master, stdout_slave = pty.openpty()
    stderr_master, stderr_slave = pty.openpty()
    os.set_blocking(stdout_master, False)
    os.set_blocking(stderr_master, False)
    master_fds = [stdout_master, stderr_master]
    stdout_buffer, stderr_buffer = bytearray(), bytearray()
    buffers = {stdout_master: stdout_buffer, stderr_master: stderr_buffer}
    node_launch_error = None
    session_marker_elapsed = None
    state_before_publisher = None
    publisher_state_witness = None
    publisher_launch_error = None
    inference_gate_elapsed = None
    node_fd_snapshot = []
    publisher_stdout_path = ATTEMPT / "publisher.stdout.log"
    publisher_stderr_path = ATTEMPT / "publisher.stderr.log"

    with node_stdout_path.open("xb") as node_out, node_stderr_path.open("xb") as node_err:
        streams = {stdout_master: node_out, stderr_master: node_err}
        try:
            node_start_monotonic = time.monotonic()
            node_proc = subprocess.Popen(NODE_COMMAND, cwd=str(ATTEMPT), env=env, stdin=subprocess.DEVNULL, stdout=stdout_slave, stderr=stderr_slave, start_new_session=True, close_fds=True)
            starts["node_start_count"] = 1
            os.close(stdout_slave); stdout_slave = -1
            os.close(stderr_slave); stderr_slave = -1
            write_json_exclusive(ATTEMPT / "node_process_started.json", {"started_at": now_iso(), "pid": node_proc.pid, "command": NODE_COMMAND, "node_start_count": 1, "capture": "two_dedicated_ptys"})
            deadline = node_start_monotonic + NODE_READY_TIMEOUT
            while time.monotonic() < deadline:
                drain_pty(master_fds, streams, buffers, 0.05)
                if classify_node_output(bytes(stdout_buffer), bytes(stderr_buffer))["session_marker_count"] >= 1:
                    session_marker_elapsed = time.monotonic() - node_start_monotonic
                    state_before_publisher = get_system_state()
                    node_fd_snapshot = BASE.snapshot_open_fds(node_proc.pid)
                    break
                if node_proc.poll() is not None:
                    break
            node_ready = session_marker_elapsed is not None and input_connection_contract(state_before_publisher, publisher_required=False)
            if node_ready:
                publisher_claim = {
                    "schema_version": "aqua-fe-supervins-stage3-publisher-start-claim-v1", "created_at": now_iso(),
                    "authorization_token_sha256": hashlib.sha256(token.encode()).hexdigest(), "command": PUBLISHER_COMMAND,
                    "maximum_publisher_starts": 1, "publisher_start_count_before_claim": 0, "node_pid": node_proc.pid,
                    "node_state_before_publisher": state_before_publisher, "node_start_claim": artifacts["node_start_claim"],
                }
                artifacts["publisher_start_claim"] = write_json_exclusive(ATTEMPT / "publisher_start_claim.json", publisher_claim)
                publisher_out = publisher_stdout_path.open("xb")
                publisher_err = publisher_stderr_path.open("xb")
                try:
                    publisher_proc = subprocess.Popen(PUBLISHER_COMMAND, cwd=str(ATTEMPT), env=env, stdin=subprocess.DEVNULL, stdout=publisher_out, stderr=publisher_err, start_new_session=True)
                    starts["publisher_start_count"] = 1
                    write_json_exclusive(ATTEMPT / "publisher_process_started.json", {"started_at": now_iso(), "pid": publisher_proc.pid, "command": PUBLISHER_COMMAND, "publisher_start_count": 1})
                except OSError as exc:
                    publisher_launch_error = type(exc).__name__ + ":" + str(exc)[:500]
                gate_start = time.monotonic()
                gate_deadline = gate_start + INFERENCE_TIMEOUT
                connection_deadline = gate_start + PUBLISHER_CONNECTION_TIMEOUT
                while publisher_proc and time.monotonic() < gate_deadline:
                    drain_pty(master_fds, streams, buffers, 0.05)
                    state = get_system_state()
                    if time.monotonic() <= connection_deadline and input_connection_contract(state, publisher_required=True):
                        publisher_state_witness = state
                    classification = classify_node_output(bytes(stdout_buffer), bytes(stderr_buffer))
                    if classification["extract_feature_time_count"] >= 2 and classification["matches_size_count"] >= 1 and publisher_proc.poll() is not None:
                        inference_gate_elapsed = time.monotonic() - gate_start
                        break
                    if node_proc.poll() is not None:
                        break
                publisher_termination = terminate_and_reap(publisher_proc)
                publisher_out.flush(); publisher_err.flush()
                os.fsync(publisher_out.fileno()); os.fsync(publisher_err.fileno())
                publisher_out.close(); publisher_err.close()
        except OSError as exc:
            node_launch_error = type(exc).__name__ + ":" + str(exc)[:500]
        finally:
            for slave in (stdout_slave, stderr_slave):
                if slave >= 0:
                    os.close(slave)
            publisher_termination = publisher_termination or terminate_and_reap(publisher_proc)
            node_termination = terminate_and_reap(node_proc)
            drain_deadline = time.monotonic() + 0.75
            while master_fds and time.monotonic() < drain_deadline:
                drain_pty(master_fds, streams, buffers, 0.05)
            for fd in (stdout_master, stderr_master):
                try:
                    os.close(fd)
                except OSError:
                    pass
            node_out.flush(); node_err.flush()
            os.fsync(node_out.fileno()); os.fsync(node_err.fileno())

    master_termination = terminate_and_reap(master_proc)
    time.sleep(0.10)
    classification = classify_node_output(bytes(stdout_buffer), bytes(stderr_buffer))
    publisher_bytes = publisher_stdout_path.read_bytes() if publisher_stdout_path.exists() else b""
    publisher_parse = parse_publisher_output(publisher_bytes)
    terminals = publisher_parse["terminal_records"]
    terminal = terminals[-1] if terminals else {}
    publisher_complete = (
        len(terminals) == 1 and terminal.get("camera_count") == 41 and terminal.get("imu_count") == 401
        and terminal.get("event_count") == 442 and terminal.get("rosbag_used") is False
        and terminal.get("groundtruth_published") is False and terminal.get("cam1_published") is False
        and len(publisher_parse["camera_records"]) == 41
        and publisher_termination.get("returncode") == 0
    )

    post_publisher_preflight = run_publisher_preflight()
    post_summary = post_publisher_preflight.get("parsed") or {}
    post_input_ok = post_publisher_preflight["returncode"] == 0 and post_summary.get("status") == "READY_NO_ROS_STARTED" and post_summary.get("ready") is True
    post_pins = post_pin_audit(protocol, stage2_freeze, manifest)
    changed_pins = [path for path, item in post_pins.items() if not item["ok"]]
    trajectory_paths = set(protocol["trajectory_artifact_pre_pins"])
    changed_trajectory = [path for path in changed_pins if path in trajectory_paths]
    post_nodes = BASE.process_pids_by_comm("supervins_node")
    post_publishers = publisher_processes()
    post_masters = port_processes()
    post_port_bound = port_is_bound()
    dataset_or_bag_fds = [item for item in node_fd_snapshot if "/datasets/" in item["target"] or item["target"].lower().endswith(".bag")]

    pass_conditions = {
        "preflight_go": preflight["ready"],
        "roscore_start_count_exactly_one": starts["roscore_start_count"] == 1,
        "node_start_count_exactly_one": starts["node_start_count"] == 1,
        "publisher_start_count_exactly_one": starts["publisher_start_count"] == 1,
        "node_launch_error_absent": node_launch_error is None,
        "publisher_launch_error_absent": publisher_launch_error is None,
        "session_marker_before_timeout": session_marker_elapsed is not None and session_marker_elapsed <= NODE_READY_TIMEOUT,
        "node_subscribers_exact_before_publisher": input_connection_contract(state_before_publisher, publisher_required=False),
        "publisher_identity_witness_exact": publisher_state_witness is not None and input_connection_contract(publisher_state_witness, publisher_required=True),
        "publisher_complete_exact_counts": publisher_complete,
        "extract_feature_time_count_at_least_two": classification["extract_feature_time_count"] >= 2,
        "matches_size_count_at_least_one": classification["matches_size_count"] >= 1,
        "node_reaped": node_termination.get("reaped") is True,
        "publisher_reaped": publisher_termination.get("reaped") is True,
        "roscore_reaped": master_termination.get("reaped") is True,
        "no_post_supervins_process": not post_nodes,
        "no_post_publisher_process": not post_publishers,
        "no_post_master_process": not post_masters,
        "master_port_unbound_post": not post_port_bound,
        "post_input_digest_preflight_passes": post_input_ok,
        "all_frozen_pins_unchanged": not changed_pins,
        "trajectory_artifacts_unchanged": not changed_trajectory,
    }
    passed = all(pass_conditions.values())
    status = PASS_STATUS if passed else "FAIL_STAGE3_OFFICIAL_MH01_FIRST2S_INFERENCE_SMOKE_NO_RETRY"
    artifacts.update(
        {
            "roscore_stdout": file_identity(master_stdout_path), "roscore_stderr": file_identity(master_stderr_path),
            "node_stdout": file_identity(node_stdout_path), "node_stderr": file_identity(node_stderr_path),
            "publisher_stdout": file_identity(publisher_stdout_path) if publisher_stdout_path.exists() else None,
            "publisher_stderr": file_identity(publisher_stderr_path) if publisher_stderr_path.exists() else None,
            "roscore_process_started": file_identity(ATTEMPT / "roscore_process_started.json"),
            "node_process_started": file_identity(ATTEMPT / "node_process_started.json"),
            "publisher_process_started": file_identity(ATTEMPT / "publisher_process_started.json") if (ATTEMPT / "publisher_process_started.json").exists() else None,
        }
    )
    result = {
        "schema_version": "aqua-fe-published-supervins-v1-official-euroc-mh01-first2s-inference-smoke-result-v1",
        "status": status, "return_code": 0 if passed else 1, "evaluable": True,
        "input_disclosure": {"sequence": "official EuRoC MH_01_easy first 2.000 seconds", "is_supervins_readme_recommended_v2_01": False, "camera_count": 41, "imu_count": 401, "event_count": 442},
        "authorization": {**starts, "retry_authorized": False},
        "master": {"command": MASTER_COMMAND, "pid": master_proc.pid if master_proc else None, "state_before_node": state_before_node, "termination": master_termination, "post_port_bound": post_port_bound},
        "node": {"command": NODE_COMMAND, "pid": node_proc.pid if node_proc else None, "launch_error": node_launch_error, "session_marker_elapsed_seconds": session_marker_elapsed, "inference_gate_elapsed_seconds": inference_gate_elapsed, "state_before_publisher": state_before_publisher, "termination": node_termination, "capture": {"stdout": "DEDICATED_PTY", "stderr": "DEDICATED_PTY"}},
        "publisher": {"command": PUBLISHER_COMMAND, "pid": publisher_proc.pid if publisher_proc else None, "launch_error": publisher_launch_error, "system_state_witness": publisher_state_witness, "terminal": terminal, "camera_event_record_count": len(publisher_parse["camera_records"]), "termination": publisher_termination},
        "inference_witness": classification,
        "input_and_scope_evidence": {"node_fd_snapshot_before_publisher": node_fd_snapshot, "node_dataset_or_bag_fds_before_publisher": dataset_or_bag_fds, "rosbag_processes_started_by_runner": 0, "groundtruth_publishers_started_by_runner": 0, "cam1_publishers_started_by_runner": 0, "post_publisher_input_preflight": post_publisher_preflight},
        "pass_conditions": pass_conditions,
        "post_pin_audit": {"changed_pins": changed_pins, "changed_trajectory_artifacts": changed_trajectory, "checks": post_pins},
        "post_process_audit": {"supervins_pids": post_nodes, "publisher_processes": post_publishers, "master_processes": post_masters, "master_port_bound": post_port_bound},
        "artifacts": artifacts,
        "claim_boundary": {"development_only": True, "proves_extractor_and_matcher_inference_runability_on_frozen_prefix": passed, "proves_complete_vio_or_trajectory": False, "trajectory_or_ape_rpe_run": False, "formal_baseline_authorized": False, "underwater_claim_authorized": False, "comparison_with_aqua_fe_authorized": False},
        "next_stage_automatically_authorized": False,
    }
    result_identity = write_json_exclusive(ATTEMPT / "run_result.json", result)
    print(json.dumps({**result, "run_result_identity": result_identity}, sort_keys=True))
    return 0 if passed else 1


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--action", choices=("preflight", "run"), required=True)
    parser.add_argument("--authorization-token")
    args = parser.parse_args()
    if args.action == "preflight":
        result = collect_preflight()
        print(json.dumps(result, sort_keys=True))
        return 0 if result["ready"] else 1
    return run_once(args.authorization_token)


if __name__ == "__main__":
    sys.exit(main())
