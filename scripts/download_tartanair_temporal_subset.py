#!/usr/bin/env python3
"""Task-specific V1 selection; reuse existing range/ZIP helpers, never full ZIPs."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import remotezip
import requests
import download_mimir_uw_slam_subset as ranges

ROOT = Path('/mnt/data/AQUA-FE_WS/experiments/temporal_refinement_tartanair_v1')
BASE = 'https://airlab-cloud.andrew.cmu.edu:8080/swift/v1/AUTH_ac8533a83cff4d48bc8c608ad222d330/tartanair/'
# First four distinct physical scene names in the official V1 sorted list.
# abandonedfactory_night is the same physical scene and is grouped with its day version.
SCENES = ['abandonedfactory', 'amusement', 'carwelding', 'endofworld']
MODES = ['image_left', 'depth_left', 'flow_mask', 'flow_flow']


def directory(key):
    path = ROOT / 'official' / (key.replace('/', '_') + '.directory.json')
    if path.exists():
        return json.loads(path.read_text())
    url = BASE + key + '.zip'
    with remotezip.RemoteZip(url, timeout=45) as remote:
        ordered = sorted(remote.infolist(), key=lambda x: x.header_offset)
        members = [dict(name=x.filename, size=x.file_size, compressed=x.compress_size,
                        start=x.header_offset, end=(ordered[i+1].header_offset if i+1<len(ordered) else remote.start_dir)-1,
                        crc=x.CRC) for i, x in enumerate(ordered) if not x.is_dir()]
        result = dict(url=url, size=remote.size(), central_start=remote.start_dir, members=members)
    path.write_text(json.dumps(result))
    print('directory', key, len(members), flush=True)
    return result


def plan():
    keys = [scene + '/Easy/' + mode for scene in SCENES for mode in MODES]
    with ThreadPoolExecutor(4) as pool:
        tables = dict(zip(keys, pool.map(directory, keys)))
    selections, downloads = [], []
    for scene, role, cap in zip(SCENES, ['train', 'train', 'validation', 'test'], [1200,1200,600,600]):
        table = {mode: tables[scene+'/Easy/'+mode] for mode in MODES}
        names = {mode: {x['name']: x for x in table[mode]['members']} for mode in MODES}
        trajectories = sorted({n.split('/')[2] for n in names['image_left'] if '/image_left/' in n})
        chosen = None
        for trajectory in trajectories:
            prefix = scene + '/Easy/' + trajectory
            images = sorted(n for n in names['image_left'] if n.startswith(prefix+'/image_left/'))
            total = len(images)
            if total < 22 or prefix+'/pose_left.txt' not in names['image_left']:
                continue
            if not all(prefix+f'/image_left/{i:06d}_left.png' in names['image_left'] and
                       prefix+f'/depth_left/{i:06d}_left_depth.npy' in names['depth_left'] for i in range(total)):
                continue
            if not all(prefix+f'/flow/{i:06d}_{i+1:06d}_mask.npy' in names['flow_mask'] for i in range(total-1)):
                continue
            chosen = prefix
            break
        if chosen is None:
            raise RuntimeError('no complete trajectory in fixed scene '+scene)
        n = min(cap, total)
        selections.append(dict(sequence=chosen, role=role, camera='left', source_frames=total,
                               start_index=0, end_index=n, stride=1, source=str(ROOT/'data'/chosen)))
        probe_frames = [0,1,10,11,20,21]
        for mode in MODES:
            if mode == 'image_left':
                wanted = [chosen+f'/image_left/{i:06d}_left.png' for i in range(n)] + [chosen+'/pose_left.txt']
                probes = [chosen+f'/image_left/{i:06d}_left.png' for i in probe_frames] + [chosen+'/pose_left.txt']
            elif mode == 'depth_left':
                wanted = [chosen+f'/depth_left/{i:06d}_left_depth.npy' for i in range(n)]
                probes = [chosen+f'/depth_left/{i:06d}_left_depth.npy' for i in probe_frames]
            elif mode == 'flow_mask':
                wanted = [chosen+f'/flow/{i:06d}_{i+1:06d}_mask.npy' for i in range(n-1)]
                probes = [chosen+f'/flow/{i:06d}_{i+1:06d}_mask.npy' for i in [0,10,20]]
            else:
                wanted = probes = [chosen+f'/flow/{i:06d}_{i+1:06d}_flow.npy' for i in [0,10,20]]
            for name in wanted:
                if name not in names[mode]:
                    raise RuntimeError('missing '+name)
            downloads.append(dict(key=scene+'/Easy/'+mode, source=table[mode],
                                   wanted=wanted, probes=probes))
    result = dict(version='TartanAir V1', selection_rule='sorted distinct scene then Easy then first complete sequence; all selected windows start 0, stride1; no model outcome selection',
                  sequences=selections, downloads=downloads)
    path = ROOT/'download_plan.json'
    with path.open('x') as stream:
        json.dump(result, stream)
    for mode in ['probes','wanted']:
        compressed = unpacked = count = 0
        for item in downloads:
            selected = set(item[mode])
            for member in item['source']['members']:
                if member['name'] in selected:
                    count += 1; compressed += member['compressed']; unpacked += member['size']
        print(mode, dict(files=count, compressed_bytes=compressed, extracted_bytes=unpacked), flush=True)
    print('split', selections, flush=True)


def fetch(stage):
    plan = json.loads((ROOT/'download_plan.json').read_text())
    stage_key = 'probes' if stage == 'probe' else 'wanted'
    # Reuse sparse ZIP range downloader; only required members and ZIP index are fetched.
    for item in plan['downloads']:
        source = item['source']
        wanted = set(item[stage_key])
        missing = {name for name in wanted if not (ROOT/'data'/name).exists()}
        if not missing:
            continue
        members = [m for m in source['members'] if m['name'] in missing]
        selected_ranges = ranges.merge_ranges([(m['start'],m['end']) for m in members] + [(source['central_start'],source['size']-1)])
        tag = item['key'].replace('/','_') + '_' + stage
        partial = ROOT/'ranges'/(tag+'.partial')
        state = ROOT/'ranges'/(tag+'.json')
        print('fetch', item['key'], 'members',len(members), 'range_bytes',sum(e-s+1 for s,e in selected_ranges),flush=True)
        with requests.Session() as session:
            ranges.populate_partial_zip(session=session,url=source['url'],partial_path=partial,state_path=state,
                                        archive_size=source['size'],ranges=selected_ranges,chunk_size=8*1024**2,workers=4)
        receipt = ranges.extract_selected(partial,ROOT/'data',sorted(missing),item['key']+'.zip',dict(size=source['size'],md5=None))
        receipt['schema_version'] = 'tartanair-v1-selected-members'
        receipt['source'] = {k:source[k] for k in ['url','size','central_start']}
        receipt['selection'] = dict(sequence=next(s['sequence'] for s in plan['sequences'] if item['key'].startswith(s['sequence'].split('/')[0]+'/')),
                                     modalities='V1 left RGB/depth/pose/mask; three official flow files for geometry checks only',stage=stage)
        (ROOT/'ranges'/(tag+'.receipt.json')).write_text(json.dumps(receipt,indent=2))
        # Only this task's successfully extracted duplicate transport scratch.
        # Raw members, receipts and incomplete/failed downloads are retained.
        partial.unlink()


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('action',choices=['plan','probe','full'])
    a = p.parse_args()
    if a.action == 'plan':
        plan()
    else:
        fetch(a.action)
