#!/usr/bin/env python3
"""Bridge only the sealed A10 HFNet warm-start score crop to VINS CSV.

Input rows are ``timestamp_ns tx ty tz qx qy qz qw`` and encode
``world_T_body``. Output rows are ``timestamp_ns,tx,ty,tz,qw,qx,qy,qz``.
Only the delimiter, integral timestamp spelling, and quaternion column order
change. No inversion, extrinsic composition, time snapping, interpolation,
resampling, alignment, scale, or numeric pose transformation is permitted.
"""

from __future__ import annotations

import argparse
from contextlib import contextmanager
from decimal import Decimal, InvalidOperation
import hashlib
import json
import math
import os
from pathlib import Path
import secrets
import signal
import stat
import sys
from typing import Any, Mapping, Sequence


SCHEMA = "aqua-fe-hfnet-v6-a10-warmstart-world-body-vins-csv-bridge-v1"
RUN_RESULT = {
    "path": "/mnt/data/AQUA-FE_WS/logs/published_hfnet_slam_v6/positive_windows/a10_0000_2800_score_2400_2800_warmstart/attempt_001/run_result.json",
    "size_bytes": 21463,
    "sha256": "88c340849adcc60985711dedd499c74db36e36b3ac103768bc3aa0d615372a46",
}
SCORE_CROP = {
    "path": "/mnt/data/AQUA-FE_WS/logs/published_hfnet_slam_v6/positive_windows/a10_0000_2800_score_2400_2800_warmstart/attempt_001/result/trajectory_score_2400_2800.txt",
    "size_bytes": 45556,
    "sha256": "b5df265df24baa0d7035ee183de28ca105b2bf6429ebf819d90fd6f275154566",
}
EXPECTED_FIRST_NS = 1542888916043622144
EXPECTED_LAST_NS = 1542888936039921408
EXPECTED_ROWS = 401


class BridgeError(RuntimeError):
    pass


def canonical(value: Any) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n").encode()


def write_all(descriptor: int, payload: bytes) -> None:
    offset = 0
    while offset < len(payload):
        written = os.write(descriptor, payload[offset:])
        if written <= 0:
            raise OSError("zero-length write")
        offset += written


def fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | os.O_CLOEXEC | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


@contextmanager
def blocked_termination_signals():
    signals = (signal.SIGINT, signal.SIGTERM, signal.SIGHUP)
    previous = signal.pthread_sigmask(signal.SIG_BLOCK, signals)
    try:
        yield
    finally:
        signal.pthread_sigmask(signal.SIG_SETMASK, previous)


def read_regular(path: Path) -> tuple[bytes, dict[str, Any]]:
    path = path.absolute()
    descriptor = os.open(path, os.O_RDONLY | os.O_CLOEXEC | getattr(os, "O_NOFOLLOW", 0))
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode):
            raise BridgeError(f"NOT_REGULAR:{path}")
        chunks: list[bytes] = []
        while True:
            block = os.read(descriptor, 1024 * 1024)
            if not block:
                break
            chunks.append(block)
        data = b"".join(chunks)
        after = os.fstat(descriptor)
        if (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns) != (
            after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns
        ):
            raise BridgeError(f"CHANGED_WHILE_READING:{path}")
    finally:
        os.close(descriptor)
    return data, {
        "path": str(path), "size_bytes": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
    }


def require_identity(path: Path, expected: Mapping[str, Any], label: str) -> tuple[bytes, dict[str, Any]]:
    data, identity = read_regular(path)
    if identity != dict(expected):
        raise BridgeError(f"{label}_SEALED_IDENTITY_MISMATCH")
    return data, identity


