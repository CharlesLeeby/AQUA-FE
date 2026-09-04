#!/usr/bin/env python3
"""Safely reclaim reproducible P07 AQUALOC raw-window bag caches.

The command is deliberately conservative.  It discovers bags only from P07
``command.log`` files, then requires the complete B1/M/P evidence graph before
it considers a bag reclaimable.  A plain invocation is a read-only dry run;
``--execute`` is the only switch which permits an unlink.
"""

from __future__ import annotations

import argparse
import csv
import fcntl
import hashlib
import json
import os
import re
import secrets
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Iterator, Mapping, Sequence


ROOT = Path(__file__).resolve().parents[1]
BUNDLE = ROOT / "papers/ieee_sensors_journal_experiments"
P07 = BUNDLE / "p07"
RAW_CACHE_ROOT = ROOT / "datasets/aqualoc/rosbags"
QUEUE = P07 / "frontend_export_queue_v1.csv"
ALLOCATION = P07 / "frontend_run_allocation_v1.csv"
RUN_REGISTRY = BUNDLE / "run_registry.csv"
ARM_APPLICABILITY = BUNDLE / "arm_applicability.csv"
DATASET_MANIFEST = BUNDLE / "dataset_manifest_v4.csv"
DATA_ELIGIBILITY = BUNDLE / "data_eligibility_manifest.csv"
DATASET_CHECKSUMS = BUNDLE / "dataset_checksum_manifest.txt"
RECLAMATION_ROOT = P07 / "raw_cache_reclamation"
EXECUTION_LEDGER = BUNDLE / "execution_ledger.jsonl"
LOCK_NAME = ".reclamation.lock"

SCHEMA = "isj-p07-raw-cache-reclamation-v1"
ARM_B1 = "B1_klt_nativeq_v3"
ARM_M = "M_xfeat_pairwise_nativeq_v1"
ARM_P = "P_legacy_nativeq_xfeat_seedchain_v3"
FRONTEND_ARMS = frozenset({ARM_B1, ARM_M, ARM_P})
ARM_ALIASES = {"B1": ARM_B1, "M": ARM_M, "P": ARM_P}

RAW_BAG_RE = re.compile(r"(?:^|\s)raw_bag=(?P<value>\"[^\"]*\"|'[^']*'|[^\s]+)")
QUEUE_INDEX_RE = re.compile(r"(?:^|[/_])queue[_-](?P<index>\d+)(?:[_/.-]|$)")
QUEUE_TEXT_RE = re.compile(r"\bqueue_index\s*[=:]\s*(\d+)\b")
CHECKSUM_LINE_RE = re.compile(r"^\s*([0-9a-fA-F]{64})\s+(?:\*?)(.+?)\s*$")
AUDIT_NAME_RE = re.compile(r"^audit_v([34])\.json$")
COMMAND_COUNT_RE = re.compile(
    r"\b(images|imu|gt|raw_images|raw_imu|raw_gt|feature_frames)=([0-9]+)\b"
)


class ReclamationError(RuntimeError):
    """Raised for a fail-closed governance or filesystem error."""


@dataclass(frozen=True)
class RawBinding:
    """One raw_bag occurrence and the queue identity inferred for its log."""

    path: Path
    command_log: Path
    queue_index: int | None
    occurrences: int


@dataclass
class Candidate:
    """A fully validated candidate, with absolute paths kept private to output."""

    path: Path
    window_id: str
    queues: list[dict[str, Any]]
    command_logs: list[Path]
    command_log_counts: dict[str, int]
    raw_bag_line_count: int
    size_bytes: int
    sha256: str
    source_archive_path: Path
    source_archive_sha256: str
    evidence_paths: list[Path] = field(default_factory=list)
    raw_bag_line_counts_by_queue: dict[str, int] = field(default_factory=dict)

    def as_dict(self, root: Path) -> dict[str, Any]:
        queue_indices = [int(item["queue_index"]) for item in self.queues]
        run_ids = [str(item["run_id"]) for item in self.queues]
        arms = [str(item["arm"]) for item in self.queues]
        return {
            "raw_cache_path": display_path(root, self.path),
            "raw_bag_path": display_path(root, self.path),
            "size_bytes": self.size_bytes,
            "sha256": self.sha256,
            "source_archive_path": display_path(root, self.source_archive_path),
            "source_archive_sha256": self.source_archive_sha256,
            "window_id": self.window_id,
            "queues": queue_indices,
            "queue_indices": queue_indices,
            "run_ids": run_ids,
            "arms": arms,
            "command_logs": [display_path(root, path) for path in self.command_logs],
            "command_log_counts": dict(self.command_log_counts),
            "command_log_count": len(self.command_logs),
            "raw_bag_line_count": self.raw_bag_line_count,
            "raw_bag_line_counts_by_queue": dict(self.raw_bag_line_counts_by_queue),
            "evidence_paths": [display_path(root, path) for path in self.evidence_paths],
        }


@dataclass
class Rejection:
    path: Path
    reasons: list[str]
    command_logs: list[Path] = field(default_factory=list)
    raw_bag_line_count: int = 0

    def as_dict(self, root: Path) -> dict[str, Any]:
        return {
            "raw_cache_path": display_path(root, self.path),
            "reasons": list(self.reasons),
            "command_logs": [display_path(root, p) for p in self.command_logs],
            "command_log_count": len(self.command_logs),
            "raw_bag_line_count": self.raw_bag_line_count,
        }


def canonical_arm(value: str) -> str:
    value = str(value).strip()
    return ARM_ALIASES.get(value, value)


def lexical_absolute(path: Path) -> Path:
    """Make a path absolute without following symlinks."""

    return Path(os.path.abspath(os.fspath(path)))


def real_absolute(path: Path) -> Path:
    return Path(os.path.realpath(os.fspath(path)))


def display_path(root: Path, path: Path) -> str:
    absolute = lexical_absolute(path)
    root_abs = lexical_absolute(root)
    try:
        return absolute.relative_to(root_abs).as_posix()
    except ValueError:
        return str(absolute)


def resolve_reference(root: Path, value: str | os.PathLike[str]) -> Path:
    text = os.fspath(value).strip().strip("\"'")
    # Applicability evidence often uses a CSV anchor (``path#slot_index=``).
    text = text.split("#", 1)[0]
    path = Path(text)
    return lexical_absolute(path if path.is_absolute() else root / path)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _confined(path: Path, parent: Path) -> bool:
    """Require both lexical and resolved paths to remain below ``parent``."""

    try:
        lexical_absolute(path).relative_to(lexical_absolute(parent))
        real_absolute(path).relative_to(real_absolute(parent))
    except ValueError:
        return False
    return True


def _truth_false(value: Any) -> bool:
    # JSON evidence uses a boolean.  Accepting the textual spelling keeps the
    # reader compatible with a few early hand-authored closeouts.
    return value is False or (isinstance(value, str) and value.strip().lower() == "false")


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        raise ReclamationError(f"missing CSV: {path}")
    with path.open(newline="", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_SH)
        try:
            reader = csv.DictReader(handle)
            fields = list(reader.fieldnames or [])
            if not fields or len(fields) != len(set(fields)):
                raise ReclamationError(f"invalid CSV header: {path}")
            rows = list(reader)
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    if any(None in row for row in rows):
        raise ReclamationError(f"ragged CSV: {path}")
    return [dict(row) for row in rows]


