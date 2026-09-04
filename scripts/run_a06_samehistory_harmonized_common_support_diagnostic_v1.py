#!/usr/bin/env python3
"""Run the frozen A06 analysis-only harmonized common-support diagnostic.

This program never starts SLAM, VINS, ROS replay, or HFNet. It reads four
existing trajectories, restores only the sealed HFNet timestamp spelling to
the exact source camera headers, and invokes the epoch-ns evaluator once.
"""

from __future__ import annotations

import argparse
from bisect import bisect_left
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
PROTOCOL = ROOT / "papers/a06_samehistory_harmonized_common_support_diagnostic_v1_protocol.md"
OUTPUT = Path("/mnt/data/AQUA-FE_WS/experiments/a06_samehistory_harmonized_diagnostic_v1")
RAW_BAG = Path("/mnt/data/AQUA-FE_WS/experiments/samehistory_system_v1/raw/archaeo06_0000_2460.bag")
HFNET_BRIDGE = Path(
    "/mnt/data/AQUA-FE_WS/logs/published_hfnet_slam_v6/fresh_underwater/"
    "aqualoc_archaeology_a06_0000_2460/attempt_001/bridges/"
    "hfnet_world_T_body_vins_csv_v1.csv"
)
VANILLA_RECEIPT = Path(
    "/mnt/data/AQUA-FE_WS/experiments/samehistory_system_v1/runs/a06/"
    "vanilla_origin/formal_run_receipt_v1.json"
)
KLT_RECEIPT = Path(
    "/mnt/data/AQUA-FE_WS/experiments/samehistory_system_v1/runs/a06/"
    "external_klt_corrective_replay/formal_run_receipt_v1.json"
)
AQUA_RECEIPT = Path(
    "/mnt/data/AQUA-FE_WS/experiments/samehistory_system_v1/runs/a06/"
    "aquafe_proposed_safe/formal_run_receipt_v1.json"
)
KLT_FEATURES = Path(
    "/mnt/data/AQUA-FE_WS/experiments/samehistory_system_v1/runs/a06/external_klt/features.bag"
)
AQUA_FEATURES = Path(
    "/mnt/data/AQUA-FE_WS/experiments/samehistory_system_v1/runs/a06/aquafe_proposed_safe/features.bag"
)
AQUA_METRICS = Path(
    "/mnt/data/AQUA-FE_WS/experiments/samehistory_system_v1/runs/a06/"
    "aquafe_proposed_safe/frontend_metrics.csv"
)
EVALUATOR = ROOT / "scripts/evaluate_vins_common_support_epoch_v2.py"
EVALUATOR_BASE = ROOT / "scripts/evaluate_vins_common_support.py"
EVALUATOR_CORE = ROOT / "scripts/trajectory_eval_core.py"
HFNET_CONFIG = ROOT / "configs/published_baselines/hfnet_aqualoc_a02_body_T_cam0_v1.yaml"
EVO_APE = Path("/home/ma/.local/bin/evo_ape")
EVO_RPE = Path("/home/ma/.local/bin/evo_rpe")

SCORE_START_NS = 1_542_883_422_269_233_600
SCORE_END_NS = 1_542_883_434_765_650_624
CAMERA_TOPIC = "/camera/image_raw"
REFERENCE_TOPIC = "/aqualoc/colmap_gt"
EXPECTED_DELTA_HISTOGRAM = {
    -128: 133,
    -96: 302,
    -64: 334,
    -32: 288,
    0: 320,
    32: 305,
    64: 294,
    96: 329,
    128: 152,
}

ARM_ORDER = (
    "VANILLA_ORIGIN_NATIVE_IMAGE_CONTEXT",
    "EXTERNAL_KLT_CORRECTIVE_REPLAY",
    "AQUAFE_PROPOSED_SAFE_NO_LEARNED_ACTION",
    "HFNET_SLAM_NATURAL_HISTORY",
)

