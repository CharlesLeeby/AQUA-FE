#!/usr/bin/env python3
"""Synthetic, process-free tests for the A02 full-history materializer."""

from __future__ import annotations

import hashlib
import io
from pathlib import Path
import struct
import tarfile
import tempfile
import unittest
from unittest import mock
import zlib

from scripts import materialize_hfnet_v6_a02_0001_6300_score_4500_6300_v1 as adapter


def _chunk(kind: bytes, payload: bytes) -> bytes:
    return struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", zlib.crc32(kind + payload) & 0xFFFFFFFF)


def _png(value: int) -> bytes:
    header = struct.pack(">IIBBBBB", 3, 2, 8, 0, 0, 0, 0)
    scanlines = b"\x00" + bytes([value]) * 3 + b"\x00" + bytes([value]) * 3
    return b"\x89PNG\r\n\x1a\n" + _chunk(b"IHDR", header) + _chunk(b"IDAT", zlib.compress(scanlines)) + _chunk(b"IEND", b"")


def _add(tar: tarfile.TarFile, name: str, payload: bytes) -> None:
    info = tarfile.TarInfo(name)
    info.size = len(payload)
    tar.addfile(info, io.BytesIO(payload))


class A02FullHistoryMaterializerTests(unittest.TestCase):
    def test_production_selection_and_honest_imu_trim_are_frozen(self) -> None:
        contract = adapter.PRODUCTION_CONTRACT
        self.assertEqual((contract.camera_start_index, contract.camera_end_index, contract.camera_count), (1, 6300, 6300))
        self.assertEqual((contract.imu_first_index, contract.imu_last_index, contract.imu_count), (2, 62940, 62939))
        self.assertEqual(contract.imu_shift_ns, 53_694_112)
        self.assertLess(contract.imu_first_output_ns, contract.camera_first_ns)
        self.assertGreater(contract.imu_second_output_ns, contract.camera_first_ns)
        self.assertLess(contract.imu_penultimate_output_ns, contract.camera_last_ns)
        self.assertGreater(contract.imu_last_output_ns, contract.camera_last_ns)
        camera_zero_ns = 1_542_828_791_736_012_032
        raw_imu_zero_ns = 1_542_828_791_718_948_544
        self.assertGreater(raw_imu_zero_ns + contract.imu_shift_ns, camera_zero_ns)

    def test_selector_discloses_development_and_p07_boundaries(self) -> None:
        observed = adapter.validate_selector(adapter.DEFAULT_SELECTOR_FREEZE)
        self.assertEqual(observed["sha256"], adapter.SELECTOR_FREEZE_SHA256)

    def test_config_changes_only_provenance_comments_from_established_a02(self) -> None:
        root = Path(__file__).resolve().parents[2]
        old = (root / "configs/published_baselines/hfnet_slam_aqualoc_a02_0005.yaml").read_text()
        new = (root / "configs/published_baselines/hfnet_slam_aqualoc_a02_0001_6300_score_4500_6300_v1.yaml").read_text()
        self.assertEqual(old[old.index('File.version:'):], new[new.index('File.version:'):])

    def test_synthetic_materialization_is_atomic_and_starts_no_process(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.tar.gz"
            selector = root / "selector.json"
            selector.write_text("{}\n", encoding="utf-8")
            cameras = [1000, 2000, 3000, 4000]
            imus = [1800, 1950, 2050, 2800, 2950]
            camera_csv = (adapter.core.IMAGE_CSV_HEADER + "\n" + "\n".join(f"{stamp},frame{index:06d}.png" for index, stamp in enumerate(cameras)) + "\n").encode()
            imu_csv = (adapter.core.IMU_CSV_HEADER + "\n" + "\n".join(f"{stamp},1,2,3,4,5,6" for stamp in imus) + "\n").encode()
            images = [_png(index) for index in range(4)]
            with tarfile.open(source, "w:gz") as tar:
                _add(tar, "raw_data/camera.csv", camera_csv)
                _add(tar, "raw_data/imu.csv", imu_csv)
                for index, payload in enumerate(images):
                    _add(tar, f"raw_data/images/frame{index:06d}.png", payload)
            source_bytes = source.read_bytes()
            pin = lambda payload: adapter.FilePin(len(payload), hashlib.sha256(payload).hexdigest(), f"{zlib.crc32(payload) & 0xffffffff:08x}")
            contract = adapter.MaterializationContract(
                source_archive=source,
                source_pin=adapter.FilePin(len(source_bytes), hashlib.sha256(source_bytes).hexdigest()),
                source_gzip_crc32=None,
                source_gzip_isize=None,
                image_csv_member="raw_data/camera.csv",
                image_csv_pin=pin(camera_csv),
                imu_csv_member="raw_data/imu.csv",
                imu_csv_pin=pin(imu_csv),
                image_member_prefix="raw_data/images/",
                source_camera_count=4,
                source_imu_count=5,
                camera_start_index=1,
                camera_end_index=2,
                camera_first_ns=2000,
                camera_last_ns=3000,
                width=3,
                height=2,
                png_bit_depth=8,
                png_color_type=0,
                imu_shift_ns=100,
                imu_first_index=0,
                imu_last_index=4,
                imu_first_raw_ns=1800,
                imu_last_raw_ns=2950,
                imu_first_output_ns=1900,
                imu_second_output_ns=2050,
                imu_penultimate_output_ns=2900,
                imu_last_output_ns=3050,
                expected_image_total_bytes=None,
                expected_source_image_inventory_sha256=None,
                expected_source_image_inventory_crc32=None,
                expected_renamed_image_inventory_sha256=None,
                expected_renamed_image_inventory_crc32=None,
                times_pin=adapter.FilePin(),
                camera_csv_pin=adapter.FilePin(),
                imu_output_pin=adapter.FilePin(),
                expected_payload_sha256=None,
                expected_payload_crc32=None,
            )
            output = root / "output"
            with mock.patch.object(adapter.adapter, "validate_selector", return_value={"path": str(selector), "size_bytes": 3, "sha256": "synthetic"}):
                manifest = adapter.materialize(selector, source, output, contract)
            self.assertEqual(manifest["status"], "PASS_PREPARATION_ONLY")
            self.assertFalse(manifest["claims"]["hfnet_started"])
            self.assertEqual((output / "mav0/cam0/data/2000.png").read_bytes(), images[1])
            self.assertEqual((output / "mav0/cam0/data/3000.png").read_bytes(), images[2])


if __name__ == "__main__":
    unittest.main()
