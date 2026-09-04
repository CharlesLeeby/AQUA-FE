#!/usr/bin/env python3
"""Exactly-once four-arm A06 common-support evaluation for lifecycle rearm v1."""

from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import time
from typing import Any, Iterable, Mapping


ROOT = Path("/home/ma/AQUA-FE_WS")
PROTOCOL = ROOT / "papers/a06_lifecycle_rearmed_fourarm_common_support_v1_protocol.md"
RUNNER = Path(__file__).resolve()
OUTPUT = Path(
    "/mnt/data/AQUA-FE_WS/experiments/"
    "a06_lifecycle_rearmed_fourarm_common_support_v1"
)
STAGE = OUTPUT.parent / ".a06_lifecycle_rearmed_fourarm_common_support_v1.stage_v1"
FAILURE = OUTPUT.parent / "a06_lifecycle_rearmed_fourarm_common_support_v1_failed_v1"
GLOBAL_LOCK = OUTPUT.parent / ".a06_lifecycle_rearmed_fourarm_common_support_v1.flock"

RAW_BAG = Path(
    "/mnt/data/AQUA-FE_WS/experiments/samehistory_system_v1/raw/"
    "archaeo06_0000_2460.bag"
)
BACKEND_TERMINAL = Path(
    "/mnt/data/AQUA-FE_WS/experiments/a06_lifecycle_rearmed_backend_pair_v1/"
    "terminal_backend_pair_receipt_v1.json"
)
KLT_RECEIPT = Path(
    "/mnt/data/AQUA-FE_WS/experiments/a06_lifecycle_rearmed_backend_pair_v1/"
    "klt_external_feature_context_fresh_pair_v1/formal_run_receipt_v1.json"
)
AQUA_RECEIPT = Path(
    "/mnt/data/AQUA-FE_WS/experiments/a06_lifecycle_rearmed_backend_pair_v1/"
    "aquafe_lifecycle_rearmed_external_feature_context_fresh_pair_v1/"
    "formal_run_receipt_v1.json"
)
VANILLA_RECEIPT = Path(
    "/mnt/data/AQUA-FE_WS/experiments/samehistory_system_v1/runs/a06/"
    "vanilla_origin/formal_run_receipt_v1.json"
)
HFNET_MANIFEST = Path(
    "/mnt/data/AQUA-FE_WS/experiments/a06_samehistory_harmonized_diagnostic_v1/"
    "hfnet_world_T_body_source_stamp_canonical_v1.csv.manifest.json"
)

EVALUATOR = ROOT / "scripts/evaluate_vins_common_support_epoch_v2.py"
EVALUATOR_BASE = ROOT / "scripts/evaluate_vins_common_support.py"
EVALUATOR_CORE = ROOT / "scripts/trajectory_eval_core.py"
EVO_APE = Path("/home/ma/.local/bin/evo_ape")
EVO_RPE = Path("/home/ma/.local/bin/evo_rpe")

START_NS = 1_542_883_404_763_902_848
END_NS = 1_542_883_434_765_650_624
REFERENCE_TOPIC = "/aqualoc/colmap_gt"
CONTRAST = "A06_LIFECYCLE_REARMED_FOURARM_COMMON_SUPPORT_V1_SCORE_1860_2460"

