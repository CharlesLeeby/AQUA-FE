from __future__ import annotations

import unittest
from collections import Counter

from scripts.build_p07_frontend_export_queue_v1 import (
    B1,
    D_ARM,
    EXPORT_ARMS,
    M_ARM,
    P_ARM,
    build_rows,
    family_args,
    modern_args,
)


class P07FrontendExportQueueV1Tests(unittest.TestCase):
    def test_queue_is_exactly_20_by_three_and_export_only(self) -> None:
        exports, d_rows, _lock = build_rows()
        self.assertEqual(len(exports), 60)
        self.assertEqual(Counter(row["arm"] for row in exports), {arm: 20 for arm in EXPORT_ARMS})
        self.assertTrue(all("RUN_VINS=0" in row["command"] for row in exports))
        self.assertTrue(all("FORCE_EXPORT=1" in row["command"] for row in exports))
        self.assertNotIn(D_ARM, {row["arm"] for row in exports})
        self.assertEqual(len(d_rows), 20)
        self.assertTrue(all(row["applicability"] == "PENDING_APPLICABILITY" for row in d_rows))

    def test_aqualoc_seconds_convert_to_exact_20hz_frames(self) -> None:
        args = family_args(
            {
                "dataset_family": "aqualoc_archaeology",
                "sequence": "A01",
                "window_start_s": "135.0",
                "window_end_s": "180.0",
            }
        )
        self.assertEqual(args, ["aqualoc_archaeology", "A01", "2700", "3600", "2"])
        self.assertEqual(
            modern_args(
                {
                    "dataset_family": "aqualoc_archaeology",
                    "sequence": "A01",
                    "window_start_s": "135.0",
                    "window_end_s": "180.0",
                }
            ),
            ["aqualoc_archaeology", "1", "2700", "3600", "2"],
        )

    def test_bag_resolution_is_exact_for_b1_m_and_deferred_for_p(self) -> None:
        exports, _d_rows, _lock = build_rows()
        for row in exports:
            if row["arm"] in {B1, M_ARM}:
                self.assertEqual(row["feature_bag_resolution"], "EXACT_PATH")
                self.assertTrue(str(row["expected_feature_bag"]).endswith("/features.bag"))
            elif row["arm"] == P_ARM:
                self.assertEqual(
                    row["feature_bag_resolution"],
                    "READ_FINAL_RUN_FROM_ARBITRATION_SUMMARY_UNDER_TAG_BASE",
                )
                self.assertEqual(row["expected_feature_bag"], "")


if __name__ == "__main__":
    unittest.main()
