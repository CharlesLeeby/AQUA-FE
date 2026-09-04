#!/usr/bin/env python3
"""Second additive post-incident continuation for A02 4500..6300.

v1 and v2.1 are immutable terminated protocols.  This wrapper retains the
two-label compact shared-manifest correction and the evidence provenance
envelope, while fixing v2.1's delegate bug: v1 DEFAULT_* globals are never
mutated.  The v2.2 evidence paths are injected as explicit, conflict-checked
CLI arguments to v1.main instead.
"""

from __future__ import annotations

import json
from pathlib import Path
import sys
from typing import Mapping, Sequence


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import verify_a02_long_three_arm_eval_inputs_v1 as v1
from scripts import verify_a02_long_three_arm_eval_inputs_v2 as v2_1


SCHEMA = "aqua-fe-a02-4500-6300-post-incident-continuation-freeze-v2-2"
STATUS = "FROZEN_SECOND_REVISED_POST_INCIDENT_DEVELOPMENT_EXPLORATORY_CONTINUATION"
DEFAULT_REVISION_FREEZE = (
    ROOT / "papers/a02_4500_6300_post_incident_continuation_freeze_v2_2.json"
)
DEFAULT_INCIDENT_V2_1 = (
    ROOT / "papers/a02_4500_6300_v2_1_9r_infrastructure_false_negative_incident_v1.json"
)
DEFAULT_V2_2_EVIDENCE = (
    ROOT
    / "papers/a02_4500_6300_three_arm_pre_eval_verification_v2_2_post_incident.json"
)
DEFAULT_V2_2_POST_EVAL_EVIDENCE = (
    v1.DEFAULT_EVAL_DIR / "strict_gate_receipt_v2_2_post_incident.json"
)
DEFAULT_ADDENDUM = (
    ROOT
    / "papers/2026-08-12--a02-4500-6300-second-post-incident-continuation-v2-2.md"
)
DEFAULT_BUILDER = (
    ROOT / "scripts/build_a02_long_post_incident_continuation_freeze_v2_2.py"
)
DEFAULT_TESTS = (
    ROOT / "scripts/tests/test_verify_a02_long_three_arm_eval_inputs_v2_2.py"
)
PRE_EVAL_SCHEMA_V2_2 = (
    "aqua-fe-a02-long-three-arm-pre-eval-verification-v2-2-post-incident-continuation"
)
POST_EVAL_SCHEMA_V2_2 = (
    "aqua-fe-a02-long-three-arm-post-eval-verification-v2-2-post-incident-continuation"
)
V2_2_VERIFIER = Path(__file__).resolve()
EXPECTED_V1_FREEZE_SHA256 = v2_1.EXPECTED_OLD_FREEZE_SHA256
EXPECTED_V1_VERIFIER_SHA256 = v2_1.EXPECTED_V1_VERIFIER_SHA256
EXPECTED_V2_1_FREEZE_SHA256 = (
    "b86da0e0015076960a9aeb9cf3766b50d6d2342438769866b7b84b4a5d55a355"
)
EXPECTED_V2_1_VERIFIER_SHA256 = (
    "842574d8abc1a0041bee0aaa0085029d63157db480ef1fac4a13656dc51dc560"
)
EXPECTED_V2_1_BUILDER_SHA256 = (
    "c7efd86e1a95464f99915f890d1fa1529651e4604fd2d696a90155896e846d56"
)
EXPECTED_INCIDENT_V2_1_SHA256 = (
    "ed71ba881409786292b1c741a8d925bf0fd13574745e7806d23d29ef48b42aea"
)

_ORIGINAL_LOAD = v1.load_canonical_json
_ORIGINAL_BUILD = v1.build_record
_ORIGINAL_POST_BUILD = v1.build_post_eval_record


def _identity(path: Path, label: str) -> dict[str, object]:
    _payload, identity = v1.read_regular(path, label)
    return identity


