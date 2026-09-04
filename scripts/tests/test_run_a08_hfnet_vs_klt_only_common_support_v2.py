#!/usr/bin/env python3

from __future__ import annotations

import csv
import json
import tempfile
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest import mock

import numpy as np

from scripts import run_a08_hfnet_vs_klt_only_common_support_v2 as runner


def metric_row(base: float, matched: int = 31, pairs: int = 30) -> dict[str, float | int]:
    return {
        "matched_count": matched,
        "rpe_pairs": pairs,
        **{
            name: base + index / 100.0
            for index, name in enumerate(runner.PRIMARY_METRICS)
        },
    }


def exclusion() -> dict[str, object]:
    return {
        "disposition": runner.XFEAT_EXCLUSION_STATUS,
        "forensic_audit": {
            "path": "/tmp/forensic.md", "size_bytes": 1, "sha256": "1" * 64
        },
        "terminal_failure_receipt": {
            "path": "/tmp/failure.json", "size_bytes": 1, "sha256": "2" * 64
        },
        "accepted_frontend_receipt_path": "/tmp/accepted-must-not-exist.json",
        "accepted_frontend_receipt_present": False,
        "structural_failure_code": "FEATURE_POINT_COUNT_RANGE",
        "original_planned_backend_slots": 5,
        "backend_items_launched": 0,
        "backend_trajectory_admitted": False,
        "method_native_profile": "klt_safe_fallback",
        "fallback_byte_identical_to_accepted_klt_inputs": True,
        "learning_contribution_claim_permitted": False,
    }


