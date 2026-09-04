#!/usr/bin/env python3
"""Non-model tests for the A06 exact-window HFNet one-shot wrapper."""

import importlib.util
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock


RUNNER = Path(__file__).resolve().parents[1] / "run_hfnet_v6_a06_0000_2460_exact_window_v1.py"
SPEC = importlib.util.spec_from_file_location("hfnet_v6_a06_exact_window_runner", str(RUNNER))
assert SPEC is not None and SPEC.loader is not None
runner = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = runner
SPEC.loader.exec_module(runner)


def base_config():
    return "\n".join(
        (
            "%YAML:1.0",
            'Camera.type: "PinHole"',
            "Camera.width: 968",
            "Camera.height: 608",
            "Camera.fps: 20",
            "IMU.NoiseGyro: 0.003",
            "IMU.NoiseAcc: 0.05",
            "IMU.GyroWalk: 0.0001",
            "IMU.AccWalk: 0.0015",
            "IMU.Frequency: 200.0",
            'Extractor.type: "HFNetRT"',
            runner.BASE_MODEL_PATH_LINE,
            "Extractor.scaleFactor: 1.2",
            "Extractor.nLevels: 4",
            "Extractor.nFeatures: 675",
            "Extractor.threshold: 0.01",
            "loopClosing: 1",
            "",
        )
    )


class A06ExactWindowRunnerTests(unittest.TestCase):
    def test_reused_engine_identity_is_exact(self):
        self.assertEqual(runner.engine.content_identity(runner.ENGINE), runner.ENGINE_EXPECTED)

    def test_a06_window_and_gates_are_frozen(self):
        self.assertEqual(runner.CAMERA_COUNT, 2461)
        self.assertEqual((runner.PREROLL_FIRST_INDEX, runner.PREROLL_LAST_INDEX), (0, 2209))
        self.assertEqual((runner.SCORE_FIRST_INDEX, runner.SCORE_LAST_INDEX), (2210, 2460))
        self.assertEqual(runner.MIN_LAST_CAMERA_INDEX, 2210)
        self.assertEqual(runner.MIN_SCORE_POSES, 20)
        self.assertEqual(runner.MIN_CONTIGUOUS_SCORE_POSES, 20)
        self.assertEqual(runner.MIN_SCORE_KEYFRAMES, 1)

    def test_runtime_config_changes_model_path_only(self):
        target = Path("/tmp/a06 exact attempt/HFNet-RT")
        before = base_config()
        after = runner.derive_runtime_config(before, target)
        changed = [
            index
            for index, rows in enumerate(zip(before.splitlines(), after.splitlines()))
            if rows[0] != rows[1]
        ]
        self.assertEqual(changed, [11])
        self.assertIn('Extractor.modelPath: "/tmp/a06 exact attempt/HFNet-RT/"', after)
        self.assertIn('Camera.type: "PinHole"', after)
        self.assertIn("IMU.NoiseGyro: 0.003", after)

    def test_runtime_config_rejects_algorithm_drift(self):
        with self.assertRaises(runner.ContractError):
            runner.derive_runtime_config(base_config().replace("Extractor.nFeatures: 675", "Extractor.nFeatures: 800"), Path("/tmp/model"))

    def test_gpu_gate_requires_three_gib_and_zero_compute_apps(self):
        good_memory = SimpleNamespace(returncode=0, stdout="4096, 800, 3296\n", stderr="")
        no_apps = SimpleNamespace(returncode=0, stdout="", stderr="")
        with mock.patch.object(runner.subprocess, "run", side_effect=[good_memory, no_apps]):
            value = runner._query_gpu_resource_gate()
        self.assertTrue(value["ready"])
        low_memory = SimpleNamespace(returncode=0, stdout="4096, 1500, 2596\n", stderr="")
        one_app = SimpleNamespace(returncode=0, stdout="4242, python3, 128\n", stderr="")
        with mock.patch.object(runner.subprocess, "run", side_effect=[low_memory, one_app]):
            value = runner._query_gpu_resource_gate()
        self.assertFalse(value["ready"])
        self.assertIn("GPU_COMPUTE_APPLICATION_PRESENT", value["errors"])
        self.assertIn("GPU_FREE_MEMORY_BELOW_3072_MIB", value["errors"])

    def test_wrong_token_cannot_check_claim_or_launch(self):
        with tempfile.TemporaryDirectory() as directory:
            spec = runner.replace(runner.DEFAULT_SPEC, attempt=Path(directory) / "attempt_001")
            with mock.patch.object(runner.engine, "check") as checked, mock.patch.object(runner.engine, "launch_once") as launched:
                result = runner.run(spec, authorization_token="wrong")
            self.assertEqual(result["status"], "RUN_NOT_AUTHORIZED")
            checked.assert_not_called()
            launched.assert_not_called()
            self.assertFalse(spec.start_claim.exists())

    def test_o_excl_no_clobber_is_inherited(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "claim.json"
            runner.write_exclusive(path, runner.canonical_json({"b": 2, "a": 1}))
            with self.assertRaises(FileExistsError):
                runner.write_exclusive(path, b"replacement")
            self.assertEqual(json.loads(path.read_text()), {"a": 1, "b": 2})

    def test_execution_lock_adds_engine_wrapper_and_resource_gate(self):
        prepared = {
            "profile": {
                "preparation_and_stack": {
                    "identities": {
                        "reused_h03_engine": {"path": str(runner.ENGINE), **runner.ENGINE_EXPECTED},
                        "a06_wrapper": {"path": str(runner.WRAPPER), "size_bytes": 1, "sha256": "abc"},
                    }
                }
            }
        }
        with mock.patch.object(runner, "_base_build_execution_lock", return_value={"claim_boundary": {}}):
            value = runner.build_execution_lock(runner.DEFAULT_SPEC, prepared, "2026-01-01T00:00:00+00:00")
        self.assertEqual(value["reused_h03_engine"]["sha256"], runner.ENGINE_EXPECTED["sha256"])
        self.assertEqual(value["resource_gate"]["minimum_gpu_free_mib"], 3072)
        self.assertTrue(value["claim_boundary"]["development_exposed_window"])

    def test_score_continuity_metrics_use_exact_relative_window(self):
        value = runner._contiguous_metrics([2209, 2210, 2211, 2214], 2210, 2460)
        self.assertEqual(value["count"], 3)
        self.assertEqual(value["longest_contiguous_run"], 2)
        self.assertEqual(value["gap_count"], 1)


if __name__ == "__main__":
    unittest.main()
