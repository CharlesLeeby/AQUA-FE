#!/usr/bin/env python3
"""Freeze the serial, no-clobber P07 backend replay execution contract."""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import math
import os
import shutil
import stat
from pathlib import Path, PurePosixPath
from typing import Any, Mapping, Sequence

try:
    from scripts import build_p07_backend_b0_formalization_adoption_bridge_v1 as b0_adoption_bridge
    from scripts import build_p07_backend_b0_materialization_lock_v1 as b0_plan
    from scripts import build_p07_backend_formalization_adoption_v1 as adoption
    from scripts import build_p07_backend_formalization_review_evidence_v1 as review_evidence
    from scripts import build_p07_backend_replacement_contract_v1 as replacement
    from scripts import build_p07_backend_replay_queue_v1 as queue_builder
    from scripts import p07_backend_replay_common_v1 as runtime_common
    from scripts import p07_g0_governance_v1 as g0_governance
    from scripts import register_p07_backend_allocations_v1 as registration
    from scripts import run_p07_backend_b0_materialization_v1 as b0_materializer
    from scripts import validate_p07_backend_replay_queue_v1 as queue_validator
except ModuleNotFoundError:  # Direct ``python3 scripts/...`` execution.
    import build_p07_backend_b0_formalization_adoption_bridge_v1 as b0_adoption_bridge  # type: ignore
    import build_p07_backend_b0_materialization_lock_v1 as b0_plan  # type: ignore
    import build_p07_backend_formalization_adoption_v1 as adoption  # type: ignore
    import build_p07_backend_formalization_review_evidence_v1 as review_evidence  # type: ignore
    import build_p07_backend_replacement_contract_v1 as replacement  # type: ignore
    import build_p07_backend_replay_queue_v1 as queue_builder  # type: ignore
    import p07_backend_replay_common_v1 as runtime_common  # type: ignore
    import p07_g0_governance_v1 as g0_governance  # type: ignore
    import register_p07_backend_allocations_v1 as registration  # type: ignore
    import run_p07_backend_b0_materialization_v1 as b0_materializer  # type: ignore
    import validate_p07_backend_replay_queue_v1 as queue_validator  # type: ignore


OUTPUT = queue_builder.P07 / "backend_replay_execution_lock_v1.json"
QUEUE_VALIDATION = queue_validator.OUTPUT
SCHEMA = "isj-p07-backend-replay-execution-lock-v1"
STATUS = "FROZEN_READY_FOR_SERIAL_BACKEND_REPLAY"
GLOBAL_FLOCK_PATH = "/tmp/aquafe_p07_backend_replay_v1.lock"

MARGIN_NUMERATOR = 6
MARGIN_DENOMINATOR = 5
RESERVE_BYTES = 2 * 1024**3
MINIMUM_GOVERNANCE_FREE_BYTES = 512 * 1024**2

ADAPTER = queue_builder.ROOT / "scripts/run_p07_backend_replay_adapter_v1.py"
EXECUTOR = queue_builder.ROOT / "scripts/run_p07_backend_replay_job_v1.py"
AUDITOR = queue_builder.ROOT / "scripts/audit_p07_backend_replay_v1.py"
INPUT_CHECKER = queue_builder.ROOT / "scripts/check_p07_backend_replay_input_v1.py"
COMMON = queue_builder.ROOT / "scripts/p07_backend_replay_common_v1.py"
SERIAL_CONTROLLER = queue_builder.ROOT / "scripts/run_p07_backend_serial_queue_v1.py"
RUNTIME_IDENTITY_TEST = (
    queue_builder.ROOT / "scripts/tests/test_p07_backend_runtime_identity_v1.py"
)
SAFETY_TEST = queue_builder.ROOT / "scripts/tests/test_p07_backend_replay_safety_v1.py"
G0_LOCK = g0_governance.DEFAULT_EVALUATION_LOCK
G0_GOVERNANCE = queue_builder.ROOT / "scripts/p07_g0_governance_v1.py"
B0_PLAN = b0_plan.OUTPUT
B0_INTENT = b0_plan.INTENT
B0_RECEIPT = b0_plan.RECEIPT
B0_PLAY_INPUTS = b0_plan.FINAL_OUTPUT
B0_PLAN_BUILDER = (
    queue_builder.ROOT / "scripts/build_p07_backend_b0_materialization_lock_v1.py"
)
B0_MATERIALIZER = queue_builder.ROOT / "scripts/run_p07_backend_b0_materialization_v1.py"
B0_MATERIALIZATION_TEST = (
    queue_builder.ROOT / "scripts/tests/test_p07_backend_b0_materialization_v1.py"
)
FORMALIZATION_ADOPTION = queue_builder.ROOT / adoption.OUTPUT_RELATIVE
B0_ADOPTION_PRELOCK = b0_adoption_bridge.PRELOCK
B0_ADOPTION_ACTION_INTENT = b0_adoption_bridge.ACTION_INTENT
B0_ADOPTION_CLOSEOUT = b0_adoption_bridge.CLOSEOUT
B0_ADOPTION_BRIDGE_BUILDER = queue_builder.ROOT / b0_adoption_bridge.BRIDGE_BUILDER
B0_ADOPTION_BRIDGE_RUNNER = queue_builder.ROOT / b0_adoption_bridge.BRIDGE_RUNNER
B0_ADOPTION_BRIDGE_TEST = queue_builder.ROOT / b0_adoption_bridge.BRIDGE_TEST

DIRECT_RUNNERS = (
    queue_builder.ROOT / "scripts/run_aqualoc_archaeo_vins_eval.sh",
    queue_builder.ROOT / "scripts/run_aqualoc_real_vins_eval.sh",
    queue_builder.ROOT / "scripts/run_ntnu_vins_eval.sh",
    queue_builder.ROOT / "scripts/run_afrl_cave_vins_eval.sh",
)
B0_WRAPPER = queue_builder.ROOT / "scripts/run_isj_b0_native_vins_guarded_v1.sh"
BACKEND_CONTRACT = queue_builder.BUNDLE / "backend_quality_contract_v1.json"
M_CONTRACT = queue_builder.BUNDLE / "p05/backend_consumer_contract_xfeat_v1.json"
NATIVEQ_CONTRACT_CHECKER = (
    queue_builder.ROOT / "scripts/check_nativeq_backend_contract.py"
)
XFEAT_CONTRACT_CHECKER = (
    queue_builder.ROOT / "scripts/check_p05_xfeat_backend_contract_v1.py"
)
REPLAY_ONLY_RUNNER = queue_builder.ROOT / "scripts/run_p07_backend_replay_only_v1.sh"
CONFIG_HELPER = queue_builder.ROOT / "scripts/prepare_p07_backend_replay_config_v1.py"
DATA_ELIGIBILITY = queue_builder.BUNDLE / "data_eligibility_manifest.csv"
DATASET_CHECKSUMS = queue_builder.BUNDLE / "dataset_checksum_manifest.txt"
REFERENCE_AUDIT = queue_builder.BUNDLE / "reference_audit.csv"
DATA_IDENTITY_SCHEMA = "isj-p07-backend-data-identity-snapshot-v1"
DATA_IDENTITY_STATUS = "VERIFIED_AT_EXECUTION_LOCK_FREEZE"


class ExecutionLockError(RuntimeError):
    """Raised when the queue is not safe to authorize for replay."""


def data_identity_snapshot_hash(payload: Mapping[str, object]) -> str:
    clone = dict(payload)
    clone.pop("data_identity_snapshot_hash", None)
    return hashlib.sha256(
        queue_builder.canonical_json(clone).encode("utf-8")
    ).hexdigest()


def _read_direct_snapshot(
    root: Path, path: Path, *, label: str
) -> tuple[bytes, dict[str, object]]:
    try:
        relative = runtime_common.display_path(root, path)
        content, _identity = queue_builder.formal_io.read_direct_bytes(
            root, relative
        )
    except (
        OSError,
        ValueError,
        queue_builder.formal_io.FormalIOError,
    ) as error:
        raise ExecutionLockError(f"cannot read direct {label}: {path}") from error
    return content, {
        "path": relative,
        "sha256": hashlib.sha256(content).hexdigest(),
        "size_bytes": len(content),
    }