def validate_run_result(path: Path, crop_identity: Mapping[str, Any]) -> dict[str, Any]:
    payload, identity = require_identity(path, RUN_RESULT, "RUN_RESULT")
    def reject_constant(value: str) -> None:
        raise BridgeError(f"RUN_RESULT_NONFINITE_JSON:{value}")

    try:
        value = json.loads(payload.decode(), parse_constant=reject_constant)
    except (UnicodeError, json.JSONDecodeError) as error:
        raise BridgeError("RUN_RESULT_INVALID_JSON") from error
    if not isinstance(value, dict) or payload != canonical(value):
        raise BridgeError("RUN_RESULT_NOT_CANONICAL_OBJECT")
    if (
        value.get("schema_version") != "aqua-fe-hfnet-v6-a10-0000-2800-score-2400-2800-warmstart-result-v1"
        or value.get("status") != "PASS_DEVELOPMENT_RUNABILITY_RESCUE"
        or value.get("errors") != []
        or value.get("failure_codes") != []
    ):
        raise BridgeError("RUN_RESULT_TERMINAL_STATUS_MISMATCH")
    execution = value.get("execution")
    terminal = value.get("terminal_contract")
    claim = value.get("claim_boundary")
    if not isinstance(execution, dict) or (
        execution.get("popen_invocations") != 1
        or execution.get("raw_returncode") != 0
        or execution.get("retry_performed") is not False
        or execution.get("retry_permitted") is not False
        or execution.get("timed_out") is not False
        or execution.get("child_reaped_before_post_audit") is not True
        or execution.get("supervisor_error") is not None
    ):
        raise BridgeError("RUN_RESULT_EXECUTION_MISMATCH")
    if not isinstance(terminal, dict) or (
        terminal.get("attempt_consumed") is not True
        or terminal.get("retry_after_pass_or_fail") is not False
        or terminal.get("terminal_json_o_excl") is not True
    ):
        raise BridgeError("RUN_RESULT_TERMINAL_CONTRACT_MISMATCH")
    if not isinstance(claim, dict) or (
        claim.get("development_only") is not True
        or claim.get("accuracy_evaluated") is not False
        or claim.get("fair_head_to_head") is not False
        or claim.get("superiority_claimed") is not False
        or claim.get("formal_paper_claim_authorized") is not False
    ):
        raise BridgeError("RUN_RESULT_CLAIM_BOUNDARY_MISMATCH")
    adjudication = value.get("score_adjudication")
    score = adjudication.get("score") if isinstance(adjudication, dict) else None
    runtime = adjudication.get("runtime_log") if isinstance(adjudication, dict) else None
    if not isinstance(adjudication, dict) or adjudication.get("passed") is not True:
        raise BridgeError("RUN_RESULT_SCORE_NOT_PASSED")
    if not isinstance(score, dict) or (
        score.get("indices_inclusive") != [2400, 2800]
        or score.get("camera_count") != EXPECTED_ROWS
        or score.get("pose_count") != EXPECTED_ROWS
        or score.get("exact_401_of_401_contiguous") is not True
        or score.get("preroll_to_score_boundary_continuous") is not True
        or score.get("trajectory_crop") != crop_identity
        or score.get("trajectory_crop_error") is not None
    ):
        raise BridgeError("RUN_RESULT_SCORE_SUPPORT_MISMATCH")
    if not isinstance(runtime, dict) or (
        runtime.get("valid") is not True
        or runtime.get("pre_score_initialized") is not True
        or runtime.get("score_window_reset_events") != []
        or runtime.get("score_window_init_frame_ids") != []
        or len(runtime.get("reset_events", [])) != 22
        or runtime.get("init_frame_ids", [])[-1:] != [2355]
    ):
        raise BridgeError("RUN_RESULT_RUNTIME_HISTORY_MISMATCH")
    return {"identity": identity, "score_pose_count": EXPECTED_ROWS, "score_reset_count": 0, "prefix_reset_count": 22}


def parse_crop(payload: bytes) -> tuple[list[tuple[str, ...]], list[int]]:
    try:
        lines = payload.decode("ascii").splitlines()
    except UnicodeError as error:
        raise BridgeError("CROP_NOT_ASCII") from error
    if len(lines) != EXPECTED_ROWS or any(not line.strip() for line in lines):
        raise BridgeError("CROP_ROW_COUNT_OR_BLANK_MISMATCH")
    rows: list[tuple[str, ...]] = []
    stamps: list[int] = []
    for index, line in enumerate(lines):
        fields = line.split()
        if len(fields) != 8:
            raise BridgeError(f"ROW_FIELD_COUNT:{index}")
        try:
            decimal_stamp = Decimal(fields[0])
            values = [float(value) for value in fields[1:]]
        except (InvalidOperation, ValueError) as error:
            raise BridgeError(f"ROW_PARSE:{index}") from error
        if not decimal_stamp.is_finite() or decimal_stamp != decimal_stamp.to_integral_value():
            raise BridgeError(f"ROW_TIMESTAMP_NOT_INTEGER_NS:{index}")
        if not all(math.isfinite(value) for value in values):
            raise BridgeError(f"ROW_NONFINITE:{index}")
        norm = math.sqrt(sum(value * value for value in values[3:7]))
        if not 0.99 <= norm <= 1.01:
            raise BridgeError(f"ROW_QUATERNION_NORM:{index}")
        stamp = int(decimal_stamp)
        stamps.append(stamp)
        rows.append((str(stamp), fields[1], fields[2], fields[3], fields[7], fields[4], fields[5], fields[6]))
    if any(right <= left for left, right in zip(stamps, stamps[1:])):
        raise BridgeError("CROP_TIMESTAMPS_NOT_STRICT")
    if stamps[0] != EXPECTED_FIRST_NS or stamps[-1] != EXPECTED_LAST_NS:
        raise BridgeError("CROP_ENDPOINTS_MISMATCH")
    return rows, stamps


