#!/usr/bin/env python3
"""Fail-closed five-repeat KLT-only A08 backend diversion supervisor.

Importing this module is inert.  ``preflight`` and ``audit`` are read-only.
The execution engine is the exact v1 backend supervisor, rebound in a private
module namespace to this independently locked KLT-only v2 campaign.
"""

from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import stat
import sys
from types import ModuleType
from typing import Any, Mapping, Optional, Sequence


WORKSPACE = Path("/home/ma/AQUA-FE_WS")
EXPERIMENT = Path("/mnt/data/AQUA-FE_WS/experiments/a08_history_matched_controls_v1")
OVERLAY = EXPERIMENT / "recovered_july_core_overlay_v1"
OVERLAY_RUN_ROOT = OVERLAY / "logs/aqualoc_archaeo_vins"
FRONTEND_ROOT = EXPERIMENT / "frontends_v1"
BACKEND_ROOT = EXPERIMENT / "backend_klt_only_replays_v2"
RUNTIME_ROOT = EXPERIMENT / "runtime/backend_klt_only_replays_v2"

PROTOCOL = WORKSPACE / (
    "papers/a08_recovered_july_history_matched_backend_klt_only_replays_v2_protocol.md"
)
DEFAULT_LOCK = WORKSPACE / (
    "papers/a08_recovered_july_history_matched_backend_klt_only_replays_v2_execution_lock.json"
)
RUNNER = WORKSPACE / (
    "scripts/run_a08_recovered_july_history_matched_backend_klt_only_replays_v2.py"
)
REPLAY_ONLY_GUARD = WORKSPACE / (
    "scripts/run_a08_recovered_july_history_matched_backend_klt_only_replay_guard_v2.sh"
)
BASE_RUNNER = WORKSPACE / "scripts/run_a08_recovered_july_history_matched_backend_replays_v1.py"
BASE_PROTOCOL = WORKSPACE / "papers/a08_recovered_july_history_matched_backend_replays_v1_protocol.md"
BASE_REPLAY_ONLY_GUARD = WORKSPACE / "scripts/run_a08_recovered_july_backend_replay_only_guard_v1.sh"
FORENSIC_AUDIT = WORKSPACE / "papers/a08_xfeat_attempt002_terminal_forensic_audit_v1.md"

BASE_AUTHORITY_EXPECTED = {
    "base_backend_runner_v1": (
        84_455,
        "4ca198cd678ba5df2e2b82a0468cbca3c23fbc5608302019d6540775ca58d3a0",
    ),
    "base_backend_protocol_v1": (
        10_363,
        "a8fb2b84fe9340e4ef6a04fb00c3137793b1312db6fa40d769de7cb2e8e72eb2",
    ),
    "base_replay_only_guard_v1": (
        8_704,
        "8740c0e4166e51050af287a05c67821f94a932a11f91d14c7e90059310244bcb",
    ),
}

KLT_RECEIPT = FRONTEND_ROOT / "klt_attempt002_export_receipt_v1.json"
XFEAT_ACCEPTED_RECEIPT = FRONTEND_ROOT / "xfeat_attempt002_export_receipt_v1.json"
XFEAT_FAILURE_RECEIPT = FRONTEND_ROOT / "xfeat_attempt002_export_failure_v1.json"
XFEAT_PROCESS_CLAIM = FRONTEND_ROOT / "xfeat_attempt002_process_start_claim_v1.json"
XFEAT_SUPERVISOR_LOG = FRONTEND_ROOT / "xfeat_attempt002_supervisor_process.log"

PROBE_RUN = OVERLAY_RUN_ROOT / (
    "external_hybrid_xfeat_every2_a08_recoveredjuly_hist0000_4660_"
    "oldarb_attempt002_rosseed_v1_probe_oldcontract_densecap"
)
FINAL_FALLBACK_RUN = OVERLAY_RUN_ROOT / (
    "external_klt_every2_a08_recoveredjuly_hist0000_4660_"
    "oldarb_attempt002_rosseed_v1_klt_safe_fallback"
)

EVIDENCE_PATHS = {
    "klt_receipt": KLT_RECEIPT,
    "xfeat_accepted_receipt": XFEAT_ACCEPTED_RECEIPT,
    "xfeat_failure_receipt": XFEAT_FAILURE_RECEIPT,
    "xfeat_process_start_claim": XFEAT_PROCESS_CLAIM,
    "xfeat_supervisor_log": XFEAT_SUPERVISOR_LOG,
    "probe_features_bag": PROBE_RUN / "features.bag",
    "probe_frontend_metrics": PROBE_RUN / "frontend_metrics.csv",
    "probe_camera_config": PROBE_RUN / "aqualoc_archaeo08_pinhole.yaml",
    "final_features_bag": FINAL_FALLBACK_RUN / "features.bag",
    "final_frontend_metrics": FINAL_FALLBACK_RUN / "frontend_metrics.csv",
    "final_camera_config": FINAL_FALLBACK_RUN / "aqualoc_archaeo08_pinhole.yaml",
    "forensic_audit": FORENSIC_AUDIT,
}

