#!/usr/bin/env python3
"""Recheck shadow mathematics and first published states against frozen sources.

These checks validate the implementation, not physical observation utility.
They leave the original summaries and the first exploratory math receipt intact.
"""
import json
from pathlib import Path

import numpy as np
from scipy.spatial.transform import Rotation

from analyze_observation_utility_v1 import (
    OLD, PAPER, flow_jacobian, gram, infometrics, rows, save, sha,
)


def main():
    xy = np.array([[-0.4, 0.2], [0.1, -0.3], [0.45, 0.35]])
    points = np.column_stack([xy, np.ones(len(xy))])
    step = 1e-6
    finite = np.empty((len(xy), 2, 6))
    for axis in range(6):
        projected = []
        for sign in [-1, 1]:
            state = np.zeros(6)
            state[axis] = sign * step
            moved = Rotation.from_rotvec(-state[3:]).apply(points) - state[:3]
            projected.append(moved[:, :2] / moved[:, 2, None])
        finite[:, :, axis] = (projected[1] - projected[0]) / (2 * step)
    error = float(np.max(np.abs(finite - flow_jacobian(xy))))
    assert error < 1e-8, error

    bearings = points / np.linalg.norm(points, axis=1, keepdims=True)
    rotation = Rotation.from_rotvec([0.1, -0.2, 0.05])
    current = rotation.apply(bearings)
    epipolar = np.cross(rotation.apply(bearings), current)
    assert np.max(np.abs(epipolar)) < 1e-14

    jb = flow_jacobian(np.array([[-0.4, -0.3], [-0.3, 0.3], [0.4, -0.2], [0.3, 0.4]]))
    jc = flow_jacobian(xy)
    qb, qc = np.array([0.8, 0.9, 0.7, 1.0]), np.array([0.7, 0.8, 0.9])
    metrics = infometrics(jb, jc, qb, qc)
    hb, hc = gram(jb, qb), gram(jc, qc)
    ridge = max(1e-12, np.trace(hb) / 6 * 1e-6)
    before = hb + np.eye(6) * ridge
    direct_gain = np.linalg.slogdet(before + hc)[1] - np.linalg.slogdet(before)[1]
    assert abs(direct_gain - metrics['logdet_gain']) < 1e-9
    assert np.linalg.eigvalsh(hc)[0] >= -1e-12
    assert -1e-10 <= metrics['logdet_gain'] <= metrics['independent_sum_logdet'] + 1e-9
    assert metrics['min_eigen_gain'] >= -1e-10
    assert metrics['weak_direction_gain'] >= -1e-10

    frozen = {(r['run_slug'], r['arm'], r['repeat']): r for r in rows(OLD / 'backend_results.csv')}
    first_states = rows(PAPER / 'first_output_state_audit.csv')
    assert len(first_states) == 36
    for row in first_states:
        run = frozen[row['run_slug'], row['arm'], row['repeat']]
        path = Path(run['run_dir']) / 'vins_output/vio.csv'
        receipt = json.loads((path.parents[1] / 'receipt.json').read_text())
        assert sha(path) == receipt['artifacts'][str(path)]
        with path.open() as stream:
            first = stream.readline().strip().split(',')
        assert row['first_pose_timestamp_ns'] == first[0]
        position = np.array(list(map(float, first[1:4])))
        np.testing.assert_array_equal(json.loads(row['first_pose_position_json']), position)
        np.testing.assert_array_equal(json.loads(row['first_pose_quaternion_json']), list(map(float, first[4:8])))
        assert abs(float(row['first_pose_position_norm']) - np.linalg.norm(position)) < 1e-14

    save(PAPER / 'supplementary_validation.json', {
        'status': 'PASS',
        'finite_difference_unit_depth_jacobian_max_error': error,
        'PSD_direct_logdet_and_diminishing_returns': 'PASS',
        'pure_rotation_epipolar_null': 'PASS',
        'original_first_published_states_checked': len(first_states),
        'first_published_state_source_hashes': 'PASS',
        'verification_script_sha256': sha(__file__),
        'initial_exploratory_math_receipt_sha256': sha(PAPER / 'shadow_math_validation.json'),
        'physical_information_or_initialization_validity': 'Not evaluated.',
    })
    print('SUPPLEMENTARY_VALIDATION_PASS', len(first_states), 'frozen first states; Jacobian error', error)


if __name__ == '__main__':
    main()
