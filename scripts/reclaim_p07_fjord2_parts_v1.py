#!/usr/bin/env python3
"""Governed executor for the exact P07 fjord_2 ``.parts`` cache.

The default mode is a read-only preflight.  Mutation requires ``--execute``, a
valid formal lock, exact frozen tool hashes, an unchanged inventory, zero
references, and zero open/download processes.  A durable no-clobber intent is
published before the first unlink; a durable no-clobber PASS receipt is
published only after all exact postconditions hold.
"""

from __future__ import annotations

import argparse
import fcntl
import json
import os
import stat
import sys
from pathlib import Path
from typing import Any, Dict, Mapping, Sequence

import build_p07_fjord2_parts_reclaim_lock_v1 as governance


ROOT = Path(__file__).resolve().parents[1]
INTENT_SCHEMA = "isj-p07-fjord2-parts-reclaim-intent-v1"
RECEIPT_SCHEMA = "isj-p07-fjord2-parts-reclaim-receipt-v1"
ACTION_LOCK_NAME = ".fjord2_parts_reclaim_action_v1.lock"


def load_formal_lock(
    root: Path, parent_fd: int | None = None
) -> Dict[str, Any]:
    root = root.absolute()
    if parent_fd is None:
        lock = governance.secure_read_direct_json(
            root, governance.LOCK_REL, "formal fjord_2 reclaim lock"
        )
    else:
        lock = governance.secure_read_direct_json_at(
            parent_fd, governance.LOCK_REL.name, "formal fjord_2 reclaim lock"
        )
    governance.validate_lock_semantics(root, lock)
    return lock


def _require_equal(label: str, current: Any, frozen: Any) -> None:
    if current != frozen:
        raise governance.ReclaimViolation(f"{label} drifted from the frozen lock")


def revalidate_locked_state(root: Path, lock: Mapping[str, Any]) -> Dict[str, Any]:
    frozen = lock.get("frozen_state")
    if not isinstance(frozen, dict):
        raise governance.ReclaimViolation("lock has no frozen_state object")
    current = governance.collect_current_state(root)

    # These components are immutable and compared byte-for-byte as JSON data.
    _require_equal("part inventory", current["inventory"], frozen.get("inventory"))
    _require_equal(
        "canonical symlink/target contract",
        current["canonical_contract"],
        frozen.get("canonical_contract"),
    )
    _require_equal(
        "checksum-manifest bindings",
        current["checksum_bindings"],
        frozen.get("checksum_bindings"),
    )
    _require_equal(
        "frozen tool hashes",
        current["frozen_artifacts"],
        frozen.get("frozen_artifacts"),
    )

    # Other experiment evidence may append between lock freeze and execution.
    # It is therefore re-scanned, but an exact candidate reference is always a
    # hard failure.  The formal capacity-recovery subtree is excluded so the
    # reclaim lock and intent do not self-trigger.
    if current["zero_reference_scan"].get("matches") != []:
        raise governance.ReclaimViolation("candidate gained an evidence reference")
    if current["quiescence"].get("active_matches") != []:
        raise governance.ReclaimViolation("candidate is live during revalidation")
    if current["quiescence"].get("inspection_errors") != []:
        raise governance.ReclaimViolation("process inspection was incomplete")
    _require_equal(
        "frozen inaccessible-process exception tuples",
        current["quiescence"].get("inaccessible_process_exceptions"),
        frozen.get("quiescence", {}).get("inaccessible_process_exceptions"),
    )
    _require_equal(
        "boot identity",
        current["quiescence"].get("boot_id_sha256"),
        frozen.get("quiescence", {}).get("boot_id_sha256"),
    )
    _require_equal(
        "inaccessible-process exception policy",
        current["quiescence"].get("inaccessible_exception_policy"),
        frozen.get("quiescence", {}).get("inaccessible_exception_policy"),
    )
    return current


