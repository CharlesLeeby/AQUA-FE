import json
import contextlib
import io
import math
import os
from pathlib import Path
import signal
import stat
import tempfile
import unittest
from unittest import mock

import numpy as np

from scripts import evaluate_published_supervins_v1_official_euroc_mh01_full_trajectory_gt_v1 as evaluator


def synthetic_associations(count=20):
    return [
        {
            "estimate_row_index": index,
            "camera_row_index": evaluator.CAMERA_FIRST_INDEX + evaluator.CAMERA_INDEX_STEP * index,
            "source_camera_timestamp_ns": 1_000_000_000_000 + 100_000_000 * index,
        }
        for index in range(count)
    ]


class TimestampContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.trajectory = evaluator.audit_trajectory_structure(include_values=False)
        cls.camera = evaluator.audit_camera_structure()
        cls.gt = evaluator.audit_gt_structure(include_values=False)
        cls.association = evaluator.associate_via_official_camera(
            cls.trajectory["rows"], cls.camera["rows"], cls.gt["rows"]
        )

    def test_actual_frozen_counts_without_metric_computation(self):
        self.assertEqual(self.trajectory["row_count"], 1810)
        self.assertEqual(self.camera["row_count"], 3682)
        self.assertEqual(self.gt["row_count"], 36382)
        self.assertEqual(self.association["matched_count"], 1799)
        self.assertEqual(self.association["excluded_count"], 11)
        self.assertEqual(self.association["unique_camera_row_count"], 1810)
        self.assertEqual(self.association["unique_gt_row_count"], 1799)
        self.assertEqual(self.association["errors"], [])

    def test_all_fixed6_rows_lose_source_submicrosecond_value(self):
        self.assertEqual(
            self.association["signed_text_minus_source_ns_histogram"],
            {"-456": 1086, "544": 724},
        )
        self.assertEqual(self.association["max_abs_text_to_camera_ns"], 544)
        self.assertNotIn("0", self.association["signed_text_minus_source_ns_histogram"])

    def test_frozen_camera_suffix_and_exact_gt_join(self):
        all_rows = self.association["matched"] + self.association["excluded"]
        self.assertEqual(all_rows[0]["camera_row_index"], 63)
        self.assertEqual(all_rows[-1]["camera_row_index"], 3681)
        self.assertTrue(
            all(row["camera_row_index"] == 63 + 2 * row["estimate_row_index"] for row in all_rows)
        )
        self.assertTrue(
            all(row["source_camera_timestamp_ns"] == self.gt["rows"][row["gt_row_index"]]["timestamp_ns"] for row in self.association["matched"])
        )
        self.assertEqual(self.association["matched"][-1]["estimate_row_index"], 1798)
        self.assertEqual(self.association["excluded"][0]["estimate_row_index"], 1799)
        self.assertTrue(all(row["reason"] == "EXCLUDED_OUTSIDE_GT_COVERAGE" for row in self.association["excluded"]))

    def test_initialization_and_generation_coverage_is_mechanical(self):
        audit = evaluator.generation_support_audit(self.camera["rows"], self.association)
        self.assertTrue(audit["ok"])
        self.assertEqual(audit["expected_estimator_output_rows"], 1841)
        self.assertEqual(audit["generated_trajectory_rows"], 1810)
        self.assertEqual(audit["missing_initialization_prefix_rows"], 31)
        self.assertEqual(audit["missing_interior_rows"], 0)
        self.assertEqual(audit["missing_terminal_rows"], 0)
        self.assertTrue(audit["generated_camera_rows_are_exact_contiguous_suffix"])
        self.assertEqual(audit["first_generated_output_delay_from_sequence_cam0_ns"], 3_149_999_872)
        self.assertEqual(audit["first_generated_output_delay_from_first_expected_output_ns"], 3_100_000_000)
        self.assertEqual(audit["generation_coverage"]["decimal_17g"], "0.98316132536664858")
        self.assertEqual(audit["gt_evaluable_generated"]["decimal_17g"], "0.99392265193370166")
        self.assertEqual(audit["gt_evaluable_expected"]["decimal_17g"], "0.97718631178707227")
        self.assertTrue(audit["excluded_tail_is_gt_coverage_not_generation_failure"])

    def test_generation_support_rejects_non_suffix_gap(self):
        broken = dict(self.association)
        broken["matched"] = [dict(row) for row in self.association["matched"]]
        broken["excluded"] = [dict(row) for row in self.association["excluded"]]
        broken["matched"][100]["camera_row_index"] += 2
        audit = evaluator.generation_support_audit(self.camera["rows"], broken)
        self.assertFalse(audit["ok"])
        self.assertFalse(audit["generated_camera_rows_are_exact_contiguous_suffix"])

    def test_exact_one_second_rpe_support(self):
        audit = evaluator.build_rpe_pairs(self.association["matched"])
        self.assertEqual(audit["pair_count"], 1789)
        self.assertEqual(audit["rejected"], [])
        self.assertEqual(audit["actual_delta_min_ns"], 1_000_000_000)
        self.assertEqual(audit["actual_delta_max_ns"], 1_000_000_000)
        self.assertTrue(all(row["right_estimate_row_index"] - row["left_estimate_row_index"] == 10 for row in audit["pairs"]))
        self.assertTrue(all(row["right_camera_row_index"] - row["left_camera_row_index"] == 20 for row in audit["pairs"]))

    def test_rpe_off_by_one_boundary(self):
        self.assertEqual(evaluator.build_rpe_pairs(synthetic_associations(10))["pair_count"], 0)
        self.assertEqual(evaluator.build_rpe_pairs(synthetic_associations(11))["pair_count"], 1)

    def test_rpe_rejects_source_index_gap(self):
        rows = synthetic_associations(20)
        rows[7]["estimate_row_index"] += 1
        audit = evaluator.build_rpe_pairs(rows)
        self.assertGreater(len(audit["rejected"]), 0)
        self.assertLess(audit["pair_count"], 10)

    def test_rpe_rejects_unmatched_interruption(self):
        rows = synthetic_associations(20)
        del rows[5]
        audit = evaluator.build_rpe_pairs(rows)
        self.assertGreater(len(audit["rejected"]), 0)

    def test_rpe_rejects_delta_over_tolerance(self):
        rows = synthetic_associations(11)
        rows[10]["source_camera_timestamp_ns"] += evaluator.RPE_DELTA_TOLERANCE_NS + 1
        audit = evaluator.build_rpe_pairs(rows)
        self.assertEqual(audit["pair_count"], 0)
        self.assertEqual(len(audit["rejected"]), 1)

    def test_decimal_parser_is_display_only(self):
        self.assertEqual(
            evaluator.decimal_seconds_to_display_ns("1403636582.913555"),
            1403636582913555000,
        )
        with self.assertRaises(ValueError):
            evaluator.decimal_seconds_to_display_ns("1403636582.9135555")


