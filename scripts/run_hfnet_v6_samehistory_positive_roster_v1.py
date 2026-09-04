#!/usr/bin/env python3
"""Govern one exact-window HFNet-v6 cold-start attempt from a frozen case spec.

The historical AQUA-FE positives were produced by starting each estimator at
the beginning of the selected window.  This runner preserves that history: it
passes exactly the materialized window to HFNet, never a natural-history
prefix.  It prepares an attempt atomically, claims the sole process start with
O_EXCL, starts one child, never retries, reaps the child, and audits inputs and
outputs after termination.

This runner does not calculate APE/RPE.  A PASS means that the external system
produced a usable trajectory on at least 70% of the cold-start window without
an active-map reset.  Accuracy remains a separate common-support operation.
"""

from __future__ import annotations

import argparse
import bisect
from contextlib import contextmanager
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import time
from typing import Any, Mapping, Sequence


ROOT = Path(__file__).resolve().parents[1]
RUNNER = Path(__file__).resolve()

CASE_SCHEMA = "aqua-fe-hfnet-v6-samehistory-positive-case-v1"
PREPARED_SCHEMA = "aqua-fe-hfnet-v6-samehistory-positive-prepared-v1"
CLAIM_SCHEMA = "aqua-fe-hfnet-v6-samehistory-positive-process-claim-v1"
RESULT_SCHEMA = "aqua-fe-hfnet-v6-samehistory-positive-result-v1"
ROSTER_LOCK_SCHEMA = "aqua-fe-hfnet-v6-samehistory-positive-roster-lock-v1"
AUDIT_BINDING_SCHEMA = "aqua-fe-hfnet-v6-samehistory-input-audit-binding-v1"
PUBLICATION_POINTER_SCHEMA = (
    "aqua-fe-hfnet-v6-samehistory-roster-publication-pointer-v1"
)
EXPECTED_ROSTER_SIZE = 10

PUBLICATION_POINTER = Path(
    "/mnt/data/AQUA-FE_WS/locks/"
    "hfnet_v6_samehistory_positive_roster_execution_lock_v1.json"
)

ROSTER_ROOT = Path(
    "/mnt/data/AQUA-FE_WS/logs/published_hfnet_slam_v6/"
    "samehistory_old_positive_roster_v1"
)

BINARY = (
    ROOT
    / "build/published_baselines/hfnet_slam_headless_entry_v3"
    / "mono_inertial_euroc_headless_v3"
)
OFFICIAL_LIBRARY = Path(
    "/home/ma/SLAM/HFNet-SLAM-paper-2023-build-r1/lib/libHFNet_SLAM.so"
)
SHARED_MODEL = Path(
    "/home/ma/SLAM/HFNet-SLAM-runtime-model-a02-r1/HFNet-RT/HF-Net.onnx"
)
SHARED_CACHE = Path(
    "/home/ma/SLAM/HFNet-SLAM-runtime-model-a02-r1/HFNet-RT/HF-Net.cache"
)

EXPECTED_STACK = {
    "binary": (
        118_280,
        "4d17eecc74ec8f4bcbe4381d579d2bb48160cf63f6dc948f7857d92e681affeb",
    ),
    "official_library": (
        4_807_712,
        "a56dfd1b48dee4af5be4e55b076d32eac2cf8fb463da8ab943b690377f193717",
    ),
    "onnx": (
        132_238_602,
        "354a23f9c28b75ea9056a8eb5586e3b13191426521fd3f5556e5bfd670fc39b5",
    ),
    "cache": (
        853_319,
        "6798ef896e4f503d4d81827a81fc9dad99d40c5e10352abbe974ed309bd0c0e7",
    ),
}

MODEL_PATH_LINE = (
    'Extractor.modelPath: '
    '"/home/ma/SLAM/HFNet-SLAM-runtime-model-a02-r1/HFNet-RT/"'
)
MIN_COVERAGE = 0.70
MIN_CONTIGUOUS = 0.70
ASSOCIATION_TOLERANCE_NS = 256


class ContractError(RuntimeError):
    """A prospective or post-run contract was violated."""


class ClaimedBoundaryError(ContractError):
    """The O_EXCL start boundary exists, but durable publication raised."""


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


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


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def core_spec_sha256(spec: Mapping[str, Any]) -> str:
    """Hash the case spec without its intentionally circular roster-lock pin."""
    core = dict(spec)
    core.pop("roster_lock", None)
    return sha256_bytes(canonical_json(core))


def canonical_attempt_root(case_id: str) -> Path:
    return ROSTER_ROOT / case_id / "attempt_001"


def permanent_case_paths(case_id: str) -> dict[str, Path]:
    root = ROSTER_ROOT / "_case_claims"
    return {
        "reservation": root / f"{case_id}.start_once",
        "claim": root / f"{case_id}.process_start_claim.json",
    }


def global_lock_path() -> Path:
    return ROSTER_ROOT / ".gpu_serial.lock"


def _relative_contract_path(value: Any, label: str) -> str:
    path = Path(str(value))
    if path.is_absolute() or not path.parts or any(part in ("", ".", "..") for part in path.parts):
        raise ContractError(f"RELATIVE_PATH_INVALID:{label}:{path}")
    return path.as_posix()


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _ensure_plain_directory(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    if path.is_symlink() or not path.is_dir():
        raise ContractError(f"DIRECTORY_MISSING_OR_SYMLINK:{path}")


def _atomic_publish_exclusive(path: Path, payload: bytes, mode: int = 0o444) -> None:
    """Publish complete bytes with same-filesystem hard-link no-replace semantics."""
    _ensure_plain_directory(path.parent)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.publish-", dir=str(path.parent)
    )
    temporary = Path(temporary_name)
    published = False
    try:
        os.fchmod(descriptor, mode)
        with os.fdopen(descriptor, "wb") as stream:
            descriptor = -1
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(temporary, path, follow_symlinks=False)
        except FileExistsError as error:
            raise ContractError(f"EXCLUSIVE_PUBLICATION_EXISTS:{path}") from error
        published = True
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass
        if published:
            _fsync_directory(path.parent)


def _copy_file_atomic_exclusive(
    source: Path,
    target: Path,
    expected: Mapping[str, Any],
    mode: int = 0o444,
) -> dict[str, object]:
    """Copy, fsync, verify, and hard-link-publish one immutable large file."""
    _ensure_plain_directory(target.parent)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{target.name}.publish-", dir=str(target.parent)
    )
    temporary = Path(temporary_name)
    published = False
    try:
        os.fchmod(descriptor, mode)
        with source.open("rb") as input_stream, os.fdopen(
            descriptor, "wb"
        ) as output_stream:
            descriptor = -1
            shutil.copyfileobj(input_stream, output_stream, length=1024 * 1024)
            output_stream.flush()
            os.fsync(output_stream.fileno())
        observed_temporary = identity(temporary)
        if (
            observed_temporary["size_bytes"] != int(expected["size_bytes"])
            or observed_temporary["sha256"] != expected["sha256"]
        ):
            raise ContractError(f"COPIED_FILE_IDENTITY_MISMATCH:{source}")
        try:
            os.link(temporary, target, follow_symlinks=False)
        except FileExistsError as error:
            raise ContractError(f"EXCLUSIVE_PUBLICATION_EXISTS:{target}") from error
        published = True
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass
        if published:
            _fsync_directory(target.parent)
    return identity(target)


def _write_o_excl_reservation(path: Path, payload: bytes) -> None:
    """Create the permanent start-once boundary before any estimator Popen."""
    _ensure_plain_directory(path.parent)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags, 0o444)
    failure: BaseException | None = None
    try:
        view = memoryview(payload)
        while view:
            written = os.write(descriptor, view)
            if written <= 0:
                raise OSError("short write while publishing O_EXCL reservation")
            view = view[written:]
        os.fsync(descriptor)
    except BaseException as error:
        failure = error
    try:
        os.close(descriptor)
    except BaseException as error:
        failure = failure or error
    if failure is not None:
        raise ClaimedBoundaryError(
            f"O_EXCL_RESERVATION_CREATED_BUT_FILE_SYNC_FAILED:{path}:"
            f"{type(failure).__name__}:{failure}"
        ) from failure
    try:
        _fsync_directory(path.parent)
    except BaseException as error:
        raise ClaimedBoundaryError(
            f"O_EXCL_RESERVATION_CREATED_BUT_DIRECTORY_SYNC_FAILED:{path}:"
            f"{type(error).__name__}:{error}"
        ) from error


def _fsync_tree(root: Path) -> None:
    directories: list[Path] = []
    for directory, child_directories, files in os.walk(root):
        current = Path(directory)
        directories.append(current)
        for name in files:
            path = current / name
            if path.is_symlink() or not path.is_file():
                raise ContractError(f"STAGING_TREE_NONREGULAR_FILE:{path}")
            descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
            try:
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
        for name in child_directories:
            if (current / name).is_symlink():
                raise ContractError(f"STAGING_TREE_SYMLINK_DIRECTORY:{current / name}")
    for directory in reversed(directories):
        _fsync_directory(directory)


def _mkdir_exclusive(path: Path, mode: int = 0o755) -> None:
    """Reserve a canonical namespace with mkdir's portable no-clobber boundary."""
    try:
        os.mkdir(path, mode)
    except FileExistsError as error:
        raise ContractError(f"EXCLUSIVE_DIRECTORY_PUBLICATION_EXISTS:{path}") from error
    _fsync_directory(path.parent)


