#!/usr/bin/env python3
"""Exactly-once two-layer common-support evaluation for fresh A10/A09 pairs."""

from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import sys
import time
from typing import Any, Iterable, Mapping


ROOT = Path("/home/ma/AQUA-FE_WS")
PROTOCOL = ROOT / "papers/positive_klt_windows_lifecycle_rearmed_evaluation_v1_protocol.md"
RUNNER = Path(__file__).resolve()
BACKEND_ROOT = Path(
    "/mnt/data/AQUA-FE_WS/experiments/"
    "positive_klt_windows_lifecycle_rearmed_backend_v1"
)
BACKEND_MULTIWINDOW_TERMINAL = (
    BACKEND_ROOT / "terminal_multiwindow_backend_receipt_v1.json"
)
OUTPUT_ROOT = Path(
    "/mnt/data/AQUA-FE_WS/experiments/"
    "positive_klt_windows_lifecycle_rearmed_evaluation_v1"
)
LOCK_PATH = OUTPUT_ROOT / ".two_layer_evaluation_supervisor.flock"
TERMINAL_RECEIPT = OUTPUT_ROOT / "terminal_multiwindow_evaluation_receipt_v1.json"

EVALUATOR = ROOT / "scripts/evaluate_vins_common_support_epoch_v2.py"
EVALUATOR_BASE = ROOT / "scripts/evaluate_vins_common_support.py"
EVALUATOR_CORE = ROOT / "scripts/trajectory_eval_core.py"
EVO_APE = Path("/home/ma/.local/bin/evo_ape")
EVO_RPE = Path("/home/ma/.local/bin/evo_rpe")
HFNET_CONFIG = ROOT / "configs/published_baselines/hfnet_aqualoc_a02_body_T_cam0_v1.yaml"
REFERENCE_TOPIC = "/aqualoc/colmap_gt"

SEQUENCE_ORDER = ("a10", "a09")
LAYER_ORDER = ("primary_pair", "context_fourarm")
BACKEND_ARM_ORDER = (
    "klt_external_feature_context_fresh_pair_v1",
    "aquafe_lifecycle_rearmed_external_feature_context_fresh_pair_v1",
)
PRIMARY_ARM_ORDER = (
    "EXTERNAL_KLT_FRESH_PAIRED",
    "AQUAFE_XFEAT_LIFECYCLE_REARMED_FRESH",
)
CONTEXT_ARM_ORDER = (
    "VANILLA_ORIGIN_NATIVE_IMAGE_CONTEXT",
    "EXTERNAL_KLT_FRESH_PAIRED",
    "AQUAFE_XFEAT_LIFECYCLE_REARMED_FRESH",
    "HFNET_SLAM_NATURAL_HISTORY",
)


def backend_arm_dir(sequence: str, arm: str) -> Path:
    return BACKEND_ROOT / sequence / arm


SEQUENCES: dict[str, dict[str, Any]] = {
    "a10": {
        "raw_bag": Path(
            "/mnt/data/AQUA-FE_WS/experiments/a10_samehistory_system_v1/raw/"
            "archaeo10_0000_2800.bag"
        ),
        "full_native_gt": 139,
        "source_config_name": "vins_aqualoc_archaeo_external.yaml",
        "primary": {
            "indices": [2199, 2800],
            "start_ns": 1_542_888_905_994_706_672,
            "end_ns": 1_542_888_936_039_921_424,
            "native_gt": 31,
            "grid_count": 31,
            "contrast": "A10_LIFECYCLE_REARMED_PRIMARY_FRESH_PAIR_V1_2199_2800",
        },
        "context": {
            "indices": [2400, 2800],
            "start_ns": 1_542_888_916_043_622_160,
            "end_ns": 1_542_888_936_039_921_424,
            "native_gt": 21,
            "grid_count": 20,
            "contrast": "A10_LIFECYCLE_REARMED_CONTEXT_FOURARM_V1_SCORE_2400_2800",
        },
        "vanilla_trajectory": Path(
            "/mnt/data/AQUA-FE_WS/experiments/a10_samehistory_system_v4_backend_recovery/"
            "backends/vanilla_origin_native_image_context/vins_output/vio.csv"
        ),
        "vanilla_config": Path(
            "/mnt/data/AQUA-FE_WS/experiments/a10_samehistory_system_v4_backend_recovery/"
            "backends/vanilla_origin_native_image_context/vins_aqualoc_archaeo_origin.yaml"
        ),
        "hfnet_trajectory": Path(
            "/mnt/data/AQUA-FE_WS/experiments/a10_samehistory_user_waived_diagnostic_v1/"
            "hfnet_world_T_body_source_stamp_canonical_v1.csv"
        ),
        "hfnet_authority": Path(
            "/mnt/data/AQUA-FE_WS/experiments/a10_samehistory_user_waived_diagnostic_v1/"
            "hfnet_world_T_body_source_stamp_canonical_v1.csv.manifest.json"
        ),
    },
    "a09": {
        "raw_bag": Path(
            "/mnt/data/AQUA-FE_WS/experiments/a09_samehistory_system_warmstart_v1/raw/"
            "archaeo09_0000_4400.bag"
        ),
        "full_native_gt": 213,
        "source_config_name": "vins_aqualoc_archaeo_external.yaml",
        "primary": {
            "indices": [3799, 4400],
            "start_ns": 1_542_888_935_990_218_544,
            "end_ns": 1_542_888_966_034_698_672,
            "native_gt": 31,
            "grid_count": 31,
            "contrast": "A09_LIFECYCLE_REARMED_PRIMARY_FRESH_PAIR_V1_3799_4400",
        },
        "context": {
            "indices": [4000, 4400],
            "start_ns": 1_542_888_946_038_630_384,
            "end_ns": 1_542_888_966_034_698_672,
            "native_gt": 21,
            "grid_count": 20,
            "contrast": "A09_LIFECYCLE_REARMED_CONTEXT_FOURARM_V1_SCORE_4000_4400",
        },
        "vanilla_trajectory": Path(
            "/mnt/data/AQUA-FE_WS/experiments/a09_samehistory_system_warmstart_v1/"
            "backends/vanilla_origin_native_image_context/vins_output/vio.csv"
        ),
        "vanilla_config": Path(
            "/mnt/data/AQUA-FE_WS/experiments/a09_samehistory_system_warmstart_v1/"
            "backends/vanilla_origin_native_image_context/vins_aqualoc_archaeo_origin.yaml"
        ),
        "hfnet_trajectory": Path(
            "/mnt/data/AQUA-FE_WS/experiments/a09_samehistory_system_warmstart_v1/"
            "external_baselines/hfnet_warmstart_bridge_v1/"
            "hfnet_world_T_body_source_stamp_canonical_v1.csv"
        ),
        "hfnet_authority": Path(
            "/mnt/data/AQUA-FE_WS/experiments/a09_samehistory_system_warmstart_v1/"
            "external_baselines/hfnet_warmstart_bridge_v1/"
            "hfnet_world_T_body_source_stamp_canonical_v1.receipt.json"
        ),
    },
}

