"""Fixed current-image evidence at unchanged correspondence coordinates.

No inference, refinement, geometry, labels, or future frames are used here.
"""
import numpy as np

PATCH_RADIUS = 5
NCC_MIN = 0.65
MIN_PATCH_STD = 1.0  # mono8 intensity units, frozen before evaluation


def sample_patches(image, points):
    """Exact bilinear 11x11 samples; never pad/replicate an out-of-image patch."""
    image = np.asarray(image)
    points = np.asarray(points, dtype=np.float64).reshape(-1, 2)
    if image.ndim != 2:
        raise ValueError('Expected one grayscale plane in mono8 intensity units')
    h, w = image.shape
    radius = PATCH_RADIUS
    valid = (np.isfinite(points).all(axis=1)
             & (points[:, 0] >= radius) & (points[:, 0] <= w - 1 - radius)
             & (points[:, 1] >= radius) & (points[:, 1] <= h - 1 - radius))
    patches = np.full((len(points), 11, 11), np.nan, dtype=np.float64)
    indices = np.flatnonzero(valid)
    if not len(indices):
        return patches, valid
    dy, dx = np.mgrid[-radius:radius+1, -radius:radius+1]
    x = points[indices, 0, None, None] + dx
    y = points[indices, 1, None, None] + dy
    x0, y0 = np.floor(x).astype(int), np.floor(y).astype(int)
    x1, y1 = np.minimum(x0+1, w-1), np.minimum(y0+1, h-1)
    wx, wy = x-x0, y-y0
    patches[indices] = ((1-wx)*(1-wy)*image[y0, x0] + wx*(1-wy)*image[y0, x1]
                        + (1-wx)*wy*image[y1, x0] + wx*wy*image[y1, x1])
    return patches, valid


def check_correspondence_evidence(image_prev, image_cur, points_prev, points_predicted):
    """Return ncc, valid_patch, evidence_accepted, reason arrays.

    valid_patch requires complete image support, finite samples and std>1.
    Unresolved scores are NaN; rejected observations are not labelled invisible.
    Input coordinates are not modified.
    """
    p0 = np.asarray(points_prev, dtype=np.float64).reshape(-1, 2)
    p1 = np.asarray(points_predicted, dtype=np.float64).reshape(-1, 2)
    if p0.shape != p1.shape:
        raise ValueError('Correspondence arrays must have the same shape')
    first, inside0 = sample_patches(image_prev, p0)
    second, inside1 = sample_patches(image_cur, p1)
    n = len(p0)
    reason = np.full(n, 'UNRESOLVED_PATCH_OUTSIDE', dtype=object)
    finite_coords = np.isfinite(p0).all(axis=1) & np.isfinite(p1).all(axis=1)
    reason[~finite_coords] = 'UNRESOLVED_NONFINITE_COORDINATE'
    inside = inside0 & inside1
    finite_data = np.isfinite(first).all(axis=(1, 2)) & np.isfinite(second).all(axis=(1, 2))
    reason[inside & ~finite_data] = 'UNRESOLVED_NONFINITE_PATCH'
    indices = np.flatnonzero(inside & finite_data)
    ncc = np.full(n, np.nan)
    valid = np.zeros(n, dtype=bool)
    if len(indices):
        a, b = first[indices], second[indices]
        a = a-a.mean(axis=(1, 2), keepdims=True)
        b = b-b.mean(axis=(1, 2), keepdims=True)
        std0 = np.sqrt(np.mean(a*a, axis=(1, 2)))
        std1 = np.sqrt(np.mean(b*b, axis=(1, 2)))
        texture = (std0 > MIN_PATCH_STD) & (std1 > MIN_PATCH_STD)
        reason[indices] = 'UNRESOLVED_LOW_VARIANCE'
        good = indices[texture]
        valid[good] = True
        denom = np.linalg.norm(a[texture], axis=(1, 2))*np.linalg.norm(b[texture], axis=(1, 2))
        ncc[good] = np.clip(np.sum(a[texture]*b[texture], axis=(1, 2))/denom, -1, 1)
        reason[good] = 'NCC_BELOW_THRESHOLD'
    accepted = valid & (ncc >= NCC_MIN)
    reason[accepted] = 'SUPPORTED_BY_NCC'
    return dict(ncc=ncc, valid_patch=valid, evidence_accepted=accepted, reason=reason)
