#!/usr/bin/env python3
"""Build the non-QG native-q method-lock candidate without rewriting P03 v1."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
BUNDLE = ROOT / "papers/ieee_sensors_journal_experiments"
DEFAULT_OUTPUT = BUNDLE / "method_lock_nativeq_legacy_candidate_v2.json"
VINS_ROOT = Path("/home/ma/SLAM/VINS-Fusion-origin/src/VINS-Fusion-master")
VINS_BINARY = Path("/home/ma/SLAM/VINS-Fusion-origin/devel/lib/vins/vins_node")
P05_AUDIT = BUNDLE / "p05/fairness_audit.json"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    args = parser.parse_args()
    payload = build_payload()
    validate_payload(payload)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print(
        f"NATIVEQ_METHOD_LOCK_OK status={payload['status']} "
        f"artifacts={len(payload['artifacts'])} missing={len(payload['missing_artifacts'])} "
        f"candidate_hash={payload['candidate_lock_hash']}"
    )
    print(f"wrote {output}")
    return 0


def build_payload() -> dict[str, object]:
    config_entrypoints = [
        ROOT / "uw_frontend/configs/experiments/low_texture_xfeat_seedchain_frontend.yaml",
        ROOT / "uw_frontend/configs/experiments/isj_p05_xfeat_pairwise_nativeq.yaml",
    ]
    config_paths: set[Path] = set()
    for entrypoint in config_entrypoints:
        config_paths.update(config_chain(entrypoint))

    local_paths = [
        "papers/ieee_sensors_journal_experiments/p02/p02_freeze_hashes.sha256",
        "papers/ieee_sensors_journal_experiments/data_eligibility_manifest.csv",
        "papers/ieee_sensors_journal_experiments/history_exclusion_manifest.csv",
        "papers/ieee_sensors_journal_experiments/window_selection_protocol.md",
        "papers/ieee_sensors_journal_experiments/evaluator_protocol_v1.md",
        "papers/ieee_sensors_journal_experiments/failure_taxonomy_v1.yaml",
        "papers/ieee_sensors_journal_experiments/environment_manifest.txt",
        "papers/ieee_sensors_journal_experiments/2026-08-04--learned-specificity--r03--ntnu-quality-contract.md",
        "papers/ieee_sensors_journal_experiments/learned_specificity_20260803/analysis-output/analysis-report.md",
        "papers/ieee_sensors_journal_experiments/learned_specificity_20260803/analysis-output/stats-appendix.md",
        "papers/ieee_sensors_journal_experiments/learned_specificity_20260803/analysis-output/figure-catalog.md",
        "papers/ieee_sensors_journal_experiments/learned_specificity_20260803/analysis-output/ntnu-replay-summary.csv",
        "papers/ieee_sensors_journal_experiments/learned_specificity_20260803/analysis-output/ntnu-prefix-summary.csv",
        "papers/ieee_sensors_journal_experiments/learned_specificity_20260803/round3_ntnu_sha256_manifest.txt",
        "papers/ieee_sensors_journal_experiments/p05/learned_baseline_fairness.md",
        "papers/ieee_sensors_journal_experiments/p05/fairness_audit.csv",
        "papers/ieee_sensors_journal_experiments/p05/fairness_audit.json",
        "scripts/run_isj_nativeq_legacy_candidate.sh",
        "scripts/run_xfeat_seedchain_arbitrated_eval.sh",
        "scripts/run_learned_seedchain_eval.sh",
        "scripts/learned_seedchain_env.sh",
        "scripts/run_p05_modern_xfeat_baseline.sh",
        "scripts/audit_p05_modern_xfeat.py",
        "scripts/build_nativeq_legacy_method_lock.py",
        "scripts/run_aqualoc_archaeo_vins_eval.sh",
        "scripts/run_aqualoc_real_vins_eval.sh",
        "scripts/run_ntnu_vins_eval.sh",
        "scripts/run_afrl_cave_vins_eval.sh",
        "scripts/evaluate_vins_common_support.py",
        "scripts/summarize_g0_common_support.py",
        "scripts/p02_window_selection.py",
        "scripts/tests/test_p05_nativeq_contract.py",
        "uw_frontend/ros/export_vins_features.py",
        "uw_frontend/tracking/hybrid_tracker.py",
        "uw_frontend/tracking/klt_tracker.py",
        "uw_frontend/tracking/pairwise_matcher_tracker.py",
        "uw_frontend/matchers/xfeat_adapter.py",
        "uw_frontend/evaluation/run_frontend_eval.py",
        "external_tools/accelerated_features/modules/xfeat.py",
        "external_tools/accelerated_features/weights/xfeat.pt",
        "external_tools/accelerated_features/LICENSE",
        "external_tools/accelerated_features/README.md",
    ]
    local_paths.extend(str(path.relative_to(ROOT)) for path in sorted(config_paths))
    artifacts = [file_record(path) for path in sorted(set(local_paths))]

    external_evidence_paths = [
        "/mnt/data/AQUA-FE_WS/validation_20260804/ntnu_fjord1_s83_d30_common_support_nativeq_constq_xfeatq1_all/common_support_summary.json",
        "/mnt/data/AQUA-FE_WS/validation_20260804/ntnu_s83_d30_contract/nativeq_reconstruction_audit.json",
        "/mnt/data/AQUA-FE_WS/validation_20260804/ntnu_fjord1_s83_d30_nativeq_retrospective_gftt_same_id.bag",
        "/mnt/data/AQUA-FE_WS/validation_20260804/ntnu_fjord1_s83_d30_nativeq_exact_drop.bag",
        "/mnt/data/AQUA-FE_WS/validation_20260804/ntnu_fjord1_s83_d30_nativeq_xfeat_q1.bag",
    ]
    external_evidence = [file_record(path, absolute=True, role="development_evidence") for path in external_evidence_paths]
    local_evidence_paths = [
        "logs/ntnu_vins/external_hybrid_xfeat_every2_validation_20260804_ntnu_fjord1_s83_d30_xfeat_historical_profile_nativeq/features.bag",
        "logs/ntnu_vins/external_klt_every2_validation_20260804_ntnu_fjord1_s83_d30_klt_nativeq/features.bag",
    ]
    development_evidence = [file_record(path, role="development_evidence") for path in local_evidence_paths]
    development_evidence.extend(external_evidence)

    old_candidate = file_record(
        "papers/ieee_sensors_journal_experiments/method_lock_candidate.json",
        role="retired_qg_candidate",
    )
    p05_status = read_p05_status()
    missing = [
        str(record["path"])
        for record in artifacts + development_evidence + [old_candidate]
        if record["status"] != "PRESENT"
    ]
    blockers = []
    if p05_status != "PASS":
        blockers.append("P05 controlled XFeat fairness/determinism audit has not passed")
    blockers.append("P06 development equivalence probes and outcome-blind window screening are pending")

    payload: dict[str, object] = {
        "schema_version": "isj-method-lock-nativeq-legacy-candidate-v2",
        "protocol_version": "isj-nativeq-legacy-candidate-v2",
        "status": (
            "READY_FOR_P06_DEVELOPMENT_PROBES"
            if p05_status == "PASS" and not missing
            else "CANDIDATE_INCOMPLETE"
        ),
        "route": "MULTI_SEQUENCE_CANDIDATE",
        "generated_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "supersedes_for_headline_only": {
            "path": old_candidate["path"],
            "sha256": old_candidate["sha256"],
            "disposition": "retained_unchanged_as_failed_qg_development_candidate",
        },
        "method_identity": {
            "name": "AQUA-FE native-q learned-seeded legacy candidate",
            "profile": "isj-nativeq-xfeat-seedchain-legacy-v2",
            "entrypoint": "scripts/run_isj_nativeq_legacy_candidate.sh",
            "selector": "frozen_lineage_early_seed_scan_arbitration",
            "proposal": "official_XFeat_sparse_matches",
            "admission": "LK/KLT_probation_then_frozen_microburst_or_safe_fallback",
            "qg_selector": "NOT_APPLICABLE_RETIRED",
            "development_only_identity_event": "NTNU_fjord1_s83_d30",
        },
        "arms": {
            "B0_native_vins_origin_v1": {
                "role": "native_vins_reference",
                "status": "RUNNABLE",
                "quality_contract": "native_vins",
            },
            "B1_klt_nativeq_v2": {
                "role": "primary_classical_external_feature_baseline",
                "status": "RUNNABLE",
                "quality_contract": "vins_safe_floor0p80_alpha0p65",
            },
            "P_legacy_nativeq_xfeat_seedchain_v2": {
                "role": "proposed_gated_persistent_measurement_frontend",
                "status": "DEVELOPMENT_LOCK_CANDIDATE",
                "quality_contract": "vins_safe_floor0p80_alpha0p65",
            },
            "M_xfeat_pairwise_nativeq_v1": {
                "role": "controlled_same_backend_modern_learned_baseline",
                "status": "P05_PASS" if p05_status == "PASS" else "P05_PENDING",
                "quality_contract": "vins_safe_floor0p80_alpha0p65",
                "entrypoint": "scripts/run_p05_modern_xfeat_baseline.sh",
            },
            "D_legacy_exact_lineage_drop_v2": {
                "role": "conditional_whole_lineage_drop",
                "status": "RESERVED_CONDITIONAL_ON_PROPOSED_ACTIVE",
            },
            "C_legacy_independent_classical_v2": {
                "role": "conditional_independent_classical_proposer_attribution",
                "status": "RESERVED_CONDITIONAL_ON_PROPOSED_ACTIVE",
                "development_retrospective_controls_are_not_online_causal_controls": True,
            },
        },
        "shared_contract": {
            "preprocess": "adaptive_clahe",
            "maximum_feature_budget": 350,
            "dose_matching": "same_maximum_budget_not_equal_realized_count",
            "backend_quality_mode": "vins_safe",
            "backend_quality_floor": 0.80,
            "backend_quality_alpha": 0.65,
            "global_constant_q_main_matrix": False,
            "sampling": {
                "aqualoc_archaeology": {"every_n": 2, "frame_offset": 1},
                "aqualoc_harbor": {"every_n": 2, "frame_offset": 1},
                "ntnu": {"every_n": 2, "frame_offset": 1},
                "afrl": {"every_n": 2, "frame_offset": 0},
            },
            "replay": "serial_single_thread_three_replays",
            "replay_reducer": "median_of_at_least_2_of_3; any_of_3_hard_and_solver_risk",
            "primary_metric": "G0_common_support_1s_translation_RPE_RMSE",
            "scientific_unit": "sequence_not_replay",
        },
        "p05_status": p05_status,
        "artifacts": artifacts,
        "development_evidence": development_evidence,
        "vins_source": vins_source_record(),
        "vins_binary": file_record(str(VINS_BINARY), absolute=True, role="vins_binary"),
        "xfeat_upstream": {
            "repository": "https://github.com/verlab/accelerated_features.git",
            "git_commit": git_output(Path("external_tools/accelerated_features"), "rev-parse", "HEAD"),
            "license": "Apache-2.0",
            "local_worktree_note": "tracked content matches recorded hashes; repository mode bits differ locally",
        },
        "missing_artifacts": sorted(set(missing)),
        "blockers": blockers,
    }
    payload["candidate_lock_hash"] = payload_hash(payload)
    return payload


def validate_payload(payload: dict[str, object]) -> None:
    shared = payload["shared_contract"]
    if shared["maximum_feature_budget"] != 350:
        raise ValueError("feature budget drift")
    if shared["backend_quality_mode"] != "vins_safe":
        raise ValueError("native reliability contract drift")
    if shared["global_constant_q_main_matrix"] is not False:
        raise ValueError("global constant q cannot enter the main matrix")
    for record in payload["artifacts"]:
        if record["status"] == "PRESENT":
            target = ROOT / str(record["path"])
            if sha256_file(target) != record["sha256"]:
                raise ValueError(f"artifact hash changed: {record['path']}")
    if payload_hash(payload) != payload["candidate_lock_hash"]:
        raise ValueError("candidate lock hash mismatch")


def config_chain(path: Path) -> list[Path]:
    path = path.resolve()
    if not path.is_file():
        return [path]
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    parent = data.get("extends")
    if not parent:
        return [path]
    parent_path = (path.parent / str(parent)).resolve()
    return config_chain(parent_path) + [path]


def read_p05_status() -> str:
    if not P05_AUDIT.is_file():
        return "NOT_RUN"
    try:
        return str(json.loads(P05_AUDIT.read_text(encoding="utf-8")).get("status", "INVALID"))
    except (OSError, json.JSONDecodeError):
        return "INVALID"


def file_record(path: str, *, absolute: bool = False, role: str = "source_or_config") -> dict[str, object]:
    target = Path(path) if absolute else ROOT / path
    record: dict[str, object] = {"path": str(path), "role": role}
    if not target.is_file():
        record.update({"status": "MISSING", "sha256": None, "size_bytes": None})
        return record
    record.update(
        {
            "status": "PRESENT",
            "sha256": sha256_file(target),
            "size_bytes": target.stat().st_size,
        }
    )
    return record


def vins_source_record() -> dict[str, object]:
    record: dict[str, object] = {"root": str(VINS_ROOT), "status": "MISSING"}
    if not VINS_ROOT.is_dir():
        return record
    pairs = []
    for path in sorted(item for item in VINS_ROOT.rglob("*") if item.is_file()):
        pairs.append(f"{sha256_file(path)}  {path.relative_to(VINS_ROOT).as_posix()}\n")
    record.update(
        {
            "status": "PRESENT",
            "file_count": len(pairs),
            "tree_sha256": hashlib.sha256("".join(pairs).encode("utf-8")).hexdigest(),
            "git_commit": git_output(VINS_ROOT, "rev-parse", "HEAD"),
        }
    )
    return record


def git_output(path: Path, *args: str) -> str | None:
    try:
        return subprocess.check_output(
            ["git", "-C", str(path), *args],
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def payload_hash(payload: dict[str, object]) -> str:
    clone = json.loads(json.dumps(payload, sort_keys=True))
    clone.pop("candidate_lock_hash", None)
    clone.pop("generated_at_utc", None)
    return hashlib.sha256(
        json.dumps(clone, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


if __name__ == "__main__":
    raise SystemExit(main())