EVIDENCE_EXPECTED = {
    "klt_receipt": (
        363_673,
        "69a857307f088e58ea18abbb6c25cd2069b7b15783fc2d17548e1fb001c4d2b8",
    ),
    "klt_features_bag": (
        70_811_242,
        "0a33248739ec3f02df26b8f784b469afa37c6bbc172461d67b2a91a82b10843a",
    ),
    "klt_frontend_metrics": (
        1_259_980,
        "7deda4bd28a0e22b0fa87be111239df2219d2e3a00d0c34b4ac47bf9ff4ff305",
    ),
    "klt_camera_config": (
        357,
        "045505013a5dbfb629bad8d3463bbbdacad965ebdcf3c590598121bd884e50a5",
    ),
    "xfeat_failure_receipt": (
        4_017,
        "15eaad3e5b02f54b4f141db416e9b1db868bea15fcb66fe8bee11318765df22c",
    ),
    "xfeat_process_start_claim": (
        149_433,
        "a8d0828f9117c077b0bcef80b60d945478f6f2856d1dbe66bab43311d2698707",
    ),
    "xfeat_supervisor_log": (
        11_417,
        "23fc5398f991e04d6050005be4ed8c909e7ee6b98609abfc09c8cb4b522decb0",
    ),
    "probe_features_bag": (
        70_140_496,
        "fcaa39bebfe9ef9f9dbaa720386a5e05367818fba9085c9d2b81fed59d5a4541",
    ),
    "probe_frontend_metrics": (
        1_452_927,
        "3a71e46077f31e8be18b4e2c6f47875ab55b81b6f69f50a05fb10836b438462d",
    ),
    "probe_camera_config": (
        357,
        "045505013a5dbfb629bad8d3463bbbdacad965ebdcf3c590598121bd884e50a5",
    ),
    "final_features_bag": (
        70_811_242,
        "0a33248739ec3f02df26b8f784b469afa37c6bbc172461d67b2a91a82b10843a",
    ),
    "final_frontend_metrics": (
        1_259_980,
        "7deda4bd28a0e22b0fa87be111239df2219d2e3a00d0c34b4ac47bf9ff4ff305",
    ),
    "final_camera_config": (
        357,
        "045505013a5dbfb629bad8d3463bbbdacad965ebdcf3c590598121bd884e50a5",
    ),
    "forensic_audit": (
        3_695,
        "4087a9cded9617e20c4f8e383bc4280c1a1c1cafe5d9fd49fbaa9fb2005bbf5a",
    ),
}

PROBE_CONTRACT = {
    "metrics_rows": 2_330,
    "violation_count": 1,
    "zero_based_row": 3,
    "frame_index": "7",
    "timestamp": "1542884961.494887114",
    "num_features": "356",
    "exported_features": "352",
    "exported_learned_features": "2",
    "exported_xfeat_features": "2",
    "export_source_histogram": "gftt:11;klt:339;xfeat_confirmed:2",
}

ITEM_ORDER = tuple(f"KLT_R{repeat:02d}" for repeat in range(1, 6))
CLAIM_NAME = "process_start_claim_v1.json"
RECEIPT_NAME = "formal_run_receipt_v2.json"
LOCK_SCHEMA = "aqua-fe-a08-recovered-july-backend-klt-only-execution-lock-v2"
RECEIPT_SCHEMA = "aqua-fe-a08-recovered-july-backend-klt-only-replay-receipt-v2"
LOCK_STATUS = "FROZEN_KLT_ONLY_AFTER_TERMINAL_XFEAT_FAILURE_BEFORE_BACKEND_LAUNCH"
BUILD_LOCK_TOKEN = (
    "A08_BUILD_KLT_ONLY_BACKEND_REPLAYS_V2_LOCK_AFTER_TERMINAL_XFEAT_FAILURE"
)
AUTHORIZATION_TOKENS = {
    item: f"A08_KLT_ONLY_BACKEND_REPLAYS_V2_RUN_{item}_EXACTLY_ONCE"
    for item in ITEM_ORDER
}

ORIGINAL_LOCK = WORKSPACE / (
    "papers/a08_recovered_july_history_matched_backend_replays_v1_execution_lock.json"
)
ORIGINAL_BACKEND_ROOT = EXPERIMENT / "backend_replays_v1"
ORIGINAL_RUNTIME_ROOT = EXPERIMENT / "runtime/backend_replays_v1"
ORIGINAL_ITEM_ORDER = tuple(
    item
    for repeat in range(1, 6)
    for item in (f"KLT_R{repeat:02d}", f"XFEAT_R{repeat:02d}")
)


def _load_engine() -> ModuleType:
    runner = BASE_RUNNER.absolute()
    if (
        not runner.exists() or runner.is_symlink()
        or not stat.S_ISREG(runner.lstat().st_mode)
        or runner.resolve(strict=True) != runner
    ):
        raise RuntimeError("BASE_ENGINE_NOT_FROZEN_REGULAR_FILE")
    raw = runner.read_bytes()
    observed = (len(raw), hashlib.sha256(raw).hexdigest())
    if observed != BASE_AUTHORITY_EXPECTED["base_backend_runner_v1"]:
        raise RuntimeError("BASE_ENGINE_BOOTSTRAP_IDENTITY_DRIFT")
    specification = importlib.util.spec_from_file_location(
        "a08_backend_replays_v1_engine_for_klt_only_v2", runner
    )
    if specification is None or specification.loader is None:
        raise RuntimeError("BASE_ENGINE_IMPORT_SPEC")
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


ENGINE = _load_engine()
BackendProtocolError = ENGINE.BackendProtocolError
require = ENGINE.require
identity = ENGINE.identity
stable_json = ENGINE.stable_json
compact_sha256 = ENGINE.compact_sha256
current_namespace = ENGINE.current_namespace
BASE_STATIC_IDENTITY_PATHS = ENGINE.static_identity_paths
BASE_STATIC_PATHS = dict(BASE_STATIC_IDENTITY_PATHS())


def _identity_tuple(value: Mapping[str, Any]) -> tuple[int, str]:
    return int(value["size_bytes"]), str(value["sha256"])


def _expect_identity(
    path: Path, expected: Mapping[str, tuple[int, str]], label: str,
) -> dict[str, Any]:
    actual = identity(Path(path).absolute())
    require(_identity_tuple(actual) == expected[label], f"TERMINAL_IDENTITY:{label}")
    return actual


