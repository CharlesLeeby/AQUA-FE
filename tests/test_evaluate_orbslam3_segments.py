from __future__ import annotations

import argparse
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from evaluate_orbslam3_segments import discover_runs, metric_stats, parse_segment


class EvaluateOrbSlam3SegmentsTest(unittest.TestCase):
    def test_parses_bounded_segment(self) -> None:
        self.assertEqual(parse_segment("prefix:0:120", 401), ("prefix", 0, 120))
        with self.assertRaises(argparse.ArgumentTypeError):
            parse_segment("bad:120:0", 401)
        with self.assertRaises(argparse.ArgumentTypeError):
            parse_segment("bad/name:0:1", 401)

    def test_discovers_arbitrary_complete_repeat_matrix(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for repeat in range(1, 4):
                for role in (
                    "orb_only",
                    "drop",
                    "full_bridge_off",
                    "full_unbounded",
                    "full",
                ):
                    (root / f"{role}_r{repeat}").mkdir()
            (root / "orb_only_r3_partial_timeout").mkdir()

            runs = discover_runs(root)

        self.assertEqual(len(runs), 15)
        self.assertEqual(runs[0][0:2], ("orb_only", 1))
        self.assertEqual(runs[-1][0:2], ("full", 3))

    def test_rejects_incomplete_optional_matrix(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for repeat in range(1, 4):
                for role in ("orb_only", "drop", "full"):
                    (root / f"{role}_r{repeat}").mkdir()
            (root / "full_bridge_off_r1").mkdir()

            with self.assertRaisesRegex(SystemExit, "incomplete optional"):
                discover_runs(root)

    def test_parses_evo_metric_output(self) -> None:
        stats = metric_stats("max 0.4\nmedian 0.2\nrmse 0.3\n")
        self.assertEqual(stats, {"rmse": 0.3, "median": 0.2, "max": 0.4})
        with self.assertRaisesRegex(RuntimeError, "missing median"):
            metric_stats("max 0.4\nrmse 0.3\n")


if __name__ == "__main__":
    unittest.main()
