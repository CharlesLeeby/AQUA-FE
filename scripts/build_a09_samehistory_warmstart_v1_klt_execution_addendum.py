#!/usr/bin/env python3
"""Publish the post-hoc execution-strength addendum for the A09 KLT export.

This does not rerun or alter the KLT export.  It is lawful only after the
one-shot KLT supervisor has returned and the canonical output has been
committed as a real directory.  The addendum deliberately narrows claims that
the original v1 receipt cannot prove, while binding a fresh external rehash of
all six accepted KLT control/science files.
"""

from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import secrets
import stat
import sys
from typing import Any, Mapping


ROOT = Path("/home/ma/AQUA-FE_WS")
AUDITOR = Path(__file__).absolute()
EXP_ROOT = Path("/mnt/data/AQUA-FE_WS/experiments/a09_samehistory_system_warmstart_v1")
KLT_DIR = EXP_ROOT / "frontends/klt_export"
FRONTEND_FLOCK = EXP_ROOT / ".frontend_supervisor.flock"
WORKSPACE_LINK = (
    ROOT
    / "logs/aqualoc_archaeo_vins/"
    "external_klt_every2_systemfair_a09_warmstart_v1_feed0000_4400_klt_export"
)
ADDENDUM = ROOT / "papers/a09_samehistory_warmstart_v1_klt_execution_strength_addendum.json"
SCHEMA = "aqua-fe-a09-samehistory-warmstart-klt-execution-strength-addendum-v1"
STATUS = "PASS_POSTHOC_KLT_EXECUTION_STRENGTH_AUDIT"
AUTHORIZATION_TOKEN = "A09_WARMSTART_V1_PUBLISH_KLT_EXECUTION_ADDENDUM_EXACTLY_ONCE"

KLT_FILES = {
    "klt_features": KLT_DIR / "features.bag",
    "klt_metrics": KLT_DIR / "frontend_metrics.csv",
    "klt_camera": KLT_DIR / "aqualoc_archaeo09_pinhole.yaml",
    "klt_claim": KLT_DIR / "process_start_claim_v1.json",
    "klt_receipt": KLT_DIR / "formal_run_receipt_v1.json",
    "klt_log": KLT_DIR / "supervisor_process.log",
}
RECEIPT_OUTPUTS = {
    "features.bag": "klt_features",
    "frontend_metrics.csv": "klt_metrics",
    "aqualoc_archaeo09_pinhole.yaml": "klt_camera",
    "supervisor_process.log": "klt_log",
}
PROCESS_MARKERS = (
    "run_a09_samehistory_warmstart_v1_frontends.py run-klt",
    "run_paper_sidecar_profiles.sh aqualoc_archaeo_loftr_mirror_klt 9 0 4400",
    "run_aqualoc_archaeo_vins_eval.sh external 9 0 4400 klt 2",
    "uw_frontend.ros.export_vins_features --bag "
    "/mnt/data/AQUA-FE_WS/experiments/a09_samehistory_system_warmstart_v1/raw/"
    "archaeo09_0000_4400.bag",
)
EXPECTED_OBSERVED_PGID = 1_508_785
EXPECTED_OBSERVED_PIDS = {
    "supervisor": 1_508_316,
    "group_leader": 1_508_785,
    "science_child": 1_508_829,
}


class AddendumError(RuntimeError):
    """Fail-closed post-hoc audit error."""


def require(condition: bool, code: str) -> None:
    if not condition:
        raise AddendumError(code)


