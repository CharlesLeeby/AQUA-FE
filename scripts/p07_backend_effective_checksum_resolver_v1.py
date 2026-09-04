#!/usr/bin/env python3
"""Resolve the frozen P07 backend dataset checksum overlay fail closed.

This module is deliberately additive.  It never rewrites the historical
dataset checksum manifest and never interprets a Hugging Face Xet identifier
as a content SHA-256.  Call :func:`load_correction_lock` once, then pass the
returned validated lock to :func:`effective_content_record` or
:func:`effective_content_sha256` together with the exact 41-row base manifest.

Loading is outcome-blind and local-only: the correction builder's canonical
validator verifies the lock self-hash and all bound source files, while live
API checks and large-bag hashing are disabled.  Resolution reconstructs the
frozen base-manifest bytes, so changed values, missing/extra paths, and an
attempt to substitute an LFS digest for a historical Xet row all fail closed.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import stat
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

try:
    from scripts import build_p07_backend_hf_checksum_semantics_correction_v1 as correction
except ModuleNotFoundError:  # direct ``python scripts/...`` import
    import build_p07_backend_hf_checksum_semantics_correction_v1 as correction  # type: ignore


ROOT = Path(__file__).resolve().parents[1]
CORRECTION_LOCK_RELATIVE = correction.OUTPUT_RELATIVE
RESOLVER_SCHEMA_VERSION = "isj-p07-backend-effective-checksum-resolver-v1"

_HEX64 = re.compile(r"[0-9a-f]{64}")
_MAX_LOCK_BYTES = 8 * 1024 * 1024
_VALIDATION_SENTINEL = object()


class EffectiveChecksumResolutionError(RuntimeError):
    """The effective checksum authority could not be resolved safely."""


def _stable_file_identity(path: Path) -> Dict[str, Any]:
    """Hash one direct Python source and reject an across-read mutation."""

    try:
        before_lstat = path.lstat()
        before = path.stat()
        if stat.S_ISLNK(before_lstat.st_mode) or not stat.S_ISREG(before.st_mode):
            raise EffectiveChecksumResolutionError(
                "loaded correction runtime source is not a direct regular file"
            )
        content = path.read_bytes()
        after_lstat = path.lstat()
        after = path.stat()
    except OSError as error:
        raise EffectiveChecksumResolutionError(
            "cannot read loaded correction runtime source"
        ) from error
    identity_before = (
        before_lstat.st_dev,
        before_lstat.st_ino,
        before_lstat.st_mode,
        before.st_dev,
        before.st_ino,
        before.st_mode,
        before.st_size,
        before.st_mtime_ns,
        before.st_ctime_ns,
    )
    identity_after = (
        after_lstat.st_dev,
        after_lstat.st_ino,
        after_lstat.st_mode,
        after.st_dev,
        after.st_ino,
        after.st_mode,
        after.st_size,
        after.st_mtime_ns,
        after.st_ctime_ns,
    )
    if identity_before != identity_after or len(content) != after.st_size:
        raise EffectiveChecksumResolutionError(
            "loaded correction runtime source changed while read"
        )
    return {
        "sha256": hashlib.sha256(content).hexdigest(),
        "size_bytes": len(content),
    }


_RUNTIME_MODULE_SOURCES: Tuple[Tuple[str, Any], ...] = (
    (correction.BUILDER_RELATIVE, correction),
    (correction.FORMAL_IO_RELATIVE, correction.formal_io),
    (correction.REPLAY_COMMON_RELATIVE, correction.replay_common),
)


def _module_source_path(module: Any) -> Path:
    raw = getattr(module, "__file__", None)
    if not isinstance(raw, str) or not raw.endswith(".py"):
        raise EffectiveChecksumResolutionError(
            "correction runtime module does not expose its Python source"
        )
    return Path(raw).absolute()


# These import-time identities close the gap between the Python code currently
# executing in memory and the source records validated from disk by the lock.
_IMPORTED_RUNTIME_IDENTITIES = {
    relative: _stable_file_identity(_module_source_path(module))
    for relative, module in _RUNTIME_MODULE_SOURCES
}


class ValidatedCorrectionLock(dict):
    """A validated lock that never returns its authoritative nested objects."""

    def __init__(
        self,
        payload: Mapping[str, Any],
        *,
        token: object,
        validated_self_hash: str,
    ) -> None:
        if token is not _VALIDATION_SENTINEL:
            raise EffectiveChecksumResolutionError(
                "validated correction locks must be created by load_correction_lock"
            )
        detached = json.loads(json.dumps(payload, ensure_ascii=True))
        super().__init__(detached)
        self._validated_self_hash = validated_self_hash
        self._validation_token = token

    @staticmethod
    def _detached_value(value: Any) -> Any:
        return json.loads(json.dumps(value, ensure_ascii=True))

    def __getitem__(self, key: str) -> Any:
        return self._detached_value(dict.__getitem__(self, key))

    def get(self, key: str, default: Any = None) -> Any:
        if not dict.__contains__(self, key):
            return self._detached_value(default)
        return self[key]

    def items(self):
        return tuple((key, self._detached_value(value)) for key, value in dict.items(self))

    def values(self):
        return tuple(self._detached_value(value) for value in dict.values(self))

    def copy(self) -> Dict[str, Any]:
        return {
            key: self._detached_value(value) for key, value in dict.items(self)
        }

    def __setitem__(self, key: str, value: Any) -> None:
        dict.__setitem__(self, key, self._detached_value(value))

    def setdefault(self, key: str, default: Any = None) -> Any:
        if not dict.__contains__(self, key):
            self[key] = default
        return self[key]

    def update(self, *args: Any, **kwargs: Any) -> None:
        incoming = dict(*args, **kwargs)
        for key, value in incoming.items():
            self[key] = value


def _json_object_without_duplicate_keys(
    pairs: Sequence[Tuple[str, Any]],
) -> Dict[str, Any]:
    result: Dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise EffectiveChecksumResolutionError(
                "correction lock JSON contains a duplicate object key"
            )
        result[key] = value
    return result


def _decode_lock(content: bytes) -> Dict[str, Any]:
    if not content or len(content) > _MAX_LOCK_BYTES:
        raise EffectiveChecksumResolutionError("correction lock size is invalid")
    try:
        payload = json.loads(
            content.decode("utf-8"),
            object_pairs_hook=_json_object_without_duplicate_keys,
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise EffectiveChecksumResolutionError(
            "correction lock is not canonical UTF-8 JSON"
        ) from error
    if not isinstance(payload, dict):
        raise EffectiveChecksumResolutionError("correction lock is not a JSON object")
    if correction.formal_io.json_bytes(payload) != content:
        raise EffectiveChecksumResolutionError(
            "correction lock bytes are not canonical formal JSON"
        )
    return payload


def _source_binding_by_path(payload: Mapping[str, Any]) -> Dict[str, Mapping[str, Any]]:
    raw = payload.get("source_bindings")
    if not isinstance(raw, list):
        raise EffectiveChecksumResolutionError(
            "correction lock source bindings are absent"
        )
    result: Dict[str, Mapping[str, Any]] = {}
    for item in raw:
        if not isinstance(item, Mapping):
            raise EffectiveChecksumResolutionError(
                "correction lock source binding is not an object"
            )
        path = item.get("path")
        if not isinstance(path, str) or path in result:
            raise EffectiveChecksumResolutionError(
                "correction lock source binding path is invalid or duplicate"
            )
        result[path] = item
    return result


def _validate_loaded_runtime_source_bindings(payload: Mapping[str, Any]) -> None:
    bindings = _source_binding_by_path(payload)
    roles = dict(correction.SOURCE_ROLES)
    for relative, module in _RUNTIME_MODULE_SOURCES:
        imported = _IMPORTED_RUNTIME_IDENTITIES[relative]
        current = _stable_file_identity(_module_source_path(module))
        if current != imported:
            raise EffectiveChecksumResolutionError(
                "correction runtime source changed after module import"
            )
        expected = {
            "path": relative,
            "sha256": imported["sha256"],
            "size_bytes": imported["size_bytes"],
            "role": roles[relative],
        }
        if bindings.get(relative) != expected:
            raise EffectiveChecksumResolutionError(
                "correction runtime source binding differs from loaded code"
            )


def load_correction_lock(root: Path = ROOT) -> ValidatedCorrectionLock:
    """Load and fully validate the additive HF correction lock.

    This verifies the formal file shape, canonical JSON bytes, self-hash,
    exact 39+2 overlay, and every correction-builder source binding.  It does
    not contact Hugging Face, hash a bag, or read any trajectory/result file.
    """

    workspace = Path(root).absolute()
    try:
        content_before, identity_before = correction.formal_io.read_direct_bytes(
            workspace, CORRECTION_LOCK_RELATIVE
        )
        payload = _decode_lock(content_before)
        _validate_loaded_runtime_source_bindings(payload)
        observed_hash = correction.validate_lock_payload(
            payload,
            root=workspace,
            verify_sources=True,
            verify_local_hashes=False,
            revalidate_local_identities=False,
            verify_live_api=False,
        )
        self_hash = payload.get(correction.SELF_HASH_FIELD)
        if (
            not isinstance(observed_hash, str)
            or _HEX64.fullmatch(observed_hash) is None
            or observed_hash != self_hash
        ):
            raise EffectiveChecksumResolutionError(
                "correction validator did not return the frozen self-hash"
            )
        _validate_loaded_runtime_source_bindings(payload)
        content_after, identity_after = correction.formal_io.read_direct_bytes(
            workspace, CORRECTION_LOCK_RELATIVE
        )
        if content_after != content_before or identity_after != identity_before:
            raise EffectiveChecksumResolutionError(
                "correction lock changed while it was validated"
            )
    except EffectiveChecksumResolutionError:
        raise
    except (OSError, ValueError, TypeError, correction.HFChecksumCorrectionError,
            correction.formal_io.FormalIOError) as error:
        raise EffectiveChecksumResolutionError(
            "cannot load the frozen HF checksum-semantics correction lock"
        ) from error
    # JSON round-trip detaches the validated value from parser-owned objects.
    detached = json.loads(json.dumps(payload, ensure_ascii=True))
    return ValidatedCorrectionLock(
        detached,
        token=_VALIDATION_SENTINEL,
        validated_self_hash=observed_hash,
    )


def _validated_overlay(
    correction_lock: Mapping[str, Any],
) -> Mapping[str, Any]:
    if (
        not isinstance(correction_lock, ValidatedCorrectionLock)
        or getattr(correction_lock, "_validation_token", None)
        is not _VALIDATION_SENTINEL
    ):
        raise EffectiveChecksumResolutionError(
            "correction_lock was not returned by load_correction_lock"
        )
    loaded_hash = getattr(correction_lock, "_validated_self_hash", None)
    if correction_lock.get(correction.SELF_HASH_FIELD) != loaded_hash:
        raise EffectiveChecksumResolutionError(
            "loaded correction lock was mutated after validation"
        )
    try:
        # Consume a canonical, detached value rather than any nested object
        # reachable through the caller-visible ValidatedCorrectionLock.  The
        # second serialization closes mutation during snapshot validation;
        # mutation after it cannot affect the detached authority returned here.
        content_before = correction.formal_io.json_bytes(correction_lock)
        snapshot = _decode_lock(content_before)
        observed_hash = correction.validate_lock_payload(
            snapshot,
            verify_sources=False,
            verify_local_hashes=False,
            revalidate_local_identities=False,
            verify_live_api=False,
        )
        content_after = correction.formal_io.json_bytes(correction_lock)
    except (
        RuntimeError,
        ValueError,
        TypeError,
        correction.HFChecksumCorrectionError,
        correction.formal_io.FormalIOError,
    ) as error:
        raise EffectiveChecksumResolutionError(
            "correction lock no longer satisfies its frozen schema"
        ) from error
    if content_after != content_before:
        raise EffectiveChecksumResolutionError(
            "correction lock changed while its detached snapshot was validated"
        )
    if observed_hash != loaded_hash:
        raise EffectiveChecksumResolutionError(
            "correction lock self-hash drifted after validation"
        )
    overlay = snapshot.get("effective_checksum_overlay")
    if not isinstance(overlay, Mapping):
        raise EffectiveChecksumResolutionError(
            "correction lock has no effective checksum overlay"
        )
    return overlay


def _normalized_base_manifest(
    entries: Mapping[str, str], overlay: Mapping[str, Any]
) -> Dict[str, str]:
    if not isinstance(entries, Mapping):
        raise EffectiveChecksumResolutionError(
            "base_manifest_entries must be a path-to-digest mapping"
        )
    try:
        items = list(entries.items())
    except (AttributeError, RuntimeError, TypeError, ValueError) as error:
        raise EffectiveChecksumResolutionError(
            "base manifest entries cannot be snapshotted"
        ) from error
    normalized: Dict[str, str] = {}
    for path, digest in items:
        if (
            not isinstance(path, str)
            or not path
            or path in normalized
            or not isinstance(digest, str)
            or _HEX64.fullmatch(digest) is None
        ):
            raise EffectiveChecksumResolutionError(
                "base manifest contains an invalid/duplicate path or digest"
            )
        normalized[path] = digest
    if len(normalized) != len(items):
        raise EffectiveChecksumResolutionError(
            "base manifest changed or collapsed duplicate paths while read"
        )

    direct = overlay.get("direct_base_paths")
    corrected = overlay.get("exact_corrected_paths")
    if not isinstance(direct, list) or not isinstance(corrected, list):
        raise EffectiveChecksumResolutionError("checksum overlay partition is invalid")
    direct_set = set(direct)
    corrected_set = set(corrected)
    if (
        len(direct) != 39
        or len(direct_set) != 39
        or len(corrected) != 2
        or len(corrected_set) != 2
        or direct_set.intersection(corrected_set)
        or len(normalized) != 41
        or set(normalized) != direct_set.union(corrected_set)
    ):
        raise EffectiveChecksumResolutionError(
            "base manifest and overlay are not the exact disjoint 39+2 partition"
        )

    binding = overlay.get("base_manifest_binding")
    if not isinstance(binding, Mapping):
        raise EffectiveChecksumResolutionError("base manifest binding is invalid")
    canonical = "".join(
        "%s  %s\n" % (normalized[path], path) for path in sorted(normalized)
    ).encode("utf-8")
    if (
        binding.get("path") != correction.DATASET_MANIFEST_RELATIVE
        or binding.get("path_count") != 41
        or binding.get("size_bytes") != len(canonical)
        or binding.get("sha256") != hashlib.sha256(canonical).hexdigest()
    ):
        raise EffectiveChecksumResolutionError(
            "base manifest values/bytes drift from the frozen source binding"
        )
    return normalized


def effective_content_record(
    path: str,
    base_manifest_entries: Mapping[str, str],
    correction_lock: Mapping[str, Any],
) -> Dict[str, Any]:
    """Return the only effective content-digest record authorized for ``path``."""

    if not isinstance(path, str) or not path:
        raise EffectiveChecksumResolutionError("checksum path must be a non-empty string")
    overlay = _validated_overlay(correction_lock)
    base = _normalized_base_manifest(base_manifest_entries, overlay)
    if path not in base:
        raise EffectiveChecksumResolutionError(
            "requested checksum path is outside the frozen 41-path scope"
        )

    raw_corrections = overlay.get("exact_corrections")
    if not isinstance(raw_corrections, list):
        raise EffectiveChecksumResolutionError("exact correction rows are invalid")
    corrections: Dict[str, Mapping[str, Any]] = {}
    for row in raw_corrections:
        if not isinstance(row, Mapping) or not isinstance(row.get("path"), str):
            raise EffectiveChecksumResolutionError("exact correction row is invalid")
        row_path = str(row["path"])
        if row_path in corrections:
            raise EffectiveChecksumResolutionError("exact correction path is duplicate")
        corrections[row_path] = row

    if path in corrections:
        row = corrections[path]
        scope_by_path = {
            spec.local_relative: spec for spec in correction.SCOPE_SPECS
        }
        spec = scope_by_path.get(path)
        base_digest = base[path]
        effective = row.get("effective_content_sha256")
        if (
            spec is None
            or base_digest != spec.xet_hash
            or row.get("base_manifest_sha256") != spec.xet_hash
            or row.get("base_digest_semantics") != "HUGGINGFACE_XET_HASH"
            or row.get("effective_digest_authority")
            != "FROZEN_OFFICIAL_API_LFS_OID_PLUS_MATCHING_LOCAL_FULL_SHA256"
            or effective != spec.lfs_oid
            or type(row.get("size_bytes")) is not int
            or row.get("size_bytes") != spec.size_bytes
        ):
            raise EffectiveChecksumResolutionError(
                "scoped Xet correction does not resolve to its distinct LFS content SHA-256"
            )
        return {
            "resolver_schema_version": RESOLVER_SCHEMA_VERSION,
            "path": path,
            "base_manifest_sha256": base_digest,
            "base_digest_semantics": "HUGGINGFACE_XET_HASH",
            "effective_content_sha256": effective,
            "effective_digest_authority": row["effective_digest_authority"],
            "correction_applied": True,
            "size_bytes": row.get("size_bytes"),
        }

    if path not in set(overlay.get("direct_base_paths", [])):
        raise EffectiveChecksumResolutionError(
            "requested path is in neither exact checksum partition"
        )
    digest = base[path]
    # The exact base-manifest binding above is what proves these 39 historical
    # values.  They are not permitted to inherit the scoped Xet semantics.
    if any(
        digest == row.get("base_manifest_sha256") for row in corrections.values()
    ):
        raise EffectiveChecksumResolutionError(
            "a direct-base path attempts to reuse a scoped Xet identifier"
        )
    return {
        "resolver_schema_version": RESOLVER_SCHEMA_VERSION,
        "path": path,
        "base_manifest_sha256": digest,
        "base_digest_semantics": "FROZEN_BASE_MANIFEST_CONTENT_SHA256",
        "effective_content_sha256": digest,
        "effective_digest_authority": "FROZEN_BOUND_BASE_MANIFEST",
        "correction_applied": False,
        "size_bytes": None,
    }


def effective_content_sha256(
    path: str,
    base_manifest_entries: Mapping[str, str],
    correction_lock: Mapping[str, Any],
) -> str:
    """Return the effective content SHA-256 for one frozen manifest path."""

    record = effective_content_record(path, base_manifest_entries, correction_lock)
    digest = record.get("effective_content_sha256")
    if not isinstance(digest, str) or _HEX64.fullmatch(digest) is None:
        raise EffectiveChecksumResolutionError(
            "effective checksum record does not contain a SHA-256"
        )
    return digest


__all__ = [
    "CORRECTION_LOCK_RELATIVE",
    "EffectiveChecksumResolutionError",
    "RESOLVER_SCHEMA_VERSION",
    "ValidatedCorrectionLock",
    "effective_content_record",
    "effective_content_sha256",
    "load_correction_lock",
]
