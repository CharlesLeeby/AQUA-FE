#!/usr/bin/env python3
"""Strict-keyset B1 guard for the additive current-exporter v3 contract."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Iterable

try:
    from scripts import check_b1_klt_nativeq_current_exporter_contract_v2 as common
    from scripts import prove_b1_klt_exporter_transition_v2 as transition
except ImportError:
    import check_b1_klt_nativeq_current_exporter_contract_v2 as common  # type: ignore
    import prove_b1_klt_exporter_transition_v2 as transition  # type: ignore


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONTRACT = ROOT / (
    "papers/ieee_sensors_journal_experiments/"
    "backend_quality_contract_b1_current_exporter_v3.json"
)
BACKEND_ROOT = Path("/home/ma/SLAM/VINS-Fusion-origin/src/VINS-Fusion-master")
REQUIRED_RECORD_KEYS = frozenset(
    {
        "base_contract_v1",
        "transition_proof",
        "transition_prover",
        "contract_builder",
        "contract_checker",
        "guard_wrapper",
        "current_exporter",
        "frontend_config",
        "original_a02_runner",
        "canonical_window_materializer",
        "data_eligibility_manifest",
        "legacy_contract_builder",
        "legacy_b1_checker",
        "legacy_b1_wrapper",
        "vins_node",
    }
)
REQUIRED_LDD_KEYS = frozenset({"libvins_lib.so", "libcamera_models.so"})
EXPECTED_CLAIM = {
    "old_exporter_sha256": transition.OLD_SHA256,
    "current_exporter_sha256": transition.CURRENT_SHA256,
    "exact_patch_count": 4,
    "klt_factory_ast_equal": True,
    "vins_pointcloud_payload_ast_equal": True,
    "allowed_delta": "DL_VINS_PAIRWISE_CAMERA_AND_METRICS_ONLY",
}
EXPECTED_BASE_CONTRACT = ROOT / (
    "papers/ieee_sensors_journal_experiments/backend_quality_contract_v1.json"
)
EXPECTED_PROOF = ROOT / (
    "papers/ieee_sensors_journal_experiments/"
    "b1_klt_exporter_7ed_to_567_transition_proof_v2.json"
)
EXPECTED_LDD_RECORDS = {
    "libvins_lib.so": {
        "path": "/home/ma/SLAM/VINS-Fusion-origin/devel/lib/libvins_lib.so",
        "size_bytes": 165_207_064,
        "sha256": "c1080aefdfd0eb3f011d491041c773649917a77923b97e24503bd90136bab467",
    },
    "libcamera_models.so": {
        "path": "/home/ma/SLAM/VINS-Fusion-origin/devel/lib/libcamera_models.so",
        "size_bytes": 2_970_640,
        "sha256": "6d7b261f12791b693f95aebea6a762a97bc3501f1f1f3c94a6af6e50f2e6690d",
    },
}


def _settings_hash(settings: dict[str, object]) -> str:
    return hashlib.sha256(
        json.dumps(
            {key: value for key, value in settings.items() if key != "settings_sha256"},
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def expected_algorithm_settings() -> dict[str, object]:
    value: dict[str, object] = {
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
        "environment_isolation": "env -i; no inherited runner/KLT variables",
    }
    value["settings_sha256"] = _settings_hash(value)
    return value


def expected_execution_governance() -> dict[str, object]:
    runner = str((ROOT / "scripts/run_aqualoc_archaeo_vins_eval.sh").resolve())
    decision_dir = str(
        (
            ROOT
            / "logs/backend_contract_decisions/b1/"
            "litcmp_a02_4500_6300_preroll_b1_native_r1"
        ).resolve()
    )
    return {
        "wrapper_api": "aqualoc_archaeology A02 4500 6300 2",
        "underlying_runner_argv": [
            "bash", runner, "external", "2", "4500", "6300", "klt", "2"
        ],
        "decision_directory": decision_dir,
        "decision_filename": "b1_current_exporter_v3_decision.json",
        "decision_directory_exclusive_create": True,
        "decision_file_exclusive_create": True,
        "output_run_directory_must_not_exist": True,
        "force_export": False,
        "retry_count": 0,
        "environment_policy": "ENV_I_EXACT_ALLOWLIST",
        "inherited_environment_reaches_runner": False,
        "explicit_fixed_inputs": ["RAW_BAG", "RAW_TAR", "GT_TXT"],
        "explicit_empty_overrides": [
            "FEATURE_BAG_OVERRIDE", "EXPORT_START_OFFSET", "EXPORT_DURATION"
        ],
        "explicit_klt_values": {
            "EXPORT_MIN_AGE": 2,
            "ZERO_VELOCITY": 0,
            "FRAME_OFFSET": 1,
            "PROCESS_SKIPPED_FRAMES": 1,
            "PREPROCESS": "adaptive_clahe",
        },
        "all_INIT_and_unlisted_EXPORT_variables": "absent_under_env_i",
    }


def evaluate_contract(contract_path: Path = DEFAULT_CONTRACT) -> dict[str, object]:
    reasons: list[str] = []
    contract: dict[str, object] = {}
    try:
        contract = common.load_object(contract_path)
    except Exception as exc:
        reasons.append(f"CONTRACT_UNREADABLE:{type(exc).__name__}:{exc}")

    records: dict[str, object] = {}
    if contract:
        if contract.get("schema_version") != "aqua-fe-b1-klt-nativeq-current-exporter-contract-v3":
            reasons.append("CONTRACT_SCHEMA_MISMATCH")
        if contract.get("status") != "FROZEN_POST_STOP_B1_CURRENT_EXPORTER_CONTRACT_V3":
            reasons.append("CONTRACT_STATUS_MISMATCH")
        if common.payload_hash(contract) != contract.get("contract_hash"):
            reasons.append("CONTRACT_HASH_MISMATCH")

        raw_records = contract.get("records")
        if not isinstance(raw_records, dict):
            reasons.append("RECORDS_INVALID")
        else:
            records = raw_records
            observed_keys = frozenset(records)
            if observed_keys != REQUIRED_RECORD_KEYS:
                reasons.append(
                    "RECORD_KEYSET_MISMATCH:"
                    f"missing={sorted(REQUIRED_RECORD_KEYS-observed_keys)}:"
                    f"extra={sorted(observed_keys-REQUIRED_RECORD_KEYS)}"
                )
            for label in sorted(REQUIRED_RECORD_KEYS & observed_keys):
                common.check_record(records[label], label, reasons)

        proof_record = records.get("transition_proof")
        if not isinstance(proof_record, dict) or not isinstance(proof_record.get("path"), str):
            reasons.append("TRANSITION_PROOF_REQUIRED")
        else:
            try:
                if Path(str(proof_record["path"])).resolve() != EXPECTED_PROOF.resolve():
                    reasons.append("TRANSITION_PROOF_PATH_MISMATCH")
                rebuilt = transition.build_proof()
                if Path(str(proof_record["path"])).read_bytes() != transition.render(rebuilt):
                    reasons.append("TRANSITION_PROOF_CONTENT_MISMATCH")
            except Exception as exc:
                reasons.append(f"TRANSITION_PROOF_RECHECK_FAILED:{type(exc).__name__}:{exc}")

        current_exporter = records.get("current_exporter")
        expected_exporter = {
            "path": str(transition.EXPORTER.resolve()),
            "size_bytes": transition.CURRENT_SIZE,
            "sha256": transition.CURRENT_SHA256,
        }
        if current_exporter != expected_exporter:
            reasons.append("CURRENT_EXPORTER_RECORD_MISMATCH")

        base: dict[str, object] | None = None
        base_record = records.get("base_contract_v1")
        if not isinstance(base_record, dict) or not isinstance(base_record.get("path"), str):
            reasons.append("BASE_CONTRACT_REQUIRED")
        else:
            try:
                if Path(str(base_record["path"])).resolve() != EXPECTED_BASE_CONTRACT.resolve():
                    reasons.append("BASE_CONTRACT_PATH_MISMATCH")
                base = common.load_object(Path(str(base_record["path"])))
                mapper = base.get("frontend_mapper")
                old = mapper.get("exporter") if isinstance(mapper, dict) else None
                if common.payload_hash(base) != base.get("contract_hash"):
                    reasons.append("BASE_CONTRACT_SELF_HASH_MISMATCH")
                if base.get("contract_hash") != contract.get("base_contract_hash"):
                    reasons.append("BASE_CONTRACT_INTERNAL_HASH_MISMATCH")
                if not isinstance(old, dict) or old.get("sha256") != transition.OLD_SHA256 or old.get("size_bytes") != transition.OLD_SIZE:
                    reasons.append("BASE_CONTRACT_OLD_EXPORTER_MISMATCH")
            except Exception as exc:
                reasons.append(f"BASE_CONTRACT_RECHECK_FAILED:{type(exc).__name__}:{exc}")

        consumers = contract.get("consumer_files")
        if (
            not isinstance(consumers, list)
            or len(consumers) != 10
            or not isinstance(base, dict)
            or consumers != base.get("consumer_files")
        ):
            reasons.append("CONSUMER_FILES_EXACT_TEN_REQUIRED")
        else:
            for index, record in enumerate(consumers):
                if not isinstance(record, dict) or not isinstance(record.get("path"), str):
                    reasons.append(f"CONSUMER_FILE:{index}:RECORD_INVALID")
                    continue
                absolute = {**record, "path": str(BACKEND_ROOT / str(record["path"]))}
                common.check_record(absolute, f"CONSUMER_FILE:{index}", reasons)

        binary_record = records.get("vins_node")
        if not isinstance(binary_record, dict) or not isinstance(binary_record.get("path"), str):
            reasons.append("VINS_NODE_REQUIRED")
        else:
            if not isinstance(base, dict) or binary_record != base.get("consumer_binary"):
                reasons.append("VINS_NODE_RECORD_MISMATCH")
            ldd_records = contract.get("vins_ldd_core")
            if not isinstance(ldd_records, dict):
                reasons.append("VINS_LDD_CORE_INVALID")
            else:
                observed_ldd = frozenset(ldd_records)
                if observed_ldd != REQUIRED_LDD_KEYS:
                    reasons.append(
                        "VINS_LDD_KEYSET_MISMATCH:"
                        f"missing={sorted(REQUIRED_LDD_KEYS-observed_ldd)}:"
                        f"extra={sorted(observed_ldd-REQUIRED_LDD_KEYS)}"
                    )
                if ldd_records != EXPECTED_LDD_RECORDS:
                    reasons.append("VINS_LDD_RECORDS_MISMATCH")
                try:
                    resolved = common._ldd_paths(Path(str(binary_record["path"])))
                    for soname in sorted(REQUIRED_LDD_KEYS & observed_ldd):
                        record = ldd_records[soname]
                        if not isinstance(record, dict) or not isinstance(record.get("path"), str):
                            reasons.append(f"VINS_LDD:{soname}:RECORD_INVALID")
                            continue
                        expected = Path(str(record["path"]))
                        actual = resolved.get(soname)
                        if actual is None or actual.resolve() != expected.resolve():
                            reasons.append(f"VINS_LDD:{soname}:PATH_MISMATCH")
                        common.check_record(record, f"VINS_LDD:{soname}", reasons)
                except Exception as exc:
                    reasons.append(f"VINS_LDD_UNREADABLE:{type(exc).__name__}:{exc}")

        algorithm = contract.get("algorithm_settings")
        if algorithm != expected_algorithm_settings():
            reasons.append("ALGORITHM_SETTINGS_EXACT_MISMATCH")
        if contract.get("transition_claim") != EXPECTED_CLAIM:
            reasons.append("TRANSITION_CLAIM_MISMATCH")
        governance = contract.get("execution_governance")
        if governance != expected_execution_governance():
            reasons.append("EXECUTION_GOVERNANCE_EXACT_MISMATCH")

    passed = not reasons
    return {
        "schema_version": "aqua-fe-b1-klt-nativeq-current-exporter-guard-decision-v3",
        "status": "PASS" if passed else "FAIL",
        "contract_pass": passed,
        "action": "ALLOW_B1_KLT_NATIVEQ_CURRENT_EXPORTER_V3" if passed else "REJECT_B1_KLT_NATIVEQ",
        "result_label": "B1_KLT_NATIVEQ_CURRENT_EXPORTER_V3" if passed else "B1_CONTRACT_REJECTED",
        "counts_as_b1": passed,
        "counts_as_proposed_result": False,
        "contract_path": str(contract_path.resolve()),
        "contract_file_sha256": common.sha256_file(contract_path) if contract_path.is_file() else None,
        "contract_hash": contract.get("contract_hash"),
        "base_contract_hash": contract.get("base_contract_hash"),
        "exporter": records.get("current_exporter"),
        "transition_proof": records.get("transition_proof"),
        "backend_binary": records.get("vins_node"),
        "vins_ldd_core": contract.get("vins_ldd_core"),
        "algorithm_settings": contract.get("algorithm_settings"),
        "reasons": reasons,
        "outcome_boundary": "B1_EXECUTION_CONTRACT_ONLY_NO_TRAJECTORY_OUTCOME",
    }


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contract", type=Path, default=DEFAULT_CONTRACT)
    parser.add_argument("--decision-json", type=Path, required=True)
    args = parser.parse_args(argv)
    decision = evaluate_contract(args.contract)
    common.write_exclusive(args.decision_json, decision)
    print(
        f"B1_CURRENT_EXPORTER_V3_GUARD action={decision['action']} "
        f"reasons={len(decision['reasons'])} decision={args.decision_json}"
    )
    return 0 if decision["contract_pass"] else 42


if __name__ == "__main__":
    raise SystemExit(main())
