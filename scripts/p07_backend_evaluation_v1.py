#!/usr/bin/env python3
"""Outcome-agnostic P07 backend evaluation planning and reduction primitives.

This module does not discover run directories, read trajectories, or launch an
evaluator.  Its inputs are explicit terminal-replay evidence records supplied
by the P07 backend auditor.  Keeping those boundaries here prevents an
evaluation plan from silently changing common support, pairing different
replay slots, or treating technical repeats as independent samples.
"""

from __future__ import annotations

from collections import defaultdict
from decimal import Decimal
import math
from pathlib import PurePosixPath
import re
from statistics import median
from typing import Iterable, Mapping, Sequence


SCHEMA_VERSION = "isj-p07-backend-evaluation-code-v1"

ARM_B0 = "B0_native_vins_origin_v1"
ARM_B1 = "B1_klt_nativeq_v3"
ARM_P = "P_legacy_nativeq_xfeat_seedchain_v3"
ARM_M = "M_xfeat_pairwise_nativeq_v1"
ARM_D = "D_legacy_exact_lineage_drop_v3"

REQUIRED_ARMS = (ARM_B0, ARM_B1, ARM_P, ARM_M)
PAIRWISE_COMPARATORS = (ARM_B1, ARM_M, ARM_D)

ROUTE_PAIRWISE_COMMON_SUPPORT = "G0_PAIRWISE_COMMON_SUPPORT_V1"
ROUTE_B0_DESCRIPTIVE = "G0_B0_REFERENCE_SUPPORT_DESCRIPTIVE_V1"
PAIRWISE_METRIC_ROLE = "FROZEN_INFERENTIAL_OR_CONTROLLED_CONTRAST"
B0_METRIC_ROLE = "DESCRIPTIVE_ONLY_NOT_AN_INFERENTIAL_CONTRAST"

REPLAY_INDICES = frozenset((1, 2, 3))
MINIMUM_EVALUABLE_REPLAYS = 2

HARD_FAILURE_CODES = (
    "NONZERO_EXIT",
    "TIMEOUT",
    "EMPTY_TRAJECTORY",
    "NONFINITE_TRAJECTORY",
    "NONMONOTONIC_TRAJECTORY",
    "INITIALIZATION_FAILURE",
    "COVERAGE_BELOW_0P50",
)
INFRASTRUCTURE_CODES = frozenset(
    (
        "ROS_MASTER_CONFLICT",
        "FILE_NOT_FOUND",
        "DISK_FULL",
        "PERMISSION_DENIED",
        "HARDWARE_INTERRUPTION",
        "OPERATOR_INTERRUPTION",
    )
)
SOLVER_RISK_PATTERNS = {
    "LINEAR_SOLVER_FAILURE": (
        re.compile(r"Linear solver failure"),
        re.compile(r"Unable to perform dense Cholesky factorization"),
    ),
    "ESTIMATOR_RESET_OR_RESTART": (
        re.compile(r"failure detection!"),
        re.compile(r"system reboot!"),
        re.compile(r"restart the estimator!"),
    ),
    "NUMERICAL_ABNORMALITY": (
        re.compile(r"(?<![A-Za-z])nan(?![A-Za-z])", re.IGNORECASE),
        re.compile(
            r"(?<![A-Za-z])[+-]?inf(?:inity)?(?![A-Za-z])", re.IGNORECASE
        ),
    ),
}

INITIALIZATION_DEADLINE_S = 10.0
HARD_FAILURE_COVERAGE_BELOW = 0.50
SUSTAINED_QUEUE_DROP_RATE_ABOVE = 0.01
SUSTAINED_BACKLOG_GROWTH_S_AT_LEAST = 5.0


class EvaluationContractError(ValueError):
    """Raised when a record would violate the frozen P07 evaluation route."""


def _require_nonempty_text(record: Mapping[str, object], key: str) -> str:
    value = record.get(key)
    if not isinstance(value, str) or not value:
        raise EvaluationContractError(f"{key} must be a non-empty string")
    return value


def _require_bool(record: Mapping[str, object], key: str) -> bool:
    value = record.get(key)
    if type(value) is not bool:
        raise EvaluationContractError(f"{key} must be a boolean")
    return value


def _finite_number(value: object, *, minimum: float | None = None) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    if not math.isfinite(number) or (minimum is not None and number < minimum):
        return None
    return number


def _require_replay_index(record: Mapping[str, object]) -> int:
    value = record.get("replay_index")
    if isinstance(value, bool) or not isinstance(value, int) or value not in REPLAY_INDICES:
        raise EvaluationContractError("replay_index must be one of 1, 2, or 3")
    return value


def _validate_sha256(value: object, key: str) -> str:
    if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value) is None:
        raise EvaluationContractError(f"{key} must be a lowercase SHA-256 hex digest")
    return value


