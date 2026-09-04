#!/usr/bin/env python3
"""Additive stage-3 attempt 002 with a bounded subscription-settle poll.

Attempt 001 is immutable and terminal.  This controller reuses its frozen
input, node, models, publisher, inference gates, and teardown logic.  Its only
runtime delta is a read-only, at-most-12-second getSystemState poll after the
session marker and before the publisher claim, because the pinned source
creates its subscriptions after printing that marker.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import importlib.util
import json
import socket
import sys
import time
from pathlib import Path


ROOT = Path("/home/ma/AQUA-FE_WS")
ATTEMPT1_RUNNER = ROOT / "scripts/run_published_supervins_v1_official_euroc_mh01_first2s_inference_smoke_v1.py"
SPEC = importlib.util.spec_from_file_location("supervins_stage3_attempt_001", ATTEMPT1_RUNNER)
A1 = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(A1)

ORIGINAL_READ_JSON = A1.read_json
ORIGINAL_ALL_FROZEN_PINS = A1.all_frozen_pins
ORIGINAL_VALIDATE_LOCK = A1.validate_lock
ORIGINAL_COLLECT_PREFLIGHT = A1.collect_preflight
RAW_GET_SYSTEM_STATE = A1.get_system_state

PROTOCOL = ROOT / "papers/supervins_v1_official_euroc_mh01_first2s_inference_smoke_attempt_002_freeze_v1.json"
LOCK = ROOT / "papers/supervins_v1_official_euroc_mh01_first2s_inference_smoke_attempt_002_execution_lock_v1.json"
TESTS = ROOT / "scripts/tests/test_run_published_supervins_v1_official_euroc_mh01_first2s_inference_smoke_attempt_002.py"
ADOPTION = ROOT / "papers/supervins_v1_official_euroc_mh01_first2s_inference_smoke_attempt_001_failure_adoption_v1.json"
BASE_STAGE3_FREEZE = ROOT / "papers/supervins_v1_official_euroc_mh01_first2s_inference_smoke_freeze_v1.json"
EVIDENCE = ROOT / "experiments/published_supervins_v1_official_euroc_mh01_first2s_inference_smoke_20260817_r2"
ATTEMPT = EVIDENCE / "attempt_002"

MASTER_HOST = "127.0.0.1"
MASTER_PORT = 11554
MASTER_URI = "http://127.0.0.1:11554"
MASTER_COMMAND = ["/opt/ros/noetic/bin/roscore", "-p", "11554"]
AUTHORIZATION_TOKEN = "SUPERVINS_STAGE3_MH01_FIRST2S_ATTEMPT_002_START_ONCE"
SUBSCRIPTION_SETTLE_TIMEOUT = 12.0
SUBSCRIPTION_POLL_INTERVAL = 0.05
PASS_STATUS = "PASS_DEVELOPMENT_OFFICIAL_MH01_FIRST2S_EXTRACTOR_MATCHER_INFERENCE_ATTEMPT_002"


def effective_protocol():
    delta = ORIGINAL_READ_JSON(PROTOCOL)
    base = copy.deepcopy(ORIGINAL_READ_JSON(BASE_STAGE3_FREEZE))
    base["status"] = "FROZEN_BEFORE_STAGE_3_MASTER_NODE_OR_PUBLISHER_START"
    base["relationship"] = delta["relationship"]
    base["base_stage_3_freeze"] = delta["base_stage_3_freeze"]
    base["attempt_001_failure_adoption"] = delta["attempt_001_failure_adoption"]
    base["fresh_namespace"] = delta["fresh_namespace"]
    base["one_shot_authority"] = delta["one_shot_authority"]
    base["ros"] = delta["ros"]
    base["success_contract"]["pass_status"] = delta["success_status"]
    return base


def read_json(path):
    if Path(path).resolve() == PROTOCOL.resolve():
        return effective_protocol()
    return ORIGINAL_READ_JSON(path)


def all_frozen_pins(protocol, stage2_freeze, manifest):
    pins = ORIGINAL_ALL_FROZEN_PINS(protocol, stage2_freeze, manifest)
    delta = ORIGINAL_READ_JSON(PROTOCOL)
    adoption = ORIGINAL_READ_JSON(ADOPTION)
    for item in (delta["base_stage_3_freeze"], delta["attempt_001_failure_adoption"]):
        pins[item["path"]] = {"sha256": item["sha256"], "size_bytes": item["size_bytes"]}
    pins.update(adoption["controller_pins"])
    pins.update(adoption["attempt_artifact_pins"])
    return pins


def port_is_bound():
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(0.2)
    try:
        return sock.connect_ex((MASTER_HOST, MASTER_PORT)) == 0
    finally:
        sock.close()


def is_attempt_master_cmdline(parts):
    executables = {Path(part).name for part in parts[:3]}
    return "11554" in parts and bool(executables & {"roscore", "rosmaster", "roslaunch"})


def port_processes():
    found = []
    for path in Path("/proc").glob("[0-9]*/cmdline"):
        try:
            parts = [part.decode("utf-8", "replace") for part in path.read_bytes().split(b"\0") if part]
        except OSError:
            continue
        if is_attempt_master_cmdline(parts):
            found.append({"pid": int(path.parent.name), "argv": parts})
    return sorted(found, key=lambda item: item["pid"])


def exact_node_subscriptions(state):
    return A1.input_connection_contract(state, publisher_required=False)


def poll_for_exact_subscriptions(
    query,
    timeout_seconds=SUBSCRIPTION_SETTLE_TIMEOUT,
    interval_seconds=SUBSCRIPTION_POLL_INTERVAL,
    monotonic=time.monotonic,
    sleeper=time.sleep,
):
    started = monotonic()
    deadline = started + timeout_seconds
    poll_count = 1
    state = query()
    node_present = bool(state.get("ok") and A1.NODE_NAME in state.get("nodes", []))
    while node_present and not exact_node_subscriptions(state) and monotonic() < deadline:
        remaining = deadline - monotonic()
        sleeper(min(interval_seconds, max(0.0, remaining)))
        state = query()
        poll_count += 1
        node_present = bool(state.get("ok") and A1.NODE_NAME in state.get("nodes", []))
    elapsed = monotonic() - started
    enriched = dict(state)
    enriched["subscription_settle_witness"] = {
        "attempted": node_present or poll_count > 1,
        "poll_count": poll_count,
        "timeout_seconds": timeout_seconds,
        "elapsed_seconds": elapsed,
        "exact_subscriptions_observed": exact_node_subscriptions(state),
        "timed_out": node_present and not exact_node_subscriptions(state) and elapsed >= timeout_seconds,
        "required": {topic: [A1.NODE_NAME] for topic in A1.INPUT_TOPICS},
    }
    return enriched


def get_system_state():
    return poll_for_exact_subscriptions(RAW_GET_SYSTEM_STATE)


def validate_lock(pins):
    observed = {"path": str(LOCK)}
    try:
        lock = ORIGINAL_READ_JSON(LOCK)
        observed["identity"] = A1.file_identity(LOCK)
    except (OSError, ValueError) as exc:
        observed["error"] = type(exc).__name__ + ":" + str(exc)[:500]
        return False, observed
    expected_special = {
        "protocol": A1.file_identity(PROTOCOL),
        "runner": A1.file_identity(Path(__file__).resolve()),
        "tests": A1.file_identity(TESTS),
        "publisher": A1.file_identity(A1.PUBLISHER),
        "input_manifest": A1.file_identity(A1.INPUT_MANIFEST),
        "attempt_001_failure_adoption": A1.file_identity(ADOPTION),
    }
    pin_digest = hashlib.sha256(A1.canonical_json_bytes(pins)).hexdigest()
    ok = all(
        (
            lock.get("schema_version") == "aqua-fe-published-supervins-v1-official-euroc-mh01-first2s-inference-smoke-attempt-002-execution-lock-v1",
            lock.get("status") == "LOCKED_FOR_EXACTLY_ONE_ATTEMPT_002_MASTER_NODE_PUBLISHER_START",
            lock.get("authorization_token") == AUTHORIZATION_TOKEN,
            lock.get("master_uri") == MASTER_URI,
            lock.get("master_command") == MASTER_COMMAND,
            lock.get("node_command") == A1.NODE_COMMAND,
            lock.get("publisher_command") == A1.PUBLISHER_COMMAND,
            lock.get("maximum_roscore_starts") == 1,
            lock.get("maximum_node_starts") == 1,
            lock.get("maximum_publisher_starts") == 1,
            lock.get("retry_authorized") is False,
            lock.get("post_marker_subscription_poll_timeout_seconds") == 12,
            lock.get("protocol") == expected_special["protocol"],
            lock.get("runner") == expected_special["runner"],
            lock.get("tests") == expected_special["tests"],
            lock.get("publisher") == expected_special["publisher"],
            lock.get("input_manifest") == expected_special["input_manifest"],
            lock.get("attempt_001_failure_adoption") == expected_special["attempt_001_failure_adoption"],
            lock.get("pinned_file_count") == len(pins),
            lock.get("pinned_files_canonical_sha256") == pin_digest,
            lock.get("fresh_evidence_root") == str(EVIDENCE),
        )
    )
    observed.update({"special_identities": expected_special, "pinned_file_count": len(pins), "pinned_files_canonical_sha256": pin_digest})
    return ok, observed


def collect_preflight():
    result = ORIGINAL_COLLECT_PREFLIGHT()
    checks = result["checks"]
    failures = result["failures"]

    def add(name, ok, expected, observed):
        checks[name] = {"ok": bool(ok), "expected": expected, "observed": observed}
        if not ok and name not in failures:
            failures.append(name)

    try:
        delta = ORIGINAL_READ_JSON(PROTOCOL)
        adoption = ORIGINAL_READ_JSON(ADOPTION)
        old_result = ORIGINAL_READ_JSON(adoption["formal_result"]["path"])
        relationship_ok = (
            delta.get("status") == "FROZEN_BEFORE_STAGE_3_ATTEMPT_002_MASTER_NODE_OR_PUBLISHER_START"
            and delta.get("relationship", {}).get("mode") == "ADDITIVE_NEW_ATTEMPT_AND_FRESH_NAMESPACE"
            and delta.get("relationship", {}).get("attempt_001_modified") is False
            and delta.get("relationship", {}).get("base_input_models_runtime_and_success_gates_changed") is False
            and delta.get("one_shot_authority", {}).get("post_marker_subscription_poll_timeout_seconds") == 12
            and delta.get("ros", {}).get("master_uri") == MASTER_URI
            and delta.get("ros", {}).get("master_command") == MASTER_COMMAND
        )
        add("attempt_002_additive_delta_semantics", relationship_ok, True, delta.get("relationship"))
        adoption_ok = (
            adoption.get("status") == "ADOPTED_TERMINAL_FAIL_CLOSED_NO_RETRY"
            and adoption.get("formal_verdict", {}).get("attempt_001_is_terminal") is True
            and adoption.get("formal_verdict", {}).get("attempt_001_namespace_reuse_or_retry_authorized") is False
            and adoption.get("observed_runtime_facts", {}).get("publisher_start_count") == 0
            and adoption.get("observed_runtime_facts", {}).get("ros_messages_published") == 0
            and adoption.get("observed_runtime_facts", {}).get("node_reaped") is True
            and adoption.get("observed_runtime_facts", {}).get("roscore_reaped") is True
            and old_result.get("status") == "FAIL_STAGE3_OFFICIAL_MH01_FIRST2S_INFERENCE_SMOKE_NO_RETRY"
            and old_result.get("authorization", {}).get("publisher_start_count") == 0
            and old_result.get("post_pin_audit", {}).get("changed_pins") == []
        )
        add("attempt_001_failure_adopted_terminal_immutable", adoption_ok, True, {"adoption_status": adoption.get("status"), "old_result_status": old_result.get("status")})
    except (OSError, ValueError, KeyError) as exc:
        add("attempt_002_delta_and_adoption_load", False, True, type(exc).__name__ + ":" + str(exc)[:500])

    result["schema_version"] = "aqua-fe-published-supervins-v1-official-euroc-mh01-first2s-inference-smoke-attempt-002-preflight-v1"
    result["status"] = "GO_EXACTLY_ONE_ATTEMPT_002_MASTER_NODE_PUBLISHER_START" if not failures else "BLOCKED_NO_PROCESS_START"
    result["ready"] = not failures
    result["boundary"]["attempt_001_modified"] = False
    result["boundary"]["subscription_poll_run"] = False
    return result


def configure_attempt_002():
    A1.PROTOCOL = PROTOCOL
    A1.LOCK = LOCK
    A1.TESTS = TESTS
    A1.EVIDENCE = EVIDENCE
    A1.ATTEMPT = ATTEMPT
    A1.MASTER_HOST = MASTER_HOST
    A1.MASTER_PORT = MASTER_PORT
    A1.MASTER_URI = MASTER_URI
    A1.MASTER_COMMAND = MASTER_COMMAND
    A1.AUTHORIZATION_TOKEN = AUTHORIZATION_TOKEN
    A1.PASS_STATUS = PASS_STATUS
    A1.__file__ = str(Path(__file__).resolve())
    A1.read_json = read_json
    A1.all_frozen_pins = all_frozen_pins
    A1.validate_lock = validate_lock
    A1.port_is_bound = port_is_bound
    A1.is_attempt_master_cmdline = is_attempt_master_cmdline
    A1.port_processes = port_processes
    A1.get_system_state = get_system_state
    A1.collect_preflight = collect_preflight


configure_attempt_002()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--action", choices=("preflight", "run"), required=True)
    parser.add_argument("--authorization-token")
    args = parser.parse_args()
    if args.action == "preflight":
        result = collect_preflight()
        print(json.dumps(result, sort_keys=True))
        return 0 if result["ready"] else 1
    return A1.run_once(args.authorization_token)


if __name__ == "__main__":
    sys.exit(main())
