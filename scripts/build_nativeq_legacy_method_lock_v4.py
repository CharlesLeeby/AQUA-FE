#!/usr/bin/env python3
"""Build the additive guarded-execution lock over native-q candidate v3."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path

try:
    from scripts.build_nativeq_backend_contract import payload_hash, sha256
except ModuleNotFoundError:  # Direct `python3 scripts/...` execution.
    from build_nativeq_backend_contract import payload_hash, sha256


ROOT = Path(__file__).resolve().parents[1]
BUNDLE = ROOT / "papers/ieee_sensors_journal_experiments"
DEFAULT_OUTPUT = BUNDLE / "method_lock_nativeq_legacy_candidate_v4.json"
V3_LOCK = BUNDLE / "method_lock_nativeq_legacy_candidate_v3.json"
BACKEND_CONTRACT = BUNDLE / "backend_quality_contract_v1.json"
CORRECTION = BUNDLE / "2026-08-05--round3-ntnu-quality-partition-correction-v2.md"
ANALYSIS = BUNDLE / "ntnu_q_partition_20260805/analysis-output"


LOCAL_ARTIFACTS = (
    V3_LOCK,
    BACKEND_CONTRACT,
    CORRECTION,
    ANALYSIS / "analysis-report.md",
    ANALYSIS / "stats-appendix.md",
    ANALYSIS / "figure-catalog.md",
    ANALYSIS / "factorial-summary.csv",
    ANALYSIS / "replay-metrics.csv",
    ANALYSIS / "replay-input-manifest.csv",
    ANALYSIS / "lineage-audit.json",
    ANALYSIS / "bag-audit-summary.csv",
    ANALYSIS / "analysis-artifact-manifest.sha256",
    ANALYSIS / "input-manifest.sha256",
    ROOT / "scripts/build_nativeq_backend_contract.py",
    ROOT / "scripts/check_nativeq_backend_contract.py",
    ROOT / "scripts/attest_nativeq_feature_bag.py",
    ROOT / "scripts/run_isj_nativeq_contract_guarded_v4.sh",
    ROOT / "scripts/run_isj_classical_contract_fallback_v4.sh",
    ROOT / "scripts/build_nativeq_legacy_method_lock_v4.py",
    ROOT / "scripts/build_ntnu_q_partition_analysis.py",
    ROOT / "scripts/rewrite_quality_partition.py",
    ROOT / "scripts/audit_quality_partition.py",
    ROOT / "scripts/tests/test_nativeq_backend_contract_guard.py",
    ROOT / "scripts/tests/test_nativeq_method_lock_v4.py",
    ROOT / "scripts/tests/test_ntnu_q_partition_analysis.py",
    ROOT / "scripts/tests/test_quality_partition.py",
)

EXTERNAL_EVIDENCE = (
    Path(
        "/mnt/data/AQUA-FE_WS/validation_20260805/ntnu_s83_d30_q_partition_factorial/"
        "g0_all_replays_max350/common_support_summary.json"
    ),
    Path(
        "/mnt/data/AQUA-FE_WS/validation_20260805/ntnu_s83_d30_q_partition_factorial/"
        "g0_all_replays_max350/evo_crosscheck.json"
    ),
    Path(
        "/mnt/data/AQUA-FE_WS/validation_20260805/ntnu_s83_d30_q_partition_factorial/"
        "learned_baseq1_xfeatnative_audit.json"
    ),
    Path(
        "/mnt/data/AQUA-FE_WS/validation_20260805/ntnu_s83_d30_q_partition_factorial/"
        "learned_kltnative_gfttq1_xfeatnative_audit.json"
    ),
    Path(
        "/mnt/data/AQUA-FE_WS/validation_20260805/ntnu_s83_d30_q_partition_factorial/"
        "learned_kltq1_gfttnative_xfeatnative_audit.json"
    ),
    Path(
        "/mnt/data/AQUA-FE_WS/validation_20260805/nativeq_backend_guard/"
        "pass_decision.json"
    ),
    Path(
        "/mnt/data/AQUA-FE_WS/validation_20260805/nativeq_backend_guard/"
        "pass_reused_bag_decision.json"
    ),
    Path(
        "/mnt/data/AQUA-FE_WS/validation_20260805/nativeq_backend_guard/"
        "ntnu_nativeq_feature_bag_attestation.json"
    ),
)


def method_payload_hash(payload: dict[str, object]) -> str:
    clone = json.loads(json.dumps(payload, sort_keys=True))
    clone.pop("candidate_lock_hash", None)
    clone.pop("generated_at_utc", None)
    return hashlib.sha256(
        json.dumps(clone, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def record(path: Path, *, role: str) -> dict[str, object]:
    if not path.is_file():
        raise FileNotFoundError(path)
    try:
        label = str(path.relative_to(ROOT))
    except ValueError:
        label = str(path)
    return {
        "path": label,
        "role": role,
        "sha256": sha256(path),
        "size_bytes": path.stat().st_size,
    }


def build_payload() -> dict[str, object]:
    v3 = json.loads(V3_LOCK.read_text(encoding="utf-8"))
    backend = json.loads(BACKEND_CONTRACT.read_text(encoding="utf-8"))
    if method_payload_hash(v3) != v3.get("candidate_lock_hash"):
        raise ValueError("base candidate-v3 lock hash mismatch")
    if payload_hash(backend) != backend.get("contract_hash"):
        raise ValueError("backend quality contract hash mismatch")
    if v3.get("status") != "READY_FOR_P06_SCREENING":
        raise ValueError("base candidate-v3 is not ready")
    payload: dict[str, object] = {
        "schema_version": "isj-method-lock-nativeq-legacy-candidate-v4",
        "protocol_version": "isj-nativeq-legacy-candidate-v4-guarded-execution",
        "status": "GUARDED_EXECUTION_CANDIDATE",
        "route": "MULTI_SEQUENCE_CANDIDATE",
        "scientific_method_identity": "UNCHANGED_FROM_V3",
        "execution_entrypoint": "scripts/run_isj_nativeq_contract_guarded_v4.sh",
        "supersedes_for_execution": {
            **record(V3_LOCK, role="base_scientific_method_lock"),
            "candidate_lock_hash": v3["candidate_lock_hash"],
            "disposition": "preserved_unchanged; scientific frontend identity retained",
        },
        "backend_quality_consumer_contract": {
            **record(BACKEND_CONTRACT, role="frozen_backend_consumer_contract"),
            "contract_hash": backend["contract_hash"],
            "consumer_id": backend["consumer_id"],
        },
        "guard_policy": {
            "allow_action": "ALLOW_LEARNED",
            "mismatch_action": "FALLBACK_CLASSICAL",
            "fallback_result_label": "KLT_BACKEND_CONTRACT_FALLBACK",
            "fallback_is_fresh_independent_klt_export": True,
            "learned_exact_drop_as_fallback_forbidden": True,
            "fallback_counts_as_proposed_result": False,
            "reused_bag_requires_hash_bound_attestation": True,
            "backend_binary_and_semantic_source_hashes_required": True,
            "runtime_mapping_must_equal": {
                "mode": "vins_safe",
                "floor": 0.8,
                "alpha": 0.65,
                "all_source_scales": 1.0,
                "constant_quality": False,
                "raw_quality": False,
            },
        },
        "development_counterexample_resolution": {
            "scientific_units": 1,
            "technical_replays_per_arm": 3,
            "matched_max_cnt": 350,
            "common_poses": 285,
            "common_rpe_pairs": 275,
            "native_rpe_median_m": 0.04894295154630014,
            "source1_q1_rpe_median_m": 0.06633626508120992,
            "gftt_birth_q1_rpe_median_m": 0.12740790773785912,
            "gftt_birth_q1_rpe_max_m": 33.39471961075973,
            "classical_q1_xfeat_native_rpe_median_m": 10.318417502716205,
            "global_q1_identical_vio_sha256": (
                "86cf4eb0997b1d4e2bc2d766676ba154a7981bc340106a776686df63ff636ffe"
            ),
            "allowed_interpretation": (
                "classical birth/propagation quality x VINS consumer interaction "
                "under fixed learned-active geometry"
            ),
            "learned_superiority_claim": "FORBIDDEN_PENDING_HELD_OUT_MATRIX",
        },
        "artifacts": [record(path, role="guarded_v4_artifact") for path in LOCAL_ARTIFACTS],
        "external_development_evidence": [
            record(path, role="development_only_external_evidence")
            for path in EXTERNAL_EVIDENCE
        ],
        "blockers": [
            "Held-out multi-sequence proposed/KLT/modern-baseline matrix is pending",
            "Online independent C_legacy formal attribution remains pending",
            "This v4 guard does not promote NTNU development evidence into confirmation",
        ],
    }
    payload["candidate_lock_hash"] = method_payload_hash(payload)
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
    print(
        "NATIVEQ_METHOD_LOCK_V4_OK "
        f"status={payload['status']} candidate_hash={payload['candidate_lock_hash']}"
    )
    print(f"wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
