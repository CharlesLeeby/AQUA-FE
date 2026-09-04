#!/usr/bin/env python3
"""Build the evidence-first analysis bundle for the frozen HFNet v6 roster.

This script is descriptive by design.  The roster contains outcome-selected
historical windows and only one window authorizes common-support accuracy, so
the script refuses inferential statistics and never converts failed runs to a
numeric error value.
"""

from __future__ import annotations

import csv
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Iterable, Mapping

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
from matplotlib.patches import Patch


WORKSPACE = Path("/home/ma/AQUA-FE_WS")
PUBLISHED = Path(
    "/mnt/data/AQUA-FE_WS/logs/published_hfnet_slam_v6/"
    "samehistory_old_positive_roster_v2"
)
LOCK_BUNDLE = Path(
    "/mnt/data/AQUA-FE_WS/locks/"
    ".hfnet_v6_samehistory_positive_roster_execution_lock_v2.bundle-a1df6b5e08cc9230"
)
OUTPUT = WORKSPACE / "papers/hfnet_v6_samehistory_positive_roster_v2_analysis/analysis-output"
FIGURES = OUTPUT / "figures"
RUNABILITY_GATE = 0.70

STYLE = Path(
    "/home/ma/.codex/skills/scientific-toolkit/references/scientific-skills/"
    "scientific-visualization/assets/publication.mplstyle"
)

ROSTER: tuple[dict[str, str], ...] = (
    {
        "case_id": "a05_3300_3700",
        "display": "A05 3300-3700",
        "dataset": "AQUALOC",
        "failure_category": "zero_kf_or_no_track",
        "diagnosis": "3 init / 3 reset; no trajectory; pre-watchdog attempt ended by SIGTERM",
    },
    {
        "case_id": "a07_10800_11200",
        "display": "A07 10800-11200",
        "dataset": "AQUALOC",
        "failure_category": "zero_kf_or_no_track",
        "diagnosis": "no initialization; confirmed zero-KF save hang",
    },
    {
        "case_id": "a08_4500_4660",
        "display": "A08 4500-4660",
        "dataset": "AQUALOC",
        "failure_category": "zero_kf_or_no_track",
        "diagnosis": "initialized then reset; confirmed zero-KF save hang",
    },
    {
        "case_id": "a09_6000_6200",
        "display": "A09 6000-6200",
        "dataset": "AQUALOC",
        "failure_category": "partial_coverage",
        "diagnosis": "normal exit with a valid but sub-threshold trajectory fragment",
    },
    {
        "case_id": "fjord1_s83_d10",
        "display": "fjord1 s83/d10",
        "dataset": "NTNU",
        "failure_category": "zero_kf_or_no_track",
        "diagnosis": "no initialization; SIGSEGV after zero-KF save signature appeared",
    },
    {
        "case_id": "mclab1_s60_d15",
        "display": "mclab1 s60/d15",
        "dataset": "NTNU",
        "failure_category": "pass",
        "diagnosis": "normal exit; continuous trajectory passes the frozen gate",
    },
    {
        "case_id": "cirs_s575_d30",
        "display": "CIRS s575/d30",
        "dataset": "CIRS",
        "failure_category": "config_abort",
        "diagnosis": "startup abort: Camera.fps YAML node is not an integer",
    },
    {
        "case_id": "cirs_s900_d30",
        "display": "CIRS s900/d30",
        "dataset": "CIRS",
        "failure_category": "config_abort",
        "diagnosis": "startup abort: Camera.fps YAML node is not an integer",
    },
    {
        "case_id": "a02_7600_8000",
        "display": "A02 7600-8000",
        "dataset": "AQUALOC",
        "failure_category": "zero_kf_or_no_track",
        "diagnosis": "no initialization; confirmed zero-KF save hang",
    },
    {
        "case_id": "mclab2_s110_d10",
        "display": "mclab2 s110/d10",
        "dataset": "NTNU",
        "failure_category": "partial_coverage",
        "diagnosis": "3 init / 2 reset; only the final short trajectory fragment survived",
    },
)

EXPECTED_PASS_CASE = "mclab1_s60_d15"
EXPECTED_WATCHDOG_CASES = {row["case_id"] for row in ROSTER[1:]}
EXPECTED_ADJUDICATION_CASES = {row["case_id"] for row in ROSTER[1:]}


def require(condition: bool, code: str) -> None:
    if not condition:
        raise RuntimeError(code)


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def identity(path: Path) -> dict[str, Any]:
    require(path.is_file(), f"MISSING_FILE:{path}")
    data = path.read_bytes()
    return {"path": str(path), "sha256": sha256_bytes(data), "size_bytes": len(data)}


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    require(isinstance(value, dict), f"JSON_NOT_OBJECT:{path}")
    return value


def assert_identity(observed_path: Path, expected: Mapping[str, Any], label: str) -> None:
    observed = identity(observed_path)
    require(observed["path"] == str(expected.get("path")), f"{label}:PATH")
    require(observed["sha256"] == expected.get("sha256"), f"{label}:SHA256")
    require(observed["size_bytes"] == expected.get("size_bytes"), f"{label}:SIZE")


def pct(value: float) -> str:
    return f"{100.0 * value:.2f}%"


def fmt_metric(value: float) -> str:
    return f"{value:.6f}"


def markdown_table(headers: Iterable[str], rows: Iterable[Iterable[Any]]) -> str:
    header_values = [str(value) for value in headers]
    lines = [
        "| " + " | ".join(header_values) + " |",
        "| " + " | ".join("---" for _ in header_values) + " |",
    ]
    for row in rows:
        lines.append("| " + " | ".join(str(value) for value in row) + " |")
    return "\n".join(lines)


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text.strip() + "\n", encoding="utf-8")