def _reference_contract(record: Mapping[str, object]) -> dict[str, object]:
    raw = record.get("reference")
    if not isinstance(raw, Mapping):
        raise EvaluationContractError("reference must be an object")
    kind = raw.get("kind")
    if kind not in ("tum", "bag"):
        raise EvaluationContractError("reference.kind must be 'tum' or 'bag'")
    path = raw.get("path")
    if not isinstance(path, str) or not path:
        raise EvaluationContractError("reference.path must be non-empty")
    topic = raw.get("topic")
    if kind == "bag" and (not isinstance(topic, str) or not topic):
        raise EvaluationContractError("reference.topic is required for a bag reference")
    if kind == "tum" and topic not in (None, ""):
        raise EvaluationContractError("reference.topic must be absent for a TUM reference")

    numeric: dict[str, float] = {}
    for key, minimum in (
        ("nominal_reference_rate_hz", 0.0),
        ("nominal_estimate_rate_hz", 0.0),
        ("window_start_s", None),
        ("window_end_s", None),
        ("max_reference_gap_s", 0.0),
        ("max_estimate_gap_s", 0.0),
        ("reference_time_offset_s", None),
    ):
        value = _finite_number(raw.get(key), minimum=minimum)
        if value is None or (minimum == 0.0 and value <= 0.0):
            raise EvaluationContractError(f"reference.{key} is invalid")
        numeric[key] = value
    if numeric["window_end_s"] <= numeric["window_start_s"]:
        raise EvaluationContractError("reference window_end_s must exceed window_start_s")
    result: dict[str, object] = {
        "kind": kind,
        "path": path,
        **({"topic": topic} if kind == "bag" else {}),
        **numeric,
    }
    # Production P07 contracts preserve absolute ROS/reference endpoints as
    # integer nanoseconds.  The float seconds remain for compatibility with
    # the original primitives, while the runner formats evaluator argv from
    # these integers so epoch-scale timestamps do not suffer a second float64
    # rounding.  Legacy fixtures without ns fields remain valid.
    start_ns = raw.get("window_start_ns")
    end_ns = raw.get("window_end_ns")
    if (start_ns is None) != (end_ns is None):
        raise EvaluationContractError(
            "reference window_start_ns/window_end_ns must be supplied together"
        )
    if start_ns is not None:
        if (
            isinstance(start_ns, bool)
            or not isinstance(start_ns, int)
            or isinstance(end_ns, bool)
            or not isinstance(end_ns, int)
            or end_ns <= start_ns
        ):
            raise EvaluationContractError("reference integer-ns endpoints are invalid")
        if start_ns < 100_000_000 * 1_000_000_000:
            raise EvaluationContractError(
                "reference integer-ns endpoints must be absolute epoch timestamps"
            )
        result["window_start_ns"] = start_ns
        result["window_end_ns"] = end_ns
        # Recompute compatibility seconds from the exact integer identity.  Do
        # not trust a caller-provided 45/90 relative-window value.
        result["window_start_s"] = float(Decimal(start_ns) / Decimal(1_000_000_000))
        result["window_end_s"] = float(Decimal(end_ns) / Decimal(1_000_000_000))
    return result


def _normalize_terminal_replay(record: Mapping[str, object]) -> dict[str, object]:
    run_id = _require_nonempty_text(record, "run_id")
    window_id = _require_nonempty_text(record, "window_id")
    arm = _require_nonempty_text(record, "arm")
    if arm not in REQUIRED_ARMS + (ARM_D,):
        raise EvaluationContractError(f"unrecognized P07 arm: {arm}")
    replay_index = _require_replay_index(record)
    if not _require_bool(record, "algorithmic_slot"):
        raise EvaluationContractError(
            f"{run_id} is an infrastructure attempt, not an algorithmic replay slot"
        )
    if not _require_bool(record, "terminal"):
        raise EvaluationContractError(f"{run_id} is not terminal")
    classification = record.get("classification")
    if not isinstance(classification, Mapping):
        raise EvaluationContractError(f"{run_id} has no frozen failure classification")
    if classification.get("schema_version") != SCHEMA_VERSION:
        raise EvaluationContractError(f"{run_id} classification schema mismatch")
    if classification.get("run_id") != run_id or classification.get("window_id") != window_id:
        raise EvaluationContractError(f"{run_id} classification identity mismatch")
    if classification.get("arm") != arm or classification.get("replay_index") != replay_index:
        raise EvaluationContractError(f"{run_id} classification slot mismatch")
    if classification.get("algorithmic_slot") is not True:
        raise EvaluationContractError(f"{run_id} classification is not algorithmic")
    classification_status = classification.get("classification_status")
    if classification_status not in ("EVALUABLE", "HARD_FAILURE"):
        raise EvaluationContractError(
            f"{run_id} classification is not terminal-complete: {classification_status}"
        )
    trajectory_path = record.get("trajectory_path")
    config_path = record.get("config_path")
    # A terminal hard failure may have no trajectory.  The plan retains the
    # slot and lets the failure classifier suppress numeric evaluation.
    if trajectory_path is not None and (not isinstance(trajectory_path, str) or not trajectory_path):
        raise EvaluationContractError("trajectory_path must be null or non-empty")
    if config_path is not None and (not isinstance(config_path, str) or not config_path):
        raise EvaluationContractError("config_path must be null or non-empty")
    time_offset = _finite_number(record.get("arm_time_offset_s", 0.0))
    if time_offset is None:
        raise EvaluationContractError("arm_time_offset_s must be finite")
    if classification_status == "EVALUABLE" and (not trajectory_path or not config_path):
        raise EvaluationContractError(
            f"{run_id} is evaluable but lacks trajectory_path or config_path"
        )
    failure_evidence_path = record.get("failure_evidence_path")
    if not isinstance(failure_evidence_path, str) or not failure_evidence_path:
        raise EvaluationContractError("failure_evidence_path must be non-empty")
    return {
        "run_id": run_id,
        "window_id": window_id,
        "arm": arm,
        "replay_index": replay_index,
        "trajectory_path": trajectory_path,
        "config_path": config_path,
        "failure_evidence_path": failure_evidence_path,
        "classification": dict(classification),
        "arm_time_offset_s": time_offset,
        "reference": _reference_contract(record),
        "evaluator_profile_id": _require_nonempty_text(record, "evaluator_profile_id"),
        "evaluator_protocol_sha256": _validate_sha256(
            record.get("evaluator_protocol_sha256"), "evaluator_protocol_sha256"
        ),
        "evaluator_script_sha256": _validate_sha256(
            record.get("evaluator_script_sha256"), "evaluator_script_sha256"
        ),
    }


