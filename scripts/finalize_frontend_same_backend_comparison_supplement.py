#!/usr/bin/env python3
"""Collect replay gates, evaluate common support, and write the supplement report."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from pathlib import Path
import re
from statistics import median
import subprocess
import sys

import rosbag

sys.path.insert(0, str(Path(__file__).resolve().parent))
import run_frontend_same_backend_comparison_supplement as frontend


ROOT = Path("/home/ma/AQUA-FE_WS")
PAPER_ROOT = ROOT / "papers/frontend_same_backend_comparison_supplement"
RUNTIME_ROOT = ROOT / "artifacts/frontend_same_backend_comparison_supplement"
REPLAY_ROOT = RUNTIME_ROOT / "replays"
EVALUATOR = ROOT / "scripts/evaluate_vins_common_support_dual_scale.py"
ARMS = tuple(frontend.ARMS)
ARM_DISPLAY = {"klt": "KLT", "splg": "SP+LG", "xfeat_seed": "XFeat-seed"}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as stream:
        return list(csv.DictReader(stream))


def write_csv(path: Path, rows: list[dict[str, object]], fields: list[str] | None = None) -> None:
    if fields is None:
        fields = []
        for row in rows:
            for key in row:
                if key not in fields:
                    fields.append(key)
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def pose_stats(path: Path) -> tuple[int, float, float | None, float | None]:
    stamps: list[float] = []
    if path.is_file():
        with path.open(encoding="utf-8", errors="ignore") as stream:
            for line in stream:
                first = line.split(",", 1)[0].strip()
                if re.fullmatch(r"\d+", first):
                    stamps.append(int(first) * 1e-9)
    if not stamps:
        return 0, 0.0, None, None
    return len(stamps), max(0.0, stamps[-1] - stamps[0]), stamps[0], stamps[-1]


def reference_span(feature_bag: Path, topic: str) -> tuple[float, float, float]:
    stamps: list[float] = []
    with rosbag.Bag(str(feature_bag)) as bag:
        for _, message, stamp in bag.read_messages(topics=[topic]):
            header = getattr(message, "header", None)
            stamps.append(float(header.stamp.to_sec()) if header is not None else float(stamp.to_sec()))
    if len(stamps) < 2:
        raise RuntimeError(f"reference topic has fewer than two poses: {feature_bag}:{topic}")
    return stamps[0], stamps[-1], stamps[-1] - stamps[0]


def update_runability() -> list[dict[str, str]]:
    subprocess.run(
        [sys.executable, str(ROOT / "scripts/analyze_frontend_same_backend_comparison_supplement.py")],
        cwd=ROOT,
        check=True,
    )
    path = PAPER_ROOT / "runability.csv"
    rows = read_csv(path)
    candidates = {row["window_id"]: row for row in read_csv(PAPER_ROOT / "candidate_windows.csv")}
    for row in rows:
        if not (
            row["candidate_status"] == "FRONTEND_PASS"
            and row["frontend_runable"] == "PASS"
            and row["exclusion_status"] == "INCLUDED"
        ):
            continue
        window, arm = row["window_id"], row["arm"]
        candidate = candidates[window]
        topic = "/afrl/colmap_gt" if candidate["family"] == "afrl" else "/aqualoc/colmap_gt"
        ref_start, ref_end, expected_span = reference_span(Path(row["feature_bag_path"]), topic)
        repeat_passes: list[bool] = []
        reasons: set[str] = set()
        for repeat in range(1, 4):
            run_dir = REPLAY_ROOT / window / arm / f"repeat{repeat}"
            vio = run_dir / "vins_output/vio.csv"
            log = run_dir / "vins.log"
            receipt = run_dir / "replay_receipt.txt"
            count, span, first, last = pose_stats(vio)
            text = log.read_text(encoding="utf-8", errors="ignore") if log.is_file() else ""
            initialized = "Initialization finish!" in text and count > 0
            coverage = min(1.0, span / expected_span) if expected_span > 0.0 else 0.0
            passed = bool(receipt.is_file() and initialized and coverage >= 0.70)
            repeat_passes.append(passed)
            row[f"repeat{repeat}_init"] = "PASS" if initialized else "FAIL"
            row[f"repeat{repeat}_pose_count"] = str(count)
            row[f"repeat{repeat}_span_s"] = f"{span:.9f}"
            row[f"repeat{repeat}_coverage"] = f"{coverage:.9f}"
            if not passed:
                lower = text.lower()
                if not receipt.is_file() and not log.is_file():
                    reasons.add("configuration_or_infrastructure")
                elif "not enough imu excitation" in lower:
                    reasons.add("insufficient_excitation")
                elif not initialized:
                    reasons.add("cold_start_no_initialization")
                elif coverage < 0.70:
                    reasons.add("coverage_failure")
                else:
                    reasons.add("early_termination")
        row["arm_window_pass"] = "PASS" if all(repeat_passes) else "FAIL"
        row["failure_class"] = ";".join(sorted(reasons))
        row["notes"] += (
            f";reference_span_s={expected_span:.9f};reference_start={ref_start:.9f};"
            f"reference_end={ref_end:.9f};backend_repeats_pass={sum(repeat_passes)}/3"
        )
    fields = list(rows[0]) if rows else []
    write_csv(path, rows, fields)
    return rows


def all_arm_backend_windows(rows: list[dict[str, str]]) -> list[str]:
    ordered = [row["window_id"] for row in read_csv(PAPER_ROOT / "candidate_windows.csv")]
    result = []
    for window in ordered:
        cells = [row for row in rows if row["window_id"] == window]
        if len(cells) == 3 and all(row["arm_window_pass"] == "PASS" for row in cells):
            result.append(window)
    return result


def evaluate(rows: list[dict[str, str]]) -> list[dict[str, object]]:
    candidates = {row["window_id"]: row for row in read_csv(PAPER_ROOT / "candidate_windows.csv")}
    status_rows: list[dict[str, object]] = []
    for window in all_arm_backend_windows(rows):
        candidate = candidates[window]
        by_arm = {row["arm"]: row for row in rows if row["window_id"] == window}
        reference_bag = by_arm["klt"]["feature_bag_path"]
        reference_topic = "/afrl/colmap_gt" if candidate["family"] == "afrl" else "/aqualoc/colmap_gt"
        config = RUNTIME_ROOT / "backend_canonical" / window / "vins_same_backend.yaml"
        output = PAPER_ROOT / "common_support" / window
        command = [
            sys.executable, str(EVALUATOR),
            "--reference-bag", reference_bag,
            "--reference-topic", reference_topic,
            "--evaluation-rate-hz", "1",
            "--max-reference-gap-s", "2.5",
            "--max-estimate-gap-s", "0.25",
            "--output-dir", str(output),
            "--run-evo",
        ]
        for arm in ARMS:
            for repeat in range(1, 4):
                name = f"{arm}_r{repeat}"
                vio = REPLAY_ROOT / window / arm / f"repeat{repeat}/vins_output/vio.csv"
                command += ["--arm", f"{name}={vio}", "--arm-config", f"{name}={config}"]
        process = subprocess.run(
            command, cwd=ROOT, text=True, stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT, check=False,
        )
        output.mkdir(parents=True, exist_ok=True)
        (output / "evaluator.log").write_text(process.stdout, encoding="utf-8")
        summary_path = output / "common_support_summary.json"
        admitted = False
        support: dict[str, object] = {}
        if process.returncode == 0 and summary_path.is_file():
            support = json.loads(summary_path.read_text(encoding="utf-8"))["support"]
            admitted = bool(support["ape_valid"] and support["rpe_valid"])
        status_rows.append(
            {
                "window_id": window,
                "status": "PASS" if admitted else "EXCLUDED_COMMON_SUPPORT",
                "return_code": process.returncode,
                "matched_count": support.get("matched_count", ""),
                "common_span_s": support.get("common_span_s", ""),
                "common_coverage": support.get("common_coverage", ""),
                "rpe_pairs": support.get("rpe_pairs", ""),
            }
        )
    write_csv(
        PAPER_ROOT / "common_support_status.csv",
        status_rows,
        ["window_id", "status", "return_code", "matched_count", "common_span_s", "common_coverage", "rpe_pairs"],
    )
    return status_rows


def finite_median(values: list[float]) -> float:
    return float(median(value for value in values if math.isfinite(value)))


def range_text(values: list[float]) -> str:
    finite = [value for value in values if math.isfinite(value)]
    return f"{min(finite):.9f}–{max(finite):.9f}"


def collect_accuracy(status_rows: list[dict[str, object]]) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    repeats: list[dict[str, object]] = []
    for status in status_rows:
        if status["status"] != "PASS":
            continue
        window = str(status["window_id"])
        metrics = read_csv(PAPER_ROOT / "common_support" / window / "common_support_metrics.csv")
        evo_data = json.loads((PAPER_ROOT / "common_support" / window / "evo_crosscheck.json").read_text())
        for row in metrics:
            match = re.fullmatch(r"(.+)_r([123])", row["arm"])
            if not match:
                continue
            arm, repeat = match.groups()
            evo_row = evo_data["arms"][row["arm"]]
            repeats.append(
                {
                    "window_id": window,
                    "arm": arm,
                    "repeat": int(repeat),
                    "common_poses": int(row["matched_count"]),
                    "rpe_pairs": int(row["rpe_pairs"]),
                    "fixed_se3_ape_rmse_m": float(row["fixed_se3_ape_rmse_m"]),
                    "fixed_se3_rpe_rmse_m": float(row["fixed_se3_rpe_rmse_m"]),
                    "sim3_scale": float(row["sim3_scale"]),
                    "sim3_ape_rmse_m": float(row["sim3_ape_rmse_m"]),
                    "sim3_rpe_rmse_m": float(row["sim3_rpe_rmse_m"]),
                    "fixed_evo_ape_abs_diff_m": evo_row["fixed_se3"]["ape_abs_diff_m"],
                    "fixed_evo_rpe_abs_diff_m": evo_row["fixed_se3"]["rpe_abs_diff_m"],
                    "sim3_evo_ape_abs_diff_m": evo_row["sim3"]["ape_abs_diff_m"],
                    "sim3_evo_rpe_abs_diff_m": evo_row["sim3"]["rpe_abs_diff_m"],
                }
            )
    grouped: list[dict[str, object]] = []
    admitted = [str(row["window_id"]) for row in status_rows if row["status"] == "PASS"]
    for window in admitted:
        for arm in ARMS:
            cells = [row for row in repeats if row["window_id"] == window and row["arm"] == arm]
            if len(cells) != 3:
                raise RuntimeError(f"accuracy repeat count is not 3: {window}/{arm}")
            grouped.append(
                {
                    "window_id": window,
                    "arm": arm,
                    "arm_display": ARM_DISPLAY[arm],
                    "repeats": 3,
                    "common_poses": cells[0]["common_poses"],
                    "rpe_pairs": cells[0]["rpe_pairs"],
                    "fixed_se3_ape_rmse_median_m": finite_median([float(c["fixed_se3_ape_rmse_m"]) for c in cells]),
                    "fixed_se3_ape_rmse_range_m": range_text([float(c["fixed_se3_ape_rmse_m"]) for c in cells]),
                    "fixed_se3_rpe_rmse_median_m": finite_median([float(c["fixed_se3_rpe_rmse_m"]) for c in cells]),
                    "fixed_se3_rpe_rmse_range_m": range_text([float(c["fixed_se3_rpe_rmse_m"]) for c in cells]),
                    "sim3_scale_median": finite_median([float(c["sim3_scale"]) for c in cells]),
                    "sim3_scale_range": range_text([float(c["sim3_scale"]) for c in cells]),
                    "sim3_ape_rmse_median_m": finite_median([float(c["sim3_ape_rmse_m"]) for c in cells]),
                    "sim3_ape_rmse_range_m": range_text([float(c["sim3_ape_rmse_m"]) for c in cells]),
                    "sim3_rpe_rmse_median_m": finite_median([float(c["sim3_rpe_rmse_m"]) for c in cells]),
                    "sim3_rpe_rmse_range_m": range_text([float(c["sim3_rpe_rmse_m"]) for c in cells]),
                    "max_evo_abs_diff_m": max(
                        float(c[key]) for c in cells for key in (
                            "fixed_evo_ape_abs_diff_m", "fixed_evo_rpe_abs_diff_m",
                            "sim3_evo_ape_abs_diff_m", "sim3_evo_rpe_abs_diff_m",
                        )
                    ),
                }
            )
    write_csv(PAPER_ROOT / "accuracy_repeats.csv", repeats)
    accuracy_fields = [
        "window_id", "arm", "arm_display", "repeats", "common_poses", "rpe_pairs",
        "fixed_se3_ape_rmse_median_m", "fixed_se3_ape_rmse_range_m",
        "fixed_se3_rpe_rmse_median_m", "fixed_se3_rpe_rmse_range_m",
        "sim3_scale_median", "sim3_scale_range",
        "sim3_ape_rmse_median_m", "sim3_ape_rmse_range_m",
        "sim3_rpe_rmse_median_m", "sim3_rpe_rmse_range_m", "max_evo_abs_diff_m",
    ]
    write_csv(PAPER_ROOT / "accuracy.csv", grouped, accuracy_fields)
    return repeats, grouped


def markdown_table(rows: list[list[str]], header: list[str]) -> str:
    lines = ["| " + " | ".join(header) + " |", "|" + "|".join("---" for _ in header) + "|"]
    lines.extend("| " + " | ".join(row) + " |" for row in rows)
    return "\n".join(lines)


def write_report(runability: list[dict[str, str]], status: list[dict[str, object]], accuracy: list[dict[str, object]]) -> None:
    candidates = read_csv(PAPER_ROOT / "candidate_windows.csv")
    status_by_window = {str(row["window_id"]): row for row in status}
    run_rows: list[list[str]] = []
    for candidate in candidates:
        window = candidate["window_id"]
        cells = {row["arm"]: row for row in runability if row["window_id"] == window}
        values = []
        for arm in ARMS:
            cell = cells.get(arm, {})
            if candidate["eligibility"] != "ELIGIBLE":
                values.append("NOT ELIGIBLE")
            elif cell.get("frontend_runable") != "PASS":
                values.append(f"FE FAIL ({cell.get('frontend_coverage','')})")
            elif cell.get("candidate_status") != "FRONTEND_PASS":
                values.append(f"FE PASS ({cell.get('frontend_coverage','')}) / window pruned")
            elif cell.get("arm_window_pass"):
                counts = [cell.get(f"repeat{i}_pose_count", "") for i in range(1, 4)]
                cover = [cell.get(f"repeat{i}_coverage", "") for i in range(1, 4)]
                values.append(f"{cell['arm_window_pass']} poses={','.join(counts)} cov={','.join(cover)}")
            else:
                values.append("FE PASS / backend not run")
        run_rows.append([window, candidate["role"], *values])
    accuracy_rows = [
        [
            str(row["window_id"]), str(row["arm_display"]),
            f"{float(row['fixed_se3_ape_rmse_median_m']):.3f} [{row['fixed_se3_ape_rmse_range_m']}]",
            f"{float(row['fixed_se3_rpe_rmse_median_m']):.3f} [{row['fixed_se3_rpe_rmse_range_m']}]",
            f"{float(row['sim3_scale_median']):.3f} [{row['sim3_scale_range']}]",
            f"{float(row['sim3_ape_rmse_median_m']):.3f}",
            f"{float(row['sim3_rpe_rmse_median_m']):.3f}",
        ]
        for row in accuracy
    ]
    by_accuracy = {(str(row["window_id"]), str(row["arm"])): row for row in accuracy}
    comparison_rows: list[list[str]] = []
    xfeat_klt_ape_wins = 0
    xfeat_klt_rpe_wins = 0
    xfeat_splg_ape_wins = 0
    xfeat_splg_rpe_wins = 0
    comparison_windows = sorted({str(row["window_id"]) for row in accuracy})
    for window in comparison_windows:
        klt = by_accuracy[(window, "klt")]
        splg = by_accuracy[(window, "splg")]
        xfeat = by_accuracy[(window, "xfeat_seed")]
        def change(metric: str, baseline: dict[str, object]) -> float:
            return 100.0 * (float(xfeat[metric]) / float(baseline[metric]) - 1.0)
        xk_ape = change("fixed_se3_ape_rmse_median_m", klt)
        xk_rpe = change("fixed_se3_rpe_rmse_median_m", klt)
        xs_ape = change("fixed_se3_ape_rmse_median_m", splg)
        xs_rpe = change("fixed_se3_rpe_rmse_median_m", splg)
        xfeat_klt_ape_wins += xk_ape < 0.0
        xfeat_klt_rpe_wins += xk_rpe < 0.0
        xfeat_splg_ape_wins += xs_ape < 0.0
        xfeat_splg_rpe_wins += xs_rpe < 0.0
        cells = {row["arm"]: row for row in runability if row["window_id"] == window}
        klt_splg_identical = cells["klt"]["feature_bag_sha256"] == cells["splg"]["feature_bag_sha256"]
        comparison_rows.append(
            [
                window, f"{xk_ape:+.2f}%", f"{xk_rpe:+.2f}%",
                f"{xs_ape:+.2f}%", f"{xs_rpe:+.2f}%",
                "KLT=SP bag" if klt_splg_identical else "all distinct",
            ]
        )
    admitted = sorted({str(row["window_id"]) for row in accuracy})
    backend_candidates = all_arm_backend_windows(runability)
    frontend_survivors = sorted({
        row["window_id"] for row in runability
        if row["candidate_status"] == "FRONTEND_PASS" and row["frontend_runable"] == "PASS"
        and row["exclusion_status"] == "INCLUDED"
    })
    max_evo = max((float(row["max_evo_abs_diff_m"]) for row in accuracy), default=math.nan)
    conclusion = (
        f"共同支撑最终为 n={len(admitted)} 个窗口（{', '.join(admitted) or 'none'}）。"
        "精度数值只能解释为与 COLMAP/proxy 的一致程度。"
    )
    if len(admitted) < 3:
        conclusion += " 未达到目标 n≥3，因此不支持可辩护的跨窗持久性/收敛性主张。"
    else:
        conclusion += " 达到 n≥3 的最低跨窗证据规模，但仍应把结论限定为这些预注册窗口。"
    text = f"""# AQUA-FE same-backend long-window supplement

