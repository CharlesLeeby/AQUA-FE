#!/usr/bin/python3
"""Fail-closed schedule state for the fair-stability 120-cell experiment."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
from typing import Any, Mapping


SCHEDULE_SHA256 = "8fdb07f404bc4a24a3866dc1acd6cf8a20b9c960b84d6a9e430299852bc655e8"
TERMINAL_STATUSES = {"SUCCESS", "PARTIAL_NON_SUCCESS", "ALGORITHM_FAILURE"}
ALL_ARMS = {
    "learned_klt_vins", "pure_klt_vins", "hfnet_openloop_675", "hfnet_openloop_350"
}
PIPELINE_EVIDENCE_NAMES = (
    "attempt_manifest.json", "ordinal_dispatch_claim.json", "start_claim.json",
    "run_result.json", "launch_receipt.json", "child_start_receipt.txt",
    "child_lifecycle.txt", "headless.stdout.log", "headless.stderr.log",
    "supervisor.stdout.log", "supervisor.stderr.log", "vins.log",
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
    controller = common.parent / "run_fair_stability_next_v1.py"
    freeze_path = (
        experiment_root / "vins_dev_nativeq_schedfix_v1" / "backend_freeze.json"
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
    }


def canonical_json(value: object) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n").encode("utf-8")


def strict_json_equal(observed: object, expected: object) -> bool:
    """Compare both JSON values and JSON scalar types (so true is not 1)."""
    try:
        return canonical_json(observed) == canonical_json(expected)
    except (TypeError, ValueError):
        return False


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


def attempt_root(experiment_root: Path, cell: Mapping[str, Any], attempt_index: int) -> Path:
    case_id, arm, repeat = str(cell["case_id"]), str(cell["arm"]), int(cell["repeat"])
    if arm.startswith("hfnet_openloop_"):
        base = experiment_root / arm / case_id / f"repeat_{repeat:03d}"
    else:
        base = (
            experiment_root / "vins_dev_nativeq_schedfix_v1" / "attempts"
            / case_id / arm / f"repeat_{repeat:03d}"
        )
    if attempt_index < 1:
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
            value.get("attempt_index", 1),
        ],
        [str(cell["case_id"]), str(cell["arm"]), int(cell["repeat"]), attempt_index],
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
            if not match or int(match.group(1)) < 2:
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
    while attempt_index <= 99:
        root = attempt_root(experiment_root, cell, attempt_index)
        require_no_symlink_components(root, experiment_root)
        manifest_path = root / "attempt_manifest.json"
        start_path = root / "start_claim.json"
        result_path = root / "run_result.json"
        invalid_receipt_path = root / "pipeline_invalid_receipt.json"
        later_root = attempt_root(experiment_root, cell, attempt_index + 1)
        if not root.exists():
            if later_root.exists():
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
        if not _coordinate_matches(manifest, cell, attempt_index):
            raise OrdinalError(f"ATTEMPT_MANIFEST_COORDINATE_MISMATCH:{root}")
        if result_path.is_file():
            if not start_path.is_file():
                raise OrdinalError(f"RESULT_WITHOUT_START_CLAIM:{root}")
            result = json.loads(result_path.read_text(encoding="utf-8"))
            if not _coordinate_matches(result, cell, attempt_index):
                raise OrdinalError(f"RESULT_COORDINATE_MISMATCH:{root}")
            status = str(result.get("status"))
            if status in TERMINAL_STATUSES:
                if later_root.exists():
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
                        != "aqua-fe-fair-stability-ordinal-terminal-v1"
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
                != "aqua-fe-fair-stability-pipeline-invalid-adjudication-v1"
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
            ):
                raise OrdinalError(f"PIPELINE_INVALID_RECEIPT_RESULT_DRIFT:{root}")
            invalid_chain.append(
                {
                    "attempt_index": attempt_index,
                    "attempt_root": str(root),
                    "run_result": identity(result_path),
                    "receipt": identity(invalid_receipt_path),
                }
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
        if later_root.exists():
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
    if claim.get("schema_version") != "aqua-fe-fair-stability-ordinal-dispatch-v1":
        raise OrdinalError("DISPATCH_SCHEMA_MISMATCH")
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
        claim.get("planned_ordinal"),
        authorize(experiment_root, case_id, arm, repeat, attempt_index)["cell"]["ordinal"],
    ):
        raise OrdinalError("DISPATCH_ORDINAL_MISMATCH")
    return {"claim": claim, "identity": identity(path)}
