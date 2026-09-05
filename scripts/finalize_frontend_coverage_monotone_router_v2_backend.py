#!/usr/bin/env python3
"""Reduce the frozen coverage-monotone-router-v2 backend continuation.

The script does not modify frozen inputs or replay outputs.  It audits the 42
cell receipts, applies the preregistered runability gate, and evaluates each
active learned intervention together with fresh KLT and its own matched-GFTT
control on one exact nine-trajectory common support.
"""

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
PAPER = ROOT / "papers/frontend_coverage_monotone_router_v2"
RUNTIME = Path(
    "/media/ma/Data/AQUA-FE_WS_storage_offload/"
    "frontend_coverage_monotone_router_v2"
)
REPLAYS = RUNTIME / "backend_replays"
PLAN = PAPER / "backend_smoke_plan.csv"
LOCK = PAPER / "backend_execution_lock.json"
EVALUATOR = ROOT / "scripts/evaluate_vins_common_support_dual_scale.py"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as stream:
        return list(csv.DictReader(stream))


def write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    fields: list[str] = []
    for row in rows:
        for key in row:
            if key not in fields:
                fields.append(key)
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def parse_receipt(path: Path) -> dict[str, str]:
    if not path.is_file():
        return {}
    return dict(
        line.split("=", 1)
        for line in path.read_text(encoding="utf-8", errors="ignore").splitlines()
        if "=" in line
    )


def verify_lock() -> tuple[int, int]:
    lock = json.loads(LOCK.read_text(encoding="utf-8"))
    checks = [(Path(item["path"]), item["sha256"]) for item in lock["files"]]
    checks += [
        (Path(lock["vins_workspace"]) / "devel/lib/vins/vins_node", lock["vins_node_sha256"]),
        (Path(lock["vins_workspace"]) / "devel/lib/libvins_lib.so", lock["vins_lib_sha256"]),
    ]
    failures = [str(path) for path, expected in checks if not path.is_file() or sha256(path) != expected]
    if failures:
        raise RuntimeError("frozen backend identity failure: " + "; ".join(failures))
    return len(checks), len(checks)


def pose_stats(path: Path) -> tuple[int, float]:
    stamps: list[float] = []
    if path.is_file():
        with path.open(encoding="utf-8", errors="ignore") as stream:
            for line in stream:
                first = line.split(",", 1)[0].strip()
                if re.fullmatch(r"\d+", first):
                    stamps.append(int(first) * 1e-9)
    if not stamps:
        return 0, 0.0
    return len(stamps), max(0.0, stamps[-1] - stamps[0])


def reference_stats(feature_bag: Path, topic: str) -> tuple[int, float]:
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


def topic_for(window_id: str) -> str:
    return "/afrl/colmap_gt" if window_id.startswith("afrl:") else "/aqualoc/colmap_gt"


def range_text(values: list[float], digits: int = 9) -> str:
    finite = [value for value in values if math.isfinite(value)]
    if not finite:
        return ""
    return f"{min(finite):.{digits}f}–{max(finite):.{digits}f}"


def classify_failure(log_text: str, receipt_ok: bool, initialized: bool, coverage: float) -> str:
    lower = log_text.lower()
    if "not enough imu excitation" in lower:
        return "insufficient_excitation"
    if not receipt_ok:
        return "missing_or_invalid_receipt"
    if not initialized:
        return "cold_start_no_initialization"
    if coverage < 0.70:
        return "coverage_failure"
    return ""


