#!/usr/bin/env python3
"""One-shot HFNet A02 4500..7200 result-informed extension supervisor.

The run always replays global camera 4500 onward.  It cannot load an atlas,
change a scientific threshold, retry, or extend to 8100.  ``preflight`` is
read-only; ``freeze`` creates only the unique run contract; ``run`` may start
the frozen headless ELF exactly once after both contracts and all inputs pass.
"""

from __future__ import annotations

import argparse
import bisect
from dataclasses import dataclass, field, replace
from decimal import Decimal, InvalidOperation
import hashlib
import json
import math
import os
from pathlib import Path
import stat
import sys
from typing import Any, Callable, Mapping, Optional, Sequence

from scripts import a02_hfnet_result_informed_extension_v1 as profile
from scripts import export_aqualoc_a02_shared_4500_7200_result_informed_v1 as shared
from scripts import run_hfnet_slam_a02_full901_headless_v3 as v3
from scripts import run_hfnet_slam_a02_long1801_headless_v4 as v4


SCHEMA = "aqua-fe-hfnet-slam-a02-4500-7200-result-informed-contract-v5"
PROFILE_SCHEMA = "aqua-fe-hfnet-slam-a02-4500-7200-result-informed-profile-v5"
RESULT_SCHEMA = "aqua-fe-hfnet-slam-a02-4500-7200-result-informed-result-v5"
ROLE = profile.ROLE
RC_OK, RC_FAILED, RC_BLOCKED = 0, 1, 2

MATERIALIZER = profile.ROOT / "scripts/materialize_aqualoc_a02_4500_7200_result_informed_v1.py"
SHARED_EXPORTER = profile.ROOT / "scripts/export_aqualoc_a02_shared_4500_7200_result_informed_v1.py"
PROFILE_MODULE = profile.ROOT / "scripts/a02_hfnet_result_informed_extension_v1.py"

EXPECTED_CAMERA_COUNT = profile.FEED_COUNT
EXPECTED_IMU_COUNT = profile.HFNET_INNER_IMU_COUNT
EXPECTED_REFERENCE_COUNT = profile.SCORE_REFERENCE_COUNT
MIN_TRAJECTORY_POSES = 30
MIN_TRAJECTORY_SCORE_POSES = 30
MIN_TRAJECTORY_SCORE_SPAN_S = 10.0
MIN_KEYFRAMES = 2
MIN_SCORE_KEYFRAMES = 1
MAX_HFNET_CAMERA_ASSOCIATION_ERROR_NS = 256


class ContractError(RuntimeError):
    pass


@dataclass(frozen=True)
class Spec:
    official_root: Path = v3.DEFAULT_OFFICIAL_ROOT
    binary: Path = v3.DEFAULT_BINARY
    build_manifest: Path = v3.DEFAULT_BUILD_MANIFEST
    official_library: Path = v3.DEFAULT_LIBRARY
    official_entry: Path = v3.DEFAULT_ENTRY_SOURCE
    headless_source: Path = v3.DEFAULT_HARNESS_SOURCE
    config: Path = v3.DEFAULT_CONFIG
    onnx: Path = v3.DEFAULT_ONNX
    cache_seed: Path = v3.DEFAULT_CACHE_SEED
    shared_root: Path = profile.NEW_SHARED_ROOT
    result: Path = profile.NEW_RESULT
    evidence: Path = profile.NEW_EVIDENCE
    contract: Path = profile.NEW_RUN_CONTRACT
    bridge_output: Path = profile.NEW_BRIDGE_OUTPUT
    static_freeze: Path = profile.STATIC_FREEZE
    expected: Mapping[str, Mapping[str, object]] = field(default_factory=lambda: v3.EXPECTED)
    timeout_seconds: int = v3.prior.TIMEOUT_SECONDS

    @property
    def sequence(self) -> Path:
        return self.shared_root / "hfnet"


DEFAULT_SPEC = Spec()
Probe = Callable[[Sequence[str], Optional[Mapping[str, str]], Optional[Path]], v3.CommandResult]
Execute = Callable[[Sequence[str], Mapping[str, str], Optional[Path], int], v3.CommandResult]


def canonical_json(value: object) -> str:
    return json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False) + "\n"


def absolute(path: Path) -> Path:
    return path.expanduser().resolve(strict=False)


def absent(path: Path) -> bool:
    return not path.exists() and not path.is_symlink()


def identity(path: Path) -> dict[str, object]:
    try:
        return v3.identity(path)
    except v3.ContractError as error:
        raise ContractError(str(error)) from error


