#!/usr/bin/env python3
"""Atomically freeze the final P06 manifest dependencies and narrowed arm matrix."""

from __future__ import annotations

import csv
import hashlib
import io
import itertools
import json
import os
from collections import Counter
from pathlib import Path

try:
    from scripts.build_nativeq_backend_contract import file_record, payload_hash
    from scripts.build_nativeq_legacy_method_lock_v5 import method_payload_hash
except ModuleNotFoundError:  # Direct ``python3 scripts/...`` execution.
    from build_nativeq_backend_contract import file_record, payload_hash  # type: ignore
    from build_nativeq_legacy_method_lock_v5 import method_payload_hash  # type: ignore


ROOT = Path(__file__).resolve().parents[1]
BUNDLE = ROOT / "papers/ieee_sensors_journal_experiments"
P06 = BUNDLE / "p06"
FINAL_MANIFEST = BUNDLE / "dataset_manifest_v4.csv"
FINAL_AUDIT = BUNDLE / "window_selection_audit_v4.csv"
FINAL_PROGRESS = P06 / "screening_progress_v4.json"
FINAL_VALIDATION = P06 / "final_artifact_validation_v4.json"
V5_LOCK = BUNDLE / "method_lock_nativeq_legacy_candidate_v5.json"
ROUTE_CONTRACT = BUNDLE / "p04/nativeq_v3_route_contract_v1.json"
P_BACKEND_CONTRACT = BUNDLE / "backend_quality_contract_v1.json"
M_BACKEND_CONTRACT = BUNDLE / "p05/backend_consumer_contract_xfeat_v1.json"
ELIGIBILITY = BUNDLE / "data_eligibility_manifest.csv"
P02_CHECKSUMS = BUNDLE / "p02/input_reference_checksums.csv"

DATASET_CHECKSUM_MANIFEST = BUNDLE / "dataset_checksum_manifest.txt"
ARM_ORDER = BUNDLE / "arm_order.csv"
FINAL_ENVIRONMENT = BUNDLE / "environment_manifest_nativeq_v5_final.txt"
METHOD_LOCK = BUNDLE / "method_lock.json"
PROTOCOL = BUNDLE / "protocol_v1_nativeq_v3.md"
FREEZE_HASHES = P06 / "final_freeze_v1.sha256"

PROTOCOL_VERSION = "isj-nativeq-v3-confirmatory-protocol-v1"
ARM_ORDER_SCHEMA = "isj-arm-order-nativeq-v3-v1"
OUTCOME_BOUNDARY = "FROZEN_BEFORE_HELD_OUT_LEARNED_OR_TRAJECTORY_OUTCOME"

B0 = "B0_native_vins_origin_v1"
B1 = "B1_klt_nativeq_v3"
P_ARM = "P_legacy_nativeq_xfeat_seedchain_v3"
M_ARM = "M_xfeat_pairwise_nativeq_v1"
D_ARM = "D_legacy_exact_lineage_drop_v3"
REQUIRED_ARMS = (B0, B1, P_ARM, M_ARM)
CONDITIONAL_ARMS = (D_ARM,)
WILLIAMS_PATTERNS = (
    (B0, B1, M_ARM, P_ARM),
    (B1, P_ARM, B0, M_ARM),
    (P_ARM, M_ARM, B1, B0),
    (M_ARM, B0, P_ARM, B1),
)

INPUT_ARTIFACTS = (
    FINAL_MANIFEST,
    FINAL_AUDIT,
    FINAL_PROGRESS,
    FINAL_VALIDATION,
    V5_LOCK,
    ROUTE_CONTRACT,
    P_BACKEND_CONTRACT,
    M_BACKEND_CONTRACT,
    BUNDLE / "p04/nativeq_v3_route_addendum_v1.md",
    BUNDLE / "p06/window_selection_quota_repair_v3.md",
    BUNDLE / "p06/final_reference_gate_repair_v4.md",
    BUNDLE / "evaluator_protocol_v1.md",
    BUNDLE / "failure_taxonomy_v1.yaml",
    BUNDLE / "environment_manifest.txt",
    BUNDLE / "environment_manifest_nativeq_v3_addendum.txt",
    ROOT / "scripts/run_isj_nativeq_contract_guarded_v4.sh",
    ROOT / "scripts/run_p05_modern_xfeat_baseline_guarded_v2.sh",
    ROOT / "scripts/audit_whole_lineage_exact_drop_v1.py",
    ROOT / "scripts/evaluate_vins_common_support.py",
    ROOT / "scripts/build_p06_screening_manifest_v4.py",
    ROOT / "scripts/validate_p06_final_artifacts_v4.py",
    ROOT / "scripts/build_p06_final_freeze_v1.py",
    ROOT / "scripts/tests/test_p06_final_freeze_v1.py",
)


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def relative(path: Path) -> str:
    return path.resolve().relative_to(ROOT).as_posix()


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        fields = list(reader.fieldnames or [])
        if not fields or len(fields) != len(set(fields)):
            raise ValueError(f"invalid CSV header: {path}")
        rows = list(reader)
    if any(None in row for row in rows):
        raise ValueError(f"ragged CSV: {path}")
    return rows


