#!/usr/bin/python3
"""Fail-closed schedule state for fair-stability runtime-exclusive v3."""

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timedelta
from pathlib import Path
import re
from typing import Any, Mapping


SCHEDULE_SHA256 = "8fdb07f404bc4a24a3866dc1acd6cf8a20b9c960b84d6a9e430299852bc655e8"
EXPERIMENT_ID = "fair-stability-positive-roster-openloop-runtimeexcl-v3"
TERMINAL_STATUSES = {"SUCCESS", "PARTIAL_NON_SUCCESS", "ALGORITHM_FAILURE"}
MAX_REPLACEMENT_ATTEMPTS_PER_CELL = 2
MAX_ATTEMPTS_PER_CELL = 1 + MAX_REPLACEMENT_ATTEMPTS_PER_CELL
AUTOMATIC_RETRY_PIPELINE_FAILURES = frozenset({
    "MIDRUN_EXTERNAL_RESOURCE_INTRUSION",
})
ALL_ARMS = {
    "learned_klt_vins", "pure_klt_vins", "hfnet_openloop_675", "hfnet_openloop_350"
}
PIPELINE_EVIDENCE_NAMES = (
    "attempt_manifest.json", "ordinal_dispatch_claim.json", "start_claim.json",
    "run_result.json", "launch_receipt.json", "child_start_receipt.txt",
    "child_lifecycle.txt", "headless.stdout.log", "headless.stderr.log",
    "supervisor.stdout.log", "supervisor.stderr.log", "vins.log",
    "runtime_resource_monitor.json",
)


class OrdinalError(RuntimeError):
    pass


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def identity(path: Path) -> dict[str, object]:
    if path.is_symlink() or not path.is_file():
        raise OrdinalError(f"IDENTITY_FILE_INVALID:{path}")
    return {"path": str(path), "size_bytes": path.stat().st_size, "sha256": sha256_file(path)}


def identity_matches(record: object, path: Path) -> bool:
    """Require the complete recorded identity, including its fixed path."""
    return isinstance(record, Mapping) and strict_json_equal(record, identity(path))


def control_boundary(experiment_root: Path) -> dict[str, dict[str, object]]:
    """Bind receipts and dispatches to this controller and this frozen control set."""
    common = Path(__file__).resolve()
    controller = common.parent / "run_fair_stability_next_v3.py"
    freeze_path = (
        experiment_root / "vins_dev_nativeq_schedfix_runtimeexcl_v3" / "backend_freeze.json"
    )
    require_no_symlink_components(freeze_path, experiment_root)
    freeze_identity = identity(freeze_path)
    freeze = json.loads(freeze_path.read_text(encoding="utf-8"))
    if freeze.get("status") != "FROZEN_BEFORE_NEW_VINS_REPLAY":
        raise OrdinalError("CONTROL_FREEZE_STATUS_INVALID")
    controls = freeze.get("controls")
    if not isinstance(controls, Mapping):
        raise OrdinalError("CONTROL_FREEZE_CONTROLS_MISSING")
    for path in (common, controller):
        if not identity_matches(controls.get(path.name), path):
            raise OrdinalError(f"CONTROL_FREEZE_IDENTITY_DRIFT:{path.name}")
    return {
        "common": identity(common),
        "controller": identity(controller),
        "control_freeze": freeze_identity,
        "attempt_matrix_freeze": identity(experiment_root / "attempt_matrix_freeze_v3.json"),
    }


def canonical_json(value: object) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n").encode("utf-8")


def strict_json_equal(observed: object, expected: object) -> bool:
    """Compare both JSON values and JSON scalar types (so true is not 1)."""
    try:
        return canonical_json(observed) == canonical_json(expected)
    except (TypeError, ValueError):
        return False


def valid_utc_receipt_timestamp(value: object) -> bool:
    """Accept only an explicit, parseable UTC timestamp for immutable receipts."""
    if not isinstance(value, str) or not value:
        return False
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return parsed.tzinfo is not None and parsed.utcoffset() == timedelta(0)


