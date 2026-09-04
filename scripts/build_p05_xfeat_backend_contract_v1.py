#!/usr/bin/env python3
"""Freeze the P05 XFeat producer and VINS native-q consumer contract."""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

import yaml

try:
    from scripts.build_nativeq_backend_contract import (
        VINS_BINARY,
        VINS_ROOT,
        file_record,
        payload_hash,
        validate_semantics,
        write_json,
    )
except ModuleNotFoundError:  # Direct ``python3 scripts/...`` execution.
    from build_nativeq_backend_contract import (  # type: ignore
        VINS_BINARY,
        VINS_ROOT,
        file_record,
        payload_hash,
        validate_semantics,
        write_json,
    )


ROOT = Path(__file__).resolve().parents[1]
BUNDLE = ROOT / "papers/ieee_sensors_journal_experiments"
DEFAULT_OUTPUT = BUNDLE / "p05/backend_consumer_contract_xfeat_v1.json"
BASE_CONTRACT = BUNDLE / "backend_quality_contract_v1.json"
VINS_WORKSPACE = Path("/home/ma/SLAM/VINS-Fusion-origin")
EXPORTER = ROOT / "uw_frontend/ros/export_vins_features.py"
P05_CONFIG = ROOT / "uw_frontend/configs/experiments/isj_p05_xfeat_pairwise_nativeq.yaml"
CONFIG_CHAIN = (
    ROOT / "uw_frontend/configs/klt_frontend.yaml",
    P05_CONFIG,
)
IMPLEMENTATION_FILES = (
    ROOT / "uw_frontend/evaluation/run_frontend_eval.py",
    ROOT / "uw_frontend/matchers/xfeat_adapter.py",
    ROOT / "uw_frontend/tracking/pairwise_matcher_tracker.py",
)
P05_RUNNER = ROOT / "scripts/run_p05_modern_xfeat_baseline.sh"
DATASET_RUNNERS = (
    ROOT / "scripts/run_ntnu_vins_eval.sh",
    ROOT / "scripts/run_aqualoc_archaeo_vins_eval.sh",
    ROOT / "scripts/run_aqualoc_real_vins_eval.sh",
    ROOT / "scripts/run_afrl_cave_vins_eval.sh",
)
XFEAT_ROOT = ROOT / "external_tools/accelerated_features"
XFEAT_WEIGHT = XFEAT_ROOT / "weights/xfeat.pt"
XFEAT_LICENSE = XFEAT_ROOT / "LICENSE"


def _workspace_record(path: Path) -> dict[str, object]:
    return file_record(path, root=ROOT)


