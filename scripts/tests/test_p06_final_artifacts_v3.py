from __future__ import annotations

import unittest

from scripts.validate_p06_final_artifacts_v3 import (
    build_report,
    deterministic_rebuild,
)


class P06FinalArtifactsV3Tests(unittest.TestCase):
    def test_deterministic_rebuild_is_byte_identical(self) -> None:
        result = deterministic_rebuild()
        self.assertTrue(result["pass"], result)

    def test_final_report_preserves_reference_revise(self) -> None:
        report = build_report()
        self.assertEqual(report["status"], "REVISE")
        self.assertEqual(report["selected_window_count"], 20)
        self.assertEqual(len(report["issues"]), 8)

    def test_eight_selected_windows_fail_full_reference_support(self) -> None:
        report = build_report()
        support = report["selected_reference_support"]
        self.assertEqual(len(support), 20)
        failed = {row["window_id"] for row in support if not row["pass"]}
        self.assertEqual(
            failed,
            {
                "afrl:bus_outside:0003",
                "afrl:cemetery:0001",
                "afrl:cemetery:0008",
                "aqualoc_archaeology:A04:0007",
                "aqualoc_archaeology:A09:0003",
                "aqualoc_archaeology:A10:0014",
                "aqualoc_harbor:H02:0006",
                "ntnu:fjord_6:0011",
            },
        )


if __name__ == "__main__":
    unittest.main()
