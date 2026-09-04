from __future__ import annotations

import json
import unittest

from scripts.build_p07_preoutcome_governance_v1 import (
    ANALYSIS_LOCK,
    ALLOCATION_CSV,
    SPLIT_CSV,
    SPLIT_JSON,
    build_allocation_rows,
    build_outputs,
    build_split_rows,
)


class P07PreoutcomeGovernanceV1Tests(unittest.TestCase):
    def test_split_identity_is_honestly_classified(self) -> None:
        rows, summary = build_split_rows()
        self.assertEqual(len(rows), 20)
        self.assertEqual(summary["selected_sequences"], 15)
        self.assertEqual(summary["sequence_unseen_low_windows"], 0)
        self.assertEqual(summary["sequence_unseen_normal_windows"], 1)
        self.assertEqual(summary["external_held_out_windows"], 0)
        self.assertFalse(any(row["selected_interval_overlaps_history"] == "true" for row in rows))
        unseen = [row for row in rows if row["corrected_split_role"].startswith("SEQUENCE_UNSEEN")]
        self.assertEqual([(row["dataset_family"], row["sequence"]) for row in unseen], [("aqualoc_harbor", "H03")])

    def test_frontend_allocations_are_unique_and_complete(self) -> None:
        rows, _queue_hash = build_allocation_rows()
        self.assertEqual(len(rows), 60)
        self.assertEqual(len({row["run_id"] for row in rows}), 60)
        self.assertTrue(all(row["status"] == "PLANNED" for row in rows))
        self.assertTrue(all(row["backend_replay"] == "b00" for row in rows))

    def test_analysis_lock_is_rpe_primary_and_narrowed(self) -> None:
        payload = json.loads(build_outputs()[ANALYSIS_LOCK])
        self.assertEqual(
            payload["metrics"]["primary"],
            "G0_common_support_exact_1s_translation_RPE_RMSE",
        )
        self.assertEqual(payload["execution"]["base_backend_replays"], 240)
        self.assertEqual(payload["execution"]["maximum_backend_replays"], 300)
        self.assertEqual(
            payload["hypotheses"]["H2_source_specificity"]["status"],
            "NOT_APPLICABLE_CARRIER_FEEDBACK",
        )
        self.assertIn("C_legacy_independent_classical_v3", payload["arms"]["retired_no_slots"])

    def test_written_machine_artifacts_rebuild_byte_identically(self) -> None:
        outputs = build_outputs()
        for path in (SPLIT_CSV, SPLIT_JSON, ALLOCATION_CSV, ANALYSIS_LOCK):
            if path.exists():
                self.assertEqual(path.read_bytes(), outputs[path], path)


if __name__ == "__main__":
    unittest.main()
