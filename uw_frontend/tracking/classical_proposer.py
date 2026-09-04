"""Independent deterministic GFTT proposer for the P03/P04 classical pool."""

from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np


@dataclass(frozen=True)
class ClassicalProposerConfig:
    detector: str = "gftt"
    max_candidates: int = 256
    quality_level: float = 0.01
    min_distance: int = 18
    block_size: int = 7
    use_harris: bool = False
    harris_k: float = 0.04
    exclusion_radius: int = 18
    id_base: int = 14_000_000
    grid_rows: int = 4
    grid_cols: int = 6

    def __post_init__(self) -> None:
        if self.detector != "gftt":
            raise ValueError("P03 classical proposer is frozen to GFTT")
        if self.max_candidates <= 0 or self.min_distance <= 0 or self.block_size <= 0:
            raise ValueError("GFTT count/distance/block parameters must be positive")
        if not 0.0 < self.quality_level <= 1.0:
            raise ValueError("quality_level must be in (0,1]")
        if self.exclusion_radius < 0 or self.grid_rows <= 0 or self.grid_cols <= 0:
            raise ValueError("exclusion radius/grid dimensions are invalid")
        # Float32 ROS channels exactly represent integers only through 2^24.
        if not 0 <= self.id_base < 16_000_000:
            raise ValueError("id_base must stay in the exact float32 integer range")


@dataclass(frozen=True)
class ClassicalProposal:
    lineage_id: int
    trigger_frame: int
    rank: int
    u: float
    v: float
    grid_row: int
    grid_col: int
    detector_response: float
    source: str = "classical_gftt"


class GFTTClassicalProposer:
    """Stateful ID allocator around a deterministic, outcome-blind detector."""

    def __init__(self, config: ClassicalProposerConfig | None = None) -> None:
        self.config = config or ClassicalProposerConfig()
        self.next_id = int(self.config.id_base)

    def reset(self) -> None:
        self.next_id = int(self.config.id_base)

    def propose(
        self,
        gray_image: np.ndarray,
        *,
        trigger_frame: int,
        exclusion_points: np.ndarray | None = None,
    ) -> list[ClassicalProposal]:
        image = np.asarray(gray_image)
        if image.ndim != 2:
            raise ValueError("GFTT proposer requires a grayscale image")
        if image.dtype != np.uint8:
            image = np.clip(image, 0, 255).astype(np.uint8)
        height, width = image.shape
        mask = np.full((height, width), 255, dtype=np.uint8)
        if exclusion_points is not None:
            points = np.asarray(exclusion_points, dtype=np.float64).reshape(-1, 2)
            for u, v in points:
                if np.isfinite(u) and np.isfinite(v):
                    cv2.circle(
                        mask,
                        (int(round(float(u))), int(round(float(v)))),
                        int(self.config.exclusion_radius),
                        0,
                        -1,
                    )
        cv2.setRNGSeed(20260730)
        detected = cv2.goodFeaturesToTrack(
            image,
            maxCorners=int(self.config.max_candidates),
            qualityLevel=float(self.config.quality_level),
            minDistance=float(self.config.min_distance),
            mask=mask,
            blockSize=int(self.config.block_size),
            useHarrisDetector=bool(self.config.use_harris),
            k=float(self.config.harris_k),
        )
        if detected is None:
            return []
        response_map = cv2.cornerMinEigenVal(
            image,
            blockSize=int(self.config.block_size),
            ksize=3,
        )
        sortable: list[tuple[float, int, int, float, float]] = []
        for u, v in detected.reshape(-1, 2):
            ui = min(width - 1, max(0, int(round(float(u)))))
            vi = min(height - 1, max(0, int(round(float(v)))))
            grid_row = min(
                self.config.grid_rows - 1,
                max(0, int(float(v) / height * self.config.grid_rows)),
            )
            grid_col = min(
                self.config.grid_cols - 1,
                max(0, int(float(u) / width * self.config.grid_cols)),
            )
            cell = grid_row * self.config.grid_cols + grid_col
            sortable.append(
                (-float(response_map[vi, ui]), cell, vi * width + ui, float(u), float(v))
            )
        sortable.sort()
        proposals: list[ClassicalProposal] = []
        for rank, item in enumerate(sortable, start=1):
            negative_response, cell, _pixel_index, u, v = item
            lineage_id = self.next_id
            self.next_id += 1
            if self.next_id >= 16_777_216:
                raise OverflowError("classical lineage IDs exceeded exact float32 range")
            proposals.append(
                ClassicalProposal(
                    lineage_id=lineage_id,
                    trigger_frame=int(trigger_frame),
                    rank=rank,
                    u=u,
                    v=v,
                    grid_row=cell // self.config.grid_cols,
                    grid_col=cell % self.config.grid_cols,
                    detector_response=-negative_response,
                )
            )
        return proposals


__all__ = [
    "ClassicalProposal",
    "ClassicalProposerConfig",
    "GFTTClassicalProposer",
]
