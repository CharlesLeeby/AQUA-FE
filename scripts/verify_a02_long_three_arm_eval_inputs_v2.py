#!/usr/bin/env python3
"""Post-incident continuation verifier for the A02 4500..6300 comparison.

This is an additive wrapper around the frozen v1 verifier.  It does not turn
the stopped v1 run into a resume.  It validates a new post-incident freeze and
then changes exactly two JSON byte-codec call sites: shared manifests emitted
by ``export_aqualoc_a02_shared_4500_6300_v1.py`` must use that producer's
compact canonical codec.  Every other v1 canonical-JSON gate is delegated to
the original v1 implementation unchanged.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import sys
from typing import Mapping, Sequence


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import export_aqualoc_a02_shared_4500_6300_v1 as shared_exporter
from scripts import verify_a02_long_three_arm_eval_inputs_v1 as v1


SCHEMA = "aqua-fe-a02-4500-6300-post-incident-continuation-freeze-v2"
STATUS = "FROZEN_REVISED_POST_INCIDENT_DEVELOPMENT_EXPLORATORY_CONTINUATION"
DEFAULT_REVISION_FREEZE = (
    ROOT / "papers/a02_4500_6300_post_incident_continuation_freeze_v2.json"
)
DEFAULT_OLD_FREEZE = (
    ROOT / "papers/a02_4500_6300_post_stop_long_window_comparison_freeze_v1.json"
)
DEFAULT_INCIDENT = (
    ROOT / "papers/a02_4500_6300_command9_infrastructure_false_negative_incident_v1.json"
)
DEFAULT_V2_EVIDENCE = (
    ROOT
    / "papers/a02_4500_6300_three_arm_pre_eval_verification_v2_post_incident.json"
)
DEFAULT_V2_POST_EVAL_EVIDENCE = (
    v1.DEFAULT_EVAL_DIR / "strict_gate_receipt_v2_post_incident.json"
)
PRE_EVAL_SCHEMA_V2 = (
    "aqua-fe-a02-long-three-arm-pre-eval-verification-v2-post-incident-continuation"
)
POST_EVAL_SCHEMA_V2 = (
    "aqua-fe-a02-long-three-arm-post-eval-verification-v2-post-incident-continuation"
)
V1_VERIFIER = ROOT / "scripts/verify_a02_long_three_arm_eval_inputs_v1.py"
V2_VERIFIER = Path(__file__).resolve()
STRICT_SHARED_PRODUCER_LABELS = frozenset(
    {"SHARED_MANIFEST_SOURCE_CHAIN", "SHARED_MANIFEST"}
)
EXPECTED_OLD_FREEZE_SHA256 = (
    "dfcae748385766f5585e1799603f737abe9223cb30d1a9bcc43fe84476abf9be"
)
EXPECTED_V1_VERIFIER_SHA256 = (
    "d5316e505d6d4337e3743a38c300d963fbede9702c037eaccd501813a0683cef"
)
EXPECTED_SHARED_EXPORTER_SHA256 = (
    "c3c79bef0e96a54dca7fe559e4f5a4d4646ad4e4e73828a13ca5aa603e5e361f"
)
EXPECTED_SHARED_FILE_COUNT = 3609
EXPECTED_SHARED_DIRECTORY_COUNT = 9
EXPECTED_SHARED_HARDLINK_PAIR_COUNT = 1801
EXPECTED_REMAINING_RESERVED_COUNT = 13
EMPTY_PYCACHE_PREFIX = Path("/tmp/aqua-fe-a02-long-eval-empty-pycache-v1")

_ORIGINAL_V1_LOAD_CANONICAL_JSON = v1.load_canonical_json
_ORIGINAL_V1_BUILD_RECORD = v1.build_record
_ORIGINAL_V1_BUILD_POST_EVAL_RECORD = v1.build_post_eval_record


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _producer_canonical_json(
    path: Path, label: str
) -> tuple[dict[str, object], dict[str, object]]:
    """Load one shared manifest using only the producer's exact byte codec."""

    if label not in STRICT_SHARED_PRODUCER_LABELS:
        raise v1.VerificationError(f"V2_SHARED_CODEC_UNAUTHORIZED_LABEL:{label}")
    payload, identity = v1.read_regular(path, label)
    try:
        value = json.loads(payload.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as error:
        raise v1.VerificationError(f"{label}_INVALID_JSON") from error
    if not isinstance(value, dict):
        raise v1.VerificationError(f"{label}_NOT_CANONICAL_OBJECT")
    if payload != shared_exporter.canonical_json_bytes(value):
        raise v1.VerificationError(f"{label}_NOT_PRODUCER_CANONICAL_OBJECT")
    return value, identity


def load_canonical_json_v2(
    path: Path, label: str
) -> tuple[dict[str, object], dict[str, object]]:
    """Narrow dispatcher: two labels change; every other label remains v1."""

    if label in STRICT_SHARED_PRODUCER_LABELS:
        return _producer_canonical_json(path, label)
    return _ORIGINAL_V1_LOAD_CANONICAL_JSON(path, label)


def _identity(path: Path, label: str) -> dict[str, object]:
    _payload, identity = v1.read_regular(path, label)
    return identity


def _require_identity(claim: object, label: str) -> dict[str, object]:
    if not isinstance(claim, Mapping):
        raise v1.VerificationError(f"{label}_IDENTITY_NOT_OBJECT")
    raw_path = claim.get("path")
    if not isinstance(raw_path, str):
        raise v1.VerificationError(f"{label}_IDENTITY_PATH_INVALID")
    actual = _identity(Path(raw_path), label)
    if dict(claim) != actual:
        raise v1.VerificationError(f"{label}_IDENTITY_MISMATCH")
    return actual


def inventory_tree(root: Path, label: str) -> list[dict[str, object]]:
    """Hash every entry under a real directory using sorted relative paths."""

    if root.is_symlink() or not root.is_dir():
        raise v1.VerificationError(f"{label}_ROOT_NOT_REAL_DIRECTORY")
    canonical_root = root.resolve(strict=True)
    entries: list[dict[str, object]] = [
        {"relative_path": ".", "type": "directory"}
    ]
    for current_raw, directory_names, file_names in os.walk(
        canonical_root, topdown=True, followlinks=False
    ):
        current = Path(current_raw)
        directory_names.sort()
        file_names.sort()
        for name in directory_names:
            child = current / name
            if child.is_symlink() or not child.is_dir():
                raise v1.VerificationError(f"{label}_NON_DIRECTORY_OR_SYMLINK:{child}")
            entries.append(
                {
                    "relative_path": child.relative_to(canonical_root).as_posix(),
                    "type": "directory",
                }
            )
        for name in file_names:
            child = current / name
            payload, identity = v1.read_regular(child, f"{label}_REGULAR")
            entries.append(
                {
                    "relative_path": child.relative_to(canonical_root).as_posix(),
                    "sha256": identity["sha256"],
                    "size_bytes": len(payload),
                    "type": "regular",
                }
            )
    entries.sort(key=lambda item: (str(item["relative_path"]), str(item["type"])))
    return entries


def _inventory_summary(entries: Sequence[Mapping[str, object]]) -> dict[str, object]:
    directories = sum(item.get("type") == "directory" for item in entries)
    regular = sum(item.get("type") == "regular" for item in entries)
    total_bytes = sum(
        int(item["size_bytes"])
        for item in entries
        if item.get("type") == "regular"
    )
    return {
        "directory_count": directories,
        "inventory_sha256": _sha256_bytes(v1.canonical_json(list(entries))),
        "regular_file_count": regular,
        "total_regular_bytes": total_bytes,
    }


def validate_shared_hardlinks(shared_root: Path) -> dict[str, object]:
    shared_dir = shared_root / "shared/cam0/data"
    hfnet_dir = shared_root / "hfnet/mav0/cam0/data"
    if any(path.is_symlink() or not path.is_dir() for path in (shared_dir, hfnet_dir)):
        raise v1.VerificationError("SHARED_CAMERA_HARDLINK_DIRECTORY_INVALID")
    shared_names = sorted(path.name for path in shared_dir.iterdir())
    hfnet_names = sorted(path.name for path in hfnet_dir.iterdir())
    if shared_names != hfnet_names or len(shared_names) != EXPECTED_SHARED_HARDLINK_PAIR_COUNT:
        raise v1.VerificationError("SHARED_CAMERA_HARDLINK_NAMESET_OR_COUNT_MISMATCH")
    for name in shared_names:
        left = shared_dir / name
        right = hfnet_dir / name
        if left.is_symlink() or right.is_symlink() or not os.path.samefile(left, right):
            raise v1.VerificationError(f"SHARED_CAMERA_NOT_HARDLINK_PAIR:{name}")
    return {
        "pair_count": len(shared_names),
        "relation": "os.path.samefile(shared/cam0/data, hfnet/mav0/cam0/data)",
    }


def expected_continuation_commands(old_freeze: Mapping[str, object]) -> list[str]:
    commands = old_freeze.get("commands")
    if not isinstance(commands, list) or len(commands) != 28 or not all(
        isinstance(command, str) for command in commands
    ):
        raise v1.VerificationError("OLD_FREEZE_COMMAND_PROTOCOL_INVALID")
    old_tool = "scripts/verify_a02_long_three_arm_eval_inputs_v1.py"
    new_tool = (
        "scripts/verify_a02_long_three_arm_eval_inputs_v2.py"
        f" --revision-freeze {DEFAULT_REVISION_FREEZE}"
    )
    suffix = f"{old_tool} --action check-b1-decision || exit 42"
    if not commands[9].endswith(suffix):
        raise v1.VerificationError("OLD_COMMAND9_UNEXPECTED")
    prefix = commands[9][: -len(suffix)]
    builder_tool = "scripts/build_a02_long_post_incident_continuation_freeze_v2.py"
    command_9r = (
        f"{prefix}{builder_tool} --action check && "
        f"{prefix}{new_tool} --action check-continuation-start && "
        f"{prefix}{new_tool} --action check-b1-decision || exit 42"
    )
    continued = []
    for command in commands[10:]:
        revised = command.replace(old_tool, new_tool)
        revised = revised.replace(str(v1.DEFAULT_OUTPUT), str(DEFAULT_V2_EVIDENCE))
        revised = revised.replace(
            str(v1.DEFAULT_POST_EVAL_OUTPUT), str(DEFAULT_V2_POST_EVAL_EVIDENCE)
        )
        continued.append(revised)
    if any(old_tool in command for command in continued):
        raise v1.VerificationError("CONTINUATION_COMMAND_STILL_REFERENCES_V1_VERIFIER")
    return [command_9r, *continued]


def expected_authority_fields(
    old_freeze_identity: Mapping[str, object],
    incident_identity: Mapping[str, object],
    diagnosis: Mapping[str, object],
) -> dict[str, object]:
    return {
        "command_labels": ["9R", *[f"{index}C" for index in range(10, 28)]],
        "evidence_contracts": {
            "mandatory_provenance_key": "post_incident_continuation",
            "post_eval_path": str(DEFAULT_V2_POST_EVAL_EVIDENCE),
            "post_eval_schema": POST_EVAL_SCHEMA_V2,
            "pre_eval_path": str(DEFAULT_V2_EVIDENCE),
            "pre_eval_schema": PRE_EVAL_SCHEMA_V2,
            "v1_evidence_paths_must_remain_absent": [
                str(v1.DEFAULT_OUTPUT),
                str(v1.DEFAULT_POST_EVAL_OUTPUT),
            ],
        },
        "execution_policy": {
            "fixed_order": True,
            "formal_commands_executed_by_builder": False,
            "mandatory_arm_and_dependency_local_failure_semantics": "INHERITED_FROM_OLD_COMMANDS_10_THROUGH_27",
            "no_retry": True,
            "old_commands_0_through_8_forbidden": True,
            "single_writer_working_directory": str(ROOT),
        },
        "incident_receipt": dict(incident_identity),
        "old_protocol": {
            "failure_command_index": 9,
            "failure_return_code": 42,
            "freeze": dict(old_freeze_identity),
            "last_consumed_command_index": 8,
            "status": "TERMINATED_AT_COMMAND9_NOT_RESUMED_NOT_FULFILLED",
        },
        "post_incident_evidence_role": "REVISED_POST_INCIDENT_DEVELOPMENT_EXPLORATORY_NOT_CONFIRMATORY",
        "shared_manifest_false_negative_diagnosis": dict(diagnosis),
    }


def validate_authority_fields(
    revision: Mapping[str, object], expected: Mapping[str, object]
) -> None:
    for key, value in expected.items():
        if revision.get(key) != value:
            raise v1.VerificationError(
                f"CONTINUATION_MACHINE_AUTHORITY_FIELD_MISMATCH:{key}"
            )


def _split_revision_argument(argv: Sequence[str]) -> tuple[list[str], Path]:
    filtered: list[str] = []
    revision = DEFAULT_REVISION_FREEZE
    index = 0
    while index < len(argv):
        token = argv[index]
        if token == "--revision-freeze":
            if index + 1 >= len(argv):
                raise v1.VerificationError("REVISION_FREEZE_ARGUMENT_MISSING")
            revision = Path(argv[index + 1])
            index += 2
            continue
        if token.startswith("--revision-freeze="):
            revision = Path(token.split("=", 1)[1])
            index += 1
            continue
        filtered.append(token)
        index += 1
    return filtered, revision


def _action(argv: Sequence[str]) -> str | None:
    for index, token in enumerate(argv):
        if token == "--action" and index + 1 < len(argv):
            return argv[index + 1]
        if token.startswith("--action="):
            return token.split("=", 1)[1]
    return None


def validate_reserved_partition(
    revision: Mapping[str, object],
    old_freeze: Mapping[str, object],
    *,
    require_remaining_absent: bool,
) -> dict[str, object]:
    """Bind the consumed 0..4 / remaining 5..17 partition and live state."""

    original_reserved = old_freeze.get("reserved_paths_absent_at_freeze")
    if not isinstance(original_reserved, list) or len(original_reserved) != 18:
        raise v1.VerificationError("CONTINUATION_OLD_RESERVED_SET_INVALID")
    consumed = original_reserved[:5]
    remaining = original_reserved[5:]
    redirected = [
        str(DEFAULT_V2_EVIDENCE) if path == str(v1.DEFAULT_OUTPUT) else
        str(DEFAULT_V2_POST_EVAL_EVIDENCE)
        if path == str(v1.DEFAULT_POST_EVAL_OUTPUT)
        else path
        for path in remaining
    ]
    if (
        revision.get("consumed_old_reserved_paths") != consumed
        or revision.get("remaining_reserved_paths") != remaining
        or revision.get("redirected_continuation_reserved_paths") != redirected
        or len(remaining) != EXPECTED_REMAINING_RESERVED_COUNT
        or len(redirected) != EXPECTED_REMAINING_RESERVED_COUNT
    ):
        raise v1.VerificationError("CONTINUATION_RESERVED_PARTITION_MISMATCH")
    missing_consumed = [path for path in consumed if not Path(path).exists()]
    if missing_consumed:
        raise v1.VerificationError(f"CONTINUATION_CONSUMED_PATH_MISSING:{missing_consumed}")
    present_remaining = [
        path for path in remaining if Path(path).exists() or Path(path).is_symlink()
    ]
    present_redirected = [
        path for path in redirected if Path(path).exists() or Path(path).is_symlink()
    ]
    if require_remaining_absent and (present_remaining or present_redirected):
        raise v1.VerificationError(
            "CONTINUATION_REMAINING_RESERVED_PATH_NOT_ABSENT:"
            f"old={present_remaining}:redirected={present_redirected}"
        )
    return {
        "consumed_count": len(consumed),
        "redirected_count": len(redirected),
        "remaining_absent": require_remaining_absent,
        "remaining_count": len(remaining),
    }


def validate_revision(
    revision_path: Path, *, require_remaining_absent: bool
) -> dict[str, object]:
    revision, revision_identity = _ORIGINAL_V1_LOAD_CANONICAL_JSON(
        revision_path, "POST_INCIDENT_CONTINUATION_FREEZE"
    )
    if revision.get("schema_version") != SCHEMA or revision.get("status") != STATUS:
        raise v1.VerificationError("CONTINUATION_FREEZE_SCHEMA_OR_STATUS_MISMATCH")
    if revision.get("working_directory") != str(ROOT):
        raise v1.VerificationError("CONTINUATION_WORKING_DIRECTORY_MISMATCH")
    if revision.get("runtime_boundary") != {
        "commands_require_prefix_absent": True,
        "python_pycache_prefix": str(EMPTY_PYCACHE_PREFIX),
        "python_writes_bytecode": False,
    }:
        raise v1.VerificationError("CONTINUATION_RUNTIME_BOUNDARY_MISMATCH")
    if require_remaining_absent and (
        EMPTY_PYCACHE_PREFIX.exists() or EMPTY_PYCACHE_PREFIX.is_symlink()
    ):
        raise v1.VerificationError("CONTINUATION_PYCACHE_PREFIX_NOT_ABSENT")
    expected_boundary = {
        "b1_attempt_role": "IMMUTABLE_CARRY_FORWARD_CONSUMED_ONCE_NOT_RETRY",
        "continuation_class": "REVISED_POST_INCIDENT_DEVELOPMENT_EXPLORATORY",
        "old_protocol_command9_return_code": 42,
        "old_protocol_terminated": True,
        "old_protocol_was_not_resumed_or_fulfilled": True,
        "reexecute_old_commands_0_through_8": False,
    }
    if revision.get("protocol_boundary") != expected_boundary:
        raise v1.VerificationError("CONTINUATION_PROTOCOL_BOUNDARY_MISMATCH")
    expected_codec = {
        "all_other_labels": "UNCHANGED_V1_PRETTY_CANONICAL_EXACT_BYTES",
        "authorized_labels": sorted(STRICT_SHARED_PRODUCER_LABELS),
        "authorized_serializer": "shared_exporter.canonical_json_bytes",
        "dual_format_acceptance": False,
        "semantic_only_acceptance": False,
    }
    if revision.get("narrow_infrastructure_change") != expected_codec:
        raise v1.VerificationError("CONTINUATION_NARROW_CHANGE_CONTRACT_MISMATCH")

    identities = revision.get("required_static_identities")
    if not isinstance(identities, Mapping) or not identities:
        raise v1.VerificationError("CONTINUATION_STATIC_IDENTITIES_INVALID")
    checked_identities = {
        str(label): _require_identity(claim, f"CONTINUATION_STATIC_{label}")
        for label, claim in identities.items()
    }
    if checked_identities.get("old_freeze", {}).get("sha256") != EXPECTED_OLD_FREEZE_SHA256:
        raise v1.VerificationError("CONTINUATION_OLD_FREEZE_SHA_MISMATCH")
    if checked_identities.get("v1_verifier", {}).get("sha256") != EXPECTED_V1_VERIFIER_SHA256:
        raise v1.VerificationError("CONTINUATION_V1_VERIFIER_SHA_MISMATCH")
    if checked_identities.get("shared_exporter", {}).get("sha256") != EXPECTED_SHARED_EXPORTER_SHA256:
        raise v1.VerificationError("CONTINUATION_SHARED_EXPORTER_SHA_MISMATCH")

    old_freeze, old_identity = _ORIGINAL_V1_LOAD_CANONICAL_JSON(
        DEFAULT_OLD_FREEZE, "CONTINUATION_OLD_FREEZE"
    )
    commands = expected_continuation_commands(old_freeze)
    if revision.get("commands") != commands:
        raise v1.VerificationError("CONTINUATION_COMMAND_PROTOCOL_MISMATCH")

    incident, incident_identity = _ORIGINAL_V1_LOAD_CANONICAL_JSON(
        DEFAULT_INCIDENT, "CONTINUATION_INCIDENT"
    )
    failure = incident.get("failure_observation")
    boundary = incident.get("v1_protocol_boundary")
    if (
        incident.get("status")
        != "CONFIRMED_INFRASTRUCTURE_FALSE_NEGATIVE_V1_PROTOCOL_TERMINATED_RC42"
        or not isinstance(failure, Mapping)
        or failure.get("exact_command") != old_freeze["commands"][9]
        or failure.get("observed_return_code") != 42
        or failure.get("observed_combined_or_stderr_lines")
        != ["VERIFICATION_BLOCKED:SHARED_MANIFEST_SOURCE_CHAIN_NOT_CANONICAL_OBJECT"]
        or failure.get("persistent_raw_stream_artifact") is not False
        or not isinstance(boundary, Mapping)
        or boundary.get("command_9_terminated_v1_protocol") is not True
        or boundary.get("continuation_is_not_v1_resume") is not True
        or boundary.get("downstream_v1_commands_executed") is not False
    ):
        raise v1.VerificationError("CONTINUATION_INCIDENT_CONTRACT_MISMATCH")

    carry_forward = revision.get("carry_forward")
    if not isinstance(carry_forward, Mapping):
        raise v1.VerificationError("CONTINUATION_CARRY_FORWARD_INVALID")
    for key in ("canonical_window_bag", "canonical_window_manifest"):
        _require_identity(carry_forward.get(key), f"CARRY_FORWARD_{key}")

    shared_claim = carry_forward.get("shared_root")
    if not isinstance(shared_claim, Mapping) or not isinstance(shared_claim.get("root"), str):
        raise v1.VerificationError("CONTINUATION_SHARED_ROOT_CLAIM_INVALID")
    shared_entries = inventory_tree(Path(shared_claim["root"]), "CONTINUATION_SHARED_ROOT")
    if shared_claim.get("entries") != shared_entries:
        raise v1.VerificationError("CONTINUATION_SHARED_FULL_INVENTORY_MISMATCH")
    shared_summary = _inventory_summary(shared_entries)
    if (
        shared_claim.get("summary") != shared_summary
        or shared_summary["regular_file_count"] != EXPECTED_SHARED_FILE_COUNT
        or shared_summary["directory_count"] != EXPECTED_SHARED_DIRECTORY_COUNT
    ):
        raise v1.VerificationError("CONTINUATION_SHARED_INVENTORY_SUMMARY_MISMATCH")
    hardlinks = validate_shared_hardlinks(Path(shared_claim["root"]))
    if shared_claim.get("camera_hardlinks") != hardlinks:
        raise v1.VerificationError("CONTINUATION_SHARED_HARDLINK_CONTRACT_MISMATCH")
    shared_manifest_payload, shared_manifest_identity = v1.read_regular(
        Path(shared_claim["root"]) / "conversion_manifest.json",
        "CONTINUATION_SHARED_MANIFEST_DIAGNOSIS",
    )
    try:
        shared_manifest_value = json.loads(shared_manifest_payload.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as error:
        raise v1.VerificationError("CONTINUATION_SHARED_MANIFEST_DIAGNOSIS_INVALID_JSON") from error
    if not isinstance(shared_manifest_value, dict):
        raise v1.VerificationError("CONTINUATION_SHARED_MANIFEST_DIAGNOSIS_NOT_OBJECT")
    compact = shared_exporter.canonical_json_bytes(shared_manifest_value)
    pretty = v1.canonical_json(shared_manifest_value)
    if shared_manifest_payload != compact or shared_manifest_payload == pretty:
        raise v1.VerificationError("CONTINUATION_SHARED_MANIFEST_DIAGNOSIS_CHANGED")
    diagnosis = {
        "actual_identity": shared_manifest_identity,
        "actual_is_producer_compact_canonical": True,
        "actual_is_v1_pretty_canonical": False,
        "producer_compact_sha256": _sha256_bytes(compact),
        "v1_pretty_reencoding_sha256": _sha256_bytes(pretty),
    }
    validate_authority_fields(
        revision,
        expected_authority_fields(old_identity, incident_identity, diagnosis),
    )

    for key in ("b1_guard_decision_tree", "b1_native_run_tree"):
        claim = carry_forward.get(key)
        if not isinstance(claim, Mapping) or not isinstance(claim.get("root"), str):
            raise v1.VerificationError(f"CONTINUATION_{key.upper()}_CLAIM_INVALID")
        entries = inventory_tree(Path(claim["root"]), f"CONTINUATION_{key.upper()}")
        if claim.get("entries") != entries or claim.get("summary") != _inventory_summary(entries):
            raise v1.VerificationError(f"CONTINUATION_{key.upper()}_INVENTORY_MISMATCH")
    decision_entries = carry_forward["b1_guard_decision_tree"]["entries"]
    decision_files = [entry for entry in decision_entries if entry.get("type") == "regular"]
    if (
        len(decision_files) != 1
        or decision_files[0].get("relative_path") != "b1_current_exporter_v3_decision.json"
    ):
        raise v1.VerificationError("CONTINUATION_B1_DECISION_NOT_SINGLETON")

    reserved = validate_reserved_partition(
        revision, old_freeze, require_remaining_absent=require_remaining_absent
    )

    static = v1.validate_static_freeze(DEFAULT_OLD_FREEZE)
    return {
        "carry_forward": {
            "b1_guard_decision_tree": carry_forward["b1_guard_decision_tree"]["summary"],
            "b1_native_run_tree": carry_forward["b1_native_run_tree"]["summary"],
            "shared_root": shared_summary,
        },
        "checked_static_identity_count": len(checked_identities),
        "old_static_gate_status": static["status"],
        "remaining_reserved_absent": require_remaining_absent,
        "remaining_reserved_count": reserved["remaining_count"],
        "revision_freeze": revision_identity,
        "status": (
            "PASS_POST_INCIDENT_CONTINUATION_START"
            if require_remaining_absent
            else "PASS_POST_INCIDENT_CONTINUATION_CARRY_FORWARD"
        ),
    }


def continuation_provenance_binding(
    revision_path: Path, *, evidence_stage: str
) -> dict[str, object]:
    if evidence_stage not in {"pre_eval", "post_eval"}:
        raise v1.VerificationError("CONTINUATION_EVIDENCE_STAGE_INVALID")
    revision, revision_identity = _ORIGINAL_V1_LOAD_CANONICAL_JSON(
        revision_path, "EVIDENCE_CONTINUATION_FREEZE"
    )
    incident, incident_identity = _ORIGINAL_V1_LOAD_CANONICAL_JSON(
        DEFAULT_INCIDENT, "EVIDENCE_INCIDENT_RECEIPT"
    )
    static = revision.get("required_static_identities")
    old_protocol = revision.get("old_protocol")
    if (
        revision.get("schema_version") != SCHEMA
        or revision.get("status") != STATUS
        or not isinstance(static, Mapping)
        or not isinstance(old_protocol, Mapping)
        or old_protocol.get("status")
        != "TERMINATED_AT_COMMAND9_NOT_RESUMED_NOT_FULFILLED"
        or incident.get("status")
        != "CONFIRMED_INFRASTRUCTURE_FALSE_NEGATIVE_V1_PROTOCOL_TERMINATED_RC42"
    ):
        raise v1.VerificationError("CONTINUATION_EVIDENCE_BINDING_SOURCE_INVALID")
    for key in ("old_freeze", "v1_verifier", "v2_verifier"):
        if not isinstance(static.get(key), Mapping):
            raise v1.VerificationError(
                f"CONTINUATION_EVIDENCE_STATIC_IDENTITY_MISSING:{key}"
            )
    v2_actual = _identity(V2_VERIFIER, "EVIDENCE_V2_VERIFIER")
    if dict(static["v2_verifier"]) != v2_actual:
        raise v1.VerificationError("CONTINUATION_EVIDENCE_V2_IDENTITY_MISMATCH")
    return {
        "continuation_freeze": revision_identity,
        "continuation_freeze_status": STATUS,
        "evidence_stage": evidence_stage,
        "incident_receipt": incident_identity,
        "loader_correction": {
            "all_other_labels": "UNCHANGED_V1_PRETTY_CANONICAL_EXACT_BYTES",
            "authorized_labels": sorted(STRICT_SHARED_PRODUCER_LABELS),
            "authorized_serializer": "shared_exporter.canonical_json_bytes",
        },
        "old_freeze": dict(static["old_freeze"]),
        "old_protocol_command9_return_code": 42,
        "old_protocol_terminated": True,
        "old_protocol_was_not_resumed_or_fulfilled": True,
        "role": "REVISED_POST_INCIDENT_DEVELOPMENT_EXPLORATORY_NOT_CONFIRMATORY",
        "v1_verifier": dict(static["v1_verifier"]),
        "v2_verifier": v2_actual,
    }


def inject_continuation_provenance(
    record: Mapping[str, object],
    binding: Mapping[str, object],
    *,
    evidence_stage: str,
) -> dict[str, object]:
    if "post_incident_continuation" in record:
        raise v1.VerificationError("CONTINUATION_EVIDENCE_BINDING_ALREADY_PRESENT")
    expected_stage = binding.get("evidence_stage")
    if expected_stage != evidence_stage:
        raise v1.VerificationError("CONTINUATION_EVIDENCE_BINDING_STAGE_MISMATCH")
    result = dict(record)
    result["schema_version"] = (
        PRE_EVAL_SCHEMA_V2 if evidence_stage == "pre_eval" else POST_EVAL_SCHEMA_V2
    )
    result["post_incident_continuation"] = dict(binding)
    return result


def _delegate_to_v1(argv: Sequence[str], revision_path: Path) -> int:
    binding_pre = continuation_provenance_binding(
        revision_path, evidence_stage="pre_eval"
    )
    binding_post = continuation_provenance_binding(
        revision_path, evidence_stage="post_eval"
    )

    def build_record_v2(args: object) -> dict[str, object]:
        return inject_continuation_provenance(
            _ORIGINAL_V1_BUILD_RECORD(args), binding_pre, evidence_stage="pre_eval"
        )

    def build_post_eval_record_v2(args: object) -> dict[str, object]:
        return inject_continuation_provenance(
            _ORIGINAL_V1_BUILD_POST_EVAL_RECORD(args),
            binding_post,
            evidence_stage="post_eval",
        )

    prior_loader = v1.load_canonical_json
    prior_build = v1.build_record
    prior_post = v1.build_post_eval_record
    prior_output = v1.DEFAULT_OUTPUT
    prior_post_output = v1.DEFAULT_POST_EVAL_OUTPUT
    v1.load_canonical_json = load_canonical_json_v2
    v1.build_record = build_record_v2
    v1.build_post_eval_record = build_post_eval_record_v2
    v1.DEFAULT_OUTPUT = DEFAULT_V2_EVIDENCE
    v1.DEFAULT_POST_EVAL_OUTPUT = DEFAULT_V2_POST_EVAL_EVIDENCE
    try:
        return v1.main(argv)
    finally:
        v1.load_canonical_json = prior_loader
        v1.build_record = prior_build
        v1.build_post_eval_record = prior_post
        v1.DEFAULT_OUTPUT = prior_output
        v1.DEFAULT_POST_EVAL_OUTPUT = prior_post_output


def main(argv: Sequence[str] | None = None) -> int:
    raw = list(sys.argv[1:] if argv is None else argv)
    try:
        filtered, revision = _split_revision_argument(raw)
        action = _action(filtered)
        if action == "check-continuation-start":
            allowed = {"--action", "check-continuation-start"}
            if len(filtered) != 2 or set(filtered) != allowed:
                raise v1.VerificationError("CONTINUATION_START_UNEXPECTED_ARGUMENTS")
            record = validate_revision(revision, require_remaining_absent=True)
            print(json.dumps(record, sort_keys=True))
            return 0
        validate_revision(revision, require_remaining_absent=False)
        return _delegate_to_v1(filtered, revision)
    except (v1.VerificationError, OSError, ValueError) as error:
        print(f"VERIFICATION_BLOCKED:{error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