def _job_input(record: Mapping[str, object]) -> dict[str, object]:
    return {
        key: record[key]
        for key in (
            "run_id",
            "arm",
            "replay_index",
            "trajectory_path",
            "config_path",
            "failure_evidence_path",
            "arm_time_offset_s",
            "classification",
        )
    }


def _evaluation_disposition(inputs: Mapping[str, Mapping[str, object]]) -> str:
    statuses = {
        str(value["classification"]["classification_status"])
        for value in inputs.values()
    }
    if statuses == {"EVALUABLE"}:
        return "EVALUATE_NUMERIC"
    if statuses.issubset({"EVALUABLE", "HARD_FAILURE"}) and "HARD_FAILURE" in statuses:
        return "SKIP_NUMERIC_HARD_FAILURE"
    raise EvaluationContractError(f"invalid evaluation input statuses: {sorted(statuses)}")


def build_evaluation_plan(
    terminal_replays: Iterable[Mapping[str, object]],
    *,
    d_applicability: Mapping[str, bool],
    output_root: str = "p07_backend_evaluations",
) -> list[dict[str, object]]:
    """Build an in-memory evaluation plan without reading any run artifact.

    Pairwise jobs always pair equal replay indices.  B0 is intentionally kept
    on a single-arm descriptive route and is never emitted as a comparator.
    """

    output_path = PurePosixPath(output_root)
    if (
        not output_root
        or output_path.is_absolute()
        or ".." in output_path.parts
        or "." in output_path.parts
    ):
        raise EvaluationContractError("output_root must be a non-empty relative path")
    records = [_normalize_terminal_replay(record) for record in terminal_replays]
    grouped: dict[str, dict[str, dict[int, dict[str, object]]]] = defaultdict(
        lambda: defaultdict(dict)
    )
    for record in records:
        window_id = str(record["window_id"])
        arm = str(record["arm"])
        replay_index = int(record["replay_index"])
        if replay_index in grouped[window_id][arm]:
            raise EvaluationContractError(
                f"duplicate terminal replay for {(window_id, arm, replay_index)}"
            )
        grouped[window_id][arm][replay_index] = record

    if set(grouped) != set(d_applicability):
        raise EvaluationContractError(
            "d_applicability keys must exactly match terminal replay window_ids"
        )

    jobs: list[dict[str, object]] = []
    for window_id in sorted(grouped):
        arms = grouped[window_id]
        d_is_applicable = d_applicability[window_id]
        if type(d_is_applicable) is not bool:
            raise EvaluationContractError("D applicability values must be booleans")
        expected_arms = set(REQUIRED_ARMS) | ({ARM_D} if d_is_applicable else set())
        if set(arms) != expected_arms:
            raise EvaluationContractError(
                f"{window_id} arms {sorted(arms)} do not match expected {sorted(expected_arms)}"
            )
        for arm, by_repeat in arms.items():
            if set(by_repeat) != REPLAY_INDICES:
                raise EvaluationContractError(
                    f"{window_id}/{arm} must contain exactly replay indices 1,2,3"
                )

        flat = [record for by_repeat in arms.values() for record in by_repeat.values()]
        invariant_keys = (
            "reference",
            "evaluator_profile_id",
            "evaluator_protocol_sha256",
            "evaluator_script_sha256",
        )
        for key in invariant_keys:
            if any(record[key] != flat[0][key] for record in flat[1:]):
                raise EvaluationContractError(f"{window_id} has mixed {key} values")

        common = flat[0]
        for replay_index in sorted(REPLAY_INDICES):
            b0 = arms[ARM_B0][replay_index]
            b0_inputs = {ARM_B0: _job_input(b0)}
            jobs.append(
                {
                    "schema_version": SCHEMA_VERSION,
                    "job_id": f"{window_id}_r{replay_index}_b0_descriptive",
                    "window_id": window_id,
                    "replay_index": replay_index,
                    "route": ROUTE_B0_DESCRIPTIVE,
                    "metric_role": B0_METRIC_ROLE,
                    "contrast_name": "B0_DESCRIPTIVE",
                    "arms": b0_inputs,
                    "evaluation_disposition": _evaluation_disposition(b0_inputs),
                    "reference": common["reference"],
                    "evaluator_profile_id": common["evaluator_profile_id"],
                    "evaluator_protocol_sha256": common["evaluator_protocol_sha256"],
                    "evaluator_script_sha256": common["evaluator_script_sha256"],
                    "output_dir": f"{output_root}/{window_id}/r{replay_index}/b0_descriptive",
                }
            )
            for comparator in PAIRWISE_COMPARATORS:
                if comparator == ARM_D and not d_is_applicable:
                    continue
                proposed = arms[ARM_P][replay_index]
                control = arms[comparator][replay_index]
                short = {ARM_B1: "b1", ARM_M: "m", ARM_D: "d"}[comparator]
                pair_inputs = {
                    comparator: _job_input(control),
                    ARM_P: _job_input(proposed),
                }
                jobs.append(
                    {
                        "schema_version": SCHEMA_VERSION,
                        "job_id": f"{window_id}_r{replay_index}_p_vs_{short}",
                        "window_id": window_id,
                        "replay_index": replay_index,
                        "route": ROUTE_PAIRWISE_COMMON_SUPPORT,
                        "metric_role": PAIRWISE_METRIC_ROLE,
                        "contrast_name": f"P_vs_{short.upper()}",
                        "proposed_arm": ARM_P,
                        "comparator_arm": comparator,
                        "arms": pair_inputs,
                        "evaluation_disposition": _evaluation_disposition(pair_inputs),
                        "reference": common["reference"],
                        "evaluator_profile_id": common["evaluator_profile_id"],
                        "evaluator_protocol_sha256": common[
                            "evaluator_protocol_sha256"
                        ],
                        "evaluator_script_sha256": common["evaluator_script_sha256"],
                        "output_dir": f"{output_root}/{window_id}/r{replay_index}/p_vs_{short}",
                    }
                )
    job_ids = [str(job["job_id"]) for job in jobs]
    if len(job_ids) != len(set(job_ids)):
        raise AssertionError("internal error: duplicate evaluation job_id")
    return jobs


