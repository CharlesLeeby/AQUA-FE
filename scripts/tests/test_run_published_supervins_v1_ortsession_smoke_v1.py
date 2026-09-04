#!/usr/bin/env python3
"""Non-model unit tests for the SuperVINS OrtSession smoke controller."""

import importlib.util
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


RUNNER = Path(__file__).resolve().parents[1] / "run_published_supervins_v1_ortsession_smoke_v1.py"
SPEC = importlib.util.spec_from_file_location("supervins_session_smoke_runner", RUNNER)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class SessionSmokeControllerTests(unittest.TestCase):
    def test_marker_without_inference_is_accepted(self):
        result = MODULE.classify_output("", "[WARN] waiting for image and imu...\n")
        self.assertEqual(result["success_marker_count"], 1)
        self.assertEqual(result["forbidden_inference_markers_found"], [])

    def test_inference_markers_are_rejected(self):
        result = MODULE.classify_output(
            "extract feature time\nmatches.size() = 42\n",
            "waiting for image and imu...\n",
        )
        self.assertEqual(result["success_marker_count"], 1)
        self.assertEqual(
            result["forbidden_inference_markers_found"],
            ["extract feature time", "matches.size()"],
        )

    def test_exclusive_json_claim_cannot_be_reused(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "claim.json"
            identity = MODULE.write_json_exclusive(path, {"start": 1})
            self.assertEqual(identity, MODULE.file_identity(path))
            with self.assertRaises(FileExistsError):
                MODULE.write_json_exclusive(path, {"start": 2})

    def test_runtime_environment_uses_unbound_isolated_master(self):
        with tempfile.TemporaryDirectory() as directory:
            env = MODULE.runtime_environment(Path(directory))
            self.assertEqual(env["ROS_MASTER_URI"], "http://127.0.0.1:11551")
            self.assertEqual(env["ROS_HOSTNAME"], "127.0.0.1")
            self.assertNotIn("ROS_NAMESPACE", env)
            self.assertIn(str(MODULE.ORT / "lib"), env["LD_LIBRARY_PATH"])

    def test_termination_kills_process_group_and_reaps(self):
        old_grace = MODULE.TERM_GRACE_SECONDS
        MODULE.TERM_GRACE_SECONDS = 0.15
        proc = subprocess.Popen(
            [
                sys.executable,
                "-c",
                (
                    "import signal,time; "
                    "signal.signal(signal.SIGTERM, signal.SIG_IGN); "
                    "print('READY', flush=True); time.sleep(30)"
                ),
            ],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
            text=True,
        )
        try:
            self.assertEqual(proc.stdout.readline().strip(), "READY")
            outcome = MODULE.terminate_and_reap(proc)
            self.assertTrue(outcome["reaped"])
            self.assertTrue(outcome["sigkill_used"])
            self.assertIsNotNone(proc.returncode)
            with self.assertRaises(ProcessLookupError):
                os.kill(proc.pid, 0)
        finally:
            MODULE.TERM_GRACE_SECONDS = old_grace
            if proc.poll() is None:
                os.killpg(proc.pid, 9)
                proc.wait()
            if proc.stdout is not None:
                proc.stdout.close()

    def test_protocol_forbids_inference_and_data(self):
        protocol, pins = MODULE.load_protocol_and_pins()
        boundary = protocol["claim_boundary"]
        self.assertTrue(boundary["ort_session_construction_authorized"])
        self.assertFalse(boundary["model_inference_authorized"])
        self.assertFalse(boundary["ros_data_consumption_authorized"])
        self.assertFalse(boundary["ros_data_publication_authorized"])
        self.assertEqual(protocol["pinned_command"], MODULE.COMMAND)
        self.assertGreaterEqual(len(pins), 10)


if __name__ == "__main__":
    unittest.main()
