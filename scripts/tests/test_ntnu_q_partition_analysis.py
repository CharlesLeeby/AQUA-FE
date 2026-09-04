from __future__ import annotations

import unittest

from scripts.build_ntnu_q_partition_analysis import summarize_replays


class NtnuQualityPartitionAnalysisTests(unittest.TestCase):
    def test_technical_replays_are_reduced_without_inflating_scientific_n(self) -> None:
        rows = []
        values = {
            "native_learned": [0.04, 0.05, 0.06],
            "kltq1_only": [0.06, 0.07, 0.08],
            "gfttq1_only": [0.10, 0.11, 20.0],
            "baseq1_xfeatnative": [10.0, 10.0, 10.0],
            "globalq1_learned": [10.0, 10.0, 10.0],
        }
        for arm_key, replay_values in values.items():
            for replay, value in enumerate(replay_values, start=1):
                rows.append(
                    {
                        "arm_key": arm_key,
                        "replay": replay,
                        "ape_rmse_m": value * 2,
                        "rpe_rmse_m": value,
                    }
                )
        summary = {row["arm_key"]: row for row in summarize_replays(rows)}
        self.assertEqual(summary["gfttq1_only"]["rpe_median_m"], 0.11)
        self.assertEqual(summary["gfttq1_only"]["rpe_max_m"], 20.0)
        self.assertEqual(summary["gfttq1_only"]["technical_replays"], 3)
        self.assertEqual(summary["gfttq1_only"]["scientific_units"], 1)

    def test_missing_replay_fails_closed(self) -> None:
        rows = [
            {
                "arm_key": "native_learned",
                "replay": replay,
                "ape_rmse_m": 0.1,
                "rpe_rmse_m": 0.1,
            }
            for replay in (1, 2)
        ]
        with self.assertRaises(ValueError):
            summarize_replays(rows)


if __name__ == "__main__":
    unittest.main()
