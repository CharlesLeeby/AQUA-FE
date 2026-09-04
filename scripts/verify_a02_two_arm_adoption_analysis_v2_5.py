#!/usr/bin/env python3
"""Adopt the immutable v2.4 wrong-tree XFeat run and gate a two-arm contrast.

This additive v2.5 protocol does not revise v2.4's terminal FAIL and never
moves, links, copies, or reruns its artifacts.  It proves that the only v2.4
XFeat process used the correct frozen feature bag and wrote a healthy VINS
trajectory into the deterministic runner directory derived from method
``klt``.  That observed tree is adopted read-only for one descriptive B1 vs
XFeat common-support proxy contrast.  HFNet is excluded; no significance,
superiority, or three-arm claim is permitted.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import re
import sys
from typing import Mapping, Sequence

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import evaluate_vins_common_support as evaluator
from scripts import verify_a02_long_three_arm_eval_inputs_v1 as v1
from scripts import verify_a02_long_component_continuation_v2_3 as v2_3
from scripts import verify_a02_xfeat_vins_continuation_v2_4 as v2_4


FREEZE_SCHEMA = "aqua-fe-a02-4500-6300-two-arm-adoption-analysis-freeze-v2-5"
FREEZE_STATUS = "FROZEN_FIFTH_POST_INCIDENT_TWO_ARM_ADOPTION_ANALYSIS"
INCIDENT_SCHEMA = "aqua-fe-a02-4500-6300-v2-4-wrong-output-tree-adoption-incident-v1"
INCIDENT_STATUS = "V2_4_TERMINAL_FAIL_WRONG_TREE_HEALTHY_TRAJECTORY_OBSERVED"
ADOPTION_SCHEMA = "aqua-fe-a02-two-arm-pre-eval-adoption-v2-5"
ADOPTION_STATUS = "PASS_READ_ONLY_WRONG_TREE_ADOPTION_TWO_ARM_INPUTS"
EVALUATOR_RECEIPT_SCHEMA = "aqua-fe-a02-two-arm-evaluator-process-receipt-v2-5"
POST_SCHEMA = "aqua-fe-a02-two-arm-proxy-contrast-post-eval-v2-5"
POST_PASS = "PASS_STRICT_TWO_ARM_COMMON_SUPPORT_PROXY_CONTRAST"
POST_FAIL = "FAIL_STRICT_TWO_ARM_COMMON_SUPPORT_PROXY_CONTRAST"
SCIENTIFIC_ROLE = (
    "POST_INCIDENT_RESULT_INFORMED_EXPLORATORY_TWO_COMPONENT_COMMON_SUPPORT_"
    "PROXY_CONTRAST_NOT_CONFIRMATORY_NO_SIGNIFICANCE_NO_SUPERIORITY"
)

DEFAULT_FREEZE = ROOT / "papers/a02_4500_6300_two_arm_adoption_analysis_freeze_v2_5.json"
DEFAULT_INCIDENT = ROOT / "papers/a02_4500_6300_v2_4_wrong_output_tree_adoption_incident_v1.json"
DEFAULT_ADDENDUM = ROOT / "papers/2026-08-12--a02-4500-6300-two-arm-adoption-analysis-v2-5.md"
DEFAULT_BUILDER = ROOT / "scripts/build_a02_two_arm_adoption_analysis_freeze_v2_5.py"
DEFAULT_TESTS = ROOT / "scripts/tests/test_verify_a02_two_arm_adoption_analysis_v2_5.py"
DEFAULT_VERIFIER = Path(__file__).resolve()

ACTUAL_XFEAT_RUN = (
    ROOT / "logs/aqualoc_archaeo_vins/"
    "external_klt_every2_litcmp_a02_4500_6300_preroll_"
    "xfeatbirth_rawlkcarrier_v1_vins_post_incident_v2_4_r1"
)
EXPECTED_XFEAT_RUN = v2_4.XFEAT_RUN
ACTUAL_XFEAT_VIO = ACTUAL_XFEAT_RUN / "vins_output/vio.csv"
ACTUAL_XFEAT_LOG = ACTUAL_XFEAT_RUN / "vins.log"
REFERENCE = v1.DEFAULT_SHARED_ROOT / "shared/reference_proxy.tum"
EVAL_CONFIG = v1.DEFAULT_EVAL_CONFIG
EVALUATOR = v1.DEFAULT_EVALUATOR
CORE = v1.DEFAULT_CORE
ADOPTION_EVIDENCE = ROOT / "papers/a02_4500_6300_two_arm_pre_eval_adoption_v2_5.json"
EVAL_DIR = (
    ROOT / "papers/litcmp_a02_4500_6300_common_support/"
    "b1_constq_vs_xfeatbirth_adopted_v2_5_r1"
)
EVALUATOR_RECEIPT = EVAL_DIR / "evaluator_process_receipt_v2_5.json"
POST_EVIDENCE = ROOT / "papers/a02_4500_6300_two_arm_proxy_contrast_post_eval_v2_5.json"
RESERVED_PATHS = [str(ADOPTION_EVIDENCE), str(EVAL_DIR), str(POST_EVIDENCE)]

ARM_LABELS = ("B1_CONSTQ", "XFEATBIRTH_RAWLK")
CONTRAST_NAME = "A02_4500_6300_POST_INCIDENT_V2_5_B1_VS_ADOPTED_XFEAT"
WINDOW_START = "1542829061.692686528"
WINDOW_END = "1542829106.687510592"
EXPECTED_GRID_COUNT = 45

EXPECTED_V2_4_TERMINAL_SHA256 = "2e7814cf6d8a2d01c022a3f7fb516b93825c651ac2643d7eae17b5a90f499e81"
EXPECTED_V2_4_TERMINAL_SIZE = 81783
EXPECTED_V2_4_RECEIPT_SHA256 = "b15e360d966e6488d1134437863688196550665c5a5f311947c0b5efcfbab571"
EXPECTED_V2_4_RECEIPT_SIZE = 958
EXPECTED_ACTUAL_VIO_SHA256 = "d6d8742753e96d7fa6243b469337c2bebaa28aac1ba9f47bcaa43971e8e88b00"
EXPECTED_ACTUAL_VIO_SIZE = 91884
EXPECTED_ACTUAL_LOG_SHA256 = "dcccdfe164b332ea7ae3d9cff16526bed8cb0191a9c7461ccca9566533b96ec3"
EXPECTED_ACTUAL_LOG_SIZE = 90373
EXPECTED_REPLAY_SHA256 = "d0f4315d764a7d21b77cf46a3b3b5d6b6f5f9679c8504e545da77b76bd79de07"
EXPECTED_ENV_SHA256 = "980de7097bb0492d7ac1b88fb17b3bd178f811d15081e96d2aecc6e944fed5b3"
EXPECTED_CONFIG_SHA256 = "86c5c5cf3a6ca82c5f66bf1f507b32d7d2b7d648298f8f1e4afe3dd836e9fd0f"
EXPECTED_APE_SHA256 = "e1a2f12a6ff1b915da9c9f28c33a44c17735a84d1b2fa01b4d42b0e3fbd02e7a"
EXPECTED_CAMERA_SHA256 = "045505013a5dbfb629bad8d3463bbbdacad965ebdcf3c590598121bd884e50a5"
EXPECTED_ROSCORE_SHA256 = "afef38fcca1bef462fd67e8f17654f1bc34ca99695da783fd6554bca30abcbf9"
EXPECTED_NORMALIZED_CONFIG_SHA256 = (
    "45eb12852b8eff6b14dbfdb8f366fa64eebf7ca5dbf838d791f011dd84a4d084"
)
EXPECTED_ACTUAL_TREE_INVENTORY_SHA256 = (
    "4124f09c96f42ea956238880b9339e190d06fac5c329d26c7db87c38a2cb0afd"
)

EXPECTED_ACTUAL_REGULAR_FILES = {
    "ape.txt": (645, EXPECTED_APE_SHA256),
    "aqualoc_archaeo02_pinhole.yaml": (357, EXPECTED_CAMERA_SHA256),
    "replay_manifest.txt": (584, EXPECTED_REPLAY_SHA256),
    "roscore.log": (869, EXPECTED_ROSCORE_SHA256),
    "vins.log": (EXPECTED_ACTUAL_LOG_SIZE, EXPECTED_ACTUAL_LOG_SHA256),
    "vins_aqualoc_archaeo_external.yaml": (999, EXPECTED_CONFIG_SHA256),
    "vins_env_manifest.txt": (2337, EXPECTED_ENV_SHA256),
    "vins_output/vio.csv": (EXPECTED_ACTUAL_VIO_SIZE, EXPECTED_ACTUAL_VIO_SHA256),
}

_ORIGINAL_LOAD = v1.load_canonical_json
_ORIGINAL_RECEIPT_CONTRACT = v1.vins_process_receipt_contract
_ORIGINAL_RECEIPT_VALIDATOR = v1.validate_vins_process_receipt


class AdoptionVerificationError(v1.VerificationError):
    """Fail-closed v2.5 governance or evidence error."""


def identity(path: Path, label: str) -> dict[str, object]:
    _payload, result = v1.read_regular(path, label)
    return result


def require_identity(claim: object, label: str) -> dict[str, object]:
    if not isinstance(claim, Mapping) or not isinstance(claim.get("path"), str):
        raise AdoptionVerificationError(f"{label}_IDENTITY_INVALID")
    actual = identity(Path(str(claim["path"])), label)
    if dict(claim) != actual:
        raise AdoptionVerificationError(f"{label}_IDENTITY_MISMATCH")
    return actual


def require_paths_absent(paths: Sequence[str], label: str) -> None:
    present = [item for item in paths if Path(item).exists() or Path(item).is_symlink()]
    if present:
        raise AdoptionVerificationError(f"{label}:{present}")


def tree_record(path: Path, label: str) -> dict[str, object]:
    return v2_3.tree_record(path, label)


def expected_receipt_record() -> dict[str, object]:
    return v2_4.build_receipt_v2_4(0, True)


def validate_expected_tree_receipt() -> dict[str, object]:
    tree = tree_record(EXPECTED_XFEAT_RUN, "V2_5_EXPECTED_TREE")
    regular = [item for item in tree["entries"] if item.get("type") == "regular"]
    if (
        len(tree["entries"]) != 2
        or len(regular) != 1
        or regular[0].get("relative_path") != "process_rc_receipt.json"
    ):
        raise AdoptionVerificationError("V2_5_EXPECTED_TREE_NOT_SINGLETON_RECEIPT")
    record, record_identity = _ORIGINAL_LOAD(
        EXPECTED_XFEAT_RUN / "process_rc_receipt.json", "V2_5_V2_4_RECEIPT"
    )
    if (
        record != expected_receipt_record()
        or record_identity["sha256"] != EXPECTED_V2_4_RECEIPT_SHA256
        or record_identity["size_bytes"] != EXPECTED_V2_4_RECEIPT_SIZE
    ):
        raise AdoptionVerificationError("V2_5_V2_4_RECEIPT_NOT_EXACT_RC0_START1")
    return {"tree": tree, "receipt": record_identity, "record": record}


def adoption_receipt_contract(label: str) -> dict[str, object]:
    if label != "XFEATBIRTH_RAWLK":
        return _ORIGINAL_RECEIPT_CONTRACT(label)
    return {
        "run_dir": ACTUAL_XFEAT_RUN,
        "feature_bag": v2_4.XFEAT_FEATURE_BAG_CANONICAL,
        "port": 11532,
        "tag": v2_4.XFEAT_TAG,
    }


def adoption_receipt_validator(run_dir: Path, label: str) -> dict[str, object]:
    if label != "XFEATBIRTH_RAWLK":
        return _ORIGINAL_RECEIPT_VALIDATOR(run_dir, label)
    if run_dir.resolve(strict=True) != ACTUAL_XFEAT_RUN.resolve(strict=True):
        raise AdoptionVerificationError("V2_5_ADOPTED_RECEIPT_RUN_BINDING_MISMATCH")
    return validate_expected_tree_receipt()["receipt"]


def raw_duration_and_score_contract(path: Path) -> dict[str, object]:
    rows: list[int] = []
    for line_number, raw in enumerate(path.read_bytes().splitlines(), 1):
        fields = raw.decode("ascii").split(",")
        if len(fields) != 12 or fields[-1] != "":
            raise AdoptionVerificationError(f"V2_5_RAW_ROW_SHAPE:{line_number}")
        rows.append(int(fields[0]))
    score = [value for value in rows if v1.SCORE_FIRST_NS <= value <= v1.SCORE_LAST_NS]
    result = {
        "row_count": len(rows),
        "first_ns": rows[0],
        "last_ns": rows[-1],
        "duration_s": (rows[-1] - rows[0]) / 1e9,
        "score_row_count": len(score),
        "score_first_ns": score[0],
        "score_last_ns": score[-1],
        "score_span_s": (score[-1] - score[0]) / 1e9,
    }
    expected = {
        "row_count": 872,
        "first_ns": 1542829019550072320,
        "last_ns": 1542829106635604480,
        "duration_s": 87.08553216,
        "score_row_count": 450,
        "score_first_ns": 1542829061741920000,
        "score_last_ns": 1542829106635604480,
        "score_span_s": 44.89368448,
    }
    if result != expected:
        raise AdoptionVerificationError(f"V2_5_RAW_DURATION_SCORE_MISMATCH:{result}")
    return result


def validate_adopted_xfeat_arm() -> dict[str, object]:
    lineage = v2_4.validate_xfeat_chain_v2_4(
        source_bag=v1.DEFAULT_B1_CONSTQ_BAG,
        raw_bag=v1.DEFAULT_WINDOW_BAG,
        camera_yaml=v1.DEFAULT_B1_NATIVE_CAMERA,
        output_bag=v2_3.XFEAT_BAG,
        manifest_path=v2_3.XFEAT_MANIFEST,
        audit_path=v2_3.XFEAT_AUDIT,
    )
    prior_contract = v1.vins_process_receipt_contract
    prior_validator = v1.validate_vins_process_receipt
    v1.vins_process_receipt_contract = adoption_receipt_contract
    v1.validate_vins_process_receipt = adoption_receipt_validator
    try:
        result = v1.validate_vins_arm(
            ACTUAL_XFEAT_VIO,
            ACTUAL_XFEAT_LOG,
            "XFEATBIRTH_RAWLK",
            expected_feature_bag=lineage["xfeat_feature_bag"],
            expected_camera_config=lineage["camera_yaml"],
            raw_window_bag=v1.DEFAULT_WINDOW_BAG,
            eval_config=EVAL_CONFIG,
            port=11532,
        )
    finally:
        v1.vins_process_receipt_contract = prior_contract
        v1.validate_vins_process_receipt = prior_validator
    if (
        result.get("status") != "PASS"
        or result["trajectory"].get("sha256") != EXPECTED_ACTUAL_VIO_SHA256
        or result["trajectory"].get("size_bytes") != EXPECTED_ACTUAL_VIO_SIZE
        or result["raw_vins_csv_schema"].get("row_count") != 872
        or result["vins_log"].get("sha256") != EXPECTED_ACTUAL_LOG_SHA256
        or result["vins_log"].get("size_bytes") != EXPECTED_ACTUAL_LOG_SIZE
        or result["vins_log"].get("initialization_success_count") != 1
        or any(result["vins_log"]["marker_counts_after_initialization"].values())
        or result["replay_provenance"].get("normalized_vins_config_sha256")
        != EXPECTED_NORMALIZED_CONFIG_SHA256
        or result["replay_provenance"].get("camera_config", {}).get("sha256")
        != EXPECTED_CAMERA_SHA256
        or result["replay_provenance"].get("feature_bag", {}).get("sha256")
        != v2_4.EXPECTED_XFEAT_BAG_SHA256
        or result["replay_provenance"].get("ros_master_port") != 11532
    ):
        raise AdoptionVerificationError("V2_5_ADOPTED_XFEAT_HEALTH_CONTRACT_MISMATCH")
    result["raw_duration_and_score_contract"] = raw_duration_and_score_contract(
        ACTUAL_XFEAT_VIO
    )
    result["input_lineage"] = lineage
    return result


def validate_b1_component() -> dict[str, object]:
    """Revalidate immutable B1 with the exact v2.3 process-receipt contract."""
    v2_3.validate_corrected_audit()
    _payload, feature_bag = v1.read_regular(
        v1.DEFAULT_B1_CONSTQ_BAG, "V2_5_B1_FEATURE_BAG"
    )
    _payload, camera = v1.read_regular(
        v1.DEFAULT_B1_NATIVE_CAMERA, "V2_5_B1_CAMERA"
    )
    prior_contract = v1.vins_process_receipt_contract
    prior_validator = v1.validate_vins_process_receipt
    v1.vins_process_receipt_contract = v2_3.receipt_contract_v2_3
    v1.validate_vins_process_receipt = v2_3.validate_receipt_v2_3
    try:
        result = v1.validate_vins_arm(
            v2_3.B1_VIO,
            v2_3.B1_LOG,
            "B1_CONSTQ",
            expected_feature_bag=feature_bag,
            expected_camera_config=camera,
            raw_window_bag=v1.DEFAULT_WINDOW_BAG,
            eval_config=EVAL_CONFIG,
            port=v2_3.B1_PORT,
        )
    finally:
        v1.vins_process_receipt_contract = prior_contract
        v1.validate_vins_process_receipt = prior_validator
    if (
        result.get("status") != "PASS"
        or result["trajectory"].get("sha256") != v2_4.EXPECTED_B1_VIO_SHA256
        or result["vins_log"].get("sha256") != v2_4.EXPECTED_B1_LOG_SHA256
        or result["vins_log"].get("initialization_success_count") != 1
        or any(result["vins_log"]["marker_counts_after_initialization"].values())
        or result["replay_provenance"].get("normalized_vins_config_sha256")
        != EXPECTED_NORMALIZED_CONFIG_SHA256
    ):
        raise AdoptionVerificationError("V2_5_B1_COMPONENT_NOT_EXACT_IMMUTABLE_PASS")
    return result


def validate_actual_tree_and_naming() -> dict[str, object]:
    actual_tree = tree_record(ACTUAL_XFEAT_RUN, "V2_5_ACTUAL_XFEAT_TREE")
    if any(item.get("type") == "symlink" for item in actual_tree["entries"]):
        raise AdoptionVerificationError("V2_5_ACTUAL_TREE_HAS_SYMLINK")
    by_path = {
        item["relative_path"]: item
        for item in actual_tree["entries"]
        if item.get("type") == "regular"
    }
    if (
        set(by_path) != set(EXPECTED_ACTUAL_REGULAR_FILES)
        or actual_tree.get("summary") != {
            "directory_count": 2,
            "regular_file_count": 8,
            "total_regular_bytes": 188048,
            "inventory_sha256": EXPECTED_ACTUAL_TREE_INVENTORY_SHA256,
        }
        or any(
            by_path.get(name, {}).get("size_bytes") != expected[0]
            or by_path.get(name, {}).get("sha256") != expected[1]
            for name, expected in EXPECTED_ACTUAL_REGULAR_FILES.items()
        )
    ):
        raise AdoptionVerificationError("V2_5_ACTUAL_TREE_REQUIRED_FILE_IDENTITY_MISMATCH")
    receipt = validate_expected_tree_receipt()
    freeze, _freeze_identity = _ORIGINAL_LOAD(v2_4.DEFAULT_FREEZE, "V2_5_V2_4_FREEZE")
    command = freeze["commands"][2]
    runner_formula = 'RUN_DIR="$ROOT/logs/aqualoc_archaeo_vins/${MODE}_${METHOD}_every${EVERY_N}_${TAG}"'
    runner_payload = v1.RUNNER.read_text(encoding="utf-8")
    invocation_tail = (
        f"{v1.RUNNER} external 2 4500 6300 klt 2"
    )
    if (
        runner_formula not in runner_payload
        or invocation_tail not in command
        or command.count(str(v1.RUNNER)) != 1
        or v2_4.XFEAT_TAG not in command
        or str(v2_4.XFEAT_FEATURE_BAG_CANONICAL) not in command
    ):
        raise AdoptionVerificationError("V2_5_RUNNER_NAMING_DERIVATION_NOT_EXACT")
    candidates = sorted(
        path.resolve(strict=True)
        for path in (ROOT / "logs/aqualoc_archaeo_vins").glob(
            "*litcmp_a02_4500_6300_preroll_xfeatbirth_rawlkcarrier_v1_vins_post_incident_v2_4_r1"
        )
        if path.is_dir() and not path.is_symlink()
    )
    expected_candidates = sorted(
        [ACTUAL_XFEAT_RUN.resolve(strict=True), EXPECTED_XFEAT_RUN.resolve(strict=True)]
    )
    if candidates != expected_candidates:
        raise AdoptionVerificationError(f"V2_5_OFFICIAL_RUN_NAMESPACE_NOT_EXACT_TWO_TREES:{candidates}")
    arm = validate_adopted_xfeat_arm()
    return {
        "classification": "POST_INCIDENT_OBSERVED_DETERMINISTIC_OUTPUT_TREE_ADOPTION",
        "v2_4_terminal_remains_fail": True,
        "receipt_claimed_run_dir": receipt["record"]["run_dir"],
        "actual_output_dir": str(ACTUAL_XFEAT_RUN.resolve(strict=True)),
        "receipt_and_actual_tree_path_contradiction_preserved": True,
        "authorized_runner_invocation_count_in_frozen_command": 1,
        "receipt_declared_process_start_count": 1,
        "receipt_declared_process_return_code": 0,
        "orchestrator_observed_singleton_process": True,
        "persistent_process_telemetry_artifact": False,
        "cryptographically_proved_unique_vins_child": False,
        "official_namespace_trees": [str(path) for path in candidates],
        "expected_tree": receipt["tree"],
        "actual_tree": actual_tree,
        "deterministic_derivation": {
            "mode": "external",
            "method_argument": "klt",
            "every_n": 2,
            "tag": v2_4.XFEAT_TAG,
            "runner_formula": runner_formula,
            "derived_output_dir": str(ACTUAL_XFEAT_RUN.resolve(strict=True)),
            "frozen_command_contains_exact_runner_invocation": True,
        },
        "movement_copy_link_or_rerun_performed": False,
        "actual_output_namespace_was_not_reserved_absent_by_v2_4": True,
        "v2_4_no_clobber_claim_not_extended_to_actual_output_namespace": True,
        "adopted_arm": arm,
    }


def v2_4_terminal_record() -> tuple[dict[str, object], dict[str, object]]:
    terminal, terminal_identity = _ORIGINAL_LOAD(
        v2_4.TERMINAL_EVIDENCE, "V2_5_V2_4_TERMINAL"
    )
    if (
        terminal_identity["sha256"] != EXPECTED_V2_4_TERMINAL_SHA256
        or terminal_identity["size_bytes"] != EXPECTED_V2_4_TERMINAL_SIZE
        or terminal.get("status") != v2_4.TERMINAL_FAIL
        or terminal.get("terminal_outcome", {}).get(
            "descriptive_two_component_comparison_eligible"
        ) is not False
    ):
        raise AdoptionVerificationError("V2_5_V2_4_TERMINAL_NOT_EXACT_FAIL")
    return terminal, terminal_identity


def expected_incident_record() -> dict[str, object]:
    _terminal, terminal_identity = v2_4_terminal_record()
    adoption = validate_actual_tree_and_naming()
    return {
        "schema_version": INCIDENT_SCHEMA,
        "status": INCIDENT_STATUS,
        "scientific_role": (
            "POST_INCIDENT_RESULT_INFORMED_ADOPTION_DIAGNOSIS_NOT_A_COMPARISON_RESULT"
        ),
        "v2_4_terminal": terminal_identity,
        "v2_4_terminal_fail_is_immutable": True,
        "adoption_decision_is_post_incident_and_result_informed": True,
        "root_cause": {
            "classification": "RUNNER_METHOD_TOKEN_DETERMINISTIC_OUTPUT_DIRECTORY_MISMATCH",
            "feature_bag_or_algorithm_mismatch": False,
            "receipt_proves_process_start_and_rc_but_not_actual_output_directory": True,
            "unique_process_claim_is_operator_observation_not_recomputable_telemetry": True,
            "actual_output_tree_was_not_a_v2_4_reserved_no_clobber_path": True,
        },
        "read_only_adoption_proof": adoption,
        "continuation_boundary": {
            "actual_tree_adopted_read_only": True,
            "move_copy_link_cleanup_or_rerun_forbidden": True,
            "b1_xfeat_vins_hfnet_producer_auditor_bridge_forbidden": True,
            "only_new_scientific_action_is_two_arm_common_support_analysis": True,
            "hfnet_excluded": True,
            "proxy_reference_not_independent_ground_truth": True,
            "significance_superiority_and_three_arm_claims_forbidden": True,
        },
    }


def frozen_protocol() -> dict[str, object]:
    return {
        "contrast_name": CONTRAST_NAME,
        "reference": str(REFERENCE),
        "evaluation_rate_hz": 1.0,
        "nominal_reference_rate_hz": 1.0,
        "nominal_estimate_rate_hz": 10.0,
        "window_start_s": float(np.longdouble(WINDOW_START)),
        "window_end_s": float(np.longdouble(WINDOW_END)),
        "max_reference_gap_s": 2.5,
        "max_estimate_gap_s": 0.25,
        "rpe_delta_s": 1.0,
        "body_to_camera_applied": True,
        "rpe_semantics": "aligned_global_frame_positional_delta",
        "reference_time_offset_s": 0.0,
        "arm_time_offsets_s": {label: 0.0 for label in ARM_LABELS},
    }


def recompute_two_arm_summary() -> dict[str, object]:
    reference_series = evaluator.load_tum_reference(REFERENCE)
    reference_stamps, _, _, _ = evaluator.prepare_reference_samples(
        reference_series.stamps,
        reference_series.positions,
        reference_series.quaternions_xyzw,
    )
    window_start = np.longdouble(WINDOW_START)
    window_end = np.longdouble(WINDOW_END)
    grid = evaluator.make_uniform_grid(window_start, window_end, 1.0)
    reference = evaluator.resample_trajectory(
        reference_series.stamps,
        reference_series.positions,
        grid,
        2.5,
        reference_series.quaternions_xyzw,
        sample_kind="reference",
    )
    paths = {"B1_CONSTQ": v2_3.B1_VIO, "XFEATBIRTH_RAWLK": ACTUAL_XFEAT_VIO}
    transform = evaluator.load_body_t_sensor(EVAL_CONFIG)
    arms = {}
    legacy = {}
    for label, path in paths.items():
        body = evaluator.load_vins_body_csv(path)
        evaluator.validate_estimate_samples(
            body.stamps, body.positions, body.quaternions_xyzw
        )
        legacy[label] = evaluator.legacy_nearest_reuse_stats(
            body.stamps, reference_stamps
        )
        positions, quaternions = evaluator.transform_body_poses_to_sensor(
            body.positions, body.quaternions_xyzw, transform
        )
        arms[label] = evaluator.resample_trajectory(
            body.stamps,
            positions,
            grid,
            0.25,
            quaternions,
            sample_kind="estimate",
        )
    evaluation = evaluator.evaluate_common_translation(
        reference,
        arms,
        window_start_s=window_start,
        window_end_s=window_end,
        max_segment_gap_s=2.5,
        rpe_delta_s=1.0,
        min_ape_poses=30,
        min_ape_span_s=10.0,
        min_common_coverage=0.70,
        min_rpe_pairs=10,
    )
    summary = evaluator.clean_json_value(
        evaluator.serializable_summary(
            evaluation, reference, arms, frozen_protocol(), legacy
        )
    )
    if not isinstance(summary, dict):
        raise AdoptionVerificationError("V2_5_RECOMPUTED_SUMMARY_NOT_OBJECT")
    return summary


def validate_summary(path: Path) -> tuple[dict[str, object], dict[str, object]]:
    summary, summary_identity = _ORIGINAL_LOAD(path, "V2_5_COMMON_SUPPORT_SUMMARY")
    if summary != recompute_two_arm_summary():
        raise AdoptionVerificationError("V2_5_SUMMARY_NOT_RECOMPUTED_FROM_ADOPTED_INPUTS")
    support = summary.get("support")
    arms = summary.get("arms")
    if (
        not isinstance(support, Mapping)
        or support.get("ape_valid") is not True
        or support.get("rpe_valid") is not True
        or support.get("grid_count") != EXPECTED_GRID_COUNT
        or support.get("matched_count", 0) < 30
        or support.get("common_span_s", 0.0) < 10.0
        or support.get("common_coverage", 0.0) < 0.70
        or support.get("rpe_pairs", 0) < 10
        or not isinstance(arms, Mapping)
        or set(arms) != set(ARM_LABELS)
        or summary.get("protocol") != frozen_protocol()
    ):
        raise AdoptionVerificationError("V2_5_SUMMARY_STRICT_SUPPORT_PROTOCOL_MISMATCH")
    for label in ARM_LABELS:
        if (
            arms[label].get("matched_count", 0) < 30
            or arms[label].get("valid_grid_count") != EXPECTED_GRID_COUNT
            or arms[label].get("rpe_pairs", 0) < 10
        ):
            raise AdoptionVerificationError(f"V2_5_{label}_SUPPORT_INVALID")
        for key in (
            "ape_rmse_m", "ape_median_m", "ape_max_m",
            "rpe_rmse_m", "rpe_median_m", "rpe_max_m",
        ):
            value = arms[label].get(key)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
                raise AdoptionVerificationError(f"V2_5_{label}_{key}_INVALID")
    return summary, summary_identity


def validate_evo_crosscheck(
    path: Path, summary: Mapping[str, object]
) -> tuple[dict[str, object], dict[str, object]]:
    """Bind evo as a diagnostic and cross-check its primary-metric echoes."""
    record, record_identity = _ORIGINAL_LOAD(path, "V2_5_EVO_CROSSCHECK")
    arms = record.get("arms")
    primary_arms = summary.get("arms")
    if (
        record.get("evo_version") != "1.31.1"
        or record.get("rpe_delta_frames") != 1
        or record.get("rpe_semantics")
        != "aligned_global_frame_positional_delta"
        or not isinstance(arms, Mapping)
        or set(arms) != set(ARM_LABELS)
        or not isinstance(primary_arms, Mapping)
    ):
        raise AdoptionVerificationError("V2_5_EVO_CROSSCHECK_SCHEMA_MISMATCH")
    for label in ARM_LABELS:
        item = arms[label]
        primary = primary_arms[label]
        if not isinstance(item, Mapping) or not isinstance(primary, Mapping):
            raise AdoptionVerificationError(f"V2_5_EVO_{label}_NOT_OBJECT")
        numeric = (
            "primary_ape_rmse_m", "evo_ape_rmse_m", "ape_abs_diff_m",
            "primary_rpe_rmse_m", "evo_segmented_rpe_rmse_m", "rpe_abs_diff_m",
        )
        if any(
            isinstance(item.get(key), bool)
            or not isinstance(item.get(key), (int, float))
            or not math.isfinite(float(item[key]))
            for key in numeric
        ):
            raise AdoptionVerificationError(f"V2_5_EVO_{label}_NONFINITE")
        segments = item.get("segments")
        if (
            item["primary_ape_rmse_m"] != primary["ape_rmse_m"]
            or item["primary_rpe_rmse_m"] != primary["rpe_rmse_m"]
            or not math.isclose(
                item["ape_abs_diff_m"],
                abs(item["primary_ape_rmse_m"] - item["evo_ape_rmse_m"]),
                rel_tol=0.0,
                abs_tol=1e-15,
            )
            or not math.isclose(
                item["rpe_abs_diff_m"],
                abs(item["primary_rpe_rmse_m"] - item["evo_segmented_rpe_rmse_m"]),
                rel_tol=0.0,
                abs_tol=1e-15,
            )
            or item.get("rpe_pair_count") != summary["support"]["rpe_pairs"]
            or not isinstance(segments, list)
            or len(segments) != 1
            or not isinstance(segments[0], Mapping)
            or set(segments[0]) != {"segment_id", "pair_count", "rmse_m"}
            or segments[0].get("segment_id") != 0
            or segments[0].get("pair_count") != summary["support"]["rpe_pairs"]
            or isinstance(segments[0].get("rmse_m"), bool)
            or not isinstance(segments[0].get("rmse_m"), (int, float))
            or not math.isfinite(float(segments[0]["rmse_m"]))
            or not math.isclose(
                float(segments[0]["rmse_m"]),
                float(item["evo_segmented_rpe_rmse_m"]),
                rel_tol=0.0,
                abs_tol=1e-15,
            )
        ):
            raise AdoptionVerificationError(
                f"V2_5_EVO_{label}_PRIMARY_CROSSCHECK_MISMATCH"
            )
    return record, record_identity


def evaluator_receipt_record(return_code: int) -> dict[str, object]:
    if isinstance(return_code, bool) or not 0 <= return_code <= 255:
        raise AdoptionVerificationError("V2_5_EVALUATOR_RC_INVALID")
    return {
        "schema_version": EVALUATOR_RECEIPT_SCHEMA,
        "status": "PASS_PROCESS_RC0" if return_code == 0 else "FAIL_PROCESS_NONZERO",
        "return_code": return_code,
        "actual_process_start_count": 1,
        "return_code_observed_after_process": True,
        "attempt_count": 1,
        "no_retry": True,
        "output_dir": str(EVAL_DIR),
        "evaluator": identity(EVALUATOR, "V2_5_RECEIPT_EVALUATOR"),
        "reference": identity(REFERENCE, "V2_5_RECEIPT_REFERENCE"),
        "config": identity(EVAL_CONFIG, "V2_5_RECEIPT_CONFIG"),
        "arms": {
            "B1_CONSTQ": identity(v2_3.B1_VIO, "V2_5_RECEIPT_B1"),
            "XFEATBIRTH_RAWLK": identity(ACTUAL_XFEAT_VIO, "V2_5_RECEIPT_XFEAT"),
        },
    }


def build_adoption_record(path: Path) -> dict[str, object]:
    validate_revision(path, require_reserved_absent=False)
    incident, incident_identity = _ORIGINAL_LOAD(DEFAULT_INCIDENT, "V2_5_ADOPTION_INCIDENT")
    return {
        "schema_version": ADOPTION_SCHEMA,
        "status": ADOPTION_STATUS,
        "scientific_role": SCIENTIFIC_ROLE,
        "active_freeze": identity(path, "V2_5_ADOPTION_FREEZE"),
        "incident": incident_identity,
        "v2_4_terminal_status_preserved": v2_4.TERMINAL_FAIL,
        "read_only_adoption_proof": incident["read_only_adoption_proof"],
        "b1_component": validate_b1_component(),
        "two_arm_analysis_eligible": True,
        "hfnet_excluded": True,
        "ranking_or_superiority_eligible": False,
        "proxy_reference_is_independent_ground_truth": False,
    }


def read_adoption_evidence(path: Path) -> dict[str, object]:
    expected = build_adoption_record(path)
    payload, evidence_identity = v1.read_regular(
        ADOPTION_EVIDENCE, "V2_5_ADOPTION_EVIDENCE"
    )
    if payload != v1.canonical_json(expected):
        raise AdoptionVerificationError("V2_5_ADOPTION_EVIDENCE_DRIFT")
    return {"record": expected, "identity": evidence_identity}


def build_post_record(path: Path) -> dict[str, object]:
    validate_revision(path, require_reserved_absent=False)
    adoption = read_adoption_evidence(path)
    failures: list[str] = []
    receipt_identity: dict[str, object] | None = None
    receipt: dict[str, object] | None = None
    try:
        receipt, receipt_identity = _ORIGINAL_LOAD(
            EVALUATOR_RECEIPT, "V2_5_EVALUATOR_RECEIPT"
        )
        if receipt != evaluator_receipt_record(0):
            failures.append("EVALUATOR_PROCESS_RECEIPT_NOT_EXACT_RC0")
    except (OSError, ValueError, v1.VerificationError) as error:
        failures.append(f"EVALUATOR_PROCESS_RECEIPT_INVALID:{error}")
    summary: dict[str, object] | None = None
    summary_identity: dict[str, object] | None = None
    try:
        summary, summary_identity = validate_summary(
            EVAL_DIR / "common_support_summary.json"
        )
    except (OSError, ValueError, v1.VerificationError) as error:
        failures.append(f"COMMON_SUPPORT_SUMMARY_INVALID:{error}")
    evo_identity: dict[str, object] | None = None
    try:
        if summary is None:
            raise AdoptionVerificationError("V2_5_EVO_REQUIRES_VALID_PRIMARY_SUMMARY")
        _evo, evo_identity = validate_evo_crosscheck(
            EVAL_DIR / "evo_crosscheck.json", summary
        )
    except (OSError, ValueError, v1.VerificationError) as error:
        failures.append(f"EVO_DIAGNOSTIC_CROSSCHECK_INVALID:{error}")
    output_tree = None
    try:
        output_tree = validate_eval_output_tree()
    except (OSError, ValueError, v1.VerificationError) as error:
        failures.append(f"EVAL_OUTPUT_TREE_INVALID:{error}")
    passed = not failures
    return {
        "schema_version": POST_SCHEMA,
        "status": POST_PASS if passed else POST_FAIL,
        "scientific_role": SCIENTIFIC_ROLE,
        "active_freeze": identity(path, "V2_5_POST_FREEZE"),
        "pre_eval_adoption_evidence": adoption["identity"],
        "evaluator_process_receipt": receipt_identity,
        "common_support_summary": summary_identity,
        "evo_crosscheck_diagnostic": evo_identity,
        "evo_crosscheck_role": "DIAGNOSTIC_ONLY_NOT_PRIMARY_RESULT_OR_RANKING",
        "auxiliary_csv_role": "BOUND_AUDIT_EXPORTS_PRIMARY_RESULT_IS_RECOMPUTED_JSON",
        "evaluation_output_tree": output_tree,
        "strict_gates": {
            "evaluator_rc0": receipt is not None and receipt.get("return_code") == 0,
            "ape_valid": bool(summary and summary.get("support", {}).get("ape_valid") is True),
            "rpe_valid": bool(summary and summary.get("support", {}).get("rpe_valid") is True),
            "grid_count": summary.get("support", {}).get("grid_count") if summary else None,
            "arm_labels": sorted(summary.get("arms", {})) if summary else [],
            "summary_recomputed_from_current_sealed_inputs": summary is not None,
            "evo_diagnostic_bound_and_primary_values_crosschecked": evo_identity is not None,
        },
        "failure_reasons": failures,
        "descriptive_two_arm_proxy_contrast_valid": passed,
        "hfnet_excluded": True,
        "three_arm_evaluation_performed": False,
        "statistical_significance_test_performed": False,
        "superiority_claim": False,
        "ranking_claim": False,
        "proxy_reference_is_independent_ground_truth": False,
        "result_metrics": summary.get("arms") if passed and summary else None,
    }


def validate_eval_output_tree() -> dict[str, object]:
    tree = tree_record(EVAL_DIR, "V2_5_EVAL_OUTPUT_TREE")
    regular = {
        item["relative_path"]
        for item in tree["entries"]
        if item.get("type") == "regular"
    }
    directories = {
        item["relative_path"]
        for item in tree["entries"]
        if item.get("type") == "directory"
    }
    expected_regular = {
        "common_grid_audit.csv",
        "common_support_metrics.csv",
        "common_support_summary.json",
        "evaluator_process_receipt_v2_5.json",
        "evo_crosscheck.json",
        "evo_crosscheck/reference_common.tum",
        "evo_crosscheck/reference_segment_000.tum",
    }
    for label in ARM_LABELS:
        expected_regular.update(
            {
                f"evo_crosscheck/{label}_common_aligned.tum",
                f"evo_crosscheck/{label}_evo_ape.log",
                f"evo_crosscheck/{label}_evo_rpe_segment_000.log",
                f"evo_crosscheck/{label}_segment_000.tum",
            }
        )
    if (
        regular != expected_regular
        or directories != {".", "evo_crosscheck"}
        or any(item.get("type") == "symlink" for item in tree["entries"])
        or tree.get("summary", {}).get("regular_file_count") != len(expected_regular)
        or tree.get("summary", {}).get("directory_count") != 2
    ):
        raise AdoptionVerificationError("V2_5_EVAL_OUTPUT_TREE_CLOSURE_MISMATCH")
    return tree


def expected_static_paths() -> dict[str, Path]:
    paths = {f"v2_4_{key}": value for key, value in v2_4.expected_static_paths().items()}
    paths.update(
        {
            "v2_4_freeze": v2_4.DEFAULT_FREEZE,
            "v2_4_terminal": v2_4.TERMINAL_EVIDENCE,
            "v2_5_addendum": DEFAULT_ADDENDUM,
            "v2_5_builder": DEFAULT_BUILDER,
            "v2_5_incident": DEFAULT_INCIDENT,
            "v2_5_tests": DEFAULT_TESTS,
            "v2_5_verifier": DEFAULT_VERIFIER,
            "evaluator": EVALUATOR,
            "trajectory_eval_core": CORE,
            "unified_arm_config": EVAL_CONFIG,
            "reference_proxy": REFERENCE,
        }
    )
    return paths


def evaluation_contract() -> dict[str, object]:
    return {
        "arm_labels": list(ARM_LABELS),
        "protocol": frozen_protocol(),
        "unified_arm_config_sha256": v1.CONFIG_SHA256,
        "reference_sha256": "b1ae03e073ea1c2bcf12891ae0cca0eab462e044e73a1045ad4f11aa8b108d2c",
        "required_grid_count": EXPECTED_GRID_COUNT,
        "ape_valid_required": True,
        "rpe_valid_required": True,
        "run_evo_crosscheck": True,
        "proxy_reference_is_independent_ground_truth": False,
        "descriptive_component_proxy_contrast_only": True,
        "significance_superiority_ranking_and_three_arm_claims_forbidden": True,
    }


def interpretation_boundary() -> dict[str, object]:
    return {
        "adoption_decision_after_native_single_arm_ape_was_visible": True,
        "pre_registered_or_confirmatory": False,
        "comparison_role": "POST_INCIDENT_RESULT_INFORMED_EXPLORATORY_TWO_COMPONENT_PROXY_CONTRAST",
        "reference_is_proxy_and_not_independent_ground_truth": True,
        "hfnet_is_excluded_as_immutable_unusable_carry_forward": True,
        "statistical_significance_superiority_ranking_and_three_arm_claims_forbidden": True,
    }


def sealed_prefix() -> str:
    return v1.sealed_evaluation_python_prefix()


def verifier_command(action: str) -> str:
    return (
        f"{sealed_prefix()} scripts/verify_a02_two_arm_adoption_analysis_v2_5.py "
        f"--revision-freeze {DEFAULT_FREEZE} --action {action}"
    )


def evaluator_command() -> str:
    return (
        f"{sealed_prefix()} scripts/evaluate_vins_common_support.py "
        f"--reference-tum {REFERENCE} "
        f"--arm B1_CONSTQ={v2_3.B1_VIO} "
        f"--arm XFEATBIRTH_RAWLK={ACTUAL_XFEAT_VIO} "
        f"--arm-config B1_CONSTQ={EVAL_CONFIG} "
        f"--arm-config XFEATBIRTH_RAWLK={EVAL_CONFIG} "
        "--nominal-reference-rate-hz 1 --nominal-estimate-rate-hz 10 "
        "--evaluation-rate-hz 1 --max-reference-gap-s 2.5 "
        f"--max-estimate-gap-s 0.25 --window-start-s {WINDOW_START} "
        f"--window-end-s {WINDOW_END} --rpe-delta-s 1 "
        "--min-ape-poses 30 --min-ape-span-s 10 --min-common-coverage 0.70 "
        f"--min-rpe-pairs 10 --contrast-name {CONTRAST_NAME} "
        f"--output-dir {EVAL_DIR} --run-evo"
    )


def expected_commands() -> list[str]:
    start = (
        f"{sealed_prefix()} scripts/build_a02_two_arm_adoption_analysis_freeze_v2_5.py --action check && "
        f"{verifier_command('check-continuation-start')} || exit 42"
    )
    adoption = (
        f"adopt_seal_rc=0; {verifier_command('seal-adoption')} || adopt_seal_rc=$?; "
        f"adopt_check_rc=2; if [ -e {ADOPTION_EVIDENCE} ]; then adopt_check_rc=0; "
        f"{verifier_command('check-adoption')} || adopt_check_rc=$?; fi; "
        "if [ \"$adopt_seal_rc\" -eq 0 ] && [ \"$adopt_check_rc\" -eq 0 ]; then exit 0; else exit 42; fi"
    )
    evaluate = (
        f"pre_rc=0; {verifier_command('check-static')} && {verifier_command('check-adoption')} || pre_rc=$?; "
        "if [ \"$pre_rc\" -ne 0 ]; then exit 42; fi; "
        f"/usr/bin/mkdir -p {EVAL_DIR.parent} || exit 73; "
        f"/usr/bin/mkdir {EVAL_DIR} || exit 73; eval_rc=0; "
        f"{evaluator_command()} || eval_rc=$?; receipt_rc=0; "
        f"{sealed_prefix()} scripts/verify_a02_two_arm_adoption_analysis_v2_5.py "
        f"--revision-freeze {DEFAULT_FREEZE} --action seal-evaluator-rc "
        "--return-code \"$eval_rc\" || receipt_rc=$?; "
        "post_seal_rc=0; "
        f"{verifier_command('seal-post')} || post_seal_rc=$?; post_check_rc=2; "
        f"if [ -e {POST_EVIDENCE} ]; then post_check_rc=0; "
        f"{verifier_command('check-post')} || post_check_rc=$?; fi; "
        "printf 'V2_5_EVALUATOR_RC=%s\\n' \"$eval_rc\"; "
        "printf 'V2_5_EVALUATOR_RECEIPT_RC=%s\\n' \"$receipt_rc\"; "
        "printf 'V2_5_POST_SEAL_RC=%s\\n' \"$post_seal_rc\"; "
        "printf 'V2_5_POST_CHECK_RC=%s\\n' \"$post_check_rc\"; "
        "if [ \"$receipt_rc\" -ne 0 ] || [ \"$post_seal_rc\" -ne 0 ]; then exit 2; fi; "
        "if [ \"$eval_rc\" -ne 0 ]; then exit \"$eval_rc\"; fi; "
        "if [ \"$post_check_rc\" -eq 0 ]; then exit 0; fi; "
        "if [ \"$post_check_rc\" -eq 3 ]; then exit 3; else exit 2; fi"
    )
    commands = [start, adoption, evaluate]
    joined = "\n".join(commands)
    forbidden = (
        "run_aqualoc_archaeo_vins_eval.sh",
        "export_xfeat_lk_carrier_v1.py",
        "audit_xfeat_lk_carrier_v1.py",
        "agent_qi_calibration_rewrite_bag.py",
        "audit_quality_partition.py",
        "run_hfnet_slam",
        "bridge_hfnet",
        "HFNET_WHOLE_SYSTEM=",
    )
    if any(token in joined for token in forbidden):
        raise AdoptionVerificationError("V2_5_COMMAND_PROTOCOL_FORBIDDEN_TOKEN")
    if joined.count("scripts/evaluate_vins_common_support.py") != 1:
        raise AdoptionVerificationError("V2_5_EVALUATOR_INVOCATION_COUNT_NOT_ONE")
    return commands


def validate_revision(path: Path, *, require_reserved_absent: bool) -> dict[str, object]:
    freeze, freeze_identity = _ORIGINAL_LOAD(path, "V2_5_FREEZE")
    keys = {
        "schema_version", "status", "working_directory", "scientific_role",
        "incident", "protocol_history", "read_only_adoption_contract",
        "evaluation_contract", "interpretation_boundary",
        "reserved_paths_absent_at_freeze",
        "execution_policy", "command_labels", "commands", "required_static_identities",
    }
    if (
        set(freeze) != keys
        or freeze.get("schema_version") != FREEZE_SCHEMA
        or freeze.get("status") != FREEZE_STATUS
        or freeze.get("working_directory") != str(ROOT)
        or freeze.get("scientific_role") != SCIENTIFIC_ROLE
    ):
        raise AdoptionVerificationError("V2_5_FREEZE_SCHEMA_STATUS_ROLE_CWD_MISMATCH")
    v2_4.validate_revision(v2_4.DEFAULT_FREEZE, require_reserved_absent=False)
    static = freeze.get("required_static_identities")
    paths = expected_static_paths()
    if not isinstance(static, Mapping) or set(static) != set(paths):
        raise AdoptionVerificationError("V2_5_STATIC_IDENTITY_SET_MISMATCH")
    for label, expected_path in paths.items():
        checked = require_identity(static[label], f"V2_5_STATIC_{label}")
        if checked["path"] != str(expected_path.resolve(strict=True)):
            raise AdoptionVerificationError(f"V2_5_STATIC_PATH_MISMATCH:{label}")
    if static["evaluator"]["sha256"] != v1.EVALUATOR_SHA256:
        raise AdoptionVerificationError("V2_5_EVALUATOR_SHA_MISMATCH")
    if static["trajectory_eval_core"]["sha256"] != v1.CORE_SHA256:
        raise AdoptionVerificationError("V2_5_CORE_SHA_MISMATCH")
    if static["unified_arm_config"]["sha256"] != v1.CONFIG_SHA256:
        raise AdoptionVerificationError("V2_5_CONFIG_SHA_MISMATCH")
    v1.validate_evaluation_runtime()
    incident, incident_identity = _ORIGINAL_LOAD(DEFAULT_INCIDENT, "V2_5_INCIDENT")
    if incident != expected_incident_record() or freeze.get("incident") != incident_identity:
        raise AdoptionVerificationError("V2_5_INCIDENT_OR_BINDING_MISMATCH")
    if freeze.get("read_only_adoption_contract") != incident["read_only_adoption_proof"]:
        raise AdoptionVerificationError("V2_5_ADOPTION_CONTRACT_DRIFT")
    if freeze.get("evaluation_contract") != evaluation_contract():
        raise AdoptionVerificationError("V2_5_EVALUATION_CONTRACT_MISMATCH")
    if freeze.get("interpretation_boundary") != interpretation_boundary():
        raise AdoptionVerificationError("V2_5_INTERPRETATION_BOUNDARY_MISMATCH")
    if freeze.get("reserved_paths_absent_at_freeze") != RESERVED_PATHS:
        raise AdoptionVerificationError("V2_5_RESERVED_PATH_SET_MISMATCH")
    if require_reserved_absent:
        require_paths_absent(RESERVED_PATHS, "V2_5_RESERVED_PATH_PRESENT")
    if freeze.get("commands") != expected_commands():
        raise AdoptionVerificationError("V2_5_COMMAND_PROTOCOL_MISMATCH")
    if freeze.get("command_labels") != ["42R5", "43C5", "44C5"]:
        raise AdoptionVerificationError("V2_5_COMMAND_LABELS_MISMATCH")
    policy = {
        "fixed_order": True,
        "formal_commands_executed_by_builder": False,
        "global_identity_or_adoption_failure_stops_before_evaluator": True,
        "single_two_arm_evaluator_attempt": True,
        "no_retry": True,
        "atomic_exact_eval_directory_claim": True,
        "single_writer_working_directory": str(ROOT),
        "move_copy_link_cleanup_or_algorithm_rerun_forbidden": True,
        "hfnet_and_three_arm_evaluation_forbidden": True,
        "descriptive_proxy_contrast_only": True,
    }
    if freeze.get("execution_policy") != policy:
        raise AdoptionVerificationError("V2_5_EXECUTION_POLICY_MISMATCH")
    history = [
        {
            "protocol": "v2.4",
            "status": "FIXED_ORDER_COMPLETED_TERMINAL_FAIL_NOT_RESUMED",
            "freeze": static["v2_4_freeze"],
            "terminal": static["v2_4_terminal"],
        },
        {
            "protocol": "v2.5",
            "status": "FROZEN_NOT_EXECUTED",
            "incident": incident_identity,
        },
    ]
    if freeze.get("protocol_history") != history:
        raise AdoptionVerificationError("V2_5_PROTOCOL_HISTORY_MISMATCH")
    return {
        "status": "PASS_V2_5_START" if require_reserved_absent else "PASS_V2_5_STATIC",
        "freeze": freeze_identity,
        "static_identity_count": len(static),
        "reserved_path_count": len(RESERVED_PATHS),
        "adopted_xfeat_vio": incident["read_only_adoption_proof"]["adopted_arm"]["trajectory"],
    }


def write_once(path: Path, record: Mapping[str, object], label: str) -> dict[str, object]:
    if path.exists() or path.is_symlink():
        raise AdoptionVerificationError(f"{label}_ALREADY_EXISTS")
    payload = v1.canonical_json(dict(record))
    v1.write_exclusive(path, payload)
    return {
        "path": str(path),
        "size_bytes": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest(),
    }


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(description=__doc__)
    value.add_argument(
        "--action",
        choices=(
            "check-continuation-start", "check-static", "seal-adoption",
            "check-adoption", "seal-evaluator-rc", "seal-post", "check-post",
        ),
        required=True,
    )
    value.add_argument("--revision-freeze", type=Path, default=DEFAULT_FREEZE)
    value.add_argument("--return-code", type=int)
    return value


def main(argv: Sequence[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        if args.action == "check-continuation-start":
            print(json.dumps(validate_revision(args.revision_freeze, require_reserved_absent=True), sort_keys=True))
            return 0
        validate_revision(args.revision_freeze, require_reserved_absent=False)
        if args.action == "check-static":
            print(json.dumps({"status": "PASS_V2_5_STATIC"}, sort_keys=True))
            return 0
        if args.action in {"seal-adoption", "check-adoption"}:
            record = build_adoption_record(args.revision_freeze)
            if args.action == "seal-adoption":
                result = write_once(ADOPTION_EVIDENCE, record, "V2_5_ADOPTION_EVIDENCE")
                status = "SEALED"
            else:
                result = read_adoption_evidence(args.revision_freeze)["identity"]
                status = "CHECK_PASS"
            print(json.dumps({"status": status, "evidence": result}, sort_keys=True))
            return 0
        if args.action == "seal-evaluator-rc":
            if args.return_code is None:
                raise AdoptionVerificationError("V2_5_EVALUATOR_RC_MISSING")
            if not EVAL_DIR.is_dir() or EVAL_DIR.is_symlink():
                raise AdoptionVerificationError("V2_5_EVAL_DIR_NOT_OWNED_REAL_DIRECTORY")
            result = write_once(
                EVALUATOR_RECEIPT,
                evaluator_receipt_record(args.return_code),
                "V2_5_EVALUATOR_RECEIPT",
            )
            print(json.dumps({"status": "SEALED_EVALUATOR_RECEIPT", "evidence": result}, sort_keys=True))
            return 0
        record = build_post_record(args.revision_freeze)
        if args.action == "seal-post":
            result = write_once(POST_EVIDENCE, record, "V2_5_POST_EVIDENCE")
            status = "SEALED"
        else:
            payload, result = v1.read_regular(POST_EVIDENCE, "V2_5_POST_EVIDENCE")
            if payload != v1.canonical_json(record):
                raise AdoptionVerificationError("V2_5_POST_EVIDENCE_DRIFT")
            status = "CHECK_PASS"
        print(json.dumps({
            "status": status,
            "scientific_status": record["status"],
            "evidence": result,
        }, sort_keys=True))
        return 0 if args.action == "seal-post" or record["status"] == POST_PASS else 3
    except (v1.VerificationError, OSError, ValueError, json.JSONDecodeError) as error:
        print(f"VERIFICATION_BLOCKED:{error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