TRAJECTORIES = {
    ARM_ORDER[0]: Path(
        "/mnt/data/AQUA-FE_WS/experiments/samehistory_system_v1/runs/a06/"
        "vanilla_origin/vins_output/vio.csv"
    ),
    ARM_ORDER[1]: Path(
        "/mnt/data/AQUA-FE_WS/experiments/samehistory_system_v1/runs/a06/"
        "external_klt_corrective_replay/vins_output/vio.csv"
    ),
    ARM_ORDER[2]: Path(
        "/mnt/data/AQUA-FE_WS/experiments/samehistory_system_v1/runs/a06/"
        "aquafe_proposed_safe/vins_output/vio.csv"
    ),
}

CONFIGS = {
    ARM_ORDER[0]: Path(
        "/mnt/data/AQUA-FE_WS/experiments/samehistory_system_v1/runs/a06/"
        "vanilla_origin/vins_aqualoc_archaeo_origin.yaml"
    ),
    ARM_ORDER[1]: Path(
        "/mnt/data/AQUA-FE_WS/experiments/samehistory_system_v1/runs/a06/"
        "external_klt_corrective_replay/vins_aqualoc_archaeo_external.yaml"
    ),
    ARM_ORDER[2]: Path(
        "/mnt/data/AQUA-FE_WS/experiments/samehistory_system_v1/runs/a06/"
        "aquafe_proposed_safe/vins_aqualoc_archaeo_external.yaml"
    ),
}

EXPECTED_IDENTITIES = {
    str(RAW_BAG): (573_420_704, "22cc3cff28dabc34de04c870eed5180ab76832c1f3c912da62d0268e9acb2e9a"),
    str(HFNET_BRIDGE): (259_978, "e460b4d51c40f6bb04068a81dcf74cb050a4192e586fa2def334e76ee9b2227d"),
    str(VANILLA_RECEIPT): (2_832, "b26ff3648a92379e1120845a2a9538fc72d6dc85c85bf547b5aa36ae58382079"),
    str(KLT_RECEIPT): (3_902, "e4ba54b2e2a09689318d2dcfd25d78f144c60eb2c1bee511bbfaf5f31d66a3bd"),
    str(AQUA_RECEIPT): (4_712, "1b880a85bc60699a32549e41bf4a13c1f6c65ffcf599891010288c6ea4a5de40"),
    str(KLT_FEATURES): (37_403_698, "0779bb8a71e4d81ddf02ba933b7428e548534ab580fd4483754f08e26e9bbeb6"),
    str(AQUA_FEATURES): (37_403_698, "0779bb8a71e4d81ddf02ba933b7428e548534ab580fd4483754f08e26e9bbeb6"),
    str(AQUA_METRICS): (1_098_581, "9ec2110f6806aeeb158157c1efb7e2a18c170b30eb00fda020bdef1bce5862a0"),
    str(EVALUATOR): (5_447, "3c455299b23157cc749b474b9460ca4a408b3bee516e9d1bf2109f253cf89f91"),
    str(EVALUATOR_BASE): (27_933, "ab6f2b5c1a10a41463657edee2724c022fc0248dc885096acb336e602384c110"),
    str(EVALUATOR_CORE): (27_945, "aa9ac4da81df7298d1f1c369548ca98a57235916004337cad66f4cf331560635"),
    str(HFNET_CONFIG): (415, "a76c728b31d47c3a87f54c465fb581007ed2da2b7d7d84df81dbde93e9a886c1"),
    str(EVO_APE): (213, "6bee25dc5bfdab0ead8988ab4014a72511339e94697ec61699f66f68f5f24d15"),
    str(EVO_RPE): (213, "9e07d0bd4566aa680d5e39e58589176a286f4f8a22ba9107a5834ddb278e2bd1"),
    str(TRAJECTORIES[ARM_ORDER[0]]): (127_225, "932025ff3a818fcad2880e88c8385022019b4f3d11df8fff8fc0bb7289a9a35a"),
    str(TRAJECTORIES[ARM_ORDER[1]]): (124_824, "c4bb08ab3cea8fd509539beb40b36f9c6764f788fcc195c70020dd2c253fc93b"),
    str(TRAJECTORIES[ARM_ORDER[2]]): (124_964, "9535c953fe543201cfd01dc1cd631daa50687fa9e89905b609642fefc1d5d6c0"),
    str(CONFIGS[ARM_ORDER[0]]): (980, "8e0860e33b8b017c32a6f203c05a03ce2081cbcb3083fc34b0a0081ef5c7f077"),
    str(CONFIGS[ARM_ORDER[1]]): (945, "8a00f216e306d3373b7b815b4123934cd62e1f6df106b5ee03eb03d9236026c4"),
    str(CONFIGS[ARM_ORDER[2]]): (1_008, "32dd52cac1ff326240e7ecbafd1394e5858f8eae0e54e64eae25b3dce9257b9c"),
}

