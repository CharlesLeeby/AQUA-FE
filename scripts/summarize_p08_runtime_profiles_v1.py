#!/usr/bin/env python3
"""Summarize the bounded P08 current-source runtime profiles."""

from __future__ import annotations

import csv
import hashlib
import json
import platform
from pathlib import Path
import statistics
import subprocess


ROOT = Path("/home/ma/AQUA-FE_WS")
RUNTIME = Path("/media/ma/Data/AQUA-FE_WS_storage_offload/p08_runtime_profiles_20260904")
P07_OUTPUT = Path(
    "/media/ma/Data/AQUA-FE_WS_storage_offload/"
    "p07_backend_completion_serial_v2/analysis-output"
)
OUTPUT = RUNTIME / "analysis-output"

CASES = [
    ("aqualoc_harbor:H05:0002", "normal_zero_action", "B1", "h05_b1_attempt03.json", "external_klt_every2_p08_profile_h05_b1_20260904_attempt03"),
    ("aqualoc_harbor:H05:0002", "normal_zero_action", "M", "h05_m.json", "external_xfeat_every2_p08_profile_h05_m_20260904"),
    ("aqualoc_harbor:H05:0002", "normal_zero_action", "P", "h05_p.json", "external_klt_every2_p08_profile_h05_p_20260904_klt_safe_fallback"),
    ("ntnu:fjord_6:0001", "third_domain", "B1", "ntnu_fjord6_b1.json", "external_klt_every2_p08_profile_ntnu_fjord6_b1_20260904"),
    ("ntnu:fjord_6:0001", "third_domain", "M", "ntnu_fjord6_m.json", "external_xfeat_every2_p08_profile_ntnu_fjord6_m_20260904"),
    ("ntnu:fjord_6:0001", "third_domain", "P", "ntnu_fjord6_p.json", "external_klt_every2_p08_profile_ntnu_fjord6_p_20260904_klt_safe_fallback"),
]
ARM_LONG = {
    "B0": "B0_native_vins_origin_v1",
    "B1": "B1_klt_nativeq_v3",
    "M": "M_xfeat_pairwise_nativeq_v1",
    "P": "P_legacy_nativeq_xfeat_seedchain_v3",
}


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as stream:
        return list(csv.DictReader(stream))


def write_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    temporary.replace(path)


def atomic_text(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(value, encoding="utf-8")
    temporary.replace(path)


def atomic_json(path: Path, value: dict) -> None:
    atomic_text(path, json.dumps(value, indent=2, sort_keys=True) + "\n")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def locate_metrics(directory_name: str) -> Path:
    matches = list((RUNTIME / "shadow_root/logs").glob(f"**/{directory_name}/frontend_metrics.csv"))
    if len(matches) != 1:
        raise RuntimeError(f"expected one metrics file for {directory_name}, found {len(matches)}")
    return matches[0]


def command_output(command: list[str]) -> str:
    result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, check=False)
    return result.stdout.strip()