def _require_identity(claim: object, label: str) -> dict[str, object]:
    if not isinstance(claim, Mapping) or not isinstance(claim.get("path"), str):
        raise v1.VerificationError(f"{label}_IDENTITY_INVALID")
    actual = _identity(Path(str(claim["path"])), label)
    if dict(claim) != actual:
        raise v1.VerificationError(f"{label}_IDENTITY_MISMATCH")
    return actual


def expected_static_paths() -> dict[str, Path]:
    return {
        "incident_v1": v2_1.DEFAULT_INCIDENT,
        "old_freeze_v1": v2_1.DEFAULT_OLD_FREEZE,
        "old_verifier_v1": v2_1.V1_VERIFIER,
        "v2_1_addendum": ROOT
        / "papers/2026-08-12--a02-4500-6300-post-incident-continuation-v2.md",
        "v2_1_builder": ROOT
        / "scripts/build_a02_long_post_incident_continuation_freeze_v2.py",
        "v2_1_freeze": v2_1.DEFAULT_REVISION_FREEZE,
        "v2_1_incident": DEFAULT_INCIDENT_V2_1,
        "v2_1_tests": ROOT
        / "scripts/tests/test_verify_a02_long_three_arm_eval_inputs_v2.py",
        "v2_1_verifier": v2_1.V2_VERIFIER,
        "v2_2_addendum": DEFAULT_ADDENDUM,
        "v2_2_builder": DEFAULT_BUILDER,
        "v2_2_tests": DEFAULT_TESTS,
        "v2_2_verifier": V2_2_VERIFIER,
    }


def expected_commands(old_freeze: Mapping[str, object]) -> list[str]:
    commands = old_freeze.get("commands")
    if not isinstance(commands, list) or len(commands) != 28 or not all(
        isinstance(command, str) for command in commands
    ):
        raise v1.VerificationError("V2_2_OLD_COMMAND_PROTOCOL_INVALID")
    old_tool = "scripts/verify_a02_long_three_arm_eval_inputs_v1.py"
    new_tool = (
        "scripts/verify_a02_long_three_arm_eval_inputs_v2_2.py"
        f" --revision-freeze {DEFAULT_REVISION_FREEZE}"
    )
    suffix = f"{old_tool} --action check-b1-decision || exit 42"
    if not commands[9].endswith(suffix):
        raise v1.VerificationError("V2_2_OLD_COMMAND9_UNEXPECTED")
    prefix = commands[9][: -len(suffix)]
    command_9r2 = (
        f"{prefix}scripts/build_a02_long_post_incident_continuation_freeze_v2_2.py --action check && "
        f"{prefix}{new_tool} --action check-continuation-start && "
        f"{prefix}{new_tool} --action check-b1-decision || exit 42"
    )
    continued: list[str] = []
    for command in commands[10:]:
        revised = command.replace(old_tool, new_tool)
        revised = revised.replace(str(v1.DEFAULT_OUTPUT), str(DEFAULT_V2_2_EVIDENCE))
        revised = revised.replace(
            str(v1.DEFAULT_POST_EVAL_OUTPUT),
            str(DEFAULT_V2_2_POST_EVAL_EVIDENCE),
        )
        continued.append(revised)
    joined = "\n".join([command_9r2, *continued])
    forbidden = (
        "materialize_aqualoc_a02_4500_6300_window_v1.py",
        "export_aqualoc_a02_shared_4500_6300_v1.py",
        "run_a02_b1_klt_nativeq_current_exporter_guarded_v4.sh",
        "verify_a02_long_three_arm_eval_inputs_v1.py",
        "verify_a02_long_three_arm_eval_inputs_v2.py",
    )
    if any(token in joined for token in forbidden):
        raise v1.VerificationError("V2_2_COMMAND_RETRIES_OR_PRIOR_VERIFIER_REFERENCE")
    return [command_9r2, *continued]


