#!/usr/bin/env python3
"""Rewrite only learned quality/sigma using the locked generic mapping."""
import ast
import copy
import csv
import io
import json
import math
from collections import defaultdict
from itertools import zip_longest
from pathlib import Path
from types import FunctionType

import numpy as np

from run_additive_budget_v1 import ROOT, FEATURE, sha, save

PAPER = ROOT / 'papers/frontend_source_neutral_quality_v1'
OLD = ROOT / 'papers/frontend_additive_budget_v1'
SOURCE = Path('/media/ma/Data/AQUA-FE_WS_storage_offload/frontend_additive_budget_v1')
RUNTIME = SOURCE.parent / 'frontend_source_neutral_quality_v1'
SLUGS = ['a02_0_900', 'a08_2700_3600']


def serialized(message):
    stream = io.BytesIO()
    message.serialize(stream)
    return stream.getvalue()


def mapping():
    from uw_frontend.ros import export_vins_features as exporter
    path = ROOT / 'uw_frontend/ros/export_vins_features.py'
    locked = json.loads((OLD / 'source_and_backend_lock.json').read_text())
    assert sha(path) == locked['files'][str(path.relative_to(ROOT))]
    nodes = {n.name: n for n in ast.parse(path.read_text()).body if isinstance(n, ast.FunctionDef)}
    generic_source = copy.deepcopy(nodes['_backend_source_reliability'])
    assert isinstance(generic_source.body[-1], ast.Return)
    generic_source.body = [generic_source.body[-1]]  # Existing fallback, not a new constant.
    generic_safe = copy.deepcopy(nodes['_vins_safe_backend_reliability'])
    assert sum(isinstance(n, ast.For) for n in generic_safe.body) == 1
    generic_safe.body = [n for n in generic_safe.body if not isinstance(n, ast.For)]
    namespace = dict(exporter.__dict__)
    module = ast.fix_missing_locations(ast.Module(body=[generic_source, generic_safe], type_ignores=[]))
    exec(compile(module, str(path) + ':generic-only', 'exec'), namespace)
    original = exporter._backend_reliability
    neutral = FunctionType(original.__code__, namespace, original.__name__, original.__defaults__)
    neutral.__kwdefaults__ = original.__kwdefaults__
    return original, neutral


def tracks_from_records(records):
    from uw_frontend.tracking.track_state import TrackSet
    n = len(records)
    values = lambda key: np.array([r[key] for r in records], dtype=np.float32)
    points = values('point').reshape(n, 2)
    return TrackSet(np.array([r['source_id'] for r in records], dtype=np.int64),
                    points.copy(), points, values('age').astype(np.int32), values('fb'),
                    values('ncc'), np.zeros(n, np.float32), values('raw_quality'),
                    ['xfeat_confirmed'] * n)


def assert_only_quality_changed(original, changed):
    restored = copy.deepcopy(changed)
    assert [c.name for c in original.channels] == [c.name for c in changed.channels]
    ids = original.channels[0].values
    for before, after in zip(original.channels, restored.channels):
        if before.name in ('quality', 'sigma'):
            after.values = list(after.values)
            for i, tid in enumerate(ids):
                if tid >= 10_000_000:
                    after.values[i] = before.values[i]
    assert serialized(original) == serialized(restored), 'Unauthorized input change'


