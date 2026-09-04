from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

from uw_frontend.quality.reliability_features import RELIABILITY_FEATURE_NAMES


def main() -> int:
    parser = argparse.ArgumentParser(description="Train a lightweight feature reliability calibrator.")
    parser.add_argument("--input-csv", action="append", required=True, help="Reliability log CSV from run_frontend_eval.")
    parser.add_argument("--output-json", required=True)
    parser.add_argument("--report-md", required=True)
    parser.add_argument("--max-rows", type=int, default=250000)
    parser.add_argument("--epochs", type=int, default=700)
    parser.add_argument("--learning-rate", type=float, default=0.08)
    parser.add_argument("--l2", type=float, default=0.01)
    parser.add_argument("--blend", type=float, default=0.85)
    parser.add_argument("--source-specific", action="store_true", help="Train source-specific calibrators with global fallback.")
    parser.add_argument(
        "--source-specific-keys",
        default="",
        help="Comma-separated source keys to specialize. Empty means all eligible keys.",
    )
    parser.add_argument(
        "--source-grouping",
        choices=["coarse", "exact"],
        default="coarse",
        help="Use coarse learned/classical groups or exact track source names for source-specific models.",
    )
    parser.add_argument("--min-source-rows", type=int, default=1000)
    args = parser.parse_args()

    df = _load_logs([Path(path) for path in args.input_csv], args.max_rows)
    model = _fit_model(df, epochs=args.epochs, lr=args.learning_rate, l2=args.l2)
    x = df[RELIABILITY_FEATURE_NAMES].to_numpy(dtype=np.float32)
    y = df["label"].to_numpy(dtype=np.float32)
    pred = _predict_model(model, x)
    base = np.clip(df["base_quality"].to_numpy(dtype=np.float32), 0.0, 1.0)
    blended = args.blend * pred + (1.0 - args.blend) * base

    out = {
        "feature_names": RELIABILITY_FEATURE_NAMES,
        "mean": model["mean"].astype(float).tolist(),
        "scale": model["scale"].astype(float).tolist(),
        "weights": model["weights"].astype(float).tolist(),
        "bias": float(model["bias"]),
        "blend": float(args.blend),
        "train_rows": int(len(df)),
        "positive_rate": float(y.mean()),
    }
    source_models = {}
    if args.source_specific:
        requested_keys = {item.strip() for item in args.source_specific_keys.split(",") if item.strip()}
        for source_key, group in _source_groups(df, args.source_grouping).items():
            if requested_keys and source_key not in requested_keys:
                continue
            if len(group) < args.min_source_rows or group["label"].nunique() < 2:
                continue
            source_model = _fit_model(group, epochs=args.epochs, lr=args.learning_rate, l2=args.l2)
            source_models[source_key] = {
                "mean": source_model["mean"].astype(float).tolist(),
                "scale": source_model["scale"].astype(float).tolist(),
                "weights": source_model["weights"].astype(float).tolist(),
                "bias": float(source_model["bias"]),
                "blend": float(args.blend),
                "rows": int(len(group)),
                "positive_rate": float(group["label"].mean()),
            }
        out["source_models"] = source_models
    output_json = Path(args.output_json)
    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(json.dumps(out, indent=2), encoding="utf-8")

    if source_models:
        pred = _predict_source_specific(out, df, args.source_grouping)
        blended = args.blend * pred + (1.0 - args.blend) * base
    report = _make_report(
        df,
        y,
        pred,
        blended,
        np.asarray(out["weights"], dtype=np.float32),
        source_models,
        args.source_grouping,
    )
    report_md = Path(args.report_md)
    report_md.parent.mkdir(parents=True, exist_ok=True)
    report_md.write_text(report, encoding="utf-8")
    print(f"wrote {output_json}")
    print(f"wrote {report_md}")
    print(report)
    return 0


def _fit_model(df: pd.DataFrame, epochs: int, lr: float, l2: float) -> dict:
    x = df[RELIABILITY_FEATURE_NAMES].to_numpy(dtype=np.float32)
    y = df["label"].to_numpy(dtype=np.float32)
    mean = x.mean(axis=0)
    scale = x.std(axis=0)
    scale = np.where(scale > 1e-6, scale, 1.0).astype(np.float32)
    xz = (x - mean.reshape(1, -1)) / scale.reshape(1, -1)
    weights, bias = _train_logistic(xz, y, epochs=epochs, lr=lr, l2=l2)
    return {
        "mean": mean.astype(np.float32),
        "scale": scale.astype(np.float32),
        "weights": weights.astype(np.float32),
        "bias": float(bias),
    }


def _predict_model(model: dict, x: np.ndarray) -> np.ndarray:
    scale = np.where(model["scale"] > 1e-6, model["scale"], 1.0)
    xz = (x - model["mean"].reshape(1, -1)) / scale.reshape(1, -1)
    return _sigmoid(xz @ model["weights"] + float(model["bias"]))


def _predict_source_specific(out: dict, df: pd.DataFrame, grouping: str = "coarse") -> np.ndarray:
    x = df[RELIABILITY_FEATURE_NAMES].to_numpy(dtype=np.float32)
    global_model = {
        "mean": np.asarray(out["mean"], dtype=np.float32),
        "scale": np.asarray(out["scale"], dtype=np.float32),
        "weights": np.asarray(out["weights"], dtype=np.float32),
        "bias": float(out["bias"]),
    }
    pred = _predict_model(global_model, x)
    for source_key, group in _source_groups(df, grouping).items():
        model_data = out.get("source_models", {}).get(source_key)
        if model_data is None:
            continue
        model = {
            "mean": np.asarray(model_data["mean"], dtype=np.float32),
            "scale": np.asarray(model_data["scale"], dtype=np.float32),
            "weights": np.asarray(model_data["weights"], dtype=np.float32),
            "bias": float(model_data["bias"]),
        }
        idx = group.index.to_numpy()
        pred[idx] = _predict_model(model, x[idx])
    return pred.astype(np.float32)


