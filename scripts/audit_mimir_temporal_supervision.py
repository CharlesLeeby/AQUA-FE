#!/usr/bin/env python3
"""Reproduce the bounded v1 depth preflight from retained official ZIP members.

Does not create truth labels or infer depth encoding from a fitted trajectory.
"""
import argparse
import csv
import hashlib
import json
import os
from pathlib import Path
import struct
import subprocess
import zlib
os.environ.setdefault('OPENCV_IO_ENABLE_OPENEXR', '1')
import cv2
import numpy as np


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--artifacts', type=Path, required=True)
    p.add_argument('--split', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    args = p.parse_args()
    root = args.artifacts
    decoded = []
    for path in sorted((root / 'supervision').rglob('*.exr')):
        raw = path.read_bytes()
        if raw[:4] != b'v/1\x01':
            raise ValueError('invalid EXR magic')
        pos, channels = 8, None
        while raw[pos]:
            end = raw.index(b'\0', pos)
            name, pos = raw[pos:end].decode(), end + 1
            end = raw.index(b'\0', pos)
            pos = end + 1
            size = struct.unpack('<I', raw[pos:pos+4])[0]
            pos += 4
            if name == 'channels':
                channels = raw[pos:pos+size].hex()
            pos += size
        depth = cv2.imread(str(path), cv2.IMREAD_UNCHANGED)
        if depth is None or depth.ndim != 2:
            raise ValueError('unreadable or unexpected depth channels')
        decoded.append(dict(path=str(path), archive_member=path.relative_to(root/'supervision').as_posix(),
                            file_bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest(), crc32=zlib.crc32(raw),
                            shape=list(depth.shape), decoded_dtype=str(depth.dtype),
                            exr_channels_header_hex=channels, min=float(depth.min()), max=float(depth.max()),
                            pixels=int(depth.size), equal_one_pixels=int((depth == 1).sum()),
                            finite_pixels=int(np.isfinite(depth).sum()), unique_values=int(len(np.unique(depth))),
                            label_status='REJECTED_UNVERIFIED_DEPTH_ENCODING'))
    if not decoded:
        raise ValueError('no retained depth files')
    constant = next(x for x in decoded if x['min'] == x['max'] == 1)
    # Independent ImageMagick decode is a constant-image cross-check only;
    # its Q16 conversion must not be used as floating-point metric depth.
    magick = subprocess.run(['identify', '-format', '%w %h %[min] %[max] %k', constant['path']],
                            check=True, text=True, capture_output=True).stdout
    coverage = []
    for seq in json.loads(args.split.read_text())['sequences']:
        directory = root / (seq['sequence'].split('/')[0] + '.directory.json')
        if not directory.exists():
            coverage.append(dict(sequence=seq['sequence'], role=seq['role'], status='Not evaluated.'))
            continue
        members = json.loads(directory.read_text())
        with Path(seq['source']).open() as stream:
            rows = list(csv.DictReader(stream))
        dedup = list(dict.fromkeys((r['timestamp'], r['filename']) for r in rows))
        stamps = {r[0] for r in dedup[seq['start_index']:seq['end_index']:seq['stride']]}
        prefix = seq['sequence'] + '/auv0/depth/cam0/data/'
        selected = [x for x in members if x['name'].startswith(prefix) and Path(x['name']).stem in stamps]
        signature_count = sum(x['size'] == constant['file_bytes'] and x['crc'] == constant['crc32'] for x in selected)
        coverage.append(dict(sequence=seq['sequence'], role=seq['role'], window=[seq['start_index'],seq['end_index']],
                             selected_depth_members=len(selected), constant_sample_size_crc_matches=signature_count,
                             boundary='ZIP directory signature match, not full decoding of all members',
                             status='supervision unverified'))
    checks = dict(metric_depth_encoding='Unknown', pose_frame_and_direction='Unknown',
                  camera_extrinsics='Unknown', timestamp_alignment='Not evaluated.',
                  occlusion_and_static_masks='Not evaluated.', real_projection_examples='Not evaluated.')
    with args.output.open('x') as stream:
        json.dump(dict(decoded=decoded, coverage=coverage, independent_constant_decode=magick,
                       supervision_checks=checks, valid_truth_observations=0,
                       conclusion='SUPERVISION_UNAVAILABLE',
                       interpretation='Sampled official depth is constant or mostly one; metric encoding and geometry cannot be verified. This does not prove all MIMIR sequences unusable.'), stream, indent=2)
        stream.write('\n')
    print(json.dumps(dict(decoded_files=len(decoded), constant_files=sum(x['unique_values']==1 for x in decoded),
                          coverage=coverage, valid_truth_observations=0)))


if __name__ == '__main__':
    main()
