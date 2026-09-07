#!/usr/bin/env python3
"""Read-only frozen observation audit. Writes only the new paper/runtime roots."""
from pathlib import Path
from collections import defaultdict, Counter
from decimal import Decimal
import argparse,csv,gzip,hashlib,json,re,subprocess,time
import numpy as np

ROOT=Path(__file__).resolve().parents[1]
PAPER=ROOT/'papers/frontend_observation_utility_audit_v1'
OLD=ROOT/'papers/frontend_additive_budget_v1'
RUNTIME=Path('/media/ma/Data/AQUA-FE_WS_storage_offload/frontend_observation_utility_audit_v1')
SOURCE=RUNTIME.parent/'frontend_additive_budget_v1'
FEATURE='/feature_tracker/feature'

def sha(p):
 h=hashlib.sha256()
 with Path(p).open('rb') as f:
  for b in iter(lambda:f.read(2**20),b''):h.update(b)
 return h.hexdigest()
def rows(p):return list(csv.DictReader(Path(p).open()))
def table(p,rs):
 if not rs:return
 keys=list(dict.fromkeys(k for r in rs for k in r))
 with Path(p).open('w',newline='') as f:
  w=csv.DictWriter(f,keys);w.writeheader();w.writerows(rs)
def save(p,x):Path(p).write_text(json.dumps(x,indent=2,sort_keys=True,allow_nan=False)+'\n')
def stats(a,prefix=''):
 a=np.asarray(a,float);a=a[np.isfinite(a)]
 out={prefix+'n':len(a)}
 if len(a):out.update({prefix+k:float(v) for k,v in zip(['min','p10','median','p90','max'],np.quantile(a,[0,.1,.5,.9,1]))});out[prefix+'mean']=float(np.mean(a))
 return out

def logs():
 out=[];events=[];provenance=[]
 for r in rows(OLD/'backend_results.csv'):
  d=Path(r['run_dir']);receipt=json.loads((d/'receipt.json').read_text())
  for p in [d/'vins.log',d/'vins_output/vio.csv',d/'backend_use.csv']:
   assert sha(p)==receipt['artifacts'][str(p)],p
  text=(d/'vins.log').read_text();raw=text.splitlines();ev=[]
  for line_no,line in enumerate(raw,1):
   m=re.search(r'\[\s*(?:INFO|WARN|DEBUG|ERROR)\]\s*\[([\d.]+)(?:,\s*([\d.]+))?\]:\s*(.*)',line)
   if m:ev.append((Decimal(m[1]),line_no,m[2],m[3]))
  ev.sort();accepted=next((t for t,_,_,v in ev if 'Initialization finish!' in v),None)
  first=Decimal((d/'vins_output/vio.csv').read_text().splitlines()[0].split(',')[0]);front=next(x for x in rows(OLD/'frontend_frame_counts.csv') if x['run_slug']==r['run_slug'])
  firstfeature=Decimal(front['stamp_ns']);bias=[]
  for t,line_no,ros,v in ev:
   if any(s in v for s in ['Not enough features','misalign visual','gyroscope bias initial','Initialization finish','IMU excitation']):
    kind=next((k for s,k in [('Not enough features','relative_pose_reject'),('misalign visual','alignment_reject'),('gyroscope bias initial','gyro_bias_delta'),('Initialization finish','accepted'),('IMU excitation','low_excitation_warning')] if s in v),'Unknown')
    vals=[]
    if kind=='gyro_bias_delta':
     vals=[float(x) for x in v.split('calibration',1)[1].split()];bias.append(np.linalg.norm(vals))
    events.append(dict(run_slug=r['run_slug'],arm=r['arm'],repeat=r['repeat'],kind=kind,log_line=line_no,wall_clock_s=str(t),ros_clock_s=ros or '',feature_timestamp_ns='Unknown',before_accept=t<=accepted if accepted else '',value_json=json.dumps(vals),scale='Unknown',gravity='Unknown',normal_spectrum='Unknown',source='existing_frozen_log',run_dir=str(d)))
  init_lines=[v for t,_,_,v in ev if accepted is None or t<=accepted]
  # Glog single clock cannot be assigned exact sensor time; full-file count is explicit.
  solver_failure_lines=[i for i,l in enumerate(raw,1) if 'Linear solver failure' in l]
  z={k:r[k] for k in ['run_slug','arm','repeat','all_four_APE_rmse_m','all_four_RPE_rmse_m','all_four_sim3_scale']}
  z.update(first_feature_ns=str(firstfeature),first_pose_ns=str(first),first_pose_delay_s=str((first-firstfeature)*Decimal('1e-9')),
   relative_pose_rejections=sum('Not enough features' in v for v in init_lines),alignment_rejections=sum('misalign visual' in v for v in init_lines),gyro_calibrations=len(bias),gyro_delta_norm_max=max(bias) if bias else '',linear_solver_failure_mentions=len(solver_failure_lines),linear_failure_line_numbers=';'.join(map(str,solver_failure_lines)),init_count=r['initialization_count'],run_dir=str(d),log_sha256=sha(d/'vins.log'),receipt_sha256=sha(d/'receipt.json'))
  out.append(z);provenance.append({'path':str(d/'receipt.json'),'sha256':sha(d/'receipt.json')})
 table(PAPER/'existing_initialization_summary.csv',out);table(PAPER/'initialization_attempts.csv',events)
 save(PAPER/'existing_log_provenance.json',{'runs':provenance,'all_72_log_vio_use_hashes':'PASS','exact_attempt_feature_timestamps':'Unknown','event_rows_are_not_full_attempt_rows':True})
 print('existing logs',len(out),'events',len(events),flush=True)

