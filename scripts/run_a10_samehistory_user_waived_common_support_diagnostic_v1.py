#!/usr/bin/env python3
"""Run the frozen A10 user-waived, analysis-only common-support diagnostic.

This program never starts SLAM, VINS, ROS replay, or HFNet.  It reads four
existing trajectories, canonicalizes only the sealed HFNet timestamp spelling,
and invokes the epoch-ns common-support evaluator once into a new output tree.
"""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from typing import Any, Mapping


ROOT = Path("/home/ma/AQUA-FE_WS")
PROTOCOL = ROOT / "papers/a10_samehistory_user_waived_common_support_diagnostic_v1_protocol.md"
OUTPUT = Path("/mnt/data/AQUA-FE_WS/experiments/a10_samehistory_user_waived_diagnostic_v1")
RAW_BAG = Path("/mnt/data/AQUA-FE_WS/experiments/a10_samehistory_system_v1/raw/archaeo10_0000_2800.bag")
HFNET_BRIDGE = Path(
    "/mnt/data/AQUA-FE_WS/logs/published_hfnet_slam_v6/positive_windows/"
    "a10_0000_2800_score_2400_2800_warmstart/attempt_001/bridges/"
    "hfnet_world_T_body_vins_csv_v1.csv"
)
KLT_RECEIPT = Path(
    "/mnt/data/AQUA-FE_WS/experiments/a10_samehistory_system_v4_backend_recovery/"
    "backends/klt_external_feature_context/formal_run_receipt_v4.json"
)
EVALUATOR = ROOT / "scripts/evaluate_vins_common_support_epoch_v2.py"
EVALUATOR_BASE = ROOT / "scripts/evaluate_vins_common_support.py"
EVALUATOR_CORE = ROOT / "scripts/trajectory_eval_core.py"
HFNET_CONFIG = ROOT / "configs/published_baselines/hfnet_aqualoc_a02_body_T_cam0_v1.yaml"
EVO_APE = Path("/home/ma/.local/bin/evo_ape")
EVO_RPE = Path("/home/ma/.local/bin/evo_rpe")

SCORE_START_NS = 1_542_888_916_043_622_160
SCORE_END_NS = 1_542_888_936_039_921_424
CAMERA_TOPIC = "/camera/image_raw"
REFERENCE_TOPIC = "/aqualoc/colmap_gt"
EXPECTED_DELTA_HISTOGRAM = {
    -112: 44,
    -80: 60,
    -48: 45,
    -16: 60,
    16: 46,
    48: 52,
    80: 38,
    112: 56,
}

ARM_ORDER = (
    "VANILLA_ORIGIN_NATIVE_IMAGE_CONTEXT",
    "EXTERNAL_KLT_FINALONLINE_BACKBONE",
    "AQUAFE_FINALONLINE_XFEAT_LINEAGE",
    "HFNET_SLAM_WARMSTART",
)

TRAJECTORIES = {
    ARM_ORDER[0]: Path(
        "/mnt/data/AQUA-FE_WS/experiments/a10_samehistory_system_v4_backend_recovery/"
        "backends/vanilla_origin_native_image_context/vins_output/vio.csv"
    ),
    ARM_ORDER[1]: Path(
        "/mnt/data/AQUA-FE_WS/experiments/a10_samehistory_system_v4_backend_recovery/"
        "backends/klt_external_feature_context/vins_output/vio.csv"
    ),
    ARM_ORDER[2]: Path(
        "/mnt/data/AQUA-FE_WS/experiments/a10_samehistory_system_v4_backend_recovery/"
        "backends/aquafe_external_feature_context/vins_output/vio.csv"
    ),
}

CONFIGS = {
    ARM_ORDER[0]: Path(
        "/mnt/data/AQUA-FE_WS/experiments/a10_samehistory_system_v4_backend_recovery/"
        "backends/vanilla_origin_native_image_context/vins_aqualoc_archaeo_origin.yaml"
    ),
    ARM_ORDER[1]: Path(
        "/mnt/data/AQUA-FE_WS/experiments/a10_samehistory_system_v4_backend_recovery/"
        "backends/klt_external_feature_context/vins_aqualoc_archaeo_external.yaml"
    ),
    ARM_ORDER[2]: Path(
        "/mnt/data/AQUA-FE_WS/experiments/a10_samehistory_system_v4_backend_recovery/"
        "backends/aquafe_external_feature_context/vins_aqualoc_archaeo_external.yaml"
    ),
}