def validate_evaluation_job(
    job: Mapping[str, object], *, require_executable: bool = False
) -> None:
    if job.get("schema_version") != SCHEMA_VERSION:
        raise EvaluationContractError("unsupported evaluation job schema_version")
    window_id = _require_nonempty_text(job, "window_id")
    _require_nonempty_text(job, "job_id")
    output_dir = _require_nonempty_text(job, "output_dir")
    output_path = PurePosixPath(output_dir)
    if output_path.is_absolute() or ".." in output_path.parts or "." in output_path.parts:
        raise EvaluationContractError("job output_dir must be a safe relative path")
    route = job.get("route")
    arms = job.get("arms")
    if not isinstance(arms, Mapping):
        raise EvaluationContractError("job arms must be an object")
    arm_names = set(arms)
    if route == ROUTE_B0_DESCRIPTIVE:
        if arm_names != {ARM_B0} or job.get("metric_role") != B0_METRIC_ROLE:
            raise EvaluationContractError("B0 descriptive route must contain only B0")
        if "proposed_arm" in job or "comparator_arm" in job:
            raise EvaluationContractError("B0 descriptive route cannot define a contrast")
    elif route == ROUTE_PAIRWISE_COMMON_SUPPORT:
        comparator = job.get("comparator_arm")
        if comparator not in PAIRWISE_COMPARATORS:
            raise EvaluationContractError("invalid pairwise comparator")
        if job.get("proposed_arm") != ARM_P:
            raise EvaluationContractError("pairwise proposed arm must be frozen P")
        if arm_names != {ARM_P, comparator}:
            raise EvaluationContractError("pairwise route must contain P and one comparator")
        if job.get("metric_role") != PAIRWISE_METRIC_ROLE:
            raise EvaluationContractError("invalid pairwise metric role")
    else:
        raise EvaluationContractError(f"unsupported evaluation route: {route!r}")
    replay_index = _require_replay_index(job)
    input_statuses: set[str] = set()
    for arm_name, raw in arms.items():
        if not isinstance(raw, Mapping):
            raise EvaluationContractError(f"job input {arm_name} must be an object")
        if raw.get("arm") != arm_name or raw.get("replay_index") != replay_index:
            raise EvaluationContractError("job inputs must use the job replay_index")
        _require_nonempty_text(raw, "run_id")
        classification = raw.get("classification")
        if not isinstance(classification, Mapping):
            raise EvaluationContractError("job input lacks failure classification")
        status = classification.get("classification_status")
        if status not in ("EVALUABLE", "HARD_FAILURE"):
            raise EvaluationContractError("job input classification is not terminal-complete")
        input_statuses.add(str(status))
        if classification.get("run_id") != raw.get("run_id"):
            raise EvaluationContractError("job input classification identity mismatch")
        if (
            classification.get("window_id") != window_id
            or classification.get("arm") != arm_name
            or classification.get("replay_index") != replay_index
            or classification.get("algorithmic_slot") is not True
        ):
            raise EvaluationContractError("job input classification slot mismatch")
        if status == "EVALUABLE":
            _require_nonempty_text(raw, "trajectory_path")
            _require_nonempty_text(raw, "config_path")
    expected_disposition = (
        "EVALUATE_NUMERIC"
        if input_statuses == {"EVALUABLE"}
        else "SKIP_NUMERIC_HARD_FAILURE"
    )
    if job.get("evaluation_disposition") != expected_disposition:
        raise EvaluationContractError("evaluation disposition disagrees with classifications")
    if require_executable and expected_disposition != "EVALUATE_NUMERIC":
        raise EvaluationContractError("hard-failure job has no numeric G0 command")
    _reference_contract(job)
    _validate_sha256(job.get("evaluator_protocol_sha256"), "evaluator_protocol_sha256")
    _validate_sha256(job.get("evaluator_script_sha256"), "evaluator_script_sha256")


