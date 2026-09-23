#!/usr/bin/env python3
"""Trace the two frozen references using public author assets, never B/C/L errors.

Small source/reference HTTP reads only. No reference rewrite, estimator, fitted
reference scale, or automatic promotion of source support to independent truth.
"""
import argparse
import hashlib
import io
import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import requests
from scipy.spatial.transform import Rotation

AUTHOR_COMMIT = "5cecd1f7544a3e0c074ee6f47c997d292ad9ef34"
AUTHOR_RAW = "https://raw.githubusercontent.com/joshi-bharat/slamutils-python/" + AUTHOR_COMMIT + "/"
PROVIDER = "afrl-uw/stereo-vi-underwater-dataset"


def digest(data):
    return hashlib.sha256(data).hexdigest()


def audit_reference(local_bytes, aligned_bytes, original_bytes, old_bytes):
    if local_bytes != aligned_bytes:
        raise ValueError("Author aligned file is not the frozen local reference")
    aligned = np.loadtxt(io.BytesIO(aligned_bytes))
    original = np.loadtxt(io.BytesIO(original_bytes))
    old = np.loadtxt(io.BytesIO(old_bytes))
    if not np.array_equal(original, old):
        raise ValueError("Unaligned author and older provider references differ")
    if aligned.shape != original.shape:
        raise ValueError("Reference rosters differ")
    # Validate the author's origin-only transformation using the first pose.
    # No trajectory fit and no evaluated estimate enters this computation.
    ra = Rotation.from_quat(aligned[:, 4:]).as_matrix()
    ro = Rotation.from_quat(original[:, 4:]).as_matrix()
    rotation = ra[0] @ ro[0].T
    translation = aligned[0, 1:4] - rotation @ original[0, 1:4]
    residual = np.linalg.norm(original[:, 1:4] @ rotation.T + translation - aligned[:, 1:4], axis=1)
    angle = np.linalg.norm(Rotation.from_matrix((rotation @ ro).transpose(0, 2, 1) @ ra).as_rotvec(), axis=1)
    if residual.max() > 1e-10 or angle.max() > 1e-10:
        raise ValueError("References are not the documented unscaled origin transform")
    old_lines = [x.split()[0] for x in original_bytes.decode().splitlines() if x.strip() and not x.startswith('#')]
    new_lines = [x.split()[0] for x in aligned_bytes.decode().splitlines() if x.strip() and not x.startswith('#')]
    writer_stamps = [x.replace('.', '')[:-9] + '.' + x.replace('.', '')[-9:] for x in old_lines]
    if writer_stamps != new_lines:
        raise ValueError("Timestamp strings do not reproduce the author's writer")
    return dict(rows=len(aligned), byte_identical_to_author_aligned=True,
        old_provider_equals_author_unaligned_numeric=True,
        transformation="first-pose left SE(3), no fit, scale exactly fixed to 1",
        first_pose_rotation=rotation.tolist(), first_pose_translation=translation.tolist(),
        max_position_residual=float(residual.max()), max_rotation_residual_rad=float(angle.max()),
        timestamp_writer_reproduced_all_rows=True,
        source_reference_path_length=float(np.linalg.norm(np.diff(original[:, 1:4], axis=0), axis=1).sum()),
        published_reference_path_length=float(np.linalg.norm(np.diff(aligned[:, 1:4], axis=0), axis=1).sum()))


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--dataset-root', type=Path, required=True)
    p.add_argument('--prior-checks', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    args = p.parse_args()
    if args.output.exists():
        raise FileExistsError("Existing audit is retained")
    session = requests.Session()
    sources = {}

    def fetch(url):
        r = session.get(url, timeout=30)
        r.raise_for_status()
        sources[url] = dict(sha256=digest(r.content), bytes=len(r.content))
        return r.content

    hf_commit = json.loads(fetch('https://huggingface.co/api/datasets/' + PROVIDER))['sha']
    old_commit = json.loads(fetch('https://api.github.com/repos/AutonomousFieldRoboticsLab/SVIn/commits/main'))['sha']
    for path in ('vi_comparison/compute_results.py', 'slam_utils/colmap_utils.py', 'slam_utils/traj_utils.py'):
        fetch(AUTHOR_RAW + path)
    fetch('https://huggingface.co/datasets/' + PROVIDER + '/resolve/' + hf_commit + '/README.md')
    old_root = 'https://raw.githubusercontent.com/AutonomousFieldRoboticsLab/SVIn/' + old_commit + '/'
    fetch(old_root + 'colmap_groundtruth/README.md')
    prior = json.loads(args.prior_checks.read_text())
    result = dict(created_at=datetime.now(timezone.utc).isoformat(), author_commit=AUTHOR_COMMIT,
        provider_commit=hf_commit, old_provider_commit=old_commit,
        no_B_C_L_results_used=True, role="source provenance, not independent metric truth",
        sources=sources, references={})
    for seq in ('bus_outside', 'cemetery'):
        local = (args.dataset_root / 'colmap_groundtruth' / (seq + '.txt')).read_bytes()
        expected = prior['references'][seq]['reference_sha256']
        if digest(local) != expected:
            raise ValueError("Local reference identity changed")
        provider_url = 'https://huggingface.co/datasets/' + PROVIDER + '/resolve/' + hf_commit + '/colmap_groundtruth/' + seq + '.txt'
        if fetch(provider_url) != local:
            raise ValueError("Pinned provider reference differs")
        base = AUTHOR_RAW + 'vi_comparison/data/' + seq + '/'
        numbers = audit_reference(local, fetch(base + 'colmap_aligned.txt'),
                                  fetch(base + 'colmap.txt'), fetch(old_root + 'colmap_groundtruth/' + seq + '.txt'))
        result['references'][seq] = dict(reference_sha256=expected,
            convention_validated=False, pose_convention="Unknown: full independent certification unavailable",
            source_supported_pose_convention="world_T_cam0",
            source_support_boundary="Author converter inverts COLMAP extrinsics, assigns camera 1 to left, writes xyzw camera poses; exact published files reproduce author's unscaled origin alignment. Original reconstruction/images.txt and per-file camera-ID export receipt not released; source support is not full independent certification.",
            metric_scale_validated=False,
            metric_scale_status="CONFLICT: provider describes stereo metric correction; exact new files are unscaled rigid transforms of old up-to-scale references",
            timestamp_mode="afrl_digits" if seq == 'cemetery' else "raw",
            prior_raw_gyro_check=prior['references'][seq]['interpretations'],
            evidence=[base + 'colmap_aligned.txt', AUTHOR_RAW + 'vi_comparison/compute_results.py',
                      AUTHOR_RAW + 'slam_utils/colmap_utils.py', provider_url],
            audit=numbers)
    with args.output.open('x') as f:
        json.dump(result, f, indent=2, allow_nan=False)
    print(json.dumps({s: r['audit'] for s, r in result['references'].items()}, indent=2))


if __name__ == '__main__':
    main()
