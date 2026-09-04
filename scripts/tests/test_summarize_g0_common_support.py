#!/usr/bin/env python3

from __future__ import annotations

import unittest

from scripts.summarize_g0_common_support import historical_signal_decision


class SummarizeG0CommonSupportTest(unittest.TestCase):
    def test_insufficient_support_forces_review(self) -> None:
        rows = [{"ape_valid": 0, "corrected_ape_gain": 0.50}]
        self.assertEqual(historical_signal_decision(rows), "HISTORICAL_SIGNAL_REVIEW")

    def test_supported_gain_routes_to_preserved_or_redirect(self) -> None:
        preserved = [
            {"ape_valid": 1, "corrected_ape_gain": 0.02},
            {"ape_valid": 1, "corrected_ape_gain": 0.10},
        ]
        redirected = [
            {"ape_valid": 1, "corrected_ape_gain": -0.02},
            {"ape_valid": 1, "corrected_ape_gain": -0.10},
        ]
        self.assertEqual(
            historical_signal_decision(preserved), "HISTORICAL_SIGNAL_PRESERVED"
        )
        self.assertEqual(
            historical_signal_decision(redirected), "HISTORICAL_SIGNAL_REDIRECT"
        )


if __name__ == "__main__":
    unittest.main()