ARM_ORDER = (
    "VANILLA_ORIGIN_NATIVE_IMAGE_CONTEXT",
    "EXTERNAL_KLT_FRESH_PAIRED",
    "AQUAFE_XFEAT_LIFECYCLE_REARMED_FRESH",
    "HFNET_SLAM_NATURAL_HISTORY",
)
TRAJECTORIES = {
    ARM_ORDER[0]: Path(
        "/mnt/data/AQUA-FE_WS/experiments/samehistory_system_v1/runs/a06/"
        "vanilla_origin/vins_output/vio.csv"
    ),
    ARM_ORDER[1]: Path(
        "/mnt/data/AQUA-FE_WS/experiments/a06_lifecycle_rearmed_backend_pair_v1/"
        "klt_external_feature_context_fresh_pair_v1/vins_output/vio.csv"
    ),
    ARM_ORDER[2]: Path(
        "/mnt/data/AQUA-FE_WS/experiments/a06_lifecycle_rearmed_backend_pair_v1/"
        "aquafe_lifecycle_rearmed_external_feature_context_fresh_pair_v1/"
        "vins_output/vio.csv"
    ),
    ARM_ORDER[3]: Path(
        "/mnt/data/AQUA-FE_WS/experiments/a06_samehistory_harmonized_diagnostic_v1/"
        "hfnet_world_T_body_source_stamp_canonical_v1.csv"
    ),
}
CONFIGS = {
    ARM_ORDER[0]: Path(
        "/mnt/data/AQUA-FE_WS/experiments/samehistory_system_v1/runs/a06/"
        "vanilla_origin/vins_aqualoc_archaeo_origin.yaml"
    ),
    ARM_ORDER[1]: Path(
        "/mnt/data/AQUA-FE_WS/experiments/a06_lifecycle_rearmed_backend_pair_v1/"
        "klt_external_feature_context_fresh_pair_v1/vins_aqualoc_archaeo_external.yaml"
    ),
    ARM_ORDER[2]: Path(
        "/mnt/data/AQUA-FE_WS/experiments/a06_lifecycle_rearmed_backend_pair_v1/"
        "aquafe_lifecycle_rearmed_external_feature_context_fresh_pair_v1/"
        "vins_aqualoc_archaeo_external.yaml"
    ),
    ARM_ORDER[3]: ROOT / "configs/published_baselines/hfnet_aqualoc_a02_body_T_cam0_v1.yaml",
}

EXPECTED_IDENTITIES = {
    RAW_BAG: (573_420_704, "22cc3cff28dabc34de04c870eed5180ab76832c1f3c912da62d0268e9acb2e9a"),
    TRAJECTORIES[ARM_ORDER[0]]: (127_225, "932025ff3a818fcad2880e88c8385022019b4f3d11df8fff8fc0bb7289a9a35a"),
    TRAJECTORIES[ARM_ORDER[1]]: (124_827, "69ddcbf4456cc0d8dcb4f68d57392bb4cbadcbf8cf3416d294b54036e403032a"),
    TRAJECTORIES[ARM_ORDER[2]]: (124_820, "96de2348b09c25e0c546ae6c2fb135c9da9dd9e7d40335524d2ba16e8150311c"),
    TRAJECTORIES[ARM_ORDER[3]]: (259_978, "a76d3670dec7434494e94dc9a823520e2a9fb3d3d61d578d62909572b67b77fd"),
    CONFIGS[ARM_ORDER[0]]: (980, "8e0860e33b8b017c32a6f203c05a03ce2081cbcb3083fc34b0a0081ef5c7f077"),
    CONFIGS[ARM_ORDER[1]]: (964, "8ec141862e362827c4c3f5f9305b6084dbdb0ffe9b89d414f821230205de393c"),
    CONFIGS[ARM_ORDER[2]]: (985, "08ea561609fd857ad7682bc38b3044dcab97834dbc865d4da17c3aa3e27d2574"),
    CONFIGS[ARM_ORDER[3]]: (415, "a76c728b31d47c3a87f54c465fb581007ed2da2b7d7d84df81dbde93e9a886c1"),
    BACKEND_TERMINAL: (2_885, "7119ba09525befcaae1398a08a521fa84a985b6fdd5d5d45b2fb1c011c6ac688"),
    KLT_RECEIPT: (13_076, "34e9894cf6bfc9dce232926b4d589dde877bfa132c39906bec36d737d951621a"),
    AQUA_RECEIPT: (13_451, "decbc0c700b764175654397a860e5121eeed1227395ac7168521a301c8526136"),
    VANILLA_RECEIPT: (2_832, "b26ff3648a92379e1120845a2a9538fc72d6dc85c85bf547b5aa36ae58382079"),
    HFNET_MANIFEST: (1_078, "4296b528c8ac93474b00ce01bf917843bf924986492e61bb0fc34a93046865a2"),
    EVALUATOR: (5_447, "3c455299b23157cc749b474b9460ca4a408b3bee516e9d1bf2109f253cf89f91"),
    EVALUATOR_BASE: (27_933, "ab6f2b5c1a10a41463657edee2724c022fc0248dc885096acb336e602384c110"),
    EVALUATOR_CORE: (27_945, "aa9ac4da81df7298d1f1c369548ca98a57235916004337cad66f4cf331560635"),
    EVO_APE: (213, "6bee25dc5bfdab0ead8988ab4014a72511339e94697ec61699f66f68f5f24d15"),
    EVO_RPE: (213, "9e07d0bd4566aa680d5e39e58589176a286f4f8a22ba9107a5834ddb278e2bd1"),
}


