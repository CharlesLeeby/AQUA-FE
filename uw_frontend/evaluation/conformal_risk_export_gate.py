from __future__ import annotations

import argparse
import re
from pathlib import Path

import numpy as np
import pandas as pd


DEFAULT_EPSILON_REL = [0.02, 0.05]


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Evaluate window-level conformal risk-control evidence for learned/"
            "conformal export strategies. This is an offline analysis tool; it "
            "does not change the frontend export gate."
        )
    )
    parser.add_argument("--window-library", required=True, help="C3 window library CSV.")
    parser.add_argument(
        "--alpha-scan-csv",
        default=None,
        help="Optional backend-q blend alpha scan CSV with dataset, alpha, se3_ape_rmse_m.",
    )
    parser.add_argument(
        "--alpha-repeat-raw-csv",
        default=None,
        help="Optional raw replay CSV from scripts/summarize_c3_replays.py.",
    )
    parser.add_argument(
        "--tau-scan-csv",
        default=None,
        help=(
            "Optional new-cell tau/export-budget scan CSV. The CSV may contain "
            "explicit tau/budget columns, or encode tau as ncN/tauN in run names."
        ),
    )
    parser.add_argument("--output-dir", required=True)
    parser.add_argument(
        "--epsilon-rel",
        action="append",
        type=float,
        default=None,
        help="Allowed relative APE increase before loss is counted. Default: 0.02 and 0.05.",
    )
    parser.add_argument(
        "--risk-tolerance-rel",
        type=float,
        default=0.01,
        help="Empirical mean excess relative APE tolerated by the CRC selector.",
    )
    parser.add_argument(
        "--violation-rate-tolerance",
        type=float,
        default=0.20,
        help="Empirical no-harm violation-rate tolerance used for a conservative flag.",
    )
    parser.add_argument("--bootstrap-iters", type=int, default=3000)
    parser.add_argument("--ci-level", type=float, default=0.95)
    parser.add_argument("--random-seed", type=int, default=17)
    parser.add_argument(
        "--exclude-status",
        action="append",
        default=["dirty_solver_failure"],
        help="Status values excluded from the clean main table. Repeatable.",
    )
    parser.add_argument(
        "--include-baselines",
        action="store_true",
        help="Include baseline rows in risk rows. By default only non-baseline strategies are evaluated.",
    )
    args = parser.parse_args()

    epsilons = args.epsilon_rel or DEFAULT_EPSILON_REL
    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    library = pd.read_csv(args.window_library)
    risk_rows = build_window_risk_rows(
        library,
        epsilons=epsilons,
        exclude_status=set(args.exclude_status or []),
        include_baselines=bool(args.include_baselines),
    )
    risk_csv = out_dir / "c3_window_risk_rows.csv"
    risk_rows.to_csv(risk_csv, index=False)

    summaries = {}
    for name, group_cols in {
        "by_role": ["role"],
        "by_dataset": ["dataset_family"],
        "by_texture": ["texture_regime"],
        "by_role_dataset": ["role", "dataset_family"],
        "by_method": ["method"],
    }.items():
        table = summarize_risk(
            risk_rows[risk_rows["clean_for_main"]],
            group_cols=group_cols,
            risk_tolerance_rel=float(args.risk_tolerance_rel),
            violation_rate_tolerance=float(args.violation_rate_tolerance),
            bootstrap_iters=int(args.bootstrap_iters),
            ci_level=float(args.ci_level),
            random_seed=int(args.random_seed),
        )
        path = out_dir / f"c3_risk_summary_{name}.csv"
        table.to_csv(path, index=False)
        summaries[name] = table

    selected_rows = []
    role_selected = select_candidates(
        summaries.get("by_role", pd.DataFrame()),
        candidate_col="role",
        selection_scope="window_role",
    )
    if not role_selected.empty:
        selected_rows.append(role_selected)

    alpha_rows = pd.DataFrame()
    alpha_summary = pd.DataFrame()
    if args.alpha_scan_csv:
        alpha_scan = pd.read_csv(args.alpha_scan_csv)
        alpha_rows = build_alpha_scan_risk_rows(
            alpha_scan,
            baselines=baseline_ape_by_dataset_key(library),
            epsilons=epsilons,
            exclude_status=set(),
        )
        alpha_rows.to_csv(out_dir / "c3_alpha_scan_risk_rows.csv", index=False)
        alpha_summary = summarize_risk(
            alpha_rows,
            group_cols=["alpha"],
            risk_tolerance_rel=float(args.risk_tolerance_rel),
            violation_rate_tolerance=float(args.violation_rate_tolerance),
            bootstrap_iters=int(args.bootstrap_iters),
            ci_level=float(args.ci_level),
            random_seed=int(args.random_seed),
        )
        alpha_summary.to_csv(out_dir / "c3_alpha_scan_risk_summary.csv", index=False)
        alpha_selected = select_candidates(
            alpha_summary,
            candidate_col="alpha",
            selection_scope="alpha_scan",
        )
        if not alpha_selected.empty:
            selected_rows.append(alpha_selected)

    alpha_repeat_rows = pd.DataFrame()
    alpha_repeat_summary = pd.DataFrame()
    alpha_repeat_by_dataset = pd.DataFrame()
    if args.alpha_repeat_raw_csv:
        alpha_repeat_raw = pd.read_csv(args.alpha_repeat_raw_csv)
        alpha_repeat_rows = build_alpha_repeat_risk_rows(
            alpha_repeat_raw,
            epsilons=epsilons,
            fallback_baselines=baseline_ape_by_dataset_key(library),
        )
        alpha_repeat_rows.to_csv(out_dir / "c3_alpha_repeat_risk_rows.csv", index=False)
        alpha_repeat_summary = summarize_risk(
            alpha_repeat_rows,
            group_cols=["alpha"],
            risk_tolerance_rel=float(args.risk_tolerance_rel),
            violation_rate_tolerance=float(args.violation_rate_tolerance),
            bootstrap_iters=int(args.bootstrap_iters),
            ci_level=float(args.ci_level),
            random_seed=int(args.random_seed),
        )
        alpha_repeat_summary.to_csv(out_dir / "c3_alpha_repeat_risk_summary.csv", index=False)
        alpha_repeat_by_dataset = summarize_risk(
            alpha_repeat_rows,
            group_cols=["dataset_family", "alpha"],
            risk_tolerance_rel=float(args.risk_tolerance_rel),
            violation_rate_tolerance=float(args.violation_rate_tolerance),
            bootstrap_iters=int(args.bootstrap_iters),
            ci_level=float(args.ci_level),
            random_seed=int(args.random_seed),
        )
        alpha_repeat_by_dataset.to_csv(out_dir / "c3_alpha_repeat_risk_by_dataset.csv", index=False)
        alpha_repeat_selected = select_candidates(
            alpha_repeat_summary,
            candidate_col="alpha",
            selection_scope="alpha_repeat",
        )
        if not alpha_repeat_selected.empty:
            selected_rows.append(alpha_repeat_selected)

    tau_rows = pd.DataFrame()
    tau_summary = pd.DataFrame()
    tau_by_dataset = pd.DataFrame()
    if args.tau_scan_csv:
        tau_scan = pd.read_csv(args.tau_scan_csv)
        tau_rows = build_tau_scan_risk_rows(
            tau_scan,
            baselines=baseline_ape_by_dataset_key(library),
            epsilons=epsilons,
        )
        tau_rows.to_csv(out_dir / "c3_tau_scan_risk_rows.csv", index=False)
        if not tau_rows.empty:
            tau_summary = summarize_risk(
                tau_rows,
                group_cols=["tau", "budget", "policy"],
                risk_tolerance_rel=float(args.risk_tolerance_rel),
                violation_rate_tolerance=float(args.violation_rate_tolerance),
                bootstrap_iters=int(args.bootstrap_iters),
                ci_level=float(args.ci_level),
                random_seed=int(args.random_seed),
            )
            tau_summary.to_csv(out_dir / "c3_tau_scan_risk_summary.csv", index=False)
            tau_by_dataset = summarize_risk(
                tau_rows,
                group_cols=["dataset_family", "tau", "budget", "policy"],
                risk_tolerance_rel=float(args.risk_tolerance_rel),
                violation_rate_tolerance=float(args.violation_rate_tolerance),
                bootstrap_iters=int(args.bootstrap_iters),
                ci_level=float(args.ci_level),
                random_seed=int(args.random_seed),
            )
            tau_by_dataset.to_csv(out_dir / "c3_tau_scan_risk_by_dataset.csv", index=False)
            tau_selected = select_tau_candidates(tau_summary)
            if not tau_selected.empty:
                selected_rows.append(tau_selected)

    selected = pd.concat(selected_rows, ignore_index=True) if selected_rows else pd.DataFrame()
    selected_path = out_dir / "c3_selected_candidates.csv"
    selected.to_csv(selected_path, index=False)

    report = make_report(
        window_library_path=Path(args.window_library),
        alpha_scan_path=Path(args.alpha_scan_csv) if args.alpha_scan_csv else None,
        tau_scan_path=Path(args.tau_scan_csv) if args.tau_scan_csv else None,
        risk_rows=risk_rows,
        summaries=summaries,
        alpha_rows=alpha_rows,
        alpha_summary=alpha_summary,
        alpha_repeat_rows=alpha_repeat_rows,
        alpha_repeat_summary=alpha_repeat_summary,
        alpha_repeat_by_dataset=alpha_repeat_by_dataset,
        tau_rows=tau_rows,
        tau_summary=tau_summary,
        tau_by_dataset=tau_by_dataset,
        selected=selected,
        epsilons=epsilons,
        risk_tolerance_rel=float(args.risk_tolerance_rel),
        violation_rate_tolerance=float(args.violation_rate_tolerance),
        exclude_status=set(args.exclude_status or []),
    )
    report_path = out_dir / "c3_crc_initial_report.md"
    report_path.write_text(report, encoding="utf-8")

    print(f"wrote {risk_csv}")
    for name in summaries:
        print(f"wrote {out_dir / f'c3_risk_summary_{name}.csv'}")
    if args.alpha_scan_csv:
        print(f"wrote {out_dir / 'c3_alpha_scan_risk_rows.csv'}")
        print(f"wrote {out_dir / 'c3_alpha_scan_risk_summary.csv'}")
    if args.alpha_repeat_raw_csv:
        print(f"wrote {out_dir / 'c3_alpha_repeat_risk_rows.csv'}")
        print(f"wrote {out_dir / 'c3_alpha_repeat_risk_summary.csv'}")
        print(f"wrote {out_dir / 'c3_alpha_repeat_risk_by_dataset.csv'}")
    if args.tau_scan_csv:
        print(f"wrote {out_dir / 'c3_tau_scan_risk_rows.csv'}")
        if not tau_summary.empty:
            print(f"wrote {out_dir / 'c3_tau_scan_risk_summary.csv'}")
            print(f"wrote {out_dir / 'c3_tau_scan_risk_by_dataset.csv'}")
    print(f"wrote {selected_path}")
    print(f"wrote {report_path}")
    print(report)
    return 0


