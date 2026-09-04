#!/usr/bin/env python3
"""Reduce completed P07 G0 evaluations into strict analysis artifacts."""

from __future__ import annotations

import csv
import hashlib
import json
import math
import os
from pathlib import Path
import re
import statistics

import numpy as np


ROOT = Path("/home/ma/AQUA-FE_WS")
QUEUE = ROOT / "papers/ieee_sensors_journal_experiments/p07/backend_replay_queue_v1.csv"
RUNTIME = Path(
    os.environ.get(
        "P07_COMPLETION_RUNTIME",
        "/media/ma/Data/AQUA-FE_WS_storage_offload/p07_backend_completion_serial_v2",
    )
)
OUTPUT = RUNTIME / "analysis-output"
EXPECTED_EVALUATIONS = 20 * 3 * 3
SOLVER_PATTERNS = {
    "LINEAR_SOLVER_FAILURE": re.compile(
        r"Linear solver failure|Unable to perform dense Cholesky factorization"
    ),
    "ESTIMATOR_RESET_OR_RESTART": re.compile(
        r"failure detection!|system reboot!|restart the estimator!"
    ),
    "NUMERICAL_ABNORMALITY": re.compile(
        r"(?<![A-Za-z])(?:nan|[+-]?inf(?:inity)?)(?![A-Za-z])", re.I
    ),
}


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as stream:
        return list(csv.DictReader(stream))


def atomic_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(text, encoding="utf-8")
    temporary.replace(path)


def atomic_json(path: Path, payload: dict) -> None:
    atomic_text(path, json.dumps(payload, indent=2, sort_keys=True) + "\n")


def write_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    fields = list(rows[0]) if rows else []
    with temporary.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        if fields:
            writer.writeheader()
            writer.writerows(rows)
    temporary.replace(path)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def median(values: list[float]) -> float | None:
    return float(statistics.median(values)) if values else None


def mean(values: list[float]) -> float | None:
    return float(statistics.mean(values)) if values else None


def sample_std(values: list[float]) -> float | None:
    return float(statistics.stdev(values)) if len(values) >= 2 else None


def iqr(values: list[float]) -> float | None:
    if not values:
        return None
    return float(np.percentile(values, 75) - np.percentile(values, 25))


def receipt_status(payload: dict) -> str:
    status = str(payload.get("status", "PENDING"))
    output = payload.get("output", {})
    if status == "FAILED" and payload.get("return_code") == 1:
        if output.get("vio_exists") and int(output.get("vio_rows", 0)) == 0:
            return "ALGORITHM_FAILURE"
    return status


def load_backend_rows(queue_rows: list[dict[str, str]]) -> list[dict]:
    result = []
    for row in queue_rows:
        receipt_path = RUNTIME / "receipts" / f"queue_{int(row['queue_index']):03d}.json"
        if not receipt_path.is_file():
            raise RuntimeError(f"missing backend receipt: {receipt_path}")
        payload = json.loads(receipt_path.read_text(encoding="utf-8"))
        status = receipt_status(payload)
        if status not in {"COMPLETED", "ALGORITHM_FAILURE"}:
            raise RuntimeError(f"nonterminal backend receipt: {receipt_path}: {status}")
        output = payload.get("output", {})
        log_path = Path(payload["log"])
        log_text = log_path.read_text(encoding="utf-8", errors="replace") if log_path.is_file() else ""
        solver_codes = [code for code, pattern in SOLVER_PATTERNS.items() if pattern.search(log_text)]
        result.append(
            {
                "queue_index": int(row["queue_index"]),
                "run_id": row["run_id"],
                "window_id": row["window_id"],
                "dataset_family": row["dataset_family"],
                "sequence": row["sequence"],
                "texture_stratum": row["texture_stratum"],
                "selection_tier": row["selection_tier"],
                "arm": row["arm"],
                "replay_index": int(row["replay_index"]),
                "status": status,
                "vio_rows": int(output.get("vio_rows", 0)),
                "wall_seconds": float(payload["wall_seconds"]),
                "solver_risk": bool(solver_codes),
                "solver_risk_codes": ";".join(solver_codes),
                "receipt": str(receipt_path),
            }
        )
    return result