EXPECTED_IDENTITIES = {
    str(RAW_BAG): (765_976_943, "49864715ec19005daa3492fa043fe87204fb6f8cc802b6b98cba55a8ab4fe87e"),
    str(HFNET_BRIDGE): (42_749, "a268350cda12c0e4b453420853c19e4dd7b4dc2e121d6616344ad247be032ec1"),
    str(KLT_RECEIPT): (366_217, "bc8aae68cad14fc746969c45ff3c097e7ae800ec51ce5a0e851d2a696feea350"),
    str(EVALUATOR): (5_447, "3c455299b23157cc749b474b9460ca4a408b3bee516e9d1bf2109f253cf89f91"),
    str(EVALUATOR_BASE): (27_933, "ab6f2b5c1a10a41463657edee2724c022fc0248dc885096acb336e602384c110"),
    str(EVALUATOR_CORE): (27_945, "aa9ac4da81df7298d1f1c369548ca98a57235916004337cad66f4cf331560635"),
    str(HFNET_CONFIG): (415, "a76c728b31d47c3a87f54c465fb581007ed2da2b7d7d84df81dbde93e9a886c1"),
    str(EVO_APE): (213, "6bee25dc5bfdab0ead8988ab4014a72511339e94697ec61699f66f68f5f24d15"),
    str(EVO_RPE): (213, "9e07d0bd4566aa680d5e39e58589176a286f4f8a22ba9107a5834ddb278e2bd1"),
    str(TRAJECTORIES[ARM_ORDER[0]]): (141_986, "f3f07e846fae02bd33b44a295106e769b8288710204c05d7b1c65f1d124dbcca"),
    str(TRAJECTORIES[ARM_ORDER[1]]): (142_025, "cd6af6015dfd85662edda8f35309b850d3b4c3f98f9554747a823ec153223fd3"),
    str(TRAJECTORIES[ARM_ORDER[2]]): (142_034, "e303003668a6c3f1fbfe90720b34bd59b990a7d6d3ca15f0d514089b877da7bb"),
    str(CONFIGS[ARM_ORDER[0]]): (1_009, "da4518da471bdcc282430ecef9f7d4f5b69b96148845a60dec012a65ebf656dc"),
    str(CONFIGS[ARM_ORDER[1]]): (1_005, "46db57acf32b1a8f70cfbe67656b7f8544fd7c761e9f79e3c1832e1cce959370"),
    str(CONFIGS[ARM_ORDER[2]]): (1_034, "4f45c72928f6437b134844954c038bbc5dd9cefdf52dea35dc2bfba11c33ff11"),
}

CANONICAL_NAME = "hfnet_world_T_body_source_stamp_canonical_v1.csv"
CANONICAL_EXPECTED = (42_749, "de0090a2c08d795ecdbe47f51c43e18cd624da14be9cfa64bfb3efd52ce2d99a")


class DiagnosticError(RuntimeError):
    pass


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def identity(path: Path) -> dict[str, Any]:
    return {
        "path": str(path),
        "size_bytes": path.stat().st_size,
        "sha256": sha256(path),
    }


def require(condition: bool, code: str) -> None:
    if not condition:
        raise DiagnosticError(code)


def read_json(path: Path) -> Any:
    with path.open(encoding="utf-8") as stream:
        return json.load(stream)


def write_json(path: Path, value: Any) -> None:
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False) + "\n",
        encoding="utf-8",
    )


