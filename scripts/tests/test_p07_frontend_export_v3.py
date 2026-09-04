from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from scripts import audit_p07_frontend_export_v3 as auditor
from scripts import build_p07_preoutcome_governance_v1 as governance
from scripts import resolve_p07_d_applicability_v2 as resolver
from scripts import run_p07_frontend_queue_v3 as queue_runner


class P07FrontendExportV3Tests(unittest.TestCase):
    def test_generalized_queue_has_twenty_three_arm_triplets(self) -> None:
        rows = [auditor.queue_row(index) for index in range(1, 61)]
        self.assertEqual(len({row["window_id"] for row in rows}), 20)
        for end_index in range(3, 61, 3):
            window = queue_runner.group_window(end_index)
            triplet = rows[end_index - 3 : end_index]
            self.assertEqual({row["window_id"] for row in triplet}, {window})
            self.assertEqual(
                {row["arm"] for row in triplet},
                {governance.B1, governance.M_ARM, governance.P_ARM},
            )

    def test_expected_frames_cover_each_dataset_family(self) -> None:
        expected = {4: 450, 10: 450, 28: 283}
        for index, count in expected.items():
            row = auditor.queue_row(index)
            manifest = auditor.manifest_row(row["window_id"])
            self.assertEqual(
                auditor.expected_feature_frames(manifest, row["dataset_family"]),
                count,
            )
        self.assertEqual(
            set(auditor.SENSOR_TOPIC_REQUIREMENTS),
            {"aqualoc_archaeology", "aqualoc_harbor", "ntnu", "afrl"},
        )

    def test_b1_guard_uses_the_frozen_decision_fields(self) -> None:
        payload = {
            "schema_version": "aqua-fe-b1-klt-nativeq-guard-decision-v1",
            "action": "ALLOW_B1_KLT_NATIVEQ",
            "contract_hash": auditor.B1_CONTRACT_HASH,
            "contract_pass": True,
            "counts_as_b1": True,
            "counts_as_proposed_result": False,
            "result_label": "B1_KLT_NATIVEQ_V3",
            "reasons": [],
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "decision.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            self.assertEqual(
                auditor.validate_guard(path, governance.B1)["action"],
                "ALLOW_B1_KLT_NATIVEQ",
            )
            payload["counts_as_b1"] = False
            path.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaises(auditor.AuditViolation):
                auditor.validate_guard(path, governance.B1)

    def test_p_summary_family_mapping_matches_frozen_runners(self) -> None:
        self.assertEqual(
            auditor.P_SUMMARY_FAMILY,
            {
                "aqualoc_archaeology": "aqualoc_archaeo",
                "aqualoc_harbor": "aqualoc_real",
                "ntnu": "ntnu",
                "afrl": "afrl",
            },
        )

    def test_applicability_match_is_exact_window_identity(self) -> None:
        manifest = auditor.manifest_row("aqualoc_archaeology:A01:0018")
        rows = governance.read_csv(resolver.APPLICABILITY)
        matches = resolver.matching_applicability_rows(rows, manifest)
        self.assertEqual(len(matches), 2)
        self.assertEqual(
            [row["resolution"] for row in matches],
            ["PENDING_APPLICABILITY", "NOT_APPLICABLE"],
        )


if __name__ == "__main__":
    unittest.main()
