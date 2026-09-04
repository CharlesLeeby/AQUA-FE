#!/usr/bin/env python3
"""Additive, one-shot continuation audit for the immutable formal900 r4 pair.

The frozen formal-v2 auditor consumed its r4 output name with an ERROR after
requiring mode 0444 for producer scientific outputs that were intentionally
published mode 0664.  This module does not replace that evidence and does not
rerun either producer.  It holds the complete existing r4 tree and locked
inputs, admits only that regular-file mode correction, delegates all semantic
and scientific validation to the exact frozen formal-v2 auditor, and publishes
one fresh continuation seal outside r4.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import stat
import sys
from typing import Mapping, Sequence


WORKSPACE_ROOT = Path(__file__).resolve().parents[1]
if str(WORKSPACE_ROOT) not in sys.path:
    sys.path.insert(0, str(WORKSPACE_ROOT))

from scripts import audit_matched_birth_rawlk_pair_formal_v2 as old
from scripts import run_matched_birth_arm_once_v1 as sealed_launcher


SCHEMA_VERSION = (
    "aqua-fe-detector-birth-rawlk-matched-pair-formal-r4-"
    "modefix-continuation-audit-v1"
)
ADOPTION_SCHEMA_VERSION = (
    "aqua-fe-detector-birth-rawlk-formal900-r4-mode-false-negative-"
    "adoption-v1"
)
OLD_AUDITOR_PATH = WORKSPACE_ROOT / "scripts/audit_matched_birth_rawlk_pair_formal_v2.py"
OLD_AUDITOR_SIZE = 344658
OLD_AUDITOR_SHA256 = (
    "39019432eb842aa53efdb9df9976a6158df19a7db8a6d813f0749bce2ffaff73"
)
R4_ROOT = old.ARTIFACT_NAMESPACE_ROOT
OLD_ERROR_SEAL_PATH = R4_ROOT / old.R4_ROOT_ARTIFACT_NAMES["post_run_pair_seal"]
OLD_ERROR_SEAL_SIZE = 461
OLD_ERROR_SEAL_SHA256 = (
    "20a8ed084c4c3d08640e1f7c7571cb927d049aadd8ba5600f11b0ec193b948d7"
)
CONTINUATION_PATH = (
    WORKSPACE_ROOT
    / "papers/a02_4500_6300_matched_birth_formal900_r4_mode_false_negative_adoption_v1.json"
)
CONTINUATION_SEAL_PATH = (
    WORKSPACE_ROOT
    / "papers/a02_4500_6300_matched_birth_formal900_r4_modefix_continuation_seal_v1.json"
)
ADOPTION_BUILDER_PATH = (
    WORKSPACE_ROOT
    / "scripts/build_matched_birth_formal900_r4_mode_false_negative_adoption_v1.py"
)

SCIENTIFIC_OUTPUT_NAMES = frozenset(
    {"features.bag", "export_manifest.json", "raw_diagnostics.csv", "legacy_primitive_manifest.json"}
)
GOVERNANCE_ARM_NAMES = frozenset(
    {"command_contract.json", "producer_attempt.json", "launcher_start_receipt.json", "launcher_rc_receipt.json"}
)
ARM_FILE_NAMES = SCIENTIFIC_OUTPUT_NAMES | GOVERNANCE_ARM_NAMES
ROOT_FILE_NAMES = frozenset(old.R4_ROOT_ARTIFACT_NAMES.values())


def _canonical_bytes(payload: object) -> bytes:
    return old._canonical_bytes(payload)


def _identity(path: Path, *, label: str) -> dict[str, object]:
    return old._file_identity(path, label=label)


def _expected_old_error_payload() -> dict[str, object]:
    return {
        "claim_boundary": {
            "contract_pass": False,
            "output_namespace_consumed_no_retry": True,
        },
        "error": {
            "message": (
                "active held regular-file contract failed: "
                "/home/ma/AQUA-FE_WS/experiments/"
                "matched_birth_a02_4500_6300_formal900_r4/"
                "xfeat_r4/export_manifest.json"
            ),
            "type": "AuditFailure",
        },
        "pass": False,
        "schema_version": old.SCHEMA_VERSION,
        "scientific_role": "post_result_development_exploratory_detector_birth_ablation",
        "status": "ERROR",
    }


def _strict_equal(actual: object, expected: object, *, label: str) -> None:
    old._strict_equal(actual, expected, label=label)


def _absolute_canonical(path: Path, *, label: str, strict: bool = True) -> Path:
    lexical = path.expanduser().absolute()
    if lexical != path:
        raise old.AuditFailure(f"{label} is not an absolute lexical path")
    try:
        resolved = path.resolve(strict=strict)
    except OSError as exc:
        raise old.AuditFailure(f"{label} cannot be resolved") from exc
    expected = path if strict else path.parent.resolve(strict=True) / path.name
    if resolved != expected:
        raise old.AuditFailure(f"{label} is not canonical and symlink-free")
    return path


def _validate_old_auditor_identity() -> dict[str, object]:
    if OLD_AUDITOR_SIZE <= 0 or len(OLD_AUDITOR_SHA256) != 64:
        raise old.AuditFailure("frozen old auditor identity constant is not pinned")
    if Path(old.__file__).resolve(strict=True) != OLD_AUDITOR_PATH:
        raise old.AuditFailure("imported old auditor path drift")
    identity = _identity(OLD_AUDITOR_PATH, label="frozen old formal-v2 auditor")
    _strict_equal(
        identity,
        {
            "path": str(OLD_AUDITOR_PATH),
            "size_bytes": OLD_AUDITOR_SIZE,
            "sha256": OLD_AUDITOR_SHA256,
        },
        label="frozen old formal-v2 auditor identity",
    )
    return identity


def _snapshot_file_mode(path: Path) -> int | None:
    if path.parent == R4_ROOT:
        return 0o444
    if path.parent.parent == R4_ROOT:
        if path.name in SCIENTIFIC_OUTPUT_NAMES:
            return 0o664
        if path.name in GOVERNANCE_ARM_NAMES:
            return 0o444
    return None


def _held_corrected_r4_snapshot(
    *,
    freeze_json: Path,
    source_bag: Path,
    raw_bag: Path,
    camera_yaml: Path,
    xfeat_bag: Path,
    xfeat_manifest: Path,
    xfeat_diagnostics: Path,
    xfeat_legacy_manifest: Path,
    xfeat_work_directory: Path,
    xfeat_attempt: Path,
    gftt_bag: Path,
    gftt_manifest: Path,
    gftt_diagnostics: Path,
    gftt_legacy_manifest: Path,
    gftt_work_directory: Path,
    gftt_attempt: Path,
    pre_run_start_receipt: Path,
    old_error_seal: Path,
) -> dict[str, object]:
    """Hold the exact immutable 5-directory/19-file r4 tree and three inputs."""

    root = _absolute_canonical(R4_ROOT, label="r4 root")
    exact_root_paths = {
        root / old.R4_ROOT_ARTIFACT_NAMES["freeze"],
        root / old.R4_ROOT_ARTIFACT_NAMES["pre_run_start_receipt"],
        root / old.R4_ROOT_ARTIFACT_NAMES["post_run_pair_seal"],
    }
    _strict_equal(
        {freeze_json, pre_run_start_receipt, old_error_seal},
        exact_root_paths,
        label="corrected snapshot exact r4 root artifacts",
    )
    role_paths = {
        old.XFEAT_ARM: {
            "feature_bag": xfeat_bag,
            "manifest_json": xfeat_manifest,
            "diagnostics_csv": xfeat_diagnostics,
            "legacy_primitive_manifest": xfeat_legacy_manifest,
            "private_work_directory": xfeat_work_directory,
            "attempt_json": xfeat_attempt,
        },
        old.GFTT_ARM: {
            "feature_bag": gftt_bag,
            "manifest_json": gftt_manifest,
            "diagnostics_csv": gftt_diagnostics,
            "legacy_primitive_manifest": gftt_legacy_manifest,
            "private_work_directory": gftt_work_directory,
            "attempt_json": gftt_attempt,
        },
    }
    exact_names = {
        "feature_bag": "features.bag",
        "manifest_json": "export_manifest.json",
        "diagnostics_csv": "raw_diagnostics.csv",
        "legacy_primitive_manifest": "legacy_primitive_manifest.json",
        "private_work_directory": "private_work",
        "attempt_json": "producer_attempt.json",
    }
    for arm_id, arm_name in old.R4_ARM_DIRECTORIES.items():
        expected = {
            key: root / arm_name / name for key, name in exact_names.items()
        }
        _strict_equal(
            role_paths[arm_id], expected, label=f"corrected snapshot {arm_id} paths"
        )

    directory_paths = {
        root,
        *(root / name for name in old.R4_ARM_DIRECTORIES.values()),
        *(
            root / name / "private_work"
            for name in old.R4_ARM_DIRECTORIES.values()
        ),
    }
    governed_paths = set(exact_root_paths)
    governed_paths.update(
        root / arm_name / name
        for arm_name in old.R4_ARM_DIRECTORIES.values()
        for name in ARM_FILE_NAMES
    )
    locked_paths = {source_bag, raw_bag, camera_yaml}
    all_file_paths = governed_paths | locked_paths
    if (
        len(directory_paths) != 5
        or len(governed_paths) != 19
        or len(locked_paths) != 3
        or len(all_file_paths) != 22
    ):
        raise old.AuditFailure("corrected snapshot path count is not exact 5/19/+3")

    directory_records: dict[Path, dict[str, object]] = {}
    file_records: dict[Path, dict[str, object]] = {}
    expected_listings: dict[Path, frozenset[str]] = {}

    def hold_directory(
        path: Path, *, name: str | None, parent_descriptor: int | None
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
                or stat.S_IMODE(held.st_mode) != 0o700
                or int(held.st_uid) != int(os.getuid())
            ):
                raise old.AuditFailure(f"corrected held directory contract failed: {path}")
            directory_records[path] = {
                "path": path,
                "descriptor": descriptor,
                "fingerprint": old._active_stat_fingerprint(held),
            }
            return descriptor
        except BaseException:
            os.close(descriptor)
            raise

    def hold_file(
        path: Path,
        *,
        name: str | None,
        parent_descriptor: int | None,
        governed: bool,
    ) -> None:
        _absolute_canonical(path, label=f"held evidence {path.name}")
        raw = str(path) if name is None else name
        visible = (
            os.lstat(path)
            if parent_descriptor is None
            else os.stat(raw, dir_fd=parent_descriptor, follow_symlinks=False)
        )
        descriptor = os.open(
            raw,
            os.O_RDONLY
            | getattr(os, "O_NOFOLLOW", 0)
            | getattr(os, "O_NONBLOCK", 0)
            | getattr(os, "O_CLOEXEC", 0),
            dir_fd=parent_descriptor,
        )
        try:
            held = os.fstat(descriptor)
            inode = (int(held.st_dev), int(held.st_ino))
            expected_mode = _snapshot_file_mode(path) if governed else None
            if (
                stat.S_ISLNK(visible.st_mode)
                or inode != (int(visible.st_dev), int(visible.st_ino))
                or not stat.S_ISREG(held.st_mode)
                or int(held.st_nlink) != 1
                or (
                    governed
                    and (
                        expected_mode is None
                        or stat.S_IMODE(held.st_mode) != expected_mode
                        or int(held.st_uid) != int(os.getuid())
                    )
                )
            ):
                raise old.AuditFailure(f"corrected held regular-file contract failed: {path}")
            capture = path.suffix != ".bag"
            payload, digest, final_stat = old._stream_held_file(
                descriptor,
                expected_identity=inode,
                label=f"corrected held {path.name}",
                capture=capture,
            )
            file_records[path] = {
                "path": path,
                "descriptor": descriptor,
                "inode_identity": inode,
                "fingerprint": old._active_stat_fingerprint(final_stat),
                "identity": {
                    "path": str(path),
                    "size_bytes": digest["size_bytes"],
                    "sha256": digest["sha256"],
                },
                "payload": payload,
                "governed": governed,
                "expected_mode_octal": (
                    None if expected_mode is None else format(expected_mode, "04o")
                ),
            }
        except BaseException:
            os.close(descriptor)
            raise

    try:
        root_fd = hold_directory(root, name=None, parent_descriptor=None)
        if old._fstatfs_magic(root_fd) != old.EXT4_SUPER_MAGIC:
            raise old.AuditFailure("corrected r4 held root is not ext4")
        root_names = set(ROOT_FILE_NAMES) | set(old.R4_ARM_DIRECTORIES.values())
        expected_listings[root] = frozenset(root_names)
        if set(os.listdir(root_fd)) != root_names:
            raise old.AuditFailure("corrected r4 root topology is not exact")
        for arm_name in old.R4_ARM_DIRECTORIES.values():
            arm = root / arm_name
            arm_fd = hold_directory(arm, name=arm_name, parent_descriptor=root_fd)
            arm_names = set(ARM_FILE_NAMES) | {"private_work"}
            expected_listings[arm] = frozenset(arm_names)
            if set(os.listdir(arm_fd)) != arm_names:
                raise old.AuditFailure(f"corrected {arm_name} topology is not exact")
            private = arm / "private_work"
            private_fd = hold_directory(
                private, name="private_work", parent_descriptor=arm_fd
            )
            expected_listings[private] = frozenset()
            if os.listdir(private_fd):
                raise old.AuditFailure(f"corrected {arm_name} private work is not empty")

        for name in sorted(ROOT_FILE_NAMES):
            hold_file(root / name, name=name, parent_descriptor=root_fd, governed=True)
        for arm_name in old.R4_ARM_DIRECTORIES.values():
            arm = root / arm_name
            arm_fd = int(directory_records[arm]["descriptor"])
            for name in sorted(ARM_FILE_NAMES):
                hold_file(
                    arm / name, name=name, parent_descriptor=arm_fd, governed=True
                )
        for path in (source_bag, raw_bag, camera_yaml):
            hold_file(path, name=None, parent_descriptor=None, governed=False)

        inode_identities = [
            tuple(record["inode_identity"]) for record in file_records.values()
        ]
        if len(inode_identities) != len(set(inode_identities)):
            raise old.AuditFailure("corrected r4 evidence/input inodes are not distinct")
        if set(directory_records) != directory_paths or set(file_records) != all_file_paths:
            raise old.AuditFailure("corrected held snapshot keyset drift")
        return {
            "action": "audit",
            "root": root,
            "directory_records": directory_records,
            "file_records": file_records,
            "required_file_paths": frozenset(all_file_paths),
            "expected_listings": expected_listings,
            "semantic_baseline": None,
        }
    except BaseException:
        for record in list(file_records.values()) + list(
            reversed(tuple(directory_records.values()))
        ):
            os.close(int(record["descriptor"]))
        raise


def _close_corrected_snapshot(snapshot: Mapping[str, object]) -> None:
    old._close_held_active_formal_snapshot(snapshot)


def _snapshot_inventory(snapshot: Mapping[str, object]) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for path, record in snapshot["directory_records"].items():
        observed = os.fstat(int(record["descriptor"]))
        rows.append(
            {
                "path": str(path),
                "kind": "directory",
                "mode_octal": format(stat.S_IMODE(observed.st_mode), "04o"),
                "size_bytes": int(observed.st_size),
                "device_id": int(observed.st_dev),
                "inode": int(observed.st_ino),
                "uid": int(observed.st_uid),
                "gid": int(observed.st_gid),
                "nlink": int(observed.st_nlink),
            }
        )
    for path, record in snapshot["file_records"].items():
        observed = os.fstat(int(record["descriptor"]))
        rows.append(
            {
                **copy.deepcopy(record["identity"]),
                "kind": "regular",
                "mode_octal": format(stat.S_IMODE(observed.st_mode), "04o"),
                "device_id": int(observed.st_dev),
                "inode": int(observed.st_ino),
                "uid": int(observed.st_uid),
                "gid": int(observed.st_gid),
                "nlink": int(observed.st_nlink),
                "governed": bool(record["governed"]),
            }
        )
    rows.sort(key=lambda row: str(row["path"]))
    if len(rows) != 27:
        raise old.AuditFailure("corrected snapshot inventory is not exact 5+19+3")
    return rows


def _builder_shaped_r4_inventory(
    snapshot: Mapping[str, object]
) -> list[dict[str, object]]:
    """Project the held snapshot onto the adoption builder's exact 24 rows."""

    rows: list[dict[str, object]] = []
    for path, record in snapshot["directory_records"].items():
        observed = os.fstat(int(record["descriptor"]))
        rows.append(
            {
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
        )
    for path, record in snapshot["file_records"].items():
        if not record["governed"]:
            continue
        observed = os.fstat(int(record["descriptor"]))
        rows.append(
            {
                "path": str(path),
                "kind": "regular",
                "mode_octal": format(stat.S_IMODE(observed.st_mode), "04o"),
                "uid": int(observed.st_uid),
                "gid": int(observed.st_gid),
                "device_id": int(observed.st_dev),
                "inode": int(observed.st_ino),
                "nlink": int(observed.st_nlink),
                "size_bytes": record["identity"]["size_bytes"],
                "sha256": record["identity"]["sha256"],
            }
        )
    rows.sort(key=lambda row: str(row["path"]))
    if len(rows) != 24:
        raise old.AuditFailure("adoption-shaped r4 inventory is not exact 5+19")
    return rows


def _validate_adoption_snapshot_binding(
    held_authorization: Mapping[str, object], snapshot: Mapping[str, object]
) -> None:
    payload = held_authorization["payload"]
    source = payload["source_namespace"]
    if type(source) is not dict or set(source) != {
        "root",
        "filesystem_type",
        "device_id",
        "directory_count",
        "regular_file_count",
        "tree_entry_count",
        "exact_tree_inventory",
        "role_mode_contract",
    }:
        raise old.AuditFailure("continuation adoption source namespace shape drift")
    root_stat = os.fstat(
        int(snapshot["directory_records"][R4_ROOT]["descriptor"])
    )
    if (
        source["root"] != str(R4_ROOT)
        or source["filesystem_type"] != "ext4"
        or source["device_id"] != int(root_stat.st_dev)
        or source["directory_count"] != 5
        or source["regular_file_count"] != 19
        or source["tree_entry_count"] != 24
    ):
        raise old.AuditFailure("continuation adoption source namespace contract drift")
    _strict_equal(
        source["role_mode_contract"],
        {
            "directories": "0700",
            "governance_and_receipt_regular_files": "0444",
            "producer_result_regular_files": "0664",
        },
        label="continuation adoption role-mode contract",
    )
    _strict_equal(
        source["exact_tree_inventory"],
        _builder_shaped_r4_inventory(snapshot),
        label="continuation adoption to held r4 inventory",
    )


def _open_held_continuation(path: Path) -> dict[str, object]:
    _absolute_canonical(path, label="continuation authorization")
    visible = os.lstat(path)
    descriptor = os.open(
        str(path),
        os.O_RDONLY
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_CLOEXEC", 0),
    )
    try:
        held = os.fstat(descriptor)
        inode = (int(held.st_dev), int(held.st_ino))
        if (
            stat.S_ISLNK(visible.st_mode)
            or not stat.S_ISREG(held.st_mode)
            or inode != (int(visible.st_dev), int(visible.st_ino))
            or int(held.st_nlink) != 1
            or int(held.st_uid) != int(os.getuid())
            or stat.S_IMODE(held.st_mode) != 0o444
        ):
            raise old.AuditFailure("continuation authorization held-file contract failed")
        encoded, final_stat = old._read_regular_descriptor_bytes(
            descriptor,
            expected_identity=inode,
            label="held continuation authorization",
        )
        try:
            payload = json.loads(encoded.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise old.AuditFailure("continuation authorization is not UTF-8 JSON") from exc
        if type(payload) is not dict or encoded != _canonical_bytes(payload):
            raise old.AuditFailure("continuation authorization is not one canonical object")
        return {
            "path": path,
            "descriptor": descriptor,
            "inode_identity": inode,
            "fingerprint": old._active_stat_fingerprint(final_stat),
            "bytes": encoded,
            "payload": payload,
            "identity": {
                "path": str(path),
                "size_bytes": len(encoded),
                "sha256": hashlib.sha256(encoded).hexdigest(),
            },
        }
    except BaseException:
        os.close(descriptor)
        raise


def _finish_held_continuation(held: Mapping[str, object]) -> None:
    descriptor = int(held["descriptor"])
    inode = tuple(held["inode_identity"])
    os.lseek(descriptor, 0, os.SEEK_SET)
    encoded, observed = old._read_regular_descriptor_bytes(
        descriptor,
        expected_identity=(int(inode[0]), int(inode[1])),
        label="final held continuation authorization",
    )
    visible = os.lstat(held["path"])
    if (
        encoded != held["bytes"]
        or old._active_stat_fingerprint(observed) != tuple(held["fingerprint"])
        or stat.S_ISLNK(visible.st_mode)
        or (int(visible.st_dev), int(visible.st_ino)) != (int(inode[0]), int(inode[1]))
        or stat.S_IMODE(visible.st_mode) != 0o444
    ):
        raise old.AuditFailure("continuation authorization drift before final commit")


def _close_held_continuation(held: Mapping[str, object]) -> None:
    os.close(int(held["descriptor"]))


def _open_held_source(
    *,
    path: Path,
    claim: object,
    required_mode: int,
    label: str,
    claim_includes_mode: bool,
) -> dict[str, object]:
    identity_keys = {"path", "size_bytes", "sha256", "mode_octal"}
    if not claim_includes_mode:
        identity_keys.remove("mode_octal")
    if (
        type(claim) is not dict
        or set(claim) != identity_keys
        or claim.get("path") != str(path)
        or type(claim.get("size_bytes")) is not int
        or claim["size_bytes"] <= 0
        or type(claim.get("sha256")) is not str
        or old._SHA256_RE.fullmatch(claim["sha256"]) is None
        or (
            claim_includes_mode
            and claim.get("mode_octal") != format(required_mode, "04o")
        )
    ):
        raise old.AuditFailure(f"{label} identity is malformed")
    visible = os.lstat(path)
    descriptor = os.open(
        str(path),
        os.O_RDONLY
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_CLOEXEC", 0),
    )
    try:
        held = os.fstat(descriptor)
        inode = (int(held.st_dev), int(held.st_ino))
        if (
            stat.S_ISLNK(visible.st_mode)
            or not stat.S_ISREG(held.st_mode)
            or inode != (int(visible.st_dev), int(visible.st_ino))
            or int(held.st_nlink) != 1
            or int(held.st_uid) != int(os.getuid())
            or stat.S_IMODE(held.st_mode) != required_mode
        ):
            raise old.AuditFailure(f"held {label} source contract failed")
        encoded, final_stat = old._read_regular_descriptor_bytes(
            descriptor,
            expected_identity=inode,
            label=f"held {label} source",
        )
        identity = {
            "path": str(path),
            "size_bytes": len(encoded),
            "sha256": hashlib.sha256(encoded).hexdigest(),
        }
        compared_claim = dict(claim)
        if claim_includes_mode:
            compared_claim.pop("mode_octal")
        _strict_equal(identity, compared_claim, label=f"held {label} source identity")
        return {
            "path": path,
            "descriptor": descriptor,
            "inode_identity": inode,
            "fingerprint": old._active_stat_fingerprint(final_stat),
            "bytes": encoded,
            "identity": identity,
            "required_mode": required_mode,
            "label": label,
        }
    except BaseException:
        os.close(descriptor)
        raise


def _finish_held_source(held: Mapping[str, object]) -> None:
    descriptor = int(held["descriptor"])
    inode = tuple(held["inode_identity"])
    os.lseek(descriptor, 0, os.SEEK_SET)
    encoded, observed = old._read_regular_descriptor_bytes(
        descriptor,
        expected_identity=(int(inode[0]), int(inode[1])),
        label=f"final held {held['label']} source",
    )
    visible = os.lstat(held["path"])
    if (
        encoded != held["bytes"]
        or old._active_stat_fingerprint(observed) != tuple(held["fingerprint"])
        or stat.S_ISLNK(visible.st_mode)
        or (int(visible.st_dev), int(visible.st_ino))
        != (int(inode[0]), int(inode[1]))
        or stat.S_IMODE(visible.st_mode) != int(held["required_mode"])
    ):
        raise old.AuditFailure(f"held {held['label']} source drift before final commit")


def _close_held_source(held: Mapping[str, object]) -> None:
    os.close(int(held["descriptor"]))


def _open_held_builder_source(claim: object) -> dict[str, object]:
    return _open_held_source(
        path=ADOPTION_BUILDER_PATH,
        claim=claim,
        required_mode=0o664,
        label="continuation adoption builder",
        claim_includes_mode=False,
    )


def _open_held_self_source(claim: object) -> dict[str, object]:
    return _open_held_source(
        path=Path(__file__).resolve(strict=True),
        claim=claim,
        required_mode=0o664,
        label="corrected continuation auditor",
        claim_includes_mode=True,
    )


def _finish_held_builder_source(held: Mapping[str, object]) -> None:
    _finish_held_source(held)


def _finish_held_self_source(held: Mapping[str, object]) -> None:
    _finish_held_source(held)


def _close_held_builder_source(held: Mapping[str, object]) -> None:
    _close_held_source(held)


def _close_held_self_source(held: Mapping[str, object]) -> None:
    _close_held_source(held)


def _corrected_auditor_identity() -> dict[str, object]:
    path = Path(__file__).resolve(strict=True)
    observed = os.lstat(path)
    identity = _identity(path, label="corrected continuation auditor")
    return {
        **identity,
        "mode_octal": format(stat.S_IMODE(observed.st_mode), "04o"),
    }


def _authorized_argv(args: argparse.Namespace) -> list[str]:
    values = [
        "/usr/bin/python3.8", "-B", "-m",
        "scripts.audit_matched_birth_rawlk_pair_formal_r4_modefix_v1",
        "--action", "audit",
        "--source-feature-bag", args.source_feature_bag,
        "--raw-image-bag", args.raw_image_bag,
        "--camera-yaml", args.camera_yaml,
        "--freeze-json", args.freeze_json,
        "--xfeat-bag", args.xfeat_bag,
        "--xfeat-manifest", args.xfeat_manifest,
        "--xfeat-diagnostics", args.xfeat_diagnostics,
        "--xfeat-legacy-manifest", args.xfeat_legacy_manifest,
        "--xfeat-work-directory", args.xfeat_work_directory,
        "--xfeat-attempt", args.xfeat_attempt,
        "--gftt-bag", args.gftt_bag,
        "--gftt-manifest", args.gftt_manifest,
        "--gftt-diagnostics", args.gftt_diagnostics,
        "--gftt-legacy-manifest", args.gftt_legacy_manifest,
        "--gftt-work-directory", args.gftt_work_directory,
        "--gftt-attempt", args.gftt_attempt,
        "--feature-topic", args.feature_topic,
        "--image-topic", args.image_topic,
    ]
    if args.allow_prefix:
        values.append("--allow-prefix")
    values.extend(
        [
            "--expected-published-frames", str(args.expected_published_frames),
            "--pre-run-start-receipt", args.pre_run_start_receipt,
            "--post-run-audit-json", args.post_run_audit_json,
            "--continuation-adoption-json", args.continuation_adoption_json,
            "--continuation-seal-json", args.continuation_seal_json,
        ]
    )
    return values


def _validate_continuation_authorization(
    held: Mapping[str, object], *, args: argparse.Namespace,
    corrected_auditor_identity: Mapping[str, object] | None = None,
) -> dict[str, object]:
    # These literals deliberately mirror the producer's exported schema.  A
    # cross-module unit test asserts equality with its public canonical sets.
    payload = held["payload"]
    top_keys = {
        "builder_execution_contract",
        "builder_identity",
        "claim_boundary",
        "continuation_authorization",
        "execution_qualification",
        "human_record",
        "incident",
        "mode_false_negative_qualification",
        "outcome_firewall",
        "schema_version",
        "scientific_role",
        "source_namespace",
        "status",
    }
    if set(payload) != top_keys:
        raise old.AuditFailure("continuation adoption top-level keyset drift")
    if payload.get("schema_version") != ADOPTION_SCHEMA_VERSION:
        raise old.AuditFailure("continuation authorization schema mismatch")
    if (
        payload.get("status")
        != "ADOPTED_CONSUMED_R4_FOR_ONE_MODE_CORRECTED_AUDIT_ONLY"
        or payload.get("scientific_role")
        != "POST_RESULT_INFRASTRUCTURE_RECOVERY_NO_RESULT_SELECTION"
    ):
        raise old.AuditFailure("continuation adoption status/scientific role drift")
    authorization = payload.get("continuation_authorization")
    if type(authorization) is not dict:
        raise old.AuditFailure("continuation authorization object is absent")
    required = {
        "corrected_auditor",
        "continuation_seal",
        "old_error_seal",
        "adoption_record",
        "authorized_argv",
        "authorized_invocation_count",
        "environment",
        "working_directory",
        "detector_or_producer_rerun_authorized",
        "r4_chmod_authorized",
        "old_error_seal_replacement_authorized",
        "other_scientific_or_governance_change_authorized",
        "vins_authorized_before_corrected_pass",
        "vins_authorization_on_corrected_error_or_fail",
        "vins_authorization_on_corrected_strict_pass",
    }
    if set(authorization) != required:
        raise old.AuditFailure("continuation authorization keyset drift")
    _strict_equal(
        authorization["corrected_auditor"],
        (
            _corrected_auditor_identity()
            if corrected_auditor_identity is None
            else corrected_auditor_identity
        ),
        label="authorized corrected auditor identity",
    )
    _strict_equal(
        authorization["continuation_seal"],
        {
            "path": str(CONTINUATION_SEAL_PATH),
            "required_pre_run_state": "ABSENT",
            "publication_mode_octal": "0444",
            "write_once_no_clobber": True,
        },
        label="authorized continuation seal",
    )
    expected_old_error = {
        "path": str(OLD_ERROR_SEAL_PATH),
        "size_bytes": OLD_ERROR_SEAL_SIZE,
        "sha256": OLD_ERROR_SEAL_SHA256,
    }
    _strict_equal(
        authorization["old_error_seal"],
        expected_old_error,
        label="authorized immutable old ERROR seal",
    )
    builder_identity = payload["builder_identity"]
    if (
        type(builder_identity) is not dict
        or set(builder_identity) != {"path", "size_bytes", "sha256"}
        or builder_identity.get("path") != str(ADOPTION_BUILDER_PATH)
        or type(builder_identity.get("size_bytes")) is not int
        or builder_identity["size_bytes"] <= 0
        or type(builder_identity.get("sha256")) is not str
        or old._SHA256_RE.fullmatch(builder_identity["sha256"]) is None
    ):
        raise old.AuditFailure("continuation adoption builder identity is malformed")
    adoption_contract = authorization["adoption_record"]
    _strict_equal(
        adoption_contract,
        {
            "path": str(CONTINUATION_PATH),
            "schema_version": ADOPTION_SCHEMA_VERSION,
            "builder_identity": builder_identity,
        },
        label="authorized continuation adoption record",
    )
    _strict_equal(
        authorization["authorized_argv"],
        _authorized_argv(args),
        label="authorized corrected auditor argv",
    )
    _strict_equal(
        authorization["environment"],
        dict(sealed_launcher.FROZEN_ENVIRONMENT),
        label="authorized corrected auditor environment",
    )
    if dict(os.environ) != dict(sealed_launcher.FROZEN_ENVIRONMENT):
        raise old.AuditFailure("live environment is not the authorized frozen environment")
    if authorization["working_directory"] != str(WORKSPACE_ROOT) or Path.cwd() != WORKSPACE_ROOT:
        raise old.AuditFailure("corrected auditor working directory drift")
    if (
        authorization["authorized_invocation_count"] != 1
        or authorization["detector_or_producer_rerun_authorized"] is not False
        or authorization["r4_chmod_authorized"] is not False
        or authorization["old_error_seal_replacement_authorized"] is not False
        or authorization["other_scientific_or_governance_change_authorized"] is not False
        or authorization["vins_authorized_before_corrected_pass"] is not False
        or authorization["vins_authorization_on_corrected_error_or_fail"] is not False
        or authorization["vins_authorization_on_corrected_strict_pass"] is not True
    ):
        raise old.AuditFailure("continuation authorization expands mutation/run authority")
    builder_execution = payload["builder_execution_contract"]
    if type(builder_execution) is not dict or (
        builder_execution.get("working_directory") != str(WORKSPACE_ROOT)
        or builder_execution.get("environment") != dict(sealed_launcher.FROZEN_ENVIRONMENT)
        or builder_execution.get("producer_started") is not False
        or builder_execution.get("auditor_started") is not False
        or builder_execution.get("vins_started") is not False
        or builder_execution.get("evidence_held_and_rechecked_through_write_once") is not True
    ):
        raise old.AuditFailure("continuation adoption builder execution contract drift")
    incident = payload["incident"]
    if type(incident) is not dict or (
        incident.get("classification") != "AUDITOR_ROLE_MODE_FALSE_NEGATIVE"
        or incident.get("namespace_consumed_no_retry") is not True
        or incident.get("scientific_pair_pass_not_yet_established") is not True
        or incident.get("scientific_pair_fail_not_established") is not True
    ):
        raise old.AuditFailure("continuation adoption incident classification drift")
    old_error_claim = incident.get("old_error_seal")
    if type(old_error_claim) is not dict:
        raise old.AuditFailure("continuation incident old ERROR claim malformed")
    _strict_equal(
        {key: old_error_claim.get(key) for key in ("path", "size_bytes", "sha256")},
        expected_old_error,
        label="continuation incident old ERROR identity",
    )
    mode_gate = payload["mode_false_negative_qualification"]
    if type(mode_gate) is not dict or (
        mode_gate.get("frozen_auditor_uniform_governed_regular_mode_octal") != "0444"
        or mode_gate.get("failed_role") != "producer_result_regular_file"
        or mode_gate.get("failed_path")
        != str(R4_ROOT / "xfeat_r4/export_manifest.json")
        or mode_gate.get("observed_and_correct_result_role_mode_octal") != "0664"
        or mode_gate.get("scientific_result_validation_reached_by_old_auditor") is not False
    ):
        raise old.AuditFailure("continuation adoption mode-false-negative gate drift")
    outcome_firewall = payload["outcome_firewall"]
    _strict_equal(
        outcome_firewall,
        {
            "result_files_read_only_for_integrity_and_schedule_qualification": True,
            "result_values_exposed_in_permit": False,
            "relative_arm_comparison_exposed_in_permit": False,
            "result_dependent_continuation_configuration": False,
            "only_inventory_governance_and_mode_correction_exposed": True,
        },
        label="continuation adoption outcome firewall",
    )
    claim = payload["claim_boundary"]
    _strict_equal(
        claim,
        {
            "confirmatory": False,
            "statistical_significance": False,
            "whole_slam_superiority": False,
            "current_pair_contract_pass": False,
            "current_pair_contract_fail": False,
            "corrected_strict_pass_required_before_vins": True,
        },
        label="continuation adoption claim boundary",
    )
    forbidden_keys = {
        "metrics", "observations", "detector_candidates", "births",
        "raw_births", "raw_drops", "unique_ids",
        "published_first_occurrences", "published_continuations",
        "observations_per_frame_max", "observations_per_frame_median",
        "observations_per_frame_min", "winner", "relative_result", "ape", "rpe",
    }

    def walk_keys(value: object) -> list[str]:
        result: list[str] = []
        if type(value) is dict:
            for key, child in value.items():
                result.append(str(key).lower())
                result.extend(walk_keys(child))
        elif type(value) is list:
            for child in value:
                result.extend(walk_keys(child))
        return result

    exposed = forbidden_keys & set(walk_keys(payload))
    if exposed:
        raise old.AuditFailure(
            "continuation adoption outcome firewall exposed keys: "
            + ",".join(sorted(exposed))
        )
    return {
        "identity": copy.deepcopy(held["identity"]),
        "authorization": copy.deepcopy(authorization),
        "builder_identity": copy.deepcopy(builder_identity),
    }


def _old_error_gate(snapshot: Mapping[str, object]) -> dict[str, object]:
    record = snapshot["file_records"].get(OLD_ERROR_SEAL_PATH)
    if record is None or type(record.get("payload")) is not bytes:
        raise old.AuditFailure("immutable old ERROR seal absent from held snapshot")
    identity = copy.deepcopy(record["identity"])
    _strict_equal(
        identity,
        {
            "path": str(OLD_ERROR_SEAL_PATH),
            "size_bytes": OLD_ERROR_SEAL_SIZE,
            "sha256": OLD_ERROR_SEAL_SHA256,
        },
        label="immutable old ERROR seal identity",
    )
    encoded = record["payload"]
    try:
        payload = json.loads(encoded.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise old.AuditFailure("immutable old ERROR seal is malformed") from exc
    if encoded != _canonical_bytes(payload):
        raise old.AuditFailure("immutable old ERROR seal is non-canonical")
    _strict_equal(payload, _expected_old_error_payload(), label="immutable old ERROR reason")
    return {"identity": identity, "payload": payload}


def _mode_correction_contract() -> dict[str, object]:
    return {
        "scope": "active_r4_snapshot_regular_file_mode_predicate_only",
        "old_false_negative_required_all_governed_regular_files_mode_octal": "0444",
        "corrected_role_modes": {
            "scientific_outputs": {
                "names": sorted(SCIENTIFIC_OUTPUT_NAMES),
                "mode_octal": "0664",
            },
            "governance_arm_records": {
                "names": sorted(GOVERNANCE_ARM_NAMES),
                "mode_octal": "0444",
            },
            "root_freeze_start_old_error": {
                "names": sorted(ROOT_FILE_NAMES),
                "mode_octal": "0444",
            },
            "directories": {"count": 5, "mode_octal": "0700"},
        },
        "old_formal_v2_semantic_and_scientific_audit_reused_exactly": True,
        "old_error_seal_replaced_or_rewritten": False,
        "r4_artifact_bytes_rewritten": False,
        "r4_artifact_modes_changed": False,
        "producer_or_detector_rerun": False,
        "outcome_dependent_configuration_or_branching": False,
    }


def _continuation_envelope(
    *,
    result: Mapping[str, object],
    old_auditor_identity: Mapping[str, object],
    old_error_gate: Mapping[str, object],
    authorization_gate: Mapping[str, object],
    snapshot: Mapping[str, object],
) -> dict[str, object]:
    if (
        type(result) is not dict
        or type(result.get("pass")) is not bool
        or result.get("status") not in {"PASS", "FAIL"}
        or (result["status"] == "PASS") is not result["pass"]
    ):
        raise old.AuditFailure("delegated formal-v2 result status contract drift")
    claim = result.get("claim_boundary")
    expected_claim = {
        "detector_birth_source_only_within_this_frozen_carrier": True,
        "whole_slam_superiority": False,
        "confirmatory": False,
        "statistical_significance": False,
    }
    _strict_equal(claim, expected_claim, label="delegated formal-v2 claim boundary")
    return {
        "schema_version": SCHEMA_VERSION,
        "status": result["status"],
        "pass": result["pass"],
        "scientific_role": "post_result_development_exploratory_detector_birth_ablation",
        "continuation_authorization": copy.deepcopy(authorization_gate),
        "immutable_old_error_seal": copy.deepcopy(old_error_gate),
        "frozen_formal_v2_auditor_identity": copy.deepcopy(old_auditor_identity),
        "mode_correction": _mode_correction_contract(),
        "held_r4_and_locked_input_inventory": _snapshot_inventory(snapshot),
        "delegated_formal_v2_result": copy.deepcopy(result),
        "claim_boundary": {
            **expected_claim,
            "old_error_remains_authoritative_for_consumed_old_name": True,
            "this_fresh_continuation_seal_is_additive": True,
            "detector_rerun_or_r4_mutation_authorized": False,
            "vins_authorized_by_this_seal_only_after_contract_pass": bool(result["pass"]),
        },
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--action", choices=("audit",), default="audit")
    parser.add_argument("--source-feature-bag", required=True)
    parser.add_argument("--raw-image-bag", required=True)
    parser.add_argument("--camera-yaml", required=True)
    parser.add_argument("--freeze-json", required=True)
    parser.add_argument("--xfeat-bag", required=True)
    parser.add_argument("--xfeat-manifest", required=True)
    parser.add_argument("--xfeat-diagnostics", required=True)
    parser.add_argument("--xfeat-legacy-manifest", required=True)
    parser.add_argument("--xfeat-work-directory", required=True)
    parser.add_argument("--xfeat-attempt", required=True)
    parser.add_argument("--gftt-bag", required=True)
    parser.add_argument("--gftt-manifest", required=True)
    parser.add_argument("--gftt-diagnostics", required=True)
    parser.add_argument("--gftt-legacy-manifest", required=True)
    parser.add_argument("--gftt-work-directory", required=True)
    parser.add_argument("--gftt-attempt", required=True)
    parser.add_argument("--feature-topic", default=old.FEATURE_TOPIC_DEFAULT)
    parser.add_argument("--image-topic", required=True)
    parser.add_argument("--allow-prefix", action="store_true")
    parser.add_argument("--expected-published-frames", type=old._positive, required=True)
    parser.add_argument("--pre-run-start-receipt", required=True)
    parser.add_argument("--post-run-audit-json", required=True)
    parser.add_argument("--continuation-adoption-json", required=True)
    parser.add_argument("--continuation-seal-json", required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    held_authorization: dict[str, object] | None = None
    held_builder: dict[str, object] | None = None
    held_self: dict[str, object] | None = None
    held_old_auditor: dict[str, object] | None = None
    snapshot: dict[str, object] | None = None
    descriptor: int | None = None
    parent_descriptor: int | None = None
    output_identity: tuple[int, int] | None = None
    parent_identity: tuple[int, int] | None = None
    initial_parent_entries: tuple[str, ...] = ()
    encoded: bytes | None = None
    completion: str | None = None
    exit_code = 2
    try:
        old_error_path = _absolute_canonical(
            Path(args.post_run_audit_json), label="immutable old ERROR seal"
        )
        continuation_path = _absolute_canonical(
            Path(args.continuation_adoption_json), label="continuation authorization"
        )
        output = _absolute_canonical(
            Path(args.continuation_seal_json),
            label="fresh continuation seal",
            strict=False,
        )
        if old_error_path != OLD_ERROR_SEAL_PATH:
            raise old.AuditFailure("old ERROR seal is not the exact immutable r4 path")
        if continuation_path != CONTINUATION_PATH:
            raise old.AuditFailure("continuation authorization path drift")
        if output != CONTINUATION_SEAL_PATH:
            raise old.AuditFailure("fresh continuation seal path drift")
        if old._ACTIVE_FORMAL_SNAPSHOT is not None:
            raise old.AuditFailure("old formal snapshot lifecycle is already occupied")

        common = {
            "freeze_json": Path(args.freeze_json).resolve(strict=True),
            "source_bag": Path(args.source_feature_bag).resolve(strict=True),
            "raw_bag": Path(args.raw_image_bag).resolve(strict=True),
            "camera_yaml": Path(args.camera_yaml).resolve(strict=True),
            "xfeat_bag": Path(args.xfeat_bag).resolve(strict=True),
            "xfeat_manifest": Path(args.xfeat_manifest).resolve(strict=True),
            "xfeat_diagnostics": Path(args.xfeat_diagnostics).resolve(strict=True),
            "xfeat_legacy_manifest": Path(args.xfeat_legacy_manifest).resolve(strict=True),
            "xfeat_work_directory": Path(args.xfeat_work_directory).resolve(strict=True),
            "xfeat_attempt": Path(args.xfeat_attempt).resolve(strict=True),
            "gftt_bag": Path(args.gftt_bag).resolve(strict=True),
            "gftt_manifest": Path(args.gftt_manifest).resolve(strict=True),
            "gftt_diagnostics": Path(args.gftt_diagnostics).resolve(strict=True),
            "gftt_legacy_manifest": Path(args.gftt_legacy_manifest).resolve(strict=True),
            "gftt_work_directory": Path(args.gftt_work_directory).resolve(strict=True),
            "gftt_attempt": Path(args.gftt_attempt).resolve(strict=True),
            "feature_topic": args.feature_topic,
            "image_topic": args.image_topic,
            "allow_prefix": bool(args.allow_prefix),
            "expected_frames": int(args.expected_published_frames),
            "pre_run_start_receipt": Path(args.pre_run_start_receipt).resolve(strict=True),
            "post_run_pair_seal": old_error_path,
        }
        old_auditor_identity = _validate_old_auditor_identity()
        held_old_auditor = _open_held_source(
            path=OLD_AUDITOR_PATH,
            claim=old_auditor_identity,
            required_mode=0o664,
            label="frozen formal-v2 auditor",
            claim_includes_mode=False,
        )
        old_auditor_identity = copy.deepcopy(held_old_auditor["identity"])
        held_authorization = _open_held_continuation(continuation_path)
        raw_authorization = held_authorization["payload"].get(
            "continuation_authorization"
        )
        if type(raw_authorization) is not dict:
            raise old.AuditFailure("continuation authorization object is absent")
        held_self = _open_held_self_source(raw_authorization.get("corrected_auditor"))
        held_self_identity = {
            **held_self["identity"],
            "mode_octal": format(int(held_self["required_mode"]), "04o"),
        }
        authorization_gate = _validate_continuation_authorization(
            held_authorization,
            args=args,
            corrected_auditor_identity=held_self_identity,
        )
        held_builder = _open_held_builder_source(
            authorization_gate["builder_identity"]
        )
        snapshot = _held_corrected_r4_snapshot(
            **{
                key: value
                for key, value in common.items()
                if key not in {"feature_topic", "image_topic", "allow_prefix", "expected_frames", "post_run_pair_seal"}
            },
            old_error_seal=old_error_path,
        )
        old_error_gate = _old_error_gate(snapshot)
        _validate_adoption_snapshot_binding(held_authorization, snapshot)
        _finish_held_continuation(held_authorization)
        _finish_held_builder_source(held_builder)
        _finish_held_self_source(held_self)
        _finish_held_source(held_old_auditor)
        old._finish_held_active_formal_snapshot(snapshot)

        (
            descriptor,
            parent_descriptor,
            output_identity,
            parent_identity,
            initial_parent_entries,
        ) = old._open_reserved_output(output)
        old._ACTIVE_FORMAL_SNAPSHOT = snapshot
        result = old.audit_pair(**common, held_snapshot=snapshot)
        old._finish_held_active_formal_snapshot(snapshot)
        old._late_validate_active_formal_snapshot(snapshot)
        _finish_held_continuation(held_authorization)
        _finish_held_builder_source(held_builder)
        _finish_held_self_source(held_self)
        _finish_held_source(held_old_auditor)
        old._finish_held_active_formal_snapshot(snapshot)
        envelope = _continuation_envelope(
            result=result,
            old_auditor_identity=old_auditor_identity,
            old_error_gate=old_error_gate,
            authorization_gate=authorization_gate,
            snapshot=snapshot,
        )
        encoded = old._publish_reserved_output(
            output=output,
            descriptor=descriptor,
            parent_descriptor=parent_descriptor,
            output_identity=output_identity,
            parent_identity=parent_identity,
            initial_parent_entries=initial_parent_entries,
            payload=envelope,
        )
        for _phase in range(2):
            old._finish_held_active_formal_snapshot(snapshot)
            old._late_validate_active_formal_snapshot(snapshot)
            _finish_held_continuation(held_authorization)
            _finish_held_builder_source(held_builder)
            _finish_held_self_source(held_self)
            _finish_held_source(held_old_auditor)
            old._verify_reserved_output(
                output=output,
                descriptor=descriptor,
                parent_descriptor=parent_descriptor,
                output_identity=output_identity,
                parent_identity=parent_identity,
                initial_parent_entries=initial_parent_entries,
                expected_bytes=encoded,
            )
        completion = _canonical_bytes(
            {"status": envelope["status"], "output": str(output)}
        ).decode().rstrip()
        exit_code = 0 if envelope["pass"] else 1
    except Exception as exc:
        if (
            descriptor is not None
            and parent_descriptor is not None
            and output_identity is not None
            and parent_identity is not None
        ):
            failure = {
                "schema_version": SCHEMA_VERSION,
                "status": "ERROR",
                "pass": False,
                "scientific_role": "post_result_development_exploratory_detector_birth_ablation",
                "error": {"type": type(exc).__name__, "message": str(exc)},
                "claim_boundary": {
                    "contract_pass": False,
                    "fresh_continuation_namespace_consumed_no_retry": True,
                    "detector_rerun_or_r4_mutation_authorized": False,
                },
            }
            try:
                old._publish_reserved_output(
                    output=CONTINUATION_SEAL_PATH,
                    descriptor=descriptor,
                    parent_descriptor=parent_descriptor,
                    output_identity=output_identity,
                    parent_identity=parent_identity,
                    initial_parent_entries=initial_parent_entries,
                    payload=failure,
                )
            except BaseException as write_exc:
                print(
                    f"AUDIT_RECEIPT_WRITE_ERROR:{type(write_exc).__name__}:{write_exc}",
                    file=sys.stderr,
                )
        print(f"AUDIT_ERROR:{type(exc).__name__}:{exc}", file=sys.stderr)
        exit_code = 2
    finally:
        old._ACTIVE_FORMAL_SNAPSHOT = None
        close_errors: list[BaseException] = []
        if snapshot is not None:
            try:
                _close_corrected_snapshot(snapshot)
            except BaseException as exc:
                close_errors.append(exc)
        if held_authorization is not None:
            try:
                _close_held_continuation(held_authorization)
            except BaseException as exc:
                close_errors.append(exc)
        if held_builder is not None:
            try:
                _close_held_builder_source(held_builder)
            except BaseException as exc:
                close_errors.append(exc)
        if held_self is not None:
            try:
                _close_held_self_source(held_self)
            except BaseException as exc:
                close_errors.append(exc)
        if held_old_auditor is not None:
            try:
                _close_held_source(held_old_auditor)
            except BaseException as exc:
                close_errors.append(exc)
        for value in (descriptor, parent_descriptor):
            if value is not None:
                try:
                    os.close(value)
                except BaseException as exc:
                    close_errors.append(exc)
        if close_errors:
            print(
                "AUDIT_CLOSE_ERROR:"
                + ";".join(f"{type(exc).__name__}:{exc}" for exc in close_errors),
                file=sys.stderr,
            )
    if completion is not None:
        print(completion)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
