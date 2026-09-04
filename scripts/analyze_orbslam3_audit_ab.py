#!/usr/bin/env python3
"""Analyze an ORB-SLAM3 instrumentation audit-on/off replay batch."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import re
import sys
from pathlib import Path
from typing import Iterable

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy import stats


ROLES = ("orb_only", "drop", "full")
METRICS = ("ape_rmse_m", "rpe_rmse_m")
METRIC_LABELS = {
    "ape_rmse_m": "APE RMSE (m)",
    "rpe_rmse_m": "RPE RMSE (m)",
}
STATE_LABELS = {
    "historical": "Historical",
    "audit_off": "Audit off",
    "audit_on": "Audit on",
}
OKABE_ITO = {
    "audit_off": "#0072B2",
    "audit_on": "#D55E00",
    "historical": "#000000",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--audit-on-csv", required=True)
    parser.add_argument("--audit-off-csv", required=True)
    parser.add_argument("--historical-csv", required=True)
    parser.add_argument("--batch-root", required=True)
    parser.add_argument("--schedule-csv", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument(
        "--practical-margin-pct",
        type=float,
        default=5.0,
        help="Symmetric practical no-harm margin for audit-on vs audit-off medians.",
    )
    parser.add_argument("--bootstrap-samples", type=int, default=20000)
    return parser.parse_args()


def require_columns(frame: pd.DataFrame, columns: Iterable[str], source: Path) -> None:
    missing = sorted(set(columns) - set(frame.columns))
    if missing:
        raise SystemExit(f"missing columns in {source}: {missing}")


def metric_report_stats(path: Path) -> dict[str, float]:
    text = path.read_text(encoding="utf-8", errors="ignore")
    result: dict[str, float] = {}
    for key in ("rmse", "median", "max"):
        match = re.search(rf"^\s*{key}\s+([0-9.eE+-]+)\s*$", text, re.MULTILINE)
        if not match:
            raise SystemExit(f"missing {key} in metric report: {path}")
        result[key] = float(match.group(1))
    return result


def validate_csv_row_against_run(row: pd.Series, expected_root: Path | None) -> None:
    role = str(row["role"])
    repeat = int(row["repeat"])
    run_dir = Path(str(row["run_dir"])).resolve()
    if expected_root is not None:
        expected = (expected_root / f"{role}_r{repeat}").resolve()
        if run_dir != expected:
            raise SystemExit(
                f"CSV run_dir mismatch for {role} r{repeat}: {run_dir} != {expected}"
            )
        manifest = parse_manifest(run_dir / "run_manifest.txt")
        if manifest.get("role") != role or int(manifest.get("repeat", -1)) != repeat:
            raise SystemExit(f"manifest role/repeat mismatch in {run_dir}")
        times_path = Path(manifest["times_file"])
        input_frames = sum(
            1 for line in times_path.read_text(encoding="ascii").splitlines() if line.strip()
        )
        if input_frames != int(row["input_frames"]):
            raise SystemExit(f"input frame count mismatch in {run_dir}")
    trajectories = [
        candidate
        for candidate in run_dir.glob("f_*.txt")
        if not candidate.name.endswith("_sec.txt")
    ]
    if len(trajectories) != 1:
        raise SystemExit(f"expected one raw trajectory in {run_dir}, found {len(trajectories)}")
    output_poses = sum(
        1
        for line in trajectories[0].read_text(encoding="ascii").splitlines()
        if len(line.split()) == 8
    )
    if output_poses != int(row["output_poses"]):
        raise SystemExit(f"output pose count mismatch in {run_dir}")
    if not math.isclose(
        float(row["coverage_ratio"]),
        output_poses / int(row["input_frames"]),
        rel_tol=0.0,
        abs_tol=1e-12,
    ):
        raise SystemExit(f"coverage mismatch in {run_dir}")
    log_text = (run_dir / "orbslam3_run.log").read_text(
        encoding="utf-8", errors="ignore"
    )
    seed_match = re.search(
        r"External seed summary: frames=(\d+) attempted=(\d+) accepted=(\d+)",
        log_text,
    )
    if not seed_match:
        raise SystemExit(f"missing external seed summary in {run_dir}")
    raw_seed_counts = tuple(int(value) for value in seed_match.groups())
    csv_seed_counts = tuple(
        int(row[field]) for field in ("seeded_frames", "attempted_seeds", "accepted_seeds")
    )
    if raw_seed_counts != csv_seed_counts:
        raise SystemExit(f"external seed log counters mismatch in {run_dir}")
    raw_resets = log_text.count("SYSTEM-> Reseting active map") + log_text.count(
        "SYSTEM-> Resetting active map"
    )
    if raw_resets != int(row["map_resets"]):
        raise SystemExit(f"map reset count mismatch in {run_dir}")
    if log_text.count("Relocalized!!") != int(row["relocalizations"]):
        raise SystemExit(f"relocalization count mismatch in {run_dir}")
    for prefix, report_name in (("ape", "ape_trans.txt"), ("rpe", "rpe_trans_1f.txt")):
        raw = metric_report_stats(run_dir / report_name)
        for statistic, value in raw.items():
            csv_value = float(row[f"{prefix}_{statistic}_m"])
            if not math.isclose(csv_value, value, rel_tol=0.0, abs_tol=1e-12):
                raise SystemExit(
                    f"{prefix} {statistic} mismatch in {run_dir}: {csv_value} != {value}"
                )


def read_runs(path: Path, state: str, expected_root: Path | None = None) -> pd.DataFrame:
    frame = pd.read_csv(path)
    require_columns(
        frame,
        (
            "role",
            "repeat",
            "input_frames",
            "map_resets",
            "relocalizations",
            "attempted_seeds",
            "accepted_seeds",
            "output_poses",
            "coverage_ratio",
            "ape_rmse_m",
            "ape_median_m",
            "ape_max_m",
            "rpe_rmse_m",
            "rpe_median_m",
            "rpe_max_m",
            "status",
            "run_dir",
        ),
        path,
    )
    if len(frame) != 24:
        raise SystemExit(f"expected 24 rows in {path}, found {len(frame)}")
    expected = {(role, repeat) for role in ROLES for repeat in range(1, 9)}
    actual = set(zip(frame["role"], frame["repeat"].astype(int)))
    if actual != expected or frame.duplicated(["role", "repeat"]).any():
        raise SystemExit(f"incomplete or duplicate role/repeat matrix in {path}")
    if set(frame["status"].astype(str)) != {"ok"}:
        raise SystemExit(f"non-ok run status in {path}")
    for metric in METRICS:
        if frame[metric].isna().any() or not np.isfinite(frame[metric]).all():
            raise SystemExit(f"invalid {metric} in {path}")
    frame = frame.copy()
    for _, row in frame.iterrows():
        validate_csv_row_against_run(row, expected_root)
    frame["state"] = state
    return frame.sort_values(["repeat", "role"]).reset_index(drop=True)


def validate_instrumentation(on: pd.DataFrame, off: pd.DataFrame) -> None:
    required_on = (
        "schema_version",
        "complete",
        "instrumentation_overflowed",
        "instrumentation_conservation_ok",
        "phase_conservation",
        "extractor_conservation",
        "accepted_conservation",
        "valid_tokens",
        "mappoint_pointer_consistency",
        "per_token_conservation",
        "mappoint_pointer_key_consistency",
        "atlas_snapshot_available",
    )
    require_columns(on, required_on, Path("audit-on CSV"))
    for field in required_on:
        expected = 0 if field == "instrumentation_overflowed" else 1
        if not (on[field] == expected).all():
            raise SystemExit(f"audit-on instrumentation check failed: {field}")
    if "schema_version" in off and off["schema_version"].notna().any():
        raise SystemExit("audit-off unexpectedly contains instrumentation values")


def percentile_ci(
    values: np.ndarray,
    statistic: str,
    confidence: float,
    samples: int,
    seed: int,
) -> tuple[float, float]:
    values = np.asarray(values, dtype=float)
    rng = np.random.default_rng(seed)
    draws = values[rng.integers(0, len(values), size=(samples, len(values)))]
    if statistic == "median":
        boot = np.median(draws, axis=1)
    elif statistic == "mean":
        boot = np.mean(draws, axis=1)
    else:
        raise ValueError(statistic)
    tail = (1.0 - confidence) / 2.0
    return tuple(float(value) for value in np.quantile(boot, [tail, 1.0 - tail]))


def holm_adjust(p_values: list[float]) -> list[float]:
    values = np.asarray(p_values, dtype=float)
    order = np.argsort(values)
    adjusted_sorted = np.empty(len(values), dtype=float)
    running = 0.0
    for rank, index in enumerate(order):
        candidate = (len(values) - rank) * values[index]
        running = max(running, candidate)
        adjusted_sorted[rank] = min(1.0, running)
    adjusted = np.empty(len(values), dtype=float)
    for rank, index in enumerate(order):
        adjusted[index] = adjusted_sorted[rank]
    return adjusted.tolist()


def rank_biserial(differences: np.ndarray) -> float:
    nonzero = differences[differences != 0]
    if len(nonzero) == 0:
        return 0.0
    ranks = stats.rankdata(np.abs(nonzero))
    positive = float(ranks[nonzero > 0].sum())
    negative = float(ranks[nonzero < 0].sum())
    return (positive - negative) / float(ranks.sum())


def wilcoxon_signed_rank(differences: np.ndarray) -> dict[str, object]:
    nonzero = np.asarray(differences, dtype=float)
    nonzero = nonzero[nonzero != 0]
    if len(nonzero) == 0:
        return {
            "statistic": 0.0,
            "p_value": 1.0,
            "effective_n": 0,
            "method": "all paired differences are zero",
        }
    if len(nonzero) <= 20:
        ranks = stats.rankdata(np.abs(nonzero), method="average")
        observed = float(ranks[nonzero > 0].sum())
        center = float(ranks.sum()) / 2.0
        observed_distance = abs(observed - center)
        extreme = 0
        total = 1 << len(nonzero)
        for mask in range(total):
            positive_sum = sum(
                rank for index, rank in enumerate(ranks) if mask & (1 << index)
            )
            if abs(float(positive_sum) - center) + 1e-12 >= observed_distance:
                extreme += 1
        statistic = min(observed, float(ranks.sum()) - observed)
        p_value = extreme / total
        method = "Wilcoxon signed-rank, exact sign enumeration with average tied ranks"
    else:
        test = stats.wilcoxon(
            nonzero,
            alternative="two-sided",
            zero_method="wilcox",
            method="approx",
        )
        statistic = float(test.statistic)
        p_value = float(test.pvalue)
        method = "Wilcoxon signed-rank, two-sided, normal approximation"
    return {
        "statistic": statistic,
        "p_value": p_value,
        "effective_n": len(nonzero),
        "method": method,
    }


def cliff_delta(first: np.ndarray, second: np.ndarray) -> float:
    comparisons = np.sign(first[:, None] - second[None, :])
    return float(comparisons.mean())


def descriptive_stats(
    frames: dict[str, pd.DataFrame], bootstrap_samples: int
) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    seed = 2026072400
    for state, frame in frames.items():
        for role in ROLES:
            selected = frame[frame["role"] == role]
            for metric in (*METRICS, "coverage_ratio"):
                values = selected[metric].to_numpy(dtype=float)
                q1, median, q3 = np.quantile(values, [0.25, 0.5, 0.75])
                mean = float(np.mean(values))
                std = float(np.std(values, ddof=1))
                sem = std / math.sqrt(len(values))
                radius = float(stats.t.ppf(0.975, len(values) - 1) * sem)
                median_low, median_high = percentile_ci(
                    values, "median", 0.95, bootstrap_samples, seed
                )
                seed += 1
                rows.append(
                    {
                        "state": state,
                        "role": role,
                        "metric": metric,
                        "n": len(values),
                        "mean": mean,
                        "std": std,
                        "mean_95ci_low": mean - radius,
                        "mean_95ci_high": mean + radius,
                        "median": float(median),
                        "q1": float(q1),
                        "q3": float(q3),
                        "iqr": float(q3 - q1),
                        "median_bootstrap_95ci_low": median_low,
                        "median_bootstrap_95ci_high": median_high,
                        "min": float(np.min(values)),
                        "max": float(np.max(values)),
                    }
                )
    return pd.DataFrame(rows)


def paired_on_off(
    on: pd.DataFrame,
    off: pd.DataFrame,
    historical: pd.DataFrame,
    margin_pct: float,
    bootstrap_samples: int,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    indexed_on = on.set_index(["role", "repeat"]).sort_index()
    indexed_off = off.set_index(["role", "repeat"]).sort_index()
    detail_rows: list[dict[str, object]] = []
    test_rows: list[dict[str, object]] = []
    seed = 2026072500
    for role in ROLES:
        history_role = historical[historical["role"] == role]
        for metric in METRICS:
            on_values = indexed_on.loc[role, metric].sort_index().to_numpy(dtype=float)
            off_values = indexed_off.loc[role, metric].sort_index().to_numpy(dtype=float)
            differences = on_values - off_values
            relative = 100.0 * differences / off_values
            history_values = history_role[metric].to_numpy(dtype=float)
            history_q1, history_q3 = np.quantile(history_values, [0.25, 0.75])
            history_iqr = float(history_q3 - history_q1)
            for repeat, on_value, off_value, difference, relative_value in zip(
                range(1, 9), on_values, off_values, differences, relative
            ):
                detail_rows.append(
                    {
                        "role": role,
                        "repeat": repeat,
                        "metric": metric,
                        "audit_off": off_value,
                        "audit_on": on_value,
                        "on_minus_off": difference,
                        "on_minus_off_pct": relative_value,
                        "audit_on_worse": int(difference > 0),
                        "within_5pct_pair": int(abs(relative_value) <= margin_pct),
                        "historical_median": float(np.median(history_values)),
                        "historical_iqr": history_iqr,
                        "abs_delta_over_historical_iqr": (
                            abs(difference) / history_iqr if history_iqr > 0 else math.inf
                        ),
                    }
                )
            shapiro = stats.shapiro(differences)
            wilcoxon = wilcoxon_signed_rank(differences)
            nonzero = differences[differences != 0]
            positive = int((nonzero > 0).sum())
            sign_test_p = (
                float(stats.binomtest(positive, len(nonzero), 0.5, alternative="two-sided").pvalue)
                if len(nonzero)
                else 1.0
            )
            relative_ci_low, relative_ci_high = percentile_ci(
                relative, "median", 0.90, bootstrap_samples, seed
            )
            seed += 1
            off_median = float(np.median(off_values))
            on_median = float(np.median(on_values))
            median_shift = on_median - off_median
            median_shift_pct = 100.0 * median_shift / off_median
            test_rows.append(
                {
                    "comparison_family": "audit_on_vs_audit_off_paired",
                    "role": role,
                    "metric": metric,
                    "n": len(differences),
                    "audit_off_median": off_median,
                    "audit_on_median": on_median,
                    "difference_of_medians": median_shift,
                    "difference_of_medians_pct": median_shift_pct,
                    "paired_difference_median": float(np.median(differences)),
                    "paired_relative_difference_median_pct": float(np.median(relative)),
                    "paired_relative_median_90ci_low_pct": relative_ci_low,
                    "paired_relative_median_90ci_high_pct": relative_ci_high,
                    "shapiro_w": float(shapiro.statistic),
                    "shapiro_p": float(shapiro.pvalue),
                    "primary_test": wilcoxon["method"],
                    "effective_n_nonzero": wilcoxon["effective_n"],
                    "test_statistic": wilcoxon["statistic"],
                    "p_value": wilcoxon["p_value"],
                    "rank_biserial_on_minus_off": rank_biserial(differences),
                    "sign_test_p": sign_test_p,
                    "historical_median": float(np.median(history_values)),
                    "historical_iqr": history_iqr,
                    "median_shift_over_historical_iqr": (
                        abs(median_shift) / history_iqr if history_iqr > 0 else math.inf
                    ),
                    "paired_relative_median_within_5pct": int(
                        abs(float(np.median(relative))) <= margin_pct
                    ),
                    "median_shift_within_historical_iqr": int(
                        abs(median_shift) <= history_iqr
                    ),
                    "bootstrap_90ci_within_5pct": int(
                        relative_ci_low >= -margin_pct
                        and relative_ci_high <= margin_pct
                    ),
                }
            )
    adjusted = holm_adjust([float(row["p_value"]) for row in test_rows])
    for row, value in zip(test_rows, adjusted):
        row["holm_p_across_6_metrics"] = value
        row["strict_distribution_preservation_screen"] = int(
            bool(row["median_shift_within_historical_iqr"])
            and bool(row["bootstrap_90ci_within_5pct"])
        )
    return pd.DataFrame(detail_rows), pd.DataFrame(test_rows)


def off_vs_historical(
    off: pd.DataFrame, historical: pd.DataFrame
) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for role in ROLES:
        for metric in METRICS:
            current = off.loc[off["role"] == role, metric].to_numpy(dtype=float)
            old = historical.loc[historical["role"] == role, metric].to_numpy(dtype=float)
            test = stats.mannwhitneyu(current, old, alternative="two-sided", method="auto")
            q1, q3 = np.quantile(old, [0.25, 0.75])
            old_iqr = float(q3 - q1)
            current_median = float(np.median(current))
            old_median = float(np.median(old))
            shift = current_median - old_median
            rows.append(
                {
                    "comparison_family": "audit_off_vs_historical_independent_runs",
                    "role": role,
                    "metric": metric,
                    "n_current": len(current),
                    "n_historical": len(old),
                    "historical_median": old_median,
                    "audit_off_median": current_median,
                    "difference_of_medians": shift,
                    "difference_of_medians_pct": 100.0 * shift / old_median,
                    "historical_q1": float(q1),
                    "historical_q3": float(q3),
                    "historical_iqr": old_iqr,
                    "median_shift_over_historical_iqr": (
                        abs(shift) / old_iqr if old_iqr > 0 else math.inf
                    ),
                    "audit_off_median_inside_historical_iqr": int(
                        q1 <= current_median <= q3
                    ),
                    "primary_test": "Mann-Whitney U, two-sided",
                    "test_statistic": float(test.statistic),
                    "p_value": float(test.pvalue),
                    "cliff_delta_current_minus_historical": cliff_delta(current, old),
                }
            )
    adjusted = holm_adjust([float(row["p_value"]) for row in rows])
    for row, value in zip(rows, adjusted):
        row["holm_p_across_6_metrics"] = value
    return pd.DataFrame(rows)


def win_counts(frames: dict[str, pd.DataFrame]) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for state, frame in frames.items():
        indexed = frame.set_index(["role", "repeat"])
        for baseline in ("orb_only", "drop"):
            coverage_comparable = ape_wins = rpe_wins = double_wins = 0
            for repeat in range(1, 9):
                full = indexed.loc[("full", repeat)]
                reference = indexed.loc[(baseline, repeat)]
                comparable = math.isclose(
                    float(full["coverage_ratio"]),
                    float(reference["coverage_ratio"]),
                    rel_tol=0.0,
                    abs_tol=1e-12,
                )
                coverage_comparable += int(comparable)
                if not comparable:
                    continue
                ape_win = float(full["ape_rmse_m"]) < float(reference["ape_rmse_m"])
                rpe_win = float(full["rpe_rmse_m"]) < float(reference["rpe_rmse_m"])
                ape_wins += int(ape_win)
                rpe_wins += int(rpe_win)
                double_wins += int(ape_win and rpe_win)
            full_ape = float(frame.loc[frame.role == "full", "ape_rmse_m"].median())
            base_ape = float(frame.loc[frame.role == baseline, "ape_rmse_m"].median())
            full_rpe = float(frame.loc[frame.role == "full", "rpe_rmse_m"].median())
            base_rpe = float(frame.loc[frame.role == baseline, "rpe_rmse_m"].median())
            rows.append(
                {
                    "state": state,
                    "baseline": baseline,
                    "pairs": 8,
                    "coverage_comparable": coverage_comparable,
                    "ape_wins": ape_wins,
                    "rpe_wins": rpe_wins,
                    "double_wins": double_wins,
                    "full_ape_median_gain_pct": 100.0 * (base_ape - full_ape) / base_ape,
                    "full_rpe_median_gain_pct": 100.0 * (base_rpe - full_rpe) / base_rpe,
                }
            )
    return pd.DataFrame(rows)


def structural_checks(frames: dict[str, pd.DataFrame]) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for state, frame in frames.items():
        for role in ROLES:
            selected = frame[frame.role == role]
            rows.append(
                {
                    "state": state,
                    "role": role,
                    "runs": len(selected),
                    "ok_runs": int((selected.status == "ok").sum()),
                    "input_frames_unique": ";".join(
                        str(value) for value in sorted(selected.input_frames.unique())
                    ),
                    "output_poses_unique": ";".join(
                        str(value) for value in sorted(selected.output_poses.unique())
                    ),
                    "coverage_unique": ";".join(
                        f"{value:.12g}" for value in sorted(selected.coverage_ratio.unique())
                    ),
                    "map_resets_sum": int(selected.map_resets.sum()),
                    "relocalizations_sum": int(selected.relocalizations.sum()),
                    "attempted_seeds_unique": ";".join(
                        str(value) for value in sorted(selected.attempted_seeds.unique())
                    ),
                    "accepted_seeds_unique": ";".join(
                        str(value) for value in sorted(selected.accepted_seeds.unique())
                    ),
                }
            )
    return pd.DataFrame(rows)


def parse_manifest(path: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        key, separator, value = line.partition("=")
        if not separator or key in result:
            raise SystemExit(f"invalid or duplicate manifest line in {path}: {line!r}")
        result[key] = value
    return result


def sha256(path: Path, cache: dict[Path, str]) -> str:
    path = path.resolve()
    if path not in cache:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        cache[path] = digest.hexdigest()
    return cache[path]


def provenance_audit(batch_root: Path, runner_path: Path) -> pd.DataFrame:
    cache: dict[Path, str] = {}
    rows: list[dict[str, object]] = []
    required = {
        "binary_sha256",
        "liborbslam3_sha256",
        "config_sha256",
        "times_sha256",
        "vocabulary_sha256",
        "external_seed_audit_source_sha256",
        "runner_sha256",
        "seed_sha256",
        "role",
        "repeat",
        "seed_audit_enabled",
    }
    for state in ("audit_on", "audit_off"):
        for role in ROLES:
            for repeat in range(1, 9):
                run_dir = batch_root / state / f"{role}_r{repeat}"
                manifest_path = run_dir / "run_manifest.txt"
                manifest = parse_manifest(manifest_path)
                missing = sorted(required - set(manifest))
                if missing:
                    raise SystemExit(f"manifest missing fields {missing}: {manifest_path}")
                binary = Path(manifest["binary"])
                vocabulary = binary.parents[2] / "Vocabulary" / "ORBvoc.txt"
                checks = {
                    "binary": sha256(binary, cache) == manifest["binary_sha256"],
                    "liborbslam3": sha256(Path(manifest["liborbslam3_path"]), cache)
                    == manifest["liborbslam3_sha256"],
                    "config": sha256(Path(manifest["config"]), cache)
                    == manifest["config_sha256"],
                    "times": sha256(Path(manifest["times_file"]), cache)
                    == manifest["times_sha256"],
                    "vocabulary": sha256(vocabulary, cache)
                    == manifest["vocabulary_sha256"],
                    "audit_source": sha256(
                        Path(manifest["external_seed_audit_source_path"]), cache
                    )
                    == manifest["external_seed_audit_source_sha256"],
                    "runner": sha256(runner_path, cache) == manifest["runner_sha256"],
                }
                if manifest["seed_file"]:
                    checks["seed"] = sha256(Path(manifest["seed_file"]), cache) == manifest[
                        "seed_sha256"
                    ]
                else:
                    checks["seed"] = manifest["seed_sha256"] == ""
                role_repeat_ok = (
                    manifest["role"] == role
                    and int(manifest["repeat"]) == repeat
                    and manifest["seed_audit_enabled"] == ("1" if state == "audit_on" else "0")
                )
                audit_artifact_ok = not (run_dir / "instrumentation").exists()
                if state == "audit_on":
                    instrumentation_dir = run_dir / "instrumentation"
                    artifact_names = (
                        "seed_events.csv",
                        "seed_mappoint_summary.csv",
                        "seed_lineages.csv",
                        "seed_summary.json",
                    )
                    artifacts_ok = all(
                        (instrumentation_dir / name).is_file()
                        and (instrumentation_dir / name).stat().st_size > 0
                        for name in artifact_names
                    )
                    summary_path = instrumentation_dir / "seed_summary.json"
                    summary = json.loads(summary_path.read_text(encoding="utf-8"))
                    true_fields = (
                        "phase_conservation",
                        "extractor_conservation",
                        "accepted_conservation",
                        "per_token_conservation",
                        "valid_tokens",
                        "mappoint_pointer_consistency",
                        "mappoint_pointer_key_consistency",
                        "atlas_snapshot_available",
                    )
                    audit_artifact_ok = bool(
                        artifacts_ok
                        and summary.get("schema_version") == 1
                        and summary.get("complete") is True
                        and summary.get("status") == "ok"
                        and Path(str(summary.get("output_directory", ""))).resolve()
                        == instrumentation_dir.resolve()
                        and summary.get("events_overflowed") == 0
                        and summary.get("related_mappoint_overflowed") == 0
                        and all(summary.get(field) is True for field in true_fields)
                    )
                seed_role_ok = (
                    (role == "orb_only" and manifest["seed_file"] == "" and manifest["seed_sha256"] == "")
                    or (
                        role in {"drop", "full"}
                        and manifest["seed_file"] != ""
                        and manifest["seed_sha256"] != ""
                    )
                )
                row: dict[str, object] = {
                    "audit_state": state,
                    "role": role,
                    "repeat": repeat,
                    "run_dir": str(run_dir),
                    "role_repeat_audit_state_ok": int(role_repeat_ok),
                    "seed_role_ok": int(seed_role_ok),
                    "audit_artifact_state_ok": int(audit_artifact_ok),
                    **{f"{name}_sha_match": int(value) for name, value in checks.items()},
                    "all_checks_ok": int(
                        role_repeat_ok
                        and seed_role_ok
                        and audit_artifact_ok
                        and all(checks.values())
                    ),
                }
                for key in (
                    "binary_sha256",
                    "liborbslam3_sha256",
                    "config_sha256",
                    "times_sha256",
                    "vocabulary_sha256",
                    "external_seed_audit_source_sha256",
                    "runner_sha256",
                    "seed_sha256",
                    "role_order",
                    "dataset_dir",
                    "times_file",
                    "config",
                    "binary",
                    "liborbslam3_path",
                    "seed_file",
                ):
                    row[key] = manifest[key]
                rows.append(row)
    result = pd.DataFrame(rows)
    if len(result) != 48 or not (result["all_checks_ok"] == 1).all():
        raise SystemExit("provenance audit failed")
    common_fields = (
        "dataset_dir",
        "times_file",
        "config",
        "binary",
        "liborbslam3_path",
        "binary_sha256",
        "liborbslam3_sha256",
        "config_sha256",
        "times_sha256",
        "vocabulary_sha256",
        "external_seed_audit_source_sha256",
        "runner_sha256",
    )
    mixed = [field for field in common_fields if result[field].nunique(dropna=False) != 1]
    if mixed:
        raise SystemExit(f"mixed common inputs or implementations across batch: {mixed}")
    role_seed_hashes = {
        role: set(result.loc[result.role == role, "seed_sha256"].astype(str))
        for role in ROLES
    }
    if role_seed_hashes["orb_only"] != {""}:
        raise SystemExit("orb_only manifests must have an empty seed hash")
    if any(len(role_seed_hashes[role]) != 1 or "" in role_seed_hashes[role] for role in ("drop", "full")):
        raise SystemExit(f"drop/full seed hashes are not role-wise unique: {role_seed_hashes}")
    if role_seed_hashes["drop"] == role_seed_hashes["full"]:
        raise SystemExit("drop and full seed hashes must differ")
    return result


def validate_schedule(schedule_path: Path, provenance: pd.DataFrame) -> pd.DataFrame:
    schedule = pd.read_csv(schedule_path)
    require_columns(
        schedule,
        ("repeat", "role_order", "first_state", "second_state"),
        schedule_path,
    )
    if (
        len(schedule) != 8
        or schedule["repeat"].duplicated().any()
        or set(schedule["repeat"].astype(int)) != set(range(1, 9))
    ):
        raise SystemExit("schedule does not contain repeats 1..8")
    if set(schedule["first_state"].astype(str)) != {"on", "off"} or not (
        schedule["first_state"].value_counts().to_dict() == {"on": 4, "off": 4}
    ):
        raise SystemExit("schedule first_state is not counterbalanced 4/4")
    position_counts = {role: [0, 0, 0] for role in ROLES}
    audit_rows: list[dict[str, object]] = []
    for row in schedule.itertuples(index=False):
        role_order = str(row.role_order).split()
        if sorted(role_order) != sorted(ROLES):
            raise SystemExit(f"invalid role order for repeat {row.repeat}: {row.role_order}")
        for position, role in enumerate(role_order):
            position_counts[role][position] += 1
        declared = set(
            provenance.loc[provenance.repeat == int(row.repeat), "role_order"].astype(str)
        )
        if declared != {str(row.role_order)}:
            raise SystemExit(f"role order disagrees with schedule for repeat {row.repeat}")
        first_state = str(row.first_state)
        second_state = str(row.second_state)
        if (first_state, second_state) not in {("on", "off"), ("off", "on")}:
            raise SystemExit(f"invalid state order for repeat {row.repeat}")
        actual_orders: dict[str, str] = {}
        state_times: dict[str, list[int]] = {}
        for state in ("on", "off"):
            selected = provenance[
                (provenance.repeat == int(row.repeat))
                & (provenance.audit_state == f"audit_{state}")
            ]
            timed = sorted(
                (
                    (Path(run_dir) / "orbslam3_run.log").stat().st_mtime_ns,
                    role,
                )
                for run_dir, role in zip(selected.run_dir, selected.role)
            )
            actual_orders[state] = " ".join(role for _, role in timed)
            state_times[state] = [timestamp for timestamp, _ in timed]
            if actual_orders[state] != str(row.role_order):
                raise SystemExit(
                    f"actual mtime role order disagrees for repeat {row.repeat} state {state}"
                )
        if max(state_times[first_state]) >= min(state_times[second_state]):
            raise SystemExit(f"actual state order disagrees for repeat {row.repeat}")
        audit_rows.append(
            {
                "repeat": int(row.repeat),
                "declared_role_order": str(row.role_order),
                "actual_audit_on_role_order": actual_orders["on"],
                "actual_audit_off_role_order": actual_orders["off"],
                "declared_first_state": first_state,
                "declared_second_state": second_state,
                "actual_first_state": first_state,
                "schedule_and_mtime_ok": 1,
            }
        )
    if any(max(counts) - min(counts) > 2 for counts in position_counts.values()):
        raise SystemExit(f"role positions are not approximately balanced: {position_counts}")
    return pd.DataFrame(audit_rows)


def save_figures(
    frames: dict[str, pd.DataFrame],
    paired: pd.DataFrame,
    output_dir: Path,
    margin_pct: float,
) -> None:
    figure_dir = output_dir / "figures"
    figure_dir.mkdir(parents=True, exist_ok=True)
    plt.rcParams.update(
        {
            "font.size": 9,
            "axes.labelsize": 10,
            "xtick.labelsize": 9,
            "ytick.labelsize": 9,
            "legend.fontsize": 8,
            "axes.spines.top": False,
            "axes.spines.right": False,
            "pdf.fonttype": 42,
        }
    )

    fig, axes = plt.subplots(1, 2, figsize=(7.0, 3.0), constrained_layout=True)
    offsets = {"audit_off": -0.12, "audit_on": 0.12}
    for axis, metric in zip(axes, METRICS):
        for role_index, role in enumerate(ROLES):
            history = frames["historical"].loc[
                frames["historical"].role == role, metric
            ].to_numpy(dtype=float)
            q1, median, q3 = np.quantile(history, [0.25, 0.5, 0.75])
            axis.fill_between(
                [role_index - 0.28, role_index + 0.28],
                q1,
                q3,
                color="#999999",
                alpha=0.18,
                linewidth=0,
            )
            axis.plot(
                [role_index - 0.28, role_index + 0.28],
                [median, median],
                color=OKABE_ITO["historical"],
                linewidth=1.2,
            )
            off_values = frames["audit_off"].loc[
                frames["audit_off"].role == role, metric
            ].sort_index().to_numpy(dtype=float)
            on_values = frames["audit_on"].loc[
                frames["audit_on"].role == role, metric
            ].sort_index().to_numpy(dtype=float)
            for off_value, on_value in zip(off_values, on_values):
                axis.plot(
                    [role_index + offsets["audit_off"], role_index + offsets["audit_on"]],
                    [off_value, on_value],
                    color="#777777",
                    alpha=0.45,
                    linewidth=0.65,
                    zorder=1,
                )
            for state, values in (("audit_off", off_values), ("audit_on", on_values)):
                axis.scatter(
                    np.full(len(values), role_index + offsets[state]),
                    values,
                    s=20,
                    color=OKABE_ITO[state],
                    edgecolor="white",
                    linewidth=0.35,
                    zorder=2,
                    label=STATE_LABELS[state] if role_index == 0 else None,
                )
        axis.set_xticks(range(len(ROLES)), ["ORB-only", "Drop", "Full"])
        axis.set_ylabel(METRIC_LABELS[metric])
        axis.set_ylim(bottom=0.0)
        axis.grid(axis="y", alpha=0.22, linewidth=0.6)
    axes[0].plot([], [], color="#999999", linewidth=6, alpha=0.25, label="Historical IQR")
    handles, labels = axes[0].get_legend_handles_labels()
    fig.legend(
        handles,
        labels,
        frameon=False,
        loc="upper center",
        bbox_to_anchor=(0.5, 1.08),
        ncol=3,
    )
    for suffix, dpi in (("pdf", None), ("png", 600)):
        fig.savefig(
            figure_dir / f"figure-01-on-off-paired.{suffix}",
            dpi=dpi,
            bbox_inches="tight",
        )
    plt.close(fig)

    fig, axes = plt.subplots(1, 2, figsize=(7.0, 3.0), constrained_layout=True)
    for axis, metric in zip(axes, METRICS):
        axis.axhspan(-margin_pct, margin_pct, color="#009E73", alpha=0.12, zorder=0)
        axis.axhline(0.0, color="#333333", linewidth=0.8, zorder=0)
        selected = paired[paired.metric == metric]
        for role_index, role in enumerate(ROLES):
            values = selected.loc[
                selected.role == role, "on_minus_off_pct"
            ].to_numpy(dtype=float)
            jitter = np.linspace(-0.09, 0.09, len(values))
            axis.scatter(
                role_index + jitter,
                values,
                s=19,
                color="#0072B2",
                alpha=0.85,
                edgecolor="white",
                linewidth=0.3,
            )
            axis.scatter(
                role_index,
                np.median(values),
                marker="D",
                s=34,
                color="#D55E00",
                edgecolor="black",
                linewidth=0.4,
                zorder=3,
            )
        axis.set_xticks(range(len(ROLES)), ["ORB-only", "Drop", "Full"])
        metric_name = "APE RMSE" if metric == "ape_rmse_m" else "RPE RMSE"
        axis.set_ylabel(f"Relative {metric_name} change: audit on - off (%)")
        axis.grid(axis="y", alpha=0.22, linewidth=0.6)
    for suffix, dpi in (("pdf", None), ("png", 600)):
        fig.savefig(
            figure_dir / f"figure-02-relative-deltas.{suffix}",
            dpi=dpi,
            bbox_inches="tight",
        )
    plt.close(fig)


def markdown_table(headers: list[str], rows: list[list[str]]) -> str:
    lines = [
        "| " + " | ".join(headers) + " |",
        "|" + "|".join("---" for _ in headers) + "|",
    ]
    lines.extend("| " + " | ".join(row) + " |" for row in rows)
    return "\n".join(lines)


def fmt(value: object, digits: int = 6) -> str:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return "-"
    if isinstance(value, (float, np.floating)):
        return f"{float(value):.{digits}f}"
    return str(value)


def write_reports(
    output_dir: Path,
    descriptive: pd.DataFrame,
    comparisons: pd.DataFrame,
    history_comparisons: pd.DataFrame,
    wins: pd.DataFrame,
    structural: pd.DataFrame,
    provenance: pd.DataFrame,
    margin_pct: float,
) -> None:
    metric_rows: list[list[str]] = []
    for state in ("historical", "audit_off", "audit_on"):
        for role in ROLES:
            ape = descriptive.query(
                "state == @state and role == @role and metric == 'ape_rmse_m'"
            ).iloc[0]
            rpe = descriptive.query(
                "state == @state and role == @role and metric == 'rpe_rmse_m'"
            ).iloc[0]
            metric_rows.append(
                [
                    STATE_LABELS[state],
                    role,
                    f"{ape['median']:.6f} [{ape['q1']:.6f}, {ape['q3']:.6f}]",
                    f"{rpe['median']:.6f} [{rpe['q1']:.6f}, {rpe['q3']:.6f}]",
                    "8",
                ]
            )
    metric_table = markdown_table(
        ["状态", "角色", "APE 中位数 [Q1,Q3]", "RPE 中位数 [Q1,Q3]", "n"],
        metric_rows,
    )

    delta_rows: list[list[str]] = []
    for row in comparisons.itertuples(index=False):
        delta_rows.append(
            [
                row.role,
                "APE" if row.metric == "ape_rmse_m" else "RPE",
                f"{row.paired_difference_median:+.6f}",
                f"{row.paired_relative_difference_median_pct:+.2f}%",
                f"{row.median_shift_over_historical_iqr:.2f}",
                f"{row.p_value:.4f}",
                f"{row.holm_p_across_6_metrics:.4f}",
                "通过" if row.strict_distribution_preservation_screen else "未通过",
            ]
        )
    delta_table = markdown_table(
        [
            "角色",
            "指标",
            "配对 on-off 差中位数",
            "配对相对差中位数",
            "边际中位差/历史 IQR",
            "Wilcoxon p",
            "Holm p",
            "严格分布保真",
        ],
        delta_rows,
    )

    win_rows: list[list[str]] = []
    for row in wins.itertuples(index=False):
        win_rows.append(
            [
                STATE_LABELS[row.state],
                row.baseline,
                f"{row.ape_wins}/{row.pairs}",
                f"{row.rpe_wins}/{row.pairs}",
                f"{row.double_wins}/{row.pairs}",
                f"{row.full_ape_median_gain_pct:+.2f}%",
                f"{row.full_rpe_median_gain_pct:+.2f}%",
            ]
        )
    win_table = markdown_table(
        ["状态", "基线", "APE 胜", "RPE 胜", "双胜", "APE 中位收益", "RPE 中位收益"],
        win_rows,
    )

    strict_pass = bool(
        (comparisons["strict_distribution_preservation_screen"] == 1).all()
    )
    operational_pass = bool(
        (comparisons["paired_relative_median_within_5pct"] == 1).all()
        and (structural["ok_runs"] == 8).all()
        and (structural["map_resets_sum"] == 0).all()
        and (structural["relocalizations_sum"] == 0).all()
        and structural["coverage_unique"].nunique() == 1
    )
    full_tests = comparisons[comparisons.role == "full"]
    full_history_preserved = bool(
        (full_tests["median_shift_within_historical_iqr"] == 1).all()
    )
    on_wins = wins[wins.state == "audit_on"].set_index("baseline")
    off_wins = wins[wins.state == "audit_off"].set_index("baseline")
    old_wins = wins[wins.state == "historical"].set_index("baseline")
    input_frame_values = sorted(set(structural["input_frames_unique"].astype(str)))
    output_pose_values = sorted(set(structural["output_poses_unique"].astype(str)))
    coverage_values = sorted(set(structural["coverage_unique"].astype(str)))
    input_frame_text = input_frame_values[0] if len(input_frame_values) == 1 else "mixed"
    output_pose_text = output_pose_values[0] if len(output_pose_values) == 1 else "mixed"
    coverage_text = coverage_values[0] if len(coverage_values) == 1 else "mixed"

    report = f"""# A09 ORB-SLAM3 instrumentation A/B 审计