class FrameAndParsingTests(unittest.TestCase):
    def test_gt_wxyz_is_converted_to_xyzw(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "gt.csv"
            path.write_text(
                "#timestamp,p...\n1000000000,1,2,3,0.5,0.1,0.2,0.8366600265340756,0,0,0,0,0,0,0,0,0\n",
                encoding="utf-8",
            )
            # Normalize the synthetic quaternion before checking its ordering.
            norm = math.sqrt(0.5**2 + 0.1**2 + 0.2**2 + 0.8366600265340756**2)
            with mock.patch.object(evaluator, "GT_CSV", path):
                rows = evaluator.audit_gt_structure(include_values=True)["rows"]
            expected = np.asarray([0.1, 0.2, 0.8366600265340756, 0.5]) / norm
            observed = np.asarray(rows[0]["quaternion_xyzw"]) / np.linalg.norm(rows[0]["quaternion_xyzw"])
            np.testing.assert_allclose(observed, expected, atol=1e-15)

    def test_associated_positions_are_body_to_body_without_camera_extrinsic(self):
        trajectory = [{"position": [1.0, 2.0, 3.0]}]
        gt = [{"position": [4.0, 5.0, 6.0]}]
        associations = [{"estimate_row_index": 0, "gt_row_index": 0}]
        estimate_positions, gt_positions = evaluator.extract_associated_positions(
            trajectory, gt, associations
        )
        np.testing.assert_array_equal(estimate_positions, [[1.0, 2.0, 3.0]])
        np.testing.assert_array_equal(gt_positions, [[4.0, 5.0, 6.0]])

    def test_both_official_body_transforms_are_identity(self):
        identity = np.eye(4)
        np.testing.assert_array_equal(evaluator.parse_t_bs(evaluator.GT_SENSOR), identity)
        np.testing.assert_array_equal(evaluator.parse_t_bs(evaluator.IMU_SENSOR), identity)


class AlignmentTests(unittest.TestCase):
    def setUp(self):
        self.source = np.asarray(
            [[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [0.0, 2.0, 0.0], [0.0, 0.0, 3.0], [1.0, 2.0, 3.0]],
            dtype=float,
        )
        angle = 0.4
        self.rotation = np.asarray(
            [[math.cos(angle), -math.sin(angle), 0.0], [math.sin(angle), math.cos(angle), 0.0], [0.0, 0.0, 1.0]],
            dtype=float,
        )
        self.translation = np.asarray([3.0, -2.0, 0.7])

    def test_fixed_scale_se3_recovers_proper_transform(self):
        target = (self.rotation @ self.source.T).T + self.translation
        alignment = evaluator.rigid_se3_alignment(self.source, target)
        self.assertEqual(alignment["scale"], 1.0)
        self.assertTrue(evaluator.alignment_audit(alignment)["proper"])
        np.testing.assert_allclose(alignment["aligned"], target, atol=1e-12)

    def test_se3_matches_frozen_reference_core(self):
        target = (self.rotation @ self.source.T).T + self.translation
        ours = evaluator.rigid_se3_alignment(self.source, target)["aligned"]
        reference = evaluator.core_align_se3_positions(self.source, target)
        np.testing.assert_allclose(ours, reference, atol=1e-12)

    def test_sim3_recovers_positive_scale_but_remains_secondary(self):
        target = 2.5 * (self.rotation @ self.source.T).T + self.translation
        alignment = evaluator.proper_umeyama_sim3(self.source, target)
        audit = evaluator.alignment_audit(alignment)
        self.assertTrue(audit["proper"])
        self.assertAlmostEqual(alignment["scale"], 2.5, places=12)
        np.testing.assert_allclose(alignment["aligned"], target, atol=1e-12)

    def test_fixed_scale_se3_does_not_silently_correct_scale(self):
        target = 2.0 * self.source + self.translation
        alignment = evaluator.rigid_se3_alignment(self.source, target)
        self.assertEqual(alignment["scale"], 1.0)
        self.assertGreater(float(np.max(np.linalg.norm(alignment["aligned"] - target, axis=1))), 0.1)

    def test_reflection_is_not_accepted_as_proper(self):
        reflected = {
            "rotation": np.diag([-1.0, 1.0, 1.0]),
            "translation": np.zeros(3),
            "scale": 1.0,
            "rank_audit": {"source_rank": 3, "target_rank": 3, "covariance_rank": 3},
        }
        self.assertFalse(evaluator.alignment_audit(reflected)["proper"])

    def test_degenerate_sim3_source_is_rejected(self):
        with self.assertRaises(ValueError):
            evaluator.proper_umeyama_sim3(np.ones((4, 3)), np.ones((4, 3)))

    def test_rank_one_correspondences_are_rejected_by_both_alignments(self):
        source = np.asarray([[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [2.0, 0.0, 0.0], [3.0, 0.0, 0.0]])
        target = source + np.asarray([1.0, 2.0, 3.0])
        with self.assertRaises(ValueError):
            evaluator.rigid_se3_alignment(source, target)
        with self.assertRaises(ValueError):
            evaluator.proper_umeyama_sim3(source, target)

    def test_reflected_correspondence_yields_only_proper_best_fit(self):
        target = self.source.copy()
        target[:, 0] *= -1.0
        alignment = evaluator.proper_umeyama_sim3(self.source, target)
        self.assertGreater(float(np.linalg.det(alignment["rotation"])), 0.0)
        self.assertGreater(float(np.max(np.linalg.norm(alignment["aligned"] - target, axis=1))), 1e-6)


class StatisticsAndBundlePrimitiveTests(unittest.TestCase):
    def test_descriptive_stats_are_complete_and_noninferential(self):
        values = evaluator.descriptive_stats(np.asarray([0.0, 1.0, 2.0, 3.0]))
        self.assertEqual(
            set(values),
            {"n", "rmse_m", "mean_m", "population_std_m", "median_m", "min_m", "p90_m", "p95_m", "max_m", "sse_m2"},
        )
        self.assertNotIn("p_value", values)
        self.assertNotIn("confidence_interval", values)

    def test_descriptive_stats_reject_nonfinite_or_negative(self):
        with self.assertRaises(ValueError):
            evaluator.descriptive_stats(np.asarray([1.0, float("nan")]))
        with self.assertRaises(ValueError):
            evaluator.descriptive_stats(np.asarray([1.0, -0.1]))

    def test_canonical_json_rejects_nan(self):
        with self.assertRaises(ValueError):
            evaluator.canonical_json_bytes({"bad": float("nan")})

    def test_artifact_tree_digest_is_deterministic_and_path_bound(self):
        left = {"b": {"sha256": "2", "size_bytes": 2}, "a": {"sha256": "1", "size_bytes": 1}}
        right = {"a": {"sha256": "1", "size_bytes": 1}, "b": {"sha256": "2", "size_bytes": 2}}
        self.assertEqual(evaluator.artifact_tree_digest(left), evaluator.artifact_tree_digest(right))
        changed = {"c": right["a"], "b": right["b"]}
        self.assertNotEqual(evaluator.artifact_tree_digest(left), evaluator.artifact_tree_digest(changed))

    def test_exclusive_durable_writer_burns_path_and_sets_mode(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "evidence.json"
            identity = evaluator.write_json_exclusive(path, {"x": 1})
            self.assertEqual(identity, evaluator.file_identity(path))
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o444)
            self.assertEqual(path.stat().st_nlink, 1)
            with self.assertRaises(FileExistsError):
                evaluator.write_json_exclusive(path, {"x": 2})

    def test_csv_headers_match_freeze_schema(self):
        freeze = json.loads(evaluator.FREEZE.read_text(encoding="utf-8"))
        schema = freeze["analysis_bundle_contract"]["bundle_schema"]
        self.assertEqual(evaluator.ASSOCIATED_HEADER, schema["associated_pairs_csv_columns"])
        self.assertEqual(evaluator.RPE_HEADER, schema["rpe_pairs_csv_columns"])

    def test_freeze_blocks_inference_and_primary_replacement(self):
        freeze = json.loads(evaluator.FREEZE.read_text(encoding="utf-8"))
        self.assertFalse(freeze["statistical_contract"]["inferential_statistics_authorized"])
        diagnostic = freeze["alignment_contract"]["secondary_sim3_scale_diagnostic"]
        self.assertFalse(diagnostic["may_replace_primary_fixed_scale_se3"])
        self.assertFalse(diagnostic["may_enter_ranking_or_superiority_claim"])
        self.assertEqual(
            freeze["analysis_bundle_contract"]["claim_candidate_location"],
            "analysis-output/analysis-report.md#Claim Candidates",
        )

    def test_svg_generation_is_deterministic_and_external_asset_free(self):
        gt = np.asarray([[0.0, 0.0, 0.0], [1.0, 0.5, -0.2], [2.0, 1.0, 0.1]])
        first = evaluator.trajectory_figure(gt, gt + 0.1, gt + 0.2)
        second = evaluator.trajectory_figure(gt, gt + 0.1, gt + 0.2)
        self.assertEqual(first, second)
        self.assertIn("<svg", first)
        self.assertNotIn("http://", first.replace('http://www.w3.org/2000/svg', ''))
        self.assertNotIn("https://", first)

    def test_number_serialization_is_frozen_17g(self):
        self.assertEqual(evaluator.number_text(1.2345678901234567), format(1.2345678901234567, ".17g"))

    def test_bundle_tree_tamper_is_detected(self):
        with tempfile.TemporaryDirectory() as directory:
            attempt = Path(directory) / "attempt"
            analysis = attempt / "analysis-output"
            analysis.mkdir(parents=True)
            data_path = analysis / "data.txt"
            evaluator.write_text_exclusive(data_path, "original\n")
            data_identity = evaluator.file_identity(data_path)
            entries = {"analysis-output/data.txt": data_identity}
            manifest_path = analysis / "artifact-manifest.json"
            evaluator.write_json_exclusive(
                manifest_path,
                {
                    "schema_version": "test",
                    "entry_count": 1,
                    "bundle_content_tree_sha256": evaluator.artifact_tree_digest(entries),
                    "entries": entries,
                },
            )
            expected = dict(entries)
            expected["analysis-output/artifact-manifest.json"] = evaluator.file_identity(manifest_path)
            required = ["analysis-output/data.txt", "analysis-output/artifact-manifest.json"]
            with mock.patch.object(evaluator, "ATTEMPT", attempt), mock.patch.object(evaluator, "ANALYSIS", analysis), mock.patch.object(evaluator, "REQUIRED_BUNDLE_FILES", required):
                self.assertTrue(evaluator.audit_completed_bundle(expected)["ok"])
                os.chmod(data_path, 0o644)
                data_path.write_text("tampered\n", encoding="utf-8")
                os.chmod(data_path, 0o444)
                self.assertFalse(evaluator.audit_completed_bundle(expected)["ok"])


class SafetyTests(unittest.TestCase):
    def test_wrong_token_never_creates_namespace(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "must-not-exist"
            with mock.patch.object(evaluator, "EVIDENCE_ROOT", root):
                with contextlib.redirect_stdout(io.StringIO()):
                    return_code = evaluator.run_once("wrong-token")
            self.assertEqual(return_code, 2)
            self.assertFalse(root.exists())

    def test_signal_handler_is_pending_only(self):
        old = evaluator.PENDING_SIGNAL
        try:
            evaluator.PENDING_SIGNAL = None
            evaluator._signal_handler(15, None)
            self.assertEqual(evaluator.PENDING_SIGNAL, 15)
            with self.assertRaises(evaluator.ControlledSignal):
                evaluator.raise_if_pending()
        finally:
            evaluator.PENDING_SIGNAL = old

    def test_declared_identity_conflict_is_rejected(self):
        value = [
            {"path": "/tmp/a", "sha256": "a", "size_bytes": 1},
            {"path": "/tmp/a", "sha256": "b", "size_bytes": 1},
        ]
        with self.assertRaises(ValueError):
            evaluator.declared_identities(value)

    def test_pending_signal_after_root_creation_still_writes_terminal_fail(self):
        with tempfile.TemporaryDirectory() as directory:
            evidence = Path(directory) / "evidence"
            attempt = evidence / "attempt_001"
            analysis = attempt / "analysis-output"
            figures = analysis / "figures"
            start_claim = attempt / "evaluation_start_claim.json"
            preflight_result = attempt / "preflight_result.json"
            run_result = attempt / "run_result.json"
            original_mkdir = evaluator.mkdir_exclusive_durable

            def injecting_mkdir(path, mode=0o755):
                original_mkdir(path, mode)
                if path == evidence:
                    evaluator._signal_handler(signal.SIGTERM, None)

            preflight = {
                "ready": True,
                "status": "GO_EXACTLY_ONE_PURE_GT_EVALUATION_START",
                "failures": [],
                "pin_snapshot": {"checks": {}},
            }
            old_pending = evaluator.PENDING_SIGNAL
            old_owned = evaluator.NAMESPACE_OWNED
            old_committed = evaluator.TERMINAL_COMMITTED
            try:
                evaluator.PENDING_SIGNAL = None
                evaluator.NAMESPACE_OWNED = False
                evaluator.TERMINAL_COMMITTED = False
                with mock.patch.object(evaluator, "EVIDENCE_ROOT", evidence), mock.patch.object(evaluator, "ATTEMPT", attempt), mock.patch.object(evaluator, "ANALYSIS", analysis), mock.patch.object(evaluator, "FIGURES", figures), mock.patch.object(evaluator, "START_CLAIM", start_claim), mock.patch.object(evaluator, "PREFLIGHT_RESULT", preflight_result), mock.patch.object(evaluator, "RUN_RESULT", run_result), mock.patch.object(evaluator, "collect_preflight", return_value=preflight), mock.patch.object(evaluator, "mkdir_exclusive_durable", side_effect=injecting_mkdir):
                    with contextlib.redirect_stdout(io.StringIO()):
                        return_code = evaluator.run_once(evaluator.TOKEN)
                self.assertEqual(return_code, 1)
                self.assertTrue(run_result.exists())
                terminal = json.loads(run_result.read_text(encoding="utf-8"))
                self.assertEqual(terminal["status"], "FAIL_DEVELOPMENT_OFFICIAL_MH01_PURE_GT_EVALUATION")
                self.assertEqual(terminal["pending_signal"], signal.SIGTERM)
                self.assertIn("preflight_pin_snapshot", terminal)
                self.assertFalse(start_claim.exists())
            finally:
                evaluator.PENDING_SIGNAL = old_pending
                evaluator.NAMESPACE_OWNED = old_owned
                evaluator.TERMINAL_COMMITTED = old_committed


if __name__ == "__main__":
    unittest.main()
