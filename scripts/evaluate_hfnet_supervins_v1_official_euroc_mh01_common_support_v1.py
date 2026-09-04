#!/usr/bin/env python3
"""One-shot, ROS-free common-support analysis of two sealed MH01 artifacts.

``preflight`` is timestamp-only: it validates identities and exact support but
does not parse positions, align trajectories, or compute error values.  The
``run`` action additionally requires a separately sealed root authority.
"""

from __future__ import annotations

import argparse
import csv
from datetime import datetime
from decimal import Decimal, InvalidOperation
import hashlib
import html
import importlib.util
import io
import json
import math
import os
from pathlib import Path
import re
import signal
import stat
import sys
import traceback
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

import numpy as np


sys.dont_write_bytecode = True

ROOT = Path(__file__).resolve().parents[1]
RUNNER = Path(__file__).resolve()
TESTS = ROOT / "scripts/tests/test_evaluate_hfnet_supervins_v1_official_euroc_mh01_common_support_v1.py"
FREEZE = ROOT / "papers/hfnet_supervins_v1_official_euroc_mh01_common_support_descriptive_freeze_v1.json"
LOCK = ROOT / "papers/hfnet_supervins_v1_official_euroc_mh01_common_support_execution_lock_v1.json"
AUTHORITY = ROOT / "papers/hfnet_supervins_v1_official_euroc_mh01_common_support_execution_authority_v1.json"
TEST_RECEIPT = ROOT / "papers/hfnet_supervins_v1_official_euroc_mh01_common_support_test_receipt_v1.json"
STAGE5_RUNNER = ROOT / "scripts/evaluate_published_supervins_v1_official_euroc_mh01_full_trajectory_gt_v1.py"
CORE = ROOT / "scripts/trajectory_eval_core.py"

EVIDENCE_ROOT = ROOT / "experiments/published_hfnet_supervins_v1_official_euroc_mh01_common_support_descriptive_20260821_r1"
ATTEMPT = EVIDENCE_ROOT / "attempt_001"
ANALYSIS = ATTEMPT / "analysis-output"
FIGURES = ANALYSIS / "figures"
START_CLAIM = ATTEMPT / "evaluation_start_claim.json"
PREFLIGHT_RESULT = ATTEMPT / "preflight_result.json"
RUN_RESULT = ATTEMPT / "run_result.json"

HF_TRAJECTORY = Path("/mnt/data/AQUA-FE_WS/logs/published_hfnet_slam_v6/dev_euroc_mh01/attempt_001/result/trajectory.txt")
HF_RESULT = Path("/mnt/data/AQUA-FE_WS/logs/published_hfnet_slam_v6/dev_euroc_mh01/attempt_001/run_result.json")
HF_STDOUT = Path("/mnt/data/AQUA-FE_WS/logs/published_hfnet_slam_v6/dev_euroc_mh01/attempt_001/headless.stdout.log")
HF_STDERR = Path("/mnt/data/AQUA-FE_WS/logs/published_hfnet_slam_v6/dev_euroc_mh01/attempt_001/headless.stderr.log")
SV_TRAJECTORY = ROOT / "experiments/published_supervins_v1_official_euroc_mh01_full_trajectory_20260817_r1/attempt_001/trajectory_output/vio.csv"
SV_RESULT = ROOT / "experiments/published_supervins_v1_official_euroc_mh01_full_trajectory_20260817_r1/attempt_001/run_result.json"
DATASET = Path("/mnt/data/AQUA-FE_WS/datasets/official_euroc_v1/MH01/MH_01_easy/mav0")
CAMERA_CSV = DATASET / "cam0/data.csv"
GT_CSV = DATASET / "state_groundtruth_estimate0/data.csv"
GT_SENSOR = DATASET / "state_groundtruth_estimate0/sensor.yaml"
IMU_SENSOR = DATASET / "imu0/sensor.yaml"

TOKEN = "HFNET_SUPERVINS_STAGE6_MH01_COMMON_SUPPORT_ATTEMPT_001_START_ONCE"
TOKEN_SHA256 = hashlib.sha256(TOKEN.encode("utf-8")).hexdigest()
CONTROLLER_COMMAND = ["/usr/bin/python3.8", "-B", str(RUNNER), "--action", "run", "--authorization-token", TOKEN]

FREEZE_SCHEMA = "aqua-fe-hfnet-supervins-mh01-common-support-descriptive-freeze-v1"
LOCK_SCHEMA = "aqua-fe-hfnet-supervins-mh01-common-support-execution-lock-v1"
AUTHORITY_SCHEMA = "aqua-fe-hfnet-supervins-mh01-common-support-root-authority-v1"
RESULT_SCHEMA = "aqua-fe-hfnet-supervins-mh01-common-support-result-v1"

CAMERA_ROWS = 3682
GT_ROWS = 36382
HF_ROWS = 2737
SV_ROWS = 1810
COMMON_FIRST = 945
COMMON_LAST = 3659
COMMON_STEP = 2
COMMON_COUNT = 1358
COMMON_FIRST_NS = 1403636627013555456
COMMON_LAST_NS = 1403636762713555456
COMMON_SPAN_NS = 135700000000
RPE_INDEX_DELTA = 10
RPE_CAMERA_DELTA = 20
RPE_DELTA_NS = 1_000_000_000
RPE_COUNT = 1348

REQUIRED_BUNDLE_FILES = [
    "analysis-output/metrics.json",
    "analysis-output/input-audit.json",
    "analysis-output/support-audit.json",
    "analysis-output/alignment.json",
    "analysis-output/common-support-poses.csv",
    "analysis-output/common-support-rpe-1s.csv",
    "analysis-output/analysis-report.md",
    "analysis-output/stats-appendix.md",
    "analysis-output/figure-catalog.md",
    "analysis-output/figures/figure-01-primary-common-support-overlay.svg",
    "analysis-output/figures/figure-02-primary-error-traces.svg",
    "analysis-output/artifact-manifest.json",
]

POSE_HEADER = [
    "common_row_index", "camera_row_index", "source_timestamp_ns", "gt_row_index",
    "gt_x_m", "gt_y_m", "gt_z_m",
    "hfnet_x_m", "hfnet_y_m", "hfnet_z_m",
    "hfnet_se3_x_m", "hfnet_se3_y_m", "hfnet_se3_z_m", "hfnet_se3_ape_m",
    "hfnet_sim3_x_m", "hfnet_sim3_y_m", "hfnet_sim3_z_m", "hfnet_sim3_ape_m",
    "supervins_x_m", "supervins_y_m", "supervins_z_m",
    "supervins_se3_x_m", "supervins_se3_y_m", "supervins_se3_z_m", "supervins_se3_ape_m",
    "supervins_sim3_x_m", "supervins_sim3_y_m", "supervins_sim3_z_m", "supervins_sim3_ape_m",
]
RPE_HEADER = [
    "pair_row_index", "left_camera_row_index", "right_camera_row_index",
    "left_timestamp_ns", "right_timestamp_ns", "delta_ns",
    "hfnet_se3_rpe_m", "hfnet_sim3_rpe_m",
    "supervins_se3_rpe_m", "supervins_sim3_rpe_m",
]

SNAPSHOT_PATHS = [HF_TRAJECTORY, HF_RESULT, HF_STDOUT, HF_STDERR, SV_TRAJECTORY, SV_RESULT,
                  CAMERA_CSV, GT_CSV, GT_SENSOR, IMU_SENSOR]
FORBIDDEN_REPORT_TOKENS = [
    "difference", "delta", "ratio", "%", "better", "outperform", "winner", "best",
    "superior", "rank", "p-value", "p_value", "confidence interval", "effect size",
]

PENDING_SIGNAL: Optional[int] = None
NAMESPACE_OWNED = False
TERMINAL_COMMITTED = False


class ControlledSignal(RuntimeError):
    pass


def _load_stage5() -> Any:
    spec = importlib.util.spec_from_file_location("frozen_stage5_eval", str(STAGE5_RUNNER))
    if spec is None or spec.loader is None:
        raise ImportError("cannot load frozen Stage5 evaluator")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


STAGE5 = _load_stage5()
rigid_se3_alignment = STAGE5.rigid_se3_alignment
proper_umeyama_sim3 = STAGE5.proper_umeyama_sim3
alignment_audit = STAGE5.alignment_audit
descriptive_stats = STAGE5.descriptive_stats
metric_samples = STAGE5.metric_samples


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def canonical_json_bytes(value: Any) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False) + "\n").encode("utf-8")