## 分析问题

在冻结的 AQUALOC A09 `4000-4400`、原生 20 Hz、相同 binary/config/times/seed 下，比较 instrumentation audit-on 与 audit-off 各 8 次三路运行。重复编号是 counterbalanced 执行块，不是可复现的随机种子；APE/RPE 越低越好，RPE 沿用历史 `delta=1 frame`。

## 判定

- **运行稳定性与 {margin_pct:.0f}% 配对中位 no-harm：{'通过' if operational_pass else '未通过'}。**48 条轨迹均有效；三路均输出 `{output_pose_text}/{input_frame_text}` poses，coverage `{coverage_text}`，reset/relocalization 均为 0。六个 role×metric 的逐 block 相对差中位数绝对值均不超过 {margin_pct:.0f}%。
- **严格“无扰动/分布保真”：{'通过' if strict_pass else '未通过'}。**full 的 APE/RPE on-off 中位差分别达到历史 full IQR 的 `{full_tests.iloc[0]['median_shift_over_historical_iqr']:.2f}×/{full_tests.iloc[1]['median_shift_over_historical_iqr']:.2f}×`，且小样本 bootstrap 等价筛查不能把全部不确定区间限制在 ±{margin_pct:.0f}% 内。`p>0.05` 只能说明未检出系统偏移，不能证明等价。
- **历史 A09 正例关系：{'保留' if full_history_preserved else '未保留'}。**历史 full 对 ORB-only/drop 双胜为 `{int(old_wins.loc['orb_only','double_wins'])}/8`、`{int(old_wins.loc['drop','double_wins'])}/8`；audit-off 仅 `{int(off_wins.loc['orb_only','double_wins'])}/8`、`{int(off_wins.loc['drop','double_wins'])}/8`，audit-on 为 `{int(on_wins.loc['orb_only','double_wins'])}/8`、`{int(on_wins.loc['drop','double_wins'])}/8`。因此当前 instrumentation build 的 MapPoint 统计不能直接解释为“稳定正例的机制”。

