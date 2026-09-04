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

from scripts import audit_superpoint_lk_carrier_v1 as audit


SCHEMA = (
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

XFEAT_TEST_METHOD_SPEC = audit.AuditMethodSpec(
    method_id="xfeat_detector_raw_frame_lk_carrier_v1",
    schema_version="aqua-fe-xfeat-lk-carrier-audit-v1",
    expected_source_code=20,
    entrypoint_source=Path(audit.__file__).resolve(),
    expected_observations_per_frame=350,
)


def _camera() -> audit.CameraModel:
    return audit.CameraModel(
        fx=500.0,
        fy=500.0,
        cx=484.0,
        cy=304.0,
        distortion=(0.0, 0.0, 0.0, 0.0),
        width=968,
        height=608,
    )


def _base_pixels() -> np.ndarray:
    x, y = np.meshgrid(
        np.linspace(30.0, 938.0, 25),
        np.linspace(25.0, 583.0, 14),
    )
    return np.column_stack((x.reshape(-1), y.reshape(-1))).astype(np.float64)


def _frame(
    index: int,
    ids: np.ndarray | None = None,
    *,
    source_code: int = 10,
) -> audit.FeatureFrame:
    camera = _camera()
    if ids is None:
        ids = np.arange(350, dtype=np.int64)
    ids = np.asarray(ids, dtype=np.int64)
    pixels = _base_pixels()[ids % 350].copy()
    pixels[:, 0] += 0.05 * index
    normalized = np.column_stack(
        (
            (pixels[:, 0] - camera.cx) / camera.fx,
            (pixels[:, 1] - camera.cy) / camera.fy,
        )
    )
    velocity = np.zeros((len(ids), 2), dtype=np.float64)
    if index:
        velocity[:, 0] = 0.001
    channels = {
        "id": ids.astype(np.float64),
        "camera_id": np.zeros(len(ids), dtype=np.float64),
        "p_u": pixels[:, 0].copy(),
        "p_v": pixels[:, 1].copy(),
        "velocity_x": velocity[:, 0].copy(),
        "velocity_y": velocity[:, 1].copy(),
        "quality": np.ones(len(ids), dtype=np.float64),
        "sigma": np.ones(len(ids), dtype=np.float64),
        "source_code": np.full(len(ids), float(source_code), dtype=np.float64),
        "is_learned": np.ones(len(ids), dtype=np.float64),
    }
    return audit.FeatureFrame(
        index=index,
        record_stamp_ns=1_000_000_000 + index * 100_000_000,
        header_stamp_ns=1_000_000_000 + index * 100_000_000,
        header_seq=index,
        header_frame_id="world",
        schema=SCHEMA,
        channels=channels,
        ids=ids,
        pixels=pixels,
        normalized=normalized,
        point_z=np.ones(len(ids), dtype=np.float64),
        velocities=velocity,
    )


def _frames(count: int = 12) -> list[audit.FeatureFrame]:
    return [_frame(index) for index in range(count)]


def _nonfeature_ok(mode: str = "full_exact") -> dict[str, object]:
    return {"pass": True, "mode": mode, "violation_counts": {}}


def _all_inliers(left: np.ndarray, _right: np.ndarray, _focal: float) -> np.ndarray:
    return np.ones(len(left), dtype=np.uint8)


class FrozenScienceGateTests(unittest.TestCase):
    def test_frozen_gate_boundaries_keep_declared_strictness(self) -> None:
        self.assertTrue(audit._gate(0.05, "<=", 0.05)["pass"])
        self.assertTrue(audit._gate(10.0, ">=", 10.0)["pass"])
        self.assertFalse(audit._gate(0.3, "<", 0.3)["pass"])
        self.assertFalse(audit._gate(0.90, ">", 0.90)["pass"])

    def test_smooth_persistent_spatially_separated_candidate_passes(self) -> None:
        frames = _frames()
        result = audit.evaluate(
            frames,
            frames,
            _camera(),
            _nonfeature_ok(),
            solver=_all_inliers,
        )
        self.assertEqual(result["status"], "PASS")
        self.assertTrue(result["pass"])
        self.assertEqual(result["failed_gates"], [])
        self.assertEqual(
            result["metrics"]["deterministic_20px_thinning_count"]["distribution"]["median"],
            350.0,
        )
        self.assertEqual(
            result["metrics"]["lag10_common_id_count"]["median"], 350.0
        )

    def test_occurrence_churn_fails_frozen_lifecycle_gates(self) -> None:
        frames = []
        for index in range(12):
            ids = np.arange(index * 350, (index + 1) * 350, dtype=np.int64)
            frame = _frame(index, ids)
            frame = replace(
                frame,
                velocities=np.zeros_like(frame.velocities),
                channels={
                    **frame.channels,
                    "velocity_x": np.zeros(len(ids)),
                    "velocity_y": np.zeros(len(ids)),
                },
            )
            frames.append(frame)
        result = audit.evaluate(
            frames,
            frames,
            _camera(),
            _nonfeature_ok(),
            solver=_all_inliers,
        )
        self.assertEqual(result["status"], "FAIL")
        for name in (
            "birth_rate_median",
            "birth_rate_p90",
            "episode_lifetime_median",
            "episode_fraction_le2",
            "lag10_common_median",
        ):
            self.assertIn(name, result["failed_gates"])

    def test_deterministic_thinning_is_order_invariant_under_age_id_priority(self) -> None:
        pixels = np.asarray([[0.0, 0.0], [5.0, 0.0], [30.0, 0.0]])
        ids = np.asarray([20, 10, 30], dtype=np.int64)
        ages = {10: 5, 20: 1, 30: 2}
        forward = audit.deterministic_thinning_count(pixels, ids, ages)
        order = np.asarray([2, 0, 1])
        reversed_count = audit.deterministic_thinning_count(
            pixels[order], ids[order], ages
        )
        self.assertEqual(forward, 2)
        self.assertEqual(reversed_count, 2)


class CandidateContractTests(unittest.TestCase):
    def test_exact_350_observations_per_frame_is_structural_contract(self) -> None:
        reference = _frames()
        normal = audit.evaluate_contract(
            reference,
            _frames(),
            _camera(),
            _nonfeature_ok(),
            allow_prefix=False,
        )
        self.assertTrue(normal["pass"])
        self.assertEqual(normal["observations_per_frame"]["expected"], 350)
        self.assertEqual(
            normal["observations_per_frame"]["observed"],
            {"min": 350, "median": 350.0, "max": 350},
        )

        for count in (349, 351):
            with self.subTest(observations=count):
                ids = np.arange(count, dtype=np.int64)
                candidate = [_frame(index, ids) for index in range(12)]
                result = audit.evaluate_contract(
                    reference,
                    candidate,
                    _camera(),
                    _nonfeature_ok(),
                    allow_prefix=False,
                )
                self.assertFalse(result["pass"])
                self.assertEqual(
                    result["violation_counts"]["OBSERVATION_COUNT_NOT_EXACT"],
                    12,
                )
                self.assertEqual(
                    result["observations_per_frame"]["observed"],
                    {"min": count, "median": float(count), "max": count},
                )
                self.assertEqual(
                    result["first_violations"][0]["detail"],
                    {"expected": 350, "observed": count},
                )

    def test_expected_source_code_is_parameterized_without_changing_science_gates(
        self,
    ) -> None:
        frames20 = [_frame(index, source_code=20) for index in range(12)]
        accepted = audit.evaluate(
            frames20,
            frames20,
            _camera(),
            _nonfeature_ok(),
            method_spec=XFEAT_TEST_METHOD_SPEC,
            solver=_all_inliers,
        )
        rejected_by_default = audit.evaluate(
            frames20,
            frames20,
            _camera(),
            _nonfeature_ok(),
            solver=_all_inliers,
        )
        self.assertTrue(accepted["pass"])
        self.assertEqual(
            accepted["schema_version"], "aqua-fe-xfeat-lk-carrier-audit-v1"
        )
        self.assertEqual(
            accepted["method"]["method_id"],
            "xfeat_detector_raw_frame_lk_carrier_v1",
        )
        self.assertEqual(accepted["contract"]["fixed_fields"]["source_code"], 20.0)
        self.assertFalse(rejected_by_default["pass"])
        self.assertEqual(rejected_by_default["failed_gates"], ["contract"])
        self.assertIn(
            "CHANNEL_NOT_EXACT:source_code=10",
            rejected_by_default["contract"]["violation_counts"],
        )

    def test_explicit_prefix_schedule_and_full_default(self) -> None:
        reference = _frames(12)
        candidate = reference[:11]
        full = audit.evaluate_contract(
            reference,
            candidate,
            _camera(),
            _nonfeature_ok(),
            allow_prefix=False,
        )
        prefix = audit.evaluate_contract(
            reference,
            candidate,
            _camera(),
            _nonfeature_ok("prefix_through_cutoff"),
            allow_prefix=True,
        )
        self.assertFalse(full["pass"])
        self.assertIn("FEATURE_FRAME_COUNT_CHANGED", full["violation_counts"])
        self.assertTrue(prefix["pass"])

    def test_q_schema_normalized_velocity_and_z_are_contract_fields(self) -> None:
        reference = _frames()
        candidate = list(reference)
        frame = candidate[3]
        channels = dict(frame.channels)
        for name in ("quality", "sigma", "source_code", "is_learned"):
            channels[name] = channels[name].copy()
            channels[name][0] = -1.0
        normalized = frame.normalized.copy()
        normalized[1, 0] += 2e-6
        velocity = frame.velocities.copy()
        velocity[2, 0] += 2e-5
        candidate[3] = replace(
            frame,
            channels=channels,
            normalized=normalized,
            velocities=velocity,
            point_z=np.full(len(frame.ids), 0.99999999),
            schema=frame.schema + ("unexpected",),
        )
        result = audit.evaluate_contract(
            reference,
            candidate,
            _camera(),
            _nonfeature_ok(),
            allow_prefix=False,
        )
        self.assertFalse(result["pass"])
        for kind in (
            "CHANNEL_SCHEMA_CHANGED",
            "CHANNEL_NOT_EXACT:quality=1",
            "CHANNEL_NOT_EXACT:sigma=1",
            "CHANNEL_NOT_EXACT:source_code=10",
            "CHANNEL_NOT_EXACT:is_learned=1",
            "NORMALIZED_FROM_PIXEL_MISMATCH",
            "VELOCITY_FROM_PUBLISHED_DT_MISMATCH",
            "POINT_Z_NOT_EXACT_ONE",
        ):
            self.assertIn(kind, result["violation_counts"])

    def test_dead_id_reuse_and_duplicate_id_are_rejected(self) -> None:
        reference = _frames(3)
        candidate = [
            _frame(0, np.asarray([0, 1, 2])),
            _frame(1, np.asarray([1, 2])),
            _frame(2, np.asarray([0, 1, 1, 2])),
        ]
        result = audit.evaluate_contract(
            reference,
            candidate,
            _camera(),
            _nonfeature_ok(),
            allow_prefix=False,
        )
        self.assertIn("DEAD_ID_REUSED", result["violation_counts"])
        self.assertIn("DUPLICATE_ID_IN_FRAME", result["violation_counts"])


class CameraAndNonfeatureTests(unittest.TestCase):
    def test_camera_k_d_and_dimensions_load_from_root_or_cam0(self) -> None:
        body = (
            "image_width: 968\nimage_height: 608\n"
            "projection_parameters:\n"
            "  fx: 500.0\n  fy: 501.0\n  cx: 484.0\n  cy: 304.0\n"
            "distortion_parameters:\n"
            "  k1: 0.1\n  k2: -0.2\n  p1: 0.01\n  p2: 0.02\n"
        )
        with tempfile.TemporaryDirectory() as directory:
            for nested in (False, True):
                with self.subTest(cam0=nested):
                    path = Path(directory) / f"camera-{nested}.yaml"
                    content = body
                    if nested:
                        content = "cam0:\n" + "\n".join(
                            f"  {line}" for line in body.splitlines()
                        ) + "\n"
                    path.write_text("%YAML:1.0\n---\n" + content, encoding="utf-8")
                    camera = audit.load_camera_model(path)
                    self.assertEqual((camera.width, camera.height), (968, 608))
                    self.assertEqual(camera.distortion, (0.1, -0.2, 0.01, 0.02))

    def test_kannala_brandt_camera_load_and_normalization_are_model_aware(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "kannala.yaml"
            path.write_text(
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
            camera = audit.load_camera_model(path)
        self.assertEqual(camera.model, "kannala_brandt")
        self.assertEqual((camera.width, camera.height), (640, 512))
        self.assertEqual(
            camera.distortion,
            (
                -0.06125568297136998,
                -0.003796743395135256,
                0.027326634771204592,
                -0.030296403142887066,
            ),
        )
        pixels = np.asarray([[305.0, 259.0], [120.0, 80.0]], dtype=np.float64)
        expected = audit.cv2.fisheye.undistortPoints(
            pixels.reshape(-1, 1, 2), camera.matrix, camera.distortion_vector
        ).reshape(-1, 2)
        np.testing.assert_allclose(
            camera.undistort_points(pixels), expected, rtol=0.0, atol=1e-12
        )

    def test_nonfeature_full_and_prefix_compare_exact_serialized_tuples(self) -> None:
        class Stamp:
            def __init__(self, value: int) -> None:
                self.value = value

            def to_nsec(self) -> int:
                return self.value

        class Message:
            def __init__(self, payload: bytes) -> None:
                self.payload = payload

            def serialize(self, buffer) -> None:
                buffer.write(self.payload)

        rows: dict[str, list[tuple[str, Message, Stamp]]] = {
            "reference": [
                ("/imu", Message(b"a"), Stamp(90)),
                (audit.DEFAULT_FEATURE_TOPIC, Message(b"feature"), Stamp(100)),
                ("/gt", Message(b"b"), Stamp(100)),
                ("/imu", Message(b"tail"), Stamp(110)),
            ],
            "candidate": [
                ("/imu", Message(b"a"), Stamp(90)),
                (audit.DEFAULT_FEATURE_TOPIC, Message(b"changed-feature"), Stamp(100)),
                ("/gt", Message(b"b"), Stamp(100)),
            ],
            "candidate_extra": [
                ("/imu", Message(b"a"), Stamp(90)),
                ("/gt", Message(b"b"), Stamp(100)),
                ("/imu", Message(b"extra"), Stamp(105)),
            ],
        }
        rows["candidate_full"] = list(rows["reference"])

        class Bag:
            def __init__(self, path: str, _mode: str) -> None:
                self.path = path

            def __enter__(self):
                return self

            def __exit__(self, *_args) -> None:
                return None

            def read_messages(self):
                return iter(rows[self.path])

        fake_rosbag = types.SimpleNamespace(Bag=Bag)
        with mock.patch.dict(sys.modules, {"rosbag": fake_rosbag}):
            prefix = audit.compare_nonfeature(
                Path("reference"),
                Path("candidate"),
                audit.DEFAULT_FEATURE_TOPIC,
                cutoff_ns=100,
            )
            full = audit.compare_nonfeature(
                Path("reference"),
                Path("candidate"),
                audit.DEFAULT_FEATURE_TOPIC,
                cutoff_ns=None,
            )
            full_exact = audit.compare_nonfeature(
                Path("reference"),
                Path("candidate_full"),
                audit.DEFAULT_FEATURE_TOPIC,
                cutoff_ns=None,
            )
            extra = audit.compare_nonfeature(
                Path("reference"),
                Path("candidate_extra"),
                audit.DEFAULT_FEATURE_TOPIC,
                cutoff_ns=100,
            )
        self.assertTrue(prefix["pass"])
        self.assertFalse(full["pass"])
        self.assertTrue(full_exact["pass"])
        self.assertFalse(extra["pass"])
        self.assertIn(
            "CANDIDATE_NONFEATURE_AFTER_CUTOFF", extra["violation_counts"]
        )


class MagsacAndCliTests(unittest.TestCase):
    def test_superpoint_cli_method_identity_is_fixed_and_not_overridable(self) -> None:
        required = [
            "--reference-bag",
            "reference.bag",
            "--candidate-bag",
            "candidate.bag",
            "--camera-yaml",
            "camera.yaml",
        ]
        parsed = audit.build_parser().parse_args(required)
        self.assertFalse(hasattr(parsed, "expected_source_code"))
        with self.assertRaises(SystemExit):
            audit.build_parser().parse_args(
                required + ["--expected-source-code", "20"]
            )

    def test_magsac_parameters_nonzero_mask_and_missing_capability(self) -> None:
        points = np.column_stack(
            (np.linspace(-0.2, 0.2, 10), np.linspace(-0.1, 0.1, 10))
        ).astype(np.float32)
        mask = np.ones((10, 1), dtype=np.uint8)
        mask[0, 0] = 255
        with mock.patch.object(audit.cv2, "USAC_MAGSAC", 38, create=True), mock.patch.object(
            audit.cv2, "findEssentialMat", return_value=(np.eye(3), mask)
        ) as estimator:
            result = audit.magsac_essential_mask(points, points, 500.0)
        self.assertTrue(np.all(result))
        _, kwargs = estimator.call_args
        self.assertEqual(kwargs["method"], 38)
        self.assertEqual(kwargs["prob"], 0.999)
        self.assertEqual(kwargs["maxIters"], 200)
        self.assertAlmostEqual(kwargs["threshold"], 0.3 / 500.0)
        with mock.patch.object(audit.cv2, "USAC_MAGSAC", None, create=True):
            with self.assertRaisesRegex(audit.AuditInputError, "USAC_MAGSAC"):
                audit.require_usac_magsac()

    def test_cli_rc_canonical_output_no_clobber_and_alias(self) -> None:
        frames = _frames()
        argv = [
            "--reference-bag",
            "reference.bag",
            "--candidate-bag",
            "candidate.bag",
            "--camera-yaml",
            "camera.yaml",
        ]
        pass_result = {
            "schema_version": audit.SCHEMA_VERSION,
            "status": "PASS",
            "pass": True,
            "failed_gates": [],
        }
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "audit.json"
            with mock.patch.object(audit, "require_usac_magsac"), mock.patch.object(
                audit, "load_camera_model", return_value=_camera()
            ), mock.patch.object(
                audit, "load_feature_frames", side_effect=[frames, frames]
            ), mock.patch.object(
                audit, "compare_nonfeature", return_value=_nonfeature_ok()
            ), mock.patch.object(
                audit, "evaluate", return_value=dict(pass_result)
            ), mock.patch("sys.stdout", new_callable=StringIO) as stdout:
                rc = audit.main(argv + ["--output-json", str(output)])
            self.assertEqual(rc, 0)
            self.assertEqual(stdout.getvalue(), output.read_text(encoding="ascii"))
            payload = json.loads(stdout.getvalue())
            self.assertEqual(stdout.getvalue(), audit.canonical_json(payload) + "\n")
            self.assertEqual(payload["schema_version"], audit.SCHEMA_VERSION)
            self.assertEqual(
                payload["method"], audit.SUPERPOINT_AUDIT_METHOD_SPEC.identity()
            )
            self.assertEqual(
                payload["input"]["method"],
                audit.SUPERPOINT_AUDIT_METHOD_SPEC.identity(),
            )
            self.assertEqual(
                payload["audit_artifact"]["method"],
                audit.SUPERPOINT_AUDIT_METHOD_SPEC.identity(),
            )

            sentinel = output.read_bytes()
            with mock.patch("sys.stdout", new_callable=StringIO):
                self.assertEqual(
                    audit.main(argv + ["--output-json", str(output)]), 2
                )
            self.assertEqual(output.read_bytes(), sentinel)

        with mock.patch("sys.stdout", new_callable=StringIO):
            self.assertEqual(
                audit.main(argv + ["--output-json", "reference.bag"]), 2
            )

        fail_result = dict(pass_result, status="FAIL", **{"pass": False})
        with mock.patch.object(audit, "require_usac_magsac"), mock.patch.object(
            audit, "load_camera_model", return_value=_camera()
        ), mock.patch.object(
            audit, "load_feature_frames", side_effect=[frames, frames]
        ), mock.patch.object(
            audit, "compare_nonfeature", return_value=_nonfeature_ok()
        ), mock.patch.object(
            audit, "evaluate", return_value=fail_result
        ), mock.patch("sys.stdout", new_callable=StringIO):
            self.assertEqual(audit.main(argv), 1)

        with mock.patch.object(
            audit, "require_usac_magsac", side_effect=audit.AuditInputError("missing")
        ), mock.patch("sys.stdout", new_callable=StringIO) as stdout:
            self.assertEqual(audit.main(argv), 2)
            self.assertEqual(json.loads(stdout.getvalue())["status"], "ERROR")


if __name__ == "__main__":
    unittest.main()