def preflight(root: Path = ROOT) -> Dict[str, Any]:
    root = root.absolute()
    try:
        parent_fd, _ = governance._open_directory_chain(
            root, governance.LOCK_REL.parent, create=False
        )
    except FileNotFoundError as exc:
        raise governance.ReclaimViolation("formal reclaim parent is missing") from exc
    try:
        lock = load_formal_lock(root, parent_fd)
        if governance._entry_lstat_at(parent_fd, governance.INTENT_REL.name) is not None:
            raise governance.ReclaimViolation("formal intent already exists")
        if governance._entry_lstat_at(parent_fd, governance.RECEIPT_REL.name) is not None:
            raise governance.ReclaimViolation("formal receipt already exists")
        current = revalidate_locked_state(root, lock)
    finally:
        os.close(parent_fd)
    return {
        "schema": "isj-p07-fjord2-parts-reclaim-preflight-v1",
        "status": "PASS_READ_ONLY_NO_MUTATION",
        "lock_hash": lock[governance.SELF_HASH_FIELD],
        "candidate_relative_path": governance.CANDIDATE_REL.as_posix(),
        "part_count": current["inventory"]["part_count"],
        "logical_bytes": current["inventory"]["logical_bytes"],
        "allocated_tree_bytes": current["inventory"]["allocated_tree_bytes"],
        "outcome_boundary": governance.OUTCOME_BOUNDARY,
    }


def _document_hash(document: Mapping[str, Any], field: str) -> str:
    return governance.document_self_hash(document, field)


def _build_intent(lock: Mapping[str, Any], current: Mapping[str, Any]) -> Dict[str, Any]:
    inventory = current["inventory"]
    intent: Dict[str, Any] = {
        "schema": INTENT_SCHEMA,
        "status": "AUTHORIZED_BEFORE_UNLINK",
        "created_at_utc": governance.utc_now(),
        "lock_hash": lock[governance.SELF_HASH_FIELD],
        "inventory_hash": inventory["inventory_hash"],
        "candidate_relative_path": governance.CANDIDATE_REL.as_posix(),
        "expected_part_count": inventory["part_count"],
        "expected_logical_bytes": inventory["logical_bytes"],
        "expected_allocated_tree_bytes": inventory["allocated_tree_bytes"],
        "canonical_contract": current["canonical_contract"],
        "ordering": "fsync intent before first unlink; fsync directories before PASS receipt",
        "crash_policy": "intent_without_PASS_receipt blocks automatic retry",
        "outcome_boundary": governance.OUTCOME_BOUNDARY,
    }
    intent["intent_hash"] = _document_hash(intent, "intent_hash")
    return intent


def _assert_lstat_matches(
    observed: os.stat_result, frozen: Mapping[str, Any], label: str
) -> None:
    current = governance._stat_record(observed)
    frozen_stat = {field: frozen.get(field) for field in current}
    if current != frozen_stat:
        raise governance.ReclaimViolation(f"immediate lstat drift for {label}")


def unlink_part(name: str, directory_fd: int) -> None:
    """One indirection so synthetic tests can inject a mid-delete failure."""

    os.unlink(name, dir_fd=directory_fd)


