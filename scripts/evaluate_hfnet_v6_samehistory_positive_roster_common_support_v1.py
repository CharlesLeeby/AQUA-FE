#!/usr/bin/env python3
"""Outcome-blind common-support core for the HFNet-v6 positive roster.

This module deliberately separates timestamp support from pose coordinates.
The support gate is evaluated from integer-nanosecond timestamps first.  Pose
coordinates are obtained from ``pose_loader`` only when that gate is open.

The command-line interface is preflight-only.  It cannot start an accuracy
analysis, reserve a claim, or publish a result.  A later, separately frozen
controller can bind this pure core to runability receipts, trajectories,
static frame transforms, evo executables, and FUSE-safe exactly-once output.

Quaternion order is TUM ``[qx, qy, qz, qw]``.  A serialized pose is
``world_T_source`` and each explicit static transform is ``source_T_target``;
their product is the pose ``world_T_target`` used for common-frame analysis.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import json
import math
import os
from pathlib import Path
import sys
from types import MappingProxyType
from typing import Any, Callable, Mapping, Sequence, Tuple

import numpy as np

try:  # Package import in tests; direct import when run as a script.
    from .trajectory_eval_core import (
        quaternion_xyzw_to_rotation,
        rotation_to_quaternion_xyzw,
        slerp_xyzw,
    )
except ImportError:  # pragma: no cover - exercised by the CLI subprocess.
    from trajectory_eval_core import (  # type: ignore
        quaternion_xyzw_to_rotation,
        rotation_to_quaternion_xyzw,
        slerp_xyzw,
    )


SCHEMA_VERSION = "aqua-fe-hfnet-v6-samehistory-positive-roster-common-support-core-v1"
ANALYSIS_LOCK_SCHEMA = (
    "aqua-fe-hfnet-v6-samehistory-positive-roster-accuracy-execution-lock-v1"
)
GRID_STEP_NS = 100_000_000
RPE_DELTA_NS = 1_000_000_000
GRID_RATE_HZ = 10
MIN_COMMON_POSES = 30
MIN_COMMON_SPAN_NS = 10_000_000_000
MIN_COMMON_COVERAGE = 0.70
MIN_RPE_PAIRS = 10
HFNET_CANONICALIZATION_MAX_DELTA_NS = 256
EVO_MAX_RMSE_DISAGREEMENT_M = 1e-5
EVO_VERSION = "v1.31.1"
EVO_APE_IDENTITY = MappingProxyType(
    {
        "path": "/home/ma/.local/bin/evo_ape",
        "size_bytes": 213,
        "sha256": "6bee25dc5bfdab0ead8988ab4014a72511339e94697ec61699f66f68f5f24d15",
    }
)
EVO_RPE_IDENTITY = MappingProxyType(
    {
        "path": "/home/ma/.local/bin/evo_rpe",
        "size_bytes": 213,
        "sha256": "9e07d0bd4566aa680d5e39e58589176a286f4f8a22ba9107a5834ddb278e2bd1",
    }
)
ANALYSIS_GRID_PREFREEZE_IDENTITY = MappingProxyType(
    {
        "path": (
            "/home/ma/AQUA-FE_WS/papers/"
            "hfnet_v6_samehistory_positive_accuracy_analysis_grid_prefreeze_v1.md"
        ),
        "size_bytes": 16_833,
        "sha256": "d31b9ee9f22ae47ba6e5b7d5d28f6a528331fd1c7071367ea28aed5032773f8d",
    }
)
PURE_HELPER_IDENTITY = MappingProxyType(
    {
        "path": "/home/ma/AQUA-FE_WS/scripts/trajectory_eval_core.py",
        "size_bytes": 27_945,
        "sha256": "aa9ac4da81df7298d1f1c369548ca98a57235916004337cad66f4cf331560635",
    }
)
EVO_ENVIRONMENT_CONTRACT = MappingProxyType(
    {
        "python": {
            "path": "/usr/bin/python3.8",
            "size_bytes": 5_490_456,
            "sha256": "298a9e830ed52f36c299427565485d717d1ce0179c0597cc16560513eb780b06",
        },
        "site_packages_root": "/home/ma/.local/lib/python3.8/site-packages",
        "implementation_tree": {
            "included_roots": ["evo", "evo-1.31.1.dist-info"],
            "include_only_regular_nonsymlink_files": True,
            "excluded_path_component": "__pycache__",
            "sort_key": "site_relative_posix_path",
            "record_encoding": "relative_path+NUL+decimal_size+NUL+file_sha256_hex+LF",
            "file_count": 45,
            "total_size_bytes": 473_395,
            "tree_sha256": "adab14dc969a68572af4c4e1966010df89b3f7dfb50f7dad441221075f410a4d",
        },
        "evo_record_sha256": "a720ae5d78b1cf5d0c5b3ed81b8deb2adc41cb686ccffd773a42a1553823cbde",
        "numpy": {
            "version": "1.24.4",
            "record_sha256": "6c7ce7bb7cd520b75be0d504637fe57020dd50aef3503d9941b2cbc20473676a",
        },
        "scipy": {
            "version": "1.10.1",
            "record_sha256": "ff024ed0ab4a9407c96c290ad8db1453153fa4cdddcdb99e6a637a2c6916d004",
        },
    }
)

SOURCE_ORDER = ("reference", "hfnet", "learned_plus_klt", "klt")
ESTIMATE_ORDER = SOURCE_ORDER[1:]

# Semantic frame names are analysis-contract names, not mutable ROS frame_id
# spellings.  The later frame seal binds each spelling and static matrix.
DATASET_FRAME_CONTRACTS: Mapping[str, Mapping[str, str]] = MappingProxyType(
    {
        "AQUALOC_ARCHAEOLOGY": MappingProxyType(
            {
                "common_target_frame": "aqualoc_camera",
                "reference_source_frame": "aqualoc_camera",
                "estimate_source_frame": "imu_body",
                "reference_transform": "IDENTITY",
                "estimate_transform": "IMU_T_CAMERA",
            }
        ),
        "NTNU": MappingProxyType(
            {
                "common_target_frame": "ntnu_imu_body",
                "reference_source_frame": "ntnu_imu_body",
                "estimate_source_frame": "ntnu_imu_body",
                "reference_transform": "IDENTITY",
                "estimate_transform": "IDENTITY_NO_BODY_T_CAMERA",
            }
        ),
        "CIRS": MappingProxyType(
            {
                "common_target_frame": "cirs_published_vehicle_body",
                "reference_source_frame": "cirs_published_vehicle_body",
                "estimate_source_frame": "mti_imu",
                "reference_transform": "IDENTITY",
                "estimate_transform": "IMU_T_VEHICLE_EQUALS_INVERSE_VEHICLE_T_IMU",
            }
        ),
    }
)
AQUALOC_IMU_T_CAMERA = (
    (-0.999372214240385, -0.034374888513960, -0.008575805730306, -0.019289625059918),
    (0.009015607185122, -0.012659747009765, -0.999879217522163, -0.175142540090067),
    (0.034262169098800, -0.999328823683828, 0.012961709892746, -0.026795196070038),
    (0.0, 0.0, 0.0, 1.0),
)
AQUALOC_CAMERA_T_IMU = (
    (-0.9993722142403839, 0.009015607185121647, 0.034262169098799616, -0.016780437426353788),
    (-0.03437488851396028, -0.012659747009765032, -0.9993288236838265, -0.029657550728147596),
    (-0.008575805730306488, -0.999879217522162, 0.012961709892746132, -0.17493949845924564),
    (0.0, 0.0, 0.0, 1.0),
)
AQUALOC_FRAME_MATRIX_ATOL = 1e-12
AQUALOC_CALIBRATION_IDENTITY = MappingProxyType(
    {
        "path": (
            "/mnt/data/AQUA-FE_WS/datasets/full_downloads/aqualoc/"
            "Archaeological_site_sequences/archaeo_calibration_files/"
            "archaeo_imu_camera_calib.yaml"
        ),
        "size_bytes": 938,
        "sha256": "e3aad241432b6619395564224fc39cb64931f17ac9446129c47a1ddf6c7a3ebc",
    }
)
CIRS_VEHICLE_T_IMU = (
    (2.220446049250313e-16, -1.0, -1.224646799147353e-16, 0.1),
    (-1.0, -2.220446049250313e-16, -2.465190328815662e-32, 0.0),
    (0.0, 1.224646799147353e-16, -1.0, -0.16),
    (0.0, 0.0, 0.0, 1.0),
)
CIRS_IMU_T_VEHICLE = (
    (2.220446049250313e-16, -1.0, 0.0, -2.220446049250313e-17),
    (-1.0, -2.220446049250313e-16, 1.224646799147353e-16, 0.10000000000000002),
    (-1.224646799147353e-16, -2.465190328815662e-32, -1.0, -0.16),
    (0.0, 0.0, 0.0, 1.0),
)
CIRS_FRAME_MATRIX_ATOL = 1e-15
CIRS_FRAME_EVIDENCE_SHA256 = MappingProxyType(
    {
        "materializer": "c11432ffe2b08620f0368e5d2c37f2c4d2105d39f246abbeddba2be4a0fd784a",
        "independent_auditor": "0bb42548755506a55e4d2555a8af13a726876173e7fa16ce2c381e4efca9979a",
        "hfnet_config": "b6e93daf3ca06e3e29433fffa7eb037119b97261888395fe1d51fa2d7a218204",
        "raw_full_dataset_bag": "6fb0309f56329c79f7b4a04be4993451975c8419d94302b980bf179f84251d3d",
        "camera_tf_bag_forbidden_as_body": "04db46c710232fcab1b461cc69ba86df9ff4236abd508f3578bbb554920df8fe",
    }
)

V2_ROSTER_AUTHORITY_IDENTITIES = MappingProxyType(
    {
        "whole_roster_pointer": {
                "path": (
                    "/mnt/data/AQUA-FE_WS/locks/"
                    "hfnet_v6_samehistory_positive_roster_execution_lock_v2.json"
                ),
                "size_bytes": 5_296,
                "sha256": "f9b44e9c126e68d151368c84a562aef5f9b06e1200b6f5dd1b6fe55d33430df1",
            },
        "bundle_root": (
            "/mnt/data/AQUA-FE_WS/locks/"
            ".hfnet_v6_samehistory_positive_roster_execution_lock_v2.bundle-"
            "a1df6b5e08cc9230"
        ),
        "roster_lock": {
                "path": (
                    "/mnt/data/AQUA-FE_WS/locks/"
                    ".hfnet_v6_samehistory_positive_roster_execution_lock_v2.bundle-"
                    "a1df6b5e08cc9230/roster_lock.json"
                ),
                "size_bytes": 3_132,
                "sha256": "a1df6b5e08cc923087e563caddf017eac344d111ddc3b2db801949a620245289",
            },
        "build_receipt": {
                "path": (
                    "/mnt/data/AQUA-FE_WS/locks/"
                    ".hfnet_v6_samehistory_positive_roster_execution_lock_v2.bundle-"
                    "a1df6b5e08cc9230/build_receipt.json"
                ),
                "size_bytes": 5_379,
                "sha256": "946f272063bfc55dc11296fcdbc09197419bd506818959bced8a836140fe8017",
            },
        "prepared_runner": {
                "path": (
                    "/home/ma/AQUA-FE_WS/scripts/"
                    "run_hfnet_v6_samehistory_positive_roster_v2.py"
                ),
                "size_bytes": 7_639,
                "sha256": "ec1afff8b1f7a8fdac0e7d395648bd4aa4b47b107bd3c2871a034eb49ba83bbb",
            },
        "prestart_parser_supersession": {
                "path": (
                    "/home/ma/AQUA-FE_WS/papers/"
                    "hfnet_v6_samehistory_positive_roster_prestart_parser_supersession_v2.md"
                ),
                "size_bytes": 4_653,
                "sha256": "cd8691886d6a9e219d0d87cb5b5a7df531433cf7f24ee3babb8190c8f58c5ae7",
            },
    }
)

FROZEN_AUTHORITY_HASHES = MappingProxyType(
    {
        "whole_roster_pointer_sha256": (
            "f9b44e9c126e68d151368c84a562aef5f9b06e1200b6f5dd1b6fe55d33430df1"
        ),
        "roster_lock_sha256": (
            "a1df6b5e08cc923087e563caddf017eac344d111ddc3b2db801949a620245289"
        ),
        "roster_build_receipt_sha256": (
            "946f272063bfc55dc11296fcdbc09197419bd506818959bced8a836140fe8017"
        ),
        "prepared_runner_sha256": (
            "ec1afff8b1f7a8fdac0e7d395648bd4aa4b47b107bd3c2871a034eb49ba83bbb"
        ),
        "prestart_parser_supersession_sha256": (
            "cd8691886d6a9e219d0d87cb5b5a7df531433cf7f24ee3babb8190c8f58c5ae7"
        ),
        "parent_protocol_sha256": (
            "a5f9db42e9b35e470fe1fa680e1d2682dd59e52a064fe805da95de829e4ef541"
        ),
        "historical_positive_report_sha256": (
            "4ddb11404c64f44537b9d142f97a4d13d744b0db3f18e1f8b857787503024ade"
        ),
        "analysis_grid_prefreeze_sha256": (
            "d31b9ee9f22ae47ba6e5b7d5d28f6a528331fd1c7071367ea28aed5032773f8d"
        ),
    }
)


class ContractError(RuntimeError):
    """A prospective analysis contract was violated."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


class AlignmentError(ContractError):
    """Proper fixed-scale SE(3) alignment cannot be authorized."""


def require(condition: bool, code: str) -> None:
    if not condition:
        raise ContractError(code)


@dataclass(frozen=True)
class CasePolicy:
    case_id: str
    dataset: str
    score_start_header_ns: int
    score_last_header_ns: int
    expected_grid_count: int
    reference_max_gap_ns: int
    estimate_max_gap_ns: int
    upper_bound_poses: int
    upper_bound_span_ns: int
    upper_bound_coverage: float
    upper_bound_rpe_pairs: int
    structural_na_reasons: Tuple[str, ...] = ()
    native_reference_anchor_count: int = 0
    reference_role: str = "non_independent_proxy_reference"


