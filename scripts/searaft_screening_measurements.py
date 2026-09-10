"""Fixed B/C/S query measurements and preregistered development gates."""
import ast
import csv
import json
from pathlib import Path
import time

import cv2
import numpy as np
from uw_frontend.quality.image_quality import score_image_quality
from uw_frontend.tracking.klt_tracker import KltConfig,KltTracker,_in_border
from uw_frontend.tracking.same_frame_recovery import recover_same_frame,RecoveryConfig
from uw_frontend.matchers.searaft_points import common_mask
from run_searaft_screening import ROOT,PAPER,RT,save


def original_preprocess():
    # Load just the unchanged pure function; do not import ROS in the model env.
    tree=ast.parse((ROOT/'uw_frontend/ros/export_vins_features.py').read_text())
    node=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='_preprocess_gray')
    namespace=dict(np=np,cv2=cv2,score_image_quality=score_image_quality)
    exec(compile(ast.Module(body=[node],type_ignores=[]),'<original _preprocess_gray>','exec'),namespace)
    return namespace['_preprocess_gray']

PREPROCESS=original_preprocess()

def write_csv(path,rows):
    fields=list(dict.fromkeys(k for r in rows for k in r))
    with path.open('x',newline='') as f:
        w=csv.DictWriter(f,fields,lineterminator='\n');w.writeheader();w.writerows(rows)

def working(image,cap):
    h,w=image.shape[:2]
    if cap and max(h,w)>cap:
        scale=cap/max(h,w);image=cv2.resize(image,(round(w*scale),round(h*scale)),interpolation=cv2.INTER_LINEAR)
    return image,np.array([image.shape[1]/w,image.shape[0]/h])

def to_original(points,scale):
    return (np.asarray(points)+.5)/scale-.5

def strong_lk(previous,current,points,scale):
    n=len(points);tick=time.perf_counter()
    predictions=np.full((n,2),np.nan);fb=np.full(n,np.nan)
    if n:
        params=dict(winSize=(31,31),maxLevel=4,criteria=(cv2.TERM_CRITERIA_EPS|cv2.TERM_CRITERIA_COUNT,40,.01))
        p0=np.float32(points).reshape(-1,1,2)
        p1,status,_=cv2.calcOpticalFlowPyrLK(previous,current,p0,None,**params)
        if p1 is not None and status is not None:
            good=status.ravel().astype(bool)&np.isfinite(p1.reshape(-1,2)).all(axis=1)
            predictions[good]=to_original(p1.reshape(-1,2)[good],scale)
            ix=np.flatnonzero(good)
            if len(ix):
                back,st,_=cv2.calcOpticalFlowPyrLK(current,previous,p1[ix],None,**params)
                if back is not None and st is not None:
                    ok=st.ravel().astype(bool)&np.isfinite(back.reshape(-1,2)).all(axis=1)
                    fb[ix[ok]]=np.linalg.norm((back.reshape(-1,2)[ok]-np.asarray(points)[ix[ok]])/scale,axis=1)
    return predictions,fb,time.perf_counter()-tick

