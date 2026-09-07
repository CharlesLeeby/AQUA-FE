#!/usr/bin/env python3
"""Full-denominator B/C analysis using the exact additive evaluation core."""
from __future__ import annotations
from collections import Counter,defaultdict
import csv
import json
from pathlib import Path
import numpy as np
from run_classical_opportunity_expansion import ROOT,PAPER,RUNTIME,OLD,sha,save,verify
import analyze_additive_budget_v1 as inherited

ARMS=['B','C-all']

def table(p,data,fields=None):
    fields=fields or list(dict.fromkeys(k for r in data for k in r))
    with p.open('w',newline='') as f:
        w=csv.DictWriter(f,fieldnames=fields,lineterminator='\n');w.writeheader();w.writerows(data)

def classify(ape_b,ape_c,rpe_b,rpe_c):
    b,c=float(np.median(ape_b)),float(np.median(ape_c));br,cr=float(np.median(rpe_b)),float(np.median(rpe_c))
    spread=max(np.ptp(ape_b),np.ptp(ape_c));rspread=max(np.ptp(rpe_b),np.ptp(rpe_c));ad=c-b;rd=cr-br
    improvement=-ad>=max(.05*b,.01) and -ad>spread
    regression=ad>=max(.05*b,.01) and ad>spread
    guard=max(.05*br,.005,rspread)
    practical='PRACTICAL_GAIN' if improvement and rd<=guard else ('PRACTICAL_LOSS' if regression or rd>guard else 'SMALL_OR_UNCERTAIN')
    severe=bool(ad>max(.1*b,.01,spread) or rd>max(.1*br,.005,rspread))
    robust=bool(practical=='PRACTICAL_GAIN' and max(ape_c)<min(ape_b) and max(rpe_c)<=min(rpe_b)+max(.05*br,.005))
    tier='ROBUST_PRACTICAL_GAIN' if robust else ('PRACTICAL_GAIN' if practical=='PRACTICAL_GAIN' else ('DIRECTIONAL_GAIN' if c<b else 'NONE'))
    return dict(practical_classification=practical,severe_regression=severe,positive_level=tier,
        APE_delta_m=ad,APE_delta_pct=100*ad/b if b else '',RPE_delta_m=rd,RPE_delta_pct=100*rd/br if br else '',
        APE_repeat_range_threshold=float(spread),RPE_repeat_range_threshold=float(rspread),RPE_guard_m=float(guard))

def per_id_receipts(bag_path,target):
    import rosbag
    wanted=Counter();actual=Counter()
    with rosbag.Bag(str(bag_path)) as bag:
        for _,m,_ in bag.read_messages(topics=['/feature_tracker/feature']):
            c={c.name:c.values for c in m.channels};wanted.update(int(i) for i in c['id'])
    p=target/'backend_use.csv'
    if p.exists():
        for r in csv.reader(p.open()):
            if r[0]=='received':actual[int(r[2])]+=int(r[3])
    return p.exists() and actual==wanted

