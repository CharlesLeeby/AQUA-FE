#!/usr/bin/env python3

from __future__ import annotations

import json
import tempfile
from types import SimpleNamespace
import unittest
from pathlib import Path
from unittest import mock

import numpy as np

from scripts import run_a08_recovered_july_joint_common_support_v1 as runner


def metric_row(base: float, matched: int = 31, pairs: int = 31) -> dict[str, float | int]:
    return {
        "matched_count": matched,
        "rpe_pairs": pairs,
        **{
            name: base + index / 100.0
            for index, name in enumerate(runner.PRIMARY_METRICS)
        },
    }


def planned_rows(
    accepted_klt: tuple[int, ...] = (1,),
    accepted_xfeat: tuple[int, ...] = (1,),
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for item_id in runner.ITEM_ORDER:
        arm = "klt" if item_id.startswith("KLT_") else "xfeat"
        repeat = int(item_id[-2:])
        accepted = repeat in (accepted_klt if arm == "klt" else accepted_xfeat)
        rows.append(
            {
                "item_id": item_id,
                "arm": arm,
                "repeat_index": repeat,
                "disposition": (
                    "PASS_BACKEND_REPLAY_ACCEPTED"
                    if accepted
                    else "FAILED_BACKEND_REPLAY_NO_REPLACEMENT"
                ),
                "accepted_for_joint_mask": accepted,
                "trajectory": (
                    {"path": f"/tmp/{item_id}.csv", "size_bytes": 1, "sha256": "0" * 64}
                    if accepted
                    else None
                ),
            }
        )
    return rows


def synthetic_lock(
    accepted_klt: tuple[int, ...] = (1,),
    accepted_xfeat: tuple[int, ...] = (1,),
) -> dict[str, object]:
    rows = planned_rows(accepted_klt, accepted_xfeat)
    return {
        "authority": {
            "backend": {
                "planned_repeats": rows,
                "valid_counts": {
                    "klt": len(accepted_klt),
                    "xfeat": len(accepted_xfeat),
                },
                "xfeat_method_native_label": {
                    "profile": "klt_safe_fallback",
                    "label": "XFeat arbitration system — method-native KLT safe fallback",
                    "method_native_klt_safe_fallback": True,
                    "exported_learned_observations": 0,
                    "learning_contribution_claim_permitted": False,
                },
            }
        }
    }


class A08JointCommonSupportTest(unittest.TestCase):
    def test_atomic_publish_never_overwrites_competing_owner(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "receipt.json"
            real_link = runner.os.link

            def competing_link(source: object, destination: object, **kwargs: object) -> None:
                target.write_text("COMPETING_OWNER\n", encoding="utf-8")
                real_link(source, destination, **kwargs)

            with mock.patch.object(runner.os, "link", side_effect=competing_link):
                with self.assertRaises(FileExistsError):
                    runner.atomic_publish(target, {"ours": True})
            self.assertEqual(target.read_text(encoding="utf-8"), "COMPETING_OWNER\n")
            self.assertEqual(list(Path(directory).glob(".*.tmp.*")), [])

    def test_terminal_directory_commit_is_atomic_and_noreplace(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory)
            staging = parent / ".staging"
            destination = parent / "terminal"
            staging.mkdir()
            (staging / "receipt.json").write_text("{}\n", encoding="utf-8")
            runner.commit_directory_noreplace(staging, destination)
            self.assertFalse(staging.exists())
            self.assertEqual(
                (destination / "receipt.json").read_text(encoding="utf-8"), "{}\n"
            )

            second_staging = parent / ".second-staging"
            second_staging.mkdir()
            (second_staging / "receipt.json").write_text("ours\n", encoding="utf-8")
            with self.assertRaises((runner.AnalysisProtocolError, FileExistsError, OSError)):
                runner.commit_directory_noreplace(second_staging, destination)
            self.assertEqual(
                (destination / "receipt.json").read_text(encoding="utf-8"), "{}\n"
            )
            self.assertTrue(second_staging.is_dir())

    def test_staging_creation_fault_after_claim_is_terminalized_as_na(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory)
            output = parent / "terminal"
            claim = parent / "claim.json"
            staging = parent / ".staging"
            failure_staging = parent / ".failure-staging"
            lock = synthetic_lock((1,), (1,))
            lock["contract_sha256"] = "b" * 64
            lock_id = {
                "path": str(parent / "analysis-lock.json"),
                "size_bytes": 1,
                "sha256": "c" * 64,
            }

            def fail_after_creating_staging() -> None:
                staging.mkdir()
                raise FileExistsError("injected post-claim staging fault")

            with mock.patch.multiple(
                runner,
                OUTPUT_ROOT=output,
                CLAIM_PATH=claim,
                STAGING_ROOT=staging,
                FAILURE_STAGING_ROOT=failure_staging,
                CAMPAIGN_PERMANENTLY_GATE_CLOSED=False,
            ), mock.patch.object(
                runner, "verify_lock", return_value=(lock, lock_id)
            ), mock.patch.object(
                runner,
                "create_primary_staging_root",
                side_effect=fail_after_creating_staging,
            ):
                code, receipt = runner.execute_analysis(
                    parent / "analysis-lock.json", runner.RUN_TOKEN
                )
            self.assertEqual(code, 3)
            self.assertTrue(claim.is_file())
            self.assertTrue((output / runner.RECEIPT_NAME).is_file())
            self.assertEqual(receipt["status"], "TERMINAL_FORMAL_RANKING_NA_NO_RETRY")
            formal = json.loads((output / runner.FORMAL_SUMMARY_NAME).read_text())
            self.assertFalse(formal["ranking_available"])
            self.assertTrue(runner.formal_metrics_are_all_na(formal))

    def test_partial_grid_writer_is_preserved_only_as_uncommitted_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory)
            output = parent / "terminal"
            claim = parent / "claim.json"
            staging = parent / ".staging"
            failure_staging = parent / ".failure-staging"
            lock = synthetic_lock((1,), (1,))
            lock["contract_sha256"] = "d" * 64
            lock_id = {
                "path": str(parent / "analysis-lock.json"),
                "size_bytes": 1,
                "sha256": "e" * 64,
            }
            primary = {
                "protocol": {"single_joint_mask": True},
                "support": {"matched_count": 31, "rpe_pairs": 31},
                "arms": {
                    "HFNET": metric_row(0.1),
                    "KLT_R01": metric_row(0.2),
                    "XFEAT_R01": metric_row(0.3),
                },
            }

            def partial_grid(path: Path, *_args: object) -> None:
                path.write_text("timestamp,reference_valid\npartial,1\n")
                raise OSError("injected grid writer failure")

            fake_evaluator = SimpleNamespace(
                write_grid_audit=partial_grid,
                write_metrics_csv=lambda *_args: None,
            )
            evaluated = (
                primary, object(), {}, {}, {"evaluator": fake_evaluator, "core": object()}
            )
            with mock.patch.multiple(
                runner,
                OUTPUT_ROOT=output,
                CLAIM_PATH=claim,
                STAGING_ROOT=staging,
                FAILURE_STAGING_ROOT=failure_staging,
                CAMPAIGN_PERMANENTLY_GATE_CLOSED=False,
            ), mock.patch.object(
                runner, "verify_lock", return_value=(lock, lock_id)
            ), mock.patch.object(
                runner, "evaluate_joint_inputs", return_value=evaluated
            ):
                code, receipt = runner.execute_analysis(
                    parent / "analysis-lock.json", runner.RUN_TOKEN
                )
            self.assertEqual(code, 3)
            self.assertEqual(receipt["execution_integrity"]["status"], "FAIL")
            self.assertFalse((output / runner.RAW_SUMMARY_NAME).exists())
            self.assertFalse((output / runner.GRID_AUDIT_NAME).exists())
            self.assertTrue(staging.is_dir())
            self.assertTrue((staging / runner.RAW_SUMMARY_NAME).is_file())
            self.assertTrue((staging / runner.GRID_AUDIT_NAME).is_file())
            partial = json.loads(
                (output / "uncommitted_partial_evidence_v1.json").read_text()
            )
            self.assertEqual(partial["status"], "PRESERVED_UNCOMMITTED_PARTIAL_EVIDENCE")

    def test_exact_integer_grid_has_33_points_and_does_not_add_endpoint(self) -> None:
        evidence = runner.exact_grid_evidence()
        self.assertEqual(evidence["grid_count"], 33)
        self.assertEqual(evidence["timestamps_ns"][0], runner.START_NS)
        self.assertEqual(evidence["timestamps_ns"][-1], 1542885193111831216)
        self.assertEqual(evidence["window_end_minus_grid_last_ns"], 994391456)
        self.assertLess(evidence["grid_last_ns"], evidence["window_end_ns_inclusive"])
        self.assertEqual(
            {right - left for left, right in zip(
                evidence["timestamps_ns"], evidence["timestamps_ns"][1:]
            )},
            {1_000_000_000},
        )

    def test_fallback_profile_forbids_learning_contribution_claim(self) -> None:
        receipt = {
            "schema_version": runner.FRONTEND_RECEIPT_SCHEMA,
            "status": "PASS_FRONTEND_EXPORT_ACCEPTED",
            "stage": "xfeat",
            "artifact_audit": {
                "final": {
                    "arbitration": {"profile": "klt_safe_fallback"},
                    "method_native_action": {
                        "exported_learned_full": 0,
                        "exported_xfeat_full": 0,
                    },
                }
            },
        }
        result = runner.classify_xfeat_profile(receipt)
        self.assertTrue(result["method_native_klt_safe_fallback"])
        self.assertFalse(result["learning_contribution_claim_permitted"])
        self.assertIn("KLT safe fallback", result["label"])

    def test_fallback_profile_rejects_hidden_learned_observations(self) -> None:
        receipt = {
            "schema_version": runner.FRONTEND_RECEIPT_SCHEMA,
            "status": "PASS_FRONTEND_EXPORT_ACCEPTED",
            "stage": "xfeat",
            "artifact_audit": {
                "final": {
                    "arbitration": {"profile": "klt_safe_fallback"},
                    "method_native_action": {
                        "exported_learned_full": 1,
                        "exported_xfeat_full": 1,
                    },
                }
            },
        }
        with self.assertRaisesRegex(runner.AnalysisProtocolError, "FALLBACK_EXPORTED"):
            runner.classify_xfeat_profile(receipt)

    def test_terminal_receipt_accepts_scientific_failure_as_na(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            item_id = "KLT_R01"
            output = root / item_id
            output.mkdir()
            claim_path = output / "process_start_claim_v1.json"
            log_path = output / "supervisor_process.log"
            claim_path.write_text("{}\n", encoding="utf-8")
            log_path.write_text("scientific failure\n", encoding="utf-8")
            namespace_path = output / "network_namespace_manifest.json"
            guard_path = output / "replay_only_guard_manifest.json"
            namespace_path.write_text("{}\n", encoding="utf-8")
            guard_path.write_text("{}\n", encoding="utf-8")
            lock_identity = {
                "path": "/tmp/backend-lock.json",
                "size_bytes": 1,
                "sha256": "a" * 64,
            }
            receipt = {
                "schema_version": runner.BACKEND_RECEIPT_SCHEMA,
                "status": "FAILED_BACKEND_REPLAY_NO_REPLACEMENT",
                "item_id": item_id,
                "arm": "klt",
                "repeat_index": 1,
                "execution_lock": lock_identity,
                "launch_allowance_consumed": True,
                "retry_count": 0,
                "replacement_permitted": False,
                "integrity_fault_latch": [],
                "execution_integrity": {
                    "status": "PASS",
                    "irreversible_fault_latch_clear": True,
                },
                "trajectory_convention": "world_T_body",
                "runtime": {
                    "popen_invocation_count": 1,
                    "child_started": True,
                    "process_group": {
                        "leader_reaped": True,
                        "process_group_empty": True,
                        "owned_descendants_empty": True,
                    },
                },
                "claim": runner.identity(claim_path.absolute()),
                "process_log": runner.identity(log_path.absolute()),
                "artifact_contract": {
                    "status": "FAIL",
                    "evidence_tree_integrity": True,
                    "integrity_issues": [],
                    # The existing backend authority performs the semantic
                    # audits before this local classifier is reached.  Keep
                    # both mandatory execution-boundary artifacts present in
                    # this process-free unit fixture.
                    "outputs": {
                        "network_namespace_manifest.json": runner.identity(
                            namespace_path.absolute()
                        ),
                        "replay_only_guard_manifest.json": runner.identity(
                            guard_path.absolute()
                        ),
                    },
                },
            }
            locked_item = {"item_id": item_id, "arm": "klt", "repeat_index": 1}
            with mock.patch.object(runner, "BACKEND_ROOT", root):
                result = runner.validate_terminal_receipt(
                    item_id, receipt, lock_identity, locked_item
                )
        self.assertFalse(result["accepted_for_joint_mask"])
        self.assertTrue(result["planned_failure_is_na_not_replaced"])
        self.assertIsNone(result["trajectory"])

    def test_terminal_receipt_integrity_failure_blocks(self) -> None:
        receipt = {
            "schema_version": runner.BACKEND_RECEIPT_SCHEMA,
            "status": "FAILED_BACKEND_REPLAY_NO_REPLACEMENT",
            "item_id": "KLT_R01",
            "arm": "klt",
            "repeat_index": 1,
            "execution_lock": {"path": "/x", "size_bytes": 1, "sha256": "a" * 64},
            "launch_allowance_consumed": True,
            "retry_count": 0,
            "replacement_permitted": False,
            "integrity_fault_latch": ["FAULT"],
            "execution_integrity": {
                "status": "FAIL",
                "irreversible_fault_latch_clear": False,
            },
            "trajectory_convention": "world_T_body",
        }
        with self.assertRaisesRegex(runner.AnalysisProtocolError, "EXECUTION_INTEGRITY"):
            runner.validate_terminal_receipt(
                "KLT_R01",
                receipt,
                receipt["execution_lock"],
                {"item_id": "KLT_R01", "arm": "klt", "repeat_index": 1},
            )

    def test_support_gate_uses_fixed_denominator_33(self) -> None:
        passing = {
            "support": {
                "grid_count": 33,
                "matched_count": 30,
                "common_span_s": 29.0,
                "rpe_pairs": 28,
                "ape_valid": True,
                "rpe_valid": True,
            }
        }
        self.assertEqual(runner.support_gate(passing)["status"], "PASS")
        failing = json.loads(json.dumps(passing))
        failing["support"]["matched_count"] = 29
        failing["support"]["ape_valid"] = False
        gate = runner.support_gate(failing)
        self.assertEqual(gate["status"], "FAIL")
        self.assertIn("matched_at_least_30", gate["failure_codes"])

    def test_evo_crosscheck_requires_same_arms_pairs_and_tolerance(self) -> None:
        primary = {
            "support": {"rpe_pairs": 31},
            "arms": {"HFNET": metric_row(1.0), "KLT_R01": metric_row(2.0)},
        }
        evo = {
            "evo_version": "1.31.1",
            "rpe_delta_frames": 1,
            "rpe_semantics": "aligned_global_frame_positional_delta",
            "arms": {
                name: {
                    "primary_ape_rmse_m": metrics["ape_rmse_m"],
                    "evo_ape_rmse_m": metrics["ape_rmse_m"] + 1e-7,
                    "ape_abs_diff_m": 1e-7,
                    "primary_rpe_rmse_m": metrics["rpe_rmse_m"],
                    "evo_segmented_rpe_rmse_m": metrics["rpe_rmse_m"] + 1e-7,
                    "rpe_abs_diff_m": 1e-7,
                    "rpe_pair_count": 31,
                    "segments": [
                        {
                            "segment_id": 0,
                            "pair_count": 31,
                            "rmse_m": metrics["rpe_rmse_m"] + 1e-7,
                        }
                    ],
                }
                for name, metrics in primary["arms"].items()
            },
        }
        audit = runner.validate_evo_crosscheck(
            evo, primary, ["HFNET", "KLT_R01"], "1.31.1"
        )
        self.assertEqual(audit["status"], "PASS")
        evo["arms"]["KLT_R01"]["rpe_abs_diff_m"] = 2e-5
        audit = runner.validate_evo_crosscheck(
            evo, primary, ["HFNET", "KLT_R01"], "1.31.1"
        )
        self.assertEqual(audit["status"], "FAIL")
        self.assertIn(
            "KLT_R01:rpe_reported_diff_matches_actual", audit["failure_codes"]
        )

    def test_evo_crosscheck_recomputes_differences_instead_of_trusting_report(self) -> None:
        primary = {
            "support": {"rpe_pairs": 10},
            "arms": {"HFNET": {**metric_row(1.0, matched=30, pairs=10)}},
        }
        row = {
            "primary_ape_rmse_m": primary["arms"]["HFNET"]["ape_rmse_m"],
            "evo_ape_rmse_m": 999.0,
            "ape_abs_diff_m": 0.0,
            "primary_rpe_rmse_m": primary["arms"]["HFNET"]["rpe_rmse_m"],
            "evo_segmented_rpe_rmse_m": 888.0,
            "rpe_abs_diff_m": 0.0,
            "rpe_pair_count": 10,
            "segments": [{"segment_id": 0, "pair_count": 10, "rmse_m": 888.0}],
        }
        evo = {
            "evo_version": "1.31.1",
            "rpe_delta_frames": 1,
            "rpe_semantics": "aligned_global_frame_positional_delta",
            "arms": {"HFNET": row},
        }
        audit = runner.validate_evo_crosscheck(
            evo, primary, ["HFNET"], "1.31.1"
        )
        self.assertEqual(audit["status"], "FAIL")
        self.assertIn("HFNET:ape_reported_diff_matches_actual", audit["failure_codes"])
        self.assertIn("HFNET:ape_diff_within_tolerance", audit["failure_codes"])

    def test_formal_summary_uses_median_not_best_and_keeps_all_plans(self) -> None:
        lock = synthetic_lock((1, 2, 3), (1, 2))
        primary_arms = {
            "HFNET": metric_row(0.8),
            "KLT_R01": metric_row(0.5),
            "XFEAT_R01": metric_row(0.4),
            "KLT_R02": metric_row(0.1),
            "XFEAT_R02": metric_row(0.2),
            "KLT_R03": metric_row(0.3),
        }
        primary = {
            "arms": primary_arms,
            "support": {"matched_count": 31, "rpe_pairs": 31},
        }
        gate = {"status": "PASS", "failure_codes": []}
        evo = {"status": "PASS", "failure_codes": []}
        formal = runner.build_formal_summary(lock, primary, gate, evo)
        self.assertTrue(formal["ranking_available"])
        self.assertEqual(len(formal["planned_repeats"]), 10)
        self.assertEqual(formal["klt"]["planned_count"], 5)
        self.assertEqual(formal["klt"]["valid_count"], 3)
        self.assertAlmostEqual(formal["klt"]["formal_median_metrics"]["ape_rmse_m"], 0.3)
        self.assertNotEqual(formal["klt"]["formal_median_metrics"]["ape_rmse_m"], 0.1)
        self.assertFalse(formal["klt"]["best_run_selected"])
        failed = next(row for row in formal["planned_repeats"] if row["item_id"] == "KLT_R04")
        self.assertTrue(failed["scientific_failure_retained_as_na"])
        self.assertTrue(all(value is None for value in failed["formal_metrics"].values()))

    def test_any_gate_failure_nulls_every_formal_ranking_metric(self) -> None:
        lock = synthetic_lock((1,), (1,))
        primary = {
            "arms": {
                "HFNET": metric_row(0.8),
                "KLT_R01": metric_row(0.5),
                "XFEAT_R01": metric_row(0.4),
            },
            "support": {"matched_count": 3, "rpe_pairs": 2},
        }
        formal = runner.build_formal_summary(
            lock,
            primary,
            {"status": "FAIL", "failure_codes": ["exact_1s_rpe_pairs_at_least_10"]},
            {"status": "NOT_RUN_SUPPORT_GATE_CLOSED", "failure_codes": ["GATE"]},
        )
        self.assertFalse(formal["ranking_available"])
        self.assertTrue(all(value is None for value in formal["hfnet"]["formal_metrics"].values()))
        self.assertTrue(all(value is None for value in formal["klt"]["formal_median_metrics"].values()))
        self.assertTrue(all(value is None for value in formal["xfeat"]["formal_median_metrics"].values()))
        for row in formal["planned_repeats"]:
            self.assertTrue(all(value is None for value in row["formal_metrics"].values()))

    def test_post_integrity_failure_nulls_previously_available_ranking(self) -> None:
        lock = synthetic_lock((1,), (1,))
        primary = {
            "arms": {
                "HFNET": metric_row(0.8),
                "KLT_R01": metric_row(0.5),
                "XFEAT_R01": metric_row(0.4),
            },
            "support": {"matched_count": 31, "rpe_pairs": 31},
        }
        formal = runner.build_formal_summary(
            lock,
            primary,
            {"status": "PASS", "failure_codes": []},
            {"status": "PASS", "failure_codes": []},
        )
        self.assertTrue(formal["ranking_available"])
        closed = runner.force_all_formal_metrics_na_for_integrity(
            formal, ["EXECUTION_INTEGRITY:POST_AUTHORITY_FAILURE"]
        )
        self.assertFalse(closed["ranking_available"])
        self.assertEqual(closed["execution_integrity_gate"]["status"], "FAIL")
        self.assertTrue(all(value is None for value in closed["hfnet"]["formal_metrics"].values()))
        self.assertTrue(all(value is None for value in closed["klt"]["formal_median_metrics"].values()))
        self.assertTrue(all(value is None for value in closed["xfeat"]["formal_median_metrics"].values()))
        for row in closed["planned_repeats"]:
            self.assertTrue(all(value is None for value in row["formal_metrics"].values()))

    def test_missing_primary_metric_closes_ranking_instead_of_partial_table(self) -> None:
        lock = synthetic_lock((1,), (1,))
        incomplete = {
            "matched_count": 31,
            "rpe_pairs": 31,
            "ape_rmse_m": 0.1,
            "rpe_rmse_m": 0.2,
        }
        primary = {
            "arms": {
                "HFNET": dict(incomplete),
                "KLT_R01": dict(incomplete),
                "XFEAT_R01": dict(incomplete),
            },
            "support": {"matched_count": 31, "rpe_pairs": 31},
        }
        formal = runner.build_formal_summary(
            lock,
            primary,
            {"status": "PASS", "failure_codes": []},
            {"status": "PASS", "failure_codes": []},
        )
        self.assertFalse(formal["ranking_available"])
        self.assertEqual(
            formal["primary_arm_completeness_gate"]["status"], "FAIL"
        )
        self.assertTrue(all(value is None for value in formal["hfnet"]["formal_metrics"].values()))

    def test_grid_audit_rejects_garbage_timestamps_and_nonboolean_validity(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "grid.csv"
            path.write_text(
                "timestamp,reference_valid,HFNET_valid,common_valid,segment_id\n"
                + "".join("GARBAGE,9,9,9,0\n" for _ in range(runner.GRID_COUNT)),
                encoding="utf-8",
            )
            grid = runner.exact_grid_seconds()
            reference = SimpleNamespace(
                stamps=grid, valid=np.ones(runner.GRID_COUNT, dtype=bool)
            )
            arms = {
                "HFNET": SimpleNamespace(
                    valid=np.ones(runner.GRID_COUNT, dtype=bool)
                )
            }
            evaluation = {
                "common_mask": np.ones(runner.GRID_COUNT, dtype=bool),
                "segments": np.zeros(runner.GRID_COUNT, dtype=int),
            }
            with self.assertRaisesRegex(
                runner.AnalysisProtocolError, "PRIMARY_GRID_AUDIT_ROW:0"
            ):
                runner.validate_grid_audit_file(
                    path, reference, arms, evaluation
                )

    def test_accepted_arm_population_is_fixed_before_accuracy(self) -> None:
        lock = synthetic_lock((1, 3), (2,))
        paths = runner.accepted_arm_paths(lock["authority"]["backend"])
        self.assertEqual(
            list(paths), ["HFNET", "KLT_R01", "XFEAT_R02", "KLT_R03"]
        )
        self.assertNotIn("KLT_R02", paths)
        self.assertNotIn("XFEAT_R01", paths)

    def test_contract_binds_integer_grid_single_mask_and_no_best_selection(self) -> None:
        authority = {
            "support": {"receipt": {"sha256": "a" * 64}},
            "backend": {"terminal_receipts": {}},
            "static_identities": {},
            "evo": {"version": "1.31.1"},
        }
        contract = runner.contract_core(authority)
        self.assertEqual(contract["grid"]["timestamps_ns"], list(runner.GRID_NS))
        self.assertTrue(
            contract["evaluation_contract"][
                "single_joint_mask_across_hfnet_and_all_accepted_repeats"
            ]
        )
        self.assertFalse(contract["population_policy"]["best_run_selection_permitted"])
        self.assertTrue(contract["execution_policy"]["ranking_gate_failure_sets_all_formal_metrics_na"])

    def test_waiting_preflight_does_not_open_dynamic_authority(self) -> None:
        missing = {"backend_lock": "MISSING"}
        with mock.patch.object(runner, "CAMPAIGN_PERMANENTLY_GATE_CLOSED", False), \
             mock.patch.object(runner, "required_terminal_presence", return_value=missing), \
             mock.patch.object(
                 runner,
                 "design_freeze_audit_readonly",
                 return_value={
                     "status": "PASS_DESIGN_FROZEN_BEFORE_DYNAMIC_RESULTS",
                     "accuracy_computed": False,
                 },
             ), \
             mock.patch.object(runner, "collect_authority", side_effect=AssertionError("must not open")):
            result = runner.preflight_readonly(Path("/tmp/nonexistent-a08-analysis-lock.json"))
        self.assertEqual(
            result["status"],
            "WAITING_FOR_BACKEND_FINAL_LOCK_AND_TEN_TERMINAL_RECEIPTS",
        )
        self.assertFalse(result["accuracy_computed"])

    def test_claimed_without_terminal_is_blocked_by_preflight_and_audit(self) -> None:
        design = {
            "status": "PASS_DESIGN_FROZEN_BEFORE_DYNAMIC_RESULTS",
            "accuracy_computed": False,
        }
        presence = {"backend_lock": "PRESENT_REGULAR"}
        lock = {"contract_sha256": "f" * 64}
        lock_id = {"path": "/tmp/lock", "size_bytes": 1, "sha256": "a" * 64}
        with tempfile.TemporaryDirectory() as directory:
            lock_path = Path(directory) / "lock.json"
            lock_path.write_text("{}\n", encoding="utf-8")
            with mock.patch.object(runner, "CAMPAIGN_PERMANENTLY_GATE_CLOSED", False), mock.patch.object(
                runner, "design_freeze_audit_readonly", return_value=design
            ), mock.patch.object(
                runner, "required_terminal_presence", return_value=presence
            ), mock.patch.object(
                runner, "verify_lock", return_value=(lock, lock_id)
            ), mock.patch.object(
                runner,
                "analysis_output_state",
                return_value="CLAIMED_WITHOUT_TERMINAL_RECEIPT",
            ):
                preflight = runner.preflight_readonly(lock_path)
                audit = runner.audit_readonly(lock_path)
        self.assertEqual(preflight["status"], "BLOCKED_PREFLIGHT")
        self.assertEqual(audit["status"], "FAIL_READ_ONLY_AUDIT")

    def test_three_arm_campaign_is_permanently_gate_closed(self) -> None:
        preflight = runner.preflight_readonly(Path("/tmp/never-build-a08-v1.json"))
        audit = runner.audit_readonly(Path("/tmp/never-build-a08-v1.json"))
        self.assertEqual(
            preflight["xfeat_disposition"],
            "NA_FRONTEND_STRUCTURAL_GATE_FAILED_NOT_LAUNCHED",
        )
        self.assertEqual(
            audit["status"],
            "BLOCKED_THREE_ARM_CAMPAIGN_PERMANENTLY_GATE_CLOSED",
        )
        with self.assertRaisesRegex(
            runner.AnalysisProtocolError,
            "THREE_ARM_CAMPAIGN_PERMANENTLY_GATE_CLOSED",
        ):
            runner.build_lock(Path("/tmp/never-build-a08-v1.json"), runner.BUILD_LOCK_TOKEN)
        with self.assertRaisesRegex(
            runner.AnalysisProtocolError,
            "THREE_ARM_CAMPAIGN_PERMANENTLY_GATE_CLOSED",
        ):
            runner.execute_analysis(Path("/tmp/never-build-a08-v1.json"), runner.RUN_TOKEN)


if __name__ == "__main__":
    unittest.main()
