"""Official SEA-RAFT flow sampled at original image points; no LK refinement."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import time

import cv2
import numpy as np
import torch
import torch.nn.functional as F


def bilinear(field, points):
    """Exact bilinear interpolation, with NaN outside the sampling domain."""
    field=np.asarray(field)
    p=np.asarray(points,dtype=np.float64).reshape(-1,2)
    h,w=field.shape[:2]
    valid=np.isfinite(p).all(axis=1)&(p[:,0]>=0)&(p[:,0]<=w-1)&(p[:,1]>=0)&(p[:,1]<=h-1)
    out=np.full((len(p),field.shape[2]),np.nan,dtype=np.float64)
    q=p[valid];lo=np.floor(q).astype(int)
    hi=np.minimum(lo+1,[w-1,h-1]);frac=q-lo
    ax,ay=frac[:,0,None],frac[:,1,None]
    out[valid]=(field[lo[:,1],lo[:,0]]*(1-ax)*(1-ay)
        +field[lo[:,1],hi[:,0]]*ax*(1-ay)
        +field[hi[:,1],lo[:,0]]*(1-ax)*ay+field[hi[:,1],hi[:,0]]*ax*ay)
    return out


def restore_flow(flow, original_shape):
    h,w=original_shape[:2]
    nh,nw=flow.shape[-2:]
    result=F.interpolate(flow,size=(h,w),mode='bilinear',align_corners=False)
    return result*result.new_tensor([w/nw,h/nh])[None,:,None,None]


def common_mask(points, predicted, fb, shape):
    h,w=shape[:2]
    finite=np.isfinite(predicted).all(axis=1)&np.isfinite(fb)
    return finite&(fb<=1.)&(predicted[:,0]>=8)&(predicted[:,0]<w-8)&(predicted[:,1]>=8)&(predicted[:,1]<h-8)


class SeaRaftPoints:
    def __init__(self, source, snapshot, longest_edge=None):
        self.source=Path(source);self.snapshot=Path(snapshot)
        sys.path.insert(0,str(self.source/'core'))
        from raft import RAFT
        from utils.utils import load_ckpt
        from safetensors.torch import load_file
        cfg=json.loads((self.source/'config/eval/spring-M.json').read_text())
        assert cfg['iters']==4 and cfg['scale']==-1
        cfg.update(batch_size=1,gpus=[0])
        self.config=cfg
        tick=time.perf_counter()
        reference=load_file(str(self.snapshot/'model.safetensors'))
        # Official BasicBlock registers bn3 again as downsample.1. HF's
        # safetensors removes these shared aliases; its strict loader clashes
        # with PyTorch's auto-filled num_batches_tracked keys. Restore only
        # those exact aliases, with unchanged values, for the official .pth loader.
        aliases={}
        for k,v in list(reference.items()):
            if '.bn3.' in k:
                alias=k.replace('.bn3.','.downsample.1.')
                if alias not in reference:
                    reference[alias]=v
                    aliases[alias]=k
        self.model=RAFT(argparse.Namespace(**cfg))
        loaded=self.model.state_dict()
        if loaded.keys()!=reference.keys():
            raise RuntimeError('Checkpoint/model state keys differ: '+str((loaded.keys()-reference.keys(),reference.keys()-loaded.keys())))
        if any(loaded[k].shape!=reference[k].shape for k in loaded):
            raise RuntimeError('Checkpoint/model tensor shape mismatch')
        pth=self.snapshot/'Tartan-C-T-TSKH-spring540x960-M.pth'
        if not pth.exists():
            torch.save(reference,pth)
        # Upstream loader uses strict=False. The exhaustive checks on both
        # sides of this call make every missing/mismatched tensor fatal here.
        load_ckpt(self.model,str(pth))
        loaded=self.model.state_dict()
        mismatched=[k for k in loaded if loaded[k].shape!=reference[k].shape or not torch.equal(loaded[k].cpu(),reference[k])]
        if mismatched:
            raise RuntimeError('Checkpoint state mismatch: '+str(mismatched[:10]))
        self.loading=dict(strict_state_audit=True,upstream_loader='utils.utils.load_ckpt',state_tensors=len(loaded),exact_state_match=True,
            restored_shared_aliases=aliases,local_pth=str(pth),local_pth_sha256=hashlib.sha256(pth.read_bytes()).hexdigest(),
            parameters=sum(p.numel() for p in self.model.parameters()),load_s=time.perf_counter()-tick)
        del reference,loaded
        self.device=torch.device('cuda:0')
        self.model=self.model.eval().to(self.device)
        self.longest_edge=longest_edge
        self.previous=self.current=None
        self.forward=self.backward=self.info=None
        self.pairs=0
        self.forward_calls=0
        self.times={}
        print('OFFICIAL_CHECKPOINT_LOADED',json.dumps(self.loading),flush=True)

    def _image(self,image):
        if image.ndim==2:
            image=np.repeat(image[:,:,None],3,axis=2)
        if image.dtype!=np.uint8 or image.shape[2]!=3:
            raise ValueError('Expected uint8 RGB or grayscale image in 0..255')
        tensor=torch.as_tensor(np.ascontiguousarray(image)).permute(2,0,1)[None].float().to(self.device)
        h,w=image.shape[:2]
        if self.longest_edge and max(h,w)>self.longest_edge:
            ratio=self.longest_edge/max(h,w)
            tensor=F.interpolate(tensor,size=(round(h*ratio),round(w*ratio)),mode='bilinear',align_corners=False)
        return F.interpolate(tensor,scale_factor=.5,mode='bilinear',align_corners=False)

    @torch.inference_mode()
    def _flow(self,one,two,shape):
        torch.cuda.synchronize()
        tick=time.perf_counter()
        output=self.model(one,two,iters=4,test_mode=True)
        torch.cuda.synchronize()
        elapsed=time.perf_counter()-tick
        self.forward_calls+=1
        tick=time.perf_counter()
        flow=restore_flow(output['flow'][-1],shape)[0].permute(1,2,0).cpu().numpy()
        info=F.interpolate(output['info'][-1],size=shape[:2],mode='bilinear',align_corners=False)[0].permute(1,2,0).cpu().numpy()
        torch.cuda.synchronize()
        return flow,info,elapsed,time.perf_counter()-tick

    def prepare_pair(self,previous,current):
        if self.previous is not None and np.array_equal(previous,self.previous) and np.array_equal(current,self.current):
            return
        if previous.shape!=current.shape:
            raise ValueError('Image pair shape mismatch')
        tick=time.perf_counter()
        one,two=self._image(previous),self._image(current)
        torch.cuda.synchronize()
        preprocessing=time.perf_counter()-tick
        torch.cuda.reset_peak_memory_stats()
        forward,info,ft,fr=self._flow(one,two,previous.shape)
        backward,_,bt,br=self._flow(two,one,previous.shape)
        self.forward,self.backward,self.info=forward,backward,info
        self.previous,self.current=previous,current
        self.pairs+=1
        self.times=dict(preprocess_s=preprocessing,forward_gpu_s=ft,backward_gpu_s=bt,restore_transfer_s=fr+br,
            peak_allocated_bytes=torch.cuda.max_memory_allocated(),peak_reserved_bytes=torch.cuda.max_memory_reserved(),
            network_height=int(one.shape[-2]),network_width=int(one.shape[-1]))

    def predict_points(self,image_prev,image_cur,points_prev):
        self.prepare_pair(image_prev,image_cur)
        points=np.asarray(points_prev,dtype=np.float64).reshape(-1,2)
        tick=time.perf_counter()
        flow=bilinear(self.forward,points)
        prediction=points+flow
        information=bilinear(self.info,points)
        sample_s=time.perf_counter()-tick
        tick=time.perf_counter()
        reverse=bilinear(self.backward,prediction)
        fb=np.linalg.norm(flow+reverse,axis=1)
        valid=common_mask(points,prediction,fb,image_prev.shape)
        return dict(points=prediction,valid=valid,fb_error=fb,raw_info=information,
                    timing=dict(self.times,sampling_s=sample_s,fb_checks_s=time.perf_counter()-tick))