def first_existing(root: Path, relative_names: Sequence[str]) -> Path:
    for name in relative_names:
        path = root / name
        if path.is_file():
            return path
    raise ReclamationError(f"none of the required files exist below {root}: {relative_names}")


def _iter_files(root: Path) -> Iterator[Path]:
    """Walk governance-relevant workspace files without following symlinks.

    The workspace contains multi-gigabyte generated/source trees which are not
    governance stores.  They are pruned by directory name, while the P07 tree
    (where every canonical hash manifest lives) is always traversed.  A caller
    can add registry-referenced manifest paths through ``_manifest_path_files``.
    """

    prune = {
        ".git",
        ".cache",
        ".venv",
        "__pycache__",
        "build",
        "devel",
        "install",
        "logs",
        "datasets",
        "node_modules",
        "source_backups",
        "uw_frontend",
    }
    for directory, dirnames, filenames in os.walk(root, topdown=True, followlinks=False):
        dirnames[:] = sorted(name for name in dirnames if name not in prune)
        for name in sorted(filenames):
            yield Path(directory) / name


def command_logs(root: Path) -> list[Path]:
    p07 = root / "papers/ieee_sensors_journal_experiments/p07"
    if not p07.is_dir():
        return []
    paths: list[Path] = []
    for directory, _dirnames, filenames in os.walk(p07, topdown=True, followlinks=False):
        if "command.log" in filenames:
            paths.append(Path(directory) / "command.log")
    return sorted(paths, key=lambda p: display_path(root, p))


def _queue_index_for_log(log: Path) -> int | None:
    values = {int(match.group("index")) for match in QUEUE_INDEX_RE.finditer(log.as_posix())}
    values.update(int(value) for value in QUEUE_TEXT_RE.findall(log.read_text(encoding="utf-8", errors="replace")))
    return values.pop() if len(values) == 1 else None


def _raw_value(value: str) -> str:
    return value.strip().strip("\"'").rstrip(",;")


def discover_raw_bindings(root: Path) -> dict[Path, list[RawBinding]]:
    """Discover raw bags exclusively from ``raw_bag=`` lines in P07 logs."""

    discovered: dict[Path, list[RawBinding]] = {}
    cache_root = root / "datasets/aqualoc/rosbags"
    for log in command_logs(root):
        try:
            text = log.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        matches = [_raw_value(match.group("value")) for match in RAW_BAG_RE.finditer(text)]
        if not matches:
            continue
        queue_index = _queue_index_for_log(log)
        counts: dict[Path, int] = {}
        for raw in matches:
            path = resolve_reference(root, raw)
            # Keep malformed/out-of-root paths in the report as rejected
            # candidates; they must never be silently treated as deletable.
            key = lexical_absolute(path)
            counts[key] = counts.get(key, 0) + 1
        for path, count in counts.items():
            discovered.setdefault(path, []).append(
                RawBinding(path=path, command_log=log, queue_index=queue_index, occurrences=count)
            )
    return discovered


def _manifest_path_files(root: Path) -> list[Path]:
    paths: list[Path] = []
    # Canonical P07 manifests live below ``papers``.  Completed runs can also
    # leave manifests under ``logs``; include that tree explicitly while still
    # avoiding the multi-gigabyte dataset/source trees.
    prune = {
        ".git",
        ".cache",
        "__pycache__",
        "build",
        "devel",
        "install",
        "datasets",
        "node_modules",
        "source_backups",
        "uw_frontend",
    }
    bases = [root / "papers"]
    logs = root / "logs"
    if logs.is_dir() and not logs.is_symlink():
        bases.append(logs)
    for base in bases:
        if not base.is_dir():
            continue
        for directory, dirnames, filenames in os.walk(base, topdown=True, followlinks=False):
            dirnames[:] = sorted(name for name in dirnames if name not in prune)
            for name in sorted(filenames):
                if name == "input_hash_manifest.sha256" or (
                    name.startswith("output_hash_manifest") and name.endswith(".sha256")
                ):
                    paths.append(Path(directory) / name)
    return sorted(paths, key=lambda p: display_path(root, p))


def _checksum_entries(path: Path) -> dict[str, str]:
    entries: dict[str, str] = {}
    for line_number, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
        if not line.strip():
            continue
        match = CHECKSUM_LINE_RE.match(line)
        if not match:
            raise ReclamationError(f"invalid checksum line {path}:{line_number}")
        digest, name = match.groups()
        name = name.strip()
        observed = digest.lower()
        prior = entries.get(name)
        if prior is not None and prior != observed:
            raise ReclamationError(f"conflicting checksum entries for {name} in {path}")
        entries[name] = observed
    return entries


def _mentioned_paths(root: Path, manifest: Path) -> set[Path]:
    mentioned: set[Path] = set()
    for line in manifest.read_text(encoding="utf-8", errors="replace").splitlines():
        match = CHECKSUM_LINE_RE.match(line)
        if match:
            mentioned.add(real_absolute(resolve_reference(root, match.group(2).strip())))
        else:
            # A malformed line is still a reference.  Extract path-like
            # tokens so a malformed manifest cannot become a bypass.
            for token in re.findall(r"(?:/[^\s]+|(?:datasets|logs|papers)/[^\s]+)", line):
                mentioned.add(real_absolute(resolve_reference(root, token.rstrip(",;"))))
    return mentioned


def protected_raw_paths(root: Path) -> tuple[set[Path], list[Path]]:
    manifests = _manifest_path_files(root)
    protected: set[Path] = set()
    for manifest in manifests:
        protected.update(_mentioned_paths(root, manifest))
    return protected, manifests


def _float_equal(left: str, right: str) -> bool:
    try:
        return float(left) == float(right)
    except (TypeError, ValueError):
        return False


def _allocation_raw_path(root: Path, allocation: Mapping[str, str]) -> Path | None:
    """Derive the deterministic AQUALOC raw-window cache path when possible."""

    family = str(allocation.get("dataset_family", "")).strip()
    sequence = str(allocation.get("sequence", "")).strip()
    start = str(allocation.get("window_start", "")).strip()
    end = str(allocation.get("window_end", "")).strip()
    if family == "aqualoc_archaeology" and re.fullmatch(r"A\d+", sequence):
        prefix = f"archaeo{int(sequence[1:]):02d}"
    elif family == "aqualoc_harbor" and re.fullmatch(r"H\d+", sequence):
        prefix = f"harbor{int(sequence[1:]):02d}"
    else:
        return None
    if not start or not end:
        return None

    def component(value: str) -> str:
        try:
            number = float(value)
        except ValueError:
            return value
        return str(int(number)) if number.is_integer() else value

    return lexical_absolute(
        root
        / "datasets/aqualoc/rosbags"
        / f"{prefix}_{component(start)}_{component(end)}.bag"
    )


