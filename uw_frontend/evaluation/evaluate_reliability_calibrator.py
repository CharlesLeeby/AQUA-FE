from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

from uw_frontend.quality.feature_confidence import ReliabilityCalibrator
from uw_frontend.quality.reliability_features import RELIABILITY_FEATURE_NAMES


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate a feature reliability calibrator on held-out logs.")
    parser.add_argument("--model-json", required=True)
    parser.add_argument("--input-csv", action="append", required=True)
    parser.add_argument("--report-md", required=True)
    args = parser.parse_args()

    calibrator = ReliabilityCalibrator.from_json(args.model_json)
    df = pd.concat([pd.read_csv(path) for path in args.input_csv], ignore_index=True)
    df = df.dropna(subset=["label", *RELIABILITY_FEATURE_NAMES])
    df = df[(df["label"] == 0) | (df["label"] == 1)].reset_index(drop=True)
    x = df[calibrator.feature_names].to_numpy(dtype=np.float32)
    y = df["label"].to_numpy(dtype=np.float32)
    base = np.clip(df["base_quality"].to_numpy(dtype=np.float32), 0.0, 1.0)
    pred = calibrator.predict(x, base, df["source"].to_numpy(dtype=object))

    report = _make_report(df, y, base, pred)
    out = Path(args.report_md)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(report, encoding="utf-8")
    print(f"wrote {out}")
    print(report)
    return 0


def _make_report(df: pd.DataFrame, y: np.ndarray, base: np.ndarray, pred: np.ndarray) -> str:
    lines = ["# Held-Out Reliability Evaluation", ""]
    lines.append(f"- rows: {len(df)}")
    lines.append(f"- positive_rate: {float(y.mean()):.4f}")
    lines.append(f"- base_brier: {_brier(y, base):.4f}")
    lines.append(f"- calibrated_brier: {_brier(y, pred):.4f}")
    lines.append(f"- base_ece: {_ece(y, base):.4f}")
    lines.append(f"- calibrated_ece: {_ece(y, pred):.4f}")
    lines.append("")
    lines.append("## By Source")
    lines.append("| source | count | positive_rate | base_brier | calibrated_brier |")
    lines.append("| --- | ---: | ---: | ---: | ---: |")
    for source, group in df.groupby("source"):
        idx = group.index.to_numpy()
        lines.append(
            f"| {source} | {len(group)} | {float(y[idx].mean()):.4f} | "
            f"{_brier(y[idx], base[idx]):.4f} | {_brier(y[idx], pred[idx]):.4f} |"
        )
    lines.append("")
    lines.append("## Calibrated Reliability Bins")
    lines.append("| bin | count | pred_mean | empirical |")
    lines.append("| --- | ---: | ---: | ---: |")
    for lo in np.linspace(0.0, 0.9, 10):
        hi = lo + 0.1
        mask = (pred >= lo) & ((pred < hi) if hi < 1.0 else (pred <= hi))
        if not np.any(mask):
            continue
        lines.append(
            f"| {lo:.1f}-{hi:.1f} | {int(mask.sum())} | {float(pred[mask].mean()):.4f} | {float(y[mask].mean()):.4f} |"
        )
    return "\n".join(lines) + "\n"


def _brier(y: np.ndarray, p: np.ndarray) -> float:
    return float(np.mean((np.clip(p, 0.0, 1.0) - y) ** 2))


def _ece(y: np.ndarray, p: np.ndarray, bins: int = 10) -> float:
    total = len(y)
    if total == 0:
        return 0.0
    ece = 0.0
    p = np.clip(p, 0.0, 1.0)
    for lo in np.linspace(0.0, 1.0 - 1.0 / bins, bins):
        hi = lo + 1.0 / bins
        mask = (p >= lo) & ((p < hi) if hi < 1.0 else (p <= hi))
        if not np.any(mask):
            continue
        ece += float(mask.sum()) / total * abs(float(p[mask].mean()) - float(y[mask].mean()))
    return float(ece)


if __name__ == "__main__":
    raise SystemExit(main())
