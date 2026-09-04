#!/usr/bin/env python3

from __future__ import annotations

import copy
import hashlib
import json
import math
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import numpy as np

from scripts import evaluate_hfnet_v6_samehistory_positive_roster_common_support_v1 as evaluator


ROOT = Path(__file__).resolve().parents[2]


def yaw_quaternion(degrees: float) -> np.ndarray:
    half = math.radians(degrees) / 2.0
    return np.asarray([0.0, 0.0, math.sin(half), math.cos(half)], dtype=float)


def trajectory_positions(
    stamps_ns: np.ndarray, origin_ns: int, *, collinear: bool
) -> np.ndarray:
    step = (
        np.asarray(stamps_ns, dtype=np.int64) - origin_ns
    ) / evaluator.GRID_STEP_NS
    if collinear:
        return np.column_stack((step, np.zeros((len(step), 2))))
    return np.column_stack(
        (0.03 * step, np.sin(step / 9.0), 0.0007 * step * step)
    )


def full_timestamps(
    case_id: str = "a05_3300_3700",
) -> dict[str, np.ndarray]:
    grid = evaluator.make_case_grid_ns(case_id)
    return {name: grid.copy() for name in evaluator.SOURCE_ORDER}


def fake_identity(
    path: str, *, size_bytes: int = 1, digest: str = "a" * 64
) -> dict[str, object]:
    return {"path": path, "size_bytes": size_bytes, "sha256": digest}


def payload_identity(path: str, payload: bytes) -> dict[str, object]:
    return {
        "path": path,
        "size_bytes": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest(),
    }


def matrix_binding(matrix: np.ndarray) -> dict[str, object]:
    values = np.asarray(matrix, dtype=float)
    return {
        "matrix": values.tolist(),
        "matrix_sha256": evaluator.static_matrix_sha256(values),
    }


def plain_v2_authorities() -> dict[str, object]:
    return json.loads(
        evaluator.canonical_json_bytes(
            dict(evaluator.V2_ROSTER_AUTHORITY_IDENTITIES)
        ).decode("utf-8")
    )


def valid_future_lock(
    case_id: str = "a05_3300_3700",
) -> dict[str, object]:
    dataset = evaluator.CASE_TABLE[case_id].dataset
    semantics = evaluator.DATASET_FRAME_CONTRACTS[dataset]
    estimate_matrix = np.eye(4)
    frame_contract: dict[str, object] = {
        "dataset": dataset,
        "semantic_contract": dict(semantics),
        "common_target_frame": semantics["common_target_frame"],
        "per_source_pose_semantics_frozen": True,
        "static_transform_direction_tested": True,
        "interpolation_before_static_extrinsic": True,
        "target_before_alignment_fit": True,
        "published_common_vehicle_body_verified": dataset == "CIRS",
        "camera_transform_used_as_body_transform": False,
    }
    if dataset == "AQUALOC_ARCHAEOLOGY":
        estimate_matrix = np.asarray(
            evaluator.AQUALOC_IMU_T_CAMERA, dtype=float
        )
        frame_contract.update(
            {
                "imu_T_camera": matrix_binding(estimate_matrix),
                "camera_T_imu": matrix_binding(
                    np.asarray(evaluator.AQUALOC_CAMERA_T_IMU, dtype=float)
                ),
                "calibration_authority": dict(
                    evaluator.AQUALOC_CALIBRATION_IDENTITY
                ),
                "inverse_forbidden_as_estimate_bridge": True,
            }
        )
    elif dataset == "CIRS":
        estimate_matrix = np.asarray(
            evaluator.CIRS_IMU_T_VEHICLE, dtype=float
        )
        frame_contract.update(
            {
                "vehicle_T_imu": matrix_binding(
                    np.asarray(evaluator.CIRS_VEHICLE_T_IMU, dtype=float)
                ),
                "imu_T_vehicle": matrix_binding(estimate_matrix),
                "calibration_representation": (
                    "FULL_PRECISION_ORIGINAL_TF_PRIMARY"
                ),
                "canonical_zero_snapping": "DISPLAY_ONLY_NOT_NUMERIC",
                "original_quaternion_sealed": True,
                "historical_online_camera_extrinsic_ignored_for_body_bridge": (
                    True
                ),
                "evidence_sha256": dict(evaluator.CIRS_FRAME_EVIDENCE_SHA256),
            }
        )

    sources: dict[str, object] = {}
    for name in evaluator.SOURCE_ORDER:
        timestamp_contract: dict[str, object] = {
            "unit": "integer_nanoseconds",
            "offset_ns": 0,
            "nearest_association": False,
            "extrapolation": False,
        }
        if name == "hfnet":
            timestamp_contract.update(
                {
                    "stock_epoch_bridge_max_absolute_delta_ns": 256,
                    "bridge_mapping": (
                        "BIJECTIVE_UNIQUE_SOURCE_CAMERA_HEADER_REPLACEMENT"
                    ),
                    "source_header_reuse": False,
                    "bridge_receipt": fake_identity(
                        "/future/hfnet_bridge.json"
                    ),
                }
            )
        is_reference = name == "reference"
        sources[name] = {
            "trajectory": fake_identity(f"/future/{name}.tum"),
            "timestamp_contract": timestamp_contract,
            "pose_convention": {
                "serialized": "world_T_source",
                "analysis": "world_T_target",
                "serialized_quaternion_order": (
                    "wxyz"
                    if name in ("learned_plus_klt", "klt")
                    else "xyzw"
                ),
                "analysis_quaternion_order": "xyzw",
                "quaternion_conversion": (
                    "LOSSLESS_PERMUTATION_WXYZ_TO_XYZW"
                    if name in ("learned_plus_klt", "klt")
                    else "IDENTITY_LOSSLESS"
                ),
                "static_transform": {
                    "identity": fake_identity(
                        f"/future/{name}_transform.json"
                    ),
                    "source_frame": (
                        semantics["reference_source_frame"]
                        if is_reference
                        else semantics["estimate_source_frame"]
                    ),
                    "target_frame": semantics["common_target_frame"],
                    "source_T_target": (
                        np.eye(4).tolist()
                        if is_reference
                        else estimate_matrix.tolist()
                    ),
                    "convention": "source_T_target",
                    "semantic": (
                        semantics["reference_transform"]
                        if is_reference
                        else semantics["estimate_transform"]
                    ),
                },
            },
        }

    return {
        "schema_version": evaluator.ANALYSIS_LOCK_SCHEMA,
        "status": "LOCKED_BEFORE_ACCURACY",
        "case_id": case_id,
        "authority_hashes": dict(evaluator.FROZEN_AUTHORITY_HASHES),
        "v2_roster_authorities": plain_v2_authorities(),
        "analysis_grid_prefreeze": dict(
            evaluator.ANALYSIS_GRID_PREFREEZE_IDENTITY
        ),
        "imported_pure_helpers": {
            "trajectory_eval_core": dict(evaluator.PURE_HELPER_IDENTITY)
        },
        "claims": {"analysis_started": False, "accuracy_measured": False},
        "evaluator": fake_identity("/future/evaluator.py"),
        "hfnet_runability_receipt": {
            "identity": fake_identity("/future/hfnet_receipt.json"),
            "status": "PASS",
        },
        "frame_convention_seal": fake_identity(
            "/future/frame_convention_seal.json"
        ),
        "frame_contract": frame_contract,
        "sources": sources,
        "evo_verification": {
            "evo_ape": dict(evaluator.EVO_APE_IDENTITY),
            "evo_rpe": dict(evaluator.EVO_RPE_IDENTITY),
            "environment_seal": fake_identity(
                "/future/evo_environment_seal.json"
            ),
            "environment_contract": dict(evaluator.EVO_ENVIRONMENT_CONTRACT),
            "version": "v1.31.1",
            "alignment": "OWN_GLOBAL_SE3_-a_FIXED_SCALE_1",
            "use_scale": False,
            "scale_flag": None,
            "timestamp_basis": (
                "relative_zero_from_authoritative_integer_ns"
            ),
            "population_binding": (
                "COUNT_AND_ORDERED_INTEGER_NS_LIST_SHA256"
            ),
            "maximum_absolute_rmse_disagreement_m": 1e-5,
        },
        "native_anchor_sensitivity": {
            "required": True,
            "descriptive_only": True,
            "run_only_after_primary_gate": True,
            "can_reopen_primary_gate": False,
            "expected_native_anchor_count": 21,
            "native_reference": fake_identity(
                "/future/native_reference.csv"
            ),
        },
    }


