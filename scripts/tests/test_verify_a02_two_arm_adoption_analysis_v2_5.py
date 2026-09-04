from __future__ import annotations

import copy
import hashlib
import json
import math
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest import mock

from scripts import build_a02_two_arm_adoption_analysis_freeze_v2_5 as builder
from scripts import verify_a02_long_three_arm_eval_inputs_v1 as v1
from scripts import verify_a02_two_arm_adoption_analysis_v2_5 as v2_5


class TwoArmAdoptionAnalysisV25Tests(unittest.TestCase):
    def test_expected_and_actual_trees_preserve_receipt_path_contradiction(self) -> None:
        result = v2_5.validate_actual_tree_and_naming()
        self.assertEqual(
            result["classification"],
            "POST_INCIDENT_OBSERVED_DETERMINISTIC_OUTPUT_TREE_ADOPTION",
        )
        self.assertTrue(result["receipt_and_actual_tree_path_contradiction_preserved"])
        self.assertNotEqual(result["receipt_claimed_run_dir"], result["actual_output_dir"])
        self.assertEqual(result["receipt_declared_process_start_count"], 1)
        self.assertEqual(result["receipt_declared_process_return_code"], 0)
        self.assertFalse(result["cryptographically_proved_unique_vins_child"])
        self.assertFalse(result["persistent_process_telemetry_artifact"])
        self.assertTrue(result["actual_output_namespace_was_not_reserved_absent_by_v2_4"])
        self.assertEqual(result["actual_tree"]["summary"]["regular_file_count"], 8)
        self.assertEqual(
            result["actual_tree"]["summary"]["inventory_sha256"],
            v2_5.EXPECTED_ACTUAL_TREE_INVENTORY_SHA256,
        )

    def test_actual_xfeat_arm_and_b1_are_full_health_passes(self) -> None:
        xfeat = v2_5.validate_adopted_xfeat_arm()
        b1 = v2_5.validate_b1_component()
        self.assertEqual(xfeat["status"], "PASS")
        self.assertEqual(b1["status"], "PASS")
        self.assertEqual(xfeat["trajectory"]["sha256"], v2_5.EXPECTED_ACTUAL_VIO_SHA256)
        self.assertEqual(xfeat["raw_vins_csv_schema"]["row_count"], 872)
        self.assertEqual(b1["trajectory"]["sha256"], v2_5.v2_4.EXPECTED_B1_VIO_SHA256)
        for arm in (xfeat, b1):
            self.assertEqual(arm["vins_log"]["initialization_success_count"], 1)
            self.assertFalse(any(arm["vins_log"]["marker_counts_after_initialization"].values()))
            self.assertEqual(
                arm["replay_provenance"]["normalized_vins_config_sha256"],
                v2_5.EXPECTED_NORMALIZED_CONFIG_SHA256,
            )

    def test_xfeat_duration_score_and_input_binding_are_exact(self) -> None:
        arm = v2_5.validate_adopted_xfeat_arm()
        self.assertEqual(
            arm["raw_duration_and_score_contract"],
            {
                "row_count": 872,
                "first_ns": 1542829019550072320,
                "last_ns": 1542829106635604480,
                "duration_s": 87.08553216,
                "score_row_count": 450,
                "score_first_ns": 1542829061741920000,
                "score_last_ns": 1542829106635604480,
                "score_span_s": 44.89368448,
            },
        )
        replay = arm["replay_provenance"]
        self.assertEqual(replay["feature_bag"]["sha256"], v2_5.v2_4.EXPECTED_XFEAT_BAG_SHA256)
        self.assertEqual(replay["ros_master_port"], 11532)
        self.assertEqual(replay["camera_config"]["sha256"], v2_5.EXPECTED_CAMERA_SHA256)

    def test_actual_tree_extra_missing_or_hash_tamper_is_rejected(self) -> None:
        actual = v2_5.tree_record(v2_5.ACTUAL_XFEAT_RUN, "TEST_TREE")
        mutations = []
        extra = copy.deepcopy(actual)
        extra["entries"].append(
            {"relative_path": "extra", "type": "regular", "size_bytes": 0, "sha256": "0" * 64}
        )
        mutations.append(extra)
        missing = copy.deepcopy(actual)
        missing["entries"] = [
            item for item in missing["entries"] if item.get("relative_path") != "roscore.log"
        ]
        mutations.append(missing)
        drift = copy.deepcopy(actual)
        next(item for item in drift["entries"] if item.get("relative_path") == "vins.log")[
            "sha256"
        ] = "0" * 64
        mutations.append(drift)
        for value in mutations:
            with self.subTest(entries=len(value["entries"])), mock.patch.object(
                v2_5, "tree_record", return_value=value
            ), self.assertRaisesRegex(v1.VerificationError, "TREE_REQUIRED_FILE"):
                v2_5.validate_actual_tree_and_naming()

    def test_incident_is_result_informed_and_does_not_rewrite_v2_4(self) -> None:
        record = v2_5.expected_incident_record()
        self.assertTrue(record["v2_4_terminal_fail_is_immutable"])
        self.assertTrue(record["adoption_decision_is_post_incident_and_result_informed"])
        self.assertTrue(
            record["root_cause"]["actual_output_tree_was_not_a_v2_4_reserved_no_clobber_path"]
        )
        self.assertTrue(record["continuation_boundary"]["move_copy_link_cleanup_or_rerun_forbidden"])
        self.assertTrue(record["continuation_boundary"]["significance_superiority_and_three_arm_claims_forbidden"])

    def test_in_memory_two_arm_recompute_has_strict_common_support(self) -> None:
        summary = v2_5.recompute_two_arm_summary()
        self.assertEqual(set(summary["arms"]), set(v2_5.ARM_LABELS))
        self.assertEqual(summary["support"]["grid_count"], 45)
        self.assertTrue(summary["support"]["ape_valid"])
        self.assertTrue(summary["support"]["rpe_valid"])
        self.assertEqual(summary["protocol"], v2_5.frozen_protocol())
        for arm in summary["arms"].values():
            self.assertTrue(math.isfinite(arm["ape_rmse_m"]))
            self.assertTrue(math.isfinite(arm["rpe_rmse_m"]))

    def test_summary_recompute_rejects_semantic_tamper(self) -> None:
        summary = v2_5.recompute_two_arm_summary()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "summary.json"
            tampered = copy.deepcopy(summary)
            tampered["support"]["grid_count"] = 44
            path.write_bytes(v1.canonical_json(tampered))
            with self.assertRaisesRegex(v1.VerificationError, "NOT_RECOMPUTED"):
                v2_5.validate_summary(path)

    def test_evo_crosscheck_is_diagnostic_and_cross_bound_to_primary(self) -> None:
        summary = {
            "support": {"rpe_pairs": 44},
            "arms": {
                label: {"ape_rmse_m": 0.2, "rpe_rmse_m": 0.03}
                for label in v2_5.ARM_LABELS
            },
        }
        arm = {
            "primary_ape_rmse_m": 0.2,
            "evo_ape_rmse_m": 0.2000000001,
            "ape_abs_diff_m": abs(0.2 - 0.2000000001),
            "primary_rpe_rmse_m": 0.03,
            "evo_segmented_rpe_rmse_m": 0.0300000001,
            "rpe_abs_diff_m": abs(0.03 - 0.0300000001),
            "rpe_pair_count": 44,
            "segments": [{"segment_id": 0, "pair_count": 44, "rmse_m": 0.0300000001}],
        }
        record = {
            "evo_version": "1.31.1",
            "rpe_delta_frames": 1,
            "rpe_semantics": "aligned_global_frame_positional_delta",
            "arms": {label: copy.deepcopy(arm) for label in v2_5.ARM_LABELS},
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "evo.json"
            path.write_bytes(v1.canonical_json(record))
            parsed, _identity = v2_5.validate_evo_crosscheck(path, summary)
            self.assertEqual(set(parsed["arms"]), set(v2_5.ARM_LABELS))
            one_ulp = copy.deepcopy(record)
            one_ulp["arms"]["B1_CONSTQ"]["segments"][0]["rmse_m"] = float(v2_5.np.nextafter(
                one_ulp["arms"]["B1_CONSTQ"]["evo_segmented_rpe_rmse_m"],
                math.inf,
            ))
            path.write_bytes(v1.canonical_json(one_ulp))
            v2_5.validate_evo_crosscheck(path, summary)
            tampered = copy.deepcopy(record)
            tampered["arms"]["B1_CONSTQ"]["rpe_pair_count"] = 43
            path.write_bytes(v1.canonical_json(tampered))
            with self.assertRaisesRegex(v1.VerificationError, "PRIMARY_CROSSCHECK"):
                v2_5.validate_evo_crosscheck(path, summary)
            excessive = copy.deepcopy(record)
            excessive["arms"]["B1_CONSTQ"]["segments"][0]["rmse_m"] += 1e-12
            path.write_bytes(v1.canonical_json(excessive))
            with self.assertRaisesRegex(v1.VerificationError, "PRIMARY_CROSSCHECK"):
                v2_5.validate_evo_crosscheck(path, summary)

    def test_evaluator_receipt_contract_is_one_attempt_and_exact_inputs(self) -> None:
        passed = v2_5.evaluator_receipt_record(0)
        failed = v2_5.evaluator_receipt_record(7)
        self.assertEqual(passed["attempt_count"], 1)
        self.assertEqual(passed["actual_process_start_count"], 1)
        self.assertTrue(passed["return_code_observed_after_process"])
        self.assertTrue(passed["no_retry"])
        self.assertEqual(failed["status"], "FAIL_PROCESS_NONZERO")
        self.assertEqual(passed["arms"]["XFEATBIRTH_RAWLK"]["sha256"], v2_5.EXPECTED_ACTUAL_VIO_SHA256)
        for bad in (-1, 256, True):
            with self.subTest(bad=bad), self.assertRaises(v1.VerificationError):
                v2_5.evaluator_receipt_record(bad)

    def test_write_once_is_no_clobber(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "receipt.json"
            result = v2_5.write_once(path, {"status": "x"}, "TEST")
            self.assertEqual(result["sha256"], hashlib.sha256(path.read_bytes()).hexdigest())
            with self.assertRaisesRegex(v1.VerificationError, "ALREADY_EXISTS"):
                v2_5.write_once(path, {"status": "y"}, "TEST")

    def test_command_protocol_is_three_steps_one_evaluator_and_no_algorithm_rerun(self) -> None:
        commands = v2_5.expected_commands()
        self.assertEqual(len(commands), 3)
        joined = "\n".join(commands)
        self.assertEqual(joined.count("scripts/evaluate_vins_common_support.py"), 1)
        self.assertIn(f"/usr/bin/mkdir {v2_5.EVAL_DIR}", commands[2])
        self.assertIn("seal-evaluator-rc", commands[2])
        self.assertIn("seal-post", commands[2])
        for token in (
            "run_aqualoc_archaeo_vins_eval.sh", "export_xfeat_lk_carrier_v1.py",
            "audit_xfeat_lk_carrier_v1.py", "run_hfnet_slam", "bridge_hfnet",
        ):
            self.assertNotIn(token, joined)
        for index, command in enumerate(commands):
            completed = subprocess.run(
                ["/bin/bash", "-n", "-c", command], capture_output=True, text=True
            )
            self.assertEqual(completed.returncode, 0, (index, completed.stderr))

    def test_atomic_eval_dir_claim_precedes_evaluator_in_same_command(self) -> None:
        command = v2_5.expected_commands()[2]
        claim = f"/usr/bin/mkdir {v2_5.EVAL_DIR}"
        evaluator = "scripts/evaluate_vins_common_support.py"
        self.assertLess(command.index(claim), command.index(evaluator))
        self.assertIn(f"{claim} || exit 73", command)
        self.assertIn('if [ "$post_check_rc" -eq 3 ]; then exit 3', command)

    def test_eval_output_tree_is_an_exact_no_symlink_closure(self) -> None:
        regular = {
            "common_grid_audit.csv", "common_support_metrics.csv",
            "common_support_summary.json", "evaluator_process_receipt_v2_5.json",
            "evo_crosscheck.json", "evo_crosscheck/reference_common.tum",
            "evo_crosscheck/reference_segment_000.tum",
        }
        for label in v2_5.ARM_LABELS:
            regular.update({
                f"evo_crosscheck/{label}_common_aligned.tum",
                f"evo_crosscheck/{label}_evo_ape.log",
                f"evo_crosscheck/{label}_evo_rpe_segment_000.log",
                f"evo_crosscheck/{label}_segment_000.tum",
            })
        entries = [{"relative_path": ".", "type": "directory"},
                   {"relative_path": "evo_crosscheck", "type": "directory"}]
        entries.extend(
            {"relative_path": name, "type": "regular", "size_bytes": 1, "sha256": "a" * 64}
            for name in sorted(regular)
        )
        tree = {
            "root": str(v2_5.EVAL_DIR), "entries": entries,
            "summary": {"directory_count": 2, "regular_file_count": len(regular)},
        }
        with mock.patch.object(v2_5, "tree_record", return_value=tree):
            self.assertEqual(v2_5.validate_eval_output_tree(), tree)
        drift = copy.deepcopy(tree)
        drift["entries"].append(
            {"relative_path": "extra.txt", "type": "regular", "size_bytes": 0, "sha256": "0" * 64}
        )
        drift["summary"]["regular_file_count"] += 1
        with mock.patch.object(v2_5, "tree_record", return_value=drift), self.assertRaisesRegex(
            v1.VerificationError, "OUTPUT_TREE_CLOSURE"
        ):
            v2_5.validate_eval_output_tree()

    def test_exact_post_failure_is_evidence_success_but_scientific_rc3(self) -> None:
        record = {"status": v2_5.POST_FAIL}
        identity = {"path": str(v2_5.POST_EVIDENCE), "size_bytes": 1, "sha256": "a" * 64}
        with mock.patch.object(v2_5, "validate_revision"), mock.patch.object(
            v2_5, "build_post_record", return_value=record
        ), mock.patch.object(
            v2_5.v1, "read_regular", return_value=(v1.canonical_json(record), identity)
        ):
            self.assertEqual(v2_5.main(["--action", "check-post"]), 3)

    def test_interpretation_boundary_forbids_ranking_and_confirmatory_claims(self) -> None:
        boundary = v2_5.interpretation_boundary()
        self.assertFalse(boundary["pre_registered_or_confirmatory"])
        self.assertTrue(boundary["adoption_decision_after_native_single_arm_ape_was_visible"])
        self.assertTrue(boundary["reference_is_proxy_and_not_independent_ground_truth"])
        self.assertTrue(boundary["statistical_significance_superiority_ranking_and_three_arm_claims_forbidden"])

    def test_reserved_paths_are_new_and_absent_before_formal_commands(self) -> None:
        self.assertEqual(len(v2_5.RESERVED_PATHS), 3)
        self.assertEqual(len(set(v2_5.RESERVED_PATHS)), 3)
        v2_5.require_paths_absent(v2_5.RESERVED_PATHS, "TEST_RESERVED")
        self.assertNotIn(str(v2_5.ACTUAL_XFEAT_RUN), v2_5.RESERVED_PATHS)
        self.assertNotIn(str(v2_5.EXPECTED_XFEAT_RUN), v2_5.RESERVED_PATHS)

    def test_incident_and_freeze_are_exact_rebuilds_when_materialized(self) -> None:
        if not v2_5.DEFAULT_INCIDENT.exists() or not v2_5.DEFAULT_FREEZE.exists():
            self.skipTest("final incident/freeze not materialized yet")
        incident_payload = v1.canonical_json(builder.build_incident_record())
        freeze_payload = v1.canonical_json(builder.build_freeze_record())
        self.assertEqual(v2_5.DEFAULT_INCIDENT.read_bytes(), incident_payload)
        self.assertEqual(v2_5.DEFAULT_FREEZE.read_bytes(), freeze_payload)
        result = v2_5.validate_revision(v2_5.DEFAULT_FREEZE, require_reserved_absent=True)
        self.assertEqual(result["status"], "PASS_V2_5_START")


if __name__ == "__main__":
    unittest.main()