def authority_presence(
    evidence_paths: Mapping[str, Path] = EVIDENCE_PATHS,
) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for label, raw_path in evidence_paths.items():
        path = Path(raw_path).absolute()
        exists = path.exists() or path.is_symlink()
        if label == "xfeat_accepted_receipt":
            state = "FORBIDDEN_PRESENT" if exists else "ABSENT_AS_REQUIRED"
        elif not exists:
            state = "MISSING"
        elif path.is_symlink() or not stat.S_ISREG(path.lstat().st_mode):
            state = "INVALID_KIND"
        else:
            state = "PRESENT_REGULAR"
        result[label] = {"path": str(path), "state": state}
    return result


def _validate_probe_contract(
    path: Path, contract: Mapping[str, Any] = PROBE_CONTRACT,
) -> dict[str, Any]:
    with Path(path).open("r", encoding="utf-8", newline="") as stream:
        rows = list(csv.DictReader(stream))
    require(len(rows) == contract["metrics_rows"], "PROBE_METRICS_ROW_COUNT")
    violations: list[tuple[int, dict[str, str]]] = []
    for index, row in enumerate(rows):
        try:
            exported = int(row["exported_features"])
        except (KeyError, TypeError, ValueError) as error:
            raise BackendProtocolError(f"PROBE_METRICS_EXPORTED_FEATURES:{index}") from error
        if exported > 350:
            violations.append((index, row))
    require(len(violations) == contract["violation_count"], "PROBE_VIOLATION_COUNT")
    index, row = violations[0]
    exact = {
        key: row.get(key)
        for key in (
            "frame_index", "timestamp", "num_features", "exported_features",
            "exported_learned_features", "exported_xfeat_features",
            "export_source_histogram",
        )
    }
    require(index == contract["zero_based_row"], "PROBE_VIOLATION_ROW")
    require(
        all(exact[key] == contract[key] for key in exact),
        "PROBE_VIOLATION_SEMANTICS",
    )
    return {
        "metrics_rows": len(rows),
        "maximum_permitted_exported_features": 350,
        "violation_count": len(violations),
        "zero_based_row": index,
        **exact,
    }


def validate_terminal_diversion_evidence(
    klt_binding: Mapping[str, Any],
    evidence_paths: Mapping[str, Path] = EVIDENCE_PATHS,
    expected: Mapping[str, tuple[int, str]] = EVIDENCE_EXPECTED,
    probe_contract: Mapping[str, Any] = PROBE_CONTRACT,
) -> dict[str, Any]:
    require(set(evidence_paths) == set(EVIDENCE_PATHS), "EVIDENCE_PATH_KEYS")
    require(set(expected) == set(EVIDENCE_EXPECTED), "EVIDENCE_EXPECTED_KEYS")
    accepted_path = Path(evidence_paths["xfeat_accepted_receipt"])
    require(
        not accepted_path.exists() and not accepted_path.is_symlink(),
        "XFEAT_ACCEPTED_RECEIPT_FORBIDDEN",
    )

    klt_receipt = _expect_identity(evidence_paths["klt_receipt"], expected, "klt_receipt")
    require(klt_binding.get("receipt") == klt_receipt, "KLT_ACCEPTED_RECEIPT_BINDING")
    require(klt_binding.get("stage") == "klt", "KLT_ACCEPTED_STAGE")
    klt_outputs: dict[str, dict[str, Any]] = {}
    for key, label in (
        ("features_bag", "klt_features_bag"),
        ("frontend_metrics", "klt_frontend_metrics"),
        ("camera_config", "klt_camera_config"),
    ):
        claim = klt_binding.get(key)
        require(isinstance(claim, dict), f"KLT_ACCEPTED_OUTPUT:{key}")
        actual = identity(Path(str(claim.get("path", ""))))
        require(actual == claim, f"KLT_ACCEPTED_OUTPUT_DRIFT:{key}")
        require(_identity_tuple(actual) == expected[label], f"KLT_ACCEPTED_OUTPUT_ID:{key}")
        klt_outputs[key] = actual

    failure, failure_identity = stable_json(evidence_paths["xfeat_failure_receipt"])
    require(
        _identity_tuple(failure_identity) == expected["xfeat_failure_receipt"],
        "XFEAT_FAILURE_RECEIPT_IDENTITY",
    )
    require(
        failure.get("schema_version") == "aqua-fe-a08-recovered-july-frontend-failure-v1"
        and failure.get("status") == "FAILED_NO_AUTOMATIC_RETRY"
        and failure.get("qualified_status") == "FAILED_ATTEMPT002_NO_FURTHER_ATTEMPT"
        and failure.get("stage") == "xfeat"
        and failure.get("error") == "FEATURE_POINT_COUNT_RANGE"
        and failure.get("vins_or_accuracy_executed") is False
        and failure.get("popen_started") is True,
        "XFEAT_FAILURE_SEMANTICS",
    )
    process_claim = _expect_identity(
        evidence_paths["xfeat_process_start_claim"], expected,
        "xfeat_process_start_claim",
    )
    supervisor_log = _expect_identity(
        evidence_paths["xfeat_supervisor_log"], expected, "xfeat_supervisor_log"
    )
    require(failure.get("process_start_claim") == process_claim, "XFEAT_FAILURE_CLAIM_BINDING")
    require(failure.get("log") == supervisor_log, "XFEAT_FAILURE_LOG_BINDING")

    probe = {
        "features_bag": _expect_identity(
            evidence_paths["probe_features_bag"], expected, "probe_features_bag"
        ),
        "frontend_metrics": _expect_identity(
            evidence_paths["probe_frontend_metrics"], expected,
            "probe_frontend_metrics",
        ),
        "camera_config": _expect_identity(
            evidence_paths["probe_camera_config"], expected, "probe_camera_config"
        ),
    }
    probe_gate = _validate_probe_contract(
        evidence_paths["probe_frontend_metrics"], probe_contract
    )

    final = {
        "features_bag": _expect_identity(
            evidence_paths["final_features_bag"], expected, "final_features_bag"
        ),
        "frontend_metrics": _expect_identity(
            evidence_paths["final_frontend_metrics"], expected,
            "final_frontend_metrics",
        ),
        "camera_config": _expect_identity(
            evidence_paths["final_camera_config"], expected, "final_camera_config"
        ),
    }
    equality = {
        key: _identity_tuple(final[key]) == _identity_tuple(klt_outputs[key])
        for key in ("features_bag", "frontend_metrics", "camera_config")
    }
    require(all(equality.values()), "FINAL_FALLBACK_NOT_BYTE_IDENTICAL_TO_ACCEPTED_KLT")
    forensic = _expect_identity(evidence_paths["forensic_audit"], expected, "forensic_audit")

    return {
        "disposition": "NA_FRONTEND_STRUCTURAL_GATE_FAILED_NOT_LAUNCHED",
        "forensic_audit": forensic,
        "terminal_failure_receipt": failure_identity,
        "accepted_receipt_present": False,
        "backend_launched_count": 0,
        "learning_contribution_claim_permitted": False,
        "failure_semantics": {
            "status": "FAILED_NO_AUTOMATIC_RETRY",
            "qualified_status": "FAILED_ATTEMPT002_NO_FURTHER_ATTEMPT",
            "error": "FEATURE_POINT_COUNT_RANGE",
            "vins_or_accuracy_executed": False,
            "process_start_claim": process_claim,
            "supervisor_log": supervisor_log,
        },
        "method_native_probe": {
            "outputs": probe,
            "structural_gate": probe_gate,
        },
        "final_fallback": {
            "outputs": final,
            "content_identity_equals_accepted_klt": equality,
            "accepted_frontend": False,
            "accepted_backend_input": False,
            "learned_contribution": False,
            "disposition": "EXCLUSION_EVIDENCE_ONLY_BYTE_IDENTICAL_KLT_FALLBACK",
        },
    }