def _read_direct_bytes(root: Path, path: Path, *, label: str) -> bytes:
    content, _record = _read_direct_snapshot(root, path, label=label)
    return content


def _json_from_bytes(content: bytes, path: Path, *, label: str) -> dict[str, Any]:
    def reject_duplicates(pairs: Sequence[tuple[str, Any]]) -> dict[str, Any]:
        value: dict[str, Any] = {}
        for key, item in pairs:
            if key in value:
                raise ExecutionLockError(f"duplicate {label} JSON key: {key}")
            value[key] = item
        return value

    try:
        value = json.loads(
            content.decode("utf-8"), object_pairs_hook=reject_duplicates
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ExecutionLockError) as error:
        raise ExecutionLockError(f"invalid {label} JSON: {path}") from error
    if not isinstance(value, dict):
        raise ExecutionLockError(f"{label} is not an object: {path}")
    if content != queue_builder.formal_io.json_bytes(value):
        raise ExecutionLockError(f"noncanonical {label} JSON: {path}")
    return value


def _read_direct_json(root: Path, path: Path, *, label: str) -> dict[str, Any]:
    return _json_from_bytes(
        _read_direct_bytes(root, path, label=label), path, label=label
    )


def _manifest_rows_from_bytes(
    content: bytes, path: Path
) -> list[dict[str, str]]:
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError as error:
        raise ExecutionLockError(f"invalid data-identity CSV: {path}") from error
    reader = csv.DictReader(io.StringIO(text, newline=""))
    fields = list(reader.fieldnames or [])
    rows = list(reader)
    if not fields or len(fields) != len(set(fields)) or any(None in row for row in rows):
        raise ExecutionLockError(f"invalid data-identity CSV: {path}")
    return rows


def _manifest_rows(path: Path, *, root: Path) -> list[dict[str, str]]:
    return _manifest_rows_from_bytes(
        _read_direct_bytes(root, path, label="data-identity CSV"), path
    )


def _checksum_rows_from_bytes(content: bytes) -> dict[str, str]:
    result: dict[str, str] = {}
    try:
        lines = content.decode("utf-8").splitlines()
    except UnicodeDecodeError as error:
        raise ExecutionLockError("dataset checksum manifest is not UTF-8") from error
    for number, line in enumerate(lines, 1):
        parts = line.split("  ", 1)
        if (
            len(parts) != 2
            or len(parts[0]) != 64
            or any(character not in "0123456789abcdef" for character in parts[0])
            or not parts[1]
            or parts[1] in result
        ):
            raise ExecutionLockError(f"invalid checksum manifest line {number}")
        result[parts[1]] = parts[0]
    if not result:
        raise ExecutionLockError("dataset checksum manifest is empty")
    return result


def _checksum_rows(path: Path, *, root: Path) -> dict[str, str]:
    return _checksum_rows_from_bytes(
        _read_direct_bytes(root, path, label="dataset checksum manifest")
    )


def _record_for_root(root: Path, path: Path) -> dict[str, object]:
    _content, record = _read_direct_snapshot(root, path, label="locked artifact")
    return record


def collect_data_identity_snapshot(
    queue_rows: Sequence[Mapping[str, str]],
    *,
    root: Path = queue_builder.ROOT,
    eligibility_path: Path = DATA_ELIGIBILITY,
    checksum_path: Path = DATASET_CHECKSUMS,
    reference_audit_path: Path = REFERENCE_AUDIT,
    frozen_manifest_snapshots: Mapping[
        Path, tuple[bytes, Mapping[str, object]]
    ]
    | None = None,
) -> dict[str, object]:
    """Hash each unique frozen data input once without interpreting its values."""

    if frozen_manifest_snapshots is None:
        eligibility_content, eligibility_record = _read_direct_snapshot(
            root, eligibility_path, label="data eligibility manifest"
        )
        checksum_content, checksum_record = _read_direct_snapshot(
            root, checksum_path, label="dataset checksum manifest"
        )
        reference_content, reference_record = _read_direct_snapshot(
            root, reference_audit_path, label="reference audit"
        )
    else:
        expected = {eligibility_path, checksum_path, reference_audit_path}
        if set(frozen_manifest_snapshots) != expected:
            raise ExecutionLockError("frozen data-identity manifest set mismatch")
        eligibility_content, eligibility_record = frozen_manifest_snapshots[
            eligibility_path
        ]
        checksum_content, checksum_record = frozen_manifest_snapshots[checksum_path]
        reference_content, reference_record = frozen_manifest_snapshots[
            reference_audit_path
        ]
    eligibility = _manifest_rows_from_bytes(eligibility_content, eligibility_path)
    audits = _manifest_rows_from_bytes(reference_content, reference_audit_path)
    checksums = _checksum_rows_from_bytes(checksum_content)
    requested = sorted(
        {(str(row["dataset_family"]), str(row["sequence"])) for row in queue_rows}
    )
    if not requested:
        raise ExecutionLockError("cannot snapshot data identity for an empty queue")
    bindings: list[dict[str, object]] = []
    path_uses: dict[str, dict[str, set[str]]] = {}
    for family, sequence in requested:
        eligible_rows = [
            row
            for row in eligibility
            if row.get("dataset_family") == family and row.get("sequence") == sequence
        ]
        audit_rows = [
            row
            for row in audits
            if row.get("dataset_family") == family and row.get("sequence") == sequence
        ]
        if len(eligible_rows) != 1 or len(audit_rows) != 1:
            raise ExecutionLockError(
                f"data identity lacks unique eligibility/audit row: {family}/{sequence}"
            )
        eligible = eligible_rows[0]
        audit = audit_rows[0]
        if eligible.get("eligibility") not in {
            "ELIGIBLE",
            "ELIGIBLE_WITH_REFERENCE_CAVEAT",
        }:
            raise ExecutionLockError(f"ineligible dataset in backend queue: {family}/{sequence}")
        raw = eligible.get("raw_input_path", "")
        reference_path_value = eligible.get("reference_path", "")
        calibrations = sorted(
            {item for item in eligible.get("calibration_paths", "").split(";") if item}
        )
        if (
            audit.get("raw_input_path") != raw
            or audit.get("reference_path") != reference_path_value
            or audit.get("reference_exists") != "true"
            or audit.get("eligibility") != eligible.get("eligibility")
        ):
            raise ExecutionLockError(f"eligibility/reference audit drift: {family}/{sequence}")
        binding = {
            "dataset_family": family,
            "sequence": sequence,
            "raw_input_path": raw,
            "reference_path": reference_path_value,
            "calibration_paths": calibrations,
        }
        bindings.append(binding)
        for kind, values in (
            ("raw", [raw]),
            ("reference", [reference_path_value]),
            ("calibration", calibrations),
        ):
            for raw_path in values:
                if not raw_path:
                    raise ExecutionLockError(
                        f"empty {kind} identity path: {family}/{sequence}"
                    )
                use = path_uses.setdefault(
                    raw_path, {"kinds": set(), "datasets": set()}
                )
                use["kinds"].add(kind)
                use["datasets"].add(f"{family}:{sequence}")
        if checksums.get(reference_path_value) != audit.get("reference_sha256"):
            raise ExecutionLockError(
                f"reference audit/checksum mismatch: {family}/{sequence}"
            )
        expected_raw_size = eligible.get("expected_raw_size_bytes", "")
        if expected_raw_size and int(expected_raw_size) != int(
            eligible.get("raw_size_bytes", "-1")
        ):
            raise ExecutionLockError(f"raw manifest size mismatch: {family}/{sequence}")

    entries: list[dict[str, object]] = []
    for raw_path, use in sorted(path_uses.items()):
        expected = checksums.get(raw_path)
        if expected is None:
            raise ExecutionLockError(f"checksum manifest lacks data input: {raw_path}")
        try:
            identity = runtime_common.capture_canonical_input_identity(
                root,
                raw_path,
                expected_sha256=expected,
                verify_sha256=True,
            )
        except runtime_common.BackendReplayViolation as error:
            raise ExecutionLockError(
                f"data input identity/hash freeze failed: {raw_path}: {error}"
            ) from error
        identity.update(
            {
                "kinds": sorted(use["kinds"]),
                "datasets": sorted(use["datasets"]),
                "sha256_verified_at_freeze": True,
            }
        )
        entries.append(identity)
    payload: dict[str, object] = {
        "schema_version": DATA_IDENTITY_SCHEMA,
        "status": DATA_IDENTITY_STATUS,
        "manifest_records": [
            dict(record)
            for record in (eligibility_record, checksum_record, reference_record)
        ],
        "dataset_bindings": bindings,
        "entries": entries,
        "verification": {
            "full_sha256_once_at_execution_lock_freeze": True,
            "stat_identity_before_each_replay": True,
            "manifest_files_rehashed_before_each_replay": True,
            "symlink_chain_before_each_replay": True,
            "trajectory_values_interpreted": False,
        },
    }
    payload["data_identity_snapshot_hash"] = data_identity_snapshot_hash(payload)
    return payload


