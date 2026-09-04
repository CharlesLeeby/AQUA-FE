#!/usr/bin/env python3

from __future__ import annotations

import unittest

from scripts.build_p06_reference_capacity_correction import build_rows


class P06ReferenceCapacityTest(unittest.TestCase):
    def test_corrected_capacity_retains_quota_breadth(self) -> None:
        rows, summary = build_rows()
        self.assertEqual(len(rows), 18)
        self.assertEqual(summary["reference_eligible_sequence_count"], 17)
        self.assertEqual(summary["corrected_capped_slot_count"], 49)
        self.assertEqual(summary["corrected_domain_count"], 4)
        self.assertEqual(summary["excluded_sequences"], ["afrl/cave_gennie"])

    def test_history_overlap_prevents_double_subtraction(self) -> None:
        rows, _ = build_rows()
        by_sequence = {row["sequence"]: row for row in rows}
        self.assertEqual(by_sequence["A08"]["reference_failed_windows"], 3)
        self.assertEqual(by_sequence["A08"]["history_reference_overlap_windows"], 3)
        self.assertEqual(by_sequence["A08"]["corrected_available_windows"], 2)


if __name__ == "__main__":
    unittest.main()
