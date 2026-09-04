#!/usr/bin/env python3
"""Validate sealed A02 r3 evidence and publish a transcription-only report.

This renderer never opens trajectories, bags, VINS logs, or runner-local
diagnostic files.  It does not import an evaluator and it starts no process.
All numeric values come from the already sealed r3 bound summary and CSV.
"""

from __future__ import annotations

import argparse
from contextlib import ExitStack, contextmanager
import csv
import ctypes
import errno
import hashlib
import io
import json
import math
import os
from pathlib import Path
import shutil
import stat
from typing import Any, Iterator, Mapping, Sequence


ROOT = Path("/home/ma/AQUA-FE_WS")
SOURCE = ROOT / "scripts/build_matched_birth_r4_vins_report_v2.py"
RESULT = ROOT / "papers/litcmp_a02_4500_6300_common_support/formal900_r4_xfeatbirth_vs_gfttbirth_r3"
POST = ROOT / "papers/a02_4500_6300_matched_birth_formal900_r4_vins_eval_seal_v3.json"
FREEZE = ROOT / "papers/a02_4500_6300_matched_birth_formal900_r4_vins_eval_freeze_v3.json"
CORRECTED_SEAL = ROOT / "papers/a02_4500_6300_matched_birth_formal900_r4_modefix_continuation_seal_v1.json"
PREFIX = RESULT.parent / ".formal900_r4_xfeatbirth_vs_gfttbirth_r3.855798b90d1b4d8c"
INTENT = Path(str(PREFIX) + ".publication_intent_v1.json")
CLOSEOUT = Path(str(PREFIX) + ".publication_closeout_v1.json")
ANALYSIS = RESULT.parent / "formal900_r4_xfeatbirth_vs_gfttbirth_r3_analysis_v2"
STAGING = RESULT.parent / ".formal900_r4_xfeatbirth_vs_gfttbirth_r3_analysis_v2.staging"

REPORT_NAME = "2026-08-14--matched-birth-r4--r3--common-support-report.md"
ANALYSIS_NAME = "analysis-report.md"
STATS_NAME = "stats-appendix.md"
FIGURES_NAME = "figure-catalog.md"
RECEIPT_NAME = "analysis_receipt_v2.json"

PAYLOAD_NAMES = (
    "bound_summary_v1.json",
    "primary/common_grid_audit.csv",
    "primary/common_support_metrics.csv",
    "primary/common_support_summary.json",
    "primary/runtime_receipt.json",
    "primary_launch_intent.json",
    "verification/common_grid_audit.csv",
    "verification/common_support_metrics.csv",
    "verification/common_support_summary.json",
    "verification/runtime_receipt.json",
    "verification_launch_intent.json",
)
EXPECTED_TREE = frozenset(PAYLOAD_NAMES + (
    "output_manifest.sha256", "result_receipt_v1.json",
))
EXPECTED_DIRS = frozenset(("primary", "verification"))
EXPECTED_ARMS = ("GFTTBIRTH_RAWLK", "XFEATBIRTH_RAWLK")
EXPECTED_GATES = {
    "primary_and_verification_process_rc0_once_no_retry": True,
    "summary_equal_after_reference_only_typed_normalization": True,
    "metrics_csv_bytes_equal": True,
    "grid_csv_bytes_equal": True,
    "actual_runtime_semantics_equal": True,
    "ape_valid": True,
    "rpe_valid": True,
    "grid_count": 90,
}
EXPECTED_OUTCOME = {
    "runner_local_ape_results_visible_before_freeze": True,
    "outcome_blind": False,
    "confirmatory": False,
    "statistical_significance": False,
    "cross_window_generalization": False,
    "whole_slam_superiority": False,
    "reference_is_image_derived_colmap_not_independent_ground_truth": True,
}
PINNED_GOVERNANCE_RECORDS = {
    "post": ("6f2e5c3c5cbf33ce4d3a431a4e609ef8e2940b09e32cbef57cbd888c1e4ae5af", 5_970),
    "freeze": ("9256c648d462968f5b35f6fa6c94dc409b25a8162f3ee4832dfa24f3611c4bd7", 2_357_610),
    "corrected": ("c727cb8cccddcae107db78f55fdeb12f16931ca56e89000398b8249b43ae4ab9", 613_756),
    "intent": ("525984e44b2d61a89d6400de40f2b3bb8dd7150625643df0818f0da69957e0b5", 1_751),
    "closeout": ("65c8392eac8877a60b9afcec9d1890d03409ee42e9026012ea9df159f3921968", 1_708),
    "receipt": ("250ac0db2a58e498543c1f7030461671f62c90a6543075d8597686eaa66c1aa0", 3_265),
    "manifest": ("0e08c32bca0ab3792eb441b262d333f2a079e2923a83eb218de0c093bf0a731a", 1_087),
    "bound_summary_v1.json": ("9605a1c23354e05322d96338a2f8a36e47cc30c9e027519b5c44db6d40831629", 31_909),
}


