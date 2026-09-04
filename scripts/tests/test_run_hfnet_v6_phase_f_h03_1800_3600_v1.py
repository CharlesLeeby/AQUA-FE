#!/usr/bin/env python3
"""Non-model tests for the dedicated Phase-F H03 one-shot runner."""

import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock


RUNNER = Path(__file__).resolve().parents[1] / "run_hfnet_v6_phase_f_h03_1800_3600_v1.py"
SPEC = importlib.util.spec_from_file_location("phase_f_h03_runner", str(RUNNER))
assert SPEC is not None and SPEC.loader is not None
runner = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = runner
SPEC.loader.exec_module(runner)


def base_config():
    return "\n".join(
        (
            '%YAML:1.0',
            'Camera.type: "KannalaBrandt8"',
            'Camera.width: 640',
            'Camera.height: 512',
            'IMU.NoiseGyro: 0.001',
            'IMU.NoiseAcc: 0.02',
            'IMU.GyroWalk: 0.00005',
            'IMU.AccWalk: 0.001',
            'IMU.Frequency: 200.0',
            'Extractor.type: "HFNetRT"',
            runner.BASE_MODEL_PATH_LINE,
            'Extractor.scaleFactor: 1.2',
            'Extractor.nLevels: 4',
            'Extractor.nFeatures: 675',
            'Extractor.threshold: 0.01',
            'loopClosing: 1',
            '',
        )
    )