class AnalysisError(RuntimeError):
    pass


def require(condition: bool, code: str) -> None:
    if not condition:
        raise AnalysisError(code)


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def identity(path: Path) -> dict[str, Any]:
    return {"path": str(path), "size_bytes": path.stat().st_size, "sha256": sha256(path)}


def require_identity(path: Path, expected: tuple[int, str]) -> dict[str, Any]:
    require(path.is_file() and not path.is_symlink(), f"INPUT_NOT_REGULAR:{path}")
    actual = identity(path)
    require((actual["size_bytes"], actual["sha256"]) == expected, f"INPUT_DRIFT:{path}")
    return actual


def input_identities() -> dict[str, Any]:
    values = {
        str(path): require_identity(path, expected)
        for path, expected in EXPECTED_IDENTITIES.items()
    }
    for path in (PROTOCOL, RUNNER):
        require(path.is_file() and not path.is_symlink(), f"CONTROL_NOT_REGULAR:{path}")
        values[str(path)] = identity(path)
    return values


def refresh(previous: dict[str, Any]) -> dict[str, Any]:
    return {raw_path: identity(Path(raw_path)) for raw_path in previous}


def read_json(path: Path) -> Any:
    with path.open(encoding="utf-8") as stream:
        return json.load(stream)


def write_json(path: Path, value: Any) -> None:
    require(not path.exists() and not path.is_symlink(), f"REFUSE_OVERWRITE:{path}")
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False) + "\n",
        encoding="utf-8",
    )


def write_text(path: Path, value: str) -> None:
    require(not path.exists() and not path.is_symlink(), f"REFUSE_OVERWRITE:{path}")
    path.write_text(value.rstrip() + "\n", encoding="utf-8")


def backend_authority() -> dict[str, Any]:
    terminal = read_json(BACKEND_TERMINAL)
    require(
        terminal.get("status") == "PASS_PAIRED_BACKENDS_ELIGIBLE_FOR_FIXED_EVALUATION",
        "BACKEND_TERMINAL_STATUS",
    )
    require(
        (terminal.get("decision") or {}).get("fixed_common_support_evaluation_may_run") is True,
        "BACKEND_EVALUATION_AUTHORITY",
    )
    require(
        (terminal.get("decision") or {}).get("accuracy_evaluator_started") is False,
        "BACKEND_PREMATURE_EVALUATOR",
    )
    require(
        terminal.get("arm_order") == [
            "klt_external_feature_context_fresh_pair_v1",
            "aquafe_lifecycle_rearmed_external_feature_context_fresh_pair_v1",
        ],
        "BACKEND_ARM_ORDER",
    )
    for receipt_path, arm in (
        (KLT_RECEIPT, "klt_external_feature_context_fresh_pair_v1"),
        (AQUA_RECEIPT, "aquafe_lifecycle_rearmed_external_feature_context_fresh_pair_v1"),
    ):
        receipt = read_json(receipt_path)
        require(receipt.get("status") == "PASS_BACKEND_ARM_ACCEPTED", f"ARM_RECEIPT_STATUS:{arm}")
        require(receipt.get("arm") == arm, f"ARM_RECEIPT_ID:{arm}")
        require((receipt.get("claim_boundary") or {}).get("accuracy_evaluator_started") is False, f"ARM_EVALUATOR:{arm}")
    vanilla = read_json(VANILLA_RECEIPT)
    require(vanilla.get("status") == "TERMINAL_PROCESS_RC0", "VANILLA_STATUS")
    require(vanilla.get("process_start_count") == 1 and vanilla.get("retry_count") == 0, "VANILLA_PROCESS")
    hfnet = read_json(HFNET_MANIFEST)
    require(hfnet.get("state") == "PASS", "HFNET_MANIFEST_STATE")
    require((hfnet.get("canonical_content") or {}).get("sha256") == EXPECTED_IDENTITIES[TRAJECTORIES[ARM_ORDER[3]]][1], "HFNET_CANONICAL_BINDING")
    return {
        "backend_terminal_status": terminal["status"],
        "paired_arm_order": terminal["arm_order"],
        "accuracy_evaluator_started_before_this_run": False,
        "vanilla_context_status": vanilla["status"],
        "hfnet_canonical_state": hfnet["state"],
    }