def validate_data_identity_snapshot_shape(
    snapshot: Mapping[str, object], queue_rows: Sequence[Mapping[str, str]]
) -> None:
    try:
        runtime_common.validate_data_identity_snapshot_shape(snapshot, queue_rows)
    except runtime_common.BackendReplayViolation as error:
        raise ExecutionLockError(f"data identity snapshot drift: {error}") from error


def execution_lock_hash(payload: Mapping[str, object]) -> str:
    clone = dict(payload)
    clone.pop("execution_lock_hash", None)
    return hashlib.sha256(
        queue_builder.canonical_json(clone).encode("utf-8")
    ).hexdigest()


def prefix_snapshot(path: Path) -> dict[str, object]:
    content = _read_direct_bytes(
        queue_builder.ROOT, path, label="mutable registry prefix"
    )
    return {
        "path": queue_builder.display_path(path),
        "sha256": hashlib.sha256(content).hexdigest(),
        "size_bytes": len(content),
    }


def required_output_free_bytes(estimated_total_output_bytes: int) -> int:
    return (
        math.ceil(
            estimated_total_output_bytes * MARGIN_NUMERATOR / MARGIN_DENOMINATOR
        )
        + RESERVE_BYTES
    )


def _record_dict(path: Path) -> dict[str, object]:
    content = _read_direct_bytes(
        queue_builder.ROOT, path, label="required execution artifact"
    )
    return {
        "path": queue_builder.display_path(path),
        "sha256": hashlib.sha256(content).hexdigest(),
        "size_bytes": len(content),
    }


def _external_record(path: Path, *, label: str) -> dict[str, object]:
    path = Path(os.path.abspath(os.fspath(path)))
    flags = os.O_RDONLY | os.O_CLOEXEC
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        fd = os.open(path, flags)
        try:
            info = os.fstat(fd)
            if not os.path.isfile(f"/proc/self/fd/{fd}"):
                raise ExecutionLockError(f"{label} is not a regular file: {path}")
            digest = hashlib.sha256()
            offset = 0
            while offset < info.st_size:
                chunk = os.pread(fd, min(1024 * 1024, info.st_size - offset), offset)
                if not chunk:
                    raise ExecutionLockError(f"short read from {label}: {path}")
                digest.update(chunk)
                offset += len(chunk)
        finally:
            os.close(fd)
    except OSError as error:
        raise ExecutionLockError(f"cannot open {label}: {path}") from error
    return {
        "path": os.fspath(path),
        "sha256": digest.hexdigest(),
        "size_bytes": info.st_size,
    }


def _same_portable_file_record(
    observed: object, expected: Mapping[str, object]
) -> bool:
    """Compare portable identity when direct reads also report inode fields."""

    return isinstance(observed, Mapping) and all(
        observed.get(key) == expected.get(key)
        for key in ("path", "sha256", "size_bytes")
    )


def _valid_authority_binding(
    value: object,
    *,
    expected_path: str,
    self_hash_field: str,
) -> bool:
    """Validate the exact portable record used for a formal authority."""

    return (
        isinstance(value, Mapping)
        and set(value) == {"path", "sha256", "size_bytes", self_hash_field}
        and value.get("path") == expected_path
        and b0_adoption_bridge.HEX64.fullmatch(str(value.get("sha256", "")))
        is not None
        and type(value.get("size_bytes")) is int
        and int(value["size_bytes"]) > 0
        and b0_adoption_bridge.HEX64.fullmatch(
            str(value.get(self_hash_field, ""))
        )
        is not None
    )


