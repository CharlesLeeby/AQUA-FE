#!/usr/bin/env python3
"""Synthetic, process-free tests for the A08 natural-history materializer."""

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

from scripts import (
    materialize_hfnet_v6_a08_0000_4660_score_4500_4660_v1 as subject,
)


def _chunk(kind: bytes, payload: bytes) -> bytes:
    return (
        struct.pack(">I", len(payload))
        + kind
        + payload
        + struct.pack(">I", zlib.crc32(kind + payload) & 0xFFFFFFFF)
    )


def _png(value: int) -> bytes:
    header = struct.pack(">IIBBBBB", 3, 2, 8, 0, 0, 0, 0)
    scanlines = b"\x00" + bytes([value]) * 3 + b"\x00" + bytes([value]) * 3
    return (
        b"\x89PNG\r\n\x1a\n"
        + _chunk(b"IHDR", header)
        + _chunk(b"IDAT", zlib.compress(scanlines))
        + _chunk(b"IEND", b"")
    )


def _add(archive: tarfile.TarFile, name: str, payload: bytes) -> None:
    info = tarfile.TarInfo(name)
    info.size = len(payload)
    archive.addfile(info, io.BytesIO(payload))


class A08NaturalHistoryMaterializerTests(unittest.TestCase):
    def test_production_contract_and_score_boundary(self) -> None:
        contract = subject.PRODUCTION_CONTRACT
        self.assertEqual(
            (contract.camera_start_index, contract.camera_end_index, contract.camera_count),
            (0, 4660, 4661),
        )
        self.assertEqual(
            (contract.imu_first_index, contract.imu_last_index, contract.imu_count),
            (12, 46570, 46559),
        )
        self.assertLessEqual(contract.imu_first_output_ns, contract.camera_first_ns)
        self.assertGreater(contract.imu_second_output_ns, contract.camera_first_ns)
        self.assertLessEqual(contract.imu_penultimate_output_ns, contract.camera_last_ns)
        self.assertGreater(contract.imu_last_output_ns, contract.camera_last_ns)

    def test_frozen_selector_identity_and_boundaries(self) -> None:
        observed = subject.validate_selector(subject.DEFAULT_SELECTOR_FREEZE)
        self.assertEqual(observed["sha256"], subject.SELECTOR_FREEZE_SHA256)

    def test_synthetic_materialization_is_atomic_and_process_free(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.tar.gz"
            selector = root / "selector.json"
            selector.write_text("{}\n", encoding="utf-8")
            cameras = [1000, 2000, 3000]
            imus = [800, 950, 1050, 1950, 3050]
            camera_csv = (
                subject.core.IMAGE_CSV_HEADER
                + "\n"
                + "\n".join(
                    f"{stamp},frame{index:06d}.png"
                    for index, stamp in enumerate(cameras)
                )
                + "\n"
            ).encode()
            imu_csv = (
                subject.core.IMU_CSV_HEADER
                + "\n"
                + "\n".join(f"{stamp},1,2,3,4,5,6" for stamp in imus)
                + "\n"
            ).encode()
            images = [_png(index) for index in range(3)]
            with tarfile.open(source, "w:gz") as archive:
                _add(archive, "raw_data/camera.csv", camera_csv)
                _add(archive, "raw_data/imu.csv", imu_csv)
                for index, payload in enumerate(images):
                    _add(archive, f"raw_data/images/frame{index:06d}.png", payload)
            source_bytes = source.read_bytes()

            def pin(payload: bytes) -> subject.FilePin:
                return subject.FilePin(
                    len(payload),
                    hashlib.sha256(payload).hexdigest(),
                    f"{zlib.crc32(payload) & 0xffffffff:08x}",
                )

            contract = subject.MaterializationContract(
                source_archive=source,
                source_pin=subject.FilePin(
                    len(source_bytes), hashlib.sha256(source_bytes).hexdigest()
                ),
                source_gzip_crc32=None,
                source_gzip_isize=None,
                image_csv_member="raw_data/camera.csv",
                image_csv_pin=pin(camera_csv),
                imu_csv_member="raw_data/imu.csv",
                imu_csv_pin=pin(imu_csv),
                image_member_prefix="raw_data/images/",
                source_camera_count=3,
                source_imu_count=5,
                camera_start_index=0,
                camera_end_index=2,
                camera_first_ns=1000,
                camera_last_ns=3000,
                width=3,
                height=2,
                png_bit_depth=8,
                png_color_type=0,
                imu_shift_ns=100,
                imu_first_index=0,
                imu_last_index=4,
                imu_first_raw_ns=800,
                imu_last_raw_ns=3050,
                imu_first_output_ns=900,
                imu_second_output_ns=1050,
                imu_penultimate_output_ns=2050,
                imu_last_output_ns=3150,
                expected_image_total_bytes=None,
                expected_source_image_inventory_sha256=None,
                expected_source_image_inventory_crc32=None,
                expected_renamed_image_inventory_sha256=None,
                expected_renamed_image_inventory_crc32=None,
                times_pin=subject.FilePin(),
                camera_csv_pin=subject.FilePin(),
                imu_output_pin=subject.FilePin(),
                expected_payload_sha256=None,
                expected_payload_crc32=None,
            )
            output = root / "output"
            with mock.patch.object(
                subject.adapter,
                "validate_selector",
                return_value={
                    "path": str(selector),
                    "size_bytes": 3,
                    "sha256": "synthetic",
                },
            ), mock.patch.object(
                subject,
                "_require_reused_code_pins",
                return_value={
                    "a05_materializer_bridge": {"sha256": "synthetic-bridge"},
                    "a06_adapter": {"sha256": "synthetic-adapter"},
                },
            ):
                manifest = subject.materialize(selector, source, output, contract)
            self.assertEqual(manifest["status"], "PASS_PREPARATION_ONLY")
            self.assertEqual(manifest["selection"]["sequence_id"], "A08")
            self.assertFalse(manifest["claims"]["hfnet_started"])
            self.assertEqual(
                (output / "mav0/cam0/data/1000.png").read_bytes(), images[0]
            )
            self.assertEqual(
                (output / "mav0/cam0/data/3000.png").read_bytes(), images[2]
            )


if __name__ == "__main__":
    unittest.main()