def require_no_symlink_components(path: Path, experiment_root: Path) -> None:
    """Reject directory redirection anywhere below the fixed experiment root."""
    anchor = Path(os.path.abspath(experiment_root))
    target = Path(os.path.abspath(path))
    try:
        relative = target.relative_to(anchor)
    except ValueError as error:
        raise OrdinalError(f"PATH_OUTSIDE_EXPERIMENT_ROOT:{target}") from error
    candidate = anchor
    if candidate.is_symlink():
        raise OrdinalError(f"SYMLINK_PATH_COMPONENT:{candidate}")
    for part in relative.parts:
        candidate = candidate / part
        if candidate.is_symlink():
            raise OrdinalError(f"SYMLINK_PATH_COMPONENT:{candidate}")


def load_schedule(experiment_root: Path) -> list[dict[str, Any]]:
    path = experiment_root / "planned_schedule.json"
    require_no_symlink_components(path, experiment_root)
    observed = identity(path)
    if observed["sha256"] != SCHEDULE_SHA256:
        raise OrdinalError("SCHEDULE_IDENTITY_MISMATCH")
    parent = json.loads((experiment_root / "experiment_manifest.json").read_text(encoding="utf-8"))
    if parent.get("experiment_id") != EXPERIMENT_ID:
        raise OrdinalError("PARENT_EXPERIMENT_ID_MISMATCH")
    parent_schedule = parent.get("planned_schedule", {})
    if (
        parent_schedule.get("sha256"), parent_schedule.get("size_bytes")
    ) != (observed["sha256"], observed["size_bytes"]):
        raise OrdinalError("PARENT_SCHEDULE_PIN_MISMATCH")
    schedule = json.loads(path.read_text(encoding="utf-8"))
    if len(schedule) != 120:
        raise OrdinalError("SCHEDULE_LENGTH_MISMATCH")
    coordinates: set[tuple[str, str, int]] = set()
    for expected_ordinal, cell in enumerate(schedule, 1):
        coordinate = (str(cell.get("case_id")), str(cell.get("arm")), int(cell.get("repeat", -1)))
        if cell.get("ordinal") != expected_ordinal or coordinate in coordinates:
            raise OrdinalError("SCHEDULE_ORDINAL_OR_COORDINATE_INVALID")
        if coordinate[1] not in ALL_ARMS or coordinate[2] not in (1, 2, 3):
            raise OrdinalError("SCHEDULE_CELL_INVALID")
        coordinates.add(coordinate)
    return schedule


