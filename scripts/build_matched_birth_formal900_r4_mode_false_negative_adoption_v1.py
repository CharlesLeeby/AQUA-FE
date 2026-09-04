#!/usr/bin/env python3
"""Adopt the consumed r4 namespace for one mode-corrected audit only.

The default ``check`` action is read-only.  It holds the complete r4 tree
(five directories and nineteen regular files) open while validating the
terminal ERROR seal, the two one-shot/full producers, and the mode mismatch
that caused the frozen auditor to stop before scientific validation.  The
record deliberately exposes no detector outcome values or relative result.

The optional ``write-once`` action is the sole publisher for the fixed permit
path.  It uses O_EXCL, mode 0444, file and parent fsync, held-FD readback, and
visible-inode rebinding checks.  This module never runs a producer, detector,
pair auditor, VINS process, or evaluator, and never chmods r4 evidence.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import os
from pathlib import Path
import stat
import sys
from typing import Mapping, Sequence


WORKSPACE_ROOT = Path(__file__).resolve().parents[1]
if str(WORKSPACE_ROOT) not in sys.path:
    sys.path.insert(0, str(WORKSPACE_ROOT))

from scripts import audit_matched_birth_rawlk_pair_formal_v2 as frozen_audit
from scripts import run_matched_birth_arm_once_v1 as launcher


SCHEMA_VERSION = (
    "aqua-fe-detector-birth-rawlk-formal900-r4-mode-false-negative-"
    "adoption-v1"
)
STATUS = "ADOPTED_CONSUMED_R4_FOR_ONE_MODE_CORRECTED_AUDIT_ONLY"
SCIENTIFIC_ROLE = "POST_RESULT_INFRASTRUCTURE_RECOVERY_NO_RESULT_SELECTION"

R4_ROOT = (
    WORKSPACE_ROOT / "experiments/matched_birth_a02_4500_6300_formal900_r4"
)
R3_ADOPTION = (
    WORKSPACE_ROOT
    / "papers/a02_4500_6300_matched_birth_r3_pass_formal900_adoption_v1.json"
)
HUMAN_RECORD = (
    WORKSPACE_ROOT
    / "papers/a02_4500_6300_matched_birth_formal900_r4_mode_false_negative_"
    "adoption_v1.md"
)
DEFAULT_OUTPUT = (
    WORKSPACE_ROOT
    / "papers/a02_4500_6300_matched_birth_formal900_r4_mode_false_negative_"
    "adoption_v1.json"
)
CORRECTED_AUDITOR = (
    WORKSPACE_ROOT
    / "scripts/audit_matched_birth_rawlk_pair_formal_r4_modefix_v1.py"
)
EXPECTED_CORRECTED_AUDITOR = {
    "path": str(CORRECTED_AUDITOR),
    "size_bytes": 55509,
    "sha256": "24793e31a572bdec96fad826bab57dc00c3633168f3c79387ea2b92c20d2b3e8",
}
CONTINUATION_SEAL = (
    WORKSPACE_ROOT
    / "papers/a02_4500_6300_matched_birth_formal900_r4_modefix_"
    "continuation_seal_v1.json"
)
FROZEN_AUDITOR = (
    WORKSPACE_ROOT / "scripts/audit_matched_birth_rawlk_pair_formal_v2.py"
)
MATCHED_CORE = WORKSPACE_ROOT / "scripts/matched_birth_rawlk_core_v1.py"
OLD_ERROR_SEAL = R4_ROOT / "formal900_post_run_pair_seal.json"
FREEZE_JSON = R4_ROOT / "formal900_freeze.json"
START_RECEIPT = R4_ROOT / "formal900_pre_run_start_receipt.json"
PY_CACHE_PREFIX = Path("/tmp/aqua-fe-a02-matched-birth-rawlk-empty-pycache-v1")

EXPECTED_DEVICE_ID = 66312
EXPECTED_ROOT_INODE = 6190245
EXPECTED_COMMIT_IDENTITIES = {
    "freeze": {
        "path": str(FREEZE_JSON),
        "size_bytes": 8447670,
        "sha256": "270d60c17e95973e002f57775eecdb67f6c93fc2aebf0a3f11fff61cebf2188f",
    },
    "pre_run_start_receipt": {
        "path": str(START_RECEIPT),
        "size_bytes": 9773,
        "sha256": "a3302c0a8152d8315f6a18e39710c9b88d9f1740fea4942150a1c07dbb5fdeab",
    },
    "old_error_seal": {
        "path": str(OLD_ERROR_SEAL),
        "size_bytes": 461,
        "sha256": "20a8ed084c4c3d08640e1f7c7571cb927d049aadd8ba5600f11b0ec193b948d7",
    },
}
EXPECTED_R3_ADOPTION = {
    "path": str(R3_ADOPTION),
    "size_bytes": 43004,
    "sha256": "6b011fd6bcf64a5b85049a2f9c6ef5d40da818cb28c5a8304f4dbef72a3df86d",
}

XFEAT_ARM = "XFEAT_BIRTH_RAWLK_MATCHED_V1"
GFTT_ARM = "GFTT_BIRTH_RAWLK_MATCHED_V1"
ARM_DIRECTORIES = {XFEAT_ARM: "xfeat_r4", GFTT_ARM: "gftt_r4"}
ROOT_FILES = frozenset(
    {
        "formal900_freeze.json",
        "formal900_pre_run_start_receipt.json",
        "formal900_post_run_pair_seal.json",
    }
)
ARM_GOVERNANCE_FILES = frozenset(
    {
        "command_contract.json",
        "producer_attempt.json",
        "launcher_start_receipt.json",
        "launcher_rc_receipt.json",
    }
)
ARM_RESULT_FILES = frozenset(
    {
        "export_manifest.json",
        "features.bag",
        "raw_diagnostics.csv",
        "legacy_primitive_manifest.json",
    }
)
ARM_FILES = ARM_GOVERNANCE_FILES | ARM_RESULT_FILES
DIAGNOSTIC_FIELDS = (
    "raw_index",
    "header_stamp_ns",
    "published",
    "adaptive_clahe_applied",
    "raw_image_sha256",
    "processed_image_sha256",
    "tracked_before",
    "tracked_after",
    "dropped",
    "slots_before_detect",
    "detector_called",
    "detector_candidates",
    "births",
    "output_tracks",
    "fb_median_px",
    "fb_p95_px",
    "ncc_median",
)
VINS_RUN_DIRECTORIES = (
    WORKSPACE_ROOT
    / "logs/aqualoc_archaeo_vins/external_klt_every2_litcmp_a02_4500_6300_"
    "preroll_matchedbirth_formal900_r4_xfeat_vins_r1",
    WORKSPACE_ROOT
    / "logs/aqualoc_archaeo_vins/external_klt_every2_litcmp_a02_4500_6300_"
    "preroll_matchedbirth_formal900_r4_gftt_vins_r1",
)

EXPECTED_ERROR_SEAL = {
    "claim_boundary": {
        "contract_pass": False,
        "output_namespace_consumed_no_retry": True,
    },
    "error": {
        "message": (
            "active held regular-file contract failed: "
            f"{R4_ROOT / 'xfeat_r4/export_manifest.json'}"
        ),
        "type": "AuditFailure",
    },
    "pass": False,
    "schema_version": (
        "aqua-fe-detector-birth-rawlk-matched-pair-formal-audit-v2"
    ),
    "scientific_role": (
        "post_result_development_exploratory_detector_birth_ablation"
    ),
    "status": "ERROR",
}

EXPECTED_PRODUCER_PROCESS = {
    "launch_attempt_count": 1,
    "process_start_count": 1,
    "producer_return_code": 0,
    "natural_end_observed": True,
    "exited_normally": True,
    "terminated_by_signal": False,
    "signal_number": None,
    "supervisor_sent_signal": False,
    "timed_out": False,
    "timeout_seconds": None,
    "retry_performed": False,
}

FORBIDDEN_RECORD_KEYS = frozenset(
    {
        "metrics",
        "observations",
        "detector_candidates",
        "births",
        "raw_births",
        "raw_drops",
        "unique_ids",
        "published_first_occurrences",
        "published_continuations",
        "observations_per_frame_max",
        "observations_per_frame_median",
        "observations_per_frame_min",
        "winner",
        "relative_result",
        "ape",
        "rpe",
    }
)
RECORD_KEYS = frozenset(
    {
        "schema_version",
        "status",
        "scientific_role",
        "builder_identity",
        "builder_execution_contract",
        "human_record",
        "incident",
        "source_namespace",
        "execution_qualification",
        "mode_false_negative_qualification",
        "continuation_authorization",
        "outcome_firewall",
        "claim_boundary",
    }
)
CONTINUATION_AUTHORIZATION_KEYS = frozenset(
    {
        "adoption_record",
        "corrected_auditor",
        "old_error_seal",
        "continuation_seal",
        "authorized_argv",
        "environment",
        "working_directory",
        "authorized_invocation_count",
        "detector_or_producer_rerun_authorized",
        "r4_chmod_authorized",
        "old_error_seal_replacement_authorized",
        "other_scientific_or_governance_change_authorized",
        "vins_authorized_before_corrected_pass",
        "vins_authorization_on_corrected_error_or_fail",
        "vins_authorization_on_corrected_strict_pass",
    }
)
ADOPTION_RECORD_KEYS = frozenset({"path", "schema_version", "builder_identity"})
CONTINUATION_SEAL_KEYS = frozenset(
    {
        "path",
        "required_pre_run_state",
        "publication_mode_octal",
        "write_once_no_clobber",
    }
)


class AdoptionError(RuntimeError):
    """The live state is not the exact governed continuation state."""


def _canonical_bytes(value: object) -> bytes:
    return (
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")


def _strict_equal(actual: object, expected: object, *, label: str) -> None:
    if type(actual) is not type(expected) or _canonical_bytes(actual) != _canonical_bytes(
        expected
    ):
        raise AdoptionError(f"{label} mismatch")


def _identity(path: Path, payload: bytes) -> dict[str, object]:
    return {
        "path": str(path),
        "size_bytes": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest(),
    }


def _read_fd(
    descriptor: int,
    expected_identity: tuple[int, int],
    *,
    label: str,
) -> tuple[bytes, os.stat_result]:
    before = os.fstat(descriptor)
    if (
        not stat.S_ISREG(before.st_mode)
        or int(before.st_nlink) != 1
        or (int(before.st_dev), int(before.st_ino)) != expected_identity
    ):
        raise AdoptionError(f"{label} is not the held single-link regular inode")
    os.lseek(descriptor, 0, os.SEEK_SET)
    chunks: list[bytes] = []
    while True:
        chunk = os.read(descriptor, 1024 * 1024)
        if not chunk:
            break
        chunks.append(chunk)
    payload = b"".join(chunks)
    after = os.fstat(descriptor)
    if (
        (int(after.st_dev), int(after.st_ino)) != expected_identity
        or int(after.st_size) != len(payload)
        or int(after.st_mtime_ns) != int(before.st_mtime_ns)
        or int(after.st_ctime_ns) != int(before.st_ctime_ns)
    ):
        raise AdoptionError(f"{label} changed during held read")
    return payload, after


def _decode_json(path: Path, payload: bytes, *, label: str) -> dict[str, object]:
    try:
        value = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AdoptionError(f"{label} is not UTF-8 JSON") from exc
    if type(value) is not dict:
        raise AdoptionError(f"{label} is not a JSON object")
    expected = (
        (json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n").encode(
            "utf-8"
        )
        if path.name == "legacy_primitive_manifest.json"
        else _canonical_bytes(value)
    )
    if payload != expected:
        raise AdoptionError(f"{label} canonical codec mismatch")
    return value


def _mode_for_relative(relative: Path) -> int:
    if len(relative.parts) == 1 and relative.name in ROOT_FILES:
        return 0o444
    if len(relative.parts) == 2 and relative.parts[0] in ARM_DIRECTORIES.values():
        if relative.name in ARM_GOVERNANCE_FILES:
            return 0o444
        if relative.name in ARM_RESULT_FILES:
            return 0o664
    raise AdoptionError(f"unclassified r4 regular-file role: {relative}")


def _directory_row(path: Path, descriptor: int) -> dict[str, object]:
    observed = os.fstat(descriptor)
    return {
        "path": str(path),
        "kind": "directory",
        "mode_octal": format(stat.S_IMODE(observed.st_mode), "04o"),
        "uid": int(observed.st_uid),
        "gid": int(observed.st_gid),
        "device_id": int(observed.st_dev),
        "inode": int(observed.st_ino),
        "nlink": int(observed.st_nlink),
        "size_bytes": int(observed.st_size),
    }


def _file_row(path: Path, descriptor: int, payload: bytes) -> dict[str, object]:
    observed = os.fstat(descriptor)
    return {
        "path": str(path),
        "kind": "regular",
        "mode_octal": format(stat.S_IMODE(observed.st_mode), "04o"),
        "uid": int(observed.st_uid),
        "gid": int(observed.st_gid),
        "device_id": int(observed.st_dev),
        "inode": int(observed.st_ino),
        "nlink": int(observed.st_nlink),
        "size_bytes": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest(),
    }


def _open_directory(
    path: Path,
    *,
    name: str | None,
    parent_descriptor: int | None,
    descriptors: dict[Path, int],
) -> int:
    raw = str(path) if name is None else name
    visible = (
        os.lstat(path)
        if parent_descriptor is None
        else os.stat(raw, dir_fd=parent_descriptor, follow_symlinks=False)
    )
    descriptor = os.open(
        raw,
        os.O_RDONLY
        | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_CLOEXEC", 0),
        dir_fd=parent_descriptor,
    )
    try:
        held = os.fstat(descriptor)
        if (
            stat.S_ISLNK(visible.st_mode)
            or not stat.S_ISDIR(held.st_mode)
            or (int(visible.st_dev), int(visible.st_ino))
            != (int(held.st_dev), int(held.st_ino))
            or int(held.st_uid) != int(os.getuid())
            or stat.S_IMODE(held.st_mode) != 0o700
        ):
            raise AdoptionError(f"r4 directory identity/mode drift: {path}")
        descriptors[path] = descriptor
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


def _open_r4_file(
    root: Path,
    path: Path,
    *,
    name: str,
    parent_descriptor: int,
    descriptors: dict[Path, int],
    payloads: dict[Path, bytes],
) -> None:
    visible = os.stat(name, dir_fd=parent_descriptor, follow_symlinks=False)
    descriptor = os.open(
        name,
        os.O_RDONLY
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_NONBLOCK", 0)
        | getattr(os, "O_CLOEXEC", 0),
        dir_fd=parent_descriptor,
    )
    descriptors[path] = descriptor
    try:
        held = os.fstat(descriptor)
        identity = (int(held.st_dev), int(held.st_ino))
        if (
            stat.S_ISLNK(visible.st_mode)
            or identity != (int(visible.st_dev), int(visible.st_ino))
            or int(held.st_uid) != int(os.getuid())
        ):
            raise AdoptionError(f"r4 file open race/owner drift: {path}")
        payload, final_stat = _read_fd(
            descriptor, identity, label=f"r4 {path.name}"
        )
        expected_mode = _mode_for_relative(path.relative_to(root))
        if stat.S_IMODE(final_stat.st_mode) != expected_mode:
            raise AdoptionError(
                f"r4 role mode drift: {path}: expected {expected_mode:04o}"
            )
        payloads[path] = payload
    except BaseException:
        descriptors.pop(path, None)
        os.close(descriptor)
        raise


def _snapshot_r4(
    root: Path = R4_ROOT,
    *,
    require_frozen_identity: bool = True,
) -> dict[str, object]:
    root = root.expanduser().absolute()
    if root.resolve(strict=True) != root:
        raise AdoptionError("r4 root is not canonical and symlink-free")
    directories: dict[Path, int] = {}
    files: dict[Path, int] = {}
    payloads: dict[Path, bytes] = {}
    try:
        root_descriptor = _open_directory(
            root, name=None, parent_descriptor=None, descriptors=directories
        )
        root_stat = os.fstat(root_descriptor)
        if require_frozen_identity and (
            int(root_stat.st_dev) != EXPECTED_DEVICE_ID
            or int(root_stat.st_ino) != EXPECTED_ROOT_INODE
            or frozen_audit._fstatfs_magic(root_descriptor)
            != frozen_audit.EXT4_SUPER_MAGIC
        ):
            raise AdoptionError("r4 root frozen ext4 identity drift")
        expected_root = ROOT_FILES | set(ARM_DIRECTORIES.values())
        if set(os.listdir(root_descriptor)) != expected_root:
            raise AdoptionError("r4 root exact listing drift")
        for arm_name in ("xfeat_r4", "gftt_r4"):
            arm_path = root / arm_name
            arm_descriptor = _open_directory(
                arm_path,
                name=arm_name,
                parent_descriptor=root_descriptor,
                descriptors=directories,
            )
            if set(os.listdir(arm_descriptor)) != ARM_FILES | {"private_work"}:
                raise AdoptionError(f"r4 {arm_name} exact listing drift")
            private_path = arm_path / "private_work"
            private_descriptor = _open_directory(
                private_path,
                name="private_work",
                parent_descriptor=arm_descriptor,
                descriptors=directories,
            )
            if os.listdir(private_descriptor):
                raise AdoptionError(f"r4 {arm_name} private work is not empty")
        for name in sorted(ROOT_FILES):
            _open_r4_file(
                root,
                root / name,
                name=name,
                parent_descriptor=root_descriptor,
                descriptors=files,
                payloads=payloads,
            )
        for arm_name in ("xfeat_r4", "gftt_r4"):
            arm_path = root / arm_name
            arm_descriptor = directories[arm_path]
            for name in sorted(ARM_FILES):
                _open_r4_file(
                    root,
                    arm_path / name,
                    name=name,
                    parent_descriptor=arm_descriptor,
                    descriptors=files,
                    payloads=payloads,
                )
        rows = [
            *(
                _directory_row(path, descriptor)
                for path, descriptor in directories.items()
            ),
            *(
                _file_row(path, descriptor, payloads[path])
                for path, descriptor in files.items()
            ),
        ]
        rows.sort(key=lambda row: str(row["path"]))
        if (
            len(directories) != 5
            or len(files) != 19
            or len(rows) != 24
            or len({str(row["path"]) for row in rows}) != 24
            or (require_frozen_identity and {int(row["device_id"]) for row in rows}
                != {EXPECTED_DEVICE_ID})
        ):
            raise AdoptionError("r4 tree is not exact 5 directories plus 19 files")
        return {
            "root": root,
            "directories": directories,
            "files": files,
            "payloads": payloads,
            "inventory": rows,
        }
    except BaseException:
        for descriptor in list(files.values()) + list(
            reversed(tuple(directories.values()))
        ):
            os.close(descriptor)
        raise


def _finish_snapshot(snapshot: Mapping[str, object]) -> None:
    root = snapshot["root"]
    directories = snapshot["directories"]
    files = snapshot["files"]
    payloads = snapshot["payloads"]
    if set(os.listdir(directories[root])) != ROOT_FILES | set(
        ARM_DIRECTORIES.values()
    ):
        raise AdoptionError("r4 root changed before snapshot close")
    for arm_name in ("xfeat_r4", "gftt_r4"):
        arm_path = root / arm_name
        if set(os.listdir(directories[arm_path])) != ARM_FILES | {"private_work"}:
            raise AdoptionError(f"r4 {arm_name} changed before snapshot close")
        if os.listdir(directories[arm_path / "private_work"]):
            raise AdoptionError(f"r4 {arm_name} private work changed")
    final_rows = [
        _directory_row(path, descriptor)
        for path, descriptor in directories.items()
    ]
    for path, descriptor in files.items():
        held = os.fstat(descriptor)
        payload, final_stat = _read_fd(
            descriptor,
            (int(held.st_dev), int(held.st_ino)),
            label=f"final held r4 {path.name}",
        )
        if payload != payloads[path]:
            raise AdoptionError(f"r4 held bytes changed: {path}")
        final_rows.append(_file_row(path, descriptor, payload))
        if stat.S_IMODE(final_stat.st_mode) != _mode_for_relative(
            path.relative_to(root)
        ):
            raise AdoptionError(f"r4 held mode changed: {path}")
    final_rows.sort(key=lambda row: str(row["path"]))
    _strict_equal(final_rows, snapshot["inventory"], label="r4 final inventory")
    for path, descriptor in {**directories, **files}.items():
        visible = os.lstat(path)
        held = os.fstat(descriptor)
        if (
            stat.S_ISLNK(visible.st_mode)
            or (int(visible.st_dev), int(visible.st_ino))
            != (int(held.st_dev), int(held.st_ino))
        ):
            raise AdoptionError(f"r4 visible inode drift before close: {path}")


def _close_snapshot(snapshot: Mapping[str, object]) -> None:
    for descriptor in list(snapshot["files"].values()) + list(
        reversed(tuple(snapshot["directories"].values()))
    ):
        try:
            os.close(descriptor)
        except OSError:
            # Cleanup is best effort after the evidence decision.  Continue so
            # one close error cannot leak every remaining held descriptor or
            # reverse an already fsync'd and fully revalidated publication.
            pass


def _open_external(
    path: Path,
    *,
    required_mode: int,
    label: str,
) -> dict[str, object]:
    if path.expanduser().absolute() != path or path.resolve(strict=True) != path:
        raise AdoptionError(f"{label} path is not canonical and symlink-free")
    visible = os.lstat(path)
    descriptor = os.open(
        path,
        os.O_RDONLY
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_NONBLOCK", 0)
        | getattr(os, "O_CLOEXEC", 0),
    )
    try:
        held = os.fstat(descriptor)
        identity = (int(held.st_dev), int(held.st_ino))
        if (
            stat.S_ISLNK(visible.st_mode)
            or identity != (int(visible.st_dev), int(visible.st_ino))
            or int(held.st_uid) != int(os.getuid())
            or stat.S_IMODE(held.st_mode) != required_mode
        ):
            raise AdoptionError(f"{label} identity/owner/mode drift")
        payload, final_stat = _read_fd(descriptor, identity, label=label)
        return {
            "path": path,
            "descriptor": descriptor,
            "payload": payload,
            "stat": final_stat,
            "fingerprint": (
                int(final_stat.st_dev),
                int(final_stat.st_ino),
                int(final_stat.st_mode),
                int(final_stat.st_uid),
                int(final_stat.st_gid),
                int(final_stat.st_nlink),
                int(final_stat.st_size),
                int(final_stat.st_mtime_ns),
                int(final_stat.st_ctime_ns),
            ),
            "required_mode": required_mode,
            "identity": _identity(path, payload),
        }
    except BaseException:
        os.close(descriptor)
        raise


def _finish_external(record: Mapping[str, object], *, label: str) -> None:
    path = record["path"]
    descriptor = record["descriptor"]
    held = os.fstat(descriptor)
    payload, final_stat = _read_fd(
        descriptor,
        (int(held.st_dev), int(held.st_ino)),
        label=f"final {label}",
    )
    final_fingerprint = (
        int(final_stat.st_dev),
        int(final_stat.st_ino),
        int(final_stat.st_mode),
        int(final_stat.st_uid),
        int(final_stat.st_gid),
        int(final_stat.st_nlink),
        int(final_stat.st_size),
        int(final_stat.st_mtime_ns),
        int(final_stat.st_ctime_ns),
    )
    if (
        payload != record["payload"]
        or final_fingerprint != record["fingerprint"]
        or int(final_stat.st_uid) != int(os.getuid())
        or int(final_stat.st_nlink) != 1
        or stat.S_IMODE(final_stat.st_mode) != int(record["required_mode"])
    ):
        raise AdoptionError(f"{label} held bytes changed")
    visible = os.lstat(path)
    if (
        stat.S_ISLNK(visible.st_mode)
        or (int(visible.st_dev), int(visible.st_ino))
        != (int(held.st_dev), int(held.st_ino))
    ):
        raise AdoptionError(f"{label} visible inode changed")


def _result_identity_from_inventory(
    rows_by_path: Mapping[str, Mapping[str, object]], path: Path
) -> dict[str, object]:
    row = rows_by_path.get(str(path))
    if type(row) is not dict or row.get("kind") != "regular":
        raise AdoptionError(f"missing r4 inventory identity: {path}")
    return {
        "path": str(path),
        "size_bytes": row["size_bytes"],
        "sha256": row["sha256"],
    }


def _validate_csv_schedule(payload: bytes, *, arm_id: str) -> None:
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise AdoptionError(f"{arm_id} diagnostics is not UTF-8") from exc
    reader = csv.DictReader(io.StringIO(text, newline=""))
    if reader.fieldnames != list(DIAGNOSTIC_FIELDS):
        raise AdoptionError(f"{arm_id} diagnostics header mismatch")
    rows = list(reader)
    if len(rows) != 1800:
        raise AdoptionError(f"{arm_id} diagnostics row count is not 1800")
    for index, row in enumerate(rows):
        if row.get("raw_index") != str(index):
            raise AdoptionError(f"{arm_id} diagnostics raw schedule drift")
        expected_published = "True" if index % 2 == 1 else "False"
        if row.get("published") != expected_published:
            raise AdoptionError(f"{arm_id} diagnostics publish schedule drift")


def _arm_paths(root: Path, arm_id: str) -> dict[str, Path]:
    directory = root / ARM_DIRECTORIES[arm_id]
    return {
        "command_contract": directory / "command_contract.json",
        "attempt": directory / "producer_attempt.json",
        "launcher_start_receipt": directory / "launcher_start_receipt.json",
        "launcher_rc_receipt": directory / "launcher_rc_receipt.json",
        "manifest": directory / "export_manifest.json",
        "feature_bag": directory / "features.bag",
        "diagnostics": directory / "raw_diagnostics.csv",
        "legacy_primitive_manifest": directory / "legacy_primitive_manifest.json",
        "private_work_directory": directory / "private_work",
    }


def _build_authorized_argv(freeze: Mapping[str, object]) -> list[str]:
    frozen = freeze["authoritative_commands"]["post_run_audit"]["argv"]
    if type(frozen) is not list or len(frozen) < 8:
        raise AdoptionError("frozen post-run audit argv malformed")
    result = list(frozen)
    if result[:4] != [
        "/usr/bin/python3.8",
        "-B",
        "-m",
        "scripts.audit_matched_birth_rawlk_pair_formal_v2",
    ]:
        raise AdoptionError("frozen post-run audit module drift")
    result[3] = "scripts.audit_matched_birth_rawlk_pair_formal_r4_modefix_v1"
    try:
        output_index = result.index("--post-run-audit-json")
    except ValueError as exc:
        raise AdoptionError("frozen post-run audit output flag missing") from exc
    if (
        output_index + 1 >= len(result)
        or result[output_index + 1] != str(OLD_ERROR_SEAL)
    ):
        raise AdoptionError("frozen post-run audit output binding drift")
    result.extend(
        [
            "--continuation-adoption-json",
            str(DEFAULT_OUTPUT),
            "--continuation-seal-json",
            str(CONTINUATION_SEAL),
        ]
    )
    return result


def _walk_keys(value: object) -> list[str]:
    keys: list[str] = []
    if type(value) is dict:
        for key, child in value.items():
            keys.append(str(key).lower())
            keys.extend(_walk_keys(child))
    elif type(value) is list:
        for child in value:
            keys.extend(_walk_keys(child))
    return keys


def _validate_outcome_firewall(record: Mapping[str, object]) -> None:
    forbidden = FORBIDDEN_RECORD_KEYS & set(_walk_keys(record))
    if forbidden:
        raise AdoptionError(
            "continuation permit exposes forbidden result keys: "
            + ",".join(sorted(forbidden))
        )
    encoded = _canonical_bytes(record).lower()
    for token in (
        b'"winner"',
        b'"ape"',
        b'"rpe"',
        b'"metrics"',
        b'"detector_candidates"',
        b'"births"',
        b'"observations"',
    ):
        if token in encoded:
            raise AdoptionError(f"continuation permit contains outcome token {token!r}")


def _validate_canonical_record_shape(record: Mapping[str, object]) -> None:
    if type(record) is not dict or set(record) != set(RECORD_KEYS):
        raise AdoptionError("continuation permit top-level keyset mismatch")
    authorization = record.get("continuation_authorization")
    if type(authorization) is not dict or set(authorization) != set(
        CONTINUATION_AUTHORIZATION_KEYS
    ):
        raise AdoptionError("continuation authorization keyset mismatch")
    adoption_record = authorization.get("adoption_record")
    if type(adoption_record) is not dict or set(adoption_record) != set(
        ADOPTION_RECORD_KEYS
    ):
        raise AdoptionError("continuation adoption-record keyset mismatch")
    continuation_seal = authorization.get("continuation_seal")
    if type(continuation_seal) is not dict or set(continuation_seal) != set(
        CONTINUATION_SEAL_KEYS
    ):
        raise AdoptionError("continuation seal authorization keyset mismatch")


def _validate_and_build_record() -> dict[str, object]:
    if Path.cwd() != WORKSPACE_ROOT:
        raise AdoptionError("adoption builder cwd is not the frozen workspace root")
    if dict(os.environ) != dict(launcher.FROZEN_ENVIRONMENT):
        raise AdoptionError("adoption builder environment is not exact frozen env -i")
    if os.path.lexists(DEFAULT_OUTPUT):
        raise AdoptionError("adoption output namespace is already consumed")
    if os.path.lexists(CONTINUATION_SEAL):
        raise AdoptionError("continuation seal namespace is already consumed")
    if os.path.lexists(PY_CACHE_PREFIX):
        raise AdoptionError("dedicated frozen pycache prefix is not absent")
    for run_directory in VINS_RUN_DIRECTORIES:
        if os.path.lexists(run_directory):
            raise AdoptionError(f"pre-PASS VINS namespace exists: {run_directory}")

    snapshot = _snapshot_r4()
    external: dict[str, dict[str, object]] = {}
    try:
        external["frozen_auditor"] = _open_external(
            FROZEN_AUDITOR, required_mode=0o664, label="frozen auditor"
        )
        external["matched_core"] = _open_external(
            MATCHED_CORE, required_mode=0o664, label="matched producer core"
        )
        external["r3_adoption"] = _open_external(
            R3_ADOPTION, required_mode=0o444, label="r3 adoption"
        )
        external["human_record"] = _open_external(
            HUMAN_RECORD, required_mode=0o444, label="human incident record"
        )
        external["corrected_auditor"] = _open_external(
            CORRECTED_AUDITOR, required_mode=0o664, label="corrected auditor"
        )
        _strict_equal(
            external["corrected_auditor"]["identity"],
            EXPECTED_CORRECTED_AUDITOR,
            label="final corrected auditor identity",
        )
        external["builder"] = _open_external(
            Path(__file__).resolve(strict=True),
            required_mode=0o664,
            label="adoption builder",
        )

        root = snapshot["root"]
        payloads = snapshot["payloads"]
        rows_by_path = {
            str(row["path"]): row for row in snapshot["inventory"]
        }

        def payload(path: Path) -> bytes:
            value = payloads.get(path)
            if type(value) is not bytes:
                raise AdoptionError(f"held r4 payload missing: {path}")
            return value

        def document(path: Path) -> dict[str, object]:
            return _decode_json(path, payload(path), label=f"held r4 {path.name}")

        freeze = document(root / "formal900_freeze.json")
        start = document(root / "formal900_pre_run_start_receipt.json")
        old_error = document(root / "formal900_post_run_pair_seal.json")
        commit_identities = {
            "freeze": _identity(FREEZE_JSON, payload(FREEZE_JSON)),
            "pre_run_start_receipt": _identity(
                START_RECEIPT, payload(START_RECEIPT)
            ),
            "old_error_seal": _identity(OLD_ERROR_SEAL, payload(OLD_ERROR_SEAL)),
        }
        _strict_equal(
            commit_identities,
            EXPECTED_COMMIT_IDENTITIES,
            label="r4 immutable commit identities",
        )
        _strict_equal(old_error, EXPECTED_ERROR_SEAL, label="old ERROR seal")
        if (
            freeze.get("schema_version")
            != "aqua-fe-detector-birth-rawlk-matched-pair-formal-freeze-v2"
            or freeze.get("status") != "FROZEN"
            or freeze.get("fixed_semantics", {}).get("allow_prefix_nonformal")
            is not False
            or freeze.get("fixed_semantics", {}).get("expected_published_frames")
            != 900
            or freeze.get("fixed_semantics", {}).get("expected_raw_frames") != 1800
        ):
            raise AdoptionError("r4 freeze is not exact formal900")
        if (
            start.get("schema_version")
            != "aqua-fe-detector-birth-rawlk-matched-pair-formal-audit-v2"
            or start.get("status") != "PASS_PRE_RUN_FREEZE_AND_ABSENCE"
            or start.get("pass") is not True
        ):
            raise AdoptionError("r4 pre-run start receipt did not pass")
        _strict_equal(
            start.get("pre_run_freeze"),
            EXPECTED_COMMIT_IDENTITIES["freeze"],
            label="r4 start-to-freeze binding",
        )
        _strict_equal(
            freeze.get("formal900_adoption"),
            EXPECTED_R3_ADOPTION,
            label="r4 freeze-to-r3-adoption binding",
        )
        _strict_equal(
            external["r3_adoption"]["identity"],
            EXPECTED_R3_ADOPTION,
            label="live r3 adoption identity",
        )
        r3_adoption = _decode_json(
            R3_ADOPTION,
            external["r3_adoption"]["payload"],
            label="r3 adoption",
        )
        if (
            r3_adoption.get("schema_version")
            != "aqua-fe-detector-birth-rawlk-formal900-adoption-v1"
            or r3_adoption.get("status")
            != "ADOPTED_R3_PASS_FOR_FRESH_FORMAL900_FREEZE_ONLY"
            or r3_adoption.get("target", {}).get("root") != str(R4_ROOT)
        ):
            raise AdoptionError("r3 adoption semantic binding drift")

        prior_result_rows = [
            row
            for row in r3_adoption["source_namespace"]["exact_tree_inventory"]
            if row.get("kind") == "regular"
            and Path(str(row.get("path", ""))).name in ARM_RESULT_FILES
        ]
        if (
            len(prior_result_rows) != 8
            or {row.get("mode_octal") for row in prior_result_rows} != {"0664"}
        ):
            raise AdoptionError("r3 PASS precedent result-role modes are not 0664")

        frozen_auditor_identity = external["frozen_auditor"]["identity"]
        core_identity = external["matched_core"]["identity"]
        _strict_equal(
            frozen_auditor_identity,
            freeze.get("auditor_identity"),
            label="frozen auditor identity",
        )
        _strict_equal(
            frozen_auditor_identity,
            freeze.get("audit_code_closure", {}).get("pair_auditor"),
            label="frozen auditor closure identity",
        )
        _strict_equal(
            core_identity,
            freeze.get("audit_code_closure", {}).get("matched_core"),
            label="matched producer core identity",
        )
        frozen_source = external["frozen_auditor"]["payload"]
        if (
            b"stat.S_IMODE(held.st_mode) != 0o444" not in frozen_source
            or b"active held regular-file contract failed" not in frozen_source
        ):
            raise AdoptionError("frozen auditor uniform-0444 predicate not found")
        core_source = external["matched_core"]["payload"]
        if (
            b'with work_manifest.open("xb") as handle:' not in core_source
            or b"_publish_owned(" not in core_source
        ):
            raise AdoptionError("matched core publication mechanism drift")

        expected_reserved = {
            str(root / arm_name / name)
            for arm_name in ARM_DIRECTORIES.values()
            for name in (ARM_RESULT_FILES | ARM_GOVERNANCE_FILES - {"command_contract.json"})
        } | {
            str(root / arm_name / "private_work")
            for arm_name in ARM_DIRECTORIES.values()
        } | {str(OLD_ERROR_SEAL)}
        if set(start.get("reserved_paths_absent", [])) != expected_reserved:
            raise AdoptionError("pre-run absence set is not the exact two-arm plan")

        arm_qualification: dict[str, object] = {}
        for arm_id in (XFEAT_ARM, GFTT_ARM):
            paths = _arm_paths(root, arm_id)
            freeze_paths = freeze["arms"][arm_id]["paths"]
            expected_freeze_paths = {
                "attempt_json": str(paths["attempt"]),
                "diagnostics_csv": str(paths["diagnostics"]),
                "feature_bag": str(paths["feature_bag"]),
                "legacy_primitive_manifest": str(
                    paths["legacy_primitive_manifest"]
                ),
                "manifest_json": str(paths["manifest"]),
                "private_work_directory": str(paths["private_work_directory"]),
            }
            _strict_equal(
                freeze_paths,
                expected_freeze_paths,
                label=f"{arm_id} freeze path mapping",
            )
            command = document(paths["command_contract"])
            attempt = document(paths["attempt"])
            launcher_start = document(paths["launcher_start_receipt"])
            launcher_rc = document(paths["launcher_rc_receipt"])
            manifest = document(paths["manifest"])
            legacy_manifest = document(paths["legacy_primitive_manifest"])
            identities = {
                role: _result_identity_from_inventory(rows_by_path, path)
                for role, path in paths.items()
                if role != "private_work_directory"
            }
            _strict_equal(
                identities["command_contract"],
                freeze["authoritative_commands"]["arms"][arm_id][
                    "command_contract"
                ],
                label=f"{arm_id} command identity",
            )
            if (
                command.get("schema_version")
                != "aqua-fe-matched-birth-sealed-command-v1"
                or command.get("arm_id") != arm_id
                or command.get("working_directory") != str(WORKSPACE_ROOT)
                or command.get("environment") != dict(launcher.FROZEN_ENVIRONMENT)
            ):
                raise AdoptionError(f"{arm_id} command contract drift")
            if (
                attempt.get("schema_version")
                != "aqua-fe-detector-birth-rawlk-attempt-v1"
                or attempt.get("status")
                != "ATTEMPT_CONSUMED_PROCESS_ENTERED_PRECHECK"
                or attempt.get("arm_id") != arm_id
                or attempt.get("attempt_count") != 1
                or attempt.get("process_start_count") != 1
                or attempt.get("no_retry") is not True
                or attempt.get("prefix_nonformal") is not False
            ):
                raise AdoptionError(f"{arm_id} attempt contract drift")
            if (
                launcher_start.get("schema_version")
                != "aqua-fe-matched-birth-launch-start-receipt-v2"
                or launcher_start.get("status")
                != "START_NAMESPACE_CONSUMED_PREVALIDATION"
                or launcher_start.get("attempt_count") != 1
                or launcher_start.get("launcher_process_start_count") != 1
                or launcher_start.get("reserved_producer_process_start_count") != 1
                or launcher_start.get("no_retry") is not True
                or launcher_start.get("no_deletion") is not True
                or launcher_start.get("producer_process_started_at_receipt")
                is not False
            ):
                raise AdoptionError(f"{arm_id} launcher start receipt drift")
            if (
                launcher_rc.get("schema_version")
                != "aqua-fe-matched-birth-launch-rc-receipt-v2"
                or launcher_rc.get("status") != "PROCESS_ENDED"
                or launcher_rc.get("arm_id") != arm_id
            ):
                raise AdoptionError(f"{arm_id} launcher RC receipt drift")
            _strict_equal(
                launcher_rc.get("command_contract"),
                identities["command_contract"],
                label=f"{arm_id} RC-to-command binding",
            )
            _strict_equal(
                launcher_rc.get("start_receipt"),
                identities["launcher_start_receipt"],
                label=f"{arm_id} RC-to-start binding",
            )
            _strict_equal(
                launcher_rc.get("actual_execution"),
                {
                    "argv": command["argv"],
                    "environment": command["environment"],
                    "working_directory": command["working_directory"],
                    "shell": False,
                },
                label=f"{arm_id} actual sealed execution",
            )
            _strict_equal(
                launcher_rc.get("pycache_contract"),
                {
                    "prefix": str(PY_CACHE_PREFIX),
                    "absent_pre": True,
                    "absent_post": True,
                    "deleted_by_launcher": False,
                },
                label=f"{arm_id} pycache absence contract",
            )
            process = launcher_rc.get("producer_process")
            if type(process) is not dict:
                raise AdoptionError(f"{arm_id} producer process is malformed")
            for key, expected in EXPECTED_PRODUCER_PROCESS.items():
                _strict_equal(
                    process.get(key), expected, label=f"{arm_id} process {key}"
                )
            if (
                manifest.get("schema_version")
                != "aqua-fe-detector-birth-rawlk-matched-export-v1"
                or manifest.get("status") != "FULL"
                or manifest.get("formal_eligible") is not True
                or manifest.get("formal_eligibility_reason")
                != "full_export_from_frozen_matched_cli_factory"
                or manifest.get("arm_contract", {}).get("arm_id") != arm_id
            ):
                raise AdoptionError(f"{arm_id} matched manifest is not FULL")
            if (
                legacy_manifest.get("status") != "FULL"
                or legacy_manifest.get("formal_eligible") is not True
                or legacy_manifest.get("formal_eligibility_reason")
                != "full_export_from_frozen_cli_production_factory"
            ):
                raise AdoptionError(f"{arm_id} legacy manifest is not FULL")
            for value, label in (
                (manifest, "matched"), (legacy_manifest, "legacy")
            ):
                if (
                    value.get("prefix", {}).get("requested_max_published_frames")
                    is not None
                    or value.get("prefix", {}).get("selected_published_frames")
                    != 900
                    or value.get("prefix", {}).get("source_total_published_frames")
                    != 900
                    or value.get("metrics", {}).get("published_frames") != 900
                    or value.get("metrics", {}).get("raw_frames_processed") != 1800
                    or type(value.get("raw_frame_diagnostics")) is not list
                    or len(value["raw_frame_diagnostics"]) != 1800
                ):
                    raise AdoptionError(
                        f"{arm_id} {label} FULL900/1800 schedule drift"
                    )
            _strict_equal(
                manifest.get("attempt"),
                {"identity": identities["attempt"], "payload": attempt},
                label=f"{arm_id} manifest-to-attempt binding",
            )
            _strict_equal(
                manifest.get("outputs"),
                {
                    "feature_bag": identities["feature_bag"],
                    "raw_diagnostics_csv": identities["diagnostics"],
                    "legacy_primitive_manifest": identities[
                        "legacy_primitive_manifest"
                    ],
                },
                label=f"{arm_id} manifest output identities",
            )
            legacy_output = legacy_manifest.get("output_bag")
            if type(legacy_output) is not dict:
                raise AdoptionError(f"{arm_id} legacy output identity malformed")
            _strict_equal(
                {key: legacy_output.get(key) for key in ("size_bytes", "sha256")},
                {
                    key: identities["feature_bag"][key]
                    for key in ("size_bytes", "sha256")
                },
                label=f"{arm_id} legacy output bytes",
            )
            _validate_csv_schedule(payload(paths["diagnostics"]), arm_id=arm_id)
            arm_qualification[arm_id] = {
                "attempt_count": 1,
                "process_start_count": 1,
                "no_retry": True,
                "producer_return_code": 0,
                "natural_end_observed": True,
                "status": "FULL",
                "formal_eligible": True,
                "published_frame_schedule_count": 900,
                "raw_frame_schedule_count": 1800,
                "result_role_mode_octal": "0664",
            }

        _finish_snapshot(snapshot)
        for label, held in external.items():
            _finish_external(held, label=label)

        result_rows = [
            row
            for row in snapshot["inventory"]
            if row.get("kind") == "regular"
            and Path(str(row["path"])).name in ARM_RESULT_FILES
        ]
        governance_rows = [
            row
            for row in snapshot["inventory"]
            if row.get("kind") == "regular" and row not in result_rows
        ]
        if (
            len(result_rows) != 8
            or {row["mode_octal"] for row in result_rows} != {"0664"}
            or len(governance_rows) != 11
            or {row["mode_octal"] for row in governance_rows} != {"0444"}
        ):
            raise AdoptionError("r4 role-specific mode partition drift")

        corrected_identity = external["corrected_auditor"]["identity"]
        authorized_argv = _build_authorized_argv(freeze)
        builder_identity = external["builder"]["identity"]
        record = {
            "schema_version": SCHEMA_VERSION,
            "status": STATUS,
            "scientific_role": SCIENTIFIC_ROLE,
            "builder_identity": builder_identity,
            "builder_execution_contract": {
                "working_directory": str(WORKSPACE_ROOT),
                "environment": dict(launcher.FROZEN_ENVIRONMENT),
                "authorized_write_once_argv": [
                    "/usr/bin/python3.8",
                    "-B",
                    "-m",
                    "scripts.build_matched_birth_formal900_r4_mode_false_negative_adoption_v1",
                    "--action",
                    "write-once",
                    "--output",
                    str(DEFAULT_OUTPUT),
                ],
                "producer_started": False,
                "auditor_started": False,
                "vins_started": False,
                "evidence_held_and_rechecked_through_write_once": True,
            },
            "human_record": external["human_record"]["identity"],
            "incident": {
                "classification": "AUDITOR_ROLE_MODE_FALSE_NEGATIVE",
                "old_error_seal": {
                    **commit_identities["old_error_seal"],
                    "mode_octal": "0444",
                    "status": "ERROR",
                    "pass": False,
                    "error_type": "AuditFailure",
                },
                "namespace_consumed_no_retry": True,
                "scientific_pair_pass_not_yet_established": True,
                "scientific_pair_fail_not_established": True,
            },
            "source_namespace": {
                "root": str(R4_ROOT),
                "filesystem_type": "ext4",
                "device_id": EXPECTED_DEVICE_ID,
                "directory_count": 5,
                "regular_file_count": 19,
                "tree_entry_count": 24,
                "exact_tree_inventory": snapshot["inventory"],
                "role_mode_contract": {
                    "directories": "0700",
                    "governance_and_receipt_regular_files": "0444",
                    "producer_result_regular_files": "0664",
                },
            },
            "execution_qualification": {
                "mode": "formal900",
                "published_frame_schedule_count": 900,
                "raw_frame_schedule_count": 1800,
                "arms": arm_qualification,
                "gftt_decision_precommitted_before_any_gftt_result": {
                    "decision_source": commit_identities["freeze"],
                    "pre_result_absence_source": commit_identities[
                        "pre_run_start_receipt"
                    ],
                    "both_arm_commands_frozen": True,
                    "both_arm_result_names_absent_at_pre_run_start": True,
                    "gftt_run_decision_depended_on_xfeat_or_gftt_result": False,
                },
            },
            "mode_false_negative_qualification": {
                "frozen_auditor": frozen_auditor_identity,
                "matched_producer_core": core_identity,
                "frozen_auditor_uniform_governed_regular_mode_octal": "0444",
                "failed_role": "producer_result_regular_file",
                "failed_path": str(R4_ROOT / "xfeat_r4/export_manifest.json"),
                "observed_and_correct_result_role_mode_octal": "0664",
                "r3_pass_precedent": {
                    "adoption": EXPECTED_R3_ADOPTION,
                    "result_role_file_count": 8,
                    "result_role_mode_octal": "0664",
                    "r3_pair_seal_status": "PASS",
                },
                "scientific_result_validation_reached_by_old_auditor": False,
                "allowed_correction": (
                    "replace only the uniform governed-file 0444 predicate with "
                    "the frozen role-specific 0444/0664 mapping"
                ),
            },
            "continuation_authorization": {
                "adoption_record": {
                    "path": str(DEFAULT_OUTPUT),
                    "schema_version": SCHEMA_VERSION,
                    "builder_identity": builder_identity,
                },
                "corrected_auditor": {
                    **corrected_identity,
                    "mode_octal": "0664",
                },
                "old_error_seal": commit_identities["old_error_seal"],
                "continuation_seal": {
                    "path": str(CONTINUATION_SEAL),
                    "required_pre_run_state": "ABSENT",
                    "publication_mode_octal": "0444",
                    "write_once_no_clobber": True,
                },
                "authorized_argv": authorized_argv,
                "environment": dict(launcher.FROZEN_ENVIRONMENT),
                "working_directory": str(WORKSPACE_ROOT),
                "authorized_invocation_count": 1,
                "detector_or_producer_rerun_authorized": False,
                "r4_chmod_authorized": False,
                "old_error_seal_replacement_authorized": False,
                "other_scientific_or_governance_change_authorized": False,
                "vins_authorized_before_corrected_pass": False,
                "vins_authorization_on_corrected_error_or_fail": False,
                "vins_authorization_on_corrected_strict_pass": True,
            },
            "outcome_firewall": {
                "result_files_read_only_for_integrity_and_schedule_qualification": True,
                "result_values_exposed_in_permit": False,
                "relative_arm_comparison_exposed_in_permit": False,
                "result_dependent_continuation_configuration": False,
                "only_inventory_governance_and_mode_correction_exposed": True,
            },
            "claim_boundary": {
                "confirmatory": False,
                "statistical_significance": False,
                "whole_slam_superiority": False,
                "current_pair_contract_pass": False,
                "current_pair_contract_fail": False,
                "corrected_strict_pass_required_before_vins": True,
            },
        }
        _validate_canonical_record_shape(record)
        _validate_outcome_firewall(record)
        return record
    finally:
        for held in external.values():
            try:
                os.close(held["descriptor"])
            except OSError:
                pass
        _close_snapshot(snapshot)


def build_record() -> dict[str, object]:
    return _validate_and_build_record()


def _open_publication_guard(record: Mapping[str, object]) -> dict[str, object]:
    """Re-hold every source that the record claims before publication."""

    snapshot = _snapshot_r4()
    external: dict[str, dict[str, object]] = {}
    try:
        for key, path, mode, label in (
            ("frozen_auditor", FROZEN_AUDITOR, 0o664, "frozen auditor"),
            ("matched_core", MATCHED_CORE, 0o664, "matched producer core"),
            ("r3_adoption", R3_ADOPTION, 0o444, "r3 adoption"),
            ("human_record", HUMAN_RECORD, 0o444, "human incident record"),
            ("corrected_auditor", CORRECTED_AUDITOR, 0o664, "corrected auditor"),
            (
                "builder",
                Path(__file__).resolve(strict=True),
                0o664,
                "adoption builder",
            ),
        ):
            external[key] = _open_external(path, required_mode=mode, label=label)
        _strict_equal(
            snapshot["inventory"],
            record["source_namespace"]["exact_tree_inventory"],
            label="publication-guard r4 inventory",
        )
        _strict_equal(
            external["builder"]["identity"],
            record["builder_identity"],
            label="publication-guard builder identity",
        )
        _strict_equal(
            external["builder"]["identity"],
            record["continuation_authorization"]["adoption_record"][
                "builder_identity"
            ],
            label="publication-guard authorized builder identity",
        )
        _strict_equal(
            external["corrected_auditor"]["identity"],
            EXPECTED_CORRECTED_AUDITOR,
            label="publication-guard final corrected auditor identity",
        )
        _strict_equal(
            EXPECTED_CORRECTED_AUDITOR,
            {
                key: record["continuation_authorization"]["corrected_auditor"][key]
                for key in ("path", "size_bytes", "sha256")
            },
            label="publication-guard corrected auditor identity",
        )
        _strict_equal(
            external["human_record"]["identity"],
            record["human_record"],
            label="publication-guard human record identity",
        )
        _strict_equal(
            external["frozen_auditor"]["identity"],
            record["mode_false_negative_qualification"]["frozen_auditor"],
            label="publication-guard frozen auditor identity",
        )
        _strict_equal(
            external["matched_core"]["identity"],
            record["mode_false_negative_qualification"]["matched_producer_core"],
            label="publication-guard matched core identity",
        )
        _strict_equal(
            external["r3_adoption"]["identity"],
            record["mode_false_negative_qualification"]["r3_pass_precedent"][
                "adoption"
            ],
            label="publication-guard r3 adoption identity",
        )
        if os.path.lexists(DEFAULT_OUTPUT):
            raise AdoptionError("adoption output became present before publication")
        if os.path.lexists(CONTINUATION_SEAL):
            raise AdoptionError("continuation seal became present before publication")
        if os.path.lexists(PY_CACHE_PREFIX):
            raise AdoptionError("dedicated pycache prefix appeared before publication")
        for run_directory in VINS_RUN_DIRECTORIES:
            if os.path.lexists(run_directory):
                raise AdoptionError(
                    f"pre-PASS VINS namespace appeared before publication: {run_directory}"
                )
        return {"snapshot": snapshot, "external": external}
    except BaseException:
        for held in external.values():
            os.close(held["descriptor"])
        _close_snapshot(snapshot)
        raise


def _finish_publication_guard(guard: Mapping[str, object]) -> None:
    first_error: BaseException | None = None
    try:
        _finish_snapshot(guard["snapshot"])
    except BaseException as exc:
        first_error = exc
    for label, held in guard["external"].items():
        try:
            _finish_external(held, label=f"publication-guard {label}")
        except BaseException as exc:
            if first_error is None:
                first_error = exc
    if first_error is not None:
        raise first_error


def _close_publication_guard(guard: Mapping[str, object]) -> None:
    for held in guard["external"].values():
        try:
            os.close(held["descriptor"])
        except OSError:
            pass
    _close_snapshot(guard["snapshot"])


def _write_all(descriptor: int, payload: bytes) -> None:
    offset = 0
    while offset < len(payload):
        written = os.write(descriptor, payload[offset:])
        if written <= 0:
            raise AdoptionError("zero-progress adoption write")
        offset += written


def _replace_held_payload(descriptor: int, payload: bytes) -> None:
    os.lseek(descriptor, 0, os.SEEK_SET)
    os.ftruncate(descriptor, 0)
    _write_all(descriptor, payload)


def _invalid_publication_bytes(status: str) -> bytes:
    return _canonical_bytes(
        {
            "schema_version": (
                "aqua-fe-detector-birth-rawlk-r4-adoption-publication-terminal-v1"
            ),
            "status": status,
            "adoption_authorized": False,
            "namespace_consumed_no_retry": True,
        }
    )


def write_once(
    output: Path,
    record: Mapping[str, object],
    *,
    held_source_postcheck: object | None = None,
    after_final_fsync_hook: object | None = None,
) -> dict[str, object]:
    if output != DEFAULT_OUTPUT or output.expanduser().absolute() != output:
        raise AdoptionError("adoption output path is not the frozen canonical path")
    if output.parent.resolve(strict=True) != output.parent:
        raise AdoptionError("adoption parent is not canonical and symlink-free")
    payload = _canonical_bytes(record)
    parent_visible = os.lstat(output.parent)
    parent_descriptor = os.open(
        output.parent,
        os.O_RDONLY
        | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_CLOEXEC", 0),
    )
    try:
        parent_held = os.fstat(parent_descriptor)
        if (
            not stat.S_ISDIR(parent_held.st_mode)
            or stat.S_ISLNK(parent_visible.st_mode)
            or (int(parent_visible.st_dev), int(parent_visible.st_ino))
            != (int(parent_held.st_dev), int(parent_held.st_ino))
            or int(parent_held.st_uid) != int(os.getuid())
            or int(parent_held.st_dev) != EXPECTED_DEVICE_ID
            or frozen_audit._fstatfs_magic(parent_descriptor)
            != frozen_audit.EXT4_SUPER_MAGIC
        ):
            raise AdoptionError("adoption parent identity/filesystem drift")
        try:
            os.stat(output.name, dir_fd=parent_descriptor, follow_symlinks=False)
        except FileNotFoundError:
            pass
        else:
            raise AdoptionError("adoption namespace is already consumed")
        descriptor = os.open(
            output.name,
            os.O_RDWR
            | os.O_CREAT
            | os.O_EXCL
            | getattr(os, "O_NOFOLLOW", 0)
            | getattr(os, "O_CLOEXEC", 0),
            0o444,
            dir_fd=parent_descriptor,
        )
        try:
            os.fchmod(descriptor, 0o444)
            opened = os.fstat(descriptor)
            identity = (int(opened.st_dev), int(opened.st_ino))
            if (
                not stat.S_ISREG(opened.st_mode)
                or stat.S_IMODE(opened.st_mode) != 0o444
                or int(opened.st_nlink) != 1
            ):
                raise AdoptionError("adoption reservation identity/mode failure")
            # Reserve the permanent namespace with a canonical document that
            # is intentionally not an adoption permit.  The corrected auditor
            # rejects this schema if any later source recheck fails.
            pending = _invalid_publication_bytes(
                "INVALID_PENDING_HELD_SOURCE_POSTCHECK"
            )
            _write_all(descriptor, pending)
            os.fsync(descriptor)
            pending_stat = os.fstat(descriptor)
            pending_visible = os.stat(
                output.name, dir_fd=parent_descriptor, follow_symlinks=False
            )
            if (
                (int(pending_stat.st_dev), int(pending_stat.st_ino)) != identity
                or (int(pending_visible.st_dev), int(pending_visible.st_ino))
                != identity
                or stat.S_ISLNK(pending_visible.st_mode)
                or stat.S_IMODE(pending_stat.st_mode) != 0o444
                or int(pending_stat.st_size) != len(pending)
            ):
                raise AdoptionError("adoption pending reservation identity drift")
            os.fsync(parent_descriptor)

            try:
                if held_source_postcheck is not None:
                    held_source_postcheck()
            except BaseException:
                # Preserve a machine-readable, permanently consumed, invalid
                # namespace.  Even if this best-effort rewrite itself fails,
                # the pre-existing PENDING schema is not an adoption permit.
                try:
                    invalid = _invalid_publication_bytes(
                        "INVALID_HELD_SOURCE_POSTCHECK_FAILED"
                    )
                    _replace_held_payload(descriptor, invalid)
                    os.fsync(descriptor)
                    os.fsync(parent_descriptor)
                except OSError:
                    pass
                raise

            # Only a successful held-source postcheck may install the adoption
            # schema, and it is installed on the same reserved inode.
            try:
                _replace_held_payload(descriptor, payload)
                os.fsync(descriptor)
                if after_final_fsync_hook is not None:
                    after_final_fsync_hook()
                final = os.fstat(descriptor)
                visible = os.stat(
                    output.name, dir_fd=parent_descriptor, follow_symlinks=False
                )
                if (
                    (int(final.st_dev), int(final.st_ino)) != identity
                    or (int(visible.st_dev), int(visible.st_ino)) != identity
                    or stat.S_ISLNK(visible.st_mode)
                    or stat.S_IMODE(final.st_mode) != 0o444
                    or int(final.st_size) != len(payload)
                ):
                    raise AdoptionError("adoption final publication identity drift")
                os.fsync(parent_descriptor)
                held_payload, held_stat = _read_fd(
                    descriptor, identity, label="published r4 continuation adoption"
                )
                visible_after = os.stat(
                    output.name, dir_fd=parent_descriptor, follow_symlinks=False
                )
                parent_after = os.lstat(output.parent)
                if (
                    held_payload != payload
                    or stat.S_IMODE(held_stat.st_mode) != 0o444
                    or stat.S_ISLNK(visible_after.st_mode)
                    or (int(visible_after.st_dev), int(visible_after.st_ino))
                    != identity
                    or stat.S_ISLNK(parent_after.st_mode)
                    or (int(parent_after.st_dev), int(parent_after.st_ino))
                    != (int(parent_held.st_dev), int(parent_held.st_ino))
                ):
                    raise AdoptionError("adoption held/visible publication drift")
            except BaseException:
                # A complete adoption payload must never survive a failed
                # final commit check on the inode we own.
                try:
                    invalid = _invalid_publication_bytes(
                        "INVALID_FINAL_PUBLICATION_CHECK_FAILED"
                    )
                    _replace_held_payload(descriptor, invalid)
                    os.fsync(descriptor)
                    os.fsync(parent_descriptor)
                except OSError:
                    pass
                raise
        finally:
            try:
                os.close(descriptor)
            except OSError:
                pass
    finally:
        try:
            os.close(parent_descriptor)
        except OSError:
            pass
    return _identity(output, payload)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument("--action", choices=("check", "write-once"), required=True)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        record = build_record()
        payload = _canonical_bytes(record)
        result: dict[str, object] = {
            "schema_version": SCHEMA_VERSION,
            "status": "PASS_R4_MODE_FALSE_NEGATIVE_ADOPTION_PREPUBLICATION_CHECK",
            "record_sha256": hashlib.sha256(payload).hexdigest(),
            "record_size_bytes": len(payload),
            "producer_started": False,
            "auditor_started": False,
            "vins_started": False,
            "adoption_published": False,
        }
        if args.action == "write-once":
            guard = _open_publication_guard(record)
            try:
                _finish_publication_guard(guard)
                result["adoption"] = write_once(
                    args.output,
                    record,
                    held_source_postcheck=lambda: _finish_publication_guard(guard),
                )
                result["adoption_published"] = True
                result["status"] = "PASS_R4_MODE_FALSE_NEGATIVE_ADOPTION_SEALED"
            finally:
                _close_publication_guard(guard)
        print(json.dumps(result, sort_keys=True))
        return 0
    except (AdoptionError, OSError, ValueError, KeyError, TypeError) as exc:
        print(
            f"R4_MODE_FALSE_NEGATIVE_ADOPTION_BLOCKED:{type(exc).__name__}:{exc}",
            file=sys.stderr,
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