def _unlink_exact_inventory(
    root: Path, locked_inventory: Mapping[str, Any]
) -> Dict[str, int]:
    candidate = root / governance.CANDIDATE_REL
    part_root = root / governance.PART_ROOT_REL
    parent = candidate.parent
    nofollow = getattr(os, "O_NOFOLLOW", 0)

    parent_fd = os.open(parent, os.O_RDONLY | os.O_DIRECTORY | nofollow)
    candidate_fd = -1
    part_fd = -1
    count = 0
    logical_bytes = 0
    allocated_file_bytes = 0
    try:
        candidate_fd = os.open(
            candidate.name, os.O_RDONLY | os.O_DIRECTORY | nofollow, dir_fd=parent_fd
        )
        _assert_lstat_matches(
            os.fstat(candidate_fd),
            locked_inventory["candidate_lstat"],
            "candidate directory",
        )
        part_fd = os.open(
            "fjord_2.bag",
            os.O_RDONLY | os.O_DIRECTORY | nofollow,
            dir_fd=candidate_fd,
        )
        _assert_lstat_matches(
            os.fstat(part_fd), locked_inventory["part_root_lstat"], "part root"
        )

        frozen_names = [record["name"] for record in locked_inventory["parts"]]
        if sorted(os.listdir(part_fd)) != sorted(frozen_names):
            raise governance.ReclaimViolation(
                "part directory entries drifted immediately before unlink"
            )

        for record in locked_inventory["parts"]:
            name = str(record["name"])
            try:
                observed = os.stat(name, dir_fd=part_fd, follow_symlinks=False)
            except FileNotFoundError as exc:
                raise governance.ReclaimViolation(
                    f"part disappeared immediately before unlink: {name}"
                ) from exc
            _assert_lstat_matches(observed, record, f"part {name}")
            unlink_part(name, part_fd)
            count += 1
            logical_bytes += int(record["size_bytes"])
            allocated_file_bytes += int(record["allocated_bytes"])

        if os.listdir(part_fd):
            raise governance.ReclaimViolation("part directory not empty after exact unlink set")
        os.fsync(part_fd)
        os.close(part_fd)
        part_fd = -1

        os.rmdir("fjord_2.bag", dir_fd=candidate_fd)
        os.fsync(candidate_fd)
        if os.listdir(candidate_fd):
            raise governance.ReclaimViolation("candidate directory not empty after part-root removal")
        os.close(candidate_fd)
        candidate_fd = -1

        os.rmdir(candidate.name, dir_fd=parent_fd)
        os.fsync(parent_fd)
    finally:
        if part_fd >= 0:
            os.close(part_fd)
        if candidate_fd >= 0:
            os.close(candidate_fd)
        os.close(parent_fd)

    return {
        "part_count": count,
        "logical_bytes": logical_bytes,
        "allocated_file_bytes": allocated_file_bytes,
    }


def _postcondition(
    root: Path,
    lock: Mapping[str, Any],
    intent: Mapping[str, Any],
    deleted: Mapping[str, int],
) -> Dict[str, Any]:
    frozen = lock["frozen_state"]
    inventory = frozen["inventory"]
    candidate = root / governance.CANDIDATE_REL
    if os.path.lexists(candidate):
        raise governance.ReclaimViolation(f"candidate remains after unlink: {candidate}")
    if deleted["part_count"] != int(inventory["part_count"]):
        raise governance.ReclaimViolation("deleted part-count postcondition mismatch")
    if deleted["logical_bytes"] != int(inventory["logical_bytes"]):
        raise governance.ReclaimViolation("deleted logical-byte postcondition mismatch")
    if deleted["allocated_file_bytes"] != int(inventory["allocated_file_bytes"]):
        raise governance.ReclaimViolation("deleted allocated-file-byte postcondition mismatch")

    canonical = governance.collect_canonical_contract(root)
    if canonical != frozen["canonical_contract"]:
        raise governance.ReclaimViolation("canonical contract changed during reclaim")
    bindings = governance.collect_checksum_bindings(root)
    if bindings != frozen["checksum_bindings"]:
        raise governance.ReclaimViolation("checksum binding changed during reclaim")
    artifacts = governance.collect_frozen_artifacts(root)
    if artifacts != frozen["frozen_artifacts"]:
        raise governance.ReclaimViolation("frozen tool/evidence artifact changed during reclaim")

    return {
        "candidate_absent": True,
        "exact_part_count_unlinked": deleted["part_count"],
        "exact_logical_bytes_unlinked": deleted["logical_bytes"],
        "exact_allocated_file_bytes_unlinked": deleted["allocated_file_bytes"],
        "expected_allocated_tree_bytes": inventory["allocated_tree_bytes"],
        "canonical_contract_unchanged": True,
        "checksum_bindings_unchanged": True,
        "frozen_artifacts_unchanged": True,
        "intent_hash": intent["intent_hash"],
    }


