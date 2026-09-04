#!/usr/bin/env python3

import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from scripts import (
    audit_hfnet_v6_a05_0001_3700_score_3300_3700_input_v1 as subject,
)


class A05IndependentAuditorTests(unittest.TestCase):
    def test_duplicate_json_key_is_rejected(self):
        with self.assertRaisesRegex(subject.AuditError, "JSON_DUPLICATE_KEY"):
            subject.load_json_unique(b'{"status":"PASS","status":"FAIL"}', "TEST")

    def test_source_camera_selection_is_index_exact(self):
        payload = (
            subject.IMAGE_CSV_HEADER
            + "\n10,frame000000.png\n20,frame000001.png\n30,frame000002.png\n"
        ).encode()
        rows, selected = subject.parse_source_camera(
            payload, source_count=3, first=1, last=2
        )
        self.assertEqual(rows, [(10, "frame000000.png"), (20, "frame000001.png"), (30, "frame000002.png")])
        self.assertEqual(selected, rows[1:])

    def test_source_imu_derivation_preserves_measurement_tokens(self):
        camera = [(25, "frame000001.png"), (35, "frame000002.png")]
        payload = (
            subject.IMU_CSV_HEADER
            + "\n10,1,2,3,4,5,6\n20,7,8,9,10,11,12\n"
            + "30,13,14,15,16,17,18\n40,19,20,21,22,23,24\n"
        ).encode()
        _, selected = subject.parse_source_imu(
            payload,
            camera,
            source_count=4,
            first_index=1,
            last_index=3,
            shift_ns=0,
        )
        self.assertEqual([row[0] for row in selected], [20, 30, 40])
        self.assertEqual(selected[0][1], ("7", "8", "9", "10", "11", "12"))
        self.assertEqual(
            subject.imu_csv_bytes(selected, shift_ns=5).splitlines()[1],
            b"25,7,8,9,10,11,12",
        )

    def test_manifest_selection_is_exact_and_tamper_fails(self):
        valid = subject.expected_manifest_selection()
        subject.validate_manifest_selection(valid)
        tampered = json.loads(json.dumps(valid))
        tampered["score_relative_indices_inclusive"] = [3300, 3699]
        with self.assertRaisesRegex(subject.AuditError, "MANIFEST_SELECTION_MISMATCH"):
            subject.validate_manifest_selection(tampered)

    def test_tree_closure_rejects_extra_file_and_symlink(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
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
            (root / "unexpected").write_bytes(b"x")
            with self.assertRaisesRegex(subject.AuditError, "OUTPUT_FILE_SET_MISMATCH"):
                subject.require_tree_closure(root, expected)
            (root / "unexpected").unlink()
            (root / "link").symlink_to(root / "cam0_times.txt")
            with self.assertRaisesRegex(subject.AuditError, "OUTPUT_SYMLINK"):
                subject.require_tree_closure(root, expected)

    def test_every_camera_requires_predecessor_and_successor(self):
        header = subject.IMU_CSV_HEADER
        payload = (
            header
            + "\n10,1,2,3,4,5,6\n20,1,2,3,4,5,6\n"
            + "30,1,2,3,4,5,6\n40,1,2,3,4,5,6"
        ).encode()
        with mock.patch.object(subject, "IMU_COUNT", 4), mock.patch.object(
            subject, "IMU_ENDPOINTS", (10, 20, 30, 40)
        ):
            valid = subject.validate_imu_brackets(payload, [15, 35])
            self.assertTrue(valid["all_camera_samples_have_predecessor_and_successor"])
            with self.assertRaisesRegex(subject.AuditError, "NOT_BRACKETED"):
                subject.validate_imu_brackets(payload, [15, 45])

    def test_receipt_write_is_no_clobber(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "receipt.json"
            subject.write_exclusive(path, b"first")
            with self.assertRaisesRegex(subject.AuditError, "NO_CLOBBER"):
                subject.write_exclusive(path, b"second")
            self.assertEqual(path.read_bytes(), b"first")


if __name__ == "__main__":
    unittest.main()