CANONICAL_NAME = "hfnet_world_T_body_source_stamp_canonical_v1.csv"
CANONICAL_EXPECTED = (
    259_978,
    "a76d3670dec7434494e94dc9a823520e2a9fb3d3d61d578d62909572b67b77fd",
)


class DiagnosticError(RuntimeError):
    pass


def require(condition: bool, code: str) -> None:
    if not condition:
        raise DiagnosticError(code)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def identity(path: Path) -> dict[str, Any]:
    return {"path": str(path), "size_bytes": path.stat().st_size, "sha256": sha256(path)}


def read_json(path: Path) -> Any:
    with path.open(encoding="utf-8") as stream:
        return json.load(stream)


def write_json(path: Path, value: Any) -> None:
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False) + "\n",
        encoding="utf-8",
    )


def verify_inputs() -> dict[str, Any]:
    require(PROTOCOL.is_file() and not PROTOCOL.is_symlink(), "PROTOCOL_NOT_REGULAR")
    claims: dict[str, Any] = {}
    for raw_path, expected in EXPECTED_IDENTITIES.items():
        path = Path(raw_path)
        require(path.is_file() and not path.is_symlink(), f"INPUT_NOT_REGULAR:{path}")
        actual = identity(path)
        require((actual["size_bytes"], actual["sha256"]) == expected, f"INPUT_IDENTITY_DRIFT:{path}")
        claims[raw_path] = actual

    vanilla = read_json(VANILLA_RECEIPT)
    klt = read_json(KLT_RECEIPT)
    aqua = read_json(AQUA_RECEIPT)
    require(vanilla.get("status") == "TERMINAL_PROCESS_RC0", "VANILLA_STATUS_DRIFT")
    require(vanilla.get("process_start_count") == 1 and vanilla.get("raw_return_code") == 0, "VANILLA_PROCESS_DRIFT")
    require(klt.get("status") == "TERMINAL_PROCESS_RC0_ADDITIVE_INFRASTRUCTURE_CORRECTIVE", "KLT_STATUS_DRIFT")
    require(klt.get("process_start_count") == 1 and klt.get("raw_return_code") == 0, "KLT_PROCESS_DRIFT")
    corrective = klt.get("corrective_contract") or {}
    require(corrective.get("front_end_recomputed") is False, "KLT_FRONTEND_RECOMPUTED")
    require(corrective.get("original_namespace_modified") is False, "KLT_ORIGINAL_NAMESPACE_MODIFIED")
    require(aqua.get("status") == "TERMINAL_PROCESS_RC0", "AQUA_STATUS_DRIFT")
    require(aqua.get("process_start_count") == 1 and aqua.get("raw_return_code") == 0, "AQUA_PROCESS_DRIFT")
    learned = aqua.get("learned_action_audit") or {}
    require(learned.get("full_exported_learned_observations") == 0, "AQUA_FULL_LEARNED_EXPORT_DRIFT")
    require(learned.get("score_exported_learned_observations") == 0, "AQUA_SCORE_LEARNED_EXPORT_DRIFT")
    require(learned.get("feature_payload_byte_identical_to_a06_external_klt") is True, "AQUA_KLT_PAYLOAD_DRIFT")
    require(learned.get("classification") == "NO_LEARNED_ACTION_NO_HARM_ONLY", "AQUA_CLASSIFICATION_DRIFT")
    require(claims[str(KLT_FEATURES)]["sha256"] == claims[str(AQUA_FEATURES)]["sha256"], "FEATURE_PAYLOAD_SHA_DRIFT")
    return {
        "files": claims,
        "receipt_audit": {
            "vanilla_status": vanilla["status"],
            "klt_status": klt["status"],
            "klt_original_censored_namespace_modified": corrective["original_namespace_modified"],
            "klt_frontend_recomputed": corrective["front_end_recomputed"],
            "aqua_status": aqua["status"],
        },
        "learned_action_boundary": {
            "feature_payloads_byte_identical": True,
            "shared_feature_payload_sha256": claims[str(KLT_FEATURES)]["sha256"],
            "full_exported_learned_observations": 0,
            "score_exported_learned_observations": 0,
            "classification": learned["classification"],
            "learned_benefit_attribution_permitted": False,
        },
    }