def execute(root: Path = ROOT) -> Dict[str, Any]:
    root = root.absolute()
    try:
        parent_fd, _ = governance._open_directory_chain(
            root, governance.LOCK_REL.parent, create=False
        )
    except FileNotFoundError as exc:
        raise governance.ReclaimViolation("formal capacity-recovery directory is missing") from exc
    action_fd = -1
    try:
        # Validate semantics before creating even the coordination lock.
        load_formal_lock(root, parent_fd)
        existed = governance._entry_lstat_at(parent_fd, ACTION_LOCK_NAME) is not None
        flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0)
        action_fd = os.open(ACTION_LOCK_NAME, flags, 0o600, dir_fd=parent_fd)
        if not stat.S_ISREG(os.fstat(action_fd).st_mode):
            raise governance.ReclaimViolation("action lock is not a direct regular file")
        if not existed:
            os.fsync(parent_fd)
        fcntl.flock(action_fd, fcntl.LOCK_EX)
        lock = load_formal_lock(root, parent_fd)
        if governance._entry_lstat_at(parent_fd, governance.INTENT_REL.name) is not None:
            raise governance.ReclaimViolation(
                "no-clobber intent already exists; automatic retry is forbidden"
            )
        if governance._entry_lstat_at(parent_fd, governance.RECEIPT_REL.name) is not None:
            raise governance.ReclaimViolation("no-clobber PASS receipt already exists")

        current = revalidate_locked_state(root, lock)

        intent = _build_intent(lock, current)
        intent_record = governance.atomic_no_clobber_json_at_formal_parent(
            root, parent_fd, governance.INTENT_REL, intent
        )

        # The durable intent is now visible.  Revalidate again immediately
        # before the first unlink; any failure leaves intent-only evidence and
        # blocks an automatic retry.
        current = revalidate_locked_state(root, lock)
        governance._assert_publication_reachable(
            root, governance.INTENT_REL, parent_fd, intent_record
        )
        observed_intent = governance.secure_read_direct_json_at(
            parent_fd, governance.INTENT_REL.name, "formal reclaim intent"
        )
        if observed_intent != intent:
            raise governance.ReclaimViolation(
                "durable intent content drifted immediately before unlink"
            )
        governance.verify_document_self_hash(observed_intent, "intent_hash")
        deleted = _unlink_exact_inventory(root, current["inventory"])
        postcondition = _postcondition(root, lock, intent, deleted)

        receipt: Dict[str, Any] = {
            "schema": RECEIPT_SCHEMA,
            "status": "PASS",
            "created_at_utc": governance.utc_now(),
            "lock_hash": lock[governance.SELF_HASH_FIELD],
            "intent_hash": intent["intent_hash"],
            "postcondition": postcondition,
            "outcome_boundary": governance.OUTCOME_BOUNDARY,
        }
        receipt["receipt_hash"] = _document_hash(receipt, "receipt_hash")
        governance.atomic_no_clobber_json_at_formal_parent(
            root, parent_fd, governance.RECEIPT_REL, receipt
        )
        return receipt
    finally:
        if action_fd >= 0:
            try:
                fcntl.flock(action_fd, fcntl.LOCK_UN)
            finally:
                os.close(action_fd)
        os.close(parent_fd)


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument(
        "--execute",
        action="store_true",
        help="perform the exact governed unlink (default is read-only preflight)",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    result = execute(args.root) if args.execute else preflight(args.root)
    print(json.dumps(result, ensure_ascii=True, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except governance.ReclaimViolation as exc:
        print(f"FJORD2_PARTS_RECLAIM_VIOLATION: {exc}", file=sys.stderr)
        raise SystemExit(1)