def build_window_risk_rows(
    df: pd.DataFrame,
    epsilons: list[float],
    exclude_status: set[str],
    include_baselines: bool = False,
) -> pd.DataFrame:
    rows = []
    work = df.copy()
    if not include_baselines and "role" in work.columns:
        work = work[work["role"].astype(str) != "baseline"].copy()
    for _, item in work.iterrows():
        for epsilon_rel in epsilons:
            rows.append(_risk_row_from_series(item, epsilon_rel, exclude_status, source_table="window_library"))
    return pd.DataFrame(rows)


def build_alpha_scan_risk_rows(
    df: pd.DataFrame,
    baselines: dict[str, float],
    epsilons: list[float],
    exclude_status: set[str],
) -> pd.DataFrame:
    rows = []
    for _, item in df.iterrows():
        dataset_key = str(item["dataset"]).lower()
        if dataset_key not in baselines:
            continue
        baseline_ape = float(baselines[dataset_key])
        series = pd.Series(
            {
                "window": dataset_key.upper(),
                "dataset_family": dataset_key.upper(),
                "texture_regime": "alpha_scan",
                "method": f"blend_alpha_{float(item['alpha']):g}",
                "role": "alpha_scan",
                "status": "clean_single_alpha_scan",
                "ape_rmse": float(item["se3_ape_rmse_m"]),
                "rpe_rmse": float(item.get("rpe_trans_rmse_m", np.nan)),
                "baseline_ape": baseline_ape,
                "alpha": float(item["alpha"]),
            }
        )
        for epsilon_rel in epsilons:
            rows.append(_risk_row_from_series(series, epsilon_rel, exclude_status, source_table="alpha_scan"))
    return pd.DataFrame(rows)