EXPECTED_IDENTITIES: dict[Path, tuple[int, str]] = {
    SEQUENCES["a10"]["raw_bag"]: (
        765_976_943,
        "49864715ec19005daa3492fa043fe87204fb6f8cc802b6b98cba55a8ab4fe87e",
    ),
    SEQUENCES["a10"]["vanilla_trajectory"]: (
        141_986,
        "f3f07e846fae02bd33b44a295106e769b8288710204c05d7b1c65f1d124dbcca",
    ),
    SEQUENCES["a10"]["vanilla_config"]: (
        1_009,
        "da4518da471bdcc282430ecef9f7d4f5b69b96148845a60dec012a65ebf656dc",
    ),
    SEQUENCES["a10"]["hfnet_trajectory"]: (
        42_749,
        "de0090a2c08d795ecdbe47f51c43e18cd624da14be9cfa64bfb3efd52ce2d99a",
    ),
    SEQUENCES["a10"]["hfnet_authority"]: (
        1_156,
        "c43ad816e70e543197a849480a1d8958381c783be9cdab141a46b427895db84a",
    ),
    SEQUENCES["a09"]["raw_bag"]: (
        1_187_038_470,
        "a4a24bd0c2451f4996d39f635e55fd99730698bf704c4e7dc81729070d0dca97",
    ),
    SEQUENCES["a09"]["vanilla_trajectory"]: (
        227_239,
        "e7f8e06536bd788edc60dd13add6c0d371a41d0351eaa29a7f5c3d1cde9afc2d",
    ),
    SEQUENCES["a09"]["vanilla_config"]: (
        990,
        "eafd7e6f22e573c4e0d7b5e36f2550938029456fc75ad55bd741c1d000016ff7",
    ),
    SEQUENCES["a09"]["hfnet_trajectory"]: (
        42_105,
        "2b5bd98de228b13c33a79e40b0462d51db57e3280449230d3e1f33f369072d5d",
    ),
    SEQUENCES["a09"]["hfnet_authority"]: (
        5_632,
        "dff07d76e1d363846e31a693017df58e580a4482a076507dd1036372c1ce22b4",
    ),
    HFNET_CONFIG: (
        415,
        "a76c728b31d47c3a87f54c465fb581007ed2da2b7d7d84df81dbde93e9a886c1",
    ),
    EVALUATOR: (
        5_447,
        "3c455299b23157cc749b474b9460ca4a408b3bee516e9d1bf2109f253cf89f91",
    ),
    EVALUATOR_BASE: (
        27_933,
        "ab6f2b5c1a10a41463657edee2724c022fc0248dc885096acb336e602384c110",
    ),
    EVALUATOR_CORE: (
        27_945,
        "aa9ac4da81df7298d1f1c369548ca98a57235916004337cad66f4cf331560635",
    ),
    EVO_APE: (
        213,
        "6bee25dc5bfdab0ead8988ab4014a72511339e94697ec61699f66f68f5f24d15",
    ),
    EVO_RPE: (
        213,
        "9e07d0bd4566aa680d5e39e58589176a286f4f8a22ba9107a5834ddb278e2bd1",
    ),
}


class EvaluationError(RuntimeError):
    """Fail-closed evaluation contract violation."""


def require(condition: bool, code: str) -> None:
    if not condition:
        raise EvaluationError(code)


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def identity(path: Path) -> dict[str, Any]:
    return {"path": str(path), "size_bytes": path.stat().st_size, "sha256": sha256(path)}


def require_identity(path: Path, expected: tuple[int, str]) -> dict[str, Any]:
    require(path.is_file() and not path.is_symlink(), f"INPUT_NOT_REGULAR:{path}")
    actual = identity(path)
    require(
        (actual["size_bytes"], actual["sha256"]) == expected,
        f"INPUT_IDENTITY_DRIFT:{path}",
    )
    return actual


def read_json(path: Path) -> Any:
    with path.open(encoding="utf-8") as stream:
        return json.load(stream)


def write_json(path: Path, value: Any) -> None:
    require(not path.exists() and not path.is_symlink(), f"REFUSE_OVERWRITE:{path}")
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False)
        + "\n",
        encoding="utf-8",
    )


def write_text(path: Path, value: str) -> None:
    require(not path.exists() and not path.is_symlink(), f"REFUSE_OVERWRITE:{path}")
    path.write_text(value.rstrip() + "\n", encoding="utf-8")


def static_input_identities(sequence: str | None = None) -> dict[str, Any]:
    shared = [HFNET_CONFIG, EVALUATOR, EVALUATOR_BASE, EVALUATOR_CORE, EVO_APE, EVO_RPE]
    selected = SEQUENCE_ORDER if sequence is None else (sequence,)
    paths = list(shared)
    for name in selected:
        item = SEQUENCES[name]
        paths.extend(
            [
                item["raw_bag"],
                item["vanilla_trajectory"],
                item["vanilla_config"],
                item["hfnet_trajectory"],
                item["hfnet_authority"],
            ]
        )
    result = {str(path): require_identity(path, EXPECTED_IDENTITIES[path]) for path in paths}
    for path in (PROTOCOL, RUNNER):
        require(path.is_file() and not path.is_symlink(), f"CONTROL_NOT_REGULAR:{path}")
        result[str(path)] = identity(path)
    return result