def native_gt_contract() -> dict[str, Any]:
    ros_path = "/opt/ros/noetic/lib/python3/dist-packages"
    if ros_path not in sys.path:
        sys.path.insert(0, ros_path)
    import rosbag  # type: ignore

    all_stamps: list[int] = []
    with rosbag.Bag(str(RAW_BAG), "r") as bag:
        for _, message, _ in bag.read_messages(topics=[REFERENCE_TOPIC]):
            stamp = message.header.stamp.secs * 1_000_000_000 + message.header.stamp.nsecs
            all_stamps.append(stamp)
    require(len(all_stamps) == 120, f"RAW_GT_TOTAL:{len(all_stamps)}")
    inside = [stamp for stamp in all_stamps if START_NS <= stamp <= END_NS]
    require(len(inside) == 30, f"NATIVE_GT_WINDOW_COUNT:{len(inside)}")
    return {
        "topic": REFERENCE_TOPIC,
        "full_messages": len(all_stamps),
        "window_native_messages": len(inside),
        "window_timestamp_ns_inclusive": [START_NS, END_NS],
    }


def evaluator_command(output_dir: Path) -> list[str]:
    command = [
        "/usr/bin/python3.8", str(EVALUATOR),
        "--reference-bag", str(RAW_BAG),
        "--reference-topic", REFERENCE_TOPIC,
    ]
    for name in ARM_ORDER:
        command.extend(["--arm", f"{name}={TRAJECTORIES[name]}"])
    for name in ARM_ORDER:
        command.extend(["--arm-config", f"{name}={CONFIGS[name]}"])
    for name in ARM_ORDER:
        command.extend(["--arm-time-offset-s", f"{name}=0"])
    command.extend([
        "--reference-time-offset-s", "0",
        "--nominal-reference-rate-hz", "1.0",
        "--nominal-estimate-rate-hz", "10.0",
        "--evaluation-rate-hz", "1.0",
        "--max-reference-gap-s", "2.5",
        "--max-estimate-gap-s", "0.25",
        "--window-start-s", "1542883404.763902848",
        "--window-end-s", "1542883434.765650624",
        "--rpe-delta-s", "1.0",
        "--min-ape-poses", "30",
        "--min-ape-span-s", "10.0",
        "--min-common-coverage", "0.70",
        "--min-rpe-pairs", "10",
        "--contrast-name", CONTRAST,
        "--output-dir", str(output_dir),
        "--run-evo",
    ])
    return command


def validate_summary(summary: Mapping[str, Any]) -> dict[str, Any]:
    require(set(summary) == {"protocol", "support", "reference", "arms"}, "SUMMARY_SCHEMA")
    protocol = summary["protocol"]
    support = summary["support"]
    arms = summary["arms"]
    require(protocol.get("contrast_name") == CONTRAST, "CONTRAST_DRIFT")
    require(protocol.get("body_to_camera_applied") is True, "BODY_CAMERA_NOT_APPLIED")
    require(protocol.get("rpe_semantics") == "aligned_global_frame_positional_delta", "RPE_SEMANTICS")
    require(protocol.get("reference_time_offset_s") == 0.0, "REFERENCE_OFFSET")
    require(set(protocol.get("arm_time_offsets_s") or {}) == set(ARM_ORDER), "ARM_OFFSET_SET")
    require(all(value == 0.0 for value in protocol["arm_time_offsets_s"].values()), "ARM_OFFSET_VALUE")
    require(set(arms) == set(ARM_ORDER), "ARM_SET")
    require(support.get("grid_count") == 31, f"GRID_COUNT:{support.get('grid_count')}")
    require(support.get("matched_count") == 30, f"MATCHED_COUNT:{support.get('matched_count')}")
    require(abs(float(support.get("common_coverage")) - 30.0 / 31.0) <= 1e-12, "COMMON_COVERAGE")
    require(abs(float(support.get("common_span_s")) - 29.0) <= 1e-9, "COMMON_SPAN")
    require(support.get("segment_count") == 1, "SEGMENT_COUNT")
    require(support.get("rpe_pairs") == 29, f"RPE_PAIRS:{support.get('rpe_pairs')}")
    require(support.get("ape_valid") is True, "APE_GATE_CLOSED")
    require(support.get("rpe_valid") is True, "RPE_GATE_CLOSED")
    require(summary["reference"].get("valid_grid_count") == 31, "REFERENCE_GRID_SUPPORT")
    metrics: dict[str, dict[str, float]] = {}
    for name in ARM_ORDER:
        row = arms[name]
        require(row.get("matched_count") == 30, f"ARM_MATCHED:{name}")
        require(row.get("rpe_pairs") == 29, f"ARM_RPE_PAIRS:{name}")
        values: dict[str, float] = {}
        for key in (
            "ape_rmse_m", "ape_median_m", "ape_max_m",
            "rpe_rmse_m", "rpe_median_m", "rpe_max_m",
        ):
            value = row.get(key)
            require(isinstance(value, (int, float)) and math.isfinite(value) and value >= 0, f"METRIC:{name}:{key}")
            values[key] = float(value)
        metrics[name] = values
    klt = metrics[ARM_ORDER[1]]
    aqua = metrics[ARM_ORDER[2]]
    paired: dict[str, Any] = {}
    for key in ("ape_rmse_m", "rpe_rmse_m"):
        delta = aqua[key] - klt[key]
        paired[key] = {
            "klt": klt[key],
            "aquafe": aqua[key],
            "aquafe_minus_klt_m": delta,
            "aquafe_minus_klt_percent_of_klt": 100.0 * delta / klt[key] if klt[key] else None,
        }
    return {
        "status": "PASS_FIXED_COMMON_SUPPORT_GATES",
        "support": {
            "native_gt_messages": 30,
            "grid_count": 31,
            "matched_count": 30,
            "common_coverage": 30.0 / 31.0,
            "common_span_s": 29.0,
            "segment_count": 1,
            "rpe_pairs": 29,
            "ape_valid": True,
            "rpe_valid": True,
        },
        "metrics_fixed_order": metrics,
        "primary_paired_contrast": paired,
    }


