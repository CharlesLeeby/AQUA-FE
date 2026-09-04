#!/usr/bin/env python3
"""Run full NTNU/AFRL P06 screening through the frozen ROS adapters."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import shlex
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

try:
    from scripts.run_p06_aqualoc_screening import audit_metrics
except ModuleNotFoundError:  # direct ``python scripts/run_p06_ros_screening.py`` entry
    from run_p06_aqualoc_screening import audit_metrics


ROOT = Path(__file__).resolve().parents[1]
BUNDLE = ROOT / "papers/ieee_sensors_journal_experiments"
ELIGIBILITY = BUNDLE / "data_eligibility_manifest.csv"
CAPACITY = BUNDLE / "p02/candidate_capacity_audit.csv"
CHECKSUMS = BUNDLE / "p02/input_reference_checksums.csv"
DEFAULT_OUTPUT = BUNDLE / "p06/screening_runs"
DEFAULT_WORK = Path("/mnt/data/AQUA-FE_WS/p06_screening_work")
CONFIG = ROOT / "uw_frontend/configs/klt_frontend.yaml"
ATTEMPT_ID_RE = re.compile(r"^attempt[0-9]{2}$")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("sequence", choices=("fjord_6", "cave_gennie", "bus_outside", "cemetery"))
    parser.add_argument("--output-root", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--work-root", default=str(DEFAULT_WORK))
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--keep-work-bags", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--attempt-id",
        default="",
        help="Versioned physical attempt directory for replacement AFRL runs",
    )
    args = parser.parse_args()

    result = run_sequence(
        args.sequence,
        Path(args.output_root),
        Path(args.work_root),
        force=bool(args.force),
        keep_work_bags=bool(args.keep_work_bags),
        dry_run=bool(args.dry_run),
        attempt_id=str(args.attempt_id),
    )
    print(
        f"P06_ROS_{result['status']} sequence={args.sequence} "
        f"rows={result.get('row_count', 0)} output={result['run_dir']}"
    )
    return 0 if result["status"] in {"PASS", "DRY_RUN"} else 1


def run_sequence(
    sequence: str,
    output_root: Path,
    work_root: Path,
    *,
    force: bool,
    keep_work_bags: bool,
    dry_run: bool,
    attempt_id: str = "",
) -> dict[str, object]:
    eligibility = unique_row(read_csv(ELIGIBILITY), sequence)
    capacity = unique_row(read_csv(CAPACITY), sequence)
    if capacity["low_normal_sequence_capacity_status"] != "CAPACITY_CANDIDATE":
        raise ValueError(f"{sequence} has no P06 candidate capacity")
    family = eligibility["dataset_family"]
    if family not in {"ntnu", "afrl"}:
        raise ValueError(f"unsupported ROS screening family: {family}")
    raw_path = ROOT / eligibility["raw_input_path"]
    if not raw_path.is_file():
        raise FileNotFoundError(raw_path)

    canonical_run_dir = output_root / family / sequence
    if attempt_id and not ATTEMPT_ID_RE.fullmatch(attempt_id):
        raise ValueError("attempt_id must match ^attempt[0-9]{2}$")
    if attempt_id and family != "afrl":
        raise ValueError("--attempt-id is reserved for AFRL replacement runs")
    existing_attempt_dirs = (
        [
            child
            for child in canonical_run_dir.iterdir()
            if child.is_dir() and ATTEMPT_ID_RE.fullmatch(child.name)
        ]
        if canonical_run_dir.is_dir()
        else []
    )
    if family == "afrl" and not attempt_id:
        # A failed AFRL run must never be silently reused for a replacement.
        if (canonical_run_dir / "screening_run.json").is_file() or existing_attempt_dirs:
            raise ValueError(
                f"AFRL replacement requires --attempt-id; existing run at {canonical_run_dir}"
            )
    run_dir = canonical_run_dir / attempt_id if attempt_id else canonical_run_dir
    canonical_work_dir = work_root / family / sequence
    work_dir = canonical_work_dir / attempt_id if attempt_id else canonical_work_dir
    if attempt_id:
        if run_dir.exists() and any(run_dir.iterdir()):
            raise FileExistsError(f"refusing to reuse non-empty attempt directory: {run_dir}")
        if work_dir.exists() and any(work_dir.iterdir()):
            raise FileExistsError(f"refusing to reuse non-empty attempt work directory: {work_dir}")
    output_metrics = run_dir / "metrics.csv"
    audit_path = run_dir / "screening_run.json"
    command_path = run_dir / "command.txt"
    process_log_path = run_dir / "process.log"
    duration = eligibility["duration_s"]
    env, command, work_metrics, temporary_bags = adapter_contract(
        family,
        sequence,
        duration,
        eligibility,
        work_dir,
    )
    base = {
        "schema_version": "isj-p06-screening-run-v1",
        "protocol_version": "isj-window-selection-v2",
        "dataset_family": family,
        "sequence": sequence,
        "split_role": eligibility["role"],
        "run_dir": relative(run_dir),
        "canonical_run_dir": relative(canonical_run_dir),
        "attempt_id": attempt_id or "default",
        "work_dir": str(work_dir),
        "metrics_path": relative(output_metrics),
        "process_log_path": relative(process_log_path),
        "command": shell_contract(env, command),
        "raw_input": {
            "path": eligibility["raw_input_path"],
            "registered_sha256": registered_digest(
                read_csv(CHECKSUMS),
                family,
                sequence,
                eligibility["raw_input_path"],
            ),
            "size_bytes": raw_path.stat().st_size,
        },
        "code": [
            file_record(CONFIG),
            file_record(ROOT / "uw_frontend/ros/export_vins_features.py"),
            file_record(
                ROOT
                / (
                    "scripts/run_ntnu_vins_eval.sh"
                    if family == "ntnu"
                    else "scripts/run_p06_afrl_direct_screening.py"
                )
            ),
            file_record(ROOT / "scripts/run_p06_ros_screening.py"),
            file_record(ROOT / "scripts/p06_window_selection_v2.py"),
        ],
        "outcome_boundary": "KLT_AND_IMAGE_QUALITY_ONLY_NO_LEARNED_OR_VINS_OUTCOME",
    }
    if dry_run:
        return {**base, "status": "DRY_RUN", "row_count": 0}

    run_dir.mkdir(parents=True, exist_ok=True)
    work_dir.mkdir(parents=True, exist_ok=True)
    command_path.write_text(shell_contract(env, command) + "\n", encoding="utf-8")
    if force:
        output_metrics.unlink(missing_ok=True)
        audit_path.unlink(missing_ok=True)
        process_log_path.unlink(missing_ok=True)
    if not output_metrics.is_file() or output_metrics.stat().st_size == 0:
        process_env = os.environ.copy()
        process_env.update(env)
        with process_log_path.open("wb") as process_log:
            completed = subprocess.run(
                command,
                cwd=ROOT,
                env=process_env,
                stdout=process_log,
                stderr=subprocess.STDOUT,
                check=False,
            )
        if completed.returncode != 0 or not work_metrics.is_file():
            result = {
                **base,
                "status": "FAILED",
                "returncode": completed.returncode,
                "generated_at_utc": now_utc(),
                "temporary_artifacts_preserved_after_failure": [
                    str(path) for path in temporary_bags if path.exists()
                ],
            }
            audit_path.write_text(json.dumps(result, sort_keys=True, indent=2) + "\n", encoding="utf-8")
            return result
        shutil.copy2(work_metrics, output_metrics)

    audit = audit_metrics(output_metrics)
    temporary_records = [temporary_record(path) for path in temporary_bags if path.is_file()]
    result = {
        **base,
        **audit,
        "status": "PASS" if audit["contract_pass"] else "FAIL",
        "metrics_sha256": sha256_file(output_metrics),
        "temporary_adapter_artifacts": temporary_records,
        "temporary_bags_retained": bool(keep_work_bags),
        "generated_at_utc": now_utc(),
    }
    audit_path.write_text(json.dumps(result, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    if result["status"] == "PASS" and not keep_work_bags:
        for path in temporary_bags:
            path.unlink(missing_ok=True)
    if family == "afrl" and attempt_id and result["status"] == "PASS" and not dry_run:
        pointer = canonical_run_dir / "current_attempt.json"
        pointer.parent.mkdir(parents=True, exist_ok=True)
        pointer_tmp = pointer.with_name(f".{pointer.name}.{attempt_id}.tmp")
        pointer_tmp.write_text(
            json.dumps(
                {
                    "schema_version": "isj-p06-current-attempt-v1",
                    "dataset_family": family,
                    "sequence": sequence,
                    "attempt_id": attempt_id,
                    "status": "PASS",
                    "run_dir": relative(run_dir),
                    "metrics_path": relative(output_metrics),
                    "screening_run_path": relative(audit_path),
                    "process_log_path": relative(process_log_path),
                    "metrics_sha256": result.get("metrics_sha256"),
                    "screening_run_sha256": sha256_file(audit_path),
                    "process_log_sha256": sha256_file(process_log_path)
                    if process_log_path.is_file()
                    else None,
                    "supersedes_attempt_id": "attempt01"
                    if attempt_id != "attempt01"
                    else None,
                    "updated_at_utc": now_utc(),
                },
                sort_keys=True,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        os.replace(pointer_tmp, pointer)
    return result


def adapter_contract(
    family: str,
    sequence: str,
    duration: str,
    eligibility: dict[str, str],
    work_dir: Path,
) -> tuple[dict[str, str], list[str], Path, list[Path]]:
    common = {
        "ROOT": str(ROOT),
        "RUN_DIR": str(work_dir),
        "RUN_VINS": "0",
        "FORCE_EXPORT": "1",
        "MEASUREMENT_SELECTION": "0",
        "FORMAL_THREE_LAYER_EXPORT": "0",
        "VINS_SAFE_SOURCE_SELECTION": "0",
        "FRONTEND_CONFIG": str(CONFIG),
        "PREPROCESS": "adaptive_clahe",
        "SEMIDENSE_FALLBACK_METHOD": "none",
        "EXPORT_MAX_FEATURES": "350",
        "EXPORT_MIN_AGE": "0",
        "FRAME_OFFSET": "0",
        "PROCESS_SKIPPED_FRAMES": "0",
        "BACKEND_QUALITY_MODE": "default",
    }
    if family == "ntnu":
        common["RAW_BAG"] = str(ROOT / eligibility["raw_input_path"])
        command = [
            "bash",
            "scripts/run_ntnu_vins_eval.sh",
            "external",
            sequence,
            "0",
            duration,
            "klt",
            "1",
        ]
        return common, command, work_dir / "frontend_metrics.csv", [work_dir / "features.bag"]

    raw = ROOT / eligibility["raw_input_path"]
    calibration = eligibility["calibration_paths"].split(";")[0]
    image_topic = (
        "/cam_fl/image_raw/compressed"
        if sequence == "cemetery"
        else "/slave1/image_raw/compressed"
    )
    common.update(
        {
            "RAW_BAG": str(raw),
            "CAMCHAIN": str(ROOT / calibration),
            "CAMERA_KEY": "cam0",
            "SRC_IMAGE_TOPIC": image_topic,
            "AFRL_ADAPTER": "isj-p06-afrl-direct-compressed-v1",
        }
    )
    command = [
        "python3",
        "scripts/run_p06_afrl_direct_screening.py",
        "--raw-bag",
        str(raw),
        "--camchain",
        str(ROOT / calibration),
        "--camera-key",
        "cam0",
        "--image-topic",
        image_topic,
        "--duration",
        duration,
        "--work-dir",
        str(work_dir),
    ]
    return common, command, work_dir / "frontend_metrics.csv", [work_dir / "features.bag"]


def shell_contract(env: dict[str, str], command: list[str]) -> str:
    assignments = " ".join(
        f"{key}={shlex.quote(value)}" for key, value in sorted(env.items())
    )
    return f"{assignments} {shlex.join(command)}"


def unique_row(rows: list[dict[str, str]], sequence: str) -> dict[str, str]:
    matches = [row for row in rows if row.get("sequence") == sequence]
    if len(matches) != 1:
        raise ValueError(f"expected one manifest row for {sequence}, found {len(matches)}")
    return matches[0]


def registered_digest(
    rows: list[dict[str, str]],
    family: str,
    sequence: str,
    path: str,
) -> str:
    matches = [
        row
        for row in rows
        if row.get("dataset_family") == family
        and row.get("sequence") == sequence
        and row.get("path") == path
        and row.get("artifact_role") == "raw_input"
    ]
    if len(matches) != 1 or matches[0].get("status") != "PASS":
        raise ValueError(f"missing registered input digest for {family}/{sequence}")
    return matches[0]["digest"]


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def file_record(path: Path) -> dict[str, object]:
    return {
        "path": relative(path),
        "sha256": sha256_file(path),
        "size_bytes": path.stat().st_size,
    }


def temporary_record(path: Path) -> dict[str, object]:
    return {
        "path": str(path),
        "sha256": sha256_file(path),
        "size_bytes": path.stat().st_size,
        "disposition": "delete_after_success_unless_keep_work_bags",
    }


def relative(path: Path) -> str:
    return path.resolve().relative_to(ROOT).as_posix()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def now_utc() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


if __name__ == "__main__":
    raise SystemExit(main())