def _case(
    case_id: str,
    dataset: str,
    start_ns: int,
    last_ns: int,
    grid_count: int,
    reference_gap_ns: int,
    estimate_gap_ns: int,
    upper_poses: int,
    upper_span_tenths_s: int,
    upper_coverage: float,
    upper_pairs: int,
    structural: Tuple[str, ...] = (),
    native_anchors: int = 0,
) -> CasePolicy:
    return CasePolicy(
        case_id=case_id,
        dataset=dataset,
        score_start_header_ns=start_ns,
        score_last_header_ns=last_ns,
        expected_grid_count=grid_count,
        reference_max_gap_ns=reference_gap_ns,
        estimate_max_gap_ns=estimate_gap_ns,
        upper_bound_poses=upper_poses,
        upper_bound_span_ns=upper_span_tenths_s * 100_000_000,
        upper_bound_coverage=upper_coverage,
        upper_bound_rpe_pairs=upper_pairs,
        structural_na_reasons=structural,
        native_reference_anchor_count=native_anchors,
    )


# The order is the frozen whole-roster order, not an outcome-dependent order.
_CASE_SEQUENCE = (
    _case(
        "a05_3300_3700", "AQUALOC_ARCHAEOLOGY", 1_455_214_343_539_451_680,
        1_455_214_363_536_846_272, 200, 2_500_000_000, 250_000_000,
        189, 188, 0.9450, 179, native_anchors=21,
    ),
    _case(
        "a07_10800_11200", "AQUALOC_ARCHAEOLOGY", 1_542_884_252_125_312_224,
        1_542_884_272_123_384_448, 200, 2_500_000_000, 250_000_000,
        150, 149, 0.7500, 140, native_anchors=21,
    ),
    _case(
        "a08_4500_4660", "AQUALOC_ARCHAEOLOGY", 1_542_885_186_107_583_632,
        1_542_885_194_106_222_672, 80, 2_500_000_000, 250_000_000,
        67, 66, 0.8375, 57, ("COMMON_SPAN_LT_10S",),
    ),
    _case(
        "a09_6000_6200", "AQUALOC_ARCHAEOLOGY", 1_542_889_046_021_625_712,
        1_542_889_056_019_958_896, 100, 2_500_000_000, 250_000_000,
        87, 86, 0.8700, 77, ("COMMON_SPAN_LT_10S",),
    ),
    _case(
        "fjord1_s83_d10", "NTNU", 1_700_604_859_627_423_848,
        1_700_604_869_577_315_890, 100, 50_000_000, 250_000_000,
        85, 84, 0.8500, 75, ("COMMON_SPAN_LT_10S",),
    ),
    _case(
        "mclab1_s60_d15", "NTNU", 1_725_639_531_533_905_891,
        1_725_639_546_483_736_516, 150, 50_000_000, 250_000_000,
        139, 138, 0.9267, 129,
    ),
    _case(
        "cirs_s575_d30", "CIRS", 1_372_687_783_674_637_079,
        1_372_687_813_476_711_988, 299, 250_000_000, 500_000_000,
        252, 251, 0.8428, 242,
    ),
    _case(
        "cirs_s900_d30", "CIRS", 1_372_688_108_674_326_896,
        1_372_688_138_475_372_076, 299, 250_000_000, 500_000_000,
        258, 257, 0.8629, 248,
    ),
    _case(
        "a02_7600_8000", "AQUALOC_ARCHAEOLOGY", 1_542_829_171_674_622_016,
        1_542_829_191_671_578_400, 200, 2_500_000_000, 250_000_000,
        150, 149, 0.7500, 140, native_anchors=21,
    ),
    _case(
        "mclab2_s110_d10", "NTNU", 1_725_640_076_078_123_169,
        1_725_640_086_028_023_053, 100, 50_000_000, 250_000_000,
        67, 68, 0.6700, 47,
        ("COMMON_SPAN_LT_10S", "COMMON_COVERAGE_LT_0_70"),
    ),
)
CASE_TABLE: Mapping[str, CasePolicy] = MappingProxyType(
    {policy.case_id: policy for policy in _CASE_SEQUENCE}
)


@dataclass(frozen=True)
class ResamplePlanNs:
    source_stamps_ns: np.ndarray
    grid_ns: np.ndarray
    valid: np.ndarray
    methods: Tuple[str, ...]
    left_indices: np.ndarray
    right_indices: np.ndarray
    bracket_gaps_ns: np.ndarray
    alpha_numerators_ns: np.ndarray
    alpha_denominators_ns: np.ndarray


@dataclass(frozen=True)
class SupportDecision:
    case: CasePolicy
    plans: Mapping[str, ResamplePlanNs]
    joint_mask: np.ndarray
    segment_ids: np.ndarray
    rpe_pair_indices: np.ndarray
    matched_count: int
    reference_valid_count: int
    common_span_ns: int
    common_coverage: float
    hfnet_runability_status: str
    gate_failures: Tuple[str, ...]

    @property
    def gate_open(self) -> bool:
        return not self.gate_failures

    def evidence(self) -> dict[str, Any]:
        per_source = {}
        for name in SOURCE_ORDER:
            plan = self.plans[name]
            histogram: dict[str, int] = {}
            for method in plan.methods:
                histogram[method] = histogram.get(method, 0) + 1
            per_source[name] = {
                "valid_grid_count": int(np.sum(plan.valid)),
                "method_histogram": dict(sorted(histogram.items())),
                "maximum_allowed_two_sided_gap_ns": (
                    self.case.reference_max_gap_ns
                    if name == "reference"
                    else self.case.estimate_max_gap_ns
                ),
            }
        segment_count = (
            int(np.max(self.segment_ids) + 1)
            if np.any(self.segment_ids >= 0)
            else 0
        )
        return {
            "phase": "TIMESTAMP_SUPPORT_ONLY",
            "grid_definition": {
                "anchor_ns": self.case.score_start_header_ns,
                "last_score_camera_header_ns": self.case.score_last_header_ns,
                "step_ns": GRID_STEP_NS,
                "rate_hz": GRID_RATE_HZ,
                "grid_count": len(self.joint_mask),
                "offset_ns": 0,
            },
            "matched_count": self.matched_count,
            "reference_valid_count": self.reference_valid_count,
            "common_span_ns": self.common_span_ns,
            "common_span_s": self.common_span_ns / 1_000_000_000.0,
            "common_coverage": self.common_coverage,
            "coverage_denominator": len(self.joint_mask),
            "joint_mask": self.joint_mask.tolist(),
            "segment_ids": self.segment_ids.tolist(),
            "segment_count": segment_count,
            "rpe_pair_indices": self.rpe_pair_indices.tolist(),
            "rpe_pair_count": len(self.rpe_pair_indices),
            "rpe_delta_ns": RPE_DELTA_NS,
            "per_source": per_source,
            "hfnet_runability_status": self.hfnet_runability_status,
            "gate_thresholds": {
                "minimum_common_poses": MIN_COMMON_POSES,
                "minimum_common_span_ns": MIN_COMMON_SPAN_NS,
                "minimum_common_coverage": MIN_COMMON_COVERAGE,
                "minimum_exact_1s_rpe_pairs": MIN_RPE_PAIRS,
                "hfnet_runability_required": "PASS",
            },
            "gate_failures": list(self.gate_failures),
            "gate_open": self.gate_open,
            "coordinates_loaded": False,
            "metrics_computed": False,
        }


@dataclass(frozen=True)
class PoseSeriesNs:
    stamps_ns: Sequence[int]
    positions: np.ndarray
    quaternions_xyzw: np.ndarray
    trajectory_identity: Mapping[str, Any]


@dataclass(frozen=True)
class LockedTimestampSeriesNs:
    stamps_ns: Sequence[int]
    trajectory_identity: Mapping[str, Any]


@dataclass(frozen=True)
class StaticFrameTransform:
    source_frame: str
    target_frame: str
    source_T_target: np.ndarray
    convention: str = "source_T_target"


@dataclass(frozen=True)
class FormalIdentityVerification:
    verification_receipt_identity: Mapping[str, Any]
    execution_lock_value_sha256: str
    execution_lock_file_identity_verified: bool
    evaluator_self_identity_verified: bool
    controller_self_identity_verified: bool
    evidence_identities_verified: bool
    pre_metric_toctou_verified: bool


_VALIDATED_LOCK_MARKER = object()


@dataclass(frozen=True)
class ValidatedExecutionLock:
    case_id: str
    value_sha256: str
    runability_status: str
    runability_receipt_identity: Mapping[str, Any]
    trajectory_identities: Mapping[str, Mapping[str, Any]]
    transforms: Mapping[str, StaticFrameTransform]
    verification_receipt_identity: Mapping[str, Any]
    _marker: Any


@dataclass(frozen=True)
class CommonFullPoseBundle:
    case_id: str
    execution_lock_value_sha256: str
    grid_ns: np.ndarray
    joint_mask: np.ndarray
    segment_ids: np.ndarray
    rpe_pair_indices: np.ndarray
    positions: Mapping[str, np.ndarray]
    quaternions_xyzw: Mapping[str, np.ndarray]
    transform_audit: Mapping[str, Any]


@dataclass(frozen=True)
class EvoAdapterPlan:
    document: Mapping[str, Any]
    generated_tum_payloads: Mapping[str, bytes]


@dataclass(frozen=True)
class ProperSE3:
    rotation: np.ndarray
    translation: np.ndarray
    source_rank: int
    target_rank: int
    determinant: float
    orthogonality_error_fro: float
    scale: float = 1.0
    method: str = "KABSCH_PROPER_SE3_FIXED_SCALE_1"

    def audit(self) -> dict[str, Any]:
        return {
            "method": self.method,
            "scale": self.scale,
            "scale_estimated": False,
            "sim3_used": False,
            "rotation_determinant": self.determinant,
            "rotation_orthogonality_error_fro": self.orthogonality_error_fro,
            "source_centered_rank": self.source_rank,
            "target_centered_rank": self.target_rank,
            "rotation": self.rotation.tolist(),
            "translation": self.translation.tolist(),
        }


