#!/usr/bin/env python3
"""Fail closed unless runtime and reused bags match the native-q contract."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path

try:
    from scripts.build_nativeq_backend_contract import payload_hash, sha256
except ModuleNotFoundError:  # Direct `python3 scripts/...` execution.
    from build_nativeq_backend_contract import payload_hash, sha256


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONTRACT = (
    ROOT / "papers/ieee_sensors_journal_experiments/backend_quality_contract_v1.json"
)
DEFAULT_BACKEND_ROOT = Path(
    "/home/ma/SLAM/VINS-Fusion-origin/src/VINS-Fusion-master"
)
DEFAULT_BINARY = Path("/home/ma/SLAM/VINS-Fusion-origin/devel/lib/vins/vins_node")
DEFAULT_EXPORTER = ROOT / "uw_frontend/ros/export_vins_features.py"
DEFAULT_CONFIG = ROOT / (
    "uw_frontend/configs/experiments/low_texture_xfeat_seedchain_frontend.yaml"
)


def runtime_contract(
    *,
    mode: str,
    floor: float,
    alpha: float,
    raw_quality: bool,
    constant_quality: bool,
    scales: dict[str, float],
    constants: dict[str, float | None],
) -> dict[str, object]:
    return {
        "backend_quality_mode": mode,
        "backend_quality_floor": float(floor),
        "backend_quality_alpha": float(alpha),
        "raw_quality_to_backend": bool(raw_quality),
        "constant_quality_to_backend": bool(constant_quality),
        "source_quality_scales": {key: float(value) for key, value in scales.items()},
        "source_quality_constants": constants,
    }


def same_value(left: object, right: object) -> bool:
    if isinstance(left, (int, float)) and isinstance(right, (int, float)):
        return math.isclose(float(left), float(right), rel_tol=0.0, abs_tol=1e-12)
    if isinstance(left, dict) and isinstance(right, dict):
        return set(left) == set(right) and all(
            same_value(left[key], right[key]) for key in left
        )
    return left == right


def load_object(path: Path) -> dict[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def check_record(path: Path, record: dict[str, object], label: str, reasons: list[str]) -> None:
    if not path.is_file():
        reasons.append(f"{label}:MISSING:{path}")
        return
    observed = sha256(path)
    if observed != record.get("sha256"):
        reasons.append(f"{label}:SHA256_MISMATCH:{path}")


def evaluate_contract(
    *,
    contract_path: Path,
    backend_root: Path,
    binary: Path,
    exporter: Path,
    frontend_config: Path,
    runtime: dict[str, object],
    feature_bag: Path | None = None,
    bag_attestation: Path | None = None,
) -> dict[str, object]:
    reasons: list[str] = []
    contract: dict[str, object] = {}
    try:
        contract = load_object(contract_path)
    except Exception as exc:
        reasons.append(f"CONTRACT_UNREADABLE:{type(exc).__name__}:{exc}")
    if contract:
        if contract.get("schema_version") != "aqua-fe-backend-quality-consumer-contract-v1":
            reasons.append("CONTRACT_SCHEMA_MISMATCH")
        if contract.get("status") != "FROZEN_DEVELOPMENT_CONSUMER_CONTRACT":
            reasons.append("CONTRACT_STATUS_MISMATCH")
        if payload_hash(contract) != contract.get("contract_hash"):
            reasons.append("CONTRACT_HASH_MISMATCH")
        semantics = contract.get("quality_semantics", {})
        required_semantics = {
            "formal_channel_required": True,
            "clip_min": 0.05,
            "clip_max": 1.0,
            "minimum_track_observations_for_factor": 4,
            "sigma_channel_consumed": False,
        }
        if not isinstance(semantics, dict) or any(
            not same_value(semantics.get(key), value)
            for key, value in required_semantics.items()
        ):
            reasons.append("CONSUMER_SEMANTICS_MISMATCH")
        expected_runtime = contract.get("expected_runtime")
        if not isinstance(expected_runtime, dict) or not same_value(runtime, expected_runtime):
            reasons.append("RUNTIME_QUALITY_MAPPING_MISMATCH")

        records = contract.get("consumer_files")
        if not isinstance(records, list):
            reasons.append("CONSUMER_FILE_RECORDS_MISSING")
        else:
            for record in records:
                if not isinstance(record, dict) or not isinstance(record.get("path"), str):
                    reasons.append("CONSUMER_FILE_RECORD_INVALID")
                    continue
                check_record(
                    backend_root / str(record["path"]), record, "CONSUMER_FILE", reasons
                )
        binary_record = contract.get("consumer_binary")
        if isinstance(binary_record, dict):
            check_record(binary, binary_record, "CONSUMER_BINARY", reasons)
        else:
            reasons.append("CONSUMER_BINARY_RECORD_MISSING")
        mapper = contract.get("frontend_mapper")
        if isinstance(mapper, dict):
            exporter_record = mapper.get("exporter")
            config_record = mapper.get("frontend_config")
            if isinstance(exporter_record, dict):
                check_record(exporter, exporter_record, "FRONTEND_EXPORTER", reasons)
            else:
                reasons.append("FRONTEND_EXPORTER_RECORD_MISSING")
            if isinstance(config_record, dict):
                check_record(frontend_config, config_record, "FRONTEND_CONFIG", reasons)
            else:
                reasons.append("FRONTEND_CONFIG_RECORD_MISSING")
        else:
            reasons.append("FRONTEND_MAPPER_RECORD_MISSING")

    if feature_bag is not None:
        if bag_attestation is None:
            reasons.append("REUSED_BAG_ATTESTATION_REQUIRED")
        elif not bag_attestation.is_file():
            reasons.append(f"REUSED_BAG_ATTESTATION_MISSING:{bag_attestation}")
        else:
            try:
                attestation = load_object(bag_attestation)
                if attestation.get("schema_version") != "aqua-fe-nativeq-bag-attestation-v1":
                    reasons.append("REUSED_BAG_ATTESTATION_SCHEMA_MISMATCH")
                if attestation.get("contract_pass") is not True:
                    reasons.append("REUSED_BAG_ATTESTATION_NOT_PASS")
                if attestation.get("backend_contract_hash") != contract.get("contract_hash"):
                    reasons.append("REUSED_BAG_CONTRACT_HASH_MISMATCH")
                if not feature_bag.is_file():
                    reasons.append(f"REUSED_FEATURE_BAG_MISSING:{feature_bag}")
                elif attestation.get("feature_bag_sha256") != sha256(feature_bag):
                    reasons.append("REUSED_FEATURE_BAG_HASH_MISMATCH")
                if not same_value(attestation.get("runtime_quality_contract"), runtime):
                    reasons.append("REUSED_BAG_RUNTIME_MAPPING_MISMATCH")
            except Exception as exc:
                reasons.append(f"REUSED_BAG_ATTESTATION_UNREADABLE:{type(exc).__name__}:{exc}")

    action = "ALLOW_LEARNED" if not reasons else "FALLBACK_CLASSICAL"
    return {
        "schema_version": "aqua-fe-nativeq-backend-guard-decision-v1",
        "contract_pass": not reasons,
        "action": action,
        "result_label": (
            "P_LEGACY_NATIVEQ" if not reasons else "KLT_BACKEND_CONTRACT_FALLBACK"
        ),
        "counts_as_proposed_result": not reasons,
        "contract_path": str(contract_path),
        "contract_hash": contract.get("contract_hash"),
        "backend_root": str(backend_root),
        "binary": str(binary),
        "feature_bag": str(feature_bag) if feature_bag is not None else None,
        "bag_attestation": str(bag_attestation) if bag_attestation is not None else None,
        "reasons": reasons,
    }


def optional_float(value: str) -> float | None:
    stripped = value.strip()
    return None if stripped == "" else float(stripped)


def truthy(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "on"}


def write_decision(path: Path, decision: dict[str, object]) -> None:
    if path.exists():
        raise FileExistsError(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f"{path.name}.partial.{os.getpid()}")
    temporary.write_text(
        json.dumps(decision, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    os.replace(temporary, path)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contract", type=Path, default=DEFAULT_CONTRACT)
    parser.add_argument("--backend-root", type=Path, default=DEFAULT_BACKEND_ROOT)
    parser.add_argument("--binary", type=Path, default=DEFAULT_BINARY)
    parser.add_argument("--exporter", type=Path, default=DEFAULT_EXPORTER)
    parser.add_argument("--frontend-config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--mode", default=os.environ.get("BACKEND_QUALITY_MODE", ""))
    parser.add_argument("--floor", type=float, default=float(os.environ.get("BACKEND_QUALITY_FLOOR", "nan")))
    parser.add_argument("--alpha", type=float, default=float(os.environ.get("BACKEND_QUALITY_ALPHA", "nan")))
    parser.add_argument("--raw-quality", default=os.environ.get("RAW_QUALITY_TO_BACKEND", "0"))
    parser.add_argument("--constant-quality", default=os.environ.get("CONSTANT_QUALITY_TO_BACKEND", "0"))
    for name in ("learned", "sp-lg", "xfeat", "loftr"):
        env_name = f"BACKEND_{name.replace('-', '_').upper()}_QUALITY_SCALE"
        parser.add_argument(
            f"--{name}-scale", type=float, default=float(os.environ.get(env_name, "nan"))
        )
        const_env = f"BACKEND_{name.replace('-', '_').upper()}_QUALITY_CONST"
        parser.add_argument(f"--{name}-const", default=os.environ.get(const_env, ""))
    parser.add_argument("--feature-bag", type=Path)
    parser.add_argument("--bag-attestation", type=Path)
    parser.add_argument("--decision-json", type=Path, required=True)
    args = parser.parse_args()
    runtime = runtime_contract(
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
        backend_root=args.backend_root,
        binary=args.binary,
        exporter=args.exporter,
        frontend_config=args.frontend_config,
        runtime=runtime,
        feature_bag=args.feature_bag,
        bag_attestation=args.bag_attestation,
    )
    write_decision(args.decision_json, decision)
    print(
        f"NATIVEQ_BACKEND_GUARD action={decision['action']} "
        f"reasons={len(decision['reasons'])} decision={args.decision_json}"
    )
    return 0 if decision["contract_pass"] else 42


if __name__ == "__main__":
    raise SystemExit(main())