def controlled_pair_measurement(model,pair,contract):
    raw=cv2.imread(pair['previous'],cv2.IMREAD_GRAYSCALE);cur=cv2.imread(pair['current'],cv2.IMREAD_GRAYSCALE)
    tick=time.perf_counter()
    original_gray=PREPROCESS(raw,'adaptive_clahe')
    kc=KltConfig(**contract['klt'])
    initial_tracker=KltTracker(kc)
    initial,_=initial_tracker.process(original_gray,score_image_quality(original_gray))
    p0=initial.points.copy()
    prevwork,scale=working(raw,model.longest_edge);curwork,_=working(cur,model.longest_edge)
    previous=original_gray if model.longest_edge is None else PREPROCESS(prevwork,'adaptive_clahe')
    current=PREPROCESS(curwork,'adaptive_clahe');q=score_image_quality(current)
    preprocessing=time.perf_counter()-tick
    tracker=initial_tracker
    if model.longest_edge is not None:
        tracker.prev_image=previous.copy();tracker.points=np.float32((p0+.5)*scale-.5)
    tick=time.perf_counter()
    b,_=tracker.process(current,q,replenish=False)
    b_time=time.perf_counter()-tick
    n=len(p0);bm=np.isin(initial.ids,b.ids)
    bx=np.full((n,2),np.nan)
    for tid,point in zip(b.ids,b.points):bx[int(tid)]=to_original(point,scale)
    bf=~bm
    query_work=np.float32((p0+.5)*scale-.5)
    cx,cfb,c_time=strong_lk(previous,current,query_work,scale)
    cm=common_mask(p0,cx,cfb,raw.shape)
    tick=time.perf_counter()
    cp,_=recover_same_frame(previous,current,q,query_work[bf],initial.ids[bf],initial.ages[bf],b,'C',
        klt_config=kc,config=RecoveryConfig(),death_reasons=tracker.last_death_reasons)
    cp_time=time.perf_counter()-tick
    cpm=np.isin(initial.ids,cp.ids)
    cpx=np.full((n,2),np.nan)
    for tid,point in zip(cp.ids,cp.points):cpx[int(tid)]=to_original(point,scale)
    s=model.predict_points(raw,cur,p0)
    matrix=np.array(pair['transform'])
    truth=p0@matrix[:,:2].T+matrix[:,2]
    visible=_in_border(truth,raw.shape,8)
    if pair['occlusion']:
        x0,y0,x1,y1=pair['occlusion'];guard=6
        visible&=~((truth[:,0]>=x0-guard)&(truth[:,0]<x1+guard)&(truth[:,1]>=y0-guard)&(truth[:,1]<y1+guard))
    data=dict(ids=initial.ids,p0=p0,truth=truth,visible=visible,b_failed=bf,B_points=bx,B_mask=bm,
        C_points=cx,C_fb=cfb,C_common=cm,C_production=cpm,C_production_points=cpx,
        S_points=s['points'],S_fb=s['fb_error'],S_common=s['valid'],S_info=s['raw_info'])
    timing=dict(pair_id=pair['pair_id'],sequence=pair['sequence'],case=pair['case'],
        classical_preprocess_quality_s=preprocessing,B_s=b_time,C_raw_s=c_time,C_production_s=cp_time,**s['timing'])
    return data,timing

def quantiles(values):
    return [float(x) for x in np.percentile(values,[50,90,95])] if len(values) else ['','','']

def metric_row(data,method,scope,metadata):
    visible=data['visible'];bf=data['b_failed'];n=len(bf)
    cx=data['C_points'];ce=np.linalg.norm(cx-data['truth'],axis=1)
    selected=np.ones(n,bool) if scope=='all_queries' else bf if scope=='B_failures' else bf&~(data['C_common']&visible&(ce<=2))
    if method=='B':points=data['B_points'];accepted=data['B_mask']
    elif method.startswith('C'):
        points=data['C_production_points'] if method=='C_production' else cx
        accepted=np.isfinite(cx).all(axis=1) if method=='C_raw' else data['C_common'] if method=='C_common' else data['C_production']
    else:
        points=data['S_points'];accepted=np.isfinite(points).all(axis=1) if method=='S_raw' else data['S_common']
    finite=np.isfinite(points).all(axis=1);error=np.linalg.norm(points-data['truth'],axis=1)
    acc=accepted&selected;vis=visible&selected
    correct=acc&visible&(error<=2);wrong=acc&~(visible&(error<=2))
    ev=error[vis&finite&accepted]
    med,p90,p95=quantiles(ev)
    h,w=metadata.get('image_shape',(0,0))
    outside=finite&((points[:,0]<0)|(points[:,0]>=w)|(points[:,1]<0)|(points[:,1]>=h)) if h else data[('C_production' if method=='C_production' else method[0])+'_outside']
    return dict(**{k:v for k,v in metadata.items() if k!='image_shape'},method=method,scope=scope,
        query_count=int(np.sum(selected)),visible_count=int(np.sum(vis)),invisible_count=int(np.sum(selected&~visible)),
        finite_count=int(np.sum(finite&selected)),missing_count=int(np.sum(~finite&selected)),outside_count=int(np.sum(outside&selected)),
        accepted=int(np.sum(acc)),correct=int(np.sum(correct)),wrong_accepted=int(np.sum(wrong)),invisible_accepted=int(np.sum(acc&~visible)),
        coverage=float(np.sum(acc)/np.sum(selected)) if np.any(selected) else '',
        correct_visible_rate=float(np.sum(correct)/np.sum(vis)) if np.any(vis) else '',
        wrong_rate=float(np.sum(wrong)/np.sum(selected)) if np.any(selected) else '',
        precision=float(np.sum(correct)/np.sum(acc)) if np.any(acc) else '',
        invisible_rate=float(np.sum(acc&~visible)/np.sum(selected&~visible)) if np.any(selected&~visible) else '',
        visible_epe_median=med,visible_epe_p90=p90,visible_epe_p95=p95,
        visible_le1_rate=float(np.sum(vis&accepted&(error<=1))/np.sum(vis)) if np.any(vis) else '',
        visible_le2_rate=float(np.sum(vis&accepted&(error<=2))/np.sum(vis)) if np.any(vis) else '')

