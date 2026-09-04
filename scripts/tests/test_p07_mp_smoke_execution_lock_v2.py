from __future__ import annotations

import json
import unittest

from scripts.build_p07_mp_smoke_execution_lock_v2 import OUTPUT, build_lock, lock_hash


class P07MPSmokeExecutionLockV2Tests(unittest.TestCase):
    def payload(self) -> dict:
        if OUTPUT.exists():
            return json.loads(OUTPUT.read_text(encoding="utf-8"))
        return build_lock()

    def test_lock_is_exact_a02_m_then_p_export_only_contract(self) -> None:
        payload = self.payload()
        self.assertEqual(payload["allowed_queue_indices"], [2, 3])
        self.assertEqual(payload["execution_order"], [2, 3])
        self.assertEqual(
            payload["allowed_arms"],
            ["M_xfeat_pairwise_nativeq_v1", "P_legacy_nativeq_xfeat_seedchain_v3"],
        )
        self.assertEqual(payload["window_id"], "aqualoc_archaeology:A02:0005")
        self.assertTrue(payload["held_out_frontend_outcome_read"])
        self.assertFalse(payload["held_out_trajectory_outcome_read"])
        self.assertEqual(payload["execution_lock_hash"], lock_hash(payload))
        self.assertEqual(
            [item["expected_feature_frames"] for item in payload["queue_items"]],
            [450, 450],
        )

    def test_mutable_streams_are_prefix_snapshots_not_locked_artifacts(self) -> None:
        payload = self.payload()
        mutable = payload["mutable_stream_prefix_snapshots"]
        self.assertEqual(len(mutable), 2)
        self.assertTrue(
            all(item["binding"] == "PREEXECUTION_APPEND_ONLY_PREFIX_SNAPSHOT" for item in mutable)
        )
        immutable_paths = {item["path"] for item in payload["artifacts"]}
        self.assertNotIn("papers/ieee_sensors_journal_experiments/run_registry.csv", immutable_paths)
        self.assertNotIn(
            "papers/ieee_sensors_journal_experiments/arm_applicability.csv",
            immutable_paths,
        )

    def test_b1_failed_event_is_preserved_as_parent_provenance(self) -> None:
        dependency = self.payload()["dependencies"]
        self.assertTrue(dependency["b1_preserved_failed_event_id"].endswith("_e02"))
        self.assertTrue(dependency["b1_required_latest_event_id"].endswith("_e03"))
        self.assertEqual(dependency["b1_required_latest_status"], "COMPLETED")


if __name__ == "__main__":
    unittest.main()
