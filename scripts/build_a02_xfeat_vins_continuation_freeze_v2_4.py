#!/usr/bin/env python3
"""Build/check the additive A02 v2.4 XFeat-VINS-only freeze and incident.

The builder is read-only with respect to scientific artifacts.  Emit actions
print an apply_patch payload; they do not execute any frozen command.
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

from scripts import verify_a02_xfeat_vins_continuation_v2_4 as v2_4
from scripts import verify_a02_long_three_arm_eval_inputs_v1 as v1


DEFAULT_OUTPUT = v2_4.DEFAULT_FREEZE
DEFAULT_INCIDENT = v2_4.DEFAULT_INCIDENT


def identity(path: Path, label: str) -> dict[str, object]:
    _payload, result = v1.read_regular(path, label)
    return result


def build_incident_record() -> dict[str, object]:
    return v2_4.expected_incident_record()


def build_freeze_record() -> dict[str, object]:
    incident, incident_identity = v2_4._ORIGINAL_LOAD(
        DEFAULT_INCIDENT, "V2_4_BUILDER_INCIDENT"
    )
    if incident != build_incident_record():
        raise v1.VerificationError("V2_4_BUILDER_INCIDENT_NOT_EXACT")
    v2_4.require_paths_absent(v2_4.RESERVED_PATHS, "V2_4_BUILDER_RESERVED_PATH_PRESENT")
    if v2_4.v2_3.EMPTY_PYCACHE_PREFIX.exists() or v2_4.v2_3.EMPTY_PYCACHE_PREFIX.is_symlink():
        raise v1.VerificationError("V2_4_BUILDER_PYCACHE_PREFIX_PRESENT")
    static = {
        label: identity(path, f"V2_4_BUILDER_STATIC_{label}")
        for label, path in sorted(v2_4.expected_static_paths().items())
    }
    return {
        "schema_version": v2_4.FREEZE_SCHEMA,
        "status": v2_4.FREEZE_STATUS,
        "working_directory": str(ROOT),
        "scientific_role": v2_4.SCIENTIFIC_ROLE,
        "incident": incident_identity,
        "protocol_history": [
            {
                "protocol": "v2.3",
                "status": "FIXED_ORDER_COMPLETED_TERMINAL_NOT_RESUMED",
                "freeze": static["v2_3_freeze"],
                "terminal": static["v2_3_terminal"],
            },
            {
                "protocol": "v2.4",
                "status": "FROZEN_NOT_EXECUTED",
                "incident": incident_identity,
            },
        ],
        "v2_3_terminal_carry_forward": v2_4.current_carry_forward(),
        "reserved_paths_absent_at_freeze": list(v2_4.RESERVED_PATHS),
        "compatibility_contract": v2_4.compatibility_contract(),
        "terminal_contract": v2_4.terminal_contract(),
        "execution_policy": {
            "fixed_order": True,
            "formal_commands_executed_by_builder": False,
            "global_identity_or_input_gate_failure_stops_before_xfeat_vins": True,
            "xfeat_vins_scientific_failure_is_terminal_and_not_retried": True,
            "new_xfeat_vins_actual_process_start_limit": 1,
            "no_retry": True,
            "single_writer_working_directory": str(ROOT),
            "producer_auditor_b1_hfnet_bridge_common_support_evaluator_forbidden": True,
            "runner_native_single_arm_descriptive_report_allowed": True,
            "ranking_performed": False,
        },
        "command_labels": ["38R4", "39C4", "40C4", "41C4"],
        "commands": v2_4.expected_commands(),
        "required_static_identities": static,
    }


def canonical(record: Mapping[str, object]) -> bytes:
    return v1.canonical_json(record)


def emit_patch(path: Path, payload: bytes) -> None:
    if path.exists() or path.is_symlink():
        raise v1.VerificationError(f"V2_4_BUILDER_OUTPUT_ALREADY_EXISTS:{path}")
    print("*** Begin Patch")
    print(f"*** Add File: {path}")
    for line in payload.decode("utf-8").splitlines():
        print(f"+{line}")
    print("*** End Patch")


def check_exact(path: Path, payload: bytes, label: str) -> None:
    actual, _identity = v1.read_regular(path, label)
    if actual != payload:
        raise v1.VerificationError(f"{label}_NOT_EXACT_REBUILD")
    print(json.dumps({
        "status": "PASS_EXACT_REBUILD",
        "path": str(path),
        "sha256": hashlib.sha256(payload).hexdigest(),
        "size_bytes": len(payload),
    }, sort_keys=True))


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
            "V2_4_INCIDENT" if incident_action else "V2_4_FREEZE",
        )
        return 0
    except (v1.VerificationError, OSError, ValueError, json.JSONDecodeError) as error:
        print(f"BUILD_BLOCKED:{error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