def bearing(x):
 b=np.column_stack([x,np.ones(len(x))]);return b/np.linalg.norm(b,axis=1,keepdims=True)
def flow_jacobian(x):
 a,b=x.T;z=np.zeros(len(x));o=np.ones(len(x))
 return np.stack([np.column_stack([-o,z,a,a*b,-1-a*a,b]),np.column_stack([z,-o,b,1+b*b,-a*b,-a])],axis=1)
def gram(j,q):return np.einsum('nki,nkj,n->ij',j,j,q)
def infometrics(jb,jc,qb,qc):
 d=jb.shape[-1];hb=gram(jb,qb);hc=gram(jc,qc);lam=max(1e-12,np.trace(hb)/d*1e-6)
 h=hb+np.eye(d)*lam;ev,u=np.linalg.eigh(h);ev2=np.linalg.eigvalsh(h+hc);iv=np.linalg.inv(h)
 small=np.einsum('nki,ij,nlj->nkl',jc,iv,jc)*qc[:,None,None]
 individual=np.linalg.slogdet(small+np.eye(jc.shape[1]))[1] if len(jc) else np.array([])
 weak=np.einsum('nki,i->nk',jc,u[:,0]);wg=qc*np.sum(weak*weak,axis=1)
 b=jb.reshape(-1,d);c=jc.reshape(-1,d)
 b=b/np.maximum(np.linalg.norm(b,axis=1,keepdims=True),1e-20);c=c/np.maximum(np.linalg.norm(c,axis=1,keepdims=True),1e-20)
 redundancy=np.max(np.abs(c@b.T),axis=1).reshape(len(jc),-1).mean(axis=1) if len(c) and len(b) else np.full(len(jc),np.nan)
 ans=dict(klt_constraints=len(jb),candidate_constraints=len(jc),ridge=lam,trace_gain=float(np.trace(hc)),logdet_gain=float(np.log(ev2).sum()-np.log(ev).sum()),min_eigen_gain=float(ev2[0]-ev[0]),weak_direction_gain=float(u[:,0]@hc@u[:,0]),condition_before=float(ev[-1]/ev[0]),condition_after=float(ev2[-1]/ev2[0]),condition_change=float(ev2[-1]/ev2[0]-ev[-1]/ev[0]),candidate_information_effective_rank=float(np.trace(hc)**2/max(np.sum(hc*hc),1e-30)),gram_cosine=float(np.sum(hb*hc)/max(np.linalg.norm(hb)*np.linalg.norm(hc),1e-30)),independent_sum_logdet=float(np.sum(individual)))
 ans['collective_to_individual_logdet_ratio']=ans['logdet_gain']/max(ans['independent_sum_logdet'],1e-30)
 ans.update(stats(individual,'individual_logdet_'));ans.update(stats(wg,'individual_weak_'));ans.update(stats(redundancy,'nearest_KLT_row_cosine_'))
 return ans