class ReportError(RuntimeError):
    pass


def _canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True, allow_nan=False).encode("ascii")


def _self_hash(value: Mapping[str, Any], field: str) -> str:
    clone = dict(value)
    if field not in clone:
        raise ReportError(f"missing self-hash field: {field}")
    clone.pop(field)
    return hashlib.sha256(_canonical(clone)).hexdigest()


def _token(value: os.stat_result) -> tuple[int, ...]:
    return (value.st_dev, value.st_ino, value.st_mode, value.st_nlink,
            value.st_uid, value.st_gid, value.st_size,
            value.st_mtime_ns, value.st_ctime_ns)


def _pread(fd: int, size: int) -> bytes:
    chunks: list[bytes] = []
    offset = 0
    while offset < size:
        chunk = os.pread(fd, min(1024 * 1024, size - offset), offset)
        if not chunk:
            raise ReportError("short retained evidence read")
        chunks.append(chunk)
        offset += len(chunk)
    return b"".join(chunks)


@contextmanager
def _hold_file(path: Path, label: str) -> Iterator[dict[str, Any]]:
    fd = os.open(path, os.O_RDONLY | os.O_CLOEXEC | getattr(os, "O_NOFOLLOW", 0))
    try:
        before = os.fstat(fd)
        named = os.lstat(path)
        if (not stat.S_ISREG(before.st_mode) or before.st_nlink != 1
                or _token(before) != _token(named)):
            raise ReportError(f"{label} is not one reachable single-link regular file")
        data = _pread(fd, before.st_size)
        record = {"path": str(path.relative_to(ROOT)),
                  "size_bytes": len(data),
                  "sha256": hashlib.sha256(data).hexdigest()}

        def validate() -> None:
            current = os.fstat(fd)
            reachable = os.lstat(path)
            if (_token(current) != _token(before)
                    or _token(reachable) != _token(before)
                    or _pread(fd, before.st_size) != data):
                raise ReportError(f"{label} changed while retained")

        validate()
        yield {"data": data, "record": record, "validate": validate}
        validate()
    finally:
        os.close(fd)


def _json(data: bytes, label: str) -> dict[str, Any]:
    def reject(_: list[tuple[str, Any]]) -> object:
        raise ReportError(f"{label} contains duplicate JSON keys")
    try:
        value = json.loads(data, object_pairs_hook=lambda pairs: _pairs(pairs, label))
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
        raise ReportError(f"invalid {label}: {error}") from error
    if not isinstance(value, dict):
        raise ReportError(f"{label} must be an object")
    if _canonical(value) + b"\n" != data:
        # Formal JSON is pretty printed.  Require semantic canonicality by a
        # round trip instead of requiring compact transport bytes.
        reparsed = json.loads(_canonical(value))
        if reparsed != value:
            raise ReportError(f"{label} JSON round trip differs")
    return value


