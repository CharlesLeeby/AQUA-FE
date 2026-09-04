#!/usr/bin/env python3
"""Prepare support-only A08 HFNet bridge inputs without computing accuracy."""

from __future__ import annotations

import argparse
from bisect import bisect_left
import ctypes
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import errno
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import stat
import tempfile
from typing import Any, Optional


ROOT = Path("/home/ma/AQUA-FE_WS")
PROTOCOL = ROOT / "papers/a08_hfnet_history_matched_support_extension_v1_protocol.md"
TERMINAL = ROOT / "papers/hfnet_v6_a08_0000_4660_score_4500_4660_todesk_corun_terminal_outcome_freeze_v1.json"
ATTEMPT = Path(
    "/mnt/data/AQUA-FE_WS/logs/published_hfnet_slam_v6/corun/"
    "old_frozen_positive_windows/"
    "a08_0000_4660_score_4500_4660_todesk_corun_development_only/attempt_001"
)
SOURCE_TIMES = ATTEMPT / "cam0_times_source_0000_4660_local_0000_4660.txt"
HFNET_TRAJECTORY = ATTEMPT / "result/trajectory.txt"
RUN_RESULT = ATTEMPT / "run_result.json"
BODY_T_CAM0 = ROOT / "configs/published_baselines/hfnet_aqualoc_a02_body_T_cam0_v1.yaml"
GT = ROOT / (
    "datasets/full_downloads/aqualoc/Archaeological_site_sequences/"
    "archaeo_groundtruth_files/new_archaeo_colmap_traj_sequence_08.txt"
)
DEFAULT_OUTPUT = Path(
    "/mnt/data/AQUA-FE_WS/experiments/"
    "a08_hfnet_history_matched_support_extension_v1/evaluation_inputs"
)

START_INDEX = 4000
END_INDEX = 4660
POSITIVE_START_INDEX = 4500
START_NS = 1_542_885_161_111_831_216
POSITIVE_START_NS = 1_542_885_186_107_583_632
END_NS = 1_542_885_194_106_222_672

PINS = {
    TERMINAL: (6338, "e9d93aff74f5614c380be46710f7857a7ac6198477cb052cc1f0faffae73a527"),
    SOURCE_TIMES: (93220, "0ce637bc6e9e74a300dee7b40eb18e84962106fb7fc867d5d0eae83bf47f7662"),
    HFNET_TRAJECTORY: (245860, "ee1c860011890ebaeb07eba1fb064868bff0239a761356d1ead7b9d96e2a67ce"),
    RUN_RESULT: (31376, "5a6bfc1144b0b87d04b6cbef4918c42f0efdde04d49432b60b9d3b82c75863e1"),
    BODY_T_CAM0: (415, "a76c728b31d47c3a87f54c465fb581007ed2da2b7d7d84df81dbde93e9a886c1"),
    GT: (54593, "519d27750efd7e53c27a2bc3ff35bc9cf5c9fd2b888184eefea284bcfe8f2b6c"),
}


class PreparationError(RuntimeError):
    pass


def require(condition: bool, code: str) -> None:
    if not condition:
        raise PreparationError(code)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def identity(path: Path, reported_path: Optional[Path] = None) -> dict[str, Any]:
    return {
        "path": str(reported_path if reported_path is not None else path),
        "size_bytes": path.stat().st_size,
        "sha256": sha256(path),
    }


def require_pin(path: Path) -> dict[str, Any]:
    require(path.is_file() and not path.is_symlink(), f"NOT_REGULAR:{path}")
    result = identity(path)
    require(
        (result["size_bytes"], result["sha256"]) == PINS[path],
        f"IDENTITY_DRIFT:{path}",
    )
    return result


def require_no_symlink_ancestors(path: Path) -> None:
    """Reject a symlink in any already-existing output ancestor."""

    absolute = path.absolute()
    for ancestor in (absolute.parent, *absolute.parent.parents):
        if ancestor.exists() or ancestor.is_symlink():
            require(not ancestor.is_symlink(), f"OUTPUT_ANCESTOR_SYMLINK:{ancestor}")


def rename_noreplace(source: Path, destination: Path) -> None:
    """Atomically publish a directory without replacing a competing owner."""

    libc = ctypes.CDLL(None, use_errno=True)
    renameat2 = getattr(libc, "renameat2", None)
    require(renameat2 is not None, "RENAMEAT2_UNAVAILABLE")
    renameat2.argtypes = [
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_uint,
    ]
    renameat2.restype = ctypes.c_int
    result = renameat2(
        -100,
        os.fsencode(source),
        -100,
        os.fsencode(destination),
        1,
    )
    if result == 0:
        return
    error_number = ctypes.get_errno()
    if error_number == errno.EEXIST:
        raise PreparationError("OUTPUT_ALREADY_EXISTS_AT_PUBLISH")
    raise OSError(error_number, os.strerror(error_number), str(destination))