def resolve_frontend_bindings(
    klt_receipt: Path = KLT_RECEIPT,
    run_root: Path = OVERLAY_RUN_ROOT,
    evidence_paths: Mapping[str, Path] = EVIDENCE_PATHS,
    expected: Mapping[str, tuple[int, str]] = EVIDENCE_EXPECTED,
    probe_contract: Mapping[str, Any] = PROBE_CONTRACT,
) -> dict[str, Any]:
    require(Path(klt_receipt).absolute() == Path(evidence_paths["klt_receipt"]).absolute(),
            "KLT_RECEIPT_PATH_AUTHORITY")
    klt = dict(ENGINE.load_frontend_binding("klt", Path(klt_receipt), Path(run_root).absolute()))
    klt.pop("_raw_contract", None)
    klt.pop("_input_claims", None)
    excluded = validate_terminal_diversion_evidence(
        klt, evidence_paths=evidence_paths, expected=expected,
        probe_contract=probe_contract,
    )
    klt["accepted_receipt"] = klt["receipt"]
    klt["acceptance_status"] = "PASS_FRONTEND_EXPORT_ACCEPTED"
    return {"klt": klt, "excluded_xfeat": excluded}


def arm_spec(item_id: str) -> dict[str, Any]:
    require(item_id in ITEM_ORDER, f"ITEM_ID:{item_id}")
    repeat = int(item_id[-2:])
    tag = f"a08_recoveredjuly_hist0000_4660_backend_klt_only_r{repeat:02d}_v2"
    return {
        "arm": "klt",
        "repeat_index": repeat,
        "method": "klt",
        "tag": tag,
        "run_leaf": f"external_klt_every2_{tag}",
    }


def item_environment(item_id: str, bindings: Mapping[str, Any]) -> dict[str, str]:
    spec = arm_spec(item_id)
    accepted = bindings["klt"]
    environment = dict(ENGINE.BASE_ENVIRONMENT)
    environment.update(ENGINE.COMMON_BACKEND_ENVIRONMENT)
    environment.update({
        "TAG": spec["tag"],
        "ROS_HOME": str(RUNTIME_ROOT / item_id / "ros_home"),
        "ROS_LOG_DIR": str(RUNTIME_ROOT / item_id / "ros_log"),
        "FEATURE_BAG_OVERRIDE": str(accepted["features_bag"]["path"]),
        "A08_FEATURE_BAG_SIZE_BYTES": str(accepted["features_bag"]["size_bytes"]),
        "A08_FEATURE_BAG_SHA256": str(accepted["features_bag"]["sha256"]),
        "A08_FRONTEND_METRICS": str(accepted["frontend_metrics"]["path"]),
        "A08_FRONTEND_METRICS_SIZE_BYTES": str(accepted["frontend_metrics"]["size_bytes"]),
        "A08_FRONTEND_METRICS_SHA256": str(accepted["frontend_metrics"]["sha256"]),
        "A08_FRONTEND_CAMERA_CONFIG": str(accepted["camera_config"]["path"]),
        "A08_FRONTEND_CAMERA_SIZE_BYTES": str(accepted["camera_config"]["size_bytes"]),
        "A08_FRONTEND_CAMERA_SHA256": str(accepted["camera_config"]["sha256"]),
        "A08_RAW_BAG_SIZE_BYTES": str(ENGINE.RAW_BAG_EXPECTED[0]),
        "A08_RAW_BAG_SHA256": ENGINE.RAW_BAG_EXPECTED[1],
        "A08_RAW_TAR_SIZE_BYTES": str(ENGINE.SOURCE_ARCHIVE_EXPECTED[0]),
        "A08_RAW_TAR_SHA256": ENGINE.SOURCE_ARCHIVE_EXPECTED[1],
        "A08_GT_SIZE_BYTES": str(ENGINE.GROUND_TRUTH_EXPECTED[0]),
        "A08_GT_SHA256": ENGINE.GROUND_TRUTH_EXPECTED[1],
        "A08_ITEM_OUTPUT_DIR": str(BACKEND_ROOT / item_id),
        "A08_ITEM_ID": item_id,
        "A08_WORKSPACE_LINK": str(OVERLAY_RUN_ROOT / spec["run_leaf"]),
        "A08_OVERLAY_BACKEND_SHELL": str(ENGINE.BACKEND_SHELL),
        "A08_KLT_ONLY_REPLAYS_V2": "1",
        "A08_ACCEPTED_FRONTEND_RECEIPT": str(accepted["accepted_receipt"]["path"]),
        "A08_XFEAT_TERMINAL_DISPOSITION": (
            "NA_FRONTEND_STRUCTURAL_GATE_FAILED_NOT_LAUNCHED"
        ),
        "A08_XFEAT_BACKEND_LAUNCHED_COUNT": "0",
        "A08_LEARNING_CONTRIBUTION_CLAIM_PERMITTED": "0",
    })
    return environment


