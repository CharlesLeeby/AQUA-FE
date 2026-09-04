#!/usr/bin/env python3
"""Bridge only the sealed HFNet-v6 A06/H07 trajectories to VINS CSV.

The accepted HFNet rows are TUM-like, but their timestamp is an integral
nanosecond value rather than seconds::

    timestamp_ns tx ty tz qx qy qz qw

They encode ``world_T_body`` with an ``xyzw`` quaternion.  The output is the
headerless format consumed by ``evaluate_vins_common_support.py``::

    timestamp_ns,tx,ty,tz,qw,qx,qy,qz

Only delimiter and quaternion column order change.  This bridge performs no
pose inversion, extrinsic composition, alignment, interpolation, resampling,
timestamp scaling, or timestamp offset.
"""

from __future__ import annotations

import argparse
from decimal import Decimal, InvalidOperation
import hashlib
import json
import math
import os
from pathlib import Path
import stat
import sys
import tempfile
from typing import Mapping, Sequence


SCHEMA = "aqua-fe-hfnet-v6-a06-h07-world-body-to-vins-csv-bridge-v1"
PASS_STATUS = "PASS_EXPLORATORY_UNDERWATER_USABILITY"

# These are identities of the two terminal, already-produced attempt_001
# results.  Exact run-result identity is deliberately required in addition to
# inspecting its fields: a copied or subsequently rewritten JSON file is not a
# sealed result accepted by this bridge.
ALLOWED_PROFILES: Mapping[str, Mapping[str, object]] = {
    "aqua-fe-hfnet-v6-a06-0000-2460-run-result-v1": {
        "profile_id": "A06_0000_2460_ATTEMPT_001",
        "scientific_role": "HFNET_V6_A06_EXACT_WINDOW_EXTERNAL_LEARNED_SYSTEM_DEVELOPMENT_ONLY",
        "run_result": {
            "path": "/mnt/data/AQUA-FE_WS/logs/published_hfnet_slam_v6/fresh_underwater/aqualoc_archaeology_a06_0000_2460/attempt_001/run_result.json",
            "size_bytes": 161_265,
            "sha256": "2b9640fbc206f11db8e5a90d74f8c57214ae0912a3608263e9d3ddc23686441b",
        },
        "trajectory": {
            "path": "/mnt/data/AQUA-FE_WS/logs/published_hfnet_slam_v6/fresh_underwater/aqualoc_archaeology_a06_0000_2460/attempt_001/result/trajectory.txt",
            "size_bytes": 277_177,
            "sha256": "72cbd969ec645ea0b5f527c9b1a404fd4e4176a9475819a054b2dd553d027460",
        },
        "pose_count": 2_457,
        "score": {"count": 251, "first_index": 2_210, "last_index": 2_460},
    },
    "aqua-fe-hfnet-v6-h07-0001-1720-run-result-v1": {
        "profile_id": "H07_0001_1720_ATTEMPT_001",
        "scientific_role": "HFNET_V6_H07_EXACT_WINDOW_EXTERNAL_LEARNED_SYSTEM_DEVELOPMENT_ONLY",
        "run_result": {
            "path": "/mnt/data/AQUA-FE_WS/logs/published_hfnet_slam_v6/fresh_underwater/aqualoc_harbor_h07_0001_1720/attempt_001/run_result.json",
            "size_bytes": 163_359,
            "sha256": "fb3d5fdd9e29b55e08d58622d02fdac8992bca0132472ccae943533d87c8179a",
        },
        "trajectory": {
            "path": "/mnt/data/AQUA-FE_WS/logs/published_hfnet_slam_v6/fresh_underwater/aqualoc_harbor_h07_0001_1720/attempt_001/result/trajectory.txt",
            "size_bytes": 188_311,
            "sha256": "d924c4c2e2f3ff8f692a0aa6f258e8998a8d0a8c05cd12ce4150bc5a54e4f4f6",
        },
        "pose_count": 1_643,
        "score": {"count": 61, "first_index": 1_659, "last_index": 1_719},
    },
}


class BridgeError(RuntimeError):
    """A fail-closed bridge contract violation."""


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def canonical_json(value: object) -> bytes:
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


