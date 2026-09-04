#!/usr/bin/env python3
"""Synthetic-only tests for the column-order bridge."""

from __future__ import annotations

import tempfile
import json
import unittest
from pathlib import Path
from unittest.mock import patch

import cv2
import numpy as np

from scripts import bridge_hfnet_world_body_to_vins_csv_v1 as bridge
from scripts import evaluate_vins_common_support as evaluator


def make_run_result(root: Path, source: Path) -> Path:
    source_identity = bridge.file_identity(source)
    value = {
        "schema_version": bridge.V4_RESULT_SCHEMA,
        "status": "PASS_LONG1801_HEADLESS_SCORE_TRAJECTORY_GATE",
        "return_code": 0,
        "evaluable": True,
        "execution": {"command_started": True, "process_start_count": 1, "raw_returncode": 0, "timed_out": False},
        "gate": {"trajectory": {"gate_pass": True, "identity": source_identity}, "keyframe_trajectory": {"gate_pass": True, "identity": {"path": "/synthetic/keyframes", "size_bytes": 1, "sha256": "0" * 64}}},
        "immutables": {"profile_sha256": "1" * 64},
    }
    path = root / "run_result.json"
    path.write_bytes(bridge.canonical_json(value))
    return path


class BridgeTests(unittest.TestCase):
    def setUp(self) -> None:
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)

    def test_reorders_only_quaternion_and_canonicalises_integral_ns(self) -> None:
        source = self.root / "trajectory.txt"
        source.write_text("1542829061692686528.000000 1.00 -2 3e0 0.1 0.2 0.3 0.9273618495\n1542829061742686528 4 5 6 0 0 0 1\n", encoding="ascii")
        rows = bridge.parse_rows(source)
        expected = b"1542829061692686528,1.00,-2,3e0,0.9273618495,0.1,0.2,0.3\n1542829061742686528,4,5,6,1,0,0,0\n"
        self.assertEqual(bridge.csv_bytes(rows), expected)
        output = self.root / "trajectory.csv"
        bridge.write_exclusive(output, expected)
        loaded = evaluator.load_vins_body_csv(output)
        self.assertEqual(len(loaded.stamps), 2)
        np.testing.assert_allclose(loaded.positions[0], [1.0, -2.0, 3.0])
        np.testing.assert_allclose(loaded.quaternions_xyzw[0], [0.1, 0.2, 0.3, 0.9273618495])

    def test_fractional_nanosecond_and_nonunit_quaternion_fail(self) -> None:
        fractional = self.root / "fractional.txt"
        fractional.write_text("1.5 0 0 0 0 0 0 1\n", encoding="ascii")
        with self.assertRaisesRegex(bridge.BridgeError, "TIMESTAMP_NOT_INTEGER_NS"):
            bridge.parse_rows(fractional)
        bad_q = self.root / "bad_q.txt"
        bad_q.write_text("1 0 0 0 0 0 0 2\n", encoding="ascii")
        with self.assertRaisesRegex(bridge.BridgeError, "INVALID_QUATERNION_NORM"):
            bridge.parse_rows(bad_q)

    def test_output_is_no_clobber(self) -> None:
        output = self.root / "existing.csv"
        output.write_bytes(b"owner data")
        with self.assertRaises(FileExistsError):
            bridge.write_exclusive(output, b"replacement")
        self.assertEqual(output.read_bytes(), b"owner data")

    def test_convert_emits_hash_manifest_and_refuses_second_publication(self) -> None:
        source = self.root / "trajectory.txt"
        source.write_text("1000000000.000000 1 2 3 0 0 0 1\n2000000000.000000 4 5 6 0 0 0 1\n", encoding="ascii")
        output = self.root / "trajectory.csv"
        run_result = make_run_result(self.root, source)
        result = bridge.convert(source, output, run_result)
        manifest_path = Path(str(output) + ".manifest.json")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(manifest["source"]["sha256"], bridge.file_identity(source)["sha256"])
        self.assertEqual(manifest["output"]["sha256"], bridge.file_identity(output)["sha256"])
        self.assertFalse(manifest["semantics"]["timestamp_numeric_value_changed"])
        self.assertTrue(manifest["semantics"]["pose_numeric_tokens_preserved_byte_for_byte_modulo_delimiter_and_quaternion_column_order"])
        self.assertTrue(manifest["semantics"]["timestamp_text_canonicalised_from_exact_integral_decimal_to_integer"])
        self.assertTrue(manifest["v4_run_result"]["trajectory_source_identity_match"])
        with self.assertRaisesRegex(bridge.BridgeError, "OUTPUT_OR_MANIFEST_ALREADY_EXISTS"):
            bridge.convert(source, output, run_result)

    def test_convert_reads_source_inode_once_for_payload_and_manifest_hash(self) -> None:
        source = self.root / "trajectory_once.txt"
        source.write_text("1000000000.000000 1 2 3 0 0 0 1\n2000000000.000000 4 5 6 0 0 0 1\n", encoding="ascii")
        output = self.root / "trajectory_once.csv"
        run_result = make_run_result(self.root, source)
        original = bridge.read_regular_once
        source_reads = []

        def counted(path):
            if path == source:
                source_reads.append(path)
            return original(path)

        with patch.object(bridge, "read_regular_once", side_effect=counted):
            bridge.convert(source, output, run_result)
        self.assertEqual(source_reads, [source])

    def test_manifest_publication_failure_rolls_back_owned_output_inode(self) -> None:
        source = self.root / "trajectory_cleanup.txt"
        source.write_text("1000000000 1 2 3 0 0 0 1\n2000000000 4 5 6 0 0 0 1\n", encoding="ascii")
        output = self.root / "trajectory_cleanup.csv"
        run_result = make_run_result(self.root, source)
        original = bridge.write_exclusive

        def fail_manifest(path, payload):
            if path == Path(str(output) + ".manifest.json"):
                raise OSError("synthetic manifest publication failure")
            return original(path, payload)

        with patch.object(bridge, "write_exclusive", side_effect=fail_manifest):
            with self.assertRaisesRegex(OSError, "synthetic manifest"):
                bridge.convert(source, output, run_result)
        self.assertFalse(output.exists())
        self.assertFalse(Path(str(output) + ".manifest.json").exists())

    def test_same_content_competing_owner_is_never_deleted(self) -> None:
        source = self.root / "trajectory_race.txt"
        source.write_text("1000000000 1 2 3 0 0 0 1\n2000000000 4 5 6 0 0 0 1\n", encoding="ascii")
        output = self.root / "trajectory_race.csv"
        run_result = make_run_result(self.root, source)
        expected = bridge.csv_bytes(bridge.parse_rows(source))
        original = bridge.write_exclusive

        def competing_publication(path, payload):
            if path == output:
                path.write_bytes(payload)
                raise FileExistsError("synthetic competing owner won")
            return original(path, payload)

        with patch.object(bridge, "write_exclusive", side_effect=competing_publication):
            with self.assertRaisesRegex(FileExistsError, "competing owner"):
                bridge.convert(source, output, run_result)
        self.assertEqual(output.read_bytes(), expected)
        self.assertFalse(Path(str(output) + ".manifest.json").exists())

    def test_replacement_after_v4_gate_is_rejected_by_identity(self) -> None:
        source = self.root / "trajectory_replaced.txt"
        source.write_text("1000000000 1 2 3 0 0 0 1\n2000000000 4 5 6 0 0 0 1\n", encoding="ascii")
        run_result = make_run_result(self.root, source)
        source.write_text("1000000000 7 8 9 0 0 0 1\n2000000000 4 5 6 0 0 0 1\n", encoding="ascii")
        with self.assertRaisesRegex(bridge.BridgeError, "V4_TRAJECTORY_IDENTITY_MISMATCH"):
            bridge.convert(source, self.root / "rejected.csv", run_result)

    def test_frozen_config_contains_only_body_T_cam0_and_matches_official(self) -> None:
        root = Path(__file__).resolve().parents[2]
        frozen_path = root / "configs/published_baselines/hfnet_aqualoc_a02_body_T_cam0_v1.yaml"
        official_path = root / "configs/published_baselines/hfnet_slam_aqualoc_a02_0005.yaml"
        text = frozen_path.read_text(encoding="utf-8")
        self.assertEqual(text.count("body_T_cam0:"), 1)
        self.assertNotIn("Camera.", text)
        self.assertNotIn("IMU.", text)
        frozen = evaluator.load_body_t_sensor(frozen_path)
        storage = cv2.FileStorage(str(official_path), cv2.FILE_STORAGE_READ)
        try:
            official = storage.getNode("IMU.T_b_c1").mat()
        finally:
            storage.release()
        np.testing.assert_array_equal(frozen, np.asarray(official, dtype=float))


if __name__ == "__main__":
    unittest.main()