def formal_verification(
    lock: dict[str, object], **overrides: object
) -> evaluator.FormalIdentityVerification:
    values: dict[str, object] = {
        "verification_receipt_identity": fake_identity(
            "/future/formal_verification.json"
        ),
        "execution_lock_value_sha256": hashlib.sha256(
            evaluator.canonical_json_bytes(lock)
        ).hexdigest(),
        "execution_lock_file_identity_verified": True,
        "evaluator_self_identity_verified": True,
        "controller_self_identity_verified": True,
        "evidence_identities_verified": True,
        "pre_metric_toctou_verified": True,
    }
    values.update(overrides)
    return evaluator.FormalIdentityVerification(**values)  # type: ignore[arg-type]


def validated_lock(
    case_id: str = "a05_3300_3700",
) -> evaluator.ValidatedExecutionLock:
    lock = valid_future_lock(case_id)
    return evaluator.validate_future_execution_lock(
        lock, formal_verification(lock)
    )


def failed_runability_lock(
    case_id: str = "a05_3300_3700",
) -> evaluator.ValidatedExecutionLock:
    lock = valid_future_lock(case_id)
    lock["hfnet_runability_receipt"]["status"] = "FAIL"  # type: ignore[index]
    return evaluator.validate_future_execution_lock(
        lock, formal_verification(lock)
    )


def locked_timestamps(
    execution_lock: evaluator.ValidatedExecutionLock,
    timestamps: dict[str, np.ndarray] | None = None,
) -> dict[str, evaluator.LockedTimestampSeriesNs]:
    values = (
        timestamps
        if timestamps is not None
        else full_timestamps(execution_lock.case_id)
    )
    return {
        name: evaluator.LockedTimestampSeriesNs(
            stamps_ns=values[name],
            trajectory_identity=execution_lock.trajectory_identities[name],
        )
        for name in evaluator.SOURCE_ORDER
    }


def pose_mapping(
    timestamps: dict[str, np.ndarray],
    execution_lock: evaluator.ValidatedExecutionLock,
    *,
    scaled_hfnet: bool = False,
    collinear: bool = False,
    varying_orientation: bool = False,
) -> dict[str, evaluator.PoseSeriesNs]:
    origin_ns = evaluator.CASE_TABLE[
        execution_lock.case_id
    ].score_start_header_ns
    output: dict[str, evaluator.PoseSeriesNs] = {}
    for name in evaluator.SOURCE_ORDER:
        stamps = np.asarray(timestamps[name], dtype=np.int64)
        target_positions = trajectory_positions(
            stamps, origin_ns, collinear=collinear
        )
        if scaled_hfnet and name == "hfnet":
            target_positions = 2.0 * target_positions
        step = (stamps - origin_ns) / evaluator.GRID_STEP_NS
        target_quaternions = np.asarray(
            [
                yaw_quaternion(
                    0.7 * float(value) if varying_orientation else 0.0
                )
                for value in step
            ]
        )
        matrix = np.asarray(
            execution_lock.transforms[name].source_T_target, dtype=float
        )
        source_R_target = matrix[:3, :3]
        source_t_target = matrix[:3, 3]
        source_positions = np.empty_like(target_positions)
        source_quaternions = np.empty_like(target_quaternions)
        for index, (target_position, target_quaternion) in enumerate(
            zip(target_positions, target_quaternions)
        ):
            world_R_target = evaluator.quaternion_xyzw_to_rotation(
                target_quaternion
            )
            world_R_source = world_R_target @ source_R_target.T
            source_positions[index] = (
                target_position - world_R_source @ source_t_target
            )
            source_quaternions[index] = (
                evaluator.rotation_to_quaternion_xyzw(world_R_source)
            )
        output[name] = evaluator.PoseSeriesNs(
            stamps_ns=stamps,
            positions=source_positions,
            quaternions_xyzw=source_quaternions,
            trajectory_identity=execution_lock.trajectory_identities[name],
        )
    return output


def split_timestamps() -> dict[str, np.ndarray]:
    timestamps = full_timestamps()
    timestamps["hfnet"] = np.delete(timestamps["hfnet"], [60, 61])
    return timestamps


def controller_evaluation(
    *, split: bool = False
) -> tuple[dict[str, object], evaluator.EvoAdapterPlan]:
    token = validated_lock()
    timestamps = split_timestamps() if split else full_timestamps()
    primary, plan = evaluator.evaluate_case_for_controller(
        "a05_3300_3700",
        locked_timestamps(token, timestamps),
        token,
        Path("/tmp/aqua-fe-synthetic-evo-plan"),
        pose_loader=lambda: pose_mapping(
            timestamps, token, varying_orientation=True
        ),
    )
    if plan is None:
        raise AssertionError(
            "synthetic controller evaluation unexpectedly closed"
        )
    return primary, plan