class PhaseFRunnerTests(unittest.TestCase):
    def test_canonical_json_and_o_excl_no_clobber(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "claim.json"
            runner.write_exclusive(path, runner.canonical_json({"b": 2, "a": 1}))
            self.assertEqual(path.read_bytes(), b'{\n  "a": 1,\n  "b": 2\n}\n')
            with self.assertRaises(FileExistsError):
                runner.write_exclusive(path, b"replacement")
            self.assertEqual(json.loads(path.read_text()), {"a": 1, "b": 2})

    def test_runtime_config_changes_exactly_model_path(self):
        target = Path("/tmp/fresh attempt/HFNet-RT")
        derived = runner.derive_runtime_config(base_config(), target)
        before = base_config().splitlines()
        after = derived.splitlines()
        changed = [index for index, pair in enumerate(zip(before, after)) if pair[0] != pair[1]]
        self.assertEqual(changed, [10])
        self.assertIn('Extractor.modelPath: "/tmp/fresh attempt/HFNet-RT/"', derived)
        self.assertIn('Camera.type: "KannalaBrandt8"', derived)
        self.assertIn('IMU.Frequency: 200.0', derived)

    def test_runtime_config_rejects_ambiguous_source(self):
        with self.assertRaises(runner.ContractError):
            runner.derive_runtime_config(base_config() + runner.BASE_MODEL_PATH_LINE + "\n", Path("/tmp/model"))

    def test_contiguous_window_metrics(self):
        metrics = runner._contiguous_metrics([899, 900, 901, 904, 905], 900, 1800)
        self.assertEqual(metrics["count"], 4)
        self.assertEqual(metrics["longest_contiguous_run"], 2)
        self.assertEqual(metrics["gap_count"], 1)
        self.assertEqual(metrics["gaps"][0]["missing_count"], 2)

    def test_trajectory_reports_preroll_score_and_continuity(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "trajectory.txt"
            stamps = [1_500_000_000_000_000_000 + index * 50_000_000 for index in range(runner.CAMERA_COUNT)]
            rows = ["%d 0 0 0 0 0 0 1" % stamp for stamp in stamps]
            path.write_text("\n".join(rows) + "\n", encoding="ascii")
            result = runner.parse_trajectory(path, stamps, keyframes=False)
            self.assertTrue(result["valid"])
            self.assertEqual(result["pose_count"], runner.CAMERA_COUNT)
            self.assertEqual(result["preroll"]["count"], 900)
            self.assertEqual(result["score"]["count"], 901)
            self.assertEqual(result["score"]["longest_contiguous_run"], 901)
            self.assertEqual(result["association_max_abs_error_ns"], 0)

    def test_trajectory_rejects_bad_quaternion(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "trajectory.txt"
            stamp = 1_500_000_000_000_000_000
            path.write_text("%d 0 0 0 0 0 0 2\n" % stamp, encoding="ascii")
            result = runner.parse_trajectory(path, [stamp], keyframes=False)
            self.assertFalse(result["valid"])
            self.assertIn("QUATERNION", result["errors"][0])

    def test_wrong_token_cannot_claim_or_launch(self):
        with tempfile.TemporaryDirectory() as directory:
            spec = runner.replace(runner.DEFAULT_SPEC, attempt=Path(directory) / "attempt")
            with mock.patch.object(runner, "check") as checked, mock.patch.object(runner, "launch_once") as launched:
                result = runner.run(spec, authorization_token="wrong")
            self.assertEqual(result["status"], "RUN_NOT_AUTHORIZED")
            checked.assert_not_called()
            launched.assert_not_called()
            self.assertFalse(spec.start_claim.exists())

    def test_prepare_is_atomic_and_unstarted(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            onnx = root / "shared.onnx"
            cache = root / "shared.cache"
            config = root / "base.yaml"
            onnx.write_bytes(b"onnx-bytes")
            cache.write_bytes(b"cache-bytes")
            config.write_text(base_config(), encoding="utf-8")
            spec = runner.replace(
                runner.DEFAULT_SPEC,
                onnx=onnx,
                cache=cache,
                config=config,
                attempt=root / "logs/fresh/attempt_001",
            )
            decision = {
                "ready": True,
                "profile": {"test_profile": True},
            }
            with mock.patch.object(runner, "preflight", return_value=decision):
                result = runner.prepare(spec)
            self.assertEqual(result["status"], "PREPARED_UNSTARTED_FRESH_ATTEMPT_001")
            self.assertEqual(runner._attempt_files(spec), runner._prepared_allowed())
            self.assertFalse(spec.start_claim.exists())
            self.assertFalse(spec.result_dir.exists())
            manifest = runner.read_canonical_json(spec.prepared_manifest)
            self.assertEqual(manifest["launch"]["maximum_popen_invocations"], 1)
            self.assertFalse(manifest["launch"]["retry"])

    def test_prepare_failure_cleans_owned_staging_and_leaves_target_absent(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            onnx = root / "shared.onnx"
            cache = root / "shared.cache"
            config = root / "base.yaml"
            onnx.write_bytes(b"onnx")
            cache.write_bytes(b"cache")
            config.write_text(base_config(), encoding="utf-8")
            spec = runner.replace(
                runner.DEFAULT_SPEC,
                onnx=onnx,
                cache=cache,
                config=config,
                attempt=root / "logs/fresh/attempt_001",
            )
            with mock.patch.object(runner, "preflight", return_value={"ready": True, "profile": {}}), mock.patch.object(
                runner.shutil, "copyfile", side_effect=OSError("injected copy failure")
            ):
                result = runner.prepare(spec)
            self.assertEqual(result["status"], "PREPARE_BLOCKED")
            self.assertFalse(spec.attempt.exists())
            parent = spec.attempt.parent
            self.assertEqual(list(parent.glob(".attempt_001.prepare.*")), [])

    def test_launch_once_invokes_popen_once_and_reaps_timeout(self):
        class FakeProcess:
            pid = 424242

            def __init__(self):
                self.calls = 0
                self.returncode = None

            def wait(self, timeout=None):
                self.calls += 1
                if self.calls == 1:
                    raise subprocess.TimeoutExpired("fake", timeout)
                self.returncode = -15
                return self.returncode

            def poll(self):
                return self.returncode

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            attempt = root / "attempt_001"
            attempt.mkdir()
            spec = runner.replace(runner.DEFAULT_SPEC, attempt=attempt, timeout_seconds=1)
            fake = FakeProcess()
            with mock.patch.object(runner.subprocess, "Popen", return_value=fake) as popen, mock.patch.object(
                runner.os, "killpg"
            ) as killpg:
                execution = runner.launch_once(spec)
            self.assertEqual(popen.call_count, 1)
            self.assertEqual(killpg.call_count, 1)
            self.assertTrue(execution.process_started)
            self.assertTrue(execution.timed_out)
            self.assertTrue(execution.synchronously_reaped)
            self.assertEqual(execution.popen_invocations, 1)
            self.assertEqual(execution.termination_signals, ("SIGTERM",))

    def test_warning_summary_is_bounded(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "stderr.log"
            path.write_text("\n".join(["WARNING CUDA failed"] * 20) + "\n", encoding="utf-8")
            summary = runner.summarize_warnings(path)
            self.assertEqual(summary["patterns"]["warning"]["count"], 20)
            self.assertEqual(len(summary["patterns"]["warning"]["examples"]), 10)
            self.assertTrue(summary["patterns"]["warning"]["examples_truncated"])


if __name__ == "__main__":
    unittest.main()
