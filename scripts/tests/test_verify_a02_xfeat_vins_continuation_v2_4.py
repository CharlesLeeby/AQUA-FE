from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest import mock

from scripts import build_a02_xfeat_vins_continuation_freeze_v2_4 as builder
from scripts import verify_a02_xfeat_vins_continuation_v2_4 as v2_4
from scripts import verify_a02_long_three_arm_eval_inputs_v1 as v1


def actual_manifest() -> dict[str, object]:
    return json.loads(v2_4.v2_3.XFEAT_MANIFEST.read_bytes())


def xfeat_kwargs() -> dict[str, Path]:
    return {
        "source_bag": v1.DEFAULT_B1_CONSTQ_BAG,
        "raw_bag": v1.DEFAULT_WINDOW_BAG,
        "camera_yaml": v1.DEFAULT_B1_NATIVE_CAMERA,
        "output_bag": v2_4.v2_3.XFEAT_BAG,
        "manifest_path": v2_4.v2_3.XFEAT_MANIFEST,
        "audit_path": v2_4.v2_3.XFEAT_AUDIT,
    }


class XFeatVinsContinuationV24Tests(unittest.TestCase):
    def test_actual_manifest_is_exact_and_legacy_false_negative_is_reproduced(self) -> None:
        payload = v2_4.v2_3.XFEAT_MANIFEST.read_bytes()
        manifest = json.loads(payload)
        self.assertEqual(payload, v1.canonical_json(manifest))
        self.assertEqual(len(payload), v2_4.EXPECTED_XFEAT_MANIFEST_SIZE)
        self.assertEqual(hashlib.sha256(payload).hexdigest(), v2_4.EXPECTED_XFEAT_MANIFEST_SHA256)
        with self.assertRaisesRegex(v1.VerificationError, "XFEAT_EXPORT_MANIFEST_CONTRACT_MISMATCH"):
            v2_4._ORIGINAL_XFEAT_VALIDATOR(**xfeat_kwargs())
        result = v2_4.validate_xfeat_chain_v2_4(**xfeat_kwargs())
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["detector_runtime_contract"]["detect_calls"], 1562)
        self.assertNotEqual(result["detector_runtime_contract"]["detect_calls"], 900)

    def test_actual_1562_is_derived_from_all_independent_counts(self) -> None:
        _projection, proof = v2_4.build_xfeat_compatibility_projection(actual_manifest())
        for key in (
            "actual_detect_calls", "refill_condition_count",
            "positive_detector_candidate_count", "runtime_profile_detect_count",
            "detector_runtime_all_count",
        ):
            self.assertEqual(proof[key], 1562)
        self.assertEqual(proof["detector_runtime_warmup_count"], 1)
        self.assertEqual(proof["detector_runtime_steady_state_count"], 1561)
        self.assertEqual(proof["raw_frame_diagnostic_count"], 1800)
        self.assertFalse(proof["compatibility_projection_written_to_disk"])

    def test_projection_changes_exactly_six_leaves_and_does_not_mutate_actual(self) -> None:
        manifest = actual_manifest()
        before = copy.deepcopy(manifest)
        projection, proof = v2_4.build_xfeat_compatibility_projection(manifest)
        self.assertEqual(manifest, before)
        self.assertEqual(
            v2_4.recursive_leaf_diff(manifest, projection),
            v2_4.EXPECTED_PROJECTION_DIFFS,
        )
        self.assertEqual(proof["compatibility_projection_leaf_paths"], v2_4.EXPECTED_PROJECTION_DIFFS)
        self.assertEqual(
            projection["code_artifacts"]["detector"]["runtime"]["detect_calls"], 900
        )
        self.assertEqual(
            manifest["code_artifacts"]["detector"]["runtime"]["detect_calls"], 1562
        )

    def test_detect_count_profile_timing_and_raw_frame_tamper_fail(self) -> None:
        mutations = (
            (("code_artifacts", "detector", "runtime", "detect_calls"), 1561),
            (("runtime_profile", "stages", "detect", "count"), 1563),
            (("code_artifacts", "detector", "runtime", "detect_ms", "all", "count"), 900),
            (("code_artifacts", "detector", "runtime", "detect_ms", "warmup", "count"), 0),
            (("code_artifacts", "detector", "runtime", "detect_ms", "steady_state", "count"), 1560),
            (("metrics", "raw_frames_processed"), 1799),
        )
        for keys, replacement in mutations:
            value = actual_manifest()
            v2_4._nested_set(value, keys, replacement)
            with self.subTest(keys=keys), self.assertRaisesRegex(
                v1.VerificationError, "DETECT_CALL|RUNTIME"
            ):
                v2_4.build_xfeat_compatibility_projection(value)
        value = actual_manifest()
        value["raw_frame_diagnostics"] = value["raw_frame_diagnostics"][:-1]
        with self.assertRaisesRegex(v1.VerificationError, "DIAGNOSTIC_COUNT"):
            v2_4.build_xfeat_compatibility_projection(value)

    def test_diagnostic_refill_and_candidate_count_tamper_fail(self) -> None:
        value = actual_manifest()
        target = next(row for row in value["raw_frame_diagnostics"] if row["tracked_after"] < 350)
        target["tracked_after"] = 350
        with self.assertRaisesRegex(v1.VerificationError, "DETECT_CALL_DERIVATION"):
            v2_4.build_xfeat_compatibility_projection(value)
        value = actual_manifest()
        target = next(row for row in value["raw_frame_diagnostics"] if row["detector_candidates"] > 0)
        target["detector_candidates"] = 0
        with self.assertRaisesRegex(v1.VerificationError, "DETECT_CALL_DERIVATION"):
            v2_4.build_xfeat_compatibility_projection(value)

    def test_lexical_paths_must_resolve_to_official_exact_targets(self) -> None:
        manifest = actual_manifest()
        leaf = v2_4.PATH_PROJECTION_LEAVES[3]
        claim = v2_4._nested_get(manifest, leaf[:-1])
        with tempfile.TemporaryDirectory(dir=v2_4.ROOT) as directory:
            copy_path = Path(directory) / "xfeat.py"
            copy_path.write_bytes(Path(claim["path"]).read_bytes())
            claim["path"] = str(copy_path)
            with self.assertRaisesRegex(v1.VerificationError, "LEXICAL_WORKSPACE_PATH|RESOLVED_IDENTITY"):
                v2_4.build_xfeat_compatibility_projection(manifest)

    def test_manifest_identity_and_codec_are_not_relaxed(self) -> None:
        original_payload = v2_4.v2_3.XFEAT_MANIFEST.read_bytes()
        manifest = json.loads(original_payload)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            pretty_wrong = root / "manifest.json"
            pretty_wrong.write_text(json.dumps(manifest, sort_keys=True) + "\n")
            with self.assertRaisesRegex(v1.VerificationError, "NOT_CANONICAL|EXACT_V2_3"):
                v2_4.load_xfeat_manifest_compatibility(pretty_wrong, "XFEAT_EXPORT_MANIFEST")
        with self.assertRaisesRegex(v1.VerificationError, "UNAUTHORIZED_LABEL"):
            v2_4.v2_1._producer_canonical_json(
                v2_4.v2_3.XFEAT_MANIFEST, "XFEAT_EXPORT_MANIFEST"
            )
        self.assertEqual(v2_4.v2_3.XFEAT_MANIFEST.read_bytes(), original_payload)

    def test_loader_is_narrow_and_patch_is_restored_after_success_and_exception(self) -> None:
        original_loader = v1.load_canonical_json
        original_validator = v1.validate_xfeat_chain
        v2_4.validate_xfeat_chain_v2_4(**xfeat_kwargs())
        self.assertIs(v1.load_canonical_json, original_loader)
        self.assertIs(v1.validate_xfeat_chain, original_validator)
        with mock.patch.object(v2_4, "_ORIGINAL_XFEAT_VALIDATOR", side_effect=RuntimeError("boom")):
            with self.assertRaisesRegex(RuntimeError, "boom"):
                v2_4.validate_xfeat_chain_v2_4(**xfeat_kwargs())
        self.assertIs(v1.load_canonical_json, original_loader)
        self.assertIs(v1.validate_xfeat_chain, original_validator)
        delegated = v2_4.load_xfeat_manifest_compatibility(
            v2_4.v2_3.DEFAULT_FREEZE, "SOME_UNAUTHORIZED_THIRD_LABEL"
        )
        expected = v2_4.v2_1.load_canonical_json_v2(
            v2_4.v2_3.DEFAULT_FREEZE, "SOME_UNAUTHORIZED_THIRD_LABEL"
        )
        self.assertEqual(delegated, expected)

    def test_outer_component_builder_restores_all_five_patches_on_exception(self) -> None:
        before = (
            v1.load_canonical_json,
            v1.validate_quality_chain,
            v1.validate_xfeat_chain,
            v1.vins_process_receipt_contract,
            v1.validate_vins_process_receipt,
        )
        with mock.patch.object(v1, "build_record", side_effect=RuntimeError("outer boom")):
            with self.assertRaisesRegex(RuntimeError, "outer boom"):
                v2_4._build_component_base_record()
        after = (
            v1.load_canonical_json,
            v1.validate_quality_chain,
            v1.validate_xfeat_chain,
            v1.vins_process_receipt_contract,
            v1.validate_vins_process_receipt,
        )
        self.assertEqual(before, after)

    def test_carry_forward_locks_b1_xfeat_and_old_skip_start_zero(self) -> None:
        carry = v2_4.current_carry_forward()
        self.assertEqual(carry["v2_3_terminal"]["sha256"], v2_4.EXPECTED_V2_3_TERMINAL_SHA256)
        self.assertEqual(carry["b1_vio"]["sha256"], v2_4.EXPECTED_B1_VIO_SHA256)
        self.assertEqual(carry["xfeat_bag"]["sha256"], v2_4.EXPECTED_XFEAT_BAG_SHA256)
        skip = carry["old_xfeat_dependency_skip_tree"]
        self.assertEqual(skip["receipt_record"]["return_code"], 125)
        self.assertFalse(skip["receipt_record"]["algorithm_started"])
        self.assertEqual(skip["receipt_record"]["actual_process_start_count"], 0)
        self.assertEqual(skip["receipt_record"]["attempt_count"], 0)

    def test_old_v2_3_terminal_is_byte_recomputable(self) -> None:
        result = v2_4.old_v2_3_terminal_recomputation()
        self.assertEqual(result["status"], "PASS_BYTE_RECOMPUTABLE")
        self.assertEqual(result["identity"]["sha256"], v2_4.EXPECTED_V2_3_TERMINAL_SHA256)

    def test_new_receipt_contract_is_one_actual_xfeat_attempt_only(self) -> None:
        passed = v2_4.build_receipt_v2_4(0, True)
        failed = v2_4.build_receipt_v2_4(7, True)
        self.assertEqual(passed["status"], "PASS_ACTUAL_PROCESS_RC0")
        self.assertEqual(failed["status"], "FAIL_ACTUAL_PROCESS_NONZERO")
        self.assertEqual(passed["actual_process_start_count"], 1)
        self.assertEqual(passed["attempt_count"], 1)
        self.assertEqual(passed["port"], 11532)
        self.assertEqual(passed["feature_bag"], str(v2_4.XFEAT_FEATURE_BAG_CANONICAL))
        for bad in (-1, 256, True):
            with self.subTest(bad=bad), self.assertRaises(v1.VerificationError):
                v2_4.build_receipt_v2_4(bad, True)
        with self.assertRaisesRegex(v1.VerificationError, "ONLY_ACTUAL"):
            v2_4.build_receipt_v2_4(125, False)

    def test_observed_receipt_rejects_tamper_and_accepts_nonzero_scientific_failure(self) -> None:
        identity = {"path": "/tmp/x", "size_bytes": 1, "sha256": "a" * 64}
        failed = v2_4.build_receipt_v2_4(9, True)
        with mock.patch.object(v2_4, "_ORIGINAL_LOAD", return_value=(failed, identity)):
            self.assertEqual(v2_4.observe_new_receipt()["status"], "OBSERVED")
        tampered = dict(failed)
        tampered["attempt_count"] = 2
        with mock.patch.object(v2_4, "_ORIGINAL_LOAD", return_value=(tampered, identity)):
            self.assertEqual(v2_4.observe_new_receipt()["status"], "MISSING_OR_INVALID")

    def test_receipt_seal_is_exclusive_read_only_and_rejects_start_zero(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run = Path(directory) / "run"
            run.mkdir()
            with mock.patch.object(v2_4, "XFEAT_RUN", run), mock.patch.object(
                v2_4, "validate_revision"
            ):
                self.assertEqual(
                    v2_4.main(["--action", "seal-arm-rc", "--return-code", "7", "--started", "1"]),
                    0,
                )
                receipt = run / "process_rc_receipt.json"
                self.assertEqual(receipt.stat().st_mode & 0o777, 0o444)
                self.assertEqual(json.loads(receipt.read_bytes())["return_code"], 7)
                self.assertEqual(
                    v2_4.main(["--action", "seal-arm-rc", "--return-code", "7", "--started", "1"]),
                    2,
                )
            other = Path(directory) / "other"
            other.mkdir()
            with mock.patch.object(v2_4, "XFEAT_RUN", other), mock.patch.object(
                v2_4, "validate_revision"
            ):
                self.assertEqual(
                    v2_4.main(["--action", "seal-arm-rc", "--return-code", "125", "--started", "0"]),
                    2,
                )
                self.assertFalse((other / "process_rc_receipt.json").exists())

    def test_replay_command_uses_resolved_manifest_bag_and_only_one_runner(self) -> None:
        commands = v2_4.expected_commands()
        replay = commands[2]
        self.assertEqual(replay.count("run_aqualoc_archaeo_vins_eval.sh"), 1)
        self.assertIn(str(v2_4.XFEAT_FEATURE_BAG_CANONICAL), replay)
        self.assertNotIn(f"FEATURE_BAG_OVERRIDE={v2_4.v2_3.XFEAT_BAG} ", replay)
        self.assertIn("PORT=11532", replay)
        self.assertIn(v2_4.XFEAT_TAG, replay)
        self.assertIn(f"/usr/bin/mkdir {v2_4.XFEAT_RUN}", replay)

    def test_commands_forbid_every_prior_scientific_producer_and_evaluator(self) -> None:
        commands = v2_4.expected_commands()
        self.assertEqual(len(commands), 4)
        joined = "\n".join(commands)
        forbidden = (
            "export_xfeat_lk_carrier_v1.py", "audit_xfeat_lk_carrier_v1.py",
            "audit_quality_partition.py", "agent_qi_calibration_rewrite_bag.py",
            "run_a02_b1_klt_nativeq_current_exporter_guarded",
            "run_hfnet_slam_a02_long1801_headless_v4.py",
            "bridge_hfnet_world_body_to_vins_csv_v1.py",
            "evaluate_vins_common_support.py", str(v2_4.v2_3.XFEAT_RUN),
        )
        for token in forbidden:
            self.assertNotIn(token, joined)
        for command in commands:
            completed = subprocess.run(["/bin/bash", "-n", "-c", command], check=False)
            self.assertEqual(completed.returncode, 0)

    def test_terminal_pass_and_fail_are_descriptive_only(self) -> None:
        base = {
            "arms": {
                "B1_CONSTQ": {"status": "PASS"},
                "XFEATBIRTH_RAWLK": {"status": "PASS"},
                "HFNET_WHOLE_SYSTEM": {"status": "FAIL"},
            },
            "schema_version": "old",
        }
        binding = {"active": True}
        observed = {"status": "OBSERVED"}
        with mock.patch.object(v2_4, "validate_revision"), mock.patch.object(
            v2_4, "_build_component_base_record", return_value=base
        ), mock.patch.object(v2_4, "continuation_binding", return_value=binding), mock.patch.object(
            v2_4, "observe_new_receipt", return_value=observed
        ):
            passed = v2_4.build_terminal_record(v2_4.DEFAULT_FREEZE)
            self.assertEqual(passed["status"], v2_4.TERMINAL_PASS)
            outcome = passed["terminal_outcome"]
            self.assertTrue(outcome["descriptive_two_component_comparison_eligible"])
            self.assertFalse(outcome["ranking_performed"])
            self.assertFalse(outcome["common_support_evaluator_run"])
            self.assertFalse(outcome["superiority_claim"])
            failed_base = copy.deepcopy(base)
            failed_base["arms"]["XFEATBIRTH_RAWLK"] = {"status": "FAIL"}
            with mock.patch.object(v2_4, "_build_component_base_record", return_value=failed_base):
                failed = v2_4.build_terminal_record(v2_4.DEFAULT_FREEZE)
            self.assertEqual(failed["status"], v2_4.TERMINAL_FAIL)
            self.assertFalse(failed["terminal_outcome"]["descriptive_two_component_comparison_eligible"])

    def test_injected_arguments_reject_conflicts_and_old_protocol_stays_immutable(self) -> None:
        with self.assertRaisesRegex(v1.VerificationError, "FIXED_ARGUMENT_CONFLICT"):
            v2_4.injected_v1_arguments(["--xfeat", "/tmp/evil"])
        before = v1.authoritative_commands()
        v2_4._assert_old_protocols_immutable()
        self.assertEqual(v1.authoritative_commands(), before)

    def test_reserved_paths_are_new_and_absent_before_freeze(self) -> None:
        self.assertEqual(v2_4.RESERVED_PATHS, [str(v2_4.XFEAT_RUN), str(v2_4.TERMINAL_EVIDENCE)])
        self.assertNotEqual(v2_4.XFEAT_RUN, v2_4.v2_3.XFEAT_RUN)
        for item in v2_4.RESERVED_PATHS:
            self.assertFalse(Path(item).exists() or Path(item).is_symlink())

    def test_incident_and_freeze_are_canonical_exact_after_materialization(self) -> None:
        if not v2_4.DEFAULT_INCIDENT.exists() or not v2_4.DEFAULT_FREEZE.exists():
            self.skipTest("builder outputs not materialized yet")
        incident_payload = v2_4.DEFAULT_INCIDENT.read_bytes()
        freeze_payload = v2_4.DEFAULT_FREEZE.read_bytes()
        self.assertEqual(incident_payload, v1.canonical_json(json.loads(incident_payload)))
        self.assertEqual(freeze_payload, v1.canonical_json(json.loads(freeze_payload)))
        self.assertEqual(json.loads(incident_payload), builder.build_incident_record())
        self.assertEqual(json.loads(freeze_payload), builder.build_freeze_record())


if __name__ == "__main__":
    unittest.main()
