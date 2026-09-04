from __future__ import annotations

import unittest

from scripts import build_e3_dualmetric_summary as e3


class E3DualMetricSummaryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.groups = e3.grouped_input()
        cls.rows = e3.load_g0_rows(cls.groups)

    def test_complete_frozen_matrix_shape(self) -> None:
        self.assertEqual(len(self.groups), 21)
        self.assertEqual(len(self.rows), 63)
        self.assertEqual(
            len({row["case_id"] for row in self.rows if row["official_fresh_20"]}),
            20,
        )

    def test_invalid_ape_does_not_discard_valid_rpe(self) -> None:
        row = next(
            item
            for item in self.rows
            if item["case_id"] == "a05_3300_3700" and item["arm"] == "full"
        )
        self.assertEqual(row["ape_valid"], 0)
        self.assertEqual(row["rpe_valid"], 1)
        self.assertEqual(row["divergent_or_invalid"], 0)

    def test_practical_tie_absorbs_same_bag_replay_jitter(self) -> None:
        rows = e3.comparisons(self.rows, fresh_only=True)
        h02 = next(
            item
            for item in rows
            if item["case_id"] == "h02_2400_2800" and item["comparator"] == "klt"
        )
        self.assertEqual(h02["outcome"], "TIE")

    def test_exact_sign_test(self) -> None:
        self.assertAlmostEqual(e3.exact_sign_test(7, 1), 0.0703125)
        self.assertEqual(e3.exact_sign_test(1, 1), 1.0)
        self.assertIsNone(e3.exact_sign_test(0, 0))

    def test_bootstrap_is_fixed_seed_deterministic(self) -> None:
        rows = e3.sequence_aggregate(
            e3.comparisons(self.rows, fresh_only=True), "klt"
        )
        self.assertEqual(e3.bootstrap_ci(rows), e3.bootstrap_ci(rows))


if __name__ == "__main__":
    unittest.main()
