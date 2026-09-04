#!/usr/bin/env python3
"""Build the narrowly scoped P07 fjord_2 downloader-parts reclaim lock.

The default invocation is read-only and prints the proposed lock.  ``--write``
is required to publish the formal no-clobber lock.  This module deliberately
does not contain any unlink operation.
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import errno
import fcntl
import hashlib
import json
import os
import re
import secrets
import stat
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Sequence, Tuple


ROOT = Path(__file__).resolve().parents[1]

LOCK_SCHEMA = "isj-p07-fjord2-parts-reclaim-lock-v1"
LOCK_STATUS = "FROZEN_READY_FOR_FJORD2_PARTS_RECLAIM"
SELF_HASH_FIELD = "reclaim_lock_hash"

CANDIDATE_REL = Path("datasets/full_downloads/ntnu_hf/subset-fjord/fjord_2/.parts")
PART_ROOT_REL = CANDIDATE_REL / "fjord_2.bag"
CANONICAL_REL = Path(
    "datasets/full_downloads/ntnu_hf/subset-fjord/fjord_2/fjord_2.bag"
)
DATASETS_LINK_REL = Path("datasets")

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

CHECKSUM_REL = Path(
    "papers/ieee_sensors_journal_experiments/p02/input_reference_checksums.csv"
)
ELIGIBILITY_REL = Path(
    "papers/ieee_sensors_journal_experiments/data_eligibility_manifest.csv"
)
REFERENCE_AUDIT_REL = Path(
    "papers/ieee_sensors_journal_experiments/reference_audit.csv"
)
EVIDENCE_SCAN_REL = Path("papers/ieee_sensors_journal_experiments")
CAPACITY_EVIDENCE_REL = Path(
    "papers/ieee_sensors_journal_experiments/p07/capacity_recovery"
)

TOOL_RELS: Tuple[Path, ...] = (
    Path("scripts/build_p07_fjord2_parts_reclaim_lock_v1.py"),
    Path("scripts/reclaim_p07_fjord2_parts_v1.py"),
    Path("scripts/tests/test_p07_fjord2_parts_reclaim_v1.py"),
    Path("scripts/download_hf_mirror_dataset.py"),
)

EXPECTED_SIZE = 23_396_131_412
EXPECTED_SHA256 = "c02cd7aad63d3234a53d9410ff77780700454851990f40244be722a883ecab49"
EXPECTED_PART_COUNT = 349
PART_RE = re.compile(r"^part_(\d{5})_(\d+)_(\d+)$")
TEXT_EVIDENCE_SUFFIXES = {
    ".conf",
    ".csv",
    ".ini",
    ".json",
    ".jsonl",
    ".lock",
    ".log",
    ".md",
    ".ndjson",
    ".py",
    ".sha256",
    ".toml",
    ".tsv",
    ".txt",
    ".yaml",
    ".yml",
}
G0_ACCURACY_PROBE_DIRS: Tuple[Path, ...] = tuple(
    Path("g0") / name
    for name in (
        "a06_2210_2460_probe",
        "a09_4000_4400_probe",
        "a10_2400_2800_probe",
        "h07_0_1000_probe",
        "ntnu_fjord4_s0_d30_probe",
    )
)
G0_EVO_RESULT_DIRS: Tuple[Path, ...] = tuple(
    probe / "evo_crosscheck" for probe in G0_ACCURACY_PROBE_DIRS
)
ANALYSIS_OUTPUT_DIRS: Tuple[Path, ...] = (
    Path("learned_specificity_20260803/analysis-output"),
    Path("ntnu_q_partition_20260805/analysis-output"),
)
CLASSIFIED_OUTCOME_CONTAINER_DIRS: Tuple[Path, ...] = (
    *G0_EVO_RESULT_DIRS,
    *ANALYSIS_OUTPUT_DIRS,
    *(directory / "figures" for directory in ANALYSIS_OUTPUT_DIRS),
)
EXACT_OUTCOME_EXCLUDED_FILES: Tuple[Path, ...] = (
    *(probe / filename for probe in G0_ACCURACY_PROBE_DIRS for filename in (
        "common_grid_audit.csv",
        "common_support_metrics.csv",
        "common_support_summary.json",
        "evo_crosscheck.json",
    )),
    Path("g0/evo_crosscheck.csv"),
    Path("g0/legacy_vs_corrected.csv"),
    Path("g0/g0_evaluator_validation.md"),
    *(Path("learned_specificity_20260803/analysis-output") / filename for filename in (
        "a03-replay-summary.csv",
        "analysis-report.md",
        "comparison-summary.csv",
        "figure-catalog.md",
        "ntnu-prefix-summary.csv",
        "ntnu-replay-summary.csv",
        "probe-summary.csv",
        "replay-metrics.csv",
        "stats-appendix.md",
        "figures/figure-01-matched-control-rpe.pdf",
        "figures/figure-01-matched-control-rpe.png",
        "figures/figure-02-a03-classical-control.pdf",
        "figures/figure-02-a03-classical-control.png",
        "figures/figure-03-ntnu-quality-interaction.pdf",
        "figures/figure-03-ntnu-quality-interaction.png",
    )),
    *(Path("ntnu_q_partition_20260805/analysis-output") / filename for filename in (
        "analysis-report.md",
        "factorial-summary.csv",
        "figure-catalog.md",
        "replay-metrics.csv",
        "stats-appendix.md",
        "figures/figure-01-quality-partition-replays.pdf",
        "figures/figure-01-quality-partition-replays.png",
        "figures/figure-02-gftt-birth-lineage.pdf",
        "figures/figure-02-gftt-birth-lineage.png",
    )),
)
KNOWN_NON_TEXT_EVIDENCE_SUFFIXES = {".bag", ".pdf", ".png"}
ACCURACY_GOVERNANCE_MARKERS = (
    "attestation",
    "audit",
    "checksum",
    "evidence",
    "intent",
    "lock",
    "manifest",
    "queue",
    "receipt",
    "registry",
    "resolution",
    "state",
)
ALLOWED_INACCESSIBLE_COMMS = {"(sd-pam)", "gnome-keyring-d", "ssh-agent"}
INACCESSIBLE_IDENTITY_FIELDS: Tuple[str, ...] = (
    "pid",
    "starttime_ticks",
    "ppid",
    "uid",
    "comm",
    "comm_sha256",
    "cmdline_sha256",
    "cgroup_sha256",
    "inaccessible_phases",
)

ALLOWED_ACTION = "unlink exact frozen downloader part files and empty dirs only"
FORBIDDEN_ACTIONS = [
    "modify or unlink canonical fjord_2.bag symlink or target",
    "modify any input/output/evidence artifact",
    "reclaim any other .parts or .incomplete cache",
    "inspect or evaluate trajectory/APE/RPE artifacts",
]
OUTCOME_BOUNDARY = "CAPACITY_RECOVERY_ONLY_NO_TRAJECTORY_OR_ACCURACY_EVIDENCE"
PREFREEZE_SCANNER_CLASSIFICATION_INCIDENT = {
    "status": "RECORDED_AND_CORRECTED_BEFORE_FORMAL_FREEZE",
    "incident": "automated bytes scan touched known development G0 evaluator outcome files before exact pre-read classification was added",
    "values_surfaced": False,
    "values_parsed_or_used": False,
    "p07_trajectory_artifacts_touched": False,
    "formal_lock_intent_receipt_were_absent": True,
    "correction": "known outcome paths/classes are now excluded before read; nearby governance remains scanned; unknown classes fail closed",
}
FORMAL_RELS: Tuple[Path, ...] = (LOCK_REL, INTENT_REL, RECEIPT_REL)
FORMAL_ACTION_LOCK_NAME = ".fjord2_parts_reclaim_publish_v1.lock"


class ReclaimViolation(RuntimeError):
    """A fail-closed violation of the fjord_2 reclaim contract."""


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=True, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def document_self_hash(document: Mapping[str, Any], field: str = SELF_HASH_FIELD) -> str:
    payload = dict(document)
    payload.pop(field, None)
    return sha256_bytes(canonical_json_bytes(payload))


def verify_document_self_hash(
    document: Mapping[str, Any], field: str = SELF_HASH_FIELD
) -> None:
    actual = document.get(field)
    expected = document_self_hash(document, field)
    if actual != expected:
        raise ReclaimViolation(
            f"self-hash mismatch: expected {expected}, observed {actual}"
        )


def _lexical_path(root: Path, relative: Path) -> Path:
    if relative.is_absolute() or ".." in relative.parts:
        raise ReclaimViolation(f"non-lexical project-relative path: {relative}")
    return root / relative


def _open_directory_chain(
    root: Path, relative: Path, *, create: bool = False
) -> Tuple[int, bool]:
    """Open a project-relative directory through anchored, no-follow dirfds."""

    if relative.is_absolute() or ".." in relative.parts:
        raise ReclaimViolation(f"unsafe directory chain: {relative}")
    flags = os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_NOFOLLOW", 0)
    try:
        current_fd = os.open(root, flags)
    except OSError as exc:
        raise ReclaimViolation(f"workspace root is not a direct directory: {root}: {exc}") from exc
    created_any = False
    try:
        components = relative.parts
        for index, component in enumerate(components):
            try:
                child_fd = os.open(component, flags, dir_fd=current_fd)
            except FileNotFoundError:
                if not create or index != len(components) - 1:
                    raise
                try:
                    os.mkdir(component, 0o775, dir_fd=current_fd)
                    os.fsync(current_fd)
                    created_any = True
                except FileExistsError:
                    # A concurrent creator is accepted only if the subsequent
                    # O_NOFOLLOW open proves it is a direct directory.
                    pass
                child_fd = os.open(component, flags, dir_fd=current_fd)
            except OSError as exc:
                raise ReclaimViolation(
                    f"formal directory component is not a direct directory: "
                    f"{relative}: {component}: {exc}"
                ) from exc
            child_st = os.fstat(child_fd)
            if not stat.S_ISDIR(child_st.st_mode):
                os.close(child_fd)
                raise ReclaimViolation(
                    f"formal directory component is not a directory: {component}"
                )
            os.close(current_fd)
            current_fd = child_fd
        return current_fd, created_any
    except Exception:
        os.close(current_fd)
        raise


def _entry_lstat_at(directory_fd: int, name: str) -> os.stat_result | None:
    try:
        return os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
    except FileNotFoundError:
        return None


def secure_path_lexists(root: Path, relative: Path) -> bool:
    try:
        parent_fd, _ = _open_directory_chain(root, relative.parent, create=False)
    except FileNotFoundError:
        return False
    try:
        return _entry_lstat_at(parent_fd, relative.name) is not None
    finally:
        os.close(parent_fd)


def assert_formal_artifacts_absent(root: Path) -> Dict[str, Any]:
    """Require all three formal evidence names absent without creating dirs."""

    parents = {relative.parent for relative in FORMAL_RELS}
    if len(parents) != 1:
        raise ReclaimViolation("formal evidence paths do not share one parent")
    parent_rel = next(iter(parents))
    try:
        parent_fd, _ = _open_directory_chain(root, parent_rel, create=False)
    except FileNotFoundError:
        return {
            "formal_parent_relative_path": parent_rel.as_posix(),
            "formal_parent_exists": False,
            "lock_intent_receipt_absent": True,
        }
    try:
        collisions = [
            relative.as_posix()
            for relative in FORMAL_RELS
            if _entry_lstat_at(parent_fd, relative.name) is not None
        ]
        if collisions:
            raise ReclaimViolation(
                f"formal lock/intent/receipt must all be absent: {collisions}"
            )
        return {
            "formal_parent_relative_path": parent_rel.as_posix(),
            "formal_parent_exists": True,
            "formal_parent_lstat": _stat_record(os.fstat(parent_fd)),
            "lock_intent_receipt_absent": True,
        }
    finally:
        os.close(parent_fd)


def secure_read_direct_json_at(
    parent_fd: int, name: str, label: str
) -> Dict[str, Any]:
    if "/" in name or name in ("", ".", ".."):
        raise ReclaimViolation(f"unsafe JSON basename for {label}: {name}")
    fd = -1
    try:
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
        try:
            fd = os.open(name, flags, dir_fd=parent_fd)
        except OSError as exc:
            raise ReclaimViolation(f"cannot securely open {label}: {name}: {exc}") from exc
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode):
            raise ReclaimViolation(f"{label} is not a direct regular file: {name}")
        chunks: List[bytes] = []
        while True:
            chunk = os.read(fd, 1024 * 1024)
            if not chunk:
                break
            chunks.append(chunk)
        try:
            value = json.loads(b"".join(chunks).decode("utf-8"))
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise ReclaimViolation(f"cannot decode {label}: {name}: {exc}") from exc
        if not isinstance(value, dict):
            raise ReclaimViolation(f"{label} is not a JSON object: {name}")
        return value
    finally:
        if fd >= 0:
            os.close(fd)


def secure_read_direct_json(root: Path, relative: Path, label: str) -> Dict[str, Any]:
    try:
        parent_fd, _ = _open_directory_chain(root, relative.parent, create=False)
    except FileNotFoundError as exc:
        raise ReclaimViolation(f"missing {label}: {relative}") from exc
    try:
        return secure_read_direct_json_at(parent_fd, relative.name, label)
    finally:
        os.close(parent_fd)


def _atomic_no_clobber_json_at(
    parent_fd: int, name: str, payload: Mapping[str, Any]
) -> Dict[str, int]:
    """Publish JSON via one anchored directory fd; never remove destination."""

    if "/" in name or name in ("", ".", ".."):
        raise ReclaimViolation(f"unsafe publication basename: {name}")
    if _entry_lstat_at(parent_fd, name) is not None:
        raise ReclaimViolation(f"no-clobber destination already exists: {name}")
    temp = f".{name}.tmp.{os.getpid()}.{secrets.token_hex(8)}"
    data = json.dumps(payload, ensure_ascii=True, sort_keys=True, indent=2).encode("utf-8") + b"\n"
    flags = (
        os.O_WRONLY
        | os.O_CREAT
        | os.O_EXCL
        | getattr(os, "O_NOFOLLOW", 0)
    )
    fd = os.open(temp, flags, 0o444, dir_fd=parent_fd)
    linked_identity: Tuple[int, int, int, int] | None = None
    try:
        offset = 0
        while offset < len(data):
            written = os.write(fd, data[offset:])
            if written <= 0:
                raise ReclaimViolation("zero-length write while publishing evidence")
            offset += written
        os.fsync(fd)
        os.close(fd)
        fd = -1
        try:
            os.link(
                temp,
                name,
                src_dir_fd=parent_fd,
                dst_dir_fd=parent_fd,
                follow_symlinks=False,
            )
        except FileExistsError as exc:
            # Never unlink name: it belongs to the winning publisher.
            raise ReclaimViolation(f"no-clobber publication race at {name}") from exc
        temp_st = os.stat(temp, dir_fd=parent_fd, follow_symlinks=False)
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
            raise ReclaimViolation(
                f"published destination identity mismatch after link: {name}"
            )
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
            os.unlink(temp, dir_fd=parent_fd)
            os.fsync(parent_fd)
        except FileNotFoundError:
            pass
    if linked_identity is None:
        raise ReclaimViolation(f"publication did not establish destination: {name}")
    final_st = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
    final_identity = (
        int(final_st.st_dev),
        int(final_st.st_ino),
        int(final_st.st_size),
        int(final_st.st_mode),
    )
    if final_identity != linked_identity or final_st.st_nlink != 1:
        raise ReclaimViolation(
            f"published destination changed after temp cleanup: {name}"
        )
    return _stat_record(final_st)


def _assert_publication_reachable(
    root: Path,
    relative: Path,
    anchored_parent_fd: int,
    destination_record: Mapping[str, Any],
) -> None:
    reopened_fd, _ = _open_directory_chain(root, relative.parent, create=False)
    try:
        anchored_parent = os.fstat(anchored_parent_fd)
        reopened_parent = os.fstat(reopened_fd)
        if (anchored_parent.st_dev, anchored_parent.st_ino) != (
            reopened_parent.st_dev,
            reopened_parent.st_ino,
        ):
            raise ReclaimViolation(
                "formal parent was renamed or swapped during publication"
            )
        observed = _entry_lstat_at(reopened_fd, relative.name)
        if observed is None or _stat_record(observed) != dict(destination_record):
            raise ReclaimViolation(
                f"formal publication is not reachable with exact identity: {relative}"
            )
    finally:
        os.close(reopened_fd)


def atomic_no_clobber_json_at_formal_parent(
    root: Path,
    parent_fd: int,
    relative: Path,
    payload: Mapping[str, Any],
) -> Dict[str, int]:
    if relative.parent != LOCK_REL.parent:
        raise ReclaimViolation(f"unexpected formal parent for publication: {relative}")
    record = _atomic_no_clobber_json_at(parent_fd, relative.name, payload)
    _assert_publication_reachable(root, relative, parent_fd, record)
    return record


def atomic_no_clobber_json(
    root: Path, relative: Path, payload: Mapping[str, Any], *, create_parent: bool = False
) -> None:
    parent_fd, _ = _open_directory_chain(root, relative.parent, create=create_parent)
    try:
        record = _atomic_no_clobber_json_at(parent_fd, relative.name, payload)
        _assert_publication_reachable(root, relative, parent_fd, record)
    finally:
        os.close(parent_fd)


def write_formal_lock(root: Path, payload: Mapping[str, Any]) -> None:
    """Publish the lock only while all three formal names remain absent."""

    validate_lock_semantics(root, payload)
    parent_fd, _ = _open_directory_chain(root, LOCK_REL.parent, create=True)
    action_fd = -1
    try:
        existed = _entry_lstat_at(parent_fd, FORMAL_ACTION_LOCK_NAME) is not None
        flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0)
        action_fd = os.open(FORMAL_ACTION_LOCK_NAME, flags, 0o600, dir_fd=parent_fd)
        if not stat.S_ISREG(os.fstat(action_fd).st_mode):
            raise ReclaimViolation("formal publication lock is not a direct regular file")
        if not existed:
            os.fsync(parent_fd)
        fcntl.flock(action_fd, fcntl.LOCK_EX)
        collisions = [
            relative.as_posix()
            for relative in FORMAL_RELS
            if _entry_lstat_at(parent_fd, relative.name) is not None
        ]
        if collisions:
            raise ReclaimViolation(
                f"formal lock/intent/receipt must all be absent at write: {collisions}"
            )
        atomic_no_clobber_json_at_formal_parent(
            root, parent_fd, LOCK_REL, payload
        )
    finally:
        if action_fd >= 0:
            try:
                fcntl.flock(action_fd, fcntl.LOCK_UN)
            finally:
                os.close(action_fd)
        os.close(parent_fd)


def _stat_record(st: os.stat_result) -> Dict[str, int]:
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


def regular_file_record(path: Path, label: str) -> Dict[str, Any]:
    try:
        st = path.lstat()
    except FileNotFoundError as exc:
        raise ReclaimViolation(f"missing {label}: {path}") from exc
    if not stat.S_ISREG(st.st_mode):
        raise ReclaimViolation(f"{label} is not a direct regular file: {path}")
    record: Dict[str, Any] = _stat_record(st)
    record["sha256"] = sha256_file(path)
    return record


def directory_record(path: Path, label: str) -> Dict[str, Any]:
    try:
        st = path.lstat()
    except FileNotFoundError as exc:
        raise ReclaimViolation(f"missing {label}: {path}") from exc
    if not stat.S_ISDIR(st.st_mode):
        raise ReclaimViolation(f"{label} is not a direct directory: {path}")
    return _stat_record(st)


def symlink_contract(path: Path, label: str) -> Dict[str, Any]:
    try:
        link_st = path.lstat()
    except FileNotFoundError as exc:
        raise ReclaimViolation(f"missing {label}: {path}") from exc
    if not stat.S_ISLNK(link_st.st_mode):
        raise ReclaimViolation(f"{label} is not a symlink: {path}")
    link_text = os.readlink(path)
    target = path.resolve(strict=True)
    target_st = target.lstat()
    if not stat.S_ISREG(target_st.st_mode) and label != "datasets mount symlink":
        raise ReclaimViolation(f"{label} target is not a direct regular file: {target}")
    if label == "datasets mount symlink" and not stat.S_ISDIR(target_st.st_mode):
        raise ReclaimViolation(f"datasets symlink target is not a directory: {target}")
    return {
        "workspace_path": str(path),
        "link_text": link_text,
        "link_lstat": _stat_record(link_st),
        "resolved_target": str(target),
        "target_lstat": _stat_record(target_st),
    }


def collect_parts_inventory(root: Path) -> Dict[str, Any]:
    candidate = _lexical_path(root, CANDIDATE_REL)
    part_root = _lexical_path(root, PART_ROOT_REL)

    candidate_dir = directory_record(candidate, "fjord_2 .parts candidate")
    part_dir = directory_record(part_root, "fjord_2 part root")

    try:
        candidate_children = sorted(entry.name for entry in os.scandir(candidate))
    except OSError as exc:
        raise ReclaimViolation(f"cannot enumerate candidate: {candidate}: {exc}") from exc
    if candidate_children != ["fjord_2.bag"]:
        raise ReclaimViolation(
            "candidate has unexpected children; expected only fjord_2.bag, observed "
            f"{candidate_children}"
        )

    records: List[Dict[str, Any]] = []
    try:
        entries = sorted(os.scandir(part_root), key=lambda entry: entry.name)
    except OSError as exc:
        raise ReclaimViolation(f"cannot enumerate part root: {part_root}: {exc}") from exc
    if not entries:
        raise ReclaimViolation("fjord_2 part inventory is empty")
    if len(entries) != EXPECTED_PART_COUNT:
        raise ReclaimViolation(
            "fjord_2 exact part-count mismatch: "
            f"{len(entries)} != {EXPECTED_PART_COUNT}"
        )

    expected_start = 0
    for expected_index, entry in enumerate(entries):
        match = PART_RE.fullmatch(entry.name)
        if match is None:
            raise ReclaimViolation(f"unexpected part entry name: {entry.name}")
        index, start, end = (int(value) for value in match.groups())
        if index != expected_index:
            raise ReclaimViolation(
                f"part index discontinuity: expected {expected_index}, observed {index}"
            )
        if start != expected_start or end < start:
            raise ReclaimViolation(
                f"part range discontinuity at {entry.name}: expected start "
                f"{expected_start}, observed {start}-{end}"
            )
        st = entry.stat(follow_symlinks=False)
        if not stat.S_ISREG(st.st_mode):
            raise ReclaimViolation(f"part is not a direct regular file: {entry.path}")
        if st.st_nlink != 1:
            raise ReclaimViolation(
                f"part link count is not one: {entry.path}: {st.st_nlink}"
            )
        expected_size = end - start + 1
        if st.st_size != expected_size:
            raise ReclaimViolation(
                f"part size/range mismatch: {entry.path}: {st.st_size} != {expected_size}"
            )
        record: Dict[str, Any] = {
            "name": entry.name,
            "relative_path": (PART_ROOT_REL / entry.name).as_posix(),
            "index": index,
            "range_start": start,
            "range_end": end,
        }
        record.update(_stat_record(st))
        records.append(record)
        expected_start = end + 1

    logical_bytes = sum(int(record["size_bytes"]) for record in records)
    if expected_start != logical_bytes:
        raise ReclaimViolation(
            f"range terminus/logical-byte mismatch: {expected_start} != {logical_bytes}"
        )
    if logical_bytes != EXPECTED_SIZE:
        raise ReclaimViolation(
            f"fjord_2 parts total mismatch: {logical_bytes} != {EXPECTED_SIZE}"
        )

    allocated_file_bytes = sum(
        int(record["allocated_bytes"]) for record in records
    )
    allocated_tree_bytes = (
        allocated_file_bytes
        + int(candidate_dir["allocated_bytes"])
        + int(part_dir["allocated_bytes"])
    )
    inventory_hash = sha256_bytes(canonical_json_bytes(records))
    return {
        "candidate_relative_path": CANDIDATE_REL.as_posix(),
        "part_root_relative_path": PART_ROOT_REL.as_posix(),
        "candidate_lstat": candidate_dir,
        "part_root_lstat": part_dir,
        "part_count": len(records),
        "logical_bytes": logical_bytes,
        "allocated_file_bytes": allocated_file_bytes,
        "allocated_tree_bytes": allocated_tree_bytes,
        "range_start": 0,
        "range_end": expected_start - 1,
        "inventory_hash": inventory_hash,
        "parts": records,
    }


def _read_csv(path: Path) -> Tuple[List[str], List[Dict[str, str]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as stream:
            reader = csv.DictReader(stream)
            if reader.fieldnames is None:
                raise ReclaimViolation(f"CSV has no header: {path}")
            rows = [dict(row) for row in reader]
            return list(reader.fieldnames), rows
    except (OSError, UnicodeError, csv.Error) as exc:
        raise ReclaimViolation(f"cannot read CSV {path}: {exc}") from exc


def _one_row(rows: Iterable[Dict[str, str]], label: str) -> Dict[str, str]:
    selected = list(rows)
    if len(selected) != 1:
        raise ReclaimViolation(f"expected one {label} row, observed {len(selected)}")
    return selected[0]


def collect_checksum_bindings(root: Path) -> Dict[str, Any]:
    canonical = CANONICAL_REL.as_posix()
    result: Dict[str, Any] = {}

    checksum_path = _lexical_path(root, CHECKSUM_REL)
    checksum_header, checksum_rows = _read_csv(checksum_path)
    checksum_row = _one_row(
        (
            row
            for row in checksum_rows
            if row.get("artifact_role") == "raw_input"
            and row.get("dataset_family") == "ntnu"
            and row.get("sequence") == "fjord_2"
            and row.get("path") == canonical
        ),
        "fjord_2 raw-input checksum",
    )
    expected_checksum_fields = {
        "checksum_schema": "isj-input-reference-checksum-v1",
        "size_bytes": str(EXPECTED_SIZE),
        "algorithm": "SHA-256",
        "digest": EXPECTED_SHA256,
        "digest_origin": "official_HuggingFace_LFS_SHA256",
        "local_size_verified": "true",
        "status": "PASS",
    }
    for field, expected in expected_checksum_fields.items():
        if checksum_row.get(field) != expected:
            raise ReclaimViolation(
                f"checksum row {field} mismatch: {checksum_row.get(field)!r} != {expected!r}"
            )
    result["input_reference_checksum"] = {
        "relative_path": CHECKSUM_REL.as_posix(),
        "header": checksum_header,
        "row": checksum_row,
        "artifact": regular_file_record(checksum_path, "checksum manifest"),
    }

    eligibility_path = _lexical_path(root, ELIGIBILITY_REL)
    eligibility_header, eligibility_rows = _read_csv(eligibility_path)
    eligibility_row = _one_row(
        (
            row
            for row in eligibility_rows
            if row.get("dataset_family") == "ntnu"
            and row.get("sequence") == "fjord_2"
            and row.get("raw_input_path") == canonical
        ),
        "fjord_2 eligibility",
    )
    for field, expected in {
        "manifest_schema": "isj-data-eligibility-v1",
        "raw_exists": "true",
        "raw_size_bytes": str(EXPECTED_SIZE),
        "expected_raw_size_bytes": str(EXPECTED_SIZE),
        "raw_integrity": "SIZE_MATCH",
    }.items():
        if eligibility_row.get(field) != expected:
            raise ReclaimViolation(
                f"eligibility row {field} mismatch: "
                f"{eligibility_row.get(field)!r} != {expected!r}"
            )
    result["data_eligibility"] = {
        "relative_path": ELIGIBILITY_REL.as_posix(),
        "header": eligibility_header,
        "row": eligibility_row,
        "artifact": regular_file_record(eligibility_path, "eligibility manifest"),
    }

    audit_path = _lexical_path(root, REFERENCE_AUDIT_REL)
    audit_header, audit_rows = _read_csv(audit_path)
    audit_row = _one_row(
        (
            row
            for row in audit_rows
            if row.get("dataset_family") == "ntnu"
            and row.get("sequence") == "fjord_2"
            and row.get("raw_input_path") == canonical
        ),
        "fjord_2 reference audit",
    )
    for field, expected in {
        "audit_schema": "isj-reference-audit-v1",
        "raw_exists": "true",
        "raw_size_bytes": str(EXPECTED_SIZE),
        "raw_integrity": "SIZE_MATCH",
    }.items():
        if audit_row.get(field) != expected:
            raise ReclaimViolation(
                f"reference-audit row {field} mismatch: "
                f"{audit_row.get(field)!r} != {expected!r}"
            )
    result["reference_audit"] = {
        "relative_path": REFERENCE_AUDIT_REL.as_posix(),
        "header": audit_header,
        "row": audit_row,
        "artifact": regular_file_record(audit_path, "reference audit"),
    }
    return result


def collect_canonical_contract(root: Path) -> Dict[str, Any]:
    datasets_link = symlink_contract(
        _lexical_path(root, DATASETS_LINK_REL), "datasets mount symlink"
    )
    canonical_link = symlink_contract(
        _lexical_path(root, CANONICAL_REL), "canonical fjord_2 symlink"
    )
    target_size = int(canonical_link["target_lstat"]["size_bytes"])
    if target_size != EXPECTED_SIZE:
        raise ReclaimViolation(
            f"canonical fjord_2 target size mismatch: {target_size} != {EXPECTED_SIZE}"
        )
    return {
        "datasets_mount": datasets_link,
        "canonical_relative_path": CANONICAL_REL.as_posix(),
        "canonical_symlink": canonical_link,
        "expected_size_bytes": EXPECTED_SIZE,
        "official_sha256": EXPECTED_SHA256,
        "content_sha256_recomputed_for_reclaim": False,
        "checksum_authority": CHECKSUM_REL.as_posix(),
    }


def collect_frozen_artifacts(root: Path) -> Dict[str, Any]:
    records: Dict[str, Any] = {}
    for relative in TOOL_RELS:
        records[relative.as_posix()] = regular_file_record(
            _lexical_path(root, relative), f"frozen tool {relative}"
        )
    return records


def _under_relative(path: Path, ancestor: Path) -> bool:
    try:
        path.relative_to(ancestor)
        return True
    except ValueError:
        return False


def _accuracy_path_class(relative: Path, *, is_directory: bool) -> str:
    """Return EXACT_EXCLUDED, SUSPECT_UNALLOWLISTED, or NON_ACCURACY."""

    if not is_directory and relative in EXACT_OUTCOME_EXCLUDED_FILES:
        return "EXACT_EXCLUDED"

    if is_directory and relative in CLASSIFIED_OUTCOME_CONTAINER_DIRS:
        return "NON_ACCURACY"

    evo_parent = next(
        (directory for directory in G0_EVO_RESULT_DIRS if _under_relative(relative, directory)),
        None,
    )
    if evo_parent is not None:
        if is_directory:
            return "SUSPECT_UNALLOWLISTED"
        basename = relative.name.lower()
        generated_evo_result = re.fullmatch(
            r"(?:reference_common|reference_segment_\d{3}|"
            r"[a-z0-9_-]+_common_aligned|[a-z0-9_-]+_segment_\d{3})\.tum|"
            r"[a-z0-9_-]+_evo_ape\.log|"
            r"[a-z0-9_-]+_evo_rpe_segment_\d{3}\.log",
            basename,
        )
        if generated_evo_result is not None:
            return "EXACT_EXCLUDED"
        if any(marker in basename for marker in ACCURACY_GOVERNANCE_MARKERS):
            return "NON_ACCURACY"
        return "SUSPECT_UNALLOWLISTED"

    analysis_parent = next(
        (directory for directory in ANALYSIS_OUTPUT_DIRS if _under_relative(relative, directory)),
        None,
    )
    if analysis_parent is not None:
        if is_directory:
            return "SUSPECT_UNALLOWLISTED"
        basename = relative.name.lower()
        if any(marker in basename for marker in ACCURACY_GOVERNANCE_MARKERS):
            return "NON_ACCURACY"
        return "SUSPECT_UNALLOWLISTED"

    components = [component.lower() for component in relative.parts]
    basename = components[-1] if components else ""
    suspected = (
        basename.endswith(".tum")
        or any(
            component in {
                "analysis-output",
                "ape",
                "evo_crosscheck",
                "rpe",
                "trajectories",
                "trajectory",
            }
            for component in components
        )
        or re.search(r"(^|[_.-])(ape|rpe|evo|trajectory|groundtruth)([_.-]|$)", basename)
        is not None
    )
    if not suspected:
        return "NON_ACCURACY"
    if not is_directory and any(marker in basename for marker in ACCURACY_GOVERNANCE_MARKERS):
        # Governance about an accuracy artifact is text evidence, not the
        # trajectory/APE/RPE payload itself, and must still be reference-scanned.
        return "NON_ACCURACY"
    return "SUSPECT_UNALLOWLISTED"


def scan_evidence_references(
    root: Path, parts_inventory: Mapping[str, Any]
) -> Dict[str, Any]:
    scan_root = _lexical_path(root, EVIDENCE_SCAN_REL)
    excluded_exact = {relative.as_posix() for relative in FORMAL_RELS}
    patterns = [
        CANDIDATE_REL.as_posix().encode("utf-8"),
        PART_ROOT_REL.as_posix().encode("utf-8"),
        b"subset-fjord/fjord_2/.parts",
    ]
    exact_part_names = {str(record["name"]) for record in parts_inventory["parts"]}
    part_name_pattern = re.compile(rb"part_\d{5}_\d+_\d+")
    inventory: List[Dict[str, Any]] = []
    matches: List[Dict[str, Any]] = []
    excluded_outcomes_seen: List[str] = []
    classified_non_text_seen: List[str] = []
    bytes_scanned = 0

    directory_record(scan_root, "evidence scan root")

    def walk_error(error: OSError) -> None:
        raise ReclaimViolation(f"cannot exhaustively walk evidence: {error}")

    for dirpath_text, dirnames, filenames in os.walk(
        scan_root, topdown=True, followlinks=False, onerror=walk_error
    ):
        dirpath = Path(dirpath_text)
        retained_dirs: List[str] = []
        for dirname in sorted(dirnames):
            child = dirpath / dirname
            relative_scan = child.relative_to(scan_root)
            accuracy_class = _accuracy_path_class(relative_scan, is_directory=True)
            if accuracy_class == "EXACT_EXCLUDED":
                continue
            if accuracy_class == "SUSPECT_UNALLOWLISTED":
                raise ReclaimViolation(
                    "unallowlisted accuracy/trajectory directory requires new governance: "
                    f"{relative_scan.as_posix()}"
                )
            try:
                child_st = child.lstat()
            except OSError as exc:
                raise ReclaimViolation(
                    f"cannot lstat relevant evidence directory {child}: {exc}"
                ) from exc
            if stat.S_ISLNK(child_st.st_mode):
                raise ReclaimViolation(
                    f"relevant evidence directory is a symlink: {child}"
                )
            if not stat.S_ISDIR(child_st.st_mode):
                raise ReclaimViolation(
                    f"relevant evidence directory is not direct: {child}"
                )
            retained_dirs.append(dirname)
        dirnames[:] = retained_dirs

        for filename in sorted(filenames):
            path = dirpath / filename
            rel = path.relative_to(root).as_posix()
            if rel in excluded_exact:
                continue
            relative_scan = path.relative_to(scan_root)
            accuracy_class = _accuracy_path_class(relative_scan, is_directory=False)
            if accuracy_class == "EXACT_EXCLUDED":
                excluded_outcomes_seen.append(relative_scan.as_posix())
                continue
            if accuracy_class == "SUSPECT_UNALLOWLISTED":
                raise ReclaimViolation(
                    "unallowlisted accuracy/trajectory file requires new governance: "
                    f"{relative_scan.as_posix()}"
                )
            if path.suffix and path.suffix.lower() not in TEXT_EVIDENCE_SUFFIXES:
                if path.suffix.lower() in KNOWN_NON_TEXT_EVIDENCE_SUFFIXES:
                    classified_non_text_seen.append(relative_scan.as_posix())
                    continue
                raise ReclaimViolation(
                    "unclassified evidence file type requires new governance before read: "
                    f"{relative_scan.as_posix()}"
                )
            try:
                st = path.lstat()
            except OSError as exc:
                raise ReclaimViolation(
                    f"cannot lstat relevant evidence file {path}: {exc}"
                ) from exc
            if stat.S_ISLNK(st.st_mode):
                raise ReclaimViolation(f"relevant evidence file is a symlink: {path}")
            if not stat.S_ISREG(st.st_mode):
                raise ReclaimViolation(
                    f"relevant evidence path is not a direct regular file: {path}"
                )
            try:
                payload = path.read_bytes()
            except OSError as exc:
                raise ReclaimViolation(f"cannot scan evidence file {path}: {exc}") from exc
            try:
                post_st = path.lstat()
            except OSError as exc:
                raise ReclaimViolation(
                    f"evidence file vanished during scan {path}: {exc}"
                ) from exc
            if _stat_record(post_st) != _stat_record(st):
                raise ReclaimViolation(f"evidence file drifted during scan: {path}")
            file_record = {
                "relative_path": rel,
                "size_bytes": len(payload),
                "sha256": sha256_bytes(payload),
            }
            inventory.append(file_record)
            bytes_scanned += len(payload)
            for pattern in patterns:
                if pattern in payload:
                    matches.append(
                        {"relative_path": rel, "pattern": pattern.decode("utf-8")}
                    )
            observed_part_names = {
                match.group(0).decode("ascii") for match in part_name_pattern.finditer(payload)
            }
            for part_name in sorted(observed_part_names & exact_part_names):
                matches.append(
                    {"relative_path": rel, "pattern": f"exact-part-basename:{part_name}"}
                )

    # os.walk can expose a top-level file that vanishes between listing and
    # lstat; every such relevant race above is a hard failure.
    if matches:
        raise ReclaimViolation(f"candidate is referenced by evidence: {matches}")
    return {
        "scan_root": EVIDENCE_SCAN_REL.as_posix(),
        "excluded_exact_paths": sorted(excluded_exact),
        "accuracy_exclusion": {
            "classified_container_directories": sorted(
                relative.as_posix() for relative in CLASSIFIED_OUTCOME_CONTAINER_DIRS
            ),
            "exact_files": sorted(
                relative.as_posix() for relative in EXACT_OUTCOME_EXCLUDED_FILES
            ),
            "g0_evo_generated_filename_class": "TUM/log names emitted by evaluate_vins_common_support.py",
            "unallowlisted_accuracy_candidate_policy": "FAIL_CLOSED_WITHOUT_READING",
        },
        "excluded_outcome_files_seen": sorted(excluded_outcomes_seen),
        "known_non_text_suffixes": sorted(KNOWN_NON_TEXT_EVIDENCE_SUFFIXES),
        "classified_non_text_files_seen": sorted(classified_non_text_seen),
        "unknown_file_type_policy": "FAIL_CLOSED_WITHOUT_READING",
        "patterns": [pattern.decode("utf-8") for pattern in patterns],
        "exact_part_basename_count": len(exact_part_names),
        "part_basename_inventory_hash": sha256_bytes(
            canonical_json_bytes(sorted(exact_part_names))
        ),
        "files_scanned": len(inventory),
        "bytes_scanned": bytes_scanned,
        "scan_inventory_hash": sha256_bytes(canonical_json_bytes(inventory)),
        "matches": [],
    }


def _proc_identity_exception(
    proc: Path, pid: int, effective_uid: int, phases: Iterable[str]
) -> Dict[str, Any]:
    """Build the exact identity tuple for one allowlisted inaccessible process."""

    try:
        stat_payload = (proc / "stat").read_bytes()
        close_paren = stat_payload.rfind(b")")
        if close_paren < 0:
            raise ReclaimViolation(f"malformed /proc stat for PID {pid}")
        fields = stat_payload[close_paren + 2 :].split()
        if len(fields) <= 19:
            raise ReclaimViolation(f"short /proc stat for PID {pid}")
        ppid = int(fields[1])
        starttime = int(fields[19])
        comm_payload = (proc / "comm").read_bytes()
        comm = comm_payload.decode("utf-8", "strict").rstrip("\n")
        cmdline_payload = (proc / "cmdline").read_bytes()
        cgroup_payload = (proc / "cgroup").read_bytes()
        status_payload = (proc / "status").read_text(encoding="utf-8")
    except (OSError, UnicodeError, ValueError) as exc:
        raise ReclaimViolation(
            f"cannot freeze inaccessible same-UID process identity PID {pid}: {exc}"
        ) from exc

    status: Dict[str, str] = {}
    for line in status_payload.splitlines():
        if ":" in line:
            key, value = line.split(":", 1)
            status[key] = value.strip()
    try:
        status_ppid = int(status["PPid"].split()[0])
        uids = [int(value) for value in status["Uid"].split()]
    except (KeyError, ValueError, IndexError) as exc:
        raise ReclaimViolation(f"malformed status identity for PID {pid}") from exc
    if status_ppid != ppid:
        raise ReclaimViolation(f"PPID drift while freezing PID {pid}")
    if not uids or any(uid != effective_uid for uid in uids):
        raise ReclaimViolation(
            f"inaccessible process PID {pid} is not exact UID {effective_uid}: {uids}"
        )
    if comm not in ALLOWED_INACCESSIBLE_COMMS:
        raise ReclaimViolation(
            f"inaccessible same-UID process is not allowlisted: PID {pid} comm={comm!r}"
        )
    return {
        "pid": pid,
        "starttime_ticks": starttime,
        "ppid": ppid,
        "uid": effective_uid,
        "comm": comm,
        "comm_sha256": sha256_bytes(comm_payload),
        "cmdline_sha256": sha256_bytes(cmdline_payload),
        "cgroup_sha256": sha256_bytes(cgroup_payload),
        "inaccessible_phases": sorted(set(phases)),
    }


def inspect_quiescence(root: Path, inventory: Mapping[str, Any]) -> Dict[str, Any]:
    """Require no same-user process to hold or download the exact candidate."""

    target_ids = {
        (int(record["dev"]), int(record["inode"]))
        for record in inventory["parts"]
    }
    target_ids.add(
        (
            int(inventory["candidate_lstat"]["dev"]),
            int(inventory["candidate_lstat"]["inode"]),
        )
    )
    target_ids.add(
        (
            int(inventory["part_root_lstat"]["dev"]),
            int(inventory["part_root_lstat"]["inode"]),
        )
    )

    candidate_texts = {
        str(_lexical_path(root, CANDIDATE_REL)),
        str(_lexical_path(root, PART_ROOT_REL)),
        str(_lexical_path(root, CANDIDATE_REL).resolve(strict=True)),
        str(_lexical_path(root, PART_ROOT_REL).resolve(strict=True)),
    }
    active: List[Dict[str, Any]] = []
    inaccessible_phases: Dict[int, set[str]] = {}
    inspected = 0
    proc_root = Path("/proc")
    current_pid = os.getpid()
    effective_uid = os.geteuid()

    for proc in sorted(
        (path for path in proc_root.iterdir() if path.name.isdigit()),
        key=lambda value: int(value.name),
    ):
        pid = int(proc.name)
        if pid == current_pid:
            continue
        try:
            if proc.stat().st_uid != effective_uid:
                continue
        except FileNotFoundError:
            continue
        except PermissionError as exc:
            raise ReclaimViolation(f"cannot identify process UID for PID {pid}: {exc}") from exc
        inspected += 1
        try:
            cmd_bytes = (proc / "cmdline").read_bytes()
            cmdline = cmd_bytes.replace(b"\0", b" ").decode("utf-8", "replace").strip()
        except FileNotFoundError:
            continue
        except PermissionError as exc:
            inaccessible_phases.setdefault(pid, set()).add("cmdline")
            continue

        lower = cmdline.lower()
        exact_path_hit = any(text in cmdline for text in candidate_texts)
        aqua_downloader = "download_hf_mirror_dataset.py" in lower
        generic_downloader = any(
            token in lower
            for token in ("huggingface", "hf_hub", "aria2", "wget", "curl")
        ) and any(token in lower for token in ("fjord_2", "ntnu_hf", str(root).lower()))
        if exact_path_hit or aqua_downloader or generic_downloader:
            active.append(
                {
                    "pid": pid,
                    "reason": "candidate/downloader command line",
                    "cmdline": cmdline,
                }
            )

        fd_root = proc / "fd"
        try:
            fds = list(fd_root.iterdir())
        except FileNotFoundError:
            continue
        except PermissionError:
            inaccessible_phases.setdefault(pid, set()).add("fd-list")
            continue
        for fd in fds:
            try:
                st = fd.stat()
            except FileNotFoundError:
                continue
            except PermissionError:
                inaccessible_phases.setdefault(pid, set()).add(f"fd-stat:{fd.name}")
                continue
            if (int(st.st_dev), int(st.st_ino)) in target_ids:
                try:
                    target_text = os.readlink(fd)
                except OSError:
                    target_text = "<unreadable>"
                active.append(
                    {
                        "pid": pid,
                        "reason": "open candidate inode",
                        "fd": fd.name,
                        "target": target_text,
                        "cmdline": cmdline,
                    }
                )

    if active:
        raise ReclaimViolation(f"candidate is live or downloader is active: {active}")

    exceptions = [
        _proc_identity_exception(proc_root / str(pid), pid, effective_uid, phases)
        for pid, phases in sorted(inaccessible_phases.items())
    ]
    observed_exception_comms = sorted(item["comm"] for item in exceptions)
    expected_exception_comms = sorted(ALLOWED_INACCESSIBLE_COMMS)
    if observed_exception_comms != expected_exception_comms:
        raise ReclaimViolation(
            "inaccessible same-UID exception comm set mismatch: "
            f"{observed_exception_comms} != {expected_exception_comms}"
        )
    try:
        boot_id_payload = Path("/proc/sys/kernel/random/boot_id").read_bytes()
    except OSError as exc:
        raise ReclaimViolation(f"cannot bind boot identity: {exc}") from exc

    # hidepid/AppArmor can make a few same-UID fd directories unreadable.  Use
    # the same exact-tree lsof check used by the capacity audit as a second,
    # independent open-file guard.  Absence of lsof or an abnormal/timeout
    # result is a fail-closed violation.
    candidate = _lexical_path(root, CANDIDATE_REL)
    try:
        lsof = subprocess.run(
            ["lsof", "-nP", "+D", str(candidate)],
            check=False,
            capture_output=True,
            text=True,
            timeout=60,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ReclaimViolation(f"exact-tree lsof inspection failed: {exc}") from exc
    if lsof.returncode not in (0, 1):
        raise ReclaimViolation(
            "exact-tree lsof inspection returned abnormal status "
            f"{lsof.returncode}: {lsof.stderr.strip()}"
        )
    lsof_lines = [line for line in lsof.stdout.splitlines() if line.strip()]
    if lsof.returncode == 0 or lsof_lines:
        raise ReclaimViolation(
            f"exact-tree lsof found open candidate paths: {lsof_lines}"
        )
    return {
        "effective_uid": effective_uid,
        "same_user_processes_inspected": inspected,
        "active_matches": [],
        "inspection_errors": [],
        "inaccessible_process_exceptions": exceptions,
        "boot_id_sha256": sha256_bytes(boot_id_payload),
        "inaccessible_exception_policy": {
            "allowed_comms": sorted(ALLOWED_INACCESSIBLE_COMMS),
            "identity_fields": list(INACCESSIBLE_IDENTITY_FIELDS),
            "executor_requires_exact_frozen_tuple_set": True,
        },
        "lsof_exact_tree_exit_code": lsof.returncode,
        "lsof_exact_tree_stdout_lines": [],
        "lsof_warnings": [
            line for line in lsof.stderr.splitlines() if line.strip()
        ],
    }


def collect_current_state(root: Path) -> Dict[str, Any]:
    root = root.absolute()
    inventory = collect_parts_inventory(root)
    return {
        "inventory": inventory,
        "canonical_contract": collect_canonical_contract(root),
        "checksum_bindings": collect_checksum_bindings(root),
        "frozen_artifacts": collect_frozen_artifacts(root),
        "zero_reference_scan": scan_evidence_references(root, inventory),
        "quiescence": inspect_quiescence(root, inventory),
    }


def expected_scope() -> Dict[str, Any]:
    return {
        "dataset": "ntnu/fjord_2",
        "candidate_relative_path": CANDIDATE_REL.as_posix(),
        "allowed_action": ALLOWED_ACTION,
        "forbidden_actions": list(FORBIDDEN_ACTIONS),
    }


def expected_formal_paths() -> Dict[str, str]:
    return {
        "lock": LOCK_REL.as_posix(),
        "intent": INTENT_REL.as_posix(),
        "receipt": RECEIPT_REL.as_posix(),
    }


def expected_execution_contract(inventory: Mapping[str, Any]) -> Dict[str, Any]:
    return {
        "default_mode": "READ_ONLY_PREFLIGHT",
        "mutation_flag": "--execute",
        "require_exact_lock_self_hash": True,
        "require_exact_lock_semantics": True,
        "require_exact_frozen_tool_hashes": True,
        "require_exact_frozen_inaccessible_process_tuples": True,
        "require_zero_references_and_open_downloaders": True,
        "require_revalidation_immediately_before_each_unlink": True,
        "require_durable_no_clobber_intent_before_unlink": True,
        "require_durable_no_clobber_pass_receipt_after_postcondition": True,
        "require_hardened_dirfd_no_follow_formal_io": True,
        "crash_policy": "intent_without_PASS_receipt blocks automatic retry",
        "postconditions": {
            "candidate_absent": True,
            "exact_part_count": EXPECTED_PART_COUNT,
            "exact_logical_bytes": EXPECTED_SIZE,
            "exact_allocated_file_bytes": inventory["allocated_file_bytes"],
            "exact_inventory_hash": inventory["inventory_hash"],
            "canonical_contract_unchanged": True,
            "checksum_bindings_unchanged": True,
            "frozen_artifacts_unchanged": True,
        },
    }


def validate_lock_semantics(root: Path, lock: Mapping[str, Any]) -> None:
    """Validate immutable meaning, even if an attacker recomputes self-hash."""

    expected_top = {
        "schema",
        "status",
        "generated_at_utc",
        "workspace_root",
        "scope",
        "formal_paths",
        "formal_precondition",
        "frozen_state",
        "execution_contract",
        "outcome_boundary",
        "pre_freeze_dry_run_scanner_classification_incident",
        SELF_HASH_FIELD,
    }
    if set(lock) != expected_top:
        raise ReclaimViolation(
            f"lock top-level semantic keys mismatch: {sorted(set(lock) ^ expected_top)}"
        )
    if lock.get("schema") != LOCK_SCHEMA or lock.get("status") != LOCK_STATUS:
        raise ReclaimViolation("lock schema/status semantic mismatch")
    if lock.get("workspace_root") != str(root.absolute()):
        raise ReclaimViolation("lock workspace-root semantic mismatch")
    if lock.get("scope") != expected_scope():
        raise ReclaimViolation("lock scope/action semantic mismatch")
    if lock.get("formal_paths") != expected_formal_paths():
        raise ReclaimViolation("lock formal-path semantic mismatch")
    if lock.get("outcome_boundary") != OUTCOME_BOUNDARY:
        raise ReclaimViolation("lock outcome-boundary semantic mismatch")
    if lock.get("pre_freeze_dry_run_scanner_classification_incident") != (
        PREFREEZE_SCANNER_CLASSIFICATION_INCIDENT
    ):
        raise ReclaimViolation("lock scanner-classification incident semantic mismatch")
    precondition = lock.get("formal_precondition")
    if not isinstance(precondition, dict) or precondition.get(
        "lock_intent_receipt_absent"
    ) is not True:
        raise ReclaimViolation("lock formal-absence precondition semantic mismatch")
    try:
        generated = dt.datetime.fromisoformat(str(lock["generated_at_utc"]))
    except (ValueError, TypeError) as exc:
        raise ReclaimViolation("lock generated_at_utc is invalid") from exc
    if generated.tzinfo is None:
        raise ReclaimViolation("lock generated_at_utc is not timezone-aware")

    frozen = lock.get("frozen_state")
    expected_frozen_keys = {
        "inventory",
        "canonical_contract",
        "checksum_bindings",
        "frozen_artifacts",
        "zero_reference_scan",
        "quiescence",
    }
    if not isinstance(frozen, dict) or set(frozen) != expected_frozen_keys:
        raise ReclaimViolation("lock frozen-state semantic keys mismatch")
    inventory = frozen["inventory"]
    if inventory.get("candidate_relative_path") != CANDIDATE_REL.as_posix():
        raise ReclaimViolation("lock candidate semantic path mismatch")
    if inventory.get("part_root_relative_path") != PART_ROOT_REL.as_posix():
        raise ReclaimViolation("lock part-root semantic path mismatch")
    if inventory.get("part_count") != EXPECTED_PART_COUNT:
        raise ReclaimViolation("lock exact 349-part semantic mismatch")
    if len(inventory.get("parts", [])) != EXPECTED_PART_COUNT:
        raise ReclaimViolation("lock part inventory length semantic mismatch")
    if inventory.get("logical_bytes") != EXPECTED_SIZE:
        raise ReclaimViolation("lock logical-byte semantic mismatch")
    if inventory.get("range_start") != 0 or inventory.get("range_end") != EXPECTED_SIZE - 1:
        raise ReclaimViolation("lock byte-range semantic mismatch")
    if inventory.get("inventory_hash") != sha256_bytes(
        canonical_json_bytes(inventory["parts"])
    ):
        raise ReclaimViolation("lock inventory-hash semantic mismatch")

    canonical = frozen["canonical_contract"]
    if canonical.get("canonical_relative_path") != CANONICAL_REL.as_posix():
        raise ReclaimViolation("lock canonical semantic path mismatch")
    if canonical.get("expected_size_bytes") != EXPECTED_SIZE:
        raise ReclaimViolation("lock canonical-size semantic mismatch")
    if canonical.get("official_sha256") != EXPECTED_SHA256:
        raise ReclaimViolation("lock official-checksum semantic mismatch")
    if canonical.get("checksum_authority") != CHECKSUM_REL.as_posix():
        raise ReclaimViolation("lock checksum-authority semantic mismatch")
    checksum_row = frozen["checksum_bindings"]["input_reference_checksum"]["row"]
    if (
        checksum_row.get("path") != CANONICAL_REL.as_posix()
        or checksum_row.get("size_bytes") != str(EXPECTED_SIZE)
        or checksum_row.get("algorithm") != "SHA-256"
        or checksum_row.get("digest") != EXPECTED_SHA256
        or checksum_row.get("status") != "PASS"
    ):
        raise ReclaimViolation("lock checksum-row semantic mismatch")

    if set(frozen["frozen_artifacts"]) != {
        relative.as_posix() for relative in TOOL_RELS
    }:
        raise ReclaimViolation("lock frozen-tool set semantic mismatch")
    reference_scan = frozen["zero_reference_scan"]
    if reference_scan.get("excluded_exact_paths") != sorted(
        relative.as_posix() for relative in FORMAL_RELS
    ):
        raise ReclaimViolation("lock exact reference-scan exclusions mismatch")
    if reference_scan.get("matches") != []:
        raise ReclaimViolation("lock contains a candidate evidence reference")
    exact_part_names = sorted(str(record["name"]) for record in inventory["parts"])
    if reference_scan.get("exact_part_basename_count") != EXPECTED_PART_COUNT:
        raise ReclaimViolation("lock part-basename scan count mismatch")
    if reference_scan.get("part_basename_inventory_hash") != sha256_bytes(
        canonical_json_bytes(exact_part_names)
    ):
        raise ReclaimViolation("lock part-basename scan inventory mismatch")
    expected_accuracy_exclusion = {
        "classified_container_directories": sorted(
            relative.as_posix() for relative in CLASSIFIED_OUTCOME_CONTAINER_DIRS
        ),
        "exact_files": sorted(
            relative.as_posix() for relative in EXACT_OUTCOME_EXCLUDED_FILES
        ),
        "g0_evo_generated_filename_class": "TUM/log names emitted by evaluate_vins_common_support.py",
        "unallowlisted_accuracy_candidate_policy": "FAIL_CLOSED_WITHOUT_READING",
    }
    if reference_scan.get("accuracy_exclusion") != expected_accuracy_exclusion:
        raise ReclaimViolation("lock exact accuracy-exclusion semantic mismatch")
    if reference_scan.get("known_non_text_suffixes") != sorted(
        KNOWN_NON_TEXT_EVIDENCE_SUFFIXES
    ) or reference_scan.get("unknown_file_type_policy") != (
        "FAIL_CLOSED_WITHOUT_READING"
    ):
        raise ReclaimViolation("lock evidence file-type policy semantic mismatch")
    for excluded in reference_scan.get("excluded_outcome_files_seen", []):
        if _accuracy_path_class(Path(excluded), is_directory=False) != "EXACT_EXCLUDED":
            raise ReclaimViolation("lock reports an unclassified excluded outcome file")

    quiescence = frozen["quiescence"]
    if quiescence.get("active_matches") != [] or quiescence.get("inspection_errors") != []:
        raise ReclaimViolation("lock quiescence semantic mismatch")
    exceptions = quiescence.get("inaccessible_process_exceptions")
    if not isinstance(exceptions, list) or sorted(
        item.get("comm") for item in exceptions
    ) != sorted(ALLOWED_INACCESSIBLE_COMMS):
        raise ReclaimViolation("lock inaccessible-process exception set mismatch")
    expected_exception_policy = {
        "allowed_comms": sorted(ALLOWED_INACCESSIBLE_COMMS),
        "identity_fields": list(INACCESSIBLE_IDENTITY_FIELDS),
        "executor_requires_exact_frozen_tuple_set": True,
    }
    if quiescence.get("inaccessible_exception_policy") != expected_exception_policy:
        raise ReclaimViolation("lock inaccessible-process policy semantic mismatch")
    required_identity_fields = set(INACCESSIBLE_IDENTITY_FIELDS)
    for identity in exceptions:
        if set(identity) != required_identity_fields:
            raise ReclaimViolation("lock inaccessible-process identity fields mismatch")
        for hash_field in ("comm_sha256", "cmdline_sha256", "cgroup_sha256"):
            if re.fullmatch(r"[0-9a-f]{64}", str(identity.get(hash_field))) is None:
                raise ReclaimViolation(f"lock invalid process identity {hash_field}")
    if re.fullmatch(r"[0-9a-f]{64}", str(quiescence.get("boot_id_sha256"))) is None:
        raise ReclaimViolation("lock boot identity hash mismatch")

    if lock.get("execution_contract") != expected_execution_contract(inventory):
        raise ReclaimViolation("lock execution requirements semantic mismatch")
    verify_document_self_hash(lock)


def build_lock(root: Path = ROOT) -> Dict[str, Any]:
    root = root.absolute()
    formal_precondition = assert_formal_artifacts_absent(root)
    state = collect_current_state(root)
    # The scan can take time; catch a lock/intent/receipt appearing meanwhile.
    assert_formal_artifacts_absent(root)
    lock: Dict[str, Any] = {
        "schema": LOCK_SCHEMA,
        "status": LOCK_STATUS,
        "generated_at_utc": utc_now(),
        "workspace_root": str(root),
        "scope": expected_scope(),
        "formal_paths": expected_formal_paths(),
        "formal_precondition": formal_precondition,
        "frozen_state": state,
        "execution_contract": expected_execution_contract(state["inventory"]),
        "outcome_boundary": OUTCOME_BOUNDARY,
        "pre_freeze_dry_run_scanner_classification_incident": dict(
            PREFREEZE_SCANNER_CLASSIFICATION_INCIDENT
        ),
    }
    lock[SELF_HASH_FIELD] = document_self_hash(lock)
    validate_lock_semantics(root, lock)
    return lock


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument(
        "--write",
        action="store_true",
        help="publish the formal no-clobber lock (default only prints proposal)",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    root = args.root.absolute()
    lock = build_lock(root)
    if args.write:
        write_formal_lock(root, lock)
        print(_lexical_path(root, LOCK_REL))
    else:
        print(json.dumps(lock, ensure_ascii=True, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ReclaimViolation as exc:
        print(f"RECLAIM_LOCK_VIOLATION: {exc}", file=sys.stderr)
        raise SystemExit(1)
