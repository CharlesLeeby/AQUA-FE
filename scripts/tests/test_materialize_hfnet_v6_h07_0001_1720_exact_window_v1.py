#!/usr/bin/env python3
"""Process-free tests for the H07 exact-window materializer."""

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

from scripts import materialize_hfnet_v6_h07_0001_1720_exact_window_v1 as adapter


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


class H07MaterializerTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.source = self.root / "source.tar.gz"
        self.selector = self.root / "selector.json"
        self.selector.write_text("{}\n", encoding="utf-8")
        camera_stamps = [1000, 2000, 3000, 4000]
        imu_stamps = [1800, 1950, 2050, 2800, 2950]
        camera = (adapter.IMAGE_CSV_HEADER + "\n" + "\n".join(f"{stamp},frame{index:06d}.png" for index, stamp in enumerate(camera_stamps)) + "\n").encode()
        imu = (adapter.IMU_CSV_HEADER + "\n" + "\n".join(f"{stamp},1,2,3,4,5,6" for stamp in imu_stamps) + "\n").encode()
        self.images = [_png(i) for i in range(4)]
        with tarfile.open(self.source, "w:gz") as tar:
            _add(tar, "raw_data/camera.csv", camera)
            _add(tar, "raw_data/imu.csv", imu)
            for index, payload in enumerate(self.images):
                _add(tar, f"raw_data/images/frame{index:06d}.png", payload)
        source = self.source.read_bytes()
        pin = lambda payload: adapter.FilePin(len(payload), hashlib.sha256(payload).hexdigest(), f"{zlib.crc32(payload) & 0xffffffff:08x}")
        self.contract = adapter.MaterializationContract(
            source_archive=self.source,
            source_pin=adapter.FilePin(len(source), hashlib.sha256(source).hexdigest()),
            source_gzip_crc32=None,
            source_gzip_isize=None,
            image_csv_member="raw_data/camera.csv",
            image_csv_pin=pin(camera),
            imu_csv_member="raw_data/imu.csv",
            imu_csv_pin=pin(imu),
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

    def _selector_patch(self):
        return mock.patch.object(adapter, "validate_selector", return_value={"path": str(self.selector), "size_bytes": 3, "sha256": "synthetic"})

    def test_frozen_contract_and_sync_trim(self) -> None:
        contract = adapter.PRODUCTION_CONTRACT
        self.assertEqual((contract.camera_start_index, contract.camera_end_index, contract.camera_count), (1, 1720, 1720))
        self.assertEqual((contract.imu_first_index, contract.imu_last_index, contract.imu_count), (4, 17192, 17189))
        self.assertEqual(contract.imu_shift_ns, 40_380_655)
        selector = adapter.validate_selector(adapter.DEFAULT_SELECTOR_FREEZE)
        self.assertEqual(selector["sha256"], adapter.SELECTOR_FREEZE_SHA256)

    def test_synthetic_materialization_is_atomic_and_process_free(self) -> None:
        output = self.root / "fresh"
        with self._selector_patch():
            manifest = adapter.materialize(self.selector, self.source, output, self.contract)
        self.assertEqual(manifest["status"], "PASS_PREPARATION_ONLY")
        self.assertFalse(manifest["claims"]["hfnet_started"])
        self.assertEqual((output / "mav0/cam0/data/2000.png").read_bytes(), self.images[1])
        stamps = [int(line.split(b",", 1)[0]) for line in (output / "mav0/imu0/data.csv").read_bytes().splitlines()[1:]]
        self.assertEqual(stamps, [1900, 2050, 2150, 2900, 3050])

    def test_no_clobber(self) -> None:
        output = self.root / "fresh"
        output.mkdir()
        marker = output / "owner"
        marker.write_text("preserve")
        with self._selector_patch(), self.assertRaisesRegex(adapter.ContractError, "NO_CLOBBER"):
            adapter.materialize(self.selector, self.source, output, self.contract)
        self.assertEqual(marker.read_text(), "preserve")

    def test_config_keeps_passed_harbor_algorithm_settings(self) -> None:
        config = Path(__file__).resolve().parents[2] / "configs/published_baselines/hfnet_slam_aqualoc_h07_0001_1720_exact_window_v1.yaml"
        text = config.read_text(encoding="utf-8")
        for token in ('Camera.type: "KannalaBrandt8"', "Camera.width: 640", "Camera.height: 512", 'Extractor.type: "HFNetRT"', "Extractor.scaleFactor: 1.2", "Extractor.nLevels: 4", "Extractor.nFeatures: 675", "Extractor.threshold: 0.01", "loopClosing: 1"):
            self.assertIn(token, text)


if __name__ == "__main__":
    unittest.main()
