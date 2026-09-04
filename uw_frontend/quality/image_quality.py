from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np


@dataclass
class ImageQuality:
    mean_intensity: float
    contrast: float
    gradient_mean: float
    laplacian_var: float
    underexposed_ratio: float
    overexposed_ratio: float
    illumination_nonuniformity: float
    local_contrast: float
    flat_region_ratio: float
    texture_score: float
    blur_score: float
    exposure_score: float
    contrast_score: float
    illumination_score: float
    backscatter_score: float
    highlight_shadow_score: float
    grid_texture_score: float
    underwater_score: float
    degradation_score: float
    global_score: float


@dataclass
class CellQualityMap:
    rows: int
    cols: int
    quality: np.ndarray
    texture: np.ndarray
    contrast: np.ndarray
    blur: np.ndarray
    exposure: np.ndarray
    illumination: np.ndarray
    backscatter: np.ndarray
    highlight_shadow: np.ndarray

    def quality_at(self, points: np.ndarray) -> np.ndarray:
        return _values_at_points(self.quality, points, self.rows, self.cols)

    def texture_at(self, points: np.ndarray) -> np.ndarray:
        return _values_at_points(self.texture, points, self.rows, self.cols)


def _clip01(value: float) -> float:
    return float(np.clip(value, 0.0, 1.0))


def score_image_quality(gray: np.ndarray) -> ImageQuality:
    if gray.ndim != 2:
        raise ValueError("score_image_quality expects a grayscale image")

    gray_u8 = gray.astype(np.uint8, copy=False)
    gray_f = gray_u8.astype(np.float32)
    mean = float(np.mean(gray_f))
    contrast = float(np.std(gray_f))

    gx = cv2.Sobel(gray_u8, cv2.CV_32F, 1, 0, ksize=3)
    gy = cv2.Sobel(gray_u8, cv2.CV_32F, 0, 1, ksize=3)
    grad_mag = cv2.magnitude(gx, gy)
    gradient_mean = float(np.mean(grad_mag))

    lap = cv2.Laplacian(gray_u8, cv2.CV_32F, ksize=3)
    laplacian_var = float(np.var(lap))

    under = float(np.mean(gray_u8 < 12))
    over = float(np.mean(gray_u8 > 243))
    shadow_highlight = float(np.mean((gray_u8 < 20) | (gray_u8 > 235)))

    illumination_nonuniformity = _illumination_nonuniformity(gray_f)
    local_contrast = _local_contrast(gray_f)
    flat_region_ratio = _flat_region_ratio(grad_mag)

    texture_score = _clip01(gradient_mean / 28.0)
    blur_score = _clip01(laplacian_var / 450.0)
    exposure_score = _clip01(1.0 - 2.5 * (under + over))
    contrast_score = _clip01(contrast / 45.0)
    illumination_score = _clip01(1.0 - 2.4 * illumination_nonuniformity)
    backscatter_score = _clip01(0.50 * contrast_score + 0.50 * _clip01(local_contrast / 0.22))
    highlight_shadow_score = _clip01(1.0 - 1.8 * shadow_highlight)
    grid_texture_score = _clip01(1.0 - flat_region_ratio)
    underwater_score = _clip01(
        0.22 * texture_score
        + 0.16 * blur_score
        + 0.12 * exposure_score
        + 0.12 * contrast_score
        + 0.14 * illumination_score
        + 0.12 * backscatter_score
        + 0.06 * highlight_shadow_score
        + 0.06 * grid_texture_score
    )
    degradation_score = _clip01(1.0 - underwater_score)
    global_score = underwater_score

    return ImageQuality(
        mean_intensity=mean,
        contrast=contrast,
        gradient_mean=gradient_mean,
        laplacian_var=laplacian_var,
        underexposed_ratio=under,
        overexposed_ratio=over,
        illumination_nonuniformity=illumination_nonuniformity,
        local_contrast=local_contrast,
        flat_region_ratio=flat_region_ratio,
        texture_score=texture_score,
        blur_score=blur_score,
        exposure_score=exposure_score,
        contrast_score=contrast_score,
        illumination_score=illumination_score,
        backscatter_score=backscatter_score,
        highlight_shadow_score=highlight_shadow_score,
        grid_texture_score=grid_texture_score,
        underwater_score=underwater_score,
        degradation_score=degradation_score,
        global_score=global_score,
    )


