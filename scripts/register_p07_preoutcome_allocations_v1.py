#!/usr/bin/env python3
"""Append frozen P07 export allocations and pending D slots to canonical streams."""

from __future__ import annotations

import argparse
import csv
import fcntl
import hashlib
import io
import json
import os
from pathlib import Path

try:
    from scripts import build_p07_preoutcome_governance_v1 as builder
except ModuleNotFoundError:  # Direct ``python3 scripts/...`` execution.
    import build_p07_preoutcome_governance_v1 as builder  # type: ignore


RUN_REGISTRY = builder.BUNDLE / "run_registry.csv"
APPLICABILITY = builder.BUNDLE / "arm_applicability.csv"
REPORT = builder.P07 / "preoutcome_registration_v1.json"
PROTOCOL = "isj-nativeq-v3-confirmatory-protocol-v1"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_csv(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        fields = list(reader.fieldnames or [])
        rows = list(reader)
    if not fields or len(fields) != len(set(fields)) or any(None in row for row in rows):
        raise ValueError(f"invalid canonical CSV: {path}")
    return fields, rows


def split_map() -> dict[str, dict[str, str]]:
    return {row["window_id"]: row for row in builder.read_csv(builder.SPLIT_CSV)}


def manifest_map() -> dict[str, dict[str, str]]:
    return {row["window_id"]: row for row in builder.read_csv(builder.MANIFEST)}


def build_registry_rows() -> list[dict[str, str]]:
    fields, _existing = read_csv(RUN_REGISTRY)
    allocations = builder.read_csv(builder.ALLOCATION_CSV)
    splits = split_map()
    arm_versions = {
        builder.B1: "nativeq-v3",
        builder.P_ARM: "actual-v3",
        builder.M_ARM: "xfeat-pairwise-nativeq-v1",
    }
    rows: list[dict[str, str]] = []
    for allocation in allocations:
        run_id = allocation["run_id"]
        run_dir = ""
        if allocation["expected_feature_bag"]:
            run_dir = str(Path(allocation["expected_feature_bag"]).parent)
        values = {
            "run_id": run_id,
            "registry_event_id": f"{run_id}_e00",
            "recorded_at": allocation["allocated_at"],
            "supersedes_event_id": "",
            "protocol_version": PROTOCOL,
            "method_profile": allocation["arm"],
            "stage": "P07_FRONTEND_EXPORT",
            "dataset_family": allocation["dataset_family"],
            "sequence": allocation["sequence"],
            "window_start": allocation["window_start"],
            "window_end": allocation["window_end"],
            "texture_stratum": allocation["texture_stratum"],
            "split_role": splits[allocation["window_id"]]["corrected_split_role"],
            "arm": allocation["arm"],
            "arm_version": arm_versions[allocation["arm"]],
            "arm_applicability": "REQUIRED",
            "applicability_rule": "ALWAYS",
            "frontend_seed": allocation["frontend_seed"],
            "backend_replay": allocation["backend_replay"],
            "status": "PLANNED",
            "replay_evaluable": "false",
            "run_dir": run_dir,
            "command_file": "papers/ieee_sensors_journal_experiments/p07/frontend_export_queue_v1.csv",
            "input_hash_manifest": "papers/ieee_sensors_journal_experiments/dataset_checksum_manifest.txt",
            "notes": (
                f"queue_index={allocation['queue_index']}; window_id={allocation['window_id']}; "
                f"tag={allocation['tag']}; command_sha256={allocation['command_sha256']}; "
                "frontend export only; trajectory outcome not read"
            ),
        }
        unknown = set(values).difference(fields)
        if unknown:
            raise ValueError(f"run registry header missing fields: {sorted(unknown)}")
        rows.append({field: values.get(field, "") for field in fields})
    if len(rows) != 60 or len({row["registry_event_id"] for row in rows}) != 60:
        raise ValueError("expected 60 unique P07 registry allocation events")
    return rows


def build_applicability_rows() -> list[dict[str, str]]:
    fields, _existing = read_csv(APPLICABILITY)
    d_rows = builder.read_csv(builder.D_QUEUE)
    manifest = manifest_map()
    rows: list[dict[str, str]] = []
    for item in d_rows:
        window = manifest[item["window_id"]]
        values = {
            "protocol_version": PROTOCOL,
            "method_profile": builder.P_ARM,
            "dataset_family": item["dataset_family"],
            "sequence": item["sequence"],
            "window_start": window["window_start_s"],
            "window_end": window["window_end_s"],
            "proposed_arm": builder.P_ARM,
            "accepted_lineage_count": "",
            "applicability_rule": item["applicability_rule"],
            "resolution_time": "",
            "drop_arm": builder.D_ARM,
            "classical_arm": "",
            "resolution": "PENDING_APPLICABILITY",
            "evidence_path": (
                "papers/ieee_sensors_journal_experiments/p07/"
                f"d_applicability_queue_v1.csv#slot_index={item['slot_index']}"
            ),
            "resolver_hash": json.loads(builder.QUEUE_LOCK.read_text(encoding="utf-8"))[
                "queue_lock_hash"
            ],
        }
        unknown = set(values).difference(fields)
        if unknown:
            raise ValueError(f"applicability header missing fields: {sorted(unknown)}")
        rows.append({field: values.get(field, "") for field in fields})
    if len(rows) != 20:
        raise ValueError("expected 20 pending D applicability rows")
    return rows


def row_bytes(fields: list[str], rows: list[dict[str, str]]) -> bytes:
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=fields, lineterminator="\n")
    writer.writerows(rows)
    return stream.getvalue().encode("utf-8")


