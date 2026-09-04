from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import numpy as np

from uw_frontend.quality.feature_confidence import quality_to_sigma


GEOMETRY_MODES = {
    "normal",
    "degraded_texture",
    "planar_near_wall",
    "severe_low_texture",
}


@dataclass(frozen=True)
class ConformalBucket:
    name: str
    count: int
    quantile: float
    uses_global: bool = False


@dataclass
class MondrianConformalCalibrator:
    """Split/Mondrian conformal wrapper for per-feature reliability.

    The base reliability model still predicts q_i. This wrapper stores
    nonconformity quantiles either globally or per bucket and can convert them
    to q-intervals or a conservative sigma scaling for backend weighting.
    """

    alpha: float
    score_type: str
    bucket_column: str = "auto"
    min_bucket_rows: int = 200
    global_quantile: float = 0.0
    buckets: dict[str, ConformalBucket] | None = None
    sigma_scale_floor: float = 1.0
    metadata: dict[str, object] | None = None

    def __post_init__(self) -> None:
        if not 0.0 < float(self.alpha) < 1.0:
            raise ValueError(f"alpha must be in (0, 1), got {self.alpha}")
        if self.score_type not in {"survival_abs_error", "residual_ratio"}:
            raise ValueError(f"unsupported score_type: {self.score_type}")
        if self.buckets is None:
            self.buckets = {}
        if self.metadata is None:
            self.metadata = {}

    @classmethod
    def fit(
        cls,
        q_hat: np.ndarray,
        *,
        alpha: float = 0.10,
        score_type: str = "survival_abs_error",
        labels: np.ndarray | None = None,
        residuals: np.ndarray | None = None,
        sigma_hat: np.ndarray | None = None,
        buckets: Iterable[object] | None = None,
        bucket_column: str = "auto",
        min_bucket_rows: int = 200,
        sigma_scale_floor: float = 1.0,
        metadata: dict[str, object] | None = None,
    ) -> "MondrianConformalCalibrator":
        q = np.clip(np.asarray(q_hat, dtype=np.float32).reshape(-1), 0.0, 1.0)
        scores = nonconformity_scores(
            q,
            score_type=score_type,
            labels=labels,
            residuals=residuals,
            sigma_hat=sigma_hat,
        )
        valid = np.isfinite(scores)
        if not np.any(valid):
            raise ValueError("no finite nonconformity scores available for conformal fit")
        scores = scores[valid]
        if buckets is None:
            bucket_arr = np.full((len(q),), "global", dtype=object)
        else:
            bucket_arr = np.asarray(list(buckets), dtype=object).reshape(-1)
            if len(bucket_arr) != len(q):
                raise ValueError("buckets must have the same length as q_hat")
        bucket_arr = bucket_arr[valid]

        global_q = conformal_quantile(scores, alpha)
        bucket_models: dict[str, ConformalBucket] = {}
        for bucket_name in sorted({str(item) for item in bucket_arr}):
            mask = bucket_arr.astype(str) == bucket_name
            count = int(np.count_nonzero(mask))
            if count < int(min_bucket_rows):
                bucket_models[bucket_name] = ConformalBucket(
                    name=bucket_name,
                    count=count,
                    quantile=float(global_q),
                    uses_global=True,
                )
                continue
            bucket_models[bucket_name] = ConformalBucket(
                name=bucket_name,
                count=count,
                quantile=float(conformal_quantile(scores[mask], alpha)),
                uses_global=False,
            )

        return cls(
            alpha=float(alpha),
            score_type=str(score_type),
            bucket_column=str(bucket_column),
            min_bucket_rows=int(min_bucket_rows),
            global_quantile=float(global_q),
            buckets=bucket_models,
            sigma_scale_floor=float(sigma_scale_floor),
            metadata=dict(metadata or {}),
        )

    @classmethod
    def from_json(cls, path: str | Path) -> "MondrianConformalCalibrator":
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        buckets = {
            name: ConformalBucket(
                name=str(item["name"]),
                count=int(item["count"]),
                quantile=float(item["quantile"]),
                uses_global=bool(item.get("uses_global", False)),
            )
            for name, item in data.get("buckets", {}).items()
        }
        return cls(
            alpha=float(data["alpha"]),
            score_type=str(data["score_type"]),
            bucket_column=str(data.get("bucket_column", "auto")),
            min_bucket_rows=int(data.get("min_bucket_rows", 200)),
            global_quantile=float(data["global_quantile"]),
            buckets=buckets,
            sigma_scale_floor=float(data.get("sigma_scale_floor", 1.0)),
            metadata=dict(data.get("metadata", {})),
        )

    def to_json(self, path: str | Path) -> None:
        out = {
            "alpha": float(self.alpha),
            "score_type": self.score_type,
            "bucket_column": self.bucket_column,
            "min_bucket_rows": int(self.min_bucket_rows),
            "global_quantile": float(self.global_quantile),
            "sigma_scale_floor": float(self.sigma_scale_floor),
            "metadata": self.metadata or {},
            "buckets": {
                name: {
                    "name": bucket.name,
                    "count": int(bucket.count),
                    "quantile": float(bucket.quantile),
                    "uses_global": bool(bucket.uses_global),
                }
                for name, bucket in sorted((self.buckets or {}).items())
            },
        }
        output = Path(path)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(out, indent=2, sort_keys=True), encoding="utf-8")

    def quantiles_for(self, buckets: Iterable[object] | None, count: int | None = None) -> np.ndarray:
        if buckets is None:
            if count is None:
                raise ValueError("count is required when buckets is None")
            return np.full((int(count),), float(self.global_quantile), dtype=np.float32)
        values = []
        for item in buckets:
            key = str(item)
            model = (self.buckets or {}).get(key)
            values.append(float(model.quantile) if model is not None else float(self.global_quantile))
        return np.asarray(values, dtype=np.float32)

    def q_interval(
        self,
        q_hat: np.ndarray,
        buckets: Iterable[object] | None = None,
    ) -> tuple[np.ndarray, np.ndarray]:
        q = np.clip(np.asarray(q_hat, dtype=np.float32).reshape(-1), 0.0, 1.0)
        q_width = self.quantiles_for(buckets, count=len(q))
        return np.clip(q - q_width, 0.0, 1.0), np.clip(q + q_width, 0.0, 1.0)

    def backend_quality(
        self,
        q_hat: np.ndarray,
        buckets: Iterable[object] | None = None,
        *,
        min_quality: float = 0.05,
    ) -> np.ndarray:
        """Return a conservative backend q_i induced by the conformal model.

        For survival-label conformal, the safe backend interpretation is the
        lower end of the q interval. For residual-ratio conformal, q_i itself is
        already the base point estimate and the residual threshold is carried by
        sigma(), so this method returns q_i with clipping.
        """

        q = np.clip(np.asarray(q_hat, dtype=np.float32).reshape(-1), 0.0, 1.0)
        if self.score_type == "survival_abs_error":
            q_lo, _ = self.q_interval(q, buckets)
            return np.clip(q_lo, float(min_quality), 1.0).astype(np.float32)
        return np.clip(q, float(min_quality), 1.0).astype(np.float32)

    def sigma(
        self,
        q_hat: np.ndarray,
        buckets: Iterable[object] | None = None,
        *,
        sigma_base: float = 1.0,
        eps: float = 1e-3,
        max_sigma: float = 10.0,
    ) -> np.ndarray:
        q = np.clip(np.asarray(q_hat, dtype=np.float32).reshape(-1), 0.0, 1.0)
        if self.score_type == "survival_abs_error":
            q_backend = self.backend_quality(q, buckets)
            return quality_to_sigma(
                q_backend,
                sigma_base=sigma_base,
                eps=eps,
                max_sigma=max_sigma,
            )
        scale = self.quantiles_for(buckets, count=len(q))
        scale = np.maximum(scale, float(self.sigma_scale_floor))
        base_sigma = quality_to_sigma(q, sigma_base=sigma_base, eps=eps, max_sigma=max_sigma)
        return np.clip(base_sigma * scale, float(sigma_base), float(max_sigma)).astype(np.float32)