def _allocation_bindings_for_raw(
    root: Path,
    raw_path: Path,
    queues: Mapping[int, Mapping[str, str]],
    allocations: Mapping[int, Mapping[str, str]],
) -> list[dict[str, Any]]:
    target = real_absolute(raw_path)
    bindings: list[dict[str, Any]] = []
    for index, allocation in allocations.items():
        expected = _allocation_raw_path(root, allocation)
        if expected is None or real_absolute(expected) != target:
            continue
        queue = queues.get(index, {})
        bindings.append(
            {
                "queue_index": index,
                "window_id": str(allocation.get("window_id") or queue.get("window_id", "")),
                "arm": canonical_arm(str(allocation.get("arm") or queue.get("arm", ""))),
                "status": str(allocation.get("status", "")),
            }
        )
    return sorted(bindings, key=lambda item: int(item["queue_index"]))


def _load_window_manifest(root: Path) -> tuple[dict[str, dict[str, str]], Path]:
    path = first_existing(
        root,
        (
            "papers/ieee_sensors_journal_experiments/dataset_manifest_v4.csv",
            "papers/ieee_sensors_journal_experiments/dataset_manifest.csv",
        ),
    )
    rows = read_csv(path)
    by_id: dict[str, dict[str, str]] = {}
    for row in rows:
        window_id = row.get("window_id", "").strip()
        if not window_id or window_id in by_id:
            raise ReclamationError(f"duplicate or empty window_id in {path}")
        by_id[window_id] = row
    return by_id, path


def _load_data_eligibility(root: Path) -> tuple[dict[tuple[str, str], list[dict[str, str]]], Path]:
    path = first_existing(
        root,
        ("papers/ieee_sensors_journal_experiments/data_eligibility_manifest.csv",),
    )
    rows = read_csv(path)
    by_key: dict[tuple[str, str], list[dict[str, str]]] = {}
    for row in rows:
        key = (row.get("dataset_family", "").strip(), row.get("sequence", "").strip())
        if not all(key):
            raise ReclamationError(f"empty dataset eligibility key in {path}: {key}")
        by_key.setdefault(key, []).append(row)
    return by_key, path


def _load_checksum_manifest(root: Path) -> tuple[dict[Path, str], Path]:
    path = first_existing(
        root, ("papers/ieee_sensors_journal_experiments/dataset_checksum_manifest.txt",)
    )
    raw = _checksum_entries(path)
    by_path: dict[Path, str] = {}
    for name, digest in raw.items():
        key = real_absolute(resolve_reference(root, name))
        prior = by_path.get(key)
        if prior is not None and prior != digest:
            raise ReclamationError(f"conflicting checksum entries for {name}")
        by_path[key] = digest
    return by_path, path


def _load_queue_and_allocations(root: Path) -> tuple[dict[int, dict[str, str]], dict[int, dict[str, str]], Path, Path]:
    queue_path = first_existing(
        root, ("papers/ieee_sensors_journal_experiments/p07/frontend_export_queue_v1.csv",)
    )
    allocation_path = first_existing(
        root, ("papers/ieee_sensors_journal_experiments/p07/frontend_run_allocation_v1.csv",)
    )
    queue_rows = read_csv(queue_path)
    allocation_rows = read_csv(allocation_path)
    queues: dict[int, dict[str, str]] = {}
    allocations: dict[int, dict[str, str]] = {}
    for row in queue_rows:
        try:
            index = int(row["queue_index"])
        except (KeyError, ValueError):
            raise ReclamationError(f"invalid queue_index in {queue_path}: {row}")
        if index in queues:
            raise ReclamationError(f"duplicate queue_index {index}")
        row = dict(row)
        row["arm"] = canonical_arm(row.get("arm", ""))
        queues[index] = row
    for row in allocation_rows:
        try:
            index = int(row["queue_index"])
        except (KeyError, ValueError):
            raise ReclamationError(f"invalid allocation queue_index in {allocation_path}: {row}")
        if index in allocations:
            raise ReclamationError(f"duplicate allocation queue_index {index}")
        row = dict(row)
        row["arm"] = canonical_arm(row.get("arm", ""))
        allocations[index] = row
    return queues, allocations, queue_path, allocation_path


def _load_registry(root: Path) -> tuple[list[dict[str, str]], Path]:
    path = first_existing(
        root,
        (
            "papers/ieee_sensors_journal_experiments/run_registry.csv",
            "papers/ieee_sensors_journal_experiments/run_registry_v1.csv",
        ),
    )
    return read_csv(path), path


def registry_chain(rows: Sequence[Mapping[str, str]], run_id: str) -> list[dict[str, str]]:
    """Validate one run's contiguous append-only chain and return it."""

    chain = [dict(row) for row in rows if str(row.get("run_id", "")) == run_id]
    if not chain:
        raise ReclamationError(f"missing run registry chain: {run_id}")
    immutable_fields = (
        "run_id",
        "protocol_version",
        "method_profile",
        "stage",
        "dataset_family",
        "sequence",
        "window_start",
        "window_end",
        "arm",
        "frontend_seed",
        "backend_replay",
    )
    previous: dict[str, str] | None = None
    seen: set[str] = set()
    for position, row in enumerate(chain):
        event_id = str(row.get("registry_event_id", ""))
        match = re.fullmatch(re.escape(run_id) + r"_e(\d+)", event_id)
        if not match or int(match.group(1)) != position or event_id in seen:
            raise ReclamationError(f"non-contiguous registry chain for {run_id}")
        seen.add(event_id)
        expected_parent = "" if previous is None else str(previous["registry_event_id"])
        if str(row.get("supersedes_event_id", "")) != expected_parent:
            raise ReclamationError(f"invalid registry supersession for {run_id}")
        if previous is not None:
            for field_name in immutable_fields:
                if row.get(field_name, "") != previous.get(field_name, ""):
                    raise ReclamationError(f"registry identity drift for {run_id}: {field_name}")
        previous = row
    return chain


def _path_from_row(root: Path, row: Mapping[str, str], field_name: str) -> Path | None:
    value = str(row.get(field_name, "")).strip()
    if not value:
        return None
    return resolve_reference(root, value)


def _queue_audit_candidates(root: Path, queue_index: int, queue_row: Mapping[str, str], logs: Sequence[Path]) -> list[Path]:
    dirs: list[Path] = []
    for log in logs:
        if _queue_index_for_log(log) == queue_index:
            dirs.append(log.parent)
    attempt_root = root / "papers/ieee_sensors_journal_experiments/p07/frontend_attempts"
    if attempt_root.is_dir():
        dirs.extend(sorted(attempt_root.glob(f"queue_{queue_index:03d}_*")))
    paths: set[Path] = set()
    for directory in dirs:
        if not directory.is_dir():
            continue
        for path in directory.iterdir():
            if path.is_file() and AUDIT_NAME_RE.match(path.name):
                paths.add(path)
    return sorted(paths, key=lambda p: (int(AUDIT_NAME_RE.match(p.name).group(1)), str(p)))


