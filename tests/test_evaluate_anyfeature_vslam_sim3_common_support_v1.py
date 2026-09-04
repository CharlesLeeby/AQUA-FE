from __future__ import annotations

from decimal import Decimal
import hashlib
import json
import math
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from evaluate_anyfeature_vslam_sim3_common_support_v1 import (  # noqa: E402
    ARM_ORDER,
    AUDIT_FILENAME,
    ContractError,
    DegenerateAlignmentError,
    MANIFEST_FILENAME,
    METRICS_FILENAME,
    RC_NUMERIC_VALID,
    RC_SCIENTIFIC_INVALID,
    REFERENCE_ROLE,
    RESULT_FILENAME,
    PoseSeries,
    TrajectoryValidationError,
    apply_sim3_orientations,
    apply_sim3_positions,
    associate_reference_stamps,
    canonical_json_bytes,
    evaluate_pair,
    fit_umeyama_sim3,
    load_strict_tum,
    quaternion_xyzw_to_rotation,
    run_formal_evaluation,
    slerp_shortest_xyzw,
)


def yaw_quaternion(degrees: float) -> np.ndarray:
    angle = math.radians(degrees) / 2.0
    return np.asarray([0.0, 0.0, math.sin(angle), math.cos(angle)], dtype=float)


def rotation_z(degrees: float) -> np.ndarray:
    angle = math.radians(degrees)
    return np.asarray(
        [
            [math.cos(angle), -math.sin(angle), 0.0],
            [math.sin(angle), math.cos(angle), 0.0],
            [0.0, 0.0, 1.0],
        ],
        dtype=float,
    )


def make_series(
    stamps,
    positions,
    quaternions=None,
) -> PoseSeries:
    stamps_decimal = tuple(Decimal(str(value)) for value in stamps)
    position_array = np.asarray(positions, dtype=float).reshape((-1, 3))
    if quaternions is None:
        quaternion_array = np.tile([0.0, 0.0, 0.0, 1.0], (len(stamps_decimal), 1))
    else:
        quaternion_array = np.asarray(quaternions, dtype=float).reshape((-1, 4))
        quaternion_array /= np.linalg.norm(quaternion_array, axis=1, keepdims=True)
    return PoseSeries(
        stamps=stamps_decimal,
        positions=position_array,
        quaternions_xyzw=quaternion_array,
        data_row_count=len(stamps_decimal),
        quaternion_norm_min=1.0,
        quaternion_norm_max=1.0,
    )


def curved_positions(count: int = 46) -> np.ndarray:
    t = np.arange(count, dtype=float)
    return np.column_stack((t, np.sin(t / 4.0), 0.015 * t * t))


def write_tum(path: Path, stamps, positions, quaternions=None) -> None:
    positions_array = np.asarray(positions, dtype=float)
    if quaternions is None:
        quaternions_array = np.tile([0.0, 0.0, 0.0, 1.0], (len(positions_array), 1))
    else:
        quaternions_array = np.asarray(quaternions, dtype=float)
    lines = []
    for stamp, position, quaternion in zip(stamps, positions_array, quaternions_array):
        values = [str(stamp)] + [
            format(float(value), ".17g")
            for value in list(position) + list(quaternion)
        ]
        lines.append(" ".join(values))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