def verify_inputs() -> dict[str, Any]:
    claims: dict[str, Any] = {}
    for raw_path, expected in EXPECTED_IDENTITIES.items():
        path = Path(raw_path)
        require(path.is_file() and not path.is_symlink(), f"INPUT_NOT_REGULAR:{path}")
        actual = identity(path)
        require(
            (actual["size_bytes"], actual["sha256"]) == expected,
            f"INPUT_IDENTITY_DRIFT:{path}",
        )
        claims[raw_path] = actual
    receipt = read_json(KLT_RECEIPT)
    require(receipt.get("status") == "TERMINAL_PROCESS_RC0", "KLT_TERMINAL_STATUS_DRIFT")
    require(
        receipt.get("overall_disposition") == "EXECUTION_INTEGRITY_FAILED",
        "KLT_DISPOSITION_DRIFT",
    )
    process = receipt.get("terminal_process") or {}
    require(process.get("popen_invocation_count") == 1, "KLT_POPEN_COUNT_DRIFT")
    require(process.get("raw_return_code") == 0, "KLT_CHILD_RC_DRIFT")
    require(process.get("timed_out") is False, "KLT_TIMEOUT_DRIFT")
    require((receipt.get("artifact_contract") or {}).get("status") == "PASS", "KLT_ARTIFACT_NOT_PASS")
    execution = receipt.get("execution_integrity") or {}
    require(execution.get("status") == "FAIL", "KLT_EXECUTION_STATUS_DRIFT")
    require(execution.get("supervisor_error") == "POSTFLIGHT_PROCESS_PRESENT", "KLT_FAILURE_REASON_DRIFT")
    require((receipt.get("score_usability") or {}).get("status") == "PASS", "KLT_SCORE_NOT_PASS")
    return {
        "files": claims,
        "klt_waiver_source": {
            "receipt": claims[str(KLT_RECEIPT)],
            "frozen_status": receipt["status"],
            "frozen_overall_disposition": receipt["overall_disposition"],
            "child_popen_invocations": process["popen_invocation_count"],
            "child_raw_return_code": process["raw_return_code"],
            "artifact_contract_status": receipt["artifact_contract"]["status"],
            "execution_integrity_status": execution["status"],
            "supervisor_error": execution["supervisor_error"],
            "score_usability_status": receipt["score_usability"]["status"],
            "receipt_not_relabelled": True,
        },
    }


def exact_stamp(message: Any) -> int:
    stamp = message.header.stamp
    secs, nsecs = stamp.secs, stamp.nsecs
    require(type(secs) is int and type(nsecs) is int, "ROS_STAMP_NOT_EXACT_INTEGERS")
    require(secs >= 0 and 0 <= nsecs < 1_000_000_000, "ROS_STAMP_RANGE")
    return secs * 1_000_000_000 + nsecs


def raw_score_camera_stamps() -> list[int]:
    ros_path = "/opt/ros/noetic/lib/python3/dist-packages"
    if ros_path not in sys.path:
        sys.path.insert(0, ros_path)
    import rosbag  # type: ignore

    selected: list[int] = []
    index = 0
    with rosbag.Bag(str(RAW_BAG)) as bag:
        for _, message, _ in bag.read_messages(topics=[CAMERA_TOPIC]):
            if 2400 <= index <= 2800:
                selected.append(exact_stamp(message))
            index += 1
    require(index == 2801, f"RAW_CAMERA_COUNT:{index}")
    require(len(selected) == 401, f"RAW_SCORE_CAMERA_COUNT:{len(selected)}")
    require(selected[0] == SCORE_START_NS, "RAW_SCORE_START_DRIFT")
    require(selected[-1] == SCORE_END_NS, "RAW_SCORE_END_DRIFT")
    require(all(b > a for a, b in zip(selected, selected[1:])), "RAW_SCORE_NOT_INCREASING")
    return selected


