#!/usr/bin/env python3
"""Non-model tests for the H07 exact-window one-shot controller."""

import importlib.util
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock


RUNNER = Path(__file__).resolve().parents[1] / "run_hfnet_v6_h07_0001_1720_exact_window_v1.py"
SPEC = importlib.util.spec_from_file_location("hfnet_v6_h07_exact_window_runner", str(RUNNER))
assert SPEC is not None and SPEC.loader is not None
runner = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = runner
SPEC.loader.exec_module(runner)


def base_config() -> str:
    return "\n".join((
        "%YAML:1.0",
        'Camera.type: "KannalaBrandt8"',
        "Camera.width: 640",
        "Camera.height: 512",
        "Camera.fps: 20",
        "IMU.NoiseGyro: 0.001",
        "IMU.NoiseAcc: 0.02",
        "IMU.GyroWalk: 0.00005",
        "IMU.AccWalk: 0.001",
        "IMU.Frequency: 200.0",
        'Extractor.type: "HFNetRT"',
        runner.BASE_MODEL_PATH_LINE,
        "Extractor.scaleFactor: 1.2",
        "Extractor.nLevels: 4",
        "Extractor.nFeatures: 675",
        "Extractor.threshold: 0.01",
        "loopClosing: 1",
        "",
    ))


class H07ExactWindowRunnerTests(unittest.TestCase):
    def test_reused_engine_identity_is_exact(self) -> None:
        self.assertEqual(runner.engine.content_identity(runner.ENGINE), runner.ENGINE_EXPECTED)

    def test_window_mapping_and_gates_are_frozen(self) -> None:
        self.assertEqual(runner.CAMERA_COUNT, 1720)
        self.assertEqual((runner.PREROLL_FIRST_INDEX, runner.PREROLL_LAST_INDEX), (0, 1658))
        self.assertEqual((runner.SCORE_FIRST_INDEX, runner.SCORE_LAST_INDEX), (1659, 1719))
        self.assertEqual(runner.MIN_LAST_CAMERA_INDEX, 1659)
        sync = runner.synchronization_boundary()
        self.assertFalse(sync["camera0_has_shifted_imu_predecessor"])
        self.assertEqual(sync["feed_first_source_frame"], 1)
        self.assertFalse(sync["synthetic_or_extrapolated_imu_used"])

    def test_runtime_config_changes_model_path_only(self) -> None:
        target = Path("/tmp/h07 exact attempt/HFNet-RT")
        before = base_config()
        after = runner.derive_runtime_config(before, target)
        changed = [index for index, rows in enumerate(zip(before.splitlines(), after.splitlines())) if rows[0] != rows[1]]
        self.assertEqual(changed, [11])
        self.assertIn('Extractor.modelPath: "/tmp/h07 exact attempt/HFNet-RT/"', after)
        self.assertIn('Camera.type: "KannalaBrandt8"', after)
        self.assertIn("IMU.NoiseGyro: 0.001", after)

    def test_runtime_config_rejects_algorithm_drift(self) -> None:
        with self.assertRaises(runner.ContractError):
            runner.derive_runtime_config(base_config().replace("Extractor.nFeatures: 675", "Extractor.nFeatures: 800"), Path("/tmp/model"))

    def test_gpu_gate_requires_three_gib_and_zero_compute_apps(self) -> None:
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

    def test_wrong_token_cannot_check_claim_or_launch(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            spec = runner.replace(runner.DEFAULT_SPEC, attempt=Path(directory) / "attempt_001")
            with mock.patch.object(runner, "_base_run", return_value={"schema_version": runner.RESULT_SCHEMA, "status": "RUN_NOT_AUTHORIZED", "return_code": 23, "execution": {"process_started": False}}) as called:
                result = runner.run(spec, authorization_token="wrong")
            self.assertEqual(result["status"], "RUN_NOT_AUTHORIZED")
            called.assert_called_once()
            self.assertFalse(spec.start_claim.exists())

    def test_execution_lock_contains_sync_and_resource_boundaries(self) -> None:
        prepared = {
            "profile": {
                "preparation_and_stack": {
                    "identities": {
                        "reused_h03_engine": {"path": str(runner.ENGINE), **runner.ENGINE_EXPECTED},
                        "h07_wrapper": {"path": str(runner.WRAPPER), "size_bytes": 1, "sha256": "abc"},
                    }
                }
            }
        }
        with mock.patch.object(runner, "_base_build_execution_lock", return_value={"claim_boundary": {}}):
            value = runner.build_execution_lock(runner.DEFAULT_SPEC, prepared, "2026-01-01T00:00:00+00:00")
        self.assertEqual(value["resource_gate"]["minimum_gpu_free_mib"], 3072)
        self.assertFalse(value["synchronization_boundary"]["synthetic_or_extrapolated_imu_used"])
        self.assertFalse(value["claim_boundary"]["formal_minimum_30_native_pose_accuracy_ranking_met"])

    def test_result_seal_injects_source_mapping_before_write(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "run_result.json"
            payload = runner.canonical_json({
                "execution": {"inference_basis": "old"},
                "claim_boundary": {},
                "support": {},
            })
            runner._seal_h07_result(path, payload)
            value = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(value["source_index_mapping"]["score_source_indices_inclusive"], [1660, 1720])
        self.assertFalse(value["synchronization_boundary"]["synthetic_or_extrapolated_imu_used"])
        self.assertIn("1720-image", value["execution"]["inference_basis"])

    def test_score_continuity_uses_relative_window(self) -> None:
        value = runner._contiguous_metrics([1658, 1659, 1660, 1663], 1659, 1719)
        self.assertEqual(value["count"], 3)
        self.assertEqual(value["longest_contiguous_run"], 2)
        self.assertEqual(value["gap_count"], 1)


if __name__ == "__main__":
    unittest.main()
