#!/usr/bin/env python3
"""Non-model tests for fresh SuperVINS session-smoke attempt 002."""

import importlib.util
import io
import os
import pty
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path


RUNNER = Path(__file__).resolve().parents[1] / "run_published_supervins_v1_ortsession_smoke_attempt_002.py"
SPEC = importlib.util.spec_from_file_location("supervins_session_smoke_attempt_002", RUNNER)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class Attempt002ControllerTests(unittest.TestCase):
    def test_output_classifier_requires_marker_and_rejects_inference(self):
        clean = MODULE.classify_output(b"waiting for image and imu...\r\n", b"")
        self.assertEqual(clean["success_marker_count"], 1)
        self.assertEqual(clean["forbidden_inference_markers_found"], [])
        dirty = MODULE.classify_output(
            b"waiting for image and imu...\nextract feature time\n",
            b"matches.size() = 4\n",
        )
        self.assertEqual(dirty["success_marker_count"], 1)
        self.assertEqual(dirty["forbidden_inference_markers_found"], MODULE.FORBIDDEN_INFERENCE_MARKERS)

    def test_system_state_parser_accepts_empty_input_topics(self):
        response = [
            1,
            "ok",
            [
                [["/rosout", ["/rosout"]]],
                [["/rosout", ["/rosout"]]],
                [["/rosout/get_loggers", ["/rosout"]]],
            ],
        ]
        parsed = MODULE.parse_system_state(response)
        self.assertEqual(parsed["nodes"], ["/rosout"])
        self.assertEqual(parsed["input_publishers"], {})

    def test_system_state_parser_detects_input_publisher(self):
        response = [
            1,
            "ok",
            [
                [["/imu0", ["/forbidden_input"]]],
                [],
                [],
            ],
        ]
        parsed = MODULE.parse_system_state(response)
        self.assertEqual(parsed["input_publishers"], {"/imu0": ["/forbidden_input"]})

    def test_exclusive_claim_is_one_shot(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "claim.json"
            MODULE.write_json_exclusive(path, {"count": 1})
            with self.assertRaises(FileExistsError):
                MODULE.write_json_exclusive(path, {"count": 2})

    def test_pty_makes_unflushed_newline_observable(self):
        master, slave = pty.openpty()
        os.set_blocking(master, False)
        proc = subprocess.Popen(
            [sys.executable, "-c", "import time; print('waiting for image and imu...'); time.sleep(30)"],
            stdin=subprocess.DEVNULL,
            stdout=slave,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
            close_fds=True,
        )
        os.close(slave)
        sink = io.BytesIO()
        buffers = {master: bytearray()}
        streams = {master: sink}
        fds = [master]
        deadline = time.monotonic() + 2
        try:
            while time.monotonic() < deadline and MODULE.SUCCESS_MARKER.encode() not in buffers[master]:
                MODULE.drain_pty(fds, streams, buffers, 0.05)
            self.assertIn(MODULE.SUCCESS_MARKER.encode(), bytes(buffers[master]))
        finally:
            MODULE.terminate_and_reap(proc)
            try:
                os.close(master)
            except OSError:
                pass

    def test_runtime_environment_is_attempt_002_isolated(self):
        with tempfile.TemporaryDirectory() as directory:
            env = MODULE.runtime_environment(Path(directory))
            self.assertEqual(env["ROS_MASTER_URI"], "http://127.0.0.1:11552")
            self.assertEqual(env["ROS_HOSTNAME"], "127.0.0.1")

    def test_protocol_is_additive_and_forbids_inference(self):
        protocol = MODULE.read_json(MODULE.PROTOCOL)
        self.assertEqual(protocol["relationship"]["mode"], "ADDITIVE_NEW_ATTEMPT_AND_FRESH_NAMESPACE")
        self.assertFalse(protocol["relationship"]["attempt_001_modified"])
        self.assertFalse(protocol["claim_boundary"]["model_inference_authorized"])
        self.assertFalse(protocol["claim_boundary"]["ros_input_publisher_authorized"])
        self.assertEqual(protocol["pinned_node_command"], MODULE.NODE_COMMAND)


if __name__ == "__main__":
    unittest.main()
