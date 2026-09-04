#!/usr/bin/env python3
"""Summarize H07 backend q-schedule calibration runs."""

from __future__ import annotations

import argparse
import csv
import math
from pathlib import Path


DEFAULT_OUT_DIR = Path("/home/ma/AQUA-FE_WS/logs/agent_qi_backend_calibration")
EXISTING_QI_VINS_DIR = Path("/home/ma/AQUA-FE_WS/logs/agent_qi_vins")
SCHEDULE_ORDER = [
    "constq",
    "prior_q",
    "raw",
    "blend0.5",
    "blend0.7",
    "blend0.85",
    "clamp0.6",
    "clamp0.8",
]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR))
    args = parser.parse_args()

    out_dir = Path(args.out_dir)
    rows = collect_rows(out_dir)
    rows = add_comparisons(rows)
    write_csv(out_dir / "summary.csv", rows)
    report = make_report(rows, out_dir)
    (out_dir / "report.md").write_text(report, encoding="utf-8")
    print(f"wrote {out_dir / 'summary.csv'}")
    print(f"wrote {out_dir / 'report.md'}")
    return 0


def collect_rows(out_dir: Path) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    prior_q = load_prior_q_row()
    if prior_q is not None:
        rows.append(prior_q)
    for run_dir in sorted(out_dir.glob("h07_1660_1950_*")):
        if not run_dir.is_dir() or run_dir.name.endswith("_source"):
            continue
        bag_stats = read_single_csv(run_dir / "bag_stats.csv")
        schedule = str(bag_stats.get("schedule") or run_dir.name.replace("h07_1660_1950_", ""))
        ape, metric_source = load_ape_metrics(run_dir, schedule)
        row: dict[str, object] = {
            "schedule": schedule,
            "run_dir": str(run_dir),
            "vins_ran": "se3_ape_rmse_m" in ape,
            "metric_source": metric_source,
            "matched": ape.get("matched", ""),
            "se3_ape_rmse_m": ape.get("se3_ape_rmse_m", ""),
            "se3_ape_median_m": ape.get("se3_ape_median_m", ""),
            "rpe_trans_rmse_m": ape.get("rpe_trans_rmse_m", ""),
            "rpe_trans_median_m": ape.get("rpe_trans_median_m", ""),
            "output_coverage_ratio": ape.get("output_coverage_ratio", ""),
            "init_success": ape.get("init_success", ""),
            "tracking_lost_count_proxy": ape.get("tracking_lost_count_proxy", ""),
            "log_linear_solver_failures": ape.get("log_linear_solver_failures", ""),
            "backend_q_min": bag_stats.get("backend_q_min", ""),
            "backend_q_median": bag_stats.get("backend_q_median", ""),
            "backend_q_mean": bag_stats.get("backend_q_mean", ""),
            "backend_q_p90": bag_stats.get("backend_q_p90", ""),
            "sigma_median": bag_stats.get("sigma_median", ""),
            "feature_frames": bag_stats.get("feature_frames", ""),
            "feature_points": bag_stats.get("feature_points", ""),
            "points_per_frame_median": bag_stats.get("points_per_frame_median", ""),
        }
        rows.append(row)
    return sorted(rows, key=schedule_sort_key)


def load_ape_metrics(run_dir: Path, schedule: str) -> tuple[dict[str, object], str]:
    local = parse_key_value_file(run_dir / "ape.txt")
    if "se3_ape_rmse_m" in local:
        return local, "calibration_vins"
    if schedule == "constq":
        existing = parse_key_value_file(EXISTING_QI_VINS_DIR / "h07_1660_1950_constq" / "ape.txt")
        if "se3_ape_rmse_m" in existing:
            return existing, "existing_constq"
    return {}, "projected_only"