def main() -> int:
    backend_rows = read_csv(P07_OUTPUT / "backend_terminal_long.csv")
    rows = []
    for window_id, category, arm, profile_name, directory_name in CASES:
        profile_path = RUNTIME / "profiles" / profile_name
        profile = json.loads(profile_path.read_text(encoding="utf-8"))
        if profile["status"] != "COMPLETED":
            raise RuntimeError(f"non-completed profile: {profile_path}")
        metrics_path = locate_metrics(directory_name)
        metrics = read_csv(metrics_path)
        timestamps = [float(row["timestamp"]) for row in metrics]
        span = max(timestamps) - min(timestamps)
        wall = float(profile["wall_seconds"])
        backend = [
            float(row["wall_seconds"])
            for row in backend_rows
            if row["window_id"] == window_id and row["arm"] == ARM_LONG[arm]
        ]
        if len(backend) != 3:
            raise RuntimeError(f"missing three backend repeats: {window_id}/{arm}")
        backend_median = statistics.median(backend)
        rows.append(
            {
                "window_id": window_id,
                "selection_category": category,
                "arm": arm,
                "source_identity": "CURRENT_SOURCE_DRIFT_PROFILE_ONLY",
                "feature_frames": len(metrics),
                "feature_span_s": span,
                "frontend_wall_s": wall,
                "frontend_output_fps": len(metrics) / wall,
                "frontend_realtime_factor": wall / span,
                "mean_exported_features_per_frame": statistics.mean(
                    float(row["exported_features"]) for row in metrics
                ),
                "peak_process_tree_rss_mib": profile["peak_process_tree_rss_bytes"] / 1024**2,
                "process_tree_cpu_s_peak_sample": profile["peak_process_tree_cpu_seconds"],
                "gpu_peak_memory_delta_mib_device_global": profile["gpu_peak_memory_delta_mib"],
                "gpu_peak_utilization_percent_device_global": profile["gpu_peak_global_utilization_percent"],
                "backend_replay_wall_median_s": backend_median,
                "approx_frontend_plus_backend_wall_s": wall + backend_median,
                "frontend_profile_receipt": str(profile_path),
                "frontend_metrics": str(metrics_path),
            }
        )

    write_csv(OUTPUT / "p08_runtime_profiles.csv", rows)
    backend_summary = json.loads((P07_OUTPUT / "analysis_summary.json").read_text())[
        "runtime_backend_replay_wall"
    ]
    summary = {
        "schema_version": "p08-runtime-resource-summary-v1",
        "decision": "PROFILED_OFFLINE",
        "profile_rows": len(rows),
        "selected_cases": {
            "normal_zero_action": "aqualoc_harbor:H05:0002 (lowest assignment rank satisfying category)",
            "third_domain": "ntnu:fjord_6:0001 (lowest subsequent distinct domain)",
            "low_active": "UNAVAILABLE: 0/20 P windows contain a learned-born lineage",
            "normal_active": "UNAVAILABLE: 0/20 P windows contain a learned-born lineage",
        },
        "all_profiled_frontends_slower_than_data_span": all(
            float(row["frontend_realtime_factor"]) > 1.0 for row in rows
        ),
        "all_profiled_outputs_have_450_frames": all(int(row["feature_frames"]) == 450 for row in rows),
        "backend_replay_all_windows": backend_summary,
        "hardware": {
            "platform": platform.platform(),
            "cpu": command_output(["bash", "-lc", "sed -n 's/^model name[[:space:]]*:[[:space:]]*//p' /proc/cpuinfo | head -n 1"]),
            "memory": command_output(["bash", "-lc", "free -h | sed -n '2p'"]),
            "gpu": command_output(["nvidia-smi", "--query-gpu=name,memory.total,driver_version", "--format=csv,noheader"]),
        },
        "measurement_boundary": (
            "frontend wall time is an offline export pipeline; backend wall time includes ROS startup, "
            "real-time playback and post-drain. Device-global GPU samples are not per-process attribution."
        ),
        "identity_boundary": (
            "P08 executes current source with an explicit profile-only guard bypass because the frozen "
            "exporter/source bytes were not retained; these rows are not P07 confirmatory outcomes."
        ),
    }
    atomic_json(OUTPUT / "p08_runtime_summary.json", summary)

    lines = [
        "# P08 runtime and resource closeout",
        "",
        "Decision: **PROFILED_OFFLINE**.",
        "",
        "All six bounded profiles produced 450 feature frames over about 44.9 s, but every frontend export took longer than the input span. The implementation therefore has no real-time evidence.",
        "",
        "| Case | Arm | Frontend wall (s) | Realtime factor | Output fps | Peak RSS (MiB) | Backend median (s) |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for row in rows:
        lines.append(
            f"| {row['window_id']} | {row['arm']} | {float(row['frontend_wall_s']):.1f} | "
            f"{float(row['frontend_realtime_factor']):.2f}x | {float(row['frontend_output_fps']):.2f} | "
            f"{float(row['peak_process_tree_rss_mib']):.1f} | {float(row['backend_replay_wall_median_s']):.1f} |"
        )
    lines += [
        "",
        "The frozen category rule could not supply low-active or normal-active examples: all 20 proposed outputs contain zero learned-born lineages. H05 is the first normal zero-action case and NTNU fjord_6 is the first subsequent distinct-domain case.",
        "",
        "The proposed path is especially inefficient in its present form because it runs a learned probe and then a full KLT fallback. Resource profiles use current post-freeze source under an explicit profile-only bypass; they are performance diagnostics, not replacements for the frozen P07 results.",
        "",
        "Backend timings are reported separately because they include ROS startup, real-time playback, post-drain, and evaluation overhead. GPU readings are device-global samples and should not be interpreted as exact per-process utilization.",
    ]
    atomic_text(OUTPUT / "p08-runtime-report.md", "\n".join(lines) + "\n")

    artifacts = []
    for relative in ["p08_runtime_profiles.csv", "p08_runtime_summary.json", "p08-runtime-report.md"]:
        path = OUTPUT / relative
        artifacts.append({"path": str(path), "bytes": path.stat().st_size, "sha256": sha256(path)})
    atomic_json(
        OUTPUT / "p08_closeout.json",
        {
            "schema_version": "p08-functional-closeout-v1",
            "status": "PASS_WITH_PROFILED_OFFLINE_RESULT",
            "artifacts": artifacts,
        },
    )
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
