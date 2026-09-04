#!/usr/bin/env python3
"""Freeze the additive B1 contract for the proven current exporter bytes."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
from typing import Iterable

try:
    from scripts import check_b1_klt_nativeq_current_exporter_contract_v2 as checker
    from scripts import prove_b1_klt_exporter_transition_v2 as transition
except ImportError:
    import check_b1_klt_nativeq_current_exporter_contract_v2 as checker  # type: ignore
    import prove_b1_klt_exporter_transition_v2 as transition  # type: ignore


ROOT = Path(__file__).resolve().parents[1]
BUNDLE = ROOT / "papers/ieee_sensors_journal_experiments"
DEFAULT_OUTPUT = BUNDLE / "backend_quality_contract_b1_current_exporter_v2.json"
BASE_CONTRACT = BUNDLE / "backend_quality_contract_v1.json"
PROOF = BUNDLE / "b1_klt_exporter_7ed_to_567_transition_proof_v2.json"
VINS_ROOT = Path("/home/ma/SLAM/VINS-Fusion-origin/src/VINS-Fusion-master")
VINS_NODE = Path("/home/ma/SLAM/VINS-Fusion-origin/devel/lib/vins/vins_node")
VINS_LIB = Path("/home/ma/SLAM/VINS-Fusion-origin/devel/lib/libvins_lib.so")
CAMERA_LIB = Path("/home/ma/SLAM/VINS-Fusion-origin/devel/lib/libcamera_models.so")


class BuildError(RuntimeError):
    pass


def record(path: Path) -> dict[str, object]:
    if path.is_symlink() or not path.is_file():
        raise BuildError(f"MISSING_OR_NOT_REGULAR:{path}")
    return {
        "path": str(path.resolve()),
        "size_bytes": path.stat().st_size,
        "sha256": checker.sha256_file(path),
    }


def algorithm_settings() -> dict[str, object]:
    settings: dict[str, object] = {
        "scope": "A02_CAMERA_GLOBAL_4500_6300_INCLUSIVE",
        "method": "klt",
        "every_n": 2,
        "frame_offset": 1,
        "preprocess": "adaptive_clahe",
        "process_skipped_frames": True,
        "measurement_selection": False,
        "formal_three_layer_export": False,
        "vins_safe_source_selection": False,
        "export_max_features": 350,
        "semidense_fallback_method": "none",
        "backend_quality_mode": "vins_safe",
        "backend_quality_floor": 0.80,
        "backend_quality_alpha": 0.65,
        "raw_quality_to_backend": False,
        "constant_quality_to_backend": False,
        "learned_source_quality_scales": {
            "learned": 1.0,
            "sp_lg": 1.0,
            "xfeat": 1.0,
            "loftr": 1.0,
        },
        "run_vins_during_export": False,
        "force_raw": False,
        "force_export": False,
        "single_thread_backend_setting": True,
    }
    settings["settings_sha256"] = hashlib.sha256(
        json.dumps(settings, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return settings


def build_payload() -> dict[str, object]:
    proof = transition.build_proof()
    if PROOF.read_bytes() != transition.render(proof):
        raise BuildError("TRANSITION_PROOF_NOT_CANONICAL")
    base = json.loads(BASE_CONTRACT.read_text(encoding="utf-8"))
    if not isinstance(base, dict) or checker.payload_hash(base) != base.get("contract_hash"):
        raise BuildError("BASE_CONTRACT_HASH_INVALID")
    mapper = base.get("frontend_mapper")
    old_exporter = mapper.get("exporter") if isinstance(mapper, dict) else None
    if not isinstance(old_exporter, dict) or (
        old_exporter.get("sha256") != transition.OLD_SHA256
        or old_exporter.get("size_bytes") != transition.OLD_SIZE
    ):
        raise BuildError("BASE_CONTRACT_EXPORTER_NOT_7ED")

    consumer_records = base.get("consumer_files")
    if not isinstance(consumer_records, list):
        raise BuildError("BASE_CONSUMER_RECORDS_INVALID")
    for item in consumer_records:
        if not isinstance(item, dict) or not isinstance(item.get("path"), str):
            raise BuildError("BASE_CONSUMER_RECORD_INVALID")
        actual = record(VINS_ROOT / str(item["path"]))
        if actual["sha256"] != item.get("sha256") or actual["size_bytes"] != item.get("size_bytes"):
            raise BuildError(f"BASE_CONSUMER_DRIFT:{item['path']}")

    records = {
        "base_contract_v1": record(BASE_CONTRACT),
        "transition_proof": record(PROOF),
        "transition_prover": record(ROOT / "scripts/prove_b1_klt_exporter_transition_v2.py"),
        "contract_builder": record(Path(__file__).resolve()),
        "contract_checker": record(ROOT / "scripts/check_b1_klt_nativeq_current_exporter_contract_v2.py"),
        "guard_wrapper": record(ROOT / "scripts/run_a02_b1_klt_nativeq_current_exporter_guarded_v2.sh"),
        "current_exporter": record(transition.EXPORTER),
        "frontend_config": record(
            ROOT / "uw_frontend/configs/experiments/low_texture_xfeat_seedchain_frontend.yaml"
        ),
        "original_a02_runner": record(ROOT / "scripts/run_aqualoc_archaeo_vins_eval.sh"),
        "canonical_window_materializer": record(
            ROOT / "scripts/materialize_aqualoc_a02_4500_6300_window_v1.py"
        ),
        "data_eligibility_manifest": record(BUNDLE / "data_eligibility_manifest.csv"),
        "legacy_contract_builder": record(ROOT / "scripts/build_nativeq_backend_contract.py"),
        "legacy_b1_checker": record(ROOT / "scripts/check_b1_klt_nativeq_contract_v1.py"),
        "legacy_b1_wrapper": record(ROOT / "scripts/run_isj_b1_klt_nativeq_guarded_v1.sh"),
        "vins_node": record(VINS_NODE),
    }
    if records["current_exporter"]["sha256"] != transition.CURRENT_SHA256:
        raise BuildError("CURRENT_EXPORTER_NOT_567")

    payload: dict[str, object] = {
        "schema_version": "aqua-fe-b1-klt-nativeq-current-exporter-contract-v2",
        "status": "FROZEN_POST_STOP_B1_CURRENT_EXPORTER_CONTRACT",
        "scope": "B1_KLT_NATIVEQ_A02_4500_6300_EXPORT_COMPATIBILITY_ONLY",
        "base_contract_hash": base["contract_hash"],
        "records": records,
        "consumer_files": consumer_records,
        "vins_ldd_core": {
            "libvins_lib.so": record(VINS_LIB),
            "libcamera_models.so": record(CAMERA_LIB),
        },
        "algorithm_settings": algorithm_settings(),
        "transition_claim": {
            "old_exporter_sha256": transition.OLD_SHA256,
            "current_exporter_sha256": transition.CURRENT_SHA256,
            "exact_patch_count": 4,
            "klt_factory_ast_equal": True,
            "vins_pointcloud_payload_ast_equal": True,
            "allowed_delta": "DL_VINS_PAIRWISE_CAMERA_AND_METRICS_ONLY",
        },
        "execution_governance": {
            "wrapper_api": "aqualoc_archaeology A02 4500 6300 2",
            "underlying_runner_argv": [
                "bash",
                str((ROOT / "scripts/run_aqualoc_archaeo_vins_eval.sh").resolve()),
                "external",
                "2",
                "4500",
                "6300",
                "klt",
                "2",
            ],
            "decision_directory": str(
                (ROOT / "logs/backend_contract_decisions/b1/"
                 "litcmp_a02_4500_6300_preroll_b1_native_r1").resolve()
            ),
            "decision_filename": "b1_current_exporter_v2_decision.json",
            "decision_directory_exclusive_create": True,
            "decision_file_exclusive_create": True,
            "output_run_directory_must_not_exist": True,
            "force_export": False,
            "retry_count": 0,
        },
        "scientific_boundary": {
            "proves": "B1 KLT source/payload-path compatibility under current exporter bytes",
            "does_not_prove": [
                "trajectory usability",
                "accuracy",
                "learned-frontend benefit",
                "published-method equivalence",
            ],
        },
    }
    payload["contract_hash"] = checker.payload_hash(payload)
    return payload


def write_exclusive(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = (json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n").encode(
        "utf-8"
    )
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o444)
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args(argv)
    payload = build_payload()
    write_exclusive(args.output, payload)
    print(f"B1_CURRENT_EXPORTER_CONTRACT_FROZEN hash={payload['contract_hash']}")
    print(f"wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