def build_lock_payload(
    *,
    frozen_at: str,
    queue_rows: Sequence[Mapping[str, str]],
    queue_record: Mapping[str, object],
    allocation_record: Mapping[str, object],
    queue_lock_record: Mapping[str, object],
    validation_record: Mapping[str, object],
    registration_record: Mapping[str, object],
    allowed_entrypoint_record: Mapping[str, object],
    executor_record: Mapping[str, object],
    adapter_record: Mapping[str, object],
    auditor_record: Mapping[str, object],
    artifacts: Sequence[Mapping[str, object]],
    external_runtime_bindings: Mapping[str, Mapping[str, object]],
    formalization_adoption: Mapping[str, object],
    formalization_review_evidence: Mapping[str, object],
    b0_adoption_prelock: Mapping[str, object],
    b0_adoption_action_intent: Mapping[str, object],
    b0_adoption_closeout: Mapping[str, object],
    replacement_contract_binding: Mapping[str, object],
    data_identity_snapshot: Mapping[str, object],
    b0_play_inputs: Mapping[str, object],
    g0_pre_replay_authority: Mapping[str, object],
    mutable_registry_prefix: Mapping[str, object],
    output_free_bytes: int,
    governance_free_bytes: int,
    root: Path = queue_builder.ROOT,
) -> dict[str, object]:
    queue_builder.allocation_stamp(frozen_at)
    estimated_total = sum(int(row["estimated_output_bytes"]) for row in queue_rows)
    required_free = required_output_free_bytes(estimated_total)
    if output_free_bytes < required_free:
        raise ExecutionLockError(
            f"output capacity gate failed: {output_free_bytes} < {required_free}"
        )
    if governance_free_bytes < MINIMUM_GOVERNANCE_FREE_BYTES:
        raise ExecutionLockError(
            "governance capacity gate failed: "
            f"{governance_free_bytes} < {MINIMUM_GOVERNANCE_FREE_BYTES}"
        )
    if not queue_rows:
        raise ExecutionLockError("cannot freeze an empty backend queue")
    queue_hashes = {str(row["method_lock_hash"]) for row in queue_rows}
    if len(queue_hashes) != 1:
        raise ExecutionLockError("backend queue has mixed method lock hashes")
    if (
        replacement_contract_binding.get("schema_version") != replacement.SCHEMA
        or replacement_contract_binding.get("status") != replacement.STATUS
        or not isinstance(replacement_contract_binding.get("contract"), dict)
        or not isinstance(
            replacement_contract_binding.get("replacement_contract_hash"), str
        )
        or replacement_contract_binding.get("formalization_adoption")
        != formalization_adoption
        or replacement_contract_binding.get("formalization_review_evidence")
        != formalization_review_evidence
    ):
        raise ExecutionLockError("replacement contract binding is not READY")
    if not _valid_authority_binding(
        formalization_adoption,
        expected_path=adoption.OUTPUT_RELATIVE,
        self_hash_field=adoption.SELF_HASH_FIELD,
    ):
        raise ExecutionLockError("formalization adoption binding is invalid")
    if not _valid_authority_binding(
        formalization_review_evidence,
        expected_path=review_evidence.OUTPUT_RELATIVE,
        self_hash_field=review_evidence.SELF_HASH_FIELD,
    ):
        raise ExecutionLockError("formalization review-evidence binding is invalid")
    for value, path, field, label in (
        (
            b0_adoption_prelock,
            queue_builder.display_path(B0_ADOPTION_PRELOCK),
            b0_adoption_bridge.PRELOCK_HASH,
            "B0 adoption prelock",
        ),
        (
            b0_adoption_action_intent,
            queue_builder.display_path(B0_ADOPTION_ACTION_INTENT),
            b0_adoption_bridge.ACTION_INTENT_HASH,
            "B0 adoption action intent",
        ),
        (
            b0_adoption_closeout,
            queue_builder.display_path(B0_ADOPTION_CLOSEOUT),
            b0_adoption_bridge.CLOSEOUT_HASH,
            "B0 adoption closeout",
        ),
    ):
        if not _valid_authority_binding(
            value, expected_path=path, self_hash_field=field
        ):
            raise ExecutionLockError(f"{label} binding is invalid")
    validate_data_identity_snapshot_shape(data_identity_snapshot, queue_rows)
    try:
        runtime_common.validate_b0_play_inputs_shape(b0_play_inputs, queue_rows)
    except runtime_common.BackendReplayViolation as error:
        raise ExecutionLockError(f"B0 play-input contract drift: {error}") from error
    try:
        g0_authority_hash = g0_governance.validate_execution_authority_binding(
            g0_pre_replay_authority, root=root
        )
    except g0_governance.G0GovernanceError as error:
        raise ExecutionLockError(f"G0 pre-replay authority drift: {error}") from error
    if g0_pre_replay_authority.get("g0_execution_authority_hash") != g0_authority_hash:
        raise ExecutionLockError("G0 pre-replay authority self-hash mismatch")
    artifact_by_path = {
        str(record.get("path")): record
        for record in artifacts
        if isinstance(record, Mapping)
    }
    if len(artifact_by_path) != len(artifacts):
        raise ExecutionLockError("execution-lock artifacts contain duplicate paths")
    missing_runtime = set(
        runtime_common.RUNTIME_IMPLEMENTATION_BINDING_PATHS.values()
    ).difference(artifact_by_path)
    if missing_runtime:
        raise ExecutionLockError(
            f"execution lock omits runtime implementations: {sorted(missing_runtime)}"
        )
    runtime_implementation_bindings = {
        role: dict(artifact_by_path[relative])
        for role, relative in sorted(
            runtime_common.RUNTIME_IMPLEMENTATION_BINDING_PATHS.items()
        )
    }
    try:
        runtime_common.validate_runtime_import_closure(
            root, runtime_implementation_bindings
        )
    except runtime_common.BackendReplayViolation as error:
        raise ExecutionLockError(
            f"runtime transitive import closure drift: {error}"
        ) from error
    if set(external_runtime_bindings) != set(
        runtime_common.EXTERNAL_RUNTIME_BINDING_PATHS
    ):
        raise ExecutionLockError("external runtime binding role set differs")
    normalized_external_runtime = {
        role: dict(external_runtime_bindings[role])
        for role in sorted(runtime_common.EXTERNAL_RUNTIME_BINDING_PATHS)
    }
    try:
        runtime_common._validate_external_runtime_bindings(  # noqa: SLF001
            {"external_runtime_bindings": normalized_external_runtime}
        )
    except runtime_common.BackendReplayViolation as error:
        raise ExecutionLockError(f"external runtime binding drift: {error}") from error
    required_embedded_paths = {
        queue_builder.display_path(FORMALIZATION_ADOPTION),
        review_evidence.OUTPUT_RELATIVE,
        queue_builder.display_path(B0_ADOPTION_PRELOCK),
        queue_builder.display_path(B0_ADOPTION_ACTION_INTENT),
        queue_builder.display_path(B0_ADOPTION_CLOSEOUT),
        queue_builder.display_path(B0_PLAN),
        queue_builder.display_path(B0_INTENT),
        queue_builder.display_path(B0_RECEIPT),
        queue_builder.display_path(B0_PLAY_INPUTS),
    }
    if required_embedded_paths.difference(artifact_by_path):
        raise ExecutionLockError(
            "execution lock omits adoption/B0 materialization artifacts"
        )
    g0_lock_record = g0_pre_replay_authority.get("evaluation_lock")
    if not isinstance(g0_lock_record, Mapping):
        raise ExecutionLockError("G0 authority lacks evaluation-lock record")
    frozen_g0_record = artifact_by_path.get(str(g0_lock_record.get("path")))
    if not isinstance(frozen_g0_record, Mapping) or any(
        frozen_g0_record.get(key) != g0_lock_record.get(key)
        for key in ("path", "sha256", "size_bytes")
    ):
        raise ExecutionLockError("execution artifacts omit exact G0 evaluation lock")
    payload: dict[str, object] = {
        "schema_version": SCHEMA,
        "status": STATUS,
        "frozen_at": frozen_at,
        "formalization_adoption": dict(formalization_adoption),
        "formalization_review_evidence": dict(formalization_review_evidence),
        "b0_formalization_adoption": {
            "pre_materialization_lock": dict(b0_adoption_prelock),
            "materialization_action_intent": dict(b0_adoption_action_intent),
            "post_materialization_closeout": dict(b0_adoption_closeout),
        },
        "backend_queue_lock_hash": queue_lock_record.get("backend_queue_lock_hash"),
        "queue_sha256": queue_record["sha256"],
        "allocation_sha256": allocation_record["sha256"],
        "queue_lock_sha256": queue_lock_record["sha256"],
        "validation_sha256": validation_record["sha256"],
        "registration_sha256": registration_record["sha256"],
        "queue_items": len(queue_rows),
        "execution_order": [
            {
                "queue_index": int(row["queue_index"]),
                "run_id": row["run_id"],
                "window_id": row["window_id"],
                "arm": row["arm"],
                "replay_index": int(row["replay_index"]),
                "algorithmic_slot": row["algorithmic_slot"],
                "feature_bag_sha256": row["feature_bag_sha256"],
                "attestation_sha256": row["attestation_sha256"],
                "input_audit_sha256": row["input_audit_sha256"],
                "source_run_id": row["source_run_id"],
                "source_provenance_kind": row["source_provenance_kind"],
                "source_provenance_hash": row["source_provenance_hash"],
                "expected_run_dir": row["expected_run_dir"],
                "expected_attempt_dir": row["expected_attempt_dir"],
            }
            for row in queue_rows
        ],
        "allowed_entrypoint": dict(allowed_entrypoint_record),
        "executor": dict(executor_record),
        "adapter": dict(adapter_record),
        "auditor": dict(auditor_record),
        "runtime_implementation_bindings": runtime_implementation_bindings,
        "external_runtime_bindings": normalized_external_runtime,
        "global_flock_path": GLOBAL_FLOCK_PATH,
        "serialization": {
            "one_ros_vins_rosbag_group_at_a_time": True,
            "queue_order_mandatory": True,
            "three_replays_per_arm_are_consecutive": True,
            "algorithmic_slots": ["b01", "b02", "b03"],
            "infrastructure_replacement_consumes_algorithmic_slot": False,
        },
        "adapter_policy": {
            "allowed_vins_workspace": "/home/ma/SLAM/VINS-Fusion-origin",
            "forbidden_workspace": "/home/ma/SLAM/VINS-Fusion_3-15-WS",
            "required_environment": {
                "preparation": {
                    "RUN_VINS": "0",
                    "FORCE_EXPORT": "0",
                    "EXPORT_FEATURES": "0",
                    "RUN_EVALUATION": "0",
                },
                "replay_only": {
                    "VINS_MULTIPLE_THREAD": "0",
                },
                "formal_ros": dict(runtime_common.FROZEN_ROS_ENVIRONMENT),
                "ros_executables": dict(runtime_common.FROZEN_ROS_EXECUTABLES),
            },
            "b0_entrypoint": "scripts/run_isj_b0_native_vins_guarded_v1.sh",
            "feature_arm_entrypoints": [
                "scripts/run_aqualoc_archaeo_vins_eval.sh",
                "scripts/run_aqualoc_real_vins_eval.sh",
                "scripts/run_ntnu_vins_eval.sh",
                "scripts/run_afrl_cave_vins_eval.sh",
            ],
            "preparation_runners_run_vins_zero_only": True,
            "replay_only_runner": "scripts/run_p07_backend_replay_only_v1.sh",
            "replay_only_config_helper": (
                "scripts/prepare_p07_backend_replay_config_v1.py"
            ),
            "replay_only_runner_is_only_ros_replay_path": True,
            "evaluation_during_replay_forbidden": True,
            "ape_rpe_during_replay_forbidden": True,
            "data_identity_check_before_launch_required": True,
            "job_is_only_entrypoint": True,
            "adapter_direct_cli_forbidden": True,
            "b0_external_feature_bag_forbidden": True,
            "feature_arms_require_readonly_fd_override": True,
            "feature_arms_require_sealed_memfd_copy": True,
            "controller_job_and_transitive_modules_require_sealed_memfd": True,
            "unknown_scripts_import_workspace_fallback_forbidden": True,
            "b0_play_input_requires_sealed_memfd_copy": True,
            "attestation_and_input_audit_require_sealed_memfd_copy": True,
            "vins_and_camera_configs_require_sealed_memfd_consumption": True,
            "vins_binary_and_project_libraries_require_sealed_memfd": True,
            "vins_pid_exe_and_maps_identity_check_required": True,
            "aqualoc_afrl_dynamic_cache_conversion_forbidden": True,
            "formal_setup_path_source_forbidden": True,
            "minimal_ros_environment_is_job_constructed": True,
            "ros_cli_absolute_paths_required": True,
            "shell_export_wrapper_forbidden": True,
            "frontend_export_wrapper_forbidden": True,
            "input_sha256_before_and_after_required": True,
            "attestation_sha256_before_and_after_required": True,
            "delete_or_replace_input_forbidden": True,
            "target_no_clobber": True,
        },
        "data_identity_policy": {
            "data_eligibility_manifest": queue_builder.display_path(DATA_ELIGIBILITY),
            "dataset_checksum_manifest": queue_builder.display_path(DATASET_CHECKSUMS),
            "reference_audit": queue_builder.display_path(REFERENCE_AUDIT),
            "unique_family_sequence_row_required": True,
            "raw_input_identity_and_checksum_required": True,
            "reference_identity_and_checksum_required": True,
            "calibration_identity_and_checksum_required": True,
            "check_before_each_replay": True,
            "trajectory_values_read_by_identity_check": False,
        },
        "data_identity_snapshot": dict(data_identity_snapshot),
        "b0_play_inputs": dict(b0_play_inputs),
        g0_governance.EXECUTION_LOCK_BINDING_KEY: dict(
            g0_pre_replay_authority
        ),
        "infrastructure_replacement": {
            **dict(replacement_contract_binding),
            "replacement_lock_schema": replacement.LOCK_SCHEMA,
            "replacement_lock_status": replacement.LOCK_STATUS,
            "replacement_lock_directory": queue_builder.display_path(
                replacement.LOCK_DIRECTORY
            ),
            "allocation_index_schema": replacement.INDEX_SCHEMA,
            "allocation_index_path": queue_builder.display_path(
                replacement.INDEX_PATH
            ),
            "allowed_effective_row_overrides": list(
                replacement.ALLOWED_EFFECTIVE_ROW_OVERRIDES
            ),
            "replacement_job_flag": "--replacement-lock",
            "new_unique_planned_e00_required": True,
            "replacement_for_immediately_failed_run_id": True,
            "algorithmic_slot_preserved": True,
        },
        "capacity_gate": {
            "policy": queue_builder.CAPACITY_POLICY,
            "margin_numerator": MARGIN_NUMERATOR,
            "margin_denominator": MARGIN_DENOMINATOR,
            "reserve_bytes": RESERVE_BYTES,
            "minimum_governance_free_bytes": MINIMUM_GOVERNANCE_FREE_BYTES,
            "estimated_total_output_bytes": estimated_total,
            "required_output_free_bytes": required_free,
            "observed_output_free_bytes_at_freeze": output_free_bytes,
            "observed_governance_free_bytes_at_freeze": governance_free_bytes,
            "output_filesystem_path": "logs",
            "governance_filesystem_path": (
                "papers/ieee_sensors_journal_experiments/p07"
            ),
            "recompute_before_each_job": True,
            "insufficient_action": "WAITING",
        },
        "method_lock_hash": next(iter(queue_hashes)),
        "artifacts": [dict(record) for record in artifacts],
        "mutable_registry_prefix": dict(mutable_registry_prefix),
        "trajectory_outcome_read_at_freeze": False,
        "outcome_boundary": "SERIAL_BACKEND_REPLAY_AUTHORIZED_TRAJECTORY_UNREAD_AT_FREEZE",
    }
    payload["execution_lock_hash"] = execution_lock_hash(payload)
    return payload


