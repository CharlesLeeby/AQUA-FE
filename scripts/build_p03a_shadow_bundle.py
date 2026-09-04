#!/usr/bin/env python3
"""Aggregate the six fixed P03A development shadow windows.

This tool is deliberately conservative: it validates master chains, invokes
the stateful five-arm shadow replay when needed, and writes machine-readable
ranking/runtime/manifests.  It never reads trajectory metrics and therefore
cannot promote a selector on frontend-only evidence.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import subprocess
import sys
from pathlib import Path
from statistics import median

ROOT = Path(__file__).resolve().parents[1]
BUNDLE = ROOT / "papers/ieee_sensors_journal_experiments"
P03 = BUNDLE / "p03"

WINDOWS = (
    ("a10_2400_2800", "A10", "low", "positive", "a10_2400_2800"),
    ("a09_4000_4400", "A09", "low", "positive", "a09_4000_4400"),
    ("a10_400_800", "A10", "boundary", "negative", "a10_400_800"),
    ("a08_7200_7600", "A08", "boundary", "negative", "a08_7200_7600"),
    ("h07_1660_1720", "H07", "normal", "normal", "h07_1660_1720"),
    ("tank_short_0_15", "Tank_short_test", "normal", "normal_zero_action", "tank_short_0_15"),
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", default=str(P03))
    parser.add_argument("--skip-replay", action="store_true")
    parser.add_argument("--model-hash", default="")
    args = parser.parse_args()
    output = Path(args.output_dir)
    output.mkdir(parents=True, exist_ok=True)

    manifest_rows = []
    result_rows = []
    runtime_rows = []
    detail_rows = []
    replay_errors = []
    for window_id, sequence_id, geometry, class_name, directory in WINDOWS:
        window_dir = output / directory
        master_path = window_dir / "master_stream.jsonl"
        calibration_path = window_dir / "calibration_rows.csv"
        metrics_path = window_dir / "master_metrics.csv"
        shadow_path = window_dir / "shadow_rankings.csv"
        detail_path = window_dir / "shadow_rankings_detail.csv"
        runtime_path = window_dir / "runtime_probe.json"
        chains_dir = window_dir / "arm_chains"
        input_hash = _sha256(master_path) if master_path.is_file() else ""
        chain_info = _validate_master(master_path)
        replay_status = "PRESENT" if shadow_path.is_file() else "MISSING"
        if replay_status == "MISSING" and not args.skip_replay and master_path.is_file():
            command = [
                sys.executable,
                str(ROOT / "scripts/replay_p03_shadow.py"),
                "--master-jsonl", str(master_path),
                "--output-csv", str(shadow_path),
                "--detail-csv", str(detail_path),
                "--runtime-json", str(runtime_path),
                "--arm-chain-dir", str(chains_dir),
            ]
            if args.model_hash:
                command.extend(["--selector-model-hash", args.model_hash])
            completed = subprocess.run(command, cwd=str(ROOT), text=True, capture_output=True)
            if completed.returncode != 0:
                replay_errors.append(f"{window_id}: {completed.stderr.strip()[-500:]}")
                replay_status = "FAIL"
            else:
                replay_status = "PRESENT"
        shadow = _read_csv(shadow_path) if shadow_path.is_file() else []
        detail = _read_csv(detail_path) if detail_path.is_file() else []
        runtime = _read_json(runtime_path) if runtime_path.is_file() else {}
        for row in detail:
            row["window_id"] = window_id
            row["sequence_id"] = sequence_id
            row["geometry_stratum"] = geometry
            detail_rows.append(row)
        shortfall = sum(
            int(row.get("matching_shortfall_r", 0) or 0)
            + int(row.get("matching_shortfall_h", 0) or 0)
            + int(row.get("matching_shortfall_q", 0) or 0)
            + int(row.get("matching_shortfall_g", 0) or 0)
            for row in shadow
        )
        overlaps = [float(row["overlap_h_qg"]) for row in shadow if row.get("overlap_h_qg", "") != ""]
        qg_admissions = sum(int(row.get("n_t_qg", 0) or 0) for row in shadow)
        final_hash = chain_info.get("final_hash", "")
        model_hashes = sorted({row.get("model_fit_hash", "") for row in shadow if row.get("model_fit_hash")})
        fit_seeds = sorted({row.get("model_fit_seed", "") for row in shadow if row.get("model_fit_seed")})
        manifest_rows.append(
            {
                "window_id": window_id,
                "canonical_sequence_id": sequence_id,
                "geometry_stratum": geometry,
                "development_class": class_name,
                "master_stream": _display(master_path),
                "calibration_rows": _display(calibration_path),
                "frontend_metrics": _display(metrics_path),
                "master_sha256": input_hash,
                "master_final_hash": final_hash,
                "master_events": chain_info.get("events", 0),
                "master_chain_status": chain_info.get("status", "MISSING"),
                "replay_status": replay_status,
                "shadow_sha256": _sha256(shadow_path) if shadow_path.is_file() else "",
                "detail_sha256": _sha256(detail_path) if detail_path.is_file() else "",
                "runtime_sha256": _sha256(runtime_path) if runtime_path.is_file() else "",
                "provenance_status": "DEVELOPMENT_ONLY",
                "notes": "No VINS trajectory metrics are read by P03A shadow.",
            }
        )
        result_rows.append(
            {
                "window_id": window_id,
                "sequence_id": sequence_id,
                "geometry_stratum": geometry,
                "development_class": class_name,
                "events": len(shadow),
                "active_qg_events": sum(int(row.get("selection_active", 0) or 0) for row in shadow),
                "qg_admission_count": qg_admissions,
                "median_h_qg_overlap": median(overlaps) if overlaps else "",
                "matching_shortfall_total": shortfall,
                "model_fit_hashes": ";".join(model_hashes),
                "model_fit_seeds": ";".join(str(value) for value in fit_seeds),
                "master_final_hash": final_hash,
                "ape_status": "NOT_RUN_DEVELOPMENT_SHADOW_ONLY",
                "vins_status": "NOT_RUN_DEVELOPMENT_SHADOW_ONLY",
                "window_status": "PASS" if replay_status == "PRESENT" and not shortfall else "REVISE",
            }
        )
        runtime_rows.append(
            {
                "window_id": window_id,
                "sequence_id": sequence_id,
                "events": runtime.get("events", len(shadow)),
                "invoked_frame_count": runtime.get("invoked_frame_count", ""),
                "calibration_p50_ms": runtime.get("calibration_p50_ms", ""),
                "calibration_p95_ms": runtime.get("calibration_p95_ms", ""),
                "kernel_p50_ms": runtime.get("kernel_p50_ms", ""),
                "kernel_p95_ms": runtime.get("kernel_p95_ms", ""),
                "combined_p50_ms": runtime.get("combined_p50_ms", ""),
                "combined_p95_ms": runtime.get("combined_p95_ms", ""),
                "all_frame_kernel_amortized_ms": runtime.get("all_frame_kernel_amortized_ms", ""),
                "all_frame_combined_amortized_ms": runtime.get("all_frame_combined_amortized_ms", ""),
                "runtime_gate_1ms": "PASS" if runtime.get("invoked_frame_p95_ms", 1e99) <= 1.0 else "FAIL",
                "status": "DEVELOPMENT_PROBE",
            }
        )

    _write_csv(output / "selector_shadow_manifest.csv", manifest_rows)
    _write_csv(output / "shadow_rank_comparison.csv", detail_rows)
    _write_csv(output / "selector_development_results.csv", result_rows)
    _write_csv(output / "selector_runtime_probe.csv", runtime_rows)
    synthetic_text, synthetic_status = _synthetic_report(output)
    (output / "selector_synthetic_test_report.md").write_text(synthetic_text, encoding="utf-8")

    calibration_summary_path = output / "reliability_calibration_summary.json"
    calibration = _read_json(calibration_summary_path) if calibration_summary_path.is_file() else {}
    calibration_status = str(calibration.get("status", "MISSING"))
    any_shortfall = any(int(row.get("matching_shortfall_total", 0) or 0) > 0 for row in result_rows)
    all_replay = bool(result_rows) and all(row["window_status"] == "PASS" for row in result_rows)
    runtime_ok = bool(runtime_rows) and all(row["runtime_gate_1ms"] == "PASS" for row in runtime_rows)
    route = "PROMOTE" if synthetic_status == "PASS" and calibration_status == "PASS" and all_replay and runtime_ok and not replay_errors else "REVISE"
    reasons = []
    if synthetic_status != "PASS":
        reasons.append("synthetic selector contract is not PASS")
    if calibration_status != "PASS":
        reasons.append(f"provisional pooled calibration status is {calibration_status}")
    if any_shortfall:
        reasons.append("admission-count matching has active-budget shortfalls")
    if not runtime_ok:
        reasons.append("selector invoked-frame P95 exceeds 1 ms development gate")
    reasons.extend(["canonical VINS exporter/H-P selector-only probe is pending", "no P03A VINS diagnostics were run"])
    decision = [
        "# P03A Selector Decision",
        "",
        f"Route: `{route}`",
        "",
        "This is a development shadow decision. It does not authorize a confirmatory arm or change the P03 ledger.",
        "",
        "Evidence:",
        f"- Fixed windows: {len(result_rows)}",
        f"- Synthetic status: `{synthetic_status}`",
        f"- Calibration audit status: `{calibration_status}`",
        f"- Runtime gate: `{'PASS' if runtime_ok else 'FAIL'}`",
        f"- Matching shortfall: `{sum(int(row.get('matching_shortfall_total', 0) or 0) for row in result_rows)}`",
        "",
        "Route reasons:",
    ]
    decision.extend(f"- `{reason}`" for reason in reasons)
    if replay_errors:
        decision.extend(["", "Replay errors:"] + [f"- `{error}`" for error in replay_errors])
    (output / "selector_decision.md").write_text("\n".join(decision) + "\n", encoding="utf-8")
    print(json.dumps({"route": route, "windows": len(result_rows), "calibration_status": calibration_status, "synthetic_status": synthetic_status, "replay_errors": replay_errors}, sort_keys=True))
    return 0 if not replay_errors else 1


def _validate_master(path: Path) -> dict[str, object]:
    if not path.is_file():
        return {"status": "MISSING", "events": 0, "final_hash": ""}
    from uw_frontend.geometry.master_candidate_stream import MasterStreamValidator, master_event_from_dict
    validator = MasterStreamValidator()
    count = 0
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            validator.push(master_event_from_dict(json.loads(line)))
            count += 1
    return {"status": "PASS", "events": count, "final_hash": validator.previous_hash}


def _synthetic_report(output: Path) -> tuple[str, str]:
    commands = [
        [sys.executable, "-m", "uw_frontend.geometry._marginal_support_selftest"],
        [sys.executable, "-m", "uw_frontend.geometry._shadow_rankings_selftest"],
    ]
    sections = []
    status = "PASS"
    for command in commands:
        completed = subprocess.run(command, cwd=str(ROOT), text=True, capture_output=True)
        if completed.returncode != 0:
            status = "FAIL"
        sections.append("$ " + " ".join(command) + "\n\n" + completed.stdout + completed.stderr)
    text = "# P03A Selector Synthetic Test Report\n\n"
    text += f"Status: `{status}`\n\n"
    text += "Synthetic tests are contract tests only; they contain no trajectory outcome.\n\n"
    text += "\n\n".join("```text\n" + section + "\n```" for section in sections) + "\n"
    return text, status


def _read_csv(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        return []
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _read_json(path: Path) -> dict[str, object]:
    if not path.is_file():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("status\nEMPTY\n", encoding="utf-8")
        return
    fields = list(rows[0].keys())
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _display(path: Path) -> str:
    try:
        return path.relative_to(ROOT).as_posix()
    except ValueError:
        return str(path)


if __name__ == "__main__":
    raise SystemExit(main())
