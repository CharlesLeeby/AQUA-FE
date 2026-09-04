#!/usr/bin/env python3
"""Re-evaluate frozen July trajectories on G0 common support and aggregate by sequence."""

from __future__ import annotations

import argparse
import csv
import json
import math
import random
import re
import statistics
import subprocess
from collections import defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
INPUT = ROOT / "papers/frozen_frontend_eval_20260714/analysis-output/results_long.csv"
G0_ROOT = ROOT / "papers/e3_g0_common_support"
OUTPUT_CSV = ROOT / "papers/e3_dualmetric_summary.csv"
OUTPUT_REPORT = ROOT / "papers/e3_sequence_aggregate.md"
ARMS = ("full", "drop", "klt")
APE_DIVERGENCE_M = 3.0
RPE_DIVERGENCE_M = 1.0
BOOTSTRAP_SEED = 20260806
BOOTSTRAP_REPLICATES = 10_000
PRACTICAL_TIE_RELATIVE = 0.001

REFERENCE_RATE = {
    "aqualoc_archaeo": 1.0,
    "aqualoc_real": 4.0,
    "ntnu": 50.0,
    "cirs": 10.0,
    "afrl": 15.0,
}
ESTIMATE_RATE = {
    "aqualoc_archaeo": 10.0,
    "aqualoc_real": 10.0,
    "ntnu": 10.0,
    "cirs": 5.0,
    "afrl": 7.5,
}
REFERENCE_TOPIC = {
    "aqualoc_archaeo": "/aqualoc/colmap_gt",
    "aqualoc_real": "/aqualoc/colmap_gt",
    "cirs": "/cirs/odometry_gt",
    "afrl": "/afrl/colmap_gt",
}


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        rows = list(reader)
    if reader.fieldnames is None or any(None in row for row in rows):
        raise ValueError(f"invalid CSV: {path}")
    return rows