def read_regular_once(path: Path) -> tuple[bytes, dict[str, object]]:
    """Read one non-symlink regular-file inode and bind identity to its bytes."""

    absolute = path.expanduser().absolute()
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(absolute, flags)
        with os.fdopen(descriptor, "rb") as stream:
            metadata = os.fstat(stream.fileno())
            if not stat.S_ISREG(metadata.st_mode):
                raise BridgeError(f"INPUT_NOT_REGULAR_NONSYMLINK_FILE:{absolute}")
            payload = stream.read()
    except OSError as error:
        raise BridgeError(
            f"INPUT_NOT_REGULAR_NONSYMLINK_FILE:{absolute}:{error}"
        ) from error
    return payload, {
        "path": str(absolute),
        "size_bytes": len(payload),
        "sha256": sha256_bytes(payload),
    }


def file_identity(path: Path) -> dict[str, object]:
    _, identity = read_regular_once(path)
    return identity


def parse_trajectory_payload(payload: bytes, label: str) -> list[tuple[str, ...]]:
    """Parse world_T_body/xyzw rows and reorder only quaternion columns."""

    try:
        lines = payload.decode("ascii").splitlines()
    except UnicodeError as error:
        raise BridgeError(f"TRAJECTORY_NOT_ASCII:{label}:{error}") from error
    if not lines:
        raise BridgeError("TRAJECTORY_EMPTY")
    if any(not line.strip() for line in lines):
        raise BridgeError("TRAJECTORY_CONTAINS_BLANK_ROW")

    rows: list[tuple[str, ...]] = []
    stamps: list[int] = []
    for index, line in enumerate(lines):
        fields = tuple(line.split())
        if len(fields) != 8:
            raise BridgeError(f"ROW_{index}_FIELD_COUNT_NOT_8")
        try:
            stamp_decimal = Decimal(fields[0])
        except InvalidOperation as error:
            raise BridgeError(f"ROW_{index}_INVALID_TIMESTAMP") from error
        if (
            not stamp_decimal.is_finite()
            or stamp_decimal != stamp_decimal.to_integral_value()
        ):
            raise BridgeError(f"ROW_{index}_TIMESTAMP_NOT_INTEGER_NS")
        stamp = int(stamp_decimal)
        try:
            pose = [float(value) for value in fields[1:]]
        except ValueError as error:
            raise BridgeError(f"ROW_{index}_INVALID_POSE") from error
        if not all(math.isfinite(value) for value in pose):
            raise BridgeError(f"ROW_{index}_NONFINITE_POSE")
        quaternion_norm = math.sqrt(sum(value * value for value in pose[3:7]))
        if not 0.99 <= quaternion_norm <= 1.01:
            raise BridgeError(f"ROW_{index}_INVALID_QUATERNION_NORM")
        stamps.append(stamp)
        rows.append(
            (
                str(stamp),
                fields[1],
                fields[2],
                fields[3],
                fields[7],
                fields[4],
                fields[5],
                fields[6],
            )
        )
    if any(right <= left for left, right in zip(stamps, stamps[1:])):
        raise BridgeError("TIMESTAMPS_NOT_STRICTLY_INCREASING")
    return rows


def csv_bytes(rows: Sequence[Sequence[str]]) -> bytes:
    return ("\n".join(",".join(row) for row in rows) + "\n").encode("ascii")


def _expect_identity(
    actual: object, expected: object, error_code: str
) -> None:
    if not isinstance(actual, dict) or actual != expected:
        raise BridgeError(error_code)