def write_json(path: Path, value: Any) -> None:
    write_text(path, json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False))


def load_roster() -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    rows: list[dict[str, Any]] = []
    source_pins: dict[str, dict[str, Any]] = {}
    pass_cases: list[str] = []

    for roster_index, meta in enumerate(ROSTER, start=1):
        case_id = meta["case_id"]
        attempt = PUBLISHED / case_id / "attempt_001"
        result_path = attempt / "run_result.json"
        raw = read_json(result_path)
        require(raw.get("case_id") == case_id, f"CASE_ID_MISMATCH:{case_id}")
        require(
            raw.get("status") == "FAIL_SAMEHISTORY_COLDSTART_RUNABILITY",
            f"UNEXPECTED_RAW_STATUS:{case_id}",
        )
        require(
            raw.get("terminal_contract", {}).get("attempt_consumed") is True,
            f"ATTEMPT_NOT_CONSUMED:{case_id}",
        )
        require(
            raw.get("terminal_contract", {}).get("retry_after_pass_or_fail") is False,
            f"RETRY_NOT_FORBIDDEN:{case_id}",
        )

        source_pins[f"{case_id}:run_result"] = identity(result_path)
        for label in ("stdout", "stderr", "permanent_case_claim", "permanent_case_reservation"):
            expected = raw.get("pins", {}).get(label)
            require(isinstance(expected, dict), f"RAW_PIN_MISSING:{case_id}:{label}")
            path = Path(str(expected["path"]))
            assert_identity(path, expected, f"RAW_PIN:{case_id}:{label}")
            source_pins[f"{case_id}:{label}"] = identity(path)

        spec_path = LOCK_BUNDLE / "cases" / f"{case_id}.json"
        source_pins[f"{case_id}:case_spec"] = identity(spec_path)

        watchdog_path = PUBLISHED / "_zero_kf_save_hang_watchdog_v1" / f"{case_id}.json"
        watchdog: dict[str, Any] | None = None
        if case_id in EXPECTED_WATCHDOG_CASES:
            watchdog = read_json(watchdog_path)
            require(watchdog.get("case_id") == case_id, f"WATCHDOG_CASE_ID:{case_id}")
            require(
                watchdog.get("execution", {}).get("retry_performed") is False,
                f"WATCHDOG_RETRY:{case_id}",
            )
            source_pins[f"{case_id}:watchdog"] = identity(watchdog_path)
        else:
            require(not watchdog_path.exists(), f"A05_RETRO_WATCHDOG_FORBIDDEN:{case_id}")

        prestart_path = PUBLISHED / "_cache_contract_adjudication_v1" / f"{case_id}.prestart.json"
        adjudication_path = (
            PUBLISHED
            / "_cache_contract_adjudication_v1"
            / f"{case_id}.runability_adjudication.json"
        )
        adjudication: dict[str, Any] | None = None
        if case_id in EXPECTED_ADJUDICATION_CASES:
            require(prestart_path.is_file(), f"PRESTART_MISSING:{case_id}")
            adjudication = read_json(adjudication_path)
            require(adjudication.get("case_id") == case_id, f"ADJUDICATION_CASE_ID:{case_id}")
            require(adjudication.get("status") in {"PASS", "FAIL"}, f"ADJUDICATION_STATUS:{case_id}")
            source_pins[f"{case_id}:prestart"] = identity(prestart_path)
            source_pins[f"{case_id}:adjudication"] = identity(adjudication_path)
        else:
            require(not prestart_path.exists(), f"A05_RETRO_PRESTART_FORBIDDEN:{case_id}")
            require(not adjudication_path.exists(), f"A05_RETRO_ADJUDICATION_FORBIDDEN:{case_id}")

        effective_status = adjudication.get("status") if adjudication else "FAIL"
        if effective_status == "PASS":
            pass_cases.append(case_id)

        support = raw.get("support", {})
        log_support = support.get("log", {})
        trajectory = support.get("trajectory", {})
        keyframes = support.get("keyframes", {})
        coverage = trajectory.get("coverage_fraction")
        coverage_numeric = float(coverage) if coverage is not None else 0.0
        require(0.0 <= coverage_numeric <= 1.0, f"COVERAGE_RANGE:{case_id}")
        trajectory_pose_count = int(trajectory.get("pose_count") or 0)
        keyframe_pose_count = int(keyframes.get("pose_count") or 0)
        map_keyframes = log_support.get("map_keyframes") or []
        final_atlas_keyframes = int(map_keyframes[-1]) if map_keyframes else 0
        require(
            keyframe_pose_count == final_atlas_keyframes,
            f"KEYFRAME_ATLAS_DISAGREEMENT:{case_id}",
        )

        stdout_path = Path(str(raw["pins"]["stdout"]["path"]))
        stderr_path = Path(str(raw["pins"]["stderr"]["path"]))
        stdout = stdout_path.read_text(encoding="utf-8", errors="replace")
        stderr = stderr_path.read_text(encoding="utf-8", errors="replace")
        combined_logs = stdout + "\n" + stderr
        if meta["failure_category"] == "config_abort":
            require(
                "Camera.fps parameter must be an integer number, aborting" in combined_logs,
                f"CIRS_FPS_ABORT_NOT_PROVEN:{case_id}",
            )
        if case_id in {"a07_10800_11200", "a08_4500_4660", "a02_7600_8000"}:
            require("Map 0 has 0 KFs" in stdout, f"ZERO_KF_LOG_MISSING:{case_id}")

        raw_returncode = int(raw.get("execution", {}).get("raw_returncode"))
        watchdog_status = watchdog.get("status") if watchdog else "NOT_APPLICABLE_PRE_ADDENDUM"
        row = {
            "roster_index": roster_index,
            "case_id": case_id,
            "display": meta["display"],
            "dataset": meta["dataset"],
            "history": raw.get("claim_boundary", {}).get("history"),
            "outcome_selected_historical_positive": raw.get("claim_boundary", {}).get(
                "outcome_selected_historical_positive"
            ),
            "camera_count": int(support.get("camera_count") or 0),
            "initialization_count": int(log_support.get("initialization_count") or 0),
            "active_map_reset_count": int(log_support.get("active_map_reset_count") or 0),
            "trajectory_pose_count": trajectory_pose_count,
            "trajectory_coverage_fraction": coverage_numeric,
            "trajectory_coverage_available": coverage is not None,
            "keyframe_pose_count": keyframe_pose_count,
            "final_atlas_keyframes": final_atlas_keyframes,
            "raw_returncode": raw_returncode,
            "raw_status": raw.get("status"),
            "effective_runability_status": effective_status,
            "adjudication_status": (
                adjudication.get("adjudication_status") if adjudication else "PRE_ADDENDUM_NO_RETRO_ADJUDICATION"
            ),
            "watchdog_status": watchdog_status,
            "failure_category": meta["failure_category"],
            "diagnosis": meta["diagnosis"],
            "accuracy_status": "AUTHORIZED" if case_id == EXPECTED_PASS_CASE else "NA",
            "ranking_authorized": case_id == EXPECTED_PASS_CASE,
            "retry_permitted": False,
        }
        rows.append(row)

    require(pass_cases == [EXPECTED_PASS_CASE], f"UNEXPECTED_PASS_SET:{pass_cases}")
    require(len(rows) == 10, f"ROSTER_COUNT:{len(rows)}")
    return rows, source_pins