def write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    if not rows:
        raise ValueError("refusing to write an empty E3 summary")
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def read_kv(path: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    if not path.is_file():
        return result
    for raw in path.read_text(encoding="utf-8").splitlines():
        if "=" in raw:
            key, value = raw.split("=", 1)
            result[key.strip()] = value.strip()
    return result


def absolute_path(raw: str) -> Path:
    path = Path(raw)
    return path if path.is_absolute() else ROOT / path


def run_manifest(run_dir: Path) -> dict[str, str]:
    return read_kv(run_dir / "replay_manifest.txt")


def vins_config(run_dir: Path) -> Path:
    candidates = sorted(
        path
        for path in run_dir.glob("vins*.yaml")
        if path.is_file() and "cam0" not in path.name
    )
    if len(candidates) != 1:
        raise ValueError(f"expected one VINS config in {run_dir}, found {candidates}")
    return candidates[0]


def reference_args(dataset_family: str, full_run: Path) -> list[str]:
    manifest = run_manifest(full_run)
    if dataset_family == "ntnu":
        raw = manifest.get("gt_tum", "")
        if not raw:
            raise ValueError(f"missing gt_tum in {full_run}/replay_manifest.txt")
        path = absolute_path(raw)
        if not path.is_file():
            raise FileNotFoundError(path)
        return ["--reference-tum", str(path)]

    raw = manifest.get("raw_bag") or manifest.get("play_bag")
    if not raw:
        raise ValueError(f"missing raw_bag/play_bag in {full_run}/replay_manifest.txt")
    path = absolute_path(raw)
    if not path.is_file():
        raise FileNotFoundError(path)
    return [
        "--reference-bag",
        str(path),
        "--reference-topic",
        REFERENCE_TOPIC[dataset_family],
    ]


def grouped_input() -> dict[str, dict[str, dict[str, str]]]:
    groups: dict[str, dict[str, dict[str, str]]] = defaultdict(dict)
    for row in read_csv(INPUT):
        groups[row["case_id"]][row["arm"]] = row
    for case_id, arms in groups.items():
        if set(arms) != set(ARMS):
            raise ValueError(f"case {case_id} does not have full/drop/klt rows")
    return dict(groups)


def evaluate_case(case_id: str, arms: dict[str, dict[str, str]]) -> None:
    output = G0_ROOT / case_id
    summary = output / "common_support_summary.json"
    if summary.is_file():
        return
    if output.exists() and any(output.iterdir()):
        raise FileExistsError(f"nonempty incomplete G0 output: {output}")
    family = arms["full"]["dataset_family"]
    run_dirs = {arm: absolute_path(arms[arm]["run_dir"]) for arm in ARMS}
    command = [
        "python3",
        "scripts/evaluate_vins_common_support.py",
        *reference_args(family, run_dirs["full"]),
    ]
    for arm in ARMS:
        vio = run_dirs[arm] / "vins_output/vio.csv"
        if not vio.is_file():
            raise FileNotFoundError(vio)
        command.extend(["--arm", f"{arm}={vio}"])
        command.extend(["--arm-config", f"{arm}={vins_config(run_dirs[arm])}"])
    command.extend(
        [
            "--nominal-reference-rate-hz",
            str(REFERENCE_RATE[family]),
            "--nominal-estimate-rate-hz",
            str(ESTIMATE_RATE[family]),
            "--contrast-name",
            case_id,
            "--output-dir",
            str(output),
        ]
    )
    completed = subprocess.run(
        command,
        cwd=ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        check=False,
    )
    output.mkdir(parents=True, exist_ok=True)
    (output / "command.txt").write_text(" ".join(command) + "\n", encoding="utf-8")
    (output / "command.log").write_text(completed.stdout, encoding="utf-8")
    if completed.returncode != 0 or not summary.is_file():
        raise RuntimeError(f"G0 evaluation failed for {case_id}: {completed.stdout[-1000:]}")


def sequence_id(row: dict[str, str]) -> str:
    family = row["dataset_family"]
    window = row["window"]
    if family in {"aqualoc_archaeo", "aqualoc_real"}:
        return window.split("_", 1)[0]
    if family == "ntnu":
        match = re.match(r"(fjord_\d+|mclab\d+)_", window)
        if not match:
            raise ValueError(f"cannot parse NTNU sequence from {window}")
        return match.group(1)
    if family == "cirs":
        return "cala_viuda"
    if family == "afrl":
        return "cemetery_front_right"
    raise ValueError(f"unsupported family {family}")


def finite(value: object) -> bool:
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError):
        return False


def load_g0_rows(groups: dict[str, dict[str, dict[str, str]]]) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for case_id, input_arms in groups.items():
        summary_path = G0_ROOT / case_id / "common_support_summary.json"
        payload = json.loads(summary_path.read_text(encoding="utf-8"))
        support = payload["support"]
        for arm in ARMS:
            metrics = payload["arms"][arm]
            source = input_arms[arm]
            ape = metrics.get("ape_rmse_m")
            rpe = metrics.get("rpe_rmse_m")
            ape_valid = bool(support.get("ape_valid")) and finite(ape)
            rpe_valid = bool(support.get("rpe_valid")) and finite(rpe)
            threshold_divergence = (
                (ape_valid and float(ape) > APE_DIVERGENCE_M)
                or (rpe_valid and float(rpe) > RPE_DIVERGENCE_M)
            )
            no_valid_metric = not ape_valid and not rpe_valid
            divergent = no_valid_metric or threshold_divergence
            rows.append(
                {
                    "case_id": case_id,
                    "cohort": source["cohort"],
                    "official_fresh_20": int(int(source["fresh_export"]) == 1),
                    "independent_cluster": source["independent_cluster"],
                    "dataset_family": source["dataset_family"],
                    "sequence": sequence_id(source),
                    "window": source["window"],
                    "arm": arm,
                    "run_dir": source["run_dir"],
                    "ape_rmse_m": ape,
                    "rpe_rmse_m": rpe,
                    "ape_valid": int(ape_valid),
                    "rpe_valid": int(rpe_valid),
                    "common_grid_count": support.get("grid_count"),
                    "common_matched_count": support.get("matched_count"),
                    "common_span_s": support.get("common_span_s"),
                    "common_coverage": support.get("common_coverage"),
                    "common_rpe_pairs": support.get("rpe_pairs"),
                    "threshold_divergence": int(threshold_divergence),
                    "both_metrics_invalid": int(no_valid_metric),
                    "divergent_or_invalid": int(divergent),
                    "solver_risk": source["solver_risk"],
                    "learned_track_ids": source["learned_track_ids"],
                    "g0_summary": str(summary_path.relative_to(ROOT)),
                    "metric_contract": "G0_COMMON_SUPPORT_1S_TRANSLATION_RPE",
                }
            )
    return rows