def synthetic_evo_receipt(
    primary: dict[str, object],
    plan: evaluator.EvoAdapterPlan,
    *,
    ape_values: dict[str, float] | None = None,
    rpe_values: dict[tuple[str, int], float] | None = None,
) -> tuple[dict[str, object], object, dict[str, bytes]]:
    ape_values = ape_values or {}
    rpe_values = rpe_values or {}
    store = dict(plan.generated_tum_payloads)
    commands: list[dict[str, object]] = []
    for command in plan.document["commands"]:
        arm = command["arm"]
        if command["kind"] == "APE":
            value = ape_values.get(
                arm,
                float(
                    primary["metrics"][arm]["translation_ape"]["rmse_m"]  # type: ignore[index]
                ),
            )
        else:
            segment_id = int(command["segment_id"])
            value = rpe_values.get(
                (arm, segment_id),
                float(
                    primary["metrics"][arm]["translation_rpe_exact_1s"][  # type: ignore[index]
                        "rmse_m"
                    ]
                ),
            )
        safe_id = str(command["command_id"]).replace(":", "_")
        stdout = (
            "synthetic evo compatibility output\n"
            f"      rmse\t{value:.17g}\n"
        ).encode()
        stderr = b""
        stdout_path = f"/synthetic/evo/{safe_id}.stdout"
        stderr_path = f"/synthetic/evo/{safe_id}.stderr"
        store[stdout_path] = stdout
        store[stderr_path] = stderr
        commands.append(
            {
                "command_id": command["command_id"],
                "argv": copy.deepcopy(command["argv"]),
                "return_code": 0,
                "stdout": payload_identity(stdout_path, stdout),
                "stderr": payload_identity(stderr_path, stderr),
            }
        )
    receipt: dict[str, object] = {
        "schema_version": (
            "aqua-fe-hfnet-v6-positive-roster-evo-adapter-receipt-v1"
        ),
        "plan_core_sha256": plan.document["plan_core_sha256"],
        "generated_tum": copy.deepcopy(plan.document["generated_tum"]),
        "commands": commands,
    }

    def loader(identity: dict[str, object]) -> bytes:
        return store[str(identity["path"])]

    return receipt, loader, store


class FrozenCaseTableTest(unittest.TestCase):
    def test_whole_roster_order_and_four_structural_na_cases(self) -> None:
        self.assertEqual(
            tuple(evaluator.CASE_TABLE),
            (
                "a05_3300_3700",
                "a07_10800_11200",
                "a08_4500_4660",
                "a09_6000_6200",
                "fjord1_s83_d10",
                "mclab1_s60_d15",
                "cirs_s575_d30",
                "cirs_s900_d30",
                "a02_7600_8000",
                "mclab2_s110_d10",
            ),
        )
        structural = {
            name
            for name, policy in evaluator.CASE_TABLE.items()
            if policy.structural_na_reasons
        }
        self.assertEqual(
            structural,
            {
                "a08_4500_4660",
                "a09_6000_6200",
                "fjord1_s83_d10",
                "mclab2_s110_d10",
            },
        )
        self.assertEqual(
            evaluator.FROZEN_AUTHORITY_HASHES[
                "whole_roster_pointer_sha256"
            ],
            "f9b44e9c126e68d151368c84a562aef5f9b06e1200b6f5dd1b6fe55d33430df1",
        )
        self.assertEqual(
            evaluator.FROZEN_AUTHORITY_HASHES[
                "analysis_grid_prefreeze_sha256"
            ],
            "d31b9ee9f22ae47ba6e5b7d5d28f6a528331fd1c7071367ea28aed5032773f8d",
        )
        self.assertEqual(
            evaluator.ANALYSIS_GRID_PREFREEZE_IDENTITY["size_bytes"], 16_833
        )
        self.assertEqual(
            evaluator.EVO_ENVIRONMENT_CONTRACT["implementation_tree"][
                "tree_sha256"
            ],
            "adab14dc969a68572af4c4e1966010df89b3f7dfb50f7dad441221075f410a4d",
        )

    def test_each_grid_is_exact_integer_ns_and_matches_frozen_count(self) -> None:
        for case_id, policy in evaluator.CASE_TABLE.items():
            with self.subTest(case_id=case_id):
                grid = evaluator.make_case_grid_ns(case_id)
                self.assertEqual(grid.dtype, np.dtype(np.int64))
                self.assertEqual(len(grid), policy.expected_grid_count)
                self.assertEqual(int(grid[0]), policy.score_start_header_ns)
                np.testing.assert_array_equal(
                    np.diff(grid), evaluator.GRID_STEP_NS
                )
                self.assertLessEqual(
                    int(grid[-1]), policy.score_last_header_ns
                )
                self.assertGreater(
                    int(grid[-1]) + evaluator.GRID_STEP_NS,
                    policy.score_last_header_ns,
                )

    def test_conditional_aqualoc_cases_disclose_21_native_anchors(self) -> None:
        for case_id in (
            "a05_3300_3700",
            "a07_10800_11200",
            "a02_7600_8000",
        ):
            self.assertEqual(
                evaluator.CASE_TABLE[case_id].native_reference_anchor_count,
                21,
            )


class IntegerTimestampAndInterpolationTest(unittest.TestCase):
    def test_rejects_float_bool_duplicate_and_nonmonotonic_timestamps(self) -> None:
        for values in ([1.0, 2], [True, 2], [1, 1], [2, 1]):
            with self.subTest(values=values), self.assertRaises(
                evaluator.ContractError
            ):
                evaluator.build_resample_plan_ns(
                    values, [1, 2], 10, label="bad"
                )

    def test_hfnet_bridge_is_fixed_256ns_bijective_nonoverridable(self) -> None:
        mapped = evaluator.canonicalize_hfnet_epoch_ns(
            [1_000_000_256, 2_000_000_000],
            [1_000_000_000, 2_000_000_000],
        )
        np.testing.assert_array_equal(
            mapped, [1_000_000_000, 2_000_000_000]
        )
        with self.assertRaisesRegex(evaluator.ContractError, "NOT_UNIQUE"):
            evaluator.canonicalize_hfnet_epoch_ns(
                [1_000_000_257], [1_000_000_000]
            )
        with self.assertRaises(TypeError):
            evaluator.canonicalize_hfnet_epoch_ns(  # type: ignore[call-arg]
                [1], [1], 999
            )
        with self.assertRaisesRegex(evaluator.ContractError, "HEADER_REUSED"):
            evaluator.canonicalize_hfnet_epoch_ns(
                [1_000_000_000, 1_000_000_100],
                [1_000_000_050, 2_000_000_000],
            )
        with self.assertRaisesRegex(evaluator.ContractError, "NOT_UNIQUE"):
            evaluator.canonicalize_hfnet_epoch_ns(
                [1_000_000_200], [1_000_000_000, 1_000_000_400]
            )

    def test_plan_uses_exact_two_sided_linear_shortest_slerp_only(self) -> None:
        plan = evaluator.build_resample_plan_ns(
            [0, 200_000_000],
            [0, 100_000_000, 200_000_000],
            250_000_000,
            label="arm",
        )
        self.assertEqual(
            plan.methods,
            ("EXACT", "INTERPOLATED_LINEAR_SLERP", "EXACT"),
        )
        positions = np.asarray(
            [[0.0, 0.0, 0.0], [2.0, 0.0, 0.0]]
        )
        quaternions = np.asarray(
            [yaw_quaternion(0), yaw_quaternion(180)]
        )
        output_positions, output_quaternions = evaluator._apply_plan_to_poses(
            plan, positions, quaternions
        )
        np.testing.assert_allclose(
            output_positions[:, 0], [0.0, 1.0, 2.0]
        )
        midpoint_rotation = evaluator.quaternion_xyzw_to_rotation(
            output_quaternions[1]
        )
        np.testing.assert_allclose(
            midpoint_rotation @ [1.0, 0.0, 0.0],
            [0.0, 1.0, 0.0],
            atol=1e-12,
        )

    def test_interpolate_then_lever_arm_noncommutative_regression(self) -> None:
        plan = evaluator.build_resample_plan_ns(
            [0, 200_000_000],
            [0, 100_000_000, 200_000_000],
            250_000_000,
            label="rotating_source",
        )
        source_positions = np.zeros((2, 3))
        source_quaternions = np.asarray(
            [yaw_quaternion(0), yaw_quaternion(180)]
        )
        matrix = np.eye(4)
        matrix[0, 3] = 1.0
        transform = evaluator.StaticFrameTransform(
            "source", "target", matrix
        )
        grid_positions, grid_quaternions = evaluator._apply_plan_to_poses(
            plan, source_positions, source_quaternions
        )
        correct, _ = evaluator.transform_world_source_to_target(
            grid_positions,
            grid_quaternions,
            transform,
            label="correct_order",
        )
        endpoint_target, endpoint_quaternions = (
            evaluator.transform_world_source_to_target(
                source_positions,
                source_quaternions,
                transform,
                label="forbidden_order",
            )
        )
        forbidden, _ = evaluator._apply_plan_to_poses(
            plan, endpoint_target, endpoint_quaternions
        )
        np.testing.assert_allclose(
            correct[1], [0.0, 1.0, 0.0], atol=1e-12
        )
        np.testing.assert_allclose(
            forbidden[1], [0.0, 0.0, 0.0], atol=1e-12
        )
        self.assertGreater(
            np.linalg.norm(correct[1] - forbidden[1]), 0.9
        )

    def test_forbids_extrapolation_nearest_and_over_gap(self) -> None:
        plan = evaluator.build_resample_plan_ns(
            [100, 500], [0, 100, 300, 500, 600], 300, label="arm"
        )
        self.assertEqual(
            plan.methods,
            (
                "OUT_OF_RANGE",
                "EXACT",
                "GAP_EXCEEDED",
                "EXACT",
                "OUT_OF_RANGE",
            ),
        )
        np.testing.assert_array_equal(
            plan.valid, [False, True, False, True, False]
        )

    def test_quaternion_order_conversion_lossless_permutation_only(self) -> None:
        tokens = np.asarray([[11, 22, 33, 44]], dtype=np.int64)
        converted = evaluator.convert_quaternion_order_lossless(
            tokens, "wxyz"
        )
        np.testing.assert_array_equal(converted, [[22, 33, 44, 11]])
        self.assertEqual(converted.dtype, tokens.dtype)