def output_payload(rows: Sequence[Sequence[str]]) -> bytes:
    return ("\n".join(",".join(row) for row in rows) + "\n").encode("ascii")


def publish(path: Path, payload: bytes) -> None:
    path = path.absolute()
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_symlink():
        raise BridgeError(f"OUTPUT_SYMLINK_FORBIDDEN:{path}")
    if path.exists():
        existing, _identity = read_regular(path)
        if existing != payload:
            raise BridgeError(f"OUTPUT_EXISTS_WITH_DIFFERENT_PAYLOAD:{path}")
        fsync_directory(path.parent)
        return
    temp = path.parent / f".{path.name}.tmp.{os.getpid()}.{secrets.token_hex(8)}"
    with blocked_termination_signals():
        descriptor = os.open(
            temp,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC
            | getattr(os, "O_NOFOLLOW", 0),
            0o600,
        )
        try:
            write_all(descriptor, payload)
            os.fchmod(descriptor, 0o444)
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        try:
            try:
                os.link(temp, path, follow_symlinks=False)
            except FileExistsError:
                existing, _identity = read_regular(path)
                if existing != payload:
                    raise BridgeError(f"OUTPUT_RACE_WITH_DIFFERENT_PAYLOAD:{path}")
            fsync_directory(path.parent)
        finally:
            try:
                temp.unlink()
            except FileNotFoundError:
                pass
            fsync_directory(path.parent)


def perform(source: Path, run_result: Path, output: Path | None) -> dict[str, Any]:
    crop_payload, crop_identity = require_identity(source, SCORE_CROP, "SCORE_CROP")
    rows, stamps = parse_crop(crop_payload)
    result_record = validate_run_result(run_result, crop_identity)
    record: dict[str, Any] = {
        "schema_version": SCHEMA,
        "status": "AUDIT_PASS_NO_WRITE" if output is None else "PASS_SEALED_BRIDGE",
        "source": crop_identity, "run_result": result_record, "row_count": len(rows),
        "first_stamp_ns": stamps[0], "last_stamp_ns": stamps[-1],
        "semantics": {
            "input_pose": "world_T_body", "input_quaternion_order": "xyzw",
            "output_pose": "world_T_body", "output_file_quaternion_order": "wxyz",
            "pose_transform_or_inversion_applied": False,
            "extrinsic_composition_applied": False, "alignment_applied": False,
            "interpolation_or_resampling_applied": False,
            "timestamp_scale_offset_or_snapping_applied": False,
        },
    }
    if output is not None:
        payload = output_payload(rows)
        manifest_path = Path(str(output.absolute()) + ".manifest.json")
        record["output"] = {
            "path": str(output.absolute()), "size_bytes": len(payload),
            "sha256": hashlib.sha256(payload).hexdigest(),
        }
        publish(output, payload)
        publish(manifest_path, canonical(record))
        record["manifest"] = read_regular(manifest_path)[1]
    return record


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=Path(SCORE_CROP["path"]))
    parser.add_argument("--run-result-json", type=Path, default=Path(RUN_RESULT["path"]))
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    try:
        result = perform(args.input, args.run_result_json, args.output)
        sys.stdout.buffer.write(canonical(result))
        return 0
    except (BridgeError, OSError) as error:
        print(f"CONTRACT_BLOCKED:{error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
