#!/usr/bin/python3
"""Pure, non-ROS regression tests for fair-stability parsers and schedule gates."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))


def load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


VINS = load("fair_vins_v2", SCRIPTS / "run_fair_stability_vins_replay_v2.py")
HFNET = load("fair_hfnet_v2", SCRIPTS / "run_fair_stability_hfnet_openloop_v2.py")
ORDINAL = load("fair_ordinal_v2", SCRIPTS / "fair_stability_ordinal_common_v2.py")
RESOURCE = load(
    "fair_runtime_resource_monitor",
    SCRIPTS / "fair_stability_runtime_resource_monitor_v2.py",
)


def hfnet_row(stamp: int, x: str = "0") -> str:
    return f"{stamp} {x} 0 0 0 0 0 1\n"


def vins_row(stamp: int, x: str = "0", velocity: str = "0") -> str:
    return f"{stamp},{x},0,0,0,0,0,1,{velocity},0,0,\n"


class TrajectoryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.stamps = [1_000_000_000 + index * 100_000_000 for index in range(100)]

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_hfnet_count_boundaries(self) -> None:
        for count, expected in ((49, 0.49), (50, 0.50), (69, 0.69), (70, 0.70)):
            path = self.root / f"hf_{count}.txt"
            path.write_text("".join(hfnet_row(value) for value in self.stamps[:count]), encoding="ascii")
            parsed = HFNET.parse_trajectory(path, self.stamps)
            self.assertTrue(parsed["valid"])
            self.assertAlmostEqual(parsed["coverage_fraction"], expected)
            self.assertAlmostEqual(parsed["longest_contiguous_fraction"], expected)

    def test_vins_empty_nonfinite_and_extra_field(self) -> None:
        empty = self.root / "empty.csv"
        empty.write_text("", encoding="ascii")
        self.assertFalse(VINS.parse_vio(empty, self.stamps)["valid"])
        hfnet_empty = self.root / "hfnet_empty.txt"
        hfnet_empty.write_text("", encoding="ascii")
        self.assertFalse(HFNET.parse_trajectory(hfnet_empty, self.stamps)["valid"])
        bad = self.root / "bad.csv"
        bad.write_text(vins_row(self.stamps[0], velocity="nan"), encoding="ascii")
        self.assertFalse(VINS.parse_vio(bad, self.stamps)["valid"])

    def test_strict_and_unique_association(self) -> None:
        duplicate = self.root / "duplicate.txt"
        duplicate.write_text(
            hfnet_row(self.stamps[0]) + hfnet_row(self.stamps[0] + 1), encoding="ascii"
        )
        self.assertFalse(HFNET.parse_trajectory(duplicate, self.stamps)["valid"])
        reverse = self.root / "reverse.csv"
        reverse.write_text(
            vins_row(self.stamps[1]) + vins_row(self.stamps[0]), encoding="ascii"
        )
        self.assertFalse(VINS.parse_vio(reverse, self.stamps)["valid"])


class LogTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.first_ns = 10_000_000_000

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_vins_requires_one_parseable_initialization(self) -> None:
        none = self.root / "none.log"
        none.write_text("ordinary line\n", encoding="utf-8")
        parsed = VINS.parse_vins_log(none, self.first_ns, (10.0, 20.0))
        self.assertEqual(parsed["initialization_count"], 0)
        self.assertIsNone(parsed["initialization_latency_seconds"])
        multiple = self.root / "multiple.log"
        multiple.write_text(
            "[ INFO] [1.0, 11.0]: Initialization finish!\n"
            "[ INFO] [2.0, 15.0]: restart the estimator!\n"
            "[ INFO] [3.0, 16.0]: Initialization finish!\n",
            encoding="utf-8",
        )
        parsed = VINS.parse_vins_log(multiple, self.first_ns, (12.0, 18.0))
        self.assertEqual(parsed["initialization_count"], 2)
        self.assertEqual(parsed["reinitialization_in_support_count"], 1)
        self.assertEqual(parsed["reboot_or_reset_in_support_count"], 1)

    def _hfnet_log(self, body: str) -> tuple[Path, Path]:
        stdout = self.root / f"stdout_{len(list(self.root.glob('stdout*')))}.log"
        stderr = stdout.with_name(stdout.name.replace("stdout", "stderr"))
        stdout.write_text(
            body
            + "Saving trajectory to /tmp/t ...\n"
            + "There are 1 maps in the atlas\n"
            + "  Map 0 has 1 KFs\n"
            + "End of saving trajectory to /tmp/t ...\n",
            encoding="utf-8",
        )
        stderr.write_text("", encoding="utf-8")
        return stdout, stderr

    def test_hfnet_reset_risk_and_init_validation(self) -> None:
        stdout, stderr = self._hfnet_log(
            "Init frame id: 5\n"
            "Fail to track local map!\n"
            "SYSTEM-> Reseting active map in monocular case\n"
            "Init frame id: 30\n"
        )
        parsed = HFNET.parse_log(stdout, stderr, 100)
        self.assertTrue(parsed["valid"])
        self.assertEqual(parsed["active_map_reset_count"], 1)
        self.assertEqual(parsed["solver_risk_count"], 1)
        events = HFNET.accepted_events(
            parsed, {"longest_contiguous_relative_indices_inclusive": [20, 90]}
        )
        self.assertTrue(events["unresolved_resets"])
        self.assertTrue(events["unresolved_solver_risks"])
        self.assertEqual(events["support_reinitializations"], [30])
        stdout2, stderr2 = self._hfnet_log("Init frame id: 100\n")
        self.assertFalse(HFNET.parse_log(stdout2, stderr2, 100)["valid"])


class LifecycleAndScheduleTests(unittest.TestCase):
    def test_vins_lifecycle_exact_identity(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            executable = root / "vins_node"
            config = root / "config.yaml"
            executable.write_bytes(b"binary")
            config.write_text("config", encoding="utf-8")
            start_path = root / "child_start_receipt.txt"
            start_values = {
                "schema_version": "aqua-fe-fair-stability-vins-child-start-v2",
                "experiment_id": ORDINAL.EXPERIMENT_ID,
                "tag": "test-tag",
                "wrapper_pid": "999",
                "wrapper_start_ticks": "9000",
                "wrapper_pgid": "999",
                "roscore_pid": "101",
                "roscore_start_ticks": "10001",
                "roscore_executable": "/usr/bin/python3",
                "roscore_command": "/usr/bin/python3 /opt/ros/noetic/bin/roscore",
                "roscore_pgid": "999",
                "vins_pid": "102",
                "vins_start_ticks": "12345",
                "vins_pgid_start": "999",
                "vins_executable_expected": str(executable),
                "vins_executable_observed": str(executable),
                "vins_command_observed": f"{executable} {config} ",
            }
            start_path.write_text(
                "".join(f"{key}={value}\n" for key, value in start_values.items()),
                encoding="utf-8",
            )
            start = VINS.parse_child_start(start_path, executable, config, 999)
            self.assertTrue(start["valid"], start["errors"])
            lifecycle_path = root / "child_lifecycle.txt"
            lifecycle_values = dict(start_values)
            lifecycle_values.update(
                {
                    "schema_version": "aqua-fe-fair-stability-vins-child-lifecycle-v2",
                    "launch_checkpoint": "COMPLETE",
                    "rosbag_returncode": "0",
                    "rosbag_reaped": "1",
                    "bag_end_vins_alive": "1",
                    "output_nonempty": "1",
                    "vins_signal_sent": "15",
                    "vins_wait_returncode": "143",
                    "vins_reaped": "1",
                    "vins_forced_kill": "0",
                    "vins_early_exit": "0",
                    "bag_end_vins_identity_match": "1",
                    "bag_end_vins_start_ticks": "12345",
                    "bag_end_vins_pgid": "999",
                    "bag_end_vins_executable": str(executable),
                    "expected_vins_wait_returncode": "143",
                    "roscore_identity_match": "1",
                    "roscore_end_start_ticks": "10001",
                    "roscore_end_pgid": "999",
                    "roscore_kill_returncode": "0",
                    "roscore_wait_returncode": "143",
                    "roscore_reaped": "1",
                    "roscore_forced_kill": "0",
                    "descendant_residual_count": "0",
                }
            )
            lifecycle_path.write_text(
                "".join(
                    f"{key}={value}\n" for key, value in lifecycle_values.items()
                ),
                encoding="utf-8",
            )
            lifecycle = VINS.parse_child_lifecycle(lifecycle_path, start)
            self.assertTrue(lifecycle["valid"], lifecycle["errors"])
            lifecycle_path.write_text(
                lifecycle_path.read_text().replace(
                    "bag_end_vins_identity_match=1", "bag_end_vins_identity_match=0"
                ),
                encoding="utf-8",
            )
            self.assertFalse(VINS.parse_child_lifecycle(lifecycle_path, start)["valid"])

    def test_v2_schedule_and_pristine_attempt_matrix(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            schedule = HFNET.frozen_schedule()
            schedule_path = root / "planned_schedule.json"
            schedule_path.write_bytes(ORDINAL.canonical_json(schedule))
            self.assertEqual(ORDINAL.identity(schedule_path)["sha256"], ORDINAL.SCHEDULE_SHA256)
            manifest_path = root / "experiment_manifest.json"
            manifest_path.write_bytes(
                ORDINAL.canonical_json(
                    {
                        "experiment_id": ORDINAL.EXPERIMENT_ID,
                        "planned_schedule": ORDINAL.identity(schedule_path),
                    }
                )
            )
            backend = (
                root
                / "vins_dev_nativeq_schedfix_runtimeexcl_v2"
                / "backend_freeze.json"
            )
            backend.parent.mkdir(parents=True)
            backend.write_text("frozen\n", encoding="ascii")
            rows = []
            for cell in schedule:
                attempt_root = ORDINAL.attempt_root(root, cell, 1)
                attempt_root.mkdir(parents=True)
                attempt_manifest = attempt_root / "attempt_manifest.json"
                attempt_manifest.write_bytes(
                    ORDINAL.canonical_json(
                        {
                            "experiment_id": ORDINAL.EXPERIMENT_ID,
                            "case_id": cell["case_id"],
                            "arm": cell["arm"],
                            "repeat": cell["repeat"],
                            "attempt_index": 1,
                        }
                    )
                )
                rows.append(
                    {
                        "ordinal": cell["ordinal"],
                        "case_id": cell["case_id"],
                        "arm": cell["arm"],
                        "repeat": cell["repeat"],
                        "attempt_index": 1,
                        "attempt_root": str(attempt_root),
                        "attempt_manifest": ORDINAL.identity(attempt_manifest),
                    }
                )
            matrix_path = root / "attempt_matrix_freeze_v2.json"
            matrix_path.write_bytes(
                ORDINAL.canonical_json(
                    {
                        "schema_version": "aqua-fe-fair-stability-attempt-matrix-freeze-v2",
                        "experiment_id": ORDINAL.EXPERIMENT_ID,
                        "status": "FROZEN_BEFORE_ANY_V2_ESTIMATOR_START",
                        "experiment_manifest": ORDINAL.identity(manifest_path),
                        "planned_schedule": ORDINAL.identity(schedule_path),
                        "backend_freeze": ORDINAL.identity(backend),
                        "attempts": rows,
                    }
                )
            )
            self.assertEqual(len(ORDINAL.load_attempt_matrix(root)["attempts"]), 120)
            state = ORDINAL.next_state(root)
            self.assertEqual(state["state"], "READY")
            self.assertEqual(state["cell"]["ordinal"], 1)


class RuntimeResourceMonitorTests(unittest.TestCase):
    @staticmethod
    def _record(
        pid: int,
        start_ticks: int,
        command: str,
        *,
        ppid: int = 1,
        pgid: int | None = None,
        executable: str = "/bin/bash",
        comm: str = "bash",
    ) -> dict[str, object]:
        tokens = command.split()
        return {
            "pid": pid,
            "start_ticks": start_ticks,
            "ppid": ppid,
            "pgid": pid if pgid is None else pgid,
            "session": pid,
            "state": "S",
            "executable": executable,
            "comm": comm,
            "cmdline": tokens,
            "command": command,
            "cmdline_sha256": "0" * 64,
            "read_errors": [],
        }

    def test_delayed_spawn_parent_commands_are_conflicts_unless_owned(self) -> None:
        names = (
            "run_mimir_selected_ours_vins.sh",
            "run_mimir_selected_klt_vins.sh",
            "run_frozen_positive_replay_regression.sh",
            "run_learned_seedchain_eval.sh",
            "run_existing_featurebag_vins_replay_only",
        )
        for index, name in enumerate(names, 1):
            with self.subTest(name=name):
                record = self._record(index, 100 + index, f"/bin/bash /tmp/{name}")
                conflicts = RESOURCE._external_process_conflicts([record], set())
                self.assertEqual([row["pid"] for row in conflicts], [index])
                owned = {(index, 100 + index)}
                self.assertEqual(
                    RESOURCE._external_process_conflicts([record], owned), []
                )
        orphan_rosout = self._record(
            90,
            190,
            "/opt/ros/noetic/lib/rosout/rosout __name:=rosout",
            executable="/opt/ros/noetic/lib/rosout/rosout",
            comm="rosout",
        )
        self.assertEqual(
            RESOURCE._external_process_conflicts([orphan_rosout], set()), []
        )

    def test_gpu_todesk_has_no_exemption_and_pid_reuse_is_not_owned(self) -> None:
        records = {
            100: self._record(100, 20, "/usr/bin/other-gpu", executable="/usr/bin/other-gpu", comm="other-gpu"),
            102: self._record(102, 12, "/opt/todesk/todesk", executable="/opt/todesk/todesk", comm="todesk"),
            103: self._record(103, 13, "/tmp/owned-gpu", executable="/tmp/owned-gpu", comm="owned-gpu"),
        }

        def read(pid: int):
            return records.get(pid), []

        applications = [
            {"pid": 100, "process_name": "reused", "used_memory_mib": "10", "raw": "100, reused, 10"},
            {"pid": 101, "process_name": "stale", "used_memory_mib": "10", "raw": "101, stale, 10"},
            {"pid": 102, "process_name": "ToDesk", "used_memory_mib": "10", "raw": "102, ToDesk, 10"},
            {"pid": 103, "process_name": "owned", "used_memory_mib": "10", "raw": "103, owned, 10"},
        ]
        known = {(100, 10), (101, 11), (103, 13)}
        with mock.patch.object(RESOURCE, "_read_process_record", side_effect=read):
            result = RESOURCE._classify_gpu_applications(
                applications, {(103, 13)}, known
            )
        self.assertEqual(
            {row["pid"] for row in result["external"]}, {100, 102}
        )
        self.assertEqual([row["pid"] for row in result["stale_owned"]], [101])
        self.assertEqual([row["pid"] for row in result["current_owned"]], [103])

    def test_proc_and_gpu_start_gap_contracts_are_independent(self) -> None:
        def samples(*starts: int) -> list[dict[str, object]]:
            return [{"probe_started_monotonic_ns": value} for value in starts]

        proc = RESOURCE._sampling_gap_report(
            samples(10_000_000, 210_000_000, 410_000_000),
            0,
            610_000_000,
            RESOURCE.PROC_TARGET_INTERVAL_SECONDS,
            RESOURCE.PROC_MAX_START_GAP_SECONDS,
        )
        gpu = RESOURCE._sampling_gap_report(
            samples(20_000_000, 770_000_000),
            0,
            900_000_000,
            RESOURCE.GPU_TARGET_INTERVAL_SECONDS,
            RESOURCE.GPU_MAX_START_GAP_SECONDS,
        )
        self.assertTrue(proc["proven"])
        self.assertTrue(gpu["proven"])
        violated = RESOURCE._sampling_gap_report(
            samples(1_000_000, 252_000_000),
            0,
            260_000_000,
            RESOURCE.PROC_TARGET_INTERVAL_SECONDS,
            RESOURCE.PROC_MAX_START_GAP_SECONDS,
        )
        self.assertFalse(violated["proven"])
        self.assertEqual(len(violated["start_gap_violations"]), 1)

    def test_signal_rechecks_exact_identity_before_individual_kill(self) -> None:
        monitor = RESOURCE.RuntimeResourceMonitor.__new__(
            RESOURCE.RuntimeResourceMonitor
        )
        monitor.pid = 200
        monitor.pgid = 200
        monitor._lock = threading.RLock()
        monitor._known_owned = {(201, 10)}
        monitor._active_owned = {(201, 10)}
        monitor._monitor_errors = []
        monitor._cleanup_actions = []
        snapshot = self._record(201, 10, "/tmp/owned", pgid=300)
        reused = self._record(201, 11, "/tmp/reused", pgid=300)
        with mock.patch.object(
            RESOURCE, "_scan_processes", return_value=([snapshot], [])
        ), mock.patch.object(
            RESOURCE, "_read_process_record", return_value=(reused, [])
        ), mock.patch.object(RESOURCE.os, "kill") as kill, mock.patch.object(
            RESOURCE.os, "killpg"
        ) as killpg:
            monitor._signal_current_owned(RESOURCE.signal.SIGTERM, "test")
        kill.assert_not_called()
        killpg.assert_not_called()

    def test_harmless_child_writes_complete_exclusive_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "runtime_resource_monitor.json"
            query = {
                "returncode": 0,
                "stdout": "not-a-pid, ToDesk, 10\n",
                "stderr": "",
                "error": None,
            }
            with mock.patch.object(RESOURCE, "_run_gpu_compute_query", return_value=query):
                process = subprocess.Popen(
                    [sys.executable, "-c", "import time; time.sleep(0.35)"],
                    start_new_session=True,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                monitor = RESOURCE.RuntimeResourceMonitor(process, output)
                returncode, reaped, timed_out = monitor.wait(5.0)
                self.assertEqual(returncode, 0)
                self.assertTrue(reaped)
                self.assertFalse(timed_out)
                self.assertTrue(monitor.reap_process_group())
                receipt = monitor.finalize()
                self.assertTrue(output.is_file())
                self.assertEqual(
                    json.loads(output.read_text(encoding="utf-8"))["schema_version"],
                    RESOURCE.SCHEMA_VERSION,
                )
        self.assertIn("intrusion_detected", receipt)
        self.assertIn("monitor_proven", receipt)
        self.assertFalse(receipt["monitor_proven"])
        self.assertTrue(receipt["intrusion_detected"])
        self.assertIn("GPU_COMPUTE_ROW_PID_INVALID", receipt["probe_errors"])
        self.assertIn("proc", receipt["samples"])
        self.assertIn("gpu", receipt["samples"])
        self.assertGreaterEqual(len(receipt["samples"]["proc"]), 1)
        self.assertGreaterEqual(len(receipt["samples"]["gpu"]), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
