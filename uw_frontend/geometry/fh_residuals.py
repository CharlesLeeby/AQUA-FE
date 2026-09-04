"""Deterministic, base-only F/H fitting and normalized residuals for P03."""

from __future__ import annotations

import hashlib
import json
import math
import struct
from dataclasses import dataclass

import cv2
import numpy as np

from uw_frontend.geometry.master_candidate_stream import ModelFitEvidence


@dataclass(frozen=True)
class FHConfig:
    seed: int = 20260730
    fundamental_threshold_px: float = 2.5
    homography_threshold_px: float = 5.0
    confidence: float = 0.999
    max_iterations: int = 2000
    min_fundamental_inliers: int = 8
    min_homography_inliers: int = 4
    e_max: float = 4.0

    def __post_init__(self) -> None:
        if self.seed != 20260730:
            raise ValueError("P03 F/H seed must be 20260730")
        if self.fundamental_threshold_px <= 0.0 or self.homography_threshold_px <= 0.0:
            raise ValueError("F/H residual thresholds must be positive")
        if not 0.0 < self.confidence < 1.0:
            raise ValueError("confidence must be in (0,1)")
        if self.max_iterations <= 0 or self.e_max <= 0.0:
            raise ValueError("max_iterations and e_max must be positive")


@dataclass(frozen=True)
class FHFitResult:
    evidence: ModelFitEvidence
    fundamental: np.ndarray | None
    homography: np.ndarray | None
    fundamental_inliers: tuple[bool, ...]
    homography_inliers: tuple[bool, ...]

    @property
    def has_valid_model(self) -> bool:
        return bool(self.evidence.valid_models)


@dataclass(frozen=True)
class ResidualDecision:
    normalized_residual: float
    accepted: bool
    best_model: str
    reason: str
    fundamental_residual_px: float | None
    homography_residual_px: float | None


def fit_base_models(
    track_ids: np.ndarray,
    previous_points: np.ndarray,
    current_points: np.ndarray,
    config: FHConfig | None = None,
) -> FHFitResult:
    """Fit F/H from sorted, finite K0 correspondences only."""

    cfg = config or FHConfig()
    ids, points0, points1 = _sorted_correspondences(
        track_ids, previous_points, current_points
    )
    fundamental = None
    homography = None
    f_mask = np.zeros((len(ids),), dtype=bool)
    h_mask = np.zeros((len(ids),), dtype=bool)

    if len(ids) >= 8:
        cv2.setRNGSeed(int(cfg.seed))
        try:
            matrix, mask = cv2.findFundamentalMat(
                points0,
                points1,
                cv2.FM_RANSAC,
                float(cfg.fundamental_threshold_px),
                float(cfg.confidence),
                int(cfg.max_iterations),
            )
        except (cv2.error, TypeError):
            matrix, mask = None, None
        candidate = _matrix3(matrix)
        candidate_mask = _mask(mask, len(ids))
        if candidate is not None and int(np.count_nonzero(candidate_mask)) >= cfg.min_fundamental_inliers:
            fundamental = candidate
            f_mask = candidate_mask

    if len(ids) >= 4:
        cv2.setRNGSeed(int(cfg.seed))
        try:
            matrix, mask = cv2.findHomography(
                points0,
                points1,
                cv2.RANSAC,
                float(cfg.homography_threshold_px),
                None,
                int(cfg.max_iterations),
                float(cfg.confidence),
            )
        except (cv2.error, TypeError):
            matrix, mask = None, None
        candidate = _matrix3(matrix)
        candidate_mask = _mask(mask, len(ids))
        if candidate is not None and int(np.count_nonzero(candidate_mask)) >= cfg.min_homography_inliers:
            homography = candidate
            h_mask = candidate_mask

    valid_models = tuple(
        name for name, matrix in (("F", fundamental), ("H", homography)) if matrix is not None
    )
    fit_hash = _fit_hash(ids, points0, points1, fundamental, homography, f_mask, h_mask, cfg)
    evidence = ModelFitEvidence(
        valid_models=valid_models,
        seed=cfg.seed,
        input_track_ids=tuple(int(value) for value in ids),
        thresholds=(
            ("F", float(cfg.fundamental_threshold_px)),
            ("H", float(cfg.homography_threshold_px)),
        ),
        fit_hash=fit_hash,
        arbitration="min_normalized_residual",
        confidence=float(cfg.confidence),
        max_iterations=int(cfg.max_iterations),
        e_max=float(cfg.e_max),
    )
    return FHFitResult(
        evidence=evidence,
        fundamental=fundamental,
        homography=homography,
        fundamental_inliers=tuple(bool(value) for value in f_mask),
        homography_inliers=tuple(bool(value) for value in h_mask),
    )