## 精确结果

{metric_table}

IQR 使用 pandas 线性分位数。方括号为 `[Q1,Q3]`，不是置信区间。

## A/B 差值

{delta_table}

Wilcoxon signed-rank 以 repeat block 配对，六个 role×metric 对比使用 Holm 校正。统计功效受 `n=8` 限制，非显著结果不构成无差异证据。

## Full 胜率

{win_table}

## Provenance 与 instrumentation 完整性

- `48/48` manifests 通过路径复算哈希，公共 binary/library/config/times/vocabulary/audit-source/runner 哈希分别唯一。
- audit-on `24/24` instrumentation summaries 为 `complete=true`、`status=ok`、无 overflow，守恒、pointer 与 Atlas 标志全通过。
- audit-off `24/24` 没有 instrumentation 目录；instrumentation 字段保持空值。
- 原始逐轮、provenance 和统计结果分别见 `paired_on_off_differences.csv`、`provenance_audit.csv` 与 `comparison_tests.csv`。

历史 8 轮与 current A/B 不是单因素对照：历史 binary 为 `5016d990…`，current binary 为 `caf6d67b…`；历史 role 位置为 ORB-only `6/1/1`、drop `1/6/1`、full `1/1/6`，current schedule 近似平衡。off-vs-history 的差异同时混有 binary/build、role order、批次时间和线程调度，不能归因给 instrumentation。

