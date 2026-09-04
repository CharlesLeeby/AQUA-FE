#!/usr/bin/env python3
"""Exactly-once descriptive analysis for the three KLT-positive AQUALOC windows.

`preflight` is read-only.  `run` writes a new staged analysis bundle and publishes
it atomically.  The controller intentionally implements no inferential statistics:
the roster is outcome-selected and contains one realized trajectory per arm/window.
"""

import argparse
import csv
import hashlib
import json
import math
import os
import statistics
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Sequence, Tuple


SCHEMA_VERSION = "positive-klt-lifecycle-rearmed-strict-analysis-v1"
METHOD_ID = "AQUAFE_XFEAT_LIFECYCLE_REARMED_DIAGNOSTIC_V1"
KLT_ARM = "EXTERNAL_KLT_FRESH_PAIRED"
AQUA_ARM = "AQUAFE_XFEAT_LIFECYCLE_REARMED_FRESH"

WORKSPACE = Path("/home/ma/AQUA-FE_WS")
PROTOCOL = WORKSPACE / "papers/positive_klt_windows_lifecycle_rearmed_analysis_v1_protocol.md"
# Bound after the frozen protocol was written.  A mismatch is fail-closed.
PROTOCOL_SHA256 = "e764c02016d32e0488651f01334e955d8873af4ae296b4c64f916d4ff6dd22bf"

EXPERIMENTS = Path("/mnt/data/AQUA-FE_WS/experiments")
FINAL_ROOT = EXPERIMENTS / "positive_klt_windows_lifecycle_rearmed_analysis_v1"
FINAL_OUTPUT = FINAL_ROOT / "analysis-output"
STAGE_ROOT = EXPERIMENTS / ".positive_klt_windows_lifecycle_rearmed_analysis_v1.stage_v1"
STAGE_OUTPUT = STAGE_ROOT / "analysis-output"