## 定位与结论

本表是固定 `VINS-Fusion-origin` 后端的**前端隔离对比**，对应 SuperVINS/XFeat-VINS 的同一设计空间。HFNet-SLAM 使用关键帧与局部 BA 后端，属于不同设计空间，只能单列为 reference；本文不作整系统对 HFNet-SLAM 的精度声明。

这里的“front+back 闭环”指从前端 feature bag、冻结 VINS 后端到共同支撑评测的完整实验闭环，不表示启用了 pose-graph 回环模块；canonical YAML 保持冻结值 `loop_closure: 0`，因此不作回环检测或 pose-graph 优化收敛声明。

Runability 是第一指标，目标是检验“前端持久性是否使固定后端保持尺度可观并收敛”，不是厘米级定位。{conclusion}

## 预注册与执行范围

- 结果盲合同见 [preregistration.md](preregistration.md)，冻结候选见 [candidate_windows.csv](candidate_windows.csv)。12 个枚举窗口全部保留；11 个 metadata-eligible，1 个因 proxy 支撑不足预先排除。
- 三臂均为 KLT、SP+LG、XFeat-seed；每个后端存活窗每臂重复 3 次。门保持 30 common poses / 10 s / 70% coverage / 10 个 1 s RPE pairs / 九轨迹共同支撑。
- Stage-2 三臂前端共同存活窗数为 {len(frontend_survivors)}；三臂后端均通过窗数为 {len(backend_candidates)}；共同支撑精度窗数为 {len(admitted)}。
- `/mnt/data` 在执行前已满（约 2.8 GiB free，显示 100%）；所有新产物写在根分区 workspace。AFRL 派生输入在三臂完成并留下 hash receipt 后回收。

