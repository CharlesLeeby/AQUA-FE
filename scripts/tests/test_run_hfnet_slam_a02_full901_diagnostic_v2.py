#!/usr/bin/env python3
"""Tests for the no-tuning HFNet-SLAM full901 diagnostic supervisor."""

from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from scripts import export_aqualoc_to_hfnet_euroc_full_v2 as adapter
from scripts import run_hfnet_slam_a02_full901_diagnostic_v2 as runner


CAMERA_STAMPS = (100_000_000, 200_000_000, 300_000_000)
IMU_RAW_STAMPS = (40_000_000, 100_000_000, 200_000_000, 260_000_000)
SHIFT_NS = 53_694_112


def _selection() -> adapter.base.SourceSelection:
    cameras = []
    for index, stamp in enumerate(CAMERA_STAMPS):
        pixels = bytes(
            (index, index + 1, index + 2, index + 3, index + 4, index + 5)
        )
        cameras.append(
            adapter.base.CameraSample(
                source_index=index,
                header_ns=stamp,
                record_ns=stamp,
                width=3,
                height=2,
                encoding="mono8",
                step=3,
                pixels=pixels,
                pixel_sha256=hashlib.sha256(pixels).hexdigest(),
            )
        )
    imus = []
    for index, stamp in enumerate(IMU_RAW_STAMPS):
        imus.append(
            adapter.base.ImuSample(
                source_index=index,
                raw_header_ns=stamp,
                output_header_ns=stamp + SHIFT_NS,
                record_ns=stamp,
                gyro_xyz=(index + 0.1, index + 0.2, index + 0.3),
                accel_xyz=(index + 1.1, index + 1.2, index + 1.3),
            )
        )
    return adapter.base.SourceSelection(
        cameras=tuple(cameras),
        imus=tuple(imus),
        topic_audit={"/camera": {"message_count": 3}, "/imu": {"message_count": 4}},
        all_image_first_ns=CAMERA_STAMPS[0],
        all_image_last_ns=CAMERA_STAMPS[-1],
        all_imu_first_ns=IMU_RAW_STAMPS[0],
        all_imu_last_ns=IMU_RAW_STAMPS[-1],
    )


FIXTURE_CONTRACT = adapter.base.PrefixContract(
    image_topic="/camera",
    imu_topic="/imu",
    expected_image_type="sensor_msgs/Image",
    expected_imu_type="sensor_msgs/Imu",
    expected_total_images=3,
    expected_total_imus=4,
    image_first_index=0,
    image_last_index=2,
    imu_first_index=0,
    imu_last_index=3,
    width=3,
    height=2,
    encoding="mono8",
    imu_shift_ns=SHIFT_NS,
    expected_first_image_stamp_ns=CAMERA_STAMPS[0],
    expected_last_image_stamp_ns=CAMERA_STAMPS[-1],
    expected_first_imu_raw_stamp_ns=IMU_RAW_STAMPS[0],
    expected_last_imu_raw_stamp_ns=IMU_RAW_STAMPS[-1],
)


def _stable_profile(spec: runner.RunSpec, token: str = "stable") -> dict:
    return {
        "baseline": {
            "implementation": "author_official_HFNet_SLAM",
            "official_repository": runner.OFFICIAL_REPOSITORY,
            "paper_doi": runner.PUBLISHED_DOI,
            "source_commit": spec.expected_commit,
            "source_tree": spec.expected_tree,
        },
        "command_argv": runner.command_argv(spec),
        "exporter": {"sha256": token},
        "identities": {
            "prefix_contract": {"path": "/prefix-contract", "sha256": "a"},
            "prefix_result": {"path": "/prefix-result", "sha256": "b"},
        },
        "input": {"payload_tree_sha256_excluding_manifest": token},
        "official_source": {
            "commit": spec.expected_commit,
            "tracked_worktree_clean": True,
            "tree": spec.expected_tree,
        },
        "prefix_runtime_continuity": {
            "cache_after_prefix_sha256": "a687",
            "classification": "TensorRT_runtime_timing_cache_not_model_weights_or_thresholds",
            "config_unchanged_from_prefix": True,
            "onnx_unchanged_from_prefix": True,
            "source": "sealed_prefix_r1_official_run_cache_after",
        },
        "profile_schema": runner.PROFILE_SCHEMA_VERSION,
        "runner": {"sha256": token},
        "scientific_role": runner.SCIENTIFIC_ROLE,
    }


def _runtime_ready(*args, **kwargs):
    return {"checks": {"synthetic": {"ok": True}}, "ok": True}


def _pose_rows(count: int = 31, step_ns: int = 100_000_000) -> str:
    return "".join(
        f"{1_000_000_000 + index * step_ns} {index}.0 0 0 0 0 0 1\n"
        for index in range(count)
    )


