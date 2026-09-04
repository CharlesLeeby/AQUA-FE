#!/usr/bin/env python3
"""Isolated tests for the Phase-F H03 preparation-only materializer."""

from __future__ import annotations

from dataclasses import replace
import hashlib
import io
import json
from pathlib import Path
import struct
import tarfile
import tempfile
import unittest
from unittest import mock
import zlib

from scripts import materialize_hfnet_v6_phase_f_h03_1800_3600_v1 as adapter


CAMERA_STAMPS = (1_000, 2_000, 3_000, 4_000, 5_000)
IMU_STAMPS = (1_800, 1_950, 2_050, 2_850, 3_850, 3_950, 4_050)
IMAGE_MEMBER = "raw_data/camera.csv"
IMU_MEMBER = "raw_data/imu.csv"
IMAGE_PREFIX = "raw_data/images/"


def _chunk(kind: bytes, payload: bytes) -> bytes:
    return (
        struct.pack(">I", len(payload))
        + kind
        + payload
        + struct.pack(">I", zlib.crc32(kind + payload) & 0xFFFFFFFF)
    )


def _png(width: int, height: int, value: int) -> bytes:
    signature = b"\x89PNG\r\n\x1a\n"
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 0, 0, 0, 0)
    rows = b"".join(b"\x00" + bytes([value]) * width for _ in range(height))
    return signature + _chunk(b"IHDR", ihdr) + _chunk(b"IDAT", zlib.compress(rows)) + _chunk(b"IEND", b"")


def _camera_csv() -> bytes:
    lines = [adapter.IMAGE_CSV_HEADER]
    lines.extend(f"{stamp},frame{index:06d}.png" for index, stamp in enumerate(CAMERA_STAMPS))
    return ("\n".join(lines) + "\n").encode("utf-8")


def _imu_csv() -> bytes:
    lines = [adapter.IMU_CSV_HEADER]
    for index, stamp in enumerate(IMU_STAMPS):
        lines.append(
            f"{stamp},{index}.1,{index}.2,{index}.3,{index}.4,{index}.5,{index}.6"
        )
    return ("\n".join(lines) + "\n").encode("utf-8")


def _pin(payload: bytes) -> adapter.FilePin:
    return adapter.FilePin(
        size_bytes=len(payload),
        sha256=hashlib.sha256(payload).hexdigest(),
        crc32=adapter.crc32_bytes(payload),
    )


def _add_bytes(tar: tarfile.TarFile, name: str, payload: bytes) -> None:
    info = tarfile.TarInfo(name)
    info.size = len(payload)
    info.mode = 0o444
    tar.addfile(info, io.BytesIO(payload))


def _build_archive(path: Path, *, corrupt_second_selected_png: bool = False):
    camera = _camera_csv()
    imu = _imu_csv()
    images = [_png(3, 2, index) for index in range(len(CAMERA_STAMPS))]
    if corrupt_second_selected_png:
        broken = bytearray(images[2])
        broken[-5] ^= 0x01
        images[2] = bytes(broken)
    with tarfile.open(str(path), "w:gz") as tar:
        _add_bytes(tar, IMAGE_MEMBER, camera)
        _add_bytes(tar, IMU_MEMBER, imu)
        for index, payload in enumerate(images):
            _add_bytes(tar, f"{IMAGE_PREFIX}frame{index:06d}.png", payload)
    return camera, imu, images