class SupportGateTest(unittest.TestCase):
    def test_joint_mask_segments_exact_1s_pairs_never_cross_break(self) -> None:
        timestamps = split_timestamps()
        support = evaluator.build_common_support(
            "a05_3300_3700", timestamps, "PASS"
        )
        self.assertFalse(support.joint_mask[60])
        self.assertFalse(support.joint_mask[61])
        self.assertNotEqual(
            support.segment_ids[59], support.segment_ids[62]
        )
        for left, right in support.rpe_pair_indices:
            self.assertEqual(
                int(support.plans["reference"].grid_ns[right])
                - int(support.plans["reference"].grid_ns[left]),
                evaluator.RPE_DELTA_NS,
            )
            self.assertEqual(
                support.segment_ids[left], support.segment_ids[right]
            )

    def test_runability_failure_receipt_opens_nothing(self) -> None:
        token = failed_runability_lock()
        calls: list[bool] = []

        def forbidden_loader():
            calls.append(True)
            raise AssertionError("coordinate loader must not run")

        result = evaluator.evaluate_case(
            "a05_3300_3700", {}, token, pose_loader=forbidden_loader
        )
        self.assertEqual(
            result["accuracy_status"], "NA_HFNET_RUNABILITY_GATE"
        )
        self.assertEqual(
            result["support"]["phase"], "RUNABILITY_RECEIPT_ONLY"
        )
        self.assertEqual(calls, [])
        self.assertNotIn("metrics", result)
        self.assertFalse(
            result["claim_boundary"]["accuracy_numeric_authorized"]
        )

    def test_low_support_closes_before_pose_loader(self) -> None:
        token = validated_lock()
        timestamps = full_timestamps()
        timestamps["hfnet"] = timestamps["hfnet"][:20]
        calls: list[bool] = []
        result = evaluator.evaluate_case(
            "a05_3300_3700",
            locked_timestamps(token, timestamps),
            token,
            pose_loader=lambda: calls.append(True),  # type: ignore[arg-type,return-value]
        )
        self.assertEqual(result["accuracy_status"], "NA_SUPPORT_GATE")
        self.assertEqual(calls, [])
        self.assertNotIn("metrics", result)
        self.assertIn("joint_mask", result["support"])
        self.assertFalse(result["support"]["coordinates_loaded"])

    def test_four_structural_na_no_metrics_or_coordinate_access(self) -> None:
        for case_id in (
            "a08_4500_4660",
            "a09_6000_6200",
            "fjord1_s83_d10",
            "mclab2_s110_d10",
        ):
            token = validated_lock(case_id)
            with self.subTest(case_id=case_id):
                result = evaluator.evaluate_case(
                    case_id,
                    {},
                    token,
                    pose_loader=lambda: (_ for _ in ()).throw(
                        AssertionError("structural NA opened coordinates")
                    ),
                )
                self.assertEqual(
                    result["accuracy_status"],
                    "STRUCTURAL_NA_PREFROZEN_UPPER_BOUND",
                )
                self.assertNotIn("metrics", result)
                self.assertNotIn("alignment_audit", result)
                self.assertFalse(result["support"]["coordinates_loaded"])
                self.assertFalse(result["support"]["metrics_computed"])

    def test_metric_entry_rejects_raw_or_mismatched_lock(self) -> None:
        with self.assertRaisesRegex(
            evaluator.ContractError, "VALIDATED_EXECUTION_LOCK_REQUIRED"
        ):
            evaluator.evaluate_case(  # type: ignore[arg-type]
                "a05_3300_3700", {}, valid_future_lock()
            )
        token = validated_lock("a05_3300_3700")
        with self.assertRaisesRegex(
            evaluator.ContractError, "EXECUTION_LOCK_CASE_MISMATCH"
        ):
            evaluator.evaluate_case("a07_10800_11200", {}, token)

    def test_timestamp_identity_must_match_validated_lock(self) -> None:
        token = validated_lock()
        timestamps = locked_timestamps(token)
        timestamps["hfnet"] = evaluator.LockedTimestampSeriesNs(
            stamps_ns=timestamps["hfnet"].stamps_ns,
            trajectory_identity=fake_identity(
                "/future/wrong_hfnet.tum"
            ),
        )
        with self.assertRaisesRegex(
            evaluator.ContractError, "TIMESTAMP_TRAJECTORY_IDENTITY"
        ):
            evaluator.evaluate_case(
                "a05_3300_3700", timestamps, token
            )


