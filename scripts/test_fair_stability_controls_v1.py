#!/usr/bin/python3
"""Pure, non-ROS regression tests for fair-stability parsers and schedule gates."""

from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest


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


VINS = load("fair_vins", SCRIPTS / "run_fair_stability_vins_replay_v1.py")
HFNET = load("fair_hfnet", SCRIPTS / "run_fair_stability_hfnet_openloop_v1.py")
ORDINAL = load("fair_ordinal", SCRIPTS / "fair_stability_ordinal_common_v1.py")


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
            start_path.write_text(
                "schema_version=aqua-fe-fair-stability-vins-child-start-v1\n"
                "roscore_pid=101\nroscore_pgid=999\n"
                "vins_pid=102\nvins_start_ticks=12345\nvins_pgid_start=999\n"
                f"vins_executable_expected={executable}\n"
                f"vins_executable_observed={executable}\n"
                f"vins_command_observed={executable} {config} \n",
                encoding="utf-8",
            )
            start = VINS.parse_child_start(start_path, executable, config, 999)
            self.assertTrue(start["valid"], start["errors"])
            lifecycle_path = root / "child_lifecycle.txt"
            lifecycle_path.write_text(
                "schema_version=aqua-fe-fair-stability-vins-child-lifecycle-v1\n"
                "roscore_pid=101\nroscore_pgid=999\n"
                "vins_pid=102\nvins_start_ticks=12345\nvins_pgid_start=999\n"
                f"vins_executable_expected={executable}\n"
                f"vins_executable_observed={executable}\n"
                f"vins_command_observed={executable} {config} \n"
                "rosbag_returncode=0\nbag_end_vins_alive=1\noutput_nonempty=1\n"
                "vins_signal_sent=15\nvins_wait_returncode=143\nvins_early_exit=0\n"
                "bag_end_vins_identity_match=1\n"
                "bag_end_vins_start_ticks=12345\nbag_end_vins_pgid=999\n"
                f"bag_end_vins_executable={executable}\n"
                "expected_vins_wait_returncode=143\n"
                "roscore_kill_returncode=0\nroscore_wait_returncode=143\n"
                "descendant_residual_check=DELEGATED_TO_PARENT_PROCESS_GROUP\n",
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

    def test_real_frozen_schedule_is_intact_and_unstarted_tail(self) -> None:
        schedule = ORDINAL.load_schedule(HFNET.EXPERIMENT_ROOT)
        self.assertEqual(len(schedule), 120)
        self.assertEqual(schedule[0]["ordinal"], 1)
        state = ORDINAL.next_state(HFNET.EXPERIMENT_ROOT)
        self.assertIn(
            state["state"],
            {"NEEDS_PREPARATION", "READY", "TERMINAL_UNADOPTED", "TERMINAL", "COMPLETE"},
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