def build_alpha_repeat_risk_rows(
    df: pd.DataFrame,
    epsilons: list[float],
    fallback_baselines: dict[str, float],
) -> pd.DataFrame:
    work = df.copy()
    work["dataset"] = work["dataset"].astype(str).str.lower()
    baselines = dict(fallback_baselines)
    baseline_mask = work["method"].astype(str).str.contains("baseline", regex=False, na=False)
    for dataset, group in work[baseline_mask].groupby("dataset"):
        values = group["se3_ape_rmse_m"].to_numpy(dtype=np.float64)
        values = values[np.isfinite(values)]
        if values.size:
            baselines[str(dataset).lower()] = float(np.median(values))

    rows = []
    candidates = work[
        work["method"].astype(str).str.contains("c95_blend", regex=False, na=False)
        & work["alpha"].notna()
    ].copy()
    for _, item in candidates.iterrows():
        dataset_key = str(item["dataset"]).lower()
        if dataset_key not in baselines:
            continue
        series = pd.Series(
            {
                "window": str(item.get("run_name", dataset_key)),
                "dataset_family": dataset_key,
                "texture_regime": "alpha_repeat",
                "method": f"blend_alpha_{float(item['alpha']):g}",
                "role": "alpha_repeat",
                "status": "clean_repeat_raw",
                "ape_rmse": float(item["se3_ape_rmse_m"]),
                "rpe_rmse": float(item.get("rpe_trans_rmse_m", np.nan)),
                "baseline_ape": float(baselines[dataset_key]),
                "alpha": float(item["alpha"]),
            }
        )
        for epsilon_rel in epsilons:
            rows.append(_risk_row_from_series(series, epsilon_rel, set(), source_table="alpha_repeat"))
    return pd.DataFrame(rows)