class StrictTumTest(unittest.TestCase):
    def test_loads_strictly_increasing_finite_unique_tum(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "trajectory.tum"
            path.write_text(
                "# comment\n0.000000 0 0 0 0 0 0 2\n"
                "1.000000 1 0 0 0 0 0 1\n",
                encoding="utf-8",
            )
            series = load_strict_tum(path, expected_count=2)
        self.assertEqual(series.stamps, (Decimal("0.000000"), Decimal("1.000000")))
        self.assertTrue(np.allclose(series.quaternions_xyzw[0], [0, 0, 0, 1]))
        self.assertEqual(series.quaternion_norm_max, 2.0)

    def test_rejects_duplicate_and_nonmonotonic_timestamps(self) -> None:
        for second_stamp, code in (("0", "DUPLICATE_TIMESTAMP"), ("-1", "NONMONOTONIC_TIMESTAMP")):
            with self.subTest(code=code), tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "bad.tum"
                path.write_text(
                    "0 0 0 0 0 0 0 1\n"
                    + second_stamp
                    + " 1 0 0 0 0 0 1\n",
                    encoding="utf-8",
                )
                with self.assertRaises(TrajectoryValidationError) as raised:
                    load_strict_tum(path, expected_count=None)
                self.assertEqual(raised.exception.code, code)

    def test_rejects_nonfinite_pose_and_invalid_quaternion(self) -> None:
        cases = (
            ("NaN 0 0 0 0 0 0 1\n", "NONFINITE_TIMESTAMP"),
            ("0 nan 0 0 0 0 0 1\n", "NONFINITE_POSE"),
            ("0 0 0 0 0 0 0 0\n", "INVALID_QUATERNION"),
        )
        for content, code in cases:
            with self.subTest(code=code), tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "bad.tum"
                path.write_text(content, encoding="utf-8")
                with self.assertRaises(TrajectoryValidationError) as raised:
                    load_strict_tum(path, expected_count=None)
                self.assertEqual(raised.exception.code, code)


class AssociationTest(unittest.TestCase):
    def test_exact_linear_and_shortest_arc_slerp(self) -> None:
        series = make_series(
            [0, 2],
            [[0, 0, 0], [2, 0, 0]],
            [yaw_quaternion(0), -yaw_quaternion(180)],
        )
        associations = associate_reference_stamps(
            [Decimal("0"), Decimal("1"), Decimal("2")], series
        )
        self.assertEqual([item.method for item in associations], ["EXACT", "INTERPOLATED", "EXACT"])
        self.assertTrue(np.allclose(associations[1].position, [1, 0, 0]))
        midpoint_rotation = quaternion_xyzw_to_rotation(
            associations[1].quaternion_xyzw
        )
        # Either +90 or -90 is a valid shortest route for a 180-degree tie;
        # the frozen sign rule makes it deterministic and still rotates x to y.
        self.assertTrue(np.allclose(midpoint_rotation @ [1, 0, 0], [0, 1, 0], atol=1e-12))

    def test_slerp_handles_antipodal_same_rotation(self) -> None:
        quaternion = yaw_quaternion(70)
        midpoint = slerp_shortest_xyzw(quaternion, -quaternion, 0.5)
        self.assertTrue(
            np.allclose(
                quaternion_xyzw_to_rotation(midpoint),
                quaternion_xyzw_to_rotation(quaternion),
                atol=1e-12,
            )
        )

    def test_forbids_extrapolation_and_rejects_gap_over_two_seconds(self) -> None:
        series = make_series([1, 4], [[1, 0, 0], [4, 0, 0]])
        associations = associate_reference_stamps(
            [Decimal("0"), Decimal("2"), Decimal("5")], series
        )
        self.assertEqual(
            [item.method for item in associations],
            ["OUT_OF_RANGE", "GAP_EXCEEDED", "OUT_OF_RANGE"],
        )
        self.assertFalse(any(item.valid for item in associations))

        boundary = make_series([0, 2], [[0, 0, 0], [2, 0, 0]])
        self.assertTrue(
            associate_reference_stamps([Decimal("1")], boundary)[0].valid
        )


class Sim3Test(unittest.TestCase):
    def test_recovers_rotation_scale_translation_and_rotates_orientation(self) -> None:
        source = curved_positions(12)
        rotation = rotation_z(37.0)
        scale = 2.75
        translation = np.asarray([4.0, -3.0, 1.25])
        target = scale * (rotation @ source.T).T + translation
        sim3 = fit_umeyama_sim3(source, target)
        self.assertAlmostEqual(sim3.scale, scale, places=12)
        self.assertTrue(np.allclose(sim3.rotation, rotation, atol=1e-12))
        self.assertTrue(np.allclose(sim3.translation, translation, atol=1e-12))
        self.assertTrue(np.allclose(apply_sim3_positions(sim3, source), target, atol=1e-11))

        aligned_quaternion = apply_sim3_orientations(
            sim3, np.asarray([[0.0, 0.0, 0.0, 1.0]])
        )[0]
        self.assertTrue(
            np.allclose(
                quaternion_xyzw_to_rotation(aligned_quaternion), rotation, atol=1e-12
            )
        )

    def test_rejects_collinear_degenerate_alignment(self) -> None:
        source = np.column_stack((np.arange(5, dtype=float), np.zeros((5, 2))))
        with self.assertRaises(DegenerateAlignmentError):
            fit_umeyama_sim3(source, source * 2.0)


class CommonSupportTest(unittest.TestCase):
    def test_independent_sim3_on_identical_mask_has_zero_metrics(self) -> None:
        reference_positions = curved_positions()
        reference = make_series(range(46), reference_positions)
        arm_values = {}
        transforms = (
            (rotation_z(25), 3.0, np.asarray([5.0, 1.0, -2.0])),
            (rotation_z(-41), 0.4, np.asarray([-7.0, 2.0, 3.0])),
        )
        for name, (rotation, scale, translation) in zip(ARM_ORDER, transforms):
            # Invert reference = s R arm + t to construct monocular arm poses.
            positions = ((rotation.T @ (reference_positions - translation).T).T) / scale
            arm_values[name] = make_series(range(46), positions)
        evaluation, _, _, _ = evaluate_pair(reference, arm_values)
        support = evaluation["support"]
        self.assertTrue(support["numeric_claim_valid"])
        self.assertEqual(support["common_reference_count"], 46)
        self.assertEqual(support["rpe_pair_count"], 45)
        for name in ARM_ORDER:
            self.assertLess(
                evaluation["metrics"][name]["translation_ape"]["rmse_m"], 1e-12
            )
            self.assertLess(
                evaluation["metrics"][name]["translation_rpe_1s_reference_grid"]["rmse_m"],
                1e-12,
            )

    def test_intersection_mask_and_rpe_do_not_bridge_missing_row(self) -> None:
        positions = curved_positions()
        reference = make_series(range(46), positions)
        orb = make_series(range(46), positions)
        # Remove keyframes around t=20 so reference t=20 has a 4 s bracket and
        # is invalid, while the other arm remains fully valid.
        keep = [index for index in range(46) if index not in (19, 20, 21)]
        r2d2 = make_series(keep, positions[keep])
        evaluation, _, _, _ = evaluate_pair(
            reference, {"orb32": orb, "r2d2_128": r2d2}
        )
        support = evaluation["support"]
        self.assertEqual(support["per_arm_valid_reference_count"]["orb32"], 46)
        self.assertEqual(support["per_arm_valid_reference_count"]["r2d2_128"], 43)
        self.assertEqual(support["common_reference_count"], 43)
        self.assertEqual(support["rpe_pair_count"], 41)
        self.assertNotIn([18, 22], support["rpe_pairs_reference_indices"])

    def test_insufficient_common_support_suppresses_all_numeric_values(self) -> None:
        positions = curved_positions()
        reference = make_series(range(46), positions)
        short = make_series(range(20), positions[:20])
        evaluation, _, aligned_positions, aligned_quaternions = evaluate_pair(
            reference, {"orb32": short, "r2d2_128": short}
        )
        self.assertFalse(evaluation["support"]["numeric_claim_valid"])
        self.assertIsNone(evaluation["metrics"])
        self.assertIsNone(evaluation["alignments"])
        self.assertEqual(aligned_positions, {})
        self.assertEqual(aligned_quaternions, {})

    def test_degenerate_common_geometry_is_audited_without_metrics(self) -> None:
        t = np.arange(46, dtype=float)
        collinear = np.column_stack((t, np.zeros((46, 2))))
        reference = make_series(range(46), collinear)
        arm = make_series(range(46), collinear)
        evaluation, _, _, _ = evaluate_pair(
            reference, {"orb32": arm, "r2d2_128": arm}
        )
        self.assertTrue(evaluation["support"]["support_valid"])
        self.assertFalse(evaluation["support"]["numeric_claim_valid"])
        self.assertIsNone(evaluation["metrics"])
        self.assertIn("rank deficient", evaluation["alignment_failures"]["orb32"])


class FormalCliCoreTest(unittest.TestCase):
    def test_publishes_canonical_json_csv_audit_manifest_and_is_no_clobber(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            stamps = [str(1542829000 + index) for index in range(46)]
            reference_positions = curved_positions()
            reference_path = root / "reference.tum"
            orb_path = root / "orb.tum"
            r2d2_path = root / "r2d2.tum"
            write_tum(reference_path, stamps, reference_positions)

            rotation = rotation_z(32)
            arm_positions = ((rotation.T @ (reference_positions - [3, -2, 1]).T).T) / 1.7
            write_tum(orb_path, stamps, arm_positions)
            write_tum(r2d2_path, stamps, arm_positions * 0.5 + [2, 1, -3])
            output = root / "evaluation"

            return_code, publication = run_formal_evaluation(
                reference_path, orb_path, r2d2_path, output
            )
            self.assertEqual(return_code, RC_NUMERIC_VALID)
            self.assertEqual(Path(publication["result"]), output / RESULT_FILENAME)
            for filename in (
                RESULT_FILENAME,
                METRICS_FILENAME,
                AUDIT_FILENAME,
                MANIFEST_FILENAME,
            ):
                self.assertTrue((output / filename).is_file())

            manifest = json.loads((output / MANIFEST_FILENAME).read_text())
            for filename in (RESULT_FILENAME, METRICS_FILENAME, AUDIT_FILENAME):
                payload = (output / filename).read_bytes()
                self.assertEqual(
                    manifest["files"][filename]["sha256"],
                    hashlib.sha256(payload).hexdigest(),
                )
                self.assertEqual(
                    manifest["files"][filename]["size_bytes"], len(payload)
                )

            raw_result = (output / RESULT_FILENAME).read_bytes()
            parsed = json.loads(raw_result)
            self.assertEqual(raw_result, canonical_json_bytes(parsed))
            self.assertEqual(
                parsed["claim_boundary"]["reference_role"], REFERENCE_ROLE
            )
            self.assertFalse(
                parsed["claim_boundary"]["reference_is_independent_ground_truth"]
            )
            self.assertTrue(parsed["evaluation"]["support"]["numeric_claim_valid"])
            self.assertEqual(len((output / AUDIT_FILENAME).read_text().splitlines()), 47)

            with self.assertRaises(ContractError):
                run_formal_evaluation(reference_path, orb_path, r2d2_path, output)

    def test_actual_cli_returns_two_and_canonical_json_on_no_clobber(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "already_exists"
            output.mkdir()
            command = [
                sys.executable,
                str(ROOT / "scripts/evaluate_anyfeature_vslam_sim3_common_support_v1.py"),
                "--reference-proxy",
                str(root / "missing_reference.tum"),
                "--orb32-trajectory",
                str(root / "missing_orb.tum"),
                "--r2d2-trajectory",
                str(root / "missing_r2d2.tum"),
                "--output-dir",
                str(output),
            ]
            completed = subprocess.run(command, check=False, capture_output=True)
        self.assertEqual(completed.returncode, 2)
        document = json.loads(completed.stdout)
        self.assertEqual(completed.stdout, canonical_json_bytes(document))
        self.assertEqual(document["status"], "CONTRACT_BLOCKED")

    def test_reference_must_have_exactly_46_rows_and_creates_no_output(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            positions = curved_positions(45)
            stamps = [str(1542829000 + index) for index in range(45)]
            reference_path = root / "reference.tum"
            orb_path = root / "orb.tum"
            r2d2_path = root / "r2d2.tum"
            write_tum(reference_path, stamps, positions)
            write_tum(orb_path, stamps, positions)
            write_tum(r2d2_path, stamps, positions)
            output = root / "evaluation"
            with self.assertRaises(ContractError):
                run_formal_evaluation(reference_path, orb_path, r2d2_path, output)
            self.assertFalse(output.exists())

    def test_invalid_official_arm_returns_one_and_blanks_metrics(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            stamps = [str(1542829000 + index) for index in range(46)]
            positions = curved_positions()
            reference_path = root / "reference.tum"
            orb_path = root / "orb.tum"
            r2d2_path = root / "r2d2.tum"
            write_tum(reference_path, stamps, positions)
            write_tum(orb_path, stamps, positions)
            r2d2_path.write_text("", encoding="utf-8")
            output = root / "evaluation"

            return_code, _ = run_formal_evaluation(
                reference_path, orb_path, r2d2_path, output
            )
            self.assertEqual(return_code, RC_SCIENTIFIC_INVALID)
            result = json.loads((output / RESULT_FILENAME).read_text())
            self.assertIsNone(result["evaluation"]["metrics"])
            self.assertEqual(
                result["trajectory_audit"]["r2d2_128"]["error_code"],
                "EMPTY_TRAJECTORY",
            )
            self.assertEqual(
                result["evaluation"]["support"]["per_arm_valid_reference_count"]["orb32"],
                46,
            )
            metrics_text = (output / METRICS_FILENAME).read_text()
            self.assertNotIn("nan", metrics_text.lower())
            self.assertIn(REFERENCE_ROLE, metrics_text)


if __name__ == "__main__":
    unittest.main()
