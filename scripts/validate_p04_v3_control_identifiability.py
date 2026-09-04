#!/usr/bin/env python3
"""Audit whether frozen native-q v3 admits a strict common-K0 P/C control.

This validator reads only frozen method metadata and source code. It never
opens feature bags, trajectories, APE, or RPE artifacts. A PASS means the
structural decision is reproducible; it does not mean that H2 passed.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_LOCK = (
    ROOT
    / "papers/ieee_sensors_journal_experiments/"
    "method_lock_nativeq_legacy_candidate_v3.json"
)
HYBRID_PATH = ROOT / "uw_frontend/tracking/hybrid_tracker.py"
KLT_PATH = ROOT / "uw_frontend/tracking/klt_tracker.py"
REPLAYER_PATH = ROOT / "scripts/p04_nativeq_arm_replayer_v4.py"

SCHEMA_VERSION = "isj-p04-v3-control-identifiability-v1"
EXPECTED_PROTOCOL = "isj-nativeq-legacy-candidate-v3"
EXPECTED_PROFILE = "isj-nativeq-xfeat-seedchain-legacy-v3"
EXPECTED_SELECTOR = "frozen_lineage_early_seed_scan_arbitration"
EXPECTED_ADMISSION = "LK/KLT_probation_then_frozen_microburst_or_safe_fallback"

REQUIRED_LOCKED_PATHS = (
    "scripts/run_isj_nativeq_legacy_candidate.sh",
    "scripts/run_xfeat_seedchain_arbitrated_eval.sh",
    "uw_frontend/ros/export_vins_features.py",
    "uw_frontend/tracking/hybrid_tracker.py",
    "uw_frontend/tracking/klt_tracker.py",
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def display_path(path: Path) -> str:
    resolved = path.resolve()
    try:
        return resolved.relative_to(ROOT).as_posix()
    except ValueError:
        return resolved.as_posix()


def function_source(path: Path, class_name: str, function_name: str) -> str:
    text = path.read_text(encoding="utf-8")
    tree = ast.parse(text, filename=str(path))
    scope: list[ast.stmt] = tree.body
    if class_name:
        classes = [
            node
            for node in tree.body
            if isinstance(node, ast.ClassDef) and node.name == class_name
        ]
        if len(classes) != 1:
            raise ValueError(f"expected one class {class_name} in {path}")
        scope = classes[0].body
    functions = [
        node
        for node in scope
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name == function_name
    ]
    if len(functions) != 1:
        raise ValueError(
            f"expected one function {class_name}.{function_name} in {path}"
        )
    segment = ast.get_source_segment(text, functions[0])
    if not segment:
        raise ValueError(f"could not extract {class_name}.{function_name}")
    return segment


def token_check(source: str, required: tuple[str, ...]) -> tuple[bool, list[str]]:
    missing = [token for token in required if token not in source]
    return not missing, missing


def check_record(
    check_id: str,
    passed: bool,
    *,
    evidence: dict[str, Any],
    failure: str,
) -> dict[str, Any]:
    return {
        "check_id": check_id,
        "status": "PASS" if passed else "FAIL",
        "failure": "" if passed else failure,
        "evidence": evidence,
    }


def build_report(lock_path: Path = DEFAULT_LOCK) -> dict[str, Any]:
    lock = json.loads(lock_path.read_text(encoding="utf-8"))
    checks: list[dict[str, Any]] = []

    identity = lock.get("method_identity", {})
    identity_ok = (
        lock.get("protocol_version") == EXPECTED_PROTOCOL
        and identity.get("profile") == EXPECTED_PROFILE
        and identity.get("selector") == EXPECTED_SELECTOR
        and identity.get("admission") == EXPECTED_ADMISSION
    )
    checks.append(
        check_record(
            "FROZEN_V3_IDENTITY",
            identity_ok,
            evidence={
                "protocol_version": lock.get("protocol_version"),
                "profile": identity.get("profile"),
                "selector": identity.get("selector"),
                "admission": identity.get("admission"),
            },
            failure="method lock is not the expected native-q v3 identity",
        )
    )

    sampling = lock.get("shared_contract", {}).get("sampling", {})
    expected_sampling = {
        "aqualoc_archaeology": {"every_n": 2, "frame_offset": 1},
        "aqualoc_harbor": {"every_n": 2, "frame_offset": 1},
        "ntnu": {"every_n": 2, "frame_offset": 1},
        "afrl": {"every_n": 2, "frame_offset": 0},
    }
    checks.append(
        check_record(
            "FROZEN_V3_SAMPLING",
            sampling == expected_sampling,
            evidence={"sampling": sampling},
            failure="native-q v3 sampling contract drifted",
        )
    )

    artifacts = {
        str(item.get("path")): item
        for item in lock.get("artifacts", [])
        if isinstance(item, dict)
    }
    hash_results: dict[str, dict[str, Any]] = {}
    hashes_ok = True
    for relative in REQUIRED_LOCKED_PATHS:
        target = ROOT / relative
        expected = str(artifacts.get(relative, {}).get("sha256", ""))
        actual = sha256(target) if target.is_file() else ""
        passed = bool(expected) and actual == expected
        hashes_ok &= passed
        hash_results[relative] = {
            "expected_sha256": expected,
            "actual_sha256": actual,
            "status": "PASS" if passed else "FAIL",
        }
    checks.append(
        check_record(
            "FROZEN_SOURCE_HASHES",
            hashes_ok,
            evidence=hash_results,
            failure="one or more frozen v3 source hashes do not match",
        )
    )

    process_source = function_source(HYBRID_PATH, "HybridKltOrbTracker", "process")
    process_tokens = (
        "self._append_to_klt_state(learned_initialized)",
        "self._append_to_klt_state(semidense_initialized)",
        "self._append_to_klt_state(confirmed_learned)",
    )
    process_ok, process_missing = token_check(process_source, process_tokens)
    checks.append(
        check_record(
            "LEARNED_WRITES_BACK_TO_KLT_CARRIER",
            process_ok,
            evidence={
                "path": HYBRID_PATH.relative_to(ROOT).as_posix(),
                "function": "HybridKltOrbTracker.process",
                "function_sha256": hashlib.sha256(
                    process_source.encode("utf-8")
                ).hexdigest(),
                "matched_calls": list(process_tokens),
                "missing_calls": process_missing,
            },
            failure="could not prove all learned/semidense KLT write-back paths",
        )
    )

    append_source = function_source(
        HYBRID_PATH, "HybridKltOrbTracker", "_append_to_klt_state"
    )
    append_tokens = (
        "self.klt.points = np.vstack([self.klt.points, recovered.points])",
        "self.klt.ids = np.concatenate([self.klt.ids, recovered.ids])",
        "self.klt.ages = np.concatenate([self.klt.ages, recovered.ages])",
    )
    append_ok, append_missing = token_check(append_source, append_tokens)
    checks.append(
        check_record(
            "KLT_STATE_MUTATION_IS_EXPLICIT",
            append_ok,
            evidence={
                "path": HYBRID_PATH.relative_to(ROOT).as_posix(),
                "function": "HybridKltOrbTracker._append_to_klt_state",
                "function_sha256": hashlib.sha256(
                    append_source.encode("utf-8")
                ).hexdigest(),
                "missing_mutations": append_missing,
            },
            failure="KLT carrier mutation could not be reproduced from source",
        )
    )

    klt_process_source = function_source(KLT_PATH, "KltTracker", "process")
    detect_source = function_source(KLT_PATH, "KltTracker", "_detect_new")
    replenish_tokens = (
        "self.config.max_features - len(self.points)",
        "self._detect_new(gray, need_new)",
    )
    mask_tokens = (
        "for x, y in self.points.reshape(-1, 2)",
        "cv2.circle(mask",
        "self.next_id",
    )
    replenish_ok, replenish_missing = token_check(
        klt_process_source, replenish_tokens
    )
    mask_ok, mask_missing = token_check(detect_source, mask_tokens)
    checks.append(
        check_record(
            "NEXT_FRAME_KLT_DEPENDS_ON_MUTATED_STATE",
            replenish_ok and mask_ok,
            evidence={
                "path": KLT_PATH.relative_to(ROOT).as_posix(),
                "process_function_sha256": hashlib.sha256(
                    klt_process_source.encode("utf-8")
                ).hexdigest(),
                "detect_function_sha256": hashlib.sha256(
                    detect_source.encode("utf-8")
                ).hexdigest(),
                "missing_replenish_tokens": replenish_missing,
                "missing_mask_tokens": mask_missing,
            },
            failure="could not prove replenishment/mask/ID dependence on KLT state",
        )
    )

    replay_source = function_source(REPLAYER_PATH, "", "replay_master_events")
    order_source = function_source(REPLAYER_PATH, "", "_candidate_order")
    replayer_text = REPLAYER_PATH.read_text(encoding="utf-8")
    v4_tokens = (
        'B_ACTIVE = 8',
        '_ArmState(P_LEGACY, "learned", "distance_grid")',
        '_ArmState(C_LEGACY, "classical", "distance_grid")',
        'if selector != "distance_grid"',
    )
    v4_combined = "\n".join((replayer_text, replay_source, order_source))
    v4_ok, v4_missing = token_check(v4_combined, v4_tokens)
    checks.append(
        check_record(
            "V4_REPLAYER_IS_NOT_V3_ADMISSION",
            v4_ok,
            evidence={
                "path": REPLAYER_PATH.relative_to(ROOT).as_posix(),
                "replayer_sha256": sha256(REPLAYER_PATH),
                "v3_selector": identity.get("selector"),
                "v4_selector": "distance_grid",
                "v4_b_active": 8,
                "missing_tokens": v4_missing,
            },
            failure="could not establish the v4 distance/grid identity difference",
        )
    )

    all_pass = all(item["status"] == "PASS" for item in checks)
    return {
        "schema_version": SCHEMA_VERSION,
        "status": "PASS" if all_pass else "REVISE",
        "decision": (
            "STRICT_MATCHED_CLASSICAL_CONTROL_NOT_IDENTIFIABLE_UNDER_V3"
            if all_pass
            else "IDENTIFIABILITY_UNRESOLVED"
        ),
        "meaning_of_pass": (
            "The structural non-identifiability decision is reproducible; "
            "H2 itself did not pass."
        ),
        "method_lock": {
            "path": display_path(lock_path),
            "sha256": sha256(lock_path),
            "candidate_lock_hash": lock.get("candidate_lock_hash"),
        },
        "causal_chain": [
            "learned/classical confirmation changes the internal KLT state",
            "the next frame tracks and replenishes from that changed state",
            "the replenishment mask, capacity, and ID allocation therefore diverge",
            "health, trigger, and later proposal opportunity may then diverge",
            "a post-hoc source swap cannot recover a shared counterfactual K0",
        ],
        "recommended_disposition": {
            "scientific_method": "RETAIN_NATIVEQ_V3",
            "H2_CONTROL_CONTRACT": "NOT_APPLICABLE_CARRIER_FEEDBACK",
            "C_legacy_confirmatory": "RETIRE",
            "C_development_diagnostics": "RETAIN_WITHOUT_CAUSAL_LANGUAGE",
            "D_exact_drop": "RETAIN_CONDITIONAL_ON_PROPOSED_ACTIVE",
            "B2": "RETIRE_AND_NARROW_ADMISSION_SPECIFIC_CLAIM",
            "main_confirmatory_arms": ["B0", "B1", "P_legacy", "M"],
        },
        "outcome_boundary": "FROZEN_SOURCE_ONLY_NO_BAG_VINS_APE_RPE_TRAJECTORY",
        "learned_outcome_read": False,
        "trajectory_outcome_read": False,
        "checks": checks,
        "issues": [] if all_pass else [
            item["failure"] for item in checks if item["status"] != "PASS"
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--method-lock", type=Path, default=DEFAULT_LOCK)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = build_report(args.method_lock.resolve())
    rendered = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.output:
        if args.output.exists():
            raise FileExistsError(f"refusing to overwrite {args.output}")
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0 if report["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
