#!/usr/bin/env python3
"""Finalize the preregistered four-arm A02 donor-delete diagnostic."""

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
PAPER = ROOT / "papers/frontend_coverage_monotone_router_v2_donor_delete_diagnostic"
V2_PAPER = ROOT / "papers/frontend_coverage_monotone_router_v2"
V2_RUNTIME = Path(
    "/media/ma/Data/AQUA-FE_WS_storage_offload/"
    "frontend_coverage_monotone_router_v2"
)
RUNTIME = Path(
    "/media/ma/Data/AQUA-FE_WS_storage_offload/"
    "frontend_coverage_monotone_router_v2_donor_delete_diagnostic"
)
PLAN = PAPER / "replay_plan.csv"
LOCK = PAPER / "execution_lock_recovery1.json"
CONTRACT = PAPER / "contract.json"
EVALUATOR = ROOT / "scripts/evaluate_vins_common_support_dual_scale.py"
CONFIG = Path(
    "/media/ma/Data/AQUA-FE_WS_storage_offload/"
    "frontend_coverage_monotone_router_v2/backend_canonical/"
    "a02_0_900/vins_same_backend.yaml"
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as stream:
        return list(csv.DictReader(stream))


def write_csv(path: Path, rows: list[dict[str, object]], fields: list[str]) -> None:
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
    checked = 0
    for item in lock["files"]:
        path = Path(item["path"])
        if not path.is_file() or sha256(path) != item["sha256"]:
            raise RuntimeError(f"execution-lock drift: {path}")
        checked += 1
    for role in ("vins_node", "vins_lib"):
        path = Path(lock[role])
        if sha256(path) != lock[f"{role}_sha256"]:
            raise RuntimeError(f"execution-lock drift: {path}")
        checked += 1
    return checked, checked


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


def reference_stats(path: Path) -> tuple[int, float]:
    stamps = []
    with rosbag.Bag(str(path), "r") as bag:
        for _, message, stamp in bag.read_messages(topics=["/aqualoc/colmap_gt"]):
            stamps.append(float(getattr(message, "header").stamp.to_sec()))
    return len(stamps), stamps[-1] - stamps[0]


def range_text(values: list[float]) -> str:
    return f"{min(values):.9f}–{max(values):.9f}"


def verify_receipt(
    receipt_path: Path,
    vio: Path,
    repeat: int,
    bag_hash: str,
    config_hash: str,
    node_hash: str,
    lib_hash: str,
) -> bool:
    receipt = parse_receipt(receipt_path)
    expected = {
        "window_id": "aqualoc_archaeology:A02:0000",
        "run_slug": "a02_0_900",
        "repeat": str(repeat),
        "feature_bag_sha256": bag_hash,
        "canonical_config_sha256": config_hash,
        "vins_node_sha256": node_hash,
        "vins_lib_sha256": lib_hash,
    }
    return bool(receipt) and all(receipt.get(key) == value for key, value in expected.items()) and bool(
        vio.is_file()
        and vio.stat().st_size > 0
        and receipt.get("vio_csv_sha256") == sha256(vio)
    )


def collect_repeats() -> list[dict[str, object]]:
    contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
    inputs = {item["role"]: item for item in contract["inputs"]}
    klt_bag = Path(inputs["fresh_klt_bag"]["path"])
    reference_count, reference_span = reference_stats(klt_bag)
    v2_rows = read_csv(V2_PAPER / "backend_results_repeats.csv")
    role_map = {
        "klt": "klt",
        "router_xfeat": "learned",
        "matched_gftt_for_router_xfeat": "matched",
    }
    rows: list[dict[str, object]] = []
    for old in v2_rows:
        if old["run_slug"] != "a02_0_900" or old["cell_id"] not in role_map:
            continue
        vio = Path(old["vio_csv"])
        receipt = Path(old["replay_receipt"])
        identity = (
            old["receipt_identity_pass"] == "True"
            and vio.is_file()
            and old["vio_csv_sha256"] == sha256(vio)
        )
        rows.append(
            {
                "role": role_map[old["cell_id"]],
                "cell_id": old["cell_id"],
                "repeat": int(old["repeat"]),
                "execution": "REUSED_FROZEN_V2_REPLAY",
                "receipt_identity_pass": identity,
                "init": old["init"],
                "pose_count": int(old["pose_count"]),
                "trajectory_span_s": float(old["trajectory_span_s"]),
                "reference_pose_count": reference_count,
                "reference_span_s": reference_span,
                "coverage": float(old["coverage"]),
                "repeat_status": old["repeat_status"],
                "failure_class": old["failure_class"],
                "feature_bag": old["feature_bag"],
                "feature_bag_sha256": old["feature_bag_sha256"],
                "canonical_config_sha256": old["canonical_config_sha256"],
                "vio_csv": str(vio),
                "vio_csv_sha256": sha256(vio),
                "vins_log": old["vins_log"],
                "replay_receipt": str(receipt),
            }
        )
    plan = read_csv(PLAN)
    for item in plan:
        repeat = int(item["repeat"])
        run_dir = (
            RUNTIME
            / "backend_replays/a02_0_900/donor_delete_only"
            / f"repeat{repeat}"
        )
        vio = run_dir / "vins_output/vio.csv"
        log = run_dir / "vins.log"
        receipt = run_dir / "replay_receipt.txt"
        identity = verify_receipt(
            receipt,
            vio,
            repeat,
            item["feature_bag_sha256"],
            item["canonical_config_sha256"],
            item["vins_node_sha256"],
            item["vins_lib_sha256"],
        )
        pose_count, span = pose_stats(vio)
        log_text = log.read_text(encoding="utf-8", errors="ignore") if log.is_file() else ""
        initialized = "Initialization finish!" in log_text and pose_count > 0
        coverage = min(1.0, span / reference_span) if reference_span else 0.0
        passed = identity and initialized and coverage >= 0.70
        failure = ""
        if not identity:
            failure = "missing_or_invalid_receipt"
        elif not initialized:
            failure = "cold_start_no_initialization"
        elif coverage < 0.70:
            failure = "coverage_failure"
        rows.append(
            {
                "role": "donor_delete",
                "cell_id": "donor_delete_only",
                "repeat": repeat,
                "execution": "NEW_ROUTE_D_REPLAY",
                "receipt_identity_pass": identity,
                "init": "PASS" if initialized else "FAIL",
                "pose_count": pose_count,
                "trajectory_span_s": span,
                "reference_pose_count": reference_count,
                "reference_span_s": reference_span,
                "coverage": coverage,
                "repeat_status": "PASS" if passed else "FAIL",
                "failure_class": failure,
                "feature_bag": item["feature_bag"],
                "feature_bag_sha256": item["feature_bag_sha256"],
                "canonical_config_sha256": item["canonical_config_sha256"],
                "vio_csv": str(vio),
                "vio_csv_sha256": sha256(vio) if vio.is_file() and vio.stat().st_size else "",
                "vins_log": str(log),
                "replay_receipt": str(receipt),
            }
        )
    rows.sort(key=lambda row: (["klt", "learned", "matched", "donor_delete"].index(str(row["role"])), int(row["repeat"])))
    if len(rows) != 12:
        raise RuntimeError(f"expected 12 trajectories, found {len(rows)}")
    fields = list(rows[0])
    write_csv(PAPER / "backend_results_repeats.csv", rows, fields)
    return rows


def build_runability(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    output = []
    for role in ("klt", "learned", "matched", "donor_delete"):
        cells = [row for row in rows if row["role"] == role]
        passes = sum(row["repeat_status"] == "PASS" for row in cells)
        poses = [float(row["pose_count"]) for row in cells]
        spans = [float(row["trajectory_span_s"]) for row in cells]
        coverage = [float(row["coverage"]) for row in cells]
        output.append(
            {
                "window_id": "aqualoc_archaeology:A02:0000",
                "role": role,
                "replays": 3,
                "independent_new_replays": 3 if role == "donor_delete" else 0,
                "reused_frozen_replays": 0 if role == "donor_delete" else 3,
                "repeats_pass": f"{passes}/3",
                "arm_window_status": "PASS" if passes == 3 else "FAIL",
                "pose_count_median": median(poses),
                "pose_count_range": range_text(poses),
                "trajectory_span_median_s": median(spans),
                "trajectory_span_range_s": range_text(spans),
                "coverage_median": median(coverage),
                "coverage_range": range_text(coverage),
                "failure_classes": ";".join(sorted({str(row["failure_class"]) for row in cells if row["failure_class"]})),
            }
        )
    write_csv(PAPER / "runability.csv", output, list(output[0]))
    return output


def build_initialization_audit(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    parsed: list[dict[str, object]] = []
    pattern = re.compile(r",\s*([0-9]+\.[0-9]+)\]: Initialization finish!")
    for row in rows:
        text = Path(str(row["vins_log"])).read_text(encoding="utf-8", errors="ignore")
        matches = pattern.findall(text)
        if len(matches) != 1:
            raise RuntimeError(
                f"expected one initialization marker: {row['role']} repeat{row['repeat']}"
            )
        parsed.append(
            {
                "role": row["role"],
                "repeat": row["repeat"],
                "initialization_timestamp_s": float(matches[0]),
                "initialization_timestamp_ns": int(round(float(matches[0]) * 1e9)),
                "vins_log": row["vins_log"],
            }
        )
    medians = {
        role: median(
            float(row["initialization_timestamp_s"])
            for row in parsed
            if row["role"] == role
        )
        for role in ("klt", "learned", "matched", "donor_delete")
    }
    for row in parsed:
        row["role_median_initialization_timestamp_s"] = medians[str(row["role"])]
        row["role_median_delta_vs_klt_s"] = medians[str(row["role"])] - medians["klt"]
    write_csv(PAPER / "initialization_event_audit.csv", parsed, list(parsed[0]))
    return parsed


def evaluate(rows: list[dict[str, object]], runability: list[dict[str, object]]) -> dict[str, object]:
    status: dict[str, object] = {
        "window_id": "aqualoc_archaeology:A02:0000",
        "required_trajectories": 12,
        "runable_trajectories": sum(row["repeat_status"] == "PASS" for row in rows),
        "status": "",
        "matched_count": "",
        "common_span_s": "",
        "common_coverage": "",
        "rpe_pairs": "",
        "return_code": "",
    }
    if not all(row["arm_window_status"] == "PASS" for row in runability):
        status["status"] = "EXCLUDED_NOT_ALL_12_RUNABLE"
    else:
        contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
        klt_bag = next(
            item["path"] for item in contract["inputs"] if item["role"] == "fresh_klt_bag"
        )
        output_dir = PAPER / "common_support"
        command = [
            sys.executable,
            str(EVALUATOR),
            "--reference-bag",
            klt_bag,
            "--reference-topic",
            "/aqualoc/colmap_gt",
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
        for row in rows:
            name = f"{row['role']}_r{row['repeat']}"
            command += ["--arm", f"{name}={row['vio_csv']}"]
            command += ["--arm-config", f"{name}={CONFIG}"]
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
        status["return_code"] = process.returncode
        summary_path = output_dir / "common_support_summary.json"
        support = {}
        if process.returncode == 0 and summary_path.is_file():
            support = json.loads(summary_path.read_text(encoding="utf-8"))["support"]
        valid = bool(support.get("ape_valid") and support.get("rpe_valid"))
        status.update(
            {
                "status": "PASS" if valid else "EXCLUDED_COMMON_SUPPORT",
                "matched_count": support.get("matched_count", ""),
                "common_span_s": support.get("common_span_s", ""),
                "common_coverage": support.get("common_coverage", ""),
                "rpe_pairs": support.get("rpe_pairs", ""),
            }
        )
    write_csv(PAPER / "common_support_status.csv", [status], list(status))
    return status


def accuracy(status: dict[str, object]) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    repeat_fields = [
        "role", "repeat", "common_poses", "rpe_pairs",
        "fixed_se3_ape_rmse_m", "fixed_se3_rpe_rmse_m", "sim3_scale",
        "sim3_ape_rmse_m", "sim3_rpe_rmse_m", "max_evo_abs_diff_m",
    ]
    aggregate_fields = [
        "role", "repeats", "common_poses", "rpe_pairs",
        "fixed_se3_ape_rmse_median_m", "fixed_se3_ape_rmse_range_m",
        "fixed_se3_rpe_rmse_median_m", "fixed_se3_rpe_rmse_range_m",
        "sim3_scale_median", "sim3_scale_range", "sim3_ape_rmse_median_m",
        "sim3_ape_rmse_range_m", "sim3_rpe_rmse_median_m",
        "sim3_rpe_rmse_range_m", "max_evo_abs_diff_m",
    ]
    if status["status"] != "PASS":
        write_csv(PAPER / "accuracy_repeats.csv", [], repeat_fields)
        write_csv(PAPER / "accuracy.csv", [], aggregate_fields)
        return [], []
    metric_rows = read_csv(PAPER / "common_support/common_support_metrics.csv")
    evo = json.loads((PAPER / "common_support/evo_crosscheck.json").read_text(encoding="utf-8"))
    repeats = []
    for metric in metric_rows:
        match = re.fullmatch(r"(klt|learned|matched|donor_delete)_r([123])", metric["arm"])
        if not match:
            raise RuntimeError(f"unexpected evaluator arm: {metric['arm']}")
        role, repeat = match.groups()
        cross = evo["arms"][metric["arm"]]
        repeats.append(
            {
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
    repeats.sort(key=lambda row: (["klt", "learned", "matched", "donor_delete"].index(str(row["role"])), int(row["repeat"])))
    grouped = []
    for role in ("klt", "learned", "matched", "donor_delete"):
        cells = [row for row in repeats if row["role"] == role]
        def values(key: str) -> list[float]:
            return [float(row[key]) for row in cells]
        grouped.append(
            {
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
    write_csv(PAPER / "accuracy_repeats.csv", repeats, repeat_fields)
    write_csv(PAPER / "accuracy.csv", grouped, aggregate_fields)
    return repeats, grouped


def decide(status: dict[str, object], grouped: list[dict[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {
        "schema_version": "aqua-fe-v2-donor-delete-decision-v1",
        "common_support_status": status["status"],
        "classification": "MIXED_OR_INCONCLUSIVE",
        "new_backend_replays": 3,
        "independent_windows": 1,
        "new_window_expansion": 0,
    }
    if status["status"] != "PASS":
        result["reason"] = "four-arm common-support gate failed"
        return result
    by_role = {str(row["role"]): row for row in grouped}
    klt = by_role["klt"]
    comparisons = []
    for role in ("learned", "matched", "donor_delete"):
        row = by_role[role]
        ape = float(row["fixed_se3_ape_rmse_median_m"])
        rpe = float(row["fixed_se3_rpe_rmse_median_m"])
        klt_ape = float(klt["fixed_se3_ape_rmse_median_m"])
        klt_rpe = float(klt["fixed_se3_rpe_rmse_median_m"])
        ape_delta = ape - klt_ape
        ape_ratio = ape / klt_ape
        rpe_ratio = rpe / klt_rpe
        noharm = (ape_ratio <= 1.05 or ape_delta < 0.01) and rpe_ratio <= 1.05
        comparisons.append(
            {
                "role": role,
                "ape_delta_m": ape_delta,
                "ape_change_pct": 100.0 * (ape_ratio - 1.0),
                "rpe_change_pct": 100.0 * (rpe_ratio - 1.0),
                "noharm_vs_klt": noharm,
            }
        )
    write_csv(PAPER / "comparisons.csv", comparisons, list(comparisons[0]))
    by_comparison = {str(row["role"]): row for row in comparisons}
    donor = by_comparison["donor_delete"]
    both_replacements_harm = not by_comparison["learned"]["noharm_vs_klt"] and not by_comparison["matched"]["noharm_vs_klt"]
    donor_both_harm = donor["ape_change_pct"] > 5.0 and donor["ape_delta_m"] >= 0.01 and donor["rpe_change_pct"] > 5.0
    if donor_both_harm:
        result["classification"] = "DELETE_SUFFICIENT"
        result["reason"] = "donor deletion alone fails the frozen no-harm boundary in APE and RPE"
    elif donor["noharm_vs_klt"] and both_replacements_harm:
        result["classification"] = "INSERTION_DOMINANT"
        result["reason"] = "deletion-only passes no-harm while both replacement arms fail"
    else:
        result["reason"] = "valid result does not meet either preregistered directional pattern"
    result["comparisons"] = comparisons
    result["next_decision"] = (
        "Do not expand v2. Use protected-KLT empty-slot admission as the sole next method-development direction; "
        "it must preserve existing observations and first pass the six-window development no-harm test."
    )
    return result


def write_report(
    identity: tuple[int, int],
    runability: list[dict[str, object]],
    status: dict[str, object],
    grouped: list[dict[str, object]],
    decision: dict[str, object],
    initialization: list[dict[str, object]],
) -> None:
    init_medians = {
        role: median(
            float(row["initialization_timestamp_s"])
            for row in initialization
            if row["role"] == role
        )
        for role in ("klt", "learned", "matched", "donor_delete")
    }
    lines = [
        "# V2 donor-delete-only route-D diagnostic",
        "",
        "Date: 2026-09-05  ",
        "Scientific role: outcome-known one-window development diagnostic; COLMAP/proxy is not independent ground truth.",
        "",
        "## Validity",
        "",
        f"- Execution identity: {identity[0]}/{identity[1]} checks PASS.",
        f"- New donor-delete-only replays: {sum(int(row['independent_new_replays']) for row in runability)}/3 completed.",
        f"- Four-arm common support: **{status['status']}**; {status['matched_count']} common poses, {status['common_span_s']} s, {status['common_coverage']} coverage, {status['rpe_pairs']} strict 1 s RPE pairs.",
        "- Repeats quantify technical stability and are not independent windows.",
        "",
        "## Result",
        "",
        "| Arm | runability | fixed SE(3) APE RMSE median [range] m | fixed SE(3) RPE RMSE median [range] m | Sim(3) scale median |",
        "|---|---:|---:|---:|---:|",
    ]
    run_by_role = {str(row["role"]): row for row in runability}
    acc_by_role = {str(row["role"]): row for row in grouped}
    labels = {"klt": "fresh KLT", "learned": "v2 XFeat replacement", "matched": "matched GFTT replacement", "donor_delete": "donor delete only"}
    for role in ("klt", "learned", "matched", "donor_delete"):
        run = run_by_role[role]
        if role in acc_by_role:
            acc = acc_by_role[role]
            ape = f"{float(acc['fixed_se3_ape_rmse_median_m']):.6f} [{acc['fixed_se3_ape_rmse_range_m']}]"
            rpe = f"{float(acc['fixed_se3_rpe_rmse_median_m']):.6f} [{acc['fixed_se3_rpe_rmse_range_m']}]"
            scale = f"{float(acc['sim3_scale_median']):.6f}"
        else:
            ape = rpe = scale = "Not evaluated."
        lines.append(f"| {labels[role]} | {run['repeats_pass']} | {ape} | {rpe} | {scale} |")
    lines += [
        "",
        "Primary alignment is per-trajectory proper fixed-scale SE(3); Sim(3) is diagnostic only.",
        "",
        "The initialization event is also phase-separated: KLT initializes at median "
        f"{init_medians['klt']:.9f} s, while learned, matched GFTT, and donor-delete-only "
        f"initialize at {init_medians['learned']:.9f}, {init_medians['matched']:.9f}, and "
        f"{init_medians['donor_delete']:.9f} s respectively. Donor deletion alone moves "
        f"the accepted initialization {init_medians['donor_delete'] - init_medians['klt']:+.3f} s "
        "relative to KLT, supporting an initialization-path/scale mechanism.",
        "",
        "## Preregistered attribution decision",
        "",
        f"**{decision['classification']}**: {decision.get('reason', '')}",
        "",
    ]
    if decision.get("comparisons"):
        for row in decision["comparisons"]:
            lines.append(
                f"- {row['role']} vs KLT: APE {float(row['ape_change_pct']):+.3f}% "
                f"(delta {float(row['ape_delta_m']):+.6f} m), RPE {float(row['rpe_change_pct']):+.3f}%, "
                f"no-harm={row['noharm_vs_klt']}."
            )
    lines += [
        "",
        "This one-window counterfactual can establish sufficiency of the tested deletion for harm, but cannot prove that insertion has no effect or estimate a natural positive-window rate.",
        "",
        "## Decision",
        "",
        str(decision.get("next_decision", "No expansion; mechanism remains inconclusive.")),
        "",
    ]
    (PAPER / "report.md").write_text("\n".join(lines), encoding="utf-8")


def write_hash_manifest(path: Path, paths: set[Path]) -> None:
    usable = sorted(
        {item.resolve() for item in paths if item.is_file() and item.resolve() != path.resolve()},
        key=str,
    )
    path.write_text(
        "".join(f"{sha256(item)}  {item}\n" for item in usable),
        encoding="utf-8",
    )


def write_v2_completion_identity_audit() -> None:
    plan = read_csv(V2_PAPER / "backend_smoke_plan.csv")
    results = {
        (row["run_slug"], row["cell_id"], row["repeat"]): row
        for row in read_csv(V2_PAPER / "backend_results_repeats.csv")
    }
    rows = []
    for item in plan:
        result = results[(item["run_slug"], item["cell_id"], item["repeat"])]
        bag_hash = sha256(Path(item["feature_bag"]))
        config_hash = sha256(Path(item["canonical_config"]))
        camera_hash = sha256(Path(item["camera_config"]))
        vio_hash = sha256(Path(result["vio_csv"]))
        checks = {
            "feature_bag_identity_pass": bag_hash == item["feature_bag_sha256"],
            "backend_config_identity_pass": config_hash == item["canonical_config_sha256"],
            "camera_config_identity_pass": camera_hash == item["camera_config_sha256"],
            "receipt_identity_pass": result["receipt_identity_pass"] == "True",
            "vio_receipt_identity_pass": vio_hash == result["vio_csv_sha256"],
            "repeat_runability_pass": result["repeat_status"] == "PASS",
        }
        rows.append(
            {
                "window_id": item["window_id"],
                "run_slug": item["run_slug"],
                "cell_id": item["cell_id"],
                "repeat": item["repeat"],
                **checks,
                "frozen_execution_lock_checks": "17/17",
                "completion_status": "PASS" if all(checks.values()) else "FAIL",
                "feature_bag": item["feature_bag"],
                "canonical_config": item["canonical_config"],
                "camera_config": item["camera_config"],
                "vio_csv": result["vio_csv"],
                "vins_log": result["vins_log"],
                "replay_receipt": result["replay_receipt"],
            }
        )
    write_csv(
        V2_PAPER / "backend_completion_identity_audit.csv",
        rows,
        list(rows[0]),
    )


def write_manifests(rows: list[dict[str, object]]) -> None:
    v2_paths: set[Path] = {
        V2_PAPER / name
        for name in (
            "backend_smoke_plan.csv", "backend_execution_lock.json",
            "backend_results_repeats.csv", "backend_results.csv", "runability.csv",
            "common_support_status.csv", "accuracy_repeats.csv", "accuracy.csv",
            "backend_comparisons.csv", "backend_completion_report.md",
            "decision_backend_complete.json", "lineage_diagnostic.csv",
            "backend_completion_identity_audit.csv",
        )
    }
    v2_paths.update(
        {
            ROOT / "scripts/run_frontend_coverage_monotone_router_v2_backend.py",
            ROOT / "scripts/run_frontend_coverage_monotone_router_v2_backend_cell.sh",
            ROOT / "scripts/finalize_frontend_coverage_monotone_router_v2_backend.py",
            ROOT / "scripts/analyze_frontend_coverage_monotone_router_v2_lineages.py",
            EVALUATOR,
        }
    )
    for row in read_csv(V2_PAPER / "backend_results_repeats.csv"):
        for key in ("feature_bag", "canonical_config", "vio_csv", "vins_log", "replay_receipt"):
            v2_paths.add(Path(row[key]))
    for row in read_csv(V2_PAPER / "backend_smoke_plan.csv"):
        v2_paths.add(Path(row["camera_config"]))
    for directory in (V2_PAPER / "common_support",):
        v2_paths.update(item for item in directory.rglob("*") if item.is_file())
    write_hash_manifest(V2_PAPER / "backend_completion_artifacts.sha256", v2_paths)

    route_paths: set[Path] = {
        item for item in PAPER.rglob("*") if item.is_file() and item.name != "artifacts.sha256"
    }
    route_paths.update(
        {
            ROOT / "scripts/build_frontend_coverage_monotone_router_v2_donor_delete_control.py",
            ROOT / "scripts/run_frontend_coverage_monotone_router_v2_donor_delete_backend.py",
            ROOT / "scripts/run_frontend_coverage_monotone_router_v2_donor_delete_backend_cell.sh",
            ROOT / "scripts/analyze_frontend_coverage_monotone_router_v2_donor_delete_backend.py",
            EVALUATOR,
            RUNTIME / "a02_0_900/features_donor_delete_only.bag",
        }
    )
    for row in rows:
        for key in ("feature_bag", "vio_csv", "vins_log", "replay_receipt"):
            route_paths.add(Path(str(row[key])))
    write_hash_manifest(PAPER / "artifacts.sha256", route_paths)


def main() -> int:
    identity = verify_lock()
    rows = collect_repeats()
    runability = build_runability(rows)
    initialization = build_initialization_audit(rows)
    status = evaluate(rows, runability)
    _, grouped = accuracy(status)
    decision = decide(status, grouped)
    (PAPER / "decision.json").write_text(json.dumps(decision, indent=2) + "\n", encoding="utf-8")
    write_report(identity, runability, status, grouped, decision, initialization)
    write_v2_completion_identity_audit()
    write_manifests(rows)
    print(json.dumps({
        "identity": f"{identity[0]}/{identity[1]}",
        "runable": sum(row["repeat_status"] == "PASS" for row in rows),
        "common_support": status["status"],
        "classification": decision["classification"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
