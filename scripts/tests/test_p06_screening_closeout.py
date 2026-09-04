#!/usr/bin/env python3

from __future__ import annotations

import unittest
import hashlib
import json
import tempfile
from pathlib import Path
from unittest import mock

from scripts import validate_p06_screening_closeout as closeout
from scripts.validate_p06_screening_closeout import (
    histogram_is_inactive,
    inactive_value,
    metric_rows_contract,
)


class P06ScreeningCloseoutTest(unittest.TestCase):
    def test_inactive_values_are_strict(self) -> None:
        for value in ("0", "0.0", "false", "n/a", "nan", "disabled", None):
            self.assertTrue(inactive_value(value))
        self.assertFalse(inactive_value("0.01"))
        self.assertFalse(inactive_value("accepted"))

    def test_histogram_allows_classical_only(self) -> None:
        self.assertTrue(histogram_is_inactive("gftt:350;klt:2"))
        self.assertTrue(histogram_is_inactive("gftt:350;xfeat:0"))
        self.assertFalse(histogram_is_inactive("gftt:340;xfeat:10"))

    def test_metric_contract_rejects_learned_and_outcome_columns(self) -> None:
        row = {
            "frame_index": "0",
            "grid_coverage": "0.8",
            "dropout_ratio": "0.1",
            "flat_region_ratio": "0.2",
            "degradation_score": "0.3",
            "tracker_mode": "klt",
            "learned_candidate_count": "0",
            "export_source_histogram": "gftt:10",
        }
        self.assertEqual(metric_rows_contract([row]), [])
        row["learned_candidate_count"] = "1"
        self.assertTrue(any("learned_nonzero" in item for item in metric_rows_contract([row])))
        row["learned_candidate_count"] = "0"
        row["rpe_rmse"] = "0.1"
        self.assertTrue(any("outcome_column" in item for item in metric_rows_contract([row])))

    def test_metric_contract_rejects_frame_gap(self) -> None:
        rows = []
        for frame in (0, 2):
            rows.append(
                {
                    "frame_index": str(frame),
                    "grid_coverage": "0.8",
                    "dropout_ratio": "0.1",
                    "flat_region_ratio": "0.2",
                    "degradation_score": "0.3",
                    "tracker_mode": "klt",
                }
            )
        self.assertIn("frame_index_gap", metric_rows_contract(rows))

    def test_afrl_pointer_resolves_only_matching_hashed_attempt(self) -> None:
        with tempfile.TemporaryDirectory(dir=closeout.ROOT) as temporary:
            screening = Path(temporary) / "screening"
            canonical = screening / "afrl" / "cave_gennie"
            attempt = canonical / "attempt02"
            attempt.mkdir(parents=True)
            metrics = attempt / "metrics.csv"
            audit = attempt / "screening_run.json"
            process_log = attempt / "process.log"
            metrics.write_text("frame_index\n0\n", encoding="utf-8")
            audit.write_text("{}\n", encoding="utf-8")
            process_log.write_text("pass\n", encoding="utf-8")
            relative = attempt.resolve().relative_to(closeout.ROOT).as_posix()
            pointer = {
                "schema_version": "isj-p06-current-attempt-v1",
                "dataset_family": "afrl",
                "sequence": "cave_gennie",
                "attempt_id": "attempt02",
                "status": "PASS",
                "run_dir": relative,
                "metrics_path": metrics.resolve().relative_to(closeout.ROOT).as_posix(),
                "screening_run_path": audit.resolve().relative_to(closeout.ROOT).as_posix(),
                "process_log_path": process_log.resolve().relative_to(closeout.ROOT).as_posix(),
                "metrics_sha256": hashlib.sha256(metrics.read_bytes()).hexdigest(),
                "screening_run_sha256": hashlib.sha256(audit.read_bytes()).hexdigest(),
                "process_log_sha256": hashlib.sha256(process_log.read_bytes()).hexdigest(),
            }
            (canonical / "current_attempt.json").write_text(
                json.dumps(pointer) + "\n", encoding="utf-8"
            )
            with mock.patch.object(closeout, "SCREENING", screening):
                resolved, issues = closeout.resolve_screening_dir(
                    "afrl", "cave_gennie"
                )
                self.assertEqual(resolved, attempt)
                self.assertEqual(issues, [])
                metrics.write_text("frame_index\n1\n", encoding="utf-8")
                _, issues = closeout.resolve_screening_dir("afrl", "cave_gennie")
                self.assertIn("current_attempt_metrics_hash_mismatch", issues)


if __name__ == "__main__":
    unittest.main()