def load_evaluation_rows(queue_rows: list[dict[str, str]]) -> list[dict]:
    window_meta = {}
    for row in queue_rows:
        window_meta.setdefault(row["window_id"], row)
    receipts = sorted(RUNTIME.glob("g0/*/repeat_*/*/evaluation_receipt.json"))
    if len(receipts) != EXPECTED_EVALUATIONS:
        raise RuntimeError(
            f"evaluation matrix incomplete: {len(receipts)}/{EXPECTED_EVALUATIONS}"
        )
    result = []
    for path in receipts:
        payload = json.loads(path.read_text(encoding="utf-8"))
        window_id = payload["window_id"]
        meta = window_meta[window_id]
        status = payload["status"]
        row = {
            "window_id": window_id,
            "dataset_family": meta["dataset_family"],
            "sequence": meta["sequence"],
            "texture_stratum": meta["texture_stratum"],
            "selection_tier": meta["selection_tier"],
            "replay_index": int(payload["replay_index"]),
            "contrast": payload["contrast"],
            "proposed_arm": payload["proposed_arm"],
            "comparator_arm": payload["comparator_arm"],
            "status": status,
            "p_backend_status": "",
            "comparator_backend_status": "",
            "rpe_valid": False,
            "ape_valid": False,
            "grid_count": "",
            "common_count": "",
            "common_coverage": "",
            "rpe_pairs": "",
            "p_valid_grid_count": "",
            "comparator_valid_grid_count": "",
            "p_rpe_rmse_m": "",
            "comparator_rpe_rmse_m": "",
            "rpe_ratio": "",
            "p_ape_rmse_m": "",
            "comparator_ape_rmse_m": "",
            "evaluation_receipt": str(path),
        }
        if status == "ARM_HARD_FAILURE":
            row["p_backend_status"] = payload["backend_status"]["P"]
            row["comparator_backend_status"] = payload["backend_status"]["comparator"]
        elif status == "EVALUATED":
            summary_path = Path(payload["summary_path"])
            summary = json.loads(summary_path.read_text(encoding="utf-8"))
            support = summary["support"]
            p_metrics = summary["arms"]["P"]
            c_metrics = summary["arms"]["comparator"]
            row.update(
                {
                    "p_backend_status": "COMPLETED",
                    "comparator_backend_status": "COMPLETED",
                    "rpe_valid": bool(support["rpe_valid"]),
                    "ape_valid": bool(support["ape_valid"]),
                    "grid_count": int(support["grid_count"]),
                    "common_count": int(support["matched_count"]),
                    "common_coverage": float(support["common_coverage"]),
                    "rpe_pairs": int(support["rpe_pairs"]),
                    "p_valid_grid_count": int(p_metrics["valid_grid_count"]),
                    "comparator_valid_grid_count": int(c_metrics["valid_grid_count"]),
                }
            )
            if support["rpe_valid"]:
                p_rpe = float(p_metrics["rpe_rmse_m"])
                c_rpe = float(c_metrics["rpe_rmse_m"])
                row.update(
                    {
                        "p_rpe_rmse_m": p_rpe,
                        "comparator_rpe_rmse_m": c_rpe,
                        "rpe_ratio": p_rpe / c_rpe if c_rpe > 0 else math.inf,
                    }
                )
            if support["ape_valid"]:
                row.update(
                    {
                        "p_ape_rmse_m": float(p_metrics["ape_rmse_m"]),
                        "comparator_ape_rmse_m": float(c_metrics["ape_rmse_m"]),
                    }
                )
        else:
            raise RuntimeError(f"nonterminal evaluator receipt: {path}: {status}")
        result.append(row)
    result.sort(key=lambda item: (item["contrast"], item["window_id"], item["replay_index"]))
    return result


