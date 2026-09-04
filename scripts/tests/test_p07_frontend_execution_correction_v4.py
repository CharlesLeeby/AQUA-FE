from __future__ import annotations

import os
import unittest
from unittest import mock

from scripts import run_p07_frontend_export_job_v4 as runner
from scripts import run_p07_frontend_queue_v4 as queue_runner


class P07FrontendExecutionCorrectionV4Tests(unittest.TestCase):
    def test_clean_environment_uses_captured_unpatched_base(self) -> None:
        with mock.patch.dict(
            os.environ,
            {"AQUAFE_GUARD_ONLY": "1", "AQUAFE_DRY_RUN": "1"},
            clear=False,
        ):
            runner.install_corrected_contract()
            environment = runner.base.clean_environment()
        self.assertNotIn("AQUAFE_GUARD_ONLY", environment)
        self.assertNotIn("AQUAFE_DRY_RUN", environment)
        self.assertEqual(environment["VINS_WS"], "/home/ma/SLAM/VINS-Fusion-origin")

    def test_correction_keeps_original_queue_identity(self) -> None:
        row = runner.auditor.queue_row(7)
        allocation = runner.auditor.allocation_row(7)
        self.assertEqual(row["tag"], "isj_p07_aqualoc_harbor_h05_0002_p_attempt01")
        self.assertEqual(row["window_id"], allocation["window_id"])
        self.assertEqual(row["arm"], allocation["arm"])
        self.assertEqual(row["tag"], allocation["tag"])
        self.assertIn("RUN_VINS=0", row["command"])

    def test_completed_a01_d_requires_closeout_evidence(self) -> None:
        self.assertTrue(
            queue_runner.window_is_terminal_complete(
                "aqualoc_archaeology:A01:0018"
            )
        )


if __name__ == "__main__":
    unittest.main()