def _pairs(pairs: list[tuple[str, Any]], label: str) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ReportError(f"{label} contains duplicate JSON key: {key}")
        result[key] = value
    return result


def _require_hash(value: Mapping[str, Any], field: str, label: str) -> None:
    observed = value.get(field)
    if not isinstance(observed, str) or observed != _self_hash(value, field):
        raise ReportError(f"{label} self hash differs")


def _require_pretty_hash(value: Mapping[str, Any], field: str, label: str) -> None:
    clone = dict(value)
    observed = clone.pop(field, None)
    encoded = (json.dumps(clone, sort_keys=True, indent=2, ensure_ascii=True,
                          allow_nan=False) + "\n").encode("utf-8")
    if not isinstance(observed, str) or observed != hashlib.sha256(encoded).hexdigest():
        raise ReportError(f"{label} pretty self hash differs")


def _record(data: bytes, path: str) -> dict[str, object]:
    return {"path": path, "size_bytes": len(data),
            "sha256": hashlib.sha256(data).hexdigest()}


def _typed_equal(left: object, right: object) -> bool:
    if type(left) is not type(right):
        return False
    if isinstance(left, dict):
        return (left.keys() == right.keys()
                and all(_typed_equal(left[key], right[key]) for key in left))
    if isinstance(left, list):
        return len(left) == len(right) and all(
            _typed_equal(a, b) for a, b in zip(left, right))
    return left == right


def _validate_tree() -> None:
    if not RESULT.is_dir() or RESULT.is_symlink():
        raise ReportError("sealed r3 result directory is missing or symlinked")
    files: set[str] = set()
    dirs: set[str] = set()
    for path in RESULT.rglob("*"):
        rel = str(path.relative_to(RESULT))
        info = os.lstat(path)
        if stat.S_ISDIR(info.st_mode):
            dirs.add(rel)
        elif stat.S_ISREG(info.st_mode) and info.st_nlink == 1:
            files.add(rel)
        else:
            raise ReportError(f"unsupported sealed result entry: {rel}")
    if files != EXPECTED_TREE or dirs != EXPECTED_DIRS:
        raise ReportError("sealed r3 result inventory differs")


def _manifest_records(data: bytes) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for raw in data.decode("ascii", "strict").splitlines():
        digest, separator, name = raw.partition("  ")
        if separator != "  " or len(digest) != 64 or name not in PAYLOAD_NAMES:
            raise ReportError("output manifest line differs")
        rows.append({"path": name, "sha256": digest})
    if [row["path"] for row in rows] != list(PAYLOAD_NAMES):
        raise ReportError("output manifest ordering differs")
    return rows


