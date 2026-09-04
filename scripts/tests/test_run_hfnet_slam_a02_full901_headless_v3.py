#!/usr/bin/env python3
"""Static/synthetic tests only; never load HFNet, CUDA, or start SLAM."""

from __future__ import annotations

import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from scripts import run_hfnet_slam_a02_full901_headless_v3 as runner


CONFIG = """%YAML:1.0
Extractor.type: "HFNetRT"
Extractor.modelPath: "{model}/"
Extractor.scaleFactor: 1.2
Extractor.nLevels: 4
Extractor.nFeatures: 675
Extractor.threshold: 0.01
loopClosing: 1
"""


def poses(count: int = 31) -> str:
    return "".join(f"{1_000_000_000 + i * 100_000_000} {i}.0 0 0 0 0 0 1\n" for i in range(count))


class HeadlessV3Tests(unittest.TestCase):
    def setUp(self) -> None:
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.shared = self.root / "shared/HFNet-RT"
        self.shared.mkdir(parents=True)
        (self.shared / "HF-Net.onnx").write_bytes(b"synthetic onnx")
        (self.shared / "HF-Net.cache").write_bytes(b"seed cache")
        config = self.root / "config.yaml"
        config.write_text(CONFIG.format(model=self.shared.resolve()), encoding="utf-8")
        self.spec = replace(
            runner.DEFAULT_SPEC,
            config=config,
            onnx=self.shared / "HF-Net.onnx",
            cache_seed=self.shared / "HF-Net.cache",
            evidence=self.root / "evidence",
            result=self.root / "result",
            contract=self.root / "contract.json",
        )

    def test_headless_source_contains_only_type_adapter_not_tracking_copy(self) -> None:
        payload = runner.DEFAULT_HARNESS_SOURCE.read_text(encoding="utf-8")
        self.assertIn(": System(settings_file, sensor, false, init_frame)", payload)
        self.assertIn("#define System HeadlessSystem", payload)
        self.assertNotIn("TrackMonocular(", payload)
        self.assertIn(str(runner.DEFAULT_ENTRY_SOURCE.resolve()), payload)

    def test_runtime_config_changes_only_model_directory(self) -> None:
        source = self.spec.config.read_text(encoding="utf-8")
        local = self.root / "local/HFNet-RT"
        derived = runner.derive_runtime_config(source, self.shared, local)
        self.assertEqual(
            source.replace(str(self.shared.resolve()), str(local.resolve())), derived
        )
        for token in ("nFeatures: 675", "threshold: 0.01", "nLevels: 4"):
            self.assertIn(token, derived)

    def test_stage_copies_cache_and_onnx_without_touching_shared_seed(self) -> None:
        self.spec.evidence.mkdir()
        before = runner.identity(self.spec.cache_seed)
        staged = runner.stage_run_local_model(self.spec)
        local_cache = Path(staged["model_dir"]) / "HF-Net.cache"
        local_cache.write_bytes(b"mutated runtime cache")
        self.assertEqual(before, runner.identity(self.spec.cache_seed))
        self.assertNotEqual(runner.sha256(local_cache), before["sha256"])
        self.assertFalse((Path(staged["model_dir"]) / "HF-Net.onnx").is_symlink())

    def test_preflight_is_read_only(self) -> None:
        with patch.object(runner, "audit_static_contract", return_value={"stable": True}):
            result = runner.preflight(self.spec)
        self.assertTrue(result["ready"])
        self.assertFalse(result["claims"]["filesystem_writes"])
        self.assertFalse(self.spec.evidence.exists())
        self.assertFalse(self.spec.contract.exists())

    def test_synthetic_run_records_expected_cache_mutation_locally(self) -> None:
        profile = {"stable": True}
        contract = runner.build_contract(profile, self.spec)
        self.spec.contract.write_text(runner.canonical_json(contract), encoding="utf-8")

        def execute(command, environment, cwd, timeout):
            self.assertNotIn("DISPLAY", environment)
            self.assertEqual(command[0], str(runner.DEFAULT_BINARY.resolve()))
            local_cache = self.spec.evidence / "run_local_model/HFNet-RT/HF-Net.cache"
            local_cache.write_bytes(b"post cache")
            self.spec.result.mkdir(parents=True)
            (self.spec.result / "trajectory.txt").write_text(poses(), encoding="ascii")
            (self.spec.result / "trajectory_keyframe.txt").write_text(poses(1), encoding="ascii")
            return runner.CommandResult(0, "synthetic", "")

        with patch.object(runner, "audit_static_contract", return_value=profile):
            result = runner.run(self.spec, execute=execute)
        self.assertTrue(result["evaluable"])
        self.assertTrue(result["cache"]["shared_unchanged"])
        self.assertFalse(result["cache"]["writeback_performed"])
        self.assertNotEqual(
            result["cache"]["run_local_pre"]["sha256"],
            result["cache"]["run_local_post"]["sha256"],
        )

    def test_malformed_keyframe_trajectory_fails_evaluability_gate(self) -> None:
        profile = {"stable": True}
        contract = runner.build_contract(profile, self.spec)
        self.spec.contract.write_text(runner.canonical_json(contract), encoding="utf-8")

        def execute(command, environment, cwd, timeout):
            self.spec.result.mkdir(parents=True)
            (self.spec.result / "trajectory.txt").write_text(poses(), encoding="ascii")
            (self.spec.result / "trajectory_keyframe.txt").write_text(
                "garbage\n", encoding="ascii"
            )
            return runner.CommandResult(0, "synthetic", "")

        with patch.object(runner, "audit_static_contract", return_value=profile):
            result = runner.run(self.spec, execute=execute)
        self.assertFalse(result["evaluable"])
        self.assertEqual(result["return_code"], runner.RC_FAILED)
        self.assertFalse(
            result["gate"]["keyframe_trajectory"]["finite_eight_field_rows"]
        )
        self.assertTrue(result["gate"]["keyframe_trajectory"]["syntax_errors"])

    def test_run_no_clobber_blocks_before_process_start(self) -> None:
        profile = {"stable": True}
        self.spec.contract.write_text(
            runner.canonical_json(runner.build_contract(profile, self.spec)),
            encoding="utf-8",
        )
        self.spec.evidence.mkdir()
        starts = []

        def must_not_execute(*args, **kwargs):
            starts.append(True)
            raise AssertionError("process must not start")

        with patch.object(runner, "audit_static_contract", return_value=profile):
            result = runner.run(self.spec, execute=must_not_execute)
        self.assertEqual(result["return_code"], runner.RC_BLOCKED)
        self.assertFalse(result["execution"]["command_started"])
        self.assertEqual(starts, [])


if __name__ == "__main__":
    unittest.main()