def compact_json_bytes(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def file_identity(path: Path, include_seal: bool = False) -> Dict[str, Any]:
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(str(path), flags)
    try:
        before = os.fstat(fd)
        if not stat.S_ISREG(before.st_mode):
            raise ValueError("identity path must be a regular non-symlink file")
        digest = hashlib.sha256()
        total = 0
        while True:
            block = os.read(fd, 1024 * 1024)
            if not block:
                break
            digest.update(block)
            total += len(block)
        after = os.fstat(fd)
        path_info = os.lstat(str(path))
    finally:
        os.close(fd)
    if not stat.S_ISREG(path_info.st_mode) or not (
        before.st_dev == after.st_dev == path_info.st_dev
        and before.st_ino == after.st_ino == path_info.st_ino
        and before.st_size == after.st_size == path_info.st_size == total
    ):
        raise ValueError("identity path changed or is not a regular non-symlink file")
    result: Dict[str, Any] = {"sha256": digest.hexdigest(), "size_bytes": total}
    if include_seal:
        result.update({"mode": format(stat.S_IMODE(after.st_mode), "04o"), "nlink": after.st_nlink})
    return result


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as stream:
        return json.load(stream)


def fsync_directory(path: Path) -> None:
    fd = os.open(str(path), os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def mkdir_exclusive_durable(path: Path, mode: int = 0o755) -> None:
    os.mkdir(str(path), mode)
    fsync_directory(path.parent)


def create_owned_evidence_root(mode: int = 0o755) -> None:
    """Create the one-shot root and record ownership before fallible durability work."""
    global NAMESPACE_OWNED
    os.mkdir(str(EVIDENCE_ROOT), mode)
    NAMESPACE_OWNED = True
    fsync_directory(EVIDENCE_ROOT.parent)


def write_bytes_exclusive(path: Path, payload: bytes, mode: int = 0o444) -> Dict[str, Any]:
    fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        offset = 0
        while offset < len(payload):
            offset += os.write(fd, payload[offset:])
        os.fchmod(fd, mode)
        os.fsync(fd)
    finally:
        os.close(fd)
    fsync_directory(path.parent)
    return file_identity(path, include_seal=True)


def write_json_exclusive(path: Path, value: Any) -> Dict[str, Any]:
    return write_bytes_exclusive(path, canonical_json_bytes(value))


def write_text_exclusive(path: Path, value: str) -> Dict[str, Any]:
    return write_bytes_exclusive(path, value.encode("utf-8"))


def canonical_pin_digest(pins: Mapping[str, Mapping[str, Any]]) -> str:
    rows = [{"path": p, "sha256": v["sha256"], "size_bytes": int(v["size_bytes"])} for p, v in sorted(pins.items())]
    return sha256_bytes(compact_json_bytes(rows))


def artifact_tree_digest(entries: Mapping[str, Mapping[str, Any]]) -> str:
    rows = [{"path": p, "sha256": v["sha256"], "size_bytes": int(v["size_bytes"])} for p, v in sorted(entries.items())]
    return sha256_bytes(compact_json_bytes(rows))


def self_hash_object(value: Mapping[str, Any]) -> str:
    clone = dict(value)
    clone["self_hash"] = None
    return sha256_bytes(compact_json_bytes(clone))


def _signal_handler(signum: int, _frame: Any) -> None:
    global PENDING_SIGNAL
    if PENDING_SIGNAL is None:
        PENDING_SIGNAL = signum


def install_signal_handlers() -> Dict[int, Any]:
    previous: Dict[int, Any] = {}
    for signum in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
        previous[signum] = signal.getsignal(signum)
        signal.signal(signum, _signal_handler)
    return previous


def restore_signal_handlers(previous: Mapping[int, Any]) -> None:
    for signum, handler in previous.items():
        signal.signal(signum, handler)


def raise_if_pending() -> None:
    if PENDING_SIGNAL is not None:
        raise ControlledSignal("caught signal {}".format(PENDING_SIGNAL))


def parse_mode(value: Any) -> int:
    text = str(value)
    return int(text, 8)


def inspect_pins(expected: Mapping[str, Mapping[str, Any]]) -> Dict[str, Any]:
    checks: Dict[str, Any] = {}
    failures: List[str] = []
    for path_text, spec in sorted(expected.items()):
        path = Path(path_text)
        try:
            observed = file_identity(path, include_seal=True)
            ok = observed["sha256"] == spec["sha256"] and observed["size_bytes"] == int(spec["size_bytes"])
            if "mode" in spec:
                ok &= observed["mode"] == format(parse_mode(spec["mode"]), "04o")
            if "nlink" in spec:
                ok &= observed["nlink"] == int(spec["nlink"])
            error = None
        except Exception as exc:
            observed = None
            ok = False
            error = "{}: {}".format(type(exc).__name__, exc)
        checks[path_text] = {"expected": dict(spec), "observed": observed, "ok": bool(ok), "error": error}
        if not ok:
            failures.append(path_text)
    return {"checks": checks, "failures": failures, "ok": not failures}


def verify_sealed(path: Path) -> bool:
    try:
        info = os.lstat(str(path))
        return stat.S_IMODE(info.st_mode) == 0o444 and info.st_nlink == 1 and stat.S_ISREG(info.st_mode)
    except OSError:
        return False


def decimal_fixed6_seconds_to_ns(text: str) -> int:
    if not re.fullmatch(r"[0-9]+\.[0-9]{6}", text):
        raise ValueError("not fixed-six seconds: {}".format(text))
    try:
        scaled = Decimal(text) * Decimal(1_000_000_000)
    except InvalidOperation as exc:
        raise ValueError("invalid decimal timestamp") from exc
    if scaled != scaled.to_integral_value():
        raise ValueError("fixed-six timestamp is not integral nanoseconds")
    return int(scaled)


def hf_timestamp_to_ns(text: str) -> int:
    match = re.fullmatch(r"([0-9]{19})\.([0-9]{6})", text)
    if not match or match.group(2) != "000000":
        raise ValueError("HFNet timestamp must be 19-digit ns plus .000000")
    value = Decimal(text)
    if value != value.to_integral_value():
        raise ValueError("HFNet timestamp is not integral nanoseconds")
    return int(match.group(1))


def parse_csv_records(payload: bytes, expected_columns: int, timestamp_only: bool) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    stream = io.StringIO(payload.decode("utf-8"), newline="")
    for record in csv.reader(stream):
        if not record or record[0].startswith("#"):
            continue
        if len(record) != expected_columns:
            raise ValueError("CSV row has {} columns; expected {}".format(len(record), expected_columns))
        timestamp_ns = int(record[0])
        if rows and timestamp_ns <= rows[-1]["timestamp_ns"]:
            raise ValueError("CSV timestamps are not strictly increasing")
        row: Dict[str, Any] = {"row_index": len(rows), "timestamp_ns": timestamp_ns}
        if not timestamp_only:
            values = [float(x) for x in record[1:]]
            if not all(math.isfinite(x) for x in values):
                raise ValueError("non-finite CSV value")
            row["position"] = values[0:3]
            if expected_columns == 17:
                row["quaternion_xyzw"] = [values[4], values[5], values[6], values[3]]
        rows.append(row)
    return rows


def parse_camera(payload: bytes) -> List[Dict[str, Any]]:
    return parse_csv_records(payload, 2, True)


def parse_gt(payload: bytes, timestamp_only: bool) -> List[Dict[str, Any]]:
    return parse_csv_records(payload, 17, timestamp_only)


def parse_hf(payload: bytes, timestamp_only: bool) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for line_no, raw in enumerate(payload.decode("utf-8").splitlines(), 1):
        if not raw.strip():
            raise ValueError("blank HFNet line {}".format(line_no))
        fields = raw.split()
        if len(fields) != 8:
            raise ValueError("HFNet line {} column count".format(line_no))
        timestamp_ns = hf_timestamp_to_ns(fields[0])
        if rows and timestamp_ns <= rows[-1]["timestamp_ns"]:
            raise ValueError("HFNet timestamps are not strictly increasing")
        row: Dict[str, Any] = {"row_index": len(rows), "timestamp_text": fields[0], "timestamp_ns": timestamp_ns}
        if not timestamp_only:
            values = [float(x) for x in fields[1:]]
            if not all(math.isfinite(x) for x in values):
                raise ValueError("non-finite HFNet pose")
            norm = math.sqrt(sum(x * x for x in values[3:7]))
            if not 0.9 <= norm <= 1.1:
                raise ValueError("invalid HFNet quaternion")
            row.update({"position": values[0:3], "quaternion_xyzw": values[3:7]})
        rows.append(row)
    return rows


def parse_sv(payload: bytes, timestamp_only: bool) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for line_no, raw in enumerate(payload.decode("utf-8").splitlines(), 1):
        if not raw.strip():
            raise ValueError("blank SuperVINS line {}".format(line_no))
        fields = raw.split()
        if len(fields) != 8:
            raise ValueError("SuperVINS line {} column count".format(line_no))
        display_ns = decimal_fixed6_seconds_to_ns(fields[0])
        if rows and display_ns <= rows[-1]["display_ns"]:
            raise ValueError("SuperVINS timestamps are not strictly increasing")
        row: Dict[str, Any] = {"row_index": len(rows), "timestamp_text": fields[0], "display_ns": display_ns}
        if not timestamp_only:
            values = [float(x) for x in fields[1:]]
            if not all(math.isfinite(x) for x in values):
                raise ValueError("non-finite SuperVINS pose")
            norm = math.sqrt(sum(x * x for x in values[3:7]))
            if not 0.9 <= norm <= 1.1:
                raise ValueError("invalid SuperVINS quaternion")
            row.update({"position": values[0:3], "quaternion_xyzw": values[3:7]})
        rows.append(row)
    return rows


def parse_t_bs_bytes(payload: bytes) -> List[List[float]]:
    match = re.search(r"T_BS:.*?data:\s*\[(.*?)\]", payload.decode("utf-8"), flags=re.DOTALL)
    if not match:
        raise ValueError("T_BS missing")
    values = [float(x) for x in re.split(r"[\s,]+", match.group(1).strip()) if x]
    if len(values) != 16 or not all(math.isfinite(x) for x in values):
        raise ValueError("T_BS must contain 16 finite values")
    return [values[i:i + 4] for i in range(0, 16, 4)]


def support_audit_from_bytes(hf_payload: bytes, sv_payload: bytes, camera_payload: bytes, gt_payload: bytes) -> Dict[str, Any]:
    hf = parse_hf(hf_payload, True)
    sv = parse_sv(sv_payload, True)
    camera = parse_camera(camera_payload)
    gt = parse_gt(gt_payload, True)
    failures: List[str] = []
    if [len(hf), len(sv), len(camera), len(gt)] != [HF_ROWS, SV_ROWS, CAMERA_ROWS, GT_ROWS]:
        failures.append("row_counts")
    for i, row in enumerate(hf):
        camera_index = 945 + i
        if camera_index >= len(camera) or row["timestamp_ns"] != camera[camera_index]["timestamp_ns"]:
            failures.append("hf_camera_binding:{}".format(i))
            break
    signed_hist: Dict[str, int] = {}
    for i, row in enumerate(sv):
        camera_index = 63 + 2 * i
        if camera_index >= len(camera):
            failures.append("sv_camera_range")
            break
        signed = int(row["display_ns"]) - int(camera[camera_index]["timestamp_ns"])
        signed_hist[str(signed)] = signed_hist.get(str(signed), 0) + 1
        if abs(signed) > 1000:
            failures.append("sv_camera_binding:{}".format(i))
            break
    gt_by_ns = {int(row["timestamp_ns"]): int(row["row_index"]) for row in gt}
    common_indices = list(range(COMMON_FIRST, COMMON_LAST + 1, COMMON_STEP))
    common_ns = [int(camera[i]["timestamp_ns"]) for i in common_indices] if len(camera) == CAMERA_ROWS else []
    exact_gt = [value in gt_by_ns for value in common_ns]
    hf_post = len([row for row in hf if int(row["timestamp_ns"]) > COMMON_LAST_NS])
    sv_post = sum(1 for i in range(len(sv)) if 63 + 2 * i > COMMON_LAST)
    rpe_deltas = [common_ns[i + RPE_INDEX_DELTA] - common_ns[i] for i in range(len(common_ns) - RPE_INDEX_DELTA)]
    checks = {
        "common_indices": common_indices == list(range(945, 3660, 2)),
        "common_count": len(common_indices) == COMMON_COUNT,
        "common_endpoints": bool(common_ns) and common_ns[0] == COMMON_FIRST_NS and common_ns[-1] == COMMON_LAST_NS,
        "common_span": bool(common_ns) and common_ns[-1] - common_ns[0] == COMMON_SPAN_NS,
        "exact_gt_join": len(exact_gt) == COMMON_COUNT and all(exact_gt),
        "rpe_pair_count": len(rpe_deltas) == RPE_COUNT,
        "rpe_exact_one_second": len(rpe_deltas) == RPE_COUNT and set(rpe_deltas) == {RPE_DELTA_NS},
        "hf_post_boundary_22": hf_post == 22,
        "sv_post_boundary_11": sv_post == 11,
        "hf_first_delay": camera[945]["timestamp_ns"] - camera[0]["timestamp_ns"] == 47249999872 if len(camera) == CAMERA_ROWS else False,
        "sv_first_delay": camera[63]["timestamp_ns"] - camera[0]["timestamp_ns"] == 3149999872 if len(camera) == CAMERA_ROWS else False,
        "common_after_sv_first": camera[945]["timestamp_ns"] - camera[63]["timestamp_ns"] == 44100000000 if len(camera) == CAMERA_ROWS else False,
        "sv_fixed6_signed_histogram": signed_hist == {"-456": 1086, "544": 724},
    }
    failures.extend(key for key, ok in checks.items() if not ok)
    return {
        "ok": not failures,
        "failures": failures,
        "checks": checks,
        "counts": {"hfnet_rows": len(hf), "supervins_rows": len(sv), "camera_rows": len(camera), "gt_rows": len(gt), "common": len(common_indices), "rpe_pairs": len(rpe_deltas)},
        "common": {"first_camera_row": COMMON_FIRST, "last_camera_row": COMMON_LAST, "step": COMMON_STEP, "first_timestamp_ns": common_ns[0] if common_ns else None, "last_timestamp_ns": common_ns[-1] if common_ns else None, "span_ns": common_ns[-1] - common_ns[0] if common_ns else None},
        "coverage": {"hfnet_full_output_rows": len(hf), "hfnet_input_camera_rows": len(camera), "hfnet_first_final_saved_camera_row": 945, "hfnet_first_final_saved_delay_ns": 47249999872, "supervins_generated_rows": len(sv), "supervins_expected_odd_rows": 1841, "supervins_first_camera_row": 63, "supervins_first_delay_ns": 3149999872, "common_starts_after_supervins_first_ns": 44100000000, "hfnet_post_common_gt_boundary_rows": hf_post, "supervins_post_common_gt_boundary_rows": sv_post},
        "sv_text_minus_source_ns_histogram": signed_hist,
        "scientific_values_parsed": False,
        "alignment_or_error_computed": False,
    }


def declared_identities(value: Any) -> Dict[str, Dict[str, Any]]:
    found: Dict[str, Dict[str, Any]] = {}

    def visit(node: Any) -> None:
        if isinstance(node, dict):
            if {"path", "sha256", "size_bytes"}.issubset(node):
                path = str(Path(str(node["path"])).resolve())
                spec: Dict[str, Any] = {"sha256": str(node["sha256"]), "size_bytes": int(node["size_bytes"])}
                if "required_mode" in node:
                    spec["mode"] = str(node["required_mode"])
                if "required_nlink" in node:
                    spec["nlink"] = int(node["required_nlink"])
                if path in found and found[path] != spec:
                    raise ValueError("conflicting identity declaration for {}".format(path))
                found[path] = spec
            for child in node.values():
                visit(child)
        elif isinstance(node, list):
            for child in node:
                visit(child)

    visit(value)
    return found


def relevant_processes() -> List[Dict[str, Any]]:
    """Read-only scan narrowly scoped to the two generators and their ROS run."""
    patterns = [
        "hfnet_slam_mono_inertial_euroc_headless_v3",
        "published_hfnet_slam_v6/dev_euroc_mh01",
        "SuperVINS/supervins_estimator",
        "published_supervins_v1_official_euroc_mh01_full_trajectory",
        "roscore --port 11555",
        "rosmaster --core -p 11555",
    ]
    found: List[Dict[str, Any]] = []
    own = os.getpid()
    proc = Path("/proc")
    for child in proc.iterdir():
        if not child.name.isdigit() or int(child.name) == own:
            continue
        try:
            cmd = (child / "cmdline").read_bytes().replace(b"\0", b" ").decode("utf-8", "replace").strip()
        except OSError:
            continue
        matched = [pattern for pattern in patterns if pattern in cmd]
        if matched:
            found.append({"pid": int(child.name), "command": cmd, "matched_patterns": matched})
    return found


def direct_child_processes() -> List[Dict[str, Any]]:
    children: List[Dict[str, Any]] = []
    own = os.getpid()
    for child in Path("/proc").iterdir():
        if not child.name.isdigit():
            continue
        try:
            status_text = (child / "status").read_text(encoding="utf-8", errors="replace")
            match = re.search(r"^PPid:\s+(\d+)$", status_text, flags=re.MULTILINE)
            if match and int(match.group(1)) == own:
                cmd = (child / "cmdline").read_bytes().replace(b"\0", b" ").decode("utf-8", "replace")
                children.append({"pid": int(child.name), "command": cmd})
        except OSError:
            continue
    return children


def held_snapshot_open(paths: Sequence[Path], expected: Mapping[str, Mapping[str, Any]]) -> Dict[str, Any]:
    records: Dict[str, Any] = {}
    opened: List[int] = []
    try:
        for path in paths:
            path_text = str(path.resolve())
            if path_text not in expected:
                raise ValueError("snapshot path not pinned: {}".format(path))
            flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
            fd = os.open(str(path), flags)
            opened.append(fd)
            before = os.fstat(fd)
            if not stat.S_ISREG(before.st_mode):
                raise ValueError("snapshot input is not a regular file")
            chunks: List[bytes] = []
            while True:
                block = os.read(fd, 1024 * 1024)
                if not block:
                    break
                chunks.append(block)
            payload = b"".join(chunks)
            after = os.fstat(fd)
            path_info = os.lstat(str(path))
            if not stat.S_ISREG(path_info.st_mode):
                raise ValueError("snapshot path itself is not a regular non-symlink file")
            spec = expected[path_text]
            observed = {
                "sha256": sha256_bytes(payload), "size_bytes": len(payload),
                "mode": format(stat.S_IMODE(after.st_mode), "04o"), "nlink": after.st_nlink,
                "device": after.st_dev, "inode": after.st_ino,
            }
            ok = (
                before.st_dev == after.st_dev == path_info.st_dev
                and before.st_ino == after.st_ino == path_info.st_ino
                and before.st_size == after.st_size == len(payload)
                and observed["sha256"] == spec["sha256"]
                and observed["size_bytes"] == int(spec["size_bytes"])
            )
            if "mode" in spec:
                ok &= observed["mode"] == format(parse_mode(spec["mode"]), "04o")
            if "nlink" in spec:
                ok &= observed["nlink"] == int(spec["nlink"])
            if not ok:
                raise ValueError("held snapshot identity mismatch: {}".format(path))
            records[path_text] = {"fd": fd, "payload": payload, "opened_identity": observed}
        return {"records": records, "requested_paths": [str(path.resolve()) for path in paths], "ok": True}
    except BaseException:
        for fd in opened:
            try:
                os.close(fd)
            except OSError:
                pass
        raise


def held_snapshot_postflight(snapshot: Mapping[str, Any], expected: Mapping[str, Mapping[str, Any]]) -> Dict[str, Any]:
    checks: Dict[str, Any] = {}
    failures: List[str] = []
    records = snapshot.get("records", {})
    requested = snapshot.get("requested_paths")
    if not isinstance(requested, list) or set(records) != set(requested):
        failures.append("snapshot_file_set")
    for path_text, record in records.items():
        try:
            fd = int(record["fd"])
            opened = record["opened_identity"]
            os.lseek(fd, 0, os.SEEK_SET)
            digest = hashlib.sha256()
            total = 0
            while True:
                block = os.read(fd, 1024 * 1024)
                if not block:
                    break
                digest.update(block)
                total += len(block)
            fd_info = os.fstat(fd)
            path = Path(path_text)
            path_flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
            path_fd = os.open(str(path), path_flags)
            try:
                path_fd_before = os.fstat(path_fd)
                path_digest = hashlib.sha256()
                path_total = 0
                while True:
                    block = os.read(path_fd, 1024 * 1024)
                    if not block:
                        break
                    path_digest.update(block)
                    path_total += len(block)
                path_fd_after = os.fstat(path_fd)
                path_info = os.lstat(str(path))
            finally:
                os.close(path_fd)
            path_identity = {"sha256": path_digest.hexdigest(), "size_bytes": path_total,
                             "mode": format(stat.S_IMODE(path_fd_after.st_mode), "04o"), "nlink": path_fd_after.st_nlink}
            spec = expected[path_text]
            ok = (
                digest.hexdigest() == opened["sha256"] == spec["sha256"]
                and total == opened["size_bytes"] == int(spec["size_bytes"])
                and fd_info.st_dev == opened["device"] == path_info.st_dev
                and fd_info.st_ino == opened["inode"] == path_info.st_ino
                and stat.S_ISREG(path_info.st_mode)
                and stat.S_ISREG(path_fd_before.st_mode) and stat.S_ISREG(path_fd_after.st_mode)
                and path_fd_before.st_dev == path_fd_after.st_dev == path_info.st_dev
                and path_fd_before.st_ino == path_fd_after.st_ino == path_info.st_ino
                and path_identity["sha256"] == spec["sha256"]
                and path_identity["size_bytes"] == int(spec["size_bytes"])
            )
            if "mode" in spec:
                ok &= path_identity["mode"] == format(parse_mode(spec["mode"]), "04o")
            if "nlink" in spec:
                ok &= path_identity["nlink"] == int(spec["nlink"])
            observed = {"descriptor_sha256": digest.hexdigest(), "descriptor_size_bytes": total,
                        "descriptor_device": fd_info.st_dev, "descriptor_inode": fd_info.st_ino,
                        "path_identity": path_identity, "path_device": path_info.st_dev, "path_inode": path_info.st_ino}
            error = None
        except Exception as exc:
            ok = False
            observed = None
            error = "{}: {}".format(type(exc).__name__, exc)
        checks[path_text] = {"ok": bool(ok), "observed": observed, "error": error}
        if not ok:
            failures.append(path_text)
    return {"ok": not failures, "failures": failures, "checks": checks,
            "requested_paths": requested, "observed_paths": sorted(records)}


def close_held_snapshot(snapshot: Optional[Mapping[str, Any]]) -> None:
    if not snapshot:
        return
    for record in snapshot.get("records", {}).values():
        try:
            os.close(int(record["fd"]))
        except OSError:
            pass


def authority_audit(lock: Mapping[str, Any]) -> Dict[str, Any]:
    if not AUTHORITY.exists():
        return {"present": False, "valid": False, "sealed": False, "failures": ["authority_absent"]}
    failures: List[str] = []
    try:
        authority = load_json(AUTHORITY)
        expected = {
            "schema_version": AUTHORITY_SCHEMA,
            "status": "AUTHORIZED_EXACTLY_ONE_PURE_COMMON_SUPPORT_EVALUATION_ATTEMPT_001_START",
            "authorization_token_sha256": TOKEN_SHA256,
            "controller_command": CONTROLLER_COMMAND,
            "fresh_evidence_root": str(EVIDENCE_ROOT),
            "attempt": "attempt_001",
            "maximum_evaluator_starts": 1,
            "retry_authorized": False,
            "root_confirmation": "ROOT_CONFIRMED_STAGE6_EXACTLY_ONE_PURE_COMMON_SUPPORT_EVALUATION",
            "claim_boundary": {
                "pure_existing_artifact_computation_only": True,
                "model_ros_publisher_or_trajectory_generation_authorized": False,
                "cross_system_metric_contrast_authorized": False,
                "performance_ordering_authorized": False,
                "inferential_statistics_authorized": False,
                "next_stage_automatically_authorized": False
            },
        }
        for key, value in expected.items():
            if authority.get(key) != value:
                failures.append(key)
        identities = {"lock": LOCK, "protocol": FREEZE, "runner": RUNNER, "tests": TESTS, "test_receipt": TEST_RECEIPT}
        for key, path in identities.items():
            if authority.get(key) != file_identity(path):
                failures.append(key)
        if not verify_sealed(AUTHORITY):
            failures.append("seal")
    except Exception as exc:
        authority = None
        failures.append("{}: {}".format(type(exc).__name__, exc))
    return {"present": True, "valid": not failures, "sealed": verify_sealed(AUTHORITY), "failures": failures,
            "identity": file_identity(AUTHORITY, include_seal=True) if AUTHORITY.exists() else None}


def collect_prestart(require_authority: bool = False) -> Dict[str, Any]:
    failures: List[str] = []
    checks: Dict[str, Any] = {}
    freeze: Dict[str, Any] = {}
    lock: Dict[str, Any] = {}
    pin_audit: Dict[str, Any] = {"ok": False, "checks": {}, "failures": ["lock_unavailable"]}
    support: Dict[str, Any] = {"ok": False, "failures": ["not_run"]}
    try:
        freeze = load_json(FREEZE)
        checks["freeze_schema"] = freeze.get("schema_version") == FREEZE_SCHEMA
        checks["freeze_status"] = freeze.get("status") == "FROZEN_DEVELOPMENT_ONLY_AWAITING_EXECUTION_LOCK_AND_AUTHORITY"
        checks["freeze_sealed"] = verify_sealed(FREEZE)
    except Exception as exc:
        checks["freeze_load"] = False
        failures.append("freeze_load:{}".format(exc))
    try:
        lock = load_json(LOCK)
        checks["lock_schema"] = lock.get("schema_version") == LOCK_SCHEMA
        checks["lock_status"] = lock.get("status") == "LOCKED_PRESTART_AWAITING_SEPARATE_ROOT_EXECUTION_AUTHORITY"
        checks["lock_sealed"] = verify_sealed(LOCK)
        checks["lock_protocol"] = lock.get("protocol") == file_identity(FREEZE)
        checks["lock_runner"] = lock.get("runner") == file_identity(RUNNER)
        checks["lock_tests"] = lock.get("tests", {}).get("identity") == file_identity(TESTS)
        checks["lock_test_receipt"] = lock.get("tests", {}).get("test_receipt") == file_identity(TEST_RECEIPT)
        checks["lock_command"] = lock.get("controller_command") == CONTROLLER_COMMAND
        checks["lock_token"] = lock.get("authorization_token_sha256") == TOKEN_SHA256
        checks["lock_root"] = lock.get("fresh_evidence_root") == str(EVIDENCE_ROOT)
        checks["lock_one_shot"] = lock.get("maximum_evaluator_starts") == 1 and lock.get("retry_authorized") is False
        pins = lock.get("pinned_files", {})
        checks["pin_count"] = lock.get("pinned_file_count") == len(pins)
        checks["pin_digest"] = lock.get("pinned_files_canonical_sha256") == canonical_pin_digest(pins)
        pin_audit = inspect_pins(pins)
        checks["all_pins"] = pin_audit["ok"]
        frozen = declared_identities(freeze)
        checks["frozen_pins_are_locked"] = all(
            path in pins and pins[path]["sha256"] == spec["sha256"] and int(pins[path]["size_bytes"]) == int(spec["size_bytes"])
            and ("mode" not in spec or format(parse_mode(pins[path].get("mode", "0")), "04o") == format(parse_mode(spec["mode"]), "04o"))
            and ("nlink" not in spec or int(pins[path].get("nlink", -1)) == int(spec["nlink"]))
            for path, spec in frozen.items()
        )
        prestart_snapshot = held_snapshot_open(SNAPSHOT_PATHS, pins)
        try:
            payloads = prestart_snapshot["records"]
            get_payload = lambda path: payloads[str(path.resolve())]["payload"]
            support = support_audit_from_bytes(get_payload(HF_TRAJECTORY), get_payload(SV_TRAJECTORY), get_payload(CAMERA_CSV), get_payload(GT_CSV))
            checks["timestamp_support"] = support["ok"]
            held_post = held_snapshot_postflight(prestart_snapshot, pins)
            checks["timestamp_snapshot_held_fd_stable"] = held_post["ok"]
        finally:
            close_held_snapshot(prestart_snapshot)
        identity = [[1.0, 0.0, 0.0, 0.0], [0.0, 1.0, 0.0, 0.0], [0.0, 0.0, 1.0, 0.0], [0.0, 0.0, 0.0, 1.0]]
        checks["gt_T_BS_identity"] = parse_t_bs_bytes(get_payload(GT_SENSOR)) == identity
        checks["imu_T_BS_identity"] = parse_t_bs_bytes(get_payload(IMU_SENSOR)) == identity
        pin_audit_after_timestamp = inspect_pins(pins)
        checks["all_pins_after_timestamp_audit"] = pin_audit_after_timestamp["ok"]
    except Exception as exc:
        checks["lock_or_timestamp_audit"] = False
        failures.append("lock_or_timestamp_audit:{}:{}".format(type(exc).__name__, exc))
    checks["fresh_root_absent"] = not EVIDENCE_ROOT.exists()
    checks["start_claim_absent"] = not START_CLAIM.exists()
    processes = relevant_processes()
    checks["relevant_generators_absent"] = not processes
    authority = authority_audit(lock)
    checks["authority_state"] = authority["valid"] if require_authority else not authority["present"]
    for key, ok in checks.items():
        if not ok and key not in {"freeze_load", "lock_or_timestamp_audit"}:
            failures.append(key)
    ready = not failures
    if ready and require_authority:
        status = "GO_EXACTLY_ONE_PURE_COMMON_SUPPORT_EVALUATION_START"
    elif ready:
        status = "GO_AWAITING_SEPARATE_ROOT_AUTHORITY_FOR_EXACTLY_ONE_PURE_COMMON_SUPPORT_EVALUATION"
    else:
        status = "NO_GO"
    return {
        "schema_version": "aqua-fe-hfnet-supervins-common-support-prestart-v1",
        "checked_at": now_iso(), "status": status, "ready": ready,
        "failures": failures, "check_count": len(checks), "checks": checks,
        "timestamp_only_support_audit": support, "pin_snapshot": pin_audit,
        "authority": authority, "relevant_processes": processes,
        "scientific_computation_run": False,
        "boundary": {"positions_parsed": False, "alignment_computed": False, "ape_computed": False,
                     "rpe_computed": False, "subprocess_spawned": False, "ros_or_model_started": False},
    }


def extract_common_positions(snapshot: Mapping[str, Any]) -> Dict[str, Any]:
    records = snapshot["records"]
    payload = lambda path: records[str(path.resolve())]["payload"]
    hf = parse_hf(payload(HF_TRAJECTORY), False)
    sv = parse_sv(payload(SV_TRAJECTORY), False)
    camera = parse_camera(payload(CAMERA_CSV))
    gt = parse_gt(payload(GT_CSV), False)
    gt_by_ns = {int(row["timestamp_ns"]): row for row in gt}
    if len(gt_by_ns) != GT_ROWS:
        raise ValueError("GT timestamps are not unique")
    rows: List[Dict[str, Any]] = []
    for common_row, camera_index in enumerate(range(COMMON_FIRST, COMMON_LAST + 1, COMMON_STEP)):
        source_ns = int(camera[camera_index]["timestamp_ns"])
        hf_row = hf[camera_index - 945]
        sv_index = (camera_index - 63) // 2
        sv_row = sv[sv_index]
        if int(hf_row["timestamp_ns"]) != source_ns:
            raise ValueError("HFNet common timestamp mismatch")
        if abs(int(sv_row["display_ns"]) - source_ns) > 1000:
            raise ValueError("SuperVINS common timestamp mismatch")
        if source_ns not in gt_by_ns:
            raise ValueError("common camera timestamp absent from GT")
        gt_row = gt_by_ns[source_ns]
        rows.append({
            "common_row_index": common_row, "camera_row_index": camera_index,
            "source_timestamp_ns": source_ns, "gt_row_index": int(gt_row["row_index"]),
            "gt_position": gt_row["position"], "hfnet_position": hf_row["position"],
            "supervins_position": sv_row["position"],
        })
    if len(rows) != COMMON_COUNT:
        raise ValueError("common support count mismatch")
    pairs = [{
        "pair_row_index": i, "left_common_index": i, "right_common_index": i + RPE_INDEX_DELTA,
        "left_camera_row_index": rows[i]["camera_row_index"],
        "right_camera_row_index": rows[i + RPE_INDEX_DELTA]["camera_row_index"],
        "left_timestamp_ns": rows[i]["source_timestamp_ns"],
        "right_timestamp_ns": rows[i + RPE_INDEX_DELTA]["source_timestamp_ns"],
        "delta_ns": rows[i + RPE_INDEX_DELTA]["source_timestamp_ns"] - rows[i]["source_timestamp_ns"],
        "left_association_index": i, "right_association_index": i + RPE_INDEX_DELTA,
    } for i in range(COMMON_COUNT - RPE_INDEX_DELTA)]
    if len(pairs) != RPE_COUNT or any(row["delta_ns"] != RPE_DELTA_NS for row in pairs):
        raise ValueError("exact one-second pair contract failed")
    arrays = body_position_arrays(rows)
    return {"rows": rows, "pairs": pairs, **arrays}


def body_position_arrays(rows: Sequence[Mapping[str, Any]]) -> Dict[str, np.ndarray]:
    """Return direct world_T_body translations; no camera extrinsic is accepted."""
    arrays = {
        "gt": np.asarray([row["gt_position"] for row in rows], dtype=float),
        "hfnet": np.asarray([row["hfnet_position"] for row in rows], dtype=float),
        "supervins": np.asarray([row["supervins_position"] for row in rows], dtype=float),
    }
    if any(value.shape != (len(rows), 3) or not np.all(np.isfinite(value)) for value in arrays.values()):
        raise ValueError("common world_T_body position arrays must be finite Nx3")
    return arrays


def evaluate_common_systems(common: Mapping[str, Any]) -> Dict[str, Any]:
    """Gate the exact common support, then call two independent fits."""
    rows = common.get("rows", [])
    pairs = common.get("pairs", [])
    if len(rows) != COMMON_COUNT or len(pairs) != RPE_COUNT:
        raise ValueError("only the frozen 1358/1348 common support is accepted")
    expected_camera = list(range(COMMON_FIRST, COMMON_LAST + 1, COMMON_STEP))
    if [int(row["camera_row_index"]) for row in rows] != expected_camera:
        raise ValueError("common camera support is not exact")
    expected_ns = [COMMON_FIRST_NS + index * 100_000_000 for index in range(COMMON_COUNT)]
    if [int(row["source_timestamp_ns"]) for row in rows] != expected_ns:
        raise ValueError("common timestamps are not the frozen exact sequence")
    for index, pair in enumerate(pairs):
        if not (
            int(pair["left_association_index"]) == index
            and int(pair["right_association_index"]) == index + RPE_INDEX_DELTA
            and int(pair["left_camera_row_index"]) == expected_camera[index]
            and int(pair["right_camera_row_index"]) == expected_camera[index + RPE_INDEX_DELTA]
            and int(pair["left_timestamp_ns"]) == expected_ns[index]
            and int(pair["right_timestamp_ns"]) == expected_ns[index + RPE_INDEX_DELTA]
            and int(pair["delta_ns"]) == RPE_DELTA_NS
        ):
            raise ValueError("common RPE pair support is not exact")
    arrays = {key: np.asarray(common[key], dtype=float) for key in ("gt", "hfnet", "supervins")}
    if any(value.shape != (COMMON_COUNT, 3) or not np.all(np.isfinite(value)) for value in arrays.values()):
        raise ValueError("only exact finite 1358x3 body-position arrays are accepted")
    hf_eval = evaluate_one_system(arrays["hfnet"], arrays["gt"], pairs)
    sv_eval = evaluate_one_system(arrays["supervins"], arrays["gt"], pairs)
    return {"hfnet": hf_eval, "supervins": sv_eval, "gt": arrays["gt"],
            "hfnet_source": arrays["hfnet"], "supervins_source": arrays["supervins"]}


def evaluate_one_system(source: np.ndarray, gt: np.ndarray, pairs: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    se3 = rigid_se3_alignment(source, gt)
    se3_audit = alignment_audit(se3)
    if not se3_audit["proper"] or se3_audit["scale"] != 1.0:
        raise ValueError("fixed-scale alignment is not proper SE3")
    core_aligned = STAGE5.core_align_se3_positions(source, gt)
    crosscheck = float(np.max(np.abs(core_aligned - se3["aligned"])))
    if not math.isfinite(crosscheck) or crosscheck > 1e-12:
        raise ValueError("frozen core SE3 coordinate crosscheck failed")
    sim3 = proper_umeyama_sim3(source, gt)
    sim3_audit = alignment_audit(sim3)
    if not sim3_audit["proper"] or not math.isfinite(float(sim3_audit["scale"])) or float(sim3_audit["scale"]) <= 0.0:
        raise ValueError("proper positive-scale Sim3 gate failed")
    se3_ape, se3_rpe = metric_samples(gt, se3["aligned"], pairs)
    sim3_ape, sim3_rpe = metric_samples(gt, sim3["aligned"], pairs)
    return {
        "se3": se3, "sim3": sim3,
        "alignment_audit": {
            "primary_fixed_scale_se3": dict(se3_audit, core_crosscheck_max_abs_m=crosscheck),
            "secondary_sim3_scale_diagnostic": sim3_audit,
        },
        "samples": {"se3_ape": se3_ape, "se3_rpe": se3_rpe, "sim3_ape": sim3_ape, "sim3_rpe": sim3_rpe},
        "metrics": {
            "primary_fixed_scale_se3": {"scale": 1.0, "ape": descriptive_stats(se3_ape), "rpe_1s": descriptive_stats(se3_rpe)},
            "secondary_sim3_scale_diagnostic": {"scale": float(sim3_audit["scale"]), "ape": descriptive_stats(sim3_ape), "rpe_1s": descriptive_stats(sim3_rpe), "may_replace_primary": False, "may_enter_cross_system_ordering": False},
        },
    }


def metrics_finite_nonnegative(metrics: Mapping[str, Any]) -> bool:
    numeric = {"rmse_m", "mean_m", "population_std_m", "median_m", "min_m", "p90_m", "p95_m", "max_m", "sse_m2"}
    try:
        for system in ("hfnet", "supervins"):
            for alignment_key in ("primary_fixed_scale_se3", "secondary_sim3_scale_diagnostic"):
                for metric_key, count in (("ape", COMMON_COUNT), ("rpe_1s", RPE_COUNT)):
                    row = metrics["systems"][system][alignment_key][metric_key]
                    if set(row) != numeric | {"n"} or int(row["n"]) != count:
                        return False
                    if any(not math.isfinite(float(row[key])) or float(row[key]) < 0.0 for key in numeric):
                        return False
            if metrics["systems"][system]["primary_fixed_scale_se3"]["scale"] != 1.0:
                return False
            scale = float(metrics["systems"][system]["secondary_sim3_scale_diagnostic"]["scale"])
            if not math.isfinite(scale) or scale <= 0.0:
                return False
        return True
    except (KeyError, TypeError, ValueError, OverflowError):
        return False


def number_text(value: float) -> str:
    return format(float(value), ".17g")


def csv_text(header: Sequence[str], rows: Iterable[Sequence[Any]]) -> str:
    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(header)
    writer.writerows(rows)
    return buffer.getvalue()


def tick_text(value: float) -> str:
    return format(float(value), ".4g")


def map_point(xvalue: float, yvalue: float, domain: Mapping[str, float], x0: float, y0: float, width: float, height: float) -> Tuple[float, float]:
    return (x0 + (xvalue - domain["xmin"]) / (domain["xmax"] - domain["xmin"]) * width,
            y0 + height - (yvalue - domain["ymin"]) / (domain["ymax"] - domain["ymin"]) * height)


def panel_svg(series: Sequence[Tuple[Sequence[float], Sequence[float], str, str, str]], domain: Mapping[str, float],
              x0: float, y0: float, width: float, height: float, xlabel: str, ylabel: str,
              label: str) -> Tuple[str, Dict[str, Any]]:
    parts = ['<rect x="{:.2f}" y="{:.2f}" width="{:.2f}" height="{:.2f}" fill="white" stroke="#555"/>'.format(x0, y0, width, height),
             '<text x="{:.2f}" y="{:.2f}" font-size="17" font-weight="bold">{}</text>'.format(x0 + 8, y0 + 23, html.escape(label))]
    vertical: List[Dict[str, float]] = []
    horizontal: List[Dict[str, float]] = []
    for tick in range(5):
        alpha = tick / 4.0
        px = x0 + alpha * width
        py = y0 + height - alpha * height
        xv = domain["xmin"] + alpha * (domain["xmax"] - domain["xmin"])
        yv = domain["ymin"] + alpha * (domain["ymax"] - domain["ymin"])
        v = {"x1": px, "y1": y0, "x2": px, "y2": y0 + height}
        h = {"x1": x0, "y1": py, "x2": x0 + width, "y2": py}
        vertical.append(v); horizontal.append(h)
        parts.append('<line class="grid-v" x1="{x1:.2f}" y1="{y1:.2f}" x2="{x2:.2f}" y2="{y2:.2f}" stroke="#e1e1e1"/>'.format(**v))
        parts.append('<line class="grid-h" x1="{x1:.2f}" y1="{y1:.2f}" x2="{x2:.2f}" y2="{y2:.2f}" stroke="#e1e1e1"/>'.format(**h))
        parts.append('<text x="{:.2f}" y="{:.2f}" font-size="11" text-anchor="middle">{}</text>'.format(px, y0 + height + 19, tick_text(xv)))
        parts.append('<text x="{:.2f}" y="{:.2f}" font-size="11" text-anchor="end">{}</text>'.format(x0 - 7, py + 4, tick_text(yv)))
    for xvalues, yvalues, colour, name, dash in series:
        points = " ".join("{:.2f},{:.2f}".format(*map_point(float(x), float(y), domain, x0, y0, width, height)) for x, y in zip(xvalues, yvalues))
        dash_attr = ' stroke-dasharray="{}"'.format(dash) if dash else ""
        parts.append('<polyline fill="none" stroke="{}" stroke-width="1.7"{} vector-effect="non-scaling-stroke" points="{}"/>'.format(colour, dash_attr, points))
    parts.append('<text x="{:.2f}" y="{:.2f}" font-size="13" text-anchor="middle">{}</text>'.format(x0 + width / 2, y0 + height + 44, html.escape(xlabel)))
    parts.append('<text x="{:.2f}" y="{:.2f}" font-size="13" text-anchor="middle" transform="rotate(-90 {:.2f} {:.2f})">{}</text>'.format(x0 - 58, y0 + height / 2, x0 - 58, y0 + height / 2, html.escape(ylabel)))
    legend_x, legend_y = x0 + width - 170, y0 + 18
    for index, (_x, _y, colour, name, dash) in enumerate(series):
        yy = legend_y + index * 19
        dash_attr = ' stroke-dasharray="{}"'.format(dash) if dash else ""
        parts.append('<line x1="{:.2f}" y1="{:.2f}" x2="{:.2f}" y2="{:.2f}" stroke="{}" stroke-width="2"{}/>'.format(legend_x, yy, legend_x + 27, yy, colour, dash_attr))
        parts.append('<text x="{:.2f}" y="{:.2f}" font-size="10.5">{}</text>'.format(legend_x + 33, yy + 4, html.escape(name)))
    audit = {"vertical_gridlines": vertical, "horizontal_gridlines": horizontal,
             "vertical_coordinates_valid": all(v["x1"] == v["x2"] and v["y1"] == y0 and v["y2"] == y0 + height for v in vertical),
             "horizontal_coordinates_valid": all(h["y1"] == h["y2"] and h["x1"] == x0 and h["x2"] == x0 + width for h in horizontal)}
    return "\n".join(parts), audit


def trajectory_figure(gt: np.ndarray, hf: np.ndarray, sv: np.ndarray) -> Tuple[str, Dict[str, Any]]:
    all_x = np.concatenate((gt[:, 0], hf[:, 0], sv[:, 0]))
    all_y = np.concatenate((gt[:, 1], hf[:, 1], sv[:, 1]))
    all_z = np.concatenate((gt[:, 2], hf[:, 2], sv[:, 2]))
    extent = max(float(np.ptp(all_x)), float(np.ptp(all_y)), float(np.ptp(all_z))) * 1.12
    if not math.isfinite(extent) or extent <= 0.0:
        raise ValueError("invalid trajectory plotting extent")
    def domain(a: np.ndarray, b: np.ndarray) -> Dict[str, float]:
        ac, bc = 0.5 * (float(np.min(a)) + float(np.max(a))), 0.5 * (float(np.min(b)) + float(np.max(b)))
        return {"xmin": ac - extent / 2, "xmax": ac + extent / 2, "ymin": bc - extent / 2, "ymax": bc + extent / 2}
    xy = domain(all_x, all_y); xz = domain(all_x, all_z)
    width = height = 440.0
    common_series_xy = [(gt[:, 0], gt[:, 1], "#000000", "Official GT", ""), (hf[:, 0], hf[:, 1], "#0072B2", "HFNet", ""), (sv[:, 0], sv[:, 1], "#D55E00", "SuperVINS", "6 3")]
    common_series_xz = [(gt[:, 0], gt[:, 2], "#000000", "Official GT", ""), (hf[:, 0], hf[:, 2], "#0072B2", "HFNet", ""), (sv[:, 0], sv[:, 2], "#D55E00", "SuperVINS", "6 3")]
    p1, g1 = panel_svg(common_series_xy, xy, 100, 70, width, height, "x (m)", "y (m)", "(a) XY primary alignment")
    p2, g2 = panel_svg(common_series_xz, xz, 700, 70, width, height, "x (m)", "z (m)", "(b) XZ primary alignment")
    mpp = extent / width
    audit = {"shared_comparison_extent_m": extent, "shared_metres_per_pixel": mpp,
             "xy_domain": xy, "xz_domain": xz,
             "xy_x_metres_per_pixel": (xy["xmax"] - xy["xmin"]) / width,
             "xy_y_metres_per_pixel": (xy["ymax"] - xy["ymin"]) / height,
             "xz_x_metres_per_pixel": (xz["xmax"] - xz["xmin"]) / width,
             "xz_z_metres_per_pixel": (xz["ymax"] - xz["ymin"]) / height,
             "gridline_audits": [g1, g2]}
    audit["equal_metric_aspect_all_axes"] = max(abs(audit[k] - mpp) for k in ("xy_x_metres_per_pixel", "xy_y_metres_per_pixel", "xz_x_metres_per_pixel", "xz_z_metres_per_pixel")) <= 1e-15
    audit["gridline_coordinates_valid"] = all(g["vertical_coordinates_valid"] and g["horizontal_coordinates_valid"] for g in audit["gridline_audits"])
    if not audit["equal_metric_aspect_all_axes"] or not audit["gridline_coordinates_valid"]:
        raise ValueError("trajectory figure geometry audit failed")
    metadata = html.escape(json.dumps(audit, sort_keys=True, separators=(",", ":"), allow_nan=False), quote=False)
    svg = '<svg xmlns="http://www.w3.org/2000/svg" width="1240" height="590" viewBox="0 0 1240 590" font-family="Arial, Helvetica, sans-serif">\n<title>MH01 exact-common-support primary trajectory overlay</title>\n<desc>Both systems are independently fixed-scale SE3 aligned on the identical 1358-pose support. Panels share one metric scale.</desc>\n<metadata id="geometry-audit">{}</metadata>\n<rect width="100%" height="100%" fill="white"/>\n{}\n{}\n</svg>\n'.format(metadata, p1, p2)
    return svg, audit


def error_figure(t_ape: np.ndarray, hf_ape: np.ndarray, sv_ape: np.ndarray, t_rpe: np.ndarray,
                 hf_rpe: np.ndarray, sv_rpe: np.ndarray) -> Tuple[str, Dict[str, Any]]:
    def domain(x: np.ndarray, a: np.ndarray, b: np.ndarray) -> Dict[str, float]:
        ymax = max(float(np.max(a)), float(np.max(b))) * 1.08
        xmax = float(np.max(x)) * 1.02
        return {"xmin": 0.0, "xmax": xmax if xmax > 0 else 1.0, "ymin": 0.0, "ymax": ymax if ymax > 0 else 1.0}
    ape_domain = domain(t_ape, hf_ape, sv_ape); rpe_domain = domain(t_rpe, hf_rpe, sv_rpe)
    ape_series = [(t_ape, hf_ape, "#0072B2", "HFNet", ""), (t_ape, sv_ape, "#D55E00", "SuperVINS", "6 3")]
    rpe_series = [(t_rpe, hf_rpe, "#0072B2", "HFNet", ""), (t_rpe, sv_rpe, "#D55E00", "SuperVINS", "6 3")]
    p1, g1 = panel_svg(ape_series, ape_domain, 100, 70, 440, 400, "time since common start (s)", "error (m)", "(a) Primary translation APE")
    p2, g2 = panel_svg(rpe_series, rpe_domain, 700, 70, 440, 400, "pair-end time since common start (s)", "error (m)", "(b) Primary 1 s translation RPE")
    audit = {"ape_domain": ape_domain, "rpe_domain": rpe_domain,
             "all_axis_lower_bounds_exact_zero": all(d[axis] == 0.0 for d in (ape_domain, rpe_domain) for axis in ("xmin", "ymin")),
             "all_source_values_nonnegative": min(float(np.min(t_ape)), float(np.min(t_rpe)), float(np.min(hf_ape)), float(np.min(sv_ape)), float(np.min(hf_rpe)), float(np.min(sv_rpe))) >= 0.0,
             "gridline_audits": [g1, g2], "gridline_coordinates_valid": all(g["vertical_coordinates_valid"] and g["horizontal_coordinates_valid"] for g in (g1, g2))}
    if not all((audit["all_axis_lower_bounds_exact_zero"], audit["all_source_values_nonnegative"], audit["gridline_coordinates_valid"])):
        raise ValueError("error figure geometry audit failed")
    metadata = html.escape(json.dumps(audit, sort_keys=True, separators=(",", ":"), allow_nan=False), quote=False)
    svg = '<svg xmlns="http://www.w3.org/2000/svg" width="1240" height="550" viewBox="0 0 1240 550" font-family="Arial, Helvetica, sans-serif">\n<title>MH01 exact-common-support primary error traces</title>\n<desc>Both systems use identical support; all displayed time and error axes start at zero.</desc>\n<metadata id="geometry-audit">{}</metadata>\n<rect width="100%" height="100%" fill="white"/>\n{}\n{}\n</svg>\n'.format(metadata, p1, p2)
    return svg, audit


def comparison_table(metrics: Mapping[str, Any]) -> str:
    lines = ["| Artifact | Alignment | Metric | n | RMSE (m) | Mean (m) | Median (m) | P95 (m) | Max (m) |",
             "|---|---|---:|---:|---:|---:|---:|---:|---:|"]
    for system, label in (("hfnet", "HFNet"), ("supervins", "SuperVINS")):
        for alignment_key, alignment_label in (("primary_fixed_scale_se3", "fixed-scale SE(3) primary"), ("secondary_sim3_scale_diagnostic", "Sim(3) diagnostic")):
            for metric_key, metric_label in (("ape", "APE"), ("rpe_1s", "RPE 1 s")):
                row = metrics["systems"][system][alignment_key][metric_key]
                lines.append("| {} | {} | {} | {} | `{}` | `{}` | `{}` | `{}` | `{}` |".format(label, alignment_label, metric_label, row["n"], number_text(row["rmse_m"]), number_text(row["mean_m"]), number_text(row["median_m"]), number_text(row["p95_m"]), number_text(row["max_m"])))
    return "\n".join(lines)


def full_statistics_table(metrics: Mapping[str, Any]) -> str:
    lines = ["| Artifact | Alignment | Metric | n | RMSE | Mean | Pop. std | Median | Min | P90 | P95 | Max | SSE (m²) |",
             "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for system, label in (("hfnet", "HFNet"), ("supervins", "SuperVINS")):
        for alignment_key, alignment_label in (("primary_fixed_scale_se3", "fixed-scale SE(3) primary"), ("secondary_sim3_scale_diagnostic", "Sim(3) diagnostic")):
            for metric_key, metric_label in (("ape", "APE"), ("rpe_1s", "RPE 1 s")):
                row = metrics["systems"][system][alignment_key][metric_key]
                values = [row[k] for k in ("rmse_m", "mean_m", "population_std_m", "median_m", "min_m", "p90_m", "p95_m", "max_m", "sse_m2")]
                lines.append("| {} | {} | {} | {} | {} |".format(label, alignment_label, metric_label, row["n"], " | ".join("`{}`".format(number_text(x)) for x in values)))
    return "\n".join(lines)


def validate_report_boundary(texts: Sequence[str]) -> Dict[str, Any]:
    joined = "\n".join(texts).lower()
    found = [token for token in FORBIDDEN_REPORT_TOKENS if token in joined]
    return {"ok": not found, "forbidden_tokens_found": found}


def validate_metrics_contrast_schema(value: Any) -> Dict[str, Any]:
    forbidden_key_fragments = ("difference", "delta", "ratio", "percent", "winner", "better", "outperform", "superior", "rank", "best", "p_value", "pvalue", "confidence_interval", "effect_size", "improvement")
    found: List[str] = []
    shape_failures: List[str] = []
    def visit(node: Any, path: str) -> None:
        if isinstance(node, dict):
            for key, child in node.items():
                lowered = str(key).lower()
                if any(fragment in lowered for fragment in forbidden_key_fragments):
                    found.append(path + "." + str(key))
                visit(child, path + "." + str(key))
        elif isinstance(node, list):
            for index, child in enumerate(node):
                visit(child, path + "[{}]".format(index))
    visit(value, "metrics")
    expected_top = {"schema_version", "support", "systems", "coverage_context", "artifact_semantics", "statistical_boundary"}
    if not isinstance(value, dict) or set(value) != expected_top:
        shape_failures.append("top_level_exact_allowlist")
    systems = value.get("systems", {}) if isinstance(value, dict) else {}
    if not isinstance(systems, dict) or set(systems) != {"hfnet", "supervins"}:
        shape_failures.append("systems_exact_allowlist")
    else:
        for system, document in systems.items():
            if set(document) != {"primary_fixed_scale_se3", "secondary_sim3_scale_diagnostic"}:
                shape_failures.append(system + ":alignment_exact_allowlist")
                continue
            if set(document["primary_fixed_scale_se3"]) != {"scale", "ape", "rpe_1s"}:
                shape_failures.append(system + ":primary_exact_allowlist")
            if set(document["secondary_sim3_scale_diagnostic"]) != {"scale", "ape", "rpe_1s", "may_replace_primary", "may_enter_cross_system_ordering"}:
                shape_failures.append(system + ":secondary_exact_allowlist")
    boundary = value.get("statistical_boundary", {}) if isinstance(value, dict) else {}
    if boundary.get("cross_system_metric_contrast_computed") is not False or boundary.get("cross_system_performance_ordering_authorized") is not False:
        shape_failures.append("boundary_false_gates")
    return {"ok": not found and not shape_failures, "forbidden_contrast_fields": found,
            "schema_shape_failures": shape_failures}


def public_snapshot_audit(snapshot: Mapping[str, Any]) -> Dict[str, Any]:
    return {path: {"opened_identity": dict(record["opened_identity"]), "payload_used_from_held_descriptor": True}
            for path, record in sorted(snapshot["records"].items())}


def build_metrics_document(timestamp_support: Mapping[str, Any], hf_eval: Mapping[str, Any], sv_eval: Mapping[str, Any]) -> Dict[str, Any]:
    """Build the exact allowlisted document; no cross-system metric operation occurs."""
    return {
        "schema_version": "aqua-fe-hfnet-supervins-common-support-metrics-v1",
        "support": {
            "sequence": "official EuRoC MH_01_easy",
            "camera_row_indices": "945..3659 inclusive, step 2",
            "first_camera_row_index": COMMON_FIRST, "last_camera_row_index": COMMON_LAST,
            "pose_count_per_system": COMMON_COUNT, "span_ns": COMMON_SPAN_NS, "span_s": 135.7,
            "rpe_pair_count_per_system": RPE_COUNT, "rpe_pair_index_step": RPE_INDEX_DELTA,
            "rpe_pair_camera_row_step": RPE_CAMERA_DELTA, "rpe_pair_time_ns": RPE_DELTA_NS,
        },
        "systems": {"hfnet": hf_eval["metrics"], "supervins": sv_eval["metrics"]},
        "coverage_context": timestamp_support["coverage"],
        "artifact_semantics": {
            "hfnet": "final-map reconstructed largest-map world_T_body trajectory with lost frames skipped",
            "supervins": "online-published world_T_body estimator-state trajectory",
            "common_window_excludes_hfnet_failed_reset_lost_prefix": True,
        },
        "statistical_boundary": {
            "run_count_per_system": 1, "descriptive_only": True,
            "inferential_statistics_computed": False, "cross_system_metric_contrast_computed": False,
            "cross_system_performance_ordering_authorized": False,
        },
    }


def generate_analysis_bundle(snapshot: Mapping[str, Any], timestamp_support: Mapping[str, Any]) -> Dict[str, Any]:
    common = extract_common_positions(snapshot)
    common_evaluation = evaluate_common_systems(common)
    gt = common_evaluation["gt"]
    hf_eval = common_evaluation["hfnet"]
    sv_eval = common_evaluation["supervins"]
    metrics = build_metrics_document(timestamp_support, hf_eval, sv_eval)
    if not metrics_finite_nonnegative(metrics):
        raise ValueError("metric schema/finite/count audit failed")

    alignment_json = {
        "schema_version": "aqua-fe-hfnet-supervins-common-support-alignment-v1",
        "same_support_for_both_systems": True,
        "shared_transform_used": False,
        "fit_on_full_system_support": False,
        "hfnet": hf_eval["alignment_audit"], "supervins": sv_eval["alignment_audit"],
        "body_frame_contract": "estimate world_T_body to official GT world_T_body; both T_BS identity; no camera extrinsic",
        "primary": "independent proper fixed-scale SE(3) per system",
        "secondary": "independent proper positive-scale Sim(3) per system; diagnostic only",
    }
    support_audit = {
        "schema_version": "aqua-fe-hfnet-supervins-common-support-audit-v1",
        "prestart_timestamp_only_audit": dict(timestamp_support),
        "counts": dict(timestamp_support["counts"]),
        "coverage": dict(timestamp_support["coverage"]),
        "common": dict(timestamp_support["common"]),
        "position_parse_occurred_only_after_authorized_start": True,
        "identical_pose_support_used_by_both_systems": True,
        "gt_join_error_ns": 0,
        "interpolation_or_extrapolation_used": False,
        "common_window_excludes_hfnet_failure_reset_lost_prefix": True,
    }
    input_audit = {
        "schema_version": "aqua-fe-hfnet-supervins-common-support-input-audit-v1",
        "held_descriptor_snapshots": public_snapshot_audit(snapshot),
        "positions_parsed_from_held_snapshot_bytes": True,
        "hfnet_full_rows": HF_ROWS, "supervins_full_rows": SV_ROWS,
        "hfnet_first_saved_pose_interpretation": "first pose retained in the final saved largest-map artifact after repeated fail/reset/lost events; not one uninterrupted initialization delay",
        "semantic_non_equivalence_disclosed": True,
        "existing_source_artifacts_mutated": False,
    }

    pose_rows: List[List[Any]] = []
    for i, row in enumerate(common["rows"]):
        pose_rows.append([
            i, row["camera_row_index"], row["source_timestamp_ns"], row["gt_row_index"],
            *[number_text(x) for x in gt[i]], *[number_text(x) for x in common["hfnet"][i]],
            *[number_text(x) for x in hf_eval["se3"]["aligned"][i]], number_text(hf_eval["samples"]["se3_ape"][i]),
            *[number_text(x) for x in hf_eval["sim3"]["aligned"][i]], number_text(hf_eval["samples"]["sim3_ape"][i]),
            *[number_text(x) for x in common["supervins"][i]],
            *[number_text(x) for x in sv_eval["se3"]["aligned"][i]], number_text(sv_eval["samples"]["se3_ape"][i]),
            *[number_text(x) for x in sv_eval["sim3"]["aligned"][i]], number_text(sv_eval["samples"]["sim3_ape"][i]),
        ])
    rpe_rows: List[List[Any]] = []
    for i, pair in enumerate(common["pairs"]):
        rpe_rows.append([
            i, pair["left_camera_row_index"], pair["right_camera_row_index"],
            pair["left_timestamp_ns"], pair["right_timestamp_ns"], pair["delta_ns"],
            number_text(hf_eval["samples"]["se3_rpe"][i]), number_text(hf_eval["samples"]["sim3_rpe"][i]),
            number_text(sv_eval["samples"]["se3_rpe"][i]), number_text(sv_eval["samples"]["sim3_rpe"][i]),
        ])

    table = comparison_table(metrics)
    report = """# Exact-Common-Support Descriptive Analysis\n\n## Evidence window\n\n- Sequence: official EuRoC MH_01_easy.\n- Exact camera support: odd indices 945 through 3659, 1358 poses per artifact, 135.7 s.\n- Exact one-second positional-change support: 1348 pairs per artifact.\n- Every source camera timestamp joins an identical official GT timestamp; no interpolation or extrapolation is used.\n- Each artifact is independently fit to GT on exactly these 1358 points using proper fixed-scale SE(3). Proper Sim(3) is reported only as a scale diagnostic. No transform is shared.\n\n## Coverage and semantic boundary\n\n- HFNet saved 2737 trajectory poses from 3682 camera inputs. Its first final-saved pose is camera index 945, 47.249999872 s after sequence cam0. The pinned log shows repeated tracking failures, insufficient-motion events, active-map resets, and lost frames before that pose. This missing prefix is not one uninterrupted initialization delay, and the common window excludes it.\n- SuperVINS generated 1810 poses from 1841 expected odd-camera outputs. Its first output is camera index 63, 3.149999872 s after sequence cam0.\n- The common window begins 44.1 s after the first SuperVINS output. Equal accuracy-sample counts therefore do not imply equal start coverage.\n- After the shared GT-covered boundary at camera index 3659, HFNet has 22 saved rows and SuperVINS has 11 generated rows. These are coverage boundaries, not generation failures.\n- HFNet is a final-map reconstructed largest-map trajectory with lost frames skipped. SuperVINS is an online-published estimator-state trajectory. The artifacts do not have interchangeable output semantics.\n\n## Side-by-side descriptive values\n\n{table}\n\nHFNet Sim(3) diagnostic scale: `{hf_scale}`.\n\nSuperVINS Sim(3) diagnostic scale: `{sv_scale}`.\n\n## Claim Boundary\n\n- Allowed wording: these two pinned artifacts have the listed descriptive values on the exact shared 135.7 s tail under their own common-support fixed-scale fits.\n- Forbidden stronger wording: any cross-system performance ordering, sequence-wide initialization equivalence, online-state equivalence, V2_01, underwater, or general claim.\n- Uncertainty: one deterministic artifact per system, serially correlated residuals, different missing-prefix histories, and non-interchangeable output semantics.\n- Next check: preregister repeated runs and a support/semantics-compatible protocol before any broader comparison.\n- Decision: retain only an artifact-level conditional description; no cross-system arithmetic is computed.\n""".format(table=table, hf_scale=number_text(hf_eval["metrics"]["secondary_sim3_scale_diagnostic"]["scale"]), sv_scale=number_text(sv_eval["metrics"]["secondary_sim3_scale_diagnostic"]["scale"]))

    appendix = """# Statistics Appendix\n\n- Unit of analysis: one deterministic artifact per system.\n- APE: Euclidean translation error after that artifact's own fixed-scale common-support SE(3) fit; n=1358.\n- RPE 1 s: Euclidean error of global-frame position change over exact common-row step 10 / camera-row step 20; all 1348 intervals are exactly 1,000,000,000 ns.\n- Sim(3): independently fit on the same 1358 points and retained only as a scale diagnostic.\n- Quantiles use NumPy linear interpolation; standard deviation is population standard deviation.\n- Timestamp residuals are serially correlated within one artifact. Only descriptive values are reported; no inferential quantities or cross-system arithmetic are computed.\n\n{table}\n""".format(table=full_statistics_table(metrics))
    catalog = """# Figure Catalog\n\n## figure-01-primary-common-support-overlay.svg\n\n- Purpose: display the shared-tail spatial paths after each artifact's own primary fixed-scale SE(3) fit.\n- Data source: `common-support-poses.csv`; official GT and two aligned position series at the same 1358 camera timestamps.\n- Caption requirements: identify official MH01, exact indices 945..3659, `n=1358` per artifact, independent transforms, and different output semantics.\n- Reader notice: XY and XZ use one shared metric extent and exactly equal metres per pixel; there are no repeated-run uncertainty marks.\n- Interpretation boundary: shape and drift patterns are artifact-level observations only; no cross-system ordering is encoded.\n\n## figure-02-primary-error-traces.svg\n\n- Purpose: expose temporal structure in primary APE and exact-one-second RPE on the shared tail.\n- Data source: `common-support-poses.csv` (`n_APE=1358` per artifact) and `common-support-rpe-1s.csv` (`n_RPE=1348` per artifact).\n- Caption requirements: define the independent fixed-scale alignment and exact row-step-10 one-second rule.\n- Reader notice: time and error axes begin at zero; samples are serially correlated and no uncertainty marks are shown.\n- Interpretation boundary: traces describe the pinned artifacts on this window and do not encode cross-system arithmetic or performance ordering.\n"""
    report = report.replace("no cross-system arithmetic is computed", "no cross-system metric contrast or ordering is computed")
    appendix = appendix.replace("no inferential quantities or cross-system arithmetic are computed", "no inferential quantities or cross-system metric contrast or ordering are computed")
    catalog = catalog.replace("cross-system arithmetic or performance ordering", "cross-system metric contrast or ordering")
    boundary_audit = validate_report_boundary([report, appendix, catalog])
    if not boundary_audit["ok"]:
        raise ValueError("forbidden comparison wording in reports: {}".format(boundary_audit["forbidden_tokens_found"]))
    metrics_schema_audit = validate_metrics_contrast_schema(metrics)
    if not metrics_schema_audit["ok"]:
        raise ValueError("forbidden cross-system metric contrast field: {}".format(metrics_schema_audit["forbidden_contrast_fields"]))

    elapsed = np.asarray([(row["source_timestamp_ns"] - COMMON_FIRST_NS) / 1e9 for row in common["rows"]], dtype=float)
    rpe_elapsed = np.asarray([(row["right_timestamp_ns"] - COMMON_FIRST_NS) / 1e9 for row in common["pairs"]], dtype=float)
    figure1, figure1_audit = trajectory_figure(gt, hf_eval["se3"]["aligned"], sv_eval["se3"]["aligned"])
    figure2, figure2_audit = error_figure(elapsed, hf_eval["samples"]["se3_ape"], sv_eval["samples"]["se3_ape"], rpe_elapsed, hf_eval["samples"]["se3_rpe"], sv_eval["samples"]["se3_rpe"])

    outputs: List[Tuple[Path, bytes]] = [
        (ANALYSIS / "metrics.json", canonical_json_bytes(metrics)),
        (ANALYSIS / "input-audit.json", canonical_json_bytes(input_audit)),
        (ANALYSIS / "support-audit.json", canonical_json_bytes(support_audit)),
        (ANALYSIS / "alignment.json", canonical_json_bytes(alignment_json)),
        (ANALYSIS / "common-support-poses.csv", csv_text(POSE_HEADER, pose_rows).encode("utf-8")),
        (ANALYSIS / "common-support-rpe-1s.csv", csv_text(RPE_HEADER, rpe_rows).encode("utf-8")),
        (ANALYSIS / "analysis-report.md", report.encode("utf-8")),
        (ANALYSIS / "stats-appendix.md", appendix.encode("utf-8")),
        (ANALYSIS / "figure-catalog.md", catalog.encode("utf-8")),
        (FIGURES / "figure-01-primary-common-support-overlay.svg", figure1.encode("utf-8")),
        (FIGURES / "figure-02-primary-error-traces.svg", figure2.encode("utf-8")),
    ]
    written: Dict[str, Dict[str, Any]] = {}
    for path, payload_bytes in outputs:
        raise_if_pending()
        written[str(path.relative_to(ATTEMPT))] = write_bytes_exclusive(path, payload_bytes)
    entries = dict(sorted(written.items()))
    manifest: Dict[str, Any] = {
        "schema_version": "aqua-fe-hfnet-supervins-common-support-artifact-manifest-v1",
        "entry_count": len(entries), "entries": entries,
        "bundle_content_tree_sha256": artifact_tree_digest(entries),
        "algorithm": "SHA-256 per exact file; compact canonical sorted path/sha256/size tree; manifest excludes itself",
        "self_hash_algorithm": "SHA-256 of compact canonical manifest object with self_hash set to null",
        "self_hash": None,
    }
    manifest["self_hash"] = self_hash_object(manifest)
    written["analysis-output/artifact-manifest.json"] = write_json_exclusive(ANALYSIS / "artifact-manifest.json", manifest)
    return {"metrics": metrics, "input_audit": input_audit, "support_audit": support_audit,
            "alignment": alignment_json, "figure_audits": {"figure_01": figure1_audit, "figure_02": figure2_audit},
            "report_boundary_audit": boundary_audit, "metrics_schema_audit": metrics_schema_audit,
            "bundle_artifacts": written}


def inventory_attempt_files(exclude_result: bool = True) -> Dict[str, Dict[str, Any]]:
    files: Dict[str, Dict[str, Any]] = {}
    if not ATTEMPT.exists():
        return files
    for path in sorted(ATTEMPT.rglob("*")):
        if path.is_file() and not (exclude_result and path == RUN_RESULT):
            files[str(path.relative_to(ATTEMPT))] = file_identity(path, include_seal=True)
    return files


def audit_completed_bundle(expected: Mapping[str, Mapping[str, Any]]) -> Dict[str, Any]:
    actual = sorted(str(path.relative_to(ATTEMPT)) for path in ANALYSIS.rglob("*") if path.is_file())
    exact = actual == sorted(REQUIRED_BUNDLE_FILES)
    checks: Dict[str, Any] = {}
    ok = exact
    for relative in actual:
        observed = file_identity(ATTEMPT / relative, include_seal=True)
        row_ok = observed == expected.get(relative) and observed["mode"] == "0444" and observed["nlink"] == 1
        checks[relative] = {"observed": observed, "expected": expected.get(relative), "ok": row_ok}
        ok &= row_ok
    manifest = load_json(ANALYSIS / "artifact-manifest.json")
    entries = manifest.get("entries", {})
    tree_ok = (set(entries) == set(REQUIRED_BUNDLE_FILES) - {"analysis-output/artifact-manifest.json"}
               and manifest.get("entry_count") == len(entries)
               and manifest.get("bundle_content_tree_sha256") == artifact_tree_digest(entries)
               and manifest.get("self_hash") == self_hash_object(manifest))
    for relative, identity in entries.items():
        tree_ok &= file_identity(ATTEMPT / relative, include_seal=True) == identity
    ok &= tree_ok
    return {"ok": bool(ok), "exact_file_set": exact, "file_checks": checks, "manifest_tree_and_self_hash_ok": bool(tree_ok),
            "bundle_content_tree_sha256": manifest.get("bundle_content_tree_sha256"),
            "manifest_identity": file_identity(ANALYSIS / "artifact-manifest.json", include_seal=True)}


def post_pin_audit(preflight: Mapping[str, Any]) -> Dict[str, Any]:
    expected = {path: row["expected"] for path, row in preflight.get("pin_snapshot", {}).get("checks", {}).items()}
    return inspect_pins(expected)


def ensure_failure_namespace() -> bool:
    if not NAMESPACE_OWNED or not EVIDENCE_ROOT.exists():
        return False
    try:
        if not ATTEMPT.exists():
            mkdir_exclusive_durable(ATTEMPT)
        return ATTEMPT.is_dir()
    except Exception:
        return False


def best_effort(callable_value: Any, fallback: Any) -> Any:
    try:
        return callable_value()
    except Exception as exc:
        if isinstance(fallback, dict):
            result = dict(fallback); result["error"] = "{}: {}".format(type(exc).__name__, exc); return result
        return fallback


def run_once(token: str) -> int:
    global NAMESPACE_OWNED, TERMINAL_COMMITTED
    if token != TOKEN:
        try:
            print(json.dumps({"status": "NO_GO", "error": "authorization token mismatch"}, sort_keys=True))
        except (BrokenPipeError, OSError):
            pass
        return 2
    preflight = collect_prestart(require_authority=True)
    if not preflight["ready"] or preflight["status"] != "GO_EXACTLY_ONE_PURE_COMMON_SUPPORT_EVALUATION_START":
        try:
            print(json.dumps({"status": "NO_GO", "failures": preflight["failures"]}, sort_keys=True))
        except (BrokenPipeError, OSError):
            pass
        return 2

    previous_handlers = install_signal_handlers()
    snapshot: Optional[Dict[str, Any]] = None
    started_at = now_iso()
    try:
        create_owned_evidence_root()
        mkdir_exclusive_durable(ATTEMPT)
        raise_if_pending()
        claim = {
            "schema_version": "aqua-fe-hfnet-supervins-common-support-start-claim-v1",
            "created_at": now_iso(), "attempt": "attempt_001",
            "evaluation_start_count_before": 0, "evaluation_start_count_after": 1,
            "maximum_evaluator_starts": 1, "retry_authorized": False,
            "controller_command": CONTROLLER_COMMAND, "authorization_token_sha256": TOKEN_SHA256,
            "protocol": file_identity(FREEZE), "lock": file_identity(LOCK),
            "authority": file_identity(AUTHORITY), "runner": file_identity(RUNNER),
            "tests": file_identity(TESTS), "test_receipt": file_identity(TEST_RECEIPT),
            "boundary": "pure computation over existing held-FD snapshots; no subprocess, ROS, model, publisher, or trajectory generation",
        }
        write_json_exclusive(START_CLAIM, claim)
        raise_if_pending()
        write_json_exclusive(PREFLIGHT_RESULT, preflight)
        mkdir_exclusive_durable(ANALYSIS)
        mkdir_exclusive_durable(FIGURES)
        raise_if_pending()

        pins = load_json(LOCK)["pinned_files"]
        snapshot = held_snapshot_open(SNAPSHOT_PATHS, pins)
        payloads = snapshot["records"]
        get_payload = lambda path: payloads[str(path.resolve())]["payload"]
        timestamp_support = support_audit_from_bytes(get_payload(HF_TRAJECTORY), get_payload(SV_TRAJECTORY), get_payload(CAMERA_CSV), get_payload(GT_CSV))
        if not timestamp_support["ok"]:
            raise ValueError("authorized held-snapshot timestamp support failed")
        evaluation = generate_analysis_bundle(snapshot, timestamp_support)
        raise_if_pending()

        held_post = held_snapshot_postflight(snapshot, pins)
        if not held_post["ok"]:
            raise ValueError("held descriptor/path postflight failed")
        post_pins = post_pin_audit(preflight)
        if not post_pins["ok"]:
            raise ValueError("postflight pin audit failed")
        bundle_audit = audit_completed_bundle(evaluation["bundle_artifacts"])
        if not bundle_audit["ok"]:
            raise ValueError("strict bundle audit failed")
        relevant = relevant_processes()
        children = direct_child_processes()
        if relevant or children:
            raise ValueError("relevant generator or evaluator child process observed")
        authority_post = authority_audit(load_json(LOCK))
        if not authority_post["valid"] or authority_post.get("identity") != preflight["authority"].get("identity"):
            raise ValueError("root execution authority changed or became invalid")
        figure_audits = evaluation["figure_audits"]
        pass_conditions = {
            "preflight_go_with_root_authority": True,
            "exact_one_evaluator_start_no_retry": True,
            "held_descriptor_snapshots_and_postflight_paths_match": held_post["ok"],
            "all_frozen_pins_unchanged": post_pins["ok"],
            "root_authority_identity_unchanged_and_valid": authority_post["valid"] and authority_post.get("identity") == preflight["authority"].get("identity"),
            "identical_exact_gt_common_support_1358_each": evaluation["support_audit"]["counts"]["common"] == COMMON_COUNT,
            "exact_one_second_pairs_1348_each": evaluation["support_audit"]["counts"]["rpe_pairs"] == RPE_COUNT,
            "independent_fixed_scale_proper_se3": all(evaluation["alignment"][system]["primary_fixed_scale_se3"]["proper"] for system in ("hfnet", "supervins")),
            "independent_positive_scale_proper_sim3_diagnostic": all(evaluation["alignment"][system]["secondary_sim3_scale_diagnostic"]["proper"] for system in ("hfnet", "supervins")),
            "frozen_core_coordinate_crosschecks": all(evaluation["alignment"][system]["primary_fixed_scale_se3"]["core_crosscheck_max_abs_m"] <= 1e-12 for system in ("hfnet", "supervins")),
            "all_metric_values_finite_nonnegative_and_counts_exact": metrics_finite_nonnegative(evaluation["metrics"]),
            "cross_system_metric_contrast_and_ordering_absent": evaluation["metrics"]["statistical_boundary"]["cross_system_metric_contrast_computed"] is False and evaluation["report_boundary_audit"]["ok"] and evaluation["metrics_schema_audit"]["ok"],
            "coverage_failure_prefix_and_output_semantics_disclosed": evaluation["input_audit"]["semantic_non_equivalence_disclosed"],
            "bundle_complete_manifested_tree_and_self_hashed": bundle_audit["ok"],
            "trajectory_figure_equal_metric_aspect_and_shared_domain": figure_audits["figure_01"]["equal_metric_aspect_all_axes"],
            "error_figure_axes_lower_zero": figure_audits["figure_02"]["all_axis_lower_bounds_exact_zero"],
            "figure_gridline_coordinates_valid": figure_audits["figure_01"]["gridline_coordinates_valid"] and figure_audits["figure_02"]["gridline_coordinates_valid"],
            "no_subprocess_ros_model_publisher_or_trajectory_generation": not relevant and not children,
        }
        if not all(pass_conditions.values()):
            raise ValueError("terminal pass condition failed")
        artifacts = inventory_attempt_files(exclude_result=True)
        result = {
            "schema_version": RESULT_SCHEMA,
            "status": "PASS_DEVELOPMENT_OFFICIAL_MH01_EXACT_COMMON_SUPPORT_DESCRIPTIVE_ANALYSIS",
            "return_code": 0, "started_at": started_at, "completed_at": now_iso(),
            "authorization": {"evaluation_start_count": 1, "retry_authorized": False,
                              "root_execution_authority": file_identity(AUTHORITY, include_seal=True)},
            "pass_conditions": pass_conditions, "metrics": evaluation["metrics"],
            "support_audit": evaluation["support_audit"], "alignment": evaluation["alignment"],
            "figure_audits": figure_audits, "bundle_audit": bundle_audit,
            "held_snapshot_postflight": held_post, "post_pin_audit": post_pins,
            "root_authority_preflight": preflight["authority"], "root_authority_postflight": authority_post,
            "relevant_processes_at_closeout": relevant, "direct_child_processes_at_closeout": children,
            "artifact_count_before_result": len(artifacts), "artifacts": artifacts,
            "claim_boundary": {
                "artifact_level_exact_common_tail_description_only": True,
                "cross_system_metric_contrast": False, "performance_ordering": False,
                "inferential_statistics": False, "model_or_ros_rerun": False,
                "equivalent_initialization_or_output_semantics": False,
                "readme_v2_01_underwater_or_generalization": False,
            },
            "next_stage_automatically_authorized": False,
        }
        raise_if_pending()
        result_identity = write_json_exclusive(RUN_RESULT, result)
        TERMINAL_COMMITTED = True
        try:
            print(json.dumps({"status": result["status"], "return_code": 0, "run_result_identity": result_identity}, sort_keys=True))
        except (BrokenPipeError, OSError):
            pass
        return 0
    except BaseException as exc:
        if ensure_failure_namespace() and not TERMINAL_COMMITTED and not RUN_RESULT.exists():
            failure = {
                "schema_version": RESULT_SCHEMA,
                "status": "FAIL_DEVELOPMENT_OFFICIAL_MH01_EXACT_COMMON_SUPPORT_DESCRIPTIVE_ANALYSIS",
                "return_code": 1, "started_at": started_at, "completed_at": now_iso(),
                "error": {"type": type(exc).__name__, "message": str(exc), "traceback": traceback.format_exc()},
                "pending_signal": PENDING_SIGNAL, "retry_authorized": False,
                "preflight_pin_snapshot": preflight.get("pin_snapshot", {}),
                "held_snapshot_postflight": best_effort(lambda: held_snapshot_postflight(snapshot or {}, load_json(LOCK)["pinned_files"]), {"ok": False, "checks": {}, "failures": []}),
                "post_pin_audit": best_effort(lambda: post_pin_audit(preflight), {"ok": False, "checks": {}, "failures": []}),
                "artifacts_before_result": best_effort(lambda: inventory_attempt_files(exclude_result=True), {}),
                "claim_boundary": {"scientific_metrics_may_be_used": False, "model_or_ros_rerun": False, "retry_authorized": False},
            }
            try:
                write_json_exclusive(RUN_RESULT, failure)
                TERMINAL_COMMITTED = True
            except Exception:
                pass
        try:
            print(json.dumps({"status": "FAIL", "error": "{}: {}".format(type(exc).__name__, exc)}, sort_keys=True))
        except (BrokenPipeError, OSError):
            pass
        return 1
    finally:
        close_held_snapshot(snapshot)
        restore_signal_handlers(previous_handlers)


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--action", choices=("preflight", "run"), required=True)
    parser.add_argument("--authorization-token", default="")
    args = parser.parse_args(argv)
    if args.action == "preflight":
        result = collect_prestart(require_authority=False)
        print(json.dumps(result, indent=2, sort_keys=True, allow_nan=False))
        return 0 if result["ready"] else 2
    return run_once(args.authorization_token)


if __name__ == "__main__":
    raise SystemExit(main())