def exact_stamp(message: Any) -> int:
    stamp = message.header.stamp
    require(type(stamp.secs) is int and type(stamp.nsecs) is int, "ROS_STAMP_NOT_EXACT_INTEGERS")
    require(stamp.secs >= 0 and 0 <= stamp.nsecs < 1_000_000_000, "ROS_STAMP_RANGE")
    return stamp.secs * 1_000_000_000 + stamp.nsecs


def raw_camera_stamps() -> list[int]:
    ros_path = "/opt/ros/noetic/lib/python3/dist-packages"
    if ros_path not in sys.path:
        sys.path.insert(0, ros_path)
    import rosbag  # type: ignore

    with rosbag.Bag(str(RAW_BAG)) as bag:
        stamps = [exact_stamp(message) for _, message, _ in bag.read_messages(topics=[CAMERA_TOPIC])]
    require(len(stamps) == 2461, f"RAW_CAMERA_COUNT:{len(stamps)}")
    require(all(b > a for a, b in zip(stamps, stamps[1:])), "RAW_CAMERA_NOT_INCREASING")
    require(stamps[2210] == SCORE_START_NS, "RAW_SCORE_START_DRIFT")
    require(stamps[2460] == SCORE_END_NS, "RAW_SCORE_END_DRIFT")
    return stamps


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
    require(len(rows) == 2457, f"HFNET_ROW_COUNT:{len(rows)}")

    source_stamps = raw_camera_stamps()
    source_indices: list[int] = []
    for stamp in sealed_stamps:
        right = bisect_left(source_stamps, stamp)
        candidates = {max(0, right - 1), min(len(source_stamps) - 1, right)}
        source_indices.append(min(candidates, key=lambda index: abs(source_stamps[index] - stamp)))
    require(source_indices == list(range(4, 2461)), "HFNET_SOURCE_INDEX_MAPPING_DRIFT")
    canonical_stamps = [source_stamps[index] for index in source_indices]
    deltas = [sealed - canonical for sealed, canonical in zip(sealed_stamps, canonical_stamps)]
    require(Counter(deltas) == Counter(EXPECTED_DELTA_HISTOGRAM), "HFNET_DELTA_HISTOGRAM_DRIFT")
    require(max(abs(value) for value in deltas) == 128, "HFNET_MAX_DELTA_DRIFT")

    lines = [str(stamp) + "," + ",".join(fields[1:]) for stamp, fields in zip(canonical_stamps, rows)]
    payload = ("\n".join(lines) + "\n").encode("ascii")
    content = {"size_bytes": len(payload), "sha256": hashlib.sha256(payload).hexdigest()}
    require((content["size_bytes"], content["sha256"]) == CANONICAL_EXPECTED, "HFNET_CANONICAL_IDENTITY_DRIFT")
    original_pose_text = "\n".join(",".join(fields[1:]) for fields in rows) + "\n"
    canonical_pose_text = "\n".join(line.split(",", 1)[1] for line in lines) + "\n"
    require(original_pose_text == canonical_pose_text, "HFNET_POSE_TEXT_CHANGED")
    return payload, {
        "schema_version": "aqua-fe-a06-hfnet-source-stamp-canonicalization-harmonized-diagnostic-v1",
        "state": "PASS",
        "source": identity(HFNET_BRIDGE),
        "source_indices_inclusive": [4, 2460],
        "score_source_indices_inclusive": [2210, 2460],
        "row_count": len(rows),
        "score_row_count": 251,
        "maximum_absolute_delta_ns": 128,
        "complete_delta_histogram_ns": {str(k): v for k, v in sorted(EXPECTED_DELTA_HISTOGRAM.items())},
        "pose_field_text_unchanged": True,
        "canonical_content": content,
        "semantics": "nearest unique source-index timestamp spelling only; no pose or fitted synchronization change",
    }


