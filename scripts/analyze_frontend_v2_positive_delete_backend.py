#!/usr/bin/env python3
"""Finalize the preregistered A09/Bus positive donor-delete diagnostic."""

from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path
import re
from statistics import median
import subprocess
import sys

import rosbag


ROOT = Path("/home/ma/AQUA-FE_WS")
PAPER = ROOT / "papers/frontend_v2_positive_delete_diagnostic"
V2_PAPER = ROOT / "papers/frontend_coverage_monotone_router_v2"
RUNTIME = Path(
    "/media/ma/Data/AQUA-FE_WS_storage_offload/"
    "frontend_v2_positive_delete_diagnostic"
)
CONTRACT = PAPER / "contract.json"
LOCK = PAPER / "execution_lock.json"
PLAN = PAPER / "replay_plan.csv"
EVALUATOR = ROOT / "scripts/evaluate_vins_common_support_dual_scale.py"
ROLES = ("B", "BD", "BDL", "BDC")


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
        fields = list(rows[0])
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, lineterminator="\n")
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


def verify_lock() -> tuple[dict[str, object], int]:
    lock = json.loads(LOCK.read_text(encoding="utf-8"))
    checked = 0
    for item in lock["files"]:
        path = Path(item["path"])
        if not path.is_file() or sha256(path) != item["sha256"]:
            raise RuntimeError(f"execution-lock drift: {path}")
        checked += 1
    for role in ("vins_node", "vins_lib"):
        path = Path(lock[role])
        if not path.is_file() or sha256(path) != lock[f"{role}_sha256"]:
            raise RuntimeError(f"execution-lock drift: {path}")
        checked += 1
    return lock, checked


def pose_stats(path: Path) -> tuple[int, float]:
    stamps: list[float] = []
    if path.is_file():
        for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
            first = line.split(",", 1)[0].strip()
            if re.fullmatch(r"\d+", first):
                stamps.append(int(first) * 1e-9)
    return (len(stamps), max(0.0, stamps[-1] - stamps[0])) if stamps else (0, 0.0)


def reference_stats(path: Path, topic: str) -> tuple[int, float]:
    stamps: list[float] = []
    with rosbag.Bag(str(path), "r") as bag:
        for _, message, _ in bag.read_messages(topics=[topic]):
            stamps.append(float(message.header.stamp.to_sec()))
    if not stamps:
        raise RuntimeError(f"no proxy messages on {topic}: {path}")
    return len(stamps), stamps[-1] - stamps[0]


def range_text(values: list[float]) -> str:
    return f"{min(values):.9f}–{max(values):.9f}"


