#!/usr/bin/env python3
"""Collect, evaluate, and report the preregistered same-backend frontend comparison."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from statistics import median
from typing import Iterable

import rosbag


ROOT = Path("/home/ma/AQUA-FE_WS")
OUT = ROOT / "papers/frontend_same_backend_comparison"
EVAL_SCRIPT = ROOT / "scripts/evaluate_vins_common_support.py"
EVAL_SHA256 = "ab6f2b5c1a10a41463657edee2724c022fc0248dc885096acb336e602384c110"
ARMS = {
    "klt": ("KLT", "klt"),
    "splg": ("SP+LG", "hybrid_superpoint_lightglue"),
    "xfeat_seed": ("XFeat-seed", "hybrid_xfeat"),
}


@dataclass(frozen=True)
class Window:
    window_id: str
    family: str
    sequence: str
    start: float
    end_or_duration: float


WINDOWS = (
    Window("a02_4500_6300", "aqualoc_archaeo", "2", 4500, 6300),
    Window("a09_4000_4400", "aqualoc_archaeo", "9", 4000, 4400),
    Window("a09_6000_6800", "aqualoc_archaeo", "9", 6000, 6800),
    Window("a10_2400_2800", "aqualoc_archaeo", "10", 2400, 2800),
    Window("a10_4800_5200", "aqualoc_archaeo", "10", 4800, 5200),
    Window("h07_1660_1720", "aqualoc_real", "7", 1660, 1720),
    Window("mclab1_s60_d15", "ntnu", "mclab_1", 60, 15),
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def run_dir(window: Window, arm: str, repeat: int) -> Path:
    method = ARMS[arm][1]
    tag = f"fsbcv1_{window.window_id}_{arm}_r{repeat}"
    roots = {
        "aqualoc_archaeo": ROOT / "logs/aqualoc_archaeo_vins",
        "aqualoc_real": ROOT / "logs/aqualoc_real_vins",
        "ntnu": ROOT / "logs/ntnu_vins",
    }
    return roots[window.family] / f"external_{method}_every2_{tag}"


def config_path(window: Window, arm: str, repeat: int) -> Path:
    names = {
        "aqualoc_archaeo": "vins_aqualoc_archaeo_external.yaml",
        "aqualoc_real": "vins_aqualoc_external.yaml",
        "ntnu": "vins_ntnu_external.yaml",
    }
    return run_dir(window, arm, repeat) / names[window.family]


def parse_key_values(path: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    if not path.is_file():
        return result
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        if re.fullmatch(r"[A-Za-z0-9_]+", key.strip()):
            result[key.strip()] = value.strip()
    return result


def float_value(values: dict[str, str], key: str) -> float:
    try:
        value = float(values[key])
    except (KeyError, ValueError):
        return math.nan
    return value if math.isfinite(value) else math.nan


def count_pose_rows(path: Path) -> int:
    if not path.is_file():
        return 0
    count = 0
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        fields = [field.strip() for field in line.split(",")]
        if not fields:
            continue
        try:
            float(fields[0])
        except (ValueError, IndexError):
            continue
        count += 1
    return count


def failure_reason(run: Path, exit_code: int, initialized: bool, coverage: float) -> str:
    console = (run / "fsbc_console.log").read_text(encoding="utf-8", errors="ignore") if (run / "fsbc_console.log").is_file() else ""
    log = (run / "vins.log").read_text(encoding="utf-8", errors="ignore") if (run / "vins.log").is_file() else ""
    body = (console + "\n" + log).lower()
    if exit_code != 0:
        if any(token in body for token in ("missing", "hash mismatch", "traceback", "unknown", "no space left", "cuda out of memory")):
            return "CONFIG_OR_INFRASTRUCTURE"
        return "RUNNER_NONZERO"
    if not initialized:
        if "not enough imu excitation" in body:
            return "INSUFFICIENT_EXCITATION"
        return "COLD_START_NO_INIT"
    if not math.isfinite(coverage) or coverage < 0.70:
        return "COVERAGE_FAIL"
    return "NONE"


def range_text(values: Iterable[float], digits: int = 6) -> str:
    finite = [float(value) for value in values if math.isfinite(float(value))]
    if not finite:
        return "NA"
    return f"{min(finite):.{digits}f}–{max(finite):.{digits}f}"


def median_value(values: Iterable[float]) -> float:
    finite = [float(value) for value in values if math.isfinite(float(value))]
    return float(median(finite)) if finite else math.nan


def write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields: list[str] = []
    for row in rows:
        for key in row:
            if key not in fields:
                fields.append(key)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def collect_runability() -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    raw: list[dict[str, object]] = []
    for window in WINDOWS:
        for arm in ARMS:
            r1_bag = run_dir(window, arm, 1) / "features.bag"
            bag_hash = sha256(r1_bag) if r1_bag.is_file() else ""
            for repeat in range(1, 4):
                run = run_dir(window, arm, repeat)
                receipt = run / "fsbc_cell_complete.json"
                receipt_data = json.loads(receipt.read_text()) if receipt.is_file() else {}
                exit_code = int(receipt_data.get("exit_code", -999))
                ape = parse_key_values(run / "ape.txt")
                coverage = float_value(ape, "output_coverage_ratio")
                init_ape = float_value(ape, "init_success")
                log_text = (run / "vins.log").read_text(encoding="utf-8", errors="ignore") if (run / "vins.log").is_file() else ""
                poses = count_pose_rows(run / "vins_output/vio.csv")
                initialized = bool(init_ape == 1.0 or "Initialization finish!" in log_text) and poses > 0
                passed = bool(exit_code == 0 and initialized and math.isfinite(coverage) and coverage >= 0.70)
                reason = failure_reason(run, exit_code, initialized, coverage)
                raw.append({
                    "window": window.window_id,
                    "arm": arm,
                    "arm_display": ARMS[arm][0],
                    "repeat": repeat,
                    "status": "PASS" if passed else "FAIL",
                    "exit_code": exit_code,
                    "init": int(initialized),
                    "poses": poses,
                    "coverage": coverage,
                    "first_output_delay_s": float_value(ape, "first_output_delay_s"),
                    "expected_duration_s": float_value(ape, "expected_duration_s"),
                    "failure_reason": reason,
                    "run_dir": str(run.resolve()),
                    "vio_csv": str((run / "vins_output/vio.csv").resolve()),
                    "vins_log": str((run / "vins.log").resolve()),
                    "frontend_metrics": str((run / "frontend_metrics.csv").resolve()),
                    "feature_bag": str(r1_bag.resolve()),
                    "feature_bag_sha256": bag_hash,
                })

    grouped: list[dict[str, object]] = []
    for window in WINDOWS:
        for arm in ARMS:
            rows = [row for row in raw if row["window"] == window.window_id and row["arm"] == arm]
            passes = sum(row["status"] == "PASS" for row in rows)
            poses = [float(row["poses"]) for row in rows]
            coverages = [float(row["coverage"]) for row in rows]
            grouped.append({
                "window": window.window_id,
                "arm": arm,
                "arm_display": ARMS[arm][0],
                "status": "PASS" if passes == 3 else "FAIL",
                "pass_repeats": passes,
                "required_repeats": 3,
                "poses_median": median_value(poses),
                "poses_range": range_text(poses, 0),
                "coverage_median": median_value(coverages),
                "coverage_range": range_text(coverages, 3),
                "failure_reasons": ";".join(sorted({str(row["failure_reason"]) for row in rows if row["failure_reason"] != "NONE"})) or "NONE",
                "feature_bag": rows[0]["feature_bag"],
                "feature_bag_sha256": rows[0]["feature_bag_sha256"],
                "repeat_run_dirs": ";".join(str(row["run_dir"]) for row in rows),
            })
    write_csv(OUT / "runability_repeats.csv", raw)
    write_csv(OUT / "runability.csv", grouped)
    return raw, grouped


def audit_effective_frontend_inputs(grouped: list[dict[str, object]]) -> list[dict[str, object]]:
    """Record when nominal frontend arms collapse to the same exported bag.

    The VINS backend consumes the exported bag, so byte-identical bags cannot
    support a causal frontend attribution even when their nominal methods differ.
    """

    rows: list[dict[str, object]] = []
    for window in WINDOWS:
        by_arm = {
            str(row["arm"]): row
            for row in grouped
            if row["window"] == window.window_id
        }
        hashes = {arm: str(by_arm[arm]["feature_bag_sha256"]) for arm in ARMS}
        nonempty = [value for value in hashes.values() if value]
        distinct = len(set(nonempty)) if len(nonempty) == len(ARMS) else 0
        if distinct == 1:
            relation = "KLT=SP+LG=XFeat-seed"
            note = "NO_FRONTEND_ATTRIBUTION_IDENTICAL_BACKEND_INPUT"
        elif hashes["klt"] == hashes["splg"] and hashes["klt"]:
            relation = "KLT=SP+LG;XFeat-seed_distinct"
            note = "KLT_VS_SPLG_NOT_ATTRIBUTABLE"
        elif distinct == len(ARMS):
            relation = "all_distinct"
            note = "EFFECTIVE_INPUTS_DISTINCT"
        else:
            relation = "partial_or_missing"
            note = "AUDIT_INCOMPLETE"
        rows.append({
            "window": window.window_id,
            "klt_feature_bag_sha256": hashes["klt"],
            "splg_feature_bag_sha256": hashes["splg"],
            "xfeat_seed_feature_bag_sha256": hashes["xfeat_seed"],
            "distinct_feature_bag_count": distinct,
            "equality_relation": relation,
            "attribution_status": note,
        })
    write_csv(OUT / "effective_frontend_input_audit.csv", rows)
    return rows


def normalized_config(path: Path) -> bytes:
    lines = []
    for line in path.read_text(encoding="utf-8", errors="strict").splitlines():
        if re.match(r"^\s*output_path\s*:", line):
            lines.append("output_path: <NORMALIZED>")
        else:
            lines.append(line)
    return ("\n".join(lines) + "\n").encode()


def audit_backend_configs() -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for window in WINDOWS:
        hashes = []
        entries = []
        for arm in ARMS:
            for repeat in range(1, 4):
                path = config_path(window, arm, repeat)
                digest = hashlib.sha256(normalized_config(path)).hexdigest() if path.is_file() else ""
                hashes.append(digest)
                entries.append((arm, repeat, path, digest))
        nonempty = [value for value in hashes if value]
        passed = len(nonempty) == 9 and len(set(nonempty)) == 1
        for arm, repeat, path, digest in entries:
            rows.append({
                "window": window.window_id,
                "arm": arm,
                "repeat": repeat,
                "config_path": str(path.resolve()),
                "normalized_config_sha256": digest,
                "window_same_backend_config": "PASS" if passed else "FAIL",
            })
    write_csv(OUT / "backend_config_audit.csv", rows)
    return rows


def evaluator_args(window: Window, eligible_rows: list[dict[str, object]]) -> list[str]:
    args = [sys.executable, str(EVAL_SCRIPT)]
    if window.family in {"aqualoc_archaeo", "aqualoc_real"}:
        reference_bag = run_dir(window, "klt", 1) / "features.bag"
        args += ["--reference-bag", str(reference_bag), "--reference-topic", "/aqualoc/colmap_gt"]
        if window.family == "aqualoc_archaeo":
            args += ["--nominal-reference-rate-hz", "1", "--evaluation-rate-hz", "1", "--max-reference-gap-s", "2.5", "--nominal-estimate-rate-hz", "10", "--max-estimate-gap-s", "0.25"]
        else:
            args += ["--nominal-reference-rate-hz", "4", "--evaluation-rate-hz", "2", "--max-reference-gap-s", "0.625", "--nominal-estimate-rate-hz", "10", "--max-estimate-gap-s", "0.25"]
    else:
        reference = ROOT / "datasets/full_downloads/ntnu_hf/subset-mclab/mclab_1/mclab_1_baseline.tum"
        first = next(float(line.split()[0]) for line in reference.read_text().splitlines() if line.strip() and not line.startswith("#"))
        start = first + window.start
        end = start + window.end_or_duration
        args += ["--reference-tum", str(reference), "--nominal-reference-rate-hz", "50", "--evaluation-rate-hz", "10", "--max-reference-gap-s", "0.05", "--nominal-estimate-rate-hz", "6.6666667", "--max-estimate-gap-s", "0.375", "--window-start-s", format(start, ".17g"), "--window-end-s", format(end, ".17g")]
    for row in eligible_rows:
        name = f"{row['arm']}_r{row['repeat']}"
        args += ["--arm", f"{name}={row['vio_csv']}"]
        args += ["--arm-config", f"{name}={config_path(window, str(row['arm']), int(row['repeat']))}"]
    args += [
        "--rpe-delta-s", "1.0", "--min-ape-poses", "30", "--min-ape-span-s", "10",
        "--min-common-coverage", "0.70", "--min-rpe-pairs", "10",
        "--contrast-name", f"fsbcv1_{window.window_id}_all9",
        "--output-dir", str(OUT / "common_support" / window.window_id), "--run-evo",
    ]
    return args


def evaluate_common_support(raw: list[dict[str, object]], grouped: list[dict[str, object]], config_audit: list[dict[str, object]]) -> None:
    if sha256(EVAL_SCRIPT) != EVAL_SHA256:
        raise RuntimeError("common-support evaluator hash mismatch")
    eval_status: list[dict[str, object]] = []
    for window in WINDOWS:
        arm_pass = all(row["status"] == "PASS" for row in grouped if row["window"] == window.window_id)
        config_pass = all(row["window_same_backend_config"] == "PASS" for row in config_audit if row["window"] == window.window_id)
        if not (arm_pass and config_pass):
            eval_status.append({"window": window.window_id, "status": "EXCLUDED", "reason": "RUNABILITY" if not arm_pass else "BACKEND_CONFIG_MISMATCH", "return_code": ""})
            continue
        rows = [row for row in raw if row["window"] == window.window_id]
        command = evaluator_args(window, rows)
        out_dir = OUT / "common_support" / window.window_id
        out_dir.mkdir(parents=True, exist_ok=True)
        process = subprocess.run(command, cwd=ROOT, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=False)
        (out_dir / "evaluator.log").write_text(process.stdout, encoding="utf-8")
        summary = out_dir / "common_support_summary.json"
        status = "PASS" if process.returncode == 0 and summary.is_file() else "FAIL"
        reason = "NONE" if status == "PASS" else "EVALUATOR_FAILURE"
        if summary.is_file():
            data = json.loads(summary.read_text())
            if not (data["support"]["ape_valid"] and data["support"]["rpe_valid"]):
                status, reason = "EXCLUDED", "COMMON_SUPPORT_GATE"
        eval_status.append({"window": window.window_id, "status": status, "reason": reason, "return_code": process.returncode})
    write_csv(OUT / "common_support_status.csv", eval_status)


def collect_accuracy() -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    raw: list[dict[str, object]] = []
    support_rows: list[dict[str, str]] = []
    status_path = OUT / "common_support_status.csv"
    if status_path.is_file():
        with status_path.open(newline="", encoding="utf-8") as handle:
            support_rows = list(csv.DictReader(handle))
    for status in support_rows:
        if status["status"] != "PASS":
            continue
        window = status["window"]
        metrics_path = OUT / "common_support" / window / "common_support_metrics.csv"
        evo_path = OUT / "common_support" / window / "evo_crosscheck.json"
        evo = json.loads(evo_path.read_text()).get("arms", {}) if evo_path.is_file() else {}
        with metrics_path.open(newline="", encoding="utf-8") as handle:
            for row in csv.DictReader(handle):
                match = re.fullmatch(r"(.+)_r([123])", row["arm"])
                if not match:
                    continue
                arm, repeat_text = match.groups()
                evo_row = evo.get(row["arm"], {})
                raw.append({
                    "window": window,
                    "arm": arm,
                    "arm_display": ARMS[arm][0],
                    "repeat": int(repeat_text),
                    "ape_rmse_m": float(row["ape_rmse_m"]),
                    "ape_median_m": float(row["ape_median_m"]),
                    "rpe_rmse_m": float(row["rpe_rmse_m"]),
                    "rpe_median_m": float(row["rpe_median_m"]),
                    "common_poses": int(row["matched_count"]),
                    "rpe_pairs": int(row["rpe_pairs"]),
                    "evo_ape_rmse_m": evo_row.get("evo_ape_rmse_m", math.nan),
                    "evo_rpe_rmse_m": evo_row.get("evo_segmented_rpe_rmse_m", math.nan),
                    "evo_ape_abs_diff_m": evo_row.get("ape_abs_diff_m", math.nan),
                    "evo_rpe_abs_diff_m": evo_row.get("rpe_abs_diff_m", math.nan),
                })
    grouped: list[dict[str, object]] = []
    for window in [item.window_id for item in WINDOWS]:
        for arm in ARMS:
            rows = [row for row in raw if row["window"] == window and row["arm"] == arm]
            if not rows:
                continue
            ape = [float(row["ape_rmse_m"]) for row in rows]
            rpe = [float(row["rpe_rmse_m"]) for row in rows]
            grouped.append({
                "window": window,
                "arm": arm,
                "arm_display": ARMS[arm][0],
                "repeats": len(rows),
                "ape_rmse_median_m": median_value(ape),
                "ape_rmse_range_m": range_text(ape),
                "rpe_rmse_median_m": median_value(rpe),
                "rpe_rmse_range_m": range_text(rpe),
                "common_poses": rows[0]["common_poses"],
                "rpe_pairs": rows[0]["rpe_pairs"],
                "max_evo_ape_abs_diff_m": max(float(row["evo_ape_abs_diff_m"]) for row in rows),
                "max_evo_rpe_abs_diff_m": max(float(row["evo_rpe_abs_diff_m"]) for row in rows),
            })
    write_csv(OUT / "accuracy_repeats.csv", raw)
    write_csv(OUT / "accuracy.csv", grouped)
    return raw, grouped


def artifact_manifest() -> None:
    paths = [OUT / name for name in (
        "windows.csv", "arms.csv", "contract.json", "preregistration.md", "runtime_weight_lock.json", "execution_conditions.md", "runability_repeats.csv", "runability.csv",
        "backend_config_audit.csv", "effective_frontend_input_audit.csv", "backend_feature_budget_audit.csv", "common_support_status.csv", "accuracy_repeats.csv", "accuracy.csv",
        "trajectory_scale_audit.csv", "report.md", "analysis-report.md", "stats-appendix.md", "figure-catalog.md",
    )]
    paths.extend(
        path for path in sorted((OUT / "common_support").rglob("*"))
        if path.is_file()
    )
    paths.extend(
        path for path in sorted((OUT / "analysis-output").rglob("*"))
        if path.is_file()
    )
    paths.extend([
        ROOT / "scripts/run_frontend_same_backend_comparison_v1.sh",
        ROOT / "scripts/analyze_frontend_same_backend_comparison_v1.py",
        ROOT / "scripts/report_frontend_same_backend_comparison_v1.py",
        ROOT / "scripts/evaluate_vins_common_support.py",
        ROOT / "scripts/trajectory_eval_core.py",
    ])
    for window in WINDOWS:
        for arm in ARMS:
            paths.append(run_dir(window, arm, 1) / "features.bag")
            for repeat in range(1, 4):
                run = run_dir(window, arm, repeat)
                paths.extend([run / "vins_output/vio.csv", run / "vins.log", run / "frontend_metrics.csv", run / "fsbc_console.log", config_path(window, arm, repeat)])
    rows = []
    for path in paths:
        if path.is_file():
            rows.append(f"{sha256(path)}  {path.resolve()}\n")
    (OUT / "artifacts.sha256").write_text("".join(rows), encoding="utf-8")


def audit_backend_feature_budget(grouped: list[dict[str, object]]) -> list[dict[str, object]]:
    """Check the actual PointCloud size received by VINS against budget 350."""

    output: list[dict[str, object]] = []
    for row in grouped:
        counts: list[int] = []
        with rosbag.Bag(str(row["feature_bag"])) as bag:
            for _, message, _ in bag.read_messages(topics=["/feature_tracker/feature"]):
                counts.append(len(message.points))
        if not counts:
            raise RuntimeError(f"no backend feature messages: {row['feature_bag']}")
        over = [count for count in counts if count > 350]
        output.append({
            "window": row["window"],
            "arm": row["arm"],
            "configured_feature_budget": 350,
            "feature_messages": len(counts),
            "points_min": min(counts),
            "points_median": median(counts),
            "points_max": max(counts),
            "messages_over_budget": len(over),
            "max_budget_excess": max(over) - 350 if over else 0,
            "budget_contract_status": "PASS" if not over else "FAIL",
        })
    write_csv(OUT / "backend_feature_budget_audit.csv", output)
    return output


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("stage", choices=("collect", "evaluate", "all"), default="all", nargs="?")
    args = parser.parse_args()
    raw, grouped = collect_runability()
    audit_effective_frontend_inputs(grouped)
    audit_backend_feature_budget(grouped)
    audit = audit_backend_configs()
    if args.stage in {"evaluate", "all"}:
        evaluate_common_support(raw, grouped, audit)
    collect_accuracy()
    artifact_manifest()
    print(f"runability={OUT / 'runability.csv'}")
    print(f"accuracy={OUT / 'accuracy.csv'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
