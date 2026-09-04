#!/usr/bin/env python3
"""Attest the retained canonical fjord_2 bag after governed parts reclaim.

The default mode is a read-only preflight.  ``--write`` is required to
publish the additive attestation.  A digest mismatch is a structured FAIL,
not an exception: preflight exits nonzero without writing, while explicit
``--write`` preserves the FAIL as a no-clobber integrity incident and still
exits nonzero.  This tool never reads trajectory, APE, RPE, or accuracy
artifacts and never modifies the frozen reclaim lock, intent, or receipt.

The reclaim receipt proves deletion of the frozen names with their frozen
stat identities.  It does *not* prove that the deleted downloader parts were
byte-identical to the retained canonical bag: a combined parts SHA-256 was
not available.  This tool therefore makes a separate, direct SHA-256
attestation of the retained canonical target and records that evidentiary
boundary explicitly.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import secrets
import stat
import sys
from pathlib import Path
from typing import Any, Dict, List, Mapping, Sequence, Tuple


ROOT = Path(__file__).resolve().parents[1]

LOCK_REL = Path(
    "papers/ieee_sensors_journal_experiments/p07/capacity_recovery/"
    "fjord2_parts_reclaim_lock_v1.json"
)
INTENT_REL = Path(
    "papers/ieee_sensors_journal_experiments/p07/capacity_recovery/"
    "fjord2_parts_reclaim_intent_v1.json"
)
RECEIPT_REL = Path(
    "papers/ieee_sensors_journal_experiments/p07/capacity_recovery/"
    "fjord2_parts_reclaim_receipt_v1.json"
)
OUTPUT_REL = Path(
    "papers/ieee_sensors_journal_experiments/p07/capacity_recovery/"
    "fjord2_retained_canonical_attestation_v1.json"
)

DATASETS_REL = Path("datasets")
CANDIDATE_REL = Path(
    "datasets/full_downloads/ntnu_hf/subset-fjord/fjord_2/.parts"
)
CANONICAL_REL = Path(
    "datasets/full_downloads/ntnu_hf/subset-fjord/fjord_2/fjord_2.bag"
)

FROZEN_SOURCE_RELS: Tuple[Path, ...] = (
    Path("scripts/build_p07_fjord2_parts_reclaim_lock_v1.py"),
    Path("scripts/reclaim_p07_fjord2_parts_v1.py"),
    Path("scripts/tests/test_p07_fjord2_parts_reclaim_v1.py"),
    Path("scripts/download_hf_mirror_dataset.py"),
)

LOCK_SCHEMA = "isj-p07-fjord2-parts-reclaim-lock-v1"
LOCK_STATUS = "FROZEN_READY_FOR_FJORD2_PARTS_RECLAIM"
INTENT_SCHEMA = "isj-p07-fjord2-parts-reclaim-intent-v1"
INTENT_STATUS = "AUTHORIZED_BEFORE_UNLINK"
RECEIPT_SCHEMA = "isj-p07-fjord2-parts-reclaim-receipt-v1"
RECEIPT_STATUS = "PASS"
ATTESTATION_SCHEMA = "isj-p07-fjord2-retained-canonical-attestation-v1"
ATTESTATION_PASS_STATUS = "PASS_RETAINED_CANONICAL_SHA256_ATTESTED"
ATTESTATION_DIGEST_MISMATCH_STATUS = "FAIL_RETAINED_CANONICAL_DIGEST_MISMATCH"

EXPECTED_SIZE = 23_396_131_412
EXPECTED_SHA256 = "c02cd7aad63d3234a53d9410ff77780700454851990f40244be722a883ecab49"
EXPECTED_PART_COUNT = 349
OUTCOME_BOUNDARY = "CAPACITY_RECOVERY_ONLY_NO_TRAJECTORY_OR_ACCURACY_EVIDENCE"
BUFFER_SIZE = 4 * 1024 * 1024

# These values make the already-published chain an external authority.  A
# document cannot be edited and merely re-self-hashed into a new "frozen"
# identity.  The source hashes are duplicated here for the same reason and
# are also required to match the records embedded in the formal lock.
EXPECTED_FORMAL_SELF_HASHES: Mapping[str, str] = {
    "lock": "be3b8e3334cb68c0320a383f65ff9ee40ad8cd58ed13f4e63ee0f044a22be09b",
    "intent": "234437b151306ebd96da7d836e34b7b2c027c04603d4094f7f6c08c99ca4c2d1",
    "receipt": "4b91be03353608843143f7ee12a7cf7281192bbcb84ce4d9a95be45d214534e6",
}
EXPECTED_FROZEN_SOURCE_SHA256: Mapping[str, str] = {
    "scripts/build_p07_fjord2_parts_reclaim_lock_v1.py": "86eb8133ce05491968b2b3cb6e966c1e65a9306ce2cf7217b09c630e934dedb6",
    "scripts/reclaim_p07_fjord2_parts_v1.py": "bd41041b3202a348b3a372f2c32940ae3bb695617db3419814c76e1329e71d72",
    "scripts/tests/test_p07_fjord2_parts_reclaim_v1.py": "e176990d9952c13631ecabb898f406e145b17be33327495180dda6eabe6114c8",
    "scripts/download_hf_mirror_dataset.py": "96e4107cab820e985b658ec65620f3f1a161488444e237ba0bcad25074be4d4c",
}


class AttestationViolation(RuntimeError):
    """A fail-closed violation of the retained-canonical contract."""


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=True, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def document_self_hash(document: Mapping[str, Any], field: str) -> str:
    payload = dict(document)
    payload.pop(field, None)
    return sha256_bytes(canonical_json_bytes(payload))


def verify_document_self_hash(
    document: Mapping[str, Any], field: str, label: str
) -> str:
    observed = document.get(field)
    expected = document_self_hash(document, field)
    if observed != expected:
        raise AttestationViolation(
            f"{label} self-hash mismatch: expected {expected}, observed {observed}"
        )
    return expected


def _require_equal(label: str, observed: Any, expected: Any) -> None:
    if observed != expected:
        raise AttestationViolation(
            f"{label} drifted: expected {expected!r}, observed {observed!r}"
        )


def _safe_relative(relative: Path, label: str) -> None:
    if relative.is_absolute() or ".." in relative.parts or not relative.parts:
        raise AttestationViolation(f"unsafe project-relative {label}: {relative}")


def stat_record(st: os.stat_result) -> Dict[str, int]:
    return {
        "dev": int(st.st_dev),
        "inode": int(st.st_ino),
        "mode": int(st.st_mode),
        "nlink": int(st.st_nlink),
        "uid": int(st.st_uid),
        "gid": int(st.st_gid),
        "size_bytes": int(st.st_size),
        "allocated_bytes": int(st.st_blocks) * 512,
        "mtime_ns": int(st.st_mtime_ns),
    }


def runtime_stat_record(st: os.stat_result) -> Dict[str, int]:
    """Identity used across a live read, including non-frozen ctime.

    The legacy frozen stat schema intentionally has no ctime field, so
    ``stat_record`` must remain byte-compatible with it.  Runtime comparisons
    add ctime separately to catch same-inode, same-size rewrites whose mtime
    is restored during hashing.
    """

    record = stat_record(st)
    record["ctime_ns"] = int(st.st_ctime_ns)
    return record


def _open_directory_chain(root: Path, relative: Path) -> int:
    """Open direct directory components through anchored O_NOFOLLOW dirfds."""

    _safe_relative(relative, "directory path")
    flags = os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_NOFOLLOW", 0)
    current_fd = -1
    try:
        current_fd = os.open(str(root), flags)
        for component in relative.parts:
            child_fd = os.open(component, flags, dir_fd=current_fd)
            os.close(current_fd)
            current_fd = child_fd
        return current_fd
    except OSError as exc:
        if current_fd >= 0:
            os.close(current_fd)
        raise AttestationViolation(
            f"directory chain is missing, indirect, or not a directory: {relative}: {exc}"
        ) from exc


def _open_relative_directory(base_fd: int, relative: Path) -> int:
    """Open a direct directory path relative to an already anchored dirfd."""

    _safe_relative(relative, "anchored directory path")
    flags = os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_NOFOLLOW", 0)
    current_fd = os.dup(base_fd)
    try:
        for component in relative.parts:
            child_fd = os.open(component, flags, dir_fd=current_fd)
            os.close(current_fd)
            current_fd = child_fd
        return current_fd
    except OSError as exc:
        os.close(current_fd)
        raise AttestationViolation(
            f"anchored directory chain is missing, indirect, or not a directory: "
            f"{relative}: {exc}"
        ) from exc


def _entry_lstat_at(parent_fd: int, name: str) -> os.stat_result | None:
    try:
        return os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
    except FileNotFoundError:
        return None


def _read_all_fd(fd: int) -> bytes:
    chunks: List[bytes] = []
    while True:
        chunk = os.read(fd, 1024 * 1024)
        if not chunk:
            break
        chunks.append(chunk)
    return b"".join(chunks)


def secure_read_json(
    root: Path, relative: Path, label: str
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Read a direct JSON file and prove its identity stayed stable."""

    _safe_relative(relative, label)
    parent_fd = _open_directory_chain(root, relative.parent)
    fd = -1
    try:
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
        try:
            fd = os.open(relative.name, flags, dir_fd=parent_fd)
        except OSError as exc:
            raise AttestationViolation(f"cannot securely open {label}: {exc}") from exc
        before = os.fstat(fd)
        if not stat.S_ISREG(before.st_mode):
            raise AttestationViolation(f"{label} is not a direct regular file")
        raw = _read_all_fd(fd)
        after = os.fstat(fd)
        if runtime_stat_record(before) != runtime_stat_record(after):
            raise AttestationViolation(f"{label} changed while it was read")
        try:
            document = json.loads(raw.decode("utf-8"))
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise AttestationViolation(f"cannot decode {label}: {exc}") from exc
        if not isinstance(document, dict):
            raise AttestationViolation(f"{label} is not a JSON object")
        return document, {
            "relative_path": relative.as_posix(),
            "file_sha256": sha256_bytes(raw),
            "file_stat": stat_record(after),
        }
    finally:
        if fd >= 0:
            os.close(fd)
        os.close(parent_fd)