def readback(w,front):
    """Independent serialized source, public-ID, float32 and velocity readback."""
    import rosbag
    from uw_frontend.ros.additive_budget_v1 import assert_backbone,serialized,channels
    root=RUNTIME/'frontend'/w['run_slug'];out=root/'independent_delivery_receipt.json'
    if out.exists():
        r=json.loads(out.read_text())
        assert r['feature_bag_sha256']==front['arms']['C-all']['sha256'];return r
    events=defaultdict(dict)
    if (root/'candidate_lifecycle.csv').exists():
        for e in csv.DictReader((root/'candidate_lifecycle.csv').open()):
            if e['event'] in ('admit','continue'):events[int(e['stamp_ns'])][int(e['public_id'])]=int(e['source_id'])
    previous={};prevns=None;frames=[];nonfeature=0
    with rosbag.Bag(w['baseline_bag']) as b,rosbag.Bag(front['arms']['C-all']['feature_bag']) as c,(root/'classical_gftt_source.jsonl').open() as sf:
        ci=iter(c.read_messages())
        for bt,bm,bs in b.read_messages():
            ct,cm,cs=next(ci);assert (ct,cs)==(bt,bs)
            if bt!='/feature_tracker/feature':assert serialized(bm)==serialized(cm);nonfeature+=1;continue
            assert_backbone(bm,cm);ns=bm.header.stamp.to_nsec();record=json.loads(next(sf));assert record['stamp_ns']==ns
            obs={o['source_id']:o for o in record['observations']};mapping=events[ns];cc=channels(cm);bc=channels(bm)
            assert set(mapping)=={int(i) for i in cc['id'][len(bm.points):]}
            assert set(mapping.values())==set(obs)
            current={}
            for i in range(len(bm.points),len(cm.points)):
                pid=int(cc['id'][i]);o=obs[mapping[pid]]
                assert 10_000_000<=pid<2**24 and int(np.float32(pid))==pid
                for key,v in {'p_u':o['point'][0],'p_v':o['point'][1],'quality':o['quality']}.items():assert cc[key][i]==float(np.float32(v))
                assert cm.points[i].x==float(np.float32(o['normalized'][0])) and cm.points[i].y==float(np.float32(o['normalized'][1]))
                vel=(np.asarray(o['normalized'])-previous[pid])/((ns-prevns)*1e-9) if pid in previous else [0.,0.]
                assert cc['velocity_x'][i]==float(np.float32(vel[0])) and cc['velocity_y'][i]==float(np.float32(vel[1]))
                current[pid]=np.asarray(o['normalized'])
            previous=current;prevns=ns
            def coverage(ch):
                h,width=front['image_shape'];cells={(min(3,max(0,int(v/h*4))),min(5,max(0,int(u/width*6)))) for u,v in zip(ch['p_u'],ch['p_v'])}
                return len(cells)/24
            frames.append(dict(frame=len(frames),stamp_ns=ns,B_features=len(bm.points),C_features=len(cm.points),
                B_feature_coverage=coverage(bc),C_feature_coverage=coverage(cc),candidates=len(mapping)))
        assert next(ci,None) is None and next(sf,None) is None
    table(root/'independent_frame_audit.csv',frames)
    r=dict(run_slug=w['run_slug'],status='PASS',backbone_serialized_exact=True,nonfeature_messages_exact=nonfeature,
        source_coordinates_q_velocity_exact=True,float32_ID_exact=True,feature_messages=len(frames),
        feature_bag_sha256=front['arms']['C-all']['sha256'],
        B_feature_coverage_median=float(np.median([r['B_feature_coverage'] for r in frames])),
        C_feature_coverage_median=float(np.median([r['C_feature_coverage'] for r in frames])),
        frame_audit_sha256=sha(root/'independent_frame_audit.csv'))
    save(out,r);return r

