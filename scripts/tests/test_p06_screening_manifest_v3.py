from __future__ import annotations

import unittest
from collections import Counter

from scripts.build_p06_screening_manifest_v3 import (
    OUTCOME_BOUNDARY,
    build_selection,
    validate_inputs,
)


class P06ScreeningManifestV3Tests(unittest.TestCase):
    def test_attempt01_is_hash_bound_and_outcome_blind(self) -> None:
        fields, rows, progress = validate_inputs()
        self.assertEqual(len(rows), 156)
        self.assertEqual(progress["status"], "REVISE")
        self.assertEqual(progress["outcome_boundary"], OUTCOME_BOUNDARY)
        lowered = " ".join(fields).lower()
        for token in ("learned", "xfeat", "trajectory", "ape", "rpe", "vins"):
            self.assertNotIn(token, lowered)

    def test_repair_produces_exact_diverse_10_plus_10(self) -> None:
        _rows, selected, progress = build_selection()
        counts = Counter(row["texture_stratum"] for row in selected)
        self.assertEqual(counts, {"low": 10, "normal": 10})
        self.assertGreaterEqual(progress["selected_low_sequence_count"], 6)
        self.assertGreaterEqual(progress["selected_normal_sequence_count"], 6)
        self.assertGreaterEqual(progress["selected_low_domain_count"], 2)
        self.assertGreaterEqual(progress["selected_normal_domain_count"], 2)
        self.assertGreaterEqual(progress["selected_domain_count"], 3)

    def test_low_and_normal_rules_are_disjoint_and_tiered(self) -> None:
        _rows, selected, progress = build_selection()
        low = [row for row in selected if row["texture_stratum"] == "low"]
        normal = [row for row in selected if row["texture_stratum"] == "normal"]
        self.assertTrue(all(float(row["score"]) > 0.10 for row in low))
        self.assertTrue(all(float(row["score"]) <= 0.10 for row in normal))
        self.assertEqual(
            set(progress["selected_tier_counts"]),
            {"ABSOLUTE_LOW", "RELATIVE_Q80_FALLBACK", "STRICT_NORMAL"},
        )

    def test_selected_rows_are_reference_valid_and_history_clean(self) -> None:
        _rows, selected, _progress = build_selection()
        for row in selected:
            self.assertEqual(row["history_excluded"], "false")
            self.assertEqual(row["reference_support_pass"], "true")
            self.assertEqual(row["selected_by_sequence_rule"], "true")


if __name__ == "__main__":
    unittest.main()