def combine(items):
    result={k:np.concatenate([d[k] for d in items]) for k in items[0]}
    return result

def group_gate(data,sequence,case,raw=False):
    bf=data['b_failed'];vis=data['visible']&bf;invis=~data['visible']&bf
    ce=np.linalg.norm(data['C_points']-data['truth'],axis=1);se=np.linalg.norm(data['S_points']-data['truth'],axis=1)
    ca=(np.isfinite(data['C_points']).all(axis=1) if raw else data['C_common'])&bf
    sa=(np.isfinite(data['S_points']).all(axis=1) if raw else data['S_common'])&bf
    cc=ca&vis&(ce<=2);sc=sa&vis&(se<=2)
    nv=int(np.sum(vis));ni=int(np.sum(invis));n=int(np.sum(bf));ns=int(np.sum(sa))
    common=ca&sa&vis
    cp95=float(np.percentile(ce[common],95)) if np.any(common) else None
    sp95=float(np.percentile(se[common],95)) if np.any(common) else None
    delta=(np.sum(sc)-np.sum(cc))/nv if nv else None
    coverage=(np.sum(sa)-np.sum(ca))/n if n else None
    cwrong=int(np.sum(ca&~cc));swrong=int(np.sum(sa&~sc))
    sufficient=nv>=20 and (raw or (ns>=20 and ni>=1))
    guards=raw or (ns>0 and np.sum(sc)/ns>=.95 and n>0 and swrong/n<=max(.01,cwrong/n+.005) and ni>0 and np.sum(sa&invis)/ni<=.01)
    aa=sufficient and delta is not None and delta>=.05
    bb=sufficient and coverage is not None and coverage>=-.02 and np.sum(common)>=20 and cp95>0 and sp95<=.8*cp95
    return dict(sequence=sequence,case=case,stage='raw_gate' if raw else 'filtered_gate',
        B_failures=n,visible_B_failures=nv,invisible_B_failures=ni,C_accepted=int(np.sum(ca)),S_accepted=ns,
        C_correct=int(np.sum(cc)),S_correct=int(np.sum(sc)),C_wrong=cwrong,S_wrong=swrong,
        S_only=int(np.sum(sa&~ca)),C_only=int(np.sum(ca&~sa)),both=int(np.sum(ca&sa)),neither=int(np.sum(bf&~ca&~sa)),
        S_only_correct=int(np.sum(sc&~ca)),S_only_wrong=int(np.sum(sa&~ca&~sc)),
        S_invisible_accepted=int(np.sum(sa&invis)),correct_rate_delta=float(delta) if delta is not None else None,
        full_coverage_delta=float(coverage) if coverage is not None else None,common_visible_accepted=int(np.sum(common)),
        C_common_epe_p95=cp95,S_common_epe_p95=sp95,sufficient=bool(sufficient),A=bool(aa),B=bool(bb),
        error_guards=bool(guards),pass_group=bool((aa or bb) and guards))

