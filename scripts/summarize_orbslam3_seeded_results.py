#!/usr/bin/env python3
"""Summarize repeated ORB-only/drop/full seeded ORB-SLAM3 comparisons."""

from __future__ import annotations

import argparse
import csv
import statistics
from pathlib import Path


ROLES = ("orb_only", "drop", "full")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--group",
        action="append",
        required=True,
        metavar="NAME=CSV",
        help="Repeated comparison group; may be supplied more than once.",
    )
    parser.add_argument("--output-csv", required=True)
    return parser.parse_args()


def optional_float(value: str | None) -> float | None:
    if value is None or value.strip() == "":
        return None
    return float(value)


def median(values: list[float | None]) -> float | str:
    finite = [value for value in values if value is not None]
    return statistics.median(finite) if finite else ""


def common_value(values: list[str | None]) -> str:
    present = {value.strip() for value in values if value and value.strip()}
    if not present:
        return ""
    return present.pop() if len(present) == 1 else "mixed"


def relative_gain(baseline: float | str, full: float | str) -> float | str:
    if not isinstance(baseline, float) or not isinstance(full, float) or baseline == 0.0:
        return ""
    return 100.0 * (baseline - full) / baseline


def paired_stats(
    indexed: dict[tuple[str, int], dict[str, str]], baseline_role: str
) -> dict[str, int]:
    repeats = sorted(
        repeat
        for role, repeat in indexed
        if role == "full" and (baseline_role, repeat) in indexed
    )
    result = {
        "pairs": len(repeats),
        "coverage_noninferior": 0,
        "metric_comparable": 0,
        "ape_wins": 0,
        "rpe_wins": 0,
        "double_wins": 0,
    }
    for repeat in repeats:
        full = indexed[("full", repeat)]
        baseline = indexed[(baseline_role, repeat)]
        full_coverage = float(full["coverage_ratio"])
        baseline_coverage = float(baseline["coverage_ratio"])
        if full_coverage + 1e-12 >= baseline_coverage:
            result["coverage_noninferior"] += 1
        if abs(full_coverage - baseline_coverage) > 1e-12:
            continue
        full_ape = optional_float(full.get("ape_rmse_m"))
        baseline_ape = optional_float(baseline.get("ape_rmse_m"))
        full_rpe = optional_float(full.get("rpe_rmse_m"))
        baseline_rpe = optional_float(baseline.get("rpe_rmse_m"))
        if None in (full_ape, baseline_ape, full_rpe, baseline_rpe):
            continue
        result["metric_comparable"] += 1
        ape_win = full_ape < baseline_ape
        rpe_win = full_rpe < baseline_rpe
        result["ape_wins"] += int(ape_win)
        result["rpe_wins"] += int(rpe_win)
        result["double_wins"] += int(ape_win and rpe_win)
    return result


def summarize_group(name: str, path: Path) -> dict[str, object]:
    with path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    indexed: dict[tuple[str, int], dict[str, str]] = {}
    for row in rows:
        role = row["role"]
        if role not in ROLES:
            raise SystemExit(f"unexpected role {role!r} in {path}")
        key = (role, int(row["repeat"]))
        if key in indexed:
            raise SystemExit(f"duplicate role/repeat {key} in {path}")
        indexed[key] = row

    role_rows = {
        role: [row for (candidate, _), row in indexed.items() if candidate == role]
        for role in ROLES
    }
    repeat_sets = {
        role: {repeat for candidate, repeat in indexed if candidate == role} for role in ROLES
    }
    if len({frozenset(repeats) for repeats in repeat_sets.values()}) != 1:
        raise SystemExit(f"role repeat sets differ in {path}: {repeat_sets}")

    summary: dict[str, object] = {
        "group": name,
        "runs_per_role": len(role_rows["full"]),
        "full_seed_phase": common_value(
            [row.get("seed_phase") for row in role_rows["full"]]
        ),
        "full_seed_phase_summary_logged_runs": sum(
            int(optional_float(row.get("seed_phase_summary_logged")) or 0)
            for row in role_rows["full"]
        ),
        "full_seed_event_frames_logged_runs": sum(
            int(optional_float(row.get("seed_event_frames_logged")) or 0)
            for row in role_rows["full"]
        ),
        "full_seed_min_consecutive_ok_frames_median": median(
            [
                optional_float(row.get("seed_min_consecutive_ok_frames"))
                for row in role_rows["full"]
            ]
        ),
        "full_attempted_seeds_median": median(
            [optional_float(row.get("attempted_seeds")) for row in role_rows["full"]]
        ),
        "full_accepted_seeds_median": median(
            [optional_float(row.get("accepted_seeds")) for row in role_rows["full"]]
        ),
    }
    for field in (
        "pre_init_attempted_seeds",
        "pre_init_accepted_seeds",
        "post_init_attempted_seeds",
        "post_init_accepted_seeds",
        "phase_skipped_seeds",
        "first_injection_frame",
        "last_injection_frame",
        "max_consecutive_ok_frames",
    ):
        summary[f"full_{field}_median"] = median(
            [optional_float(row.get(field)) for row in role_rows["full"]]
        )
    for role in ROLES:
        coverage = median(
            [optional_float(row.get("coverage_ratio")) for row in role_rows[role]]
        )
        ape = median([optional_float(row.get("ape_rmse_m")) for row in role_rows[role]])
        rpe = median([optional_float(row.get("rpe_rmse_m")) for row in role_rows[role]])
        summary[f"{role}_coverage_median"] = coverage
        summary[f"{role}_ape_rmse_median_m"] = ape
        summary[f"{role}_rpe_rmse_median_m"] = rpe
        summary[f"{role}_failed_runs"] = sum(
            1 for row in role_rows[role] if row.get("status", "ok") != "ok"
        )

    summary["full_vs_orb_ape_median_gain_pct"] = relative_gain(
        summary["orb_only_ape_rmse_median_m"], summary["full_ape_rmse_median_m"]
    )
    summary["full_vs_orb_rpe_median_gain_pct"] = relative_gain(
        summary["orb_only_rpe_rmse_median_m"], summary["full_rpe_rmse_median_m"]
    )
    summary["full_vs_drop_ape_median_gain_pct"] = relative_gain(
        summary["drop_ape_rmse_median_m"], summary["full_ape_rmse_median_m"]
    )
    summary["full_vs_drop_rpe_median_gain_pct"] = relative_gain(
        summary["drop_rpe_rmse_median_m"], summary["full_rpe_rmse_median_m"]
    )
    for label, role in (("orb", "orb_only"), ("drop", "drop")):
        paired = paired_stats(indexed, role)
        for metric, value in paired.items():
            summary[f"full_vs_{label}_{metric}"] = value
    return summary


def main() -> int:
    args = parse_args()
    summaries: list[dict[str, object]] = []
    for item in args.group:
        if "=" not in item:
            raise SystemExit(f"invalid --group {item!r}; expected NAME=CSV")
        name, raw_path = item.split("=", 1)
        path = Path(raw_path).resolve()
        if not path.is_file():
            raise SystemExit(f"missing group CSV: {path}")
        summaries.append(summarize_group(name, path))

    output = Path(args.output_csv).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(summaries[0]))
        writer.writeheader()
        writer.writerows(summaries)
    print(f"wrote {len(summaries)} group summaries to {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
