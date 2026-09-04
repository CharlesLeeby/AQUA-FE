#!/usr/bin/env python3
"""Evaluate functional P07 replays with the frozen G0 common-support metric."""

from __future__ import annotations

import argparse
import csv
from decimal import Decimal
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys


ROOT = Path("/home/ma/AQUA-FE_WS")
P07 = ROOT / "papers/ieee_sensors_journal_experiments/p07"
QUEUE = Path(os.environ.get("P07_COMPLETION_QUEUE", str(P07 / "backend_replay_queue_v1.csv")))
REFERENCE_AUDIT = ROOT / "papers/ieee_sensors_journal_experiments/reference_audit.csv"
DATA_MANIFEST = ROOT / "papers/ieee_sensors_journal_experiments/data_eligibility_manifest.csv"
RUNTIME = Path(
    os.environ.get(
        "P07_COMPLETION_RUNTIME",
        "/media/ma/Data/AQUA-FE_WS_storage_offload/p07_backend_completion_serial_v2",
    )
)
EVALUATOR = ROOT / "scripts/evaluate_vins_common_support_epoch_v2.py"
CONTRASTS = {
    "P_vs_B0": ("P_legacy_nativeq_xfeat_seedchain_v3", "B0_native_vins_origin_v1"),
    "P_vs_B1": ("P_legacy_nativeq_xfeat_seedchain_v3", "B1_klt_nativeq_v3"),
    "P_vs_M": ("P_legacy_nativeq_xfeat_seedchain_v3", "M_xfeat_pairwise_nativeq_v1"),
}
REFERENCE_TOPICS = {
    "aqualoc_archaeology": "/aqualoc/colmap_gt",
    "aqualoc_harbor": "/aqualoc/colmap_gt",
    "afrl": "/afrl/colmap_gt",
}
CONFIG_NAMES = {
    "aqualoc_archaeology": "vins_aqualoc_archaeo_{mode}.yaml",
    "aqualoc_harbor": "vins_aqualoc_{mode}.yaml",
    "ntnu": "vins_ntnu_{mode}.yaml",
    "afrl": "vins_afrl_cave_{mode}.yaml",
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def atomic_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    temporary.replace(path)


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as stream:
        return list(csv.DictReader(stream))


def backend_receipt(row: dict[str, str]) -> dict:
    path = RUNTIME / "receipts" / f"queue_{int(row['queue_index']):03d}.json"
    if not path.is_file():
        return {"status": "PENDING", "receipt": str(path)}
    payload = json.loads(path.read_text(encoding="utf-8"))
    status = payload.get("status")
    output = payload.get("output", {})
    if status == "FAILED" and payload.get("return_code") == 1:
        if output.get("vio_exists") and int(output.get("vio_rows", 0)) == 0:
            status = "ALGORITHM_FAILURE"
    return {**payload, "status": status, "receipt": str(path)}


def run_config(row: dict[str, str], receipt: dict) -> Path:
    run_dir = Path(receipt["output"]["run_dir"])
    config = run_dir / CONFIG_NAMES[row["dataset_family"]].format(mode=row["runner_mode"])
    if not config.is_file():
        raise RuntimeError(f"missing run config: {config}")
    return config


def audit_row(family: str, sequence: str) -> dict[str, str]:
    rows = [
        row
        for row in read_csv(REFERENCE_AUDIT)
        if row["dataset_family"] == family and row["sequence"] == sequence
    ]
    if len(rows) != 1:
        raise RuntimeError(f"missing reference audit: {family}/{sequence}")
    return rows[0]


def manifest_row(family: str, sequence: str) -> dict[str, str]:
    rows = [
        row
        for row in read_csv(DATA_MANIFEST)
        if row["dataset_family"] == family and row["sequence"] == sequence
    ]
    if len(rows) != 1:
        raise RuntimeError(f"missing data manifest: {family}/{sequence}")
    return rows[0]


def decimal_seconds_to_ns(value: str) -> int:
    scaled = Decimal(value.strip()) * Decimal(1_000_000_000)
    integral = scaled.to_integral_value()
    if scaled != integral:
        raise RuntimeError(f"timestamp is not exact to ns: {value}")
    return int(integral)


def tum_stamps(path: Path) -> list[int]:
    result = []
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("#"):
            result.append(decimal_seconds_to_ns(stripped.split()[0]))
    if len(result) < 2 or any(b <= a for a, b in zip(result, result[1:])):
        raise RuntimeError(f"invalid TUM reference times: {path}")
    return result


def bag_stamps(path: Path, topic: str) -> list[int]:
    import rosbag

    values = []
    with rosbag.Bag(str(path)) as bag:
        for _, message, bag_stamp in bag.read_messages(topics=[topic]):
            stamp = getattr(getattr(message, "header", None), "stamp", bag_stamp)
            values.append(int(stamp.secs) * 1_000_000_000 + int(stamp.nsecs))
    if len(values) < 2 or any(b <= a for a, b in zip(values, values[1:])):
        raise RuntimeError(f"invalid bag reference times: {path}:{topic}")
    return values


def reference_contract(window_rows: list[dict[str, str]]) -> dict:
    row = window_rows[0]
    family = row["dataset_family"]
    sequence = row["sequence"]
    audit = audit_row(family, sequence)
    contract = {
        "nominal_reference_rate_hz": audit["nominal_reference_rate_hz"],
        "nominal_estimate_rate_hz": audit["nominal_estimate_rate_hz"],
        "max_reference_gap_s": audit["max_reference_gap_s"],
        "max_estimate_gap_s": audit["max_estimate_interp_gap_s"],
        "reference_time_offset_s": audit["timestamp_offset_s"],
    }
    if family == "ntnu":
        manifest = manifest_row(family, sequence)
        path = ROOT / manifest["reference_path"]
        stamps = tum_stamps(path)
        origin = stamps[0]
        lower = origin + decimal_seconds_to_ns(row["window_start_s"])
        upper = origin + decimal_seconds_to_ns(row["window_end_s"])
        selected = [value for value in stamps if lower <= value <= upper]
        if len(selected) < 2:
            raise RuntimeError(f"insufficient NTNU reference samples: {row['window_id']}")
        contract.update(
            {
                "kind": "tum",
                "path": str(path),
                "window_start_ns": selected[0],
                "window_end_ns": selected[-1],
                "samples": len(selected),
            }
        )
    else:
        b1_rows = [r for r in window_rows if r["arm"] == "B1_klt_nativeq_v3"]
        if len(b1_rows) != 3 or len({r["feature_bag"] for r in b1_rows}) != 1:
            raise RuntimeError(f"invalid B1 reference carriers: {row['window_id']}")
        path = ROOT / b1_rows[0]["feature_bag"]
        topic = REFERENCE_TOPICS[family]
        stamps = bag_stamps(path, topic)
        contract.update(
            {
                "kind": "bag",
                "path": str(path),
                "topic": topic,
                "window_start_ns": stamps[0],
                "window_end_ns": stamps[-1],
                "samples": len(stamps),
            }
        )
    return contract


def evaluation_dir(window_id: str, replay_index: int, contrast: str) -> Path:
    slug = window_id.replace(":", "_").replace("/", "_")
    return RUNTIME / "g0" / slug / f"repeat_{replay_index}" / contrast


def valid_evaluation_receipt(path: Path) -> bool:
    if not path.is_file():
        return False
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    if payload.get("status") == "ARM_HARD_FAILURE":
        return True
    summary_path = Path(str(payload.get("summary_path", "")))
    return (
        payload.get("status") == "EVALUATED"
        and summary_path.is_file()
        and sha256(summary_path) == payload.get("summary_sha256")
    )


def evaluate_contrast(
    window_rows: list[dict[str, str]], replay_index: int, contrast: str, reference: dict
) -> str:
    output_dir = evaluation_dir(window_rows[0]["window_id"], replay_index, contrast)
    receipt_path = output_dir / "evaluation_receipt.json"
    if valid_evaluation_receipt(receipt_path):
        return "SKIPPED"
    if output_dir.exists():
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True)

    proposed_arm, comparator_arm = CONTRASTS[contrast]
    indexed = {
        row["arm"]: row
        for row in window_rows
        if int(row["replay_index"]) == replay_index
    }
    proposed_row = indexed[proposed_arm]
    comparator_row = indexed[comparator_arm]
    proposed_receipt = backend_receipt(proposed_row)
    comparator_receipt = backend_receipt(comparator_row)
    failed = {
        "P": proposed_receipt.get("status"),
        "comparator": comparator_receipt.get("status"),
    }
    if any(status != "COMPLETED" for status in failed.values()):
        payload = {
            "schema_version": "p07-functional-g0-evaluation-receipt-v1",
            "status": "ARM_HARD_FAILURE",
            "window_id": window_rows[0]["window_id"],
            "replay_index": replay_index,
            "contrast": contrast,
            "proposed_arm": proposed_arm,
            "comparator_arm": comparator_arm,
            "backend_status": failed,
            "evidence_boundary": "algorithm hard failure retained in denominator",
        }
        atomic_json(receipt_path, payload)
        print(
            f"[arm-failure] {window_rows[0]['window_id']} r{replay_index} {contrast} {failed}",
            flush=True,
        )
        return "ARM_HARD_FAILURE"

    proposed_vio = Path(proposed_receipt["output"]["vio_path"])
    comparator_vio = Path(comparator_receipt["output"]["vio_path"])
    proposed_config = run_config(proposed_row, proposed_receipt)
    comparator_config = run_config(comparator_row, comparator_receipt)
    command = [sys.executable, str(EVALUATOR)]
    if reference["kind"] == "tum":
        command += ["--reference-tum", reference["path"]]
    else:
        command += [
            "--reference-bag", reference["path"],
            "--reference-topic", reference["topic"],
        ]
    command += [
        "--arm", f"P={proposed_vio}",
        "--arm-config", f"P={proposed_config}",
        "--arm-time-offset-s", "P=0",
        "--arm", f"comparator={comparator_vio}",
        "--arm-config", f"comparator={comparator_config}",
        "--arm-time-offset-s", "comparator=0",
        "--reference-time-offset-s", reference["reference_time_offset_s"],
        "--nominal-reference-rate-hz", reference["nominal_reference_rate_hz"],
        "--nominal-estimate-rate-hz", reference["nominal_estimate_rate_hz"],
        "--max-reference-gap-s", reference["max_reference_gap_s"],
        "--max-estimate-gap-s", reference["max_estimate_gap_s"],
        "--window-start-s", str(Decimal(reference["window_start_ns"]) / Decimal(1_000_000_000)),
        "--window-end-s", str(Decimal(reference["window_end_ns"]) / Decimal(1_000_000_000)),
        "--rpe-delta-s", "1",
        "--min-ape-poses", "30",
        "--min-ape-span-s", "10",
        "--min-common-coverage", "0.70",
        "--min-rpe-pairs", "10",
        "--contrast-name", contrast,
        "--output-dir", str(output_dir),
    ]
    log_path = output_dir / "evaluator.log"
    with log_path.open("wb") as log:
        result = subprocess.run(
            command,
            cwd=ROOT,
            env={**os.environ, "PYTHONPATH": str(ROOT)},
            stdout=log,
            stderr=subprocess.STDOUT,
            check=False,
        )
    summary_path = output_dir / "common_support_summary.json"
    status = "EVALUATED" if result.returncode == 0 and summary_path.is_file() else "EVALUATOR_FAILURE"
    payload = {
        "schema_version": "p07-functional-g0-evaluation-receipt-v1",
        "status": status,
        "window_id": window_rows[0]["window_id"],
        "replay_index": replay_index,
        "contrast": contrast,
        "proposed_arm": proposed_arm,
        "comparator_arm": comparator_arm,
        "return_code": result.returncode,
        "command": command,
        "reference": reference,
        "summary_path": str(summary_path) if summary_path.is_file() else None,
        "summary_sha256": sha256(summary_path) if summary_path.is_file() else None,
        "evaluator_sha256": sha256(EVALUATOR),
        "backend_receipts": {
            "P": proposed_receipt["receipt"],
            "comparator": comparator_receipt["receipt"],
        },
    }
    atomic_json(receipt_path, payload)
    print(
        f"[{status.lower()}] {window_rows[0]['window_id']} r{replay_index} {contrast}",
        flush=True,
    )
    return status


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--probe", action="store_true")
    parser.add_argument(
        "--window-id",
        action="append",
        default=[],
        help="evaluate all three repeats for only the named frozen window",
    )
    parser.add_argument("--continue-on-failure", action="store_true")
    args = parser.parse_args()

    rows = read_csv(QUEUE)
    by_window: dict[str, list[dict[str, str]]] = {}
    for row in rows:
        by_window.setdefault(row["window_id"], []).append(row)
    if args.window_id:
        missing = sorted(set(args.window_id) - set(by_window))
        if missing:
            raise RuntimeError(f"unknown window ids: {missing}")
        selected = [(window_id, by_window[window_id]) for window_id in args.window_id]
    else:
        selected = list(by_window.items())[:1] if args.probe else list(by_window.items())
    failures = 0
    for window_id, window_rows in selected:
        reference = reference_contract(window_rows)
        repeats = (1,) if args.probe else (1, 2, 3)
        for replay_index in repeats:
            for contrast in CONTRASTS:
                status = evaluate_contrast(
                    window_rows, replay_index, contrast, reference
                )
                if status == "EVALUATOR_FAILURE":
                    failures += 1
                    if not args.continue_on_failure:
                        return 1
        print(f"[window] {window_id} evaluation pass", flush=True)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