class CoordinateAndSE3Test(unittest.TestCase):
    def test_open_gate_loads_once_primary_unauthorized_until_evo(self) -> None:
        token = validated_lock()
        timestamps = full_timestamps()
        poses = pose_mapping(
            timestamps, token, varying_orientation=True
        )
        calls: list[bool] = []

        def loader():
            calls.append(True)
            return poses

        result = evaluator.evaluate_case(
            "a05_3300_3700",
            locked_timestamps(token, timestamps),
            token,
            pose_loader=loader,
        )
        self.assertEqual(calls, [True])
        self.assertEqual(
            result["accuracy_status"],
            "PRIMARY_METRICS_COMPUTED_EVO_PENDING",
        )
        self.assertFalse(
            result["claim_boundary"]["accuracy_numeric_authorized"]
        )
        for arm in evaluator.ESTIMATE_ORDER:
            self.assertLess(
                result["metrics"][arm]["translation_ape"]["rmse_m"],
                1e-10,
            )
            self.assertLess(
                result["metrics"][arm]["translation_rpe_exact_1s"][
                    "rmse_m"
                ],
                1e-10,
            )
            audit = result["alignment_audit"]["per_arm"][arm]
            self.assertEqual(audit["scale"], 1.0)
            self.assertFalse(audit["scale_estimated"])
            self.assertFalse(audit["sim3_used"])
            self.assertGreater(audit["rotation_determinant"], 0.0)

    def test_fixed_scale_se3_does_not_hide_scaled_hfnet(self) -> None:
        token = validated_lock()
        timestamps = full_timestamps()
        result = evaluator.evaluate_case(
            "a05_3300_3700",
            locked_timestamps(token, timestamps),
            token,
            pose_loader=lambda: pose_mapping(
                timestamps, token, scaled_hfnet=True
            ),
        )
        self.assertGreater(
            result["metrics"]["hfnet"]["translation_ape"]["rmse_m"],
            1.0,
        )
        self.assertEqual(
            result["alignment_audit"]["per_arm"]["hfnet"]["scale"],
            1.0,
        )

    def test_rank_deficiency_closes_and_suppresses_metrics(self) -> None:
        token = validated_lock()
        timestamps = full_timestamps()
        result = evaluator.evaluate_case(
            "a05_3300_3700",
            locked_timestamps(token, timestamps),
            token,
            pose_loader=lambda: pose_mapping(
                timestamps, token, collinear=True
            ),
        )
        self.assertEqual(result["accuracy_status"], "NA_ALIGNMENT_GATE")
        self.assertNotIn("metrics", result)
        self.assertFalse(
            result["claim_boundary"]["accuracy_numeric_authorized"]
        )

    def test_pose_timestamp_and_identity_toctou_rejected(self) -> None:
        token = validated_lock()
        timestamps = full_timestamps()
        poses = pose_mapping(timestamps, token)
        hfnet = poses["hfnet"]
        poses["hfnet"] = evaluator.PoseSeriesNs(
            stamps_ns=np.asarray(hfnet.stamps_ns) + 1,
            positions=hfnet.positions,
            quaternions_xyzw=hfnet.quaternions_xyzw,
            trajectory_identity=hfnet.trajectory_identity,
        )
        with self.assertRaisesRegex(
            evaluator.ContractError, "POSE_TIMESTAMP_TOCTOU"
        ):
            evaluator.evaluate_case(
                "a05_3300_3700",
                locked_timestamps(token, timestamps),
                token,
                pose_loader=lambda: poses,
            )
        poses = pose_mapping(timestamps, token)
        poses["hfnet"] = evaluator.PoseSeriesNs(
            stamps_ns=poses["hfnet"].stamps_ns,
            positions=poses["hfnet"].positions,
            quaternions_xyzw=poses["hfnet"].quaternions_xyzw,
            trajectory_identity=fake_identity(
                "/future/wrong_pose.tum"
            ),
        )
        with self.assertRaisesRegex(
            evaluator.ContractError, "POSE_TRAJECTORY_IDENTITY"
        ):
            evaluator.evaluate_case(
                "a05_3300_3700",
                locked_timestamps(token, timestamps),
                token,
                pose_loader=lambda: poses,
            )

    def test_world_source_target_composition_uses_orientation(self) -> None:
        matrix = np.eye(4)
        matrix[0, 3] = 2.0
        positions, quaternions = (
            evaluator.transform_world_source_to_target(
                np.asarray(
                    [[1.0, 2.0, 3.0], [1.0, 2.0, 3.0]]
                ),
                np.asarray(
                    [yaw_quaternion(0), yaw_quaternion(90)]
                ),
                evaluator.StaticFrameTransform(
                    "source", "target", matrix
                ),
                label="composition",
            )
        )
        np.testing.assert_allclose(
            positions[0], [3.0, 2.0, 3.0], atol=1e-12
        )
        np.testing.assert_allclose(
            positions[1], [1.0, 4.0, 3.0], atol=1e-12
        )
        self.assertEqual(quaternions.shape, (2, 4))

    def test_standard_full_pose_rpe_not_global_delta_vector(self) -> None:
        reference_positions = np.asarray(
            [[0.0, 0.0, 0.0], [1.0, 0.0, 0.0]]
        )
        estimate_positions = reference_positions.copy()
        reference_quaternions = np.asarray(
            [yaw_quaternion(90), yaw_quaternion(90)]
        )
        estimate_quaternions = np.asarray(
            [yaw_quaternion(0), yaw_quaternion(0)]
        )
        errors = evaluator.full_pose_se3_relative_translation_errors(
            reference_positions,
            reference_quaternions,
            estimate_positions,
            estimate_quaternions,
            np.asarray([[0, 1]], dtype=np.int64),
        )
        old_global_delta_error = np.linalg.norm(
            (estimate_positions[1] - estimate_positions[0])
            - (reference_positions[1] - reference_positions[0])
        )
        self.assertEqual(old_global_delta_error, 0.0)
        np.testing.assert_allclose(
            errors, [math.sqrt(2.0)], atol=1e-12
        )

    def test_controller_interface_one_load_no_write_plan(self) -> None:
        token = validated_lock()
        timestamps = full_timestamps()
        calls: list[bool] = []
        with tempfile.TemporaryDirectory() as directory:
            output_root = Path(directory) / "not-created"

            def loader():
                calls.append(True)
                return pose_mapping(
                    timestamps, token, varying_orientation=True
                )

            result, plan = evaluator.evaluate_case_for_controller(
                "a05_3300_3700",
                locked_timestamps(token, timestamps),
                token,
                output_root,
                pose_loader=loader,
            )
            self.assertEqual(calls, [True])
            self.assertIsNotNone(plan)
            self.assertFalse(output_root.exists())
            self.assertEqual(
                result["independent_evo_pending"]["plan_core_sha256"],
                plan.document["plan_core_sha256"],  # type: ignore[union-attr]
            )

    def test_ntnu_and_cirs_use_their_dataset_specific_common_frames(self) -> None:
        for case_id in ("mclab1_s60_d15", "cirs_s575_d30"):
            token = validated_lock(case_id)
            timestamps = full_timestamps(case_id)
            with self.subTest(case_id=case_id):
                result = evaluator.evaluate_case(
                    case_id,
                    locked_timestamps(token, timestamps),
                    token,
                    pose_loader=lambda: pose_mapping(
                        timestamps, token, varying_orientation=True
                    ),
                )
                self.assertEqual(
                    result["accuracy_status"],
                    "PRIMARY_METRICS_COMPUTED_EVO_PENDING",
                )
                for arm in evaluator.ESTIMATE_ORDER:
                    self.assertLess(
                        result["metrics"][arm]["translation_ape"][
                            "rmse_m"
                        ],
                        1e-10,
                    )
                    np.testing.assert_allclose(
                        result["frame_transform_audit"][arm][
                            "source_T_target"
                        ],
                        token.transforms[arm].source_T_target,
                        rtol=0.0,
                        atol=1e-15,
                    )

    def test_runtime_transform_cannot_be_caller_supplied(self) -> None:
        token = validated_lock()
        with self.assertRaises(TypeError):
            evaluator.evaluate_case(
                "a05_3300_3700",
                locked_timestamps(token),
                token,
                transforms={},  # type: ignore[call-arg]
            )

    def test_reflection_static_transform_forbidden(self) -> None:
        reflection = np.eye(4)
        reflection[0, 0] = -1.0
        with self.assertRaisesRegex(
            evaluator.ContractError, "NOT_PROPER_ROTATION"
        ):
            evaluator.validate_static_transform(
                evaluator.StaticFrameTransform(
                    "source", "target", reflection
                ),
                "reflection",
            )