def _validate_audits(
    root: Path,
    queue_index: int,
    queue_row: Mapping[str, str],
    allocation: Mapping[str, str],
    logs: Sequence[Path],
) -> tuple[list[Path], list[Path]]:
    paths = _queue_audit_candidates(root, queue_index, queue_row, logs)
    if not paths:
        raise ReclamationError(f"missing v3/v4 queue audit for queue {queue_index}")
    evidence: list[Path] = []
    for path in paths:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ReclamationError(f"invalid queue audit {path}: {exc}") from exc
        schema = str(payload.get("schema_version", ""))
        if not re.search(r"frontend-export-audit-v[34]$", schema):
            raise ReclamationError(f"unsupported queue audit schema: {path}")
        if payload.get("status") != "PASS":
            raise ReclamationError(f"queue audit is not PASS: {path}")
        if payload.get("held_out_trajectory_outcome_read") is not False:
            raise ReclamationError(f"queue audit read held-out trajectory outcome: {path}")
        if payload.get("forbidden_outcome_artifacts") != []:
            raise ReclamationError(f"queue audit has forbidden outcome artifacts: {path}")
        if payload.get("window_id") != queue_row.get("window_id"):
            raise ReclamationError(f"queue audit window mismatch: {path}")
        if payload.get("queue_index") not in (queue_index, str(queue_index)):
            raise ReclamationError(f"queue audit queue mismatch: {path}")
        observed_arm = canonical_arm(str(payload.get("arm", "")))
        if observed_arm != canonical_arm(str(queue_row.get("arm", ""))):
            raise ReclamationError(f"queue audit arm mismatch: {path}")
        if payload.get("run_id") != allocation.get("run_id"):
            raise ReclamationError(f"queue audit run mismatch: {path}")
        evidence.append(path)
        evidence.extend(_existing_evidence_from_json(root, payload))
    return paths, _unique_paths(evidence)


def _existing_evidence_from_json(root: Path, value: Any, key: str = "") -> list[Path]:
    found: list[Path] = []
    if isinstance(value, Mapping):
        for child_key, child in value.items():
            found.extend(_existing_evidence_from_json(root, child, str(child_key)))
    elif isinstance(value, list):
        for child in value:
            found.extend(_existing_evidence_from_json(root, child, key))
    elif isinstance(value, str) and (
        "path" in key.lower() or "manifest" in key.lower() or key.lower() in {"audit", "attestation", "guard"}
    ):
        path = resolve_reference(root, value)
        if path.is_file():
            found.append(path)
    return found


def _unique_paths(paths: Iterable[Path]) -> list[Path]:
    seen: set[str] = set()
    result: list[Path] = []
    for path in paths:
        key = str(lexical_absolute(path))
        if key not in seen:
            seen.add(key)
            result.append(lexical_absolute(path))
    return sorted(result, key=str)


def _command_log_counts(logs: Sequence[Path]) -> dict[str, int]:
    """Collect stable count fields emitted by AQUALOC raw conversion logs."""

    counts: dict[str, int] = {}
    for log in _unique_paths(logs):
        text = log.read_text(encoding="utf-8", errors="replace")
        for line in text.splitlines():
            for key, raw_value in COMMAND_COUNT_RE.findall(line):
                value = int(raw_value)
                prior = counts.get(key)
                if prior is not None and prior != value:
                    raise ReclamationError(
                        f"conflicting command-log count {key}: {prior} != {value} in {log}"
                    )
                counts[key] = value
    return dict(sorted(counts.items()))


def _matching_applicability(
    rows: Sequence[Mapping[str, str]], window: Mapping[str, str], window_id: str
) -> list[dict[str, str]]:
    result: list[dict[str, str]] = []
    for original in rows:
        row = dict(original)
        if row.get("window_id") and row.get("window_id") != window_id:
            continue
        if row.get("window_id") != window_id and not (
            row.get("dataset_family") == window.get("dataset_family")
            and row.get("sequence") == window.get("sequence")
            and _float_equal(row.get("window_start", ""), window.get("window_start_s", ""))
            and _float_equal(row.get("window_end", ""), window.get("window_end_s", ""))
        ):
            continue
        if canonical_arm(row.get("proposed_arm", "")) != ARM_P:
            continue
        if row.get("drop_arm") and canonical_arm(row.get("drop_arm", "")) not in {
            "D_legacy_exact_lineage_drop_v3",
            "D",
        }:
            continue
        result.append(row)
    return result


def _legacy_pass_evidence(payload: Mapping[str, Any], window_id: str) -> bool:
    if payload.get("status") != "PASS" or payload.get("window_id") != window_id:
        return False
    lineages = payload.get("learned_lineages")
    count: Any = payload.get("accepted_learned_born_lineage_count")
    if count is None and isinstance(lineages, Mapping):
        count = lineages.get("accepted_learned_born_lineage_count")
    try:
        zero_count = int(count) == 0
    except (TypeError, ValueError):
        zero_count = False
    identity = payload.get("zero_action_identity")
    if identity is None and isinstance(payload.get("evidence"), Mapping):
        identity = payload["evidence"].get("zero_action_identity")
    identity_pass = (
        isinstance(identity, Mapping) and identity.get("status") == "PASS_BYTE_IDENTICAL_TO_B1"
    ) or identity == "PASS_BYTE_IDENTICAL_TO_B1"
    return zero_count and identity_pass