def _git_head(path: Path) -> str:
    completed = subprocess.run(
        ["git", "-C", str(path), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def _validate_base_contract(contract: dict[str, object]) -> None:
    if contract.get("schema_version") != "aqua-fe-backend-quality-consumer-contract-v1":
        raise ValueError("base backend contract schema mismatch")
    if contract.get("status") != "FROZEN_DEVELOPMENT_CONSUMER_CONTRACT":
        raise ValueError("base backend contract status mismatch")
    if payload_hash(contract) != contract.get("contract_hash"):
        raise ValueError("base backend contract hash mismatch")


def _validate_p05_identity() -> None:
    config = yaml.safe_load(P05_CONFIG.read_text(encoding="utf-8"))
    expected = {
        "pairwise.max_features": (config.get("pairwise") or {}).get("max_features"),
        "xfeat.top_k": (config.get("xfeat") or {}).get("top_k"),
        "xfeat.semi_dense": (config.get("xfeat") or {}).get("semi_dense"),
        "measurement_selection.enabled": (config.get("measurement_selection") or {}).get(
            "enabled"
        ),
        "backend_quality.mode": (config.get("backend_quality") or {}).get("mode"),
        "backend_quality.floor": (config.get("backend_quality") or {}).get("floor"),
        "backend_quality.alpha": (config.get("backend_quality") or {}).get("alpha"),
    }
    required = {
        "pairwise.max_features": 350,
        "xfeat.top_k": 2048,
        "xfeat.semi_dense": False,
        "measurement_selection.enabled": False,
        "backend_quality.mode": "vins_safe",
        "backend_quality.floor": 0.8,
        "backend_quality.alpha": 0.65,
    }
    if expected != required:
        raise ValueError(f"P05 config semantic mismatch: {expected}")

    runner = P05_RUNNER.read_text(encoding="utf-8")
    required_fragments = (
        "export FRONTEND_CONFIG=",
        "export PREPROCESS=adaptive_clahe",
        "export PROCESS_SKIPPED_FRAMES=1",
        "export MEASUREMENT_SELECTION=0",
        "export FORMAL_THREE_LAYER_EXPORT=0",
        "export VINS_SAFE_SOURCE_SELECTION=0",
        "export EXPORT_MAX_FEATURES=350",
        "export VINS_MAX_CNT=350",
        "export SEMIDENSE_FALLBACK_METHOD=none",
        "export BACKEND_QUALITY_MODE=vins_safe",
        "export BACKEND_QUALITY_ALPHA=0.65",
        "export BACKEND_QUALITY_FLOOR=0.80",
        "method=xfeat",
    )
    missing = [fragment for fragment in required_fragments if fragment not in runner]
    if missing:
        raise ValueError(f"P05 runner semantic fragments missing: {missing}")


def build_payload() -> dict[str, object]:
    validate_semantics(VINS_ROOT)
    _validate_p05_identity()
    base_contract = json.loads(BASE_CONTRACT.read_text(encoding="utf-8"))
    _validate_base_contract(base_contract)

    payload: dict[str, object] = {
        "schema_version": "aqua-fe-p05-xfeat-backend-consumer-contract-v1",
        "status": "FROZEN_DEVELOPMENT_P05_CONSUMER_CONTRACT",
        "baseline_id": "M_xfeat_pairwise_nativeq_v1",
        "scope": "P05_XFEAT_PAIRWISE_TO_VINS_FUSION_ORIGIN_EXTERNAL_POINTCLOUD",
        "workspace_root": str(ROOT),
        "base_backend_contract": {
            **file_record(BASE_CONTRACT),
            "contract_hash": base_contract["contract_hash"],
        },
        "backend_consumer": {
            "consumer_id": base_contract["consumer_id"],
            "vins_workspace": str(VINS_WORKSPACE),
            "consumer_root": base_contract["consumer_root"],
            "consumer_files": base_contract["consumer_files"],
            "consumer_binary": base_contract["consumer_binary"],
            "quality_semantics": base_contract["quality_semantics"],
        },
        "backend_runtime": base_contract["expected_runtime"],
        "frontend": {
            "exporter": file_record(EXPORTER),
            "primary_config": file_record(P05_CONFIG),
            "config_chain": [_workspace_record(path) for path in CONFIG_CHAIN],
            "implementation_files": [
                _workspace_record(path) for path in IMPLEMENTATION_FILES
            ],
            "runtime": {
                "method": "xfeat",
                "preprocess": "adaptive_clahe",
                "process_skipped_frames": True,
                "measurement_selection": False,
                "formal_three_layer_export": False,
                "vins_safe_source_selection": False,
                "export_max_features": 350,
                "vins_max_cnt": 350,
                "semidense_fallback_method": "none",
                "vins_multiple_thread": False,
                "export_features": True,
                "force_fresh_export_without_override": True,
            },
        },
        "xfeat_dependency": {
            "path": str(XFEAT_ROOT),
            "git_commit": _git_head(XFEAT_ROOT),
            "weight": file_record(XFEAT_WEIGHT),
            "license": file_record(XFEAT_LICENSE),
        },
        "execution": {
            "baseline_runner": _workspace_record(P05_RUNNER),
            "dataset_runners": [_workspace_record(path) for path in DATASET_RUNNERS],
            "run_vins_allowed": [False, True],
            "vins_replays": "serial_single_threaded",
        },
        "sampling": {
            "every_n": 2,
            "frame_offset_by_family": {
                "ntnu": 1,
                "aqualoc_archaeology": 1,
                "aqualoc_harbor": 1,
                "afrl": 0,
            },
        },
        "reused_bag": {
            "attestation_schema": "aqua-fe-p05-xfeat-bag-attestation-v1",
            "feature_topic": "/feature_tracker/feature",
            "required_source_code": 20,
            "required_is_learned": 1,
            "bag_sha256_required": True,
            "frontend_metrics_sha256_required": True,
        },
        "mismatch_action": {
            "action": "FALLBACK_CLASSICAL",
            "fallback": "fresh_independent_KLT_export_with_constant_q1",
            "forbidden": "reuse_or_filter_the_P05_XFeat_bag_as_fallback",
            "result_label": "KLT_BACKEND_CONTRACT_FALLBACK_P05_M_REJECTED",
            "counts_as_modern_baseline": False,
        },
    }
    payload["contract_hash"] = payload_hash(payload)
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    payload = build_payload()
    write_json(args.output, payload)
    print(f"P05_XFEAT_BACKEND_CONTRACT_FROZEN hash={payload['contract_hash']}")
    print(f"wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