## 结论边界与决策

当前证据允许写：instrumentation 没有改变初始化覆盖、reset 状态，且 A09 三路 on/off 逐 block 相对差中位数均在 {margin_pct:.0f}% 内。

当前证据禁止写：instrumentation 已被证明完全无扰动；历史 A09 ORB 正例已由 current binary 复现；MapPoint survival 已解释 full 的稳定收益。

下一步应使用同一 counterbalanced role order，分层比较可恢复的 pre-instrumentation source build、current audit-off 与 current audit-on；在这个 factorial 对照完成前，不把 off-vs-history 差异解释成 instrumentation effect，也不进入 NTNU/UVVID 的正式 MapPoint survival 表。

## Claim Candidates

- Claim: audit logging 未破坏 A09 的轨迹覆盖和初始化状态。
  - Source evidence: `ER-20260724-a09-audit-ab-01`，48 次 frozen-input ORB-SLAM3 运行。
  - Allowed wording: audit-on/off 均为 {output_pose_text}/{input_frame_text} poses，且无 reset/relocalization。
  - Forbidden stronger wording: instrumentation 对 ORB-SLAM3 完全无扰动。
  - Uncertainty: 精度分布和 strict full 胜率未保真。
  - Next check: old-source/current binary 与 audit-on/off 使用相同 counterbalanced role order 分层复跑。
  - Decision: weaken

