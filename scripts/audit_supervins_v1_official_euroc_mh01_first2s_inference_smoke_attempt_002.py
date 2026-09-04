#!/usr/bin/env python3
"""Read-only adjudication of immutable SuperVINS stage-3 attempt 002."""

from __future__ import annotations

import hashlib
import json
import re
import socket
import sys
from pathlib import Path


ROOT = Path("/home/ma/AQUA-FE_WS")
ATTEMPT = ROOT / "experiments/published_supervins_v1_official_euroc_mh01_first2s_inference_smoke_20260817_r2/attempt_002"
MASTER_LOG = ATTEMPT / "ros_home/log/87f4f138-9990-11f1-91c7-2313c6152585/master.log"
PUBLISHER_ROSPY_LOG = ATTEMPT / "ros_home/log/aqua_fe_euroc_mh01_first2s_publisher.log"

EXPECTED = {
    str(ATTEMPT / "run_result.json"): ("e92149913b46ce908301b4281c947af294d912ee4676703d56a7495e9b595fa1", 29588),
    str(MASTER_LOG): ("950ff634528d463d1669d035878d7baf55b27381d6d2eb00a42433a25e46b795", 8335),
    str(PUBLISHER_ROSPY_LOG): ("c7921d7445b289c9d012f1699ac3635304df65de1701242bb2994da72cd24914", 1872),
    str(ATTEMPT / "preflight_result.json"): ("c54a106c277aedd00afa0b0f7b05433f907020664d3d2ce62bfe923eb9a33b53", 24963),
    str(ATTEMPT / "roscore_start_claim.json"): ("e875844bd0fbb4440e31f334cd347aa2dcadeff0638158858912067ba9f2ebc3", 554),
    str(ATTEMPT / "node_start_claim.json"): ("831c42011c8259c4320785c9de606d3959cac98e5d0451f55318542aae308004", 1031),
    str(ATTEMPT / "publisher_start_claim.json"): ("01bc2afaa913941ec1cf322e100a83967243410f1b880c1f856272020b1fae77", 2461),
    str(ATTEMPT / "node.stdout.log"): ("758870d8d0d2715673db778dd77405105bd2b874e5217d11201f2d0afad20083", 9349),
    str(ATTEMPT / "node.stderr.log"): ("3a09eb67d94abff495c2cf90af02c56bd183d12835955834861a786d4fda9229", 1125),
    str(ATTEMPT / "publisher.stdout.log"): ("e9a57d21b2ddc75a4d436f2c3dcfb02d65f773fab1b091b3c05c0608df506302", 9631),
    str(ATTEMPT / "publisher.stderr.log"): ("e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855", 0),
    str(ATTEMPT / "roscore.stdout.log"): ("a66c0b059cd537f6d89e47454d24a8773ef778859898f69637961447abe535fa", 984),
    str(ATTEMPT / "roscore.stderr.log"): ("e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855", 0),
    str(ATTEMPT / "roscore_process_started.json"): ("ab9580e5eeef336670f37f74eeadc081961464a0c95ea08cf8785b8cde0ad6f9", 135),
    str(ATTEMPT / "node_process_started.json"): ("64b676a9a966524fda8329b571dae080fb85b52ad2937b6e1c3ddac66fc304a6", 317),
    str(ATTEMPT / "publisher_process_started.json"): ("e5856e1d6351f5dad48a7fdce2e8fba1cc27ac6262fa4ccbf352598280c46ffd", 277),
}


