#!/usr/bin/env python3
"""Build/check the additive v2.5 wrong-tree adoption and two-arm freeze.

The builder only inspects immutable artifacts.  Emit actions print an
``apply_patch`` payload and never execute the frozen 42R5--44C5 commands.
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

from scripts import verify_a02_long_three_arm_eval_inputs_v1 as v1
from scripts import verify_a02_two_arm_adoption_analysis_v2_5 as v2_5


DEFAULT_OUTPUT = v2_5.DEFAULT_FREEZE
DEFAULT_INCIDENT = v2_5.DEFAULT_INCIDENT


def identity(path: Path, label: str) -> dict[str, object]:
    _payload, result = v1.read_regular(path, label)
    return result


def build_incident_record() -> dict[str, object]:
    return v2_5.expected_incident_record()


def build_freeze_record() -> dict[str, object]:
    incident, incident_identity = v2_5._ORIGINAL_LOAD(
        DEFAULT_INCIDENT, "V2_5_BUILDER_INCIDENT"
    )
    if incident != build_incident_record():
        raise v1.VerificationError("V2_5_BUILDER_INCIDENT_NOT_EXACT")
    v2_5.require_paths_absent(
        v2_5.RESERVED_PATHS, "V2_5_BUILDER_RESERVED_PATH_PRESENT"
    )
    static = {
        label: identity(path, f"V2_5_BUILDER_STATIC_{label}")
        for label, path in sorted(v2_5.expected_static_paths().items())
    }
    return {
        "schema_version": v2_5.FREEZE_SCHEMA,
        "status": v2_5.FREEZE_STATUS,
        "working_directory": str(ROOT),
        "scientific_role": v2_5.SCIENTIFIC_ROLE,
        "incident": incident_identity,
        "protocol_history": [
            {
                "protocol": "v2.4",
                "status": "FIXED_ORDER_COMPLETED_TERMINAL_FAIL_NOT_RESUMED",
                "freeze": static["v2_4_freeze"],
                "terminal": static["v2_4_terminal"],
            },
            {
                "protocol": "v2.5",
                "status": "FROZEN_NOT_EXECUTED",
                "incident": incident_identity,
            },
        ],
        "read_only_adoption_contract": incident["read_only_adoption_proof"],
        "evaluation_contract": v2_5.evaluation_contract(),
        "interpretation_boundary": v2_5.interpretation_boundary(),
        "reserved_paths_absent_at_freeze": list(v2_5.RESERVED_PATHS),
        "execution_policy": {
            "fixed_order": True,
            "formal_commands_executed_by_builder": False,
            "global_identity_or_adoption_failure_stops_before_evaluator": True,
            "single_two_arm_evaluator_attempt": True,
            "no_retry": True,
            "atomic_exact_eval_directory_claim": True,
            "single_writer_working_directory": str(ROOT),
            "move_copy_link_cleanup_or_algorithm_rerun_forbidden": True,
            "hfnet_and_three_arm_evaluation_forbidden": True,
            "descriptive_proxy_contrast_only": True,
        },
        "command_labels": ["42R5", "43C5", "44C5"],
        "commands": v2_5.expected_commands(),
        "required_static_identities": static,
    }


def canonical(record: Mapping[str, object]) -> bytes:
    return v1.canonical_json(dict(record))


def emit_patch(path: Path, payload: bytes) -> None:
    if path.exists() or path.is_symlink():
        raise v1.VerificationError(f"V2_5_BUILDER_OUTPUT_ALREADY_EXISTS:{path}")
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
            "V2_5_INCIDENT" if incident_action else "V2_5_FREEZE",
        )
        return 0
    except (v1.VerificationError, OSError, ValueError, json.JSONDecodeError) as error:
        print(f"BUILD_BLOCKED:{error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