def _finite(value: object, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ReportError(f"finite {label} required")
    result = float(value)
    if not math.isfinite(result):
        raise ReportError(f"finite {label} required")
    return result


def _load_evidence(stack: ExitStack) -> dict[str, Any]:
    _validate_tree()
    paths = {
        "renderer": SOURCE,
        "post": POST, "freeze": FREEZE, "corrected": CORRECTED_SEAL,
        "intent": INTENT, "closeout": CLOSEOUT,
        "receipt": RESULT / "result_receipt_v1.json",
        "manifest": RESULT / "output_manifest.sha256",
        **{name: RESULT / name for name in PAYLOAD_NAMES},
    }
    held = {name: stack.enter_context(_hold_file(path, name))
            for name, path in paths.items()}
    for key, (digest, size) in PINNED_GOVERNANCE_RECORDS.items():
        record = held[key]["record"]
        if record["sha256"] != digest or record["size_bytes"] != size:
            raise ReportError(f"pinned governance record differs: {key}")
    post = _json(held["post"]["data"], "post")
    freeze = _json(held["freeze"]["data"], "freeze")
    corrected = _json(held["corrected"]["data"], "corrected detector seal")
    intent = _json(held["intent"]["data"], "publication intent")
    closeout = _json(held["closeout"]["data"], "publication closeout")
    receipt = _json(held["receipt"]["data"], "result receipt")
    bound = _json(held["bound_summary_v1.json"]["data"], "bound summary")

    expected_schemas = (
        (post, "aqua-fe-matched-birth-r4-vins-g0-post-seal-v4", "post"),
        (freeze, "aqua-fe-matched-birth-r4-vins-g0-freeze-v4", "freeze"),
        (bound, "aqua-fe-matched-birth-r4-vins-g0-bound-summary-v4", "bound"),
        (receipt, "isj-p07-g0-result-receipt-v1", "receipt"),
        (intent, "isj-p07-g0-publication-intent-v1", "intent"),
        (closeout, "isj-p07-g0-publication-closeout-v1", "closeout"),
    )
    for value, schema, label in expected_schemas:
        if value.get("schema_version") != schema:
            raise ReportError(f"{label} schema differs")
    if (post.get("status") != "PASS_STRICT_FULL_REFERENCE_COMMON_SUPPORT"
            or post.get("pass") is not True or post.get("failure_reasons") != []
            or post.get("post_process_start_count") != 0
            or not _typed_equal(post.get("strict_gates"), EXPECTED_GATES)
            or not _typed_equal(post.get("outcome_boundary"), EXPECTED_OUTCOME)):
        raise ReportError("strict post result differs")
    if (freeze.get("status") != "FROZEN_POST_RESULT_EXPLORATORY_FORMAL900_FULL_REFERENCE_G0"
            or not _typed_equal(freeze.get("outcome_boundary"), EXPECTED_OUTCOME)
            or bound.get("status") != "COMPLETED_PRIMARY_AND_VERIFICATION_RC0"
            or not _typed_equal(bound.get("outcome_boundary"), EXPECTED_OUTCOME)
            or corrected.get("status") != "PASS" or corrected.get("pass") is not True):
        raise ReportError("freeze/bound/corrected authority differs")
    if corrected.get("schema_version") != (
            "aqua-fe-detector-birth-rawlk-matched-pair-formal-r4-"
            "modefix-continuation-audit-v1"):
        raise ReportError("corrected detector seal schema differs")
    corrected_claim = corrected.get("claim_boundary")
    if (not isinstance(corrected_claim, dict)
            or corrected_claim.get("confirmatory") is not False
            or corrected_claim.get("statistical_significance") is not False
            or corrected_claim.get("whole_slam_superiority") is not False
            or corrected_claim.get("detector_rerun_or_r4_mutation_authorized") is not False):
        raise ReportError("corrected detector claim boundary differs")
    if freeze.get("input_records", {}).get("corrected_seal") != held["corrected"]["record"]:
        raise ReportError("corrected detector seal is not the frozen input record")
    for value, field, label in (
        (post, "post_hash", "post"), (freeze, "freeze_hash", "freeze"),
        (bound, "bound_summary_hash", "bound summary"),
        (receipt, "result_receipt_hash", "result receipt"),
        (intent, "publication_intent_hash", "publication intent"),
        (closeout, "publication_closeout_hash", "publication closeout"),
    ):
        _require_hash(value, field, label)

    actual_payload = [_record(held[name]["data"], name) for name in PAYLOAD_NAMES]
    if (receipt.get("payload_records") != actual_payload
            or post.get("published_payload_records") != actual_payload):
        raise ReportError("published payload inventory differs")
    manifest_rows = _manifest_records(held["manifest"]["data"])
    for row, record in zip(manifest_rows, actual_payload):
        if row != {"path": record["path"], "sha256": record["sha256"]}:
            raise ReportError("manifest payload record differs")
    manifest_record = _record(held["manifest"]["data"],
                              str((RESULT / "output_manifest.sha256").relative_to(ROOT)))
    if receipt.get("output_manifest") != manifest_record:
        raise ReportError("receipt manifest record differs")
    if post.get("freeze") != held["freeze"]["record"]:
        raise ReportError("post freeze record differs")
    if bound.get("freeze") != held["freeze"]["record"]:
        raise ReportError("bound summary freeze record differs")
    if (closeout.get("output_manifest") != manifest_record
            or closeout.get("receipt") != held["receipt"]["record"]):
        raise ReportError("closeout retained file records differ")
    for key, expected in (
        ("freeze_hash", freeze["freeze_hash"]),
        ("bound_summary_hash", bound["bound_summary_hash"]),
        ("result_receipt_hash", receipt["result_receipt_hash"]),
        ("publication_intent_hash", intent["publication_intent_hash"]),
        ("publication_closeout_hash", closeout["publication_closeout_hash"]),
    ):
        if post.get(key) != expected:
            raise ReportError(f"post {key} cross-bind differs")
    if (bound.get("freeze_hash") != freeze["freeze_hash"]
            or bound.get("publication_intent_hash") != intent["publication_intent_hash"]
            or receipt.get("publication_intent_hash") != intent["publication_intent_hash"]
            or closeout.get("publication_intent_hash") != intent["publication_intent_hash"]
            or closeout.get("result_receipt_hash") != receipt["result_receipt_hash"]):
        raise ReportError("publication hash chain differs")
    job_hash = freeze.get("publication_authority", {}).get("job_hash")
    destination = str(RESULT)
    if (job_hash != "855798b90d1b4d8c79e04c49cd348ef10d391ca32f419963d92601e162c8ecd6"
            or any(value.get("job_hash") != job_hash
                   for value in (intent, receipt, closeout))
            or any(value.get("destination_absolute") != destination
                   for value in (intent, receipt, closeout))):
        raise ReportError("job/destination publication authority differs")
    authority = freeze.get("publication_authority")
    if not isinstance(authority, dict):
        raise ReportError("freeze publication authority is absent")
    expected_common = {
        "job_id": authority.get("job_id"),
        "job_hash": authority.get("job_hash"),
        "plan_hash": authority.get("plan_hash"),
        "evaluation_lock_hash": authority.get("evaluation_lock_hash"),
        "backend_execution_lock_hash": authority.get("backend_execution_lock_hash"),
        "g0_execution_authority_hash": freeze["freeze_hash"],
        "outcome_boundary": freeze.get("publication_technical_boundary"),
    }
    for label, value, expected_status in (
        ("intent", intent, "PLANNED_NO_CLOBBER_PUBLICATION"),
        ("receipt", receipt, "SEALED_STAGING_RESULT"),
        ("closeout", closeout, "ATOMICALLY_PUBLISHED_NO_CLOBBER"),
    ):
        if value.get("status") != expected_status:
            raise ReportError(f"{label} publication status differs")
        if any(value.get(key) != expected for key, expected in expected_common.items()):
            raise ReportError(f"{label} publication authority differs")
    if (intent.get("evaluation_disposition") != authority.get("evaluation_disposition")
            or receipt.get("evaluation_disposition") != authority.get("evaluation_disposition")):
        raise ReportError("publication evaluation disposition differs")

    for leaf in ("common_support_summary.json", "common_support_metrics.csv",
                 "common_grid_audit.csv"):
        if held[f"primary/{leaf}"]["data"] != held[f"verification/{leaf}"]["data"]:
            raise ReportError(f"role {leaf} bytes differ")
    normalized = bound.get("normalized_summary")
    if not isinstance(normalized, dict) or set(normalized.get("arms", {})) != set(EXPECTED_ARMS):
        raise ReportError("normalized summary arms differ")
    if not _typed_equal(post.get("result_metrics"), normalized["arms"]):
        raise ReportError("post result metric echo differs")
    support = normalized.get("support")
    protocol = normalized.get("protocol")
    if (not isinstance(support, dict) or support.get("grid_count") != 90
            or support.get("matched_count") != 84
            or support.get("rpe_pairs") != 83
            or support.get("ape_valid") is not True
            or support.get("rpe_valid") is not True
            or not isinstance(protocol, dict)
            or protocol.get("contrast_name") != "A02_4500_6300_MATCHED_BIRTH_FORMAL900_R4_XFEAT_VS_GFTT_FULL_REFERENCE"
            or protocol.get("rpe_semantics") != "aligned_global_frame_positional_delta"
            or protocol.get("reference") != str(ROOT / "datasets/aqualoc/rosbags/archaeo02_4500_6300.bag") + ":/aqualoc/colmap_gt"):
        raise ReportError("normalized protocol/support differs")
    rows = list(csv.DictReader(io.StringIO(
        held["primary/common_support_metrics.csv"]["data"].decode("ascii"))))
    if [row.get("arm") for row in rows] != list(EXPECTED_ARMS):
        raise ReportError("metrics CSV arm order differs")
    for row in rows:
        arm = str(row["arm"])
        for key in ("ape_rmse_m", "ape_median_m", "ape_max_m",
                    "rpe_rmse_m", "rpe_median_m", "rpe_max_m"):
            if float(row[key]) != normalized["arms"][arm][key]:
                raise ReportError(f"metrics CSV {arm} {key} differs")
    for role in ("primary", "verification"):
        runtime = _json(held[f"{role}/runtime_receipt.json"]["data"], f"{role} runtime")
        if (runtime.get("role") != role or runtime.get("evaluator_called") is not True
                or runtime.get("evaluator_rc") != 0
                or runtime.get("evaluator_error") is not None
                or runtime.get("status") != "ACTUAL_RUNTIME_CAPTURED"):
            raise ReportError(f"{role} runtime terminal state differs")
        _require_pretty_hash(runtime, "runtime_receipt_hash", f"{role} runtime")
    return {"held": held, "post": post, "freeze": freeze, "bound": bound,
            "intent": intent, "closeout": closeout, "receipt": receipt,
            "normalized": normalized, "support": support, "protocol": protocol}


def _fmt(value: object, digits: int = 10) -> str:
    return format(_finite(value, "metric"), f".{digits}g")


def _render(evidence: Mapping[str, Any]) -> dict[str, bytes]:
    summary = evidence["normalized"]
    arms = summary["arms"]
    support = summary["support"]
    g = arms["GFTTBIRTH_RAWLK"]
    x = arms["XFEATBIRTH_RAWLK"]
    ape_delta = _finite(g["ape_rmse_m"], "GFTT APE") - _finite(x["ape_rmse_m"], "XFeat APE")
    rpe_delta = _finite(g["rpe_rmse_m"], "GFTT RPE") - _finite(x["rpe_rmse_m"], "XFeat RPE")
    ape_pct = 100.0 * ape_delta / _finite(g["ape_rmse_m"], "GFTT APE")
    rpe_pct = 100.0 * rpe_delta / _finite(g["rpe_rmse_m"], "GFTT RPE")
    table = (
        "| Arm | APE RMSE (m) | APE median (m) | RPE RMSE (m) | RPE median (m) | Common poses | RPE pairs |\n"
        "|---|---:|---:|---:|---:|---:|---:|\n"
        f"| GFTT birth raw-LK | {_fmt(g['ape_rmse_m'])} | {_fmt(g['ape_median_m'])} | {_fmt(g['rpe_rmse_m'])} | {_fmt(g['rpe_median_m'])} | {g['matched_count']} | {g['rpe_pairs']} |\n"
        f"| XFeat birth raw-LK | {_fmt(x['ape_rmse_m'])} | {_fmt(x['ape_median_m'])} | {_fmt(x['rpe_rmse_m'])} | {_fmt(x['rpe_median_m'])} | {x['matched_count']} | {x['rpe_pairs']} |\n"
    )
    report = f"""# A02 matched-birth r4 frozen common-support report (r3)

The sealed formal result is `PASS_STRICT_FULL_REFERENCE_COMMON_SUPPORT`. This document transcribes the sealed r3 summary and CSV; it does not open trajectories or recompute APE/RPE.

{table}
Common support is {support['matched_count']}/{support['grid_count']} ({_fmt(support['common_coverage'])}), spanning {_fmt(support['common_span_s'])} s in {support['segment_count']} segment, with {support['rpe_pairs']} one-second RPE pairs.

For descriptive presentation only, the sealed point estimates give an APE RMSE reduction of {_fmt(ape_delta)} m ({_fmt(ape_pct, 6)}%) and an RPE RMSE reduction of {_fmt(rpe_delta)} m ({_fmt(rpe_pct, 6)}%) for XFeat-birth relative to GFTT-birth on this one frozen window.

## Claim boundary

- This is post-result exploratory evidence; it was not outcome-blind or confirmatory.
- `n=1` frozen A02 window and one underlying VINS replay per arm. The two evaluator roles are a deterministic consistency check, not independent samples.
- No significance test, confidence interval, cross-window/dataset generalization, whole-SLAM superiority, or standalone detector superiority is claimed.
- The reference is image-derived COLMAP, not independent external ground truth.
- Runner-local APE outputs were visible before freeze; this report uses only the sealed common-support result.
"""
    analysis = f"""# Analysis report

## Question

Within the frozen A02 4500–6300 matched-birth carrier, how do the two already-produced VINS trajectories compare on one reference-anchored common mask?

## Observation

{table}
Both APE and 1 s positional RPE RMSE are lower for the XFeat-birth arm on the sealed common support. The descriptive reductions are {_fmt(ape_pct, 6)}% for APE RMSE and {_fmt(rpe_pct, 6)}% for RPE RMSE.

## Interpretation limit

This observation is specific to one post-result exploratory window. It does not establish causal detector superiority, statistical significance, or generalization. Both role executions used the same code and inputs, so role agreement establishes execution consistency only.
"""
    stats = f"""# Stats appendix

{table}
Support: grid={support['grid_count']}, common={support['matched_count']}, coverage={_fmt(support['common_coverage'])}, span={_fmt(support['common_span_s'])} s, segments={support['segment_count']}, RPE pairs={support['rpe_pairs']}.

Derived presentation arithmetic from sealed scalars: APE delta={_fmt(ape_delta)} m; RPE delta={_fmt(rpe_delta)} m. No inferential statistic is reported.
"""
    figures = """# Figure catalog

No figure is published by report generation v2.

Permitted sealed sources for a later, separately reviewed renderer:

- `primary/common_support_metrics.csv` for table/point-estimate plots.
- `primary/common_grid_audit.csv` for support-mask visualization.

The verification copies are byte-identical consistency evidence. A later renderer must not read trajectories or recompute APE/RPE.
"""
    return {
        REPORT_NAME: report.encode("utf-8"),
        ANALYSIS_NAME: analysis.encode("utf-8"),
        STATS_NAME: stats.encode("utf-8"),
        FIGURES_NAME: figures.encode("utf-8"),
    }


def _receipt(evidence: Mapping[str, Any], documents: Mapping[str, bytes]) -> dict[str, Any]:
    held = evidence["held"]
    value: dict[str, Any] = {
        "schema_version": "aqua-fe-matched-birth-r4-vins-analysis-receipt-v2",
        "status": "TRANSCRIBED_FROM_SEALED_R3_WITHOUT_SCIENTIFIC_RECOMPUTATION",
        "source_records": [held[key]["record"] for key in sorted(held)],
        "freeze_hash": evidence["freeze"]["freeze_hash"],
        "post_hash": evidence["post"]["post_hash"],
        "publication_intent_hash": evidence["intent"]["publication_intent_hash"],
        "result_receipt_hash": evidence["receipt"]["result_receipt_hash"],
        "publication_closeout_hash": evidence["closeout"]["publication_closeout_hash"],
        "bound_summary_hash": evidence["bound"]["bound_summary_hash"],
        "strict_gates": evidence["post"]["strict_gates"],
        "outcome_boundary": evidence["post"]["outcome_boundary"],
        "no_scientific_recomputation": True,
        "derived_presentation_arithmetic_only": True,
        "document_records": [
            {"path": name, "size_bytes": len(data),
             "sha256": hashlib.sha256(data).hexdigest()}
            for name, data in sorted(documents.items())
        ],
        "analysis_hash": "0" * 64,
    }
    value["analysis_hash"] = _self_hash(value, "analysis_hash")
    return value


def _write_all(fd: int, data: bytes) -> None:
    offset = 0
    while offset < len(data):
        count = os.write(fd, data[offset:])
        if count <= 0:
            raise ReportError("zero-progress report write")
        offset += count


def _publish(files: Mapping[str, bytes], validate_sources) -> None:
    if os.path.lexists(ANALYSIS) or os.path.lexists(STAGING):
        raise ReportError("analysis or staging namespace already exists")
    os.mkdir(STAGING, 0o700)
    committed = False
    try:
        for name, data in sorted(files.items()):
            fd = os.open(STAGING / name,
                         os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC,
                         0o444)
            try:
                _write_all(fd, data)
                os.fsync(fd)
            finally:
                os.close(fd)
        directory_fd = os.open(STAGING, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
        validate_sources()
        libc = ctypes.CDLL(None, use_errno=True)
        renameat2 = getattr(libc, "renameat2", None)
        if renameat2 is None:
            raise ReportError("renameat2 is unavailable")
        renameat2.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int,
                              ctypes.c_char_p, ctypes.c_uint]
        renameat2.restype = ctypes.c_int
        if renameat2(-100, os.fsencode(STAGING), -100, os.fsencode(ANALYSIS), 1) != 0:
            code = ctypes.get_errno()
            if code in (errno.EEXIST, errno.ENOTEMPTY):
                raise ReportError("analysis destination already exists")
            raise ReportError(f"analysis renameat2 failed: errno={code}")
        committed = True
        observed_names = {item.name for item in ANALYSIS.iterdir()}
        if observed_names != set(files):
            raise ReportError("published analysis inventory differs")
        for name, expected in files.items():
            path = ANALYSIS / name
            info = os.lstat(path)
            if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1
                    or stat.S_IMODE(info.st_mode) != 0o444
                    or path.read_bytes() != expected):
                raise ReportError(f"published analysis leaf differs: {name}")
        parent_fd = os.open(ANALYSIS.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
        try:
            os.fsync(parent_fd)
        finally:
            os.close(parent_fd)
    finally:
        if not committed and STAGING.exists():
            shutil.rmtree(STAGING)


def execute(action: str) -> dict[str, Any]:
    with ExitStack() as stack:
        evidence = _load_evidence(stack)
        documents = _render(evidence)
        receipt = _receipt(evidence, documents)
        files = dict(documents)
        files[RECEIPT_NAME] = json.dumps(
            receipt, indent=2, sort_keys=True, ensure_ascii=True,
            allow_nan=False).encode("ascii") + b"\n"
        validators = [value["validate"] for value in evidence["held"].values()]

        def validate_all() -> None:
            for validator in validators:
                validator()
            _validate_tree()

        validate_all()
        if action == "write-once":
            _publish(files, validate_all)
            validate_all()
        return {"status": "PASS_REPORT_V2_PREPUBLICATION" if action == "check"
                else "PASS_REPORT_V2_PUBLISHED",
                "write_performed": action == "write-once",
                "analysis_hash": receipt["analysis_hash"],
                "destination": str(ANALYSIS),
                "documents": receipt["document_records"]}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument("--action", required=True, choices=("check", "write-once"))
    args = parser.parse_args(argv)
    try:
        print(json.dumps(execute(args.action), indent=2, sort_keys=True))
        return 0
    except (ReportError, OSError, ValueError, KeyError, TypeError) as error:
        print(f"REPORT_BLOCKED:{type(error).__name__}:{error}", file=os.sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
