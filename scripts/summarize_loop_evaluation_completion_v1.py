#!/usr/bin/env python3
"""Publish all six saved-output diagnostics and a nonblinded accepted-pair ledger."""
import argparse
import csv
import hashlib
import json
from pathlib import Path

import numpy as np
from scipy.spatial.transform import Rotation

from evaluate_loop_system_v1 import reference
from trajectory_eval_core import resample_trajectory


def read_csv(path):
    with path.open() as f:
        return list(csv.DictReader(f))


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_csv(path, rows):
    with path.open('x', newline='') as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--runtime-view', type=Path, required=True)
    p.add_argument('--evaluation-root', type=Path, required=True)
    p.add_argument('--dataset-root', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    a = p.parse_args()
    records, rows, pairs, identity = {}, [], {}, {}
    for seq in ('bus_outside', 'cemetery'):
        reference_path = a.dataset_root / 'colmap_groundtruth' / (seq + '.txt')
        rt, rp, rq = reference(reference_path, 'afrl_digits' if seq == 'cemetery' else 'raw')
        for rep in (1, 2, 3):
            key = f'{seq}_r{rep}'
            path = a.evaluation_root / key / 'evaluation.json'
            ev = json.loads(path.read_text())
            if ev['formal_accuracy_status'] != 'Not evaluated' or not ev['conditional_proxy_diagnostic']:
                raise ValueError('This publisher requires explicit conditional diagnostics')
            records[key] = ev
            identity[str(path)] = digest(path)
            block = a.runtime_view / key
            for arm in 'BCL':
                result = ev['arms'][arm]
                row = dict(sequence_id=seq, repeat=rep, arm=arm,
                    status=result['status'], formal_outcome='NOT_EVALUABLE_REFERENCE_AND_LABELS',
                    translation_units='supplied_proxy_units_not_certified_metres',
                    common_poses=ev['support']['common_pose_count'],
                    coverage=ev['support']['common_reference_coverage'],
                    support_gate=ev['support']['support_gate'], initialization_time_s=ev['initialization_time_s'])
                for prefix, field in [('fixed', 'fixed_scale'), ('sim3', 'sim3_explicit_diagnostic')]:
                    for metric in ('ape_rmse', 'rpe_1s_translation_rmse', 'rpe_1s_rotation_rmse_deg', 'rpe_pairs', 'scale', 'evo_crosscheck'):
                        row[prefix + '_' + metric] = result.get(field, {}).get(metric, '')
                row['pre_loop_ape_same_whole_alignment'] = result.get('pre_post', {}).get('pre_loop', {}).get('ape_rmse_same_whole_sequence_alignment', '')
                row['post_loop_ape_same_whole_alignment'] = result.get('pre_post', {}).get('post_loop', {}).get('ape_rmse_same_whole_sequence_alignment', '')
                row['shared_boundary_s'] = ev['shared_pre_post_boundary_s']
                rows.append(row)
            roster = read_csv(block / 'archive/keyframes.csv')
            headers = read_csv(block / 'archive/header_identity.csv')
            for arm in 'CL':
                for g in read_csv(block / arm / 'native/geometry.csv'):
                    if g['geometry'] != 'PASS':
                        continue
                    q, c = roster[int(g['query_id'])], roster[int(g['candidate_id'])]
                    pair_id = (seq, q['image_sha256'], c['image_sha256'])
                    if pair_id not in pairs:
                        stamps = np.array([np.longdouble(q['timestamp_ns']), np.longdouble(c['timestamp_ns'])]) / 10**9
                        sampled = resample_trajectory(rt, rp, stamps, 1., rq, sample_kind='reference')
                        valid = bool(sampled.valid.all())
                        gap = float(stamps[0] - stamps[1])
                        wheel = seq == 'bus_outside' and int(q['id']) < 2200
                        evidence = ('Shared wheel arch and rim; window upright and horizontal body seam; corresponding corrosion patches.' if wheel else
                            'Shared circular front opening; diagonal rectangular panel; window frame; cable attachment and corrosion patches.' if seq == 'bus_outside' else
                            'Compatible ring of rocks; adjacent upright triangular stones and flattened oval stones. Repetitive stones and changed viewpoint limit unique-site certainty.')
                        pairs[pair_id] = dict(pair_id=f'P{len(pairs)+1:02d}', sequence_id=seq,
                            query_image_sha256=q['image_sha256'], candidate_image_sha256=c['image_sha256'],
                            query_original_timestamp_ns=headers[int(q['id'])]['original_feature_ns'],
                            candidate_original_timestamp_ns=headers[int(c['id'])]['original_feature_ns'],
                            query_image_path=str((block / 'archive' / q['image']).resolve()),
                            candidate_image_path=str((block / 'archive' / c['image']).resolve()),
                            occurrences=[], temporal_gap_s=gap,
                            proxy_association_valid=valid,
                            conditional_proxy_separation=float(np.linalg.norm(sampled.positions[0]-sampled.positions[1])) if valid else '',
                            conditional_proxy_orientation_gap_deg=float(np.linalg.norm((Rotation.from_quat(sampled.quaternions[0]).inv()*Rotation.from_quat(sampled.quaternions[1])).as_rotvec())*180/np.pi) if valid else '',
                            review='VISUAL_OVERLAP_SUPPORTED_NONBLIND' if seq == 'bus_outside' else 'VISUAL_OVERLAP_PLAUSIBLE_REPETITIVE_SCENE_NONBLIND',
                            visual_evidence=evidence, formal_independent_correctness='Unknown',
                            reviewer='Codex visual inspection 2026-09-23; prior outcome exposure disclosed',
                            labels_used_online=False, temporal_neighbor=False,
                            nearby_without_overlap='Not observed in reviewed images; not independently excluded',
                            repetition_risk='Repeated bus windows/wheels; additional shared structure inspected' if seq == 'bus_outside' else 'Repeated stones; no unique fiducial')
                    pairs[pair_id]['occurrences'].append(f'{rep}:{arm}:{g["query_id"]}->{g["candidate_id"]}')
    if len(rows) != 18 or len(pairs) != 8:
        raise ValueError('Unexpected denominator; do not silently publish a subset')
    pair_rows = list(pairs.values())
    for pair in pair_rows:
        pair['occurrences'] = ';'.join(pair['occurrences'])
    write_csv(a.output / 'proxy_diagnostic_accuracy.csv', rows)
    write_csv(a.output / 'accepted_pair_review.csv', pair_rows)
    receipt = dict(role='Conditional saved-output diagnostics, not formal accuracy or independent loop labels',
        source_receipts=identity, evaluator_sha256=digest(Path(__file__).with_name('evaluate_loop_system_v1.py')),
        publisher_sha256=digest(Path(__file__)), blocks=records)
    with (a.output / 'evaluation_completion_receipts.json').open('x') as f:
        json.dump(receipt, f, indent=2, allow_nan=False)
    for seq in ('bus_outside', 'cemetery'):
        for arm in 'CL':
            selected = [r for r in rows if r['sequence_id'] == seq and r['arm'] == arm]
            summary = {m: [float(np.median([r[m] for r in selected])), min(r[m] for r in selected), max(r[m] for r in selected)] for m in
                ('fixed_ape_rmse', 'fixed_rpe_1s_translation_rmse', 'sim3_ape_rmse', 'sim3_scale')}
            print(seq, arm, json.dumps(summary))


if __name__ == '__main__':
    main()
