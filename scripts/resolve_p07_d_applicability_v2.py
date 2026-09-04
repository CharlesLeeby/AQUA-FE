#!/usr/bin/env python3
"""Resolve one frozen P07 D slot after its B1/M/P exports are terminal."""

from __future__ import annotations

import argparse
import csv
import fcntl
import hashlib
import io
import json
import os
import subprocess
from datetime import datetime
from pathlib import Path

try:
    from scripts import audit_p07_frontend_export_v3 as frontend_audit
    from scripts import build_p07_preoutcome_governance_v1 as governance
    from scripts import run_p07_mp_frontend_export_job_v2 as registry
except ModuleNotFoundError:  # Direct ``python3 scripts/...`` execution.
    import audit_p07_frontend_export_v3 as frontend_audit  # type: ignore
    import build_p07_preoutcome_governance_v1 as governance  # type: ignore
    import run_p07_mp_frontend_export_job_v2 as registry  # type: ignore


APPLICABILITY = governance.BUNDLE / "arm_applicability.csv"
RESOLUTION_ROOT = governance.P07 / "d_resolutions"
LOCK_ROOT = governance.P07 / "d_resolution_locks"
DERIVATION_ROOT_NAME = "p07_d_derivations"


class ResolutionViolation(RuntimeError):
    """Raised when a D slot cannot be resolved under the frozen contract."""


def now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def resolution_lock_path(window_id: str) -> Path:
    return LOCK_ROOT / f"{slug(window_id)}_v2.json"


