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

    def test_final_report_passes_all_contracts(self) -> None:
        report = build_report()
        self.assertEqual(report["status"], "PASS", report["issues"])
        self.assertEqual(report["selected_window_count"], 20)
        self.assertEqual(report["issues"], [])

    def test_all_selected_windows_have_full_reference_support(self) -> None:
        report = build_report()
        support = report["selected_reference_support"]
        self.assertEqual(len(support), 20)
        self.assertTrue(all(row["pass"] for row in support))


if __name__ == "__main__":
    unittest.main()