def load_object(path: Path) -> dict[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def content_record(path: Path, content: bytes) -> dict[str, object]:
    return {
        "path": relative(path),
        "sha256": sha256_bytes(content),
        "size_bytes": len(content),
    }


def validate_inputs() -> dict[str, object]:
    report = load_object(FINAL_VALIDATION)
    progress = load_object(FINAL_PROGRESS)
    v5 = load_object(V5_LOCK)
    route = load_object(ROUTE_CONTRACT)
    p_contract = load_object(P_BACKEND_CONTRACT)
    m_contract = load_object(M_BACKEND_CONTRACT)
    if (
        report.get("status") != "PASS"
        or report.get("issues") != []
        or report.get("learned_outcome_read") is not False
        or report.get("trajectory_outcome_read") is not False
    ):
        raise ValueError("P06 final v4 validation is not an outcome-blind PASS")
    if (
        progress.get("status") != "PASS"
        or progress.get("selected_low_count") != 10
        or progress.get("selected_normal_count") != 10
        or progress.get("all_selected_full_reference_support") is not True
    ):
        raise ValueError("P06 final v4 progress mismatch")
    if (
        v5.get("status") != "READY_FOR_P06_FINAL_SELECTION"
        or method_payload_hash(v5) != v5.get("candidate_lock_hash")
        or v5.get("H2_CONTROL_CONTRACT")
        != "NOT_APPLICABLE_CARRIER_FEEDBACK"
    ):
        raise ValueError("narrowed v5 method route lock mismatch")
    if (
        route.get("status") != "READY_FOR_P06_FINAL_METHOD_FREEZE"
        or payload_hash(route) != route.get("contract_hash")
    ):
        raise ValueError("P04 route contract mismatch")
    if payload_hash(p_contract) != p_contract.get("contract_hash"):
        raise ValueError("P backend contract mismatch")
    if payload_hash(m_contract) != m_contract.get("contract_hash"):
        raise ValueError("M backend contract mismatch")
    manifest = read_csv(FINAL_MANIFEST)
    if len(manifest) != 20 or Counter(row["texture_stratum"] for row in manifest) != {
        "low": 10,
        "normal": 10,
    }:
        raise ValueError("final manifest is not 10+10")
    if any(
        row.get("reference_full_coverage") != "1.0"
        or row.get("reference_grid_count")
        != row.get("reference_supported_grid_count")
        for row in manifest
    ):
        raise ValueError("final manifest contains incomplete reference support")
    return {
        "report": report,
        "progress": progress,
        "v5": v5,
        "route": route,
        "p_contract": p_contract,
        "m_contract": m_contract,
        "manifest": manifest,
    }


def dataset_checksum_content(manifest: list[dict[str, str]]) -> bytes:
    eligibility_rows = read_csv(ELIGIBILITY)
    eligibility = {
        (row["dataset_family"], row["sequence"]): row for row in eligibility_rows
    }
    checksum_rows = read_csv(P02_CHECKSUMS)
    checksums = {row["path"]: row for row in checksum_rows}
    paths: set[str] = set()
    for key in sorted({(row["dataset_family"], row["sequence"]) for row in manifest}):
        row = eligibility.get(key)
        if row is None:
            raise ValueError(f"selected sequence missing eligibility: {key}")
        required = [row["raw_input_path"], row["reference_path"]]
        required.extend(path for path in row["calibration_paths"].split(";") if path)
        paths.update(required)
    lines: list[str] = []
    for path in sorted(paths):
        record = checksums.get(path)
        if (
            record is None
            or record.get("algorithm") != "SHA-256"
            or record.get("status") != "PASS"
            or len(record.get("digest", "")) != 64
        ):
            raise ValueError(f"selected input has no frozen PASS checksum: {path}")
        local = ROOT / path
        if not local.is_file() or local.stat().st_size != int(record["size_bytes"]):
            raise ValueError(f"selected input size drift: {path}")
        lines.append(f"{record['digest']}  {path}")
    if len(lines) != 41:
        raise ValueError(f"expected 41 unique selected input artifacts, got {len(lines)}")
    return ("\n".join(lines) + "\n").encode("ascii")


ARM_FIELDS = [
    "schema_version",
    "protocol_version",
    "window_id",
    "dataset_family",
    "data_domain",
    "sequence",
    "texture_stratum",
    "selection_tier",
    "assignment_rank",
    "pattern_id",
    "order_position",
    "arm",
    "arm_role",
    "applicability",
    "applicability_rule",
    "dependency",
    "algorithmic_replay_slots",
    "scientific_unit",
    "counterbalanced",
    "outcome_boundary",
]


def arm_order_rows(
    manifest: list[dict[str, str]], candidate_lock_hash: str
) -> list[dict[str, object]]:
    ranked = sorted(
        manifest,
        key=lambda row: hashlib.sha256(
            f"{candidate_lock_hash}|{row['window_id']}".encode("ascii")
        ).hexdigest(),
    )
    rows: list[dict[str, object]] = []
    role = {
        B0: "native_vins_reference",
        B1: "strong_external_klt_baseline",
        P_ARM: "proposed_gated_persistent_frontend",
        M_ARM: "controlled_modern_xfeat_baseline",
        D_ARM: "conditional_direct_backend_exposure_ablation",
    }
    for assignment_rank, window in enumerate(ranked, 1):
        pattern_id = (assignment_rank - 1) % len(WILLIAMS_PATTERNS)
        pattern = WILLIAMS_PATTERNS[pattern_id]
        common = {
            "schema_version": ARM_ORDER_SCHEMA,
            "protocol_version": PROTOCOL_VERSION,
            "window_id": window["window_id"],
            "dataset_family": window["dataset_family"],
            "data_domain": window["data_domain"],
            "sequence": window["sequence"],
            "texture_stratum": window["texture_stratum"],
            "selection_tier": window["selection_tier"],
            "assignment_rank": assignment_rank,
            "pattern_id": pattern_id,
            "algorithmic_replay_slots": 3,
            "scientific_unit": "sequence_not_replay",
            "outcome_boundary": OUTCOME_BOUNDARY,
        }
        for position, arm in enumerate(pattern, 1):
            rows.append(
                {
                    **common,
                    "order_position": position,
                    "arm": arm,
                    "arm_role": role[arm],
                    "applicability": "REQUIRED",
                    "applicability_rule": "ALWAYS",
                    "dependency": "NONE",
                    "counterbalanced": "true",
                }
            )
        rows.append(
            {
                **common,
                "order_position": 5,
                "arm": D_ARM,
                "arm_role": role[D_ARM],
                "applicability": "PENDING_APPLICABILITY",
                "applicability_rule": "accepted_learned_born_lineage_count>0",
                "dependency": "P_EXPORT_THEN_EXACT_WHOLE_LINEAGE_DROP_AUDIT",
                "counterbalanced": "false",
            }
        )
    validate_arm_rows(rows)
    return rows


def validate_arm_rows(rows: list[dict[str, object]]) -> None:
    if len(rows) != 100:
        raise ValueError(f"expected 100 arm rows, got {len(rows)}")
    by_window: dict[str, list[dict[str, object]]] = {}
    for window_id, group in itertools.groupby(rows, key=lambda row: str(row["window_id"])):
        by_window[window_id] = list(group)
    if len(by_window) != 20:
        raise ValueError("arm order does not cover 20 unique windows")
    first_counts: Counter[str] = Counter()
    for window_id, values in by_window.items():
        required = [row for row in values if row["applicability"] == "REQUIRED"]
        conditional = [
            row for row in values if row["applicability"] == "PENDING_APPLICABILITY"
        ]
        if {row["arm"] for row in required} != set(REQUIRED_ARMS):
            raise ValueError(f"required arm set mismatch: {window_id}")
        if len(conditional) != 1 or conditional[0]["arm"] != D_ARM:
            raise ValueError(f"conditional D slot mismatch: {window_id}")
        first = next(row for row in required if row["order_position"] == 1)
        first_counts[str(first["arm"])] += 1
    if first_counts != {arm: 5 for arm in REQUIRED_ARMS}:
        raise ValueError(f"unbalanced first positions: {dict(first_counts)}")
    forbidden = {"C_legacy_independent_classical_v3", "B2_all_eligible"}
    if forbidden & {str(row["arm"]) for row in rows}:
        raise ValueError("retired C/B2 arm leaked into arm order")


def render_csv(fields: list[str], rows: list[dict[str, object]]) -> bytes:
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=fields)
    writer.writeheader()
    writer.writerows(rows)
    return stream.getvalue().encode("utf-8")