def reduce_windows(evaluation_rows: list[dict]) -> list[dict]:
    grouped: dict[tuple[str, str], list[dict]] = {}
    for row in evaluation_rows:
        grouped.setdefault((row["contrast"], row["window_id"]), []).append(row)
    result = []
    for (contrast, window_id), rows in sorted(grouped.items()):
        if len(rows) != 3:
            raise RuntimeError(f"window contrast lacks three replays: {contrast}/{window_id}")
        numeric = [row for row in rows if row["status"] == "EVALUATED" and row["rpe_valid"]]
        p_rpe = [float(row["p_rpe_rmse_m"]) for row in numeric]
        c_rpe = [float(row["comparator_rpe_rmse_m"]) for row in numeric]
        p_ape = [float(row["p_ape_rmse_m"]) for row in rows if row["status"] == "EVALUATED" and row["ape_valid"]]
        c_ape = [float(row["comparator_ape_rmse_m"]) for row in rows if row["status"] == "EVALUATED" and row["ape_valid"]]
        p_median = median(p_rpe)
        c_median = median(c_rpe)
        ratio = p_median / c_median if p_median is not None and c_median not in (None, 0) else None
        coverages = [float(row["common_coverage"]) for row in rows if row["status"] == "EVALUATED"]
        p_coverage = [
            float(row["p_valid_grid_count"]) / float(row["grid_count"])
            for row in rows if row["status"] == "EVALUATED"
        ]
        c_coverage = [
            float(row["comparator_valid_grid_count"]) / float(row["grid_count"])
            for row in rows if row["status"] == "EVALUATED"
        ]
        meta = rows[0]
        result.append(
            {
                "contrast": contrast,
                "window_id": window_id,
                "dataset_family": meta["dataset_family"],
                "sequence": meta["sequence"],
                "texture_stratum": meta["texture_stratum"],
                "selection_tier": meta["selection_tier"],
                "status": "NUMERIC" if len(numeric) >= 2 else "INSUFFICIENT_NUMERIC_REPLAYS",
                "numeric_replays": len(numeric),
                "evaluated_replays": sum(row["status"] == "EVALUATED" for row in rows),
                "p_hard_failure_any": any(row["p_backend_status"] != "COMPLETED" for row in rows),
                "comparator_hard_failure_any": any(row["comparator_backend_status"] != "COMPLETED" for row in rows),
                "p_rpe_median_m": p_median,
                "p_rpe_mean_m": mean(p_rpe),
                "p_rpe_std_m": sample_std(p_rpe),
                "p_rpe_iqr_m": iqr(p_rpe),
                "comparator_rpe_median_m": c_median,
                "comparator_rpe_mean_m": mean(c_rpe),
                "comparator_rpe_std_m": sample_std(c_rpe),
                "comparator_rpe_iqr_m": iqr(c_rpe),
                "rpe_ratio": ratio,
                "rpe_improvement_fraction": 1.0 - ratio if ratio is not None else None,
                "p_ape_median_m": median(p_ape),
                "comparator_ape_median_m": median(c_ape),
                "common_coverage_median": median(coverages),
                "p_coverage_median": median(p_coverage),
                "comparator_coverage_median": median(c_coverage),
                "coverage_loss_fraction": (
                    median(c_coverage) - median(p_coverage)
                    if p_coverage and c_coverage else None
                ),
            }
        )
    return result


def exact_two_sided_sign_p(effects: list[float]) -> tuple[int, int, float | None]:
    positive = sum(value > 0 for value in effects)
    negative = sum(value < 0 for value in effects)
    n = positive + negative
    if n == 0:
        return positive, negative, None
    tail = min(positive, negative)
    probability = 2.0 * sum(math.comb(n, k) for k in range(tail + 1)) / (2**n)
    return positive, negative, min(1.0, probability)


def sequence_effects(rows: list[dict]) -> dict[str, list[float]]:
    grouped: dict[str, list[float]] = {}
    for row in rows:
        if row["status"] == "NUMERIC":
            grouped.setdefault(row["sequence"], []).append(math.log(float(row["rpe_ratio"])))
    return grouped


def bootstrap_effect(rows: list[dict], *, seed: int = 20260730, draws: int = 10000) -> dict:
    grouped = sequence_effects(rows)
    sequences = sorted(grouped)
    if not sequences:
        return {"draws": draws, "seed": seed, "median_improvement": None, "ci95": [None, None]}
    rng = np.random.default_rng(seed)
    samples = np.empty(draws)
    for index in range(draws):
        chosen = rng.choice(sequences, size=len(sequences), replace=True)
        per_sequence = []
        for sequence in chosen:
            values = grouped[str(sequence)]
            resampled = rng.choice(values, size=len(values), replace=True)
            per_sequence.append(float(np.median(resampled)))
        samples[index] = float(np.median(per_sequence))
    improvements = 1.0 - np.exp(samples)
    point_effects = [float(np.median(grouped[key])) for key in sequences]
    return {
        "draws": draws,
        "seed": seed,
        "sequences": len(sequences),
        "median_log_ratio": float(np.median(point_effects)),
        "median_improvement": float(1.0 - math.exp(float(np.median(point_effects)))),
        "ci95": [float(np.percentile(improvements, 2.5)), float(np.percentile(improvements, 97.5))],
    }


def descriptive_contrast(rows: list[dict]) -> dict:
    numeric = [row for row in rows if row["status"] == "NUMERIC"]
    grouped = sequence_effects(rows)
    sequence_values = [float(np.median(values)) for values in grouped.values()]
    positive, negative, sign_p = exact_two_sided_sign_p(sequence_values)
    return {
        "windows_total": len(rows),
        "numeric_windows": len(numeric),
        "sequences": len(grouped),
        "bootstrap": bootstrap_effect(rows),
        "sign_test": {
            "positive_log_ratio_sequences_P_worse": positive,
            "negative_log_ratio_sequences_P_better": negative,
            "two_sided_p": sign_p,
        },
        "p_only_hard_failures": sum(
            row["p_hard_failure_any"] and not row["comparator_hard_failure_any"]
            for row in rows
        ),
    }