def _split_revision_argument(argv: Sequence[str]) -> tuple[list[str], Path]:
    filtered: list[str] = []
    revision = DEFAULT_REVISION_FREEZE
    index = 0
    while index < len(argv):
        token = argv[index]
        if token == "--revision-freeze":
            if index + 1 >= len(argv):
                raise v1.VerificationError("V2_2_REVISION_FREEZE_ARGUMENT_MISSING")
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


def inject_explicit_evidence_arguments(argv: Sequence[str]) -> list[str]:
    conflicting = [
        token
        for token in argv
        if token in {"--evidence", "--post-eval-evidence"}
        or token.startswith("--evidence=")
        or token.startswith("--post-eval-evidence=")
    ]
    if conflicting:
        raise v1.VerificationError(
            f"V2_2_EXPLICIT_EVIDENCE_ARGUMENT_CONFLICT:{conflicting}"
        )
    return [
        *argv,
        "--evidence",
        str(DEFAULT_V2_2_EVIDENCE),
        "--post-eval-evidence",
        str(DEFAULT_V2_2_POST_EVAL_EVIDENCE),
    ]


def expected_protocol_history(
    *,
    v1_freeze: Mapping[str, object],
    incident_v1: Mapping[str, object],
    v2_1_freeze: Mapping[str, object],
    incident_v2_1: Mapping[str, object],
) -> list[dict[str, object]]:
    return [
        {
            "failure_return_code": 42,
            "freeze": dict(v1_freeze),
            "incident": dict(incident_v1),
            "protocol": "v1",
            "status": "TERMINATED_AT_COMMAND9_NOT_RESUMED_NOT_FULFILLED",
        },
        {
            "failure_return_code": 42,
            "freeze": dict(v2_1_freeze),
            "incident": dict(incident_v2_1),
            "protocol": "v2.1",
            "status": "TERMINATED_AT_9R_NOT_RETRIED_NOT_RESUMED",
        },
    ]


def validate_incident_v2_1(
    incident: Mapping[str, object], prior_freeze: Mapping[str, object]
) -> None:
    observation = incident.get("failure_observation")
    boundary = incident.get("v2_1_protocol_boundary")
    if (
        incident.get("status")
        != "CONFIRMED_INFRASTRUCTURE_FALSE_NEGATIVE_V2_1_PROTOCOL_TERMINATED_RC42"
        or not isinstance(observation, Mapping)
        or observation.get("exact_command") != prior_freeze["commands"][0]
        or observation.get("whole_command_return_code") != 42
        or observation.get("persistent_raw_stream_artifact") is not False
        or not isinstance(boundary, Mapping)
        or boundary.get("command_9r_must_not_be_reexecuted") is not True
        or boundary.get("continuation_is_not_v2_1_resume") is not True
        or boundary.get("downstream_scientific_commands_executed") is not False
        or boundary.get("producer_or_b1_commands_executed_by_v2_1") is not False
    ):
        raise v1.VerificationError("V2_2_INCIDENT_V2_1_CONTRACT_MISMATCH")
    stages = observation.get("stages")
    if not isinstance(stages, Mapping):
        raise v1.VerificationError("V2_2_INCIDENT_V2_1_STAGES_MISSING")
    builder = stages.get("builder_exact_rebuild")
    start = stages.get("continuation_start")
    decision = stages.get("decision")
    parsed = start.get("parsed_record") if isinstance(start, Mapping) else None
    if (
        not isinstance(builder, Mapping)
        or builder.get("status") != "PASS_EXACT_REBUILD"
        or not isinstance(parsed, Mapping)
        or parsed.get("status") != "PASS_POST_INCIDENT_CONTINUATION_START"
        or parsed.get("revision_freeze_sha256") != EXPECTED_V2_1_FREEZE_SHA256
        or parsed.get("remaining_reserved_count") != 13
        or not isinstance(decision, Mapping)
        or decision.get("observed_stderr_lines")
        != ["VERIFICATION_BLOCKED:STATIC_COMMAND_PROTOCOL_EXACT_MISMATCH_AT_25"]
    ):
        raise v1.VerificationError("V2_2_INCIDENT_V2_1_STAGE_EVIDENCE_MISMATCH")


