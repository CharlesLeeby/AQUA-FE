#!/usr/bin/env python3
"""Build or mechanically check the A02 post-incident continuation freeze.

The builder is read-only with respect to experiment artifacts.  It emits JSON
or an ``apply_patch`` payload to stdout; it never runs any frozen command.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
from typing import Sequence


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import verify_a02_long_three_arm_eval_inputs_v1 as v1
from scripts import verify_a02_long_three_arm_eval_inputs_v2 as v2


DEFAULT_OUTPUT = v2.DEFAULT_REVISION_FREEZE
ADDENDUM = ROOT / "papers/2026-08-12--a02-4500-6300-post-incident-continuation-v2.md"
V2_TESTS = ROOT / "scripts/tests/test_verify_a02_long_three_arm_eval_inputs_v2.py"
OLD_PREREG = ROOT / "papers/2026-08-12--a02-4500-6300-post-stop-long-window-comparison-preregistration.md"


def identity(path: Path, label: str) -> dict[str, object]:
    _payload, result = v1.read_regular(path, label)
    return result


def build_record() -> dict[str, object]:
    old_freeze, old_identity = v2._ORIGINAL_V1_LOAD_CANONICAL_JSON(
        v2.DEFAULT_OLD_FREEZE, "BUILDER_OLD_FREEZE"
    )
    incident, incident_identity = v2._ORIGINAL_V1_LOAD_CANONICAL_JSON(
        v2.DEFAULT_INCIDENT, "BUILDER_INCIDENT"
    )
    if old_identity["sha256"] != v2.EXPECTED_OLD_FREEZE_SHA256:
        raise v1.VerificationError("BUILDER_OLD_FREEZE_IDENTITY_MISMATCH")
    if (
        incident.get("status")
        != "CONFIRMED_INFRASTRUCTURE_FALSE_NEGATIVE_V1_PROTOCOL_TERMINATED_RC42"
    ):
        raise v1.VerificationError("BUILDER_INCIDENT_NOT_CONFIRMED")

    original_reserved = old_freeze.get("reserved_paths_absent_at_freeze")
    if not isinstance(original_reserved, list) or len(original_reserved) != 18:
        raise v1.VerificationError("BUILDER_OLD_RESERVED_SET_INVALID")
    consumed = original_reserved[:5]
    remaining = original_reserved[5:]
    redirected = [
        str(v2.DEFAULT_V2_EVIDENCE) if path == str(v1.DEFAULT_OUTPUT) else
        str(v2.DEFAULT_V2_POST_EVAL_EVIDENCE)
        if path == str(v1.DEFAULT_POST_EVAL_OUTPUT)
        else path
        for path in remaining
    ]
    if any(not Path(path).exists() for path in consumed):
        raise v1.VerificationError("BUILDER_CONSUMED_PATH_MISSING")
    present_remaining = [
        path for path in remaining if Path(path).exists() or Path(path).is_symlink()
    ]
    if present_remaining:
        raise v1.VerificationError(
            f"BUILDER_REMAINING_RESERVED_PATH_PRESENT:{present_remaining}"
        )
    present_redirected = [
        path for path in redirected if Path(path).exists() or Path(path).is_symlink()
    ]
    if present_redirected:
        raise v1.VerificationError(
            f"BUILDER_REDIRECTED_RESERVED_PATH_PRESENT:{present_redirected}"
        )
    if v2.EMPTY_PYCACHE_PREFIX.exists() or v2.EMPTY_PYCACHE_PREFIX.is_symlink():
        raise v1.VerificationError("BUILDER_PYCACHE_PREFIX_NOT_ABSENT")

    shared_root = v1.DEFAULT_SHARED_ROOT.resolve(strict=True)
    shared_entries = v2.inventory_tree(shared_root, "BUILDER_SHARED_ROOT")
    shared_summary = v2._inventory_summary(shared_entries)
    if (
        shared_summary["directory_count"] != v2.EXPECTED_SHARED_DIRECTORY_COUNT
        or shared_summary["regular_file_count"] != v2.EXPECTED_SHARED_FILE_COUNT
    ):
        raise v1.VerificationError("BUILDER_SHARED_INVENTORY_COUNT_MISMATCH")
    hardlinks = v2.validate_shared_hardlinks(shared_root)

    decision_root = v1.DEFAULT_B1_GUARD_DECISION_DIR.resolve(strict=True)
    decision_entries = v2.inventory_tree(decision_root, "BUILDER_B1_DECISION")
    decision_files = [entry for entry in decision_entries if entry["type"] == "regular"]
    if (
        len(decision_files) != 1
        or decision_files[0]["relative_path"]
        != "b1_current_exporter_v3_decision.json"
    ):
        raise v1.VerificationError("BUILDER_B1_DECISION_NOT_SINGLETON")
    native_root = v1.DEFAULT_B1_NATIVE_BAG.parent.resolve(strict=True)
    native_entries = v2.inventory_tree(native_root, "BUILDER_B1_NATIVE_RUN")

    shared_manifest = shared_root / "conversion_manifest.json"
    shared_payload, shared_manifest_identity = v1.read_regular(
        shared_manifest, "BUILDER_SHARED_MANIFEST"
    )
    parsed_shared = json.loads(shared_payload.decode("utf-8"))
    compact = v2.shared_exporter.canonical_json_bytes(parsed_shared)
    pretty = v1.canonical_json(parsed_shared)
    if shared_payload != compact or shared_payload == pretty:
        raise v1.VerificationError("BUILDER_SHARED_MANIFEST_CODEC_FINDING_CHANGED")

    required_files = {
        "continuation_addendum": ADDENDUM,
        "freeze_builder": Path(__file__).resolve(),
        "incident_receipt": v2.DEFAULT_INCIDENT,
        "old_freeze": v2.DEFAULT_OLD_FREEZE,
        "old_preregistration": OLD_PREREG,
        "shared_exporter": ROOT / "scripts/export_aqualoc_a02_shared_4500_6300_v1.py",
        "v1_verifier": v2.V1_VERIFIER,
        "v2_tests": V2_TESTS,
        "v2_verifier": v2.V2_VERIFIER,
    }
    required_identities = {
        label: identity(path, f"BUILDER_STATIC_{label}")
        for label, path in sorted(required_files.items())
    }

    commands = v2.expected_continuation_commands(old_freeze)
    return {
        "carry_forward": {
            "b1_guard_decision_tree": {
                "entries": decision_entries,
                "root": str(decision_root),
                "summary": v2._inventory_summary(decision_entries),
            },
            "b1_native_run_tree": {
                "entries": native_entries,
                "root": str(native_root),
                "summary": v2._inventory_summary(native_entries),
            },
            "canonical_window_bag": identity(
                v1.DEFAULT_WINDOW_BAG.resolve(strict=True), "BUILDER_WINDOW_BAG"
            ),
            "canonical_window_manifest": identity(
                v1.DEFAULT_WINDOW_MANIFEST.resolve(strict=True),
                "BUILDER_WINDOW_MANIFEST",
            ),
            "shared_root": {
                "camera_hardlinks": hardlinks,
                "entries": shared_entries,
                "root": str(shared_root),
                "summary": shared_summary,
            },
        },
        "command_labels": ["9R", *[f"{index}C" for index in range(10, 28)]],
        "commands": commands,
        "consumed_old_reserved_paths": consumed,
        "evidence_contracts": {
            "mandatory_provenance_key": "post_incident_continuation",
            "post_eval_path": str(v2.DEFAULT_V2_POST_EVAL_EVIDENCE),
            "post_eval_schema": v2.POST_EVAL_SCHEMA_V2,
            "pre_eval_path": str(v2.DEFAULT_V2_EVIDENCE),
            "pre_eval_schema": v2.PRE_EVAL_SCHEMA_V2,
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
        "incident_receipt": incident_identity,
        "narrow_infrastructure_change": {
            "all_other_labels": "UNCHANGED_V1_PRETTY_CANONICAL_EXACT_BYTES",
            "authorized_labels": sorted(v2.STRICT_SHARED_PRODUCER_LABELS),
            "authorized_serializer": "shared_exporter.canonical_json_bytes",
            "dual_format_acceptance": False,
            "semantic_only_acceptance": False,
        },
        "old_protocol": {
            "failure_command_index": 9,
            "failure_return_code": 42,
            "freeze": old_identity,
            "last_consumed_command_index": 8,
            "status": "TERMINATED_AT_COMMAND9_NOT_RESUMED_NOT_FULFILLED",
        },
        "post_incident_evidence_role": "REVISED_POST_INCIDENT_DEVELOPMENT_EXPLORATORY_NOT_CONFIRMATORY",
        "protocol_boundary": {
            "b1_attempt_role": "IMMUTABLE_CARRY_FORWARD_CONSUMED_ONCE_NOT_RETRY",
            "continuation_class": "REVISED_POST_INCIDENT_DEVELOPMENT_EXPLORATORY",
            "old_protocol_command9_return_code": 42,
            "old_protocol_terminated": True,
            "old_protocol_was_not_resumed_or_fulfilled": True,
            "reexecute_old_commands_0_through_8": False,
        },
        "remaining_reserved_paths": remaining,
        "redirected_continuation_reserved_paths": redirected,
        "required_static_identities": required_identities,
        "runtime_boundary": {
            "commands_require_prefix_absent": True,
            "python_pycache_prefix": str(v2.EMPTY_PYCACHE_PREFIX),
            "python_writes_bytecode": False,
        },
        "schema_version": v2.SCHEMA,
        "shared_manifest_false_negative_diagnosis": {
            "actual_identity": shared_manifest_identity,
            "actual_is_producer_compact_canonical": True,
            "actual_is_v1_pretty_canonical": False,
            "producer_compact_sha256": hashlib.sha256(compact).hexdigest(),
            "v1_pretty_reencoding_sha256": hashlib.sha256(pretty).hexdigest(),
        },
        "status": v2.STATUS,
        "working_directory": str(ROOT),
    }


def payload() -> bytes:
    return v1.canonical_json(build_record())


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(description=__doc__)
    value.add_argument(
        "--action",
        choices=("print", "emit-apply-patch", "check"),
        required=True,
    )
    value.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return value


def main(argv: Sequence[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        encoded = payload()
        if args.action == "print":
            sys.stdout.buffer.write(encoded)
            return 0
        if args.action == "emit-apply-patch":
            if args.output.exists() or args.output.is_symlink():
                raise v1.VerificationError("BUILDER_OUTPUT_ALREADY_EXISTS")
            lines = encoded.decode("utf-8").splitlines()
            print("*** Begin Patch")
            print(f"*** Add File: {args.output}")
            for line in lines:
                print(f"+{line}")
            print("*** End Patch")
            return 0
        existing, _identity = v1.read_regular(args.output, "BUILDER_EXISTING_FREEZE")
        if existing != encoded:
            raise v1.VerificationError("BUILDER_EXISTING_FREEZE_NOT_EXACT_REBUILD")
        print(
            json.dumps(
                {
                    "sha256": hashlib.sha256(encoded).hexdigest(),
                    "size_bytes": len(encoded),
                    "status": "PASS_EXACT_REBUILD",
                },
                sort_keys=True,
            )
        )
        return 0
    except (v1.VerificationError, OSError, ValueError, json.JSONDecodeError) as error:
        print(f"BUILD_BLOCKED:{error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
