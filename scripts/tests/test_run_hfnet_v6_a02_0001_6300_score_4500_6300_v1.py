#!/usr/bin/env python3
"""Non-model tests for the A02 full-history HFNet one-shot wrapper."""

import importlib.util
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock


RUNNER = Path(__file__).resolve().parents[1] / "run_hfnet_v6_a02_0001_6300_score_4500_6300_v1.py"
SPEC = importlib.util.spec_from_file_location("hfnet_v6_a02_full_history_runner", str(RUNNER))
assert SPEC is not None and SPEC.loader is not None
runner = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = runner
SPEC.loader.exec_module(runner)


def base_config() -> str:
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


class A02FullHistoryRunnerTests(unittest.TestCase):
    def test_reused_controller_identity_is_exact(self) -> None:
        observed = runner.engine.content_identity(runner.REUSED_A06_CONTROLLER)
        self.assertEqual(observed, runner.REUSED_A06_CONTROLLER_EXPECTED)

    def test_full_history_and_score_window_are_frozen(self) -> None:
        self.assertEqual(runner.CAMERA_COUNT, 6300)
        self.assertEqual((runner.PREROLL_FIRST_INDEX, runner.PREROLL_LAST_INDEX), (0, 4498))
        self.assertEqual((runner.SCORE_FIRST_INDEX, runner.SCORE_LAST_INDEX), (4499, 6299))
        self.assertEqual(runner.SCORE_LAST_INDEX - runner.SCORE_FIRST_INDEX + 1, 1801)
        self.assertEqual(runner.MIN_LAST_CAMERA_INDEX, 4499)
        self.assertEqual(runner.MIN_SCORE_POSES, 20)
        self.assertEqual(runner.MIN_CONTIGUOUS_SCORE_POSES, 20)
        self.assertEqual(runner.MIN_SCORE_KEYFRAMES, 1)

    def test_runtime_config_changes_model_path_only(self) -> None:
        target = Path("/tmp/a02 full history/HFNet-RT")
        before = base_config()
        after = runner.derive_runtime_config(before, target)
        changed = [
            index
            for index, rows in enumerate(zip(before.splitlines(), after.splitlines()))
            if rows[0] != rows[1]
        ]
        self.assertEqual(changed, [11])
        self.assertIn('Extractor.modelPath: "/tmp/a02 full history/HFNet-RT/"', after)
        self.assertIn("Extractor.nFeatures: 675", after)
        self.assertIn("IMU.NoiseGyro: 0.003", after)

    def test_runtime_config_rejects_algorithm_drift(self) -> None:
        with self.assertRaises(runner.ContractError):
            runner.derive_runtime_config(
                base_config().replace("Extractor.nFeatures: 675", "Extractor.nFeatures: 800"),
                Path("/tmp/model"),
            )

    def test_gpu_gate_requires_three_gib_and_zero_compute_apps(self) -> None:
        good_memory = SimpleNamespace(returncode=0, stdout="4096, 700, 3396\n", stderr="")
        no_apps = SimpleNamespace(returncode=0, stdout="", stderr="")
        with mock.patch.object(runner.subprocess, "run", side_effect=[good_memory, no_apps]):
            value = runner._query_gpu_resource_gate()
        self.assertTrue(value["ready"])
        low_memory = SimpleNamespace(returncode=0, stdout="4096, 1600, 2496\n", stderr="")
        one_app = SimpleNamespace(returncode=0, stdout="42, hfnet, 128\n", stderr="")
        with mock.patch.object(runner.subprocess, "run", side_effect=[low_memory, one_app]):
            value = runner._query_gpu_resource_gate()
        self.assertFalse(value["ready"])
        self.assertIn("GPU_COMPUTE_APPLICATION_PRESENT", value["errors"])
        self.assertIn("GPU_FREE_MEMORY_BELOW_3072_MIB", value["errors"])

    def test_wrong_token_cannot_create_claim_or_launch(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            spec = runner.replace(runner.DEFAULT_SPEC, attempt=Path(directory) / "attempt_001")
            with mock.patch.object(runner.engine, "check") as checked, mock.patch.object(runner.engine, "launch_once") as launched:
                result = runner.run(spec, authorization_token="wrong")
            self.assertEqual(result["status"], "RUN_NOT_AUTHORIZED")
            checked.assert_not_called()
            launched.assert_not_called()
            self.assertFalse(spec.start_claim.exists())

    def test_no_clobber_is_inherited(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "claim.json"
            runner.write_exclusive(path, runner.canonical_json({"b": 2, "a": 1}))
            with self.assertRaises(FileExistsError):
                runner.write_exclusive(path, b"replacement")
            self.assertEqual(json.loads(path.read_text()), {"a": 1, "b": 2})

    def test_score_continuity_uses_local_indices_for_source_4500_6300(self) -> None:
        value = runner._contiguous_metrics([4498, 4499, 4500, 4503], 4499, 6299)
        self.assertEqual(value["count"], 3)
        self.assertEqual(value["longest_contiguous_run"], 2)
        self.assertEqual(value["gap_count"], 1)

    def test_execution_lock_discloses_additive_and_p07_boundaries(self) -> None:
        prepared = {
            "profile": {
                "preparation_and_stack": {
                    "identities": {
                        "reused_a06_controller": {"path": str(runner.REUSED_A06_CONTROLLER), **runner.REUSED_A06_CONTROLLER_EXPECTED},
                        "a02_wrapper": {"path": str(runner.WRAPPER), "size_bytes": 1, "sha256": "abc"},
                    },
                    "legacy_read_only_pins": {"p07_result_receipt": {"sha256": "pinned"}},
                }
            }
        }
        with mock.patch.object(runner, "_base_build_execution_lock", return_value={"claim_boundary": {}}):
            value = runner.build_execution_lock(runner.DEFAULT_SPEC, prepared, "2026-01-01T00:00:00+00:00")
        self.assertTrue(value["claim_boundary"]["full_history_protocol_is_additive_not_a_rewrite_of_old_a02"])
        self.assertTrue(value["claim_boundary"]["p07_backfill_forbidden"])
        self.assertEqual(value["resource_gate"]["minimum_gpu_free_mib"], 3072)


if __name__ == "__main__":
    unittest.main()