def collect_backend_repeats(plan: list[dict[str, str]]) -> list[dict[str, object]]:
    reference_cache: dict[tuple[str, str], tuple[int, float]] = {}
    rows: list[dict[str, object]] = []
    for item in plan:
        run_slug = item["run_slug"]
        cell_id = item["cell_id"]
        repeat = int(item["repeat"])
        run_dir = REPLAYS / run_slug / cell_id / f"repeat{repeat}"
        receipt_path = run_dir / "replay_receipt.txt"
        vio = run_dir / "vins_output/vio.csv"
        log = run_dir / "vins.log"
        receipt = parse_receipt(receipt_path)
        expected_receipt = {
            "window_id": item["window_id"],
            "run_slug": run_slug,
            "cell_id": cell_id,
            "repeat": item["repeat"],
            "feature_bag_sha256": item["feature_bag_sha256"],
            "canonical_config_sha256": item["canonical_config_sha256"],
            "vins_node_sha256": item["vins_node_sha256"],
            "vins_lib_sha256": item["vins_lib_sha256"],
        }
        receipt_ok = bool(receipt) and all(receipt.get(key) == value for key, value in expected_receipt.items())
        vio_hash_ok = bool(
            receipt_ok
            and vio.is_file()
            and vio.stat().st_size > 0
            and receipt.get("vio_csv_sha256") == sha256(vio)
        )
        receipt_ok = receipt_ok and vio_hash_ok
        reference_topic = topic_for(item["window_id"])
        reference_key = (item["feature_bag"], reference_topic)
        if reference_key not in reference_cache:
            reference_cache[reference_key] = reference_stats(Path(item["feature_bag"]), reference_topic)
        reference_count, expected_span = reference_cache[reference_key]
        pose_count, span = pose_stats(vio)
        log_text = log.read_text(encoding="utf-8", errors="ignore") if log.is_file() else ""
        initialized = "Initialization finish!" in log_text and pose_count > 0
        coverage = min(1.0, span / expected_span) if expected_span > 0.0 else 0.0
        passed = bool(receipt_ok and initialized and pose_count > 0 and coverage >= 0.70)
        rows.append(
            {
                "window_id": item["window_id"],
                "run_slug": run_slug,
                "cell_id": cell_id,
                "source_arm": item["source_arm"],
                "backend_role": item["backend_role"],
                "repeat": repeat,
                "receipt_identity_pass": receipt_ok,
                "init": "PASS" if initialized else "FAIL",
                "pose_count": pose_count,
                "trajectory_span_s": f"{span:.9f}",
                "reference_pose_count": reference_count,
                "reference_span_s": f"{expected_span:.9f}",
                "coverage": f"{coverage:.9f}",
                "repeat_status": "PASS" if passed else "FAIL",
                "failure_class": classify_failure(log_text, receipt_ok, initialized, coverage),
                "feature_bag": item["feature_bag"],
                "feature_bag_sha256": item["feature_bag_sha256"],
                "canonical_config": item["canonical_config"],
                "canonical_config_sha256": item["canonical_config_sha256"],
                "vio_csv": str(vio),
                "vio_csv_sha256": sha256(vio) if vio.is_file() and vio.stat().st_size else "",
                "vins_log": str(log),
                "replay_receipt": str(receipt_path),
            }
        )
    write_csv(PAPER / "backend_results_repeats.csv", rows)
    return rows


def aggregate_backend(repeats: list[dict[str, object]]) -> list[dict[str, object]]:
    groups: dict[tuple[str, str], list[dict[str, object]]] = {}
    for row in repeats:
        groups.setdefault((str(row["run_slug"]), str(row["cell_id"])), []).append(row)
    output: list[dict[str, object]] = []
    for (run_slug, cell_id), cells in sorted(groups.items()):
        cells.sort(key=lambda row: int(row["repeat"]))
        if len(cells) != 3:
            raise RuntimeError(f"expected three repeats: {run_slug}/{cell_id}")
        poses = [float(row["pose_count"]) for row in cells]
        spans = [float(row["trajectory_span_s"]) for row in cells]
        coverage = [float(row["coverage"]) for row in cells]
        passes = [row["repeat_status"] == "PASS" for row in cells]
        output.append(
            {
                "window_id": cells[0]["window_id"],
                "run_slug": run_slug,
                "cell_id": cell_id,
                "source_arm": cells[0]["source_arm"],
                "backend_role": cells[0]["backend_role"],
                "backend_replays_completed": 3,
                "backend_repeats_pass": f"{sum(passes)}/3",
                "arm_window_status": "PASS" if all(passes) else "FAIL",
                "init_repeats": sum(row["init"] == "PASS" for row in cells),
                "pose_count_median": median(poses),
                "pose_count_range": range_text(poses, 0),
                "trajectory_span_median_s": median(spans),
                "trajectory_span_range_s": range_text(spans),
                "coverage_median": median(coverage),
                "coverage_range": range_text(coverage),
                "failure_classes": ";".join(sorted({str(row["failure_class"]) for row in cells if row["failure_class"]})),
                "feature_bag": cells[0]["feature_bag"],
                "feature_bag_sha256": cells[0]["feature_bag_sha256"],
                "canonical_config_sha256": cells[0]["canonical_config_sha256"],
            }
        )
    write_csv(PAPER / "backend_results.csv", output)
    return output