def materialize_reducer_records(
    job: Mapping[str, object], g0_summary: Mapping[str, object] | None
) -> list[dict[str, object]]:
    """Adapt one validated G0 job/summary into per-arm reducer records.

    A pairwise summary supplies the same contrast-specific support decision to
    both arms.  A hard-failure job supplies no numeric summary for either arm;
    the per-replay classifiers still preserve which side failed.
    """

    validate_evaluation_job(job)
    arms = job["arms"]
    assert isinstance(arms, Mapping)
    disposition = job["evaluation_disposition"]
    if disposition == "SKIP_NUMERIC_HARD_FAILURE":
        if g0_summary is not None:
            raise EvaluationContractError(
                "a hard-failure job must not attach a post-hoc numeric summary"
            )
        return [
            {
                "classification": raw["classification"],
                "route": job["route"],
                "contrast_name": job["contrast_name"],
                "evaluation": None,
                "evaluation_job_id": job["job_id"],
            }
            for raw in arms.values()
        ]

    if not isinstance(g0_summary, Mapping):
        raise EvaluationContractError("an executable job requires a G0 summary")
    support = g0_summary.get("support")
    metrics_by_arm = g0_summary.get("arms")
    protocol = g0_summary.get("protocol")
    if not isinstance(support, Mapping) or not isinstance(metrics_by_arm, Mapping):
        raise EvaluationContractError("G0 summary lacks support or arms")
    if not isinstance(protocol, Mapping):
        raise EvaluationContractError("G0 summary lacks protocol")
    if protocol.get("contrast_name") != job.get("contrast_name"):
        raise EvaluationContractError("G0 summary contrast_name differs from job")
    if set(metrics_by_arm) != set(arms):
        raise EvaluationContractError("G0 summary arm set differs from job")
    for key in ("rpe_valid", "ape_valid"):
        if type(support.get(key)) is not bool:
            raise EvaluationContractError(f"G0 support.{key} must be boolean")
    coverage = _finite_number(support.get("common_coverage"), minimum=0.0)
    if coverage is None or coverage > 1.0:
        raise EvaluationContractError("G0 common_coverage is invalid")

    records: list[dict[str, object]] = []
    for arm_name, raw in arms.items():
        assert isinstance(raw, Mapping)
        metrics = metrics_by_arm[arm_name]
        if not isinstance(metrics, Mapping):
            raise EvaluationContractError(f"G0 metrics for {arm_name} must be an object")
        rpe = metrics.get("rpe_rmse_m")
        ape = metrics.get("ape_rmse_m")
        if support["rpe_valid"] and _finite_number(rpe, minimum=0.0) is None:
            raise EvaluationContractError(f"valid G0 RPE lacks a finite metric for {arm_name}")
        if support["ape_valid"] and _finite_number(ape, minimum=0.0) is None:
            raise EvaluationContractError(f"valid G0 APE lacks a finite metric for {arm_name}")
        records.append(
            {
                "classification": raw["classification"],
                "route": job["route"],
                "contrast_name": job["contrast_name"],
                "evaluation_job_id": job["job_id"],
                "evaluation": {
                    "status": "COMPLETED",
                    "rpe_valid": support["rpe_valid"],
                    "rpe_rmse_m": rpe,
                    "ape_valid": support["ape_valid"],
                    "ape_rmse_m": ape,
                    "common_coverage": coverage,
                },
            }
        )
    return records


