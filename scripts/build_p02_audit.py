#!/usr/bin/env python3
"""Build the machine-readable P02 history, eligibility, and reference audit.

The script intentionally stops at a candidate capacity audit. It does not
decode held-out images, run learned frontends, or create the P06 dataset
manifest.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import math
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

try:
    from scripts.p02_window_selection import TAU_LOW, TAU_NORMAL, score_metric_rows
except ModuleNotFoundError:  # direct ``python scripts/build_p02_audit.py`` entry
    from p02_window_selection import TAU_LOW, TAU_NORMAL, score_metric_rows


ROOT = Path(__file__).resolve().parents[1]
BUNDLE = ROOT / "papers/ieee_sensors_journal_experiments"
P02 = BUNDLE / "p02"
DATA = ROOT / "datasets/full_downloads"


@dataclass(frozen=True)
class Candidate:
    dataset_family: str
    data_domain: str
    sequence: str
    raw_path: Path | None
    raw_format: str
    reference_path: Path | None
    reference_type: str
    reference_method: str
    reference_independence: str
    reference_frame: str
    metric_scale: str
    nominal_reference_rate_hz: float | None
    nominal_image_rate_hz: float | None
    nominal_imu_rate_hz: float | None
    nominal_estimate_rate_hz: float | None
    calibration_paths: tuple[Path, ...]
    license_name: str
    license_status: str
    duration_s: float | None
    role: str
    eligibility: str
    decision_reason: str
    evidence_paths: tuple[Path, ...]
    expected_raw_size: int | None = None
    source_digest: str = ""
    source_digest_origin: str = ""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--hash-local-inputs", action="store_true")
    args = parser.parse_args()
    P02.mkdir(parents=True, exist_ok=True)

    commands = _write_search_commands()
    history = _build_history_manifest()
    _write_history(history)
    candidates = _build_candidates()
    checksums = _write_eligibility_and_reference(candidates, args.hash_local_inputs)
    _write_capacity_audit(candidates, history)
    _write_development_score_audit()
    _write_candidate_summary(candidates, history)
    _write_b1_hash_manifest()
    print(f"history_rows={len(history)} candidate_rows={len(candidates)} checksum_rows={len(checksums)}")
    print(f"wrote {P02}")
    return 0


def _build_history_manifest() -> list[dict[str, str]]:
    matches: dict[tuple[str, str, str, str, str], dict[str, object]] = {}
    for path in _history_paths():
        _record_windows_from_text(path, _rel(path), matches)
        if _read_history_content(path):
            try:
                if path.stat().st_size <= 8_000_000:
                    text = path.read_text(encoding="utf-8", errors="ignore")
                else:
                    text = ""
            except OSError:
                text = ""
            if text:
                for line_number, line in enumerate(text.splitlines(), 1):
                    _record_windows_from_text(
                        path,
                        f"{_rel(path)}:{line_number}",
                        matches,
                        line,
                    )

    rows: list[dict[str, str]] = []
    for key in sorted(matches):
        item = matches[key]
        paths = sorted(item["paths"])
        rows.append(
            {
                "dataset_family": key[0],
                "sequence": key[1],
                "start": key[2],
                "end": key[3],
                "window_unit": key[4],
                "prior_artifact_count": str(len(paths)),
                "prior_learned_seen": str(bool(item["learned"])).lower(),
                "prior_vins_seen": str(bool(item["vins"])).lower(),
                "prior_parameter_use": str(bool(item["parameter"])).lower(),
                "allowed_role": "DEVELOPMENT_ONLY",
                "evidence_paths": _join_evidence(paths),
                "decision_reason": (
                    "Prior artifact or parameter/search reference found before P02 freeze; "
                    "exclude exact window from confirmatory denominator."
                ),
            }
        )
    return rows


def _read_history_content(path: Path) -> bool:
    """Avoid reparsing large per-frame logs; path identity is still audited."""

    suffix = path.suffix.lower()
    if suffix not in {".md", ".csv", ".json", ".jsonl", ".sh", ".py", ".txt", ".yaml", ".yml"}:
        return False
    if path.stat().st_size > 8_000_000:
        return False
    parts = set(path.parts)
    if "logs" in parts and suffix == ".csv":
        return False
    if "logs" in parts and suffix not in {".md", ".txt", ".json", ".jsonl"}:
        return False
    return True


def _history_paths() -> Iterable[Path]:
    roots = [ROOT / "logs", ROOT / "papers", ROOT / "正反例窗口整理", ROOT / "scripts"]
    for root in roots:
        if not root.exists():
            continue
        for path in root.rglob("*"):
            if path.is_file() and BUNDLE not in path.parents:
                yield path


def _record_windows_from_text(
    path: Path,
    evidence: str,
    matches: dict[tuple[str, str, str, str, str], dict[str, object]],
    text: str | None = None,
) -> None:
    context = f"{path.as_posix()} {text or ''}"
    lower = context.lower()
    found: list[tuple[str, str, str, str, str]] = []

    for match in re.finditer(
        r"(?<![a-z0-9])([ah])(\d{1,2})[_ -](\d+(?:\.\d+)?)[_-](\d+(?:\.\d+)?)(?![a-z0-9])",
        context,
        flags=re.IGNORECASE,
    ):
        prefix, number, start, end = match.groups()
        family = "aqualoc_archaeology" if prefix.lower() == "a" else "aqualoc_harbor"
        found.append((family, f"{prefix.upper()}{int(number):02d}", start, end, "frame"))
    for match in re.finditer(
        r"(?<![a-z0-9])(?:archaeo|harbor)(?:_sequence)?[_ -]?(\d{1,2})[_ -](\d+(?:\.\d+)?)[_-](\d+(?:\.\d+)?)(?![a-z0-9])",
        context,
        flags=re.IGNORECASE,
    ):
        name, start, end = match.groups()
        family = "aqualoc_archaeology" if "archaeo" in match.group(0).lower() else "aqualoc_harbor"
        prefix = "A" if family.endswith("archaeology") else "H"
        found.append((family, f"{prefix}{int(name):02d}", start, end, "frame"))

    for match in re.finditer(
        r"(?i)(fjord|mclab)[_-]?(\d+).*?s(\d+(?:p\d+|(?:\.\d+)?))[_-]?d(\d+(?:p\d+|(?:\.\d+)?))",
        context,
    ):
        environment, number, start, duration = match.groups()
        end = _decimal_add(start, duration)
        found.append(("ntnu", f"{environment.lower()}_{int(number)}", start, end, "second"))
    for match in re.finditer(
        r"(?i)(fjord|mclab)[_-]?(\d+)[_-](\d+(?:\.\d+)?)[_-](\d+(?:\.\d+)?)(?![a-z0-9])",
        context,
    ):
        environment, number, start, end = match.groups()
        found.append(("ntnu", f"{environment.lower()}_{int(number)}", start, end, "second"))

    for match in re.finditer(
        r"(?i)(?:cirs[_ -]?)s(\d+(?:\.\d+)?)[_-]d(\d+(?:\.\d+)?)",
        context,
    ):
        start, duration = match.groups()
        found.append(("cirs", "cala_viuda", start, _decimal_add(start, duration), "second"))
    for match in re.finditer(
        r"(?i)(?:orientkaj|uvvid).*?s(\d+(?:\.\d+)?)[_-]d(\d+(?:\.\d+)?)",
        context,
    ):
        start, duration = match.groups()
        found.append(("uvvid", "orientkaj_run1", start, _decimal_add(start, duration), "second"))
    for match in re.finditer(
        r"(?i)(?:tank|short_test).*?s(\d+(?:\.\d+)?)[_-]d(\d+(?:\.\d+)?)",
        context,
    ):
        start, duration = match.groups()
        found.append(("tank", "short_test", start, _decimal_add(start, duration), "second"))
    for match in re.finditer(
        r"(?i)(?:afrl[_ -]?)?(cave|bus|cemetery|cemfr|cemfl|fr|fl)[_-]?s?(\d+(?:\.\d+)?)[_-]d?(\d+(?:\.\d+)?)",
        context,
    ):
        sequence, start, duration = match.groups()
        found.append(("afrl", _normalize_afrl_sequence(sequence), start, _decimal_add(start, duration), "second"))
    for match in re.finditer(r"(?i)\b(fr|fl)(\d+(?:\.\d+)?)[_-](\d+(?:\.\d+)?)\b", context):
        sequence, start, end = match.groups()
        found.append(("afrl", f"cemetery_{sequence.lower()}", start, end, "second"))

    for key in set(found):
        item = matches.setdefault(key, {"paths": set(), "learned": False, "vins": False, "parameter": False})
        item["paths"].add(evidence)
        item["learned"] = bool(item["learned"]) or bool(
            re.search(r"learn|xfeat|loftr|superpoint|sp[_-]?lg|sidecar|proposed|hybrid|drop", lower)
        )
        item["vins"] = bool(item["vins"]) or bool(re.search(r"vins|ape|rpe|vio|feature.?bag|trajectory", lower))
        item["parameter"] = bool(item["parameter"]) or bool(
            re.search(r"config|gate|ablation|tune|search|screen|probe|positive|negative|final|frozen|arbitration", lower)
        )


def _build_candidates() -> list[Candidate]:
    candidates: list[Candidate] = []
    aqualoc = DATA / "aqualoc"
    aqualoc_calib = (
        aqualoc / "Archaeological_site_sequences/archaeo_calibration_files/archaeo_imu_camera_calib.yaml",
        aqualoc / "Archaeological_site_sequences/archaeo_calibration_files/archaeo_camera_calib.yaml",
        aqualoc / "Archaeological_site_sequences/archaeo_calibration_files/archaeo_imu_noises.yaml",
    )
    harbor_calib = (
        aqualoc / "Harbor_sites_sequences/harbor_calibration_files/harbor_imu_camera_calib.yaml",
        aqualoc / "Harbor_sites_sequences/harbor_calibration_files/harbor_camera_calib.yaml",
        aqualoc / "Harbor_sites_sequences/harbor_calibration_files/harbor_imu_noises.yaml",
    )
    for number in range(1, 11):
        number_text = f"{number:02d}"
        raw = aqualoc / f"Archaeological_site_sequences/archaeo_sequence_{number}_raw_data.tar.gz"
        if number == 6:
            raw = ROOT / "datasets/aqualoc/samples/archaeo_sequence_06_raw_data.tar.gz"
        reference = aqualoc / f"Archaeological_site_sequences/archaeo_groundtruth_files/new_archaeo_colmap_traj_sequence_{number_text}.txt"
        duration = _aqualoc_duration(reference, 20.0)
        candidates.append(
            _aqualoc_candidate(
                "aqualoc_archaeology", "AQUALOC archaeology", f"A{number:02d}", raw, reference,
                aqualoc_calib, 1.0, duration, "AQUALOC README + raw/reference files",
            )
        )
    for number in range(1, 8):
        number_text = f"{number:02d}"
        raw = aqualoc / f"Harbor_sites_sequences/harbor_sequence_{number:02d}_raw_data.tar.gz"
        if number in {6, 7}:
            raw = ROOT / f"datasets/aqualoc/samples/harbor_sequence_{number:02d}_raw_data.tar.gz"
        reference = aqualoc / f"Harbor_sites_sequences/harbor_groundtruth_files/new_harbor_colmap_traj_sequence_{number_text}.txt"
        duration = _aqualoc_duration(reference, 20.0)
        candidates.append(
            _aqualoc_candidate(
                "aqualoc_harbor", "AQUALOC harbor", f"H{number:02d}", raw, reference,
                harbor_calib, 4.0, duration, "AQUALOC README + raw/reference files",
            )
        )

    ntnu = DATA / "ntnu_hf"
    ntnu_calib = (
        ntnu / "calibrations/cam0_cam1_stereo/intrinsics_water/camchain-stereo-intrinsics-underwater.yaml",
        ntnu / "calibrations/cam0_cam1_stereo/extrinsics_air/camchain-imucam-stereo-extrinsics-air.yaml",
        ntnu / "calibrations/cam0_cam1_stereo/extrinsics_air/imu-stereo-extrinsics-air.yaml",
    )
    durations = {1: 312.0, 2: 499.0, 3: 272.0, 4: 411.0, 5: 440.0, 6: 638.0}
    for number in range(1, 7):
        sequence = f"fjord_{number}"
        raw = ntnu / f"subset-fjord/{sequence}/{sequence}.bag"
        reference = ntnu / f"subset-fjord/{sequence}/{sequence}_baseline.tum"
        candidates.append(_ntnu_candidate(sequence, raw, reference, ntnu_calib, durations[number], "NTNU README"))
    for number, duration in ((1, 390.0), (2, 304.0)):
        sequence = f"mclab_{number}"
        raw = ntnu / f"subset-mclab/{sequence}/{sequence}.bag"
        reference = ntnu / f"subset-mclab/{sequence}/{sequence}_baseline.tum"
        candidates.append(_ntnu_candidate(sequence, raw, reference, ntnu_calib, duration, "NTNU README"))

    afrl = DATA / "afrl_hf"
    afrl_calib = (
        afrl / "camera_imu_parameters/camchain_cave_gennie.yaml",
        afrl / "camera_imu_parameters/imu.yaml",
    )
    for sequence, gt_name, raw_name in (
        ("cave_gennie", "cave_gennie.txt", "cave_gennie.bag"),
        ("bus_outside", "bus_outside.txt", "bus_outside.bag"),
        ("cemetery", "cemetery.txt", "cemetery.bag"),
    ):
        raw = afrl / f"ros1_bags/{raw_name}"
        reference = afrl / f"colmap_groundtruth/{gt_name}"
        duration = _afrl_duration(reference, sequence)
        candidates.append(_afrl_candidate(sequence, raw, reference, afrl_calib, duration, "AFRL README"))

    candidates.extend(_supplementary_candidates())
    return candidates


def _aqualoc_candidate(family: str, domain: str, sequence: str, raw: Path, reference: Path, calib: tuple[Path, ...], rate: float, duration: float | None, evidence: str) -> Candidate:
    return Candidate(
        dataset_family=family, data_domain=domain, sequence=sequence, raw_path=raw,
        raw_format="AQUALOC raw_data tar.gz", reference_path=reference,
        reference_type="camera trajectory", reference_method="offline COLMAP",
        reference_independence="method-independent but image-derived; not sensor-independent",
        reference_frame="world_T_camera", metric_scale="updated AQUALOC COLMAP scale corrected with depth metadata",
        nominal_reference_rate_hz=rate, nominal_image_rate_hz=20.0, nominal_imu_rate_hz=200.0,
        nominal_estimate_rate_hz=10.0, calibration_paths=calib, license_name="AQUALOC public dataset",
        license_status="citation/readme terms; explicit SPDX license not found locally", duration_s=duration,
        role="SEQUENCE_HELD_OUT_WINDOW_CANDIDATE", eligibility="ELIGIBLE_WITH_REFERENCE_CAVEAT",
        decision_reason="Raw archive, updated COLMAP reference, and Kalibr calibration are present; exact prior windows are excluded.",
        evidence_paths=(ROOT / "datasets/full_downloads/aqualoc/README.md", reference, *calib),
    )


def _ntnu_candidate(sequence: str, raw: Path, reference: Path, calib: tuple[Path, ...], duration: float, evidence: str) -> Candidate:
    return Candidate(
        dataset_family="ntnu", data_domain="NTNU underwater VI", sequence=sequence, raw_path=raw,
        raw_format="ROS1 bag", reference_path=reference, reference_type="camera trajectory",
        reference_method="ReAqROVIO four-camera+IMU baseline", reference_independence="separate method and sensor subset, not external sensor ground truth",
        reference_frame="world_T_cam0", metric_scale="metric baseline trajectory supplied by dataset",
        nominal_reference_rate_hz=50.0, nominal_image_rate_hz=13.3333333, nominal_imu_rate_hz=100.0,
        nominal_estimate_rate_hz=6.6666667, calibration_paths=calib, license_name="BSD-3-Clause",
        license_status="dataset README SPDX metadata verified", duration_s=duration, role="SEQUENCE_HELD_OUT_WINDOW_CANDIDATE",
        eligibility="ELIGIBLE_WITH_REFERENCE_CAVEAT", decision_reason="Complete ROS1 bag, baseline TUM, and Kalibr camera-IMU calibration are present; reference is ReAqROVIO pseudo-GT.",
        evidence_paths=(DATA / "ntnu_hf/README.md", reference, *calib),
        source_digest_origin="HuggingFace LFS SHA-256 in hf_filelist_with_sizes.tsv",
    )


def _afrl_candidate(sequence: str, raw: Path, reference: Path, calib: tuple[Path, ...], duration: float | None, evidence: str) -> Candidate:
    return Candidate(
        dataset_family="afrl", data_domain="AFRL stereo VI", sequence=sequence, raw_path=raw,
        raw_format="ROS1 bag", reference_path=reference, reference_type="camera trajectory",
        reference_method="offline COLMAP with stereo-baseline scale correction", reference_independence="method-independent but image-derived approximate reference; not sensor-independent",
        reference_frame="world_T_camera", metric_scale="stereo baseline scale correction documented by dataset",
        nominal_reference_rate_hz=5.0, nominal_image_rate_hz=15.0, nominal_imu_rate_hz=100.0,
        nominal_estimate_rate_hz=7.5, calibration_paths=calib, license_name="MIT",
        license_status="dataset README SPDX metadata verified", duration_s=duration, role="SEQUENCE_HELD_OUT_WINDOW_CANDIDATE",
        eligibility="ELIGIBLE_WITH_REFERENCE_CAVEAT", decision_reason="Complete ROS1 bag, COLMAP reference, camera-IMU calibration, and stereo scale metadata are present.",
        evidence_paths=(DATA / "afrl_hf/README.md", reference, raw, *calib),
        source_digest_origin="HuggingFace LFS SHA-256 in hf_filelist_with_sizes.tsv",
    )


def _supplementary_candidates() -> list[Candidate]:
    return [
        Candidate(
            "tank", "Tank sample", "short_test", DATA / "tank/short_test/short_test.bag", "ROS1 bag",
            None, "none", "none", "no independent trajectory reference", "unknown", "not applicable",
            None, None, None, None, (DATA / "tank/short_test/short_test.yaml",), "request-gated public sample",
            "official full dataset request required", 15.0, "FRONTEND_RUNTIME_ONLY", "NOT_ELIGIBLE_PRIMARY_APE",
            "Short sample has no independent GT and is below the 42 s 1 Hz support floor.",
            (DATA / "tank/download_status_20260616.md", DATA / "tank/short_test/short_test.yaml"),
        ),
        Candidate(
            "uma_vi", "UMA-VI sample", "sample", DATA / "uma_vi/sample/sample", "image+IMU directory",
            None, "none", "none", "sample has no independent trajectory reference", "unknown", "not applicable",
            None, 1.25, 200.0, None, (DATA / "uma_vi/calibration_files/camchain-imu-ueye.yaml",), "dataset page terms",
            "license not machine-verified", 80.0, "FRONTEND_RUNTIME_ONLY", "NOT_ELIGIBLE_PRIMARY_APE",
            "Local sample is downsampled and contains no independent GT; retain only for frontend/runtime checks.",
            (DATA / "uma_vi/sample/readme.txt", DATA / "uma_vi/calibration_files/camchain-imu-ueye.yaml"),
        ),
        Candidate(
            "uvvid", "UVVID visual-inertial", "orientkaj_run1", DATA / "uvvid/files/visual-inertial/Orientkaj/Run_1", "video+ROS bags",
            None, "derived local odometry", "post-processed UVVID stabilization", "derived reference; not independent", "unknown", "not independently scaled",
            None, 20.0, 100.0, None, (DATA / "uvvid/files/visual-inertial/Orientkaj/Run_1/left_calibration.yaml",), "CC BY",
            "dataset README metadata verified", 120.0, "FRONTEND_RUNTIME_ONLY", "NOT_ELIGIBLE_PRIMARY_APE",
            "Reference is derived stabilization and no independent GT contract is present; retain as supplementary runtime data.",
            (DATA / "uvvid/files/root/63346924_README.txt", DATA / "uvvid/files/visual-inertial/README.md"),
        ),
        Candidate(
            "cirs", "CIRS Girona", "cala_viuda", DATA / "cirs_caves/cirs_girona_cala_viuda.zip", "ROS package/archive",
            None, "none", "none", "reference provenance unresolved", "unknown", "not independently scaled",
            None, 10.0, 100.0, None, (), "dataset package terms", "license not machine-verified", 120.0,
            "FRONTEND_RUNTIME_ONLY", "NOT_ELIGIBLE_PRIMARY_APE",
            "Local package has image/IMU material but no independently auditable reference trajectory contract.",
            (DATA / "cirs_caves/cirs_girona_cala_viuda.zip",),
        ),
        Candidate(
            "flsea_vi", "FLSea-VI", "metadata_only", None, "not staged", None, "unknown", "unknown",
            "not auditable locally", "unknown", "unknown", None, None, None, None, (), "Kaggle terms",
            "credentials and data not staged", None, "EXTERNAL_HELD_OUT_METADATA_ONLY", "NOT_READY_EXTERNAL",
            "Only metadata placeholder exists; no raw input, reference, calibration, or checksum is locally auditable.",
            (ROOT / "datasets/download_manifest.json",),
        ),
    ]


def _write_history(rows: list[dict[str, str]]) -> None:
    fields = [
        "dataset_family", "sequence", "start", "end", "window_unit", "prior_artifact_count",
        "prior_learned_seen", "prior_vins_seen", "prior_parameter_use", "allowed_role",
        "evidence_paths", "decision_reason",
    ]
    _write_csv(BUNDLE / "history_exclusion_manifest.csv", fields, rows)


def _write_eligibility_and_reference(candidates: list[Candidate], hash_local: bool) -> list[dict[str, str]]:
    eligibility_fields = [
        "manifest_schema", "dataset_family", "data_domain", "sequence", "role", "eligibility",
        "raw_input_path", "raw_format", "raw_exists", "raw_size_bytes", "expected_raw_size_bytes",
        "raw_integrity", "reference_path", "reference_type", "reference_method", "reference_independence",
        "reference_frame", "metric_scale", "nominal_reference_rate_hz", "nominal_image_rate_hz",
        "nominal_imu_rate_hz", "nominal_estimate_rate_hz", "duration_s", "calibration_paths",
        "license_name", "license_status", "evidence_paths", "decision_reason",
    ]
    reference_fields = [
        "audit_schema", "dataset_family", "data_domain", "sequence", "raw_input_path", "raw_format",
        "raw_exists", "raw_size_bytes", "raw_integrity", "reference_path", "reference_exists",
        "reference_type", "reference_method", "reference_independence", "reference_frame", "metric_scale",
        "reference_raw_count", "reference_unique_count", "reference_duplicate_count",
        "reference_start_s", "reference_end_s", "reference_duration_s",
        "observed_reference_rate_hz", "observed_max_reference_gap_s",
        "nominal_reference_rate_hz", "evaluation_rate_hz", "max_reference_gap_s",
        "nominal_estimate_rate_hz", "max_estimate_interp_gap_s", "nominal_image_rate_hz", "nominal_imu_rate_hz",
        "timestamp_offset_s", "image_imu_sync_status", "calibration_status", "license_status",
        "reference_sha256", "eligibility", "decision_reason", "evidence_paths",
    ]
    checksum_fields = [
        "checksum_schema", "artifact_role", "dataset_family", "sequence", "path", "size_bytes",
        "algorithm", "digest", "digest_origin", "local_size_verified", "status",
    ]
    eligibility_rows: list[dict[str, str]] = []
    reference_rows: list[dict[str, str]] = []
    checksum_rows: list[dict[str, str]] = []
    hf_digests = _hf_digests()
    aqualoc_sizes = _aqualoc_sizes()
    for candidate in candidates:
        raw_exists = bool(candidate.raw_path and candidate.raw_path.exists())
        raw_size = _artifact_size(candidate.raw_path) if raw_exists and candidate.raw_path else None
        expected = (
            candidate.expected_raw_size
            or aqualoc_sizes.get(candidate.raw_path.name if candidate.raw_path else "")
            or (hf_digests.get(_hf_key(candidate.raw_path)) or {}).get("size")
        )
        raw_integrity = "MISSING"
        if raw_exists:
            if expected is None:
                raw_integrity = "PRESENT_SIZE_UNVERIFIED"
            else:
                raw_integrity = "SIZE_MATCH" if expected == raw_size else "SIZE_MISMATCH"
        reference_exists = bool(candidate.reference_path and candidate.reference_path.exists())
        reference_stats = _reference_stats(candidate)
        ref_digest = _digest(candidate.reference_path, hash_local) if reference_exists else ""
        evidence = _join_evidence([_rel(path) for path in candidate.evidence_paths])
        eligibility_rows.append(
            {
                "manifest_schema": "isj-data-eligibility-v1",
                "dataset_family": candidate.dataset_family, "data_domain": candidate.data_domain,
                "sequence": candidate.sequence, "role": candidate.role, "eligibility": candidate.eligibility,
                "raw_input_path": _rel(candidate.raw_path), "raw_format": candidate.raw_format,
                "raw_exists": str(raw_exists).lower(), "raw_size_bytes": _str(raw_size),
                "expected_raw_size_bytes": _str(expected), "raw_integrity": raw_integrity,
                "reference_path": _rel(candidate.reference_path), "reference_type": candidate.reference_type,
                "reference_method": candidate.reference_method, "reference_independence": candidate.reference_independence,
                "reference_frame": candidate.reference_frame, "metric_scale": candidate.metric_scale,
                "nominal_reference_rate_hz": _str(candidate.nominal_reference_rate_hz),
                "nominal_image_rate_hz": _str(candidate.nominal_image_rate_hz), "nominal_imu_rate_hz": _str(candidate.nominal_imu_rate_hz),
                "nominal_estimate_rate_hz": _str(candidate.nominal_estimate_rate_hz), "duration_s": _str(candidate.duration_s),
                "calibration_paths": _join_evidence([_rel(path) for path in candidate.calibration_paths]),
                "license_name": candidate.license_name, "license_status": candidate.license_status,
                "evidence_paths": evidence, "decision_reason": candidate.decision_reason,
            }
        )
        reference_rows.append(
            {
                "audit_schema": "isj-reference-audit-v1", "dataset_family": candidate.dataset_family,
                "data_domain": candidate.data_domain, "sequence": candidate.sequence,
                "raw_input_path": _rel(candidate.raw_path), "raw_format": candidate.raw_format,
                "raw_exists": str(raw_exists).lower(), "raw_size_bytes": _str(raw_size), "raw_integrity": raw_integrity,
                "reference_path": _rel(candidate.reference_path), "reference_exists": str(reference_exists).lower(),
                "reference_type": candidate.reference_type, "reference_method": candidate.reference_method,
                "reference_independence": candidate.reference_independence, "reference_frame": candidate.reference_frame,
                "metric_scale": candidate.metric_scale, **reference_stats, "timestamp_offset_s": "0.0",
                "image_imu_sync_status": _sync_status(candidate), "calibration_status": _calibration_status(candidate),
                "license_status": candidate.license_status, "reference_sha256": ref_digest,
                "eligibility": candidate.eligibility, "decision_reason": candidate.decision_reason,
                "evidence_paths": evidence,
            }
        )
        for role, path in (("raw_input", candidate.raw_path), ("reference", candidate.reference_path)):
            if path is not None and path.exists():
                digest, origin = _artifact_digest(path, candidate, role, hash_local, hf_digests)
                checksum_rows.append(
                    {
                        "checksum_schema": "isj-input-reference-checksum-v1", "artifact_role": role,
                        "dataset_family": candidate.dataset_family, "sequence": candidate.sequence,
                        "path": _rel(path), "size_bytes": str(_artifact_size(path)), "algorithm": "SHA-256",
                        "digest": digest, "digest_origin": origin,
                        "local_size_verified": (
                            str(expected == _artifact_size(path)).lower()
                            if role == "raw_input" and expected is not None
                            else ("" if role == "raw_input" else "true")
                        ),
                        "status": "PASS" if digest else "PENDING",
                    }
                )
        for path in candidate.calibration_paths:
            if path.exists():
                checksum_rows.append(
                    {
                        "checksum_schema": "isj-input-reference-checksum-v1", "artifact_role": "calibration",
                        "dataset_family": candidate.dataset_family, "sequence": candidate.sequence,
                        "path": _rel(path), "size_bytes": str(path.stat().st_size), "algorithm": "SHA-256",
                        "digest": _digest(path, True), "digest_origin": "local_file", "local_size_verified": "true", "status": "PASS",
                    }
                )
    _write_csv(BUNDLE / "data_eligibility_manifest.csv", eligibility_fields, eligibility_rows)
    _write_csv(BUNDLE / "reference_audit.csv", reference_fields, reference_rows)
    _write_csv(P02 / "input_reference_checksums.csv", checksum_fields, _dedupe_checksum_rows(checksum_rows))
    return checksum_rows


def _write_capacity_audit(candidates: list[Candidate], history: list[dict[str, str]]) -> None:
    fields = [
        "dataset_family", "data_domain", "sequence", "role", "eligibility", "duration_s",
        "window_duration_s", "gross_nonoverlap_windows", "history_overlap_windows",
        "available_candidate_windows", "max_per_sequence_cap", "reference_rate_hz",
        "low_normal_sequence_capacity_status", "decision_reason",
    ]
    rows: list[dict[str, str]] = []
    for candidate in candidates:
        if candidate.duration_s is None:
            continue
        gross = int(math.floor(candidate.duration_s / 45.0))
        excluded_indices: set[int] = set()
        if candidate.eligibility == "ELIGIBLE_WITH_REFERENCE_CAVEAT":
            for window in history:
                if window["dataset_family"] != candidate.dataset_family or window["sequence"] != candidate.sequence:
                    continue
                start = _window_seconds(window, candidate)
                end = _window_end_seconds(window, candidate)
                if end <= start:
                    continue
                for index in range(gross):
                    ws, we = index * 45.0, (index + 1) * 45.0
                    if ws < end and we > start:
                        excluded_indices.add(index)
        excluded = len(excluded_indices)
        available = gross - excluded if candidate.eligibility == "ELIGIBLE_WITH_REFERENCE_CAVEAT" else 0
        capacity_status = "CAPACITY_CANDIDATE" if available else "NO_CAPACITY"
        reason = "P06 must still run frozen KLT-only screening; this row proves only metadata/time capacity."
        if candidate.eligibility != "ELIGIBLE_WITH_REFERENCE_CAVEAT":
            capacity_status = "NOT_PRIMARY_ELIGIBLE"
            reason = "Sequence lacks the primary trajectory-reference contract and cannot contribute to the confirmatory APE matrix."
        rows.append(
            {
                "dataset_family": candidate.dataset_family, "data_domain": candidate.data_domain,
                "sequence": candidate.sequence, "role": candidate.role, "eligibility": candidate.eligibility,
                "duration_s": _str(candidate.duration_s), "window_duration_s": "45.0",
                "gross_nonoverlap_windows": str(gross), "history_overlap_windows": str(excluded),
                "available_candidate_windows": str(available), "max_per_sequence_cap": str(min(4, available)),
                "reference_rate_hz": _str(candidate.nominal_reference_rate_hz),
                "low_normal_sequence_capacity_status": capacity_status,
                "decision_reason": reason,
            }
        )
    _write_csv(P02 / "candidate_capacity_audit.csv", fields, rows)


def _write_development_score_audit() -> None:
    fixtures = [
        ("aqualoc_a06_2210_2460", "aqualoc_archaeology", "A06", "metrics.csv", 20.0, "primary"),
        ("aqualoc_h06_2280_2490", "aqualoc_harbor", "H06", "metrics.csv", 20.0, "primary"),
        ("aqualoc_h07_1660_1720", "aqualoc_harbor", "H07", "metrics.csv", 20.0, "sensitivity"),
        ("afrl_cemetery_fr_005_410", "afrl", "cemetery_fr", "metrics_r2.csv", 3.0, "primary"),
        ("afrl_cemetery_fl_080_319", "afrl", "cemetery_fl", "metrics.csv", 3.0, "primary"),
        ("tank_short_000_299", "tank", "short_test", "metrics.csv", 20.0, "sensitivity"),
        ("uvvid_cannon_000_179", "uvvid", "cannon_bottom", "metrics_r2.csv", 2.0, "sensitivity"),
    ]
    fields = [
        "fixture_role", "fixture_id", "dataset_family", "sequence", "metrics_path", "row_count",
        "input_rate_hz", "grid_coverage_p50", "dropout_ratio_p50", "flat_region_ratio_p50",
        "degradation_score_p50", "frame_score_q25", "window_score_q50", "frame_score_q75",
        "absolute_stratum", "notes",
    ]
    rows = []
    # Keep the fixture table readable as (id, family, sequence, file, rate, role).
    # The previous unpacking treated the id as the role and the role as the
    # sequence, which silently corrupted the audit rows after all screenings
    # had completed.
    for fixture_id, family, sequence, file_name, rate, fixture_role in fixtures:
        path = P02 / "development_screening" / fixture_id / file_name
        if not path.exists():
            raise FileNotFoundError(path)
        metrics = list(csv.DictReader(path.open(encoding="utf-8")))
        components = score_metric_rows(metrics)
        score = components.score
        absolute = "low" if score >= TAU_LOW else "normal" if score <= TAU_NORMAL else "unclassified"
        rows.append(
            {
                "fixture_role": fixture_role, "fixture_id": fixture_id, "dataset_family": family,
                "sequence": sequence, "metrics_path": _rel(path), "row_count": str(len(metrics)),
                "input_rate_hz": str(rate), "grid_coverage_p50": f"{components.grid_coverage_p50:.9f}",
                "dropout_ratio_p50": f"{components.dropout_ratio_p50:.9f}", "flat_region_ratio_p50": f"{components.flat_region_ratio_p50:.9f}",
                "degradation_score_p50": f"{components.degradation_score_p50:.9f}", "frame_score_q25": f"{components.frame_score_p25:.9f}",
                "window_score_q50": f"{components.frame_score_p50:.9f}", "frame_score_q75": f"{components.frame_score_p75:.9f}",
                "absolute_stratum": absolute,
                "notes": "Fresh unified B1 output; old non-unified/partial CSVs excluded. Sensitivity rows are below primary 200-frame contract where applicable.",
            }
        )
    _write_csv(P02 / "development_score_audit.csv", fields, rows)


def _write_candidate_summary(candidates: list[Candidate], history: list[dict[str, str]]) -> None:
    eligible = [c for c in candidates if c.eligibility == "ELIGIBLE_WITH_REFERENCE_CAVEAT"]
    domains = sorted({c.data_domain for c in eligible})
    capacity_path = P02 / "candidate_capacity_audit.csv"
    capacity_rows = list(csv.DictReader(capacity_path.open(encoding="utf-8")))
    eligible_capacity = [
        row for row in capacity_rows
        if row["eligibility"] == "ELIGIBLE_WITH_REFERENCE_CAVEAT"
    ]
    available = sum(int(row["available_candidate_windows"]) for row in eligible_capacity)
    capped_slots = sum(int(row["max_per_sequence_cap"]) for row in eligible_capacity)
    capacity_sequences = sum(int(row["available_candidate_windows"]) > 0 for row in eligible_capacity)
    capacity_domains = sorted(
        {row["data_domain"] for row in eligible_capacity if int(row["available_candidate_windows"]) > 0}
    )
    capacity_pass = capped_slots >= 20 and capacity_sequences >= 6 and len(capacity_domains) >= 3
    summary = [
        "# P02 Candidate Capacity Decision",
        "",
        "- `split_route`: `MULTI_SEQUENCE_CANDIDATE`",
        "- `external_held_out_ready`: `false`",
        f"- `eligible_reference_sequences`: `{len(eligible)}`",
        f"- `eligible_data_domains`: `{len(domains)}` (`{', '.join(domains)}`)",
        f"- `available_nonoverlap_45s_candidates_after_history_exclusion`: `{available}`",
        f"- `available_slots_after_per_sequence_cap`: `{capped_slots}`",
        f"- `capacity_sequences`: `{capacity_sequences}`",
        f"- `capacity_domains`: `{len(capacity_domains)}` (`{', '.join(capacity_domains)}`)",
        f"- `target_matrix_capacity`: `{'PASS' if capacity_pass else 'REVISE'} at metadata/time level; final low/normal counts are deferred to P06 KLT-only screening`",
        "- `APE_reference_caveat`: AQUALOC/AFRL references are offline image-derived COLMAP; NTNU references are ReAqROVIO pseudo-GT, not independent sensor truth.",
        "- `external_boundary`: FLSea-VI has metadata only; no external image decode, frontend run, or learned/VINS result was performed in P02.",
        "- `history_boundary`: exact windows present in `history_exclusion_manifest.csv` remain development-only; P06 must exclude overlaps before selecting candidates.",
        "",
        "The capacity result is not a claim that 10 low and 10 normal windows exist. It proves only that the frozen P06 selector has enough eligible sequence/time slots to attempt the preregistered matrix without reusing exact historical windows.",
    ]
    (P02 / "candidate_capacity_decision.md").write_text("\n".join(summary) + "\n", encoding="utf-8")


def _write_search_commands() -> Path:
    path = P02 / "history_search_commands.txt"
    lines = [
        "# Reproduction commands for the P02 history audit (read-only)",
        "find -L logs papers '正反例窗口整理' scripts -type f -printf '%p\\n' | sort",
        "rg -n -i 'aqualoc|archaeo|harbor|fjord|mclab|afrl|cirs|tank|uvvid|learn|vins|ape|rpe|window|sequence' logs papers '正反例窗口整理' scripts",
        "python3 scripts/build_p02_audit.py --hash-local-inputs",
        "# The builder excludes its own governance bundle from the scan and records exact evidence paths in history_exclusion_manifest.csv.",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def _write_b1_hash_manifest() -> None:
    paths = (
        ROOT / "uw_frontend/configs/klt_frontend.yaml",
        ROOT / "uw_frontend/evaluation/run_frontend_eval.py",
        ROOT / "uw_frontend/tracking/klt_tracker.py",
        ROOT / "uw_frontend/evaluation/frontend_metrics.py",
        ROOT / "uw_frontend/quality/image_quality.py",
        ROOT / "uw_frontend/geometry/grid.py",
        ROOT / "uw_frontend/datasets/image_sequence.py",
        ROOT / "uw_frontend/ros/export_vins_features.py",
        ROOT / "uw_frontend/datasets/afrl_cave_to_rosbag.py",
        ROOT / "scripts/p02_window_selection.py",
        ROOT / "scripts/run_p02_development_screening.sh",
        ROOT / "scripts/run_ntnu_vins_eval.sh",
        ROOT / "scripts/run_afrl_cave_vins_eval.sh",
    )
    lines = [f"{_digest(path, True)}  {_rel(path)}" for path in paths]
    (P02 / "b1_screening_code_hashes.sha256").write_text(
        "\n".join(lines) + "\n", encoding="utf-8"
    )


def _reference_stats(candidate: Candidate) -> dict[str, str]:
    path = candidate.reference_path
    if path is None or not path.exists():
        return {
            "reference_raw_count": "0", "reference_unique_count": "0", "reference_duplicate_count": "0",
            "reference_start_s": "", "reference_end_s": "", "reference_duration_s": "",
            "observed_reference_rate_hz": "", "observed_max_reference_gap_s": "",
            "nominal_reference_rate_hz": _str(candidate.nominal_reference_rate_hz),
            "evaluation_rate_hz": _eval_rate(candidate.nominal_reference_rate_hz), "max_reference_gap_s": _gap(candidate.nominal_reference_rate_hz),
            "nominal_estimate_rate_hz": _str(candidate.nominal_estimate_rate_hz), "max_estimate_interp_gap_s": _estimate_gap(candidate.nominal_estimate_rate_hz),
            "nominal_image_rate_hz": _str(candidate.nominal_image_rate_hz), "nominal_imu_rate_hz": _str(candidate.nominal_imu_rate_hz),
        }
    raw_values: list[float] = []
    if candidate.dataset_family.startswith("aqualoc"):
        for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
            parts = line.split()
            if len(parts) >= 8:
                try: raw_values.append(float(parts[0]) / 20.0)
                except ValueError: pass
    elif candidate.dataset_family == "ntnu":
        for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
            parts = line.split()
            if len(parts) >= 8:
                try: raw_values.append(float(parts[0]))
                except ValueError: pass
    elif candidate.dataset_family == "afrl":
        for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
            if not line.strip() or line.startswith("#"): continue
            parts = line.split()
            if len(parts) >= 8:
                try: raw_values.append(_afrl_stamp(parts[0], candidate.sequence))
                except ValueError: pass
    values = sorted(set(raw_values))
    diffs = [b-a for a,b in zip(values, values[1:]) if b > a]
    duration = values[-1] - values[0] if len(values) >= 2 else None
    observed_rate = (len(values) - 1) / duration if duration and duration > 0 else None
    return {
        "reference_raw_count": str(len(raw_values)), "reference_unique_count": str(len(values)),
        "reference_duplicate_count": str(len(raw_values) - len(values)),
        "reference_start_s": _str(values[0] if values else None), "reference_end_s": _str(values[-1] if values else None),
        "reference_duration_s": _str(duration),
        "observed_reference_rate_hz": _str(observed_rate),
        "observed_max_reference_gap_s": _str(max(diffs) if diffs else None),
        "nominal_reference_rate_hz": _str(candidate.nominal_reference_rate_hz),
        "evaluation_rate_hz": _eval_rate(candidate.nominal_reference_rate_hz),
        "max_reference_gap_s": _gap(candidate.nominal_reference_rate_hz),
        "nominal_estimate_rate_hz": _str(candidate.nominal_estimate_rate_hz),
        "max_estimate_interp_gap_s": _estimate_gap(candidate.nominal_estimate_rate_hz),
        "nominal_image_rate_hz": _str(candidate.nominal_image_rate_hz), "nominal_imu_rate_hz": _str(candidate.nominal_imu_rate_hz),
    }


def _aqualoc_duration(path: Path, image_rate: float) -> float | None:
    if not path.exists(): return None
    values = []
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        parts = line.split()
        if len(parts) >= 8:
            try: values.append(float(parts[0]))
            except ValueError: pass
    return (max(values)-min(values))/image_rate if values else None


def _afrl_stamp(value: str, sequence: str) -> float:
    raw = float(value)
    if sequence != "cemetery" or raw > 1e9:
        return raw
    digits = "".join(ch for ch in value if ch.isdigit())
    return float(f"{digits[:10]}.{digits[10:]}") if len(digits) > 10 else raw


def _afrl_duration(path: Path, sequence: str) -> float | None:
    values: list[float] = []
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        parts = line.split()
        if len(parts) >= 8:
            try:
                values.append(_afrl_stamp(parts[0], sequence))
            except ValueError:
                pass
    return max(values) - min(values) if values else None


def _hf_digests() -> dict[str, dict[str, object]]:
    output: dict[str, dict[str, object]] = {}
    for path in (DATA / "ntnu_hf/hf_filelist_with_sizes.tsv", DATA / "afrl_hf/hf_filelist_with_sizes.tsv"):
        if not path.exists(): continue
        with path.open(encoding="utf-8", errors="ignore") as handle:
            reader = csv.DictReader(handle, delimiter="\t")
            for row in reader:
                etag = row.get("etag", "").strip().strip('"')
                if re.fullmatch(r"[0-9a-fA-F]{64}", etag):
                    output[row.get("path", "")] = {"digest": etag.lower(), "size": int(row.get("size_bytes", 0) or 0)}
    return output


def _aqualoc_sizes() -> dict[str, int]:
    path = DATA / "aqualoc/file_list.csv"
    if not path.exists():
        return {}
    sizes: dict[str, int] = {}
    with path.open(encoding="utf-8", errors="ignore") as handle:
        for row in csv.DictReader(handle):
            name = row.get("file_name", "")
            value = str(row.get("size", ""))
            if not name or not value.isdigit():
                continue
            sizes[name] = int(value)
            match = re.fullmatch(r"archaeo_sequence_(\d+)_raw_data\.tar\.gz", name)
            if match:
                sizes[f"archaeo_sequence_{int(match.group(1)):02d}_raw_data.tar.gz"] = int(value)
    return sizes


def _artifact_digest(path: Path, candidate: Candidate, role: str, hash_local: bool, hf: dict[str, dict[str, object]]) -> tuple[str, str]:
    key = _hf_key(path)
    if role == "raw_input" and key in hf:
        return str(hf[key]["digest"]), "official_HuggingFace_LFS_SHA256"
    if not hash_local and role == "raw_input":
        return "", "deferred_local_hash"
    return _digest(path, True), "local_tree_v1" if path.is_dir() else "local_file"


def _digest(path: Path | None, enabled: bool) -> str:
    if path is None or not path.exists() or not enabled: return ""
    h = hashlib.sha256()
    if path.is_dir():
        h.update(b"isj-directory-sha256-v1\0")
        for child in sorted(item for item in path.rglob("*") if item.is_file()):
            relative = child.relative_to(path).as_posix().encode("utf-8")
            h.update(len(relative).to_bytes(8, "big"))
            h.update(relative)
            h.update(child.stat().st_size.to_bytes(8, "big"))
            _update_digest_from_file(h, child)
    else:
        _update_digest_from_file(h, path)
    return h.hexdigest()


def _update_digest_from_file(digest: Any, path: Path) -> None:
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(chunk)


def _artifact_size(path: Path) -> int:
    if path.is_dir():
        return sum(item.stat().st_size for item in path.rglob("*") if item.is_file())
    return path.stat().st_size


def _hf_key(path: Path | None) -> str:
    if path is None: return ""
    text = path.as_posix()
    marker = "/full_downloads/"
    if marker in text:
        return text.split(marker, 1)[1].split("/", 1)[1] if "/" in text.split(marker, 1)[1] else ""
    return ""


def _calibration_status(candidate: Candidate) -> str:
    return "PASS_ALL_PRESENT" if candidate.calibration_paths and all(path.exists() for path in candidate.calibration_paths) else "MISSING_OR_NOT_APPLICABLE"


def _sync_status(candidate: Candidate) -> str:
    if candidate.dataset_family.startswith("aqualoc"): return "IMAGE_IMU_SHARED_EPOCH_GT_IMAGE_INDEXED"
    if candidate.dataset_family == "ntnu": return "ROS_HEADER_CLOCK_AND_CALIBRATION_METADATA"
    if candidate.dataset_family == "afrl": return "ROS_HEADER_CLOCK_GT_TIMESTAMP_OVERLAP"
    return "NOT_APPLICABLE_OR_UNRESOLVED"


def _eval_rate(rate: float | None) -> str:
    if rate is None: return ""
    return str(max(v for v in (1.0, 2.0, 5.0, 10.0) if v <= rate))


def _gap(rate: float | None) -> str:
    return _str(2.5 / rate) if rate and rate > 0 else ""


def _estimate_gap(rate: float | None) -> str:
    return _str(2.5 / rate) if rate and rate > 0 else ""


def _window_seconds(window: dict[str, str], candidate: Candidate) -> float:
    start = _number(window["start"])
    return start / 20.0 if window.get("window_unit") == "frame" else start


def _window_end_seconds(window: dict[str, str], candidate: Candidate) -> float:
    end = _number(window["end"])
    return end / 20.0 if window.get("window_unit") == "frame" else end


def _normalize_afrl_sequence(sequence: str) -> str:
    sequence = sequence.lower()
    return {
        "cave": "cave_gennie",
        "bus": "bus_outside",
        "cemfr": "cemetery_fr",
        "cemfl": "cemetery_fl",
        "fr": "cemetery_fr",
        "fl": "cemetery_fl",
    }.get(sequence, sequence)


def _decimal_add(start: str, duration: str) -> str:
    value = _number(start) + _number(duration)
    return f"{value:g}"


def _number(value: str) -> float:
    return float(str(value).replace("p", "."))


def _write_csv(path: Path, fields: list[str], rows: Iterable[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _dedupe_checksum_rows(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    out: dict[tuple[str, str], dict[str, str]] = {}
    for row in rows:
        key = (row["artifact_role"], row["path"])
        out[key] = row
    return [out[key] for key in sorted(out)]


def _join_evidence(values: Iterable[str]) -> str:
    items = sorted(dict.fromkeys(str(value) for value in values if value))
    if len(items) > 12:
        return ";".join(items[:12]) + f";...(+{len(items)-12})"
    return ";".join(items)


def _str(value: object) -> str:
    if value is None: return ""
    if isinstance(value, float): return f"{value:.9g}"
    return str(value)


def _rel(path: Path | None) -> str:
    if path is None: return ""
    try: return path.relative_to(ROOT).as_posix()
    except ValueError: return path.as_posix()


if __name__ == "__main__":
    raise SystemExit(main())
