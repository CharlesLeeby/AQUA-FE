from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "summarize_msckf_dvio_triplet.py"


class SummarizeMsckfDvioTripletTest(unittest.TestCase):
    def test_reports_paired_wins_and_medians(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            for round_index in range(1, 3):
                values = {
                    "full": (0.8 + 0.01 * round_index, 0.4),
                    "drop": (1.0 + 0.01 * round_index, 0.5),
                    "klt": (1.2 + 0.01 * round_index, 0.6),
                }
                for role, (ape, rpe) in values.items():
                    run = root / f"round_{round_index:02d}_{role}"
                    run.mkdir()
                    (run / "metrics.txt").write_text(
                        f"se3_ape_rmse_m={ape}\n"
                        f"rpe_trans_rmse_m={rpe}\n"
                        "output_coverage_ratio=1.0\n"
                        "output_poses=200\n"
                        "init_success=1\n"
                        "log_linear_solver_failures=0\n",
                        encoding="ascii",
                    )
                    (run / "estimator.log").write_text(
                        "chi2 failed: id:1\n", encoding="ascii"
                    )
            output_csv = root / "runs.csv"
            report = root / "report.md"
            subprocess.run(
                [
                    "python3",
                    str(SCRIPT),
                    "--run-root",
                    str(root),
                    "--rounds",
                    "2",
                    "--output-csv",
                    str(output_csv),
                    "--output-report",
                    str(report),
                ],
                check=True,
                capture_output=True,
                text=True,
            )
            text = report.read_text(encoding="utf-8")
            self.assertIn("full vs drop | 2/2 | 2/2 | 2/2", text)
            self.assertIn("full vs klt | 2/2 | 2/2 | 2/2", text)
            self.assertEqual(len(output_csv.read_text().splitlines()), 7)


if __name__ == "__main__":
    unittest.main()