def canonical_bytes(value: Mapping[str, Any]) -> bytes:
    return (
        json.dumps(
            value, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def compact_sha256(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()


def snapshot(path: Path) -> dict[str, Any]:
    path = path.absolute()
    flags = os.O_RDONLY | os.O_CLOEXEC | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as error:
        raise AddendumError(f"OPEN_FAILED:{path}:{error.errno}") from error
    try:
        before = os.fstat(descriptor)
        require(stat.S_ISREG(before.st_mode), f"NOT_REGULAR:{path}")
        digest = hashlib.sha256()
        while True:
            block = os.read(descriptor, 8 * 1024 * 1024)
            if not block:
                break
            digest.update(block)
        after = os.fstat(descriptor)
        fields = ("st_dev", "st_ino", "st_size", "st_mtime_ns", "st_ctime_ns")
        require(
            all(getattr(before, key) == getattr(after, key) for key in fields),
            f"CHANGED_WHILE_HASHING:{path}",
        )
        return {
            "path": str(path),
            "size_bytes": int(after.st_size),
            "sha256": digest.hexdigest(),
        }
    finally:
        os.close(descriptor)


@contextmanager
def frontend_mutex() -> Any:
    require(FRONTEND_FLOCK.is_file() and not FRONTEND_FLOCK.is_symlink(), "FRONTEND_FLOCK_MISSING")
    descriptor = os.open(
        FRONTEND_FLOCK,
        os.O_RDWR | os.O_CLOEXEC | getattr(os, "O_NOFOLLOW", 0),
    )
    try:
        require(stat.S_ISREG(os.fstat(descriptor).st_mode), "FRONTEND_FLOCK_NOT_REGULAR")
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise AddendumError("FRONTEND_SUPERVISOR_STILL_ACTIVE") from error
        yield
    finally:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
        finally:
            os.close(descriptor)


def stable_json(path: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    before = snapshot(path)
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise AddendumError(f"JSON_PARSE:{path}:{type(error).__name__}:{error}") from error
    require(isinstance(value, dict), f"JSON_ROOT:{path}")
    after = snapshot(path)
    require(before == after, f"JSON_CHANGED_DURING_PARSE:{path}")
    return value, after


def proc_stat(pid: int) -> tuple[int, int] | None:
    try:
        text = Path(f"/proc/{pid}/stat").read_text(encoding="ascii")
    except (FileNotFoundError, ProcessLookupError, PermissionError, OSError):
        return None
    close = text.rfind(")")
    if close < 0:
        return None
    fields = text[close + 2 :].split()
    try:
        return int(fields[2]), int(fields[19])  # pgrp, start_ticks
    except (IndexError, ValueError):
        return None


def proc_argv(pid: int) -> list[str] | None:
    try:
        data = Path(f"/proc/{pid}/cmdline").read_bytes()
    except (FileNotFoundError, ProcessLookupError, PermissionError, OSError):
        return None
    if not data:
        return None
    return [part.decode("utf-8", errors="replace") for part in data.split(b"\0") if part]


def posthoc_process_scan(observed_pgid: int, observed_pids: Mapping[str, int]) -> dict[str, Any]:
    require(observed_pgid > 1, "OBSERVED_PGID_RANGE")
    require(set(observed_pids) == {"supervisor", "group_leader", "science_child"}, "OBSERVED_PID_KEYS")
    require(all(type(value) is int and value > 1 for value in observed_pids.values()), "OBSERVED_PID_RANGE")
    require(observed_pgid == EXPECTED_OBSERVED_PGID, "OBSERVED_PGID_NOT_FROZEN_LIVE_OBSERVATION")
    require(dict(observed_pids) == EXPECTED_OBSERVED_PIDS, "OBSERVED_PIDS_NOT_FROZEN_LIVE_OBSERVATION")
    group_members: list[dict[str, Any]] = []
    marker_matches: list[dict[str, Any]] = []
    observed_pid_presence: list[dict[str, Any]] = []
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        pid = int(entry.name)
        stat_row = proc_stat(pid)
        argv = proc_argv(pid)
        if stat_row is not None and stat_row[0] == observed_pgid:
            group_members.append(
                {"pid": pid, "start_ticks": stat_row[1], "argv": argv or []}
            )
        text = " ".join(argv or [])
        hits = [marker for marker in PROCESS_MARKERS if marker in text]
        if hits:
            marker_matches.append(
                {"pid": pid, "start_ticks": stat_row[1] if stat_row else None, "markers": hits}
            )
    for role, pid in sorted(observed_pids.items()):
        row = proc_stat(pid)
        if row is not None:
            observed_pid_presence.append(
                {"role": role, "pid": pid, "pgrp": row[0], "start_ticks": row[1]}
            )
    require(not group_members, f"OBSERVED_PROCESS_GROUP_NOT_EMPTY:{group_members}")
    require(not marker_matches, f"KNOWN_KLT_PROCESS_MARKERS_PRESENT:{marker_matches}")
    require(not observed_pid_presence, f"OBSERVED_PIDS_STILL_PRESENT:{observed_pid_presence}")
    return {
        "status": "PASS_POSTHOC_EMPTY_SNAPSHOT",
        "evidence_scope": "POSTHOC_SNAPSHOT_NOT_CONTINUOUS_OWNERSHIP_PROOF",
        "observed_process_group_id": observed_pgid,
        "observed_process_identifiers": [
            {"role": role, "pid": pid} for role, pid in sorted(observed_pids.items())
        ],
        "process_group_empty": True,
        "owned_descendants_empty": True,
        "owned_descendants_interpretation": (
            "No original-PGID member, observed PID, or known A09 KLT command marker "
            "was present at this post-hoc snapshot; this is not a contemporaneous "
            "proof of descendant emptiness when the leader exited."
        ),
        "observed_process_markers": list(PROCESS_MARKERS),
        "identifier_provenance": (
            "EXTERNAL_ORCHESTRATOR_LIVE_PROC_OBSERVATION_DURING_EXECUTION_"
            "NOT_BOUND_BY_ORIGINAL_V1_RECEIPT"
        ),
        "identifier_provenance_is_original_receipt_bound": False,
        "matching_processes": [],
    }


def canonical_and_rehash_audit() -> tuple[
    dict[str, Any], dict[str, Any], dict[str, dict[str, Any]]
]:
    require(KLT_DIR.exists() and not KLT_DIR.is_symlink(), "KLT_CANONICAL_NOT_REAL")
    info = KLT_DIR.lstat()
    require(stat.S_ISDIR(info.st_mode), "KLT_CANONICAL_NOT_DIRECTORY")
    require(KLT_DIR.resolve(strict=True) == KLT_DIR.absolute(), "KLT_CANONICAL_RESOLUTION")
    require(WORKSPACE_LINK.is_symlink(), "KLT_WORKSPACE_NOT_SYMLINK")
    target = os.readlink(WORKSPACE_LINK)
    require(target == str(KLT_DIR), f"KLT_WORKSPACE_TARGET:{target}")
    target_info = WORKSPACE_LINK.stat()
    require(
        (int(target_info.st_dev), int(target_info.st_ino))
        == (int(info.st_dev), int(info.st_ino)),
        "KLT_WORKSPACE_INODE_BINDING",
    )
    bindings = {key: snapshot(path) for key, path in KLT_FILES.items()}
    receipt, receipt_snapshot = stable_json(KLT_FILES["klt_receipt"])
    require(receipt_snapshot == bindings["klt_receipt"], "KLT_RECEIPT_REHASH_DRIFT")
    require(
        receipt.get("schema_version")
        == "aqua-fe-a09-samehistory-warmstart-frontend-receipt-v1",
        "KLT_RECEIPT_SCHEMA",
    )
    require(
        receipt.get("status") == "PASS_FRONTEND_STAGE_ACCEPTED"
        and receipt.get("stage") == "klt",
        "KLT_RECEIPT_STATUS",
    )
    require(
        receipt.get("artifact_audit", {}).get("status") == "PASS_KLT_FRONTEND_AUDIT",
        "KLT_ARTIFACT_AUDIT_STATUS",
    )
    outputs = receipt.get("outputs")
    require(isinstance(outputs, dict) and set(outputs) == set(RECEIPT_OUTPUTS), "KLT_RECEIPT_OUTPUT_SET")
    for output_name, binding_key in RECEIPT_OUTPUTS.items():
        recorded = outputs.get(output_name)
        actual = bindings[binding_key]
        require(
            isinstance(recorded, dict)
            and recorded.get("size_bytes") == actual["size_bytes"]
            and recorded.get("sha256") == actual["sha256"],
            f"KLT_RECEIPT_OUTPUT_BINDING:{output_name}",
        )
    claim, claim_snapshot = stable_json(KLT_FILES["klt_claim"])
    require(claim_snapshot == bindings["klt_claim"], "KLT_CLAIM_REHASH_DRIFT")
    require(
        claim.get("schema_version") == "aqua-fe-a09-frontend-process-start-claim-v1"
        and claim.get("stage") == "klt"
        and claim.get("status") == "CLAIMED_BEFORE_SINGLE_POPEN",
        "KLT_CLAIM_STATUS",
    )
    final_info = KLT_DIR.lstat()
    require(
        stat.S_ISDIR(final_info.st_mode)
        and (int(final_info.st_dev), int(final_info.st_ino))
        == (int(info.st_dev), int(info.st_ino)),
        "KLT_CANONICAL_CHANGED_DURING_REHASH",
    )
    require(
        WORKSPACE_LINK.is_symlink()
        and os.readlink(WORKSPACE_LINK) == target
        and (int(WORKSPACE_LINK.stat().st_dev), int(WORKSPACE_LINK.stat().st_ino))
        == (int(info.st_dev), int(info.st_ino)),
        "KLT_WORKSPACE_CHANGED_DURING_REHASH",
    )
    path_state = {
        "canonical": {
            "path": str(KLT_DIR),
            "is_real_directory": True,
            "device": int(info.st_dev),
            "inode": int(info.st_ino),
        },
        "workspace": {
            "path": str(WORKSPACE_LINK),
            "is_symlink": True,
            "target": target,
            "resolves_canonical_inode": True,
        },
    }
    postcommit = {
        "canonical_is_real_directory": True,
        "workspace_resolves_canonical_inode": True,
        "all_six_rehashed_after_commit": True,
        "receipt_output_binding_equal": True,
        "bindings_sha256": compact_sha256(bindings),
    }
    return path_state, postcommit, bindings


def build_value(observed_pgid: int, observed_pids: Mapping[str, int]) -> dict[str, Any]:
    path_state, postcommit, bindings = canonical_and_rehash_audit()
    processes = posthoc_process_scan(observed_pgid, observed_pids)
    return {
        "schema_version": SCHEMA,
        "status": STATUS,
        "observed_at_utc": utc_now(),
        "auditor_identity": snapshot(AUDITOR),
        "bindings": bindings,
        "path_state": path_state,
        "posthoc_process_tree": processes,
        "postcommit_external_rehash": postcommit,
        "limitations": {
            "old_receipt_waited_session_leader_only": True,
            "old_receipt_process_group_claim_is_not_strong_proof": True,
            "cannot_retroactively_prove_descendants_empty_at_leader_exit": True,
            "old_receipt_environment_records_overrides_only": True,
            "full_effective_environment_not_proven": True,
            "old_claim_was_plain_write_not_durable_or_exclusive": True,
            "exactly_once_execution_not_proven": True,
            "addendum_is_posthoc_evidence_only": True,
            "runtime_or_paper_performance_claim_permitted": False,
        },
        "claim_boundary": {
            "frontend_artifact_only": True,
            "vins_or_slam_executed": False,
            "trajectory_or_accuracy_result_available": False,
            "runtime_or_throughput_claim_permitted": False,
            "formal_paper_accuracy_evidence_permitted": False,
        },
    }


def fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | os.O_CLOEXEC | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def publish(path: Path, value: Mapping[str, Any]) -> dict[str, Any]:
    path = path.absolute()
    require(path == ADDENDUM, "NONCANONICAL_ADDENDUM_PATH")
    require(not path.exists() and not path.is_symlink(), "ADDENDUM_ALREADY_EXISTS")
    data = canonical_bytes(value)
    temp = path.parent / f".{path.name}.tmp.{os.getpid()}.{secrets.token_hex(8)}"
    descriptor = os.open(
        temp,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC | getattr(os, "O_NOFOLLOW", 0),
        0o600,
    )
    try:
        offset = 0
        while offset < len(data):
            written = os.write(descriptor, data[offset:])
            require(written > 0, "ADDENDUM_WRITE_NO_PROGRESS")
            offset += written
        os.fchmod(descriptor, 0o444)
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    try:
        os.link(temp, path, follow_symlinks=False)
        fsync_directory(path.parent)
    finally:
        try:
            temp.unlink()
        except FileNotFoundError:
            pass
        fsync_directory(path.parent)
    final = snapshot(path)
    require(path.read_bytes() == data, "ADDENDUM_FINAL_BYTES")
    return final


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("status", "audit", "build"))
    parser.add_argument("--authorization-token")
    parser.add_argument("--observed-pgid", type=int)
    parser.add_argument("--supervisor-pid", type=int)
    parser.add_argument("--group-leader-pid", type=int)
    parser.add_argument("--science-child-pid", type=int)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.command == "status":
        print(
            json.dumps(
                {
                    "status": "PRESENT" if ADDENDUM.exists() or ADDENDUM.is_symlink() else "ABSENT",
                    "path": str(ADDENDUM),
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 0
    if args.command == "audit":
        require(args.authorization_token is None, "AUDIT_REJECTS_TOKEN")
    else:
        require(args.authorization_token == AUTHORIZATION_TOKEN, "AUTHORIZATION_TOKEN_MISMATCH")
        require(not ADDENDUM.exists() and not ADDENDUM.is_symlink(), "ADDENDUM_ALREADY_EXISTS")
    required = {
        "observed_pgid": args.observed_pgid,
        "supervisor": args.supervisor_pid,
        "group_leader": args.group_leader_pid,
        "science_child": args.science_child_pid,
    }
    require(all(type(value) is int for value in required.values()), "OBSERVED_IDENTIFIERS_REQUIRED")
    with frontend_mutex():
        value = build_value(
            int(args.observed_pgid),
            {
                "supervisor": int(args.supervisor_pid),
                "group_leader": int(args.group_leader_pid),
                "science_child": int(args.science_child_pid),
            },
        )
        result = publish(ADDENDUM, value) if args.command == "build" else None
    if args.command == "audit":
        print(json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False))
        return 0
    require(isinstance(result, dict), "ADDENDUM_PUBLICATION_RESULT")
    print(
        json.dumps(
            {"status": STATUS, "addendum": result},
            indent=2,
            sort_keys=True,
            ensure_ascii=False,
            allow_nan=False,
        )
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (AddendumError, OSError, ValueError) as error:
        print(f"KLT_ADDENDUM_ERROR:{type(error).__name__}:{error}", file=sys.stderr)
        raise SystemExit(2)
