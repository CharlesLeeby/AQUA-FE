#!/usr/bin/env python3
"""Non-model tests for the PRESTART-gated full-MH01 SuperVINS runner."""

import contextlib
import importlib.util
import io
import json
import signal
import tempfile
import unittest
from pathlib import Path
from unittest import mock


RUNNER = Path(__file__).resolve().parents[1] / "run_published_supervins_v1_official_euroc_mh01_full_trajectory_v1.py"
SPEC = importlib.util.spec_from_file_location("supervins_mh01_full_trajectory", RUNNER)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def graph_state(input_subscribers=None, input_publishers=None, trajectory_publishers=None):
    return {
        "ok": True,
        "nodes": [MODULE.NODE_NAME, "/rosout"],
        "input_subscribers": dict(input_subscribers or {}),
        "input_publishers": dict(input_publishers or {}),
        "trajectory_publishers": dict(trajectory_publishers or {}),
        "state": {"publishers": {}, "subscribers": {}, "services": {}},
    }


class FullTrajectoryPrestartTests(unittest.TestCase):
    def test_manifest_is_full_official_mh01_and_not_v2_01(self):
        manifest = MODULE.read_json(MODULE.MANIFEST)
        selection = manifest["selection"]
        self.assertEqual(selection["camera_count"], 3682)
        self.assertEqual(selection["imu_count"], 36820)
        self.assertEqual(selection["event_count"], 40502)
        self.assertEqual(selection["publish_source_time_per_wall_time"], 0.2)
        self.assertFalse(manifest["sequence_disclosure"]["selected_sequence_is_readme_recommended_v2_01"])
        self.assertFalse(manifest["boundary"]["ape_rpe_or_accuracy_authorized"])

    def test_manifest_fixes_all_four_aggregate_content_digests(self):
        manifest = MODULE.read_json(MODULE.MANIFEST)
        self.assertEqual(
            {key: value["sha256"] for key, value in manifest["selected_content_digests"].items()},
            {
                "camera_png_assets": "bfe212e7d278bd671bc9d56c43cd21415c9b7d00397e919720c7079d77673f48",
                "camera_decoded_mono8_pixels": "ed56178788ec5a15ecec996f8d24626f93a0565b2956adad3665d4edc612d11c",
                "imu_rows": "86585bd901bbd9b7e2b539eeb71fe4078d770267f8e15f47e9184582948876b7",
                "combined_events": "7ef5e4726d877202a9d56644639d65904ca657bb336055512758da1344edc5c9",
            },
        )

    def test_config_changes_only_output_path_and_both_resolutions_are_fresh(self):
        delta = MODULE.config_delta_check()
        self.assertTrue(delta["only_output_path_changed"])
        self.assertEqual(set(delta["changed"]), {"output_path"})
        self.assertTrue(delta["adapted_output_path_exact"])
        self.assertTrue(delta["both_resolve_to_trajectory_dir"])
        self.assertTrue(delta["calibration_byte_identical"])

    def test_original_calibration_identity_is_frozen_not_live_derived(self):
        protocol = MODULE.read_json(MODULE.PROTOCOL)
        calib = protocol["adapted_config"]["cam0_calibration_copy"]
        self.assertEqual(calib["original_path"], str(MODULE.ORIGINAL_CALIB))
        self.assertEqual(calib["original_sha256"], calib["sha256"])
        self.assertEqual(calib["original_size_bytes"], calib["size_bytes"])

    def test_protocol_precreates_output_directory_and_forbids_algorithm_changes(self):
        protocol = MODULE.read_json(MODULE.PROTOCOL)
        contract = protocol["output_path_resolution_contract"]
        self.assertTrue(contract["trajectory_output_directory_precreated_before_any_process_start"])
        self.assertFalse(contract["writes_outside_fresh_namespace_authorized"])
        self.assertFalse(protocol["claim_boundary"]["network_model_threshold_or_backend_change_authorized"])
        self.assertFalse(protocol["claim_boundary"]["groundtruth_consumption_authorized"])
        self.assertFalse(protocol["claim_boundary"]["ape_rpe_or_accuracy_authorized"])

    def test_system_state_parser_extracts_required_topic_owners(self):
        response = [
            1,
            "ok",
            [
                [["/imu0", [MODULE.PUBLISHER_NODE]], ["/supervins_estimator/path", [MODULE.NODE_NAME]]],
                [["/imu0", [MODULE.NODE_NAME]], ["/cam0/image_raw", [MODULE.NODE_NAME]]],
                [["/supervins_estimator/get_loggers", [MODULE.NODE_NAME]]],
            ],
        ]
        parsed = MODULE.parse_system_state(response)
        self.assertEqual(parsed["input_publishers"], {"/imu0": [MODULE.PUBLISHER_NODE]})
        self.assertEqual(parsed["input_subscribers"], {topic: [MODULE.NODE_NAME] for topic in MODULE.INPUT_TOPICS})
        self.assertEqual(parsed["trajectory_publishers"], {"/supervins_estimator/path": [MODULE.NODE_NAME]})

    def test_subscription_gate_requires_exact_node_and_no_input_publisher(self):
        subscribers = {topic: [MODULE.NODE_NAME] for topic in MODULE.INPUT_TOPICS}
        outputs = {topic: [MODULE.NODE_NAME] for topic in MODULE.OUTPUT_TOPICS}
        self.assertTrue(MODULE.subscriptions_ready(graph_state(subscribers, {}, outputs)))
        subscribers["/imu0"] = [MODULE.NODE_NAME, "/extra"]
        self.assertFalse(MODULE.subscriptions_ready(graph_state(subscribers, {}, outputs)))
        subscribers["/imu0"] = [MODULE.NODE_NAME]
        self.assertFalse(MODULE.subscriptions_ready(graph_state(subscribers, {"/imu0": ["/early"]}, outputs)))

    def test_publisher_graph_gate_requires_exact_publisher_and_trajectory_node(self):
        subscribers = {topic: [MODULE.NODE_NAME] for topic in MODULE.INPUT_TOPICS}
        publishers = {topic: [MODULE.PUBLISHER_NODE] for topic in MODULE.INPUT_TOPICS}
        outputs = {topic: [MODULE.NODE_NAME] for topic in MODULE.OUTPUT_TOPICS}
        self.assertTrue(MODULE.publisher_graph_ready(graph_state(subscribers, publishers, outputs)))
        publishers["/cam0/image_raw"] = [MODULE.PUBLISHER_NODE, "/extra"]
        self.assertFalse(MODULE.publisher_graph_ready(graph_state(subscribers, publishers, outputs)))

    def test_output_classifier_counts_coverage_initialization_and_failures(self):
        classified = MODULE.classify_node_output(
            b"waiting for image and imu...\nextract feature time\nextract feature time\nInitialization finish!\n",
            b"matches.size() = 14\nfailure detection!\nsystem reboot!\n",
        )
        self.assertEqual(classified["session_marker_count"], 1)
        self.assertEqual(classified["extract_feature_time_count"], 2)
        self.assertEqual(classified["matches_size_values"], [14])
        self.assertEqual(classified["initialization_finish_count"], 1)
        self.assertEqual(classified["failure_detection_count"], 1)
        self.assertEqual(classified["system_reboot_count"], 1)

    def test_output_classifier_freezes_full_and_even_timestamp_digests(self):
        rows = MODULE.expected_camera_rows()
        payload = "".join(f"{timestamp_ns / 1e9:.9f}\r\n" for _, timestamp_ns, _ in rows).encode("ascii")
        classified = MODULE.classify_node_output(payload, b"")
        self.assertEqual(classified["frame_timestamp_count"], 3682)
        self.assertEqual(classified["frame_timestamp_first"], MODULE.FIRST_FRAME_TIMESTAMP_TEXT)
        self.assertEqual(classified["frame_timestamp_last"], MODULE.LAST_FRAME_TIMESTAMP_TEXT)
        self.assertEqual(classified["frame_timestamp_sha256_lf"], MODULE.FRAME_TIMESTAMP_SHA256)
        self.assertEqual(classified["even_frame_timestamp_sha256_lf"], MODULE.EVEN_FRAME_TIMESTAMP_SHA256)

    def test_trajectory_audit_accepts_valid_tum_rows_and_tail_coverage(self):
        with tempfile.TemporaryDirectory() as directory:
            trajectory = Path(directory) / "vio.csv"
            end = MODULE.LAST_CAMERA_SECONDS
            trajectory.write_text(
                f"{end - 100.0:.6f} 0 0 0 0 0 0 1\n{end:.6f} 1 2 3 0 0 0 1\n",
                encoding="utf-8",
            )
            audit = MODULE.trajectory_audit(trajectory)
        self.assertEqual(audit["valid_row_count"], 2)
        self.assertTrue(audit["timestamps_strictly_increasing"])
        self.assertTrue(audit["all_values_finite"])
        self.assertTrue(audit["quaternion_norm_in_range"])
        self.assertGreaterEqual(audit["source_span_seconds"], 99.9)
        self.assertLessEqual(audit["tail_gap_seconds"], 1e-3)

    def test_trajectory_audit_rejects_nonmonotonic_nonfinite_and_bad_quaternion(self):
        with tempfile.TemporaryDirectory() as directory:
            trajectory = Path(directory) / "vio.csv"
            trajectory.write_text(
                "2 0 0 0 0 0 0 2\n2 0 0 nan 0 0 0 1\n1 0 0 0 0 0 0 1\n",
                encoding="utf-8",
            )
            audit = MODULE.trajectory_audit(trajectory)
        self.assertFalse(audit["timestamps_strictly_increasing"])
        self.assertFalse(audit["all_values_finite"])
        self.assertFalse(audit["quaternion_norm_in_range"])
        self.assertEqual(audit["invalid_lines"], [2])

    def test_trajectory_tail_gap_rejects_timestamp_after_last_camera(self):
        with tempfile.TemporaryDirectory() as directory:
            trajectory = Path(directory) / "vio.csv"
            trajectory.write_text(
                f"{MODULE.LAST_CAMERA_SECONDS + 0.1:.6f} 0 0 0 0 0 0 1\n",
                encoding="utf-8",
            )
            audit = MODULE.trajectory_audit(trajectory)
        self.assertLess(audit["tail_gap_seconds"], 0)

    def test_trajectory_membership_gate_accepts_even_camera_and_rejects_decoy(self):
        even_timestamp = MODULE.expected_camera_rows()[1][1] / 1e9
        with tempfile.TemporaryDirectory() as directory:
            trajectory = Path(directory) / "vio.csv"
            trajectory.write_text(f"{even_timestamp:.6f} 0 0 0 0 0 0 1\n", encoding="utf-8")
            accepted = MODULE.trajectory_audit(trajectory, enforce_even_camera_membership=True)
            trajectory.write_text("1.000000 0 0 0 0 0 0 1\n", encoding="utf-8")
            rejected = MODULE.trajectory_audit(trajectory, enforce_even_camera_membership=True)
        self.assertTrue(accepted["timestamps_are_even_camera_subset"])
        self.assertFalse(rejected["timestamps_are_even_camera_subset"])

    def test_trajectory_suffix_gate_requires_exact_final_even_camera(self):
        expected = MODULE.expected_even_camera_timestamp_sequence_fixed6()
        with tempfile.TemporaryDirectory() as directory:
            trajectory = Path(directory) / "vio.csv"
            trajectory.write_text(
                "".join(f"{timestamp} 0 0 0 0 0 0 1\n" for timestamp in expected[-2:]),
                encoding="utf-8",
            )
            complete = MODULE.trajectory_audit(trajectory, enforce_even_camera_membership=True)
            trajectory.write_text(f"{expected[-2]} 0 0 0 0 0 0 1\n", encoding="utf-8")
            truncated = MODULE.trajectory_audit(trajectory, enforce_even_camera_membership=True)
        self.assertTrue(complete["timestamps_are_contiguous_even_camera_suffix"])
        self.assertEqual(complete["last_timestamp_text"], MODULE.LAST_CAMERA_FIXED6_TEXT)
        self.assertFalse(truncated["timestamps_are_contiguous_even_camera_suffix"])
        self.assertNotEqual(truncated["last_timestamp_text"], MODULE.LAST_CAMERA_FIXED6_TEXT)

    def test_backend_timing_audit_requires_finite_nonnegative_rows(self):
        with tempfile.TemporaryDirectory() as directory:
            timing = Path(directory) / "backend.txt"
            timing.write_text("0.1\n0\n-1\nNaN\nnot-a-number\n", encoding="utf-8")
            audit = MODULE.count_finite_timing_rows(timing)
        self.assertEqual(audit["line_count"], 4)
        self.assertFalse(audit["all_finite_nonnegative"])
        self.assertEqual(audit["invalid_lines"], [3, 4, 5])

    def test_gpu_gate_requires_three_gib_free_and_no_compute_apps(self):
        ready_responses = [
            {"returncode": 0, "stdout": "0, NVIDIA GTX, 4096, 3380\n", "stderr": ""},
            {"returncode": 0, "stdout": "", "stderr": ""},
        ]
        with mock.patch.object(MODULE.BASE, "command", side_effect=ready_responses):
            ready = MODULE.gpu_runtime_snapshot()
        busy_responses = [
            {"returncode": 0, "stdout": "0, NVIDIA GTX, 4096, 3071\n", "stderr": ""},
            {"returncode": 0, "stdout": "42, other, 100\n", "stderr": ""},
        ]
        with mock.patch.object(MODULE.BASE, "command", side_effect=busy_responses):
            busy = MODULE.gpu_runtime_snapshot()
        self.assertTrue(ready["ready"])
        self.assertFalse(busy["ready"])

    def test_termination_attempts_cleanup_even_when_poll_diagnostic_raises(self):
        class PollFailureProcess:
            pid = 123456

            def poll(self):
                raise RuntimeError("poll-failed")

            def wait(self, timeout=None):
                return 0

        with mock.patch.object(MODULE.os, "killpg") as killpg:
            result = MODULE.terminate_and_reap(PollFailureProcess())
        killpg.assert_called_once_with(123456, MODULE.signal.SIGTERM)
        self.assertTrue(result["reaped"])
        self.assertTrue(any(event.get("event") == "POLL_DIAGNOSTIC_FAILED_ASSUME_RUNNING" for event in result["events"]))

    def test_extrinsic_audit_requires_finite_4x4_body_transform(self):
        source = MODULE.cv2.FileStorage(str(MODULE.ADAPTED_CONFIG), MODULE.cv2.FILE_STORAGE_READ)
        matrix = source.getNode("body_T_cam0").mat()
        source.release()
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "extrinsic_parameter.csv"
            storage = MODULE.cv2.FileStorage(str(output), MODULE.cv2.FILE_STORAGE_WRITE)
            storage.write("body_T_cam0", matrix)
            storage.release()
            audit = MODULE.extrinsic_audit(output)
        self.assertGreater(audit["size_bytes"], 0)
        self.assertEqual(audit["body_T_cam0_shape"], [4, 4])
        self.assertTrue(audit["all_values_finite"])
        self.assertTrue(audit["is_finite_se3"])

    def test_extrinsic_audit_rejects_zero_rotation_and_reflection(self):
        source = MODULE.cv2.FileStorage(str(MODULE.ADAPTED_CONFIG), MODULE.cv2.FILE_STORAGE_READ)
        matrix = source.getNode("body_T_cam0").mat()
        source.release()
        zero_rotation = matrix * 0
        zero_rotation[3, 3] = 1
        reflection = matrix.copy()
        reflection[:3, 0] *= -1
        audits = []
        with tempfile.TemporaryDirectory() as directory:
            for index, candidate in enumerate((zero_rotation, reflection)):
                output = Path(directory) / f"extrinsic_{index}.yaml"
                storage = MODULE.cv2.FileStorage(str(output), MODULE.cv2.FILE_STORAGE_WRITE)
                storage.write("body_T_cam0", candidate)
                storage.release()
                audits.append(MODULE.extrinsic_audit(output))
        self.assertFalse(audits[0]["is_finite_se3"])
        self.assertAlmostEqual(audits[0]["rotation_determinant"], 0.0)
        self.assertFalse(audits[1]["is_finite_se3"])
        self.assertLess(audits[1]["rotation_determinant"], 0.0)

    def test_exclusive_start_claim_cannot_be_reused(self):
        with tempfile.TemporaryDirectory() as directory:
            claim = Path(directory) / "claim.json"
            MODULE.write_json_exclusive(claim, {"start_count": 1})
            with self.assertRaises(FileExistsError):
                MODULE.write_json_exclusive(claim, {"start_count": 2})

    def test_master_process_filter_is_fixed_to_port_11555(self):
        self.assertTrue(MODULE.is_master_cmdline(["/usr/bin/python3", "/opt/ros/noetic/bin/roscore", "-p", "11555"]))
        self.assertFalse(MODULE.is_master_cmdline(["/usr/bin/python3", "/opt/ros/noetic/bin/roscore", "-p", "11554"]))
        self.assertFalse(MODULE.is_master_cmdline(["bash", "-c", "roscore 11555"]))

    def test_continuous_graph_monitor_records_midrun_identity_loss(self):
        subscribers = {topic: [MODULE.NODE_NAME] for topic in MODULE.INPUT_TOPICS}
        publishers = {topic: [MODULE.PUBLISHER_NODE] for topic in MODULE.INPUT_TOPICS}
        outputs = {topic: [MODULE.NODE_NAME] for topic in MODULE.OUTPUT_TOPICS}
        monitor = MODULE.new_graph_monitor()
        self.assertTrue(MODULE.update_graph_monitor(monitor, graph_state(subscribers, publishers, outputs), True, True))
        publishers["/imu0"] = ["/wrong"]
        self.assertFalse(MODULE.update_graph_monitor(monitor, graph_state(subscribers, publishers, outputs), True, True))
        self.assertEqual(monitor["sample_count"], 2)
        self.assertEqual(monitor["identity_violation_count"], 1)

    def test_continuous_graph_monitor_records_early_node_exit(self):
        subscribers = {topic: [MODULE.NODE_NAME] for topic in MODULE.INPUT_TOPICS}
        publishers = {topic: [MODULE.PUBLISHER_NODE] for topic in MODULE.INPUT_TOPICS}
        outputs = {topic: [MODULE.NODE_NAME] for topic in MODULE.OUTPUT_TOPICS}
        monitor = MODULE.new_graph_monitor()
        self.assertFalse(MODULE.update_graph_monitor(monitor, graph_state(subscribers, publishers, outputs), True, False))
        self.assertEqual(monitor["process_liveness_violation_count"], 1)

    def test_quiescence_requires_unchanged_snapshot_for_full_interval(self):
        snapshot, since, complete = MODULE.update_quiescence(None, None, (1841, 100, 900, 200), 5.0)
        self.assertFalse(complete)
        snapshot, since, complete = MODULE.update_quiescence(snapshot, since, (1841, 100, 900, 200), 5.9)
        self.assertFalse(complete)
        snapshot, since, complete = MODULE.update_quiescence(snapshot, since, (1841, 100, 900, 200), 6.0)
        self.assertTrue(complete)
        _, reset_since, reset_complete = MODULE.update_quiescence(snapshot, since, (1841, 101, 901, 210), 6.1)
        self.assertFalse(reset_complete)
        self.assertEqual(reset_since, 6.1)

    def test_correct_run_token_still_blocks_before_preflight_without_root_authority(self):
        with tempfile.TemporaryDirectory() as directory:
            absent = Path(directory) / "authority.json"
            with mock.patch.object(MODULE, "AUTHORITY", absent), mock.patch.object(
                MODULE.subprocess, "Popen", side_effect=AssertionError("process start forbidden")
            ):
                stdout = io.StringIO()
                with contextlib.redirect_stdout(stdout):
                    return_code = MODULE.run_once(MODULE.AUTHORIZATION_TOKEN)
        self.assertEqual(return_code, 3)
        result = json.loads(stdout.getvalue())
        self.assertEqual(result["status"], "BLOCKED_ROOT_EXECUTION_AUTHORITY_ABSENT_OR_INVALID_NO_START")

    def test_exception_after_namespace_ownership_persists_terminal_closeout_without_process_start(self):
        with tempfile.TemporaryDirectory() as directory:
            evidence = Path(directory) / "evidence"
            attempt = evidence / "attempt_001"

            def fail_after_ownership(_token):
                evidence.mkdir()
                attempt.mkdir()
                MODULE.RUN_GUARD_STATE["namespace_owned"] = True
                raise RuntimeError("injected-controller-failure")

            stdout = io.StringIO()
            with mock.patch.object(MODULE, "EVIDENCE", evidence), mock.patch.object(MODULE, "ATTEMPT", attempt), mock.patch.object(
                MODULE, "_run_once_impl", side_effect=fail_after_ownership
            ), contextlib.redirect_stdout(stdout):
                return_code = MODULE.run_once(MODULE.AUTHORIZATION_TOKEN)
            result = json.loads((attempt / "run_result.json").read_text(encoding="utf-8"))
        self.assertEqual(return_code, 5)
        self.assertEqual(result["status"], "FAIL_CONTROLLER_EXCEPTION_TERMINAL_NO_RETRY")
        self.assertEqual(result["authorization"]["roscore_start_count"], 0)
        self.assertIn("injected-controller-failure", result["exception"]["message"])

    def test_error_after_terminal_commit_preserves_single_run_result(self):
        with tempfile.TemporaryDirectory() as directory:
            evidence = Path(directory) / "evidence"
            attempt = evidence / "attempt_001"
            evidence.mkdir()
            attempt.mkdir()
            run_result = attempt / "run_result.json"
            run_result.write_text('{"status":"PASS_TEST","return_code":0}\n', encoding="utf-8")

            def fail_after_commit(_token):
                MODULE.RUN_GUARD_STATE["namespace_owned"] = True
                MODULE.RUN_GUARD_STATE["terminal_result_committed"] = True
                MODULE.RUN_GUARD_STATE["terminal_return_code"] = 0
                raise BrokenPipeError("injected-after-commit")

            with mock.patch.object(MODULE, "EVIDENCE", evidence), mock.patch.object(MODULE, "ATTEMPT", attempt), mock.patch.object(
                MODULE, "_run_once_impl", side_effect=fail_after_commit
            ), contextlib.redirect_stdout(io.StringIO()):
                return_code = MODULE.run_once(MODULE.AUTHORIZATION_TOKEN)
            names = sorted(path.name for path in attempt.iterdir())
        self.assertEqual(return_code, 0)
        self.assertEqual(names, ["run_result.json"])

    def test_controlled_sigterm_path_closes_owned_namespace_and_restores_handlers(self):
        with tempfile.TemporaryDirectory() as directory:
            evidence = Path(directory) / "evidence"
            attempt = evidence / "attempt_001"
            old_handler = signal.getsignal(signal.SIGTERM)

            def terminate_after_ownership(_token):
                evidence.mkdir()
                attempt.mkdir()
                MODULE.RUN_GUARD_STATE["namespace_owned"] = True
                MODULE.raise_controlled_termination(signal.SIGTERM, None)
                MODULE.raise_if_termination_pending()

            with mock.patch.object(MODULE, "EVIDENCE", evidence), mock.patch.object(MODULE, "ATTEMPT", attempt), mock.patch.object(
                MODULE, "_run_once_impl", side_effect=terminate_after_ownership
            ), contextlib.redirect_stdout(io.StringIO()):
                return_code = MODULE.run_once(MODULE.AUTHORIZATION_TOKEN)
            result = json.loads((attempt / "run_result.json").read_text(encoding="utf-8"))
            restored_handler = signal.getsignal(signal.SIGTERM)
        self.assertEqual(return_code, 5)
        self.assertEqual(result["status"], "FAIL_CONTROLLER_EXCEPTION_TERMINAL_NO_RETRY")
        self.assertEqual(result["exception"]["type"], "ControlledTermination")
        self.assertIn("SIGTERM", result["exception"]["message"])
        self.assertEqual(restored_handler, old_handler)

    def test_signal_in_root_mkdir_to_owned_window_still_persists_terminal_result(self):
        with tempfile.TemporaryDirectory() as directory:
            evidence = Path(directory) / "evidence"
            attempt = evidence / "attempt_001"

            class SignalingRoot:
                def mkdir(self, **_kwargs):
                    evidence.mkdir()
                    MODULE.raise_controlled_termination(signal.SIGTERM, None)

            def terminate_in_ownership_window(_token):
                MODULE.create_owned_evidence_root(SignalingRoot())

            with mock.patch.object(MODULE, "EVIDENCE", evidence), mock.patch.object(MODULE, "ATTEMPT", attempt), mock.patch.object(
                MODULE, "_run_once_impl", side_effect=terminate_in_ownership_window
            ), contextlib.redirect_stdout(io.StringIO()):
                return_code = MODULE.run_once(MODULE.AUTHORIZATION_TOKEN)
            result = json.loads((attempt / "run_result.json").read_text(encoding="utf-8"))
        self.assertEqual(return_code, 5)
        self.assertTrue(result["authorization"]["retry_authorized"] is False)
        self.assertEqual(result["exception"]["type"], "ControlledTermination")

    def test_signal_in_each_popen_return_registration_window_tracks_process_before_raise(self):
        class FakeProcess:
            pid = 123456

            def poll(self):
                return 0

            def wait(self, timeout=None):
                return 0

        mappings = (
            ("roscore", "roscore_start_count"),
            ("node", "node_start_count"),
            ("publisher", "publisher_start_count"),
        )
        for process_name, count_key in mappings:
            with self.subTest(process_name=process_name):
                fake = FakeProcess()
                for key in MODULE.ACTIVE_PROCESSES:
                    MODULE.ACTIVE_PROCESSES[key] = None
                MODULE.RUN_GUARD_STATE["starts"] = {
                    "roscore_start_count": 0, "node_start_count": 0, "publisher_start_count": 0,
                }
                MODULE.TERMINATION_SIGNAL_STATE.update({"in_progress": False, "pending_signum": None})

                def popen_with_signal(*_args, **_kwargs):
                    MODULE.raise_controlled_termination(signal.SIGTERM, None)
                    return fake

                with mock.patch.object(MODULE.subprocess, "Popen", side_effect=popen_with_signal):
                    with self.assertRaises(MODULE.ControlledTermination):
                        MODULE.tracked_popen(process_name, count_key, ["fake"])
                self.assertIs(MODULE.ACTIVE_PROCESSES[process_name], fake)
                self.assertEqual(MODULE.RUN_GUARD_STATE["starts"][count_key], 1)
                cleanup = MODULE.terminate_and_reap(MODULE.ACTIVE_PROCESSES[process_name])
                self.assertTrue(cleanup["reaped"])
        MODULE.TERMINATION_SIGNAL_STATE.update({"in_progress": False, "pending_signum": None})

    def test_post_pin_audit_uses_prestart_snapshot_and_detects_mutation(self):
        special_paths = {
            "protocol": MODULE.PROTOCOL,
            "lock": MODULE.LOCK,
            "authority": MODULE.AUTHORITY,
            "runner": MODULE.RUNNER_PATH,
            "tests": MODULE.TESTS,
            "publisher": MODULE.PUBLISHER,
            "input_manifest": MODULE.MANIFEST,
            "adapted_config": MODULE.ADAPTED_CONFIG,
            "adapted_calibration": MODULE.ADAPTED_CALIB,
        }
        with tempfile.TemporaryDirectory() as directory:
            mutable = Path(directory) / "frozen.bin"
            mutable.write_bytes(b"before")
            preflight = {
                "frozen_pin_snapshot": {str(mutable): MODULE.file_identity(mutable)},
                "special_identity_snapshot": {
                    key: MODULE.file_identity(path) if path.exists() else None for key, path in special_paths.items()
                },
            }
            mutable.write_bytes(b"after")
            audit = MODULE.post_pin_audit(preflight)
        self.assertFalse(audit[str(mutable)]["ok"])
        self.assertEqual(audit[str(mutable)]["expected"]["sha256"], MODULE.hashlib.sha256(b"before").hexdigest())

    def test_malformed_execution_authority_never_authorizes_start(self):
        with tempfile.TemporaryDirectory() as directory:
            authority = Path(directory) / "authority.json"
            lock = Path(directory) / "lock.json"
            authority.write_text("{}\n", encoding="utf-8")
            lock.write_text("{}\n", encoding="utf-8")
            with mock.patch.object(MODULE, "AUTHORITY", authority), mock.patch.object(MODULE, "LOCK", lock):
                valid, observed = MODULE.validate_execution_authority()
        self.assertFalse(valid)
        self.assertTrue(observed["exists"])

    def test_fresh_namespace_and_execution_authority_are_absent_at_prestart(self):
        self.assertFalse(MODULE.EVIDENCE.exists())
        self.assertFalse(MODULE.AUTHORITY.exists())
        self.assertEqual(MODULE.MASTER_COMMAND, ["/opt/ros/noetic/bin/roscore", "-p", "11555"])
        self.assertEqual(MODULE.BACKEND_COUNT, MODULE.CAMERA_COUNT // 2)


if __name__ == "__main__":
    unittest.main()
