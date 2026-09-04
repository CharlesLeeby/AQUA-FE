#!/usr/bin/env python3
"""Evaluate KLT versus persistence-conditioned replacement on locked support."""

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
PAPER = ROOT / "papers/frontend_persistence_conditioned_replacement_v1"
RUNTIME = ROOT / "artifacts/frontend_persistence_conditioned_replacement_v1"
EVALUATOR = ROOT / "scripts/evaluate_vins_common_support_dual_scale.py"
ARMS = ("klt", "persistence_replace")


CASES = {
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
    "a06_s000_d045": {
        "klt_bag": ROOT / "artifacts/frontend_same_backend_comparison_supplement/shadow_root/logs/aqualoc_archaeo_vins/external_klt_every2_fsbcsupp_a06_s000_d045_klt_frontend/features.bag",
        "klt_run": str(ROOT / "artifacts/frontend_same_backend_comparison_supplement/replays/a06_s000_d045/klt/repeat{repeat}"),
        "klt_config": str(ROOT / "artifacts/frontend_same_backend_comparison_supplement/backend_canonical/a06_s000_d045/vins_same_backend.yaml"),
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


def normalized_config_hash(path: Path) -> str:
    text = re.sub(
        r'^output_path:\s*".*"$', 'output_path: "<NORMALIZED>"',
        path.read_text(encoding="utf-8"), flags=re.MULTILINE,
    )
    return hashlib.sha256(text.encode()).hexdigest()


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


def klt_run(window: str, repeat: int) -> Path:
    return Path(str(CASES[window]["klt_run"]).format(repeat=repeat))


def arm_run(window: str, arm: str, repeat: int, identical: bool) -> Path:
    if arm == "klt" or identical:
        return klt_run(window, repeat)
    return RUNTIME / "replays" / window / "persistence_replace" / f"repeat{repeat}"


def pose_stats(path: Path) -> tuple[int, float]:
    stamps: list[float] = []
    if path.is_file():
        for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
            first = line.split(",", 1)[0].strip()
            if re.fullmatch(r"\d+", first):
                stamps.append(int(first) * 1e-9)
    return len(stamps), max(0.0, stamps[-1] - stamps[0]) if stamps else 0.0


def reference_span(path: Path) -> float:
    stamps: list[float] = []
    with rosbag.Bag(str(path)) as bag:
        for _, message, record_time in bag.read_messages(topics=["/aqualoc/colmap_gt"]):
            header = getattr(message, "header", None)
            stamps.append(float(header.stamp.to_sec()) if header is not None else record_time.to_sec())
    if len(stamps) < 2:
        raise RuntimeError(f"insufficient proxy poses: {path}")
    return stamps[-1] - stamps[0]


def finite_median(values: list[float]) -> float:
    return float(median(value for value in values if math.isfinite(value)))


def value_range(values: list[float]) -> str:
    values = [value for value in values if math.isfinite(value)]
    return f"{min(values):.9f}–{max(values):.9f}"


def main() -> int:
    validation = {row["window"]: row for row in read_csv(PAPER / "frontend_validation.csv")}
    run_repeats: list[dict[str, object]] = []
    run_summary: list[dict[str, object]] = []
    audit: list[dict[str, object]] = []
    for window, case in CASES.items():
        identical = validation[window]["whole_bag_byte_identical_to_klt"].lower() == "true"
        span_expected = reference_span(Path(case["klt_bag"]))
        for arm in ARMS:
            passed = []
            for repeat in range(1, 4):
                run = arm_run(window, arm, repeat, identical)
                vio = run / "vins_output/vio.csv"
                log = run / "vins.log"
                count, span = pose_stats(vio)
                initialized = "Initialization finish!" in (
                    log.read_text(encoding="utf-8", errors="ignore") if log.is_file() else ""
                )
                coverage = min(1.0, span / span_expected) if span_expected > 0 else 0.0
                gate = initialized and count >= 30 and span >= 10.0 and coverage >= 0.70
                passed.append(gate)
                run_repeats.append(
                    {
                        "window": window, "arm": arm, "repeat": repeat,
                        "status": "PASS" if gate else "FAIL", "initialized": initialized,
                        "pose_count": count, "span_s": span, "reference_span_s": span_expected,
                        "coverage": coverage, "reuse_exact_klt_input": arm != "klt" and identical,
                        "vio_csv": str(vio), "vins_log": str(log),
                    }
                )
                actual_config = (
                    Path(str(case["klt_config"]).format(repeat=repeat))
                    if arm == "klt" or identical
                    else RUNTIME / "backend_canonical" / window / "vins_same_backend.yaml"
                )
                feature_bag = (
                    Path(case["klt_bag"])
                    if arm == "klt" or identical
                    else Path(validation[window]["feature_bag_sha256"])
                )
                # For a distinct learned input, validation records the hash but the
                # path is fixed by the backend receipt; recover it from that receipt.
                if arm != "klt" and not identical:
                    receipt = run / "replay_receipt.txt"
                    receipt_data = dict(
                        line.split("=", 1) for line in receipt.read_text(encoding="utf-8").splitlines()
                        if "=" in line
                    )
                    feature_bag = Path(receipt_data["feature_bag"])
                audit.append(
                    {
                        "window": window, "arm": arm, "repeat": repeat,
                        "status": "FROZEN_RESULT_REUSE" if arm == "klt" or identical else "COMPLETE",
                        "feature_bag": str(feature_bag), "feature_bag_sha256": sha256(feature_bag),
                        "config": str(actual_config), "config_sha256": sha256(actual_config),
                        "normalized_backend_config_sha256": normalized_config_hash(actual_config),
                        "vins_node_sha256": sha256(Path("/home/ma/SLAM/VINS-Fusion-origin/devel/lib/vins/vins_node")),
                        "libvins_sha256": sha256(Path("/home/ma/SLAM/VINS-Fusion-origin/devel/lib/libvins_lib.so")),
                        "vio_csv": str(vio), "vio_csv_sha256": sha256(vio) if vio.is_file() else "MISSING",
                    }
                )
            run_summary.append(
                {
                    "window": window, "arm": arm,
                    "status": "PASS" if all(passed) else "FAIL",
                    "repeats_passed": sum(passed), "repeats_required": 3,
                    "reuse_exact_klt_input": arm != "klt" and identical,
                }
            )
        config_hashes = {row["normalized_backend_config_sha256"] for row in audit if row["window"] == window}
        if len(config_hashes) != 1:
            raise RuntimeError(f"backend config mismatch beyond output_path: {window} {config_hashes}")
    write_csv(PAPER / "runability_repeats.csv", run_repeats)
    write_csv(PAPER / "runability.csv", run_summary)
    write_csv(PAPER / "backend_config_audit.csv", audit)

    support_rows: list[dict[str, object]] = []
    accuracy_repeats: list[dict[str, object]] = []
    for window, case in CASES.items():
        window_runable = all(
            row["status"] == "PASS" for row in run_summary if row["window"] == window
        )
        if not window_runable:
            support_rows.append({"window": window, "status": "EXCLUDED_RUNABILITY"})
            continue
        identical = validation[window]["whole_bag_byte_identical_to_klt"].lower() == "true"
        config = RUNTIME / "backend_canonical" / window / "vins_same_backend.yaml"
        output = PAPER / "common_support" / window
        command = [
            sys.executable, str(EVALUATOR), "--reference-bag", str(case["klt_bag"]),
            "--reference-topic", "/aqualoc/colmap_gt", "--evaluation-rate-hz", "1",
            "--max-reference-gap-s", "2.5", "--max-estimate-gap-s", "0.25",
            "--output-dir", str(output), "--run-evo",
        ]
        for arm in ARMS:
            for repeat in range(1, 4):
                name = f"{arm}_r{repeat}"
                vio = arm_run(window, arm, repeat, identical) / "vins_output/vio.csv"
                command += ["--arm", f"{name}={vio}", "--arm-config", f"{name}={config}"]
        process = subprocess.run(
            command, cwd=ROOT, text=True, stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT, check=False,
        )
        output.mkdir(parents=True, exist_ok=True)
        (output / "evaluator.log").write_text(process.stdout, encoding="utf-8")
        summary_file = output / "common_support_summary.json"
        support = {}
        if summary_file.is_file():
            support = json.loads(summary_file.read_text(encoding="utf-8"))["support"]
        admitted = bool(
            process.returncode == 0 and support.get("ape_valid") and support.get("rpe_valid")
        )
        support_rows.append(
            {
                "window": window, "status": "PASS" if admitted else "EXCLUDED_COMMON_SUPPORT",
                "return_code": process.returncode, "matched_count": support.get("matched_count", ""),
                "common_span_s": support.get("common_span_s", ""),
                "common_coverage": support.get("common_coverage", ""),
                "rpe_pairs": support.get("rpe_pairs", ""),
            }
        )
        if not admitted:
            continue
        evo = json.loads((output / "evo_crosscheck.json").read_text(encoding="utf-8"))["arms"]
        for row in read_csv(output / "common_support_metrics.csv"):
            match = re.fullmatch(r"(klt|persistence_replace)_r([123])", row["arm"])
            if not match:
                continue
            arm, repeat = match.groups()
            check = evo[row["arm"]]
            accuracy_repeats.append(
                {
                    "window": window, "arm": arm, "repeat": int(repeat),
                    "common_poses": int(row["matched_count"]), "rpe_pairs": int(row["rpe_pairs"]),
                    "fixed_se3_ape_rmse_m": float(row["fixed_se3_ape_rmse_m"]),
                    "fixed_se3_rpe_rmse_m": float(row["fixed_se3_rpe_rmse_m"]),
                    "sim3_scale": float(row["sim3_scale"]),
                    "sim3_ape_rmse_m": float(row["sim3_ape_rmse_m"]),
                    "sim3_rpe_rmse_m": float(row["sim3_rpe_rmse_m"]),
                    "max_evo_abs_diff_m": max(
                        float(check[mode][metric]) for mode in ("fixed_se3", "sim3")
                        for metric in ("ape_abs_diff_m", "rpe_abs_diff_m")
                    ),
                }
            )
    write_csv(PAPER / "common_support_status.csv", support_rows)
    write_csv(PAPER / "accuracy_repeats.csv", accuracy_repeats)

    grouped: list[dict[str, object]] = []
    for window in CASES:
        for arm in ARMS:
            cells = [row for row in accuracy_repeats if row["window"] == window and row["arm"] == arm]
            if not cells:
                continue
            grouped.append(
                {
                    "window": window, "arm": arm, "repeats": len(cells),
                    "common_poses": cells[0]["common_poses"], "rpe_pairs": cells[0]["rpe_pairs"],
                    "fixed_se3_ape_rmse_median_m": finite_median([float(c["fixed_se3_ape_rmse_m"]) for c in cells]),
                    "fixed_se3_ape_rmse_range_m": value_range([float(c["fixed_se3_ape_rmse_m"]) for c in cells]),
                    "fixed_se3_rpe_rmse_median_m": finite_median([float(c["fixed_se3_rpe_rmse_m"]) for c in cells]),
                    "fixed_se3_rpe_rmse_range_m": value_range([float(c["fixed_se3_rpe_rmse_m"]) for c in cells]),
                    "sim3_scale_median": finite_median([float(c["sim3_scale"]) for c in cells]),
                    "sim3_scale_range": value_range([float(c["sim3_scale"]) for c in cells]),
                    "sim3_ape_rmse_median_m": finite_median([float(c["sim3_ape_rmse_m"]) for c in cells]),
                    "sim3_ape_rmse_range_m": value_range([float(c["sim3_ape_rmse_m"]) for c in cells]),
                    "sim3_rpe_rmse_median_m": finite_median([float(c["sim3_rpe_rmse_m"]) for c in cells]),
                    "sim3_rpe_rmse_range_m": value_range([float(c["sim3_rpe_rmse_m"]) for c in cells]),
                    "max_evo_abs_diff_m": max(float(c["max_evo_abs_diff_m"]) for c in cells),
                }
            )
    write_csv(PAPER / "accuracy.csv", grouped)

    decisions: list[dict[str, object]] = []
    for window in CASES:
        exact = validation[window]["whole_bag_byte_identical_to_klt"].lower() == "true"
        klt = next((row for row in grouped if row["window"] == window and row["arm"] == "klt"), None)
        new = next((row for row in grouped if row["window"] == window and row["arm"] == "persistence_replace"), None)
        run_ok = all(row["status"] == "PASS" for row in run_summary if row["window"] == window)
        if exact:
            label, reason = "NO_HARM_INPUT", "new feature bag is byte-identical to KLT"
        elif not run_ok or not klt or not new:
            label, reason = "REGRESSION", "runability or common-support failure"
        else:
            ka, kr = float(klt["fixed_se3_ape_rmse_median_m"]), float(klt["fixed_se3_rpe_rmse_median_m"])
            na, nr = float(new["fixed_se3_ape_rmse_median_m"]), float(new["fixed_se3_rpe_rmse_median_m"])
            if na < ka and nr < kr:
                label, reason = "WIN", "both fixed-scale APE and RPE medians are lower than KLT"
            elif (na < ka) != (nr < kr):
                label, reason = "MIXED", "fixed-scale APE and RPE directions disagree"
            else:
                klt_cells = [r for r in accuracy_repeats if r["window"] == window and r["arm"] == "klt"]
                outside = (
                    na > max(float(r["fixed_se3_ape_rmse_m"]) for r in klt_cells)
                    and nr > max(float(r["fixed_se3_rpe_rmse_m"]) for r in klt_cells)
                )
                label = "REGRESSION" if outside else "INCONCLUSIVE_WORSE"
                reason = "both fixed-scale medians worsen" + (" outside KLT repeat ranges" if outside else " within KLT repeat variation")
        decisions.append({"window": window, "decision": label, "reason": reason})
    write_csv(PAPER / "decisions.csv", decisions)

    manifest: list[dict[str, object]] = []
    manifest_paths = {
        *PAPER.glob("*.csv"), *PAPER.glob("*.md"), *PAPER.glob("analysis-output/*.md"),
        *PAPER.glob("common_support/**/*.json"), *PAPER.glob("common_support/**/*.csv"),
        *RUNTIME.glob("receipts/*.json"), *RUNTIME.glob("replays/**/replay_receipt.txt"),
        *RUNTIME.glob("replays/**/vins_output/vio.csv"), *RUNTIME.glob("replays/**/vins.log"),
        *RUNTIME.glob("backend_canonical/**/*.yaml"),
        *RUNTIME.glob("shadow_root/logs/**/features.bag"),
        *RUNTIME.glob("shadow_root/logs/**/frontend_metrics.csv"),
        ROOT / "uw_frontend/ros/export_vins_features.py",
        ROOT / "scripts/learned_seedchain_env.sh",
        ROOT / "scripts/run_persistence_conditioned_frontend_v1.py",
        ROOT / "scripts/analyze_persistence_conditioned_frontend_v1.py",
        ROOT / "scripts/run_persistence_conditioned_backend_v1.py",
        ROOT / "scripts/run_persistence_conditioned_backend_v1_cell.sh",
        ROOT / "scripts/analyze_persistence_conditioned_backend_v1.py",
        ROOT / "uw_frontend/configs/experiments/low_texture_xfeat_seedchain_frontend.yaml",
        *[Path(case["klt_bag"]) for case in CASES.values()],
    }
    manifest_paths -= {PAPER / "artifacts.sha256.csv", PAPER / "artifacts.sha256"}
    for path in sorted(manifest_paths):
        if path.is_file():
            manifest.append({"sha256": sha256(path), "bytes": path.stat().st_size, "path": str(path)})
    write_csv(PAPER / "artifacts.sha256.csv", manifest)
    (PAPER / "artifacts.sha256").write_text(
        "".join(f"{row['sha256']}  {row['path']}\n" for row in manifest),
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
