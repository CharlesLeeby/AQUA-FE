#!/usr/bin/env python3

from __future__ import annotations

import unittest

from scripts.validate_p06_final_artifacts import afrl_stamp, reference_support


class P06FinalArtifactTest(unittest.TestCase):
    def test_reference_support_requires_complete_45_second_grid(self) -> None:
        result = reference_support(
            [float(value) for value in range(46)],
            0.0,
            45.0,
            evaluation_rate_hz=1.0,
            max_reference_gap_s=2.5,
        )
        self.assertTrue(result["pass"])
        self.assertEqual(result["supported_grid_count"], 46)
        self.assertEqual(result["coverage"], 1.0)

    def test_reference_support_rejects_internal_gap(self) -> None:
        stamps = [float(value) for value in range(46) if not 20 <= value <= 30]
        result = reference_support(
            stamps,
            0.0,
            45.0,
            evaluation_rate_hz=1.0,
            max_reference_gap_s=2.5,
        )
        self.assertFalse(result["pass"])
        self.assertLess(result["coverage"], 1.0)

    def test_cemetery_compact_timestamp_is_normalized(self) -> None:
        self.assertAlmostEqual(
            afrl_stamp("153.522486209", "cemetery"),
            1535224862.09,
            places=6,
        )
        self.assertEqual(afrl_stamp("1535224860.5", "cave_gennie"), 1535224860.5)


if __name__ == "__main__":
    unittest.main()