def load_prior_q_row() -> dict[str, object] | None:
    run_dir = EXISTING_QI_VINS_DIR / "h07_1660_1950_q"
    ape = parse_key_value_file(run_dir / "ape.txt")
    if "se3_ape_rmse_m" not in ape:
        return None
    metrics = read_frontend_metrics(run_dir / "frontend_metrics.csv")
    bag_stats = read_existing_bag_stats(run_dir / "features.bag")
    row: dict[str, object] = {
        "schedule": "prior_q",
        "run_dir": str(run_dir),
        "vins_ran": True,
        "metric_source": "existing_prior_q",
        "matched": ape.get("matched", ""),
        "se3_ape_rmse_m": ape.get("se3_ape_rmse_m", ""),
        "se3_ape_median_m": ape.get("se3_ape_median_m", ""),
        "rpe_trans_rmse_m": ape.get("rpe_trans_rmse_m", ""),
        "rpe_trans_median_m": ape.get("rpe_trans_median_m", ""),
        "output_coverage_ratio": ape.get("output_coverage_ratio", ""),
        "init_success": ape.get("init_success", ""),
        "tracking_lost_count_proxy": ape.get("tracking_lost_count_proxy", ""),
        "log_linear_solver_failures": ape.get("log_linear_solver_failures", ""),
        "backend_q_min": bag_stats.get("backend_q_min", ""),
        "backend_q_median": bag_stats.get("backend_q_median", metrics.get("backend_q_median", "")),
        "backend_q_mean": bag_stats.get("backend_q_mean", ""),
        "backend_q_p90": bag_stats.get("backend_q_p90", ""),
        "sigma_median": bag_stats.get("sigma_median", ""),
        "feature_frames": metrics.get("feature_frames", bag_stats.get("feature_frames", "")),
        "feature_points": bag_stats.get("feature_points", ""),
        "points_per_frame_median": bag_stats.get("points_per_frame_median", metrics.get("points_per_frame_median", "")),
    }
    return row