def build_tau_scan_risk_rows(
    df: pd.DataFrame,
    baselines: dict[str, float],
    epsilons: list[float],
) -> pd.DataFrame:
    rows = []
    for _, item in df.iterrows():
        ape = _finite_float(item.get("se3_ape_rmse_m", item.get("ape_rmse", np.nan)))
        if ape is None:
            continue
        dataset_key = _dataset_key_from_scan_row(item)
        if not dataset_key or dataset_key not in baselines:
            continue
        tau = _tau_from_scan_row(item)
        if tau is None:
            continue
        budget = _budget_from_scan_row(item)
        policy = _policy_from_scan_row(item)
        series = pd.Series(
            {
                "window": str(item.get("window", item.get("run", item.get("run_dir", dataset_key)))),
                "dataset_family": dataset_key,
                "texture_regime": str(item.get("texture_regime", "tau_scan")),
                "method": f"tau_{tau}_budget_{budget}_{policy}",
                "role": "tau_scan",
                "status": str(item.get("status", "clean_tau_scan")),
                "ape_rmse": ape,
                "rpe_rmse": _finite_float(item.get("rpe_trans_rmse_m", item.get("rpe_rmse", np.nan))) or np.nan,
                "baseline_ape": float(baselines[dataset_key]),
                "tau": int(tau),
                "budget": budget,
                "policy": policy,
                "exported_learned_observations": _finite_float(
                    item.get("published_learned_observations", item.get("exported_learned_features_sum", np.nan))
                ),
                "exported_loftr_observations": _finite_float(
                    item.get("published_loftr_observations", item.get("exported_loftr_features_sum", np.nan))
                ),
            }
        )
        for epsilon_rel in epsilons:
            rows.append(_risk_row_from_series(series, epsilon_rel, set(), source_table="tau_scan"))
    return pd.DataFrame(rows)


def _finite_float(value: object) -> float | None:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    if not np.isfinite(out):
        return None
    return out


def _scan_text(item: pd.Series) -> str:
    parts = []
    for col in ["dataset", "dataset_family", "window", "run", "run_dir", "method"]:
        if col in item and pd.notna(item[col]):
            parts.append(str(item[col]))
    return " ".join(parts).lower()


def _dataset_key_from_scan_row(item: pd.Series) -> str | None:
    for col in ["dataset", "dataset_family"]:
        if col in item and pd.notna(item[col]):
            raw = str(item[col]).strip().lower()
            normalized = _normalize_dataset_key(raw)
            if normalized:
                return normalized
    return _normalize_dataset_key(_scan_text(item))


def _normalize_dataset_key(text: str) -> str | None:
    raw = str(text).lower()
    if "h07" in raw or "harbor07" in raw:
        return "h07"
    if "h06" in raw or "harbor06" in raw:
        return "h06"
    if "a09" in raw or "archaeo09" in raw:
        return "a09"
    if "a08" in raw or "archaeo08" in raw:
        return "a08"
    if "a06" in raw or "archaeo06" in raw:
        return "a06"
    if "afrl-fl" in raw or "afrl_fl" in raw or re.search(r"\bfl\b", raw):
        return "afrl-fl"
    if "afrl-fr" in raw or "afrl_fr" in raw or re.search(r"\bfr\b", raw):
        return "afrl-fr"
    if "ntnu" in raw:
        return "ntnu"
    return None


def _tau_from_scan_row(item: pd.Series) -> int | None:
    for col in ["tau", "new_cell_tau", "new_cell_threshold", "required_new_cells", "min_new_cells"]:
        if col in item and pd.notna(item[col]):
            value = _finite_float(item[col])
            if value is not None:
                return int(value)
    match = re.search(r"(?:^|[_\-/])(?:nc|tau)(\d+)(?:[_\-/]|$)", _scan_text(item))
    return int(match.group(1)) if match else None


def _budget_from_scan_row(item: pd.Series) -> str:
    for col in ["budget", "export_budget", "sidecar_budget", "max_sidecar_observations"]:
        if col in item and pd.notna(item[col]):
            value = _finite_float(item[col])
            return str(int(value)) if value is not None and value.is_integer() else str(item[col])
    match = re.search(r"(?:^|[_\-/])(?:budget|b)(\d+)(?:[_\-/]|$)", _scan_text(item))
    return match.group(1) if match else "default"


def _policy_from_scan_row(item: pd.Series) -> str:
    text = _scan_text(item)
    for name in ["qfloorselect", "qfloor", "openprobe", "h07fix", "largepool", "noinit", "budget6"]:
        if name in text:
            return name
    return str(item.get("policy", item.get("profile", "default")))


