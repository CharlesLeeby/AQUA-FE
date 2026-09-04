from __future__ import annotations

import json
from dataclasses import replace
from io import StringIO
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest import mock

import numpy as np

from scripts import audit_seeded_lk_featurebag_v1 as audit


def _frame(
    index: int,
    *,
    count: int = 12,
    jitter: float = 0.0,
) -> audit.FeatureFrame:
    ids = np.arange(count, dtype=np.int64)
    base = np.column_stack(
        (np.linspace(20.0, 220.0, count), np.linspace(30.0, 160.0, count))
    ).astype(np.float32)
    pixel = base + np.asarray([2.0 * index, -0.5 * index], dtype=np.float32)
    if jitter:
        pixel[:, 0] += np.float32(jitter * ((-1) ** index))
    normalized = (pixel - np.asarray([120.0, 90.0], dtype=np.float32)) / 500.0
    channel_names = (
        "id",
        "camera_id",
        "p_u",
        "p_v",
        "velocity_x",
        "velocity_y",
        "quality",
        "sigma",
        "source_code",
        "is_learned",
    )
    preserved = {
        "id": ids.astype(np.float32),
        "camera_id": np.zeros(count, dtype=np.float32),
        "quality": np.ones(count, dtype=np.float32),
        "sigma": np.ones(count, dtype=np.float32),
        "source_code": np.full(count, 10.0, dtype=np.float32),
        "is_learned": np.ones(count, dtype=np.float32),
    }
    velocity = np.zeros((count, 2), dtype=np.float32)
    if index:
        velocity[:, 0] = np.float32(
            (2.0 + 2.0 * jitter * ((-1) ** index)) / 50.0
        )
        velocity[:, 1] = np.float32(-0.01)
    return audit.FeatureFrame(
        index=index,
        record_stamp_ns=1_000_000_000 + index * 100_000_000,
        header_stamp_ns=1_000_000_000 + index * 100_000_000,
        header_seq=index,
        header_frame_id="world",
        ids=ids,
        pixel_points=pixel,
        normalized_points=normalized.astype(np.float32),
        point_z=np.ones(count, dtype=np.float32),
        velocities=velocity,
        channel_names=channel_names,
        preserved_channels=preserved,
    )


def _frames(*, jitter: float = 0.0) -> list[audit.FeatureFrame]:
    return [_frame(index, jitter=jitter) for index in range(5)]


def _all_inliers(left: np.ndarray, _right: np.ndarray, _focal: float) -> np.ndarray:
    return np.ones(len(left), dtype=bool)


def _nonfeature_pass() -> dict[str, object]:
    return {"pass": True, "mode": "full_exact", "violation_counts": {}}


class ImmutableContractTests(unittest.TestCase):
    def test_only_coordinate_normalized_and_velocity_changes_are_allowed(self) -> None:
        source = _frames()
        candidate = []
        for frame in source:
            candidate.append(
                replace(
                    frame,
                    pixel_points=frame.pixel_points + 0.25,
                    normalized_points=frame.normalized_points + 0.0005,
                    velocities=frame.velocities + 0.1,
                )
            )
        result = audit.compare_immutable_contract(source, candidate)
        self.assertTrue(result["pass"])
        self.assertEqual(result["violation_counts"], {})

    def test_stamp_id_occurrence_quality_and_source_changes_are_rejected(self) -> None:
        source = _frames()
        mutations = []
        mutations.append(
            ("record", replace(source[2], record_stamp_ns=source[2].record_stamp_ns + 1))
        )
        changed_ids = source[2].ids.copy()
        changed_ids[0] = 999
        mutations.append(("ids", replace(source[2], ids=changed_ids)))
        for channel in ("quality", "source_code"):
            preserved = dict(source[2].preserved_channels)
            preserved[channel] = preserved[channel].copy()
            preserved[channel][0] += 0.1
            mutations.append((channel, replace(source[2], preserved_channels=preserved)))

        for label, replacement in mutations:
            with self.subTest(label=label):
                candidate = list(source)
                candidate[2] = replacement
                result = audit.compare_immutable_contract(source, candidate)
                self.assertFalse(result["pass"])
                self.assertTrue(result["violation_counts"])

    def test_prefix_is_explicit_and_point_z_must_be_exact_one(self) -> None:
        source = _frames()
        candidate = source[:3]
        self.assertFalse(audit.compare_immutable_contract(source, candidate)["pass"])
        self.assertTrue(
            audit.compare_immutable_contract(
                source, candidate, allow_candidate_prefix=True
            )["pass"]
        )
        bad_source = list(source)
        bad_source[0] = replace(
            bad_source[0], point_z=np.full(12, 0.99999994, dtype=np.float32)
        )
        result = audit.compare_immutable_contract(
            bad_source, candidate, allow_candidate_prefix=True
        )
        self.assertIn(
            "SOURCE_POINT_Z_NOT_EXACT_ONE", result["violation_counts"]
        )