- Claim: current instrumentation build 保留 A09 稳定 learned-seed 正例。
  - Source evidence: 当前 on/off 双胜明显低于历史。
  - Allowed wording: 当前批次未复现历史正例关系。
  - Forbidden stronger wording: current MapPoint audit 已验证稳定跨后端机制。
  - Uncertainty: ORB 多线程分支、build layout 和审计开销的贡献尚未拆分。
  - Next check: old/new binary 与 audit-on/off 的分层回归。
  - Decision: discard
"""
    (output_dir / "analysis-report.md").write_text(report, encoding="utf-8")

    test_rows = []
    for row in comparisons.itertuples(index=False):
        test_rows.append(
            [
                row.role,
                row.metric,
                fmt(row.paired_difference_median),
                fmt(row.paired_relative_difference_median_pct, 3),
                f"[{row.paired_relative_median_90ci_low_pct:.3f}, {row.paired_relative_median_90ci_high_pct:.3f}]",
                fmt(row.shapiro_p, 4),
                fmt(row.test_statistic, 3),
                fmt(row.p_value, 4),
                fmt(row.holm_p_across_6_metrics, 4),
                fmt(row.rank_biserial_on_minus_off, 3),
            ]
        )
    history_rows = []
    for row in history_comparisons.itertuples(index=False):
        history_rows.append(
            [
                row.role,
                row.metric,
                fmt(row.difference_of_medians),
                fmt(row.difference_of_medians_pct, 3),
                fmt(row.median_shift_over_historical_iqr, 3),
                fmt(row.test_statistic, 3),
                fmt(row.p_value, 4),
                fmt(row.holm_p_across_6_metrics, 4),
                fmt(row.cliff_delta_current_minus_historical, 3),
            ]
        )
    appendix = f"""# A09 instrumentation A/B 统计附录

