#!/usr/bin/python3
"""Pure, non-ROS regression tests for fair-stability parsers and schedule gates."""

from __future__ import annotations

import importlib.util
import hashlib
import json
import os
from pathlib import Path
import re
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


VINS = load("fair_vins_v6", SCRIPTS / "run_fair_stability_vins_replay_v6.py")
HFNET = load("fair_hfnet_v6", SCRIPTS / "run_fair_stability_hfnet_openloop_v6.py")
ORDINAL = load("fair_ordinal_v6", SCRIPTS / "fair_stability_ordinal_common_v6.py")
NEXT = load("fair_next_v6", SCRIPTS / "run_fair_stability_next_v6.py")
SUMMARY = load("fair_summary_v6", SCRIPTS / "summarize_fair_stability_v6.py")
RESOURCE = load(
    "fair_runtime_resource_monitor",
    SCRIPTS / "fair_stability_runtime_resource_monitor_v6.py",
)
SYSTEMD = load(
    "fair_systemd_supervisor_v6",
    SCRIPTS / "run_fair_stability_systemd_supervisor_v6.py",
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
        boundary_stdout, boundary_stderr = self._hfnet_log(
            "Init frame id: 5\n"
            "SYSTEM-> Reseting active map in monocular case\n"
            "Init frame id: 20\n"
        )
        boundary_log = HFNET.parse_log(boundary_stdout, boundary_stderr, 100)
        boundary = HFNET.accepted_events(
            boundary_log,
            {"longest_contiguous_relative_indices_inclusive": [20, 90]},
        )
        self.assertTrue(boundary["unresolved_resets"])
        self.assertEqual(boundary["support_reinitializations"], [20])
        stdout2, stderr2 = self._hfnet_log("Init frame id: 100\n")
        self.assertFalse(HFNET.parse_log(stdout2, stderr2, 100)["valid"])


class LifecycleAndScheduleTests(unittest.TestCase):
    def test_vins_lifecycle_exact_identity(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            executable = root / "vins_node"
            config = root / "config.yaml"
            camera = root / "camera.yaml"
            executable.write_bytes(b"binary")
            config.write_text("config", encoding="utf-8")
            camera.write_text("camera", encoding="utf-8")
            camera_identity = VINS.identity(camera)
            start_path = root / "child_start_receipt.txt"
            start_values = {
                "schema_version": "aqua-fe-fair-stability-vins-child-start-v6",
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
                "source_camera_config": str(camera),
                "runtime_camera_config": str(camera),
                "runtime_camera_config_size_bytes": str(
                    camera_identity["size_bytes"]
                ),
                "runtime_camera_config_sha256": camera_identity["sha256"],
                "runtime_camera_config_matches_source": "1",
            }
            start_path.write_text(
                "".join(f"{key}={value}\n" for key, value in start_values.items()),
                encoding="utf-8",
            )
            start = VINS.parse_child_start(
                start_path, executable, config, camera, camera_identity, 999
            )
            self.assertTrue(start["valid"], start["errors"])
            bad_start_values = dict(start_values)
            bad_start_values["runtime_camera_config_sha256"] = "0" * 64
            start_path.write_text(
                "".join(
                    f"{key}={value}\n" for key, value in bad_start_values.items()
                ),
                encoding="utf-8",
            )
            self.assertFalse(
                VINS.parse_child_start(
                    start_path, executable, config, camera, camera_identity, 999
                )["valid"]
            )
            start_path.write_text(
                "".join(f"{key}={value}\n" for key, value in start_values.items()),
                encoding="utf-8",
            )
            lifecycle_path = root / "child_lifecycle.txt"
            lifecycle_values = dict(start_values)
            lifecycle_values.update(
                {
                    "schema_version": "aqua-fe-fair-stability-vins-child-lifecycle-v6",
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

    def test_v6_schedule_and_pristine_attempt_matrix(self) -> None:
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
                / "vins_dev_nativeq_schedfix_runtimeexcl_v6"
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
                            "schema_version": (
                                "aqua-fe-fair-stability-hfnet-attempt-v6"
                                if str(cell["arm"]).startswith("hfnet_openloop_")
                                else "aqua-fe-fair-stability-vins-attempt-v6"
                            ),
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
                        "maximum_replacement_attempts": (
                            ORDINAL.MAX_REPLACEMENT_ATTEMPTS_PER_CELL
                        ),
                        "maximum_total_attempts": ORDINAL.MAX_ATTEMPTS_PER_CELL,
                        "attempt_manifest": ORDINAL.identity(attempt_manifest),
                    }
                )
            matrix_path = root / "attempt_matrix_freeze_v6.json"
            matrix_path.write_bytes(
                ORDINAL.canonical_json(
                    {
                        "schema_version": "aqua-fe-fair-stability-attempt-matrix-freeze-v6",
                        "experiment_id": ORDINAL.EXPERIMENT_ID,
                        "status": "FROZEN_BEFORE_ANY_V6_ESTIMATOR_START",
                        "experiment_manifest": ORDINAL.identity(manifest_path),
                        "planned_schedule": ORDINAL.identity(schedule_path),
                        "backend_freeze": ORDINAL.identity(backend),
                        "replacement_policy": {
                            "automatic_retry_pipeline_failure_codes": sorted(
                                ORDINAL.AUTOMATIC_RETRY_PIPELINE_FAILURES
                            ),
                            "maximum_replacement_attempts_per_planned_cell": (
                                ORDINAL.MAX_REPLACEMENT_ATTEMPTS_PER_CELL
                            ),
                            "maximum_total_attempts_per_planned_cell": (
                                ORDINAL.MAX_ATTEMPTS_PER_CELL
                            ),
                            "same_pipeline_failure_code_may_repeat": False,
                        },
                        "claims": {
                            "attempt_count": 120,
                            "v1_results_imported": False,
                            "v2_results_imported": False,
                            "v3_results_imported": False,
                            "v4_results_imported": False,
                            "v5_results_imported": False,
                            "dispatch_claim_count": 0,
                            "start_claim_count": 0,
                            "run_result_count": 0,
                            "terminal_receipt_count": 0,
                        },
                        "attempts": rows,
                    }
                )
            )
            matrix = ORDINAL.load_attempt_matrix(root)
            self.assertEqual(len(matrix["attempts"]), 120)
            self.assertIs(matrix["claims"]["v1_results_imported"], False)
            self.assertIs(matrix["claims"]["v2_results_imported"], False)
            self.assertIs(matrix["claims"]["v3_results_imported"], False)
            self.assertIs(matrix["claims"]["v4_results_imported"], False)
            self.assertIs(matrix["claims"]["v5_results_imported"], False)
            state = ORDINAL.next_state(root)
            self.assertEqual(state["state"], "READY")
            self.assertEqual(state["cell"]["ordinal"], 1)


class V6ControlRegressionTests(unittest.TestCase):
    def test_summary_tristate_observability_and_window_inference(self) -> None:
        observed_none = [
            {"event_log_observable": True, "reset_count": 0} for _ in range(3)
        ]
        self.assertIs(SUMMARY.tri_state_any(
            observed_none, "reset_count", "event_log_observable"
        ), False)
        self.assertIsNone(SUMMARY.tri_state_any(
            observed_none[:2], "reset_count", "event_log_observable"
        ))
        partly_unobservable = observed_none[:2] + [
            {"event_log_observable": False, "reset_count": None}
        ]
        self.assertIsNone(SUMMARY.tri_state_any(
            partly_unobservable, "reset_count", "event_log_observable"
        ))
        partly_unobservable[0]["reset_count"] = 1
        self.assertIs(SUMMARY.tri_state_any(
            partly_unobservable, "reset_count", "event_log_observable"
        ), True)

        missing_log = SUMMARY.normalize_result(
            {"ordinal": 1, "case_id": "c", "arm": "hfnet_openloop_675", "repeat": 1},
            {
                "attempt_index": 1,
                "invalid_chain": [],
                "result": {
                    "status": "ALGORITHM_FAILURE",
                    "clean_success": False,
                    "failure_codes": ["FINAL_ATLAS_EMPTY_OR_UNPARSEABLE"],
                    "algorithm_failure_codes": ["FINAL_ATLAS_EMPTY_OR_UNPARSEABLE"],
                    "support": {"trajectory": {}, "log": {}, "events": {}},
                    "execution": {},
                },
            },
        )
        self.assertFalse(missing_log["event_log_observable"])
        self.assertIsNone(missing_log["reset_count"])
        self.assertIsNone(missing_log["unresolved_reset"])

        cases = [f"case_{index}" for index in range(10)]
        arms = (
            "learned_klt_vins", "pure_klt_vins",
            "hfnet_openloop_675", "hfnet_openloop_350",
        )
        rows = []
        for case_id in cases:
            for arm in arms:
                for repeat in (1, 2, 3):
                    rows.append(
                        {
                            "case_id": case_id,
                            "arm": arm,
                            "repeat": repeat,
                            "clean_success": arm == "learned_klt_vins",
                        }
                    )
        analysis = SUMMARY.window_level_analysis(rows, cases, True)
        self.assertTrue(analysis["analysis_authorized"])
        primary = analysis["contrasts"]["primary"]
        self.assertEqual(primary["window_clean_count_differences"], [3] * 10)
        self.assertEqual(
            primary["exact_window_block_swap"]["p_value"], 2 / 1024
        )
        self.assertEqual(primary["paired_window_bootstrap"]["ci"], [1.0, 1.0])
        self.assertEqual(
            primary["paired_window_bootstrap"]["unique_count_vectors"], 92378
        )
        self.assertEqual(
            sum(
                weight
                for _, weight in SUMMARY.multinomial_window_count_vectors(10)
            ),
            10**10,
        )
        self.assertTrue(primary["supports_higher_clean_stability_for_arm_a"])
        learned_secondary = analysis["contrasts"][
            "secondary_learned_vs_pure_klt"
        ]
        hfnet_secondary = analysis["contrasts"]["secondary_hfnet_675_vs_350"]
        self.assertTrue(analysis["multiplicity"]["primary_gate_open"])
        self.assertAlmostEqual(
            learned_secondary["holm_adjusted_p_value"], 4 / 1024
        )
        self.assertTrue(learned_secondary["holm_reject_at_alpha_0_05"])
        self.assertTrue(
            learned_secondary[
                "holm_rejects_and_observed_direction_favors_arm_a"
            ]
        )
        self.assertEqual(hfnet_secondary["holm_adjusted_p_value"], 1.0)
        self.assertFalse(hfnet_secondary["holm_reject_at_alpha_0_05"])
        self.assertFalse(
            hfnet_secondary[
                "holm_rejects_and_observed_direction_favors_arm_a"
            ]
        )
        self.assertNotIn(
            "supports_higher_clean_stability_for_arm_a", learned_secondary
        )
        zero_boundary = SUMMARY.paired_window_bootstrap_interval(
            [-2, -1, 2, 1, 2, 1, 2, 1, 2, 1], 3
        )
        self.assertEqual(zero_boundary["ci_integer_numerators"][0], 0)
        self.assertEqual(zero_boundary["ci_common_denominator"], 30)
        self.assertEqual(zero_boundary["ci"][0], 0.0)
        self.assertEqual(
            primary["exact_window_block_swap"]["extreme_assignments"], 2
        )

        gate_closed_rows = [dict(row, clean_success=False) for row in rows]
        gate_closed = SUMMARY.window_level_analysis(gate_closed_rows, cases, True)
        self.assertFalse(gate_closed["multiplicity"]["primary_gate_open"])
        for name in (
            "secondary_learned_vs_pure_klt",
            "secondary_hfnet_675_vs_350",
        ):
            secondary = gate_closed["contrasts"][name]
            self.assertEqual(
                secondary["inferential_status"], "DESCRIPTIVE_PRIMARY_GATE_CLOSED"
            )
            self.assertIsNone(secondary["holm_adjusted_p_value"])
            self.assertIsNone(secondary["holm_reject_at_alpha_0_05"])
            self.assertIsNone(
                secondary[
                    "holm_rejects_and_observed_direction_favors_arm_a"
                ]
            )

        missing_one = SUMMARY.window_level_analysis(rows[:-1], cases, True)
        self.assertFalse(missing_one["analysis_authorized"])
        self.assertIsNone(missing_one["contrasts"])
        duplicate_case_order = SUMMARY.window_level_analysis(
            rows, cases[:-1] + [cases[0]], True
        )
        self.assertFalse(duplicate_case_order["analysis_authorized"])
        self.assertIsNone(duplicate_case_order["contrasts"])

    def test_receipt_timestamps_require_explicit_utc(self) -> None:
        self.assertTrue(ORDINAL.valid_utc_receipt_timestamp("2026-08-29T12:34:56+00:00"))
        self.assertTrue(ORDINAL.valid_utc_receipt_timestamp("2026-08-29T12:34:56Z"))
        self.assertFalse(ORDINAL.valid_utc_receipt_timestamp("2026-08-29T12:34:56"))
        self.assertFalse(ORDINAL.valid_utc_receipt_timestamp("2026-08-29T20:34:56+08:00"))
        self.assertFalse(ORDINAL.valid_utc_receipt_timestamp("not-a-timestamp"))
        self.assertFalse(ORDINAL.valid_utc_receipt_timestamp(None))

    CHILD = SCRIPTS / "run_fair_stability_vins_replay_child_v6.sh"

    def test_hfnet_generated_config_uses_opencv2(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            model_dir = root / "model"
            config = root / "settings.yaml"
            config.write_text(
                "%YAML:1.0\n"
                "Camera.fps: 5\n"
                "Extractor.nFeatures: 675\n"
                "loopClosing: 0\n"
                f'Extractor.modelPath: "{model_dir}/"\n',
                encoding="utf-8",
            )
            observed = HFNET.validate_generated_config(config, 5, 675, model_dir)
            self.assertEqual(observed["Camera.fps"], 5)
            self.assertEqual(observed["Extractor.nFeatures"], 675)
            self.assertEqual(observed["loopClosing"], 0)
            self.assertEqual(observed["Extractor.modelPath"], f"{model_dir}/")

    def test_canonical_td_and_matched_imu_materialization(self) -> None:
        imu_rows = [
            (stamp, stamp, (0.1, -0.2, 0.3, 1.0, -2.0, 3.0))
            for stamp in (100, 200, 300, 400)
        ]
        payload, shifted, receipt = HFNET.matched_imu_csv(
            imu_rows, "0.0000000015", [250], "synthetic"
        )
        self.assertEqual(shifted, [98, 198, 298, 398])
        self.assertLessEqual(receipt["maximum_rounding_residual_ns"], 0.5)
        self.assertTrue(receipt["all_camera_predecessor_indices_equal"])
        self.assertGreater(
            receipt["native_predecessor_comparison"][
                "minimum_boundary_margin_seconds"
            ],
            0.0,
        )
        rows = payload.decode("ascii").splitlines()
        self.assertEqual(len(rows), 5)
        self.assertEqual([int(row.split(",", 1)[0]) for row in rows[1:]], shifted)
        with self.assertRaisesRegex(
            HFNET.ContractError, "CROSS_BACKEND_IMU_CUTOFF_MISMATCH"
        ):
            HFNET.matched_imu_csv(imu_rows, "0.0", [200], "boundary-equality")

        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "source.yaml"
            source.write_text(
                "%YAML:1.0\n"
                "multiple_thread: 0\n"
                'imu_topic: "/rtimulib_node/imu"\n'
                'output_path: "/tmp/old"\n'
                "loop_closure: 0\n"
                "td: -0.033694112369382575\n"
                "estimate_td: 0\n",
                encoding="utf-8",
            )
            config, patch = VINS.canonical_vins_config(
                source, "aqualoc_archaeology"
            )
            self.assertTrue(patch["td_changed"])
            self.assertEqual(
                patch["canonical_td_seconds"], "-0.053694112369382575"
            )
            self.assertIn(b"td: -0.053694112369382575", config)
            template = Path(temporary) / "template.yaml"
            template.write_bytes(config)
            runtime = VINS.runtime_vins_config_payload(
                template, Path(temporary) / "output"
            )
            self.assertIn(
                f'output_path: "{Path(temporary) / "output"}"'.encode(), runtime
            )

    def test_supervised_residuals_are_nonretryable_pipeline_faults(self) -> None:
        expected = ["SUPERVISED_SHUTDOWN_CONTRACT_UNPROVEN"]
        self.assertEqual(VINS.supervised_shutdown_failure_codes(False), expected)
        self.assertEqual(
            HFNET.supervised_shutdown_failure_codes(True, [{"pid": 1}]), expected
        )
        self.assertEqual(VINS.supervised_shutdown_failure_codes(True), [])
        self.assertEqual(HFNET.supervised_shutdown_failure_codes(True, []), [])
        self.assertNotIn(
            expected[0], ORDINAL.AUTOMATIC_RETRY_PIPELINE_FAILURES
        )

    def test_vins_rejects_prior_result_import_claims(self) -> None:
        roster: dict[str, dict[str, str]] = {}
        historical: dict[str, dict[str, str]] = {}
        manifest = {
            "schema_version": "aqua-fe-fair-stability-hfnet-input-freeze-v6",
            "status": "FROZEN_INPUTS_NO_ESTIMATOR_STARTED",
            "experiment_id": VINS.EXPERIMENT_ID,
            "protocol": {"sha256": VINS.EXPECTED_PROTOCOL_SHA256},
            "roster": {"sha256": VINS.EXPECTED_ROSTER_SHA256},
            "historical_results": {"path": "p", "size_bytes": 1, "sha256": "h"},
            "historical_manifest": {"path": "p", "size_bytes": 1, "sha256": "h"},
            "claims": {
                "v1_results_imported": False,
                "v2_results_imported": False,
                "v3_results_imported": False,
                "v4_results_imported": False,
                "v5_results_imported": False,
                "cross_arm_imu_semantics_exact_before_clock_normalization": True,
                "cross_vins_arm_replay_schedule_exact": True,
                "dataset_canonical_td_shared_across_windows": True,
                "available_imu_samples_and_camera_cutoff_matched": True,
                "identical_native_backend_imu_consumption_claimed": False,
            },
            "execution_controls": {},
            "control_documents": {
                "runtime_exclusivity_addendum": {},
                "v1_runtime_contamination_report": {},
                "v2_lifecycle_false_positive_contamination_report": {},
                "control_supersession": {},
                "v3_outer_batch_timeout_abandonment_report": {},
                "v4_ros_python_environment_abandonment_report": {},
                "v5_watchdog_exit_race_abandonment_report": {},
                "shutdown_addendum": {},
            },
            "stack": {},
            "runtime_seed": {},
            "planned_schedule": {},
            "cases": {},
        }
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = root / "experiment_manifest.json"
            with mock.patch.object(VINS, "EXPERIMENT_ROOT", root), mock.patch.object(
                VINS, "CASE_ORDER", []
            ), mock.patch.object(
                VINS, "require_identity"
            ), mock.patch.object(
                VINS, "read_csv_rows", side_effect=[roster, historical] * 8
            ), mock.patch.object(
                VINS, "load_schedule", return_value=[{}] * 120
            ), mock.patch.object(
                VINS, "identity", return_value={"path": "p", "size_bytes": 1, "sha256": "h"}
            ), mock.patch.object(VINS, "identity_matches", return_value=True):
                path.write_text(json.dumps(manifest), encoding="utf-8")
                VINS.verify_common_inputs()
                for key in (
                    "v1_results_imported",
                    "v2_results_imported",
                    "v3_results_imported",
                    "v4_results_imported",
                    "v5_results_imported",
                ):
                    invalid = json.loads(json.dumps(manifest))
                    invalid["claims"][key] = True
                    path.write_text(json.dumps(invalid), encoding="utf-8")
                    with self.subTest(key=key), self.assertRaises(VINS.ContractError):
                        VINS.verify_common_inputs()

    def test_runner_summaries_delegate_to_receipt_state_machine(self) -> None:
        sentinel = {"schema_version": "receipt-validated-sentinel"}
        with mock.patch(
            "summarize_fair_stability_v6.summarize", return_value=sentinel
        ) as summarize:
            self.assertIs(HFNET.summary(), sentinel)
            self.assertIs(VINS.summary(), sentinel)
        self.assertEqual(summarize.call_count, 2)

    def test_vins_timeout_and_empty_output_remain_algorithm_outcomes(self) -> None:
        tag = "attempt-tag"
        start = {"valid": True, "values": {"tag": tag}}
        empty_output = {
            "valid": False,
            "errors": ["VALUE_MISMATCH:output_nonempty:0:1"],
            "values": {
                "tag": tag,
                "output_nonempty": "0",
                "vins_early_exit": "0",
                "rosbag_returncode": "0",
            },
        }
        pipeline, algorithm = VINS.classify_child_lifecycle(
            start, empty_output, tag, False
        )
        self.assertEqual(pipeline, [])
        self.assertEqual(algorithm, [])

        timeout_lifecycle = {"valid": False, "errors": ["FILE_MISSING"], "values": {}}
        pipeline, algorithm = VINS.classify_child_lifecycle(
            start, timeout_lifecycle, tag, True
        )
        self.assertEqual(pipeline, [])
        self.assertEqual(algorithm, [])
        pipeline, _ = VINS.classify_child_lifecycle(
            start, timeout_lifecycle, tag, False
        )
        self.assertIn("SUPERVISED_SHUTDOWN_CONTRACT_UNPROVEN", pipeline)
        early_exit_with_residual = {
            "valid": False,
            "errors": [
                "VALUE_MISMATCH:vins_early_exit:1:0",
                "VALUE_MISMATCH:descendant_residual_count:1:0",
            ],
            "values": {
                "tag": tag,
                "vins_early_exit": "1",
                "rosbag_returncode": "0",
                "output_nonempty": "0",
            },
        }
        pipeline, algorithm = VINS.classify_child_lifecycle(
            start, early_exit_with_residual, tag, False
        )
        self.assertIn("ESTIMATOR_EXITED_BEFORE_BAG_END", algorithm)
        self.assertIn("SUPERVISED_SHUTDOWN_CONTRACT_UNPROVEN", pipeline)

    def test_common_rejects_inconsistent_result_contracts(self) -> None:
        success = {
            "status": "SUCCESS",
            "clean_success": True,
            "failure_codes": [],
            "pipeline_failure_codes": [],
            "algorithm_failure_codes": [],
            "execution": {"postprocess_signals_deferred": []},
        }
        self.assertTrue(ORDINAL.result_contract_valid(success))
        contaminated_success = dict(success)
        contaminated_success.update(
            {
                "failure_codes": ["MIDRUN_EXTERNAL_RESOURCE_INTRUSION"],
                "pipeline_failure_codes": ["MIDRUN_EXTERNAL_RESOURCE_INTRUSION"],
            }
        )
        self.assertFalse(ORDINAL.result_contract_valid(contaminated_success))
        impossible_clean_failure = {
            "status": "ALGORITHM_FAILURE",
            "clean_success": True,
            "failure_codes": ["ESTIMATOR_OR_REPLAY_TIMEOUT"],
            "pipeline_failure_codes": [],
            "algorithm_failure_codes": ["ESTIMATOR_OR_REPLAY_TIMEOUT"],
        }
        self.assertFalse(ORDINAL.result_contract_valid(impossible_clean_failure))
        mismatched_failure_list = dict(impossible_clean_failure)
        mismatched_failure_list["clean_success"] = False
        mismatched_failure_list["failure_codes"] = []
        self.assertFalse(ORDINAL.result_contract_valid(mismatched_failure_list))
        cell = {
            "case_id": "a05_3300_3700",
            "arm": "learned_klt_vins",
            "repeat": 1,
        }
        self.assertFalse(
            ORDINAL._coordinate_matches(
                {"case_id": cell["case_id"], "arm": cell["arm"], "repeat": 1},
                cell,
                1,
            )
        )

    def test_postprocess_signals_remain_fail_stop_through_result_publication(self) -> None:
        success = {
            "status": "SUCCESS",
            "clean_success": True,
            "failure_codes": [],
            "pipeline_failure_codes": [],
            "algorithm_failure_codes": [],
            "execution": {"postprocess_signals_deferred": []},
        }
        tampered = json.loads(json.dumps(success))
        tampered["execution"]["postprocess_signals_deferred"] = [15]
        self.assertTrue(ORDINAL.result_contract_valid(success))
        self.assertFalse(ORDINAL.result_contract_valid(tampered))
        for path in (
            SCRIPTS / "run_fair_stability_hfnet_openloop_v6.py",
            SCRIPTS / "run_fair_stability_vins_replay_v6.py",
        ):
            source = path.read_text(encoding="utf-8")
            with self.subTest(path=path.name):
                self.assertNotIn("def defer_postprocess_signal", source)
                install = source.rfind(
                    "signal.signal(value, raise_supervisor_interrupt)"
                )
                publish = source.rfind(
                    'write_exclusive(root / "run_result.json", canonical_json(result))'
                )
                restore = source.rfind("signal.signal(value, handler)")
                self.assertGreater(install, 0)
                self.assertGreater(publish, install)
                self.assertGreater(restore, publish)

    def test_result_published_then_runner_signal_is_controller_fail_stop(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            attempt = base / "attempt"
            attempt.mkdir()
            matrix = base / "attempt_matrix_freeze_v6.json"
            matrix.write_text("{}\n", encoding="ascii")
            dispatch_claim = attempt / "ordinal_dispatch_claim.json"
            dispatch_claim.write_text("{}\n", encoding="ascii")
            state = {
                "state": "READY",
                "attempt_root": str(attempt),
                "attempt_index": 1,
                "cell": {
                    "ordinal": 1,
                    "case_id": "a05_3300_3700",
                    "arm": "learned_klt_vins",
                    "repeat": 1,
                },
            }

            def fake_run(
                argv: list[str], environment: dict[str, str] | None = None
            ) -> subprocess.CompletedProcess[str]:
                del environment
                if argv[2] == "check":
                    return subprocess.CompletedProcess(
                        argv,
                        0,
                        json.dumps(
                            {
                                "ready": True,
                                "resource_gate": {
                                    "schema_version": (
                                        "aqua-fe-fair-stability-"
                                        "prestart-resource-gate-v6"
                                    ),
                                    "experiment_id": ORDINAL.EXPERIMENT_ID,
                                    "ready": True,
                                },
                            }
                        ),
                        "",
                    )
                self.assertEqual(argv[2], "run")
                (attempt / "start_claim.json").write_text(
                    "{}\n", encoding="ascii"
                )
                (attempt / "run_result.json").write_bytes(
                    ORDINAL.canonical_json(
                        {
                            "schema_version": "aqua-fe-fair-stability-vins-result-v6",
                            "experiment_id": ORDINAL.EXPERIMENT_ID,
                            "case_id": "a05_3300_3700",
                            "arm": "learned_klt_vins",
                            "repeat": 1,
                            "attempt_index": 1,
                            "status": "SUCCESS",
                            "clean_success": True,
                            "failure_codes": [],
                            "pipeline_failure_codes": [],
                            "algorithm_failure_codes": [],
                            "execution": {"postprocess_signals_deferred": []},
                        }
                    )
                )
                # Models SIGTERM after exclusive result publication but before
                # the runner has completed its process exit.
                return subprocess.CompletedProcess(argv, -15, "", "SIGTERM")

            with mock.patch.object(
                NEXT, "MATRIX_FREEZE", matrix
            ), mock.patch.object(
                NEXT, "run_command", side_effect=fake_run
            ), mock.patch.object(
                NEXT, "dispatch_claim", return_value=({}, "token")
            ), mock.patch.object(
                NEXT, "verify_control_freeze", return_value={}
            ), mock.patch.object(NEXT, "next_state") as next_state_mock:
                outcome = NEXT.dispatch(state)
            self.assertEqual(
                outcome["outcome"],
                "EXPERIMENT_ABANDONMENT_REQUIRED_"
                "RUNNER_RESULT_RETURN_CODE_BINDING_INVALID",
            )
            self.assertEqual(outcome["runner_returncode"], -15)
            self.assertEqual(outcome["expected_runner_returncode"], 0)
            next_state_mock.assert_not_called()
            execution_path = attempt / "controller_dispatch_execution_001.json"
            execution = json.loads(execution_path.read_text(encoding="utf-8"))
            self.assertIs(
                execution["runner_result_returncode_binding_valid"], False
            )
            with self.assertRaisesRegex(
                ORDINAL.OrdinalError,
                "CONTROLLER_DISPATCH_RUNNER_RESULT_EXIT_BINDING_INVALID",
            ):
                ORDINAL.validate_controller_dispatch_execution_for_result(
                    base,
                    attempt,
                    json.loads(
                        (attempt / "run_result.json").read_text(encoding="utf-8")
                    ),
                )
            with mock.patch.object(
                NEXT, "run_next", return_value=outcome
            ), mock.patch("builtins.print"):
                self.assertEqual(NEXT.main(["run-next"]), 5)

    def test_resource_check_stdout_then_signal_cannot_start_estimator(self) -> None:
        state = {
            "state": "READY",
            "attempt_root": "/tmp/never-started-v6",
            "attempt_index": 1,
            "cell": {
                "ordinal": 1,
                "case_id": "a05_3300_3700",
                "arm": "learned_klt_vins",
                "repeat": 1,
            },
        }
        gate = {
            "schema_version": "aqua-fe-fair-stability-prestart-resource-gate-v6",
            "experiment_id": ORDINAL.EXPERIMENT_ID,
            "ready": True,
        }
        signalled_check = subprocess.CompletedProcess(
            ["runner", "check"],
            -15,
            json.dumps({"ready": True, "resource_gate": gate}),
            "SIGTERM",
        )
        with mock.patch.object(
            NEXT, "run_command", return_value=signalled_check
        ) as run, mock.patch.object(NEXT, "dispatch_claim") as claim:
            outcome = NEXT.dispatch(state)
        self.assertEqual(run.call_count, 1)
        claim.assert_not_called()
        self.assertEqual(
            outcome["outcome"],
            "EXPERIMENT_ABANDONMENT_REQUIRED_"
            "RESOURCE_CHECK_RETURN_CODE_BINDING_INVALID",
        )
        self.assertEqual(outcome["runner_returncode"], -15)
        self.assertIs(outcome["runner_ready"], True)
        with mock.patch.object(
            NEXT, "run_next", return_value=outcome
        ), mock.patch("builtins.print"):
            self.assertEqual(NEXT.main(["run-next"]), 5)

    @classmethod
    def scanner_source(cls) -> str:
        source = cls.CHILD.read_text(encoding="utf-8")
        match = re.search(
            r"^scan_group_residuals\(\) \{\n.*?^\}\n",
            source,
            flags=re.MULTILINE | re.DOTALL,
        )
        if not match:
            raise AssertionError("scan_group_residuals function not found")
        return match.group(0)

    def test_residual_scanner_is_static_pure_bash_proc_scan(self) -> None:
        scanner = self.scanner_source()
        for forbidden in ("ps -", "awk ", "paste", "$("):
            self.assertNotIn(forbidden, scanner)
        self.assertIn("for proc_path in /proc/[0-9]*", scanner)
        self.assertIn('DESCENDANT_RESIDUALS=""', scanner)
        self.assertIn("DESCENDANT_RESIDUAL_COUNT=0", scanner)
        child = self.CHILD.read_text(encoding="utf-8")
        self.assertNotIn('$(group_residuals)', child)

    def test_resource_monitor_catches_compiler_driver_variants(self) -> None:
        for name in (
            "cc",
            "c++",
            "nvcc",
            "x86_64-linux-gnu-g++",
            "x86_64-linux-gnu-gcc-12",
            "aarch64-linux-gnu-clang++-17",
        ):
            with self.subTest(name=name):
                record = {
                    "comm": name,
                    "executable": f"/usr/bin/{name}",
                    "cmdline": [f"/usr/bin/{name}", "source.cc"],
                    "command": f"/usr/bin/{name} source.cc",
                }
                self.assertTrue(RESOURCE._is_forbidden_process(record))

    def test_resource_monitor_catches_both_frontend_exporter_forms(self) -> None:
        commands = (
            ["/usr/bin/python3", "-m", "uw_frontend.ros.export_vins_features"],
            [
                "/usr/bin/python3",
                "/home/ma/AQUA-FE_WS/uw_frontend/ros/export_vins_features.py",
            ],
        )
        for command in commands:
            with self.subTest(command=command):
                record = {
                    "comm": "python3",
                    "executable": "/usr/bin/python3",
                    "cmdline": command,
                    "command": " ".join(command),
                }
                self.assertTrue(RESOURCE._is_forbidden_process(record))
        benign = {
            "comm": "python3",
            "executable": "/usr/bin/python3",
            "cmdline": ["/usr/bin/python3", "analysis.py"],
            "command": "/usr/bin/python3 analysis.py",
        }
        self.assertFalse(RESOURCE._is_forbidden_process(benign))

    def run_scanner_harness(self, body: str) -> subprocess.CompletedProcess[str]:
        script = (
            "set -euo pipefail\n"
            + self.scanner_source()
            + '\nWRAPPER_PID="$$"\nWRAPPER_PGID="$$"\n'
            + body
        )
        return subprocess.run(
            ["/usr/bin/bash", "-c", script],
            check=False,
            capture_output=True,
            text=True,
            start_new_session=True,
            timeout=10,
        )

    def test_residual_scanner_does_not_observe_itself(self) -> None:
        result = self.run_scanner_harness(
            "scan_group_residuals\n"
            "printf '%s|%s\\n' \"$DESCENDANT_RESIDUAL_COUNT\" \"$DESCENDANT_RESIDUALS\"\n"
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "0|\n")

    def test_residual_scanner_observes_one_real_group_child(self) -> None:
        result = self.run_scanner_harness(
            "/bin/sleep 5 &\nchild=$!\n"
            "scan_group_residuals\n"
            "printf '%s|%s|%s\\n' \"$DESCENDANT_RESIDUAL_COUNT\" \"$DESCENDANT_RESIDUALS\" \"$child\"\n"
            "kill \"$child\"\nwait \"$child\" 2>/dev/null || true\n"
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        count, residuals, child = result.stdout.strip().split("|")
        self.assertEqual(count, "1")
        self.assertRegex(residuals, rf"^{re.escape(child)}:[A-Z]$")

    def test_retry_allowlist_persistent_repeat_and_limit_halt(self) -> None:
        allowed = "MIDRUN_EXTERNAL_RESOURCE_INTRUSION"
        first = {
            "attempt_index": 1,
            "result": {"pipeline_failure_codes": [allowed]},
            "invalid_chain": [],
        }
        self.assertEqual(NEXT.automatic_retry_codes(first), [allowed])
        for codes in (
            ["SUPERVISED_SHUTDOWN_CONTRACT_UNPROVEN"],
            ["RUNTIME_RESOURCE_MONITOR_UNPROVEN"],
            [allowed, "ONNX_MODEL_DRIFT"],
        ):
            with self.subTest(codes=codes), self.assertRaises(NEXT.ControllerError):
                NEXT.automatic_retry_codes(
                    {"attempt_index": 1, "result": {"pipeline_failure_codes": codes}, "invalid_chain": []}
                )
        with self.assertRaisesRegex(NEXT.ControllerError, "REPEATED_PIPELINE"):
            NEXT.automatic_retry_codes(
                {
                    "attempt_index": 2,
                    "result": {"pipeline_failure_codes": [allowed]},
                    "invalid_chain": [{"pipeline_failure_codes": [allowed]}],
                }
            )
        with self.assertRaisesRegex(NEXT.ControllerError, "REPLACEMENT_LIMIT"):
            NEXT.automatic_retry_codes(
                {"attempt_index": 3, "result": {"pipeline_failure_codes": [allowed]}, "invalid_chain": []}
            )

    def test_adjudication_allowed_path_has_bound_result(self) -> None:
        allowed = "MIDRUN_EXTERNAL_RESOURCE_INTRUSION"
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "run_result.json").write_text("{}\n", encoding="ascii")
            state = {
                "state": "PIPELINE_INVALID_UNADJUDICATED",
                "attempt_root": str(root),
                "attempt_index": 1,
                "cell": {"ordinal": 1, "case_id": "c", "arm": "a", "repeat": 1},
                "result": {
                    "pipeline_failure_codes": [allowed],
                    "algorithm_failure_codes": [],
                },
                "invalid_chain": [],
            }
            with mock.patch.object(NEXT, "verify_control_freeze", return_value={}), mock.patch.object(
                NEXT, "identity", side_effect=lambda path: {"path": str(path)}
            ), mock.patch.object(
                NEXT,
                "systemd_adoption_identity_for_attempt",
                return_value={"path": "/frozen/systemd_adoption_receipt.json"},
            ), mock.patch.object(NEXT, "write_exclusive") as write:
                receipt = NEXT.adjudicate_pipeline_invalid(state)
            self.assertEqual(receipt["pipeline_failure_codes"], [allowed])
            self.assertEqual(receipt["automatic_retry_policy"], "EXPLICIT_EXTERNAL_TRANSIENT_ONLY_V6")
            write.assert_called_once()

    def test_attempt_limit_and_port_failure_leave_no_directory(self) -> None:
        cell = {"case_id": "a05_3300_3700", "arm": "learned_klt_vins", "repeat": 1}
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with self.assertRaises(ORDINAL.OrdinalError):
                ORDINAL.attempt_root(root, cell, 4)
            with mock.patch.object(VINS, "VINS_ROOT", root / "vins"):
                with self.assertRaises(VINS.ContractError):
                    VINS.attempt_root(cell["case_id"], cell["arm"], 1, 4)
                expected = VINS.attempt_root(cell["case_id"], cell["arm"], 1, 1)
                with mock.patch.object(VINS, "load_freeze", return_value={}), mock.patch.object(
                    VINS, "port_for", side_effect=VINS.ContractError("ATTEMPT_PORT_EXHAUSTED")
                ):
                    with self.assertRaisesRegex(VINS.ContractError, "ATTEMPT_PORT_EXHAUSTED"):
                        VINS.prepare_attempt(cell["case_id"], cell["arm"], 1, 1)
                self.assertFalse(expected.exists())
            with mock.patch.object(HFNET, "EXPERIMENT_ROOT", root / "hfnet"):
                with self.assertRaises(HFNET.ContractError):
                    HFNET.attempt_root(cell["case_id"], 675, 1, 4)

    def test_replenishment_cannot_precede_invalid_adjudication(self) -> None:
        cell = {
            "ordinal": 1,
            "case_id": "a05_3300_3700",
            "arm": "learned_klt_vins",
            "repeat": 1,
        }
        with tempfile.TemporaryDirectory() as temporary:
            experiment_root = Path(temporary)
            first = ORDINAL.attempt_root(experiment_root, cell, 1)
            later = ORDINAL.attempt_root(experiment_root, cell, 2)
            first.mkdir(parents=True)
            (first / "attempt_manifest.json").write_text(
                json.dumps(
                    {
                        "schema_version": "aqua-fe-fair-stability-vins-attempt-v6",
                        "experiment_id": ORDINAL.EXPERIMENT_ID,
                        "case_id": cell["case_id"],
                        "arm": cell["arm"],
                        "repeat": 1,
                        "attempt_index": 1,
                    }
                ),
                encoding="utf-8",
            )
            (first / "start_claim.json").write_text("{}\n", encoding="ascii")
            pipeline_code = "MIDRUN_EXTERNAL_RESOURCE_INTRUSION"
            (first / "run_result.json").write_text(
                json.dumps(
                    {
                        "schema_version": "aqua-fe-fair-stability-vins-result-v6",
                        "experiment_id": ORDINAL.EXPERIMENT_ID,
                        "case_id": cell["case_id"],
                        "arm": cell["arm"],
                        "repeat": 1,
                        "attempt_index": 1,
                        "status": "PIPELINE_INVALID",
                        "clean_success": False,
                        "failure_codes": [pipeline_code],
                        "pipeline_failure_codes": [pipeline_code],
                        "algorithm_failure_codes": [],
                        "execution": {"postprocess_signals_deferred": []},
                    }
                ),
                encoding="utf-8",
            )
            dispatch_claim_path = first / "ordinal_dispatch_claim.json"
            dispatch_claim_path.write_text("{}\n", encoding="ascii")
            execution_path = first / "controller_dispatch_execution_001.json"
            execution_path.write_bytes(
                ORDINAL.canonical_json(
                    {
                        "schema_version": ORDINAL.CONTROLLER_DISPATCH_EXECUTION_SCHEMA,
                        "experiment_id": ORDINAL.EXPERIMENT_ID,
                        "dispatch_index": 1,
                        "returncode": 3,
                        "dispatch_claim": ORDINAL.identity(dispatch_claim_path),
                        "controller": ORDINAL.identity(
                            SCRIPTS / "run_fair_stability_next_v6.py"
                        ),
                        "run_result": ORDINAL.identity(first / "run_result.json"),
                        "run_result_status": "PIPELINE_INVALID",
                        "expected_runner_returncode_from_result_status": 3,
                        "runner_result_returncode_binding_valid": True,
                        "run_result_parse_error": None,
                    }
                )
            )
            later.mkdir()
            with self.assertRaisesRegex(
                ORDINAL.OrdinalError,
                "REPLENISHMENT_BEFORE_PIPELINE_INVALID_ADJUDICATION",
            ):
                ORDINAL.inspect_cell(experiment_root, cell)

        for pipeline_code in (
            "MIDRUN_EXTERNAL_RESOURCE_INTRUSION",
            "SUPERVISED_SHUTDOWN_CONTRACT_UNPROVEN",
        ):
            unadjudicated = {
                "state": "PIPELINE_INVALID_UNADJUDICATED",
                "cell": dict(cell),
                "attempt_index": 1,
                "result": {"pipeline_failure_codes": [pipeline_code]},
            }
            with self.subTest(runner="vins", pipeline_code=pipeline_code), tempfile.TemporaryDirectory() as temporary:
                vins_root = Path(temporary) / "vins"
                expected = vins_root / "attempts" / cell["case_id"] / cell["arm"] / "repeat_001__replenishment_002"
                with mock.patch.object(VINS, "VINS_ROOT", vins_root), mock.patch.object(
                    VINS, "load_freeze", return_value={}
                ), mock.patch.object(
                    VINS, "ordinal_next_state", return_value=unadjudicated
                ):
                    with self.assertRaisesRegex(
                        VINS.ContractError,
                        "REPLENISHMENT_NOT_AUTHORIZED_BY_ORDINAL_STATE",
                    ):
                        VINS.prepare_attempt(cell["case_id"], cell["arm"], 1, 2)
                self.assertFalse(expected.exists())

            with self.subTest(runner="hfnet", pipeline_code=pipeline_code), tempfile.TemporaryDirectory() as temporary:
                hfnet_root = Path(temporary) / "experiment"
                expected = hfnet_root / "hfnet_openloop_675" / cell["case_id"] / "repeat_001__replenishment_002"
                hfnet_state = dict(unadjudicated)
                hfnet_state["cell"] = dict(cell, arm="hfnet_openloop_675")
                with mock.patch.object(HFNET, "EXPERIMENT_ROOT", hfnet_root), mock.patch.object(
                    HFNET,
                    "load_experiment",
                    return_value={"cases": {cell["case_id"]: {}}},
                ), mock.patch.object(
                    HFNET, "backend_freeze_identity", return_value={}
                ), mock.patch.object(
                    HFNET, "ordinal_next_state", return_value=hfnet_state
                ):
                    with self.assertRaisesRegex(
                        HFNET.ContractError,
                        "REPLENISHMENT_NOT_AUTHORIZED_BY_ORDINAL_STATE",
                    ):
                        HFNET.prepare_attempt(cell["case_id"], 675, 1, 2)
                self.assertFalse(expected.exists())


class SystemdControlTests(unittest.TestCase):
    INVOCATION = "1" * 32

    def build_chain(
        self,
        experiment_root: Path,
        claim_environment: dict[str, str] | None = None,
        start_environment: dict[str, str] | None = None,
        submission_index: int = 1,
        ordinal_state_before_submit: dict[str, object] | None = None,
    ) -> tuple[Path, dict[str, dict[str, object]]]:
        attempt_root = experiment_root / "attempt"
        directory = (
            experiment_root
            / "systemd_supervision"
            / "ordinal_001"
            / f"submission_{submission_index:03d}"
        )
        directory.mkdir(parents=True)
        unit = (
            "aqua-fe-fair-stability-v6-o001-a001-"
            f"s{submission_index:03d}-aabbcc.service"
        )
        claim = {
            "schema_version": SYSTEMD.SUBMISSION_SCHEMA,
            "experiment_id": ORDINAL.EXPERIMENT_ID,
            "unit": unit,
            "planned_ordinal": 1,
            "attempt_index": 1,
            "attempt_root": str(attempt_root),
            "submission_directory": str(directory),
            "ordinal_state_before_submit": (
                {
                    "state": "READY",
                    "attempt_root": str(attempt_root),
                    "attempt_index": 1,
                }
                if ordinal_state_before_submit is None
                else ordinal_state_before_submit
            ),
            "systemd_run_argv": SYSTEMD.systemd_run_argv(unit, directory),
            "systemd_contract": {
                "minimum_fixed_environment": (
                    dict(ORDINAL.FIXED_SERVICE_ENVIRONMENT)
                    if claim_environment is None
                    else claim_environment
                )
            },
        }
        claim_path = directory / "submission_claim.json"
        claim_path.write_bytes(ORDINAL.canonical_json(claim))
        submit = {
            "schema_version": SYSTEMD.SUBMIT_RECEIPT_SCHEMA,
            "experiment_id": ORDINAL.EXPERIMENT_ID,
            "unit": unit,
            "accepted": True,
            "submission_claim": ORDINAL.identity(claim_path),
        }
        submit_path = directory / "submission_receipt.json"
        submit_path.write_bytes(ORDINAL.canonical_json(submit))
        start = {
            "schema_version": SYSTEMD.START_RECEIPT_SCHEMA,
            "experiment_id": ORDINAL.EXPERIMENT_ID,
            "unit": unit,
            "invocation_id": self.INVOCATION,
            "submission_claim": ORDINAL.identity(claim_path),
            "submission_receipt": ORDINAL.identity(submit_path),
            "fixed_service_environment": (
                dict(ORDINAL.FIXED_SERVICE_ENVIRONMENT)
                if start_environment is None
                else start_environment
            ),
        }
        start_path = directory / "systemd_start_receipt.json"
        start_path.write_bytes(ORDINAL.canonical_json(start))
        execution = {
            "schema_version": SYSTEMD.EXECUTION_SCHEMA,
            "experiment_id": ORDINAL.EXPERIMENT_ID,
            "unit": unit,
            "invocation_id": self.INVOCATION,
            "systemd_start_receipt": ORDINAL.identity(start_path),
            "controller_returncode": 0,
            "controller_result": {
                "outcome": "TERMINAL_RESULT_PENDING_SYSTEMD_ADOPTION",
                "systemd_authority": {
                    "path": str(start_path),
                    "identity": ORDINAL.identity(start_path),
                    "receipt": start,
                },
            },
        }
        execution_path = directory / "systemd_execution_receipt.json"
        execution_path.write_bytes(ORDINAL.canonical_json(execution))
        terminal = {
            "schema_version": SYSTEMD.TERMINAL_SCHEMA,
            "experiment_id": ORDINAL.EXPERIMENT_ID,
            "unit": unit,
            "invocation_id_environment": self.INVOCATION,
            "service_result_environment": "success",
            "exit_code_environment": "exited",
            "exit_status_environment": "0",
            "observed_tuple": {
                "Result": "success",
                "ExecMainCode": "1",
                "ExecMainStatus": "0",
            },
            "submission_claim": ORDINAL.identity(claim_path),
            "submission_receipt": ORDINAL.identity(submit_path),
            "systemd_start_receipt": ORDINAL.identity(start_path),
            "systemd_execution_receipt": ORDINAL.identity(execution_path),
        }
        terminal_path = directory / "systemd_terminal_receipt.json"
        terminal_path.write_bytes(ORDINAL.canonical_json(terminal))
        records = {
            "submission_claim": ORDINAL.identity(claim_path),
            "submission_receipt": ORDINAL.identity(submit_path),
            "systemd_start_receipt": ORDINAL.identity(start_path),
            "systemd_execution_receipt": ORDINAL.identity(execution_path),
            "systemd_terminal_receipt": ORDINAL.identity(terminal_path),
        }
        return directory, records

    def finalize_chain(
        self,
        experiment_root: Path,
        directory: Path,
        records: dict[str, object],
        controller_outcome: str = "TERMINAL_RESULT_PENDING_SYSTEMD_ADOPTION",
    ) -> None:
        claim = json.loads(
            (directory / "submission_claim.json").read_text(encoding="utf-8")
        )
        adoption_claim = {
            "schema_version": SYSTEMD.ADOPTION_CLAIM_SCHEMA,
            "experiment_id": ORDINAL.EXPERIMENT_ID,
            "unit": claim["unit"],
            "controller_returncode": 0,
            "controller_outcome": controller_outcome,
            **records,
        }
        adoption_claim_path = directory / "systemd_adoption_claim.json"
        adoption_claim_path.write_bytes(ORDINAL.canonical_json(adoption_claim))
        final = {
            "schema_version": SYSTEMD.ADOPTION_SCHEMA,
            "experiment_id": ORDINAL.EXPERIMENT_ID,
            "unit": claim["unit"],
            "controller_returncode": 0,
            "controller_outcome": controller_outcome,
            **records,
            "systemd_adoption_claim": ORDINAL.identity(adoption_claim_path),
            "ordinal_terminal_receipt": None,
        }
        (directory / "systemd_adoption_receipt.json").write_bytes(
            ORDINAL.canonical_json(final)
        )

    def test_systemd_unit_contract_and_submit_only_argv(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            unit = "aqua-fe-fair-stability-v6-o001-a001-s001-aabbcc.service"
            argv = SYSTEMD.systemd_run_argv(unit, directory)
        self.assertIn("--service-type=exec", argv)
        self.assertIn("--property=KillMode=control-group", argv)
        self.assertIn("--property=RuntimeMaxSec=2400s", argv)
        self.assertIn("--property=TimeoutStopSec=120s", argv)
        self.assertIn("--property=RemainAfterExit=no", argv)
        self.assertIn("--property=UMask=0077", argv)
        expected_setenv = [
            f"--setenv={key}={value}"
            for key, value in ORDINAL.FIXED_SERVICE_ENVIRONMENT.items()
        ]
        self.assertEqual(
            [value for value in argv if value.startswith("--setenv=")],
            expected_setenv,
        )
        self.assertIn(
            "--setenv=PYTHONPATH=/opt/ros/noetic/lib/python3/dist-packages",
            argv,
        )
        self.assertFalse(any(value in argv for value in ("--wait", "--collect", "--scope", "--pipe")))
        post = next(value for value in argv if value.startswith("--property=ExecStopPost="))
        self.assertIn(str(SYSTEMD.SUPERVISOR), post)
        self.assertIn("service-post", post)
        verified = SYSTEMD.verify_unit_contract(
            unit,
            {
                "returncode": 0,
                "properties": {
                    "Id": unit,
                    "LoadState": "loaded",
                    "ActiveState": "active",
                    "Type": "exec",
                    "KillMode": "control-group",
                    "SendSIGKILL": "yes",
                    "NRestarts": "0",
                    "Transient": "yes",
                    "RemainAfterExit": "no",
                    "Restart": "no",
                    "UMask": "0077",
                    "RuntimeMaxUSec": "40min",
                    "TimeoutStopUSec": "2min",
                    "KillSignal": "15",
                    "InvocationID": self.INVOCATION,
                    "MainPID": "1234",
                    "ControlGroup": "/user.slice/test.service",
                },
            },
            require_live_main=True,
        )
        self.assertEqual(verified["invocation_id"], self.INVOCATION)

    def test_exact_fixed_environment_imports_rosbag(self) -> None:
        command = subprocess.run(
            [
                str(SYSTEMD.PYTHON),
                "-c",
                (
                    "import pathlib, rosbag, site; "
                    "assert site.ENABLE_USER_SITE is False; "
                    "print(pathlib.Path(rosbag.__file__).resolve())"
                ),
            ],
            cwd=str(ROOT),
            env=dict(ORDINAL.FIXED_SERVICE_ENVIRONMENT),
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertEqual(command.returncode, 0, command.stderr)
        self.assertEqual(
            command.stdout.strip(),
            "/opt/ros/noetic/lib/python3/dist-packages/rosbag/__init__.py",
        )
        for mode in ("missing", "wrong"):
            environment = dict(ORDINAL.FIXED_SERVICE_ENVIRONMENT)
            if mode == "missing":
                del environment["PYTHONPATH"]
            else:
                environment["PYTHONPATH"] = "/nonexistent/aqua-fe-ros-python"
            rejected = subprocess.run(
                [str(SYSTEMD.PYTHON), "-c", "import rosbag"],
                cwd=str(ROOT),
                env=environment,
                check=False,
                capture_output=True,
                text=True,
                timeout=30,
            )
            with self.subTest(mode=mode):
                self.assertNotEqual(rejected.returncode, 0)

    def test_service_entry_rejects_fixed_subset_drift_before_controller(self) -> None:
        valid = SYSTEMD.verify_fixed_service_environment(
            dict(ORDINAL.FIXED_SERVICE_ENVIRONMENT)
        )
        self.assertEqual(valid, ORDINAL.FIXED_SERVICE_ENVIRONMENT)
        for mode in ("missing", "wrong"):
            environment = dict(ORDINAL.FIXED_SERVICE_ENVIRONMENT)
            if mode == "missing":
                del environment["PYTHONPATH"]
            else:
                environment["PYTHONNOUSERSITE"] = "0"
            with self.subTest(mode=mode), mock.patch.object(
                subprocess, "run"
            ) as controller:
                with self.assertRaisesRegex(
                    SYSTEMD.SystemdSupervisorError,
                    "SERVICE_ENTRY_FIXED_ENVIRONMENT_DRIFT",
                ):
                    SYSTEMD.verify_fixed_service_environment(environment)
                controller.assert_not_called()

    def test_exact_fixed_environment_reads_real_feature_and_imu(self) -> None:
        bag = (
            ROOT
            / "logs/aqualoc_archaeo_vins/"
            "external_hybrid_xfeat_every2_jul14frozen3way_"
            "a05_3300_3700_degraded_early_dense_visible_motion_count/features.bag"
        )
        command = subprocess.run(
            [
                str(SYSTEMD.PYTHON),
                "-c",
                (
                    "import rosbag, sys; seen=set(); "
                    "b=rosbag.Bag(sys.argv[1], 'r'); "
                    "[(seen.add(t)) for t,_,_ in b.read_messages(topics=["
                    "'/feature_tracker/feature','/rtimulib_node/imu']) "
                    "if len(seen)<2]; b.close(); "
                    "assert seen == {'/feature_tracker/feature','/rtimulib_node/imu'}; "
                    "print('feature+imu')"
                ),
                str(bag),
            ],
            cwd=str(ROOT),
            env=dict(ORDINAL.FIXED_SERVICE_ENVIRONMENT),
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertEqual(command.returncode, 0, command.stderr)
        self.assertEqual(command.stdout.strip(), "feature+imu")

    def test_systemd_chain_rejects_fixed_subset_drift(self) -> None:
        for target in ("claim", "start"):
            with tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                drifted = dict(ORDINAL.FIXED_SERVICE_ENVIRONMENT)
                drifted["PYTHONPATH"] = "/wrong/ros/path"
                directory, records = self.build_chain(
                    root,
                    claim_environment=drifted if target == "claim" else None,
                    start_environment=drifted if target == "start" else None,
                )
                with self.subTest(target=target), self.assertRaisesRegex(
                    ORDINAL.OrdinalError,
                    "SYSTEMD_CHAIN_FIXED_ENVIRONMENT_INVALID",
                ):
                    ORDINAL.validate_systemd_chain(root, records, directory)

    def test_complete_chain_is_revalidated_and_tamper_blocks(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            directory, records = self.build_chain(root)
            loaded = ORDINAL.validate_systemd_chain(root, records, directory)
            self.assertEqual(loaded["submission_claim"]["planned_ordinal"], 1)
            (directory / "systemd_execution_receipt.json").write_text(
                (directory / "systemd_execution_receipt.json").read_text(encoding="utf-8")
                + " ",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ORDINAL.OrdinalError, "IDENTITY_DRIFT"):
                ORDINAL.validate_systemd_chain(root, records, directory)

    def test_systemd_chain_revalidates_inner_runner_result_exit_binding(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            directory, _records = self.build_chain(root)
            attempt = root / "attempt"
            attempt.mkdir()
            dispatch_claim_path = attempt / "ordinal_dispatch_claim.json"
            dispatch_claim_path.write_text("{}\n", encoding="ascii")
            result_path = attempt / "run_result.json"
            result_path.write_bytes(
                ORDINAL.canonical_json(
                    {
                        "status": "SUCCESS",
                        "clean_success": True,
                        "failure_codes": [],
                        "pipeline_failure_codes": [],
                        "algorithm_failure_codes": [],
                        "execution": {"postprocess_signals_deferred": []},
                    }
                )
            )
            dispatch_execution_path = (
                attempt / "controller_dispatch_execution_001.json"
            )
            dispatch_execution = {
                "schema_version": ORDINAL.CONTROLLER_DISPATCH_EXECUTION_SCHEMA,
                "experiment_id": ORDINAL.EXPERIMENT_ID,
                "dispatch_index": 1,
                "returncode": 0,
                "dispatch_claim": ORDINAL.identity(dispatch_claim_path),
                "controller": ORDINAL.identity(
                    SCRIPTS / "run_fair_stability_next_v6.py"
                ),
                "run_result": ORDINAL.identity(result_path),
                "run_result_status": "SUCCESS",
                "expected_runner_returncode_from_result_status": 0,
                "runner_result_returncode_binding_valid": True,
                "run_result_parse_error": None,
            }
            dispatch_execution_path.write_bytes(
                ORDINAL.canonical_json(dispatch_execution)
            )

            systemd_execution_path = directory / "systemd_execution_receipt.json"
            systemd_execution = json.loads(
                systemd_execution_path.read_text(encoding="utf-8")
            )
            systemd_execution["controller_result"].update(
                {
                    "outcome": "TERMINAL_RESULT_PENDING_SYSTEMD_ADOPTION",
                    "runner_returncode": 0,
                    "dispatch_execution": ORDINAL.identity(
                        dispatch_execution_path
                    ),
                }
            )
            systemd_execution_path.write_bytes(
                ORDINAL.canonical_json(systemd_execution)
            )
            terminal_path = directory / "systemd_terminal_receipt.json"
            terminal = json.loads(terminal_path.read_text(encoding="utf-8"))
            terminal["systemd_execution_receipt"] = ORDINAL.identity(
                systemd_execution_path
            )
            terminal_path.write_bytes(ORDINAL.canonical_json(terminal))
            records = {
                "submission_claim": ORDINAL.identity(
                    directory / "submission_claim.json"
                ),
                "submission_receipt": ORDINAL.identity(
                    directory / "submission_receipt.json"
                ),
                "systemd_start_receipt": ORDINAL.identity(
                    directory / "systemd_start_receipt.json"
                ),
                "systemd_execution_receipt": ORDINAL.identity(
                    systemd_execution_path
                ),
                "systemd_terminal_receipt": ORDINAL.identity(terminal_path),
            }
            ORDINAL.validate_systemd_chain(root, records, directory)

            dispatch_execution["returncode"] = -15
            dispatch_execution["runner_result_returncode_binding_valid"] = False
            dispatch_execution_path.write_bytes(
                ORDINAL.canonical_json(dispatch_execution)
            )
            with self.assertRaisesRegex(
                ORDINAL.OrdinalError,
                "CONTROLLER_DISPATCH_RUNNER_RESULT_EXIT_BINDING_INVALID",
            ):
                ORDINAL.validate_systemd_chain(root, records, directory)

    def test_pipeline_invalid_second_submission_adjudicates_prior_adoption(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            first_directory, _ = self.build_chain(root, submission_index=1)
            attempt = root / "attempt"
            attempt.mkdir()
            first_start_record = ORDINAL.identity(
                first_directory / "systemd_start_receipt.json"
            )
            (attempt / "start_claim.json").write_bytes(
                ORDINAL.canonical_json(
                    {"systemd_start_receipt": first_start_record}
                )
            )
            dispatch_claim_path = attempt / "ordinal_dispatch_claim.json"
            dispatch_claim_path.write_text("{}\n", encoding="ascii")
            pipeline_code = "MIDRUN_EXTERNAL_RESOURCE_INTRUSION"
            result = {
                "status": "PIPELINE_INVALID",
                "clean_success": False,
                "failure_codes": [pipeline_code],
                "pipeline_failure_codes": [pipeline_code],
                "algorithm_failure_codes": [],
                "execution": {"postprocess_signals_deferred": []},
            }
            result_path = attempt / "run_result.json"
            result_path.write_bytes(ORDINAL.canonical_json(result))
            dispatch_execution_path = (
                attempt / "controller_dispatch_execution_001.json"
            )
            dispatch_execution_path.write_bytes(
                ORDINAL.canonical_json(
                    {
                        "schema_version": ORDINAL.CONTROLLER_DISPATCH_EXECUTION_SCHEMA,
                        "experiment_id": ORDINAL.EXPERIMENT_ID,
                        "dispatch_index": 1,
                        "returncode": 3,
                        "dispatch_claim": ORDINAL.identity(dispatch_claim_path),
                        "controller": ORDINAL.identity(
                            SCRIPTS / "run_fair_stability_next_v6.py"
                        ),
                        "run_result": ORDINAL.identity(result_path),
                        "run_result_status": "PIPELINE_INVALID",
                        "expected_runner_returncode_from_result_status": 3,
                        "runner_result_returncode_binding_valid": True,
                        "run_result_parse_error": None,
                    }
                )
            )

            first_execution_path = (
                first_directory / "systemd_execution_receipt.json"
            )
            first_execution = json.loads(
                first_execution_path.read_text(encoding="utf-8")
            )
            first_execution["controller_result"].update(
                {
                    "outcome": "PIPELINE_INVALID_REQUIRES_ADJUDICATION",
                    "runner_returncode": 3,
                    "dispatch_execution": ORDINAL.identity(
                        dispatch_execution_path
                    ),
                }
            )
            first_execution_path.write_bytes(
                ORDINAL.canonical_json(first_execution)
            )
            first_terminal_path = (
                first_directory / "systemd_terminal_receipt.json"
            )
            first_terminal = json.loads(
                first_terminal_path.read_text(encoding="utf-8")
            )
            first_terminal["systemd_execution_receipt"] = ORDINAL.identity(
                first_execution_path
            )
            first_terminal_path.write_bytes(
                ORDINAL.canonical_json(first_terminal)
            )
            first_records = {
                "submission_claim": ORDINAL.identity(
                    first_directory / "submission_claim.json"
                ),
                "submission_receipt": ORDINAL.identity(
                    first_directory / "submission_receipt.json"
                ),
                "systemd_start_receipt": first_start_record,
                "systemd_execution_receipt": ORDINAL.identity(
                    first_execution_path
                ),
                "systemd_terminal_receipt": ORDINAL.identity(
                    first_terminal_path
                ),
            }
            ORDINAL.validate_systemd_chain(
                root, first_records, first_directory
            )
            self.finalize_chain(
                root,
                first_directory,
                first_records,
                "PIPELINE_INVALID_REQUIRES_ADJUDICATION",
            )
            prior_adoption_path = (
                first_directory / "systemd_adoption_receipt.json"
            )

            pre_state = {
                "state": "PIPELINE_INVALID_UNADJUDICATED",
                "attempt_root": str(attempt),
                "attempt_index": 1,
                "result": result,
            }
            second_directory, _ = self.build_chain(
                root,
                submission_index=2,
                ordinal_state_before_submit=pre_state,
            )
            invalid_receipt = {
                "schema_version": (
                    "aqua-fe-fair-stability-pipeline-invalid-adjudication-v6"
                ),
                "experiment_id": ORDINAL.EXPERIMENT_ID,
                "accepted_as_external_pipeline_fault": True,
                "run_result": ORDINAL.identity(result_path),
                "systemd_adoption_receipt": ORDINAL.identity(
                    prior_adoption_path
                ),
            }
            (attempt / "pipeline_invalid_receipt.json").write_bytes(
                ORDINAL.canonical_json(invalid_receipt)
            )
            next_state = {
                "state": "READY",
                "attempt_root": str(root / "attempt_2"),
                "attempt_index": 2,
            }
            second_execution_path = (
                second_directory / "systemd_execution_receipt.json"
            )
            second_execution = json.loads(
                second_execution_path.read_text(encoding="utf-8")
            )
            second_execution["controller_result"].update(
                {
                    "outcome": (
                        "PIPELINE_INVALID_ADJUDICATED_REPLENISHMENT_PREPARED"
                    ),
                    "invalid_receipt": invalid_receipt,
                    "next": next_state,
                }
            )
            second_execution["ordinal_state_after_controller"] = next_state
            second_execution_path.write_bytes(
                ORDINAL.canonical_json(second_execution)
            )
            second_terminal_path = (
                second_directory / "systemd_terminal_receipt.json"
            )
            second_terminal = json.loads(
                second_terminal_path.read_text(encoding="utf-8")
            )
            second_terminal["systemd_execution_receipt"] = ORDINAL.identity(
                second_execution_path
            )
            second_terminal_path.write_bytes(
                ORDINAL.canonical_json(second_terminal)
            )
            second_records = {
                "submission_claim": ORDINAL.identity(
                    second_directory / "submission_claim.json"
                ),
                "submission_receipt": ORDINAL.identity(
                    second_directory / "submission_receipt.json"
                ),
                "systemd_start_receipt": ORDINAL.identity(
                    second_directory / "systemd_start_receipt.json"
                ),
                "systemd_execution_receipt": ORDINAL.identity(
                    second_execution_path
                ),
                "systemd_terminal_receipt": ORDINAL.identity(
                    second_terminal_path
                ),
            }
            ORDINAL.validate_systemd_chain(
                root, second_records, second_directory
            )

            prior_adoption_path.unlink()
            with self.assertRaises(ORDINAL.OrdinalError):
                ORDINAL.validate_systemd_chain(
                    root, second_records, second_directory
                )

    def test_attempt_start_must_bind_the_adopted_systemd_start(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _directory, records = self.build_chain(root)
            attempt = root / "attempt"
            attempt.mkdir()
            start_path = attempt / "start_claim.json"
            start_path.write_text("{}\n", encoding="ascii")
            with self.assertRaisesRegex(
                ORDINAL.OrdinalError, "ATTEMPT_SYSTEMD_START_CHAIN_MISMATCH"
            ):
                ORDINAL.validate_attempt_start_systemd_binding(
                    root, start_path, records["systemd_start_receipt"]
                )
            start_path.write_bytes(
                ORDINAL.canonical_json(
                    {"systemd_start_receipt": records["systemd_start_receipt"]}
                )
            )
            loaded = ORDINAL.validate_attempt_start_systemd_binding(
                root, start_path, records["systemd_start_receipt"]
            )
            self.assertEqual(loaded["invocation_id"], self.INVOCATION)
            wrong = dict(records["systemd_start_receipt"])
            wrong["sha256"] = "0" * 64
            with self.assertRaisesRegex(
                ORDINAL.OrdinalError, "ATTEMPT_SYSTEMD_START_CHAIN_MISMATCH"
            ):
                ORDINAL.validate_attempt_start_systemd_binding(
                    root, start_path, wrong
                )

    def test_final_adoption_and_symlink_receipts_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            directory, records = self.build_chain(root)
            self.finalize_chain(root, directory, records)
            with mock.patch.object(SYSTEMD, "EXPERIMENT_ROOT", root), mock.patch.object(
                SYSTEMD, "SUPERVISION_ROOT", root / "systemd_supervision"
            ):
                accepted = SYSTEMD.validate_final_adoption(directory)
                self.assertEqual(accepted["controller_returncode"], 0)
                (directory / "systemd_terminal_receipt.json").write_text(
                    "{}\n", encoding="utf-8"
                )
                with self.assertRaises(Exception):
                    SYSTEMD.validate_final_adoption(directory)

        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            target = directory / "missing.json"
            (directory / "systemd_adoption_receipt.json").symlink_to(target)
            with self.assertRaisesRegex(
                SYSTEMD.SystemdSupervisorError, "RECEIPT_PATH_INVALID"
            ):
                SYSTEMD.poll_receipts(directory)

    def test_direct_controller_and_symlink_locks_are_rejected(self) -> None:
        with mock.patch.dict(os.environ, {}, clear=True), self.assertRaisesRegex(
            NEXT.ControllerError, "SYSTEMD_TRANSIENT_SERVICE_AUTHORITY_REQUIRED"
        ):
            NEXT.verify_systemd_authority()
        for module, error in (
            (NEXT, NEXT.ControllerError),
            (HFNET, HFNET.ContractError),
            (VINS, VINS.ContractError),
        ):
            with self.subTest(module=module.__name__), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                target = root / "target"
                target.write_text("lock", encoding="ascii")
                lock = root / "lock"
                lock.symlink_to(target)
                with self.assertRaises(error):
                    module.open_regular_lock(lock)

    def test_start_without_systemd_authority_is_explicit_fail_stop(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            attempt = root / "attempt"
            attempt.mkdir()
            start = attempt / "start_claim.json"
            start.write_text("{}\n", encoding="ascii")
            state = ORDINAL.systemd_started_without_result_state(
                root,
                start,
                {"ordinal": 1, "case_id": "c", "arm": "a", "repeat": 1},
                1,
            )
            self.assertEqual(
                state["state"],
                "SYSTEMD_AUTHORITY_UNPROVEN_STARTED_WITHOUT_RESULT",
            )
            self.assertIsNot(state.get("automatic_retry_permitted"), True)


class ZeroKfWatchdogTests(unittest.TestCase):
    @staticmethod
    def signature_lines(trajectory: Path, maps: list[tuple[int, int]]) -> str:
        return "\n".join(
            [
                "tracking output",
                "Shutdown",
                f"Saving trajectory to {trajectory} ...",
                f"There are {len(maps)} maps in the atlas",
                *[f"  Map {map_id} has {keyframes} KFs" for map_id, keyframes in maps],
            ]
        ) + "\n"

    def test_exact_zero_kf_signature_positive_and_negative_cases(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            stdout = root / "stdout.log"
            trajectory = root / "result/trajectory.txt"
            keyframes = root / "result/trajectory_keyframe.txt"
            trajectory.parent.mkdir()
            for maps in ([(0, 0)], [(1, 0), (0, 0)]):
                stdout.write_text(
                    self.signature_lines(trajectory, maps), encoding="utf-8"
                )
                parsed = HFNET.parse_zero_kf_post_shutdown_signature(
                    stdout, trajectory, keyframes
                )
                self.assertTrue(parsed["parser_proven"])
                self.assertTrue(parsed["confirmed"], parsed)

            base = self.signature_lines(trajectory, [(0, 0)])
            other = root / "result/other.txt"
            cases = {
                "missing_shutdown": base.replace("Shutdown\n", ""),
                "shutdown_after_save": base.replace("Shutdown\n", "").replace(
                    "There are 1 maps", "Shutdown\nThere are 1 maps"
                ),
                "other_saving_path": base.replace(str(trajectory), str(other)),
                "saving_suffix": base.replace(
                    f"{trajectory} ...", f"{trajectory} ... extra"
                ),
                "atlas_missing": base.replace("There are 1 maps in the atlas\n", ""),
                "atlas_zero": base.replace("There are 1 maps", "There are 0 maps"),
                "map_missing": base.replace("  Map 0 has 0 KFs\n", ""),
                "map_duplicate": base.replace(
                    "  Map 0 has 0 KFs\n", "  Map 0 has 0 KFs\n  Map 0 has 0 KFs\n"
                ),
                "map_out_of_range": base.replace("Map 0", "Map 1"),
                "map_nonzero": base.replace("has 0 KFs", "has 1 KFs"),
                "partial_map_line": base.rstrip("\n"),
                "end_observed": base
                + f"End of saving trajectory to {trajectory} ...\n",
                "multiple_saving": base
                + f"Saving trajectory to {trajectory} ...\n",
                "multiple_atlas": base + "There are 1 maps in the atlas\n",
                "partial_end": base
                + f"End of saving trajectory to {trajectory} ...",
            }
            for name, text_value in cases.items():
                with self.subTest(name=name):
                    stdout.write_text(text_value, encoding="utf-8")
                    parsed = HFNET.parse_zero_kf_post_shutdown_signature(
                        stdout, trajectory, keyframes
                    )
                    self.assertFalse(parsed["confirmed"], parsed)

            stdout.write_text(base, encoding="utf-8")
            trajectory.write_text("pose\n", encoding="ascii")
            self.assertFalse(
                HFNET.parse_zero_kf_post_shutdown_signature(
                    stdout, trajectory, keyframes
                )["confirmed"]
            )
            trajectory.unlink()
            keyframes.symlink_to(root / "missing")
            self.assertFalse(
                HFNET.parse_zero_kf_post_shutdown_signature(
                    stdout, trajectory, keyframes
                )["confirmed"]
            )

    def test_exact_group_sigterm_is_one_shot_and_never_individual(self) -> None:
        process = mock.Mock()
        process.poll.return_value = None
        monitor = RESOURCE.RuntimeResourceMonitor.__new__(
            RESOURCE.RuntimeResourceMonitor
        )
        monitor.process = process
        monitor.pid = 4242
        monitor.pgid = 4242
        monitor.leader_identity = (4242, 100)
        monitor._watchdog_signal_attempted = False
        monitor._lock = threading.RLock()
        monitor._cleanup_actions = []
        argv = ["/exact/hfnet", "config", "result", "images", "times"]
        leader = {
            "pid": 4242,
            "start_ticks": 100,
            "pgid": 4242,
            "session": 4242,
            "state": "S",
            "ppid": 1,
            "executable": "/exact/hfnet",
            "cmdline": argv,
            "cmdline_sha256": "a",
            "read_errors": [],
        }
        child = {
            "pid": 4243,
            "start_ticks": 101,
            "pgid": 4242,
            "session": 4242,
            "state": "S",
            "ppid": 4242,
            "executable": "/exact/helper",
            "cmdline": ["/exact/helper"],
            "cmdline_sha256": "b",
            "read_errors": [],
        }
        records = [leader, child]
        by_pid = {4242: leader, 4243: child}
        with mock.patch.object(
            RESOURCE, "_scan_processes", return_value=(records, [])
        ), mock.patch.object(
            RESOURCE,
            "_read_process_record",
            side_effect=lambda pid: (dict(by_pid[pid]), []),
        ), mock.patch.object(RESOURCE.os, "killpg") as killpg, mock.patch.object(
            RESOURCE.os, "kill"
        ) as kill_one:
            action = monitor.watchdog_sigterm_exact_group(
                "/exact/hfnet",
                argv,
                deadline_monotonic=100.0,
                sample_started_monotonic=0.0,
                maximum_observation_gap_seconds=0.25,
                monotonic=lambda: 0.0,
            )
            self.assertTrue(action["signal_sent"], action)
            killpg.assert_called_once_with(4242, RESOURCE.signal.SIGTERM)
            kill_one.assert_not_called()
            second = monitor.watchdog_sigterm_exact_group(
                "/exact/hfnet",
                argv,
                deadline_monotonic=100.0,
                sample_started_monotonic=0.0,
                maximum_observation_gap_seconds=0.25,
                monotonic=lambda: 0.0,
            )
            self.assertFalse(second["signal_sent"])
            killpg.assert_called_once()

        bad = dict(leader, session=999)
        with mock.patch.object(
            RESOURCE, "_scan_processes", return_value=([bad], [])
        ), mock.patch.object(
            RESOURCE, "_read_process_record", return_value=(bad, [])
        ):
            snapshot = monitor.watchdog_exact_group_snapshot("/exact/hfnet", argv)
            self.assertFalse(snapshot["proven"])

        deadline_monitor = RESOURCE.RuntimeResourceMonitor.__new__(
            RESOURCE.RuntimeResourceMonitor
        )
        deadline_monitor.process = process
        deadline_monitor.pid = 4242
        deadline_monitor.pgid = 4242
        deadline_monitor.leader_identity = (4242, 100)
        deadline_monitor._watchdog_signal_attempted = False
        deadline_monitor._lock = threading.RLock()
        deadline_monitor._cleanup_actions = []
        deadline_clock = {"value": 9.90}

        def delayed_proof(*_args):
            deadline_clock["value"] += 0.02
            return {
                "proven": True,
                "errors": [],
                "members": [{"pid": 4242, "start_ticks": 100}],
            }

        def delayed_poll():
            deadline_clock["value"] += 0.07
            return None

        with mock.patch.object(
            deadline_monitor,
            "watchdog_exact_group_snapshot",
            side_effect=delayed_proof,
        ), mock.patch.object(
            deadline_monitor.process, "poll", side_effect=delayed_poll
        ), mock.patch.object(RESOURCE.os, "killpg") as deadline_killpg:
            deadline_action = deadline_monitor.watchdog_sigterm_exact_group(
                "/exact/hfnet",
                argv,
                deadline_monotonic=10.0,
                sample_started_monotonic=9.75,
                maximum_observation_gap_seconds=0.25,
                monotonic=lambda: deadline_clock["value"],
            )
        self.assertFalse(deadline_action["signal_sent"], deadline_action)
        self.assertIn(
            "WATCHDOG_DEADLINE_REACHED_BEFORE_SIGNAL",
            deadline_action["errors"],
        )
        deadline_killpg.assert_not_called()

        poll_process = mock.Mock()
        poll_monitor = RESOURCE.RuntimeResourceMonitor.__new__(
            RESOURCE.RuntimeResourceMonitor
        )
        poll_monitor.process = poll_process
        poll_monitor.pid = 4242
        poll_monitor.pgid = 4242
        poll_monitor.leader_identity = (4242, 100)
        poll_monitor._watchdog_signal_attempted = False
        poll_monitor._lock = threading.RLock()
        poll_monitor._cleanup_actions = []
        poll_clock = {"value": 0.0}

        def slow_final_proof(*_args):
            poll_clock["value"] += 0.10
            return {
                "proven": True,
                "errors": [],
                "members": [{"pid": 4242, "start_ticks": 100}],
            }

        def slow_final_poll():
            poll_clock["value"] += 0.10
            return None

        with mock.patch.object(
            poll_monitor,
            "watchdog_exact_group_snapshot",
            side_effect=slow_final_proof,
        ), mock.patch.object(
            poll_process, "poll", side_effect=slow_final_poll
        ), mock.patch.object(RESOURCE.os, "killpg") as poll_killpg:
            poll_action = poll_monitor.watchdog_sigterm_exact_group(
                "/exact/hfnet",
                argv,
                deadline_monotonic=100.0,
                sample_started_monotonic=0.0,
                maximum_observation_gap_seconds=0.25,
                monotonic=lambda: poll_clock["value"],
            )
        self.assertFalse(poll_action["signal_sent"], poll_action)
        self.assertIn(
            "WATCHDOG_POLL_WINDOW_EXCEEDED_BEFORE_SIGNAL",
            poll_action["errors"],
        )
        poll_killpg.assert_not_called()

    def test_exact_group_snapshot_is_observational_and_terminal_shapes_strict(
        self,
    ) -> None:
        process = mock.Mock()
        monitor = RESOURCE.RuntimeResourceMonitor.__new__(
            RESOURCE.RuntimeResourceMonitor
        )
        monitor.process = process
        monitor.pid = 7
        monitor.pgid = 7
        monitor.leader_identity = (7, 9)
        argv = ["/exact/hfnet"]

        def record(
            *,
            state="S",
            executable="/exact/hfnet",
            cmdline=None,
        ):
            tokens = argv if cmdline is None else cmdline
            raw = b"\0".join(os.fsencode(value) for value in tokens)
            if tokens:
                raw += b"\0"
            return {
                "pid": 7,
                "start_ticks": 9,
                "pgid": 7,
                "session": 7,
                "state": state,
                "executable": executable,
                "cmdline": tokens,
                "cmdline_sha256": hashlib.sha256(raw).hexdigest(),
                "read_errors": [],
            }

        initial = record(state="S")
        current = record(state="R")
        with mock.patch.object(
            RESOURCE, "_scan_processes", return_value=([initial], [])
        ), mock.patch.object(
            RESOURCE, "_read_process_record", return_value=(current, [])
        ):
            live = monitor.watchdog_exact_group_snapshot(argv[0], argv)
        self.assertTrue(live["proven"], live)
        self.assertEqual(live["members"][0]["state"], "R")
        process.poll.assert_not_called()

        with mock.patch.object(
            RESOURCE, "_scan_processes", return_value=([], [])
        ):
            absent = monitor.watchdog_exact_group_snapshot(argv[0], argv)
        self.assertTrue(
            RESOURCE.watchdog_terminal_transition_candidate(absent), absent
        )

        with mock.patch.object(
            RESOURCE, "_scan_processes", return_value=([initial], [])
        ), mock.patch.object(
            RESOURCE, "_read_process_record", return_value=(None, [])
        ):
            vanished = monitor.watchdog_exact_group_snapshot(argv[0], argv)
        self.assertTrue(
            RESOURCE.watchdog_terminal_transition_candidate(vanished), vanished
        )

        drifted_visible = record(state="S")
        drifted_visible["pgid"] = 8
        drifted_visible["session"] = 8
        with mock.patch.object(
            RESOURCE,
            "_scan_processes",
            return_value=([drifted_visible], []),
        ):
            visible_outside_group = monitor.watchdog_exact_group_snapshot(
                argv[0], argv
            )
        self.assertIn(
            "GLOBAL_FROZEN_LEADER_STABLE_IDENTITY_DRIFT",
            visible_outside_group["errors"],
        )
        self.assertFalse(
            RESOURCE.watchdog_terminal_transition_candidate(
                visible_outside_group
            ),
            visible_outside_group,
        )

        zombie = record(state="Z", executable=None, cmdline=[])
        with mock.patch.object(
            RESOURCE, "_scan_processes", return_value=([zombie], [])
        ), mock.patch.object(
            RESOURCE, "_read_process_record", return_value=(zombie, [])
        ):
            terminal = monitor.watchdog_exact_group_snapshot(argv[0], argv)
        self.assertTrue(
            RESOURCE.watchdog_terminal_transition_candidate(terminal), terminal
        )

        non_z_empty = record(state="S", executable=None, cmdline=[])
        with mock.patch.object(
            RESOURCE, "_scan_processes", return_value=([non_z_empty], [])
        ), mock.patch.object(
            RESOURCE, "_read_process_record", return_value=(non_z_empty, [])
        ):
            not_terminal = monitor.watchdog_exact_group_snapshot(argv[0], argv)
        self.assertFalse(
            RESOURCE.watchdog_terminal_transition_candidate(not_terminal),
            not_terminal,
        )

        wrong = record(executable="/wrong/live/hfnet", cmdline=["/wrong/live/hfnet"])
        with mock.patch.object(
            RESOURCE, "_scan_processes", return_value=([wrong], [])
        ), mock.patch.object(
            RESOURCE, "_read_process_record", return_value=(wrong, [])
        ):
            wrong_identity = monitor.watchdog_exact_group_snapshot(argv[0], argv)
        self.assertFalse(
            RESOURCE.watchdog_terminal_transition_candidate(wrong_identity),
            wrong_identity,
        )
        process.poll.assert_not_called()

    def test_watchdog_gate_latch_is_atomic_under_concurrency(self) -> None:
        process = mock.Mock()
        process.poll.return_value = None
        monitor = RESOURCE.RuntimeResourceMonitor.__new__(
            RESOURCE.RuntimeResourceMonitor
        )
        monitor.process = process
        monitor.pid = 7
        monitor.pgid = 7
        monitor.leader_identity = (7, 9)
        monitor._lock = threading.RLock()
        monitor._watchdog_gate_entered = False
        monitor._watchdog_signal_attempted = False
        monitor._cleanup_actions = []
        entered = threading.Event()
        release = threading.Event()
        proof_calls = {"count": 0}
        proof = {
            "proven": True,
            "errors": [],
            "members": [{"pid": 7, "start_ticks": 9, "state": "S"}],
        }

        def proof_side_effect(*_args):
            proof_calls["count"] += 1
            if proof_calls["count"] == 1:
                entered.set()
                self.assertTrue(release.wait(timeout=5.0))
            return json.loads(json.dumps(proof))

        results = []
        failures = []

        def invoke():
            try:
                results.append(
                    monitor.watchdog_sigterm_exact_group(
                        "/exact/hfnet",
                        ["/exact/hfnet"],
                        deadline_monotonic=100.0,
                        sample_started_monotonic=0.0,
                        maximum_observation_gap_seconds=0.25,
                        monotonic=lambda: 0.0,
                    )
                )
            except BaseException as error:
                failures.append(error)

        with mock.patch.object(
            monitor,
            "watchdog_exact_group_snapshot",
            side_effect=proof_side_effect,
        ), mock.patch.object(RESOURCE.os, "killpg") as killpg:
            first = threading.Thread(target=invoke)
            second = threading.Thread(target=invoke)
            first.start()
            self.assertTrue(entered.wait(timeout=5.0))
            second.start()
            second.join(timeout=5.0)
            release.set()
            first.join(timeout=5.0)
        self.assertEqual(failures, [])
        self.assertEqual(len(results), 2)
        self.assertEqual(killpg.call_count, 1)
        self.assertEqual(
            sorted(value["classification"] for value in results),
            ["SIGNAL_ALREADY_ATTEMPTED", "SIGTERM_SENT"],
        )

    def test_clean_natural_exit_has_mandatory_ordinary_adjudication(self) -> None:
        class Process:
            returncode = 0

            def poll(self):
                return self.returncode

            def wait(self, timeout=0):
                return self.returncode

        returncode, reaped, timed_out, outcome = (
            HFNET.wait_with_zero_kf_watchdog(
                Process(), mock.Mock(), Path("stdout"), Path("trajectory"),
                Path("keyframes"), "/exact/hfnet", ["/exact/hfnet"],
                timeout=10.0,
            )
        )
        self.assertEqual(returncode, 0)
        self.assertTrue(reaped)
        self.assertFalse(timed_out)
        self.assertTrue(outcome["monitor_proven"], outcome)
        passive = outcome["passive_exit_adjudication"]
        self.assertEqual(passive["phase"], "ORDINARY_PROCESS_EXIT:LOOP_POLL")
        self.assertIsNone(passive["last_exact_group_snapshot"])
        self.assertEqual(passive["child_returncode"], 0)

    def test_final_passive_proof_time_counts_toward_poll_gap(self) -> None:
        class Clock:
            value = 0.0

            def __call__(self):
                return self.value

        clock = Clock()
        monitor = mock.Mock()
        monitor.watchdog_exact_group_snapshot.return_value = {
            "proven": True,
            "errors": [],
            "members": [{"pid": 7, "start_ticks": 9}],
        }

        def delayed_passive(*_args, **_kwargs):
            clock.value += 0.30
            return {
                "classification": "LEADER_REAPED_BEFORE_SIGNAL",
                "phase": "BEFORE_FIRST_FINAL_GROUP_PROOF",
                "leader_returncode": -6,
                "reaped_before_next_sample": True,
                "signal_attempted": False,
                "signal_sent": False,
                "errors": [],
            }

        monitor.watchdog_sigterm_exact_group.side_effect = delayed_passive

        class Process:
            returncode = None

            def poll(self):
                return self.returncode

            def wait(self, timeout=0):
                if monitor.watchdog_sigterm_exact_group.called:
                    self.returncode = -6
                    return self.returncode
                clock.value += float(timeout)
                raise subprocess.TimeoutExpired(["dummy"], timeout)

        with mock.patch.object(
            HFNET,
            "parse_zero_kf_post_shutdown_signature",
            return_value={"parser_proven": True, "confirmed": True, "errors": []},
        ):
            returncode, reaped, timed_out, outcome = (
                HFNET.wait_with_zero_kf_watchdog(
                    Process(), monitor, Path("stdout"), Path("trajectory"),
                    Path("keyframes"), "/exact/hfnet", ["/exact/hfnet"],
                    timeout=100.0, monotonic=clock,
                )
            )
        self.assertEqual(returncode, -6)
        self.assertTrue(reaped)
        self.assertFalse(timed_out)
        self.assertFalse(outcome["monitor_proven"], outcome)
        self.assertIsNone(outcome["passive_exit_adjudication"])
        self.assertGreater(
            outcome["maximum_observed_poll_interval_seconds"], 0.25
        )
        self.assertTrue(
            any(
                str(value).startswith("WATCHDOG_POLL_GAP_EXCEEDED:")
                for value in outcome["monitoring_errors"]
            ),
            outcome,
        )

    def test_failed_signal_action_is_preserved_in_runner_outcome(self) -> None:
        class Clock:
            value = 0.0

            def __call__(self):
                return self.value

        clock = Clock()
        monitor = mock.Mock()
        monitor.watchdog_exact_group_snapshot.return_value = {
            "proven": True,
            "errors": [],
            "members": [{"pid": 7, "start_ticks": 9}],
        }
        failed_action = {
            "classification": "SIGNAL_DELIVERY_FAILED",
            "signal_attempted": True,
            "signal_sent": False,
            "errors": ["WATCHDOG_KILLPG_FAILED:3"],
        }
        monitor.watchdog_sigterm_exact_group.return_value = failed_action

        class Process:
            returncode = None

            def poll(self):
                return self.returncode

            def wait(self, timeout=0):
                if monitor.watchdog_sigterm_exact_group.called:
                    self.returncode = -6
                    return self.returncode
                clock.value += float(timeout)
                raise subprocess.TimeoutExpired(["dummy"], timeout)

        with mock.patch.object(
            HFNET,
            "parse_zero_kf_post_shutdown_signature",
            return_value={"parser_proven": True, "confirmed": True, "errors": []},
        ):
            returncode, reaped, timed_out, outcome = (
                HFNET.wait_with_zero_kf_watchdog(
                    Process(), monitor, Path("stdout"), Path("trajectory"),
                    Path("keyframes"), "/exact/hfnet", ["/exact/hfnet"],
                    timeout=100.0, monotonic=clock,
                )
            )
        self.assertEqual(returncode, -6)
        self.assertTrue(reaped)
        self.assertFalse(timed_out)
        self.assertFalse(outcome["monitor_proven"], outcome)
        self.assertEqual(outcome["watchdog_action"], failed_action)
        self.assertTrue(outcome["signal_attempted"])
        self.assertFalse(outcome["sigterm_sent"])
        self.assertIn(
            "FINAL_SIGNAL_GATE:WATCHDOG_KILLPG_FAILED:3",
            outcome["monitoring_errors"],
        )

    def run_fake_watchdog(
        self,
        timeout: float,
        parser_side_effect=None,
        *,
        first_parser_delay: float = 0.0,
        first_group_delay: float = 0.0,
        parser_delay_at_call: tuple[int, float] | None = None,
        group_delay_at_call: tuple[int, float] | None = None,
    ) -> tuple[dict[str, object], mock.Mock]:
        class Clock:
            value = 0.0

            def __call__(self):
                return self.value

        clock = Clock()
        monitor = mock.Mock()
        group_calls = {"count": 0}

        def group_snapshot(*_args, **_kwargs):
            group_calls["count"] += 1
            if group_calls["count"] == 1:
                clock.value += first_group_delay
            if (
                group_delay_at_call is not None
                and group_calls["count"] == group_delay_at_call[0]
            ):
                clock.value += group_delay_at_call[1]
            return {
                "proven": True,
                "errors": [],
                "members": [{"pid": 7, "start_ticks": 9}],
            }

        monitor.watchdog_exact_group_snapshot.side_effect = group_snapshot
        monitor.watchdog_sigterm_exact_group.return_value = {
            "signal_attempted": True,
            "signal_sent": True,
            "signal": 15,
            "individual_identities_sent": [],
            "errors": [],
        }

        class Process:
            pid = 7
            returncode = None

            def poll(self):
                return self.returncode

            def wait(self, timeout=0):
                if monitor.watchdog_sigterm_exact_group.called:
                    self.returncode = -15
                    return self.returncode
                clock.value += float(timeout)
                raise subprocess.TimeoutExpired(["dummy"], timeout)

        confirmed = {"parser_proven": True, "confirmed": True, "errors": []}
        parser_calls = {"count": 0}

        def parser(*args):
            parser_calls["count"] += 1
            if parser_calls["count"] == 1:
                clock.value += first_parser_delay
            if (
                parser_delay_at_call is not None
                and parser_calls["count"] == parser_delay_at_call[0]
            ):
                clock.value += parser_delay_at_call[1]
            if parser_side_effect is not None:
                return parser_side_effect(*args)
            return dict(confirmed)

        with mock.patch.object(
            HFNET, "parse_zero_kf_post_shutdown_signature", side_effect=parser
        ):
            _returncode, _reaped, _timed_out, outcome = (
                HFNET.wait_with_zero_kf_watchdog(
                    Process(),
                    monitor,
                    Path("stdout"),
                    Path("trajectory"),
                    Path("keyframes"),
                    "/exact/hfnet",
                    ["/exact/hfnet"],
                    timeout=timeout,
                    monotonic=clock,
                )
            )
        return outcome, monitor

    def test_continuous_thirty_second_gate_and_reset(self) -> None:
        before, before_monitor = self.run_fake_watchdog(29.999)
        self.assertFalse(before["sigterm_sent"])
        before_monitor.watchdog_sigterm_exact_group.assert_not_called()
        after, after_monitor = self.run_fake_watchdog(30.5)
        self.assertTrue(after["sigterm_sent"], after)
        after_monitor.watchdog_sigterm_exact_group.assert_called_once()

        calls = {"count": 0}

        def interrupted(*_args):
            calls["count"] += 1
            if calls["count"] == 51:
                return {"parser_proven": True, "confirmed": False, "errors": []}
            return {"parser_proven": True, "confirmed": True, "errors": []}

        reset, reset_monitor = self.run_fake_watchdog(35.0, interrupted)
        self.assertFalse(reset["sigterm_sent"], reset)
        reset_monitor.watchdog_sigterm_exact_group.assert_not_called()

        delayed, delayed_monitor = self.run_fake_watchdog(
            30.05,
            first_parser_delay=0.10,
            first_group_delay=0.10,
        )
        self.assertFalse(delayed["sigterm_sent"], delayed)
        delayed_monitor.watchdog_sigterm_exact_group.assert_not_called()

        proof_overrun, proof_overrun_monitor = self.run_fake_watchdog(
            0.20,
            first_parser_delay=0.30,
        )
        self.assertFalse(proof_overrun["monitor_proven"], proof_overrun)
        self.assertTrue(
            any(
                str(value).startswith("WATCHDOG_POLL_GAP_EXCEEDED:")
                for value in proof_overrun["monitoring_errors"]
            ),
            proof_overrun,
        )
        proof_overrun_monitor.watchdog_sigterm_exact_group.assert_not_called()

        trigger_group_overrun, trigger_group_monitor = self.run_fake_watchdog(
            31.0,
            group_delay_at_call=(151, 0.30),
        )
        self.assertFalse(trigger_group_overrun["monitor_proven"], trigger_group_overrun)
        trigger_group_monitor.watchdog_sigterm_exact_group.assert_not_called()

        final_parser_overrun, final_parser_monitor = self.run_fake_watchdog(
            31.0,
            parser_delay_at_call=(152, 0.30),
        )
        self.assertFalse(final_parser_overrun["monitor_proven"], final_parser_overrun)
        final_parser_monitor.watchdog_sigterm_exact_group.assert_not_called()

    def test_natural_exit_tail_poll_gap_fails_closed(self) -> None:
        class Clock:
            value = 0.0

            def __call__(self):
                return self.value

        clock = Clock()

        class DelayedExitProcess:
            returncode = None

            def poll(self):
                return self.returncode

            def wait(self, timeout=0):
                clock.value += 1.0
                self.returncode = 0
                return 0

        monitor = mock.Mock()
        with mock.patch.object(
            HFNET,
            "parse_zero_kf_post_shutdown_signature",
            return_value={"parser_proven": True, "confirmed": False, "errors": []},
        ):
            _returncode, _reaped, _timed_out, outcome = (
                HFNET.wait_with_zero_kf_watchdog(
                    DelayedExitProcess(),
                    monitor,
                    Path("stdout"),
                    Path("trajectory"),
                    Path("keyframes"),
                    "/exact/hfnet",
                    ["/exact/hfnet"],
                    timeout=10.0,
                    monotonic=clock,
                )
            )
        self.assertFalse(outcome["monitor_proven"], outcome)
        self.assertGreater(
            outcome["maximum_observed_poll_interval_seconds"], 0.25
        )
        self.assertTrue(
            any(
                str(value).startswith("WATCHDOG_POLL_GAP_EXCEEDED:")
                for value in outcome["monitoring_errors"]
            ),
            outcome,
        )

    @staticmethod
    def terminal_transition_snapshot(
        executable: str = "/exact/hfnet",
        argv: list[str] | None = None,
    ) -> dict[str, object]:
        expected_argv = argv or [executable]
        return {
            "observed_at_utc": "2026-08-29T10:00:00+00:00",
            "observed_monotonic_ns": 1,
            "proven": False,
            "errors": ["EXACT_GROUP_LEADER_IDENTITY_OR_ARGV_MISMATCH"],
            "leader_pid": 7,
            "leader_start_ticks": 9,
            "expected_executable": executable,
            "expected_argv": expected_argv,
            "pgid": 7,
            "session": 7,
            "members": [
                {
                    "pid": 7,
                    "start_ticks": 9,
                    "pgid": 7,
                    "session": 7,
                    "state": "Z",
                    "executable": None,
                    "cmdline_sha256": RESOURCE.EMPTY_CMDLINE_SHA256,
                }
            ],
        }

    def test_terminal_transition_reaped_before_next_sample_is_passive(self) -> None:
        class Clock:
            value = 0.0

            def __call__(self):
                return self.value

        clock = Clock()
        monitor = mock.Mock()
        monitor.watchdog_exact_group_snapshot.return_value = (
            self.terminal_transition_snapshot()
        )

        class Process:
            returncode = None

            def poll(self):
                return self.returncode

            def wait(self, timeout=0):
                clock.value += min(float(timeout), 0.1)
                self.returncode = -6
                return self.returncode

        with mock.patch.object(
            HFNET,
            "parse_zero_kf_post_shutdown_signature",
            return_value={"parser_proven": True, "confirmed": True, "errors": []},
        ):
            returncode, reaped, timed_out, outcome = (
                HFNET.wait_with_zero_kf_watchdog(
                    Process(), monitor, Path("stdout"), Path("trajectory"),
                    Path("keyframes"), "/exact/hfnet", ["/exact/hfnet"],
                    timeout=10.0, monotonic=clock,
                )
            )
        self.assertEqual(returncode, -6)
        self.assertTrue(reaped)
        self.assertFalse(timed_out)
        self.assertTrue(outcome["monitor_proven"], outcome)
        self.assertEqual(outcome["monitoring_errors"], [])
        passive = outcome["passive_exit_adjudication"]
        self.assertEqual(passive["phase"], "PERIODIC_EXACT_GROUP_PROOF")
        self.assertEqual(passive["child_returncode"], -6)
        self.assertFalse(passive["signal_attempted"])
        monitor.watchdog_sigterm_exact_group.assert_not_called()

    def test_terminal_transition_still_live_and_wrong_nonempty_identity_fail(self) -> None:
        class Clock:
            value = 0.0

            def __call__(self):
                return self.value

        def run(snapshot: dict[str, object]) -> dict[str, object]:
            clock = Clock()
            monitor = mock.Mock()
            monitor.watchdog_exact_group_snapshot.return_value = snapshot

            class Process:
                returncode = None
                waits = 0

                def poll(self):
                    return self.returncode

                def wait(self, timeout=0):
                    self.waits += 1
                    clock.value += float(timeout)
                    if self.waits >= 2:
                        self.returncode = -6
                        return self.returncode
                    raise subprocess.TimeoutExpired(["dummy"], timeout)

            with mock.patch.object(
                HFNET,
                "parse_zero_kf_post_shutdown_signature",
                return_value={"parser_proven": True, "confirmed": True, "errors": []},
            ):
                return HFNET.wait_with_zero_kf_watchdog(
                    Process(), monitor, Path("stdout"), Path("trajectory"),
                    Path("keyframes"), "/exact/hfnet", ["/exact/hfnet"],
                    timeout=10.0, monotonic=clock,
                )[3]

        still_live = run(self.terminal_transition_snapshot())
        self.assertFalse(still_live["monitor_proven"], still_live)
        self.assertIsNone(still_live["passive_exit_adjudication"])

        wrong = self.terminal_transition_snapshot()
        wrong["members"][0]["executable"] = "/wrong/live/hfnet"
        wrong["members"][0]["cmdline_sha256"] = "a" * 64
        wrong_later_exited = run(wrong)
        self.assertFalse(wrong_later_exited["monitor_proven"], wrong_later_exited)
        self.assertIsNone(wrong_later_exited["passive_exit_adjudication"])

        visible_pgid_drift = self.terminal_transition_snapshot()
        visible_pgid_drift["errors"] = [
            "GLOBAL_FROZEN_LEADER_STABLE_IDENTITY_DRIFT",
            "EXACT_GROUP_LEADER_COUNT:0",
        ]
        visible_pgid_drift["members"] = []
        drift_then_reaped = run(visible_pgid_drift)
        self.assertFalse(drift_then_reaped["monitor_proven"], drift_then_reaped)
        self.assertIsNone(drift_then_reaped["passive_exit_adjudication"])

        class ImmediateWrongExitProcess:
            returncode = None
            polls = 0

            def poll(self):
                self.polls += 1
                if self.polls >= 2:
                    self.returncode = -6
                return self.returncode

            def wait(self, timeout=0):
                return -6

        immediate_monitor = mock.Mock()
        immediate_monitor.watchdog_exact_group_snapshot.return_value = wrong
        with mock.patch.object(
            HFNET,
            "parse_zero_kf_post_shutdown_signature",
            return_value={"parser_proven": True, "confirmed": True, "errors": []},
        ):
            immediate = HFNET.wait_with_zero_kf_watchdog(
                ImmediateWrongExitProcess(), immediate_monitor, Path("stdout"),
                Path("trajectory"), Path("keyframes"), "/exact/hfnet",
                ["/exact/hfnet"], timeout=10.0, monotonic=Clock(),
            )[3]
        self.assertFalse(immediate["monitor_proven"], immediate)
        self.assertIsNone(immediate["passive_exit_adjudication"])

    def test_final_double_proof_exit_is_passive_and_never_signaled(self) -> None:
        process = mock.Mock()
        process.poll.side_effect = [None, None, -6]
        process.wait.return_value = -6
        monitor = RESOURCE.RuntimeResourceMonitor.__new__(
            RESOURCE.RuntimeResourceMonitor
        )
        monitor.process = process
        monitor.pid = 7
        monitor.pgid = 7
        monitor.leader_identity = (7, 9)
        monitor._watchdog_signal_attempted = False
        monitor._lock = threading.RLock()
        monitor._cleanup_actions = []
        proof = {
            "proven": True,
            "errors": [],
            "members": [{"pid": 7, "start_ticks": 9}],
        }
        with mock.patch.object(
            monitor, "watchdog_exact_group_snapshot", return_value=proof
        ), mock.patch.object(RESOURCE.os, "killpg") as killpg:
            gate = monitor.watchdog_sigterm_exact_group(
                "/exact/hfnet", ["/exact/hfnet"],
                deadline_monotonic=100.0,
                sample_started_monotonic=0.0,
                maximum_observation_gap_seconds=0.25,
                monotonic=lambda: 0.0,
            )
        self.assertEqual(gate["classification"], "LEADER_REAPED_BEFORE_SIGNAL")
        self.assertEqual(gate["leader_returncode"], -6)
        self.assertFalse(gate["signal_attempted"])
        self.assertFalse(monitor._watchdog_signal_attempted)
        self.assertEqual(monitor._cleanup_actions, [])
        killpg.assert_not_called()

        wrong_process = mock.Mock()
        wrong_process.poll.side_effect = [None, -6]
        wrong_monitor = RESOURCE.RuntimeResourceMonitor.__new__(
            RESOURCE.RuntimeResourceMonitor
        )
        wrong_monitor.process = wrong_process
        wrong_monitor.pid = 7
        wrong_monitor.pgid = 7
        wrong_monitor.leader_identity = (7, 9)
        wrong_monitor._watchdog_signal_attempted = False
        wrong_monitor._lock = threading.RLock()
        wrong_monitor._cleanup_actions = []
        wrong_proof = self.terminal_transition_snapshot()
        wrong_proof["members"][0]["executable"] = "/wrong/live/hfnet"
        wrong_proof["members"][0]["cmdline_sha256"] = "b" * 64
        with mock.patch.object(
            wrong_monitor, "watchdog_exact_group_snapshot", return_value=wrong_proof
        ), mock.patch.object(RESOURCE.os, "killpg") as wrong_killpg:
            wrong_gate = wrong_monitor.watchdog_sigterm_exact_group(
                "/exact/hfnet", ["/exact/hfnet"],
                deadline_monotonic=100.0,
                sample_started_monotonic=0.0,
                maximum_observation_gap_seconds=0.25,
                monotonic=lambda: 0.0,
            )
        self.assertEqual(
            wrong_gate["classification"], "LIVE_OR_UNKNOWN_GROUP_UNPROVEN"
        )
        self.assertFalse(wrong_gate["signal_attempted"])
        wrong_killpg.assert_not_called()

    def test_common_watchdog_chain_rejects_contradictory_signal_proofs(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "attempt"
            result_dir = root / "result"
            result_dir.mkdir(parents=True)
            trajectory = result_dir / "trajectory.txt"
            keyframes = result_dir / "trajectory_keyframe.txt"
            stdout = root / "headless.stdout.log"
            stdout.write_text(
                self.signature_lines(trajectory, [(0, 0)]), encoding="utf-8"
            )
            contract = {
                "enabled": True,
                "fixed_grace_seconds": 30.0,
                "target_poll_interval_seconds": 0.20,
                "maximum_poll_interval_seconds": 0.25,
                "signal": "SIGTERM",
                "signal_scope": "EXACT_REVALIDATED_PROCESS_GROUP",
                "signal_attempt_limit": 1,
                "sigkill_authorized_by_watchdog": False,
                "estimator_total_timeout_seconds": 1800,
                "applies_to_all_hfnet_budgets_windows_and_repeats": True,
            }
            argv = [
                "/exact/hfnet",
                str(root / "config.yaml"),
                f"{result_dir}/",
                str(root / "images"),
                str(root / "times.txt"),
            ]
            manifest = {
                "zero_kf_post_shutdown_watchdog": contract,
                "launch": {"argv": argv},
            }
            (root / "attempt_manifest.json").write_bytes(
                HFNET.canonical_json(manifest)
            )
            (root / "start_claim.json").write_text("{}\n", encoding="ascii")
            (root / "runtime_resource_monitor.json").write_text(
                "{}\n", encoding="ascii"
            )
            launch = {
                "schema_version": "aqua-fe-fair-stability-hfnet-launch-receipt-v6",
                "experiment_id": ORDINAL.EXPERIMENT_ID,
                "valid": True,
                "errors": [],
                "pid": 4242,
                "start_ticks": 777,
                "pgid": 4242,
                "session": 4242,
                "executable": argv[0],
                "argv": argv,
                "expected_executable": argv[0],
                "expected_argv": argv,
            }
            (root / "launch_receipt.json").write_bytes(HFNET.canonical_json(launch))

            def runtime_receipt(returncode, cleanup_actions):
                return {
                    "schema_version": (
                        "aqua-fe-fair-stability-runtime-resource-monitor-v6"
                    ),
                    "experiment_id": ORDINAL.EXPERIMENT_ID,
                    "coverage": {"process_group_empty": True},
                    "supervised_process": {
                        "pid": 4242,
                        "leader_identity": {"pid": 4242, "start_ticks": 777},
                        "pgid": 4242,
                        "returncode": returncode,
                        "active_owned_identities_at_finalize": [],
                    },
                    "cleanup_actions": cleanup_actions,
                    "intrusion_detected": False,
                    "monitor_proven": True,
                    "pipeline_valid": True,
                    "pipeline_failure_reasons": [],
                }

            member = {
                "pid": 4242,
                "start_ticks": 777,
                "pgid": 4242,
                "session": 4242,
                "state": "S",
                "executable": argv[0],
                "cmdline_sha256": hashlib.sha256(
                    b"\0".join(os.fsencode(value) for value in argv) + b"\0"
                ).hexdigest(),
            }
            proof = {
                "observed_at_utc": "2026-08-29T10:00:30+00:00",
                "observed_monotonic_ns": 30_000_000_000,
                "proven": True,
                "errors": [],
                "leader_pid": 4242,
                "leader_start_ticks": 777,
                "expected_executable": argv[0],
                "expected_argv": argv,
                "pgid": 4242,
                "session": 4242,
                "members": [member],
            }
            action = {
                "at_utc": "2026-08-29T10:00:31+00:00",
                "monotonic_ns": 30_160_000_000,
                "deadline_monotonic": 1800.0,
                "sample_started_monotonic": 30.0,
                "maximum_observation_gap_seconds": 0.25,
                "pre_signal_monotonic": 30.15,
                "label": "confirmed_zero_kf_post_shutdown_watchdog",
                "signal": 15,
                "signal_scope": "EXACT_REVALIDATED_PROCESS_GROUP",
                "signal_attempted": True,
                "signal_sent": True,
                "group_sent": True,
                "group_error": None,
                "individual_identities_sent": [],
                "first_exact_group_proof": proof,
                "final_exact_group_proof": json.loads(json.dumps(proof)),
                "errors": [],
            }
            action["first_exact_group_proof"][
                "observed_monotonic_ns"
            ] = 30_050_000_000
            action["final_exact_group_proof"][
                "observed_monotonic_ns"
            ] = 30_100_000_000
            (root / "runtime_resource_monitor.json").write_bytes(
                HFNET.canonical_json(runtime_receipt(-15, [action]))
            )
            signature = HFNET.parse_zero_kf_post_shutdown_signature(
                stdout, trajectory, keyframes
            )
            outcome = {
                "schema_version": (
                    "aqua-fe-fair-stability-hfnet-zero-kf-watchdog-outcome-v6"
                ),
                "monitor_proven": True,
                "monitoring_errors": [],
                "sample_count": 151,
                "target_poll_interval_seconds": 0.20,
                "maximum_allowed_poll_interval_seconds": 0.25,
                "maximum_observed_poll_interval_seconds": 0.20,
                "fixed_signature_grace_seconds": 30.0,
                "signature_first_observed_at_utc": "2026-08-29T10:00:00+00:00",
                "signature_continuous_seconds_at_end": 30.1,
                "last_confirmed_signature": signature,
                "last_exact_group_snapshot": json.loads(json.dumps(proof)),
                "watchdog_action": action,
                "final_child_returncode": -15,
                "signal_attempted": True,
                "sigterm_sent": True,
                "permanently_disabled_after_unproven_evidence": False,
                "total_timeout_seconds": 1800,
            }
            receipt = {
                "schema_version": (
                    "aqua-fe-fair-stability-hfnet-zero-kf-post-shutdown-watchdog-v6"
                ),
                "experiment_id": ORDINAL.EXPERIMENT_ID,
                "finalized_at_utc": "2026-08-29T10:00:32+00:00",
                "case_id": "case",
                "budget": 675,
                "arm": "hfnet_openloop_675",
                "repeat": 1,
                "attempt_index": 1,
                "attempt_root": str(root),
                "status": (
                    "SIGTERM_SENT_FOR_CONFIRMED_ZERO_KF_POST_SHUTDOWN_SAVE_HANG"
                ),
                "monitor_proven": True,
                "monitoring_errors": [],
                "fixed_contract": contract,
                "outcome": outcome,
                "watchdog_action": action,
                "final_child_returncode": -15,
                "sigterm_sent": True,
                "signal_attempt_count": 1,
                "signal_count": 1,
                "signal": "SIGTERM",
                "signal_scope": "EXACT_REVALIDATED_PROCESS_GROUP",
                "sigkill_sent_by_watchdog": False,
                "retry_permitted": False,
                "pins": {
                    label: ORDINAL.identity(path)
                    for label, path in {
                        "attempt_manifest": root / "attempt_manifest.json",
                        "start_claim": root / "start_claim.json",
                        "launch_receipt": root / "launch_receipt.json",
                        "stdout": stdout,
                        "runtime_resource_monitor": (
                            root / "runtime_resource_monitor.json"
                        ),
                    }.items()
                },
                "final_outputs": {
                    "trajectory_path": str(trajectory),
                    "trajectory_absent_non_symlink": True,
                    "keyframe_path": str(keyframes),
                    "keyframe_absent_non_symlink": True,
                },
            }
            receipt_path = root / "zero_kf_post_shutdown_watchdog.json"
            result = {
                "pipeline_failure_codes": [],
                "algorithm_failure_codes": [
                    "CONFIRMED_ZERO_KF_POST_SHUTDOWN_SAVE_HANG"
                ],
                "execution": {
                    "raw_returncode": -15,
                    "child_reaped": True,
                    "timed_out": False,
                    "supervised_process_group_empty_after_wait": True,
                },
                "runtime_resource_monitor_decision": {
                    "intrusion_detected": False,
                    "monitor_proven": True,
                    "pipeline_failure_reasons": [],
                },
                "zero_kf_post_shutdown_watchdog_decision": {
                    "monitor_proven": True,
                    "sigterm_sent": True,
                    "retry_permitted": False,
                    "pipeline_failure_code_if_unproven": (
                        "ZERO_KF_POST_SHUTDOWN_WATCHDOG_UNPROVEN"
                    ),
                    "algorithm_failure_code_if_sent": (
                        "CONFIRMED_ZERO_KF_POST_SHUTDOWN_SAVE_HANG"
                    ),
                },
            }
            cell = {
                "case_id": "case",
                "arm": "hfnet_openloop_675",
                "repeat": 1,
            }

            def publish(candidate):
                candidate_action = candidate.get("watchdog_action")
                (root / "runtime_resource_monitor.json").write_bytes(
                    HFNET.canonical_json(
                        runtime_receipt(
                            -15,
                            [candidate_action]
                            if isinstance(candidate_action, dict)
                            else [],
                        )
                    )
                )
                candidate["pins"]["runtime_resource_monitor"] = ORDINAL.identity(
                    root / "runtime_resource_monitor.json"
                )
                receipt_path.write_bytes(HFNET.canonical_json(candidate))
                result["zero_kf_post_shutdown_watchdog"] = ORDINAL.identity(
                    receipt_path
                )

            publish(receipt)
            ORDINAL.validate_hfnet_watchdog_evidence(
                root, manifest, result, cell, 1
            )

            transition = {
                "observed_at_utc": "2026-08-29T10:00:00+00:00",
                "observed_monotonic_ns": 1,
                "proven": False,
                "errors": ["EXACT_GROUP_LEADER_IDENTITY_OR_ARGV_MISMATCH"],
                "leader_pid": 4242,
                "leader_start_ticks": 777,
                "expected_executable": argv[0],
                "expected_argv": argv,
                "pgid": 4242,
                "session": 4242,
                "members": [{
                    "pid": 4242,
                    "start_ticks": 777,
                    "pgid": 4242,
                    "session": 4242,
                    "state": "Z",
                    "executable": None,
                    "cmdline_sha256": RESOURCE.EMPTY_CMDLINE_SHA256,
                }],
            }
            passive = {
                "phase": "PERIODIC_EXACT_GROUP_PROOF",
                "evidence": transition,
                "last_exact_group_snapshot": transition,
                "adjudicated_at_utc": "2026-08-29T10:00:01+00:00",
                "adjudicated_monotonic_ns": 2,
                "child_returncode": -6,
                "reaped_before_next_sample": True,
                "signal_attempted": False,
                "signal_sent": False,
            }
            passive_outcome = {
                "schema_version": (
                    "aqua-fe-fair-stability-hfnet-zero-kf-watchdog-outcome-v6"
                ),
                "monitor_proven": True,
                "monitoring_errors": [],
                "sample_count": 1,
                "target_poll_interval_seconds": 0.20,
                "maximum_allowed_poll_interval_seconds": 0.25,
                "maximum_observed_poll_interval_seconds": 0.20,
                "fixed_signature_grace_seconds": 30.0,
                "signature_first_observed_at_utc": None,
                "signature_continuous_seconds_at_end": 0.0,
                "last_confirmed_signature": None,
                "last_exact_group_snapshot": transition,
                "watchdog_action": None,
                "passive_exit_adjudication": passive,
                "signal_attempted": False,
                "sigterm_sent": False,
                "permanently_disabled_after_unproven_evidence": False,
                "total_timeout_seconds": 1800,
            }
            (root / "runtime_resource_monitor.json").write_bytes(
                HFNET.canonical_json(runtime_receipt(-6, []))
            )
            passive_receipt = HFNET.build_zero_kf_watchdog_receipt(
                root, "case", 675, 1, 1, manifest, passive_outcome, -6, []
            )
            passive_result = {
                "pipeline_failure_codes": [],
                "algorithm_failure_codes": ["ESTIMATOR_NONZERO_EXIT"],
                "execution": {
                    "raw_returncode": -6,
                    "child_reaped": True,
                    "timed_out": False,
                    "supervised_process_group_empty_after_wait": True,
                },
                "runtime_resource_monitor_decision": {
                    "intrusion_detected": False,
                    "monitor_proven": True,
                    "pipeline_failure_reasons": [],
                },
                "zero_kf_post_shutdown_watchdog_decision": {
                    "monitor_proven": True,
                    "sigterm_sent": False,
                    "retry_permitted": False,
                    "pipeline_failure_code_if_unproven": (
                        "ZERO_KF_POST_SHUTDOWN_WATCHDOG_UNPROVEN"
                    ),
                    "algorithm_failure_code_if_sent": (
                        "CONFIRMED_ZERO_KF_POST_SHUTDOWN_SAVE_HANG"
                    ),
                },
            }

            def publish_passive(candidate):
                receipt_path.write_bytes(HFNET.canonical_json(candidate))
                passive_result["zero_kf_post_shutdown_watchdog"] = (
                    ORDINAL.identity(receipt_path)
                )

            publish_passive(passive_receipt)
            ORDINAL.validate_hfnet_watchdog_evidence(
                root, manifest, passive_result, cell, 1
            )
            passive_tampers = {
                "returncode": lambda value: value[
                    "passive_exit_adjudication"
                ].__setitem__("child_returncode", 0),
                "not_reaped": lambda value: value[
                    "passive_exit_adjudication"
                ].__setitem__("reaped_before_next_sample", False),
                "signal_attempted": lambda value: value[
                    "passive_exit_adjudication"
                ].__setitem__("signal_attempted", True),
                "wrong_live_executable": lambda value: value[
                    "passive_exit_adjudication"
                ]["evidence"]["members"][0].__setitem__(
                    "executable", "/wrong/live/hfnet"
                ),
            }
            for name, mutate in passive_tampers.items():
                with self.subTest(passive_tamper=name):
                    candidate = json.loads(json.dumps(passive_receipt))
                    mutate(candidate)
                    publish_passive(candidate)
                    with self.assertRaises(ORDINAL.OrdinalError):
                        ORDINAL.validate_hfnet_watchdog_evidence(
                            root, manifest, passive_result, cell, 1
                        )

            prior = json.loads(json.dumps(proof))
            prior["observed_monotonic_ns"] = 30_000_000_000
            first_final = json.loads(json.dumps(proof))
            first_final["observed_monotonic_ns"] = 30_050_000_000
            first_final["members"][0]["state"] = "R"
            second_final = json.loads(json.dumps(proof))
            second_final["observed_monotonic_ns"] = 30_100_000_000
            second_final["members"][0]["state"] = "S"
            final_gate_evidence = {
                "classification": "LEADER_REAPED_BEFORE_SIGNAL",
                "phase": "BEFORE_KILLPG",
                "observed_at_utc": "2026-08-29T10:00:31+00:00",
                "observed_monotonic_ns": 30_120_000_000,
                "leader_returncode": -6,
                "reaped_before_next_sample": True,
                "signal_attempted": False,
                "signal_sent": False,
                "errors": [],
                "first_exact_group_proof": first_final,
                "final_exact_group_proof": second_final,
            }
            final_passive = {
                "phase": "FINAL_SIGNAL_GATE:BEFORE_KILLPG",
                "evidence": final_gate_evidence,
                "last_exact_group_snapshot": prior,
                "adjudicated_at_utc": "2026-08-29T10:00:32+00:00",
                "adjudicated_monotonic_ns": 30_130_000_000,
                "child_returncode": -6,
                "reaped_before_next_sample": True,
                "signal_attempted": False,
                "signal_sent": False,
            }
            final_passive_outcome = json.loads(json.dumps(passive_outcome))
            final_passive_outcome["last_exact_group_snapshot"] = prior
            final_passive_outcome["passive_exit_adjudication"] = final_passive
            (root / "runtime_resource_monitor.json").write_bytes(
                HFNET.canonical_json(runtime_receipt(-6, []))
            )
            final_passive_receipt = HFNET.build_zero_kf_watchdog_receipt(
                root, "case", 675, 1, 1, manifest, final_passive_outcome, -6, []
            )
            publish_passive(final_passive_receipt)
            ORDINAL.validate_hfnet_watchdog_evidence(
                root, manifest, passive_result, cell, 1
            )

            coordinated_final_tampers = {
                "proof_removed": lambda value: [
                    wrapper["evidence"].pop("final_exact_group_proof")
                    for wrapper in (
                        value["passive_exit_adjudication"],
                        value["outcome"]["passive_exit_adjudication"],
                    )
                ],
                "passive_chain_stripped": lambda value: (
                    value.__setitem__("passive_exit_adjudication", None),
                    value["outcome"].__setitem__(
                        "passive_exit_adjudication", None
                    ),
                ),
                "prior_snapshot_forged": lambda value: [
                    snapshot["members"][0].__setitem__(
                        "executable", "/wrong/live/hfnet"
                    )
                    for snapshot in (
                        value["outcome"]["last_exact_group_snapshot"],
                        value["passive_exit_adjudication"][
                            "last_exact_group_snapshot"
                        ],
                        value["outcome"]["passive_exit_adjudication"][
                            "last_exact_group_snapshot"
                        ],
                    )
                ],
            }
            for name, mutate in coordinated_final_tampers.items():
                with self.subTest(final_passive_tamper=name):
                    candidate = json.loads(json.dumps(final_passive_receipt))
                    mutate(candidate)
                    publish_passive(candidate)
                    with self.assertRaises(ORDINAL.OrdinalError):
                        ORDINAL.validate_hfnet_watchdog_evidence(
                            root, manifest, passive_result, cell, 1
                        )

            publish_passive(final_passive_receipt)
            forged_runtime = runtime_receipt(0, [])
            (root / "runtime_resource_monitor.json").write_bytes(
                HFNET.canonical_json(forged_runtime)
            )
            final_passive_receipt["pins"]["runtime_resource_monitor"] = (
                ORDINAL.identity(root / "runtime_resource_monitor.json")
            )
            publish_passive(final_passive_receipt)
            with self.assertRaises(ORDINAL.OrdinalError):
                ORDINAL.validate_hfnet_watchdog_evidence(
                    root, manifest, passive_result, cell, 1
                )

            def mutate_both_actions(value, callback):
                callback(value["watchdog_action"])
                callback(value["outcome"]["watchdog_action"])

            contradictions = {
                "watchdog_child_returncode_forged": lambda value: (
                    value.__setitem__("final_child_returncode", 0),
                    value["outcome"].__setitem__("final_child_returncode", 0),
                ),
                "outcome_sent_false": lambda value: value["outcome"].__setitem__(
                    "sigterm_sent", False
                ),
                "outcome_error_hidden": lambda value: value["outcome"][
                    "monitoring_errors"
                ].append("HIDDEN"),
                "impossible_sample_count": lambda value: value["outcome"].__setitem__(
                    "sample_count", 119
                ),
                "proof_errors_nonempty": lambda value: mutate_both_actions(
                    value,
                    lambda action_value: action_value[
                        "final_exact_group_proof"
                    ]["errors"].append("FORGED"),
                ),
                "proof_members_differ": lambda value: mutate_both_actions(
                    value,
                    lambda action_value: action_value[
                        "final_exact_group_proof"
                    ]["members"][0].__setitem__("start_ticks", 778),
                ),
                "leader_pgid_drift": lambda value: mutate_both_actions(
                    value,
                    lambda action_value: action_value[
                        "first_exact_group_proof"
                    ].__setitem__("pgid", 9999),
                ),
                "leader_cmdline_hash_drift": lambda value: mutate_both_actions(
                    value,
                    lambda action_value: action_value[
                        "first_exact_group_proof"
                    ]["members"][0].__setitem__("cmdline_sha256", "b" * 64),
                ),
                "sample_after_pre_signal": lambda value: mutate_both_actions(
                    value,
                    lambda action_value: action_value.__setitem__(
                        "sample_started_monotonic", 30.20
                    ),
                ),
                "final_proof_before_first": lambda value: mutate_both_actions(
                    value,
                    lambda action_value: action_value[
                        "final_exact_group_proof"
                    ].__setitem__("observed_monotonic_ns", 30_040_000_000),
                ),
                "final_proof_after_action_receipt": lambda value: mutate_both_actions(
                    value,
                    lambda action_value: action_value[
                        "final_exact_group_proof"
                    ].__setitem__("observed_monotonic_ns", 30_200_000_000),
                ),
                "pre_signal_after_action_receipt": lambda value: mutate_both_actions(
                    value,
                    lambda action_value: action_value.__setitem__(
                        "pre_signal_monotonic", 30.17
                    ),
                ),
                "action_scope_individual": lambda value: mutate_both_actions(
                    value,
                    lambda action_value: action_value.__setitem__(
                        "signal_scope", "INDIVIDUAL"
                    ),
                ),
                "last_sample_group_after_first_action_proof": lambda value: value[
                    "outcome"
                ]["last_exact_group_snapshot"].__setitem__(
                    "observed_monotonic_ns", 30_060_000_000
                ),
                "top_action_differs": lambda value: value["watchdog_action"].__setitem__(
                    "pre_signal_monotonic", 32.0
                ),
            }
            for name, mutate in contradictions.items():
                with self.subTest(name=name):
                    candidate = json.loads(json.dumps(receipt))
                    mutate(candidate)
                    publish(candidate)
                    with self.assertRaises(ORDINAL.OrdinalError):
                        ORDINAL.validate_hfnet_watchdog_evidence(
                            root, manifest, result, cell, 1
                        )

            forged_stdout = json.loads(json.dumps(receipt))
            stdout.write_text("ordinary output without terminal markers\n", encoding="utf-8")
            forged_stdout["pins"]["stdout"] = ORDINAL.identity(stdout)
            publish(forged_stdout)
            with self.assertRaises(ORDINAL.OrdinalError):
                ORDINAL.validate_hfnet_watchdog_evidence(
                    root, manifest, result, cell, 1
                )

            stdout.write_text(
                self.signature_lines(trajectory, [(0, 0)]), encoding="utf-8"
            )
            failed_outcome = json.loads(json.dumps(outcome))
            failed_action = failed_outcome["watchdog_action"]
            failed_action["signal_sent"] = False
            failed_action["group_sent"] = False
            failed_action["group_error"] = "ProcessLookupError:3"
            failed_action["errors"] = ["WATCHDOG_KILLPG_FAILED:3"]
            failed_outcome["sigterm_sent"] = False
            failed_outcome["monitor_proven"] = False
            failed_outcome["monitoring_errors"] = [
                "FINAL_SIGNAL_GATE:WATCHDOG_KILLPG_FAILED:3"
            ]
            failed_outcome[
                "permanently_disabled_after_unproven_evidence"
            ] = True
            (root / "runtime_resource_monitor.json").write_bytes(
                HFNET.canonical_json(runtime_receipt(-15, [failed_action]))
            )
            failed_receipt = HFNET.build_zero_kf_watchdog_receipt(
                root,
                "case",
                675,
                1,
                1,
                manifest,
                failed_outcome,
                -15,
                [],
            )
            receipt_path.write_bytes(HFNET.canonical_json(failed_receipt))
            result = {
                "pipeline_failure_codes": [
                    "ZERO_KF_POST_SHUTDOWN_WATCHDOG_UNPROVEN"
                ],
                "algorithm_failure_codes": [],
                "execution": {
                    "raw_returncode": -15,
                    "child_reaped": True,
                    "timed_out": False,
                    "supervised_process_group_empty_after_wait": True,
                },
                "runtime_resource_monitor_decision": {
                    "intrusion_detected": False,
                    "monitor_proven": True,
                    "pipeline_failure_reasons": [],
                },
                "zero_kf_post_shutdown_watchdog": ORDINAL.identity(receipt_path),
                "zero_kf_post_shutdown_watchdog_decision": {
                    "monitor_proven": False,
                    "sigterm_sent": False,
                    "retry_permitted": False,
                    "pipeline_failure_code_if_unproven": (
                        "ZERO_KF_POST_SHUTDOWN_WATCHDOG_UNPROVEN"
                    ),
                    "algorithm_failure_code_if_sent": (
                        "CONFIRMED_ZERO_KF_POST_SHUTDOWN_SAVE_HANG"
                    ),
                },
            }
            self.assertIn(
                "WATCHDOG_SIGNAL_ATTEMPT_NOT_DELIVERED",
                failed_receipt["monitoring_errors"],
            )
            self.assertEqual(
                failed_receipt["monitoring_errors"],
                failed_receipt["outcome"]["monitoring_errors"],
            )
            ORDINAL.validate_hfnet_watchdog_evidence(
                root, manifest, result, cell, 1
            )


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
        with mock.patch.object(
            RESOURCE,
            "_parse_proc_stat",
            side_effect=[{"start_ticks": 11}, {"start_ticks": 22}],
        ), mock.patch.object(
            RESOURCE.Path, "read_text", return_value="stat"
        ), mock.patch.object(
            RESOURCE.Path, "read_bytes", return_value=b""
        ), mock.patch.object(
            RESOURCE.os, "readlink", return_value="/tmp/reused"
        ):
            changed_record, changed_errors = RESOURCE._read_process_record(101)
        self.assertIsNone(changed_record)
        self.assertEqual(
            changed_errors,
            ["PROC_IDENTITY_CHANGED_DURING_READ:101:11:22"],
        )

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

        # A numeric PID from a previously owned identity is not a safe stale
        # row when /proc identity failed to read: it may already be a reused
        # external GPU process.  The row must be external and the probe must
        # be unproven.
        read_error = "PROC_STAT_READ_FAILED:101:13"
        with mock.patch.object(
            RESOURCE,
            "_read_process_record",
            return_value=(None, [read_error]),
        ):
            unreadable = RESOURCE._classify_gpu_applications(
                [applications[1]], set(), {(101, 11)}
            )
        self.assertEqual([row["pid"] for row in unreadable["external"]], [101])
        self.assertEqual(unreadable["stale_owned"], [])
        self.assertEqual(
            unreadable["external"][0]["proc_identity_read_errors"],
            [read_error],
        )

        monitor = RESOURCE.RuntimeResourceMonitor.__new__(
            RESOURCE.RuntimeResourceMonitor
        )
        monitor._lock = threading.RLock()
        monitor._active_owned = set()
        monitor._known_owned = {(101, 11)}
        monitor.pgid = 101
        with mock.patch.object(
            RESOURCE,
            "_run_gpu_compute_query",
            return_value={
                "returncode": 0,
                "stdout": "101, reused-unreadable, 10\n",
                "stderr": "",
                "error": None,
            },
        ), mock.patch.object(
            RESOURCE,
            "_read_process_record",
            return_value=(None, [read_error]),
        ):
            sample = monitor._gpu_probe(1)
        self.assertEqual(
            [row["pid"] for row in sample["external_compute_applications"]],
            [101],
        )
        self.assertIn(read_error, sample["probe_errors"])

    def test_numeric_group_reuse_and_stale_parent_scan_are_never_cleanup_owned(
        self,
    ) -> None:
        monitor = RESOURCE.RuntimeResourceMonitor.__new__(
            RESOURCE.RuntimeResourceMonitor
        )
        monitor.pid = 4242
        monitor.pgid = 4242
        monitor.leader_identity = (4242, 100)
        monitor._lock = threading.RLock()
        monitor._known_owned = {(4242, 100)}
        monitor._active_owned = set()
        monitor._monitor_errors = []
        monitor._cleanup_actions = []

        reused_leader = self._record(
            4242, 200, "/tmp/foreign-parent", pgid=4242
        )
        reused_leader["session"] = 4242
        gpu_rows = [{
            "pid": 4242,
            "process_name": "foreign",
            "used_memory_mib": "10",
            "raw": "4242, foreign, 10",
        }]
        with mock.patch.object(
            RESOURCE,
            "_read_process_record",
            return_value=(reused_leader, []),
        ):
            gpu = RESOURCE._classify_gpu_applications(
                gpu_rows,
                monitor._active_owned,
                monitor._known_owned,
                monitor.pgid,
            )
        self.assertEqual(gpu["discovered_owned_identities"], [])
        self.assertEqual(len(gpu["external"]), 1)

        stale_old_leader = self._record(
            4242, 100, "/tmp/old-owned-parent", pgid=4242
        )
        stale_old_leader["session"] = 4242
        foreign_child = self._record(
            5000,
            300,
            "/tmp/foreign-child",
            ppid=4242,
            pgid=4242,
        )
        foreign_child["session"] = 4242

        def lineage_recheck(pid):
            return (
                reused_leader if pid == 4242 else foreign_child,
                [],
            )

        monitor._active_owned = {(4242, 100)}
        with mock.patch.object(
            RESOURCE, "_read_process_record", side_effect=lineage_recheck
        ):
            observed_owned = monitor._refresh_owned(
                [stale_old_leader, foreign_child]
            )
        self.assertNotIn((5000, 300), observed_owned)
        self.assertNotIn((5000, 300), monitor._known_owned)

        with mock.patch.object(
            RESOURCE,
            "_scan_processes",
            return_value=([reused_leader, foreign_child], []),
        ), mock.patch.object(
            RESOURCE, "_read_process_record", side_effect=lineage_recheck
        ), mock.patch.object(RESOURCE.os, "killpg") as killpg, mock.patch.object(
            RESOURCE.os, "kill"
        ) as kill:
            monitor._signal_current_owned(RESOURCE.signal.SIGTERM, "reuse-test")
        killpg.assert_not_called()
        kill.assert_not_called()

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

        after_end = RESOURCE._sampling_gap_report(
            samples(200_000_000),
            0,
            100_000_000,
            RESOURCE.GPU_TARGET_INTERVAL_SECONDS,
            RESOURCE.GPU_MAX_START_GAP_SECONDS,
        )
        self.assertFalse(after_end["proven"])
        self.assertEqual(
            after_end["sample_start_contract_violations"][0]["label"],
            "probe_start_outside_coverage_interval",
        )
        out_of_order = RESOURCE._sampling_gap_report(
            samples(50_000_000, 40_000_000),
            0,
            100_000_000,
            RESOURCE.PROC_TARGET_INTERVAL_SECONDS,
            RESOURCE.PROC_MAX_START_GAP_SECONDS,
        )
        self.assertFalse(out_of_order["proven"])
        self.assertIn(
            "probe_starts_not_strictly_increasing",
            {
                row["label"]
                for row in out_of_order["sample_start_contract_violations"]
            },
        )

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
                self.assertEqual(receipt["experiment_id"], RESOURCE.EXPERIMENT_ID)
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