def build_runability(backend: list[dict[str, object]]) -> list[dict[str, object]]:
    by_cell = {(str(row["run_slug"]), str(row["cell_id"])): row for row in backend}
    frontend_rows = read_csv(PAPER / "frontend_audit.csv")
    output: list[dict[str, object]] = []
    for front in frontend_rows:
        arm = front["arm"]
        exact_fallback = arm != "klt" and front["byte_identical_to_klt"] == "True"
        mapped = "klt" if exact_fallback or arm == "klt" else arm
        back = by_cell[(front["run_slug"], mapped)]
        output.append(
            {
                "window_id": front["window_id"],
                "run_slug": front["run_slug"],
                "arm": arm,
                "role": "frontend_primary",
                "frontend_action": int(front["kept_sidecars"]) > 0,
                "feature_bag_sha256": front["feature_bag_sha256"],
                "backend_execution": "REUSED_EXACT_KLT" if exact_fallback else "INDEPENDENT_REPLAY",
                "mapped_backend_cell": mapped,
                "independent_replays": 0 if exact_fallback else 3,
                "mapped_replays": 3 if exact_fallback else 0,
                "backend_repeats_pass": back["backend_repeats_pass"],
                "arm_window_status": back["arm_window_status"],
                "init_repeats": back["init_repeats"],
                "pose_count_median": back["pose_count_median"],
                "pose_count_range": back["pose_count_range"],
                "coverage_median": back["coverage_median"],
                "coverage_range": back["coverage_range"],
                "accuracy_role": "EXACT_TIE_NO_ACTION" if exact_fallback else "EVALUATE_IF_COMMON_SUPPORT",
            }
        )
    for match in read_csv(PAPER / "matched_control_audit.csv"):
        cell_id = f"matched_gftt_for_{match['arm']}"
        back = by_cell[(match["run_slug"], cell_id)]
        output.append(
            {
                "window_id": back["window_id"],
                "run_slug": match["run_slug"],
                "arm": cell_id,
                "role": "matched_classical_attribution_control",
                "frontend_action": True,
                "feature_bag_sha256": back["feature_bag_sha256"],
                "backend_execution": "INDEPENDENT_REPLAY",
                "mapped_backend_cell": cell_id,
                "independent_replays": 3,
                "mapped_replays": 0,
                "backend_repeats_pass": back["backend_repeats_pass"],
                "arm_window_status": back["arm_window_status"],
                "init_repeats": back["init_repeats"],
                "pose_count_median": back["pose_count_median"],
                "pose_count_range": back["pose_count_range"],
                "coverage_median": back["coverage_median"],
                "coverage_range": back["coverage_range"],
                "accuracy_role": "EVALUATE_WITH_CORRESPONDING_LEARNED_ARM",
            }
        )
    write_csv(PAPER / "runability.csv", output)
    return output


def active_comparisons() -> list[dict[str, str]]:
    output = []
    for row in read_csv(PAPER / "matched_control_audit.csv"):
        output.append(
            {
                "comparison_id": f"{row['run_slug']}__{row['arm']}",
                "run_slug": row["run_slug"],
                "learned_arm": row["arm"],
                "matched_cell": f"matched_gftt_for_{row['arm']}",
            }
        )
    return output


