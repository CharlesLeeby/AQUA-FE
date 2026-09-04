#!/usr/bin/python3.8
"""Run the non-ROS v4 cleanup tree under a supervisor-like blocked mask."""

import json
import hashlib
import os
from pathlib import Path
import signal
import subprocess
import sys
import time


signal.pthread_sigmask(
    signal.SIG_BLOCK, {signal.SIGHUP, signal.SIGINT, signal.SIGTERM}
)
environment = dict(os.environ)
environment["A08_SEALED_FD_OWNER_PID"] = str(os.getpid())
command = [
    environment["A08_PYTHON38_PATH"],
    environment["A08_SIGNAL_MASK_LAUNCHER_PATH"],
    "aqualoc_archaeo", "8", "0", "4660", "klt", "2",
]
started = time.monotonic()
process = subprocess.Popen(command, env=environment, close_fds=True)
code = process.wait(timeout=12.0)
elapsed = time.monotonic() - started
output = Path(environment["A08_ITEM_OUTPUT_DIR"])
mask = json.loads((output / "overlay_signal_mask_manifest_v4.json").read_text())
wrapper = json.loads((output / "vins_lifecycle_start_manifest_v4.json").read_text())
terminal = json.loads((output / "vins_lifecycle_terminal_manifest_v4.json").read_text())
roscore = json.loads((output / "roscore_inherited_mask_probe.json").read_text())
control = {int(signal.SIGHUP), int(signal.SIGINT), int(signal.SIGTERM)}


def digest_valid(value):
    observed = value["contract_sha256"]
    unsigned = dict(value)
    unsigned.pop("contract_sha256")
    raw = json.dumps(unsigned, sort_keys=True, separators=(",", ":")).encode()
    return observed == hashlib.sha256(raw).hexdigest()


child_pid = int(wrapper["real_child_pid"])
result = {
    "probe_only_non_ros_non_vins": True,
    "return_code": code,
    "elapsed_seconds": elapsed,
    "owner_blocked_control_signals": sorted(control),
    "launcher_before_contains_control_signals": control <= set(mask["blocked_signals_before"]),
    "launcher_after_control_signals_empty": not (control & set(mask["blocked_signals_after"])),
    "wrapper_after_control_signals_empty": not (
        control & set(wrapper["wrapper_blocked_signals_after_unblock"])
    ),
    "roscore_inherited_control_signals_empty": not (control & set(roscore["blocked"])),
    "stubborn_vins_child_reaped": terminal["real_child_reaped"],
    "stubborn_vins_child_pid_absent": not Path(f"/proc/{child_pid}").exists(),
    "launcher_manifest_digest_valid": digest_valid(mask),
    "wrapper_start_manifest_digest_valid": digest_valid(wrapper),
    "wrapper_terminal_manifest_digest_valid": digest_valid(terminal),
    "start_terminal_pid_binding_valid": (
        terminal["wrapper_pid"] == wrapper["wrapper_pid"]
        and terminal["real_child_pid"] == child_pid
    ),
    "wrapper_terminal_status": terminal["status"],
    "shutdown_stage_signals": [row["signal"] for row in terminal["shutdown_stages"]],
}
print(json.dumps(result, indent=2, sort_keys=True))
if not (
    code == 0
    and result["launcher_before_contains_control_signals"]
    and result["launcher_after_control_signals_empty"]
    and result["wrapper_after_control_signals_empty"]
    and result["roscore_inherited_control_signals_empty"]
    and result["stubborn_vins_child_reaped"]
    and result["stubborn_vins_child_pid_absent"]
    and result["launcher_manifest_digest_valid"]
    and result["wrapper_start_manifest_digest_valid"]
    and result["wrapper_terminal_manifest_digest_valid"]
    and result["start_terminal_pid_binding_valid"]
    and elapsed < 5.0
):
    raise SystemExit(1)
