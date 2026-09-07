#!/usr/bin/env python3
"""Independent readback of source mappings, serialized deliveries and received IDs."""
from collections import Counter, defaultdict
import csv
import json
import numpy as np
from run_additive_budget_v1 import ROOT, PAPER, RUNTIME, FEATURE, sha, verify
from analyze_additive_budget_v1 import table, verify_artifacts
from uw_frontend.ros.additive_budget_v1 import channels, assert_backbone, serialized


def main():
    import rosbag
    lock = verify()
    for p, h in json.loads((PAPER/'evaluation_lock.json').read_text()).items():
        assert sha(ROOT/p) == h, p
    execution = json.loads((PAPER/'backend_execution_lock_v2.json').read_text())
    for p, h in execution['files'].items():
        assert sha(p) == h, p
    rows = []
    for w in lock['windows']:
        root = RUNTIME/'frontend'/w['run_slug']
        if not (root/'receipt.json').exists():
            continue
        receipt = json.loads((root/'receipt.json').read_text())
        verify_artifacts(receipt)
        if (root/'recovery_execution.json').exists():
            recovery=json.loads((root/'recovery_execution.json').read_text())
            assert sha(root/'receipt.json')==recovery['resulting_frontend_receipt_sha256']
            assert sha(PAPER/'cemetery_recovery_lock.json')==recovery['recovery_lock_sha256']
            for p,h in json.loads((PAPER/'cemetery_recovery_lock.json').read_text())['files'].items():
                assert sha(ROOT/p)==h,p
        assert sha(w['baseline_bag']) == w['baseline_sha256']
        assert receipt['arms']['L6']['source_stream_sha256'] == receipt['arms']['L-all']['source_stream_sha256']
        events = defaultdict(dict)
        for e in csv.DictReader((root/'candidate_lifecycle.csv').open()):
            if e['event'] in ('admit','continue'):
                key=(e['arm'],int(e['stamp_ns']))
                pid=int(e['public_id'])
                assert pid not in events[key]
                events[key][pid]=int(e['source_id'])
        published_maps = {}
        for arm in ['B','L6','L-all','C-all']:
            item = receipt['arms'][arm]
            ids = Counter(); n_candidate=0; n_messages=0; n_nonfeature=0
            previous = {}; previous_ns = None; arm_maps={}
            source = 'xfeat' if arm.startswith('L') else 'classical_gftt'
            source_file = (root/(source+'_source.jsonl')).open() if arm!='B' else None
            with rosbag.Bag(w['baseline_bag']) as base, rosbag.Bag(item['feature_bag']) as added:
                ai = iter(added.read_messages())
                for bt, bm, bs in base.read_messages():
                    at, am, ast = next(ai)
                    assert bt==at and bs==ast
                    if bt!=FEATURE:
                        assert serialized(bm)==serialized(am)
                        n_nonfeature+=1
                        continue
                    assert_backbone(bm,am); n_messages+=1
                    c=channels(am); ns=am.header.stamp.to_nsec()
                    ids.update(int(x) for x in c['id'])
                    if arm=='B':
                        continue
                    record=json.loads(next(source_file));assert ns==record['stamp_ns']
                    source_obs={o['source_id']:o for o in record['observations']}
                    mapping=events[arm,ns]
                    actual={int(x) for x in c['id'][len(bm.points):]}
                    assert set(mapping)==actual
                    if arm=='L6':assert len(actual)<=6
                    else:assert set(mapping.values())==set(source_obs)
                    current={}; mapped={}
                    for i in range(len(bm.points),len(am.points)):
                        pid=int(c['id'][i]);sid=mapping[pid];o=source_obs[sid]
                        expected={'p_u':o['point'][0],'p_v':o['point'][1],'quality':o['quality']}
                        for key,value in expected.items():assert c[key][i]==float(np.float32(value))
                        assert am.points[i].x==float(np.float32(o['normalized'][0]))
                        assert am.points[i].y==float(np.float32(o['normalized'][1]))
                        assert am.points[i].z==1.
                        velocity=(np.asarray(o['normalized'])-previous[pid])/((ns-previous_ns)*1e-9) if pid in previous else [0.,0.]
                        assert c['velocity_x'][i]==float(np.float32(velocity[0]))
                        assert c['velocity_y'][i]==float(np.float32(velocity[1]))
                        current[pid]=np.asarray(o['normalized'])
                        mapped[sid]=(am.points[i].x,am.points[i].y,c['p_u'][i],c['p_v'][i],c['quality'][i])
                    arm_maps[ns]=mapped;previous=current;previous_ns=ns;n_candidate+=len(actual)
                assert next(ai,None) is None
            if source_file:
                assert next(source_file,None) is None
                source_file.close()
            published_maps[arm]=arm_maps
            received_repeats=0
            for repeat in (1,2,3):
                target=RUNTIME/'backend'/w['run_slug']/arm/f'repeat{repeat}'
                if not (target/'receipt.json').exists():continue
                received=Counter()
                use_path=target/'backend_use.csv'
                for row in csv.reader(use_path.open()) if use_path.exists() else []:
                    if row[0]=='received':received[int(row[2])]+=int(row[3])
                if received==ids:received_repeats+=1
                else:
                    status=json.loads((target/'receipt.json').read_text())['status']
                    assert status!='COMPLETE', (w['run_slug'],arm,repeat,'complete but received ID mismatch')
            rows.append(dict(run_slug=w['run_slug'],arm=arm,feature_messages=n_messages,
                nonfeature_messages=n_nonfeature,candidate_observations=n_candidate,
                backbone_serialized_exact=True,source_coordinates_quality_exact=True,
                velocity_continuity_exact=True,received_per_id_exact_repeats=received_repeats,
                feature_bag_sha256=item['sha256']))
        for ns,small in published_maps['L6'].items():
            large=published_maps['L-all'][ns]
            assert small.items()<=large.items(), (w['run_slug'],ns)
        print('DELIVERY_AUDIT_PASS',w['run_slug'],flush=True)
    table(PAPER/'delivery_readback_audit.csv',rows)


if __name__=='__main__':
    main()
