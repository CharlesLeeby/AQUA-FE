from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np


@dataclass
class GeometryStats:
    num_pairs: int
    fundamental_inliers: int
    fundamental_inlier_ratio: float
    homography_inliers: int
    homography_inlier_ratio: float
    median_epipolar_error: float
    median_homography_error: float
    planar_score: float


def _median_epipolar_error(f_mat: np.ndarray, pts0: np.ndarray, pts1: np.ndarray) -> float:
    if f_mat is None or len(pts0) == 0:
        return float("nan")
    p0 = np.concatenate([pts0, np.ones((len(pts0), 1), dtype=np.float32)], axis=1)
    p1 = np.concatenate([pts1, np.ones((len(pts1), 1), dtype=np.float32)], axis=1)
    lines1 = (f_mat @ p0.T).T
    numer = np.abs(np.sum(p1 * lines1, axis=1))
    denom = np.sqrt(lines1[:, 0] ** 2 + lines1[:, 1] ** 2) + 1e-6
    return float(np.median(numer / denom))


def _median_homography_error(h_mat: np.ndarray, pts0: np.ndarray, pts1: np.ndarray) -> float:
    if h_mat is None or len(pts0) == 0:
        return float("nan")
    pts0_h = np.concatenate([pts0, np.ones((len(pts0), 1), dtype=np.float32)], axis=1)
    warped = (h_mat @ pts0_h.T).T
    warped = warped[:, :2] / (warped[:, 2:3] + 1e-6)
    return float(np.median(np.linalg.norm(warped - pts1, axis=1)))


def validate_geometry(
    pts0: np.ndarray,
    pts1: np.ndarray,
    ransac_reproj_threshold: float = 1.0,
) -> tuple[GeometryStats, np.ndarray]:
    pts0 = np.asarray(pts0, dtype=np.float32).reshape(-1, 2)
    pts1 = np.asarray(pts1, dtype=np.float32).reshape(-1, 2)
    n = min(len(pts0), len(pts1))
    if n < 8:
        stats = GeometryStats(n, 0, 0.0, 0, 0.0, float("nan"), float("nan"), 0.0)
        return stats, np.zeros((n,), dtype=bool)

    f_mat, f_mask = cv2.findFundamentalMat(
        pts0,
        pts1,
        method=cv2.FM_RANSAC,
        ransacReprojThreshold=ransac_reproj_threshold,
        confidence=0.99,
    )
    if f_mask is None:
        f_inlier_mask = np.zeros((n,), dtype=bool)
    else:
        f_inlier_mask = f_mask.reshape(-1).astype(bool)

    h_mat, h_mask = cv2.findHomography(pts0, pts1, cv2.RANSAC, 3.0)
    if h_mask is None:
        h_inlier_mask = np.zeros((n,), dtype=bool)
    else:
        h_inlier_mask = h_mask.reshape(-1).astype(bool)

    f_inliers = int(np.sum(f_inlier_mask))
    h_inliers = int(np.sum(h_inlier_mask))
    f_ratio = float(f_inliers / n) if n else 0.0
    h_ratio = float(h_inliers / n) if n else 0.0
    planar_score = float(h_ratio / (f_ratio + 1e-6))

    stats = GeometryStats(
        num_pairs=n,
        fundamental_inliers=f_inliers,
        fundamental_inlier_ratio=f_ratio,
        homography_inliers=h_inliers,
        homography_inlier_ratio=h_ratio,
        median_epipolar_error=_median_epipolar_error(f_mat, pts0, pts1),
        median_homography_error=_median_homography_error(h_mat, pts0, pts1),
        planar_score=planar_score,
    )
    return stats, f_inlier_mask