def canonical_hfnet_payload() -> tuple[bytes, dict[str, Any]]:
    rows: list[list[str]] = []
    sealed_stamps: list[int] = []
    for line_number, raw in enumerate(HFNET_BRIDGE.read_text(encoding="ascii").splitlines(), 1):
        fields = raw.split(",")
        require(len(fields) == 8, f"HFNET_BRIDGE_COLUMNS:LINE_{line_number}")
        try:
            stamp = int(fields[0])
            values = [float(value) for value in fields[1:]]
        except ValueError as error:
            raise DiagnosticError(f"HFNET_BRIDGE_NUMERIC:LINE_{line_number}") from error
        require(all(math.isfinite(value) for value in values), f"HFNET_NONFINITE:LINE_{line_number}")
        rows.append(fields)
        sealed_stamps.append(stamp)
    require(len(rows) == 401, f"HFNET_ROW_COUNT:{len(rows)}")
    canonical_stamps = raw_score_camera_stamps()
    deltas = [sealed - canonical for sealed, canonical in zip(sealed_stamps, canonical_stamps)]
    require(Counter(deltas) == Counter(EXPECTED_DELTA_HISTOGRAM), "HFNET_DELTA_HISTOGRAM_DRIFT")
    require(max(abs(value) for value in deltas) == 112, "HFNET_MAX_DELTA_DRIFT")
    lines = [str(stamp) + "," + ",".join(fields[1:]) for stamp, fields in zip(canonical_stamps, rows)]
    payload = ("\n".join(lines) + "\n").encode("ascii")
    content = {"size_bytes": len(payload), "sha256": hashlib.sha256(payload).hexdigest()}
    require((content["size_bytes"], content["sha256"]) == CANONICAL_EXPECTED, "HFNET_CANONICAL_IDENTITY_DRIFT")
    original_pose_text = "\n".join(",".join(fields[1:]) for fields in rows) + "\n"
    canonical_pose_text = "\n".join(line.split(",", 1)[1] for line in lines) + "\n"
    require(original_pose_text == canonical_pose_text, "HFNET_POSE_TEXT_CHANGED")
    return payload, {
        "schema_version": "aqua-fe-a10-hfnet-source-stamp-canonicalization-user-waived-diagnostic-v1",
        "state": "PASS",
        "source": identity(HFNET_BRIDGE),
        "source_indices_inclusive": [2400, 2800],
        "row_count": 401,
        "sealed_first_stamp_ns": sealed_stamps[0],
        "sealed_last_stamp_ns": sealed_stamps[-1],
        "canonical_first_stamp_ns": canonical_stamps[0],
        "canonical_last_stamp_ns": canonical_stamps[-1],
        "maximum_absolute_delta_ns": 112,
        "complete_delta_histogram_ns": {str(k): v for k, v in sorted(EXPECTED_DELTA_HISTOGRAM.items())},
        "pose_field_text_unchanged": True,
        "canonical_content": content,
        "semantics": "source-index timestamp spelling only; no pose or fitted synchronization change",
    }


def evaluator_command(output_dir: Path, canonical: Path) -> list[str]:
    command = [
        "/usr/bin/python3.8",
        str(EVALUATOR),
        "--reference-bag", str(RAW_BAG),
        "--reference-topic", REFERENCE_TOPIC,
    ]
    for name in ARM_ORDER[:3]:
        command.extend(["--arm", f"{name}={TRAJECTORIES[name]}"])
    command.extend(["--arm", f"{ARM_ORDER[3]}={canonical}"])
    for name in ARM_ORDER[:3]:
        command.extend(["--arm-config", f"{name}={CONFIGS[name]}"])
    command.extend(["--arm-config", f"{ARM_ORDER[3]}={HFNET_CONFIG}"])
    command.extend([
        "--nominal-reference-rate-hz", "1.0",
        "--nominal-estimate-rate-hz", "10.0",
        "--evaluation-rate-hz", "1.0",
        "--max-reference-gap-s", "2.5",
        "--max-estimate-gap-s", "0.25",
        "--window-start-s", "1542888916.043622160",
        "--window-end-s", "1542888936.039921424",
        "--rpe-delta-s", "1.0",
        "--min-ape-poses", "30",
        "--min-ape-span-s", "10.0",
        "--min-common-coverage", "0.70",
        "--min-rpe-pairs", "10",
        "--contrast-name", "A10_SAMEHISTORY_USER_WAIVED_DIAGNOSTIC_V1_SCORE_2400_2800",
        "--output-dir", str(output_dir),
        "--run-evo",
    ])
    return command