def collect_repeats(contract: dict[str, object], lock: dict[str, object]) -> list[dict[str, object]]:
    v2_rows = read_csv(V2_PAPER / "backend_results_repeats.csv")
    plan_rows = read_csv(PLAN)
    cell_roles = {"klt": "B", "router_xfeat": "BDL", "matched_gftt_for_router_xfeat": "BDC"}
    rows: list[dict[str, object]] = []
    for window in contract["windows"]:
        slug = str(window["run_slug"])
        ref_count, ref_span = reference_stats(Path(window["fresh_klt_bag"]), str(window["proxy_topic"]))
        for old in v2_rows:
            if old["run_slug"] != slug or old["cell_id"] not in cell_roles:
                continue
            vio = Path(old["vio_csv"])
            identity = (
                old["receipt_identity_pass"] == "True"
                and vio.is_file() and old["vio_csv_sha256"] == sha256(vio)
                and old["canonical_config_sha256"] == window["canonical_config_sha256"]
            )
            rows.append(
                {
                    "window_id": window["window_id"], "run_slug": slug,
                    "role": cell_roles[old["cell_id"]], "cell_id": old["cell_id"],
                    "repeat": int(old["repeat"]), "execution": "REUSED_FROZEN_V2_REPLAY",
                    "receipt_identity_pass": identity, "init": old["init"],
                    "pose_count": int(old["pose_count"]), "trajectory_span_s": float(old["trajectory_span_s"]),
                    "reference_pose_count": ref_count, "reference_span_s": ref_span,
                    "coverage": float(old["coverage"]), "repeat_status": old["repeat_status"],
                    "failure_class": old["failure_class"], "feature_bag": old["feature_bag"],
                    "feature_bag_sha256": old["feature_bag_sha256"],
                    "canonical_config": window["canonical_config"],
                    "canonical_config_sha256": old["canonical_config_sha256"],
                    "vio_csv": str(vio), "vio_csv_sha256": sha256(vio),
                    "vins_log": old["vins_log"], "replay_receipt": old["replay_receipt"],
                }
            )
        for item in plan_rows:
            if item["run_slug"] != slug:
                continue
            repeat = int(item["repeat"])
            run_dir = RUNTIME / "backend_replays" / slug / "donor_delete_only" / f"repeat{repeat}"
            vio = run_dir / "vins_output/vio.csv"
            log = run_dir / "vins.log"
            receipt_path = run_dir / "replay_receipt.txt"
            receipt = parse_receipt(receipt_path)
            identity = bool(receipt) and all(
                (
                    receipt.get("window_id") == window["window_id"],
                    receipt.get("run_slug") == slug,
                    receipt.get("repeat") == str(repeat),
                    receipt.get("feature_bag_sha256") == item["feature_bag_sha256"],
                    receipt.get("canonical_config_sha256") == item["canonical_config_sha256"],
                    receipt.get("vins_node_sha256") == lock["vins_node_sha256"],
                    receipt.get("vins_lib_sha256") == lock["vins_lib_sha256"],
                    vio.is_file(),
                    receipt.get("vio_csv_sha256") == (sha256(vio) if vio.is_file() else ""),
                )
            )
            poses, span = pose_stats(vio)
            log_text = log.read_text(encoding="utf-8", errors="ignore") if log.is_file() else ""
            initialized = "Initialization finish!" in log_text and poses > 0
            coverage = min(1.0, span / ref_span) if ref_span else 0.0
            passed = identity and initialized and coverage >= 0.70
            failure = "" if passed else (
                "missing_or_invalid_receipt" if not identity else
                "cold_start_no_initialization" if not initialized else "coverage_failure"
            )
            rows.append(
                {
                    "window_id": window["window_id"], "run_slug": slug,
                    "role": "BD", "cell_id": "donor_delete_only", "repeat": repeat,
                    "execution": "NEW_POSITIVE_DELETE_REPLAY", "receipt_identity_pass": identity,
                    "init": "PASS" if initialized else "FAIL", "pose_count": poses,
                    "trajectory_span_s": span, "reference_pose_count": ref_count,
                    "reference_span_s": ref_span, "coverage": coverage,
                    "repeat_status": "PASS" if passed else "FAIL", "failure_class": failure,
                    "feature_bag": item["feature_bag"], "feature_bag_sha256": item["feature_bag_sha256"],
                    "canonical_config": item["canonical_config"],
                    "canonical_config_sha256": item["canonical_config_sha256"],
                    "vio_csv": str(vio), "vio_csv_sha256": sha256(vio) if vio.is_file() else "",
                    "vins_log": str(log), "replay_receipt": str(receipt_path),
                }
            )
    rows.sort(key=lambda row: (str(row["run_slug"]), ROLES.index(str(row["role"])), int(row["repeat"])))
    if len(rows) != 24:
        raise RuntimeError(f"expected 24 trajectories, found {len(rows)}")
    write_csv(PAPER / "backend_results_repeats.csv", rows)
    return rows