def _v2_2_reserved_paths(prior_freeze: Mapping[str, object]) -> list[str]:
    prior_paths = prior_freeze.get("redirected_continuation_reserved_paths")
    if not isinstance(prior_paths, list) or len(prior_paths) != 13:
        raise v1.VerificationError("V2_2_PRIOR_RESERVED_PATHS_INVALID")
    return [
        str(DEFAULT_V2_2_EVIDENCE)
        if path == str(v2_1.DEFAULT_V2_EVIDENCE)
        else str(DEFAULT_V2_2_POST_EVAL_EVIDENCE)
        if path == str(v2_1.DEFAULT_V2_POST_EVAL_EVIDENCE)
        else path
        for path in prior_paths
    ]


def validate_three_generation_reserved_paths(
    revision: Mapping[str, object],
    prior_freeze: Mapping[str, object],
    *,
    require_absent: bool,
) -> dict[str, object]:
    old_remaining = prior_freeze.get("remaining_reserved_paths")
    prior_remaining = prior_freeze.get("redirected_continuation_reserved_paths")
    current_remaining = _v2_2_reserved_paths(prior_freeze)
    if (
        not isinstance(old_remaining, list)
        or not isinstance(prior_remaining, list)
        or revision.get("legacy_v1_remaining_reserved_paths") != old_remaining
        or revision.get("v2_1_remaining_reserved_paths") != prior_remaining
        or revision.get("v2_2_remaining_reserved_paths") != current_remaining
    ):
        raise v1.VerificationError("V2_2_THREE_GENERATION_RESERVED_PATHS_MISMATCH")
    union = sorted(set([*old_remaining, *prior_remaining, *current_remaining]))
    if require_absent:
        present = [
            path
            for path in union
            if Path(path).exists() or Path(path).is_symlink()
        ]
        if present:
            raise v1.VerificationError(
                f"V2_2_THREE_GENERATION_EVIDENCE_OR_OUTPUT_PRESENT:{present}"
            )
    return {
        "generation_count": 3,
        "unique_path_count": len(union),
        "v2_2_remaining_reserved_count": len(current_remaining),
    }