def validate_summary(summary: Mapping[str, Any]) -> dict[str, Any]:
    require(set(summary) == {"protocol", "support", "reference", "arms"}, "SUMMARY_SCHEMA")
    protocol = summary["protocol"]
    support = summary["support"]
    arms = summary["arms"]
    require(isinstance(protocol, Mapping) and isinstance(support, Mapping) and isinstance(arms, Mapping), "SUMMARY_TYPES")
    require(protocol.get("contrast_name") == "A10_SAMEHISTORY_USER_WAIVED_DIAGNOSTIC_V1_SCORE_2400_2800", "CONTRAST_DRIFT")
    require(protocol.get("body_to_camera_applied") is True, "BODY_CAMERA_NOT_APPLIED")
    require(protocol.get("rpe_semantics") == "aligned_global_frame_positional_delta", "RPE_SEMANTICS_DRIFT")
    require(protocol.get("evaluation_rate_hz") == 1.0, "EVAL_RATE_DRIFT")
    require(protocol.get("max_reference_gap_s") == 2.5, "REFERENCE_GAP_DRIFT")
    require(protocol.get("max_estimate_gap_s") == 0.25, "ESTIMATE_GAP_DRIFT")
    require(set(arms) == set(ARM_ORDER), "ARM_SET_DRIFT")
    grid = support.get("grid_count")
    matched = support.get("matched_count")
    pairs = support.get("rpe_pairs")
    coverage = support.get("common_coverage")
    require(type(grid) is int and grid == 20, f"GRID_COUNT:{grid}")
    require(type(matched) is int and 0 <= matched <= grid, f"MATCHED_COUNT:{matched}")
    require(type(pairs) is int and 0 <= pairs <= 19, f"RPE_PAIRS:{pairs}")
    require(isinstance(coverage, (int, float)) and math.isfinite(coverage), "COVERAGE_INVALID")
    require(abs(float(coverage) - matched / grid) <= 1e-12, "COVERAGE_INCONSISTENT")
    require(support.get("ape_valid") is False, "FORMAL_APE_GATE_UNEXPECTEDLY_OPEN")
    common_gate = matched >= 15 and matched / 20 >= 0.70 and matched / 21 >= 0.70
    rpe_gate = common_gate and pairs >= 10
    metrics: dict[str, Any] = {}
    for name in ARM_ORDER:
        row = arms[name]
        require(row.get("matched_count") == matched, f"ARM_MATCHED_DRIFT:{name}")
        require(row.get("rpe_pairs") == pairs, f"ARM_RPE_PAIR_DRIFT:{name}")
        values = {}
        for key in ("ape_rmse_m", "ape_median_m", "ape_max_m", "rpe_rmse_m", "rpe_median_m", "rpe_max_m"):
            value = row.get(key)
            require(isinstance(value, (int, float)) and math.isfinite(value) and value >= 0, f"METRIC_INVALID:{name}:{key}")
            values[key] = float(value)
        metrics[name] = values
    return {
        "uniform_grid_count": grid,
        "uniform_common_matched_count": matched,
        "uniform_common_coverage": matched / 20,
        "conservative_fixed_denominator_index": matched / 21,
        "uniform_exact_1s_rpe_pairs": pairs,
        "common_support_gate_pass": common_gate,
        "descriptive_rpe_gate_pass": rpe_gate,
        "formal_ape_gate_open": False,
        "formal_winner_permitted": False,
        "metrics_fixed_order": metrics,
    }


