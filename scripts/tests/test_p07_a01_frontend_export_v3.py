from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from scripts.audit_p07_a01_frontend_export_v3 import (
    AuditViolation,
    allocation_row,
    expected_raw_bag,
    queue_row,
    validate_guard,
)
from scripts.build_p07_preoutcome_governance_v1 import B1, M_ARM, P_ARM


class P07A01FrontendExportV3Tests(unittest.TestCase):
    def test_queue_rows_are_exact_frozen_a01_order(self) -> None:
        rows = [queue_row(index) for index in (4, 5, 6)]
        self.assertEqual([row["arm"] for row in rows], [B1, P_ARM, M_ARM])
        self.assertEqual(
            [row["command_sha256"] for row in rows],
            [
                "5b5c191fd030dc78332bbbfc7c944abcf74c7fcbdadd8552e2f20153542a7f9c",
                "64139dac1e29bbb3b4a0602419d30d4d991f485b48519069e325beb8d03982ae",
                "fb6209732dcbf7c0201759d0bc854fd1a5607458cd69fe3a7de98457d9f20fa1",
            ],
        )
        self.assertTrue(all(row["window_id"] == "aqualoc_archaeology:A01:0018" for row in rows))

    def test_raw_bag_path_is_exact_a01_window_cache(self) -> None:
        row = queue_row(4)
        path = expected_raw_bag(row, allocation_row(4))
        self.assertEqual(
            str(path),
            "/home/ma/AQUA-FE_WS/datasets/aqualoc/rosbags/archaeo01_16200_17100.bag",
        )

    def test_b1_guard_rejects_non_allow_action(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "decision.json"
            path.write_text(
                json.dumps(
                    {
                        "schema_version": "aqua-fe-b1-klt-nativeq-guard-decision-v1",
                        "action": "REJECT_B1_KLT_NATIVEQ",
                        "contract_hash": "wrong",
                        "contract_pass": False,
                        "counts_as_b1": False,
                        "counts_as_proposed_result": False,
                        "result_label": "B1_CONTRACT_REJECTED",
                        "reasons": ["drift"],
                    }
                ),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(AuditViolation, "exact frozen PASS"):
                validate_guard(path, B1)


if __name__ == "__main__":
    unittest.main()