def environment_content(inputs: dict[str, object]) -> bytes:
    p_contract = inputs["p_contract"]
    m_contract = inputs["m_contract"]
    v5 = inputs["v5"]
    text = f"""IEEE Sensors Journal final native-q environment
==================================================

Schema: isj-environment-nativeq-v5-final-v1
Status: FROZEN_FOR_P07_CONFIRMATORY_EXECUTION
Scientific identity: native-q v3 unchanged
Candidate route lock: {v5['candidate_lock_hash']}
P backend contract: {p_contract['contract_hash']}
M backend contract: {m_contract['contract_hash']}

Backend
-------
Workspace: /home/ma/SLAM/VINS-Fusion-origin
Historical workspace forbidden: /home/ma/SLAM/VINS-Fusion_3-15-WS
Replay concurrency: one VINS/roscore/rosbag instance
VINS multiple_thread: 0
Algorithmic replays per window-arm: 3 serial
Scientific unit: sequence, not replay

Frontend
--------
Preprocess: adaptive_clahe
External feature cap: 350
Backend quality: vins_safe, floor 0.80, alpha 0.65
AQUALOC/NTNU sampling: every_n=2, frame_offset=1
AFRL sampling: every_n=2, frame_offset=0
P entrypoint: scripts/run_isj_nativeq_contract_guarded_v4.sh
M entrypoint: scripts/run_p05_modern_xfeat_baseline_guarded_v2.sh
D audit: scripts/audit_whole_lineage_exact_drop_v1.py

Selection
---------
Screening used KLT/image quality only.
Final selection protocol: isj-window-selection-v4-full-reference
Required arms: B0, B1, P_legacy, M
Conditional arm: D_legacy after P activity and exact-drop audit
Retired with no slots: C_legacy, B2
H2_CONTROL_CONTRACT: NOT_APPLICABLE_CARRIER_FEEDBACK
"""
    return text.encode("ascii")