def report_markdown(adjudication: Mapping[str, Any]) -> str:
    lines = [
        "# A10 same-history user-waived common-support diagnostic v1",
        "",
        "Status: `DEVELOPMENT_ONLY_USER_WAIVED_DIAGNOSTIC`.",
        "",
        "The frozen v4 KLT receipt remains `EXECUTION_INTEGRITY_FAILED`; its real RC0/artifact-PASS/score-PASS trajectory is read only under the explicit local-policy waiver. No prior receipt was changed and no SLAM system was rerun.",
        "",
        "| Fixed-order system | Descriptive SE(3) APE RMSE / median / max (m) | Descriptive 1 s RPE RMSE / median / max (m) |",
        "|---|---:|---:|",
    ]
    metrics = adjudication["metrics_fixed_order"]
    for name in ARM_ORDER:
        row = metrics[name]
        lines.append(
            f"| `{name}` | {row['ape_rmse_m']:.6f} / {row['ape_median_m']:.6f} / {row['ape_max_m']:.6f} | "
            f"{row['rpe_rmse_m']:.6f} / {row['rpe_median_m']:.6f} / {row['rpe_max_m']:.6f} |"
        )
    lines.extend([
        "",
        "## Support",
        "",
        f"- Uniform grid: {adjudication['uniform_grid_count']}.",
        f"- Jointly matched: {adjudication['uniform_common_matched_count']}.",
        f"- matched/20: {adjudication['uniform_common_coverage']:.6f}.",
        f"- conservative matched/21 index: {adjudication['conservative_fixed_denominator_index']:.6f}.",
        f"- Exact 1 s RPE pairs: {adjudication['uniform_exact_1s_rpe_pairs']}.",
        "- Formal APE gate: closed (20 uniform samples and 21 native proxy rows are both below the frozen 30-pose minimum).",
        "",
        "## Interpretation boundary",
        "",
        "This is one selected development window with one existing trajectory per method. Values are descriptive COLMAP/depth-scale proxies only. No confidence interval, p-value, ranking, winner, superiority, or primary-paper claim is authorized. AQUA-FE learned additions occur only in the prefix in this natural-history run, so any score-window difference is a history effect, not direct score-frame learned action.",
        "",
    ])
    return "\n".join(lines)


def stats_markdown(adjudication: Mapping[str, Any]) -> str:
    return "\n".join([
        "# Statistical appendix",
        "",
        "- Unit of analysis: one preselected A10 score window.",
        "- Independent run/window count: `n=1` for inference; the 20 time-grid samples are correlated trajectory samples and are not treated as independent replicates.",
        "- Descriptive statistics: exact per-arm APE/RPE summaries on one four-arm intersection mask.",
        "- Uncertainty interval: not computed; no independent repeated trajectories under the same accepted protocol.",
        "- Inferential test/effect size/multiple-comparison correction: not applicable and not performed.",
        f"- Common support: `{adjudication['uniform_common_matched_count']}/20`; exact 1 s RPE pairs: `{adjudication['uniform_exact_1s_rpe_pairs']}`.",
        "- Alignment: fixed-scale SE(3), no Sim(3) scale fitting.",
        "- Reference: same-image COLMAP/depth-scale proxy, not independent ground truth.",
        "- Formal APE gate: closed by the preregistered 30-pose minimum.",
        "",
    ])


def figure_catalog_markdown() -> str:
    return "\n".join([
        "# Figure catalog",
        "",
        "No figure is generated for this diagnostic. Four exact fixed-order rows are clearer than an uncertainty-free bar chart, and the single-window design does not support error bars or inferential visual claims.",
        "",
    ])


