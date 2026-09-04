#!/usr/bin/env python3
"""Build and validate the P03 candidate method lock without running experiments."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BUNDLE = ROOT / "papers/ieee_sensors_journal_experiments"
DEFAULT_OUTPUT = BUNDLE / "method_lock_candidate.json"
VINS_ROOT = Path("/home/ma/SLAM/VINS-Fusion-origin/src/VINS-Fusion-master")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    args = parser.parse_args()
    payload = build_payload()
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(payload, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    validate_payload(payload)
    print(
        f"P03_METHOD_LOCK_OK artifacts={len(payload['artifacts'])} "
        f"missing={len(payload['missing_artifacts'])} "
        f"candidate_hash={payload['candidate_lock_hash']}"
    )
    print(f"wrote {output}")
    return 0


def build_payload() -> dict[str, object]:
    artifact_paths = [
        "papers/ieee_sensors_journal_experiments/p02/p02_freeze_hashes.sha256",
        "papers/ieee_sensors_journal_experiments/window_selection_protocol.md",
        "papers/ieee_sensors_journal_experiments/evaluator_protocol_v1.md",
        "papers/ieee_sensors_journal_experiments/protocol_v1_candidate.md",
        "papers/ieee_sensors_journal_experiments/failure_taxonomy_v1.yaml",
        "papers/ieee_sensors_journal_experiments/environment_manifest.txt",
        "uw_frontend/configs/klt_frontend.yaml",
        "uw_frontend/configs/experiments/low_texture_xfeat_seedchain_frontend.yaml",
        "uw_frontend/configs/isj_p03_core_method_candidate.yaml",
        "uw_frontend/tracking/klt_tracker.py",
        "uw_frontend/tracking/classical_proposer.py",
        "uw_frontend/matchers/xfeat_adapter.py",
        "uw_frontend/geometry/master_candidate_stream.py",
        "uw_frontend/geometry/fh_residuals.py",
        "uw_frontend/geometry/marginal_support.py",
        "uw_frontend/geometry/shadow_rankings.py",
        "uw_frontend/quality/temporal_reliability.py",
        "uw_frontend/evaluation/failure_classifier.py",
        "uw_frontend/evaluation/run_frontend_eval.py",
        "scripts/export_p03_master_stream.py",
        "scripts/replay_p03_shadow.py",
        "scripts/selector_shadow_compare.py",
        "scripts/run_aqualoc_archaeo_vins_eval.sh",
        "scripts/run_aqualoc_real_vins_eval.sh",
        "scripts/run_ntnu_vins_eval.sh",
        "scripts/run_afrl_cave_vins_eval.sh",
        "scripts/p02_window_selection.py",
        "scripts/validate_p02_bundle.py",
        "scripts/classify_isj_replay.py",
        "scripts/build_p03_method_lock.py",
        "scripts/tests/test_failure_classifier.py",
        "scripts/tests/test_master_candidate_stream.py",
        "scripts/tests/test_fh_residuals.py",
        "scripts/tests/test_classical_proposer.py",
        "scripts/tests/test_temporal_reliability.py",
    ]
    artifacts = [_file_record(path) for path in artifact_paths]
    missing = [record["path"] for record in artifacts if record["status"] != "PRESENT"]
    weight_path = "external_tools/accelerated_features/weights/xfeat.pt"
    artifacts.append(_file_record(weight_path, role="model_weight"))
    if not Path(weight_path).exists():
        missing.append(weight_path)

    source_record = _vins_source_record()
    binary_record = _file_record(
        "/home/ma/SLAM/VINS-Fusion-origin/devel/lib/vins/vins_node",
        role="vins_binary",
        absolute=True,
    )
    if binary_record["status"] != "PRESENT":
        missing.append(binary_record["path"])

    smoke_records = []
    for path in (
        "papers/ieee_sensors_journal_experiments/p03/smoke_a06_v2/master_stream.jsonl",
        "papers/ieee_sensors_journal_experiments/p03/smoke_a06_v2/calibration_rows.csv",
        "papers/ieee_sensors_journal_experiments/p03/smoke_a06_learned_v3/master_stream.jsonl",
        "papers/ieee_sensors_journal_experiments/p03/smoke_a06_learned_v3/calibration_rows.csv",
        "papers/ieee_sensors_journal_experiments/p03/smoke_a06_learned_v3/shadow_rankings.csv",
    ):
        record = _file_record(path, role="development_smoke_artifact")
        smoke_records.append(record)
        if record["status"] != "PRESENT":
            missing.append(path)

    payload: dict[str, object] = {
        "schema_version": "isj-method-lock-candidate-v1",
        "status": "P03_CANDIDATE_NOT_CANONICAL",
        "protocol_version": "isj-core-method-candidate-v1",
        "route": "MULTI_SEQUENCE_CANDIDATE",
        "generated_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "artifacts": artifacts,
        "vins_source": source_record,
        "vins_binary": binary_record,
        "development_smoke_artifacts": smoke_records,
        "arms": {
            "B0_native_vins_origin_v1": {
                "role": "native_vins_reference",
                "status": "RUNNABLE_CANDIDATE",
                "q_backend": "native",
                "selector": "native_vins",
            },
            "B1_klt_adaptive_clahe_v1": {
                "role": "primary_classical_baseline",
                "status": "RUNNABLE_CANDIDATE",
                "q_backend": 1.0,
                "selector": "none",
                "p02_hash_manifest": "papers/ieee_sensors_journal_experiments/p02/b1_screening_code_hashes.sha256",
            },
            "B2_xfeat_all_eligible_v1": {
                "role": "ungated_learned_seed_ablation",
                "status": "EXPORT_PRODUCER_CANDIDATE_NOT_CANONICAL",
                "q_backend": 1.0,
                "selector": "all_eligible",
            },
            "H_confirmatory_xfeat_distance_grid_v1": {
                "role": "heuristic_selector_control",
                "status": "SHADOW_READY_EXPORT_NOT_READY",
                "q_backend": 1.0,
                "selector": "distance_grid",
            },
            "P_qg_reserved_p03b": {
                "role": "proposed_calibrated_marginal_support",
                "status": "SHADOW_READY_EXPORT_NOT_READY",
                "q_backend": 1.0,
                "selector": "qg_marginal_support",
            },
            "D_from_P_whole_lineage_v1": {
                "role": "whole_lineage_drop",
                "status": "RESERVED_CONDITIONAL_ON_P_ACTIVE",
                "q_backend": 1.0,
                "selector": "derived_from_stable_p_bag",
            },
            "C-QG_gftt_qg_matched_v1": {
                "role": "independent_classical_matched_dose_control",
                "status": "PROPOSER_READY_MATCHING_NOT_IMPLEMENTED",
                "q_backend": 1.0,
                "selector": "same_qg_on_independent_pool",
            },
            "M_xfeat_direct_same_backend_v1": {
                "role": "modern_same_backend_reference",
                "status": "RESERVED_P05",
                "q_backend": 1.0,
                "selector": "direct_or_periodic_xfeat",
            },
        },
        "shared_contract": {
            "master_stream_schema": "isj-master-candidate-stream-v1",
            "master_pool_hash_pairing": "H/P must match frame by frame",
            "b_active": 8,
            "total_feature_cap": 350,
            "base_export_cap": 342,
            "backend_q_external_arms": 1.0,
            "fh_seed": 20260730,
            "fh_thresholds_px": {"F": 2.5, "H": 5.0},
            "reliability_horizon_frames": 5,
            "reliability_alpha": 0.10,
            "selector_min_gain": 0.001,
            "selector_random_seed": 20260730,
            "replay_reducer": "median_of_at_least_2_of_3; any_of_3_hard_and_solver_risk",
        },
        "calibration": {
            "status": "PROVISIONAL_DEVELOPMENT_ONLY",
            "model_path": None,
            "row_schema": "isj-temporal-reliability-model-v1",
            "required_source_groups": ["klt", "learned", "classical"],
            "smoke_rows_are_not_frozen": True,
        },
        "environment": {
            "manifest": "papers/ieee_sensors_journal_experiments/environment_manifest.txt",
            "torch_cuda_available": False,
            "real_time_claim_authorized": False,
        },
        "missing_artifacts": sorted(set(missing)),
        "blockers": [
            "canonical VINS exporter integration and H/P selector-only bag probe are pending",
            "pooled reliability calibration split/subgroup gates are not frozen",
            "CPU-only shadow selection P95 exceeds the 1 ms P03B gate",
            "C-QG matched-dose implementation is pending",
        ],
    }
    payload["candidate_lock_hash"] = _payload_hash(payload)
    return payload


def validate_payload(payload: dict[str, object]) -> None:
    if payload.get("schema_version") != "isj-method-lock-candidate-v1":
        raise ValueError("method lock schema mismatch")
    for record in payload.get("artifacts", []):
        if record["status"] == "PRESENT":
            path = ROOT / record["path"]
            if not path.exists() or _sha256_file(path) != record["sha256"]:
                raise ValueError(f"artifact hash changed: {record['path']}")
    if payload["shared_contract"]["b_active"] != 8:
        raise ValueError("B_active drift")
    if payload["shared_contract"]["total_feature_cap"] != 350:
        raise ValueError("total feature cap drift")
    if payload["shared_contract"]["backend_q_external_arms"] != 1.0:
        raise ValueError("external backend q drift")


def _file_record(path: str, *, role: str = "source_or_config", absolute: bool = False) -> dict[str, object]:
    target = Path(path) if absolute else ROOT / path
    record: dict[str, object] = {"path": str(path), "role": role}
    if not target.exists() or not target.is_file():
        record["status"] = "MISSING"
        record["sha256"] = None
        record["size_bytes"] = None
        return record
    record["status"] = "PRESENT"
    record["sha256"] = _sha256_file(target)
    record["size_bytes"] = target.stat().st_size
    return record


def _vins_source_record() -> dict[str, object]:
    record: dict[str, object] = {
        "root": str(VINS_ROOT),
        "git_head": _git_head(VINS_ROOT),
        "tree_sha256": None,
        "status": "MISSING",
    }
    if not VINS_ROOT.exists():
        return record
    pairs: list[bytes] = []
    for path in sorted(p for p in VINS_ROOT.rglob("*") if p.is_file()):
        digest = _sha256_file(path)
        pairs.append(f"{digest}  {path.relative_to(VINS_ROOT).as_posix()}\n".encode("utf-8"))
    record["tree_sha256"] = hashlib.sha256(b"".join(pairs)).hexdigest()
    record["status"] = "PRESENT"
    record["file_count"] = len(pairs)
    try:
        record["git_commit"] = subprocess.check_output(
            ["git", "-C", str(VINS_ROOT), "rev-parse", "HEAD"],
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        record["git_commit"] = None
    return record


def _git_head(path: Path) -> str | None:
    head = path / ".git" / "HEAD"
    if not head.exists():
        return None
    text = head.read_text(encoding="utf-8", errors="replace").strip()
    return text


def _payload_hash(payload: dict[str, object]) -> str:
    clone = json.loads(json.dumps(payload, sort_keys=True))
    clone.pop("candidate_lock_hash", None)
    return hashlib.sha256(
        json.dumps(clone, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


if __name__ == "__main__":
    raise SystemExit(main())
