from __future__ import annotations

import unittest

from scripts.build_p06_window_time_mapping_v3 import normalize_runner_start


class P06WindowTimeMappingV3Test(unittest.TestCase):
    def base_row(self, start: float) -> dict[str, object]:
        return {
            "runner_interface": "ROS_BAG_START_OFFSET_AND_DURATION",
            "runner_start": start,
            "runner_end_or_duration": 45.0,
            "absolute_image_end_s": 145.0,
            "raw_bag_end_s": 200.0,
            "mapping_pass": "false",
            "dataset_family": "ntnu",
            "sequence": "fjord_6",
            "window_index": "0",
        }

    def test_small_negative_header_offset_is_clamped(self) -> None:
        row, adjustment = normalize_runner_start(self.base_row(-0.0283))
        self.assertEqual(row["runner_start"], 0.0)
        self.assertEqual(row["mapping_pass"], "true")
        self.assertIsNotNone(adjustment)

    def test_large_negative_offset_remains_failed(self) -> None:
        row, adjustment = normalize_runner_start(self.base_row(-0.5))
        self.assertEqual(row["runner_start"], -0.5)
        self.assertEqual(row["mapping_pass"], "false")
        self.assertIsNone(adjustment)


if __name__ == "__main__":
    unittest.main()
