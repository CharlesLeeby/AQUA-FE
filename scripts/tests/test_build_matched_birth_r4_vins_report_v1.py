from __future__ import annotations

import copy
import json
import os
from pathlib import Path
import stat
import tempfile
import unittest

from scripts import build_matched_birth_r4_vins_report_v1 as report


def write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


class MatchedBirthR4VinsReportTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.evaluation = self.root / "sealed-evaluation"
        self.evaluation.mkdir()
        self.corrected_path = self.root / "corrected.json"
        self.post_path = self.root / "post.json"

        self.corrected = {
            "schema_version": report.CORRECTED_SCHEMA,
            "status": "PASS",
            "pass": True,
            "claim_boundary": {
                "confirmatory": False,
                "statistical_significance": False,
                "whole_slam_superiority": False,
                "detector_birth_source_only_within_this_frozen_carrier": True,
                "detector_rerun_or_r4_mutation_authorized": False,
                "old_error_remains_authoritative_for_consumed_old_name": True,
                "this_fresh_continuation_seal_is_additive": True,
                "vins_authorized_by_this_seal_only_after_contract_pass": True,
            },
        }
        write_json(self.corrected_path, self.corrected)

        self.arms = {
            "XFEATBIRTH_RAWLK": self.arm(0.70, 0.05, raw=845),
            "GFTTBIRTH_RAWLK": self.arm(1.00, 0.25, raw=854),
        }
        self.summary = {
            "protocol": {
                "contrast_name": "A02_4500_6300_MATCHED_BIRTH_FORMAL900_R4_XFEAT_VS_GFTT_FULL_INTERVAL",
                "reference": f"{report.EXPECTED_REFERENCE_PATH}:{report.EXPECTED_REFERENCE_TOPIC}",
                "evaluation_rate_hz": 1.0,
                "nominal_reference_rate_hz": 1.0,
                "nominal_estimate_rate_hz": 10.0,
                "window_start_s": report.EXPECTED_WINDOW_START,
                "window_end_s": report.EXPECTED_WINDOW_END,
                "max_reference_gap_s": 2.5,
                "max_estimate_gap_s": 0.25,
                "rpe_delta_s": 1.0,
                "body_to_camera_applied": True,
                "rpe_semantics": "aligned_global_frame_positional_delta",
                "reference_time_offset_s": 0.0,
                "arm_time_offsets_s": {arm: 0.0 for arm in report.EXPECTED_ARMS},
            },
            "support": {
                "ape_valid": True,
                "rpe_valid": True,
                "grid_count": 90,
                "matched_count": 84,
                "common_span_s": 83.0,
                "common_coverage": 84 / 90,
                "segment_count": 1,
                "rpe_pairs": 83,
                "window_duration_s": 89.9870752,
            },
            "reference": {"valid_grid_count": 90},
            "arms": self.arms,
        }
        self.evo = {
            "evo_version": "1.31.1",
            "rpe_delta_frames": 1,
            "rpe_semantics": "aligned_global_frame_positional_delta",
            "arms": {
                arm: {
                    "primary_ape_rmse_m": values["ape_rmse_m"],
                    "evo_ape_rmse_m": values["ape_rmse_m"],
                    "ape_abs_diff_m": 0.0,
                    "primary_rpe_rmse_m": values["rpe_rmse_m"],
                    "evo_segmented_rpe_rmse_m": values["rpe_rmse_m"],
                    "rpe_abs_diff_m": 0.0,
                    "rpe_pair_count": 83,
                    "segments": [{"segment_id": 0, "pair_count": 83, "rmse_m": values["rpe_rmse_m"]}],
                }
                for arm, values in self.arms.items()
            },
        }
        write_json(self.evaluation / report.SUMMARY_NAME, self.summary)
        write_json(self.evaluation / report.EVO_NAME, self.evo)
        (self.evaluation / report.METRICS_NAME).write_text("arm,ape_rmse_m\nXFEATBIRTH_RAWLK,0.70\nGFTTBIRTH_RAWLK,1.00\n")
        (self.evaluation / report.GRID_NAME).write_text("timestamp,common_valid\n1542829016.7,0\n")
        write_json(self.evaluation / "evaluator_process_receipt_v1.json", {"return_code": 0})
        self.write_manifest()
        self.write_post()

    def tearDown(self) -> None:
        self.temporary.cleanup()

    @staticmethod
    def arm(ape: float, rpe: float, *, raw: int) -> dict[str, object]:
        return {
            "ape_rmse_m": ape,
            "ape_median_m": ape * 0.8,
            "ape_max_m": ape * 1.8,
            "rpe_rmse_m": rpe,
            "rpe_median_m": rpe * 0.8,
            "rpe_max_m": rpe * 2.0,
            "matched_count": 84,
            "rpe_pairs": 83,
            "valid_grid_count": 84,
            "bracket_gap_p50_s": 0.1,
            "bracket_gap_p95_s": 0.102,
            "bracket_gap_max_s": 0.105,
            "legacy_pair_count": raw,
            "legacy_unique_reference_used": 85,
            "legacy_max_reference_reuse": 10,
            "legacy_timestamp_error_p95_s": 0.45,
            "legacy_timestamp_error_max_s": 0.46,
            "legacy_unique_assignment_pair_count": 85,
            "legacy_unique_assignment_error_p95_s": 0.05,
            "legacy_unique_assignment_error_max_s": 0.06,
            "audit": {
                "raw_count": raw,
                "finite_count": raw,
                "unique_count": raw,
                "duplicate_count": 0,
                "rejected_nonfinite_count": 0,
            },
            "rejection_histogram": {"INTERPOLATED": 84, "OUT_OF_RANGE": 6},
        }

    def write_manifest(self) -> None:
        manifest = {
            "schema_version": report.MANIFEST_SCHEMA,
            "status": "SEALED_STAGING_READY_FOR_NOREPLACE_PROMOTION",
            "members_excluding_this_manifest": report.live_tree_inventory(self.evaluation),
        }
        write_json(self.evaluation / report.MANIFEST_NAME, manifest)

    def post_claim(self) -> dict[str, bool]:
        return {
            "runner_local_ape_results_visible_before_freeze": True,
            "outcome_blind": False,
            "confirmatory": False,
            "statistical_significance": False,
            "cross_window_or_cross_dataset_generalization": False,
            "whole_slam_superiority": False,
            "reference_is_image_derived_colmap_not_independent_ground_truth": True,
        }

    def write_post(self) -> None:
        post = {
            "schema_version": report.POST_SCHEMA,
            "status": report.POST_STATUS,
            "pass": True,
            "corrected_r4_seal": report.file_identity(self.corrected_path),
            "formal_output_manifest": report.file_identity(self.evaluation / report.MANIFEST_NAME),
            "summary": report.file_identity(self.evaluation / report.SUMMARY_NAME),
            "evo_crosscheck": report.file_identity(self.evaluation / report.EVO_NAME),
            "strict_gates": {
                "evaluator_rc0": True,
                "ape_valid": True,
                "rpe_valid": True,
                "grid_count": 90,
                "expected_grid_count": 90,
                "summary_recomputed": True,
                "output_manifest_and_tree_closure": True,
                "evo_primary_echo_crosschecked": True,
            },
            "failure_reasons": [],
            "result_metrics": self.arms,
            "claim_boundary": self.post_claim(),
        }
        write_json(self.post_path, post)

    def load(self) -> dict[str, object]:
        return report.load_evidence(
            self.evaluation,
            self.corrected_path,
            post_seal_path=self.post_path,
        )

    def test_renderer_produces_four_documents_with_complete_boundaries(self) -> None:
        documents = report.render_documents(self.load())
        self.assertEqual(
            set(documents),
            {report.REPORT_NAME, report.ANALYSIS_NAME, report.STATS_NAME, report.FIGURE_CATALOG_NAME},
        )
        main = documents[report.REPORT_NAME]
        self.assertIn("one VINS replay per arm", main)
        self.assertIn("No confidence interval", main)
        self.assertIn("whole-SLAM superiority", main)
        self.assertIn("standalone detector superiority", main)
        self.assertIn("image-derived COLMAP", main)
        self.assertIn("1542829016.700435392", main)
        self.assertIn("1542829106.687510592", main)
        self.assertIn("full 90 s", documents[report.ANALYSIS_NAME])

    def test_primary_values_are_transcribed_and_inference_is_blocked(self) -> None:
        documents = report.render_documents(self.load())
        appendix = documents[report.STATS_NAME]
        self.assertIn("| XFeat birth | 0.7 | 0.56 | 1.26 | 0.05 | 0.04 | 0.1 |", appendix)
        self.assertIn("| GFTT birth | 1 | 0.8 | 1.8 | 0.25 | 0.2 | 0.5 |", appendix)
        self.assertIn("one replay per arm", appendix)
        self.assertIn("Inferential statistics: not run", appendix)
        self.assertIn("neither common grid poses nor RPE pairs are treated as independent replicates", appendix)

    def test_all_native_and_legacy_diagnostics_are_rendered(self) -> None:
        documents = report.render_documents(self.load())
        appendix = documents[report.STATS_NAME]
        for key in report.LEGACY_KEYS:
            self.assertIn(f"`{key}`", appendix)
        for key in ("raw_count", "finite_count", "unique_count", "duplicate_count", "rejected_nonfinite_count"):
            self.assertIn(f"`{key}`", appendix)
        self.assertIn("Runner-local `ape.txt`", appendix)
        self.assertIn("deliberately not transcribed", appendix)

    def test_figure_catalog_has_real_sources_but_no_fabricated_error_bars(self) -> None:
        catalog = report.render_documents(self.load())[report.FIGURE_CATALOG_NAME]
        self.assertIn(report.METRICS_NAME, catalog)
        self.assertIn(report.GRID_NAME, catalog)
        self.assertIn("Error bars: none", catalog)
        self.assertIn("No figure is published", catalog)

    def test_rejects_metric_echo_drift_in_post_seal(self) -> None:
        post = json.loads(self.post_path.read_text())
        post["result_metrics"]["XFEATBIRTH_RAWLK"]["ape_rmse_m"] = 999.0
        write_json(self.post_path, post)
        with self.assertRaisesRegex(report.ReportError, "exactly echo"):
            self.load()

    def test_rejects_output_tree_drift(self) -> None:
        (self.evaluation / "unsealed-extra.txt").write_text("drift\n")
        with self.assertRaisesRegex(report.ReportError, "close the live evaluation tree"):
            self.load()

    def test_rejects_incomplete_claim_boundary(self) -> None:
        post = json.loads(self.post_path.read_text())
        del post["claim_boundary"]["statistical_significance"]
        write_json(self.post_path, post)
        with self.assertRaisesRegex(report.ReportError, "claim boundary"):
            self.load()

    def test_rejects_proxy_half_window(self) -> None:
        summary = json.loads((self.evaluation / report.SUMMARY_NAME).read_text())
        summary["protocol"]["window_start_s"] = 1542829061.692686528
        write_json(self.evaluation / report.SUMMARY_NAME, summary)
        os.unlink(self.evaluation / report.MANIFEST_NAME)
        self.write_manifest()
        self.write_post()
        with self.assertRaisesRegex(report.ReportError, "window start"):
            self.load()

    def test_publish_is_exclusive_and_read_only(self) -> None:
        documents = report.render_documents(self.load())
        output = self.root / "analysis-v1"
        report.publish_documents(output, documents)
        self.assertEqual(sorted(path.name for path in output.iterdir()), sorted(documents))
        for path in output.iterdir():
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o444)
        with self.assertRaisesRegex(report.ReportError, "already exists"):
            report.publish_documents(output, documents)

    def test_source_has_no_scientific_evaluator_dependencies(self) -> None:
        source = Path(report.__file__).read_text(encoding="utf-8")
        for forbidden in (
            "import numpy",
            "import rosbag",
            "trajectory_eval_core",
            "evaluate_vins_common_support",
            "load_vins",
            "align_se3",
            "compute_rpe",
        ):
            self.assertNotIn(forbidden, source)


if __name__ == "__main__":
    unittest.main()