def classify_replay_evidence(evidence: Mapping[str, object]) -> dict[str, object]:
    """Classify one attempt under the frozen P07 failure taxonomy."""

    run_id = _require_nonempty_text(evidence, "run_id")
    window_id = _require_nonempty_text(evidence, "window_id")
    arm = _require_nonempty_text(evidence, "arm")
    if arm not in REQUIRED_ARMS + (ARM_D,):
        raise EvaluationContractError(f"unrecognized P07 arm: {arm}")
    replay_index = _require_replay_index(evidence)
    algorithmic_slot = _require_bool(evidence, "algorithmic_slot")

    raw_infrastructure = evidence.get("infrastructure_codes", [])
    if not isinstance(raw_infrastructure, Sequence) or isinstance(
        raw_infrastructure, (str, bytes)
    ):
        raise EvaluationContractError("infrastructure_codes must be a list")
    infrastructure = sorted(set(str(value) for value in raw_infrastructure))
    unknown = set(infrastructure) - INFRASTRUCTURE_CODES
    if unknown:
        raise EvaluationContractError(f"unknown infrastructure codes: {sorted(unknown)}")
    if infrastructure and algorithmic_slot:
        raise EvaluationContractError(
            "an infrastructure replacement attempt cannot occupy an algorithmic slot"
        )
    if not infrastructure and not algorithmic_slot:
        raise EvaluationContractError(
            "a non-algorithmic attempt requires infrastructure evidence"
        )

    process = evidence.get("process")
    trajectory = evidence.get("trajectory")
    initialization = evidence.get("initialization")
    support = evidence.get("support")
    if not isinstance(process, Mapping):
        raise EvaluationContractError("process evidence must be an object")
    if not isinstance(trajectory, Mapping):
        raise EvaluationContractError("trajectory evidence must be an object")
    if not isinstance(initialization, Mapping):
        raise EvaluationContractError("initialization evidence must be an object")
    if not isinstance(support, Mapping):
        raise EvaluationContractError("support evidence must be an object")

    incomplete: list[str] = []
    hard_codes: list[str] = []

    timed_out = process.get("timed_out")
    if type(timed_out) is not bool:
        incomplete.append("process.timed_out")
        timed_out = False
    if timed_out:
        hard_codes.append("TIMEOUT")

    exit_code = process.get("exit_code")
    if exit_code is None:
        if not timed_out:
            incomplete.append("process.exit_code")
    elif isinstance(exit_code, bool) or not isinstance(exit_code, int):
        incomplete.append("process.exit_code")
    elif exit_code != 0:
        hard_codes.append("NONZERO_EXIT")

    present = trajectory.get("present")
    if type(present) is not bool:
        incomplete.append("trajectory.present")
        present = False
    row_count = trajectory.get("row_count")
    if isinstance(row_count, bool) or not isinstance(row_count, int) or row_count < 0:
        incomplete.append("trajectory.row_count")
        row_count = 0
    if not present or row_count == 0:
        hard_codes.append("EMPTY_TRAJECTORY")
    if present and row_count > 0:
        finite = trajectory.get("finite")
        monotonic = trajectory.get("strictly_increasing")
        if type(finite) is not bool:
            incomplete.append("trajectory.finite")
        elif not finite:
            hard_codes.append("NONFINITE_TRAJECTORY")
        if type(monotonic) is not bool:
            incomplete.append("trajectory.strictly_increasing")
        elif not monotonic:
            hard_codes.append("NONMONOTONIC_TRAJECTORY")

        init_success = initialization.get("success")
        delay = _finite_number(initialization.get("first_output_delay_s"), minimum=0.0)
        if type(init_success) is not bool:
            incomplete.append("initialization.success")
        elif not init_success:
            hard_codes.append("INITIALIZATION_FAILURE")
        if delay is None:
            incomplete.append("initialization.first_output_delay_s")
        elif delay > INITIALIZATION_DEADLINE_S:
            hard_codes.append("INITIALIZATION_FAILURE")

        coverage = _finite_number(support.get("coverage_ratio"), minimum=0.0)
        if coverage is None or coverage > 1.0:
            incomplete.append("support.coverage_ratio")
        elif coverage < HARD_FAILURE_COVERAGE_BELOW:
            hard_codes.append("COVERAGE_BELOW_0P50")

    log_inspected = evidence.get("solver_log_inspected")
    log_text = evidence.get("solver_log_text")
    if type(log_inspected) is not bool or not log_inspected:
        incomplete.append("solver_log_inspected")
    if not isinstance(log_text, str):
        incomplete.append("solver_log_text")
        log_text = ""
    solver_codes = sorted(
        code
        for code, patterns in SOLVER_RISK_PATTERNS.items()
        if any(pattern.search(log_text) for pattern in patterns)
    )

    queue = evidence.get("queue", {})
    if not isinstance(queue, Mapping):
        raise EvaluationContractError("queue evidence must be an object")
    queue_status = queue.get("evidence_status")
    if queue_status is None and {
        "drop_rate",
        "backlog_growth_s",
    }.issubset(queue):
        # Backwards-compatible legacy fixture branch.  Presence of both
        # explicit values means measured; absence is never converted to zero.
        queue_status = "MEASURED"
    queue_risk_codes: list[str] = []
    if queue_status == "MEASURED":
        drop_rate = _finite_number(queue.get("drop_rate"), minimum=0.0)
        backlog_growth_s = _finite_number(
            queue.get("backlog_growth_s"), minimum=0.0
        )
        if drop_rate is None or drop_rate > 1.0:
            incomplete.append("queue.drop_rate")
        elif drop_rate > SUSTAINED_QUEUE_DROP_RATE_ABOVE:
            queue_risk_codes.append("SUSTAINED_QUEUE_DROP")
        if backlog_growth_s is None:
            incomplete.append("queue.backlog_growth_s")
        elif backlog_growth_s >= SUSTAINED_BACKLOG_GROWTH_S_AT_LEAST:
            queue_risk_codes.append("SUSTAINED_BACKLOG_GROWTH")
    elif queue_status == "NOT_INSTRUMENTED_NO_ZERO_IMPUTATION":
        # Queue risk is a diagnostic, not one of the preregistered hard-
        # failure codes.  Its complete absence therefore remains explicit
        # unknown without converting an otherwise complete replay into
        # INCOMPLETE_EVIDENCE.  Partial/pseudo-zero telemetry is forbidden.
        if queue.get("drop_rate") is not None or queue.get("backlog_growth_s") is not None:
            incomplete.append("queue.not_instrumented_values_must_be_null")
    else:
        incomplete.append("queue.evidence_status")

    ordered_hard_codes = [code for code in HARD_FAILURE_CODES if code in hard_codes]
    observed_hard = bool(ordered_hard_codes)
    if infrastructure:
        status = "INFRASTRUCTURE_REPLACEMENT_REQUIRED"
    elif incomplete:
        status = "INCOMPLETE_EVIDENCE"
    elif observed_hard:
        status = "HARD_FAILURE"
    else:
        status = "EVALUABLE"
    hard_for_analysis = bool(algorithmic_slot and observed_hard)
    return {
        "schema_version": SCHEMA_VERSION,
        "run_id": run_id,
        "window_id": window_id,
        "arm": arm,
        "replay_index": replay_index,
        "algorithmic_slot": algorithmic_slot,
        "classification_status": status,
        "incomplete_evidence_fields": sorted(set(incomplete)),
        "infrastructure_codes": infrastructure,
        "observed_hard_failure_codes": ordered_hard_codes,
        "hard_failure": hard_for_analysis,
        "solver_risk_codes": solver_codes,
        "solver_risk": bool(algorithmic_slot and solver_codes),
        "queue_evidence_status": queue_status,
        "queue_risk_codes": sorted(set(queue_risk_codes)),
        "numeric_evaluable_before_common_support": status == "EVALUABLE",
    }