class Full901RunnerV2Tests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def _input_spec(self) -> runner.RunSpec:
        source = self.root / "source.bag"
        source.write_bytes(b"synthetic source")
        sequence = self.root / "sequence"
        adapter.write_artifact(
            sequence,
            source,
            hashlib.sha256(source.read_bytes()).hexdigest(),
            _selection(),
            FIXTURE_CONTRACT,
            {"actual_commit": adapter.base.HFNET_COMMIT, "errors": []},
            {"path": "/adapter-v1.py", "sha256": adapter.BASE_ADAPTER_SHA256},
        )
        return replace(
            runner.DEFAULT_SPEC,
            sequence_root=sequence,
            expected_camera_count=3,
            expected_source_imu_count=4,
            expected_imu_count=4,
            expected_camera_indices=(0, 2),
            expected_imu_indices=(0, 3),
            expected_first_camera_ns=CAMERA_STAMPS[0],
            expected_last_camera_ns=CAMERA_STAMPS[-1],
            expected_first_imu_raw_ns=IMU_RAW_STAMPS[0],
            expected_last_imu_raw_ns=IMU_RAW_STAMPS[-1],
            expected_imu_shift_ns=SHIFT_NS,
        )

    def _run_spec(self) -> runner.RunSpec:
        return replace(
            runner.DEFAULT_SPEC,
            sequence_root=self.root / "sequence",
            result_directory=self.root / "official-result",
            evidence_directory=self.root / "evidence",
            contract_json=self.root / "contract.json",
        )

    def test_input_audit_rehashes_exact_manifest_payload_and_tree(self) -> None:
        spec = self._input_spec()
        observed = runner.audit_input(spec)
        manifest = json.loads(
            (spec.sequence_root / "conversion_manifest.json").read_text()
        )
        self.assertEqual(observed["camera_count"], 3)
        self.assertEqual(observed["imu_count"], 4)
        self.assertEqual(
            observed["payload_tree_sha256_excluding_manifest"],
            manifest["payload_tree_sha256_excluding_manifest"],
        )
        extra = spec.sequence_root / "unregistered.txt"
        extra.write_text("must fail closed", encoding="utf-8")
        with self.assertRaisesRegex(runner.ContractError, "INPUT_FILE_TREE_MISMATCH"):
            runner.audit_input(spec)

    def test_production_contract_freezes_full_window_and_legacy_stop(self) -> None:
        spec = runner.DEFAULT_SPEC
        self.assertEqual(spec.expected_camera_count, 901)
        self.assertEqual(spec.expected_imu_count, 8994)
        self.assertEqual(spec.expected_camera_indices, (0, 900))
        self.assertEqual(spec.expected_imu_indices, (38, 9031))
        contract = runner.build_contract(_stable_profile(spec), spec)
        self.assertEqual(contract["legacy_prefix_r1"]["decision"], "STOP")
        self.assertTrue(contract["legacy_prefix_r1"]["preserved"])
        self.assertFalse(contract["legacy_prefix_r1"]["replacement_by_this_track"])
        self.assertEqual(
            contract["execution_policy"]["maximum_official_process_starts"], 1
        )
        self.assertFalse(contract["execution_policy"]["config_or_threshold_modification"])

    def test_prefix_post_run_cache_continuity_is_fail_closed(self) -> None:
        config = self.root / "config.yaml"
        config.write_text(
            '\n'.join(
                (
                    'Extractor.type: "HFNetRT"',
                    "Extractor.scaleFactor: 1.2",
                    "Extractor.nLevels: 4",
                    "Extractor.nFeatures: 675",
                    "Extractor.threshold: 0.01",
                )
            )
            + "\n",
            encoding="utf-8",
        )
        prefix = self.root / "prefix-result.json"
        prefix_value = {
            "decision": {"full_window_allowed": False, "status": "STOP"},
            "identity": {"config_sha256": "config", "onnx_sha256": "onnx"},
            "runtime": {
                "cache_after_sha256": "post-cache",
                "cache_before_sha256": "pre-cache",
            },
        }
        prefix.write_text(runner.canonical_json(prefix_value), encoding="utf-8")
        spec = replace(
            runner.DEFAULT_SPEC,
            config=config,
            prefix_result=prefix,
            expected_identities={"model_cache": {"sha256": "post-cache"}},
        )
        identities = {
            "config": {"sha256": "config"},
            "model_cache": {"sha256": "post-cache"},
            "onnx_model": {"sha256": "onnx"},
        }
        continuity = runner.validate_prefix_runtime_continuity(spec, identities)
        self.assertEqual(continuity["source"], "sealed_prefix_r1_official_run_cache_after")
        self.assertTrue(continuity["onnx_unchanged_from_prefix"])

        prefix_value["runtime"]["cache_after_sha256"] = "unrelated-cache"
        prefix.write_text(runner.canonical_json(prefix_value), encoding="utf-8")
        with self.assertRaisesRegex(
            runner.ContractError, "PREFIX_POST_RUN_CACHE_CONTINUITY_MISMATCH"
        ):
            runner.validate_prefix_runtime_continuity(spec, identities)

    def test_trajectory_gate_is_strict(self) -> None:
        valid = self.root / "valid.txt"
        valid.write_text(_pose_rows(), encoding="ascii")
        audit = runner.audit_trajectory(valid)
        self.assertTrue(audit["gate_pass"])
        self.assertEqual(audit["pose_count"], 31)
        self.assertEqual(audit["span_seconds"], 3.0)

        invalid = self.root / "invalid.txt"
        invalid.write_text(
            "1000000000 0 0 0 0 0 0 1\n"
            "1000000000 nan 0 0 0 0 0 1\n",
            encoding="ascii",
        )
        rejected = runner.audit_trajectory(invalid)
        self.assertFalse(rejected["gate_pass"])
        self.assertFalse(rejected["finite_eight_field_rows"])

    def test_empty_map_save_sigsegv_is_secondary_and_never_success(self) -> None:
        execution = runner.CommandResult(
            -11,
            stdout=(
                "Saving trajectory to /result/trajectory.txt ...\n"
                "There are 2 maps in the atlas\n"
                "  Map 0 has 0 KFs\n"
                "  Map 1 has 0 KFs\n"
            ),
        )
        self.assertTrue(runner.is_empty_map_save_exit_bug(execution))
        status, evaluable, rc = runner.classify_execution(
            execution, {"exists": False, "pose_count": 0}, {"pose_count": 0}
        )
        self.assertEqual(status, "EMPTY_MAP_SAVE_EXIT_BUG_AFTER_ALGORITHM_FAILURE")
        self.assertFalse(evaluable)
        self.assertEqual(rc, runner.RC_EXECUTION_FAILED)

    def test_freeze_is_canonical_and_no_clobber(self) -> None:
        spec = self._run_spec()
        profile = _stable_profile(spec)
        collector = lambda _spec, _probe: profile
        first = runner.freeze_contract(
            spec, profile_collector=collector, runtime_checker=_runtime_ready
        )
        self.assertEqual(first["status"], "CONTRACT_FROZEN_NO_RUN_STARTED")
        payload = spec.contract_json.read_text(encoding="utf-8")
        self.assertEqual(payload, runner.canonical_json(json.loads(payload)))
        before = hashlib.sha256(spec.contract_json.read_bytes()).hexdigest()
        second = runner.freeze_contract(
            spec, profile_collector=collector, runtime_checker=_runtime_ready
        )
        self.assertEqual(second["return_code"], runner.RC_CONTRACT_BLOCKED)
        self.assertEqual(before, hashlib.sha256(spec.contract_json.read_bytes()).hexdigest())

    def test_contract_drift_blocks_before_official_start(self) -> None:
        spec = self._run_spec()
        frozen_profile = _stable_profile(spec, "before")
        spec.contract_json.write_text(
            runner.canonical_json(runner.build_contract(frozen_profile, spec)),
            encoding="utf-8",
        )
        starts = []

        def forbidden_execute(*args, **kwargs):
            starts.append(1)
            return runner.CommandResult(0)

        result = runner.run_diagnostic(
            spec,
            execute_runner=forbidden_execute,
            profile_collector=lambda _spec, _probe: _stable_profile(spec, "after"),
            runtime_checker=_runtime_ready,
        )
        self.assertEqual(result["status"], "CONTRACT_BLOCKED")
        self.assertFalse(result["execution"]["command_started"])
        self.assertEqual(starts, [])

    def test_unique_official_start_and_success_gate(self) -> None:
        spec = self._run_spec()
        profile = _stable_profile(spec)
        spec.contract_json.write_text(
            runner.canonical_json(runner.build_contract(profile, spec)),
            encoding="utf-8",
        )
        commands = []

        def execute(command, environment, cwd, timeout):
            commands.append(list(command))
            spec.result_directory.mkdir()
            (spec.result_directory / "trajectory.txt").write_text(
                _pose_rows(), encoding="ascii"
            )
            (spec.result_directory / "trajectory_keyframe.txt").write_text(
                _pose_rows(2, 1_000_000_000), encoding="ascii"
            )
            return runner.CommandResult(0, "official complete\n", "")

        result = runner.run_diagnostic(
            spec,
            execute_runner=execute,
            profile_collector=lambda _spec, _probe: profile,
            runtime_checker=_runtime_ready,
        )
        self.assertEqual(result["status"], "PASS_FULL901_DIAGNOSTIC_TRAJECTORY_GATE")
        self.assertTrue(result["evaluable"])
        self.assertEqual(result["execution"]["official_process_start_count"], 1)
        self.assertEqual(commands, [runner.command_argv(spec)])
        self.assertTrue((spec.evidence_directory / "run_result.json").is_file())

    def test_failed_official_child_is_not_retried(self) -> None:
        spec = self._run_spec()
        profile = _stable_profile(spec)
        spec.contract_json.write_text(
            runner.canonical_json(runner.build_contract(profile, spec)),
            encoding="utf-8",
        )
        starts = []

        def execute(*args):
            starts.append(1)
            return runner.CommandResult(7, "tracking failed\n", "")

        result = runner.run_diagnostic(
            spec,
            execute_runner=execute,
            profile_collector=lambda _spec, _probe: profile,
            runtime_checker=_runtime_ready,
        )
        self.assertEqual(starts, [1])
        self.assertFalse(result["evaluable"])
        self.assertFalse(result["supervision"]["retry_performed"])
        self.assertEqual(result["execution"]["raw_returncode"], 7)


if __name__ == "__main__":
    unittest.main()