def validate_evo(path: Path) -> dict[str, Any]:
    evo = read_json(path)
    require(evo.get("evo_version") == "1.31.1", "EVO_VERSION")
    require(evo.get("rpe_delta_frames") == 1, "EVO_RPE_DELTA")
    require(set(evo.get("arms") or {}) == set(ARM_ORDER), "EVO_ARM_SET")
    maximum = 0.0
    for name in ARM_ORDER:
        row = evo["arms"][name]
        require(row.get("rpe_pair_count") == 29, f"EVO_RPE_PAIRS:{name}")
        for key in ("ape_abs_diff_m", "rpe_abs_diff_m"):
            value = float(row[key])
            require(math.isfinite(value) and value <= 1e-5, f"EVO_TOLERANCE:{name}:{key}:{value}")
            maximum = max(maximum, value)
    return {"version": "1.31.1", "maximum_rmse_abs_diff_m": maximum, "tolerance_m": 1e-5}


def report_markdown(result: Mapping[str, Any]) -> str:
    lines = [
        "# A06 lifecycle-rearmed four-arm common-support evaluation v1", "",
        "Status: `DEVELOPMENT_ONLY_ACTION_GATED_SINGLE_WINDOW`.", "",
        "| Fixed-order arm | APE RMSE / median / max (m) | 1 s RPE RMSE / median / max (m) |",
        "|---|---:|---:|",
    ]
    for name in ARM_ORDER:
        row = result["metrics_fixed_order"][name]
        lines.append(
            f"| `{name}` | {row['ape_rmse_m']:.6f} / {row['ape_median_m']:.6f} / {row['ape_max_m']:.6f} | "
            f"{row['rpe_rmse_m']:.6f} / {row['rpe_median_m']:.6f} / {row['rpe_max_m']:.6f} |"
        )
    ape = result["primary_paired_contrast"]["ape_rmse_m"]
    rpe = result["primary_paired_contrast"]["rpe_rmse_m"]
    lines.extend([
        "", "## Primary controlled pair", "",
        f"- APE RMSE, AQUA minus KLT: `{ape['aquafe_minus_klt_m']:+.9f} m` "
        f"(`{ape['aquafe_minus_klt_percent_of_klt']:+.4f}%` of KLT).",
        f"- RPE RMSE, AQUA minus KLT: `{rpe['aquafe_minus_klt_m']:+.9f} m` "
        f"(`{rpe['aquafe_minus_klt_percent_of_klt']:+.4f}%` of KLT).",
        "", "## Support and interpretation", "",
        "- Native proxy messages: 30; joint common grid: 30/31; one 29 s segment; exact 1 s RPE pairs: 29.",
        "- Both APE and RPE support gates are open; evo 1.31.1 independently cross-checks every arm.",
        "- KLT versus lifecycle-AQUA is the controlled same-backend contrast. Vanilla and HFNet are descriptive context arms with different frontend/backend contracts.",
        "- This is one development-exposed A06 window with n=1 trajectory per arm and a same-image COLMAP/depth-scale proxy. No ranking, significance, uncertainty, general superiority, or final-online identity claim is authorized.",
    ])
    return "\n".join(lines)


