from __future__ import annotations

import os
import unittest
from unittest import mock

from scripts import build_p07_frontend_execution_correction_lock_v5 as builder
from scripts import run_p07_frontend_export_job_v5 as runner


class P07FrontendExecutionCorrectionV5Tests(unittest.TestCase):
    def test_clean_environment_remains_nonrecursive(self) -> None:
        with mock.patch.dict(os.environ, {"AQUAFE_DRY_RUN": "1"}, clear=False):
            runner.install_corrected_contract()
            environment = runner.base.clean_environment()
        self.assertNotIn("AQUAFE_DRY_RUN", environment)
        self.assertEqual(environment["VINS_WS"], "/home/ma/SLAM/VINS-Fusion-origin")

    def test_lock_preserves_queue_and_scientific_commands(self) -> None:
        payload = builder.build_lock()
        self.assertEqual(payload["allowed_queue_indices"], list(range(29, 61)))
        self.assertFalse(payload["correction"]["scientific_command_changed"])
        self.assertFalse(payload["queue_28_correction"]["physical_frontend_rerun"])
        self.assertEqual(
            payload["correction"]["afrl_replay_manifest_policy"],
            "EXACT_METADATA_ONLY_WITH_ABSENT_VINS_OUTPUT",
        )


if __name__ == "__main__":
    unittest.main()
