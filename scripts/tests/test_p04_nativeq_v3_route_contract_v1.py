from __future__ import annotations

import unittest

from scripts.build_nativeq_backend_contract import payload_hash
from scripts.build_p04_nativeq_v3_route_contract_v1 import (
    build_payload,
    validate_inputs,
)


class P04NativeQV3RouteContractTests(unittest.TestCase):
    def test_frozen_evidence_validates(self) -> None:
        values = validate_inputs()
        self.assertEqual(
            values["identifiability"]["recommended_disposition"][
                "H2_CONTROL_CONTRACT"
            ],
            "NOT_APPLICABLE_CARRIER_FEEDBACK",
        )

    def test_route_has_no_c_or_b2_slots(self) -> None:
        payload = build_payload()
        arms = payload["arm_contract"]
        self.assertEqual(
            arms["required_every_window"],
            [
                "B0_native_vins_origin_v1",
                "B1_klt_nativeq_v3",
                "P_legacy_nativeq_xfeat_seedchain_v3",
                "M_xfeat_pairwise_nativeq_v1",
            ],
        )
        self.assertEqual(
            arms["conditional_before_trajectory_outcome"],
            ["D_legacy_exact_lineage_drop_v3"],
        )
        self.assertEqual(
            arms["retired_no_slots"],
            ["C_legacy_independent_classical_v3", "B2_all_eligible"],
        )

    def test_contract_hash_is_self_consistent(self) -> None:
        payload = build_payload()
        self.assertEqual(payload_hash(payload), payload["contract_hash"])

    def test_drop_interpretation_is_narrow(self) -> None:
        payload = build_payload()
        text = payload["d_legacy_applicability"]["interpretation"]
        self.assertIn("learned-conditioned carrier", text)
        self.assertIn("not removal of the complete learned frontend", text)


if __name__ == "__main__":
    unittest.main()