def append_missing(
    path: Path,
    intended: list[dict[str, str]],
    *,
    key_fields: tuple[str, ...],
) -> int:
    fields, existing = read_csv(path)
    by_key = {tuple(row[field] for field in key_fields): row for row in existing}
    missing: list[dict[str, str]] = []
    for row in intended:
        key = tuple(row[field] for field in key_fields)
        observed = by_key.get(key)
        if observed is None:
            missing.append(row)
        elif observed != row:
            raise ValueError(f"canonical row collision with different content: {path}:{key}")
    if not missing:
        return 0
    content = row_bytes(fields, missing)
    with path.open("ab", buffering=0) as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        handle.seek(0, os.SEEK_END)
        if handle.tell() and path.read_bytes()[-1:] != b"\n":
            raise ValueError(f"canonical CSV lacks final newline: {path}")
        handle.write(content)
        os.fsync(handle.fileno())
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    return len(missing)


def validate_registered() -> dict[str, object]:
    registry_intended = build_registry_rows()
    applicability_intended = build_applicability_rows()
    _registry_fields, registry = read_csv(RUN_REGISTRY)
    _app_fields, applicability = read_csv(APPLICABILITY)
    registry_ids = {row["registry_event_id"] for row in registry}
    pending_keys = {
        (
            row["dataset_family"],
            row["sequence"],
            row["window_start"],
            row["window_end"],
            row["proposed_arm"],
            row["resolution"],
        )
        for row in applicability
    }
    return {
        "registry_allocations_present": sum(
            row["registry_event_id"] in registry_ids for row in registry_intended
        ),
        "pending_D_rows_present": sum(
            (
                row["dataset_family"],
                row["sequence"],
                row["window_start"],
                row["window_end"],
                row["proposed_arm"],
                row["resolution"],
            )
            in pending_keys
            for row in applicability_intended
        ),
    }


def apply_registration() -> dict[str, object]:
    if REPORT.exists():
        raise FileExistsError(REPORT)
    before = {
        "run_registry_sha256": sha256(RUN_REGISTRY),
        "arm_applicability_sha256": sha256(APPLICABILITY),
    }
    registry_added = append_missing(
        RUN_REGISTRY,
        build_registry_rows(),
        key_fields=("registry_event_id",),
    )
    applicability_added = append_missing(
        APPLICABILITY,
        build_applicability_rows(),
        key_fields=(
            "dataset_family",
            "sequence",
            "window_start",
            "window_end",
            "proposed_arm",
            "resolution",
        ),
    )
    validation = validate_registered()
    if validation != {"registry_allocations_present": 60, "pending_D_rows_present": 20}:
        raise ValueError(f"post-registration validation failed: {validation}")
    report = {
        "schema_version": "isj-p07-preoutcome-registration-v1",
        "status": "PASS",
        "recorded_at": builder.ALLOCATION_TIME,
        "registry_rows_appended": registry_added,
        "pending_D_rows_appended": applicability_added,
        "validation": validation,
        "before": before,
        "after": {
            "run_registry_sha256": sha256(RUN_REGISTRY),
            "arm_applicability_sha256": sha256(APPLICABILITY),
        },
        "allocation": builder.file_record(builder.ALLOCATION_CSV),
        "d_queue": builder.file_record(builder.D_QUEUE),
        "queue_lock_hash": json.loads(builder.QUEUE_LOCK.read_text(encoding="utf-8"))[
            "queue_lock_hash"
        ],
        "outcome_boundary": builder.OUTCOME_BOUNDARY,
        "held_out_frontend_outcome_read": False,
        "held_out_trajectory_outcome_read": False,
    }
    temporary = REPORT.with_name(f"{REPORT.name}.partial.{os.getpid()}")
    temporary.write_text(
        json.dumps(report, indent=2, sort_keys=True, ensure_ascii=True) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, REPORT)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    if not args.apply:
        intended = {
            "registry_rows": len(build_registry_rows()),
            "pending_D_rows": len(build_applicability_rows()),
            "current": validate_registered(),
        }
        print(json.dumps(intended, sort_keys=True))
        return 0
    report = apply_registration()
    print(
        "P07_PREOUTCOME_REGISTRATION_PASS "
        f"registry_added={report['registry_rows_appended']} "
        f"pending_D_added={report['pending_D_rows_appended']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