## Runability 总表

{markdown_table(run_rows, ['window', 'role', 'KLT', 'SP+LG', 'XFeat-seed'])}

完整逐臂/逐重复数据、feature bag 路径、哈希、pose count、span 与 coverage 见 [runability.csv](runability.csv)。超过 350 特征预算的 learned bag 按冻结 integrity gate 失败，未进入后端；三臂 bag 全相同的窗口必须排除（本轮 pairwise 相同但非 all-three 的情形只限制对应 pair 的归因）。

## 共同支撑精度

主指标是各轨迹独立的 fixed-scale proper SE(3)，禁止尺度拟合。Sim(3) 仅作为显式二级诊断，拟合 scale 单列，不能挽救 runability 或共同支撑门。所有九条轨迹使用同一 1 Hz pose intersection 与同一 1 s RPE pairs。

{markdown_table(accuracy_rows, ['window', 'arm', 'SE3 APE RMSE median [range] m', 'SE3 RPE RMSE median [range] m', 'Sim3 scale median [range]', 'Sim3 APE m', 'Sim3 RPE m']) if accuracy_rows else '无窗口通过九轨迹共同支撑门；`accuracy.csv` 仅含表头。'}

`evo` 对 SE(3)/Sim(3) APE 和分段 1 s RPE 做独立交叉检查；最大绝对差为 {max_evo if math.isfinite(max_evo) else 'NA'} m。逐重复与差值见 [accuracy_repeats.csv](accuracy_repeats.csv)。