def load_attempt_matrix(experiment_root: Path) -> dict[str, Any]:
    """Verify the immutable 120-attempt v3 matrix without freezing later retries."""
    path = experiment_root / "attempt_matrix_freeze_v3.json"
    require_no_symlink_components(path, experiment_root)
    if path.is_symlink() or not path.is_file():
        raise OrdinalError("ATTEMPT_MATRIX_FREEZE_MISSING_OR_INVALID")
    value = json.loads(path.read_text(encoding="utf-8"))
    if (
        value.get("schema_version")
        != "aqua-fe-fair-stability-attempt-matrix-freeze-v3"
        or value.get("experiment_id") != EXPERIMENT_ID
        or value.get("status") != "FROZEN_BEFORE_ANY_V3_ESTIMATOR_START"
    ):
        raise OrdinalError("ATTEMPT_MATRIX_FREEZE_HEADER_INVALID")
    expected_replacement_policy = {
        "automatic_retry_pipeline_failure_codes": sorted(
            AUTOMATIC_RETRY_PIPELINE_FAILURES
        ),
        "maximum_replacement_attempts_per_planned_cell": MAX_REPLACEMENT_ATTEMPTS_PER_CELL,
        "maximum_total_attempts_per_planned_cell": MAX_ATTEMPTS_PER_CELL,
        "same_pipeline_failure_code_may_repeat": False,
    }
    if not strict_json_equal(
        value.get("replacement_policy"), expected_replacement_policy
    ):
        raise OrdinalError("ATTEMPT_MATRIX_REPLACEMENT_POLICY_INVALID")
    expected_claims = {
        "attempt_count": 120,
        "v1_results_imported": False,
        "v2_results_imported": False,
        "dispatch_claim_count": 0,
        "start_claim_count": 0,
        "run_result_count": 0,
        "terminal_receipt_count": 0,
    }
    if not strict_json_equal(value.get("claims"), expected_claims):
        raise OrdinalError("ATTEMPT_MATRIX_CLAIMS_INVALID")
    for key, candidate in (
        ("experiment_manifest", experiment_root / "experiment_manifest.json"),
        ("planned_schedule", experiment_root / "planned_schedule.json"),
        (
            "backend_freeze",
            experiment_root
            / "vins_dev_nativeq_schedfix_runtimeexcl_v3"
            / "backend_freeze.json",
        ),
    ):
        if not identity_matches(value.get(key), candidate):
            raise OrdinalError(f"ATTEMPT_MATRIX_PARENT_DRIFT:{key}")
    schedule = load_schedule(experiment_root)
    rows = value.get("attempts")
    if not isinstance(rows, list) or len(rows) != 120:
        raise OrdinalError("ATTEMPT_MATRIX_LENGTH_MISMATCH")
    for cell, row in zip(schedule, rows):
        if not isinstance(row, Mapping):
            raise OrdinalError("ATTEMPT_MATRIX_ROW_INVALID")
        expected_root = attempt_root(experiment_root, cell, 1)
        expected_manifest = expected_root / "attempt_manifest.json"
        if not strict_json_equal(
            [
                row.get("ordinal"), row.get("case_id"), row.get("arm"),
                row.get("repeat"), row.get("attempt_index"),
                row.get("attempt_root"), row.get("maximum_replacement_attempts"),
                row.get("maximum_total_attempts"),
            ],
            [
                int(cell["ordinal"]), str(cell["case_id"]), str(cell["arm"]),
                int(cell["repeat"]), 1, str(expected_root),
                MAX_REPLACEMENT_ATTEMPTS_PER_CELL, MAX_ATTEMPTS_PER_CELL,
            ],
        ) or not identity_matches(row.get("attempt_manifest"), expected_manifest):
            raise OrdinalError(f"ATTEMPT_MATRIX_ROW_DRIFT:{cell['ordinal']}")
    return value


def attempt_root(experiment_root: Path, cell: Mapping[str, Any], attempt_index: int) -> Path:
    case_id, arm, repeat = str(cell["case_id"]), str(cell["arm"]), int(cell["repeat"])
    if arm.startswith("hfnet_openloop_"):
        base = experiment_root / arm / case_id / f"repeat_{repeat:03d}"
    else:
        base = (
            experiment_root / "vins_dev_nativeq_schedfix_runtimeexcl_v3" / "attempts"
            / case_id / arm / f"repeat_{repeat:03d}"
        )
    if attempt_index < 1 or attempt_index > MAX_ATTEMPTS_PER_CELL:
        raise OrdinalError("ATTEMPT_INDEX_INVALID")
    return base if attempt_index == 1 else base.with_name(
        f"{base.name}__replenishment_{attempt_index:03d}"
    )


def _coordinate_matches(value: Mapping[str, Any], cell: Mapping[str, Any], attempt_index: int) -> bool:
    observed_arm = value.get("arm")
    if observed_arm is None and value.get("budget") is not None:
        if type(value.get("budget")) is not int:
            return False
        observed_arm = f"hfnet_openloop_{value['budget']}"
    return strict_json_equal(
        [
            value.get("case_id"), observed_arm, value.get("repeat"),
            value.get("attempt_index"),
        ],
        [str(cell["case_id"]), str(cell["arm"]), int(cell["repeat"]), attempt_index],
    )