def evaluate_common_support(
    comparisons: list[dict[str, str]],
    backend: list[dict[str, object]],
) -> list[dict[str, object]]:
    by_cell = {(str(row["run_slug"]), str(row["cell_id"])): row for row in backend}
    status_rows: list[dict[str, object]] = []
    for comparison in comparisons:
        run_slug = comparison["run_slug"]
        cells = {
            "klt": by_cell[(run_slug, "klt")],
            "learned": by_cell[(run_slug, comparison["learned_arm"])],
            "matched": by_cell[(run_slug, comparison["matched_cell"])],
        }
        status: dict[str, object] = {
            **comparison,
            "window_id": cells["klt"]["window_id"],
            "status": "",
            "return_code": "",
            "matched_count": "",
            "common_span_s": "",
            "common_coverage": "",
            "rpe_pairs": "",
        }
        if not all(row["arm_window_status"] == "PASS" for row in cells.values()):
            status["status"] = "NOT_ALL_THREE_CELLS_BACKEND_PASS"
            status_rows.append(status)
            continue
        reference_topic = topic_for(str(cells["klt"]["window_id"]))
        config_paths = {str(row["canonical_config_sha256"]) for row in cells.values()}
        if len(config_paths) != 1:
            raise RuntimeError(f"backend config hash mismatch: {comparison['comparison_id']}")
        output_dir = PAPER / "common_support" / comparison["comparison_id"]
        command = [
            sys.executable,
            str(EVALUATOR),
            "--reference-bag",
            str(cells["klt"]["feature_bag"]),
            "--reference-topic",
            reference_topic,
            "--evaluation-rate-hz",
            "1",
            "--max-reference-gap-s",
            "2.5",
            "--max-estimate-gap-s",
            "0.25",
            "--output-dir",
            str(output_dir),
            "--run-evo",
        ]
        for role, row in cells.items():
            config = next(
                item["canonical_config"]
                for item in read_csv(PLAN)
                if item["run_slug"] == run_slug and item["cell_id"] == row["cell_id"]
            )
            for repeat in range(1, 4):
                name = f"{role}_r{repeat}"
                vio = REPLAYS / run_slug / str(row["cell_id"]) / f"repeat{repeat}/vins_output/vio.csv"
                command += ["--arm", f"{name}={vio}", "--arm-config", f"{name}={config}"]
        process = subprocess.run(
            command,
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
        )
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / "evaluator.log").write_text(process.stdout, encoding="utf-8")
        summary_path = output_dir / "common_support_summary.json"
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
        status_rows.append(status)
    write_csv(PAPER / "common_support_status.csv", status_rows)
    return status_rows