def classify(full: dict[str, object], comparator: dict[str, object]) -> tuple[str, float | None]:
    full_div = bool(int(full["divergent_or_invalid"]))
    comparator_div = bool(int(comparator["divergent_or_invalid"]))
    if full_div and comparator_div:
        return "DOUBLE_DIVERGENCE_TIE_EXCLUDED", None
    if full_div:
        return "FULL_LOSS_SINGLE_DIVERGENCE", -1.0
    if comparator_div:
        return "FULL_WIN_SINGLE_DIVERGENCE", 1.0
    full_rpe_valid = bool(int(full["rpe_valid"]))
    comparator_rpe_valid = bool(int(comparator["rpe_valid"]))
    if not full_rpe_valid and not comparator_rpe_valid:
        return "RPE_INVALID_TIE_EXCLUDED", None
    if not full_rpe_valid:
        return "FULL_LOSS_RPE_INVALID", -1.0
    if not comparator_rpe_valid:
        return "FULL_WIN_COMPARATOR_RPE_INVALID", 1.0
    full_rpe = float(full["rpe_rmse_m"])
    comparator_rpe = float(comparator["rpe_rmse_m"])
    if comparator_rpe <= 0.0:
        return ("TIE", 0.0) if full_rpe == comparator_rpe else ("FULL_LOSS", -1.0)
    improvement = (comparator_rpe - full_rpe) / comparator_rpe
    if math.isclose(
        improvement, 0.0, rel_tol=0.0, abs_tol=PRACTICAL_TIE_RELATIVE
    ):
        return "TIE", 0.0
    return ("FULL_WIN", improvement) if improvement > 0.0 else ("FULL_LOSS", improvement)


def comparisons(rows: list[dict[str, object]], *, fresh_only: bool) -> list[dict[str, object]]:
    grouped: dict[str, dict[str, dict[str, object]]] = defaultdict(dict)
    for row in rows:
        if fresh_only and not bool(row["official_fresh_20"]):
            continue
        grouped[str(row["case_id"])][str(row["arm"])] = row
    output: list[dict[str, object]] = []
    for case_id, arms in grouped.items():
        for comparator_name in ("klt", "drop"):
            outcome, improvement = classify(arms["full"], arms[comparator_name])
            output.append(
                {
                    "case_id": case_id,
                    "dataset_family": arms["full"]["dataset_family"],
                    "sequence": arms["full"]["sequence"],
                    "window": arms["full"]["window"],
                    "comparator": comparator_name,
                    "outcome": outcome,
                    "rpe_relative_improvement": improvement,
                    "full_divergent": arms["full"]["divergent_or_invalid"],
                    "comparator_divergent": arms[comparator_name]["divergent_or_invalid"],
                    "full_ape": arms["full"]["ape_rmse_m"],
                    "comparator_ape": arms[comparator_name]["ape_rmse_m"],
                    "full_rpe": arms["full"]["rpe_rmse_m"],
                    "comparator_rpe": arms[comparator_name]["rpe_rmse_m"],
                }
            )
    return output


