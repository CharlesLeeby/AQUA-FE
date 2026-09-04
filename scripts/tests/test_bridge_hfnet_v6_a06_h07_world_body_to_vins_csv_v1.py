#!/usr/bin/env python3
"""Tests for the sealed HFNet-v6 A06/H07 trajectory bridge."""

from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

import numpy as np

from scripts import bridge_hfnet_v6_a06_h07_world_body_to_vins_csv_v1 as bridge
from scripts import evaluate_vins_common_support as evaluator


class BridgeV6Tests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def make_synthetic_profile(
        self,
        *,
        schema: str = "synthetic-a06-v6",
        status: str = bridge.PASS_STATUS,
    ) -> tuple[Path, Path, dict[str, dict[str, object]]]:
        source = self.root / "trajectory.txt"
        source.write_text(
            "1542883311981428480.000000 1.00 -2 3e0 0.1 0.2 0.3 0.9273618495\n"
            "1542883312030068992.000000 4 5 6 0 0 0 1\n",
            encoding="ascii",
        )
        source_identity = bridge.file_identity(source)
        role = "HFNET_V6_SYNTHETIC_TEST_ONLY"
        result_value = {
            "schema_version": schema,
            "status": status,
            "return_code": 0,
            "errors": [],
            "scientific_role": role,
            "execution": {
                "process_started": True,
                "popen_invocations": 1,
                "raw_returncode": 0,
                "retry_performed": False,
                "retry_permitted": False,
                "timed_out": False,
                "synchronously_reaped": True,
                "supervisor_error": None,
            },
            "gate": {
                "execution": True,
                "exploratory_underwater_usability": True,
                "full_pre_post_profile_exact": True,
                "keyframe_score_support": True,
                "run_local_onnx_and_config_exact": True,
                "shared_cache_exact": True,
                "trajectory_score_continuity": True,
            },
            "sealing_contract": {
                "target": str((self.root / "run_result.json").absolute()),
                "terminal_after_any_started_attempt": True,
                "retry_after_pass_or_fail": False,
                "write_mode": "O_EXCL_then_fsync_then_chmod_0444",
            },
            "support": {
                "trajectory": {
                    "identity": source_identity,
                    "exists": True,
                    "valid": True,
                    "kind": "frame_trajectory",
                    "strictly_increasing_timestamps": True,
                    "unique_strict_camera_associations": True,
                    "all_quaternions_within_tolerance": True,
                    "errors": [],
                    "pose_count": 2,
                    "score": {
                        "count": 2,
                        "first_index": 0,
                        "last_index": 1,
                        "coverage_fraction": 1.0,
                        "gap_count": 0,
                        "contiguous_run_count": 1,
                        "longest_contiguous_run": 2,
                    },
                }
            },
        }
        run_result = self.root / "run_result.json"
        run_result.write_bytes(bridge.canonical_json(result_value))
        profiles = {
            schema: {
                "profile_id": "SYNTHETIC_A06",
                "scientific_role": role,
                "run_result": bridge.file_identity(run_result),
                "trajectory": source_identity,
                "pose_count": 2,
                "score": {"count": 2, "first_index": 0, "last_index": 1},
            }
        }
        return source, run_result, profiles

    def test_convert_reorders_only_quaternion_and_evaluator_reads_it(self) -> None:
        source, run_result, profiles = self.make_synthetic_profile()
        output = self.root / "bridge.csv"
        result = bridge.convert(source, output, run_result, profiles)
        self.assertEqual(result["status"], "PASS_SEALED_V6_BRIDGE")
        self.assertEqual(
            output.read_bytes(),
            b"1542883311981428480,1.00,-2,3e0,0.9273618495,0.1,0.2,0.3\n"
            b"1542883312030068992,4,5,6,1,0,0,0\n",
        )
        loaded = evaluator.load_vins_body_csv(output)
        np.testing.assert_allclose(loaded.positions[0], [1.0, -2.0, 3.0])
        np.testing.assert_allclose(
            loaded.quaternions_xyzw[0], [0.1, 0.2, 0.3, 0.9273618495]
        )
        manifest = json.loads(
            Path(str(output) + ".manifest.json").read_text(encoding="utf-8")
        )
        semantics = manifest["semantics"]
        self.assertEqual(semantics["input_pose"], "world_T_body")
        self.assertEqual(semantics["input_quaternion_order"], "xyzw")
        self.assertFalse(semantics["alignment_applied"])
        self.assertFalse(semantics["interpolation_or_resampling_applied"])
        self.assertFalse(semantics["pose_transform_or_inversion_applied"])

    def test_public_allowlist_accepts_only_exact_a06_h07_sealed_files(self) -> None:
        for profile in bridge.ALLOWED_PROFILES.values():
            source = Path(profile["trajectory"]["path"])
            run_result = Path(profile["run_result"]["path"])
            if not source.exists() or not run_result.exists():
                self.skipTest("sealed /mnt HFNet-v6 evidence is unavailable")
            record = bridge.audit(source, run_result)
            self.assertEqual(record["status"], "AUDIT_PASS_NO_WRITE")
            self.assertEqual(record["row_count"], profile["pose_count"])

    def test_unknown_including_a02_schema_is_rejected(self) -> None:
        source, run_result, _ = self.make_synthetic_profile(
            schema="aqua-fe-hfnet-v6-a02-0001-6300-run-result-v2"
        )
        with self.assertRaisesRegex(
            bridge.BridgeError, "SCHEMA_NOT_ALLOWED_A06_OR_H07_V6"
        ):
            bridge.audit(source, run_result)

    def test_status_mutation_is_rejected_even_with_matching_test_identity(self) -> None:
        source, run_result, profiles = self.make_synthetic_profile(status="FAIL")
        with self.assertRaisesRegex(bridge.BridgeError, "NOT_EXACT_EVALUABLE"):
            bridge.audit(source, run_result, profiles)

    def test_run_result_path_size_or_sha_mismatch_is_rejected(self) -> None:
        source, run_result, profiles = self.make_synthetic_profile()
        profile = profiles["synthetic-a06-v6"]
        copied = self.root / "copied_result.json"
        copied.write_bytes(run_result.read_bytes())
        profile["run_result"] = bridge.file_identity(copied)
        with self.assertRaisesRegex(bridge.BridgeError, "SEALED_IDENTITY_MISMATCH"):
            bridge.audit(source, run_result, profiles)

    def test_trajectory_path_size_or_sha_mismatch_is_rejected(self) -> None:
        source, run_result, profiles = self.make_synthetic_profile()
        copied = self.root / "copied_trajectory.txt"
        copied.write_bytes(source.read_bytes())
        with self.assertRaisesRegex(bridge.BridgeError, "TRAJECTORY_SEALED_IDENTITY"):
            bridge.audit(copied, run_result, profiles)

    def test_run_result_internal_trajectory_identity_mismatch_is_rejected(self) -> None:
        source, run_result, profiles = self.make_synthetic_profile()
        value = json.loads(run_result.read_text(encoding="utf-8"))
        value["support"]["trajectory"]["identity"]["sha256"] = "0" * 64
        run_result.write_bytes(bridge.canonical_json(value))
        profiles["synthetic-a06-v6"]["run_result"] = bridge.file_identity(run_result)
        with self.assertRaisesRegex(
            bridge.BridgeError, "RUN_RESULT_TRAJECTORY_IDENTITY_MISMATCH"
        ):
            bridge.audit(source, run_result, profiles)

    def test_fractional_timestamp_nonunit_quaternion_and_blank_fail(self) -> None:
        with self.assertRaisesRegex(bridge.BridgeError, "TIMESTAMP_NOT_INTEGER_NS"):
            bridge.parse_trajectory_payload(b"1.5 0 0 0 0 0 0 1\n", "fractional")
        with self.assertRaisesRegex(bridge.BridgeError, "INVALID_QUATERNION_NORM"):
            bridge.parse_trajectory_payload(b"1 0 0 0 0 0 0 2\n", "quaternion")
        with self.assertRaisesRegex(bridge.BridgeError, "BLANK_ROW"):
            bridge.parse_trajectory_payload(
                b"1 0 0 0 0 0 0 1\n\n2 0 0 0 0 0 0 1\n", "blank"
            )

    def test_output_is_no_clobber(self) -> None:
        source, run_result, profiles = self.make_synthetic_profile()
        output = self.root / "owned.csv"
        output.write_bytes(b"owner data")
        with self.assertRaisesRegex(bridge.BridgeError, "ALREADY_EXISTS"):
            bridge.convert(source, output, run_result, profiles)
        self.assertEqual(output.read_bytes(), b"owner data")


if __name__ == "__main__":
    unittest.main()