def validate_v6_run_result(
    path: Path,
    source_identity: Mapping[str, object],
    profiles: Mapping[str, Mapping[str, object]] = ALLOWED_PROFILES,
) -> dict[str, object]:
    """Validate an exact sealed PASS and its exact trajectory identity."""

    payload, result_identity = read_regular_once(path)
    try:
        value = json.loads(payload.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as error:
        raise BridgeError("RUN_RESULT_INVALID_JSON") from error
    if not isinstance(value, dict) or payload != canonical_json(value):
        raise BridgeError("RUN_RESULT_NOT_CANONICAL_OBJECT")

    schema = value.get("schema_version")
    profile = profiles.get(schema) if isinstance(schema, str) else None
    if profile is None:
        raise BridgeError("RUN_RESULT_SCHEMA_NOT_ALLOWED_A06_OR_H07_V6")
    _expect_identity(
        result_identity,
        profile.get("run_result"),
        "RUN_RESULT_SEALED_IDENTITY_MISMATCH",
    )
    _expect_identity(
        source_identity,
        profile.get("trajectory"),
        "TRAJECTORY_SEALED_IDENTITY_MISMATCH",
    )

    if (
        value.get("status") != PASS_STATUS
        or value.get("return_code") != 0
        or value.get("errors") != []
        or value.get("scientific_role") != profile.get("scientific_role")
    ):
        raise BridgeError("RUN_RESULT_NOT_EXACT_EVALUABLE_USABILITY_PASS")

    execution = value.get("execution")
    if not isinstance(execution, dict) or (
        execution.get("process_started") is not True
        or execution.get("popen_invocations") != 1
        or execution.get("raw_returncode") != 0
        or execution.get("retry_performed") is not False
        or execution.get("retry_permitted") is not False
        or execution.get("timed_out") is not False
        or execution.get("synchronously_reaped") is not True
        or execution.get("supervisor_error") is not None
    ):
        raise BridgeError("RUN_RESULT_EXECUTION_GATE_MISMATCH")

    gates = value.get("gate")
    required_gates = (
        "execution",
        "exploratory_underwater_usability",
        "full_pre_post_profile_exact",
        "keyframe_score_support",
        "run_local_onnx_and_config_exact",
        "shared_cache_exact",
        "trajectory_score_continuity",
    )
    if not isinstance(gates, dict) or any(gates.get(key) is not True for key in required_gates):
        raise BridgeError("RUN_RESULT_PASS_GATE_MISMATCH")

    sealing = value.get("sealing_contract")
    expected_result = profile.get("run_result")
    expected_result_path = (
        expected_result.get("path") if isinstance(expected_result, dict) else None
    )
    if not isinstance(sealing, dict) or (
        sealing.get("target") != expected_result_path
        or sealing.get("terminal_after_any_started_attempt") is not True
        or sealing.get("retry_after_pass_or_fail") is not False
        or sealing.get("write_mode") != "O_EXCL_then_fsync_then_chmod_0444"
    ):
        raise BridgeError("RUN_RESULT_SEALING_CONTRACT_MISMATCH")

    support = value.get("support")
    trajectory = support.get("trajectory") if isinstance(support, dict) else None
    if not isinstance(trajectory, dict):
        raise BridgeError("RUN_RESULT_TRAJECTORY_SUPPORT_MISSING")
    _expect_identity(
        trajectory.get("identity"),
        source_identity,
        "RUN_RESULT_TRAJECTORY_IDENTITY_MISMATCH",
    )
    if (
        trajectory.get("exists") is not True
        or trajectory.get("valid") is not True
        or trajectory.get("kind") != "frame_trajectory"
        or trajectory.get("strictly_increasing_timestamps") is not True
        or trajectory.get("unique_strict_camera_associations") is not True
        or trajectory.get("all_quaternions_within_tolerance") is not True
        or trajectory.get("errors") != []
        or trajectory.get("pose_count") != profile.get("pose_count")
    ):
        raise BridgeError("RUN_RESULT_TRAJECTORY_GATE_MISMATCH")

    score = trajectory.get("score")
    expected_score = profile.get("score")
    if not isinstance(score, dict) or not isinstance(expected_score, dict) or (
        score.get("count") != expected_score.get("count")
        or score.get("first_index") != expected_score.get("first_index")
        or score.get("last_index") != expected_score.get("last_index")
        or score.get("coverage_fraction") != 1.0
        or score.get("gap_count") != 0
        or score.get("contiguous_run_count") != 1
        or score.get("longest_contiguous_run") != expected_score.get("count")
    ):
        raise BridgeError("RUN_RESULT_SCORE_SUPPORT_MISMATCH")

    return {
        "identity": result_identity,
        "profile_id": profile.get("profile_id"),
        "schema_version": schema,
        "status": value.get("status"),
        "trajectory_source_identity_match": True,
        "pose_count": profile.get("pose_count"),
        "score": expected_score,
    }


def write_exclusive(path: Path, payload: bytes) -> tuple[int, int]:
    """Atomically publish a complete read-only file without replacement."""

    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.tmp-", dir=str(path.parent)
    )
    temporary = Path(temporary_name)
    published_inode: tuple[int, int] | None = None
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, 0o444)
        metadata = os.lstat(temporary)
        os.link(temporary, path)
        published_inode = (metadata.st_dev, metadata.st_ino)
    finally:
        try:
            temporary.unlink()
        except OSError:
            pass
    if published_inode is None:
        raise BridgeError("INTERNAL_PUBLICATION_STATE_MISSING")
    return published_inode


def unlink_if_same_inode(path: Path, owned_inode: tuple[int, int]) -> None:
    try:
        metadata = os.lstat(path)
        if (
            stat.S_ISREG(metadata.st_mode)
            and (metadata.st_dev, metadata.st_ino) == owned_inode
        ):
            path.unlink()
    except FileNotFoundError:
        pass


