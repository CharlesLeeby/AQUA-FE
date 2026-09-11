#!/usr/bin/env python3
"""Generate immutable B observations and birth-anchored V1 labels for the existing model."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import time
import cv2
import numpy as np
import yaml
from uw_frontend.datasets.tartanair_temporal import (
    load_poses,read_frame,read_mask,sample,anchor_world,visible_world,
)
from uw_frontend.temporal_refinement import extract_patch,require_verified_supervision
from uw_frontend.tracking.klt_tracker import KltTracker,KltConfig
from uw_frontend.quality.image_quality import score_image_quality
from uw_frontend.quality.feature_confidence import quality_to_sigma
from train_temporal_refinement import file_sha256


def sequence_cache(spec,config):
    root=Path(spec['source']);poses=load_poses(root)
    tracker=KltTracker(KltConfig(**config))
    states={};bank=[];rows=[];previous_mask=None
    started=time.perf_counter()
    for frame in range(spec['start_index'],spec['end_index']):
        gray,depth=read_frame(root,frame)
        mask=read_mask(root,frame) if frame<spec['end_index']-1 else None
        tracks,_=tracker.process(gray,score_image_quality(gray))
        ids=tracks.ids.tolist();uv=tracks.points.copy();n=len(ids)
        truth=np.full((n,2),np.nan,np.float32)
        reasons=np.full(n,'prior_invalid',dtype='<U40')
        mask_codes=np.full(n,-1,np.int16)
        new=[j for j,identity in enumerate(ids) if identity not in states]
        if new:
            world,birth_reason=anchor_world(uv[new],depth,poses[frame])
            codes=sample(mask,uv[new],True,border=255) if mask is not None else np.full(len(new),255)
            for k,j in enumerate(new):
                identity=ids[j];reason=birth_reason[k]
                if reason=='valid' and codes[k]!=0:
                    reason='unconfirmed_last_birth' if mask is None else 'official_mask_nonzero'
                reasons[j]=reason;mask_codes[j]=codes[k]
                truth[j]=uv[j] if reason=='valid' else np.nan
                states[identity]=dict(world=world[k],active=reason=='valid',birth_uv=uv[j].copy(),
                                      previous_uv=uv[j].copy(),previous_truth=truth[j].copy(),
                                      ref=None,prev=None,ref_valid=False,prev_valid=False)
        new_set=set(new)
        active=[j for j,identity in enumerate(ids) if j not in new_set and states[identity]['active']]
        if active:
            world=np.array([states[ids[j]]['world'] for j in active])
            prior_truth=np.array([states[ids[j]]['previous_truth'] for j in active])
            projected,current_reason=visible_world(world,depth,poses[frame])
            codes=sample(previous_mask,prior_truth,True,border=255)
            for k,j in enumerate(active):
                reason=current_reason[k] if codes[k]==0 else 'official_mask_nonzero'
                reasons[j]=reason;mask_codes[j]=codes[k]
                if reason=='valid':truth[j]=projected[k]
                states[ids[j]]['active']=reason=='valid'
        sigmas=quality_to_sigma(tracks.qualities)
        for j,identity in enumerate(ids):
            state=states[identity]
            patch,patch_reason=extract_patch(gray,uv[j]);index=len(bank);bank.append(patch)
            current_patch_valid=patch_reason=='valid'
            if state['ref'] is None:
                state['ref']=index;state['prev']=index
                state['ref_valid']=patch_reason=='valid';state['prev_valid']=state['ref_valid']
            patch_valid=patch_reason=='valid' and state['ref_valid'] and state['prev_valid']
            if patch_reason=='valid' and not patch_valid:
                patch_reason='reference_or_previous_patch_invalid'
            rows.append((identity,frame,int(tracks.ages[j])-1,uv[j].copy(),truth[j].copy(),reasons[j],
                         np.r_[uv[j]-state['previous_uv'],uv[j]-state['birth_uv']],
                         [state['ref'],state['prev'],index],patch_valid,patch_reason,
                         float(tracks.qualities[j]),float(sigmas[j]),int(mask_codes[j])))
            state['prev']=index;state['prev_valid']=current_patch_valid
            state['previous_uv']=uv[j].copy();state['previous_truth']=truth[j].copy()
        previous_mask=mask
        if frame%100==0:
            print(spec['sequence'],frame,'B observations',len(rows),'active labels',int((reasons=='valid').sum()),flush=True)
    out=dict(patch_bank=np.stack(bank).astype(np.float32),
             id=np.array([r[0] for r in rows],np.int64),frame=np.array([r[1] for r in rows],np.int32),
             age=np.array([r[2] for r in rows],np.int32),baseline=np.array([r[3] for r in rows],np.float32),
             truth=np.array([r[4] for r in rows],np.float32),label_reason=np.array([r[5] for r in rows]),
             label_valid=np.array([r[5]=='valid' for r in rows]),history=np.array([r[6] for r in rows],np.float32),
             patch_indices=np.array([r[7] for r in rows],np.int64),patch_valid=np.array([r[8] for r in rows]),
             patch_reason=np.array([r[9] for r in rows]),q=np.array([r[10] for r in rows],np.float32),
             sigma=np.array([r[11] for r in rows],np.float32),mask_code=np.array([r[12] for r in rows],np.int16),
             sequence=np.full(len(rows),spec['sequence']))
    summary=dict(sequence=spec['sequence'],role=spec['role'],frames=spec['end_index']-spec['start_index'],
                 observations=len(rows),tracks=len(states),valid_labels=int(out['label_valid'].sum()),
                 valid_tracks=int(len(np.unique(out['id'][out['label_valid']]))),
                 invalid_reasons=dict(Counter(out['label_reason'].tolist())),patch_reasons=dict(Counter(out['patch_reason'].tolist())),
                 wall_s=time.perf_counter()-started)
    return out,summary


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--split',type=Path,required=True);p.add_argument('--geometry',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    args=p.parse_args();split=json.loads(args.split.read_text());geometry=json.loads(args.geometry.read_text())
    if not geometry['passed']:raise ValueError('actual geometry did not pass')
    require_verified_supervision(geometry['supervision_checks'])
    config_path=Path('uw_frontend/configs/klt_frontend.yaml')
    config=yaml.safe_load(config_path.read_text())['klt']
    args.output.mkdir(parents=True,exist_ok=False)
    cv2.setNumThreads(2);summaries=[]
    for role in ['train','validation','test']:
        parts=[];offset=0
        for spec in split['sequences']:
            if spec['role']!=role:continue
            data,summary=sequence_cache(spec,config);summaries.append(summary)
            data['patch_indices']+=offset;offset+=len(data['patch_bank']);parts.append(data)
        data={key:np.concatenate([part[key] for part in parts]) for key in parts[0]}
        del parts
        target=args.output/(role+'.npz')
        print('writing',role,'observations',len(data['baseline']),flush=True)
        np.savez_compressed(target,**data)
        metadata=dict(role=role,cache_sha256=file_sha256(target),supervision_checks=geometry['supervision_checks'],
                      split=str(args.split.resolve()),split_sha256=file_sha256(args.split),
                      geometry=str(args.geometry),geometry_sha256=file_sha256(args.geometry),
                      config_sha256=file_sha256(config_path),sequences=[s for s in summaries if s['role']==role],
                      patch_representation='float32 original/255 single-patch bank with immutable causal ref/previous/current indices',
                      inference_inputs=['patch_bank via patch_indices','history','patch_valid'])
        target.with_suffix('.json').write_text(json.dumps(metadata,indent=2)+'\n')
        del data
    (args.output/'summary.json').write_text(json.dumps(summaries,indent=2)+'\n')
    print(json.dumps(summaries),flush=True)


if __name__=='__main__':
    main()
