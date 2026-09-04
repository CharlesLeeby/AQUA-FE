#!/usr/bin/env python3
"""Analyze the preregistered repaired no-harm same-backend epoch."""

from __future__ import annotations

import csv
import io
from pathlib import Path

import analyze_frontend_same_backend_comparison_v1 as core
import analyze_frontend_same_backend_supplement_v1 as base
import rosbag


ROOT = Path("/home/ma/AQUA-FE_WS")
OUT = ROOT / "papers/frontend_same_backend_comparison_noharm_v2"
WINDOWS = base.WINDOWS
_ORIGINAL_ARTIFACT_MANIFEST = base.artifact_manifest
_ORIGINAL_EVALUATOR_ARGS = base.evaluator_args


def run_dir(window: core.Window, arm: str, repeat: int) -> Path:
    method = core.ARMS[arm][1]
    roots = {
        "aqualoc_archaeo": ROOT / "logs/aqualoc_archaeo_vins",
        "aqualoc_real": ROOT / "logs/aqualoc_real_vins",
        "ntnu": ROOT / "logs/ntnu_vins",
    }
    return roots[window.family] / f"external_{method}_every2_fsbcnh2_{window.window_id}_{arm}_r{repeat}"


def evaluator_args(window: core.Window, eligible_rows: list[dict[str, object]]) -> list[str]:
    args = _ORIGINAL_EVALUATOR_ARGS(window, eligible_rows)
    index = args.index("--contrast-name") + 1
    args[index] = f"fsbcnh2_{window.window_id}_all9"
    return args


def artifact_manifest() -> None:
    _ORIGINAL_ARTIFACT_MANIFEST()
    manifest = OUT / "artifacts.sha256"
    lines = manifest.read_text(encoding="utf-8").splitlines() if manifest.is_file() else []
    existing = {line.split("  ", 1)[1] for line in lines if "  " in line}
    additions = (
        ROOT / "scripts/run_frontend_same_backend_noharm_v2.py",
        ROOT / "scripts/analyze_frontend_same_backend_noharm_v2.py",
        ROOT / "scripts/report_frontend_same_backend_noharm_v2.py",
        ROOT / "tests/test_final_mirror_noharm_contract.py",
        ROOT / "papers/frontend_same_backend_noharm_fix_v1/report.md",
        OUT / "final_mirror_noharm_audit.csv",
        OUT / "execution_conditions.md",
    )
    for path in additions:
        if path.is_file() and str(path.resolve()) not in existing:
            lines.append(f"{core.sha256(path)}  {path.resolve()}")
    manifest.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _serialized_messages(path: Path) -> list[tuple[int, bytes]]:
    output: list[tuple[int, bytes]] = []
    with rosbag.Bag(str(path)) as bag:
        for _, message, stamp in bag.read_messages(topics=["/feature_tracker/feature"]):
            buffer = io.BytesIO()
            message.serialize(buffer)
            output.append((stamp.to_nsec(), buffer.getvalue()))
    return output


def collect_final_mirror_audit() -> None:
    """Verify the repaired rollback/cap contract against emitted messages."""

    output: list[dict[str, object]] = []
    numeric = (
        "final_mirror_input_sidecars",
        "final_mirror_kept_sidecars",
        "final_mirror_dropped_sidecars_for_cap",
        "final_mirror_dropped_classical_for_cap",
        "final_mirror_remapped_sidecar_ids",
    )
    for window in WINDOWS:
        klt_messages = _serialized_messages(run_dir(window, "klt", 1) / "features.bag")
        for arm in core.ARMS:
            metrics_path = run_dir(window, arm, 1) / "frontend_metrics.csv"
            with metrics_path.open(newline="", encoding="utf-8") as handle:
                metrics = list(csv.DictReader(handle))
            messages = _serialized_messages(run_dir(window, arm, 1) / "features.bag")
            zero_indices = [
                index for index, row in enumerate(metrics)
                if int(float(row.get("final_mirror_zero_sidecar_restore", "0") or 0)) == 1
            ]
            comparable = len(messages) == len(metrics) == len(klt_messages)
            mismatches = 0
            if comparable:
                mismatches = sum(messages[index] != klt_messages[index] for index in zero_indices)
            else:
                mismatches = len(zero_indices)
            sums = {
                field: int(sum(float(row.get(field, "0") or 0) for row in metrics))
                for field in numeric
            }
            active_frames = sum(
                int(float(row.get("final_mirror_kept_sidecars", "0") or 0)) > 0
                for row in metrics
            )
            output.append({
                "window": window.window_id,
                "arm": arm,
                "selected_frames": len(metrics),
                "feature_messages": len(messages),
                "zero_sidecar_restore_frames": len(zero_indices),
                "active_sidecar_frames": active_frames,
                **{f"{field}_total": value for field, value in sums.items()},
                "zero_sidecar_messages_equal_klt": len(zero_indices) - mismatches,
                "zero_sidecar_message_mismatches": mismatches,
                "zero_sidecar_rollback_status": "PASS" if comparable and mismatches == 0 else "FAIL",
            })
    core.write_csv(OUT / "final_mirror_noharm_audit.csv", output)


def configure() -> None:
    base.OUT = OUT
    base.WINDOWS = WINDOWS
    base.run_dir = run_dir
    base.evaluator_args = evaluator_args
    base.artifact_manifest = artifact_manifest


def main() -> int:
    configure()
    result = base.main()
    collect_final_mirror_audit()
    artifact_manifest()
    return result


if __name__ == "__main__":
    raise SystemExit(main())
