from __future__ import annotations

import unittest

from scripts.build_nativeq_legacy_method_lock_v4 import (
    build_payload,
    method_payload_hash,
)


class NativeQualityMethodLockV4Tests(unittest.TestCase):
    def test_guarded_lock_is_additive_and_self_consistent(self) -> None:
        payload = build_payload()
        self.assertEqual(payload["scientific_method_identity"], "UNCHANGED_FROM_V3")
        self.assertFalse(payload["guard_policy"]["fallback_counts_as_proposed_result"])
        self.assertTrue(payload["guard_policy"]["reused_bag_requires_hash_bound_attestation"])
        self.assertEqual(
            payload["candidate_lock_hash"], method_payload_hash(payload)
        )


if __name__ == "__main__":
    unittest.main()