def result_contract_valid(value: Mapping[str, Any]) -> bool:
    """Verify the runner's deterministic status/failure-code derivation."""
    lists: list[list[str]] = []
    for key in (
        "failure_codes",
        "pipeline_failure_codes",
        "algorithm_failure_codes",
    ):
        candidate = value.get(key)
        if (
            not isinstance(candidate, list)
            or any(not isinstance(code, str) or not code for code in candidate)
            or len(candidate) != len(set(candidate))
        ):
            return False
        lists.append(candidate)
    failures, pipeline, algorithm = lists
    if failures != pipeline + algorithm or set(pipeline).intersection(algorithm):
        return False
    if pipeline:
        expected_status = "PIPELINE_INVALID"
    elif not algorithm:
        expected_status = "SUCCESS"
    elif algorithm == ["PARTIAL_TRAJECTORY_COVERAGE_BELOW_70_PERCENT"]:
        expected_status = "PARTIAL_NON_SUCCESS"
    else:
        expected_status = "ALGORITHM_FAILURE"
    clean_success = value.get("clean_success")
    return (
        value.get("status") == expected_status
        and type(clean_success) is bool
        and (expected_status == "SUCCESS" or clean_success is False)
    )


def inspect_cell(experiment_root: Path, cell: Mapping[str, Any]) -> dict[str, Any]:
    base = attempt_root(experiment_root, cell, 1)
    require_no_symlink_components(base, experiment_root)
    existing_indices: list[int] = []
    if base.exists():
        existing_indices.append(1)
    if base.parent.is_dir():
        prefix = f"{base.name}__replenishment_"
        for candidate in base.parent.glob(f"{prefix}*"):
            match = re.fullmatch(re.escape(prefix) + r"([0-9]{3})", candidate.name)
            if (
                not match
                or int(match.group(1)) < 2
                or int(match.group(1)) > MAX_ATTEMPTS_PER_CELL
            ):
                raise OrdinalError(f"ATTEMPT_DIRECTORY_NAME_INVALID:{candidate}")
            existing_indices.append(int(match.group(1)))
    if existing_indices:
        ordered_indices = sorted(set(existing_indices))
        if len(ordered_indices) != len(existing_indices) or ordered_indices != list(
            range(1, ordered_indices[-1] + 1)
        ):
            raise OrdinalError(f"ATTEMPT_INDEX_GAP_OR_DUPLICATE:{cell['ordinal']}:{ordered_indices}")
    invalid_chain: list[dict[str, Any]] = []
    attempt_index = 1
    while attempt_index <= MAX_ATTEMPTS_PER_CELL:
        root = attempt_root(experiment_root, cell, attempt_index)
        require_no_symlink_components(root, experiment_root)
        manifest_path = root / "attempt_manifest.json"
        start_path = root / "start_claim.json"
        result_path = root / "run_result.json"
        invalid_receipt_path = root / "pipeline_invalid_receipt.json"
        later_root = (
            attempt_root(experiment_root, cell, attempt_index + 1)
            if attempt_index < MAX_ATTEMPTS_PER_CELL
            else None
        )
        if not root.exists():
            if later_root is not None and later_root.exists():
                raise OrdinalError(f"ATTEMPT_INDEX_GAP:{cell['ordinal']}:{attempt_index}")
            return {
                "state": "NEEDS_PREPARATION",
                "cell": dict(cell),
                "attempt_index": attempt_index,
                "attempt_root": str(root),
                "invalid_chain": invalid_chain,
            }
        if not manifest_path.is_file():
            raise OrdinalError(f"ATTEMPT_MANIFEST_MISSING:{root}")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        hfnet_arm = str(cell["arm"]).startswith("hfnet_openloop_")
        expected_manifest_schema = (
            "aqua-fe-fair-stability-hfnet-attempt-v3"
            if hfnet_arm
            else "aqua-fe-fair-stability-vins-attempt-v3"
        )
        if (
            manifest.get("schema_version") != expected_manifest_schema
            or manifest.get("experiment_id") != EXPERIMENT_ID
            or not _coordinate_matches(manifest, cell, attempt_index)
        ):
            raise OrdinalError(f"ATTEMPT_MANIFEST_SCHEMA_OR_COORDINATE_MISMATCH:{root}")
        if result_path.is_file():
            if not start_path.is_file():
                raise OrdinalError(f"RESULT_WITHOUT_START_CLAIM:{root}")
            result = json.loads(result_path.read_text(encoding="utf-8"))
            expected_result_schema = (
                "aqua-fe-fair-stability-hfnet-result-v3"
                if hfnet_arm
                else "aqua-fe-fair-stability-vins-result-v3"
            )
            if (
                result.get("schema_version") != expected_result_schema
                or result.get("experiment_id") != EXPERIMENT_ID
                or not _coordinate_matches(result, cell, attempt_index)
                or not result_contract_valid(result)
            ):
                raise OrdinalError(f"RESULT_SCHEMA_OR_COORDINATE_MISMATCH:{root}")
            status = str(result.get("status"))
            if status in TERMINAL_STATUSES:
                if later_root is not None and later_root.exists():
                    raise OrdinalError(f"REPLENISHMENT_AFTER_ALGORITHM_TERMINAL:{root}")
                terminal_receipt = (
                    experiment_root / "ordinal_receipts"
                    / f"ordinal_{int(cell['ordinal']):03d}_terminal.json"
                )
                require_no_symlink_components(terminal_receipt, experiment_root)
                if terminal_receipt.is_symlink():
                    raise OrdinalError(f"TERMINAL_RECEIPT_SYMLINK:{terminal_receipt}")
                if terminal_receipt.exists() and not terminal_receipt.is_file():
                    raise OrdinalError(f"TERMINAL_RECEIPT_NONREGULAR:{terminal_receipt}")
                if terminal_receipt.is_file():
                    receipt_value = json.loads(terminal_receipt.read_text(encoding="utf-8"))
                    boundary = control_boundary(experiment_root)
                    if (
                        receipt_value.get("schema_version")
                        != "aqua-fe-fair-stability-ordinal-terminal-v3"
                        or not strict_json_equal(
                            [
                                receipt_value.get("planned_ordinal"),
                                receipt_value.get("case_id"),
                                receipt_value.get("arm"),
                                receipt_value.get("repeat"),
                                receipt_value.get("accepted_attempt_index"),
                            ],
                            [
                                int(cell["ordinal"]), str(cell["case_id"]),
                                str(cell["arm"]), int(cell["repeat"]), attempt_index,
                            ],
                        )
                        or not identity_matches(receipt_value.get("run_result"), result_path)
                        or not identity_matches(receipt_value.get("start_claim"), start_path)
                        or not identity_matches(receipt_value.get("attempt_manifest"), manifest_path)
                        or not identity_matches(
                            receipt_value.get("ordinal_dispatch_claim"),
                            root / "ordinal_dispatch_claim.json",
                        )
                        or receipt_value.get("terminal_status") != status
                        or not isinstance(receipt_value.get("clean_success"), bool)
                        or receipt_value.get("clean_success") is not bool(
                            result.get("clean_success")
                        )
                        or receipt_value.get("schedule_sha256") != SCHEDULE_SHA256
                        or not strict_json_equal(
                            receipt_value.get("invalid_attempt_chain"), invalid_chain
                        )
                        or not strict_json_equal(
                            receipt_value.get("controller"), boundary["controller"]
                        )
                        or not strict_json_equal(
                            receipt_value.get("control_freeze"), boundary["control_freeze"]
                        )
                        or not strict_json_equal(
                            receipt_value.get("attempt_matrix_freeze"),
                            boundary["attempt_matrix_freeze"],
                        )
                        or receipt_value.get("experiment_id") != EXPERIMENT_ID
                        or not valid_utc_receipt_timestamp(
                            receipt_value.get("adopted_at_utc")
                        )
                    ):
                        raise OrdinalError(f"TERMINAL_RECEIPT_MISMATCH:{terminal_receipt}")
                return {
                    "state": "TERMINAL" if terminal_receipt.is_file() else "TERMINAL_UNADOPTED",
                    "cell": dict(cell),
                    "attempt_index": attempt_index,
                    "attempt_root": str(root),
                    "result": result,
                    "result_identity": identity(result_path),
                    "terminal_receipt": str(terminal_receipt),
                    "invalid_chain": invalid_chain,
                }
            if status != "PIPELINE_INVALID":
                raise OrdinalError(f"UNKNOWN_RESULT_STATUS:{root}:{status}")
            if invalid_receipt_path.is_symlink():
                raise OrdinalError(f"PIPELINE_INVALID_RECEIPT_SYMLINK:{invalid_receipt_path}")
            if invalid_receipt_path.exists() and not invalid_receipt_path.is_file():
                raise OrdinalError(f"PIPELINE_INVALID_RECEIPT_NONREGULAR:{invalid_receipt_path}")
            if not invalid_receipt_path.is_file():
                if later_root is not None and later_root.exists():
                    raise OrdinalError(
                        f"REPLENISHMENT_BEFORE_PIPELINE_INVALID_ADJUDICATION:{root}"
                    )
                return {
                    "state": "PIPELINE_INVALID_UNADJUDICATED",
                    "cell": dict(cell),
                    "attempt_index": attempt_index,
                    "attempt_root": str(root),
                    "result": result,
                    "result_identity": identity(result_path),
                    "invalid_chain": invalid_chain,
                }
            invalid_receipt = json.loads(invalid_receipt_path.read_text(encoding="utf-8"))
            if invalid_receipt.get("accepted_as_external_pipeline_fault") is not True:
                raise OrdinalError(f"PIPELINE_INVALID_RECEIPT_REJECTED:{root}")
            boundary = control_boundary(experiment_root)
            evidence = invalid_receipt.get("evidence")
            if not isinstance(evidence, Mapping):
                raise OrdinalError(f"PIPELINE_INVALID_EVIDENCE_MISSING:{root}")
            required_evidence = (
                "attempt_manifest.json", "ordinal_dispatch_claim.json",
                "start_claim.json", "run_result.json",
            )
            if any(
                name not in evidence
                or not identity_matches(evidence.get(name), root / name)
                for name in required_evidence
            ):
                raise OrdinalError(f"PIPELINE_INVALID_REQUIRED_EVIDENCE_DRIFT:{root}")
            expected_evidence: dict[str, object] = {}
            for name in PIPELINE_EVIDENCE_NAMES:
                candidate = root / name
                if candidate.is_symlink() or (
                    candidate.exists() and not candidate.is_file()
                ):
                    raise OrdinalError(f"PIPELINE_INVALID_EVIDENCE_NONREGULAR:{candidate}")
                if candidate.is_file():
                    expected_evidence[name] = identity(candidate)
            if not strict_json_equal(evidence, expected_evidence):
                raise OrdinalError(f"PIPELINE_INVALID_EVIDENCE_DRIFT:{root}")
            if (
                invalid_receipt.get("schema_version")
                != "aqua-fe-fair-stability-pipeline-invalid-adjudication-v3"
                or invalid_receipt.get("automatic_retry_policy")
                != "EXPLICIT_EXTERNAL_TRANSIENT_ONLY_V3"
                or invalid_receipt.get("maximum_replacement_attempts_per_planned_cell")
                != MAX_REPLACEMENT_ATTEMPTS_PER_CELL
                or not identity_matches(invalid_receipt.get("run_result"), result_path)
                or not strict_json_equal(
                    [
                        invalid_receipt.get("planned_ordinal"),
                        invalid_receipt.get("case_id"), invalid_receipt.get("arm"),
                        invalid_receipt.get("repeat"),
                        invalid_receipt.get("attempt_index"),
                    ],
                    [
                        int(cell["ordinal"]), str(cell["case_id"]),
                        str(cell["arm"]), int(cell["repeat"]), attempt_index,
                    ],
                )
                or invalid_receipt.get("schedule_sha256") != SCHEDULE_SHA256
                or not strict_json_equal(
                    invalid_receipt.get("pipeline_failure_codes"),
                    [str(value) for value in result.get("pipeline_failure_codes", [])],
                )
                or not strict_json_equal(
                    invalid_receipt.get(
                        "algorithm_failure_codes_observed_but_excluded_with_invalid_attempt"
                    ),
                    list(result.get("algorithm_failure_codes", [])),
                )
                or not strict_json_equal(
                    invalid_receipt.get("controller"), boundary["controller"]
                )
                or not strict_json_equal(
                    invalid_receipt.get("control_freeze"), boundary["control_freeze"]
                )
                or not strict_json_equal(
                    invalid_receipt.get("attempt_matrix_freeze"),
                    boundary["attempt_matrix_freeze"],
                )
                or invalid_receipt.get("experiment_id") != EXPERIMENT_ID
                or not valid_utc_receipt_timestamp(
                    invalid_receipt.get("adjudicated_at_utc")
                )
            ):
                raise OrdinalError(f"PIPELINE_INVALID_RECEIPT_RESULT_DRIFT:{root}")
            pipeline_codes = [
                str(value) for value in result.get("pipeline_failure_codes", [])
            ]
            if (
                not pipeline_codes
                or len(pipeline_codes) != len(set(pipeline_codes))
                or any(
                    code not in AUTOMATIC_RETRY_PIPELINE_FAILURES
                    for code in pipeline_codes
                )
            ):
                raise OrdinalError(
                    f"PIPELINE_INVALID_RECEIPT_NONRETRYABLE_CODE:{root}"
                )
            prior_codes = {
                code
                for entry in invalid_chain
                for code in entry.get("pipeline_failure_codes", [])
            }
            if prior_codes.intersection(pipeline_codes):
                raise OrdinalError(
                    f"REPEATED_PIPELINE_FAILURE_CODE_HALT:{cell['ordinal']}"
                )
            invalid_chain.append(
                {
                    "attempt_index": attempt_index,
                    "attempt_root": str(root),
                    "pipeline_failure_codes": pipeline_codes,
                    "run_result": identity(result_path),
                    "receipt": identity(invalid_receipt_path),
                }
            )
            if attempt_index == MAX_ATTEMPTS_PER_CELL:
                raise OrdinalError(
                    f"REPLACEMENT_LIMIT_EXHAUSTED:{cell['ordinal']}:"
                    f"{MAX_REPLACEMENT_ATTEMPTS_PER_CELL}"
                )
            attempt_index += 1
            continue
        if invalid_receipt_path.exists():
            raise OrdinalError(f"INVALID_RECEIPT_WITHOUT_RESULT:{root}")
        if start_path.exists():
            return {
                "state": "STARTED_WITHOUT_RESULT",
                "cell": dict(cell),
                "attempt_index": attempt_index,
                "attempt_root": str(root),
                "start_claim": identity(start_path),
                "invalid_chain": invalid_chain,
            }
        if later_root is not None and later_root.exists():
            raise OrdinalError(f"LATER_ATTEMPT_BEFORE_CURRENT_TERMINAL:{root}")
        return {
            "state": "READY",
            "cell": dict(cell),
            "attempt_index": attempt_index,
            "attempt_root": str(root),
            "invalid_chain": invalid_chain,
        }
    raise OrdinalError("ATTEMPT_INDEX_LIMIT_EXCEEDED")