def _frozen_content(contents: Mapping[str, bytes], path: Path) -> bytes:
    relative = queue_builder.display_path(path)
    try:
        return contents[relative]
    except KeyError as error:
        raise ExecutionLockError(f"required frozen snapshot is missing: {relative}") from error


def _load_and_validate_queue(
    *,
    contents: Mapping[str, bytes],
    records: Mapping[str, Mapping[str, object]],
    registry_content: bytes,
) -> tuple[list[dict[str, str]], dict[str, object]]:
    validation = _json_from_bytes(
        _frozen_content(contents, QUEUE_VALIDATION),
        QUEUE_VALIDATION,
        label="backend queue validation",
    )
    if (
        validation.get("schema_version") != queue_validator.REPORT_SCHEMA
        or validation.get("status") != "PASS"
        or validation.get("issues") != []
        or validation.get("live_rebuild_requested") is not True
        or not all(validation.get("deterministic_live_rebuild", {}).values())
        or validation.get("held_out_trajectory_outcome_read") is not False
    ):
        raise ExecutionLockError("backend queue validation is not a full live-rebuild PASS")
    queue_content = _frozen_content(contents, queue_builder.BACKEND_QUEUE)
    allocation_content = _frozen_content(contents, queue_builder.BACKEND_ALLOCATION)
    queue_lock = _json_from_bytes(
        _frozen_content(contents, queue_builder.BACKEND_QUEUE_LOCK),
        queue_builder.BACKEND_QUEUE_LOCK,
        label="backend queue lock",
    )
    _queue_fields, rows = queue_validator.parse_csv(queue_content)
    issues = queue_validator.validate_artifacts(
        queue_content=queue_content,
        allocation_content=allocation_content,
        lock_payload=queue_lock,
        arm_order_rows=queue_validator.parse_csv(
            _frozen_content(contents, queue_builder.ARM_ORDER)
        )[1],
    )
    if issues:
        raise ExecutionLockError(f"backend queue drift after validation: {issues}")
    if validation.get("backend_queue_lock_hash") != queue_lock.get(
        "backend_queue_lock_hash"
    ):
        raise ExecutionLockError("validation/queue-lock identity mismatch")
    registration_payload = _json_from_bytes(
        _frozen_content(contents, registration.REPORT),
        registration.REPORT,
        label="backend registration report",
    )
    if (
        registration_payload.get("schema_version") != registration.SCHEMA
        or registration_payload.get("status") != "PASS"
        or registration_payload.get("registration_report_hash")
        != registration._document_hash(
            registration_payload, "registration_report_hash"
        )
        or registration_payload.get("backend_queue_lock_hash")
        != queue_lock.get("backend_queue_lock_hash")
        or registration_payload.get("allocation_sha256")
        != hashlib.sha256(allocation_content).hexdigest()
        or registration_payload.get("held_out_trajectory_outcome_read") is not False
        or registration_payload.get("validation", {}).get("pass") is not True
        or int(
            registration_payload.get("validation", {}).get(
                "unique_untouched_planned_e00", -1
            )
        )
        != len(rows)
    ):
        raise ExecutionLockError("backend allocation registration is not an exact PASS")
    _allocation_fields, allocation_rows = queue_validator.parse_csv(allocation_content)
    registry_fields, registry_rows = queue_validator.parse_csv(registry_content)
    split_roles = {
        row["window_id"]: row["corrected_split_role"]
        for row in queue_validator.parse_csv(
            _frozen_content(
                contents, queue_builder.P07 / "split_role_audit_v1.csv"
            )
        )[1]
    }
    intended = registration.build_registry_rows(
        rows,
        allocation_rows,
        registry_fields=registry_fields,
        split_roles=split_roles,
    )
    current_registration = registration.validate_registered(intended, registry_rows)
    if current_registration.get("pass") is not True:
        raise ExecutionLockError(
            f"backend registry is no longer untouched PLANNED: {current_registration}"
        )
    try:
        registration_intent = _json_from_bytes(
            _frozen_content(contents, registration.INTENT),
            registration.INTENT,
            label="backend registration intent",
        )
    except ExecutionLockError as error:
        raise ExecutionLockError("backend registration intent is invalid") from error
    registration.validate_registration_intent(
        registration_intent,
        intended=intended,
        queue_lock=queue_lock,
        expected_artifact_records={
            "backend_queue": records[
                queue_builder.display_path(queue_builder.BACKEND_QUEUE)
            ],
            "backend_allocation": records[
                queue_builder.display_path(queue_builder.BACKEND_ALLOCATION)
            ],
            "backend_queue_lock": records[
                queue_builder.display_path(queue_builder.BACKEND_QUEUE_LOCK)
            ],
            "backend_queue_validation": records[
                queue_builder.display_path(queue_builder.BACKEND_QUEUE_VALIDATION)
            ],
            "split_role_audit": records[
                queue_builder.display_path(
                    queue_builder.P07 / "split_role_audit_v1.csv"
                )
            ],
        },
    )
    intent_binding = registration_payload.get("registration_intent")
    expected_intent_record = records[queue_builder.display_path(registration.INTENT)]
    if (
        not isinstance(intent_binding, dict)
        or any(
            intent_binding.get(key) != expected_intent_record.get(key)
            for key in ("path", "sha256", "size_bytes")
        )
        or intent_binding.get("registration_intent_hash")
        != registration_intent.get("registration_intent_hash")
        or int(
            registration_payload.get(
                "registry_rows_appended_this_invocation", -1
            )
        )
        < 0
        or int(
            registration_payload.get("registry_rows_reconciled_existing", -1)
        )
        < 0
        or int(
            registration_payload["registry_rows_appended_this_invocation"]
        )
        + int(registration_payload["registry_rows_reconciled_existing"])
        != len(intended)
    ):
        raise ExecutionLockError("backend registration intent/reconcile binding drift")
    return rows, queue_lock