def _record_prepare_incident(
    paths: Mapping[str, Path], spec: Mapping[str, Any], error: BaseException
) -> None:
    incident = paths["root"] / "preparation_incident.json"
    payload = canonical_json(
        {
            "schema_version": (
                "aqua-fe-hfnet-v6-samehistory-positive-preparation-incident-v1"
            ),
            "status": "INCOMPLETE_PREPARATION_NOT_RUNNABLE",
            "recorded_at_utc": now_utc(),
            "case_id": spec.get("case_id"),
            "attempt_root": str(paths["root"]),
            "error": f"{type(error).__name__}:{error}",
            "prepared_manifest_published": paths["prepared"].is_file(),
            "process_claim_published": paths["claim"].is_file(),
        }
    )
    _atomic_publish_exclusive(incident, payload)


def _cleanup_incomplete_owned_attempt(
    paths: Mapping[str, Path], spec: Mapping[str, Any], error: BaseException
) -> None:
    """Remove our mkdir-reserved incomplete tree or leave an explicit incident."""
    permanent = permanent_case_paths(str(spec["case_id"]))
    claim_boundary_exists = any(
        path.exists() or path.is_symlink()
        for path in (
            paths["claim"],
            permanent["reservation"],
            permanent["claim"],
        )
    )
    if claim_boundary_exists:
        return
    if paths["prepared"].exists() or paths["prepared"].is_symlink():
        _record_prepare_incident(paths, spec, error)
        return
    cleanup_error: BaseException | None = None
    try:
        shutil.rmtree(paths["root"])
        _fsync_directory(paths["root"].parent)
        return
    except BaseException as observed:
        cleanup_error = observed
    if paths["root"].is_dir() and not paths["root"].is_symlink():
        try:
            _record_prepare_incident(paths, spec, error)
            return
        except BaseException as incident_error:
            raise ContractError(
                "PREPARATION_CLEANUP_AND_INCIDENT_PUBLICATION_FAILED:"
                f"cleanup={type(cleanup_error).__name__}:{cleanup_error};"
                f"incident={type(incident_error).__name__}:{incident_error}"
            ) from error
    raise ContractError(
        "PREPARATION_CLEANUP_FAILED:"
        f"{type(cleanup_error).__name__}:{cleanup_error}"
    ) from error


@contextmanager
def global_serial_lock() -> Any:
    """Hold one cooperative GPU/estimator lock for the entire formal boundary."""
    path = global_lock_path()
    _ensure_plain_directory(path.parent)
    flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags, 0o644)
    try:
        observed = os.fstat(descriptor)
        if not stat.S_ISREG(observed.st_mode):
            raise ContractError(f"GLOBAL_LOCK_NOT_REGULAR:{path}")
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise ContractError("GLOBAL_SERIAL_LOCK_BUSY") from error
        yield {
            "path": str(path),
            "pid": os.getpid(),
            "acquired_at_utc": now_utc(),
        }
    finally:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
        finally:
            os.close(descriptor)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def identity(path: Path) -> dict[str, object]:
    if path.is_symlink() or not path.is_file():
        raise ContractError(f"NOT_REGULAR_NONSYMLINK_FILE:{path}")
    return {
        "path": str(path.resolve()),
        "size_bytes": path.stat().st_size,
        "sha256": sha256_file(path),
    }


def safe_identity(path: Path) -> dict[str, object]:
    try:
        return identity(path)
    except Exception as error:
        return {
            "path": str(path),
            "identity_error": f"{type(error).__name__}:{error}",
        }


def require_pin(path: Path, expected: Mapping[str, Any], label: str) -> dict[str, object]:
    observed = identity(path)
    if (
        observed["size_bytes"] != int(expected.get("size_bytes", -1))
        or observed["sha256"] != expected.get("sha256")
    ):
        raise ContractError(f"IDENTITY_MISMATCH:{label}:{path}")
    return observed


def require_stack() -> dict[str, object]:
    result: dict[str, object] = {}
    for label, path, key in (
        ("binary", BINARY, "binary"),
        ("official_library", OFFICIAL_LIBRARY, "official_library"),
        ("shared_onnx", SHARED_MODEL, "onnx"),
        ("shared_cache", SHARED_CACHE, "cache"),
    ):
        size, digest = EXPECTED_STACK[key]
        result[label] = require_pin(
            path,
            {"size_bytes": size, "sha256": digest},
            label,
        )
    return result


def load_json(path: Path) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise ContractError(f"JSON_MISSING_OR_NOT_REGULAR:{path}")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ContractError(f"JSON_ROOT_NOT_OBJECT:{path}")
    return value


def _absolute_nonsymlink_directory(value: Any, label: str) -> Path:
    path = Path(str(value))
    if not path.is_absolute():
        raise ContractError(f"PATH_NOT_ABSOLUTE:{label}")
    if path.is_symlink() or not path.is_dir():
        raise ContractError(f"DIRECTORY_MISSING_OR_SYMLINK:{label}:{path}")
    return path


def input_layout(spec: Mapping[str, Any]) -> dict[str, str]:
    extension = str(spec.get("image_extension", ".png"))
    if extension not in (".png", ".jpg", ".jpeg"):
        raise ContractError("IMAGE_EXTENSION_INVALID")
    return {
        "times_relative_path": _relative_contract_path(
            spec.get("times_relative_path", "cam0_times.txt"), "times_relative_path"
        ),
        "images_relative_path": _relative_contract_path(
            spec.get("images_relative_path", "mav0/cam0/data"),
            "images_relative_path",
        ),
        "image_extension": extension,
        "imu_relative_path": _relative_contract_path(
            spec.get("imu_relative_path", "mav0/imu0/data.csv"),
            "imu_relative_path",
        ),
    }


def expected_input_audit_binding(
    spec: Mapping[str, Any],
    input_root: Path,
    input_manifest: Mapping[str, object],
    base_config: Mapping[str, object],
) -> dict[str, object]:
    layout = input_layout(spec)
    return {
        "schema_version": AUDIT_BINDING_SCHEMA,
        "case_id": spec["case_id"],
        "input_root": str(input_root.resolve()),
        "input_manifest": dict(input_manifest),
        "base_config": dict(base_config),
        "camera_count": spec["camera_count"],
        "camera_header_ns_inclusive": spec["camera_header_ns_inclusive"],
        "score_relative_indices_inclusive": spec[
            "score_relative_indices_inclusive"
        ],
        "history": "EXACT_WINDOW_COLD_START_NO_PRIOR_CAMERA_HISTORY",
        **layout,
        "imu_reader_bracket_valid": True,
    }


def require_roster_lock(spec: Mapping[str, Any]) -> dict[str, object]:
    pin = spec.get("roster_lock")
    if not isinstance(pin, Mapping):
        raise ContractError("ROSTER_LOCK_PIN_MISSING")
    path = Path(str(pin.get("path", "")))
    observed = require_pin(path, pin, "roster_lock")
    lock = load_json(path)
    if lock.get("schema_version") != ROSTER_LOCK_SCHEMA:
        raise ContractError("ROSTER_LOCK_SCHEMA_MISMATCH")
    if lock.get("status") != "FROZEN_READY_FOR_EXECUTION":
        raise ContractError("ROSTER_LOCK_STATUS_MISMATCH")
    rows = lock.get("cases")
    if not isinstance(rows, list) or len(rows) != EXPECTED_ROSTER_SIZE:
        raise ContractError("ROSTER_LOCK_CASE_COUNT_MISMATCH")
    if lock.get("case_count") != EXPECTED_ROSTER_SIZE:
        raise ContractError("ROSTER_LOCK_DECLARED_CASE_COUNT_MISMATCH")
    case_ids: list[str] = []
    attempt_roots: list[str] = []
    selected: Mapping[str, Any] | None = None
    for row in rows:
        if not isinstance(row, Mapping):
            raise ContractError("ROSTER_LOCK_CASE_ROW_INVALID")
        case_id = row.get("case_id")
        attempt_root = row.get("attempt_root")
        digest = row.get("core_spec_sha256")
        if (
            not isinstance(case_id, str)
            or not isinstance(attempt_root, str)
            or not re.fullmatch(r"[0-9a-f]{64}", str(digest))
        ):
            raise ContractError("ROSTER_LOCK_CASE_ROW_INVALID")
        if attempt_root != str(canonical_attempt_root(case_id)):
            raise ContractError("ROSTER_LOCK_NONCANONICAL_ATTEMPT_ROOT")
        case_ids.append(case_id)
        attempt_roots.append(attempt_root)
        if case_id == spec.get("case_id"):
            selected = row
    if len(set(case_ids)) != len(case_ids):
        raise ContractError("ROSTER_LOCK_DUPLICATE_CASE_ID")
    if len(set(attempt_roots)) != len(attempt_roots):
        raise ContractError("ROSTER_LOCK_DUPLICATE_ATTEMPT_ROOT")
    if selected is None:
        raise ContractError("CASE_MISSING_FROM_ROSTER_LOCK")
    if selected.get("attempt_root") != str(spec.get("attempt_root")):
        raise ContractError("ROSTER_LOCK_CASE_ATTEMPT_MISMATCH")
    if selected.get("core_spec_sha256") != core_spec_sha256(spec):
        raise ContractError("ROSTER_LOCK_CORE_SPEC_MISMATCH")
    if identity(path) != observed:
        raise ContractError("ROSTER_LOCK_CHANGED_DURING_VALIDATION")
    return {
        **observed,
        "schema_version": lock["schema_version"],
        "status": lock["status"],
        "case_count": len(rows),
        "case_core_spec_sha256": selected["core_spec_sha256"],
        "cases": [dict(row) for row in rows],
    }


def _exact_identity_pin(value: Any, label: str) -> dict[str, object]:
    if not isinstance(value, Mapping) or set(value) != {
        "path",
        "size_bytes",
        "sha256",
    }:
        raise ContractError(f"IDENTITY_PIN_FIELDS_INVALID:{label}")
    path = value.get("path")
    size = value.get("size_bytes")
    digest = value.get("sha256")
    if (
        not isinstance(path, str)
        or not Path(path).is_absolute()
        or not isinstance(size, int)
        or size < 0
        or not isinstance(digest, str)
        or not re.fullmatch(r"[0-9a-f]{64}", digest)
    ):
        raise ContractError(f"IDENTITY_PIN_VALUE_INVALID:{label}")
    return dict(value)


