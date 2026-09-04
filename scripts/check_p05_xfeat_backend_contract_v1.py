#!/usr/bin/env python3
"""Fail closed unless the P05 XFeat producer and VINS consumer are frozen."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
from pathlib import Path

try:
    from scripts.build_nativeq_backend_contract import payload_hash, sha256
    from scripts.check_nativeq_backend_contract import (
        optional_float,
        runtime_contract,
        same_value,
        truthy,
        write_decision,
    )
except ModuleNotFoundError:  # Direct ``python3 scripts/...`` execution.
    from build_nativeq_backend_contract import payload_hash, sha256  # type: ignore
    from check_nativeq_backend_contract import (  # type: ignore
        optional_float,
        runtime_contract,
        same_value,
        truthy,
        write_decision,
    )


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONTRACT = (
    ROOT
    / "papers/ieee_sensors_journal_experiments/p05/backend_consumer_contract_xfeat_v1.json"
)
DEFAULT_VINS_WORKSPACE = Path("/home/ma/SLAM/VINS-Fusion-origin")
DEFAULT_BACKEND_ROOT = DEFAULT_VINS_WORKSPACE / "src/VINS-Fusion-master"
DEFAULT_BINARY = DEFAULT_VINS_WORKSPACE / "devel/lib/vins/vins_node"
DEFAULT_EXPORTER = ROOT / "uw_frontend/ros/export_vins_features.py"
DEFAULT_CONFIG = ROOT / "uw_frontend/configs/experiments/isj_p05_xfeat_pairwise_nativeq.yaml"

FAMILY_ALIASES = {
    "ntnu": "ntnu",
    "aqualoc_archaeology": "aqualoc_archaeology",
    "aqualoc_archaeo": "aqualoc_archaeology",
    "aqualoc_harbor": "aqualoc_harbor",
    "aqualoc_real": "aqualoc_harbor",
    "afrl": "afrl",
}


def load_object(path: Path) -> dict[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def _resolved(path: Path) -> Path:
    return path.expanduser().resolve(strict=False)


def _record_path(record: dict[str, object], *, root: Path | None = None) -> Path | None:
    raw = record.get("path")
    if not isinstance(raw, str) or not raw:
        return None
    path = Path(raw)
    return path if path.is_absolute() or root is None else root / path


def _check_record(
    observed_path: Path,
    record: object,
    label: str,
    reasons: list[str],
    *,
    require_recorded_path: bool = True,
    record_root: Path | None = None,
) -> None:
    if not isinstance(record, dict):
        reasons.append(f"{label}:RECORD_MISSING")
        return
    expected_path = _record_path(record, root=record_root)
    if expected_path is None:
        reasons.append(f"{label}:RECORDED_PATH_MISSING")
    elif require_recorded_path and _resolved(observed_path) != _resolved(expected_path):
        reasons.append(f"{label}:PATH_MISMATCH:{observed_path}")
    if not observed_path.is_file():
        reasons.append(f"{label}:MISSING:{observed_path}")
        return
    if sha256(observed_path) != record.get("sha256"):
        reasons.append(f"{label}:SHA256_MISMATCH:{observed_path}")
    size = record.get("size_bytes")
    if not isinstance(size, int) or observed_path.stat().st_size != size:
        reasons.append(f"{label}:SIZE_MISMATCH:{observed_path}")


def canonical_family(value: str) -> str | None:
    return FAMILY_ALIASES.get(value)


def attestation_payload_hash(payload: dict[str, object]) -> str:
    normalized = {
        key: value
        for key, value in payload.items()
        if key not in {"attestation_hash", "generated_at_utc"}
    }
    encoded = json.dumps(
        normalized, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def producer_identity(contract: dict[str, object]) -> dict[str, object]:
    frontend = contract.get("frontend")
    execution = contract.get("execution")
    if not isinstance(frontend, dict) or not isinstance(execution, dict):
        return {}
    return {
        "exporter_sha256": (frontend.get("exporter") or {}).get("sha256"),
        "primary_config_sha256": (frontend.get("primary_config") or {}).get("sha256"),
        "config_chain_sha256": [
            record.get("sha256")
            for record in frontend.get("config_chain", [])
            if isinstance(record, dict)
        ],
        "implementation_sha256": [
            record.get("sha256")
            for record in frontend.get("implementation_files", [])
            if isinstance(record, dict)
        ],
        "baseline_runner_sha256": (execution.get("baseline_runner") or {}).get(
            "sha256"
        ),
    }


def _check_git_dependency(record: object, reasons: list[str]) -> None:
    if not isinstance(record, dict):
        reasons.append("XFEAT_DEPENDENCY_RECORD_MISSING")
        return
    raw_path = record.get("path")
    expected_commit = record.get("git_commit")
    if not isinstance(raw_path, str) or not isinstance(expected_commit, str):
        reasons.append("XFEAT_DEPENDENCY_IDENTITY_MISSING")
        return
    path = Path(raw_path)
    try:
        completed = subprocess.run(
            ["git", "-C", str(path), "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        )
        if completed.stdout.strip() != expected_commit:
            reasons.append("XFEAT_GIT_COMMIT_MISMATCH")
    except Exception as exc:
        reasons.append(f"XFEAT_GIT_COMMIT_UNREADABLE:{type(exc).__name__}:{exc}")
    for key, label in (("weight", "XFEAT_WEIGHT"), ("license", "XFEAT_LICENSE")):
        item = record.get(key)
        if isinstance(item, dict):
            path_value = _record_path(item)
            if path_value is None:
                reasons.append(f"{label}:RECORDED_PATH_MISSING")
            else:
                _check_record(path_value, item, label, reasons)
        else:
            reasons.append(f"{label}:RECORD_MISSING")


def _check_reused_bag(
    *,
    feature_bag: Path,
    bag_attestation: Path | None,
    contract: dict[str, object],
    backend_runtime: dict[str, object],
    frontend_runtime: dict[str, object],
    reasons: list[str],
) -> None:
    if bag_attestation is None:
        reasons.append("REUSED_BAG_ATTESTATION_REQUIRED")
        return
    if not bag_attestation.is_file():
        reasons.append(f"REUSED_BAG_ATTESTATION_MISSING:{bag_attestation}")
        return
    try:
        attestation = load_object(bag_attestation)
    except Exception as exc:
        reasons.append(f"REUSED_BAG_ATTESTATION_UNREADABLE:{type(exc).__name__}:{exc}")
        return

    reused_contract = contract.get("reused_bag")
    expected_schema = (
        reused_contract.get("attestation_schema")
        if isinstance(reused_contract, dict)
        else None
    )
    if attestation.get("schema_version") != expected_schema:
        reasons.append("REUSED_BAG_ATTESTATION_SCHEMA_MISMATCH")
    if attestation.get("status") != "PASS" or attestation.get("contract_pass") is not True:
        reasons.append("REUSED_BAG_ATTESTATION_NOT_PASS")
    if attestation_payload_hash(attestation) != attestation.get("attestation_hash"):
        reasons.append("REUSED_BAG_ATTESTATION_HASH_MISMATCH")
    if attestation.get("baseline_id") != contract.get("baseline_id"):
        reasons.append("REUSED_BAG_BASELINE_ID_MISMATCH")
    if attestation.get("backend_contract_hash") != contract.get("contract_hash"):
        reasons.append("REUSED_BAG_CONTRACT_HASH_MISMATCH")
    if not same_value(attestation.get("backend_runtime"), backend_runtime):
        reasons.append("REUSED_BAG_BACKEND_RUNTIME_MISMATCH")
    if not same_value(attestation.get("frontend_runtime"), frontend_runtime):
        reasons.append("REUSED_BAG_FRONTEND_RUNTIME_MISMATCH")
    if not same_value(attestation.get("producer_identity"), producer_identity(contract)):
        reasons.append("REUSED_BAG_PRODUCER_IDENTITY_MISMATCH")

    if not feature_bag.is_file():
        reasons.append(f"REUSED_FEATURE_BAG_MISSING:{feature_bag}")
    else:
        if attestation.get("feature_bag_sha256") != sha256(feature_bag):
            reasons.append("REUSED_FEATURE_BAG_HASH_MISMATCH")
        if attestation.get("feature_bag_size_bytes") != feature_bag.stat().st_size:
            reasons.append("REUSED_FEATURE_BAG_SIZE_MISMATCH")

    metrics_raw = attestation.get("frontend_metrics")
    metrics_hash = attestation.get("frontend_metrics_sha256")
    if not isinstance(metrics_raw, str) or not isinstance(metrics_hash, str):
        reasons.append("REUSED_BAG_FRONTEND_METRICS_BINDING_MISSING")
    else:
        metrics = Path(metrics_raw)
        if not metrics.is_file():
            reasons.append(f"REUSED_BAG_FRONTEND_METRICS_MISSING:{metrics}")
        elif sha256(metrics) != metrics_hash:
            reasons.append("REUSED_BAG_FRONTEND_METRICS_HASH_MISMATCH")

    audit = attestation.get("bag_audit")
    if not isinstance(audit, dict) or audit.get("status") != "PASS":
        reasons.append("REUSED_BAG_CONTENT_AUDIT_NOT_PASS")


def evaluate_contract(
    *,
    contract_path: Path,
    workspace_root: Path,
    vins_workspace: Path,
    backend_root: Path,
    binary: Path,
    exporter: Path,
    frontend_config: Path,
    family: str,
    every_n: int,
    frame_offset: int,
    backend_runtime: dict[str, object],
    frontend_runtime: dict[str, object],
    run_vins: bool,
    feature_bag: Path | None = None,
    bag_attestation: Path | None = None,
) -> dict[str, object]:
    reasons: list[str] = []
    contract: dict[str, object] = {}
    try:
        contract = load_object(contract_path)
    except Exception as exc:
        reasons.append(f"CONTRACT_UNREADABLE:{type(exc).__name__}:{exc}")

    canonical = canonical_family(family)
    if canonical is None:
        reasons.append(f"UNSUPPORTED_DATASET_FAMILY:{family}")

    if contract:
        if contract.get("schema_version") != "aqua-fe-p05-xfeat-backend-consumer-contract-v1":
            reasons.append("CONTRACT_SCHEMA_MISMATCH")
        if contract.get("status") != "FROZEN_DEVELOPMENT_P05_CONSUMER_CONTRACT":
            reasons.append("CONTRACT_STATUS_MISMATCH")
        if payload_hash(contract) != contract.get("contract_hash"):
            reasons.append("CONTRACT_HASH_MISMATCH")
        recorded_workspace = contract.get("workspace_root")
        if not isinstance(recorded_workspace, str) or _resolved(workspace_root) != _resolved(
            Path(recorded_workspace or ".")
        ):
            reasons.append("WORKSPACE_ROOT_MISMATCH")

        base_record = contract.get("base_backend_contract")
        if isinstance(base_record, dict):
            base_path = _record_path(base_record)
            if base_path is None:
                reasons.append("BASE_BACKEND_CONTRACT_PATH_MISSING")
            else:
                _check_record(base_path, base_record, "BASE_BACKEND_CONTRACT", reasons)
                try:
                    base = load_object(base_path)
                    if payload_hash(base) != base_record.get("contract_hash"):
                        reasons.append("BASE_BACKEND_CONTRACT_HASH_MISMATCH")
                except Exception as exc:
                    reasons.append(
                        f"BASE_BACKEND_CONTRACT_UNREADABLE:{type(exc).__name__}:{exc}"
                    )
        else:
            reasons.append("BASE_BACKEND_CONTRACT_RECORD_MISSING")

        consumer = contract.get("backend_consumer")
        if isinstance(consumer, dict):
            expected_workspace = consumer.get("vins_workspace")
            expected_root = consumer.get("consumer_root")
            if not isinstance(expected_workspace, str) or _resolved(vins_workspace) != _resolved(
                Path(expected_workspace or ".")
            ):
                reasons.append("VINS_WORKSPACE_MISMATCH")
            if not isinstance(expected_root, str) or _resolved(backend_root) != _resolved(
                Path(expected_root or ".")
            ):
                reasons.append("CONSUMER_ROOT_MISMATCH")
            records = consumer.get("consumer_files")
            if isinstance(records, list):
                for record in records:
                    if isinstance(record, dict) and isinstance(record.get("path"), str):
                        _check_record(
                            backend_root / str(record["path"]),
                            record,
                            "CONSUMER_FILE",
                            reasons,
                            record_root=backend_root,
                        )
                    else:
                        reasons.append("CONSUMER_FILE_RECORD_INVALID")
            else:
                reasons.append("CONSUMER_FILE_RECORDS_MISSING")
            _check_record(binary, consumer.get("consumer_binary"), "CONSUMER_BINARY", reasons)
        else:
            reasons.append("BACKEND_CONSUMER_RECORD_MISSING")

        if not same_value(backend_runtime, contract.get("backend_runtime")):
            reasons.append("BACKEND_RUNTIME_MISMATCH")

        frontend = contract.get("frontend")
        if isinstance(frontend, dict):
            _check_record(exporter, frontend.get("exporter"), "P05_EXPORTER", reasons)
            _check_record(
                frontend_config, frontend.get("primary_config"), "P05_PRIMARY_CONFIG", reasons
            )
            for key, label in (
                ("config_chain", "P05_CONFIG_CHAIN"),
                ("implementation_files", "P05_IMPLEMENTATION"),
            ):
                records = frontend.get(key)
                if not isinstance(records, list):
                    reasons.append(f"{label}:RECORDS_MISSING")
                    continue
                for record in records:
                    if not isinstance(record, dict):
                        reasons.append(f"{label}:RECORD_INVALID")
                        continue
                    path = _record_path(record, root=workspace_root)
                    if path is None:
                        reasons.append(f"{label}:RECORDED_PATH_MISSING")
                        continue
                    _check_record(path, record, label, reasons, record_root=workspace_root)
            if not same_value(frontend_runtime, frontend.get("runtime")):
                reasons.append("P05_FRONTEND_RUNTIME_MISMATCH")
        else:
            reasons.append("P05_FRONTEND_RECORD_MISSING")

        execution = contract.get("execution")
        if isinstance(execution, dict):
            execution_records = [execution.get("baseline_runner")]
            dataset_records = execution.get("dataset_runners")
            if isinstance(dataset_records, list):
                execution_records.extend(dataset_records)
            else:
                reasons.append("P05_DATASET_RUNNER_RECORDS_MISSING")
            for record in execution_records:
                if not isinstance(record, dict):
                    reasons.append("P05_EXECUTION_RECORD_INVALID")
                    continue
                path = _record_path(record, root=workspace_root)
                if path is None:
                    reasons.append("P05_EXECUTION_PATH_MISSING")
                    continue
                _check_record(
                    path, record, "P05_EXECUTION", reasons, record_root=workspace_root
                )
            allowed = execution.get("run_vins_allowed")
            if not isinstance(allowed, list) or run_vins not in allowed:
                reasons.append("RUN_VINS_VALUE_NOT_ALLOWED")
        else:
            reasons.append("P05_EXECUTION_RECORD_MISSING")

        sampling = contract.get("sampling")
        if isinstance(sampling, dict):
            if every_n != sampling.get("every_n"):
                reasons.append("P05_EVERY_N_MISMATCH")
            offsets = sampling.get("frame_offset_by_family")
            if (
                canonical is None
                or not isinstance(offsets, dict)
                or frame_offset != offsets.get(canonical)
            ):
                reasons.append("P05_FRAME_OFFSET_MISMATCH")
        else:
            reasons.append("P05_SAMPLING_RECORD_MISSING")

        _check_git_dependency(contract.get("xfeat_dependency"), reasons)

        if feature_bag is not None:
            _check_reused_bag(
                feature_bag=feature_bag,
                bag_attestation=bag_attestation,
                contract=contract,
                backend_runtime=backend_runtime,
                frontend_runtime=frontend_runtime,
                reasons=reasons,
            )

    action = "ALLOW_M_XFEAT" if not reasons else "FALLBACK_CLASSICAL"
    return {
        "schema_version": "aqua-fe-p05-xfeat-backend-guard-decision-v1",
        "contract_pass": not reasons,
        "action": action,
        "result_label": (
            "M_XFEAT_PAIRWISE_NATIVEQ_V1"
            if not reasons
            else "KLT_BACKEND_CONTRACT_FALLBACK_P05_M_REJECTED"
        ),
        "counts_as_modern_baseline": not reasons,
        "contract_path": str(contract_path),
        "contract_hash": contract.get("contract_hash"),
        "workspace_root": str(workspace_root),
        "vins_workspace": str(vins_workspace),
        "backend_root": str(backend_root),
        "binary": str(binary),
        "family": canonical or family,
        "every_n": every_n,
        "frame_offset": frame_offset,
        "run_vins": run_vins,
        "feature_bag": str(feature_bag) if feature_bag is not None else None,
        "feature_bag_sha256": (
            sha256(feature_bag) if feature_bag is not None and feature_bag.is_file() else None
        ),
        "bag_attestation": str(bag_attestation) if bag_attestation is not None else None,
        "reasons": reasons,
    }


def _frontend_runtime_from_args(args: argparse.Namespace) -> dict[str, object]:
    return {
        "method": args.method,
        "preprocess": args.preprocess,
        "process_skipped_frames": truthy(args.process_skipped_frames),
        "measurement_selection": truthy(args.measurement_selection),
        "formal_three_layer_export": truthy(args.formal_three_layer_export),
        "vins_safe_source_selection": truthy(args.vins_safe_source_selection),
        "export_max_features": args.export_max_features,
        "vins_max_cnt": args.vins_max_cnt,
        "semidense_fallback_method": args.semidense_fallback_method,
        "vins_multiple_thread": truthy(args.vins_multiple_thread),
        "export_features": truthy(args.export_features),
        "force_fresh_export_without_override": truthy(args.force_export),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contract", type=Path, default=DEFAULT_CONTRACT)
    parser.add_argument("--workspace-root", type=Path, default=ROOT)
    parser.add_argument("--vins-workspace", type=Path, default=DEFAULT_VINS_WORKSPACE)
    parser.add_argument("--backend-root", type=Path, default=DEFAULT_BACKEND_ROOT)
    parser.add_argument("--binary", type=Path, default=DEFAULT_BINARY)
    parser.add_argument("--exporter", type=Path, default=DEFAULT_EXPORTER)
    parser.add_argument("--frontend-config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--family", required=True)
    parser.add_argument("--every-n", type=int, required=True)
    parser.add_argument("--frame-offset", type=int, required=True)
    parser.add_argument(
        "--run-vins", choices=("0", "1"), default=os.environ.get("RUN_VINS", "0")
    )
    parser.add_argument("--method", default=os.environ.get("P05_METHOD", "xfeat"))
    parser.add_argument("--preprocess", default=os.environ.get("PREPROCESS", ""))
    parser.add_argument(
        "--process-skipped-frames", default=os.environ.get("PROCESS_SKIPPED_FRAMES", "0")
    )
    parser.add_argument(
        "--measurement-selection", default=os.environ.get("MEASUREMENT_SELECTION", "1")
    )
    parser.add_argument(
        "--formal-three-layer-export", default=os.environ.get("FORMAL_THREE_LAYER_EXPORT", "1")
    )
    parser.add_argument(
        "--vins-safe-source-selection", default=os.environ.get("VINS_SAFE_SOURCE_SELECTION", "1")
    )
    parser.add_argument(
        "--export-max-features", type=int, default=int(os.environ.get("EXPORT_MAX_FEATURES", "-1"))
    )
    parser.add_argument("--vins-max-cnt", type=int, default=int(os.environ.get("VINS_MAX_CNT", "-1")))
    parser.add_argument(
        "--semidense-fallback-method", default=os.environ.get("SEMIDENSE_FALLBACK_METHOD", "")
    )
    parser.add_argument(
        "--vins-multiple-thread", default=os.environ.get("VINS_MULTIPLE_THREAD", "1")
    )
    parser.add_argument("--export-features", default=os.environ.get("EXPORT_FEATURES", "0"))
    parser.add_argument("--force-export", default=os.environ.get("FORCE_EXPORT", "0"))
    parser.add_argument("--mode", default=os.environ.get("BACKEND_QUALITY_MODE", ""))
    parser.add_argument(
        "--floor", type=float, default=float(os.environ.get("BACKEND_QUALITY_FLOOR", "nan"))
    )
    parser.add_argument(
        "--alpha", type=float, default=float(os.environ.get("BACKEND_QUALITY_ALPHA", "nan"))
    )
    parser.add_argument("--raw-quality", default=os.environ.get("RAW_QUALITY_TO_BACKEND", "0"))
    parser.add_argument(
        "--constant-quality", default=os.environ.get("CONSTANT_QUALITY_TO_BACKEND", "0")
    )
    for name in ("learned", "sp-lg", "xfeat", "loftr"):
        normalized = name.replace("-", "_").upper()
        parser.add_argument(
            f"--{name}-scale",
            type=float,
            default=float(os.environ.get(f"BACKEND_{normalized}_QUALITY_SCALE", "nan")),
        )
        parser.add_argument(
            f"--{name}-const", default=os.environ.get(f"BACKEND_{normalized}_QUALITY_CONST", "")
        )
    parser.add_argument("--feature-bag", type=Path)
    parser.add_argument("--bag-attestation", type=Path)
    parser.add_argument("--decision-json", type=Path, required=True)
    args = parser.parse_args()

    backend_runtime = runtime_contract(
        mode=args.mode,
        floor=args.floor,
        alpha=args.alpha,
        raw_quality=truthy(args.raw_quality),
        constant_quality=truthy(args.constant_quality),
        scales={
            "learned": args.learned_scale,
            "sp_lg": args.sp_lg_scale,
            "xfeat": args.xfeat_scale,
            "loftr": args.loftr_scale,
        },
        constants={
            "learned": optional_float(args.learned_const),
            "sp_lg": optional_float(args.sp_lg_const),
            "xfeat": optional_float(args.xfeat_const),
            "loftr": optional_float(args.loftr_const),
        },
    )
    decision = evaluate_contract(
        contract_path=args.contract,
        workspace_root=args.workspace_root,
        vins_workspace=args.vins_workspace,
        backend_root=args.backend_root,
        binary=args.binary,
        exporter=args.exporter,
        frontend_config=args.frontend_config,
        family=args.family,
        every_n=args.every_n,
        frame_offset=args.frame_offset,
        backend_runtime=backend_runtime,
        frontend_runtime=_frontend_runtime_from_args(args),
        run_vins=args.run_vins == "1",
        feature_bag=args.feature_bag,
        bag_attestation=args.bag_attestation,
    )
    write_decision(args.decision_json, decision)
    print(
        f"P05_XFEAT_BACKEND_GUARD action={decision['action']} "
        f"reasons={len(decision['reasons'])} decision={args.decision_json}"
    )
    return 0 if decision["contract_pass"] else 42


if __name__ == "__main__":
    raise SystemExit(main())