def classify_correspondences(
    fit: FHFitResult,
    previous_points: np.ndarray,
    current_points: np.ndarray,
    config: FHConfig | None = None,
) -> list[ResidualDecision]:
    evidence_thresholds = dict(fit.evidence.thresholds)
    cfg = config or FHConfig(
        seed=int(fit.evidence.seed),
        fundamental_threshold_px=float(evidence_thresholds.get("F", 2.5)),
        homography_threshold_px=float(evidence_thresholds.get("H", 5.0)),
        confidence=float(fit.evidence.confidence),
        max_iterations=int(fit.evidence.max_iterations),
        e_max=float(fit.evidence.e_max),
    )
    if abs(float(cfg.fundamental_threshold_px) - float(evidence_thresholds.get("F", cfg.fundamental_threshold_px))) > 1e-12:
        raise ValueError("F threshold differs from fitted model evidence")
    if abs(float(cfg.homography_threshold_px) - float(evidence_thresholds.get("H", cfg.homography_threshold_px))) > 1e-12:
        raise ValueError("H threshold differs from fitted model evidence")
    if int(cfg.seed) != int(fit.evidence.seed) or int(cfg.max_iterations) != int(fit.evidence.max_iterations):
        raise ValueError("F/H fit configuration identity differs from model evidence")
    if abs(float(cfg.confidence) - float(fit.evidence.confidence)) > 1e-12 or abs(float(cfg.e_max) - float(fit.evidence.e_max)) > 1e-12:
        raise ValueError("F/H confidence/e_max differs from model evidence")
    points0 = _points(previous_points)
    points1 = _points(current_points)
    if len(points0) != len(points1):
        raise ValueError("candidate point arrays must have equal length")
    if not fit.has_valid_model:
        return [
            ResidualDecision(
                normalized_residual=float(cfg.e_max),
                accepted=False,
                best_model="",
                reason="NO_VALID_BASE_MODEL",
                fundamental_residual_px=None,
                homography_residual_px=None,
            )
            for _ in range(len(points0))
        ]

    f_values = (
        epipolar_residual_px(fit.fundamental, points0, points1)
        if fit.fundamental is not None
        else np.full((len(points0),), np.inf, dtype=np.float64)
    )
    h_values = (
        homography_residual_px(fit.homography, points0, points1)
        if fit.homography is not None
        else np.full((len(points0),), np.inf, dtype=np.float64)
    )
    decisions: list[ResidualDecision] = []
    for f_value, h_value in zip(f_values, h_values):
        normalized = {
            "F": float(f_value) / float(cfg.fundamental_threshold_px),
            "H": float(h_value) / float(cfg.homography_threshold_px),
        }
        valid = {name: value for name, value in normalized.items() if name in fit.evidence.valid_models}
        best_model, raw_e = min(valid.items(), key=lambda item: (item[1], item[0]))
        e_value = min(max(0.0, float(raw_e)), float(cfg.e_max))
        accepted = math.isfinite(float(raw_e)) and float(raw_e) <= 1.0
        decisions.append(
            ResidualDecision(
                normalized_residual=e_value,
                accepted=accepted,
                best_model=best_model,
                reason="CORRECTNESS_PASS" if accepted else "FH_RESIDUAL_REJECT",
                fundamental_residual_px=(float(f_value) if fit.fundamental is not None else None),
                homography_residual_px=(float(h_value) if fit.homography is not None else None),
            )
        )
    return decisions


def epipolar_residual_px(
    fundamental: np.ndarray,
    previous_points: np.ndarray,
    current_points: np.ndarray,
) -> np.ndarray:
    matrix = _matrix3(fundamental)
    if matrix is None:
        raise ValueError("invalid fundamental matrix")
    points0 = _points(previous_points)
    points1 = _points(current_points)
    if len(points0) != len(points1):
        raise ValueError("point arrays must have equal length")
    homogeneous0 = np.column_stack((points0, np.ones((len(points0),), dtype=np.float64)))
    homogeneous1 = np.column_stack((points1, np.ones((len(points1),), dtype=np.float64)))
    lines1 = (matrix @ homogeneous0.T).T
    numerator = np.abs(np.sum(homogeneous1 * lines1, axis=1))
    denominator = np.sqrt(lines1[:, 0] ** 2 + lines1[:, 1] ** 2)
    return numerator / np.maximum(denominator, 1e-12)