### XFeat 的逐窗变化（负值表示 XFeat 更低）

{markdown_table(comparison_rows, ['window', 'APE vs KLT', 'RPE vs KLT', 'APE vs SP+LG', 'RPE vs SP+LG', 'input audit'])}

在四个独立窗口上，XFeat-seed 相对 KLT 的 fixed-scale APE 中位数为 {xfeat_klt_ape_wins}/4 窗更低、RPE 为 {xfeat_klt_rpe_wins}/4 窗更低，因此**不支持 accuracy-level universal no-harm**。相对 SP+LG，XFeat-seed 的 APE 与 RPE 中位数均为 {xfeat_splg_ape_wins}/4 和 {xfeat_splg_rpe_wins}/4 窗更低；这是 n=4 的逐窗方向性证据，不把三次 replay 当成额外科学样本，也不声称显著性。

## 可支持的叙事边界

- 四个存活窗的 36/36 replay 全部初始化并过 coverage，三臂的 pose count/coverage 在每窗几乎相同；因此本批数据支持“持久输入足以让冻结后端稳定收敛”，但**没有观察到 arm-specific convergence failure，不能据此声称 XFeat 持久性决定了相对 KLT 的收敛**。
- 其余 AFRL 窗大多因 learned bag 实际超过 350 而在 Stage-2 integrity gate 被剪枝。这是预算合同失败，不是冷启动或后端发散，不能拿来支持“XFeat 更可运行”。
- A06 首窗的 fitted scale 明显偏离 1（KLT/XFeat 中位数约 1.856/2.059），且 Sim(3) 显著降低 APE，说明 fixed-scale 误差中含尺度不可观成分；A06 第二窗、AFRL 与 Harbor 的胜负则不一致。故“前端持久性 → 尺度可观”在本 n=4 上也不是普遍单调关系。
- XFeat-seed 相对 KLT、以及 XFeat-seed 对 SP+LG 的 APE/RPE 只按上述共同支撑窗口逐窗解释；不使用失败窗改变精度分母，也不把 Sim(3) 数字冒充 fixed-scale 主结果。
- proxy 不是独立 GT；APE/RPE 表示与 proxy 的一致程度，不是绝对定位误差。窗口是科学重复单位，三次 replay 只用于中位数与范围。