## 设计与单位

- 单位：同一 frozen input 下的 ORB-SLAM3 run。
- 每个状态、每个角色 `n=8`；on/off 按 counterbalanced repeat block 配对。
- APE/RPE 均为 translation RMSE，单目 Sim(3) 对齐；RPE 为 `delta=1 frame`。
- 主要 A/B 检验：two-sided Wilcoxon signed-rank；六项 Holm 校正。
- 效应量：rank-biserial，正值表示 audit-on 数值更大（对误差指标即更差）。
- practical screen：逐 block 相对差的中位数不超过 ±{margin_pct:.0f}%；90% percentile bootstrap CI 也须完全位于该区间。
- historical IQR screen：on/off 中位差绝对值不超过同角色历史 IQR。

## Audit-on vs audit-off

{markdown_table(['角色','指标','配对差中位数','配对相对差中位数 %','90% bootstrap CI %','Shapiro p','W','p','Holm p','rank-biserial'], test_rows)}

Shapiro-Wilk 仅作差值分布诊断。`n=8` 时检验功效有限，因此主分析使用非参数 Wilcoxon，并把等价性写成预设区间的筛查而不是正式“证明相等”。

## Audit-off vs historical

{markdown_table(['角色','指标','中位差','相对差 %','历史 IQR 倍数','U','p','Holm p','Cliff delta'], history_rows)}

