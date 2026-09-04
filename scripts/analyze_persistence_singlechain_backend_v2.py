#!/usr/bin/env python3
"""Evaluate single-chain v2 against frozen KLT on common support."""

from __future__ import annotations

import csv
import hashlib
import json
import math
from pathlib import Path
import re
from statistics import median
import subprocess
import sys

import rosbag


ROOT = Path("/home/ma/AQUA-FE_WS")
PAPER = ROOT / "papers/frontend_persistence_singlechain_v2"
RUNTIME = ROOT / "artifacts/frontend_persistence_singlechain_v2"
EVALUATOR = ROOT / "scripts/evaluate_vins_common_support_dual_scale.py"
ARMS = ("klt", "singlechain")

CASES = {
    "a06_s000_d045": {
        "klt_bag": ROOT / "artifacts/frontend_same_backend_comparison_supplement/shadow_root/logs/aqualoc_archaeo_vins/external_klt_every2_fsbcsupp_a06_s000_d045_klt_frontend/features.bag",
        "klt_run": str(ROOT / "artifacts/frontend_same_backend_comparison_supplement/replays/a06_s000_d045/klt/repeat{repeat}"),
        "klt_config": str(ROOT / "artifacts/frontend_same_backend_comparison_supplement/backend_canonical/a06_s000_d045/vins_same_backend.yaml"),
    },
    "a09_6000_6800": {
        "klt_bag": Path("/mnt/data/AQUA-FE_WS/logs/aqualoc_archaeo_vins/external_klt_every2_fsbcv1_a09_6000_6800_klt_r1/features.bag"),
        "klt_run": "/mnt/data/AQUA-FE_WS/logs/aqualoc_archaeo_vins/external_klt_every2_fsbcv1_a09_6000_6800_klt_r{repeat}",
        "klt_config": "/mnt/data/AQUA-FE_WS/logs/aqualoc_archaeo_vins/external_klt_every2_fsbcv1_a09_6000_6800_klt_r{repeat}/vins_aqualoc_archaeo_external.yaml",
    },
    "a06_s045_d045": {
        "klt_bag": ROOT / "artifacts/frontend_same_backend_comparison_supplement/shadow_root/logs/aqualoc_archaeo_vins/external_klt_every2_fsbcsupp_a06_s045_d045_klt_frontend/features.bag",
        "klt_run": str(ROOT / "artifacts/frontend_same_backend_comparison_supplement/replays/a06_s045_d045/klt/repeat{repeat}"),
        "klt_config": str(ROOT / "artifacts/frontend_same_backend_comparison_supplement/backend_canonical/a06_s045_d045/vins_same_backend.yaml"),
    },
    "h07_s000_d050": {
        "klt_bag": ROOT / "artifacts/frontend_same_backend_comparison_supplement/shadow_root/logs/aqualoc_real_vins/external_klt_every2_fsbcsupp_h07_s000_d050_klt_frontend/features.bag",
        "klt_run": str(ROOT / "artifacts/frontend_same_backend_comparison_supplement/replays/h07_s000_d050/klt/repeat{repeat}"),
        "klt_config": str(ROOT / "artifacts/frontend_same_backend_comparison_supplement/backend_canonical/h07_s000_d050/vins_same_backend.yaml"),
    },
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as stream:
        return list(csv.DictReader(stream))


def write(path: Path, data: list[dict[str, object]]) -> None:
    fields: list[str] = []
    for row in data:
        for key in row:
            if key not in fields:
                fields.append(key)
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader(); writer.writerows(data)


def normalized_config(path: Path) -> str:
    text = re.sub(r'^output_path:\s*".*"$', 'output_path: "<NORMALIZED>"', path.read_text(encoding="utf-8"), flags=re.MULTILINE)
    return hashlib.sha256(text.encode()).hexdigest()


def klt_run(window: str, repeat: int) -> Path:
    return Path(str(CASES[window]["klt_run"]).format(repeat=repeat))


def arm_run(window: str, arm: str, repeat: int, identical: bool) -> Path:
    if arm == "klt" or identical:
        return klt_run(window, repeat)
    return RUNTIME / "replays" / window / "singlechain" / f"repeat{repeat}"


def pose_stats(path: Path) -> tuple[int, float]:
    stamps = []
    if path.is_file():
        for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
            first = line.split(",", 1)[0].strip()
            if re.fullmatch(r"\d+", first): stamps.append(int(first) * 1e-9)
    return len(stamps), max(0.0, stamps[-1] - stamps[0]) if stamps else 0.0


def proxy_span(path: Path) -> float:
    stamps = []
    with rosbag.Bag(str(path)) as bag:
        for _, message, stamp in bag.read_messages(topics=["/aqualoc/colmap_gt"]):
            stamps.append(message.header.stamp.to_sec() if hasattr(message, "header") else stamp.to_sec())
    return stamps[-1] - stamps[0]


def med(values: list[float]) -> float: return float(median(values))
def extent(values: list[float]) -> str: return f"{min(values):.9f}–{max(values):.9f}"


def main() -> int:
    frontend = {row["window"]: row for row in rows(PAPER / "frontend_validation.csv")}
    run_repeats: list[dict[str, object]] = []
    runability: list[dict[str, object]] = []
    audit: list[dict[str, object]] = []
    for window, case in CASES.items():
        identical = frontend[window]["byte_identical_klt"].lower() == "true"
        expected = proxy_span(Path(case["klt_bag"]))
        for arm in ARMS:
            gates = []
            for repeat in range(1, 4):
                run = arm_run(window, arm, repeat, identical)
                vio, log = run / "vins_output/vio.csv", run / "vins.log"
                count, span = pose_stats(vio)
                init = "Initialization finish!" in (log.read_text(encoding="utf-8", errors="ignore") if log.is_file() else "")
                coverage = min(1.0, span / expected)
                passed = init and count >= 30 and span >= 10 and coverage >= 0.70
                gates.append(passed)
                run_repeats.append({
                    "window": window, "arm": arm, "repeat": repeat, "status": "PASS" if passed else "FAIL",
                    "initialized": init, "pose_count": count, "span_s": span, "reference_span_s": expected,
                    "coverage": coverage, "reuse_exact_klt_input": arm == "singlechain" and identical,
                    "vio_csv": str(vio), "vins_log": str(log),
                })
                config = (
                    Path(str(case["klt_config"]).format(repeat=repeat))
                    if arm == "klt" or identical else RUNTIME / "backend_canonical" / window / "vins_same_backend.yaml"
                )
                feature_bag = Path(case["klt_bag"])
                if arm == "singlechain" and not identical:
                    receipt = dict(
                        line.split("=", 1) for line in (run / "replay_receipt.txt").read_text(encoding="utf-8").splitlines() if "=" in line
                    )
                    feature_bag = Path(receipt["feature_bag"])
                audit.append({
                    "window": window, "arm": arm, "repeat": repeat,
                    "status": "FROZEN_RESULT_REUSE" if arm == "klt" or identical else "COMPLETE",
                    "feature_bag": str(feature_bag), "feature_bag_sha256": sha256(feature_bag),
                    "config": str(config), "config_sha256": sha256(config),
                    "normalized_backend_config_sha256": normalized_config(config),
                    "vins_node_sha256": sha256(Path("/home/ma/SLAM/VINS-Fusion-origin/devel/lib/vins/vins_node")),
                    "libvins_sha256": sha256(Path("/home/ma/SLAM/VINS-Fusion-origin/devel/lib/libvins_lib.so")),
                    "vio_csv": str(vio), "vio_csv_sha256": sha256(vio) if vio.is_file() else "MISSING",
                })
            runability.append({"window": window, "arm": arm, "status": "PASS" if all(gates) else "FAIL", "repeats_passed": sum(gates), "repeats_required": 3})
        hashes = {row["normalized_backend_config_sha256"] for row in audit if row["window"] == window}
        if len(hashes) != 1: raise RuntimeError(f"backend config mismatch: {window}")
    write(PAPER / "runability_repeats.csv", run_repeats)
    write(PAPER / "runability.csv", runability)
    write(PAPER / "backend_config_audit.csv", audit)

    support_rows: list[dict[str, object]] = []
    repeat_metrics: list[dict[str, object]] = []
    for window, case in CASES.items():
        if not all(row["status"] == "PASS" for row in runability if row["window"] == window):
            support_rows.append({"window": window, "status": "EXCLUDED_RUNABILITY"}); continue
        identical = frontend[window]["byte_identical_klt"].lower() == "true"
        config = RUNTIME / "backend_canonical" / window / "vins_same_backend.yaml"
        output = PAPER / "common_support" / window
        command = [sys.executable, str(EVALUATOR), "--reference-bag", str(case["klt_bag"]), "--reference-topic", "/aqualoc/colmap_gt", "--evaluation-rate-hz", "1", "--max-reference-gap-s", "2.5", "--max-estimate-gap-s", "0.25", "--output-dir", str(output), "--run-evo"]
        for arm in ARMS:
            for repeat in range(1, 4):
                name = f"{arm}_r{repeat}"; vio = arm_run(window, arm, repeat, identical) / "vins_output/vio.csv"
                command += ["--arm", f"{name}={vio}", "--arm-config", f"{name}={config}"]
        result = subprocess.run(command, cwd=ROOT, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=False)
        output.mkdir(parents=True, exist_ok=True); (output / "evaluator.log").write_text(result.stdout, encoding="utf-8")
        summary_file = output / "common_support_summary.json"
        support = json.loads(summary_file.read_text(encoding="utf-8"))["support"] if summary_file.is_file() else {}
        admitted = result.returncode == 0 and support.get("ape_valid") and support.get("rpe_valid")
        support_rows.append({"window": window, "status": "PASS" if admitted else "EXCLUDED_COMMON_SUPPORT", "matched_count": support.get("matched_count", ""), "common_span_s": support.get("common_span_s", ""), "common_coverage": support.get("common_coverage", ""), "rpe_pairs": support.get("rpe_pairs", "")})
        if not admitted: continue
        evo = json.loads((output / "evo_crosscheck.json").read_text(encoding="utf-8"))["arms"]
        for row in rows(output / "common_support_metrics.csv"):
            match = re.fullmatch(r"(klt|singlechain)_r([123])", row["arm"])
            if not match: continue
            arm, repeat = match.groups(); cross = evo[row["arm"]]
            repeat_metrics.append({
                "window": window, "arm": arm, "repeat": int(repeat), "common_poses": int(row["matched_count"]), "rpe_pairs": int(row["rpe_pairs"]),
                "fixed_se3_ape_rmse_m": float(row["fixed_se3_ape_rmse_m"]), "fixed_se3_rpe_rmse_m": float(row["fixed_se3_rpe_rmse_m"]),
                "sim3_scale": float(row["sim3_scale"]), "sim3_ape_rmse_m": float(row["sim3_ape_rmse_m"]), "sim3_rpe_rmse_m": float(row["sim3_rpe_rmse_m"]),
                "max_evo_abs_diff_m": max(float(cross[mode][key]) for mode in ("fixed_se3", "sim3") for key in ("ape_abs_diff_m", "rpe_abs_diff_m")),
            })
    write(PAPER / "common_support_status.csv", support_rows)
    write(PAPER / "accuracy_repeats.csv", repeat_metrics)
    grouped: list[dict[str, object]] = []
    for window in CASES:
        for arm in ARMS:
            cells = [row for row in repeat_metrics if row["window"] == window and row["arm"] == arm]
            if not cells: continue
            grouped.append({
                "window": window, "arm": arm, "repeats": len(cells), "common_poses": cells[0]["common_poses"], "rpe_pairs": cells[0]["rpe_pairs"],
                "fixed_se3_ape_rmse_median_m": med([float(c["fixed_se3_ape_rmse_m"]) for c in cells]), "fixed_se3_ape_rmse_range_m": extent([float(c["fixed_se3_ape_rmse_m"]) for c in cells]),
                "fixed_se3_rpe_rmse_median_m": med([float(c["fixed_se3_rpe_rmse_m"]) for c in cells]), "fixed_se3_rpe_rmse_range_m": extent([float(c["fixed_se3_rpe_rmse_m"]) for c in cells]),
                "sim3_scale_median": med([float(c["sim3_scale"]) for c in cells]), "sim3_scale_range": extent([float(c["sim3_scale"]) for c in cells]),
                "sim3_ape_rmse_median_m": med([float(c["sim3_ape_rmse_m"]) for c in cells]), "sim3_rpe_rmse_median_m": med([float(c["sim3_rpe_rmse_m"]) for c in cells]),
                "max_evo_abs_diff_m": max(float(c["max_evo_abs_diff_m"]) for c in cells),
            })
    write(PAPER / "accuracy.csv", grouped)

    decisions = []
    for window in CASES:
        exact = frontend[window]["byte_identical_klt"].lower() == "true"
        k = next((r for r in grouped if r["window"] == window and r["arm"] == "klt"), None)
        n = next((r for r in grouped if r["window"] == window and r["arm"] == "singlechain"), None)
        if exact: decision, reason = "NO_HARM_INPUT", "feature bag byte-identical to KLT"
        elif not k or not n: decision, reason = "FAIL", "runability/common-support failure"
        elif window == "a06_s000_d045":
            kc = [r for r in repeat_metrics if r["window"] == window and r["arm"] == "klt"]
            nc = [r for r in repeat_metrics if r["window"] == window and r["arm"] == "singlechain"]
            ka, kr = float(k["fixed_se3_ape_rmse_median_m"]), float(k["fixed_se3_rpe_rmse_median_m"])
            diverged = any(float(r["fixed_se3_ape_rmse_m"]) > 10 * ka or float(r["sim3_scale"]) < 0.1 for r in nc)
            inside = float(n["fixed_se3_ape_rmse_median_m"]) <= max(float(r["fixed_se3_ape_rmse_m"]) for r in kc) and float(n["fixed_se3_rpe_rmse_median_m"]) <= max(float(r["fixed_se3_rpe_rmse_m"]) for r in kc)
            decision = "REPAIR_PASS" if not diverged and inside else "FAIL"
            reason = f"scale_diverged_repeat={diverged};medians_within_klt_envelope={inside}"
        else:
            better = float(n["fixed_se3_ape_rmse_median_m"]) < float(k["fixed_se3_ape_rmse_median_m"]) and float(n["fixed_se3_rpe_rmse_median_m"]) < float(k["fixed_se3_rpe_rmse_median_m"])
            decision = "POSITIVE_RETAINED" if better else "FAIL"; reason = "both fixed-scale medians below KLT" if better else "positive not retained"
        decisions.append({"window": window, "decision": decision, "reason": reason})
    write(PAPER / "decisions.csv", decisions)
    return 0


if __name__ == "__main__": raise SystemExit(main())