def configs(w):
 import cv2
 c=cv2.FileStorage(w['backend_config_source'],cv2.FILE_STORAGE_READ)
 rot=c.getNode('body_T_cam0').mat()[:3,:3];td=c.getNode('td').real();h=int(c.getNode('image_height').real());width=int(c.getNode('image_width').real());imu=c.getNode('imu_topic').string();c.release()
 return rot,td,h,width,imu

def images_imu(w,times):
 import rosbag,cv2
 from scipy.spatial.transform import Rotation
 rot,td,h,width,topic=configs(w);ts=[];gy=[]
 with rosbag.Bag(w['input_bag']) as b:
  for _,m,_ in b.read_messages(topics=[topic]):ts.append(m.header.stamp.to_nsec());gy.append([m.angular_velocity.x,m.angular_velocity.y,m.angular_velocity.z])
 ts=np.array(ts,np.int64);gy=np.array(gy);assert np.all(np.diff(ts)>0)
 orient=[np.eye(3)]
 for i in range(1,len(ts)):orient.append(orient[-1]@Rotation.from_rotvec(gy[i-1]*(int(ts[i])-int(ts[i-1]))*1e-9).as_matrix())
 orient=np.array(orient);out={}
 for t in times:
  target=t+int(round(td*1e9));i=np.searchsorted(ts,target,side='right')-1
  if i<0 or target>ts[-1]:out[t]=None;continue
  out[t]=(orient[i]@Rotation.from_rotvec(gy[i]*(target-int(ts[i]))*1e-9).as_matrix())@rot
 return out

def raw_images(w,times):
 import rosbag,cv2
 wanted=set(times);emitted=set()
 with rosbag.Bag(w['input_bag']) as b:
  for idx,(_,m,_) in enumerate(b.read_messages(topics=[w['image_topic']])):
   t=m.header.stamp.to_nsec()
   if t not in wanted or idx%int(w['every_n'])!=int(w['frame_offset']):continue
   assert t not in emitted;emitted.add(t)
   if m._type.endswith('CompressedImage'):im=cv2.imdecode(np.frombuffer(m.data,np.uint8),cv2.IMREAD_GRAYSCALE)
   else:
    a=np.frombuffer(m.data,np.uint8).reshape(m.height,m.step)[:,:m.width*(3 if m.encoding in ['bgr8','rgb8'] else 1)]
    im=cv2.cvtColor(a.reshape(m.height,m.width,3),cv2.COLOR_RGB2GRAY if m.encoding=='rgb8' else cv2.COLOR_BGR2GRAY) if m.encoding in ['bgr8','rgb8'] else a
   yield t,im
 assert emitted==wanted,(len(emitted),len(wanted))

def patch_stats(im,pts):
 import cv2
 # 9x9 local mean/gradient, reflected border. No enhancer/network.
 mean=cv2.boxFilter(im.astype(np.float32)/255.,-1,(9,9),normalize=True)
 g=np.hypot(cv2.Sobel(im.astype(np.float32)/255.,-1,1,0),cv2.Sobel(im.astype(np.float32)/255.,-1,0,1))
 g=cv2.boxFilter(g,-1,(9,9),normalize=True)
 xy=np.rint(pts).astype(int);xy[:,0]=np.clip(xy[:,0],0,im.shape[1]-1);xy[:,1]=np.clip(xy[:,1],0,im.shape[0]-1)
 return mean[xy[:,1],xy[:,0]],g[xy[:,1],xy[:,0]]

