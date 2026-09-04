#!/usr/bin/env python3
"""Wait until a replayed VINS process has drained its callback backlog.

`rosbag play` returning only means that publishing has finished.  VINS can
still be processing queued image/IMU callbacks, especially on low-texture
windows with repeated initialization attempts.  Killing it after a fixed
sleep silently truncates the trajectory.  This helper watches both output
files and process CPU time and returns once the backend has stayed idle for a
short, configurable interval.
"""

from __future__ import annotations

import argparse
import os
import time
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pid", required=True, type=int)
    parser.add_argument("--file", action="append", type=Path, default=[])
    parser.add_argument("--min-wait-s", type=float, default=2.0)
    parser.add_argument("--stable-s", type=float, default=4.0)
    parser.add_argument("--timeout-s", type=float, default=120.0)
    parser.add_argument("--poll-s", type=float, default=0.5)
    parser.add_argument(
        "--active-cpu-s",
        type=float,
        default=0.03,
        help="CPU-time increase per poll that resets the idle timer.",
    )
    return parser.parse_args()


def file_snapshot(paths: list[Path]) -> tuple[tuple[int, int], ...]:
    result = []
    for path in paths:
        try:
            stat = path.stat()
            result.append((stat.st_size, stat.st_mtime_ns))
        except FileNotFoundError:
            result.append((-1, -1))
    return tuple(result)


def process_cpu_seconds(pid: int) -> float | None:
    try:
        text = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8")
    except (FileNotFoundError, PermissionError, ProcessLookupError):
        return None
    # The command name is parenthesized and may contain spaces.  Fields after
    # the final ')' begin at field 3; utime/stime are fields 14/15.
    fields = text[text.rfind(")") + 2 :].split()
    if len(fields) < 13:
        return None
    ticks = int(fields[11]) + int(fields[12])
    return ticks / float(os.sysconf(os.sysconf_names["SC_CLK_TCK"]))


def main() -> int:
    args = parse_args()
    started = time.monotonic()
    last_activity = started
    previous_files = file_snapshot(args.file)
    previous_cpu = process_cpu_seconds(args.pid)

    while True:
        time.sleep(max(0.05, args.poll_s))
        now = time.monotonic()
        current_cpu = process_cpu_seconds(args.pid)
        if current_cpu is None:
            print(
                f"vins_drain_status=process_exited elapsed_s={now - started:.3f}",
                flush=True,
            )
            return 0

        current_files = file_snapshot(args.file)
        cpu_delta = (
            current_cpu - previous_cpu if previous_cpu is not None else 0.0
        )
        if current_files != previous_files or cpu_delta >= args.active_cpu_s:
            last_activity = now
        previous_files = current_files
        previous_cpu = current_cpu

        elapsed = now - started
        idle = now - last_activity
        if elapsed >= args.min_wait_s and idle >= args.stable_s:
            print(
                "vins_drain_status=idle "
                f"elapsed_s={elapsed:.3f} idle_s={idle:.3f}",
                flush=True,
            )
            return 0
        if elapsed >= args.timeout_s:
            print(
                "vins_drain_status=timeout "
                f"elapsed_s={elapsed:.3f} idle_s={idle:.3f}",
                flush=True,
            )
            return 0


if __name__ == "__main__":
    raise SystemExit(main())
