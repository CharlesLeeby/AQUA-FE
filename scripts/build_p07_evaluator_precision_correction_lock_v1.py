#!/usr/bin/env python3
"""Freeze the outcome-blind epoch-ns precision correction for the P07 evaluator.

The builder reads only the exact governance/source allowlist declared below.
It does not discover run directories, read trajectory/APE/RPE/result artifacts,
launch VINS, evaluate a trajectory, or create an evaluation plan.
"""

from __future__ import annotations

from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
from typing import Mapping, Sequence


ROOT = Path(__file__).resolve().parents[1]
OUTPUT_RELATIVE = Path(
    "papers/ieee_sensors_journal_experiments/p07/"
    "evaluator_precision_correction_lock_v1.json"
)
METHOD_LOCK_RELATIVE = Path("papers/ieee_sensors_journal_experiments/method_lock.json")
PROTOCOL_RELATIVE = Path(
    "papers/ieee_sensors_journal_experiments/evaluator_protocol_v1.md"
)
EVALUATOR_RELATIVE = Path("scripts/evaluate_vins_common_support.py")
CORE_RELATIVE = Path("scripts/trajectory_eval_core.py")
BUILDER_RELATIVE = Path("scripts/build_p07_evaluator_precision_correction_lock_v1.py")
GOVERNANCE_TEST_RELATIVE = Path(
    "scripts/tests/test_p07_evaluator_precision_correction_lock_v1.py"
)
EVALUATOR_TEST_RELATIVE = Path("scripts/tests/test_evaluate_vins_common_support.py")
CORE_TEST_RELATIVE = Path("scripts/tests/test_trajectory_eval_core.py")

SCHEMA_VERSION = "isj-p07-evaluator-precision-correction-lock-v1"
STATUS = "FROZEN_OUTCOME_BLIND_ADDITIVE_EVALUATOR_PRECISION_CORRECTION"
EXPECTED_METHOD_SCHEMA = "isj-method-lock-nativeq-v3-final-v1"
EXPECTED_METHOD_STATUS = "FROZEN_FOR_P07_CONFIRMATORY_EXECUTION"

ALLOWED_READ_PATHS = (
    METHOD_LOCK_RELATIVE,
    PROTOCOL_RELATIVE,
    EVALUATOR_RELATIVE,
    CORE_RELATIVE,
    BUILDER_RELATIVE,
    GOVERNANCE_TEST_RELATIVE,
    EVALUATOR_TEST_RELATIVE,
    CORE_TEST_RELATIVE,
)
IMPLEMENTATION_PATHS = (EVALUATOR_RELATIVE, CORE_RELATIVE)


def now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def file_record(root: Path, relative: Path) -> dict[str, object]:
    path = root / relative
    if not path.is_file():
        raise FileNotFoundError(path)
    return {
        "path": relative.as_posix(),
        "sha256": sha256_file(path),
        "size_bytes": path.stat().st_size,
    }