def window(w):
 import rosbag
 from scipy.spatial import cKDTree
 slug=w['run_slug'];target=RUNTIME/'existing_data'/slug;target.mkdir(parents=True,exist_ok=False)
 begin=time.monotonic();receipt=json.loads((SOURCE/'frontend'/slug/'receipt.json').read_text())
 # Validate frozen input bags/source and provenance before using any rows.
 assert sha(w['input_bag'])==w['input_bag_sha256'];assert sha(w['baseline_bag'])==w['baseline_sha256']
 source_records={}
 for source in ['xfeat','classical_gftt']:
  path=SOURCE/'frontend'/slug/(source+'_source.jsonl');assert sha(path)==receipt['artifacts'][str(path)]
  source_records[source]=[json.loads(l) for l in path.open()]
 base=[]
 with rosbag.Bag(w['baseline_bag']) as bag:
  for _,m,_ in bag.read_messages(topics=[FEATURE]):
   c={v.name:np.asarray(v.values) for v in m.channels}
   base.append((m.header.stamp.to_nsec(),c,np.array([[p.x,p.y] for p in m.points])))
 times=[t for t,_,_ in base];ori=images_imu(w,times);rot,td,h,width,topic=configs(w)
 for src,recs in source_records.items():assert [r['stamp_ns'] for r in recs]==times
 prev={};first={};blengths=Counter();frames=[];information=[];allvalues=defaultdict(lambda:defaultdict(list));phasevalues=defaultdict(lambda:defaultdict(list))
 init=rows(PAPER/'existing_initialization_summary.csv');cuts={a:[int(r['first_pose_ns']) for r in init if r['run_slug']==slug and r['arm']==a] for a in ['B','L-all','C-all']}
 prevori=None;previm=None;prevglobal=None
 detail=gzip.open(target/'observations.csv.gz','wt',newline='');writer=None
 for f,((t,bc,bx),(it,im)) in enumerate(zip(base,raw_images(w,times))):
  assert t==it;ptsB=np.column_stack([bc['p_u'],bc['p_v']]);bids=bc['id'].astype(int)
  samples={'B':[dict(id=int(i),point=p,normalized=x,quality=float(q),age=0,fb=np.nan,ncc=np.nan,raw_quality=np.nan) for i,p,x,q in zip(bids,ptsB,bx,bc['quality'])]}
  for src,arm in [('xfeat','L-all'),('classical_gftt','C-all')]:samples[arm]=[dict(o,id=o['source_id']) for o in source_records[src][f]['observations']]
  current={};motion={};jac={};epij={};qvals={};R=ori[t].T@prevori if ori[t] is not None and prevori is not None else None
  occB=set(np.clip((ptsB[:,0]/width*6).astype(int),0,5)+6*np.clip((ptsB[:,1]/h*4).astype(int),0,3));tree=cKDTree(ptsB) if len(ptsB) else None
  # Common KLT motion is the only local reference for both candidate sources.
  bcommon=[(i,o) for i,o in enumerate(samples['B']) if ('B',o['id']) in prev]
  localtree=None
  if bcommon and R is not None:
   oldx=np.array([prev[('B',o['id'])]['x'] for _,o in bcommon]);currx=np.array([o['normalized'] for _,o in bcommon]);rotb=bearing(oldx)@R.T;rotb=rotb[:,:2]/rotb[:,2,None]
   bflow=currx-rotb;localtree=cKDTree(np.array([o['point'] for _,o in bcommon]))
  for arm,obs in samples.items():
   x=np.array([o['normalized'] for o in obs]).reshape(-1,2);px=np.array([o['point'] for o in obs]).reshape(-1,2);q=np.array([o['quality'] for o in obs]);qvals[arm]=q;jac[arm]=flow_jacobian(x);epi=[];eq=[]
   pm,pg=patch_stats(im,px) if len(px) else ([],[])
   dots=bearing(x)@bearing(bx).T
   if arm=='B':np.fill_diagonal(dots,-1)
   distances=tree.query(px,k=2 if arm=='B' else 1)[0] if len(px) and tree else np.full(len(px),np.nan)
   if arm=='B' and len(px):distances=distances[:,-1]
   sensitivity=[]
   from scipy.spatial.transform import Rotation
   for axis in np.eye(3):
    bp=bearing(x)@Rotation.from_rotvec(axis*1e-4).as_matrix().T
    jp=flow_jacobian(bp[:,:2]/bp[:,2,None]);sensitivity.append(np.linalg.norm(jp-jac[arm],axis=(1,2))/np.maximum(np.linalg.norm(jac[arm],axis=(1,2)),1e-15)/1e-4)
   sensitivity=np.max(sensitivity,axis=0)
   addcells=set(np.clip((px[:,0]/width*6).astype(int),0,5)+6*np.clip((px[:,1]/h*4).astype(int),0,3))-occB if len(px) else set()
   for i,o in enumerate(obs):
    key=(arm,o['id']);old=prev.get(key);streak=old['streak']+1 if old else 1
    if key not in first:first[key]=(x[i],ori[t])
    if arm=='B':blengths[o['id']]+=1
    d=dict(run_slug=slug,arm=arm,frame=f,stamp_ns=t,track_id=o['id'],q=o['quality'],raw_quality=o['raw_quality'],age_so_far=o['age'] if arm!='B' else streak,public_streak_so_far=streak,fb=o['fb'],ncc=o['ncc'],distance_to_KLT_px=float(distances[i]))
    d['bearing_novelty_rad']=float(np.arccos(np.clip(dots[i].max(),-1,1))) if len(bx) else np.nan
    d['jacobian_perturbation_sensitivity_per_rad']=float(sensitivity[i])
    if old and R is not None:
     br=R@bearing(old['x'].reshape(1,2))[0];bn=bearing(x[i:i+1])[0];rc=x[i]-br[:2]/br[2]
     angle=float(np.arctan2(np.linalg.norm(np.cross(br,bn)),np.dot(br,bn)))
     d.update(displacement_px=float(np.linalg.norm(px[i]-old['px'])),rotation_compensated_parallax_norm=float(np.linalg.norm(rc)),triangulation_angle_rad=angle,triangulation_condition_proxy=1/max(np.sin(angle),1e-12))
     epi.append(np.cross(br,bn).reshape(1,3));eq.append(q[i])
     if localtree:
      _,ix=localtree.query(px[i],k=min(8,len(bcommon)));pred=np.median(bflow[np.atleast_1d(ix)],axis=0)
      d['local_motion_residual_norm']=float(np.linalg.norm(rc-pred))
     d['patch_mean_abs_delta']=float(abs(pm[i]-old['mean']));d['global_corrected_patch_abs_delta']=float(abs((pm[i]-old['mean'])-(im.mean()/255.-prevglobal)));d['patch_gradient_abs_delta']=float(abs(pg[i]-old['gradient']))
    fx,fo=first[key]
    if fo is not None and ori[t] is not None:
     bfirst=ori[t].T@fo@bearing(fx.reshape(1,2))[0];bn=bearing(x[i:i+1])[0]
     d['parallax_so_far_rad']=float(np.arctan2(np.linalg.norm(np.cross(bfirst,bn)),np.dot(bfirst,bn)))
    current[key]=dict(x=x[i],px=px[i],mean=pm[i],gradient=pg[i],streak=streak)
    # Explicit post-outcome stage definitions for each technical repeat.
    for k,v in d.items():
     if k not in ['run_slug','arm','frame','stamp_ns','track_id'] and np.isfinite(v):
      allvalues[arm][k].append(v)
      for repeat,cut in enumerate(cuts[arm],1):phasevalues[(arm,repeat,'pre_init' if t<cut else 'post_init')][k].append(v)
    detailkeys=['run_slug','arm','frame','stamp_ns','track_id','q','raw_quality','age_so_far','public_streak_so_far','fb','ncc','distance_to_KLT_px','bearing_novelty_rad','jacobian_perturbation_sensitivity_per_rad','displacement_px','rotation_compensated_parallax_norm','triangulation_angle_rad','triangulation_condition_proxy','local_motion_residual_norm','patch_mean_abs_delta','global_corrected_patch_abs_delta','patch_gradient_abs_delta','parallax_so_far_rad']
    if writer is None:writer=csv.DictWriter(detail,detailkeys);writer.writeheader()
    writer.writerow(d)
   epij[arm]=(np.array(epi).reshape(-1,1,3),np.array(eq))
   frames.append(dict(run_slug=slug,arm=arm,frame=f,stamp_ns=t,observations=len(obs),occupied_KLT_cells=len(occB),added_cells=len(addcells)))
  for arm in ['L-all','C-all']:
   for model in ['unit_depth_flow','imu_epipolar_translation']:
    jb,jc,qb,qc=(jac['B'],jac[arm],qvals['B'],qvals[arm]) if model=='unit_depth_flow' else (*[epij[a][0] for a in ['B',arm]],*[epij[a][1] for a in ['B',arm]])
    if len(jb)==0 or len(jc)==0:continue
    for weighting in ['original_q','unit_q']:
     r=infometrics(jb,jc,qb if weighting=='original_q' else np.ones(len(qb)),qc if weighting=='original_q' else np.ones(len(qc)))
     r.update(run_slug=slug,arm=arm,frame=f,stamp_ns=t,model=model,weighting=weighting);information.append(r)
  prev=current;prevori=ori[t];previm=im;prevglobal=im.mean()/255.
  if f%100==0:print(slug,'frame',f,'/',len(base),flush=True)
 detail.close();table(target/'frame_summary.csv',frames);table(target/'information_frames.csv',information)
 summaries=[]
 for arm,vals in allvalues.items():
  r=dict(run_slug=slug,arm=arm,phase='all',repeat='not_applicable',observation_rows=len(vals['q']))
  for k,v in vals.items():r.update(stats(v,k+'_'))
  fs=[x for x in frames if x['arm']==arm];r.update(stats([x['observations'] for x in fs],'per_frame_count_'));r.update(stats([x['added_cells'] for x in fs],'added_cells_'))
  lifetime=[int(x['public_observations']) for x in rows(OLD/'candidate_lifecycle.csv') if x['run_slug']==slug and x['arm']==arm] if arm!='B' else list(blengths.values())
  r.update(stats(lifetime,'final_public_lifetime_'));r.update(final_tracks_ge4=sum(v>=4 for v in lifetime),final_tracks_ge10=sum(v>=10 for v in lifetime));summaries.append(r)
 for (arm,repeat,phase),vals in phasevalues.items():
  r=dict(run_slug=slug,arm=arm,phase=phase,repeat=repeat,observation_rows=len(vals['q']))
  for k,v in vals.items():r.update(stats(v,k+'_'))
  summaries.append(r)
 table(target/'candidate_summary.csv',summaries)
 info=[]
 for arm in ['L-all','C-all']:
  for model in ['unit_depth_flow','imu_epipolar_translation']:
   for weighting in ['original_q','unit_q']:
    sel=[r for r in information if r['arm']==arm and r['model']==model and r['weighting']==weighting]
    for repeat,phase in [(0,'all')]+[(r,s) for r in [1,2,3] for s in ['pre_init','post_init']]:
     sub=sel if repeat==0 else [z for z in sel if ('pre_init' if z['stamp_ns']<cuts[arm][repeat-1] else 'post_init')==phase]
     out=dict(run_slug=slug,arm=arm,model=model,weighting=weighting,repeat=repeat,phase=phase,frames=len(sub))
     for k in (sel[0] if sel else {}):
      if k not in ['run_slug','arm','frame','stamp_ns','model','weighting']:out.update(stats([z[k] for z in sub if k in z],k+'_'))
     info.append(out)
 table(target/'information_summary.csv',info)
 save(target/'receipt.json',dict(run_slug=slug,source_commit=subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip(),script_sha256=sha(__file__),wall_s=time.monotonic()-begin,frames=len(base),orientation_unavailable=sum(v is None for v in ori.values()),input_sha256=w['input_bag_sha256'],baseline_sha256=w['baseline_sha256'],source_receipt_sha256=sha(SOURCE/'frontend'/slug/'receipt.json'),outputs={str(p):sha(p) for p in target.iterdir() if p.is_file()}))
 print('COMPLETE',slug,flush=True)