def audit_static_freeze(spec: Spec) -> dict[str, Any]:
    expected_spec_paths = {
        "shared_root": profile.NEW_SHARED_ROOT,
        "result": profile.NEW_RESULT,
        "evidence": profile.NEW_EVIDENCE,
        "contract": profile.NEW_RUN_CONTRACT,
        "bridge_output": profile.NEW_BRIDGE_OUTPUT,
        "static_freeze": profile.STATIC_FREEZE,
    }
    if any(absolute(getattr(spec, key)) != absolute(expected) for key, expected in expected_spec_paths.items()):
        raise ContractError("FROZEN_SPEC_PATH_OVERRIDE_FORBIDDEN")
    freeze_identity = identity(spec.static_freeze)
    payload = spec.static_freeze.read_bytes()
    try:
        value = json.loads(payload.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as error:
        raise ContractError("STATIC_FREEZE_INVALID_JSON") from error
    if payload != profile.canonical_json_bytes(value):
        raise ContractError("STATIC_FREEZE_NOT_CANONICAL_PRETTY_JSON")
    expected_top_level_keys = {
        "authoritative_commands", "code_identities", "design",
        "disk_feasibility_snapshot", "execution_environment",
        "feasibility_observations_not_success_guarantees", "paths",
        "preregistration", "prior_observation", "reserved_path_initial_state",
        "schema_version", "scientific_role", "source_identities", "status",
    }
    if set(value) != expected_top_level_keys:
        raise ContractError("STATIC_FREEZE_TOP_LEVEL_KEYSET_MISMATCH")
    if value.get("schema_version") != "aqua-fe-a02-hfnet-result-informed-extension-freeze-v1" or value.get("status") != "FROZEN_NO_EXTENSION_ARTIFACTS_OR_SLAM_STARTED" or value.get("scientific_role") != ROLE:
        raise ContractError("STATIC_FREEZE_SCHEMA_STATUS_OR_ROLE_MISMATCH")
    design = value.get("design")
    if not isinstance(design, Mapping):
        raise ContractError("STATIC_FREEZE_DESIGN_INVALID")
    expected_design = {
        "feed_global_camera_indices_inclusive": [profile.FEED_FIRST, profile.FEED_LAST],
        "feed_camera_count": profile.FEED_COUNT,
        "same_prefix_global_camera_indices_inclusive": [profile.FEED_FIRST, profile.PRIOR_FEED_LAST],
        "new_global_camera_indices_inclusive": [profile.PRIOR_FEED_LAST + 1, profile.FEED_LAST],
        "new_camera_count": profile.NEW_CAMERA_COUNT,
        "score_global_camera_indices_inclusive": [profile.SCORE_FIRST, profile.SCORE_LAST],
        "score_reference_pose_count": profile.SCORE_REFERENCE_COUNT,
        "score_evaluation_grid_count": profile.SCORE_EVALUATION_GRID_COUNT,
        "score_span_ns": profile.SCORE_SPAN_NS,
        "start_from_scratch": True,
        "atlas_resume": False,
        "algorithm_or_threshold_modified": False,
        "retry": False,
        "failure_triggered_extension_to_8100": False,
        "maximum_source_window_export_attempts": 1,
        "maximum_shared_export_attempts": 1,
    }
    if dict(design) != expected_design:
        raise ContractError("STATIC_FREEZE_DESIGN_MISMATCH")
    expected_paths = {
        "window_bag": str(absolute(profile.NEW_WINDOW_BAG)),
        "window_manifest": str(absolute(profile.NEW_WINDOW_MANIFEST)),
        "window_attempt": str(absolute(profile.NEW_WINDOW_ATTEMPT)),
        "shared_root": str(absolute(profile.NEW_SHARED_ROOT)),
        "shared_attempt": str(absolute(profile.NEW_SHARED_ATTEMPT)),
        "run_contract": str(absolute(profile.NEW_RUN_CONTRACT)),
        "result": str(absolute(profile.NEW_RESULT)),
        "evidence": str(absolute(profile.NEW_EVIDENCE)),
        "bridge_output": str(absolute(profile.NEW_BRIDGE_OUTPUT)),
    }
    paths = value.get("paths")
    if not isinstance(paths, Mapping) or dict(paths) != expected_paths:
        raise ContractError("STATIC_FREEZE_PATH_MISMATCH")
    source = value.get("source_identities")
    if not isinstance(source, Mapping):
        raise ContractError("STATIC_FREEZE_SOURCE_IDENTITIES_INVALID")
    current_source = profile.expected_static_source_identities()
    if dict(source) != current_source:
        raise ContractError("STATIC_FREEZE_SOURCE_IDENTITY_MISMATCH")
    code = value.get("code_identities")
    expected_code_paths = {
        "prior_hfnet_runner_v4": profile.ROOT / "scripts/run_hfnet_slam_a02_long1801_headless_v4.py",
        "prior_shared_exporter_v1": profile.ROOT / "scripts/export_aqualoc_a02_shared_4500_6300_v1.py",
        "result_informed_materializer": MATERIALIZER,
        "result_informed_profile": PROFILE_MODULE,
        "result_informed_shared_exporter": SHARED_EXPORTER,
        "result_informed_synthetic_tests": profile.ROOT / "scripts/tests/test_a02_hfnet_result_informed_extension_v1.py",
        "result_informed_v5_runner": Path(__file__),
    }
    if not isinstance(code, Mapping) or set(code) != set(expected_code_paths):
        raise ContractError("STATIC_FREEZE_CODE_IDENTITIES_INVALID")
    for label, expected_path in expected_code_paths.items():
        raw = code[label]
        if not isinstance(raw, Mapping) or not isinstance(raw.get("path"), str):
            raise ContractError(f"STATIC_FREEZE_CODE_ROW_INVALID:{label}")
        if absolute(Path(str(raw["path"]))) != absolute(expected_path) or identity(expected_path) != dict(raw):
            raise ContractError(f"STATIC_FREEZE_CODE_IDENTITY_MISMATCH:{label}")
    expected_execution_environment = {
        "clear_parent_environment": True,
        "cwd": str(profile.ROOT),
        "interpreter": profile.SEALED_PYTHON,
        "required_environment": profile.REQUIRED_ENVIRONMENT,
        "required_pycache_prefix_initial_state": "ABSENT",
    }
    if value.get("execution_environment") != expected_execution_environment:
        raise ContractError("STATIC_FREEZE_EXECUTION_ENVIRONMENT_MISMATCH")
    if value.get("authoritative_commands") != profile.authoritative_commands():
        raise ContractError("STATIC_FREEZE_AUTHORITATIVE_COMMANDS_MISMATCH")
    expected_reservations = {
        "all_absent": True,
        "bridge_manifest_absent": True,
        "bridge_output_absent": True,
        "evidence_absent": True,
        "observed_at_local_date": "2026-08-12",
        "result_absent": True,
        "run_contract_absent": True,
        "shared_root_absent": True,
        "shared_attempt_absent": True,
        "window_bag_absent": True,
        "window_manifest_absent": True,
        "window_attempt_absent": True,
    }
    if value.get("reserved_path_initial_state") != expected_reservations:
        raise ContractError("STATIC_FREEZE_INITIAL_RESERVATION_RECORD_MISMATCH")
    expected_disk = {
        "available_bytes_mnt_data": 12_906_319_872,
        "estimated_new_4500_7200_bag_bytes": 673_460_138,
        "estimated_new_png_physical_bytes_when_prefix_hardlinked": 212_881_732,
        "estimated_run_local_model_and_cache_bytes": 133_091_921,
        "policy": "old 1801 PNG payloads must be hard-linked or byte-copied only after exact audit; no duplicate AnyFeature descriptor tree is authorized by this freeze",
    }
    if value.get("disk_feasibility_snapshot") != expected_disk:
        raise ContractError("STATIC_FREEZE_DISK_FEASIBILITY_RECORD_MISMATCH")
    expected_feasibility = {
        "score_6300_7200_accumulated_gt_rotation_deg": 125.916,
        "score_6300_7200_gt_path_length_m": 4.4028,
        "score_6300_7200_gt_pose_count": 46,
        "score_6300_7200_span_s": 44.989672064,
        "score_first_approximately_10s_gt_path_length_m": 1.1451,
        "score_first_approximately_10s_gt_rotation_deg": 8.914,
        "warning": "the final prior map had not emitted a final-map Imu initialized marker and followed 13 resets; data support does not guarantee HFNet usability",
    }
    if value.get("feasibility_observations_not_success_guarantees") != expected_feasibility:
        raise ContractError("STATIC_FREEZE_FEASIBILITY_OBSERVATION_MISMATCH")
    expected_preregistration = {
        "path": str(profile.ROOT / "papers/2026-08-12--a02-hfnet-result-informed-extension-4500-7200-v1.md"),
        "purpose": "transparent post-failure exploratory continuation; cannot amend or rescue the prior confirmatory comparison",
    }
    if value.get("preregistration") != expected_preregistration:
        raise ContractError("STATIC_FREEZE_PREREGISTRATION_BINDING_MISMATCH")
    expected_prior_observation = {
        "associated_first_global_camera_index": 6279,
        "associated_last_global_camera_index": 6300,
        "final_keyframe_count": 6,
        "interpretation": "used_only_to motivate a separately frozen exploratory continuation; not confirmatory and not a retry",
        "raw_child_return_code": 0,
        "reset_due_to_insufficient_motion_count": 13,
        "result_evaluable": False,
        "result_return_code": 1,
        "result_status": "HEADLESS_RUN_FAILED_OR_UNUSABLE",
        "score_pose_count": 22,
        "score_span_seconds": 1.051619328,
    }
    if value.get("prior_observation") != expected_prior_observation:
        raise ContractError("STATIC_FREEZE_PRIOR_OBSERVATION_MISMATCH")
    old = json.loads(profile.OLD_HFNET_RESULT.read_text(encoding="utf-8"))
    trajectory = old.get("gate", {}).get("trajectory", {})
    if old.get("schema_version") != "aqua-fe-hfnet-slam-a02-long1801-headless-result-v4" or old.get("status") != "HEADLESS_RUN_FAILED_OR_UNUSABLE" or old.get("return_code") != 1 or old.get("evaluable") is not False or old.get("execution", {}).get("raw_returncode") != 0 or trajectory.get("gate_pass") is not False or trajectory.get("score_pose_count") != 22 or trajectory.get("associated_first_relative_camera_index") != 1779 or trajectory.get("associated_last_relative_camera_index") != 1800:
        raise ContractError("PRIOR_HFNET_UNUSABLE_RESULT_SEMANTIC_MISMATCH")
    return {"identity": freeze_identity, "value": value}


def audit_official_stack(spec: Spec, probe: Probe = v3.default_probe) -> dict[str, Any]:
    official = v4.audit_official_stack(spec, probe)
    support = dict(official["support_identities"])
    support.update({
        "result_informed_profile_module": identity(PROFILE_MODULE),
        "result_informed_materializer": identity(MATERIALIZER),
        "result_informed_shared_exporter": identity(SHARED_EXPORTER),
        "result_informed_v5_runner": identity(Path(__file__)),
        "static_extension_freeze": identity(spec.static_freeze),
        "prior_v4_runner": identity(profile.ROOT / "scripts/run_hfnet_slam_a02_long1801_headless_v4.py"),
    })
    official["support_identities"] = support
    official["headless_boundary"] = {"viewer_enabled": False, "official_entry_included": True, "algorithm_or_threshold_modified": False, "atlas_resume": False}
    return official


def audit_profile(spec: Spec, probe: Probe = v3.default_probe) -> dict[str, Any]:
    static = audit_static_freeze(spec)
    return {
        "schema_version": PROFILE_SCHEMA,
        "scientific_role": ROLE,
        "static_freeze": static["identity"],
        "prior_unusable_result": profile.expected_static_source_identities()["prior_hfnet_unusable_result"],
        "official": audit_official_stack(spec, probe),
        "input": shared.audit_exported_artifact(spec.shared_root),
        "score_gate": {
            "global_camera_indices_inclusive": [profile.SCORE_FIRST, profile.SCORE_LAST],
            "reference_pose_count": profile.SCORE_REFERENCE_COUNT,
            "evaluation_grid_count": profile.SCORE_EVALUATION_GRID_COUNT,
            "minimum_trajectory_score_poses": MIN_TRAJECTORY_SCORE_POSES,
            "minimum_trajectory_score_span_s": MIN_TRAJECTORY_SCORE_SPAN_S,
            "minimum_keyframes": MIN_KEYFRAMES,
            "minimum_score_keyframes": MIN_SCORE_KEYFRAMES,
            "hfnet_double_timestamp_camera_association_max_abs_error_ns": MAX_HFNET_CAMERA_ASSOCIATION_ERROR_NS,
            "output_timestamps_or_poses_modified": False,
        },
        "execution_controls": {"start_from_scratch": True, "atlas_resume": False, "maximum_process_starts": 1, "retry": False, "extend_to_8100": False},
    }


def preflight(spec: Spec = DEFAULT_SPEC, *, probe: Probe = v3.default_probe) -> dict[str, Any]:
    errors: list[str] = []
    frozen_profile = None
    try:
        frozen_profile = audit_profile(spec, probe)
    except (ContractError, shared.ContractError, profile.ExtensionError, v3.ContractError, v4.ContractError, OSError, UnicodeError, ValueError, json.JSONDecodeError) as error:
        errors.append(str(error))
    reservations = {"contract_absent": absent(spec.contract), "evidence_absent": absent(spec.evidence), "result_absent": absent(spec.result), "bridge_output_absent": absent(spec.bridge_output), "bridge_manifest_absent": absent(Path(str(spec.bridge_output) + ".manifest.json"))}
    if not all(reservations.values()):
        errors.append("OUTPUT_RESERVATION_NOT_EMPTY")
    return {"schema_version": PROFILE_SCHEMA, "status": "PREFLIGHT_READY" if not errors else "PREFLIGHT_BLOCKED", "ready": not errors, "errors": errors, "profile": frozen_profile, "reservations": reservations, "claims": {"slam_started": False, "filesystem_writes": False}}


def build_contract(frozen_profile: Mapping[str, Any], spec: Spec) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA,
        "scientific_role": ROLE,
        "frozen_profile": dict(frozen_profile),
        "frozen_profile_sha256": hashlib.sha256(canonical_json(frozen_profile).encode()).hexdigest(),
        "execution_policy": {"start_from_scratch_at_global_camera": profile.FEED_FIRST, "maximum_process_starts": 1, "retry": False, "viewer": False, "atlas_resume": False, "extend_to_8100": False, "official_algorithm_or_threshold_modification": False, "cache": "copy seed to run-local model directory; record pre/post SHA; never write back", "trajectory_gate": "RC0 plus valid world_T_body trajectory and keyframe files with frozen 6300..7200 support"},
        "paths": {
            "static_freeze": str(absolute(spec.static_freeze)),
            "contract": str(absolute(spec.contract)),
            "evidence": str(absolute(spec.evidence)),
            "result": str(absolute(spec.result)),
            "raw_trajectory": str(absolute(spec.result / "trajectory.txt")),
            "raw_keyframes": str(absolute(spec.result / "trajectory_keyframe.txt")),
            "reserved_vins_csv_bridge_output": str(absolute(spec.bridge_output)),
            "reserved_vins_csv_bridge_manifest": str(
                absolute(Path(str(spec.bridge_output) + ".manifest.json"))
            ),
        },
    }


