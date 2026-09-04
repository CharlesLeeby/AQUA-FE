from __future__ import annotations

import unittest

from scripts import audit_p07_frontend_export_v3 as auditor
from scripts import build_p07_d_resolution_lock_v3 as builder
from scripts import resolve_p07_d_applicability_v3 as resolver


WINDOW = "afrl:bus_outside:0001"


class P07DResolutionV3Tests(unittest.TestCase):
    def test_afrl_v4_p_audit_is_accepted_without_trajectory_access(self) -> None:
        row = next(
            row
            for row in resolver.queue_rows(WINDOW)
            if row["arm"] == "P_legacy_nativeq_xfeat_seedchain_v3"
        )
        path, payload = resolver.load_p_audit(WINDOW, row)
        self.assertEqual(path.name, "audit_v4.json")
        self.assertEqual(payload["learned_lineages"]["accepted_learned_born_lineage_count"], 0)
        self.assertTrue(payload["checks"]["afrl_replay_manifest_metadata_only"])
        self.assertFalse(payload["held_out_trajectory_outcome_read"])

    def test_v3_lock_changes_only_audit_compatibility(self) -> None:
        payload = builder.build_lock(WINDOW)
        self.assertEqual(payload["schema_version"], "isj-p07-d-resolution-lock-v3")
        self.assertFalse(
            payload["audit_compatibility_correction"]["lineage_or_drop_contract_changed"]
        )
        self.assertEqual(
            payload["resolution_lock_hash"], resolver.resolution_lock_hash(payload)
        )


if __name__ == "__main__":
    unittest.main()