def reduce_sequences(window_rows: list[dict]) -> list[dict]:
    grouped: dict[tuple[str, str, str], list[dict]] = {}
    for row in window_rows:
        grouped.setdefault(
            (row["contrast"], row["texture_stratum"], row["sequence"]), []
        ).append(row)
    result = []
    for (contrast, texture, sequence), rows in sorted(grouped.items()):
        numeric = [row for row in rows if row["status"] == "NUMERIC"]
        ratios = [float(row["rpe_ratio"]) for row in numeric]
        p_rpe = [float(row["p_rpe_median_m"]) for row in numeric]
        c_rpe = [float(row["comparator_rpe_median_m"]) for row in numeric]
        ratio = float(np.median(ratios)) if ratios else None
        result.append(
            {
                "contrast": contrast,
                "texture_stratum": texture,
                "sequence": sequence,
                "windows_total": len(rows),
                "numeric_windows": len(numeric),
                "p_hard_failure_windows": sum(row["p_hard_failure_any"] for row in rows),
                "comparator_hard_failure_windows": sum(
                    row["comparator_hard_failure_any"] for row in rows
                ),
                "p_rpe_sequence_median_m": median(p_rpe),
                "comparator_rpe_sequence_median_m": median(c_rpe),
                "rpe_ratio_sequence_median": ratio,
                "rpe_improvement_fraction": 1.0 - ratio if ratio is not None else None,
            }
        )
    return result


def analyze(window_rows: list[dict], backend_rows: list[dict]) -> dict:
    p_b1 = [row for row in window_rows if row["contrast"] == "P_vs_B1"]
    low = [row for row in p_b1 if row["texture_stratum"] == "low"]
    normal = [row for row in p_b1 if row["texture_stratum"] == "normal"]
    low_boot = bootstrap_effect(low)
    low_sequence = sequence_effects(low)
    sequence_values = [float(np.median(values)) for values in low_sequence.values()]
    positive, negative, sign_p = exact_two_sided_sign_p(sequence_values)
    p_only_failures = sum(
        row["p_hard_failure_any"] and not row["comparator_hard_failure_any"] for row in low
    )
    h1_pass = (
        sum(row["status"] == "NUMERIC" for row in low) >= 8
        and len(low_sequence) >= 6
        and (low_boot["median_improvement"] or -math.inf) >= 0.05
        and ((low_boot["ci95"][0] or -math.inf) > 0 or (sign_p is not None and sign_p < 0.05))
        and p_only_failures == 0
    )

    normal_numeric = [row for row in normal if row["status"] == "NUMERIC"]
    normal_good = sum(float(row["rpe_ratio"]) <= 1.05 for row in normal_numeric)
    normal_sequences = sequence_effects(normal)
    normal_sequence_ratios = {
        sequence: math.exp(float(np.median(values)))
        for sequence, values in normal_sequences.items()
    }
    normal_sequence_good = sum(value <= 1.05 for value in normal_sequence_ratios.values())
    normal_losses_by_sequence: dict[str, list[float]] = {}
    for row in normal_numeric:
        if row["coverage_loss_fraction"] is not None:
            normal_losses_by_sequence.setdefault(row["sequence"], []).append(
                float(row["coverage_loss_fraction"])
            )
    median_sequence_coverage_loss = median(
        [float(np.median(values)) for values in normal_losses_by_sequence.values()]
    )
    backend_by_key = {
        (row["window_id"], row["arm"]): [] for row in backend_rows
    }
    for row in backend_rows:
        backend_by_key[(row["window_id"], row["arm"])].append(row)
    p_solver = sum(
        any(item["solver_risk"] for item in backend_by_key[(row["window_id"], "P_legacy_nativeq_xfeat_seedchain_v3")])
        for row in normal
    )
    b1_solver = sum(
        any(item["solver_risk"] for item in backend_by_key[(row["window_id"], "B1_klt_nativeq_v3")])
        for row in normal
    )
    h4_pass = (
        len(normal) == 10
        and len(normal_numeric) >= 9
        and normal_good >= 9
        and len(normal_sequence_ratios) > 0
        and normal_sequence_good / len(normal_sequence_ratios) >= 0.8
        and median_sequence_coverage_loss is not None
        and median_sequence_coverage_loss <= 0.02
        and not any(row["p_hard_failure_any"] and not row["comparator_hard_failure_any"] for row in normal)
        and p_solver <= b1_solver
    )

    terminal_counts: dict[str, dict[str, int]] = {}
    for row in backend_rows:
        terminal_counts.setdefault(row["arm"], {}).setdefault(row["status"], 0)
        terminal_counts[row["arm"]][row["status"]] += 1
    runtime = {}
    for arm in sorted({row["arm"] for row in backend_rows}):
        values = [row["wall_seconds"] for row in backend_rows if row["arm"] == arm]
        runtime[arm] = {
            "n": len(values), "mean_s": mean(values), "std_s": sample_std(values),
            "median_s": median(values), "iqr_s": iqr(values),
        }
    p_m = [row for row in window_rows if row["contrast"] == "P_vs_M"]
    p_b0 = [row for row in window_rows if row["contrast"] == "P_vs_B0"]
    return {
        "schema_version": "p07-functional-analysis-summary-v1",
        "primary_metric": "G0 common-support exact 1 s translation RPE RMSE; lower is better",
        "scientific_unit": "sequence; three replays are technical repeats",
        "backend_terminal_counts": terminal_counts,
        "runtime_backend_replay_wall": runtime,
        "descriptive_P_vs_original_VINS": {
            "all": descriptive_contrast(p_b0),
            "low": descriptive_contrast(
                [row for row in p_b0 if row["texture_stratum"] == "low"]
            ),
            "normal": descriptive_contrast(
                [row for row in p_b0 if row["texture_stratum"] == "normal"]
            ),
            "claim_role": "secondary descriptive contrast; not the preregistered H1",
        },
        "H1_low_P_vs_B1": {
            "decision": "PASS" if h1_pass else "FAIL_OR_INADEQUATE",
            "windows_total": len(low),
            "numeric_windows": sum(row["status"] == "NUMERIC" for row in low),
            "sequences": len(low_sequence),
            "bootstrap": low_boot,
            "sign_test": {
                "positive_log_ratio_sequences_P_worse": positive,
                "negative_log_ratio_sequences_P_better": negative,
                "two_sided_p": sign_p,
            },
            "p_only_hard_failures": p_only_failures,
        },
        "H4a_normal_no_harm_P_vs_B1": {
            "decision": "PASS" if h4_pass else "FAIL_OR_INADEQUATE",
            "windows_total": len(normal),
            "numeric_windows": len(normal_numeric),
            "windows_ratio_at_most_1p05": normal_good,
            "sequences": len(normal_sequence_ratios),
            "sequences_ratio_at_most_1p05": normal_sequence_good,
            "median_sequence_coverage_loss_fraction": median_sequence_coverage_loss,
            "p_solver_risk_windows": p_solver,
            "b1_solver_risk_windows": b1_solver,
        },
        "M_control": {
            "windows_total": len(p_m),
            "numeric_windows": sum(row["status"] == "NUMERIC" for row in p_m),
            "windows_with_M_hard_failure": sum(row["comparator_hard_failure_any"] for row in p_m),
            "decision": "COMPLETE_FAIR_COMPARISON_NO_SUPERIORITY_REQUIREMENT",
        },
        "claim_boundary": (
            "multi-sequence VINS-primary window evidence; not external-held-out, "
            "not a claim that learned features are uniformly superior"
        ),
    }


