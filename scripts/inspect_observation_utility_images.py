#!/usr/bin/env python3
"""Fixed-frame evidence contact sheet; no point labels or image enhancement."""
import json
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import rosbag
from analyze_observation_utility_v1 import OLD,PAPER,SOURCE,raw_images,FEATURE,sha,save

def main():
 windows=json.loads((OLD/'source_and_backend_lock.json').read_text())['windows'];selected=['a02_0_900','a08_2700_3600','afrl_bus_s180_d045'];fig,axes=plt.subplots(3,2,figsize=(12,11));audit=[]
 for row,slug in enumerate(selected):
  w=next(x for x in windows if x['run_slug']==slug);base=[]
  with rosbag.Bag(w['baseline_bag']) as b:
   for _,m,_ in b.read_messages(topics=[FEATURE]):base.append(m)
  indices=[10,len(base)//2];times=[base[f].header.stamp.to_nsec() for f in indices]
  ims=dict(raw_images(w,times))
  streams={s:[json.loads(l) for l in (SOURCE/'frontend'/slug/(s+'_source.jsonl')).open()] for s in ['xfeat','classical_gftt']}
  for col,f in enumerate(indices):
   ax=axes[row,col];t=times[col];im=ims[t];ax.imshow(im,cmap='gray',vmin=0,vmax=255);c={c.name:c.values for c in base[f].channels}
   ax.scatter(c['p_u'],c['p_v'],s=5,c='white',alpha=.45,label='B')
   counts={}
   for s,color,marker in [('xfeat','#E69F00','o'),('classical_gftt','#00BFFF','+')]:
    pts=np.array([o['point'] for o in streams[s][f]['observations']]).reshape(-1,2);counts[s]=len(pts)
    ax.scatter(pts[:,0],pts[:,1],s=17,facecolors='none' if marker=='o' else color,edgecolors=color,marker=marker,linewidths=.7,label=s)
   ax.set_title(f'{slug} / output {f}\nX={counts["xfeat"]}, C={counts["classical_gftt"]}, B={len(c["id"])}',fontsize=10);ax.set_xticks([]);ax.set_yticks([])
   audit.append(dict(run_slug=slug,frame=f,stamp_ns=t,raw_image_sha256=__import__('hashlib').sha256(im.tobytes()).hexdigest(),selection='fixed output10 and midpoint; no outcome or outlier selection',particle_caustic_label='Unknown'))
 handles,labels=axes[0,0].get_legend_handles_labels();fig.legend(handles,labels,loc='lower center',ncol=3);fig.suptitle('Observed candidate locations; physical validity labels unavailable',fontsize=14);fig.tight_layout(rect=(0,.035,1,.97))
 p=PAPER/'analysis-output/figures';p.mkdir(parents=True,exist_ok=True);fig.savefig(p/'03-fixed-image-audit.png',dpi=170);plt.close(fig);save(PAPER/'image_audit_identity.json',dict(images=audit,figure_sha256=sha(p/'03-fixed-image-audit.png')))
if __name__=='__main__':main()