def fuse_image_quality_for_gates(
    processed: ImageQuality,
    raw: ImageQuality | None,
    mode: str = "preprocessed",
) -> ImageQuality:
    """Return the quality object used by scheduler/gating decisions.

    The frontend may track on enhanced imagery while deciding degradation from
    the original frame. This prevents CLAHE from hiding genuinely textureless
    or backscatter-heavy underwater regions from learned-sidecar gates.
    """

    if raw is None or mode in {"", "preprocessed", "processed"}:
        return processed
    if mode == "raw":
        return raw
    if mode != "raw_degradation":
        raise ValueError(f"unsupported quality gate mode: {mode}")
    return ImageQuality(
        mean_intensity=processed.mean_intensity,
        contrast=processed.contrast,
        gradient_mean=min(processed.gradient_mean, raw.gradient_mean),
        laplacian_var=min(processed.laplacian_var, raw.laplacian_var),
        underexposed_ratio=max(processed.underexposed_ratio, raw.underexposed_ratio),
        overexposed_ratio=max(processed.overexposed_ratio, raw.overexposed_ratio),
        illumination_nonuniformity=max(
            processed.illumination_nonuniformity,
            raw.illumination_nonuniformity,
        ),
        local_contrast=min(processed.local_contrast, raw.local_contrast),
        flat_region_ratio=max(processed.flat_region_ratio, raw.flat_region_ratio),
        texture_score=min(processed.texture_score, raw.texture_score),
        blur_score=min(processed.blur_score, raw.blur_score),
        exposure_score=min(processed.exposure_score, raw.exposure_score),
        contrast_score=min(processed.contrast_score, raw.contrast_score),
        illumination_score=min(processed.illumination_score, raw.illumination_score),
        backscatter_score=min(processed.backscatter_score, raw.backscatter_score),
        highlight_shadow_score=min(
            processed.highlight_shadow_score,
            raw.highlight_shadow_score,
        ),
        grid_texture_score=min(processed.grid_texture_score, raw.grid_texture_score),
        underwater_score=min(processed.underwater_score, raw.underwater_score),
        degradation_score=max(processed.degradation_score, raw.degradation_score),
        global_score=min(processed.global_score, raw.global_score),
    )


def _illumination_nonuniformity(gray_f: np.ndarray) -> float:
    h, w = gray_f.shape[:2]
    sigma = max(9.0, float(max(h, w)) / 12.0)
    low_freq = cv2.GaussianBlur(gray_f, (0, 0), sigmaX=sigma, sigmaY=sigma)
    p10, p90 = np.percentile(low_freq, [10, 90])
    return _clip01(float(p90 - p10) / 255.0)


def _local_contrast(gray_f: np.ndarray) -> float:
    kernel = (31, 31)
    local_mean = cv2.blur(gray_f, kernel)
    local_sq_mean = cv2.blur(gray_f * gray_f, kernel)
    local_std = np.sqrt(np.maximum(local_sq_mean - local_mean * local_mean, 0.0))
    normalized = local_std / (local_mean + 10.0)
    return float(np.median(normalized))


def _flat_region_ratio(grad_mag: np.ndarray, rows: int = 4, cols: int = 6) -> float:
    h, w = grad_mag.shape[:2]
    flat = 0
    total = 0
    for row in range(rows):
        y0 = int(round(row * h / rows))
        y1 = int(round((row + 1) * h / rows))
        for col in range(cols):
            x0 = int(round(col * w / cols))
            x1 = int(round((col + 1) * w / cols))
            cell = grad_mag[y0:y1, x0:x1]
            if cell.size == 0:
                continue
            total += 1
            if float(np.mean(cell)) < 12.0:
                flat += 1
    return 0.0 if total == 0 else float(flat / total)


def local_texture_scores(gray: np.ndarray, points: np.ndarray, patch_radius: int = 7) -> np.ndarray:
    """Return a [0, 1] texture score around every point."""

    if len(points) == 0:
        return np.empty((0,), dtype=np.float32)
    gx = cv2.Sobel(gray.astype(np.uint8, copy=False), cv2.CV_32F, 1, 0, ksize=3)
    gy = cv2.Sobel(gray.astype(np.uint8, copy=False), cv2.CV_32F, 0, 1, ksize=3)
    grad = cv2.magnitude(gx, gy)
    h, w = gray.shape[:2]
    scores = []
    for x, y in points.reshape(-1, 2):
        x0 = max(0, int(round(x)) - patch_radius)
        y0 = max(0, int(round(y)) - patch_radius)
        x1 = min(w, int(round(x)) + patch_radius + 1)
        y1 = min(h, int(round(y)) + patch_radius + 1)
        if x0 >= x1 or y0 >= y1:
            scores.append(0.0)
        else:
            scores.append(_clip01(float(np.mean(grad[y0:y1, x0:x1])) / 32.0))
    return np.asarray(scores, dtype=np.float32)


