#!/usr/bin/env python3
"""ROS-only extraction, separate from the model environment; no model inference."""
import argparse
import json
from pathlib import Path
import cv2
import numpy as np
import rosbag
from cv_bridge import CvBridge
from run_learned_recovery_frontend import controlled_pair

ROOT=Path(__file__).resolve().parents[1]
PAPER=ROOT/'papers/frontend_searaft_screening_v1'
RT=Path('/media/ma/Data/AQUA-FE_WS_storage_offload/frontend_searaft_screening_v1')

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--natural',action='store_true');args=parser.parse_args()
    cv2.setNumThreads(1)
    contract=json.loads((PAPER/'controlled_pair_source.json').read_text())
    destination=RT/('natural_inputs' if args.natural else 'controlled_inputs')
    destination.mkdir(exist_ok=False)
    bridge=CvBridge();manifest=[]
    for w in contract['windows']:
        selected=range(200) if args.natural else contract['controlled_base_offsets']
        images={};stamps=[]
        with rosbag.Bag(w['input_bag']) as bag:
            for i,(_,msg,_) in enumerate(bag.read_messages(topics=[w['image_topic']])):
                if i>=200:break
                stamps.append(msg.header.stamp.to_nsec())
                if i in selected:
                    if msg.encoding!='mono8':raise ValueError('Input differs from inspected mono8 identity: '+msg.encoding)
                    images[i]=bridge.imgmsg_to_cv2(msg,desired_encoding='mono8').copy()
        assert len(stamps)==200 and stamps[0]==w['first_stamp_ns'] and stamps[-1]==w['last_stamp_ns']
        assert all(a<b for a,b in zip(stamps,stamps[1:]))
        for offset,image in images.items():
            if args.natural:
                path=destination/(w['sequence']+'_'+str(offset)+'.png');assert cv2.imwrite(str(path),image)
                manifest.append(dict(sequence=w['sequence'],offset=offset,raw_index=w['raw_start']+offset,stamp_ns=stamps[offset],image=str(path)))
            else:
                for ci,case in enumerate(contract['controlled_cases']):
                    current,transform,occlusion=controlled_pair(image,case,contract,offset*10+ci)
                    slug='{}_{}_{}'.format(w['sequence'],offset,case['name'])
                    before=destination/(slug+'_previous.png');after=destination/(slug+'_current.png')
                    assert cv2.imwrite(str(before),image) and cv2.imwrite(str(after),current)
                    manifest.append(dict(pair_id=slug,sequence=w['sequence'],base_offset=offset,case=case['name'],
                        raw_index=w['raw_start']+offset,stamp_ns=stamps[offset],previous=str(before),current=str(after),
                        transform=transform.tolist(),occlusion=occlusion,image_shape=list(image.shape)))
        print('INPUTS_PREPARED',w['sequence'],len(images),'raw images',flush=True)
    (destination/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    (destination/'receipt.json').write_text(json.dumps(dict(generator='scripts/run_learned_recovery_frontend.py:controlled_pair',
        generator_commit='3bd6cc62a81edf2bb12e377a201499ebc8e62c11',reconstructed_from_original_generator=True,
        xfeat_inferences=0,phase='natural' if args.natural else 'controlled',entries=len(manifest)),indent=2)+'\n')

if __name__=='__main__':main()
