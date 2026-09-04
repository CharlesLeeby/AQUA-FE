#!/usr/bin/env python3
"""Audit the frozen A06/H07 same-history system comparison.

This program is deliberately analysis-only.  It never starts ROS, VINS, an
exporter, HFNet, or a GPU process.  Once all formal VINS arms have terminal
``formal_run_receipt_v1.json`` receipts, it may invoke the already validated
``evaluate_vins_common_support.py`` CPU evaluator.  Missing receipts are
PENDING even when a run directory contains partial files.

The output is descriptive.  Both score windows have only 13 native COLMAP
proxy rows, so the formal APE/RPE gate remains closed by construction.  The
script may retain evaluator numbers as explicitly labelled descriptive proxy
errors, but it never computes a winner, a cross-window mean, a p-value, or a
failure-as-zero penalty.
"""

from __future__ import annotations

import argparse
import bisect
import csv
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, ROUND_HALF_EVEN
import hashlib
import json
import math
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
from typing import Any, Iterable, Mapping, Optional, Sequence


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_LOCK = ROOT / "papers/samehistory_system_comparison_v1_execution_lock.json"
DEFAULT_PROTOCOL = ROOT / "papers/samehistory_system_comparison_v1_protocol.md"
DEFAULT_A06_KLT_CORRECTIVE_PROTOCOL = (
    ROOT / "papers/samehistory_system_comparison_v1_a06_klt_corrective_replay_protocol.md"
)
DEFAULT_HFNET_BUNDLE = (
    ROOT
    / "papers/hfnet_multiwindow_strict_analysis_v2_1"
    / "hfnet_multiwindow_analysis_bundle_v2.json"
)
DEFAULT_OUTPUT = ROOT / "papers/samehistory_system_comparison_v1_analysis"
EVALUATOR = ROOT / "scripts/evaluate_vins_common_support.py"
RECEIPT_NAME = "formal_run_receipt_v1.json"

A06_KLT_CORRECTIVE_PROTOCOL_SHA256 = (
    "4f4c96e435c94331a8e185d1c30899d6d88156a86dc118fce6076f3025016571"
)
A06_KLT_FROZEN_SOURCE = {
    "feature_bag": {
        "relative_path": "runs/a06/external_klt/features.bag",
        "size_bytes": 37_403_698,
        "sha256": "0779bb8a71e4d81ddf02ba933b7428e548534ab580fd4483754f08e26e9bbeb6",
    },
    "frontend_metrics": {
        "relative_path": "runs/a06/external_klt/frontend_metrics.csv",
        "sha256": "aab2266ace8f565ff39faf475889e6f8face3345b40385fb894d435eafdfd25e",
    },
    "vins_config": {
        "relative_path": "runs/a06/external_klt/vins_aqualoc_archaeo_external.yaml",
        "sha256": "e3b0ef0badfbe4392b3c29f59b1dd0a4d6c5260b528bf7380dc0b17ac4de19d0",
    },
    "camera_config": {
        "relative_path": "runs/a06/external_klt/aqualoc_archaeo06_pinhole.yaml",
        "sha256": "045505013a5dbfb629bad8d3463bbbdacad965ebdcf3c590598121bd884e50a5",
    },
}
A06_KLT_CORRECTIVE_RUNNER = ROOT / "scripts/run_existing_featurebag_vins_eval.sh"
A06_KLT_CORRECTIVE_RUNNER_SHA256 = (
    "2233e2be8bf9f9db3eb691392218b59bd7f9fbbe741bf51b6bea40316d509f8e"
)
A06_KLT_VINS_NODE = Path(
    "/home/ma/SLAM/VINS-Fusion-origin/devel/lib/vins/vins_node"
)
A06_KLT_VINS_NODE_SHA256 = (
    "4e91d8ac0735163fb6617e18d64ae0de91cc903d036f0e568a29bd3e5f5f4278"
)

SCHEMA = "aqua-fe-samehistory-system-analysis-v1"
WINDOW_ORDER = ("A06", "H07")
ARM_ORDER = ("vanilla_origin", "external_klt", "aquafe_proposed_safe")
METHOD_ORDER = ARM_ORDER + ("hfnet_slam",)
COMMON_ARM_NAMES = {
    "vanilla_origin": "VANILLA_ORIGIN",
    "external_klt": "EXTERNAL_KLT",
    "aquafe_proposed_safe": "AQUAFE_PROPOSED_SAFE",
    "hfnet_slam": "HFNET_SLAM",
}

WINDOWS: Mapping[str, Mapping[str, Any]] = {
    "A06": {
        "lock_prefix": "a06",
        "feed": (0, 2460),
        "score": (2210, 2460),
        "camera_csv": Path(
            "/mnt/data/AQUA-FE_WS/datasets/hfnet_v6_a06_exact_window_v1/"
            "aqualoc_archaeology_a06_0000_2460/mav0/cam0/data.csv"
        ),
        "raw_bag_name": "archaeo06_0000_2460.bag",
        "external_phase": 1,
        "external_score_expected": 125,
        "reference_native_rows": 13,
        "nominal_reference_rate_hz": 1.0,
        "evaluation_rate_hz": 1.0,
        "max_reference_gap_s": 2.5,
        "hfnet_window_id": "A06_SCORE_2210_2460",
        "hfnet_bridge": Path(
            "/mnt/data/AQUA-FE_WS/logs/published_hfnet_slam_v6/fresh_underwater/"
            "aqualoc_archaeology_a06_0000_2460/attempt_001/bridges/"
            "hfnet_world_T_body_vins_csv_v1.csv"
        ),
    },
    "H07": {
        "lock_prefix": "h07",
        "feed": (1, 1720),
        "score": (1660, 1720),
        "camera_csv": Path(
            "/mnt/data/AQUA-FE_WS/datasets/hfnet_v6_h07_exact_window_v1/"
            "aqualoc_harbor_h07_0001_1720/mav0/cam0/data.csv"
        ),
        "raw_bag_name": "harbor07_0001_1720.bag",
        "external_phase": 0,
        "external_score_expected": 31,
        "reference_native_rows": 13,
        "nominal_reference_rate_hz": 4.0,
        "evaluation_rate_hz": 2.0,
        "max_reference_gap_s": 0.625,
        "hfnet_window_id": "H07_SCORE_1660_1720",
        "hfnet_bridge": Path(
            "/mnt/data/AQUA-FE_WS/logs/published_hfnet_slam_v6/fresh_underwater/"
            "aqualoc_harbor_h07_0001_1720/attempt_001/bridges/"
            "hfnet_world_T_body_vins_csv_v1.csv"
        ),
    },
}

RUN_SUBDIR = {
    "a06_vanilla_origin": ("a06", "vanilla_origin"),
    "a06_external_klt": ("a06", "external_klt"),
    "a06_aquafe_proposed_safe": ("a06", "aquafe_proposed_safe"),
    "h07_vanilla_origin": ("h07", "vanilla_origin"),
    "h07_external_klt": ("h07", "external_klt"),
    "h07_aquafe_proposed_safe": ("h07", "aquafe_proposed_safe"),
}


class EvidenceError(RuntimeError):
    """A frozen input is missing, malformed, contradictory, or stale."""


@dataclass(frozen=True)
class CameraGrid:
    sequence: str
    feed_start: int
    feed_end: int
    stamps_ns: tuple[int, ...]
    path: Path

    def stamp_for_source(self, source_index: int) -> int:
        offset = source_index - self.feed_start
        if offset < 0 or offset >= len(self.stamps_ns):
            raise EvidenceError(
                f"{self.sequence}:SOURCE_INDEX_OUTSIDE_CAMERA_GRID:{source_index}"
            )
        return self.stamps_ns[offset]

    def source_for_offset(self, offset: int) -> int:
        return self.feed_start + offset


@dataclass(frozen=True)
class ArmPaths:
    lock_id: str
    sequence: str
    method: str
    run_dir: Path
    receipt: Path
    trajectory: Path
    vins_log: Path
    frontend_metrics: Optional[Path]
    vins_config: Path


def read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise EvidenceError(f"MISSING_JSON:{path}") from error
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise EvidenceError(f"UNREADABLE_JSON:{path}:{type(error).__name__}") from error
    if not isinstance(value, dict):
        raise EvidenceError(f"JSON_ROOT_NOT_OBJECT:{path}")
    return value


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def identity(path: Path) -> dict[str, Any]:
    return {
        "path": str(path),
        "size_bytes": path.stat().st_size,
        "sha256": sha256(path),
    }


def verify_protocol_lock(lock_path: Path, protocol_path: Path) -> dict[str, Any]:
    lock = read_json(lock_path)
    if lock.get("schema_version") != (
        "aqua-fe-samehistory-system-comparison-execution-lock-v1"
    ):
        raise EvidenceError("EXECUTION_LOCK_SCHEMA_DRIFT")
    identities = lock.get("identities")
    policy = lock.get("policy")
    arms = lock.get("arms")
    if not isinstance(identities, Mapping) or not isinstance(policy, Mapping):
        raise EvidenceError("EXECUTION_LOCK_CORE_FIELDS_MISSING")
    if not isinstance(arms, Mapping):
        raise EvidenceError("EXECUTION_LOCK_ARMS_MISSING")
    if identities.get("protocol_sha256") != sha256(protocol_path):
        raise EvidenceError("FROZEN_PROTOCOL_SHA256_DRIFT")
    if policy.get("arm_order") != list(RUN_SUBDIR):
        raise EvidenceError("FROZEN_ARM_ORDER_DRIFT")
    if set(arms) != set(RUN_SUBDIR):
        raise EvidenceError("FROZEN_ARM_SET_DRIFT")
    if policy.get("one_launch_per_arm") is not True:
        raise EvidenceError("ONE_LAUNCH_POLICY_DRIFT")
    if policy.get("result_informed_retry") is not False:
        raise EvidenceError("ZERO_RESULT_INFORMED_RETRY_POLICY_DRIFT")
    if policy.get("vins_multiple_thread") != 1:
        raise EvidenceError("VINS_MULTIPLE_THREAD_POLICY_DRIFT")
    return lock


def resolve_trajectory(run_dir: Path) -> Path:
    nested = run_dir / "vins_output" / "vio.csv"
    legacy = run_dir / "vio.csv"
    if nested.is_file():
        return nested
    if legacy.is_file():
        return legacy
    return nested


def resolve_arm_paths(lock: Mapping[str, Any]) -> dict[str, ArmPaths]:
    policy = lock["policy"]
    artifact_root = Path(str(policy["large_artifact_root"]))
    result: dict[str, ArmPaths] = {}
    for lock_id, (sequence_dir, method) in RUN_SUBDIR.items():
        sequence = sequence_dir.upper()
        run_dir = artifact_root / "runs" / sequence_dir / method
        if sequence == "A06":
            config_name = (
                "vins_aqualoc_archaeo_origin.yaml"
                if method == "vanilla_origin"
                else "vins_aqualoc_archaeo_external.yaml"
            )
        else:
            config_name = (
                "vins_aqualoc_origin.yaml"
                if method == "vanilla_origin"
                else "vins_aqualoc_external.yaml"
            )
        result[lock_id] = ArmPaths(
            lock_id=lock_id,
            sequence=sequence,
            method=method,
            run_dir=run_dir,
            receipt=run_dir / RECEIPT_NAME,
            trajectory=resolve_trajectory(run_dir),
            vins_log=run_dir / "vins.log",
            frontend_metrics=(
                None if method == "vanilla_origin" else run_dir / "frontend_metrics.csv"
            ),
            vins_config=run_dir / config_name,
        )
    return result


