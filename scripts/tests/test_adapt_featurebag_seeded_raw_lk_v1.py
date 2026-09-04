from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import genpy
import numpy as np
import rosbag
from geometry_msgs.msg import Point32
from nav_msgs.msg import Odometry
from sensor_msgs.msg import ChannelFloat32, Image, Imu, PointCloud

from scripts import adapt_featurebag_seeded_raw_lk_v1 as adapter


FEATURE_TOPIC = "/feature_tracker/feature"
IMAGE_TOPIC = "/camera/image_raw"
IMU_TOPIC = "/imu"
GT_TOPIC = "/ground_truth"


def _time(nanoseconds: int) -> genpy.Time:
    return genpy.Time(nanoseconds // 1_000_000_000, nanoseconds % 1_000_000_000)


def _feature_frame(stamp_ns: int, ids: list[int], pixels: list[list[float]]):
    return adapter.FeatureFrame(
        header_stamp_ns=stamp_ns,
        record_stamp_ns=stamp_ns,
        ids=np.asarray(ids, dtype=np.int64),
        pixels=np.asarray(pixels, dtype=np.float32),
    )


def _raw_frame(stamp_ns: int, value: int):
    return adapter.RawFrame(
        header_stamp_ns=stamp_ns,
        image=np.full((48, 64), value, dtype=np.uint8),
    )


def _diagnostics(frames: list[adapter.FeatureFrame]):
    rows = []
    for index, frame in enumerate(frames):
        rows.append(
            adapter.FrameCarrierDiagnostics(
                frame_index=index,
                header_stamp_ns=frame.header_stamp_ns,
                observation_count=len(frame.ids),
                birth_count=len(frame.ids) if index == 0 else 0,
                continuation_count=0 if index == 0 else len(frame.ids),
                accepted_count=0 if index == 0 else len(frame.ids),
                fallback_count=0,
                removed_count=0,
                accepted_fraction=float("nan") if index == 0 else 1.0,
                fb_median_px=float("nan") if index == 0 else 0.0,
                fb_p95_px=float("nan") if index == 0 else 0.0,
                correction_median_px=0.0,
                correction_p95_px=0.0,
            )
        )
    return rows


def _image_message(stamp_ns: int, value: int) -> Image:
    message = Image()
    message.header.stamp = _time(stamp_ns)
    message.header.frame_id = "cam0"
    message.height = 48
    message.width = 64
    message.encoding = "mono8"
    message.is_bigendian = 0
    message.step = 64
    message.data = bytes([value]) * (48 * 64)
    return message


CHANNEL_NAMES = (
    "id",
    "camera_id",
    "p_u",
    "p_v",
    "velocity_x",
    "velocity_y",
    "gx",
    "gy",
    "gz",
    "quality",
    "sigma",
    "source_code",
    "is_learned",
)


def _feature_message(
    stamp_ns: int, ids: list[int], pixels: list[list[float]]
) -> PointCloud:
    message = PointCloud()
    message.header.stamp = _time(stamp_ns)
    message.header.frame_id = "world"
    message.points = [
        Point32(9.0 + index, 8.0 + index, 1.0)
        for index in range(len(ids))
    ]
    values = {
        "id": [float(value) for value in ids],
        "camera_id": [0.0] * len(ids),
        "p_u": [float(value[0]) for value in pixels],
        "p_v": [float(value[1]) for value in pixels],
        "velocity_x": [91.0 + index for index in range(len(ids))],
        "velocity_y": [81.0 + index for index in range(len(ids))],
        "gx": [71.0 + index for index in range(len(ids))],
        "gy": [61.0 + index for index in range(len(ids))],
        "gz": [51.0 + index for index in range(len(ids))],
        "quality": [0.71 + index * 0.01 for index in range(len(ids))],
        "sigma": [1.11 + index * 0.01 for index in range(len(ids))],
        "source_code": [20.0] * len(ids),
        "is_learned": [1.0] * len(ids),
    }
    message.channels = [
        ChannelFloat32(name=name, values=values[name]) for name in CHANNEL_NAMES
    ]
    return message


def _imu_message(stamp_ns: int, value: float) -> Imu:
    message = Imu()
    message.header.stamp = _time(stamp_ns)
    message.linear_acceleration.x = value
    message.angular_velocity.z = -value
    return message


def _gt_message(stamp_ns: int, value: float) -> Odometry:
    message = Odometry()
    message.header.stamp = _time(stamp_ns)
    message.header.frame_id = "world"
    message.pose.pose.position.x = value
    message.pose.pose.orientation.w = 1.0
    return message


def _write_raw_bag(path: Path, stamps_ns: list[int]) -> None:
    with rosbag.Bag(str(path), "w") as bag:
        for index, stamp_ns in enumerate(stamps_ns):
            bag.write(IMAGE_TOPIC, _image_message(stamp_ns, index), _time(stamp_ns))


def _write_feature_bag(
    path: Path,
    stamps_ns: list[int],
    ids_by_frame: list[list[int]],
    pixels_by_frame: list[list[list[float]]],
) -> None:
    with rosbag.Bag(str(path), "w") as bag:
        bag.write(
            IMU_TOPIC,
            _imu_message(stamps_ns[0] - 10_000_000, 1.25),
            _time(stamps_ns[0] - 10_000_000),
        )
        for index, stamp_ns in enumerate(stamps_ns):
            bag.write(
                FEATURE_TOPIC,
                _feature_message(stamp_ns, ids_by_frame[index], pixels_by_frame[index]),
                _time(stamp_ns),
            )
            bag.write(
                IMU_TOPIC,
                _imu_message(stamp_ns + 10_000_000, 2.5 + index),
                _time(stamp_ns + 10_000_000),
            )
            bag.write(
                GT_TOPIC,
                _gt_message(stamp_ns + 20_000_000, 3.5 + index),
                _time(stamp_ns + 20_000_000),
            )


def _write_camera_yaml(path: Path) -> None:
    path.write_text(
        "model_type: PINHOLE\n"
        "projection_parameters:\n"
        "  fx: 100.0\n"
        "  fy: 100.0\n"
        "  cx: 0.0\n"
        "  cy: 0.0\n"
        "distortion_parameters:\n"
        "  k1: 0.0\n"
        "  k2: 0.0\n"
        "  p1: 0.0\n"
        "  p2: 0.0\n",
        encoding="utf-8",
    )


def _channel_values(message: PointCloud) -> dict[str, list[float]]:
    return {channel.name: list(channel.values) for channel in message.channels}


class SeededRawLKUnitTests(unittest.TestCase):
    def test_input_point_z_must_be_finite_and_exactly_one(self) -> None:
        for invalid_z in (float("nan"), float("inf"), 0.999999):
            with self.subTest(invalid_z=invalid_z):
                message = _feature_message(100, [1], [[10.0, 20.0]])
                message.points[0].z = invalid_z
                with self.assertRaisesRegex(
                    ValueError, "point.z must be finite and exactly 1.0"
                ):
                    adapter._frame_from_message(message, 100)

    def test_seeded_lk_uses_exact_frozen_probe_parameters(self) -> None:
        image0 = np.zeros((24, 32), dtype=np.uint8)
        image1 = np.ones((24, 32), dtype=np.uint8)
        points0 = np.asarray([[4.0, 5.0], [8.0, 9.0]], dtype=np.float32)
        seed = np.asarray([[4.5, 5.0], [8.5, 9.0]], dtype=np.float32)
        returned = seed.reshape(-1, 1, 2).copy()
        status = np.ones((2, 1), dtype=np.uint8)
        error = np.zeros((2, 1), dtype=np.float32)

        with mock.patch.object(
            adapter.cv2,
            "calcOpticalFlowPyrLK",
            return_value=(returned, status, error),
        ) as optical_flow:
            points1, valid = adapter._seeded_lk(image0, image1, points0, seed)

        np.testing.assert_array_equal(points1, seed)
        np.testing.assert_array_equal(valid, [True, True])
        args, kwargs = optical_flow.call_args
        self.assertIs(args[0], image0)
        self.assertIs(args[1], image1)
        np.testing.assert_array_equal(args[2].reshape(-1, 2), points0)
        np.testing.assert_array_equal(args[3].reshape(-1, 2), seed)
        self.assertEqual(kwargs["winSize"], (21, 21))
        self.assertEqual(kwargs["maxLevel"], 3)
        self.assertEqual(
            kwargs["criteria"],
            (adapter.cv2.TERM_CRITERIA_EPS | adapter.cv2.TERM_CRITERIA_COUNT, 30, 0.01),
        )
        self.assertEqual(kwargs["flags"], adapter.cv2.OPTFLOW_USE_INITIAL_FLOW)
        self.assertEqual(kwargs["minEigThreshold"], 1e-4)

    def test_start_middle_end_seeds_and_fail_open_preserve_occurrences(self) -> None:
        feature_frames = [
            _feature_frame(100, [101, 202], [[10.0, 10.0], [20.0, 20.0]]),
            _feature_frame(
                200,
                [202, 303, 101],
                [[22.0, 20.0], [30.0, 30.0], [12.0, 10.0]],
            ),
        ]
        raw_frames = [_raw_frame(100, 0), _raw_frame(150, 1), _raw_frame(200, 2)]
        point1 = np.asarray([[21.1, 20.0], [11.1, 10.0]], dtype=np.float32)
        point2 = np.asarray([[22.2, 20.0], [12.2, 10.0]], dtype=np.float32)
        point1_back = np.asarray([[21.0, 20.0], [11.0, 10.0]], dtype=np.float32)
        point0_back = np.asarray([[20.2, 20.0], [10.2, 10.0]], dtype=np.float32)
        side_effect = [
            (point1, np.asarray([True, True])),
            (point2, np.asarray([True, True])),
            (point1_back, np.asarray([True, False])),
            (point0_back, np.asarray([True, True])),
        ]

        with mock.patch.object(adapter, "_seeded_lk", side_effect=side_effect) as seeded:
            adapted, diagnostics = adapter.adapt_pixel_frames(feature_frames, raw_frames)

        self.assertEqual(seeded.call_count, 4)
        expected_start = np.asarray([[20.0, 20.0], [10.0, 10.0]], dtype=np.float32)
        expected_end_seed = np.asarray([[22.0, 20.0], [12.0, 10.0]], dtype=np.float32)
        expected_middle_seed = (expected_start + expected_end_seed) * 0.5
        calls = seeded.call_args_list
        self.assertIs(calls[0].args[0], raw_frames[0].image)
        self.assertIs(calls[0].args[1], raw_frames[1].image)
        np.testing.assert_array_equal(calls[0].args[2], expected_start)
        np.testing.assert_array_equal(calls[0].args[3], expected_middle_seed)
        self.assertIs(calls[1].args[0], raw_frames[1].image)
        self.assertIs(calls[1].args[1], raw_frames[2].image)
        np.testing.assert_array_equal(calls[1].args[2], point1)
        np.testing.assert_array_equal(calls[1].args[3], expected_end_seed)
        self.assertIs(calls[2].args[0], raw_frames[2].image)
        self.assertIs(calls[2].args[1], raw_frames[1].image)
        np.testing.assert_array_equal(calls[2].args[2], point2)
        np.testing.assert_array_equal(calls[2].args[3], point1)
        self.assertIs(calls[3].args[0], raw_frames[1].image)
        self.assertIs(calls[3].args[1], raw_frames[0].image)
        np.testing.assert_array_equal(calls[3].args[2], point1_back)
        np.testing.assert_array_equal(calls[3].args[3], expected_start)

        np.testing.assert_array_equal(adapted[0], feature_frames[0].pixels)
        np.testing.assert_array_equal(
            adapted[1],
            np.asarray([[22.2, 20.0], [30.0, 30.0], [12.0, 10.0]], dtype=np.float32),
        )
        self.assertEqual(diagnostics[1].observation_count, 3)
        self.assertEqual(diagnostics[1].continuation_count, 2)
        self.assertEqual(diagnostics[1].birth_count, 1)
        self.assertEqual(diagnostics[1].accepted_count, 1)
        self.assertEqual(diagnostics[1].fallback_count, 1)
        self.assertEqual(diagnostics[1].removed_count, 0)

    def test_nonfinite_lk_chain_never_commits_published_point(self) -> None:
        frames = [
            _feature_frame(100, [1], [[10.0, 10.0]]),
            _feature_frame(200, [1], [[12.0, 10.0]]),
        ]
        raw = [_raw_frame(100, 0), _raw_frame(150, 1), _raw_frame(200, 2)]
        all_valid = np.asarray([True])
        side_effect = [
            (np.asarray([[11.0, 10.0]], np.float32), all_valid),
            (np.asarray([[np.nan, 10.0]], np.float32), all_valid),
            (np.asarray([[11.0, 10.0]], np.float32), all_valid),
            (np.asarray([[10.0, 10.0]], np.float32), all_valid),
        ]
        with mock.patch.object(adapter, "_seeded_lk", side_effect=side_effect):
            adapted, diagnostics = adapter.adapt_pixel_frames(frames, raw)
        np.testing.assert_array_equal(adapted[1], frames[1].pixels)
        self.assertEqual(diagnostics[1].accepted_count, 0)
        self.assertEqual(diagnostics[1].fallback_count, 1)

    def test_fixed_stride_two_and_exact_stamp_join_are_hard_requirements(self) -> None:
        frames = [
            _feature_frame(100, [1], [[1.0, 1.0]]),
            _feature_frame(300, [1], [[2.0, 1.0]]),
        ]
        bad_stride = [
            _raw_frame(100, 0),
            _raw_frame(150, 1),
            _raw_frame(250, 2),
            _raw_frame(300, 3),
        ]
        with self.assertRaisesRegex(ValueError, "exactly two raw frames apart"):
            adapter._raw_indices_for_features(frames, bad_stride)
        with self.assertRaisesRegex(ValueError, "missing exact raw-image matches"):
            adapter._raw_indices_for_features(frames, bad_stride[:-1])

    def test_normalization_and_velocity_use_adjacent_published_true_dt(self) -> None:
        frames = [
            _feature_frame(1_000_000_000, [5], [[110.0, 220.0]]),
            _feature_frame(
                1_200_000_000, [7, 5], [[10.0, 20.0], [210.0, 420.0]]
            ),
        ]
        camera = np.asarray(
            [[100.0, 0.0, 10.0], [0.0, 200.0, 20.0], [0.0, 0.0, 1.0]],
            dtype=np.float64,
        )
        normalized = adapter.normalized_frames(
            [frame.pixels for frame in frames], camera, np.zeros(4, dtype=np.float64)
        )
        velocity = adapter.velocity_frames(frames, normalized)

        np.testing.assert_allclose(normalized[0], [[1.0, 1.0]], atol=1e-7)
        np.testing.assert_allclose(normalized[1], [[0.0, 0.0], [2.0, 2.0]], atol=1e-7)
        np.testing.assert_array_equal(velocity[0], [[0.0, 0.0]])
        np.testing.assert_array_equal(velocity[1][0], [0.0, 0.0])
        np.testing.assert_allclose(velocity[1][1], [5.0, 5.0], atol=1e-6)


class SeededRawLKBagAdapterTests(unittest.TestCase):
    def test_bag_adapter_changes_only_coordinate_contract_and_never_clobbers(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.bag"
            raw = root / "raw.bag"
            camera = root / "camera.yaml"
            output = root / "adapted.bag"
            diagnostics_path = root / "diagnostics.json"
            stamps = [1_000_000_000, 1_100_000_000, 1_200_000_000]
            raw_stamps = [
                1_000_000_000,
                1_050_000_000,
                1_100_000_000,
                1_150_000_000,
                1_200_000_000,
            ]
            ids = [[10, 20], [20, 10, 30], [10, 30]]
            source_pixels = [
                [[20.0, 10.0], [30.0, 20.0]],
                [[31.0, 20.0], [21.0, 10.0], [40.0, 25.0]],
                [[22.0, 10.0], [41.0, 25.0]],
            ]
            adapted_pixels = [
                np.asarray(source_pixels[0], dtype=np.float32),
                np.asarray([[31.2, 20.0], [21.2, 10.0], [40.0, 25.0]], dtype=np.float32),
                np.asarray([[22.4, 10.0], [41.2, 25.0]], dtype=np.float32),
            ]
            _write_feature_bag(source, stamps, ids, source_pixels)
            _write_raw_bag(raw, raw_stamps)
            _write_camera_yaml(camera)

            expected_frames = adapter.read_feature_frames(source, FEATURE_TOPIC)
            with mock.patch.object(
                adapter,
                "adapt_pixel_frames",
                return_value=(adapted_pixels, _diagnostics(expected_frames)),
            ):
                report = adapter.adapt_bag(
                    source,
                    raw,
                    camera,
                    output,
                    image_topic=IMAGE_TOPIC,
                    diagnostics_json=diagnostics_path,
                )

            self.assertFalse(report["truncated"])
            self.assertEqual(report["feature_frames"], 3)
            self.assertTrue(output.is_file())
            self.assertTrue(diagnostics_path.is_file())
            diagnostics_text = diagnostics_path.read_text(encoding="utf-8")
            parsed_diagnostics = json.loads(diagnostics_text)
            self.assertNotIn("NaN", diagnostics_text)
            self.assertIsNone(parsed_diagnostics["frame_diagnostics"][0]["fb_median_px"])
            self.assertIsNone(
                parsed_diagnostics["frame_diagnostics"][0]["accepted_fraction"]
            )
            for artifact_name, artifact_path in (
                ("source_feature_bag", source),
                ("raw_image_bag", raw),
                ("camera_yaml", camera),
                ("output_bag", output),
                ("adapter_source", Path(adapter.__file__).resolve()),
            ):
                metadata = report["artifacts"][artifact_name]
                self.assertEqual(metadata["size_bytes"], artifact_path.stat().st_size)
                self.assertEqual(metadata["sha256"], adapter._sha256_file(artifact_path))
            self.assertEqual(
                report["preserved_topic_digests_before"],
                report["preserved_topic_digests_after"],
            )
            self.assertEqual(
                adapter._topic_content_digest(source, {IMU_TOPIC, GT_TOPIC}),
                adapter._topic_content_digest(output, {IMU_TOPIC, GT_TOPIC}),
            )

            with rosbag.Bag(str(source), "r") as source_bag:
                source_rows = list(source_bag.read_messages(topics=[FEATURE_TOPIC]))
            with rosbag.Bag(str(output), "r") as output_bag:
                output_rows = list(output_bag.read_messages(topics=[FEATURE_TOPIC]))
            self.assertEqual(len(source_rows), len(output_rows))

            expected_normalized = [pixels / 100.0 for pixels in adapted_pixels]
            expected_velocities = [
                np.zeros((2, 2), dtype=np.float32),
                np.asarray([[0.12, 0.0], [0.12, 0.0], [0.0, 0.0]], dtype=np.float32),
                np.asarray([[0.12, 0.0], [0.12, 0.0]], dtype=np.float32),
            ]
            immutable_channels = set(CHANNEL_NAMES) - {
                "p_u",
                "p_v",
                "velocity_x",
                "velocity_y",
            }
            for frame_index, (source_row, output_row) in enumerate(
                zip(source_rows, output_rows)
            ):
                source_topic, source_message, source_stamp = source_row
                output_topic, output_message, output_stamp = output_row
                self.assertEqual(output_topic, source_topic)
                self.assertEqual(output_stamp.to_nsec(), source_stamp.to_nsec())
                self.assertEqual(
                    output_message.header.stamp.to_nsec(),
                    source_message.header.stamp.to_nsec(),
                )
                self.assertEqual(output_message.header.frame_id, source_message.header.frame_id)
                self.assertEqual(
                    [channel.name for channel in output_message.channels],
                    [channel.name for channel in source_message.channels],
                )
                source_channels = _channel_values(source_message)
                output_channels = _channel_values(output_message)
                for channel_name in immutable_channels:
                    self.assertEqual(
                        output_channels[channel_name], source_channels[channel_name]
                    )
                np.testing.assert_allclose(
                    output_channels["p_u"], adapted_pixels[frame_index][:, 0], atol=1e-6
                )
                np.testing.assert_allclose(
                    output_channels["p_v"], adapted_pixels[frame_index][:, 1], atol=1e-6
                )
                np.testing.assert_allclose(
                    output_channels["velocity_x"],
                    expected_velocities[frame_index][:, 0],
                    atol=1e-6,
                )
                np.testing.assert_allclose(
                    output_channels["velocity_y"],
                    expected_velocities[frame_index][:, 1],
                    atol=1e-6,
                )
                np.testing.assert_allclose(
                    [[point.x, point.y] for point in output_message.points],
                    expected_normalized[frame_index],
                    atol=1e-6,
                )
                np.testing.assert_array_equal(
                    [point.z for point in output_message.points],
                    [point.z for point in source_message.points],
                )

            with self.assertRaisesRegex(FileExistsError, "refusing to overwrite"):
                adapter.adapt_bag(
                    source,
                    raw,
                    camera,
                    output,
                    image_topic=IMAGE_TOPIC,
                )

            failed_output = root / "diagnostics_failure.bag"
            with mock.patch.object(
                adapter,
                "adapt_pixel_frames",
                return_value=(adapted_pixels, _diagnostics(expected_frames)),
            ), mock.patch.object(
                adapter,
                "_write_json_no_clobber",
                side_effect=OSError("diagnostics failure"),
            ):
                with self.assertRaisesRegex(OSError, "diagnostics failure"):
                    adapter.adapt_bag(
                        source,
                        raw,
                        camera,
                        failed_output,
                        image_topic=IMAGE_TOPIC,
                        diagnostics_json=root / "failed.json",
                    )
            self.assertFalse(failed_output.exists())

    def test_optional_frame_limit_is_a_declared_prefix_not_a_silent_full_run(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.bag"
            raw = root / "raw.bag"
            camera = root / "camera.yaml"
            output = root / "prefix.bag"
            stamps = [2_000_000_000, 2_100_000_000, 2_200_000_000]
            _write_feature_bag(
                source,
                stamps,
                [[1], [1], [1]],
                [[[10.0, 10.0]], [[11.0, 10.0]], [[12.0, 10.0]]],
            )
            _write_raw_bag(
                raw,
                [
                    2_000_000_000,
                    2_050_000_000,
                    2_100_000_000,
                    2_150_000_000,
                    2_200_000_000,
                ],
            )
            _write_camera_yaml(camera)
            prefix_frames = adapter.read_feature_frames(
                source, FEATURE_TOPIC, max_feature_frames=2
            )
            prefix_pixels = [frame.pixels.copy() for frame in prefix_frames]

            with mock.patch.object(
                adapter,
                "adapt_pixel_frames",
                return_value=(prefix_pixels, _diagnostics(prefix_frames)),
            ), mock.patch.object(
                adapter, "_topic_content_digest", wraps=adapter._topic_content_digest
            ) as digest:
                report = adapter.adapt_bag(
                    source,
                    raw,
                    camera,
                    output,
                    image_topic=IMAGE_TOPIC,
                    max_feature_frames=2,
                )

            self.assertTrue(report["truncated"])
            self.assertEqual(report["feature_frames"], 2)
            self.assertEqual(
                report["digest_cutoff_record_stamp_ns"],
                prefix_frames[-1].record_stamp_ns,
            )
            self.assertEqual(
                report["preserved_topic_digests_before"],
                report["preserved_topic_digests_after"],
            )
            self.assertEqual(len(digest.call_args_list), 2)
            for call in digest.call_args_list:
                self.assertEqual(
                    call.kwargs["max_record_stamp_ns"],
                    prefix_frames[-1].record_stamp_ns,
                )
            with rosbag.Bag(str(output), "r") as bag:
                rows = list(bag.read_messages(topics=[FEATURE_TOPIC]))
            self.assertEqual(len(rows), 2)

            mismatch_output = root / "prefix_mismatch.bag"
            with mock.patch.object(
                adapter,
                "adapt_pixel_frames",
                return_value=(prefix_pixels, _diagnostics(prefix_frames)),
            ), mock.patch.object(
                adapter,
                "_topic_content_digest",
                side_effect=[
                    {IMU_TOPIC: {"count": 1, "sha256": "before"}},
                    {IMU_TOPIC: {"count": 1, "sha256": "after"}},
                ],
            ):
                with self.assertRaisesRegex(
                    RuntimeError, "content changed within the adaptation cutoff"
                ):
                    adapter.adapt_bag(
                        source,
                        raw,
                        camera,
                        mismatch_output,
                        image_topic=IMAGE_TOPIC,
                        max_feature_frames=2,
                    )
            self.assertFalse(mismatch_output.exists())


if __name__ == "__main__":
    unittest.main()