def evaluator_command(output_dir: Path, canonical: Path) -> list[str]:
    command = [
        "/usr/bin/python3.8", str(EVALUATOR),
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
        "--window-start-s", "1542883422.269233600",
        "--window-end-s", "1542883434.765650624",
        "--rpe-delta-s", "1.0",
        "--min-ape-poses", "30",
        "--min-ape-span-s", "10.0",
        "--min-common-coverage", "0.70",
        "--min-rpe-pairs", "10",
        "--contrast-name", "A06_SAMEHISTORY_HARMONIZED_DIAGNOSTIC_V1_SCORE_2210_2460",
        "--output-dir", str(output_dir),
        "--run-evo",
    ])
    return command


def validate_summary(summary: Mapping[str, Any]) -> dict[str, Any]:
    require(set(summary) == {"protocol", "support", "reference", "arms"}, "SUMMARY_SCHEMA")
    protocol, support, arms = summary["protocol"], summary["support"], summary["arms"]
    require(isinstance(protocol, Mapping) and isinstance(support, Mapping) and isinstance(arms, Mapping), "SUMMARY_TYPES")
    require(protocol.get("contrast_name") == "A06_SAMEHISTORY_HARMONIZED_DIAGNOSTIC_V1_SCORE_2210_2460", "CONTRAST_DRIFT")
    require(protocol.get("body_to_camera_applied") is True, "BODY_CAMERA_NOT_APPLIED")
    require(protocol.get("rpe_semantics") == "aligned_global_frame_positional_delta", "RPE_SEMANTICS_DRIFT")
    require(set(arms) == set(ARM_ORDER), "ARM_SET_DRIFT")
    require(support.get("grid_count") == 13, f"GRID_COUNT:{support.get('grid_count')}")
    require(support.get("matched_count") == 13, f"MATCHED_COUNT:{support.get('matched_count')}")
    require(abs(float(support.get("common_coverage")) - 1.0) <= 1e-12, "COVERAGE_DRIFT")
    require(support.get("segment_count") == 1, "SEGMENT_COUNT_DRIFT")
    require(support.get("rpe_pairs") == 12, f"RPE_PAIRS:{support.get('rpe_pairs')}")
    require(support.get("ape_valid") is False, "FORMAL_APE_GATE_UNEXPECTEDLY_OPEN")
    require(support.get("rpe_valid") is True, "DESCRIPTIVE_RPE_GATE_CLOSED")
    metrics: dict[str, Any] = {}
    for name in ARM_ORDER:
        row = arms[name]
        require(row.get("matched_count") == 13 and row.get("rpe_pairs") == 12, f"ARM_SUPPORT_DRIFT:{name}")
        values: dict[str, float] = {}
        for key in ("ape_rmse_m", "ape_median_m", "ape_max_m", "rpe_rmse_m", "rpe_median_m", "rpe_max_m"):
            value = row.get(key)
            require(isinstance(value, (int, float)) and math.isfinite(value) and value >= 0, f"METRIC_INVALID:{name}:{key}")
            values[key] = float(value)
        metrics[name] = values
    return {
        "uniform_grid_count": 13,
        "uniform_common_matched_count": 13,
        "uniform_common_coverage": 1.0,
        "uniform_exact_1s_rpe_pairs": 12,
        "common_support_gate_pass": True,
        "descriptive_rpe_gate_pass": True,
        "formal_ape_gate_open": False,
        "formal_winner_permitted": False,
        "metrics_fixed_order": metrics,
    }