class EvoAdapterTest(unittest.TestCase):
    def test_population_ordered_integer_ns_digests(self) -> None:
        support = evaluator.build_common_support(
            "a05_3300_3700", full_timestamps(), "PASS"
        )
        contract = evaluator.evo_population_contract(support)
        self.assertEqual(contract["common_pose_count"], 200)
        self.assertEqual(contract["exact_1s_pair_count"], 190)
        self.assertEqual(
            len(contract["ordered_common_pose_ns_sha256"]), 64
        )
        self.assertEqual(
            len(contract["ordered_exact_1s_pair_ns_sha256"]), 64
        )

    def test_exact_argv_segments_real_full_pose_orientations(self) -> None:
        _primary, plan = controller_evaluation(split=True)
        commands = plan.document["commands"]
        ape = next(
            command for command in commands if command["kind"] == "APE"
        )
        self.assertEqual(
            ape["argv"][4:],
            [
                "-a",
                "-r",
                "trans_part",
                "--t_max_diff",
                "1e-9",
                "--t_offset",
                "0",
            ],
        )
        self.assertNotIn("-s", ape["argv"])
        rpe = next(
            command for command in commands if command["kind"] == "RPE"
        )
        self.assertEqual(
            rpe["argv"][4:],
            [
                "-r",
                "trans_part",
                "-d",
                "10",
                "-u",
                "f",
                "--all_pairs",
                "--pairs_from_reference",
                "--t_max_diff",
                "1e-9",
                "--t_offset",
                "0",
            ],
        )
        self.assertNotIn("-a", rpe["argv"])
        self.assertNotIn("-s", rpe["argv"])
        populations = plan.document["segment_population"]
        self.assertEqual(len(populations), 2)
        self.assertEqual(
            sum(item["pair_count"] for item in populations),
            plan.document["population"]["exact_1s_pair_count"],
        )
        for item in populations:
            self.assertEqual(
                len(item["grid_indices"]), item["pose_count"]
            )
            self.assertEqual(
                len(item["ordered_pose_ns"]), item["pose_count"]
            )
            self.assertEqual(
                len(item["ordered_pair_grid_indices"]),
                item["pair_count"],
            )
        reference_path = next(
            path
            for path in plan.generated_tum_payloads
            if path.endswith("reference_common.tum")
        )
        lines = plan.generated_tum_payloads[
            reference_path
        ].decode().splitlines()
        quaternion = np.asarray(
            [float(value) for value in lines[5].split()[4:8]]
        )
        self.assertGreater(abs(quaternion[2]), 1e-3)
        self.assertAlmostEqual(
            float(np.linalg.norm(quaternion)), 1.0, places=12
        )

    def test_synthetic_receipt_required_before_authorization(self) -> None:
        primary, plan = controller_evaluation()
        self.assertFalse(
            primary["claim_boundary"]["accuracy_numeric_authorized"]
        )
        receipt, loader, _store = synthetic_evo_receipt(primary, plan)
        crosscheck = evaluator.validate_evo_adapter_receipt(
            plan, primary, receipt, loader  # type: ignore[arg-type]
        )
        self.assertEqual(crosscheck["status"], "PASS")
        finalized = evaluator.finalize_primary_with_evo(
            primary, crosscheck
        )
        self.assertEqual(
            finalized["accuracy_status"],
            "ACCURACY_AUTHORIZED_EVO_PASS",
        )
        self.assertTrue(
            finalized["claim_boundary"]["accuracy_numeric_authorized"]
        )

    def test_segment_rmse_weighted_by_parsed_pair_counts(self) -> None:
        primary, plan = controller_evaluation(split=True)
        populations = plan.document["segment_population"]
        first, second = populations
        expected = math.sqrt(
            (
                first["pair_count"] * 1.0**2
                + second["pair_count"] * 3.0**2
            )
            / (first["pair_count"] + second["pair_count"])
        )
        primary_for_weighting = copy.deepcopy(primary)
        rpe_values: dict[tuple[str, int], float] = {}
        for arm in evaluator.ESTIMATE_ORDER:
            primary_for_weighting["metrics"][arm][  # type: ignore[index]
                "translation_rpe_exact_1s"
            ]["rmse_m"] = expected
            rpe_values[(arm, int(first["segment_id"]))] = 1.0
            rpe_values[(arm, int(second["segment_id"]))] = 3.0
        receipt, loader, _store = synthetic_evo_receipt(
            primary_for_weighting,
            plan,
            rpe_values=rpe_values,
        )
        crosscheck = evaluator.validate_evo_adapter_receipt(
            plan,
            primary_for_weighting,
            receipt,
            loader,  # type: ignore[arg-type]
        )
        self.assertEqual(crosscheck["status"], "PASS")
        for arm in evaluator.ESTIMATE_ORDER:
            observed = crosscheck["per_arm"][arm]
            self.assertAlmostEqual(
                observed["evo_weighted_segment_rpe_rmse_m"], expected
            )
            self.assertEqual(
                observed["rpe_pair_count"],
                plan.document["population"]["exact_1s_pair_count"],
            )
            self.assertTrue(
                all(
                    segment["pair_count_source"].startswith(
                        "PARSED_GENERATED_TUM"
                    )
                    for segment in observed["segments"]
                )
            )

    def test_rejects_caller_scalars_argv_artifact_drift(self) -> None:
        primary, plan = controller_evaluation()
        receipt, loader, store = synthetic_evo_receipt(primary, plan)
        with_scalar = copy.deepcopy(receipt)
        with_scalar["metrics"] = {"hfnet": 0.0}
        with self.assertRaisesRegex(
            evaluator.ContractError, "EVO_RECEIPT_KEYS"
        ):
            evaluator.validate_evo_adapter_receipt(
                plan,
                primary,
                with_scalar,
                loader,  # type: ignore[arg-type]
            )
        argv_drift = copy.deepcopy(receipt)
        argv_drift["commands"][0]["argv"].append("-s")  # type: ignore[index,union-attr]
        with self.assertRaisesRegex(evaluator.ContractError, "EVO_ARGV"):
            evaluator.validate_evo_adapter_receipt(
                plan,
                primary,
                argv_drift,
                loader,  # type: ignore[arg-type]
            )
        boolean_return = copy.deepcopy(receipt)
        boolean_return["commands"][0]["return_code"] = False  # type: ignore[index]
        with self.assertRaisesRegex(
            evaluator.ContractError, "EVO_RETURN_CODE"
        ):
            evaluator.validate_evo_adapter_receipt(
                plan,
                primary,
                boolean_return,
                loader,  # type: ignore[arg-type]
            )
        negative_receipt, negative_loader, _negative_store = (
            synthetic_evo_receipt(
                primary, plan, ape_values={"hfnet": -1.0}
            )
        )
        with self.assertRaisesRegex(
            evaluator.ContractError, "EVO_RMSE_COUNT"
        ):
            evaluator.validate_evo_adapter_receipt(
                plan,
                primary,
                negative_receipt,
                negative_loader,  # type: ignore[arg-type]
            )
        first_stdout = receipt["commands"][0]["stdout"]  # type: ignore[index]
        store[str(first_stdout["path"])] += b"drift"  # type: ignore[index]
        with self.assertRaisesRegex(
            evaluator.ContractError, "EVO_ARTIFACT_SIZE"
        ):
            evaluator.validate_evo_adapter_receipt(
                plan,
                primary,
                receipt,
                loader,  # type: ignore[arg-type]
            )

    def test_disagreement_over_1e5_closes_without_ranking(self) -> None:
        primary, plan = controller_evaluation()
        baseline = float(
            primary["metrics"]["hfnet"]["translation_ape"]["rmse_m"]
        )
        receipt, loader, _store = synthetic_evo_receipt(
            primary,
            plan,
            ape_values={"hfnet": baseline + 2e-5},
        )
        crosscheck = evaluator.validate_evo_adapter_receipt(
            plan, primary, receipt, loader  # type: ignore[arg-type]
        )
        self.assertEqual(crosscheck["status"], "CLOSED_NO_RANKING")
        self.assertFalse(crosscheck["accuracy_numeric_authorized"])
        finalized = evaluator.finalize_primary_with_evo(
            primary, crosscheck
        )
        self.assertEqual(
            finalized["accuracy_status"], "CLOSED_NO_RANKING"
        )
        self.assertFalse(
            finalized["claim_boundary"]["ranking_authorized"]
        )

    def test_finalize_rejects_forged_inconsistent_crosscheck(self) -> None:
        primary, plan = controller_evaluation()
        receipt, loader, _store = synthetic_evo_receipt(primary, plan)
        forged = evaluator.validate_evo_adapter_receipt(
            plan, primary, receipt, loader  # type: ignore[arg-type]
        )
        forged["failures"] = ["still failed"]
        with self.assertRaisesRegex(
            evaluator.ContractError, "AUTHORIZATION_INCONSISTENT"
        ):
            evaluator.finalize_primary_with_evo(primary, forged)

    def test_native_sensitivity_cannot_reopen_closed_primary(self) -> None:
        token = failed_runability_lock()
        closed = evaluator.evaluate_case(
            "a05_3300_3700", {}, token
        )
        preflight = evaluator.native_anchor_sensitivity_preflight(
            "a05_3300_3700", closed
        )
        self.assertFalse(preflight["authorized"])
        self.assertFalse(preflight["metrics_computed"])
        self.assertFalse(preflight["can_reopen_closed_primary_gate"])
        opened, _plan = controller_evaluation()
        ready = evaluator.native_anchor_sensitivity_preflight(
            "a05_3300_3700", opened
        )
        self.assertTrue(ready["authorized"])
        self.assertEqual(ready["native_reference_anchor_count"], 21)


