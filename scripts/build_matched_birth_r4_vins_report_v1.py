#!/usr/bin/env python3
"""Render the r4 matched-birth VINS evidence reports from sealed results.

This module is intentionally a renderer, not an evaluator.  It accepts the
formal common-support directory and the corrected r4 detector seal, validates
their write-once provenance, and copies already-sealed metrics into Markdown.
It never opens a trajectory, bag, VINS log, or runner-local ``ape.txt`` and it
does not align, resample, match, or otherwise recompute a primary metric.
"""

from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
import math
import os
from pathlib import Path
import re
import stat
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[1]
SEALED_EVALUATION_DIR = (
    ROOT
    / "papers/litcmp_a02_4500_6300_common_support"
    / "formal900_r4_xfeatbirth_vs_gfttbirth_r1"
)
CORRECTED_R4_SEAL = (
    ROOT
    / "papers/a02_4500_6300_matched_birth_formal900_r4_modefix_continuation_seal_v1.json"
)
EVALUATION_POST_SEAL = (
    ROOT
    / "papers/a02_4500_6300_matched_birth_formal900_r4_vins_eval_seal_v1.json"
)
ANALYSIS_DIR = (
    ROOT
    / "papers/litcmp_a02_4500_6300_common_support"
    / "formal900_r4_xfeatbirth_vs_gfttbirth_r1_analysis_v1"
)

SUMMARY_NAME = "common_support_summary.json"
METRICS_NAME = "common_support_metrics.csv"
GRID_NAME = "common_grid_audit.csv"
EVO_NAME = "evo_crosscheck.json"
MANIFEST_NAME = "formal_output_manifest_v1.json"
REPORT_NAME = "2026-08-13--matched-birth-r4--r1--common-support-report.md"
ANALYSIS_NAME = "analysis-report.md"
STATS_NAME = "stats-appendix.md"
FIGURE_CATALOG_NAME = "figure-catalog.md"

EXPECTED_ARMS = ("GFTTBIRTH_RAWLK", "XFEATBIRTH_RAWLK")
PRIMARY_KEYS = (
    "ape_rmse_m",
    "ape_median_m",
    "ape_max_m",
    "rpe_rmse_m",
    "rpe_median_m",
    "rpe_max_m",
)
LEGACY_KEYS = (
    "legacy_pair_count",
    "legacy_unique_reference_used",
    "legacy_max_reference_reuse",
    "legacy_timestamp_error_p95_s",
    "legacy_timestamp_error_max_s",
    "legacy_unique_assignment_pair_count",
    "legacy_unique_assignment_error_p95_s",
    "legacy_unique_assignment_error_max_s",
)
POST_SCHEMA = "aqua-fe-matched-birth-r4-vins-g0-post-seal-v1"
POST_STATUS = "PASS_STRICT_FULL_INTERVAL_COMMON_SUPPORT"
CORRECTED_SCHEMA = (
    "aqua-fe-detector-birth-rawlk-matched-pair-formal-r4-modefix-continuation-audit-v1"
)
MANIFEST_SCHEMA = "aqua-fe-matched-birth-r4-vins-g0-output-manifest-v1"
EXPECTED_REFERENCE_TOPIC = "/aqualoc/colmap_gt"
EXPECTED_REFERENCE_PATH = ROOT / "datasets/aqualoc/rosbags/archaeo02_4500_6300.bag"
EXPECTED_WINDOW_START_TEXT = "1542829016.700435392"
EXPECTED_WINDOW_END_TEXT = "1542829106.687510592"
EXPECTED_WINDOW_START = float(EXPECTED_WINDOW_START_TEXT)
EXPECTED_WINDOW_END = float(EXPECTED_WINDOW_END_TEXT)
EXPECTED_GRID_COUNT = 90


class ReportError(RuntimeError):
    """The sealed report inputs or publication contract are invalid."""


def sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def file_identity(path: Path) -> dict[str, object]:
    flags = os.O_RDONLY | os.O_CLOEXEC | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags)
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
            raise ReportError(f"single-link regular file required: {path}")
        digest = hashlib.sha256()
        size = 0
        while True:
            chunk = os.read(descriptor, 1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
            size += len(chunk)
        after = os.fstat(descriptor)
        if (
            before.st_dev,
            before.st_ino,
            before.st_size,
            before.st_mtime_ns,
        ) != (
            after.st_dev,
            after.st_ino,
            after.st_size,
            after.st_mtime_ns,
        ):
            raise ReportError(f"file changed while hashing: {path}")
        return {
            "path": str(path.resolve(strict=True)),
            "size_bytes": size,
            "sha256": digest.hexdigest(),
        }
    finally:
        os.close(descriptor)


def read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_bytes())
    except (OSError, json.JSONDecodeError) as error:
        raise ReportError(f"invalid JSON: {path}: {error}") from error
    if not isinstance(value, dict):
        raise ReportError(f"JSON object required: {path}")
    return value


def identity_matches(observed: Mapping[str, object], path: Path, label: str) -> None:
    actual = file_identity(path)
    if any(observed.get(key) != actual[key] for key in ("path", "size_bytes", "sha256")):
        raise ReportError(f"{label} identity differs")


def live_tree_inventory(root: Path) -> list[dict[str, object]]:
    records: list[dict[str, object]] = []
    for path in sorted(root.rglob("*"), key=lambda item: str(item.relative_to(root))):
        relative = str(path.relative_to(root))
        if relative == MANIFEST_NAME:
            continue
        info = os.lstat(path)
        if stat.S_ISLNK(info.st_mode):
            raise ReportError(f"symlink forbidden in sealed evaluation: {relative}")
        if stat.S_ISDIR(info.st_mode):
            records.append(
                {
                    "relative_path": relative,
                    "type": "directory",
                    "mode_octal": format(stat.S_IMODE(info.st_mode), "04o"),
                }
            )
        elif stat.S_ISREG(info.st_mode) and info.st_nlink == 1:
            identity = file_identity(path)
            records.append(
                {
                    "relative_path": relative,
                    "type": "regular",
                    "size_bytes": identity["size_bytes"],
                    "sha256": identity["sha256"],
                }
            )
        else:
            raise ReportError(f"unsupported sealed evaluation entry: {relative}")
    return records


