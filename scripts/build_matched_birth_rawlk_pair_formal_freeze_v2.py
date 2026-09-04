#!/usr/bin/env python3
"""Build the fresh formal900 freeze promoted from the sealed r3 PASS probe.

This builder reads immutable inputs/static code identities plus the sealed r3
adoption record required to authorize the exact 16/32-to-900/1800 transition.
R3 outcomes are verified only inside the auditor's sanitized PASS gate and are
never exposed to candidate construction.  It never imports a future r4
manifest, feature bag, diagnostics stream, attempt, or launcher
receipt.  Two canonical command-contract files and the canonical freeze are
published with O_EXCL and are never removed or replaced.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import secrets
import stat
from typing import Mapping, Sequence

from scripts import audit_matched_birth_rawlk_pair_formal_v2 as audit
from scripts import matched_birth_rawlk_core_v1 as core
from scripts import run_matched_birth_arm_once_v1 as launcher


SCHEMA_VERSION = "aqua-fe-matched-birth-pair-formal-freeze-builder-v2"
MODE_CONTRACTS = {
    "formal900": {"allow_prefix": False, "expected_frames": 900},
}


class FreezeBuildError(RuntimeError):
    pass


def _owned_regular_identity(path: Path, expected: tuple[int, int], *, label: str) -> os.stat_result:
    observed = os.lstat(path)
    if (
        not stat.S_ISREG(observed.st_mode)
        or int(observed.st_nlink) != 1
        or path.is_symlink()
        or (int(observed.st_dev), int(observed.st_ino)) != expected
    ):
        raise FreezeBuildError(f"{label} ownership/regular-file contract failed")
    return observed


def _create_probe_file(
    path: Path,
    payload: bytes,
    owned: dict[Path, tuple[int, int] | None],
) -> tuple[int, int]:
    owned[path] = None
    descriptor = os.open(
        str(path),
        os.O_WRONLY
        | os.O_CREAT
        | os.O_EXCL
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_CLOEXEC", 0),
        0o600,
    )
    try:
        observed = os.fstat(descriptor)
        identity = (int(observed.st_dev), int(observed.st_ino))
        owned[path] = identity
        os.fchmod(descriptor, 0o600)
        observed = os.fstat(descriptor)
        if (
            not stat.S_ISREG(observed.st_mode)
            or stat.S_IMODE(observed.st_mode) != 0o600
            or int(observed.st_nlink) != 1
        ):
            raise FreezeBuildError("capability probe regular-file creation failed")
        audit._write_all(descriptor, payload)
        os.fsync(descriptor)
        after = os.fstat(descriptor)
        if (
            (int(after.st_dev), int(after.st_ino)) != identity
            or int(after.st_size) != len(payload)
        ):
            raise FreezeBuildError("capability probe regular-file write drift")
        return identity
    finally:
        os.close(descriptor)


def _read_owned_probe_file(
    path: Path, expected: tuple[int, int], *, expected_payload: bytes, label: str
) -> None:
    _owned_regular_identity(path, expected, label=label)
    descriptor = os.open(
        str(path),
        os.O_RDONLY
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_CLOEXEC", 0),
    )
    try:
        opened = os.fstat(descriptor)
        if (int(opened.st_dev), int(opened.st_ino)) != expected:
            raise FreezeBuildError(f"{label} changed before O_NOFOLLOW reopen")
        chunks = []
        while True:
            block = os.read(descriptor, 64 * 1024)
            if not block:
                break
            chunks.append(block)
        if b"".join(chunks) != expected_payload:
            raise FreezeBuildError(f"{label} byte verification failed")
        after = os.fstat(descriptor)
        if (int(after.st_dev), int(after.st_ino)) != expected:
            raise FreezeBuildError(f"{label} changed during O_NOFOLLOW read")
    finally:
        os.close(descriptor)


def _probe_artifact_publication_capabilities(
    governed_paths: Sequence[Path],
) -> dict[str, object]:
    """Exercise the exact publication primitives in a disposable private dir.

    The directory is outside the governed names and exists only for this
    pre-publication capability check.  Cleanup is inode-checked within its
    mode-0700, same-UID non-adversarial trust boundary.
    """

    audit._artifact_filesystem_contract(governed_paths)
    root = audit.ARTIFACT_NAMESPACE_ROOT
    stale = sorted(
        entry.name
        for entry in root.iterdir()
        if entry.name.startswith(".publication-capability-")
    )
    if stale:
        raise FreezeBuildError(
            f"stale capability probe evidence blocks publication: {stale}"
        )
    probe = root / f".publication-capability-{secrets.token_hex(16)}"
    if os.path.lexists(probe):
        raise FreezeBuildError("capability probe path unexpectedly exists")
    os.mkdir(probe, 0o700)
    probe_identity: tuple[int, int] | None = None
    owned: dict[Path, tuple[int, int] | None] = {}
    primary = probe / "o_excl_mode_and_bytes.json"
    rename_source = probe / "rename_source.bin"
    rename_destination = probe / "rename_destination.bin"
    primary_payload = b'{"capability":"o_excl_fchmod_fsync_nofollow"}\n'
    source_payload = b"rename-source\n"
    destination_payload = b"rename-existing-destination\n"
    failure: BaseException | None = None
    try:
        probe_stat = os.lstat(probe)
        probe_identity = (int(probe_stat.st_dev), int(probe_stat.st_ino))
        os.chmod(probe, 0o700)
        probe_stat = os.lstat(probe)
        if (
            (int(probe_stat.st_dev), int(probe_stat.st_ino)) != probe_identity
            or not stat.S_ISDIR(probe_stat.st_mode)
            or stat.S_IMODE(probe_stat.st_mode) != 0o700
            or int(probe_stat.st_uid) != int(os.getuid())
            or probe.is_symlink()
        ):
            raise FreezeBuildError("capability probe private directory contract failed")
        owned[primary] = None
        descriptor = os.open(
            str(primary),
            os.O_WRONLY
            | os.O_CREAT
            | os.O_EXCL
            | getattr(os, "O_NOFOLLOW", 0)
            | getattr(os, "O_CLOEXEC", 0),
            0o444,
        )
        try:
            opened = os.fstat(descriptor)
            owned[primary] = (int(opened.st_dev), int(opened.st_ino))
            os.fchmod(descriptor, 0o444)
            opened = os.fstat(descriptor)
            if (
                not stat.S_ISREG(opened.st_mode)
                or stat.S_IMODE(opened.st_mode) != 0o444
                or int(opened.st_nlink) != 1
            ):
                raise FreezeBuildError("capability probe fchmod(0444) failed")
            audit._write_all(descriptor, primary_payload)
            os.fsync(descriptor)
            after = os.fstat(descriptor)
            if (
                (int(after.st_dev), int(after.st_ino)) != owned[primary]
                or stat.S_IMODE(after.st_mode) != 0o444
                or int(after.st_size) != len(primary_payload)
            ):
                raise FreezeBuildError("capability probe held file postcondition failed")
        finally:
            os.close(descriptor)
        visible = _owned_regular_identity(
            primary, owned[primary], label="capability probe published file"
        )
        if stat.S_IMODE(visible.st_mode) != 0o444:
            raise FreezeBuildError("capability probe visible mode is not 0444")
        _read_owned_probe_file(
            primary,
            owned[primary],
            expected_payload=primary_payload,
            label="capability probe published file",
        )

        parent_descriptor = os.open(
            str(probe),
            os.O_RDONLY
            | getattr(os, "O_DIRECTORY", 0)
            | getattr(os, "O_NOFOLLOW", 0)
            | getattr(os, "O_CLOEXEC", 0),
        )
        try:
            os.fsync(parent_descriptor)
        finally:
            os.close(parent_descriptor)

        _create_probe_file(rename_source, source_payload, owned)
        _create_probe_file(rename_destination, destination_payload, owned)
        try:
            core._rename_noreplace(rename_source, rename_destination)
        except FileExistsError:
            pass
        else:
            raise FreezeBuildError("renameat2 NOREPLACE failed to preserve EEXIST")
        _read_owned_probe_file(
            rename_source,
            owned[rename_source],
            expected_payload=source_payload,
            label="capability probe rename source after EEXIST",
        )
        _read_owned_probe_file(
            rename_destination,
            owned[rename_destination],
            expected_payload=destination_payload,
            label="capability probe rename destination after EEXIST",
        )
        _owned_regular_identity(
            rename_destination,
            owned[rename_destination],
            label="capability probe owned destination before unlink",
        )
        os.unlink(rename_destination)
        del owned[rename_destination]
        core._rename_noreplace(rename_source, rename_destination)
        source_identity = owned.pop(rename_source)
        owned[rename_destination] = source_identity
        if os.path.lexists(rename_source):
            raise FreezeBuildError("renameat2 source remained after successful move")
        _read_owned_probe_file(
            rename_destination,
            source_identity,
            expected_payload=source_payload,
            label="capability probe destination after successful move",
        )
    except BaseException as exc:
        failure = exc

    cleanup_failure: BaseException | None = None
    try:
        for path, identity in sorted(owned.items(), key=lambda item: str(item[0])):
            if os.path.lexists(path):
                if identity is None:
                    raise FreezeBuildError(
                        "unidentified capability probe file retained as failure evidence"
                    )
                else:
                    _owned_regular_identity(
                        path, identity, label="capability probe cleanup"
                    )
                os.unlink(path)
        remaining = os.listdir(probe)
        if remaining:
            raise FreezeBuildError(
                f"capability probe private directory has foreign entries: {remaining}"
            )
        current_probe = os.lstat(probe)
        if (
            probe_identity is None
            or
            (int(current_probe.st_dev), int(current_probe.st_ino)) != probe_identity
            or not stat.S_ISDIR(current_probe.st_mode)
            or stat.S_IMODE(current_probe.st_mode) != 0o700
        ):
            raise FreezeBuildError("capability probe directory changed before cleanup")
        os.rmdir(probe)
        if os.path.lexists(probe):
            raise FreezeBuildError("capability probe cleanup did not remove private dir")
        stale_after = sorted(
            entry.name
            for entry in root.iterdir()
            if entry.name.startswith(".publication-capability-")
        )
        if stale_after:
            raise FreezeBuildError(
                f"capability probe cleanup left hidden evidence: {stale_after}"
            )
    except BaseException as exc:
        cleanup_failure = exc

    if cleanup_failure is not None:
        raise FreezeBuildError(
            f"capability probe cleanup failed: {type(cleanup_failure).__name__}:"
            f"{cleanup_failure}"
        ) from failure
    if failure is not None:
        raise failure
    return audit._expected_artifact_capability_attestation()


def _canonical_future_path(value: Path, *, label: str) -> Path:
    raw = os.fspath(value)
    if not Path(raw).is_absolute() or os.path.normpath(raw) != raw:
        raise FreezeBuildError(f"{label} must be a canonical absolute path")
    path = Path(raw)
    if os.path.lexists(path):
        raise FreezeBuildError(f"{label} already exists: {path}")
    parent = path.parent.resolve(strict=True)
    if str(parent) != str(path.parent):
        raise FreezeBuildError(f"{label} parent must be canonical: {path.parent}")
    observed = os.lstat(parent)
    if not stat.S_ISDIR(observed.st_mode):
        raise FreezeBuildError(f"{label} parent is not a directory")
    return path


def _write_exclusive(path: Path, payload: Mapping[str, object]) -> dict[str, object]:
    encoded = audit._canonical_bytes(payload)
    parent_before = os.lstat(path.parent)
    descriptor = os.open(
        str(path),
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
        0o444,
    )
    created_identity: tuple[int, int] | None = None
    try:
        os.fchmod(descriptor, 0o444)
        opened = os.fstat(descriptor)
        if (
            not stat.S_ISREG(opened.st_mode)
            or stat.S_IMODE(opened.st_mode) != 0o444
            or int(opened.st_nlink) != 1
        ):
            raise FreezeBuildError("O_EXCL artifact descriptor contract failed")
        created_identity = (int(opened.st_dev), int(opened.st_ino))
        audit._write_all(descriptor, encoded)
        os.fsync(descriptor)
        after = os.fstat(descriptor)
        if (
            (int(after.st_dev), int(after.st_ino)) != created_identity
            or int(after.st_size) != len(encoded)
            or int(after.st_nlink) != 1
            or stat.S_IMODE(after.st_mode) != 0o444
        ):
            raise FreezeBuildError("O_EXCL artifact write postcondition failed")
    finally:
        os.close(descriptor)
    visible = os.lstat(path)
    if (
        created_identity is None
        or (int(visible.st_dev), int(visible.st_ino)) != created_identity
        or not stat.S_ISREG(visible.st_mode)
        or int(visible.st_nlink) != 1
        or stat.S_IMODE(visible.st_mode) != 0o444
        or int(visible.st_size) != len(encoded)
        or path.is_symlink()
    ):
        raise FreezeBuildError("published artifact is not single-link regular")
    read_descriptor = os.open(
        str(path), os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    )
    try:
        read_stat = os.fstat(read_descriptor)
        if (int(read_stat.st_dev), int(read_stat.st_ino)) != created_identity:
            raise FreezeBuildError("published artifact changed before byte verification")
        observed = bytearray()
        while True:
            block = os.read(read_descriptor, 64 * 1024)
            if not block:
                break
            observed.extend(block)
        if bytes(observed) != encoded:
            raise FreezeBuildError("published artifact bytes changed")
    finally:
        os.close(read_descriptor)
    parent_after = os.lstat(path.parent)
    if (int(parent_after.st_dev), int(parent_after.st_ino)) != (
        int(parent_before.st_dev), int(parent_before.st_ino)
    ):
        raise FreezeBuildError("published artifact parent changed")
    parent_descriptor = os.open(
        str(path.parent),
        os.O_RDONLY
        | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_NOFOLLOW", 0),
    )
    try:
        os.fsync(parent_descriptor)
    finally:
        os.close(parent_descriptor)
    return audit._file_identity(path, label=f"built {path.name}")


def _absent_alias_key(path: Path) -> tuple[int, int, str]:
    parent = os.lstat(path.parent)
    if not stat.S_ISDIR(parent.st_mode):
        raise FreezeBuildError(f"future artifact parent is not a directory: {path.parent}")
    return int(parent.st_dev), int(parent.st_ino), path.name


def _assert_absent_paths(paths: Sequence[Path], *, label: str) -> None:
    keys: dict[tuple[int, int, str], Path] = {}
    for path in paths:
        if os.path.lexists(path):
            raise FreezeBuildError(f"{label} path appeared before commit: {path}")
        key = _absent_alias_key(path)
        if key in keys:
            raise FreezeBuildError(
                f"{label} absent path aliases {keys[key]} by parent inode/name: {path}"
            )
        keys[key] = path


def _governed_future_paths(kwargs: Mapping[str, object]) -> list[Path]:
    paths = [
        Path(kwargs["freeze_json"]),
        Path(kwargs["pre_run_start_receipt"]),
        Path(kwargs["post_run_pair_seal"]),
        *(
            Path(path)
            for arm_paths in kwargs["arm_paths"].values()
            for path in arm_paths.values()
        ),
        *(Path(path) for path in kwargs["command_contract_paths"].values()),
        *(Path(path) for path in kwargs["launcher_start_receipts"].values()),
        *(Path(path) for path in kwargs["launcher_rc_receipts"].values()),
    ]
    if len(paths) != 21 or len({str(path) for path in paths}) != 21:
        raise FreezeBuildError("governed r4 path set is not exact 21")
    return paths


def _validate_exact_fresh_r4_namespace(kwargs: Mapping[str, object]) -> None:
    """Require the exact empty r4 directory skeleton and all canonical names."""

    root = audit.ARTIFACT_NAMESPACE_ROOT
    if root.expanduser().absolute() != root or root.resolve(strict=True) != root:
        raise FreezeBuildError("formal900 r4 root is not canonical/symlink-free")
    root_stat = os.lstat(root)
    if (
        not stat.S_ISDIR(root_stat.st_mode)
        or stat.S_IMODE(root_stat.st_mode) != 0o700
        or int(root_stat.st_uid) != int(os.getuid())
        or set(os.listdir(root)) != set(audit.R4_ARM_DIRECTORIES.values())
    ):
        raise FreezeBuildError("formal900 r4 root is not the exact fresh skeleton")
    exact_root_paths = {
        "freeze_json": root / audit.R4_ROOT_ARTIFACT_NAMES["freeze"],
        "pre_run_start_receipt": (
            root / audit.R4_ROOT_ARTIFACT_NAMES["pre_run_start_receipt"]
        ),
        "post_run_pair_seal": (
            root / audit.R4_ROOT_ARTIFACT_NAMES["post_run_pair_seal"]
        ),
    }
    for key, expected in exact_root_paths.items():
        if Path(kwargs[key]) != expected:
            raise FreezeBuildError(f"formal900 exact root path mismatch: {key}")
    artifact_names = {
        "feature_bag": "features.bag",
        "manifest_json": "export_manifest.json",
        "diagnostics_csv": "raw_diagnostics.csv",
        "legacy_primitive_manifest": "legacy_primitive_manifest.json",
        "private_work_directory": "private_work",
        "attempt_json": "producer_attempt.json",
    }
    for arm_id, arm_name in audit.R4_ARM_DIRECTORIES.items():
        arm_root = root / arm_name
        arm_stat = os.lstat(arm_root)
        if (
            not stat.S_ISDIR(arm_stat.st_mode)
            or stat.S_IMODE(arm_stat.st_mode) != 0o700
            or int(arm_stat.st_uid) != int(os.getuid())
            or os.listdir(arm_root)
        ):
            raise FreezeBuildError(f"formal900 {arm_name} is not fresh mode-0700")
        for role, name in artifact_names.items():
            if Path(kwargs["arm_paths"][arm_id][role]) != arm_root / name:
                raise FreezeBuildError(
                    f"formal900 {arm_id} exact artifact path mismatch: {role}"
                )
        if Path(kwargs["command_contract_paths"][arm_id]) != arm_root / "command_contract.json":
            raise FreezeBuildError(f"formal900 {arm_id} command path mismatch")
        if Path(kwargs["launcher_start_receipts"][arm_id]) != arm_root / "launcher_start_receipt.json":
            raise FreezeBuildError(f"formal900 {arm_id} start receipt path mismatch")
        if Path(kwargs["launcher_rc_receipts"][arm_id]) != arm_root / "launcher_rc_receipt.json":
            raise FreezeBuildError(f"formal900 {arm_id} RC receipt path mismatch")


def _canonical_arm_paths(values: Mapping[str, Path], *, arm_id: str) -> dict[str, Path]:
    if set(values) != set(audit.FREEZE_PATH_KEYS):
        raise FreezeBuildError(f"{arm_id} path role set mismatch")
    result = {
        role: _canonical_future_path(Path(path), label=f"{arm_id}.{role}")
        for role, path in values.items()
    }
    if len(set(result.values())) != len(result):
        raise FreezeBuildError(f"{arm_id} output paths alias")
    parents = {path.parent for path in result.values()}
    if len(parents) != 1:
        raise FreezeBuildError(f"{arm_id} outputs must share one run parent")
    return result


def _attempt_payload(
    *,
    arm_id: str,
    paths: Mapping[str, Path],
    locked_inputs: Mapping[str, object],
    allow_prefix: bool,
) -> dict[str, object]:
    return {
        "schema_version": "aqua-fe-detector-birth-rawlk-attempt-v1",
        "status": "ATTEMPT_CONSUMED_PROCESS_ENTERED_PRECHECK",
        "attempt_count": 1,
        "process_start_count": 1,
        "no_retry": True,
        "arm_id": arm_id,
        "prefix_nonformal": bool(allow_prefix),
        "requested_inputs": {
            role: locked_inputs[role]["path"]
            for role in ("source_feature_bag", "raw_image_bag", "camera_yaml")
        },
        "reserved_outputs": {
            role: str(paths[role])
            for role in (
                "feature_bag", "manifest_json", "diagnostics_csv",
                "legacy_primitive_manifest", "private_work_directory",
            )
        },
        "producer": {
            "matched_core_requested": str(Path(core.__file__).resolve(strict=True)),
            "wrapper_requested": str(
                audit.EXPECTED_WRAPPERS[arm_id].resolve(strict=True)
            ),
        },
    }


def _producer_values(
    *,
    paths: Mapping[str, Path],
    locked_inputs: Mapping[str, object],
    feature_topic: str,
    image_topic: str,
    allow_prefix: bool,
    expected_frames: int,
) -> dict[str, str]:
    values = {
        "--source-feature-bag": locked_inputs["source_feature_bag"]["path"],
        "--raw-image-bag": locked_inputs["raw_image_bag"]["path"],
        "--camera-yaml": locked_inputs["camera_yaml"]["path"],
        "--output-bag": str(paths["feature_bag"]),
        "--image-topic": image_topic,
        "--feature-topic": feature_topic,
        "--manifest-json": str(paths["manifest_json"]),
        "--diagnostics-csv": str(paths["diagnostics_csv"]),
        "--legacy-manifest-json": str(paths["legacy_primitive_manifest"]),
        "--work-directory": str(paths["private_work_directory"]),
        "--attempt-json": str(paths["attempt_json"]),
    }
    if allow_prefix:
        values[launcher.OPTIONAL_LIMIT] = str(expected_frames)
    return values


def build_payload(
    *,
    mode: str,
    freeze_json: Path,
    source_bag: Path,
    raw_bag: Path,
    camera_yaml: Path,
    arm_paths: Mapping[str, Mapping[str, Path]],
    command_contract_paths: Mapping[str, Path],
    launcher_start_receipts: Mapping[str, Path],
    launcher_rc_receipts: Mapping[str, Path],
    pre_run_start_receipt: Path,
    post_run_pair_seal: Path,
    feature_topic: str,
    image_topic: str,
) -> tuple[dict[str, object], dict[str, dict[str, object]]]:
    if audit._canonical_bytes(dict(os.environ)) != audit._canonical_bytes(
        launcher.FROZEN_ENVIRONMENT
    ):
        raise FreezeBuildError("builder process environment is not the exact frozen environment")
    if mode not in MODE_CONTRACTS:
        raise FreezeBuildError(f"unsupported matched freeze mode: {mode}")
    if mode != "formal900":
        raise FreezeBuildError("formal v2 builder accepts exactly formal900")
    if feature_topic != "/feature_tracker/feature":
        raise FreezeBuildError("feature topic differs from frozen consumer contract")
    if image_topic != "/camera/image_raw":
        raise FreezeBuildError("image topic differs from frozen A02 contract")
    allow_prefix = bool(MODE_CONTRACTS[mode]["allow_prefix"])
    expected_frames = int(MODE_CONTRACTS[mode]["expected_frames"])
    _validate_exact_fresh_r4_namespace(
        {
            "freeze_json": freeze_json,
            "pre_run_start_receipt": pre_run_start_receipt,
            "post_run_pair_seal": post_run_pair_seal,
            "arm_paths": arm_paths,
            "command_contract_paths": command_contract_paths,
            "launcher_start_receipts": launcher_start_receipts,
            "launcher_rc_receipts": launcher_rc_receipts,
        }
    )
    freeze_json = _canonical_future_path(freeze_json, label="freeze JSON")
    canonical_arms = {
        arm: _canonical_arm_paths(arm_paths[arm], arm_id=arm)
        for arm in (audit.XFEAT_ARM, audit.GFTT_ARM)
    }
    audit_paths = {
        "pre_run_start_receipt": _canonical_future_path(
            pre_run_start_receipt, label="pre-run start receipt"
        ),
        "post_run_pair_seal": _canonical_future_path(
            post_run_pair_seal, label="post-run pair seal"
        ),
    }
    command_paths = {
        arm: _canonical_future_path(
            command_contract_paths[arm], label=f"{arm} command contract"
        )
        for arm in audit.EXPECTED_ARMS
    }
    launcher_starts = {
        arm: _canonical_future_path(
            launcher_start_receipts[arm], label=f"{arm} launcher start receipt"
        )
        for arm in audit.EXPECTED_ARMS
    }
    launcher_rcs = {
        arm: _canonical_future_path(
            launcher_rc_receipts[arm], label=f"{arm} launcher RC receipt"
        )
        for arm in audit.EXPECTED_ARMS
    }
    reserved = [freeze_json, *audit_paths.values()]
    reserved.extend(path for paths in canonical_arms.values() for path in paths.values())
    reserved.extend(command_paths.values())
    reserved.extend(launcher_starts.values())
    reserved.extend(launcher_rcs.values())
    if len(reserved) != len(set(reserved)):
        raise FreezeBuildError("freeze/arm/command/receipt paths alias")
    absent_keys: dict[tuple[int, int, str], Path] = {}
    for path in [*reserved, launcher.PYCACHE_PREFIX]:
        key = _absent_alias_key(path)
        if key in absent_keys:
            raise FreezeBuildError(
                "freeze/arm/command/receipt/pycache path aliases by "
                f"parent inode/name: {absent_keys[key]} and {path}"
            )
        absent_keys[key] = path
    if os.path.lexists(launcher.PYCACHE_PREFIX):
        raise FreezeBuildError("shared frozen pycache prefix is not absent")
    adoption_gate = audit._validate_formal900_adoption()
    filesystem_envelope = audit._artifact_filesystem_envelope(reserved)

    source_bag = audit._regular_path(source_bag, label="source feature bag")
    raw_bag = audit._regular_path(raw_bag, label="raw image bag")
    camera_yaml = audit._regular_path(camera_yaml, label="camera YAML")
    locked_inputs = {
        "source_feature_bag": audit._file_identity(source_bag, label="source bag"),
        "raw_image_bag": audit._file_identity(raw_bag, label="raw bag"),
        "camera_yaml": audit._file_identity(camera_yaml, label="camera YAML"),
    }
    input_paths = {Path(item["path"]) for item in locked_inputs.values()}
    if len(input_paths) != 3:
        raise FreezeBuildError("locked input paths/inodes are not distinct")
    input_inodes = {
        (int(os.lstat(path).st_dev), int(os.lstat(path).st_ino))
        for path in input_paths
    }
    if len(input_inodes) != 3:
        raise FreezeBuildError("locked input inode identities are not distinct")
    if input_paths & set(reserved):
        raise FreezeBuildError("governed future artifact aliases a locked input")
    audit._validate_formal900_mode_and_inputs(
        adoption_gate=adoption_gate,
        allow_prefix=allow_prefix,
        expected_frames=expected_frames,
        locked_inputs=locked_inputs,
    )

    runtime = audit._audit_runtime_observation()
    common = core.common_contract(strict_runtime=True)
    expected_pycache = str(launcher.PYCACHE_PREFIX)
    if (
        type(runtime.get("core_runtime")) is not dict
        or runtime.get("pycache_prefix") != expected_pycache
        or runtime["core_runtime"].get("pycache_prefix") != expected_pycache
    ):
        raise FreezeBuildError("audit runtime pycache prefix drift")
    if (
        type(common.get("runtime")) is not dict
        or common["runtime"].get("pycache_prefix") != expected_pycache
    ):
        raise FreezeBuildError("common runtime pycache prefix drift")
    if audit._canonical_bytes(runtime["core_runtime"]) != audit._canonical_bytes(
        common["runtime"]
    ):
        raise FreezeBuildError("audit/common core runtime cross-binding drift")
    common_rows, reconstruction = audit._reconstruct_common_diagnostics(
        source_bag=source_bag,
        raw_bag=raw_bag,
        feature_topic=feature_topic,
        image_topic=image_topic,
        allow_prefix=allow_prefix,
        expected_frames=expected_frames,
    )
    _matrix, _distortion, camera_model = core.primitive.load_camera_model(camera_yaml)
    nonfeature = core._call_trusted_rosbag_scoped(
        core.primitive._nonfeature_digest,
        source_bag,
        feature_topic,
        reconstruction["cutoff_feature_record_stamp_ns"],
    )

    contracts: dict[str, dict[str, object]] = {}
    arms: dict[str, object] = {}
    for arm_id in (audit.XFEAT_ARM, audit.GFTT_ARM):
        paths = canonical_arms[arm_id]
        attempt = _attempt_payload(
            arm_id=arm_id,
            paths=paths,
            locked_inputs=locked_inputs,
            allow_prefix=allow_prefix,
        )
        values = _producer_values(
            paths=paths,
            locked_inputs=locked_inputs,
            feature_topic=feature_topic,
            image_topic=image_topic,
            allow_prefix=allow_prefix,
            expected_frames=expected_frames,
        )
        contracts[arm_id] = launcher.build_command_contract(
            arm_id,
            values,
            start_receipt=launcher_starts[arm_id],
            rc_receipt=launcher_rcs[arm_id],
        )
        path_strings = {role: str(path) for role, path in paths.items()}
        template = audit._symbolic_manifest_expected(
            arm_id=arm_id,
            paths=path_strings,
            expected_attempt=attempt,
            locked_inputs=locked_inputs,
            expected_common=common,
            feature_topic=feature_topic,
            image_topic=image_topic,
            allow_prefix=allow_prefix,
            expected_frames=expected_frames,
            common_rows=common_rows,
            reconstruction=reconstruction,
            camera_normalization_model=camera_model,
            nonfeature_stream=nonfeature,
        )
        dynamic_paths = sorted(audit._template_dynamic_paths(template))
        mandatory = audit._mandatory_dynamic_rules(
            arm_id,
            allow_prefix=allow_prefix,
            expected_frames=expected_frames,
        )
        if dynamic_paths != sorted(mandatory):
            raise FreezeBuildError(f"{arm_id} symbolic dynamic rule set drift")
        arms[arm_id] = {
            "paths": path_strings,
            "pre_run_required_absent": True,
            "manifest_template": template,
            "manifest_template_sha256": core._canonical_sha256(template),
            "dynamic_scalar_paths": dynamic_paths,
            "attempt": attempt,
        }

    template_differences = set(
        audit._pair_scalar_differences(
            arms[audit.XFEAT_ARM]["manifest_template"],
            arms[audit.GFTT_ARM]["manifest_template"],
        )
    )
    allowed = sorted(
        template_differences
        | set(arms[audit.XFEAT_ARM]["dynamic_scalar_paths"])
        | set(arms[audit.GFTT_ARM]["dynamic_scalar_paths"])
    )
    command_identities = {
        arm: {
            "path": str(command_paths[arm]),
            "size_bytes": len(audit._canonical_bytes(contracts[arm])),
            "sha256": hashlib.sha256(
                audit._canonical_bytes(contracts[arm])
            ).hexdigest(),
        }
        for arm in audit.EXPECTED_ARMS
    }
    audit_arms = {
        arm: {
            "working_directory": str(audit.WORKSPACE_ROOT),
            "environment": dict(launcher.FROZEN_ENVIRONMENT),
            "command_contract": command_identities[arm],
            "launcher_argv": [
                "/usr/bin/python3.8", "-B", "-m",
                "scripts.run_matched_birth_arm_once_v1",
                "--start-receipt", str(launcher_starts[arm]),
                "--rc-receipt", str(launcher_rcs[arm]),
                "--command-contract-json", str(command_paths[arm]),
            ],
            "launcher_start_receipt": str(launcher_starts[arm]),
            "launcher_rc_receipt": str(launcher_rcs[arm]),
        }
        for arm in audit.EXPECTED_ARMS
    }
    audit_env = dict(launcher.FROZEN_ENVIRONMENT)
    audit_path_map = {role: str(path) for role, path in audit_paths.items()}
    authoritative_commands = {
        "check_start": {
            "working_directory": str(audit.WORKSPACE_ROOT),
            "environment": audit_env,
            "argv": audit._auditor_argv(
                action="check-start", freeze_json=freeze_json,
                source_bag=source_bag, raw_bag=raw_bag,
                camera_yaml=camera_yaml, arm_paths=canonical_arms,
                audit_paths=audit_paths, feature_topic=feature_topic,
                image_topic=image_topic, allow_prefix=allow_prefix,
                expected_frames=expected_frames,
            ),
        },
        "arms": audit_arms,
        "post_run_audit": {
            "working_directory": str(audit.WORKSPACE_ROOT),
            "environment": audit_env,
            "argv": audit._auditor_argv(
                action="audit", freeze_json=freeze_json,
                source_bag=source_bag, raw_bag=raw_bag,
                camera_yaml=camera_yaml, arm_paths=canonical_arms,
                audit_paths=audit_paths, feature_topic=feature_topic,
                image_topic=image_topic, allow_prefix=allow_prefix,
                expected_frames=expected_frames,
            ),
        },
    }
    if audit._canonical_bytes(audit._audit_runtime_observation()) != audit._canonical_bytes(
        runtime
    ):
        raise FreezeBuildError("audit runtime drift after locked-bag reconstruction")
    freeze = {
        "schema_version": audit.FREEZE_SCHEMA_VERSION,
        "status": "FROZEN",
        "scientific_role": (
            "post_result_development_exploratory_detector_birth_ablation"
        ),
        "auditor_identity": audit._audit_code_closure()["pair_auditor"],
        "audit_code_closure": audit._audit_code_closure(),
        "audit_runtime": runtime,
        "fixed_semantics": audit._fixed_semantics(
            feature_topic=feature_topic,
            image_topic=image_topic,
            allow_prefix=allow_prefix,
            expected_frames=expected_frames,
        ),
        "locked_inputs": locked_inputs,
        "audit_paths": audit_path_map,
        "expected_common_contract": common,
        "expected_common_contract_sha256": core._canonical_sha256(common),
        "arms": arms,
        "allowed_pair_scalar_differences": allowed,
        "required_pair_scalar_differences": sorted(
            audit.MANDATORY_PAIR_DIFFERENCES
        ),
        "freeze_builder_identity": audit._file_identity(
            Path(__file__), label="freeze builder"
        ),
        "authoritative_commands": authoritative_commands,
        "launcher_receipt_contract": {
            "command_contract_schema": launcher.COMMAND_CONTRACT_SCHEMA,
            "start_receipt_schema": launcher.START_RECEIPT_SCHEMA,
            "rc_receipt_schema": launcher.RC_RECEIPT_SCHEMA,
            "launcher_identity": audit._file_identity(
                Path(launcher.__file__), label="sealed launcher"
            ),
            "supervision": copy.deepcopy(launcher.EXPECTED_SUPERVISION),
        },
        "publication_contract": {
            "commit_marker_role": "freeze",
            "freeze_published_last": True,
            "orphan_contracts_non_authoritative": True,
            "result_outcomes_read": False,
            "producer_started": False,
        },
        "infrastructure_incident": adoption_gate["infrastructure_incident"],
        "formal900_adoption": adoption_gate["identity"],
        "artifact_filesystem_contract": filesystem_envelope,
    }
    audit._validate_formal900_transition(
        freeze,
        adoption_gate=adoption_gate,
        allow_prefix=allow_prefix,
        expected_frames=expected_frames,
        candidate_command_contracts=contracts,
    )
    return freeze, contracts


def build_and_write(**kwargs) -> dict[str, object]:
    _validate_exact_fresh_r4_namespace(kwargs)
    freeze, contracts = build_payload(**kwargs)
    governed_paths = _governed_future_paths(kwargs)
    _assert_absent_paths(
        [*governed_paths, launcher.PYCACHE_PREFIX],
        label="pre-capability-probe",
    )
    capability = _probe_artifact_publication_capabilities(governed_paths)
    expected_capability = freeze["artifact_filesystem_contract"][
        "builder_prepublication_capability_probe"
    ]
    if audit._canonical_bytes(capability) != audit._canonical_bytes(expected_capability):
        raise FreezeBuildError("artifact capability probe attestation drift")
    _assert_absent_paths(
        [*governed_paths, launcher.PYCACHE_PREFIX],
        label="post-capability-probe",
    )
    mode = MODE_CONTRACTS[kwargs["mode"]]
    audit._validate_freeze(
        freeze,
        freeze_json=Path(kwargs["freeze_json"]),
        runtime=audit._audit_runtime_observation(),
        source_bag=Path(kwargs["source_bag"]).resolve(strict=True),
        raw_bag=Path(kwargs["raw_bag"]).resolve(strict=True),
        camera_yaml=Path(kwargs["camera_yaml"]).resolve(strict=True),
        arm_paths=kwargs["arm_paths"],
        audit_paths={
            "pre_run_start_receipt": kwargs["pre_run_start_receipt"],
            "post_run_pair_seal": kwargs["post_run_pair_seal"],
        },
        feature_topic=kwargs["feature_topic"],
        image_topic=kwargs["image_topic"],
        allow_prefix=bool(mode["allow_prefix"]),
        expected_frames=int(mode["expected_frames"]),
        in_memory_command_contracts=contracts,
    )
    contract_paths = kwargs["command_contract_paths"]
    noncontract_future_paths = [
        Path(kwargs["freeze_json"]),
        Path(kwargs["pre_run_start_receipt"]),
        Path(kwargs["post_run_pair_seal"]),
        *(Path(path) for paths in kwargs["arm_paths"].values() for path in paths.values()),
        *(Path(path) for path in kwargs["launcher_start_receipts"].values()),
        *(Path(path) for path in kwargs["launcher_rc_receipts"].values()),
        launcher.PYCACHE_PREFIX,
    ]
    _assert_absent_paths(
        [*noncontract_future_paths, *(Path(path) for path in contract_paths.values())],
        label="pre-publication",
    )
    # XFeat contract, then GFTT contract, then the freeze commit marker.  If a
    # filesystem failure leaves either contract orphaned, no freeze exists and
    # check-start has no authoritative protocol to accept.
    identities = {}
    for arm in (audit.XFEAT_ARM, audit.GFTT_ARM):
        identities[arm] = _write_exclusive(
            Path(contract_paths[arm]), contracts[arm]
        )
    for arm in audit.EXPECTED_ARMS:
        if identities[arm] != freeze["authoritative_commands"]["arms"][arm]["command_contract"]:
            raise FreezeBuildError(f"{arm} written command identity drift")
    # The static reconstruction can be long.  Recheck every not-yet-published
    # governed name immediately before publishing the sole commit marker.
    _assert_absent_paths(noncontract_future_paths, label="pre-freeze-commit")
    for arm in audit.EXPECTED_ARMS:
        live = audit._file_identity(
            Path(contract_paths[arm]), label=f"pre-commit {arm} command contract"
        )
        if live != identities[arm]:
            raise FreezeBuildError(f"{arm} command changed before freeze commit")
    live_adoption = audit._validate_formal900_adoption()
    if audit._canonical_bytes(live_adoption["identity"]) != audit._canonical_bytes(
        freeze["formal900_adoption"]
    ):
        raise FreezeBuildError("formal900 adoption drift before freeze commit")
    if audit._canonical_bytes(live_adoption["static_projection"]) != audit._canonical_bytes(
        audit._static_scientific_projection(
            freeze, command_contracts=contracts
        )
    ):
        raise FreezeBuildError("formal900 static projection drift before freeze commit")
    audit._validate_formal900_transition(
        freeze,
        adoption_gate=live_adoption,
        allow_prefix=False,
        expected_frames=900,
        candidate_command_contracts=contracts,
    )
    if audit._canonical_bytes(audit._audit_runtime_observation()) != audit._canonical_bytes(
        freeze["audit_runtime"]
    ):
        raise FreezeBuildError("formal900 runtime drift before freeze commit")
    live_filesystem = audit._artifact_filesystem_envelope(governed_paths)
    if audit._canonical_bytes(live_filesystem) != audit._canonical_bytes(
        freeze["artifact_filesystem_contract"]
    ):
        raise FreezeBuildError("artifact filesystem drift before freeze commit")
    freeze_identity = _write_exclusive(Path(kwargs["freeze_json"]), freeze)
    return {
        "schema_version": SCHEMA_VERSION,
        "status": "PASS_OUTCOME_BLIND_FREEZE_BUILT",
        "freeze": freeze_identity,
        "command_contracts": identities,
        "candidate_r4_outcomes_read": False,
        "r3_pass_gate_read_only_inside_sanitized_adoption_validator": True,
        "r3_outcomes_exposed_to_formal_builder": False,
        "r3_outcomes_used_for_candidate_projection": False,
        "producer_started": False,
    }


def _add_arm_paths(parser: argparse.ArgumentParser, prefix: str) -> None:
    for role in audit.FREEZE_PATH_KEYS:
        parser.add_argument(f"--{prefix}-{role.replace('_', '-')}", required=True)
    parser.add_argument(f"--{prefix}-command-contract", required=True)
    parser.add_argument(f"--{prefix}-launcher-start-receipt", required=True)
    parser.add_argument(f"--{prefix}-launcher-rc-receipt", required=True)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument("--mode", choices=tuple(MODE_CONTRACTS), required=True)
    parser.add_argument("--freeze-json", required=True)
    parser.add_argument("--source-feature-bag", required=True)
    parser.add_argument("--raw-image-bag", required=True)
    parser.add_argument("--camera-yaml", required=True)
    parser.add_argument("--feature-topic", default=audit.FEATURE_TOPIC_DEFAULT)
    parser.add_argument("--image-topic", required=True)
    parser.add_argument("--pre-run-start-receipt", required=True)
    parser.add_argument("--post-run-pair-seal", required=True)
    _add_arm_paths(parser, "xfeat")
    _add_arm_paths(parser, "gftt")
    return parser


def _arm_values(args: argparse.Namespace, prefix: str) -> dict[str, Path]:
    return {
        role: Path(getattr(args, f"{prefix}_{role}"))
        for role in audit.FREEZE_PATH_KEYS
    }


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result = build_and_write(
            mode=args.mode,
            freeze_json=Path(args.freeze_json),
            source_bag=Path(args.source_feature_bag),
            raw_bag=Path(args.raw_image_bag),
            camera_yaml=Path(args.camera_yaml),
            arm_paths={
                audit.XFEAT_ARM: _arm_values(args, "xfeat"),
                audit.GFTT_ARM: _arm_values(args, "gftt"),
            },
            command_contract_paths={
                audit.XFEAT_ARM: Path(args.xfeat_command_contract),
                audit.GFTT_ARM: Path(args.gftt_command_contract),
            },
            launcher_start_receipts={
                audit.XFEAT_ARM: Path(args.xfeat_launcher_start_receipt),
                audit.GFTT_ARM: Path(args.gftt_launcher_start_receipt),
            },
            launcher_rc_receipts={
                audit.XFEAT_ARM: Path(args.xfeat_launcher_rc_receipt),
                audit.GFTT_ARM: Path(args.gftt_launcher_rc_receipt),
            },
            pre_run_start_receipt=Path(args.pre_run_start_receipt),
            post_run_pair_seal=Path(args.post_run_pair_seal),
            feature_topic=args.feature_topic,
            image_topic=args.image_topic,
        )
    except Exception as exc:
        print(f"FREEZE_BUILD_ERROR:{type(exc).__name__}:{exc}", file=os.sys.stderr)
        return 2
    print(audit._canonical_bytes(result).decode("utf-8").rstrip())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