def sequence_aggregate(rows: list[dict[str, object]], comparator: str) -> list[dict[str, object]]:
    selected = [row for row in rows if row["comparator"] == comparator]
    grouped: dict[tuple[str, str], list[dict[str, object]]] = defaultdict(list)
    for row in selected:
        grouped[(str(row["dataset_family"]), str(row["sequence"]))].append(row)
    output: list[dict[str, object]] = []
    for (family, sequence), values in sorted(grouped.items()):
        usable = [row for row in values if row["rpe_relative_improvement"] is not None]
        improvements = [float(row["rpe_relative_improvement"]) for row in usable]
        median = statistics.median(improvements) if improvements else None
        if median is None:
            outcome = "EXCLUDED_ALL_DOUBLE_DIVERGENCE"
        elif median > 0.0:
            outcome = "WIN"
        elif median < 0.0:
            outcome = "LOSS"
        else:
            outcome = "TIE"
        output.append(
            {
                "dataset_family": family,
                "sequence": sequence,
                "window_count": len(values),
                "usable_window_count": len(usable),
                "window_wins": sum(str(row["outcome"]).startswith("FULL_WIN") for row in values),
                "window_losses": sum(str(row["outcome"]).startswith("FULL_LOSS") for row in values),
                "window_ties": sum(row["outcome"] == "TIE" for row in values),
                "invalid_or_double_divergence_excluded": sum(
                    str(row["outcome"]).endswith("_EXCLUDED") for row in values
                ),
                "median_rpe_relative_improvement": median,
                "sequence_outcome": outcome,
            }
        )
    return output


def exact_sign_test(wins: int, losses: int) -> float | None:
    n = wins + losses
    if n == 0:
        return None
    tail = sum(math.comb(n, value) for value in range(min(wins, losses) + 1)) / (2**n)
    return min(1.0, 2.0 * tail)


def bootstrap_ci(sequence_rows: list[dict[str, object]]) -> tuple[float | None, float | None]:
    values = [
        float(row["median_rpe_relative_improvement"])
        for row in sequence_rows
        if row["median_rpe_relative_improvement"] is not None
    ]
    if not values:
        return None, None
    rng = random.Random(BOOTSTRAP_SEED)
    medians = sorted(
        statistics.median(rng.choices(values, k=len(values)))
        for _ in range(BOOTSTRAP_REPLICATES)
    )
    low = medians[math.floor(0.025 * (len(medians) - 1))]
    high = medians[math.ceil(0.975 * (len(medians) - 1))]
    return low, high


def fmt(value: object, digits: int = 3) -> str:
    if value is None or value == "":
        return "NA"
    return f"{float(value):.{digits}f}"


def report_section(
    title: str, comparisons_rows: list[dict[str, object]], comparator: str
) -> list[str]:
    sequence_rows = sequence_aggregate(comparisons_rows, comparator)
    wins = sum(row["sequence_outcome"] == "WIN" for row in sequence_rows)
    losses = sum(row["sequence_outcome"] == "LOSS" for row in sequence_rows)
    ties = sum(row["sequence_outcome"] == "TIE" for row in sequence_rows)
    excluded = sum(
        row["sequence_outcome"] == "EXCLUDED_ALL_DOUBLE_DIVERGENCE"
        for row in sequence_rows
    )
    usable = wins + losses
    nonexcluded = wins + losses + ties
    win_rate = wins / nonexcluded if nonexcluded else None
    directional_win_rate = wins / usable if usable else None
    improvements = [
        float(row["median_rpe_relative_improvement"])
        for row in sequence_rows
        if row["median_rpe_relative_improvement"] is not None
    ]
    median = statistics.median(improvements) if improvements else None
    ci_low, ci_high = bootstrap_ci(sequence_rows)
    p_value = exact_sign_test(wins, losses)
    lines = [
        f"## {title}: full vs {comparator}",
        "",
        (
            f"Sequence units: {len(sequence_rows)}; wins/losses/ties/excluded = "
            f"{wins}/{losses}/{ties}/{excluded}. Win rate over non-excluded sequences is "
            f"{fmt(win_rate * 100 if win_rate is not None else None, 1)}%; directional "
            f"win rate excluding ties is "
            f"{fmt(directional_win_rate * 100 if directional_win_rate is not None else None, 1)}%. "
            f"Median RPE improvement = {fmt(median * 100 if median is not None else None, 1)}%, "
            f"fixed-seed 10,000x sequence bootstrap 95% CI "
            f"[{fmt(ci_low * 100 if ci_low is not None else None, 1)}, "
            f"{fmt(ci_high * 100 if ci_high is not None else None, 1)}]%; "
            f"two-sided exact sign-test p = {fmt(p_value, 4)}."
        ),
        "",
        "| Domain | Sequence | Windows | W/L/T/X | Median RPE improvement | Sequence result |",
        "| --- | --- | ---: | --- | ---: | --- |",
    ]
    for row in sequence_rows:
        lines.append(
            f"| {row['dataset_family']} | {row['sequence']} | {row['window_count']} | "
            f"{row['window_wins']}/{row['window_losses']}/{row['window_ties']}/"
            f"{row['invalid_or_double_divergence_excluded']} | "
            f"{fmt(float(row['median_rpe_relative_improvement']) * 100 if row['median_rpe_relative_improvement'] is not None else None, 1)}% | "
            f"{row['sequence_outcome']} |"
        )
    lines.append("")
    return lines


