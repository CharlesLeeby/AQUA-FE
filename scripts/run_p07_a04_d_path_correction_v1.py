#!/usr/bin/env python3
"""Run the additive, fail-closed A04 D-v4 path correction.

Only the frozen top-level ``datasets`` symlink may cross the workspace
boundary, and only for the archive and GT files already hash-bound by the q55
recovery lock.  The legacy D-v4 resolver is patched only inside a context
manager and is restored unconditionally.  D semantics and frontend commands
remain unchanged.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import os
import stat
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator, Mapping

try:
    from scripts import audit_p07_frontend_export_v3 as audit_v3
    from scripts import build_p07_a04_d_path_correction_lock_v1 as contract
    from scripts import build_p07_d_resolution_lock_v4 as legacy_builder
    from scripts import build_p07_preoutcome_governance_v1 as governance
    from scripts import resolve_p07_d_applicability_v2 as d_v2
    from scripts import resolve_p07_d_applicability_v4 as d_v4
    from scripts import run_p07_q55_a04_layout_replacement_v1 as recovery
except ModuleNotFoundError:  # Direct ``python3 scripts/...`` execution.
    import audit_p07_frontend_export_v3 as audit_v3  # type: ignore
    import build_p07_a04_d_path_correction_lock_v1 as contract  # type: ignore
    import build_p07_d_resolution_lock_v4 as legacy_builder  # type: ignore
    import build_p07_preoutcome_governance_v1 as governance  # type: ignore
    import resolve_p07_d_applicability_v2 as d_v2  # type: ignore
    import resolve_p07_d_applicability_v4 as d_v4  # type: ignore
    import run_p07_q55_a04_layout_replacement_v1 as recovery  # type: ignore


LOCK_PATH = contract.OUTPUT
WINDOW_ID = contract.WINDOW_ID
ENHANCED_D_LOCK = contract.D_V4_LOCK
BUILDER_PATH = contract.ROOT / "scripts/build_p07_a04_d_path_correction_lock_v1.py"
WRAPPER_PATH = Path(__file__).resolve()
TEST_PATH = contract.TEST_FILE


class PathCorrectionError(RuntimeError):
    """Raised on correction-lock, filesystem, ordering, or evidence drift."""


def sha256(path: Path) -> str:
    return contract.sha256(path)


def _json_object(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise PathCorrectionError(f"cannot read {label}: {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise PathCorrectionError(f"{label} is not a JSON object: {path}")
    return value


def _relative_text(value: object, label: str) -> tuple[str, Path]:
    if not isinstance(value, str) or not value or "\\" in value:
        raise d_v4.ResolutionViolation(f"{label} path is missing or non-POSIX")
    relative = Path(value)
    if relative.is_absolute():
        raise d_v4.ResolutionViolation(f"{label} path must be workspace-relative")
    if ".." in relative.parts:
        raise d_v4.ResolutionViolation(f"{label} path contains forbidden '..'")
    if not relative.parts or relative.parts[0] in {"", "."}:
        raise d_v4.ResolutionViolation(f"{label} path is not canonical relative")
    return value, relative


def _strict_internal_file(root: Path, relative: Path, label: str) -> Path:
    cursor = root
    for component in relative.parts:
        cursor = cursor / component
        try:
            item_stat = os.lstat(cursor)
        except OSError as exc:
            raise d_v4.ResolutionViolation(f"missing {label}: {cursor}") from exc
        if stat.S_ISLNK(item_stat.st_mode):
            raise d_v4.ResolutionViolation(
                f"{label} traverses a forbidden workspace symlink: {cursor}"
            )
    try:
        cursor.resolve(strict=True).relative_to(root.resolve(strict=True))
    except (OSError, ValueError) as exc:
        raise d_v4.ResolutionViolation(f"{label} path escapes the workspace") from exc
    try:
        leaf_stat = os.lstat(cursor)
    except OSError as exc:
        raise d_v4.ResolutionViolation(f"missing {label}: {cursor}") from exc
    if stat.S_ISLNK(leaf_stat.st_mode) or not stat.S_ISREG(leaf_stat.st_mode):
        raise d_v4.ResolutionViolation(f"{label} is not a non-symlink regular file")
    return cursor


def _validate_symlink_identity(payload: Mapping[str, Any], root: Path) -> dict[str, Any]:
    frozen = payload.get("datasets_symlink_identity")
    if not isinstance(frozen, dict):
        raise PathCorrectionError("correction lock lacks datasets symlink identity")
    path = root / "datasets"
    try:
        link_stat = os.lstat(path)
        link_text = os.readlink(path)
        resolved = path.resolve(strict=True)
        target_stat = os.lstat(resolved)
        observed = {
            "workspace_entry": "datasets",
            "lstat": contract._stat_record(link_stat),
            "readlink": link_text,
            "resolved_target": str(resolved),
            "resolved_target_lstat": contract._stat_record(target_stat),
        }
    except Exception as exc:
        raise PathCorrectionError(f"cannot validate frozen datasets symlink: {exc}") from exc
    if not stat.S_ISLNK(link_stat.st_mode) or not stat.S_ISDIR(target_stat.st_mode):
        raise PathCorrectionError("datasets entry/target type drift")
    if observed != frozen:
        raise PathCorrectionError(
            f"datasets symlink lstat/readlink/target identity drift: {observed}"
        )
    return frozen


def corrected_workspace_path(
    payload: Mapping[str, Any], value: object, label: str, *, root: Path | None = None
) -> Path:
    """Resolve one old-v4 artifact under the exact additive path policy."""

    root = contract.ROOT if root is None else root
    text, relative = _relative_text(value, label)
    if relative.parts[0] != "datasets":
        return _strict_internal_file(root, relative, label)

    allowlist = payload.get("datasets_external_file_allowlist")
    if not isinstance(allowlist, list):
        raise d_v4.ResolutionViolation("datasets external allowlist is missing")
    allowed: dict[str, dict[str, Any]] = {}
    for record in allowlist:
        if not isinstance(record, dict) or not isinstance(record.get("path"), str):
            raise d_v4.ResolutionViolation("invalid datasets external allowlist")
        allowed[str(record["path"])] = record
    if len(allowed) != 2 or text not in allowed:
        raise d_v4.ResolutionViolation(
            f"{label} datasets path is outside the exact archive/GT allowlist"
        )
    try:
        frozen_link = _validate_symlink_identity(payload, root)
    except PathCorrectionError as exc:
        raise d_v4.ResolutionViolation(str(exc)) from exc
    target = Path(str(frozen_link["resolved_target"]))
    candidate = root / relative
    cursor = root / "datasets"
    for component in relative.parts[1:]:
        cursor = cursor / component
        try:
            item_stat = os.lstat(cursor)
        except OSError as exc:
            raise d_v4.ResolutionViolation(f"missing {label}: {cursor}") from exc
        if stat.S_ISLNK(item_stat.st_mode):
            raise d_v4.ResolutionViolation(
                f"{label} nested or leaf datasets symlink is forbidden: {cursor}"
            )
    try:
        resolved = candidate.resolve(strict=True)
        resolved.relative_to(target)
        leaf_stat = os.lstat(candidate)
    except (OSError, ValueError) as exc:
        raise d_v4.ResolutionViolation(
            f"{label} path escapes the frozen datasets target"
        ) from exc
    record = allowed[text]
    if (
        stat.S_ISLNK(leaf_stat.st_mode)
        or not stat.S_ISREG(leaf_stat.st_mode)
        or candidate.stat().st_size != int(record.get("size_bytes", -1))
    ):
        raise d_v4.ResolutionViolation(f"{label} allowlisted file identity/size drift")
    # The frozen old-v4 caller immediately checks this file's SHA against the
    # recovery-lock artifact record.  Keeping hashing there avoids reading the
    # 3.28-GiB archive twice while retaining the exact old hash check.
    return candidate


@contextmanager
def patched_legacy_workspace_path(payload: Mapping[str, Any]) -> Iterator[None]:
    """Temporarily patch only the old-v4 path helper and always restore it."""

    original = d_v4._workspace_path

    def adapter(value: object, label: str) -> Path:
        return corrected_workspace_path(payload, value, label)

    d_v4._workspace_path = adapter
    try:
        yield
    finally:
        d_v4._workspace_path = original


def _validate_artifact_record(record: Mapping[str, Any], root: Path) -> None:
    text, relative = _relative_text(record.get("path"), "correction artifact")
    if relative.parts[0] == "datasets":
        raise PathCorrectionError(f"correction artifact cannot be external data: {text}")
    try:
        path = _strict_internal_file(root, relative, "correction artifact")
    except d_v4.ResolutionViolation as exc:
        raise PathCorrectionError(str(exc)) from exc
    if (
        path.stat().st_size != int(record.get("size_bytes", -1))
        or sha256(path) != record.get("sha256")
    ):
        raise PathCorrectionError(f"correction artifact drift: {path}")


def _validate_prefix(snapshot: Mapping[str, Any], root: Path) -> None:
    _, relative = _relative_text(snapshot.get("path"), "correction stream")
    try:
        path = _strict_internal_file(root, relative, "correction stream")
        content = path.read_bytes()
        size = int(snapshot.get("size_bytes", -1))
    except (d_v4.ResolutionViolation, OSError, TypeError, ValueError) as exc:
        raise PathCorrectionError(f"cannot validate correction stream: {exc}") from exc
    if (
        size < 0
        or len(content) < size
        or hashlib.sha256(content[:size]).hexdigest() != snapshot.get("sha256")
    ):
        raise PathCorrectionError(f"correction stream prefix drift: {path}")


def _csv_prefix_rows(snapshot: Mapping[str, Any], root: Path) -> list[dict[str, str]]:
    path = root / str(snapshot["path"])
    content = path.read_bytes()[: int(snapshot["size_bytes"])]
    reader = csv.DictReader(io.StringIO(content.decode("utf-8"), newline=""))
    rows = list(reader)
    if not reader.fieldnames or any(None in row for row in rows):
        raise PathCorrectionError(f"invalid CSV prefix: {path}")
    return rows


def validate_lock_payload(
    payload: dict[str, Any], *, root: Path | None = None
) -> dict[str, Any]:
    root = contract.ROOT if root is None else root
    if (
        payload.get("schema_version") != contract.SCHEMA
        or payload.get("status") != contract.STATUS
        or payload.get("window_id") != WINDOW_ID
        or payload.get(contract.SELF_HASH_FIELD) != contract.document_hash(payload)
        or payload.get("expected_d_decision")
        != "NOT_APPLICABLE_REQUIRE_BYTE_IDENTICAL_B1"
        or payload.get("action_order") != contract.ACTION_ORDER
        or payload.get("outcome_boundary") != contract.OUTCOME_BOUNDARY
        or payload.get("trajectory_outcome_read") is not False
        or payload.get("vins_execution_allowed") is not False
        or payload.get("resume_queue_indices") != [58, 59, 60]
    ):
        raise PathCorrectionError("correction lock schema/hash/identity/boundary mismatch")
    if payload.get("authorized_wrapper_actions") != [
        "preflight-d",
        "build-d",
        "resolve-d",
        "resume-preflight",
        "resume-execute",
    ]:
        raise PathCorrectionError("correction wrapper authorization mismatch")
    policy = payload.get("path_policy")
    allowlist = payload.get("datasets_external_file_allowlist")
    if (
        not isinstance(policy, dict)
        or policy.get("only_allowed_symlink_entry") != "datasets"
        or policy.get("only_allowed_symlink_depth") != 1
        or policy.get("datasets_paths_not_in_exact_allowlist_allowed") is not False
        or policy.get("leaf_symlinks_allowed") is not False
        or policy.get("nested_symlinks_allowed") is not False
        or not isinstance(allowlist, list)
        or len(allowlist) != 2
        or len({str(record.get("path")) for record in allowlist if isinstance(record, dict)})
        != 2
    ):
        raise PathCorrectionError("correction path policy/allowlist mismatch")
    _validate_symlink_identity(payload, root)
    artifacts = payload.get("artifacts")
    snapshots = payload.get("mutable_stream_prefix_snapshots")
    if not isinstance(artifacts, list) or not isinstance(snapshots, list):
        raise PathCorrectionError("correction artifacts/streams missing")
    for record in artifacts:
        if not isinstance(record, dict):
            raise PathCorrectionError("invalid correction artifact record")
        _validate_artifact_record(record, root)
    for snapshot in snapshots:
        if not isinstance(snapshot, dict):
            raise PathCorrectionError("invalid correction stream snapshot")
        _validate_prefix(snapshot, root)

    required = {
        "scripts/build_p07_a04_d_path_correction_lock_v1.py",
        "scripts/run_p07_a04_d_path_correction_v1.py",
        "scripts/tests/test_p07_a04_d_path_correction_v1.py",
        "scripts/resolve_p07_d_applicability_v4.py",
        "scripts/build_p07_d_resolution_lock_v4.py",
        "scripts/resolve_p07_d_applicability_v2.py",
        "scripts/build_p07_d_resolution_lock_v2.py",
        "scripts/resolve_p07_d_applicability_v3.py",
        "scripts/build_p07_d_resolution_lock_v3.py",
        "scripts/tests/test_p07_d_resolution_v3.py",
        "scripts/run_p07_q55_a04_layout_replacement_v1.py",
        contract.display_path(contract.RECOVERY_LOCK),
        contract.display_path(contract.RECOVERY_REGISTRATION),
        contract.display_path(contract.RECOVERY_CLOSEOUT),
    }
    locked = {str(record.get("path")): record for record in artifacts}
    missing = sorted(required - set(locked))
    if missing:
        raise PathCorrectionError(f"correction lock omits required artifacts: {missing}")
    _allowlist_matches_recovery(payload, root=root)

    snapshot_by_path = {str(item.get("path")): item for item in snapshots}
    for required_stream in (
        contract.RUN_REGISTRY,
        contract.REPLACEMENT_LEDGER,
        contract.APPLICABILITY,
        governance.D_QUEUE,
    ):
        display = contract.display_path(required_stream)
        if display not in snapshot_by_path:
            raise PathCorrectionError(f"correction lock omits stream prefix: {display}")

    # Prove the frozen event and pending-row objects occurred inside the exact
    # prefixes, while allowing later append-only queue progress.
    registry_rows = _csv_prefix_rows(
        snapshot_by_path[contract.display_path(contract.RUN_REGISTRY)], root
    )
    frozen_events = {
        row.get("registry_event_id"): row for row in registry_rows
    }
    frontend = payload.get("frontend_terminal_evidence")
    if not isinstance(frontend, list) or len(frontend) != 3:
        raise PathCorrectionError("frontend terminal evidence list mismatch")
    for item in frontend:
        if not isinstance(item, dict) or not isinstance(
            item.get("terminal_registry_event"), dict
        ):
            raise PathCorrectionError("invalid frontend terminal event")
        event = item["terminal_registry_event"]
        if frozen_events.get(event.get("registry_event_id")) != event:
            raise PathCorrectionError("terminal event not exact in frozen registry prefix")
        for evidence_key in ("audit", "input_hash_manifest", "output_hash_manifest"):
            evidence_record = item.get(evidence_key)
            if (
                not isinstance(evidence_record, dict)
                or locked.get(str(evidence_record.get("path", ""))) != evidence_record
            ):
                raise PathCorrectionError(
                    f"frontend {evidence_key} is not an exact locked artifact"
                )
        feature = item.get("feature_bag")
        output_manifest = item.get("output_hash_manifest")
        if not isinstance(feature, dict) or not isinstance(output_manifest, dict):
            raise PathCorrectionError("frontend feature/output-manifest record missing")
        manifest_path = root / str(output_manifest.get("path", ""))
        expected_line = f"{feature.get('sha256')}  {feature.get('path')}"
        try:
            manifest_lines = manifest_path.read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeError) as exc:
            raise PathCorrectionError(
                f"cannot inspect frozen frontend output manifest: {manifest_path}"
            ) from exc
        if expected_line not in manifest_lines:
            raise PathCorrectionError(
                "frontend feature bag lacks transitive output-manifest binding"
            )
    by_index = {
        int(item.get("queue_index", -1)): item
        for item in frontend
        if isinstance(item, dict)
    }
    zero = payload.get("zero_action_identity")
    p_feature = by_index.get(55, {}).get("feature_bag")
    b1_feature = by_index.get(57, {}).get("feature_bag")
    if (
        not isinstance(zero, dict)
        or not isinstance(p_feature, dict)
        or not isinstance(b1_feature, dict)
        or zero.get("accepted_learned_born_lineage_count") != 0
        or zero.get("p_feature_bag") != p_feature
        or zero.get("b1_feature_bag") != b1_feature
        or zero.get("byte_identical_sha256")
        != contract.EXPECTED_ZERO_ACTION_BAG_SHA256
        or zero.get("byte_identical_size_bytes")
        != contract.EXPECTED_ZERO_ACTION_BAG_SIZE
        or p_feature.get("sha256") != zero.get("byte_identical_sha256")
        or b1_feature.get("sha256") != zero.get("byte_identical_sha256")
        or p_feature.get("size_bytes") != zero.get("byte_identical_size_bytes")
        or b1_feature.get("size_bytes") != zero.get("byte_identical_size_bytes")
    ):
        raise PathCorrectionError("frozen zero-action P/B1 identity mismatch")
    application_rows = _csv_prefix_rows(
        snapshot_by_path[contract.display_path(contract.APPLICABILITY)], root
    )
    frozen_matching = payload.get("applicability_precondition", {}).get(
        "matching_rows"
    )
    if (
        not isinstance(frozen_matching, list)
        or len(frozen_matching) != 1
        or frozen_matching[0] not in application_rows
        or frozen_matching[0].get("resolution") != "PENDING_APPLICABILITY"
    ):
        raise PathCorrectionError("frozen A04 pending applicability row mismatch")
    return payload


def load_lock() -> dict[str, Any]:
    if not LOCK_PATH.is_file() or LOCK_PATH.is_symlink():
        raise PathCorrectionError(f"missing formal correction lock: {LOCK_PATH}")
    return validate_lock_payload(_json_object(LOCK_PATH, "correction lock"))


def _allowlist_matches_recovery(
    payload: Mapping[str, Any], *, root: Path | None = None
) -> None:
    root = contract.ROOT if root is None else root
    recovery_path = root / contract.display_path(contract.RECOVERY_LOCK)
    recovery_lock = _json_object(recovery_path, "q55 recovery lock")
    frozen_records = {
        str(record.get("path")): {
            "sha256": str(record.get("sha256")),
            "size_bytes": int(record.get("size_bytes", -1)),
        }
        for record in recovery_lock.get("artifacts", [])
        if isinstance(record, dict) and str(record.get("path", "")).startswith("datasets/")
    }
    correction_records = {
        str(record.get("path")): {
            "sha256": str(record.get("sha256")),
            "size_bytes": int(record.get("size_bytes", -1)),
        }
        for record in payload.get("datasets_external_file_allowlist", [])
        if isinstance(record, dict)
    }
    if frozen_records != correction_records or len(frozen_records) != 2:
        raise PathCorrectionError("correction allowlist differs from frozen recovery lock")


def validate_recovery_under_correction(payload: Mapping[str, Any]) -> dict[str, Any]:
    _allowlist_matches_recovery(payload)
    with patched_legacy_workspace_path(payload):
        recovery_payload = recovery.load_lock(verify_artifacts=True)
        recovery.load_closeout(recovery_payload)
        p_row = next(
            row
            for row in d_v4.queue_rows(WINDOW_ID)
            if row["arm"] == governance.P_ARM
        )
        d_v4.load_replacement_evidence(p_row)
    return recovery_payload


def _application_state() -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    manifest = audit_v3.manifest_row(WINDOW_ID)
    matching = d_v2.matching_applicability_rows(
        governance.read_csv(contract.APPLICABILITY), manifest
    )
    pending = [row for row in matching if row.get("resolution") == "PENDING_APPLICABILITY"]
    terminal = [row for row in matching if row.get("resolution") != "PENDING_APPLICABILITY"]
    return pending, terminal


def _d_collision_paths() -> list[Path]:
    possible = [d_v2.output_paths(WINDOW_ID, count)[0] for count in (0, 1)]
    derivation = d_v2.output_paths(WINDOW_ID, 1)[1]
    partials = [
        *ENHANCED_D_LOCK.parent.glob(f"{ENHANCED_D_LOCK.name}.partial.*"),
        *possible[0].parent.glob(f"{possible[0].name}.partial.*"),
        *possible[1].parent.glob(f"{possible[1].name}.partial.*"),
    ]
    paths = [ENHANCED_D_LOCK, *possible, *partials]
    if derivation is not None:
        paths.append(derivation)
    return [path for path in paths if os.path.lexists(path)]


def preflight_d(payload: dict[str, Any]) -> dict[str, Any]:
    validate_recovery_under_correction(payload)
    collisions = _d_collision_paths()
    pending, terminal = _application_state()
    if collisions or len(pending) != 1 or terminal:
        raise PathCorrectionError(
            f"corrected D preflight requires no collision and one pending/no terminal: "
            f"collisions={collisions} pending={len(pending)} terminal={len(terminal)}"
        )
    with patched_legacy_workspace_path(payload):
        observed = d_v4.preflight(WINDOW_ID)
    if (
        set(observed.get("frontend_statuses", {}).values()) != {"COMPLETED"}
        or observed.get("accepted_learned_born_lineage_count") != 0
        or observed.get("resolution_collision") is not False
        or observed.get("resolution_lock_exists") is not False
        or observed.get("effective_p_run_id")
        != payload["recovery_evidence"]["replacement_q55_terminal_event"]["run_id"]
    ):
        raise PathCorrectionError(f"corrected D legacy preflight mismatch: {observed}")
    return {
        "status": "PASS_NO_COLLISION_EXACTLY_ONE_PENDING",
        "window_id": WINDOW_ID,
        "legacy_v4_preflight": observed,
        "correction_lock_hash": payload[contract.SELF_HASH_FIELD],
        "trajectory_outcome_read": False,
    }


def _enhanced_records() -> list[dict[str, object]]:
    return [
        contract.file_record(path)
        for path in (LOCK_PATH, BUILDER_PATH, WRAPPER_PATH, TEST_PATH)
    ]


def _correction_metadata(
    payload: Mapping[str, Any], records: list[dict[str, object]]
) -> dict[str, object]:
    return {
        "schema_version": contract.SCHEMA,
        "status": "APPLIED_ADDITIVE_PATH_ADAPTER_ONLY",
        "correction_lock": records[0],
        "correction_lock_hash": payload[contract.SELF_HASH_FIELD],
        "added_artifacts": records,
        "datasets_symlink_identity": payload["datasets_symlink_identity"],
        "datasets_external_file_allowlist": payload[
            "datasets_external_file_allowlist"
        ],
        "legacy_v4_files_modified": False,
        "scientific_decision_contract_changed": False,
        "lineage_or_drop_contract_changed": False,
        "outcome_boundary": contract.OUTCOME_BOUNDARY,
        "trajectory_outcome_read": False,
    }


def build_d(payload: dict[str, Any]) -> dict[str, Any]:
    # Re-run the exact pre-build assertions; this action does not trust a
    # previous terminal printout as evidence of current filesystem state.
    preflight_d(payload)
    with patched_legacy_workspace_path(payload):
        d_payload = legacy_builder.build_lock(WINDOW_ID)
    if (
        d_payload.get("schema_version") != "isj-p07-d-resolution-lock-v4"
        or d_payload.get("decision")
        != "NOT_APPLICABLE_REQUIRE_BYTE_IDENTICAL_B1"
        or d_payload.get("lineage_contract", {}).get(
            "accepted_learned_born_lineage_count"
        )
        != 0
    ):
        raise PathCorrectionError("legacy builder produced an unexpected D decision")
    records = _enhanced_records()
    artifacts = d_payload.get("artifacts")
    if not isinstance(artifacts, list):
        raise PathCorrectionError("legacy D payload has no artifact list")
    by_path = {
        str(record.get("path")): record
        for record in [*artifacts, *records]
        if isinstance(record, dict)
    }
    d_payload["artifacts"] = list(by_path.values())
    d_payload["a04_d_path_correction"] = _correction_metadata(payload, records)
    d_payload["resolution_lock_hash"] = d_v4.resolution_lock_hash(d_payload)
    validated = _validate_then_publish_enhanced_d_lock(payload, d_payload)
    return {
        "status": "PASS_ENHANCED_D_V4_LOCK_FROZEN_NO_CLOBBER",
        "window_id": WINDOW_ID,
        "resolution_lock": contract.display_path(ENHANCED_D_LOCK),
        "resolution_lock_hash": validated["resolution_lock_hash"],
        "decision": validated["decision"],
        "correction_lock_hash": payload[contract.SELF_HASH_FIELD],
        "trajectory_outcome_read": False,
    }


def _validate_enhanced_payload(
    payload: dict[str, Any], observed: dict[str, Any]
) -> dict[str, Any]:
    metadata = observed.get("a04_d_path_correction")
    records = _enhanced_records()
    if (
        not isinstance(metadata, dict)
        or metadata != _correction_metadata(payload, records)
        or observed.get("decision")
        != "NOT_APPLICABLE_REQUIRE_BYTE_IDENTICAL_B1"
        or observed.get("lineage_contract", {}).get(
            "accepted_learned_born_lineage_count"
        )
        != 0
        or observed.get("parent_p", {}).get("run_id")
        != payload["recovery_evidence"]["replacement_q55_terminal_event"]["run_id"]
    ):
        raise PathCorrectionError("enhanced D-v4 correction metadata/decision mismatch")
    locked = {
        str(record.get("path")): record
        for record in observed.get("artifacts", [])
        if isinstance(record, dict)
    }
    for record in records:
        if locked.get(str(record["path"])) != record:
            raise PathCorrectionError(
                f"enhanced D lock omits exact correction artifact: {record['path']}"
            )
    return observed


@contextmanager
def _temporary_resolution_lock_path(path: Path) -> Iterator[None]:
    original = d_v4.resolution_lock_path
    d_v4.resolution_lock_path = lambda window_id: path
    try:
        yield
    finally:
        d_v4.resolution_lock_path = original


def _write_fsynced_json_exclusive(path: Path, payload: Mapping[str, Any]) -> None:
    fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
    try:
        content = (
            json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=True) + "\n"
        ).encode("utf-8")
        with os.fdopen(fd, "wb", closefd=True) as handle:
            fd = -1
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
    finally:
        if fd >= 0:
            os.close(fd)


def _validate_then_publish_enhanced_d_lock(
    payload: dict[str, Any], d_payload: dict[str, Any]
) -> dict[str, Any]:
    """Validate the exact temp document through old-v4 before no-replace publish."""

    ENHANCED_D_LOCK.parent.mkdir(parents=True, exist_ok=True)
    if os.path.lexists(ENHANCED_D_LOCK):
        raise FileExistsError(ENHANCED_D_LOCK)
    temporary = ENHANCED_D_LOCK.with_name(
        f"{ENHANCED_D_LOCK.name}.partial.correction.{os.getpid()}"
    )
    if os.path.lexists(temporary):
        raise FileExistsError(temporary)
    _write_fsynced_json_exclusive(temporary, d_payload)
    try:
        with patched_legacy_workspace_path(payload):
            with _temporary_resolution_lock_path(temporary):
                observed = d_v4.load_resolution_lock(WINDOW_ID)
        validated = _validate_enhanced_payload(payload, observed)
        os.link(temporary, ENHANCED_D_LOCK)
        directory_fd = os.open(
            ENHANCED_D_LOCK.parent,
            os.O_RDONLY | getattr(os, "O_DIRECTORY", 0),
        )
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
        return validated
    finally:
        temporary.unlink(missing_ok=True)


def load_enhanced_d_lock(payload: dict[str, Any]) -> dict[str, Any]:
    with patched_legacy_workspace_path(payload):
        observed = d_v4.load_resolution_lock(WINDOW_ID)
    return _validate_enhanced_payload(payload, observed)


def resolve_d(payload: dict[str, Any]) -> dict[str, Any]:
    lock = load_enhanced_d_lock(payload)
    collisions = [path for path in _d_collision_paths() if path != ENHANCED_D_LOCK]
    pending, terminal = _application_state()
    if collisions or len(pending) != 1 or terminal:
        raise PathCorrectionError(
            f"D resolve is not pristine/no-clobber: {collisions}, {pending}, {terminal}"
        )
    with patched_legacy_workspace_path(payload):
        result = d_v4.append_resolution(WINDOW_ID)
    pending_after, terminal_after = _application_state()
    output = d_v2.output_paths(WINDOW_ID, 0)[0]
    if (
        result.get("status") != "PASS_NOT_APPLICABLE"
        or result.get("resolution") != "NOT_APPLICABLE"
        or result.get("accepted_learned_born_lineage_count") != 0
        or result.get("resolver_hash") != lock.get("resolution_lock_hash")
        or result.get("parent_p_run_id")
        != payload["recovery_evidence"]["replacement_q55_terminal_event"]["run_id"]
        or len(pending_after) != 1
        or len(terminal_after) != 1
        or terminal_after[0].get("resolution") != "NOT_APPLICABLE"
        or terminal_after[0].get("resolver_hash") != lock.get("resolution_lock_hash")
        or not output.is_file()
        or _json_object(output, "A04 D closeout") != result
    ):
        raise PathCorrectionError("A04 D terminal NOT_APPLICABLE validation failed")
    return result


@contextmanager
def correction_manifest_overlay() -> Iterator[None]:
    """Add correction lock/runtime to resumed q58--60 input manifests."""

    original = recovery.base_job.write_hash_manifest
    required = [LOCK_PATH, WRAPPER_PATH]

    def writer(path: Path, files: list[Path]) -> None:
        selected = list(files)
        if path.name == "input_hash_manifest.sha256":
            selected.extend(required)
        original(path, selected)
        if path.name == "input_hash_manifest.sha256":
            text = path.read_text(encoding="utf-8")
            for item in required:
                display = audit_v3.display_path(item)
                if display not in text:
                    raise PathCorrectionError(
                        f"resumed input manifest omitted correction evidence: {display}"
                    )

    recovery.base_job.write_hash_manifest = writer
    try:
        yield
    finally:
        recovery.base_job.write_hash_manifest = original


def _assert_resume_order(index: int) -> None:
    if index not in (58, 59, 60):
        raise PathCorrectionError("corrected resume is restricted to queue 58..60")
    for predecessor in range(58, index):
        allocation = audit_v3.allocation_row(predecessor)
        chain = recovery.registry_chain(contract.RUN_REGISTRY, allocation["run_id"])
        if not chain or chain[-1].get("status") != "COMPLETED":
            raise PathCorrectionError(
                f"queue {index} blocked by corrected-resume predecessor {predecessor}"
            )


def resume_preflight(payload: dict[str, Any], index: int) -> dict[str, Any]:
    _assert_resume_order(index)
    load_enhanced_d_lock(payload)
    pending, terminal = _application_state()
    if len(pending) != 1 or len(terminal) != 1 or terminal[0].get("resolution") != "NOT_APPLICABLE":
        raise PathCorrectionError("q58+ requires terminal A04 D NOT_APPLICABLE")
    with patched_legacy_workspace_path(payload):
        return recovery.resume_preflight(recovery.load_lock(), index)


def resume_execute(
    payload: dict[str, Any], index: int, *, timeout_s: int
) -> dict[str, Any]:
    _assert_resume_order(index)
    load_enhanced_d_lock(payload)
    pending, terminal = _application_state()
    if len(pending) != 1 or len(terminal) != 1 or terminal[0].get("resolution") != "NOT_APPLICABLE":
        raise PathCorrectionError("q58+ requires terminal A04 D NOT_APPLICABLE")
    with patched_legacy_workspace_path(payload):
        recovery_payload = recovery.load_lock()
        with correction_manifest_overlay():
            return recovery.resume_execute(recovery_payload, index, timeout_s=timeout_s)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--action",
        required=True,
        choices=(
            "preflight-d",
            "build-d",
            "resolve-d",
            "resume-preflight",
            "resume-execute",
        ),
    )
    parser.add_argument("--queue-index", type=int)
    parser.add_argument("--timeout-s", type=int, default=7200)
    args = parser.parse_args()
    if args.action.startswith("resume-"):
        if args.queue_index not in (58, 59, 60):
            raise PathCorrectionError("resume action requires --queue-index 58..60")
    elif args.queue_index is not None:
        raise PathCorrectionError("--queue-index is valid only for resume actions")
    with recovery.action_lock():
        payload = load_lock()
        if args.action == "preflight-d":
            result = preflight_d(payload)
        elif args.action == "build-d":
            result = build_d(payload)
        elif args.action == "resolve-d":
            result = resolve_d(payload)
        elif args.action == "resume-preflight":
            assert args.queue_index is not None
            result = resume_preflight(payload, args.queue_index)
        else:
            assert args.queue_index is not None
            result = resume_execute(payload, args.queue_index, timeout_s=args.timeout_s)
    print(json.dumps(result, indent=2, sort_keys=True, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
