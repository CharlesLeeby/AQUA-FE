#!/usr/bin/env python3
"""Process-free tests for the additive A08 common-support analysis v3."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from scripts import run_a08_hfnet_vs_klt_only_common_support_v3 as runner


def fake_identity(name: str = "x", digit: str = "a") -> dict[str, object]:
    return {"path": f"/authority/{name}", "size_bytes": 1, "sha256": digit * 64}


def prior_r01() -> dict[str, object]:
    return {
        "item_id": "KLT_R01",
        "disposition": runner.R01_DISPOSITION,
        "receipt": fake_identity("r01", "1"),
        "v2_execution_lock": fake_identity("v2-lock", "2"),
        "v2_deep_terminal_evidence_audit": "PASS",
        "vio_empty": True,
        "empty_vio": {"path": "/r01/vio.csv", "size_bytes": 0,
                      "sha256": runner.EMPTY_SHA256},
        "ape_empty": True,
        "empty_ape": {"path": "/r01/ape.txt", "size_bytes": 0,
                      "sha256": runner.EMPTY_SHA256},
        "artifact_accepted": False,
        "failure_code": runner.R01_FAILURE_CODE,
        "execution_integrity": "PASS",
        "backend_supervisor_launched": True,
        "backend_replay_started": False,
        "rerun_or_replacement_permitted": False,
        "process_log": fake_identity("log", "3"),
    }


def exclusion() -> dict[str, object]:
    return {
        "disposition": runner.XFEAT_DISPOSITION,
        "accepted_frontend_receipt_present": False,
        "backend_items_launched": 0,
        "backend_trajectory_admitted": False,
        "learning_contribution_claim_permitted": False,
    }


class AnalysisV3ProtocolTests(unittest.TestCase):
    def test_frozen_v2_authorities_are_byte_identical(self) -> None:
        paths = {
            "protocol": runner.V2_PROTOCOL,
            "runner": runner.V2_RUNNER,
            "tests": runner.V2_TESTS,
            "design_freeze": runner.V2_DESIGN_FREEZE,
        }
        for label, path in paths.items():
            raw = path.read_bytes()
            self.assertEqual(
                (len(raw), hashlib.sha256(raw).hexdigest()),
                runner.FROZEN_V2_EXPECTED[label],
            )

    def test_population_contract_is_exact_five_plus_four(self) -> None:
        contract = runner.design_contract_snapshot()
        population = contract["population_and_failure_rules"]
        self.assertEqual(population["backend_item_order"], list(runner.FULL_ITEM_ORDER))
        self.assertEqual(population["v3_backend_item_order"], list(runner.V3_ITEM_ORDER))
        self.assertEqual(population["klt_planned_count"], 5)
        self.assertEqual(population["maximum_valid_klt_count"], 4)
        self.assertEqual(population["r01_disposition"], runner.R01_DISPOSITION)
        self.assertFalse(population["r01_counts_as_valid"])
        self.assertFalse(population["r01_rerun_or_replacement_permitted"])
        self.assertFalse(population["best_repeat_selection_permitted"])
        self.assertTrue(
            contract["execution_rules"]["design_freeze_before_v3_backend_terminal_results"]
        )

    def test_numeric_and_joint_mask_rules_are_inherited_unchanged(self) -> None:
        current = runner.design_contract_snapshot()
        frozen = runner._V2_DESIGN_CONTRACT_SNAPSHOT()
        self.assertEqual(current["numeric_rules"], frozen["numeric_rules"])
        numeric = current["numeric_rules"]
        self.assertEqual(numeric["fixed_denominator"], 33)
        self.assertTrue(numeric["proper_fixed_scale_se3"])
        self.assertFalse(numeric["sim3_or_scale_fit"])
        self.assertTrue(numeric["single_joint_mask_across_hfnet_and_all_accepted_klt_repeats"])
        self.assertEqual(numeric["evo_abs_tolerance_m"], 1e-5)

    def test_r01_population_row_is_infrastructure_na_not_scientific(self) -> None:
        row = runner._r01_population_row(prior_r01())
        self.assertEqual(row["disposition"], runner.R01_DISPOSITION)
        self.assertFalse(row["accepted_for_joint_mask"])
        self.assertIsNone(row["trajectory"])
        self.assertFalse(row["scientific_failure_retained_as_na"])
        self.assertTrue(row["backend_infrastructure_failure_retained_as_na"])
        self.assertTrue(row["backend_launched"])
        self.assertFalse(row["backend_replay_started"])
        self.assertFalse(row["replacement_permitted"])

    def test_accepted_arm_paths_excludes_r01_and_failed_v3(self) -> None:
        backend = {
            "planned_repeats": [
                runner._r01_population_row(prior_r01()),
                {"item_id": "KLT_R02", "accepted_for_joint_mask": True,
                 "trajectory": {"path": "/accepted/r02.csv"}},
                {"item_id": "KLT_R03", "accepted_for_joint_mask": False,
                 "trajectory": None},
                {"item_id": "KLT_R04", "accepted_for_joint_mask": True,
                 "trajectory": {"path": "/accepted/r04.csv"}},
                {"item_id": "KLT_R05", "accepted_for_joint_mask": False,
                 "trajectory": None},
            ]
        }
        paths = runner.accepted_arm_paths(backend)
        self.assertEqual(list(paths), ["HFNET", "KLT_R02", "KLT_R04"])
        self.assertNotIn("KLT_R01", paths)

    def test_coordinatewise_median_uses_every_valid_repeat(self) -> None:
        names = list(runner.PRIMARY_METRICS)
        rows = [
            {name: value for name in names}
            for value in (1.0, 100.0, 3.0, 5.0)
        ]
        observed = runner.median_metrics(rows)
        for name in names:
            self.assertEqual(observed[name], 4.0)

    def test_real_r01_receipt_deep_audits_process_free(self) -> None:
        observed = runner.prior_r01_binding()
        self.assertEqual(observed["disposition"], runner.R01_DISPOSITION)
        self.assertEqual(observed["receipt"]["sha256"], runner.R01_RECEIPT_EXPECTED[1])
        self.assertEqual(observed["v2_execution_lock"]["sha256"], runner.V2_LOCK_EXPECTED[1])
        self.assertEqual(observed["v2_deep_terminal_evidence_audit"], "PASS")
        self.assertTrue(observed["vio_empty"])
        self.assertFalse(observed["artifact_accepted"])
        self.assertFalse(observed["backend_replay_started"])
        self.assertTrue(observed["ape_empty"])
        self.assertEqual(observed["empty_ape"]["sha256"], runner.EMPTY_SHA256)
        self.assertEqual(observed["failure_code"], runner.R01_FAILURE_CODE)

    def test_backend_v3_interface_is_four_remaining_items(self) -> None:
        module = runner.load_backend_v3_authority_module()
        self.assertEqual(tuple(module.ITEM_ORDER), runner.V3_ITEM_ORDER)
        self.assertEqual(Path(module.BACKEND_ROOT), runner.BACKEND_V3_ROOT)
        self.assertEqual(Path(module.DEFAULT_LOCK), runner.BACKEND_V3_LOCK)
        self.assertEqual(module.RECEIPT_NAME, runner.BACKEND_V3_RECEIPT_NAME)

    def test_required_static_identity_keys_match_backend_order_gate(self) -> None:
        frozen = {
            label: fake_identity(f"v2-{label}", str(index))
            for index, label in enumerate(runner.FROZEN_V2_EXPECTED, start=1)
        }

        def observed(path: Path) -> dict[str, object]:
            if path == runner.V2_R01_RECEIPT:
                return {"path": str(path), "size_bytes": runner.R01_RECEIPT_EXPECTED[0],
                        "sha256": runner.R01_RECEIPT_EXPECTED[1]}
            if path == runner.V2_BACKEND_LOCK:
                return {"path": str(path), "size_bytes": runner.V2_LOCK_EXPECTED[0],
                        "sha256": runner.V2_LOCK_EXPECTED[1]}
            return fake_identity(path.name, "a")

        with mock.patch.object(runner, "_check_frozen_v2_identities", return_value=frozen), \
             mock.patch.object(runner, "identity", side_effect=observed):
            values = runner.collect_static_identities()
        required = {
            "backend_v3_protocol", "backend_v3_runner", "backend_v3_guard",
            "backend_v3_process_free_tests", "v2_r01_terminal_receipt",
            "v2_execution_lock",
        }
        self.assertTrue(required <= set(values))

    def _payload(self) -> dict[str, object]:
        missing = {"backend_v3_execution_lock": "MISSING", **{
            item: "MISSING" for item in runner.V3_ITEM_ORDER
        }}
        absent = {"backend_v3_root": "ABSENT", "backend_v3_runtime_root": "ABSENT", **{
            f"workspace:{item}": "ABSENT" for item in runner.V3_ITEM_ORDER
        }}
        old_absent = {
            f"{kind}:{item}": "ABSENT"
            for item in runner.V3_ITEM_ORDER
            for kind in ("output", "runtime", "workspace")
        }
        patches = (
            mock.patch.object(runner, "backend_v3_terminal_presence", return_value=missing),
            mock.patch.object(runner, "backend_v3_campaign_prelaunch_presence", return_value=absent),
            mock.patch.object(runner, "v2_remaining_items_presence", return_value=old_absent),
            mock.patch.object(runner, "analysis_output_state", return_value="ABSENT"),
            mock.patch.object(runner, "_require_analysis_diversion_untouched"),
            mock.patch.object(runner.BASE, "regular_absence"),
            mock.patch.object(runner, "prior_r01_binding", return_value=prior_r01()),
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
            patcher.start()
            self.addCleanup(patcher.stop)
        return runner.build_design_freeze_payload("2026-08-28T12:00:00+00:00")

    def test_design_freeze_payload_matches_backend_exact_semantics(self) -> None:
        payload = self._payload()
        self.assertEqual(payload["schema_version"], runner.DESIGN_FREEZE_SCHEMA)
        self.assertEqual(payload["status"], runner.DESIGN_FREEZE_STATUS)
        prior = payload["prior_r01"]
        self.assertEqual(prior["disposition"], runner.R01_DISPOSITION)
        self.assertEqual(prior["v2_deep_terminal_evidence_audit"], "PASS")
        self.assertTrue(prior["vio_empty"])
        self.assertFalse(prior["artifact_accepted"])
        self.assertFalse(prior["rerun_or_replacement_permitted"])
        self.assertTrue(prior["ape_empty"])
        self.assertEqual(prior["failure_code"], runner.R01_FAILURE_CODE)
        self.assertTrue(all(
            value == "ABSENT"
            for value in payload["v2_remaining_r02_r05_presence_at_freeze"].values()
        ))
        boundary = payload["claim_boundary"]
        self.assertFalse(boundary["backend_v3_execution_lock_built"])
        self.assertEqual(boundary["v3_backend_items_started"], 0)
        self.assertFalse(boundary["ape_or_rpe_computed"])
        self.assertFalse(boundary["ros_or_vins_started_for_v3"])
        unsigned = dict(payload)
        digest = unsigned.pop("freeze_sha256")
        self.assertEqual(digest, runner.compact_sha256(unsigned))

    def test_design_freeze_rejects_any_old_v2_remaining_touch(self) -> None:
        missing = {"backend_v3_execution_lock": "MISSING", **{
            item: "MISSING" for item in runner.V3_ITEM_ORDER
        }}
        prelaunch = {
            "backend_v3_root": "ABSENT", "backend_v3_runtime_root": "ABSENT",
            **{f"workspace:{item}": "ABSENT" for item in runner.V3_ITEM_ORDER},
        }
        old = {
            f"{kind}:{item}": "ABSENT"
            for item in runner.V3_ITEM_ORDER
            for kind in ("output", "runtime", "workspace")
        }
        old["runtime:KLT_R04"] = "PRESENT"
        with mock.patch.object(
            runner, "backend_v3_terminal_presence", return_value=missing
        ), mock.patch.object(
            runner, "backend_v3_campaign_prelaunch_presence", return_value=prelaunch
        ), mock.patch.object(
            runner, "v2_remaining_items_presence", return_value=old
        ):
            with self.assertRaisesRegex(
                runner.AnalysisProtocolError, "OLD_V2_R02_R05_MUST_REMAIN_UNTOUCHED"
            ):
                runner.build_design_freeze_payload("never-published")

    def test_design_freeze_round_trip_and_digest_tamper_rejection(self) -> None:
        payload = self._payload()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "freeze.json"
            path.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")
            with mock.patch.object(runner, "DESIGN_FREEZE", path):
                binding = runner.collect_design_freeze_binding()
                self.assertEqual(binding["freeze_sha256"], payload["freeze_sha256"])
                payload["freeze_sha256"] = "0" * 64
                path.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")
                with self.assertRaisesRegex(runner.AnalysisProtocolError,
                                            "DESIGN_FREEZE_DIGEST"):
                    runner.collect_design_freeze_binding()

    def test_preflight_waits_for_four_terminals_without_collecting_accuracy(self) -> None:
        presence = {"backend_v3_execution_lock": "PRESENT_REGULAR", **{
            item: ("MISSING" if item == "KLT_R05" else "PRESENT_REGULAR")
            for item in runner.V3_ITEM_ORDER
        }}
        authority = mock.Mock(side_effect=AssertionError("must not collect authority"))
        with mock.patch.object(
            runner, "design_freeze_audit_readonly",
            return_value={"status": "PASS_DESIGN_FROZEN_AFTER_R01_BEFORE_R02_R05"},
        ), mock.patch.object(
            runner, "backend_v3_terminal_presence", return_value=presence
        ), mock.patch.object(runner, "collect_authority", authority):
            result = runner.preflight_readonly(runner.DEFAULT_LOCK)
        self.assertEqual(result["status"],
                         "WAITING_FOR_BACKEND_V3_LOCK_AND_FOUR_TERMINAL_RECEIPTS")
        self.assertFalse(result["accuracy_computed"])
        authority.assert_not_called()

    def test_build_lock_rejects_missing_terminal_before_authority(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "analysis-lock.json"
            presence = {"backend_v3_execution_lock": "PRESENT_REGULAR", **{
                item: ("MISSING" if item == "KLT_R02" else "PRESENT_REGULAR")
                for item in runner.V3_ITEM_ORDER
            }}
            authority = mock.Mock(side_effect=AssertionError("authority must not open"))
            with mock.patch.object(runner, "DEFAULT_LOCK", path), \
                 mock.patch.object(runner, "analysis_output_state", return_value="ABSENT"), \
                 mock.patch.object(runner, "collect_design_freeze_binding", return_value={}), \
                 mock.patch.object(runner, "backend_v3_terminal_presence", return_value=presence), \
                 mock.patch.object(runner, "collect_authority", authority):
                with self.assertRaisesRegex(runner.AnalysisProtocolError,
                                            "FOUR_V3_TERMINAL_RECEIPTS_REQUIRED"):
                    runner.build_lock(path, runner.BUILD_LOCK_TOKEN)
            self.assertFalse(path.exists())
            authority.assert_not_called()

    def test_build_lock_is_identity_only_and_reports_no_accuracy(self) -> None:
        authority = {
            "backend": {"planned_count": 5, "maximum_valid_count": 4,
                        "valid_count": 3},
            "excluded_xfeat": exclusion(),
        }
        presence = {"backend_v3_execution_lock": "PRESENT_REGULAR", **{
            item: "PRESENT_REGULAR" for item in runner.V3_ITEM_ORDER
        }}
        numeric = mock.Mock(side_effect=AssertionError("accuracy forbidden"))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "analysis-lock.json"
            with mock.patch.object(runner, "DEFAULT_LOCK", path), \
                 mock.patch.object(runner, "analysis_output_state", return_value="ABSENT"), \
                 mock.patch.object(runner, "collect_design_freeze_binding", return_value={}), \
                 mock.patch.object(runner, "backend_v3_terminal_presence", return_value=presence), \
                 mock.patch.object(runner, "collect_authority", return_value=authority), \
                 mock.patch.object(runner, "evaluate_joint_inputs", numeric):
                result = runner.build_lock(path, runner.BUILD_LOCK_TOKEN)
            self.assertTrue(path.is_file())
            self.assertFalse(result["accuracy_computed"])
            self.assertEqual(result["klt_valid_count"], 3)
            numeric.assert_not_called()

    def test_current_readonly_preflight_writes_nothing_and_freeze_is_absent(self) -> None:
        self.assertFalse(runner.DESIGN_FREEZE.exists())
        before = {
            path: (path.exists(), path.is_symlink())
            for path in (runner.DESIGN_FREEZE, runner.DEFAULT_LOCK,
                         runner.OUTPUT_ROOT, runner.CLAIM_PATH)
        }
        result = runner.preflight_readonly()
        after = {
            path: (path.exists(), path.is_symlink())
            for path in before
        }
        self.assertEqual(before, after)
        self.assertEqual(result["status"], "BLOCKED_DESIGN_FREEZE")
        self.assertFalse(result["accuracy_computed"])


if __name__ == "__main__":
    unittest.main()
