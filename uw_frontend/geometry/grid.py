from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass
class GridStats:
    rows: int
    cols: int
    occupied: int
    total: int
    coverage: float
    min_count: int
    max_count: int
    counts: np.ndarray


def grid_stats(points: np.ndarray, image_shape: tuple[int, int], rows: int = 4, cols: int = 6) -> GridStats:
    h, w = image_shape[:2]
    counts = np.zeros((rows, cols), dtype=np.int32)
    if len(points) > 0:
        pts = points.reshape(-1, 2)
        xs = np.clip((pts[:, 0] / max(1, w) * cols).astype(np.int32), 0, cols - 1)
        ys = np.clip((pts[:, 1] / max(1, h) * rows).astype(np.int32), 0, rows - 1)
        for x, y in zip(xs, ys):
            counts[y, x] += 1
    occupied = int(np.sum(counts > 0))
    total = rows * cols
    nonzero = counts[counts > 0]
    return GridStats(
        rows=rows,
        cols=cols,
        occupied=occupied,
        total=total,
        coverage=float(occupied / total) if total else 0.0,
        min_count=int(nonzero.min()) if len(nonzero) else 0,
        max_count=int(counts.max()) if counts.size else 0,
        counts=counts,
    )

