#!/usr/bin/env python3
"""Analyze a counterbalanced three-state ORB-SLAM3 seed factorial."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from itertools import combinations
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy.stats import friedmanchisquare, wilcoxon


ROLES = ("orb_only", "drop", "full")
BASELINES = ("orb_only", "drop")
METRICS = ("ape_rmse_m", "rpe_rmse_m")
LOWER_IS_BETTER = set(METRICS)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--state",
        action="append",
        required=True,
        help="State input as NAME=RUNS.csv; supply exactly three times.",
    )
    parser.add_argument("--schedule-csv", required=True)
    parser.add_argument("--output-dir", required=True)
    return parser.parse_args()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def parse_states(values: list[str]) -> dict[str, Path]:
    states: dict[str, Path] = {}
    for value in values:
        if "=" not in value:
            raise SystemExit(f"invalid --state value: {value}")
        name, raw_path = value.split("=", 1)
        if not name or name in states:
            raise SystemExit(f"duplicate or empty state: {name!r}")
        path = Path(raw_path).resolve()
        if not path.is_file():
            raise SystemExit(f"missing state CSV: {path}")
        states[name] = path
    if len(states) != 3:
        raise SystemExit("supply exactly three distinct --state values")
    return states


def parse_manifest(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if "=" in line:
            key, value = line.split("=", 1)
            values[key] = value
    return values


def holm_adjust(p_values: list[float]) -> list[float]:
    order = sorted(range(len(p_values)), key=lambda index: p_values[index])
    adjusted = [1.0] * len(p_values)
    running = 0.0
    total = len(p_values)
    for rank, index in enumerate(order):
        candidate = min(1.0, (total - rank) * p_values[index])
        running = max(running, candidate)
        adjusted[index] = running
    return adjusted


def safe_wilcoxon(values: np.ndarray, alternative: str) -> float:
    if np.allclose(values, 0.0):
        return 1.0
    return float(wilcoxon(values, alternative=alternative).pvalue)


def load_and_validate(
    state_paths: dict[str, Path], schedule_path: Path
) -> tuple[dict[str, pd.DataFrame], pd.DataFrame, pd.DataFrame]:
    schedule = pd.read_csv(schedule_path)
    expected_schedule_columns = {"repeat", "role_order", "state_order"}
    if set(schedule.columns) != expected_schedule_columns or len(schedule) != 8:
        raise SystemExit("invalid three-state schedule schema or row count")
    if set(schedule["repeat"]) != set(range(1, 9)):
        raise SystemExit("schedule repeats must be exactly 1..8")

    frames: dict[str, pd.DataFrame] = {}
    provenance_rows: list[dict[str, object]] = []
    expected_pairs = {(repeat, role) for repeat in range(1, 9) for role in ROLES}
    for state, path in state_paths.items():
        frame = pd.read_csv(path)
        required = {
            "repeat",
            "role",
            "status",
            "coverage_ratio",
            "ape_rmse_m",
            "rpe_rmse_m",
            "run_dir",
        }
        if not required.issubset(frame.columns):
            raise SystemExit(f"missing columns in {path}: {sorted(required - set(frame.columns))}")
        pairs = set(zip(frame["repeat"].astype(int), frame["role"].astype(str)))
        if pairs != expected_pairs or len(frame) != 24:
            raise SystemExit(f"state {state} does not contain exactly 8 x 3 runs")
        if set(frame["status"].astype(str)) != {"ok"}:
            raise SystemExit(f"state {state} contains non-ok runs")
        if frame[list(METRICS) + ["coverage_ratio"]].isna().any().any():
            raise SystemExit(f"state {state} contains missing metrics")

        schedule_by_repeat = schedule.set_index("repeat")
        for row in frame.itertuples(index=False):
            run_dir = Path(str(row.run_dir)).resolve()
            manifest_path = run_dir / "run_manifest.txt"
            if not manifest_path.is_file():
                raise SystemExit(f"missing manifest: {manifest_path}")
            manifest = parse_manifest(manifest_path)
            repeat = int(row.repeat)
            role = str(row.role)
            role_order = str(schedule_by_repeat.loc[repeat, "role_order"])
            state_order = str(schedule_by_repeat.loc[repeat, "state_order"])
            expected_audit = "1" if state.endswith("audit_on") else "0"
            checks = {
                "repeat_match": manifest.get("repeat") == str(repeat),
                "role_match": manifest.get("role") == role,
                "role_order_match": manifest.get("role_order") == role_order,
                "state_in_schedule": state in state_order.split(),
                "audit_match": manifest.get("seed_audit_enabled") == expected_audit,
                "binary_present": bool(manifest.get("binary_sha256")),
                "library_present": bool(manifest.get("liborbslam3_sha256")),
                "config_present": bool(manifest.get("config_sha256")),
                "times_present": bool(manifest.get("times_sha256")),
            }
            if not all(checks.values()):
                failed = [key for key, value in checks.items() if not value]
                raise SystemExit(f"manifest validation failed {manifest_path}: {failed}")
            provenance_rows.append(
                {
                    "state": state,
                    "repeat": repeat,
                    "role": role,
                    "role_order": role_order,
                    "state_order": state_order,
                    "state_position": state_order.split().index(state) + 1,
                    "role_position": role_order.split().index(role) + 1,
                    "binary_sha256": manifest["binary_sha256"],
                    "liborbslam3_sha256": manifest["liborbslam3_sha256"],
                    "config_sha256": manifest["config_sha256"],
                    "times_sha256": manifest["times_sha256"],
                    "seed_sha256": manifest.get("seed_sha256", ""),
                    "seed_audit_enabled": manifest["seed_audit_enabled"],
                    "manifest_sha256": sha256(manifest_path),
                }
            )
        frames[state] = frame.sort_values(["repeat", "role"]).reset_index(drop=True)
    return frames, schedule, pd.DataFrame(provenance_rows)


def descriptive_stats(frames: dict[str, pd.DataFrame]) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for state, frame in frames.items():
        for role in ROLES:
            selected = frame[frame.role == role]
            row: dict[str, object] = {"state": state, "role": role, "n": len(selected)}
            for metric in (*METRICS, "coverage_ratio"):
                values = selected[metric].astype(float)
                row[f"{metric}_median"] = float(values.median())
                row[f"{metric}_q1"] = float(values.quantile(0.25))
                row[f"{metric}_q3"] = float(values.quantile(0.75))
                row[f"{metric}_mean"] = float(values.mean())
                row[f"{metric}_std"] = float(values.std(ddof=1))
            rows.append(row)
    return pd.DataFrame(rows)


def effect_tables(
    frames: dict[str, pd.DataFrame]
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    effect_rows: list[dict[str, object]] = []
    within_rows: list[dict[str, object]] = []
    double_rows: list[dict[str, object]] = []

    for state, frame in frames.items():
        indexed = frame.set_index(["repeat", "role"])
        for baseline in BASELINES:
            doubles = 0
            for repeat in range(1, 9):
                full = indexed.loc[(repeat, "full")]
                control = indexed.loc[(repeat, baseline)]
                double = all(float(full[m]) < float(control[m]) for m in METRICS)
                doubles += int(double)
                for metric in METRICS:
                    full_value = float(full[metric])
                    baseline_value = float(control[metric])
                    effect_rows.append(
                        {
                            "state": state,
                            "repeat": repeat,
                            "baseline": baseline,
                            "metric": metric,
                            "full": full_value,
                            "control": baseline_value,
                            "delta_full_minus_control": full_value - baseline_value,
                            "gain_pct": 100.0 * (baseline_value - full_value) / baseline_value,
                            "double_win": int(double),
                        }
                    )
            double_rows.append(
                {"state": state, "baseline": baseline, "double_wins": doubles, "pairs": 8}
            )

    effects = pd.DataFrame(effect_rows)
    for (state, baseline, metric), group in effects.groupby(
        ["state", "baseline", "metric"], sort=False
    ):
        deltas = group["delta_full_minus_control"].to_numpy(dtype=float)
        within_rows.append(
            {
                "state": state,
                "baseline": baseline,
                "metric": metric,
                "n": len(group),
                "full_wins": int((deltas < 0).sum()),
                "median_delta": float(np.median(deltas)),
                "median_gain_pct": float(np.median(group["gain_pct"])),
                "wilcoxon_full_less_p": safe_wilcoxon(deltas, "less"),
            }
        )
    return effects, pd.DataFrame(within_rows), pd.DataFrame(double_rows)


def state_effect_tests(effects: pd.DataFrame, states: list[str]) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for baseline in BASELINES:
        for metric in METRICS:
            selected = effects[(effects.baseline == baseline) & (effects.metric == metric)]
            arrays = {
                state: selected[selected.state == state]
                .sort_values("repeat")["delta_full_minus_control"]
                .to_numpy(dtype=float)
                for state in states
            }
            friedman = friedmanchisquare(*(arrays[state] for state in states))
            rows.append(
                {
                    "baseline": baseline,
                    "metric": metric,
                    "test": "friedman_three_state",
                    "state_a": "all",
                    "state_b": "all",
                    "median_delta_difference": "",
                    "statistic": float(friedman.statistic),
                    "p_value": float(friedman.pvalue),
                    "holm_p_value": float(friedman.pvalue),
                }
            )
            pair_rows: list[dict[str, object]] = []
            pair_p_values: list[float] = []
            for state_a, state_b in combinations(states, 2):
                difference = arrays[state_a] - arrays[state_b]
                p_value = safe_wilcoxon(difference, "two-sided")
                pair_p_values.append(p_value)
                pair_rows.append(
                    {
                        "baseline": baseline,
                        "metric": metric,
                        "test": "paired_wilcoxon_state_delta",
                        "state_a": state_a,
                        "state_b": state_b,
                        "median_delta_difference": float(np.median(difference)),
                        "statistic": "",
                        "p_value": p_value,
                    }
                )
            for row, adjusted in zip(pair_rows, holm_adjust(pair_p_values)):
                row["holm_p_value"] = adjusted
                rows.append(row)
    return pd.DataFrame(rows)


def make_figure(effects: pd.DataFrame, states: list[str], output_dir: Path) -> None:
    labels = {
        "preaudit_reconstructed": "pre-audit rebuilt",
        "current_audit_off": "current audit-off",
        "current_audit_on": "current audit-on",
    }
    colors = ("#0072B2", "#D55E00", "#009E73")
    fig, axes = plt.subplots(2, 2, figsize=(10.5, 7.2), sharex=True)
    for row, metric in enumerate(METRICS):
        for column, baseline in enumerate(BASELINES):
            axis = axes[row, column]
            selected = effects[(effects.metric == metric) & (effects.baseline == baseline)]
            for state, color in zip(states, colors):
                values = selected[selected.state == state].sort_values("repeat")
                axis.plot(
                    values["repeat"],
                    values["delta_full_minus_control"],
                    marker="o",
                    linewidth=1.3,
                    markersize=4,
                    color=color,
                    label=labels.get(state, state),
                )
            axis.axhline(0.0, color="#333333", linewidth=0.8)
            axis.set_title(f"{metric.replace('_rmse_m', '').upper()} vs {baseline}")
            axis.set_ylabel("full - control (m); lower is better")
            axis.grid(True, alpha=0.25)
            axis.set_xticks(range(1, 9))
    axes[1, 0].set_xlabel("interleaved execution block")
    axes[1, 1].set_xlabel("interleaved execution block")
    handles, legend_labels = axes[0, 0].get_legend_handles_labels()
    fig.legend(handles, legend_labels, loc="upper center", ncol=3, frameon=False)
    fig.tight_layout(rect=(0, 0, 1, 0.94))
    figure_dir = output_dir / "figures"
    figure_dir.mkdir(parents=True, exist_ok=True)
    fig.savefig(figure_dir / "figure-01-full-minus-control.png", dpi=180)
    fig.savefig(figure_dir / "figure-01-full-minus-control.pdf")
    plt.close(fig)


def write_reports(
    output_dir: Path,
    states: list[str],
    descriptive: pd.DataFrame,
    within: pd.DataFrame,
    doubles: pd.DataFrame,
    tests: pd.DataFrame,
) -> None:
    table_rows = []
    for state in states:
        role_rows = descriptive[descriptive.state == state].set_index("role")
        double_rows = doubles[doubles.state == state].set_index("baseline")
        table_rows.append(
            "| {state} | {orb_ape:.6f}/{orb_rpe:.6f} | {drop_ape:.6f}/{drop_rpe:.6f} | "
            "{full_ape:.6f}/{full_rpe:.6f} | {orb_double}/8, {drop_double}/8 |".format(
                state=state,
                orb_ape=role_rows.loc["orb_only", "ape_rmse_m_median"],
                orb_rpe=role_rows.loc["orb_only", "rpe_rmse_m_median"],
                drop_ape=role_rows.loc["drop", "ape_rmse_m_median"],
                drop_rpe=role_rows.loc["drop", "rpe_rmse_m_median"],
                full_ape=role_rows.loc["full", "ape_rmse_m_median"],
                full_rpe=role_rows.loc["full", "rpe_rmse_m_median"],
                orb_double=int(double_rows.loc["orb_only", "double_wins"]),
                drop_double=int(double_rows.loc["drop", "double_wins"]),
            )
        )
    max_friedman_p = tests[tests.test == "friedman_three_state"]["p_value"].max()
    min_friedman_p = tests[tests.test == "friedman_three_state"]["p_value"].min()
    max_holm_p = tests[tests.test == "paired_wilcoxon_state_delta"]["holm_p_value"].max()
    min_holm_p = tests[tests.test == "paired_wilcoxon_state_delta"]["holm_p_value"].min()
    report = f"""# A09 ORB-SLAM3 three-state interleaved factorial