def baseline_ape_by_dataset_key(df: pd.DataFrame) -> dict[str, float]:
    baselines: dict[str, float] = {}
    if "role" not in df.columns:
        return baselines
    for _, item in df[df["role"].astype(str) == "baseline"].iterrows():
        key = _normalize_dataset_key(str(item.get("dataset_family", "")))
        if key is None:
            key = _normalize_dataset_key(str(item.get("window", "")))
        if key:
            baselines[key] = float(item.get("baseline_ape", item.get("ape_rmse")))
    return baselines


def summarize_risk(
    rows: pd.DataFrame,
    group_cols: list[str],
    risk_tolerance_rel: float,
    violation_rate_tolerance: float,
    bootstrap_iters: int,
    ci_level: float,
    random_seed: int,
) -> pd.DataFrame:
    if rows.empty:
        return pd.DataFrame()
    needed_cols = ["epsilon_rel", *group_cols]
    summaries = []
    grouped = rows.groupby(needed_cols, dropna=False, sort=True)
    for key, group in grouped:
        if not isinstance(key, tuple):
            key = (key,)
        key_map = dict(zip(needed_cols, key))
        loss_rel = group["loss_rel"].to_numpy(dtype=np.float64)
        violation = group["violation"].to_numpy(dtype=np.float64)
        ci_loss = bootstrap_mean_ci(loss_rel, bootstrap_iters, ci_level, random_seed)
        ci_violation = bootstrap_mean_ci(violation, bootstrap_iters, ci_level, random_seed + 1)
        mean_loss = float(np.mean(loss_rel)) if len(loss_rel) else float("nan")
        violation_rate = float(np.mean(violation)) if len(violation) else float("nan")
        summaries.append(
            {
                **key_map,
                "n_windows": int(len(group)),
                "n_unique_windows": int(group["window"].nunique()) if "window" in group else int(len(group)),
                "mean_delta_rel": float(group["relative_delta"].mean()),
                "median_delta_rel": float(group["relative_delta"].median()),
                "worst_delta_rel": float(group["relative_delta"].max()),
                "mean_loss_rel": mean_loss,
                "loss_rel_ci_low": ci_loss[0],
                "loss_rel_ci_high": ci_loss[1],
                "violation_rate": violation_rate,
                "violation_ci_low": ci_violation[0],
                "violation_ci_high": ci_violation[1],
                "empirical_mean_loss_pass": bool(mean_loss <= risk_tolerance_rel),
                "empirical_violation_pass": bool(violation_rate <= violation_rate_tolerance),
                "conservative_mean_loss_pass": bool(ci_loss[1] <= risk_tolerance_rel),
                "conservative_violation_pass": bool(ci_violation[1] <= violation_rate_tolerance),
            }
        )
    return pd.DataFrame(summaries)


def select_candidates(
    summary: pd.DataFrame,
    candidate_col: str,
    selection_scope: str,
) -> pd.DataFrame:
    if summary.empty or candidate_col not in summary.columns:
        return pd.DataFrame()
    rows = []
    for epsilon_rel, group in summary.groupby("epsilon_rel", dropna=False, sort=True):
        work = group.copy()
        empirical = work[
            (work["empirical_mean_loss_pass"].astype(bool))
            & (work["empirical_violation_pass"].astype(bool))
        ].copy()
        conservative = work[
            (work["conservative_mean_loss_pass"].astype(bool))
            & (work["conservative_violation_pass"].astype(bool))
        ].copy()
        for tier, candidates in {
            "empirical": empirical,
            "conservative": conservative,
        }.items():
            if candidates.empty:
                continue
            ranked = candidates.sort_values(
                by=["mean_loss_rel", "violation_rate", "mean_delta_rel", "worst_delta_rel"],
                ascending=[True, True, True, True],
            )
            best = ranked.iloc[0].to_dict()
            rows.append(
                {
                    "selection_scope": selection_scope,
                    "selection_tier": tier,
                    "epsilon_rel": float(epsilon_rel),
                    "selected_candidate": best[candidate_col],
                    "n_windows": int(best["n_windows"]),
                    "mean_delta_rel": float(best["mean_delta_rel"]),
                    "worst_delta_rel": float(best["worst_delta_rel"]),
                    "mean_loss_rel": float(best["mean_loss_rel"]),
                    "violation_rate": float(best["violation_rate"]),
                    "note": _selection_note(selection_scope, tier, best[candidate_col]),
                }
            )
    return pd.DataFrame(rows)