def require_publication_pointer(
    spec_path: Path,
    spec: Mapping[str, Any],
    roster_lock: Mapping[str, object],
) -> dict[str, object]:
    """Require the sole visible whole-roster commit, not a hidden bundle alone."""
    pointer_identity = identity(PUBLICATION_POINTER)
    pointer = load_json(PUBLICATION_POINTER)
    if pointer.get("schema_version") != PUBLICATION_POINTER_SCHEMA:
        raise ContractError("PUBLICATION_POINTER_SCHEMA_MISMATCH")
    if pointer.get("status") != "FROZEN_READY_FOR_EXECUTION":
        raise ContractError("PUBLICATION_POINTER_STATUS_MISMATCH")
    roster_pin = _exact_identity_pin(spec.get("roster_lock"), "roster_lock")
    observed_roster_identity = {
        "path": roster_lock["path"],
        "size_bytes": roster_lock["size_bytes"],
        "sha256": roster_lock["sha256"],
    }
    if pointer.get("roster_lock") != roster_pin:
        raise ContractError("PUBLICATION_POINTER_ROSTER_PIN_MISMATCH")
    if pointer.get("roster_lock") != observed_roster_identity:
        raise ContractError("PUBLICATION_POINTER_ROSTER_OBSERVED_MISMATCH")
    roster_parent = Path(str(observed_roster_identity["path"])).parent.resolve()
    bundle_root = Path(str(pointer.get("bundle_root", "")))
    expected_bundle_root = (
        PUBLICATION_POINTER.parent
        / (
            f".{PUBLICATION_POINTER.stem}.bundle-"
            f"{str(observed_roster_identity['sha256'])[:16]}"
        )
    ).resolve()
    if str(bundle_root) != str(expected_bundle_root):
        raise ContractError("PUBLICATION_POINTER_NONCANONICAL_BUNDLE_NAME")
    if not bundle_root.is_absolute() or str(bundle_root) != str(roster_parent):
        raise ContractError("PUBLICATION_POINTER_BUNDLE_ROOT_MISMATCH")
    if bundle_root.is_symlink() or not bundle_root.is_dir():
        raise ContractError("PUBLICATION_POINTER_BUNDLE_ROOT_INVALID")
    cases = pointer.get("cases")
    if not isinstance(cases, list) or len(cases) != EXPECTED_ROSTER_SIZE:
        raise ContractError("PUBLICATION_POINTER_CASE_COUNT_MISMATCH")
    roster_rows = roster_lock.get("cases")
    if not isinstance(roster_rows, list):
        raise ContractError("ROSTER_LOCK_CASE_ROWS_NOT_AVAILABLE")
    roster_by_case = {str(row["case_id"]): row for row in roster_rows}
    pointer_case_ids: list[str] = []
    selected: Mapping[str, Any] | None = None
    cases_root = bundle_root / "cases"
    if cases_root.is_symlink() or not cases_root.is_dir():
        raise ContractError("PUBLICATION_POINTER_CASES_DIRECTORY_INVALID")
    for row in cases:
        if not isinstance(row, Mapping) or set(row) != {
            "case_id",
            "spec",
            "core_spec_sha256",
        }:
            raise ContractError("PUBLICATION_POINTER_CASE_ROW_INVALID")
        case_id = row.get("case_id")
        if not isinstance(case_id, str) or case_id not in roster_by_case:
            raise ContractError("PUBLICATION_POINTER_CASE_ID_INVALID")
        pointer_case_ids.append(case_id)
        roster_row = roster_by_case[case_id]
        if row.get("core_spec_sha256") != roster_row.get("core_spec_sha256"):
            raise ContractError("PUBLICATION_POINTER_CASE_CORE_ROSTER_MISMATCH")
        spec_pin = _exact_identity_pin(row.get("spec"), f"case_spec:{case_id}")
        expected_spec_path = cases_root / f"{case_id}.json"
        if spec_pin["path"] != str(expected_spec_path):
            raise ContractError("PUBLICATION_POINTER_CASE_SPEC_PATH_MISMATCH")
        try:
            observed_spec = require_pin(
                expected_spec_path, spec_pin, f"case_spec:{case_id}"
            )
        except ContractError as error:
            raise ContractError(
                f"PUBLICATION_POINTER_CASE_SPEC_IDENTITY_MISMATCH:{case_id}"
            ) from error
        candidate_spec = load_json(expected_spec_path)
        if (
            candidate_spec.get("schema_version") != CASE_SCHEMA
            or candidate_spec.get("status")
            != "FROZEN_READY_FOR_ONE_SHOT_COLDSTART"
            or candidate_spec.get("case_id") != case_id
        ):
            raise ContractError("PUBLICATION_POINTER_CASE_SPEC_CONTRACT_MISMATCH")
        if candidate_spec.get("roster_lock") != roster_pin:
            raise ContractError("PUBLICATION_POINTER_CASE_ROSTER_PIN_MISMATCH")
        if candidate_spec.get("attempt_root") != roster_row.get("attempt_root"):
            raise ContractError("PUBLICATION_POINTER_CASE_ATTEMPT_ROSTER_MISMATCH")
        if core_spec_sha256(candidate_spec) != roster_row.get("core_spec_sha256"):
            raise ContractError("PUBLICATION_POINTER_CASE_CORE_SPEC_MISMATCH")
        if identity(expected_spec_path) != observed_spec:
            raise ContractError("PUBLICATION_POINTER_CASE_SPEC_CHANGED_DURING_VALIDATION")
        if case_id == spec.get("case_id"):
            selected = row
    if len(set(pointer_case_ids)) != len(pointer_case_ids):
        raise ContractError("PUBLICATION_POINTER_DUPLICATE_CASE_ID")
    if set(pointer_case_ids) != set(roster_by_case):
        raise ContractError("PUBLICATION_POINTER_ROSTER_CASE_SET_MISMATCH")
    if selected is None:
        raise ContractError("PUBLICATION_POINTER_SELECTED_CASE_MISSING")
    spec_identity = identity(spec_path)
    if selected.get("spec") != spec_identity:
        raise ContractError("PUBLICATION_POINTER_CASE_SPEC_IDENTITY_MISMATCH")
    if selected.get("core_spec_sha256") != core_spec_sha256(spec):
        raise ContractError("PUBLICATION_POINTER_CASE_CORE_SPEC_MISMATCH")
    claims = pointer.get("claims")
    if not isinstance(claims, dict) or not claims or any(
        value is not False for value in claims.values()
    ):
        raise ContractError("PUBLICATION_POINTER_CLAIMS_NOT_ALL_FALSE")
    receipt_pin = _exact_identity_pin(
        pointer.get("build_receipt"), "build_receipt"
    )
    expected_receipt_path = bundle_root / "build_receipt.json"
    if receipt_pin["path"] != str(expected_receipt_path):
        raise ContractError("PUBLICATION_POINTER_RECEIPT_PATH_MISMATCH")
    observed_receipt = require_pin(
        expected_receipt_path, receipt_pin, "build_receipt"
    )
    receipt = load_json(expected_receipt_path)
    if (
        receipt.get("schema_version")
        != "aqua-fe-hfnet-v6-samehistory-roster-build-receipt-v1"
    ):
        raise ContractError("BUILD_RECEIPT_SCHEMA_MISMATCH")
    if receipt.get("status") != "FROZEN_READY_FOR_EXECUTION":
        raise ContractError("BUILD_RECEIPT_STATUS_MISMATCH")
    if receipt.get("roster_lock") != pointer.get("roster_lock"):
        raise ContractError("BUILD_RECEIPT_ROSTER_MISMATCH")
    if receipt.get("cases") != cases:
        raise ContractError("BUILD_RECEIPT_CASES_MISMATCH")
    if receipt.get("claims") != claims:
        raise ContractError("BUILD_RECEIPT_CLAIMS_MISMATCH")
    if any(value is not False for value in receipt["claims"].values()):
        raise ContractError("BUILD_RECEIPT_CLAIMS_NOT_ALL_FALSE")
    if identity(expected_receipt_path) != observed_receipt:
        raise ContractError("BUILD_RECEIPT_CHANGED_DURING_VALIDATION")
    if identity(PUBLICATION_POINTER) != pointer_identity:
        raise ContractError("PUBLICATION_POINTER_CHANGED_DURING_VALIDATION")
    return {
        **pointer_identity,
        "schema_version": pointer["schema_version"],
        "status": pointer["status"],
        "bundle_root": str(bundle_root),
        "roster_lock": observed_roster_identity,
        "build_receipt": observed_receipt,
        "case_count": len(cases),
        "selected_case_spec": spec_identity,
        "selected_case_core_spec_sha256": selected["core_spec_sha256"],
    }