def _contract(path: Path, camera: bytes, imu: bytes) -> adapter.MaterializationContract:
    source = path.read_bytes()
    return adapter.MaterializationContract(
        source_archive=path,
        source_pin=adapter.FilePin(
            size_bytes=len(source), sha256=hashlib.sha256(source).hexdigest()
        ),
        source_gzip_crc32=None,
        source_gzip_isize=None,
        image_csv_member=IMAGE_MEMBER,
        image_csv_pin=_pin(camera),
        imu_csv_member=IMU_MEMBER,
        imu_csv_pin=_pin(imu),
        image_member_prefix=IMAGE_PREFIX,
        source_camera_count=5,
        source_imu_count=7,
        camera_start_index=1,
        camera_end_index=3,
        camera_first_ns=2_000,
        camera_last_ns=4_000,
        width=3,
        height=2,
        png_bit_depth=8,
        png_color_type=0,
        imu_shift_ns=100,
        imu_first_index=0,
        imu_last_index=5,
        imu_first_raw_ns=1_800,
        imu_last_raw_ns=3_950,
        imu_first_output_ns=1_900,
        imu_second_output_ns=2_050,
        imu_penultimate_output_ns=3_950,
        imu_last_output_ns=4_050,
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


class PhaseFH03MaterializerTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.source = self.root / "source.tar.gz"
        camera, imu, images = _build_archive(self.source)
        self.camera_csv = camera
        self.imu_csv = imu
        self.images = images
        self.contract = _contract(self.source, camera, imu)
        self.selector = self.root / "selector.json"
        self.selector.write_text("{}\n", encoding="utf-8")

    def _selector_patch(self):
        return mock.patch.object(
            adapter,
            "validate_selector",
            return_value={"path": str(self.selector), "size_bytes": 3, "sha256": "synthetic"},
        )

    def test_production_contract_and_selector_are_frozen(self) -> None:
        contract = adapter.PRODUCTION_CONTRACT
        self.assertEqual((contract.camera_start_index, contract.camera_end_index), (1800, 3600))
        self.assertEqual(contract.camera_count, 1801)
        self.assertEqual((contract.imu_first_index, contract.imu_last_index), (18003, 36001))
        self.assertEqual(contract.imu_count, 17999)
        self.assertEqual(contract.imu_shift_ns, 40_380_655)
        self.assertEqual(
            contract.imu_output_pin.sha256,
            "45edd79a4073f646813cc53d710ab5fd6a26a4b3acb927dfa18292dc6c377193",
        )
        observed = adapter.validate_selector(adapter.DEFAULT_SELECTOR_FREEZE)
        self.assertEqual(observed["sha256"], adapter.SELECTOR_FREEZE_SHA256)

    def test_exact_csv_serializers_and_imu_reader_bracket(self) -> None:
        selected_camera = [(stamp, f"frame{index:06d}.png") for index, stamp in enumerate((2000, 3000, 4000), start=1)]
        selected_imu = [
            (stamp, tuple(f"{index}.{axis}" for axis in range(1, 7)))
            for index, stamp in enumerate(IMU_STAMPS[:6])
        ]
        times = adapter.camera_times_bytes(selected_camera)
        camera_csv = adapter.camera_csv_bytes(selected_camera)
        imu_csv = adapter.imu_csv_bytes(selected_imu, 100)
        self.assertEqual(times, b"2000\n3000\n4000\n")
        self.assertEqual(
            camera_csv,
            b"#timestamp [ns],filename\n2000,2000.png\n3000,3000.png\n4000,4000.png\n",
        )
        self.assertFalse(imu_csv.endswith(b"\n"))
        self.assertIn(b"1900,0.1,0.2,0.3,0.4,0.5,0.6", imu_csv)
        bracket = adapter.validate_imu_bracket(imu_csv, selected_camera, self.contract)
        self.assertTrue(bracket["strictly_monotonic"])

    def test_synthetic_materialization_is_atomic_exact_and_preparation_only(self) -> None:
        output = self.root / "fresh"
        with self._selector_patch():
            manifest = adapter.materialize(
                self.selector, self.source, output, self.contract
            )
        self.assertEqual(manifest["status"], "PASS_PREPARATION_ONLY")
        self.assertFalse(manifest["claims"]["hfnet_started"])
        self.assertFalse(manifest["claims"]["runner_created"])
        self.assertEqual(manifest["camera"]["count"], 3)
        self.assertTrue(manifest["camera"]["png_chunk_crc_all_valid"])
        self.assertEqual(
            (output / "mav0/cam0/data/2000.png").read_bytes(), self.images[1]
        )
        self.assertEqual(
            (output / "mav0/cam0/data/3000.png").read_bytes(), self.images[2]
        )
        self.assertEqual(
            (output / "mav0/cam0/data/4000.png").read_bytes(), self.images[3]
        )
        self.assertEqual(
            (output / "cam0_times.txt").read_bytes(), b"2000\n3000\n4000\n"
        )
        imu_payload = (output / "mav0/imu0/data.csv").read_bytes()
        self.assertFalse(imu_payload.endswith(b"\n"))
        self.assertEqual(
            [int(line.split(b",", 1)[0]) for line in imu_payload.splitlines()[1:]],
            [1900, 2050, 2150, 2950, 3950, 4050],
        )
        loaded = json.loads((output / "materialization_manifest.json").read_text())
        self.assertEqual(loaded["payload_file_count_excluding_manifest"], 6)
        self.assertFalse(loaded["claims"]["start_claim_created"])

    def test_preflight_does_not_create_output(self) -> None:
        output = self.root / "fresh"
        with self._selector_patch():
            result = adapter.preflight_result(
                self.selector, self.source, output, self.contract
            )
        self.assertEqual(result["status"], "PREFLIGHT_READY_PREPARATION_ONLY")
        self.assertFalse(output.exists())
        self.assertFalse(result["claims"]["output_created"])

    def test_existing_output_is_never_clobbered(self) -> None:
        output = self.root / "fresh"
        output.mkdir()
        marker = output / "owner.txt"
        marker.write_text("preserve", encoding="utf-8")
        with self._selector_patch(), self.assertRaisesRegex(
            adapter.ContractError, "NO_CLOBBER_OUTPUT_EXISTS"
        ):
            adapter.materialize(self.selector, self.source, output, self.contract)
        self.assertEqual(marker.read_text(encoding="utf-8"), "preserve")

    def test_corrupt_png_crc_rolls_back_staging(self) -> None:
        corrupt = self.root / "corrupt.tar.gz"
        camera, imu, _ = _build_archive(corrupt, corrupt_second_selected_png=True)
        contract = _contract(corrupt, camera, imu)
        output = self.root / "fresh"
        with self._selector_patch(), self.assertRaisesRegex(
            adapter.ContractError, "PNG_CHUNK_CRC_MISMATCH"
        ):
            adapter.materialize(self.selector, corrupt, output, contract)
        self.assertFalse(output.exists())
        self.assertEqual(list(self.root.glob(".fresh.tmp-*")), [])

    def test_wrong_shift_contract_fails_before_publication(self) -> None:
        output = self.root / "fresh"
        bad = replace(self.contract, imu_shift_ns=0)
        with self._selector_patch(), self.assertRaisesRegex(
            adapter.ContractError, "IMU_SELECTION_INDEX_MISMATCH"
        ):
            adapter.materialize(self.selector, self.source, output, bad)
        self.assertFalse(output.exists())

    def test_config_adopts_harbor_fisheye_imu_and_passed_extractor(self) -> None:
        config = (
            Path(__file__).resolve().parents[2]
            / "configs/published_baselines/hfnet_slam_aqualoc_h03_1800_3600_phase_f_v1.yaml"
        ).read_text(encoding="utf-8")
        required = (
            'Camera.type: "KannalaBrandt8"',
            "Camera.width: 640",
            "Camera.height: 512",
            "IMU.NoiseGyro: 0.001",
            "IMU.NoiseAcc: 0.02",
            "IMU.GyroWalk: 0.00005",
            "IMU.AccWalk: 0.001",
            "IMU.Frequency: 200.0",
            "Extractor.nFeatures: 675",
            "Extractor.threshold: 0.01",
            "Extractor.nLevels: 4",
            "loopClosing: 1",
        )
        for text in required:
            self.assertIn(text, config)
        self.assertIn("-0.99978035", config)
        self.assertIn("0.14944769", config)
        self.assertIn(
            "354a23f9c28b75ea9056a8eb5586e3b13191426521fd3f5556e5bfd670fc39b5",
            config,
        )
        self.assertIn(
            "6798ef896e4f503d4d81827a81fc9dad99d40c5e10352abbe974ed309bd0c0e7",
            config,
        )


if __name__ == "__main__":
    unittest.main()
