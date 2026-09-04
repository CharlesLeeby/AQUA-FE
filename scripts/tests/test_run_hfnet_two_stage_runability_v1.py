#!/usr/bin/env python3
"""Static and synthetic tests; never start the real HFNet-SLAM ELF."""

from __future__ import annotations

from dataclasses import replace
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts import run_hfnet_two_stage_runability_v1 as runner


OFFICIAL_CONFIG = """%YAML:1.0
Camera1.fx: 458.654
Extractor.type: "HFNetRT"
Extractor.modelPath: "/home/llm/ROS/HFNet_SLAM/model/HFNet-RT/"
Extractor.scaleFactor: 1.2
Extractor.nLevels: 4
Extractor.nFeatures: 675
Extractor.threshold: 0.01
loopClosing: 1
"""


def trajectory(camera_stamps: list[int], indices: list[int]) -> str:
    return "".join(
        f"{camera_stamps[index]}.000000 {row}.0 0 0 0 0 0 1\n"
        for row, index in enumerate(indices)
    )


class PhaseDMH01RunnerTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.model = self.root / "shared/HFNet-RT"
        self.model.mkdir(parents=True)
        (self.model / "HF-Net.onnx").write_bytes(b"synthetic onnx")
        (self.model / "HF-Net.cache").write_bytes(b"synthetic cache seed")
        self.config = self.root / "official_euroc.yaml"
        self.config.write_text(OFFICIAL_CONFIG, encoding="utf-8")
        self.timestamps = self.root / "MH01.txt"
        self.camera_stamps = [
            1_400_000_000_000_000_000 + index * 50_000_000
            for index in range(runner.EXPECTED_CAMERA_COUNT)
        ]
        self.timestamps.write_text(
            "\n".join(str(value) for value in self.camera_stamps) + "\n",
            encoding="ascii",
        )
        self.spec = replace(
            runner.DEFAULT_SPEC,
            binary=self.root / "headless",
            official_config=self.config,
            timestamps=self.timestamps,
            onnx=self.model / "HF-Net.onnx",
            cache_seed=self.model / "HF-Net.cache",
            dataset=self.root / "dataset",
            attempt=self.root / "attempt_001",
            governance_records_required=False,
        )
        self.profile = {
            "schema_version": runner.PREFLIGHT_SCHEMA,
            "input": {
                "camera_count": runner.EXPECTED_CAMERA_COUNT,
                "camera_timestamps_ns": self.camera_stamps,
            },
            "synthetic": True,
        }

    def prepare_synthetic(self) -> dict:
        with patch.object(runner, "collect_profile", return_value=self.profile):
            prepared = runner.prepare(self.spec)
        self.assertEqual(prepared["return_code"], runner.RC_OK)
        self.assertFalse(self.spec.start_claim.exists())
        return prepared

    def test_runtime_config_changes_only_official_model_path_line(self) -> None:
        derived = runner.derive_runtime_config(
            OFFICIAL_CONFIG, self.spec.model_dir
        )
        self.assertEqual(
            derived,
            OFFICIAL_CONFIG.replace(
                runner.OFFICIAL_MODEL_PATH_LINE,
                f'Extractor.modelPath: "{self.spec.model_dir.resolve()}/"',
            ),
        )
        self.assertIn("Extractor.nFeatures: 675", derived)
        self.assertIn("Extractor.threshold: 0.01", derived)

    def test_preflight_is_read_only(self) -> None:
        with patch.object(runner, "collect_profile", return_value=self.profile):
            result = runner.preflight(self.spec)
        self.assertTrue(result["ready"])
        self.assertFalse(result["claims"]["filesystem_writes"])
        self.assertFalse(self.spec.attempt.exists())

    def test_prepare_and_check_stage_run_local_assets_without_start(self) -> None:
        source_cache_before = runner.identity(self.spec.cache_seed)
        self.prepare_synthetic()
        self.assertEqual(
            runner.identity(self.spec.model_dir / "HF-Net.onnx")["sha256"],
            runner.identity(self.spec.onnx)["sha256"],
        )
        self.assertEqual(
            runner.identity(self.spec.model_dir / "HF-Net.cache")["sha256"],
            source_cache_before["sha256"],
        )
        self.assertEqual(runner.identity(self.spec.cache_seed), source_cache_before)
        self.assertFalse(self.spec.result_dir.exists())
        self.assertFalse(self.spec.run_result.exists())
        with patch.object(runner, "collect_profile", return_value=self.profile):
            checked = runner.check(self.spec)
        self.assertTrue(checked["ready"])
        self.assertEqual(
            checked["audit"]["launch"]["argv"], runner.command_argv(self.spec)
        )
        self.assertNotIn("DISPLAY", checked["audit"]["launch"]["environment"])
        self.assertNotIn("XAUTHORITY", checked["audit"]["launch"]["environment"])

    def test_check_fails_closed_on_staged_cache_tamper(self) -> None:
        self.prepare_synthetic()
        (self.spec.model_dir / "HF-Net.cache").write_bytes(b"tampered")
        with patch.object(runner, "collect_profile", return_value=self.profile):
            checked = runner.check(self.spec)
        self.assertFalse(checked["ready"])
        self.assertIn("PREPARED_STAGED_IDENTITY_DRIFT", checked["errors"][0])

    def test_run_requires_exact_authorization_and_does_not_claim_start(self) -> None:
        self.prepare_synthetic()
        starts: list[bool] = []

        def must_not_execute(*args, **kwargs):
            starts.append(True)
            raise AssertionError("unauthorized run must not execute")

        result = runner.run(
            self.spec,
            authorization_token="wrong",
            execute=must_not_execute,
        )
        self.assertEqual(result["return_code"], runner.RC_BLOCKED)
        self.assertEqual(starts, [])
        self.assertFalse(self.spec.start_claim.exists())

    def test_post_audit_failure_and_config_mutation_still_write_terminal_failure(self) -> None:
        self.prepare_synthetic()

        def execute(command, environment, cwd, timeout):
            self.spec.derived_config.chmod(0o644)
            self.spec.derived_config.write_text("mutated after start\n", encoding="utf-8")
            return runner.CommandResult(0, "stdout retained", "stderr retained", False, 0.5)

        with patch.object(
            runner,
            "collect_profile",
            side_effect=[self.profile, runner.ContractError("synthetic post audit failure")],
        ):
            result = runner.run(
                self.spec,
                authorization_token=runner.RUN_AUTHORIZATION_TOKEN,
                execute=execute,
            )
        self.assertEqual(result["status"], "FAIL_PHASE_D_OFFICIAL_MH01_RUNABILITY")
        self.assertEqual(result["execution"]["process_start_count"], 1)
        self.assertFalse(result["gate"]["derived_config_pre_post_exact"])
        self.assertTrue(any(error.startswith("POST_PROFILE_AUDIT_FAILED:") for error in result["errors"]))
        self.assertIn("DERIVED_CONFIG_PRE_POST_MISMATCH", result["errors"])
        self.assertTrue(self.spec.start_claim.is_file())
        self.assertTrue(self.spec.run_result.is_file())
        self.assertEqual(self.spec.stdout_log.read_text(), "stdout retained")
        self.assertEqual(self.spec.stderr_log.read_text(), "stderr retained")

    def test_synthetic_one_shot_run_records_full_contract_and_passes(self) -> None:
        self.prepare_synthetic()
        trajectory_indices = [
            index * (runner.EXPECTED_CAMERA_COUNT - 1)
            // (runner.MIN_TRAJECTORY_ROWS - 1)
            for index in range(runner.MIN_TRAJECTORY_ROWS)
        ]
        keyframe_indices = [
            index * (runner.EXPECTED_CAMERA_COUNT - 1)
            // (runner.MIN_KEYFRAMES - 1)
            for index in range(runner.MIN_KEYFRAMES)
        ]
        starts: list[list[str]] = []

        def execute(command, environment, cwd, timeout):
            starts.append(list(command))
            self.assertEqual(list(command), runner.command_argv(self.spec))
            self.assertNotIn("DISPLAY", environment)
            self.assertNotIn("XAUTHORITY", environment)
            self.assertEqual(cwd, self.spec.attempt)
            self.assertEqual(timeout, runner.TIMEOUT_SECONDS)
            self.spec.result_dir.mkdir()
            (self.spec.result_dir / "trajectory.txt").write_text(
                trajectory(self.camera_stamps, trajectory_indices),
                encoding="ascii",
            )
            (self.spec.result_dir / "trajectory_keyframe.txt").write_text(
                trajectory(self.camera_stamps, keyframe_indices),
                encoding="ascii",
            )
            (self.spec.model_dir / "HF-Net.cache").write_bytes(
                b"synthetic runtime-mutated local cache"
            )
            return runner.CommandResult(0, "synthetic stdout", "", False, 1.25)

        with patch.object(runner, "collect_profile", return_value=self.profile):
            result = runner.run(
                self.spec,
                authorization_token=runner.RUN_AUTHORIZATION_TOKEN,
                execute=execute,
            )
        self.assertTrue(result["evaluable"])
        self.assertEqual(result["status"], "PASS_PHASE_D_OFFICIAL_MH01_RUNABILITY")
        self.assertEqual(len(starts), 1)
        self.assertEqual(result["execution"]["process_start_count"], 1)
        self.assertFalse(result["execution"]["retry_performed"])
        self.assertEqual(
            result["gate"]["input_images_consumed"],
            runner.EXPECTED_CAMERA_COUNT,
        )
        self.assertGreaterEqual(
            result["gate"]["trajectory"]["reaches_last_input_fraction"], 0.9
        )
        self.assertTrue(result["gate"]["keyframes"]["late_keyframe"])
        self.assertEqual(result["argv"], runner.command_argv(self.spec))
        self.assertEqual(result["environment"], runner.runtime_environment(self.spec))
        self.assertTrue(self.spec.start_claim.is_file())
        self.assertTrue(self.spec.run_result.is_file())
        self.assertEqual(
            runner.identity(self.spec.cache_seed),
            result["identities"]["official_shared_cache_pre"],
        )


if __name__ == "__main__":
    unittest.main()
