#!/usr/bin/env python3
"""Superseding v2 runner for the ten same-history HFNet cold-start cases.

The v1 runner was retired before any estimator start because its post-run
parser called ``int()`` on HFNet-SLAM's fixed-decimal EuRoC timestamp token
(for example ``1542885085174933504.000000``).  The official writer emits that
format even though the value is an integral nanosecond epoch.  This v2 wrapper
pins the complete v1 governance implementation, changes only the publication
namespace/schema identities, and replaces trajectory parsing with an exact
Decimal-to-integer bridge followed by unique 256 ns camera-header mapping.
"""

from __future__ import annotations

import bisect
from decimal import Decimal, InvalidOperation
import hashlib
import importlib.util
import math
from pathlib import Path
from typing import Any, Sequence


ROOT = Path(__file__).resolve().parents[1]
RUNNER = Path(__file__).resolve()
BASE_RUNNER = ROOT / "scripts/run_hfnet_v6_samehistory_positive_roster_v1.py"
BASE_RUNNER_SIZE = 80_696
BASE_RUNNER_SHA256 = (
    "9dc28f08b44c240b4623f519e6ee90dd02bbdbe177c9cacc5096aab638021ad3"
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


if (
    BASE_RUNNER.is_symlink()
    or not BASE_RUNNER.is_file()
    or BASE_RUNNER.stat().st_size != BASE_RUNNER_SIZE
    or _sha256(BASE_RUNNER) != BASE_RUNNER_SHA256
):
    raise RuntimeError("PINNED_V1_RUNNER_IDENTITY_MISMATCH")

_spec = importlib.util.spec_from_file_location(
    "_hfnet_v6_samehistory_positive_roster_v1_pinned", BASE_RUNNER
)
if _spec is None or _spec.loader is None:  # pragma: no cover - import machinery.
    raise RuntimeError("PINNED_V1_RUNNER_IMPORT_FAILED")
_v1 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_v1)


PUBLICATION_POINTER = Path(
    "/mnt/data/AQUA-FE_WS/locks/"
    "hfnet_v6_samehistory_positive_roster_execution_lock_v2.json"
)
ROSTER_ROOT = Path(
    "/mnt/data/AQUA-FE_WS/logs/published_hfnet_slam_v6/"
    "samehistory_old_positive_roster_v2"
)

# Keep the already audited v1 case/roster schemas.  Change every mutable
# attempt/result namespace so a v1 prepared attempt can never be mistaken for
# a v2 attempt.
PREPARED_SCHEMA = "aqua-fe-hfnet-v6-samehistory-positive-prepared-v2"
CLAIM_SCHEMA = "aqua-fe-hfnet-v6-samehistory-positive-process-claim-v2"
RESULT_SCHEMA = "aqua-fe-hfnet-v6-samehistory-positive-result-v2"
CASE_SCHEMA = "aqua-fe-hfnet-v6-samehistory-positive-case-v2"
ROSTER_LOCK_SCHEMA = "aqua-fe-hfnet-v6-samehistory-positive-roster-lock-v2"


def _integral_epoch_ns(token: str, row: int) -> int:
    """Parse an HFNet fixed-decimal epoch without binary floating point."""

    try:
        value = Decimal(token)
    except InvalidOperation as error:
        raise ValueError(f"ROW_{row}_TIMESTAMP_DECIMAL") from error
    if not value.is_finite() or value != value.to_integral_value():
        raise ValueError(f"ROW_{row}_TIMESTAMP_NOT_INTEGRAL_NS")
    return int(value)


