#!/usr/bin/env python3
"""Synthetic and timestamp-only tests for the Stage6 common-support evaluator."""

from __future__ import annotations

import hashlib
import contextlib
import importlib.util
import io
import json
import math
import os
from pathlib import Path
import signal
import stat
import tempfile
import unittest

import numpy as np


ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "scripts/evaluate_hfnet_supervins_v1_official_euroc_mh01_common_support_v1.py"
SPEC = importlib.util.spec_from_file_location("stage6_common_support_eval", str(MODULE_PATH))
assert SPEC is not None and SPEC.loader is not None
M = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(M)


def synthetic_points(n: int = 24) -> np.ndarray:
    t = np.linspace(-1.3, 2.1, n)
    return np.column_stack((t, 0.3 * t * t + 0.2 * np.sin(t), np.sin(1.7 * t) + 0.1 * t))


def rotation_z(angle: float) -> np.ndarray:
    c, s = math.cos(angle), math.sin(angle)
    return np.array([[c, -s, 0.0], [s, c, 0.0], [0.0, 0.0, 1.0]])


def exact_synthetic_common() -> dict:
    gt = synthetic_points(M.COMMON_COUNT)
    hf = (rotation_z(-0.25) @ (gt - np.array([1.0, 0.5, -0.2])).T).T
    sv = (rotation_z(0.65) @ (gt - np.array([-0.4, 1.2, 0.7])).T).T
    rows = [{"common_row_index": i, "camera_row_index": M.COMMON_FIRST + 2 * i,
             "source_timestamp_ns": M.COMMON_FIRST_NS + 100_000_000 * i,
             "gt_position": gt[i].tolist(), "hfnet_position": hf[i].tolist(),
             "supervins_position": sv[i].tolist()} for i in range(M.COMMON_COUNT)]
    pairs = [{"pair_row_index": i, "left_association_index": i, "right_association_index": i + 10,
              "left_camera_row_index": M.COMMON_FIRST + 2 * i,
              "right_camera_row_index": M.COMMON_FIRST + 2 * (i + 10),
              "left_timestamp_ns": M.COMMON_FIRST_NS + 100_000_000 * i,
              "right_timestamp_ns": M.COMMON_FIRST_NS + 100_000_000 * (i + 10),
              "delta_ns": M.RPE_DELTA_NS} for i in range(M.RPE_COUNT)]
    return {"rows": rows, "pairs": pairs, "gt": gt, "hfnet": hf, "supervins": sv}


