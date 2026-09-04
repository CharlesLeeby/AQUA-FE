#!/usr/bin/env python3
"""Process-free tests for the independent A08 input auditor."""

from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from scripts import (
    audit_hfnet_v6_a08_0000_4660_score_4500_4660_input_v1 as subject,
)


class A08IndependentAuditorTests(unittest.TestCase):
    def test_dataset_constants_and_core_binding_are_exact(self) -> None:
        self.assertEqual(
            (subject.SOURCE_CAMERA_FIRST, subject.SOURCE_CAMERA_LAST, subject.CAMERA_COUNT),
            (0, 4660, 4661),
        )
        self.assertEqual(
            (subject.IMU_FIRST_INDEX, subject.IMU_LAST_INDEX, subject.IMU_COUNT),
            (12, 46570, 46559),
        )
        self.assertEqual(subject.core.SOURCE_SHA256, subject.SOURCE_SHA256)
        self.assertIs(subject.core.validate_manifest, subject.validate_manifest)

    def test_selector_is_exact_and_discloses_outcome_selection(self) -> None:
        payload = subject.SELECTOR.read_bytes()
        value = subject.validate_selector(payload)
        self.assertEqual(value["selection"], subject.expected_selector_selection())
        self.assertTrue(value["knowledge_boundary"]["window_is_outcome_selected"])

    def test_manifest_selection_is_exact_and_tamper_fails(self) -> None:
        valid = subject.expected_manifest_selection()
        subject.validate_manifest_selection(valid)
        tampered = json.loads(json.dumps(valid))
        tampered["score_relative_indices_inclusive"] = [4499, 4660]
        with self.assertRaisesRegex(subject.AuditError, "MANIFEST_SELECTION_MISMATCH"):
            subject.validate_manifest_selection(tampered)

    def test_wrapper_audit_repairs_no_scientific_data_and_starts_no_process(self) -> None:
        fake = {
            "auditor": {"sha256": "base"},
            "camera": {"preroll_source_indices_inclusive": [1, 3299]},
            "reporting_boundary": "base",
            "claims": dict(subject.core.CLAIMS),
        }
        with mock.patch.object(subject, "_require_base_auditor_pin"), mock.patch.object(
            subject, "_base_audit", return_value=fake
        ):
            result = subject.audit(Path("root"), Path("source"), Path("selector"), Path("config"))
        self.assertEqual(result["camera"]["preroll_source_indices_inclusive"], [0, 4499])
        self.assertIn("A08", result["reporting_boundary"])
        self.assertFalse(result["claims"]["hfnet_started"])

    def test_tree_closure_and_receipt_are_no_clobber(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "input"
            (root / "mav0/cam0/data").mkdir(parents=True)
            (root / "mav0/imu0").mkdir(parents=True)
            expected = {
                "cam0_times.txt",
                "mav0/cam0/data.csv",
                "mav0/imu0/data.csv",
                "materialization_manifest.json",
            }
            for relative in expected:
                path = root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b"x")
            subject.require_tree_closure(root, expected)
            report = Path(temporary) / "receipt.json"
            subject.write_exclusive(report, b"first")
            with self.assertRaisesRegex(subject.AuditError, "NO_CLOBBER"):
                subject.write_exclusive(report, b"second")


if __name__ == "__main__":
    unittest.main()
