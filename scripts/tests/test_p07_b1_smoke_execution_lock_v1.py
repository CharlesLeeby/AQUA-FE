from __future__ import annotations

import json
import unittest

from scripts.build_p07_b1_smoke_execution_lock_v1 import OUTPUT, build_lock, lock_hash


class P07B1SmokeExecutionLockV1Tests(unittest.TestCase):
    def test_lock_is_single_job_no_trajectory_contract(self) -> None:
        payload = build_lock()
        self.assertEqual(payload["allowed_queue_indices"], [1])
        self.assertEqual(payload["allowed_arms"], ["B1_klt_nativeq_v3"])
        self.assertEqual(payload["queue_item"]["expected_feature_frames"], 450)
        self.assertEqual(payload["queue_item"]["expected_raw_images"], 901)
        self.assertFalse(payload["held_out_frontend_outcome_read"])
        self.assertFalse(payload["held_out_trajectory_outcome_read"])
        self.assertEqual(payload["execution_lock_hash"], lock_hash(payload))

    def test_written_lock_matches_rebuild_when_prestart(self) -> None:
        if OUTPUT.exists():
            observed = json.loads(OUTPUT.read_text(encoding="utf-8"))
            self.assertEqual(observed["execution_lock_hash"], lock_hash(observed))
            self.assertEqual(observed["status"], "FROZEN_READY_FOR_SINGLE_B1_SMOKE")
            self.assertEqual(observed["queue_item"]["queue_index"], 1)


if __name__ == "__main__":
    unittest.main()
