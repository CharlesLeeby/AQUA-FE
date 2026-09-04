#!/usr/bin/env python3
"""Additive v2.4 continuation: one first XFeat VINS attempt, no ranking.

The v1--v2.3 protocols and all scientific artifacts they produced are
immutable.  v2.3 ended normally with B1 usable, HFNet unusable, and the XFeat
VINS process not started because the legacy XFeat manifest validator compared
one runtime counter to the publication-frame count and compared five lexical
paths without resolving the workspace data symlink.  This verifier accepts
only the already-produced, byte-exact XFeat manifest and proves its actual
``detect_calls == 1562`` from independent fields before applying a six-leaf
in-memory compatibility projection to the frozen v1 validator.  The projected
object is never written and 900 is never reported as an observed detector-call
count.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path
import sys
from typing import Mapping, Sequence


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import verify_a02_long_component_continuation_v2_3 as v2_3
from scripts import verify_a02_long_three_arm_eval_inputs_v1 as v1
from scripts import verify_a02_long_three_arm_eval_inputs_v2 as v2_1


FREEZE_SCHEMA = "aqua-fe-a02-4500-6300-xfeat-vins-only-continuation-freeze-v2-4"
FREEZE_STATUS = "FROZEN_FOURTH_POST_INCIDENT_XFEAT_VINS_ONLY_CONTINUATION"
INCIDENT_SCHEMA = "aqua-fe-a02-4500-6300-v2-3-xfeat-manifest-false-negative-incident-v1"
INCIDENT_STATUS = "V2_3_FIXED_ORDER_COMPLETED_XFEAT_VINS_NOT_STARTED_FALSE_NEGATIVE"
RECEIPT_SCHEMA = "aqua-fe-a02-xfeat-vins-process-receipt-v2-4"
TERMINAL_SCHEMA = "aqua-fe-a02-xfeat-vins-terminal-v2-4-post-incident-continuation"
TERMINAL_PASS = (
    "TERMINAL_XFEAT_VINS_USABLE_DESCRIPTIVE_TWO_COMPONENT_COMPARISON_"
    "ELIGIBLE_HFNET_EXCLUDED"
)
TERMINAL_FAIL = "TERMINAL_XFEAT_VINS_UNUSABLE_NO_COMPARISON_HFNET_EXCLUDED"
SCIENTIFIC_ROLE = (
    "FOURTH_POST_INCIDENT_DEVELOPMENT_EXPLORATORY_XFEAT_VINS_USABILITY_"
    "NOT_CONFIRMATORY_NOT_A_RANKING_RESULT"
)

DEFAULT_FREEZE = ROOT / "papers/a02_4500_6300_xfeat_vins_only_continuation_freeze_v2_4.json"
DEFAULT_INCIDENT = ROOT / "papers/a02_4500_6300_v2_3_xfeat_manifest_false_negative_incident_v1.json"
DEFAULT_ADDENDUM = ROOT / "papers/2026-08-12--a02-4500-6300-xfeat-vins-only-continuation-v2-4.md"
DEFAULT_BUILDER = ROOT / "scripts/build_a02_xfeat_vins_continuation_freeze_v2_4.py"
DEFAULT_TESTS = ROOT / "scripts/tests/test_verify_a02_xfeat_vins_continuation_v2_4.py"
DEFAULT_VERIFIER = Path(__file__).resolve()

XFEAT_RUN = (
    ROOT
    / "logs/aqualoc_archaeo_vins/"
    "external_xfeat_lk_every2_litcmp_a02_4500_6300_preroll_"
    "xfeatbirth_rawlkcarrier_v1_vins_post_incident_v2_4_r1"
)
XFEAT_VIO = XFEAT_RUN / "vins_output/vio.csv"
XFEAT_LOG = XFEAT_RUN / "vins.log"
XFEAT_TAG = (
    "litcmp_a02_4500_6300_preroll_"
    "xfeatbirth_rawlkcarrier_v1_vins_post_incident_v2_4_r1"
)
XFEAT_PORT = 11532
XFEAT_FEATURE_BAG_CANONICAL = v2_3.XFEAT_BAG.resolve(strict=True)
TERMINAL_EVIDENCE = ROOT / "papers/a02_4500_6300_xfeat_vins_terminal_v2_4_post_incident.json"
RESERVED_PATHS = [str(XFEAT_RUN), str(TERMINAL_EVIDENCE)]

EXPECTED_V2_3_FREEZE_SHA256 = "0d008cb6b18ae2d4fada2f84dfd444b16e54abf0fdf54c7a9ad80b1f352e4609"
EXPECTED_V2_3_TERMINAL_SHA256 = "533c2c58f07ccaff7e513bed098178764b026334b362dafc889dc616f232ac2b"
EXPECTED_XFEAT_MANIFEST_SHA256 = "49ab1814a84222167a173f9e01a9ff9a70b33df9974a131d4b32e026f436da99"
EXPECTED_XFEAT_MANIFEST_SIZE = 812038
EXPECTED_XFEAT_BAG_SHA256 = "13d0daf45e81560506cc44927318d91821ffc40564ded4529ce1466ed70700c0"
EXPECTED_XFEAT_BAG_SIZE = 27396366
EXPECTED_XFEAT_AUDIT_SHA256 = "d2bc2d8be0c5daf5700a89e1e68ebbc6f9c479ebf260eb80fac10c01031901b5"
EXPECTED_XFEAT_AUDIT_SIZE = 6053
EXPECTED_B1_VIO_SHA256 = "59c505704e9e82c050abe2c3e2edb83517b7044828beb694780646ff7a2bea92"
EXPECTED_B1_LOG_SHA256 = "454d828f9eec6884c680d079e0664db0e4de2dcacc6bef62ad2ddddb8842281e"
EXPECTED_B1_RECEIPT_SHA256 = "545219acf1fe53422e27c6b0cf1def9d0f83603e1697922ae41dd6122eb43023"
EXPECTED_OLD_XFEAT_SKIP_RECEIPT_SHA256 = "20b5417f9553f8e9e93c538124d2ed7d1e8354e6d0e187bec2720ed3bb06dd9f"
ACTUAL_DETECT_CALLS = 1562
RAW_FRAME_COUNT = 1800
PUBLISHED_FRAME_COUNT = 900

_ORIGINAL_LOAD = v1.load_canonical_json
_ORIGINAL_XFEAT_VALIDATOR = v1.validate_xfeat_chain
_ORIGINAL_QUALITY_VALIDATOR = v1.validate_quality_chain
_ORIGINAL_RECEIPT_CONTRACT = v1.vins_process_receipt_contract
_ORIGINAL_RECEIPT_VALIDATOR = v1.validate_vins_process_receipt


class XFeatContinuationError(v1.VerificationError):
    """Fail-closed v2.4 governance or evidence error."""


def identity(path: Path, label: str) -> dict[str, object]:
    _payload, result = v1.read_regular(path, label)
    return result


def require_identity(claim: object, label: str) -> dict[str, object]:
    if not isinstance(claim, Mapping) or not isinstance(claim.get("path"), str):
        raise XFeatContinuationError(f"{label}_IDENTITY_INVALID")
    actual = identity(Path(str(claim["path"])), label)
    if dict(claim) != actual:
        raise XFeatContinuationError(f"{label}_IDENTITY_MISMATCH")
    return actual


def require_paths_absent(paths: Sequence[str], label: str) -> None:
    present = [item for item in paths if Path(item).exists() or Path(item).is_symlink()]
    if present:
        raise XFeatContinuationError(f"{label}:{present}")


def _nested_get(value: Mapping[str, object], keys: Sequence[str]) -> object:
    current: object = value
    for key in keys:
        if not isinstance(current, Mapping) or key not in current:
            raise XFeatContinuationError(f"XFEAT_MANIFEST_REQUIRED_FIELD_MISSING:{'.'.join(keys)}")
        current = current[key]
    return current


def _nested_set(value: dict[str, object], keys: Sequence[str], replacement: object) -> None:
    current: dict[str, object] = value
    for key in keys[:-1]:
        child = current.get(key)
        if not isinstance(child, dict):
            raise XFeatContinuationError(f"XFEAT_COMPATIBILITY_PATH_INVALID:{'.'.join(keys)}")
        current = child
    current[keys[-1]] = replacement


def recursive_leaf_diff(left: object, right: object, prefix: tuple[str, ...] = ()) -> list[str]:
    if isinstance(left, Mapping) and isinstance(right, Mapping):
        if set(left) != set(right):
            return [".".join(prefix + ("<keyset>",))]
        result: list[str] = []
        for key in sorted(left):
            result.extend(recursive_leaf_diff(left[key], right[key], prefix + (str(key),)))
        return result
    if isinstance(left, list) and isinstance(right, list):
        if len(left) != len(right):
            return [".".join(prefix + ("<length>",))]
        result = []
        for index, (a, b) in enumerate(zip(left, right)):
            result.extend(recursive_leaf_diff(a, b, prefix + (str(index),)))
        return result
    return [] if left == right else [".".join(prefix)]


PATH_PROJECTION_LEAVES = (
    ("code_artifacts", "detector", "closure", "interpolator.py", "path"),
    ("code_artifacts", "detector", "closure", "model.py", "path"),
    ("code_artifacts", "detector", "closure", "xfeat.pt", "path"),
    ("code_artifacts", "detector", "closure", "xfeat.py", "path"),
    ("code_artifacts", "detector", "license", "file", "path"),
)
DETECT_PROJECTION_LEAF = ("code_artifacts", "detector", "runtime", "detect_calls")
EXPECTED_PROJECTION_DIFFS = sorted(
    [".".join(keys) for keys in PATH_PROJECTION_LEAVES + (DETECT_PROJECTION_LEAF,)]
)


def _require_resolved_identity(
    record: object, expected: Mapping[str, object], label: str
) -> dict[str, object]:
    if not isinstance(record, Mapping) or set(record) != {"path", "sha256", "size_bytes"}:
        raise XFeatContinuationError(f"{label}_CLAIM_INVALID")
    raw_path = record.get("path")
    if not isinstance(raw_path, str) or not raw_path.startswith(str(ROOT / "external_tools")):
        raise XFeatContinuationError(f"{label}_LEXICAL_WORKSPACE_PATH_INVALID")
    actual = identity(Path(raw_path), label)
    if (
        record.get("sha256") != actual["sha256"]
        or record.get("size_bytes") != actual["size_bytes"]
        or Path(raw_path).resolve(strict=True) != Path(str(actual["path"]))
        or actual != dict(expected)
    ):
        raise XFeatContinuationError(f"{label}_RESOLVED_IDENTITY_MISMATCH")
    return actual


def build_xfeat_compatibility_projection(
    manifest: Mapping[str, object],
) -> tuple[dict[str, object], dict[str, object]]:
    """Validate actual runtime facts, then build the exact six-leaf projection."""

    diagnostics = _nested_get(manifest, ("raw_frame_diagnostics",))
    runtime = _nested_get(manifest, ("code_artifacts", "detector", "runtime"))
    detect_stage = _nested_get(manifest, ("runtime_profile", "stages", "detect"))
    detect_ms = _nested_get(manifest, ("code_artifacts", "detector", "runtime", "detect_ms"))
    if not isinstance(diagnostics, list) or len(diagnostics) != RAW_FRAME_COUNT:
        raise XFeatContinuationError("XFEAT_ACTUAL_RAW_FRAME_DIAGNOSTIC_COUNT_MISMATCH")
    if (
        not isinstance(runtime, Mapping)
        or not isinstance(detect_stage, Mapping)
        or not isinstance(detect_ms, Mapping)
    ):
        raise XFeatContinuationError("XFEAT_ACTUAL_RUNTIME_RECORD_INVALID")
    detect_all = detect_ms.get("all")
    detect_warmup = detect_ms.get("warmup")
    detect_steady = detect_ms.get("steady_state")
    tracked_refill_calls = sum(
        isinstance(row, Mapping) and row.get("tracked_after", 10**9) < 350
        for row in diagnostics
    )
    candidate_calls = sum(
        isinstance(row, Mapping) and row.get("detector_candidates", 0) > 0
        for row in diagnostics
    )
    if (
        runtime.get("detect_calls") != ACTUAL_DETECT_CALLS
        or detect_stage.get("count") != ACTUAL_DETECT_CALLS
        or tracked_refill_calls != ACTUAL_DETECT_CALLS
        or candidate_calls != ACTUAL_DETECT_CALLS
        or not isinstance(detect_all, Mapping)
        or detect_all.get("count") != ACTUAL_DETECT_CALLS
        or not isinstance(detect_warmup, Mapping)
        or detect_warmup.get("count") != 1
        or not isinstance(detect_steady, Mapping)
        or detect_steady.get("count") != ACTUAL_DETECT_CALLS - 1
        or _nested_get(manifest, ("metrics", "raw_frames_processed")) != RAW_FRAME_COUNT
        or _nested_get(manifest, ("metrics", "published_frames")) != PUBLISHED_FRAME_COUNT
        or _nested_get(manifest, ("prefix", "selected_published_frames")) != PUBLISHED_FRAME_COUNT
    ):
        raise XFeatContinuationError("XFEAT_ACTUAL_DETECT_CALL_DERIVATION_MISMATCH")

    projection = copy.deepcopy(dict(manifest))
    resolved_claims: dict[str, dict[str, object]] = {}
    official = v1.validate_xfeat_official_closure()["files"]
    official_by_leaf = {
        PATH_PROJECTION_LEAVES[0]: official["external_tools/accelerated_features/modules/interpolator.py"],
        PATH_PROJECTION_LEAVES[1]: official["external_tools/accelerated_features/modules/model.py"],
        PATH_PROJECTION_LEAVES[2]: official["external_tools/accelerated_features/weights/xfeat.pt"],
        PATH_PROJECTION_LEAVES[3]: official["external_tools/accelerated_features/modules/xfeat.py"],
        PATH_PROJECTION_LEAVES[4]: official["external_tools/accelerated_features/LICENSE"],
    }
    for keys in PATH_PROJECTION_LEAVES:
        claim = _nested_get(manifest, keys[:-1])
        checked = _require_resolved_identity(
            claim, official_by_leaf[keys], "XFEAT_" + "_".join(keys[2:-1]).upper()
        )
        resolved_claims[".".join(keys[:-1])] = checked
        _nested_set(projection, keys, checked["path"])
    # This value exists only long enough to invoke the frozen legacy validator.
    # The returned evidence below records only the observed value 1562 and the
    # identity of the projected field, never 900 as an observed fact.
    _nested_set(projection, DETECT_PROJECTION_LEAF, PUBLISHED_FRAME_COUNT)
    differences = recursive_leaf_diff(manifest, projection)
    if differences != EXPECTED_PROJECTION_DIFFS:
        raise XFeatContinuationError(f"XFEAT_COMPATIBILITY_PROJECTION_NOT_SIX_LEAVES:{differences}")
    proof = {
        "status": "PASS_ACTUAL_1562_SELF_CONSISTENT",
        "actual_detect_calls": ACTUAL_DETECT_CALLS,
        "raw_frame_diagnostic_count": RAW_FRAME_COUNT,
        "refill_condition_count": tracked_refill_calls,
        "positive_detector_candidate_count": candidate_calls,
        "runtime_profile_detect_count": detect_stage["count"],
        "detector_runtime_all_count": detect_all["count"],
        "detector_runtime_warmup_count": detect_warmup["count"],
        "detector_runtime_steady_state_count": detect_steady["count"],
        "published_frame_count": PUBLISHED_FRAME_COUNT,
        "resolved_identity_equivalence": resolved_claims,
        "compatibility_projection_leaf_paths": differences,
        "compatibility_projection_written_to_disk": False,
    }
    return projection, proof


def load_xfeat_manifest_compatibility(
    path: Path, label: str
) -> tuple[dict[str, object], dict[str, object]]:
    if label != "XFEAT_EXPORT_MANIFEST":
        return v2_1.load_canonical_json_v2(path, label)
    manifest, manifest_identity = _ORIGINAL_LOAD(path, label)
    if (
        path.resolve(strict=True) != v2_3.XFEAT_MANIFEST.resolve(strict=True)
        or manifest_identity["sha256"] != EXPECTED_XFEAT_MANIFEST_SHA256
        or manifest_identity["size_bytes"] != EXPECTED_XFEAT_MANIFEST_SIZE
    ):
        raise XFeatContinuationError("XFEAT_COMPATIBILITY_REQUIRES_EXACT_V2_3_MANIFEST")
    projection, _proof = build_xfeat_compatibility_projection(manifest)
    return projection, manifest_identity


def validate_xfeat_chain_v2_4(**kwargs: object) -> dict[str, object]:
    manifest_path = Path(str(kwargs["manifest_path"]))
    manifest, manifest_identity = _ORIGINAL_LOAD(
        manifest_path, "V2_4_ACTUAL_XFEAT_EXPORT_MANIFEST"
    )
    if (
        manifest_identity["sha256"] != EXPECTED_XFEAT_MANIFEST_SHA256
        or manifest_identity["size_bytes"] != EXPECTED_XFEAT_MANIFEST_SIZE
    ):
        raise XFeatContinuationError("V2_4_XFEAT_MANIFEST_IDENTITY_MISMATCH")
    _projection, proof = build_xfeat_compatibility_projection(manifest)
    prior_loader = v1.load_canonical_json
    v1.load_canonical_json = load_xfeat_manifest_compatibility
    try:
        result = _ORIGINAL_XFEAT_VALIDATOR(**kwargs)
    finally:
        v1.load_canonical_json = prior_loader
    if result.get("status") != "PASS":
        raise XFeatContinuationError("V2_4_LEGACY_XFEAT_CHAIN_NOT_PASS_AFTER_NARROW_PROJECTION")
    result = dict(result)
    runtime_contract = dict(result.get("detector_runtime_contract", {}))
    runtime_contract["detect_calls"] = ACTUAL_DETECT_CALLS
    runtime_contract["detect_calls_observation_basis"] = (
        "manifest_runtime_equals_runtime_profile_equals_two_raw_frame_diagnostic_counts"
    )
    result["detector_runtime_contract"] = runtime_contract
    result["manifest_identity"] = manifest_identity
    result["v2_4_compatibility_proof"] = proof
    return result


def old_v2_3_terminal_recomputation() -> dict[str, object]:
    record = v2_3.build_terminal_record(v2_3.DEFAULT_FREEZE)
    payload = v1.canonical_json(record)
    actual, actual_identity = v1.read_regular(
        v2_3.TERMINAL_EVIDENCE, "V2_4_V2_3_TERMINAL"
    )
    if (
        actual != payload
        or actual_identity["sha256"] != EXPECTED_V2_3_TERMINAL_SHA256
        or record.get("status") != v2_3.TERMINAL_FAIL
        or record.get("arms", {}).get("B1_CONSTQ", {}).get("status") != "PASS"
        or record.get("arms", {}).get("XFEATBIRTH_RAWLK", {}).get("status") != "FAIL"
        or record.get("arms", {}).get("HFNET_WHOLE_SYSTEM", {}).get("status") != "FAIL"
        or record.get("terminal_outcome", {}).get("component_process_receipts", {})
        .get("XFEATBIRTH_RAWLK", {}).get("record", {}).get("actual_process_start_count") != 0
    ):
        raise XFeatContinuationError("V2_4_V2_3_TERMINAL_NOT_BYTE_RECOMPUTABLE_OR_SKIP_NOT_ZERO")
    return {"status": "PASS_BYTE_RECOMPUTABLE", "identity": actual_identity}


def current_carry_forward() -> dict[str, object]:
    b1_receipt = identity(v2_3.B1_RUN / "process_rc_receipt.json", "V2_4_B1_RECEIPT")
    old_skip = v2_3.tree_record(v2_3.XFEAT_RUN, "V2_4_OLD_XFEAT_SKIP_TREE")
    regular = [entry for entry in old_skip["entries"] if entry.get("type") == "regular"]
    if (
        len(old_skip["entries"]) != 2
        or len(regular) != 1
        or regular[0].get("relative_path") != "process_rc_receipt.json"
    ):
        raise XFeatContinuationError("V2_4_OLD_XFEAT_SKIP_NOT_SINGLETON_RECEIPT_TREE")
    old_skip_record, old_skip_identity = _ORIGINAL_LOAD(
        v2_3.XFEAT_RUN / "process_rc_receipt.json", "V2_4_OLD_XFEAT_SKIP_RECEIPT"
    )
    if old_skip_record != v2_3.build_receipt_v2_3("XFEATBIRTH_RAWLK", 125, False):
        raise XFeatContinuationError("V2_4_OLD_XFEAT_SKIP_RECEIPT_NOT_EXACT_RC125_START0")
    old_skip = dict(old_skip)
    old_skip["receipt_identity"] = old_skip_identity
    old_skip["receipt_record"] = old_skip_record
    old_skip["semantic_interpretation"] = {
        "algorithm_process_start_count": 0,
        "classification": "DEPENDENCY_SKIP_NOT_ALGORITHM_ATTEMPT",
    }
    result = {
        "v2_3_freeze": identity(v2_3.DEFAULT_FREEZE, "V2_4_V2_3_FREEZE"),
        "v2_3_terminal": identity(v2_3.TERMINAL_EVIDENCE, "V2_4_V2_3_TERMINAL_ID"),
        "corrected_quality_audit": identity(v2_3.CORRECTED_AUDIT, "V2_4_CORRECTED_AUDIT"),
        "b1_run_tree": v2_3.tree_record(v2_3.B1_RUN, "V2_4_B1_RUN_TREE"),
        "b1_receipt": b1_receipt,
        "b1_vio": identity(v2_3.B1_VIO, "V2_4_B1_VIO"),
        "b1_log": identity(v2_3.B1_LOG, "V2_4_B1_LOG"),
        "xfeat_export_tree": v2_3.tree_record(v2_3.XFEAT_ROOT, "V2_4_XFEAT_EXPORT_TREE"),
        "xfeat_bag": identity(v2_3.XFEAT_BAG, "V2_4_XFEAT_BAG"),
        "xfeat_manifest": identity(v2_3.XFEAT_MANIFEST, "V2_4_XFEAT_MANIFEST"),
        "xfeat_audit": identity(v2_3.XFEAT_AUDIT, "V2_4_XFEAT_AUDIT"),
        "old_xfeat_dependency_skip_tree": old_skip,
    }
    if (
        result["v2_3_freeze"]["sha256"] != EXPECTED_V2_3_FREEZE_SHA256
        or result["v2_3_terminal"]["sha256"] != EXPECTED_V2_3_TERMINAL_SHA256
        or result["b1_receipt"]["sha256"] != EXPECTED_B1_RECEIPT_SHA256
        or result["b1_vio"]["sha256"] != EXPECTED_B1_VIO_SHA256
        or result["b1_log"]["sha256"] != EXPECTED_B1_LOG_SHA256
        or result["xfeat_bag"]["sha256"] != EXPECTED_XFEAT_BAG_SHA256
        or result["xfeat_bag"]["size_bytes"] != EXPECTED_XFEAT_BAG_SIZE
        or result["xfeat_manifest"]["sha256"] != EXPECTED_XFEAT_MANIFEST_SHA256
        or result["xfeat_audit"]["sha256"] != EXPECTED_XFEAT_AUDIT_SHA256
        or result["xfeat_audit"]["size_bytes"] != EXPECTED_XFEAT_AUDIT_SIZE
        or old_skip["receipt_identity"]["sha256"] != EXPECTED_OLD_XFEAT_SKIP_RECEIPT_SHA256
        or old_skip["semantic_interpretation"]["algorithm_process_start_count"] != 0
    ):
        raise XFeatContinuationError("V2_4_CARRY_FORWARD_IDENTITY_OR_SKIP_SEMANTICS_MISMATCH")
    return result


def expected_incident_record() -> dict[str, object]:
    carry = current_carry_forward()
    manifest, _identity = _ORIGINAL_LOAD(v2_3.XFEAT_MANIFEST, "V2_4_INCIDENT_MANIFEST")
    _projection, proof = build_xfeat_compatibility_projection(manifest)
    return {
        "schema_version": INCIDENT_SCHEMA,
        "status": INCIDENT_STATUS,
        "scientific_role": "POST_STOP_EXPLORATORY_INFRASTRUCTURE_FALSE_NEGATIVE_NOT_A_RESULT",
        "v2_3_terminal": carry["v2_3_terminal"],
        "v2_3_fixed_order_completed": True,
        "v2_3_must_not_resume_or_retry": True,
        "b1_component_arm": {
            "status": "PASS",
            "immutable_receipt": carry["b1_receipt"],
            "immutable_vio": carry["b1_vio"],
            "immutable_log": carry["b1_log"],
        },
        "xfeat_producer_and_audit": {
            "producer_rerun_forbidden": True,
            "audit_rerun_forbidden": True,
            "bag": carry["xfeat_bag"],
            "manifest": carry["xfeat_manifest"],
            "audit": carry["xfeat_audit"],
            "scientific_artifacts_passed_independent_audit": True,
        },
        "xfeat_vins_v2_3": {
            "algorithm_process_start_count": 0,
            "dependency_skip_receipt": carry["old_xfeat_dependency_skip_tree"]["receipt_identity"],
            "classification": "DEPENDENCY_SKIP_NOT_ALGORITHM_ATTEMPT",
        },
        "root_cause": {
            "classification": "LEGACY_XFEAT_MANIFEST_VALIDATOR_FALSE_NEGATIVE",
            "actual_runtime_contract": proof,
            "bad_legacy_comparison": "detector_calls_was_compared_to_published_frames",
            "lexical_alias_count": 5,
            "lexical_aliases_resolve_to_byte_identical_targets": True,
            "manifest_or_bag_modified_by_diagnosis": False,
        },
        "continuation_boundary": {
            "additive_not_v2_3_resume": True,
            "only_never_started_xfeat_vins_may_start_once": True,
            "b1_xfeat_producer_auditor_hfnet_bridge_common_support_evaluator_forbidden": True,
            "runner_native_single_arm_descriptive_report_is_inherent_not_a_common_support_comparison": True,
            "hfnet_remains_immutable_unusable_and_excluded": True,
            "ranking_forbidden": True,
        },
    }


def receipt_contract_v2_4(label: str) -> dict[str, object]:
    if label == "B1_CONSTQ":
        return v2_3.receipt_contract_v2_3(label)
    if label != "XFEATBIRTH_RAWLK":
        raise XFeatContinuationError(f"V2_4_UNKNOWN_ARM:{label}")
    return {
        "run_dir": XFEAT_RUN,
        "feature_bag": XFEAT_FEATURE_BAG_CANONICAL,
        "port": XFEAT_PORT,
        "tag": XFEAT_TAG,
    }


def build_receipt_v2_4(return_code: int, started: bool) -> dict[str, object]:
    if isinstance(return_code, bool) or not 0 <= return_code <= 255:
        raise XFeatContinuationError("V2_4_RECEIPT_RETURN_CODE_INVALID")
    if not started:
        raise XFeatContinuationError("V2_4_ONLY_ACTUAL_XFEAT_PROCESS_MAY_BE_RECEIPTED")
    contract = receipt_contract_v2_4("XFEATBIRTH_RAWLK")
    return {
        "schema_version": RECEIPT_SCHEMA,
        "status": "PASS_ACTUAL_PROCESS_RC0" if return_code == 0 else "FAIL_ACTUAL_PROCESS_NONZERO",
        "arm": "XFEATBIRTH_RAWLK",
        "return_code": return_code,
        "algorithm_started": True,
        "actual_process_start_count": 1,
        "attempt_count": 1,
        "no_retry": True,
        "run_dir": str(Path(contract["run_dir"]).absolute()),
        "feature_bag": str(Path(contract["feature_bag"]).absolute()),
        "port": contract["port"],
        "tag": contract["tag"],
        "runner": {"path": str(v1.RUNNER), "sha256": v1.RUNNER_SHA256},
        "continuation_generation": "v2.4_xfeat_vins_only",
    }


def validate_receipt_v2_4(run_dir: Path, label: str) -> dict[str, object]:
    if label == "B1_CONSTQ":
        return v2_3.validate_receipt_v2_3(run_dir, label)
    if label != "XFEATBIRTH_RAWLK" or run_dir.resolve(strict=False) != XFEAT_RUN.resolve(strict=False):
        raise XFeatContinuationError("V2_4_XFEAT_RECEIPT_RUN_BINDING_MISMATCH")
    receipt, receipt_identity = _ORIGINAL_LOAD(
        run_dir / "process_rc_receipt.json", "V2_4_XFEAT_PROCESS_RECEIPT"
    )
    if receipt != build_receipt_v2_4(0, True):
        raise XFeatContinuationError("V2_4_XFEAT_RECEIPT_NOT_EXACT_ACTUAL_RC0")
    return receipt_identity


def observe_new_receipt() -> dict[str, object]:
    path = XFEAT_RUN / "process_rc_receipt.json"
    try:
        record, record_identity = _ORIGINAL_LOAD(path, "V2_4_OBSERVED_XFEAT_RECEIPT")
    except (OSError, ValueError, v1.VerificationError) as error:
        return {"status": "MISSING_OR_INVALID", "reason": str(error)}
    return_code = record.get("return_code") if isinstance(record, Mapping) else None
    try:
        expected = build_receipt_v2_4(return_code, True)
    except (TypeError, ValueError, v1.VerificationError) as error:
        return {"status": "MISSING_OR_INVALID", "reason": str(error)}
    if record != expected:
        return {
            "status": "MISSING_OR_INVALID",
            "reason": "V2_4_OBSERVED_XFEAT_RECEIPT_NOT_EXACT",
        }
    return {"status": "OBSERVED", "identity": record_identity, "record": record}


def injected_v1_arguments(argv: Sequence[str]) -> list[str]:
    fixed = {
        "--b1-quality-audit": v2_3.CORRECTED_AUDIT,
        "--xfeat-bag": v2_3.XFEAT_BAG,
        "--xfeat-manifest": v2_3.XFEAT_MANIFEST,
        "--xfeat-audit": v2_3.XFEAT_AUDIT,
        "--b1": v2_3.B1_VIO,
        "--b1-log": v2_3.B1_LOG,
        "--xfeat": XFEAT_VIO,
        "--xfeat-log": XFEAT_LOG,
        "--evidence": TERMINAL_EVIDENCE,
    }
    for token in argv:
        if token in fixed or any(token.startswith(option + "=") for option in fixed):
            raise XFeatContinuationError(f"V2_4_FIXED_ARGUMENT_CONFLICT:{token}")
    result = list(argv)
    for option, value in fixed.items():
        result.extend([option, str(value)])
    return result


def _assert_old_protocols_immutable() -> None:
    v2_3._assert_v1_immutable()
    if v1.load_canonical_json is not _ORIGINAL_LOAD:
        raise XFeatContinuationError("V2_4_V1_LOADER_LEFT_PATCHED")


def _build_component_base_record() -> dict[str, object]:
    args = v1.parser().parse_args(injected_v1_arguments(["--action", "check"]))
    prior_loader = v1.load_canonical_json
    prior_quality = v1.validate_quality_chain
    prior_xfeat = v1.validate_xfeat_chain
    prior_contract = v1.vins_process_receipt_contract
    prior_receipt = v1.validate_vins_process_receipt
    _assert_old_protocols_immutable()
    v1.load_canonical_json = v2_1.load_canonical_json_v2
    v1.validate_quality_chain = v2_3.validate_quality_chain_v2_3
    v1.validate_xfeat_chain = validate_xfeat_chain_v2_4
    v1.vins_process_receipt_contract = receipt_contract_v2_4
    v1.validate_vins_process_receipt = validate_receipt_v2_4
    try:
        return v1.build_record(args)
    finally:
        v1.load_canonical_json = prior_loader
        v1.validate_quality_chain = prior_quality
        v1.validate_xfeat_chain = prior_xfeat
        v1.vins_process_receipt_contract = prior_contract
        v1.validate_vins_process_receipt = prior_receipt
        _assert_old_protocols_immutable()


def expected_static_paths() -> dict[str, Path]:
    paths = {f"v2_3_{label}": path for label, path in v2_3.expected_static_paths().items()}
    paths.update(
        {
            "v2_3_freeze": v2_3.DEFAULT_FREEZE,
            "v2_3_terminal": v2_3.TERMINAL_EVIDENCE,
            "v2_4_addendum": DEFAULT_ADDENDUM,
            "v2_4_builder": DEFAULT_BUILDER,
            "v2_4_incident": DEFAULT_INCIDENT,
            "v2_4_tests": DEFAULT_TESTS,
            "v2_4_verifier": DEFAULT_VERIFIER,
        }
    )
    return paths


def project_python_prefix() -> str:
    return v1.sealed_evaluation_python_prefix()


def verifier_command(action: str) -> str:
    return (
        f"{project_python_prefix()} scripts/verify_a02_xfeat_vins_continuation_v2_4.py "
        f"--revision-freeze {DEFAULT_FREEZE} --action {action}"
    )


def expected_commands() -> list[str]:
    prefix = project_python_prefix()
    start = (
        f"{prefix} scripts/build_a02_xfeat_vins_continuation_freeze_v2_4.py --action check && "
        f"{verifier_command('check-continuation-start')} || exit 42"
    )
    input_gate = (
        f"{verifier_command('check-static')} && {verifier_command('check-xfeat-input')} "
        "|| exit 42"
    )
    replay = (
        "gate_rc=0; "
        f"{verifier_command('check-static')} && {verifier_command('check-xfeat-input')} "
        "|| gate_rc=$?; if [ \"$gate_rc\" -ne 0 ]; then exit 42; fi; "
        "xfeat_vins_rc=73; xfeat_started=0; "
        f"if [ ! -e {XFEAT_RUN} ]; then /usr/bin/mkdir {XFEAT_RUN} || exit 73; "
        f"xfeat_started=1; xfeat_vins_rc=0; {v2_3._vins_invocation(XFEAT_FEATURE_BAG_CANONICAL, XFEAT_PORT, XFEAT_TAG)} "
        "|| xfeat_vins_rc=$?; fi; receipt_rc=0; "
        f"{prefix} scripts/verify_a02_xfeat_vins_continuation_v2_4.py "
        f"--revision-freeze {DEFAULT_FREEZE} --action seal-arm-rc "
        "--return-code \"$xfeat_vins_rc\" --started \"$xfeat_started\" || receipt_rc=$?; "
        "printf 'V2_4_XFEAT_VINS_RC=%s\\n' \"$xfeat_vins_rc\"; "
        "printf 'V2_4_XFEAT_RECEIPT_RC=%s\\n' \"$receipt_rc\"; "
        "if [ \"$receipt_rc\" -ne 0 ]; then exit \"$receipt_rc\"; fi; exit \"$xfeat_vins_rc\""
    )
    terminal = (
        f"terminal_seal_rc=0; {verifier_command('seal-terminal')} || terminal_seal_rc=$?; "
        "terminal_check_rc=2; "
        f"if [ -e {TERMINAL_EVIDENCE} ]; then terminal_check_rc=0; "
        f"{verifier_command('check-terminal')} || terminal_check_rc=$?; fi; "
        "printf 'V2_4_TERMINAL_SEAL_RC=%s\\n' \"$terminal_seal_rc\"; "
        "printf 'V2_4_TERMINAL_CHECK_RC=%s\\n' \"$terminal_check_rc\"; "
        "if [ \"$terminal_seal_rc\" -eq 0 ] && [ \"$terminal_check_rc\" -eq 0 ]; then "
        "echo V2_4_XFEAT_VINS_EVIDENCE_SEALED_STATUS_IN_JSON_NO_RANKING; exit 0; "
        "else echo V2_4_XFEAT_VINS_TERMINAL_GATE_FAILED; exit 2; fi"
    )
    commands = [start, input_gate, replay, terminal]
    joined = "\n".join(commands)
    forbidden = (
        "export_xfeat_lk_carrier_v1.py",
        "audit_xfeat_lk_carrier_v1.py",
        "audit_quality_partition.py",
        "agent_qi_calibration_rewrite_bag.py",
        "run_a02_b1_klt_nativeq_current_exporter_guarded",
        v2_3.B1_TAG,
        "run_hfnet_slam_a02_long1801_headless_v4.py",
        "bridge_hfnet_world_body_to_vins_csv_v1.py",
        "evaluate_vins_common_support.py",
        str(v2_3.XFEAT_RUN),
    )
    if any(token in joined for token in forbidden):
        raise XFeatContinuationError("V2_4_COMMAND_PROTOCOL_FORBIDDEN_TOKEN")
    return commands


def compatibility_contract() -> dict[str, object]:
    return {
        "exact_manifest_sha256": EXPECTED_XFEAT_MANIFEST_SHA256,
        "actual_detect_calls": ACTUAL_DETECT_CALLS,
        "actual_detect_calls_derivation_fields": [
            "code_artifacts.detector.runtime.detect_calls",
            "runtime_profile.stages.detect.count",
            "code_artifacts.detector.runtime.detect_ms.all.count",
            "code_artifacts.detector.runtime.detect_ms.warmup.count + steady_state.count",
            "count(raw_frame_diagnostics.tracked_after < 350)",
            "count(raw_frame_diagnostics.detector_candidates > 0)",
        ],
        "resolved_path_alias_leaf_count": 5,
        "in_memory_projection_leaf_count": 6,
        "projection_written_to_disk": False,
        "manifest_bag_or_audit_modified": False,
        "all_nonprojected_legacy_checks_preserved": True,
    }


def terminal_contract() -> dict[str, object]:
    return {
        "schema_version": TERMINAL_SCHEMA,
        "evidence_path": str(TERMINAL_EVIDENCE),
        "only_xfeat_vins_may_be_newly_executed": True,
        "b1_is_immutable_pass_carry_forward": True,
        "hfnet_is_immutable_unusable_excluded": True,
        "descriptive_two_component_comparison_eligible_requires_both_vins_usable": True,
        "ranking_performed": False,
        "common_support_evaluator_run": False,
        "superiority_claim_allowed": False,
    }


def validate_revision(path: Path, *, require_reserved_absent: bool) -> dict[str, object]:
    freeze, freeze_identity = _ORIGINAL_LOAD(path, "V2_4_FREEZE")
    expected_keys = {
        "schema_version", "status", "working_directory", "scientific_role",
        "incident", "protocol_history", "v2_3_terminal_carry_forward",
        "reserved_paths_absent_at_freeze", "compatibility_contract",
        "terminal_contract", "execution_policy", "command_labels", "commands",
        "required_static_identities",
    }
    if (
        set(freeze) != expected_keys
        or freeze.get("schema_version") != FREEZE_SCHEMA
        or freeze.get("status") != FREEZE_STATUS
        or freeze.get("working_directory") != str(ROOT)
        or freeze.get("scientific_role") != SCIENTIFIC_ROLE
    ):
        raise XFeatContinuationError("V2_4_FREEZE_SCHEMA_STATUS_ROLE_CWD_MISMATCH")
    v2_3.validate_revision(v2_3.DEFAULT_FREEZE, require_reserved_absent=False)
    static = freeze.get("required_static_identities")
    paths = expected_static_paths()
    if not isinstance(static, Mapping) or set(static) != set(paths):
        raise XFeatContinuationError("V2_4_STATIC_IDENTITY_KEYSET_MISMATCH")
    for label, expected_path in paths.items():
        checked = require_identity(static[label], f"V2_4_STATIC_{label}")
        if checked["path"] != str(expected_path.resolve(strict=True)):
            raise XFeatContinuationError(f"V2_4_STATIC_PATH_MISMATCH:{label}")
    incident, incident_identity = _ORIGINAL_LOAD(DEFAULT_INCIDENT, "V2_4_INCIDENT")
    if incident != expected_incident_record() or freeze.get("incident") != incident_identity:
        raise XFeatContinuationError("V2_4_INCIDENT_OR_BINDING_MISMATCH")
    history = freeze.get("protocol_history")
    if history != [
        {
            "protocol": "v2.3",
            "status": "FIXED_ORDER_COMPLETED_TERMINAL_NOT_RESUMED",
            "freeze": static["v2_3_freeze"],
            "terminal": static["v2_3_terminal"],
        },
        {
            "protocol": "v2.4",
            "status": "FROZEN_NOT_EXECUTED",
            "incident": incident_identity,
        },
    ]:
        raise XFeatContinuationError("V2_4_PROTOCOL_HISTORY_MISMATCH")
    carry = current_carry_forward()
    if freeze.get("v2_3_terminal_carry_forward") != carry:
        raise XFeatContinuationError("V2_4_TERMINAL_CARRY_FORWARD_DRIFT")
    if freeze.get("reserved_paths_absent_at_freeze") != RESERVED_PATHS:
        raise XFeatContinuationError("V2_4_RESERVED_PATH_SET_MISMATCH")
    if freeze.get("compatibility_contract") != compatibility_contract():
        raise XFeatContinuationError("V2_4_COMPATIBILITY_CONTRACT_MISMATCH")
    if freeze.get("terminal_contract") != terminal_contract():
        raise XFeatContinuationError("V2_4_TERMINAL_CONTRACT_MISMATCH")
    if freeze.get("command_labels") != ["38R4", "39C4", "40C4", "41C4"]:
        raise XFeatContinuationError("V2_4_COMMAND_LABELS_MISMATCH")
    if freeze.get("commands") != expected_commands():
        raise XFeatContinuationError("V2_4_COMMAND_PROTOCOL_MISMATCH")
    if freeze.get("execution_policy") != {
        "fixed_order": True,
        "formal_commands_executed_by_builder": False,
        "global_identity_or_input_gate_failure_stops_before_xfeat_vins": True,
        "xfeat_vins_scientific_failure_is_terminal_and_not_retried": True,
        "new_xfeat_vins_actual_process_start_limit": 1,
        "no_retry": True,
        "single_writer_working_directory": str(ROOT),
        "producer_auditor_b1_hfnet_bridge_common_support_evaluator_forbidden": True,
        "runner_native_single_arm_descriptive_report_allowed": True,
        "ranking_performed": False,
    }:
        raise XFeatContinuationError("V2_4_EXECUTION_POLICY_MISMATCH")
    if require_reserved_absent:
        require_paths_absent(RESERVED_PATHS, "V2_4_RESERVED_PATH_PRESENT")
    if v2_3.EMPTY_PYCACHE_PREFIX.exists() or v2_3.EMPTY_PYCACHE_PREFIX.is_symlink():
        raise XFeatContinuationError("V2_4_PYCACHE_PREFIX_PRESENT")
    _assert_old_protocols_immutable()
    result = {
        "status": "PASS_V2_4_CONTINUATION_START" if require_reserved_absent else "PASS_V2_4_STATIC",
        "revision_freeze": freeze_identity,
        "reserved_path_count": len(RESERVED_PATHS),
        "static_identity_count": len(static),
        "v2_3_terminal_recomputation": old_v2_3_terminal_recomputation(),
    }
    if require_reserved_absent:
        result["xfeat_input_compatibility"] = validate_xfeat_chain_v2_4(
            source_bag=v1.DEFAULT_B1_CONSTQ_BAG,
            raw_bag=v1.DEFAULT_WINDOW_BAG,
            camera_yaml=v1.DEFAULT_B1_NATIVE_CAMERA,
            output_bag=v2_3.XFEAT_BAG,
            manifest_path=v2_3.XFEAT_MANIFEST,
            audit_path=v2_3.XFEAT_AUDIT,
        )
    return result


def continuation_binding(path: Path) -> dict[str, object]:
    freeze, freeze_identity = _ORIGINAL_LOAD(path, "V2_4_BINDING_FREEZE")
    verifier_identity = identity(DEFAULT_VERIFIER, "V2_4_BINDING_VERIFIER")
    if freeze.get("required_static_identities", {}).get("v2_4_verifier") != verifier_identity:
        raise XFeatContinuationError("V2_4_BINDING_VERIFIER_MISMATCH")
    return {
        "active_freeze": freeze_identity,
        "active_verifier": verifier_identity,
        "incident": freeze["incident"],
        "role": SCIENTIFIC_ROLE,
        "v2_3_terminal_not_resumed": True,
        "only_new_algorithm_attempt": "XFEATBIRTH_RAWLK_VINS",
        "compatibility_contract": compatibility_contract(),
        "no_retry": True,
    }


def build_terminal_record(path: Path) -> dict[str, object]:
    validate_revision(path, require_reserved_absent=False)
    base = _build_component_base_record()
    arms = base.get("arms")
    if not isinstance(arms, Mapping) or set(arms) != set(v1.ARM_LABELS):
        raise XFeatContinuationError("V2_4_BASE_ARM_SET_INVALID")
    if arms["B1_CONSTQ"].get("status") != "PASS":
        raise XFeatContinuationError("V2_4_IMMUTABLE_B1_CARRY_FORWARD_NOT_PASS")
    if arms["HFNET_WHOLE_SYSTEM"].get("status") != "FAIL":
        raise XFeatContinuationError("V2_4_HFNET_MUST_REMAIN_UNUSABLE_EXCLUDED")
    xfeat_usable = arms["XFEATBIRTH_RAWLK"].get("status") == "PASS"
    result = dict(base)
    result["schema_version"] = TERMINAL_SCHEMA
    result["status"] = TERMINAL_PASS if xfeat_usable else TERMINAL_FAIL
    result["scientific_role"] = SCIENTIFIC_ROLE
    result["post_incident_continuation"] = continuation_binding(path)
    result["terminal_outcome"] = {
        "component_arm_status": {
            "B1_CONSTQ": "PASS",
            "XFEATBIRTH_RAWLK": arms["XFEATBIRTH_RAWLK"].get("status"),
            "HFNET_WHOLE_SYSTEM": "EXCLUDED_IMMUTABLE_UNUSABLE",
        },
        "new_xfeat_process_receipt": observe_new_receipt(),
        "descriptive_two_component_comparison_eligible": xfeat_usable,
        "eligibility_is_not_a_comparison_result": True,
        "ranking_performed": False,
        "common_support_evaluator_run": False,
        "common_support_ranking_metrics_generated": False,
        "superiority_claim": False,
        "hfnet_rerun": False,
        "bridge_run": False,
        "producer_or_auditor_rerun": False,
        "b1_rerun": False,
        "proxy_reference_is_not_independent_ground_truth": True,
    }
    return result


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(description=__doc__)
    value.add_argument(
        "--action",
        choices=(
            "check-continuation-start", "check-static", "check-xfeat-input",
            "seal-arm-rc", "seal-terminal", "check-terminal",
        ),
        required=True,
    )
    value.add_argument("--revision-freeze", type=Path, default=DEFAULT_FREEZE)
    value.add_argument("--return-code", type=int)
    value.add_argument("--started", type=int, choices=(0, 1))
    return value


def main(argv: Sequence[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        if args.action == "check-continuation-start":
            print(json.dumps(validate_revision(args.revision_freeze, require_reserved_absent=True), sort_keys=True))
            return 0
        validate_revision(args.revision_freeze, require_reserved_absent=False)
        if args.action == "check-static":
            print(json.dumps({"status": "PASS_V2_4_STATIC"}, sort_keys=True))
            return 0
        if args.action == "check-xfeat-input":
            result = validate_xfeat_chain_v2_4(
                source_bag=v1.DEFAULT_B1_CONSTQ_BAG,
                raw_bag=v1.DEFAULT_WINDOW_BAG,
                camera_yaml=v1.DEFAULT_B1_NATIVE_CAMERA,
                output_bag=v2_3.XFEAT_BAG,
                manifest_path=v2_3.XFEAT_MANIFEST,
                audit_path=v2_3.XFEAT_AUDIT,
            )
            print(json.dumps({"status": "PASS_V2_4_XFEAT_INPUT", "lineage": result}, sort_keys=True))
            return 0
        if args.action == "seal-arm-rc":
            if args.return_code is None or args.started is None:
                raise XFeatContinuationError("V2_4_SEAL_RECEIPT_ARGUMENTS_MISSING")
            receipt_path = XFEAT_RUN / "process_rc_receipt.json"
            if receipt_path.exists() or receipt_path.is_symlink():
                raise XFeatContinuationError("V2_4_PROCESS_RECEIPT_ALREADY_EXISTS")
            if not XFEAT_RUN.is_dir() or XFEAT_RUN.is_symlink():
                raise XFeatContinuationError("V2_4_XFEAT_RUN_DIRECTORY_NOT_OWNED_REAL_DIRECTORY")
            payload = v1.canonical_json(build_receipt_v2_4(args.return_code, bool(args.started)))
            v1.write_exclusive(receipt_path, payload)
            print(json.dumps({
                "status": "SEALED_V2_4_XFEAT_PROCESS_RECEIPT",
                "evidence": str(receipt_path),
                "evidence_sha256": hashlib.sha256(payload).hexdigest(),
            }, sort_keys=True))
            return 0
        record = build_terminal_record(args.revision_freeze)
        payload = v1.canonical_json(record)
        if args.action == "seal-terminal":
            if TERMINAL_EVIDENCE.exists() or TERMINAL_EVIDENCE.is_symlink():
                raise XFeatContinuationError("V2_4_TERMINAL_EVIDENCE_ALREADY_EXISTS")
            v1.write_exclusive(TERMINAL_EVIDENCE, payload)
            status = "SEALED"
        else:
            existing, _identity = v1.read_regular(TERMINAL_EVIDENCE, "V2_4_TERMINAL_EVIDENCE")
            if existing != payload:
                raise XFeatContinuationError("V2_4_TERMINAL_EVIDENCE_DRIFT")
            status = "CHECK_PASS"
        print(json.dumps({
            "status": status,
            "scientific_status": record["status"],
            "evidence": str(TERMINAL_EVIDENCE),
            "evidence_sha256": hashlib.sha256(payload).hexdigest(),
        }, sort_keys=True))
        return 0
    except (v1.VerificationError, OSError, ValueError, json.JSONDecodeError) as error:
        print(f"VERIFICATION_BLOCKED:{error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