def validate_revision(
    revision_path: Path, *, require_remaining_absent: bool
) -> dict[str, object]:
    revision, revision_identity = _ORIGINAL_LOAD(
        revision_path, "V2_2_CONTINUATION_FREEZE"
    )
    if (
        revision.get("schema_version") != SCHEMA
        or revision.get("status") != STATUS
        or revision.get("working_directory") != str(ROOT)
    ):
        raise v1.VerificationError("V2_2_FREEZE_SCHEMA_STATUS_OR_CWD_MISMATCH")

    prior_state = v2_1.validate_revision(
        v2_1.DEFAULT_REVISION_FREEZE,
        require_remaining_absent=require_remaining_absent,
    )
    prior_freeze, prior_freeze_identity = _ORIGINAL_LOAD(
        v2_1.DEFAULT_REVISION_FREEZE, "V2_2_PRIOR_FREEZE"
    )
    old_freeze, old_freeze_identity = _ORIGINAL_LOAD(
        v2_1.DEFAULT_OLD_FREEZE, "V2_2_OLD_FREEZE"
    )
    incident_v1, incident_v1_identity = _ORIGINAL_LOAD(
        v2_1.DEFAULT_INCIDENT, "V2_2_INCIDENT_V1"
    )
    incident_v2_1, incident_v2_1_identity = _ORIGINAL_LOAD(
        DEFAULT_INCIDENT_V2_1, "V2_2_INCIDENT_V2_1"
    )
    validate_incident_v2_1(incident_v2_1, prior_freeze)

    identities = revision.get("required_static_identities")
    expected_paths = expected_static_paths()
    if not isinstance(identities, Mapping) or set(identities) != set(expected_paths):
        raise v1.VerificationError("V2_2_STATIC_IDENTITIES_INVALID")
    checked = {
        str(label): _require_identity(claim, f"V2_2_STATIC_{label}")
        for label, claim in identities.items()
    }
    for label, path in expected_paths.items():
        if checked[label]["path"] != str(path.resolve(strict=True)):
            raise v1.VerificationError(f"V2_2_STATIC_IDENTITY_PATH_MISMATCH:{label}")
    required_hashes = {
        "old_freeze_v1": EXPECTED_V1_FREEZE_SHA256,
        "old_verifier_v1": EXPECTED_V1_VERIFIER_SHA256,
        "v2_1_builder": EXPECTED_V2_1_BUILDER_SHA256,
        "v2_1_freeze": EXPECTED_V2_1_FREEZE_SHA256,
        "v2_1_verifier": EXPECTED_V2_1_VERIFIER_SHA256,
        "v2_1_incident": EXPECTED_INCIDENT_V2_1_SHA256,
    }
    for label, expected_sha in required_hashes.items():
        if checked.get(label, {}).get("sha256") != expected_sha:
            raise v1.VerificationError(f"V2_2_REQUIRED_IDENTITY_SHA_MISMATCH:{label}")

    if revision.get("carry_forward") != prior_freeze.get("carry_forward"):
        raise v1.VerificationError("V2_2_CARRY_FORWARD_NOT_EXACT_PRIOR_INVENTORY")
    prior_observation = incident_v2_1.get("failure_observation")
    prior_stages = (
        prior_observation.get("stages")
        if isinstance(prior_observation, Mapping)
        else None
    )
    prior_start = (
        prior_stages.get("continuation_start")
        if isinstance(prior_stages, Mapping)
        else None
    )
    expected_prior_start = (
        prior_start.get("parsed_record") if isinstance(prior_start, Mapping) else None
    )
    if (
        not isinstance(expected_prior_start, Mapping)
        or revision.get("prior_continuation_start_state")
        != dict(expected_prior_start)
    ):
        raise v1.VerificationError("V2_2_PRIOR_START_STATE_MISMATCH")
    if revision.get("runtime_boundary") != prior_freeze.get("runtime_boundary"):
        raise v1.VerificationError("V2_2_RUNTIME_BOUNDARY_MISMATCH")
    if revision.get("shared_manifest_false_negative_diagnosis") != prior_freeze.get(
        "shared_manifest_false_negative_diagnosis"
    ):
        raise v1.VerificationError("V2_2_SHARED_DIAGNOSIS_NOT_EXACT_PRIOR")
    commands = expected_commands(old_freeze)
    if revision.get("commands") != commands:
        raise v1.VerificationError("V2_2_COMMAND_PROTOCOL_MISMATCH")
    if revision.get("command_labels") != [
        "9R2",
        *[f"{index}C2" for index in range(10, 28)],
    ]:
        raise v1.VerificationError("V2_2_COMMAND_LABELS_MISMATCH")

    history = expected_protocol_history(
        v1_freeze=old_freeze_identity,
        incident_v1=incident_v1_identity,
        v2_1_freeze=prior_freeze_identity,
        incident_v2_1=incident_v2_1_identity,
    )
    if revision.get("protocol_history") != history:
        raise v1.VerificationError("V2_2_PROTOCOL_HISTORY_MISMATCH")
    expected_change = {
        "delegate_default_globals_mutated": False,
        "evidence_argument_conflicts_rejected": True,
        "evidence_paths_injected_as_explicit_cli_arguments": True,
        "shared_manifest_authorized_labels": sorted(
            v2_1.STRICT_SHARED_PRODUCER_LABELS
        ),
        "shared_manifest_authorized_serializer": "shared_exporter.canonical_json_bytes",
    }
    if revision.get("narrow_infrastructure_change") != expected_change:
        raise v1.VerificationError("V2_2_NARROW_CHANGE_MISMATCH")
    expected_evidence = {
        "mandatory_provenance_key": "post_incident_continuation",
        "post_eval_path": str(DEFAULT_V2_2_POST_EVAL_EVIDENCE),
        "post_eval_schema": POST_EVAL_SCHEMA_V2_2,
        "pre_eval_path": str(DEFAULT_V2_2_EVIDENCE),
        "pre_eval_schema": PRE_EVAL_SCHEMA_V2_2,
        "prior_generation_evidence_paths_must_remain_absent": [
            str(v1.DEFAULT_OUTPUT),
            str(v1.DEFAULT_POST_EVAL_OUTPUT),
            str(v2_1.DEFAULT_V2_EVIDENCE),
            str(v2_1.DEFAULT_V2_POST_EVAL_EVIDENCE),
        ],
    }
    if revision.get("evidence_contracts") != expected_evidence:
        raise v1.VerificationError("V2_2_EVIDENCE_CONTRACT_MISMATCH")
    expected_policy = {
        "fixed_order": True,
        "formal_commands_executed_by_builder": False,
        "no_retry": True,
        "old_commands_0_through_8_forbidden": True,
        "single_writer_working_directory": str(ROOT),
        "v2_1_command_9r_forbidden": True,
    }
    if revision.get("execution_policy") != expected_policy:
        raise v1.VerificationError("V2_2_EXECUTION_POLICY_MISMATCH")
    if (
        revision.get("post_incident_evidence_role")
        != "SECOND_REVISED_POST_INCIDENT_DEVELOPMENT_EXPLORATORY_NOT_CONFIRMATORY"
    ):
        raise v1.VerificationError("V2_2_EVIDENCE_ROLE_MISMATCH")

    reserved = validate_three_generation_reserved_paths(
        revision, prior_freeze, require_absent=require_remaining_absent
    )
    return {
        "checked_static_identity_count": len(checked),
        "prior_state_status": prior_state["status"],
        "revision_freeze": revision_identity,
        "status": (
            "PASS_SECOND_POST_INCIDENT_CONTINUATION_START"
            if require_remaining_absent
            else "PASS_SECOND_POST_INCIDENT_CONTINUATION_CARRY_FORWARD"
        ),
        "v1_and_v2_1_terminated_protocol_count": len(history),
        "v2_2_remaining_reserved_count": reserved["v2_2_remaining_reserved_count"],
    }