def _median_or_none(values: Sequence[float], minimum_count: int = 2) -> float | None:
    return float(median(values)) if len(values) >= minimum_count else None


def reduce_window_arm_replays(
    replay_records: Sequence[Mapping[str, object]],
) -> dict[str, object]:
    """Reduce exactly three registered algorithmic replays for one window-arm."""

    if len(replay_records) != 3:
        raise EvaluationContractError("window-arm reduction requires exactly three records")
    normalized: list[tuple[Mapping[str, object], Mapping[str, object] | None]] = []
    identities: set[tuple[object, ...]] = set()
    indices: set[int] = set()
    for record in replay_records:
        classification = record.get("classification")
        if not isinstance(classification, Mapping):
            raise EvaluationContractError("each reducer record needs classification")
        if classification.get("schema_version") != SCHEMA_VERSION:
            raise EvaluationContractError("classification schema mismatch")
        if classification.get("algorithmic_slot") is not True:
            raise EvaluationContractError("infrastructure attempts cannot enter reduction")
        replay_index = _require_replay_index(classification)
        indices.add(replay_index)
        identity = (
            classification.get("window_id"),
            classification.get("arm"),
            record.get("route"),
            record.get("contrast_name"),
        )
        identities.add(identity)
        evaluation = record.get("evaluation")
        if evaluation is not None and not isinstance(evaluation, Mapping):
            raise EvaluationContractError("evaluation must be null or an object")
        normalized.append((classification, evaluation))
    if indices != REPLAY_INDICES:
        raise EvaluationContractError("reducer replay indices must be exactly 1,2,3")
    if len(identities) != 1:
        raise EvaluationContractError("reducer records must share window, arm, and route")

    identity = next(iter(identities))
    window_id, arm, route, contrast_name = identity
    if route not in (ROUTE_PAIRWISE_COMMON_SUPPORT, ROUTE_B0_DESCRIPTIVE):
        raise EvaluationContractError("unknown reducer route")
    if route == ROUTE_B0_DESCRIPTIVE and arm != ARM_B0:
        raise EvaluationContractError("B0 descriptive reduction must contain B0")
    if route == ROUTE_PAIRWISE_COMMON_SUPPORT and arm == ARM_B0:
        raise EvaluationContractError("B0 cannot enter pairwise common-support reduction")

    rpe_values: list[float] = []
    ape_values: list[float] = []
    coverage_values: list[float] = []
    evaluable_indices: list[int] = []
    support_insufficient_indices: list[int] = []
    for classification, evaluation in normalized:
        replay_index = int(classification["replay_index"])
        if evaluation is None or evaluation.get("status") != "COMPLETED":
            continue
        coverage = _finite_number(evaluation.get("common_coverage"), minimum=0.0)
        if coverage is not None and coverage <= 1.0:
            coverage_values.append(coverage)
        if not classification.get("numeric_evaluable_before_common_support"):
            continue
        if evaluation.get("rpe_valid") is not True:
            support_insufficient_indices.append(replay_index)
            continue
        rpe = _finite_number(evaluation.get("rpe_rmse_m"), minimum=0.0)
        if rpe is None:
            continue
        rpe_values.append(rpe)
        evaluable_indices.append(replay_index)
        if evaluation.get("ape_valid") is True:
            ape = _finite_number(evaluation.get("ape_rmse_m"), minimum=0.0)
            if ape is not None:
                ape_values.append(ape)

    classifications = [item[0] for item in normalized]
    hard_any = any(item.get("hard_failure") is True for item in classifications)
    solver_any = any(item.get("solver_risk") is True for item in classifications)
    rpe_median = _median_or_none(rpe_values, MINIMUM_EVALUABLE_REPLAYS)
    if rpe_median is None:
        status = "INCONCLUSIVE_FEWER_THAN_2_EVALUABLE_REPLAYS"
    elif len(rpe_values) == 3:
        status = "NUMERIC_3_OF_3"
    else:
        status = "NUMERIC_2_OF_3"
    return {
        "schema_version": SCHEMA_VERSION,
        "window_id": window_id,
        "arm": arm,
        "route": route,
        "contrast_name": contrast_name,
        "scientific_unit": "sequence_not_replay",
        "registered_algorithmic_replays": 3,
        "rpe_evaluable_count": len(rpe_values),
        "evaluable_replay_indices": sorted(evaluable_indices),
        "insufficient_common_support_replay_indices": sorted(
            support_insufficient_indices
        ),
        "rpe_rmse_median": rpe_median,
        "ape_evaluable_count": len(ape_values),
        "ape_rmse_median": _median_or_none(ape_values, MINIMUM_EVALUABLE_REPLAYS),
        "coverage_evaluable_count": len(coverage_values),
        "common_coverage_median": _median_or_none(
            coverage_values, MINIMUM_EVALUABLE_REPLAYS
        ),
        "hard_failure_any_of_three": hard_any,
        "hard_failure_codes": sorted(
            {
                code
                for item in classifications
                for code in item.get("observed_hard_failure_codes", [])
            }
        ),
        "solver_risk_any_of_three": solver_any,
        "solver_risk_codes": sorted(
            {
                code
                for item in classifications
                for code in item.get("solver_risk_codes", [])
            }
        ),
        "reduction_status": status,
    }