def add_comparisons(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    raw = find_raw_baseline(rows)
    raw_projected = next((row for row in rows if row.get("schedule") == "raw"), None)
    const = next((row for row in rows if row.get("schedule") == "constq"), None)
    raw_ape = as_float(raw.get("se3_ape_rmse_m")) if raw else None
    raw_rpe = as_float(raw.get("rpe_trans_rmse_m")) if raw else None
    const_ape = as_float(const.get("se3_ape_rmse_m")) if const else None
    const_rpe = as_float(const.get("rpe_trans_rmse_m")) if const else None
    raw_gap_ape = None if raw_ape is None or const_ape is None else max(0.0, raw_ape - const_ape)
    raw_gap_rpe = None if raw_rpe is None or const_rpe is None else max(0.0, raw_rpe - const_rpe)

    for row in rows:
        schedule = row.get("schedule")
        stable = is_stable(row)
        ape = as_float(row.get("se3_ape_rmse_m"))
        rpe = as_float(row.get("rpe_trans_rmse_m"))
        if schedule in {"raw", "prior_q"} and row is raw:
            row["improves_over_raw"] = "baseline"
        elif row.get("metric_source") == "projected_only":
            row["improves_over_raw"] = "not run"
        elif raw_ape is None or raw_rpe is None or ape is None or rpe is None:
            row["improves_over_raw"] = "n/a"
        elif stable and ape < raw_ape and rpe <= raw_rpe * 1.02:
            row["improves_over_raw"] = "yes"
        else:
            row["improves_over_raw"] = "no"

        if schedule == "constq":
            row["approaches_constq"] = "baseline"
        elif row.get("metric_source") == "projected_only":
            row["approaches_constq"] = projected_constq_note(row, raw_projected or raw, const)
        elif const_ape is None or const_rpe is None or ape is None or rpe is None:
            row["approaches_constq"] = "n/a"
        elif no_worse_than_const(ape, rpe, const_ape, const_rpe):
            row["approaches_constq"] = "yes"
        elif (
            raw_gap_ape is not None
            and raw_gap_rpe is not None
            and raw_gap_ape > 1e-9
            and raw_gap_rpe > 1e-9
            and max(0.0, ape - const_ape) <= 0.5 * raw_gap_ape
            and max(0.0, rpe - const_rpe) <= 0.5 * raw_gap_rpe
        ):
            row["approaches_constq"] = "partial"
        else:
            row["approaches_constq"] = "no"
    return rows


def make_report(rows: list[dict[str, object]], out_dir: Path) -> str:
    raw = find_raw_baseline(rows)
    const = next((row for row in rows if row.get("schedule") == "constq"), None)
    decision = make_decision(rows, raw, const)
    table_rows = [
        {
            "schedule": row.get("schedule", ""),
            "q_med": row.get("backend_q_median", ""),
            "q_min": row.get("backend_q_min", ""),
            "APE_RMSE_m": row.get("se3_ape_rmse_m", ""),
            "APE_med_m": row.get("se3_ape_median_m", ""),
            "RPE_RMSE_m": row.get("rpe_trans_rmse_m", ""),
            "matched": row.get("matched", ""),
            "coverage": row.get("output_coverage_ratio", ""),
            "init/lost": init_lost(row),
            "metric_src": row.get("metric_source", ""),
            "improves_raw": row.get("improves_over_raw", ""),
            "approaches_constq": row.get("approaches_constq", ""),
        }
        for row in rows
    ]
    metric_count = sum(1 for row in rows if bool(row.get("vins_ran")))
    if metric_count == len(rows):
        metric_note = "All listed schedules have VINS metrics."
    else:
        metric_note = "Some new rows are q/sigma projection only and need VINS before performance claims."
    lines = [
        "# q_i Backend Calibration Report",
        "",
        "## Scope",
        "",
        "This run keeps the frontend and VINS C++ backend fixed. A raw-quality external-feature bag is exported once, then only the PointCloud `quality` and `sigma` channels are rewritten for each backend schedule.",
        "",
        f"- Dataset/window: AQUALOC H07 `harbor07_1660_1950.bag`, short local window.",
        "- Schedules: `constq`, raw frontend q, alpha blends `alpha + (1-alpha)q`, and raw-q clamps.",
        "- The previous H07 `q` ablation is listed as `prior_q`: it used the exporter's then-default backend reliability path, not necessarily raw frontend q.",
        "- Backend effect: VINS reads `quality`; `sigma` is kept consistent as `1/sqrt(max(0.05, q_backend))` for channel diagnostics.",
        "- APE/RPE source: `calibration_vins` means this script ran VINS; `existing_prior_q`/`existing_constq` reuse the prior H07 ablation; `projected_only` means only bag-channel q/sigma statistics were computed.",
        f"- VINS metric rows available: {metric_count}/{len(rows)}. {metric_note}",
        "",
        "## Results",
        "",
        markdown_table(table_rows),
        "",
        "## Decision",
        "",
        decision,
        "",
        "## Reproduction",
        "",
        "```bash",
        "cd /home/ma/AQUA-FE_WS",
        "OUT_ROOT=logs/agent_qi_backend_calibration RUN_VINS=0 KEEP_BAGS=0 PORT_BASE=11451 ./scripts/agent_qi_calibration_h07_run.sh",
        "python3 scripts/agent_qi_calibration_report.py --out-dir logs/agent_qi_backend_calibration",
        "```",
        "",
        "Set `RUN_VINS=1` to run the schedules through VINS on ports starting at `PORT_BASE`. Intermediate feature bags are removed by default after `bag_stats.csv` and any `ape.txt` are written; set `KEEP_BAGS=1` to retain them for inspection.",
        "",
        "Claim boundary: this is a short H07 backend smoke test. `blend0.85` is a calibration candidate for further validation, not yet a general trajectory-improvement claim.",
        "",
        f"Artifacts live under `{out_dir}`.",
    ]
    return "\n".join(lines) + "\n"


def make_decision(
    rows: list[dict[str, object]],
    raw: dict[str, object] | None,
    const: dict[str, object] | None,
) -> str:
    if not rows:
        return "No calibration rows were found; q needs offline calibration before a backend schedule can be recommended."
    if raw is None or const is None:
        return "The raw-q and constq baselines were not both available, so no schedule is recommended."
    raw_ape = as_float(raw.get("se3_ape_rmse_m"))
    raw_rpe = as_float(raw.get("rpe_trans_rmse_m"))
    const_ape = as_float(const.get("se3_ape_rmse_m"))
    const_rpe = as_float(const.get("rpe_trans_rmse_m"))
    if raw_ape is None or raw_rpe is None or const_ape is None or const_rpe is None:
        return "The VINS metrics are incomplete, so no schedule is recommended."

    candidates = [
        row
        for row in rows
        if row.get("schedule") not in {"constq", "raw", "prior_q"}
        and is_stable(row)
        and as_float(row.get("se3_ape_rmse_m")) is not None
        and as_float(row.get("rpe_trans_rmse_m")) is not None
    ]
    const_like = [
        row
        for row in candidates
        if no_worse_than_const(
            as_float(row.get("se3_ape_rmse_m")),
            as_float(row.get("rpe_trans_rmse_m")),
            const_ape,
            const_rpe,
        )
    ]
    if const_like:
        best = min(const_like, key=lambda row: (as_float(row.get("se3_ape_rmse_m")), as_float(row.get("rpe_trans_rmse_m"))))
        return (
            f"`{best['schedule']}` is the conservative candidate from this H07 smoke test: "
            "it is stable and stays within the constq margin while preserving calibrated quality variation. "
            "Treat this as a tunable backend calibration setting that needs longer-window and cross-window checks before promotion."
        )

    clearly_better_raw = [
        row
        for row in candidates
        if as_float(row.get("se3_ape_rmse_m")) <= 0.85 * raw_ape
        and as_float(row.get("rpe_trans_rmse_m")) <= 0.85 * raw_rpe
    ]
    if clearly_better_raw:
        best = min(
            clearly_better_raw,
            key=lambda row: (as_float(row.get("se3_ape_rmse_m")), as_float(row.get("rpe_trans_rmse_m"))),
        )
        return (
            f"`{best['schedule']}` is clearly safer than raw q without instability, but it does not reach the constq margin. "
            "Treat it as an experimental fallback and do offline calibration before making it the default."
        )
    return (
        "No non-constant schedule has VINS evidence showing it is both stable and convincingly close to constq or clearly better than raw q. "
        "Do not recommend a backend q schedule yet; q needs offline calibration."
    )


def no_worse_than_const(
    ape: float | None,
    rpe: float | None,
    const_ape: float,
    const_rpe: float,
) -> bool:
    if ape is None or rpe is None:
        return False
    ape_margin = max(0.03, 0.10 * const_ape)
    rpe_margin = max(0.02, 0.10 * const_rpe)
    return ape <= const_ape + ape_margin and rpe <= const_rpe + rpe_margin


def find_raw_baseline(rows: list[dict[str, object]]) -> dict[str, object] | None:
    raw = next((row for row in rows if row.get("schedule") == "raw" and row.get("vins_ran")), None)
    if raw is not None:
        return raw
    return next((row for row in rows if row.get("schedule") == "prior_q" and row.get("vins_ran")), None)


def is_stable(row: dict[str, object]) -> bool:
    init_success = as_float(row.get("init_success"))
    lost = as_float(row.get("tracking_lost_count_proxy"))
    failures = as_float(row.get("log_linear_solver_failures"))
    return init_success == 1.0 and (lost is not None and lost <= 0.0) and (failures is None or failures <= 0.0)


def projected_constq_note(
    row: dict[str, object],
    raw: dict[str, object] | None,
    const: dict[str, object] | None,
) -> str:
    q_med = as_float(row.get("backend_q_median"))
    raw_med = as_float(raw.get("backend_q_median")) if raw else None
    const_med = as_float(const.get("backend_q_median")) if const else 1.0
    if q_med is None:
        return "not run"
    if const_med is None:
        const_med = 1.0
    if raw_med is None:
        return "q-only"
    raw_gap = abs(const_med - raw_med)
    if raw_gap <= 1e-9:
        return "q-only"
    rel_gap = abs(const_med - q_med) / raw_gap
    if rel_gap <= 0.25:
        return "q-close"
    if rel_gap <= 0.50:
        return "q-partial"
    return "q-far"


def init_lost(row: dict[str, object]) -> str:
    init = row.get("init_success", "")
    lost = row.get("tracking_lost_count_proxy", "")
    if init == "" and lost == "":
        return "n/a"
    return f"{fmt(init)}/{fmt(lost)}"


def read_single_csv(path: Path) -> dict[str, object]:
    if not path.exists():
        return {}
    with path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    if not rows:
        return {}
    return {key: parse_scalar(value) for key, value in rows[0].items()}


def read_frontend_metrics(path: Path) -> dict[str, object]:
    if not path.exists():
        return {}
    with path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    if not rows:
        return {}
    exported = [as_float(row.get("exported_features")) for row in rows]
    backend_q = [as_float(row.get("median_backend_quality")) for row in rows]
    exported = [item for item in exported if item is not None]
    backend_q = [item for item in backend_q if item is not None]
    out: dict[str, object] = {"feature_frames": len(rows)}
    if exported:
        out["points_per_frame_median"] = median(exported)
    if backend_q:
        out["backend_q_median"] = median(backend_q)
    return out


def read_existing_bag_stats(path: Path) -> dict[str, object]:
    if not path.exists():
        return {}
    try:
        import numpy as np
        import rosbag
    except Exception:
        return {}
    qualities: list[float] = []
    sigmas: list[float] = []
    counts: list[int] = []
    with rosbag.Bag(str(path)) as bag:
        for _, msg, _ in bag.read_messages(topics=["/feature_tracker/feature"]):
            channel_map = {channel.name: channel.values for channel in msg.channels}
            qualities.extend(float(item) for item in channel_map.get("quality", []))
            sigmas.extend(float(item) for item in channel_map.get("sigma", []))
            counts.append(len(msg.points))
    if not qualities:
        return {"feature_points": 0, "feature_frames": len(counts)}
    q = np.asarray(qualities, dtype=np.float64)
    sigma = np.asarray(sigmas, dtype=np.float64)
    count_arr = np.asarray(counts, dtype=np.float64)
    return {
        "feature_frames": len(counts),
        "feature_points": int(len(q)),
        "points_per_frame_median": float(np.median(count_arr)) if len(count_arr) else "",
        "backend_q_min": float(np.min(q)),
        "backend_q_median": float(np.median(q)),
        "backend_q_mean": float(np.mean(q)),
        "backend_q_p90": float(np.percentile(q, 90)),
        "sigma_median": float(np.median(sigma)) if len(sigma) else "",
    }


def median(values: list[float]) -> float:
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2:
        return float(ordered[mid])
    return float((ordered[mid - 1] + ordered[mid]) * 0.5)


def parse_key_value_file(path: Path) -> dict[str, object]:
    out: dict[str, object] = {}
    if not path.exists():
        return out
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        out[key] = parse_scalar(value)
    return out


def parse_scalar(value: object) -> object:
    if value is None:
        return ""
    text = str(value).strip()
    if text == "":
        return ""
    try:
        return float(text)
    except ValueError:
        return text


def as_float(value: object) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    return number


def schedule_sort_key(row: dict[str, object]) -> tuple[int, str]:
    schedule = str(row.get("schedule", ""))
    try:
        return (SCHEDULE_ORDER.index(schedule), schedule)
    except ValueError:
        return (len(SCHEDULE_ORDER), schedule)


def write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fieldnames = list(rows[0].keys())
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def markdown_table(rows: list[dict[str, object]]) -> str:
    if not rows:
        return "(empty)"
    headers = list(rows[0].keys())
    body = [[fmt(row.get(header, "")) for header in headers] for row in rows]
    widths = [max(len(header), *(len(row[idx]) for row in body)) for idx, header in enumerate(headers)]
    header_line = "| " + " | ".join(header.ljust(widths[idx]) for idx, header in enumerate(headers)) + " |"
    sep = "| " + " | ".join("-" * widths[idx] for idx in range(len(headers))) + " |"
    body_lines = [
        "| " + " | ".join(row[idx].ljust(widths[idx]) for idx in range(len(headers))) + " |"
        for row in body
    ]
    return "\n".join([header_line, sep] + body_lines)


def fmt(value: object) -> str:
    if isinstance(value, float):
        if math.isnan(value):
            return "nan"
        if abs(value) >= 100:
            return f"{value:.1f}"
        return f"{value:.6f}"
    return str(value)


if __name__ == "__main__":
    raise SystemExit(main())
