from __future__ import annotations

import inspect
import json
import os
import subprocess
import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import genpy
from geometry_msgs.msg import Point32
import numpy as np
import rosbag
from sensor_msgs.msg import ChannelFloat32, Image, Imu, PointCloud
from std_msgs.msg import Header

from scripts import export_superpoint_lk_carrier_v1 as exporter


FEATURE_TOPIC = "/feature_tracker/feature"
IMAGE_TOPIC = "/camera/image_raw"
IMU_TOPIC = "/imu"


def _time(nanoseconds: int) -> genpy.Time:
    return genpy.Time(
        nanoseconds // 1_000_000_000,
        nanoseconds % 1_000_000_000,
    )


def _schedule_frame(stamp_ns: int, *, seq: int = 0) -> exporter.ScheduleFrame:
    header = Header(seq=seq, stamp=_time(stamp_ns), frame_id="world")
    return exporter.ScheduleFrame(
        header=header,
        header_stamp_ns=stamp_ns,
        record_stamp_ns=stamp_ns,
    )


def _raw_frame(stamp_ns: int, value: int = 0) -> exporter.RawFrame:
    return exporter.RawFrame(
        header_stamp_ns=stamp_ns,
        image=np.full((48, 96), value, dtype=np.uint8),
    )


def _identity_preprocess(image: np.ndarray) -> tuple[np.ndarray, bool]:
    return image.copy(), False


def _identity_tracker(
    _previous: np.ndarray,
    _current: np.ndarray,
    points: np.ndarray,
) -> exporter.TrackResult:
    count = len(points)
    return exporter.TrackResult(
        points=np.asarray(points, dtype=np.float32).copy(),
        valid=np.ones((count,), dtype=bool),
        fb_errors=np.zeros((count,), dtype=np.float32),
        ncc_scores=np.ones((count,), dtype=np.float32),
    )