def summarize():
 src=[];inf=[];under=[]
 for d in sorted((RUNTIME/'existing_data').iterdir()):
  if not (d/'receipt.json').exists():continue
  src+=rows(d/'candidate_summary.csv');inf+=rows(d/'information_summary.csv')
 for r in src:
  keys=['run_slug','arm','phase','repeat','observation_rows']+[k for k in r if any(x in k for x in ['motion_residual','patch_','fb_','ncc_'])]
  under.append({**{k:r[k] for k in keys},'physical_label':'Unknown','interpretation_label':'UNDERWATER_RELIABILITY_HYPOTHESIS','causal_per_point_harm_label':'Unknown'})
 table(PAPER/'candidate_source_comparison.csv',src);table(PAPER/'information_geometry_summary.csv',inf);table(PAPER/'underwater_reliability_audit.csv',under)
 print('summaries',len(src),len(inf),flush=True)

def main():
 p=argparse.ArgumentParser();p.add_argument('--logs',action='store_true');p.add_argument('--window');p.add_argument('--summarize',action='store_true');a=p.parse_args()
 if a.logs:logs()
 if a.window:
  windows=json.loads((OLD/'source_and_backend_lock.json').read_text())['windows']
  for w in windows:
   if a.window in ['all',w['run_slug']]:window(w)
 if a.summarize:summarize()
if __name__=='__main__':main()
