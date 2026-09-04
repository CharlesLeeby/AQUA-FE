#!/usr/bin/env python3
"""Validate the P03 candidate evidence bundle without running experiments.

The validator is intentionally a *candidate-bundle* check.  A successful run
means that the checked documents and development artifacts are internally
consistent; it does not promote P03, authorize a confirmatory claim, or
replace the P03A/P03B/P06 gates.

Only the Python standard library is used for orchestration, hashing, CSV and
JSON checks.  The existing failure classifier is imported for the taxonomy
contract check (and therefore uses the project's already pinned YAML parser).
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import re
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple


ROOT = Path(__file__).resolve().parents[1]
BUNDLE = ROOT / "papers/ieee_sensors_journal_experiments"
DEFAULT_LOCK = BUNDLE / "method_lock_candidate.json"
DEFAULT_PROTOCOL = BUNDLE / "protocol_v1_candidate.md"
DEFAULT_TAXONOMY = BUNDLE / "failure_taxonomy_v1.yaml"
DEFAULT_MASTER = BUNDLE / "p03/smoke_a06_learned_v3/master_stream.jsonl"
DEFAULT_SHADOW = BUNDLE / "p03/smoke_a06_learned_v3/shadow_rankings.csv"
DEFAULT_REPORT = BUNDLE / "p03/p03_candidate_bundle_validation.json"

# ``python scripts/validate_p03_candidate_bundle.py`` puts ``scripts/`` first
# on sys.path.  The production modules live at the workspace root, so make
# the import boundary explicit for both direct invocation and unit tests.
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

HEX64 = re.compile(r"^[0-9a-f]{64}$")


class BundleValidationError(ValueError):
    """Raised for a contract violation in a candidate artifact."""


@dataclass(frozen=True)
class CheckResult:
    name: str
    status: str
    detail: Dict[str, Any]

    def as_dict(self) -> Dict[str, Any]:
        return {"name": self.name, "status": self.status, "detail": self.detail}


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--method-lock", default=str(DEFAULT_LOCK))
    parser.add_argument("--protocol", default=str(DEFAULT_PROTOCOL))
    parser.add_argument("--taxonomy", default=str(DEFAULT_TAXONOMY))
    parser.add_argument("--master-stream", default=str(DEFAULT_MASTER))
    parser.add_argument("--shadow-csv", default=str(DEFAULT_SHADOW))
    parser.add_argument("--report", default=str(DEFAULT_REPORT))
    parser.add_argument(
        "--skip-contract-tests",
        action="store_true",
        help="skip subprocess unit/selftests (the report is then PARTIAL)",
    )
    args = parser.parse_args(argv)

    results: List[CheckResult] = []
    parsed_events: List[Any] = []

    def run_check(name: str, fn: Callable[[], Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        try:
            detail = fn()
        except Exception as exc:  # keep the report complete after one failure
            results.append(
                CheckResult(
                    name=name,
                    status="FAIL",
                    detail={"error": f"{type(exc).__name__}: {exc}"},
                )
            )
            return None
        results.append(CheckResult(name=name, status="PASS", detail=detail))
        return detail

    protocol_detail = run_check(
        "protocol_required_tokens",
        lambda: validate_protocol(Path(args.protocol)),
    )
    lock_detail = run_check(
        "method_lock_artifact_hash_integrity",
        lambda: validate_method_lock(Path(args.method_lock)),
    )
    run_check(
        "failure_taxonomy_classifier_contract",
        lambda: validate_failure_taxonomy(Path(args.taxonomy)),
    )
    master_detail = run_check(
        "smoke_a06_learned_v3_master_chain",
        lambda: validate_master_stream(Path(args.master_stream), parsed_events),
    )
    if master_detail is not None:
        run_check(
            "shadow_csv_schema_and_master_alignment",
            lambda: validate_shadow_csv(Path(args.shadow_csv), parsed_events),
        )
    else:
        results.append(
            CheckResult(
                name="shadow_csv_schema_and_master_alignment",
                status="FAIL",
                detail={"error": "master stream check failed; alignment cannot be established"},
            )
        )
    run_check(
        "development_confirmatory_claim_boundary",
        lambda: validate_claim_boundary(Path(args.protocol), Path(args.method_lock), BUNDLE),
    )

    if args.skip_contract_tests:
        results.append(
            CheckResult(
                name="related_unit_and_selftests",
                status="SKIP",
                detail={"reason": "--skip-contract-tests"},
            )
        )
    else:
        run_check("related_unit_and_selftests", run_related_tests)

    statuses = [result.status for result in results]
    overall = "PASS" if statuses and all(status == "PASS" for status in statuses) else "FAIL"
    if args.skip_contract_tests and overall == "PASS":
        overall = "PARTIAL"

    # Preserve the lock's declared blockers even when the integrity check
    # itself fails (for example, while a parallel agent is rebuilding a
    # frozen source snapshot).  This keeps the report actionable instead of
    # replacing the known blockers with a generic parse error.
    declared_blockers: List[str] = []
    try:
        raw_lock_for_report = _read_json(Path(args.method_lock))
        declared_blockers = [str(item) for item in raw_lock_for_report.get("blockers", [])]
    except Exception:
        pass

    # This explicit state is part of the report so a green bundle check cannot
    # be mistaken for a stage transition or a confirmatory result.
    report: Dict[str, Any] = {
        "schema_version": "isj-p03-candidate-bundle-validation-v1",
        "validation_status": overall,
        "stage": "P03",
        "stage_status": "IN_PROGRESS",
        "candidate_bundle_pass": overall == "PASS",
        "p03_pass_authorized": False,
        "confirmatory_claim_authorized": False,
        "generated_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "inputs": {
            "method_lock": _display_path(Path(args.method_lock)),
            "protocol": _display_path(Path(args.protocol)),
            "failure_taxonomy": _display_path(Path(args.taxonomy)),
            "master_stream": _display_path(Path(args.master_stream)),
            "shadow_csv": _display_path(Path(args.shadow_csv)),
        },
        "checks": [result.as_dict() for result in results],
        "residual_blockers": (
            (lock_detail or {}).get("blockers", [])
            if lock_detail is not None
            else (declared_blockers or ["method lock did not validate; inspect the check error"])
        ),
        "notes": [
            "Development smoke and historical VINS numbers remain development-only.",
            "A PASS here validates the candidate bundle only; it does not append a ledger event.",
        ],
    }
    report_path = Path(args.report)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, sort_keys=True, indent=2) + "\n", encoding="utf-8")

    print(
        f"P03_CANDIDATE_BUNDLE_{overall} checks={len(results)} "
        "stage=P03_IN_PROGRESS confirmatory_claims=FORBIDDEN"
    )
    print(f"wrote {report_path}")
    return 0 if overall in {"PASS", "PARTIAL"} else 1


def validate_protocol(path: Path) -> Dict[str, Any]:
    text = _read_text(path)
    # These are deliberately contract phrases rather than a broad prose
    # linter.  They cover identity, fairness, score, geometry, budget,
    # matching, replay reduction and the stage boundary.
    required = {
        "candidate_identity": "isj-core-method-candidate-v1",
        "candidate_status": "CANDIDATE_P03",
        "multi_sequence_route": "MULTI_SEQUENCE_CANDIDATE",
        "claim_disclaimer": "No number in this document is a confirmatory",
        "master_stream": "same master stream and the same maximum budget",
        "dose_matching": ("admission-count-matched", "at each common event", "first `n_t` entries"),
        "k0_l_e_contract": "K_t^0",
        "budget_active": "B_active=8",
        "total_feature_cap": "total exported-feature cap is 350",
        "base_export_cap": "reserves 342 slots",
        "min_gain": "min_gain=0.001",
        "no_valid_base_model": "NO_VALID_BASE_MODEL",
        "reliability_horizon": "h=5",
        "reliability_alpha": "alpha=0.10",
        "f_threshold": "F uses a 2.5 px threshold",
        "h_threshold": "H uses a 5.0 px threshold",
        "failure_reducer": ("median of at least 2 of 3", "2/3 algorithmic replays are evaluable", "median of evaluable replays"),
        "any_repeat": "any_repeat_hard_failure",
        "cqg_independent": "independent classical GFTT pool",
        "cqg_outcome_blind": "trajectory-outcome-blind",
        "cqg_not_causal": ("not a randomized, unconditional, or causal control", "randomized, unconditional, or causal control"),
        "stage_boundary": "stage P03 `IN_PROGRESS`",
        "no_confirmatory_result": "no held-out or confirmatory learned/VINS result is claimed",
    }
    missing = [
        name
        for name, token in required.items()
        if not any(candidate in text for candidate in (token if isinstance(token, tuple) else (token,)))
    ]
    if missing:
        raise BundleValidationError("protocol missing required tokens: " + ", ".join(missing))
    return {
        "path": _display_path(path),
        "required_token_count": len(required),
        "tokens_checked": sorted(required),
        "status_token": "CANDIDATE_P03",
        "route_token": "MULTI_SEQUENCE_CANDIDATE",
    }


def validate_method_lock(path: Path) -> Dict[str, Any]:
    data = _read_json(path)
    if data.get("schema_version") != "isj-method-lock-candidate-v1":
        raise BundleValidationError("method lock schema mismatch")
    if data.get("status") != "P03_CANDIDATE_NOT_CANONICAL":
        raise BundleValidationError("method lock must remain a non-canonical P03 candidate")
    if data.get("protocol_version") != "isj-core-method-candidate-v1":
        raise BundleValidationError("method lock protocol version mismatch")
    if data.get("route") != "MULTI_SEQUENCE_CANDIDATE":
        raise BundleValidationError("method lock route mismatch")

    artifacts = list(data.get("artifacts", []))
    smoke = list(data.get("development_smoke_artifacts", []))
    if not artifacts or not smoke:
        raise BundleValidationError("method lock artifact lists must be non-empty")
    records = artifacts + smoke
    paths = [str(record.get("path")) for record in records]
    if len(paths) != len(set(paths)):
        raise BundleValidationError("method lock contains duplicate artifact paths")
    for record in records:
        _validate_record(record)
        if record.get("status") != "PRESENT":
            raise BundleValidationError(f"artifact is not present: {record.get('path')}")
        target = _record_target(str(record["path"]))
        if not target.is_file():
            raise BundleValidationError(f"artifact path disappeared: {record['path']}")
        actual_size = target.stat().st_size
        actual_hash = sha256_file(target)
        if int(record.get("size_bytes", -1)) != actual_size or record.get("sha256") != actual_hash:
            raise BundleValidationError(f"artifact hash/size mismatch: {record['path']}")

    missing = list(data.get("missing_artifacts", []))
    if missing:
        raise BundleValidationError("method lock reports missing artifacts: " + ", ".join(map(str, missing)))
    required_paths = {
        "papers/ieee_sensors_journal_experiments/protocol_v1_candidate.md",
        "papers/ieee_sensors_journal_experiments/failure_taxonomy_v1.yaml",
        "papers/ieee_sensors_journal_experiments/environment_manifest.txt",
        "uw_frontend/geometry/master_candidate_stream.py",
        "uw_frontend/geometry/fh_residuals.py",
        "uw_frontend/quality/temporal_reliability.py",
        "uw_frontend/evaluation/failure_classifier.py",
        "scripts/export_p03_master_stream.py",
        "scripts/replay_p03_shadow.py",
    }
    listed = set(paths)
    absent_required = sorted(required_paths - listed)
    if absent_required:
        raise BundleValidationError("method lock omitted required artifacts: " + ", ".join(absent_required))

    for record in smoke:
        if record.get("role") != "development_smoke_artifact":
            raise BundleValidationError(f"smoke artifact role mismatch: {record['path']}")
        if "p03/smoke_" not in str(record["path"]):
            raise BundleValidationError(f"non-smoke path in smoke artifact list: {record['path']}")

    _validate_vins_records(data)
    contract = data.get("shared_contract")
    if not isinstance(contract, Mapping):
        raise BundleValidationError("shared_contract must be an object")
    exact_contract = {
        "b_active": 8,
        "total_feature_cap": 350,
        "base_export_cap": 342,
        "backend_q_external_arms": 1.0,
        "fh_seed": 20260730,
        "reliability_horizon_frames": 5,
        "reliability_alpha": 0.10,
        "selector_min_gain": 0.001,
        "selector_random_seed": 20260730,
    }
    for key, expected in exact_contract.items():
        if contract.get(key) != expected:
            raise BundleValidationError(f"shared_contract drift: {key}={contract.get(key)!r}")
    thresholds = contract.get("fh_thresholds_px")
    if thresholds != {"F": 2.5, "H": 5.0}:
        raise BundleValidationError("F/H threshold contract drift")
    if contract.get("master_stream_schema") != "isj-master-candidate-stream-v1":
        raise BundleValidationError("master stream schema contract drift")
    if "median_of_at_least_2_of_3" not in str(contract.get("replay_reducer")):
        raise BundleValidationError("replay reducer contract drift")

    calibration = data.get("calibration")
    if not isinstance(calibration, Mapping) or calibration.get("status") != "PROVISIONAL_DEVELOPMENT_ONLY":
        raise BundleValidationError("calibration must remain provisional development-only")
    if calibration.get("smoke_rows_are_not_frozen") is not True:
        raise BundleValidationError("smoke calibration rows must not be marked frozen")
    if list(calibration.get("required_source_groups", [])) != ["klt", "learned", "classical"]:
        raise BundleValidationError("calibration source-group contract drift")
    environment = data.get("environment")
    if not isinstance(environment, Mapping) or environment.get("real_time_claim_authorized") is not False:
        raise BundleValidationError("real-time claim must remain unauthorized")

    blockers = list(data.get("blockers", []))
    blocker_text = " ".join(str(item).lower() for item in blockers)
    for marker in ("canonical", "calibration", "p95", "c-qg"):
        if marker not in blocker_text:
            raise BundleValidationError(f"method lock blocker list missing marker: {marker}")

    expected_hash = payload_hash(data)
    if data.get("candidate_lock_hash") != expected_hash:
        raise BundleValidationError("candidate_lock_hash mismatch")
    return {
        "path": _display_path(path),
        "artifact_count": len(artifacts),
        "development_smoke_artifact_count": len(smoke),
        "vins_source_tree_verified": True,
        "candidate_lock_hash": expected_hash,
        "shared_contract": {
            key: contract[key]
            for key in ("b_active", "total_feature_cap", "base_export_cap", "selector_min_gain")
        },
        "blockers": blockers,
    }


def validate_failure_taxonomy(path: Path) -> Dict[str, Any]:
    raw = _read_yaml(path)
    if raw.get("schema_version") != "isj-failure-taxonomy-v1":
        raise BundleValidationError("failure taxonomy schema mismatch")
    if raw.get("status") != "FROZEN_CANDIDATE_P03":
        raise BundleValidationError("failure taxonomy status must be FROZEN_CANDIDATE_P03")
    thresholds = raw.get("thresholds")
    if not isinstance(thresholds, Mapping):
        raise BundleValidationError("failure taxonomy thresholds missing")
    exact_thresholds = {
        "initialization_deadline_s": 10.0,
        "output_segment_max_gap_s": 1.0,
        "hard_failure_coverage_below": 0.50,
        "sustained_queue_drop_rate_above": 0.01,
        "sustained_backlog_growth_s_at_least": 5.0,
        "planned_algorithmic_replays": 3,
        "minimum_evaluable_replays": 2,
    }
    for key, expected in exact_thresholds.items():
        if thresholds.get(key) != expected:
            raise BundleValidationError(f"failure threshold drift: {key}")
    hard_reasons = list(raw.get("replay_hard_failure_any", []))
    expected_reasons = {
        "NONZERO_EXIT",
        "TIMEOUT",
        "EMPTY_TRAJECTORY",
        "NONFINITE_TRAJECTORY",
        "NONMONOTONIC_TRAJECTORY",
        "INITIALIZATION_FAILURE",
        "COVERAGE_BELOW_0P50",
    }
    if set(hard_reasons) != expected_reasons:
        raise BundleValidationError("replay hard-failure vocabulary drift")
    reducer = raw.get("reducer")
    if not isinstance(reducer, Mapping):
        raise BundleValidationError("failure reducer missing")
    for key, expected in {
        "unit": "window_x_arm",
        "evaluable_gate": "at_least_2_of_3",
        "numeric_reducer": "median_over_evaluable_replays",
        "any_repeat_hard_failure": "any_of_3",
        "window_arm_solver_risk": "any_of_3",
    }.items():
        if reducer.get(key) != expected:
            raise BundleValidationError(f"failure reducer drift: {key}")
    if reducer.get("preserve_evaluable_count") is not True:
        raise BundleValidationError("failure reducer must preserve evaluable count")

    # Parse through the production classifier and exercise each contract class
    # with tiny deterministic evidence.  This catches a YAML file that looks
    # plausible but is not consumable by the actual reducer.
    from uw_frontend.evaluation.failure_classifier import FailureTaxonomy, ReplayEvidence

    taxonomy = FailureTaxonomy.from_yaml(path)

    def evidence(**overrides: Any) -> ReplayEvidence:
        values: Dict[str, Any] = {
            "process_exit_code": 0,
            "timed_out": False,
            "window_start_s": 0.0,
            "window_end_s": 20.0,
            "trajectory_timestamps_s": [float(i) for i in range(21)],
            "trajectory_rows_finite": [True] * 21,
            "log_text": "",
            "input_message_count": 100,
            "processed_message_count": 100,
            "observable_backlog_growth_s": 0.0,
            "infrastructure_evidence": (),
        }
        values.update(overrides)
        return ReplayEvidence(**values)

    good = taxonomy.classify(evidence())
    if not good.replay_evaluable or good.replay_hard_failure:
        raise BundleValidationError("classifier rejected a valid replay probe")
    hard = taxonomy.classify(evidence(process_exit_code=9))
    if "NONZERO_EXIT" not in hard.hard_failure_reasons or hard.replay_evaluable:
        raise BundleValidationError("classifier hard-failure probe failed")
    risky = taxonomy.classify(evidence(log_text="failure detection!"))
    if not risky.solver_risk or risky.replay_hard_failure:
        raise BundleValidationError("solver-risk probe failed")
    reduced = taxonomy.reduce_window_arm(
        [good, risky, good],
        [{"ape_rmse_m": 1.0}, {"ape_rmse_m": 100.0}, {"ape_rmse_m": 3.0}],
    )
    if reduced.evaluable_replays != 3 or reduced.window_arm_solver_risk is not True:
        raise BundleValidationError("three-replay reducer probe failed")
    dropped = taxonomy.classify(evidence(processed_message_count=98))
    if not dropped.sustained_queue_drop:
        raise BundleValidationError("queue-drop probe failed")
    return {
        "path": _display_path(path),
        "schema_version": raw["schema_version"],
        "hard_failure_reason_count": len(hard_reasons),
        "solver_signature_groups": sorted(raw.get("solver_risk_signatures", {})),
        "classifier_probe": "valid/hard/solver-risk/queue-drop/reducer PASS",
    }


def validate_master_stream(path: Path, events_out: Optional[List[Any]] = None) -> Dict[str, Any]:
    from uw_frontend.geometry.master_candidate_stream import (
        MasterStreamValidator,
        master_event_from_dict,
    )

    lines = path.read_text(encoding="utf-8").splitlines()
    if not lines:
        raise BundleValidationError("master stream is empty")
    validator = MasterStreamValidator()
    events: List[Any] = []
    for line_number, line in enumerate(lines, start=1):
        if not line.strip():
            raise BundleValidationError(f"blank master stream line {line_number}")
        try:
            event = master_event_from_dict(json.loads(line))
            validator.push(event)
        except Exception as exc:
            raise BundleValidationError(f"master stream line {line_number}: {exc}")
        events.append(event)
    if len(events) != 20:
        raise BundleValidationError(f"A06 learned v3 smoke must contain 20 events, got {len(events)}")
    if "smoke" not in events[0].sequence_id.lower() or "a06" not in events[0].sequence_id.lower():
        raise BundleValidationError("master stream sequence is not the A06 development smoke")
    if events[0].previous_master_hash:
        raise BundleValidationError("first master event must have an empty predecessor hash")
    learned_count = sum(len(event.live_learned) for event in events)
    classical_count = sum(len(event.live_classical) for event in events)
    if learned_count <= 0 or classical_count <= 0:
        raise BundleValidationError("v3 smoke must exercise learned and classical live pools")
    if events_out is not None:
        events_out.extend(events)
    return {
        "path": _display_path(path),
        "event_count": len(events),
        "sequence_id": events[0].sequence_id,
        "first_master_hash": events[0].master_pool_hash,
        "final_master_hash": events[-1].master_pool_hash,
        "learned_live_rows": learned_count,
        "classical_live_rows": classical_count,
        "chain": "predecessor/hash/retirement PASS",
    }


def validate_shadow_csv(path: Path, events: Sequence[Any]) -> Dict[str, Any]:
    required = {
        "event_index",
        "frame_index",
        "timestamp_s",
        "master_pool_hash",
        "candidate_pool_hash",
        "selector_config_hash",
        "n_eligible",
        "n_active_before",
        "n_t_qg",
        "overlap_h_qg",
        "overlap_r_qg",
        "overlap_q_qg",
        "overlap_g_qg",
        "h_topn",
        "r_topn",
        "q_topn",
        "g_topn",
        "qg_topn",
        "h_order",
        "qg_order",
        "selection_kernel_ms",
        "selection_active",
    }
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        fields = reader.fieldnames or []
        if len(fields) != len(set(fields)):
            raise BundleValidationError("shadow CSV header contains duplicate columns")
        missing = sorted(required - set(fields))
        if missing:
            raise BundleValidationError("shadow CSV missing columns: " + ", ".join(missing))
        rows = list(reader)
    if len(rows) != len(events):
        raise BundleValidationError(f"shadow/master row count mismatch: {len(rows)} != {len(events)}")
    active_events = 0
    selector_hashes: set = set()
    for index, (row, event) in enumerate(zip(rows, events)):
        try:
            if int(row["event_index"]) != index or int(row["frame_index"]) != event.frame_index:
                raise ValueError("event/frame index mismatch")
            if not math.isclose(float(row["timestamp_s"]), event.timestamp_s, rel_tol=0.0, abs_tol=1e-9):
                raise ValueError("timestamp mismatch")
            if row["master_pool_hash"] != event.master_pool_hash:
                raise ValueError("master_pool_hash mismatch")
            if row["candidate_pool_hash"] != row["master_pool_hash"]:
                raise ValueError("candidate_pool_hash must equal the learned master pool hash")
            if not HEX64.fullmatch(row["master_pool_hash"]):
                raise ValueError("invalid master hash")
            if not HEX64.fullmatch(row["selector_config_hash"]):
                raise ValueError("invalid selector config hash")
            selector_hashes.add(row["selector_config_hash"])
            n_eligible = int(row["n_eligible"])
            n_active = int(row["n_active_before"])
            n_t = int(row["n_t_qg"])
            if n_eligible != len(event.eligible_learned):
                raise ValueError("n_eligible does not match master event")
            if not 0 <= n_active <= 8 or not 0 <= n_t <= min(8 - n_active, n_eligible):
                raise ValueError("active budget or n_t_qg is out of bounds")
            active = row["selection_active"]
            if active not in {"0", "1"} or (active == "1") != (n_t > 0):
                raise ValueError("selection_active is inconsistent with n_t_qg")
            all_ids = {track.track_id for track in event.eligible_learned}
            h_order = _parse_ids(row["h_order"])
            qg_order = _parse_ids(row["qg_order"])
            if set(h_order) != all_ids or set(qg_order) != all_ids:
                raise ValueError("full H/QG order is not a permutation of eligible IDs")
            if len(h_order) != len(set(h_order)) or len(qg_order) != len(set(qg_order)):
                raise ValueError("full order contains duplicate IDs")
            for column in ("h_topn", "r_topn", "q_topn", "g_topn", "qg_topn"):
                top = _parse_ids(row[column])
                if len(top) != n_t or len(top) != len(set(top)) or not set(top) <= all_ids:
                    raise ValueError(f"{column} is inconsistent with n_t_qg/eligible IDs")
            if _parse_ids(row["h_topn"]) != h_order[:n_t]:
                raise ValueError("h_topn is not the prefix of h_order")
            if _parse_ids(row["qg_topn"]) != qg_order[:n_t]:
                raise ValueError("qg_topn is not the prefix of qg_order")
            for column in ("overlap_h_qg", "overlap_r_qg", "overlap_q_qg", "overlap_g_qg"):
                value = row[column]
                if n_t == 0:
                    if value.strip():
                        raise ValueError(f"{column} must be blank when n_t_qg=0")
                else:
                    score = float(value)
                    if not math.isfinite(score) or not 0.0 <= score <= 1.0:
                        raise ValueError(f"{column} is outside [0,1]")
            kernel = float(row["selection_kernel_ms"])
            if not math.isfinite(kernel) or kernel < 0.0:
                raise ValueError("selection_kernel_ms must be finite and non-negative")
        except (KeyError, TypeError, ValueError) as exc:
            raise BundleValidationError(f"shadow row {index}: {exc}")
        if n_t > 0:
            active_events += 1
    if not selector_hashes:
        raise BundleValidationError("shadow CSV has no selector config identity")
    if active_events <= 0:
        raise BundleValidationError("shadow CSV has no active QG event")
    return {
        "path": _display_path(path),
        "columns": fields,
        "event_rows": len(rows),
        "active_events": active_events,
        "selector_config_hashes": sorted(selector_hashes),
        "schema": "development shadow rankings v1",
    }


def validate_claim_boundary(protocol_path: Path, lock_path: Path, bundle: Path) -> Dict[str, Any]:
    protocol = _read_text(protocol_path)
    lock = _read_json(lock_path)
    claim_paths = [protocol_path]
    p03_dir = bundle / "p03"
    if p03_dir.exists():
        claim_paths.extend(sorted(p03_dir.rglob("*.md")))
        # The validator's own JSON report contains the previous check log,
        # including any failure text; feeding that self-referential log back
        # into the claim scanner would manufacture a claim on the next run.
        claim_paths.extend(
            path
            for path in sorted(p03_dir.rglob("*.json"))
            if "candidate_bundle_validation" not in path.name
        )
    forbidden: List[str] = []
    development_values = (
        "0.268486",
        "0.113326",
        "0.265652",
        "0.113263",
        "0.255863",
        "0.108435",
        "0.118616",
        "0.062520",
        "0.058071",
        "0.048803",
        "0.050207",
        "0.113417",
        "0.113416",
    )
    claim_pattern = re.compile(
        r"(?i)\bconfirmatory\b[^\n]{0,120}\b(?:ape|rpe|vins|result|improv|outperform|gain)\b"
        r"[^\n]{0,120}(?:=|:|\bis\b|\bwas\b|\bimprov\w*\b|\breduc\w*\b)"
        r"[^\n]{0,80}\d"
    )
    for path in claim_paths:
        text = _read_text(path)
        for match in claim_pattern.finditer(text):
            context = match.group(0).lower()
            line_start = text.rfind("\n", 0, match.start()) + 1
            line_end = text.find("\n", match.end())
            if line_end < 0:
                line_end = len(text)
            line_context = text[line_start:line_end].lower()
            negative_disclaimer = (
                ("no " in line_context or "not " in line_context or "never" in line_context)
                and ("confirmatory" in line_context or "claimed" in line_context)
            )
            if not negative_disclaimer and not any(
                marker in context for marker in ("no ", "not ", "never", "pending", "prohibit")
            ):
                forbidden.append(f"{_display_path(path)}: {match.group(0)[:160]}")
        for value in development_values:
            start = 0
            while True:
                position = text.find(value, start)
                if position < 0:
                    break
                context = text[max(0, position - 180) : position + 180].lower()
                if not any(
                    marker in context
                    for marker in ("development", "smoke", "historical", "cached", "candidate", "not confirmatory")
                ):
                    forbidden.append(f"{_display_path(path)}: unlabelled development value {value}")
                start = position + len(value)
    if forbidden:
        raise BundleValidationError("confirmatory/development boundary violations: " + " | ".join(forbidden))
    required_disclaimers = (
        "No number in this document is a confirmatory",
        "Existing cached learned/VINS windows remain development-only",
        "no held-out or confirmatory learned/VINS result is claimed",
    )
    missing = [token for token in required_disclaimers if token not in protocol]
    if missing:
        raise BundleValidationError("protocol claim-boundary disclaimer missing: " + ", ".join(missing))
    smoke_records = lock.get("development_smoke_artifacts", [])
    if not smoke_records or any(record.get("role") != "development_smoke_artifact" for record in smoke_records):
        raise BundleValidationError("development smoke artifacts are not explicitly labelled")
    if lock.get("calibration", {}).get("status") != "PROVISIONAL_DEVELOPMENT_ONLY":
        raise BundleValidationError("calibration status does not preserve development boundary")
    return {
        "claim_docs_scanned": [_display_path(path) for path in claim_paths],
        "forbidden_claim_count": 0,
        "development_values_guarded": list(development_values),
        "confirmatory_claim_authorized": False,
    }


def run_related_tests() -> Dict[str, Any]:
    commands = [
        [
            sys.executable,
            "-m",
            "unittest",
            "scripts.tests.test_failure_classifier",
            "scripts.tests.test_master_candidate_stream",
            "scripts.tests.test_fh_residuals",
            "scripts.tests.test_classical_proposer",
            "scripts.tests.test_temporal_reliability",
        ],
        [sys.executable, "-m", "uw_frontend.geometry._marginal_support_selftest"],
        [sys.executable, "-m", "uw_frontend.geometry._shadow_rankings_selftest"],
    ]
    reports: List[Dict[str, Any]] = []
    for command in commands:
        completed = subprocess.run(
            command,
            cwd=str(ROOT),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
        )
        output = completed.stdout or ""
        reports.append(
            {
                "command": " ".join(command),
                "returncode": completed.returncode,
                "output_tail": output[-4000:],
            }
        )
        if completed.returncode != 0:
            raise BundleValidationError(
                f"related test command failed ({completed.returncode}): {' '.join(command)}"
            )
    return {"commands": reports, "status": "all unit tests and selector selftests PASS"}


def payload_hash(data: Mapping[str, Any]) -> str:
    clone = json.loads(json.dumps(data, sort_keys=True))
    clone.pop("candidate_lock_hash", None)
    return hashlib.sha256(
        json.dumps(clone, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _validate_vins_records(data: Mapping[str, Any]) -> None:
    binary = data.get("vins_binary")
    if not isinstance(binary, Mapping):
        raise BundleValidationError("vins_binary record missing")
    _validate_record(binary)
    if binary.get("status") != "PRESENT":
        raise BundleValidationError("VINS binary is not present")
    binary_path = _record_target(str(binary["path"]))
    if sha256_file(binary_path) != binary.get("sha256") or binary_path.stat().st_size != binary.get("size_bytes"):
        raise BundleValidationError("VINS binary hash/size mismatch")

    source = data.get("vins_source")
    if not isinstance(source, Mapping) or source.get("status") != "PRESENT":
        raise BundleValidationError("VINS source record is not present")
    root = Path(str(source.get("root")))
    if not root.is_dir():
        raise BundleValidationError("VINS source root is missing")
    pairs: List[bytes] = []
    for child in sorted(child for child in root.rglob("*") if child.is_file()):
        pairs.append(f"{sha256_file(child)}  {child.relative_to(root).as_posix()}\n".encode("utf-8"))
    tree_hash = hashlib.sha256(b"".join(pairs)).hexdigest()
    if tree_hash != source.get("tree_sha256") or len(pairs) != int(source.get("file_count", -1)):
        raise BundleValidationError("VINS source tree hash/count mismatch")


def _validate_record(record: Mapping[str, Any]) -> None:
    if not isinstance(record, Mapping):
        raise BundleValidationError("artifact record must be an object")
    path = record.get("path")
    if not path:
        raise BundleValidationError("artifact record has no path")
    if record.get("status") not in {"PRESENT", "MISSING"}:
        raise BundleValidationError(f"invalid artifact status for {path}")
    if record.get("status") == "PRESENT":
        if not HEX64.fullmatch(str(record.get("sha256", ""))):
            raise BundleValidationError(f"invalid artifact SHA-256 for {path}")
        if int(record.get("size_bytes", -1)) < 0:
            raise BundleValidationError(f"invalid artifact size for {path}")


def _record_target(path: str) -> Path:
    target = Path(path)
    return target if target.is_absolute() else ROOT / target


def _parse_ids(value: str) -> List[int]:
    if not value.strip():
        return []
    return [int(item) for item in value.split(";") if item != ""]


def _read_text(path: Path) -> str:
    if not path.is_file():
        raise BundleValidationError(f"missing file: {path}")
    return path.read_text(encoding="utf-8")


def _read_json(path: Path) -> Dict[str, Any]:
    try:
        data = json.loads(_read_text(path))
    except json.JSONDecodeError as exc:
        raise BundleValidationError(f"invalid JSON {path}: {exc}")
    if not isinstance(data, dict):
        raise BundleValidationError(f"JSON root must be an object: {path}")
    return data


def _read_yaml(path: Path) -> Dict[str, Any]:
    try:
        import yaml
    except ImportError as exc:
        raise BundleValidationError("PyYAML is required by the existing failure classifier") from exc
    try:
        data = yaml.safe_load(_read_text(path)) or {}
    except Exception as exc:
        raise BundleValidationError(f"invalid YAML {path}: {exc}")
    if not isinstance(data, dict):
        raise BundleValidationError(f"YAML root must be a mapping: {path}")
    return data


def _display_path(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(ROOT.resolve()))
    except ValueError:
        return str(path)


if __name__ == "__main__":
    raise SystemExit(main())
