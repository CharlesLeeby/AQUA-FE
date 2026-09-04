#!/usr/bin/env python3
"""Non-execution tests for the HFNet multi-window analysis generator v2."""

from __future__ import annotations

import copy
import csv
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest


GENERATOR = Path(__file__).resolve().parents[1] / "generate_hfnet_multiwindow_analysis_v2.py"
SPEC = importlib.util.spec_from_file_location("hfnet_multiwindow_analysis_v2", str(GENERATOR))
assert SPEC is not None and SPEC.loader is not None
analysis = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = analysis
SPEC.loader.exec_module(analysis)


def _distributed_segment(timestamps, start, end, total_ns):
    intervals = end - start
    quotient, remainder = divmod(total_ns, intervals)
    value = timestamps[start]
    for offset, index in enumerate(range(start + 1, end + 1), start=1):
        value += quotient + (1 if offset <= remainder else 0)
        timestamps[index] = value


def write_camera_csv(path: Path, count: int, *, legacy_exact: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    timestamps = [1_500_000_000_000_000_000 + index * 50_000_000 for index in range(count)]
    if legacy_exact:
        # Reproduce the frozen legacy delay and the camera-association span.
        _distributed_segment(timestamps, 900, 1779, 43_943_204_608)
        _distributed_segment(timestamps, 1779, 1800, 1_051_619_456)
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream, lineterminator="\n")
        writer.writerow(["#timestamp [ns]", "filename"])
        for timestamp in timestamps:
            writer.writerow([timestamp, "%d.png" % timestamp])


