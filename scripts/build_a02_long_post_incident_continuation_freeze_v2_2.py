#!/usr/bin/env python3
"""Build/check the second A02 post-incident continuation freeze, read-only."""

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
from scripts import verify_a02_long_three_arm_eval_inputs_v2 as v2_1
from scripts import verify_a02_long_three_arm_eval_inputs_v2_2 as v2_2


DEFAULT_OUTPUT = v2_2.DEFAULT_REVISION_FREEZE


def identity(path: Path, label: str) -> dict[str, object]:
    _payload, result = v1.read_regular(path, label)
    return result


def build_record() -> dict[str, object]:
    prior_state = v2_1.validate_revision(
        v2_1.DEFAULT_REVISION_FREEZE, require_remaining_absent=True
    )
    prior, prior_identity = v2_2._ORIGINAL_LOAD(
        v2_1.DEFAULT_REVISION_FREEZE, "V2_2_BUILDER_PRIOR_FREEZE"
    )
    old, old_identity = v2_2._ORIGINAL_LOAD(
        v2_1.DEFAULT_OLD_FREEZE, "V2_2_BUILDER_OLD_FREEZE"
    )
    incident_v1, incident_v1_identity = v2_2._ORIGINAL_LOAD(
        v2_1.DEFAULT_INCIDENT, "V2_2_BUILDER_INCIDENT_V1"
    )
    incident_v2_1, incident_v2_1_identity = v2_2._ORIGINAL_LOAD(
        v2_2.DEFAULT_INCIDENT_V2_1, "V2_2_BUILDER_INCIDENT_V2_1"
    )
    v2_2.validate_incident_v2_1(incident_v2_1, prior)
    prior_start = incident_v2_1["failure_observation"]["stages"][
        "continuation_start"
    ]["parsed_record"]
    if (
        prior_identity["sha256"] != v2_2.EXPECTED_V2_1_FREEZE_SHA256
        or old_identity["sha256"] != v2_2.EXPECTED_V1_FREEZE_SHA256
        or incident_v2_1_identity["sha256"] != v2_2.EXPECTED_INCIDENT_V2_1_SHA256
    ):
        raise v1.VerificationError("V2_2_BUILDER_IMMUTABLE_IDENTITY_MISMATCH")

    old_remaining = prior.get("remaining_reserved_paths")
    prior_remaining = prior.get("redirected_continuation_reserved_paths")
    current_remaining = v2_2._v2_2_reserved_paths(prior)
    all_reserved = set([*old_remaining, *prior_remaining, *current_remaining])
    present = [
        path for path in all_reserved if Path(path).exists() or Path(path).is_symlink()
    ]
    if present:
        raise v1.VerificationError(f"V2_2_BUILDER_RESERVED_PATH_PRESENT:{sorted(present)}")
    if v2_1.EMPTY_PYCACHE_PREFIX.exists() or v2_1.EMPTY_PYCACHE_PREFIX.is_symlink():
        raise v1.VerificationError("V2_2_BUILDER_PYCACHE_PREFIX_PRESENT")

    required_files = v2_2.expected_static_paths()
    required_identities = {
        label: identity(path, f"V2_2_BUILDER_STATIC_{label}")
        for label, path in sorted(required_files.items())
    }
    commands = v2_2.expected_commands(old)
    history = v2_2.expected_protocol_history(
        v1_freeze=old_identity,
        incident_v1=incident_v1_identity,
        v2_1_freeze=prior_identity,
        incident_v2_1=incident_v2_1_identity,
    )
    return {
        "carry_forward": prior["carry_forward"],
        "command_labels": ["9R2", *[f"{index}C2" for index in range(10, 28)]],
        "commands": commands,
        "evidence_contracts": {
            "mandatory_provenance_key": "post_incident_continuation",
            "post_eval_path": str(v2_2.DEFAULT_V2_2_POST_EVAL_EVIDENCE),
            "post_eval_schema": v2_2.POST_EVAL_SCHEMA_V2_2,
            "pre_eval_path": str(v2_2.DEFAULT_V2_2_EVIDENCE),
            "pre_eval_schema": v2_2.PRE_EVAL_SCHEMA_V2_2,
            "prior_generation_evidence_paths_must_remain_absent": [
                str(v1.DEFAULT_OUTPUT),
                str(v1.DEFAULT_POST_EVAL_OUTPUT),
                str(v2_1.DEFAULT_V2_EVIDENCE),
                str(v2_1.DEFAULT_V2_POST_EVAL_EVIDENCE),
            ],
        },
        "execution_policy": {
            "fixed_order": True,
            "formal_commands_executed_by_builder": False,
            "no_retry": True,
            "old_commands_0_through_8_forbidden": True,
            "single_writer_working_directory": str(ROOT),
            "v2_1_command_9r_forbidden": True,
        },
        "legacy_v1_remaining_reserved_paths": old_remaining,
        "narrow_infrastructure_change": {
            "delegate_default_globals_mutated": False,
            "evidence_argument_conflicts_rejected": True,
            "evidence_paths_injected_as_explicit_cli_arguments": True,
            "shared_manifest_authorized_labels": sorted(
                v2_1.STRICT_SHARED_PRODUCER_LABELS
            ),
            "shared_manifest_authorized_serializer": "shared_exporter.canonical_json_bytes",
        },
        "post_incident_evidence_role": "SECOND_REVISED_POST_INCIDENT_DEVELOPMENT_EXPLORATORY_NOT_CONFIRMATORY",
        "prior_continuation_start_state": prior_start,
        "protocol_history": history,
        "required_static_identities": required_identities,
        "runtime_boundary": prior["runtime_boundary"],
        "schema_version": v2_2.SCHEMA,
        "shared_manifest_false_negative_diagnosis": prior[
            "shared_manifest_false_negative_diagnosis"
        ],
        "status": v2_2.STATUS,
        "v2_1_remaining_reserved_paths": prior_remaining,
        "v2_2_remaining_reserved_paths": current_remaining,
        "working_directory": str(ROOT),
    }


def payload() -> bytes:
    return v1.canonical_json(build_record())


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(description=__doc__)
    value.add_argument(
        "--action", choices=("print", "emit-apply-patch", "check"), required=True
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
                raise v1.VerificationError("V2_2_BUILDER_OUTPUT_ALREADY_EXISTS")
            print("*** Begin Patch")
            print(f"*** Add File: {args.output}")
            for line in encoded.decode("utf-8").splitlines():
                print(f"+{line}")
            print("*** End Patch")
            return 0
        existing, _identity = v1.read_regular(args.output, "V2_2_EXISTING_FREEZE")
        if existing != encoded:
            raise v1.VerificationError("V2_2_EXISTING_FREEZE_NOT_EXACT_REBUILD")
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