def publish_directory_noreplace(
    source: Path, destination: Path, receipt_name: str
) -> None:
    """Publish a complete directory without clobbering on limited filesystems.

    ``renameat2(RENAME_NOREPLACE)`` is preferred.  Some mounted filesystems
    return ``EINVAL`` for that flag; there we atomically claim the final
    directory with ``mkdir`` and hard-link regular files into it, publishing
    the completion receipt last.  A destination without the receipt is
    deliberately fail-closed after a crash.
    """

    try:
        rename_noreplace(source, destination)
        return
    except OSError as error:
        unsupported = {errno.EINVAL, errno.ENOSYS, errno.ENOTSUP}
        if hasattr(errno, "EOPNOTSUPP"):
            unsupported.add(errno.EOPNOTSUPP)
        if error.errno not in unsupported:
            raise

    require(source.is_dir() and not source.is_symlink(), "STAGE_NOT_REGULAR_DIRECTORY")
    os.mkdir(destination, 0o755)
    owner = os.lstat(destination)
    published: list[tuple[Path, tuple[int, int]]] = []
    try:
        children = list(source.iterdir())
        require(
            all(stat.S_ISREG(os.lstat(child).st_mode) and not child.is_symlink() for child in children),
            "STAGE_CONTAINS_NONREGULAR_ENTRY",
        )
        names = {child.name for child in children}
        require(receipt_name in names, "STAGE_RECEIPT_MISSING")
        ordered = sorted(
            children,
            key=lambda child: (child.name == receipt_name, child.name),
        )
        require(ordered[-1].name == receipt_name, "RECEIPT_NOT_LAST")
        for child in ordered:
            target = destination / child.name
            os.link(child, target, follow_symlinks=False)
            metadata = os.lstat(target)
            published.append((target, (metadata.st_dev, metadata.st_ino)))
        descriptor = os.open(destination, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        shutil.rmtree(source)
    except BaseException:
        for target, inode in reversed(published):
            try:
                metadata = os.lstat(target)
                if (metadata.st_dev, metadata.st_ino) == inode:
                    target.unlink()
            except FileNotFoundError:
                pass
        try:
            metadata = os.lstat(destination)
            if (
                (metadata.st_dev, metadata.st_ino) == (owner.st_dev, owner.st_ino)
                and not any(destination.iterdir())
            ):
                destination.rmdir()
        except (FileNotFoundError, OSError):
            pass
        raise


def parse_source_times(path: Path = SOURCE_TIMES) -> list[int]:
    values: list[int] = []
    for line_number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        text = raw.strip()
        require(text.isdigit(), f"SOURCE_TIME_GRAMMAR:{line_number}")
        values.append(int(text))
    require(len(values) == 4661, "SOURCE_TIME_COUNT")
    require(all(right > left for left, right in zip(values, values[1:])), "SOURCE_TIME_ORDER")
    require(values[START_INDEX] == START_NS, "SUPPORT_START_TIME")
    require(values[POSITIVE_START_INDEX] == POSITIVE_START_NS, "POSITIVE_START_TIME")
    require(values[END_INDEX] == END_NS, "SUPPORT_END_TIME")
    return values


def nearest_source_index(timestamp_ns: int, source_times: list[int]) -> tuple[int, int]:
    insertion = bisect_left(source_times, timestamp_ns)
    candidates = [
        index for index in (insertion - 1, insertion)
        if 0 <= index < len(source_times)
    ]
    require(bool(candidates), "NO_TIMESTAMP_CANDIDATE")
    index = min(candidates, key=lambda item: (abs(source_times[item] - timestamp_ns), item))
    return index, source_times[index] - timestamp_ns


def parse_hfnet_rows(
    source_times: list[int], path: Path = HFNET_TRAJECTORY
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line_number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not raw.strip():
            continue
        fields = raw.split()
        require(len(fields) == 8, f"HFNET_COLUMN_COUNT:{line_number}")
        try:
            printed_decimal = Decimal(fields[0])
            require(
                printed_decimal.is_finite()
                and printed_decimal == printed_decimal.to_integral_value(),
                f"HFNET_NONINTEGER_TIMESTAMP:{line_number}",
            )
            printed_ns = int(printed_decimal)
            numeric = [float(value) for value in fields[1:]]
        except (InvalidOperation, ValueError) as error:
            raise PreparationError(f"HFNET_NUMERIC_GRAMMAR:{line_number}") from error
        require(all(math.isfinite(value) for value in numeric), f"HFNET_NONFINITE:{line_number}")
        require(sum(value * value for value in numeric[3:7]) > 1e-12, f"HFNET_ZERO_QUATERNION:{line_number}")
        source_index, delta_ns = nearest_source_index(printed_ns, source_times)
        rows.append(
            {
                "line_number": line_number,
                "source_index": source_index,
                "exact_timestamp_ns": source_times[source_index],
                "rounding_delta_ns": delta_ns,
                "pose_fields": fields[1:],
            }
        )
    indices = [int(row["source_index"]) for row in rows]
    require(len(rows) == 2180, "HFNET_FULL_POSE_COUNT")
    require(indices == list(range(2481, 4661)), "HFNET_FULL_SOURCE_CONTINUITY")
    max_rounding = max(abs(int(row["rounding_delta_ns"])) for row in rows)
    require(max_rounding <= 128, "HFNET_TIMESTAMP_ROUNDING_TOO_LARGE")
    selected = [row for row in rows if START_INDEX <= int(row["source_index"]) <= END_INDEX]
    require(
        [int(row["source_index"]) for row in selected] == list(range(START_INDEX, END_INDEX + 1)),
        "HFNET_EXTENSION_NOT_CONTIGUOUS",
    )
    return selected, {
        "full_pose_count": len(rows),
        "full_source_indices_inclusive": [indices[0], indices[-1]],
        "extension_pose_count": len(selected),
        "extension_source_indices_inclusive": [START_INDEX, END_INDEX],
        "extension_exact_contiguous": True,
        "max_abs_printed_timestamp_rounding_ns": max_rounding,
        "timestamp_repair": "unique nearest frozen camera timestamp; no fitted offset",
    }


def validate_run_result(path: Path = RUN_RESULT) -> dict[str, Any]:
    try:
        result = json.loads(path.read_text(encoding="utf-8"))
        adjudication = result["score_adjudication"]
        runtime = adjudication["runtime_log"]
        init_frame_ids = runtime["init_frame_ids"]
        reset_events = runtime["reset_events"]
    except (json.JSONDecodeError, KeyError, TypeError) as error:
        raise PreparationError("RUN_RESULT_SCHEMA") from error
    require(
        result.get("status") == "PASS_DEVELOPMENT_RUNABILITY",
        "RUN_RESULT_NOT_PASS",
    )
    require(adjudication.get("passed") is True, "RUN_RESULT_ADJUDICATION_NOT_PASS")
    require(runtime.get("valid") is True, "RUN_RESULT_RUNTIME_NOT_VALID")
    require(runtime.get("reset_parse_complete") is True, "RUN_RESULT_RESET_PARSE_INCOMPLETE")
    require(runtime.get("unresolved_reset_events") == [], "RUN_RESULT_UNRESOLVED_RESET")
    require(init_frame_ids[-1] == 2473, "RUN_RESULT_FINAL_INITIALIZATION_DRIFT")
    require(
        reset_events[-1] == {"init_frame_id": 2413, "next_first_frame_id": 2423},
        "RUN_RESULT_FINAL_RESET_DRIFT",
    )
    require(max(init_frame_ids) < START_INDEX, "INITIALIZATION_INSIDE_EXTENSION")
    require(
        max(event["init_frame_id"] for event in reset_events) < START_INDEX,
        "RESET_INSIDE_EXTENSION",
    )
    return {
        "last_reset_init_frame_id": 2413,
        "last_reset_next_first_frame_id": 2423,
        "last_initialization_frame_id": 2473,
        "no_initialization_or_reset_in_extension": True,
    }


def parse_gt(path: Path = GT) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    for line_number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        fields = raw.split()
        require(len(fields) >= 8, f"GT_COLUMN_COUNT:{line_number}")
        try:
            index_float = float(fields[0])
            index = int(round(index_float))
            pose = [float(value) for value in fields[1:8]]
        except ValueError as error:
            raise PreparationError(f"GT_NUMERIC_GRAMMAR:{line_number}") from error
        require(abs(index_float - index) <= 1e-9, f"GT_NONINTEGER_INDEX:{line_number}")
        require(all(math.isfinite(value) for value in pose), f"GT_NONFINITE:{line_number}")
        if START_INDEX <= index <= END_INDEX:
            selected.append({"source_index": index, "pose_fields": fields[1:8]})
    expected = [
        index for index in range(START_INDEX, END_INDEX + 1, 20)
        if index not in (4400, 4640)
    ]
    require([int(row["source_index"]) for row in selected] == expected, "GT_EXTENSION_SUPPORT")
    return selected


def seconds_text(timestamp_ns: int) -> str:
    seconds, nanoseconds = divmod(timestamp_ns, 1_000_000_000)
    return f"{seconds}.{nanoseconds:09d}"


def preflight(output_dir: Path = DEFAULT_OUTPUT) -> dict[str, Any]:
    require(PROTOCOL.is_file() and not PROTOCOL.is_symlink(), "PROTOCOL_NOT_REGULAR")
    require_no_symlink_ancestors(output_dir)
    require(not output_dir.exists() and not output_dir.is_symlink(), "OUTPUT_ALREADY_EXISTS")
    inputs = {str(path): require_pin(path) for path in PINS}
    source_times = parse_source_times()
    selected, support = parse_hfnet_rows(source_times)
    gt = parse_gt()
    runtime = validate_run_result()
    require(len(selected) == 661, "EXTENSION_POSE_COUNT")
    require(len(gt) == 32, "EXTENSION_GT_COUNT")
    return {
        "status": "READY_SUPPORT_ONLY_PREPARATION",
        "output": str(output_dir),
        "inputs": inputs,
        "protocol": identity(PROTOCOL),
        "runner": identity(Path(__file__)),
        "support": support,
        "runtime": runtime,
        "gt_anchor_count": len(gt),
        "fixed_one_hz_grid_point_count": 33,
        "accuracy_computed": False,
    }


def prepare(output_dir: Path = DEFAULT_OUTPUT) -> dict[str, Any]:
    ready = preflight(output_dir)
    output_dir.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix=".a08_hfnet_support_extension_v1.", dir=str(output_dir.parent)))
    try:
        source_times = parse_source_times()
        selected, support = parse_hfnet_rows(source_times)
        gt_rows = parse_gt()

        bridge = stage / "hfnet_world_T_body_support_source_4000_4660.vio.csv"
        bridge_lines: list[str] = []
        for row in selected:
            x, y, z, qx, qy, qz, qw = row["pose_fields"]
            bridge_lines.append(
                ",".join((str(row["exact_timestamp_ns"]), x, y, z, qw, qx, qy, qz))
            )
        bridge.write_text("\n".join(bridge_lines) + "\n", encoding="utf-8")

        config = stage / "hfnet_aqualoc_body_T_cam0.yaml"
        shutil.copyfile(BODY_T_CAM0, config)
        require(
            (config.stat().st_size, sha256(config)) == PINS[BODY_T_CAM0],
            "COPIED_BODY_T_CAM0_IDENTITY_DRIFT",
        )

        reference = stage / "a08_reference_source_4000_4660.tum"
        reference_lines = [
            " ".join(
                [seconds_text(source_times[int(row["source_index"])])] + list(row["pose_fields"])
            )
            for row in gt_rows
        ]
        reference.write_text("\n".join(reference_lines) + "\n", encoding="utf-8")

        receipt = {
            "schema_version": "aqua-fe-a08-hfnet-history-matched-support-extension-preparation-v1",
            "status": "PASS_SUPPORT_ONLY_PREPARATION_NO_ACCURACY",
            "created_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "inputs": ready["inputs"],
            "protocol": ready["protocol"],
            "runner": ready["runner"],
            "support": support,
            "runtime": ready["runtime"],
            "fixed_one_hz_grid_point_count": 33,
            "historical_positive_subwindow_source_indices_inclusive": [4500, 4660],
            "gt_anchor_count": len(gt_rows),
            "artifacts": {
                "hfnet_world_T_body_vins_csv_bridge": identity(
                    bridge, output_dir / bridge.name
                ),
                "hfnet_body_T_cam0_config": identity(config, output_dir / config.name),
                "reference_tum": identity(reference, output_dir / reference.name),
            },
            "claim_boundary": {
                "hfnet_pose_semantics": "world_T_body",
                "frozen_body_T_cam0_applied_only_by_downstream_evaluator": True,
                "identity_extrinsic_used": False,
                "source_hfnet_trajectory_edited": False,
                "fitted_time_offset": False,
                "ape_or_rpe_computed": False,
                "ranking_supported": False,
            },
        }
        receipt_path = stage / "support_preparation_receipt_v1.json"
        receipt_path.write_text(
            json.dumps(receipt, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        publish_directory_noreplace(
            stage, output_dir, "support_preparation_receipt_v1.json"
        )
        return {
            "status": receipt["status"],
            "output": str(output_dir),
            "support": support,
            "artifacts": receipt["artifacts"],
        }
    except Exception:
        shutil.rmtree(stage, ignore_errors=True)
        raise


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("preflight", "prepare"))
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    try:
        result = preflight(args.output_dir) if args.command == "preflight" else prepare(args.output_dir)
        print(json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False))
        return 0
    except (PreparationError, OSError, ValueError) as error:
        print(f"PREPARATION_ERROR:{error}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