def continuation_binding(
    revision_path: Path, *, evidence_stage: str
) -> dict[str, object]:
    if evidence_stage not in {"pre_eval", "post_eval"}:
        raise v1.VerificationError("V2_2_EVIDENCE_STAGE_INVALID")
    revision, revision_identity = _ORIGINAL_LOAD(
        revision_path, "V2_2_EVIDENCE_FREEZE"
    )
    static = revision.get("required_static_identities")
    history = revision.get("protocol_history")
    if (
        revision.get("schema_version") != SCHEMA
        or revision.get("status") != STATUS
        or not isinstance(static, Mapping)
        or not isinstance(history, list)
        or len(history) != 2
    ):
        raise v1.VerificationError("V2_2_EVIDENCE_BINDING_SOURCE_INVALID")
    actual_v2_2 = _identity(V2_2_VERIFIER, "V2_2_EVIDENCE_VERIFIER")
    if dict(static.get("v2_2_verifier", {})) != actual_v2_2:
        raise v1.VerificationError("V2_2_EVIDENCE_VERIFIER_IDENTITY_MISMATCH")
    return {
        "active_continuation_freeze": revision_identity,
        "active_verifier": actual_v2_2,
        "evidence_stage": evidence_stage,
        "loader_correction": {
            "authorized_labels": sorted(v2_1.STRICT_SHARED_PRODUCER_LABELS),
            "authorized_serializer": "shared_exporter.canonical_json_bytes",
            "all_other_labels": "UNCHANGED_V1_PRETTY_CANONICAL_EXACT_BYTES",
        },
        "protocol_history": history,
        "role": "SECOND_REVISED_POST_INCIDENT_DEVELOPMENT_EXPLORATORY_NOT_CONFIRMATORY",
        "v2_2_delegate_contract": {
            "default_globals_mutated": False,
            "evidence_paths_are_explicit_cli_arguments": True,
        },
    }