def homography_residual_px(
    homography: np.ndarray,
    previous_points: np.ndarray,
    current_points: np.ndarray,
) -> np.ndarray:
    matrix = _matrix3(homography)
    if matrix is None:
        raise ValueError("invalid homography matrix")
    points0 = _points(previous_points)
    points1 = _points(current_points)
    if len(points0) != len(points1):
        raise ValueError("point arrays must have equal length")
    homogeneous0 = np.column_stack((points0, np.ones((len(points0),), dtype=np.float64)))
    projected = (matrix @ homogeneous0.T).T
    result = np.full((len(points0),), np.inf, dtype=np.float64)
    valid = np.abs(projected[:, 2]) > 1e-12
    result[valid] = np.linalg.norm(
        projected[valid, :2] / projected[valid, 2:3] - points1[valid], axis=1
    )
    return result


def _sorted_correspondences(track_ids, previous_points, current_points):
    ids = np.asarray(track_ids, dtype=np.int64).reshape(-1)
    points0 = _points(previous_points)
    points1 = _points(current_points)
    if len(ids) != len(points0) or len(ids) != len(points1):
        raise ValueError("IDs and K0 point arrays must have equal length")
    if len(ids) != len(set(int(value) for value in ids)):
        raise ValueError("K0 fit IDs must be unique")
    if np.any(ids < 0):
        raise ValueError("K0 fit IDs must be non-negative")
    finite = np.isfinite(points0).all(axis=1) & np.isfinite(points1).all(axis=1)
    ids = ids[finite]
    points0 = points0[finite]
    points1 = points1[finite]
    order = np.argsort(ids, kind="stable")
    return ids[order], points0[order], points1[order]


def _points(values) -> np.ndarray:
    array = np.asarray(values, dtype=np.float64)
    if array.size == 0:
        return np.empty((0, 2), dtype=np.float64)
    return array.reshape(-1, 2)


def _matrix3(value) -> np.ndarray | None:
    if value is None:
        return None
    array = np.asarray(value, dtype=np.float64)
    if array.ndim != 2 or array.shape[0] < 3 or array.shape[1] < 3:
        return None
    matrix = array[:3, :3].copy()
    return matrix if np.isfinite(matrix).all() else None


def _mask(value, count: int) -> np.ndarray:
    if value is None:
        return np.zeros((count,), dtype=bool)
    array = np.asarray(value).reshape(-1)
    if len(array) != count:
        return np.zeros((count,), dtype=bool)
    return array.astype(bool)


def _fit_hash(ids, points0, points1, fundamental, homography, f_mask, h_mask, cfg) -> str:
    payload = {
        "seed": cfg.seed,
        "fundamental_threshold_px": _float_token(cfg.fundamental_threshold_px),
        "homography_threshold_px": _float_token(cfg.homography_threshold_px),
        "confidence": _float_token(cfg.confidence),
        "max_iterations": cfg.max_iterations,
        "min_fundamental_inliers": cfg.min_fundamental_inliers,
        "min_homography_inliers": cfg.min_homography_inliers,
        "e_max": _float_token(cfg.e_max),
        "ids": [int(value) for value in ids],
        "points0": [[_float_token(x), _float_token(y)] for x, y in points0],
        "points1": [[_float_token(x), _float_token(y)] for x, y in points1],
        "fundamental": _matrix_payload(fundamental),
        "homography": _matrix_payload(homography),
        "fundamental_inliers": [bool(value) for value in f_mask],
        "homography_inliers": [bool(value) for value in h_mask],
    }
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("ascii")
    return hashlib.sha256(blob).hexdigest()


def _matrix_payload(matrix):
    if matrix is None:
        return None
    return [[_float_token(value) for value in row] for row in np.asarray(matrix, dtype=np.float64)]


def _float_token(value: float) -> str:
    return struct.pack(">d", float(value)).hex()


__all__ = [
    "FHConfig",
    "FHFitResult",
    "ResidualDecision",
    "classify_correspondences",
    "epipolar_residual_px",
    "fit_base_models",
    "homography_residual_px",
]