def refresh(previous: Mapping[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for raw_path in previous:
        path = Path(raw_path)
        require(path.is_file() and not path.is_symlink(), f"CLAIMED_INPUT_NOT_REGULAR:{path}")
        result[raw_path] = identity(path)
    return result


def same_identity_maps(left: Mapping[str, Any], right: Mapping[str, Any]) -> bool:
    def compact(values: Mapping[str, Any]) -> dict[str, tuple[int, str]]:
        return {
            key: (int(value["size_bytes"]), str(value["sha256"]))
            for key, value in values.items()
        }

    return compact(left) == compact(right)


def _require_record_identity(record: Mapping[str, Any], actual: Mapping[str, Any], code: str) -> None:
    require(
        int(record.get("size_bytes", -1)) == int(actual["size_bytes"])
        and str(record.get("sha256")) == str(actual["sha256"]),
        code,
    )


def normalized_config(path: Path) -> bytes:
    text = path.read_text(encoding="utf-8")
    require(
        len(re.findall(r'^output_path:\s*".*"$', text, flags=re.MULTILINE)) == 1,
        f"CONFIG_OUTPUT_PATH:{path}",
    )
    return re.sub(
        r'^output_path:\s*".*"$',
        'output_path: "<NORMALIZED>"',
        text,
        flags=re.MULTILINE,
    ).encode("utf-8")


def fresh_trajectory(sequence: str, arm_name: str) -> Path:
    backend_arm = BACKEND_ARM_ORDER[0] if arm_name == PRIMARY_ARM_ORDER[0] else BACKEND_ARM_ORDER[1]
    return backend_arm_dir(sequence, backend_arm) / "vins_output/vio.csv"


def fresh_config(sequence: str, arm_name: str) -> Path:
    backend_arm = BACKEND_ARM_ORDER[0] if arm_name == PRIMARY_ARM_ORDER[0] else BACKEND_ARM_ORDER[1]
    return backend_arm_dir(sequence, backend_arm) / SEQUENCES[sequence]["source_config_name"]


def trajectories_for(sequence: str, layer: str) -> dict[str, Path]:
    if layer == "primary_pair":
        return {name: fresh_trajectory(sequence, name) for name in PRIMARY_ARM_ORDER}
    item = SEQUENCES[sequence]
    return {
        CONTEXT_ARM_ORDER[0]: item["vanilla_trajectory"],
        CONTEXT_ARM_ORDER[1]: fresh_trajectory(sequence, PRIMARY_ARM_ORDER[0]),
        CONTEXT_ARM_ORDER[2]: fresh_trajectory(sequence, PRIMARY_ARM_ORDER[1]),
        CONTEXT_ARM_ORDER[3]: item["hfnet_trajectory"],
    }


def configs_for(sequence: str, layer: str) -> dict[str, Path]:
    if layer == "primary_pair":
        return {name: fresh_config(sequence, name) for name in PRIMARY_ARM_ORDER}
    item = SEQUENCES[sequence]
    return {
        CONTEXT_ARM_ORDER[0]: item["vanilla_config"],
        CONTEXT_ARM_ORDER[1]: fresh_config(sequence, PRIMARY_ARM_ORDER[0]),
        CONTEXT_ARM_ORDER[2]: fresh_config(sequence, PRIMARY_ARM_ORDER[1]),
        CONTEXT_ARM_ORDER[3]: HFNET_CONFIG,
    }


def hfnet_authority(sequence: str) -> dict[str, Any]:
    item = SEQUENCES[sequence]
    authority = read_json(item["hfnet_authority"])
    trajectory_actual = identity(item["hfnet_trajectory"])
    if sequence == "a10":
        require(authority.get("state") == "PASS", "A10_HFNET_AUTHORITY_STATE")
        record = authority.get("canonical_content") or {}
        _require_record_identity(record, trajectory_actual, "A10_HFNET_CANONICAL_BINDING")
        require(authority.get("source_indices_inclusive") == item["context"]["indices"], "A10_HFNET_WINDOW")
    else:
        require(
            authority.get("status") == "PASS_SEALED_A09_HFNET_SOURCE_STAMP_CANONICALIZATION",
            "A09_HFNET_AUTHORITY_STATE",
        )
        record = authority.get("output") or {}
        _require_record_identity(record, trajectory_actual, "A09_HFNET_CANONICAL_BINDING")
        require(authority.get("source_indices_inclusive") == item["context"]["indices"], "A09_HFNET_WINDOW")
    return {
        "status": authority.get("state") or authority.get("status"),
        "trajectory": trajectory_actual,
        "authority": identity(item["hfnet_authority"]),
    }


def backend_authority(sequence: str) -> dict[str, Any]:
    require(
        BACKEND_MULTIWINDOW_TERMINAL.is_file() and not BACKEND_MULTIWINDOW_TERMINAL.is_symlink(),
        "BACKEND_MULTIWINDOW_TERMINAL_MISSING",
    )
    multi = read_json(BACKEND_MULTIWINDOW_TERMINAL)
    outcomes = multi.get("window_outcomes") or {}
    require(set(outcomes) == set(SEQUENCE_ORDER), "BACKEND_MULTIWINDOW_SET")
    status = (outcomes.get(sequence) or {}).get("status")
    if status != "PASS_PAIRED_BACKENDS_ELIGIBLE_FOR_FIXED_EVALUATION":
        return {
            "sequence": sequence,
            "eligible": False,
            "backend_status": status,
            "reason": "BACKEND_WINDOW_NOT_PAIRED_ACCEPTED",
            "multiwindow_terminal": identity(BACKEND_MULTIWINDOW_TERMINAL),
        }
    eligible = (multi.get("decision") or {}).get("evaluation_eligible_windows") or []
    require(sequence in eligible, f"BACKEND_ELIGIBLE_LIST:{sequence}")
    window_terminal_path = BACKEND_ROOT / sequence / "terminal_backend_pair_receipt_v1.json"
    require(window_terminal_path.is_file() and not window_terminal_path.is_symlink(), f"BACKEND_WINDOW_TERMINAL_MISSING:{sequence}")
    terminal = read_json(window_terminal_path)
    require(terminal.get("status") == status, f"BACKEND_WINDOW_STATUS:{sequence}")
    require(terminal.get("arm_order") == list(BACKEND_ARM_ORDER), f"BACKEND_ARM_ORDER:{sequence}")
    decision = terminal.get("decision") or {}
    require(decision.get("fixed_two_layer_evaluation_may_run") is True, f"BACKEND_EVAL_AUTHORITY:{sequence}")
    require(decision.get("backend_retry_permitted") is False, f"BACKEND_RETRY_POLICY:{sequence}")
    require(decision.get("accuracy_evaluator_started") is False, f"BACKEND_PREMATURE_EVALUATOR:{sequence}")
    artifacts: dict[str, Any] = {}
    normalized_hashes: list[str] = []
    for backend_arm, public_arm in zip(BACKEND_ARM_ORDER, PRIMARY_ARM_ORDER):
        receipt_path = backend_arm_dir(sequence, backend_arm) / "formal_run_receipt_v1.json"
        require(receipt_path.is_file() and not receipt_path.is_symlink(), f"BACKEND_ARM_RECEIPT_MISSING:{sequence}:{backend_arm}")
        receipt_actual = identity(receipt_path)
        _require_record_identity(
            (terminal.get("arm_receipts") or {}).get(backend_arm) or {},
            receipt_actual,
            f"BACKEND_ARM_TERMINAL_BINDING:{sequence}:{backend_arm}",
        )
        receipt = read_json(receipt_path)
        require(receipt.get("status") == "PASS_BACKEND_ARM_ACCEPTED", f"BACKEND_ARM_STATUS:{sequence}:{backend_arm}")
        require(receipt.get("arm") == backend_arm, f"BACKEND_ARM_ID:{sequence}:{backend_arm}")
        require((receipt.get("claim_boundary") or {}).get("accuracy_evaluator_started") is False, f"BACKEND_ARM_PREMATURE_EVALUATOR:{sequence}:{backend_arm}")
        require((receipt.get("execution_integrity") or {}).get("no_automatic_retry") is True, f"BACKEND_ARM_RETRY:{sequence}:{backend_arm}")
        trajectory_path = fresh_trajectory(sequence, public_arm)
        config_path = fresh_config(sequence, public_arm)
        require(trajectory_path.is_file() and not trajectory_path.is_symlink(), f"FRESH_TRAJECTORY_MISSING:{sequence}:{backend_arm}")
        require(config_path.is_file() and not config_path.is_symlink(), f"FRESH_CONFIG_MISSING:{sequence}:{backend_arm}")
        trajectory_actual = identity(trajectory_path)
        config_actual = identity(config_path)
        outputs = receipt.get("outputs") or {}
        _require_record_identity(
            outputs.get("vins_output/vio.csv") or {},
            trajectory_actual,
            f"BACKEND_TRAJECTORY_BINDING:{sequence}:{backend_arm}",
        )
        _require_record_identity(
            outputs.get(SEQUENCES[sequence]["source_config_name"]) or {},
            config_actual,
            f"BACKEND_CONFIG_BINDING:{sequence}:{backend_arm}",
        )
        normalized_hash = hashlib.sha256(normalized_config(config_path)).hexdigest()
        require(
            normalized_hash
            == (receipt.get("artifact_audit") or {}).get("normalized_vins_config_sha256"),
            f"BACKEND_NORMALIZED_CONFIG_BINDING:{sequence}:{backend_arm}",
        )
        normalized_hashes.append(normalized_hash)
        artifacts[backend_arm] = {
            "receipt": receipt_actual,
            "trajectory": trajectory_actual,
            "config": config_actual,
        }
    require(len(set(normalized_hashes)) == 1, f"BACKEND_PAIR_CONFIG_ASYMMETRY:{sequence}")
    require(
        (terminal.get("pair_symmetry") or {}).get("normalized_vins_config_sha256")
        == normalized_hashes[0],
        f"BACKEND_WINDOW_CONFIG_BINDING:{sequence}",
    )
    return {
        "sequence": sequence,
        "eligible": True,
        "backend_status": status,
        "multiwindow_terminal": identity(BACKEND_MULTIWINDOW_TERMINAL),
        "window_terminal": identity(window_terminal_path),
        "arms": artifacts,
        "normalized_vins_config_sha256": normalized_hashes[0],
    }


def evaluation_input_identities(sequence: str, authority: Mapping[str, Any]) -> dict[str, Any]:
    result = static_input_identities(sequence)
    dynamic: list[Path] = [BACKEND_MULTIWINDOW_TERMINAL]
    if authority.get("eligible"):
        dynamic.append(BACKEND_ROOT / sequence / "terminal_backend_pair_receipt_v1.json")
        for arm in BACKEND_ARM_ORDER:
            dynamic.extend(
                [
                    backend_arm_dir(sequence, arm) / "formal_run_receipt_v1.json",
                    backend_arm_dir(sequence, arm) / "vins_output/vio.csv",
                    backend_arm_dir(sequence, arm) / SEQUENCES[sequence]["source_config_name"],
                ]
            )
    for path in dynamic:
        require(path.is_file() and not path.is_symlink(), f"DYNAMIC_INPUT_NOT_REGULAR:{path}")
        result[str(path)] = identity(path)
    return result


def native_gt_contract(sequence: str) -> dict[str, Any]:
    ros_path = "/opt/ros/noetic/lib/python3/dist-packages"
    if ros_path not in sys.path:
        sys.path.insert(0, ros_path)
    import rosbag  # type: ignore

    item = SEQUENCES[sequence]
    stamps: list[int] = []
    with rosbag.Bag(str(item["raw_bag"]), "r") as bag:
        for _, message, _ in bag.read_messages(topics=[REFERENCE_TOPIC]):
            stamps.append(message.header.stamp.secs * 1_000_000_000 + message.header.stamp.nsecs)
    require(len(stamps) == item["full_native_gt"], f"RAW_GT_TOTAL:{sequence}:{len(stamps)}")
    layers: dict[str, Any] = {}
    for layer, key in (("primary_pair", "primary"), ("context_fourarm", "context")):
        contract = item[key]
        inside = [stamp for stamp in stamps if contract["start_ns"] <= stamp <= contract["end_ns"]]
        require(len(inside) == contract["native_gt"], f"RAW_GT_WINDOW:{sequence}:{layer}:{len(inside)}")
        require(
            0 <= inside[0] - contract["start_ns"] <= 2_500_000_000,
            f"RAW_GT_FIRST_BRACKET:{sequence}:{layer}",
        )
        require(
            0 <= contract["end_ns"] - inside[-1] <= 2_500_000_000,
            f"RAW_GT_LAST_BRACKET:{sequence}:{layer}",
        )
        layers[layer] = {
            "native_messages": len(inside),
            "first_timestamp_ns": inside[0],
            "last_timestamp_ns": inside[-1],
        }
    return {
        "sequence": sequence,
        "topic": REFERENCE_TOPIC,
        "full_messages": len(stamps),
        "layers": layers,
    }


def ns_to_seconds(value: int) -> str:
    return f"{value // 1_000_000_000}.{value % 1_000_000_000:09d}"


def layer_contract(sequence: str, layer: str) -> Mapping[str, Any]:
    return SEQUENCES[sequence]["primary" if layer == "primary_pair" else "context"]


def evaluator_command(sequence: str, layer: str, output_dir: Path) -> list[str]:
    contract = layer_contract(sequence, layer)
    trajectories = trajectories_for(sequence, layer)
    configs = configs_for(sequence, layer)
    command = [
        "/usr/bin/python3.8",
        str(EVALUATOR),
        "--reference-bag",
        str(SEQUENCES[sequence]["raw_bag"]),
        "--reference-topic",
        REFERENCE_TOPIC,
    ]
    for name, path in trajectories.items():
        command.extend(["--arm", f"{name}={path}"])
    for name, path in configs.items():
        command.extend(["--arm-config", f"{name}={path}"])
    for name in trajectories:
        command.extend(["--arm-time-offset-s", f"{name}=0"])
    command.extend(
        [
            "--reference-time-offset-s",
            "0",
            "--nominal-reference-rate-hz",
            "1.0",
            "--nominal-estimate-rate-hz",
            "10.0",
            "--evaluation-rate-hz",
            "1.0",
            "--max-reference-gap-s",
            "2.5",
            "--max-estimate-gap-s",
            "0.25",
            "--window-start-s",
            ns_to_seconds(contract["start_ns"]),
            "--window-end-s",
            ns_to_seconds(contract["end_ns"]),
            "--rpe-delta-s",
            "1.0",
            "--min-ape-poses",
            "30",
            "--min-ape-span-s",
            "10.0",
            "--min-common-coverage",
            "0.70",
            "--min-rpe-pairs",
            "10",
            "--contrast-name",
            contract["contrast"],
            "--output-dir",
            str(output_dir),
            "--run-evo",
        ]
    )
    return command


def _finite_metric(value: Any, code: str) -> float | None:
    if value is None:
        return None
    require(isinstance(value, (int, float)), code)
    result = float(value)
    require(math.isfinite(result) and result >= 0.0, code)
    return result


def validate_summary(sequence: str, layer: str, summary: Mapping[str, Any]) -> dict[str, Any]:
    require(set(summary) == {"protocol", "support", "reference", "arms"}, f"SUMMARY_SCHEMA:{sequence}:{layer}")
    protocol = summary["protocol"]
    support = summary["support"]
    arms = summary["arms"]
    contract = layer_contract(sequence, layer)
    expected_arms = PRIMARY_ARM_ORDER if layer == "primary_pair" else CONTEXT_ARM_ORDER
    require(protocol.get("contrast_name") == contract["contrast"], f"CONTRAST:{sequence}:{layer}")
    require(protocol.get("body_to_camera_applied") is True, f"BODY_CAMERA:{sequence}:{layer}")
    require(protocol.get("rpe_semantics") == "aligned_global_frame_positional_delta", f"RPE_SEMANTICS:{sequence}:{layer}")
    require(protocol.get("reference_time_offset_s") == 0.0, f"REFERENCE_OFFSET:{sequence}:{layer}")
    require(set(protocol.get("arm_time_offsets_s") or {}) == set(expected_arms), f"ARM_OFFSET_SET:{sequence}:{layer}")
    require(all(value == 0.0 for value in protocol["arm_time_offsets_s"].values()), f"ARM_OFFSET_VALUE:{sequence}:{layer}")
    require(abs(float(protocol.get("evaluation_rate_hz")) - 1.0) <= 1e-12, f"EVAL_RATE:{sequence}:{layer}")
    require(abs(float(protocol.get("max_reference_gap_s")) - 2.5) <= 1e-12, f"REFERENCE_GAP:{sequence}:{layer}")
    require(abs(float(protocol.get("max_estimate_gap_s")) - 0.25) <= 1e-12, f"ESTIMATE_GAP:{sequence}:{layer}")
    require(abs(float(protocol.get("window_start_s")) - contract["start_ns"] / 1e9) <= 1e-6, f"WINDOW_START:{sequence}:{layer}")
    require(abs(float(protocol.get("window_end_s")) - contract["end_ns"] / 1e9) <= 1e-6, f"WINDOW_END:{sequence}:{layer}")
    require(set(arms) == set(expected_arms), f"ARM_SET:{sequence}:{layer}")
    grid_count = int(support.get("grid_count", -1))
    matched_count = int(support.get("matched_count", -1))
    rpe_pairs = int(support.get("rpe_pairs", -1))
    require(grid_count == contract["grid_count"], f"GRID_COUNT:{sequence}:{layer}:{grid_count}")
    require(0 <= matched_count <= grid_count, f"MATCHED_COUNT:{sequence}:{layer}:{matched_count}")
    require(0 <= rpe_pairs <= max(0, matched_count - 1), f"RPE_PAIRS:{sequence}:{layer}:{rpe_pairs}")
    coverage = float(support.get("common_coverage"))
    require(math.isfinite(coverage) and abs(coverage - matched_count / grid_count) <= 1e-12, f"COVERAGE:{sequence}:{layer}")
    require(summary["reference"].get("valid_grid_count") == grid_count, f"REFERENCE_SUPPORT:{sequence}:{layer}")
    ape_valid = support.get("ape_valid") is True
    rpe_valid = support.get("rpe_valid") is True
    if layer == "context_fourarm":
        require(ape_valid is False, f"CONTEXT_APE_MUST_BE_GATE_CLOSED:{sequence}")
    metrics: dict[str, dict[str, float | None]] = {}
    for name in expected_arms:
        row = arms[name]
        require(row.get("matched_count") == matched_count, f"ARM_MATCHED:{sequence}:{layer}:{name}")
        require(row.get("rpe_pairs") == rpe_pairs, f"ARM_RPE_PAIRS:{sequence}:{layer}:{name}")
        metrics[name] = {
            key: _finite_metric(row.get(key), f"METRIC:{sequence}:{layer}:{name}:{key}")
            for key in (
                "ape_rmse_m",
                "ape_median_m",
                "ape_max_m",
                "rpe_rmse_m",
                "rpe_median_m",
                "rpe_max_m",
            )
        }
    paired: dict[str, Any] | None = None
    if layer == "primary_pair":
        paired = {}
        for metric, gate in (("ape_rmse_m", ape_valid), ("rpe_rmse_m", rpe_valid)):
            klt = metrics[PRIMARY_ARM_ORDER[0]][metric]
            aqua = metrics[PRIMARY_ARM_ORDER[1]][metric]
            delta = None if klt is None or aqua is None else aqua - klt
            paired[metric] = {
                "klt": klt,
                "aquafe": aqua,
                "aquafe_minus_klt_m": delta,
                "aquafe_minus_klt_percent_of_klt": (
                    None if delta is None or not klt else 100.0 * delta / klt
                ),
                "claim_gate_open": gate,
            }
    status = (
        "PASS_PRIMARY_APE_RPE_GATES"
        if layer == "primary_pair" and ape_valid and rpe_valid
        else "COMPLETE_PRIMARY_SUPPORT_GATE_CLOSED"
        if layer == "primary_pair"
        else "COMPLETE_CONTEXT_RPE_GATE_OPEN_APE_PREDECLARED_CLOSED"
        if rpe_valid
        else "COMPLETE_CONTEXT_APE_AND_RPE_GATES_CLOSED"
    )
    return {
        "status": status,
        "sequence": sequence,
        "layer": layer,
        "support": {
            "native_gt_messages": contract["native_gt"],
            "grid_count": grid_count,
            "matched_count": matched_count,
            "common_coverage": coverage,
            "common_span_s": float(support.get("common_span_s")),
            "segment_count": int(support.get("segment_count")),
            "rpe_pairs": rpe_pairs,
            "ape_valid": ape_valid,
            "rpe_valid": rpe_valid,
        },
        "metrics_fixed_order": metrics,
        "primary_paired_contrast": paired,
        "claim_boundary": {
            "primary_controlled_pair": layer == "primary_pair",
            "context_different_system_contracts": layer == "context_fourarm",
            "ape_values_authorized": ape_valid and layer == "primary_pair",
            "rpe_values_authorized": rpe_valid,
            "context_ape_values_gate_closed_diagnostics_only": layer == "context_fourarm",
            "ranking_or_superiority_permitted": False,
            "statistical_inference_permitted": False,
        },
    }


def validate_evo(
    sequence: str, layer: str, path: Path, summary_result: Mapping[str, Any]
) -> dict[str, Any]:
    evo = read_json(path)
    expected_arms = PRIMARY_ARM_ORDER if layer == "primary_pair" else CONTEXT_ARM_ORDER
    require(evo.get("evo_version") == "1.31.1", f"EVO_VERSION:{sequence}:{layer}")
    require(evo.get("rpe_delta_frames") == 1, f"EVO_RPE_DELTA:{sequence}:{layer}")
    require(set(evo.get("arms") or {}) == set(expected_arms), f"EVO_ARM_SET:{sequence}:{layer}")
    maximum = 0.0
    expected_pairs = summary_result["support"]["rpe_pairs"]
    for name in expected_arms:
        row = evo["arms"][name]
        require(row.get("rpe_pair_count") == expected_pairs, f"EVO_RPE_PAIRS:{sequence}:{layer}:{name}")
        for key in ("ape_abs_diff_m", "rpe_abs_diff_m"):
            value = float(row[key])
            require(math.isfinite(value) and value <= 1e-5, f"EVO_TOLERANCE:{sequence}:{layer}:{name}:{key}:{value}")
            maximum = max(maximum, value)
    return {
        "version": "1.31.1",
        "maximum_rmse_abs_diff_m": maximum,
        "tolerance_m": 1e-5,
    }


def layer_paths(sequence: str, layer: str) -> tuple[Path, Path, Path]:
    base = OUTPUT_ROOT / sequence
    return (
        base / f".{layer}.stage_v1",
        base / layer,
        base / f"{layer}_failed_v1",
    )


def terminate_group(process: subprocess.Popen[Any]) -> None:
    if process.poll() is not None:
        return
    for sig, delay in ((signal.SIGINT, 10), (signal.SIGTERM, 5), (signal.SIGKILL, 2)):
        try:
            os.killpg(process.pid, sig)
        except ProcessLookupError:
            return
        try:
            process.wait(timeout=delay)
            return
        except subprocess.TimeoutExpired:
            continue


def run_child(command: list[str], log_path: Path) -> tuple[int, float]:
    started = time.monotonic()
    environment = {
        **os.environ,
        "PATH": f"/home/ma/.local/bin:{os.environ.get('PATH', '')}",
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONHASHSEED": "0",
    }
    with log_path.open("xb") as log:
        process = subprocess.Popen(
            command,
            cwd=str(ROOT),
            env=environment,
            stdout=log,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        try:
            return_code = process.wait(timeout=300)
        except BaseException:
            terminate_group(process)
            raise
    return return_code, time.monotonic() - started


def output_identities(directory: Path, names: Iterable[str]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for name in names:
        path = directory / name
        require(path.is_file() and not path.is_symlink(), f"OUTPUT_MISSING:{path}")
        result[name] = identity(path)
    return result


def static_preflight() -> dict[str, Any]:
    require(not OUTPUT_ROOT.exists() and not OUTPUT_ROOT.is_symlink(), "OUTPUT_ROOT_EXISTS")
    require(OUTPUT_ROOT.parent.is_dir(), "OUTPUT_PARENT_MISSING")
    require(shutil.disk_usage(OUTPUT_ROOT.parent).free >= 5_000_000_000, "INSUFFICIENT_SPACE")
    inputs = static_input_identities()
    native = {sequence: native_gt_contract(sequence) for sequence in SEQUENCE_ORDER}
    authorities = {sequence: hfnet_authority(sequence) for sequence in SEQUENCE_ORDER}
    return {
        "status": "READY_STATIC_WAITING_FOR_PAIRED_BACKENDS",
        "sequence_order": list(SEQUENCE_ORDER),
        "layer_order_within_window": list(LAYER_ORDER),
        "inputs": inputs,
        "native_gt_contracts": native,
        "hfnet_authorities": authorities,
        "no_retry": True,
    }


def preflight() -> dict[str, Any]:
    static = static_preflight()
    backend = {sequence: backend_authority(sequence) for sequence in SEQUENCE_ORDER}
    commands: dict[str, dict[str, list[str]]] = {}
    for sequence in SEQUENCE_ORDER:
        commands[sequence] = {}
        if backend[sequence]["eligible"]:
            evaluation_input_identities(sequence, backend[sequence])
            for layer in LAYER_ORDER:
                commands[sequence][layer] = evaluator_command(
                    sequence, layer, layer_paths(sequence, layer)[1] / "common_support"
                )
    return {
        **static,
        "status": "READY_ACTION_GATED_TWO_LAYER_COMMON_SUPPORT_EVALUATION",
        "backend_authorities": backend,
        "commands_for_backend_eligible_windows": commands,
        "ineligible_window_policy": "RECORD_SKIP_START_ZERO_EVALUATORS",
    }


def stage_failure(sequence: str, layer: str, error: BaseException) -> None:
    stage, accepted, failure = layer_paths(sequence, layer)
    if accepted.is_symlink():
        accepted.unlink()
    if not stage.is_dir() or stage.is_symlink() or failure.exists() or failure.is_symlink():
        return
    try:
        write_json(
            stage / "failure_receipt_v1.json",
            {
                "status": "FAILED_LAYER_RETAINED_NO_RETRY",
                "sequence": sequence,
                "layer": layer,
                "error_type": type(error).__name__,
                "error": str(error),
                "recorded_at_utc": now(),
            },
        )
        stage.rename(failure)
    except OSError:
        pass


def execute_layer(
    sequence: str,
    layer: str,
    inputs_before: Mapping[str, Any],
    authority: Mapping[str, Any],
    native: Mapping[str, Any],
) -> dict[str, Any]:
    stage, accepted, failure = layer_paths(sequence, layer)
    for path, code in ((stage, "STAGE"), (accepted, "ACCEPTED"), (failure, "FAILURE")):
        require(not path.exists() and not path.is_symlink(), f"{code}_EXISTS:{sequence}:{layer}")
    stage.mkdir(mode=0o755)
    accepted.symlink_to(stage, target_is_directory=True)
    command = evaluator_command(sequence, layer, accepted / "common_support")
    claim = {
        "schema_version": "positive-klt-lifecycle-rearmed-evaluation-start-claim-v1",
        "status": "CLAIMED_BEFORE_SINGLE_EVALUATOR_POPEN",
        "sequence": sequence,
        "layer": layer,
        "created_at_utc": now(),
        "command": command,
        "inputs": inputs_before,
        "backend_authority": authority,
        "native_gt_contract": native["layers"][layer],
        "no_retry": True,
    }
    write_json(stage / "process_start_claim_v1.json", claim)
    started = now()
    try:
        return_code, wall_time = run_child(command, stage / "evaluator_process.log")
        require(return_code == 0, f"EVALUATOR_RETURN_CODE:{sequence}:{layer}:{return_code}")
        summary_path = stage / "common_support/common_support_summary.json"
        evo_path = stage / "common_support/evo_crosscheck.json"
        require(summary_path.is_file(), f"SUMMARY_MISSING:{sequence}:{layer}")
        require(evo_path.is_file(), f"EVO_MISSING:{sequence}:{layer}")
        adjudication = validate_summary(sequence, layer, read_json(summary_path))
        adjudication["evo_crosscheck"] = validate_evo(sequence, layer, evo_path, adjudication)
        write_json(stage / "adjudication_v1.json", adjudication)
        inputs_after = refresh(inputs_before)
        require(same_identity_maps(inputs_before, inputs_after), f"INPUT_IDENTITY_CHANGED:{sequence}:{layer}")
        outputs = output_identities(
            stage,
            (
                "process_start_claim_v1.json",
                "evaluator_process.log",
                "common_support/common_support_summary.json",
                "common_support/common_support_metrics.csv",
                "common_support/common_grid_audit.csv",
                "common_support/evo_crosscheck.json",
                "adjudication_v1.json",
            ),
        )
        receipt = {
            "schema_version": "positive-klt-lifecycle-rearmed-evaluation-layer-receipt-v1",
            "status": "COMPLETE_FIXED_COMMON_SUPPORT_LAYER",
            "sequence": sequence,
            "layer": layer,
            "started_at_utc": started,
            "ended_at_utc": now(),
            "terminal_process": {
                "return_code": return_code,
                "single_popen": True,
                "wall_time_seconds": wall_time,
            },
            "command": command,
            "inputs_before": inputs_before,
            "inputs_after": inputs_after,
            "outputs": outputs,
            "adjudication": adjudication,
            "no_retry": True,
        }
        write_json(stage / "terminal_layer_receipt_v1.json", receipt)
        accepted.unlink()
        stage.rename(accepted)
        return {
            "status": receipt["status"],
            "adjudication": adjudication,
            "terminal_receipt": identity(accepted / "terminal_layer_receipt_v1.json"),
        }
    except BaseException as error:
        stage_failure(sequence, layer, error)
        raise


def format_value(value: Any) -> str:
    return "NA" if value is None else f"{float(value):.6f}"


def report_markdown(sequence: str, outcomes: Mapping[str, Any]) -> str:
    lines = [
        f"# {sequence.upper()} lifecycle-rearmed two-layer evaluation v1",
        "",
        "Status: secondary development-exposed evidence; one trajectory per arm.",
        "",
    ]
    primary = outcomes.get("primary_pair") or {}
    if primary.get("status") == "COMPLETE_FIXED_COMMON_SUPPORT_LAYER":
        result = primary["adjudication"]
        lines.extend(
            [
                "## Primary controlled fresh pair",
                "",
                "| Arm | APE RMSE (m) | 1 s RPE RMSE (m) |",
                "|---|---:|---:|",
            ]
        )
        for name in PRIMARY_ARM_ORDER:
            row = result["metrics_fixed_order"][name]
            lines.append(
                f"| `{name}` | {format_value(row['ape_rmse_m'])} | {format_value(row['rpe_rmse_m'])} |"
            )
        pair = result["primary_paired_contrast"]
        lines.extend(
            [
                "",
                f"- APE gate: `{result['support']['ape_valid']}`; AQUA minus KLT RMSE: "
                f"`{format_value(pair['ape_rmse_m']['aquafe_minus_klt_m'])} m`.",
                f"- RPE gate: `{result['support']['rpe_valid']}`; AQUA minus KLT RMSE: "
                f"`{format_value(pair['rpe_rmse_m']['aquafe_minus_klt_m'])} m`.",
                f"- Joint support: `{result['support']['matched_count']}/{result['support']['grid_count']}`; "
                f"RPE pairs: `{result['support']['rpe_pairs']}`.",
                "",
            ]
        )
    else:
        lines.extend(["## Primary controlled fresh pair", "", f"Retained outcome: `{primary.get('status')}`.", ""])
    context = outcomes.get("context_fourarm") or {}
    if context.get("status") == "COMPLETE_FIXED_COMMON_SUPPORT_LAYER":
        result = context["adjudication"]
        lines.extend(
            [
                "## Exact-score four-arm context",
                "",
                "| Context arm | Gate-closed APE diagnostic RMSE (m) | Descriptive 1 s RPE RMSE (m) |",
                "|---|---:|---:|",
            ]
        )
        for name in CONTEXT_ARM_ORDER:
            row = result["metrics_fixed_order"][name]
            lines.append(
                f"| `{name}` | {format_value(row['ape_rmse_m'])} | {format_value(row['rpe_rmse_m'])} |"
            )
        lines.extend(
            [
                "",
                f"- APE gate: `{result['support']['ape_valid']}` by construction on the 20-point score grid; "
                "its displayed values are not authorized comparisons.",
                f"- RPE gate: `{result['support']['rpe_valid']}`; joint support "
                f"`{result['support']['matched_count']}/{result['support']['grid_count']}`.",
                "- Vanilla and HFNet are descriptive context systems, not causal ablation arms.",
                "",
            ]
        )
    else:
        lines.extend(["## Exact-score four-arm context", "", f"Retained outcome: `{context.get('status')}`.", ""])
    lines.extend(
        [
            "No ranking, significance, uncertainty, runtime, confirmatory, or general-superiority claim is permitted.",
        ]
    )
    return "\n".join(lines)


def execute_sequence(
    sequence: str, authority: Mapping[str, Any], native: Mapping[str, Any]
) -> dict[str, Any]:
    directory = OUTPUT_ROOT / sequence
    require(not directory.exists() and not directory.is_symlink(), f"SEQUENCE_OUTPUT_EXISTS:{sequence}")
    directory.mkdir(mode=0o755)
    if not authority.get("eligible"):
        skip = {
            "schema_version": "positive-klt-lifecycle-rearmed-evaluation-skip-v1",
            "status": "SKIPPED_BACKEND_WINDOW_NOT_ELIGIBLE",
            "sequence": sequence,
            "recorded_at_utc": now(),
            "backend_authority": authority,
            "evaluator_process_starts": 0,
            "retry_count": 0,
        }
        path = directory / "evaluation_skip_receipt_v1.json"
        write_json(path, skip)
        return {**skip, "terminal_receipt": identity(path)}
    inputs = evaluation_input_identities(sequence, authority)
    outcomes: dict[str, Any] = {}
    for layer in LAYER_ORDER:
        try:
            outcomes[layer] = execute_layer(sequence, layer, inputs, authority, native)
        except Exception as error:
            failure_path = layer_paths(sequence, layer)[2] / "failure_receipt_v1.json"
            outcomes[layer] = {
                "status": "FAILED_LAYER_RETAINED_NO_RETRY",
                "error_type": type(error).__name__,
                "error": str(error),
                "failure_receipt": identity(failure_path) if failure_path.is_file() else None,
            }
    write_json(directory / "sequence_summary_v1.json", {"sequence": sequence, "layers": outcomes})
    write_text(directory / "analysis-report.md", report_markdown(sequence, outcomes))
    failures = [layer for layer in LAYER_ORDER if outcomes[layer]["status"] != "COMPLETE_FIXED_COMMON_SUPPORT_LAYER"]
    terminal = {
        "schema_version": "positive-klt-lifecycle-rearmed-sequence-evaluation-terminal-v1",
        "status": "COMPLETE_WITH_RETAINED_LAYER_FAILURES" if failures else "COMPLETE_TWO_LAYER_EVALUATION",
        "sequence": sequence,
        "recorded_at_utc": now(),
        "layer_order": list(LAYER_ORDER),
        "layer_outcomes": {
            layer: {
                "status": outcomes[layer]["status"],
                "terminal_receipt": outcomes[layer].get("terminal_receipt"),
                "adjudication_status": (outcomes[layer].get("adjudication") or {}).get("status"),
            }
            for layer in LAYER_ORDER
        },
        "retained_failures": failures,
        "retry_permitted": False,
    }
    path = directory / "terminal_sequence_evaluation_receipt_v1.json"
    write_json(path, terminal)
    return {**terminal, "terminal_receipt": identity(path)}


def execute() -> dict[str, Any]:
    ready = preflight()
    OUTPUT_ROOT.mkdir(mode=0o755)
    LOCK_PATH.touch(exist_ok=False)
    with LOCK_PATH.open("r+") as lock_stream:
        fcntl.flock(lock_stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        outcomes: dict[str, Any] = {}
        for sequence in SEQUENCE_ORDER:
            authority = backend_authority(sequence)
            native = ready["native_gt_contracts"][sequence]
            outcomes[sequence] = execute_sequence(sequence, authority, native)
        failures = [sequence for sequence in SEQUENCE_ORDER if outcomes[sequence]["status"] == "COMPLETE_WITH_RETAINED_LAYER_FAILURES"]
        skips = [sequence for sequence in SEQUENCE_ORDER if outcomes[sequence]["status"] == "SKIPPED_BACKEND_WINDOW_NOT_ELIGIBLE"]
        status = (
            "COMPLETE_WITH_RETAINED_EVALUATION_FAILURES"
            if failures
            else "COMPLETE_WITH_BACKEND_INELIGIBLE_SKIPS"
            if skips
            else "COMPLETE_ALL_TWO_LAYER_EVALUATIONS"
        )
        terminal = {
            "schema_version": "positive-klt-lifecycle-rearmed-multiwindow-evaluation-terminal-v1",
            "status": status,
            "recorded_at_utc": now(),
            "sequence_order": list(SEQUENCE_ORDER),
            "layer_order_within_window": list(LAYER_ORDER),
            "sequence_outcomes": {
                sequence: {
                    "status": outcomes[sequence]["status"],
                    "terminal_receipt": outcomes[sequence]["terminal_receipt"],
                }
                for sequence in SEQUENCE_ORDER
            },
            "retained_failures": failures,
            "backend_ineligible_skips": skips,
            "retry_permitted": False,
            "claim_boundary": {
                "development_exposed_roster": True,
                "independent_trajectory_count_per_method_per_window": 1,
                "statistical_inference_permitted": False,
                "ranking_or_general_superiority_permitted": False,
            },
        }
        write_json(TERMINAL_RECEIPT, terminal)
        return terminal


def audit_existing() -> dict[str, Any]:
    require(TERMINAL_RECEIPT.is_file() and not TERMINAL_RECEIPT.is_symlink(), "TERMINAL_MISSING")
    terminal = read_json(TERMINAL_RECEIPT)
    require(terminal.get("sequence_order") == list(SEQUENCE_ORDER), "TERMINAL_SEQUENCE_ORDER")
    static_input_identities()
    native = {sequence: native_gt_contract(sequence) for sequence in SEQUENCE_ORDER}
    audits: dict[str, Any] = {}
    for sequence in SEQUENCE_ORDER:
        sequence_status = terminal["sequence_outcomes"][sequence]["status"]
        if sequence_status == "SKIPPED_BACKEND_WINDOW_NOT_ELIGIBLE":
            skip = read_json(OUTPUT_ROOT / sequence / "evaluation_skip_receipt_v1.json")
            require(skip.get("evaluator_process_starts") == 0, f"SKIP_PROCESS_COUNT:{sequence}")
            audits[sequence] = {"status": sequence_status}
            continue
        authority = backend_authority(sequence)
        evaluation_input_identities(sequence, authority)
        layer_audits: dict[str, Any] = {}
        for layer in LAYER_ORDER:
            accepted = layer_paths(sequence, layer)[1]
            failed = layer_paths(sequence, layer)[2]
            if accepted.is_dir() and not accepted.is_symlink():
                adjudication = validate_summary(
                    sequence,
                    layer,
                    read_json(accepted / "common_support/common_support_summary.json"),
                )
                adjudication["evo_crosscheck"] = validate_evo(
                    sequence,
                    layer,
                    accepted / "common_support/evo_crosscheck.json",
                    adjudication,
                )
                layer_audits[layer] = {"status": "PASS_EXISTING_LAYER_AUDIT", "adjudication": adjudication}
            else:
                require(failed.is_dir() and not failed.is_symlink(), f"LAYER_OUTPUT_MISSING:{sequence}:{layer}")
                layer_audits[layer] = {"status": "RETAINED_LAYER_FAILURE"}
        audits[sequence] = {"status": sequence_status, "native_gt": native[sequence], "layers": layer_audits}
    return {
        "status": "PASS_EXISTING_MULTIWINDOW_EVALUATION_AUDIT",
        "terminal_status": terminal.get("status"),
        "windows": audits,
        "terminal_receipt": identity(TERMINAL_RECEIPT),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("static-preflight", "preflight", "run", "audit"))
    args = parser.parse_args()
    try:
        if args.command == "static-preflight":
            result = static_preflight()
        elif args.command == "preflight":
            result = preflight()
        elif args.command == "run":
            result = execute()
        else:
            result = audit_existing()
        print(json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False))
        return 0
    except (
        EvaluationError,
        OSError,
        ValueError,
        csv.Error,
        json.JSONDecodeError,
        subprocess.SubprocessError,
    ) as error:
        print(
            f"POSITIVE_KLT_EVALUATION_V1_ERROR:{type(error).__name__}:{error}",
            file=sys.stderr,
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