def score_cell_quality_map(gray: np.ndarray, rows: int = 4, cols: int = 6) -> CellQualityMap:
    """Score local underwater image quality on a regular grid."""

    if gray.ndim != 2:
        raise ValueError("score_cell_quality_map expects a grayscale image")
    rows = max(1, int(rows))
    cols = max(1, int(cols))
    gray_u8 = gray.astype(np.uint8, copy=False)
    gray_f = gray_u8.astype(np.float32)
    gx = cv2.Sobel(gray_u8, cv2.CV_32F, 1, 0, ksize=3)
    gy = cv2.Sobel(gray_u8, cv2.CV_32F, 0, 1, ksize=3)
    grad = cv2.magnitude(gx, gy)
    lap = cv2.Laplacian(gray_u8, cv2.CV_32F, ksize=3)
    global_mean = float(np.mean(gray_f))
    h, w = gray.shape[:2]

    texture = np.zeros((rows, cols), dtype=np.float32)
    contrast = np.zeros((rows, cols), dtype=np.float32)
    blur = np.zeros((rows, cols), dtype=np.float32)
    exposure = np.zeros((rows, cols), dtype=np.float32)
    illumination = np.zeros((rows, cols), dtype=np.float32)
    backscatter = np.zeros((rows, cols), dtype=np.float32)
    highlight_shadow = np.zeros((rows, cols), dtype=np.float32)
    quality = np.zeros((rows, cols), dtype=np.float32)

    for row in range(rows):
        y0 = int(round(row * h / rows))
        y1 = int(round((row + 1) * h / rows))
        for col in range(cols):
            x0 = int(round(col * w / cols))
            x1 = int(round((col + 1) * w / cols))
            cell = gray_u8[y0:y1, x0:x1]
            cell_f = gray_f[y0:y1, x0:x1]
            if cell.size == 0:
                continue
            cell_grad = grad[y0:y1, x0:x1]
            cell_lap = lap[y0:y1, x0:x1]
            mean = float(np.mean(cell_f))
            std = float(np.std(cell_f))
            under = float(np.mean(cell < 12))
            over = float(np.mean(cell > 243))
            shadow_highlight = float(np.mean((cell < 20) | (cell > 235)))
            local_contrast = std / (mean + 10.0)

            texture_score = _clip01(float(np.mean(cell_grad)) / 28.0)
            blur_score = _clip01(float(np.var(cell_lap)) / 450.0)
            exposure_score = _clip01(1.0 - 2.5 * (under + over))
            contrast_score = _clip01(std / 45.0)
            illumination_score = _clip01(1.0 - abs(mean - global_mean) / 96.0)
            backscatter_score = _clip01(0.50 * contrast_score + 0.50 * _clip01(local_contrast / 0.22))
            highlight_shadow_score = _clip01(1.0 - 1.8 * shadow_highlight)
            score = _clip01(
                0.24 * texture_score
                + 0.16 * blur_score
                + 0.12 * exposure_score
                + 0.14 * contrast_score
                + 0.12 * illumination_score
                + 0.14 * backscatter_score
                + 0.08 * highlight_shadow_score
            )

            texture[row, col] = texture_score
            contrast[row, col] = contrast_score
            blur[row, col] = blur_score
            exposure[row, col] = exposure_score
            illumination[row, col] = illumination_score
            backscatter[row, col] = backscatter_score
            highlight_shadow[row, col] = highlight_shadow_score
            quality[row, col] = score

    return CellQualityMap(
        rows=rows,
        cols=cols,
        quality=quality,
        texture=texture,
        contrast=contrast,
        blur=blur,
        exposure=exposure,
        illumination=illumination,
        backscatter=backscatter,
        highlight_shadow=highlight_shadow,
    )


def _values_at_points(values: np.ndarray, points: np.ndarray, rows: int, cols: int) -> np.ndarray:
    if len(points) == 0:
        return np.empty((0,), dtype=np.float32)
    pts = np.asarray(points, dtype=np.float32).reshape(-1, 2)
    h_norm = max(1.0, float(np.max(pts[:, 1]) + 1.0))
    w_norm = max(1.0, float(np.max(pts[:, 0]) + 1.0))
    # The caller supplies image-grid values but not the image shape. Use the
    # maximum coordinate as a conservative fallback; trackers call this through
    # quality_at_points below when the image shape is known.
    xs = np.clip((pts[:, 0] / w_norm * cols).astype(np.int32), 0, cols - 1)
    ys = np.clip((pts[:, 1] / h_norm * rows).astype(np.int32), 0, rows - 1)
    return values[ys, xs].astype(np.float32)


def cell_quality_at_points(
    quality_map: CellQualityMap,
    points: np.ndarray,
    image_shape: tuple[int, int],
    kind: str = "quality",
) -> np.ndarray:
    if len(points) == 0:
        return np.empty((0,), dtype=np.float32)
    values = getattr(quality_map, kind)
    pts = np.asarray(points, dtype=np.float32).reshape(-1, 2)
    h, w = image_shape[:2]
    xs = np.clip((pts[:, 0] / max(1, w) * quality_map.cols).astype(np.int32), 0, quality_map.cols - 1)
    ys = np.clip((pts[:, 1] / max(1, h) * quality_map.rows).astype(np.int32), 0, quality_map.rows - 1)
    return values[ys, xs].astype(np.float32)
