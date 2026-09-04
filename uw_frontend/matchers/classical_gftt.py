"""Classical Shi-Tomasi (GFTT) + KLT matcher — the C-QG control detector.

Drop-in ``BaseMatcher`` whose ``match(img0, img1)`` produces the SAME
(points0, points1, confidences) contract as the XFeat/SP-LG learned matchers,
but via classical detection + optical-flow tracking:

  points0     = goodFeaturesToTrack(img0)            (Shi-Tomasi corners in img0)
  points1     = forward LK-track of points0 into img1 (kept if FB-consistent)
  confidences = per-corner min-eigenvalue (Shi-Tomasi score), normalized

Plugging this into ``LearnedSeedKltSidecar`` in place of ``XFeatMatcher`` runs
the entire downstream pipeline (LK probation, NCC, motion/homography gates,
novelty admission, export) BYTE-IDENTICALLY. The only changed variable is the
detector (XFeat -> Shi-Tomasi), which is exactly the C-QG "is learned necessary"
control from the ISJ plan.
"""

from __future__ import annotations

import cv2
import numpy as np

from uw_frontend.matchers.base import Availability, BaseMatcher, MatchResult


class ClassicalGfttMatcher(BaseMatcher):
    name = "classical_gftt"

    def __init__(
        self,
        max_corners: int = 1024,
        quality_level: float = 0.01,
        min_distance: int = 8,
        block_size: int = 3,
        lk_win_size: int = 21,
        lk_max_level: int = 3,
        fb_threshold: float = 1.0,
    ) -> None:
        self.max_corners = int(max_corners)
        self.quality_level = float(quality_level)
        self.min_distance = int(min_distance)
        self.block_size = int(block_size)
        self._lk = dict(
            winSize=(int(lk_win_size), int(lk_win_size)),
            maxLevel=int(lk_max_level),
            criteria=(cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 30, 0.01),
        )
        self.fb_threshold = float(fb_threshold)

    @classmethod
    def availability(cls) -> Availability:
        return Availability(True, "opencv")

    @staticmethod
    def _gray(img: np.ndarray) -> np.ndarray:
        if img.ndim == 3:
            img = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        return np.asarray(img, dtype=np.uint8)

    def _empty(self) -> MatchResult:
        z2 = np.empty((0, 2), dtype=np.float32)
        return MatchResult(z2, z2.copy(), np.empty((0,), dtype=np.float32), self.name)

    def match(self, image0: np.ndarray, image1: np.ndarray) -> MatchResult:
        g0, g1 = self._gray(image0), self._gray(image1)
        corners = cv2.goodFeaturesToTrack(
            g0, self.max_corners, self.quality_level, self.min_distance, blockSize=self.block_size
        )
        if corners is None or len(corners) == 0:
            return self._empty()
        p0 = corners.reshape(-1, 1, 2).astype(np.float32)
        p1, st, _ = cv2.calcOpticalFlowPyrLK(g0, g1, p0, None, **self._lk)
        if p1 is None or st is None:
            return self._empty()
        pb, _, _ = cv2.calcOpticalFlowPyrLK(g1, g0, p1, None, **self._lk)
        if pb is None:
            return self._empty()
        fb = np.linalg.norm((p0 - pb).reshape(-1, 2), axis=1)
        ok = (st.reshape(-1) == 1) & (fb < self.fb_threshold)
        pts0 = p0.reshape(-1, 2)[ok]
        pts1 = p1.reshape(-1, 2)[ok]
        if len(pts0) == 0:
            return self._empty()
        # classical per-corner confidence = Shi-Tomasi min-eigenvalue at points0
        eig = cv2.cornerMinEigenVal(g0, self.block_size)
        h, w = g0.shape[:2]
        xi = np.clip(np.round(pts0[:, 0]).astype(int), 0, w - 1)
        yi = np.clip(np.round(pts0[:, 1]).astype(int), 0, h - 1)
        conf = eig[yi, xi].astype(np.float32)
        cmax = float(conf.max()) if len(conf) else 0.0
        conf = conf / cmax if cmax > 0 else np.ones((len(pts0),), dtype=np.float32)
        return MatchResult(pts0.astype(np.float32), pts1.astype(np.float32), conf, self.name)