def require_frozen_dependencies(
    spec_path: Path, spec: Mapping[str, Any], input_root: Path
) -> dict[str, object]:
    """Validate every independent, cross-bound preparation dependency."""
    input_manifest = require_pin(
        Path(str(spec["input_manifest"]["path"])),
        spec["input_manifest"],
        "input_manifest",
    )
    base_config = require_pin(
        Path(str(spec["base_config"]["path"])),
        spec["base_config"],
        "base_config",
    )
    audit_pin = spec.get("input_audit")
    if not isinstance(audit_pin, Mapping):
        raise ContractError("INPUT_AUDIT_PIN_MISSING")
    expected_audit_schema = audit_pin.get("schema_version")
    if not isinstance(expected_audit_schema, str) or not expected_audit_schema:
        raise ContractError("INPUT_AUDIT_SCHEMA_PIN_MISSING")
    audit_path = Path(str(audit_pin.get("path", "")))
    input_audit = require_pin(audit_path, audit_pin, "input_audit")
    audit = load_json(audit_path)
    if audit.get("schema_version") != expected_audit_schema:
        raise ContractError("INPUT_AUDIT_SCHEMA_MISMATCH")
    if audit.get("status") != "PASS_PREPARATION_ONLY_INDEPENDENT_AUDIT":
        raise ContractError("INPUT_AUDIT_STATUS_MISMATCH")
    claims = audit.get("claims")
    if not isinstance(claims, dict) or not claims:
        raise ContractError("INPUT_AUDIT_CLAIMS_MISSING")
    if any(value is not False for value in claims.values()):
        raise ContractError("INPUT_AUDIT_FORBIDDEN_CLAIM")
    expected_binding = expected_input_audit_binding(
        spec, input_root, input_manifest, base_config
    )
    if audit.get("runner_binding") != expected_binding:
        raise ContractError("INPUT_AUDIT_RUNNER_BINDING_MISMATCH")
    roster_lock = require_roster_lock(spec)
    publication_pointer = require_publication_pointer(
        spec_path, spec, roster_lock
    )
    return {
        "input_manifest": input_manifest,
        "base_config": base_config,
        "input_audit": {
            **input_audit,
            "schema_version": audit["schema_version"],
            "status": audit["status"],
            "runner_binding": expected_binding,
        },
        "roster_lock": roster_lock,
        "publication_pointer": publication_pointer,
    }


def validate_spec(
    spec_path: Path, *, require_attempt_absent: bool = True
) -> tuple[dict[str, Any], dict[str, object]]:
    spec_identity = identity(spec_path)
    spec = load_json(spec_path)
    if spec.get("schema_version") != CASE_SCHEMA:
        raise ContractError("CASE_SPEC_SCHEMA_MISMATCH")
    if spec.get("status") != "FROZEN_READY_FOR_ONE_SHOT_COLDSTART":
        raise ContractError("CASE_SPEC_STATUS_MISMATCH")
    case_id = spec.get("case_id")
    if not isinstance(case_id, str) or not re.fullmatch(r"[a-z0-9_]+", case_id):
        raise ContractError("CASE_ID_INVALID")
    if spec.get("history") != "EXACT_WINDOW_COLD_START_NO_PRIOR_CAMERA_HISTORY":
        raise ContractError("CASE_HISTORY_MISMATCH")
    camera_count = spec.get("camera_count")
    if not isinstance(camera_count, int) or camera_count < 30:
        raise ContractError("CAMERA_COUNT_INVALID")
    camera_boundary = spec.get("camera_header_ns_inclusive")
    if (
        not isinstance(camera_boundary, list)
        or len(camera_boundary) != 2
        or any(not isinstance(value, int) for value in camera_boundary)
        or camera_boundary[1] <= camera_boundary[0]
    ):
        raise ContractError("CAMERA_HEADER_BOUNDARY_INVALID")
    if spec.get("score_relative_indices_inclusive") != [0, camera_count - 1]:
        raise ContractError("SCORE_NOT_WHOLE_COLDSTART_WINDOW")
    input_root = _absolute_nonsymlink_directory(spec.get("input_root"), "input_root")
    input_layout(spec)
    attempt_root = Path(str(spec.get("attempt_root")))
    if not attempt_root.is_absolute():
        raise ContractError("ATTEMPT_ROOT_NOT_ABSOLUTE")
    expected_attempt_root = canonical_attempt_root(case_id)
    if attempt_root != expected_attempt_root:
        raise ContractError(
            f"ATTEMPT_ROOT_NOT_CANONICAL:{attempt_root}:{expected_attempt_root}"
        )
    if require_attempt_absent:
        if attempt_root.exists() or attempt_root.is_symlink():
            raise ContractError(f"ATTEMPT_NAMESPACE_ALREADY_EXISTS:{attempt_root}")
        permanent = permanent_case_paths(case_id)
        if any(path.exists() or path.is_symlink() for path in permanent.values()):
            raise ContractError("PERMANENT_CASE_START_ALREADY_CLAIMED_NO_RETRY")
    elif attempt_root.is_symlink() or not attempt_root.is_dir():
        raise ContractError(f"ATTEMPT_NAMESPACE_MISSING_OR_SYMLINK:{attempt_root}")
    if input_root == attempt_root or input_root in attempt_root.parents:
        raise ContractError("ATTEMPT_OVERLAPS_INPUT_ROOT")
    timeout = spec.get("timeout_seconds")
    if not isinstance(timeout, int) or not 60 <= timeout <= 3600:
        raise ContractError("TIMEOUT_INVALID")
    token = spec.get("authorization_token")
    if not isinstance(token, str) or len(token) < 32:
        raise ContractError("AUTHORIZATION_TOKEN_INVALID")
    if spec.get("retry_permitted") is not False:
        raise ContractError("RETRY_MUST_BE_FALSE")
    if spec.get("accuracy_evaluated_by_runner") is not False:
        raise ContractError("RUNNER_ACCURACY_BOUNDARY_MISSING")

    require_frozen_dependencies(spec_path, spec, input_root)
    return spec, spec_identity


def selected_timestamps(spec: Mapping[str, Any]) -> list[int]:
    layout = input_layout(spec)
    path = Path(str(spec["input_root"])) / layout["times_relative_path"]
    rows = path.read_text(encoding="ascii").splitlines()
    try:
        stamps = [int(row) for row in rows if row.strip()]
    except ValueError as error:
        raise ContractError("CAMERA_TIMES_NOT_INTEGER") from error
    if len(stamps) != int(spec["camera_count"]):
        raise ContractError("CAMERA_TIMES_COUNT_MISMATCH")
    if any(right <= left for left, right in zip(stamps, stamps[1:])):
        raise ContractError("CAMERA_TIMES_NOT_STRICT")
    expected = spec["camera_header_ns_inclusive"]
    if expected != [stamps[0], stamps[-1]]:
        raise ContractError("CAMERA_TIME_BOUNDARY_MISMATCH")
    return stamps


def _parse_imu_stamps(path: Path) -> list[int]:
    lines = path.read_text(encoding="utf-8").splitlines()
    data = [line for line in lines if line.strip() and not line.startswith("#")]
    if len(data) < 2:
        raise ContractError("IMU_TOO_SHORT")
    try:
        stamps = [int(line.split(",", 1)[0]) for line in data]
    except ValueError as error:
        raise ContractError("IMU_TIME_PARSE_FAILED") from error
    if any(right <= left for left, right in zip(stamps, stamps[1:])):
        raise ContractError("IMU_TIMES_NOT_STRICT")
    return stamps


def input_inventory(spec: Mapping[str, Any], stamps: Sequence[int]) -> dict[str, object]:
    root = Path(str(spec["input_root"]))
    layout = input_layout(spec)
    image_root = root / layout["images_relative_path"]
    extension = layout["image_extension"]
    digest = hashlib.sha256()
    total = 0
    for stamp in stamps:
        path = image_root / f"{stamp}{extension}"
        item = identity(path)
        relative = path.relative_to(root).as_posix()
        digest.update(
            f"{relative}\0{item['size_bytes']}\0{item['sha256']}\n".encode("ascii")
        )
        total += int(item["size_bytes"])
    times_path = root / layout["times_relative_path"]
    imu_path = root / layout["imu_relative_path"]
    imu_stamps = _parse_imu_stamps(imu_path)
    first_imu, last_imu = imu_stamps[0], imu_stamps[-1]
    # The stock EuRoC reader advances from the beginning of the IMU vector
    # until it finds the first sample strictly after each camera timestamp.
    # Therefore legal input may retain any number of padding samples before
    # and after the camera window; the camera endpoints do not have to fall in
    # the first or last IMU pair.  Require the actual predecessor/successor
    # pairs that the reader will use instead.
    first_right = bisect.bisect_right(imu_stamps, stamps[0])
    last_right = bisect.bisect_right(imu_stamps, stamps[-1])
    if (
        first_right == 0
        or first_right >= len(imu_stamps)
        or last_right == 0
        or last_right >= len(imu_stamps)
    ):
        raise ContractError("IMU_READER_BRACKET_INVALID")
    reader_bracket = {
        "first_camera_ns": stamps[0],
        "first_camera_predecessor_imu_ns": imu_stamps[first_right - 1],
        "first_camera_successor_imu_ns": imu_stamps[first_right],
        "last_camera_ns": stamps[-1],
        "last_camera_predecessor_imu_ns": imu_stamps[last_right - 1],
        "last_camera_successor_imu_ns": imu_stamps[last_right],
    }
    return {
        "camera_count": len(stamps),
        "camera_header_ns_inclusive": [stamps[0], stamps[-1]],
        "image_total_bytes": total,
        "image_inventory_sha256": digest.hexdigest(),
        "times": identity(times_path),
        "imu": identity(imu_path),
        "imu_count": len(imu_stamps),
        "imu_header_ns_inclusive": [first_imu, last_imu],
        "imu_brackets_camera_window": True,
        "imu_reader_bracket_valid": True,
        "imu_reader_bracket": reader_bracket,
    }


def attempt_paths(spec: Mapping[str, Any]) -> dict[str, Path]:
    root = Path(str(spec["attempt_root"]))
    return {
        "root": root,
        "runtime_config": root / "runtime_config_model_path_only.yaml",
        "local_model": root / "run_local_model/HFNet-RT/HF-Net.onnx",
        "local_cache": root / "run_local_model/HFNet-RT/HF-Net.cache",
        "prepared": root / "prepared_manifest.json",
        "prepare_incident": root / "preparation_incident.json",
        "claim": root / "process_start_claim.json",
        "result": root / "run_result.json",
        "stdout": root / "headless.stdout.log",
        "stderr": root / "headless.stderr.log",
        "result_dir": root / "result",
    }