def inject_provenance(
    record: Mapping[str, object],
    binding: Mapping[str, object],
    *,
    evidence_stage: str,
) -> dict[str, object]:
    if "post_incident_continuation" in record:
        raise v1.VerificationError("V2_2_PROVENANCE_ALREADY_PRESENT")
    if binding.get("evidence_stage") != evidence_stage:
        raise v1.VerificationError("V2_2_PROVENANCE_STAGE_MISMATCH")
    result = dict(record)
    result["schema_version"] = (
        PRE_EVAL_SCHEMA_V2_2
        if evidence_stage == "pre_eval"
        else POST_EVAL_SCHEMA_V2_2
    )
    result["post_incident_continuation"] = dict(binding)
    return result


def _delegate(argv: Sequence[str], revision_path: Path) -> int:
    explicit = inject_explicit_evidence_arguments(argv)
    binding_pre = continuation_binding(revision_path, evidence_stage="pre_eval")
    binding_post = continuation_binding(revision_path, evidence_stage="post_eval")

    def build_v2_2(args: object) -> dict[str, object]:
        return inject_provenance(
            _ORIGINAL_BUILD(args), binding_pre, evidence_stage="pre_eval"
        )

    def post_build_v2_2(args: object) -> dict[str, object]:
        return inject_provenance(
            _ORIGINAL_POST_BUILD(args), binding_post, evidence_stage="post_eval"
        )

    original_defaults = (v1.DEFAULT_OUTPUT, v1.DEFAULT_POST_EVAL_OUTPUT)
    prior_loader = v1.load_canonical_json
    prior_build = v1.build_record
    prior_post = v1.build_post_eval_record
    v1.load_canonical_json = v2_1.load_canonical_json_v2
    v1.build_record = build_v2_2
    v1.build_post_eval_record = post_build_v2_2
    try:
        if (v1.DEFAULT_OUTPUT, v1.DEFAULT_POST_EVAL_OUTPUT) != original_defaults:
            raise v1.VerificationError("V2_2_DEFAULT_GLOBALS_CHANGED_BEFORE_DELEGATE")
        old_freeze, _old_identity = _ORIGINAL_LOAD(
            v2_1.DEFAULT_OLD_FREEZE, "V2_2_DELEGATE_OLD_FREEZE"
        )
        if v1.authoritative_commands() != old_freeze.get("commands"):
            raise v1.VerificationError(
                "V2_2_DELEGATE_MUTATED_V1_AUTHORITATIVE_COMMANDS"
            )
        return v1.main(explicit)
    finally:
        v1.load_canonical_json = prior_loader
        v1.build_record = prior_build
        v1.build_post_eval_record = prior_post
        if (v1.DEFAULT_OUTPUT, v1.DEFAULT_POST_EVAL_OUTPUT) != original_defaults:
            raise v1.VerificationError("V2_2_DEFAULT_GLOBALS_CHANGED_DURING_DELEGATE")


def main(argv: Sequence[str] | None = None) -> int:
    raw = list(sys.argv[1:] if argv is None else argv)
    try:
        filtered, revision = _split_revision_argument(raw)
        action = _action(filtered)
        if action == "check-continuation-start":
            if filtered != ["--action", "check-continuation-start"]:
                raise v1.VerificationError("V2_2_START_UNEXPECTED_ARGUMENTS")
            record = validate_revision(revision, require_remaining_absent=True)
            print(json.dumps(record, sort_keys=True))
            return 0
        validate_revision(revision, require_remaining_absent=False)
        return _delegate(filtered, revision)
    except (v1.VerificationError, OSError, ValueError) as error:
        print(f"VERIFICATION_BLOCKED:{error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
