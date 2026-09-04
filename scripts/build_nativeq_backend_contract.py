#!/usr/bin/env python3
"""Freeze the VINS native-q consumer and frontend mapper contract."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BUNDLE = ROOT / "papers/ieee_sensors_journal_experiments"
DEFAULT_OUTPUT = BUNDLE / "backend_quality_contract_v1.json"
VINS_ROOT = Path("/home/ma/SLAM/VINS-Fusion-origin/src/VINS-Fusion-master")
VINS_BINARY = Path("/home/ma/SLAM/VINS-Fusion-origin/devel/lib/vins/vins_node")
EXPORTER = ROOT / "uw_frontend/ros/export_vins_features.py"
FRONTEND_CONFIG = ROOT / (
    "uw_frontend/configs/experiments/low_texture_xfeat_seedchain_frontend.yaml"
)
V3_LOCK = BUNDLE / "method_lock_nativeq_legacy_candidate_v3.json"

CONSUMER_FILES = (
    "vins_estimator/src/rosNodeTest.cpp",
    "vins_estimator/src/estimator/feature_manager.cpp",
    "vins_estimator/src/estimator/feature_manager.h",
    "vins_estimator/src/estimator/estimator.cpp",
    "vins_estimator/src/factor/projectionTwoFrameOneCamFactor.cpp",
    "vins_estimator/src/factor/projectionTwoFrameOneCamFactor.h",
    "vins_estimator/src/factor/projectionTwoFrameTwoCamFactor.cpp",
    "vins_estimator/src/factor/projectionTwoFrameTwoCamFactor.h",
    "vins_estimator/src/factor/projectionOneFrameTwoCamFactor.cpp",
    "vins_estimator/src/factor/projectionOneFrameTwoCamFactor.h",
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def payload_hash(payload: dict[str, object]) -> str:
    normalized = {
        key: value
        for key, value in payload.items()
        if key not in {"contract_hash", "generated_at_utc"}
    }
    encoded = json.dumps(
        normalized, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def file_record(path: Path, *, root: Path | None = None) -> dict[str, object]:
    if not path.is_file():
        raise FileNotFoundError(path)
    label = str(path.relative_to(root)) if root is not None else str(path)
    return {"path": label, "sha256": sha256(path), "size_bytes": path.stat().st_size}


def validate_semantics(vins_root: Path) -> None:
    ros_node = (vins_root / CONSUMER_FILES[0]).read_text(encoding="utf-8")
    required_ros = (
        "double visual_quality = 1.0;",
        'name == "quality"',
        "std::max(0.05, std::min(1.0",
        "estimator.inputFeature(t, featureFrame);",
    )
    for fragment in required_ros:
        if fragment not in ros_node:
            raise ValueError(f"quality callback semantic missing: {fragment}")

    feature_manager = (vins_root / CONSUMER_FILES[2]).read_text(encoding="utf-8")
    if feature_manager.count("visual_quality = std::max(0.05") < 2:
        raise ValueError("FeaturePerFrame quality clipping/min contract missing")
    if "std::min(visual_quality, _point(7))" not in feature_manager:
        raise ValueError("stereo same-frame min-quality contract missing")

    estimator = (
        vins_root / "vins_estimator/src/estimator/estimator.cpp"
    ).read_text(encoding="utf-8")
    if estimator.count("if (it_per_id.used_num < 4)") < 2:
        raise ValueError("four-observation factor gate missing")
    if estimator.count("setQualityWeight(std::min") < 4:
        raise ValueError("temporal min(first,current) quality contract missing")
    if estimator.count("setQualityWeight(it_per_frame.visual_quality)") < 2:
        raise ValueError("same-frame stereo quality contract missing")

    for relative in CONSUMER_FILES:
        if not (vins_root / relative).is_file():
            raise FileNotFoundError(vins_root / relative)
    factor_cpp = [relative for relative in CONSUMER_FILES if relative.endswith("Factor.cpp")]
    for relative in factor_cpp:
        text = (vins_root / relative).read_text(encoding="utf-8")
        for fragment in (
            "quality_weight = std::max(0.05, std::min(1.0, quality));",
            "const double sqrt_quality = std::sqrt(quality_weight);",
            "residual = sqrt_quality * sqrt_info * residual;",
            "reduce = sqrt_quality * sqrt_info * reduce;",
        ):
            if fragment not in text:
                raise ValueError(f"factor quality semantic missing in {relative}: {fragment}")

    consumer_text = "\n".join(
        (vins_root / relative).read_text(encoding="utf-8", errors="replace")
        for relative in CONSUMER_FILES
    )
    if re_search_sigma(consumer_text):
        raise ValueError("consumer unexpectedly references the diagnostic sigma channel")


def re_search_sigma(text: str) -> bool:
    import re

    return re.search(r"(?<![A-Za-z0-9_])sigma(?![A-Za-z0-9_])", text, re.IGNORECASE) is not None


def build_payload() -> dict[str, object]:
    validate_semantics(VINS_ROOT)
    v3 = json.loads(V3_LOCK.read_text(encoding="utf-8"))
    payload: dict[str, object] = {
        "schema_version": "aqua-fe-backend-quality-consumer-contract-v1",
        "status": "FROZEN_DEVELOPMENT_CONSUMER_CONTRACT",
        "consumer_id": "vins-fusion-origin-external-pointcloud-nativeq-v1",
        "scope": "VINS_FUSION_ORIGIN_EXTERNAL_POINTCLOUD_ONLY",
        "quality_semantics": {
            "input_topic": "/feature_tracker/feature",
            "channel": "quality",
            "formal_channel_required": True,
            "missing_channel_backend_default": 1.0,
            "clip_min": 0.05,
            "clip_max": 1.0,
            "minimum_track_observations_for_factor": 4,
            "temporal_weight": "min(anchor_first_observation_q,current_observation_q)",
            "same_frame_stereo_weight": "min(left_q,right_q)",
            "factor_scale": "sqrt(q)_multiplies_residual_and_jacobians",
            "optimization_and_marginalization_both_weighted": True,
            "sigma_channel_consumed": False,
            "sigma_role": "export_and_audit_diagnostic_only",
        },
        "expected_runtime": {
            "backend_quality_mode": "vins_safe",
            "backend_quality_floor": 0.8,
            "backend_quality_alpha": 0.65,
            "raw_quality_to_backend": False,
            "constant_quality_to_backend": False,
            "source_quality_scales": {
                "learned": 1.0,
                "sp_lg": 1.0,
                "xfeat": 1.0,
                "loftr": 1.0,
            },
            "source_quality_constants": {
                "learned": None,
                "sp_lg": None,
                "xfeat": None,
                "loftr": None,
            },
        },
        "consumer_root": str(VINS_ROOT),
        "consumer_files": [
            file_record(VINS_ROOT / relative, root=VINS_ROOT)
            for relative in CONSUMER_FILES
        ],
        "consumer_binary": file_record(VINS_BINARY),
        "frontend_mapper": {
            "exporter": file_record(EXPORTER),
            "frontend_config": file_record(FRONTEND_CONFIG),
            "mapping": "vins_safe_floor0p80_alpha0p65_source_scales_one",
        },
        "base_method_lock": {
            **file_record(V3_LOCK),
            "candidate_lock_hash": v3["candidate_lock_hash"],
            "status": v3["status"],
        },
        "mismatch_action": {
            "action": "FALLBACK_CLASSICAL",
            "fallback": "fresh_independent_KLT_export_with_constant_q1",
            "forbidden": "learned_bag_exact_drop_as_fallback",
            "result_label": "KLT_BACKEND_CONTRACT_FALLBACK",
            "counts_as_proposed_result": False,
        },
    }
    payload["contract_hash"] = payload_hash(payload)
    return payload


def write_json(path: Path, payload: dict[str, object]) -> None:
    if path.exists():
        raise FileExistsError(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f"{path.name}.partial.{os.getpid()}")
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    os.replace(temporary, path)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    payload = build_payload()
    write_json(args.output, payload)
    print(f"NATIVEQ_BACKEND_CONTRACT_FROZEN hash={payload['contract_hash']}")
    print(f"wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