def runtime_config_bytes(base_config: Path, local_model: Path) -> bytes:
    source = base_config.read_text(encoding="utf-8")
    if source.count(MODEL_PATH_LINE) != 1:
        raise ContractError("BASE_CONFIG_MODEL_PATH_LINE_MISMATCH")
    replacement = f'Extractor.modelPath: "{local_model.parent}/"'
    return source.replace(MODEL_PATH_LINE, replacement).encode("utf-8")


def canonical_launch(
    spec: Mapping[str, Any], paths: Mapping[str, Path]
) -> dict[str, object]:
    layout = input_layout(spec)
    input_root = Path(str(spec["input_root"]))
    return {
        "argv": [
            str(BINARY),
            str(paths["runtime_config"]),
            str(paths["result_dir"]) + "/",
            str(input_root),
            str(input_root / layout["times_relative_path"]),
        ],
        "cwd": str(paths["root"]),
        "maximum_popen_invocations": 1,
    }


def canonical_scientific_boundary(spec: Mapping[str, Any]) -> dict[str, object]:
    return {
        "history": spec["history"],
        "score_relative_indices_inclusive": spec[
            "score_relative_indices_inclusive"
        ],
        "outcome_selected_historical_positive": True,
        "accuracy_evaluated": False,
        "retry_permitted": False,
    }


def expected_runtime_config_identity(
    spec: Mapping[str, Any], paths: Mapping[str, Path]
) -> dict[str, object]:
    payload = runtime_config_bytes(
        Path(str(spec["base_config"]["path"])), paths["local_model"]
    )
    return {
        "path": str(paths["runtime_config"]),
        "size_bytes": len(payload),
        "sha256": sha256_bytes(payload),
    }


def canonical_derived(
    spec: Mapping[str, Any], paths: Mapping[str, Path]
) -> dict[str, object]:
    return {
        "runtime_config": expected_runtime_config_identity(spec, paths),
        "local_onnx": {
            "path": str(paths["local_model"]),
            "size_bytes": EXPECTED_STACK["onnx"][0],
            "sha256": EXPECTED_STACK["onnx"][1],
        },
        "local_cache": {
            "path": str(paths["local_cache"]),
            "size_bytes": EXPECTED_STACK["cache"][0],
            "sha256": EXPECTED_STACK["cache"][1],
        },
    }


def prepare(spec_path: Path) -> dict[str, Any]:
    spec, spec_identity = validate_spec(spec_path)
    stamps = selected_timestamps(spec)
    inventory = input_inventory(spec, stamps)
    dependencies = require_frozen_dependencies(
        spec_path, spec, Path(str(spec["input_root"]))
    )
    stack = require_stack()
    paths = attempt_paths(spec)
    target = paths["root"]
    _ensure_plain_directory(target.parent)
    created_attempt = False
    try:
        try:
            os.mkdir(target, 0o755)
        except FileExistsError as error:
            raise ContractError(
                f"EXCLUSIVE_DIRECTORY_PUBLICATION_EXISTS:{target}"
            ) from error
        created_attempt = True
        _fsync_directory(target.parent)
        _mkdir_exclusive(target / "run_local_model")
        _mkdir_exclusive(target / "run_local_model/HFNet-RT")
        _mkdir_exclusive(paths["result_dir"])
        _copy_file_atomic_exclusive(
            SHARED_MODEL,
            paths["local_model"],
            {
                "size_bytes": EXPECTED_STACK["onnx"][0],
                "sha256": EXPECTED_STACK["onnx"][1],
            },
        )
        _copy_file_atomic_exclusive(
            SHARED_CACHE,
            paths["local_cache"],
            {
                "size_bytes": EXPECTED_STACK["cache"][0],
                "sha256": EXPECTED_STACK["cache"][1],
            },
        )
        base_config = Path(str(spec["base_config"]["path"]))
        _atomic_publish_exclusive(
            paths["runtime_config"],
            runtime_config_bytes(base_config, paths["local_model"]),
        )
        expected_derived = canonical_derived(spec, paths)
        for path_key, derived_key in (
            ("runtime_config", "runtime_config"),
            ("local_model", "local_onnx"),
            ("local_cache", "local_cache"),
        ):
            observed = identity(paths[path_key])
            expected = expected_derived[derived_key]
            if (
                observed["size_bytes"] != expected["size_bytes"]
                or observed["sha256"] != expected["sha256"]
            ):
                raise ContractError(f"STAGED_DERIVED_IDENTITY_MISMATCH:{derived_key}")
        manifest = {
            "schema_version": PREPARED_SCHEMA,
            "status": "PREPARED_NOT_STARTED",
            "prepared_at_utc": now_utc(),
            "case_id": spec["case_id"],
            "case_spec": spec_identity,
            "runner": identity(RUNNER),
            "stack": stack,
            "frozen_dependencies": dependencies,
            "input_inventory": inventory,
            "derived": expected_derived,
            "launch": canonical_launch(spec, paths),
            "scientific_boundary": canonical_scientific_boundary(spec),
        }
        # A directory on the formal fuseblk mount cannot use renameat2
        # RENAME_NOREPLACE.  Each immutable child is already link-published;
        # this manifest is the final completeness/visibility boundary.
        _fsync_tree(target)
        _atomic_publish_exclusive(paths["prepared"], canonical_json(manifest))
        return load_json(paths["prepared"])
    except BaseException as error:
        if created_attempt:
            _cleanup_incomplete_owned_attempt(paths, spec, error)
        raise