def require_number(value: object, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ReportError(f"finite numeric {label} required")
    result = float(value)
    if not math.isfinite(result):
        raise ReportError(f"finite numeric {label} required")
    return result


def require_int(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ReportError(f"integer {label} required")
    return value


def metric_text(value: object) -> str:
    number = require_number(value, "rendered metric")
    return format(number, ".9g")


def bool_text(value: object) -> str:
    if value is True:
        return "true"
    if value is False:
        return "false"
    return str(value)


def _validate_claim_boundaries(post: Mapping[str, Any], corrected: Mapping[str, Any]) -> None:
    post_claim = post.get("claim_boundary")
    corrected_claim = corrected.get("claim_boundary")
    if not isinstance(post_claim, Mapping) or not isinstance(corrected_claim, Mapping):
        raise ReportError("both seals must contain claim boundaries")
    expected_post = {
        "runner_local_ape_results_visible_before_freeze": True,
        "outcome_blind": False,
        "confirmatory": False,
        "statistical_significance": False,
        "cross_window_or_cross_dataset_generalization": False,
        "whole_slam_superiority": False,
        "reference_is_image_derived_colmap_not_independent_ground_truth": True,
    }
    expected_corrected = {
        "confirmatory": False,
        "statistical_significance": False,
        "whole_slam_superiority": False,
        "detector_birth_source_only_within_this_frozen_carrier": True,
        "detector_rerun_or_r4_mutation_authorized": False,
    }
    if any(post_claim.get(key) is not value for key, value in expected_post.items()):
        raise ReportError("evaluation claim boundary differs")
    if any(corrected_claim.get(key) is not value for key, value in expected_corrected.items()):
        raise ReportError("corrected r4 claim boundary differs")


def load_evidence(
    evaluation_dir: Path,
    corrected_seal_path: Path,
    *,
    post_seal_path: Path = EVALUATION_POST_SEAL,
) -> dict[str, Any]:
    """Validate and load sealed evidence without recomputing scientific metrics."""

    if not evaluation_dir.is_dir() or evaluation_dir.is_symlink():
        raise ReportError("sealed evaluation directory is missing or is a symlink")
    corrected = read_json(corrected_seal_path)
    post = read_json(post_seal_path)
    manifest_path = evaluation_dir / MANIFEST_NAME
    summary_path = evaluation_dir / SUMMARY_NAME
    evo_path = evaluation_dir / EVO_NAME
    manifest = read_json(manifest_path)
    summary = read_json(summary_path)
    evo = read_json(evo_path)

    if corrected.get("schema_version") != CORRECTED_SCHEMA or corrected.get("status") != "PASS" or corrected.get("pass") is not True:
        raise ReportError("corrected r4 detector seal is not strict PASS")
    if post.get("schema_version") != POST_SCHEMA or post.get("status") != POST_STATUS or post.get("pass") is not True:
        raise ReportError("formal VINS evaluation seal is not strict PASS")
    if manifest.get("schema_version") != MANIFEST_SCHEMA:
        raise ReportError("formal output manifest schema differs")
    members = manifest.get("members_excluding_this_manifest")
    if not isinstance(members, list) or members != live_tree_inventory(evaluation_dir):
        raise ReportError("formal output manifest does not close the live evaluation tree")

    for key, path in (
        ("corrected_r4_seal", corrected_seal_path),
        ("formal_output_manifest", manifest_path),
        ("summary", summary_path),
        ("evo_crosscheck", evo_path),
    ):
        record = post.get(key)
        if not isinstance(record, Mapping):
            raise ReportError(f"formal VINS seal lacks {key}")
        identity_matches(record, path, f"formal VINS seal {key}")

    strict = post.get("strict_gates")
    required_true = (
        "evaluator_rc0",
        "ape_valid",
        "rpe_valid",
        "summary_recomputed",
        "output_manifest_and_tree_closure",
        "evo_primary_echo_crosschecked",
    )
    if not isinstance(strict, Mapping) or any(strict.get(key) is not True for key in required_true):
        raise ReportError("formal VINS strict gates are incomplete")
    if strict.get("grid_count") != EXPECTED_GRID_COUNT or strict.get("expected_grid_count") != EXPECTED_GRID_COUNT:
        raise ReportError("formal VINS grid count differs")
    if post.get("failure_reasons") != []:
        raise ReportError("formal VINS seal contains failure reasons")

    support = summary.get("support")
    arms = summary.get("arms")
    protocol = summary.get("protocol")
    result_metrics = post.get("result_metrics")
    if not isinstance(support, Mapping) or not isinstance(arms, Mapping) or not isinstance(protocol, Mapping):
        raise ReportError("common-support summary structure differs")
    if set(arms) != set(EXPECTED_ARMS) or result_metrics != arms:
        raise ReportError("sealed result metrics do not exactly echo summary arms")
    if support.get("ape_valid") is not True or support.get("rpe_valid") is not True:
        raise ReportError("common support is not valid for APE and RPE")
    if require_int(support.get("grid_count"), "support.grid_count") != EXPECTED_GRID_COUNT:
        raise ReportError("summary grid count differs")
    if require_number(support.get("common_coverage"), "support.common_coverage") < 0.70:
        raise ReportError("summary common coverage is below the formal gate")
    if require_int(support.get("rpe_pairs"), "support.rpe_pairs") < 10:
        raise ReportError("summary has too few RPE pairs")
    for key in ("matched_count", "segment_count"):
        require_int(support.get(key), f"support.{key}")
    for key in ("common_span_s", "window_duration_s"):
        require_number(support.get(key), f"support.{key}")

    if protocol.get("contrast_name") != "A02_4500_6300_MATCHED_BIRTH_FORMAL900_R4_XFEAT_VS_GFTT_FULL_INTERVAL":
        raise ReportError("summary contrast differs")
    if protocol.get("reference_topic") not in (None, EXPECTED_REFERENCE_TOPIC):
        raise ReportError("summary reference topic differs")
    reference = protocol.get("reference")
    canonical_reference = f"{EXPECTED_REFERENCE_PATH}:{EXPECTED_REFERENCE_TOPIC}"
    procfd_pattern = rf"/proc/self/fd/[0-9]+:{re.escape(EXPECTED_REFERENCE_TOPIC)}"
    if not isinstance(reference, str) or (
        reference != canonical_reference and re.fullmatch(procfd_pattern, reference) is None
    ):
        raise ReportError("summary does not bind the expected reference topic")
    for key, expected in (
        ("evaluation_rate_hz", 1.0),
        ("nominal_reference_rate_hz", 1.0),
        ("nominal_estimate_rate_hz", 10.0),
        ("max_reference_gap_s", 2.5),
        ("max_estimate_gap_s", 0.25),
        ("rpe_delta_s", 1.0),
    ):
        if require_number(protocol.get(key), f"protocol.{key}") != expected:
            raise ReportError(f"summary protocol {key} differs")
    if not math.isclose(require_number(protocol.get("window_start_s"), "protocol.window_start_s"), EXPECTED_WINDOW_START, abs_tol=5e-7):
        raise ReportError("summary window start differs")
    if not math.isclose(require_number(protocol.get("window_end_s"), "protocol.window_end_s"), EXPECTED_WINDOW_END, abs_tol=5e-7):
        raise ReportError("summary window end differs")
    if protocol.get("body_to_camera_applied") is not True or protocol.get("rpe_semantics") != "aligned_global_frame_positional_delta":
        raise ReportError("summary transform or RPE semantics differs")

    for arm in EXPECTED_ARMS:
        item = arms[arm]
        if not isinstance(item, Mapping):
            raise ReportError(f"summary arm is not an object: {arm}")
        for key in PRIMARY_KEYS + LEGACY_KEYS:
            require_number(item.get(key), f"{arm}.{key}")
        audit = item.get("audit")
        if not isinstance(audit, Mapping):
            raise ReportError(f"summary arm audit is absent: {arm}")
        for key in ("raw_count", "finite_count", "unique_count", "duplicate_count", "rejected_nonfinite_count"):
            require_int(audit.get(key), f"{arm}.audit.{key}")

    evo_arms = evo.get("arms")
    if evo.get("evo_version") != "1.31.1" or not isinstance(evo_arms, Mapping) or set(evo_arms) != set(EXPECTED_ARMS):
        raise ReportError("evo cross-check structure differs")
    for arm in EXPECTED_ARMS:
        item = evo_arms[arm]
        if not isinstance(item, Mapping):
            raise ReportError(f"evo arm is invalid: {arm}")
        if item.get("primary_ape_rmse_m") != arms[arm].get("ape_rmse_m") or item.get("primary_rpe_rmse_m") != arms[arm].get("rpe_rmse_m"):
            raise ReportError(f"evo primary echo differs: {arm}")
        for key in ("ape_abs_diff_m", "rpe_abs_diff_m", "evo_ape_rmse_m", "evo_segmented_rpe_rmse_m"):
            require_number(item.get(key), f"evo.{arm}.{key}")

    _validate_claim_boundaries(post, corrected)
    return {
        "evaluation_dir": evaluation_dir,
        "corrected_path": corrected_seal_path,
        "post_path": post_seal_path,
        "corrected": corrected,
        "post": post,
        "manifest": manifest,
        "summary": summary,
        "evo": evo,
        "identities": {
            "corrected_r4_seal": file_identity(corrected_seal_path),
            "formal_vins_seal": file_identity(post_seal_path),
            "formal_output_manifest": file_identity(manifest_path),
            "common_support_summary": file_identity(summary_path),
            "evo_crosscheck": file_identity(evo_path),
        },
    }


def _primary_table(arms: Mapping[str, Mapping[str, object]]) -> str:
    labels = {"XFEATBIRTH_RAWLK": "XFeat birth", "GFTTBIRTH_RAWLK": "GFTT birth"}
    rows = [
        "| Arm | APE RMSE (m) | APE median (m) | APE max (m) | RPE RMSE (m) | RPE median (m) | RPE max (m) |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for arm in ("XFEATBIRTH_RAWLK", "GFTTBIRTH_RAWLK"):
        item = arms[arm]
        rows.append("| " + " | ".join([labels[arm], *(metric_text(item[key]) for key in PRIMARY_KEYS)]) + " |")
    return "\n".join(rows)


def _support_table(support: Mapping[str, object]) -> str:
    keys = (
        ("Grid poses", "grid_count"),
        ("Common poses", "matched_count"),
        ("Common span (s)", "common_span_s"),
        ("Common coverage", "common_coverage"),
        ("Segments", "segment_count"),
        ("RPE pairs", "rpe_pairs"),
        ("APE valid", "ape_valid"),
        ("RPE valid", "rpe_valid"),
    )
    rows = ["| Support field | Sealed value |", "|---|---:|"]
    for label, key in keys:
        value = support.get(key)
        rows.append(f"| {label} | {bool_text(value) if isinstance(value, bool) else metric_text(value)} |")
    return "\n".join(rows)


def _legacy_table(arms: Mapping[str, Mapping[str, object]]) -> str:
    rows = [
        "| Diagnostic | XFeat birth | GFTT birth |",
        "|---|---:|---:|",
    ]
    for key in LEGACY_KEYS:
        rows.append(
            f"| `{key}` | {metric_text(arms['XFEATBIRTH_RAWLK'][key])} | {metric_text(arms['GFTTBIRTH_RAWLK'][key])} |"
        )
    return "\n".join(rows)


def _audit_table(arms: Mapping[str, Mapping[str, object]]) -> str:
    rows = ["| Native trajectory audit | XFeat birth | GFTT birth |", "|---|---:|---:|"]
    for key in ("raw_count", "finite_count", "unique_count", "duplicate_count", "rejected_nonfinite_count"):
        rows.append(f"| `{key}` | {arms['XFEATBIRTH_RAWLK']['audit'][key]} | {arms['GFTTBIRTH_RAWLK']['audit'][key]} |")
    return "\n".join(rows)


def _identity_table(identities: Mapping[str, Mapping[str, object]]) -> str:
    rows = ["| Sealed artifact | SHA-256 | Bytes |", "|---|---|---:|"]
    for label, record in identities.items():
        rows.append(f"| {label} | `{record['sha256']}` | {record['size_bytes']} |")
    return "\n".join(rows)


def _boundary_lines(post: Mapping[str, Any], corrected: Mapping[str, Any]) -> str:
    rows = ["Evaluation seal:"]
    rows.extend(f"- `{key}`: `{bool_text(value)}`" for key, value in sorted(post["claim_boundary"].items()))
    rows.append("")
    rows.append("Corrected detector-pair seal:")
    rows.extend(f"- `{key}`: `{bool_text(value)}`" for key, value in sorted(corrected["claim_boundary"].items()))
    return "\n".join(rows)


def _directions(arms: Mapping[str, Mapping[str, object]]) -> list[str]:
    xfeat = arms["XFEATBIRTH_RAWLK"]
    gftt = arms["GFTTBIRTH_RAWLK"]
    labels = {
        "ape_rmse_m": "APE RMSE",
        "ape_median_m": "APE median",
        "ape_max_m": "APE maximum",
        "rpe_rmse_m": "RPE RMSE",
        "rpe_median_m": "RPE median",
        "rpe_max_m": "RPE maximum",
    }
    rows: list[str] = []
    for key in PRIMARY_KEYS:
        xvalue = require_number(xfeat[key], key)
        gvalue = require_number(gftt[key], key)
        if xvalue == gvalue:
            direction = "equal point estimates"
        else:
            direction = f"lower for {'XFeat birth' if xvalue < gvalue else 'GFTT birth'}"
        rows.append(f"- {labels[key]} is {direction} on the sealed common support.")
    return rows


def render_documents(evidence: Mapping[str, Any]) -> dict[str, str]:
    summary = evidence["summary"]
    arms = summary["arms"]
    support = summary["support"]
    protocol = summary["protocol"]
    post = evidence["post"]
    corrected = evidence["corrected"]
    evo = evidence["evo"]
    primary = _primary_table(arms)
    support_table = _support_table(support)
    legacy = _legacy_table(arms)
    audit = _audit_table(arms)
    boundaries = _boundary_lines(post, corrected)
    identities = _identity_table(evidence["identities"])
    directions = "\n".join(_directions(arms))

    report = f"""# A02 4500–6300 matched detector-birth VINS common-support report

## Outcome

The sealed full-interval common-support evaluation passed its APE, RPE, tree-closure, independent-summary-recomputation, and evo echo gates. The table below transcribes the primary point estimates from the formal VINS post seal; this report performs no trajectory evaluation.

{primary}

{directions}

These are descriptive directions for one A02 window and one VINS replay per arm. They are not inferential evidence of a population-level winner.

## Common support and protocol

{support_table}

- Reference: `{EXPECTED_REFERENCE_PATH}:{EXPECTED_REFERENCE_TOPIC}` (canonical identity; a sealed evaluator may serialize its held `/proc/self/fd/N` lease in the source summary).
- Reference topic: `{EXPECTED_REFERENCE_TOPIC}`
- Complete formal interval: `{EXPECTED_WINDOW_START_TEXT}` to `{EXPECTED_WINDOW_END_TEXT}` s (about 90 s).
- Evaluation grid: `{metric_text(protocol['evaluation_rate_hz'])}` Hz, reference-anchored.
- Estimate nominal rate / maximum interpolation gap: `{metric_text(protocol['nominal_estimate_rate_hz'])}` Hz / `{metric_text(protocol['max_estimate_gap_s'])}` s.
- Reference nominal rate / maximum interpolation gap: `{metric_text(protocol['nominal_reference_rate_hz'])}` Hz / `{metric_text(protocol['max_reference_gap_s'])}` s.
- Transform: frozen `body_T_cam0` applied before interpolation and fixed-scale SE(3) alignment.
- RPE: `{metric_text(protocol['rpe_delta_s'])}` s positional delta in the aligned global frame, within valid common-support segments.

The roughly 90 s raw-carrier/reference interval is the formal primary domain. Any earlier 46-pose proxy-reference or exact-native-timestamp calculation is historical diagnostic evidence only and is not substituted for this common-grid result. Initialization delay and native output coverage belong to replay diagnostics; they are not silently converted into additional common-grid samples.

## Native trajectory and legacy association diagnostics

{audit}

{legacy}

The `legacy_*` fields are evaluator-emitted association diagnostics. They do not enter the primary common-support APE/RPE mask. Runner-local `ape.txt` values are neither identity-bound by this report input nor transcribed here; they remain non-primary historical diagnostics.

## Claim boundary

{boundaries}

Additional reporting constraints:

- Experimental unit: one preselected A02 4500–6300 window; `n=1` replay per arm.
- Scientific role: post-result exploratory matched detector-birth source control inside one frozen carrier.
- No confidence interval, hypothesis test, p-value, multiple-comparison correction, or population effect size is estimable from this pair.
- No claim of statistical significance, repeatability, cross-window or cross-dataset generalization, whole-SLAM superiority, or standalone detector superiority is permitted.
- The `/aqualoc/colmap_gt` reference is image-derived COLMAP, not independent external ground truth.
- GFTT's earlier native outputs, if any, are excluded wherever the frozen common mask requires both arms; native initialization/coverage must be reported separately from primary accuracy.

## Evidence identities

{identities}
"""

    analysis = f"""# Analysis report

## Analysis question

On the frozen A02 4500–6300 formal900 carrier, how do the XFeat-birth and GFTT-birth source controls differ in translation APE and 1 s positional RPE when evaluated on one reference-anchored common mask?

## Evidence validity

- Formal evaluation status: `{post['status']}`.
- Common support: APE valid `{bool_text(support['ape_valid'])}`, RPE valid `{bool_text(support['rpe_valid'])}`, `{support['matched_count']}` common poses, `{metric_text(support['common_coverage'])}` coverage.
- Experimental unit and repeats: one window, one replay per arm (`n=1`).
- Inference: blocked by design; descriptive point estimates only.

## Sealed point estimates

{primary}

## Key observations

{directions}

The observations change the next decision only at the exploratory level: they can motivate preregistered repeats and additional windows. They cannot select a generally superior detector or SLAM system.

## Claim candidates

- Claim:
  - Source evidence: formal VINS post seal and `common_support_summary.json` on the full 90 s A02 reference domain.
  - Allowed wording: "In this single exploratory A02 replay, [name the exact metric] was lower for [arm] on the frozen common support."
  - Forbidden stronger wording: "XFeat/GFTT is statistically significantly, consistently, generally, or universally better," or "the whole SLAM system is superior."
  - Uncertainty: no replay repeats, no second window, image-derived COLMAP reference.
  - Next check: preregister repeated replays and matched low-texture windows before inspecting their trajectories.
  - Decision: weaken.

- Claim:
  - Source evidence: strict common-support and evo gates.
  - Allowed wording: "Both arms produced sufficient shared support for descriptive APE/RPE evaluation in this window."
  - Forbidden stronger wording: "Both frontends are robust across AQUALOC" or "tracking reliability is established."
  - Uncertainty: support validity is not a cross-window robustness test.
  - Next check: repeat across independently selected windows and report initialization/coverage separately.
  - Decision: keep.

## Caveats

{boundaries}
"""

    evo_rows = ["| Arm | Primary APE RMSE | evo APE RMSE | abs. diff. | Primary RPE RMSE | evo RPE RMSE | abs. diff. |", "|---|---:|---:|---:|---:|---:|---:|"]
    for arm in ("XFEATBIRTH_RAWLK", "GFTTBIRTH_RAWLK"):
        item = evo["arms"][arm]
        evo_rows.append(
            f"| {arm} | {metric_text(item['primary_ape_rmse_m'])} | {metric_text(item['evo_ape_rmse_m'])} | {metric_text(item['ape_abs_diff_m'])} | {metric_text(item['primary_rpe_rmse_m'])} | {metric_text(item['evo_segmented_rpe_rmse_m'])} | {metric_text(item['rpe_abs_diff_m'])} |"
        )
    evo_table = "\n".join(evo_rows)
    stats = f"""# Statistics appendix

## Unit of analysis and inference gate

- Unit: one A02 4500–6300 experimental window.
- Replay count: one replay per arm (one XFeat-birth and one GFTT-birth replay).
- Independent sample size: `n=1` window; neither common grid poses nor RPE pairs are treated as independent replicates.
- Descriptive statistics: sealed RMSE, median, and maximum only.
- Inferential statistics: not run. Normality tests, confidence intervals, hypothesis tests, p-values, standardized population effect sizes, and multiple-comparison corrections are not valid at `n=1`.

## Primary descriptive statistics

{primary}

These values are copied from `result_metrics` in the formal post seal, which exactly echoes the sealed common-support summary. The renderer does not load the native trajectories and cannot recompute them.

## Support audit

{support_table}

## Independent implementation echo

{evo_table}

The formal post seal requires finite evo values and exact primary RMSE echoes. This is an implementation cross-check, not an independent experiment or a second statistical sample.

## Native input audit

{audit}

## Legacy association diagnostics

{legacy}

Legacy nearest-reference reuse and one-to-one assignment diagnostics describe timestamp association behavior only. They do not replace the primary reference-grid common-support estimator.

## Explicit blockers

- No repeat-level variance.
- No independent second window or dataset.
- No valid inferential effect size or confidence interval.
- No independent external ground truth; the reference is image-derived COLMAP.
- Runner-local `ape.txt` is outside this renderer's sealed input bundle and is deliberately not transcribed.
"""

    figures = f"""# Figure catalog

No figure is published by report generation v1. This is deliberate: the first release freezes the textual analysis without altering the sealed evaluation directory. Any later figure generator must read only the sealed CSV/grid files named below, must remain in the separate analysis namespace, and must not recompute APE/RPE from trajectories.

## Figure 01 — primary descriptive comparison (not generated)

- Filename: `figures/figure-01-primary-common-support-metrics.pdf`
- Purpose: compare the six sealed APE/RPE point estimates for the two arms.
- Data source: `{SUMMARY_NAME}` or `{METRICS_NAME}`, identity-bound through `{MANIFEST_NAME}` and the formal post seal.
- Error bars: none; `n=1`, so uncertainty bars would be fabricated.
- Caption requirements: state A02 4500–6300, one replay per arm, full 90 s reference domain, common support, fixed-scale SE(3), 1 s RPE, and descriptive-only status.
- Key observation: use only the metric-specific directions listed in `analysis-report.md`.
- Interpretation checklist: explain why the figure exists; name the exact lower point estimates; state that the observation motivates repeats rather than establishing superiority.
- Caveat: do not plot common poses or RPE pairs as independent samples.

## Figure 02 — support mask timeline (not generated)

- Filename: `figures/figure-02-common-support-timeline.pdf`
- Purpose: show which 1 Hz reference-grid points enter the shared mask and how valid segments are formed.
- Data source: `{GRID_NAME}`, identity-bound through `{MANIFEST_NAME}` and the formal post seal.
- Plotted variables: timestamp, reference validity, each arm's validity, `common_valid`, and `segment_id`.
- Error bars: not applicable.
- Caption requirements: distinguish the full raw/reference interval from native initialization coverage and identify common-mask exclusion.
- Key observation: the primary accuracy comparison uses only points valid for the reference and both arms.
- Interpretation checklist: explain mask fairness, identify any excluded prefix/gaps, and avoid interpreting validity count as accuracy.
- Caveat: a support timeline is diagnostic, not evidence of statistical repeatability.

## Publication rule

Figures remain absent until a separate write-once figure generator validates the same formal post seal and writes into this analysis namespace without touching the sealed evaluation tree.
"""

    return {
        REPORT_NAME: report.rstrip() + "\n",
        ANALYSIS_NAME: analysis.rstrip() + "\n",
        STATS_NAME: stats.rstrip() + "\n",
        FIGURE_CATALOG_NAME: figures.rstrip() + "\n",
    }


def _write_file_exclusive(path: Path, content: str) -> None:
    data = content.encode("utf-8")
    descriptor = os.open(
        path,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC | getattr(os, "O_NOFOLLOW", 0),
        0o444,
    )
    try:
        os.fchmod(descriptor, 0o444)
        view = memoryview(data)
        while view:
            written = os.write(descriptor, view)
            if written <= 0:
                raise ReportError(f"short report write: {path}")
            view = view[written:]
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    if file_identity(path)["sha256"] != sha256_bytes(data):
        raise ReportError(f"report readback differs: {path}")


def _rename_noreplace(source: Path, destination: Path) -> None:
    libc = ctypes.CDLL(None, use_errno=True)
    number = getattr(os, "SYS_renameat2", 316)
    result = libc.syscall(number, -100, os.fsencode(source), -100, os.fsencode(destination), 1)
    if result != 0:
        error = ctypes.get_errno()
        raise OSError(error, os.strerror(error), str(destination))


def publish_documents(output_dir: Path, documents: Mapping[str, str]) -> None:
    if output_dir.exists() or output_dir.is_symlink():
        raise ReportError("analysis output directory already exists")
    staging = output_dir.with_name(f".{output_dir.name}.staging")
    if staging.exists() or staging.is_symlink():
        raise ReportError("analysis staging directory already exists")
    output_dir.parent.mkdir(parents=True, exist_ok=True)
    os.mkdir(staging, 0o700)
    for name in (REPORT_NAME, ANALYSIS_NAME, STATS_NAME, FIGURE_CATALOG_NAME):
        _write_file_exclusive(staging / name, documents[name])
    parent = os.open(staging, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
    try:
        os.fsync(parent)
    finally:
        os.close(parent)
    _rename_noreplace(staging, output_dir)
    parent = os.open(output_dir.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
    try:
        os.fsync(parent)
    finally:
        os.close(parent)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--action", required=True, choices=("check", "publish"))
    parser.add_argument("--sealed-evaluation-dir", required=True)
    parser.add_argument("--corrected-r4-seal", required=True)
    parser.add_argument("--output-dir", default=str(ANALYSIS_DIR))
    args = parser.parse_args()

    evaluation_dir = Path(args.sealed_evaluation_dir).resolve(strict=False)
    corrected = Path(args.corrected_r4_seal).resolve(strict=False)
    output = Path(args.output_dir).resolve(strict=False)
    if evaluation_dir != SEALED_EVALUATION_DIR or corrected != CORRECTED_R4_SEAL or output != ANALYSIS_DIR:
        raise ReportError("CLI paths must equal the frozen r4 report paths")
    evidence = load_evidence(evaluation_dir, corrected)
    documents = render_documents(evidence)
    if args.action == "publish":
        publish_documents(output, documents)
        print(output)
    else:
        print("PASS_REPORT_INPUTS")
        for name in documents:
            print(name)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ReportError) as error:
        print(f"REPORT_ERROR:{type(error).__name__}:{error}", file=os.sys.stderr)
        raise SystemExit(2)
