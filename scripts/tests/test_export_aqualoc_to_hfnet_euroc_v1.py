#!/usr/bin/env python3
"""Synthetic, isolated tests for the A02-to-HFNet EuRoC adapter."""

from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import cv2
import genpy
import numpy as np
import rosbag
from sensor_msgs.msg import Image, Imu

from scripts import export_aqualoc_to_hfnet_euroc_v1 as adapter


BASE_NS = 1_700_000_000_000_000_000
CAMERA_STAMPS = (BASE_NS + 100, BASE_NS + 200, BASE_NS + 300)
IMU_STAMPS = (
    BASE_NS + 50,
    BASE_NS + 90,
    BASE_NS + 150,
    BASE_NS + 250,
    BASE_NS + 310,
    BASE_NS + 400,
)

FIXTURE_CONTRACT = adapter.PrefixContract(
    image_topic=adapter.CAMERA_TOPIC,
    imu_topic=adapter.IMU_TOPIC,
    expected_image_type="sensor_msgs/Image",
    expected_imu_type="sensor_msgs/Imu",
    expected_total_images=3,
    expected_total_imus=6,
    image_first_index=0,
    image_last_index=2,
    imu_first_index=1,
    imu_last_index=4,
    width=3,
    height=2,
    encoding="mono8",
    imu_shift_ns=10,
    expected_first_image_stamp_ns=CAMERA_STAMPS[0],
    expected_last_image_stamp_ns=CAMERA_STAMPS[-1],
    expected_first_imu_raw_stamp_ns=IMU_STAMPS[1],
    expected_last_imu_raw_stamp_ns=IMU_STAMPS[4],
)