def resolution_lock_hash(payload: dict[str, object]) -> str:
    clone = dict(payload)
    clone.pop("resolution_lock_hash", None)
    encoded = json.dumps(
        clone, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def load_resolution_lock(window_id: str) -> dict[str, object]:
    path = resolution_lock_path(window_id)
    if not path.is_file():
        raise ResolutionViolation(f"missing D resolution lock: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if (
        payload.get("schema_version") != "isj-p07-d-resolution-lock-v2"
        or payload.get("status") != "FROZEN_READY_TO_RESOLVE_D"
        or payload.get("window_id") != window_id
        or payload.get("resolution_lock_hash") != resolution_lock_hash(payload)
    ):
        raise ResolutionViolation("D resolution lock schema, identity, status, or hash mismatch")
    for record in payload["artifacts"]:
        artifact = governance.ROOT / str(record["path"])
        if (
            not artifact.is_file()
            or artifact.stat().st_size != int(record["size_bytes"])
            or sha256(artifact) != record["sha256"]
        ):
            raise ResolutionViolation(f"locked D artifact drift: {artifact}")
    for snapshot in payload["mutable_stream_prefix_snapshots"]:
        stream = governance.ROOT / str(snapshot["path"])
        content = stream.read_bytes()
        size = int(snapshot["size_bytes"])
        if (
            len(content) < size
            or hashlib.sha256(content[:size]).hexdigest() != snapshot["sha256"]
        ):
            raise ResolutionViolation(f"append-only D stream prefix drift: {stream}")
    return payload


def read_csv_bytes(content: bytes) -> tuple[list[str], list[dict[str, str]]]:
    reader = csv.DictReader(io.StringIO(content.decode("utf-8"), newline=""))
    fields = list(reader.fieldnames or [])
    rows = list(reader)
    if not fields or len(fields) != len(set(fields)) or any(None in row for row in rows):
        raise ResolutionViolation("invalid canonical applicability CSV")
    return fields, rows


def slug(window_id: str) -> str:
    return window_id.lower().replace(":", "_").replace("-", "_")


def queue_rows(window_id: str) -> list[dict[str, str]]:
    rows = [
        row
        for row in governance.read_csv(governance.EXPORT_QUEUE)
        if row["window_id"] == window_id
    ]
    if len(rows) != 3 or {row["arm"] for row in rows} != {
        governance.B1,
        governance.M_ARM,
        governance.P_ARM,
    }:
        raise ResolutionViolation(f"window does not have the frozen B1/M/P triplet: {window_id}")
    return sorted(rows, key=lambda row: int(row["queue_index"]))


def latest_registry_rows(rows: list[dict[str, str]]) -> dict[str, dict[str, str]]:
    result: dict[str, dict[str, str]] = {}
    for row in rows:
        allocation = frontend_audit.allocation_row(int(row["queue_index"]))
        chain = registry.registry_chain(allocation["run_id"])
        if not chain or chain[-1]["status"] != "COMPLETED":
            raise ResolutionViolation(
                f"queue index {row['queue_index']} is not terminal COMPLETED"
            )
        result[row["arm"]] = chain[-1]
    return result


def p_audit_path(p_row: dict[str, str]) -> Path:
    attempt = (
        governance.P07
        / "frontend_attempts"
        / f"queue_{int(p_row['queue_index']):03d}_{p_row['tag']}"
    )
    path = attempt / "audit_v3.json"
    if not path.is_file():
        raise ResolutionViolation(f"missing P v3 audit: {path}")
    return path


def load_p_audit(window_id: str, p_row: dict[str, str]) -> tuple[Path, dict[str, object]]:
    path = p_audit_path(p_row)
    payload = json.loads(path.read_text(encoding="utf-8"))
    if (
        payload.get("schema_version")
        not in {
            "isj-p07-frontend-export-audit-v3",
            "isj-p07-a01-frontend-export-audit-v3",
        }
        or payload.get("status") != "PASS"
        or payload.get("window_id") != window_id
        or payload.get("arm") != governance.P_ARM
        or not isinstance(payload.get("learned_lineages"), dict)
    ):
        raise ResolutionViolation("P v3 audit identity or status mismatch")
    return path, payload


def matching_applicability_rows(
    rows: list[dict[str, str]], manifest: dict[str, str]
) -> list[dict[str, str]]:
    return [
        row
        for row in rows
        if row["protocol_version"] == "isj-nativeq-v3-confirmatory-protocol-v1"
        and row["method_profile"] == "P_legacy_nativeq_xfeat_seedchain_v3"
        and row["dataset_family"] == manifest["dataset_family"]
        and row["sequence"] == manifest["sequence"]
        and float(row["window_start"]) == float(manifest["window_start_s"])
        and float(row["window_end"]) == float(manifest["window_end_s"])
        and row["proposed_arm"] == governance.P_ARM
        and row["drop_arm"] == "D_legacy_exact_lineage_drop_v3"
    ]


def output_paths(window_id: str, count: int) -> tuple[Path, Path | None]:
    stem = slug(window_id)
    suffix = "applicable" if count else "not_applicable"
    resolution = RESOLUTION_ROOT / f"{stem}_{suffix}_v2.json"
    derivation = (
        governance.ROOT / "logs" / DERIVATION_ROOT_NAME / f"{stem}_d_attempt01"
        if count
        else None
    )
    return resolution, derivation


def run_checked(command: list[str], log_path: Path) -> None:
    with log_path.open("wb") as log:
        completed = subprocess.run(
            command,
            cwd=governance.ROOT,
            stdout=log,
            stderr=subprocess.STDOUT,
            check=False,
        )
    if completed.returncode != 0:
        raise ResolutionViolation(f"command failed rc={completed.returncode}: {command}")


def derive_drop_bag(
    proposed_bag: Path, derivation_dir: Path
) -> dict[str, object]:
    if derivation_dir.exists():
        raise FileExistsError(derivation_dir)
    derivation_dir.mkdir(parents=True)
    drop_bag = derivation_dir / "features.bag"
    producer_stats = derivation_dir / "drop_whole_lineage_stats.csv"
    producer_log = derivation_dir / "producer.log"
    audit_json = derivation_dir / "exact_drop_audit.json"
    audit_log = derivation_dir / "exact_drop_audit.log"
    attestation = Path(str(drop_bag) + ".quality-contract.json")
    attestation_log = derivation_dir / "attestation.log"

    run_checked(
        [
            "python3",
            "scripts/filter_feature_bag_by_channel.py",
            "--input-bag",
            str(proposed_bag),
            "--output-bag",
            str(drop_bag),
            "--stats-csv",
            str(producer_stats),
            "--drop-learned-track-lineage",
        ],
        producer_log,
    )
    run_checked(
        [
            "python3",
            "scripts/audit_whole_lineage_exact_drop_v1.py",
            "--proposed-bag",
            str(proposed_bag),
            "--drop-bag",
            str(drop_bag),
            "--producer-stats-csv",
            str(producer_stats),
            "--audit-json",
            str(audit_json),
        ],
        audit_log,
    )
    audit = json.loads(audit_json.read_text(encoding="utf-8"))
    if (
        audit.get("contract_pass") is not True
        or audit.get("decision") != "PASS_EXACT_WHOLE_LINEAGE_DROP"
    ):
        raise ResolutionViolation("whole-lineage exact-drop audit did not pass")
    run_checked(
        [
            "python3",
            "scripts/attest_nativeq_feature_bag.py",
            "--feature-bag",
            str(drop_bag),
            "--contract",
            "papers/ieee_sensors_journal_experiments/backend_quality_contract_v1.json",
            "--output",
            str(attestation),
        ],
        attestation_log,
    )
    output_manifest = derivation_dir / "output_hash_manifest.sha256"
    files = sorted(path for path in derivation_dir.iterdir() if path.is_file())
    output_manifest.write_text(
        "".join(
            f"{sha256(path)}  {frontend_audit.display_path(path)}\n" for path in files
        ),
        encoding="utf-8",
    )
    return {
        "drop_bag": frontend_audit.display_path(drop_bag),
        "drop_bag_sha256": sha256(drop_bag),
        "producer_stats": frontend_audit.display_path(producer_stats),
        "exact_drop_audit": frontend_audit.display_path(audit_json),
        "exact_drop_audit_sha256": sha256(audit_json),
        "attestation": frontend_audit.display_path(attestation),
        "attestation_sha256": sha256(attestation),
        "output_hash_manifest": frontend_audit.display_path(output_manifest),
    }


def append_resolution(window_id: str) -> dict[str, object]:
    resolution_lock = load_resolution_lock(window_id)
    rows = queue_rows(window_id)
    latest = latest_registry_rows(rows)
    p_row = next(row for row in rows if row["arm"] == governance.P_ARM)
    b1_row = next(row for row in rows if row["arm"] == governance.B1)
    p_audit_file, p_audit = load_p_audit(window_id, p_row)
    lineage_count = int(
        p_audit["learned_lineages"]["accepted_learned_born_lineage_count"]
    )
    if lineage_count != int(
        resolution_lock["lineage_contract"]["accepted_learned_born_lineage_count"]
    ):
        raise ResolutionViolation("P lineage count differs from the frozen D resolution lock")
    proposed_bag = governance.ROOT / str(p_audit["feature_bag"]["path"])
    b1_bag = governance.ROOT / b1_row["expected_feature_bag"]
    resolution_path, derivation_dir = output_paths(window_id, lineage_count)
    if resolution_path.exists():
        raise FileExistsError(resolution_path)
    RESOLUTION_ROOT.mkdir(parents=True, exist_ok=True)

    zero_identity: dict[str, object] | None = None
    derivation: dict[str, object] | None = None
    if lineage_count == 0:
        if not b1_bag.is_file() or not proposed_bag.is_file():
            raise ResolutionViolation("zero-action identity requires both frozen P and B1 bags")
        p_hash = sha256(proposed_bag)
        b1_hash = sha256(b1_bag)
        if p_hash != b1_hash:
            raise ResolutionViolation("zero-action P is not byte-identical to frozen B1")
        zero_identity = {
            "status": "PASS_BYTE_IDENTICAL_TO_B1",
            "p_feature_bag": frontend_audit.display_path(proposed_bag),
            "p_feature_bag_sha256": p_hash,
            "b1_feature_bag": frontend_audit.display_path(b1_bag),
            "b1_feature_bag_sha256": b1_hash,
        }
        resolution = "NOT_APPLICABLE"
    else:
        assert derivation_dir is not None
        derivation = derive_drop_bag(proposed_bag, derivation_dir)
        resolution = "APPLICABLE"

    manifest = frontend_audit.manifest_row(window_id)
    resolver_hash = str(resolution_lock["resolution_lock_hash"])
    resolution_time = now()
    temporary = resolution_path.with_name(
        f"{resolution_path.name}.partial.{os.getpid()}"
    )
    evidence_path = frontend_audit.display_path(resolution_path)

    with APPLICABILITY.open("r+b", buffering=0) as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            handle.seek(0)
            content = handle.read()
            fields, applicability_rows = read_csv_bytes(content)
            matching = matching_applicability_rows(applicability_rows, manifest)
            pending = [row for row in matching if row["resolution"] == "PENDING_APPLICABILITY"]
            terminal = [row for row in matching if row["resolution"] != "PENDING_APPLICABILITY"]
            if len(pending) != 1 or terminal:
                raise ResolutionViolation(
                    f"applicability state is not one pending/no terminal: {matching}"
                )
            terminal_row = dict(pending[0])
            terminal_row.update(
                {
                    "accepted_lineage_count": str(lineage_count),
                    "resolution_time": resolution_time,
                    "resolution": resolution,
                    "evidence_path": evidence_path,
                    "resolver_hash": resolver_hash,
                }
            )
            stream = io.StringIO(newline="")
            writer = csv.DictWriter(stream, fieldnames=fields, lineterminator="\n")
            writer.writerow(terminal_row)
            appended = stream.getvalue().encode("utf-8")
            closeout = {
                "schema_version": "isj-p07-d-applicability-resolution-v2",
                "status": f"PASS_{resolution}",
                "recorded_at": resolution_time,
                "window_id": window_id,
                "parent_p_run_id": latest[governance.P_ARM]["run_id"],
                "accepted_learned_born_lineage_count": lineage_count,
                "resolution": resolution,
                "p_audit": frontend_audit.display_path(p_audit_file),
                "p_audit_sha256": sha256(p_audit_file),
                "zero_action_identity": zero_identity,
                "derivation": derivation,
                "resolver_hash": resolver_hash,
                "resolution_lock": frontend_audit.display_path(
                    resolution_lock_path(window_id)
                ),
                "canonical_stream": {
                    "path": frontend_audit.display_path(APPLICABILITY),
                    "prefix_size_bytes": len(content),
                    "prefix_sha256": hashlib.sha256(content).hexdigest(),
                    "appended_row_sha256": hashlib.sha256(appended).hexdigest(),
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
    os.replace(temporary, resolution_path)
    return closeout


def preflight(window_id: str) -> dict[str, object]:
    rows = queue_rows(window_id)
    statuses = {}
    for row in rows:
        allocation = frontend_audit.allocation_row(int(row["queue_index"]))
        statuses[row["arm"]] = registry.registry_chain(allocation["run_id"])[-1]["status"]
    p_row = next(row for row in rows if row["arm"] == governance.P_ARM)
    count = None
    if statuses[governance.P_ARM] == "COMPLETED" and p_audit_path(p_row).is_file():
        payload = json.loads(p_audit_path(p_row).read_text(encoding="utf-8"))
        count = int(payload["learned_lineages"]["accepted_learned_born_lineage_count"])
    resolution_path = output_paths(window_id, count or 0)[0] if count is not None else None
    return {
        "window_id": window_id,
        "frontend_statuses": statuses,
        "accepted_learned_born_lineage_count": count,
        "resolution_output": (
            frontend_audit.display_path(resolution_path) if resolution_path else None
        ),
        "resolution_collision": bool(resolution_path and resolution_path.exists()),
        "resolution_lock": frontend_audit.display_path(resolution_lock_path(window_id)),
        "resolution_lock_exists": resolution_lock_path(window_id).is_file(),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--window-id", required=True)
    parser.add_argument("--preflight-only", action="store_true")
    args = parser.parse_args()
    if args.preflight_only:
        report = preflight(args.window_id)
        print(json.dumps(report, indent=2, sort_keys=True))
        return 0
    result = append_resolution(args.window_id)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
