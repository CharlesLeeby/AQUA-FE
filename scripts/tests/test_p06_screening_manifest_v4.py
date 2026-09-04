from __future__ import annotations

import unittest
from collections import Counter

from scripts.build_p06_screening_manifest_v4 import build_selection, validate_inputs


class P06ScreeningManifestV4Tests(unittest.TestCase):
    def test_attempt02_and_reference_table_are_hash_bound(self) -> None:
        support = validate_inputs()
        self.assertEqual(len(support), 171)

    def test_full_reference_repair_produces_diverse_10_plus_10(self) -> None:
        _rows, selected, progress = build_selection()
        self.assertEqual(
            Counter(row["texture_stratum"] for row in selected),
            {"low": 10, "normal": 10},
        )
        self.assertEqual(progress["selected_low_sequence_count"], 8)
        self.assertEqual(progress["selected_normal_sequence_count"], 10)
        self.assertGreaterEqual(progress["selected_domain_count"], 3)

    def test_every_selected_window_has_full_reference_grid(self) -> None:
        _rows, selected, _progress = build_selection()
        for row in selected:
            self.assertEqual(row["full_reference_support"], "true")
            self.assertEqual(
                int(row["reference_supported_grid_count"]),
                int(row["reference_grid_count"]),
            )

    def test_score_and_tier_contract_remains_v3(self) -> None:
        _rows, selected, _progress = build_selection()
        for row in selected:
            score = float(row["score"])
            if row["selection_tier"] == "ABSOLUTE_LOW":
                self.assertGreaterEqual(score, 0.17)
            elif row["selection_tier"] == "RELATIVE_Q80_FALLBACK":
                self.assertGreater(score, 0.10)
                self.assertLess(score, 0.17)
            else:
                self.assertEqual(row["selection_tier"], "STRICT_NORMAL")
                self.assertLessEqual(score, 0.10)


if __name__ == "__main__":
    unittest.main()