def freeze(spec: Spec = DEFAULT_SPEC, *, probe: Probe = v3.default_probe) -> dict[str, Any]:
    decision = preflight(spec, probe=probe)
    if not decision["ready"]:
        return {**decision, "return_code": RC_BLOCKED, "status": "FREEZE_BLOCKED"}
    try:
        v3.write_exclusive(spec.contract, canonical_json(build_contract(decision["profile"], spec)).encode())
    except (OSError, FileExistsError) as error:
        return {**decision, "return_code": RC_BLOCKED, "status": "FREEZE_BLOCKED", "errors": [*decision["errors"], str(error)]}
    return {"schema_version": SCHEMA, "status": "CONTRACT_FROZEN_NO_RUN_STARTED", "return_code": RC_OK, "contract": identity(spec.contract), "slam_started": False}


def reserve_run_roots(spec: Spec) -> None:
    """Atomically claim both final namespaces before the one allowed ELF start."""
    for path, label in ((spec.result, "RESULT"), (spec.evidence, "EVIDENCE")):
        if path.exists() or path.is_symlink():
            raise ContractError(f"{label}_ROOT_ALREADY_EXISTS")
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            path.mkdir(exist_ok=False)
        except FileExistsError as error:
            raise ContractError(f"{label}_ROOT_RESERVATION_RACE") from error
        if path.is_symlink() or not path.is_dir() or any(path.iterdir()):
            raise ContractError(f"{label}_ROOT_RESERVATION_INVALID")


