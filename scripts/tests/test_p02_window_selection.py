#!/usr/bin/env python3

from __future__ import annotations

import unittest

from scripts.p02_window_selection import (
    build_fixed_windows,
    classify_scores,
    linear_quantile,
    score_metric_rows,
    select_within_sequence,
)


class P02WindowSelectionTest(unittest.TestCase):
    def test_type7_quantile_is_deterministic(self) -> None:
        self.assertAlmostEqual(linear_quantile([0, 1, 2, 3], 0.25), 0.75)
        self.assertAlmostEqual(linear_quantile([0, 1, 2, 3], 0.75), 2.25)

    def test_score_uses_only_four_frozen_klt_image_components(self) -> None:
        rows = [
            {
                "grid_coverage": 0.5,
                "dropout_ratio": 0.4,
                "flat_region_ratio": 0.8,
                "degradation_score": 0.6,
                "trajectory_ape": -999,
            }
            for _ in range(4)
        ]
        score = score_metric_rows(rows)
        expected = (0.5 + 0.4 + 0.8 + 0.6) / 4.0
        self.assertAlmostEqual(score.score, expected)

    def test_absolute_and_relative_gates_are_both_required(self) -> None:
        scores = [0.05, 0.18, 0.21, 0.34, 0.41, 0.70]
        self.assertEqual(
            classify_scores(scores),
            ["normal", "unclassified", "unclassified", "unclassified", "low", "low"],
        )

    def test_fixed_windows_are_nonoverlapping_and_require_frame_floor(self) -> None:
        rows = [_metric_row(index) for index in range(900)]
        windows = build_fixed_windows(rows, input_rate_hz=10.0)
        self.assertEqual(len(windows), 2)
        self.assertEqual(windows[0]["window_start_s"], 0.0)
        self.assertEqual(windows[0]["window_end_s"], 45.0)
        self.assertEqual(windows[1]["window_start_s"], 45.0)
        self.assertEqual(windows[1]["window_end_s"], 90.0)
        self.assertEqual(windows[0]["input_frame_count"], 450)

    def test_screening_rejects_learned_track_rows(self) -> None:
        rows = [_metric_row(index) for index in range(450)]
        rows[100]["xfeat_tracks"] = "1"
        with self.assertRaisesRegex(ValueError, "learned track count"):
            build_fixed_windows(rows, input_rate_hz=10.0)

    def test_stable_tie_break_prefers_earlier_start(self) -> None:
        windows = [
            {
                "window_index": index,
                "window_start_s": float(index * 45),
                "score": score,
                "texture_stratum": "low",
            }
            for index, score in enumerate([0.8, 0.8, 0.7])
        ]
        selected = select_within_sequence(windows, max_per_stratum=2)
        self.assertEqual(
            [row["selected_by_sequence_rule"] for row in selected],
            [True, True, False],
        )


def _metric_row(index: int) -> dict[str, str]:
    return {
        "frame_index": str(index),
        "tracker_mode": "klt",
        "grid_coverage": "0.9",
        "dropout_ratio": "0.1",
        "flat_region_ratio": "0.2",
        "degradation_score": "0.1",
        "xfeat_tracks": "0",
        "superpoint_lightglue_tracks": "0",
        "loftr_tracks": "0",
    }


if __name__ == "__main__":
    unittest.main()