def convert(slug):
    import rosbag
    original_map, neutral_map = mapping()
    w = next(w for w in json.loads((OLD / 'source_and_backend_lock.json').read_text())['windows']
             if w['run_slug'] == slug)
    olddir = SOURCE / 'frontend' / slug
    oldreceipt = json.loads((olddir / 'receipt.json').read_text())
    arm = oldreceipt['arms']['L-all']
    for p, expected in [(arm['feature_bag'], arm['sha256']),
                        (olddir / 'xfeat_source.jsonl', arm['source_stream_sha256']),
                        (w['baseline_bag'], w['baseline_sha256']),
                        (w['input_bag'], w['input_bag_sha256']),
                        (w['backend_config_source'], w['backend_config_source_sha256']),
                        (w['camera'], w['camera_sha256'])]:
        assert sha(p) == expected, str(p)
    lifecycle = olddir / 'candidate_lifecycle.csv'
    assert sha(lifecycle) == oldreceipt['artifacts'][str(lifecycle)]
    identities = defaultdict(dict)
    for row in csv.DictReader(lifecycle.open()):
        if row['arm'] == 'L-all' and row['event'] in ('admit', 'continue'):
            key = int(row['frame']), int(row['public_id'])
            assert key[1] not in identities[key[0]]
            identities[key[0]][key[1]] = int(row['source_id'])
    dest = RUNTIME / 'frontend' / slug
    dest.mkdir(parents=True, exist_ok=False)
    output = dest / 'L-neutral.bag'
    q_before, q_after = [], []
    frame = 0
    with rosbag.Bag(arm['feature_bag']) as oldbag, rosbag.Bag(w['baseline_bag']) as bbag, \
            rosbag.Bag(str(output), 'w') as newbag, (olddir / 'xfeat_source.jsonl').open() as source:
        for old, baseline in zip_longest(oldbag.read_messages(), bbag.read_messages()):
            assert old is not None and baseline is not None
            topic, message, stamp = old
            assert topic == baseline.topic and stamp == baseline.timestamp
            if topic != FEATURE:
                assert serialized(message) == serialized(baseline.message)
                newbag.write(topic, message, stamp)
                continue
            record = json.loads(next(source))
            assert record['frame'] == frame and record['stamp_ns'] == message.header.stamp.to_nsec()
            obs = record['observations']
            tracks = tracks_from_records(obs)
            oldq = original_map(tracks, mode='vins_safe', floor=.8, alpha=.65)
            newq = neutral_map(tracks, mode='vins_safe', floor=.8, alpha=.65)
            np.testing.assert_array_equal(oldq, np.array([o['quality'] for o in obs], np.float32))
            lookup = {o['source_id']: (o, oldq[i], newq[i]) for i, o in enumerate(obs)}
            assert len(lookup) == len(obs)
            changed = copy.deepcopy(message)
            channels = {c.name: c for c in changed.channels}
            for name in ('quality', 'sigma'):
                channels[name].values = list(channels[name].values)
            ids = list(message.channels[0].values)
            assert {int(t) for t in ids if t >= 10_000_000} == set(identities[frame])
            assert set(identities[frame].values()) == set(lookup)
            for i, tid in enumerate(ids):
                if tid < 10_000_000:
                    continue
                o, oq, nq = lookup[identities[frame][int(tid)]]
                assert o['source'] == 'xfeat'
                assert channels['quality'].values[i] == oq
                np.testing.assert_array_equal([message.points[i].x, message.points[i].y], o['normalized'])
                np.testing.assert_array_equal([channels['p_u'].values[i], channels['p_v'].values[i]], o['point'])
                channels['quality'].values[i] = float(nq)
                channels['sigma'].values[i] = float(np.float32(1 / math.sqrt(float(nq))))
                q_before.append(float(oq)); q_after.append(float(nq))
            assert_only_quality_changed(message, changed)
            backbone = copy.deepcopy(changed)
            backbone.points = backbone.points[:len(baseline.message.points)]
            for channel in backbone.channels:
                channel.values = channel.values[:len(baseline.message.points)]
            assert serialized(backbone) == serialized(baseline.message), 'KLT changed'
            newbag.write(topic, changed, stamp)
            frame += 1
        assert next(source, None) is None
    # Independent disk readback: all original fields, KLT q, IDs, source tags and timing.
    with rosbag.Bag(arm['feature_bag']) as original, rosbag.Bag(str(output)) as changed:
        for a, b in zip_longest(original.read_messages(), changed.read_messages()):
            assert a is not None and b is not None and (a.topic, a.timestamp) == (b.topic, b.timestamp)
            if a.topic == FEATURE:
                assert_only_quality_changed(a.message, b.message)
            else:
                assert serialized(a.message) == serialized(b.message)
    assert len(q_before) == arm['total_published']
    receipt = dict(run_slug=slug, status='PASS', frames=frame, candidate_observations=len(q_before),
                   source_jsonl_sha256=arm['source_stream_sha256'], lifecycle_sha256=sha(lifecycle),
                   original_mapping_reproduced_exactly=True, input_only_quality_sigma_changed=True,
                   KLT_all_fields_exact=True, source_labels_unchanged=True,
                   old_q_median=float(np.median(q_before)), neutral_q_median=float(np.median(q_after)),
                   neutral_q_min=float(min(q_after)), neutral_q_max=float(max(q_after)),
                   changed_q_observations=int(np.count_nonzero(np.array(q_before) != q_after)),
                   script_sha256=sha(__file__), arms={
                       'B': dict(feature_bag=w['baseline_bag'], sha256=w['baseline_sha256']),
                       'L-original': dict(feature_bag=arm['feature_bag'], sha256=arm['sha256']),
                       'L-neutral': dict(feature_bag=str(output), sha256=sha(output))})
    save(dest / 'receipt.json', receipt)
    print('CONVERSION_PASS', slug, len(q_before), 'q median', receipt['old_q_median'], '->', receipt['neutral_q_median'], flush=True)
    return receipt


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--window', required=True, choices=SLUGS)
    convert(parser.parse_args().window)