def corrective_a06_klt_paths(artifact_root: Path) -> ArmPaths:
    run_dir = artifact_root / "runs" / "a06" / "external_klt_corrective_replay"
    return ArmPaths(
        lock_id="a06_external_klt_corrective_replay",
        sequence="A06",
        method="external_klt",
        run_dir=run_dir,
        receipt=run_dir / RECEIPT_NAME,
        trajectory=resolve_trajectory(run_dir),
        vins_log=run_dir / "vins.log",
        frontend_metrics=run_dir / "frontend_metrics.csv",
        vins_config=run_dir / "vins_aqualoc_archaeo_external.yaml",
    )


def identity_matches_claim(path: Path, claim: object) -> bool:
    if not path.is_file() or not isinstance(claim, Mapping):
        return False
    if claim.get("path") != str(path):
        return False
    if claim.get("sha256") != sha256(path):
        return False
    claimed_size = claim.get("size_bytes")
    return claimed_size is None or claimed_size == path.stat().st_size


def parse_replay_manifest(path: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    if not path.is_file():
        return result
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        result[key.strip()] = value.strip()
    return result


def normalize_only_output_path(config_path: Path) -> bytes:
    payload = config_path.read_bytes()
    return re.sub(
        br'(?m)^output_path:[^\r\n]*$',
        b'output_path: "<FROZEN_CORRECTIVE_OUTPUT>"',
        payload,
    )


def frozen_source_payload_audit(artifact_root: Path) -> dict[str, Any]:
    files: dict[str, Any] = {}
    errors: list[str] = []
    for name, contract in A06_KLT_FROZEN_SOURCE.items():
        path = artifact_root / str(contract["relative_path"])
        record: dict[str, Any] = {"path": str(path), "exists": path.is_file()}
        if path.is_file():
            record.update(identity(path))
            if record["sha256"] != contract["sha256"]:
                errors.append(f"FROZEN_{name.upper()}_SHA256_MISMATCH")
            expected_size = contract.get("size_bytes")
            if expected_size is not None and record["size_bytes"] != expected_size:
                errors.append(f"FROZEN_{name.upper()}_SIZE_MISMATCH")
        else:
            errors.append(f"FROZEN_{name.upper()}_MISSING")
        files[name] = record
    for label, path, expected in (
        ("CORRECTIVE_RUNNER", A06_KLT_CORRECTIVE_RUNNER, A06_KLT_CORRECTIVE_RUNNER_SHA256),
        ("VINS_NODE", A06_KLT_VINS_NODE, A06_KLT_VINS_NODE_SHA256),
    ):
        if not path.is_file() or sha256(path) != expected:
            errors.append(f"FROZEN_{label}_SHA256_MISMATCH_OR_MISSING")
        files[label.lower()] = identity(path) if path.is_file() else {"path": str(path), "exists": False}
    return {
        "state": "PASS" if not errors else "FAIL",
        "files": files,
        "errors": errors,
    }


def exact_original_a06_klt_incident(
    original: ArmPaths, expected_lock_sha256: str
) -> tuple[bool, dict[str, Any]]:
    receipt_audit = audit_receipt(original.receipt)
    errors: list[str] = []
    if not original.receipt.is_file():
        return False, {"state": "NO_TERMINAL_ORIGINAL_RECEIPT", "errors": []}
    value = read_json(original.receipt)
    if value.get("status") != "INFRASTRUCTURE_CENSORED_SUPERVISOR_TIMEOUT_DURING_REPLAY":
        return False, {"state": "NOT_THE_FROZEN_INFRASTRUCTURE_INCIDENT", "errors": []}
    if (
        receipt_audit.get("raw_return_code") != 124
        or receipt_audit.get("launch_count") != 1
        or receipt_audit.get("retry_count") != 0
    ):
        errors.append("ORIGINAL_CENSORED_EXECUTION_FIELDS_DRIFT")
    stage = value.get("failure_stage")
    required_stage = {
        "offline_feature_export_completed": True,
        "vins_replay_started": True,
        "vins_replay_completed": False,
        "legacy_evaluator_started": False,
        "score_window_reached": False,
        "algorithmic_usability_adjudicated": False,
    }
    if not isinstance(stage, Mapping) or any(stage.get(key) != expected for key, expected in required_stage.items()):
        errors.append("ORIGINAL_CENSORED_FAILURE_STAGE_DRIFT")
    interpretation = value.get("interpretation")
    if not isinstance(interpretation, Mapping) or (
        interpretation.get("algorithm_failure") is not False
        or interpretation.get("formal_usability_result_available") is not False
        or interpretation.get("partial_trajectory_eligible_for_score_or_accuracy") is not False
        or interpretation.get("same_namespace_may_be_reused") is not False
    ):
        errors.append("ORIGINAL_CENSORED_INTERPRETATION_DRIFT")
    claims = value.get("identities")
    if not isinstance(claims, Mapping):
        errors.append("ORIGINAL_CENSORED_IDENTITIES_MISSING")
    else:
        if claims.get("execution_lock_sha256") != expected_lock_sha256:
            errors.append("ORIGINAL_CENSORED_EXECUTION_LOCK_SHA256_MISMATCH")
        source_feature = original.run_dir / "features.bag"
        if not identity_matches_claim(source_feature, claims.get("features_bag")):
            errors.append("ORIGINAL_CENSORED_FEATURE_BAG_CLAIM_MISMATCH")
        source_metrics = original.run_dir / "frontend_metrics.csv"
        if not identity_matches_claim(source_metrics, claims.get("frontend_metrics")):
            errors.append("ORIGINAL_CENSORED_FRONTEND_METRICS_CLAIM_MISMATCH")
        if not identity_matches_claim(original.trajectory, claims.get("partial_vio_csv")):
            errors.append("ORIGINAL_CENSORED_PARTIAL_VIO_CLAIM_MISMATCH")
        if not identity_matches_claim(original.vins_log, claims.get("partial_vins_log")):
            errors.append("ORIGINAL_CENSORED_PARTIAL_LOG_CLAIM_MISMATCH")
    return True, {
        "state": "VALID_INFRASTRUCTURE_CENSORED_INCIDENT" if not errors else "INVALID_INCIDENT_EVIDENCE",
        "algorithm_failure": False,
        "partial_trajectory_score_eligible": False,
        "receipt": receipt_audit,
        "failure_stage": dict(stage) if isinstance(stage, Mapping) else stage,
        "errors": errors,
    }


def corrective_feature_claim(receipt: Mapping[str, Any]) -> object:
    claims = receipt.get("claimed_identities")
    if not isinstance(claims, Mapping):
        return None
    for key in (
        "source_feature_bag",
        "source_features_bag",
        "feature_bag",
        "features_bag",
    ):
        if key in claims:
            return claims[key]
    return None


def resolve_a06_klt_corrective_adoption(
    lock: Mapping[str, Any], paths: Mapping[str, ArmPaths], lock_sha256: str
) -> tuple[dict[str, Any], ArmPaths]:
    """Select the additive backend replay only through the frozen adoption gate."""

    original = paths["a06_external_klt"]
    incident_applies, incident = exact_original_a06_klt_incident(
        original, lock_sha256
    )
    if not incident_applies:
        return {
            "state": "NOT_APPLICABLE",
            "original_incident": incident,
            "adopted": False,
            "errors": [],
        }, original
    artifact_root = Path(str(lock["policy"]["large_artifact_root"]))
    protocol_identity = identity(DEFAULT_A06_KLT_CORRECTIVE_PROTOCOL)
    source_audit = frozen_source_payload_audit(artifact_root)
    errors = list(incident.get("errors") or []) + list(source_audit["errors"])
    if protocol_identity["sha256"] != A06_KLT_CORRECTIVE_PROTOCOL_SHA256:
        errors.append("CORRECTIVE_PROTOCOL_SHA256_DRIFT")
    corrective = corrective_a06_klt_paths(artifact_root)
    receipt = audit_receipt(corrective.receipt)
    record: dict[str, Any] = {
        "protocol": protocol_identity,
        "original_incident": incident,
        "frozen_source_payload": source_audit,
        "corrective_namespace": str(corrective.run_dir),
        "corrective_receipt": receipt,
        "original_partial_trajectory_scored": False,
        "original_namespace_rewritten": False,
        "backend_corrective_is_independent_method_repeat": False,
        "errors": errors,
    }
    if errors:
        record.update({"state": "REJECTED_FROZEN_EVIDENCE_INVALID", "adopted": False})
        return record, original
    if receipt["state"] == "PENDING_MISSING_RECEIPT":
        record.update({"state": "PENDING_CORRECTIVE_REPLAY", "adopted": False})
        return record, original
    if (
        receipt["state"] != "TERMINAL"
        or not receipt["policy_compliant"]
        or receipt["raw_return_code"] != 0
        or receipt.get("schema_version") != "aqua-fe-samehistory-formal-run-receipt-v1"
        or receipt.get("arm_id") != "a06_external_klt_corrective_replay"
    ):
        record["errors"].append("CORRECTIVE_RECEIPT_NOT_COMPLIANT_RC0_ONE_SHOT")
        record.update({"state": "TERMINAL_CORRECTIVE_NOT_ADOPTED", "adopted": False})
        return record, original
    source_feature = original.run_dir / "features.bag"
    if not identity_matches_claim(source_feature, corrective_feature_claim(receipt)):
        record["errors"].append("CORRECTIVE_RECEIPT_SOURCE_FEATURE_BAG_IDENTITY_MISMATCH")
    corrective_contract = receipt.get("corrective_contract")
    if not isinstance(corrective_contract, Mapping) or (
        corrective_contract.get("protocol_path") != str(DEFAULT_A06_KLT_CORRECTIVE_PROTOCOL)
        or corrective_contract.get("protocol_sha256") != A06_KLT_CORRECTIVE_PROTOCOL_SHA256
        or corrective_contract.get("original_terminal_receipt_path") != str(original.receipt)
        or corrective_contract.get("original_terminal_receipt_sha256") != sha256(original.receipt)
        or corrective_contract.get("original_namespace_modified") is not False
        or corrective_contract.get("front_end_recomputed") is not False
        or corrective_contract.get("result_informed_change") is not False
    ):
        record["errors"].append("CORRECTIVE_RECEIPT_CONTRACT_PROVENANCE_MISMATCH")
    corrective_claims = receipt.get("claimed_identities")
    if not isinstance(corrective_claims, Mapping) or (
        corrective_claims.get("replay_runner_sha256") != A06_KLT_CORRECTIVE_RUNNER_SHA256
        or corrective_claims.get("vins_node_sha256") != A06_KLT_VINS_NODE_SHA256
        or corrective_claims.get("source_frontend_metrics_sha256")
        != A06_KLT_FROZEN_SOURCE["frontend_metrics"]["sha256"]
    ):
        record["errors"].append("CORRECTIVE_RECEIPT_RUNTIME_OR_FRONTEND_IDENTITY_MISMATCH")
    for error in validate_receipt_artifact_claims(receipt, corrective, None):
        record["errors"].append(f"CORRECTIVE_{error}")
    manifest = parse_replay_manifest(corrective.run_dir / "replay_manifest.txt")
    if (
        manifest.get("feature_bag") != str(source_feature)
        or manifest.get("play_bag") != str(source_feature)
    ):
        record["errors"].append("CORRECTIVE_REPLAY_MANIFEST_SOURCE_FEATURE_BAG_MISMATCH")
    manifest_path = corrective.run_dir / "replay_manifest.txt"
    if (
        not isinstance(corrective_claims, Mapping)
        or not manifest_path.is_file()
        or corrective_claims.get("replay_manifest_sha256") != sha256(manifest_path)
    ):
        record["errors"].append("CORRECTIVE_REPLAY_MANIFEST_SHA256_CLAIM_MISMATCH")
    if corrective.frontend_metrics is None or not corrective.frontend_metrics.is_file():
        record["errors"].append("CORRECTIVE_FRONTEND_METRICS_COPY_MISSING")
    elif sha256(corrective.frontend_metrics) != A06_KLT_FROZEN_SOURCE["frontend_metrics"]["sha256"]:
        record["errors"].append("CORRECTIVE_FRONTEND_METRICS_COPY_SHA256_MISMATCH")
    if not corrective.vins_config.is_file():
        record["errors"].append("CORRECTIVE_VINS_CONFIG_MISSING")
    else:
        source_config = original.vins_config
        if normalize_only_output_path(corrective.vins_config) != normalize_only_output_path(source_config):
            record["errors"].append("CORRECTIVE_CONFIG_CHANGED_BEYOND_OUTPUT_PATH")
    if record["errors"]:
        record.update({"state": "TERMINAL_CORRECTIVE_NOT_ADOPTED", "adopted": False})
        return record, original
    record.update(
        {
            "state": "ADOPTED_EXACT_BACKEND_ONLY_CORRECTIVE_REPLAY",
            "adopted": True,
            "selected_run_dir": str(corrective.run_dir),
            "source_feature_bag": identity(source_feature),
        }
    )
    return record, corrective


def parse_timestamp_ns(raw: str, *, seconds_allowed: bool = True) -> int:
    stripped = raw.strip()
    try:
        value = Decimal(stripped)
    except InvalidOperation as error:
        raise ValueError(f"invalid timestamp {raw!r}") from error
    if not value.is_finite():
        raise ValueError(f"non-finite timestamp {raw!r}")
    # Epoch-scale integer nanoseconds are >= 1e15 for these sequences.  A
    # decimal seconds stamp is around 1e9 and is converted without float64.
    if seconds_allowed and abs(value) < Decimal("1e12"):
        value *= Decimal("1000000000")
    integral = value.to_integral_value(rounding=ROUND_HALF_EVEN)
    if abs(value - integral) > Decimal("0.5"):
        raise ValueError(f"timestamp is not representable in integer ns: {raw!r}")
    return int(integral)


def load_camera_grid(
    path: Path, sequence: str, feed_start: int, feed_end: int
) -> CameraGrid:
    stamps: list[int] = []
    with path.open(newline="", encoding="utf-8") as handle:
        for line_number, row in enumerate(csv.reader(handle), 1):
            if not row or not any(value.strip() for value in row):
                continue
            if row[0].lstrip().startswith("#"):
                continue
            try:
                stamp = parse_timestamp_ns(row[0], seconds_allowed=False)
            except ValueError as error:
                raise EvidenceError(f"{path}:{line_number}:INVALID_CAMERA_STAMP") from error
            stamps.append(stamp)
    expected = feed_end - feed_start + 1
    if len(stamps) != expected:
        raise EvidenceError(
            f"{sequence}:CAMERA_ROW_COUNT_MISMATCH:{len(stamps)}!={expected}"
        )
    if any(right <= left for left, right in zip(stamps, stamps[1:])):
        raise EvidenceError(f"{sequence}:CAMERA_TIMESTAMPS_NOT_STRICT")
    return CameraGrid(sequence, feed_start, feed_end, tuple(stamps), path)


def load_trajectory(path: Path) -> dict[str, Any]:
    stamps: list[int] = []
    finite_rows = 0
    nonfinite_rows = 0
    malformed_rows = 0
    if not path.is_file():
        return {
            "state": "MISSING",
            "path": str(path),
            "pose_count": 0,
            "finite_count": 0,
            "nonfinite_count": 0,
            "malformed_count": 0,
            "strictly_increasing": False,
            "stamps_ns": [],
        }
    with path.open(newline="", encoding="utf-8", errors="replace") as handle:
        for row in csv.reader(handle):
            if not row or not any(value.strip() for value in row):
                continue
            if len(row) < 8:
                malformed_rows += 1
                continue
            try:
                stamp = parse_timestamp_ns(row[0])
                pose = [float(value) for value in row[1:8]]
            except ValueError:
                malformed_rows += 1
                continue
            if not all(math.isfinite(value) for value in pose):
                nonfinite_rows += 1
                continue
            stamps.append(stamp)
            finite_rows += 1
    strict = bool(stamps) and all(
        right > left for left, right in zip(stamps, stamps[1:])
    )
    valid = finite_rows > 0 and nonfinite_rows == 0 and malformed_rows == 0 and strict
    return {
        "state": "VALID" if valid else "INVALID",
        "path": str(path),
        "pose_count": finite_rows + nonfinite_rows + malformed_rows,
        "finite_count": finite_rows,
        "nonfinite_count": nonfinite_rows,
        "malformed_count": malformed_rows,
        "strictly_increasing": strict,
        "first_timestamp_ns": stamps[0] if stamps else None,
        "last_timestamp_ns": stamps[-1] if stamps else None,
        "stamps_ns": stamps,
    }


def percentile(values: Sequence[int], fraction: float) -> Optional[float]:
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * fraction
    left = int(math.floor(position))
    right = int(math.ceil(position))
    if left == right:
        return float(ordered[left])
    weight = position - left
    return float(ordered[left] * (1.0 - weight) + ordered[right] * weight)


def associate_stamps_to_camera(
    stamps_ns: Sequence[int], camera: CameraGrid, tolerance_ns: int = 5_000_000
) -> dict[str, Any]:
    associations: list[Optional[int]] = []
    errors: list[int] = []
    ambiguous_nearest = 0
    camera_stamps = camera.stamps_ns
    for stamp in stamps_ns:
        right = bisect.bisect_left(camera_stamps, stamp)
        candidates: list[int] = []
        if right < len(camera_stamps):
            candidates.append(right)
        if right > 0:
            candidates.append(right - 1)
        if not candidates:
            associations.append(None)
            continue
        ranked = sorted((abs(camera_stamps[index] - stamp), index) for index in candidates)
        if len(ranked) == 2 and ranked[0][0] == ranked[1][0]:
            ambiguous_nearest += 1
        error, offset = ranked[0]
        if error > tolerance_ns:
            associations.append(None)
            continue
        associations.append(camera.source_for_offset(offset))
        errors.append(error)
    matched = [value for value in associations if value is not None]
    unique = sorted(set(matched))
    duplicate_count = len(matched) - len(unique)
    return {
        "total_pose_count": len(stamps_ns),
        "matched_pose_count": len(matched),
        "unmatched_pose_count": len(stamps_ns) - len(matched),
        "unique_source_count": len(unique),
        "duplicate_source_association_count": duplicate_count,
        "ambiguous_nearest_count": ambiguous_nearest,
        "max_abs_error_ns": max(errors) if errors else None,
        "p95_abs_error_ns": percentile(errors, 0.95),
        "tolerance_ns": tolerance_ns,
        "source_indices": associations,
        "unique_source_indices": unique,
    }


def longest_expected_run(covered: Iterable[int], expected: Sequence[int]) -> int:
    covered_set = set(covered)
    best = 0
    current = 0
    for index in expected:
        if index in covered_set:
            current += 1
            best = max(best, current)
        else:
            current = 0
    return best


def score_support(
    sequence: str,
    method: str,
    camera: CameraGrid,
    association: Mapping[str, Any],
) -> dict[str, Any]:
    window = WINDOWS[sequence]
    score_start, score_end = window["score"]
    camera_expected = list(range(score_start, score_end + 1))
    associated_all = [
        value for value in association["source_indices"] if value is not None
    ]
    associated_score = sorted(
        set(value for value in associated_all if score_start <= value <= score_end)
    )
    parity_counts = {
        "even": sum(1 for value in associated_all if value % 2 == 0),
        "odd": sum(1 for value in associated_all if value % 2 == 1),
    }
    if method in ("external_klt", "aquafe_proposed_safe"):
        phase = int(window["external_phase"])
        phase_source = "FROZEN_EXTERNAL_EVERY2_FRAME_OFFSET1"
        phase_confidence = 1.0
    else:
        total = parity_counts["even"] + parity_counts["odd"]
        dominant_count = max(parity_counts.values()) if total else 0
        phase_confidence = dominant_count / total if total else 0.0
        phase = 0 if parity_counts["even"] >= parity_counts["odd"] else 1
        phase_source = "OBSERVED_ORIGIN_MT1_TIMESTAMP_ASSOCIATION"
    native_expected = [value for value in camera_expected if value % 2 == phase]
    if method == "vanilla_origin" and phase_confidence < 0.95:
        phase_state = "AMBIGUOUS"
    else:
        phase_state = "PASS"
    if method != "vanilla_origin" and len(native_expected) != int(
        window["external_score_expected"]
    ):
        raise EvidenceError(f"{sequence}:FROZEN_EXTERNAL_EXPECTED_GRID_DRIFT")
    covered_native = sorted(set(associated_score).intersection(native_expected))
    longest = longest_expected_run(covered_native, native_expected)
    native_count = len(native_expected)
    native_coverage = len(covered_native) / native_count if native_count else 0.0
    contiguous_fraction = longest / native_count if native_count else 0.0
    camera_coverage = len(associated_score) / len(camera_expected)
    first_source = min(associated_score) if associated_score else None
    first_delay_s = (
        (camera.stamp_for_source(first_source) - camera.stamp_for_source(score_start))
        / 1e9
        if first_source is not None
        else None
    )
    return {
        "score_source_range": [score_start, score_end],
        "phase": "even" if phase == 0 else "odd",
        "phase_source": phase_source,
        "phase_state": phase_state,
        "phase_confidence": phase_confidence,
        "associated_feed_parity_counts": parity_counts,
        "method_native_expected_count": native_count,
        "method_native_expected_first_source": native_expected[0] if native_expected else None,
        "method_native_expected_last_source": native_expected[-1] if native_expected else None,
        "method_native_covered_count": len(covered_native),
        "method_native_coverage_fraction": native_coverage,
        "method_native_longest_contiguous_count": longest,
        "method_native_longest_contiguous_fraction": contiguous_fraction,
        "camera_grid_expected_count": len(camera_expected),
        "camera_grid_covered_count": len(associated_score),
        "camera_grid_coverage_fraction": camera_coverage,
        "first_score_output_source": first_source,
        "first_score_output_delay_s": first_delay_s,
        "covered_source_indices": covered_native,
    }


def _find_first(mapping: Mapping[str, Any], names: Sequence[str]) -> Any:
    for name in names:
        if name in mapping:
            return mapping[name]
    execution = mapping.get("execution")
    if isinstance(execution, Mapping):
        for name in names:
            if name in execution:
                return execution[name]
    return None


def audit_receipt(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {
            "state": "PENDING_MISSING_RECEIPT",
            "path": str(path),
            "raw_return_code": None,
            "launch_count": None,
            "retry_count": None,
            "policy_compliant": False,
            "errors": ["FORMAL_RUN_RECEIPT_MISSING"],
        }
    try:
        value = read_json(path)
    except EvidenceError as error:
        return {
            "state": "INVALID_RECEIPT",
            "path": str(path),
            "raw_return_code": None,
            "launch_count": None,
            "retry_count": None,
            "policy_compliant": False,
            "errors": [str(error)],
        }
    raw_rc = _find_first(value, ("raw_return_code", "raw_returncode", "return_code"))
    launch_count = _find_first(
        value, ("launch_count", "process_start_count", "popen_invocations")
    )
    retry_count = _find_first(value, ("retry_count",))
    if launch_count is None:
        one_launch = _find_first(value, ("one_launch", "one_launch_per_arm"))
        if isinstance(one_launch, bool):
            launch_count = 1 if one_launch else None
    if retry_count is None:
        zero_retry = _find_first(value, ("zero_retry",))
        if isinstance(zero_retry, bool):
            retry_count = 0 if zero_retry else None
    errors: list[str] = []
    for label, raw in (
        ("RAW_RETURN_CODE", raw_rc),
        ("LAUNCH_COUNT", launch_count),
        ("RETRY_COUNT", retry_count),
    ):
        if isinstance(raw, bool) or not isinstance(raw, int):
            errors.append(f"{label}_MISSING_OR_NONINTEGER")
    policy_compliant = (
        not errors and int(launch_count) == 1 and int(retry_count) == 0
    )
    if not errors and int(launch_count) != 1:
        errors.append("LAUNCH_COUNT_NOT_ONE")
    if not errors and int(retry_count) != 0:
        errors.append("RETRY_COUNT_NOT_ZERO")
    return {
        "state": "TERMINAL" if not errors else "TERMINAL_RECEIPT_INCOMPLETE_OR_NONCOMPLIANT",
        "path": str(path),
        "raw_return_code": raw_rc if isinstance(raw_rc, int) and not isinstance(raw_rc, bool) else None,
        "launch_count": launch_count if isinstance(launch_count, int) and not isinstance(launch_count, bool) else None,
        "retry_count": retry_count if isinstance(retry_count, int) and not isinstance(retry_count, bool) else None,
        "policy_compliant": policy_compliant,
        "started_at_local": _find_first(value, ("started_at_local", "start_local")),
        "ended_at_local": _find_first(value, ("ended_at_local", "end_local")),
        "wall_time_s": _find_first(
            value, ("tool_wall_time_s", "wall_time_s", "wall_time_seconds")
        ),
        "schema_version": value.get("schema_version"),
        "arm_id": value.get("arm_id"),
        "claimed_identities": value.get("identities"),
        "corrective_contract": value.get("corrective_contract"),
        "errors": errors,
        "identity": identity(path),
    }


LOG_PATTERNS: Mapping[str, re.Pattern[str]] = {
    "initialization_finish": re.compile(r"Initialization finish!", re.I),
    "init_first_imu_pose": re.compile(r"init first imu pose", re.I),
    "gyro_bias_initial_calibration": re.compile(
        r"gyroscope bias initial calibration", re.I
    ),
    "failure_detection": re.compile(r"failure detection", re.I),
    "explicit_reset_or_reboot": re.compile(
        r"(?:clear\s*state|\breset(?:ting)?\b|\breboot\b|\brestart\b)", re.I
    ),
    "linear_solver_failure": re.compile(r"Linear solver failure", re.I),
    "marginalization_failure": re.compile(r"marginali[sz].*fail", re.I),
}


def audit_vins_log(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {"state": "MISSING", "path": str(path), "counts": {}, "examples": {}}
    counts = {name: 0 for name in LOG_PATTERNS}
    examples: dict[str, list[dict[str, Any]]] = {name: [] for name in LOG_PATTERNS}
    with path.open(encoding="utf-8", errors="replace") as handle:
        for line_number, line in enumerate(handle, 1):
            clean = re.sub(r"\x1b\[[0-9;]*m", "", line).strip()
            for name, pattern in LOG_PATTERNS.items():
                if pattern.search(clean):
                    counts[name] += 1
                    if len(examples[name]) < 5:
                        examples[name].append(
                            {"line_number": line_number, "text": clean[:300]}
                        )
    return {
        "state": "READ",
        "path": str(path),
        "counts": counts,
        "examples": {name: rows for name, rows in examples.items() if rows},
        "hard_reset_evidence_count": (
            counts["failure_detection"] + counts["explicit_reset_or_reboot"]
        ),
    }


def validate_receipt_artifact_claims(
    receipt: Mapping[str, Any], paths: ArmPaths, expected_lock_sha256: Optional[str]
) -> list[str]:
    """Bind a terminal receipt's claims back to the files being analyzed."""

    errors: list[str] = []
    if receipt.get("schema_version") != "aqua-fe-samehistory-formal-run-receipt-v1":
        errors.append("FORMAL_RECEIPT_SCHEMA_DRIFT")
    if receipt.get("arm_id") != paths.lock_id:
        errors.append("FORMAL_RECEIPT_ARM_ID_MISMATCH")
    claims = receipt.get("claimed_identities")
    if not isinstance(claims, Mapping):
        return errors + ["FORMAL_RECEIPT_IDENTITIES_MISSING"]
    if expected_lock_sha256 is not None and claims.get("execution_lock_sha256") != expected_lock_sha256:
        errors.append("FORMAL_RECEIPT_EXECUTION_LOCK_SHA256_MISMATCH")
    required = {
        "vio_csv": paths.trajectory,
        "vins_log": paths.vins_log,
        "legacy_ape_diagnostic": paths.run_dir / "ape.txt",
        "vins_config": paths.vins_config,
    }
    for label, path in required.items():
        claim = claims.get(label)
        if label == "vins_config" and not isinstance(claim, Mapping):
            runtime_sha = claims.get("runtime_vins_config_sha256")
            if not path.is_file():
                errors.append("FORMAL_RECEIPT_VINS_CONFIG_ACTUAL_MISSING")
            elif runtime_sha != sha256(path):
                errors.append("FORMAL_RECEIPT_VINS_CONFIG_SHA256_MISMATCH")
            continue
        if not isinstance(claim, Mapping):
            errors.append(f"FORMAL_RECEIPT_{label.upper()}_CLAIM_MISSING")
            continue
        if not path.is_file():
            errors.append(f"FORMAL_RECEIPT_{label.upper()}_ACTUAL_MISSING")
            continue
        if claim.get("path") != str(path):
            errors.append(f"FORMAL_RECEIPT_{label.upper()}_PATH_MISMATCH")
        if claim.get("sha256") != sha256(path):
            errors.append(f"FORMAL_RECEIPT_{label.upper()}_SHA256_MISMATCH")
        claimed_size = claim.get("size_bytes")
        if claimed_size is not None and claimed_size != path.stat().st_size:
            errors.append(f"FORMAL_RECEIPT_{label.upper()}_SIZE_MISMATCH")
    return errors


LEARNED_COLUMNS = {
    "sp_lg": "exported_sp_lg_features",
    "xfeat": "exported_xfeat_features",
    "loftr": "exported_loftr_features",
}

LEARNED_PIPELINE_ACTIVITY_COLUMNS = {
    "learned_candidate_count_sum": "learned_candidate_count",
    "pre_gate_sidecar_total_sum": "pre_gate_sidecar_total",
    "learned_export_gate_dropped_sum": "learned_export_gate_dropped",
}


def numeric_count(row: Mapping[str, str], key: str) -> int:
    raw = (row.get(key) or "").strip()
    if not raw:
        return 0
    try:
        value = float(raw)
    except ValueError as error:
        raise EvidenceError(f"FRONTEND_METRIC_NONNUMERIC:{key}:{raw}") from error
    if not math.isfinite(value) or value < 0 or abs(value - round(value)) > 1e-6:
        raise EvidenceError(f"FRONTEND_METRIC_INVALID_COUNT:{key}:{raw}")
    return int(round(value))


def empty_segment() -> dict[str, Any]:
    return {
        "metric_rows": 0,
        "published_feature_rows": 0,
        "exported_features_sum": 0,
        "learned_observations": {
            "total": 0,
            "sp_lg": 0,
            "xfeat": 0,
            "loftr": 0,
            "other_non_loftr": 0,
        },
        "learned_affected_frames": {
            "any": 0,
            "sp_lg": 0,
            "xfeat": 0,
            "loftr": 0,
            "other_non_loftr": 0,
        },
        "learned_pipeline_activity": {
            **{name: 0 for name in LEARNED_PIPELINE_ACTIVITY_COLUMNS},
            "interpretation": (
                "SUMMED_PER-FRAME_DIAGNOSTIC_COUNTS_NOT_INDEPENDENT_SAMPLES"
            ),
        },
    }


def audit_frontend_metrics(
    path: Path, camera: CameraGrid, sequence: str
) -> dict[str, Any]:
    if not path.is_file():
        return {"state": "MISSING", "path": str(path), "errors": ["FRONTEND_METRICS_MISSING"]}
    score_start, score_end = WINDOWS[sequence]["score"]
    feed_start, feed_end = WINDOWS[sequence]["feed"]
    segments = {"full": empty_segment(), "preroll": empty_segment(), "score": empty_segment()}
    mapping_errors: list[str] = []
    mapped_sources: list[int] = []
    activity_column_presence: dict[str, bool] = {}
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        required = {"frame_index", "timestamp"}
        if reader.fieldnames is None or not required.issubset(reader.fieldnames):
            raise EvidenceError(f"{path}:FRONTEND_METRICS_REQUIRED_COLUMNS_MISSING")
        activity_column_presence = {
            name: column in reader.fieldnames
            for name, column in LEARNED_PIPELINE_ACTIVITY_COLUMNS.items()
        }
        for row_number, row in enumerate(reader, 2):
            try:
                stamp_ns = parse_timestamp_ns(row["timestamp"])
            except ValueError as error:
                raise EvidenceError(f"{path}:{row_number}:INVALID_METRIC_TIMESTAMP") from error
            association = associate_stamps_to_camera([stamp_ns], camera)
            source = association["source_indices"][0]
            if source is None:
                mapping_errors.append(f"ROW_{row_number}_TIMESTAMP_UNMAPPED")
                continue
            try:
                declared_local = int(row["frame_index"])
            except ValueError as error:
                raise EvidenceError(f"{path}:{row_number}:INVALID_FRAME_INDEX") from error
            declared_source = feed_start + declared_local
            if declared_source != source:
                mapping_errors.append(
                    f"ROW_{row_number}_FRAME_TIMESTAMP_SOURCE_DISAGREE:"
                    f"{declared_source}!={source}"
                )
            if not feed_start <= source <= feed_end:
                mapping_errors.append(f"ROW_{row_number}_SOURCE_OUTSIDE_FEED:{source}")
                continue
            mapped_sources.append(source)
            destinations = ["full"]
            if source < score_start:
                destinations.append("preroll")
            elif source <= score_end:
                destinations.append("score")
            explicit = {
                name: numeric_count(row, column)
                for name, column in LEARNED_COLUMNS.items()
            }
            aggregate = numeric_count(row, "exported_learned_features")
            explicit_sum = sum(explicit.values())
            if aggregate == 0 and explicit_sum:
                aggregate = explicit_sum
            if aggregate < explicit_sum:
                raise EvidenceError(
                    f"{path}:{row_number}:LEARNED_AGGREGATE_LT_SOURCE_SUM"
                )
            other = aggregate - explicit_sum
            published = numeric_count(row, "published_feature_frame")
            exported = numeric_count(row, "exported_features")
            learned_pipeline_activity = {
                name: numeric_count(row, column)
                for name, column in LEARNED_PIPELINE_ACTIVITY_COLUMNS.items()
            }
            for destination in destinations:
                segment = segments[destination]
                segment["metric_rows"] += 1
                segment["published_feature_rows"] += int(published > 0)
                segment["exported_features_sum"] += exported
                observations = segment["learned_observations"]
                frames = segment["learned_affected_frames"]
                observations["total"] += aggregate
                observations["other_non_loftr"] += other
                frames["any"] += int(aggregate > 0)
                frames["other_non_loftr"] += int(other > 0)
                for name, value in explicit.items():
                    observations[name] += value
                    frames[name] += int(value > 0)
                activity = segment["learned_pipeline_activity"]
                for name, value in learned_pipeline_activity.items():
                    activity[name] += value
    if any(right <= left for left, right in zip(mapped_sources, mapped_sources[1:])):
        mapping_errors.append("MAPPED_SOURCE_INDICES_NOT_STRICTLY_INCREASING")
    full_total = segments["full"]["learned_observations"]["total"]
    preroll_total = segments["preroll"]["learned_observations"]["total"]
    score_total = segments["score"]["learned_observations"]["total"]
    if full_total != preroll_total + score_total:
        mapping_errors.append("FULL_LEARNED_TOTAL_NOT_PREROLL_PLUS_SCORE")
    if full_total == 0:
        action = "NO_LEARNED_ACTION_NO_HARM_ONLY"
    elif score_total > 0 and preroll_total > 0:
        action = "LEARNED_ACTION_PREROLL_AND_SCORE"
    elif score_total > 0:
        action = "DIRECT_LEARNED_ACTION_IN_SCORE"
    else:
        action = "LEARNED_ACTION_PREROLL_HISTORY_ONLY"
    return {
        "state": "VALID" if not mapping_errors else "INVALID",
        "path": str(path),
        "mapping": {
            "authority": "TIMESTAMP_TO_FROZEN_CAMERA_CSV",
            "frame_index_formula_audit": "source=feed_start+frame_index",
            "mapped_row_count": len(mapped_sources),
            "first_source": mapped_sources[0] if mapped_sources else None,
            "last_source": mapped_sources[-1] if mapped_sources else None,
        },
        "segments": segments,
        "learned_action_class": action,
        "learned_pipeline_activity_columns_present": activity_column_presence,
        "learned_pipeline_activity_interpretation": (
            "Candidate, pre-gate sidecar, and gate-drop sums show pipeline activity only; "
            "they are repeated per-frame diagnostics and are not independent samples or "
            "exported learned action."
        ),
        "errors": mapping_errors,
    }


def audit_vins_arm(
    paths: ArmPaths,
    camera: CameraGrid,
    *,
    expected_lock_sha256: Optional[str] = None,
) -> dict[str, Any]:
    receipt = audit_receipt(paths.receipt)
    base = {
        "sequence": paths.sequence,
        "method": paths.method,
        "run_dir": str(paths.run_dir),
        "receipt": receipt,
        "input_rate": (
            "20_HZ_NATIVE_TRACKER_MT1_EVERY_SECOND_BACKEND"
            if paths.method == "vanilla_origin"
            else "20_HZ_TRACKER_STATE_10_HZ_EVERY2_EXPORT_AND_BACKEND"
        ),
    }
    if receipt["state"] == "PENDING_MISSING_RECEIPT":
        return {
            **base,
            "analysis_state": "PENDING",
            "usability": {"status": "PENDING", "failure_codes": ["FORMAL_RUN_RECEIPT_MISSING"]},
            "trajectory": None,
            "score_support": None,
            "vins_log": None,
            "frontend": None,
        }
    trajectory = load_trajectory(paths.trajectory)
    log = audit_vins_log(paths.vins_log)
    association = associate_stamps_to_camera(trajectory["stamps_ns"], camera)
    support = score_support(paths.sequence, paths.method, camera, association)
    frontend = (
        {"state": "NOT_APPLICABLE_NATIVE_IMAGE_TRACKER"}
        if paths.frontend_metrics is None
        else audit_frontend_metrics(paths.frontend_metrics, camera, paths.sequence)
    )
    failures: list[str] = []
    receipt_identity_errors = validate_receipt_artifact_claims(
        receipt, paths, expected_lock_sha256
    )
    if receipt_identity_errors:
        failures.append("FORMAL_RECEIPT_ARTIFACT_IDENTITY_INVALID")
    if receipt["state"] != "TERMINAL" or not receipt["policy_compliant"]:
        failures.append("EXECUTION_RECEIPT_NONCOMPLIANT")
    if receipt["raw_return_code"] != 0:
        failures.append("PROCESS_RETURN_CODE_NONZERO")
    if trajectory["state"] != "VALID":
        failures.append("TRAJECTORY_NOT_FINITE_STRICTLY_INCREASING")
    if association["unmatched_pose_count"]:
        failures.append("TRAJECTORY_TIMESTAMP_UNMAPPED")
    if association["duplicate_source_association_count"]:
        failures.append("TRAJECTORY_DUPLICATE_CAMERA_ASSOCIATION")
    if support["phase_state"] != "PASS":
        failures.append("ORIGIN_MT1_PHASE_AMBIGUOUS")
    if support["method_native_coverage_fraction"] < 0.70:
        failures.append("SCORE_NATIVE_COVERAGE_LT_70_PERCENT")
    if support["method_native_longest_contiguous_fraction"] < 0.70:
        failures.append("SCORE_NATIVE_CONTIGUOUS_LT_70_PERCENT")
    if support["method_native_covered_count"] == 0:
        failures.append("INITIALIZATION_NOT_OBSERVED_IN_SCORE")
    required_files = [
        paths.vins_log,
        paths.run_dir / "ape.txt",
        paths.run_dir / "replay_manifest.txt",
        paths.vins_config,
    ]
    missing_required = [str(path) for path in required_files if not path.is_file()]
    if missing_required:
        failures.append("REQUIRED_TERMINAL_ARTIFACT_MISSING")
    if log.get("hard_reset_evidence_count", 0):
        failures.append("EXPLICIT_FAILURE_OR_RESET_EVIDENCE")
    if paths.frontend_metrics is not None and frontend["state"] != "VALID":
        failures.append("FRONTEND_METRICS_INVALID_OR_MISSING")
    if paths.method == "external_klt" and frontend.get("state") == "VALID":
        if frontend["segments"]["full"]["learned_observations"]["total"] != 0:
            failures.append("EXTERNAL_KLT_EXPORTED_LEARNED_OBSERVATIONS")
    return {
        **base,
        "analysis_state": "TERMINAL",
        "usability": {
            "status": "PASS" if not failures else "FAIL",
            "failure_codes": failures,
            "initialization_success": support["method_native_covered_count"] > 0,
            "required_artifacts_missing": missing_required,
            "receipt_artifact_identity_errors": receipt_identity_errors,
            "solver_failure_count_disclosed_not_automatically_failed": (
                log.get("counts", {}).get("linear_solver_failure", 0)
            ),
        },
        "trajectory": {key: value for key, value in trajectory.items() if key != "stamps_ns"},
        "timestamp_association": {
            key: value
            for key, value in association.items()
            if key not in ("source_indices", "unique_source_indices")
        },
        "score_support": support,
        "vins_log": log,
        "frontend": frontend,
    }


def nonadopted_a06_klt_incident_row(
    original: ArmPaths,
    camera: CameraGrid,
    corrective: Mapping[str, Any],
) -> dict[str, Any]:
    """Represent censorship without scoring the immutable partial output."""

    pending = corrective.get("state") == "PENDING_CORRECTIVE_REPLAY"
    trajectory = load_trajectory(original.trajectory)
    association = associate_stamps_to_camera(trajectory["stamps_ns"], camera)
    frontend = audit_frontend_metrics(
        original.run_dir / "frontend_metrics.csv", camera, "A06"
    )
    return {
        "sequence": "A06",
        "method": "external_klt",
        "run_dir": str(original.run_dir),
        "analysis_state": (
            "PENDING_INFRASTRUCTURE_CORRECTIVE_REPLAY"
            if pending
            else "TERMINAL_CORRECTIVE_REPLAY_NOT_ADOPTED"
        ),
        "input_rate": "20_HZ_TRACKER_STATE_10_HZ_EVERY2_EXPORT_AND_BACKEND",
        "receipt": audit_receipt(original.receipt),
        "usability": {
            "status": "PENDING" if pending else "FAIL",
            "failure_codes": [
                "ORIGINAL_INFRASTRUCTURE_CENSORED_NOT_ALGORITHM_FAILURE",
                (
                    "FROZEN_CORRECTIVE_REPLAY_PENDING"
                    if pending
                    else "CORRECTIVE_REPLAY_TERMINAL_NOT_ADOPTABLE"
                ),
            ],
            "algorithmic_usability_adjudicated": False,
        },
        "trajectory": {
            **{key: value for key, value in trajectory.items() if key != "stamps_ns"},
            "score_or_accuracy_eligible": False,
            "role": "IMMUTABLE_PARTIAL_INFRASTRUCTURE_CENSORED_CONTEXT",
        },
        "timestamp_association": {
            key: value
            for key, value in association.items()
            if key not in ("source_indices", "unique_source_indices")
        },
        "score_support": None,
        "vins_log": audit_vins_log(original.vins_log),
        "frontend": frontend,
        "infrastructure_corrective_replay": dict(corrective),
    }


def load_hfnet_rows(path: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    bundle = read_json(path)
    if bundle.get("schema_version") != "aqua-fe-hfnet-multiwindow-analysis-bundle-v2":
        raise EvidenceError("HFNET_BUNDLE_SCHEMA_DRIFT")
    if bundle.get("analysis_state") != "TERMINAL_DESCRIPTIVE_ONLY":
        raise EvidenceError("HFNET_BUNDLE_NOT_TERMINAL")
    rows = bundle.get("rows")
    if not isinstance(rows, list):
        raise EvidenceError("HFNET_BUNDLE_ROWS_MISSING")
    selected: dict[str, dict[str, Any]] = {}
    for sequence in WINDOW_ORDER:
        window_id = WINDOWS[sequence]["hfnet_window_id"]
        candidates = [row for row in rows if isinstance(row, dict) and row.get("window_id") == window_id]
        if len(candidates) != 1:
            raise EvidenceError(f"HFNET_{sequence}_ROW_NOT_UNIQUE")
        row = candidates[0]
        if row.get("method_id") != "HFNET_SLAM":
            raise EvidenceError(f"HFNET_{sequence}_METHOD_DRIFT")
        usability = row.get("usability")
        if not isinstance(usability, Mapping) or usability.get("status") not in ("PASS", "FAIL"):
            raise EvidenceError(f"HFNET_{sequence}_USABILITY_NOT_TERMINAL")
        selected[sequence] = row
    return selected, bundle


def hfnet_analysis_row(sequence: str, row: Mapping[str, Any]) -> dict[str, Any]:
    usability = dict(row["usability"])
    return {
        "sequence": sequence,
        "method": "hfnet_slam",
        "analysis_state": "SEALED_TERMINAL",
        "input_rate": "20_HZ_CAMERA_AND_BACKEND",
        "usability": usability,
        "score_support": {
            "method_native_expected_count": row["score"]["expected_frame_count"],
            "method_native_covered_count": usability["score_pose_count"],
            "method_native_coverage_fraction": usability["score_coverage_fraction"],
            "method_native_longest_contiguous_count": usability["score_longest_contiguous_count"],
            "method_native_longest_contiguous_fraction": usability["score_longest_contiguous_fraction"],
            "camera_grid_expected_count": row["score"]["expected_frame_count"],
            "camera_grid_covered_count": usability["score_pose_count"],
            "camera_grid_coverage_fraction": usability["score_coverage_fraction"],
            "first_score_output_delay_s": usability["score_first_output_delay_s"],
        },
        "frontend": {"state": "NOT_AVAILABLE_SEALED_EXTERNAL_WHOLE_SYSTEM"},
        "artifacts": row.get("artifacts"),
        "sealed_source_window_id": row.get("window_id"),
    }


def clean_json(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): clean_json(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [clean_json(item) for item in value]
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def evaluator_input_manifest(
    sequence: str,
    paths: Mapping[str, ArmPaths],
    raw_bag: Path,
) -> dict[str, Any]:
    hfnet_bridge = Path(WINDOWS[sequence]["hfnet_bridge"])
    sequence_paths = {
        path.method: path for path in paths.values() if path.sequence == sequence
    }
    files: dict[str, dict[str, Any]] = {
        "evaluator": identity(EVALUATOR),
        "reference_bag": identity(raw_bag),
        "hfnet_bridge": identity(hfnet_bridge),
    }
    for method in ARM_ORDER:
        files[f"{method}_trajectory"] = identity(sequence_paths[method].trajectory)
        files[f"{method}_config"] = identity(sequence_paths[method].vins_config)
    return {
        "schema_version": "aqua-fe-samehistory-common-support-input-manifest-v1",
        "sequence": sequence,
        "files": files,
        "formal_gates": {
            "min_ape_poses": 30,
            "min_ape_span_s": 10.0,
            "min_common_coverage": 0.70,
            "min_rpe_pairs": 10,
        },
    }


def decimal_seconds(stamp_ns: int) -> str:
    return format(Decimal(stamp_ns) / Decimal("1000000000"), "f")


def build_evaluator_command(
    sequence: str,
    paths: Mapping[str, ArmPaths],
    camera: CameraGrid,
    raw_bag: Path,
    output_dir: Path,
) -> list[str]:
    sequence_paths = {
        path.method: path for path in paths.values() if path.sequence == sequence
    }
    window = WINDOWS[sequence]
    score_start, score_end = window["score"]
    command = [
        sys.executable,
        str(EVALUATOR),
        "--reference-bag",
        str(raw_bag),
        "--reference-topic",
        "/aqualoc/colmap_gt",
    ]
    for method in ARM_ORDER:
        command.extend(
            [
                "--arm",
                f"{COMMON_ARM_NAMES[method]}={sequence_paths[method].trajectory}",
            ]
        )
    command.extend(
        [
            "--arm",
            f"HFNET_SLAM={window['hfnet_bridge']}",
        ]
    )
    for method in ARM_ORDER:
        command.extend(
            [
                "--arm-config",
                f"{COMMON_ARM_NAMES[method]}={sequence_paths[method].vins_config}",
            ]
        )
    # HFNet's bridge is world_T_body, so it uses the same calibrated
    # body_T_cam0 as the native-image VINS arm for the same sequence.
    command.extend(
        [
            "--arm-config",
            f"HFNET_SLAM={sequence_paths['vanilla_origin'].vins_config}",
            "--nominal-reference-rate-hz",
            str(window["nominal_reference_rate_hz"]),
            "--nominal-estimate-rate-hz",
            "10.0",
            "--evaluation-rate-hz",
            str(window["evaluation_rate_hz"]),
            "--max-reference-gap-s",
            str(window["max_reference_gap_s"]),
            "--max-estimate-gap-s",
            "0.25",
            "--window-start-s",
            decimal_seconds(camera.stamp_for_source(score_start)),
            "--window-end-s",
            decimal_seconds(camera.stamp_for_source(score_end)),
            "--rpe-delta-s",
            "1.0",
            "--min-ape-poses",
            "30",
            "--min-ape-span-s",
            "10.0",
            "--min-common-coverage",
            "0.70",
            "--min-rpe-pairs",
            "10",
            "--contrast-name",
            f"SAMEHISTORY_SYSTEM_V1_{sequence}",
            "--output-dir",
            str(output_dir),
        ]
    )
    return command


def ensure_common_support(
    sequence: str,
    paths: Mapping[str, ArmPaths],
    camera: CameraGrid,
    raw_bag: Path,
    common_root: Path,
    *,
    run_evaluator: bool,
) -> tuple[Optional[dict[str, Any]], dict[str, Any]]:
    final = common_root / sequence.lower()
    summary_path = final / "common_support_summary.json"
    manifest_path = final / "samehistory_evaluator_input_manifest_v1.json"
    expected_manifest = evaluator_input_manifest(sequence, paths, raw_bag)
    if summary_path.is_file():
        if not manifest_path.is_file():
            raise EvidenceError(f"{sequence}:UNATTESTED_EXISTING_COMMON_SUPPORT")
        actual_manifest = read_json(manifest_path)
        if actual_manifest != expected_manifest:
            raise EvidenceError(f"{sequence}:STALE_COMMON_SUPPORT_INPUT_MANIFEST")
        return read_json(summary_path), {
            "state": "READ_EXISTING_COMMON_SUPPORT",
            "summary_path": str(summary_path),
            "input_manifest": expected_manifest,
        }
    if not run_evaluator:
        return None, {
            "state": "READY_BUT_EVALUATOR_DISABLED",
            "summary_path": str(summary_path),
            "input_manifest": expected_manifest,
        }
    final.parent.mkdir(parents=True, exist_ok=True)
    if final.exists():
        raise EvidenceError(f"{sequence}:PARTIAL_COMMON_SUPPORT_DIR_EXISTS")
    staging = Path(tempfile.mkdtemp(prefix=f".{sequence.lower()}_common_support.", dir=str(final.parent)))
    try:
        command = build_evaluator_command(sequence, paths, camera, raw_bag, staging)
        process = subprocess.run(
            command,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
        )
        (staging / "evaluator_process_receipt_v1.json").write_text(
            json.dumps(
                {
                    "schema_version": "aqua-fe-samehistory-evaluator-process-receipt-v1",
                    "command": command,
                    "raw_return_code": process.returncode,
                    "stdout": process.stdout,
                },
                indent=2,
                sort_keys=True,
                ensure_ascii=False,
            )
            + "\n",
            encoding="utf-8",
        )
        if process.returncode != 0 or not (staging / "common_support_summary.json").is_file():
            raise EvidenceError(
                f"{sequence}:COMMON_SUPPORT_EVALUATOR_FAILED_RC_{process.returncode}:"
                f"{process.stdout[-1000:]}"
            )
        (staging / manifest_path.name).write_text(
            json.dumps(expected_manifest, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        staging.rename(final)
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    return read_json(summary_path), {
        "state": "RAN_COMMON_SUPPORT_EVALUATOR",
        "summary_path": str(summary_path),
        "input_manifest": expected_manifest,
    }


def formal_accuracy_gate(
    sequence: str,
    common_summary: Optional[Mapping[str, Any]],
    usability_rows: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    native_rows = int(WINDOWS[sequence]["reference_native_rows"])
    blockers: list[str] = []
    if native_rows < 30:
        blockers.append("REFERENCE_NATIVE_ROWS_LT_30")
    if any(row.get("usability", {}).get("status") != "PASS" for row in usability_rows):
        blockers.append("SYSTEM_UNUSABLE_OR_PENDING")
    descriptive: Optional[dict[str, Any]] = None
    support: Optional[dict[str, Any]] = None
    if common_summary is None:
        blockers.append("COMMON_SUPPORT_NOT_AVAILABLE")
    else:
        raw_support = common_summary.get("support")
        arms = common_summary.get("arms")
        if not isinstance(raw_support, Mapping) or not isinstance(arms, Mapping):
            raise EvidenceError(f"{sequence}:COMMON_SUPPORT_SCHEMA_INVALID")
        support = dict(raw_support)
        if bool(raw_support.get("ape_valid")):
            raise EvidenceError(
                f"{sequence}:FORMAL_APE_GATE_OPEN_DESPITE_NATIVE_REFERENCE_LT_30"
            )
        # The evaluator reports APE and 1 s RPE gates separately.  A06 can
        # have >=10 descriptive RPE pairs even though it has fewer than 30
        # native/common poses.  That does not open the aggregate formal
        # accuracy gate, which requires every frozen condition.
        if int(raw_support.get("matched_count") or 0) < 30:
            blockers.append("COMMON_MATCHED_ROWS_LT_30")
        if float(raw_support.get("common_span_s") or 0.0) < 10.0:
            blockers.append("COMMON_SPAN_LT_10S")
        if int(raw_support.get("rpe_pairs") or 0) < 10:
            blockers.append("RPE_PAIRS_LT_10")
        expected_names = set(COMMON_ARM_NAMES.values())
        if set(arms) != expected_names:
            raise EvidenceError(f"{sequence}:COMMON_SUPPORT_ARM_SET_DRIFT")
        descriptive = {
            "label": "DESCRIPTIVE_SAME_IMAGE_COLMAP_PROXY_ONLY_NO_RANKING",
            "arms": {
                name: {
                    key: metrics.get(key)
                    for key in (
                        "matched_count",
                        "ape_rmse_m",
                        "ape_median_m",
                        "ape_max_m",
                        "rpe_pairs",
                        "rpe_rmse_m",
                        "rpe_median_m",
                        "rpe_max_m",
                    )
                }
                for name, metrics in arms.items()
                if isinstance(metrics, Mapping)
            },
        }
    return {
        "state": "BLOCKED_FORMAL",
        "formal_winner_permitted": False,
        "significance_test_permitted": False,
        "cross_window_mean_ranking_permitted": False,
        "failure_zero_imputation_permitted": False,
        "native_reference_rows_in_score": native_rows,
        "block_codes": sorted(set(blockers)),
        "common_support": support,
        "descriptive_proxy_metrics": descriptive,
    }


def optional_file_identity(path: Path, *, role: str) -> dict[str, Any]:
    if not path.is_file():
        return {"path": str(path), "exists": False, "role": role}
    return {**identity(path), "exists": True, "role": role}


def frontend_payload_comparison(
    sequence: str,
    paths: Mapping[str, ArmPaths],
    rows: Sequence[Mapping[str, Any]],
    a06_klt_corrective: Mapping[str, Any],
) -> dict[str, Any]:
    """Determine whether proposed_safe changed the actual feature-bag bytes.

    Metric-side learned counts alone are not enough: a zero-action proposed
    run can be byte-identical to KLT.  Conversely, two backend trajectories
    produced from one identical bag are repeated backend executions, so any
    difference is backend nondeterminism and cannot be credited to a frontend.
    """

    external_paths = paths[f"{sequence.lower()}_external_klt"]
    proposed_paths = paths[f"{sequence.lower()}_aquafe_proposed_safe"]
    if sequence == "A06" and a06_klt_corrective.get("state") != "NOT_APPLICABLE":
        source_record = a06_klt_corrective.get("source_feature_bag")
        if not isinstance(source_record, Mapping):
            source_audit = a06_klt_corrective.get("frozen_source_payload")
            source_files = (
                source_audit.get("files") if isinstance(source_audit, Mapping) else None
            )
            source_record = (
                source_files.get("feature_bag")
                if isinstance(source_files, Mapping)
                else None
            )
        source_path = (
            source_record.get("path") if isinstance(source_record, Mapping) else None
        )
        external_bag = (
            Path(str(source_path))
            if source_path
            else paths["a06_vanilla_origin"].run_dir.parents[1]
            / "a06"
            / "external_klt"
            / "features.bag"
        )
        external_role = "FROZEN_SOURCE_FEATURE_BAG_FOR_CORRECTIVE_BACKEND_REPLAY"
    else:
        external_bag = external_paths.run_dir / "features.bag"
        external_role = "FORMAL_EXTERNAL_KLT_FEATURE_BAG"
    proposed_bag = proposed_paths.run_dir / "features.bag"
    bag_records = {
        "external_klt": optional_file_identity(external_bag, role=external_role),
        "aquafe_proposed_safe": optional_file_identity(
            proposed_bag, role="FORMAL_AQUAFE_PROPOSED_SAFE_FEATURE_BAG"
        ),
    }
    both_bags_exist = all(record["exists"] for record in bag_records.values())
    payload_identical: Optional[bool] = None
    if both_bags_exist:
        payload_identical = (
            bag_records["external_klt"]["size_bytes"]
            == bag_records["aquafe_proposed_safe"]["size_bytes"]
            and bag_records["external_klt"]["sha256"]
            == bag_records["aquafe_proposed_safe"]["sha256"]
        )
    sequence_rows = {
        str(row["method"]): row for row in rows if row.get("sequence") == sequence
    }
    proposed_frontend = sequence_rows.get("aquafe_proposed_safe", {}).get("frontend")
    learned_total: Optional[int] = None
    learned_pipeline_activity: Optional[dict[str, Any]] = None
    activity_columns_present: Optional[dict[str, bool]] = None
    if isinstance(proposed_frontend, Mapping):
        segments = proposed_frontend.get("segments")
        if isinstance(segments, Mapping):
            full = segments.get("full")
            if isinstance(full, Mapping):
                learned = full.get("learned_observations")
                if isinstance(learned, Mapping) and isinstance(learned.get("total"), int):
                    learned_total = int(learned["total"])
                activity = full.get("learned_pipeline_activity")
                if isinstance(activity, Mapping):
                    learned_pipeline_activity = dict(activity)
        presence = proposed_frontend.get("learned_pipeline_activity_columns_present")
        if isinstance(presence, Mapping):
            activity_columns_present = {
                str(name): bool(value) for name, value in presence.items()
            }
    trajectories = {
        "external_klt": optional_file_identity(
            external_paths.trajectory, role="SELECTED_EXTERNAL_KLT_VIO"
        ),
        "aquafe_proposed_safe": optional_file_identity(
            proposed_paths.trajectory, role="AQUAFE_PROPOSED_SAFE_VIO"
        ),
    }
    both_trajectories_usable = all(
        sequence_rows.get(method, {}).get("usability", {}).get("status") == "PASS"
        for method in ("external_klt", "aquafe_proposed_safe")
    )
    trajectory_sha_different: Optional[bool] = None
    if all(record["exists"] for record in trajectories.values()):
        trajectory_sha_different = (
            trajectories["external_klt"]["sha256"]
            != trajectories["aquafe_proposed_safe"]["sha256"]
        )
    if payload_identical is None or learned_total is None:
        action_class = "PENDING_FEATURE_PAYLOAD_OR_LEARNED_ACTION_EVIDENCE"
    elif payload_identical and learned_total == 0:
        action_class = "NO_ACTION_BYTE_IDENTICAL_TO_KLT"
    elif payload_identical and learned_total > 0:
        action_class = "CONTRADICTORY_LEARNED_COUNT_WITH_BYTE_IDENTICAL_PAYLOAD"
    elif learned_total == 0:
        action_class = "NO_LEARNED_ACTION_PAYLOAD_BYTES_DIFFER"
    else:
        action_class = "LEARNED_ACTION_AND_PAYLOAD_BYTES_DIFFER"
    backend_nondeterminism = bool(
        payload_identical is True and trajectory_sha_different is True
    )
    if payload_identical is True:
        learning_attribution = "PROHIBITED_PAYLOAD_BYTE_IDENTICAL"
    else:
        learning_attribution = "NOT_ESTABLISHED_BY_PAYLOAD_IDENTITY_AUDIT"
    pipeline_activity_observed: Optional[bool] = None
    if learned_pipeline_activity is not None:
        pipeline_activity_observed = any(
            isinstance(learned_pipeline_activity.get(name), int)
            and learned_pipeline_activity[name] > 0
            for name in LEARNED_PIPELINE_ACTIVITY_COLUMNS
        )
    return {
        "state": "COMPLETE" if both_bags_exist and learned_total is not None else "PENDING",
        "sequence": sequence,
        "feature_bags": bag_records,
        "payload_byte_identical": payload_identical,
        "proposed_learned_observations_full": learned_total,
        "proposed_learned_pipeline_activity_full": learned_pipeline_activity,
        "proposed_learned_pipeline_activity_columns_present": activity_columns_present,
        "proposed_learned_pipeline_activity_observed": pipeline_activity_observed,
        "candidate_activity_is_independent_sample_evidence": False,
        "action_class": action_class,
        "selected_trajectories": trajectories,
        "trajectory_comparison_eligible": both_trajectories_usable,
        "trajectory_sha_different": trajectory_sha_different,
        "backend_run_nondeterminism_observed": backend_nondeterminism,
        "trajectory_difference_not_attributable_to_frontend": backend_nondeterminism,
        "learning_improvement_claim_permitted": (
            False if payload_identical is True else None
        ),
        "learning_improvement_attribution": learning_attribution,
        "interpretation": (
            "Identical feature-bag bytes fix the complete frontend payload. Any selected "
            "VIO SHA difference is a backend-run difference, not learned-frontend evidence."
            if payload_identical is True
            else "Payload identity does not by itself establish an accuracy improvement."
        ),
    }


def build_bundle(
    lock_path: Path,
    protocol_path: Path,
    hfnet_bundle_path: Path,
    camera_overrides: Mapping[str, Path],
    output_dir: Path,
    *,
    run_evaluator: bool,
) -> dict[str, Any]:
    lock = verify_protocol_lock(lock_path, protocol_path)
    paths = resolve_arm_paths(lock)
    lock_digest = sha256(lock_path)
    a06_klt_corrective, selected_a06_klt = resolve_a06_klt_corrective_adoption(
        lock, paths, lock_digest
    )
    paths["a06_external_klt"] = selected_a06_klt
    hfnet_rows, hfnet_bundle = load_hfnet_rows(hfnet_bundle_path)
    cameras: dict[str, CameraGrid] = {}
    rows: list[dict[str, Any]] = []
    for sequence in WINDOW_ORDER:
        feed_start, feed_end = WINDOWS[sequence]["feed"]
        camera_path = camera_overrides.get(sequence, Path(WINDOWS[sequence]["camera_csv"]))
        cameras[sequence] = load_camera_grid(
            camera_path, sequence, feed_start, feed_end
        )
        for method in ARM_ORDER:
            lock_id = f"{sequence.lower()}_{method}"
            if sequence == "A06" and method == "external_klt" and not a06_klt_corrective["adopted"] and a06_klt_corrective["state"] != "NOT_APPLICABLE":
                original_paths = resolve_arm_paths(lock)["a06_external_klt"]
                rows.append(
                    nonadopted_a06_klt_incident_row(
                        original_paths, cameras[sequence], a06_klt_corrective
                    )
                )
            else:
                arm_row = audit_vins_arm(
                    paths[lock_id],
                    cameras[sequence],
                    expected_lock_sha256=(
                        None
                        if sequence == "A06"
                        and method == "external_klt"
                        and a06_klt_corrective["adopted"]
                        else lock_digest
                    ),
                )
                if sequence == "A06" and method == "external_klt":
                    arm_row["infrastructure_corrective_replay"] = a06_klt_corrective
                rows.append(arm_row)
        rows.append(hfnet_analysis_row(sequence, hfnet_rows[sequence]))

    payload_comparisons = {
        sequence: frontend_payload_comparison(
            sequence, paths, rows, a06_klt_corrective
        )
        for sequence in WINDOW_ORDER
    }
    for row in rows:
        method = row["method"]
        if method not in ("external_klt", "aquafe_proposed_safe"):
            continue
        comparison = payload_comparisons[row["sequence"]]
        row["feature_bag_identity"] = comparison["feature_bags"][method]
        row["frontend_payload_pair_audit"] = {
            key: comparison[key]
            for key in (
                "state",
                "payload_byte_identical",
                "proposed_learned_observations_full",
                "proposed_learned_pipeline_activity_full",
                "proposed_learned_pipeline_activity_columns_present",
                "proposed_learned_pipeline_activity_observed",
                "candidate_activity_is_independent_sample_evidence",
                "action_class",
                "trajectory_sha_different",
                "backend_run_nondeterminism_observed",
                "trajectory_difference_not_attributable_to_frontend",
                "learning_improvement_claim_permitted",
                "learning_improvement_attribution",
            )
        }

    accuracy: dict[str, Any] = {}
    evaluator_audits: dict[str, Any] = {}
    for sequence in WINDOW_ORDER:
        sequence_rows = [row for row in rows if row["sequence"] == sequence]
        all_vins_terminal = all(
            str(row["analysis_state"]).startswith("TERMINAL")
            for row in sequence_rows
            if row["method"] in ARM_ORDER
        )
        all_systems_usable = all(
            row.get("usability", {}).get("status") == "PASS"
            for row in sequence_rows
        )
        all_inputs_exist = all(
            path.sequence != sequence
            or (
                path.trajectory.is_file()
                and path.vins_config.is_file()
                and path.receipt.is_file()
            )
            for path in paths.values()
        ) and Path(WINDOWS[sequence]["hfnet_bridge"]).is_file()
        raw_bag = Path(
            str(lock["policy"]["large_artifact_root"])
        ) / "raw" / str(WINDOWS[sequence]["raw_bag_name"])
        common_summary: Optional[dict[str, Any]] = None
        if (
            all_vins_terminal
            and all_systems_usable
            and all_inputs_exist
            and raw_bag.is_file()
        ):
            common_summary, evaluator_audits[sequence] = ensure_common_support(
                sequence,
                paths,
                cameras[sequence],
                raw_bag,
                output_dir / "common_support",
                run_evaluator=run_evaluator,
            )
        else:
            evaluator_audits[sequence] = {
                "state": (
                    "BLOCKED_SYSTEM_UNUSABLE"
                    if all_vins_terminal and not all_systems_usable
                    else "PENDING_REQUIRED_TERMINAL_INPUTS"
                ),
                "all_vins_terminal": all_vins_terminal,
                "all_systems_usable": all_systems_usable,
                "all_inputs_exist": all_inputs_exist,
                "raw_bag_exists": raw_bag.is_file(),
            }
        accuracy[sequence] = formal_accuracy_gate(
            sequence, common_summary, sequence_rows
        )

    terminal_vins = sum(
        str(row["analysis_state"]).startswith("TERMINAL")
        for row in rows
        if row["method"] in ARM_ORDER
    )
    bundle = {
        "schema_version": SCHEMA,
        "analysis_state": (
            "TERMINAL_DESCRIPTIVE_FORMAL_ACCURACY_BLOCKED"
            if terminal_vins == 6
            else "PENDING_FORMAL_ARMS"
        ),
        "question": (
            "Same raw camera history: native-image VINS context, same-exporter KLT "
            "ablation, AQUA-FE proposed_safe, and sealed HFNet-SLAM usability."
        ),
        "frozen_protocol": identity(protocol_path),
        "execution_lock": identity(lock_path),
        "hfnet_bundle": identity(hfnet_bundle_path),
        "a06_external_klt_corrective_replay": a06_klt_corrective,
        "hfnet_sealed_summary": hfnet_bundle.get("current_protocol_summary"),
        "camera_history": {
            sequence: {
                "identity": identity(cameras[sequence].path),
                "feed_source_range": list(WINDOWS[sequence]["feed"]),
                "score_source_range": list(WINDOWS[sequence]["score"]),
            }
            for sequence in WINDOW_ORDER
        },
        "rows": rows,
        "frontend_payload_comparisons": payload_comparisons,
        "accuracy": accuracy,
        "evaluator_audit": evaluator_audits,
        "statistical_gate": {
            "unit_of_analysis": "frozen_development_window",
            "window_count": 2,
            "formal_algorithmic_outcome_count_per_arm_window": 1,
            "a06_external_klt_corrective_backend_replay_is_independent_repeat": False,
            "inferential_statistics_permitted": False,
            "reason": (
                "Only two development windows and one formal execution per arm/window; "
                "trajectory frames are repeated time-series samples, not independent n."
            ),
        },
        "cross_system_disclosures": [
            "A06 external_klt original replay was infrastructure-censored before score; only the exact frozen-feature backend corrective namespace may be adopted, and the immutable partial output is never scored",
            "vanilla_origin is the pinned native-image context control from the local quality-capable checkout, not a byte-identical pristine upstream Vanilla VINS-Fusion",
            "camera-history matched / IMU API support differs",
            "external AQUA-FE arms export at 10 Hz while HFNet camera/backend is 20 Hz",
            "origin sees 20 Hz images but MT1 queues every second tracker feature frame",
            "Candidate/pre-gate/gate-drop sums are repeated per-frame pipeline diagnostics, not independent samples or exported learned action",
            "Byte-identical external_klt and proposed feature bags prohibit attributing any VIO difference to the learned frontend",
            "VINS online outputs and HFNet final-map trajectory semantics differ",
            "reference is a same-image COLMAP depth-scale proxy, not sensor-independent GT",
        ],
        "figures_generated": False,
    }
    return clean_json(bundle)


def write_rows_csv(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    fieldnames = [
        "sequence",
        "method",
        "analysis_state",
        "usability_status",
        "failure_codes",
        "native_expected_count",
        "native_covered_count",
        "native_coverage_fraction",
        "native_longest_contiguous_count",
        "native_longest_contiguous_fraction",
        "camera_expected_count",
        "camera_covered_count",
        "camera_coverage_fraction",
        "learned_full_total",
        "learned_preroll_total",
        "learned_score_total",
        "learned_action_class",
        "feature_bag_size_bytes",
        "feature_bag_sha256",
        "payload_byte_identical",
        "payload_action_class",
        "proposed_learned_candidate_count_sum",
        "proposed_pre_gate_sidecar_total_sum",
        "proposed_learned_export_gate_dropped_sum",
        "proposed_learned_pipeline_activity_observed",
        "backend_run_nondeterminism_observed",
        "trajectory_difference_not_attributable_to_frontend",
        "learning_improvement_claim_permitted",
        "learning_improvement_attribution",
        "infrastructure_incident_state",
        "corrective_replay_adopted",
        "run_dir",
    ]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            support = row.get("score_support") or {}
            usability = row.get("usability") or {}
            frontend = row.get("frontend") or {}
            corrective = row.get("infrastructure_corrective_replay") or {}
            feature_bag = row.get("feature_bag_identity") or {}
            payload_audit = row.get("frontend_payload_pair_audit") or {}
            pipeline_activity = (
                payload_audit.get("proposed_learned_pipeline_activity_full") or {}
            )
            segments = frontend.get("segments") or {}

            def learned(segment: str) -> Optional[int]:
                value = segments.get(segment)
                if not isinstance(value, Mapping):
                    return None
                observations = value.get("learned_observations")
                return observations.get("total") if isinstance(observations, Mapping) else None

            writer.writerow(
                {
                    "sequence": row.get("sequence"),
                    "method": row.get("method"),
                    "analysis_state": row.get("analysis_state"),
                    "usability_status": usability.get("status"),
                    "failure_codes": "|".join(usability.get("failure_codes") or []),
                    "native_expected_count": support.get("method_native_expected_count"),
                    "native_covered_count": support.get("method_native_covered_count"),
                    "native_coverage_fraction": support.get("method_native_coverage_fraction"),
                    "native_longest_contiguous_count": support.get("method_native_longest_contiguous_count"),
                    "native_longest_contiguous_fraction": support.get("method_native_longest_contiguous_fraction"),
                    "camera_expected_count": support.get("camera_grid_expected_count"),
                    "camera_covered_count": support.get("camera_grid_covered_count"),
                    "camera_coverage_fraction": support.get("camera_grid_coverage_fraction"),
                    "learned_full_total": learned("full"),
                    "learned_preroll_total": learned("preroll"),
                    "learned_score_total": learned("score"),
                    "learned_action_class": frontend.get("learned_action_class"),
                    "feature_bag_size_bytes": feature_bag.get("size_bytes"),
                    "feature_bag_sha256": feature_bag.get("sha256"),
                    "payload_byte_identical": payload_audit.get("payload_byte_identical"),
                    "payload_action_class": payload_audit.get("action_class"),
                    "proposed_learned_candidate_count_sum": pipeline_activity.get(
                        "learned_candidate_count_sum"
                    ),
                    "proposed_pre_gate_sidecar_total_sum": pipeline_activity.get(
                        "pre_gate_sidecar_total_sum"
                    ),
                    "proposed_learned_export_gate_dropped_sum": pipeline_activity.get(
                        "learned_export_gate_dropped_sum"
                    ),
                    "proposed_learned_pipeline_activity_observed": payload_audit.get(
                        "proposed_learned_pipeline_activity_observed"
                    ),
                    "backend_run_nondeterminism_observed": payload_audit.get(
                        "backend_run_nondeterminism_observed"
                    ),
                    "trajectory_difference_not_attributable_to_frontend": payload_audit.get(
                        "trajectory_difference_not_attributable_to_frontend"
                    ),
                    "learning_improvement_claim_permitted": payload_audit.get(
                        "learning_improvement_claim_permitted"
                    ),
                    "learning_improvement_attribution": payload_audit.get(
                        "learning_improvement_attribution"
                    ),
                    "infrastructure_incident_state": corrective.get("state"),
                    "corrective_replay_adopted": corrective.get("adopted"),
                    "run_dir": row.get("run_dir"),
                }
            )


def write_report(path: Path, bundle: Mapping[str, Any]) -> None:
    lines = [
        "# Same-history system comparison v1: strict descriptive audit",
        "",
        f"State: `{bundle['analysis_state']}`",
        "",
        "Formal accuracy is blocked for both windows. Each has only 13 native same-image "
        "COLMAP proxy rows; no winner, significance test, failure penalty, or cross-window "
        "mean ranking is permitted.",
        "",
        "## Usability and learned action",
        "",
        "| Window | Method | State | Usability | Native score support | Learned full / preroll / score |",
        "|---|---|---|---|---:|---:|",
    ]
    for row in bundle["rows"]:
        support = row.get("score_support") or {}
        usability = row.get("usability") or {}
        frontend = row.get("frontend") or {}
        segments = frontend.get("segments") or {}

        def total(name: str) -> str:
            segment = segments.get(name)
            if not isinstance(segment, Mapping):
                return "n/a"
            learned = segment.get("learned_observations")
            return str(learned.get("total")) if isinstance(learned, Mapping) else "n/a"

        expected = support.get("method_native_expected_count")
        covered = support.get("method_native_covered_count")
        coverage = support.get("method_native_coverage_fraction")
        support_text = (
            f"{covered}/{expected} ({coverage:.3f})"
            if isinstance(coverage, (int, float))
            else "pending"
        )
        lines.append(
            f"| {row['sequence']} | {row['method']} | {row['analysis_state']} | "
            f"{usability.get('status', 'n/a')} | {support_text} | "
            f"{total('full')} / {total('preroll')} / {total('score')} |"
        )
    lines.extend(["", "## Frontend payload identity gate", ""])
    for sequence in WINDOW_ORDER:
        comparison = bundle["frontend_payload_comparisons"][sequence]
        bags = comparison["feature_bags"]
        activity = comparison.get("proposed_learned_pipeline_activity_full") or {}
        for method in ("external_klt", "aquafe_proposed_safe"):
            bag = bags[method]
            lines.append(
                f"- {sequence} `{method}` features.bag: size_bytes="
                f"`{bag.get('size_bytes')}`, SHA-256=`{bag.get('sha256')}`, "
                f"exists=`{bag.get('exists')}`."
            )
        lines.extend(
            [
                f"- {sequence} payload_byte_identical: "
                f"`{comparison.get('payload_byte_identical')}`; action: "
                f"`{comparison.get('action_class')}`; proposed exported learned full total: "
                f"`{comparison.get('proposed_learned_observations_full')}`.",
                f"- {sequence} learned pipeline activity (summed diagnostics only): "
                f"observed=`{comparison.get('proposed_learned_pipeline_activity_observed')}`, "
                f"learned_candidate_count=`{activity.get('learned_candidate_count_sum')}`, "
                f"pre_gate_sidecar_total=`{activity.get('pre_gate_sidecar_total_sum')}`, "
                f"learned_export_gate_dropped=`{activity.get('learned_export_gate_dropped_sum')}`. "
                "These repeated per-frame counts are not independent samples and are not "
                "exported learned action.",
                f"- {sequence} backend_run_nondeterminism_observed: "
                f"`{comparison.get('backend_run_nondeterminism_observed')}`; "
                "trajectory_difference_not_attributable_to_frontend: "
                f"`{comparison.get('trajectory_difference_not_attributable_to_frontend')}`; "
                "learning improvement attribution: "
                f"`{comparison.get('learning_improvement_attribution')}`.",
            ]
        )
        if comparison.get("backend_run_nondeterminism_observed"):
            lines.append(
                f"- {sequence}: the feature payload bytes are identical while selected VIO "
                "SHA-256 differs. This is backend-run nondeterminism evidence; the trajectory "
                "difference cannot be credited to the learned frontend."
            )
    lines.extend(
        [
            "",
            "## A06 external-KLT infrastructure incident",
            "",
        ]
    )
    corrective = bundle["a06_external_klt_corrective_replay"]
    incident = corrective.get("original_incident") or {}
    lines.extend(
        [
            "- The original wrapper invocation was infrastructure-censored by its outer "
            "1800 s supervisor timeout after the frozen frontend export but before the score window.",
            f"- Original incident state: `{incident.get('state')}`; algorithm failure: "
            f"`{incident.get('algorithm_failure')}`; partial trajectory scored: `false`.",
            f"- Corrective adoption state: `{corrective.get('state')}`; adopted: "
            f"`{corrective.get('adopted')}`.",
            "- The corrective run is a backend-only replay of the exact frozen feature bag; "
            "it neither rewrites the original namespace nor counts as an independent method repeat.",
            "",
            "## Accuracy gate",
            "",
        ]
    )
    for sequence in WINDOW_ORDER:
        gate = bundle["accuracy"][sequence]
        lines.append(
            f"- {sequence}: `{gate['state']}` — " + ", ".join(gate["block_codes"])
        )
    lines.extend(
        [
            "",
            "## Mandatory disclosures",
            "",
        ]
    )
    for disclosure in bundle["cross_system_disclosures"]:
        lines.append(f"- {disclosure}")
    lines.extend(
        [
            "",
            "No figures were generated by this audit.",
            "",
        ]
    )
    path.write_text("\n".join(lines), encoding="utf-8")


def parse_camera_overrides(values: Sequence[str]) -> dict[str, Path]:
    result: dict[str, Path] = {}
    for value in values:
        if "=" not in value:
            raise EvidenceError(f"--camera-csv requires SEQUENCE=PATH: {value}")
        sequence, raw_path = value.split("=", 1)
        sequence = sequence.upper()
        if sequence not in WINDOWS or sequence in result or not raw_path:
            raise EvidenceError(f"invalid or duplicate --camera-csv: {value}")
        result[sequence] = Path(raw_path)
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--lock", default=str(DEFAULT_LOCK))
    parser.add_argument("--protocol", default=str(DEFAULT_PROTOCOL))
    parser.add_argument("--hfnet-bundle", default=str(DEFAULT_HFNET_BUNDLE))
    parser.add_argument("--camera-csv", action="append", default=[], metavar="SEQUENCE=PATH")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT))
    parser.add_argument(
        "--no-evaluator",
        action="store_true",
        help="audit readiness but do not invoke evaluate_vins_common_support.py",
    )
    args = parser.parse_args()
    output = Path(args.output_dir)
    output.mkdir(parents=True, exist_ok=True)
    try:
        bundle = build_bundle(
            Path(args.lock),
            Path(args.protocol),
            Path(args.hfnet_bundle),
            parse_camera_overrides(args.camera_csv),
            output,
            run_evaluator=not args.no_evaluator,
        )
    except EvidenceError as error:
        print(f"analysis_error={error}", file=sys.stderr)
        return 2
    bundle_path = output / "samehistory_system_analysis_bundle_v1.json"
    bundle_path.write_text(
        json.dumps(bundle, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    write_rows_csv(output / "samehistory_system_rows_v1.csv", bundle["rows"])
    write_report(output / "samehistory_system_analysis_report_v1.md", bundle)
    print(f"bundle={bundle_path}")
    print(f"analysis_state={bundle['analysis_state']}")
    for sequence in WINDOW_ORDER:
        print(f"{sequence.lower()}_formal_accuracy={bundle['accuracy'][sequence]['state']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