class ExecutionLockAndPreflightTest(unittest.TestCase):
    def test_conditional_cases_validate_to_matching_tokens(self) -> None:
        for case_id in (
            "a05_3300_3700",
            "a07_10800_11200",
            "mclab1_s60_d15",
            "cirs_s575_d30",
            "cirs_s900_d30",
            "a02_7600_8000",
        ):
            with self.subTest(case_id=case_id):
                lock = valid_future_lock(case_id)
                token = evaluator.validate_future_execution_lock(
                    lock, formal_verification(lock)
                )
                self.assertIsInstance(
                    token, evaluator.ValidatedExecutionLock
                )
                self.assertEqual(token.case_id, case_id)
                self.assertEqual(token.runability_status, "PASS")
                self.assertEqual(
                    set(token.transforms), set(evaluator.SOURCE_ORDER)
                )

    def test_formal_verification_mandatory_complete_lock_bound(self) -> None:
        lock = valid_future_lock()
        with self.assertRaisesRegex(
            evaluator.ContractError,
            "FORMAL_IDENTITY_VERIFICATION_REQUIRED",
        ):
            evaluator.validate_future_execution_lock(lock)
        with self.assertRaisesRegex(
            evaluator.ContractError,
            "FORMAL_IDENTITY_VERIFICATION_INCOMPLETE",
        ):
            evaluator.validate_future_execution_lock(
                lock,
                formal_verification(
                    lock, evaluator_self_identity_verified=False
                ),
            )
        verification = formal_verification(lock)
        lock["claims"]["analysis_started"] = True  # type: ignore[index]
        with self.assertRaisesRegex(
            evaluator.ContractError, "LOCK_VALUE_MISMATCH"
        ):
            evaluator.validate_future_execution_lock(
                lock, verification
            )

    def test_v1_authority_is_retired_and_rejected(self) -> None:
        lock = valid_future_lock()
        lock["authority_hashes"]["whole_roster_pointer_sha256"] = (  # type: ignore[index]
            "bcbcd0b7444f6292b0b09d802d1f806dd38fd2fb6a70cc97665bf035b37cf722"
        )
        with self.assertRaisesRegex(evaluator.ContractError, "LOCK_AUTHORITIES"):
            evaluator.validate_future_execution_lock(
                lock, formal_verification(lock)
            )
        lock = valid_future_lock()
        lock["v2_roster_authorities"]["prepared_runner"]["path"] = (  # type: ignore[index]
            "/home/ma/AQUA-FE_WS/scripts/"
            "run_hfnet_v6_samehistory_positive_roster_v1.py"
        )
        with self.assertRaisesRegex(
            evaluator.ContractError, "LOCK_V2_ROSTER_AUTHORITY_IDENTITIES"
        ):
            evaluator.validate_future_execution_lock(
                lock, formal_verification(lock)
            )

    def test_runability_derived_only_from_receipt(self) -> None:
        token = failed_runability_lock()
        self.assertEqual(token.runability_status, "FAIL")
        self.assertEqual(token.trajectory_identities, {})
        result = evaluator.evaluate_case(
            "a05_3300_3700", {}, token
        )
        self.assertEqual(
            result["support"]["hfnet_runability_status"], "FAIL"
        )

    def test_rejects_aqualoc_inverse_and_out_of_tolerance(self) -> None:
        inverse_lock = valid_future_lock()
        inverse = np.asarray(
            evaluator.AQUALOC_CAMERA_T_IMU, dtype=float
        )
        inverse_lock["frame_contract"]["imu_T_camera"] = (  # type: ignore[index]
            matrix_binding(inverse)
        )
        for name in evaluator.ESTIMATE_ORDER:
            inverse_lock["sources"][name]["pose_convention"][  # type: ignore[index]
                "static_transform"
            ]["source_T_target"] = inverse.tolist()
        with self.assertRaisesRegex(
            evaluator.ContractError, "AQUALOC_FROZEN_TRANSFORM_VALUE"
        ):
            evaluator.validate_future_execution_lock(
                inverse_lock, formal_verification(inverse_lock)
            )

        drift_lock = valid_future_lock()
        drift = np.asarray(
            evaluator.AQUALOC_IMU_T_CAMERA, dtype=float
        )
        drift[0, 3] += 2e-12
        drift_lock["frame_contract"]["imu_T_camera"] = (  # type: ignore[index]
            matrix_binding(drift)
        )
        for name in evaluator.ESTIMATE_ORDER:
            drift_lock["sources"][name]["pose_convention"][  # type: ignore[index]
                "static_transform"
            ]["source_T_target"] = drift.tolist()
        with self.assertRaisesRegex(
            evaluator.ContractError, "AQUALOC_FROZEN_TRANSFORM_VALUE"
        ):
            evaluator.validate_future_execution_lock(
                drift_lock, formal_verification(drift_lock)
            )

    def test_rejects_ntnu_camera_bridge_cirs_camera_confusion(self) -> None:
        ntnu = valid_future_lock("mclab1_s60_d15")
        ntnu["sources"]["hfnet"]["pose_convention"][  # type: ignore[index]
            "static_transform"
        ]["source_T_target"][0][3] = 0.1
        with self.assertRaisesRegex(
            evaluator.ContractError, "STATIC_TRANSFORM_VALUE:hfnet"
        ):
            evaluator.validate_future_execution_lock(
                ntnu, formal_verification(ntnu)
            )

        cirs = valid_future_lock("cirs_s575_d30")
        cirs["frame_contract"][  # type: ignore[index]
            "historical_online_camera_extrinsic_ignored_for_body_bridge"
        ] = False
        with self.assertRaisesRegex(
            evaluator.ContractError, "CIRS_BODY_FRAME_ADJUDICATION"
        ):
            evaluator.validate_future_execution_lock(
                cirs, formal_verification(cirs)
            )

        cirs_drift = valid_future_lock("cirs_s575_d30")
        drift = np.asarray(
            evaluator.CIRS_IMU_T_VEHICLE, dtype=float
        )
        drift[0, 3] += 2e-15
        cirs_drift["frame_contract"]["imu_T_vehicle"] = (  # type: ignore[index]
            matrix_binding(drift)
        )
        for name in evaluator.ESTIMATE_ORDER:
            cirs_drift["sources"][name]["pose_convention"][  # type: ignore[index]
                "static_transform"
            ]["source_T_target"] = drift.tolist()
        with self.assertRaisesRegex(
            evaluator.ContractError, "CIRS_FROZEN_TRANSFORM_VALUE"
        ):
            evaluator.validate_future_execution_lock(
                cirs_drift, formal_verification(cirs_drift)
            )

    def test_pins_quaternion_order_evo_no_sim3(self) -> None:
        lock = valid_future_lock()
        lock["sources"]["klt"]["pose_convention"][  # type: ignore[index]
            "serialized_quaternion_order"
        ] = "xyzw"
        with self.assertRaisesRegex(
            evaluator.ContractError, "LOCK_QUATERNION_ORDER:klt"
        ):
            evaluator.validate_future_execution_lock(
                lock, formal_verification(lock)
            )
        lock = valid_future_lock()
        lock["evo_verification"]["use_scale"] = True  # type: ignore[index]
        with self.assertRaisesRegex(
            evaluator.ContractError, "SIM3_FORBIDDEN"
        ):
            evaluator.validate_future_execution_lock(
                lock, formal_verification(lock)
            )

    def test_dry_run_read_only_symlink_safe_canonical_distinct(self) -> None:
        token = validated_lock()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "output"
            claim = root / "claim.json"
            terminal = root / "terminal.json"
            result = evaluator.dry_run_preflight(
                "a05_3300_3700", token, output, claim, terminal
            )
            self.assertEqual(result["status"], "DRY_RUN_READY")
            self.assertFalse(output.exists())
            self.assertFalse(claim.exists())
            self.assertFalse(terminal.exists())
            self.assertFalse(result["claim_created"])
            output.symlink_to(root / "missing-target")
            with self.assertRaisesRegex(
                evaluator.ContractError, "DESTINATION_EXISTS:output"
            ):
                evaluator.dry_run_preflight(
                    "a05_3300_3700",
                    token,
                    output,
                    claim,
                    terminal,
                )
            output.unlink()
            alias = root / "nested" / ".." / "same"
            same = root / "same"
            with self.assertRaisesRegex(
                evaluator.ContractError,
                "DESTINATIONS_NOT_DISTINCT",
            ):
                evaluator.dry_run_preflight(
                    "a05_3300_3700",
                    token,
                    alias,
                    same,
                    terminal,
                )

    def test_cli_describe_dry_run_only_no_accuracy_run(self) -> None:
        script = str(
            ROOT
            / "scripts/"
            "evaluate_hfnet_v6_samehistory_positive_roster_common_support_v1.py"
        )
        completed = subprocess.run(
            [
                sys.executable,
                script,
                "describe",
                "--case-id",
                "a05_3300_3700",
            ],
            check=False,
            capture_output=True,
        )
        self.assertEqual(
            completed.returncode, 0, completed.stderr.decode()
        )
        document = json.loads(completed.stdout)
        self.assertFalse(document["real_accuracy_execution_available"])
        self.assertEqual(
            completed.stdout, evaluator.canonical_json_bytes(document)
        )
        forbidden = subprocess.run(
            [sys.executable, script, "run"],
            check=False,
            capture_output=True,
        )
        self.assertNotEqual(forbidden.returncode, 0)

    def test_only_pinned_pure_helper_imported(self) -> None:
        source = (
            ROOT
            / "scripts/"
            "evaluate_hfnet_v6_samehistory_positive_roster_common_support_v1.py"
        ).read_text()
        self.assertIn("trajectory_eval_core import", source)
        self.assertNotIn("evaluate_vins_common_support import", source)
        self.assertNotIn(
            "evaluate_vins_common_support_epoch_v2 import", source
        )


if __name__ == "__main__":
    unittest.main()