def identity(path):
    path = Path(path)
    return {"sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "size_bytes": path.stat().st_size}


def exact_processes():
    publisher = "/home/ma/AQUA-FE_WS/scripts/publish_supervins_euroc_mh01_first2s_v1.py"
    found = []
    for path in Path("/proc").glob("[0-9]*/cmdline"):
        try:
            parts = [part.decode("utf-8", "replace") for part in path.read_bytes().split(b"\0") if part]
        except OSError:
            continue
        names = {Path(part).name for part in parts[:3]}
        if publisher in parts or "supervins_node" in names or ("11554" in parts and names & {"roscore", "rosmaster", "roslaunch"}):
            found.append({"pid": int(path.parent.name), "argv": parts})
    return sorted(found, key=lambda item: item["pid"])


def port_bound(port):
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(0.2)
    try:
        return sock.connect_ex(("127.0.0.1", port)) == 0
    finally:
        sock.close()


def parse_json_lines(path):
    records = []
    for line in Path(path).read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            records.append(value)
    return records


def audit():
    checks = {}
    for path, (sha256, size) in EXPECTED.items():
        observed = identity(path)
        checks["identity:" + path] = observed == {"sha256": sha256, "size_bytes": size}

    result = json.loads((ATTEMPT / "run_result.json").read_text(encoding="utf-8"))
    false_gates = sorted(name for name, passed in result["pass_conditions"].items() if not passed)
    checks["formal_result_remains_fail"] = result["status"] == "FAIL_STAGE3_OFFICIAL_MH01_FIRST2S_INFERENCE_SMOKE_NO_RETRY"
    checks["only_formal_false_gate_is_memory_identity_witness"] = false_gates == ["publisher_identity_witness_exact"]
    checks["one_start_each_no_retry"] = result["authorization"] == {"roscore_start_count": 1, "node_start_count": 1, "publisher_start_count": 1, "retry_authorized": False}

    node_text = (ATTEMPT / "node.stdout.log").read_text(encoding="utf-8", errors="replace") + "\n" + (ATTEMPT / "node.stderr.log").read_text(encoding="utf-8", errors="replace")
    match_values = [int(value) for value in re.findall(r"matches\.size\(\)\s*=\s*(-?\d+)", node_text, re.IGNORECASE)]
    node_witness = {
        "session_marker_count": node_text.lower().count("waiting for image and imu..."),
        "extract_feature_time_count": node_text.lower().count("extract feature time"),
        "matches_size_count": len(match_values),
        "matches_size_values": match_values,
    }
    checks["raw_node_logs_meet_inference_gates"] = node_witness["session_marker_count"] >= 1 and node_witness["extract_feature_time_count"] >= 2 and node_witness["matches_size_count"] >= 1

    publisher_records = parse_json_lines(ATTEMPT / "publisher.stdout.log")
    camera_records = [record for record in publisher_records if record.get("event") == "CAMERA_PUBLISHED"]
    terminals = [record for record in publisher_records if record.get("status") == "PUBLISH_COMPLETE"]
    terminal = terminals[-1] if terminals else {}
    checks["raw_publisher_log_exact_input_complete"] = (
        len(camera_records) == 41 and len(terminals) == 1 and terminal.get("camera_count") == 41
        and terminal.get("imu_count") == 401 and terminal.get("event_count") == 442
        and terminal.get("rosbag_used") is False and terminal.get("cam1_published") is False
        and terminal.get("groundtruth_published") is False
    )

    master_text = MASTER_LOG.read_text(encoding="utf-8", errors="replace")
    master_patterns = {
        "subscriber_imu": "+SUB [/imu0] /supervins_estimator ",
        "subscriber_camera": "+SUB [/cam0/image_raw] /supervins_estimator ",
        "publisher_camera": "+PUB [/cam0/image_raw] /aqua_fe_euroc_mh01_first2s_publisher ",
        "publisher_imu": "+PUB [/imu0] /aqua_fe_euroc_mh01_first2s_publisher ",
    }
    master_counts = {name: master_text.count(pattern) for name, pattern in master_patterns.items()}
    checks["master_log_reconstructs_exact_topic_node_graph"] = all(count == 1 for count in master_counts.values())

    rospy_text = PUBLISHER_ROSPY_LOG.read_text(encoding="utf-8", errors="replace")
    rospy_patterns = {
        "node_init": "init_node, name[/aqua_fe_euroc_mh01_first2s_publisher]",
        "camera_connection": "topic[/cam0/image_raw] adding connection to [/supervins_estimator]",
        "imu_connection": "topic[/imu0] adding connection to [/supervins_estimator]",
    }
    rospy_counts = {name: rospy_text.count(pattern) for name, pattern in rospy_patterns.items()}
    checks["publisher_rospy_log_confirms_two_live_connections"] = all(count == 1 for count in rospy_counts.values())

    claims = {name: json.loads((ATTEMPT / name).read_text(encoding="utf-8")) for name in ("roscore_start_claim.json", "node_start_claim.json", "publisher_start_claim.json")}
    subscription_state = claims["publisher_start_claim.json"]["node_state_before_publisher"]
    checks["publisher_claim_follows_exact_two_subscriptions"] = (
        subscription_state["input_publishers"] == {}
        and subscription_state["input_subscribers"] == {"/cam0/image_raw": ["/supervins_estimator"], "/imu0": ["/supervins_estimator"]}
        and subscription_state["subscription_settle_witness"]["exact_subscriptions_observed"] is True
    )

    checks["all_recorded_pins_unchanged"] = result["post_pin_audit"]["changed_pins"] == []
    checks["trajectory_artifacts_unchanged"] = result["post_pin_audit"]["changed_trajectory_artifacts"] == []
    processes = exact_processes()
    port_11553 = port_bound(11553)
    port_11554 = port_bound(11554)
    checks["no_residual_processes"] = not processes
    checks["ports_11553_11554_unbound"] = not port_11553 and not port_11554

    failures = sorted(name for name, passed in checks.items() if not passed)
    return {
        "status": "ADJUDICATION_RECONSTRUCTED_FROM_IMMUTABLE_LOGS" if not failures else "ADJUDICATION_BLOCKED",
        "ready": not failures,
        "failures": failures,
        "checks": checks,
        "formal_result": {"status": result["status"], "false_gates": false_gates},
        "raw_inference_witness": node_witness,
        "raw_publisher_terminal": terminal,
        "master_graph_pattern_counts": master_counts,
        "publisher_rospy_pattern_counts": rospy_counts,
        "residual": {"processes": processes, "port_11553_bound": port_11553, "port_11554_bound": port_11554},
    }


if __name__ == "__main__":
    value = audit()
    print(json.dumps(value, sort_keys=True))
    sys.exit(0 if value["ready"] else 1)
