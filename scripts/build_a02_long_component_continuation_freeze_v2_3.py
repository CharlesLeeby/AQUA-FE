#!/usr/bin/env python3
"""Build/check the additive A02 v2.3 component-only freeze and incident.

This builder is read-only with respect to scientific artifacts.  Emit actions
only print an ``apply_patch`` payload; they never create the output directly
and never execute a frozen continuation command.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
from typing import Mapping, Sequence


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import verify_a02_long_component_continuation_v2_3 as v2_3
from scripts import verify_a02_long_three_arm_eval_inputs_v1 as v1
from scripts import verify_a02_long_three_arm_eval_inputs_v2 as v2_1
from scripts import verify_a02_long_three_arm_eval_inputs_v2_2 as v2_2


DEFAULT_OUTPUT = v2_3.DEFAULT_FREEZE
DEFAULT_INCIDENT = v2_3.DEFAULT_INCIDENT


def identity(path: Path, label: str) -> dict[str, object]:
    _payload, result = v1.read_regular(path, label)
    return result


def build_incident_record() -> dict[str, object]:
    return v2_3.expected_incident_record()


def build_freeze_record() -> dict[str, object]:
    prior_freeze, prior_freeze_identity = v2_3._ORIGINAL_LOAD(
        v2_2.DEFAULT_REVISION_FREEZE, "V2_3_BUILDER_PRIOR_FREEZE"
    )
    if prior_freeze_identity["sha256"] != v2_3.EXPECTED_V2_2_FREEZE_SHA256:
        raise v1.VerificationError("V2_3_BUILDER_PRIOR_FREEZE_IDENTITY_MISMATCH")
    incident, incident_identity = v2_3._ORIGINAL_LOAD(
        DEFAULT_INCIDENT, "V2_3_BUILDER_INCIDENT"
    )
    if incident != build_incident_record():
        raise v1.VerificationError("V2_3_BUILDER_INCIDENT_NOT_EXACT")

    present = [
        item
        for item in v2_3.RESERVED_PATHS
        if Path(item).exists() or Path(item).is_symlink()
    ]
    if present:
        raise v1.VerificationError(f"V2_3_BUILDER_RESERVED_PATH_PRESENT:{present}")
    if v2_3.EMPTY_PYCACHE_PREFIX.exists() or v2_3.EMPTY_PYCACHE_PREFIX.is_symlink():
        raise v1.VerificationError("V2_3_BUILDER_PYCACHE_PREFIX_PRESENT")

    prior_absent = v2_3.prior_absent_paths(prior_freeze)
    appeared = [
        item for item in prior_absent if Path(item).exists() or Path(item).is_symlink()
    ]
    if appeared:
        raise v1.VerificationError(f"V2_3_BUILDER_PRIOR_ABSENT_APPEARED:{appeared}")

    static_paths = v2_3.expected_static_paths()
    static_identities = {
        label: identity(path, f"V2_3_BUILDER_STATIC_{label}")
        for label, path in sorted(static_paths.items())
    }
    incident_ids = [
        static_identities["incident_v1"],
        static_identities["incident_v2_1"],
        static_identities["incident_v2_2"],
    ]
    return {
        "schema_version": v2_3.FREEZE_SCHEMA,
        "status": v2_3.FREEZE_STATUS,
        "working_directory": str(ROOT),
        "post_incident_evidence_role": v2_3.SCIENTIFIC_ROLE,
        "incident": incident_identity,
        "protocol_history": v2_3.expected_protocol_history(*incident_ids),
        "prior_v2_2_carry_forward": prior_freeze["carry_forward"],
        "v2_2_terminal_carry_forward": v2_3.current_terminal_carry_forward(),
        "prior_present_paths_immutable": v2_3.prior_present_paths(),
        "prior_absent_paths_must_remain_absent": prior_absent,
        "reserved_paths_absent_at_freeze": list(v2_3.RESERVED_PATHS),
        "corrected_quality_audit_contract": v2_3.expected_corrected_audit_claim(),
        "narrow_infrastructure_change": {
            "quality_audit_source_codes_before": [1],
            "quality_audit_source_codes_after": [1, 2],
            "constq_rewrite_repeated": False,
            "b1_native_or_constq_bag_modified": False,
            "all_other_component_algorithms_or_parameters_changed": False,
            "hfnet_or_bridge_or_evaluator_executed": False,
        },
        "component_terminal_contract": {
            "schema_version": v2_3.TERMINAL_SCHEMA,
            "evidence_path": str(v2_3.TERMINAL_EVIDENCE),
            "b1_and_xfeat_usability_only": True,
            "component_ranking_performed": False,
            "three_arm_ranking_eligible": False,
            "hfnet_is_immutable_unusable_carry_forward": True,
            "scientific_failure_is_sealed_without_suppressing_later_commands": True,
        },
        "execution_policy": {
            "fixed_order": True,
            "formal_commands_executed_by_builder": False,
            "global_start_or_static_failure_stops_protocol": True,
            "scientific_or_dependency_failure_does_not_suppress_later_commands": True,
            "no_retry": True,
            "single_writer_working_directory": str(ROOT),
            "hfnet_bridge_evaluator_forbidden": True,
            "component_ranking_performed": False,
        },
        "command_labels": [
            "28R3", "29C3", "30C3", "31C3", "32C3",
            "33C3", "34C3", "35C3", "36C3", "37C3",
        ],
        "commands": v2_3.expected_commands(),
        "required_static_identities": static_identities,
    }


def canonical(record: Mapping[str, object]) -> bytes:
    return v1.canonical_json(record)


def emit_patch(path: Path, payload: bytes) -> None:
    if path.exists() or path.is_symlink():
        raise v1.VerificationError(f"V2_3_BUILDER_OUTPUT_ALREADY_EXISTS:{path}")
    print("*** Begin Patch")
    print(f"*** Add File: {path}")
    for line in payload.decode("utf-8").splitlines():
        print(f"+{line}")
    print("*** End Patch")


def check_exact(path: Path, payload: bytes, label: str) -> None:
    actual, _identity = v1.read_regular(path, label)
    if actual != payload:
        raise v1.VerificationError(f"{label}_NOT_EXACT_REBUILD")
    print(
        json.dumps(
            {
                "status": "PASS_EXACT_REBUILD",
                "path": str(path),
                "sha256": hashlib.sha256(payload).hexdigest(),
                "size_bytes": len(payload),
            },
            sort_keys=True,
        )
    )


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(description=__doc__)
    value.add_argument(
        "--action",
        choices=(
            "print-incident", "emit-incident-apply-patch", "check-incident",
            "print", "emit-apply-patch", "check",
        ),
        required=True,
    )
    value.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    value.add_argument("--incident", type=Path, default=DEFAULT_INCIDENT)
    return value


def main(argv: Sequence[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        incident_action = args.action in {
            "print-incident", "emit-incident-apply-patch", "check-incident"
        }
        record = build_incident_record() if incident_action else build_freeze_record()
        payload = canonical(record)
        if args.action in {"print-incident", "print"}:
            sys.stdout.buffer.write(payload)
            return 0
        if args.action in {"emit-incident-apply-patch", "emit-apply-patch"}:
            emit_patch(args.incident if incident_action else args.output, payload)
            return 0
        check_exact(
            args.incident if incident_action else args.output,
            payload,
            "V2_3_INCIDENT" if incident_action else "V2_3_FREEZE",
        )
        return 0
    except (v1.VerificationError, OSError, ValueError, json.JSONDecodeError) as error:
        print(f"BUILD_BLOCKED:{error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