class FixedDetector:
    def __init__(
        self,
        points: list[list[float]] | None = None,
        scores: list[float] | None = None,
    ) -> None:
        self.points = np.asarray(
            points if points is not None else [[20.0, 20.0]],
            dtype=np.float32,
        ).reshape(-1, 2)
        self.scores = np.asarray(
            scores if scores is not None else [1.0],
            dtype=np.float32,
        )
        self.calls = 0

    def detect(self, _image: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        self.calls += 1
        return self.points.copy(), self.scores.copy()

    def artifact_metadata(self) -> dict[str, object]:
        return {"identity": "unit-test-fixed-detector", "calls": self.calls}


class FailingDetector:
    def __init__(self) -> None:
        self.calls = 0

    def detect(self, _image: np.ndarray):
        self.calls += 1
        raise RuntimeError("injected detector failure")


class ProductionIdentityClaimingDetector(FixedDetector):
    def artifact_metadata(self) -> dict[str, object]:
        return {
            "identity": "LightGlue_repository_SuperPoint_detector_only",
            "claim": "malicious self-report used to test provenance isolation",
        }


def _image_message(stamp_ns: int, value: int = 0) -> Image:
    message = Image()
    message.header.stamp = _time(stamp_ns)
    message.header.frame_id = "cam0"
    message.height = 48
    message.width = 96
    message.encoding = "mono8"
    message.is_bigendian = 0
    message.step = 96
    message.data = bytes([value % 256]) * (48 * 96)
    return message


def _reference_feature_message(stamp_ns: int, seq: int) -> PointCloud:
    message = PointCloud()
    message.header.seq = seq
    message.header.stamp = _time(stamp_ns)
    message.header.frame_id = "world"
    message.points = [Point32(99.0, 88.0, 1.0)]
    values = {
        "id": [float(9000 + seq)],
        "camera_id": [0.0],
        "p_u": [77.0],
        "p_v": [66.0],
        "velocity_x": [55.0],
        "velocity_y": [44.0],
        "gx": [33.0],
        "gy": [22.0],
        "gz": [11.0],
        "quality": [0.25],
        "sigma": [2.0],
        "source_code": [20.0],
        "is_learned": [1.0],
    }
    message.channels = [
        ChannelFloat32(name=name, values=values[name])
        for name in exporter.CHANNEL_NAMES
    ]
    return message


def _imu_message(stamp_ns: int, value: float) -> Imu:
    message = Imu()
    message.header.stamp = _time(stamp_ns)
    message.linear_acceleration.x = value
    message.angular_velocity.z = -value
    return message


def _write_reference_bag(
    path: Path,
    raw_stamps: list[int],
) -> list[int]:
    published_stamps = raw_stamps[1::2]
    with rosbag.Bag(str(path), "w") as bag:
        bag.write(
            IMU_TOPIC,
            _imu_message(raw_stamps[0], 0.0),
            _time(raw_stamps[0]),
        )
        for index, stamp_ns in enumerate(published_stamps):
            bag.write(
                FEATURE_TOPIC,
                _reference_feature_message(stamp_ns, index),
                _time(stamp_ns),
            )
            imu_stamp = stamp_ns + 1_000
            bag.write(
                IMU_TOPIC,
                _imu_message(imu_stamp, index + 1.0),
                _time(imu_stamp),
            )
    return published_stamps


def _write_raw_bag(path: Path, raw_stamps: list[int]) -> None:
    with rosbag.Bag(str(path), "w") as bag:
        for index, stamp_ns in enumerate(raw_stamps):
            bag.write(
                IMAGE_TOPIC,
                _image_message(stamp_ns, index),
                _time(stamp_ns),
            )


def _write_camera_yaml(path: Path) -> None:
    path.write_text(
        "model_type: PINHOLE\n"
        "projection_parameters:\n"
        "  fx: 100.0\n"
        "  fy: 200.0\n"
        "  cx: 0.0\n"
        "  cy: 0.0\n"
        "distortion_parameters:\n"
        "  k1: 0.0\n"
        "  k2: 0.0\n"
        "  p1: 0.0\n"
        "  p2: 0.0\n",
        encoding="utf-8",
    )


def _channels(message: PointCloud) -> dict[str, list[float]]:
    return {channel.name: list(channel.values) for channel in message.channels}


class DetectorAndContractTests(unittest.TestCase):
    def test_main_attests_the_frozen_cli_factory_path(self) -> None:
        manifest = {
            "status": "FULL",
            "formal_eligible": True,
            "output_bag": {},
            "metrics": {},
        }
        argv = [
            "--source-feature-bag",
            "source.bag",
            "--raw-image-bag",
            "raw.bag",
            "--camera-yaml",
            "camera.yaml",
            "--output-bag",
            "output.bag",
            "--image-topic",
            IMAGE_TOPIC,
        ]
        with mock.patch.object(
            exporter, "export_bag", return_value=manifest
        ) as export_call, mock.patch("builtins.print"):
            self.assertEqual(exporter.main(argv), 0)
        self.assertIs(
            export_call.call_args.kwargs["_cli_production_factory_token"],
            exporter._CLI_PRODUCTION_FACTORY_TOKEN,
        )
        self.assertNotIn("detector", export_call.call_args.kwargs)

    def test_absolute_cli_help_imports_from_nonworkspace_without_workspace_pythonpath(
        self,
    ) -> None:
        script = Path(exporter.__file__).resolve()
        workspace = script.parents[1]
        environment = os.environ.copy()
        # Preserve the sourced ROS paths needed by rosbag/message imports, but
        # prove that the in-tree package is not supplied through PYTHONPATH.
        pythonpath = []
        for entry in environment.get("PYTHONPATH", "").split(os.pathsep):
            if not entry:
                continue
            try:
                if Path(entry).resolve() == workspace:
                    continue
            except OSError:
                pass
            pythonpath.append(entry)
        environment["PYTHONPATH"] = os.pathsep.join(pythonpath)
        self.assertNotIn(str(workspace), pythonpath)
        with tempfile.TemporaryDirectory() as foreign_cwd:
            completed = subprocess.run(
                [sys.executable, str(script), "--help"],
                cwd=foreign_cwd,
                env=environment,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("--source-feature-bag", completed.stdout)

    def test_contract_is_detector_only_and_uses_formal_superpoint_enum(self) -> None:
        contract = exporter._algorithm_contract()
        self.assertEqual(
            contract,
            exporter._algorithm_contract(exporter.SUPERPOINT_METHOD_SPEC),
        )
        self.assertEqual(
            exporter.SUPERPOINT_METHOD_SPEC.manifest_schema_version,
            "superpoint-lk-carrier-export-v1",
        )
        self.assertIs(
            exporter.SUPERPOINT_METHOD_SPEC.detector_factory,
            exporter.SuperPointDetector,
        )
        self.assertTrue(contract["superpoint"]["detector_only"])
        self.assertIsNone(contract["superpoint"]["matcher"])
        self.assertEqual(contract["superpoint"]["max_keypoints"], 2048)
        self.assertEqual(contract["superpoint"]["resize"], 1024)
        self.assertEqual(contract["publication"]["source_code"], 10)
        self.assertEqual(contract["publication"]["is_learned"], 1)
        self.assertNotIn("LightGlue(", inspect.getsource(exporter.SuperPointDetector))

    def test_loader_constructs_superpoint_but_never_matcher(self) -> None:
        class FakeExtractor:
            def __init__(self) -> None:
                self.devices = []

            def eval(self):
                return self

            def to(self, device):
                self.devices.append(device)
                return self

        fake_extractor = FakeExtractor()
        superpoint_constructor = mock.Mock(return_value=fake_extractor)
        matcher_constructor = mock.Mock(side_effect=AssertionError("matcher constructed"))
        fake_torch = SimpleNamespace(
            cuda=SimpleNamespace(is_available=lambda: False)
        )
        fake_lightglue = SimpleNamespace(
            SuperPoint=superpoint_constructor,
            LightGlue=matcher_constructor,
        )

        def import_module(name: str):
            return {"torch": fake_torch, "lightglue": fake_lightglue}[name]

        detector = exporter.SuperPointDetector()
        with mock.patch.object(detector, "_validate_weight"), mock.patch.object(
            exporter.importlib,
            "import_module",
            side_effect=import_module,
        ):
            detector._load()

        superpoint_constructor.assert_called_once_with(max_num_keypoints=2048)
        matcher_constructor.assert_not_called()
        self.assertEqual(fake_extractor.devices, ["cpu"])

    def test_extract_coordinates_are_already_original_scale_and_never_rescaled(self) -> None:
        import torch

        class FakeExtractor:
            def __init__(self) -> None:
                self.resize = None
                self.input_shape = None

            def extract(self, tensor, *, resize):
                self.resize = resize
                self.input_shape = tuple(tensor.shape)
                # LightGlue Extractor.extract has already mapped these coordinates
                # back to the original input geometry.
                return {
                    "keypoints": torch.tensor(
                        [[[489.25, 305.5], [800.0, 500.0]]], dtype=torch.float32
                    ),
                    "keypoint_scores": torch.tensor(
                        [[0.9, 0.8]], dtype=torch.float32
                    ),
                }

        fake = FakeExtractor()
        detector = exporter.SuperPointDetector()
        detector._torch = torch
        detector._extractor = fake
        detector._device = "cpu"
        points, scores = detector.detect(np.zeros((608, 968), dtype=np.uint8))

        self.assertEqual(fake.resize, 1024)
        self.assertEqual(fake.input_shape, (1, 1, 608, 968))
        np.testing.assert_array_equal(
            points,
            np.asarray([[489.25, 305.5], [800.0, 500.0]], dtype=np.float32),
        )
        np.testing.assert_array_equal(scores, np.asarray([0.9, 0.8], np.float32))

    def test_adaptive_clahe_enhanced_and_passthrough_paths(self) -> None:
        gray = np.arange(48, dtype=np.uint8).reshape(6, 8)
        healthy = SimpleNamespace(
            contrast_score=0.9,
            grid_texture_score=0.9,
            illumination_nonuniformity=0.1,
            degradation_score=0.1,
        )
        degraded = SimpleNamespace(
            contrast_score=0.71,
            grid_texture_score=0.9,
            illumination_nonuniformity=0.1,
            degradation_score=0.1,
        )
        clahe = mock.Mock()
        clahe.apply.return_value = gray + 1
        factory = mock.Mock(return_value=clahe)

        result, applied = exporter.adaptive_clahe(
            gray,
            quality_scorer=lambda _image: healthy,
            clahe_factory=factory,
        )
        self.assertIs(result, gray)
        self.assertFalse(applied)
        factory.assert_not_called()

        result, applied = exporter.adaptive_clahe(
            gray,
            quality_scorer=lambda _image: degraded,
            clahe_factory=factory,
        )
        self.assertTrue(applied)
        np.testing.assert_array_equal(result, gray + 1)
        factory.assert_called_once_with(clipLimit=2.0, tileGridSize=(8, 8))
        clahe.apply.assert_called_once_with(gray)


class CarrierPureFunctionTests(unittest.TestCase):
    def test_lk_uses_frozen_parameters_and_rejects_fb_and_ncc_failures(self) -> None:
        previous = np.zeros((64, 96), dtype=np.uint8)
        current = np.ones((64, 96), dtype=np.uint8)
        points = np.asarray(
            [[20.0, 20.0], [40.0, 20.0], [60.0, 20.0]],
            dtype=np.float32,
        )
        forward = points + np.asarray([1.0, 0.0], dtype=np.float32)
        backward = points.copy()
        backward[1, 0] += 1.01
        status = np.ones((3, 1), dtype=np.uint8)
        error = np.zeros((3, 1), dtype=np.float32)
        flow = mock.Mock(
            side_effect=[
                (forward.reshape(-1, 1, 2), status, error),
                (backward.reshape(-1, 1, 2), status, error),
            ]
        )
        ncc = mock.Mock(
            return_value=np.asarray([0.80, 0.80, 0.64], dtype=np.float32)
        )

        result = exporter.track_points_lk(
            previous,
            current,
            points,
            flow=flow,
            ncc_function=ncc,
        )

        np.testing.assert_array_equal(result.valid, [True, False, False])
        self.assertEqual(flow.call_count, 2)
        for call in flow.call_args_list:
            self.assertEqual(call.kwargs["winSize"], (21, 21))
            self.assertEqual(call.kwargs["maxLevel"], 3)
            self.assertEqual(
                call.kwargs["criteria"],
                (
                    exporter.cv2.TERM_CRITERIA_EPS
                    | exporter.cv2.TERM_CRITERIA_COUNT,
                    30,
                    0.01,
                ),
            )
            self.assertEqual(call.kwargs["minEigThreshold"], 1e-4)
        ncc.assert_called_once()
        self.assertEqual(ncc.call_args.args[-1], 5)

    def test_score_order_spacing_border_and_cap_are_exact(self) -> None:
        candidates = np.asarray(
            [
                [7.99, 40.0],
                [50.0, 50.0],
                [27.0, 10.0],
                [80.0, 80.0],
                [10.0, 10.0],
                [60.0, 50.0],
            ],
            dtype=np.float32,
        )
        scores = np.asarray([1.0, 0.99, 0.90, 0.80, 0.70, 0.95], np.float32)
        occupied = np.asarray([[50.0, 50.0]], dtype=np.float32)

        selected = exporter.select_births(
            candidates,
            scores,
            occupied,
            (100, 100),
            slots=2,
        )

        np.testing.assert_array_equal(
            selected,
            np.asarray([[27.0, 10.0], [80.0, 80.0]], dtype=np.float32),
        )
        exactly_18 = exporter.select_births(
            np.asarray([[18.0, 30.0]], np.float32),
            np.asarray([1.0], np.float32),
            np.asarray([[36.0, 30.0]], np.float32),
            (100, 100),
            slots=1,
        )
        np.testing.assert_array_equal(exactly_18, [[18.0, 30.0]])

    def test_lifetime_is_monotonic_and_dead_ids_are_never_reused(self) -> None:
        state = exporter.CarrierState(
            points=np.asarray([[20.0, 20.0], [50.0, 20.0]], np.float32),
            ids=np.asarray([0, 1], np.int64),
            ages=np.asarray([5, 3], np.int32),
            next_id=2,
        )

        def drop_second(_previous, _current, points):
            return exporter.TrackResult(
                points=points + np.asarray([1.0, 0.0], np.float32),
                valid=np.asarray([True, False]),
                fb_errors=np.asarray([0.0, 2.0], np.float32),
                ncc_scores=np.asarray([1.0, 1.0], np.float32),
            )

        image = np.zeros((64, 96), dtype=np.uint8)
        exporter.advance_state(state, image, image, tracker=drop_second)
        exporter.replenish_state(
            state,
            image,
            FixedDetector([[75.0, 30.0]], [1.0]),
        )
        np.testing.assert_array_equal(state.ids, [0, 2])
        np.testing.assert_array_equal(state.ages, [6, 1])
        self.assertEqual(state.next_id, 3)

        def drop_oldest(_previous, _current, points):
            return exporter.TrackResult(
                points=points,
                valid=np.asarray([False, True]),
                fb_errors=np.asarray([2.0, 0.0], np.float32),
                ncc_scores=np.asarray([1.0, 1.0], np.float32),
            )

        exporter.advance_state(state, image, image, tracker=drop_oldest)
        exporter.replenish_state(
            state,
            image,
            FixedDetector([[20.0, 35.0]], [1.0]),
        )
        np.testing.assert_array_equal(state.ids, [2, 3])
        self.assertEqual(state.next_id, 4)
        self.assertNotIn(0, state.ids)
        self.assertNotIn(1, state.ids)

    def test_raw0_initializes_raw1_and_raw3_publish_deterministically(self) -> None:
        schedule = [_schedule_frame(200, seq=7), _schedule_frame(400, seq=8)]
        raw = [
            _raw_frame(100),
            _raw_frame(200),
            _raw_frame(300),
            _raw_frame(400),
        ]

        def shift_tracker(_previous, _current, points):
            count = len(points)
            return exporter.TrackResult(
                points=points + np.asarray([1.0, 0.0], np.float32),
                valid=np.ones((count,), dtype=bool),
                fb_errors=np.zeros((count,), np.float32),
                ncc_scores=np.ones((count,), np.float32),
            )

        result1 = exporter.run_carrier(
            schedule,
            raw,
            FixedDetector(),
            tracker=shift_tracker,
            preprocess=_identity_preprocess,
        )
        result2 = exporter.run_carrier(
            schedule,
            raw,
            FixedDetector(),
            tracker=shift_tracker,
            preprocess=_identity_preprocess,
        )

        self.assertEqual([row.published for row in result1.raw_diagnostics], [False, True, False, True])
        np.testing.assert_array_equal(result1.published_frames[0].ids, [0])
        np.testing.assert_array_equal(result1.published_frames[0].pixels, [[21.0, 20.0]])
        np.testing.assert_array_equal(result1.published_frames[1].pixels, [[23.0, 20.0]])
        for frame1, frame2 in zip(result1.published_frames, result2.published_frames):
            np.testing.assert_array_equal(frame1.ids, frame2.ids)
            np.testing.assert_array_equal(frame1.pixels, frame2.pixels)
            np.testing.assert_array_equal(frame1.ages, frame2.ages)

    def test_schedule_requires_raw_offset_one_and_every_two(self) -> None:
        with self.assertRaisesRegex(ValueError, "first publication at raw index 1"):
            exporter._schedule_raw_indices(
                [_schedule_frame(100)],
                [_raw_frame(100)],
            )
        with self.assertRaisesRegex(ValueError, "not exact raw frames 1,3"):
            exporter._schedule_raw_indices(
                [_schedule_frame(200), _schedule_frame(500)],
                [
                    _raw_frame(100),
                    _raw_frame(200),
                    _raw_frame(300),
                    _raw_frame(400),
                    _raw_frame(500),
                ],
            )

    def test_camera_normalization_velocity_and_birth_zero(self) -> None:
        schedule = [
            _schedule_frame(1_000_000_000),
            _schedule_frame(1_100_000_000),
        ]
        frames = [
            exporter.PublishedFrame(
                ids=np.asarray([0], np.int64),
                pixels=np.asarray([[10.0, 20.0]], np.float32),
                ages=np.asarray([2], np.int32),
            ),
            exporter.PublishedFrame(
                ids=np.asarray([0, 1], np.int64),
                pixels=np.asarray([[12.0, 20.0], [30.0, 30.0]], np.float32),
                ages=np.asarray([4, 1], np.int32),
            ),
        ]
        camera_matrix = np.asarray(
            [[100.0, 0.0, 0.0], [0.0, 200.0, 0.0], [0.0, 0.0, 1.0]],
            dtype=np.float64,
        )
        normalized = exporter.normalized_frames(
            frames,
            camera_matrix,
            np.zeros((4,), dtype=np.float64),
        )
        velocities = exporter.velocity_frames(schedule, frames, normalized)

        np.testing.assert_allclose(normalized[0], [[0.1, 0.1]], atol=1e-7)
        np.testing.assert_allclose(
            normalized[1], [[0.12, 0.1], [0.3, 0.15]], atol=1e-7
        )
        np.testing.assert_allclose(velocities[0], [[0.0, 0.0]], atol=1e-7)
        np.testing.assert_allclose(
            velocities[1], [[0.2, 0.0], [0.0, 0.0]], atol=1e-6
        )

        message = exporter.build_feature_message(
            schedule[1], frames[1], normalized[1], velocities[1]
        )
        channels = _channels(message)
        self.assertEqual(list(channels), list(exporter.CHANNEL_NAMES))
        self.assertEqual(channels["quality"], [1.0, 1.0])
        self.assertEqual(channels["sigma"], [1.0, 1.0])
        self.assertEqual(channels["source_code"], [10.0, 10.0])
        self.assertEqual(channels["is_learned"], [1.0, 1.0])
        self.assertTrue(all(point.z == 1.0 for point in message.points))

    def test_kannala_brandt_loader_and_normalization_match_opencv_fisheye(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            camera_yaml = Path(directory) / "kannala.yaml"
            camera_yaml.write_text(
                "%YAML:1.0\n---\n"
                "model_type: KANNALA_BRANDT\n"
                "image_width: 640\nimage_height: 512\n"
                "projection_parameters:\n"
                "  k2: -0.06125568297136998\n"
                "  k3: -0.003796743395135256\n"
                "  k4: 0.027326634771204592\n"
                "  k5: -0.030296403142887066\n"
                "  mu: 413.32595366566017\n"
                "  mv: 413.70198739483686\n"
                "  u0: 305.9507483284928\n"
                "  v0: 259.4439948946375\n",
                encoding="utf-8",
            )
            matrix, distortion, model = exporter.load_camera_model(camera_yaml)
            with self.assertRaisesRegex(ValueError, "expected pinhole"):
                exporter.load_pinhole_camera(camera_yaml)
        self.assertEqual(model, "kannala_brandt")
        np.testing.assert_allclose(
            matrix,
            [
                [413.32595366566017, 0.0, 305.9507483284928],
                [0.0, 413.70198739483686, 259.4439948946375],
                [0.0, 0.0, 1.0],
            ],
        )
        pixels = np.asarray([[305.0, 259.0], [120.0, 80.0]], dtype=np.float32)
        frames = [
            exporter.PublishedFrame(
                ids=np.asarray([0, 1], np.int64),
                pixels=pixels,
                ages=np.asarray([1, 1], np.int32),
            )
        ]
        actual = exporter.normalized_frames(
            frames, matrix, distortion, model
        )[0]
        expected = exporter.cv2.fisheye.undistortPoints(
            pixels.reshape(-1, 1, 2), matrix, distortion
        ).reshape(-1, 2)
        np.testing.assert_allclose(actual, expected, rtol=0.0, atol=1e-7)


class BagExportContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.source = self.root / "source.bag"
        self.raw = self.root / "raw.bag"
        self.camera = self.root / "camera.yaml"
        base = 1_000_000_000
        step = 10_000_000
        self.raw_stamps = [base + index * step for index in range(202)]
        self.published_stamps = _write_reference_bag(self.source, self.raw_stamps)
        _write_raw_bag(self.raw, self.raw_stamps)
        _write_camera_yaml(self.camera)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _export(
        self,
        name: str,
        *,
        max_published_frames: int | None,
        detector=None,
    ) -> tuple[Path, Path, dict[str, object]]:
        output = self.root / f"{name}.bag"
        manifest = self.root / f"{name}.json"
        payload = exporter.export_bag(
            self.source,
            self.raw,
            self.camera,
            output,
            image_topic=IMAGE_TOPIC,
            feature_topic=FEATURE_TOPIC,
            max_published_frames=max_published_frames,
            manifest_json=manifest,
            detector=detector if detector is not None else FixedDetector(),
            tracker=_identity_tracker,
            preprocess=_identity_preprocess,
        )
        return output, manifest, payload

    def test_100_frame_prefix_and_full_are_explicit_and_schedule_exact(self) -> None:
        prefix_output, prefix_manifest, prefix = self._export(
            "prefix100",
            max_published_frames=100,
        )
        full_output, full_manifest, full = self._export(
            "full",
            max_published_frames=None,
        )

        self.assertEqual(prefix["status"], "PREFIX_NONFORMAL")
        self.assertFalse(prefix["formal_eligible"])
        self.assertEqual(prefix["prefix"]["requested_max_published_frames"], 100)
        self.assertEqual(prefix["prefix"]["selected_published_frames"], 100)
        self.assertEqual(prefix["prefix"]["source_total_published_frames"], 101)
        self.assertEqual(prefix["metrics"]["published_frames"], 100)
        self.assertEqual(full["status"], "FULL")
        self.assertFalse(full["formal_eligible"])
        self.assertEqual(full["detector_origin"], "python_api_injected_detector")
        self.assertEqual(
            full["formal_eligibility_reason"],
            "python_api_injected_detector_is_nonformal",
        )
        self.assertIsNone(full["prefix"]["requested_max_published_frames"])
        self.assertEqual(full["metrics"]["published_frames"], 101)
        self.assertTrue(prefix_output.is_file())
        self.assertTrue(prefix_manifest.is_file())
        self.assertTrue(full_output.is_file())
        self.assertTrue(full_manifest.is_file())
        self.assertEqual(
            json.loads(prefix_manifest.read_text(encoding="utf-8"))["status"],
            "PREFIX_NONFORMAL",
        )

        with rosbag.Bag(str(prefix_output), "r") as bag:
            prefix_features = list(bag.read_messages(topics=[FEATURE_TOPIC]))
        with rosbag.Bag(str(full_output), "r") as bag:
            full_features = list(bag.read_messages(topics=[FEATURE_TOPIC]))
        self.assertEqual(len(prefix_features), 100)
        self.assertEqual(len(full_features), 101)
        for index, (_topic, message, record_stamp) in enumerate(prefix_features):
            self.assertEqual(
                int(message.header.stamp.to_nsec()), self.published_stamps[index]
            )
            self.assertEqual(int(record_stamp.to_nsec()), self.published_stamps[index])
            self.assertEqual(message.header.seq, index)
            channels = _channels(message)
            self.assertEqual(channels["id"], [0.0])
            self.assertNotEqual(channels["id"], [float(9000 + index)])
            self.assertEqual(channels["source_code"], [10.0])
        self.assertEqual(
            prefix["nonfeature_stream_before"],
            prefix["nonfeature_stream_after"],
        )
        self.assertEqual(
            full["nonfeature_stream_before"],
            full["nonfeature_stream_after"],
        )
        self.assertEqual(prefix["algorithm_config_sha256"], full["algorithm_config_sha256"])
        self.assertEqual(len(prefix["algorithm_config_sha256"]), 64)
        for key in ("source_feature_bag", "raw_image_bag", "camera_yaml"):
            self.assertEqual(len(prefix["inputs"][key]["sha256"]), 64)
        self.assertEqual(len(prefix["output_bag"]["sha256"]), 64)
        self.assertEqual(len(prefix["code_artifacts"]["exporter"]["sha256"]), 64)
        self.assertEqual(prefix["schema_version"], "superpoint-lk-carrier-export-v1")
        self.assertNotIn("carrier_base", prefix["code_artifacts"])
        self.assertNotIn("runtime_profile", prefix)

    def test_prefix_equal_to_full_length_never_pretends_to_be_full(self) -> None:
        _output, _manifest, payload = self._export(
            "prefix101",
            max_published_frames=101,
        )
        self.assertEqual(payload["status"], "PREFIX_NONFORMAL")
        self.assertFalse(payload["formal_eligible"])
        self.assertEqual(payload["metrics"]["published_frames"], 101)

    def test_only_cli_factory_full_is_formal_and_python_factory_is_not(self) -> None:
        cli_detector = FixedDetector()
        cli_spec = replace(
            exporter.SUPERPOINT_METHOD_SPEC,
            detector_factory=lambda: cli_detector,
        )
        cli_output = self.root / "cli-factory.bag"
        cli_manifest = exporter.export_bag(
            self.source,
            self.raw,
            self.camera,
            cli_output,
            image_topic=IMAGE_TOPIC,
            detector=None,
            tracker=_identity_tracker,
            preprocess=_identity_preprocess,
            method_spec=cli_spec,
            _cli_production_factory_token=exporter._CLI_PRODUCTION_FACTORY_TOKEN,
        )
        self.assertTrue(cli_manifest["formal_eligible"])
        self.assertEqual(cli_manifest["detector_origin"], "cli_production_factory")
        self.assertEqual(
            cli_manifest["formal_eligibility_reason"],
            "full_export_from_frozen_cli_production_factory",
        )

        python_detector = FixedDetector()
        python_spec = replace(
            exporter.SUPERPOINT_METHOD_SPEC,
            detector_factory=lambda: python_detector,
        )
        python_manifest = exporter.export_bag(
            self.source,
            self.raw,
            self.camera,
            self.root / "python-factory.bag",
            image_topic=IMAGE_TOPIC,
            detector=None,
            tracker=_identity_tracker,
            preprocess=_identity_preprocess,
            method_spec=python_spec,
        )
        self.assertFalse(python_manifest["formal_eligible"])
        self.assertEqual(
            python_manifest["detector_origin"], "python_api_production_factory"
        )

    def test_injected_detector_cannot_self_report_formal_identity(self) -> None:
        detector = ProductionIdentityClaimingDetector()
        manifest = exporter.export_bag(
            self.source,
            self.raw,
            self.camera,
            self.root / "malicious-identity.bag",
            image_topic=IMAGE_TOPIC,
            detector=detector,
            tracker=_identity_tracker,
            preprocess=_identity_preprocess,
        )
        self.assertEqual(
            manifest["code_artifacts"]["detector"]["identity"],
            exporter.SUPERPOINT_METHOD_SPEC.production_detector_identity,
        )
        self.assertFalse(manifest["formal_eligible"])
        self.assertEqual(
            manifest["detector_origin"], "python_api_injected_detector"
        )

    def test_existing_output_is_never_clobbered(self) -> None:
        output = self.root / "exists.bag"
        output.write_bytes(b"sentinel")
        detector = FixedDetector()
        with self.assertRaises(FileExistsError):
            exporter.export_bag(
                self.source,
                self.raw,
                self.camera,
                output,
                image_topic=IMAGE_TOPIC,
                detector=detector,
                tracker=_identity_tracker,
                preprocess=_identity_preprocess,
            )
        self.assertEqual(output.read_bytes(), b"sentinel")
        self.assertEqual(detector.calls, 0)
        self.assertFalse((self.root / "exists.bag.manifest.json").exists())

    def test_strict_failure_removes_reserved_outputs_and_temporaries(self) -> None:
        output = self.root / "failure.bag"
        manifest = self.root / "failure.json"
        detector = FailingDetector()
        with self.assertRaisesRegex(RuntimeError, "injected detector failure"):
            exporter.export_bag(
                self.source,
                self.raw,
                self.camera,
                output,
                image_topic=IMAGE_TOPIC,
                manifest_json=manifest,
                max_published_frames=1,
                detector=detector,
                tracker=_identity_tracker,
                preprocess=_identity_preprocess,
            )
        self.assertEqual(detector.calls, 1)
        self.assertFalse(output.exists())
        self.assertFalse(manifest.exists())
        self.assertEqual(list(self.root.glob(".*.tmp.*")), [])

    def test_max_published_frames_accepts_only_positive_integers(self) -> None:
        parser = exporter.build_parser()
        base = [
            "--source-feature-bag",
            str(self.source),
            "--raw-image-bag",
            str(self.raw),
            "--camera-yaml",
            str(self.camera),
            "--output-bag",
            str(self.root / "unused.bag"),
            "--image-topic",
            IMAGE_TOPIC,
        ]
        with self.assertRaises(SystemExit):
            parser.parse_args(base + ["--max-published-frames", "0"])
        with self.assertRaises(SystemExit):
            parser.parse_args(base + ["--max-published-frames", "1.5"])
        self.assertEqual(
            parser.parse_args(base + ["--max-published-frames", "100"]).max_published_frames,
            100,
        )


if __name__ == "__main__":
    unittest.main()