def collect_accuracy(statuses: list[dict[str, object]]) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    repeats: list[dict[str, object]] = []
    for status in statuses:
        if status["status"] != "PASS":
            continue
        output_dir = PAPER / "common_support" / str(status["comparison_id"])
        metrics = read_csv(output_dir / "common_support_metrics.csv")
        evo = json.loads((output_dir / "evo_crosscheck.json").read_text(encoding="utf-8"))
        for metric in metrics:
            match = re.fullmatch(r"(klt|learned|matched)_r([123])", metric["arm"])
            if not match:
                raise RuntimeError(f"unexpected evaluator arm: {metric['arm']}")
            role, repeat = match.groups()
            cross = evo["arms"][metric["arm"]]
            repeats.append(
                {
                    "comparison_id": status["comparison_id"],
                    "window_id": status["window_id"],
                    "run_slug": status["run_slug"],
                    "learned_arm": status["learned_arm"],
                    "role": role,
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
    for status in statuses:
        if status["status"] != "PASS":
            continue
        for role in ("klt", "learned", "matched"):
            cells = [row for row in repeats if row["comparison_id"] == status["comparison_id"] and row["role"] == role]
            if len(cells) != 3:
                raise RuntimeError(f"expected three accuracy repeats: {status['comparison_id']}/{role}")
            def values(key: str) -> list[float]:
                return [float(cell[key]) for cell in cells]
            grouped.append(
                {
                    "comparison_id": status["comparison_id"],
                    "window_id": status["window_id"],
                    "run_slug": status["run_slug"],
                    "learned_arm": status["learned_arm"],
                    "role": role,
                    "repeats": 3,
                    "common_poses": cells[0]["common_poses"],
                    "rpe_pairs": cells[0]["rpe_pairs"],
                    "fixed_se3_ape_rmse_median_m": median(values("fixed_se3_ape_rmse_m")),
                    "fixed_se3_ape_rmse_range_m": range_text(values("fixed_se3_ape_rmse_m")),
                    "fixed_se3_rpe_rmse_median_m": median(values("fixed_se3_rpe_rmse_m")),
                    "fixed_se3_rpe_rmse_range_m": range_text(values("fixed_se3_rpe_rmse_m")),
                    "sim3_scale_median": median(values("sim3_scale")),
                    "sim3_scale_range": range_text(values("sim3_scale")),
                    "sim3_ape_rmse_median_m": median(values("sim3_ape_rmse_m")),
                    "sim3_ape_rmse_range_m": range_text(values("sim3_ape_rmse_m")),
                    "sim3_rpe_rmse_median_m": median(values("sim3_rpe_rmse_m")),
                    "sim3_rpe_rmse_range_m": range_text(values("sim3_rpe_rmse_m")),
                    "max_evo_abs_diff_m": max(values("max_evo_abs_diff_m")),
                }
            )
    write_csv(PAPER / "accuracy_repeats.csv", repeats)
    write_csv(PAPER / "accuracy.csv", grouped)
    return repeats, grouped


def primary_outcome(proposed: float, comparator: float) -> str:
    return "WIN" if proposed < comparator else "LOSS" if proposed > comparator else "TIE"


def joint_outcome(ape_ratio: float, rpe_ratio: float) -> str:
    if ape_ratio < 1.0 and rpe_ratio < 1.0:
        return "BOTH_WIN"
    if ape_ratio > 1.0 and rpe_ratio > 1.0:
        return "BOTH_LOSS"
    if ape_ratio == 1.0 and rpe_ratio == 1.0:
        return "EXACT_TIE"
    return "MIXED"


def build_comparisons(statuses: list[dict[str, object]], accuracy: list[dict[str, object]]) -> list[dict[str, object]]:
    by_accuracy = {(str(row["comparison_id"]), str(row["role"])): row for row in accuracy}
    output: list[dict[str, object]] = []
    for status in statuses:
        base: dict[str, object] = {
            "comparison_id": status["comparison_id"],
            "window_id": status["window_id"],
            "run_slug": status["run_slug"],
            "learned_arm": status["learned_arm"],
            "common_support_status": status["status"],
            "common_poses": status["matched_count"],
            "common_span_s": status["common_span_s"],
            "common_coverage": status["common_coverage"],
            "rpe_pairs": status["rpe_pairs"],
        }
        if status["status"] != "PASS":
            base.update(
                {
                    "learned_vs_klt_primary_outcome": "FAIL",
                    "learned_vs_matched_primary_outcome": "FAIL",
                    "failure_reason": status["status"],
                }
            )
            output.append(base)
            continue
        learned = by_accuracy[(str(status["comparison_id"]), "learned")]
        klt = by_accuracy[(str(status["comparison_id"]), "klt")]
        matched = by_accuracy[(str(status["comparison_id"]), "matched")]
        l_ape = float(learned["fixed_se3_ape_rmse_median_m"])
        l_rpe = float(learned["fixed_se3_rpe_rmse_median_m"])
        for name, row in (("klt", klt), ("matched", matched)):
            c_ape = float(row["fixed_se3_ape_rmse_median_m"])
            c_rpe = float(row["fixed_se3_rpe_rmse_median_m"])
            ape_ratio = l_ape / c_ape
            rpe_ratio = l_rpe / c_rpe
            base.update(
                {
                    f"learned_vs_{name}_primary_outcome": primary_outcome(l_ape, c_ape),
                    f"learned_vs_{name}_joint_outcome": joint_outcome(ape_ratio, rpe_ratio),
                    f"learned_vs_{name}_ape_percent_change": 100.0 * (ape_ratio - 1.0),
                    f"learned_vs_{name}_rpe_percent_change": 100.0 * (rpe_ratio - 1.0),
                }
            )
        base.update(
            {
                "klt_fixed_se3_ape_median_m": klt["fixed_se3_ape_rmse_median_m"],
                "learned_fixed_se3_ape_median_m": learned["fixed_se3_ape_rmse_median_m"],
                "matched_fixed_se3_ape_median_m": matched["fixed_se3_ape_rmse_median_m"],
                "klt_fixed_se3_rpe_median_m": klt["fixed_se3_rpe_rmse_median_m"],
                "learned_fixed_se3_rpe_median_m": learned["fixed_se3_rpe_rmse_median_m"],
                "matched_fixed_se3_rpe_median_m": matched["fixed_se3_rpe_rmse_median_m"],
                "failure_reason": "",
            }
        )
        output.append(base)
    write_csv(PAPER / "backend_comparisons.csv", output)
    return output


def main() -> int:
    identity_passed, identity_total = verify_lock()
    plan = read_csv(PLAN)
    if len(plan) != 42:
        raise RuntimeError(f"expected 42 frozen plan rows, got {len(plan)}")
    repeats = collect_backend_repeats(plan)
    backend = aggregate_backend(repeats)
    runability = build_runability(backend)
    comparisons = active_comparisons()
    statuses = evaluate_common_support(comparisons, backend)
    accuracy_repeats, accuracy = collect_accuracy(statuses)
    outcomes = build_comparisons(statuses, accuracy)
    print(
        json.dumps(
            {
                "identity": f"{identity_passed}/{identity_total}",
                "backend_repeats": len(repeats),
                "backend_cells": len(backend),
                "runability_rows": len(runability),
                "comparisons": len(outcomes),
                "common_support_pass": sum(row["status"] == "PASS" for row in statuses),
                "accuracy_repeat_rows": len(accuracy_repeats),
                "accuracy_rows": len(accuracy),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
