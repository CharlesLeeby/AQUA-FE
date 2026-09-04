#!/usr/bin/env python3
"""Freeze the 60-job P07 frontend export queue and 20 conditional D slots."""

from __future__ import annotations

import csv
import hashlib
import json
import os
import shlex
from pathlib import Path

try:
    from scripts.build_nativeq_backend_contract import file_record
    from scripts.build_p07_execution_adapter_lock_v1 import adapter_hash
except ModuleNotFoundError:  # Direct ``python3 scripts/...`` execution.
    from build_nativeq_backend_contract import file_record  # type: ignore
    from build_p07_execution_adapter_lock_v1 import adapter_hash  # type: ignore


ROOT = Path(__file__).resolve().parents[1]
BUNDLE = ROOT / "papers/ieee_sensors_journal_experiments"
P07 = BUNDLE / "p07"
MANIFEST = BUNDLE / "dataset_manifest_v4.csv"
ARM_ORDER = BUNDLE / "arm_order.csv"
METHOD_LOCK = BUNDLE / "method_lock.json"
ADAPTER_LOCK = P07 / "execution_adapter_lock_v1.json"
ADAPTER_ADDENDUM = P07 / "execution_adapter_addendum_v1.md"
EXPORT_QUEUE = P07 / "frontend_export_queue_v1.csv"
D_QUEUE = P07 / "d_applicability_queue_v1.csv"
QUEUE_LOCK = P07 / "frontend_queue_lock_v1.json"

QUEUE_VERSION = "isj-p07-frontend-export-queue-v1"
OUTCOME_BOUNDARY = "FRONTEND_EXPORT_ONLY_NO_VINS_APE_RPE_TRAJECTORY"
B1 = "B1_klt_nativeq_v3"
P_ARM = "P_legacy_nativeq_xfeat_seedchain_v3"
M_ARM = "M_xfeat_pairwise_nativeq_v1"
D_ARM = "D_legacy_exact_lineage_drop_v3"
EXPORT_ARMS = (B1, P_ARM, M_ARM)

ROOT_BY_FAMILY = {
    "ntnu": "logs/ntnu_vins",
    "aqualoc_archaeology": "logs/aqualoc_archaeo_vins",
    "aqualoc_harbor": "logs/aqualoc_real_vins",
    "afrl": "logs/afrl_cave_v31",
}

EXPORT_FIELDS = [
    "schema_version",
    "queue_index",
    "assignment_rank",
    "arm_order_position",
    "window_id",
    "dataset_family",
    "data_domain",
    "sequence",
    "texture_stratum",
    "selection_tier",
    "arm",
    "tag",
    "command",
    "command_sha256",
    "expected_run_root",
    "expected_feature_bag",
    "feature_bag_resolution",
    "dependency",
    "status",
    "outcome_boundary",
]

D_FIELDS = [
    "schema_version",
    "slot_index",
    "window_id",
    "dataset_family",
    "data_domain",
    "sequence",
    "texture_stratum",
    "selection_tier",
    "arm",
    "proposed_queue_index",
    "proposed_tag_base",
    "applicability",
    "applicability_rule",
    "resolution_time",
    "derivation",
    "required_audit",
    "algorithmic_replay_slots",
    "status",
    "outcome_boundary",
]


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        fields = list(reader.fieldnames or [])
        if not fields or len(fields) != len(set(fields)):
            raise ValueError(f"invalid CSV header: {path}")
        rows = list(reader)
    if any(None in row for row in rows):
        raise ValueError(f"ragged CSV: {path}")
    return rows


