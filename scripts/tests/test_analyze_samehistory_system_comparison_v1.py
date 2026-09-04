#!/usr/bin/env python3
"""Synthetic tests for the same-history system analysis v1."""

from __future__ import annotations

import csv
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from scripts import analyze_samehistory_system_comparison_v1 as analysis


class SameHistoryAnalysisTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def camera(self, sequence: str) -> analysis.CameraGrid:
        feed_start, feed_end = analysis.WINDOWS[sequence]["feed"]
        base = 1_500_000_000_000_000_000
        stamps = tuple(
            base + 50_000_000 * offset
            for offset in range(feed_end - feed_start + 1)
        )
        return analysis.CameraGrid(
            sequence, feed_start, feed_end, stamps, self.root / f"{sequence}.csv"
        )

    def write_vio(self, path: Path, stamps: list[int], *, nonfinite: bool = False) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        rows = []
        for index, stamp in enumerate(stamps):
            x = "nan" if nonfinite and index == 0 else str(index * 0.01)
            rows.append(f"{stamp},{x},0,0,1,0,0,0\n")
        path.write_text("".join(rows), encoding="ascii")

    def payload_comparison_fixture(
        self,
        *,
        external_bag: bytes = b"same feature payload",
        proposed_bag: bytes = b"same feature payload",
        external_vio: bytes = b"external trajectory",
        proposed_vio: bytes = b"proposed trajectory",
        learned_total: int = 0,
    ) -> tuple[dict[str, analysis.ArmPaths], list[dict[str, object]]]:
        paths: dict[str, analysis.ArmPaths] = {}
        for method, bag_bytes, vio_bytes in (
            ("external_klt", external_bag, external_vio),
            ("aquafe_proposed_safe", proposed_bag, proposed_vio),
        ):
            run = self.root / "h07" / method
            run.mkdir(parents=True, exist_ok=True)
            (run / "features.bag").write_bytes(bag_bytes)
            trajectory = run / "vins_output/vio.csv"
            trajectory.parent.mkdir(parents=True, exist_ok=True)
            trajectory.write_bytes(vio_bytes)
            paths[f"h07_{method}"] = analysis.ArmPaths(
                f"h07_{method}",
                "H07",
                method,
                run,
                run / analysis.RECEIPT_NAME,
                trajectory,
                run / "vins.log",
                run / "frontend_metrics.csv",
                run / "config.yaml",
            )
        rows: list[dict[str, object]] = [
            {
                "sequence": "H07",
                "method": "external_klt",
                "usability": {"status": "PASS"},
                "frontend": {"segments": {"full": {"learned_observations": {"total": 0}}}},
            },
            {
                "sequence": "H07",
                "method": "aquafe_proposed_safe",
                "usability": {"status": "PASS"},
                "frontend": {
                    "segments": {
                        "full": {
                            "learned_observations": {"total": learned_total},
                            "learned_pipeline_activity": {
                                "learned_candidate_count_sum": 17,
                                "pre_gate_sidecar_total_sum": 29,
                                "learned_export_gate_dropped_sum": 29,
                                "interpretation": (
                                    "SUMMED_PER-FRAME_DIAGNOSTIC_COUNTS_NOT_INDEPENDENT_SAMPLES"
                                ),
                            },
                        }
                    },
                    "learned_pipeline_activity_columns_present": {
                        "learned_candidate_count_sum": True,
                        "pre_gate_sidecar_total_sum": True,
                        "learned_export_gate_dropped_sum": True,
                    },
                },
            },
        ]
        return paths, rows

    def test_external_frozen_native_grids_are_a06_odd125_h07_even31(self) -> None:
        for sequence, method, expected_count, phase in (
            ("A06", "external_klt", 125, "odd"),
            ("H07", "aquafe_proposed_safe", 31, "even"),
        ):
            camera = self.camera(sequence)
            start, end = analysis.WINDOWS[sequence]["score"]
            frozen_phase = analysis.WINDOWS[sequence]["external_phase"]
            sources = [value for value in range(start, end + 1) if value % 2 == frozen_phase]
            stamps = [camera.stamp_for_source(value) for value in sources]
            association = analysis.associate_stamps_to_camera(stamps, camera)
            support = analysis.score_support(sequence, method, camera, association)
            self.assertEqual(support["phase"], phase)
            self.assertEqual(support["method_native_expected_count"], expected_count)
            self.assertEqual(support["method_native_covered_count"], expected_count)
            self.assertEqual(support["method_native_coverage_fraction"], 1.0)
            self.assertEqual(support["method_native_longest_contiguous_count"], expected_count)

    def test_origin_mt1_phase_is_inferred_from_actual_timestamp_association(self) -> None:
        camera = self.camera("A06")
        # Use only the even MT1 phase.  A06 score 2210..2460 therefore has 126
        # native expected outputs, unlike the frozen external odd phase's 125.
        sources = list(range(0, 2461, 2))
        association = analysis.associate_stamps_to_camera(
            [camera.stamp_for_source(value) for value in sources], camera
        )
        support = analysis.score_support("A06", "vanilla_origin", camera, association)
        self.assertEqual(support["phase"], "even")
        self.assertEqual(support["phase_source"], "OBSERVED_ORIGIN_MT1_TIMESTAMP_ASSOCIATION")
        self.assertEqual(support["phase_confidence"], 1.0)
        self.assertEqual(support["method_native_expected_count"], 126)
        self.assertEqual(support["method_native_covered_count"], 126)

    def test_origin_mixed_phase_is_ambiguous_not_silently_assigned(self) -> None:
        camera = self.camera("H07")
        sources = list(range(1600, 1640))
        association = analysis.associate_stamps_to_camera(
            [camera.stamp_for_source(value) for value in sources], camera
        )
        support = analysis.score_support("H07", "vanilla_origin", camera, association)
        self.assertEqual(support["phase_state"], "AMBIGUOUS")
        self.assertEqual(support["phase_confidence"], 0.5)

    def test_trajectory_requires_finite_strictly_increasing_rows(self) -> None:
        path = self.root / "bad.csv"
        self.write_vio(path, [20, 10])
        result = analysis.load_trajectory(path)
        self.assertEqual(result["state"], "INVALID")
        self.assertFalse(result["strictly_increasing"])
        self.write_vio(path, [10, 20], nonfinite=True)
        result = analysis.load_trajectory(path)
        self.assertEqual(result["state"], "INVALID")
        self.assertEqual(result["nonfinite_count"], 1)

    def test_camera_association_rejects_unmatched_and_counts_duplicate_sources(self) -> None:
        camera = self.camera("A06")
        stamp = camera.stamp_for_source(2211)
        result = analysis.associate_stamps_to_camera(
            [stamp, stamp + 1, stamp + 20_000_000], camera
        )
        self.assertEqual(result["matched_pose_count"], 2)
        self.assertEqual(result["unmatched_pose_count"], 1)
        self.assertEqual(result["duplicate_source_association_count"], 1)

    def write_frontend_metrics(self, path: Path, rows: list[dict[str, object]]) -> None:
        fields = [
            "frame_index",
            "timestamp",
            "published_feature_frame",
            "exported_features",
            "exported_learned_features",
            "exported_sp_lg_features",
            "exported_xfeat_features",
            "exported_loftr_features",
            "learned_candidate_count",
            "pre_gate_sidecar_total",
            "learned_export_gate_dropped",
        ]
        with path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            writer.writerows(rows)

    def test_frontend_h07_maps_local_frame_index_to_source_and_splits_action(self) -> None:
        camera = self.camera("H07")
        path = self.root / "frontend.csv"
        # H07 feed starts at source 1: local frame_index 1 is source 2.  This
        # catches the error of interpreting frame_index itself as source 1.
        self.write_frontend_metrics(
            path,
            [
                {
                    "frame_index": 1,
                    "timestamp": str(camera.stamp_for_source(2) / 1e9),
                    "published_feature_frame": 1,
                    "exported_features": 100,
                    "exported_learned_features": 3,
                    "exported_sp_lg_features": 3,
                    "exported_xfeat_features": 0,
                    "exported_loftr_features": 0,
                },
                {
                    "frame_index": 1659,
                    "timestamp": str(camera.stamp_for_source(1660) / 1e9),
                    "published_feature_frame": 1,
                    "exported_features": 100,
                    "exported_learned_features": 4,
                    "exported_sp_lg_features": 0,
                    "exported_xfeat_features": 0,
                    "exported_loftr_features": 4,
                },
            ],
        )
        result = analysis.audit_frontend_metrics(path, camera, "H07")
        self.assertEqual(result["state"], "VALID")
        self.assertEqual(result["mapping"]["first_source"], 2)
        self.assertEqual(result["segments"]["full"]["learned_observations"]["total"], 7)
        self.assertEqual(result["segments"]["preroll"]["learned_observations"]["sp_lg"], 3)
        self.assertEqual(result["segments"]["score"]["learned_observations"]["loftr"], 4)
        self.assertEqual(result["learned_action_class"], "LEARNED_ACTION_PREROLL_AND_SCORE")

    def test_frontend_candidate_activity_is_aggregated_as_diagnostic_not_samples(self) -> None:
        camera = self.camera("H07")
        path = self.root / "frontend_activity.csv"
        self.write_frontend_metrics(
            path,
            [
                {
                    "frame_index": 1,
                    "timestamp": str(camera.stamp_for_source(2) / 1e9),
                    "published_feature_frame": 1,
                    "exported_features": 100,
                    "exported_learned_features": 0,
                    "exported_sp_lg_features": 0,
                    "exported_xfeat_features": 0,
                    "exported_loftr_features": 0,
                    "learned_candidate_count": 7,
                    "pre_gate_sidecar_total": 11,
                    "learned_export_gate_dropped": 11,
                },
                {
                    "frame_index": 1659,
                    "timestamp": str(camera.stamp_for_source(1660) / 1e9),
                    "published_feature_frame": 1,
                    "exported_features": 100,
                    "exported_learned_features": 0,
                    "exported_sp_lg_features": 0,
                    "exported_xfeat_features": 0,
                    "exported_loftr_features": 0,
                    "learned_candidate_count": 5,
                    "pre_gate_sidecar_total": 13,
                    "learned_export_gate_dropped": 13,
                },
            ],
        )
        result = analysis.audit_frontend_metrics(path, camera, "H07")
        activity = result["segments"]["full"]["learned_pipeline_activity"]
        self.assertEqual(activity["learned_candidate_count_sum"], 12)
        self.assertEqual(activity["pre_gate_sidecar_total_sum"], 24)
        self.assertEqual(activity["learned_export_gate_dropped_sum"], 24)
        self.assertEqual(result["segments"]["full"]["learned_observations"]["total"], 0)
        self.assertIn("not independent samples", result["learned_pipeline_activity_interpretation"])

    def test_frontend_timestamp_frame_disagreement_fails_closed(self) -> None:
        camera = self.camera("A06")
        path = self.root / "frontend_bad.csv"
        self.write_frontend_metrics(
            path,
            [
                {
                    "frame_index": 3,
                    "timestamp": str(camera.stamp_for_source(5) / 1e9),
                    "published_feature_frame": 1,
                    "exported_features": 100,
                    "exported_learned_features": 0,
                    "exported_sp_lg_features": 0,
                    "exported_xfeat_features": 0,
                    "exported_loftr_features": 0,
                }
            ],
        )
        result = analysis.audit_frontend_metrics(path, camera, "A06")
        self.assertEqual(result["state"], "INVALID")
        self.assertTrue(any("DISAGREE" in code for code in result["errors"]))

    def test_zero_learned_identical_payload_and_different_vio_is_backend_nondeterminism(self) -> None:
        paths, rows = self.payload_comparison_fixture()
        result = analysis.frontend_payload_comparison(
            "H07", paths, rows, {"state": "NOT_APPLICABLE"}
        )
        self.assertTrue(result["payload_byte_identical"])
        self.assertEqual(result["action_class"], "NO_ACTION_BYTE_IDENTICAL_TO_KLT")
        self.assertTrue(result["backend_run_nondeterminism_observed"])
        self.assertTrue(result["trajectory_difference_not_attributable_to_frontend"])
        self.assertFalse(result["learning_improvement_claim_permitted"])
        self.assertEqual(
            result["learning_improvement_attribution"],
            "PROHIBITED_PAYLOAD_BYTE_IDENTICAL",
        )
        self.assertFalse(result["candidate_activity_is_independent_sample_evidence"])
        self.assertTrue(result["proposed_learned_pipeline_activity_observed"])
        self.assertEqual(
            result["proposed_learned_pipeline_activity_full"][
                "learned_candidate_count_sum"
            ],
            17,
        )

    def test_zero_learned_identical_payload_and_same_vio_has_no_nondeterminism_flag(self) -> None:
        paths, rows = self.payload_comparison_fixture(
            external_vio=b"same trajectory", proposed_vio=b"same trajectory"
        )
        result = analysis.frontend_payload_comparison(
            "H07", paths, rows, {"state": "NOT_APPLICABLE"}
        )
        self.assertEqual(result["action_class"], "NO_ACTION_BYTE_IDENTICAL_TO_KLT")
        self.assertFalse(result["trajectory_sha_different"])
        self.assertFalse(result["backend_run_nondeterminism_observed"])
        self.assertFalse(result["trajectory_difference_not_attributable_to_frontend"])

    def test_zero_learned_different_payload_does_not_claim_byte_equivalence(self) -> None:
        paths, rows = self.payload_comparison_fixture(proposed_bag=b"different payload")
        result = analysis.frontend_payload_comparison(
            "H07", paths, rows, {"state": "NOT_APPLICABLE"}
        )
        self.assertFalse(result["payload_byte_identical"])
        self.assertEqual(result["action_class"], "NO_LEARNED_ACTION_PAYLOAD_BYTES_DIFFER")
        self.assertFalse(result["backend_run_nondeterminism_observed"])
        self.assertIsNone(result["learning_improvement_claim_permitted"])

    def test_identical_payload_with_nonzero_learned_count_fails_closed_as_contradiction(self) -> None:
        paths, rows = self.payload_comparison_fixture(learned_total=3)
        result = analysis.frontend_payload_comparison(
            "H07", paths, rows, {"state": "NOT_APPLICABLE"}
        )
        self.assertEqual(
            result["action_class"],
            "CONTRADICTORY_LEARNED_COUNT_WITH_BYTE_IDENTICAL_PAYLOAD",
        )
        self.assertFalse(result["learning_improvement_claim_permitted"])

    def test_report_states_no_action_and_forbids_frontend_attribution(self) -> None:
        paths, rows = self.payload_comparison_fixture()
        comparison = analysis.frontend_payload_comparison(
            "H07", paths, rows, {"state": "NOT_APPLICABLE"}
        )
        report = self.root / "report.md"
        analysis.write_report(
            report,
            {
                "analysis_state": "TERMINAL_DESCRIPTIVE_FORMAL_ACCURACY_BLOCKED",
                "rows": [],
                "frontend_payload_comparisons": {
                    "A06": comparison,
                    "H07": comparison,
                },
                "a06_external_klt_corrective_replay": {
                    "state": "NOT_APPLICABLE",
                    "adopted": False,
                    "original_incident": {},
                },
                "accuracy": {
                    "A06": {"state": "BLOCKED_FORMAL", "block_codes": ["REFERENCE_NATIVE_ROWS_LT_30"]},
                    "H07": {"state": "BLOCKED_FORMAL", "block_codes": ["REFERENCE_NATIVE_ROWS_LT_30"]},
                },
                "cross_system_disclosures": [],
            },
        )
        text = report.read_text(encoding="utf-8")
        self.assertIn("NO_ACTION_BYTE_IDENTICAL_TO_KLT", text)
        self.assertIn("backend_run_nondeterminism_observed: `True`", text)
        self.assertIn("cannot be credited to the learned frontend", text)
        self.assertIn("not independent samples", text)

    def test_a06_corrective_payload_audit_uses_bound_original_source_bag(self) -> None:
        vanilla = self.root / "runs/a06/vanilla_origin"
        original = self.root / "runs/a06/external_klt"
        corrective = self.root / "runs/a06/external_klt_corrective_replay"
        proposed = self.root / "runs/a06/aquafe_proposed_safe"
        for run in (vanilla, original, corrective, proposed):
            (run / "vins_output").mkdir(parents=True, exist_ok=True)
        (original / "features.bag").write_bytes(b"bound source payload")
        (proposed / "features.bag").write_bytes(b"bound source payload")
        (corrective / "vins_output/vio.csv").write_bytes(b"corrective VIO")
        (proposed / "vins_output/vio.csv").write_bytes(b"proposed VIO")
        paths = {
            "a06_vanilla_origin": analysis.ArmPaths(
                "a06_vanilla_origin", "A06", "vanilla_origin", vanilla,
                vanilla / analysis.RECEIPT_NAME, vanilla / "vins_output/vio.csv",
                vanilla / "vins.log", None, vanilla / "config.yaml",
            ),
            "a06_external_klt": analysis.ArmPaths(
                "a06_external_klt_corrective_replay", "A06", "external_klt", corrective,
                corrective / analysis.RECEIPT_NAME, corrective / "vins_output/vio.csv",
                corrective / "vins.log", corrective / "frontend_metrics.csv",
                corrective / "config.yaml",
            ),
            "a06_aquafe_proposed_safe": analysis.ArmPaths(
                "a06_aquafe_proposed_safe", "A06", "aquafe_proposed_safe", proposed,
                proposed / analysis.RECEIPT_NAME, proposed / "vins_output/vio.csv",
                proposed / "vins.log", proposed / "frontend_metrics.csv",
                proposed / "config.yaml",
            ),
        }
        rows = [
            {"sequence": "A06", "method": "external_klt", "usability": {"status": "PASS"}},
            {
                "sequence": "A06",
                "method": "aquafe_proposed_safe",
                "usability": {"status": "PASS"},
                "frontend": {"segments": {"full": {"learned_observations": {"total": 0}}}},
            },
        ]
        result = analysis.frontend_payload_comparison(
            "A06",
            paths,
            rows,
            {
                "state": "ADOPTED_EXACT_BACKEND_ONLY_CORRECTIVE_REPLAY",
                "source_feature_bag": analysis.identity(original / "features.bag"),
            },
        )
        self.assertEqual(
            result["feature_bags"]["external_klt"]["path"],
            str(original / "features.bag"),
        )
        self.assertTrue(result["payload_byte_identical"])
        self.assertEqual(result["action_class"], "NO_ACTION_BYTE_IDENTICAL_TO_KLT")

    def test_receipt_missing_is_pending_and_terminal_contract_is_parsed(self) -> None:
        path = self.root / analysis.RECEIPT_NAME
        pending = analysis.audit_receipt(path)
        self.assertEqual(pending["state"], "PENDING_MISSING_RECEIPT")
        path.write_text(
            json.dumps(
                {
                    "raw_return_code": 0,
                    "one_launch": True,
                    "zero_retry": True,
                    "wall_time_seconds": 12.5,
                }
            ),
            encoding="utf-8",
        )
        terminal = analysis.audit_receipt(path)
        self.assertEqual(terminal["state"], "TERMINAL")
        self.assertTrue(terminal["policy_compliant"])
        self.assertEqual(terminal["launch_count"], 1)
        self.assertEqual(terminal["retry_count"], 0)
        self.assertEqual(terminal["wall_time_s"], 12.5)

    def test_receipt_does_not_infer_missing_launch_or_retry_fields(self) -> None:
        path = self.root / analysis.RECEIPT_NAME
        path.write_text(json.dumps({"raw_return_code": 0}), encoding="utf-8")
        result = analysis.audit_receipt(path)
        self.assertEqual(result["state"], "TERMINAL_RECEIPT_INCOMPLETE_OR_NONCOMPLIANT")
        self.assertFalse(result["policy_compliant"])

    def make_corrective_fixture(self, name: str) -> dict[str, object]:
        artifact_root = self.root / name
        original_run = artifact_root / "runs/a06/external_klt"
        corrective_run = artifact_root / "runs/a06/external_klt_corrective_replay"
        (original_run / "vins_output").mkdir(parents=True)
        (corrective_run / "vins_output").mkdir(parents=True)
        source_feature = original_run / "features.bag"
        source_metrics = original_run / "frontend_metrics.csv"
        source_config = original_run / "vins_aqualoc_archaeo_external.yaml"
        camera_config = original_run / "aqualoc_archaeo06_pinhole.yaml"
        source_feature.write_bytes(b"frozen feature payload")
        source_metrics.write_text("frame_index,timestamp\n", encoding="utf-8")
        source_config.write_text(
            'multiple_thread: 1\noutput_path: "/old/output"\n', encoding="utf-8"
        )
        camera_config.write_text("camera\n", encoding="utf-8")
        original_vio = original_run / "vins_output/vio.csv"
        original_log = original_run / "vins.log"
        self.write_vio(original_vio, [1_500_000_000_000_000_000])
        original_log.write_text("partial\n", encoding="utf-8")
        expected_lock = "a" * 64
        original_receipt = original_run / analysis.RECEIPT_NAME
        original_value = {
            "schema_version": "aqua-fe-samehistory-formal-run-receipt-v1",
            "arm_id": "a06_external_klt",
            "status": "INFRASTRUCTURE_CENSORED_SUPERVISOR_TIMEOUT_DURING_REPLAY",
            "process_start_count": 1,
            "retry_count": 0,
            "raw_return_code": 124,
            "failure_stage": {
                "offline_feature_export_completed": True,
                "vins_replay_started": True,
                "vins_replay_completed": False,
                "legacy_evaluator_started": False,
                "score_window_reached": False,
                "algorithmic_usability_adjudicated": False,
            },
            "identities": {
                "execution_lock_sha256": expected_lock,
                "features_bag": analysis.identity(source_feature),
                "frontend_metrics": analysis.identity(source_metrics),
                "partial_vio_csv": analysis.identity(original_vio),
                "partial_vins_log": analysis.identity(original_log),
            },
            "interpretation": {
                "algorithm_failure": False,
                "formal_usability_result_available": False,
                "partial_trajectory_eligible_for_score_or_accuracy": False,
                "same_namespace_may_be_reused": False,
            },
        }
        original_receipt.write_text(json.dumps(original_value), encoding="utf-8")

        protocol = self.root / f"{name}_protocol.md"
        protocol.write_text("frozen corrective protocol\n", encoding="utf-8")
        runner = self.root / f"{name}_runner.sh"
        runner.write_text("runner\n", encoding="utf-8")
        vins_node = self.root / f"{name}_vins_node"
        vins_node.write_text("vins\n", encoding="utf-8")

        corrective_metrics = corrective_run / "frontend_metrics.csv"
        corrective_config = corrective_run / "vins_aqualoc_archaeo_external.yaml"
        corrective_log = corrective_run / "vins.log"
        corrective_vio = corrective_run / "vins_output/vio.csv"
        corrective_ape = corrective_run / "ape.txt"
        corrective_metrics.write_bytes(source_metrics.read_bytes())
        corrective_config.write_text(
            'multiple_thread: 1\noutput_path: "/new/output"\n', encoding="utf-8"
        )
        corrective_log.write_text("complete\n", encoding="utf-8")
        self.write_vio(corrective_vio, [1_500_000_000_000_000_000])
        corrective_ape.write_text("diagnostic\n", encoding="utf-8")
        replay_manifest = corrective_run / "replay_manifest.txt"
        replay_manifest.write_text(
            f"play_bag={source_feature}\nfeature_bag={source_feature}\n",
            encoding="utf-8",
        )
        corrective_receipt = corrective_run / analysis.RECEIPT_NAME
        corrective_value = {
            "schema_version": "aqua-fe-samehistory-formal-run-receipt-v1",
            "arm_id": "a06_external_klt_corrective_replay",
            "status": "TERMINAL_PROCESS_RC0_ADDITIVE_INFRASTRUCTURE_CORRECTIVE",
            "process_start_count": 1,
            "retry_count": 0,
            "raw_return_code": 0,
            "corrective_contract": {
                "protocol_path": str(protocol),
                "protocol_sha256": analysis.sha256(protocol),
                "original_terminal_receipt_path": str(original_receipt),
                "original_terminal_receipt_sha256": analysis.sha256(original_receipt),
                "original_namespace_modified": False,
                "front_end_recomputed": False,
                "result_informed_change": False,
            },
            "identities": {
                "replay_runner_sha256": analysis.sha256(runner),
                "vins_node_sha256": analysis.sha256(vins_node),
                "source_features_bag": analysis.identity(source_feature),
                "source_frontend_metrics_sha256": analysis.sha256(source_metrics),
                "vio_csv": analysis.identity(corrective_vio),
                "vins_log": analysis.identity(corrective_log),
                "legacy_ape_diagnostic": analysis.identity(corrective_ape),
                "replay_manifest_sha256": analysis.sha256(replay_manifest),
                "runtime_vins_config_sha256": analysis.sha256(corrective_config),
            },
        }
        corrective_receipt.write_text(json.dumps(corrective_value), encoding="utf-8")
        original_paths = analysis.ArmPaths(
            "a06_external_klt", "A06", "external_klt", original_run,
            original_receipt, original_vio, original_log, source_metrics, source_config,
        )
        frozen = {
            "feature_bag": {
                "relative_path": "runs/a06/external_klt/features.bag",
                "size_bytes": source_feature.stat().st_size,
                "sha256": analysis.sha256(source_feature),
            },
            "frontend_metrics": {
                "relative_path": "runs/a06/external_klt/frontend_metrics.csv",
                "sha256": analysis.sha256(source_metrics),
            },
            "vins_config": {
                "relative_path": "runs/a06/external_klt/vins_aqualoc_archaeo_external.yaml",
                "sha256": analysis.sha256(source_config),
            },
            "camera_config": {
                "relative_path": "runs/a06/external_klt/aqualoc_archaeo06_pinhole.yaml",
                "sha256": analysis.sha256(camera_config),
            },
        }
        return {
            "artifact_root": artifact_root,
            "lock": {"policy": {"large_artifact_root": str(artifact_root)}},
            "paths": {"a06_external_klt": original_paths},
            "expected_lock": expected_lock,
            "protocol": protocol,
            "runner": runner,
            "vins_node": vins_node,
            "frozen": frozen,
            "source_feature": source_feature,
            "corrective_receipt": corrective_receipt,
        }

    def corrective_patches(self, fixture: dict[str, object]) -> list[mock._patch]:
        return [
            mock.patch.object(analysis, "DEFAULT_A06_KLT_CORRECTIVE_PROTOCOL", fixture["protocol"]),
            mock.patch.object(
                analysis,
                "A06_KLT_CORRECTIVE_PROTOCOL_SHA256",
                analysis.sha256(fixture["protocol"]),
            ),
            mock.patch.object(analysis, "A06_KLT_FROZEN_SOURCE", fixture["frozen"]),
            mock.patch.object(analysis, "A06_KLT_CORRECTIVE_RUNNER", fixture["runner"]),
            mock.patch.object(
                analysis,
                "A06_KLT_CORRECTIVE_RUNNER_SHA256",
                analysis.sha256(fixture["runner"]),
            ),
            mock.patch.object(analysis, "A06_KLT_VINS_NODE", fixture["vins_node"]),
            mock.patch.object(
                analysis,
                "A06_KLT_VINS_NODE_SHA256",
                analysis.sha256(fixture["vins_node"]),
            ),
        ]

    def test_corrective_replay_adoption_requires_exact_frozen_feature_payload(self) -> None:
        fixture = self.make_corrective_fixture("adopt")
        patches = self.corrective_patches(fixture)
        for patcher in patches:
            patcher.start()
            self.addCleanup(patcher.stop)
        record, selected = analysis.resolve_a06_klt_corrective_adoption(
            fixture["lock"], fixture["paths"], fixture["expected_lock"]
        )
        self.assertEqual(record["state"], "ADOPTED_EXACT_BACKEND_ONLY_CORRECTIVE_REPLAY")
        self.assertTrue(record["adopted"])
        self.assertEqual(selected.lock_id, "a06_external_klt_corrective_replay")
        self.assertFalse(record["original_partial_trajectory_scored"])
        fixture["source_feature"].write_bytes(b"mutated feature payload")
        rejected, selected_after_mutation = analysis.resolve_a06_klt_corrective_adoption(
            fixture["lock"], fixture["paths"], fixture["expected_lock"]
        )
        self.assertFalse(rejected["adopted"])
        self.assertEqual(rejected["state"], "REJECTED_FROZEN_EVIDENCE_INVALID")
        self.assertEqual(selected_after_mutation.lock_id, "a06_external_klt")

    def test_censored_original_is_pending_when_corrective_receipt_absent(self) -> None:
        fixture = self.make_corrective_fixture("pending")
        fixture["corrective_receipt"].unlink()
        patches = self.corrective_patches(fixture)
        for patcher in patches:
            patcher.start()
            self.addCleanup(patcher.stop)
        record, selected = analysis.resolve_a06_klt_corrective_adoption(
            fixture["lock"], fixture["paths"], fixture["expected_lock"]
        )
        self.assertEqual(record["state"], "PENDING_CORRECTIVE_REPLAY")
        self.assertFalse(record["adopted"])
        self.assertEqual(selected.lock_id, "a06_external_klt")

    def test_public_a06_klt_corrective_receipt_adopts_and_has_125_score_grid(self) -> None:
        receipt = Path(
            "/mnt/data/AQUA-FE_WS/experiments/samehistory_system_v1/runs/a06/"
            "external_klt_corrective_replay/formal_run_receipt_v1.json"
        )
        if not receipt.is_file():
            self.skipTest("sealed A06 corrective replay is unavailable")
        lock = analysis.verify_protocol_lock(analysis.DEFAULT_LOCK, analysis.DEFAULT_PROTOCOL)
        paths = analysis.resolve_arm_paths(lock)
        record, selected = analysis.resolve_a06_klt_corrective_adoption(
            lock, paths, analysis.sha256(analysis.DEFAULT_LOCK)
        )
        self.assertEqual(record["state"], "ADOPTED_EXACT_BACKEND_ONLY_CORRECTIVE_REPLAY")
        window = analysis.WINDOWS["A06"]
        camera = analysis.load_camera_grid(
            Path(window["camera_csv"]), "A06", *window["feed"]
        )
        row = analysis.audit_vins_arm(selected, camera, expected_lock_sha256=None)
        self.assertEqual(row["usability"]["status"], "PASS")
        self.assertEqual(row["score_support"]["method_native_covered_count"], 125)
        self.assertEqual(row["score_support"]["method_native_expected_count"], 125)
        self.assertEqual(
            row["frontend"]["segments"]["full"]["learned_observations"]["total"], 0
        )

    def synthetic_common_support(self, *, ape_valid: bool = False) -> dict[str, object]:
        arms = {}
        for name in analysis.COMMON_ARM_NAMES.values():
            arms[name] = {
                "matched_count": 12,
                "ape_rmse_m": 0.1,
                "ape_median_m": 0.09,
                "ape_max_m": 0.2,
                "rpe_pairs": 11,
                "rpe_rmse_m": 0.03,
                "rpe_median_m": 0.02,
                "rpe_max_m": 0.05,
            }
        return {
            "support": {
                "ape_valid": ape_valid,
                "rpe_valid": True,
                "matched_count": 12,
                "common_span_s": 12.0,
                "rpe_pairs": 11,
            },
            "arms": arms,
        }

    def test_formal_accuracy_remains_blocked_with_descriptive_numbers(self) -> None:
        rows = [{"usability": {"status": "PASS"}} for _ in range(4)]
        result = analysis.formal_accuracy_gate(
            "A06", self.synthetic_common_support(), rows
        )
        self.assertEqual(result["state"], "BLOCKED_FORMAL")
        self.assertIn("REFERENCE_NATIVE_ROWS_LT_30", result["block_codes"])
        self.assertFalse(result["formal_winner_permitted"])
        self.assertEqual(
            result["descriptive_proxy_metrics"]["label"],
            "DESCRIPTIVE_SAME_IMAGE_COLMAP_PROXY_ONLY_NO_RANKING",
        )

    def test_contradictory_open_ape_gate_is_rejected(self) -> None:
        rows = [{"usability": {"status": "PASS"}} for _ in range(4)]
        with self.assertRaisesRegex(analysis.EvidenceError, "FORMAL_APE_GATE_OPEN"):
            analysis.formal_accuracy_gate(
                "A06", self.synthetic_common_support(ape_valid=True), rows
            )

    def test_evaluator_command_contains_all_four_arms_and_frozen_gates(self) -> None:
        camera = self.camera("A06")
        paths = {}
        for method in analysis.ARM_ORDER:
            run = self.root / method
            paths[f"a06_{method}"] = analysis.ArmPaths(
                f"a06_{method}",
                "A06",
                method,
                run,
                run / analysis.RECEIPT_NAME,
                run / "vins_output/vio.csv",
                run / "vins.log",
                None if method == "vanilla_origin" else run / "frontend_metrics.csv",
                run / "config.yaml",
            )
        command = analysis.build_evaluator_command(
            "A06", paths, camera, self.root / "raw.bag", self.root / "out"
        )
        joined = " ".join(command)
        for name in analysis.COMMON_ARM_NAMES.values():
            self.assertIn(name + "=", joined)
        self.assertIn("--min-ape-poses 30", joined)
        self.assertIn("--min-ape-span-s 10.0", joined)
        self.assertNotIn("--run-evo", command)

    def test_existing_common_support_is_read_only_when_input_manifest_matches(self) -> None:
        camera = self.camera("A06")
        paths = {}
        for method in analysis.ARM_ORDER:
            run = self.root / method
            trajectory = run / "vins_output/vio.csv"
            config = run / "config.yaml"
            self.write_vio(trajectory, [camera.stamp_for_source(2211)])
            config.parent.mkdir(parents=True, exist_ok=True)
            config.write_text("config\n", encoding="utf-8")
            paths[f"a06_{method}"] = analysis.ArmPaths(
                f"a06_{method}", "A06", method, run,
                run / analysis.RECEIPT_NAME, trajectory, run / "vins.log",
                None if method == "vanilla_origin" else run / "frontend_metrics.csv",
                config,
            )
        raw = self.root / "raw.bag"
        raw.write_bytes(b"raw")
        bridge = self.root / "hfnet.csv"
        bridge.write_bytes(b"bridge")
        common_root = self.root / "common"
        final = common_root / "a06"
        final.mkdir(parents=True)
        summary = {"support": {}, "arms": {}}
        (final / "common_support_summary.json").write_text(
            json.dumps(summary), encoding="utf-8"
        )
        with mock.patch.dict(
            analysis.WINDOWS["A06"], {"hfnet_bridge": bridge}, clear=False
        ):
            manifest = analysis.evaluator_input_manifest("A06", paths, raw)
            (final / "samehistory_evaluator_input_manifest_v1.json").write_text(
                json.dumps(manifest), encoding="utf-8"
            )
            loaded, audit = analysis.ensure_common_support(
                "A06", paths, camera, raw, common_root, run_evaluator=False
            )
            self.assertEqual(loaded, summary)
            self.assertEqual(audit["state"], "READ_EXISTING_COMMON_SUPPORT")
            paths["a06_external_klt"].trajectory.write_text(
                "1,0,0,0,1,0,0,0\n", encoding="ascii"
            )
            with self.assertRaisesRegex(analysis.EvidenceError, "STALE_COMMON_SUPPORT"):
                analysis.ensure_common_support(
                    "A06", paths, camera, raw, common_root, run_evaluator=False
                )

    def test_vins_arm_with_missing_receipt_stays_pending_despite_partial_vio(self) -> None:
        camera = self.camera("A06")
        run = self.root / "run"
        self.write_vio(
            run / "vins_output/vio.csv",
            [camera.stamp_for_source(2211)],
        )
        paths = analysis.ArmPaths(
            "a06_external_klt",
            "A06",
            "external_klt",
            run,
            run / analysis.RECEIPT_NAME,
            run / "vins_output/vio.csv",
            run / "vins.log",
            run / "frontend_metrics.csv",
            run / "config.yaml",
        )
        result = analysis.audit_vins_arm(paths, camera)
        self.assertEqual(result["analysis_state"], "PENDING")
        self.assertEqual(result["usability"]["status"], "PENDING")

    def test_hfnet_bundle_integration_selects_only_frozen_a06_h07(self) -> None:
        rows = []
        for sequence in analysis.WINDOW_ORDER:
            rows.append(
                {
                    "window_id": analysis.WINDOWS[sequence]["hfnet_window_id"],
                    "method_id": "HFNET_SLAM",
                    "usability": {"status": "PASS"},
                }
            )
        path = self.root / "hfnet.json"
        path.write_text(
            json.dumps(
                {
                    "schema_version": "aqua-fe-hfnet-multiwindow-analysis-bundle-v2",
                    "analysis_state": "TERMINAL_DESCRIPTIVE_ONLY",
                    "rows": rows,
                }
            ),
            encoding="utf-8",
        )
        selected, _ = analysis.load_hfnet_rows(path)
        self.assertEqual(set(selected), {"A06", "H07"})


if __name__ == "__main__":
    unittest.main()