def _validate_d(
    root: Path, window_id: str, window: Mapping[str, str]
) -> tuple[Path, dict[str, Any], list[Path]]:
    path = first_existing(root, ("papers/ieee_sensors_journal_experiments/arm_applicability.csv",))
    rows = read_csv(path)
    matches = _matching_applicability(rows, window, window_id)
    terminals = [row for row in matches if row.get("resolution", "").strip() != "PENDING_APPLICABILITY"]
    if len(terminals) != 1:
        raise ReclamationError(f"expected exactly one terminal D row for {window_id}, found {len(terminals)}")
    row = terminals[0]
    evidence_value = row.get("evidence_path", "").strip()
    if not evidence_value:
        raise ReclamationError(f"terminal D row has no evidence path: {window_id}")
    evidence_path = resolve_reference(root, evidence_value)
    if not _confined(evidence_path, root) or not evidence_path.is_file() or evidence_path.is_symlink():
        raise ReclamationError(f"terminal D evidence is missing: {evidence_path}")
    try:
        payload = json.loads(evidence_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ReclamationError(f"invalid terminal D evidence: {evidence_path}: {exc}") from exc
    if not isinstance(payload, Mapping):
        raise ReclamationError(f"invalid terminal D evidence object: {evidence_path}")
    resolution = row.get("resolution", "").strip()
    expected_status = f"PASS_{resolution}"
    accepted = payload.get("window_id") == window_id and payload.get("status") == expected_status
    if not accepted:
        accepted = _legacy_pass_evidence(payload, window_id)
    if not accepted:
        raise ReclamationError(f"terminal D evidence status mismatch: {evidence_path}")
    if payload.get("held_out_trajectory_outcome_read") is not None and not _truth_false(
        payload.get("held_out_trajectory_outcome_read")
    ):
        raise ReclamationError(f"terminal D evidence read held-out trajectory outcome: {evidence_path}")
    payload_resolution = str(payload.get("resolution", "")).strip()
    if payload_resolution and payload_resolution != resolution:
        raise ReclamationError(f"terminal D resolution mismatch: {evidence_path}")
    row_count = str(row.get("accepted_lineage_count", "")).strip()
    payload_count: Any = payload.get("accepted_learned_born_lineage_count")
    if payload_count is None and isinstance(payload.get("evidence"), Mapping):
        payload_count = payload["evidence"].get("accepted_learned_born_lineage_count")
    if row_count and payload_count is not None:
        try:
            if int(row_count) != int(payload_count):
                raise ReclamationError(f"terminal D lineage count mismatch: {evidence_path}")
        except ValueError as exc:
            raise ReclamationError(f"invalid terminal D lineage count: {evidence_path}") from exc
    return path, row, [evidence_path]


def _validate_source(
    root: Path,
    window_id: str,
    window: Mapping[str, str],
    window_manifest_path: Path,
    eligibility_by_key: Mapping[tuple[str, str], Sequence[Mapping[str, str]]],
    eligibility_path: Path,
    checksum_by_path: Mapping[Path, str],
    checksum_path: Path,
    observed_hashes: dict[Path, str] | None = None,
) -> tuple[Path, str, list[Path]]:
    key = (window.get("dataset_family", ""), window.get("sequence", ""))
    rows = eligibility_by_key.get(key)
    if not rows:
        raise ReclamationError(f"no source eligibility row for {window_id}: {key}")
    if len(rows) != 1:
        raise ReclamationError(f"ambiguous source eligibility rows for {window_id}: {key}")
    row = rows[0]
    source_value = str(row.get("raw_input_path", "")).strip()
    if not source_value:
        raise ReclamationError(f"source eligibility row has no raw_input_path: {key}")
    source = resolve_reference(root, source_value)
    if not source.is_file() or source.is_symlink():
        raise ReclamationError(f"immutable source archive missing or symlink: {source}")
    source_key = real_absolute(source)
    expected = checksum_by_path.get(source_key)
    if expected is None:
        raise ReclamationError(f"source archive is not covered by checksum manifest: {source}")
    if observed_hashes is not None and source_key in observed_hashes:
        observed = observed_hashes[source_key]
    else:
        observed = sha256(source)
        if observed_hashes is not None:
            observed_hashes[source_key] = observed
    if observed != expected:
        raise ReclamationError(f"source archive checksum mismatch: {source}")
    for size_field in ("raw_size_bytes", "expected_raw_size_bytes"):
        value = str(row.get(size_field, "")).strip()
        if value:
            try:
                if source.stat().st_size != int(value):
                    raise ReclamationError(
                        f"source archive size mismatch ({size_field}): {source}"
                    )
            except ValueError as exc:
                raise ReclamationError(f"invalid {size_field} for source {key}") from exc
    integrity = str(row.get("raw_integrity", "")).strip()
    if integrity.upper() in {"MISSING", "FAIL", "FAILED", "SIZE_MISMATCH", "HASH_MISMATCH"}:
        raise ReclamationError(f"source archive integrity is not accepted for {key}: {integrity}")
    raw_exists = str(row.get("raw_exists", "")).strip().lower()
    if raw_exists and raw_exists != "true":
        raise ReclamationError(f"source eligibility does not certify an existing archive: {key}")
    return source, expected, [window_manifest_path, eligibility_path, checksum_path]


def _candidate_queue_records(
    bindings: Sequence[RawBinding],
    queues: Mapping[int, Mapping[str, str]],
    allocations: Mapping[int, Mapping[str, str]],
    registry_rows: Sequence[Mapping[str, str]],
    root: Path,
    all_logs: Sequence[Path],
    queue_path: Path,
    allocation_path: Path,
) -> tuple[
    str,
    list[dict[str, Any]],
    list[Path],
    dict[str, int],
    dict[str, int],
    int,
    list[Path],
]:
    indices = {binding.queue_index for binding in bindings}
    if None in indices:
        raise ReclamationError("one or more raw_bag command logs have no unique queue index")
    queue_indices = sorted(int(index) for index in indices if index is not None)
    if any(index <= 6 for index in queue_indices):
        raise ReclamationError("raw cache is bound to protected early queue q1-6")
    if len(queue_indices) != 3:
        raise ReclamationError(f"raw cache is not bound to exactly one three-arm triplet: queues={queue_indices}")
    queue_records: list[dict[str, Any]] = []
    windows: set[str] = set()
    command_logs: list[Path] = []
    counts: dict[str, int] = {}
    lines = 0
    evidence: list[Path] = []
    for binding in bindings:
        command_logs.append(binding.command_log)
        lines += binding.occurrences
        if binding.queue_index is not None:
            counts[str(binding.queue_index)] = counts.get(str(binding.queue_index), 0) + binding.occurrences
    for index in queue_indices:
        queue = queues.get(index)
        allocation = allocations.get(index)
        if queue is None or allocation is None:
            raise ReclamationError(f"missing queue/allocation row for queue {index}")
        window_id = str(queue.get("window_id", "")).strip()
        if not window_id or str(allocation.get("window_id", "")).strip() != window_id:
            raise ReclamationError(f"queue/allocation window mismatch for queue {index}")
        windows.add(window_id)
        queue_records.append(
            {
                "queue_index": index,
                "arm": canonical_arm(str(queue.get("arm", ""))),
                "window_id": window_id,
                "run_id": str(allocation.get("run_id", "")).strip(),
                "tag": str(queue.get("tag", "")).strip(),
                "allocation": dict(allocation),
            }
        )
        evidence.extend(
            path
            for path in (
                queue_path,
                allocation_path,
            )
            if path.is_file()
        )
    if len(windows) != 1:
        raise ReclamationError(f"raw cache is bound to multiple windows: {sorted(windows)}")
    if {record["arm"] for record in queue_records} != FRONTEND_ARMS:
        raise ReclamationError(f"triplet does not contain exactly B1/M/P arms: {queue_records}")
    # A queue file with duplicate rows for the same window is ambiguous even
    # when only three of them happened to mention this cache.
    window_id = next(iter(windows))
    frozen_window_rows = [
        row for row in queues.values() if str(row.get("window_id", "")).strip() == window_id and canonical_arm(str(row.get("arm", ""))) in FRONTEND_ARMS
    ]
    if len(frozen_window_rows) != 3 or {canonical_arm(str(row.get("arm", ""))) for row in frozen_window_rows} != FRONTEND_ARMS:
        raise ReclamationError(f"frozen queue does not contain exactly one B1/M/P triplet: {window_id}")
    for record in queue_records:
        chain = registry_chain(registry_rows, record["run_id"])
        latest = chain[-1]
        if latest.get("status") != "COMPLETED":
            raise ReclamationError(f"queue {record['queue_index']} latest registry status is not COMPLETED")
        if latest.get("arm") and canonical_arm(str(latest.get("arm"))) != record["arm"]:
            raise ReclamationError(f"registry arm mismatch for queue {record['queue_index']}")
        if latest.get("dataset_family") and latest.get("dataset_family") != record["allocation"].get("dataset_family"):
            raise ReclamationError(f"registry dataset family mismatch for queue {record['queue_index']}")
        if latest.get("sequence") and latest.get("sequence") != record["allocation"].get("sequence"):
            raise ReclamationError(f"registry sequence mismatch for queue {record['queue_index']}")
        for registry_field, allocation_field in (("window_start", "window_start"), ("window_end", "window_end")):
            if latest.get(registry_field) and not _float_equal(
                str(latest.get(registry_field)), str(record["allocation"].get(allocation_field, ""))
            ):
                raise ReclamationError(
                    f"registry {registry_field} mismatch for queue {record['queue_index']}"
                )
        for field_name in ("command_file", "input_hash_manifest", "output_hash_manifest", "run_dir"):
            path = _path_from_row(root, latest, field_name)
            if path is not None:
                if not path.exists():
                    raise ReclamationError(f"registry evidence path is missing: {path}")
                evidence.append(path)
        audit_paths, audit_evidence = _validate_audits(
            root,
            record["queue_index"],
            queues[record["queue_index"]],
            allocations[record["queue_index"]],
            [binding.command_log for binding in bindings],
        )
        evidence.extend(audit_paths)
        evidence.extend(audit_evidence)
    unique_logs = _unique_paths(command_logs)
    observed_counts = _command_log_counts(unique_logs)
    return (
        window_id,
        queue_records,
        unique_logs,
        observed_counts,
        counts,
        lines,
        _unique_paths([*evidence, *unique_logs]),
    )


def _evaluate(
    root: Path,
    raw_path: Path,
    bindings: Sequence[RawBinding],
    queues: Mapping[int, Mapping[str, str]],
    allocations: Mapping[int, Mapping[str, str]],
    registry_rows: Sequence[Mapping[str, str]],
    windows: Mapping[str, Mapping[str, str]],
    window_manifest_path: Path,
    eligibility_by_key: Mapping[tuple[str, str], Sequence[Mapping[str, str]]],
    eligibility_path: Path,
    checksum_by_path: Mapping[Path, str],
    checksum_path: Path,
    protected: set[Path],
    queue_path: Path,
    allocation_path: Path,
    registry_path: Path,
    observed_source_hashes: dict[Path, str] | None = None,
) -> Candidate:
    reasons: list[str] = []
    cache_root = root / "datasets/aqualoc/rosbags"
    if raw_path.suffix.lower() != ".bag":
        reasons.append("candidate is not a .bag file")
    if not _confined(raw_path, cache_root):
        reasons.append("candidate is outside datasets/aqualoc/rosbags")
    if raw_path.is_symlink() or not raw_path.is_file():
        reasons.append("candidate is missing, non-regular, or symlinked")
    if real_absolute(raw_path) in protected:
        reasons.append("candidate is referenced by an input/output hash manifest")
    if reasons:
        raise ReclamationError("; ".join(reasons))
    _assert_quiescent(raw_path)
    allocation_bindings = _allocation_bindings_for_raw(root, raw_path, queues, allocations)
    if allocation_bindings:
        bound_windows = {item["window_id"] for item in allocation_bindings}
        bound_indices = {int(item["queue_index"]) for item in allocation_bindings}
        if len(bound_windows) != 1 or len(bound_indices) != 3:
            raise ReclamationError(
                "raw cache has non-triplet or future allocation bindings: "
                f"{allocation_bindings}"
            )
        if any(index <= 6 for index in bound_indices):
            raise ReclamationError("raw cache is bound to protected early queue q1-6")
    all_command_logs = command_logs(root)
    (
        window_id,
        queue_records,
        candidate_logs,
        observed_counts,
        raw_line_counts,
        line_count,
        evidence,
    ) = _candidate_queue_records(
        bindings,
        queues,
        allocations,
        registry_rows,
        root,
        all_command_logs,
        queue_path,
        allocation_path,
    )
    if allocation_bindings:
        allocation_indices = {int(item["queue_index"]) for item in allocation_bindings}
        command_indices = {int(item["queue_index"]) for item in queue_records}
        allocation_windows = {str(item["window_id"]) for item in allocation_bindings}
        if allocation_indices != command_indices or allocation_windows != {window_id}:
            raise ReclamationError(
                "command-log triplet differs from deterministic allocation bindings: "
                f"logs={sorted(command_indices)} allocations={allocation_bindings}"
            )
    window = windows.get(window_id)
    if window is None:
        raise ReclamationError(f"window is absent from frozen dataset manifest: {window_id}")
    for record in queue_records:
        allocation = record["allocation"]
        if (
            allocation.get("dataset_family") != window.get("dataset_family")
            or allocation.get("sequence") != window.get("sequence")
        ):
            raise ReclamationError(
                f"queue/allocation identity differs from dataset manifest: {record['queue_index']}"
            )
    source, source_hash, source_evidence = _validate_source(
        root,
        window_id,
        window,
        window_manifest_path,
        eligibility_by_key,
        eligibility_path,
        checksum_by_path,
        checksum_path,
        observed_source_hashes,
    )
    d_path, d_row, d_evidence = _validate_d(root, window_id, window)
    evidence.extend([source, registry_path, *source_evidence])
    evidence.extend([d_path, *d_evidence])
    return Candidate(
        path=lexical_absolute(raw_path),
        window_id=window_id,
        queues=queue_records,
        command_logs=candidate_logs,
        command_log_counts=observed_counts,
        raw_bag_line_counts_by_queue=raw_line_counts,
        raw_bag_line_count=line_count,
        size_bytes=raw_path.stat().st_size,
        sha256=sha256(raw_path),
        source_archive_path=source,
        source_archive_sha256=source_hash,
        evidence_paths=_unique_paths(evidence),
    )


def scan(root: Path, window_id: str | None = None) -> tuple[list[Candidate], list[Rejection], dict[str, Any]]:
    """Read-only discovery and governance validation."""

    root = lexical_absolute(root)
    bindings_by_path = discover_raw_bindings(root)
    protected, hash_manifests = protected_raw_paths(root)
    queues, allocations, queue_path, allocation_path = _load_queue_and_allocations(root)
    registry_rows, registry_path = _load_registry(root)
    windows, window_manifest_path = _load_window_manifest(root)
    eligibility, eligibility_path = _load_data_eligibility(root)
    checksums, checksum_path = _load_checksum_manifest(root)
    candidates: list[Candidate] = []
    rejections: list[Rejection] = []
    observed_source_hashes: dict[Path, str] = {}
    for raw_path in sorted(bindings_by_path, key=str):
        bindings = bindings_by_path[raw_path]
        if window_id is not None:
            observed_windows = {
                queues[b.queue_index]["window_id"]
                for b in bindings
                if b.queue_index is not None and b.queue_index in queues
            }
            if window_id not in observed_windows:
                continue
        try:
            candidates.append(
                _evaluate(
                    root,
                    raw_path,
                    bindings,
                    queues,
                    allocations,
                    registry_rows,
                    windows,
                    window_manifest_path,
                    eligibility,
                    eligibility_path,
                    checksums,
                    checksum_path,
                    protected,
                    queue_path,
                    allocation_path,
                    registry_path,
                    observed_source_hashes,
                )
            )
        except (ReclamationError, OSError, ValueError) as exc:
            rejections.append(
                Rejection(
                    path=raw_path,
                    reasons=[str(exc)],
                    command_logs=_unique_paths([binding.command_log for binding in bindings]),
                    raw_bag_line_count=sum(binding.occurrences for binding in bindings),
                )
            )
    context = {
        "queue_path": display_path(root, queue_path),
        "allocation_path": display_path(root, allocation_path),
        "run_registry_path": display_path(root, registry_path),
        "window_manifest_path": display_path(root, window_manifest_path),
        "data_eligibility_manifest_path": display_path(root, eligibility_path),
        "dataset_checksum_manifest_path": display_path(root, checksum_path),
        "hash_manifest_paths": [display_path(root, path) for path in hash_manifests],
        "discovered_raw_cache_count": len(bindings_by_path),
    }
    return candidates, rejections, context


def _fsync_directory(path: Path) -> None:
    fd = os.open(os.fspath(path), os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _active_processes_for_path(path: Path) -> list[dict[str, Any]]:
    """Return processes which still refer to ``path``.

    P07 raw-bag generation opens its destination directly, without taking the
    reclamation lock.  Looking at both open file descriptors and process
    arguments/environment therefore gives the reclaim operation a conservative
    producer/consumer quiescence check.  Any procfs race or permission error
    is ignored here; the subsequent inode/hash check remains authoritative and
    the caller can fail closed on an explicit match.
    """

    path = lexical_absolute(path)
    try:
        target_stat = path.stat()
    except OSError:
        return []
    aliases = {
        os.fspath(path),
        os.fspath(real_absolute(path)),
    }
    matches: list[dict[str, Any]] = []
    proc_root = Path("/proc")
    for proc in proc_root.iterdir():
        if not proc.name.isdigit() or int(proc.name) == os.getpid():
            continue
        pid = int(proc.name)
        evidence: set[str] = set()
        try:
            cmdline_bytes = (proc / "cmdline").read_bytes()
            cmdline_parts = [part.decode("utf-8", "replace") for part in cmdline_bytes.split(b"\0") if part]
            cmdline = " ".join(cmdline_parts)
            if any(alias in cmdline for alias in aliases):
                evidence.add("command_line")
        except OSError:
            cmdline = ""
        try:
            environ = (proc / "environ").read_bytes().decode("utf-8", "replace")
            if any(alias in environ for alias in aliases):
                evidence.add("environment")
        except OSError:
            pass
        try:
            for fd_entry in (proc / "fd").iterdir():
                try:
                    fd_stat = fd_entry.stat()
                except OSError:
                    continue
                if fd_stat.st_dev == target_stat.st_dev and fd_stat.st_ino == target_stat.st_ino:
                    evidence.add("open_file_descriptor")
                    break
        except OSError:
            pass
        if evidence:
            matches.append(
                {
                    "pid": pid,
                    "evidence": sorted(evidence),
                    "command": cmdline[:400],
                }
            )
    return sorted(matches, key=lambda item: int(item["pid"]))


def _assert_quiescent(path: Path) -> None:
    active = _active_processes_for_path(path)
    if active:
        details = "; ".join(
            f"pid={item['pid']} evidence={','.join(item['evidence'])} command={item['command']}"
            for item in active
        )
        raise ReclamationError(f"active process still references raw cache: {path} ({details})")


def _revalidate_before_unlink(path: Path, candidate: Candidate, root: Path) -> None:
    """Recheck confinement, inode type, bytes, digest, and process quiescence."""

    if path.is_symlink() or not path.is_file() or not _confined(path, root / "datasets/aqualoc/rosbags"):
        raise ReclamationError(f"candidate changed or escaped before unlink: {path}")
    observed_stat = path.stat()
    observed_hash = sha256(path)
    if observed_stat.st_size != candidate.size_bytes or observed_hash != candidate.sha256:
        raise ReclamationError(f"candidate changed before unlink: {path}")
    _assert_quiescent(path)


def _atomic_no_clobber_json(path: Path, payload: Mapping[str, Any]) -> None:
    """Publish a complete JSON file atomically and refuse a name collision."""

    path.parent.mkdir(parents=True, exist_ok=True)
    content = (json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=True) + "\n").encode("utf-8")
    temporary = path.with_name(f".{path.name}.partial.{os.getpid()}.{secrets.token_hex(8)}")
    fd = os.open(os.fspath(temporary), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        # link() publishes the already-fsynced inode without replacing an
        # existing receipt.  It is atomic on the same filesystem.
        os.link(os.fspath(temporary), os.fspath(path))
        _fsync_directory(path.parent)
    except Exception:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass
        raise
    else:
        temporary.unlink()
        _fsync_directory(path.parent)


@contextmanager
def _execute_lock(root: Path) -> Iterator[None]:
    directory = root / "papers/ieee_sensors_journal_experiments/p07/raw_cache_reclamation"
    if directory.is_symlink():
        raise ReclamationError(f"reclamation directory is a symlink: {directory}")
    directory.mkdir(parents=True, exist_ok=True)
    lock_path = directory / LOCK_NAME
    fd = os.open(os.fspath(lock_path), os.O_CREAT | os.O_RDWR, 0o644)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        try:
            fcntl.flock(fd, fcntl.LOCK_UN)
        finally:
            os.close(fd)


def _unique_event_id(existing: set[str]) -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    while True:
        event_id = f"p07-raw-cache-reclaim-{stamp}-{os.getpid()}-{secrets.token_hex(4)}"
        if event_id not in existing:
            return event_id


@contextmanager
def _locked_ledger(root: Path) -> Iterator[dict[str, Any]]:
    """Validate and exclusively lock the ledger before any destructive step."""

    path = root / "papers/ieee_sensors_journal_experiments/execution_ledger.jsonl"
    if path.is_symlink():
        raise ReclamationError(f"execution ledger is a symlink: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            handle.seek(0)
            content = handle.read()
            try:
                text = content.decode("utf-8")
            except UnicodeDecodeError as exc:
                raise ReclamationError("execution ledger is not UTF-8") from exc
            existing_ids: set[str] = set()
            for line_number, line in enumerate(text.splitlines(), 1):
                if not line.strip():
                    continue
                try:
                    payload = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise ReclamationError(f"invalid execution ledger JSON at line {line_number}") from exc
                if not isinstance(payload, Mapping):
                    raise ReclamationError(f"invalid execution ledger event at line {line_number}")
                if payload.get("event_id"):
                    existing_ids.add(str(payload["event_id"]))
            yield {
                "handle": handle,
                "path": path,
                "event_ids": existing_ids,
                "prefix_size_bytes": len(content),
                "prefix_sha256": hashlib.sha256(content).hexdigest(),
            }
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _append_locked_ledger(state: Mapping[str, Any], event: Mapping[str, Any]) -> dict[str, Any]:
    handle = state["handle"]
    event_payload = dict(event)
    event_payload["event_id"] = _unique_event_id(set(state["event_ids"]))
    event_payload["ledger_prefix_size_bytes"] = int(state["prefix_size_bytes"])
    event_payload["ledger_prefix_sha256"] = str(state["prefix_sha256"])
    encoded = (
        json.dumps(event_payload, sort_keys=True, ensure_ascii=True, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")
    handle.seek(0, os.SEEK_END)
    handle.write(encoded)
    handle.flush()
    os.fsync(handle.fileno())
    _fsync_directory(Path(state["path"]).parent)
    return event_payload


def _append_ledger(root: Path, event: Mapping[str, Any]) -> dict[str, Any]:
    """Append one event under the same validated-lock contract used by execute."""

    with _locked_ledger(root) as state:
        return _append_locked_ledger(state, event)


def _execute_candidate(root: Path, candidate: Candidate, context: Mapping[str, Any]) -> dict[str, Any]:
    path = candidate.path
    _revalidate_before_unlink(path, candidate, root)
    recorded_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    receipt_dir = root / "papers/ieee_sensors_journal_experiments/p07/raw_cache_reclamation"
    # A prior authorization for the same bytes is never overwritten or
    # retried silently.  This also makes a crash between receipt and unlink
    # fail closed on the next invocation.
    prior_receipts = sorted(receipt_dir.glob(f"receipt-{candidate.sha256[:16]}-*.json"))
    if prior_receipts:
        raise FileExistsError(f"File exists: existing reclamation receipt for candidate: {prior_receipts[0]}")
    receipt_name = f"receipt-{candidate.sha256[:16]}-{secrets.token_hex(8)}.json"
    receipt_path = receipt_dir / receipt_name
    receipt = {
        "schema_version": SCHEMA,
        "receipt_id": receipt_path.stem,
        "status": "AUTHORIZED_BEFORE_UNLINK",
        "recorded_at": recorded_at,
        "mode": "EXECUTE",
        "raw_cache_path": display_path(root, path),
        "raw_cache_size_bytes": candidate.size_bytes,
        "raw_cache_sha256": candidate.sha256,
        "source_archive_path": display_path(root, candidate.source_archive_path),
        "source_archive_sha256": candidate.source_archive_sha256,
        "window_id": candidate.window_id,
        "queues": candidate.as_dict(root)["queues"],
        "run_ids": candidate.as_dict(root)["run_ids"],
        "command_logs": candidate.as_dict(root)["command_logs"],
        "command_log_counts": candidate.command_log_counts,
        "raw_bag_line_count": candidate.raw_bag_line_count,
        "raw_bag_line_counts_by_queue": candidate.raw_bag_line_counts_by_queue,
        "evidence_paths": candidate.as_dict(root)["evidence_paths"],
        "outcome_boundary": "P07_FRONTEND_ONLY_NO_TRAJECTORY_OUTCOME",
        "held_out_trajectory_outcome_read": False,
        "deletion": {
            "pre_delete_exists": True,
            "pre_delete_size_bytes": candidate.size_bytes,
            "pre_delete_sha256": candidate.sha256,
        },
    }
    with _locked_ledger(root) as ledger_state:
        _atomic_no_clobber_json(receipt_path, receipt)
        receipt_size = receipt_path.stat().st_size
        receipt_hash = sha256(receipt_path)
        # The receipt is durable before this final check and unlink.  A
        # producer which starts after the scan is therefore reported without
        # risking deletion of changed bytes.
        _revalidate_before_unlink(path, candidate, root)
        os.unlink(path)
        _fsync_directory(path.parent)
        event = {
            "schema_version": SCHEMA,
            "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "stage": "P07",
            "event_type": "RAW_CACHE_RECLAIMED",
            "status": "PASS",
            "actor": "reclaim_p07_raw_cache_v1",
            "mode": "EXECUTE",
            "window_id": candidate.window_id,
            "queues": candidate.as_dict(root)["queues"],
            "run_ids": candidate.as_dict(root)["run_ids"],
            "arms": candidate.as_dict(root)["arms"],
            "raw_cache_path": display_path(root, path),
            "raw_cache_size_bytes": candidate.size_bytes,
            "raw_cache_sha256": candidate.sha256,
            "source_archive_path": display_path(root, candidate.source_archive_path),
            "source_archive_sha256": candidate.source_archive_sha256,
            "command_logs": candidate.as_dict(root)["command_logs"],
            "command_log_counts": candidate.command_log_counts,
            "raw_bag_line_count": candidate.raw_bag_line_count,
            "raw_bag_line_counts_by_queue": candidate.raw_bag_line_counts_by_queue,
            "evidence_paths": candidate.as_dict(root)["evidence_paths"],
            "receipt_path": display_path(root, receipt_path),
            "receipt_size_bytes": receipt_size,
            "receipt_sha256": receipt_hash,
            "deleted": True,
            "bytes_freed": candidate.size_bytes,
            "outcome_boundary": "P07_FRONTEND_ONLY_NO_TRAJECTORY_OUTCOME",
            "held_out_trajectory_outcome_read": False,
            "self_contained": True,
        }
        appended = _append_locked_ledger(ledger_state, event)
    return {"receipt": receipt, "receipt_path": receipt_path, "ledger_event": appended}


def run(root: Path | None = None, *, execute: bool = False, window_id: str | None = None) -> dict[str, Any]:
    """Run a dry scan or, with ``execute=True``, reclaim validated caches."""

    root = lexical_absolute(ROOT if root is None else root)
    if execute:
        with _execute_lock(root):
            candidates, rejections, context = scan(root, window_id)
            executed: list[dict[str, Any]] = []
            execution_errors: list[dict[str, Any]] = []
            for candidate in candidates:
                try:
                    result = _execute_candidate(root, candidate, context)
                    executed.append(
                        {
                            "raw_cache_path": display_path(root, candidate.path),
                            "receipt_path": display_path(root, result["receipt_path"]),
                            "event_id": result["ledger_event"]["event_id"],
                            "bytes_freed": candidate.size_bytes,
                        }
                    )
                except (OSError, ReclamationError) as exc:
                    execution_errors.append(
                        {"raw_cache_path": display_path(root, candidate.path), "reason": str(exc)}
                    )
            mode = "EXECUTE"
    else:
        candidates, rejections, context = scan(root, window_id)
        executed = []
        execution_errors = []
        mode = "DRY_RUN"
    return {
        "schema_version": SCHEMA,
        "mode": mode,
        "dry_run": mode == "DRY_RUN",
        "status": "PARTIAL" if execution_errors else "PASS",
        "execute_required_for_deletion": True,
        "candidates": [candidate.as_dict(root) for candidate in candidates],
        "rejected": [item.as_dict(root) for item in rejections],
        "executed": executed,
        "execution_errors": execution_errors,
        "bytes_reclaimable": sum(candidate.size_bytes for candidate in candidates),
        "bytes_freed": sum(int(item.get("bytes_freed", 0)) for item in executed),
        "context": context,
    }


def discover_candidates(root: Path | None = None, window_id: str | None = None) -> tuple[list[Candidate], list[Rejection]]:
    """Compatibility helper used by focused tests and callers."""

    candidates, rejections, _context = scan(ROOT if root is None else root, window_id)
    return candidates, rejections


def reclaim(root: Path | None = None, *, execute: bool = False, window_id: str | None = None) -> dict[str, Any]:
    """Named alias for callers that treat reclamation as an operation."""

    return run(root, execute=execute, window_id=window_id)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT, help="workspace root (fixture override)")
    parser.add_argument("--window-id", help="restrict discovery to one window")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--execute",
        action="store_true",
        help="unlink validated caches; without this flag the command is a dry run",
    )
    mode.add_argument(
        "--dry-run",
        action="store_true",
        help="explicitly request the default read-only mode",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    report = run(args.root, execute=args.execute, window_id=args.window_id)
    print(json.dumps(report, indent=2, sort_keys=True, ensure_ascii=True))
    return 1 if report["execution_errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
