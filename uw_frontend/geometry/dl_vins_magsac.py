from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np


DL_VINS_MAGSAC_PROBABILITY = 0.999
DL_VINS_MAGSAC_PIXEL_THRESHOLD = 1.0
DL_VINS_MAGSAC_MAX_ITERS = 200
DL_VINS_MAGSAC_MIN_CORRESPONDENCES = 8
DL_VINS_MAGSAC_MIN_INLIER_RATIO = 0.5


@dataclass(frozen=True)
class DlVinsMagsacResult:
    """Decision and evidence from the DL-VINS temporal geometry filter."""

    keep_mask: np.ndarray
    candidate_count: int
    inlier_count: int
    inlier_ratio: float
    action: str
    reason: str

    @classmethod
    def fail_open(
        cls,
        candidate_count: int,
        reason: str,
        *,
        inlier_count: int = 0,
        inlier_ratio: float = float("nan"),
    ) -> "DlVinsMagsacResult":
        return cls(
            keep_mask=np.ones((candidate_count,), dtype=bool),
            candidate_count=int(candidate_count),
            inlier_count=int(inlier_count),
            inlier_ratio=float(inlier_ratio),
            action="keep_all_fail_open",
            reason=str(reason),
        )


def require_dl_vins_magsac_available() -> None:
    """Fail before processing when OpenCV lacks the required USAC estimator."""

    if getattr(cv2, "USAC_MAGSAC", None) is None:
        raise RuntimeError(
            "DL-VINS MAGSAC geometry requires cv2.USAC_MAGSAC; "
            "use an isolated OpenCV build with USAC support"
        )


def filter_dl_vins_magsac(
    points0_normalized: np.ndarray,
    points1_normalized: np.ndarray,
    *,
    focal_mean_px: float,
) -> DlVinsMagsacResult:
    """Apply the temporal Essential-MAGSAC filter used by DL-VINS-Factory.

    Inputs are already undistorted normalized image coordinates.  The estimator
    and fallback contract intentionally mirror the official implementation:
    fewer than eight pairs, estimator errors, malformed masks, or an inlier
    ratio below 0.5 retain every candidate.  A valid mask at or above the ratio
    gate is the only condition that removes matches.
    """

    require_dl_vins_magsac_available()
    points0 = np.asarray(points0_normalized, dtype=np.float32).reshape(-1, 2)
    points1 = np.asarray(points1_normalized, dtype=np.float32).reshape(-1, 2)
    candidate_count = int(len(points0))
    if len(points1) != candidate_count:
        return DlVinsMagsacResult.fail_open(candidate_count, "point_count_mismatch")
    if candidate_count < DL_VINS_MAGSAC_MIN_CORRESPONDENCES:
        return DlVinsMagsacResult.fail_open(candidate_count, "fewer_than_8_correspondences")
    if not np.isfinite(focal_mean_px) or float(focal_mean_px) <= 0.0:
        return DlVinsMagsacResult.fail_open(candidate_count, "invalid_focal_mean")

    threshold_normalized = DL_VINS_MAGSAC_PIXEL_THRESHOLD / float(focal_mean_px)
    try:
        _essential, mask = cv2.findEssentialMat(
            points0,
            points1,
            np.eye(3, dtype=np.float64),
            method=cv2.USAC_MAGSAC,
            prob=DL_VINS_MAGSAC_PROBABILITY,
            threshold=threshold_normalized,
            maxIters=DL_VINS_MAGSAC_MAX_ITERS,
        )
    except Exception as exc:
        return DlVinsMagsacResult.fail_open(
            candidate_count,
            f"find_essential_exception:{type(exc).__name__}",
        )

    if mask is None:
        return DlVinsMagsacResult.fail_open(candidate_count, "missing_inlier_mask")
    mask_flat = np.asarray(mask).reshape(-1)
    if len(mask_flat) != candidate_count:
        return DlVinsMagsacResult.fail_open(candidate_count, "invalid_inlier_mask_length")

    inlier_mask = mask_flat == 1
    inlier_count = int(np.count_nonzero(inlier_mask))
    inlier_ratio = float(inlier_count / candidate_count)
    if inlier_ratio < DL_VINS_MAGSAC_MIN_INLIER_RATIO:
        return DlVinsMagsacResult.fail_open(
            candidate_count,
            "inlier_ratio_below_0.5",
            inlier_count=inlier_count,
            inlier_ratio=inlier_ratio,
        )

    return DlVinsMagsacResult(
        keep_mask=inlier_mask.astype(bool, copy=False),
        candidate_count=candidate_count,
        inlier_count=inlier_count,
        inlier_ratio=inlier_ratio,
        action="filter_inliers",
        reason="magsac_inlier_mask_applied",
    )