def _time(stamp_ns: int) -> genpy.Time:
    return genpy.Time(stamp_ns // 1_000_000_000, stamp_ns % 1_000_000_000)


def _image(stamp_ns: int, index: int, *, bad_schema: bool = False) -> Image:
    message = Image()
    message.header.stamp = _time(stamp_ns)
    message.height = 2
    message.width = 4 if bad_schema else 3
    message.encoding = "mono8"
    message.is_bigendian = 0
    message.step = message.width
    message.data = bytes((index, index + 1, index + 2, index + 3, index + 4, index + 5))
    if bad_schema:
        message.data += b"\x06\x07"
    return message


def _imu(stamp_ns: int, index: int) -> Imu:
    message = Imu()
    message.header.stamp = _time(stamp_ns)
    message.angular_velocity.x = index + 0.1
    message.angular_velocity.y = index + 0.2
    message.angular_velocity.z = index + 0.3
    message.linear_acceleration.x = index + 1.1
    message.linear_acceleration.y = index + 1.2
    message.linear_acceleration.z = index + 1.3
    return message


def _build_bag(
    path: Path,
    *,
    include_imu: bool = True,
    nonmonotonic_camera_header: bool = False,
    bad_camera_schema: bool = False,
) -> None:
    events: list[tuple[int, str, object]] = []
    for index, stamp_ns in enumerate(CAMERA_STAMPS):
        header_ns = stamp_ns
        if nonmonotonic_camera_header and index == 2:
            header_ns = CAMERA_STAMPS[0] - 1
        events.append(
            (
                stamp_ns,
                adapter.CAMERA_TOPIC,
                _image(header_ns, index, bad_schema=bad_camera_schema and index == 1),
            )
        )
    if include_imu:
        for index, stamp_ns in enumerate(IMU_STAMPS):
            events.append((stamp_ns, adapter.IMU_TOPIC, _imu(stamp_ns, index)))
    with rosbag.Bag(str(path), "w", chunk_threshold=128) as bag:
        for record_ns, topic, message in sorted(events, key=lambda row: row[0]):
            bag.write(topic, message, _time(record_ns))


def _source_identity(path: Path) -> tuple[int, str]:
    return path.stat().st_size, hashlib.sha256(path.read_bytes()).hexdigest()


def _upstream_audit() -> dict[str, object]:
    return {
        "root": "/synthetic/read-only-hfnet",
        "actual_commit": adapter.HFNET_COMMIT,
        "errors": [],
    }


def _prepare_fixture(path: Path, contract: adapter.PrefixContract = FIXTURE_CONTRACT):
    size, digest = _source_identity(path)
    with mock.patch.object(
        adapter, "audit_hfnet_checkout", return_value=_upstream_audit()
    ):
        return adapter.prepare(
            path,
            Path("/synthetic/read-only-hfnet"),
            contract=contract,
            expected_size=size,
            expected_sha256=digest,
        )


class AqualocHfnetEurocV1Tests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.source = self.root / "source.bag"

    def test_production_contract_is_frozen(self) -> None:
        contract = adapter.A02_PREFIX_CONTRACT
        self.assertEqual(adapter.SOURCE_SIZE_BYTES, 222_477_260)
        self.assertEqual(
            adapter.SOURCE_SHA256,
            "8cceb4c76065f3862e60428b14ba10f9a26fc7249e11e9e9d090fed2437238a8",
        )
        self.assertEqual((contract.image_first_index, contract.image_last_index), (0, 199))
        self.assertEqual((contract.imu_first_index, contract.imu_last_index), (38, 2027))
        self.assertEqual(contract.image_count, 200)
        self.assertEqual(contract.imu_count, 1990)

    def test_hfnet_checkout_identity_is_frozen(self) -> None:
        self.assertEqual(
            adapter.HFNET_COMMIT, "c354c72588a97bb6f6a9c7c8317530795956ec80"
        )
        self.assertEqual(
            adapter.HFNET_ORIGIN,
            "https://github.com/LiuLimingCode/HFNet_SLAM.git",
        )
        self.assertEqual(len(adapter.HFNET_FILE_SHA256), 6)
        self.assertIn(
            "Examples/Monocular-Inertial/mono_inertial_euroc.cc",
            adapter.HFNET_FILE_SHA256,
        )

    def test_kalibr_shift_rounding_is_exact(self) -> None:
        self.assertEqual(
            round(-adapter.KALIBR_TIMESHIFT_CAM_IMU_S * 1e9),
            adapter.IMU_OUTPUT_SHIFT_NS,
        )
        self.assertEqual(adapter.IMU_OUTPUT_SHIFT_NS, 53_694_112)
        self.assertEqual(adapter.shifted_imu_stamp_ns(100), 53_694_212)

    def test_csv_has_expected_order_and_no_final_newline(self) -> None:
        sample = adapter.ImuSample(
            source_index=38,
            raw_header_ns=100,
            output_header_ns=110,
            record_ns=100,
            gyro_xyz=(1.0, 2.0, 3.0),
            accel_xyz=(4.0, 5.0, 6.0),
        )
        payload = adapter.imu_csv_bytes([sample])
        self.assertFalse(payload.endswith(b"\n"))
        lines = payload.decode().splitlines()
        self.assertEqual(lines[0], adapter.CSV_HEADER)
        self.assertEqual(lines[1], "110,1,2,3,4,5,6")

    def test_synthetic_export_has_exact_layout_pixels_and_times(self) -> None:
        _build_bag(self.source)
        source_hash, upstream, selection = _prepare_fixture(self.source)
        output = self.root / "sequence"
        manifest = adapter.write_artifact(
            output,
            self.source,
            source_hash,
            selection,
            FIXTURE_CONTRACT,
            upstream,
        )
        self.assertEqual(manifest["status"], adapter.STATUS_EXPORTED)
        self.assertFalse(manifest["claims"]["hfnet_started"])
        image_paths = sorted((output / "mav0/cam0/data").glob("*.png"))
        self.assertEqual([path.stem for path in image_paths], [str(x) for x in CAMERA_STAMPS])
        for index, path in enumerate(image_paths):
            decoded = cv2.imread(str(path), cv2.IMREAD_UNCHANGED)
            expected = np.frombuffer(selection.cameras[index].pixels, dtype=np.uint8).reshape(2, 3)
            self.assertTrue(np.array_equal(decoded, expected))
        self.assertEqual(
            (output / "cam0_times.txt").read_text().splitlines(),
            [str(x) for x in CAMERA_STAMPS],
        )
        csv_payload = (output / "mav0/imu0/data.csv").read_bytes()
        self.assertFalse(csv_payload.endswith(b"\n"))
        output_stamps = [
            int(line.split(b",", 1)[0]) for line in csv_payload.splitlines()[1:]
        ]
        self.assertEqual(output_stamps, [x + 10 for x in IMU_STAMPS[1:5]])
        loaded_manifest = json.loads((output / "conversion_manifest.json").read_text())
        self.assertEqual(loaded_manifest["camera"]["count"], 3)
        self.assertEqual(loaded_manifest["imu"]["count"], 4)

    def test_wrong_source_sha_fails_before_output(self) -> None:
        _build_bag(self.source)
        size, _ = _source_identity(self.source)
        with mock.patch.object(
            adapter, "audit_hfnet_checkout", return_value=_upstream_audit()
        ):
            with self.assertRaisesRegex(
                adapter.ContractError, "SOURCE_BAG_SHA256_MISMATCH"
            ):
                adapter.prepare(
                    self.source,
                    Path("/synthetic/read-only-hfnet"),
                    contract=FIXTURE_CONTRACT,
                    expected_size=size,
                    expected_sha256="0" * 64,
                )

    def test_missing_imu_topic_fails_closed(self) -> None:
        _build_bag(self.source, include_imu=False)
        with self.assertRaisesRegex(adapter.ContractError, "IMU_TOPIC_MISSING"):
            _prepare_fixture(self.source)

    def test_nonmonotonic_camera_header_fails_closed(self) -> None:
        _build_bag(self.source, nonmonotonic_camera_header=True)
        with self.assertRaisesRegex(
            adapter.ContractError, "RECORD_HEADER_STAMP_MISMATCH"
        ):
            _prepare_fixture(self.source)

    def test_bad_camera_schema_fails_closed(self) -> None:
        _build_bag(self.source, bad_camera_schema=True)
        with self.assertRaisesRegex(
            adapter.ContractError, "CAMERA_DIMENSION_MISMATCH"
        ):
            _prepare_fixture(self.source)

    def test_existing_output_is_never_clobbered(self) -> None:
        _build_bag(self.source)
        source_hash, upstream, selection = _prepare_fixture(self.source)
        output = self.root / "sequence"
        output.mkdir()
        marker = output / "owner.txt"
        marker.write_text("preserve", encoding="utf-8")
        with self.assertRaisesRegex(adapter.ContractError, "OUTPUT_ALREADY_EXISTS"):
            adapter.write_artifact(
                output,
                self.source,
                source_hash,
                selection,
                FIXTURE_CONTRACT,
                upstream,
            )
        self.assertEqual(marker.read_text(), "preserve")

    def test_encoding_failure_rolls_back_atomic_staging(self) -> None:
        _build_bag(self.source)
        source_hash, upstream, selection = _prepare_fixture(self.source)
        output = self.root / "sequence"
        with mock.patch.object(
            adapter,
            "encode_lossless_png",
            side_effect=adapter.ContractError("PNG_ENCODE_FAILED:synthetic"),
        ):
            with self.assertRaisesRegex(adapter.ContractError, "PNG_ENCODE_FAILED"):
                adapter.write_artifact(
                    output,
                    self.source,
                    source_hash,
                    selection,
                    FIXTURE_CONTRACT,
                    upstream,
                )
        self.assertFalse(output.exists())
        self.assertEqual([path.name for path in self.root.iterdir()], ["source.bag"])


if __name__ == "__main__":
    unittest.main()