def load_prepared(spec_path: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    spec, _spec_identity = validate_spec(
        spec_path, require_attempt_absent=False
    )
    paths = attempt_paths(spec)
    if paths["prepare_incident"].exists() or paths["prepare_incident"].is_symlink():
        raise ContractError("PREPARATION_INCIDENT_PRESENT_NOT_RUNNABLE")
    prepared = load_json(paths["prepared"])
    if prepared.get("schema_version") != PREPARED_SCHEMA:
        raise ContractError("PREPARED_SCHEMA_MISMATCH")
    return spec, prepared


def require_prepared_contract(
    spec_path: Path, spec: Mapping[str, Any], prepared: Mapping[str, Any]
) -> dict[str, object]:
    paths = attempt_paths(spec)
    if paths["prepare_incident"].exists() or paths["prepare_incident"].is_symlink():
        raise ContractError("PREPARATION_INCIDENT_PRESENT_NOT_RUNNABLE")
    if paths["root"].is_symlink() or not paths["root"].is_dir():
        raise ContractError("PREPARED_ATTEMPT_ROOT_INVALID")
    if paths["result_dir"].is_symlink() or not paths["result_dir"].is_dir():
        raise ContractError("PREPARED_RESULT_DIRECTORY_INVALID")
    if prepared.get("status") != "PREPARED_NOT_STARTED":
        raise ContractError("PREPARED_STATUS_MISMATCH")
    if prepared.get("case_id") != spec.get("case_id"):
        raise ContractError("PREPARED_CASE_ID_MISMATCH")
    if prepared.get("case_spec") != identity(spec_path):
        raise ContractError("CASE_SPEC_DRIFT")
    runner = identity(RUNNER)
    if prepared.get("runner") != runner:
        raise ContractError("RUNNER_DRIFT")
    stack = require_stack()
    if prepared.get("stack") != stack:
        raise ContractError("PREPARED_STACK_MISMATCH")
    dependencies = require_frozen_dependencies(
        spec_path, spec, Path(str(spec["input_root"]))
    )
    if prepared.get("frozen_dependencies") != dependencies:
        raise ContractError("FROZEN_DEPENDENCY_DRIFT")
    stamps = selected_timestamps(spec)
    inventory = input_inventory(spec, stamps)
    if prepared.get("input_inventory") != inventory:
        raise ContractError("INPUT_INVENTORY_DRIFT")
    expected_derived = canonical_derived(spec, paths)
    if prepared.get("derived") != expected_derived:
        raise ContractError("PREPARED_DERIVED_CONTRACT_MISMATCH")
    for path_key, derived_key in (
        ("runtime_config", "runtime_config"),
        ("local_model", "local_onnx"),
        ("local_cache", "local_cache"),
    ):
        observed = identity(paths[path_key])
        expected = expected_derived[derived_key]
        if (
            observed["size_bytes"] != expected["size_bytes"]
            or observed["sha256"] != expected["sha256"]
        ):
            raise ContractError(f"DERIVED_FILE_DRIFT:{derived_key}")
    launch = canonical_launch(spec, paths)
    if prepared.get("launch") != launch:
        raise ContractError("PREPARED_LAUNCH_CONTRACT_MISMATCH")
    scientific = canonical_scientific_boundary(spec)
    if prepared.get("scientific_boundary") != scientific:
        raise ContractError("PREPARED_SCIENTIFIC_BOUNDARY_MISMATCH")
    return {
        "runner": runner,
        "stack": stack,
        "frozen_dependencies": dependencies,
        "input_inventory": inventory,
        "derived": expected_derived,
        "launch": launch,
        "scientific_boundary": scientific,
    }


def _process_record(proc_root: Path, pid: int) -> dict[str, object]:
    root = proc_root / str(pid)
    try:
        executable = os.readlink(root / "exe")
    except OSError:
        executable = ""
    try:
        comm = (root / "comm").read_text(encoding="utf-8", errors="replace").strip()
    except OSError:
        comm = ""
    try:
        raw = (root / "cmdline").read_bytes()
        tokens = [
            item.decode("utf-8", errors="replace")
            for item in raw.split(b"\0")
            if item
        ]
    except OSError:
        tokens = []
    return {
        "pid": pid,
        "executable": executable,
        "comm": comm,
        "command_tokens": tokens,
        "command": " ".join(tokens),
    }


def _process_names(record: Mapping[str, object], extra: str = "") -> set[str]:
    values = [str(record.get("executable", "")), str(record.get("comm", "")), extra]
    values.extend(str(value) for value in record.get("command_tokens", []))
    return {Path(value).name.lower() for value in values if value}


def _is_todesk_process(record: Mapping[str, object], process_name: str = "") -> bool:
    tokens = list(record.get("command_tokens", []))
    candidates = {
        Path(str(record.get("executable", ""))).name.lower(),
        Path(str(record.get("comm", ""))).name.lower(),
        Path(process_name).name.lower(),
    }
    if tokens:
        candidates.add(Path(str(tokens[0])).name.lower())
    return bool(candidates & {"todesk", "todesk_service", "todeskservice"})


def _is_forbidden_estimator_process(record: Mapping[str, object]) -> bool:
    forbidden = {
        "mono_inertial_euroc_headless_v3",
        "mono_inertial_euroc",
        "stereo_inertial_euroc",
        "vins_node",
        "roscore",
        "rosmaster",
        "roslaunch",
        "rosbag",
    }
    return bool(_process_names(record) & forbidden)


def resource_gate(
    *, proc_root: Path = Path("/proc"), command_runner: Any | None = None
) -> dict[str, Any]:
    errors: list[str] = []
    run_command = subprocess.run if command_runner is None else command_runner
    try:
        memory = run_command(
            [
                "nvidia-smi",
                "--query-gpu=name,uuid,driver_version,memory.total,memory.used,memory.free",
                "--format=csv,noheader,nounits",
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
        rows = [row.strip() for row in memory.stdout.splitlines() if row.strip()]
        if memory.returncode != 0 or not rows:
            raise ValueError("GPU_MEMORY_QUERY_INVALID")
        gpus: list[dict[str, object]] = []
        for index, row in enumerate(rows):
            fields = [item.strip() for item in row.split(",", 5)]
            if len(fields) != 6:
                raise ValueError("GPU_MEMORY_ROW_INVALID")
            gpus.append(
                {
                    "index": index,
                    "name": fields[0],
                    "uuid": fields[1],
                    "driver_version": fields[2],
                    "memory_total_mib": int(fields[3]),
                    "memory_used_mib": int(fields[4]),
                    "memory_free_mib": int(fields[5]),
                }
            )
        compute = run_command(
            [
                "nvidia-smi",
                "--query-compute-apps=pid,process_name,used_memory",
                "--format=csv,noheader,nounits",
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
        if compute.returncode != 0:
            raise ValueError("GPU_COMPUTE_QUERY_INVALID")
    except (OSError, subprocess.SubprocessError, ValueError) as error:
        return {
            "ready": False,
            "errors": [f"GPU_QUERY_FAILED:{type(error).__name__}:{error}"],
            "gpu_hardware_not_method_gated": True,
            "external_onnx_and_cache_still_frozen_stack": True,
        }

    applications = [row.strip() for row in compute.stdout.splitlines() if row.strip()]
    competing_compute: list[dict[str, object]] = []
    for row in applications:
        fields = [item.strip() for item in row.split(",", 2)]
        if len(fields) != 3:
            errors.append("GPU_COMPUTE_ROW_INVALID")
            continue
        try:
            pid = int(fields[0])
        except ValueError:
            errors.append("GPU_COMPUTE_ROW_INVALID")
            continue
        record = _process_record(proc_root, pid)
        record.update({"process_name": fields[1], "used_memory_mib": fields[2], "row": row})
        if not _is_todesk_process(record, fields[1]):
            competing_compute.append(record)
    if competing_compute:
        errors.append("COMPETING_GPU_COMPUTE_APPLICATION_PRESENT")

    conflicts: list[dict[str, object]] = []
    try:
        entries = list(proc_root.iterdir())
    except OSError as error:
        entries = []
        errors.append(f"PROCESS_SCAN_FAILED:{type(error).__name__}:{error}")
    for entry in entries:
        if not entry.name.isdigit() or int(entry.name) == os.getpid():
            continue
        record = _process_record(proc_root, int(entry.name))
        if _is_forbidden_estimator_process(record):
            conflicts.append(record)
    if conflicts:
        errors.append("CONFLICTING_SLAM_OR_ROS_PROCESS_PRESENT")
    selected = gpus[0]
    return {
        "ready": not errors,
        "errors": errors,
        "gpus": gpus,
        "selected_cuda_visible_device": 0,
        "memory_total_mib": selected["memory_total_mib"],
        "memory_used_mib": selected["memory_used_mib"],
        "memory_free_mib": selected["memory_free_mib"],
        "minimum_free_mib": None,
        "minimum_free_mib_waived_by_user": True,
        "gpu_hardware_not_method_gated": True,
        "external_onnx_and_cache_still_frozen_stack": True,
        "compute_applications_observed": applications,
        "competing_compute_applications": competing_compute,
        "conflicting_processes": conflicts,
    }


def _check_locked(
    spec_path: Path,
    *,
    require_unclaimed: bool,
    resource: Mapping[str, Any],
    lock_evidence: Mapping[str, Any],
) -> dict[str, Any]:
    errors: list[str] = []
    case_id: object = None
    try:
        spec, prepared = load_prepared(spec_path)
        case_id = spec.get("case_id")
        paths = attempt_paths(spec)
        require_prepared_contract(spec_path, spec, prepared)
        permanent = permanent_case_paths(str(spec["case_id"]))
        if require_unclaimed and any(
            path.exists() or path.is_symlink()
            for path in (paths["claim"], *permanent.values())
        ):
            errors.append("PROCESS_START_ALREADY_CLAIMED_NO_RETRY")
        if paths["result"].exists() or paths["result"].is_symlink():
            errors.append("RUN_RESULT_ALREADY_EXISTS_TERMINAL")
        for label in ("stdout", "stderr"):
            if paths[label].exists() or paths[label].is_symlink():
                errors.append(f"PREEXISTING_{label.upper()}_LOG")
        if any(paths["result_dir"].iterdir()):
            errors.append("RESULT_DIRECTORY_NOT_EMPTY")
    except (ContractError, KeyError, OSError, ValueError, TypeError) as error:
        errors.append(f"{type(error).__name__}:{error}")
    errors.extend(str(item) for item in resource.get("errors", []))
    return {
        "schema_version": "aqua-fe-hfnet-v6-samehistory-positive-check-v1",
        "case_id": case_id,
        "checked_at_utc": now_utc(),
        "ready": not errors,
        "errors": errors,
        "global_serial_lock": dict(lock_evidence),
        "resource_gate": dict(resource),
    }


def check(spec_path: Path, require_unclaimed: bool = True) -> dict[str, Any]:
    with global_serial_lock() as lock_evidence:
        resource = resource_gate()
        return _check_locked(
            spec_path,
            require_unclaimed=require_unclaimed,
            resource=resource,
            lock_evidence=lock_evidence,
        )


def parse_trajectory(path: Path, stamps: Sequence[int]) -> dict[str, Any]:
    result: dict[str, Any] = {
        "exists": path.is_file(),
        "valid": False,
        "pose_count": 0,
        "errors": [],
    }
    if not path.is_file():
        result["errors"] = ["MISSING"]
        return result
    associated: list[int] = []
    used: set[int] = set()
    previous_stamp: int | None = None
    rows = [line for line in path.read_text(encoding="ascii").splitlines() if line.strip()]
    for line_number, raw in enumerate(rows, start=1):
        fields = raw.split()
        if len(fields) != 8:
            result["errors"].append(f"ROW_{line_number}_FIELD_COUNT")
            continue
        try:
            stamp = int(fields[0])
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
        if previous_stamp is not None and stamp <= previous_stamp:
            result["errors"].append(f"ROW_{line_number}_TIMESTAMP_NOT_STRICT")
            continue
        previous_stamp = stamp
        insertion = bisect.bisect_left(stamps, stamp)
        candidates = [
            value
            for value in (insertion - 1, insertion)
            if 0 <= value < len(stamps)
        ]
        if not candidates:
            result["errors"].append(f"ROW_{line_number}_NO_ASSOCIATION")
            continue
        index = min(candidates, key=lambda value: abs(stamps[value] - stamp))
        if (
            abs(stamps[index] - stamp) > ASSOCIATION_TOLERANCE_NS
            or index in used
        ):
            result["errors"].append(f"ROW_{line_number}_ASSOCIATION")
            continue
        used.add(index)
        associated.append(index)
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
            "identity": identity(path),
            "valid": not result["errors"],
            "pose_count": len(associated),
            "first_relative_index": associated[0] if associated else None,
            "last_relative_index": associated[-1] if associated else None,
            "coverage_fraction": len(associated) / len(stamps),
            "longest_contiguous_count": longest,
            "longest_contiguous_fraction": longest / len(stamps),
            "longest_contiguous_relative_indices_inclusive": (
                [longest_start, longest_end] if longest_start is not None else None
            ),
        }
    )
    return result


def parse_log(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {"valid": False, "errors": ["STDOUT_MISSING"]}
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    init_ids: list[int] = []
    reset_events: list[dict[str, int | None]] = []
    last_init: int | None = None
    pending_resets: list[dict[str, int | None]] = []
    for line in lines:
        match = re.search(r"Init frame id:\s*(\d+)", line)
        if match:
            next_init = int(match.group(1))
            for event in pending_resets:
                event["next_init_frame_id"] = next_init
            pending_resets.clear()
            last_init = next_init
            init_ids.append(last_init)
        if "SYSTEM-> Reseting active map" in line:
            event = {
                "preceding_init_frame_id": last_init,
                "next_init_frame_id": None,
            }
            reset_events.append(event)
            pending_resets.append(event)
    saving = max(
        (index for index, line in enumerate(lines) if line.startswith("Saving trajectory to ")),
        default=-1,
    )
    tail = lines[saving + 1 :] if saving >= 0 else []
    atlas_count: int | None = None
    atlas_position = -1
    for index, line in enumerate(tail):
        match = re.search(r"There are (\d+) maps in (?:the )?atlas", line)
        if match:
            atlas_count = int(match.group(1))
            atlas_position = index
    end_position = (
        next(
            (
                index
                for index, line in enumerate(
                    tail[atlas_position + 1 :], start=atlas_position + 1
                )
                if line.startswith("End of saving trajectory to ")
            ),
            -1,
        )
        if atlas_position >= 0
        else -1
    )
    map_rows: list[tuple[int, int]] = []
    if atlas_position >= 0 and end_position >= 0:
        for line in tail[atlas_position + 1 : end_position]:
            match = re.fullmatch(r"\s*Map (\d+) has (\d+) KFs\s*", line)
            if match:
                map_rows.append((int(match.group(1)), int(match.group(2))))
    exact = bool(
        atlas_count is not None
        and end_position >= 0
        and len(map_rows) == atlas_count
        and {row[0] for row in map_rows} == set(range(atlas_count))
    )
    return {
        "valid": exact,
        "init_frame_ids": init_ids,
        "initialization_count": len(init_ids),
        "reset_events": reset_events,
        "active_map_reset_count": len(reset_events),
        "reset_next_initialization_parse_complete": all(
            row["next_init_frame_id"] is not None for row in reset_events
        ),
        "atlas_map_count": atlas_count,
        "map_keyframes": [row[1] for row in map_rows],
        "final_atlas_nonempty": bool(exact and any(row[1] > 0 for row in map_rows)),
        "trajectory_save_completed": end_position >= 0,
    }


def events_in_accepted_support(
    log: Mapping[str, Any], trajectory: Mapping[str, Any]
) -> dict[str, object]:
    """Classify reset/reinitialization events against the frozen support run."""
    accepted = trajectory.get("longest_contiguous_relative_indices_inclusive")
    if not (
        isinstance(accepted, list)
        and len(accepted) == 2
        and all(isinstance(value, int) for value in accepted)
    ):
        return {
            "first_relative_index": None,
            "last_relative_index": None,
            "proven_early_reset_events": [],
            "unresolved_reset_events": list(log.get("reset_events", [])),
            "reinitialization_frame_ids": [],
        }
    start, end = accepted
    reset_events = list(log.get("reset_events", []))
    proven_early = [
        row
        for row in reset_events
        if row.get("next_init_frame_id") is not None
        and int(row["next_init_frame_id"]) <= start
    ]
    unresolved = [row for row in reset_events if row not in proven_early]
    reinitializations = [
        int(value)
        for value in log.get("init_frame_ids", [])
        if start < int(value) <= end
    ]
    return {
        "first_relative_index": start,
        "last_relative_index": end,
        "proven_early_reset_events": proven_early,
        "unresolved_reset_events": unresolved,
        "reinitialization_frame_ids": reinitializations,
    }


def runtime_environment() -> dict[str, str]:
    return {
        "CUDA_VISIBLE_DEVICES": "0",
        "HOME": "/home/ma",
        "USER": "ma",
        "LANG": "C",
        "LC_ALL": "C",
        "PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
        "LD_LIBRARY_PATH": ":".join(
            [
                "/home/ma/SLAM/HFNet-SLAM-paper-2023-build-r1/lib",
                "/home/ma/SLAM/HFNet-SLAM-paper-2023-build-r1/Thirdparty/g2o/lib",
                "/home/ma/SLAM/aqua_deps/install/lib",
                "/home/ma/opt/hfnet_cuda116_trt851_r1/usr/lib/x86_64-linux-gnu",
                "/home/ma/opt/hfnet_cuda116_trt851_r1/usr/local/cuda-11.6/targets/x86_64-linux/lib",
                "/home/ma/opt/hfnet_cuda116_trt851_r1/usr/local/cuda-11.8/targets/x86_64-linux/lib",
            ]
        ),
    }


def _terminate_and_reap(process: Any) -> tuple[int | None, bool, list[str], str]:
    errors: list[str] = []
    termination = "SIGTERM_THEN_SIGKILL_IF_NEEDED"
    for signal_value, label in (
        (signal.SIGTERM, "SIGTERM"),
        (signal.SIGKILL, "SIGKILL"),
    ):
        if process.poll() is None:
            try:
                os.killpg(process.pid, signal_value)
            except ProcessLookupError:
                pass
            except BaseException as error:
                errors.append(f"{label}_FAILED:{type(error).__name__}:{error}")
        try:
            return process.wait(timeout=10), True, errors, termination
        except subprocess.TimeoutExpired:
            continue
        except BaseException as error:
            errors.append(f"{label}_WAIT_FAILED:{type(error).__name__}:{error}")
    try:
        if process.poll() is not None:
            return process.wait(timeout=0), True, errors, termination
    except BaseException as error:
        errors.append(f"FINAL_REAP_FAILED:{type(error).__name__}:{error}")
    return process.poll(), False, errors, termination


def execute_once(
    spec: Mapping[str, Any],
    paths: Mapping[str, Path],
    launch: Mapping[str, Any],
) -> dict[str, object]:
    started = now_utc()
    start_monotonic = time.monotonic()
    process: Any | None = None
    return_code: int | None = None
    child_reaped = False
    timed_out = False
    termination: str | None = None
    popen_invocations = 0
    errors: list[str] = []
    try:
        with paths["stdout"].open("xb") as stdout, paths["stderr"].open("xb") as stderr:
            try:
                popen_invocations += 1
                process = subprocess.Popen(
                    launch["argv"],
                    cwd=launch["cwd"],
                    env=runtime_environment(),
                    stdout=stdout,
                    stderr=stderr,
                    start_new_session=True,
                )
            except BaseException as error:
                errors.append(f"POPEN_FAILED:{type(error).__name__}:{error}")
            if process is not None:
                try:
                    return_code = process.wait(timeout=int(spec["timeout_seconds"]))
                    child_reaped = True
                except subprocess.TimeoutExpired:
                    timed_out = True
                    return_code, child_reaped, cleanup, termination = _terminate_and_reap(
                        process
                    )
                    errors.extend(cleanup)
                except BaseException as error:
                    errors.append(f"WAIT_FAILED:{type(error).__name__}:{error}")
                    return_code, child_reaped, cleanup, termination = _terminate_and_reap(
                        process
                    )
                    errors.extend(cleanup)
    except BaseException as error:
        errors.append(f"LOG_OPEN_OR_EXECUTION_FAILED:{type(error).__name__}:{error}")
    finally:
        if process is not None and not child_reaped:
            return_code, child_reaped, cleanup, final_termination = _terminate_and_reap(
                process
            )
            errors.extend(cleanup)
            termination = termination or final_termination
    return {
        "started_at_utc": started,
        "ended_at_utc": now_utc(),
        "duration_seconds": time.monotonic() - start_monotonic,
        "raw_returncode": return_code,
        "timed_out": timed_out,
        "termination": termination,
        "supervisor_error": ";".join(errors) if errors else None,
        "child_reaped_before_post_audit": child_reaped,
        "popen_invocations": popen_invocations,
        "retry_performed": False,
        "retry_permitted": False,
    }


def _invalid_output(path: Path, error: BaseException) -> dict[str, object]:
    return {
        "exists": path.is_file(),
        "valid": False,
        "pose_count": 0,
        "errors": [f"POST_AUDIT_EXCEPTION:{type(error).__name__}:{error}"],
    }


def build_run_result(
    spec_path: Path,
    spec: Mapping[str, Any],
    prepared: Mapping[str, Any],
    paths: Mapping[str, Path],
    claim: Mapping[str, Any],
    precheck: Mapping[str, Any],
    execution: Mapping[str, object],
) -> dict[str, Any]:
    post_audit_errors: list[str] = []
    try:
        stamps = selected_timestamps(spec)
    except BaseException as error:
        stamps = list(range(int(spec["camera_count"])))
        post_audit_errors.append(
            f"CAMERA_TIMES_POST_AUDIT:{type(error).__name__}:{error}"
        )
    trajectory_path = paths["result_dir"] / "trajectory.txt"
    keyframe_path = paths["result_dir"] / "trajectory_keyframe.txt"
    try:
        trajectory = parse_trajectory(trajectory_path, stamps)
    except BaseException as error:
        trajectory = _invalid_output(trajectory_path, error)
        post_audit_errors.append(
            f"TRAJECTORY_POST_AUDIT:{type(error).__name__}:{error}"
        )
    try:
        keyframes = parse_trajectory(keyframe_path, stamps)
    except BaseException as error:
        keyframes = _invalid_output(keyframe_path, error)
        post_audit_errors.append(
            f"KEYFRAME_POST_AUDIT:{type(error).__name__}:{error}"
        )
    try:
        log = parse_log(paths["stdout"])
    except BaseException as error:
        log = {
            "valid": False,
            "errors": [f"POST_AUDIT_EXCEPTION:{type(error).__name__}:{error}"],
            "reset_events": [],
            "init_frame_ids": [],
        }
        post_audit_errors.append(f"LOG_POST_AUDIT:{type(error).__name__}:{error}")
    try:
        post_contract: dict[str, object] | None = require_prepared_contract(
            spec_path, spec, prepared
        )
        prepared_unchanged = identity(paths["prepared"]) == claim["prepared_manifest"]
    except BaseException as error:
        post_contract = None
        prepared_unchanged = False
        post_audit_errors.append(
            f"FROZEN_CONTRACT_POST_AUDIT:{type(error).__name__}:{error}"
        )

    accepted_events = events_in_accepted_support(log, trajectory)
    support_start = accepted_events["first_relative_index"]
    support_end = accepted_events["last_relative_index"]
    proven_early_resets = accepted_events["proven_early_reset_events"]
    unresolved_resets = accepted_events["unresolved_reset_events"]
    support_reinitializations = accepted_events["reinitialization_frame_ids"]
    log["accepted_support_first_relative_index"] = support_start
    log["accepted_support_last_relative_index"] = support_end
    log["proven_early_reset_events"] = proven_early_resets
    log["accepted_support_unresolved_reset_events"] = unresolved_resets
    log["accepted_support_reinitialization_frame_ids"] = support_reinitializations

    failure_codes: list[str] = []
    if (
        execution.get("raw_returncode") != 0
        or execution.get("timed_out") is True
        or execution.get("supervisor_error") is not None
        or execution.get("child_reaped_before_post_audit") is not True
        or execution.get("popen_invocations") != 1
    ):
        failure_codes.append("EXECUTION_NOT_CLEAN")
    if post_contract is None or not prepared_unchanged:
        failure_codes.append("FROZEN_CONTRACT_DRIFT")
    if post_audit_errors:
        failure_codes.append("POST_AUDIT_INCOMPLETE")
    if trajectory.get("valid") is not True:
        failure_codes.append("TRAJECTORY_INVALID")
    if float(trajectory.get("coverage_fraction", 0.0)) < MIN_COVERAGE:
        failure_codes.append("TRAJECTORY_COVERAGE_BELOW_70_PERCENT")
    if float(trajectory.get("longest_contiguous_fraction", 0.0)) < MIN_CONTIGUOUS:
        failure_codes.append("TRAJECTORY_CONTIGUOUS_SUPPORT_BELOW_70_PERCENT")
    if keyframes.get("valid") is not True or int(keyframes.get("pose_count", 0)) < 1:
        failure_codes.append("NO_VALID_KEYFRAME_TRAJECTORY")
    if log.get("valid") is not True or log.get("final_atlas_nonempty") is not True:
        failure_codes.append("FINAL_ATLAS_EMPTY_OR_UNPARSEABLE")
    if int(log.get("initialization_count", 0)) < 1:
        failure_codes.append("NO_SUCCESSFUL_INITIALIZATION")
    if unresolved_resets:
        failure_codes.append("ACTIVE_MAP_RESET_BOUNDARY_UNRESOLVED")
    if support_reinitializations:
        failure_codes.append("REINITIALIZATION_WITHIN_ACCEPTED_SUPPORT")
    passed = not failure_codes
    permanent = permanent_case_paths(str(spec["case_id"]))
    return {
        "schema_version": RESULT_SCHEMA,
        "status": (
            "PASS_SAMEHISTORY_COLDSTART_RUNABILITY"
            if passed
            else "FAIL_SAMEHISTORY_COLDSTART_RUNABILITY"
        ),
        "case_id": spec["case_id"],
        "failure_codes": failure_codes,
        "post_audit_errors": post_audit_errors,
        "prestart_check": dict(precheck),
        "execution": dict(execution),
        "support": {
            "camera_count": len(stamps),
            "trajectory": trajectory,
            "keyframes": keyframes,
            "log": log,
        },
        "integrity": {
            "frozen_contract_unchanged": post_contract is not None,
            "prepared_manifest_unchanged": prepared_unchanged,
            "post_contract": post_contract,
            "case_spec_post": safe_identity(spec_path),
            "runner_post": safe_identity(RUNNER),
        },
        "pins": {
            "prepared_manifest": safe_identity(paths["prepared"]),
            "process_start_claim": safe_identity(paths["claim"]),
            "permanent_case_reservation": safe_identity(permanent["reservation"]),
            "permanent_case_claim": safe_identity(permanent["claim"]),
            "stdout": safe_identity(paths["stdout"]),
            "stderr": safe_identity(paths["stderr"]),
        },
        "claim_boundary": {
            "history": spec["history"],
            "outcome_selected_historical_positive": True,
            "accuracy_evaluated": False,
            "ranking_authorized": False,
            "failed_accuracy_is_na_not_zero": True,
        },
        "terminal_contract": {
            "attempt_consumed": True,
            "retry_after_pass_or_fail": False,
            "claim_without_result_is_terminal_fail": True,
        },
    }


def terminal_supervisor_failure_result(
    spec_path: Path,
    spec: Mapping[str, Any],
    paths: Mapping[str, Path],
    precheck: Mapping[str, Any],
    execution: Mapping[str, object] | None,
    error: BaseException,
) -> dict[str, Any]:
    permanent = permanent_case_paths(str(spec["case_id"]))
    observed_execution = dict(execution or {})
    observed_execution.setdefault("popen_invocations", 0)
    observed_execution.setdefault("retry_performed", False)
    observed_execution.setdefault("retry_permitted", False)
    observed_execution["terminal_supervisor_exception"] = (
        f"{type(error).__name__}:{error}"
    )
    return {
        "schema_version": RESULT_SCHEMA,
        "status": "FAIL_SAMEHISTORY_COLDSTART_RUNABILITY",
        "case_id": spec["case_id"],
        "failure_codes": ["SUPERVISOR_EXCEPTION", "EXECUTION_NOT_CLEAN"],
        "post_audit_errors": [f"TERMINAL_EXCEPTION:{type(error).__name__}:{error}"],
        "prestart_check": dict(precheck),
        "execution": observed_execution,
        "support": {"camera_count": spec["camera_count"], "audit_incomplete": True},
        "integrity": {
            "case_spec_post": safe_identity(spec_path),
            "runner_post": safe_identity(RUNNER),
        },
        "pins": {
            "prepared_manifest": safe_identity(paths["prepared"]),
            "process_start_claim": safe_identity(paths["claim"]),
            "permanent_case_reservation": safe_identity(permanent["reservation"]),
            "permanent_case_claim": safe_identity(permanent["claim"]),
            "stdout": safe_identity(paths["stdout"]),
            "stderr": safe_identity(paths["stderr"]),
        },
        "claim_boundary": {
            "history": spec["history"],
            "accuracy_evaluated": False,
            "ranking_authorized": False,
            "failed_accuracy_is_na_not_zero": True,
        },
        "terminal_contract": {
            "attempt_consumed": True,
            "retry_after_pass_or_fail": False,
            "claim_without_result_is_terminal_fail": True,
        },
    }


def run(spec_path: Path, token: str) -> dict[str, Any]:
    with global_serial_lock() as lock_evidence:
        spec, prepared = load_prepared(spec_path)
        if token != spec.get("authorization_token"):
            raise ContractError("AUTHORIZATION_TOKEN_MISMATCH")
        resource = resource_gate()
        precheck = _check_locked(
            spec_path,
            require_unclaimed=True,
            resource=resource,
            lock_evidence=lock_evidence,
        )
        if not precheck["ready"]:
            raise ContractError(
                "PRESTART_CHECK_FAILED:" + ";".join(precheck["errors"])
            )
        paths = attempt_paths(spec)
        launch = canonical_launch(spec, paths)
        permanent = permanent_case_paths(str(spec["case_id"]))
        claimed_at = now_utc()
        reservation_payload = canonical_json(
            {
                "case_id": spec["case_id"],
                "attempt_root": str(paths["root"]),
                "core_spec_sha256": core_spec_sha256(spec),
                "claimed_at_utc": claimed_at,
            }
        )
        execution: dict[str, object] | None = None
        try:
            _write_o_excl_reservation(
                permanent["reservation"], reservation_payload
            )
        except ClaimedBoundaryError as error:
            result = terminal_supervisor_failure_result(
                spec_path, spec, paths, precheck, execution, error
            )
            _atomic_publish_exclusive(paths["result"], canonical_json(result))
            return result
        try:
            claim = {
                "schema_version": CLAIM_SCHEMA,
                "status": "O_EXCL_PERMANENT_CASE_CLAIM_BEFORE_ONLY_HFNET_POPEN",
                "claimed_at_utc": claimed_at,
                "case_id": spec["case_id"],
                "authorization_token_sha256": sha256_bytes(token.encode("utf-8")),
                "maximum_popen_invocations": 1,
                "retry_permitted": False,
                "prepared_manifest": identity(paths["prepared"]),
                "permanent_o_excl_reservation": identity(
                    permanent["reservation"]
                ),
                "runner": identity(RUNNER),
                "launch": launch,
                "prestart_check": precheck,
            }
            _atomic_publish_exclusive(permanent["claim"], canonical_json(claim))
            _atomic_publish_exclusive(paths["claim"], canonical_json(claim))
            execution = execute_once(spec, paths, launch)
            result = build_run_result(
                spec_path, spec, prepared, paths, claim, precheck, execution
            )
        except BaseException as error:
            result = terminal_supervisor_failure_result(
                spec_path, spec, paths, precheck, execution, error
            )
        _atomic_publish_exclusive(paths["result"], canonical_json(result))
        return result


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("prepare", "check", "run"))
    parser.add_argument("--case-spec", type=Path, required=True)
    parser.add_argument("--authorization-token", default="")
    args = parser.parse_args(argv)
    try:
        if args.action == "prepare":
            value = prepare(args.case_spec)
        elif args.action == "check":
            value = check(args.case_spec, require_unclaimed=True)
        else:
            value = run(args.case_spec, args.authorization_token)
        print(
            json.dumps(
                value,
                indent=2,
                sort_keys=True,
                ensure_ascii=False,
                allow_nan=False,
            )
        )
        if args.action == "run":
            return (
                0
                if value.get("status") == "PASS_SAMEHISTORY_COLDSTART_RUNABILITY"
                else 2
            )
        return 0 if value.get("ready", True) else 2
    except (
        ContractError,
        KeyError,
        OSError,
        TypeError,
        ValueError,
        subprocess.SubprocessError,
    ) as error:
        print(
            json.dumps(
                {
                    "status": "FAIL_CLOSED",
                    "error": f"{type(error).__name__}:{error}",
                },
                indent=2,
            ),
            file=sys.stderr,
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
