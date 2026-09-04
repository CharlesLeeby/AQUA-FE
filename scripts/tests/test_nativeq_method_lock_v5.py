from __future__ import annotations

import unittest

from scripts.build_nativeq_legacy_method_lock_v5 import build_payload, method_payload_hash


class NativeQMethodLockV5Tests(unittest.TestCase):
    def test_v5_is_narrowed_v3_not_new_scientific_method(self) -> None:
        payload = build_payload()
        self.assertEqual(payload["scientific_method_identity"], "UNCHANGED_FROM_V3")
        self.assertEqual(
            payload["p04_stage_disposition"],
            "PASS_WITH_H2_NOT_APPLICABLE_CARRIER_FEEDBACK",
        )

    def test_v5_arm_matrix_is_exact(self) -> None:
        arms = build_payload()["arms"]
        self.assertEqual(len(arms["required_every_window"]), 4)
        self.assertEqual(
            arms["conditional_before_trajectory_outcome"],
            ["D_legacy_exact_lineage_drop_v3"],
        )
        self.assertNotIn(
            "C_legacy_independent_classical_v3", arms["required_every_window"]
        )
        self.assertNotIn("B2_all_eligible", arms["required_every_window"])

    def test_v5_hash_is_self_consistent(self) -> None:
        payload = build_payload()
        self.assertEqual(method_payload_hash(payload), payload["candidate_lock_hash"])


if __name__ == "__main__":
    unittest.main()