def next_state(experiment_root: Path) -> dict[str, Any]:
    load_attempt_matrix(experiment_root)
    schedule = load_schedule(experiment_root)
    first_nonterminal: dict[str, Any] | None = None
    for position, cell in enumerate(schedule):
        state = inspect_cell(experiment_root, cell)
        if state["state"] == "TERMINAL":
            continue
        first_nonterminal = state
        for later in schedule[position + 1 :]:
            later_state = inspect_cell(experiment_root, later)
            later_root = Path(later_state["attempt_root"])
            if (
                later_state["state"] not in {"READY", "NEEDS_PREPARATION"}
                or int(later_state.get("attempt_index", 1)) != 1
                or bool(later_state.get("invalid_chain"))
                or (later_root / "ordinal_dispatch_claim.json").exists()
                or (later_root / "start_claim.json").exists()
                or (later_root / "run_result.json").exists()
            ):
                raise OrdinalError(f"LATER_CELL_STARTED_OUT_OF_ORDER:{later['ordinal']}")
        break
    return first_nonterminal or {"state": "COMPLETE", "completed": 120}


def authorize(
    experiment_root: Path,
    case_id: str,
    arm: str,
    repeat: int,
    attempt_index: int,
) -> dict[str, Any]:
    state = next_state(experiment_root)
    if state.get("state") != "READY":
        raise OrdinalError(f"NEXT_CELL_NOT_READY:{state.get('state')}")
    cell = state["cell"]
    requested = (case_id, arm, repeat, attempt_index)
    expected = (
        str(cell["case_id"]), str(cell["arm"]), int(cell["repeat"]), int(state["attempt_index"])
    )
    if requested != expected:
        raise OrdinalError(f"OUT_OF_ORDER_REQUEST:{requested}:EXPECTED:{expected}")
    return state


