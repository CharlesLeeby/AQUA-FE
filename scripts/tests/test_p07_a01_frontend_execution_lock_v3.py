from __future__ import annotations

import json
import unittest

from scripts.build_p07_a01_frontend_execution_lock_v3 import OUTPUT, build_lock, lock_hash


class P07A01FrontendExecutionLockV3Tests(unittest.TestCase):
    def payload(self) -> dict:
        if OUTPUT.exists():
            return json.loads(OUTPUT.read_text(encoding="utf-8"))
        return build_lock()

    def test_lock_is_exact_a01_b1_p_m_export_only_contract(self) -> None:
        payload = self.payload()
        self.assertEqual(payload["allowed_queue_indices"], [4, 5, 6])
        self.assertEqual(payload["execution_order"], [4, 5, 6])
        self.assertEqual(
            payload["allowed_arms"],
            [
                "B1_klt_nativeq_v3",
                "P_legacy_nativeq_xfeat_seedchain_v3",
                "M_xfeat_pairwise_nativeq_v1",
            ],
        )
        self.assertEqual(payload["raw_bag_contract"]["expected_images"], 901)
        self.assertFalse(payload["raw_bag_contract"]["preexisting_at_freeze"])
        self.assertFalse(payload["held_out_trajectory_outcome_read"])
        self.assertEqual(payload["execution_lock_hash"], lock_hash(payload))

    def test_lock_binds_prior_a02_closeout_and_d_slot_3(self) -> None:
        payload = self.payload()
        self.assertEqual(payload["dependencies"]["a02_d_resolution"], "NOT_APPLICABLE")
        self.assertEqual(payload["dependencies"]["queue_5_completion_gates_d_slot"], 3)
        self.assertEqual(
            [item["expected_feature_frames"] for item in payload["queue_items"]],
            [450, 450, 450],
        )


if __name__ == "__main__":
    unittest.main()