def _target_collisions(queue_rows: Sequence[Mapping[str, str]]) -> list[str]:
    collisions: list[str] = []
    for row in queue_rows:
        for field in ("expected_run_dir", "expected_attempt_dir"):
            relative = str(row[field])
            pure = PurePosixPath(relative)
            if pure.is_absolute() or ".." in pure.parts:
                collisions.append(f"unsafe:{field}:{relative}")
                continue
            try:
                state = queue_builder.rooted_io.path_state_bound_input_rooted(
                    queue_builder.ROOT,
                    queue_builder.ROOT.joinpath(*pure.parts),
                    label=f"backend execution target {field}",
                )
            except queue_builder.rooted_io.gov.G0GovernanceError:
                collisions.append(f"unsafe:{field}:{relative}")
                continue
            if state != "ABSENT":
                collisions.append(f"exists:{field}:{relative}")
    return collisions


def required_artifact_paths() -> tuple[Path, ...]:
    paths = (
        queue_builder.BACKEND_QUEUE,
        queue_builder.BACKEND_ALLOCATION,
        queue_builder.BACKEND_QUEUE_LOCK,
        queue_builder.ARM_ORDER,
        queue_builder.P07 / "split_role_audit_v1.csv",
        QUEUE_VALIDATION,
        registration.INTENT,
        registration.REPORT,
        queue_builder.METHOD_LOCK,
        queue_builder.ENVIRONMENT,
        queue_builder.EVALUATOR,
        queue_builder.FAILURE_TAXONOMY,
        queue_builder.EVALUATOR_CORRECTION_LOCK,
        queue_builder.EVALUATOR_CORRECTION_BUILDER,
        queue_builder.EVALUATOR_CORRECTION_TEST,
        *queue_builder.EVALUATOR_SOURCES,
        queue_builder.ROOT / "scripts/build_p07_backend_replay_queue_v1.py",
        queue_builder.ROOT / "scripts/validate_p07_backend_replay_queue_v1.py",
        queue_builder.ROOT / "scripts/build_p07_backend_execution_lock_v1.py",
        queue_builder.ROOT / "scripts/register_p07_backend_allocations_v1.py",
        queue_builder.ROOT / "scripts/tests/test_p07_backend_registration_v1.py",
        ADAPTER,
        EXECUTOR,
        AUDITOR,
        INPUT_CHECKER,
        COMMON,
        SERIAL_CONTROLLER,
        RUNTIME_IDENTITY_TEST,
        SAFETY_TEST,
        *DIRECT_RUNNERS,
        B0_WRAPPER,
        REPLAY_ONLY_RUNNER,
        CONFIG_HELPER,
        BACKEND_CONTRACT,
        M_CONTRACT,
        NATIVEQ_CONTRACT_CHECKER,
        XFEAT_CONTRACT_CHECKER,
        DATA_ELIGIBILITY,
        DATASET_CHECKSUMS,
        REFERENCE_AUDIT,
        FORMALIZATION_ADOPTION,
        queue_builder.ROOT / review_evidence.OUTPUT_RELATIVE,
        B0_ADOPTION_PRELOCK,
        B0_ADOPTION_ACTION_INTENT,
        B0_ADOPTION_CLOSEOUT,
        B0_ADOPTION_BRIDGE_BUILDER,
        B0_ADOPTION_BRIDGE_RUNNER,
        B0_ADOPTION_BRIDGE_TEST,
        replacement.OUTPUT,
        queue_builder.ROOT / "scripts/build_p07_backend_replacement_contract_v1.py",
        queue_builder.ROOT / "scripts/allocate_p07_backend_replacement_v1.py",
        queue_builder.ROOT / "scripts/tests/test_p07_backend_replacement_v1.py",
        queue_builder.ROOT / "scripts/tests/test_p07_backend_execution_adoption_v1.py",
        queue_builder.ROOT / review_evidence.BUILDER_RELATIVE,
        queue_builder.ROOT / review_evidence.TEST_RELATIVE,
        queue_builder.ROOT / review_evidence.LEAF_TEST_RELATIVE,
        queue_builder.ROOT / "scripts/check_b0_vins_origin_identity_v1.py",
        B0_PLAN,
        B0_INTENT,
        B0_RECEIPT,
        B0_PLAY_INPUTS,
        B0_PLAN_BUILDER,
        B0_MATERIALIZER,
        B0_MATERIALIZATION_TEST,
        G0_LOCK,
        G0_GOVERNANCE,
        queue_builder.ROOT / "scripts/tests/test_p07_g0_governance_v1.py",
        *(
            queue_builder.ROOT / relative
            for relative in runtime_common.RUNTIME_IMPLEMENTATION_BINDING_PATHS.values()
        ),
    )
    # Several dedicated records are also runtime roles.  Freeze them once and
    # reject only genuinely duplicate relative paths during live collection.
    return tuple(dict.fromkeys(paths))