def build_items(
    bindings: Mapping[str, Any], host_net: str, host_user: str,
) -> dict[str, Any]:
    require(re.fullmatch(r"net:\[[0-9]+\]", host_net) is not None, "HOST_NETNS")
    require(re.fullmatch(r"user:\[[0-9]+\]", host_user) is not None, "HOST_USERNS")
    require(set(bindings) == {"klt", "excluded_xfeat"}, "FRONTEND_BINDING_KEYS")
    excluded = bindings["excluded_xfeat"]
    require(
        excluded.get("disposition") == "NA_FRONTEND_STRUCTURAL_GATE_FAILED_NOT_LAUNCHED"
        and excluded.get("accepted_receipt_present") is False
        and excluded.get("backend_launched_count") == 0
        and excluded.get("learning_contribution_claim_permitted") is False,
        "EXCLUDED_XFEAT_BOUNDARY",
    )
    result: dict[str, Any] = {}
    for item_id in ITEM_ORDER:
        spec = arm_spec(item_id)
        output_dir = BACKEND_ROOT / item_id
        workspace_link = OVERLAY_RUN_ROOT / spec["run_leaf"]
        inner = [
            str(ENGINE.BASH), str(REPLAY_ONLY_GUARD), "aqualoc_archaeo", "8",
            "0", "4660", "klt", "2",
        ]
        argv = [
            str(ENGINE.UNSHARE), "--user", "--map-root-user", "--net",
            str(ENGINE.PYTHON38), str(ENGINE.NETNS_ENTRY),
            "--output-dir", str(output_dir),
            "--formal-port", str(ENGINE.FORMAL_PORT),
            "--host-network-namespace", host_net,
            "--host-user-namespace", host_user,
            "--", *inner,
        ]
        environment = item_environment(item_id, bindings)
        result[item_id] = {
            "item_id": item_id,
            "arm": "klt",
            "repeat_index": spec["repeat_index"],
            "method": "klt",
            "output_dir": str(output_dir),
            "workspace_link": str(workspace_link),
            "argv": argv,
            "inner_backend_argv_sha256": compact_sha256(inner),
            "host_network_namespace": host_net,
            "host_user_namespace": host_user,
            "env": environment,
            "cwd": str(OVERLAY),
            "timeout_seconds": ENGINE.TIMEOUT_SECONDS,
            "expected_outputs": list(ENGINE.EXPECTED_OUTPUTS),
            "input_binding": bindings["klt"],
            "excluded_xfeat_sha256": compact_sha256(excluded),
            "scientific_boundary": {
                "xfeat_accuracy": "NA",
                "learned_contribution_claim_permitted": False,
                "final_fallback_accepted": False,
            },
            "command_sha256": compact_sha256({"argv": argv, "env": environment}),
        }
    return result


def static_identity_paths() -> dict[str, Path]:
    inherited = dict(BASE_STATIC_PATHS)
    paths = dict(inherited)
    paths["base_backend_runner_v1"] = paths.pop("runner")
    paths["base_backend_protocol_v1"] = paths.pop("protocol")
    paths["base_replay_only_guard_v1"] = paths.pop("replay_only_guard")
    paths.update({
        "runner": RUNNER,
        "protocol": PROTOCOL,
        "klt_only_replay_guard_v2": REPLAY_ONLY_GUARD,
        "xfeat_terminal_forensic_audit_excluded_authority": FORENSIC_AUDIT,
    })
    return paths


def collect_static_identities() -> dict[str, Any]:
    values = {name: identity(path) for name, path in static_identity_paths().items()}
    require(
        _identity_tuple(values["process_safety_base"]) == ENGINE.SAFETY_BASE_EXPECTED,
        "SAFETY_BASE_BOOTSTRAP_DRIFT",
    )
    for label, expected in (
        ("raw_bag", ENGINE.RAW_BAG_EXPECTED),
        ("source_archive", ENGINE.SOURCE_ARCHIVE_EXPECTED),
        ("ground_truth", ENGINE.GROUND_TRUTH_EXPECTED),
    ):
        require(_identity_tuple(values[label]) == expected,
                f"FROZEN_HISTORY_INPUT_DRIFT:{label}")
    require(
        _identity_tuple(values["xfeat_terminal_forensic_audit_excluded_authority"])
        == EVIDENCE_EXPECTED["forensic_audit"],
        "FORENSIC_AUDIT_BOOTSTRAP_DRIFT",
    )
    for label, expected in BASE_AUTHORITY_EXPECTED.items():
        require(_identity_tuple(values[label]) == expected,
                f"BASE_AUTHORITY_BOOTSTRAP_DRIFT:{label}")
    return values