def method_lock_payload(
    inputs: dict[str, object],
    checksum_content: bytes,
    arm_content: bytes,
    environment: bytes,
) -> dict[str, object]:
    v5 = inputs["v5"]
    route = inputs["route"]
    p_contract = inputs["p_contract"]
    m_contract = inputs["m_contract"]
    payload: dict[str, object] = {
        "schema_version": "isj-method-lock-nativeq-v3-final-v1",
        "status": "FROZEN_FOR_P07_CONFIRMATORY_EXECUTION",
        "protocol_version": PROTOCOL_VERSION,
        "scientific_method_identity": "UNCHANGED_FROM_NATIVEQ_V3",
        "base_candidate_lock_hash": v5["candidate_lock_hash"],
        "p04_route_contract_hash": route["contract_hash"],
        "H2_CONTROL_CONTRACT": "NOT_APPLICABLE_CARRIER_FEEDBACK",
        "arms": {
            "required_every_window": list(REQUIRED_ARMS),
            "conditional_before_trajectory_outcome": list(CONDITIONAL_ARMS),
            "retired_no_slots": [
                "C_legacy_independent_classical_v3",
                "B2_all_eligible",
            ],
        },
        "entrypoints": {
            P_ARM: "scripts/run_isj_nativeq_contract_guarded_v4.sh",
            M_ARM: "scripts/run_p05_modern_xfeat_baseline_guarded_v2.sh",
            D_ARM: "scripts/audit_whole_lineage_exact_drop_v1.py",
        },
        "quality_contracts": {
            "P_B1_D": p_contract["contract_hash"],
            "M": m_contract["contract_hash"],
            "mapping": "vins_safe_floor0p80_alpha0p65",
            "external_feature_cap": 350,
        },
        "selection": {
            "protocol": "isj-window-selection-v4-full-reference",
            "manifest": file_record(FINAL_MANIFEST, root=ROOT),
            "window_audit": file_record(FINAL_AUDIT, root=ROOT),
            "progress": file_record(FINAL_PROGRESS, root=ROOT),
            "validation": file_record(FINAL_VALIDATION, root=ROOT),
            "strata": {"low_or_degraded": 10, "normal": 10},
            "tiers": {
                "ABSOLUTE_LOW": 3,
                "RELATIVE_Q80_FALLBACK": 7,
                "STRICT_NORMAL": 10,
            },
        },
        "data_freeze": {
            "dataset_checksum_manifest": content_record(
                DATASET_CHECKSUM_MANIFEST, checksum_content
            ),
            "selected_unique_input_artifacts": 41,
        },
        "execution_freeze": {
            "arm_order": content_record(ARM_ORDER, arm_content),
            "environment": content_record(FINAL_ENVIRONMENT, environment),
            "algorithmic_replays": 3,
            "minimum_evaluable_replays": 2,
            "numeric_reducer": "median_over_evaluable_replays",
            "hard_failure_and_solver_risk": "any_of_3",
            "scientific_unit": "sequence_not_replay",
        },
        "evaluation": {
            "primary": "G0_common_support_1s_translation_RPE_RMSE",
            "secondary": "G0_valid_SE3_APE_RMSE",
            "evaluator": file_record(
                BUNDLE / "evaluator_protocol_v1.md", root=ROOT
            ),
            "failure_taxonomy": file_record(
                BUNDLE / "failure_taxonomy_v1.yaml", root=ROOT
            ),
        },
        "claim_boundary": route["claim_boundary"],
        "artifacts": [file_record(path, root=ROOT) for path in INPUT_ARTIFACTS],
        "outcome_boundary": OUTCOME_BOUNDARY,
        "held_out_learned_outcome_read": False,
        "held_out_trajectory_outcome_read": False,
        "next_stage": "P07_CONFIRMATORY_FRONTEND_EXPORT_QUEUE",
    }
    payload["method_lock_hash"] = method_payload_hash(
        {**payload, "candidate_lock_hash": payload.get("method_lock_hash")}
    )
    return payload


