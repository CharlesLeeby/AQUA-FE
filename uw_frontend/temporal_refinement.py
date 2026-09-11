"""Bounded post-KLT patch correction. No tracker state or ground truth inputs."""
from __future__ import annotations

import copy
import numpy as np
import torch
from torch import nn
from torch.nn import functional as F


class PatchRefiner(nn.Module):
    """Frozen v1 architecture; patches N,3,31,31 and causal history N,4."""

    def __init__(self):
        super().__init__()
        self.encoder = nn.Sequential(
            nn.Conv2d(1, 16, 3, 2, 1), nn.ReLU(),
            nn.Conv2d(16, 32, 3, 2, 1), nn.ReLU(),
            nn.Conv2d(32, 32, 3, 2, 1), nn.ReLU(), nn.Flatten(),
        )
        self.hidden = nn.Sequential(nn.Linear(1540, 128), nn.ReLU())
        self.head = nn.Linear(128, 2)
        nn.init.zeros_(self.head.weight)
        nn.init.zeros_(self.head.bias)

    def forward(self, patches, history, patch_valid):
        if patches.shape[1:] != (3, 31, 31) or history.shape != (len(patches), 4):
            raise ValueError("expected three 31px patches and four causal displacements")
        valid = patch_valid.bool() & torch.isfinite(patches).flatten(1).all(1)
        valid &= torch.isfinite(history).all(1)
        clean = torch.where(valid[:, None, None, None], patches, 0.)
        h = torch.where(valid[:, None], history, 0.)
        encoded = self.encoder(clean.reshape(-1, 1, 31, 31)).reshape(len(patches), -1)
        delta = 2 * torch.tanh(self.head(self.hidden(torch.cat((encoded, h / 31), 1))))
        return torch.where(valid[:, None], delta, 0.)


def paired_loss(delta, baseline, truth, temporal_weight):
    """All tensors N,2(time),2(xy); caller supplies valid same-point pairs."""
    if delta.shape != baseline.shape or truth.shape != baseline.shape or delta.shape[1:] != (2, 2):
        raise ValueError("expected N,2,2 consecutive same-identity pairs")
    error = baseline + delta - truth
    pointwise = F.smooth_l1_loss(error, torch.zeros_like(error), beta=1.)
    change = error[:, 1] - error[:, 0]
    temporal = F.smooth_l1_loss(change, torch.zeros_like(change), beta=1.)
    return pointwise + temporal_weight * temporal, pointwise, temporal


def extract_patch(image, uv):
    """Return normalized raw gray patch and reason; never delete an observation."""
    import cv2
    uv = np.asarray(uv, dtype=float)
    if image is None or image.ndim != 2 or not np.isfinite(uv).all():
        return np.zeros((31, 31), np.float32), "missing_or_nonfinite"
    x, y = uv
    if x < 15 or y < 15 or x > image.shape[1] - 16 or y > image.shape[0] - 16:
        return np.zeros((31, 31), np.float32), "patch_out_of_bounds"
    patch = cv2.getRectSubPix(image.astype(np.float32), (31, 31), (float(x), float(y)))
    return patch / 255., "valid"


def correct_records(records, deltas, normalize):
    """Generic saved-observation adapter, not a validated ROS bag exporter.

    Fields: id, timestamp_ns, uv, normalized, velocity, plus untouched metadata.
    normalize maps Nx2 original pixels to Nx2 camera-normalized coordinates.
    Input records must be in public-frame order, one record per ID per timestamp.
    Exact zero correction returns the original fields, including first velocity.
    """
    deltas = np.asarray(deltas, dtype=float)
    if deltas.shape != (len(records), 2) or not np.isfinite(deltas).all() or np.any(abs(deltas) > 2):
        raise ValueError("one finite bounded correction required per original record")
    output = copy.deepcopy(records)
    previous = {}
    last_stamp = None
    for src, dst, delta in zip(records, output, deltas):
        stamp, identity = int(src['timestamp_ns']), src['id']
        if last_stamp is not None and stamp < last_stamp:
            raise ValueError("public records must be chronological")
        last_stamp = stamp
        old = previous.get(identity)
        if old is not None and stamp <= old[0]:
            raise ValueError("duplicate or nonincreasing ID timestamp")
        changed = bool(np.any(delta != 0))
        if changed:
            uv = np.asarray(src['uv']) + delta
            normalized = np.asarray(normalize(uv[None]))[0]
            if normalized.shape != (2,) or not np.isfinite(normalized).all():
                raise ValueError("invalid normalized coordinates")
            dst['uv'], dst['normalized'] = uv.tolist(), normalized.tolist()
            if old is None:
                dst['velocity'] = [0., 0.]
        if old is not None and (changed or old[2]):
            dt = (stamp - old[0]) * 1e-9
            dst['velocity'] = ((np.asarray(dst['normalized']) - old[1]) / dt).tolist()
        previous[identity] = (stamp, np.asarray(dst['normalized']), changed)
    return output


def unproject_z(uv, depth_z_m, intrinsics):
    """Geometry primitive ONLY for externally verified metric optical z depth."""
    uv = np.asarray(uv, dtype=float)
    rays = np.c_[uv, np.ones(len(uv))] @ np.linalg.inv(intrinsics).T
    return rays * np.asarray(depth_z_m)[:, None]


def project_world(points_world, world_from_camera, intrinsics):
    points = (np.c_[points_world, np.ones(len(points_world))]
              @ np.linalg.inv(world_from_camera).T)[:, :3]
    pixels = points @ np.asarray(intrinsics).T
    with np.errstate(invalid='ignore', divide='ignore'):
        uv = pixels[:, :2] / pixels[:, 2:]
    return uv, points[:, 2]


def require_verified_supervision(certificate):
    required = ('metric_depth_encoding', 'pose_frame_and_direction', 'camera_extrinsics',
                'timestamp_alignment', 'occlusion_and_static_masks', 'real_projection_examples')
    missing = [k for k in required if certificate.get(k) != 'PASS']
    if missing:
        raise ValueError('SUPERVISION_UNAVAILABLE: ' + ', '.join(missing))
