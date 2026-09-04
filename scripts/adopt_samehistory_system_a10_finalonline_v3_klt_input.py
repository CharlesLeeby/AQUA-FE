#!/usr/bin/env python3
"""Byte-preserving adoption of the sealed A10 v2 KLT frontend artifacts.

This utility deliberately has a narrow responsibility.  It validates pinned
regular-file identities, verifies the recorded v2 terminal/artifact/execution
disposition, and copies three artifacts plus a pre-sealed static manifest into
an already-created supervisor output directory.  It does not inspect ROS
graphs, bags, CSV semantics, or camera semantics; those checks belong to the
v3 supervisor.

The v2 source attempt is *not* a PASS: its child returned zero and its artifact
contract passed, but its execution-integrity contract failed with
POSTFLIGHT_PROCESS_PRESENT.  The static adoption manifest must preserve that
distinction.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import sys
from typing import Any, Dict, Iterable, Mapping, MutableMapping, Sequence, Tuple


MANIFEST_SCHEMA = "aqua-fe-a10-samehistory-klt-input-adoption-manifest-v1"
ADOPTION_DISPOSITION = "SEALED_BYTE_PRESERVING_INPUT_ONLY"
SOURCE_FAILURE_REASON = "POSTFLIGHT_PROCESS_PRESENT"

CONTROL_FILES = frozenset({"process_start_claim.json", "supervisor_process.log"})
TARGET_NAMES = frozenset(
    {
        "features.bag",
        "frontend_metrics.csv",
        "aqualoc_archaeo10_pinhole.yaml",
        "adoption_manifest.json",
    }
)
HEX64 = re.compile(r"[0-9a-f]{64}\Z")
COPY_CHUNK_BYTES = 4 * 1024 * 1024
FORBIDDEN_MANIFEST_DYNAMIC_KEYS = frozenset(
    {
        "created_at",
        "created_at_local",
        "generated_at",
        "generated_at_local",
        "timestamp",
        "timestamp_ns",
        "mtime",
        "mtime_ns",
        "ctime",
        "ctime_ns",
        "inode",
        "device",
        "dev",
    }
)


class AdoptionError(RuntimeError):
    """A fail-closed adoption-contract error."""


@dataclass(frozen=True)
class IdentitySpec:
    label: str
    path: Path
    sha256: str
    size_bytes: int

    def manifest_identity(self) -> Dict[str, Any]:
        return {
            "path": str(self.path),
            "sha256": self.sha256,
            "size_bytes": self.size_bytes,
        }


@dataclass(frozen=True)
class OpenIdentity:
    device: int
    inode: int
    mode: int
    nlink: int
    size_bytes: int
    mtime_ns: int
    ctime_ns: int


def nonnegative_int(value: str) -> int:
    try:
        result = int(value, 10)
    except ValueError as error:
        raise argparse.ArgumentTypeError("must be a base-10 integer") from error
    if result < 0:
        raise argparse.ArgumentTypeError("must be non-negative")
    return result


def pinned_sha256(value: str) -> str:
    if HEX64.fullmatch(value) is None:
        raise argparse.ArgumentTypeError("must be exactly 64 lowercase hex digits")
    return value


def absolute_path(value: str) -> Path:
    if "\x00" in value:
        raise argparse.ArgumentTypeError("NUL is forbidden in paths")
    path = Path(value)
    if not path.is_absolute():
        raise argparse.ArgumentTypeError("must be an absolute path")
    if os.path.normpath(value) != value:
        raise argparse.ArgumentTypeError("must be a normalized absolute path")
    return path


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(
        description="Adopt the one sealed A10 v2 KLT payload into a v3 output tree."
    )
    result.add_argument("--output-dir", required=True, type=absolute_path)

    for prefix in ("features", "metrics", "camera", "manifest"):
        result.add_argument(f"--{prefix}-source", required=True, type=absolute_path)
        result.add_argument(f"--{prefix}-sha256", required=True, type=pinned_sha256)
        result.add_argument(f"--{prefix}-size", required=True, type=nonnegative_int)

    for prefix in ("v2-claim", "v2-receipt", "v2-log", "v2-lock"):
        result.add_argument(f"--{prefix}", required=True, type=absolute_path)
        result.add_argument(f"--{prefix}-sha256", required=True, type=pinned_sha256)
        result.add_argument(f"--{prefix}-size", required=True, type=nonnegative_int)
    return result


def _open_identity(st: os.stat_result) -> OpenIdentity:
    return OpenIdentity(
        device=int(st.st_dev),
        inode=int(st.st_ino),
        mode=int(st.st_mode),
        nlink=int(st.st_nlink),
        size_bytes=int(st.st_size),
        mtime_ns=int(st.st_mtime_ns),
        ctime_ns=int(st.st_ctime_ns),
    )


def _same_open_identity(left: OpenIdentity, right: OpenIdentity) -> bool:
    return left == right


def _canonical_regular_path(path: Path, label: str) -> None:
    try:
        resolved = path.resolve(strict=True)
    except (OSError, RuntimeError) as error:
        raise AdoptionError(f"{label}: source path cannot be resolved: {error}") from error
    if resolved != path:
        raise AdoptionError(f"{label}: symlinked or non-canonical path is forbidden")


def _open_pinned_source(spec: IdentitySpec) -> Tuple[int, OpenIdentity]:
    _canonical_regular_path(spec.path, spec.label)
    try:
        before = os.lstat(spec.path)
    except OSError as error:
        raise AdoptionError(f"{spec.label}: lstat failed: {error}") from error
    if not stat.S_ISREG(before.st_mode):
        raise AdoptionError(f"{spec.label}: source is not a regular file")
    if before.st_nlink != 1:
        raise AdoptionError(f"{spec.label}: hardlinked source is forbidden")

    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(spec.path, flags)
    except OSError as error:
        raise AdoptionError(f"{spec.label}: secure open failed: {error}") from error
    try:
        opened = os.fstat(fd)
        identity = _open_identity(opened)
        if not stat.S_ISREG(opened.st_mode):
            raise AdoptionError(f"{spec.label}: opened source is not regular")
        if opened.st_nlink != 1:
            raise AdoptionError(f"{spec.label}: opened source is hardlinked")
        if (before.st_dev, before.st_ino) != (opened.st_dev, opened.st_ino):
            raise AdoptionError(f"{spec.label}: source changed between lstat and open")
        if opened.st_size != spec.size_bytes:
            raise AdoptionError(
                f"{spec.label}: size mismatch: expected={spec.size_bytes} "
                f"observed={opened.st_size}"
            )
        return fd, identity
    except BaseException:
        os.close(fd)
        raise


def _finish_source_read(fd: int, before: OpenIdentity, spec: IdentitySpec) -> None:
    after = _open_identity(os.fstat(fd))
    if not _same_open_identity(before, after):
        raise AdoptionError(f"{spec.label}: source metadata changed while reading")


def _read_and_hash(fd: int, *, collect: bool) -> Tuple[str, int, bytes]:
    digest = hashlib.sha256()
    total = 0
    chunks = [] if collect else None
    while True:
        block = os.read(fd, COPY_CHUNK_BYTES)
        if not block:
            break
        digest.update(block)
        total += len(block)
        if chunks is not None:
            chunks.append(block)
    return digest.hexdigest(), total, b"".join(chunks or ())


def verify_pinned_file(spec: IdentitySpec, *, collect: bool = False) -> bytes:
    fd, before = _open_pinned_source(spec)
    try:
        observed_sha256, observed_size, payload = _read_and_hash(fd, collect=collect)
        _finish_source_read(fd, before, spec)
    finally:
        os.close(fd)
    if observed_size != spec.size_bytes:
        raise AdoptionError(
            f"{spec.label}: streamed size mismatch: expected={spec.size_bytes} "
            f"observed={observed_size}"
        )
    if observed_sha256 != spec.sha256:
        raise AdoptionError(
            f"{spec.label}: SHA-256 mismatch: expected={spec.sha256} "
            f"observed={observed_sha256}"
        )
    return payload


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"non-finite JSON constant is forbidden: {value}")


def parse_json_object(payload: bytes, label: str) -> Mapping[str, Any]:
    try:
        value = json.loads(payload.decode("utf-8"), parse_constant=_reject_json_constant)
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
        raise AdoptionError(f"{label}: invalid strict UTF-8 JSON: {error}") from error
    if not isinstance(value, Mapping):
        raise AdoptionError(f"{label}: JSON root must be an object")
    return value


def _require_mapping(value: Any, context: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise AdoptionError(f"{context}: expected object")
    return value


def validate_v2_receipt(receipt: Mapping[str, Any]) -> None:
    terminal = _require_mapping(receipt.get("terminal_process"), "v2 receipt terminal_process")
    artifact = _require_mapping(receipt.get("artifact_contract"), "v2 receipt artifact_contract")
    execution = _require_mapping(
        receipt.get("execution_integrity"), "v2 receipt execution_integrity"
    )

    required = {
        "receipt.status": (receipt.get("status"), "TERMINAL_PROCESS_RC0"),
        "receipt.overall_disposition": (
            receipt.get("overall_disposition"),
            "EXECUTION_INTEGRITY_FAILED",
        ),
        "terminal.status": (terminal.get("status"), "TERMINAL_PROCESS_RC0"),
        "terminal.raw_return_code": (terminal.get("raw_return_code"), 0),
        "terminal.child_started": (terminal.get("child_started"), True),
        "terminal.timed_out": (terminal.get("timed_out"), False),
        "terminal.popen_invocation_count": (terminal.get("popen_invocation_count"), 1),
        "artifact.status": (artifact.get("status"), "PASS"),
        "execution.status": (execution.get("status"), "FAIL"),
        "execution.supervisor_error": (
            execution.get("supervisor_error"),
            SOURCE_FAILURE_REASON,
        ),
    }
    failures = [
        f"{name}: expected={expected!r} observed={observed!r}"
        for name, (observed, expected) in required.items()
        if type(observed) is not type(expected) or observed != expected
    ]
    if artifact.get("issues") != []:
        failures.append(
            f"artifact.issues: expected=[] observed={artifact.get('issues')!r}"
        )
    if failures:
        raise AdoptionError("v2 receipt disposition mismatch: " + "; ".join(failures))


def _validate_manifest_identity(
    value: Any, expected: IdentitySpec, context: str
) -> None:
    record = _require_mapping(value, context)
    required = expected.manifest_identity()
    failures = [
        f"{key}: expected={wanted!r} observed={record.get(key)!r}"
        for key, wanted in required.items()
        if type(record.get(key)) is not type(wanted) or record.get(key) != wanted
    ]
    if failures:
        raise AdoptionError(f"{context}: identity mismatch: " + "; ".join(failures))


def _walk_manifest_keys(value: Any, path: str = "$") -> Iterable[Tuple[str, str]]:
    if isinstance(value, Mapping):
        for key, child in value.items():
            if not isinstance(key, str):
                raise AdoptionError(f"manifest key at {path} is not text")
            child_path = f"{path}.{key}"
            yield key, child_path
            yield from _walk_manifest_keys(child, child_path)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from _walk_manifest_keys(child, f"{path}[{index}]")


def validate_static_manifest(
    manifest: Mapping[str, Any],
    copies: Mapping[str, Tuple[IdentitySpec, str]],
    evidence: Mapping[str, IdentitySpec],
) -> None:
    if manifest.get("schema_version") != MANIFEST_SCHEMA:
        raise AdoptionError(
            "manifest schema mismatch: "
            f"expected={MANIFEST_SCHEMA!r} observed={manifest.get('schema_version')!r}"
        )
    if manifest.get("adoption_disposition") != ADOPTION_DISPOSITION:
        raise AdoptionError(
            "manifest adoption_disposition must be " + ADOPTION_DISPOSITION
        )

    source_attempt = _require_mapping(
        manifest.get("source_attempt"), "manifest source_attempt"
    )
    required_source_disposition = {
        "terminal_process_status": "TERMINAL_PROCESS_RC0",
        "raw_return_code": 0,
        "artifact_contract_status": "PASS",
        "execution_integrity_status": "FAIL",
        "execution_failure_reason": SOURCE_FAILURE_REASON,
        "overall_disposition": "EXECUTION_INTEGRITY_FAILED",
        "overall_pass": False,
        "must_not_be_described_as_pass": True,
    }
    for key, expected in required_source_disposition.items():
        observed = source_attempt.get(key)
        if type(observed) is not type(expected) or observed != expected:
            raise AdoptionError(
                f"manifest source_attempt.{key}: expected={expected!r} "
                f"observed={observed!r}"
            )

    evidence_records = _require_mapping(
        manifest.get("source_attempt_evidence"),
        "manifest source_attempt_evidence",
    )
    for label, spec in evidence.items():
        _validate_manifest_identity(
            evidence_records.get(label), spec, f"manifest source_attempt_evidence.{label}"
        )

    adopted_records = _require_mapping(
        manifest.get("adopted_files"), "manifest adopted_files"
    )
    for label, (spec, output_name) in copies.items():
        record = _require_mapping(
            adopted_records.get(label), f"manifest adopted_files.{label}"
        )
        if record.get("output_name") != output_name:
            raise AdoptionError(
                f"manifest adopted_files.{label}.output_name mismatch"
            )
        # The frozen project manifest uses a flat, readily inspectable record.
        # A nested form is also accepted so the copier remains generally useful;
        # mixing the two representations is rejected as ambiguous.
        nested_keys = {"source", "expected_output"}
        flat_keys = {
            "source_path",
            "sha256",
            "size_bytes",
            "expected_output_sha256",
            "expected_output_size_bytes",
        }
        has_nested = bool(set(record) & nested_keys)
        has_flat = bool(set(record) & flat_keys)
        if has_nested == has_flat:
            raise AdoptionError(
                f"manifest adopted_files.{label}: require exactly one of flat or nested identity form"
            )
        if has_nested:
            if not nested_keys <= set(record):
                raise AdoptionError(
                    f"manifest adopted_files.{label}: incomplete nested identity form"
                )
            _validate_manifest_identity(
                record.get("source"), spec, f"manifest adopted_files.{label}.source"
            )
            expected_output = _require_mapping(
                record.get("expected_output"),
                f"manifest adopted_files.{label}.expected_output",
            )
            observed_output = {
                "sha256": expected_output.get("sha256"),
                "size_bytes": expected_output.get("size_bytes"),
            }
        else:
            if not flat_keys <= set(record):
                raise AdoptionError(
                    f"manifest adopted_files.{label}: incomplete flat identity form"
                )
            flat_source = {
                "path": record.get("source_path"),
                "sha256": record.get("sha256"),
                "size_bytes": record.get("size_bytes"),
            }
            _validate_manifest_identity(
                flat_source, spec, f"manifest adopted_files.{label}.flat_source"
            )
            observed_output = {
                "sha256": record.get("expected_output_sha256"),
                "size_bytes": record.get("expected_output_size_bytes"),
            }
        wanted_output = {"sha256": spec.sha256, "size_bytes": spec.size_bytes}
        for key, expected in wanted_output.items():
            observed = observed_output.get(key)
            if type(observed) is not type(expected) or observed != expected:
                raise AdoptionError(
                    f"manifest adopted_files.{label}.expected_output.{key}: "
                    f"expected={expected!r} observed={observed!r}"
                )

    forbidden = [
        path
        for key, path in _walk_manifest_keys(manifest)
        if key in FORBIDDEN_MANIFEST_DYNAMIC_KEYS
    ]
    if forbidden:
        raise AdoptionError(
            "manifest contains dynamic filesystem/time fields: " + ", ".join(forbidden)
        )


def _open_output_directory(path: Path) -> int:
    try:
        resolved = path.resolve(strict=True)
    except (OSError, RuntimeError) as error:
        raise AdoptionError(f"output directory cannot be resolved: {error}") from error
    if resolved != path:
        raise AdoptionError("output directory uses a symlinked or non-canonical path")
    try:
        before = os.lstat(path)
    except OSError as error:
        raise AdoptionError(f"output directory lstat failed: {error}") from error
    if not stat.S_ISDIR(before.st_mode):
        raise AdoptionError("output path is not a directory")
    flags = os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(path, flags)
    except OSError as error:
        raise AdoptionError(f"secure output-directory open failed: {error}") from error
    try:
        opened = os.fstat(fd)
        if not stat.S_ISDIR(opened.st_mode):
            raise AdoptionError("opened output path is not a directory")
        if (before.st_dev, before.st_ino) != (opened.st_dev, opened.st_ino):
            raise AdoptionError("output directory changed between lstat and open")
        return fd
    except BaseException:
        os.close(fd)
        raise


def _validate_control_file(dir_fd: int, name: str) -> None:
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(name, flags, dir_fd=dir_fd)
    except OSError as error:
        raise AdoptionError(f"output control file {name!r} cannot be opened: {error}") from error
    try:
        observed = os.fstat(fd)
        if not stat.S_ISREG(observed.st_mode):
            raise AdoptionError(f"output control entry {name!r} is not regular")
        if observed.st_nlink != 1:
            raise AdoptionError(f"output control entry {name!r} is hardlinked")
    finally:
        os.close(fd)


def validate_output_tree(dir_fd: int) -> None:
    try:
        entries = set(os.listdir(dir_fd))
    except OSError as error:
        raise AdoptionError(f"cannot enumerate output directory: {error}") from error
    unexpected = sorted(entries - CONTROL_FILES)
    if unexpected:
        raise AdoptionError(
            "output directory contains entries other than supervisor controls: "
            + ", ".join(repr(item) for item in unexpected)
        )
    for name in sorted(entries):
        _validate_control_file(dir_fd, name)
    existing_targets = sorted(entries & TARGET_NAMES)
    if existing_targets:
        raise AdoptionError(
            "adoption targets already exist: " + ", ".join(existing_targets)
        )


def _write_all(fd: int, block: bytes) -> None:
    view = memoryview(block)
    while view:
        written = os.write(fd, view)
        if written <= 0:
            raise AdoptionError("destination write made no progress")
        view = view[written:]


def _hash_output_at(dir_fd: int, name: str) -> Tuple[str, int, OpenIdentity]:
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(name, flags, dir_fd=dir_fd)
    try:
        before = _open_identity(os.fstat(fd))
        if not stat.S_ISREG(before.mode) or before.nlink != 1:
            raise AdoptionError(f"destination {name!r} is not an unlinked regular file")
        digest, size_bytes, _ = _read_and_hash(fd, collect=False)
        after = _open_identity(os.fstat(fd))
        if before != after:
            raise AdoptionError(f"destination {name!r} changed while verifying")
        return digest, size_bytes, after
    finally:
        os.close(fd)


def copy_pinned_file(
    spec: IdentitySpec,
    output_name: str,
    dir_fd: int,
    created: MutableMapping[str, Tuple[int, int]],
) -> Mapping[str, Any]:
    if output_name not in TARGET_NAMES or "/" in output_name or output_name in {".", ".."}:
        raise AdoptionError(f"invalid fixed output name: {output_name!r}")

    source_fd, source_before = _open_pinned_source(spec)
    destination_fd = -1
    try:
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        flags |= getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
        try:
            destination_fd = os.open(output_name, flags, 0o400, dir_fd=dir_fd)
        except OSError as error:
            raise AdoptionError(
                f"{spec.label}: exclusive destination create failed: {error}"
            ) from error

        destination_initial = os.fstat(destination_fd)
        if not stat.S_ISREG(destination_initial.st_mode):
            raise AdoptionError(f"{spec.label}: destination is not regular")
        if destination_initial.st_nlink != 1:
            raise AdoptionError(f"{spec.label}: destination is unexpectedly hardlinked")
        created[output_name] = (
            int(destination_initial.st_dev),
            int(destination_initial.st_ino),
        )
        if (destination_initial.st_dev, destination_initial.st_ino) == (
            source_before.device,
            source_before.inode,
        ):
            raise AdoptionError(f"{spec.label}: destination aliases source inode")

        digest = hashlib.sha256()
        total = 0
        while True:
            block = os.read(source_fd, COPY_CHUNK_BYTES)
            if not block:
                break
            digest.update(block)
            total += len(block)
            _write_all(destination_fd, block)

        _finish_source_read(source_fd, source_before, spec)
        observed_sha256 = digest.hexdigest()
        if total != spec.size_bytes or observed_sha256 != spec.sha256:
            raise AdoptionError(
                f"{spec.label}: source changed or mismatched during copy: "
                f"expected=({spec.sha256},{spec.size_bytes}) "
                f"observed=({observed_sha256},{total})"
            )

        os.fchmod(destination_fd, 0o444)
        os.fsync(destination_fd)
        destination_after = os.fstat(destination_fd)
        if not stat.S_ISREG(destination_after.st_mode) or destination_after.st_nlink != 1:
            raise AdoptionError(f"{spec.label}: destination identity invalid after fsync")
        if destination_after.st_size != spec.size_bytes:
            raise AdoptionError(f"{spec.label}: destination size mismatch after fsync")
    finally:
        if destination_fd >= 0:
            os.close(destination_fd)
        os.close(source_fd)

    # Persist the directory entry, then independently reread the destination.
    os.fsync(dir_fd)
    copied_sha256, copied_size, copied_identity = _hash_output_at(dir_fd, output_name)
    if copied_sha256 != spec.sha256 or copied_size != spec.size_bytes:
        raise AdoptionError(
            f"{spec.label}: copied output identity mismatch: "
            f"expected=({spec.sha256},{spec.size_bytes}) "
            f"observed=({copied_sha256},{copied_size})"
        )
    return {
        "path": output_name,
        "sha256": copied_sha256,
        "size_bytes": copied_size,
        "regular_file": True,
        "symlink": False,
        "hardlink": False,
        "device": copied_identity.device,
        "inode": copied_identity.inode,
    }


def cleanup_created(
    dir_fd: int, created: Mapping[str, Tuple[int, int]]
) -> Sequence[str]:
    errors = []
    for name, expected in reversed(tuple(created.items())):
        try:
            observed = os.stat(name, dir_fd=dir_fd, follow_symlinks=False)
        except FileNotFoundError:
            continue
        except OSError as error:
            errors.append(f"{name}:stat:{error}")
            continue
        if (observed.st_dev, observed.st_ino) != expected:
            errors.append(f"{name}:identity-changed-refused-unlink")
            continue
        try:
            os.unlink(name, dir_fd=dir_fd)
        except OSError as error:
            errors.append(f"{name}:unlink:{error}")
    try:
        os.fsync(dir_fd)
    except OSError as error:
        errors.append(f"directory:fsync:{error}")
    return errors


def _spec(arguments: argparse.Namespace, label: str, prefix: str) -> IdentitySpec:
    attr = prefix.replace("-", "_")
    path_attr = attr if prefix.startswith("v2-") else f"{attr}_source"
    return IdentitySpec(
        label=label,
        path=getattr(arguments, path_attr),
        sha256=getattr(arguments, f"{attr}_sha256"),
        size_bytes=getattr(arguments, f"{attr}_size"),
    )


def run(arguments: argparse.Namespace) -> Mapping[str, Any]:
    copies: Dict[str, Tuple[IdentitySpec, str]] = {
        "features_bag": (
            _spec(arguments, "sealed features bag", "features"),
            "features.bag",
        ),
        "frontend_metrics": (
            _spec(arguments, "sealed frontend metrics", "metrics"),
            "frontend_metrics.csv",
        ),
        "camera_yaml": (
            _spec(arguments, "sealed camera YAML", "camera"),
            "aqualoc_archaeo10_pinhole.yaml",
        ),
    }
    manifest_spec = _spec(arguments, "sealed static adoption manifest", "manifest")
    evidence: Dict[str, IdentitySpec] = {
        "claim": _spec(arguments, "v2 process-start claim", "v2-claim"),
        "receipt": _spec(arguments, "v2 terminal receipt", "v2-receipt"),
        "process_log": _spec(arguments, "v2 supervisor process log", "v2-log"),
        "execution_lock": _spec(arguments, "v2 execution lock", "v2-lock"),
    }

    all_specs = [
        *(spec for spec, _ in copies.values()),
        manifest_spec,
        *evidence.values(),
    ]
    paths = [str(spec.path) for spec in all_specs]
    if len(set(paths)) != len(paths):
        raise AdoptionError("all source/evidence paths must be distinct")

    # Complete preflight before creating the first destination.
    for spec, _ in copies.values():
        verify_pinned_file(spec)
    evidence_payloads = {
        label: verify_pinned_file(spec, collect=(label == "receipt"))
        for label, spec in evidence.items()
    }
    receipt = parse_json_object(evidence_payloads["receipt"], "v2 receipt")
    validate_v2_receipt(receipt)
    manifest_payload = verify_pinned_file(manifest_spec, collect=True)
    manifest = parse_json_object(manifest_payload, "static adoption manifest")
    validate_static_manifest(manifest, copies, evidence)

    dir_fd = _open_output_directory(arguments.output_dir)
    created: Dict[str, Tuple[int, int]] = {}
    outputs: Dict[str, Mapping[str, Any]] = {}
    try:
        validate_output_tree(dir_fd)
        try:
            for label, (spec, output_name) in copies.items():
                outputs[label] = copy_pinned_file(spec, output_name, dir_fd, created)
            outputs["adoption_manifest"] = copy_pinned_file(
                manifest_spec, "adoption_manifest.json", dir_fd, created
            )
            os.fsync(dir_fd)
        except BaseException as error:
            cleanup_errors = cleanup_created(dir_fd, created)
            if cleanup_errors:
                raise AdoptionError(
                    f"adoption failed ({error}); cleanup also failed: "
                    + "; ".join(cleanup_errors)
                ) from error
            raise
    finally:
        os.close(dir_fd)

    return {
        "status": "ADOPTION_COPY_RC0",
        "adoption_disposition": ADOPTION_DISPOSITION,
        "source_attempt_overall_pass": False,
        "source_attempt_execution_integrity": "FAIL",
        "source_attempt_execution_failure_reason": SOURCE_FAILURE_REASON,
        "outputs": outputs,
    }


def main(argv: Sequence[str] | None = None) -> int:
    arguments = parser().parse_args(argv)
    try:
        result = run(arguments)
    except (AdoptionError, OSError) as error:
        print(f"ADOPTION_ERROR:{error}", file=sys.stderr)
        return 2
    print(json.dumps(result, sort_keys=True, separators=(",", ":"), allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