def analyze():
    lock=verify();inherited.ROOT=ROOT;inherited.PAPER=PAPER;inherited.RUNTIME=RUNTIME
    backend={};frontrows=[];backrows=[];outcomes=[];cases=[];supports=[];armstats=[];delivery=[]
    activated={'A'}
    gate=RUNTIME/'batch_A_gate.json'
    if gate.exists() and json.loads(gate.read_text())['execute_batch_B']:activated.add('B')
    for w in sorted(lock['windows'],key=lambda w:(w['batch'],int(w['batch_order']))):
        slug=w['run_slug'];fp=RUNTIME/'frontend'/slug/'receipt.json'
        fr=json.loads(fp.read_text()) if fp.exists() else None
        outcome=dict(window_id=w['window_id'],run_slug=slug,sequence=w['sequence'],heldout_type=w['heldout_type'],
            heldout_scope=w['heldout_scope'],batch=w['batch'],start_index=w['start_index'],end_index_exclusive=w['end_index_exclusive'],
            classification='PENDING' if w['batch'] in activated else 'NOT_ACTIVATED',reason='',severe_regression=False,
            positive_level='NONE',new_C_failure=False,structural_failure=False,backend_attempted=0)
        case=dict(outcome,reference_kind='COLMAP/proxy, not independent GT',reference_poses=int(w['reference_poses']),
            raw_reference_span_s=float(w['duration_s']),notes=w['prior_project_exposure'],
            independent_feature_labels='Not evaluated.; set-level window outcomes only')
        if fr:
            inherited.verify_artifacts(fr);dr=readback(w,fr);delivery.append(dr)
            case.update({k:v for k,v in dr.items() if 'coverage' in k})
            c=fr['arms']['C-all'];case.update(candidate_published_count=c['total_published'],unique_candidate_IDs=c['public_ids'],
                candidate_IDs_ge4=c['chains_ge4'],candidate_IDs_ge10=c['chains_ge10'],candidate_lifetime_median=c['lifetime_median'],
                candidate_lifetime_max=c['lifetime_max'],candidate_peak_concurrent=c['max_concurrent'])
        for arm in ARMS:
            f=dict(window_id=w['window_id'],run_slug=slug,arm=arm,status='Not evaluated.')
            if fr:f.update(status='COMPLETE',**fr['arms'][arm],frontend_receipt=str(fp))
            frontrows.append(f)
            for rep in [1,2,3]:
                target=RUNTIME/'backend'/slug/arm/f'repeat{rep}';rp=target/'receipt.json'
                br=dict(window_id=w['window_id'],run_slug=slug,arm=arm,repeat=rep,status='Not evaluated.')
                if rp.exists():
                    br.update(inherited.backend_stats(target));br['received_per_id_exact']=per_id_receipts(br.get('feature_bag',fr['arms'][arm]['feature_bag']),target)
                    if not br['received_per_id_exact']:br['runability']='FAIL'
                    backend[(slug,arm,rep)]=br;outcome['backend_attempted']+=1
                backrows.append(br)
        errorfile=RUNTIME/'window_failures'/f'{slug}.json'
        if errorfile.exists():
            er=json.loads(errorfile.read_text());outcome.update(classification='FAIL',reason=er['reason'],structural_failure=True)
        elif outcome['backend_attempted']==6:
            bs=[backend[(slug,'B',r)] for r in [1,2,3]];cs=[backend[(slug,'C-all',r)] for r in [1,2,3]]
            allb=all(r['runability']=='PASS' for r in bs);allc=all(r['runability']=='PASS' for r in cs)
            outcome.update(new_C_failure=allb and not allc,severe_regression=allb and not allc,
                structural_failure=any(r['status'] in ('CAPACITY_UNSUPPORTED','BACKEND_FAILED','RESOURCE_LIMIT') or not r['received_per_id_exact'] for r in bs+cs))
            if not (allb and allc):
                outcome.update(classification='FAIL',reason=';'.join(f"{r['arm']}_r{r['repeat']}:{r['status']}:runability={r['runability']}" for r in bs+cs if r['runability']!='PASS'))
            summary,status=inherited.evaluate(w,['C-all','B'],backend)
            supports.append(dict(window_id=w['window_id'],status=status,support_json=json.dumps(summary['support']) if summary else '',artifact=str(PAPER/'common_support'/slug/'C-all_vs_B')))
            if summary:
                metrics={}
                for arm in ARMS:
                    for key,label in [('fixed_se3_ape_rmse_m','APE'),('fixed_se3_rpe_rmse_m','RPE'),('sim3_scale','fitted_scale')]:
                        vals=[summary['arms'][f'{arm}_r{r}'][key] for r in [1,2,3]];metrics[arm,label]=vals
                        for stat,v in [('min',min(vals)),('median',float(np.median(vals))),('max',max(vals))]:case[f'{arm}_{label}_{stat}']=v
                        for rep,value in zip([1,2,3],vals):backend[(slug,arm,rep)][label]=value
                    case[arm+'_unusual_repeat_instability']=bool(np.ptp(metrics[arm,'APE'])>max(.1*np.median(metrics[arm,'APE']),.01) or np.ptp(metrics[arm,'RPE'])>max(.1*np.median(metrics[arm,'RPE']),.005))
                classification=classify(metrics['B','APE'],metrics['C-all','APE'],metrics['B','RPE'],metrics['C-all','RPE'])
                if classification['positive_level']=='ROBUST_PRACTICAL_GAIN' and (sum(r['reset_count_proxy'] for r in cs)>sum(r['reset_count_proxy'] for r in bs) or sum(r['failure_detection_count'] for r in cs)>sum(r['failure_detection_count'] for r in bs)):
                    classification['positive_level']='PRACTICAL_GAIN'
                outcome.update(classification=classification.pop('practical_classification'),**classification)
                case['common_support_json']=json.dumps(summary['support'])
            elif allb and allc:outcome.update(classification='NOT_EVALUABLE',reason=status)
            for arm,reps in [('B',bs),('C-all',cs)]:
                for key in ['first_pose_delay_from_reference_start_s','trajectory_coverage','trajectory_length_m','received_candidate','residual_candidate',
                            'received_candidate_unique_ids','eligible_candidate_unique_ids','max_actual_eligible','reset_count_proxy','failure_detection_count',
                            'initialization_count','initialization_visual_imu_misalignment_count','wall_s']:
                    vals=[float(r[key]) for r in reps if r.get(key) not in ('',None,'Unknown')]
                    for stat,val in [('min',min(vals) if vals else 'Unknown'),('median',float(np.median(vals)) if vals else 'Unknown'),('max',max(vals) if vals else 'Unknown')]:case[f'{arm}_{key}_{stat}']=val
                case[arm+'_lost_tracking_count']='Unknown; reset/failure-detection log proxies reported separately'
                armstats.append({k:v for k,v in case.items() if k.startswith(arm+'_')}|dict(window_id=w['window_id'],arm=arm))
        case.update(outcome);case['practical_classification']=outcome['classification'];cases.append(case);outcomes.append(outcome)
    # backrows objects were updated in place with common-support per-repeat metrics.
    table(PAPER/'frontend_audit.csv',frontrows);table(PAPER/'backend_results.csv',backrows)
    table(PAPER/'window_outcomes.csv',outcomes);table(PAPER/'case_registry.csv',cases)
    for name,kind in [('positive_cases','PRACTICAL_GAIN'),('neutral_cases','SMALL_OR_UNCERTAIN'),('negative_cases','PRACTICAL_LOSS')]:
        table(PAPER/(name+'.csv'),[r for r in cases if r['classification']==kind],list(dict.fromkeys(k for r in cases for k in r)))
    table(PAPER/'failure_cases.csv',[r for r in cases if r['classification'] in ('FAIL','NOT_EVALUABLE')],list(dict.fromkeys(k for r in cases for k in r)))
    if supports:table(PAPER/'common_support_status.csv',supports)
    if armstats:table(PAPER/'backend_arm_summary.csv',armstats)
    if delivery:table(PAPER/'delivery_readback_audit.csv',delivery)
    current=[r for r in outcomes if r['batch'] in activated];done=all(r['classification'] not in ('PENDING','NOT_ACTIVATED') for r in current)
    counts=dict(Counter(r['classification'] for r in current));positives=[r for r in current if r['classification']=='PRACTICAL_GAIN']
    severe=sum(r['severe_regression'] for r in current);structural=sum(r['structural_failure'] for r in current)
    decision=dict(status='BATCH_RESOLVED' if done else 'IN_PROGRESS',activated_batches=sorted(activated),physical_windows_planned=len(current),
        physical_windows_replayed=sum(r['backend_attempted']>0 for r in current),backend_attempted=sum(r['backend_attempted'] for r in current),
        classification_counts=counts,severe_regression_count=severe,structural_failure_windows=structural,
        robust_practical_gain_count=sum(r['positive_level']=='ROBUST_PRACTICAL_GAIN' for r in current),
        practical_positive_sequences=sorted({r['sequence'] for r in positives}),
        scientific_decision='Unknown',next_step='Complete the frozen active batch and registered decision; no tuning or substitutions.')
    if done and gate.exists():
        decision['status']='COMPLETE'
        decision['expansion_status']='BATCH_B_COMPLETED' if 'B' in activated else 'EXPANSION_STOPPED_AFTER_BATCH_A'
        decision['scientific_decision']='CLASSICAL_ADDITIVE_OPPORTUNITY_CONFIRMED' if len(positives)>=2 and len({r['sequence'] for r in positives})>=2 and severe<=1 and structural<2 else 'ADDITIVE_OPPORTUNITY_NOT_GENERALIZED'
        decision['next_step']='Transfer the retained positive/negative/initialization cases to observation-utility / risk-mechanism research; no automatic C-all tuning.'
    (PAPER/'decision.json').write_text(json.dumps(decision,indent=2,ensure_ascii=False)+'\n')
    # The final research interpretation and old-case comparison are reviewed by
    # the operator; this checkpoint always exposes all requested first-page counts.
    lines=['# Classical additive opportunity expansion — evidence checkpoint','',
        'Status: '+decision['status']+'; scientific decision: '+decision['scientific_decision']+'.','',
        f"1. New prospective C-all physical windows replayed: {decision['physical_windows_replayed']}; replay attempts: {decision['backend_attempted']}.",
        '2. Activated roster: '+str(len(current))+' sequence-held-out / 0 window-held-out relative to the six C-all development windows; broader project exposure retained.',
        '3. Full activated denominator: '+json.dumps(counts)+'.',
        '4. ROBUST_PRACTICAL_GAIN: '+str(decision['robust_practical_gain_count'])+'.',
        '5. Practical positive sequences: '+json.dumps(decision['practical_positive_sequences'])+'.',
        '6. Severe regression windows: '+str(severe)+'.',
        '7. Candidate dose/lifetime/initialization comparison with old A02/Bus: pending final case interpretation; exact new fields in case_registry.csv and old tables remain frozen.',
        '8. Batch B activated: '+str('B' in activated)+'. Exact unactivated windows remain in the registry.',
        '9. Decision: '+decision['scientific_decision']+'.',
        '10. Case handoff: positive_cases.csv, neutral_cases.csv, negative_cases.csv, failure_cases.csv.',
        '11. Next step: '+decision['next_step'],'',
        '| Window | Batch | Class | Tier | B APE min / median / max (m) | C APE min / median / max (m) | Severe | Reason |',
        '|---|---|---|---|---|---|---|---|']
    for c in cases:
        def triple(arm):return ' / '.join(f"{c[arm+'_APE_'+k]:.6g}" for k in ['min','median','max']) if arm+'_APE_median' in c else 'Not evaluated.'
        lines.append(f"| {c['window_id']} | {c['batch']} | {c['classification']} | {c['positive_level']} | {triple('B')} | {triple('C-all')} | {c['severe_regression']} | {c['reason']} |")
    lines+=['','COLMAP/proxy is not independent GT. C-all is a classical opportunity probe, not the final AQUA-FE innovation. Technical repeats and neighboring windows are not independent population samples.',
        'Every valid comparison uses its own six-trajectory common support and the frozen additive criteria. Fitted scale is diagnostic. Missing/invalid comparisons are never replaced by per-arm unmatched APE.',
        'Candidate-set positives/negatives are not per-feature utility labels. Actual residual blocks may reuse an observation across optimization calls.',
        'Source and execution identities: source_and_backend_lock.json, backend_execution_lock_v2.json, evaluation_lock.json. Raw bags and full console logs remain under the isolated runtime root.']
    (PAPER/'report.md').write_text('\n'.join(lines)+'\n')
    print(json.dumps(decision,indent=2),flush=True);return decision

if __name__=='__main__':analyze()