def reduce_pairwise_contrast(
    proposed: Mapping[str, object], comparator: Mapping[str, object]
) -> dict[str, object]:
    """Apply frozen P07 pairwise failure precedence and numeric effect rules."""

    if proposed.get("route") != ROUTE_PAIRWISE_COMMON_SUPPORT or comparator.get(
        "route"
    ) != ROUTE_PAIRWISE_COMMON_SUPPORT:
        raise EvaluationContractError("pairwise contrast requires pairwise summaries")
    if proposed.get("arm") != ARM_P:
        raise EvaluationContractError("proposed summary must be frozen P")
    if comparator.get("arm") not in PAIRWISE_COMPARATORS:
        raise EvaluationContractError("invalid comparator summary")
    for key in ("window_id", "contrast_name"):
        if proposed.get(key) != comparator.get(key):
            raise EvaluationContractError(f"pairwise summaries have different {key}")

    proposed_hard = proposed.get("hard_failure_any_of_three") is True
    comparator_hard = comparator.get("hard_failure_any_of_three") is True
    if proposed_hard and comparator_hard:
        status = "FAILURE_TIE"
    elif proposed_hard:
        status = "PROPOSED_ONLY_HARD_FAILURE_AUTOMATIC_LOSS"
    elif comparator_hard:
        status = "COMPARATOR_ONLY_HARD_FAILURE_PROPOSED_FAILURE_WIN"
    else:
        p_value = _finite_number(proposed.get("rpe_rmse_median"), minimum=0.0)
        c_value = _finite_number(comparator.get("rpe_rmse_median"), minimum=0.0)
        if p_value is None or c_value is None:
            status = "INCONCLUSIVE_PAIR"
        elif p_value <= 0.0 or c_value <= 0.0:
            status = "INCONCLUSIVE_NONPOSITIVE_RPE_FOR_LOG_EFFECT"
        else:
            status = "NUMERIC_PAIR"

    p_value = _finite_number(proposed.get("rpe_rmse_median"), minimum=0.0)
    c_value = _finite_number(comparator.get("rpe_rmse_median"), minimum=0.0)
    numeric_effect = status == "NUMERIC_PAIR" and p_value is not None and c_value is not None
    return {
        "schema_version": SCHEMA_VERSION,
        "window_id": proposed.get("window_id"),
        "contrast_name": proposed.get("contrast_name"),
        "proposed_arm": ARM_P,
        "comparator_arm": comparator.get("arm"),
        "pair_status": status,
        "retained_in_failure_denominator": True,
        "proposed_rpe_rmse_median": p_value,
        "comparator_rpe_rmse_median": c_value,
        "rpe_ratio_proposed_over_comparator": (
            p_value / c_value if numeric_effect and c_value and p_value is not None else None
        ),
        "rpe_improvement_fraction": (
            1.0 - p_value / c_value
            if numeric_effect and c_value and p_value is not None
            else None
        ),
        "log_rpe_ratio": (
            math.log(p_value / c_value)
            if numeric_effect and c_value and p_value is not None
            else None
        ),
    }


__all__ = [
    "ARM_B0",
    "ARM_B1",
    "ARM_D",
    "ARM_M",
    "ARM_P",
    "B0_METRIC_ROLE",
    "EvaluationContractError",
    "HARD_FAILURE_CODES",
    "PAIRWISE_METRIC_ROLE",
    "ROUTE_B0_DESCRIPTIVE",
    "ROUTE_PAIRWISE_COMMON_SUPPORT",
    "SCHEMA_VERSION",
    "build_evaluation_plan",
    "classify_replay_evidence",
    "materialize_reducer_records",
    "reduce_pairwise_contrast",
    "reduce_window_arm_replays",
    "validate_evaluation_job",
]
