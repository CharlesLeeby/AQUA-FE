#!/usr/bin/env python3
"""Freeze the additive queue-55 A04 archive-layout replacement contract.

This builder never edits the canonical queue, allocation, or registry.  It
freezes the already-terminal FAILED q55 chain and allocates a distinct
attempt02 identity whose scientific command differs only in ``TAG_BASE``.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import secrets
import tarfile
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

try:
    from scripts import audit_p07_frontend_export_v3 as frontend_audit
    from scripts import build_p07_preoutcome_governance_v1 as governance
    from scripts import run_p07_frontend_queue_v6 as v6_queue
    from scripts import run_p07_mp_frontend_export_job_v2 as registry
except ModuleNotFoundError:  # Direct ``python3 scripts/...`` execution.
    import audit_p07_frontend_export_v3 as frontend_audit  # type: ignore
    import build_p07_preoutcome_governance_v1 as governance  # type: ignore
    import run_p07_frontend_queue_v6 as v6_queue  # type: ignore
    import run_p07_mp_frontend_export_job_v2 as registry  # type: ignore


SCHEMA = "isj-p07-a04-layout-replacement-lock-v1"
STATUS = "FROZEN_READY_FOR_Q55_A04_LAYOUT_ATTEMPT02_RECOVERY"
SELF_HASH_FIELD = "replacement_lock_hash"
OUTCOME_BOUNDARY = "FRONTEND_EXPORT_ONLY_NO_VINS_APE_RPE_TRAJECTORY"
REASON_CODE = "AQUALOC_ARCHIVE_ROOT_LAYOUT_MISMATCH"
ORIGINAL_QUEUE_INDEX = 55
WINDOW_ID = "aqualoc_archaeology:A04:0002"
ORIGINAL_TAG = "isj_p07_aqualoc_archaeology_a04_0002_p_attempt01"
REPLACEMENT_TAG = "isj_p07_aqualoc_archaeology_a04_0002_p_attempt02"
REPLACEMENT_SUFFIX = "_layout_attempt02"
EXPECTED_TOPIC_COUNTS = {
    "/camera/image_raw": 901,
    "/rtimulib_node/imu": 9091,
    "/aqualoc/colmap_gt": 44,
}
EXPECTED_ARCHIVE_IMAGE_ROWS = 13385
ACTION_ORDER = [
    "register",
    "materialize",
    "execute",
    "closeout",
    "resume-preflight/resume-execute:56",
    "resume-preflight/resume-execute:57",
    "build-a04-d-resolution-lock-v4",
    "resolve-a04-d-v4",
    "reclaim-a04-raw-cache",
    "resume-preflight/resume-execute:58",
    "resume-preflight/resume-execute:59",
    "resume-preflight/resume-execute:60",
    "resolve-final-window-d-v3",
]

ROOT = governance.ROOT
P07 = governance.P07
REPLACEMENT_ROOT = P07 / "frontend_replacements"
OUTPUT = REPLACEMENT_ROOT / "queue_055_a04_layout_attempt02_lock_v1.json"
CLOSEOUT = REPLACEMENT_ROOT / "queue_055_a04_layout_attempt02_closeout_v1.json"
REGISTRATION = REPLACEMENT_ROOT / "queue_055_a04_layout_attempt02_registration_v1.json"
LEDGER = REPLACEMENT_ROOT / "replacement_ledger_v1.jsonl"
RECLAIM_CLOSEOUT = (
    REPLACEMENT_ROOT / "queue_055_a04_layout_attempt02_raw_reclaim_closeout_v1.json"
)
ATTEMPT_DIR = (
    P07 / "frontend_attempts" / f"queue_055_{REPLACEMENT_TAG}"
)
ORIGINAL_ATTEMPT_DIR = (
    P07 / "frontend_attempts" / f"queue_055_{ORIGINAL_TAG}"
)
RAW_ARCHIVE = (
    ROOT
    / "datasets/full_downloads/aqualoc/Archaeological_site_sequences/"
    "archaeo_sequence_4_raw_data.tar.gz"
)
GT_INPUT = (
    ROOT
    / "datasets/full_downloads/aqualoc/Archaeological_site_sequences/"
    "archaeo_groundtruth_files/new_archaeo_colmap_traj_sequence_04.txt"
)
RAW_BAG = ROOT / "datasets/aqualoc/rosbags/archaeo04_1800_2700.bag"
ARCHIVE_SHA256 = "b81d03e63a112e6d9bc3f7ae9855f3e183c93c7897b87deb136e705bb574109e"
GT_SHA256 = "7b6242a9046e5894143f39e2d60b98dcddfd33f8ff2a13d3157ba88ceda878d5"


class ReplacementLockError(RuntimeError):
    """Raised when the q55 correction cannot be frozen without ambiguity."""


def now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def document_hash(payload: dict[str, Any], field: str = SELF_HASH_FIELD) -> str:
    clone = dict(payload)
    clone.pop(field, None)
    encoded = json.dumps(
        clone, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def display_path(path: Path) -> str:
    return frontend_audit.display_path(path)


def file_record(path: Path, *, expected_sha256: str | None = None) -> dict[str, Any]:
    if not path.is_file() or path.is_symlink():
        raise FileNotFoundError(path)
    observed = sha256(path)
    if expected_sha256 is not None and observed != expected_sha256:
        raise ReplacementLockError(
            f"checksum mismatch for {path}: {observed} != {expected_sha256}"
        )
    return {
        "path": display_path(path),
        "sha256": observed,
        "size_bytes": path.stat().st_size,
    }


def prefix_snapshot(path: Path) -> dict[str, Any]:
    content = path.read_bytes()
    return {
        "path": display_path(path),
        "sha256": hashlib.sha256(content).hexdigest(),
        "size_bytes": len(content),
    }


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        fields = list(reader.fieldnames or [])
        rows = list(reader)
    if not fields or len(fields) != len(set(fields)) or any(None in row for row in rows):
        raise ReplacementLockError(f"invalid CSV: {path}")
    return [dict(row) for row in rows]


def replacement_run_id(original_run_id: str) -> str:
    if not original_run_id or original_run_id.endswith(REPLACEMENT_SUFFIX):
        raise ReplacementLockError("invalid original run_id")
    return original_run_id + REPLACEMENT_SUFFIX


def build_effective_queue_row(original: dict[str, str]) -> dict[str, str]:
    if original.get("tag") != ORIGINAL_TAG:
        raise ReplacementLockError("q55 original tag mismatch")
    old_token = f"TAG_BASE={ORIGINAL_TAG}"
    new_token = f"TAG_BASE={REPLACEMENT_TAG}"
    command = original.get("command", "")
    if command.count(old_token) != 1 or REPLACEMENT_TAG in command:
        raise ReplacementLockError("q55 command does not contain one exact original tag")
    effective = dict(original)
    effective["tag"] = REPLACEMENT_TAG
    effective["command"] = command.replace(old_token, new_token, 1)
    effective["command_sha256"] = hashlib.sha256(
        effective["command"].encode("utf-8")
    ).hexdigest()
    assert_tag_only_command_diff(original, effective)
    return effective


def assert_tag_only_command_diff(
    original: dict[str, str], effective: dict[str, str]
) -> None:
    changed_fields = {
        key for key in set(original) | set(effective) if original.get(key) != effective.get(key)
    }
    if changed_fields != {"tag", "command", "command_sha256"}:
        raise ReplacementLockError(
            f"effective queue row changes non-governance fields: {sorted(changed_fields)}"
        )
    old_command = original["command"]
    expected = old_command.replace(
        f"TAG_BASE={ORIGINAL_TAG}", f"TAG_BASE={REPLACEMENT_TAG}", 1
    )
    if effective["command"] != expected:
        raise ReplacementLockError("replacement command is not an exact tag-only rewrite")
    if hashlib.sha256(effective["command"].encode()).hexdigest() != effective[
        "command_sha256"
    ]:
        raise ReplacementLockError("replacement command hash mismatch")


def build_effective_allocation_row(
    original: dict[str, str], effective_queue: dict[str, str], *, allocated_at: str
) -> dict[str, str]:
    effective = dict(original)
    effective.update(
        {
            "run_id": replacement_run_id(original["run_id"]),
            "allocated_at": allocated_at,
            "tag": effective_queue["tag"],
            "command_sha256": effective_queue["command_sha256"],
            "command_source": (
                display_path(OUTPUT) + "#replacement.effective_queue_row"
            ),
            "status": "PLANNED",
        }
    )
    return effective


def validate_original_failure_chain(
    chain: Iterable[dict[str, str]], original_run_id: str
) -> list[dict[str, str]]:
    observed = [dict(row) for row in chain]
    if len(observed) != 3 or [row.get("status") for row in observed] != [
        "PLANNED",
        "RUNNING",
        "FAILED",
    ]:
        raise ReplacementLockError("q55 must have exact e00/e01/e02 FAILED chain")
    for index, row in enumerate(observed):
        event = f"{original_run_id}_e{index:02d}"
        parent = "" if index == 0 else f"{original_run_id}_e{index - 1:02d}"
        if (
            row.get("run_id") != original_run_id
            or row.get("registry_event_id") != event
            or row.get("supersedes_event_id") != parent
        ):
            raise ReplacementLockError("q55 registry failure chain is not contiguous")
    terminal = observed[-1]
    if (
        terminal.get("infrastructure_failure") != "false"
        or terminal.get("command_file")
        != display_path(ORIGINAL_ATTEMPT_DIR / "command.txt")
        or "frontend export command failed rc=1" not in terminal.get("notes", "")
    ):
        raise ReplacementLockError("q55 terminal failure identity mismatch")
    return observed


def validate_archive_layout(path: Path) -> dict[str, Any]:
    """Prove the A04 archive is root-layout and contains the frozen window."""

    with tarfile.open(path, "r:*") as archive:
        names = set(archive.getnames())
        required = {"img_sequence_4.csv", "imu_sequence_4.csv", "images_sequence_4"}
        missing = sorted(required - names)
        if missing:
            raise ReplacementLockError(f"A04 root-layout members missing: {missing}")
        if "raw_data/img_sequence_4.csv" in names:
            raise ReplacementLockError("A04 archive unexpectedly contains legacy raw_data root")
        handle = archive.extractfile("img_sequence_4.csv")
        if handle is None:
            raise ReplacementLockError("cannot read A04 image CSV")
        rows = [
            row
            for row in csv.reader(line.decode("utf-8") for line in handle.readlines())
            if row and not row[0].startswith("#")
        ]
        if len(rows) != EXPECTED_ARCHIVE_IMAGE_ROWS:
            raise ReplacementLockError(
                f"A04 image row count {len(rows)} != {EXPECTED_ARCHIVE_IMAGE_ROWS}"
            )
        window = rows[1800:2701]
        if len(window) != EXPECTED_TOPIC_COUNTS["/camera/image_raw"]:
            raise ReplacementLockError("A04 frozen window does not contain 901 image rows")
        missing_images = [
            row[1]
            for row in window
            if len(row) < 2 or f"images_sequence_4/{row[1]}" not in names
        ]
        if missing_images:
            raise ReplacementLockError(
                f"A04 frozen window references missing images: {missing_images[:3]}"
            )
    return {
        "archive_layout": "MEMBERS_AT_ARCHIVE_ROOT",
        "raw_root_argv": "",
        "required_members": [
            "img_sequence_4.csv",
            "imu_sequence_4.csv",
            "images_sequence_4/",
        ],
        "forbidden_legacy_member": "raw_data/img_sequence_4.csv",
        "archive_image_rows": EXPECTED_ARCHIVE_IMAGE_ROWS,
        "window_image_rows": EXPECTED_TOPIC_COUNTS["/camera/image_raw"],
    }


def materialization_argv_template() -> list[str]:
    return [
        "python3",
        "-m",
        "uw_frontend.datasets.aqualoc_raw_to_rosbag",
        "--input",
        display_path(RAW_ARCHIVE),
        "--output-bag",
        "{TEMP_OUTPUT_BAG}",
        "--sequence-name",
        "archaeo_sequence_4",
        "--raw-root",
        "",
        "--image-dir",
        "images_sequence_4",
        "--image-csv",
        "img_sequence_4.csv",
        "--imu-csv",
        "imu_sequence_4.csv",
        "--gt-txt",
        display_path(GT_INPUT),
        "--start-index",
        "1800",
        "--end-index",
        "2700",
        "--image-topic",
        "/camera/image_raw",
        "--imu-topic",
        "/rtimulib_node/imu",
        "--gt-topic",
        "/aqualoc/colmap_gt",
    ]


def required_artifact_paths() -> list[Path]:
    return [
        P07 / "frontend_export_queue_v1.csv",
        P07 / "frontend_run_allocation_v1.csv",
        P07 / "frontend_orchestration_correction_lock_v6.json",
        P07 / "frontend_execution_correction_lock_v5.json",
        ROOT / "papers/ieee_sensors_journal_experiments/dataset_checksum_manifest.txt",
        ROOT / "papers/ieee_sensors_journal_experiments/p06/screening_runs/aqualoc_archaeology/A04/screening_run.json",
        ORIGINAL_ATTEMPT_DIR / "command.txt",
        ORIGINAL_ATTEMPT_DIR / "command.log",
        ORIGINAL_ATTEMPT_DIR / "input_hash_manifest.sha256",
        ORIGINAL_ATTEMPT_DIR / "capacity_preflight.json",
        ORIGINAL_ATTEMPT_DIR / "guard_preflight_command.txt",
        ORIGINAL_ATTEMPT_DIR / "guard_preflight.log",
        ROOT / "scripts/run_isj_nativeq_contract_guarded_v4.sh",
        ROOT / "scripts/run_aqualoc_archaeo_vins_eval.sh",
        ROOT / "uw_frontend/datasets/aqualoc_raw_to_rosbag.py",
        ROOT / "scripts/run_p07_frontend_export_job_v5.py",
        ROOT / "scripts/run_p07_frontend_queue_v4.py",
        ROOT / "scripts/audit_p07_frontend_export_v4.py",
        ROOT / "scripts/audit_p07_frontend_export_v3.py",
        ROOT / "scripts/resolve_p07_d_applicability_v2.py",
        ROOT / "scripts/build_p07_d_resolution_lock_v4.py",
        ROOT / "scripts/resolve_p07_d_applicability_v4.py",
        ROOT / "scripts/tests/test_p07_d_resolution_v4.py",
        ROOT / "scripts/run_p07_mp_frontend_export_job_v2.py",
        ROOT / "scripts/reclaim_p07_raw_cache_v1.py",
        ROOT / "scripts/build_p07_q55_a04_layout_replacement_lock_v1.py",
        ROOT / "scripts/run_p07_q55_a04_layout_replacement_v1.py",
        ROOT / "scripts/tests/test_p07_q55_a04_layout_replacement_v1.py",
        RAW_ARCHIVE,
        GT_INPUT,
    ]


def build_payload(
    *,
    frozen_at: str,
    original_queue: dict[str, str],
    original_allocation: dict[str, str],
    original_chain: list[dict[str, str]],
    artifacts: list[dict[str, Any]],
    stream_snapshots: list[dict[str, Any]],
    archive_layout: dict[str, Any],
) -> dict[str, Any]:
    effective_queue = build_effective_queue_row(original_queue)
    effective_allocation = build_effective_allocation_row(
        original_allocation, effective_queue, allocated_at=frozen_at
    )
    new_run_id = effective_allocation["run_id"]
    payload: dict[str, Any] = {
        "schema_version": SCHEMA,
        "status": STATUS,
        "frozen_at": frozen_at,
        "original_queue_index": ORIGINAL_QUEUE_INDEX,
        "original_run_id": original_allocation["run_id"],
        "replacement_run_id": new_run_id,
        "replacement_tag": REPLACEMENT_TAG,
        "original": {
            "queue_row": original_queue,
            "allocation_row": original_allocation,
            "registry_failure_chain": original_chain,
            "canonical_chain_must_remain_terminal_failed": True,
            "failed_attempt_preserved": display_path(ORIGINAL_ATTEMPT_DIR),
        },
        "replacement": {
            "run_id": new_run_id,
            "tag": REPLACEMENT_TAG,
            "command": effective_queue["command"],
            "command_sha256": effective_queue["command_sha256"],
            "effective_queue_row": effective_queue,
            "effective_allocation_row": effective_allocation,
            "attempt_dir": display_path(ATTEMPT_DIR),
            "registration_path": display_path(REGISTRATION),
            "closeout_path": display_path(CLOSEOUT),
            "replacement_for": {
                "original_queue_index": ORIGINAL_QUEUE_INDEX,
                "original_run_id": original_allocation["run_id"],
                "original_failed_registry_event_id": original_chain[-1][
                    "registry_event_id"
                ],
                "reason_code": REASON_CODE,
            },
            "physical_frontend_rerun": True,
            "scientific_command_change_scope": ["TAG_BASE"],
            "scientific_parameters_changed": False,
        },
        "raw_materialization": {
            "source_archive": display_path(RAW_ARCHIVE),
            "source_archive_sha256": ARCHIVE_SHA256,
            "ground_truth_input": display_path(GT_INPUT),
            "ground_truth_sha256": GT_SHA256,
            "target_raw_bag": display_path(RAW_BAG),
            "converter_argv_template": materialization_argv_template(),
            "layout": archive_layout,
            "expected_topic_counts": EXPECTED_TOPIC_COUNTS,
            "atomic_publish": "HARDLINK_NOREPLACE_THEN_UNLINK_TEMP",
            "raw_bag_is_reproducible_cache": True,
            "raw_bag_must_not_enter_replacement_output_manifest": True,
        },
        "action_order": ACTION_ORDER,
        "allowed_remaining_indices": list(range(56, 61)),
        "remaining_queue_policy": {
            "canonical_rows_allocations_commands_unchanged": True,
            "only_dependency_override": "QUEUE_55_EFFECTIVE_SLOT_COMPLETED_BY_REPLACEMENT",
            "require_a04_d_terminal_before_queue_index_58_plus": True,
        },
        "replacement_ledger": {
            "path": display_path(LEDGER),
            "schema_version": "isj-p07-frontend-replacement-ledger-event-v1",
            "append_only": True,
        },
        "crash_policy": {
            "ordinary_exception_after_attempt_creation": (
                "APPEND_REPLACEMENT_RUNNING_THEN_FAILED_WITH_PHASE_EVIDENCE"
            ),
            "exact_e00_sidecar_gap": "RECONCILE_ONLY_IF_E00_BYTE_EXACT",
            "process_loss_or_partial_unknown_state": (
                "FAIL_CLOSED_REQUIRES_NEW_ADDITIVE_REPLACEMENT_GOVERNANCE"
            ),
            "canonical_original_chain_mutation_allowed": False,
        },
        "capacity_gate": {
            # Preserve the 3 GiB frontend floor after publishing a raw cache
            # whose deliberately conservative upper bound is 512 MiB.
            "raw_cache_upper_bound_bytes": 512 * 1024**2,
            "raw_materialization_minimum_free_bytes": 3 * 1024**3 + 512 * 1024**2,
            "frontend_output_minimum_free_bytes": 3 * 1024**3,
            "governance_minimum_free_bytes": 512 * 1024**2,
        },
        "raw_cache_reclamation": {
            "executor": "scripts/reclaim_p07_raw_cache_v1.py",
            "allowed_only_after_replacement_closeout": True,
            "required_completed_queue_indices": [56, 57],
            "required_terminal_d_window": WINDOW_ID,
            "replacement_aware_allocation_overlay_required": True,
            "source_archive_reverified_before_unlink": True,
            "raw_bag_excluded_from_replacement_output_manifest": True,
            "replacement_binding_sidecar": display_path(RECLAIM_CLOSEOUT),
        },
        "artifacts": artifacts,
        "mutable_stream_prefix_snapshots": stream_snapshots,
        "outcome_boundary": OUTCOME_BOUNDARY,
        "trajectory_outcome_read": False,
        "vins_execution_allowed": False,
    }
    payload[SELF_HASH_FIELD] = document_hash(payload)
    return payload


def _validate_precedent() -> None:
    path = (
        ROOT
        / "papers/ieee_sensors_journal_experiments/p06/screening_runs/"
        "aqualoc_archaeology/A04/screening_run.json"
    )
    payload = json.loads(path.read_text(encoding="utf-8"))
    text = json.dumps(payload, sort_keys=True)
    if "13385" not in text or "contract_pass" not in text or "true" not in text.lower():
        raise ReplacementLockError("A04 outcome-blind screening layout precedent mismatch")


def build_lock() -> dict[str, Any]:
    if OUTPUT.exists():
        raise FileExistsError(OUTPUT)
    v6_queue.validate_lock(ORIGINAL_QUEUE_INDEX, ORIGINAL_QUEUE_INDEX)
    original_queue = frontend_audit.queue_row(ORIGINAL_QUEUE_INDEX)
    original_allocation = frontend_audit.allocation_row(ORIGINAL_QUEUE_INDEX)
    if (
        original_queue.get("window_id") != WINDOW_ID
        or original_queue.get("arm") != governance.P_ARM
        or original_allocation.get("window_id") != WINDOW_ID
    ):
        raise ReplacementLockError("canonical q55 identity mismatch")
    chain = validate_original_failure_chain(
        registry.registry_chain(original_allocation["run_id"]),
        original_allocation["run_id"],
    )
    if registry.registry_chain(replacement_run_id(original_allocation["run_id"])):
        raise ReplacementLockError("replacement registry identity already exists")
    for index, expected in ((54, "COMPLETED"), (56, "PLANNED"), (57, "PLANNED")):
        allocation = frontend_audit.allocation_row(index)
        status = registry.registry_chain(allocation["run_id"])[-1]["status"]
        if status != expected:
            raise ReplacementLockError(f"queue {index} status {status} != {expected}")
    failure_log = (ORIGINAL_ATTEMPT_DIR / "command.log").read_text(
        encoding="utf-8", errors="replace"
    )
    if (
        "filename 'raw_data/img_sequence_4.csv' not found" not in failure_log
        or "KeyError" not in failure_log
    ):
        raise ReplacementLockError("q55 failure log does not prove archive-root mismatch")
    if (
        RAW_BAG.exists()
        or ATTEMPT_DIR.exists()
        or CLOSEOUT.exists()
        or REGISTRATION.exists()
        or RECLAIM_CLOSEOUT.exists()
    ):
        raise FileExistsError("q55 replacement or raw target collision")
    root = ROOT / original_queue["expected_run_root"]
    collisions = sorted(root.glob(f"*{REPLACEMENT_TAG}*"))
    if collisions:
        raise FileExistsError(f"q55 replacement output collision: {collisions}")
    _validate_precedent()
    archive_layout = validate_archive_layout(RAW_ARCHIVE)
    records: list[dict[str, Any]] = []
    for path in required_artifact_paths():
        expected = ARCHIVE_SHA256 if path == RAW_ARCHIVE else GT_SHA256 if path == GT_INPUT else None
        records.append(file_record(path, expected_sha256=expected))
    return build_payload(
        frozen_at=now(),
        original_queue=original_queue,
        original_allocation=original_allocation,
        original_chain=chain,
        artifacts=records,
        stream_snapshots=[prefix_snapshot(governance.BUNDLE / "run_registry.csv")],
        archive_layout=archive_layout,
    )


def atomic_no_clobber_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    content = (json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=True) + "\n").encode()
    temporary = path.with_name(
        f".{path.name}.partial.{os.getpid()}.{secrets.token_hex(8)}"
    )
    fd = os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.link(temporary, path)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args()
    if args.output != OUTPUT:
        raise ReplacementLockError("formal lock path is fixed")
    payload = build_lock()
    atomic_no_clobber_json(args.output, payload)
    print(f"P07_Q55_A04_LAYOUT_REPLACEMENT_LOCK_PASS hash={payload[SELF_HASH_FIELD]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
