from __future__ import annotations

import unittest

from scripts.build_p06_window_time_mapping_v2 import filter_support_rows


class P06WindowTimeMappingV2Test(unittest.TestCase):
    def test_excluded_cave_is_removed_without_touching_other_sequences(self) -> None:
        rows = [
            {"dataset_family": "afrl", "sequence": "cave_gennie"},
            {"dataset_family": "afrl", "sequence": "bus_outside"},
            {"dataset_family": "aqualoc_archaeology", "sequence": "A01"},
        ]
        self.assertEqual(filter_support_rows(rows), [rows[1], rows[2]])


if __name__ == "__main__":
    unittest.main()
