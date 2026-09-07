#!/usr/bin/env python3
"""Supplement completed case tables with timing, provenance and old-control context.

This does not recalculate or change any practical/severe classification.
Run only after the active matrix is complete and the batch controller has exited.
"""
import csv
from collections import defaultdict
from decimal import Decimal
import json
from pathlib import Path
import statistics

from run_classical_opportunity_expansion import ROOT,PAPER,RUNTIME,OLD,sha,save,verify

def rows(p):
    with Path(p).open() as f:return list(csv.DictReader(f))

def table(p,data):
    keys=list(dict.fromkeys(k for r in data for k in r))
    with Path(p).open('w',newline='') as f:
        w=csv.DictWriter(f,fieldnames=keys,lineterminator='\n');w.writeheader();w.writerows(data)

def summarize(row,prefix,values):
    for label,val in [('min',min(values) if values else 'Unknown'),('median',statistics.median(values) if values else 'Unknown'),('max',max(values) if values else 'Unknown')]:
        row[prefix+'_'+label]=val

def main():
    import rosbag
    verify();decision=json.loads((PAPER/'decision.json').read_text())
    assert decision['status']=='COMPLETE','No final supplement from incomplete evidence'
    lock=json.loads((PAPER/'source_and_backend_lock.json').read_text());windows={w['window_id']:w for w in lock['windows']}
    cases=rows(PAPER/'case_registry.csv');back=rows(PAPER/'backend_results.csv')
    before={r['window_id']:(r['classification'],r['positive_level'],r['severe_regression']) for r in cases}
    history={r['window_id']:r for r in rows(PAPER/'broader_history_exposure_audit.csv')}
    oldfront=rows(OLD/'frontend_audit.csv');oldback=rows(OLD/'backend_results.csv');old_positive=[]
    for slug in ['a02_0_900','afrl_bus_s180_d045']:
        f=next(r for r in oldfront if r['run_slug']==slug and r['arm']=='C-all')
        row=dict(case_origin='OLD_OUTCOME_KNOWN_DEVELOPMENT',window_id=slug)
        for k in ['total_published','max_concurrent','public_ids','chains_ge4','chains_ge10','lifetime_median','lifetime_max']:row[k]=f[k]
        s=json.loads((OLD/'common_support'/slug/'C-all_vs_B/common_support_summary.json').read_text())
        for arm in ['B','C-all']:
            for key,label in [('fixed_se3_ape_rmse_m','APE'),('fixed_se3_rpe_rmse_m','RPE'),('sim3_scale','fitted_scale')]:
                summarize(row,arm+'_'+label,[s['arms'][arm+'_r'+str(r)][key] for r in [1,2,3]])
            for key in ['first_pose_delay_from_reference_start_s','initialization_visual_imu_misalignment_count','residual_candidate']:
                summarize(row,arm+'_'+key,[float(r[key]) for r in oldback if r['run_slug']==slug and r['arm']==arm])
        row['artifact']=str(OLD/'common_support'/slug/'C-all_vs_B/common_support_summary.json')
        old_positive.append(row)
    table(PAPER/'old_positive_comparison_reference.csv',old_positive)
    resources=[];lifecycle=[];supply=[]
    for c in cases:
        w=windows[c['window_id']];slug=w['run_slug'];c['broader_project_history_status']=history[c['window_id']]['broader_history_status']
        c['broader_history_evidence']=history[c['window_id']]['known_overlapping_intervals']
        c['heldout_scope']='six_C_all_development_windows; not globally unseen project data'
        c['per_feature_positive_or_negative_labels']='Not evaluated.; no individual candidate labels inferred from window class'
        fp=RUNTIME/'frontend'/slug/'receipt.json'
        if not fp.exists():continue
        fr=json.loads(fp.read_text());bp=RUNTIME/'baseline'/slug/'receipt.json';prep=RUNTIME/'prepared'/slug/'receipt.json'
        resources.append(dict(window_id=w['window_id'],batch=w['batch'],preparation_wall_s=json.loads(prep.read_text())['wall_s'],
            fresh_B_export_wall_s=json.loads(bp.read_text())['wall_s'],C_source_generation_wall_s=fr['generation_wall_s'],
            B_merge_audit_wall_s=fr['arms']['B']['merge_wall_s'],C_merge_audit_wall_s=fr['arms']['C-all']['merge_wall_s'],
            C_generation_peak_rss_kib=fr['peak_rss_kib'],timing_boundary='separate CPU-stage timings, nonexclusive host; B merge is not B inference cost'))
        supply.append(dict(window_id=w['window_id'],**fr['source_counters']['classical_gftt']))
        starts={};ends={};lengths=defaultdict(int);source={}
        path=RUNTIME/'frontend'/slug/'candidate_lifecycle.csv'
        for e in rows(path) if path.exists() else []:
            if e['event'] not in ('admit','continue'):continue
            pid=int(e['public_id']);ns=int(e['stamp_ns']);starts.setdefault(pid,ns);ends[pid]=ns;lengths[pid]+=1;source[pid]=e['source_id']
        seconds=[]
        for pid,n in lengths.items():
            span=(ends[pid]-starts[pid])/1e9;seconds.append(span)
            lifecycle.append(dict(window_id=w['window_id'],public_id=pid,source_id=source[pid],public_observations=n,
                first_stamp_ns=starts[pid],last_stamp_ns=ends[pid],observed_span_s=span,exact_private_termination_reason='Unknown'))
        assert len(lengths)==fr['arms']['C-all']['public_ids']
        assert sum(lengths.values())==fr['arms']['C-all']['total_published']
        c['candidate_lifetime_seconds_median']=statistics.median(seconds) if seconds else 0.
        c['candidate_lifetime_seconds_max']=max(seconds) if seconds else 0.
        stamp0=Decimal(w['start_stamp_ns'])/Decimal(1_000_000_000)
        for arm in ['B','C-all']:
            rr=[r for r in back if r['run_slug']==slug and r['arm']==arm and r['status']!='Not evaluated.']
            for key,label in [('first_pose_sensor_s','first_pose_delay_from_raw_start_s'),('initialization_finish_first_ros_clock_s','initialization_ROS_clock_delay_from_raw_start_s')]:
                vals=[float(Decimal(r[key])-stamp0) for r in rr if r.get(key) not in ('',None,'Unknown')]
                summarize(c,arm+'_'+label,vals)
            c[arm+'_per_ID_receipts_exact']=all(r.get('received_per_id_exact')=='True' for r in rr) if len(rr)==3 else 'Unknown'
            c[arm+'_backend_receipt_count']=len(rr)
            c[arm+'_runability_failed_repeats']=';'.join(r['repeat'] for r in rr if r.get('runability')!='PASS')
        for metric,absolute in [('APE',.01),('RPE',.005)]:
            baseline=c.get('B_'+metric+'_median')
            if baseline not in ('',None,'Unknown'):
                b=float(baseline)
                exceeded=[r['repeat'] for r in back if r['run_slug']==slug and r['arm']=='C-all'
                          and r.get(metric) not in ('',None,'Unknown') and float(r[metric])-b>max(.1*b,absolute)]
                c['C_single_repeat_'+metric+'_severe_vs_B_median_repeats']=';'.join(exceeded)
                c['C_single_repeat_'+metric+'_severe_vs_B_median_count']=len(exceeded)
            else:
                c['C_single_repeat_'+metric+'_severe_vs_B_median_count']='Not evaluated.'
        c['single_repeat_flag_definition']='frozen descriptive flag: C repeat exceeds B median by max(10%,.01m APE/.005m RPE); does not alter window class'
        gt=[]
        with rosbag.Bag(w['input_bag']) as bag:
            gt=[m.header.stamp.to_nsec() for _,m,_ in bag.read_messages(topics=['/aqualoc/colmap_gt'])]
        c['reference_span_s']=(max(gt)-min(gt))/1e9 if len(gt)>1 else 0.
        c['raw_image_span_s']=(int(w['end_stamp_ns'])-int(w['start_stamp_ns']))/1e9
        c['raw_reference_span_s_field_note']='legacy field contains roster image span; use explicit reference_span_s and raw_image_span_s'
        c['reference_time_span_over_raw_window']=(max(gt)-min(gt))/(int(w['end_stamp_ns'])-int(w['start_stamp_ns'])) if len(gt)>1 else 0.
        grid=PAPER/'common_support'/slug/'C-all_vs_B/common_grid_audit.csv'
        if grid.exists():
            gr=rows(grid);c['reference_valid_fraction_on_evaluation_grid']=sum(int(r['reference_valid']) for r in gr)/len(gr) if gr else 'Unknown'
        else:c['reference_valid_fraction_on_evaluation_grid']='Not evaluated.'
        c['reference_coverage_definition']='span/raw image span and interpolation-valid fraction on inherited evaluator grid; neither is independent GT'
        c['candidate_lifetime_observation_unit']='number of published observations per public ID; seconds span reported separately'
        c['case_artifact_root']=str(RUNTIME/'backend'/slug)
    assert before=={r['window_id']:(r['classification'],r['positive_level'],r['severe_regression']) for r in cases}
    table(PAPER/'case_registry.csv',cases)
    for name,kinds in [('positive_cases',['PRACTICAL_GAIN']),('neutral_cases',['SMALL_OR_UNCERTAIN']),('negative_cases',['PRACTICAL_LOSS']),('failure_cases',['FAIL','NOT_EVALUABLE'])]:
        data=[c for c in cases if c['classification'] in kinds]
        if data:table(PAPER/(name+'.csv'),data)
        else:
            with (PAPER/(name+'.csv')).open('w',newline='') as f:csv.writer(f,lineterminator='\n').writerow(list(dict.fromkeys(k for r in cases for k in r)))
    if resources:table(PAPER/'resource_usage.csv',resources)
    if lifecycle:table(PAPER/'candidate_lifecycle.csv',lifecycle)
    if supply:table(PAPER/'source_supply.csv',supply)
    seq=[]
    for batch in ['A','B']:
        for sequence in sorted({c['sequence'] for c in cases}):
            ss=[c for c in cases if c['sequence']==sequence and c['batch']==batch]
            row=dict(sequence=sequence,batch=batch,frozen_windows=len(ss))
            for k in ['PRACTICAL_GAIN','PRACTICAL_LOSS','SMALL_OR_UNCERTAIN','FAIL','NOT_EVALUABLE','NOT_ACTIVATED']:row[k]=sum(c['classification']==k for c in ss)
            row['ROBUST_PRACTICAL_GAIN']=sum(c['positive_level']=='ROBUST_PRACTICAL_GAIN' for c in ss);seq.append(row)
    table(PAPER/'sequence_distribution.csv',seq)
    receipt=PAPER/'case_supplement_receipt.json'
    save(receipt,dict(status='COMPLETE',classification_unchanged=True,
        script_sha256=sha(Path(__file__)),case_registry_sha256=sha(PAPER/'case_registry.csv'),
        backend_results_sha256=sha(PAPER/'backend_results.csv'),historical_audit_sha256=sha(PAPER/'broader_history_exposure_audit.csv')))
    print('CASE_SUPPLEMENT_COMPLETE: classifications preserved',flush=True)

if __name__=='__main__':main()