def run() -> dict[str, Any]:
    require(not OUTPUT.exists() and not OUTPUT.is_symlink(), "OUTPUT_ALREADY_EXISTS")
    preflight = verify_inputs()
    payload, canonical_audit = canonical_hfnet_payload()
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".a10_user_waived_diagnostic_v1.", dir=str(OUTPUT.parent)))
    try:
        canonical_path = staging / CANONICAL_NAME
        canonical_path.write_bytes(payload)
        write_json(staging / f"{CANONICAL_NAME}.manifest.json", canonical_audit)
        evaluator_dir = staging / "common_support"
        command = evaluator_command(evaluator_dir, canonical_path)
        process = subprocess.run(
            command,
            cwd=str(ROOT),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=180,
            check=False,
            env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        )
        write_json(staging / "evaluator_process_receipt.json", {
            "schema_version": "aqua-fe-a10-user-waived-diagnostic-evaluator-process-receipt-v1",
            "command": command,
            "raw_return_code": process.returncode,
            "timed_out": False,
            "stdout": process.stdout,
        })
        require(process.returncode == 0, f"EVALUATOR_RC:{process.returncode}")
        summary_path = evaluator_dir / "common_support_summary.json"
        require(summary_path.is_file(), "COMMON_SUPPORT_SUMMARY_MISSING")
        summary = read_json(summary_path)
        adjudication = validate_summary(summary)
        require(adjudication["common_support_gate_pass"] is True, "COMMON_SUPPORT_GATE_FAILED")
        require(adjudication["descriptive_rpe_gate_pass"] is True, "RPE_SUPPORT_GATE_FAILED")
        evo_path = evaluator_dir / "evo_crosscheck.json"
        require(evo_path.is_file(), "EVO_CROSSCHECK_MISSING")
        evo = read_json(evo_path)
        require(evo.get("evo_version") == "1.31.1", "EVO_VERSION_DRIFT")
        require(evo.get("rpe_semantics") == "aligned_global_frame_positional_delta", "EVO_RPE_SEMANTICS_DRIFT")
        require(set((evo.get("arms") or {})) == set(ARM_ORDER), "EVO_ARM_SET_DRIFT")
        for name in ARM_ORDER:
            row = evo["arms"][name]
            require(row.get("rpe_pair_count") == adjudication["uniform_exact_1s_rpe_pairs"], f"EVO_RPE_PAIR_DRIFT:{name}")
            require(float(row.get("ape_abs_diff_m")) <= 1e-5, f"EVO_APE_CROSSCHECK_DRIFT:{name}")
            require(float(row.get("rpe_abs_diff_m")) <= 1e-5, f"EVO_RPE_CROSSCHECK_DRIFT:{name}")
        input_manifest = {
            "schema_version": "aqua-fe-a10-user-waived-diagnostic-input-manifest-v1",
            "status": "PASS",
            "protocol": identity(PROTOCOL),
            "runner": identity(Path(__file__)),
            **preflight,
            "hfnet_canonicalization": canonical_audit,
            "fixed_arm_order": list(ARM_ORDER),
        }
        write_json(staging / "input_manifest.json", input_manifest)
        bundle = {
            "schema_version": "aqua-fe-a10-samehistory-user-waived-common-support-diagnostic-v1",
            "status": "DEVELOPMENT_ONLY_USER_WAIVED_DIAGNOSTIC",
            "generated_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "slams_or_backends_executed": False,
            "prior_v4_receipt_relabelled": False,
            "klt_local_policy_waiver": preflight["klt_waiver_source"],
            "support_adjudication": adjudication,
            "common_support_summary": summary,
            "evo_1_31_1_crosscheck": evo,
            "claim_boundary": {
                "development_only": True,
                "formal_ape_gate_open": False,
                "accuracy_values_are_descriptive_colmap_proxy": True,
                "independent_run_count_for_inference": 1,
                "confidence_interval_computed": False,
                "significance_test_performed": False,
                "ranking_or_winner_computed": False,
                "superiority_claimed": False,
                "primary_paper_evidence_permitted": False,
            },
        }
        write_json(staging / "analysis_bundle.json", bundle)
        (staging / "analysis-report.md").write_text(report_markdown(adjudication), encoding="utf-8")
        (staging / "stats-appendix.md").write_text(stats_markdown(adjudication), encoding="utf-8")
        (staging / "figure-catalog.md").write_text(figure_catalog_markdown(), encoding="utf-8")
        files = {}
        for path in sorted(staging.rglob("*")):
            if path.is_file() and path.name != "result_manifest.json":
                files[str(path.relative_to(staging))] = {
                    "size_bytes": path.stat().st_size,
                    "sha256": sha256(path),
                }
        write_json(staging / "result_manifest.json", {
            "schema_version": "aqua-fe-a10-user-waived-diagnostic-result-manifest-v1",
            "status": "COMPLETE",
            "files": files,
        })
        require(not OUTPUT.exists() and not OUTPUT.is_symlink(), "OUTPUT_APPEARED_DURING_RUN")
        staging.rename(OUTPUT)
        return {
            "status": bundle["status"],
            "output": str(OUTPUT),
            "support": adjudication,
        }
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("preflight", "run"))
    args = parser.parse_args()
    try:
        if args.command == "preflight":
            require(not OUTPUT.exists() and not OUTPUT.is_symlink(), "OUTPUT_ALREADY_EXISTS")
            result = {"status": "READY", "output_absent": True, **verify_inputs()}
        else:
            result = run()
        print(json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False))
        return 0
    except (DiagnosticError, OSError, ValueError, subprocess.TimeoutExpired) as error:
        print(f"DIAGNOSTIC_ERROR:{error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
