from __future__ import annotations

import unittest

from scripts.validate_p06_final_freeze_v1 import build_report


class P06FinalFreezeValidationV1Tests(unittest.TestCase):
    def test_published_freeze_rebuilds_exactly(self) -> None:
        report = build_report()
        self.assertEqual(report["status"], "PASS", report["issues"])
        self.assertEqual(report["issues"], [])
        self.assertEqual(report["dataset_checksum_entry_count"], 41)
        self.assertEqual(report["arm_order_row_count"], 100)
        self.assertTrue(
            all(
                row["byte_identical_to_rebuild"]
                for row in report["published_artifacts"].values()
            )
        )


if __name__ == "__main__":
    unittest.main()