class CameraAndMeasurementContractTests(unittest.TestCase):
    def test_camera_loads_k_and_d_from_root_and_cam0(self) -> None:
        root_body = (
            "projection_parameters:\n"
            "  fx: 500.0\n  fy: 501.0\n  cx: 120.0\n  cy: 90.0\n"
            "distortion_parameters:\n"
            "  k1: 0.1\n  k2: -0.2\n  p1: 0.01\n  p2: 0.02\n"
        )
        with tempfile.TemporaryDirectory() as directory:
            for nested in (False, True):
                with self.subTest(cam0=nested):
                    path = Path(directory) / f"camera-{nested}.yaml"
                    if nested:
                        body = "cam0:\n" + "\n".join(
                            f"  {line}" for line in root_body.splitlines()
                        ) + "\n"
                    else:
                        body = root_body
                    path.write_text("%YAML:1.0\n---\n" + body, encoding="utf-8")
                    camera = audit.load_camera_model(path)
                    self.assertEqual((camera.fx, camera.fy, camera.cx, camera.cy), (500.0, 501.0, 120.0, 90.0))
                    self.assertEqual(camera.distortion, (0.1, -0.2, 0.01, 0.02))

    def test_candidate_normalized_velocity_and_birth_are_independently_checked(self) -> None:
        camera = audit.CameraModel(500.0, 500.0, 120.0, 90.0)
        frames = _frames()
        self.assertTrue(audit.candidate_measurement_contract(frames, camera)["pass"])

        bad_normalized = list(frames)
        normalized = frames[2].normalized_points.copy()
        normalized[0, 0] += np.float32(2e-6)
        bad_normalized[2] = replace(frames[2], normalized_points=normalized)
        result = audit.candidate_measurement_contract(bad_normalized, camera)
        self.assertIn(
            "CANDIDATE_NORMALIZED_FROM_PIXEL_MISMATCH",
            result["violation_counts"],
        )

        bad_velocity = list(frames)
        velocity = frames[0].velocities.copy()
        velocity[0, 0] = np.float32(2e-5)
        bad_velocity[0] = replace(frames[0], velocities=velocity)
        result = audit.candidate_measurement_contract(bad_velocity, camera)
        self.assertIn("CANDIDATE_VELOCITY_MISMATCH", result["violation_counts"])


class ScientificGateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.camera = audit.CameraModel(fx=500.0, fy=500.0, cx=120.0, cy=90.0)

    def test_smooth_candidate_passes_both_fixed_gates(self) -> None:
        source = _frames(jitter=0.6)
        candidate = _frames(jitter=0.0)
        # Candidate is allowed to change only measurement fields.
        for index in range(len(candidate)):
            candidate[index] = replace(
                candidate[index],
                preserved_channels=source[index].preserved_channels,
            )
        result = audit.evaluate_feature_frames(
            source, candidate, self.camera, solver=_all_inliers
        )
        self.assertTrue(result["pass"])
        self.assertEqual(result["status"], "PASS")
        self.assertLess(
            result["metrics"]["three_frame_second_difference"]["distribution"]["median"],
            0.3,
        )
        self.assertGreater(
            result["metrics"]["adjacent_essential"]["inlier_ratio_distribution"]["median"],
            0.90,
        )

    def test_second_difference_above_fixed_threshold_fails(self) -> None:
        source = _frames()
        candidate = _frames()
        # A quadratic 0.155*n^2 offset has a constant 0.31 px second difference.
        offsets = [0.155 * index * index for index in range(5)]
        for index, offset in enumerate(offsets):
            pixels = candidate[index].pixel_points.copy()
            pixels[:, 0] += np.float32(offset)
            candidate[index] = replace(candidate[index], pixel_points=pixels)
        result = audit.evaluate_feature_frames(
            source, candidate, self.camera, solver=_all_inliers
        )
        self.assertFalse(result["pass"])
        self.assertIn(
            "SECOND_DIFFERENCE_MEDIAN_NOT_BELOW_0.3PX", result["reasons"]
        )

    def test_essential_ratio_boundary_is_strict(self) -> None:
        source = _frames()

        def ninety_percent(left, _right, _focal):
            mask = np.ones(len(left), dtype=bool)
            # Frames have 12 observations: use a deterministic 9/10-like
            # boundary by returning 90 inliers for a synthetic 100-point case.
            mask[:] = False
            mask[: int(round(0.9 * len(mask)))] = True
            return mask

        source = [_frame(index, count=10) for index in range(5)]
        result = audit.evaluate_feature_frames(
            source, source, self.camera, solver=ninety_percent
        )
        self.assertFalse(result["pass"])
        self.assertIn(
            "ESSENTIAL_INLIER_MEDIAN_NOT_ABOVE_0.90", result["reasons"]
        )

    def test_no_three_frame_or_essential_support_is_scientific_fail(self) -> None:
        frames = [_frame(0), _frame(1)]
        frames[1] = replace(frames[1], ids=np.arange(100, 112, dtype=np.int64))
        result = audit.evaluate_feature_frames(
            frames, frames, self.camera, solver=_all_inliers
        )
        self.assertEqual(result["status"], "FAIL")
        self.assertIn("NO_THREE_FRAME_COMMON_IDS", result["reasons"])
        self.assertIn("NO_ADJACENT_ESSENTIAL_PAIRS", result["reasons"])