def select_tau_candidates(summary: pd.DataFrame) -> pd.DataFrame:
    if summary.empty or "tau" not in summary.columns:
        return pd.DataFrame()
    rows = []
    for epsilon_rel, group in summary.groupby("epsilon_rel", dropna=False, sort=True):
        work = group.copy()
        candidates = work[
            (work["empirical_mean_loss_pass"].astype(bool))
            & (work["empirical_violation_pass"].astype(bool))
        ].copy()
        if candidates.empty:
            continue
        max_windows = int(candidates["n_unique_windows"].max()) if "n_unique_windows" in candidates else 0
        if max_windows < 2:
            continue
        candidates = candidates[candidates["n_unique_windows"] >= 2].copy()
        candidates["_budget_rank"] = candidates["budget"].map(_budget_rank)
        ranked = candidates.sort_values(
            by=["tau", "n_unique_windows", "_budget_rank", "mean_loss_rel", "violation_rate", "worst_delta_rel"],
            ascending=[True, False, False, True, True, True],
        )
        best = ranked.iloc[0].to_dict()
        rows.append(
            {
                "selection_scope": "tau_scan",
                "selection_tier": "empirical",
                "epsilon_rel": float(epsilon_rel),
                "selected_candidate": f"tau={int(best['tau'])}, budget={best['budget']}, policy={best['policy']}",
                "n_windows": int(best["n_windows"]),
                "mean_delta_rel": float(best["mean_delta_rel"]),
                "worst_delta_rel": float(best["worst_delta_rel"]),
                "mean_loss_rel": float(best["mean_loss_rel"]),
                "violation_rate": float(best["violation_rate"]),
                "note": "empirical selector chooses the least restrictive tau/budget passing no-harm risk checks.",
            }
        )
    return pd.DataFrame(rows)


def _budget_rank(value: object) -> float:
    if value is None or pd.isna(value):
        return -1.0
    text = str(value).lower()
    if text == "default":
        return 0.0
    numeric = _finite_float(text)
    return float(numeric) if numeric is not None else 0.0


def _selection_note(scope: str, tier: str, candidate: object) -> str:
    if scope == "alpha_repeat":
        return (
            f"{tier} risk selector chooses backend blend alpha={candidate} "
            "from repeated VINS replays."
        )
    if scope == "alpha_scan":
        return (
            f"{tier} risk selector chooses backend blend alpha={candidate}. "
            "This is still based on single-run alpha scans."
        )
    return f"{tier} risk selector chooses {candidate} in the current window library."


def bootstrap_mean_ci(
    values: np.ndarray,
    iters: int,
    ci_level: float,
    seed: int,
) -> tuple[float, float]:
    values = np.asarray(values, dtype=np.float64)
    values = values[np.isfinite(values)]
    if values.size == 0:
        return float("nan"), float("nan")
    if values.size == 1 or iters <= 0:
        mean = float(values.mean())
        return mean, mean
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, values.size, size=(int(iters), values.size))
    means = values[idx].mean(axis=1)
    tail = (1.0 - float(ci_level)) / 2.0
    return float(np.quantile(means, tail)), float(np.quantile(means, 1.0 - tail))


def _risk_row_from_series(
    item: pd.Series,
    epsilon_rel: float,
    exclude_status: set[str],
    source_table: str,
) -> dict:
    ape = float(item["ape_rmse"])
    baseline = float(item["baseline_ape"])
    delta = ape - baseline
    relative_delta = delta / baseline if baseline > 0.0 else float("nan")
    epsilon_abs_m = float(epsilon_rel) * baseline
    loss_m = max(0.0, delta - epsilon_abs_m)
    loss_rel = max(0.0, relative_delta - float(epsilon_rel)) if np.isfinite(relative_delta) else float("nan")
    status = str(item.get("status", ""))
    clean_for_main = status not in exclude_status and status.startswith("clean")
    out = {
        "source_table": source_table,
        "window": item.get("window", ""),
        "dataset_family": item.get("dataset_family", ""),
        "texture_regime": item.get("texture_regime", ""),
        "method": item.get("method", ""),
        "role": item.get("role", ""),
        "status": status,
        "clean_for_main": bool(clean_for_main),
        "ape_rmse": ape,
        "rpe_rmse": float(item.get("rpe_rmse", np.nan)),
        "baseline_ape": baseline,
        "delta_ape": delta,
        "relative_delta": relative_delta,
        "epsilon_rel": float(epsilon_rel),
        "epsilon_abs_m": epsilon_abs_m,
        "loss_m": loss_m,
        "loss_rel": loss_rel,
        "violation": bool(delta > epsilon_abs_m),
    }
    if "alpha" in item:
        out["alpha"] = float(item["alpha"])
    for col in ["tau", "budget", "policy", "exported_learned_observations", "exported_loftr_observations"]:
        if col in item:
            out[col] = item[col]
    return out