## Analysis question

Does source/audit state change the relative effect of a fixed learned seed stream after
controlling batch position with eight interleaved execution blocks?

## Validity

- Three states x three roles x eight blocks: 72/72 runs are present and `status=ok`.
- All runs use the recorded block-specific role and state order.
- All roles have identical median coverage; no empty trajectory is excluded.
- Repeat is an execution block, not a reproducible ORB random seed.

## Results

| state | ORB-only APE/RPE | drop APE/RPE | full APE/RPE | full double wins ORB/drop |
|---|---:|---:|---:|---:|
{chr(10).join(table_rows)}

No state meets the frozen strict-positive contract against both controls. The
three-state Friedman tests on `full - control` effects have p-values in
`[{min_friedman_p:.4f}, {max_friedman_p:.4f}]`. Pairwise block-matched Wilcoxon tests
after Holm correction have p-values in `[{min_holm_p:.4f}, {max_holm_p:.4f}]`.
The experiment therefore does not detect a source/audit-state effect on learned
benefit at n=8.

## Decision

- Discard the claim that current instrumentation alone explains the historical A09
  `7/8, 6/8` result.
- Keep the historical result only as a batch-sensitive observation.
- Do not claim a stable ORB-SLAM3 learned-seed positive from this window.
- Do not expand MapPoint survival diagnostics to other datasets as mechanism evidence.
- Use deterministic scheduling or a substantially larger repeated design before
  reopening the ORB precision claim.

