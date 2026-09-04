#!/usr/bin/env python3

from __future__ import annotations

from dataclasses import replace
import hashlib
import io
from pathlib import Path
import struct
import sys
import tarfile
import tempfile
import unittest
from unittest import mock
import zlib

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from scripts import audit_hfnet_v6_aqualoc_old_positive_coldstart_input_v1 as auditor
from scripts import materialize_hfnet_v6_aqualoc_old_positive_coldstart_roster_v1 as materializer


def chunk(kind: bytes, payload: bytes) -> bytes:
    return struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", zlib.crc32(kind + payload) & 0xFFFFFFFF)


def png(width: int, height: int, value: int) -> bytes:
    header = struct.pack(">IIBBBBB", width, height, 8, 0, 0, 0, 0)
    scanlines = (b"\x00" + bytes([value]) * width) * height
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", zlib.compress(scanlines)) + chunk(b"IEND", b"")


class ColdstartRosterTests(unittest.TestCase):
    def test_five_frozen_profiles_and_shared_config(self) -> None:
        expected = {
            "a02_7600_8000": ("A02", 7600, 8000, 401),
            "a05_3300_3700": ("A05", 3300, 3700, 401),
            "a07_10800_11200": ("A07", 10800, 11200, 401),
            "a08_4500_4660": ("A08", 4500, 4660, 161),
            "a09_6000_6200": ("A09", 6000, 6200, 201),
        }
        self.assertEqual(set(materializer.PROFILES), set(expected))
        for key, wanted in expected.items():
            row = materializer.PROFILES[key]
            self.assertEqual((row.sequence_id, row.start, row.end, row.camera_count), wanted)
            self.assertEqual(materializer.contract_for(row).camera_count, wanted[3])
        materializer.validate_authorities(
            materializer.PROFILES["a02_7600_8000"],
            materializer.DEFAULT_ROSTER,
            materializer.DEFAULT_CONFIG,
        )
        text = materializer.DEFAULT_CONFIG.read_text(encoding="utf-8")
        self.assertIn('Extractor.modelPath: "/home/ma/SLAM/HFNet-SLAM-runtime-model-a02-r1/HFNet-RT/"', text)
        self.assertIn("Extractor.nFeatures: 675", text)
        self.assertIn("Extractor.threshold: 0.01", text)

    def test_a02_a07_historical_every2_headers_match_all_200(self) -> None:
        for key in ("a02_7600_8000", "a07_10800_11200"):
            profile = materializer.PROFILES[key]
            stamps = [int(line) for line in Path(str(profile.legacy_times_path)).read_text().splitlines()]
            rows = [(stamp, f"frame{profile.start + index:06d}.png") for index, stamp in enumerate(stamps)]
            materialized = materializer.crosscheck_legacy_window(profile, rows)
            independent = auditor.crosscheck_legacy_window(profile, stamps)
            self.assertEqual(materialized["status"], "PASS_EXACT_HISTORICAL_WINDOW_CROSSCHECK")
            self.assertEqual(independent["status"], "PASS_EXACT_HISTORICAL_WINDOW_CROSSCHECK")
            self.assertEqual(materialized["legacy_every2_feature_count"], 200)
            self.assertTrue(independent["same_window_claimed"])

    def test_synthetic_materialization_is_atomic_and_no_clobber(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.tar.gz"
            images = [png(3, 2, value) for value in range(4)]
            camera = (
                "#timestamp [ns], frame_id\n"
                "1000,frame000000.png\n2000,frame000001.png\n"
                "3000,frame000002.png\n4000,frame000003.png\n"
            ).encode()
            imu_header = materializer.core.IMU_CSV_HEADER
            imu = (imu_header + "\n1800,1,2,3,4,5,6\n1950,1,2,3,4,5,6\n2050,1,2,3,4,5,6\n2800,1,2,3,4,5,6\n2950,1,2,3,4,5,6").encode()
            with tarfile.open(source, "w:gz") as tar:
                for name, payload in (("raw_data/img_sequence_2.csv", camera), ("raw_data/imu_sequence_2.csv", imu)):
                    info = tarfile.TarInfo(name)
                    info.size = len(payload)
                    tar.addfile(info, io.BytesIO(payload))
                for index, payload in enumerate(images):
                    info = tarfile.TarInfo(f"raw_data/images_sequence_2/frame{index:06d}.png")
                    info.size = len(payload)
                    tar.addfile(info, io.BytesIO(payload))

            def pin(payload: bytes) -> materializer.FilePin:
                return materializer.FilePin(len(payload), hashlib.sha256(payload).hexdigest(), f"{zlib.crc32(payload) & 0xffffffff:08x}")

            selected = [(2000, "frame000001.png"), (3000, "frame000002.png")]
            times = materializer.core.camera_times_bytes(selected)
            camera_out = materializer.core.camera_csv_bytes(selected)
            imu_out = materializer.core.imu_csv_bytes(
                [(1800, ("1", "2", "3", "4", "5", "6")), (1950, ("1", "2", "3", "4", "5", "6")), (2050, ("1", "2", "3", "4", "5", "6")), (2800, ("1", "2", "3", "4", "5", "6")), (2950, ("1", "2", "3", "4", "5", "6"))],
                100,
            )
            output_rows = [materializer.core.identity_bytes(f"mav0/cam0/data/{stamp}.png", images[index]) for index, (stamp, _) in zip((1, 2), selected)]
            source_rows = [dict(row, path=f"raw_data/images_sequence_2/frame{index:06d}.png") for index, row in zip((1, 2), output_rows)]
            generated = [materializer.core.identity_bytes("cam0_times.txt", times), materializer.core.identity_bytes("mav0/cam0/data.csv", camera_out), materializer.core.identity_bytes("mav0/imu0/data.csv", imu_out)]
            source_bytes = source.read_bytes()
            contract = materializer.MaterializationContract(
                source_archive=source,
                source_pin=materializer.FilePin(len(source_bytes), hashlib.sha256(source_bytes).hexdigest()),
                source_gzip_crc32=None, source_gzip_isize=None,
                image_csv_member="raw_data/img_sequence_2.csv", image_csv_pin=pin(camera),
                imu_csv_member="raw_data/imu_sequence_2.csv", imu_csv_pin=pin(imu),
                image_member_prefix="raw_data/images_sequence_2/", source_camera_count=4, source_imu_count=5,
                camera_start_index=1, camera_end_index=2, camera_first_ns=2000, camera_last_ns=3000,
                width=3, height=2, png_bit_depth=8, png_color_type=0, imu_shift_ns=100,
                imu_first_index=0, imu_last_index=4, imu_first_raw_ns=1800, imu_last_raw_ns=2950,
                imu_first_output_ns=1900, imu_second_output_ns=2050, imu_penultimate_output_ns=2900, imu_last_output_ns=3050,
                expected_image_total_bytes=len(images[1]) + len(images[2]),
                expected_source_image_inventory_sha256=materializer.core.aggregate_identities(source_rows)["sha256"],
                expected_source_image_inventory_crc32=materializer.core.aggregate_identities(source_rows)["crc32"],
                expected_renamed_image_inventory_sha256=materializer.core.aggregate_identities(output_rows)["sha256"],
                expected_renamed_image_inventory_crc32=materializer.core.aggregate_identities(output_rows)["crc32"],
                times_pin=pin(times), camera_csv_pin=pin(camera_out), imu_output_pin=pin(imu_out),
                expected_payload_sha256=materializer.core.aggregate_identities(output_rows + generated)["sha256"],
                expected_payload_crc32=materializer.core.aggregate_identities(output_rows + generated)["crc32"],
            )
            profile = replace(
                materializer.PROFILES["a02_7600_8000"],
                key="synthetic", start=1, end=2, camera_first_ns=2000, camera_last_ns=3000,
                legacy_times_path=None, legacy_full_bag_path=None, legacy_full_bag_size=None, legacy_full_bag_sha256=None,
            )
            output = root / "output"
            fake_authorities = {"reused_streaming_core": {}, "roster": {}, "config": {}}
            with mock.patch.object(materializer, "validate_authorities", return_value=fake_authorities):
                manifest = materializer.materialize(profile, source, output, contract=contract)
                self.assertEqual(manifest["status"], "PASS_PREPARATION_ONLY")
                self.assertEqual(len(list((output / "mav0/cam0/data").glob("*.png"))), 2)
                self.assertFalse(manifest["claims"]["hfnet_started"])
                with self.assertRaisesRegex(materializer.ContractError, "NO_CLOBBER"):
                    materializer.materialize(profile, source, output, contract=contract)

    def test_independent_png_auditor_rejects_crc_tamper(self) -> None:
        payload = png(968, 608, 7)
        self.assertTrue(auditor.engine.validate_png(payload)["idat_decoded"])
        damaged = bytearray(payload)
        damaged[-5] ^= 1
        with self.assertRaises(auditor.AuditError):
            auditor.engine.validate_png(bytes(damaged))

    def test_runner_binding_schema_and_fail_closed_bracket(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = root / "materialization_manifest.json"
            manifest.write_text("{}\n", encoding="utf-8")
            profile = replace(
                materializer.PROFILES["a02_7600_8000"],
                key="synthetic_case", start=1, end=2,
            )
            config_identity = {
                "path": str(materializer.DEFAULT_CONFIG.resolve()),
                "size_bytes": materializer.CONFIG_SIZE,
                "sha256": materializer.CONFIG_SHA256,
            }
            binding = auditor.build_runner_binding(
                profile,
                root,
                manifest,
                config_identity,
                [2000, 3000],
                {"reader_bracket_valid": True},
            )
            self.assertEqual(
                binding["schema_version"],
                "aqua-fe-hfnet-v6-samehistory-input-audit-binding-v1",
            )
            self.assertEqual(binding["case_id"], "synthetic_case")
            self.assertEqual(binding["score_relative_indices_inclusive"], [0, 1])
            self.assertEqual(
                binding["history"],
                "EXACT_WINDOW_COLD_START_NO_PRIOR_CAMERA_HISTORY",
            )
            self.assertEqual(binding["images_relative_path"], "mav0/cam0/data")
            self.assertTrue(Path(binding["input_manifest"]["path"]).is_absolute())
            self.assertEqual(
                set(binding["base_config"]), {"path", "size_bytes", "sha256"}
            )
            self.assertNotIn("config", binding)
            with self.assertRaisesRegex(auditor.AuditError, "IMU_READER_BRACKET_INVALID"):
                auditor.build_runner_binding(
                    profile,
                    root,
                    manifest,
                    config_identity,
                    [2000, 3000],
                    {"reader_bracket_valid": False},
                )


if __name__ == "__main__":
    unittest.main()