def make_report(
    window_library_path: Path,
    alpha_scan_path: Path | None,
    tau_scan_path: Path | None,
    risk_rows: pd.DataFrame,
    summaries: dict[str, pd.DataFrame],
    alpha_rows: pd.DataFrame,
    alpha_summary: pd.DataFrame,
    alpha_repeat_rows: pd.DataFrame,
    alpha_repeat_summary: pd.DataFrame,
    alpha_repeat_by_dataset: pd.DataFrame,
    tau_rows: pd.DataFrame,
    tau_summary: pd.DataFrame,
    tau_by_dataset: pd.DataFrame,
    selected: pd.DataFrame,
    epsilons: list[float],
    risk_tolerance_rel: float,
    violation_rate_tolerance: float,
    exclude_status: set[str],
) -> str:
    lines = []
    lines.append("# C3 CRC 初始离线评估")
    lines.append("")
    lines.append("这个报告只评估已有窗口库,不代表正式 new-cell τ 门已经接入导出流程。")
    lines.append("")
    lines.append("## 输入")
    lines.append("")
    lines.append(f"- window_library: `{window_library_path}`")
    if alpha_scan_path:
        lines.append(f"- alpha_scan: `{alpha_scan_path}`")
    if tau_scan_path:
        lines.append(f"- tau_scan: `{tau_scan_path}`")
    lines.append(f"- epsilon_rel: {', '.join(f'{v:.1%}' for v in epsilons)}")
    lines.append(f"- mean_loss tolerance: {risk_tolerance_rel:.2%}")
    lines.append(f"- violation-rate tolerance: {violation_rate_tolerance:.1%}")
    lines.append(f"- excluded status from main table: {', '.join(sorted(exclude_status)) or 'none'}")
    lines.append("")

    clean = risk_rows[risk_rows["clean_for_main"]]
    excluded = risk_rows[~risk_rows["clean_for_main"]]
    lines.append("## 窗口库状态")
    lines.append("")
    lines.append(f"- clean candidate rows: {int(clean[['window', 'method']].drop_duplicates().shape[0])}")
    lines.append(f"- excluded/appendix rows: {int(excluded[['window', 'method']].drop_duplicates().shape[0])}")
    if not excluded.empty:
        excluded_unique = excluded[["window", "method", "status"]].drop_duplicates()
        lines.append("")
        lines.append("| window | method | status |")
        lines.append("|---|---|---|")
        for _, row in excluded_unique.iterrows():
            lines.append(f"| {row['window']} | {row['method']} | {row['status']} |")
    lines.append("")

    role_summary = summaries.get("by_role", pd.DataFrame())
    if not role_summary.empty:
        lines.append("## 主结果:按策略角色汇总")
        lines.append("")
        lines.append(_format_table(role_summary, preferred_cols=[
            "epsilon_rel",
            "role",
            "n_windows",
            "mean_delta_rel",
            "worst_delta_rel",
            "mean_loss_rel",
            "violation_rate",
            "empirical_mean_loss_pass",
            "empirical_violation_pass",
        ]))
        lines.append("")

    method_summary = summaries.get("by_method", pd.DataFrame())
    if not method_summary.empty:
        lines.append("## 方法级风险表")
        lines.append("")
        lines.append(_format_table(method_summary, preferred_cols=[
            "epsilon_rel",
            "method",
            "n_windows",
            "mean_delta_rel",
            "worst_delta_rel",
            "mean_loss_rel",
            "violation_rate",
        ]))
        lines.append("")

    if not alpha_summary.empty:
        lines.append("## blend alpha 扫描")
        lines.append("")
        lines.append("这部分是单次 VINS 扫描,只能说明风险形状,不能替代重复运行。")
        lines.append("")
        lines.append(_format_table(alpha_summary, preferred_cols=[
            "epsilon_rel",
            "alpha",
            "n_windows",
            "mean_delta_rel",
            "worst_delta_rel",
            "mean_loss_rel",
            "violation_rate",
        ]))
        lines.append("")
        bad = alpha_rows[(alpha_rows["violation"]) & (alpha_rows["epsilon_rel"] == min(epsilons))]
        if not bad.empty:
            lines.append("2% no-harm 下触发违反的 alpha 行:")
            lines.append("")
            lines.append(_format_table(bad, preferred_cols=[
                "window",
                "alpha",
                "ape_rmse",
                "baseline_ape",
                "relative_delta",
                "loss_rel",
            ]))
            lines.append("")

    if not alpha_repeat_summary.empty:
        lines.append("## blend alpha 重复重放风险")
        lines.append("")
        lines.append("这部分使用每次 VINS replay 的 raw 结果,比单次 alpha scan 更适合决定 alpha。")
        lines.append("")
        lines.append(_format_table(alpha_repeat_summary, preferred_cols=[
            "epsilon_rel",
            "alpha",
            "n_windows",
            "mean_delta_rel",
            "worst_delta_rel",
            "mean_loss_rel",
            "violation_rate",
            "empirical_mean_loss_pass",
            "empirical_violation_pass",
        ]))
        lines.append("")
        if not alpha_repeat_by_dataset.empty:
            lines.append("按数据集分解:")
            lines.append("")
            lines.append(_format_table(alpha_repeat_by_dataset, preferred_cols=[
                "epsilon_rel",
                "dataset_family",
                "alpha",
                "n_windows",
                "mean_delta_rel",
                "worst_delta_rel",
                "mean_loss_rel",
                "violation_rate",
            ]))
            lines.append("")

    if tau_scan_path:
        lines.append("## new-cell tau 扫描")
        lines.append("")
        if tau_rows.empty:
            lines.append("当前 tau 扫描 CSV 没有可用的 VINS APE 行,所以只可作导出行为审计,不能作风险选择。")
            lines.append("")
        else:
            lines.append("这部分把 tau/new-cell 扫描接入同一个 no-harm 风险表。只有带 VINS APE 的行会进入汇总。")
            lines.append("")
            lines.append(_format_table(tau_summary, preferred_cols=[
                "epsilon_rel",
                "tau",
                "budget",
                "policy",
                "n_windows",
                "mean_delta_rel",
                "worst_delta_rel",
                "mean_loss_rel",
                "violation_rate",
                "empirical_mean_loss_pass",
                "empirical_violation_pass",
            ]))
            lines.append("")
            if not tau_by_dataset.empty:
                lines.append("按数据集分解:")
                lines.append("")
                lines.append(_format_table(tau_by_dataset, preferred_cols=[
                    "epsilon_rel",
                    "dataset_family",
                    "tau",
                    "budget",
                    "policy",
                    "n_windows",
                    "mean_delta_rel",
                    "worst_delta_rel",
                    "mean_loss_rel",
                    "violation_rate",
                ]))
                lines.append("")

    if not selected.empty:
        lines.append("## 风险选择器输出")
        lines.append("")
        lines.append("这只是离线选择器结果;alpha/tau 扫描仍需重复运行和更多窗口后才能写成主结论。")
        lines.append("")
        lines.append(_format_table(selected, preferred_cols=[
            "selection_scope",
            "selection_tier",
            "epsilon_rel",
            "selected_candidate",
            "n_windows",
            "mean_delta_rel",
            "worst_delta_rel",
            "mean_loss_rel",
            "violation_rate",
            "note",
        ]))
        lines.append("")

    lines.append("## 结论")
    lines.append("")
    lines.append("- 现在 C3 已经可以做窗口级 no-harm 风险审计。")
    role_summary = summaries.get("by_role", pd.DataFrame())
    if not role_summary.empty:
        passed = role_summary[
            (role_summary["empirical_mean_loss_pass"].astype(bool))
            & (role_summary["empirical_violation_pass"].astype(bool))
        ]
        if not passed.empty:
            eps_text = ", ".join(f"{float(v):.1%}" for v in sorted(passed["epsilon_rel"].unique()))
            lines.append(f"- 当前窗口库在这些 no-harm 容忍度下通过经验风险检查:{eps_text}。最终能否写主文,还要看窗口数和重复运行是否足够。")
        else:
            lines.append("- 当前窗口库没有通过经验 no-harm 风险检查的容忍度;只能作为反例/敏感性分析。")
    lines.append("- blend alpha 的单次扫描只能说明风险形状;A06 存在重放敏感和异常尖峰,必须补重复运行后再下定论。")
    if tau_scan_path and not tau_rows.empty:
        lines.append("- `new-cell τ` 扫描已经能进入同一个风险表;现在还需要补全更多窗口/重复运行后再写正式 CRC 结论。")
    else:
        lines.append("- 还不能写成正式的 `new-cell τ` CRC claim,因为当前窗口库不是完整 τ 扫描矩阵。")
    lines.append("- 下一步要生成 τ/new-cell/export-ratio 的 VINS 扫描表,再用同一个脚本选择风险受控的导出阈值。")
    return "\n".join(lines) + "\n"