def _original_item_paths(item_id: str) -> dict[str, Path]:
    arm = "klt" if item_id.startswith("KLT_") else "xfeat"
    repeat = int(item_id[-2:])
    method = "klt" if arm == "klt" else "hybrid_xfeat"
    tag = f"a08_recoveredjuly_hist0000_4660_backend_{arm}_r{repeat:02d}_v1"
    return {
        "output": ORIGINAL_BACKEND_ROOT / item_id,
        "workspace": OVERLAY_RUN_ROOT / f"external_{method}_every2_{tag}",
        "runtime": ORIGINAL_RUNTIME_ROOT / item_id,
    }


def original_campaign_diversion_gate() -> dict[str, Any]:
    require(not ORIGINAL_LOCK.exists() and not ORIGINAL_LOCK.is_symlink(),
            "ORIGINAL_5_PLUS_5_LOCK_PRESENT")
    require(not ORIGINAL_BACKEND_ROOT.exists() and not ORIGINAL_BACKEND_ROOT.is_symlink(),
            "ORIGINAL_5_PLUS_5_OUTPUT_ROOT_PRESENT")
    require(not ORIGINAL_RUNTIME_ROOT.exists() and not ORIGINAL_RUNTIME_ROOT.is_symlink(),
            "ORIGINAL_5_PLUS_5_RUNTIME_ROOT_PRESENT")
    items: dict[str, Any] = {}
    for item_id in ORIGINAL_ITEM_ORDER:
        observed: dict[str, str] = {}
        for label, path in _original_item_paths(item_id).items():
            require(not path.exists() and not path.is_symlink(),
                    f"ORIGINAL_5_PLUS_5_ITEM_TOUCHED:{item_id}:{label}")
            observed[label] = str(path)
        items[item_id] = observed
    return {
        "status": "PASS_ORIGINAL_5_PLUS_5_LOCK_ABSENT_ALL_TEN_ITEMS_UNSTARTED",
        "execution_lock": {"path": str(ORIGINAL_LOCK), "state": "ABSENT"},
        "output_root": {"path": str(ORIGINAL_BACKEND_ROOT), "state": "ABSENT"},
        "runtime_root": {"path": str(ORIGINAL_RUNTIME_ROOT), "state": "ABSENT"},
        "item_order": list(ORIGINAL_ITEM_ORDER),
        "items": items,
    }


def require_campaign_unstarted() -> None:
    require(not BACKEND_ROOT.exists() and not BACKEND_ROOT.is_symlink(),
            "KLT_ONLY_V2_OUTPUT_ROOT_ALREADY_TOUCHED")
    require(not RUNTIME_ROOT.exists() and not RUNTIME_ROOT.is_symlink(),
            "KLT_ONLY_V2_RUNTIME_ROOT_ALREADY_TOUCHED")
    for item_id in ITEM_ORDER:
        spec = arm_spec(item_id)
        paths = {
            "output": BACKEND_ROOT / item_id,
            "workspace": OVERLAY_RUN_ROOT / spec["run_leaf"],
            "runtime": RUNTIME_ROOT / item_id,
        }
        for label, path in paths.items():
            require(not path.exists() and not path.is_symlink(),
                    f"KLT_ONLY_V2_ALREADY_TOUCHED:{item_id}:{label}")


def contract_core(
    bindings: Mapping[str, Any], static_identities: Mapping[str, Any],
    host_net: str, host_user: str,
) -> dict[str, Any]:
    items = build_items(bindings, host_net, host_user)
    return {
        "schema_version": LOCK_SCHEMA,
        "status": LOCK_STATUS,
        "campaign": "A08_RECOVERED_JULY_HISTORY_MATCHED_BACKEND_KLT_ONLY_REPLAYS_V2",
        "item_order": list(ITEM_ORDER),
        "policy": {
            "klt_repeat_count": 5,
            "xfeat_backend_items": 0,
            "fixed_klt_only_order": True,
            "single_supervisor_popen_per_item": True,
            "automatic_retry_count": 0,
            "replacement_repeat_permitted": False,
            "terminal_result_failure_does_not_block_later_items": True,
            "execution_integrity_failure_blocks_later_items": True,
            "vins_multiple_thread": 0,
            "fresh_user_and_network_namespace_per_item": True,
            "strict_fd_replay_only": True,
            "formal_internal_ros_port": ENGINE.FORMAL_PORT,
            "ambient_desktop_allowed": True,
            "runtime_or_throughput_claim_permitted": False,
            "common_support_score_interval_source_indices": [4000, 4660],
        },
        "scientific_boundary": {
            "campaign_result": "KLT_BACKEND_REPEAT_STABILITY_ONLY",
            "xfeat_accuracy": "NA",
            "this_campaign_klt_vs_learned_accuracy_comparison_permitted": False,
            "separately_frozen_hfnet_vs_klt_evaluator_permitted": True,
            "final_fallback_accepted_as_xfeat": False,
            "xfeat_or_learned_frontend_contribution_claim_permitted": False,
        },
        "host_namespace": {"network": host_net, "user": host_user},
        "frontend_authority": {
            "klt": bindings["klt"],
            "excluded_xfeat": bindings["excluded_xfeat"],
        },
        "excluded_xfeat": bindings["excluded_xfeat"],
        "original_5_plus_5_diversion_gate": original_campaign_diversion_gate(),
        "static_identities": dict(static_identities),
        "items": items,
    }