class TimestampTests(unittest.TestCase):
    def test_hf_timestamp_string_exact(self) -> None:
        text = "1403636627013555457.000000"
        self.assertEqual(M.hf_timestamp_to_ns(text), 1403636627013555457)
        self.assertNotEqual(int(float(text)), 1403636627013555457)

    def test_hf_timestamp_rejects_fraction(self) -> None:
        with self.assertRaises(ValueError):
            M.hf_timestamp_to_ns("1403636627013555456.000001")

    def test_hf_timestamp_rejects_short_integer(self) -> None:
        with self.assertRaises(ValueError):
            M.hf_timestamp_to_ns("123.000000")

    def test_supervins_fixed6_decimal(self) -> None:
        self.assertEqual(M.decimal_fixed6_seconds_to_ns("1403636582.913555"), 1403636582913555000)

    def test_supervins_rejects_nonfixed_text(self) -> None:
        with self.assertRaises(ValueError):
            M.decimal_fixed6_seconds_to_ns("1403636582.9135554")

    def test_real_timestamp_only_support_contract(self) -> None:
        audit = M.support_audit_from_bytes(M.HF_TRAJECTORY.read_bytes(), M.SV_TRAJECTORY.read_bytes(), M.CAMERA_CSV.read_bytes(), M.GT_CSV.read_bytes())
        self.assertTrue(audit["ok"], audit["failures"])
        self.assertFalse(audit["scientific_values_parsed"])
        self.assertEqual(audit["counts"]["common"], 1358)
        self.assertEqual(audit["counts"]["rpe_pairs"], 1348)

    def test_real_common_timestamp_endpoints(self) -> None:
        audit = M.support_audit_from_bytes(M.HF_TRAJECTORY.read_bytes(), M.SV_TRAJECTORY.read_bytes(), M.CAMERA_CSV.read_bytes(), M.GT_CSV.read_bytes())
        self.assertEqual(audit["common"]["first_timestamp_ns"], M.COMMON_FIRST_NS)
        self.assertEqual(audit["common"]["last_timestamp_ns"], M.COMMON_LAST_NS)
        self.assertEqual(audit["common"]["span_ns"], 135700000000)

    def test_real_sv_fixed6_histogram(self) -> None:
        audit = M.support_audit_from_bytes(M.HF_TRAJECTORY.read_bytes(), M.SV_TRAJECTORY.read_bytes(), M.CAMERA_CSV.read_bytes(), M.GT_CSV.read_bytes())
        self.assertEqual(audit["sv_text_minus_source_ns_histogram"], {"-456": 1086, "544": 724})

    def test_hf_timestamp_off_by_one_fails_support(self) -> None:
        lines = M.HF_TRAJECTORY.read_bytes().splitlines()
        fields = lines[0].split()
        fields[0] = b"1403636627013555457.000000"
        lines[0] = b" ".join(fields)
        audit = M.support_audit_from_bytes(b"\n".join(lines) + b"\n", M.SV_TRAJECTORY.read_bytes(), M.CAMERA_CSV.read_bytes(), M.GT_CSV.read_bytes())
        self.assertFalse(audit["ok"])
        self.assertIn("hf_camera_binding:0", audit["failures"])

    def test_supervins_over_1000ns_fails_support(self) -> None:
        lines = M.SV_TRAJECTORY.read_bytes().splitlines()
        fields = lines[0].split(); fields[0] = b"1403636582.913557"; lines[0] = b" ".join(fields)
        audit = M.support_audit_from_bytes(M.HF_TRAJECTORY.read_bytes(), b"\n".join(lines) + b"\n", M.CAMERA_CSV.read_bytes(), M.GT_CSV.read_bytes())
        self.assertFalse(audit["ok"])
        self.assertIn("sv_camera_binding:0", audit["failures"])

    def test_supervins_wrong_camera_formula_fails_support(self) -> None:
        camera = M.parse_camera(M.CAMERA_CSV.read_bytes())
        lines = M.SV_TRAJECTORY.read_bytes().splitlines()
        fields = lines[0].split()
        fields[0] = (format(camera[64]["timestamp_ns"] / 1e9, ".6f")).encode("ascii")
        lines[0] = b" ".join(fields)
        audit = M.support_audit_from_bytes(M.HF_TRAJECTORY.read_bytes(), b"\n".join(lines) + b"\n", M.CAMERA_CSV.read_bytes(), M.GT_CSV.read_bytes())
        self.assertFalse(audit["ok"])

    def test_missing_exact_gt_timestamp_fails_support(self) -> None:
        lines = M.GT_CSV.read_bytes().splitlines()
        needle = str(M.COMMON_FIRST_NS).encode("ascii") + b","
        modified = [line for line in lines if not line.startswith(needle)]
        self.assertEqual(len(lines) - len(modified), 1)
        audit = M.support_audit_from_bytes(M.HF_TRAJECTORY.read_bytes(), M.SV_TRAJECTORY.read_bytes(), M.CAMERA_CSV.read_bytes(), b"\n".join(modified) + b"\n")
        self.assertFalse(audit["ok"])
        self.assertIn("exact_gt_join", audit["failures"])

    def test_rpe_pair_endpoints_and_off_by_one(self) -> None:
        camera = M.parse_camera(M.CAMERA_CSV.read_bytes())
        stamps = [camera[i]["timestamp_ns"] for i in range(945, 3660, 2)]
        pairs = [(i, i + 10) for i in range(len(stamps) - 10)]
        self.assertEqual((pairs[0], pairs[-1], len(pairs)), ((0, 10), (1347, 1357), 1348))
        self.assertEqual({stamps[right] - stamps[left] for left, right in pairs}, {1_000_000_000})
        wrong = [(i, i + 9) for i in range(len(stamps) - 9)]
        self.assertEqual(len(wrong), 1349)
        self.assertNotEqual({stamps[right] - stamps[left] for left, right in wrong}, {1_000_000_000})

    def test_exact_support_constants(self) -> None:
        indices = list(range(945, 3660, 2))
        self.assertEqual((indices[0], indices[-1], len(indices)), (945, 3659, 1358))
        self.assertEqual(len(indices) - 10, 1348)


class FrameAndParsingTests(unittest.TestCase):
    def test_both_t_bs_are_identity(self) -> None:
        expected = np.eye(4).tolist()
        self.assertEqual(M.parse_t_bs_bytes(M.GT_SENSOR.read_bytes()), expected)
        self.assertEqual(M.parse_t_bs_bytes(M.IMU_SENSOR.read_bytes()), expected)

    def test_gt_wxyz_becomes_xyzw(self) -> None:
        payload = b"1,1,2,3,0.5,0.1,0.2,0.3,0,0,0,0,0,0,0,0,0\n"
        row = M.parse_gt(payload, False)[0]
        self.assertEqual(row["position"], [1.0, 2.0, 3.0])
        self.assertEqual(row["quaternion_xyzw"], [0.1, 0.2, 0.3, 0.5])

    def test_hf_pose_position_not_camera_transformed(self) -> None:
        payload = b"1403636627013555456.000000 1 2 3 0 0 0 1\n"
        self.assertEqual(M.parse_hf(payload, False)[0]["position"], [1.0, 2.0, 3.0])

    def test_supervins_pose_position_not_camera_transformed(self) -> None:
        payload = b"1403636627.013555 4 5 6 0 0 0 1\n"
        self.assertEqual(M.parse_sv(payload, False)[0]["position"], [4.0, 5.0, 6.0])

    def test_parse_rejects_nonfinite_pose(self) -> None:
        with self.assertRaises(ValueError):
            M.parse_hf(b"1403636627013555456.000000 nan 2 3 0 0 0 1\n", False)


