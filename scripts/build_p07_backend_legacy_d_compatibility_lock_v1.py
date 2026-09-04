#!/usr/bin/env python3
"""Build additive backend provenance for the two legacy P07 D resolutions.

A01:0018 and A02:0005 predate the generalized ``d_resolution_locks/`` layout.
Their immutable locks remain at the P07 root and their terminal resolution JSON
records only the lock self-hash, not its path.  This builder creates two
additive sidecars and one commit-last compatibility lock without modifying any
legacy evidence.  ``--write`` is required for a future formal action.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping, Sequence

try:
    from scripts import p07_backend_formal_io_v1 as formal_io
    from scripts import p07_backend_frontend_provenance_v1 as provenance
except ModuleNotFoundError:  # Direct ``python3 scripts/...`` execution.
    import p07_backend_formal_io_v1 as formal_io  # type: ignore
    import p07_backend_frontend_provenance_v1 as provenance  # type: ignore


ROOT = Path(__file__).resolve().parents[1]
BUNDLE = ROOT / "papers/ieee_sensors_journal_experiments"
P07 = BUNDLE / "p07"
APPLICABILITY = BUNDLE / "arm_applicability.csv"
A01_SIDECAR = P07 / "backend_a01_0018_legacy_d_sidecar_v1.json"
A02_SIDECAR = P07 / "backend_a02_0005_legacy_d_sidecar_v1.json"
OUTPUT = P07 / "backend_legacy_d_resolution_compatibility_lock_v1.json"

SIDECAR_SCHEMA = "isj-p07-backend-legacy-d-resolution-sidecar-v1"
SIDECAR_STATUS = "PASS_NOT_APPLICABLE_LEGACY_LOCK_BOUND"
LOCK_SCHEMA = "isj-p07-backend-legacy-d-resolution-compatibility-lock-v1"
LOCK_STATUS = "FROZEN_READY_FOR_BACKEND_QUEUE_INPUT"


class LegacyDCompatibilityError(RuntimeError):
    """Legacy D evidence is missing, drifted, or scientifically inconsistent."""


@dataclass(frozen=True)
class LegacyCase:
    label: str
    window_id: str
    slot_index: int
    sequence: str
    start: str
    end: str
    lock_relative: str
    lock_schema: str
    terminal_relative: str
    terminal_schema: str
    sidecar_relative: str


CASES = (
    LegacyCase(
        label="A01_0018",
        window_id="aqualoc_archaeology:A01:0018",
        slot_index=3,
        sequence="A01",
        start="810.0",
        end="855.0",
        lock_relative="papers/ieee_sensors_journal_experiments/p07/a01_d_resolution_lock_v1.json",
        lock_schema="isj-p07-a01-d-resolution-lock-v1",
        terminal_relative=(
            "papers/ieee_sensors_journal_experiments/p07/d_resolutions/"
            "a01_0018_not_applicable_v1.json"
        ),
        terminal_schema="isj-p07-a01-d-applicability-resolution-v1",
        sidecar_relative=(
            "papers/ieee_sensors_journal_experiments/p07/"
            "backend_a01_0018_legacy_d_sidecar_v1.json"
        ),
    ),
    LegacyCase(
        label="A02_0005",
        window_id="aqualoc_archaeology:A02:0005",
        slot_index=4,
        sequence="A02",
        start="225.0",
        end="270.0",
        lock_relative="papers/ieee_sensors_journal_experiments/p07/a02_d_resolution_lock_v1.json",
        lock_schema="isj-p07-a02-d-resolution-lock-v1",
        terminal_relative=(
            "papers/ieee_sensors_journal_experiments/p07/d_resolutions/"
            "a02_0005_not_applicable_v1.json"
        ),
        terminal_schema="isj-p07-a02-d-applicability-resolution-v1",
        sidecar_relative=(
            "papers/ieee_sensors_journal_experiments/p07/"
            "backend_a02_0005_legacy_d_sidecar_v1.json"
        ),
    ),
)

LEGACY_ARTIFACT_PATHS = {
    "A01_0018": {
        "papers/ieee_sensors_journal_experiments/method_lock.json",
        "papers/ieee_sensors_journal_experiments/protocol_v1_nativeq_v3.md",
        "papers/ieee_sensors_journal_experiments/p07/d_applicability_queue_v1.csv",
        "papers/ieee_sensors_journal_experiments/p07/frontend_queue_lock_v1.json",
        "papers/ieee_sensors_journal_experiments/p07/a01_frontend_execution_lock_v3.json",
        "papers/ieee_sensors_journal_experiments/p07/frontend_attempts/queue_004_isj_p07_aqualoc_archaeology_a01_0018_b1_attempt01/audit_v3.json",
        "papers/ieee_sensors_journal_experiments/p07/frontend_attempts/queue_004_isj_p07_aqualoc_archaeology_a01_0018_b1_attempt01/output_hash_manifest.sha256",
        "papers/ieee_sensors_journal_experiments/p07/frontend_attempts/queue_005_isj_p07_aqualoc_archaeology_a01_0018_p_attempt01/audit_v3.json",
        "papers/ieee_sensors_journal_experiments/p07/frontend_attempts/queue_005_isj_p07_aqualoc_archaeology_a01_0018_p_attempt01/output_hash_manifest.sha256",
        "papers/ieee_sensors_journal_experiments/p07/frontend_attempts/queue_006_isj_p07_aqualoc_archaeology_a01_0018_m_attempt01/audit_v3.json",
        "papers/ieee_sensors_journal_experiments/p07/frontend_attempts/queue_006_isj_p07_aqualoc_archaeology_a01_0018_m_attempt01/output_hash_manifest.sha256",
        "logs/aqualoc_archaeo_vins/external_klt_every2_isj_p07_aqualoc_archaeology_a01_0018_p_attempt01_klt_safe_fallback/features.bag",
        "logs/aqualoc_archaeo_vins/external_klt_every2_isj_p07_aqualoc_archaeology_a01_0018_b1_attempt01/features.bag",
        "datasets/aqualoc/rosbags/archaeo01_16200_17100.bag",
        "scripts/resolve_p07_a01_d_applicability_v1.py",
        "scripts/build_p07_a01_d_resolution_lock_v1.py",
        "scripts/tests/test_p07_a01_d_resolution_v1.py",
    },
    "A02_0005": {
        "papers/ieee_sensors_journal_experiments/method_lock.json",
        "papers/ieee_sensors_journal_experiments/protocol_v1_nativeq_v3.md",
        "papers/ieee_sensors_journal_experiments/p07/d_applicability_queue_v1.csv",
        "papers/ieee_sensors_journal_experiments/p07/frontend_queue_lock_v1.json",
        "papers/ieee_sensors_journal_experiments/p07/mp_smoke_execution_lock_v2.json",
        "papers/ieee_sensors_journal_experiments/p07/frontend_attempts/queue_003_isj_p07_aqualoc_archaeology_a02_0005_p_attempt01/audit_v2.json",
        "papers/ieee_sensors_journal_experiments/p07/frontend_attempts/queue_003_isj_p07_aqualoc_archaeology_a02_0005_p_attempt01/output_hash_manifest.sha256",
        "logs/aqualoc_archaeo_vins/external_klt_every2_isj_p07_aqualoc_archaeology_a02_0005_p_attempt01_klt_safe_fallback/features.bag",
        "logs/aqualoc_archaeo_vins/external_klt_every2_isj_p07_aqualoc_archaeology_a02_0005_b1_attempt01/features.bag",
        "scripts/resolve_p07_a02_d_applicability_v1.py",
        "scripts/build_p07_a02_d_resolution_lock_v1.py",
        "scripts/tests/test_p07_a02_d_resolution_v1.py",
    },
}
LEGACY_PREFIX_PATHS = {
    "papers/ieee_sensors_journal_experiments/run_registry.csv",
    "papers/ieee_sensors_journal_experiments/arm_applicability.csv",
}


def canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def document_hash(payload: Mapping[str, object], field: str) -> str:
    clone = dict(payload)
    clone.pop(field, None)
    return hashlib.sha256(canonical_json(clone).encode("utf-8")).hexdigest()


def _timestamp(value: str) -> None:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise LegacyDCompatibilityError("frozen_at is not ISO-8601") from error
    if parsed.tzinfo is None:
        raise LegacyDCompatibilityError("frozen_at must include a timezone")


def _json(root: Path, relative: str) -> tuple[dict[str, Any], dict[str, object]]:
    path = root / relative
    try:
        content, record = provenance.rooted_io.read_bytes_and_record_bound_input_rooted(
            root, path, label=f"legacy D JSON {relative}"
        )
        payload = json.loads(content)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise LegacyDCompatibilityError(f"invalid legacy D JSON: {relative}") from error
    except Exception as error:
        raise LegacyDCompatibilityError(
            f"missing or unsafe legacy D JSON: {relative}"
        ) from error
    if not isinstance(payload, dict):
        raise LegacyDCompatibilityError(f"legacy D JSON is not an object: {relative}")
    return payload, record


def _validate_record(root: Path, record: Mapping[str, object]) -> dict[str, object]:
    try:
        relative = str(record["path"])
        digest = str(record["sha256"])
        size = int(record["size_bytes"])
    except (KeyError, TypeError, ValueError) as error:
        raise LegacyDCompatibilityError("invalid legacy lock artifact record") from error
    observed = provenance.file_record(root, root / relative)
    if observed["sha256"] != digest or observed["size_bytes"] != size:
        raise LegacyDCompatibilityError(f"legacy lock artifact drift: {relative}")
    return observed


def _validate_prefix(root: Path, snapshot: Mapping[str, object]) -> None:
    try:
        path = root / str(snapshot["path"])
        size = int(snapshot["size_bytes"])
        expected = str(snapshot["sha256"])
    except (KeyError, TypeError, ValueError) as error:
        raise LegacyDCompatibilityError("invalid legacy mutable prefix") from error
    try:
        content = provenance.rooted_io.read_bytes_bound_input_rooted(
            root, path, label="legacy D mutable prefix"
        )
    except Exception as error:
        raise LegacyDCompatibilityError(
            f"legacy mutable prefix is missing or unsafe: {path}"
        ) from error
    if (
        size < 0
        or len(content) < size
        or hashlib.sha256(content[:size]).hexdigest() != expected
    ):
        raise LegacyDCompatibilityError(f"legacy mutable prefix drift: {path}")


def read_applicability(
    root: Path, path: Path
) -> tuple[list[str], list[dict[str, str]]]:
    try:
        content = provenance.rooted_io.read_bytes_bound_input_rooted(
            root, path, label="canonical arm applicability"
        )
        text = content.decode("utf-8")
    except Exception as error:
        raise LegacyDCompatibilityError(
            "canonical arm applicability is missing or unsafe"
        ) from error
    reader = csv.DictReader(io.StringIO(text, newline=""))
    fields = list(reader.fieldnames or [])
    rows = list(reader)
    if not fields or len(fields) != len(set(fields)) or any(None in row for row in rows):
        raise LegacyDCompatibilityError("invalid canonical arm applicability CSV")
    return fields, rows


def _terminal_row(case: LegacyCase, rows: Sequence[Mapping[str, str]]) -> dict[str, str]:
    matches = [
        dict(row)
        for row in rows
        if row.get("protocol_version") == "isj-nativeq-v3-confirmatory-protocol-v1"
        and row.get("method_profile") == "P_legacy_nativeq_xfeat_seedchain_v3"
        and row.get("dataset_family") == "aqualoc_archaeology"
        and row.get("sequence") == case.sequence
        and row.get("window_start") == case.start
        and row.get("window_end") == case.end
        and row.get("proposed_arm") == "P_legacy_nativeq_xfeat_seedchain_v3"
        and row.get("drop_arm") == "D_legacy_exact_lineage_drop_v3"
        and row.get("resolution") != "PENDING_APPLICABILITY"
    ]
    if len(matches) != 1:
        raise LegacyDCompatibilityError(
            f"legacy D case lacks exactly one terminal canonical row: {case.window_id}"
        )
    return matches[0]


def _render_row(fields: Sequence[str], row: Mapping[str, str]) -> bytes:
    stream = io.StringIO(newline="")
    csv.DictWriter(stream, fieldnames=list(fields), lineterminator="\n").writerow(row)
    return stream.getvalue().encode("utf-8")


def build_sidecar(
    case: LegacyCase,
    *,
    root: Path,
    applicability_fields: Sequence[str],
    applicability_rows: Sequence[Mapping[str, str]],
) -> dict[str, object]:
    lock, lock_record = _json(root, case.lock_relative)
    terminal, terminal_record = _json(root, case.terminal_relative)
    if (
        lock.get("schema_version") != case.lock_schema
        or lock.get("status") != "FROZEN_READY_TO_APPEND_NOT_APPLICABLE"
        or lock.get("window_id") != case.window_id
        or int(lock.get("slot_index", -1)) != case.slot_index
        or lock.get("resolution_lock_hash")
        != document_hash(lock, "resolution_lock_hash")
        or lock.get("held_out_trajectory_outcome_read") is not False
    ):
        raise LegacyDCompatibilityError(f"legacy D lock mismatch: {case.label}")
    artifacts = lock.get("artifacts")
    prefixes = lock.get("mutable_stream_prefix_snapshots")
    if not isinstance(artifacts, list) or not isinstance(prefixes, list):
        raise LegacyDCompatibilityError("legacy D lock lacks artifact/prefix arrays")
    observed_artifact_paths: set[str] = set()
    for record in artifacts:
        if not isinstance(record, dict) or set(record) != {
            "path",
            "sha256",
            "size_bytes",
        }:
            raise LegacyDCompatibilityError("legacy D artifact is not an object")
        path_value = str(record.get("path", ""))
        if path_value in observed_artifact_paths:
            raise LegacyDCompatibilityError("legacy D artifact path is duplicated")
        observed_artifact_paths.add(path_value)
        _validate_record(root, record)
    if observed_artifact_paths != LEGACY_ARTIFACT_PATHS[case.label]:
        raise LegacyDCompatibilityError("legacy D exact artifact set drift")
    observed_prefix_paths: set[str] = set()
    for snapshot in prefixes:
        if (
            not isinstance(snapshot, dict)
            or set(snapshot) != {"binding", "path", "sha256", "size_bytes"}
            or snapshot.get("binding")
            != "PRE_RESOLUTION_APPEND_ONLY_PREFIX_SNAPSHOT"
            or type(snapshot.get("size_bytes")) is not int
            or int(snapshot["size_bytes"]) <= 0
        ):
            raise LegacyDCompatibilityError("legacy D prefix is not an object")
        observed_prefix_paths.add(str(snapshot["path"]))
        _validate_prefix(root, snapshot)
    if len(prefixes) != 2 or observed_prefix_paths != LEGACY_PREFIX_PATHS:
        raise LegacyDCompatibilityError("legacy D exact mutable-prefix set drift")
    if (
        terminal.get("schema_version") != case.terminal_schema
        or terminal.get("status") != "PASS_NOT_APPLICABLE"
        or terminal.get("window_id") != case.window_id
        or int(terminal.get("slot_index", -1)) != case.slot_index
        or terminal.get("resolution") != "NOT_APPLICABLE"
        or int(terminal.get("accepted_learned_born_lineage_count", -1)) != 0
        or terminal.get("d_bag_created") is not False
        or int(terminal.get("d_replay_slots_created", -1)) != 0
        or terminal.get("resolution_lock_hash") != lock["resolution_lock_hash"]
        or terminal.get("held_out_trajectory_outcome_read") is not False
    ):
        raise LegacyDCompatibilityError(f"legacy D terminal mismatch: {case.label}")
    evidence = terminal.get("evidence")
    if not isinstance(evidence, dict):
        raise LegacyDCompatibilityError("legacy D terminal lacks evidence")
    p_hash = str(evidence.get("p_feature_bag_sha256", ""))
    b1_hash = str(evidence.get("b1_feature_bag_sha256", ""))
    if (
        evidence.get("accepted_learned_born_lineage_count") != 0
        or evidence.get("active") is not False
        or evidence.get("zero_action_identity") != "PASS_BYTE_IDENTICAL_TO_B1"
        or p_hash != b1_hash
        or len(p_hash) != 64
    ):
        raise LegacyDCompatibilityError("legacy D zero-action identity mismatch")
    p_record = provenance.file_record(
        root, root / str(evidence.get("p_feature_bag", ""))
    )
    b1_record = provenance.file_record(
        root, root / str(evidence.get("b1_feature_bag", ""))
    )
    audit_record = provenance.file_record(root, root / str(evidence.get("audit", "")))
    if (
        p_record["sha256"] != p_hash
        or b1_record["sha256"] != b1_hash
        or audit_record["sha256"] != evidence.get("audit_sha256")
    ):
        raise LegacyDCompatibilityError("legacy D evidence file hash drift")
    canonical_row = _terminal_row(case, applicability_rows)
    rendered_hash = hashlib.sha256(
        _render_row(applicability_fields, canonical_row)
    ).hexdigest()
    canonical_stream = terminal.get("canonical_stream")
    if (
        canonical_row.get("accepted_lineage_count") != "0"
        or canonical_row.get("resolution") != "NOT_APPLICABLE"
        or canonical_row.get("resolver_hash") != lock["resolution_lock_hash"]
        or not isinstance(canonical_stream, dict)
        or canonical_stream.get("appended_row_sha256") != rendered_hash
    ):
        raise LegacyDCompatibilityError("legacy D canonical terminal row mismatch")
    payload: dict[str, object] = {
        "schema_version": SIDECAR_SCHEMA,
        "status": SIDECAR_STATUS,
        "window_id": case.window_id,
        "slot_index": case.slot_index,
        "resolution": "NOT_APPLICABLE",
        "accepted_learned_born_lineage_count": 0,
        "legacy_resolution_lock": lock_record,
        "legacy_resolution_lock_hash": lock["resolution_lock_hash"],
        "terminal_resolution": terminal_record,
        "parent_p_run_id": terminal.get("parent_p_run_id"),
        "p_feature_bag": p_record,
        "b1_feature_bag": b1_record,
        "p_b1_byte_identical": p_record["sha256"] == b1_record["sha256"],
        "parent_p_audit": audit_record,
        "canonical_applicability_row": canonical_row,
        "canonical_applicability_row_sha256": rendered_hash,
        "d_bag_created": False,
        "d_replay_slots_created": 0,
        "held_out_trajectory_outcome_read": False,
        "outcome_boundary": "FRONTEND_EXPORT_ONLY_NO_VINS_APE_RPE_TRAJECTORY",
    }
    payload["sidecar_hash"] = document_hash(payload, "sidecar_hash")
    return payload


def build_outputs(
    *,
    root: Path = ROOT,
    frozen_at: str,
    include_code_records: bool = True,
) -> dict[Path, bytes]:
    _timestamp(frozen_at)
    fields, rows = read_applicability(
        root,
        root / "papers/ieee_sensors_journal_experiments/arm_applicability.csv",
    )
    sidecars = [
        build_sidecar(
            case,
            root=root,
            applicability_fields=fields,
            applicability_rows=rows,
        )
        for case in CASES
    ]
    outputs = {
        root / case.sidecar_relative: formal_io.json_bytes(sidecar)
        for case, sidecar in zip(CASES, sidecars)
    }
    records = [
        {
            "path": case.sidecar_relative,
            "sha256": hashlib.sha256(outputs[root / case.sidecar_relative]).hexdigest(),
            "size_bytes": len(outputs[root / case.sidecar_relative]),
            "sidecar_hash": sidecar["sidecar_hash"],
            "window_id": case.window_id,
        }
        for case, sidecar in zip(CASES, sidecars)
    ]
    code_records: list[dict[str, object]] = []
    if include_code_records:
        for relative in (
            "scripts/build_p07_backend_legacy_d_compatibility_lock_v1.py",
            "scripts/p07_backend_formal_io_v1.py",
            "scripts/p07_backend_frontend_provenance_v1.py",
            "scripts/tests/test_p07_backend_legacy_d_compatibility_lock_v1.py",
        ):
            code_records.append(provenance.file_record(root, root / relative))
    lock: dict[str, object] = {
        "schema_version": LOCK_SCHEMA,
        "status": LOCK_STATUS,
        "frozen_at": frozen_at,
        "legacy_windows": [case.window_id for case in CASES],
        "sidecars": records,
        "source_evidence": [
            {
                "window_id": case.window_id,
                "legacy_resolution_lock": provenance.file_record(
                    root, root / case.lock_relative
                ),
                "terminal_resolution": provenance.file_record(
                    root, root / case.terminal_relative
                ),
            }
            for case in CASES
        ],
        "artifacts": code_records,
        "authorization": (
            "BACKEND_QUEUE_MAY_BIND_LEGACY_D_TERMINALS_ONLY_AFTER_THIS_LOCK"
        ),
        "held_out_trajectory_outcome_read": False,
        "outcome_boundary": "FRONTEND_EXPORT_ONLY_NO_VINS_APE_RPE_TRAJECTORY",
    }
    lock["compatibility_lock_hash"] = document_hash(
        lock, "compatibility_lock_hash"
    )
    outputs[root / OUTPUT.relative_to(ROOT)] = formal_io.json_bytes(lock)
    return outputs


def validate_live_bundle(*, root: Path = ROOT) -> dict[str, object]:
    """Validate and deterministically rebuild the committed compatibility bundle."""

    output = root / OUTPUT.relative_to(ROOT)
    payload, _record = _json(root, output.relative_to(root).as_posix())
    if (
        payload.get("schema_version") != LOCK_SCHEMA
        or payload.get("status") != LOCK_STATUS
        or payload.get("compatibility_lock_hash")
        != document_hash(payload, "compatibility_lock_hash")
        or payload.get("legacy_windows") != [case.window_id for case in CASES]
        or payload.get("held_out_trajectory_outcome_read") is not False
    ):
        raise LegacyDCompatibilityError(
            "legacy-D compatibility lock schema/status/hash mismatch"
        )
    sidecars = payload.get("sidecars")
    if not isinstance(sidecars, list) or len(sidecars) != len(CASES):
        raise LegacyDCompatibilityError("legacy-D compatibility sidecar set mismatch")
    expected_paths = {case.sidecar_relative for case in CASES}
    observed_paths: set[str] = set()
    for item in sidecars:
        if not isinstance(item, dict):
            raise LegacyDCompatibilityError("legacy-D sidecar record is not an object")
        record = _validate_record(root, item)
        observed_paths.add(str(record["path"]))
        sidecar, _sidecar_record = _json(root, str(record["path"]))
        if (
            sidecar.get("schema_version") != SIDECAR_SCHEMA
            or sidecar.get("status") != SIDECAR_STATUS
            or sidecar.get("sidecar_hash") != document_hash(sidecar, "sidecar_hash")
            or sidecar.get("window_id") != item.get("window_id")
            or sidecar.get("sidecar_hash") != item.get("sidecar_hash")
            or sidecar.get("p_b1_byte_identical") is not True
            or sidecar.get("held_out_trajectory_outcome_read") is not False
        ):
            raise LegacyDCompatibilityError("legacy-D sidecar semantic mismatch")
    if observed_paths != expected_paths:
        raise LegacyDCompatibilityError("legacy-D compatibility sidecar paths mismatch")
    frozen_at = str(payload.get("frozen_at", ""))
    code_records = payload.get("artifacts")
    if not isinstance(code_records, list):
        raise LegacyDCompatibilityError("legacy-D compatibility artifacts malformed")
    rebuilt = build_outputs(
        root=root,
        frozen_at=frozen_at,
        include_code_records=bool(code_records),
    )
    expected_output_paths = {
        root / case.sidecar_relative for case in CASES
    } | {output}
    if set(rebuilt) != expected_output_paths:
        raise LegacyDCompatibilityError("legacy-D deterministic output set mismatch")
    for path, content in rebuilt.items():
        try:
            observed = provenance.rooted_io.read_bytes_bound_input_rooted(
                root, path, label="legacy-D deterministic output"
            )
        except Exception as error:
            raise LegacyDCompatibilityError(
                f"legacy-D deterministic output is missing or unsafe: {path}"
            ) from error
        if observed != content:
            raise LegacyDCompatibilityError(
                f"legacy-D deterministic rebuild drift: {path.relative_to(root)}"
            )
    return payload


def _relative(root: Path, path: Path) -> str:
    return path.absolute().relative_to(root.absolute()).as_posix()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--frozen-at", required=True)
    parser.add_argument("--preflight-only", action="store_true")
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()
    outputs = build_outputs(frozen_at=args.frozen_at)
    lock = json.loads(outputs[OUTPUT])
    if args.preflight_only:
        print(
            json.dumps(
                {
                    "status": "READY",
                    "legacy_windows": lock["legacy_windows"],
                    "compatibility_lock_hash": lock["compatibility_lock_hash"],
                    "held_out_trajectory_outcome_read": False,
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 0
    if not args.write:
        parser.error("refusing formal legacy-D generation without --write")
    formal_io.publish_bundle_commit_last(
        ROOT,
        [
            (_relative(ROOT, path), content)
            for path, content in outputs.items()
            if path != OUTPUT
        ],
        commit_artifact=(_relative(ROOT, OUTPUT), outputs[OUTPUT]),
    )
    print(
        "P07_BACKEND_LEGACY_D_COMPATIBILITY_FROZEN "
        f"hash={lock['compatibility_lock_hash']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
