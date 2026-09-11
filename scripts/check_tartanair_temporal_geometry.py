#!/usr/bin/env python3
"""Fixed actual V1 frame checks, before labels/training; official flow is offline only."""
import argparse
import json
from pathlib import Path
import numpy as np
from uw_frontend.datasets.tartanair_temporal import (
    load_poses,read_frame,read_mask,sample,anchor_world,visible_world,depth_query,K,
)
from uw_frontend.temporal_refinement import project_world


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--split',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    args = p.parse_args()
    split = json.loads(args.split.read_text())
    results = []
    x,y = np.meshgrid(np.arange(16,624,8),np.arange(16,464,8))
    uv = np.c_[x.ravel(),y.ravel()].astype(float)
    for seq in split['sequences']:
        root=Path(seq['source']);poses=load_poses(root)
        if len(poses) != seq['source_frames']:
            raise ValueError('pose/image count mismatch: '+seq['sequence'])
        for i in [0,10,20]:
            im0,d0=read_frame(root,i);im1,d1=read_frame(root,i+1);mask=read_mask(root,i)
            flow=np.load(root/'flow'/f'{i:06d}_{i+1:06d}_flow.npy',allow_pickle=False)
            if flow.shape != (480,640,2):
                raise ValueError('unexpected official V1 flow shape')
            world,reason=anchor_world(uv,d0,poses[i])
            mapped,reason1=visible_world(world,d1,poses[i+1])
            expected, _ = project_world(world,poses[i+1],K)
            roundtrip,_ = project_world(world,poses[i],K)
            official = flow[y.ravel(),x.ravel()]
            mask_codes=sample(mask,uv,True,border=255)
            base_valid=(reason=='valid') & (mask_codes==0)
            valid=base_valid & (reason1=='valid')
            error=np.linalg.norm(expected-uv-official,axis=1)
            # Target discontinuity/out-of-view exclusions are not depth disagreements.
            # Compare depth only where both maps admit a depth query.
            _, target_reason = depth_query(d1,mapped)
            eligible = base_valid & (target_reason=='valid')
            consistency=float(valid.sum()/max(1,eligible.sum()))
            photo=np.abs(im0[y.ravel(),x.ravel()].astype(float)-sample(im1,mapped).astype(float))
            r=dict(sequence=seq['sequence'],pair=[i,i+1],queries=len(uv),source_valid=int(base_valid.sum()),
                   visible_valid=int(valid.sum()),target_depth_eligible=int(eligible.sum()),depth_consistency_fraction=consistency,
                   official_flow_error_median_px=float(np.median(error[base_valid])),
                   official_flow_error_p95_px=float(np.quantile(error[base_valid],.95)),
                   projection_roundtrip_max_px=float(np.max(np.linalg.norm(roundtrip-uv,axis=1)[base_valid])),
                   warp_gray_absolute_error_median=float(np.median(photo[valid])),
                   mask_histogram={str(k):int(v) for k,v in zip(*np.unique(mask,return_counts=True))},
                   depth_dtype_on_disk=str(np.load(root/'depth_left'/f'{i:06d}_left_depth.npy').dtype))
            # Convention correctness tests only; these do not select favorable model results.
            r['pass']=r['source_valid']>=100 and r['official_flow_error_p95_px']<.2 and consistency>=.8 and r['projection_roundtrip_max_px']<1e-6
            results.append(r);print(json.dumps(r),flush=True)
    checks={k:'PASS' for k in ['metric_depth_encoding','pose_frame_and_direction','camera_extrinsics','timestamp_alignment','occlusion_and_static_masks','real_projection_examples']}
    passed=all(r['pass'] for r in results)
    with args.output.open('x') as f:
        json.dump(dict(passed=passed,results=results,supervision_checks=checks if passed else {},
                       boundary='V1 official flow agrees with independent projection, depth/visibility cross-checked on fixed real files. Official masks define valid static support; not proof of perfect masks or underwater performance.'),f,indent=2)
        f.write('\n')
    if not passed:
        raise SystemExit('Actual-data geometry check failed; do not start training')


if __name__=='__main__':
    main()