这组历史比较是独立的两批 ORB 多线程运行，使用 two-sided Mann-Whitney U 与 Cliff's delta。两批同时更换了 binary/build、role-order 分布和运行时间，只能视为混杂的 batch comparison；不能识别单独的 build effect 或 instrumentation effect，也不把历史 repeat 与新 repeat 伪装成相同随机种子的配对样本。

## 多重比较与限制

- A/B 六项和 off-vs-history 六项分别在各自 family 内做 Holm 校正。
- 没有删除 outlier；audit-on full r6 和历史 drop r7 均保留。
- 5% 是项目已冻结的 no-harm 门槛，不是从本批数据调参得到。
- 历史 IQR 是经验噪声带，不是概率置信区间。
- current repeat block 对 audit state 做 4/4 counterbalance，并近似平衡 role 位置；历史批次 role 位置严重不平衡，不能与 current 做单因素归因。
- repeat block 不能消除 ORB-SLAM3 多线程调度的随机分支。
"""
    (output_dir / "stats-appendix.md").write_text(appendix, encoding="utf-8")

    catalog = """# A09 instrumentation A/B 图目录

## figure-01-on-off-paired.pdf

- Purpose: 检查各角色 audit-on/off 逐 block 差异是否落在历史分布附近。
- Data source: 两份 current 8-repeat CSV 与历史 8-repeat CSV。
- Caption requirements: 每个点是一轮；灰线连接相同 repeat block；灰带是历史 IQR，黑线是历史中位数；n=8/状态/角色；误差越低越好。
- Key observation: coverage 状态相同，但 full 精度点分布较历史窄 IQR 明显扩散；单一 outlier 没有被隐藏。
- Interpretation: instrumentation 未造成轨迹丢失，但不能据此声称精度分布完全保真。