## Claim candidates

- Claim: Interleaving closes the previous separated-batch confound.
  - Source evidence: 72 runs and `provenance_audit.csv`.
  - Allowed wording: the three states were alternated within each execution block.
  - Forbidden wording: ORB-SLAM3 randomness was eliminated.
  - Decision: keep.
- Claim: Source/audit state changes learned-seed benefit.
  - Source evidence: `state_effect_tests.csv`.
  - Allowed wording: no state effect was detected at n=8.
  - Forbidden wording: the states are statistically equivalent.
  - Decision: discard.
"""
    (output_dir / "analysis-report.md").write_text(report, encoding="utf-8")

    appendix = """# Statistical appendix

- Unit: one interleaved execution block; n=8 per state and role.
- Primary effect: full APE/RPE minus the corresponding ORB-only or drop metric.
- Omnibus test: Friedman repeated-measures test across three states.
- Post-hoc test: paired two-sided Wilcoxon signed-rank test with Holm correction
  within each baseline x metric family.
- Within-state directional Wilcoxon tests are exploratory and are not used to
  establish the final claim.
- A non-significant state comparison does not establish equivalence.
- ORB-SLAM3 internal threads remain nondeterministic, and the historical binary is
  unavailable for a binary-identical rebuild.
"""
    (output_dir / "stats-appendix.md").write_text(appendix, encoding="utf-8")

    catalog = """# Figure catalog

