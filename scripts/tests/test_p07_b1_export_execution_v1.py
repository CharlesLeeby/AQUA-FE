from __future__ import annotations

import hashlib
import unittest

from scripts.audit_p07_b1_frontend_export_v1 import allocation_row, manifest_row, queue_row
from scripts.run_p07_frontend_export_job_v1 import capacity_report, target_collisions


class P07B1ExportExecutionV1Tests(unittest.TestCase):
    def test_queue_index_1_is_exact_frozen_b1_smoke(self) -> None:
        row = queue_row(1)
        allocation = allocation_row(1)
        manifest = manifest_row(row["window_id"])
        self.assertEqual(row["window_id"], "aqualoc_archaeology:A02:0005")
        self.assertEqual(row["arm"], "B1_klt_nativeq_v3")
        self.assertEqual(allocation["window_start"], "4500")
        self.assertEqual(allocation["window_end"], "5400")
        self.assertEqual(manifest["input_frame_count"], "900")
        self.assertEqual(
            hashlib.sha256(row["command"].encode("utf-8")).hexdigest(),
            row["command_sha256"],
        )

    def test_preflight_reports_capacity_and_no_collision_before_smoke(self) -> None:
        row = queue_row(1)
        report = capacity_report(row)
        self.assertIn("output_pass", report)
        self.assertIn("governance_pass", report)
        collisions = target_collisions(row)
        self.assertIsInstance(collisions, list)


if __name__ == "__main__":
    unittest.main()