def report_markdown(adjudication: Mapping[str, Any]) -> str:
    lines = [
        "# A06 same-history harmonized common-support diagnostic v1", "",
        "Status: `DEVELOPMENT_ONLY_HARMONIZED_DIAGNOSTIC`.", "",
        "No SLAM system was rerun. The existing four trajectories were evaluated with the same epoch-ns, fixed-scale SE(3), common-mask and evo protocol used for A10.", "",
        "| Fixed-order system | Descriptive SE(3) APE RMSE / median / max (m) | Descriptive 1 s RPE RMSE / median / max (m) |",
        "|---|---:|---:|",
    ]
    for name in ARM_ORDER:
        row = adjudication["metrics_fixed_order"][name]
        lines.append(
            f"| `{name}` | {row['ape_rmse_m']:.6f} / {row['ape_median_m']:.6f} / {row['ape_max_m']:.6f} | "
            f"{row['rpe_rmse_m']:.6f} / {row['rpe_median_m']:.6f} / {row['rpe_max_m']:.6f} |"
        )
    lines.extend([
        "", "## Support", "",
        "- Uniform common support: 13/13 in one continuous segment.",
        "- Exact 1 s RPE pairs: 12.",
        "- Formal APE gate: closed because 13 native proxy rows are below the frozen 30-pose minimum.",
        "", "## Interpretation boundary", "",
        "This is one selected development window with one existing trajectory per method and a same-image COLMAP/depth-scale proxy. No confidence interval, significance test, ranking, winner, superiority or primary-paper claim is authorized. AQUA-FE and KLT feature payloads are byte-identical and AQUA-FE exported zero learned observations, so this window supports no-harm only and cannot support learned-benefit attribution.", "",
    ])
    return "\n".join(lines)


def stats_markdown() -> str:
    return "\n".join([
        "# Statistical appendix", "",
        "- Unit of analysis: one preselected A06 score window; independent trajectory count per method is `n=1`.",
        "- The 13 correlated time-grid samples are not treated as independent replicates.",
        "- Uncertainty interval, significance test, effect size and multiple-comparison correction: not applicable and not performed.",
        "- Common support: `13/13`; exact 1 s RPE pairs: `12`.",
        "- Alignment: fixed-scale SE(3), no Sim(3) scale fitting.",
        "- Reference: same-image COLMAP/depth-scale proxy, not independent ground truth.",
        "- Formal APE gate: closed by the preregistered 30-pose minimum.", "",
    ])