def make_figures(window_rows: list[dict], backend_rows: list[dict]) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    figures = OUTPUT / "figures"
    figures.mkdir(parents=True, exist_ok=True)
    rows = [row for row in window_rows if row["contrast"] == "P_vs_B1"]
    rows.sort(key=lambda row: (row["texture_stratum"] != "low", row["window_id"]))
    colors = {"low": "#D55E00", "normal": "#0072B2"}
    fig, axis = plt.subplots(figsize=(7.0, 3.5))
    for index, row in enumerate(rows):
        if row["status"] == "NUMERIC":
            axis.scatter(index, row["rpe_ratio"], color=colors[row["texture_stratum"]], s=28, zorder=3)
        else:
            axis.scatter(index, 1.45, marker="x", color="black", s=38, zorder=3)
    axis.axhline(1.0, color="black", linewidth=1.0)
    axis.axhline(1.05, color="#777777", linewidth=1.0, linestyle="--")
    axis.set_ylabel("RPE ratio (P / External-KLT)")
    axis.set_xlabel("Preregistered window (low texture first)")
    axis.set_xticks(range(len(rows)))
    axis.set_xticklabels([row["window_id"].split(":")[-2] + ":" + row["window_id"].split(":")[-1] for row in rows], rotation=55, ha="right", fontsize=7)
    axis.grid(axis="y", alpha=0.25)
    axis.set_ylim(bottom=0)
    fig.tight_layout()
    fig.savefig(figures / "figure-01-main-p-vs-klt-rpe-ratio.pdf")
    plt.close(fig)

    arms = sorted({row["arm"] for row in backend_rows})
    complete = [sum(row["arm"] == arm and row["status"] == "COMPLETED" for row in backend_rows) for arm in arms]
    failed = [sum(row["arm"] == arm and row["status"] == "ALGORITHM_FAILURE" for row in backend_rows) for arm in arms]
    labels = [arm.split("_")[0] for arm in arms]
    fig, axis = plt.subplots(figsize=(5.2, 3.2))
    x = np.arange(len(arms))
    axis.bar(x, complete, color="#56B4E9", label="trajectory produced")
    axis.bar(x, failed, bottom=complete, color="#E69F00", hatch="//", label="algorithm hard failure")
    axis.set_xticks(x)
    axis.set_xticklabels(labels)
    axis.set_ylabel("Backend replays (n=60 per arm)")
    axis.set_ylim(0, 64)
    axis.legend(frameon=False, fontsize=8)
    axis.grid(axis="y", alpha=0.25)
    fig.tight_layout()
    fig.savefig(figures / "figure-02-terminal-outcomes.pdf")
    plt.close(fig)

    fig, axis = plt.subplots(figsize=(5.2, 3.2))
    data = [[row["wall_seconds"] for row in backend_rows if row["arm"] == arm] for arm in arms]
    axis.boxplot(data, labels=labels, showfliers=False)
    for index, values in enumerate(data, 1):
        jitter = np.linspace(-0.08, 0.08, len(values))
        axis.scatter(np.full(len(values), index) + jitter, values, s=8, color="#0072B2", alpha=0.35)
    axis.set_ylabel("Replay wall time (s)")
    axis.grid(axis="y", alpha=0.25)
    fig.tight_layout()
    fig.savefig(figures / "figure-03-backend-runtime.pdf")
    plt.close(fig)


