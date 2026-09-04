#!/usr/bin/python3
"""Pure, non-ROS regression tests for fair-stability parsers and schedule gates."""

from __future__ import annotations

import importlib.util
import json
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


VINS = load("fair_vins_v3", SCRIPTS / "run_fair_stability_vins_replay_v3.py")
HFNET = load("fair_hfnet_v3", SCRIPTS / "run_fair_stability_hfnet_openloop_v3.py")
ORDINAL = load("fair_ordinal_v3", SCRIPTS / "fair_stability_ordinal_common_v3.py")
NEXT = load("fair_next_v3", SCRIPTS / "run_fair_stability_next_v3.py")
SUMMARY = load("fair_summary_v3", SCRIPTS / "summarize_fair_stability_v3.py")
RESOURCE = load(
    "fair_runtime_resource_monitor",
    SCRIPTS / "fair_stability_runtime_resource_monitor_v3.py",
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
                "schema_version": "aqua-fe-fair-stability-vins-child-start-v3",
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
                    "schema_version": "aqua-fe-fair-stability-vins-child-lifecycle-v3",
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

    def test_v3_schedule_and_pristine_attempt_matrix(self) -> None:
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
                / "vins_dev_nativeq_schedfix_runtimeexcl_v3"
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
                                "aqua-fe-fair-stability-hfnet-attempt-v3"
                                if str(cell["arm"]).startswith("hfnet_openloop_")
                                else "aqua-fe-fair-stability-vins-attempt-v3"
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
            matrix_path = root / "attempt_matrix_freeze_v3.json"
            matrix_path.write_bytes(
                ORDINAL.canonical_json(
                    {
                        "schema_version": "aqua-fe-fair-stability-attempt-matrix-freeze-v3",
                        "experiment_id": ORDINAL.EXPERIMENT_ID,
                        "status": "FROZEN_BEFORE_ANY_V3_ESTIMATOR_START",
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
            state = ORDINAL.next_state(root)
            self.assertEqual(state["state"], "READY")
            self.assertEqual(state["cell"]["ordinal"], 1)


class V3ControlRegressionTests(unittest.TestCase):
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

    CHILD = SCRIPTS / "run_fair_stability_vins_replay_child_v3.sh"

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
            "schema_version": "aqua-fe-fair-stability-hfnet-input-freeze-v3",
            "status": "FROZEN_INPUTS_NO_ESTIMATOR_STARTED",
            "experiment_id": VINS.EXPERIMENT_ID,
            "protocol": {"sha256": VINS.EXPECTED_PROTOCOL_SHA256},
            "roster": {"sha256": VINS.EXPECTED_ROSTER_SHA256},
            "historical_results": {"path": "p", "size_bytes": 1, "sha256": "h"},
            "historical_manifest": {"path": "p", "size_bytes": 1, "sha256": "h"},
            "claims": {
                "v1_results_imported": False,
                "v2_results_imported": False,
                "cross_arm_imu_semantics_exact_before_clock_normalization": True,
                "cross_vins_arm_replay_schedule_exact": True,
                "dataset_canonical_td_shared_across_windows": True,
                "available_imu_samples_and_camera_cutoff_matched": True,
                "identical_native_backend_imu_consumption_claimed": False,
            },
            "execution_controls": {},
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
                VINS, "read_csv_rows", side_effect=[roster, historical] * 3
            ), mock.patch.object(
                VINS, "load_schedule", return_value=[{}] * 120
            ), mock.patch.object(
                VINS, "identity", return_value={"path": "p", "size_bytes": 1, "sha256": "h"}
            ), mock.patch.object(VINS, "identity_matches", return_value=True):
                path.write_text(json.dumps(manifest), encoding="utf-8")
                VINS.verify_common_inputs()
                for key in ("v1_results_imported", "v2_results_imported"):
                    invalid = json.loads(json.dumps(manifest))
                    invalid["claims"][key] = True
                    path.write_text(json.dumps(invalid), encoding="utf-8")
                    with self.subTest(key=key), self.assertRaises(VINS.ContractError):
                        VINS.verify_common_inputs()

    def test_runner_summaries_delegate_to_receipt_state_machine(self) -> None:
        sentinel = {"schema_version": "receipt-validated-sentinel"}
        with mock.patch(
            "summarize_fair_stability_v3.summarize", return_value=sentinel
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
            ), mock.patch.object(NEXT, "write_exclusive") as write:
                receipt = NEXT.adjudicate_pipeline_invalid(state)
            self.assertEqual(receipt["pipeline_failure_codes"], [allowed])
            self.assertEqual(receipt["automatic_retry_policy"], "EXPLICIT_EXTERNAL_TRANSIENT_ONLY_V3")
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
                        "schema_version": "aqua-fe-fair-stability-vins-attempt-v3",
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
                        "schema_version": "aqua-fe-fair-stability-vins-result-v3",
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
                    }
                ),
                encoding="utf-8",
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
