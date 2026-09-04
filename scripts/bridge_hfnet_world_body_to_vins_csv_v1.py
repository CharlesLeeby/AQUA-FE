#!/usr/bin/env python3
"""Losslessly bridge HFNet world_T_body rows to VINS-style CSV columns.

Input rows are ``stamp_ns tx ty tz qx qy qz qw``.  Output rows are
``stamp_ns,tx,ty,tz,qw,qx,qy,qz``.  The timestamp must be exactly integral;
canonicalising ``123.000000`` to ``123`` changes no timestamp value.  Pose
values are copied as text and are never transformed, inverted, or normalised.
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
from typing import Sequence

SCHEMA = "aqua-fe-hfnet-world-body-to-vins-csv-bridge-v1"
V4_RESULT_SCHEMA = "aqua-fe-hfnet-slam-a02-long1801-headless-result-v4"


class BridgeError(RuntimeError):
    pass


def read_regular_once(path: Path) -> tuple[bytes, dict[str, object]]:
    """Read one opened non-symlink inode and bind identity to those bytes."""

    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
        with os.fdopen(descriptor, "rb") as stream:
            metadata = os.fstat(stream.fileno())
            if not stat.S_ISREG(metadata.st_mode):
                raise BridgeError(f"INPUT_NOT_REGULAR_NONSYMLINK_FILE:{path}")
            payload = stream.read()
    except OSError as error:
        raise BridgeError(f"INPUT_NOT_REGULAR_NONSYMLINK_FILE:{path}:{error}") from error
    return payload, {"path": str(path.expanduser().absolute()), "size_bytes": len(payload), "sha256": sha256_bytes(payload)}


def parse_payload(payload: bytes, label: str) -> list[tuple[str, ...]]:
    try:
        lines = payload.decode("ascii").splitlines()
    except UnicodeError as error:
        raise BridgeError(f"INPUT_UNREADABLE:{label}:{error}") from error
    if not lines or any(not line.strip() for line in lines):
        raise BridgeError("INPUT_EMPTY_OR_CONTAINS_BLANK_ROW")

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
        if not stamp_decimal.is_finite() or stamp_decimal != stamp_decimal.to_integral_value():
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
        # Integer timestamp text is required by load_vins_body_csv.  All pose
        # tokens remain byte-for-byte identical, modulo delimiters/order.
        rows.append((str(stamp), fields[1], fields[2], fields[3], fields[7], fields[4], fields[5], fields[6]))
    if any(right <= left for left, right in zip(stamps, stamps[1:])):
        raise BridgeError("TIMESTAMPS_NOT_STRICTLY_INCREASING")
    return rows


def parse_rows(path: Path) -> list[tuple[str, ...]]:
    payload, _ = read_regular_once(path)
    return parse_payload(payload, str(path))


def csv_bytes(rows: Sequence[Sequence[str]]) -> bytes:
    return ("\n".join(",".join(row) for row in rows) + "\n").encode("ascii")


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def file_identity(path: Path) -> dict[str, object]:
    _, identity = read_regular_once(path)
    return identity


def canonical_json(value: object) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False) + "\n").encode("utf-8")


def validate_v4_run_result(path: Path, source_identity: dict[str, object]) -> dict[str, object]:
    payload, result_identity = read_regular_once(path)
    try:
        value = json.loads(payload.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as error:
        raise BridgeError("V4_RUN_RESULT_INVALID_JSON") from error
    if payload != canonical_json(value) or not isinstance(value, dict):
        raise BridgeError("V4_RUN_RESULT_NOT_CANONICAL_OBJECT")
    execution = value.get("execution")
    gate = value.get("gate")
    trajectory = gate.get("trajectory") if isinstance(gate, dict) else None
    keyframes = gate.get("keyframe_trajectory") if isinstance(gate, dict) else None
    if value.get("schema_version") != V4_RESULT_SCHEMA or value.get("status") != "PASS_LONG1801_HEADLESS_SCORE_TRAJECTORY_GATE" or value.get("return_code") != 0 or value.get("evaluable") is not True:
        raise BridgeError("V4_RUN_RESULT_NOT_EVALUABLE_PASS")
    if not isinstance(execution, dict) or execution.get("command_started") is not True or execution.get("process_start_count") != 1 or execution.get("raw_returncode") != 0 or execution.get("timed_out") is not False:
        raise BridgeError("V4_RUN_RESULT_EXECUTION_GATE_MISMATCH")
    if not isinstance(trajectory, dict) or trajectory.get("gate_pass") is not True or trajectory.get("identity") != source_identity:
        raise BridgeError("V4_TRAJECTORY_IDENTITY_MISMATCH")
    if not isinstance(keyframes, dict) or keyframes.get("gate_pass") is not True or not isinstance(keyframes.get("identity"), dict):
        raise BridgeError("V4_KEYFRAME_GATE_MISMATCH")
    return {"identity": result_identity, "trajectory_source_identity_match": True, "v4_profile_sha256": value.get("immutables", {}).get("profile_sha256") if isinstance(value.get("immutables"), dict) else None}


def write_exclusive(path: Path, payload: bytes) -> tuple[int, int]:
    """Publish one complete file atomically without replacing any owner data."""

    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.tmp-", dir=str(path.parent))
    temporary = Path(temporary_name)
    published_inode: tuple[int, int] | None = None
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, 0o444)
        metadata = os.lstat(temporary)
        # link(2) is an atomic no-replace publication on the same filesystem.
        os.link(temporary, path)
        published_inode = (metadata.st_dev, metadata.st_ino)
    finally:
        try:
            temporary.unlink()
        except OSError:
            # Publication, when it happened, is already a complete fsynced
            # inode.  A hidden temporary cleanup error must not turn success
            # into an ambiguous exception that loses ownership information.
            pass
    if published_inode is None:
        raise BridgeError("INTERNAL_PUBLICATION_STATE_MISSING")
    return published_inode


def unlink_if_same_inode(path: Path, owned_inode: tuple[int, int]) -> None:
    """Rollback only an inode this invocation demonstrably published."""

    try:
        metadata = os.lstat(path)
        if stat.S_ISREG(metadata.st_mode) and (metadata.st_dev, metadata.st_ino) == owned_inode:
            path.unlink()
    except FileNotFoundError:
        pass


def convert(source: Path, output: Path, run_result: Path) -> dict[str, object]:
    source_payload, source_identity = read_regular_once(source)
    rows = parse_payload(source_payload, str(source))
    run_result_record = validate_v4_run_result(run_result, source_identity)
    payload = csv_bytes(rows)
    manifest_path = Path(str(output) + ".manifest.json")
    if output.exists() or output.is_symlink() or manifest_path.exists() or manifest_path.is_symlink():
        raise BridgeError("OUTPUT_OR_MANIFEST_ALREADY_EXISTS")
    output_record = {"path": str(output.resolve(strict=False)), "size_bytes": len(payload), "sha256": sha256_bytes(payload)}
    manifest = {
        "schema_version": SCHEMA,
        "status": "PASS",
        "producer": file_identity(Path(__file__)),
        "source": source_identity,
        "v4_run_result": run_result_record,
        "output": output_record,
        "row_count": len(rows),
        "semantics": {
            "input_columns": ["timestamp_ns", "tx", "ty", "tz", "qx", "qy", "qz", "qw"],
            "input_pose": "world_T_body",
            "output_columns": ["timestamp_ns", "tx", "ty", "tz", "qw", "qx", "qy", "qz"],
            "output_pose": "world_T_body",
            "timestamp_numeric_value_changed": False,
            "timestamp_scale_or_offset_applied": False,
            "pose_transform_inverse_or_normalisation_applied": False,
            "pose_numeric_tokens_preserved_byte_for_byte_modulo_delimiter_and_quaternion_column_order": True,
            "timestamp_text_canonicalised_from_exact_integral_decimal_to_integer": True,
            "source_bytes_equal_v4_passed_trajectory_identity": True,
        },
    }
    manifest_payload = canonical_json(manifest)
    published: dict[Path, tuple[int, int]] = {}
    try:
        published[output] = write_exclusive(output, payload)
        if file_identity(output)["sha256"] != output_record["sha256"]:
            raise BridgeError("OUTPUT_POSTWRITE_IDENTITY_MISMATCH")
        published[manifest_path] = write_exclusive(manifest_path, manifest_payload)
    except BaseException:
        for candidate, owned_inode in reversed(tuple(published.items())):
            unlink_if_same_inode(candidate, owned_inode)
        raise
    return {"manifest": file_identity(manifest_path), "output": file_identity(output), "row_count": len(rows), "status": "PASS"}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--action", choices=("audit", "convert"), default="audit")
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--run-result-json", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.action == "convert":
            if args.output is None:
                raise BridgeError("OUTPUT_REQUIRED_FOR_CONVERT")
            if args.run_result_json is None:
                raise BridgeError("RUN_RESULT_JSON_REQUIRED_FOR_CONVERT")
            result = convert(args.input, args.output, args.run_result_json)
        else:
            source_payload, source_identity = read_regular_once(args.input)
            rows = parse_payload(source_payload, str(args.input))
            result = {"source": source_identity, "row_count": len(rows), "status": "AUDIT_PASS_NO_WRITE"}
        sys.stdout.buffer.write(canonical_json(result))
        return 0
    except (BridgeError, OSError) as error:
        print(f"CONTRACT_BLOCKED:{error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