def verify_dispatch_claim(
    experiment_root: Path,
    attempt_root_path: Path,
    case_id: str,
    arm: str,
    repeat: int,
    attempt_index: int,
) -> dict[str, Any]:
    require_no_symlink_components(attempt_root_path, experiment_root)
    token = os.environ.get("FAIR_STABILITY_DISPATCH_TOKEN", "")
    if not token:
        raise OrdinalError("DISPATCH_TOKEN_MISSING")
    path = attempt_root_path / "ordinal_dispatch_claim.json"
    if not path.is_file() or path.is_symlink():
        raise OrdinalError("DISPATCH_CLAIM_MISSING_OR_INVALID")
    claim = json.loads(path.read_text(encoding="utf-8"))
    expected = [case_id, arm, repeat, attempt_index]
    observed = [
        claim.get("case_id"), claim.get("arm"),
        claim.get("repeat"), claim.get("attempt_index"),
    ]
    if not strict_json_equal(observed, expected):
        raise OrdinalError(f"DISPATCH_COORDINATE_MISMATCH:{observed}:{expected}")
    if claim.get("schema_version") != "aqua-fe-fair-stability-ordinal-dispatch-v3":
        raise OrdinalError("DISPATCH_SCHEMA_MISMATCH")
    if claim.get("experiment_id") != EXPERIMENT_ID:
        raise OrdinalError("DISPATCH_EXPERIMENT_ID_MISMATCH")
    if claim.get("schedule_sha256") != SCHEDULE_SHA256:
        raise OrdinalError("DISPATCH_SCHEDULE_MISMATCH")
    boundary = control_boundary(experiment_root)
    current_attempt_manifest = identity(attempt_root_path / "attempt_manifest.json")
    claimed_attempt_manifest = claim.get("attempt_manifest")
    if not strict_json_equal(claimed_attempt_manifest, current_attempt_manifest):
        raise OrdinalError("DISPATCH_ATTEMPT_MANIFEST_DRIFT")
    if claim.get("token_sha256") != hashlib.sha256(token.encode("ascii")).hexdigest():
        raise OrdinalError("DISPATCH_TOKEN_MISMATCH")
    if claim.get("dispatch_token") != token:
        raise OrdinalError("DISPATCH_EMBEDDED_TOKEN_MISMATCH")
    if not strict_json_equal(claim.get("controller"), boundary["controller"]):
        raise OrdinalError("DISPATCH_CONTROLLER_DRIFT")
    if not strict_json_equal(claim.get("control_freeze"), boundary["control_freeze"]):
        raise OrdinalError("DISPATCH_CONTROL_FREEZE_DRIFT")
    if not strict_json_equal(
        claim.get("attempt_matrix_freeze"), boundary["attempt_matrix_freeze"]
    ):
        raise OrdinalError("DISPATCH_ATTEMPT_MATRIX_FREEZE_DRIFT")
    if not strict_json_equal(
        claim.get("planned_ordinal"),
        authorize(experiment_root, case_id, arm, repeat, attempt_index)["cell"]["ordinal"],
    ):
        raise OrdinalError("DISPATCH_ORDINAL_MISMATCH")
    return {"claim": claim, "identity": identity(path)}