def conformal_quantile(scores: np.ndarray, alpha: float) -> float:
    values = np.asarray(scores, dtype=np.float64).reshape(-1)
    values = values[np.isfinite(values)]
    if values.size == 0:
        raise ValueError("cannot compute conformal quantile from empty scores")
    values.sort()
    rank = int(math.ceil((values.size + 1) * (1.0 - float(alpha))))
    rank = min(max(rank, 1), values.size)
    return float(values[rank - 1])


def nonconformity_scores(
    q_hat: np.ndarray,
    *,
    score_type: str,
    labels: np.ndarray | None = None,
    residuals: np.ndarray | None = None,
    sigma_hat: np.ndarray | None = None,
) -> np.ndarray:
    q = np.clip(np.asarray(q_hat, dtype=np.float32).reshape(-1), 0.0, 1.0)
    if score_type == "survival_abs_error":
        if labels is None:
            raise ValueError("labels are required for survival_abs_error")
        y = np.asarray(labels, dtype=np.float32).reshape(-1)
        if len(y) != len(q):
            raise ValueError("labels must have the same length as q_hat")
        return np.abs(y - q).astype(np.float32)
    if score_type == "residual_ratio":
        if residuals is None:
            raise ValueError("residuals are required for residual_ratio")
        residual = np.asarray(residuals, dtype=np.float32).reshape(-1)
        if len(residual) != len(q):
            raise ValueError("residuals must have the same length as q_hat")
        if sigma_hat is None:
            sigma = quality_to_sigma(q)
        else:
            sigma = np.asarray(sigma_hat, dtype=np.float32).reshape(-1)
            if len(sigma) != len(q):
                raise ValueError("sigma_hat must have the same length as q_hat")
        return (np.maximum(0.0, residual) / np.maximum(1e-6, sigma)).astype(np.float32)
    raise ValueError(f"unsupported score_type: {score_type}")