def audit_run_local_immutables(staged: Mapping[str, Any]) -> dict[str, object]:
    model_dir = Path(str(staged["model_dir"]))
    onnx_post = identity(model_dir / "HF-Net.onnx")
    config_post = identity(Path(str(staged["derived_config"]["path"])))
    onnx_unchanged = onnx_post == staged["onnx"]
    config_unchanged = config_post == staged["derived_config"]
    if not onnx_unchanged or not config_unchanged:
        raise ContractError("RUN_LOCAL_ONNX_OR_DERIVED_CONFIG_CHANGED")
    return {
        "onnx_pre": staged["onnx"],
        "onnx_post": onnx_post,
        "onnx_unchanged": True,
        "derived_config_pre": staged["derived_config"],
        "derived_config_post": config_post,
        "derived_config_unchanged": True,
    }


def _parse_trajectory(path: Path, camera_timestamps_ns: Sequence[int], *, keyframes: bool) -> dict[str, Any]:
    result: dict[str, Any] = {"exists": False, "identity": None, "pose_count": 0, "score_pose_count": 0, "strictly_increasing_timestamps": False, "finite_valid_world_T_body_rows": False, "all_rows_uniquely_associated_to_camera": False, "association_max_abs_error_ns": None, "associated_first_relative_camera_index": None, "associated_last_relative_camera_index": None, "associated_max_camera_index_gap": None, "associated_skipped_camera_count": None, "span_seconds": None, "score_span_seconds": None, "gate_pass": False, "errors": []}
    if len(camera_timestamps_ns) != EXPECTED_CAMERA_COUNT or any(right <= left for left, right in zip(camera_timestamps_ns, camera_timestamps_ns[1:])):
        result["errors"] = ["invalid_frozen_camera_timestamp_grid"]
        return result
    try:
        requested = path.expanduser()
        if requested.parent.is_symlink() or not requested.parent.is_dir() or requested.is_symlink():
            raise ContractError("TRAJECTORY_PATH_OR_RESULT_ROOT_SYMLINK_FORBIDDEN")
        canonical_parent = requested.parent.resolve(strict=True)
        descriptor = os.open(requested, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        with os.fdopen(descriptor, "rb") as stream:
            metadata = os.fstat(stream.fileno())
            if not stat.S_ISREG(metadata.st_mode):
                raise ContractError("TRAJECTORY_NOT_REGULAR_FILE")
            opened = Path(f"/proc/self/fd/{stream.fileno()}").resolve(strict=True)
            if opened.parent != canonical_parent or opened.name != requested.name:
                raise ContractError("TRAJECTORY_ESCAPES_RESERVED_RESULT_ROOT")
            payload = stream.read()
        lines = payload.decode("ascii").splitlines()
        result["exists"] = True
        result["identity"] = {"path": str(canonical_parent / requested.name), "size_bytes": len(payload), "sha256": hashlib.sha256(payload).hexdigest()}
    except (ContractError, OSError, UnicodeError) as error:
        result["errors"] = [str(error)]
        return result
    if not lines or any(not line.strip() for line in lines):
        result["errors"] = ["empty_or_blank_row"]
        return result
    stamps: list[int] = []
    errors: list[str] = []
    for index, line in enumerate(lines):
        fields = line.split()
        if len(fields) != 8:
            errors.append(f"row_{index}_field_count")
            continue
        try:
            raw_stamp = Decimal(fields[0])
            values = [float(item) for item in fields[1:]]
        except (InvalidOperation, ValueError):
            errors.append(f"row_{index}_nonnumeric")
            continue
        if not raw_stamp.is_finite() or raw_stamp != raw_stamp.to_integral_value() or not all(math.isfinite(item) for item in values) or not 0.99 <= math.sqrt(sum(item * item for item in values[3:7])) <= 1.01:
            errors.append(f"row_{index}_invalid_pose")
            continue
        stamps.append(int(raw_stamp))
    rows_valid = not errors and len(stamps) == len(lines)
    strict = rows_valid and all(right > left for left, right in zip(stamps, stamps[1:]))
    associations: list[int] = []
    association_errors: list[int] = []
    for row_index, stamp in enumerate(stamps):
        insertion = bisect.bisect_left(camera_timestamps_ns, stamp)
        candidates = [index for index in (insertion - 1, insertion) if 0 <= index < len(camera_timestamps_ns)]
        if not candidates:
            errors.append(f"row_{row_index}_no_camera_candidate")
            associations.append(-1)
            continue
        nearest = min(candidates, key=lambda index: (abs(camera_timestamps_ns[index] - stamp), index))
        error = abs(camera_timestamps_ns[nearest] - stamp)
        if error > MAX_HFNET_CAMERA_ASSOCIATION_ERROR_NS:
            errors.append(f"row_{row_index}_camera_association_error")
            associations.append(-1)
            continue
        associations.append(nearest)
        association_errors.append(error)
    association_strict = len(associations) == len(stamps) and all(index >= 0 for index in associations) and len(set(associations)) == len(associations) and all(right > left for left, right in zip(associations, associations[1:]))
    if associations and not association_strict:
        errors.append("associated_camera_indices_not_unique_strict")
    score_relative_first = profile.SCORE_FIRST - profile.FEED_FIRST
    score_relative_last = profile.SCORE_LAST - profile.FEED_FIRST
    score_stamps = [stamp for stamp, associated in zip(stamps, associations) if score_relative_first <= associated <= score_relative_last]
    gaps = [right - left for left, right in zip(associations, associations[1:])] if association_strict else []
    result.update({"pose_count": len(stamps), "score_pose_count": len(score_stamps), "strictly_increasing_timestamps": strict, "finite_valid_world_T_body_rows": rows_valid, "all_rows_uniquely_associated_to_camera": association_strict, "association_max_abs_error_ns": max(association_errors) if association_errors else None, "associated_first_relative_camera_index": associations[0] if associations and associations[0] >= 0 else None, "associated_last_relative_camera_index": associations[-1] if associations and associations[-1] >= 0 else None, "associated_max_camera_index_gap": max(gaps) if gaps else 0, "associated_skipped_camera_count": sum(gap - 1 for gap in gaps) if gaps else 0, "span_seconds": (stamps[-1] - stamps[0]) / 1e9 if strict else None, "score_span_seconds": (score_stamps[-1] - score_stamps[0]) / 1e9 if len(score_stamps) >= 2 else 0.0, "errors": errors})
    if keyframes:
        result["gate_pass"] = bool(rows_valid and strict and association_strict and len(stamps) >= MIN_KEYFRAMES and len(score_stamps) >= MIN_SCORE_KEYFRAMES)
    else:
        result["gate_pass"] = bool(rows_valid and strict and association_strict and len(stamps) >= MIN_TRAJECTORY_POSES and len(score_stamps) >= MIN_TRAJECTORY_SCORE_POSES and result["score_span_seconds"] >= MIN_TRAJECTORY_SCORE_SPAN_S)
    return result


def run(spec: Spec = DEFAULT_SPEC, *, probe: Probe = v3.default_probe, execute: Execute = v3.default_execute) -> dict[str, Any]:
    try:
        contract_payload = spec.contract.read_bytes()
        frozen = json.loads(contract_payload.decode("utf-8"))
        if contract_payload != canonical_json(frozen).encode():
            raise ContractError("FROZEN_CONTRACT_NOT_CANONICAL_PRETTY_JSON")
        frozen_profile = audit_profile(spec, probe)
        if frozen != build_contract(frozen_profile, spec):
            raise ContractError("FROZEN_CONTRACT_OR_PROFILE_MISMATCH")
        if not all(absent(path) for path in (spec.evidence, spec.result, spec.bridge_output, Path(str(spec.bridge_output) + ".manifest.json"))):
            raise ContractError("RUN_OUTPUT_NO_CLOBBER")
        reserve_run_roots(spec)
        v3.write_exclusive(spec.evidence / "frozen_contract.snapshot.json", canonical_json(frozen).encode())
        shared_cache_pre = identity(spec.cache_seed)
        staged = v3.stage_run_local_model(spec)
    except (ContractError, shared.ContractError, profile.ExtensionError, v3.ContractError, v4.ContractError, OSError, UnicodeError, ValueError, json.JSONDecodeError) as error:
        return {"schema_version": RESULT_SCHEMA, "status": "CONTRACT_BLOCKED", "return_code": RC_BLOCKED, "evaluable": False, "errors": [str(error)], "execution": {"command_started": False, "process_start_count": 0}}
    command = v3.command_argv(spec, Path(staged["derived_config"]["path"]))
    execution = execute(command, v3.runtime_environment(spec), spec.evidence, spec.timeout_seconds)
    v3.write_exclusive(spec.evidence / "headless.stdout.log", execution.stdout.encode(errors="replace"))
    v3.write_exclusive(spec.evidence / "headless.stderr.log", execution.stderr.encode(errors="replace"))
    timestamps = frozen_profile["input"]["camera_timestamps_ns"]
    trajectory = _parse_trajectory(spec.result / "trajectory.txt", timestamps, keyframes=False)
    keyframes = _parse_trajectory(spec.result / "trajectory_keyframe.txt", timestamps, keyframes=True)
    cache_errors: list[str] = []
    try:
        run_local_post = identity(Path(staged["model_dir"]) / "HF-Net.cache")
        shared_cache_post = identity(spec.cache_seed)
        shared_unchanged = shared_cache_pre == shared_cache_post
    except (ContractError, OSError, v3.ContractError) as error:
        run_local_post, shared_cache_post, shared_unchanged = None, None, False
        cache_errors.append(f"CACHE_POST_AUDIT_FAILED:{error}")
    post_errors: list[str] = []
    try:
        run_local_immutables = audit_run_local_immutables(staged)
        run_local_immutables_unchanged = True
    except (ContractError, OSError, v3.ContractError, KeyError, TypeError) as error:
        run_local_immutables, run_local_immutables_unchanged = None, False
        post_errors.append(f"RUN_LOCAL_IMMUTABLE_POST_AUDIT_FAILED:{error}")
    try:
        official_post = audit_official_stack(spec, probe)
        official_unchanged = official_post == frozen_profile["official"]
    except (ContractError, profile.ExtensionError, v3.ContractError, v4.ContractError, OSError, UnicodeError, ValueError, json.JSONDecodeError) as error:
        official_post, official_unchanged = None, False
        post_errors.append(f"OFFICIAL_STACK_POST_AUDIT_FAILED:{error}")
    try:
        input_post = shared.audit_exported_artifact(spec.shared_root)
        input_unchanged = input_post == frozen_profile["input"]
    except (shared.ContractError, profile.ExtensionError, OSError, UnicodeError, ValueError, json.JSONDecodeError) as error:
        input_post, input_unchanged = None, False
        post_errors.append(f"SHARED_INPUT_POST_AUDIT_FAILED:{error}")
    passed = execution.returncode == 0 and not execution.timed_out and trajectory["gate_pass"] is True and keyframes["gate_pass"] is True and shared_unchanged and run_local_immutables_unchanged and official_unchanged and input_unchanged
    errors = cache_errors + post_errors + ([] if shared_unchanged else ["SHARED_CACHE_WAS_MODIFIED_OR_UNREADABLE"]) + ([] if run_local_immutables_unchanged else ["RUN_LOCAL_ONNX_OR_DERIVED_CONFIG_CHANGED_OR_UNREADABLE"]) + ([] if official_unchanged else ["OFFICIAL_STACK_CHANGED_OR_UNREADABLE"]) + ([] if input_unchanged else ["SHARED_INPUT_CHANGED_OR_UNREADABLE"])
    result = {"schema_version": RESULT_SCHEMA, "scientific_role": ROLE, "status": "PASS_RESULT_INFORMED_EXTENSION_SCORE_GATE" if passed else "RESULT_INFORMED_EXTENSION_FAILED_OR_UNUSABLE", "return_code": RC_OK if passed else RC_FAILED, "evaluable": passed, "errors": errors, "command_argv": command, "execution": {"command_started": True, "process_start_count": 1, "raw_returncode": execution.returncode, "timed_out": execution.timed_out}, "cache": {"shared_pre": shared_cache_pre, "shared_post": shared_cache_post, "shared_unchanged": shared_unchanged, "run_local_pre": staged["cache_pre"], "run_local_post": run_local_post, "writeback_performed": False}, "immutables": {"static_freeze": identity(spec.static_freeze), "profile_sha256": frozen["frozen_profile_sha256"], "run_local": run_local_immutables, "run_local_immutables_unchanged": run_local_immutables_unchanged, "official_stack_post": official_post, "official_stack_unchanged": official_unchanged, "shared_input_post": input_post, "shared_input_unchanged": input_unchanged}, "gate": {"return_code_zero": execution.returncode == 0, "trajectory": trajectory, "keyframe_trajectory": keyframes}, "supervision": {"start_from_scratch": True, "viewer_enabled": False, "atlas_resume": False, "algorithm_or_threshold_modified": False, "retry_performed": False, "extension_to_8100_performed": False}}
    v3.write_exclusive(spec.evidence / "run_result.json", canonical_json(result).encode())
    return result


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(description=__doc__)
    value.add_argument("--action", choices=("preflight", "freeze", "run"), default="preflight")
    value.add_argument("--shared-root", type=Path, default=profile.NEW_SHARED_ROOT)
    value.add_argument("--result-directory", type=Path, default=profile.NEW_RESULT)
    value.add_argument("--evidence-directory", type=Path, default=profile.NEW_EVIDENCE)
    value.add_argument("--contract-json", type=Path, default=profile.NEW_RUN_CONTRACT)
    value.add_argument("--bridge-output", type=Path, default=profile.NEW_BRIDGE_OUTPUT)
    value.add_argument("--static-freeze", type=Path, default=profile.STATIC_FREEZE)
    return value


def main(argv: Sequence[str] | None = None) -> int:
    try:
        profile.audit_sealed_invocation_environment()
    except profile.ExtensionError as error:
        decision = {"schema_version": RESULT_SCHEMA, "status": "CONTRACT_BLOCKED", "return_code": RC_BLOCKED, "evaluable": False, "errors": [str(error)], "execution": {"command_started": False, "process_start_count": 0}}
        sys.stdout.write(canonical_json(decision))
        return RC_BLOCKED
    args = parser().parse_args(argv)
    spec = replace(DEFAULT_SPEC, shared_root=args.shared_root, result=args.result_directory, evidence=args.evidence_directory, contract=args.contract_json, bridge_output=args.bridge_output, static_freeze=args.static_freeze)
    decision = preflight(spec) if args.action == "preflight" else freeze(spec) if args.action == "freeze" else run(spec)
    if args.action == "preflight":
        decision["return_code"] = RC_OK if decision["ready"] else RC_BLOCKED
    sys.stdout.write(canonical_json(decision))
    return int(decision["return_code"])


if __name__ == "__main__":
    raise SystemExit(main())
