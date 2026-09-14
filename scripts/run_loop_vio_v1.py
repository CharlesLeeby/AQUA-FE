#!/usr/bin/env python3
"""One serial, passive-capture local VIO repeat; no loop feedback or estimator edits."""
from __future__ import annotations

import argparse
import datetime
import json
import os
from pathlib import Path
import re
import signal
import socket
import subprocess
import time
import xmlrpc.client

import cv2
import numpy as np

from learned_loop_encoder_v1 import guard, sha

VINS = Path("/home/ma/SLAM/VINS-Fusion-origin")
NODE = VINS / "devel/lib/vins/vins_node"
LIB = VINS / "devel/lib/libvins_lib.so"
NODE_SHA = "4e91d8ac0735163fb6617e18d64ae0de91cc903d036f0e568a29bd3e5f5f4278"
LIB_SHA = "373a598c7ce591b4fe97ced9b3ee1de5bbf0322c105a54afcb03a91b810f71e8"
CAPTURE_TOPICS = ["/vins_estimator/keyframe_pose", "/vins_estimator/keyframe_point",
    "/vins_estimator/odometry", "/vins_estimator/extrinsic", "/feature_tracker/feature", "/imu/imu"]
YAML_SHAS = {"bus_outside": "cb9a252cdb0864aad843b7c6ad050f74ce0c1c07760df8963238d188364052f1",
    "cemetery": "47a9e75a9c2076276d0068c2d3d38da697d931a1311138794842a9e1c388f23e"}


def ros_environment(output: Path, port: int) -> dict:
    # Never print or save inherited credentials/environment wholesale.
    command = "source /opt/ros/noetic/setup.bash\nsource " + str(VINS) + "/devel/setup.bash\nenv -0"
    raw = subprocess.check_output(["bash", "-c", command])
    env = dict(item.split("=", 1) for item in raw.decode().split("\0") if "=" in item)
    env.update(ROS_MASTER_URI=f"http://localhost:{port}", ROS_HOSTNAME="localhost",
        ROS_HOME=str(output / "ros_home"), ROS_LOG_DIR=str(output / "ros_logs"), PYTHONDONTWRITEBYTECODE="1")
    return env


def start(command, output: Path, env: dict):
    with output.open("xb") as stream:
        return subprocess.Popen(command, stdout=stream, stderr=subprocess.STDOUT, env=env, start_new_session=True)


def stop(process) -> None:
    if process is None or process.poll() is not None:
        return
    for sig, timeout in ((signal.SIGINT, 10), (signal.SIGTERM, 5)):
        os.killpg(process.pid, sig)
        try:
            process.wait(timeout=timeout)
            return
        except subprocess.TimeoutExpired:
            pass
    os.killpg(process.pid, signal.SIGKILL)
    process.wait()


def wait_master(port: int, timeout: float = 20):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            master = xmlrpc.client.ServerProxy(f"http://localhost:{port}")
            if master.getPid("aqua_loop_capture")[0] == 1:
                return master
        except (OSError, xmlrpc.client.Error):
            pass
        time.sleep(.25)
    raise RuntimeError("Task ROS master did not become ready")


def yaml_value(node):
    if node.isString():
        return node.string()
    if node.isSeq():
        return [yaml_value(node.at(i)) for i in range(node.size())]
    if node.isMap():
        return {key: yaml_value(node.getNode(key)) for key in node.keys()}
    return node.real()