def aggregate_controlled(manifest):
    pairs=[];rows=[];points_rows=[]
    for item in manifest:
        data=dict(np.load(RT/'controlled_predictions'/(item['pair_id']+'.npz')))
        h,w=item['image_shape']
        for arm in ['B','C','S','C_production']:
            p=data[arm+'_points'];data[arm+'_outside']=np.isfinite(p).all(axis=1)&((p[:,0]<0)|(p[:,0]>=w)|(p[:,1]<0)|(p[:,1]>=h))
        pairs.append((item,data))
        for method in ['B','C_raw','C_common','C_production','S_raw','S_common']:
            for scope in ['all_queries','B_failures','C_common_not_correct']:
                rows.append(metric_row(data,method,scope,dict(level='pair',pair_id=item['pair_id'],sequence=item['sequence'],case=item['case'],image_shape=item['image_shape'])))
        for i,tid in enumerate(data['ids']):
            r=dict(pair_id=item['pair_id'],sequence=item['sequence'],case=item['case'],track_id=int(tid),
                previous_x=float(data['p0'][i,0]),previous_y=float(data['p0'][i,1]),truth_x=float(data['truth'][i,0]),truth_y=float(data['truth'][i,1]),
                visible=bool(data['visible'][i]),B_failed=bool(data['b_failed'][i]))
            for arm in ['B','C','S']:
                r[arm+'_x'],r[arm+'_y']=data[arm+'_points'][i]
            for key in ['B_mask','C_common','C_production','S_common']:r[key]=bool(data[key][i])
            for key in ['C_fb','S_fb']:r[key]=float(data[key][i])
            for j in range(4):r['S_info_'+str(j)]=float(data['S_info'][i,j])
            points_rows.append(r)
    gates=[]
    for seq in ['A02','A08','H02','ALL']:
        for case in ['small','large','illumination_blur','outside_occluded','ALL']:
            selected=[d for item,d in pairs if (seq=='ALL' or item['sequence']==seq) and (case=='ALL' or item['case']==case)]
            data=combine(selected)
            for method in ['B','C_raw','C_common','C_production','S_raw','S_common']:
                for scope in ['all_queries','B_failures','C_common_not_correct']:
                    rows.append(metric_row(data,method,scope,dict(level='group',pair_id='',sequence=seq,case=case)))
            if seq!='ALL' and case!='ALL':
                gates.extend([group_gate(data,seq,case,False),group_gate(data,seq,case,True)])
    wins={}
    for stage in ['filtered_gate','raw_gate']:
        wins[stage]=[case for case in ['large','illumination_blur','outside_occluded'] if sum(g['stage']==stage and g['case']==case and g['pass_group'] for g in gates)>=2]
    write_csv(PAPER/'controlled_results.csv',rows)
    write_csv(PAPER/'controlled_comparison.csv',gates)
    write_csv(PAPER/'controlled_points.csv',points_rows)
    return dict(winning_types=wins,group_gates=gates,completed_pairs=len(pairs),
        overall={method:next(r for r in rows if r['level']=='group' and r['sequence']=='ALL' and r['case']=='ALL' and r['scope']=='B_failures' and r['method']==method)
            for method in ['C_raw','C_common','C_production','S_raw','S_common']})

def run_screen(model,lock):
    contract=json.loads((PAPER/'controlled_pair_source.json').read_text())
    manifest=json.loads((RT/'controlled_inputs/manifest.json').read_text())
    assert len(manifest)==48
    destination=RT/'controlled_predictions';destination.mkdir(exist_ok=False)
    times=[]
    for index,pair in enumerate(manifest):
        data,timing=controlled_pair_measurement(model,pair,contract)
        np.savez_compressed(destination/(pair['pair_id']+'.npz'),**data)
        times.append(timing)
        save(RT/'controlled_timing_progress.json',times)
        save(PAPER/'status.json',dict(task='SEA-RAFT',status='RUNNING',phase='CONTROLLED',official_weights_loaded=True,
            real_inferred_pairs=index+1,planned_controlled_pairs=48,model_load_count=1,network_forward_calls=model.forward_calls))
        print('CONTROLLED_COMPLETE',index+1,'/48',pair['pair_id'],flush=True)
    write_csv(PAPER/'timing.csv',times)
    result=aggregate_controlled(manifest)
    save(RT/'controlled_decision.json',result)
    natural=None
    if result['winning_types']['filtered_gate']:
        print('CONTROLLED_GATE_PASS',result['winning_types']['filtered_gate'],flush=True)
        from searaft_screening_natural import run_natural
        natural=run_natural(model,contract)
        decision='PROMISING_MEASUREMENT_CAPABILITY' if natural['opportunity_pass'] else 'CONTROLLED_GAIN_ONLY'
    else:
        decision='PREDICTION_GAIN_FILTERING_UNRESOLVED' if result['winning_types']['raw_gate'] else 'NO_MEASUREMENT_ADVANTAGE'
    final=dict(task='SEA-RAFT MEASUREMENT CAPABILITY SCREENING',decision=decision,official_weights_loaded=True,
        controlled_pairs_completed=48,model_load_count=1,failed_model_load_attempts=1,controlled=result,natural=natural,
        natural_status='COMPLETE' if natural is not None else 'Not evaluated.',network_forward_calls=model.forward_calls,
        interface_pair_count=lock['interface_pair_count'],checkpoint_count=1,training_steps=0,backend_replays=0,
        next_step='Publish this screening decision only; no automatic integration, tuning or expanded cases.',
        evidence_boundary='Controlled development measurements; natural physical identity Unknown; VINS benefit and system safety Not evaluated.')
    save(PAPER/'decision.json',final)
    save(PAPER/'status.json',dict(task='SEA-RAFT',status='COMPLETE',phase='SCREENING_COMPLETED',official_weights_loaded=True,
        real_inferred_pairs=48,planned_controlled_pairs=48,decision=decision,natural_status=final['natural_status'],backend_replays=0))
    print('SCREENING_COMPLETE',decision,flush=True)