def build_live_lock(*, frozen_at: str) -> dict[str, object]:
    if queue_builder.formal_io.destination_exists(
        queue_builder.ROOT, queue_builder.display_path(OUTPUT)
    ):
        raise FileExistsError(OUTPUT)
    paths = required_artifact_paths()
    contents: dict[str, bytes] = {}
    records: list[dict[str, object]] = []
    try:
        for path in paths:
            content, record = _read_direct_snapshot(
                queue_builder.ROOT,
                path,
                label="required execution artifact",
            )
            relative = str(record["path"])
            if relative in contents:
                raise ExecutionLockError(
                    f"duplicate required execution artifact: {relative}"
                )
            contents[relative] = content
            records.append(record)
        registry_content, registry_record = _read_direct_snapshot(
            queue_builder.ROOT,
            registration.RUN_REGISTRY,
            label="canonical run-registry prefix",
        )
    except (OSError, ValueError, queue_builder.formal_io.FormalIOError) as error:
        raise ExecutionLockError(
            "required execution artifact is missing or unsafe"
        ) from error
    by_path = {str(record["path"]): record for record in records}
    external_runtime_bindings = {
        role: _external_record(path, label=f"external runtime {role}")
        for role, path in sorted(
            runtime_common.EXTERNAL_RUNTIME_BINDING_PATHS.items()
        )
    }
    queue_rows, queue_lock = _load_and_validate_queue(
        contents=contents,
        records=by_path,
        registry_content=registry_content,
    )
    collisions = _target_collisions(queue_rows)
    if collisions:
        raise ExecutionLockError(f"backend targets are not empty: {collisions[:5]}")
    output_free = shutil.disk_usage(queue_builder.ROOT / "logs").free
    governance_free = shutil.disk_usage(queue_builder.P07).free
    queue_lock_record = dict(by_path[queue_builder.display_path(queue_builder.BACKEND_QUEUE_LOCK)])
    queue_lock_record["backend_queue_lock_hash"] = queue_lock[
        "backend_queue_lock_hash"
    ]
    replacement_payload = _json_from_bytes(
        _frozen_content(contents, replacement.OUTPUT),
        replacement.OUTPUT,
        label="backend replacement contract",
    )
    try:
        replacement.validate_contract_payload(
            replacement_payload, root=queue_builder.ROOT, verify_artifacts=True
        )
    except replacement.ReplacementContractError as error:
        raise ExecutionLockError(f"replacement contract is not READY: {error}") from error
    replacement_binding = {
        "schema_version": replacement_payload["schema_version"],
        "status": replacement_payload["status"],
        "contract": by_path[queue_builder.display_path(replacement.OUTPUT)],
        "replacement_contract_hash": replacement_payload[
            replacement.SELF_HASH_FIELD
        ],
        "formalization_adoption": replacement_payload[
            "formalization_adoption"
        ],
        "formalization_review_evidence": replacement_payload[
            "formalization_review_evidence"
        ],
    }
    try:
        adoption_binding = adoption.adoption_authority_binding(
            root=queue_builder.ROOT
        )
        evidence_binding = review_evidence.review_evidence_authority_binding(
            root=queue_builder.ROOT
        )
        b0_prelock_payload, b0_prelock_record = b0_adoption_bridge.load_prelock(
            root=queue_builder.ROOT
        )
        b0_action_payload, b0_action_record = b0_adoption_bridge.load_action_intent(
            root=queue_builder.ROOT
        )
        b0_closeout_payload, b0_closeout_record = b0_adoption_bridge.load_closeout(
            root=queue_builder.ROOT
        )
    except (
        adoption.AdoptionError,
        review_evidence.ReviewEvidenceError,
        b0_adoption_bridge.B0AdoptionBridgeError,
    ) as error:
        raise ExecutionLockError(
            f"formalization-adoption/B0 bridge is not READY: {error}"
        ) from error
    if (
        b0_prelock_payload.get("formalization_adoption") != adoption_binding
        or b0_action_payload.get("formalization_adoption") != adoption_binding
        or b0_closeout_payload.get("formalization_adoption") != adoption_binding
        or b0_action_payload.get("pre_materialization_lock")
        != {
            **b0_prelock_record,
            b0_adoption_bridge.PRELOCK_HASH: b0_prelock_payload[
                b0_adoption_bridge.PRELOCK_HASH
            ],
        }
        or b0_closeout_payload.get("pre_materialization_lock")
        != {
            **b0_prelock_record,
            b0_adoption_bridge.PRELOCK_HASH: b0_prelock_payload[
                b0_adoption_bridge.PRELOCK_HASH
            ],
        }
    ):
        raise ExecutionLockError("B0 bridge/adoption transitive binding drift")
    if (
        b0_prelock_payload.get("formalization_review_evidence") != evidence_binding
        or b0_action_payload.get("formalization_review_evidence") != evidence_binding
        or b0_closeout_payload.get("formalization_review_evidence") != evidence_binding
        or b0_closeout_payload.get("materialization_action_intent")
        != {
            **b0_action_record,
            b0_adoption_bridge.ACTION_INTENT_HASH: b0_action_payload[
                b0_adoption_bridge.ACTION_INTENT_HASH
            ],
        }
    ):
        raise ExecutionLockError("B0 bridge review-evidence binding drift")
    for expected_path, observed_record in (
        (FORMALIZATION_ADOPTION, adoption_binding),
        (B0_ADOPTION_PRELOCK, b0_prelock_record),
        (B0_ADOPTION_ACTION_INTENT, b0_action_record),
        (B0_ADOPTION_CLOSEOUT, b0_closeout_record),
    ):
        frozen_record = by_path.get(queue_builder.display_path(expected_path))
        if not _same_portable_file_record(frozen_record, observed_record):
            raise ExecutionLockError(
                f"execution artifacts omit exact adoption bridge: {expected_path}"
            )
    data_identity_snapshot = collect_data_identity_snapshot(
        queue_rows,
        frozen_manifest_snapshots={
            path: (
                _frozen_content(contents, path),
                by_path[queue_builder.display_path(path)],
            )
            for path in (DATA_ELIGIBILITY, DATASET_CHECKSUMS, REFERENCE_AUDIT)
        },
    )
    b0_plan_payload = _json_from_bytes(
        _frozen_content(contents, B0_PLAN),
        B0_PLAN,
        label="frozen B0 materialization lock",
    )
    b0_intent_payload = _json_from_bytes(
        _frozen_content(contents, B0_INTENT),
        B0_INTENT,
        label="frozen B0 materialization intent",
    )
    b0_receipt_payload = _json_from_bytes(
        _frozen_content(contents, B0_RECEIPT),
        B0_RECEIPT,
        label="frozen B0 materialization receipt",
    )
    b0_play_inputs = _json_from_bytes(
        _frozen_content(contents, B0_PLAY_INPUTS),
        B0_PLAY_INPUTS,
        label="frozen B0 play-input contract",
    )
    b0_plan.validate_plan_payload(
        b0_plan_payload,
        require_live_artifacts=True,
        root=queue_builder.ROOT,
    )
    b0_materializer.validate_intent_payload(b0_intent_payload, b0_plan_payload)
    b0_materializer.validate_receipt_payload(
        b0_receipt_payload, b0_plan_payload, b0_intent_payload
    )
    try:
        runtime_common.validate_b0_play_inputs_shape(b0_play_inputs, queue_rows)
    except runtime_common.BackendReplayViolation as error:
        raise ExecutionLockError(f"frozen B0 play-input contract drift: {error}") from error
    plan_record = by_path[queue_builder.display_path(B0_PLAN)]
    intent_record = by_path[queue_builder.display_path(B0_INTENT)]
    receipt_record = by_path[queue_builder.display_path(B0_RECEIPT)]
    receipt_intent_record = b0_receipt_payload.get("materialization_intent")
    if (
        not _same_portable_file_record(
            b0_receipt_payload.get("materialization_lock"), plan_record
        )
        or not _same_portable_file_record(receipt_intent_record, intent_record)
        or b0_receipt_payload.get("materialization_lock_hash")
        != b0_plan_payload.get(b0_plan.SELF_HASH)
        or b0_play_inputs.get("materialization_lock_hash")
        != b0_plan_payload.get(b0_plan.SELF_HASH)
        or b0_play_inputs.get("materialization_receipt") != receipt_record
        or b0_play_inputs.get("materialization_receipt_hash")
        != b0_receipt_payload.get(b0_materializer.RECEIPT_HASH)
        or b0_play_inputs.get("materialization_intent_hash")
        != b0_intent_payload.get(b0_materializer.INTENT_HASH)
    ):
        raise ExecutionLockError("B0 plan/receipt/play-input transitive binding drift")
    try:
        g0_authority = g0_governance.build_execution_authority_binding(
            G0_LOCK, root=queue_builder.ROOT
        )
    except g0_governance.G0GovernanceError as error:
        raise ExecutionLockError(f"pre-replay G0 lock is not READY: {error}") from error
    if not _same_portable_file_record(
        g0_authority.get("evaluation_lock"),
        by_path[queue_builder.display_path(G0_LOCK)],
    ):
        raise ExecutionLockError("G0 authority/evaluation-lock snapshot drift")
    for path in paths:
        observed = _record_dict(path)
        expected = by_path[queue_builder.display_path(path)]
        if not _same_portable_file_record(observed, expected):
            raise ExecutionLockError(
                f"required execution artifact changed during freeze: {expected['path']}"
            )
    for role, path in sorted(runtime_common.EXTERNAL_RUNTIME_BINDING_PATHS.items()):
        if _external_record(path, label=f"external runtime {role}") != (
            external_runtime_bindings[role]
        ):
            raise ExecutionLockError(
                f"external runtime artifact changed during freeze: {role}"
            )
    return build_lock_payload(
        frozen_at=frozen_at,
        queue_rows=queue_rows,
        queue_record=by_path[queue_builder.display_path(queue_builder.BACKEND_QUEUE)],
        allocation_record=by_path[
            queue_builder.display_path(queue_builder.BACKEND_ALLOCATION)
        ],
        queue_lock_record=queue_lock_record,
        validation_record=by_path[queue_builder.display_path(QUEUE_VALIDATION)],
        registration_record=by_path[queue_builder.display_path(registration.REPORT)],
        allowed_entrypoint_record=by_path[queue_builder.display_path(EXECUTOR)],
        executor_record=by_path[queue_builder.display_path(EXECUTOR)],
        adapter_record=by_path[queue_builder.display_path(ADAPTER)],
        auditor_record=by_path[queue_builder.display_path(AUDITOR)],
        artifacts=records,
        external_runtime_bindings=external_runtime_bindings,
        formalization_adoption=adoption_binding,
        formalization_review_evidence=evidence_binding,
        b0_adoption_prelock={
            **b0_prelock_record,
            b0_adoption_bridge.PRELOCK_HASH: b0_prelock_payload[
                b0_adoption_bridge.PRELOCK_HASH
            ],
        },
        b0_adoption_action_intent={
            **b0_action_record,
            b0_adoption_bridge.ACTION_INTENT_HASH: b0_action_payload[
                b0_adoption_bridge.ACTION_INTENT_HASH
            ],
        },
        b0_adoption_closeout={
            **b0_closeout_record,
            b0_adoption_bridge.CLOSEOUT_HASH: b0_closeout_payload[
                b0_adoption_bridge.CLOSEOUT_HASH
            ],
        },
        replacement_contract_binding=replacement_binding,
        data_identity_snapshot=data_identity_snapshot,
        b0_play_inputs=b0_play_inputs,
        g0_pre_replay_authority=g0_authority,
        mutable_registry_prefix={
            "path": registry_record["path"],
            "sha256": registry_record["sha256"],
            "size_bytes": registry_record["size_bytes"],
        },
        output_free_bytes=output_free,
        governance_free_bytes=governance_free,
    )