def queue_hash(payload: dict[str, object]) -> str:
    clone = dict(payload)
    clone.pop("queue_lock_hash", None)
    encoded = json.dumps(
        clone, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def number(value: str | float) -> str:
    parsed = float(value)
    return str(int(parsed)) if parsed.is_integer() else format(parsed, ".9g")


def slug(value: str) -> str:
    return "".join(character.lower() if character.isalnum() else "_" for character in value).strip("_")


def family_args(window: dict[str, str]) -> list[str]:
    family = window["dataset_family"]
    sequence = window["sequence"]
    start = float(window["window_start_s"])
    end = float(window["window_end_s"])
    if family.startswith("aqualoc_"):
        return [family, sequence, str(round(start * 20.0)), str(round(end * 20.0)), "2"]
    return [family, sequence, number(start), number(end - start), "2"]


def proposed_args(window: dict[str, str]) -> list[str]:
    family = window["dataset_family"]
    common = family_args(window)
    if family == "ntnu":
        return ["ntnu", common[1], common[2], common[3], "hybrid_xfeat", "2"]
    if family == "aqualoc_archaeology":
        return ["aqualoc_archaeo", str(int(common[1][1:])), common[2], common[3], "hybrid_xfeat", "2"]
    if family == "aqualoc_harbor":
        return ["aqualoc_real", common[1], common[2], common[3], "hybrid_xfeat", "2"]
    if family == "afrl":
        return ["afrl_dataset", common[1], common[2], common[3], "hybrid_xfeat", "2"]
    raise ValueError(f"unsupported family: {family}")


def modern_args(window: dict[str, str]) -> list[str]:
    common = family_args(window)
    if window["dataset_family"] == "aqualoc_archaeology":
        common[1] = str(int(common[1][1:]))
    return common


def command_for(arm: str, window: dict[str, str], tag: str) -> tuple[str, str, str]:
    family = window["dataset_family"]
    run_root = ROOT_BY_FAMILY[family]
    if arm == B1:
        argv = ["bash", "scripts/run_isj_b1_klt_nativeq_guarded_v1.sh", *family_args(window)]
        command = shlex.join(["RUN_VINS=0", "FORCE_EXPORT=1", f"TAG={tag}", *argv])
        bag = f"{run_root}/external_klt_every2_{tag}/features.bag"
        resolution = "EXACT_PATH"
    elif arm == M_ARM:
        argv = ["bash", "scripts/run_p05_modern_xfeat_baseline_guarded_v2.sh", *modern_args(window)]
        command = shlex.join(["RUN_VINS=0", "FORCE_EXPORT=1", f"TAG={tag}", *argv])
        bag = f"{run_root}/external_xfeat_every2_{tag}/features.bag"
        resolution = "EXACT_PATH"
    elif arm == P_ARM:
        argv = ["bash", "scripts/run_isj_nativeq_contract_guarded_v4.sh", *proposed_args(window)]
        command = shlex.join(["RUN_VINS=0", "FORCE_EXPORT=1", f"TAG_BASE={tag}", *argv])
        bag = ""
        resolution = "READ_FINAL_RUN_FROM_ARBITRATION_SUMMARY_UNDER_TAG_BASE"
    else:
        raise ValueError(f"not a frontend export arm: {arm}")
    # shlex quotes NAME=VALUE as ordinary argv tokens; restore shell assignments.
    command = command.replace("'RUN_VINS=0'", "RUN_VINS=0").replace(
        "'FORCE_EXPORT=1'", "FORCE_EXPORT=1"
    ).replace(f"'TAG={tag}'", f"TAG={tag}").replace(
        f"'TAG_BASE={tag}'", f"TAG_BASE={tag}"
    )
    return command, run_root, bag + ("" if bag else "")


def build_rows() -> tuple[list[dict[str, object]], list[dict[str, object]], dict[str, object]]:
    method = json.loads(METHOD_LOCK.read_text(encoding="utf-8"))
    adapter = json.loads(ADAPTER_LOCK.read_text(encoding="utf-8"))
    if method.get("method_lock_hash") != adapter.get("final_method_lock_hash"):
        raise ValueError("adapter/final method lock mismatch")
    if adapter_hash(adapter) != adapter.get("adapter_lock_hash"):
        raise ValueError("execution adapter lock hash mismatch")
    if str(adapter["adapter_lock_hash"]) not in ADAPTER_ADDENDUM.read_text(encoding="utf-8"):
        raise ValueError("execution adapter addendum hash mismatch")
    manifest = {row["window_id"]: row for row in read_csv(MANIFEST)}
    order = read_csv(ARM_ORDER)
    ordered_external = sorted(
        (row for row in order if row["arm"] in EXPORT_ARMS),
        key=lambda row: (int(row["assignment_rank"]), int(row["order_position"])),
    )
    exports: list[dict[str, object]] = []
    proposed_index: dict[str, tuple[int, str]] = {}
    for queue_index, order_row in enumerate(ordered_external, 1):
        window = manifest[order_row["window_id"]]
        arm = order_row["arm"]
        arm_slug = {B1: "b1", P_ARM: "p", M_ARM: "m"}[arm]
        tag = f"isj_p07_{slug(window['window_id'])}_{arm_slug}_attempt01"
        command, run_root, bag = command_for(arm, window, tag)
        if "RUN_VINS=0" not in command or "FORCE_EXPORT=1" not in command:
            raise ValueError("frontend queue command is not export-only/fresh")
        row: dict[str, object] = {
            "schema_version": QUEUE_VERSION,
            "queue_index": queue_index,
            "assignment_rank": order_row["assignment_rank"],
            "arm_order_position": order_row["order_position"],
            "window_id": window["window_id"],
            "dataset_family": window["dataset_family"],
            "data_domain": window["data_domain"],
            "sequence": window["sequence"],
            "texture_stratum": window["texture_stratum"],
            "selection_tier": window["selection_tier"],
            "arm": arm,
            "tag": tag,
            "command": command,
            "command_sha256": hashlib.sha256(command.encode("utf-8")).hexdigest(),
            "expected_run_root": run_root,
            "expected_feature_bag": bag,
            "feature_bag_resolution": (
                "EXACT_PATH" if bag else "READ_FINAL_RUN_FROM_ARBITRATION_SUMMARY_UNDER_TAG_BASE"
            ),
            "dependency": "NONE",
            "status": "PLANNED",
            "outcome_boundary": OUTCOME_BOUNDARY,
        }
        exports.append(row)
        if arm == P_ARM:
            proposed_index[window["window_id"]] = (queue_index, tag)
    if len(exports) != 60 or any(
        sum(row["arm"] == arm for row in exports) != 20 for arm in EXPORT_ARMS
    ):
        raise ValueError("frontend queue is not 20 x B1/P/M")

    d_rows: list[dict[str, object]] = []
    for slot_index, window in enumerate(
        sorted(manifest.values(), key=lambda row: row["window_id"]), 1
    ):
        queue_index, tag = proposed_index[window["window_id"]]
        d_rows.append(
            {
                "schema_version": "isj-p07-d-applicability-queue-v1",
                "slot_index": slot_index,
                "window_id": window["window_id"],
                "dataset_family": window["dataset_family"],
                "data_domain": window["data_domain"],
                "sequence": window["sequence"],
                "texture_stratum": window["texture_stratum"],
                "selection_tier": window["selection_tier"],
                "arm": D_ARM,
                "proposed_queue_index": queue_index,
                "proposed_tag_base": tag,
                "applicability": "PENDING_APPLICABILITY",
                "applicability_rule": "accepted_learned_born_lineage_count>0",
                "resolution_time": "AFTER_P_EXPORT_BEFORE_TRAJECTORY_OUTCOME",
                "derivation": "EXACT_WHOLE_LEARNED_BORN_ID_LINEAGE_DROP",
                "required_audit": "PASS_EXACT_WHOLE_LINEAGE_DROP",
                "algorithmic_replay_slots": 3,
                "status": "PLANNED",
                "outcome_boundary": OUTCOME_BOUNDARY,
            }
        )
    lock: dict[str, object] = {
        "schema_version": "isj-p07-frontend-queue-lock-v1",
        "status": "FROZEN_FOR_EXPORT_EXECUTION",
        "final_method_lock_hash": method["method_lock_hash"],
        "execution_adapter_lock_hash": adapter["adapter_lock_hash"],
        "frontend_export_jobs": 60,
        "jobs_per_arm": {B1: 20, P_ARM: 20, M_ARM: 20},
        "conditional_d_slots": 20,
        "commands_require": ["RUN_VINS=0", "FORCE_EXPORT=1"],
        "outcome_boundary": OUTCOME_BOUNDARY,
        "held_out_trajectory_outcome_read": False,
        "artifacts": [
            file_record(path, root=ROOT)
            for path in (
                MANIFEST,
                ARM_ORDER,
                METHOD_LOCK,
                ADAPTER_LOCK,
                ADAPTER_ADDENDUM,
                ROOT / "scripts/build_p07_frontend_export_queue_v1.py",
                ROOT / "scripts/tests/test_p07_frontend_export_queue_v1.py",
            )
        ],
    }
    return exports, d_rows, lock


def render_csv(fields: list[str], rows: list[dict[str, object]]) -> bytes:
    import io

    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=fields)
    writer.writeheader()
    writer.writerows(rows)
    return stream.getvalue().encode("utf-8")


