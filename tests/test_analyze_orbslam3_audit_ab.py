from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from analyze_orbslam3_audit_ab import (
    holm_adjust,
    rank_biserial,
    validate_csv_row_against_run,
    wilcoxon_signed_rank,
    win_counts,
)


class AnalyzeOrbSlam3AuditAbTest(unittest.TestCase):
    def test_holm_adjustment_preserves_step_down_monotonicity(self) -> None:
        adjusted = holm_adjust([0.01, 0.04, 0.5])
        np.testing.assert_allclose(adjusted, [0.03, 0.08, 0.5])

    def test_rank_biserial_sign_convention(self) -> None:
        self.assertEqual(rank_biserial(np.array([1.0, 2.0, 3.0])), 1.0)
        self.assertEqual(rank_biserial(np.array([-1.0, -2.0, -3.0])), -1.0)
        self.assertEqual(rank_biserial(np.array([1.0, 2.0, -3.0])), 0.0)

    def test_wilcoxon_all_zero_pairs_are_explicit(self) -> None:
        result = wilcoxon_signed_rank(np.zeros(8))
        self.assertEqual(result["effective_n"], 0)
        self.assertEqual(result["statistic"], 0.0)
        self.assertEqual(result["p_value"], 1.0)

    def test_wilcoxon_reports_nonzero_effective_sample(self) -> None:
        result = wilcoxon_signed_rank(np.array([0.0, 1.0, -2.0, 0.0]))
        self.assertEqual(result["effective_n"], 2)

    def test_wilcoxon_exact_enumeration_respects_tied_ranks(self) -> None:
        result = wilcoxon_signed_rank(np.array([1.0, 1.0, 2.0, -3.0]))
        self.assertEqual(result["effective_n"], 4)
        self.assertAlmostEqual(result["p_value"], 0.75)

    def test_win_counts_requires_equal_coverage_for_metric_wins(self) -> None:
        rows = []
        for repeat in range(1, 9):
            rows.extend(
                [
                    {
                        "role": "orb_only",
                        "repeat": repeat,
                        "coverage_ratio": 1.0,
                        "ape_rmse_m": 2.0,
                        "rpe_rmse_m": 2.0,
                    },
                    {
                        "role": "drop",
                        "repeat": repeat,
                        "coverage_ratio": 1.0,
                        "ape_rmse_m": 3.0,
                        "rpe_rmse_m": 3.0,
                    },
                    {
                        "role": "full",
                        "repeat": repeat,
                        "coverage_ratio": 0.5 if repeat == 8 else 1.0,
                        "ape_rmse_m": 1.0,
                        "rpe_rmse_m": 1.0,
                    },
                ]
            )
        frame = pd.DataFrame(rows)
        result = win_counts({"audit_on": frame}).set_index("baseline")
        self.assertEqual(result.loc["orb_only", "coverage_comparable"], 7)
        self.assertEqual(result.loc["orb_only", "double_wins"], 7)
        self.assertEqual(result.loc["drop", "double_wins"], 7)

    def test_raw_run_binding_rejects_seed_log_counter_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            run_dir = root / "orb_only_r1"
            run_dir.mkdir()
            times = root / "times.txt"
            times.write_text("100\n", encoding="ascii")
            (run_dir / "run_manifest.txt").write_text(
                "role=orb_only\nrepeat=1\ntimes_file=" + str(times) + "\n",
                encoding="utf-8",
            )
            (run_dir / "f_case.txt").write_text(
                "100 0 0 0 0 0 0 1\n", encoding="ascii"
            )
            (run_dir / "orbslam3_run.log").write_text(
                "External seed summary: frames=0 attempted=0 accepted=0\n",
                encoding="utf-8",
            )
            report = "rmse 1\nmedian 2\nmax 3\n"
            (run_dir / "ape_trans.txt").write_text(report, encoding="utf-8")
            (run_dir / "rpe_trans_1f.txt").write_text(report, encoding="utf-8")
            row = pd.Series(
                {
                    "role": "orb_only",
                    "repeat": 1,
                    "run_dir": str(run_dir),
                    "input_frames": 1,
                    "output_poses": 1,
                    "coverage_ratio": 1.0,
                    "seeded_frames": 0,
                    "attempted_seeds": 1,
                    "accepted_seeds": 0,
                    "map_resets": 0,
                    "relocalizations": 0,
                    "ape_rmse_m": 1.0,
                    "ape_median_m": 2.0,
                    "ape_max_m": 3.0,
                    "rpe_rmse_m": 1.0,
                    "rpe_median_m": 2.0,
                    "rpe_max_m": 3.0,
                }
            )
            with self.assertRaisesRegex(SystemExit, "seed log counters mismatch"):
                validate_csv_row_against_run(row, root)


if __name__ == "__main__":
    unittest.main()