class AlignmentTests(unittest.TestCase):
    def test_se3_recovers_synthetic_rigid_transform(self) -> None:
        source = synthetic_points()
        target = (rotation_z(0.4) @ source.T).T + np.array([2.0, -1.0, 0.5])
        result = M.rigid_se3_alignment(source, target)
        self.assertLess(float(np.max(np.abs(result["aligned"] - target))), 1e-12)
        self.assertTrue(M.alignment_audit(result)["proper"])

    def test_two_systems_are_fit_independently(self) -> None:
        gt = synthetic_points()
        hf = (rotation_z(-0.25) @ (gt - np.array([1.0, 0.5, -0.2])).T).T
        sv = (rotation_z(0.65) @ (gt - np.array([-0.4, 1.2, 0.7])).T).T
        pairs = [{"left_association_index": i, "right_association_index": i + 1} for i in range(len(gt) - 1)]
        hf_eval = M.evaluate_one_system(hf, gt, pairs)
        sv_eval = M.evaluate_one_system(sv, gt, pairs)
        self.assertLess(float(np.max(np.abs(hf_eval["se3"]["aligned"] - gt))), 1e-12)
        self.assertLess(float(np.max(np.abs(sv_eval["se3"]["aligned"] - gt))), 1e-12)
        shared_wrong = (hf_eval["se3"]["rotation"] @ sv.T).T + hf_eval["se3"]["translation"]
        self.assertGreater(float(np.max(np.abs(shared_wrong - gt))), 0.1)

    def test_full_support_shape_mismatch_rejected(self) -> None:
        with self.assertRaises(ValueError):
            M.rigid_se3_alignment(synthetic_points(12), synthetic_points(11))

    def test_se3_rank_one_rejected(self) -> None:
        source = np.column_stack((np.arange(5.0), np.zeros(5), np.zeros(5)))
        with self.assertRaises(ValueError):
            M.rigid_se3_alignment(source, source.copy())

    def test_sim3_rank_one_rejected(self) -> None:
        source = np.column_stack((np.arange(5.0), np.zeros(5), np.zeros(5)))
        with self.assertRaises(ValueError):
            M.proper_umeyama_sim3(source, source.copy())

    def test_sim3_positive_scale(self) -> None:
        source = synthetic_points()
        target = 1.7 * (rotation_z(0.3) @ source.T).T + np.array([1.0, 2.0, -0.2])
        result = M.proper_umeyama_sim3(source, target)
        self.assertAlmostEqual(result["scale"], 1.7, places=12)
        self.assertTrue(M.alignment_audit(result)["proper"])

    def test_reflected_correspondence_returns_proper_rotation(self) -> None:
        source = synthetic_points()
        target = source.copy(); target[:, 0] *= -1.0
        result = M.rigid_se3_alignment(source, target)
        self.assertGreater(np.linalg.det(result["rotation"]), 0.0)

    def test_core_crosscheck_synthetic(self) -> None:
        source = synthetic_points()
        target = (rotation_z(0.2) @ source.T).T + 0.3
        fresh = M.rigid_se3_alignment(source, target)["aligned"]
        core = M.STAGE5.core_align_se3_positions(source, target)
        self.assertLessEqual(float(np.max(np.abs(fresh - core))), 1e-12)

    def test_fixed_scale_primary_does_not_correct_scale(self) -> None:
        source = synthetic_points()
        target = 2.0 * source
        result = M.rigid_se3_alignment(source, target)
        self.assertEqual(result["scale"], 1.0)
        self.assertGreater(float(np.max(np.abs(result["aligned"] - target))), 0.1)

    def test_sim3_cannot_replace_primary_flag(self) -> None:
        gt = synthetic_points()
        source = gt / 1.5
        pairs = [{"left_association_index": i, "right_association_index": i + 1} for i in range(len(gt) - 1)]
        evaluation = M.evaluate_one_system(source, gt, pairs)
        secondary = evaluation["metrics"]["secondary_sim3_scale_diagnostic"]
        self.assertFalse(secondary["may_replace_primary"])
        self.assertFalse(secondary["may_enter_cross_system_ordering"])

    def test_actual_common_wiring_uses_exact_support_and_independent_fits(self) -> None:
        common = exact_synthetic_common()
        evaluation = M.evaluate_common_systems(common)
        self.assertEqual(evaluation["hfnet_source"].shape, (1358, 3))
        self.assertEqual(evaluation["supervins_source"].shape, (1358, 3))
        self.assertTrue(evaluation["hfnet"]["alignment_audit"]["primary_fixed_scale_se3"]["proper"])
        self.assertTrue(evaluation["supervins"]["alignment_audit"]["primary_fixed_scale_se3"]["proper"])
        self.assertFalse(np.allclose(evaluation["hfnet"]["se3"]["rotation"], evaluation["supervins"]["se3"]["rotation"]))
        metrics = M.build_metrics_document({"coverage": {}}, evaluation["hfnet"], evaluation["supervins"])
        self.assertTrue(M.validate_metrics_contrast_schema(metrics)["ok"])
        self.assertTrue(M.metrics_finite_nonnegative(metrics))

    def test_actual_common_wiring_rejects_full_support(self) -> None:
        common = exact_synthetic_common()
        common["rows"].append(dict(common["rows"][-1]))
        common["gt"] = np.vstack((common["gt"], common["gt"][-1]))
        common["hfnet"] = np.vstack((common["hfnet"], common["hfnet"][-1]))
        common["supervins"] = np.vstack((common["supervins"], common["supervins"][-1]))
        with self.assertRaises(ValueError):
            M.evaluate_common_systems(common)

    def test_body_position_wiring_has_no_extrinsic_argument(self) -> None:
        rows = [{"gt_position": [1, 2, 3], "hfnet_position": [4, 5, 6], "supervins_position": [7, 8, 9]}]
        arrays = M.body_position_arrays(rows)
        self.assertEqual(arrays["gt"].tolist(), [[1.0, 2.0, 3.0]])
        self.assertEqual(arrays["hfnet"].tolist(), [[4.0, 5.0, 6.0]])
        self.assertEqual(arrays["supervins"].tolist(), [[7.0, 8.0, 9.0]])

    def test_se3_target_rank_one_rejected(self) -> None:
        source = synthetic_points(8)
        target = np.column_stack((np.arange(8.0), np.zeros(8), np.zeros(8)))
        with self.assertRaises(ValueError):
            M.rigid_se3_alignment(source, target)

    def test_se3_covariance_rank_one_rejected(self) -> None:
        u = np.array([1.0, -1.0, 0.0, 0.0])
        v = np.array([0.0, 0.0, 1.0, -1.0])
        w = np.array([1.0, 1.0, -1.0, -1.0])
        source = np.column_stack((u, v, np.zeros(4)))
        target = np.column_stack((u, w, np.zeros(4)))
        self.assertEqual(np.linalg.matrix_rank(source - source.mean(0)), 2)
        self.assertEqual(np.linalg.matrix_rank(target - target.mean(0)), 2)
        self.assertEqual(np.linalg.matrix_rank((source - source.mean(0)).T @ (target - target.mean(0))), 1)
        with self.assertRaises(ValueError):
            M.rigid_se3_alignment(source, target)

    def test_sim3_reflection_is_corrected_to_proper_rotation(self) -> None:
        source = synthetic_points()
        target = source.copy(); target[:, 0] *= -1.0
        result = M.proper_umeyama_sim3(source, target)
        self.assertGreater(np.linalg.det(result["rotation"]), 0.0)
        self.assertGreater(result["scale"], 0.0)


