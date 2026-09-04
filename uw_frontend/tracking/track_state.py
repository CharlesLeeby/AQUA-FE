from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass
class TrackSet:
    ids: np.ndarray
    prev_points: np.ndarray
    points: np.ndarray
    ages: np.ndarray
    fb_errors: np.ndarray
    ncc_scores: np.ndarray
    local_texture: np.ndarray
    qualities: np.ndarray
    sources: list[str]

    @classmethod
    def empty(cls) -> "TrackSet":
        return cls(
            ids=np.empty((0,), dtype=np.int64),
            prev_points=np.empty((0, 2), dtype=np.float32),
            points=np.empty((0, 2), dtype=np.float32),
            ages=np.empty((0,), dtype=np.int32),
            fb_errors=np.empty((0,), dtype=np.float32),
            ncc_scores=np.empty((0,), dtype=np.float32),
            local_texture=np.empty((0,), dtype=np.float32),
            qualities=np.empty((0,), dtype=np.float32),
            sources=[],
        )

    def __len__(self) -> int:
        return int(len(self.ids))


@dataclass
class TrackerDiagnostics:
    added_features: int
    dropped_features: int
    tracked_before_filter: int
    tracked_after_filter: int
    median_fb_error: float
    median_ncc: float
    median_quality: float