## figure-02-relative-deltas.pdf

- Purpose: 直接展示每个 repeat block 的 audit-on 相对 audit-off 误差变化。
- Data source: `paired_on_off_differences.csv`。
- Caption requirements: 纵轴为 `(on-off)/off × 100%`；正值表示 audit-on 误差更大；绿色带为预设 ±5% practical margin；菱形为配对差中位数；n=8。
- Key observation: 中位变化位于 ±5%，但若干单轮差值明显越界，full 的 bootstrap 等价筛查不通过。
- Interpretation: 可报告 median no-harm，不可升级为严格无扰动。
"""
    (output_dir / "figure-catalog.md").write_text(catalog, encoding="utf-8")


def write_csv(frame: pd.DataFrame, path: Path) -> None:
    frame.to_csv(path, index=False, float_format="%.12g", quoting=csv.QUOTE_MINIMAL)


def main() -> int:
    args = parse_args()
    batch_root = Path(args.batch_root).resolve()
    paths = {
        "audit_on": Path(args.audit_on_csv).resolve(),
        "audit_off": Path(args.audit_off_csv).resolve(),
        "historical": Path(args.historical_csv).resolve(),
    }
    frames = {
        "audit_on": read_runs(paths["audit_on"], "audit_on", batch_root / "audit_on"),
        "audit_off": read_runs(paths["audit_off"], "audit_off", batch_root / "audit_off"),
        "historical": read_runs(paths["historical"], "historical"),
    }
    validate_instrumentation(frames["audit_on"], frames["audit_off"])

    output_dir = Path(args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    provenance = provenance_audit(
        batch_root,
        Path(__file__).resolve().parent / "run_orbslam3_seeded_triplet.sh",
    )
    execution_order = validate_schedule(Path(args.schedule_csv).resolve(), provenance)
    descriptive = descriptive_stats(frames, args.bootstrap_samples)
    paired, comparisons = paired_on_off(
        frames["audit_on"],
        frames["audit_off"],
        frames["historical"],
        args.practical_margin_pct,
        args.bootstrap_samples,
    )
    historical_comparisons = off_vs_historical(
        frames["audit_off"], frames["historical"]
    )
    wins = win_counts(frames)
    structural = structural_checks(frames)

    write_csv(descriptive, output_dir / "descriptive_stats.csv")
    write_csv(paired, output_dir / "paired_on_off_differences.csv")
    write_csv(comparisons, output_dir / "comparison_tests.csv")
    write_csv(
        historical_comparisons,
        output_dir / "audit_off_vs_historical_tests.csv",
    )
    write_csv(wins, output_dir / "win_counts.csv")
    write_csv(structural, output_dir / "structural_checks.csv")
    write_csv(provenance, output_dir / "provenance_audit.csv")
    write_csv(execution_order, output_dir / "execution_order_audit.csv")
    save_figures(frames, paired, output_dir, args.practical_margin_pct)
    write_reports(
        output_dir,
        descriptive,
        comparisons,
        historical_comparisons,
        wins,
        structural,
        provenance,
        args.practical_margin_pct,
    )

    script_path = Path(__file__).resolve()
    schedule_path = Path(args.schedule_csv).resolve()
    analysis_outputs = (
        "analysis-report.md",
        "stats-appendix.md",
        "figure-catalog.md",
        "descriptive_stats.csv",
        "paired_on_off_differences.csv",
        "comparison_tests.csv",
        "audit_off_vs_historical_tests.csv",
        "win_counts.csv",
        "structural_checks.csv",
        "provenance_audit.csv",
        "execution_order_audit.csv",
        "figures/figure-01-on-off-paired.pdf",
        "figures/figure-01-on-off-paired.png",
        "figures/figure-02-relative-deltas.pdf",
        "figures/figure-02-relative-deltas.png",
    )
    manifest = {
        "schema_version": 1,
        "command": [str(script_path), *sys.argv[1:]],
        "analyzer_sha256": hashlib.sha256(script_path.read_bytes()).hexdigest(),
        "inputs": {state: str(path) for state, path in paths.items()},
        "input_sha256": {
            state: hashlib.sha256(path.read_bytes()).hexdigest()
            for state, path in paths.items()
        },
        "batch_root": str(batch_root),
        "schedule_csv": str(schedule_path),
        "schedule_sha256": hashlib.sha256(schedule_path.read_bytes()).hexdigest(),
        "practical_margin_pct": args.practical_margin_pct,
        "bootstrap_samples": args.bootstrap_samples,
        "runs_analyzed": 48,
        "historical_runs": 24,
        "provenance_checks_ok": int((provenance.all_checks_ok == 1).all()),
        "output_sha256": {
            relative: hashlib.sha256((output_dir / relative).read_bytes()).hexdigest()
            for relative in analysis_outputs
        },
    }
    (output_dir / "analysis_manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )
    print(f"wrote A/B analysis bundle to {output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