class MetricAndSerializationTests(unittest.TestCase):
    def test_descriptive_stats_reject_nan(self) -> None:
        with self.assertRaises(ValueError):
            M.descriptive_stats(np.asarray([0.0, np.nan]))

    def test_canonical_json_reject_nan(self) -> None:
        with self.assertRaises(ValueError):
            M.canonical_json_bytes({"x": float("nan")})

    def test_metric_samples_exact_pairs(self) -> None:
        gt = synthetic_points(14)
        aligned = gt + np.array([0.1, 0.0, 0.0])
        pairs = [{"left_association_index": i, "right_association_index": i + 10} for i in range(4)]
        ape, rpe = M.metric_samples(gt, aligned, pairs)
        self.assertEqual((len(ape), len(rpe)), (14, 4))
        self.assertTrue(np.allclose(rpe, 0.0))

    def test_manifest_self_hash_tamper(self) -> None:
        value = {"entries": {}, "self_hash": None, "schema_version": "x"}
        value["self_hash"] = M.self_hash_object(value)
        self.assertEqual(value["self_hash"], M.self_hash_object(value))
        value["schema_version"] = "y"
        self.assertNotEqual(value["self_hash"], M.self_hash_object(value))

    def test_artifact_tree_order_independent(self) -> None:
        a = {"b": {"sha256": "2", "size_bytes": 2}, "a": {"sha256": "1", "size_bytes": 1}}
        b = dict(reversed(list(a.items())))
        self.assertEqual(M.artifact_tree_digest(a), M.artifact_tree_digest(b))

    def test_report_boundary_blocks_ordering_wording(self) -> None:
        self.assertFalse(M.validate_report_boundary(["method A is superior to method B"])["ok"])
        self.assertTrue(M.validate_report_boundary(["side-by-side descriptive values only"])["ok"])

    def test_metrics_schema_blocks_cross_system_contrast_field(self) -> None:
        for key in ("cross_system_delta", "metric_ratio", "best", "p_value", "confidence_interval", "effect_size", "percent_improvement"):
            audit = M.validate_metrics_contrast_schema({key: 1.0})
            self.assertFalse(audit["ok"])
            self.assertTrue(audit["forbidden_contrast_fields"])

    def test_within_system_rpe_delta_is_confined_to_csv_not_metrics(self) -> None:
        self.assertIn("delta_ns", M.RPE_HEADER)
        self.assertNotIn("delta_ns", json.dumps({"support": {"rpe_pair_time_ns": M.RPE_DELTA_NS}}))


class FigureTests(unittest.TestCase):
    def test_horizontal_gridline_coordinates(self) -> None:
        body, audit = M.panel_svg([([0, 1], [0, 1], "#000", "x", "")], {"xmin": 0.0, "xmax": 1.0, "ymin": 0.0, "ymax": 1.0}, 10, 20, 100, 80, "x", "y", "p")
        self.assertTrue(audit["horizontal_coordinates_valid"])
        self.assertTrue(all(row["x1"] == 10 and row["x2"] == 110 and row["y1"] == row["y2"] for row in audit["horizontal_gridlines"]))
        self.assertIn('class="grid-h"', body)

    def test_trajectory_equal_metric_aspect(self) -> None:
        gt = synthetic_points()
        svg, audit = M.trajectory_figure(gt, gt + 0.01, gt - 0.02)
        self.assertTrue(audit["equal_metric_aspect_all_axes"])
        self.assertTrue(audit["gridline_coordinates_valid"])
        self.assertIn("shared_metres_per_pixel", svg)

    def test_error_axes_lower_zero(self) -> None:
        t = np.linspace(0, 10, 20)
        svg, audit = M.error_figure(t, 0.1 + t * 0.01, 0.2 + t * 0.01, t[10:], 0.2 + t[10:] * 0.01, 0.3 + t[10:] * 0.01)
        self.assertTrue(audit["all_axis_lower_bounds_exact_zero"])
        self.assertTrue(audit["gridline_coordinates_valid"])
        self.assertIn('"xmin":0.0', html_unescape(svg))

    def test_error_figure_rejects_negative_source(self) -> None:
        with self.assertRaises(ValueError):
            M.error_figure(np.array([-1.0, 0.0]), np.array([0.1, 0.2]), np.array([0.2, 0.3]), np.array([0.0]), np.array([0.1]), np.array([0.2]))