def stats_markdown() -> str:
    return "\n".join([
        "# Statistical appendix", "",
        "- Independent trajectory count per method: `n=1`.",
        "- The 30 correlated 1 Hz common samples and 29 overlapping 1 s deltas are not independent replicates.",
        "- Confidence intervals, significance tests, standardized effect sizes, and multiple-comparison correction: not applicable and not performed.",
        "- Alignment: per-arm proper fixed-scale SE(3); no Sim(3) or fitted time offset.",
        "- Reference: same-image COLMAP/depth-scale proxy, not independent ground truth.",
        "- The reported paired difference is descriptive for this predeclared development window only.",
    ])


def terminate_group(process: subprocess.Popen[Any]) -> None:
    if process.poll() is not None:
        return
    for sig, delay in ((signal.SIGINT, 10), (signal.SIGTERM, 5), (signal.SIGKILL, 2)):
        try:
            os.killpg(process.pid, sig)
        except ProcessLookupError:
            return
        try:
            process.wait(timeout=delay)
            return
        except subprocess.TimeoutExpired:
            continue


def run_child(command: list[str], log_path: Path) -> tuple[int, float]:
    started = time.monotonic()
    environment = {
        **os.environ,
        "PATH": f"/home/ma/.local/bin:{os.environ.get('PATH', '')}",
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONHASHSEED": "0",
    }
    with log_path.open("xb") as log:
        process = subprocess.Popen(
            command, cwd=str(ROOT), env=environment, stdout=log,
            stderr=subprocess.STDOUT, start_new_session=True,
        )
        try:
            return_code = process.wait(timeout=300)
        except BaseException:
            terminate_group(process)
            raise
    return return_code, time.monotonic() - started


