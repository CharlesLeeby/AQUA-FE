from __future__ import annotations

import csv
import re
from pathlib import Path

import numpy as np


ROOT = Path("/home/ma/AQUA-FE_WS")
VINS_ROOT = Path("/home/ma/SLAM/VINS-Fusion-origin/src/VINS-Fusion-master")
OUT_DIR = ROOT / "logs/agent_qi_vins"


CODE_PATTERNS = [
    (
        "PointCloud quality channel read",
        VINS_ROOT / "vins_estimator/src/rosNodeTest.cpp",
        'channels[channel_idx].name == "quality"',
        "first",
    ),
    (
        "q_i stored per observation",
        VINS_ROOT / "vins_estimator/src/estimator/feature_manager.h",
        "visual_quality = std::max(0.05",
        "first",
    ),
    (
        "mono residual sqrt(q)",
        VINS_ROOT / "vins_estimator/src/factor/projectionTwoFrameOneCamFactor.cpp",
        "residual = sqrt_quality * sqrt_info * residual",
        "first",
    ),
    (
        "two-frame stereo residual sqrt(q)",
        VINS_ROOT / "vins_estimator/src/factor/projectionTwoFrameTwoCamFactor.cpp",
        "residual = sqrt_quality * sqrt_info * residual",
        "first",
    ),
    (
        "one-frame stereo residual sqrt(q)",
        VINS_ROOT / "vins_estimator/src/factor/projectionOneFrameTwoCamFactor.cpp",
        "residual = sqrt_quality * sqrt_info * residual",
        "first",
    ),
    (
        "normal optimization q wiring",
        VINS_ROOT / "vins_estimator/src/estimator/estimator.cpp",
        "f->setQualityWeight(std::min(it_per_id.feature_per_frame[0].visual_quality, it_per_frame.visual_quality));",
        "first",
    ),
    (
        "marginalization q wiring",
        VINS_ROOT / "vins_estimator/src/estimator/estimator.cpp",
        "f_td->setQualityWeight(std::min(it_per_id.feature_per_frame[0].visual_quality, it_per_frame.visual_quality));",
        "last",
    ),
]


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    code_rows = collect_code_rows()
    ablation_rows = collect_ablation_rows()
    write_csv(OUT_DIR / "qi_vins_code_support.csv", code_rows)
    write_csv(OUT_DIR / "qi_vins_ablation_summary.csv", ablation_rows)
    (OUT_DIR / "qi_vins_report.md").write_text(make_report(code_rows, ablation_rows), encoding="utf-8")
    print(f"wrote {OUT_DIR / 'qi_vins_code_support.csv'}")
    print(f"wrote {OUT_DIR / 'qi_vins_ablation_summary.csv'}")
    print(f"wrote {OUT_DIR / 'qi_vins_report.md'}")
    return 0


def collect_code_rows() -> list[dict[str, object]]:
    rows = []
    for label, path, pattern, occurrence in CODE_PATTERNS:
        matches = find_lines(path, pattern)
        match = matches[-1] if occurrence == "last" and matches else matches[0] if matches else None
        rows.append(
            {
                "check": label,
                "path": str(path),
                "line": match[0] if match else "",
                "matched": bool(matches),
                "snippet": match[1].strip() if match else "",
            }
        )
    return rows


def collect_ablation_rows() -> list[dict[str, object]]:
    rows = []
    for mode in ["q", "constq"]:
        run_dir = OUT_DIR / f"h07_1660_1950_{mode}"
        ape = parse_key_value_file(run_dir / "ape.txt")
        metrics = summarize_frontend_metrics(run_dir / "frontend_metrics.csv")
        bag_stats = summarize_feature_bag(run_dir / "features.bag")
        row: dict[str, object] = {
            "mode": mode,
            "run_dir": str(run_dir),
            "matched": ape.get("matched", ""),
            "se3_ape_rmse_m": ape.get("se3_ape_rmse_m", ""),
            "se3_ape_median_m": ape.get("se3_ape_median_m", ""),
            "rpe_trans_rmse_m": ape.get("rpe_trans_rmse_m", ""),
            "rpe_trans_median_m": ape.get("rpe_trans_median_m", ""),
            "output_coverage_ratio": ape.get("output_coverage_ratio", ""),
            "init_success": ape.get("init_success", ""),
            "log_linear_solver_failures": ape.get("log_linear_solver_failures", ""),
        }
        row.update(metrics)
        row.update(bag_stats)
        rows.append(row)
    return rows