def audit(
    source: Path,
    run_result: Path,
    profiles: Mapping[str, Mapping[str, object]] = ALLOWED_PROFILES,
) -> dict[str, object]:
    source_payload, source_identity = read_regular_once(source)
    rows = parse_trajectory_payload(source_payload, str(source))
    result_record = validate_v6_run_result(run_result, source_identity, profiles)
    if len(rows) != result_record["pose_count"]:
        raise BridgeError("TRAJECTORY_ROW_COUNT_RUN_RESULT_MISMATCH")
    return {
        "status": "AUDIT_PASS_NO_WRITE",
        "profile_id": result_record["profile_id"],
        "source": source_identity,
        "run_result": result_record,
        "row_count": len(rows),
    }


def convert(
    source: Path,
    output: Path,
    run_result: Path,
    profiles: Mapping[str, Mapping[str, object]] = ALLOWED_PROFILES,
) -> dict[str, object]:
    source_payload, source_identity = read_regular_once(source)
    rows = parse_trajectory_payload(source_payload, str(source))
    result_record = validate_v6_run_result(run_result, source_identity, profiles)
    if len(rows) != result_record["pose_count"]:
        raise BridgeError("TRAJECTORY_ROW_COUNT_RUN_RESULT_MISMATCH")

    output = output.expanduser().absolute()
    manifest_path = Path(str(output) + ".manifest.json")
    if (
        output.exists()
        or output.is_symlink()
        or manifest_path.exists()
        or manifest_path.is_symlink()
    ):
        raise BridgeError("OUTPUT_OR_MANIFEST_ALREADY_EXISTS")

    payload = csv_bytes(rows)
    output_record = {
        "path": str(output),
        "size_bytes": len(payload),
        "sha256": sha256_bytes(payload),
    }
    manifest = {
        "schema_version": SCHEMA,
        "status": "PASS_SEALED_V6_BRIDGE",
        "producer": file_identity(Path(__file__)),
        "profile_id": result_record["profile_id"],
        "source": source_identity,
        "sealed_v6_run_result": result_record,
        "output": output_record,
        "row_count": len(rows),
        "semantics": {
            "input_format": "HFNet_TUM_like_whitespace_without_header",
            "input_columns": [
                "timestamp_ns",
                "tx",
                "ty",
                "tz",
                "qx",
                "qy",
                "qz",
                "qw",
            ],
            "input_pose": "world_T_body",
            "input_quaternion_order": "xyzw",
            "output_format": "evaluate_vins_common_support_headerless_csv",
            "output_columns": [
                "timestamp_ns",
                "tx",
                "ty",
                "tz",
                "qw",
                "qx",
                "qy",
                "qz",
            ],
            "output_pose": "world_T_body",
            "output_file_quaternion_order": "wxyz",
            "evaluator_loaded_quaternion_order": "xyzw",
            "pose_transform_or_inversion_applied": False,
            "extrinsic_composition_applied": False,
            "alignment_applied": False,
            "interpolation_or_resampling_applied": False,
            "timestamp_scale_or_offset_applied": False,
            "timestamp_numeric_value_changed": False,
            "pose_numeric_tokens_preserved_byte_for_byte_modulo_delimiter_and_quaternion_column_order": True,
            "timestamp_text_canonicalised_from_exact_integral_decimal_to_integer": True,
        },
    }
    manifest_payload = canonical_json(manifest)
    published: dict[Path, tuple[int, int]] = {}
    try:
        published[output] = write_exclusive(output, payload)
        if file_identity(output) != output_record:
            raise BridgeError("OUTPUT_POSTWRITE_IDENTITY_MISMATCH")
        published[manifest_path] = write_exclusive(manifest_path, manifest_payload)
    except BaseException:
        for candidate, owned_inode in reversed(tuple(published.items())):
            unlink_if_same_inode(candidate, owned_inode)
        raise
    return {
        "status": "PASS_SEALED_V6_BRIDGE",
        "profile_id": result_record["profile_id"],
        "output": file_identity(output),
        "manifest": file_identity(manifest_path),
        "row_count": len(rows),
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--action", choices=("audit", "convert"), default="audit")
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--run-result-json", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.action == "convert":
            if args.output is None:
                raise BridgeError("OUTPUT_REQUIRED_FOR_CONVERT")
            result = convert(args.input, args.output, args.run_result_json)
        else:
            if args.output is not None:
                raise BridgeError("OUTPUT_FORBIDDEN_FOR_AUDIT")
            result = audit(args.input, args.run_result_json)
        sys.stdout.buffer.write(canonical_json(result))
        return 0
    except (BridgeError, OSError) as error:
        print(f"CONTRACT_BLOCKED:{error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