def output_identities(directory: Path, names: Iterable[str]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for name in names:
        path = directory / name
        require(path.is_file() and not path.is_symlink(), f"OUTPUT_MISSING:{path}")
        result[name] = identity(path)
    return result


def preflight() -> dict[str, Any]:
    for path, code in ((OUTPUT, "OUTPUT"), (STAGE, "STAGE"), (FAILURE, "FAILURE")):
        require(not path.exists() and not path.is_symlink(), f"{code}_EXISTS")
    inputs = input_identities()
    authority = backend_authority()
    native = native_gt_contract()
    return {
        "status": "READY_EXACTLY_ONCE_COMMON_SUPPORT_EVALUATION",
        "inputs": inputs,
        "backend_authority": authority,
        "native_gt_contract": native,
        "arm_order": list(ARM_ORDER),
        "command": evaluator_command(STAGE / "common_support"),
        "no_retry": True,
    }


def stage_failure(error: BaseException) -> None:
    if not STAGE.is_dir() or STAGE.is_symlink() or FAILURE.exists() or FAILURE.is_symlink():
        return
    try:
        write_json(STAGE / "failure_receipt_v1.json", {
            "status": "FAILED_NO_RETRY",
            "error_type": type(error).__name__,
            "error": str(error),
            "recorded_at_utc": now(),
        })
        STAGE.rename(FAILURE)
    except OSError:
        pass


def execute() -> dict[str, Any]:
    ready = preflight()
    GLOBAL_LOCK.touch(exist_ok=True)
    with GLOBAL_LOCK.open("r+") as lock_stream:
        fcntl.flock(lock_stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        STAGE.mkdir(mode=0o755)
        inputs_before = input_identities()
        command = evaluator_command(STAGE / "common_support")
        claim = {
            "schema_version": "a06-lifecycle-rearmed-analysis-start-claim-v1",
            "status": "CLAIMED_BEFORE_SINGLE_POPEN",
            "created_at_utc": now(),
            "command": command,
            "inputs": inputs_before,
            "backend_authority": ready["backend_authority"],
            "native_gt_contract": ready["native_gt_contract"],
            "no_retry": True,
        }
        write_json(STAGE / "process_start_claim_v1.json", claim)
        started = now()
        try:
            return_code, wall_time = run_child(command, STAGE / "evaluator_process.log")
            require(return_code == 0, f"EVALUATOR_RETURN_CODE:{return_code}")
            summary_path = STAGE / "common_support/common_support_summary.json"
            evo_path = STAGE / "common_support/evo_crosscheck.json"
            require(summary_path.is_file(), "SUMMARY_MISSING")
            require(evo_path.is_file(), "EVO_MISSING")
            adjudication = validate_summary(read_json(summary_path))
            adjudication["evo_crosscheck"] = validate_evo(evo_path)
            adjudication["claim_boundary"] = {
                "development_exposed_single_window": True,
                "primary_controlled_pair": [ARM_ORDER[1], ARM_ORDER[2]],
                "context_arms": [ARM_ORDER[0], ARM_ORDER[3]],
                "ranking_or_superiority_permitted": False,
                "statistical_inference_permitted": False,
            }
            write_json(STAGE / "adjudication_v1.json", adjudication)
            write_text(STAGE / "analysis-report.md", report_markdown(adjudication))
            write_text(STAGE / "statistical-appendix.md", stats_markdown())
            inputs_after = refresh(inputs_before)
            require(
                {key: (value["size_bytes"], value["sha256"]) for key, value in inputs_before.items()}
                == {key: (value["size_bytes"], value["sha256"]) for key, value in inputs_after.items()},
                "INPUT_IDENTITY_CHANGED",
            )
            outputs = output_identities(STAGE, (
                "process_start_claim_v1.json", "evaluator_process.log",
                "common_support/common_support_summary.json",
                "common_support/common_support_metrics.csv",
                "common_support/common_grid_audit.csv",
                "common_support/evo_crosscheck.json",
                "adjudication_v1.json", "analysis-report.md", "statistical-appendix.md",
            ))
            receipt = {
                "schema_version": "a06-lifecycle-rearmed-fourarm-analysis-receipt-v1",
                "status": "COMPLETE_FIXED_COMMON_SUPPORT_EVALUATION",
                "started_at_utc": started,
                "ended_at_utc": now(),
                "terminal_process": {
                    "return_code": return_code,
                    "single_popen": True,
                    "wall_time_seconds": wall_time,
                },
                "command": command,
                "inputs_before": inputs_before,
                "inputs_after": inputs_after,
                "outputs": outputs,
                "adjudication": adjudication,
                "no_retry": True,
            }
            write_json(STAGE / "terminal_analysis_receipt_v1.json", receipt)
            STAGE.rename(OUTPUT)
            return {
                "status": receipt["status"],
                "output_dir": str(OUTPUT),
                "terminal_receipt": identity(OUTPUT / "terminal_analysis_receipt_v1.json"),
                "adjudication": adjudication,
            }
        except BaseException as error:
            stage_failure(error)
            raise


def audit_existing() -> dict[str, Any]:
    require(OUTPUT.is_dir() and not OUTPUT.is_symlink(), "OUTPUT_MISSING")
    input_identities()
    native_gt_contract()
    adjudication = validate_summary(read_json(OUTPUT / "common_support/common_support_summary.json"))
    adjudication["evo_crosscheck"] = validate_evo(OUTPUT / "common_support/evo_crosscheck.json")
    receipt = read_json(OUTPUT / "terminal_analysis_receipt_v1.json")
    require(receipt.get("status") == "COMPLETE_FIXED_COMMON_SUPPORT_EVALUATION", "RECEIPT_STATUS")
    return {
        "status": "PASS_EXISTING_FOURARM_ANALYSIS_AUDIT",
        "adjudication": adjudication,
        "terminal_receipt": identity(OUTPUT / "terminal_analysis_receipt_v1.json"),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("preflight", "run", "audit"))
    args = parser.parse_args()
    try:
        result = preflight() if args.command == "preflight" else execute() if args.command == "run" else audit_existing()
        print(json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False))
        return 0
    except (
        AnalysisError, OSError, ValueError, csv.Error, json.JSONDecodeError,
        subprocess.SubprocessError,
    ) as error:
        print(f"A06_FOURARM_ANALYSIS_ERROR:{type(error).__name__}:{error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