def write_outputs() -> None:
    exports, d_rows, lock = build_rows()
    export_content = render_csv(EXPORT_FIELDS, exports)
    d_content = render_csv(D_FIELDS, d_rows)
    lock["frontend_export_queue"] = {
        "path": EXPORT_QUEUE.relative_to(ROOT).as_posix(),
        "sha256": hashlib.sha256(export_content).hexdigest(),
        "size_bytes": len(export_content),
    }
    lock["d_applicability_queue"] = {
        "path": D_QUEUE.relative_to(ROOT).as_posix(),
        "sha256": hashlib.sha256(d_content).hexdigest(),
        "size_bytes": len(d_content),
    }
    lock["queue_lock_hash"] = queue_hash(lock)
    lock_content = (
        json.dumps(lock, indent=2, sort_keys=True, ensure_ascii=True) + "\n"
    ).encode("utf-8")
    outputs = {EXPORT_QUEUE: export_content, D_QUEUE: d_content, QUEUE_LOCK: lock_content}
    existing = [str(path) for path in outputs if path.exists()]
    if existing:
        raise FileExistsError(f"refusing to overwrite frontend queues: {existing}")
    temporary = {
        path: path.with_name(f"{path.name}.partial.{os.getpid()}") for path in outputs
    }
    for path, content in outputs.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary[path].write_bytes(content)
    for path in outputs:
        os.replace(temporary[path], path)
    print(
        f"P07_FRONTEND_QUEUE_FROZEN jobs={len(exports)} d_slots={len(d_rows)} "
        f"hash={lock['queue_lock_hash']}"
    )


if __name__ == "__main__":
    write_outputs()