def _stream_sha256_fd(fd: int) -> Tuple[str, int]:
    digest = hashlib.sha256()
    total = 0
    while True:
        block = os.read(fd, BUFFER_SIZE)
        if not block:
            break
        digest.update(block)
        total += len(block)
    return digest.hexdigest(), total


def secure_hash_project_file(
    root: Path, relative: Path, frozen: Mapping[str, Any]
) -> Dict[str, Any]:
    """Hash one frozen source through O_NOFOLLOW with stable fstat checks."""

    _safe_relative(relative, "frozen source")
    parent_fd = _open_directory_chain(root, relative.parent)
    fd = -1
    try:
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
        try:
            fd = os.open(relative.name, flags, dir_fd=parent_fd)
        except OSError as exc:
            raise AttestationViolation(
                f"cannot securely open frozen source {relative}: {exc}"
            ) from exc
        before = os.fstat(fd)
        if not stat.S_ISREG(before.st_mode):
            raise AttestationViolation(
                f"frozen source is not a direct regular file: {relative}"
            )
        digest, byte_count = _stream_sha256_fd(fd)
        after = os.fstat(fd)
        current = stat_record(after)
        if runtime_stat_record(before) != runtime_stat_record(after):
            raise AttestationViolation(f"frozen source changed while hashing: {relative}")
        expected_record = {key: frozen.get(key) for key in current}
        _require_equal(f"frozen source stat {relative}", current, expected_record)
        _require_equal(
            f"frozen source SHA-256 {relative}", digest, frozen.get("sha256")
        )
        _require_equal(
            f"frozen source byte count {relative}", byte_count, current["size_bytes"]
        )
        return {
            "relative_path": relative.as_posix(),
            "sha256": digest,
            "size_bytes": byte_count,
            "frozen_hash_match": True,
            "frozen_stat_match": True,
            "opened_with_o_nofollow": True,
            "fstat_stable_before_after": True,
        }
    finally:
        if fd >= 0:
            os.close(fd)
        os.close(parent_fd)


