#!/usr/bin/env python3
"""Append the locked A02 D=NOT_APPLICABLE resolution to the canonical stream."""

from __future__ import annotations

import argparse
import csv
import fcntl
import hashlib
import io
import json
import os
from datetime import datetime
from pathlib import Path

try:
    from scripts import build_p07_preoutcome_governance_v1 as governance
except ModuleNotFoundError:  # Direct ``python3 scripts/...`` execution.
    import build_p07_preoutcome_governance_v1 as governance  # type: ignore


LOCK_PATH = governance.P07 / "a02_d_resolution_lock_v1.json"
APPLICABILITY = governance.BUNDLE / "arm_applicability.csv"
OUTPUT = governance.P07 / "d_resolutions/a02_0005_not_applicable_v1.json"
P_RUN_ID = (
    "isj-nativeq-v3_P07_aqualoc_archaeology-A02_4500-5400_"
    "P_f0_b00_20260806T084500Z"
)


class ResolutionViolation(RuntimeError):
    """Raised when the append-only applicability contract is not satisfied."""


def now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def lock_hash(payload: dict[str, object]) -> str:
    clone = dict(payload)
    clone.pop("resolution_lock_hash", None)
    encoded = json.dumps(
        clone, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def read_csv_bytes(content: bytes) -> tuple[list[str], list[dict[str, str]]]:
    handle = io.StringIO(content.decode("utf-8"), newline="")
    reader = csv.DictReader(handle)
    fields = list(reader.fieldnames or [])
    rows = list(reader)
    if not fields or len(fields) != len(set(fields)) or any(None in row for row in rows):
        raise ResolutionViolation("invalid canonical applicability CSV")
    return fields, rows


def load_and_validate_lock() -> dict[str, object]:
    if not LOCK_PATH.is_file():
        raise ResolutionViolation(f"missing A02 D resolution lock: {LOCK_PATH}")
    payload = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
    if (
        payload.get("schema_version") != "isj-p07-a02-d-resolution-lock-v1"
        or payload.get("status") != "FROZEN_READY_TO_APPEND_NOT_APPLICABLE"
        or payload.get("resolution_lock_hash") != lock_hash(payload)
    ):
        raise ResolutionViolation("A02 D resolution lock schema, status, or hash mismatch")
    for record in payload["artifacts"]:
        path = governance.ROOT / str(record["path"])
        if (
            not path.is_file()
            or path.stat().st_size != int(record["size_bytes"])
            or sha256(path) != record["sha256"]
        ):
            raise ResolutionViolation(f"locked D-resolution artifact drift: {path}")
    for snapshot in payload["mutable_stream_prefix_snapshots"]:
        path = governance.ROOT / str(snapshot["path"])
        content = path.read_bytes()
        size = int(snapshot["size_bytes"])
        if len(content) < size or sha256_bytes(content[:size]) != snapshot["sha256"]:
            raise ResolutionViolation(f"append-only stream prefix drift: {path}")
    return payload


def is_a02_row(row: dict[str, str]) -> bool:
    return (
        row["protocol_version"] == "isj-nativeq-v3-confirmatory-protocol-v1"
        and row["method_profile"] == "P_legacy_nativeq_xfeat_seedchain_v3"
        and row["dataset_family"] == "aqualoc_archaeology"
        and row["sequence"] == "A02"
        and row["window_start"] == "225.0"
        and row["window_end"] == "270.0"
        and row["proposed_arm"] == "P_legacy_nativeq_xfeat_seedchain_v3"
        and row["drop_arm"] == "D_legacy_exact_lineage_drop_v3"
    )


def build_terminal_row(
    pending: dict[str, str], *, resolution_time: str, resolver_hash: str
) -> dict[str, str]:
    row = dict(pending)
    row.update(
        {
            "accepted_lineage_count": "0",
            "resolution_time": resolution_time,
            "resolution": "NOT_APPLICABLE",
            "evidence_path": (
                "papers/ieee_sensors_journal_experiments/p07/frontend_attempts/"
                "queue_003_isj_p07_aqualoc_archaeology_a02_0005_p_attempt01/audit_v2.json"
            ),
            "resolver_hash": resolver_hash,
        }
    )
    return row


def validate_p_registry(lock: dict[str, object]) -> dict[str, str]:
    path = governance.BUNDLE / "run_registry.csv"
    _fields, rows = read_csv_bytes(path.read_bytes())
    chain = [row for row in rows if row["run_id"] == P_RUN_ID]
    if (
        len(chain) != 3
        or [row["status"] for row in chain] != ["PLANNED", "RUNNING", "COMPLETED"]
        or chain[-1]["registry_event_id"] != f"{P_RUN_ID}_e02"
        or chain[-1]["accepted_lineage_count"] != "0"
        or chain[-1]["active"] != "false"
        or chain[-1]["output_hash_manifest"]
        != lock["parent_p"]["output_hash_manifest"]
    ):
        raise ResolutionViolation("parent P registry chain is not the locked zero-lineage PASS")
    return chain[-1]


def append_resolution(lock: dict[str, object]) -> dict[str, object]:
    if OUTPUT.exists():
        raise FileExistsError(OUTPUT)
    validate_p_registry(lock)
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    resolution_time = now()
    temporary = OUTPUT.with_name(f"{OUTPUT.name}.partial.{os.getpid()}")

    with APPLICABILITY.open("r+b", buffering=0) as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            handle.seek(0)
            content = handle.read()
            fields, rows = read_csv_bytes(content)
            a02_rows = [row for row in rows if is_a02_row(row)]
            pending = [row for row in a02_rows if row["resolution"] == "PENDING_APPLICABILITY"]
            terminal = [row for row in a02_rows if row["resolution"] != "PENDING_APPLICABILITY"]
            if len(pending) != 1 or terminal:
                raise ResolutionViolation(
                    f"A02 applicability state is not one pending/no terminal: {a02_rows}"
                )
            row = build_terminal_row(
                pending[0],
                resolution_time=resolution_time,
                resolver_hash=str(lock["resolution_lock_hash"]),
            )
            stream = io.StringIO(newline="")
            writer = csv.DictWriter(stream, fieldnames=fields, lineterminator="\n")
            writer.writerow(row)
            appended = stream.getvalue().encode("utf-8")
            closeout = {
                "schema_version": "isj-p07-a02-d-applicability-resolution-v1",
                "status": "PASS_NOT_APPLICABLE",
                "recorded_at": resolution_time,
                "window_id": "aqualoc_archaeology:A02:0005",
                "slot_index": 4,
                "parent_p_run_id": P_RUN_ID,
                "accepted_learned_born_lineage_count": 0,
                "resolution": "NOT_APPLICABLE",
                "d_bag_created": False,
                "d_replay_slots_created": 0,
                "evidence": lock["parent_p"],
                "resolution_lock_hash": lock["resolution_lock_hash"],
                "canonical_stream": {
                    "path": "papers/ieee_sensors_journal_experiments/arm_applicability.csv",
                    "prefix_size_bytes": len(content),
                    "prefix_sha256": sha256_bytes(content),
                    "appended_row_sha256": sha256_bytes(appended),
                },
                "outcome_boundary": "FRONTEND_EXPORT_ONLY_NO_VINS_APE_RPE_TRAJECTORY",
                "held_out_trajectory_outcome_read": False,
            }
            temporary.write_text(
                json.dumps(closeout, indent=2, sort_keys=True, ensure_ascii=True) + "\n",
                encoding="utf-8",
            )
            handle.seek(0, os.SEEK_END)
            handle.write(appended)
            os.fsync(handle.fileno())
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    os.replace(temporary, OUTPUT)
    return closeout


def preflight(lock: dict[str, object]) -> dict[str, object]:
    p_event = validate_p_registry(lock)
    _fields, rows = read_csv_bytes(APPLICABILITY.read_bytes())
    a02_rows = [row for row in rows if is_a02_row(row)]
    return {
        "slot_index": 4,
        "parent_p_latest_event": p_event["registry_event_id"],
        "parent_p_lineage_count": p_event["accepted_lineage_count"],
        "a02_resolutions": [row["resolution"] for row in a02_rows],
        "output_collision": OUTPUT.exists(),
        "action": "APPEND_NOT_APPLICABLE_NO_D_BAG_NO_REPLAY_SLOT",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--preflight-only", action="store_true")
    args = parser.parse_args()
    lock = load_and_validate_lock()
    if args.preflight_only:
        report = preflight(lock)
        print(json.dumps(report, indent=2, sort_keys=True))
        return 0 if (
            report["parent_p_lineage_count"] == "0"
            and report["a02_resolutions"] == ["PENDING_APPLICABILITY"]
            and not report["output_collision"]
        ) else 1
    result = append_resolution(lock)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
