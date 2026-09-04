#!/usr/bin/env python3
"""Non-model tests for the one-shot official MH01 stage-3 controller."""

import importlib.util
import json
import os
import tempfile
import unittest
from pathlib import Path


RUNNER = Path(__file__).resolve().parents[1] / "run_published_supervins_v1_official_euroc_mh01_first2s_inference_smoke_v1.py"
SPEC = importlib.util.spec_from_file_location("supervins_stage3_mh01_first2s", RUNNER)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class Stage3ControllerTests(unittest.TestCase):
    def test_node_classifier_counts_extractor_and_matcher_occurrences(self):
        result = MODULE.classify_node_output(
            b"waiting for image and imu...\nextract feature time\nextract feature time\n",
            b"[INFO] matches.size() = 123\n",
        )
        self.assertEqual(result["session_marker_count"], 1)
        self.assertEqual(result["extract_feature_time_count"], 2)
        self.assertEqual(result["matches_size_count"], 1)
        self.assertEqual(result["matches_size_values"], [123])

    def test_node_classifier_does_not_infer_matcher_without_marker(self):
        result = MODULE.classify_node_output(b"extract feature time\n" * 2, b"")
        self.assertEqual(result["extract_feature_time_count"], 2)
        self.assertEqual(result["matches_size_count"], 0)

    def test_publisher_parser_requires_json_terminal_and_camera_records(self):
        lines = [json.dumps({"event": "CAMERA_PUBLISHED", "index": index}) for index in range(2)]
        lines.append(json.dumps({"status": "PUBLISH_COMPLETE", "camera_count": 2}))
        parsed = MODULE.parse_publisher_output(("\n".join(lines) + "\n").encode())
        self.assertEqual(len(parsed["camera_records"]), 2)
        self.assertEqual(len(parsed["terminal_records"]), 1)

    def test_system_state_contract_requires_exact_node_and_publisher(self):
        response = [
            1,
            "ok",
            [
                [["/imu0", [MODULE.PUBLISHER_NODE]], ["/cam0/image_raw", [MODULE.PUBLISHER_NODE]]],
                [["/imu0", [MODULE.NODE_NAME]], ["/cam0/image_raw", [MODULE.NODE_NAME]]],
                [],
            ],
        ]
        state = {"ok": True, **MODULE.parse_system_state(response)}
        self.assertTrue(MODULE.input_connection_contract(state, publisher_required=True))
        state["input_publishers"]["/imu0"].append("/forbidden")
        self.assertFalse(MODULE.input_connection_contract(state, publisher_required=True))

    def test_system_state_contract_accepts_exact_subscribers_before_publisher(self):
        response = [
            1,
            "ok",
            [[], [["/imu0", [MODULE.NODE_NAME]], ["/cam0/image_raw", [MODULE.NODE_NAME]]], []],
        ]
        state = {"ok": True, **MODULE.parse_system_state(response)}
        self.assertTrue(MODULE.input_connection_contract(state, publisher_required=False))

    def test_exclusive_claim_is_one_shot(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "claim.json"
            MODULE.write_json_exclusive(path, {"count": 1})
            with self.assertRaises(FileExistsError):
                MODULE.write_json_exclusive(path, {"count": 2})

    def test_master_cmdline_filter_is_exact_to_attempt_port(self):
        self.assertTrue(MODULE.is_attempt_master_cmdline(["/usr/bin/python3", "/opt/ros/noetic/bin/roscore", "-p", "11553"]))
        self.assertFalse(MODULE.is_attempt_master_cmdline(["bash", "-c", "mention roscore and 11553"]))
        self.assertFalse(MODULE.is_attempt_master_cmdline(["/opt/ros/noetic/bin/roscore", "-p", "11552"]))

    def test_runtime_environment_is_isolated_to_stage3_master(self):
        with tempfile.TemporaryDirectory() as directory:
            env = MODULE.runtime_environment(Path(directory))
            self.assertEqual(env["ROS_MASTER_URI"], "http://127.0.0.1:11553")
            self.assertEqual(env["ROS_HOSTNAME"], "127.0.0.1")

    def test_protocol_discloses_non_readme_sequence_and_forbids_trajectory(self):
        protocol = MODULE.read_json(MODULE.PROTOCOL)
        self.assertFalse(protocol["sequence_boundary"]["input_is_readme_recommended_sequence"])
        self.assertTrue(protocol["claim_boundary"]["feature_extractor_inference_authorized"])
        self.assertTrue(protocol["claim_boundary"]["matcher_inference_authorized"])
        self.assertFalse(protocol["claim_boundary"]["full_vio_or_trajectory_run_authorized"])
        self.assertFalse(protocol["claim_boundary"]["ape_rpe_authorized"])
        self.assertEqual(protocol["ros"]["node_command"], MODULE.NODE_COMMAND)
        self.assertEqual(protocol["ros"]["publisher_command"], MODULE.PUBLISHER_COMMAND)

    def test_manifest_freezes_exact_counts_topics_and_types(self):
        manifest = MODULE.read_json(MODULE.INPUT_MANIFEST)
        self.assertEqual(manifest["selection"]["camera_count"], 41)
        self.assertEqual(manifest["selection"]["imu_count"], 401)
        self.assertEqual(manifest["selection"]["event_count"], 442)
        ok, observed = MODULE.topic_contract(MODULE.read_json(MODULE.PROTOCOL), manifest)
        self.assertTrue(ok, observed)


if __name__ == "__main__":
    unittest.main()