def validate_formal_chain(
    root: Path,
    *,
    expected_size: int,
    expected_sha256: str,
    expected_part_count: int,
    expected_formal_self_hashes: Mapping[str, str],
    expected_source_sha256: Mapping[str, str],
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """Validate schemas, semantics, self-hashes, chain links, and source hashes."""

    lock, lock_source = secure_read_json(root, LOCK_REL, "frozen reclaim lock")
    intent, intent_source = secure_read_json(root, INTENT_REL, "frozen reclaim intent")
    receipt, receipt_source = secure_read_json(
        root, RECEIPT_REL, "frozen reclaim receipt"
    )

    lock_hash = verify_document_self_hash(lock, "reclaim_lock_hash", "reclaim lock")
    intent_hash = verify_document_self_hash(intent, "intent_hash", "reclaim intent")
    receipt_hash = verify_document_self_hash(
        receipt, "receipt_hash", "reclaim receipt"
    )
    _require_equal(
        "formal self-hash authority keys",
        set(expected_formal_self_hashes),
        {"lock", "intent", "receipt"},
    )
    _require_equal(
        "frozen lock identity", lock_hash, expected_formal_self_hashes.get("lock")
    )
    _require_equal(
        "frozen intent identity", intent_hash, expected_formal_self_hashes.get("intent")
    )
    _require_equal(
        "frozen receipt identity",
        receipt_hash,
        expected_formal_self_hashes.get("receipt"),
    )

    _require_equal("lock schema", lock.get("schema"), LOCK_SCHEMA)
    _require_equal("lock status", lock.get("status"), LOCK_STATUS)
    _require_equal("lock workspace root", lock.get("workspace_root"), str(root))
    _require_equal(
        "lock candidate path",
        lock.get("scope", {}).get("candidate_relative_path"),
        CANDIDATE_REL.as_posix(),
    )
    _require_equal("lock outcome boundary", lock.get("outcome_boundary"), OUTCOME_BOUNDARY)

    frozen = lock.get("frozen_state")
    if not isinstance(frozen, dict):
        raise AttestationViolation("lock has no frozen_state object")
    canonical_contract = frozen.get("canonical_contract")
    if not isinstance(canonical_contract, dict):
        raise AttestationViolation("lock has no canonical contract")
    _require_equal(
        "canonical relative path",
        canonical_contract.get("canonical_relative_path"),
        CANONICAL_REL.as_posix(),
    )
    _require_equal(
        "canonical expected size",
        canonical_contract.get("expected_size_bytes"),
        expected_size,
    )
    _require_equal(
        "canonical official SHA-256",
        canonical_contract.get("official_sha256"),
        expected_sha256,
    )
    inventory = frozen.get("inventory")
    if not isinstance(inventory, dict):
        raise AttestationViolation("lock has no frozen inventory")
    _require_equal("frozen part count", inventory.get("part_count"), expected_part_count)
    _require_equal("frozen logical bytes", inventory.get("logical_bytes"), expected_size)

    _require_equal("intent schema", intent.get("schema"), INTENT_SCHEMA)
    _require_equal("intent status", intent.get("status"), INTENT_STATUS)
    _require_equal("intent lock hash", intent.get("lock_hash"), lock_hash)
    _require_equal(
        "intent candidate path",
        intent.get("candidate_relative_path"),
        CANDIDATE_REL.as_posix(),
    )
    _require_equal("intent part count", intent.get("expected_part_count"), expected_part_count)
    _require_equal("intent logical bytes", intent.get("expected_logical_bytes"), expected_size)
    _require_equal(
        "intent inventory hash", intent.get("inventory_hash"), inventory.get("inventory_hash")
    )
    _require_equal(
        "intent canonical contract", intent.get("canonical_contract"), canonical_contract
    )
    _require_equal(
        "intent outcome boundary", intent.get("outcome_boundary"), OUTCOME_BOUNDARY
    )

    _require_equal("receipt schema", receipt.get("schema"), RECEIPT_SCHEMA)
    _require_equal("receipt status", receipt.get("status"), RECEIPT_STATUS)
    _require_equal("receipt lock hash", receipt.get("lock_hash"), lock_hash)
    _require_equal("receipt intent hash", receipt.get("intent_hash"), intent_hash)
    _require_equal(
        "receipt outcome boundary", receipt.get("outcome_boundary"), OUTCOME_BOUNDARY
    )
    postcondition = receipt.get("postcondition")
    if not isinstance(postcondition, dict):
        raise AttestationViolation("receipt has no postcondition object")
    _require_equal("receipt candidate absent", postcondition.get("candidate_absent"), True)
    _require_equal(
        "receipt canonical contract unchanged",
        postcondition.get("canonical_contract_unchanged"),
        True,
    )
    _require_equal(
        "receipt frozen artifacts unchanged",
        postcondition.get("frozen_artifacts_unchanged"),
        True,
    )
    _require_equal(
        "receipt checksum bindings unchanged",
        postcondition.get("checksum_bindings_unchanged"),
        True,
    )
    _require_equal(
        "receipt exact part count",
        postcondition.get("exact_part_count_unlinked"),
        expected_part_count,
    )
    _require_equal(
        "receipt exact logical bytes",
        postcondition.get("exact_logical_bytes_unlinked"),
        expected_size,
    )
    _require_equal(
        "receipt postcondition intent hash", postcondition.get("intent_hash"), intent_hash
    )

    frozen_artifacts = frozen.get("frozen_artifacts")
    if not isinstance(frozen_artifacts, dict):
        raise AttestationViolation("lock has no frozen source-artifact map")
    expected_source_names = {relative.as_posix() for relative in FROZEN_SOURCE_RELS}
    _require_equal(
        "frozen source path set", set(frozen_artifacts), expected_source_names
    )
    _require_equal(
        "frozen source hash-authority path set",
        set(expected_source_sha256),
        expected_source_names,
    )
    source_attestations: List[Dict[str, Any]] = []
    for relative in FROZEN_SOURCE_RELS:
        record = frozen_artifacts.get(relative.as_posix())
        if not isinstance(record, dict):
            raise AttestationViolation(f"missing frozen source record: {relative}")
        _require_equal(
            f"frozen source authoritative SHA-256 {relative}",
            record.get("sha256"),
            expected_source_sha256.get(relative.as_posix()),
        )
        source = secure_hash_project_file(root, relative, record)
        source["authoritative_hash_match"] = True
        source_attestations.append(source)

    chain = {
        "lock": {
            **lock_source,
            "schema": LOCK_SCHEMA,
            "status": LOCK_STATUS,
            "self_hash_field": "reclaim_lock_hash",
            "self_hash": lock_hash,
            "self_hash_valid": True,
        },
        "intent": {
            **intent_source,
            "schema": INTENT_SCHEMA,
            "status": INTENT_STATUS,
            "self_hash_field": "intent_hash",
            "self_hash": intent_hash,
            "self_hash_valid": True,
            "lock_hash_link_valid": True,
        },
        "receipt": {
            **receipt_source,
            "schema": RECEIPT_SCHEMA,
            "status": RECEIPT_STATUS,
            "self_hash_field": "receipt_hash",
            "self_hash": receipt_hash,
            "self_hash_valid": True,
            "lock_hash_link_valid": True,
            "intent_hash_link_valid": True,
        },
        "frozen_source_hashes": source_attestations,
        "all_self_hashes_valid": True,
        "all_self_hashes_match_frozen_authority": True,
        "all_chain_links_valid": True,
        "all_frozen_source_hashes_valid": True,
        "all_frozen_source_hashes_match_authority": True,
    }
    return lock, intent, receipt, chain


def _verify_dataset_mount(root: Path, contract: Mapping[str, Any]) -> int:
    """Verify the exact workspace datasets symlink and open its direct target."""

    workspace_path = root / DATASETS_REL
    _require_equal(
        "datasets workspace path", contract.get("workspace_path"), str(workspace_path)
    )
    try:
        link_st = os.lstat(str(workspace_path))
    except FileNotFoundError as exc:
        raise AttestationViolation("datasets workspace symlink is missing") from exc
    if not stat.S_ISLNK(link_st.st_mode):
        raise AttestationViolation("datasets workspace path is not a symlink")
    _require_equal(
        "datasets symlink lstat", stat_record(link_st), contract.get("link_lstat")
    )
    link_text = os.readlink(str(workspace_path))
    _require_equal("datasets symlink text", link_text, contract.get("link_text"))
    resolved = os.path.realpath(str(workspace_path))
    _require_equal("datasets resolved target", resolved, contract.get("resolved_target"))
    try:
        target_st = os.lstat(resolved)
    except FileNotFoundError as exc:
        raise AttestationViolation("datasets resolved target is missing") from exc
    if not stat.S_ISDIR(target_st.st_mode):
        raise AttestationViolation("datasets resolved target is not a direct directory")
    _require_equal(
        "datasets target lstat", stat_record(target_st), contract.get("target_lstat")
    )
    flags = os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(resolved, flags)
    except OSError as exc:
        raise AttestationViolation(
            f"cannot O_NOFOLLOW-open datasets resolved target: {exc}"
        ) from exc
    opened = os.fstat(fd)
    if stat_record(opened) != stat_record(target_st):
        os.close(fd)
        raise AttestationViolation("datasets target changed between lstat and open")
    return fd


def _candidate_absent(root: Path, datasets_contract: Mapping[str, Any]) -> bool:
    dataset_relative = CANDIDATE_REL.relative_to(DATASETS_REL)
    dataset_fd = _verify_dataset_mount(root, datasets_contract)
    current_fd = os.dup(dataset_fd)
    try:
        for component in dataset_relative.parent.parts:
            observed = _entry_lstat_at(current_fd, component)
            if observed is None:
                return True
            if not stat.S_ISDIR(observed.st_mode):
                raise AttestationViolation(
                    f"candidate ancestor is indirect or not a directory: {component}"
                )
            try:
                child_fd = os.open(
                    component,
                    os.O_RDONLY
                    | os.O_DIRECTORY
                    | getattr(os, "O_NOFOLLOW", 0),
                    dir_fd=current_fd,
                )
            except OSError as exc:
                raise AttestationViolation(
                    f"candidate ancestor changed while opening: {component}: {exc}"
                ) from exc
            os.close(current_fd)
            current_fd = child_fd
        observed = _entry_lstat_at(current_fd, dataset_relative.name)
        if observed is not None:
            raise AttestationViolation(
                f"reclaim candidate reappeared: {CANDIDATE_REL.as_posix()}"
            )
        return True
    finally:
        os.close(current_fd)
        os.close(dataset_fd)


def _canonical_symlink_snapshot(
    root: Path, canonical_contract: Mapping[str, Any]
) -> Dict[str, Any]:
    datasets_contract = canonical_contract.get("datasets_mount")
    symlink_contract = canonical_contract.get("canonical_symlink")
    if not isinstance(datasets_contract, dict) or not isinstance(symlink_contract, dict):
        raise AttestationViolation("canonical contract lacks symlink subcontracts")
    _require_equal(
        "canonical workspace path",
        symlink_contract.get("workspace_path"),
        str(root / CANONICAL_REL),
    )

    relative = CANONICAL_REL.relative_to(DATASETS_REL)
    dataset_fd = _verify_dataset_mount(root, datasets_contract)
    parent_fd = -1
    try:
        parent_fd = _open_relative_directory(dataset_fd, relative.parent)
        link_st = _entry_lstat_at(parent_fd, relative.name)
        if link_st is None:
            raise AttestationViolation("canonical workspace symlink is missing")
        if not stat.S_ISLNK(link_st.st_mode):
            raise AttestationViolation("canonical workspace path is not a symlink")
        current_link_record = stat_record(link_st)
        _require_equal(
            "canonical symlink lstat",
            current_link_record,
            symlink_contract.get("link_lstat"),
        )
        link_text = os.readlink(relative.name, dir_fd=parent_fd)
        _require_equal(
            "canonical symlink text", link_text, symlink_contract.get("link_text")
        )
    finally:
        if parent_fd >= 0:
            os.close(parent_fd)
        os.close(dataset_fd)

    resolved = os.path.realpath(str(root / CANONICAL_REL))
    _require_equal(
        "canonical resolved target", resolved, symlink_contract.get("resolved_target")
    )
    try:
        target_st = os.lstat(resolved)
    except FileNotFoundError as exc:
        raise AttestationViolation("canonical resolved target is missing") from exc
    if not stat.S_ISREG(target_st.st_mode):
        raise AttestationViolation(
            "canonical resolved target is not a direct regular file"
        )
    target_record = stat_record(target_st)
    _require_equal(
        "canonical resolved-target lstat",
        target_record,
        symlink_contract.get("target_lstat"),
    )
    return {
        "workspace_path": str(root / CANONICAL_REL),
        "link_text": link_text,
        "link_lstat": current_link_record,
        "link_runtime_lstat": runtime_stat_record(link_st),
        "resolved_target": resolved,
        "target_lstat": target_record,
        "target_runtime_lstat": runtime_stat_record(target_st),
    }


def _hash_canonical_target(
    resolved_target: str,
    frozen_target_record: Mapping[str, Any],
    expected_runtime_target_record: Mapping[str, Any],
    *,
    expected_size: int,
    expected_sha256: str,
) -> Dict[str, Any]:
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    fd = -1
    try:
        try:
            fd = os.open(resolved_target, flags)
        except OSError as exc:
            raise AttestationViolation(
                f"cannot O_NOFOLLOW-open canonical resolved target: {exc}"
            ) from exc
        before = os.fstat(fd)
        if not stat.S_ISREG(before.st_mode):
            raise AttestationViolation(
                "O_NOFOLLOW-opened canonical target is not a regular file"
            )
        before_record = stat_record(before)
        before_runtime_record = runtime_stat_record(before)
        _require_equal(
            "canonical opened-target fstat", before_record, frozen_target_record
        )
        _require_equal(
            "canonical opened-target runtime identity",
            before_runtime_record,
            expected_runtime_target_record,
        )
        digest, byte_count = _stream_sha256_fd(fd)
        after = os.fstat(fd)
        after_record = stat_record(after)
        after_runtime_record = runtime_stat_record(after)
        _require_equal(
            "canonical runtime fstat before/after",
            after_runtime_record,
            before_runtime_record,
        )
        try:
            path_after = os.lstat(resolved_target)
        except FileNotFoundError as exc:
            raise AttestationViolation(
                "canonical target path disappeared while hashing"
            ) from exc
        if not stat.S_ISREG(path_after.st_mode):
            raise AttestationViolation(
                "canonical target path became indirect or non-regular while hashing"
            )
        _require_equal(
            "canonical runtime path identity after hashing",
            runtime_stat_record(path_after),
            before_runtime_record,
        )
        _require_equal("canonical streamed byte count", byte_count, expected_size)
        _require_equal("canonical fstat size", before_record["size_bytes"], expected_size)
        digest_match = digest == expected_sha256
        return {
            "size_bytes": byte_count,
            "expected_size_bytes": expected_size,
            "sha256": digest,
            "expected_sha256": expected_sha256,
            "size_match": True,
            "sha256_match": digest_match,
            "resolved_target_type": "DIRECT_REGULAR_FILE",
            "opened_with_o_nofollow": True,
            "fstat_before": before_runtime_record,
            "fstat_after": after_runtime_record,
            "fstat_stable_before_after": True,
            "path_identity_stable_after_hash": True,
        }
    finally:
        if fd >= 0:
            os.close(fd)


def build_attestation(
    root: Path = ROOT,
    *,
    expected_size: int = EXPECTED_SIZE,
    expected_sha256: str = EXPECTED_SHA256,
    expected_part_count: int = EXPECTED_PART_COUNT,
    expected_formal_self_hashes: Mapping[str, str] = EXPECTED_FORMAL_SELF_HASHES,
    expected_source_sha256: Mapping[str, str] = EXPECTED_FROZEN_SOURCE_SHA256,
) -> Dict[str, Any]:
    """Build an in-memory attestation; no file is written."""

    root = root.absolute()
    if expected_size < 0:
        raise AttestationViolation("expected size must be non-negative")
    if len(expected_sha256) != 64 or any(
        character not in "0123456789abcdef" for character in expected_sha256
    ):
        raise AttestationViolation("expected SHA-256 is not lowercase hexadecimal")

    lock, _intent, _receipt, chain = validate_formal_chain(
        root,
        expected_size=expected_size,
        expected_sha256=expected_sha256,
        expected_part_count=expected_part_count,
        expected_formal_self_hashes=expected_formal_self_hashes,
        expected_source_sha256=expected_source_sha256,
    )
    canonical_contract = lock["frozen_state"]["canonical_contract"]
    datasets_contract = canonical_contract["datasets_mount"]

    candidate_absent_before = _candidate_absent(root, datasets_contract)
    symlink_before = _canonical_symlink_snapshot(root, canonical_contract)
    target = _hash_canonical_target(
        symlink_before["resolved_target"],
        symlink_before["target_lstat"],
        symlink_before["target_runtime_lstat"],
        expected_size=expected_size,
        expected_sha256=expected_sha256,
    )
    symlink_after = _canonical_symlink_snapshot(root, canonical_contract)
    _require_equal(
        "canonical symlink snapshot before/after", symlink_after, symlink_before
    )
    candidate_absent_after = _candidate_absent(root, datasets_contract)

    digest_match = bool(target["sha256_match"])
    attestation_status = (
        ATTESTATION_PASS_STATUS
        if digest_match
        else ATTESTATION_DIGEST_MISMATCH_STATUS
    )
    attestation: Dict[str, Any] = {
        "schema": ATTESTATION_SCHEMA,
        "status": attestation_status,
        "assessment_passed": digest_match,
        "created_at_utc": utc_now(),
        "workspace_root": str(root),
        "formal_reclaim_chain": chain,
        "reclaim_evidence_boundary": {
            "candidate_relative_path": CANDIDATE_REL.as_posix(),
            "candidate_absent_before_canonical_hash": candidate_absent_before,
            "candidate_absent_after_canonical_hash": candidate_absent_after,
            "receipt_proof_scope": "FROZEN_NAME_AND_STAT_DELETION_ONLY",
            "receipt_proves_frozen_names_and_stat_identities_deleted": True,
            "receipt_proves_byte_identical_redundancy": False,
            "parts_combined_sha256": {
                "available": False,
                "value": None,
                "reason": "the frozen reclaim evidence contains names and stat identities but no combined SHA-256 of downloader part contents",
            },
            "byte_identical_redundancy_claim": "NOT_MADE_UNAVAILABLE_PARTS_COMBINED_SHA256",
            "interpretation": "the receipt proves only deletion of the frozen names with their frozen stat identities; retained canonical content integrity is assessed separately by direct SHA-256 here and any mismatch is preserved as FAIL",
        },
        "retained_canonical": {
            "canonical_relative_path": CANONICAL_REL.as_posix(),
            "workspace_entry_type": "SYMLINK",
            "exact_frozen_symlink_contract_match_before_hash": True,
            "exact_frozen_symlink_contract_match_after_hash": True,
            "symlink_snapshot": symlink_after,
            "canonical_content_integrity_established": digest_match,
            **target,
        },
        "integrity_incident": (
            {
                "present": False,
                "status": "NONE_CANONICAL_DIGEST_MATCHED",
            }
            if digest_match
            else {
                "present": True,
                "status": ATTESTATION_DIGEST_MISMATCH_STATUS,
                "expected_sha256": expected_sha256,
                "observed_sha256": target["sha256"],
                "expected_size_bytes": expected_size,
                "observed_size_bytes": target["size_bytes"],
                "recovery_attempted": False,
                "prior_lock_intent_receipt_modified": False,
                "deleted_parts_content_reconstruction_attempted": False,
                "reason_reconstruction_is_unavailable": "combined downloader-parts content SHA-256 was never captured and the governed parts are absent",
            }
        ),
        "outcome_blinding": {
            "outcome_blind": True,
            "trajectory_artifacts_read": False,
            "ape_rpe_or_accuracy_artifacts_read": False,
            "trajectory_or_accuracy_values_parsed": False,
            "trajectory_or_accuracy_claim_made": False,
        },
        "outcome_boundary": OUTCOME_BOUNDARY,
    }
    attestation["attestation_hash"] = document_self_hash(
        attestation, "attestation_hash"
    )
    return attestation


def _atomic_no_clobber_json_at(
    parent_fd: int, name: str, payload: Mapping[str, Any]
) -> Dict[str, int]:
    """Publish by fsynced temp + hardlink, never replacing destination."""

    if "/" in name or name in ("", ".", ".."):
        raise AttestationViolation(f"unsafe output basename: {name}")
    if _entry_lstat_at(parent_fd, name) is not None:
        raise AttestationViolation(f"no-clobber destination already exists: {name}")
    temp_name = f".{name}.tmp.{os.getpid()}.{secrets.token_hex(8)}"
    data = (
        json.dumps(payload, ensure_ascii=True, sort_keys=True, indent=2).encode("utf-8")
        + b"\n"
    )
    flags = (
        os.O_WRONLY
        | os.O_CREAT
        | os.O_EXCL
        | getattr(os, "O_NOFOLLOW", 0)
    )
    fd = -1
    linked_identity: Tuple[int, int, int, int] | None = None
    try:
        fd = os.open(temp_name, flags, 0o444, dir_fd=parent_fd)
        offset = 0
        while offset < len(data):
            written = os.write(fd, data[offset:])
            if written <= 0:
                raise AttestationViolation("zero-length output write")
            offset += written
        os.fsync(fd)
        os.close(fd)
        fd = -1
        try:
            os.link(
                temp_name,
                name,
                src_dir_fd=parent_fd,
                dst_dir_fd=parent_fd,
                follow_symlinks=False,
            )
        except FileExistsError as exc:
            raise AttestationViolation(
                f"no-clobber publication race at {name}"
            ) from exc
        temp_st = os.stat(temp_name, dir_fd=parent_fd, follow_symlinks=False)
        destination_st = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
        if (
            temp_st.st_dev,
            temp_st.st_ino,
            temp_st.st_size,
            temp_st.st_mode,
        ) != (
            destination_st.st_dev,
            destination_st.st_ino,
            destination_st.st_size,
            destination_st.st_mode,
        ):
            raise AttestationViolation("hardlink publication identity mismatch")
        linked_identity = (
            int(destination_st.st_dev),
            int(destination_st.st_ino),
            int(destination_st.st_size),
            int(destination_st.st_mode),
        )
        os.fsync(parent_fd)
    finally:
        if fd >= 0:
            os.close(fd)
        try:
            os.unlink(temp_name, dir_fd=parent_fd)
            os.fsync(parent_fd)
        except FileNotFoundError:
            pass
    if linked_identity is None:
        raise AttestationViolation("attestation publication did not establish output")
    final_st = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
    final_identity = (
        int(final_st.st_dev),
        int(final_st.st_ino),
        int(final_st.st_size),
        int(final_st.st_mode),
    )
    if final_identity != linked_identity or final_st.st_nlink != 1:
        raise AttestationViolation("published output changed after temp cleanup")
    return stat_record(final_st)


def _output_absent(root: Path) -> None:
    parent_fd = _open_directory_chain(root, OUTPUT_REL.parent)
    try:
        if _entry_lstat_at(parent_fd, OUTPUT_REL.name) is not None:
            raise AttestationViolation(
                f"no-clobber destination already exists: {OUTPUT_REL.as_posix()}"
            )
    finally:
        os.close(parent_fd)


def write_attestation(
    root: Path = ROOT,
    *,
    expected_size: int = EXPECTED_SIZE,
    expected_sha256: str = EXPECTED_SHA256,
    expected_part_count: int = EXPECTED_PART_COUNT,
    expected_formal_self_hashes: Mapping[str, str] = EXPECTED_FORMAL_SELF_HASHES,
    expected_source_sha256: Mapping[str, str] = EXPECTED_FROZEN_SOURCE_SHA256,
) -> Dict[str, Any]:
    """Atomically publish the additive attestation or negative incident."""

    root = root.absolute()
    _output_absent(root)
    payload = build_attestation(
        root,
        expected_size=expected_size,
        expected_sha256=expected_sha256,
        expected_part_count=expected_part_count,
        expected_formal_self_hashes=expected_formal_self_hashes,
        expected_source_sha256=expected_source_sha256,
    )
    parent_fd = _open_directory_chain(root, OUTPUT_REL.parent)
    try:
        record = _atomic_no_clobber_json_at(parent_fd, OUTPUT_REL.name, payload)
    finally:
        os.close(parent_fd)

    # Reopen through the anchored project path and require exact bytes/content.
    observed, observed_source = secure_read_json(
        root, OUTPUT_REL, "published retained-canonical attestation"
    )
    if observed != payload:
        raise AttestationViolation("published attestation content mismatch")
    if observed_source["file_stat"] != record:
        raise AttestationViolation("published attestation path identity mismatch")
    verify_document_self_hash(observed, "attestation_hash", "published attestation")
    return payload


def preflight(
    root: Path = ROOT,
    *,
    expected_size: int = EXPECTED_SIZE,
    expected_sha256: str = EXPECTED_SHA256,
    expected_part_count: int = EXPECTED_PART_COUNT,
    expected_formal_self_hashes: Mapping[str, str] = EXPECTED_FORMAL_SELF_HASHES,
    expected_source_sha256: Mapping[str, str] = EXPECTED_FROZEN_SOURCE_SHA256,
) -> Dict[str, Any]:
    """Perform the full read-only validation without publishing output."""

    root = root.absolute()
    _output_absent(root)
    proposal = build_attestation(
        root,
        expected_size=expected_size,
        expected_sha256=expected_sha256,
        expected_part_count=expected_part_count,
        expected_formal_self_hashes=expected_formal_self_hashes,
        expected_source_sha256=expected_source_sha256,
    )
    passed = proposal["status"] == ATTESTATION_PASS_STATUS
    return {
        "schema": "isj-p07-fjord2-retained-canonical-preflight-v1",
        "status": (
            "PASS_READ_ONLY_NO_MUTATION"
            if passed
            else "FAIL_READ_ONLY_RETAINED_CANONICAL_DIGEST_MISMATCH"
        ),
        "assessment_passed": passed,
        "output_relative_path": OUTPUT_REL.as_posix(),
        "output_written": False,
        "proposed_attestation": proposal,
    }


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--preflight-only",
        action="store_true",
        help="run full read-only validation without writing (default)",
    )
    mode.add_argument(
        "--write",
        action="store_true",
        help="publish the additive no-clobber attestation/FAIL incident",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    result = write_attestation(args.root) if args.write else preflight(args.root)
    print(json.dumps(result, ensure_ascii=True, sort_keys=True, indent=2))
    if args.write:
        return 0 if result.get("status") == ATTESTATION_PASS_STATUS else 1
    return 0 if result.get("assessment_passed") is True else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except AttestationViolation as exc:
        print(f"FJORD2_RETAINED_CANONICAL_ATTESTATION_VIOLATION: {exc}", file=sys.stderr)
        raise SystemExit(1)