def html_unescape(text: str) -> str:
    import html
    return html.unescape(text)


class FilesystemAndControlTests(unittest.TestCase):
    def test_write_bytes_exclusive_mode_nlink_and_no_overwrite(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "x.json"
            identity = M.write_bytes_exclusive(path, b"{}\n")
            self.assertEqual((identity["mode"], identity["nlink"]), ("0444", 1))
            with self.assertRaises(FileExistsError):
                M.write_bytes_exclusive(path, b"changed")

    def test_held_snapshot_detects_path_replacement(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "input"
            path.write_bytes(b"original")
            os.chmod(path, 0o644)
            spec = {str(path.resolve()): {"sha256": hashlib.sha256(b"original").hexdigest(), "size_bytes": 8, "mode": "0644", "nlink": 1}}
            snap = M.held_snapshot_open([path], spec)
            replacement = Path(directory) / "replacement"
            replacement.write_bytes(b"original")
            os.replace(replacement, path)
            try:
                self.assertFalse(M.held_snapshot_postflight(snap, spec)["ok"])
            finally:
                M.close_held_snapshot(snap)

    def test_held_snapshot_rejects_symlink(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "target"; target.write_bytes(b"x")
            link = Path(directory) / "link"; link.symlink_to(target)
            spec = {str(link.resolve()): {"sha256": hashlib.sha256(b"x").hexdigest(), "size_bytes": 1}}
            with self.assertRaises(OSError):
                M.held_snapshot_open([link], spec)

    def test_held_snapshot_detects_postopen_symlink_to_original_inode(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "input"; path.write_bytes(b"original"); os.chmod(path, 0o644)
            spec = {str(path.resolve()): {"sha256": hashlib.sha256(b"original").hexdigest(), "size_bytes": 8, "mode": "0644", "nlink": 1}}
            snap = M.held_snapshot_open([path], spec)
            moved = Path(directory) / "moved"
            path.rename(moved)
            path.symlink_to(moved)
            try:
                self.assertFalse(M.held_snapshot_postflight(snap, spec)["ok"])
            finally:
                M.close_held_snapshot(snap)

    def test_general_identity_and_pin_audit_reject_symlink(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "target"; target.write_bytes(b"x")
            link = Path(directory) / "link"; link.symlink_to(target)
            with self.assertRaises(OSError):
                M.file_identity(link)
            spec = {str(link): {"sha256": hashlib.sha256(b"x").hexdigest(), "size_bytes": 1}}
            self.assertFalse(M.inspect_pins(spec)["ok"])

    def test_signal_is_pending_only(self) -> None:
        old = M.PENDING_SIGNAL
        try:
            M.PENDING_SIGNAL = None
            M._signal_handler(signal.SIGTERM, None)
            self.assertEqual(M.PENDING_SIGNAL, signal.SIGTERM)
            with self.assertRaises(M.ControlledSignal):
                M.raise_if_pending()
        finally:
            M.PENDING_SIGNAL = old

    def test_source_does_not_import_subprocess(self) -> None:
        source = MODULE_PATH.read_text(encoding="utf-8")
        self.assertNotRegex(source, r"(?m)^import subprocess|^from subprocess")

    def test_required_bundle_file_set(self) -> None:
        self.assertEqual(len(M.REQUIRED_BUNDLE_FILES), 12)
        self.assertEqual(len(set(M.REQUIRED_BUNDLE_FILES)), 12)
        self.assertIn("analysis-output/artifact-manifest.json", M.REQUIRED_BUNDLE_FILES)

    def test_freeze_contract_no_single_initialization_claim(self) -> None:
        freeze = json.loads(M.FREEZE.read_text(encoding="utf-8"))
        disclosure = freeze["comparison_and_claim_contract"]["mandatory_disclosure"]
        self.assertIn("first output", disclosure)
        self.assertIn("must not be described as one uninterrupted initialization delay", disclosure)

    def test_authority_absent_is_not_valid(self) -> None:
        if M.AUTHORITY.exists():
            self.skipTest("separate authority exists after PRESTART")
        audit = M.authority_audit({})
        self.assertFalse(audit["valid"])

    def _build_bundle(self, root: Path):
        old_attempt, old_analysis = M.ATTEMPT, M.ANALYSIS
        attempt = root / "attempt_001"; analysis = attempt / "analysis-output"
        (analysis / "figures").mkdir(parents=True)
        M.ATTEMPT, M.ANALYSIS = attempt, analysis
        expected = {}
        try:
            for relative in M.REQUIRED_BUNDLE_FILES:
                if relative.endswith("artifact-manifest.json"):
                    continue
                path = attempt / relative
                expected[relative] = M.write_bytes_exclusive(path, (relative + "\n").encode("utf-8"))
            manifest = {"schema_version": "test", "entry_count": len(expected), "entries": dict(expected),
                        "bundle_content_tree_sha256": M.artifact_tree_digest(expected), "self_hash": None}
            manifest["self_hash"] = M.self_hash_object(manifest)
            expected["analysis-output/artifact-manifest.json"] = M.write_json_exclusive(analysis / "artifact-manifest.json", manifest)
            return old_attempt, old_analysis, attempt, analysis, expected
        except BaseException:
            M.ATTEMPT, M.ANALYSIS = old_attempt, old_analysis
            raise

    def test_bundle_tamper_is_detected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            old_attempt, old_analysis, attempt, analysis, expected = self._build_bundle(Path(directory))
            try:
                self.assertTrue(M.audit_completed_bundle(expected)["ok"])
                target = analysis / "metrics.json"; os.chmod(target, 0o644); target.write_bytes(b"tamper\n")
                self.assertFalse(M.audit_completed_bundle(expected)["ok"])
            finally:
                M.ATTEMPT, M.ANALYSIS = old_attempt, old_analysis

    def test_attempt_extra_bundle_file_is_detected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            old_attempt, old_analysis, attempt, analysis, expected = self._build_bundle(Path(directory))
            try:
                self.assertTrue(M.audit_completed_bundle(expected)["exact_file_set"])
                (analysis / "extra.txt").write_text("extra", encoding="utf-8")
                self.assertFalse(M.audit_completed_bundle(expected)["exact_file_set"])
            finally:
                M.ATTEMPT, M.ANALYSIS = old_attempt, old_analysis

    def test_early_pending_signal_writes_single_fail_terminal(self) -> None:
        names = ("EVIDENCE_ROOT", "ATTEMPT", "ANALYSIS", "FIGURES", "START_CLAIM", "PREFLIGHT_RESULT", "RUN_RESULT")
        old_paths = {name: getattr(M, name) for name in names}
        old_collect = M.collect_prestart
        old_state = (M.PENDING_SIGNAL, M.NAMESPACE_OWNED, M.TERMINAL_COMMITTED)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "evidence"; attempt = root / "attempt_001"
            replacements = {"EVIDENCE_ROOT": root, "ATTEMPT": attempt, "ANALYSIS": attempt / "analysis-output",
                            "FIGURES": attempt / "analysis-output/figures", "START_CLAIM": attempt / "evaluation_start_claim.json",
                            "PREFLIGHT_RESULT": attempt / "preflight_result.json", "RUN_RESULT": attempt / "run_result.json"}
            try:
                for name, value in replacements.items(): setattr(M, name, value)
                M.collect_prestart = lambda require_authority=False: {"ready": True, "status": "GO_EXACTLY_ONE_PURE_COMMON_SUPPORT_EVALUATION_START", "failures": [], "pin_snapshot": {}, "authority": {}}
                M.PENDING_SIGNAL, M.NAMESPACE_OWNED, M.TERMINAL_COMMITTED = signal.SIGTERM, False, False
                with contextlib.redirect_stdout(io.StringIO()):
                    self.assertEqual(M.run_once(M.TOKEN), 1)
                files = [path for path in attempt.rglob("*") if path.is_file()]
                self.assertEqual(files, [attempt / "run_result.json"])
                terminal = json.loads((attempt / "run_result.json").read_text(encoding="utf-8"))
                self.assertTrue(terminal["status"].startswith("FAIL_"))
                self.assertFalse(terminal["retry_authorized"])
                self.assertEqual(set(("error", "preflight_pin_snapshot", "held_snapshot_postflight", "post_pin_audit", "artifacts_before_result")) - set(terminal), set())
                info = (attempt / "run_result.json").stat()
                self.assertEqual((stat.S_IMODE(info.st_mode), info.st_nlink), (0o444, 1))
            finally:
                for name, value in old_paths.items(): setattr(M, name, value)
                M.collect_prestart = old_collect
                M.PENDING_SIGNAL, M.NAMESPACE_OWNED, M.TERMINAL_COMMITTED = old_state

    def test_root_parent_fsync_failure_after_mkdir_writes_terminal(self) -> None:
        names = ("EVIDENCE_ROOT", "ATTEMPT", "ANALYSIS", "FIGURES", "START_CLAIM", "PREFLIGHT_RESULT", "RUN_RESULT")
        old_paths = {name: getattr(M, name) for name in names}
        old_collect, old_fsync = M.collect_prestart, M.fsync_directory
        old_state = (M.PENDING_SIGNAL, M.NAMESPACE_OWNED, M.TERMINAL_COMMITTED)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "evidence"; attempt = root / "attempt_001"
            replacements = {"EVIDENCE_ROOT": root, "ATTEMPT": attempt, "ANALYSIS": attempt / "analysis-output",
                            "FIGURES": attempt / "analysis-output/figures", "START_CLAIM": attempt / "evaluation_start_claim.json",
                            "PREFLIGHT_RESULT": attempt / "preflight_result.json", "RUN_RESULT": attempt / "run_result.json"}
            injected = {"raised": False}
            def fail_first_root_parent_fsync(path: Path) -> None:
                if path == root.parent and not injected["raised"]:
                    injected["raised"] = True
                    raise OSError("injected root parent fsync failure")
                old_fsync(path)
            try:
                for name, value in replacements.items(): setattr(M, name, value)
                M.collect_prestart = lambda require_authority=False: {"ready": True, "status": "GO_EXACTLY_ONE_PURE_COMMON_SUPPORT_EVALUATION_START", "failures": [], "pin_snapshot": {}, "authority": {}}
                M.fsync_directory = fail_first_root_parent_fsync
                M.PENDING_SIGNAL, M.NAMESPACE_OWNED, M.TERMINAL_COMMITTED = None, False, False
                with contextlib.redirect_stdout(io.StringIO()):
                    self.assertEqual(M.run_once(M.TOKEN), 1)
                self.assertTrue(injected["raised"])
                self.assertTrue(root.is_dir())
                files = [path for path in attempt.rglob("*") if path.is_file()]
                self.assertEqual(files, [attempt / "run_result.json"])
                terminal_path = attempt / "run_result.json"
                terminal = json.loads(terminal_path.read_text(encoding="utf-8"))
                self.assertTrue(terminal["status"].startswith("FAIL_"))
                self.assertEqual(terminal["error"]["type"], "OSError")
                self.assertEqual(terminal["error"]["message"], "injected root parent fsync failure")
                self.assertFalse(terminal["retry_authorized"])
                self.assertEqual(set(("preflight_pin_snapshot", "held_snapshot_postflight", "post_pin_audit", "artifacts_before_result")) - set(terminal), set())
                info = terminal_path.stat()
                self.assertEqual((stat.S_IMODE(info.st_mode), info.st_nlink), (0o444, 1))
            finally:
                for name, value in old_paths.items(): setattr(M, name, value)
                M.collect_prestart, M.fsync_directory = old_collect, old_fsync
                M.PENDING_SIGNAL, M.NAMESPACE_OWNED, M.TERMINAL_COMMITTED = old_state

    def test_ordinary_exception_after_claim_writes_complete_fail_terminal(self) -> None:
        names = ("EVIDENCE_ROOT", "ATTEMPT", "ANALYSIS", "FIGURES", "START_CLAIM", "PREFLIGHT_RESULT", "RUN_RESULT", "AUTHORITY")
        old_paths = {name: getattr(M, name) for name in names}
        old_collect, old_open = M.collect_prestart, M.held_snapshot_open
        old_state = (M.PENDING_SIGNAL, M.NAMESPACE_OWNED, M.TERMINAL_COMMITTED)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "evidence"; attempt = root / "attempt_001"; authority = Path(directory) / "authority.json"
            authority.write_text("{}\n", encoding="utf-8"); os.chmod(authority, 0o444)
            replacements = {"EVIDENCE_ROOT": root, "ATTEMPT": attempt, "ANALYSIS": attempt / "analysis-output", "FIGURES": attempt / "analysis-output/figures",
                            "START_CLAIM": attempt / "evaluation_start_claim.json", "PREFLIGHT_RESULT": attempt / "preflight_result.json", "RUN_RESULT": attempt / "run_result.json", "AUTHORITY": authority}
            try:
                for name, value in replacements.items(): setattr(M, name, value)
                fake_pin = {"checks": {"x": {"expected": {"sha256": "0", "size_bytes": 0}}}, "failures": [], "ok": True}
                M.collect_prestart = lambda require_authority=False: {"ready": True, "status": "GO_EXACTLY_ONE_PURE_COMMON_SUPPORT_EVALUATION_START", "failures": [], "pin_snapshot": fake_pin, "authority": {"identity": M.file_identity(authority, True)}}
                M.held_snapshot_open = lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("injected ordinary exception"))
                M.PENDING_SIGNAL, M.NAMESPACE_OWNED, M.TERMINAL_COMMITTED = None, False, False
                with contextlib.redirect_stdout(io.StringIO()): self.assertEqual(M.run_once(M.TOKEN), 1)
                terminal = json.loads((attempt / "run_result.json").read_text(encoding="utf-8"))
                self.assertIn("evaluation_start_claim.json", terminal["artifacts_before_result"])
                self.assertIn("preflight_result.json", terminal["artifacts_before_result"])
                self.assertEqual(terminal["preflight_pin_snapshot"], fake_pin)
                self.assertEqual(terminal["error"]["message"], "injected ordinary exception")
                self.assertEqual((stat.S_IMODE((attempt / "run_result.json").stat().st_mode), (attempt / "run_result.json").stat().st_nlink), (0o444, 1))
            finally:
                for name, value in old_paths.items(): setattr(M, name, value)
                M.collect_prestart, M.held_snapshot_open = old_collect, old_open
                M.PENDING_SIGNAL, M.NAMESPACE_OWNED, M.TERMINAL_COMMITTED = old_state

    def test_partial_bundle_exception_is_recorded_before_terminal(self) -> None:
        names = ("EVIDENCE_ROOT", "ATTEMPT", "ANALYSIS", "FIGURES", "START_CLAIM", "PREFLIGHT_RESULT", "RUN_RESULT", "AUTHORITY")
        old_paths = {name: getattr(M, name) for name in names}
        old_collect, old_open, old_support, old_generate = M.collect_prestart, M.held_snapshot_open, M.support_audit_from_bytes, M.generate_analysis_bundle
        old_state = (M.PENDING_SIGNAL, M.NAMESPACE_OWNED, M.TERMINAL_COMMITTED)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "evidence"; attempt = root / "attempt_001"; authority = Path(directory) / "authority.json"
            authority.write_text("{}\n", encoding="utf-8"); os.chmod(authority, 0o444)
            replacements = {"EVIDENCE_ROOT": root, "ATTEMPT": attempt, "ANALYSIS": attempt / "analysis-output", "FIGURES": attempt / "analysis-output/figures",
                            "START_CLAIM": attempt / "evaluation_start_claim.json", "PREFLIGHT_RESULT": attempt / "preflight_result.json", "RUN_RESULT": attempt / "run_result.json", "AUTHORITY": authority}
            try:
                for name, value in replacements.items(): setattr(M, name, value)
                M.collect_prestart = lambda require_authority=False: {"ready": True, "status": "GO_EXACTLY_ONE_PURE_COMMON_SUPPORT_EVALUATION_START", "failures": [], "pin_snapshot": {"checks": {}, "failures": [], "ok": True}, "authority": {"identity": M.file_identity(authority, True)}}
                records = {str(path.resolve()): {"payload": b"", "fd": -1, "opened_identity": {}} for path in M.SNAPSHOT_PATHS}
                M.held_snapshot_open = lambda *_args, **_kwargs: {"records": records, "requested_paths": list(records), "ok": True}
                M.support_audit_from_bytes = lambda *_args: {"ok": True, "coverage": {}, "counts": {"common": 1358, "rpe_pairs": 1348}}
                def fail_after_one_file(_snapshot, _support):
                    M.write_bytes_exclusive(M.ANALYSIS / "metrics.json", b"partial\n")
                    raise RuntimeError("injected partial bundle exception")
                M.generate_analysis_bundle = fail_after_one_file
                M.PENDING_SIGNAL, M.NAMESPACE_OWNED, M.TERMINAL_COMMITTED = None, False, False
                with contextlib.redirect_stdout(io.StringIO()): self.assertEqual(M.run_once(M.TOKEN), 1)
                terminal_path = attempt / "run_result.json"; terminal = json.loads(terminal_path.read_text(encoding="utf-8"))
                self.assertIn("analysis-output/metrics.json", terminal["artifacts_before_result"])
                self.assertEqual(terminal["error"]["message"], "injected partial bundle exception")
                self.assertGreaterEqual(terminal_path.stat().st_mtime_ns, (attempt / "analysis-output/metrics.json").stat().st_mtime_ns)
            finally:
                for name, value in old_paths.items(): setattr(M, name, value)
                M.collect_prestart, M.held_snapshot_open = old_collect, old_open
                M.support_audit_from_bytes, M.generate_analysis_bundle = old_support, old_generate
                M.PENDING_SIGNAL, M.NAMESPACE_OWNED, M.TERMINAL_COMMITTED = old_state

    def test_authority_audit_and_identity_change_gate(self) -> None:
        old_authority = M.AUTHORITY
        with tempfile.TemporaryDirectory() as directory:
            authority = Path(directory) / "authority.json"; M.AUTHORITY = authority
            try:
                document = {
                    "schema_version": M.AUTHORITY_SCHEMA,
                    "status": "AUTHORIZED_EXACTLY_ONE_PURE_COMMON_SUPPORT_EVALUATION_ATTEMPT_001_START",
                    "authorization_token_sha256": M.TOKEN_SHA256, "controller_command": M.CONTROLLER_COMMAND,
                    "fresh_evidence_root": str(M.EVIDENCE_ROOT), "attempt": "attempt_001", "maximum_evaluator_starts": 1,
                    "retry_authorized": False, "root_confirmation": "ROOT_CONFIRMED_STAGE6_EXACTLY_ONE_PURE_COMMON_SUPPORT_EVALUATION",
                    "claim_boundary": {"pure_existing_artifact_computation_only": True, "model_ros_publisher_or_trajectory_generation_authorized": False,
                                       "cross_system_metric_contrast_authorized": False, "performance_ordering_authorized": False,
                                       "inferential_statistics_authorized": False, "next_stage_automatically_authorized": False},
                    "lock": M.file_identity(M.LOCK), "protocol": M.file_identity(M.FREEZE), "runner": M.file_identity(M.RUNNER),
                    "tests": M.file_identity(M.TESTS), "test_receipt": M.file_identity(M.TEST_RECEIPT),
                }
                M.write_json_exclusive(authority, document)
                before = M.authority_audit({})
                self.assertTrue(before["valid"], before["failures"])
                os.chmod(authority, 0o644); authority.write_text("{}\n", encoding="utf-8")
                after = M.authority_audit({})
                self.assertFalse(after["valid"])
                self.assertNotEqual(before["identity"], after["identity"])
            finally:
                M.AUTHORITY = old_authority

    def test_run_source_requires_authority_pre_post_identity_equality(self) -> None:
        source = MODULE_PATH.read_text(encoding="utf-8")
        self.assertIn('authority_post.get("identity") != preflight["authority"].get("identity")', source)


if __name__ == "__main__":
    unittest.main()
