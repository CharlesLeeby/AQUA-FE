#!/usr/bin/env python3
"""Process-free tests for additive A08 common-support analysis v5."""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from scripts import run_a08_hfnet_vs_klt_only_common_support_v5 as runner


def fake_identity(name: str = "x", digit: str = "a") -> dict[str, object]:
    return {"path": f"/authority/{name}", "size_bytes": 1, "sha256": digit * 64}


def prior_r01() -> dict[str, object]:
    return {
        "item_id": "KLT_R01", "disposition": runner.R01_DISPOSITION,
        "failure_code": runner.R01_FAILURE_CODE,
        "receipt": fake_identity("r01", "1"), "artifact_accepted": False,
        "rerun_or_replacement_permitted": False,
    }


def prior_r02() -> dict[str, object]:
    trajectory = fake_identity("r02-vio", "2")
    return {
        "item_id": "KLT_R02", "disposition": runner.R02_DISPOSITION,
        "failure_code": runner.R02_FAILURE_CODE,
        "receipt": fake_identity("r02", "3"), "artifact_accepted": False,
        "trajectory_identity": trajectory, "trajectory_admitted": False,
        "replay_completed": True, "post_result_cleanup_failed": True,
        "rerun_or_replacement_permitted": False,
    }


def prior_r03() -> dict[str, object]:
    trajectory = fake_identity("r03-vio", "4")
    artifacts = {"vins_output/vio.csv": trajectory}
    return {
        "item_id": "KLT_R03", "disposition": runner.R03_DISPOSITION,
        "failure_code": runner.R03_FAILURE_CODE,
        "receipt": fake_identity("r03", "5"),
        "v4_execution_lock": fake_identity("v4-lock", "6"),
        "analysis_v4_design_freeze": fake_identity("v4-freeze", "9"),
        "v4_base_artifact_audit": "PASS",
        "v4_artifact_receipt_reconstruction": "PASS",
        "v4_base_prior_receipt_audit": "FAIL_EXPECTED_R03_INFRASTRUCTURE",
        "v4_base_prior_failure_code": runner.R03_PRIOR_DEEP_FAILURE,
        "v4_strict_prior_receipt_audit": "FAIL_EXPECTED_R03_INFRASTRUCTURE",
        "v4_strict_prior_failure_code": runner.R03_PRIOR_DEEP_FAILURE,
        "receipt_status": "FAILED_BACKEND_REPLAY_NO_REPLACEMENT",
        "execution_integrity": "FAIL_EXPECTED_INFRASTRUCTURE_AUDIT_CONTRACT",
        "integrity_fault_latch": [runner.R03_INTEGRITY_LATCH],
        "runtime_timed_out": False, "raw_return_code": 0,
        "artifact_contract_status": "FAIL",
        "artifact_issue": runner.R03_ARTIFACT_ISSUE,
        "artifact_integrity_issue": runner.R03_INTEGRITY_ISSUE,
        "artifact_integrity_issues": [runner.R03_INTEGRITY_ISSUE],
        "evidence_tree_integrity": True,
        "complete_artifacts_identity_bound": True, "artifact_accepted": False,
        "complete_artifacts": True, "complete_artifact_identities": artifacts,
        "process_log": fake_identity("r03-log", "7"),
        "trajectory_complete": True, "trajectory_rows": 2319,
        "trajectory_identity": trajectory, "trajectory_admitted": False,
        "diagnostic_ape_identity": fake_identity("r03-ape", "8"),
        "diagnostic_ape_admitted_to_common_support": False,
        "backend_usability_status": "PASS", "replay_manifest_semantic_status": "PASS",
        "replay_guard_status": "PASS", "overlay_signal_mask_status": "PASS",
        "vins_lifecycle_status": "FAIL_EXPECTED_LOCKED_ENV_AUDIT_MISMATCH",
        "locked_item_ros_hostname_present": False,
        "observed_overlay_ros_hostname": "localhost",
        "runtime_lifecycle_ros_hostname": "localhost",
        "all_other_selected_scientific_environment_equal": True,
        "only_permitted_v5_environment_addition":
            dict(runner.V5_ENVIRONMENT_AMENDMENT),
        "replay_completed": True, "post_result_cleanup_completed": True,
        "counts_as_valid_repeat": False,
        "rerun_or_replacement_permitted": False,
    }


