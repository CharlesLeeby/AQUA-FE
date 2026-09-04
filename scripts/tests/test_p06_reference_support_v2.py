#!/usr/bin/env python3

from __future__ import annotations

import unittest

from scripts.build_p06_reference_window_support_v2 import g0_reference_support


class P06ReferenceSupportV2Test(unittest.TestCase):
    def test_complete_reference_passes(self) -> None:
        result = g0_reference_support(
            [float(value) for value in range(46)], 0.0, 45.0, 1.0, 2.5
        )
        self.assertTrue(result["pass"])
        self.assertEqual(result["reason"], "PASS_G0_REFERENCE_ONLY")

    def test_segmented_reference_can_pass_g0_threshold(self) -> None:
        stamps = [float(value) for value in range(46) if not 15 <= value <= 25]
        result = g0_reference_support(stamps, 0.0, 45.0, 1.0, 2.5)
        self.assertTrue(result["pass"])
        self.assertGreaterEqual(result["coverage"], 0.70)
        self.assertGreaterEqual(result["supported_grid_count"], 30)

    def test_reference_below_coverage_threshold_fails(self) -> None:
        stamps = [float(value) for value in range(30)]
        result = g0_reference_support(stamps, 0.0, 45.0, 1.0, 2.5)
        self.assertFalse(result["pass"])
        self.assertIn("REFERENCE_COVERAGE_LT_0P70", result["reason"])


if __name__ == "__main__":
    unittest.main()