def reports(summary: dict, window_rows: list[dict], backend_rows: list[dict]) -> None:
    h1 = summary["H1_low_P_vs_B1"]
    h4 = summary["H4a_normal_no_harm_P_vs_B1"]
    m = summary["M_control"]
    terminal = summary["backend_terminal_counts"]
    b0 = summary["descriptive_P_vs_original_VINS"]
    report = f"""# P07 strict analysis report

## Analysis question

Does the proposed frozen frontend improve exact-1-s translation RPE over the strong External-KLT baseline on the 10 low-texture windows, while avoiding harm on the 10 normal windows? The scientific unit is the sequence; three backend replays measure technical stability and are reduced by their median.

## Key findings

- H1 low-texture P vs B1: **{h1['decision']}**; {h1['numeric_windows']}/{h1['windows_total']} numeric windows across {h1['sequences']} sequences; sequence-equal median improvement {100*(h1['bootstrap']['median_improvement'] or 0):.2f}% with hierarchical 95% CI [{100*(h1['bootstrap']['ci95'][0] or 0):.2f}%, {100*(h1['bootstrap']['ci95'][1] or 0):.2f}%]; exact two-sided sign-test p={h1['sign_test']['two_sided_p']}.
- H4a normal-texture no-harm: **{h4['decision']}**; {h4['windows_ratio_at_most_1p05']}/{h4['windows_total']} windows meet ratio <=1.05, with {h4['p_solver_risk_windows']} P and {h4['b1_solver_risk_windows']} B1 solver-risk windows.
- Controlled XFeat comparison: {m['numeric_windows']}/{m['windows_total']} numeric windows; {m['windows_with_M_hard_failure']} windows have at least one XFeat hard failure. This is a completeness/fairness result, not a requirement that P beat M.
- Descriptive P vs original VINS: all-window sequence-equal median RPE improvement {100*(b0['all']['bootstrap']['median_improvement'] or 0):.2f}% (95% CI [{100*(b0['all']['bootstrap']['ci95'][0] or 0):.2f}%, {100*(b0['all']['bootstrap']['ci95'][1] or 0):.2f}%]); low-texture {100*(b0['low']['bootstrap']['median_improvement'] or 0):.2f}%; normal-texture {100*(b0['normal']['bootstrap']['median_improvement'] or 0):.2f}%. This is secondary descriptive evidence, not the preregistered H1.
- Terminal replay counts: `{json.dumps(terminal, sort_keys=True)}`.

## Claim candidates

- Claim: P changes low-texture RPE relative to External-KLT under the frozen VINS-primary setup.
  - Source evidence: `window_summary.csv`, H1 bootstrap and sign test in `analysis_summary.json`.
  - Allowed wording: use the numeric direction and uncertainty reported above.
  - Forbidden stronger wording: external-held-out generalization or uniformly superior learned features.
  - Uncertainty: most sequences were development-exposed and references are image-derived/pseudo-GT.
  - Next check: external Tank supplement after access approval.
  - Decision: {'keep' if h1['decision']=='PASS' else 'revise'}.

- Claim: normal-texture operation is no-harm relative to External-KLT.
  - Source evidence: H4a frozen gates and every normal window in Figure 1.
  - Allowed wording: only if H4a is PASS.
  - Forbidden stronger wording: universal robustness.
  - Uncertainty: window-level common-support failures remain in the denominator.
  - Next check: inspect any ratio above 1.05 and solver-risk logs.
  - Decision: {'keep' if h4['decision']=='PASS' else 'discard'}.

## Main caveats

APE is secondary and used only where its G0 support flag is valid. Failed initializations are retained rather than imputed. Backend wall time includes ROS startup, playback, post-drain, and the legacy per-run evaluator, so it is not frontend-only latency and cannot establish real-time operation.
"""
    atomic_text(OUTPUT / "analysis-report.md", report)

    stats = f"""# Statistical appendix

- Primary metric: G0 common-support exact 1 s translation RPE RMSE (m), lower is better.
- Technical repeats: 3 per window-arm; numeric reducer: median when at least 2/3 are evaluable.
- Scientific unit: sequence, not replay and not window.
- Primary contrast: P vs B1 on 10 low-texture windows.
- Effect: log(P/B1 RPE); practical threshold: at least 5% sequence-equal median improvement.
- Uncertainty: 10,000-draw hierarchical percentile bootstrap, seed 20260730, resampling sequences then windows.
- Direction test: exact two-sided sign test on sequence median effects; positive={h1['sign_test']['positive_log_ratio_sequences_P_worse']}, negative={h1['sign_test']['negative_log_ratio_sequences_P_better']}, p={h1['sign_test']['two_sided_p']}.
- Bootstrap result: median improvement={h1['bootstrap']['median_improvement']}; 95% CI={h1['bootstrap']['ci95']}.
- Multiple comparisons: no multiplicity correction is applied because H1 is the sole preregistered primary effectiveness contrast; H4 is a thresholded safety gate and P-vs-M has no superiority claim.
- Distributional assumptions: no Gaussian assumption is made; medians, hierarchical bootstrap, and exact sign test are used because sequence n is small and windows are clustered within sequence.
- Failure policy: all 20 preregistered windows remain in denominators; any-of-three hard failure is retained; no failed metric is imputed.
- Descriptive repeat statistics (mean, sample SD, median, IQR) are in `window_summary.csv`; replay-level values are in `results_long.csv`.
"""
    atomic_text(OUTPUT / "stats-appendix.md", stats)

    catalog = """# Figure catalog

## figure-01-main-p-vs-klt-rpe-ratio.pdf

- Purpose: test the preregistered P-vs-External-KLT low-texture effect and normal-texture no-harm gate.
- Data: one three-replay median RPE ratio per window; low-texture windows appear first.
- Caption requirements: ratio below 1 favors P; dashed line is the 1.05 no-harm boundary; n=20 windows, scientific inference at sequence level; hard failures are not converted to numeric ratios.
- Observation: inspect direction, heterogeneity, and every threshold violation rather than only the aggregate median.
- Implication: determines whether H1/H4a wording is allowed.

## figure-02-terminal-outcomes.pdf

- Purpose: expose initialization/trajectory failures instead of hiding them behind successful-run averages.
- Data: 60 backend replays per arm, stacked by terminal outcome.
- Caption requirements: three repeats across 20 frozen windows; algorithm failures remain in the denominator.
- Observation: compare failure burden, especially for pairwise XFeat.
- Implication: constrains claims of learned-frontend robustness.

## figure-03-backend-runtime.pdf

- Purpose: show replay stability and gross runtime cost across arms.
- Data: all 60 wall times per arm; box shows quartiles and line shows median; points are individual replays.
- Caption requirements: wall time includes ROS startup, real-time playback, post-drain, and legacy evaluation; it is not frontend-only latency.
- Observation: inspect dispersion and preparation outliers.
- Implication: supports reproducibility/resource disclosure but not a real-time claim.
"""
    atomic_text(OUTPUT / "figure-catalog.md", catalog)


