#!/usr/bin/env python3
"""Synthetic tests for the post-STOP HFNet full-window adapter."""

from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import cv2
import numpy as np

from scripts import export_aqualoc_to_hfnet_euroc_full_v2 as adapter


def _selection() -> adapter.base.SourceSelection:
    cameras = []
    for index, stamp in enumerate((100, 200, 300)):
        pixels = bytes((index, index + 1, index + 2, index + 3, index + 4, index + 5))
        cameras.append(
            adapter.base.CameraSample(
                source_index=index,
                header_ns=stamp,
                record_ns=stamp,
                width=3,
                height=2,
                encoding="mono8",
                step=3,
                pixels=pixels,
                pixel_sha256=hashlib.sha256(pixels).hexdigest(),
            )
        )
    imus = []
    for index, stamp in enumerate((90, 150, 250, 310), start=1):
        imus.append(
            adapter.base.ImuSample(
                source_index=index,
                raw_header_ns=stamp,
                output_header_ns=stamp + 10,
                record_ns=stamp,
                gyro_xyz=(index + 0.1, index + 0.2, index + 0.3),
                accel_xyz=(index + 1.1, index + 1.2, index + 1.3),
            )
        )
    return adapter.base.SourceSelection(
        cameras=tuple(cameras),
        imus=tuple(imus),
        topic_audit={"/camera": {"message_count": 3}, "/imu": {"message_count": 4}},
        all_image_first_ns=100,
        all_image_last_ns=300,
        all_imu_first_ns=90,
        all_imu_last_ns=310,
    )


FIXTURE_CONTRACT = adapter.base.PrefixContract(
    image_topic="/camera",
    imu_topic="/imu",
    expected_image_type="sensor_msgs/Image",
    expected_imu_type="sensor_msgs/Imu",
    expected_total_images=3,
    expected_total_imus=4,
    image_first_index=0,
    image_last_index=2,
    imu_first_index=1,
    imu_last_index=4,
    width=3,
    height=2,
    encoding="mono8",
    imu_shift_ns=10,
    expected_first_image_stamp_ns=100,
    expected_last_image_stamp_ns=300,
    expected_first_imu_raw_stamp_ns=90,
    expected_last_imu_raw_stamp_ns=310,
)


class HfnetFullAdapterV2Tests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.source = self.root / "source.bag"
        self.source.write_bytes(b"synthetic immutable bag")

    def test_production_contract_is_exact_full_window(self) -> None:
        contract = adapter.A02_FULL_CONTRACT
        self.assertEqual((contract.image_first_index, contract.image_last_index), (0, 900))
        self.assertEqual(contract.image_count, 901)
        self.assertEqual((contract.imu_first_index, contract.imu_last_index), (38, 9031))
        self.assertEqual(contract.imu_count, 8994)
        self.assertEqual(contract.expected_last_image_stamp_ns, 1542829061692686528)
        self.assertEqual(contract.expected_last_imu_raw_stamp_ns, 1542829061641706560)

    def test_clock_conversion_is_identical_to_sealed_prefix_adapter(self) -> None:
        self.assertEqual(adapter.A02_FULL_CONTRACT.imu_shift_ns, 53_694_112)
        self.assertEqual(
            round(-adapter.base.KALIBR_TIMESHIFT_CAM_IMU_S * 1e9),
            adapter.A02_FULL_CONTRACT.imu_shift_ns,
        )

    def test_base_adapter_identity_is_locked(self) -> None:
        observed = adapter.validate_base_adapter_identity()
        self.assertEqual(observed["sha256"], adapter.BASE_ADAPTER_SHA256)
        with mock.patch.object(adapter, "_sha256", return_value="0" * 64):
            with self.assertRaisesRegex(
                adapter.ContractError, "BASE_ADAPTER_IDENTITY_MISMATCH"
            ):
                adapter.validate_base_adapter_identity()

    def test_synthetic_full_manifest_and_layout_are_exact(self) -> None:
        output = self.root / "full"
        manifest = adapter.write_artifact(
            output,
            self.source,
            hashlib.sha256(self.source.read_bytes()).hexdigest(),
            _selection(),
            FIXTURE_CONTRACT,
            {"actual_commit": adapter.base.HFNET_COMMIT, "errors": []},
            {"path": "/adapter-v1.py", "sha256": adapter.BASE_ADAPTER_SHA256},
        )
        self.assertEqual(manifest["status"], adapter.STATUS_EXPORTED)
        self.assertEqual(manifest["artifact_scope"], adapter.ARTIFACT_SCOPE)
        self.assertEqual(manifest["scientific_role"], adapter.SCIENTIFIC_ROLE)
        self.assertTrue(manifest["claims"]["full_a02_window_exported"])
        self.assertFalse(manifest["claims"]["hfnet_started"])
        self.assertFalse(manifest["claims"]["prefix_r1_result_replaced"])
        self.assertEqual(
            (output / "cam0_times.txt").read_text().splitlines(),
            ["100", "200", "300"],
        )
        csv = (output / "mav0/imu0/data.csv").read_bytes()
        self.assertFalse(csv.endswith(b"\n"))
        self.assertEqual(
            [int(row.split(b",", 1)[0]) for row in csv.splitlines()[1:]],
            [100, 160, 260, 320],
        )
        images = sorted((output / "mav0/cam0/data").glob("*.png"))
        self.assertEqual([path.stem for path in images], ["100", "200", "300"])
        for index, path in enumerate(images):
            decoded = cv2.imread(str(path), cv2.IMREAD_UNCHANGED)
            expected = np.frombuffer(
                _selection().cameras[index].pixels, dtype=np.uint8
            ).reshape(2, 3)
            self.assertTrue(np.array_equal(decoded, expected))
        loaded = json.loads((output / "conversion_manifest.json").read_text())
        self.assertEqual(loaded, manifest)

    def test_existing_output_is_never_reused_or_clobbered(self) -> None:
        output = self.root / "full"
        output.mkdir()
        marker = output / "owner.txt"
        marker.write_text("preserve", encoding="utf-8")
        with self.assertRaisesRegex(adapter.ContractError, "OUTPUT_ALREADY_EXISTS"):
            adapter.write_artifact(
                output,
                self.source,
                hashlib.sha256(self.source.read_bytes()).hexdigest(),
                _selection(),
                FIXTURE_CONTRACT,
                {"errors": []},
                {"sha256": adapter.BASE_ADAPTER_SHA256},
            )
        self.assertEqual(marker.read_text(), "preserve")


if __name__ == "__main__":
    unittest.main()