WINDOW_SPECS: Sequence[Mapping[str, Any]] = (
    {
        "window_id": "A06",
        "sequence": "AQUALOC_ARCHAEO_06",
        "evaluation_path": Path(
            "/mnt/data/AQUA-FE_WS/experiments/"
            "a06_lifecycle_rearmed_fourarm_common_support_v1/terminal_analysis_receipt_v1.json"
        ),
        "evaluation_sha256": "45e0476cc9a913737b6e1531cb9eb77fbec6892d5c4a524abd0b22968075853d",
        "evaluation_size_bytes": 23217,
        "evaluation_kind": "a06_terminal_receipt",
        "evaluation_status": "PASS_FIXED_COMMON_SUPPORT_GATES",
        "action_path": Path(
            "/mnt/data/AQUA-FE_WS/experiments/"
            "a06_lifecycle_rearmed_natural_history_v1/terminal_probe_receipt_v1.json"
        ),
        "action_sha256": "4dd554b066bb67112c792f2e1c5c83a9a57601c941cfc56f6e7094161e33b705",
        "action_size_bytes": 2644,
        "action_observation_key": "historical_window_2210_2460",
        "score_action_observations": 107,
        "score_carrier_messages": 125,
        "score_source_indices_inclusive": [2210, 2460],
    },
    {
        "window_id": "A10",
        "sequence": "AQUALOC_ARCHAEO_10",
        "evaluation_path": Path(
            "/mnt/data/AQUA-FE_WS/experiments/positive_klt_windows_lifecycle_rearmed_evaluation_v1/"
            "a10/primary_pair/adjudication_v1.json"
        ),
        "evaluation_sha256": "2735f48090ee5c786f322ff68a3c0f87b8a4e270a7a9a67800a831eb2c0319d5",
        "evaluation_size_bytes": 1944,
        "evaluation_kind": "primary_pair_adjudication",
        "evaluation_status": "PASS_PRIMARY_APE_RPE_GATES",
        "action_path": Path(
            "/mnt/data/AQUA-FE_WS/experiments/positive_klt_windows_lifecycle_rearmed_v1/"
            "a10/terminal_probe_receipt_v1.json"
        ),
        "action_sha256": "252bf9cda368aa052134b94aff5dd1d0349d0ee8b466c1b4860a05186364a619",
        "action_size_bytes": 2482,
        "action_observation_key": "score_gate",
        "score_action_observations": 184,
        "score_carrier_messages": 200,
        "score_source_indices_inclusive": [2400, 2800],
    },
    {
        "window_id": "A09",
        "sequence": "AQUALOC_ARCHAEO_09",
        "evaluation_path": Path(
            "/mnt/data/AQUA-FE_WS/experiments/positive_klt_windows_lifecycle_rearmed_evaluation_v1/"
            "a09/primary_pair/adjudication_v1.json"
        ),
        "evaluation_sha256": "1dccd654ba29f3474551935b459bbf47db61ec1693fbf647142eeda5e5c4f605",
        "evaluation_size_bytes": 1943,
        "evaluation_kind": "primary_pair_adjudication",
        "evaluation_status": "PASS_PRIMARY_APE_RPE_GATES",
        "action_path": Path(
            "/mnt/data/AQUA-FE_WS/experiments/positive_klt_windows_lifecycle_rearmed_v1/"
            "a09/terminal_probe_receipt_v1.json"
        ),
        "action_sha256": "7eda30a0c6316b67d8976e460138785d4078adbf862b0f0595e3e092a6c6cb8c",
        "action_size_bytes": 2608,
        "action_observation_key": "score_gate",
        "score_action_observations": 182,
        "score_carrier_messages": 200,
        "score_source_indices_inclusive": [4000, 4400],
    },
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def file_record(path: Path) -> Dict[str, Any]:
    return {
        "path": str(path),
        "sha256": sha256_file(path),
        "size_bytes": path.stat().st_size,
    }


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def require_close(actual: float, expected: float, label: str, atol: float = 1e-12) -> None:
    require(math.isfinite(actual), "%s is not finite" % label)
    require(
        math.isclose(actual, expected, rel_tol=1e-12, abs_tol=atol),
        "%s mismatch: actual=%r expected=%r" % (label, actual, expected),
    )


def read_pinned_json(path: Path, expected_sha256: str, expected_size: int) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    require(path.is_file(), "missing pinned input: %s" % path)
    record = file_record(path)
    require(record["sha256"] == expected_sha256, "SHA-256 mismatch for %s" % path)
    require(record["size_bytes"] == expected_size, "size mismatch for %s" % path)
    with path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    require(isinstance(payload, dict), "JSON root is not an object: %s" % path)
    return payload, record


def protocol_record() -> Dict[str, Any]:
    require(PROTOCOL.is_file(), "missing frozen protocol: %s" % PROTOCOL)
    record = file_record(PROTOCOL)
    require(record["sha256"] == PROTOCOL_SHA256, "frozen protocol SHA-256 mismatch")
    return record


def extract_window(spec: Mapping[str, Any]) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    evaluation_doc, evaluation_record = read_pinned_json(
        spec["evaluation_path"], spec["evaluation_sha256"], spec["evaluation_size_bytes"]
    )
    action_doc, action_record = read_pinned_json(
        spec["action_path"], spec["action_sha256"], spec["action_size_bytes"]
    )

    if spec["evaluation_kind"] == "a06_terminal_receipt":
        require("adjudication" in evaluation_doc, "A06 terminal receipt lacks adjudication")
        adjudication = evaluation_doc["adjudication"]
    else:
        adjudication = evaluation_doc

    require(adjudication["status"] == spec["evaluation_status"], "unexpected evaluation status")
    boundary = adjudication["claim_boundary"]
    require(boundary["statistical_inference_permitted"] is False, "inference unexpectedly permitted")
    require(boundary["ranking_or_superiority_permitted"] is False, "ranking unexpectedly permitted")
    if spec["evaluation_kind"] == "a06_terminal_receipt":
        require(
            boundary["primary_controlled_pair"] == [KLT_ARM, AQUA_ARM],
            "A06 primary controlled pair mismatch",
        )
        require(boundary["development_exposed_single_window"] is True, "A06 development flag mismatch")
    else:
        require(boundary["primary_controlled_pair"] is True, "primary-pair flag mismatch")
        require(boundary["ape_values_authorized"] is True, "APE authorization closed")
        require(boundary["rpe_values_authorized"] is True, "RPE authorization closed")
        require(adjudication["sequence"].upper() == spec["window_id"], "evaluation sequence mismatch")

    support = adjudication["support"]
    require(support["ape_valid"] is True, "APE support gate closed")
    require(support["rpe_valid"] is True, "RPE support gate closed")
    require(int(support["matched_count"]) >= 30, "matched common support below 30")
    require(float(support["common_span_s"]) >= 10.0, "common span below 10 s")
    require(int(support["rpe_pairs"]) >= 10, "RPE support below 10 pairs")
    require(int(support["segment_count"]) == 1, "unexpected multi-segment primary support")

    metrics = adjudication["metrics_fixed_order"]
    require(KLT_ARM in metrics and AQUA_ARM in metrics, "controlled arm metrics missing")
    klt_ape = float(metrics[KLT_ARM]["ape_rmse_m"])
    aqua_ape = float(metrics[AQUA_ARM]["ape_rmse_m"])
    klt_rpe = float(metrics[KLT_ARM]["rpe_rmse_m"])
    aqua_rpe = float(metrics[AQUA_ARM]["rpe_rmse_m"])
    require(min(klt_ape, aqua_ape, klt_rpe, aqua_rpe) >= 0.0, "negative RMSE encountered")
    require(klt_ape > 0.0 and klt_rpe > 0.0, "relative delta denominator is zero")

    delta_ape = aqua_ape - klt_ape
    delta_rpe = aqua_rpe - klt_rpe
    relative_ape = 100.0 * delta_ape / klt_ape
    relative_rpe = 100.0 * delta_rpe / klt_rpe
    stored = adjudication["primary_paired_contrast"]
    require_close(float(stored["ape_rmse_m"]["klt"]), klt_ape, "stored KLT APE")
    require_close(float(stored["ape_rmse_m"]["aquafe"]), aqua_ape, "stored AQUA APE")
    require_close(float(stored["ape_rmse_m"]["aquafe_minus_klt_m"]), delta_ape, "stored APE delta")
    require_close(
        float(stored["ape_rmse_m"]["aquafe_minus_klt_percent_of_klt"]),
        relative_ape,
        "stored APE relative delta",
    )
    require_close(float(stored["rpe_rmse_m"]["klt"]), klt_rpe, "stored KLT RPE")
    require_close(float(stored["rpe_rmse_m"]["aquafe"]), aqua_rpe, "stored AQUA RPE")
    require_close(float(stored["rpe_rmse_m"]["aquafe_minus_klt_m"]), delta_rpe, "stored RPE delta")
    require_close(
        float(stored["rpe_rmse_m"]["aquafe_minus_klt_percent_of_klt"]),
        relative_rpe,
        "stored RPE relative delta",
    )

    require(action_doc["status"] == "PASS_SCORE_ACTION_GATE_FRONTEND_ONLY", "action receipt status mismatch")
    require(action_doc["method_id"] == METHOD_ID, "action method ID mismatch")
    gate = action_doc["learned_action_gate"]
    require(gate["passed"] is True, "action gate did not pass")
    action_observations = int(gate["value"])
    require(action_observations > 0, "score-window action is zero")
    require(action_observations == int(spec["score_action_observations"]), "action count mismatch")
    observed_from_full = int(
        action_doc["full_learned_action"]["observations"][spec["action_observation_key"]]
    )
    require(observed_from_full == action_observations, "action count provenance mismatch")
    action_range = action_doc.get(
        "historical_action_gate_source_indices_inclusive",
        action_doc.get("score_gate_source_indices_inclusive"),
    )
    require(action_range == spec["score_source_indices_inclusive"], "score source interval mismatch")
    if "sequence" in action_doc:
        require(action_doc["sequence"] == spec["sequence"], "action sequence mismatch")

    carriers = int(spec["score_carrier_messages"])
    action_density = action_observations / carriers
    require(0.0 < action_density <= 1.0, "action density outside frozen one-lineage contract")

    improved_ape = delta_ape < 0.0
    improved_rpe = delta_rpe < 0.0
    if improved_ape and improved_rpe:
        direction = "both_improved"
    elif delta_ape > 0.0 and delta_rpe > 0.0:
        direction = "both_degraded"
    else:
        direction = "mixed_or_tied"

    row: Dict[str, Any] = {
        "window_id": spec["window_id"],
        "sequence": spec["sequence"],
        "roster_status": "historical_klt_positive_outcome_selected",
        "development_exposed": True,
        "primary_unit_n_per_arm": 1,
        "action_positive": True,
        "score_action_observations": action_observations,
        "score_carrier_messages": carriers,
        "action_density": action_density,
        "native_gt_messages": int(support["native_gt_messages"]),
        "grid_count": int(support["grid_count"]),
        "matched_count": int(support["matched_count"]),
        "common_span_s": float(support["common_span_s"]),
        "rpe_pairs": int(support["rpe_pairs"]),
        "klt_ape_rmse_m": klt_ape,
        "aquafe_ape_rmse_m": aqua_ape,
        "aquafe_minus_klt_ape_m": delta_ape,
        "aquafe_minus_klt_ape_pct": relative_ape,
        "klt_rpe_rmse_m": klt_rpe,
        "aquafe_rpe_rmse_m": aqua_rpe,
        "aquafe_minus_klt_rpe_m": delta_rpe,
        "aquafe_minus_klt_rpe_pct": relative_rpe,
        "both_metrics_improved": improved_ape and improved_rpe,
        "result_direction": direction,
        "evaluation_receipt_path": str(spec["evaluation_path"]),
        "evaluation_receipt_sha256": spec["evaluation_sha256"],
        "action_receipt_path": str(spec["action_path"]),
        "action_receipt_sha256": spec["action_sha256"],
    }
    return row, [evaluation_record, action_record]


def extract_all() -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    rows: List[Dict[str, Any]] = []
    input_records: List[Dict[str, Any]] = []
    for spec in WINDOW_SPECS:
        row, records = extract_window(spec)
        rows.append(row)
        input_records.extend(records)
    require([row["window_id"] for row in rows] == ["A06", "A10", "A09"], "display order changed")
    require(sum(bool(row["both_metrics_improved"]) for row in rows) == 2, "expected 2/3 both-metric wins")
    require(all(bool(row["action_positive"]) for row in rows), "expected all windows action-positive")
    require(
        next(row for row in rows if row["window_id"] == "A10")["result_direction"] == "both_degraded",
        "A10 retained negative result changed",
    )
    return rows, input_records


def describe(values: Sequence[float]) -> Dict[str, Any]:
    require(len(values) > 0, "cannot describe an empty sequence")
    return {
        "n_selected_windows": len(values),
        "mean": sum(values) / len(values),
        "sample_sd": statistics.stdev(values) if len(values) > 1 else None,
        "median": statistics.median(values),
        "minimum": min(values),
        "maximum": max(values),
        "range": [min(values), max(values)],
    }


def build_aggregate(rows: Sequence[Mapping[str, Any]], inputs: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    ape_relative = [float(row["aquafe_minus_klt_ape_pct"]) for row in rows]
    rpe_relative = [float(row["aquafe_minus_klt_rpe_pct"]) for row in rows]
    action_density = [float(row["action_density"]) for row in rows]
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": utc_now(),
        "analysis_question": (
            "Descriptive fresh-KLT versus fresh lifecycle-rearmed AQUA-FE comparison on the "
            "complete three-window historical KLT-positive roster."
        ),
        "roster": {
            "fixed_order": [row["window_id"] for row in rows],
            "n_selected_windows": len(rows),
            "selection": "historical_klt_positive_outcome_selected",
            "development_exposed": True,
            "broader_orb_mechanism_roster_included": False,
        },
        "unit_of_analysis": {
            "primary": "one paired trajectory realization per arm per window",
            "n_trajectories_per_arm_per_window": 1,
            "n_selected_window_pairs": len(rows),
            "grid_points_are_independent_n": False,
            "rpe_pairs_are_independent_n": False,
        },
        "claim_boundary": {
            "descriptive_only": True,
            "inferential_tests_permitted": False,
            "confidence_intervals_permitted": False,
            "significance_language_permitted": False,
            "generalization_permitted": False,
            "ranking_or_superiority_permitted": False,
            "sample_sd_interpretation": "heterogeneity across three selected windows only",
        },
        "effect_definition": {
            "absolute": "AQUA minus KLT RMSE in metres",
            "relative": "100 * (AQUA minus KLT) / KLT",
            "direction": "negative is lower RMSE (improvement)",
        },
        "primary_result": {
            "both_metrics_improved_windows": [
                row["window_id"] for row in rows if row["both_metrics_improved"]
            ],
            "both_metrics_improved_count": sum(bool(row["both_metrics_improved"]) for row in rows),
            "both_metrics_improved_fraction": "2/3",
            "retained_both_metrics_degraded_windows": [
                row["window_id"] for row in rows if row["result_direction"] == "both_degraded"
            ],
            "all_action_positive": all(bool(row["action_positive"]) for row in rows),
            "action_positive_count": sum(bool(row["action_positive"]) for row in rows),
        },
        "descriptive_relative_delta_pct": {
            "ape_rmse": describe(ape_relative),
            "rpe_rmse": describe(rpe_relative),
        },
        "descriptive_action_density": {
            "definition": "score-window injected observations / score carrier messages",
            "summary": describe(action_density),
            "independent_sample_statistic": False,
        },
        "windows": list(rows),
        "pinned_inputs": list(inputs),
        "inference": {
            "status": "BLOCKED_BY_DESIGN",
            "tests_run": [],
            "p_values": [],
            "confidence_intervals": [],
            "reason": (
                "Outcome-selected development roster with only one realized trajectory per arm/window; "
                "within-trajectory support samples are not independent repeats."
            ),
        },
    }


CSV_COLUMNS = (
    "window_id",
    "sequence",
    "roster_status",
    "development_exposed",
    "primary_unit_n_per_arm",
    "action_positive",
    "score_action_observations",
    "score_carrier_messages",
    "action_density",
    "native_gt_messages",
    "grid_count",
    "matched_count",
    "common_span_s",
    "rpe_pairs",
    "klt_ape_rmse_m",
    "aquafe_ape_rmse_m",
    "aquafe_minus_klt_ape_m",
    "aquafe_minus_klt_ape_pct",
    "klt_rpe_rmse_m",
    "aquafe_rpe_rmse_m",
    "aquafe_minus_klt_rpe_m",
    "aquafe_minus_klt_rpe_pct",
    "both_metrics_improved",
    "result_direction",
    "evaluation_receipt_path",
    "evaluation_receipt_sha256",
    "action_receipt_path",
    "action_receipt_sha256",
)


def csv_value(value: Any) -> Any:
    if isinstance(value, float):
        return format(value, ".15g")
    if isinstance(value, bool):
        return "true" if value else "false"
    return value


def write_csv(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_COLUMNS, lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({column: csv_value(row[column]) for column in CSV_COLUMNS})


def write_json(path: Path, payload: Mapping[str, Any]) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")


def write_text(path: Path, payload: str) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(payload)


def pct(value: float) -> str:
    return "%+.4f%%" % value


def metres(value: float) -> str:
    return "%.9f" % value


def render_analysis_report(rows: Sequence[Mapping[str, Any]], aggregate: Mapping[str, Any]) -> str:
    ape_desc = aggregate["descriptive_relative_delta_pct"]["ape_rmse"]
    rpe_desc = aggregate["descriptive_relative_delta_pct"]["rpe_rmse"]
    table_lines = []
    for row in rows:
        table_lines.append(
            "| {window_id} | {ka:.9f} | {aa:.9f} | {da:+.9f} | {ra} | "
            "{kr:.9f} | {ar:.9f} | {dr:+.9f} | {rr} | {action}/{carrier} | {direction} |".format(
                window_id=row["window_id"],
                ka=row["klt_ape_rmse_m"],
                aa=row["aquafe_ape_rmse_m"],
                da=row["aquafe_minus_klt_ape_m"],
                ra=pct(row["aquafe_minus_klt_ape_pct"]),
                kr=row["klt_rpe_rmse_m"],
                ar=row["aquafe_rpe_rmse_m"],
                dr=row["aquafe_minus_klt_rpe_m"],
                rr=pct(row["aquafe_minus_klt_rpe_pct"]),
                action=row["score_action_observations"],
                carrier=row["score_carrier_messages"],
                direction=row["result_direction"],
            )
        )
    return """# 三个 KLT 正例窗口：lifecycle-rearmed 严格描述性分析

## 分析问题与结论边界

本 bundle 回答一个固定的描述性问题：在完整的三个历史 KLT 正例窗口
（A06、A10、A09）上，同一 VINS-Fusion 后端下，fresh lifecycle-rearmed
AQUA-FE 相对 fresh external KLT 的 APE/RPE RMSE 如何变化。

每窗每臂只有一条实现轨迹（`n = 1 trajectory/arm/window`）。三窗均为
outcome-selected 且 development-exposed；共同支撑网格点与 RPE pair 是轨迹内
评价样本，不是独立重复。因此本报告不做显著性检验、p 值、置信区间、总体
排名、稳健性或泛化声明。

## 固定主对照结果

RMSE 越低越好；`AQUA - KLT` 为负表示改善。显示顺序已冻结，不按结果排序。

| 窗口 | KLT APE (m) | AQUA APE (m) | APE delta (m) | APE delta (%) | KLT RPE (m) | AQUA RPE (m) | RPE delta (m) | RPE delta (%) | score action | 方向 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
{table}

观察：A06 和 A09 的 APE/RPE RMSE 同时下降，A10 的两项 RMSE 同时上升；因此
“两项都改善”为 **2/3 个已选择窗口**。A10 是固定保留的反例，不能被平均值
隐藏。三窗的 score-window learned action 都非零（107/125、184/200、182/200）。

## 跨窗描述量

- APE 相对 delta：macro mean {ape_mean} ± {ape_sd}（sample SD），median
  {ape_median}，range [{ape_min}, {ape_max}]。
- RPE 相对 delta：macro mean {rpe_mean} ± {rpe_sd}（sample SD），median
  {rpe_median}，range [{rpe_min}, {rpe_max}]。

这些统计量只描述三个已选择窗口之间的异质性，不能解释为总体均值的不确定性。
尤其是 macro mean 为负并不构成“方法总体优于 KLT”的证据。

## 动作门与决策含义

非零 learned action 是把轨迹差异归因于 learned frontend 的必要门槛；它不是
性能改善的充分条件。A10 在 184/200 的高 action density 下仍出现 APE/RPE
小幅上升，说明下一步应研究“哪些 action 有效”，而不是单纯提高 action 数量。

## Claim Candidates

- Claim:
  - 三个固定历史 KLT 正例窗口均在原 score window 内产生了非零 lifecycle-rearmed learned action。
  - Source evidence: 三个 pinned frontend terminal receipts；`window_metrics.csv`。
  - Allowed wording: “在 A06/A10/A09 的冻结 score gate 下，诊断版 lifecycle-rearmed 前端均产生非零 learned action。”
  - Forbidden stronger wording: “该前端在所有水下场景都稳定触发”或“动作必然改善定位”。
  - Uncertainty: roster 仅含三个 outcome-selected、development-exposed 窗口。
  - Next check: 在预先冻结、非按结果选择的独立窗口 roster 上复现 action gate。
  - Decision: keep

- Claim:
  - 在三个已选择窗口的 fresh paired-backend 描述中，A06/A09 两项 RMSE 同时下降，A10 两项同时上升。
  - Source evidence: 三个 pinned primary adjudications；`window_metrics.csv`。
  - Allowed wording: “在该三窗描述性 roster 中，两窗的 APE/RPE RMSE 同时下降，一窗同时上升（2/3）。”
  - Forbidden stronger wording: “AQUA-FE 显著优于 KLT”“跨场景稳健优于 KLT”或“胜率为 66.7% 的总体估计”。
  - Uncertainty: 每窗每臂只有一条轨迹，窗口 outcome-selected，且无独立重复或 held-out roster。
  - Next check: 预注册 held-out 窗口、固定参数，并增加独立重复或可解释的序列级单位。
  - Decision: keep

- Claim:
  - learned action 是有效 accuracy attribution 的必要门槛，但在本审计中不是改善的充分条件。
  - Source evidence: all-three action-positive receipts；A10 的 +0.7642% APE 和 +0.7394% RPE delta。
  - Allowed wording: “非零 action 允许进行 learned-vs-KLT 归因对照；A10 表明 action 本身不保证误差下降。”
  - Forbidden stronger wording: “action density 与精度负相关”或任何因果机制声明。
  - Uncertainty: 仅三个窗口，action density 与误差变化没有足够独立单位做关联分析。
  - Next check: 冻结 action quality 指标并在更大 held-out roster 上做机制分层。
  - Decision: keep

## 证据完整性

正式 runner 对六个 source receipts 执行运行前/运行后 SHA-256 锁定，并核验所有
主对照 gate、support gate、delta 重算、固定 2/3 结果和 A10 负结果。正式输出为
exactly-once、additive；旧实验不被改写。
""".format(
        table="\n".join(table_lines),
        ape_mean=pct(ape_desc["mean"]),
        ape_sd="%.4f%%" % ape_desc["sample_sd"],
        ape_median=pct(ape_desc["median"]),
        ape_min=pct(ape_desc["minimum"]),
        ape_max=pct(ape_desc["maximum"]),
        rpe_mean=pct(rpe_desc["mean"]),
        rpe_sd="%.4f%%" % rpe_desc["sample_sd"],
        rpe_median=pct(rpe_desc["median"]),
        rpe_min=pct(rpe_desc["minimum"]),
        rpe_max=pct(rpe_desc["maximum"]),
    )


def render_stats_appendix(rows: Sequence[Mapping[str, Any]], aggregate: Mapping[str, Any]) -> str:
    ape = aggregate["descriptive_relative_delta_pct"]["ape_rmse"]
    rpe = aggregate["descriptive_relative_delta_pct"]["rpe_rmse"]
    action = aggregate["descriptive_action_density"]["summary"]
    per_window = "\n".join(
        "- {window}: APE {ape_abs:+.9f} m ({ape_rel}); RPE {rpe_abs:+.9f} m ({rpe_rel}); "
        "action {obs}/{carrier} = {density:.1f}%.".format(
            window=row["window_id"],
            ape_abs=row["aquafe_minus_klt_ape_m"],
            ape_rel=pct(row["aquafe_minus_klt_ape_pct"]),
            rpe_abs=row["aquafe_minus_klt_rpe_m"],
            rpe_rel=pct(row["aquafe_minus_klt_rpe_pct"]),
            obs=row["score_action_observations"],
            carrier=row["score_carrier_messages"],
            density=100.0 * row["action_density"],
        )
        for row in rows
    )
    return """# Statistical appendix: strict descriptive mode

## Comparison unit and sample size

- Primary contrast: fresh `AQUAFE_XFEAT_LIFECYCLE_REARMED_FRESH` minus fresh
  `EXTERNAL_KLT_FRESH_PAIRED`, evaluated on the same per-window common support.
- Unit: one paired trajectory realization per arm per window.
- Per-window count: `n = 1 trajectory/arm`; selected roster count: `n = 3 windows`.
- Common-grid poses (30 matched/window) and RPE pairs (29/window) are repeated
  within-trajectory evaluation samples, not independent experimental units.
- Metric direction: APE/RPE RMSE in metres, lower is better.
- Effect: absolute paired delta in metres and relative paired delta
  `100 * (AQUA - KLT) / KLT`; negative is improvement.

## Per-window effects

{per_window}

## Macro descriptors of relative delta

| Metric | n selected windows | Mean (%) | Sample SD (%) | Median (%) | Min (%) | Max (%) |
|---|---:|---:|---:|---:|---:|---:|
| APE RMSE | {ape_n} | {ape_mean:+.6f} | {ape_sd:.6f} | {ape_median:+.6f} | {ape_min:+.6f} | {ape_max:+.6f} |
| RPE RMSE | {rpe_n} | {rpe_mean:+.6f} | {rpe_sd:.6f} | {rpe_median:+.6f} | {rpe_min:+.6f} | {rpe_max:+.6f} |

The sample SD above is a finite-roster heterogeneity descriptor, not an uncertainty
estimate.  The action-density macro descriptor is mean {action_mean:.6f}, sample SD
{action_sd:.6f}, median {action_median:.6f}, range
[{action_min:.6f}, {action_max:.6f}]; it is likewise descriptive and its carrier
messages are not independent trials.

## Inferential-statistics gate

- Normality tests: not run.
- Paired t-test / Wilcoxon signed-rank test: not run.
- Confidence intervals: not computed.
- p-values and multiple-comparison correction: not applicable because no
  inferential contrasts were authorized.
- Standardized population effect sizes: not computed.

Reason: the roster was selected for historical positive KLT behavior, is
development-exposed, and has one realized trajectory per arm/window.  `n = 3`
selected windows is insufficient to justify a population model here; treating 30
grid samples or 29 RPE pairs per window as independent would be pseudoreplication.
Consequently no significance, superiority, robustness, or generalization statement
is valid from this bundle.

## Completeness and negative-result audit

- Valid primary APE/RPE gates: 3/3 windows.
- Nonzero learned-action gate: 3/3 windows.
- Both metrics decreased: A06 and A09 (2/3 selected windows).
- Both metrics increased: A10 (1/3), retained without exclusion or retuning.
- Missing/failed selected windows: none.

No error bars appear in the figures because there are no repeated trajectory runs
from which SD, SE, or CI could be estimated.  Adding error bars across within-window
grid points would misstate the experimental unit.
""".format(
        per_window=per_window,
        ape_n=ape["n_selected_windows"],
        ape_mean=ape["mean"],
        ape_sd=ape["sample_sd"],
        ape_median=ape["median"],
        ape_min=ape["minimum"],
        ape_max=ape["maximum"],
        rpe_n=rpe["n_selected_windows"],
        rpe_mean=rpe["mean"],
        rpe_sd=rpe["sample_sd"],
        rpe_median=rpe["median"],
        rpe_min=rpe["minimum"],
        rpe_max=rpe["maximum"],
        action_mean=action["mean"],
        action_sd=action["sample_sd"],
        action_median=action["median"],
        action_min=action["minimum"],
        action_max=action["maximum"],
    )


def render_figure_catalog(rows: Sequence[Mapping[str, Any]]) -> str:
    return """# Figure catalog

## Figure 01

- Filename: `figures/figure-01-primary-relative-change.pdf`
- Purpose: show the direction and magnitude of the per-window fresh AQUA-minus-KLT
  APE/RPE RMSE changes on the fixed three-window roster.
- Data source: `window_metrics.csv`, columns
  `aquafe_minus_klt_ape_pct` and `aquafe_minus_klt_rpe_pct`; each value is recomputed
  from a pinned primary adjudication.
- Caption requirements: negative means lower RMSE (improvement); display order is
  A06/A10/A09 and is not metric-sorted; each bar is one realized paired trajectory
  effect per selected window; `n = 1 trajectory/arm/window`; no error bars because
  repeated runs are unavailable; roster is outcome-selected and development-exposed.
- Key observation: A06 and A09 are below zero for both metrics, while A10 is above
  zero for both metrics.
- Interpretation checklist:
  1. Why: distinguish consistency from an average that could hide A10.
  2. Notice: 2/3 selected windows improve both metrics; A10 degrades both.
  3. Decision: retain the branch for broader held-out testing, but do not make a
     superiority or robustness claim.
- Known caveats: three selected windows only; no repeats, CI, p-value, or independent
  population sampling.

## Figure 02

- Filename: `figures/figure-02-action-density.pdf`
- Purpose: audit whether learned action actually reached each historical score
  window and test the limited proposition that action alone guarantees improvement.
- Data source: three pinned frontend terminal receipts plus frozen carrier counts;
  exact ratios are A06 107/125, A10 184/200, A09 182/200.
- Caption requirements: density means injected observations per score carrier
  message under the one-concurrent-lineage contract; it is not a probability or
  independent trial rate; all windows pass the nonzero attribution gate; no error
  bars because each ratio is deterministic from one receipt.
- Key observation: all three action gates pass, including A10 at 92.0% density, yet
  A10 does not improve either primary metric.
- Interpretation checklist:
  1. Why: separate “the learned branch acted” from “the action helped”.
  2. Notice: action is present in every window but accuracy direction is not uniform.
  3. Decision: study action quality/selection on a held-out roster instead of merely
     increasing action count.
- Known caveats: with only three windows, the figure cannot support correlation,
  dose-response, or causal mechanism claims.

## Visual encoding QA

- Vector PDF output; Okabe-Ito colorblind-safe colors.
- Black edges, hatch patterns, and point markers provide grayscale redundancy.
- Figure 01 includes an explicit zero line and labels negative as improvement.
- No inferential glyphs, significance stars, smoothing, truncated categorical
  membership, or error bars.
"""


def configure_matplotlib() -> Any:
    import matplotlib

    matplotlib.use("Agg")
    matplotlib.rcParams.update(
        {
            "font.family": "DejaVu Sans",
            "font.size": 9,
            "axes.labelsize": 10,
            "xtick.labelsize": 9,
            "ytick.labelsize": 9,
            "legend.fontsize": 9,
            "axes.linewidth": 0.8,
            "pdf.fonttype": 42,
            "ps.fonttype": 42,
        }
    )
    return matplotlib


def save_figure(fig: Any, path: Path) -> None:
    fig.savefig(
        str(path),
        format="pdf",
        bbox_inches="tight",
        metadata={
            "Title": path.stem,
            "Author": "AQUA-FE strict analysis controller",
            "Creator": "summarize_positive_klt_windows_lifecycle_rearmed_v1.py",
            "CreationDate": None,
            "ModDate": None,
        },
    )


def generate_figures(rows: Sequence[Mapping[str, Any]], figures_dir: Path) -> str:
    matplotlib = configure_matplotlib()
    import matplotlib.pyplot as plt

    labels = [str(row["window_id"]) for row in rows]
    x = list(range(len(rows)))
    ape = [float(row["aquafe_minus_klt_ape_pct"]) for row in rows]
    rpe = [float(row["aquafe_minus_klt_rpe_pct"]) for row in rows]

    width = 0.34
    fig, ax = plt.subplots(figsize=(7.0, 3.8))
    ape_bars = ax.bar(
        [value - width / 2 for value in x],
        ape,
        width,
        label="APE RMSE",
        color="#56B4E9",
        edgecolor="black",
        linewidth=0.8,
        hatch="///",
        zorder=3,
    )
    rpe_bars = ax.bar(
        [value + width / 2 for value in x],
        rpe,
        width,
        label="RPE RMSE",
        color="#E69F00",
        edgecolor="black",
        linewidth=0.8,
        hatch="\\\\",
        zorder=3,
    )
    ax.axhline(0.0, color="black", linewidth=1.0, zorder=4)
    ax.set_xticks(x)
    ax.set_xticklabels(labels)
    ax.set_ylabel("Relative RMSE change vs KLT (%)")
    ax.set_xlabel("Selected window (fixed order)")
    ax.grid(axis="y", color="#BDBDBD", linewidth=0.6, alpha=0.55, zorder=0)
    ax.legend(frameon=False, ncol=2, loc="upper left")
    ax.text(
        0.99,
        0.03,
        "negative = lower RMSE (improvement)\nno error bars: one trajectory/arm/window",
        transform=ax.transAxes,
        ha="right",
        va="bottom",
        fontsize=8,
    )
    for bars in (ape_bars, rpe_bars):
        for bar in bars:
            value = float(bar.get_height())
            offset = 3 if value >= 0 else -12
            va = "bottom" if value >= 0 else "top"
            ax.annotate(
                "%+.3f" % value,
                xy=(bar.get_x() + bar.get_width() / 2, value),
                xytext=(0, offset),
                textcoords="offset points",
                ha="center",
                va=va,
                fontsize=8,
            )
    finite = ape + rpe + [0.0]
    margin = max(0.18, 0.18 * (max(finite) - min(finite)))
    ax.set_ylim(min(finite) - margin, max(finite) + margin)
    fig.tight_layout()
    save_figure(fig, figures_dir / "figure-01-primary-relative-change.pdf")
    plt.close(fig)

    densities = [100.0 * float(row["action_density"]) for row in rows]
    colors = ["#0072B2", "#E69F00", "#009E73"]
    hatches = ["///", "xx", ".."]
    fig, ax = plt.subplots(figsize=(6.0, 3.8))
    bars = []
    for idx, (density, color, hatch) in enumerate(zip(densities, colors, hatches)):
        bar = ax.bar(
            [idx],
            [density],
            width=0.62,
            color=color,
            edgecolor="black",
            linewidth=0.8,
            hatch=hatch,
            zorder=3,
        )[0]
        bars.append(bar)
        ax.plot(idx, density, marker="o", markersize=4, color="black", zorder=4)
    ax.set_xticks(x)
    ax.set_xticklabels(labels)
    ax.set_ylim(0.0, 100.0)
    ax.set_ylabel("Score-window action density (%)")
    ax.set_xlabel("Selected window (fixed order)")
    ax.grid(axis="y", color="#BDBDBD", linewidth=0.6, alpha=0.55, zorder=0)
    for bar, row, density in zip(bars, rows, densities):
        ax.annotate(
            "%d/%d\n(%.1f%%)" % (
                row["score_action_observations"],
                row["score_carrier_messages"],
                density,
            ),
            xy=(bar.get_x() + bar.get_width() / 2, density),
            xytext=(0, 5),
            textcoords="offset points",
            ha="center",
            va="bottom",
            fontsize=8,
        )
    ax.text(
        0.01,
        0.03,
        "action is an attribution gate, not a guarantee of improvement\n"
        "no error bars: deterministic receipt ratios",
        transform=ax.transAxes,
        ha="left",
        va="bottom",
        fontsize=8,
    )
    fig.tight_layout()
    save_figure(fig, figures_dir / "figure-02-action-density.pdf")
    plt.close(fig)
    return str(matplotlib.__version__)


REQUIRED_RELATIVE_FILES = (
    "window_metrics.csv",
    "aggregate_summary.json",
    "analysis-report.md",
    "stats-appendix.md",
    "figure-catalog.md",
    "figures/figure-01-primary-relative-change.pdf",
    "figures/figure-02-action-density.pdf",
)


def validate_pdfs(output_dir: Path) -> None:
    for relative in REQUIRED_RELATIVE_FILES:
        path = output_dir / relative
        require(path.is_file(), "required output missing: %s" % relative)
        require(path.stat().st_size > 0, "required output empty: %s" % relative)
    for relative in REQUIRED_RELATIVE_FILES[-2:]:
        with (output_dir / relative).open("rb") as handle:
            require(handle.read(5) == b"%PDF-", "invalid PDF header: %s" % relative)


def stable_input_audit(expected: Sequence[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    current = [file_record(Path(record["path"])) for record in expected]
    require(current == list(expected), "pinned input changed during analysis generation")
    return current


def run_preflight() -> int:
    protocol = protocol_record()
    rows, inputs = extract_all()
    output_absent = not FINAL_ROOT.exists()
    stage_absent = not STAGE_ROOT.exists()
    payload = {
        "schema_version": SCHEMA_VERSION,
        "mode": "read_only_preflight",
        "status": "READY_FOR_EXACTLY_ONCE_RUN" if output_absent and stage_absent else "BLOCKED_EXISTING_PATH",
        "protocol": protocol,
        "final_root_absent": output_absent,
        "stage_root_absent": stage_absent,
        "pinned_inputs": inputs,
        "fixed_window_summary": [
            {
                "window_id": row["window_id"],
                "action": "%d/%d" % (row["score_action_observations"], row["score_carrier_messages"]),
                "ape_relative_delta_pct": row["aquafe_minus_klt_ape_pct"],
                "rpe_relative_delta_pct": row["aquafe_minus_klt_rpe_pct"],
                "direction": row["result_direction"],
            }
            for row in rows
        ],
        "both_metrics_improved_count": 2,
        "all_action_positive": True,
        "formal_outputs_written": False,
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if output_absent and stage_absent else 2


def run_formal() -> int:
    require(not FINAL_ROOT.exists(), "final output root already exists; exact-once run refused")
    require(not STAGE_ROOT.exists(), "fixed staging root already exists; exact-once run refused")
    protocol = protocol_record()
    rows, inputs_before = extract_all()

    STAGE_OUTPUT.mkdir(parents=True, exist_ok=False)
    figures_dir = STAGE_OUTPUT / "figures"
    figures_dir.mkdir(exist_ok=False)
    start_claim = {
        "schema_version": SCHEMA_VERSION,
        "status": "STARTED_EXACTLY_ONCE_ANALYSIS",
        "started_at_utc": utc_now(),
        "controller_pid": os.getpid(),
        "final_root": str(FINAL_ROOT),
        "stage_root": str(STAGE_ROOT),
        "retry_permitted": False,
        "protocol": protocol,
        "pinned_inputs_before": inputs_before,
    }
    write_json(STAGE_OUTPUT / "process_start_claim_v1.json", start_claim)

    aggregate = build_aggregate(rows, inputs_before)
    write_csv(STAGE_OUTPUT / "window_metrics.csv", rows)
    write_json(STAGE_OUTPUT / "aggregate_summary.json", aggregate)
    write_text(STAGE_OUTPUT / "analysis-report.md", render_analysis_report(rows, aggregate))
    write_text(STAGE_OUTPUT / "stats-appendix.md", render_stats_appendix(rows, aggregate))
    write_text(STAGE_OUTPUT / "figure-catalog.md", render_figure_catalog(rows))
    matplotlib_version = generate_figures(rows, figures_dir)
    validate_pdfs(STAGE_OUTPUT)
    inputs_after = stable_input_audit(inputs_before)

    output_records = [file_record(STAGE_OUTPUT / relative) for relative in REQUIRED_RELATIVE_FILES]
    controller_record = file_record(Path(__file__).resolve())
    terminal_receipt = {
        "schema_version": SCHEMA_VERSION,
        "status": "COMPLETE_STRICT_DESCRIPTIVE_ANALYSIS",
        "ended_at_utc": utc_now(),
        "formal_analysis_processes_started": 1,
        "retry_count": 0,
        "fixed_order": ["A06", "A10", "A09"],
        "n_selected_windows": 3,
        "n_trajectories_per_arm_per_window": 1,
        "both_metrics_improved_count": 2,
        "both_metrics_improved_fraction": "2/3",
        "retained_negative_window": "A10",
        "all_action_positive": True,
        "inferential_tests_run": [],
        "confidence_intervals_computed": [],
        "grid_points_treated_as_independent_n": False,
        "protocol": protocol,
        "controller": controller_record,
        "python": sys.version,
        "matplotlib_version": matplotlib_version,
        "pinned_inputs_before": inputs_before,
        "pinned_inputs_after": inputs_after,
        "output_artifacts": output_records,
        "publication": {
            "stage_root": str(STAGE_ROOT),
            "final_root": str(FINAL_ROOT),
            "atomic_root_rename_pending_at_receipt_write": True,
            "existing_artifacts_modified": False,
        },
    }
    write_json(STAGE_OUTPUT / "terminal_analysis_receipt_v1.json", terminal_receipt)
    require((STAGE_OUTPUT / "terminal_analysis_receipt_v1.json").stat().st_size > 0, "terminal receipt empty")
    stable_input_audit(inputs_before)
    os.replace(str(STAGE_ROOT), str(FINAL_ROOT))
    require(FINAL_OUTPUT.is_dir(), "atomic publication did not create final analysis-output")
    print(str(FINAL_OUTPUT))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "mode",
        choices=("preflight", "run"),
        help="preflight is read-only; run performs the one allowed additive publication",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        if args.mode == "preflight":
            return run_preflight()
        return run_formal()
    except Exception as exc:
        print("ERROR: %s" % exc, file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
