"""TartanAir V1-only geometry and validity for fixed-point KLT supervision."""
from pathlib import Path
import cv2
import numpy as np
from scipy.spatial.transform import Rotation
from uw_frontend.temporal_refinement import unproject_z, project_world

K = np.array([[320.,0.,320.],[0.,320.,240.],[0.,0.,1.]])
# V1 camera pose uses forward/right/down axes; optical vectors use right/down/forward.
NED_FROM_OPTICAL = np.array([[0.,0.,1.],[1.,0.,0.],[0.,1.,0.]])


def load_poses(sequence):
    rows = np.loadtxt(Path(sequence)/'pose_left.txt')
    if rows.ndim != 2 or rows.shape[1] != 7 or not np.isfinite(rows).all():
        raise ValueError('invalid V1 camera pose rows')
    if not np.allclose(np.linalg.norm(rows[:,3:],axis=1),1.,atol=1e-4):
        raise ValueError('invalid V1 quaternion normalization')
    poses = np.tile(np.eye(4),(len(rows),1,1))
    poses[:,:3,:3] = Rotation.from_quat(rows[:,3:]).as_matrix() @ NED_FROM_OPTICAL
    poses[:,:3,3] = rows[:,:3]
    return poses


def read_frame(sequence, index):
    root = Path(sequence)
    image = cv2.imread(str(root/'image_left'/f'{index:06d}_left.png'),cv2.IMREAD_GRAYSCALE)
    depth = np.load(root/'depth_left'/f'{index:06d}_left_depth.npy',allow_pickle=False).astype(np.float32)
    if image is None or image.shape != (480,640) or depth.shape != (480,640):
        raise ValueError('not a synchronized 640x480 V1 frame')
    return image, depth


def read_mask(sequence, index):
    mask = np.load(Path(sequence)/'flow'/f'{index:06d}_{index+1:06d}_mask.npy',allow_pickle=False)
    if mask.shape != (480,640) or mask.dtype != np.uint8:
        raise ValueError('unexpected V1 flow-mask format')
    return mask


def sample(array, uv, nearest=False, border=0):
    uv = np.asarray(uv,np.float32).reshape(-1,2)
    # OpenCV remap cannot address a >32767-pixel dimension.
    pieces = []
    for first in range(0,len(uv),16000):
        xy = uv[first:first+16000]
        pieces.append(cv2.remap(array,xy[:,0,None],xy[:,1,None],
                              cv2.INTER_NEAREST if nearest else cv2.INTER_LINEAR,
                              borderMode=cv2.BORDER_CONSTANT,borderValue=border)[:,0])
    return np.concatenate(pieces) if pieces else np.empty(0)


def depth_query(depth, uv):
    uv = np.asarray(uv,dtype=float).reshape(-1,2)
    inside = np.isfinite(uv).all(1) & (uv[:,0]>=1) & (uv[:,0]<=638) & (uv[:,1]>=1) & (uv[:,1]<=478)
    safe_uv = np.where(inside[:,None],uv,0).astype(np.float32)
    valid_depth = np.isfinite(depth) & (depth>0) & (depth<1000)
    clean = np.where(valid_depth,depth,0).astype(np.float32)
    kernel = np.ones((3,3),np.uint8)
    lo, hi = cv2.erode(clean,kernel), cv2.dilate(clean,kernel)
    z = sample(clean,safe_uv)
    low, high = sample(lo,safe_uv), sample(hi,safe_uv)
    neighborhood_valid = sample(cv2.erode(valid_depth.astype(np.uint8),kernel),safe_uv,True) == 1
    reason = np.full(len(uv),'valid',dtype='<U40')
    reason[~neighborhood_valid] = 'invalid_or_sky_depth'
    reason[neighborhood_valid & ((high-low)>0.02*np.maximum(z,1e-12))] = 'depth_discontinuity'
    reason[~inside] = 'out_of_view'
    return z, reason


def anchor_world(uv, depth, pose):
    z, reason = depth_query(depth,uv)
    xyz = unproject_z(np.asarray(uv),z,K)
    return xyz @ pose[:3,:3].T + pose[:3,3], reason


def visible_world(points, depth, pose):
    uv, z = project_world(np.asarray(points),pose,K)
    target_z, reason = depth_query(depth,uv)
    reason[(reason=='valid') & (np.abs(target_z-z)>np.maximum(.02,.01*np.abs(z)))] = 'occluded_or_depth_mismatch'
    reason[~np.isfinite(z) | (z<=0)] = 'behind_camera'
    return uv, reason
