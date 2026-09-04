#!/usr/bin/env python3

from __future__ import annotations

import unittest

from scripts.build_p06_screening_manifest_guarded import (
    reference_aware_build_sequence_windows,
    stable_relative_rows,
)


class P06GuardedBuilderTest(unittest.TestCase):
    def test_duplicate_timestamps_use_frame_index_secondary_key(self) -> None:
        rows = [
            {"timestamp": "10.0", "frame_index": "2"},
            {"timestamp": "10.0", "frame_index": "1"},
            {"timestamp": "10.1", "frame_index": "3"},
        ]
        ordered = stable_relative_rows(rows, 15.0)
        self.assertEqual([row["frame_index"] for _, row in ordered], ["1", "2", "3"])
        for actual, expected in zip((value for value, _ in ordered), (0.0, 0.0, 0.1)):
            self.assertAlmostEqual(actual, expected)

    def test_frame_only_rows_remain_index_ordered(self) -> None:
        rows = [
            {"frame_index": "5"},
            {"frame_index": "3"},
            {"frame_index": "4"},
        ]
        ordered = stable_relative_rows(rows, 20.0)
        self.assertEqual([row["frame_index"] for _, row in ordered], ["3", "4", "5"])
        self.assertEqual([value for value, _ in ordered], [0.0, 0.05, 0.1])

    def test_reference_failure_is_removed_before_scoring(self) -> None:
        rows = [
            {
                "frame_index": str(index),
                "tracker_mode": "klt",
                "grid_coverage": "0.8",
                "dropout_ratio": "0.1",
                "flat_region_ratio": "0.2",
                "degradation_score": "0.3",
            }
            for index in range(6 * 45 * 20)
        ]
        spec = {
            "dataset_family": "aqualoc_archaeology",
            "data_domain": "AQUALOC archaeology",
            "sequence": "A08",
            "gross_nonoverlap_windows": "10",
            "history_overlap_windows": "0",
            "available_candidate_windows": "7",
        }
        windows, _ = reference_aware_build_sequence_windows(spec, rows, [])
        failed = windows[5]
        self.assertEqual(failed["reference_support_pass"], "false")
        self.assertEqual(failed["texture_stratum"], "reference_support_failed")
        self.assertNotIn("score", failed)
        self.assertEqual(failed["selected_by_sequence_rule"], "false")


if __name__ == "__main__":
    unittest.main()
