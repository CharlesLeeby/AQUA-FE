from __future__ import annotations

import unittest

from scripts.validate_p07_frontend_export_queue_v1 import build_report


class P07FrontendQueueValidationV1Tests(unittest.TestCase):
    def test_frozen_queues_rebuild_exactly_without_execution(self) -> None:
        report = build_report(dry_run_all=False)
        self.assertEqual(report["status"], "PASS", report["issues"])
        self.assertEqual(report["frontend_export_jobs"], 60)
        self.assertEqual(report["conditional_d_slots"], 20)
        self.assertTrue(all(report["deterministic_rebuild"].values()))


if __name__ == "__main__":
    unittest.main()
