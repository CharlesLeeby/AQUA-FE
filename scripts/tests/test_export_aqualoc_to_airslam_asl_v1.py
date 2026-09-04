#!/usr/bin/env python3
"""Isolated contract tests for the fail-closed AirSLAM ASL adapter."""

from __future__ import annotations

import copy
import tempfile
import unittest
from pathlib import Path

import genpy
import rosbag
from sensor_msgs.msg import Image, Imu

from scripts import export_aqualoc_to_airslam_asl_v1 as adapter


def _time(stamp_ns: int) -> genpy.Time:
    return genpy.Time(stamp_ns // 1_000_000_000, stamp_ns % 1_000_000_000)


def _identity() -> list[list[float]]:
    return [
        [1.0, 0.0, 0.0, 0.0],
        [0.0, 1.0, 0.0, 0.0],
        [0.0, 0.0, 1.0, 0.0],
        [0.0, 0.0, 0.0, 1.0],
    ]


def _ntnu_calibration_fixture():
    t_cam1_cam0 = _identity()
    t_cam1_cam0[0][3] = 0.11
    camera = {
        "cam0": {
            "rostopic": "/alphasense_driver_ros/cam0",
            "camera_model": "pinhole",
            "distortion_model": "equidistant",
            "resolution": [720, 540],
            "intrinsics": [460.0, 461.0, 358.0, 266.0],
            "distortion_coeffs": [0.04, 0.17, -0.3, 0.47],
        },
        "cam1": {
            "rostopic": "/alphasense_driver_ros/cam1",
            "camera_model": "pinhole",
            "distortion_model": "equidistant",
            "resolution": [720, 540],
            "intrinsics": [457.0, 458.0, 357.0, 261.0],
            "distortion_coeffs": [0.04, 0.16, -0.25, 0.42],
            "T_cn_cnm1": t_cam1_cam0,
        },
    }
    imucam = {
        "cam0": {
            **copy.deepcopy(camera["cam0"]),
            "T_cam_imu": _identity(),
            "timeshift_cam_imu": 0.001765,
        },
        "cam1": {
            **copy.deepcopy(camera["cam1"]),
            "T_cam_imu": t_cam1_cam0,
            "timeshift_cam_imu": 0.001770,
        },
    }
    imu = {
        "rostopic": "/alphasense_driver_ros/imu",
        "update_rate": 200.0,
        "accelerometer_noise_density": 0.0186,
        "accelerometer_random_walk": 0.00433,
        "gyroscope_noise_density": 0.000587,
        "gyroscope_random_walk": 0.002866,
    }
    return camera, imucam, imu


class AirslamAslAdapterV1Tests(unittest.TestCase):
    def test_paper_era_identity_is_frozen(self) -> None:
        self.assertEqual(
            adapter.AIRSLAM_COMMIT,
            "2b825166b05b351fc708c70cee3fc8b5a5b380e9",
        )
        self.assertEqual(len(adapter.AIRSLAM_FILE_HASHES), 7)
        self.assertIn("src/dataset.cc", adapter.AIRSLAM_FILE_HASHES)
        self.assertIn("src/map_builder.cc", adapter.AIRSLAM_FILE_HASHES)

    def test_a02_is_blocked_without_cam1_topic_and_calibration(self) -> None:
        blockers = adapter.modal_blockers(
            "/camera/image_raw",
            None,
            "/rtimulib_node/imu",
            {
                "/camera/image_raw": {},
                "/rtimulib_node/imu": {},
                "/aqualoc/colmap_gt": {},
            },
            ["cam0"],
        )
        self.assertEqual(
            blockers,
            [
                "AIRSLAM_REQUIRES_INDEPENDENT_CAM1_TOPIC",
                "AIRSLAM_REQUIRES_CAM1_CALIBRATION",
            ],
        )

    def test_aliasing_cam0_as_cam1_is_forbidden(self) -> None:
        blockers = adapter.modal_blockers(
            "/cam",
            "/cam",
            "/imu",
            {"/cam": {}, "/imu": {}},
            ["cam0", "cam1"],
        )
        self.assertIn("CAM0_CAM1_TOPIC_ALIAS_FORBIDDEN", blockers)

    def test_imu_timestamp_is_shifted_into_camera_clock(self) -> None:
        raw_ns = 1_700_603_752_857_818_564
        self.assertEqual(
            adapter.shift_imu_timestamp_ns(raw_ns, 0.0017656238182069367),
            raw_ns - 1_765_624,
        )
        self.assertEqual(
            adapter.shift_imu_timestamp_ns(raw_ns, -0.053694112369382575),
            raw_ns + 53_694_112,
        )

    def test_integer_nanosecond_name_matches_airslam_parser(self) -> None:
        stamp_ns = 1_700_603_752_857_818_564
        parsed = adapter.airslam_string_time_to_seconds(str(stamp_ns))
        self.assertAlmostEqual(parsed, stamp_ns / 1e9, places=6)

    def test_exact_real_stereo_rows_pass(self) -> None:
        left = [
            adapter.ImageRow(10, 11, "left-a"),
            adapter.ImageRow(20, 21, "left-b"),
        ]
        right = [
            adapter.ImageRow(10, 12, "right-a"),
            adapter.ImageRow(20, 22, "right-b"),
        ]
        result = adapter.validate_stereo_rows(left, right, 2)
        self.assertTrue(result["all_pairs_exact_header_match"])
        self.assertEqual(result["identical_payload_pair_count"], 0)

    def test_copied_left_stream_is_rejected(self) -> None:
        left = [adapter.ImageRow(10, 11, "same")]
        right = [adapter.ImageRow(10, 12, "same")]
        with self.assertRaisesRegex(
            adapter.ContractError, "CAM0_DUPLICATED_AS_CAM1_FORBIDDEN"
        ):
            adapter.validate_stereo_rows(left, right, 1)

    def test_stereo_header_mismatch_is_rejected(self) -> None:
        left = [adapter.ImageRow(10, 11, "left")]
        right = [adapter.ImageRow(11, 12, "right")]
        with self.assertRaisesRegex(
            adapter.ContractError, "STEREO_HEADER_TIMESTAMP_SETS_DIFFER"
        ):
            adapter.validate_stereo_rows(left, right, 1)

    def test_ntnu_camera_config_uses_water_stereo_transform(self) -> None:
        camera, imucam, imu = _ntnu_calibration_fixture()
        audit = adapter.validate_ntnu_calibrations(
            adapter.PROFILES["ntnu-fjord6-0001"], camera, imucam, imu
        )
        self.assertAlmostEqual(audit["underwater_stereo_baseline_m"], 0.11)
        config = adapter.build_ntnu_airslam_camera_config(camera, imucam, imu)
        self.assertEqual(config["distortion_type"], 2)
        self.assertEqual(config["cam0"]["T_type"], 1)
        self.assertEqual(config["cam1"]["T_type"], 1)
        self.assertAlmostEqual(config["cam1"]["T"][0][3], 0.11)
        self.assertEqual(len(config["cam0"]["distortion_coeffs"]), 5)
        self.assertEqual(config["cam0"]["distortion_coeffs"][-1], 0.0)

    def test_vo_config_changes_only_input_dimensions(self) -> None:
        official = {
            "plnet": {"use_superpoint": 1, "max_keypoints": 400},
            "point_matcher": {
                "matcher": 0,
                "image_width": 752,
                "image_height": 480,
                "onnx_file": "unchanged.onnx",
            },
            "keyframe": {"min_init_stereo_feature": 90},
        }
        adapted = adapter.build_ntnu_vo_io_config(official)
        self.assertEqual(adapted["point_matcher"]["image_width"], 720)
        self.assertEqual(adapted["point_matcher"]["image_height"], 540)
        self.assertEqual(adapted["point_matcher"]["matcher"], 0)
        self.assertEqual(adapted["keyframe"], official["keyframe"])
        self.assertEqual(official["point_matcher"]["image_width"], 752)

    def test_fast_footer_inspection_reports_exact_topic_counts(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            bag_path = Path(temporary) / "tiny.bag"
            image = Image()
            image.height = 1
            image.width = 1
            image.encoding = "mono8"
            image.step = 1
            image.data = b"\x01"
            imu = Imu()
            with rosbag.Bag(str(bag_path), "w", chunk_threshold=128) as bag:
                for index in range(2):
                    stamp = _time(1_700_000_000_000_000_000 + index)
                    image.header.stamp = stamp
                    bag.write("/cam0", image, stamp)
                stamp = _time(1_700_000_000_000_000_010)
                imu.header.stamp = stamp
                bag.write("/imu", imu, stamp)
            topics = adapter.inspect_bag_topics(bag_path)
        self.assertEqual(topics["/cam0"]["message_type"], "sensor_msgs/Image")
        self.assertEqual(topics["/cam0"]["message_count"], 2)
        self.assertEqual(topics["/imu"]["message_type"], "sensor_msgs/Imu")
        self.assertEqual(topics["/imu"]["message_count"], 1)

    def test_atomic_directory_rolls_back_and_never_clobbers(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary) / "artifact"
            with self.assertRaisesRegex(RuntimeError, "synthetic failure"):
                with adapter.atomic_directory(target) as staging:
                    (staging / "partial.txt").write_text("partial", encoding="utf-8")
                    raise RuntimeError("synthetic failure")
            self.assertFalse(target.exists())
            self.assertEqual(list(Path(temporary).iterdir()), [])
            target.mkdir()
            with self.assertRaisesRegex(adapter.ContractError, "OUTPUT_ALREADY_EXISTS"):
                with adapter.atomic_directory(target):
                    pass


if __name__ == "__main__":
    unittest.main()