def build_lock_payload(
    bindings: Mapping[str, Any], static_identities: Mapping[str, Any],
    host_net: str, host_user: str, created_at_utc: str,
) -> dict[str, Any]:
    core = contract_core(bindings, static_identities, host_net, host_user)
    payload = {**core, "created_at_utc": created_at_utc}
    payload["contract_sha256"] = compact_sha256(payload)
    return payload


def expected_lock_from_current_authority(
    bindings: Mapping[str, Any], created: str,
) -> dict[str, Any]:
    return build_lock_payload(
        bindings, collect_static_identities(), current_namespace("net"),
        current_namespace("user"), created,
    )


def verify_lock(
    lock_path: Path, bindings: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    lock, lock_identity = stable_json(lock_path)
    created = lock.get("created_at_utc")
    require(isinstance(created, str) and created, "LOCK_CREATED_AT")
    expected = expected_lock_from_current_authority(bindings, created)
    require(lock == expected, "KLT_ONLY_V2_EXECUTION_LOCK_AUTHORITY_DRIFT")
    excluded = lock.get("excluded_xfeat")
    require(
        isinstance(excluded, dict)
        and excluded.get("disposition")
        == "NA_FRONTEND_STRUCTURAL_GATE_FAILED_NOT_LAUNCHED"
        and excluded.get("forensic_audit")
        == lock["static_identities"]["xfeat_terminal_forensic_audit_excluded_authority"]
        and excluded.get("terminal_failure_receipt")
        == bindings["excluded_xfeat"]["terminal_failure_receipt"]
        and excluded.get("accepted_receipt_present") is False
        and excluded.get("backend_launched_count") == 0
        and excluded.get("learning_contribution_claim_permitted") is False,
        "LOCK_EXCLUDED_XFEAT_BOUNDARY",
    )
    require(
        lock["frontend_authority"]["klt"]["accepted_receipt"]
        == bindings["klt"]["accepted_receipt"],
        "LOCK_KLT_ACCEPTED_RECEIPT",
    )
    return lock, lock_identity


def preflight_readonly(lock_path: Path = DEFAULT_LOCK) -> dict[str, Any]:
    presence = authority_presence()
    bad = {
        label: row for label, row in presence.items()
        if row["state"] not in {"PRESENT_REGULAR", "ABSENT_AS_REQUIRED"}
    }
    if bad:
        return {
            "status": "BLOCKED_TERMINAL_DIVERSION_AUTHORITY",
            "read_only": True,
            "authority_presence": presence,
            "invalid": bad,
            "lock_path": str(lock_path.absolute()),
            "item_order": list(ITEM_ORDER),
        }
    try:
        bindings = resolve_frontend_bindings()
        original_gate = original_campaign_diversion_gate()
        if not lock_path.exists() and not lock_path.is_symlink():
            require_campaign_unstarted()
            static_identities = collect_static_identities()
            core = contract_core(
                bindings, static_identities,
                current_namespace("net"), current_namespace("user"),
            )
            return {
                "status": "READY_TO_BUILD_KLT_ONLY_V2_EXECUTION_LOCK",
                "read_only": True,
                "authority_presence": presence,
                "frontend_bindings": bindings,
                "original_5_plus_5_diversion_gate": original_gate,
                "candidate_core_sha256": compact_sha256(core),
                "lock_path": str(lock_path.absolute()),
                "lock_present": False,
                "item_order": list(ITEM_ORDER),
            }
        lock, lock_identity = verify_lock(lock_path, bindings)
        return {
            "status": "PASS_LOCKED_READY_FOR_AUTHORIZED_KLT_ITEM",
            "read_only": True,
            "authority_presence": presence,
            "frontend_bindings": bindings,
            "original_5_plus_5_diversion_gate": original_gate,
            "lock": lock_identity,
            "contract_sha256": lock["contract_sha256"],
            "item_order": list(ITEM_ORDER),
        }
    except (BackendProtocolError, OSError, ValueError) as error:
        return {
            "status": "BLOCKED_PREFLIGHT",
            "read_only": True,
            "authority_presence": presence,
            "error": f"{type(error).__name__}:{error}",
            "lock_path": str(lock_path.absolute()),
            "item_order": list(ITEM_ORDER),
        }


def _configure_engine() -> None:
    assignments = {
        "BACKEND_ROOT": BACKEND_ROOT,
        "RUNTIME_ROOT": RUNTIME_ROOT,
        "PROTOCOL": PROTOCOL,
        "DEFAULT_LOCK": DEFAULT_LOCK,
        "KLT_RECEIPT": KLT_RECEIPT,
        "DEFAULT_RECEIPTS": {"klt": KLT_RECEIPT},
        "REPLAY_ONLY_GUARD": REPLAY_ONLY_GUARD,
        "ITEM_ORDER": ITEM_ORDER,
        "CLAIM_NAME": CLAIM_NAME,
        "RECEIPT_NAME": RECEIPT_NAME,
        "LOCK_SCHEMA": LOCK_SCHEMA,
        "RECEIPT_SCHEMA": RECEIPT_SCHEMA,
        "LOCK_STATUS": LOCK_STATUS,
        "BUILD_LOCK_TOKEN": BUILD_LOCK_TOKEN,
        "AUTHORIZATION_TOKENS": AUTHORIZATION_TOKENS,
        "arm_spec": arm_spec,
        "item_environment": item_environment,
        "build_items": build_items,
        "static_identity_paths": static_identity_paths,
        "collect_static_identities": collect_static_identities,
        "contract_core": contract_core,
        "build_lock_payload": build_lock_payload,
        "expected_lock_from_current_authority": expected_lock_from_current_authority,
        "verify_lock": verify_lock,
        "resolve_frontend_bindings": resolve_frontend_bindings,
        "require_campaign_unstarted": require_campaign_unstarted,
    }
    for name, value in assignments.items():
        setattr(ENGINE, name, value)


def inspect_item_readonly(item_id: str) -> dict[str, Any]:
    _configure_engine()
    return ENGINE.inspect_item_readonly(item_id)


def prior_receipt(
    lock_identity: Mapping[str, Any], item: Mapping[str, Any],
) -> dict[str, Any]:
    """Deeply re-audit one terminal v2 receipt through the pinned v1 engine."""
    _configure_engine()
    return ENGINE.prior_receipt(lock_identity, item)


def audit_readonly(lock_path: Path = DEFAULT_LOCK) -> dict[str, Any]:
    presence = authority_presence()
    lock_present = lock_path.exists() or lock_path.is_symlink()
    lock_audit: dict[str, Any] = {
        "path": str(lock_path.absolute()),
        "state": "PRESENT" if lock_present else "ABSENT",
        "authority": "NOT_CHECKED_LOCK_ABSENT" if not lock_present else "NOT_CHECKED",
    }
    verified_lock: Optional[dict[str, Any]] = None
    verified_identity: Optional[dict[str, Any]] = None
    if lock_present:
        try:
            bindings = resolve_frontend_bindings()
            verified_lock, verified_identity = verify_lock(lock_path, bindings)
            lock_audit.update({
                "authority": "PASS", "identity": verified_identity,
                "contract_sha256": verified_lock["contract_sha256"],
            })
        except (BackendProtocolError, OSError, ValueError) as error:
            lock_audit.update({
                "authority": "FAIL", "error": f"{type(error).__name__}:{error}",
            })
    rows = [inspect_item_readonly(item) for item in ITEM_ORDER]
    if verified_lock is not None and verified_identity is not None:
        for row in rows:
            if row["state"] != "TERMINAL_RECEIPT":
                continue
            try:
                prior_receipt(
                    verified_identity, verified_lock["items"][row["item_id"]]
                )
                row["deep_terminal_evidence_audit"] = "PASS"
            except (BackendProtocolError, OSError, ValueError) as error:
                row.update({
                    "state": "INVALID_TERMINAL_EVIDENCE",
                    "deep_terminal_evidence_audit": "FAIL",
                    "error": f"{type(error).__name__}:{error}",
                })
    blocked_by: Optional[str] = None
    next_item: Optional[str] = None
    for row in rows:
        if row["state"] == "TERMINAL_RECEIPT" and row.get("integrity") == "PASS":
            continue
        if row["state"] == "NOT_STARTED":
            next_item = row["item_id"]
        else:
            blocked_by = row["item_id"]
        break
    if lock_audit.get("authority") != "PASS":
        next_item = None
        block_reason = f"LOCK_AUTHORITY:{lock_audit.get('authority')}"
    elif blocked_by is not None:
        block_reason = f"PRIOR_ITEM:{blocked_by}"
    else:
        block_reason = None
    return {
        "status": "READ_ONLY_AUDIT",
        "read_only": True,
        "authority_presence": presence,
        "lock": lock_audit,
        "item_order": list(ITEM_ORDER),
        "items": rows,
        "next_item_if_lock_and_authorization_pass": next_item,
        "next_item_block_reason": block_reason,
        "blocked_by_integrity_or_incomplete_item": blocked_by,
        "excluded_xfeat_disposition": "NA_FRONTEND_STRUCTURAL_GATE_FAILED_NOT_LAUNCHED",
    }


def execute_item(
    lock_path: Path, item_id: str, authorization_token: str,
) -> tuple[int, dict[str, Any]]:
    require(item_id in ITEM_ORDER, f"ITEM_ID:{item_id}")
    require(authorization_token == AUTHORIZATION_TOKENS[item_id], "AUTHORIZATION_TOKEN")
    _configure_engine()
    return ENGINE.execute_item(lock_path, item_id, authorization_token)


def build_lock(lock_path: Path, authorization_token: str) -> dict[str, Any]:
    require(authorization_token == BUILD_LOCK_TOKEN, "BUILD_LOCK_AUTHORIZATION_TOKEN")
    require(not lock_path.exists() and not lock_path.is_symlink(), "LOCK_ALREADY_EXISTS")
    bindings = resolve_frontend_bindings()
    original_campaign_diversion_gate()
    require_campaign_unstarted()
    created = datetime.now(timezone.utc).isoformat(timespec="seconds")
    payload = expected_lock_from_current_authority(bindings, created)
    safety = ENGINE.safety_module()
    safety.atomic_publish(lock_path, payload, propagate_interruption_after_commit=True)
    return {"status": "KLT_ONLY_V2_EXECUTION_LOCK_PUBLISHED", "lock": identity(lock_path)}


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lock", type=Path, default=DEFAULT_LOCK)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("preflight")
    commands.add_parser("audit")
    build = commands.add_parser("build-lock")
    build.add_argument("--authorization-token", required=True)
    run = commands.add_parser("run-item")
    run.add_argument("item_id", choices=ITEM_ORDER)
    run.add_argument("--authorization-token", required=True)
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    lock_path = args.lock.absolute()
    if args.command == "preflight":
        result = preflight_readonly(lock_path)
        print(json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False))
        return 0 if result["status"].startswith(("PASS_", "READY_")) else 2
    if args.command == "audit":
        print(json.dumps(audit_readonly(lock_path), indent=2, sort_keys=True, ensure_ascii=False))
        return 0
    try:
        if args.command == "build-lock":
            result = build_lock(lock_path, args.authorization_token)
            code = 0
        else:
            code, result = execute_item(
                lock_path, args.item_id, args.authorization_token
            )
        print(json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False))
        return code
    except (OSError, ValueError, RuntimeError) as error:
        print(f"A08_KLT_ONLY_V2_ERROR:{type(error).__name__}:{error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