def _format_table(df: pd.DataFrame, preferred_cols: list[str]) -> str:
    cols = [col for col in preferred_cols if col in df.columns]
    if not cols:
        cols = list(df.columns)
    work = df[cols].copy()
    for col in work.columns:
        if pd.api.types.is_float_dtype(work[col]):
            if re.search(r"epsilon|rate|rel|pass|alpha", col):
                work[col] = work[col].map(lambda v: "" if pd.isna(v) else f"{float(v):.4f}")
            else:
                work[col] = work[col].map(lambda v: "" if pd.isna(v) else f"{float(v):.6f}")
    return _dataframe_to_markdown(work)


def _dataframe_to_markdown(df: pd.DataFrame) -> str:
    if df.empty:
        return "_empty_"
    cols = [str(col) for col in df.columns]
    rows = []
    for _, row in df.iterrows():
        values = []
        for col in df.columns:
            value = row[col]
            if pd.isna(value):
                values.append("")
            else:
                values.append(str(value))
        rows.append(values)
    lines = [
        "| " + " | ".join(cols) + " |",
        "| " + " | ".join("---" for _ in cols) + " |",
    ]
    for row in rows:
        lines.append("| " + " | ".join(_escape_markdown_cell(value) for value in row) + " |")
    return "\n".join(lines)


def _escape_markdown_cell(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ")


if __name__ == "__main__":
    raise SystemExit(main())