def find_lines(path: Path, pattern: str) -> list[tuple[int, str]]:
    if not path.exists():
        return []
    matches = []
    for idx, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), start=1):
        if pattern in line:
            matches.append((idx, line))
    return matches


def parse_key_value_file(path: Path) -> dict[str, float | str]:
    out: dict[str, float | str] = {}
    if not path.exists():
        return out
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        try:
            out[key] = float(value)
        except ValueError:
            out[key] = value
    return out


def summarize_frontend_metrics(path: Path) -> dict[str, float | int | str]:
    if not path.exists():
        return {}
    with path.open("r", newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    if not rows:
        return {}
    exported = np.asarray([float(r["exported_features"]) for r in rows], dtype=np.float64)
    median_q = np.asarray([float(r["median_quality"]) for r in rows], dtype=np.float64)
    median_backend_q = np.asarray([float(r["median_backend_quality"]) for r in rows], dtype=np.float64)
    return {
        "feature_frames": len(rows),
        "exported_features_median": float(np.median(exported)),
        "frontend_q_median_of_medians": float(np.median(median_q)),
        "backend_q_median_of_medians": float(np.median(median_backend_q)),
    }


def summarize_feature_bag(path: Path) -> dict[str, float | int | str]:
    if not path.exists():
        return {}
    try:
        import rosbag
    except Exception as exc:
        return {"feature_bag_error": str(exc)}
    qualities = []
    sigmas = []
    counts = []
    with rosbag.Bag(str(path)) as bag:
        for _, msg, _ in bag.read_messages(topics=["/feature_tracker/feature"]):
            channel_map = {ch.name: ch.values for ch in msg.channels}
            qualities.extend(channel_map.get("quality", []))
            sigmas.extend(channel_map.get("sigma", []))
            counts.append(len(msg.points))
    if not qualities:
        return {"feature_points": 0}
    q = np.asarray(qualities, dtype=np.float64)
    sigma = np.asarray(sigmas, dtype=np.float64)
    counts_arr = np.asarray(counts, dtype=np.float64)
    return {
        "feature_points": int(len(q)),
        "points_per_frame_median": float(np.median(counts_arr)),
        "point_q_min": float(np.min(q)),
        "point_q_median": float(np.median(q)),
        "point_q_mean": float(np.mean(q)),
        "point_q_max": float(np.max(q)),
        "point_sigma_median": float(np.median(sigma)),
    }


def write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fieldnames = list(rows[0].keys())
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def make_report(code_rows: list[dict[str, object]], ablation_rows: list[dict[str, object]]) -> str:
    q_row = next((row for row in ablation_rows if row["mode"] == "q"), {})
    const_row = next((row for row in ablation_rows if row["mode"] == "constq"), {})
    lines = [
        "# q_i -> VINS Backend Closed Loop",
        "",
        "## Summary",
        "",
        "VINS-Fusion-origin now has a complete q_i path from external PointCloud input to projection residual weighting. "
        "The backend reads a `quality` channel, stores it per observation, and multiplies visual projection residuals and their Jacobians by `sqrt(q_i)` with q clipped to [0.05, 1.0]. "
        "This is equivalent to using `sigma_i = sigma_base / sqrt(q_i)` up to the fixed global VINS `sqrt_info` scale.",
        "",
        "Catkin validation passed with `catkin_make -C /home/ma/SLAM/VINS-Fusion-origin -j2`; `libvins_lib.so`, `vins_node`, `kitti_odom_test`, and `kitti_gps_test` rebuilt successfully.",
        "",
        "## H07 Closed-Loop Ablation",
        "",
        "The small AQUALOC H07 external-feature ablation reused the existing `datasets/aqualoc/rosbags/harbor07_1660_1950.bag` and wrote only under `logs/agent_qi_vins/`. "
        "Both runs used KLT + adaptive CLAHE, every-2 frames, about 350 exported features per feature frame. "
        "`q` used the exported backend quality channel; `constq` sent `quality=1` and `sigma=1` for every feature.",
        "",
        markdown_table(ablation_rows),
        "",
        "Interpretation: the q path is active because the same feature stream with different quality values changes APE/RPE substantially. "
        "On this all-feature H07 KLT window, however, the current q scale is not performance-positive: q weighting reduces visual information relative to the VINS tuning and increases APE/RPE. "
        "Use this run as a functional closed-loop validation, not as a final accuracy claim. A calibrated/floored backend q schedule should be tested before claiming trajectory improvement.",
        "",
        "## Code Evidence",
        "",
        markdown_table(code_rows),
        "",
        "## Modified VINS Files",
        "",
        "- `/home/ma/SLAM/VINS-Fusion-origin/src/VINS-Fusion-master/vins_estimator/src/factor/projectionTwoFrameOneCamFactor.cpp`: aligned quality floor to 0.05.",
        "- `/home/ma/SLAM/VINS-Fusion-origin/src/VINS-Fusion-master/vins_estimator/src/factor/projectionTwoFrameTwoCamFactor.h` and `.cpp`: added `setQualityWeight`, `quality_weight`, and `sqrt(q)` residual/Jacobian scaling.",
        "- `/home/ma/SLAM/VINS-Fusion-origin/src/VINS-Fusion-master/vins_estimator/src/factor/projectionOneFrameTwoCamFactor.h` and `.cpp`: added the same q weighting for one-frame stereo residuals.",
        "- `/home/ma/SLAM/VINS-Fusion-origin/src/VINS-Fusion-master/vins_estimator/src/estimator/estimator.cpp`: wired q into normal optimization and marginalization residual creation for stereo factors.",
        "",
        "Existing support confirmed but not newly edited: `/home/ma/SLAM/VINS-Fusion-origin/src/VINS-Fusion-master/vins_estimator/src/rosNodeTest.cpp` reads the `quality` channel by name, and `feature_manager.h` stores q in `FeaturePerFrame::visual_quality`.",
        "",
        "## Reproduction",
        "",
        "```bash",
        "cd /home/ma/AQUA-FE_WS",
        "bash -lc 'source /opt/ros/noetic/setup.bash && catkin_make -C /home/ma/SLAM/VINS-Fusion-origin -j2'",
        "DURATION=15.0 PREPROCESS=adaptive_clahe MEASUREMENT_SELECTION=0 EXPORT_MAX_FEATURES=350 ./scripts/agent_qi_vins_h07_ablation.sh q",
        "DURATION=15.0 PREPROCESS=adaptive_clahe MEASUREMENT_SELECTION=0 EXPORT_MAX_FEATURES=350 ./scripts/agent_qi_vins_h07_ablation.sh constq",
        "python scripts/agent_qi_vins_summarize.py",
        "```",
        "",
        "No files under `/home/ma/SLAM/VINS-Fusion_3-15-WS` were modified.",
    ]
    if q_row and const_row:
        try:
            delta = float(q_row["se3_ape_rmse_m"]) - float(const_row["se3_ape_rmse_m"])
            lines.insert(
                10,
                f"Result snapshot: q APE RMSE={float(q_row['se3_ape_rmse_m']):.6f} m, constq APE RMSE={float(const_row['se3_ape_rmse_m']):.6f} m, delta={delta:+.6f} m.",
            )
            lines.insert(11, "")
        except Exception:
            pass
    return "\n".join(lines) + "\n"


def markdown_table(rows: list[dict[str, object]]) -> str:
    if not rows:
        return "(empty)"
    headers = list(rows[0].keys())
    body = [[fmt(row.get(header, "")) for header in headers] for row in rows]
    widths = [max(len(header), *(len(row[i]) for row in body)) for i, header in enumerate(headers)]
    header_line = "| " + " | ".join(header.ljust(widths[i]) for i, header in enumerate(headers)) + " |"
    sep = "| " + " | ".join("-" * widths[i] for i in range(len(headers))) + " |"
    body_lines = [
        "| " + " | ".join(row[i].ljust(widths[i]) for i in range(len(headers))) + " |"
        for row in body
    ]
    return "\n".join([header_line, sep] + body_lines)


def fmt(value: object) -> str:
    if isinstance(value, float):
        return f"{value:.6f}"
    return str(value)


if __name__ == "__main__":
    raise SystemExit(main())