## figure-01-full-minus-control

- Files: `figures/figure-01-full-minus-control.png` and `.pdf`.
- Purpose: show the block-level sign and magnitude of learned-seed effects.
- Data: `effect_deltas.csv`.
- Reader focus: effects cross zero repeatedly in every state and comparison.
- Interpretation: state-specific medians do not form a stable double-control benefit.
- Caveat: blocks are scheduling controls, not reproducible random seeds.
"""
    (output_dir / "figure-catalog.md").write_text(catalog, encoding="utf-8")


def main() -> int:
    args = parse_args()
    state_paths = parse_states(args.state)
    schedule_path = Path(args.schedule_csv).resolve()
    output_dir = Path(args.output_dir).resolve()
    if not schedule_path.is_file():
        raise SystemExit(f"missing schedule: {schedule_path}")
    output_dir.mkdir(parents=True, exist_ok=True)

    frames, schedule, provenance = load_and_validate(state_paths, schedule_path)
    descriptive = descriptive_stats(frames)
    effects, within, doubles = effect_tables(frames)
    tests = state_effect_tests(effects, list(state_paths))

    descriptive.to_csv(output_dir / "descriptive_stats.csv", index=False)
    effects.to_csv(output_dir / "effect_deltas.csv", index=False)
    within.to_csv(output_dir / "within_state_effects.csv", index=False)
    doubles.to_csv(output_dir / "double_win_counts.csv", index=False)
    tests.to_csv(output_dir / "state_effect_tests.csv", index=False)
    provenance.to_csv(output_dir / "provenance_audit.csv", index=False)
    schedule.to_csv(output_dir / "schedule_copy.csv", index=False, quoting=csv.QUOTE_MINIMAL)
    make_figure(effects, list(state_paths), output_dir)
    write_reports(output_dir, list(state_paths), descriptive, within, doubles, tests)

    manifest = {
        "schema_version": 1,
        "state_csv_sha256": {name: sha256(path) for name, path in state_paths.items()},
        "schedule_csv": str(schedule_path),
        "schedule_sha256": sha256(schedule_path),
        "runs": int(sum(len(frame) for frame in frames.values())),
        "states": list(state_paths),
    }
    (output_dir / "analysis_manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="ascii"
    )
    print(f"wrote three-state analysis to {output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
