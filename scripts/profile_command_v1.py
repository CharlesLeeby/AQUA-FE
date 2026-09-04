#!/usr/bin/env python3
"""Run one command while recording process-tree and GPU resource use."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

import psutil


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def gpu_sample() -> tuple[float | None, float | None]:
    command = [
        "nvidia-smi",
        "--query-gpu=memory.used,utilization.gpu",
        "--format=csv,noheader,nounits",
    ]
    try:
        result = subprocess.run(
            command, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            text=True, timeout=2, check=False,
        )
        if result.returncode != 0 or not result.stdout.strip():
            return None, None
        values = result.stdout.splitlines()[0].split(",")
        return float(values[0].strip()), float(values[1].strip())
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return None, None


def tree_metrics(pid: int) -> dict[str, float]:
    try:
        root = psutil.Process(pid)
        processes = [root, *root.children(recursive=True)]
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return {"rss_bytes": 0.0, "cpu_seconds": 0.0, "read_bytes": 0.0, "write_bytes": 0.0}
    result = {"rss_bytes": 0.0, "cpu_seconds": 0.0, "read_bytes": 0.0, "write_bytes": 0.0}
    for process in processes:
        try:
            result["rss_bytes"] += float(process.memory_info().rss)
            times = process.cpu_times()
            result["cpu_seconds"] += float(times.user + times.system)
            io = process.io_counters()
            result["read_bytes"] += float(io.read_bytes)
            result["write_bytes"] += float(io.write_bytes)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    return result


def atomic_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    temporary.replace(path)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--log", required=True, type=Path)
    parser.add_argument("--label", required=True)
    parser.add_argument("--cwd", type=Path, default=Path.cwd())
    parser.add_argument("--timeout-s", type=float, default=3600.0)
    parser.add_argument("--sample-period-s", type=float, default=0.25)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    if not command:
        parser.error("missing command after --")

    args.log.parent.mkdir(parents=True, exist_ok=True)
    started_at = now()
    start = time.monotonic()
    baseline_gpu_memory, _ = gpu_sample()
    peak = {"rss_bytes": 0.0, "cpu_seconds": 0.0, "read_bytes": 0.0, "write_bytes": 0.0}
    peak_gpu_memory = baseline_gpu_memory
    peak_gpu_utilization = 0.0
    samples = 0
    timed_out = False
    with args.log.open("wb") as log:
        process = subprocess.Popen(
            command, cwd=str(args.cwd), env=os.environ.copy(), stdout=log,
            stderr=subprocess.STDOUT, start_new_session=True,
        )
        while process.poll() is None:
            metrics = tree_metrics(process.pid)
            for key, value in metrics.items():
                peak[key] = max(peak[key], value)
            gpu_memory, gpu_utilization = gpu_sample()
            if gpu_memory is not None:
                peak_gpu_memory = max(peak_gpu_memory or gpu_memory, gpu_memory)
            if gpu_utilization is not None:
                peak_gpu_utilization = max(peak_gpu_utilization, gpu_utilization)
            samples += 1
            if time.monotonic() - start > args.timeout_s:
                timed_out = True
                os.killpg(process.pid, signal.SIGTERM)
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL)
                break
            time.sleep(args.sample_period_s)
        return_code = process.wait()
        final_metrics = tree_metrics(process.pid)
        for key, value in final_metrics.items():
            peak[key] = max(peak[key], value)

    wall_seconds = time.monotonic() - start
    payload = {
        "schema_version": "aqua-command-resource-profile-v1",
        "label": args.label,
        "status": "COMPLETED" if return_code == 0 and not timed_out else "FAILED",
        "started_at": started_at,
        "finished_at": now(),
        "wall_seconds": wall_seconds,
        "return_code": return_code,
        "timed_out": timed_out,
        "sample_period_s": args.sample_period_s,
        "samples": samples,
        "command": command,
        "cwd": str(args.cwd),
        "log": str(args.log),
        "peak_process_tree_rss_bytes": int(peak["rss_bytes"]),
        "peak_process_tree_cpu_seconds": peak["cpu_seconds"],
        "peak_process_tree_read_bytes": int(peak["read_bytes"]),
        "peak_process_tree_write_bytes": int(peak["write_bytes"]),
        "gpu_baseline_memory_mib": baseline_gpu_memory,
        "gpu_peak_memory_mib": peak_gpu_memory,
        "gpu_peak_memory_delta_mib": (
            peak_gpu_memory - baseline_gpu_memory
            if peak_gpu_memory is not None and baseline_gpu_memory is not None else None
        ),
        "gpu_peak_global_utilization_percent": peak_gpu_utilization,
        "measurement_boundary": (
            "process-tree CPU/RSS/IO; GPU memory and utilization are device-global "
            "samples and require an otherwise idle GPU for attribution"
        ),
    }
    atomic_json(args.output, payload)
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0 if payload["status"] == "COMPLETED" else 1


if __name__ == "__main__":
    sys.exit(main())