## 公平性与产物

- [backend_config_audit.csv](backend_config_audit.csv)：每窗 9/9 replay 读取同一 canonical YAML 字节与同一 camera YAML；后端二进制不重编译。
- [common_support_status.csv](common_support_status.csv)：所有后端共同存活窗的共同支撑门结果。
- [artifacts.sha256](artifacts.sha256)：feature bags、canonical configs、`vio.csv`、`vins.log`、CSV/报告及执行脚本哈希。
- 运行产物根目录：`{RUNTIME_ROOT}`。一次 A06 duplicate-writer 半成品，以及一次 scratch-cleanup runner 错误产生的空目录/被中断 partial replay，均已保留在 `quarantine/`；二者从正式总账、评分与哈希清单排除。scratch 错误发生前已经写 receipt 的正式 replay 保留并通过最终哈希/轨迹审计。
"""
    (PAPER_ROOT / "report.md").write_text(text, encoding="utf-8")


def write_manifest() -> None:
    paths: list[Path] = []
    for name in (
        "preregistration.md", "candidate_windows.csv", "runability.csv", "accuracy.csv",
        "accuracy_repeats.csv", "backend_config_audit.csv", "common_support_status.csv", "report.md",
    ):
        paths.append(PAPER_ROOT / name)
    paths.extend(path for path in (PAPER_ROOT / "common_support").rglob("*") if path.is_file())
    for base in (
        RUNTIME_ROOT / "backend_canonical", RUNTIME_ROOT / "replays",
        RUNTIME_ROOT / "shadow_root/logs", RUNTIME_ROOT / "prepared",
    ):
        if not base.exists():
            continue
        for path in base.rglob("*"):
            if not path.is_file() or "quarantine" in path.parts:
                continue
            if path.name in {
                "features.bag", "vio.csv", "vins.log", "vins_same_backend.yaml",
                "supplement_frontend_receipt.json", "replay_receipt.txt",
                "materialization_audit.json", "reclaimed_prepared_input.json",
            } or path.suffix == ".yaml" and "backend_canonical" in path.parts:
                paths.append(path)
    paths.extend(
        ROOT / "scripts" / name for name in (
            "run_frontend_same_backend_comparison_supplement.py",
            "analyze_frontend_same_backend_comparison_supplement.py",
            "run_frontend_same_backend_comparison_supplement_backend.py",
            "run_frontend_same_backend_comparison_supplement_backend_cell.sh",
            "evaluate_vins_common_support_dual_scale.py",
            "finalize_frontend_same_backend_comparison_supplement.py",
        )
    )
    unique = sorted({path.resolve() for path in paths if path.is_file()}, key=str)
    (PAPER_ROOT / "artifacts.sha256").write_text(
        "".join(f"{sha256(path)}  {path}\n" for path in unique), encoding="utf-8"
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("stage", choices=("collect", "evaluate", "report", "all"), default="all", nargs="?")
    args = parser.parse_args()
    frontend.verify_frozen()
    rows = update_runability()
    status: list[dict[str, object]] = []
    if args.stage in {"evaluate", "all"}:
        status = evaluate(rows)
    elif (PAPER_ROOT / "common_support_status.csv").is_file():
        status = read_csv(PAPER_ROOT / "common_support_status.csv")
    repeats, accuracy = collect_accuracy(status)
    if args.stage in {"report", "all"}:
        write_report(rows, status, accuracy)
    if not (PAPER_ROOT / "report.md").is_file():
        (PAPER_ROOT / "report.md").write_text("# Supplement incomplete\n", encoding="utf-8")
    write_manifest()
    print(f"runability={PAPER_ROOT / 'runability.csv'}")
    print(f"accuracy={PAPER_ROOT / 'accuracy.csv'} rows={len(accuracy)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
