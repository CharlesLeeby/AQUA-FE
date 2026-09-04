#!/usr/bin/env python3
"""One-shot, no-data OrtSession construction smoke for pinned SuperVINS r1.

This runner is deliberately narrower than an inference test.  Its only active
operation is one direct start of the pinned node against an unbound, isolated
ROS master URI.  The source-ordered ``waiting for image and imu...`` marker is
the success witness that both configured OrtSession constructors returned.
No ROS master, publisher, bag, image, IMU, model Run(), or trajectory is used.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import signal
import socket
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path


ROOT = Path("/home/ma/AQUA-FE_WS")
PROTOCOL = ROOT / "papers/supervins_v1_ortsession_construction_smoke_freeze_v1.json"
LOCK = ROOT / "papers/supervins_v1_ortsession_construction_smoke_execution_lock_v1.json"
TESTS = ROOT / "scripts/tests/test_run_published_supervins_v1_ortsession_smoke_v1.py"
EVIDENCE = ROOT / "experiments/published_supervins_v1_ortsession_smoke_20260816_r1"
ATTEMPT = EVIDENCE / "attempt_001"

OFFICIAL = Path("/home/ma/SLAM/SuperVINS-paper-1.0-r1")
WORKSPACE = Path("/home/ma/SLAM/SuperVINS-v1-devrepair-ws-20260816-r1")
PRIVATE = WORKSPACE / "src/SuperVINS"
DEPENDENCIES = Path("/home/ma/opt/supervins_v1_devrepair_20260816_r1")
ORT = DEPENDENCIES / "onnxruntime-linux-x64-gpu-1.16.3"
CERES = DEPENDENCIES / "install/ceres-2.1.0"
EXTRA_CUDA = DEPENDENCIES / "cuda-runtime-11.6-extra/usr/local/cuda-11.6/targets/x86_64-linux/lib"
HFNET_ASSET = Path("/home/ma/opt/hfnet_cuda116_trt851_r1")
CUDNN = HFNET_ASSET / "usr/lib/x86_64-linux-gnu"
CUBLAS = HFNET_ASSET / "usr/local/cuda-11.8/targets/x86_64-linux/lib"
CUDART = HFNET_ASSET / "usr/local/cuda-11.6/targets/x86_64-linux/lib"

BINARY = WORKSPACE / "devel/lib/supervins/supervins_node"
LIBSUPERVINS = WORKSPACE / "devel/lib/libsupervins_lib.so"
CONFIG = PRIVATE / "config/euroc/euroc_mono_imu_config.yaml"
COMMAND = [str(BINARY), str(CONFIG)]

COMMIT = "91e85d72a3828844538715cc4b1cd4b86a2620db"
TREE = "036391d321d4ea9a914739a454c20976f01f7bd7"
DIFF_SHA256 = "94379f74e31417f883f499a6a8fd4591e93bf24429c852ff83de1ef20a3c75a0"
CHANGED_PATHS = [
    "supervins_estimator/CMakeLists.txt",
    "supervins_estimator/src/featureTracker/extractor_matcher_dpl.cpp",
]

AUTHORIZATION_TOKEN = "SUPERVINS_V1_ORTSESSION_SMOKE_ATTEMPT_001_START_ONCE"
MASTER_HOST = "127.0.0.1"
MASTER_PORT = 11551
MASTER_URI = "http://127.0.0.1:11551"
TIMEOUT_SECONDS = 45.0
TERM_GRACE_SECONDS = 3.0
SUCCESS_MARKER = "waiting for image and imu..."
FORBIDDEN_INFERENCE_MARKERS = [
    "extract feature time",
    "matches.size()",
    "matches.size =",
    "track image",
]
PASS_STATUS = "PASS_DEVELOPMENT_ORTSESSION_CONSTRUCTION_ONLY"

RUNTIME_PATHS = [
    ORT / "lib",
    EXTRA_CUDA,
    CUDNN,
    CUBLAS,
    CUDART,
    CERES / "lib",
    WORKSPACE / "devel/lib",
    Path("/opt/ros/noetic/lib"),
]
RUNTIME_LD_LIBRARY_PATH = ":".join(str(path) for path in RUNTIME_PATHS)


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


def command(argv, cwd=None, env=None, binary=False, timeout=60):
    probe_env = dict(os.environ if env is None else env)
    probe_env["LC_ALL"] = "C"
    probe_env["GIT_OPTIONAL_LOCKS"] = "0"
    try:
        completed = subprocess.run(
            [str(item) for item in argv],
            cwd=str(cwd) if cwd else None,
            env=probe_env,
            check=False,
            capture_output=True,
            text=not binary,
            timeout=timeout,
        )
        return {
            "returncode": completed.returncode,
            "stdout": completed.stdout,
            "stderr": completed.stderr,
        }
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {
            "returncode": 124 if isinstance(exc, subprocess.TimeoutExpired) else 126,
            "stdout": b"" if binary else "",
            "stderr": type(exc).__name__ + ":" + str(exc)[:500],
        }


def git(repo, *args, binary=False):
    return command(["git", "-C", repo, *args], binary=binary)


def process_pids_by_comm(comm):
    found = []
    for path in Path("/proc").glob("[0-9]*/comm"):
        try:
            if path.read_text(encoding="utf-8").strip() == comm:
                found.append(int(path.parent.name))
        except (OSError, ValueError):
            pass
    return sorted(found)


def port_is_bound(host=MASTER_HOST, port=MASTER_PORT):
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(0.2)
    try:
        return sock.connect_ex((host, port)) == 0
    finally:
        sock.close()


def runtime_environment(ros_home):
    env = dict(os.environ)
    env.update(
        {
            "CUDA_VISIBLE_DEVICES": "0",
            "LD_LIBRARY_PATH": RUNTIME_LD_LIBRARY_PATH,
            "LC_ALL": "C",
            "ROS_HOME": str(ros_home),
            "ROS_LOG_DIR": str(Path(ros_home) / "log"),
            "ROS_HOSTNAME": MASTER_HOST,
            "ROS_MASTER_URI": MASTER_URI,
        }
    )
    for key in ("ROS_NAMESPACE", "ROS_IP"):
        env.pop(key, None)
    return env


def classify_output(stdout_text, stderr_text):
    combined = stdout_text + "\n" + stderr_text
    lower = combined.lower()
    return {
        "success_marker": SUCCESS_MARKER,
        "success_marker_count": lower.count(SUCCESS_MARKER.lower()),
        "forbidden_inference_markers_found": [
            marker for marker in FORBIDDEN_INFERENCE_MARKERS if marker.lower() in lower
        ],
    }


def snapshot_open_fds(pid):
    targets = []
    for fd in sorted((Path("/proc") / str(pid) / "fd").glob("*"), key=lambda p: p.name):
        try:
            target = os.readlink(str(fd))
        except OSError:
            continue
        targets.append({"fd": fd.name, "target": target})
    return targets


def terminate_and_reap(proc):
    events = []
    if proc.poll() is None:
        try:
            os.killpg(proc.pid, signal.SIGTERM)
            events.append({"at": now_iso(), "signal": "SIGTERM_PROCESS_GROUP"})
        except ProcessLookupError:
            events.append({"at": now_iso(), "signal": "SIGTERM_PROCESS_GROUP_ALREADY_GONE"})
    try:
        returncode = proc.wait(timeout=TERM_GRACE_SECONDS)
        events.append({"at": now_iso(), "event": "REAPED_AFTER_TERM_OR_PRIOR_EXIT"})
        return {"events": events, "returncode": returncode, "sigkill_used": False, "reaped": True}
    except subprocess.TimeoutExpired:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
            events.append({"at": now_iso(), "signal": "SIGKILL_PROCESS_GROUP"})
        except ProcessLookupError:
            events.append({"at": now_iso(), "signal": "SIGKILL_PROCESS_GROUP_ALREADY_GONE"})
        returncode = proc.wait(timeout=5)
        events.append({"at": now_iso(), "event": "REAPED_AFTER_KILL"})
        return {"events": events, "returncode": returncode, "sigkill_used": True, "reaped": True}


def check_identity(path, expected):
    try:
        observed = file_identity(path)
        return observed == expected, observed
    except OSError as exc:
        return False, {"error": type(exc).__name__ + ":" + str(exc)[:500]}


def load_protocol_and_pins():
    protocol = read_json(PROTOCOL)
    pins = {}
    pins.update(protocol["pinned_r1_governance"])
    pins.update(protocol["pinned_runtime_artifacts"])
    return protocol, pins


def validate_execution_lock(protocol, pins):
    observed = {"path": str(LOCK)}
    try:
        lock = read_json(LOCK)
        observed["identity"] = file_identity(LOCK)
    except (OSError, ValueError, KeyError) as exc:
        observed["error"] = type(exc).__name__ + ":" + str(exc)[:500]
        return False, observed

    expected_special = {
        "protocol": file_identity(PROTOCOL),
        "runner": file_identity(Path(__file__).resolve()),
        "tests": file_identity(TESTS),
    }
    expected_pinset_sha256 = hashlib.sha256(canonical_json_bytes(pins)).hexdigest()
    conditions = [
        lock.get("schema_version") == "aqua-fe-published-supervins-v1-ortsession-construction-smoke-execution-lock-v1",
        lock.get("status") == "LOCKED_FOR_EXACTLY_ONE_NODE_START",
        lock.get("authorization_token") == AUTHORIZATION_TOKEN,
        lock.get("timeout_seconds") == 45,
        lock.get("maximum_supervins_node_starts") == 1,
        lock.get("command") == COMMAND,
        lock.get("ros_master_uri") == MASTER_URI,
        lock.get("protocol") == expected_special["protocol"],
        lock.get("runner") == expected_special["runner"],
        lock.get("tests") == expected_special["tests"],
        lock.get("pinned_file_count") == len(pins),
        lock.get("pinned_files_canonical_sha256") == expected_pinset_sha256,
        lock.get("fresh_evidence_root") == str(EVIDENCE),
    ]
    observed.update(
        {
            "schema_version": lock.get("schema_version"),
            "status": lock.get("status"),
            "special_identities": {
                key: {"expected": value, "observed": lock.get(key)}
                for key, value in expected_special.items()
            },
            "pinned_file_count": lock.get("pinned_file_count"),
            "pinned_files_canonical_sha256": lock.get("pinned_files_canonical_sha256"),
        }
    )
    return all(conditions), observed


def collect_preflight(require_fresh_namespace=True):
    checks = {}
    failures = []

    def add(name, ok, expected, observed):
        checks[name] = {"ok": bool(ok), "expected": expected, "observed": observed}
        if not ok:
            failures.append(name)

    try:
        protocol, pins = load_protocol_and_pins()
        protocol_ok = (
            protocol.get("schema_version")
            == "aqua-fe-published-supervins-v1-ortsession-construction-smoke-freeze-v1"
            and protocol.get("status") == "FROZEN_BEFORE_ORTSESSION_CONSTRUCTION"
            and protocol.get("claim_boundary", {}).get("ort_session_construction_authorized") is True
            and protocol.get("claim_boundary", {}).get("model_inference_authorized") is False
            and protocol.get("claim_boundary", {}).get("ros_data_consumption_authorized") is False
            and protocol.get("claim_boundary", {}).get("ros_data_publication_authorized") is False
            and protocol.get("one_shot_authority", {}).get("maximum_supervins_node_starts") == 1
            and protocol.get("one_shot_authority", {}).get("timeout_seconds") == 45
            and protocol.get("pinned_command") == COMMAND
        )
        add("protocol_semantics", protocol_ok, True, protocol.get("claim_boundary"))
    except (OSError, ValueError, KeyError) as exc:
        protocol, pins = {}, {}
        add("protocol_semantics", False, True, type(exc).__name__ + ":" + str(exc)[:500])

    for path_text, expected in pins.items():
        ok, observed = check_identity(Path(path_text), expected)
        add("pin:" + path_text, ok, expected, observed)

    lock_ok, lock_observed = validate_execution_lock(protocol, pins) if protocol else (False, {})
    add("execution_lock", lock_ok, True, lock_observed)

    receipt_path = ROOT / "experiments/published_supervins_v1_devrepair_20260816_r1/compile_preflight_receipt.json"
    try:
        receipt = read_json(receipt_path)
        receipt_ok = (
            receipt.get("status") == "READY_FOR_ORTSESSION_SMOKE_NOT_EXECUTED"
            and receipt.get("ready_for_ortsession_smoke") is True
            and receipt.get("failures") == []
            and receipt.get("probe_boundary", {}).get("ort_session_created") is False
            and receipt.get("probe_boundary", {}).get("model_inference_run") is False
            and receipt.get("probe_boundary", {}).get("ros_node_started") is False
        )
        receipt_observed = {
            "status": receipt.get("status"),
            "ready": receipt.get("ready_for_ortsession_smoke"),
            "failures": receipt.get("failures"),
            "probe_boundary": receipt.get("probe_boundary"),
        }
    except (OSError, ValueError) as exc:
        receipt_ok = False
        receipt_observed = {"error": type(exc).__name__ + ":" + str(exc)[:500]}
    add("r1_receipt_semantics", receipt_ok, True, receipt_observed)

    contract_path = ROOT / "experiments/published_supervins_v1_devrepair_20260816_r1/development_contract.json"
    try:
        contract = read_json(contract_path)
        old_boundary = contract.get("claim_boundary", {})
        contract_ok = (
            old_boundary
            and all(value is False for value in old_boundary.values())
            and contract.get("authorized_terminal_stage")
            == "COMPILE_AND_PREFLIGHT_CHECKPOINT_BEFORE_SESSION_CONSTRUCTION"
        )
        contract_observed = {
            "claim_boundary": old_boundary,
            "authorized_terminal_stage": contract.get("authorized_terminal_stage"),
        }
    except (OSError, ValueError) as exc:
        contract_ok = False
        contract_observed = {"error": type(exc).__name__ + ":" + str(exc)[:500]}
    add("r1_contract_remains_unmodified_and_closed", contract_ok, True, contract_observed)

    official_head = git(OFFICIAL, "rev-parse", "HEAD")
    official_tree = git(OFFICIAL, "rev-parse", "HEAD^{tree}")
    official_status = git(OFFICIAL, "status", "--porcelain=v1", "--untracked-files=all", "--ignore-submodules=none")
    official_observed = {
        "head": official_head["stdout"].strip(),
        "tree": official_tree["stdout"].strip(),
        "status": official_status["stdout"].splitlines(),
    }
    add(
        "official_checkout_identity",
        official_head["returncode"] == 0
        and official_tree["returncode"] == 0
        and official_status["returncode"] == 0
        and official_observed == {"head": COMMIT, "tree": TREE, "status": []},
        {"head": COMMIT, "tree": TREE, "status": []},
        official_observed,
    )

    private_head = git(PRIVATE, "rev-parse", "HEAD")
    private_tree = git(PRIVATE, "rev-parse", "HEAD^{tree}")
    private_names = git(PRIVATE, "diff", "--name-only")
    private_diff = git(PRIVATE, "diff", "--no-ext-diff", "--no-color", binary=True)
    diff_bytes = private_diff["stdout"] if isinstance(private_diff["stdout"], bytes) else b""
    private_observed = {
        "head": private_head["stdout"].strip(),
        "tree": private_tree["stdout"].strip(),
        "changed_paths": private_names["stdout"].splitlines(),
        "diff_sha256": hashlib.sha256(diff_bytes).hexdigest(),
    }
    add(
        "private_repair_identity",
        private_head["returncode"] == 0
        and private_tree["returncode"] == 0
        and private_names["returncode"] == 0
        and private_diff["returncode"] == 0
        and private_observed
        == {"head": COMMIT, "tree": TREE, "changed_paths": CHANGED_PATHS, "diff_sha256": DIFF_SHA256},
        {"head": COMMIT, "tree": TREE, "changed_paths": CHANGED_PATHS, "diff_sha256": DIFF_SHA256},
        private_observed,
    )

    try:
        main_text = (PRIVATE / "supervins_estimator/src/supervins_main.cpp").read_text(encoding="utf-8")
        estimator_text = (PRIVATE / "supervins_estimator/src/estimator/estimator.cpp").read_text(encoding="utf-8")
        tracker_text = (PRIVATE / "supervins_estimator/src/featureTracker/feature_tracker_dpl.cpp").read_text(encoding="utf-8")
        ort_text = (PRIVATE / "supervins_estimator/src/featureTracker/extractor_matcher_dpl.cpp").read_text(encoding="utf-8")
        causal_observed = {
            "set_parameter_before_wait_marker": main_text.index("estimator.setParameter();") < main_text.index(SUCCESS_MARKER),
            "estimator_calls_initialize_pair": estimator_text.count("initializeExtractorMatcher(") >= 1,
            "extractor_before_matcher": tracker_text.index("FeatureExtractorDPL->initialize(") < tracker_text.index("FeatureMatcherDPL->initialize("),
            "ort_session_constructor_count": ort_text.count("std::make_unique<Ort::Session>") == 2,
            "cuda_provider_registration_count": ort_text.count("AppendExecutionProvider_CUDA") == 2,
            "size_max_count": len(re.findall(r"gpu_mem_limit\s*=\s*SIZE_MAX\s*;", ort_text)) == 2,
        }
        causal_ok = all(causal_observed.values())
    except (OSError, ValueError) as exc:
        causal_ok = False
        causal_observed = {"error": type(exc).__name__ + ":" + str(exc)[:500]}
    add("source_order_causal_witness", causal_ok, True, causal_observed)

    runtime_env = runtime_environment(ROOT / ".preflight_ros_home_not_created")
    binary_ldd = command(["ldd", BINARY], env=runtime_env)
    provider_ldd = command(["ldd", ORT / "lib/libonnxruntime_providers_cuda.so"], env=runtime_env)
    ldd_observed = {
        "binary_returncode": binary_ldd["returncode"],
        "binary_missing": [line.strip() for line in binary_ldd["stdout"].splitlines() if "not found" in line],
        "provider_returncode": provider_ldd["returncode"],
        "provider_missing": [line.strip() for line in provider_ldd["stdout"].splitlines() if "not found" in line],
        "isolated_ort": str(ORT) in binary_ldd["stdout"],
        "isolated_ceres": str(CERES) in binary_ldd["stdout"],
        "isolated_cufft": str(EXTRA_CUDA / "libcufft.so.10") in provider_ldd["stdout"],
        "isolated_curand": str(EXTRA_CUDA / "libcurand.so.10") in provider_ldd["stdout"],
    }
    ldd_ok = (
        binary_ldd["returncode"] == 0
        and provider_ldd["returncode"] == 0
        and not ldd_observed["binary_missing"]
        and not ldd_observed["provider_missing"]
        and all(ldd_observed[key] for key in ("isolated_ort", "isolated_ceres", "isolated_cufft", "isolated_curand"))
    )
    add("runtime_link_closure", ldd_ok, True, ldd_observed)

    gpu = command(["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader"])
    add(
        "gpu_visible",
        gpu["returncode"] == 0 and bool(gpu["stdout"].strip()),
        "at_least_one_gpu",
        gpu["stdout"].splitlines(),
    )

    running = process_pids_by_comm("supervins_node")
    add("no_preexisting_supervins_node", not running, [], running)
    bound = port_is_bound()
    add("isolated_master_port_unbound", not bound, False, bound)
    namespace_observed = EVIDENCE.exists()
    namespace_ok = not namespace_observed if require_fresh_namespace else namespace_observed
    add(
        "fresh_evidence_namespace",
        namespace_ok,
        "ABSENT" if require_fresh_namespace else "PRESENT",
        "PRESENT" if namespace_observed else "ABSENT",
    )
    try:
        free_bytes = os.statvfs(str(ROOT)).f_bavail * os.statvfs(str(ROOT)).f_frsize
    except OSError:
        free_bytes = 0
    add("minimum_free_storage", free_bytes >= 512 * 1024 * 1024, 512 * 1024 * 1024, free_bytes)

    return {
        "schema_version": "aqua-fe-published-supervins-v1-ortsession-smoke-preflight-v1",
        "checked_at": now_iso(),
        "status": "GO_EXACTLY_ONE_NODE_START" if not failures else "BLOCKED_NO_NODE_START",
        "ready": not failures,
        "failures": failures,
        "checks": checks,
        "boundary": {
            "ort_session_created": False,
            "model_inference_run": False,
            "ros_master_started": False,
            "ros_data_opened_or_replayed": False,
            "supervins_node_started": False,
        },
    }


def post_pin_audit(protocol):
    outcomes = {}
    for path_text, expected in {**protocol["pinned_r1_governance"], **protocol["pinned_runtime_artifacts"]}.items():
        ok, observed = check_identity(path_text, expected)
        outcomes[path_text] = {"ok": ok, "expected": expected, "observed": observed}
    lock = read_json(LOCK)
    for path, expected in (
        (PROTOCOL, lock["protocol"]),
        (Path(__file__).resolve(), lock["runner"]),
        (TESTS, lock["tests"]),
    ):
        ok, observed = check_identity(path, expected)
        outcomes[str(path)] = {"ok": ok, "expected": expected, "observed": observed}
    return outcomes


def run_once(token):
    if token != AUTHORIZATION_TOKEN:
        result = {
            "status": "BLOCKED_INVALID_AUTHORIZATION_TOKEN_NO_NODE_START",
            "return_code": 2,
            "node_start_count": 0,
        }
        print(json.dumps(result, sort_keys=True))
        return 2

    preflight = collect_preflight(require_fresh_namespace=True)
    if not preflight["ready"]:
        result = {
            "status": "BLOCKED_PREFLIGHT_NO_NODE_START",
            "return_code": 3,
            "node_start_count": 0,
            "preflight": preflight,
        }
        print(json.dumps(result, sort_keys=True))
        return 3

    protocol = read_json(PROTOCOL)
    EVIDENCE.mkdir(mode=0o755, parents=False, exist_ok=False)
    ATTEMPT.mkdir(mode=0o755, exist_ok=False)
    ros_home = ATTEMPT / "ros_home"
    (ros_home / "log").mkdir(mode=0o755, parents=True, exist_ok=False)

    preflight_path = ATTEMPT / "preflight_result.json"
    preflight_identity = write_json_exclusive(preflight_path, preflight)
    claim = {
        "schema_version": "aqua-fe-published-supervins-v1-ortsession-smoke-start-claim-v1",
        "created_at": now_iso(),
        "authorization_token_sha256": hashlib.sha256(token.encode("utf-8")).hexdigest(),
        "command": COMMAND,
        "maximum_supervins_node_starts": 1,
        "node_start_count_before_claim": 0,
        "preflight_result": preflight_identity,
        "execution_lock": file_identity(LOCK),
    }
    claim_path = ATTEMPT / "node_start_claim.json"
    claim_identity = write_json_exclusive(claim_path, claim)

    stdout_path = ATTEMPT / "node.stdout.log"
    stderr_path = ATTEMPT / "node.stderr.log"
    started_path = ATTEMPT / "node_process_started.json"
    start_monotonic = time.monotonic()
    started_at = now_iso()
    proc = None
    launch_error = None
    marker_observed_during_run = False
    marker_elapsed_seconds = None
    fd_snapshot = []
    termination = {"events": [], "returncode": None, "sigkill_used": False, "reaped": False}

    with stdout_path.open("xb") as stdout_stream, stderr_path.open("xb") as stderr_stream:
        try:
            proc = subprocess.Popen(
                COMMAND,
                cwd=str(ATTEMPT),
                env=runtime_environment(ros_home),
                stdin=subprocess.DEVNULL,
                stdout=stdout_stream,
                stderr=stderr_stream,
                start_new_session=True,
            )
            started_record = {
                "schema_version": "aqua-fe-published-supervins-v1-ortsession-smoke-process-start-v1",
                "started_at": started_at,
                "pid": proc.pid,
                "process_group": proc.pid,
                "command": COMMAND,
                "ros_master_uri": MASTER_URI,
                "roscore_started": False,
                "node_start_count": 1,
            }
            write_json_exclusive(started_path, started_record)

            deadline = start_monotonic + TIMEOUT_SECONDS
            while time.monotonic() < deadline:
                stdout_stream.flush()
                stderr_stream.flush()
                stdout_text = stdout_path.read_text(encoding="utf-8", errors="replace")
                stderr_text = stderr_path.read_text(encoding="utf-8", errors="replace")
                if SUCCESS_MARKER.lower() in (stdout_text + "\n" + stderr_text).lower():
                    marker_observed_during_run = True
                    marker_elapsed_seconds = time.monotonic() - start_monotonic
                    fd_snapshot = snapshot_open_fds(proc.pid)
                    break
                if proc.poll() is not None:
                    break
                time.sleep(0.10)
        except OSError as exc:
            launch_error = type(exc).__name__ + ":" + str(exc)[:500]
        finally:
            if proc is not None:
                termination = terminate_and_reap(proc)
            stdout_stream.flush()
            stderr_stream.flush()
            os.fsync(stdout_stream.fileno())
            os.fsync(stderr_stream.fileno())

    finished_at = now_iso()
    elapsed_seconds = time.monotonic() - start_monotonic
    stdout_text = stdout_path.read_text(encoding="utf-8", errors="replace")
    stderr_text = stderr_path.read_text(encoding="utf-8", errors="replace")
    output_classification = classify_output(stdout_text, stderr_text)
    post_running = process_pids_by_comm("supervins_node")
    post_port_bound = port_is_bound()
    post_pins = post_pin_audit(protocol)
    changed_pins = [path for path, item in post_pins.items() if not item["ok"]]
    dataset_fd_targets = [
        item for item in fd_snapshot
        if "/datasets/" in item["target"] or item["target"].lower().endswith(".bag")
    ]
    output_identities = {
        "stdout": file_identity(stdout_path),
        "stderr": file_identity(stderr_path),
        "process_started": file_identity(started_path) if started_path.exists() else None,
        "start_claim": claim_identity,
    }

    pass_conditions = {
        "preflight_go": preflight["ready"],
        "node_start_count_exactly_one": proc is not None and started_path.exists(),
        "launch_error_absent": launch_error is None,
        "success_marker_observed_before_timeout": marker_observed_during_run and elapsed_seconds <= TIMEOUT_SECONDS + TERM_GRACE_SECONDS + 5,
        "success_marker_present_in_persisted_output": output_classification["success_marker_count"] >= 1,
        "inference_markers_absent": not output_classification["forbidden_inference_markers_found"],
        "no_dataset_or_bag_fd_at_marker": not dataset_fd_targets,
        "node_synchronously_reaped": termination["reaped"],
        "no_supervins_process_post": not post_running,
        "isolated_master_port_unbound_post": not post_port_bound,
        "pinned_artifacts_unchanged_post": not changed_pins,
    }
    passed = all(pass_conditions.values())
    status = PASS_STATUS if passed else "FAIL_DEVELOPMENT_ORTSESSION_CONSTRUCTION_NO_RETRY"
    result = {
        "schema_version": "aqua-fe-published-supervins-v1-ortsession-construction-smoke-result-v1",
        "status": status,
        "return_code": 0 if passed else 1,
        "evaluable": True,
        "started_at": started_at,
        "finished_at": finished_at,
        "elapsed_seconds": elapsed_seconds,
        "command": COMMAND,
        "authorization": {
            "attempt": "attempt_001",
            "maximum_node_starts": 1,
            "node_start_count": 1 if proc is not None else 0,
            "retry_authorized": False,
            "start_claim": output_identities["start_claim"],
        },
        "runtime": {
            "pid": proc.pid if proc is not None else None,
            "launch_error": launch_error,
            "timeout_seconds": TIMEOUT_SECONDS,
            "marker_elapsed_seconds": marker_elapsed_seconds,
            "termination": termination,
            "ros_master_uri": MASTER_URI,
            "roscore_started": False,
            "ros_master_port_bound_post": post_port_bound,
            "post_supervins_pids": post_running,
        },
        "session_witness": {
            "marker_observed_during_run": marker_observed_during_run,
            "causal_interpretation": "Pinned source returns from extractor and matcher OrtSession construction before emitting the marker.",
            **output_classification,
        },
        "no_data_evidence": {
            "ros_publishers_started_by_runner": 0,
            "rosbags_started_by_runner": 0,
            "datasets_opened_by_runner": 0,
            "open_fd_snapshot_at_marker": fd_snapshot,
            "dataset_or_bag_fd_targets": dataset_fd_targets,
        },
        "pass_conditions": pass_conditions,
        "post_pin_audit": {"changed_pins": changed_pins, "checks": post_pins},
        "artifacts": output_identities,
        "claim_boundary": {
            "accuracy_claim_authorized": False,
            "ape_rpe_authorized": False,
            "formal_baseline_authorized": False,
            "model_inference_run": False,
            "ort_sessions_constructed": passed,
            "ros_data_opened_or_replayed": False,
            "trajectory_run": False,
        },
        "next_stage_automatically_authorized": False,
    }
    result_path = ATTEMPT / "run_result.json"
    result_identity = write_json_exclusive(result_path, result)
    result["run_result_identity"] = result_identity
    print(json.dumps(result, sort_keys=True))
    return 0 if passed else 1


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--action", choices=("preflight", "run"), required=True)
    parser.add_argument("--authorization-token")
    args = parser.parse_args()
    if args.action == "preflight":
        result = collect_preflight(require_fresh_namespace=True)
        print(json.dumps(result, sort_keys=True))
        return 0 if result["ready"] else 1
    return run_once(args.authorization_token)


if __name__ == "__main__":
    sys.exit(main())