def write_current_result(
    path: Path,
    *,
    score_first: int,
    score_last: int,
    expected: int,
    produced: int,
    keyframes: int,
    raw_returncode: int = 0,
    strict_a02: bool = False,
    execution_lock: Path = None,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if produced > 0:
        observed_last = score_first + produced - 1
        score = {
            "count": produced,
            "coverage_fraction": produced / expected,
            "first_index": score_first,
            "last_index": observed_last,
            "longest_contiguous_run": produced,
            "gap_count": 0,
        }
    else:
        score = {
            "count": 0,
            "coverage_fraction": 0.0,
            "first_index": None,
            "last_index": None,
            "longest_contiguous_run": 0,
            "gap_count": 0,
        }
    passed = raw_returncode == 0 and produced / expected >= 0.70 and keyframes >= 1
    result = {
        "schema_version": (
            "aqua-fe-hfnet-v6-a02-0001-6300-strict70-run-result-v2"
            if strict_a02 else "synthetic-current-run-result-for-analysis-test"
        ),
        "status": (
            "PASS_EXPLORATORY_UNDERWATER_USABILITY"
            if passed else "FAIL_EXPLORATORY_UNDERWATER_USABILITY"
        ),
        "return_code": 0 if passed else 1,
        "execution": {
            "popen_invocations": 1,
            "retry_performed": False,
            "raw_returncode": raw_returncode,
            "timed_out": False,
            "duration_seconds": 12.5,
        },
        "support": {
            "trajectory": {
                "exists": produced > 0,
                "valid": produced > 0,
                "strictly_increasing_timestamps": produced > 0,
                "errors": [],
                "identity": {"path": str(path.parent / "result/trajectory.txt")},
                "score": score,
            },
            "keyframes": {
                "identity": {"path": str(path.parent / "result/trajectory_keyframe.txt")},
                "score": {"count": keyframes},
            },
        },
    }
    if strict_a02:
        assert execution_lock is not None and execution_lock.is_file()
        result["support"]["strict70_trajectory_adjudication"] = {
            "score_camera_count": 1801,
            "minimum_score_poses": 1261,
            "minimum_contiguous_score_poses": 1261,
            "score_pose_count": produced,
            "longest_contiguous_score_poses": produced,
            "pass": False,
        }
        result["pins"] = {
            "execution_lock": {
                "path": str(execution_lock),
                "sha256": hashlib.sha256(execution_lock.read_bytes()).hexdigest(),
            }
        }
    path.write_text(json.dumps(result), encoding="utf-8")


def write_legacy_result(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    result = {
        "schema_version": "synthetic-legacy-run-result-for-analysis-test",
        "execution": {
            "process_start_count": 1,
            "raw_returncode": 0,
            "timed_out": False,
        },
        "supervision": {"retry_performed": False},
        "gate": {
            "trajectory": {
                "score_pose_count": 22,
                "associated_first_relative_camera_index": 1779,
                "associated_last_relative_camera_index": 1800,
                "associated_skipped_camera_count": 0,
                "associated_max_camera_index_gap": 1,
                "association_max_abs_error_ns": 128,
                "score_span_seconds": 1.051619328,
                "identity": {"path": str(path.parent / "trajectory.txt")},
            },
            "keyframe_trajectory": {
                "score_pose_count": 6,
                "identity": {"path": str(path.parent / "trajectory_keyframe.txt")},
            },
        },
    }
    path.write_text(json.dumps(result), encoding="utf-8")


def make_inputs(root: Path, *, h07_state: str, a02_state: str) -> analysis.AnalysisInputs:
    specifications = {
        analysis.A06: (2461, 2210, 2460, 251, 27, "pass"),
        analysis.H07: (1720, 1659, 1719, 61, 19, h07_state),
        analysis.A02: (6300, 4499, 6299, 1801, 40, a02_state),
    }
    sources = {}
    for window_id, (count, first, last, expected, keyframes, state) in specifications.items():
        directory = root / window_id
        camera_csv = directory / "mav0/cam0/data.csv"
        run_result = directory / "attempt_001/run_result.json"
        selector = root / (window_id + "-selector.json")
        execution_lock = root / (window_id + "-lock.json")
        selector.write_text("{}\n", encoding="utf-8")
        execution_lock.write_text("synthetic immutable lock\n", encoding="utf-8")
        write_camera_csv(camera_csv, count)
        if state == "pass":
            write_current_result(
                run_result,
                score_first=first,
                score_last=last,
                expected=expected,
                produced=expected,
                keyframes=keyframes,
                strict_a02=window_id == analysis.A02,
                execution_lock=execution_lock,
            )
        elif state == "fail":
            write_current_result(
                run_result,
                score_first=first,
                score_last=last,
                expected=expected,
                produced=10,
                keyframes=1,
                strict_a02=window_id == analysis.A02,
                execution_lock=execution_lock,
            )
        elif state != "pending":
            raise AssertionError(state)
        sources[window_id] = analysis.WindowSource(
            window_id,
            run_result,
            camera_csv,
            selector,
            execution_lock,
            window_id != analysis.A06,
        )
    legacy_directory = root / analysis.LEGACY_A02
    legacy_camera_csv = legacy_directory / "mav0/cam0/data.csv"
    legacy_run_result = legacy_directory / "run_result.json"
    write_camera_csv(legacy_camera_csv, 1801, legacy_exact=True)
    write_legacy_result(legacy_run_result)
    sources[analysis.LEGACY_A02] = analysis.WindowSource(
        analysis.LEGACY_A02,
        legacy_run_result,
        legacy_camera_csv,
        root / "legacy-contract.json",
        None,
        False,
    )
    return analysis.AnalysisInputs(
        analysis.PROTOCOL,
        analysis.ROW_SCHEMA,
        analysis.CSV_TEMPLATE,
        sources,
    )


class MultiwindowAnalysisV2Tests(unittest.TestCase):
    def test_selector_namespaces_resolve_exactly(self) -> None:
        inputs = analysis.default_inputs()
        self.assertEqual(
            str(inputs.sources[analysis.H07].run_result),
            "/mnt/data/AQUA-FE_WS/logs/published_hfnet_slam_v6/fresh_underwater/"
            "aqualoc_harbor_h07_0001_1720/attempt_001/run_result.json",
        )
        self.assertEqual(
            str(inputs.sources[analysis.A02].run_result),
            "/mnt/data/AQUA-FE_WS/logs/published_hfnet_slam_v6/fresh_underwater/"
            "aqualoc_archaeology_a02_feed_0001_6300_score_4500_6300_strict70/"
            "attempt_001/run_result.json",
        )
        self.assertEqual(inputs.sources[analysis.A02].selector_or_contract, analysis.A02_STRICT70_PROTOCOL)
        self.assertEqual(inputs.sources[analysis.A02].execution_lock, analysis.A02_STRICT70_EXECUTION_LOCK)
        self.assertEqual(inputs.sources[analysis.A02].feed_selector, analysis.A02_SELECTOR)

    def test_frozen_strict70_terminal_normalizes_to_expected_fail(self) -> None:
        _, records, evidence = analysis.build_records(analysis.default_inputs())
        a02 = records[2]
        self.assertEqual(a02["usability"]["status"], "FAIL")
        self.assertEqual(a02["usability"]["failure_code"], "INSUFFICIENT_SCORE_COVERAGE")
        self.assertEqual(a02["execution"]["raw_returncode"], 0)
        self.assertEqual(a02["usability"]["score_pose_count"], 13)
        self.assertEqual(a02["usability"]["score_longest_contiguous_count"], 13)
        self.assertEqual(a02["usability"]["keyframe_score_count"], 4)
        self.assertEqual(a02["accuracy"]["state"], "BLOCKED_UNUSABLE")
        self.assertIn("SYSTEM_UNUSABLE", a02["accuracy"]["block_codes"])
        self.assertIn("HISTORY_MISMATCH", a02["accuracy"]["block_codes"])
        self.assertIsNone(a02["accuracy"]["ape_rmse_m"])
        self.assertEqual(evidence[2]["producer_terminal"]["controller_return_code"], 1)
        self.assertEqual(evidence[2]["producer_terminal"]["raw_returncode"], 0)

    def test_pending_rows_remain_null_and_figures_are_withheld(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            inputs = make_inputs(root, h07_state="pending", a02_state="pending")
            output = root / "pending-bundle"
            bundle = analysis.emit_bundle(inputs, output, generated_at="2026-08-22T00:00:00+00:00")
            self.assertEqual(bundle["analysis_state"], "PENDING_CURRENT_RESULTS")
            self.assertEqual(bundle["current_protocol_summary"]["denominator"], 3)
            self.assertEqual(bundle["current_protocol_summary"]["pending_count"], 2)
            self.assertIsNone(bundle["current_protocol_summary"]["final_usable_k_of_3"])
            self.assertFalse(bundle["figures_generated"])
            self.assertFalse((output / "figures").exists())
            for record in bundle["rows"][1:3]:
                self.assertEqual(record["usability"]["status"], "PENDING")
                self.assertIsNone(record["usability"]["score_pose_count"])
                self.assertIsNone(record["usability"]["score_coverage_fraction"])
                self.assertIsNone(record["accuracy"]["ape_rmse_m"])
                self.assertIsNone(record["accuracy"]["rpe_rmse_m"])
            with (output / "hfnet_multiwindow_results_final_v2.csv").open(
                "r", encoding="utf-8", newline=""
            ) as stream:
                csv_rows = list(csv.DictReader(stream))
            self.assertEqual(csv_rows[1]["score_pose_count"], "")
            self.assertEqual(csv_rows[2]["score_coverage_fraction"], "")
            report = (output / "hfnet_multiwindow_analysis_report_v2.md").read_text(encoding="utf-8")
            self.assertIn("PENDING", report)
            self.assertIn("不把 PENDING 计入失败", report)

    def test_terminal_bundle_preserves_failure_support_and_generates_vectors(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            inputs = make_inputs(root, h07_state="pass", a02_state="fail")
            output = root / "terminal-bundle"
            bundle = analysis.emit_bundle(
                inputs,
                output,
                require_current_terminal=True,
                generated_at="2026-08-22T00:00:00+00:00",
            )
            self.assertEqual(bundle["analysis_state"], "TERMINAL_DESCRIPTIVE_ONLY")
            self.assertEqual(bundle["presentation_revision"], "v2.1")
            self.assertEqual(bundle["current_protocol_summary"]["final_usable_k_of_3"], "2/3")
            self.assertTrue(bundle["current_protocol_summary"]["legacy_context_excluded_from_denominator"])
            a02 = bundle["rows"][2]
            self.assertEqual(a02["usability"]["status"], "FAIL")
            self.assertEqual(a02["usability"]["failure_code"], "INSUFFICIENT_SCORE_COVERAGE")
            self.assertEqual(a02["usability"]["score_pose_count"], 10)
            self.assertAlmostEqual(a02["usability"]["score_coverage_fraction"], 10 / 1801)
            self.assertIsNone(a02["accuracy"]["ape_rmse_m"])
            legacy = bundle["rows"][3]
            self.assertEqual(legacy["usability"]["score_pose_count"], 22)
            self.assertEqual(legacy["row_role"], "LEGACY_TERMINAL_CONTEXT")
            for stem in (
                "figure-01-usability-matrix-v2",
                "figure-02-score-support-v2",
                "figure-03-feed-score-timeline-v2",
            ):
                svg = output / "figures" / (stem + ".svg")
                pdf = output / "figures" / (stem + ".pdf")
                self.assertGreater(svg.stat().st_size, 1000)
                self.assertTrue(pdf.read_bytes().startswith(b"%PDF"))
            support_svg = (
                output / "figures/figure-02-score-support-v2.svg"
            ).read_text(encoding="utf-8")
            self.assertNotIn("expected=", support_svg)
            report = (output / "hfnet_multiwindow_analysis_report_v2.md").read_text(
                encoding="utf-8"
            )
            self.assertIn("呈现修订：`v2.1`", report)
            self.assertFalse(bundle["statistical_gate"]["significance_tests_permitted"])
            self.assertFalse(bundle["statistical_gate"]["confidence_intervals_permitted"])
            self.assertFalse(bundle["statistical_gate"]["cross_window_winner_ranking_permitted"])

    def test_strict_final_rejects_pending_before_writing(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            inputs = make_inputs(root, h07_state="pass", a02_state="pending")
            output = root / "must-not-exist"
            with self.assertRaisesRegex(analysis.EvidenceError, "STRICT_FINAL_BLOCKED_PENDING"):
                analysis.emit_bundle(inputs, output, require_current_terminal=True)
            self.assertFalse(output.exists())

    def test_accuracy_numeric_imputation_is_rejected_by_final_gate(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            inputs = make_inputs(Path(directory), h07_state="pass", a02_state="fail")
            _, records, _ = analysis.build_records(inputs)
            tampered = copy.deepcopy(records)
            tampered[2]["accuracy"]["ape_rmse_m"] = 0.0
            with self.assertRaisesRegex(analysis.EvidenceError, "ROW_SCHEMA_INVALID|IMPUTATION_FORBIDDEN"):
                analysis.validate_records(tampered, analysis._read_json(analysis.ROW_SCHEMA))

    def test_output_directory_is_additive_and_never_overwritten(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            inputs = make_inputs(root, h07_state="pending", a02_state="pending")
            output = root / "bundle"
            analysis.emit_bundle(inputs, output)
            with self.assertRaisesRegex(analysis.EvidenceError, "OUTPUT_DIRECTORY_ALREADY_EXISTS"):
                analysis.emit_bundle(inputs, output)


if __name__ == "__main__":
    unittest.main()