def run() -> dict[str, Any]:
    require(not OUTPUT.exists() and not OUTPUT.is_symlink(), "OUTPUT_ALREADY_EXISTS")
    preflight = verify_inputs()
    payload, canonical_audit = canonical_hfnet_payload()
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".a06_harmonized_diagnostic_v1.", dir=str(OUTPUT.parent)))
    try:
        canonical_path = staging / CANONICAL_NAME
        canonical_path.write_bytes(payload)
        write_json(staging / f"{CANONICAL_NAME}.manifest.json", canonical_audit)
        evaluator_dir = staging / "common_support"
        command = evaluator_command(evaluator_dir, canonical_path)
        process = subprocess.run(
            command, cwd=str(ROOT), text=True, stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT, timeout=180, check=False,
            env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        )
        write_json(staging / "evaluator_process_receipt.json", {
            "schema_version": "aqua-fe-a06-harmonized-diagnostic-evaluator-process-receipt-v1",
            "command": command, "raw_return_code": process.returncode,
            "timed_out": False, "stdout": process.stdout,
        })
        require(process.returncode == 0, f"EVALUATOR_RC:{process.returncode}")
        summary_path = evaluator_dir / "common_support_summary.json"
        require(summary_path.is_file(), "COMMON_SUPPORT_SUMMARY_MISSING")
        summary = read_json(summary_path)
        adjudication = validate_summary(summary)
        evo_path = evaluator_dir / "evo_crosscheck.json"
        require(evo_path.is_file(), "EVO_CROSSCHECK_MISSING")
        evo = read_json(evo_path)
        require(evo.get("evo_version") == "1.31.1", "EVO_VERSION_DRIFT")
        require(set((evo.get("arms") or {})) == set(ARM_ORDER), "EVO_ARM_SET_DRIFT")
        for name in ARM_ORDER:
            row = evo["arms"][name]
            require(row.get("rpe_pair_count") == 12, f"EVO_RPE_PAIR_DRIFT:{name}")
            require(float(row.get("ape_abs_diff_m")) <= 1e-5, f"EVO_APE_CROSSCHECK_DRIFT:{name}")
            require(float(row.get("rpe_abs_diff_m")) <= 1e-5, f"EVO_RPE_CROSSCHECK_DRIFT:{name}")

        write_json(staging / "input_manifest.json", {
            "schema_version": "aqua-fe-a06-harmonized-diagnostic-input-manifest-v1",
            "status": "PASS", "protocol": identity(PROTOCOL),
            "runner": identity(Path(__file__)), **preflight,
            "hfnet_canonicalization": canonical_audit,
            "fixed_arm_order": list(ARM_ORDER),
        })
        bundle = {
            "schema_version": "aqua-fe-a06-samehistory-harmonized-common-support-diagnostic-v1",
            "status": "DEVELOPMENT_ONLY_HARMONIZED_DIAGNOSTIC",
            "generated_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "slams_or_backends_executed": False,
            "receipt_audit": preflight["receipt_audit"],
            "learned_action_boundary": preflight["learned_action_boundary"],
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
                "learned_benefit_attribution_permitted": False,
                "primary_paper_evidence_permitted": False,
            },
        }
        write_json(staging / "analysis_bundle.json", bundle)
        (staging / "analysis-report.md").write_text(report_markdown(adjudication), encoding="utf-8")
        (staging / "stats-appendix.md").write_text(stats_markdown(), encoding="utf-8")
        (staging / "figure-catalog.md").write_text(
            "# Figure catalog\n\nNo figure is generated: four exact fixed-order rows are clearer than an uncertainty-free chart.\n",
            encoding="utf-8",
        )
        files = {}
        for path in sorted(staging.rglob("*")):
            if path.is_file() and path.name != "result_manifest.json":
                files[str(path.relative_to(staging))] = {
                    "size_bytes": path.stat().st_size, "sha256": sha256(path),
                }
        write_json(staging / "result_manifest.json", {
            "schema_version": "aqua-fe-a06-harmonized-diagnostic-result-manifest-v1",
            "status": "COMPLETE", "files": files,
        })
        require(not OUTPUT.exists() and not OUTPUT.is_symlink(), "OUTPUT_APPEARED_DURING_RUN")
        staging.rename(OUTPUT)
        return {"status": bundle["status"], "output": str(OUTPUT), "support": adjudication}
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