def backend_rows(
    accepted: tuple[int, ...] = (1, 2, 3),
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for repeat, item_id in enumerate(runner.ITEM_ORDER, start=1):
        ok = repeat in accepted
        rows.append({
            "item_id": item_id,
            "arm": "klt",
            "repeat_index": repeat,
            "disposition": (
                "PASS_BACKEND_REPLAY_ACCEPTED"
                if ok else "FAILED_BACKEND_REPLAY_NO_REPLACEMENT"
            ),
            "accepted_for_joint_mask": ok,
            "trajectory": (
                {
                    "path": f"/tmp/{item_id}.csv",
                    "size_bytes": 1,
                    "sha256": f"{repeat}" * 64,
                }
                if ok else None
            ),
            "scientific_failure_retained_as_na": not ok,
            "replacement_permitted": False,
        })
    return rows


def synthetic_lock(accepted: tuple[int, ...] = (1, 2, 3)) -> dict[str, object]:
    rows = backend_rows(accepted)
    return {
        "contract_sha256": "a" * 64,
        "authority": {
            "backend": {
                "planned_repeats": rows,
                "planned_count": 5,
                "valid_count": len(accepted),
                "failed_count": 5 - len(accepted),
            },
            "excluded_xfeat": exclusion(),
            "evo": {"version": "1.31.1"},
        },
    }


def primary_summary(
    accepted: tuple[int, ...] = (1, 2, 3),
    bases: tuple[float, ...] = (0.5, 0.1, 0.3),
) -> dict[str, object]:
    arms: dict[str, object] = {"HFNET": metric_row(1.0)}
    for repeat, base in zip(accepted, bases):
        arms[f"KLT_R{repeat:02d}"] = metric_row(base)
    return {
        "protocol": {
            "single_joint_mask": True,
            "joint_mask_population": "reference_and_hfnet_and_all_accepted_klt_repeats",
            "xfeat_excluded_before_backend": True,
            "shared_full_precision_body_T_cam0": str(runner.SHARED_EXTRINSIC),
            "proper_fixed_scale_se3": True,
            "sim3": False,
            "reference_time_offset_s": 0.0,
            "all_arm_time_offsets_s": 0.0,
        },
        "support": {
            "grid_count": 33,
            "matched_count": 31,
            "common_span_s": 30.0,
            "rpe_pairs": 30,
            "ape_valid": True,
            "rpe_valid": True,
        },
        "arms": arms,
    }


def pass_evo_audit() -> dict[str, object]:
    return {"status": "PASS", "failure_codes": [], "tolerance_m": 1e-5}


class A08HfnetVsKltOnlyV2Test(unittest.TestCase):
    def test_exact_integer_ns_grid_has_33_points(self) -> None:
        grid = runner.exact_grid_evidence()
        self.assertEqual(grid["timestamps_ns"], list(runner.GRID_NS))
        self.assertEqual(len(grid["timestamps_ns"]), 33)
        self.assertTrue(all(isinstance(value, int) for value in grid["timestamps_ns"]))
        self.assertEqual(grid["grid_last_ns"], 1_542_885_193_111_831_216)
        self.assertEqual(grid["window_end_minus_grid_last_ns"], 994_391_456)

    def test_live_xfeat_failure_is_bound_only_as_excluded_evidence(self) -> None:
        observed = runner.collect_xfeat_exclusion()
        self.assertEqual(observed["disposition"], runner.XFEAT_EXCLUSION_STATUS)
        self.assertFalse(observed["accepted_frontend_receipt_present"])
        self.assertEqual(observed["backend_items_launched"], 0)
        self.assertFalse(observed["backend_trajectory_admitted"])
        self.assertFalse(observed["learning_contribution_claim_permitted"])

    def test_live_backend_v2_helper_interface_is_deep_and_exclusion_aware(self) -> None:
        module = runner.load_backend_authority_module()
        bindings = module.resolve_frontend_bindings()
        self.assertEqual(set(bindings), {"klt", "excluded_xfeat"})
        self.assertEqual(
            bindings["excluded_xfeat"]["disposition"],
            runner.XFEAT_EXCLUSION_STATUS,
        )
        self.assertFalse(bindings["excluded_xfeat"]["accepted_receipt_present"])
        self.assertEqual(bindings["excluded_xfeat"]["backend_launched_count"], 0)
        self.assertTrue(callable(module.verify_lock))
        self.assertTrue(callable(module.prior_receipt))

    def test_xfeat_accepted_receipt_presence_blocks_exclusion(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            accepted = Path(directory) / "accepted.json"
            accepted.write_text("{}\n", encoding="utf-8")
            with mock.patch.object(runner, "XFEAT_ACCEPTED_RECEIPT", accepted):
                with self.assertRaisesRegex(
                    runner.AnalysisProtocolError,
                    "XFEAT_ACCEPTED_RECEIPT_MUST_REMAIN_ABSENT",
                ):
                    runner.collect_xfeat_exclusion()

    def test_formal_uses_median_of_all_valid_klt_repeats_not_best(self) -> None:
        lock = synthetic_lock((1, 2, 3))
        primary = primary_summary((1, 2, 3), (0.5, 0.1, 0.3))
        formal = runner.build_formal_summary(
            lock, primary, runner.support_gate(primary), pass_evo_audit()
        )
        self.assertTrue(formal["ranking_available"])
        self.assertEqual(formal["klt"]["planned_count"], 5)
        self.assertEqual(formal["klt"]["valid_count"], 3)
        self.assertFalse(formal["klt"]["best_run_selected"])
        self.assertAlmostEqual(
            formal["klt"]["formal_median_metrics"]["ape_rmse_m"], 0.3
        )
        xfeat_rows = [
            row for row in formal["original_ten_slot_dispositions"]
            if row["arm"] == "xfeat"
        ]
        self.assertEqual(len(xfeat_rows), 5)
        self.assertTrue(all(not row["backend_launched"] for row in xfeat_rows))
        self.assertTrue(all(row["formal_metrics"] == runner.null_metrics()
                            for row in xfeat_rows))

    def test_any_support_gate_failure_sets_all_formal_metrics_na(self) -> None:
        lock = synthetic_lock((1,))
        primary = primary_summary((1,), (0.4,))
        primary["support"]["matched_count"] = 9
        primary["arms"]["HFNET"]["matched_count"] = 9
        primary["arms"]["KLT_R01"]["matched_count"] = 9
        gate = runner.support_gate(primary)
        formal = runner.build_formal_summary(lock, primary, gate, pass_evo_audit())
        self.assertFalse(formal["ranking_available"])
        self.assertTrue(runner.formal_metrics_are_all_na(formal))

    def test_missing_sixth_metric_closes_ranking(self) -> None:
        lock = synthetic_lock((1,))
        primary = primary_summary((1,), (0.4,))
        del primary["arms"]["KLT_R01"]["rpe_max_m"]
        formal = runner.build_formal_summary(
            lock, primary, runner.support_gate(primary), pass_evo_audit()
        )
        self.assertFalse(formal["ranking_available"])
        self.assertTrue(runner.formal_metrics_are_all_na(formal))
        self.assertTrue(any(
            "finite_nonnegative:rpe_max_m" in code
            for code in formal["failure_codes"]
        ))

    def test_backend_scientific_failures_remain_planned_na(self) -> None:
        lock = synthetic_lock((1, 3))
        primary = primary_summary((1, 3), (0.5, 0.3))
        formal = runner.build_formal_summary(
            lock, primary, runner.support_gate(primary), pass_evo_audit()
        )
        failed = next(
            row for row in formal["planned_klt_repeats"]
            if row["item_id"] == "KLT_R02"
        )
        self.assertEqual(
            failed["terminal_disposition"],
            "FAILED_BACKEND_REPLAY_NO_REPLACEMENT",
        )
        self.assertTrue(failed["scientific_failure_retained_as_na"])
        self.assertEqual(failed["formal_metrics"], runner.null_metrics())
        self.assertAlmostEqual(
            formal["klt"]["formal_median_metrics"]["ape_rmse_m"], 0.4
        )

    def test_zero_valid_klt_population_sets_every_formal_metric_na(self) -> None:
        lock = synthetic_lock(())
        primary = primary_summary((), ())
        formal = runner.build_formal_summary(
            lock, primary, runner.support_gate(primary),
            {"status": "NOT_RUN_POPULATION_GATE_CLOSED",
             "failure_codes": ["KLT_HAS_ZERO_VALID_PLANNED_REPEATS"]},
        )
        self.assertFalse(formal["ranking_available"])
        self.assertTrue(runner.formal_metrics_are_all_na(formal))

    def test_evo_self_reported_zero_diff_cannot_hide_wrong_metrics(self) -> None:
        primary = primary_summary((1,), (0.4,))
        evo_arms: dict[str, object] = {}
        for name, row in primary["arms"].items():
            evo_arms[name] = {
                "primary_ape_rmse_m": row["ape_rmse_m"],
                "evo_ape_rmse_m": 999.0,
                "ape_abs_diff_m": 0.0,
                "primary_rpe_rmse_m": row["rpe_rmse_m"],
                "evo_segmented_rpe_rmse_m": 888.0,
                "rpe_abs_diff_m": 0.0,
                "rpe_pair_count": 30,
                "segments": [{"segment_id": 0, "pair_count": 30, "rmse_m": 888.0}],
            }
        audit = runner.common.validate_evo_crosscheck(
            {
                "evo_version": "1.31.1",
                "rpe_delta_frames": 1,
                "rpe_semantics": "aligned_global_frame_positional_delta",
                "arms": evo_arms,
            },
            primary,
            list(primary["arms"]),
            "1.31.1",
        )
        self.assertEqual(audit["status"], "FAIL")
        self.assertTrue(any("reported_diff_matches_actual" in code
                            for code in audit["failure_codes"]))

    def test_atomic_json_publish_never_overwrites_competing_owner(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "receipt.json"
            real_link = runner.common.os.link

            def competing_link(source: object, destination: object, **kwargs: object) -> None:
                target.write_text("COMPETING_OWNER\n", encoding="utf-8")
                real_link(source, destination, **kwargs)

            with mock.patch.object(
                runner.common.os, "link", side_effect=competing_link
            ):
                with self.assertRaises(FileExistsError):
                    runner.atomic_publish(target, {"ours": True})
            self.assertEqual(target.read_text(encoding="utf-8"), "COMPETING_OWNER\n")

    def test_terminal_directory_commit_is_noreplace(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            destination = root / "terminal"
            first = root / ".first"
            first.mkdir()
            (first / "receipt.json").write_text("first\n", encoding="utf-8")
            runner.commit_directory_noreplace(first, destination)
            second = root / ".second"
            second.mkdir()
            (second / "receipt.json").write_text("second\n", encoding="utf-8")
            with self.assertRaises((OSError, runner.AnalysisProtocolError)):
                runner.commit_directory_noreplace(second, destination)
            self.assertEqual(
                (destination / "receipt.json").read_text(encoding="utf-8"),
                "first\n",
            )

    def test_design_freeze_fails_if_any_backend_terminal_is_visible(self) -> None:
        presence = {"backend_lock": "MISSING", **{
            item: ("PRESENT_REGULAR" if item == "KLT_R03" else "MISSING")
            for item in runner.ITEM_ORDER
        }}
        with mock.patch.object(runner, "backend_terminal_presence", return_value=presence):
            with self.assertRaisesRegex(
                runner.AnalysisProtocolError,
                "DESIGN_FREEZE_MUST_PRECEDE_BACKEND_LOCK_AND_TERMINAL_RESULTS",
            ):
                runner.build_design_freeze_payload("2026-08-28T00:00:00+00:00")

    def test_design_freeze_fails_if_backend_was_touched_without_receipt(self) -> None:
        terminals = {"backend_lock": "MISSING", **{
            item: "MISSING" for item in runner.ITEM_ORDER
        }}
        prelaunch = {
            "backend_root": "PRESENT",
            "backend_runtime_root": "ABSENT",
            **{f"workspace:{item}": "ABSENT" for item in runner.ITEM_ORDER},
        }
        with mock.patch.object(
            runner, "backend_terminal_presence", return_value=terminals
        ), mock.patch.object(
            runner, "backend_campaign_prelaunch_presence", return_value=prelaunch
        ):
            with self.assertRaisesRegex(
                runner.AnalysisProtocolError,
                "DESIGN_FREEZE_MUST_PRECEDE_ANY_BACKEND_CAMPAIGN_TOUCH",
            ):
                runner.build_design_freeze_payload("2026-08-28T00:00:00+00:00")

    def test_backend_binding_never_downgrades_around_deep_prior_receipt(self) -> None:
        bindings = {
            "klt": {
                "receipt": {"path": "/tmp/klt", "size_bytes": 1, "sha256": "3" * 64},
                "accepted_receipt": {
                    "path": "/tmp/klt", "size_bytes": 1, "sha256": "3" * 64
                },
            },
            "excluded_xfeat": {
                **exclusion(),
                "accepted_receipt_present": False,
                "backend_launched_count": 0,
            },
        }
        lock_id = {"path": "/tmp/backend-lock", "size_bytes": 1, "sha256": "4" * 64}
        fake_identity = {"path": "identity", "size_bytes": 1, "sha256": "5" * 64}
        items = {
            item: {"item_id": item, "arm": "klt", "repeat_index": index}
            for index, item in enumerate(runner.ITEM_ORDER, start=1)
        }
        lock = {
            "schema_version": "backend-lock-v2",
            "status": "BACKEND_LOCK_STATUS_V2",
            "item_order": list(runner.ITEM_ORDER),
            "frontend_authority": bindings,
            "static_identities": {"runner": fake_identity, "protocol": fake_identity},
            "items": items,
        }
        module = SimpleNamespace(
            ITEM_ORDER=runner.ITEM_ORDER,
            BACKEND_ROOT=runner.BACKEND_ROOT,
            DEFAULT_LOCK=runner.BACKEND_LOCK,
            RECEIPT_NAME=runner.BACKEND_RECEIPT_NAME,
            LOCK_SCHEMA="backend-lock-v2",
            LOCK_STATUS="BACKEND_LOCK_STATUS_V2",
            RECEIPT_SCHEMA="backend-receipt-v2",
            resolve_frontend_bindings=lambda: bindings,
            verify_lock=lambda path, live: (lock, lock_id),
            prior_receipt=mock.Mock(
                side_effect=runner.AnalysisProtocolError("DEEP_RECEIPT_REAUDIT_REJECTED")
            ),
        )
        with mock.patch.object(runner, "load_backend_authority_module", return_value=module), \
             mock.patch.object(runner, "identity", return_value=fake_identity), \
             mock.patch.object(
                 runner,
                 "collect_klt_frontend_binding",
                 return_value={"receipt": bindings["klt"]["receipt"]},
             ), \
             mock.patch.object(runner, "collect_xfeat_exclusion", return_value=exclusion()), \
             mock.patch.object(runner, "stable_json", return_value=({}, {"path": "r"})):
            with self.assertRaisesRegex(
                runner.AnalysisProtocolError, "DEEP_RECEIPT_REAUDIT_REJECTED"
            ):
                runner.collect_backend_binding()
        module.prior_receipt.assert_called_once()

    def test_staging_creation_fault_after_claim_is_terminalized(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "terminal"
            claim = root / "claim.json"
            staging = root / ".staging"
            evo = root / ".evo"
            failure = root / ".failure"
            lock = synthetic_lock((1,))
            lock_id = {"path": str(root / "lock.json"), "size_bytes": 1,
                       "sha256": "6" * 64}

            def fail_after_creating_staging() -> None:
                staging.mkdir()
                raise FileExistsError("injected staging fault")

            with mock.patch.multiple(
                runner,
                OUTPUT_ROOT=output,
                CLAIM_PATH=claim,
                STAGING_ROOT=staging,
                EVO_WORK_ROOT=evo,
                FAILURE_STAGING_ROOT=failure,
                DEFAULT_LOCK=root / "lock.json",
            ), mock.patch.object(
                runner, "verify_lock", return_value=(lock, lock_id)
            ), mock.patch.object(
                runner, "create_primary_staging_root", side_effect=fail_after_creating_staging
            ):
                code, receipt = runner.execute_analysis(root / "lock.json", runner.RUN_TOKEN)
                state = runner.analysis_output_state()
                terminal_audit = runner.audit_terminal_semantics(lock, lock_id)
            self.assertEqual(code, 3)
            self.assertEqual(
                state, "TERMINAL_RECEIPT_PRESENT_WITH_UNCOMMITTED_PARTIAL"
            )
            self.assertEqual(
                terminal_audit["status"], "PASS_TERMINAL_EVIDENCE_DEEP_AUDIT"
            )
            self.assertTrue(claim.is_file())
            self.assertTrue((output / runner.RECEIPT_NAME).is_file())
            self.assertEqual(
                receipt["status"],
                "TERMINAL_FORMAL_HFNET_VS_KLT_RANKING_NA_NO_RETRY",
            )
            formal = json.loads((output / runner.FORMAL_SUMMARY_NAME).read_text())
            self.assertTrue(runner.formal_metrics_are_all_na(formal))

    def test_partial_grid_writer_remains_only_uncommitted_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "terminal"
            claim = root / "claim.json"
            staging = root / ".staging"
            evo = root / ".evo"
            failure = root / ".failure"
            lock = synthetic_lock((1,))
            lock_id = {"path": str(root / "lock.json"), "size_bytes": 1,
                       "sha256": "7" * 64}
            primary = primary_summary((1,), (0.4,))

            def partial_grid(path: Path, *_: object) -> None:
                path.write_text("timestamp,reference_valid\npartial,9\n", encoding="utf-8")
                raise OSError("injected writer failure")

            evaluator = SimpleNamespace(
                write_grid_audit=partial_grid,
                write_metrics_csv=lambda *args: None,
            )
            with mock.patch.multiple(
                runner,
                OUTPUT_ROOT=output,
                CLAIM_PATH=claim,
                STAGING_ROOT=staging,
                EVO_WORK_ROOT=evo,
                FAILURE_STAGING_ROOT=failure,
                DEFAULT_LOCK=root / "lock.json",
            ), mock.patch.object(
                runner, "verify_lock", return_value=(lock, lock_id)
            ), mock.patch.object(
                runner,
                "evaluate_joint_inputs",
                return_value=(primary, object(), {}, {}, {"evaluator": evaluator}),
            ):
                code, _ = runner.execute_analysis(root / "lock.json", runner.RUN_TOKEN)
            self.assertEqual(code, 3)
            self.assertFalse((output / runner.RAW_SUMMARY_NAME).exists())
            partial = json.loads((output / runner.PARTIAL_EVIDENCE_NAME).read_text())
            self.assertEqual(partial["status"], "PRESERVED_UNCOMMITTED_PARTIAL_EVIDENCE")
            self.assertIn(runner.GRID_AUDIT_NAME, partial["tree"])

    def test_post_authority_integrity_failure_redacts_formal_numbers(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "terminal"
            claim = root / "claim.json"
            staging = root / ".staging"
            evo = root / ".evo"
            failure = root / ".failure"
            lock = synthetic_lock((1,))
            lock_id = {"path": str(root / "lock.json"), "size_bytes": 1,
                       "sha256": "8" * 64}
            primary = primary_summary((1,), (0.4,))
            primary["support"]["matched_count"] = 9
            primary["arms"]["HFNET"]["matched_count"] = 9
            primary["arms"]["KLT_R01"]["matched_count"] = 9
            evaluator = SimpleNamespace(
                write_grid_audit=lambda path, *_: path.write_text("partial\n"),
                write_metrics_csv=lambda path, *_: path.write_text("partial\n"),
            )
            with mock.patch.multiple(
                runner,
                OUTPUT_ROOT=output,
                CLAIM_PATH=claim,
                STAGING_ROOT=staging,
                EVO_WORK_ROOT=evo,
                FAILURE_STAGING_ROOT=failure,
                DEFAULT_LOCK=root / "lock.json",
            ), mock.patch.object(
                runner,
                "verify_lock",
                side_effect=[
                    (lock, lock_id),
                    runner.AnalysisProtocolError("post authority drift"),
                ],
            ), mock.patch.object(
                runner,
                "evaluate_joint_inputs",
                return_value=(primary, object(), {}, {}, {"evaluator": evaluator}),
            ):
                code, receipt = runner.execute_analysis(root / "lock.json", runner.RUN_TOKEN)
            self.assertEqual(code, 3)
            self.assertEqual(receipt["execution_integrity"]["status"], "FAIL")
            formal = json.loads((output / runner.FORMAL_SUMMARY_NAME).read_text())
            self.assertTrue(runner.formal_metrics_are_all_na(formal))
            self.assertFalse(formal["ranking_available"])

    def test_claimed_without_terminal_is_blocked_by_preflight_and_audit(self) -> None:
        design = {
            "status": "PASS_DESIGN_FROZEN_BEFORE_KLT_BACKEND_RESULTS",
            "accuracy_computed": False,
        }
        presence = {"backend_lock": "PRESENT_REGULAR", **{
            item: "PRESENT_REGULAR" for item in runner.ITEM_ORDER
        }}
        lock = synthetic_lock((1,))
        lock_id = {"path": "/tmp/lock", "size_bytes": 1, "sha256": "9" * 64}
        with tempfile.TemporaryDirectory() as directory:
            lock_path = Path(directory) / "lock.json"
            lock_path.write_text("{}\n", encoding="utf-8")
            with mock.patch.object(runner, "DEFAULT_LOCK", lock_path), mock.patch.object(
                runner, "design_freeze_audit_readonly", return_value=design
            ), mock.patch.object(
                runner, "backend_terminal_presence", return_value=presence
            ), mock.patch.object(
                runner, "verify_lock", return_value=(lock, lock_id)
            ), mock.patch.object(
                runner, "analysis_output_state",
                return_value="CLAIMED_WITHOUT_TERMINAL_RECEIPT",
            ):
                preflight = runner.preflight_readonly(lock_path)
                audit = runner.audit_readonly(lock_path)
        self.assertEqual(preflight["status"], "BLOCKED_PREFLIGHT")
        self.assertEqual(audit["status"], "FAIL_READ_ONLY_AUDIT")

    def test_claim_link_visible_after_publish_exception_is_terminalized(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "terminal"
            claim = root / "claim.json"
            staging = root / ".staging"
            evo = root / ".evo"
            failure = root / ".failure"
            lock_path = root / "lock.json"
            lock = synthetic_lock((1,))
            lock_id = {"path": str(lock_path), "size_bytes": 1, "sha256": "b" * 64}
            real_publish = runner.atomic_publish

            def publish_then_raise(path: Path, value: object) -> None:
                real_publish(path, value)
                if path == claim:
                    raise OSError("injected parent fsync exception after link")

            with mock.patch.multiple(
                runner,
                OUTPUT_ROOT=output,
                CLAIM_PATH=claim,
                STAGING_ROOT=staging,
                EVO_WORK_ROOT=evo,
                FAILURE_STAGING_ROOT=failure,
                DEFAULT_LOCK=lock_path,
                atomic_publish=publish_then_raise,
            ), mock.patch.object(
                runner, "verify_lock", return_value=(lock, lock_id)
            ):
                code, receipt = runner.execute_analysis(lock_path, runner.RUN_TOKEN)
            self.assertEqual(code, 3)
            self.assertTrue(claim.is_file())
            self.assertTrue((output / runner.RECEIPT_NAME).is_file())
            self.assertEqual(receipt["execution_integrity"]["status"], "FAIL")

    def test_noncanonical_analysis_lock_path_is_rejected(self) -> None:
        with self.assertRaisesRegex(
            runner.AnalysisProtocolError, "ANALYSIS_LOCK_PATH_MUST_BE_CANONICAL"
        ):
            runner.build_lock(Path("/tmp/noncanonical-a08-v2-lock.json"),
                              runner.BUILD_LOCK_TOKEN)

    def test_output_without_lock_fails_read_only_audit(self) -> None:
        with mock.patch.object(
            runner, "analysis_output_state", return_value="TERMINAL_RECEIPT_PRESENT"
        ):
            result = runner.audit_readonly(Path("/tmp/a08-v2-lock-definitely-absent"))
        self.assertEqual(result["status"], "FAIL_READ_ONLY_AUDIT")

    def test_terminal_with_bound_partial_staging_cannot_skip_deep_audit(self) -> None:
        lock = synthetic_lock((1,))
        lock_id = {"path": "/tmp/lock", "size_bytes": 1, "sha256": "c" * 64}
        terminal = {
            "status": "PASS_TERMINAL_EVIDENCE_DEEP_AUDIT",
            "formal_ranking_available": False,
        }
        with tempfile.TemporaryDirectory() as directory:
            lock_path = Path(directory) / "lock.json"
            lock_path.write_text("{}\n", encoding="utf-8")
            deep = mock.Mock(return_value=terminal)
            with mock.patch.object(runner, "DEFAULT_LOCK", lock_path), \
                 mock.patch.object(runner, "verify_lock", return_value=(lock, lock_id)), \
                 mock.patch.object(
                     runner,
                     "analysis_output_state",
                     return_value="TERMINAL_RECEIPT_PRESENT_WITH_UNCOMMITTED_PARTIAL",
                 ), \
                 mock.patch.object(runner, "audit_terminal_semantics", deep):
                result = runner.audit_readonly(lock_path)
        self.assertEqual(result["status"], "PASS_TERMINAL_EVIDENCE_DEEP_AUDIT")
        deep.assert_called_once_with(lock, lock_id)

    def test_garbage_grid_timestamp_and_nonbinary_validity_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "grid.csv"
            fields = [
                "timestamp", "reference_valid", "HFNET_valid",
                "common_valid", "segment_id",
            ]
            with path.open("w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(handle, fieldnames=fields)
                writer.writeheader()
                for _ in range(33):
                    writer.writerow({
                        "timestamp": "GARBAGE",
                        "reference_valid": "9",
                        "HFNET_valid": "9",
                        "common_valid": "9",
                        "segment_id": "0",
                    })
            reference = SimpleNamespace(
                stamps=runner.exact_grid_seconds(), valid=np.ones(33, dtype=bool)
            )
            arms = {"HFNET": SimpleNamespace(valid=np.ones(33, dtype=bool))}
            evaluation = {
                "common_mask": np.ones(33, dtype=bool),
                "segments": np.zeros(33, dtype=int),
            }
            with self.assertRaisesRegex(
                runner.AnalysisProtocolError, "PRIMARY_GRID_AUDIT_ROW:0"
            ):
                runner.common.validate_grid_audit_file(
                    path, reference, arms, evaluation
                )

    def test_tampered_metrics_csv_is_rejected_against_primary(self) -> None:
        primary = primary_summary((1,), (0.4,))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "metrics.csv"
            path.write_text("arm,ape_rmse_m\nHFNET,999\n", encoding="utf-8")
            with self.assertRaisesRegex(
                runner.AnalysisProtocolError,
                "PRIMARY_METRICS_CSV_RECOMPUTATION",
            ):
                runner.validate_primary_metrics_csv_file(path, primary)

    def test_xfeat_slot_relabel_is_rejected_by_formal_audit(self) -> None:
        lock = synthetic_lock((1,))
        primary = primary_summary((1,), (0.4,))
        formal = runner.build_formal_summary(
            lock, primary, runner.support_gate(primary), pass_evo_audit()
        )
        xfeat = next(
            row for row in formal["original_ten_slot_dispositions"]
            if row["arm"] == "xfeat"
        )
        xfeat["backend_launched"] = True
        with self.assertRaisesRegex(
            runner.AnalysisProtocolError, "FORMAL_XFEAT_SLOT"
        ):
            runner.validate_formal_population_binding(formal, lock)


if __name__ == "__main__":
    unittest.main()