class MagsacAndCliContractTests(unittest.TestCase):
    def test_exact_magsac_parameters_and_capability_hard_error(self) -> None:
        points = np.column_stack(
            (np.linspace(-0.2, 0.2, 10), np.linspace(-0.1, 0.1, 10))
        ).astype(np.float32)
        mask = np.ones((10, 1), dtype=np.uint8)
        mask[0, 0] = 255
        with mock.patch.object(audit.cv2, "USAC_MAGSAC", 38, create=True), mock.patch.object(
            audit.cv2, "findEssentialMat", return_value=(np.eye(3), mask)
        ) as estimator:
            result = audit.magsac_essential_inlier_mask(points, points, 500.0)
        self.assertTrue(np.all(result))
        args, kwargs = estimator.call_args
        np.testing.assert_array_equal(args[2], np.eye(3))
        self.assertEqual(kwargs["method"], 38)
        self.assertEqual(kwargs["prob"], 0.999)
        self.assertAlmostEqual(kwargs["threshold"], 0.3 / 500.0)
        self.assertEqual(kwargs["maxIters"], 200)

        with mock.patch.object(audit.cv2, "USAC_MAGSAC", None, create=True):
            with self.assertRaisesRegex(audit.AuditInputError, "USAC_MAGSAC"):
                audit.require_usac_magsac_available()

    def test_cli_rc0_rc1_rc2_and_canonical_json(self) -> None:
        camera = audit.CameraModel(500.0, 500.0, 120.0, 90.0)
        frames = _frames()
        argv = [
            "--source-bag",
            "source.bag",
            "--candidate-bag",
            "candidate.bag",
            "--camera-yaml",
            "camera.yaml",
        ]
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "audit.json"
            cli = argv + ["--output-json", str(output)]
            with mock.patch.object(audit, "require_usac_magsac_available"), mock.patch.object(
                audit, "load_camera_model", return_value=camera
            ), mock.patch.object(
                audit, "load_feature_frames", side_effect=[frames, frames]
            ), mock.patch.object(
                audit, "compare_nonfeature_topics", return_value=_nonfeature_pass()
            ), mock.patch.object(
                audit, "magsac_essential_inlier_mask", side_effect=_all_inliers
            ), mock.patch.object(
                audit, "adjacent_essential_inlier_ratios"
            ) as adjacent, mock.patch("sys.stdout", new_callable=StringIO) as stdout:
                adjacent.side_effect = lambda candidate, focal_mean_px, solver=None: {
                    "pixel_threshold": 0.3,
                    "method": "USAC_MAGSAC",
                    "evaluated_adjacent_pairs": 4,
                    "skipped_fewer_than_8": 0,
                    "inlier_ratio_distribution": audit._quantiles([1.0] * 4),
                    "common_id_count_distribution": audit._quantiles([12.0] * 4),
                }
                rc = audit.main(cli)
            self.assertEqual(rc, 0)
            rendered = stdout.getvalue()
            self.assertEqual(rendered, output.read_text(encoding="ascii"))
            payload = json.loads(rendered)
            self.assertEqual(rendered, audit.canonical_json(payload) + "\n")

        failing = _frames(jitter=1.0)
        with mock.patch.object(audit, "require_usac_magsac_available"), mock.patch.object(
            audit, "load_camera_model", return_value=camera
        ), mock.patch.object(
            audit, "load_feature_frames", side_effect=[frames, failing]
        ), mock.patch.object(
            audit, "compare_nonfeature_topics", return_value=_nonfeature_pass()
        ), mock.patch.object(
            audit, "adjacent_essential_inlier_ratios",
            return_value={
                "pixel_threshold": 0.3,
                "method": "USAC_MAGSAC",
                "evaluated_adjacent_pairs": 4,
                "skipped_fewer_than_8": 0,
                "inlier_ratio_distribution": audit._quantiles([1.0] * 4),
                "common_id_count_distribution": audit._quantiles([12.0] * 4),
            },
        ), mock.patch("sys.stdout", new_callable=StringIO):
            self.assertEqual(audit.main(argv), 1)

        with mock.patch.object(
            audit.cv2, "USAC_MAGSAC", None, create=True
        ), mock.patch("sys.stdout", new_callable=StringIO) as stdout:
            self.assertEqual(audit.main(argv), 2)
            self.assertEqual(json.loads(stdout.getvalue())["status"], "ERROR")


if __name__ == "__main__":
    unittest.main()