def _source_groups(df: pd.DataFrame, grouping: str = "coarse") -> dict[str, pd.DataFrame]:
    groups: dict[str, pd.DataFrame] = {}
    if grouping == "exact":
        for source_key, group in df.groupby("source"):
            if not group.empty:
                groups[str(source_key)] = group
        return groups
    for source_key in {"klt", "gftt", "lk_recovery", "homography_recovery", "orb_recovery", "learned_recovery", "learned_init"}:
        mask = df["source"].map(lambda value: _source_key_from_name(str(value)) == source_key)
        group = df[mask]
        if not group.empty:
            groups[source_key] = group
    other = df[~df.index.isin(pd.concat(groups.values()).index if groups else [])]
    if not other.empty:
        groups["other"] = other
    return groups


def _source_key_from_name(source: str) -> str:
    if source in {"klt", "gftt", "lk_recovery", "homography_recovery", "orb_recovery"}:
        return source
    if source.endswith("_recovery"):
        return "learned_recovery"
    if source.endswith("_init"):
        return "learned_init"
    return "other"


def _load_logs(paths: list[Path], max_rows: int) -> pd.DataFrame:
    frames = []
    for path in paths:
        df = pd.read_csv(path)
        frames.append(df)
    merged = pd.concat(frames, ignore_index=True)
    merged = merged.dropna(subset=["label", *RELIABILITY_FEATURE_NAMES])
    merged = merged[(merged["label"] == 0) | (merged["label"] == 1)]
    if len(merged) > max_rows:
        pos = merged[merged["label"] == 1]
        neg = merged[merged["label"] == 0]
        rng = np.random.default_rng(7)
        keep_pos = min(len(pos), max_rows // 2)
        keep_neg = min(len(neg), max_rows - keep_pos)
        pos_idx = rng.choice(pos.index.to_numpy(), size=keep_pos, replace=False) if len(pos) > keep_pos else pos.index.to_numpy()
        neg_idx = rng.choice(neg.index.to_numpy(), size=keep_neg, replace=False) if len(neg) > keep_neg else neg.index.to_numpy()
        merged = merged.loc[np.concatenate([pos_idx, neg_idx])].sample(frac=1.0, random_state=7)
    return merged.reset_index(drop=True)


def _train_logistic(
    x: np.ndarray,
    y: np.ndarray,
    epochs: int,
    lr: float,
    l2: float,
) -> tuple[np.ndarray, float]:
    weights = np.zeros((x.shape[1],), dtype=np.float32)
    bias = float(np.log((y.mean() + 1e-3) / (1.0 - y.mean() + 1e-3)))
    n = max(1, len(y))
    for _ in range(int(epochs)):
        pred = _sigmoid(x @ weights + bias)
        error = pred - y
        grad_w = (x.T @ error) / n + float(l2) * weights
        grad_b = float(error.mean())
        weights -= float(lr) * grad_w.astype(np.float32)
        bias -= float(lr) * grad_b
    return weights.astype(np.float32), float(bias)


def _sigmoid(value: np.ndarray) -> np.ndarray:
    return (1.0 / (1.0 + np.exp(-np.clip(value, -30.0, 30.0)))).astype(np.float32)


def _make_report(
    df: pd.DataFrame,
    y: np.ndarray,
    pred: np.ndarray,
    blended: np.ndarray,
    weights: np.ndarray,
    source_models: dict | None = None,
    source_grouping: str = "coarse",
) -> str:
    lines = ["# Reliability Calibrator Report", ""]
    lines.append(f"- rows: {len(df)}")
    lines.append(f"- positive_rate: {float(y.mean()):.4f}")
    lines.append(f"- base_brier: {_brier(y, df['base_quality'].to_numpy(dtype=np.float32)):.4f}")
    lines.append(f"- calibrated_brier: {_brier(y, pred):.4f}")
    lines.append(f"- blended_brier: {_brier(y, blended):.4f}")
    lines.append(f"- calibrated_ece: {_ece(y, pred):.4f}")
    lines.append(f"- blended_ece: {_ece(y, blended):.4f}")
    lines.append("")
    lines.append("## Top Weights")
    order = np.argsort(-np.abs(weights))[:12]
    for idx in order:
        lines.append(f"- {RELIABILITY_FEATURE_NAMES[int(idx)]}: {float(weights[int(idx)]):.4f}")
    if source_models:
        lines.append("")
        lines.append("## Source-Specific Models")
        lines.append("| source | rows | positive_rate | calibrated_brier |")
        lines.append("| --- | ---: | ---: | ---: |")
        for source_key, group in _source_groups(df, source_grouping).items():
            if source_key not in source_models:
                continue
            idx = group.index.to_numpy()
            lines.append(
                f"| {source_key} | {len(group)} | {float(y[idx].mean()):.4f} | {_brier(y[idx], pred[idx]):.4f} |"
            )
    lines.append("")
    lines.append("## Reliability Bins")
    lines.append("| bin | count | pred_mean | empirical |")
    lines.append("| --- | ---: | ---: | ---: |")
    for lo in np.linspace(0.0, 0.9, 10):
        hi = lo + 0.1
        mask = (blended >= lo) & (blended < hi if hi < 1.0 else blended <= hi)
        if not np.any(mask):
            continue
        lines.append(
            f"| {lo:.1f}-{hi:.1f} | {int(mask.sum())} | {float(blended[mask].mean()):.4f} | {float(y[mask].mean()):.4f} |"
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