def write_report(rows: list[dict[str, object]]) -> None:
    fresh = comparisons(rows, fresh_only=True)
    all_rows = comparisons(rows, fresh_only=False)
    lines = [
        "# E3 G0 dual-metric and sequence aggregation",
        "",
        "This report recomputes the frozen July trajectories without replaying VINS. All three arms of a window are evaluated on one G0 common time grid. Primary outcome is 1 s translational RPE RMSE. APE is secondary and is reported only with `ape_valid`; RPE uses `rpe_valid`.",
        "",
        f"Divergence is preregistered as valid APE > {APE_DIVERGENCE_M:.0f} m or valid RPE > {RPE_DIVERGENCE_M:.0f} m; a case with neither metric valid is also excluded as invalid support. Double divergence is an excluded tie; single divergence determines win/loss. Absolute RPE changes below {PRACTICAL_TIE_RELATIVE * 100:.1f}% are practical ties. Bootstrap seed is `{BOOTSTRAP_SEED}` and the scientific unit is sequence, not window or replay.",
        "",
    ]
    lines.extend(report_section("Official fresh 20-window denominator", fresh, "klt"))
    lines.extend(report_section("Official fresh 20-window attribution", fresh, "drop"))
    lines.extend(report_section("All 21 clusters (AFRL appendix included)", all_rows, "klt"))
    lines.extend(
        [
            "## Window appendix: official fresh full vs KLT",
            "",
            "| Window | Domain | Sequence | Full APE/RPE | KLT APE/RPE | Outcome | RPE improvement |",
            "| --- | --- | --- | --- | --- | --- | ---: |",
        ]
    )
    for row in [item for item in fresh if item["comparator"] == "klt"]:
        lines.append(
            f"| {row['case_id']} | {row['dataset_family']} | {row['sequence']} | "
            f"{fmt(row['full_ape'])}/{fmt(row['full_rpe'])} | "
            f"{fmt(row['comparator_ape'])}/{fmt(row['comparator_rpe'])} | "
            f"{row['outcome']} | "
            f"{fmt(float(row['rpe_relative_improvement']) * 100 if row['rpe_relative_improvement'] is not None else None, 1)}% |"
        )
    lines.extend(
        [
            "",
            "## Evidence boundary",
            "",
            "These 20 fresh windows are historical frozen clusters, not the P06/P07 outcome-blind confirmatory matrix and not external-held-out data. The metrics may support development diagnostics only. Confirmatory claims remain blocked until the P07 frontend queue, D resolution, backend replay queue and three replays per arm are terminal.",
            "",
        ]
    )
    OUTPUT_REPORT.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--skip-evaluation", action="store_true")
    args = parser.parse_args()
    groups = grouped_input()
    G0_ROOT.mkdir(parents=True, exist_ok=True)
    if not args.skip_evaluation:
        for case_id, arms in groups.items():
            print(f"E3_G0_EVALUATE case={case_id}", flush=True)
            evaluate_case(case_id, arms)
    rows = load_g0_rows(groups)
    write_csv(OUTPUT_CSV, rows)
    write_report(rows)
    print(f"E3_G0_COMPLETE cases={len(groups)} arms={len(rows)}")
    print(f"summary={OUTPUT_CSV.relative_to(ROOT)}")
    print(f"report={OUTPUT_REPORT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
