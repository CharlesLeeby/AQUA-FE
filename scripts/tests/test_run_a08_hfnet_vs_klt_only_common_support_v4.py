#!/usr/bin/env python3
"""Process-free tests for the additive A08 common-support analysis v4."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from scripts import run_a08_hfnet_vs_klt_only_common_support_v4 as runner


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
        "receipt": fake_identity("r02", "3"),
        "v3_execution_lock": fake_identity("v3-lock", "4"),
        "base_deep_terminal_evidence_audit": "PASS",
        "v3_strict_deep_terminal_evidence_audit":
            "FAIL_EXPECTED_LEGACY_REPLAY_MANIFEST_SCHEMA",
        "v3_strict_deep_failure_code": runner.R02_V3_WRAPPER_DEEP_FAILURE,
        "receipt_status": "FAILED_BACKEND_REPLAY_NO_REPLACEMENT",
        "execution_integrity": "PASS", "runtime_timed_out": True,
        "raw_return_code": -9, "artifact_contract_status": "FAIL",
        "artifact_issue": runner.R02_ARTIFACT_ISSUE,
        "evidence_tree_integrity": True,
        "complete_artifacts_identity_bound": True,
        "artifact_accepted": False,
        "complete_artifacts": True,
        "complete_artifact_identities": {"vins_output/vio.csv": trajectory},
        "process_log": fake_identity("r02-log", "5"),
        "trajectory_complete": True, "trajectory_rows": 2319,
        "trajectory_identity": trajectory, "trajectory_admitted": False,
        "diagnostic_ape_identity": fake_identity("r02-ape", "6"),
        "diagnostic_ape_admitted_to_common_support": False,
        "backend_usability_status": "PASS",
        "replay_manifest_semantic_status": "FAIL_EXPECTED_LEGACY_SCHEMA",
        "replay_manifest_missing_keys": list(runner.R02_REPLAY_MANIFEST_MISSING_KEYS),
        "guard_post_replay_append_not_executed_before_supervisor_timeout": True,
        "replay_completed": True, "post_result_cleanup_failed": True,
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


def synthetic_r02_terminal(root: Path) -> tuple[dict[str, object], dict[str, object],
                                                 dict[str, object], dict[str, object]]:
    expected_outputs = [
        "vins_output/vio.csv", "vins.log", "ape.txt", "replay_manifest.txt",
        "vins_aqualoc_archaeo_external.yaml", "aqualoc_archaeo08_pinhole.yaml",
        "vins_env_manifest.txt", "roscore.log", "network_namespace_manifest.json",
        "replay_only_guard_manifest.json", "frontend_metrics.csv",
    ]
    outputs: dict[str, object] = {}
    for relative in expected_outputs:
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"sealed:{relative}\n", encoding="utf-8")
        outputs[relative] = runner.identity(path)
    log = root / "supervisor_process.log"
    log.write_text("complete replay then cleanup wait timeout\n", encoding="utf-8")
    lock_id = fake_identity("backend-v3-lock", "7")
    item = {"item_id": "KLT_R02", "expected_outputs": expected_outputs}
    receipt = {
        "schema_version": "aqua-fe-a08-recovered-july-backend-klt-only-remaining-receipt-v3",
        "status": "FAILED_BACKEND_REPLAY_NO_REPLACEMENT",
        "item_id": "KLT_R02", "repeat_index": 2,
        "execution_lock": lock_id, "launch_allowance_consumed": True,
        "retry_count": 0, "replacement_permitted": False,
        "supervisor_errors": [], "trajectory_convention": "world_T_body",
        "integrity_fault_latch": [], "process_log": runner.identity(log),
        "runtime": {
            "popen_invocation_count": 1, "child_started": True,
            "timed_out": True, "raw_return_code": -9,
            "process_group": {"leader_reaped": True, "process_group_empty": True,
                              "owned_descendants_empty": True},
        },
        "execution_integrity": {
            "status": "PASS", "irreversible_fault_latch_clear": True,
            "claim_stable": True, "workspace_binding_stable": True,
            "owned_processes_drained": True, "artifact_integrity_issues": [],
        },
        "artifact_contract": {
            "status": "FAIL", "issues": [runner.R02_ARTIFACT_ISSUE], "outputs": outputs,
            "evidence_tree_integrity": True, "integrity_issues": [],
            "semantic_checks": {
                "trajectory": {"rows": 2319, "convention": "world_T_body"},
                "backend_usability": {
                    "status": "PASS", "values": {"output_poses": 2319.0}
                },
                "replay_manifest": {
                    "status": "FAIL",
                    "missing_keys": list(runner.R02_REPLAY_MANIFEST_MISSING_KEYS),
                    "conflicting_keys": [], "child_self_fd_value_keys": [],
                    "explicit_lineage_conflict": False,
                    "sealed_fd_owner_pid": 12345,
                },
                "replay_only_guard": {"status": "PASS", "sealed_fd_owner_pid": 12345},
                "network_namespace": {"status": "PASS"},
            },
        },
    }
    receipt["runtime"]["pid"] = 12345
    receipt_id = {"path": str(root / "receipt.json"), "size_bytes": 123,
                  "sha256": "8" * 64}
    return receipt, receipt_id, lock_id, item


class AnalysisV4ProtocolTests(unittest.TestCase):
    def test_frozen_v3_lineage_is_byte_identical(self) -> None:
        analysis = {
            "protocol": runner.ANALYSIS_V3_PROTOCOL,
            "runner": runner.ANALYSIS_V3_RUNNER,
            "tests": runner.ANALYSIS_V3_TESTS,
            "design_freeze": runner.ANALYSIS_V3_DESIGN_FREEZE,
        }
        backend = {
            "protocol": runner.BACKEND_V3_PROTOCOL,
            "runner": runner.BACKEND_V3_RUNNER,
            "guard": runner.BACKEND_V3_GUARD,
            "tests": runner.BACKEND_V3_TESTS,
            "execution_lock": runner.BACKEND_V3_LOCK,
        }
        for label, path in analysis.items():
            raw = path.read_bytes()
            self.assertEqual((len(raw), hashlib.sha256(raw).hexdigest()),
                             runner.FROZEN_ANALYSIS_V3_EXPECTED[label])
        for label, path in backend.items():
            raw = path.read_bytes()
            self.assertEqual((len(raw), hashlib.sha256(raw).hexdigest()),
                             runner.FROZEN_BACKEND_V3_EXPECTED[label])

    def test_population_contract_is_exact_five_plus_three(self) -> None:
        contract = runner.design_contract_snapshot()
        population = contract["population_and_failure_rules"]
        self.assertEqual(population["backend_item_order"], list(runner.FULL_ITEM_ORDER))
        self.assertEqual(population["v4_backend_item_order"], list(runner.V4_ITEM_ORDER))
        self.assertEqual(population["klt_planned_count"], 5)
        self.assertEqual(population["maximum_valid_klt_count"], 3)
        self.assertEqual(population["r01_disposition"], runner.R01_DISPOSITION)
        self.assertEqual(population["r02_disposition"], runner.R02_DISPOSITION)
        self.assertEqual(population["r02_failure_code"], runner.R02_FAILURE_CODE)
        self.assertFalse(population["r01_counts_as_valid"])
        self.assertFalse(population["r02_counts_as_valid"])
        self.assertFalse(population["r02_complete_trajectory_admitted"])
        self.assertFalse(population["best_repeat_selection_permitted"])

    def test_numeric_rules_are_identical_to_frozen_v3(self) -> None:
        current = runner.design_contract_snapshot()
        frozen = runner._V3_DESIGN_CONTRACT_SNAPSHOT()
        self.assertEqual(current["numeric_rules"], frozen["numeric_rules"])
        self.assertEqual(current["numeric_rules"]["fixed_denominator"], 33)
        self.assertTrue(current["numeric_rules"]["proper_fixed_scale_se3"])
        self.assertFalse(current["numeric_rules"]["sim3_or_scale_fit"])
        self.assertEqual(current["numeric_rules"]["evo_abs_tolerance_m"], 1e-5)

    def test_r01_r02_rows_are_permanent_infrastructure_na(self) -> None:
        r01 = runner._r01_population_row(prior_r01())
        r02 = runner._r02_population_row(prior_r02())
        self.assertFalse(r01["accepted_for_joint_mask"])
        self.assertFalse(r01["backend_replay_completed"])
        self.assertTrue(r01["backend_infrastructure_failure_retained_as_na"])
        self.assertFalse(r02["accepted_for_joint_mask"])
        self.assertIsNone(r02["trajectory"])
        self.assertTrue(r02["backend_replay_completed"])
        self.assertTrue(r02["post_result_cleanup_failed"])
        self.assertTrue(r02["backend_infrastructure_failure_retained_as_na"])
        self.assertIn("complete_unaccepted_trajectory", r02)

    def test_accepted_arm_paths_excludes_both_prior_slots(self) -> None:
        backend = {"planned_repeats": [
            runner._r01_population_row(prior_r01()),
            runner._r02_population_row(prior_r02()),
            {"item_id": "KLT_R03", "accepted_for_joint_mask": True,
             "trajectory": {"path": "/accepted/r03.csv"}},
            {"item_id": "KLT_R04", "accepted_for_joint_mask": False,
             "trajectory": None},
            {"item_id": "KLT_R05", "accepted_for_joint_mask": True,
             "trajectory": {"path": "/accepted/r05.csv"}},
        ]}
        paths = runner.accepted_arm_paths(backend)
        self.assertEqual(list(paths), ["HFNET", "KLT_R03", "KLT_R05"])
        self.assertNotIn("KLT_R01", paths)
        self.assertNotIn("KLT_R02", paths)

    def test_coordinatewise_median_uses_all_valid_v4_repeats(self) -> None:
        rows = [{name: value for name in runner.PRIMARY_METRICS}
                for value in (1.0, 100.0, 3.0)]
        observed = runner.median_metrics(rows)
        for name in runner.PRIMARY_METRICS:
            self.assertEqual(observed[name], 3.0)

    def test_complete_failed_r02_receipt_is_bound_but_not_accepted(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            receipt, receipt_id, lock_id, item = synthetic_r02_terminal(Path(directory))
            value = runner.validate_r02_terminal_receipt(
                receipt, receipt_id, lock_id, item,
                expected_identity=(123, "8" * 64),
            )
        self.assertEqual(value["disposition"], runner.R02_DISPOSITION)
        self.assertEqual(value["failure_code"], runner.R02_FAILURE_CODE)
        self.assertTrue(value["trajectory_complete"])
        self.assertEqual(value["trajectory_rows"], 2319)
        self.assertFalse(value["trajectory_admitted"])
        self.assertFalse(value["artifact_accepted"])
        self.assertEqual(value["artifact_contract_status"], "FAIL")
        self.assertEqual(value["artifact_issue"], runner.R02_ARTIFACT_ISSUE)
        self.assertEqual(value["base_deep_terminal_evidence_audit"], "PASS")
        self.assertEqual(
            value["v3_strict_deep_terminal_evidence_audit"],
            "FAIL_EXPECTED_LEGACY_REPLAY_MANIFEST_SCHEMA",
        )
        self.assertTrue(value["runtime_timed_out"])
        self.assertEqual(value["raw_return_code"], -9)

    def test_real_r02_receipt_has_exact_dual_audit_boundary(self) -> None:
        value = runner.prior_r02_binding()
        self.assertEqual(value["receipt"]["size_bytes"], 12840)
        self.assertEqual(value["receipt"]["sha256"], runner.R02_TERMINAL_EXPECTED[1])
        self.assertEqual(value["base_deep_terminal_evidence_audit"], "PASS")
        self.assertEqual(
            value["v3_strict_deep_terminal_evidence_audit"],
            "FAIL_EXPECTED_LEGACY_REPLAY_MANIFEST_SCHEMA",
        )
        self.assertEqual(
            value["v3_strict_deep_failure_code"],
            runner.R02_V3_WRAPPER_DEEP_FAILURE,
        )
        self.assertEqual(value["artifact_contract_status"], "FAIL")
        self.assertEqual(value["artifact_issue"], runner.R02_ARTIFACT_ISSUE)
        self.assertTrue(value["complete_artifacts_identity_bound"])
        self.assertTrue(value["complete_artifacts"])
        self.assertEqual(len(value["complete_artifact_identities"]), 11)
        self.assertTrue(value["trajectory_complete"])
        self.assertFalse(value["trajectory_admitted"])

    def test_r02_receipt_cannot_be_relabelled_pass(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            receipt, receipt_id, lock_id, item = synthetic_r02_terminal(Path(directory))
            receipt["status"] = "PASS_BACKEND_REPLAY_ACCEPTED"
            with self.assertRaisesRegex(runner.AnalysisProtocolError,
                                        "R02_TERMINAL_CONTROL"):
                runner.validate_r02_terminal_receipt(
                    receipt, receipt_id, lock_id, item,
                    expected_identity=(123, "8" * 64),
                )

    def test_r02_artifact_or_row_degradation_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            receipt, receipt_id, lock_id, item = synthetic_r02_terminal(Path(directory))
            receipt["artifact_contract"]["status"] = "PASS"
            with self.assertRaisesRegex(runner.AnalysisProtocolError,
                                        "R02_COMPLETE_UNACCEPTED_ARTIFACTS"):
                runner.validate_r02_terminal_receipt(
                    receipt, receipt_id, lock_id, item,
                    expected_identity=(123, "8" * 64),
                )
            receipt["artifact_contract"]["status"] = "FAIL"
            receipt["artifact_contract"]["semantic_checks"]["trajectory"]["rows"] = 2318
            with self.assertRaisesRegex(runner.AnalysisProtocolError,
                                        "R02_COMPLETE_REPLAY_SEMANTICS"):
                runner.validate_r02_terminal_receipt(
                    receipt, receipt_id, lock_id, item,
                    expected_identity=(123, "8" * 64),
                )

    def test_late_bound_r02_identity_blocks_even_if_path_exists(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            receipt = Path(directory) / "formal_run_receipt_v3.json"
            receipt.write_text("{}\n", encoding="utf-8")
            with mock.patch.object(runner, "R02_RECEIPT", receipt), \
                 mock.patch.object(runner, "R02_TERMINAL_EXPECTED", None):
                with self.assertRaisesRegex(
                    runner.AnalysisProtocolError,
                    "R02_TERMINAL_EXPECTED_IDENTITY_NOT_FILLED",
                ):
                    runner.prior_r02_binding()

    def _payload(self) -> dict[str, object]:
        missing = {"backend_v4_execution_lock": "MISSING", **{
            item: "MISSING" for item in runner.V4_ITEM_ORDER
        }}
        absent = {"backend_v4_root": "ABSENT", "backend_v4_runtime_root": "ABSENT", **{
            f"workspace:{item}": "ABSENT" for item in runner.V4_ITEM_ORDER
        }}
        old_absent = {
            f"{kind}:{item}": "ABSENT" for item in runner.V4_ITEM_ORDER
            for kind in ("output", "runtime", "workspace")
        }
        patches = (
            mock.patch.object(runner, "backend_v4_terminal_presence", return_value=missing),
            mock.patch.object(runner, "backend_v4_campaign_prelaunch_presence", return_value=absent),
            mock.patch.object(runner, "v3_remaining_r03_r05_presence", return_value=old_absent),
            mock.patch.object(runner, "analysis_output_state", return_value="ABSENT"),
            mock.patch.object(runner, "_require_prior_analysis_diversions_untouched"),
            mock.patch.object(runner.ENGINE, "regular_absence"),
            mock.patch.object(runner, "prior_r01_binding", return_value=prior_r01()),
            mock.patch.object(runner, "prior_r02_binding", return_value=prior_r02()),
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

    def test_design_freeze_payload_records_two_na_and_no_v4_results(self) -> None:
        payload = self._payload()
        self.assertEqual(payload["schema_version"], runner.DESIGN_FREEZE_SCHEMA)
        self.assertEqual(payload["status"], runner.DESIGN_FREEZE_STATUS)
        self.assertEqual(payload["prior_r01"]["disposition"], runner.R01_DISPOSITION)
        self.assertEqual(payload["prior_r02"]["disposition"], runner.R02_DISPOSITION)
        self.assertFalse(payload["prior_r02"]["trajectory_admitted"])
        boundary = payload["claim_boundary"]
        self.assertTrue(boundary["r02_complete_artifacts_identity_bound_but_unaccepted"])
        self.assertFalse(boundary["r02_trajectory_opened_for_common_support"])
        self.assertFalse(boundary["backend_v4_execution_lock_built"])
        self.assertEqual(boundary["v4_backend_items_started"], 0)
        self.assertFalse(boundary["ape_or_rpe_computed_for_v4"])
        unsigned = dict(payload); digest = unsigned.pop("freeze_sha256")
        self.assertEqual(digest, runner.compact_sha256(unsigned))

    def test_real_candidate_payload_passes_backend_v4_order_gate(self) -> None:
        payload = runner.build_design_freeze_payload("PROCESS_FREE_DRY_CANDIDATE")
        backend = runner.load_backend_v4_authority_module()
        with tempfile.TemporaryDirectory() as directory:
            freeze = Path(directory) / "noncanonical_process_free_dry_freeze.json"
            freeze.write_text(
                json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
            with mock.patch.object(backend, "ANALYSIS_V4_DESIGN_FREEZE", freeze):
                binding = backend.collect_analysis_v4_design_freeze_binding()
        self.assertEqual(binding["status"], runner.DESIGN_FREEZE_STATUS)
        self.assertEqual(binding["freeze_sha256"], payload["freeze_sha256"])
        self.assertEqual(
            binding["prior_r02"]["base_deep_terminal_evidence_audit"], "PASS"
        )
        self.assertEqual(
            binding["prior_r02"]["v3_strict_deep_terminal_evidence_audit"],
            "FAIL_EXPECTED_LEGACY_REPLAY_MANIFEST_SCHEMA",
        )
        self.assertTrue(binding["prior_r02"]["complete_artifacts"])
        self.assertEqual(
            len(binding["prior_r02"]["complete_artifact_identities"]), 11
        )
        self.assertFalse(binding["prior_r02"]["trajectory_admitted"])
        self.assertFalse(binding["claim_boundary"]["ape_or_rpe_computed_for_v4"])

    def test_design_freeze_rejects_old_v3_remaining_touch(self) -> None:
        missing = {"backend_v4_execution_lock": "MISSING", **{
            item: "MISSING" for item in runner.V4_ITEM_ORDER
        }}
        prelaunch = {"backend_v4_root": "ABSENT", "backend_v4_runtime_root": "ABSENT", **{
            f"workspace:{item}": "ABSENT" for item in runner.V4_ITEM_ORDER
        }}
        old = {f"{kind}:{item}": "ABSENT" for item in runner.V4_ITEM_ORDER
               for kind in ("output", "runtime", "workspace")}
        old["output:KLT_R04"] = "PRESENT"
        with mock.patch.object(runner, "backend_v4_terminal_presence", return_value=missing), \
             mock.patch.object(runner, "backend_v4_campaign_prelaunch_presence", return_value=prelaunch), \
             mock.patch.object(runner, "v3_remaining_r03_r05_presence", return_value=old):
            with self.assertRaisesRegex(runner.AnalysisProtocolError,
                                        "OLD_V3_R03_R05_MUST_REMAIN_UNTOUCHED"):
                runner.build_design_freeze_payload("never")

    def test_static_identity_keyset_includes_backend_v4_and_r02_lineage(self) -> None:
        frozen = {name: fake_identity(name) for name in (
            "analysis_v3_protocol", "analysis_v3_runner", "analysis_v3_tests",
            "analysis_v3_design_freeze", "backend_v3_protocol", "backend_v3_runner",
            "backend_v3_guard", "backend_v3_tests", "backend_v3_execution_lock",
        )}
        expected = (123, "9" * 64)

        def observed(path: Path) -> dict[str, object]:
            if path == runner.R02_RECEIPT:
                return {"path": str(path), "size_bytes": expected[0], "sha256": expected[1]}
            return fake_identity(path.name)

        with mock.patch.object(runner, "_check_frozen_lineage_identities", return_value=frozen), \
             mock.patch.object(runner, "identity", side_effect=observed), \
             mock.patch.object(runner, "R02_TERMINAL_EXPECTED", expected):
            values = runner.collect_static_identities()
        required = {
            "backend_v4_protocol", "backend_v4_runner", "backend_v4_guard",
            "backend_v4_lifecycle_wrapper", "backend_v4_signal_mask_launcher",
            "backend_v4_process_free_tests", "backend_v4_python38",
            "backend_v4_vins_node",
            "analysis_v3_design_freeze", "backend_v3_execution_lock",
            "v3_r02_terminal_receipt",
        }
        self.assertTrue(required <= set(values))

    def test_preflight_waits_for_backend_v4_sources_after_r02_identity(self) -> None:
        presence = {
            "backend_v4_protocol": "MISSING",
            "backend_v4_runner": "MISSING",
            "backend_v4_guard": "MISSING",
            "backend_v4_lifecycle_wrapper": "MISSING",
            "backend_v4_signal_mask_launcher": "MISSING",
            "backend_v4_process_free_tests": "MISSING",
            "backend_v4_python38": "PRESENT_REGULAR",
            "backend_v4_vins_node": "PRESENT_REGULAR",
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            receipt = root / "receipt.json"; receipt.write_text("{}\n")
            freeze = root / "freeze.json"; lock = root / "lock.json"
            with mock.patch.multiple(
                runner, R02_RECEIPT=receipt, DESIGN_FREEZE=freeze,
                DEFAULT_LOCK=lock, R02_TERMINAL_EXPECTED=(3, "a" * 64),
            ), mock.patch.object(
                runner, "backend_v4_authority_source_presence", return_value=presence
            ):
                result = runner.preflight_readonly(lock)
        self.assertEqual(result["status"], "WAITING_BACKEND_V4_CANDIDATE_AUTHORITIES")
        self.assertFalse(result["accuracy_computed"])

    def test_preflight_waits_for_natural_r02_without_writes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            receipt = root / "missing-receipt.json"
            freeze = root / "missing-freeze.json"
            lock = root / "missing-lock.json"
            output = root / "missing-output"
            claim = root / "missing-claim.json"
            before = list(root.iterdir())
            with mock.patch.multiple(
                runner, R02_RECEIPT=receipt, DESIGN_FREEZE=freeze,
                DEFAULT_LOCK=lock, OUTPUT_ROOT=output, CLAIM_PATH=claim,
            ):
                result = runner.preflight_readonly(lock)
            self.assertEqual(before, list(root.iterdir()))
        self.assertEqual(result["status"], "WAITING_V3_R02_NATURAL_TERMINAL_RECEIPT")
        self.assertFalse(result["accuracy_computed"])

    def test_build_lock_rejects_missing_v4_terminal_before_authority(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "lock.json"
            presence = {"backend_v4_execution_lock": "PRESENT_REGULAR", **{
                item: ("MISSING" if item == "KLT_R05" else "PRESENT_REGULAR")
                for item in runner.V4_ITEM_ORDER
            }}
            authority = mock.Mock(side_effect=AssertionError("must not collect"))
            with mock.patch.object(runner, "DEFAULT_LOCK", path), \
                 mock.patch.object(runner, "analysis_output_state", return_value="ABSENT"), \
                 mock.patch.object(runner, "collect_design_freeze_binding", return_value={}), \
                 mock.patch.object(runner, "backend_v4_terminal_presence", return_value=presence), \
                 mock.patch.object(runner, "collect_authority", authority):
                with self.assertRaisesRegex(runner.AnalysisProtocolError,
                                            "THREE_V4_TERMINAL_RECEIPTS_REQUIRED"):
                    runner.build_lock(path, runner.BUILD_LOCK_TOKEN)
            self.assertFalse(path.exists()); authority.assert_not_called()

    def test_build_lock_is_identity_only_no_accuracy(self) -> None:
        authority = {"backend": {"planned_count": 5, "maximum_valid_count": 3,
                                 "valid_count": 2}, "excluded_xfeat": exclusion()}
        presence = {"backend_v4_execution_lock": "PRESENT_REGULAR", **{
            item: "PRESENT_REGULAR" for item in runner.V4_ITEM_ORDER
        }}
        numeric = mock.Mock(side_effect=AssertionError("accuracy forbidden"))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "lock.json"
            with mock.patch.object(runner, "DEFAULT_LOCK", path), \
                 mock.patch.object(runner, "analysis_output_state", return_value="ABSENT"), \
                 mock.patch.object(runner, "collect_design_freeze_binding", return_value={}), \
                 mock.patch.object(runner, "backend_v4_terminal_presence", return_value=presence), \
                 mock.patch.object(runner, "collect_authority", return_value=authority), \
                 mock.patch.object(runner, "evaluate_joint_inputs", numeric):
                result = runner.build_lock(path, runner.BUILD_LOCK_TOKEN)
            self.assertTrue(path.is_file()); self.assertFalse(result["accuracy_computed"])
            self.assertEqual(result["maximum_valid_klt_count"], 3)
            numeric.assert_not_called()

    def test_formal_summary_keeps_r02_out_of_mask_and_median(self) -> None:
        from scripts.tests.test_run_a08_hfnet_vs_klt_only_common_support_v2 import (
            pass_evo_audit, primary_summary, synthetic_lock,
        )
        lock = synthetic_lock((3, 5))
        rows = lock["authority"]["backend"]["planned_repeats"]
        rows[0].update(runner._r01_population_row(prior_r01()))
        rows[1].update(runner._r02_population_row(prior_r02()))
        lock["authority"]["backend"].update({
            "maximum_valid_count": 3, "infrastructure_na_count": 2,
        })
        primary = primary_summary((3, 5), (0.6, 0.2))
        formal = runner.build_formal_summary(
            lock, primary, runner.support_gate(primary), pass_evo_audit()
        )
        runner.validate_formal_population_binding(formal, lock)
        self.assertEqual(formal["single_joint_mask_arm_set"],
                         ["HFNET", "KLT_R03", "KLT_R05"])
        self.assertEqual(formal["klt"]["planned_count"], 5)
        self.assertEqual(formal["klt"]["valid_count"], 2)
        self.assertEqual(formal["klt"]["formal_median_metrics"]["ape_rmse_m"], 0.4)
        r02 = formal["planned_klt_repeats"][1]
        self.assertEqual(r02["terminal_disposition"], runner.R02_DISPOSITION)
        self.assertFalse(r02["accepted_for_single_joint_mask"])
        self.assertTrue(r02["post_result_cleanup_failed"])

    def test_canonical_v4_freeze_lock_and_output_are_absent(self) -> None:
        for path in (runner.DESIGN_FREEZE, runner.DEFAULT_LOCK,
                     runner.OUTPUT_ROOT, runner.CLAIM_PATH):
            self.assertFalse(path.exists() or path.is_symlink(), str(path))


if __name__ == "__main__":
    unittest.main()
