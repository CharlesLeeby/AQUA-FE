from __future__ import annotations

import json
import unittest

from scripts.build_p07_a01_d_resolution_lock_v1 import OUTPUT, build_lock, lock_hash
from scripts.resolve_p07_a01_d_applicability_v1 import build_terminal_row


class P07A01DResolutionV1Tests(unittest.TestCase):
    def payload(self) -> dict:
        if OUTPUT.exists():
            return json.loads(OUTPUT.read_text(encoding="utf-8"))
        return build_lock()

    def test_lock_allows_only_zero_lineage_not_applicable_append(self) -> None:
        payload = self.payload()
        self.assertEqual(payload["slot_index"], 3)
        self.assertEqual(payload["parent_p"]["accepted_learned_born_lineage_count"], 0)
        self.assertEqual(payload["parent_p"]["zero_action_identity"], "PASS_BYTE_IDENTICAL_TO_B1")
        self.assertEqual(
            payload["parent_p"]["p_feature_bag_sha256"],
            payload["parent_p"]["b1_feature_bag_sha256"],
        )
        self.assertEqual(payload["terminal_contract"]["resolution"], "NOT_APPLICABLE")
        self.assertEqual(len(payload["parent_runs"]), 3)
        self.assertFalse(payload["held_out_trajectory_outcome_read"])
        self.assertEqual(payload["resolution_lock_hash"], lock_hash(payload))

    def test_terminal_row_preserves_identity_and_sets_zero(self) -> None:
        pending = self.payload()["pending_row"]
        terminal = build_terminal_row(
            pending,
            resolution_time="2026-08-07T02:00:00+08:00",
            resolver_hash="locked",
        )
        self.assertEqual(terminal["sequence"], "A01")
        self.assertEqual(terminal["accepted_lineage_count"], "0")
        self.assertEqual(terminal["resolution"], "NOT_APPLICABLE")
        self.assertEqual(terminal["resolver_hash"], "locked")


if __name__ == "__main__":
    unittest.main()
