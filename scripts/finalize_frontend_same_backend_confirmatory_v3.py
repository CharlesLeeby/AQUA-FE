#!/usr/bin/env python3
"""Collect gates and evaluate confirmatory-v3 on exact common support."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from pathlib import Path
import re
from statistics import median
import subprocess
import sys

import numpy as np
import rosbag

sys.path.insert(0, str(Path(__file__).resolve().parent))
import run_frontend_same_backend_confirmatory_v3 as frontend


ROOT = Path("/home/ma/AQUA-FE_WS")
PAPER = ROOT / "papers/frontend_same_backend_confirmatory_v3"
RUNTIME = Path(
    "/media/ma/Data/AQUA-FE_WS_storage_offload/"
    "frontend_same_backend_confirmatory_v3"
)
REPLAYS = RUNTIME / "replays"
EVALUATOR = ROOT / "scripts/evaluate_vins_common_support_dual_scale.py"
ARMS = ("klt", "splg", "xfeat_v3")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as stream:
        return list(csv.DictReader(stream))


def write_csv(path: Path, rows: list[dict[str, object]], fields: list[str] | None = None) -> None:
    if fields is None:
        fields = []
        for row in rows:
            for key in row:
                if key not in fields:
                    fields.append(key)
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def pose_stats(path: Path) -> tuple[int, float]:
    stamps: list[float] = []
    if path.is_file():
        with path.open(encoding="utf-8", errors="ignore") as stream:
            for line in stream:
                first = line.split(",", 1)[0].strip()
                if re.fullmatch(r"\d+", first):
                    stamps.append(int(first) * 1e-9)
    return (len(stamps), max(0.0, stamps[-1] - stamps[0])) if stamps else (0, 0.0)


def reference_span(feature_bag: Path, topic: str) -> tuple[int, float]:
    stamps: list[float] = []
    with rosbag.Bag(str(feature_bag), "r") as bag:
        for _, message, stamp in bag.read_messages(topics=[topic]):
            header = getattr(message, "header", None)
            stamps.append(
                float(header.stamp.to_sec()) if header is not None else float(stamp.to_sec())
            )
    if len(stamps) < 2:
        raise RuntimeError(f"reference has fewer than two poses: {feature_bag}:{topic}")
    return len(stamps), stamps[-1] - stamps[0]


def classify_failure(log_text: str, receipt_exists: bool, initialized: bool, coverage: float) -> str:
    lower = log_text.lower()
    if not receipt_exists and not log_text:
        return "not_run_or_infrastructure"
    if "not enough imu excitation" in lower:
        return "insufficient_excitation"
    if not initialized:
        return "cold_start_no_initialization"
    if coverage < 0.70:
        return "coverage_failure"
    if not receipt_exists:
        return "early_termination"
    return ""


def collect_runability() -> list[dict[str, object]]:
    subprocess.run(
        [sys.executable, str(ROOT / "scripts/analyze_frontend_same_backend_confirmatory_v3.py")],
        cwd=ROOT,
        check=True,
    )
    frontend_rows = read_csv(PAPER / "frontend_runability.csv")
    windows = {row["run_slug"]: row for row in frontend.load_windows()}
    rows: list[dict[str, object]] = []
    for source in frontend_rows:
        row: dict[str, object] = dict(source)
        run_slug = source["run_slug"]
        arm = source["arm"]
        window = windows[run_slug]
        row["reference_pose_count"] = ""
        row["reference_span_s"] = ""
        for repeat in range(1, 4):
            for suffix in ("init", "pose_count", "span_s", "coverage", "pass"):
                row[f"repeat{repeat}_{suffix}"] = ""
        row["backend_repeats_pass"] = ""
        row["arm_window_pass"] = "NOT_RUN"
        row["backend_failure_class"] = ""
        row["accuracy_exclusion"] = ""

        if source["cell_status"] != "PASS":
            row["backend_failure_class"] = "frontend_not_pass"
            rows.append(row)
            continue
        if source["all_three_bags_byte_identical"] == "true":
            row["accuracy_exclusion"] = "EXCLUDED_ALL_THREE_FEATURE_BAGS_IDENTICAL"
            rows.append(row)
            continue

        topic = (
            "/afrl/colmap_gt"
            if window["family"] == "afrl"
            else "/aqualoc/colmap_gt"
        )
        reference_count, expected_span = reference_span(
            Path(source["feature_bag_path"]), topic
        )
        row["reference_pose_count"] = reference_count
        row["reference_span_s"] = f"{expected_span:.9f}"
        passes: list[bool] = []
        failures: set[str] = set()
        for repeat in range(1, 4):
            run_dir = REPLAYS / run_slug / arm / f"repeat{repeat}"
            vio = run_dir / "vins_output/vio.csv"
            log = run_dir / "vins.log"
            receipt = run_dir / "replay_receipt.txt"
            count, span = pose_stats(vio)
            log_text = log.read_text(encoding="utf-8", errors="ignore") if log.is_file() else ""
            initialized = "Initialization finish!" in log_text and count > 0
            coverage = min(1.0, span / expected_span) if expected_span > 0.0 else 0.0
            passed = bool(receipt.is_file() and initialized and coverage >= 0.70)
            passes.append(passed)
            row[f"repeat{repeat}_init"] = "PASS" if initialized else "FAIL"
            row[f"repeat{repeat}_pose_count"] = count
            row[f"repeat{repeat}_span_s"] = f"{span:.9f}"
            row[f"repeat{repeat}_coverage"] = f"{coverage:.9f}"
            row[f"repeat{repeat}_pass"] = "PASS" if passed else "FAIL"
            failure = classify_failure(log_text, receipt.is_file(), initialized, coverage)
            if failure:
                failures.add(failure)
        row["backend_repeats_pass"] = f"{sum(passes)}/3"
        row["arm_window_pass"] = "PASS" if all(passes) else "FAIL"
        row["backend_failure_class"] = ";".join(sorted(failures))
        rows.append(row)
    write_csv(PAPER / "runability.csv", rows)
    return rows


def eligible_backend_windows(rows: list[dict[str, object]]) -> list[dict[str, str]]:
    by_cell = {(str(row["run_slug"]), str(row["arm"])): row for row in rows}
    result: list[dict[str, str]] = []
    for window in frontend.load_windows():
        cells = [by_cell[(window["run_slug"], arm)] for arm in ARMS]
        if all(cell["arm_window_pass"] == "PASS" for cell in cells):
            result.append(window)
    return result


def evaluate(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    by_cell = {(str(row["run_slug"]), str(row["arm"])): row for row in rows}
    eligible = {window["run_slug"]: window for window in eligible_backend_windows(rows)}
    statuses: list[dict[str, object]] = []
    for window in frontend.load_windows():
        run_slug = window["run_slug"]
        cells = [by_cell[(run_slug, arm)] for arm in ARMS]
        status: dict[str, object] = {
            "window_id": window["window_id"],
            "run_slug": run_slug,
            "status": "",
            "return_code": "",
            "matched_count": "",
            "common_span_s": "",
            "common_coverage": "",
            "rpe_pairs": "",
        }
        if not all(cell["cell_status"] == "PASS" for cell in cells):
            status["status"] = "NOT_ALL_FRONTENDS_PASS"
            statuses.append(status)
            continue
        if all(cell["all_three_bags_byte_identical"] == "true" for cell in cells):
            status["status"] = "EXCLUDED_ALL_THREE_FEATURE_BAGS_IDENTICAL"
            statuses.append(status)
            continue
        if run_slug not in eligible:
            status["status"] = "NOT_ALL_ARMS_BACKEND_PASS"
            statuses.append(status)
            continue

        reference_topic = (
            "/afrl/colmap_gt"
            if window["family"] == "afrl"
            else "/aqualoc/colmap_gt"
        )
        config = RUNTIME / "backend_canonical" / run_slug / "vins_same_backend.yaml"
        output = PAPER / "common_support" / run_slug
        command = [
            sys.executable,
            str(EVALUATOR),
            "--reference-bag",
            str(by_cell[(run_slug, "klt")]["feature_bag_path"]),
            "--reference-topic",
            reference_topic,
            "--evaluation-rate-hz",
            "1",
            "--max-reference-gap-s",
            "2.5",
            "--max-estimate-gap-s",
            "0.25",
            "--output-dir",
            str(output),
            "--run-evo",
        ]
        for arm in ARMS:
            for repeat in range(1, 4):
                name = f"{arm}_r{repeat}"
                vio = REPLAYS / run_slug / arm / f"repeat{repeat}/vins_output/vio.csv"
                command += ["--arm", f"{name}={vio}", "--arm-config", f"{name}={config}"]
        process = subprocess.run(
            command,
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
        )
        output.mkdir(parents=True, exist_ok=True)
        (output / "evaluator.log").write_text(process.stdout, encoding="utf-8")
        summary_path = output / "common_support_summary.json"
        support: dict[str, object] = {}
        if process.returncode == 0 and summary_path.is_file():
            support = json.loads(summary_path.read_text(encoding="utf-8"))["support"]
        admitted = bool(support.get("ape_valid") and support.get("rpe_valid"))
        status.update(
            {
                "status": "PASS" if admitted else "EXCLUDED_COMMON_SUPPORT",
                "return_code": process.returncode,
                "matched_count": support.get("matched_count", ""),
                "common_span_s": support.get("common_span_s", ""),
                "common_coverage": support.get("common_coverage", ""),
                "rpe_pairs": support.get("rpe_pairs", ""),
            }
        )
        statuses.append(status)
    write_csv(PAPER / "common_support_status.csv", statuses)
    return statuses


def finite_median(values: list[float]) -> float:
    finite = [value for value in values if math.isfinite(value)]
    return float(median(finite)) if finite else math.nan


def range_text(values: list[float]) -> str:
    finite = [value for value in values if math.isfinite(value)]
    return f"{min(finite):.9f}–{max(finite):.9f}" if finite else ""


def collect_accuracy(statuses: list[dict[str, object]]) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    repeats: list[dict[str, object]] = []
    admitted = [row for row in statuses if row["status"] == "PASS"]
    for status in admitted:
        run_slug = str(status["run_slug"])
        path = PAPER / "common_support" / run_slug
        metrics = read_csv(path / "common_support_metrics.csv")
        evo = json.loads((path / "evo_crosscheck.json").read_text(encoding="utf-8"))
        for metric in metrics:
            match = re.fullmatch(r"(.+)_r([123])", metric["arm"])
            if not match:
                continue
            arm, repeat = match.groups()
            cross = evo["arms"][metric["arm"]]
            repeats.append(
                {
                    "window_id": status["window_id"],
                    "run_slug": run_slug,
                    "arm": arm,
                    "repeat": int(repeat),
                    "common_poses": int(metric["matched_count"]),
                    "rpe_pairs": int(metric["rpe_pairs"]),
                    "fixed_se3_ape_rmse_m": float(metric["fixed_se3_ape_rmse_m"]),
                    "fixed_se3_rpe_rmse_m": float(metric["fixed_se3_rpe_rmse_m"]),
                    "sim3_scale": float(metric["sim3_scale"]),
                    "sim3_ape_rmse_m": float(metric["sim3_ape_rmse_m"]),
                    "sim3_rpe_rmse_m": float(metric["sim3_rpe_rmse_m"]),
                    "max_evo_abs_diff_m": max(
                        float(cross[mode][key])
                        for mode in ("fixed_se3", "sim3")
                        for key in ("ape_abs_diff_m", "rpe_abs_diff_m")
                    ),
                }
            )
    grouped: list[dict[str, object]] = []
    for status in admitted:
        for arm in ARMS:
            cells = [
                row
                for row in repeats
                if row["run_slug"] == status["run_slug"] and row["arm"] == arm
            ]
            if len(cells) != 3:
                raise RuntimeError(f"expected 3 repeats: {status['run_slug']}/{arm}")
            def values(key: str) -> list[float]:
                return [float(cell[key]) for cell in cells]
            grouped.append(
                {
                    "window_id": status["window_id"],
                    "run_slug": status["run_slug"],
                    "arm": arm,
                    "repeats": 3,
                    "common_poses": cells[0]["common_poses"],
                    "rpe_pairs": cells[0]["rpe_pairs"],
                    "fixed_se3_ape_rmse_median_m": finite_median(values("fixed_se3_ape_rmse_m")),
                    "fixed_se3_ape_rmse_range_m": range_text(values("fixed_se3_ape_rmse_m")),
                    "fixed_se3_rpe_rmse_median_m": finite_median(values("fixed_se3_rpe_rmse_m")),
                    "fixed_se3_rpe_rmse_range_m": range_text(values("fixed_se3_rpe_rmse_m")),
                    "sim3_scale_median": finite_median(values("sim3_scale")),
                    "sim3_scale_range": range_text(values("sim3_scale")),
                    "sim3_ape_rmse_median_m": finite_median(values("sim3_ape_rmse_m")),
                    "sim3_ape_rmse_range_m": range_text(values("sim3_ape_rmse_m")),
                    "sim3_rpe_rmse_median_m": finite_median(values("sim3_rpe_rmse_m")),
                    "sim3_rpe_rmse_range_m": range_text(values("sim3_rpe_rmse_m")),
                    "max_evo_abs_diff_m": max(values("max_evo_abs_diff_m")),
                }
            )
    write_csv(PAPER / "accuracy_repeats.csv", repeats)
    write_csv(PAPER / "accuracy.csv", grouped)
    return repeats, grouped


def exact_sign_p(wins: int, losses: int) -> float:
    n = wins + losses
    if n == 0:
        return math.nan
    tail = sum(math.comb(n, k) for k in range(0, min(wins, losses) + 1)) / 2**n
    return min(1.0, 2.0 * tail)


def bootstrap_median_log_ci(values: list[float]) -> tuple[float, float]:
    if not values:
        return math.nan, math.nan
    array = np.asarray(values, dtype=float)
    rng = np.random.default_rng(20260904)
    draws = rng.choice(array, size=(100000, len(array)), replace=True)
    medians = np.median(draws, axis=1)
    return tuple(float(value) for value in np.quantile(medians, [0.025, 0.975]))


def pairwise_stats(
    runability: list[dict[str, object]], accuracy: list[dict[str, object]]
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    by_accuracy = {
        (str(row["run_slug"]), str(row["arm"])): row for row in accuracy
    }
    by_run = {(str(row["run_slug"]), str(row["arm"])): row for row in runability}
    detailed: list[dict[str, object]] = []
    for run_slug in sorted({str(row["run_slug"]) for row in accuracy}):
        proposed = by_accuracy[(run_slug, "xfeat_v3")]
        for comparator in ("klt", "splg"):
            baseline = by_accuracy[(run_slug, comparator)]
            identical = (
                by_run[(run_slug, "xfeat_v3")]["feature_bag_sha256"]
                == by_run[(run_slug, comparator)]["feature_bag_sha256"]
            )
            for metric, field in (
                ("ape", "fixed_se3_ape_rmse_median_m"),
                ("rpe", "fixed_se3_rpe_rmse_median_m"),
            ):
                ratio = float(proposed[field]) / float(baseline[field])
                detailed.append(
                    {
                        "window_id": proposed["window_id"],
                        "run_slug": run_slug,
                        "comparator": comparator,
                        "metric": metric,
                        "pairwise_feature_bags_identical": str(identical).lower(),
                        "included": str(not identical).lower(),
                        "xfeat_v3_value_m": proposed[field],
                        "comparator_value_m": baseline[field],
                        "ratio": ratio,
                        "log_ratio": math.log(ratio),
                        "percent_change": 100.0 * (ratio - 1.0),
                        "outcome": "win" if ratio < 1.0 else "loss" if ratio > 1.0 else "tie",
                    }
                )
    summaries: list[dict[str, object]] = []
    for comparator in ("klt", "splg"):
        for metric in ("ape", "rpe"):
            cells = [
                row
                for row in detailed
                if row["comparator"] == comparator
                and row["metric"] == metric
                and row["included"] == "true"
            ]
            logs = [float(row["log_ratio"]) for row in cells]
            ci_low, ci_high = bootstrap_median_log_ci(logs)
            wins = sum(row["outcome"] == "win" for row in cells)
            losses = sum(row["outcome"] == "loss" for row in cells)
            ties = sum(row["outcome"] == "tie" for row in cells)
            median_log = float(median(logs)) if logs else math.nan
            summaries.append(
                {
                    "comparator": comparator,
                    "metric": metric,
                    "n_windows": len(cells),
                    "wins": wins,
                    "ties": ties,
                    "losses": losses,
                    "median_ratio": math.exp(median_log) if logs else math.nan,
                    "median_percent_change": 100.0 * (math.exp(median_log) - 1.0) if logs else math.nan,
                    "bootstrap95_ratio_low": math.exp(ci_low) if logs else math.nan,
                    "bootstrap95_ratio_high": math.exp(ci_high) if logs else math.nan,
                    "sign_test_two_sided_p": exact_sign_p(wins, losses) if metric == "ape" else math.nan,
                    "holm_adjusted_p": math.nan,
                }
            )
    primary = [row for row in summaries if row["metric"] == "ape"]
    ordered = sorted(primary, key=lambda row: float(row["sign_test_two_sided_p"]))
    running = 0.0
    for index, row in enumerate(ordered):
        raw = float(row["sign_test_two_sided_p"])
        adjusted = min(1.0, raw * (len(ordered) - index))
        running = max(running, adjusted)
        row["holm_adjusted_p"] = running
    write_csv(PAPER / "pairwise_windows.csv", detailed)
    write_csv(PAPER / "pairwise_summary.csv", summaries)
    return detailed, summaries


def write_manifest() -> None:
    paths: list[Path] = []
    for name in (
        "preregistration.md",
        "candidate_windows.csv",
        "arms.csv",
        "contract.json",
        "current_history_audit.csv",
        "execution_notes.md",
        "frontend_runability.csv",
        "runability.csv",
        "backend_config_audit.csv",
        "common_support_status.csv",
        "accuracy_repeats.csv",
        "accuracy.csv",
        "pairwise_windows.csv",
        "pairwise_summary.csv",
        "report.md",
    ):
        path = PAPER / name
        if path.is_file():
            paths.append(path)
    common = PAPER / "common_support"
    if common.exists():
        paths.extend(path for path in common.rglob("*") if path.is_file())
    for base in (
        RUNTIME / "backend_canonical",
        RUNTIME / "replays",
        RUNTIME / "shadow_root/logs",
        RUNTIME / "prepared",
    ):
        if not base.exists():
            continue
        for path in base.rglob("*"):
            if not path.is_file() or "quarantine" in path.parts:
                continue
            if path.name in {
                "features.bag",
                "frontend_metrics.csv",
                "confirmatory_frontend_receipt.json",
                "vins_same_backend.yaml",
                "vio.csv",
                "vins.log",
                "replay_receipt.txt",
                "materialization_receipt.json",
            } or (path.suffix == ".yaml" and "backend_canonical" in path.parts):
                paths.append(path)
    for name in (
        "run_frontend_same_backend_confirmatory_v3.py",
        "run_frontend_same_backend_confirmatory_v3_batch.py",
        "run_frontend_same_backend_confirmatory_v3_service.sh",
        "materialize_frontend_same_backend_confirmatory_v3_a04.py",
        "analyze_frontend_same_backend_confirmatory_v3.py",
        "run_frontend_same_backend_confirmatory_v3_backend.py",
        "run_frontend_same_backend_confirmatory_v3_backend_cell.sh",
        "run_frontend_same_backend_confirmatory_v3_backend_service.sh",
        "evaluate_vins_common_support_dual_scale.py",
        "finalize_frontend_same_backend_confirmatory_v3.py",
    ):
        paths.append(ROOT / "scripts" / name)
    unique = sorted({path.resolve() for path in paths if path.is_file()}, key=str)
    (PAPER / "artifacts.sha256").write_text(
        "".join(f"{sha256(path)}  {path}\n" for path in unique), encoding="utf-8"
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("stage", choices=("collect", "evaluate", "all"), default="all", nargs="?")
    args = parser.parse_args()
    frontend.verify_lock()
    runability = collect_runability()
    if args.stage in ("evaluate", "all"):
        statuses = evaluate(runability)
    elif (PAPER / "common_support_status.csv").is_file():
        statuses = read_csv(PAPER / "common_support_status.csv")
    else:
        statuses = []
    _, accuracy = collect_accuracy(statuses)
    pairwise_stats(runability, accuracy)
    write_manifest()
    print(
        f"runability_rows={len(runability)} accuracy_rows={len(accuracy)} "
        f"common_support_pass={sum(row['status'] == 'PASS' for row in statuses)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