def build_runability(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    output: list[dict[str, object]] = []
    for slug in sorted({str(row["run_slug"]) for row in rows}):
        for role in ROLES:
            cells = [row for row in rows if row["run_slug"] == slug and row["role"] == role]
            passes = sum(row["repeat_status"] == "PASS" for row in cells)
            output.append(
                {
                    "window_id": cells[0]["window_id"], "run_slug": slug, "role": role,
                    "replays": 3, "independent_new_replays": 3 if role == "BD" else 0,
                    "reused_frozen_replays": 0 if role == "BD" else 3,
                    "repeats_pass": f"{passes}/3", "arm_window_status": "PASS" if passes == 3 else "FAIL",
                    "pose_count_median": median(float(row["pose_count"]) for row in cells),
                    "pose_count_range": range_text([float(row["pose_count"]) for row in cells]),
                    "trajectory_span_median_s": median(float(row["trajectory_span_s"]) for row in cells),
                    "coverage_median": median(float(row["coverage"]) for row in cells),
                    "coverage_range": range_text([float(row["coverage"]) for row in cells]),
                    "failure_classes": ";".join(sorted({str(row["failure_class"]) for row in cells if row["failure_class"]})),
                }
            )
    write_csv(PAPER / "runability.csv", output)
    return output


def build_initialization_audit(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    pattern = re.compile(r",\s*([0-9]+\.[0-9]+)\]: Initialization finish!")
    output: list[dict[str, object]] = []
    for row in rows:
        matches = pattern.findall(Path(str(row["vins_log"])).read_text(encoding="utf-8", errors="ignore"))
        if len(matches) != 1:
            raise RuntimeError(f"expected one init marker: {row['run_slug']} {row['role']} r{row['repeat']}")
        output.append(
            {
                "window_id": row["window_id"], "run_slug": row["run_slug"],
                "role": row["role"], "repeat": row["repeat"],
                "initialization_timestamp_s": float(matches[0]),
                "initialization_timestamp_ns": int(round(float(matches[0]) * 1e9)),
                "vins_log": row["vins_log"],
            }
        )
    for slug in sorted({str(row["run_slug"]) for row in output}):
        medians = {
            role: median(float(row["initialization_timestamp_s"]) for row in output if row["run_slug"] == slug and row["role"] == role)
            for role in ROLES
        }
        for row in output:
            if row["run_slug"] == slug:
                row["role_median_initialization_timestamp_s"] = medians[str(row["role"])]
                row["role_median_delta_vs_B_s"] = medians[str(row["role"])] - medians["B"]
    write_csv(PAPER / "initialization_event_audit.csv", output)
    return output


def build_config_audit(rows: list[dict[str, object]], contract: dict[str, object]) -> list[dict[str, object]]:
    by_slug = {str(window["run_slug"]): window for window in contract["windows"]}
    output = []
    for row in rows:
        expected = by_slug[str(row["run_slug"])]["canonical_config_sha256"]
        actual = sha256(Path(str(row["canonical_config"])))
        output.append(
            {
                "window_id": row["window_id"], "run_slug": row["run_slug"], "role": row["role"],
                "repeat": row["repeat"], "expected_config_sha256": expected,
                "actual_config_sha256": actual, "identical": actual == expected,
            }
        )
    write_csv(PAPER / "backend_config_audit.csv", output)
    return output


def evaluate(
    rows: list[dict[str, object]], runability: list[dict[str, object]], contract: dict[str, object]
) -> list[dict[str, object]]:
    statuses: list[dict[str, object]] = []
    for window in contract["windows"]:
        slug = str(window["run_slug"])
        selected = [row for row in rows if row["run_slug"] == slug]
        status: dict[str, object] = {
            "window_id": window["window_id"], "run_slug": slug, "required_trajectories": 12,
            "runable_trajectories": sum(row["repeat_status"] == "PASS" for row in selected),
            "status": "", "matched_count": "", "common_span_s": "", "common_coverage": "",
            "rpe_pairs": "", "return_code": "",
        }
        run_rows = [row for row in runability if row["run_slug"] == slug]
        if not all(row["arm_window_status"] == "PASS" for row in run_rows):
            status["status"] = "EXCLUDED_NOT_ALL_12_RUNABLE"
        else:
            output_dir = PAPER / "common_support" / slug
            command = [
                sys.executable, str(EVALUATOR), "--reference-bag", str(window["fresh_klt_bag"]),
                "--reference-topic", str(window["proxy_topic"]), "--evaluation-rate-hz", "1",
                "--max-reference-gap-s", "2.5", "--max-estimate-gap-s", "0.25",
                "--output-dir", str(output_dir), "--run-evo",
            ]
            for row in selected:
                name = f"{row['role']}_r{row['repeat']}"
                command += ["--arm", f"{name}={row['vio_csv']}"]
                command += ["--arm-config", f"{name}={window['canonical_config']}"]
            process = subprocess.run(command, cwd=ROOT, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
            output_dir.mkdir(parents=True, exist_ok=True)
            (output_dir / "evaluator.log").write_text(process.stdout, encoding="utf-8")
            status["return_code"] = process.returncode
            support_path = output_dir / "common_support_summary.json"
            support = json.loads(support_path.read_text(encoding="utf-8"))["support"] if process.returncode == 0 and support_path.is_file() else {}
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
        statuses.append(status)
    write_csv(PAPER / "common_support_status.csv", statuses)
    return statuses


def build_accuracy(statuses: list[dict[str, object]]) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    repeats: list[dict[str, object]] = []
    aggregates: list[dict[str, object]] = []
    for status in statuses:
        if status["status"] != "PASS":
            continue
        slug = str(status["run_slug"])
        metrics = read_csv(PAPER / "common_support" / slug / "common_support_metrics.csv")
        evo = json.loads((PAPER / "common_support" / slug / "evo_crosscheck.json").read_text(encoding="utf-8"))
        for metric in metrics:
            match = re.fullmatch(r"(B|BD|BDL|BDC)_r([123])", metric["arm"])
            if not match:
                raise RuntimeError(f"unexpected evaluator arm: {metric['arm']}")
            role, repeat = match.groups()
            cross = evo["arms"][metric["arm"]]
            repeats.append(
                {
                    "window_id": status["window_id"], "run_slug": slug, "role": role, "repeat": int(repeat),
                    "common_poses": int(metric["matched_count"]), "rpe_pairs": int(metric["rpe_pairs"]),
                    "fixed_se3_ape_rmse_m": float(metric["fixed_se3_ape_rmse_m"]),
                    "fixed_se3_rpe_rmse_m": float(metric["fixed_se3_rpe_rmse_m"]),
                    "sim3_scale": float(metric["sim3_scale"]),
                    "sim3_ape_rmse_m": float(metric["sim3_ape_rmse_m"]),
                    "sim3_rpe_rmse_m": float(metric["sim3_rpe_rmse_m"]),
                    "max_evo_abs_diff_m": max(
                        float(cross[mode][key]) for mode in ("fixed_se3", "sim3")
                        for key in ("ape_abs_diff_m", "rpe_abs_diff_m")
                    ),
                }
            )
        for role in ROLES:
            cells = [row for row in repeats if row["run_slug"] == slug and row["role"] == role]
            values = lambda key: [float(row[key]) for row in cells]
            aggregates.append(
                {
                    "window_id": status["window_id"], "run_slug": slug, "role": role, "repeats": 3,
                    "common_poses": cells[0]["common_poses"], "rpe_pairs": cells[0]["rpe_pairs"],
                    "fixed_se3_ape_rmse_median_m": median(values("fixed_se3_ape_rmse_m")),
                    "fixed_se3_ape_rmse_range_m": range_text(values("fixed_se3_ape_rmse_m")),
                    "fixed_se3_rpe_rmse_median_m": median(values("fixed_se3_rpe_rmse_m")),
                    "fixed_se3_rpe_rmse_range_m": range_text(values("fixed_se3_rpe_rmse_m")),
                    "sim3_scale_median": median(values("sim3_scale")),
                    "sim3_scale_range": range_text(values("sim3_scale")),
                    "sim3_ape_rmse_median_m": median(values("sim3_ape_rmse_m")),
                    "sim3_rpe_rmse_median_m": median(values("sim3_rpe_rmse_m")),
                    "max_evo_abs_diff_m": max(values("max_evo_abs_diff_m")),
                }
            )
    repeat_fields = list(repeats[0]) if repeats else ["window_id", "run_slug", "role", "repeat"]
    aggregate_fields = list(aggregates[0]) if aggregates else ["window_id", "run_slug", "role", "repeats"]
    write_csv(PAPER / "accuracy_repeats.csv", repeats, repeat_fields)
    write_csv(PAPER / "accuracy.csv", aggregates, aggregate_fields)
    return repeats, aggregates


def decide(statuses: list[dict[str, object]], accuracy: list[dict[str, object]]) -> list[dict[str, object]]:
    output: list[dict[str, object]] = []
    for status in statuses:
        slug = str(status["run_slug"])
        result: dict[str, object] = {
            "window_id": status["window_id"], "run_slug": slug,
            "common_support_status": status["status"], "classification": "MIXED_OR_INCONCLUSIVE",
        }
        if status["status"] == "PASS":
            by_role = {str(row["role"]): row for row in accuracy if row["run_slug"] == slug}
            ape = {role: float(by_role[role]["fixed_se3_ape_rmse_median_m"]) for role in ROLES}
            rpe = {role: float(by_role[role]["fixed_se3_rpe_rmse_median_m"]) for role in ROLES}
            bd_win = ape["BD"] < ape["B"] and rpe["BD"] < rpe["B"]
            learned_win = ape["BDL"] < ape["B"] and rpe["BDL"] < rpe["B"]
            closer = (
                abs(ape["BD"] - ape["BDL"]) < abs(ape["BD"] - ape["B"])
                and abs(rpe["BD"] - rpe["BDL"]) < abs(rpe["BD"] - rpe["B"])
            )
            if bd_win and closer:
                result["classification"] = "DELETE_REPRODUCES_MAIN_WIN"
            elif bd_win:
                result["classification"] = "DELETE_DIRECTION_ONLY"
            elif learned_win:
                result["classification"] = "INSERTION_REQUIRED_FOR_WIN"
            result.update(
                {
                    "B_ape_m": ape["B"], "BD_ape_m": ape["BD"], "BDL_ape_m": ape["BDL"], "BDC_ape_m": ape["BDC"],
                    "B_rpe_m": rpe["B"], "BD_rpe_m": rpe["BD"], "BDL_rpe_m": rpe["BDL"], "BDC_rpe_m": rpe["BDC"],
                    "BD_vs_B_ape_change_pct": 100.0 * (ape["BD"] / ape["B"] - 1.0),
                    "BD_vs_B_rpe_change_pct": 100.0 * (rpe["BD"] / rpe["B"] - 1.0),
                    "BDL_minus_BD_ape_m": ape["BDL"] - ape["BD"],
                    "BDL_minus_BD_rpe_m": rpe["BDL"] - rpe["BD"],
                    "BDC_minus_BD_ape_m": ape["BDC"] - ape["BD"],
                    "BDC_minus_BD_rpe_m": rpe["BDC"] - rpe["BD"],
                    "BD_closer_to_BDL_than_B_both_metrics": closer,
                }
            )
        output.append(result)
    write_csv(PAPER / "comparisons.csv", output)
    decision = {
        "schema_version": "aqua-fe-v2-positive-delete-decision-v1",
        "new_backend_replays": 6,
        "independent_windows": 2,
        "window_decisions": output,
        "new_window_expansion_authorized": False,
        "next_step": "Combine with A02 deletion sufficiency and lineage budget audit; choose exactly one minimal development version.",
    }
    (PAPER / "decision.json").write_text(json.dumps(decision, indent=2) + "\n", encoding="utf-8")
    return output


def write_report(
    identity_checks: int, statuses: list[dict[str, object]], runability: list[dict[str, object]],
    accuracy: list[dict[str, object]], comparisons: list[dict[str, object]], initialization: list[dict[str, object]],
) -> None:
    lines = [
        "# V2 positive-window donor-delete-only diagnostic", "", "Date: 2026-09-05", "",
        "Scientific role: two outcome-known development-window mechanism diagnostics; COLMAP/proxy is not independent ground truth.", "",
        "## Validity", "", f"- Execution lock: {identity_checks}/{identity_checks} checks PASS.",
        f"- New donor-delete replays: {sum(int(row['independent_new_replays']) for row in runability)}/6.",
        f"- Window common support: {sum(row['status'] == 'PASS' for row in statuses)}/2 PASS.",
        "- Repeats measure technical stability, not independent scientific samples.", "", "## Absolute results", "",
        "Primary alignment is per-trajectory proper fixed-scale SE(3); Sim(3) scale is diagnostic only.", "",
        "| Window | Arm | runability | APE median [range] m | RPE median [range] m | Sim(3) scale | init delta vs B s |", "|---|---|---:|---:|---:|---:|---:|",
    ]
    labels = {"B": "fresh KLT (B)", "BD": "delete only (B-D)", "BDL": "XFeat replace (B-D+L)", "BDC": "matched GFTT (B-D+C)"}
    init_medians = {
        (slug, role): median(float(row["initialization_timestamp_s"]) for row in initialization if row["run_slug"] == slug and row["role"] == role)
        for slug in {str(row["run_slug"]) for row in initialization} for role in ROLES
    }
    run_by = {(str(row["run_slug"]), str(row["role"])): row for row in runability}
    acc_by = {(str(row["run_slug"]), str(row["role"])): row for row in accuracy}
    for slug in sorted({str(row["run_slug"]) for row in runability}):
        for role in ROLES:
            run = run_by[(slug, role)]
            acc = acc_by.get((slug, role))
            if acc:
                ape = f"{float(acc['fixed_se3_ape_rmse_median_m']):.6f} [{acc['fixed_se3_ape_rmse_range_m']}]"
                rpe = f"{float(acc['fixed_se3_rpe_rmse_median_m']):.6f} [{acc['fixed_se3_rpe_rmse_range_m']}]"
                scale = f"{float(acc['sim3_scale_median']):.6f}"
            else:
                ape = rpe = scale = "Not evaluated."
            delta = init_medians[(slug, role)] - init_medians[(slug, "B")]
            lines.append(f"| {slug} | {labels[role]} | {run['repeats_pass']} | {ape} | {rpe} | {scale} | {delta:+.6f} |")
    lines += ["", "## Preregistered attribution", ""]
    for row in comparisons:
        lines.append(
            f"- **{row['run_slug']}: {row['classification']}**. "
            + (f"B-D vs B APE/RPE {float(row['BD_vs_B_ape_change_pct']):+.3f}%/{float(row['BD_vs_B_rpe_change_pct']):+.3f}%; "
               f"conditional learned deltas {float(row['BDL_minus_BD_ape_m']):+.6f}/{float(row['BDL_minus_BD_rpe_m']):+.6f} m."
               if "BD_vs_B_ape_change_pct" in row else "Common support invalid; accuracy Not evaluated.")
        )
    lines += [
        "", "These classifications establish only the sufficiency or insufficiency of each registered deletion set under the tested four-arm intervention. They do not prove a learned candidate has zero effect, identify a single causal donor, or estimate prevalence.",
        "", "## Decision", "", "Do not expand v2. Combine these results with A02 DELETE_SUFFICIENT and the lineage budget audit, then implement at most one minimal development version.", "",
    ]
    (PAPER / "report.md").write_text("\n".join(lines), encoding="utf-8")


def write_manifest() -> None:
    paths = sorted(
        {path.resolve() for path in PAPER.rglob("*") if path.is_file() and path.name != "artifacts.sha256"},
        key=str,
    )
    (PAPER / "artifacts.sha256").write_text(
        "".join(f"{sha256(path)}  {path}\n" for path in paths), encoding="utf-8"
    )


def main() -> int:
    lock, identity_checks = verify_lock()
    contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
    rows = collect_repeats(contract, lock)
    runability = build_runability(rows)
    initialization = build_initialization_audit(rows)
    config_audit = build_config_audit(rows, contract)
    if not all(row["identical"] for row in config_audit):
        raise RuntimeError("backend config audit failed")
    statuses = evaluate(rows, runability, contract)
    _, accuracy = build_accuracy(statuses)
    comparisons = decide(statuses, accuracy)
    write_report(identity_checks, statuses, runability, accuracy, comparisons, initialization)
    write_manifest()
    print(json.dumps({"new_replays_pass": sum(row["role"] == "BD" and row["repeat_status"] == "PASS" for row in rows), "common_support_pass": sum(row["status"] == "PASS" for row in statuses), "decisions": {row["run_slug"]: row["classification"] for row in comparisons}}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
