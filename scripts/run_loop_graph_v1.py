#!/usr/bin/env python3
"""Run one frozen native C/L graph on an existing shared local archive."""
from __future__ import annotations

import argparse
import csv
import datetime
import json
from pathlib import Path
import socket
import subprocess
import time

from archive_loop_keyframes_v1 import validate_archive
from learned_loop_encoder_v1 import guard, sha
from run_loop_vio_v1 import VINS, ros_environment, start, stop, wait_master

BINARY_SHA = "e87f60c8d9b13f4c8db90a960b7a95610fb83ff609928db9ecc00f064cf6b027"


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--local-dir", type=Path, required=True)
    p.add_argument("--archive", type=Path, required=True)
    p.add_argument("--binary", type=Path, required=True)
    p.add_argument("--arm", choices=("C", "L"), required=True)
    p.add_argument("--candidates", type=Path)
    p.add_argument("--output-dir", type=Path, required=True)
    p.add_argument("--port", type=int, default=13471)
    a = p.parse_args()
    if (a.arm == "L") != (a.candidates is not None):
        p.error("Only L requires the frozen learned candidate CSV")
    local, archive, output = a.local_dir.resolve(), a.archive.resolve(), a.output_dir.resolve()
    guard(output, 128 * 1024**2)
    if output.exists():
        raise FileExistsError("Previous graph attempt is retained, never replaced")
    if sha(a.binary) != BINARY_SHA:
        raise ValueError("Not the frozen native bridge build")
    receipt = json.loads((local / "replay_receipt.json").read_text())
    if receipt["status"] != "LOCAL_REPLAY_FINISHED":
        raise ValueError("A failed/empty local repeat cannot supply a legal graph archive")
    saved = validate_archive(archive)
    if saved["capture_bag_sha256"] != receipt["artifacts"]["capture.bag"]:
        raise ValueError("Archive/local capture identity differs")
    camera = local / receipt["config_audit"]["camera_file"]
    config = local / "vins_same_backend.yaml"
    if (sha(camera) != receipt["config_audit"]["camera_sha256"]
            or sha(config) != receipt["config_audit"]["generated_yaml_sha256"]):
        raise ValueError("Frozen camera/backend configuration identity differs")
    if subprocess.run(["pgrep", "-x", "vins_node"], stdout=subprocess.DEVNULL).returncode == 0:
        raise RuntimeError("Concurrent VINS process; do not compete for timed solver resources")
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", a.port))
    output.mkdir(parents=True)
    support = VINS / "src/VINS-Fusion-master/support_files"
    command = [str(a.binary.resolve()), str(archive), str(camera), str(config),
        str(support / "brief_k10L6.bin"), str(support / "brief_pattern.yml"),
        str(output / "native"), a.arm, receipt["sequence"], str(receipt["repeat"])]
    if a.candidates:
        command.append(str(a.candidates.resolve()))
    record = dict(status="REGISTERED_BEFORE_GRAPH", arm=a.arm, sequence=receipt["sequence"],
        repeat=receipt["repeat"], command=command, graph_started=False, binary_sha256=BINARY_SHA,
        shared_local_receipt_sha256=sha(local / "replay_receipt.json"),
        archive_roster_sha256=saved["keyframes_csv_sha256"],
        camera_sha256=sha(camera), config_sha256=sha(config),
        brief_vocabulary_sha256=sha(support / "brief_k10L6.bin"),
        brief_pattern_sha256=sha(support / "brief_pattern.yml"),
        candidates_sha256=sha(a.candidates) if a.candidates else None,
        runner_sha256=sha(Path(__file__)),
        source_commit=subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
        started_at=datetime.datetime.now().astimezone().isoformat())
    with (output / "input_lock.json").open("x") as f:
        json.dump(record, f, indent=2)
    env = ros_environment(output, a.port)
    master = graph = None
    begun = time.monotonic()
    try:
        master = start(["roscore", "-p", str(a.port)], output / "roscore.log", env)
        wait_master(a.port)
        graph = start(command, output / "native.log", env)
        record["graph_started"] = True
        begun = time.monotonic()
        while graph.poll() is None:
            guard(output)
            time.sleep(1)
        record["native_process_wall_s"] = time.monotonic() - begun
        if graph.returncode != 0:
            raise RuntimeError("Native graph exited with code " + str(graph.returncode))
        expected = int(saved["keyframes"])
        for name in ("local_body.tum", "global_body.tum"):
            if sum(bool(line.strip()) for line in (output / "native" / name).open()) != expected:
                raise ValueError("Native trajectory does not cover the shared keyframe roster")
        rows = list(csv.DictReader((output / "native/geometry.csv").open()))
        record.update(status="GRAPH_COMPLETE", keyframes=expected,
            verified_candidates=sum(r["geometry"] == "PASS" for r in rows),
            rejected_candidates=sum(r["geometry"] == "REJECT" for r in rows),
            correctness="Unknown", optimization_time_separate="Unknown: native process wall includes other work")
    except Exception as exc:
        record.update(status="GRAPH_INVALID" if record["graph_started"] else "SETUP_FAILED_NO_GRAPH", error=str(exc))
    finally:
        stop(graph); stop(master)
    record.update(completed_at=datetime.datetime.now().astimezone().isoformat(),
        artifacts={p.name: sha(p) for p in sorted((output / "native").glob("*")) if p.is_file()})
    with (output / "graph_receipt.json").open("x") as f:
        json.dump(record, f, indent=2)
    print(json.dumps(record))
    if record["status"] != "GRAPH_COMPLETE":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
