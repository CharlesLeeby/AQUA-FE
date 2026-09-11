#!/usr/bin/env python3
"""Causal prepared patches -> corrected saved observations; keeps every row.

Inputs contain no truth: NPZ patches/history/patch_valid, JSON record list.
Camera JSON intrinsics, distortion_coefficients follows existing MIMIR sensor.
Output is JSON records, not a validated VINS feature bag.
"""
import argparse
import json
from pathlib import Path
import cv2
import numpy as np
import torch
from uw_frontend.temporal_refinement import PatchRefiner, correct_records


def main():
    p = argparse.ArgumentParser(description=__doc__)
    for name in ['patches', 'records', 'camera', 'checkpoint', 'output']:
        p.add_argument('--' + name, type=Path, required=True)
    a = p.parse_args()
    with np.load(a.patches, allow_pickle=False) as data:
        if set(data.files) != {'patches', 'history', 'patch_valid'}:
            raise ValueError('inference cache must contain only causal model inputs')
        patches, history, valid = data['patches'], data['history'], data['patch_valid']
    records = json.loads(a.records.read_text())
    if len(records) != len(patches):
        raise ValueError('input row count mismatch')
    model = PatchRefiner()
    model.load_state_dict(torch.load(a.checkpoint, map_location='cpu', weights_only=True)['state_dict'])
    model.eval()
    chunks = []
    with torch.no_grad():
        for start in range(0, len(records), 256):
            sl = slice(start, start + 256)
            chunks.append(model(torch.as_tensor(patches[sl]).float(), torch.as_tensor(history[sl]).float(),
                                torch.as_tensor(valid[sl])).numpy())
    delta = np.concatenate(chunks) if chunks else np.empty((0, 2))
    camera = json.loads(a.camera.read_text())
    K = np.asarray(camera['intrinsics'], dtype=float)
    dist = np.asarray(camera['distortion_coefficients'], dtype=float)
    if camera['camera_model'] != 'pinhole' or camera['distortion_model'] != 'radial-tangential':
        raise ValueError('unsupported camera model')
    normalize = lambda uv: cv2.undistortPoints(uv.reshape(-1, 1, 2).astype(float), K, dist).reshape(-1, 2)
    output = correct_records(records, delta, normalize)
    with a.output.open('x') as f:
        json.dump(dict(records=output, delta=delta.tolist(), patch_valid=valid.astype(bool).tolist()), f)


if __name__ == '__main__':
    main()