def load_accuracy(source_pins: dict[str, dict[str, Any]]) -> dict[str, Any]:
    root = PUBLISHED / "_accuracy_analysis_v2" / EXPECTED_PASS_CASE
    result_path = root / "attempt_001" / "accuracy_result.json"
    terminal_path = root / "terminal_receipt.json"
    claim_path = (
        PUBLISHED
        / "_accuracy_analysis_v2"
        / "_claims"
        / f"{EXPECTED_PASS_CASE}.start_once"
    )
    lock_path = PUBLISHED / "_accuracy_execution_locks_v2" / f"{EXPECTED_PASS_CASE}.json"
    bridge_path = (
        PUBLISHED
        / "_accuracy_execution_locks_v2"
        / f"{EXPECTED_PASS_CASE}.hfnet_timestamp_bridge_receipt.json"
    )
    evo_path = root / "attempt_001" / "evo_crosscheck.json"

    for label, path in (
        ("accuracy_result", result_path),
        ("accuracy_terminal", terminal_path),
        ("accuracy_claim", claim_path),
        ("accuracy_execution_lock", lock_path),
        ("accuracy_timestamp_bridge", bridge_path),
        ("accuracy_evo_crosscheck", evo_path),
    ):
        source_pins[f"{EXPECTED_PASS_CASE}:{label}"] = identity(path)

    result = read_json(result_path)
    terminal = read_json(terminal_path)
    require(result.get("status") == "FORMAL_ACCURACY_ANALYSIS_TERMINAL", "ACCURACY_RESULT_STATUS")
    require(terminal.get("status") == "PASS_TERMINAL_RECEIPT", "ACCURACY_TERMINAL_STATUS")
    require(terminal.get("accuracy_numeric_authorized") is True, "ACCURACY_NOT_AUTHORIZED")
    require(terminal.get("ranking_authorized") is True, "RANKING_NOT_AUTHORIZED")

    scientific = result.get("scientific_result", {})
    require(scientific.get("case_id") == EXPECTED_PASS_CASE, "ACCURACY_CASE_ID")
    require(scientific.get("accuracy_status") == "ACCURACY_AUTHORIZED_EVO_PASS", "ACCURACY_STATUS")
    claim = scientific.get("claim_boundary", {})
    require(claim.get("accuracy_numeric_authorized") is True, "SCIENTIFIC_NUMERIC_AUTHORITY")
    require(claim.get("ranking_authorized") is True, "SCIENTIFIC_RANKING_AUTHORITY")
    require(claim.get("significance_test_performed") is False, "UNEXPECTED_SIGNIFICANCE_TEST")
    require(claim.get("sim3_used") is False, "SIM3_FORBIDDEN")

    support = scientific.get("support", {})
    require(support.get("gate_open") is True, "COMMON_SUPPORT_GATE_CLOSED")
    require(support.get("matched_count") == 139, "COMMON_SUPPORT_COUNT")
    require(support.get("rpe_pair_count") == 129, "RPE_PAIR_COUNT")
    require(math.isclose(float(support.get("common_coverage")), 139 / 150), "COMMON_COVERAGE")
    require(math.isclose(float(support.get("common_span_s")), 13.8), "COMMON_SPAN")

    evo = scientific.get("evo_crosscheck", {})
    require(evo.get("status") == "PASS", "EVO_CROSSCHECK_STATUS")
    require(evo.get("failures") == [], "EVO_CROSSCHECK_FAILURES")
    require(evo.get("accuracy_numeric_authorized") is True, "EVO_NUMERIC_AUTHORITY")
    require(evo.get("ranking_authorized") is True, "EVO_RANKING_AUTHORITY")

    reference = scientific.get("reference_disclosure", {})
    require(reference.get("role") == "non_independent_proxy_reference", "REFERENCE_ROLE")
    require(reference.get("is_independent_ground_truth") is False, "REFERENCE_NOT_PROXY")
    require(
        reference.get("common_grid_samples_are_independent_replicates") is False,
        "COMMON_GRID_INDEPENDENCE",
    )

    alignment = scientific.get("alignment_audit", {})
    require(alignment.get("status") == "PASS", "ALIGNMENT_AUDIT_STATUS")
    require(alignment.get("fixed_scale") == 1.0, "ALIGNMENT_SCALE")
    require(alignment.get("independent_alignment_per_arm") is True, "ALIGNMENT_ARM_INDEPENDENCE")
    require(alignment.get("sim3_used") is False, "ALIGNMENT_SIM3")
    for method in ("klt", "learned_plus_klt", "hfnet"):
        require(
            alignment.get("per_arm", {}).get(method, {}).get("method")
            == "KABSCH_PROPER_SE3_FIXED_SCALE_1",
            f"ALIGNMENT_METHOD:{method}",
        )

    metrics = scientific.get("metrics", {})
    methods = ("klt", "learned_plus_klt", "hfnet")
    require(set(metrics) == set(methods), f"METRIC_ARMS:{sorted(metrics)}")
    table: list[dict[str, Any]] = []
    display = {"klt": "KLT", "learned_plus_klt": "Learned+KLT", "hfnet": "HFNet-SLAM"}
    for method in methods:
        ape = metrics[method]["translation_ape"]
        rpe = metrics[method]["translation_rpe_exact_1s"]
        require(ape.get("pose_count") == 139, f"APE_POSE_COUNT:{method}")
        require(rpe.get("pair_count") == 129, f"RPE_PAIR_COUNT:{method}")
        table.append(
            {
                "method": method,
                "display": display[method],
                "ape_rmse_m": float(ape["rmse_m"]),
                "ape_median_m": float(ape["median_m"]),
                "ape_max_m": float(ape["max_m"]),
                "ape_pose_count": int(ape["pose_count"]),
                "rpe_exact_1s_rmse_m": float(rpe["rmse_m"]),
                "rpe_exact_1s_median_m": float(rpe["median_m"]),
                "rpe_exact_1s_max_m": float(rpe["max_m"]),
                "rpe_pair_count": int(rpe["pair_count"]),
            }
        )

    lookup = {row["method"]: row for row in table}
    hfnet = lookup["hfnet"]
    reductions: dict[str, dict[str, float]] = {}
    for baseline in ("klt", "learned_plus_klt"):
        base = lookup[baseline]
        reductions[baseline] = {
            "ape_relative_error_reduction_fraction": 1.0 - hfnet["ape_rmse_m"] / base["ape_rmse_m"],
            "rpe_relative_error_reduction_fraction": (
                1.0 - hfnet["rpe_exact_1s_rmse_m"] / base["rpe_exact_1s_rmse_m"]
            ),
        }
    learned = lookup["learned_plus_klt"]
    klt = lookup["klt"]
    learned_vs_klt = {
        "ape_relative_error_reduction_fraction": 1.0 - learned["ape_rmse_m"] / klt["ape_rmse_m"],
        "rpe_relative_error_reduction_fraction": (
            1.0 - learned["rpe_exact_1s_rmse_m"] / klt["rpe_exact_1s_rmse_m"]
        ),
    }

    return {
        "case_id": EXPECTED_PASS_CASE,
        "accuracy_status": scientific["accuracy_status"],
        "common_support": {
            "matched_pose_count": support["matched_count"],
            "coverage_denominator": support["coverage_denominator"],
            "common_coverage_fraction": support["common_coverage"],
            "common_span_s": support["common_span_s"],
            "rpe_pair_count": support["rpe_pair_count"],
            "segment_count": support["segment_count"],
        },
        "metrics": table,
        "hfnet_relative_error_reductions": reductions,
        "learned_plus_klt_vs_klt": learned_vs_klt,
        "evo_crosscheck": {
            "status": evo["status"],
            "maximum_allowed_absolute_rmse_disagreement_m": evo[
                "maximum_allowed_absolute_rmse_disagreement_m"
            ],
            "failures": evo["failures"],
        },
        "reference_disclosure": {
            "role": reference["role"],
            "is_independent_ground_truth": reference["is_independent_ground_truth"],
            "common_grid_samples_are_independent_replicates": reference[
                "common_grid_samples_are_independent_replicates"
            ],
        },
        "alignment": {
            "method": "KABSCH_PROPER_SE3_FIXED_SCALE_1",
            "fixed_scale": alignment["fixed_scale"],
            "independent_alignment_per_arm": alignment["independent_alignment_per_arm"],
            "sim3_used": alignment["sim3_used"],
        },
        "inference": {
            "unit_of_analysis": "one outcome-selected historical window",
            "authorized_accuracy_window_count": 1,
            "significance_test_performed": False,
            "confidence_interval_computed": False,
            "standardized_effect_size_computed": False,
            "reason": "n=1 authorized window; no seed/repeat distribution",
        },
    }