def prepare_yaml(source: Path, output: Path) -> dict:
    text = source.read_text()
    changed, count = re.subn(r'^output_path:\s*"[^"\n]*"\s*$',
        'output_path: "' + str(output / "vins_output") + '"', text, flags=re.MULTILINE)
    if count != 1:
        raise ValueError("Expected exactly one output path in frozen YAML")
    config = output / "vins_same_backend.yaml"
    with config.open("x") as f:
        f.write(changed)
    old, new = cv2.FileStorage(str(source), cv2.FILE_STORAGE_READ), cv2.FileStorage(str(config), cv2.FILE_STORAGE_READ)
    keys = list(old.root().keys())
    if keys != list(new.root().keys()):
        raise ValueError("Backend YAML key set changed")
    for key in keys:
        if key != "output_path" and yaml_value(old.getNode(key)) != yaml_value(new.getNode(key)):
            raise ValueError("Numerical/configuration change forbidden: " + key)
    camera = old.getNode("cam0_calib").string()
    if Path(camera).is_absolute() or ".." in Path(camera).parts:
        raise ValueError("Unexpected camera-config reference")
    with (output / camera).open("xb") as f:
        f.write((source.parent / camera).read_bytes())
    old.release(); new.release()
    return dict(keys=len(keys), unchanged_keys=len(keys) - 1, only_changed_key="output_path",
        camera_file=camera, camera_sha256=sha(output / camera), generated_yaml_sha256=sha(config))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sequence", choices=tuple(YAML_SHAS), required=True)
    parser.add_argument("--repeat", type=int, choices=(1, 2, 3), required=True)
    parser.add_argument("--features", type=Path, required=True)
    parser.add_argument("--export-receipt", type=Path, required=True)
    parser.add_argument("--canonical-yaml", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--port", type=int, default=13470)
    args = parser.parse_args()
    output = args.output_dir.resolve()
    # Includes capture, logs and a worst-case first shared PNG/point archive;
    # later descriptor/graph stages recheck their own bounded allowance.
    guard(output, 2300 * 1024**2)
    if output.exists():
        raise FileExistsError("Previous repeat/partial attempt preserved; inspect its receipt")
    if sha(NODE) != NODE_SHA or sha(LIB) != LIB_SHA or sha(args.canonical_yaml) != YAML_SHAS[args.sequence]:
        raise ValueError("Frozen estimator/configuration identity mismatch")
    export = json.loads(args.export_receipt.read_text())
    if export["status"] != "EXPORT_COMPLETE" or export.get("probe") is not False or sha(args.features) != export["feature_bag_sha256"]:
        raise ValueError("Not a valid full-sequence KLT input")
    # Do not start a second local estimator or interfere with unrelated processes.
    if subprocess.run(["pgrep", "-x", "vins_node"], stdout=subprocess.DEVNULL).returncode == 0:
        raise RuntimeError("Existing VINS process; do not start a duplicate")
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", args.port))
    output.mkdir(parents=True)
    (output / "vins_output").mkdir()
    audit = prepare_yaml(args.canonical_yaml, output)
    env = ros_environment(output, args.port)
    identity = dict(status="REGISTERED_BEFORE_LOCAL_RUN", sequence=args.sequence, repeat=args.repeat,
        feature_bag_sha256=export["feature_bag_sha256"], canonical_yaml_sha256=YAML_SHAS[args.sequence],
        config_audit=audit, vins_node_sha256=NODE_SHA, vins_lib_sha256=LIB_SHA,
        local_run_started=False, loop_feedback=False, shared_arms=["B", "C", "L"],
        playback_rate=1.0, playback_delay_s=3, post_play_s=8, capture_topics=CAPTURE_TOPICS,
        runner_sha256=sha(Path(__file__)), source_commit=subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
        started_at=datetime.datetime.now().astimezone().isoformat())
    with (output / "input_lock.json").open("x") as f:
        json.dump(identity, f, indent=2)
    master_process = recorder = estimator = player = None
    error = None
    socket.setdefaulttimeout(2)
    try:
        master_process = start(["roscore", "-p", str(args.port)], output / "roscore.log", env)
        master = wait_master(args.port)
        if master.setParam("aqua_loop_capture", "/use_sim_time", True)[0] != 1:
            raise RuntimeError("Could not set shared simulated clock")
        recorder = start(["rosbag", "record", "-O", str(output / "capture.bag"), "--buffsize", "256", *CAPTURE_TOPICS], output / "capture.log", env)
        estimator = start([str(NODE), str(output / "vins_same_backend.yaml")], output / "vins.log", env)
        identity["local_run_started"] = True
        deadline = time.monotonic() + 25
        while time.monotonic() < deadline:
            if estimator.poll() is not None or recorder.poll() is not None:
                raise RuntimeError("Estimator/recorder exited before playback")
            subscriptions = dict(master.getSystemState("aqua_loop_capture")[2][1])
            input_ready = all(any("record" not in n for n in subscriptions.get(t, [])) for t in ("/feature_tracker/feature", "/imu/imu"))
            capture_ready = all(any("record" in n for n in subscriptions.get(t, [])) for t in CAPTURE_TOPICS)
            if input_ready and capture_ready:
                break
            time.sleep(.25)
        else:
            raise RuntimeError("Actual estimator/capture subscriptions not ready")
        player = start(["rosbag", "play", str(args.features.resolve()), "--clock", "--rate", "1.0", "--delay", "3", "--quiet"], output / "rosbag_play.log", env)
        while player.poll() is None:
            guard(output)
            if estimator.poll() is not None or recorder.poll() is not None:
                raise RuntimeError("Estimator/recorder exited during playback")
            time.sleep(1)
        if player.returncode != 0:
            raise RuntimeError("Feature bag playback failed")
        time.sleep(8)
        identity["status"] = "LOCAL_REPLAY_FINISHED"
    except Exception as exc:
        error = str(exc)
        identity["status"] = "LOCAL_REPLAY_INVALID" if identity["local_run_started"] else "SETUP_FAILED_NO_LOCAL_RUN"
        identity["error"] = error
    finally:
        stop(player); stop(estimator); stop(recorder); stop(master_process)
    vio = output / "vins_output/vio.csv"
    log = (output / "vins.log").read_text(errors="replace") if (output / "vins.log").exists() else ""
    identity.update(completed_at=datetime.datetime.now().astimezone().isoformat(),
        initialization_log_detected="Initialization finish!" in log,
        vio_rows=sum(1 for line in vio.open() if line.strip()) if vio.exists() else 0,
        artifacts={p.name: sha(p) for p in (vio, output / "capture.bag", output / "vins.log") if p.is_file()})
    if identity["status"] == "LOCAL_REPLAY_FINISHED" and identity["vio_rows"] == 0:
        identity["status"] = "LOCAL_EMPTY_TRAJECTORY"
    with (output / "replay_receipt.json").open("x") as f:
        json.dump(identity, f, indent=2)
    print(json.dumps(identity))
    if error:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
