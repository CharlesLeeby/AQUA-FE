from __future__ import annotations

import unittest

from scripts.build_p07_execution_adapter_lock_v1 import (
    B0,
    B1,
    D_ARM,
    M_ARM,
    P_ARM,
    adapter_hash,
    build_payload,
)


class P07ExecutionAdapterLockV1Tests(unittest.TestCase):
    def test_all_final_arms_have_explicit_entrypoints(self) -> None:
        payload = build_payload()
        self.assertEqual(set(payload["entrypoints"]), {B0, B1, P_ARM, M_ARM, D_ARM})
        self.assertEqual(payload["scientific_identity_change"], "NONE_ADDITIVE_EXECUTION_PROVENANCE_ONLY")

    def test_b0_b1_guards_pass_and_hash_is_consistent(self) -> None:
        payload = build_payload()
        self.assertEqual(payload["guard_decisions"][B0]["action"], "ALLOW_B0_NATIVE")
        self.assertEqual(payload["guard_decisions"][B1]["action"], "ALLOW_B1_KLT_NATIVEQ")
        self.assertEqual(adapter_hash(payload), payload["adapter_lock_hash"])


if __name__ == "__main__":
    unittest.main()