def write_csv_files(rows: list[dict[str, Any]], accuracy: Mapping[str, Any]) -> None:
    roster_fields = [
        "roster_index",
        "case_id",
        "dataset",
        "camera_count",
        "effective_runability_status",
        "raw_returncode",
        "initialization_count",
        "active_map_reset_count",
        "trajectory_pose_count",
        "trajectory_coverage_fraction",
        "keyframe_pose_count",
        "watchdog_status",
        "adjudication_status",
        "failure_category",
        "accuracy_status",
        "diagnosis",
    ]
    with (OUTPUT / "roster-summary.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=roster_fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row[field] for field in roster_fields})

    metric_fields = [
        "method",
        "display",
        "ape_rmse_m",
        "ape_median_m",
        "ape_max_m",
        "ape_pose_count",
        "rpe_exact_1s_rmse_m",
        "rpe_exact_1s_median_m",
        "rpe_exact_1s_max_m",
        "rpe_pair_count",
    ]
    with (OUTPUT / "mclab1-common-support-metrics.csv").open(
        "w", encoding="utf-8", newline=""
    ) as handle:
        writer = csv.DictWriter(handle, fieldnames=metric_fields)
        writer.writeheader()
        for row in accuracy["metrics"]:
            writer.writerow({field: row[field] for field in metric_fields})


def save_figure(fig: plt.Figure, stem: str) -> None:
    for suffix in ("pdf", "svg"):
        fig.savefig(FIGURES / f"{stem}.{suffix}", bbox_inches="tight", pad_inches=0.04)
    fig.savefig(
        FIGURES / f"{stem}.png",
        dpi=600,
        bbox_inches="tight",
        pad_inches=0.04,
        facecolor="white",
    )


def make_figures(rows: list[dict[str, Any]], accuracy: Mapping[str, Any]) -> None:
    plt.style.use(str(STYLE))
    FIGURES.mkdir(parents=True, exist_ok=True)

    # Figure 1: frozen runability gate for every outcome-selected window.
    fig, ax = plt.subplots(figsize=(7.0, 4.2), constrained_layout=True)
    labels = [row["display"] for row in rows]
    values = [100.0 * row["trajectory_coverage_fraction"] for row in rows]
    pass_color = "#0072B2"
    fail_color = "#999999"
    colors = [pass_color if row["effective_runability_status"] == "PASS" else fail_color for row in rows]
    hatches = ["..." if row["effective_runability_status"] == "PASS" else "///" for row in rows]
    y_positions = list(range(len(rows)))
    bars = ax.barh(y_positions, values, color=colors, edgecolor="black", linewidth=0.55)
    for bar, hatch in zip(bars, hatches):
        bar.set_hatch(hatch)
    ax.axvline(
        100.0 * RUNABILITY_GATE,
        color="#D55E00",
        linestyle="--",
        linewidth=1.25,
        label="Frozen runability gate (70%)",
    )
    ax.set_yticks(y_positions, labels)
    ax.invert_yaxis()
    ax.set_xlim(0.0, 104.0)
    ax.set_xlabel("Valid contiguous trajectory coverage (%)")
    ax.set_ylabel("Outcome-selected historical window")
    ax.xaxis.grid(True, color="#DDDDDD", linewidth=0.5)
    ax.set_axisbelow(True)
    for y, value in zip(y_positions, values):
        ax.text(max(value + 1.0, 1.0), y, f"{value:.1f}%", va="center", ha="left", fontsize=7)
    ax.legend(
        handles=[
            Patch(facecolor=pass_color, edgecolor="black", hatch="...", label="PASS (1/10)"),
            Patch(facecolor=fail_color, edgecolor="black", hatch="///", label="FAIL / accuracy NA (9/10)"),
            Line2D([0], [0], color="#D55E00", linestyle="--", label="Frozen gate (70%)"),
        ],
        loc="lower right",
    )
    save_figure(fig, "figure-01-runability-coverage")
    plt.close(fig)

    # Figure 2: exact point estimates for the sole accuracy-authorized window.
    metric_rows = accuracy["metrics"]
    method_order = ["KLT", "Learned+KLT", "HFNet-SLAM"]
    lookup = {row["display"]: row for row in metric_rows}
    colors = ["#999999", "#E69F00", "#0072B2"]
    hatches = ["///", "xx", "..."]
    fig, axes = plt.subplots(1, 2, figsize=(7.0, 2.8), constrained_layout=True)
    panels = (
        (axes[0], "ape_rmse_m", "Translation APE RMSE (m)", "a"),
        (axes[1], "rpe_exact_1s_rmse_m", "Translation RPE RMSE at 1 s (m)", "b"),
    )
    for ax, field, ylabel, panel_label in panels:
        values = [float(lookup[name][field]) for name in method_order]
        bars = ax.bar(range(3), values, color=colors, edgecolor="black", linewidth=0.55)
        for bar, hatch in zip(bars, hatches):
            bar.set_hatch(hatch)
        ax.set_xticks(range(3), method_order, rotation=18, ha="right")
        ax.set_ylabel(ylabel)
        ax.set_ylim(0.0, max(values) * 1.22)
        ax.yaxis.grid(True, color="#DDDDDD", linewidth=0.5)
        ax.set_axisbelow(True)
        for index, value in enumerate(values):
            ax.text(index, value + max(values) * 0.025, f"{value:.3f}", ha="center", va="bottom", fontsize=7)
        ax.text(-0.12, 1.04, panel_label, transform=ax.transAxes, fontweight="bold", fontsize=10)
    fig.text(
        0.5,
        -0.09,
        (
            "mclab1 s60/d15; non-independent proxy reference; 139 poses / 129 pairs; "
            "independent fixed-scale SE(3) alignment.\n"
            "Single accuracy-authorized window (n=1); exact point estimates; no uncertainty bars or inference."
        ),
        ha="center",
        fontsize=7,
    )
    save_figure(fig, "figure-02-mclab1-common-support-errors")
    plt.close(fig)


def build_reports(rows: list[dict[str, Any]], accuracy: Mapping[str, Any]) -> None:
    pass_rows = [row for row in rows if row["effective_runability_status"] == "PASS"]
    fail_rows = [row for row in rows if row["effective_runability_status"] == "FAIL"]
    require(len(pass_rows) == 1 and len(fail_rows) == 9, "PASS_FAIL_COUNTS")

    category_counts: dict[str, int] = {}
    for row in rows:
        category_counts[row["failure_category"]] = category_counts.get(row["failure_category"], 0) + 1

    roster_table = markdown_table(
        ["Window", "Data", "Init/reset", "Poses", "Coverage", "KFs", "Effective", "Accuracy", "Diagnosis"],
        [
            [
                row["display"],
                row["dataset"],
                f'{row["initialization_count"]}/{row["active_map_reset_count"]}',
                row["trajectory_pose_count"],
                pct(row["trajectory_coverage_fraction"]),
                row["keyframe_pose_count"],
                row["effective_runability_status"],
                row["accuracy_status"],
                row["diagnosis"],
            ]
            for row in rows
        ],
    )

    metric_lookup = {row["method"]: row for row in accuracy["metrics"]}
    metric_table = markdown_table(
        ["Method", "APE RMSE (m)", "APE median (m)", "1 s RPE RMSE (m)", "RPE median (m)", "Support"],
        [
            [
                row["display"],
                fmt_metric(row["ape_rmse_m"]),
                fmt_metric(row["ape_median_m"]),
                fmt_metric(row["rpe_exact_1s_rmse_m"]),
                fmt_metric(row["rpe_exact_1s_median_m"]),
                "139 poses / 129 pairs",
            ]
            for row in accuracy["metrics"]
        ],
    )

    hfnet_vs_klt = accuracy["hfnet_relative_error_reductions"]["klt"]
    hfnet_vs_learned = accuracy["hfnet_relative_error_reductions"]["learned_plus_klt"]
    learned_vs_klt = accuracy["learned_plus_klt_vs_klt"]

    report = f"""
# HFNet-SLAM on the frozen old-positive roster: strict analysis

## Analysis question

在以前由 `Learned+KLT` 相对纯 KLT 产生正例的精确窗口上，外部学习特征视觉惯性 SLAM 系统 HFNet-SLAM 是否能够在**相同冷启动历史、相同窗口和相同时间支持**下运行，并在可比较时取得怎样的轨迹误差？

## Evidence boundary

- 固定名单：10 个**按既有结果选择**的历史正例窗口；这不是随机样本。
- 历史：每个窗口均为 `EXACT_WINDOW_COLD_START_NO_PRIOR_CAMERA_HISTORY`。
- 运行：每个 case 最多一次；失败后不重试、不替换、不改窗口。
- 运行性门：有效连续轨迹覆盖至少 70%；失败窗口的精度是 `NA`，不是 0。
- 精度：仅 mclab1 通过运行性门，并在 139 个共同位姿、129 个精确 1 s RPE 对、13.8 s 共同跨度上获得数值授权；独立 evo 交叉校验通过。
- 参考：mclab1 使用明确标注的 `non_independent_proxy_reference`，不是独立 ground truth；共同时间点也不是独立实验重复。
- 对齐：各臂独立进行 fixed-scale proper SE(3) 对齐，scale=1；未使用 Sim(3)。
- 推断：只有 1 个授权窗口、无重复种子，因此不做显著性检验、置信区间或标准化效应量。

## Exact roster outcome

{roster_table}

冻结名单的描述性通过数为 **1/10**。另外 9 项均保留为 FAIL/accuracy NA：5 项没有形成可用跟踪（含 0-KF 保存或 SIGSEGV），2 项只有低覆盖轨迹，2 项因 CIRS `Camera.fps` YAML 类型不兼容而在启动时 abort。这个 1/10 不能解释为总体成功概率，因为窗口是按既有 `Learned+KLT > KLT` 结果选择的。

![Frozen runability coverage](figures/figure-01-runability-coverage.svg)

## Authorized common-support comparison: mclab1 s60/d15

共同支持覆盖为 **{pct(float(accuracy['common_support']['common_coverage_fraction']))}**（139/150），共同跨度 13.8 s；误差越低越好。以下为相对非独立 proxy reference 的单窗口点估计，不是独立 ground-truth 误差或跨窗口均值。

{metric_table}

在这个窗口上：

- `Learned+KLT` 相对 KLT 的 APE/RPE 分别降低 **{pct(learned_vs_klt['ape_relative_error_reduction_fraction'])}** 和 **{pct(learned_vs_klt['rpe_relative_error_reduction_fraction'])}**，所以它确实仍是旧正例。
- HFNet-SLAM 相对 KLT 的 APE/RPE 分别降低 **{pct(hfnet_vs_klt['ape_relative_error_reduction_fraction'])}** 和 **{pct(hfnet_vs_klt['rpe_relative_error_reduction_fraction'])}**。
- HFNet-SLAM 相对 `Learned+KLT` 的 APE/RPE 分别降低 **{pct(hfnet_vs_learned['ape_relative_error_reduction_fraction'])}** 和 **{pct(hfnet_vs_learned['rpe_relative_error_reduction_fraction'])}**。

![mclab1 common-support errors](figures/figure-02-mclab1-common-support-errors.svg)

## What this changes

1. 已经满足“至少运行好一个别人的学习系统并在旧正例窗口上比较”的要求：mclab1 的 HFNet-SLAM 不仅可运行，而且两项 proxy-reference 误差点估计均低于 KLT 与 `Learned+KLT`。
2. 这项单窗口结果不支持“我们的 learned 前端在这些条件下一定优于外部 learned-feature SLAM system”的强表述。
3. 但 HFNet-SLAM 在冻结名单上只通过 1 项，说明**本批精确冷启动窗口中的运行性很脆弱**；这可以报告为 roster observation，不能外推为算法总体成功率。
4. 下一步若要形成论文级系统排名，必须先做一个**新的、事前修正配置且不按结果筛选**的 roster，并增加多次独立运行；不能追溯修改本批已经消耗的 case。

## Claim candidates

- Claim:
  - Source evidence: mclab1 accuracy v2 terminal + accuracy result + evo crosscheck。
  - Allowed wording: “On the frozen mclab1 s60/d15 window and 139-pose common support, HFNet-SLAM obtained lower proxy-reference APE and 1 s RPE RMSE than both KLT and Learned+KLT.”
  - Forbidden stronger wording: “HFNet-SLAM generally outperforms our method on underwater data.”
  - Uncertainty: n=1 accuracy-authorized window; no repeated runs.
  - Next check: preregistered, unscreened multi-window roster with repeated runs.
  - Decision: keep with a single-window qualifier.

- Claim:
  - Source evidence: 10 exactly-once runability receipts and the 70% frozen gate.
  - Allowed wording: “HFNet-SLAM passed the frozen runability gate in 1 of 10 outcome-selected cold-start windows.”
  - Forbidden stronger wording: “HFNet-SLAM has a 10% underwater success rate.”
  - Uncertainty: outcome-selected windows, mixed datasets, two CIRS configuration aborts.
  - Next check: prospective configuration-qualified roster.
  - Decision: keep as a roster audit result, not a population estimate.

## Files

- Exact rows: [roster-summary.csv](roster-summary.csv)
- Authorized metrics: [mclab1-common-support-metrics.csv](mclab1-common-support-metrics.csv)
- Statistical boundary: [stats-appendix.md](stats-appendix.md)
- Figure interpretation: [figure-catalog.md](figure-catalog.md)
- Machine-readable bundle: [analysis-bundle.json](analysis-bundle.json)
- Source hashes: [source-manifest.json](source-manifest.json)
"""

    stats = f"""
# Statistical appendix

## Design and unit of analysis

- Comparison unit: one exact historical window, not an individual frame.
- Roster size: 10 outcome-selected windows across AQUALOC, NTNU, and CIRS.
- Independent repeated runs/seeds: 1 per case by exactly-once design.
- Accuracy-authorized units: 1 window (mclab1 s60/d15).
- Metric direction: lower APE/RPE is better.
- Sim(3): not used.
- Reference: non-independent proxy, not independent ground truth.
- Alignment: independent proper fixed-scale SE(3) per arm, scale=1; no Sim(3).

Frames and RPE pairs within mclab1 are repeated temporal observations from the same run. They are used to define the deterministic metric population, not treated as 139 or 129 independent experimental replicates.

## Descriptive runability

{markdown_table(['Outcome', 'Count', 'Interpretation'], [
    ['PASS', 1, 'Passed the frozen 70% contiguous-coverage gate'],
    ['Zero-KF / no usable tracking', category_counts.get('zero_kf_or_no_track', 0), 'No accuracy number'],
    ['Partial coverage', category_counts.get('partial_coverage', 0), 'Valid fragment but below 70%; no accuracy number'],
    ['Configuration abort', category_counts.get('config_abort', 0), 'HFNet did not reach model execution; no accuracy number'],
])}

The observed roster pass fraction is 1/10. No binomial confidence interval is reported because these windows were selected by prior outcome and are not a random sample from a defined population.

## mclab1 point estimates

{metric_table}

Descriptive relative error reductions are computed as `1 - RMSE_method / RMSE_baseline`:

{markdown_table(['Contrast', 'APE reduction', '1 s RPE reduction'], [
    ['Learned+KLT vs KLT', pct(learned_vs_klt['ape_relative_error_reduction_fraction']), pct(learned_vs_klt['rpe_relative_error_reduction_fraction'])],
    ['HFNet-SLAM vs KLT', pct(hfnet_vs_klt['ape_relative_error_reduction_fraction']), pct(hfnet_vs_klt['rpe_relative_error_reduction_fraction'])],
    ['HFNet-SLAM vs Learned+KLT', pct(hfnet_vs_learned['ape_relative_error_reduction_fraction']), pct(hfnet_vs_learned['rpe_relative_error_reduction_fraction'])],
])}

These percentages are deterministic point-estimate ratios, not inferential effect sizes.

## Inferential statistics deliberately blocked

- Significance test: not performed (`n=1` accuracy-authorized window).
- 95% CI: not computed; there is no seed/window sampling distribution that supports one.
- Standardized effect size: not computed.
- Multiple-comparison correction: not applicable because no hypothesis tests were run.
- Error bars: omitted from Figure 2 because uncertainty cannot be estimated from one formal run; fabricating zero-width or pseudo-replicate bars would be misleading.

## Integrity checks

- All 10 runner attempts are consumed and forbid retry.
- A05 remains pre-addendum and has no retroactive watchdog/adjudication receipt.
- The remaining 9 cases have per-case prestart, watchdog, and terminal adjudication receipts.
- Only mclab1 has a PASS cache adjudication, frozen accuracy lock, exactly-once accuracy claim, PASS terminal receipt, and evo-authorized numeric result.
- Failed accuracy values are `NA`, never numeric zero and never included in averages.
"""

    figure_catalog = """
# Figure catalog

## Figure 1 — Frozen roster runability coverage

- Filename: `figures/figure-01-runability-coverage.{pdf,svg,png}`
- Purpose: show which exact historical windows produced enough continuous HFNet trajectory to enter accuracy analysis.
- Data source: ten immutable `run_result.json` receipts plus per-case adjudication receipts.
- Plotted variables: contiguous trajectory coverage per window; dashed line is the preregistered 70% gate.
- Sample size: 10 outcome-selected windows, one run each.
- Error bars: none; each bar is a deterministic single-run coverage value, not a sample mean.
- Caption requirements: state exactly-once cold start, 70% gate, FAIL=accuracy NA, and outcome-selected roster.
- Key observation: only mclab1 crosses the gate; A09 and mclab2 retain fragments but remain below it; all other windows have zero usable coverage.
- Interpretation: external-baseline accuracy is available for one window only. The figure is a runability audit, not a population success-rate estimate.
- Decision changed: do not average failures with the one valid result; design a prospective unscreened roster before making robustness claims.

## Figure 2 — mclab1 common-support APE/RPE

- Filename: `figures/figure-02-mclab1-common-support-errors.{pdf,svg,png}`
- Purpose: compare HFNet-SLAM, Learned+KLT, and KLT on the sole accuracy-authorized window.
- Data source: formal accuracy v2 result and independent evo crosscheck; the reference is a disclosed non-independent proxy.
- Plotted variables: translation APE RMSE and exact-1-s translation RPE RMSE in metres; lower is better.
- Common support: 139 poses, 129 RPE pairs, 13.8 s, 92.67% grid coverage.
- Sample size: one outcome-selected window, one run per method trajectory.
- Error bars: none because no repeat/seed distribution exists; bars are exact point estimates.
- Caption requirements: name mclab1 s60/d15, common support, proxy-reference role, independent fixed-scale SE(3) alignment, metric direction, n=1 boundary, and no inferential test.
- Key observation: HFNet-SLAM has the lowest point estimate for both metrics; Learned+KLT remains better than KLT.
- Interpretation: the external learned-feature SLAM system has lower point estimates on this window, but one window cannot establish general superiority.
- Decision changed: retain HFNet-SLAM as a strong system-level baseline and expand prospective coverage before manuscript-level ranking.

## Accessibility and export QA

- Okabe–Ito-compatible colors plus hatch patterns provide redundant encoding.
- Bar axes start at zero.
- Vector PDF/SVG and 600-DPI PNG are exported.
- Figures use English labels to avoid font substitution in the manuscript toolchain.
"""

    write_text(OUTPUT / "analysis-report.md", report)
    write_text(OUTPUT / "stats-appendix.md", stats)
    write_text(OUTPUT / "figure-catalog.md", figure_catalog)


def main() -> int:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    FIGURES.mkdir(parents=True, exist_ok=True)

    rows, source_pins = load_roster()
    accuracy = load_accuracy(source_pins)

    source_pins["authority:roster_pointer"] = identity(
        Path("/mnt/data/AQUA-FE_WS/locks/hfnet_v6_samehistory_positive_roster_execution_lock_v2.json")
    )
    source_pins["authority:accuracy_supersession_v2"] = identity(
        Path("/mnt/data/AQUA-FE_WS/locks/hfnet_v6_samehistory_positive_accuracy_supersession_v2.json")
    )
    for label, path in (
        ("authority:runner_v2", WORKSPACE / "scripts/run_hfnet_v6_samehistory_positive_roster_v2.py"),
        (
            "authority:cache_adjudicator_v1",
            WORKSPACE / "scripts/adjudicate_hfnet_v6_samehistory_positive_roster_cache_contract_v1.py",
        ),
        (
            "authority:zero_kf_watchdog_v1",
            WORKSPACE / "scripts/run_hfnet_v6_samehistory_positive_roster_zero_kf_watchdog_v1.py",
        ),
        (
            "authority:accuracy_controller_v2",
            WORKSPACE / "scripts/run_hfnet_v6_samehistory_positive_roster_accuracy_v2.py",
        ),
        (
            "analysis_builder",
            Path(__file__).resolve(),
        ),
        (
            "analysis:publication_style",
            STYLE,
        ),
    ):
        source_pins[label] = identity(path)

    category_counts: dict[str, int] = {}
    for row in rows:
        category_counts[row["failure_category"]] = category_counts.get(row["failure_category"], 0) + 1
    bundle = {
        "schema_version": "aqua-fe-hfnet-v6-samehistory-positive-roster-analysis-v1",
        "analysis_status": "DESCRIPTIVE_COMPLETE_INFERENCE_BLOCKED_N1",
        "protocol": {
            "roster_size": 10,
            "selection": "OUTCOME_SELECTED_HISTORICAL_LEARNED_PLUS_KLT_POSITIVES",
            "history": "EXACT_WINDOW_COLD_START_NO_PRIOR_CAMERA_HISTORY",
            "runability_gate_minimum_contiguous_coverage": RUNABILITY_GATE,
            "exactly_once": True,
            "failed_accuracy_is_na_not_zero": True,
        },
        "runability": {
            "pass_count": 1,
            "fail_count": 9,
            "descriptive_roster_pass_fraction": 0.1,
            "category_counts": category_counts,
            "population_success_rate_claim_authorized": False,
        },
        "cases": rows,
        "accuracy": accuracy,
        "claim_boundary": {
            "single_window_point_estimate_comparison_authorized": True,
            "cross_window_mean_authorized": False,
            "significance_claim_authorized": False,
            "general_superiority_claim_authorized": False,
        },
    }
    write_json(OUTPUT / "analysis-bundle.json", bundle)
    write_csv_files(rows, accuracy)
    make_figures(rows, accuracy)
    build_reports(rows, accuracy)

    output_paths = [
        OUTPUT / "analysis-bundle.json",
        OUTPUT / "roster-summary.csv",
        OUTPUT / "mclab1-common-support-metrics.csv",
        OUTPUT / "analysis-report.md",
        OUTPUT / "stats-appendix.md",
        OUTPUT / "figure-catalog.md",
    ] + sorted(FIGURES.glob("figure-*.*"))
    manifest = {
        "schema_version": "aqua-fe-hfnet-v6-samehistory-positive-roster-analysis-source-manifest-v1",
        "status": "PASS_ALL_DECLARED_SOURCES_AND_OUTPUTS_SNAPSHOTTED",
        "input_count": len(source_pins),
        "inputs": dict(sorted(source_pins.items())),
        "outputs": {path.name: identity(path) for path in output_paths},
        "reproducibility": {
            "builder": identity(Path(__file__).resolve()),
            "inferential_statistics_performed": False,
            "failed_cases_imputed": False,
        },
    }
    write_json(OUTPUT / "source-manifest.json", manifest)

    print(
        json.dumps(
            {
                "status": "PASS_ANALYSIS_BUNDLE_BUILT",
                "output": str(OUTPUT),
                "roster_count": len(rows),
                "runability_pass_count": 1,
                "accuracy_authorized_case_count": 1,
                "figures": 2,
                "inference_performed": False,
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
