#!/usr/bin/env python3
"""One model lifetime: load, interface check, freeze pause, controlled and conditional natural."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time
import traceback

import cv2
import numpy as np
import torch
from uw_frontend.matchers.searaft_points import SeaRaftPoints

ROOT=Path(__file__).resolve().parents[1]
PAPER=ROOT/'papers/frontend_searaft_screening_v1'
RT=Path('/media/ma/Data/AQUA-FE_WS_storage_offload/frontend_searaft_screening_v1')

def save(path,data):
    temporary=path.with_suffix(path.suffix+'.tmp')
    temporary.write_text(json.dumps(data,indent=2,allow_nan=False)+'\n')
    temporary.replace(path)

def main():
    cv2.setNumThreads(1);torch.set_num_threads(1);torch.manual_seed(20260909);np.random.seed(20260909)
    torch.backends.cudnn.benchmark=False
    torch.backends.cuda.matmul.allow_tf32=False
    torch.backends.cudnn.allow_tf32=False
    source=RT/'official_SEA-RAFT'
    assert subprocess.check_output(['git','rev-parse','HEAD'],cwd=source,text=True).strip()=='9137517ba24e628442aec097d3afe71d03503b75'
    assert not subprocess.check_output(['git','status','--porcelain'],cwd=source,text=True).strip()
    assert not (RT/'controlled_predictions').exists(), 'Existing formal progress: do not restart or overwrite'
    model=SeaRaftPoints(source,RT/'model')
    manifest=json.loads((RT/'controlled_inputs/manifest.json').read_text())
    first=cv2.imread(manifest[0]['previous'],cv2.IMREAD_GRAYSCALE)
    yy,xx=np.mgrid[24:first.shape[0]-24:24,24:first.shape[1]-24:24]
    points=np.column_stack((xx.ravel(),yy.ravel()))
    smoke=[];fallback_error=None
    for name,image,target in [('identity',first,np.array([0.,0.])),
            ('translation',cv2.warpAffine(first,np.float32([[1,0,12],[0,1,-8]]),(first.shape[1],first.shape[0])),np.array([12.,-8.]))]:
        try:
            prediction=model.predict_points(first,image,points)
        except torch.cuda.OutOfMemoryError as error:
            if model.longest_edge is not None:raise
            fallback_error=str(error)
            save(RT/'initial_oom.json',dict(error=fallback_error,phase=name,pairs_completed=model.pairs))
            torch.cuda.empty_cache();model.longest_edge=640
            model.previous=model.current=None
            prediction=model.predict_points(first,image,points)
        delta=prediction['points']-points
        finite=np.isfinite(delta).all(axis=1)
        assert np.mean(finite)>.99, 'No usable numerical network output in interface check'
        smoke.append(dict(name=name,finite_fraction=float(np.mean(finite)),median_displacement=np.median(delta[finite],axis=0).tolist(),
            median_target_error_px=float(np.median(np.linalg.norm(delta[finite]-target,axis=1))),timing=prediction['timing']))
    import torchvision,huggingface_hub,safetensors
    receipt=json.loads((RT/'model/download_receipt.json').read_text())
    lock=dict(task='SEA-RAFT',official_source_commit='9137517ba24e628442aec097d3afe71d03503b75',
        model=receipt,official_config='config/eval/spring-M.json',inference_config=model.config,loading=model.loading,
        official_weights_loaded=True,model_load_count=1,precision='FP32',tf32=False,device=str(model.device),
        gpu=torch.cuda.get_device_name(0),python=os.sys.version,torch=torch.__version__,torchvision=torchvision.__version__,
        huggingface_hub=huggingface_hub.__version__,safetensors=safetensors.__version__,opencv=cv2.__version__,numpy=np.__version__,
        environment=os.sys.executable,threads=1,original_longest_edge_cap=model.longest_edge,
        fallback_oom=fallback_error,interface_pairs=smoke,interface_pair_count=model.pairs,
        real_controlled_pairs=0,deterministic_coordinate_tests='3 PASS',
        flow_coordinates='Original pixels; exact W/Wnet and H/Hnet; network internal unpad retained',
        protocol_sha256=hashlib.sha256((PAPER/'protocol.md').read_bytes()).hexdigest())
    save(PAPER/'model_lock.json',lock)
    save(PAPER/'status.json',dict(task='SEA-RAFT',status='RUNNING',phase='MODEL_LOCKED_AWAITING_FREEZE',
        official_weights_loaded=True,real_inferred_pairs=0,planned_controlled_pairs=48,interface_pairs=model.pairs,
        prior_blocker_resolved=True,pid=os.getpid()))
    print('MODEL_LOCK_READY',json.dumps(dict(weights=True,controlled_pairs=0,interface_pairs=model.pairs,cap=model.longest_edge,smoke=smoke)),flush=True)
    command=input('Type RUN after protocol/model-lock commit checkpoint: ')
    if command.strip()!='RUN':raise RuntimeError('Missing explicit local freeze release')
    from searaft_screening_measurements import run_screen
    run_screen(model,lock)

if __name__=='__main__':
    try:main()
    except BaseException as error:
        if isinstance(error,KeyboardInterrupt):raise
        traceback.print_exc()
        completed=len(list((RT/'controlled_predictions').glob('*.npz'))) if (RT/'controlled_predictions').exists() else 0
        save(RT/'runtime_failure.json',dict(error=repr(error),traceback=traceback.format_exc(),controlled_pairs_with_sparse_output=completed))
        raise