def final_method_hash(payload: dict[str, object]) -> str:
    clone = dict(payload)
    clone.pop("method_lock_hash", None)
    encoded = json.dumps(
        clone, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def protocol_content(
    method_lock: dict[str, object], checksum_content: bytes, arm_content: bytes
) -> bytes:
    text = f"""# AQUA-FE native-q v3 confirmatory protocol v1

Status: `FROZEN_FOR_P07_CONFIRMATORY_EXECUTION`  
Protocol: `{PROTOCOL_VERSION}`  
Method lock: `{method_lock['method_lock_hash']}`  
Dataset manifest SHA-256: `{file_record(FINAL_MANIFEST, root=ROOT)['sha256']}`  
Dataset checksum manifest SHA-256: `{sha256_bytes(checksum_content)}`  
Arm order SHA-256: `{sha256_bytes(arm_content)}`

## Scientific boundary

The retained method is the frozen native-q v3 learned-seeded persistent
frontend. It is evaluated as a restricted gated component, not as a uniformly
superior detector. The July QG selector and all universal learned-superiority
claims remain retired.

H2 is `NOT_APPLICABLE_CARRIER_FEEDBACK` and must be reported as not tested
under frozen v3. `D_legacy` estimates only the direct backend exposure effect
of published learned-born lineages on the learned-conditioned carrier.

## Frozen data

The final outcome-blind manifest is `dataset_manifest_v4.csv`: 10 degraded/low
and 10 normal windows, 15 sequences, and four domains. All selected evaluator
grids have 100% frozen reference support. The degraded set contains three
`ABSOLUTE_LOW` and seven `RELATIVE_Q80_FALLBACK` windows; results must report
these tiers and may not relabel the fallback tier as satisfying `tau_low`.

The original v2 empty selection and v3 reference-incomplete selection remain
preserved REVISE attempts. No learned export or trajectory outcome was used in
either repair.

## Arms and applicability

Every window runs B0, B1, P_legacy, and M in the frozen Williams order from
`arm_order.csv`. Each arm has three serial algorithmic replays. C_legacy and B2
have no slots.

D_legacy is resolved after P export and before any trajectory/APE/RPE access.
When `accepted_learned_born_lineage_count == 0`, append NOT_APPLICABLE. When it
is positive, derive D by complete learned-born ID lineage deletion and require
`PASS_EXACT_WHOLE_LINEAGE_DROP` before replay. Contract failure blocks D and
the H3 contrast; no seed-only deletion or post-outcome replacement is allowed.

## Execution and evaluation

Use only `/home/ma/SLAM/VINS-Fusion-origin`, one ROS/VINS replay at a time, and
the guarded P/M entrypoints in `method_lock.json`. Reused bags require their
hash-bound attestation. A fallback never counts as P or M.

Primary outcome is G0 common-support 1 s translation RPE RMSE. APE is
secondary only when the G0 support contract is valid. At least two of three
replays are required for a numeric window-arm median; hard failure and solver
risk retain any-of-three flags. Replay does not increase scientific n; sequence
is the independent unit.

All 10 normal windows remain in the no-harm denominator. All failed, blocked,
and zero-action windows remain in their preregistered denominators. Method,
window, or evaluator changes require a new protocol version.
"""
    return text.encode("ascii")


def build_outputs() -> dict[Path, bytes]:
    inputs = validate_inputs()
    manifest = inputs["manifest"]
    checksum_content = dataset_checksum_content(manifest)
    arm_rows = arm_order_rows(manifest, str(inputs["v5"]["candidate_lock_hash"]))
    arm_content = render_csv(ARM_FIELDS, arm_rows)
    environment = environment_content(inputs)
    method_lock = method_lock_payload(
        inputs, checksum_content, arm_content, environment
    )
    method_lock["method_lock_hash"] = final_method_hash(method_lock)
    method_content = (
        json.dumps(method_lock, indent=2, sort_keys=True, ensure_ascii=True) + "\n"
    ).encode("utf-8")
    protocol = protocol_content(method_lock, checksum_content, arm_content)
    outputs: dict[Path, bytes] = {
        DATASET_CHECKSUM_MANIFEST: checksum_content,
        ARM_ORDER: arm_content,
        FINAL_ENVIRONMENT: environment,
        METHOD_LOCK: method_content,
        PROTOCOL: protocol,
    }
    freeze_paths = [
        FINAL_MANIFEST,
        FINAL_AUDIT,
        FINAL_PROGRESS,
        FINAL_VALIDATION,
        V5_LOCK,
        ROUTE_CONTRACT,
        DATASET_CHECKSUM_MANIFEST,
        ARM_ORDER,
        FINAL_ENVIRONMENT,
        METHOD_LOCK,
        PROTOCOL,
    ]
    lines: list[str] = []
    for path in freeze_paths:
        digest = (
            sha256_bytes(outputs[path]) if path in outputs else file_record(path)["sha256"]
        )
        lines.append(f"{digest}  {relative(path)}")
    outputs[FREEZE_HASHES] = ("\n".join(lines) + "\n").encode("ascii")
    return outputs


def write_outputs(outputs: dict[Path, bytes]) -> None:
    existing = [str(path) for path in outputs if path.exists()]
    if existing:
        raise FileExistsError(f"refusing to overwrite final freeze: {existing}")
    temporary = {
        path: path.with_name(f"{path.name}.partial.{os.getpid()}") for path in outputs
    }
    for path, content in outputs.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary[path].write_bytes(content)
    for path in outputs:
        os.replace(temporary[path], path)


def main() -> int:
    outputs = build_outputs()
    write_outputs(outputs)
    method = json.loads(outputs[METHOD_LOCK].decode("utf-8"))
    print(
        "P06_FINAL_FREEZE_PASS "
        f"method_lock={method['method_lock_hash']} outputs={len(outputs)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
