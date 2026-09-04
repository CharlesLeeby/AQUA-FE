#!/usr/bin/env python3
"""Preparation-only tests for the two CIRS HFNet v6 cold-start inputs."""

from __future__ import annotations

import ast
import json
import os
from pathlib import Path
import tempfile
import unittest

import numpy as np

from scripts import audit_hfnet_v6_cirs_exact_window_coldstart_input_v1 as audit
from scripts import materialize_hfnet_v6_cirs_exact_window_coldstart_v1 as materializer


ROOT = Path(__file__).resolve().parents[2]


class CirsHFNetV6ExactWindowTests(unittest.TestCase):
    def test_frozen_contracts_are_exact_cold_start_windows(self) -> None:
        expected = {
            "cirs_s575_d30": ((2874, 3023), 1372687783674637079, 1372687813476711988, 344),
            "cirs_s900_d30": ((4499, 4648), 1372688108674326896, 1372688138475372076, 348),
        }
        for name, values in expected.items():
            contract = materializer.WINDOWS[name]
            indices, first_ns, last_ns, proxy_count = values
            self.assertEqual(contract.source_indices_inclusive, indices)
            self.assertEqual(contract.camera_count, 150)
            self.assertEqual(contract.camera_endpoints_ns, (first_ns, last_ns))
            self.assertEqual(contract.imu_count, 310)
            self.assertEqual(contract.odometry_proxy_count, proxy_count)
            selector = json.loads(contract.selector.read_text(encoding="utf-8"))
            selection = selector["selection"]
            self.assertTrue(selection["cold_start"])
            self.assertEqual(selection["feed_camera_source_indices_inclusive"], list(indices))
            self.assertEqual(selection["score_camera_source_indices_inclusive"], list(indices))
            self.assertTrue(selector["knowledge_boundary"]["development_result_conditioned_selection"])
            self.assertFalse(selector["knowledge_boundary"]["independent_ground_truth_available"])

    def test_historical_raw_segments_are_explicitly_undistorted_frame_ud_inputs(self) -> None:
        metadata_paths = (
            ROOT / "logs/cirs_caves_vins/external_klt_every1_jul14frozen3way_cirs_s575_d30_klt/raw_segment_meta.json",
            ROOT / "logs/cirs_caves_vins/external_klt_every1_jul14frozen3way_cirs_s900_d30_klt/raw_segment_meta.json",
        )
        for path in metadata_paths:
            metadata = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(Path(metadata["frames"]).name, "undistorted_frames.zip")
            self.assertTrue(metadata["first_image"].startswith("frame_ud_"))
            self.assertTrue(metadata["last_image"].startswith("frame_ud_"))
            self.assertEqual(metadata["image_width"], 384)
            self.assertEqual(metadata["image_height"], 288)
            self.assertEqual(metadata["image_count"], 150)

    def test_extrinsic_is_proper_and_config_keeps_shared_model_path(self) -> None:
        result = materializer.extrinsic_audit()
        transform = np.asarray(result["T_imu_camera"])
        expected = np.array(
            [
                [-1.0, 0.0, 0.0, 0.0],
                [0.0, 1.0, 0.0, -0.16],
                [0.0, 0.0, -1.0, -0.14],
                [0.0, 0.0, 0.0, 1.0],
            ]
        )
        self.assertLess(np.max(np.abs(transform - expected)), 1e-12)
        self.assertAlmostEqual(np.linalg.det(transform[:3, :3]), 1.0, places=12)
        self.assertLess(np.max(np.abs(transform[:3, :3].T @ transform[:3, :3] - np.eye(3))), 1e-12)
        config = materializer.CONFIG.read_text(encoding="utf-8")
        self.assertIn('Extractor.modelPath: "/home/ma/SLAM/HFNet-SLAM-runtime-model-a02-r1/HFNet-RT/"', config)
        self.assertIn("Camera1.fx: 405.6384738851233", config)
        self.assertIn("Camera1.k1: 0.0", config)
        self.assertIn("IMU.Frequency: 10.0", config)
        self.assertIn("ASSUMED_NOT_DATASET_CALIBRATED", config)

    def test_production_preflight_both_windows_creates_nothing(self) -> None:
        with tempfile.TemporaryDirectory(prefix="cirs_hfnet_preflight_test_") as temporary:
            base = Path(temporary)
            for name, contract in materializer.WINDOWS.items():
                output = base / name
                result = materializer.preflight(contract, contract.source_bag, contract.selector, materializer.CONFIG, output)
                self.assertEqual(result["status"], "PREFLIGHT_READY_PREPARATION_ONLY")
                self.assertFalse(output.exists())
                self.assertFalse(result["claims"]["output_created"])
                self.assertFalse(result["claims"]["hfnet_started"])
                self.assertEqual(result["camera_count"], 150)
                self.assertEqual(result["imu_count"], 310)
                self.assertTrue(result["imu_reader_bracket"]["official_reader_bracket_valid"])

    def test_real_materialization_and_independent_audit_both_windows(self) -> None:
        with tempfile.TemporaryDirectory(prefix="cirs_hfnet_materialize_test_") as temporary:
            base = Path(temporary)
            for name in sorted(materializer.WINDOWS):
                contract = materializer.WINDOWS[name]
                output = base / name
                manifest = materializer.materialize(contract, contract.source_bag, contract.selector, materializer.CONFIG, output)
                report = audit.audit(audit.CONTRACTS[name], output, contract.source_bag, contract.selector, audit.CONFIG)
                self.assertEqual(manifest["status"], "PASS_PREPARATION_ONLY")
                self.assertEqual(report["status"], "PASS_PREPARATION_ONLY_INDEPENDENT_AUDIT")
                self.assertFalse(manifest["claims"]["hfnet_started"])
                self.assertFalse(report["claims"]["hfnet_started"])
                self.assertEqual(
                    report["runner_binding"],
                    {
                        "schema_version": "aqua-fe-hfnet-v6-samehistory-input-audit-binding-v1",
                        "case_id": name,
                        "input_root": str(output.resolve()),
                        "input_manifest": {
                            "path": str(
                                (output / "materialization_manifest.json").resolve()
                            ),
                            "size_bytes": report["manifest"]["identity"][
                                "size_bytes"
                            ],
                            "sha256": report["manifest"]["identity"]["sha256"],
                        },
                        "base_config": {
                            "path": str(audit.CONFIG.resolve()),
                            "size_bytes": report["config"]["size_bytes"],
                            "sha256": report["config"]["sha256"],
                        },
                        "camera_count": 150,
                        "camera_header_ns_inclusive": list(
                            contract.camera_endpoints_ns
                        ),
                        "score_relative_indices_inclusive": [0, 149],
                        "history": "EXACT_WINDOW_COLD_START_NO_PRIOR_CAMERA_HISTORY",
                        "times_relative_path": "cam0_times.txt",
                        "images_relative_path": "mav0/cam0/data",
                        "image_extension": ".png",
                        "imu_relative_path": "mav0/imu0/data.csv",
                        "imu_reader_bracket_valid": True,
                    },
                )
                self.assertTrue((output / "materialization_manifest.json").is_file())
                self.assertTrue((output / "cam0_times.txt").is_file())
                self.assertTrue((output / "mav0/imu0/data.csv").is_file())
                self.assertEqual(len(list((output / "mav0/cam0/data").glob("*.png"))), 150)

    def test_no_clobber_preserves_existing_namespace(self) -> None:
        contract = materializer.WINDOWS["cirs_s575_d30"]
        with tempfile.TemporaryDirectory(prefix="cirs_hfnet_no_clobber_test_") as temporary:
            output = Path(temporary) / "owned"
            output.mkdir()
            marker = output / "owner.txt"
            marker.write_text("preserve", encoding="utf-8")
            with self.assertRaisesRegex(materializer.ContractError, "NO_CLOBBER"):
                materializer.materialize(contract, contract.source_bag, contract.selector, materializer.CONFIG, output)
            self.assertEqual(marker.read_text(encoding="utf-8"), "preserve")

    def test_independent_auditor_rejects_png_tamper(self) -> None:
        name = "cirs_s575_d30"
        contract = materializer.WINDOWS[name]
        with tempfile.TemporaryDirectory(prefix="cirs_hfnet_tamper_test_") as temporary:
            output = Path(temporary) / name
            materializer.materialize(contract, contract.source_bag, contract.selector, materializer.CONFIG, output)
            first_stamp = contract.camera_endpoints_ns[0]
            image = output / f"mav0/cam0/data/{first_stamp}.png"
            os.chmod(image, 0o644)
            payload = bytearray(image.read_bytes())
            payload[-5] ^= 1
            image.write_bytes(payload)
            with self.assertRaises(audit.AuditError):
                audit.audit(audit.CONTRACTS[name], output, contract.source_bag, contract.selector, audit.CONFIG)

    def test_independent_auditor_imports_no_materializer(self) -> None:
        source = (ROOT / "scripts/audit_hfnet_v6_cirs_exact_window_coldstart_input_v1.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        imported = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.append(node.module)
        self.assertFalse(any("materialize_hfnet_v6_cirs" in name for name in imported))


if __name__ == "__main__":
    unittest.main()