def parse_trajectory(path: Path, stamps: Sequence[int]) -> dict[str, Any]:
    """Audit HFNet EuRoC output using its real fixed-decimal timestamp format."""

    result: dict[str, Any] = {
        "exists": path.is_file(),
        "valid": False,
        "pose_count": 0,
        "errors": [],
        "timestamp_serialization": "INTEGRAL_DECIMAL_NS",
        "association": "UNIQUE_SOURCE_CAMERA_HEADER_WITHIN_256_NS",
    }
    if not path.is_file():
        result["errors"] = ["MISSING"]
        return result
    if not stamps or any(right <= left for left, right in zip(stamps, stamps[1:])):
        result["errors"] = ["SOURCE_CAMERA_HEADERS_INVALID"]
        return result

    associated: list[int] = []
    used: set[int] = set()
    previous_serialized_stamp: int | None = None
    previous_header_index: int | None = None
    rows = [
        line
        for line in path.read_text(encoding="ascii").splitlines()
        if line.strip()
    ]
    for line_number, raw in enumerate(rows, start=1):
        fields = raw.split()
        if len(fields) != 8:
            result["errors"].append(f"ROW_{line_number}_FIELD_COUNT")
            continue
        try:
            stamp = _integral_epoch_ns(fields[0], line_number)
            pose = [float(value) for value in fields[1:]]
        except ValueError:
            result["errors"].append(f"ROW_{line_number}_PARSE")
            continue
        if not all(math.isfinite(value) for value in pose):
            result["errors"].append(f"ROW_{line_number}_NONFINITE")
            continue
        quaternion_norm = math.sqrt(sum(value * value for value in pose[3:7]))
        if abs(quaternion_norm - 1.0) > 1e-3:
            result["errors"].append(f"ROW_{line_number}_QUATERNION_NORM")
            continue
        if previous_serialized_stamp is not None and stamp <= previous_serialized_stamp:
            result["errors"].append(f"ROW_{line_number}_TIMESTAMP_NOT_STRICT")
            continue
        previous_serialized_stamp = stamp

        lower = bisect.bisect_left(stamps, stamp - _v1.ASSOCIATION_TOLERANCE_NS)
        upper = bisect.bisect_right(stamps, stamp + _v1.ASSOCIATION_TOLERANCE_NS)
        if upper - lower != 1:
            result["errors"].append(f"ROW_{line_number}_ASSOCIATION_NOT_UNIQUE")
            continue
        index = lower
        if index in used:
            result["errors"].append(f"ROW_{line_number}_SOURCE_HEADER_REUSED")
            continue
        if previous_header_index is not None and index <= previous_header_index:
            result["errors"].append(f"ROW_{line_number}_CANONICAL_HEADER_NOT_STRICT")
            continue
        used.add(index)
        associated.append(index)
        previous_header_index = index

    longest = 0
    longest_start: int | None = None
    longest_end: int | None = None
    current = 0
    current_start: int | None = None
    previous_index: int | None = None
    for index in associated:
        if previous_index is not None and index == previous_index + 1:
            current += 1
        else:
            current = 1
            current_start = index
        if current > longest:
            longest = current
            longest_start = current_start
            longest_end = index
        previous_index = index
    result.update(
        {
            "identity": _v1.identity(path),
            "valid": not result["errors"],
            "pose_count": len(associated),
            "first_relative_index": associated[0] if associated else None,
            "last_relative_index": associated[-1] if associated else None,
            "coverage_fraction": len(associated) / len(stamps),
            "longest_contiguous_count": longest,
            "longest_contiguous_fraction": longest / len(stamps),
            "longest_contiguous_relative_indices_inclusive": (
                [longest_start, longest_end]
                if longest_start is not None
                else None
            ),
        }
    )
    return result


# Rebind only prospective namespace/schema constants plus the fixed parser.
_v1.RUNNER = RUNNER
_v1.PUBLICATION_POINTER = PUBLICATION_POINTER
_v1.ROSTER_ROOT = ROSTER_ROOT
_v1.CASE_SCHEMA = CASE_SCHEMA
_v1.ROSTER_LOCK_SCHEMA = ROSTER_LOCK_SCHEMA
_v1.PREPARED_SCHEMA = PREPARED_SCHEMA
_v1.CLAIM_SCHEMA = CLAIM_SCHEMA
_v1.RESULT_SCHEMA = RESULT_SCHEMA
_v1.parse_trajectory = parse_trajectory


def main(argv: Sequence[str] | None = None) -> int:
    return _v1.main(argv)


if __name__ == "__main__":
    raise SystemExit(main())