def _revalidate_execution_publication_inputs(payload: Mapping[str, object]) -> None:
    if (
        payload.get("schema_version") != SCHEMA
        or payload.get("status") != STATUS
        or payload.get("execution_lock_hash") != execution_lock_hash(payload)
    ):
        raise ExecutionLockError("execution lock payload drift before publication")
    artifacts = payload.get("artifacts")
    if not isinstance(artifacts, list) or not artifacts:
        raise ExecutionLockError("execution lock lacks publication artifact bindings")
    for record in artifacts:
        if not isinstance(record, dict):
            raise ExecutionLockError("execution lock publication artifact is malformed")
        try:
            relative = str(record["path"])
            pure = PurePosixPath(relative)
            if pure.is_absolute() or ".." in pure.parts or not pure.parts:
                raise ValueError(relative)
            observed = _record_dict(queue_builder.ROOT.joinpath(*pure.parts))
        except (KeyError, OSError, ValueError) as error:
            raise ExecutionLockError(
                "execution lock publication artifact is missing or unsafe"
            ) from error
        if not _same_portable_file_record(observed, record):
            raise ExecutionLockError(
                f"execution lock publication artifact drift: {relative}"
            )
    prefix = payload.get("mutable_registry_prefix")
    if not isinstance(prefix, dict):
        raise ExecutionLockError("execution lock lacks mutable registry prefix")
    registry_content = _read_direct_bytes(
        queue_builder.ROOT,
        registration.RUN_REGISTRY,
        label="execution-lock registry publication prefix",
    )
    try:
        prefix_size = int(prefix["size_bytes"])
        prefix_hash = str(prefix["sha256"])
    except (KeyError, TypeError, ValueError) as error:
        raise ExecutionLockError("execution lock registry prefix is malformed") from error
    if (
        prefix.get("path") != queue_builder.display_path(registration.RUN_REGISTRY)
        or prefix_size < 0
        or len(registry_content) < prefix_size
        or hashlib.sha256(registry_content[:prefix_size]).hexdigest() != prefix_hash
    ):
        raise ExecutionLockError("execution lock registry prefix drift before publication")


def write_no_clobber(path: Path, payload: Mapping[str, object]) -> None:
    try:
        relative = path.absolute().relative_to(queue_builder.ROOT.absolute()).as_posix()
    except ValueError as error:
        raise ExecutionLockError("formal execution lock path escapes workspace") from error
    content = queue_builder.formal_io.json_bytes(payload)
    with queue_builder.formal_io.global_formal_lock():
        with queue_builder.formal_io._parent_dirfd(
            queue_builder.ROOT, relative
        ) as (parent_fd, name):
            partial_prefix = f".{name}.partial.{os.getpid()}."
            preexisting_partials = {
                entry
                for entry in os.listdir(parent_fd)
                if entry.startswith(partial_prefix)
            }
            staged_fd = -1
            staged_identity: tuple[int, int] | None = None

            def guarded_pre_link_validation() -> None:
                nonlocal staged_fd, staged_identity
                candidates = [
                    entry
                    for entry in os.listdir(parent_fd)
                    if entry.startswith(partial_prefix)
                    and entry not in preexisting_partials
                ]
                if len(candidates) != 1 or staged_fd >= 0:
                    raise ExecutionLockError(
                        "execution lock staged publication identity is ambiguous"
                    )
                staged_fd = os.open(
                    candidates[0],
                    os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW,
                    dir_fd=parent_fd,
                )
                staged = os.fstat(staged_fd)
                if (
                    not stat.S_ISREG(staged.st_mode)
                    or staged.st_nlink != 1
                    or staged.st_size != len(content)
                    or queue_builder.formal_io._pread_all(
                        staged_fd, staged.st_size
                    )
                    != content
                ):
                    raise ExecutionLockError(
                        "execution lock staged publication identity differs"
                    )
                staged_identity = (staged.st_dev, staged.st_ino)
                _revalidate_execution_publication_inputs(payload)

            def guarded_post_link_validation() -> None:
                linked = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
                if staged_identity is None or (
                    linked.st_dev,
                    linked.st_ino,
                ) != staged_identity:
                    raise ExecutionLockError(
                        "execution lock destination is not the staged inode"
                    )
                _revalidate_execution_publication_inputs(payload)

            try:
                queue_builder.formal_io.publish_bytes_no_clobber(
                    queue_builder.ROOT,
                    relative,
                    content,
                    pre_link_guard=guarded_pre_link_validation,
                    post_link_guard=guarded_post_link_validation,
                )
            except BaseException:
                # The frozen generic publisher intentionally never unlinks a
                # destination.  This execution-lock wrapper can safely roll
                # back only the inode it observed immediately after its own
                # link.  A replacement/race winner is never removed.
                if staged_identity is not None:
                    try:
                        current = os.stat(
                            name, dir_fd=parent_fd, follow_symlinks=False
                        )
                    except FileNotFoundError:
                        current = None
                    if current is not None and (
                        current.st_dev,
                        current.st_ino,
                    ) == staged_identity:
                        os.unlink(name, dir_fd=parent_fd)
                        os.fsync(parent_fd)
                raise
            finally:
                if staged_fd >= 0:
                    os.close(staged_fd)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--preflight-only", action="store_true")
    parser.add_argument("--write", action="store_true")
    parser.add_argument("--frozen-at", help="ISO-8601 lock time")
    args = parser.parse_args()
    if not args.frozen_at:
        parser.error("--frozen-at is required")
    payload = build_live_lock(frozen_at=args.frozen_at)
    if args.preflight_only:
        print(
            json.dumps(
                {
                    "status": "READY",
                    "queue_items": payload["queue_items"],
                    "capacity_gate": payload["capacity_gate"],
                    "trajectory_outcome_read_at_freeze": False,
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 0
    if not args.write:
        parser.error("refusing formal execution-lock generation without --write")
    write_no_clobber(OUTPUT, payload)
    print(
        "P07_BACKEND_EXECUTION_LOCK_FROZEN "
        f"jobs={payload['queue_items']} hash={payload['execution_lock_hash']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