def canonical_json_bytes(value: Any) -> bytes:
    return (
        json.dumps(
            value,
            indent=2,
            sort_keys=True,
            ensure_ascii=False,
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")


def case_policy(case_id: str) -> CasePolicy:
    try:
        return CASE_TABLE[case_id]
    except KeyError as error:
        raise ContractError(f"UNKNOWN_CASE:{case_id}") from error


def make_case_grid_ns(policy_or_case_id: Any) -> np.ndarray:
    policy = (
        case_policy(policy_or_case_id)
        if isinstance(policy_or_case_id, str)
        else policy_or_case_id
    )
    require(isinstance(policy, CasePolicy), "INVALID_CASE_POLICY")
    require(policy.score_last_header_ns >= policy.score_start_header_ns, "INVALID_SCORE_RANGE")
    count = (
        (policy.score_last_header_ns - policy.score_start_header_ns) // GRID_STEP_NS
    ) + 1
    require(count == policy.expected_grid_count, f"GRID_COUNT_DRIFT:{policy.case_id}")
    # Roster epochs fit signed int64; explicit construction keeps every step exact.
    last_grid_ns = policy.score_start_header_ns + (count - 1) * GRID_STEP_NS
    require(last_grid_ns <= policy.score_last_header_ns, "GRID_LAST_AFTER_SCORE_END")
    require(last_grid_ns + GRID_STEP_NS > policy.score_last_header_ns, "GRID_NOT_MAXIMAL")
    return policy.score_start_header_ns + np.arange(count, dtype=np.int64) * GRID_STEP_NS


def _strict_integer_ns(values: Sequence[int], label: str, *, allow_empty: bool = True) -> np.ndarray:
    materialized = list(values)
    if not materialized:
        require(allow_empty, f"EMPTY_TIMESTAMPS:{label}")
        return np.asarray([], dtype=np.int64)
    checked: list[int] = []
    lower, upper = np.iinfo(np.int64).min, np.iinfo(np.int64).max
    for index, value in enumerate(materialized):
        require(
            isinstance(value, (int, np.integer)) and not isinstance(value, (bool, np.bool_)),
            f"TIMESTAMP_NOT_INTEGER_NS:{label}:{index}",
        )
        converted = int(value)
        require(lower <= converted <= upper, f"TIMESTAMP_INT64_RANGE:{label}:{index}")
        checked.append(converted)
    result = np.asarray(checked, dtype=np.int64)
    if len(result) > 1:
        deltas = np.diff(result)
        require(np.all(deltas > 0), f"TIMESTAMPS_NOT_STRICTLY_INCREASING:{label}")
    return result


def canonicalize_hfnet_epoch_ns(
    serialized_epoch_ns: Sequence[int],
    source_camera_header_ns: Sequence[int],
) -> np.ndarray:
    """Map each stock-HFNet epoch stamp to one unique source camera header.

    No offset is estimated.  A row with zero or multiple candidate headers is
    rejected, as is reuse of one camera header by multiple output rows.
    """

    max_absolute_delta_ns = HFNET_CANONICALIZATION_MAX_DELTA_NS
    serialized = _strict_integer_ns(serialized_epoch_ns, "hfnet_serialized")
    headers = _strict_integer_ns(source_camera_header_ns, "source_camera_headers")
    mapped: list[int] = []
    used_indices: set[int] = set()
    for row, stamp in enumerate(serialized):
        lower = int(np.searchsorted(headers, int(stamp) - max_absolute_delta_ns, side="left"))
        upper = int(np.searchsorted(headers, int(stamp) + max_absolute_delta_ns, side="right"))
        require(upper - lower == 1, f"HFNET_HEADER_MAPPING_NOT_UNIQUE:ROW_{row}")
        require(lower not in used_indices, f"HFNET_HEADER_REUSED:ROW_{row}")
        used_indices.add(lower)
        mapped.append(int(headers[lower]))
    # This is a bijection between output rows and their selected header subset;
    # a run may legitimately have no output pose for some input camera frames.
    require(len(used_indices) == len(mapped), "HFNET_BRIDGE_NOT_BIJECTIVE")
    return _strict_integer_ns(mapped, "canonical_hfnet", allow_empty=True)


def convert_quaternion_order_lossless(
    quaternions: Sequence[Sequence[Any]], source_order: str
) -> np.ndarray:
    """Permute quaternion columns to xyzw without normalization or arithmetic."""

    require(source_order in ("xyzw", "wxyz"), "QUATERNION_SOURCE_ORDER")
    values = np.asarray(quaternions)
    require(values.ndim == 2 and values.shape[1] == 4, "QUATERNION_ARRAY_SHAPE")
    if source_order == "xyzw":
        return values.copy()
    return values[:, [1, 2, 3, 0]].copy()


def build_resample_plan_ns(
    source_stamps_ns: Sequence[int],
    grid_ns: Sequence[int],
    max_two_sided_gap_ns: int,
    *,
    label: str,
) -> ResamplePlanNs:
    require(
        isinstance(max_two_sided_gap_ns, int) and max_two_sided_gap_ns > 0,
        f"INVALID_MAX_GAP:{label}",
    )
    stamps = _strict_integer_ns(source_stamps_ns, label)
    grid = _strict_integer_ns(grid_ns, "analysis_grid", allow_empty=False)
    valid = np.zeros(len(grid), dtype=bool)
    left = np.full(len(grid), -1, dtype=np.int64)
    right = np.full(len(grid), -1, dtype=np.int64)
    gaps = np.full(len(grid), -1, dtype=np.int64)
    numerators = np.zeros(len(grid), dtype=np.int64)
    denominators = np.ones(len(grid), dtype=np.int64)
    methods: list[str] = []

    for index, stamp in enumerate(grid):
        insertion = int(np.searchsorted(stamps, stamp, side="left"))
        if insertion < len(stamps) and stamps[insertion] == stamp:
            valid[index] = True
            left[index] = insertion
            right[index] = insertion
            gaps[index] = 0
            methods.append("EXACT")
            continue
        if insertion == 0 or insertion == len(stamps):
            methods.append("NO_SAMPLES" if not len(stamps) else "OUT_OF_RANGE")
            continue
        left_index = insertion - 1
        right_index = insertion
        gap = int(stamps[right_index]) - int(stamps[left_index])
        left[index] = left_index
        right[index] = right_index
        gaps[index] = gap
        if gap > max_two_sided_gap_ns:
            methods.append("GAP_EXCEEDED")
            continue
        numerator = int(stamp) - int(stamps[left_index])
        require(0 < numerator < gap, f"INVALID_TWO_SIDED_BRACKET:{label}:{index}")
        valid[index] = True
        numerators[index] = numerator
        denominators[index] = gap
        methods.append("INTERPOLATED_LINEAR_SLERP")

    return ResamplePlanNs(
        source_stamps_ns=stamps,
        grid_ns=grid,
        valid=valid,
        methods=tuple(methods),
        left_indices=left,
        right_indices=right,
        bracket_gaps_ns=gaps,
        alpha_numerators_ns=numerators,
        alpha_denominators_ns=denominators,
    )


def contiguous_segment_ids(joint_mask: Sequence[bool]) -> np.ndarray:
    mask = np.asarray(joint_mask, dtype=bool)
    require(mask.ndim == 1, "JOINT_MASK_NOT_ONE_DIMENSIONAL")
    result = np.full(len(mask), -1, dtype=np.int64)
    segment = -1
    previous = -2
    for index in np.flatnonzero(mask):
        if int(index) != previous + 1:
            segment += 1
        result[index] = segment
        previous = int(index)
    return result


def exact_delta_pairs_ns(
    grid_ns: Sequence[int],
    joint_mask: Sequence[bool],
    segment_ids: Sequence[int],
    delta_ns: int = RPE_DELTA_NS,
) -> np.ndarray:
    grid = _strict_integer_ns(grid_ns, "rpe_grid", allow_empty=True)
    mask = np.asarray(joint_mask, dtype=bool)
    segments = np.asarray(segment_ids, dtype=np.int64)
    require(grid.shape == mask.shape == segments.shape, "RPE_ARRAY_SHAPE_MISMATCH")
    require(isinstance(delta_ns, int) and delta_ns > 0, "INVALID_RPE_DELTA_NS")
    lookup = {int(stamp): index for index, stamp in enumerate(grid)}
    pairs: list[tuple[int, int]] = []
    for left in np.flatnonzero(mask):
        right = lookup.get(int(grid[left]) + delta_ns)
        if right is None or not mask[right]:
            continue
        if segments[right] != segments[left]:
            continue
        require(int(grid[right]) - int(grid[left]) == delta_ns, "RPE_DELTA_IDENTITY_FAILED")
        pairs.append((int(left), int(right)))
    return np.asarray(pairs, dtype=np.int64).reshape((-1, 2))


def build_common_support(
    case_id: str,
    timestamps_by_source: Mapping[str, Sequence[int]],
    hfnet_runability_status: str,
) -> SupportDecision:
    policy = case_policy(case_id)
    require(
        set(timestamps_by_source) == set(SOURCE_ORDER),
        "TIMESTAMP_SOURCE_SET_MISMATCH",
    )
    grid = make_case_grid_ns(policy)
    plans: dict[str, ResamplePlanNs] = {}
    for name in SOURCE_ORDER:
        plans[name] = build_resample_plan_ns(
            timestamps_by_source[name],
            grid,
            policy.reference_max_gap_ns if name == "reference" else policy.estimate_max_gap_ns,
            label=name,
        )
    joint = np.ones(len(grid), dtype=bool)
    for name in SOURCE_ORDER:
        joint &= plans[name].valid
    indices = np.flatnonzero(joint)
    matched = len(indices)
    span_ns = int(grid[indices[-1]]) - int(grid[indices[0]]) if matched >= 2 else 0
    coverage = matched / len(grid)
    segments = contiguous_segment_ids(joint)
    pairs = exact_delta_pairs_ns(grid, joint, segments)
    failures: list[str] = []
    if matched < MIN_COMMON_POSES:
        failures.append("COMMON_POSES_LT_30")
    if span_ns < MIN_COMMON_SPAN_NS:
        failures.append("COMMON_SPAN_LT_10S")
    if coverage < MIN_COMMON_COVERAGE:
        failures.append("COMMON_COVERAGE_LT_0_70")
    if len(pairs) < MIN_RPE_PAIRS:
        failures.append("EXACT_1S_RPE_PAIRS_LT_10")
    if hfnet_runability_status != "PASS":
        failures.append("HFNET_RUNABILITY_NOT_PASS")
    return SupportDecision(
        case=policy,
        plans=MappingProxyType(plans),
        joint_mask=joint,
        segment_ids=segments,
        rpe_pair_indices=pairs,
        matched_count=matched,
        reference_valid_count=int(np.sum(plans["reference"].valid)),
        common_span_ns=span_ns,
        common_coverage=coverage,
        hfnet_runability_status=hfnet_runability_status,
        gate_failures=tuple(failures),
    )


def _ordered_ns_digest(rows: Sequence[Sequence[int]]) -> str:
    """Digest ordered integer-nanosecond rows in an explicit ASCII format."""

    digest = hashlib.sha256()
    for row in rows:
        checked = _strict_integer_ns(row, "population_digest_row", allow_empty=False)
        digest.update((",".join(str(int(value)) for value in checked) + "\n").encode("ascii"))
    return digest.hexdigest()


def evo_population_contract(support: SupportDecision) -> dict[str, Any]:
    """Bind primary and independent-evo populations before either is compared."""

    require(support.gate_open, "EVO_POPULATION_REQUESTED_BEFORE_SUPPORT_GATE")
    common_stamps = support.plans["reference"].grid_ns[support.joint_mask]
    pair_stamps = [
        (
            int(support.plans["reference"].grid_ns[left]),
            int(support.plans["reference"].grid_ns[right]),
        )
        for left, right in support.rpe_pair_indices
    ]
    return {
        "serialization": "ORDERED_SIGNED_DECIMAL_INTEGER_NS_CSV_NEWLINE",
        "common_pose_count": len(common_stamps),
        "ordered_common_pose_ns_sha256": _ordered_ns_digest(
            [(int(stamp),) for stamp in common_stamps]
        ),
        "exact_1s_pair_count": len(pair_stamps),
        "ordered_exact_1s_pair_ns_sha256": _ordered_ns_digest(pair_stamps),
        "pair_delta_ns": RPE_DELTA_NS,
        "evo_timestamp_basis": "relative_zero_from_authoritative_integer_ns",
        "primary_and_evo_population_must_match": True,
    }


def _payload_identity(path: Path, payload: bytes) -> dict[str, Any]:
    return {
        "path": str(path),
        "size_bytes": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest(),
    }


def _relative_ns_text(stamp_ns: int, origin_ns: int) -> str:
    relative = stamp_ns - origin_ns
    require(relative >= 0, "EVO_RELATIVE_TIMESTAMP_NEGATIVE")
    seconds, nanoseconds = divmod(relative, 1_000_000_000)
    return f"{seconds}.{nanoseconds:09d}"


def render_full_pose_tum(
    grid_ns: np.ndarray,
    positions: np.ndarray,
    quaternions_xyzw: np.ndarray,
    indices: np.ndarray,
    origin_ns: int,
) -> bytes:
    """Render real full poses; identity-quaternion substitution is forbidden."""

    grid = _strict_integer_ns(grid_ns, "evo_tum_grid", allow_empty=False)
    positions = np.asarray(positions, dtype=float)
    quaternions = np.asarray(quaternions_xyzw, dtype=float)
    selected = np.asarray(indices, dtype=np.int64)
    require(positions.shape == (len(grid), 3), "EVO_TUM_POSITION_SHAPE")
    require(quaternions.shape == (len(grid), 4), "EVO_TUM_QUATERNION_SHAPE")
    require(len(selected) > 0, "EVO_TUM_EMPTY_SELECTION")
    lines: list[str] = []
    for row, index in enumerate(selected):
        require(0 <= index < len(grid), f"EVO_TUM_INDEX_RANGE:{row}")
        pose_values = np.concatenate((positions[index], quaternions[index]))
        require(np.all(np.isfinite(pose_values)), f"EVO_TUM_NONFINITE:{row}")
        quaternion_norm = float(np.linalg.norm(quaternions[index]))
        require(abs(quaternion_norm - 1.0) <= 1e-9, f"EVO_TUM_QUATERNION_NORM:{row}")
        lines.append(
            " ".join(
                [_relative_ns_text(int(grid[index]), origin_ns)]
                + [format(float(value), ".17g") for value in pose_values]
            )
        )
    return ("\n".join(lines) + "\n").encode("ascii")


def plan_evo_adapter(
    support: SupportDecision,
    bundle: CommonFullPoseBundle,
    output_root: Path,
) -> EvoAdapterPlan:
    """Create exact evo inputs/argv without starting a subprocess."""

    require(support.gate_open, "EVO_PLAN_BEFORE_SUPPORT_GATE")
    require(bundle.case_id == support.case.case_id, "EVO_PLAN_BUNDLE_CASE")
    require(output_root.is_absolute(), "EVO_PLAN_OUTPUT_NOT_ABSOLUTE")
    root = output_root.resolve(strict=False)
    require(
        np.array_equal(bundle.grid_ns, support.plans["reference"].grid_ns)
        and np.array_equal(bundle.joint_mask, support.joint_mask)
        and np.array_equal(bundle.segment_ids, support.segment_ids)
        and np.array_equal(bundle.rpe_pair_indices, support.rpe_pair_indices),
        "EVO_PLAN_SUPPORT_BUNDLE_MISMATCH",
    )
    common_indices = np.flatnonzero(support.joint_mask)
    origin_ns = support.case.score_start_header_ns
    payloads: dict[str, bytes] = {}
    identities: dict[str, dict[str, Any]] = {}

    def add_tum(relative_path: str, source: str, indices: np.ndarray) -> Path:
        path = (root / relative_path).resolve(strict=False)
        require(str(path).startswith(str(root) + os.sep), "EVO_TUM_PATH_ESCAPES_ROOT")
        payload = render_full_pose_tum(
            bundle.grid_ns,
            bundle.positions[source],
            bundle.quaternions_xyzw[source],
            indices,
            origin_ns,
        )
        payloads[str(path)] = payload
        identities[str(path)] = _payload_identity(path, payload)
        return path

    reference_common = add_tum("inputs/reference_common.tum", "reference", common_indices)
    commands: list[dict[str, Any]] = []
    segment_population: list[dict[str, Any]] = []
    segment_indices: dict[int, np.ndarray] = {}
    for segment_id in sorted(set(int(value) for value in support.segment_ids if value >= 0)):
        indices = np.flatnonzero(support.segment_ids == segment_id)
        pair_count = max(0, len(indices) - 10)
        if pair_count == 0:
            continue
        segment_indices[segment_id] = indices
        pair_rows = [
            (int(bundle.grid_ns[index]), int(bundle.grid_ns[index + 10]))
            for index in indices[:-10]
        ]
        require(
            all(right - left == RPE_DELTA_NS for left, right in pair_rows),
            f"EVO_SEGMENT_PAIR_DELTA:{segment_id}",
        )
        segment_population.append(
            {
                "segment_id": segment_id,
                "pose_count": len(indices),
                "pair_count": pair_count,
                "grid_indices": [int(index) for index in indices],
                "ordered_pose_ns": [
                    int(bundle.grid_ns[index]) for index in indices
                ],
                "ordered_pair_grid_indices": [
                    [int(index), int(index + 10)] for index in indices[:-10]
                ],
                "ordered_pose_ns_sha256": _ordered_ns_digest(
                    [(int(bundle.grid_ns[index]),) for index in indices]
                ),
                "ordered_pair_ns_sha256": _ordered_ns_digest(pair_rows),
            }
        )
    require(
        sum(item["pair_count"] for item in segment_population)
        == len(support.rpe_pair_indices),
        "EVO_SEGMENT_PAIR_TOTAL_MISMATCH",
    )

    reference_segment_paths: dict[int, Path] = {}
    for segment_id, indices in segment_indices.items():
        reference_segment_paths[segment_id] = add_tum(
            f"inputs/segments/reference_segment_{segment_id:03d}.tum",
            "reference",
            indices,
        )

    for arm in ESTIMATE_ORDER:
        estimate_common = add_tum(f"inputs/{arm}_common.tum", arm, common_indices)
        commands.append(
            {
                "command_id": f"ape:{arm}",
                "kind": "APE",
                "arm": arm,
                "segment_id": None,
                "expected_pair_count": None,
                "argv": [
                    str(EVO_APE_IDENTITY["path"]),
                    "tum",
                    str(reference_common),
                    str(estimate_common),
                    "-a",
                    "-r",
                    "trans_part",
                    "--t_max_diff",
                    "1e-9",
                    "--t_offset",
                    "0",
                ],
            }
        )
        for population in segment_population:
            segment_id = int(population["segment_id"])
            estimate_segment = add_tum(
                f"inputs/segments/{arm}_segment_{segment_id:03d}.tum",
                arm,
                segment_indices[segment_id],
            )
            commands.append(
                {
                    "command_id": f"rpe:{arm}:segment_{segment_id:03d}",
                    "kind": "RPE",
                    "arm": arm,
                    "segment_id": segment_id,
                    "expected_pair_count": int(population["pair_count"]),
                    "argv": [
                        str(EVO_RPE_IDENTITY["path"]),
                        "tum",
                        str(reference_segment_paths[segment_id]),
                        str(estimate_segment),
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
                }
            )

    core_document = {
        "schema_version": "aqua-fe-hfnet-v6-positive-roster-evo-adapter-plan-v1",
        "case_id": support.case.case_id,
        "execution_lock_value_sha256": bundle.execution_lock_value_sha256,
        "status": "PLANNED_NOT_EXECUTED",
        "evo_version": EVO_VERSION,
        "timestamp_origin_ns": origin_ns,
        "timestamp_sync_tolerance_s": "1e-9",
        "timestamp_offset_s": "0",
        "population": evo_population_contract(support),
        "segment_population": segment_population,
        "generated_tum": identities,
        "commands": commands,
        "real_orientations_preserved": True,
        "subprocess_started": False,
    }
    plan_digest = hashlib.sha256(canonical_json_bytes(core_document)).hexdigest()
    document = {**core_document, "plan_core_sha256": plan_digest}
    return EvoAdapterPlan(
        document=MappingProxyType(document),
        generated_tum_payloads=MappingProxyType(payloads),
    )


def _load_verified_artifact(
    identity_value: Mapping[str, Any],
    artifact_loader: Callable[[Mapping[str, Any]], bytes],
    label: str,
) -> bytes:
    _identity_shape(identity_value, label)
    payload = artifact_loader(identity_value)
    require(isinstance(payload, bytes), f"EVO_ARTIFACT_LOADER_NOT_BYTES:{label}")
    require(len(payload) == identity_value["size_bytes"], f"EVO_ARTIFACT_SIZE:{label}")
    require(
        hashlib.sha256(payload).hexdigest() == identity_value["sha256"],
        f"EVO_ARTIFACT_SHA256:{label}",
    )
    return payload


def _parse_evo_rmse(stdout_payload: bytes, command_id: str) -> float:
    try:
        text_value = stdout_payload.decode("utf-8")
    except UnicodeDecodeError as error:
        raise ContractError(f"EVO_STDOUT_NOT_UTF8:{command_id}") from error
    values: list[float] = []
    for line in text_value.splitlines():
        fields = line.strip().split()
        if fields and fields[0] == "rmse" and len(fields) >= 2:
            try:
                values.append(float(fields[-1]))
            except ValueError as error:
                raise ContractError(f"EVO_RMSE_PARSE:{command_id}") from error
    require(
        len(values) == 1 and math.isfinite(values[0]) and values[0] >= 0.0,
        f"EVO_RMSE_COUNT:{command_id}",
    )
    return values[0]


def _parse_generated_tum_pose_count(payload: bytes, label: str) -> int:
    """Independently validate a generated evo input and count its full poses."""

    try:
        text_value = payload.decode("ascii")
    except UnicodeDecodeError as error:
        raise ContractError(f"EVO_TUM_NOT_ASCII:{label}") from error
    lines = text_value.splitlines()
    require(bool(lines), f"EVO_TUM_EMPTY:{label}")
    previous_timestamp = -math.inf
    for row, line in enumerate(lines):
        fields = line.split()
        require(len(fields) == 8, f"EVO_TUM_FIELD_COUNT:{label}:{row}")
        try:
            values = [float(field) for field in fields]
        except ValueError as error:
            raise ContractError(f"EVO_TUM_FLOAT_PARSE:{label}:{row}") from error
        require(all(math.isfinite(value) for value in values), f"EVO_TUM_NONFINITE:{label}:{row}")
        require(values[0] > previous_timestamp, f"EVO_TUM_TIME_ORDER:{label}:{row}")
        previous_timestamp = values[0]
        quaternion_norm = math.sqrt(sum(value * value for value in values[4:8]))
        require(abs(quaternion_norm - 1.0) <= 1e-9, f"EVO_TUM_QUATERNION_NORM:{label}:{row}")
    return len(lines)


def validate_evo_adapter_receipt(
    plan: EvoAdapterPlan,
    primary_result: Mapping[str, Any],
    receipt: Mapping[str, Any],
    artifact_loader: Callable[[Mapping[str, Any]], bytes],
) -> dict[str, Any]:
    """Parse evo artifacts; caller-supplied RMSE/population values are rejected."""

    require(isinstance(plan, EvoAdapterPlan), "EVO_PLAN_TYPE")
    document = plan.document
    core_document = dict(document)
    sealed_plan_digest = core_document.pop("plan_core_sha256", None)
    require(
        sealed_plan_digest == hashlib.sha256(canonical_json_bytes(core_document)).hexdigest(),
        "EVO_PLAN_CORE_DIGEST",
    )
    require(
        primary_result.get("case_id") == document["case_id"]
        and primary_result.get("accuracy_status")
        == "PRIMARY_METRICS_COMPUTED_EVO_PENDING"
        and primary_result.get("evo_population_contract") == document["population"]
        and (primary_result.get("execution_lock_binding") or {}).get("value_sha256")
        == document["execution_lock_value_sha256"],
        "EVO_PRIMARY_RESULT_BINDING",
    )
    pending = primary_result.get("independent_evo_pending") or {}
    require(
        pending.get("status") == "EVO_CROSSCHECK_PENDING"
        and pending.get("plan_core_sha256") == document["plan_core_sha256"]
        and (primary_result.get("claim_boundary") or {}).get(
            "accuracy_numeric_authorized"
        )
        is False
        and (primary_result.get("claim_boundary") or {}).get(
            "ranking_authorized"
        )
        is False,
        "EVO_PRIMARY_PLAN_BINDING",
    )
    require(
        receipt.get("schema_version")
        == "aqua-fe-hfnet-v6-positive-roster-evo-adapter-receipt-v1",
        "EVO_RECEIPT_SCHEMA",
    )
    require(
        set(receipt) == {
            "schema_version",
            "plan_core_sha256",
            "generated_tum",
            "commands",
        },
        "EVO_RECEIPT_KEYS",
    )
    require(receipt.get("plan_core_sha256") == document["plan_core_sha256"], "EVO_RECEIPT_PLAN")
    require(receipt.get("generated_tum") == document["generated_tum"], "EVO_RECEIPT_TUM_BINDING")
    require(
        set(plan.generated_tum_payloads) == set(document["generated_tum"]),
        "EVO_PLAN_TUM_PAYLOAD_SET",
    )
    verified_tum_payloads: dict[str, bytes] = {}
    observed_artifact_paths = set(document["generated_tum"])
    for path, identity_value in document["generated_tum"].items():
        payload = _load_verified_artifact(identity_value, artifact_loader, f"tum:{path}")
        require(payload == plan.generated_tum_payloads[path], f"EVO_TUM_PAYLOAD_DRIFT:{path}")
        _parse_generated_tum_pose_count(payload, path)
        verified_tum_payloads[path] = payload

    planned_commands = document["commands"]
    observed_commands = receipt.get("commands")
    require(isinstance(observed_commands, list), "EVO_RECEIPT_COMMANDS_NOT_LIST")
    require(len(observed_commands) == len(planned_commands), "EVO_RECEIPT_COMMAND_COUNT")
    parsed: dict[str, dict[str, Any]] = {arm: {"rpe_segments": []} for arm in ESTIMATE_ORDER}
    for planned, observed in zip(planned_commands, observed_commands):
        require(
            isinstance(observed, Mapping)
            and set(observed)
            == {"command_id", "argv", "return_code", "stdout", "stderr"},
            f"EVO_COMMAND_RECEIPT_KEYS:{planned['command_id']}",
        )
        require(observed["command_id"] == planned["command_id"], "EVO_COMMAND_ID")
        require(observed["argv"] == planned["argv"], f"EVO_ARGV:{planned['command_id']}")
        require(
            isinstance(observed["return_code"], int)
            and not isinstance(observed["return_code"], bool)
            and observed["return_code"] == 0,
            f"EVO_RETURN_CODE:{planned['command_id']}",
        )
        stdout_path = observed["stdout"].get("path") if isinstance(observed["stdout"], Mapping) else None
        stderr_path = observed["stderr"].get("path") if isinstance(observed["stderr"], Mapping) else None
        require(
            isinstance(stdout_path, str)
            and isinstance(stderr_path, str)
            and stdout_path not in observed_artifact_paths
            and stderr_path not in observed_artifact_paths
            and stdout_path != stderr_path,
            f"EVO_COMMAND_ARTIFACT_PATH_REUSE:{planned['command_id']}",
        )
        observed_artifact_paths.update((stdout_path, stderr_path))
        stdout_payload = _load_verified_artifact(
            observed["stdout"], artifact_loader, f"stdout:{planned['command_id']}"
        )
        _load_verified_artifact(
            observed["stderr"], artifact_loader, f"stderr:{planned['command_id']}"
        )
        rmse = _parse_evo_rmse(stdout_payload, planned["command_id"])
        arm_result = parsed[planned["arm"]]
        if planned["kind"] == "APE":
            require("ape_rmse_m" not in arm_result, f"EVO_DUPLICATE_APE:{planned['arm']}")
            arm_result["ape_rmse_m"] = rmse
        else:
            reference_path = planned["argv"][2]
            estimate_path = planned["argv"][3]
            reference_pose_count = _parse_generated_tum_pose_count(
                verified_tum_payloads[reference_path], reference_path
            )
            estimate_pose_count = _parse_generated_tum_pose_count(
                verified_tum_payloads[estimate_path], estimate_path
            )
            require(
                reference_pose_count == estimate_pose_count,
                f"EVO_RPE_INPUT_POSE_COUNT:{planned['command_id']}",
            )
            parsed_pair_count = max(0, reference_pose_count - 10)
            require(
                parsed_pair_count == planned["expected_pair_count"],
                f"EVO_RPE_PARSED_PAIR_COUNT:{planned['command_id']}",
            )
            arm_result["rpe_segments"].append(
                {
                    "segment_id": planned["segment_id"],
                    "pair_count": parsed_pair_count,
                    "pair_count_source": (
                        "PARSED_GENERATED_TUM_POSE_COUNT_MINUS_EXACT_FRAME_DELTA_10"
                    ),
                    "rmse_m": rmse,
                }
            )

    failures: list[str] = []
    per_arm: dict[str, Any] = {}
    primary_metrics = primary_result.get("metrics")
    require(isinstance(primary_metrics, Mapping), "EVO_PRIMARY_METRICS_MISSING")
    for arm in ESTIMATE_ORDER:
        arm_result = parsed[arm]
        require("ape_rmse_m" in arm_result, f"EVO_APE_MISSING:{arm}")
        total_pairs = sum(item["pair_count"] for item in arm_result["rpe_segments"])
        require(
            total_pairs == document["population"]["exact_1s_pair_count"],
            f"EVO_RPE_PAIR_COUNT:{arm}",
        )
        weighted_squared = sum(
            item["pair_count"] * item["rmse_m"] ** 2
            for item in arm_result["rpe_segments"]
        )
        rpe_rmse = math.sqrt(weighted_squared / total_pairs)
        primary_ape = float(primary_metrics[arm]["translation_ape"]["rmse_m"])
        primary_rpe = float(
            primary_metrics[arm]["translation_rpe_exact_1s"]["rmse_m"]
        )
        ape_difference = abs(primary_ape - arm_result["ape_rmse_m"])
        rpe_difference = abs(primary_rpe - rpe_rmse)
        if ape_difference > EVO_MAX_RMSE_DISAGREEMENT_M:
            failures.append(f"EVO_APE_DISAGREEMENT_GT_1E_5:{arm}")
        if rpe_difference > EVO_MAX_RMSE_DISAGREEMENT_M:
            failures.append(f"EVO_RPE_DISAGREEMENT_GT_1E_5:{arm}")
        per_arm[arm] = {
            "primary_ape_rmse_m": primary_ape,
            "evo_ape_rmse_m": arm_result["ape_rmse_m"],
            "ape_absolute_difference_m": ape_difference,
            "primary_rpe_rmse_m": primary_rpe,
            "evo_weighted_segment_rpe_rmse_m": rpe_rmse,
            "rpe_absolute_difference_m": rpe_difference,
            "rpe_pair_count": total_pairs,
            "segments": arm_result["rpe_segments"],
        }
    return {
        "schema_version": "aqua-fe-hfnet-v6-positive-roster-evo-crosscheck-v1",
        "status": "PASS" if not failures else "CLOSED_NO_RANKING",
        "plan_core_sha256": document["plan_core_sha256"],
        "failures": failures,
        "maximum_allowed_absolute_rmse_disagreement_m": EVO_MAX_RMSE_DISAGREEMENT_M,
        "per_arm": per_arm,
        "accuracy_numeric_authorized": not failures,
        "ranking_authorized": not failures,
    }


def _validated_crosscheck_pass_for_finalize(
    primary_result: Mapping[str, Any], crosscheck: Mapping[str, Any]
) -> bool:
    require(
        set(crosscheck)
        == {
            "schema_version",
            "status",
            "plan_core_sha256",
            "failures",
            "maximum_allowed_absolute_rmse_disagreement_m",
            "per_arm",
            "accuracy_numeric_authorized",
            "ranking_authorized",
        },
        "EVO_FINALIZE_CROSSCHECK_KEYS",
    )
    require(
        crosscheck.get("schema_version")
        == "aqua-fe-hfnet-v6-positive-roster-evo-crosscheck-v1",
        "EVO_FINALIZE_CROSSCHECK_SCHEMA",
    )
    require(
        crosscheck.get("plan_core_sha256")
        == (primary_result.get("independent_evo_pending") or {}).get(
            "plan_core_sha256"
        ),
        "EVO_FINALIZE_PLAN_BINDING",
    )
    require(
        crosscheck.get("maximum_allowed_absolute_rmse_disagreement_m")
        == EVO_MAX_RMSE_DISAGREEMENT_M,
        "EVO_FINALIZE_TOLERANCE",
    )
    primary_metrics = primary_result.get("metrics")
    per_arm = crosscheck.get("per_arm")
    require(
        isinstance(primary_metrics, Mapping)
        and isinstance(per_arm, Mapping)
        and set(per_arm) == set(ESTIMATE_ORDER),
        "EVO_FINALIZE_PER_ARM_SET",
    )
    expected_failures: list[str] = []
    for arm in ESTIMATE_ORDER:
        values = per_arm[arm]
        require(
            isinstance(values, Mapping)
            and set(values)
            == {
                "primary_ape_rmse_m",
                "evo_ape_rmse_m",
                "ape_absolute_difference_m",
                "primary_rpe_rmse_m",
                "evo_weighted_segment_rpe_rmse_m",
                "rpe_absolute_difference_m",
                "rpe_pair_count",
                "segments",
            },
            f"EVO_FINALIZE_PER_ARM_KEYS:{arm}",
        )
        numeric = {
            key: float(values[key])
            for key in (
                "primary_ape_rmse_m",
                "evo_ape_rmse_m",
                "ape_absolute_difference_m",
                "primary_rpe_rmse_m",
                "evo_weighted_segment_rpe_rmse_m",
                "rpe_absolute_difference_m",
            )
        }
        require(
            all(math.isfinite(value) and value >= 0.0 for value in numeric.values()),
            f"EVO_FINALIZE_NONFINITE_OR_NEGATIVE:{arm}",
        )
        primary_ape = float(primary_metrics[arm]["translation_ape"]["rmse_m"])
        primary_rpe = float(
            primary_metrics[arm]["translation_rpe_exact_1s"]["rmse_m"]
        )
        ape_difference = abs(
            numeric["primary_ape_rmse_m"] - numeric["evo_ape_rmse_m"]
        )
        rpe_difference = abs(
            numeric["primary_rpe_rmse_m"]
            - numeric["evo_weighted_segment_rpe_rmse_m"]
        )
        require(
            numeric["primary_ape_rmse_m"] == primary_ape
            and numeric["primary_rpe_rmse_m"] == primary_rpe
            and math.isclose(
                numeric["ape_absolute_difference_m"],
                ape_difference,
                rel_tol=0.0,
                abs_tol=1e-15,
            )
            and math.isclose(
                numeric["rpe_absolute_difference_m"],
                rpe_difference,
                rel_tol=0.0,
                abs_tol=1e-15,
            ),
            f"EVO_FINALIZE_RECOMPUTE:{arm}",
        )
        segments = values["segments"]
        require(isinstance(segments, list) and bool(segments), f"EVO_FINALIZE_SEGMENTS:{arm}")
        segment_pair_total = 0
        weighted_squared = 0.0
        for segment in segments:
            require(
                isinstance(segment, Mapping)
                and set(segment)
                == {
                    "segment_id",
                    "pair_count",
                    "pair_count_source",
                    "rmse_m",
                }
                and segment.get("pair_count_source")
                == "PARSED_GENERATED_TUM_POSE_COUNT_MINUS_EXACT_FRAME_DELTA_10"
                and isinstance(segment.get("pair_count"), int)
                and segment["pair_count"] > 0,
                f"EVO_FINALIZE_SEGMENT_RECORD:{arm}",
            )
            segment_rmse = float(segment["rmse_m"])
            require(
                math.isfinite(segment_rmse) and segment_rmse >= 0.0,
                f"EVO_FINALIZE_SEGMENT_RMSE:{arm}",
            )
            segment_pair_total += segment["pair_count"]
            weighted_squared += segment["pair_count"] * segment_rmse**2
        require(
            values["rpe_pair_count"] == segment_pair_total
            == (primary_result.get("evo_population_contract") or {}).get(
                "exact_1s_pair_count"
            )
            and math.isclose(
                math.sqrt(weighted_squared / segment_pair_total),
                numeric["evo_weighted_segment_rpe_rmse_m"],
                rel_tol=0.0,
                abs_tol=1e-15,
            ),
            f"EVO_FINALIZE_PAIR_WEIGHTING:{arm}",
        )
        if ape_difference > EVO_MAX_RMSE_DISAGREEMENT_M:
            expected_failures.append(f"EVO_APE_DISAGREEMENT_GT_1E_5:{arm}")
        if rpe_difference > EVO_MAX_RMSE_DISAGREEMENT_M:
            expected_failures.append(f"EVO_RPE_DISAGREEMENT_GT_1E_5:{arm}")
    passed = not expected_failures
    require(
        crosscheck.get("failures") == expected_failures
        and crosscheck.get("status")
        == ("PASS" if passed else "CLOSED_NO_RANKING")
        and crosscheck.get("accuracy_numeric_authorized") is passed
        and crosscheck.get("ranking_authorized") is passed,
        "EVO_FINALIZE_AUTHORIZATION_INCONSISTENT",
    )
    return passed


def finalize_primary_with_evo(
    primary_result: Mapping[str, Any], crosscheck: Mapping[str, Any]
) -> dict[str, Any]:
    require(
        primary_result.get("accuracy_status")
        == "PRIMARY_METRICS_COMPUTED_EVO_PENDING",
        "EVO_FINALIZE_PRIMARY_STATUS",
    )
    passed = _validated_crosscheck_pass_for_finalize(primary_result, crosscheck)
    result = json.loads(canonical_json_bytes(primary_result).decode("utf-8"))
    result["evo_crosscheck"] = dict(crosscheck)
    result["accuracy_status"] = (
        "ACCURACY_AUTHORIZED_EVO_PASS" if passed else "CLOSED_NO_RANKING"
    )
    result["claim_boundary"]["accuracy_numeric_authorized"] = bool(passed)
    result["claim_boundary"]["ranking_authorized"] = bool(passed)
    return result


def native_anchor_sensitivity_preflight(
    case_id: str, primary_result: Mapping[str, Any]
) -> dict[str, Any]:
    """Authorize, but do not invent, the separately locked AQUALOC sensitivity."""

    policy = case_policy(case_id)
    require(policy.dataset == "AQUALOC_ARCHAEOLOGY", "SENSITIVITY_NOT_AQUALOC")
    require(policy.native_reference_anchor_count > 0, "SENSITIVITY_NATIVE_ANCHORS_NOT_FROZEN")
    primary_open = (
        primary_result.get("case_id") == case_id
        and isinstance(primary_result.get("metrics"), Mapping)
        and (primary_result.get("support") or {}).get("gate_open") is True
        and primary_result.get("accuracy_status")
        == "PRIMARY_METRICS_COMPUTED_EVO_PENDING"
    )
    return {
        "case_id": case_id,
        "authorized": bool(primary_open),
        "status": "READY_FOR_SEPARATELY_LOCKED_DESCRIPTIVE_SENSITIVITY" if primary_open else "NA_PRIMARY_GATE_CLOSED",
        "native_reference_anchor_count": policy.native_reference_anchor_count,
        "descriptive_only": True,
        "changes_primary_grid_contract": False,
        "can_reopen_closed_primary_gate": False,
        "metrics_computed": False,
    }


def _structural_na_result(policy: CasePolicy, runability_status: str) -> dict[str, Any]:
    require(bool(policy.structural_na_reasons), "CASE_NOT_STRUCTURAL_NA")
    return {
        "schema_version": SCHEMA_VERSION,
        "case_id": policy.case_id,
        "dataset": policy.dataset,
        "accuracy_status": "STRUCTURAL_NA_PREFROZEN_UPPER_BOUND",
        "support": {
            "phase": "PREFROZEN_HISTORICAL_THREE_SOURCE_UPPER_BOUND",
            "upper_bound_poses": policy.upper_bound_poses,
            "grid_count": policy.expected_grid_count,
            "upper_bound_span_ns": policy.upper_bound_span_ns,
            "upper_bound_span_s": policy.upper_bound_span_ns / 1_000_000_000.0,
            "upper_bound_coverage": policy.upper_bound_coverage,
            "upper_bound_exact_1s_rpe_pairs": policy.upper_bound_rpe_pairs,
            "structural_na_reasons": list(policy.structural_na_reasons),
            "adding_hfnet_can_only_remove_support": True,
            "hfnet_runability_status": runability_status,
            "coordinates_loaded": False,
            "metrics_computed": False,
        },
        "claim_boundary": {
            "accuracy_numeric_authorized": False,
            "ranking_computed": False,
            "ranking_authorized": False,
            "sim3_used": False,
        },
    }


def _validate_pose_series(
    series: PoseSeriesNs,
    plan: ResamplePlanNs,
    label: str,
    expected_trajectory_identity: Mapping[str, Any],
) -> tuple[np.ndarray, np.ndarray]:
    require(
        dict(series.trajectory_identity) == dict(expected_trajectory_identity),
        f"POSE_TRAJECTORY_IDENTITY_MISMATCH:{label}",
    )
    stamps = _strict_integer_ns(series.stamps_ns, f"pose:{label}")
    require(np.array_equal(stamps, plan.source_stamps_ns), f"POSE_TIMESTAMP_TOCTOU:{label}")
    positions = np.asarray(series.positions, dtype=float)
    quaternions = np.asarray(series.quaternions_xyzw, dtype=float)
    require(positions.shape == (len(stamps), 3), f"POSE_POSITION_SHAPE:{label}")
    require(quaternions.shape == (len(stamps), 4), f"POSE_QUATERNION_SHAPE:{label}")
    require(np.all(np.isfinite(positions)), f"POSE_POSITION_NONFINITE:{label}")
    require(np.all(np.isfinite(quaternions)), f"POSE_QUATERNION_NONFINITE:{label}")
    norms = np.linalg.norm(quaternions, axis=1)
    require(np.all(norms > 1e-12), f"POSE_QUATERNION_ZERO:{label}")
    return positions, quaternions / norms[:, None]


def validate_static_transform(transform: StaticFrameTransform, label: str) -> np.ndarray:
    require(transform.convention == "source_T_target", f"TRANSFORM_CONVENTION:{label}")
    require(bool(transform.source_frame) and bool(transform.target_frame), f"TRANSFORM_FRAME_EMPTY:{label}")
    matrix = np.asarray(transform.source_T_target, dtype=float)
    require(matrix.shape == (4, 4), f"TRANSFORM_SHAPE:{label}")
    require(np.all(np.isfinite(matrix)), f"TRANSFORM_NONFINITE:{label}")
    require(
        np.allclose(matrix[3], [0.0, 0.0, 0.0, 1.0], rtol=0.0, atol=1e-12),
        f"TRANSFORM_HOMOGENEOUS_ROW:{label}",
    )
    rotation = matrix[:3, :3]
    determinant = float(np.linalg.det(rotation))
    orthogonality = float(np.linalg.norm(rotation.T @ rotation - np.eye(3), ord="fro"))
    require(abs(determinant - 1.0) <= 1e-9, f"TRANSFORM_NOT_PROPER_ROTATION:{label}")
    require(orthogonality <= 1e-9, f"TRANSFORM_NOT_ORTHONORMAL:{label}")
    return matrix


def transform_world_source_to_target(
    positions: np.ndarray,
    quaternions_xyzw: np.ndarray,
    transform: StaticFrameTransform,
    *,
    label: str,
) -> tuple[np.ndarray, np.ndarray]:
    """Compose ``world_T_source @ source_T_target`` for all sample poses."""

    matrix = validate_static_transform(transform, label)
    positions = np.asarray(positions, dtype=float)
    quaternions = np.asarray(quaternions_xyzw, dtype=float)
    require(positions.ndim == 2 and positions.shape[1] == 3, f"TRANSFORM_POSITION_SHAPE:{label}")
    require(quaternions.shape == (len(positions), 4), f"TRANSFORM_QUATERNION_SHAPE:{label}")
    result_positions = np.empty_like(positions)
    result_quaternions = np.empty_like(quaternions)
    source_R_target = matrix[:3, :3]
    source_t_target = matrix[:3, 3]
    for index, (position, quaternion) in enumerate(zip(positions, quaternions)):
        world_R_source = quaternion_xyzw_to_rotation(quaternion)
        result_positions[index] = position + world_R_source @ source_t_target
        result_quaternions[index] = rotation_to_quaternion_xyzw(
            world_R_source @ source_R_target
        )
    return result_positions, result_quaternions


def _apply_plan_to_poses(
    plan: ResamplePlanNs,
    positions: np.ndarray,
    quaternions: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    output_positions = np.full((len(plan.grid_ns), 3), np.nan, dtype=float)
    output_quaternions = np.full((len(plan.grid_ns), 4), np.nan, dtype=float)
    for grid_index in np.flatnonzero(plan.valid):
        left = int(plan.left_indices[grid_index])
        right = int(plan.right_indices[grid_index])
        if left == right:
            output_positions[grid_index] = positions[left]
            output_quaternions[grid_index] = quaternions[left]
            continue
        alpha = (
            int(plan.alpha_numerators_ns[grid_index])
            / int(plan.alpha_denominators_ns[grid_index])
        )
        output_positions[grid_index] = (
            (1.0 - alpha) * positions[left] + alpha * positions[right]
        )
        output_quaternions[grid_index] = slerp_xyzw(
            quaternions[left], quaternions[right], alpha
        )
    return output_positions, output_quaternions


def fit_proper_fixed_scale_se3(source: np.ndarray, target: np.ndarray) -> ProperSE3:
    source = np.asarray(source, dtype=float)
    target = np.asarray(target, dtype=float)
    require(
        source.shape == target.shape and source.ndim == 2 and source.shape[1] == 3,
        "ALIGNMENT_POSITION_SHAPE",
    )
    require(len(source) >= 3, "ALIGNMENT_LT_3_POSES")
    require(np.all(np.isfinite(source)) and np.all(np.isfinite(target)), "ALIGNMENT_NONFINITE")
    source_centered = source - source.mean(axis=0)
    target_centered = target - target.mean(axis=0)
    source_rank = int(np.linalg.matrix_rank(source_centered))
    target_rank = int(np.linalg.matrix_rank(target_centered))
    if source_rank < 2 or target_rank < 2:
        raise AlignmentError(
            f"ALIGNMENT_RANK_DEFICIENT:SOURCE_{source_rank}:TARGET_{target_rank}"
        )
    u_matrix, _singular_values, vt_matrix = np.linalg.svd(
        source_centered.T @ target_centered
    )
    rotation = vt_matrix.T @ u_matrix.T
    if np.linalg.det(rotation) < 0.0:
        vt_matrix[-1, :] *= -1.0
        rotation = vt_matrix.T @ u_matrix.T
    determinant = float(np.linalg.det(rotation))
    orthogonality = float(np.linalg.norm(rotation.T @ rotation - np.eye(3), ord="fro"))
    if determinant <= 0.0 or abs(determinant - 1.0) > 1e-9:
        raise AlignmentError(f"ALIGNMENT_NOT_PROPER:DET_{determinant:.17g}")
    if orthogonality > 1e-9:
        raise AlignmentError(f"ALIGNMENT_NOT_ORTHONORMAL:{orthogonality:.17g}")
    translation = target.mean(axis=0) - rotation @ source.mean(axis=0)
    return ProperSE3(
        rotation=rotation,
        translation=translation,
        source_rank=source_rank,
        target_rank=target_rank,
        determinant=determinant,
        orthogonality_error_fro=orthogonality,
    )


def apply_proper_se3(alignment: ProperSE3, positions: np.ndarray) -> np.ndarray:
    require(alignment.scale == 1.0, "ALIGNMENT_SCALE_NOT_ONE")
    require(alignment.determinant > 0.0, "ALIGNMENT_DETERMINANT_NOT_POSITIVE")
    return (alignment.rotation @ np.asarray(positions, dtype=float).T).T + alignment.translation


def apply_proper_se3_full_poses(
    alignment: ProperSE3,
    positions: np.ndarray,
    quaternions_xyzw: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    """Apply one global left SE(3) alignment to full poses."""

    aligned_positions = apply_proper_se3(alignment, positions)
    quaternions = np.asarray(quaternions_xyzw, dtype=float)
    require(quaternions.shape == (len(aligned_positions), 4), "ALIGNMENT_QUATERNION_SHAPE")
    aligned_quaternions = np.empty_like(quaternions)
    for index, quaternion in enumerate(quaternions):
        aligned_quaternions[index] = rotation_to_quaternion_xyzw(
            alignment.rotation @ quaternion_xyzw_to_rotation(quaternion)
        )
    return aligned_positions, aligned_quaternions


def full_pose_se3_relative_translation_errors(
    reference_positions: np.ndarray,
    reference_quaternions_xyzw: np.ndarray,
    estimate_positions: np.ndarray,
    estimate_quaternions_xyzw: np.ndarray,
    pair_indices: np.ndarray,
) -> np.ndarray:
    """Standard translation RPE from ``A_ij^-1 B_ij`` full-pose SE(3)."""

    reference_positions = np.asarray(reference_positions, dtype=float)
    estimate_positions = np.asarray(estimate_positions, dtype=float)
    reference_quaternions = np.asarray(reference_quaternions_xyzw, dtype=float)
    estimate_quaternions = np.asarray(estimate_quaternions_xyzw, dtype=float)
    pairs = np.asarray(pair_indices, dtype=np.int64)
    require(
        reference_positions.shape == estimate_positions.shape
        and reference_positions.ndim == 2
        and reference_positions.shape[1] == 3,
        "FULL_POSE_RPE_POSITION_SHAPE",
    )
    require(
        reference_quaternions.shape == estimate_quaternions.shape
        == (len(reference_positions), 4),
        "FULL_POSE_RPE_QUATERNION_SHAPE",
    )
    require(pairs.ndim == 2 and pairs.shape[1] == 2, "FULL_POSE_RPE_PAIR_SHAPE")
    errors = np.empty(len(pairs), dtype=float)
    for row, (left, right) in enumerate(pairs):
        require(
            0 <= left < len(reference_positions) and 0 <= right < len(reference_positions),
            f"FULL_POSE_RPE_PAIR_RANGE:{row}",
        )
        reference_R_i = quaternion_xyzw_to_rotation(reference_quaternions[left])
        estimate_R_i = quaternion_xyzw_to_rotation(estimate_quaternions[left])
        reference_R_ij = reference_R_i.T @ quaternion_xyzw_to_rotation(
            reference_quaternions[right]
        )
        reference_t_ij = reference_R_i.T @ (
            reference_positions[right] - reference_positions[left]
        )
        estimate_t_ij = estimate_R_i.T @ (
            estimate_positions[right] - estimate_positions[left]
        )
        # E_ij = A_ij^-1 B_ij.  Rotation of A^-1 preserves the norm but is
        # applied explicitly to keep the full-pose SE(3) definition visible.
        error_translation = reference_R_ij.T @ (
            estimate_t_ij - reference_t_ij
        )
        errors[row] = float(np.linalg.norm(error_translation))
    require(np.all(np.isfinite(errors)), "FULL_POSE_RPE_NONFINITE")
    return errors


def _distribution(values: np.ndarray) -> dict[str, float]:
    require(len(values) > 0 and np.all(np.isfinite(values)), "METRIC_VALUES_INVALID")
    return {
        "rmse_m": float(np.sqrt(np.mean(values ** 2))),
        "median_m": float(np.median(values)),
        "max_m": float(np.max(values)),
    }


def prepare_common_full_pose_bundle(
    support: SupportDecision,
    pose_loader: Callable[[], Mapping[str, PoseSeriesNs]],
    execution_lock: ValidatedExecutionLock,
) -> CommonFullPoseBundle:
    require(support.gate_open, "COORDINATES_REQUESTED_BEFORE_SUPPORT_GATE")
    require(execution_lock._marker is _VALIDATED_LOCK_MARKER, "VALIDATED_EXECUTION_LOCK_REQUIRED")
    require(
        execution_lock.case_id == support.case.case_id,
        "POSE_BUNDLE_EXECUTION_LOCK_CASE_MISMATCH",
    )
    transforms = execution_lock.transforms
    require(set(transforms) == set(SOURCE_ORDER), "TRANSFORM_SOURCE_SET_MISMATCH")
    loaded = pose_loader()
    require(set(loaded) == set(SOURCE_ORDER), "POSE_SOURCE_SET_MISMATCH")
    resampled_positions: dict[str, np.ndarray] = {}
    resampled_quaternions: dict[str, np.ndarray] = {}
    transform_audit: dict[str, Any] = {}
    common_target_frame: str = ""
    for name in SOURCE_ORDER:
        positions, quaternions = _validate_pose_series(
            loaded[name],
            support.plans[name],
            name,
            execution_lock.trajectory_identities[name],
        )
        transform = transforms[name]
        if not common_target_frame:
            common_target_frame = transform.target_frame
        require(transform.target_frame == common_target_frame, f"COMMON_TARGET_FRAME_MISMATCH:{name}")
        # Frozen non-commuting order: interpolate source pose first, then
        # right-compose the lever-arm/static transform on each valid grid pose.
        grid_source_positions, grid_source_quaternions = _apply_plan_to_poses(
            support.plans[name], positions, quaternions
        )
        valid = support.plans[name].valid
        target_positions = np.full_like(grid_source_positions, np.nan)
        target_quaternions = np.full_like(grid_source_quaternions, np.nan)
        transformed_positions, transformed_quaternions = transform_world_source_to_target(
            grid_source_positions[valid],
            grid_source_quaternions[valid],
            transform,
            label=name,
        )
        target_positions[valid] = transformed_positions
        target_quaternions[valid] = transformed_quaternions
        resampled_positions[name] = target_positions
        resampled_quaternions[name] = target_quaternions
        matrix = np.asarray(transform.source_T_target, dtype=float)
        transform_audit[name] = {
            "serialized_pose_convention": "world_T_source",
            "static_transform_convention": "source_T_target",
            "analysis_pose_convention": "world_T_target",
            "source_frame": transform.source_frame,
            "target_frame": transform.target_frame,
            "source_T_target": matrix.tolist(),
            "rotation_determinant": float(np.linalg.det(matrix[:3, :3])),
            "operation_order": [
                "RESAMPLE_SOURCE_POSITION_LINEAR_AND_NORMALIZED_SHORTEST_SLERP",
                "RIGHT_COMPOSE_SOURCE_T_TARGET",
                "FIT_LEFT_PROPER_FIXED_SCALE_SE3_IN_TARGET",
                "METRICS_ON_ACCEPTED_JOINT_POPULATION",
            ],
        }

    frozen_positions: dict[str, np.ndarray] = {}
    frozen_quaternions: dict[str, np.ndarray] = {}
    for name in SOURCE_ORDER:
        frozen_positions[name] = np.array(resampled_positions[name], copy=True)
        frozen_quaternions[name] = np.array(resampled_quaternions[name], copy=True)
        frozen_positions[name].setflags(write=False)
        frozen_quaternions[name].setflags(write=False)
    frozen_grid = np.array(support.plans["reference"].grid_ns, copy=True)
    frozen_joint_mask = np.array(support.joint_mask, copy=True)
    frozen_segment_ids = np.array(support.segment_ids, copy=True)
    frozen_rpe_pairs = np.array(support.rpe_pair_indices, copy=True)
    for value in (
        frozen_grid,
        frozen_joint_mask,
        frozen_segment_ids,
        frozen_rpe_pairs,
    ):
        value.setflags(write=False)
    return CommonFullPoseBundle(
        case_id=support.case.case_id,
        execution_lock_value_sha256=execution_lock.value_sha256,
        grid_ns=frozen_grid,
        joint_mask=frozen_joint_mask,
        segment_ids=frozen_segment_ids,
        rpe_pair_indices=frozen_rpe_pairs,
        positions=MappingProxyType(frozen_positions),
        quaternions_xyzw=MappingProxyType(frozen_quaternions),
        transform_audit=MappingProxyType(transform_audit),
    )


def _coordinate_metrics(
    support: SupportDecision,
    bundle: CommonFullPoseBundle,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    require(support.gate_open, "METRICS_REQUESTED_BEFORE_SUPPORT_GATE")
    require(bundle.case_id == support.case.case_id, "METRIC_BUNDLE_CASE_MISMATCH")
    require(
        np.array_equal(bundle.grid_ns, support.plans["reference"].grid_ns)
        and np.array_equal(bundle.joint_mask, support.joint_mask)
        and np.array_equal(bundle.segment_ids, support.segment_ids)
        and np.array_equal(bundle.rpe_pair_indices, support.rpe_pair_indices),
        "METRIC_BUNDLE_SUPPORT_MISMATCH",
    )
    resampled_positions = bundle.positions
    resampled_quaternions = bundle.quaternions_xyzw
    transform_audit = dict(bundle.transform_audit)

    mask = support.joint_mask
    reference = resampled_positions["reference"][mask]
    alignments: dict[str, ProperSE3] = {}
    alignment_failures: dict[str, str] = {}
    for name in ESTIMATE_ORDER:
        try:
            alignments[name] = fit_proper_fixed_scale_se3(
                resampled_positions[name][mask], reference
            )
        except AlignmentError as error:
            alignment_failures[name] = error.code
    if alignment_failures:
        return (
            {},
            {
                "status": "NA_ALIGNMENT_GATE",
                "failures": alignment_failures,
                "successful_alignment_audits": {
                    name: alignment.audit() for name, alignment in alignments.items()
                },
            },
            transform_audit,
        )

    metrics: dict[str, Any] = {}
    alignment_audit = {
        "status": "PASS",
        "per_arm": {name: alignments[name].audit() for name in ESTIMATE_ORDER},
        "independent_alignment_per_arm": True,
        "fixed_scale": 1.0,
        "sim3_used": False,
    }
    reference_grid = resampled_positions["reference"]
    reference_quaternion_grid = resampled_quaternions["reference"]
    pairs = support.rpe_pair_indices
    for name in ESTIMATE_ORDER:
        aligned_common, aligned_common_quaternions = apply_proper_se3_full_poses(
            alignments[name],
            resampled_positions[name][mask],
            resampled_quaternions[name][mask],
        )
        aligned_grid = np.full_like(reference_grid, np.nan)
        aligned_quaternion_grid = np.full_like(reference_quaternion_grid, np.nan)
        aligned_grid[mask] = aligned_common
        aligned_quaternion_grid[mask] = aligned_common_quaternions
        ape_errors = np.linalg.norm(aligned_common - reference, axis=1)
        rpe_errors = full_pose_se3_relative_translation_errors(
            reference_grid,
            reference_quaternion_grid,
            aligned_grid,
            aligned_quaternion_grid,
            pairs,
        )
        metrics[name] = {
            "translation_ape": {**_distribution(ape_errors), "pose_count": len(ape_errors)},
            "translation_rpe_exact_1s": {
                **_distribution(rpe_errors),
                "pair_count": len(rpe_errors),
                "delta_ns": RPE_DELTA_NS,
                "semantics": "FULL_POSE_SE3_A_IJ_INVERSE_B_IJ_TRANSLATION_NORM",
            },
        }
    return metrics, alignment_audit, transform_audit


def _evaluate_case_with_artifacts(
    case_id: str,
    timestamps_by_source: Mapping[str, LockedTimestampSeriesNs],
    execution_lock: ValidatedExecutionLock,
    *,
    pose_loader: Callable[[], Mapping[str, PoseSeriesNs]] | None = None,
) -> tuple[dict[str, Any], SupportDecision | None, CommonFullPoseBundle | None]:
    """Evaluate once and retain non-serializable artifacts for the controller."""

    policy = case_policy(case_id)
    require(
        isinstance(execution_lock, ValidatedExecutionLock)
        and execution_lock._marker is _VALIDATED_LOCK_MARKER,
        "VALIDATED_EXECUTION_LOCK_REQUIRED",
    )
    require(execution_lock.case_id == case_id, "EXECUTION_LOCK_CASE_MISMATCH")
    if policy.structural_na_reasons:
        # The historical three-source support is a mathematical upper bound;
        # adding HFNet cannot repair these four cases.
        result = _structural_na_result(policy, execution_lock.runability_status)
        result["execution_lock_binding"] = {
            "value_sha256": execution_lock.value_sha256,
            "formal_verification_receipt": dict(
                execution_lock.verification_receipt_identity
            ),
        }
        return result, None, None

    if execution_lock.runability_status != "PASS":
        return {
            "schema_version": SCHEMA_VERSION,
            "case_id": case_id,
            "dataset": policy.dataset,
            "accuracy_status": "NA_HFNET_RUNABILITY_GATE",
            "support": {
                "phase": "RUNABILITY_RECEIPT_ONLY",
                "hfnet_runability_status": execution_lock.runability_status,
                "coordinates_loaded": False,
                "metrics_computed": False,
                "gate_open": False,
                "gate_failures": ["HFNET_RUNABILITY_NOT_PASS"],
            },
            "execution_lock_binding": {
                "value_sha256": execution_lock.value_sha256,
                "hfnet_runability_receipt": dict(
                    execution_lock.runability_receipt_identity
                ),
            },
            "claim_boundary": {
                "accuracy_numeric_authorized": False,
                "ranking_computed": False,
                "ranking_authorized": False,
                "sim3_used": False,
            },
        }, None, None

    require(
        set(timestamps_by_source) == set(SOURCE_ORDER),
        "LOCKED_TIMESTAMP_SOURCE_SET_MISMATCH",
    )
    plain_timestamps: dict[str, Sequence[int]] = {}
    for name in SOURCE_ORDER:
        source = timestamps_by_source[name]
        require(
            isinstance(source, LockedTimestampSeriesNs),
            f"LOCKED_TIMESTAMP_TYPE:{name}",
        )
        require(
            dict(source.trajectory_identity)
            == dict(execution_lock.trajectory_identities[name]),
            f"TIMESTAMP_TRAJECTORY_IDENTITY_MISMATCH:{name}",
        )
        plain_timestamps[name] = source.stamps_ns

    support = build_common_support(case_id, plain_timestamps, execution_lock.runability_status)
    result: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "case_id": case_id,
        "dataset": policy.dataset,
        "execution_lock_binding": {
            "value_sha256": execution_lock.value_sha256,
            "formal_verification_receipt": dict(
                execution_lock.verification_receipt_identity
            ),
            "hfnet_runability_receipt": dict(
                execution_lock.runability_receipt_identity
            ),
        },
        "accuracy_status": "PRIMARY_METRIC_GATE_OPEN" if support.gate_open else "NA_SUPPORT_GATE",
        "support": support.evidence(),
        "reference_disclosure": {
            "role": policy.reference_role,
            "is_independent_ground_truth": False,
            "native_reference_anchor_count": (
                policy.native_reference_anchor_count or None
            ),
            "common_grid_samples_are_independent_replicates": False,
            "aqualoc_native_anchor_sensitivity_required": (
                policy.dataset == "AQUALOC_ARCHAEOLOGY"
            ),
        },
        "claim_boundary": {
            "accuracy_numeric_authorized": False,
            "ranking_computed": False,
            "ranking_authorized": False,
            "significance_test_performed": False,
            "sim3_used": False,
        },
    }
    if not support.gate_open:
        return result, support, None
    require(pose_loader is not None, "POSE_LOADER_REQUIRED_AFTER_SUPPORT_GATE")
    bundle = prepare_common_full_pose_bundle(support, pose_loader, execution_lock)
    metrics, alignment_audit, transform_audit = _coordinate_metrics(
        support, bundle
    )
    result["support"]["coordinates_loaded"] = True
    result["frame_transform_audit"] = transform_audit
    result["alignment_audit"] = alignment_audit
    if alignment_audit["status"] != "PASS":
        result["accuracy_status"] = "NA_ALIGNMENT_GATE"
        result["claim_boundary"]["accuracy_numeric_authorized"] = False
        return result, support, bundle
    result["metrics"] = metrics
    result["accuracy_status"] = "PRIMARY_METRICS_COMPUTED_EVO_PENDING"
    result["evo_population_contract"] = evo_population_contract(support)
    result["independent_evo_pending"] = {
        "required": True,
        "status": "EVO_CROSSCHECK_PENDING",
        "version": EVO_VERSION,
        "evo_ape": dict(EVO_APE_IDENTITY),
        "evo_rpe": dict(EVO_RPE_IDENTITY),
        "alignment": "OWN_GLOBAL_SE3_-a_FIXED_SCALE_NO_-s",
        "maximum_absolute_rmse_disagreement_m": EVO_MAX_RMSE_DISAGREEMENT_M,
        "executed_by_this_scaffold": False,
    }
    result["support"]["metrics_computed"] = True
    result["claim_boundary"]["accuracy_numeric_authorized"] = False
    return result, support, bundle


def evaluate_case(
    case_id: str,
    timestamps_by_source: Mapping[str, LockedTimestampSeriesNs],
    execution_lock: ValidatedExecutionLock,
    *,
    pose_loader: Callable[[], Mapping[str, PoseSeriesNs]] | None = None,
) -> dict[str, Any]:
    """Return the public primary result through one formally verified lock."""

    result, _support, _bundle = _evaluate_case_with_artifacts(
        case_id,
        timestamps_by_source,
        execution_lock,
        pose_loader=pose_loader,
    )
    return result


def evaluate_case_for_controller(
    case_id: str,
    timestamps_by_source: Mapping[str, LockedTimestampSeriesNs],
    execution_lock: ValidatedExecutionLock,
    evo_output_root: Path,
    *,
    pose_loader: Callable[[], Mapping[str, PoseSeriesNs]] | None = None,
) -> tuple[dict[str, Any], EvoAdapterPlan | None]:
    """Return a public result plus an in-memory evo plan from the same load.

    Gate-closed, structural-NA, runability-failed, and alignment-failed cases
    return ``None`` for the plan.  No files are written and no subprocess is
    started here.
    """

    result, support, bundle = _evaluate_case_with_artifacts(
        case_id,
        timestamps_by_source,
        execution_lock,
        pose_loader=pose_loader,
    )
    if result.get("accuracy_status") != "PRIMARY_METRICS_COMPUTED_EVO_PENDING":
        return result, None
    require(support is not None and bundle is not None, "CONTROLLER_EVO_ARTIFACTS_MISSING")
    plan = plan_evo_adapter(support, bundle, evo_output_root)
    result["independent_evo_pending"]["plan_core_sha256"] = plan.document[
        "plan_core_sha256"
    ]
    return result, plan


def _identity_shape(value: Any, label: str) -> None:
    require(isinstance(value, Mapping), f"IDENTITY_NOT_OBJECT:{label}")
    require(set(value) == {"path", "size_bytes", "sha256"}, f"IDENTITY_KEYS:{label}")
    require(isinstance(value["path"], str) and Path(value["path"]).is_absolute(), f"IDENTITY_PATH:{label}")
    require(isinstance(value["size_bytes"], int) and value["size_bytes"] >= 0, f"IDENTITY_SIZE:{label}")
    digest = value["sha256"]
    require(
        isinstance(digest, str)
        and len(digest) == 64
        and all(character in "0123456789abcdef" for character in digest),
        f"IDENTITY_SHA256:{label}",
    )


def static_matrix_sha256(matrix: np.ndarray) -> str:
    values = np.asarray(matrix, dtype=float)
    require(values.shape == (4, 4), "STATIC_MATRIX_DIGEST_SHAPE")
    return hashlib.sha256(canonical_json_bytes(values.tolist())).hexdigest()


def _locked_static_matrix(value: Any, label: str) -> np.ndarray:
    require(isinstance(value, Mapping), f"LOCKED_MATRIX_NOT_OBJECT:{label}")
    require(set(value) == {"matrix", "matrix_sha256"}, f"LOCKED_MATRIX_KEYS:{label}")
    matrix = np.asarray(value.get("matrix"), dtype=float)
    validate_static_transform(
        StaticFrameTransform(label, label, matrix), f"frame_contract:{label}"
    )
    require(
        value.get("matrix_sha256") == static_matrix_sha256(matrix),
        f"LOCKED_MATRIX_DIGEST:{label}",
    )
    return matrix


def validate_future_execution_lock(
    lock: Mapping[str, Any],
    verification: FormalIdentityVerification | None = None,
) -> ValidatedExecutionLock:
    """Return an opaque metric token only after formal identity attestation."""

    require(
        isinstance(verification, FormalIdentityVerification),
        "FORMAL_IDENTITY_VERIFICATION_REQUIRED",
    )
    _identity_shape(
        verification.verification_receipt_identity,
        "formal_identity_verification_receipt",
    )
    lock_value_sha256 = hashlib.sha256(canonical_json_bytes(lock)).hexdigest()
    require(
        verification.execution_lock_value_sha256 == lock_value_sha256,
        "FORMAL_VERIFICATION_LOCK_VALUE_MISMATCH",
    )
    require(
        verification.execution_lock_file_identity_verified
        and verification.evaluator_self_identity_verified
        and verification.controller_self_identity_verified
        and verification.evidence_identities_verified
        and verification.pre_metric_toctou_verified,
        "FORMAL_IDENTITY_VERIFICATION_INCOMPLETE",
    )

    require(lock.get("schema_version") == ANALYSIS_LOCK_SCHEMA, "LOCK_SCHEMA")
    require(lock.get("status") == "LOCKED_BEFORE_ACCURACY", "LOCK_STATUS")
    policy = case_policy(lock.get("case_id"))
    require(lock.get("authority_hashes") == dict(FROZEN_AUTHORITY_HASHES), "LOCK_AUTHORITIES")
    expected_v2_authorities = json.loads(
        canonical_json_bytes(dict(V2_ROSTER_AUTHORITY_IDENTITIES)).decode("utf-8")
    )
    require(
        lock.get("v2_roster_authorities") == expected_v2_authorities,
        "LOCK_V2_ROSTER_AUTHORITY_IDENTITIES",
    )
    require(
        lock.get("analysis_grid_prefreeze") == dict(ANALYSIS_GRID_PREFREEZE_IDENTITY),
        "LOCK_ANALYSIS_GRID_PREFREEZE_IDENTITY",
    )
    require(
        lock.get("imported_pure_helpers")
        == {"trajectory_eval_core": dict(PURE_HELPER_IDENTITY)},
        "LOCK_PURE_HELPER_IDENTITY",
    )
    claims = lock.get("claims")
    require(
        isinstance(claims, Mapping)
        and claims.get("analysis_started") is False
        and claims.get("accuracy_measured") is False,
        "LOCK_CLAIMS_NOT_PRISTINE",
    )
    _identity_shape(lock.get("evaluator"), "evaluator")
    receipt = lock.get("hfnet_runability_receipt")
    require(isinstance(receipt, Mapping), "LOCK_HFNET_RECEIPT")
    _identity_shape(receipt.get("identity"), "hfnet_runability_receipt")
    runability_status = receipt.get("status")
    require(runability_status in ("PASS", "FAIL"), "LOCK_HFNET_RUNABILITY_STATUS")

    sources = lock.get("sources")
    locked_transforms: dict[str, StaticFrameTransform] = {}
    trajectory_identities: dict[str, Mapping[str, Any]] = {}
    if runability_status == "PASS" and not policy.structural_na_reasons:
        expected_frame = DATASET_FRAME_CONTRACTS[policy.dataset]
        _identity_shape(lock.get("frame_convention_seal"), "frame_convention_seal")
        frame_contract = lock.get("frame_contract")
        require(isinstance(frame_contract, Mapping), "LOCK_FRAME_CONTRACT")
        require(
            frame_contract.get("dataset") == policy.dataset
            and frame_contract.get("semantic_contract") == dict(expected_frame)
            and frame_contract.get("common_target_frame")
            == expected_frame["common_target_frame"]
            and frame_contract.get("per_source_pose_semantics_frozen") is True
            and frame_contract.get("static_transform_direction_tested") is True
            and frame_contract.get("interpolation_before_static_extrinsic") is True
            and frame_contract.get("target_before_alignment_fit") is True,
            "LOCK_FRAME_CONTRACT_INCOMPLETE",
        )
        expected_estimate_matrix = np.eye(4)
        if policy.dataset == "AQUALOC_ARCHAEOLOGY":
            expected_estimate_matrix = _locked_static_matrix(
                frame_contract.get("imu_T_camera"), "aqualoc_imu_T_camera"
            )
            camera_T_imu = _locked_static_matrix(
                frame_contract.get("camera_T_imu"), "aqualoc_camera_T_imu"
            )
            require(
                frame_contract.get("calibration_authority")
                == dict(AQUALOC_CALIBRATION_IDENTITY)
                and frame_contract.get("inverse_forbidden_as_estimate_bridge") is True,
                "LOCK_AQUALOC_CALIBRATION_AUTHORITY",
            )
            require(
                np.allclose(
                    expected_estimate_matrix,
                    np.asarray(AQUALOC_IMU_T_CAMERA, dtype=float),
                    rtol=0.0,
                    atol=AQUALOC_FRAME_MATRIX_ATOL,
                )
                and np.allclose(
                    camera_T_imu,
                    np.asarray(AQUALOC_CAMERA_T_IMU, dtype=float),
                    rtol=0.0,
                    atol=AQUALOC_FRAME_MATRIX_ATOL,
                ),
                "LOCK_AQUALOC_FROZEN_TRANSFORM_VALUE",
            )
            require(
                np.allclose(
                    expected_estimate_matrix @ camera_T_imu,
                    np.eye(4),
                    rtol=0.0,
                    atol=AQUALOC_FRAME_MATRIX_ATOL,
                )
                and np.allclose(
                    camera_T_imu @ expected_estimate_matrix,
                    np.eye(4),
                    rtol=0.0,
                    atol=AQUALOC_FRAME_MATRIX_ATOL,
                ),
                "LOCK_AQUALOC_INVERSE_CLOSURE",
            )
        if policy.dataset == "CIRS":
            require(
                frame_contract.get("published_common_vehicle_body_verified") is True
                and frame_contract.get("camera_transform_used_as_body_transform") is False
                and frame_contract.get("calibration_representation")
                == "FULL_PRECISION_ORIGINAL_TF_PRIMARY"
                and frame_contract.get("canonical_zero_snapping")
                == "DISPLAY_ONLY_NOT_NUMERIC"
                and frame_contract.get("original_quaternion_sealed") is True
                and frame_contract.get(
                    "historical_online_camera_extrinsic_ignored_for_body_bridge"
                )
                is True
                and frame_contract.get("evidence_sha256")
                == dict(CIRS_FRAME_EVIDENCE_SHA256),
                "LOCK_CIRS_BODY_FRAME_ADJUDICATION",
            )
            vehicle_T_imu = _locked_static_matrix(
                frame_contract.get("vehicle_T_imu"), "cirs_vehicle_T_imu"
            )
            expected_estimate_matrix = _locked_static_matrix(
                frame_contract.get("imu_T_vehicle"), "cirs_imu_T_vehicle"
            )
            require(
                np.allclose(
                    vehicle_T_imu,
                    np.asarray(CIRS_VEHICLE_T_IMU, dtype=float),
                    rtol=0.0,
                    atol=CIRS_FRAME_MATRIX_ATOL,
                )
                and np.allclose(
                    expected_estimate_matrix,
                    np.asarray(CIRS_IMU_T_VEHICLE, dtype=float),
                    rtol=0.0,
                    atol=CIRS_FRAME_MATRIX_ATOL,
                ),
                "LOCK_CIRS_FROZEN_TRANSFORM_VALUE",
            )
            require(
                np.allclose(
                    vehicle_T_imu @ expected_estimate_matrix,
                    np.eye(4),
                    rtol=0.0,
                    atol=CIRS_FRAME_MATRIX_ATOL,
                )
                and np.allclose(
                    expected_estimate_matrix @ vehicle_T_imu,
                    np.eye(4),
                    rtol=0.0,
                    atol=CIRS_FRAME_MATRIX_ATOL,
                ),
                "LOCK_CIRS_VEHICLE_IMU_INVERSE",
            )
        require(isinstance(sources, Mapping) and set(sources) == set(SOURCE_ORDER), "LOCK_SOURCE_SET")
        target_frames: set[str] = set()
        for name in SOURCE_ORDER:
            source = sources[name]
            require(isinstance(source, Mapping), f"LOCK_SOURCE_NOT_OBJECT:{name}")
            _identity_shape(source.get("trajectory"), f"trajectory:{name}")
            trajectory_identities[name] = dict(source["trajectory"])
            timestamp = source.get("timestamp_contract")
            require(
                isinstance(timestamp, Mapping)
                and timestamp.get("unit") == "integer_nanoseconds"
                and timestamp.get("offset_ns") == 0
                and timestamp.get("nearest_association") is False
                and timestamp.get("extrapolation") is False,
                f"LOCK_TIMESTAMP_CONTRACT:{name}",
            )
            if name == "hfnet":
                require(
                    timestamp.get("stock_epoch_bridge_max_absolute_delta_ns")
                    == HFNET_CANONICALIZATION_MAX_DELTA_NS
                    and timestamp.get("bridge_mapping")
                    == "BIJECTIVE_UNIQUE_SOURCE_CAMERA_HEADER_REPLACEMENT"
                    and timestamp.get("source_header_reuse") is False,
                    "LOCK_HFNET_TIMESTAMP_BRIDGE",
                )
                _identity_shape(
                    timestamp.get("bridge_receipt"), "hfnet_timestamp_bridge_receipt"
                )
            pose = source.get("pose_convention")
            require(isinstance(pose, Mapping), f"LOCK_POSE_CONVENTION:{name}")
            require(pose.get("serialized") == "world_T_source", f"LOCK_SERIALIZED_POSE:{name}")
            require(pose.get("analysis") == "world_T_target", f"LOCK_ANALYSIS_POSE:{name}")
            serialized_order = pose.get("serialized_quaternion_order")
            required_serialized_order = (
                "wxyz" if name in ("learned_plus_klt", "klt") else "xyzw"
            )
            expected_conversion = (
                "IDENTITY_LOSSLESS"
                if serialized_order == "xyzw"
                else "LOSSLESS_PERMUTATION_WXYZ_TO_XYZW"
            )
            require(
                serialized_order == required_serialized_order
                and pose.get("analysis_quaternion_order") == "xyzw"
                and pose.get("quaternion_conversion") == expected_conversion,
                f"LOCK_QUATERNION_ORDER:{name}",
            )
            transform = pose.get("static_transform")
            require(isinstance(transform, Mapping), f"LOCK_STATIC_TRANSFORM:{name}")
            _identity_shape(transform.get("identity"), f"static_transform:{name}")
            static = StaticFrameTransform(
                source_frame=transform.get("source_frame"),
                target_frame=transform.get("target_frame"),
                source_T_target=np.asarray(transform.get("source_T_target"), dtype=float),
                convention=transform.get("convention"),
            )
            actual_matrix = validate_static_transform(static, f"lock:{name}")
            locked_transforms[name] = static
            expected_source_frame = (
                expected_frame["reference_source_frame"]
                if name == "reference"
                else expected_frame["estimate_source_frame"]
            )
            expected_transform_semantics = (
                expected_frame["reference_transform"]
                if name == "reference"
                else expected_frame["estimate_transform"]
            )
            require(
                static.source_frame == expected_source_frame,
                f"LOCK_SOURCE_FRAME_SEMANTICS:{name}",
            )
            require(
                static.target_frame == expected_frame["common_target_frame"],
                f"LOCK_TARGET_FRAME_SEMANTICS:{name}",
            )
            require(
                transform.get("semantic") == expected_transform_semantics,
                f"LOCK_STATIC_TRANSFORM_SEMANTICS:{name}",
            )
            expected_matrix = np.eye(4) if name == "reference" else expected_estimate_matrix
            matrix_atol = (
                CIRS_FRAME_MATRIX_ATOL if policy.dataset == "CIRS" else 1e-12
            )
            require(
                np.allclose(actual_matrix, expected_matrix, rtol=0.0, atol=matrix_atol),
                f"LOCK_STATIC_TRANSFORM_VALUE:{name}",
            )
            target_frames.add(static.target_frame)
        require(len(target_frames) == 1, "LOCK_COMMON_TARGET_FRAME_MISMATCH")
        require(
            next(iter(target_frames)) == frame_contract.get("common_target_frame"),
            "LOCK_FRAME_CONTRACT_TARGET_MISMATCH",
        )

    evo = lock.get("evo_verification")
    require(isinstance(evo, Mapping), "LOCK_EVO_NOT_OBJECT")
    _identity_shape(evo.get("evo_ape"), "evo_ape")
    _identity_shape(evo.get("evo_rpe"), "evo_rpe")
    require(evo.get("evo_ape") == dict(EVO_APE_IDENTITY), "LOCK_EVO_APE_IDENTITY")
    require(evo.get("evo_rpe") == dict(EVO_RPE_IDENTITY), "LOCK_EVO_RPE_IDENTITY")
    _identity_shape(evo.get("environment_seal"), "evo_environment_seal")
    environment = evo.get("environment_contract")
    require(
        environment == dict(EVO_ENVIRONMENT_CONTRACT),
        "LOCK_EVO_ENVIRONMENT_CONTRACT",
    )
    require(evo.get("version") == EVO_VERSION, "LOCK_EVO_VERSION")
    require(evo.get("alignment") == "OWN_GLOBAL_SE3_-a_FIXED_SCALE_1", "LOCK_EVO_ALIGNMENT")
    require(evo.get("use_scale") is False, "LOCK_EVO_SIM3_FORBIDDEN")
    require(evo.get("scale_flag") is None, "LOCK_EVO_SCALE_FLAG_FORBIDDEN")
    require(
        evo.get("timestamp_basis") == "relative_zero_from_authoritative_integer_ns",
        "LOCK_EVO_TIMESTAMP_BASIS",
    )
    require(
        evo.get("population_binding")
        == "COUNT_AND_ORDERED_INTEGER_NS_LIST_SHA256",
        "LOCK_EVO_POPULATION_BINDING",
    )
    require(
        evo.get("maximum_absolute_rmse_disagreement_m")
        == EVO_MAX_RMSE_DISAGREEMENT_M,
        "LOCK_EVO_RMSE_TOLERANCE",
    )

    sensitivity = lock.get("native_anchor_sensitivity")
    if policy.dataset == "AQUALOC_ARCHAEOLOGY" and policy.native_reference_anchor_count:
        require(isinstance(sensitivity, Mapping), "LOCK_NATIVE_SENSITIVITY_MISSING")
        require(
            sensitivity.get("required") is True
            and sensitivity.get("descriptive_only") is True
            and sensitivity.get("run_only_after_primary_gate") is True
            and sensitivity.get("can_reopen_primary_gate") is False
            and sensitivity.get("expected_native_anchor_count")
            == policy.native_reference_anchor_count,
            "LOCK_NATIVE_SENSITIVITY_CONTRACT",
        )
        _identity_shape(
            sensitivity.get("native_reference"), "native_anchor_reference"
        )
    frozen_transforms: dict[str, StaticFrameTransform] = {}
    for name, transform in locked_transforms.items():
        matrix = np.array(transform.source_T_target, dtype=float, copy=True)
        matrix.setflags(write=False)
        frozen_transforms[name] = StaticFrameTransform(
            source_frame=transform.source_frame,
            target_frame=transform.target_frame,
            source_T_target=matrix,
            convention=transform.convention,
        )
    return ValidatedExecutionLock(
        case_id=policy.case_id,
        value_sha256=lock_value_sha256,
        runability_status=runability_status,
        runability_receipt_identity=MappingProxyType(dict(receipt["identity"])),
        trajectory_identities=MappingProxyType(
            {
                name: MappingProxyType(dict(value))
                for name, value in trajectory_identities.items()
            }
        ),
        transforms=MappingProxyType(frozen_transforms),
        verification_receipt_identity=MappingProxyType(
            dict(verification.verification_receipt_identity)
        ),
        _marker=_VALIDATED_LOCK_MARKER,
    )


def _path_absent_no_follow(path: Path) -> bool:
    try:
        os.lstat(str(path))
    except FileNotFoundError:
        return True
    return False


def dry_run_preflight(
    case_id: str,
    execution_lock: ValidatedExecutionLock,
    output_dir: Path,
    process_claim: Path,
    terminal_receipt: Path,
) -> dict[str, Any]:
    """Read-only preflight for a later FUSE-safe exactly-once controller."""

    policy = case_policy(case_id)
    require(
        isinstance(execution_lock, ValidatedExecutionLock)
        and execution_lock._marker is _VALIDATED_LOCK_MARKER,
        "PREFLIGHT_VALIDATED_LOCK_REQUIRED",
    )
    require(execution_lock.case_id == case_id, "PREFLIGHT_CASE_LOCK_MISMATCH")
    raw_paths = (output_dir, process_claim, terminal_receipt)
    for label, path in zip(("output", "claim", "terminal"), raw_paths):
        require(path.is_absolute(), f"PREFLIGHT_PATH_NOT_ABSOLUTE:{label}")
        require(
            _path_absent_no_follow(path),
            f"PREFLIGHT_DESTINATION_EXISTS:{label}",
        )
    paths = tuple(path.resolve(strict=False) for path in raw_paths)
    for label, path in zip(("output", "claim", "terminal"), paths):
        require(_path_absent_no_follow(path), f"PREFLIGHT_DESTINATION_EXISTS:{label}")
    require(len({str(path) for path in paths}) == 3, "PREFLIGHT_DESTINATIONS_NOT_DISTINCT")
    return {
        "schema_version": SCHEMA_VERSION,
        "status": "DRY_RUN_READY",
        "case_id": case_id,
        "structural_na": bool(policy.structural_na_reasons),
        "runability_status": execution_lock.runability_status,
        "destinations_absent": True,
        "scientific_inputs_opened": False,
        "accuracy_computed": False,
        "claim_created": False,
        "publication_strategy_required": (
            "MKDIR_RESERVATION_THEN_TEMP_FSYNC_HARDLINK_NOREPLACE_AND_DIRECTORY_FSYNC"
        ),
        "retry_policy_required": "EXACTLY_ONCE_NO_RETRY_AFTER_CLAIM",
        "future_outputs": {
            "output_dir": str(paths[0]),
            "process_claim": str(paths[1]),
            "terminal_receipt": str(paths[2]),
        },
    }


def describe_cases(case_id: str | None = None) -> dict[str, Any]:
    selected = [case_policy(case_id)] if case_id else list(_CASE_SEQUENCE)
    return {
        "schema_version": SCHEMA_VERSION,
        "status": "OUTCOME_BLIND_SCAFFOLD_ONLY",
        "real_accuracy_execution_available": False,
        "frozen_case_order": [policy.case_id for policy in selected],
        "cases": [
            {
                "case_id": policy.case_id,
                "dataset": policy.dataset,
                "grid_anchor_ns": policy.score_start_header_ns,
                "last_score_camera_header_ns": policy.score_last_header_ns,
                "grid_step_ns": GRID_STEP_NS,
                "grid_count": policy.expected_grid_count,
                "reference_max_two_sided_gap_ns": policy.reference_max_gap_ns,
                "estimate_max_two_sided_gap_ns": policy.estimate_max_gap_ns,
                "structural_na_reasons": list(policy.structural_na_reasons),
                "native_reference_anchor_count": policy.native_reference_anchor_count or None,
                "frame_semantics": dict(DATASET_FRAME_CONTRACTS[policy.dataset]),
            }
            for policy in selected
        ],
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    describe = subparsers.add_parser("describe", help="print the frozen case table")
    describe.add_argument("--case-id", choices=tuple(CASE_TABLE))
    preflight = subparsers.add_parser("dry-run", help="validate a future lock without analysis")
    preflight.add_argument("--case-id", required=True, choices=tuple(CASE_TABLE))
    preflight.add_argument("--execution-lock", required=True, type=Path)
    preflight.add_argument("--formal-verification", required=True, type=Path)
    preflight.add_argument("--output-dir", required=True, type=Path)
    preflight.add_argument("--process-claim", required=True, type=Path)
    preflight.add_argument("--terminal-receipt", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        if args.command == "describe":
            result = describe_cases(args.case_id)
        else:
            raw = args.execution_lock.read_bytes()
            lock_document = json.loads(raw.decode("utf-8"))
            require(raw == canonical_json_bytes(lock_document), "EXECUTION_LOCK_NOT_CANONICAL_JSON")
            verification_raw = args.formal_verification.read_bytes()
            verification_document = json.loads(verification_raw.decode("utf-8"))
            require(
                verification_raw == canonical_json_bytes(verification_document),
                "FORMAL_VERIFICATION_NOT_CANONICAL_JSON",
            )
            require(
                set(verification_document)
                == {
                    "verification_receipt_identity",
                    "execution_lock_value_sha256",
                    "execution_lock_file_identity_verified",
                    "evaluator_self_identity_verified",
                    "controller_self_identity_verified",
                    "evidence_identities_verified",
                    "pre_metric_toctou_verified",
                },
                "FORMAL_VERIFICATION_KEYS",
            )
            execution_lock = validate_future_execution_lock(
                lock_document,
                FormalIdentityVerification(**verification_document),
            )
            result = dry_run_preflight(
                args.case_id,
                execution_lock,
                args.output_dir,
                args.process_claim,
                args.terminal_receipt,
            )
        sys.stdout.buffer.write(canonical_json_bytes(result))
        return 0
    except (ContractError, OSError, ValueError, TypeError, json.JSONDecodeError) as error:
        code = error.code if isinstance(error, ContractError) else f"{type(error).__name__}:{error}"
        sys.stdout.buffer.write(
            canonical_json_bytes(
                {
                    "schema_version": SCHEMA_VERSION,
                    "status": "PREFLIGHT_BLOCKED",
                    "error": code,
                    "accuracy_computed": False,
                    "claim_created": False,
                }
            )
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