def coverage_mask(
    calibrator: MondrianConformalCalibrator,
    q_hat: np.ndarray,
    *,
    labels: np.ndarray | None = None,
    residuals: np.ndarray | None = None,
    sigma_hat: np.ndarray | None = None,
    buckets: Iterable[object] | None = None,
) -> np.ndarray:
    q = np.clip(np.asarray(q_hat, dtype=np.float32).reshape(-1), 0.0, 1.0)
    threshold = calibrator.quantiles_for(buckets, count=len(q))
    scores = nonconformity_scores(
        q,
        score_type=calibrator.score_type,
        labels=labels,
        residuals=residuals,
        sigma_hat=sigma_hat,
    )
    return np.asarray(scores <= threshold, dtype=bool)


def assign_mondrian_buckets(
    frame,
    *,
    bucket_column: str = "auto",
    infer_geometry_mode: bool = True,
) -> np.ndarray:
    """Return bucket labels from a pandas-like frame.

    This function deliberately accepts any object with columns and __getitem__
    so the core calibrator does not depend on pandas at import time.
    """

    columns = set(getattr(frame, "columns", []))
    requested = str(bucket_column or "auto")
    if requested != "auto":
        if requested not in columns:
            raise ValueError(f"bucket column {requested!r} is missing")
        return _clean_bucket_values(frame[requested])
    if "geometry_mode" in columns:
        return _clean_bucket_values(frame["geometry_mode"])
    if infer_geometry_mode and _can_infer_geometry_mode(columns):
        return infer_geometry_mode_from_reliability_frame(frame)
    if "source" in columns:
        return _clean_bucket_values(frame["source"])
    return np.full((len(frame),), "global", dtype=object)


def infer_geometry_mode_from_reliability_frame(frame) -> np.ndarray:
    columns = set(getattr(frame, "columns", []))
    if not _can_infer_geometry_mode(columns):
        return np.full((len(frame),), "unknown", dtype=object)
    image_quality = _as_float_column(frame, "image_quality", default=1.0)
    texture_score = _as_float_column(frame, "texture_score", default=1.0)
    grid_coverage = _as_float_column(frame, "grid_coverage", default=1.0)
    flat_region = 1.0 - _as_float_column(frame, "flat_region_inv", default=1.0)
    degradation = 1.0 - _as_float_column(frame, "degradation_inv", default=1.0)
    dropout = 1.0 - _as_float_column(frame, "dropout_inv", default=1.0)
    h_inlier = _as_float_column(frame, "h_inlier_ratio", default=0.0)
    h_score = _as_float_column(frame, "homography_score", default=0.0)

    severe_votes = (
        (image_quality <= 0.20).astype(np.int32)
        + (texture_score <= 0.245).astype(np.int32)
        + (flat_region >= 0.90).astype(np.int32)
        + (grid_coverage <= 0.55).astype(np.int32)
    )
    planar = (dropout <= 0.20) & (h_inlier >= 0.94) & (h_score >= 0.90) & (
        (flat_region >= 0.85) | (texture_score <= 0.15)
    )
    degraded = (texture_score <= 0.38) | (image_quality <= 0.32) | (degradation >= 0.50) | (dropout >= 0.40)

    out = np.full((len(frame),), "normal", dtype=object)
    out[degraded] = "degraded_texture"
    out[planar] = "planar_near_wall"
    out[severe_votes >= 2] = "severe_low_texture"
    return out


def _can_infer_geometry_mode(columns: set[str]) -> bool:
    needed = {
        "image_quality",
        "texture_score",
        "grid_coverage",
        "flat_region_inv",
        "degradation_inv",
        "dropout_inv",
    }
    return needed.issubset(columns)


def _clean_bucket_values(values) -> np.ndarray:
    arr = np.asarray(values, dtype=object).reshape(-1)
    out = []
    for item in arr:
        text = str(item)
        if text == "" or text.lower() in {"nan", "none"}:
            text = "unknown"
        out.append(text)
    return np.asarray(out, dtype=object)


def _as_float_column(frame, name: str, default: float) -> np.ndarray:
    columns = set(getattr(frame, "columns", []))
    if name not in columns:
        return np.full((len(frame),), float(default), dtype=np.float32)
    arr = np.asarray(frame[name], dtype=np.float32).reshape(-1)
    arr[~np.isfinite(arr)] = float(default)
    return arr