def canonical_hash(payload: Mapping[str, object], excluded_key: str) -> str:
    clone = dict(payload)
    clone.pop(excluded_key, None)
    encoded = json.dumps(
        clone, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("utf-8")
    return sha256_bytes(encoded)


def correction_lock_hash(payload: Mapping[str, object]) -> str:
    return canonical_hash(payload, "correction_lock_hash")


def implementation_bundle_hash(records: Sequence[Mapping[str, object]]) -> str:
    """Hash a canonical ordered list of implementation file records."""

    encoded = json.dumps(
        list(records), sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("utf-8")
    return sha256_bytes(encoded)


def load_json_object(path: Path) -> dict[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def unique_artifact(
    method_lock: Mapping[str, object], relative: Path
) -> dict[str, object]:
    artifacts = method_lock.get("artifacts")
    if not isinstance(artifacts, list):
        raise ValueError("method lock artifacts must be a list")
    matches = [
        value
        for value in artifacts
        if isinstance(value, dict) and value.get("path") == relative.as_posix()
    ]
    if len(matches) != 1:
        raise ValueError(f"method lock must bind exactly one {relative.as_posix()}")
    record = dict(matches[0])
    digest = record.get("sha256")
    if not isinstance(digest, str) or len(digest) != 64:
        raise ValueError(f"invalid frozen SHA for {relative.as_posix()}")
    return record


def validate_precision_patch(evaluator_text: str, core_text: str) -> None:
    evaluator_compact = "".join(evaluator_text.split())
    core_compact = "".join(core_text.split())
    evaluator_markers = (
        "def parse_nanosecond_timestamp",
        'np.longdouble(stripped) / np.longdouble("1000000000")',
        "type=np.longdouble",
    )
    core_markers = (
        "dtype=np.longdouble",
        'np.longdouble("1e-12")',
        "target_stamp = stamp_arr[left] + np.longdouble(str(delta_s))",
    )
    missing = [
        marker
        for marker in evaluator_markers
        if "".join(marker.split()) not in evaluator_compact
    ] + [
        marker
        for marker in core_markers
        if "".join(marker.split()) not in core_compact
    ]
    if missing:
        raise ValueError(f"precision correction marker missing: {missing}")
    if "float(row[0])*1e-9" in evaluator_compact:
        raise ValueError("legacy epoch-ns float64 conversion is still present")


def build_lock(
    *,
    root: Path = ROOT,
    frozen_at: str | None = None,
    require_output_absent: bool = True,
) -> dict[str, object]:
    root = root.resolve()
    output = root / OUTPUT_RELATIVE
    if require_output_absent and output.exists():
        raise FileExistsError(output)

    # Do not replace this explicit allowlist with workspace discovery.  It is
    # the mechanical outcome-blind boundary for this correction builder.
    records = {relative: file_record(root, relative) for relative in ALLOWED_READ_PATHS}
    method_lock = load_json_object(root / METHOD_LOCK_RELATIVE)
    if method_lock.get("schema_version") != EXPECTED_METHOD_SCHEMA:
        raise ValueError("unexpected parent method lock schema")
    if method_lock.get("status") != EXPECTED_METHOD_STATUS:
        raise ValueError("parent method lock is not frozen for P07")

    prior_evaluator = unique_artifact(method_lock, EVALUATOR_RELATIVE)
    prior_protocol = unique_artifact(method_lock, PROTOCOL_RELATIVE)
    evaluation = method_lock.get("evaluation")
    if not isinstance(evaluation, dict) or not isinstance(
        evaluation.get("evaluator"), dict
    ):
        raise ValueError("method lock evaluation.evaluator binding is absent")
    evaluation_protocol = evaluation["evaluator"]
    assert isinstance(evaluation_protocol, dict)
    if evaluation_protocol.get("path") != PROTOCOL_RELATIVE.as_posix():
        raise ValueError("method lock evaluator protocol path changed")
    if evaluation_protocol.get("sha256") != prior_protocol.get("sha256"):
        raise ValueError("method lock contains inconsistent protocol hashes")
    current_protocol = records[PROTOCOL_RELATIVE]
    if current_protocol["sha256"] != prior_protocol["sha256"]:
        raise ValueError("evaluator protocol changed; precision correction is not additive")

    current_evaluator = records[EVALUATOR_RELATIVE]
    current_core = records[CORE_RELATIVE]
    if current_evaluator["sha256"] == prior_evaluator["sha256"]:
        raise ValueError("current evaluator still has the frozen pre-correction hash")
    validate_precision_patch(
        (root / EVALUATOR_RELATIVE).read_text(encoding="utf-8"),
        (root / CORE_RELATIVE).read_text(encoding="utf-8"),
    )

    implementation_records = [records[path] for path in IMPLEMENTATION_PATHS]
    payload: dict[str, object] = {
        "schema_version": SCHEMA_VERSION,
        "status": STATUS,
        "frozen_at": frozen_at or now(),
        "parent_method_lock": {
            **records[METHOD_LOCK_RELATIVE],
            "schema_version": method_lock["schema_version"],
            "status": method_lock["status"],
            "scientific_method_identity": method_lock.get(
                "scientific_method_identity"
            ),
        },
        "prior_implementation_binding": {
            "evaluator": prior_evaluator,
            "trajectory_eval_core": "NOT_SEPARATELY_HASH_BOUND_IN_PARENT_METHOD_LOCK",
            "disposition": "PARENT_PROVENANCE_ONLY_NOT_AUTHORIZED_FOR_P07_BACKEND_EVALUATION",
        },
        "corrected_implementation_binding": {
            "ordered_paths": [path.as_posix() for path in IMPLEMENTATION_PATHS],
            "files": implementation_records,
            "bundle_hash_algorithm": (
                "sha256(canonical_json_ordered_file_records_sort_keys_ascii_compact)"
            ),
            "implementation_bundle_sha256": implementation_bundle_hash(
                implementation_records
            ),
            "required_for_all_new_p07_backend_evaluation": True,
        },
        "protocol_binding": {
            "path": PROTOCOL_RELATIVE.as_posix(),
            "parent_sha256": prior_protocol["sha256"],
            "current_sha256": current_protocol["sha256"],
            "unchanged": True,
            "protocol_identity": "isj-evaluator-v1",
        },
        "precision_correction": {
            "scope": "TIMESTAMP_NUMERIC_REPRESENTATION_ONLY",
            "old_epoch_ns_conversion": "float(raw_integer_nanoseconds) * 1e-9",
            "new_epoch_ns_conversion": (
                "np.longdouble(raw_integer_nanoseconds) / np.longdouble(1000000000)"
            ),
            "extended_precision_preserved_through": [
                "timestamp_parse",
                "strict_monotonicity_validation",
                "uniform_grid_construction",
                "trajectory_resampling",
                "exact_delta_pair_selection",
            ],
            "prevents": [
                "epoch_scale_integer_to_float64_double_rounding",
                "sub_float64_interval_timestamp_collapse",
            ],
            "unchanged_contracts": [
                "reference_and_estimate_input_semantics",
                "camera_frame_transform",
                "evaluation_rate_selection",
                "window_boundaries",
                "gap_limits",
                "common_support_intersection",
                "SE3_fixed_scale_alignment",
                "exact_1s_translation_RPE",
                "APE_and_RPE_support_thresholds",
                "metric_definitions",
                "failure_taxonomy",
                "2_of_3_reducer",
                "scientific_unit_sequence_not_replay",
            ],
            "metric_equivalence_on_real_outcomes_claimed": False,
            "reason_no_equivalence_claim": (
                "outcome-blind source correction frozen before reading any real trajectory metric"
            ),
        },
        "outcome_blind_audit": {
            "builder_allowed_read_paths": [
                path.as_posix() for path in ALLOWED_READ_PATHS
            ],
            "workspace_discovery_used": False,
            "real_trajectory_artifact_read": False,
            "ape_artifact_read": False,
            "rpe_artifact_read": False,
            "result_artifact_read": False,
            "vins_executed": False,
            "evaluator_executed": False,
            "evaluation_plan_generated": False,
            "backend_queue_generated": False,
        },
        "governance_artifacts": [
            records[BUILDER_RELATIVE],
            records[GOVERNANCE_TEST_RELATIVE],
            records[EVALUATOR_TEST_RELATIVE],
            records[CORE_TEST_RELATIVE],
        ],
        "scientific_method_identity": "UNCHANGED_FROM_NATIVEQ_V3",
        "correction_kind": "ADDITIVE_IMPLEMENTATION_PRECISION_CORRECTION",
        "outcome_boundary": (
            "SOURCE_AND_GOVERNANCE_ONLY_NO_REAL_TRAJECTORY_APE_RPE_RESULT_READ"
        ),
        "next_action": (
            "BACKEND_QUEUE_AND_EXECUTION_LOCK_MUST_BIND_THIS_CORRECTION_LOCK_"
            "AND_CORRECTED_IMPLEMENTATION_BUNDLE"
        ),
    }
    payload["correction_lock_hash"] = correction_lock_hash(payload)
    return payload


def main() -> int:
    output = ROOT / OUTPUT_RELATIVE
    payload = build_lock()
    temporary = output.with_name(f"{output.name}.partial.{os.getpid()}")
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=True) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, output)
    print(
        "P07_EVALUATOR_PRECISION_CORRECTION_V1_PASS "
        f"hash={payload['correction_lock_hash']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