def write_closeout_assets(
    summary: dict,
    backend_rows: list[dict],
    evaluation_rows: list[dict],
    window_rows: list[dict],
) -> None:
    sequence_rows = reduce_sequences(window_rows)
    write_csv(OUTPUT / "sequence_summary.csv", sequence_rows)

    failure_rows = []
    for row in backend_rows:
        if row["status"] != "COMPLETED" or row["solver_risk"]:
            failure_rows.append(
                {
                    "level": "backend_replay",
                    "window_id": row["window_id"],
                    "sequence": row["sequence"],
                    "arm_or_contrast": row["arm"],
                    "replay_index": row["replay_index"],
                    "status": row["status"],
                    "solver_risk": row["solver_risk"],
                    "detail": row["solver_risk_codes"],
                }
            )
    for row in window_rows:
        if row["status"] != "NUMERIC":
            failure_rows.append(
                {
                    "level": "window_contrast",
                    "window_id": row["window_id"],
                    "sequence": row["sequence"],
                    "arm_or_contrast": row["contrast"],
                    "replay_index": "",
                    "status": row["status"],
                    "solver_risk": "",
                    "detail": (
                        "comparator_hard_failure"
                        if row["comparator_hard_failure_any"] else "insufficient_support"
                    ),
                }
            )
    write_csv(OUTPUT / "failure_table.csv", failure_rows)

    runtime_rows = []
    for arm, values in summary["runtime_backend_replay_wall"].items():
        runtime_rows.append({"arm": arm, **values})
    write_csv(OUTPUT / "runtime_table.csv", runtime_rows)

    h1 = summary["H1_low_P_vs_B1"]
    h4 = summary["H4a_normal_no_harm_P_vs_B1"]
    claim_rows = [
        {
            "claim_id": "H1_LOW_P_VS_EXTERNAL_KLT",
            "decision": h1["decision"],
            "allowed_wording": "P and External-KLT are statistically indistinguishable in the frozen low-texture matrix" if h1["decision"] != "PASS" else "P improves low-texture RPE over External-KLT under the frozen protocol",
            "boundary": summary["claim_boundary"],
            "source": "analysis_summary.json:H1_low_P_vs_B1",
        },
        {
            "claim_id": "H4A_NORMAL_NO_HARM",
            "decision": h4["decision"],
            "allowed_wording": "P meets the frozen normal-texture no-harm gate relative to External-KLT" if h4["decision"] == "PASS" else "No normal-texture no-harm claim",
            "boundary": summary["claim_boundary"],
            "source": "analysis_summary.json:H4a_normal_no_harm_P_vs_B1",
        },
        {
            "claim_id": "P_VS_ORIGINAL_VINS_DESCRIPTIVE",
            "decision": "DESCRIPTIVE_ONLY",
            "allowed_wording": "Report sequence-equal effect and uncertainty; do not present it as the preregistered primary hypothesis",
            "boundary": summary["claim_boundary"],
            "source": "analysis_summary.json:descriptive_P_vs_original_VINS",
        },
        {
            "claim_id": "PAIRWISE_XFEAT_CONTROL",
            "decision": summary["M_control"]["decision"],
            "allowed_wording": "Pairwise XFeat produced no VINS trajectory in all frozen windows under this interface",
            "boundary": "algorithm/interface-specific failure; not universal XFeat inferiority",
            "source": "analysis_summary.json:M_control",
        },
    ]
    write_csv(OUTPUT / "claim_matrix.csv", claim_rows)
    write_csv(OUTPUT / "contrast_results_long.csv", evaluation_rows)

    required = [
        "backend_terminal_long.csv", "results_long.csv", "contrast_results_long.csv",
        "window_summary.csv", "sequence_summary.csv", "failure_table.csv",
        "runtime_table.csv", "claim_matrix.csv", "analysis_summary.json",
        "analysis-report.md", "stats-appendix.md", "figure-catalog.md",
        "figures/figure-01-main-p-vs-klt-rpe-ratio.pdf",
        "figures/figure-02-terminal-outcomes.pdf",
        "figures/figure-03-backend-runtime.pdf",
    ]
    artifacts = []
    for relative in required:
        path = OUTPUT / relative
        if not path.is_file():
            raise RuntimeError(f"missing P10 artifact: {path}")
        artifacts.append(
            {"path": str(path), "bytes": path.stat().st_size, "sha256": sha256(path)}
        )
    atomic_json(
        OUTPUT / "g5_closeout.json",
        {
            "schema_version": "p10-g5-functional-closeout-v1",
            "status": "PASS",
            "source_rows": {
                "backend_replays": len(backend_rows),
                "evaluation_contrasts": len(evaluation_rows),
                "window_contrasts": len(window_rows),
                "sequence_contrasts": len(sequence_rows),
            },
            "artifacts": artifacts,
            "claim_boundary": summary["claim_boundary"],
        },
    )


def main() -> int:
    queue_rows = read_csv(QUEUE)
    if len(queue_rows) != 240:
        raise RuntimeError(f"backend queue incomplete: {len(queue_rows)}/240")
    backend_rows = load_backend_rows(queue_rows)
    evaluation_rows = load_evaluation_rows(queue_rows)
    window_rows = reduce_windows(evaluation_rows)
    summary = analyze(window_rows, backend_rows)
    OUTPUT.mkdir(parents=True, exist_ok=True)
    write_csv(OUTPUT / "backend_terminal_long.csv", backend_rows)
    write_csv(OUTPUT / "results_long.csv", evaluation_rows)
    write_csv(OUTPUT / "window_summary.csv", window_rows)
    atomic_json(OUTPUT / "analysis_summary.json", summary)
    make_figures(window_rows, backend_rows)
    reports(summary, window_rows, backend_rows)
    write_closeout_assets(summary, backend_rows, evaluation_rows, window_rows)
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