def exclusion() -> dict[str, object]:
    return {
        "disposition": runner.XFEAT_DISPOSITION,
        "accepted_frontend_receipt_present": False,
        "backend_items_launched": 0, "backend_trajectory_admitted": False,
        "learning_contribution_claim_permitted": False,
    }


class AnalysisV5ProtocolTests(unittest.TestCase):
    def test_frozen_v4_lineage_is_byte_identical(self) -> None:
        analysis = {
            "protocol": runner.ANALYSIS_V4_PROTOCOL,
            "runner": runner.ANALYSIS_V4_RUNNER,
            "tests": runner.ANALYSIS_V4_TESTS,
            "design_freeze": runner.ANALYSIS_V4_DESIGN_FREEZE,
        }
        backend = {
            "protocol": runner.BACKEND_V4_PROTOCOL,
            "runner": runner.BACKEND_V4_RUNNER,
            "guard": runner.BACKEND_V4_GUARD,
            "lifecycle_wrapper": runner.BACKEND_V4_LIFECYCLE_WRAPPER,
            "signal_mask_launcher": runner.BACKEND_V4_SIGNAL_MASK_LAUNCHER,
            "tests": runner.BACKEND_V4_TESTS,
            "execution_lock": runner.BACKEND_V4_LOCK,
        }
        for label, path in analysis.items():
            raw = path.read_bytes()
            self.assertEqual((len(raw), hashlib.sha256(raw).hexdigest()),
                             runner.FROZEN_ANALYSIS_V4_EXPECTED[label])
        for label, path in backend.items():
            raw = path.read_bytes()
            self.assertEqual((len(raw), hashlib.sha256(raw).hexdigest()),
                             runner.FROZEN_BACKEND_V4_EXPECTED[label])

    def test_population_contract_is_planned_five_executable_two(self) -> None:
        contract = runner.design_contract_snapshot()
        population = contract["population_and_failure_rules"]
        self.assertEqual(population["backend_item_order"], list(runner.FULL_ITEM_ORDER))
        self.assertEqual(population["v5_backend_item_order"], ["KLT_R04", "KLT_R05"])
        self.assertEqual(population["klt_planned_count"], 5)
        self.assertEqual(population["maximum_valid_klt_count"], 2)
        self.assertEqual(population["r01_failure_code"], runner.R01_FAILURE_CODE)
        self.assertEqual(population["r03_disposition"], runner.R03_DISPOSITION)
        self.assertEqual(population["r03_failure_code"], runner.R03_FAILURE_CODE)
        for repeat in (1, 2, 3):
            self.assertFalse(population[f"r{repeat:02d}_counts_as_valid"])
        self.assertTrue(population["three_infrastructure_na_slots_retained"])
        self.assertNotIn("two_infrastructure_na_slots_retained", population)
        self.assertFalse(population["best_repeat_selection_permitted"])
        self.assertEqual(
            contract["v5_environment_amendment"],
            {
                "only_permitted_scientific_environment_addition": {
                    "ROS_HOSTNAME": "localhost",
                },
                "all_other_scientific_signal_lifecycle_values_unchanged": True,
                "reuse_frozen_v4_lifecycle_wrapper": True,
                "reuse_frozen_v4_signal_mask_launcher": True,
            },
        )

    def test_numeric_rules_are_identical_to_frozen_v4(self) -> None:
        current = runner.design_contract_snapshot()
        frozen = runner._V4_DESIGN_CONTRACT_SNAPSHOT()
        self.assertEqual(current["numeric_rules"], frozen["numeric_rules"])
        self.assertEqual(current["numeric_rules"]["fixed_denominator"], 33)
        self.assertEqual(current["numeric_rules"]["min_common_coverage"], 0.70)
        self.assertTrue(current["numeric_rules"]["proper_fixed_scale_se3"])
        self.assertFalse(current["numeric_rules"]["sim3_or_scale_fit"])
        self.assertEqual(current["numeric_rules"]["evo_abs_tolerance_m"], 1e-5)
        self.assertTrue(
            current["execution_rules"]["dynamic_lock_after_two_v5_terminal_receipts_before_accuracy"]
        )
        protocol = runner.PROTOCOL.read_text(encoding="utf-8")
        self.assertIn("at least 70", protocol)
        self.assertIn("percent common coverage", protocol)
        self.assertNotIn("at least 90", protocol)

    def test_real_r03_exact_reconstruction_and_expected_deep_failures(self) -> None:
        value = runner.prior_r03_binding()
        self.assertEqual(
            (value["receipt"]["size_bytes"], value["receipt"]["sha256"]),
            runner.R03_TERMINAL_EXPECTED,
        )
        self.assertEqual(value["v4_artifact_receipt_reconstruction"], "PASS")
        self.assertEqual(value["v4_base_artifact_audit"], "PASS")
        self.assertEqual(
            value["v4_base_prior_receipt_audit"],
            "FAIL_EXPECTED_R03_INFRASTRUCTURE",
        )
        self.assertEqual(value["v4_base_prior_failure_code"], runner.R03_PRIOR_DEEP_FAILURE)
        self.assertEqual(
            value["v4_strict_prior_receipt_audit"],
            "FAIL_EXPECTED_R03_INFRASTRUCTURE",
        )
        self.assertEqual(value["v4_strict_prior_failure_code"], runner.R03_PRIOR_DEEP_FAILURE)
        self.assertEqual(len(value["complete_artifact_identities"]), 14)
        self.assertTrue(value["trajectory_complete"])
        self.assertEqual(value["trajectory_rows"], 2319)
        self.assertFalse(value["trajectory_admitted"])
        self.assertEqual(value["execution_integrity"],
                         "FAIL_EXPECTED_INFRASTRUCTURE_AUDIT_CONTRACT")

    def test_r03_root_cause_is_exact_single_environment_delta(self) -> None:
        value = runner.prior_r03_binding()
        self.assertFalse(value["locked_item_ros_hostname_present"])
        self.assertEqual(value["observed_overlay_ros_hostname"], "localhost")
        self.assertEqual(value["artifact_issue"], runner.R03_ARTIFACT_ISSUE)
        self.assertEqual(value["artifact_integrity_issue"], runner.R03_INTEGRITY_ISSUE)
        self.assertEqual(value["integrity_fault_latch"], [runner.R03_INTEGRITY_LATCH])
        self.assertEqual(value["backend_usability_status"], "PASS")
        self.assertEqual(value["replay_manifest_semantic_status"], "PASS")
        self.assertTrue(value["post_result_cleanup_completed"])

    def test_r03_tamper_cannot_be_relabelled_or_admitted(self) -> None:
        module = runner.load_backend_v4_authority_module()
        bindings = module.resolve_frontend_bindings()
        lock, lock_id = module.verify_lock(runner.BACKEND_V4_LOCK, bindings)
        receipt, receipt_id = runner.stable_json(runner.R03_RECEIPT)
        item = lock["items"]["KLT_R03"]
        reconstructed = module.artifact_audit(item)
        relabelled = copy.deepcopy(receipt)
        relabelled["status"] = "PASS_BACKEND_REPLAY_ACCEPTED"
        with self.assertRaisesRegex(runner.AnalysisProtocolError, "R03_TERMINAL_CONTROL"):
            runner.validate_r03_terminal_receipt(
                relabelled, receipt_id, lock_id, item, reconstructed
            )
        degraded = copy.deepcopy(receipt)
        degraded["artifact_contract"]["semantic_checks"]["trajectory"]["rows"] = 2318
        degraded_artifact = degraded["artifact_contract"]
        with self.assertRaisesRegex(
            runner.AnalysisProtocolError,
            "R03_COMPLETE_REPLAY_SINGLE_ENV_AUDIT_MISMATCH",
        ):
            runner.validate_r03_terminal_receipt(
                degraded, receipt_id, lock_id, item, degraded_artifact
            )

    def test_three_prior_rows_are_permanent_infrastructure_na(self) -> None:
        rows = [
            runner._r01_population_row(prior_r01()),
            runner._r02_population_row(prior_r02()),
            runner._r03_population_row(prior_r03()),
        ]
        self.assertTrue(all(not row["accepted_for_joint_mask"] for row in rows))
        self.assertTrue(all(row["backend_infrastructure_failure_retained_as_na"] for row in rows))
        self.assertIsNone(rows[2]["trajectory"])
        self.assertTrue(rows[2]["backend_replay_completed"])
        self.assertFalse(rows[2]["post_result_cleanup_failed"])
        self.assertIn("complete_unaccepted_trajectory", rows[2])

    def test_accepted_arm_paths_excludes_r01_r02_r03(self) -> None:
        backend = {"planned_repeats": [
            runner._r01_population_row(prior_r01()),
            runner._r02_population_row(prior_r02()),
            runner._r03_population_row(prior_r03()),
            {"item_id": "KLT_R04", "accepted_for_joint_mask": True,
             "trajectory": {"path": "/accepted/r04.csv"}},
            {"item_id": "KLT_R05", "accepted_for_joint_mask": True,
             "trajectory": {"path": "/accepted/r05.csv"}},
        ]}
        paths = runner.accepted_arm_paths(backend)
        self.assertEqual(list(paths), ["HFNET", "KLT_R04", "KLT_R05"])

    def test_coordinatewise_median_uses_all_valid_r04_r05(self) -> None:
        rows = [{name: value for name in runner.PRIMARY_METRICS}
                for value in (1.0, 3.0)]
        observed = runner.median_metrics(rows)
        for name in runner.PRIMARY_METRICS:
            self.assertEqual(observed[name], 2.0)
        single = runner.median_metrics([
            {name: 1.25 for name in runner.PRIMARY_METRICS}
        ])
        for name in runner.PRIMARY_METRICS:
            self.assertEqual(single[name], 1.25)

    def _payload(self) -> dict[str, object]:
        missing = {"backend_v5_execution_lock": "MISSING", **{
            item: "MISSING" for item in runner.V5_ITEM_ORDER
        }}
        absent = {"backend_v5_root": "ABSENT", "backend_v5_runtime_root": "ABSENT", **{
            f"workspace:{item}": "ABSENT" for item in runner.V5_ITEM_ORDER
        }}
        old_absent = {
            f"{kind}:{item}": "ABSENT" for item in runner.V5_ITEM_ORDER
            for kind in ("output", "runtime", "workspace")
        }
        patches = (
            mock.patch.object(runner, "backend_v5_terminal_presence", return_value=missing),
            mock.patch.object(runner, "backend_v5_campaign_prelaunch_presence", return_value=absent),
            mock.patch.object(runner, "v4_remaining_r04_r05_presence", return_value=old_absent),
            mock.patch.object(runner, "analysis_output_state", return_value="ABSENT"),
            mock.patch.object(runner, "_require_prior_analysis_diversions_untouched"),
            mock.patch.object(runner.ENGINE, "regular_absence"),
            mock.patch.object(runner, "prior_r01_binding", return_value=prior_r01()),
            mock.patch.object(runner, "prior_r02_binding", return_value=prior_r02()),
            mock.patch.object(runner, "prior_r03_binding", return_value=prior_r03()),
            mock.patch.object(runner, "collect_static_identities",
                              return_value={"runner": fake_identity("runner")}),
            mock.patch.object(runner.common, "collect_support_binding",
                              return_value={"support": "sealed"}),
            mock.patch.object(runner, "collect_klt_frontend_binding",
                              return_value={"receipt": fake_identity("klt")}),
            mock.patch.object(runner, "collect_xfeat_exclusion", return_value=exclusion()),
            mock.patch.object(runner.common, "collect_evo_authority",
                              return_value={"version": "evo"}),
        )
        for patcher in patches:
            patcher.start(); self.addCleanup(patcher.stop)
        return runner.build_design_freeze_payload("CANDIDATE_NOT_PUBLISHED")

    def test_design_freeze_payload_records_three_na_and_no_v5_results(self) -> None:
        payload = self._payload()
        self.assertEqual(payload["schema_version"], runner.DESIGN_FREEZE_SCHEMA)
        self.assertEqual(payload["status"], runner.DESIGN_FREEZE_STATUS)
        self.assertEqual(payload["prior_r03"]["disposition"], runner.R03_DISPOSITION)
        self.assertFalse(payload["prior_r03"]["trajectory_admitted"])
        boundary = payload["claim_boundary"]
        self.assertTrue(boundary["r03_complete_artifacts_identity_bound_but_unaccepted"])
        self.assertTrue(boundary["r01_r02_r03_terminal_failures_opened_only_for_exclusion"])
        self.assertFalse(boundary["r03_trajectory_opened_for_common_support"])
        self.assertFalse(boundary["backend_v5_execution_lock_built"])
        self.assertEqual(boundary["v5_backend_items_started"], 0)
        self.assertFalse(boundary["ape_or_rpe_computed_for_v5"])
        self.assertFalse(boundary["final_dynamic_analysis_lock_built"])
        unsigned = dict(payload); digest = unsigned.pop("freeze_sha256")
        self.assertEqual(digest, runner.compact_sha256(unsigned))

    def test_design_freeze_rejects_old_v4_r04_r05_touch(self) -> None:
        missing = {"backend_v5_execution_lock": "MISSING", **{
            item: "MISSING" for item in runner.V5_ITEM_ORDER
        }}
        prelaunch = {"backend_v5_root": "ABSENT", "backend_v5_runtime_root": "ABSENT", **{
            f"workspace:{item}": "ABSENT" for item in runner.V5_ITEM_ORDER
        }}
        old = {f"{kind}:{item}": "ABSENT" for item in runner.V5_ITEM_ORDER
               for kind in ("output", "runtime", "workspace")}
        old["output:KLT_R04"] = "PRESENT"
        with mock.patch.object(runner, "backend_v5_terminal_presence", return_value=missing), \
             mock.patch.object(runner, "backend_v5_campaign_prelaunch_presence", return_value=prelaunch), \
             mock.patch.object(runner, "v4_remaining_r04_r05_presence", return_value=old):
            with self.assertRaisesRegex(runner.AnalysisProtocolError,
                                        "OLD_V4_R04_R05_MUST_REMAIN_UNTOUCHED"):
                runner.build_design_freeze_payload("never")

    def test_frozen_design_binding_live_rechecks_old_v4_and_prior_diversions(self) -> None:
        payload = self._payload()
        freeze_id = fake_identity("v5-freeze", "f")
        absent = {
            f"{kind}:{item}": "ABSENT" for item in runner.V5_ITEM_ORDER
            for kind in ("output", "runtime", "workspace")
        }
        untouched = mock.Mock()
        with mock.patch.object(runner, "stable_json", return_value=(payload, freeze_id)), \
             mock.patch.object(runner, "v4_remaining_r04_r05_presence",
                               return_value=absent), \
             mock.patch.object(runner, "_require_prior_analysis_diversions_untouched",
                               untouched):
            observed = runner.collect_design_freeze_binding()
        self.assertEqual(observed["identity"], freeze_id)
        untouched.assert_called_once_with()

        touched = dict(absent); touched["runtime:KLT_R05"] = "PRESENT"
        with mock.patch.object(runner, "stable_json", return_value=(payload, freeze_id)), \
             mock.patch.object(runner, "v4_remaining_r04_r05_presence",
                               return_value=touched):
            with self.assertRaisesRegex(
                runner.AnalysisProtocolError,
                "FROZEN_V4_R04_R05_MUST_REMAIN_UNTOUCHED",
            ):
                runner.collect_design_freeze_binding()

    def test_static_identity_keyset_includes_backend_v5_and_r03_lineage(self) -> None:
        frozen = {name: fake_identity(name) for name in (
            "analysis_v4_protocol", "analysis_v4_runner", "analysis_v4_tests",
            "analysis_v4_design_freeze", "backend_v4_protocol", "backend_v4_runner",
            "backend_v4_guard", "backend_v4_lifecycle_wrapper",
            "backend_v4_signal_mask_launcher", "backend_v4_tests",
            "backend_v4_execution_lock",
        )}

        def observed(path: Path) -> dict[str, object]:
            if path == runner.R03_RECEIPT:
                return {"path": str(path), "size_bytes": runner.R03_TERMINAL_EXPECTED[0],
                        "sha256": runner.R03_TERMINAL_EXPECTED[1]}
            return fake_identity(path.name)

        with mock.patch.object(runner, "_check_frozen_lineage_identities", return_value=frozen), \
             mock.patch.object(runner, "identity", side_effect=observed):
            values = runner.collect_static_identities()
        required = {
            "backend_v5_protocol", "backend_v5_runner", "backend_v5_guard",
            "backend_v5_lifecycle_wrapper", "backend_v5_signal_mask_launcher",
            "backend_v5_process_free_tests", "backend_v5_python38",
            "backend_v5_vins_node", "analysis_v4_design_freeze",
            "backend_v4_execution_lock", "v4_r03_terminal_receipt",
        }
        self.assertTrue(required <= set(values))

    def test_backend_v5_reuses_frozen_v4_lifecycle_authorities(self) -> None:
        self.assertEqual(runner.BACKEND_V5_LIFECYCLE_WRAPPER,
                         runner.BACKEND_V4_LIFECYCLE_WRAPPER)
        self.assertEqual(runner.BACKEND_V5_SIGNAL_MASK_LAUNCHER,
                         runner.BACKEND_V4_SIGNAL_MASK_LAUNCHER)

    def test_real_candidate_freeze_passes_backend_v5_cross_gate_process_free(self) -> None:
        payload = runner.build_design_freeze_payload("PROCESS_FREE_CROSS_GATE")
        backend = runner.load_backend_v5_authority_module()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "candidate-freeze.json"
            path.write_text(
                json.dumps(payload, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            with mock.patch.object(backend, "ANALYSIS_V5_DESIGN_FREEZE", path):
                binding = backend.collect_analysis_v5_design_freeze_binding()
            tamper_cases = {
                "sealed_support": lambda value: value.__setitem__("sealed_support", {}),
                "klt_frontend": lambda value: value.__setitem__("klt_frontend", {}),
                "excluded_xfeat": lambda value: value.__setitem__("excluded_xfeat", {}),
                "evo_authority": lambda value: value.__setitem__("evo_authority", {}),
                "primary_evaluator": lambda value: value["static_identities"].__setitem__(
                    "primary_evaluator", fake_identity("tampered-primary", "0")
                ),
            }
            for label, mutate in tamper_cases.items():
                with self.subTest(recomputed_digest_tamper=label):
                    tampered = copy.deepcopy(payload)
                    tampered.pop("freeze_sha256")
                    mutate(tampered)
                    tampered["freeze_sha256"] = runner.compact_sha256(tampered)
                    path.write_text(
                        json.dumps(tampered, indent=2, sort_keys=True) + "\n",
                        encoding="utf-8",
                    )
                    with mock.patch.object(backend, "ANALYSIS_V5_DESIGN_FREEZE", path):
                        with self.assertRaises(RuntimeError):
                            backend.collect_analysis_v5_design_freeze_binding()
        self.assertEqual(binding["schema_version"], runner.DESIGN_FREEZE_SCHEMA)
        self.assertEqual(binding["status"], runner.DESIGN_FREEZE_STATUS)
        self.assertFalse(binding["prior_r03"]["trajectory_admitted"])
        self.assertEqual(
            binding["population_and_failure_rules"]["maximum_valid_klt_count"], 2
        )
        self.assertEqual(
            binding["v5_environment_amendment"]
                ["only_permitted_scientific_environment_addition"],
            runner.V5_ENVIRONMENT_AMENDMENT,
        )

    def test_preflight_waits_for_backend_v5_sources_without_writes(self) -> None:
        presence = {
            "backend_v5_protocol": "MISSING", "backend_v5_runner": "MISSING",
            "backend_v5_guard": "PRESENT_REGULAR",
            "backend_v5_lifecycle_wrapper": "PRESENT_REGULAR",
            "backend_v5_signal_mask_launcher": "PRESENT_REGULAR",
            "backend_v5_process_free_tests": "MISSING",
            "backend_v5_python38": "PRESENT_REGULAR",
            "backend_v5_vins_node": "PRESENT_REGULAR",
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            receipt = root / "receipt.json"; receipt.write_text("{}\n")
            freeze = root / "freeze.json"; lock = root / "lock.json"
            with mock.patch.multiple(
                runner, R03_RECEIPT=receipt, DESIGN_FREEZE=freeze, DEFAULT_LOCK=lock,
            ), mock.patch.object(
                runner, "backend_v5_authority_source_presence", return_value=presence
            ):
                result = runner.preflight_readonly(lock)
        self.assertEqual(result["status"], "WAITING_BACKEND_V5_CANDIDATE_AUTHORITIES")
        self.assertFalse(result["accuracy_computed"])

    def test_preflight_blocks_premature_analysis_lock_before_two_terminals(self) -> None:
        presence = {
            "backend_v5_execution_lock": "PRESENT_REGULAR",
            "KLT_R04": "PRESENT_REGULAR", "KLT_R05": "MISSING",
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            freeze = root / "freeze.json"; freeze.write_text("{}\n")
            lock = root / "lock.json"; lock.write_text("premature\n")
            with mock.patch.multiple(
                runner, DESIGN_FREEZE=freeze, DEFAULT_LOCK=lock,
            ), mock.patch.object(
                runner, "design_freeze_audit_readonly",
                return_value={"status":
                              "PASS_DESIGN_FROZEN_AFTER_R01_R02_R03_BEFORE_R04_R05"},
            ), mock.patch.object(
                runner, "backend_v5_terminal_presence", return_value=presence,
            ):
                result = runner.preflight_readonly(lock)
        self.assertEqual(
            result["status"],
            "BLOCKED_PREMATURE_ANALYSIS_V5_LOCK_BEFORE_TWO_BACKEND_TERMINAL_RECEIPTS",
        )
        self.assertTrue(result["analysis_lock_present"])
        self.assertFalse(result["accuracy_computed"])

    def test_build_lock_rejects_missing_r05_before_authority(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "lock.json"
            presence = {"backend_v5_execution_lock": "PRESENT_REGULAR",
                        "KLT_R04": "PRESENT_REGULAR", "KLT_R05": "MISSING"}
            authority = mock.Mock(side_effect=AssertionError("must not collect"))
            with mock.patch.object(runner, "DEFAULT_LOCK", path), \
                 mock.patch.object(runner, "analysis_output_state", return_value="ABSENT"), \
                 mock.patch.object(runner, "collect_design_freeze_binding", return_value={}), \
                 mock.patch.object(runner, "backend_v5_terminal_presence", return_value=presence), \
                 mock.patch.object(runner, "collect_authority", authority):
                with self.assertRaisesRegex(runner.AnalysisProtocolError,
                                            "TWO_V5_TERMINAL_RECEIPTS_REQUIRED"):
                    runner.build_lock(path, runner.BUILD_LOCK_TOKEN)
            self.assertFalse(path.exists()); authority.assert_not_called()

    def test_build_lock_is_identity_only_no_accuracy(self) -> None:
        authority = {"backend": {"planned_count": 5, "maximum_valid_count": 2,
                                 "valid_count": 1}, "excluded_xfeat": exclusion()}
        presence = {"backend_v5_execution_lock": "PRESENT_REGULAR",
                    "KLT_R04": "PRESENT_REGULAR", "KLT_R05": "PRESENT_REGULAR"}
        numeric = mock.Mock(side_effect=AssertionError("accuracy forbidden"))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "lock.json"
            with mock.patch.object(runner, "DEFAULT_LOCK", path), \
                 mock.patch.object(runner, "analysis_output_state", return_value="ABSENT"), \
                 mock.patch.object(runner, "collect_design_freeze_binding", return_value={}), \
                 mock.patch.object(runner, "backend_v5_terminal_presence", return_value=presence), \
                 mock.patch.object(runner, "collect_authority", return_value=authority), \
                 mock.patch.object(runner, "evaluate_joint_inputs", numeric):
                result = runner.build_lock(path, runner.BUILD_LOCK_TOKEN)
            self.assertTrue(path.is_file()); self.assertFalse(result["accuracy_computed"])
            self.assertEqual(result["maximum_valid_klt_count"], 2)
            numeric.assert_not_called()

    def test_formal_summary_keeps_r03_out_of_mask_and_median(self) -> None:
        from scripts.tests.test_run_a08_hfnet_vs_klt_only_common_support_v2 import (
            pass_evo_audit, primary_summary, synthetic_lock,
        )
        lock = synthetic_lock((4, 5))
        rows = lock["authority"]["backend"]["planned_repeats"]
        rows[0].update(runner._r01_population_row(prior_r01()))
        rows[1].update(runner._r02_population_row(prior_r02()))
        rows[2].update(runner._r03_population_row(prior_r03()))
        lock["authority"]["backend"].update({
            "maximum_valid_count": 2, "infrastructure_na_count": 3,
        })
        primary = primary_summary((4, 5), (0.6, 0.2))
        formal = runner.build_formal_summary(
            lock, primary, runner.support_gate(primary), pass_evo_audit()
        )
        runner.validate_formal_population_binding(formal, lock)
        self.assertEqual(formal["single_joint_mask_arm_set"],
                         ["HFNET", "KLT_R04", "KLT_R05"])
        self.assertEqual(formal["klt"]["planned_count"], 5)
        self.assertEqual(formal["klt"]["valid_count"], 2)
        self.assertEqual(formal["klt"]["formal_median_metrics"]["ape_rmse_m"], 0.4)
        r03 = formal["planned_klt_repeats"][2]
        self.assertEqual(r03["terminal_disposition"], runner.R03_DISPOSITION)
        self.assertFalse(r03["accepted_for_single_joint_mask"])
        self.assertFalse(r03["post_result_cleanup_failed"])

    def test_canonical_v5_freeze_lock_outputs_and_backend_are_absent(self) -> None:
        for path in (
            runner.DESIGN_FREEZE, runner.DEFAULT_LOCK, runner.OUTPUT_ROOT,
            runner.CLAIM_PATH, runner.BACKEND_V5_LOCK, runner.BACKEND_V5_ROOT,
            runner.BACKEND_V5_RUNTIME_ROOT,
        ):
            self.assertFalse(path.exists() or path.is_symlink(), str(path))


if __name__ == "__main__":
    unittest.main()
