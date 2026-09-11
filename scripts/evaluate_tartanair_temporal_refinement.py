#!/usr/bin/env python3
"""Same-observation B/P/T test measurement and the unchanged frozen backend gate."""
import argparse
from collections import Counter
import csv
import json
from pathlib import Path
import time
import numpy as np
import torch
from uw_frontend.temporal_refinement import PatchRefiner
from train_temporal_refinement import load_cache,consecutive_pairs,predict,file_sha256


def quantile(values,level):
    return float(np.quantile(values,level)) if len(values) else None


def write_csv(path,rows):
    fields=list(dict.fromkeys(k for row in rows for k in row))
    with path.open('x',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=fields,lineterminator='\n');writer.writeheader();writer.writerows(rows)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--split',type=Path,required=True);p.add_argument('--cache',type=Path,required=True)
    p.add_argument('--training',type=Path,required=True);p.add_argument('--artifacts',type=Path,required=True)
    p.add_argument('--paper',type=Path,required=True);p.add_argument('--device',default='cuda')
    args=p.parse_args();args.artifacts.mkdir(parents=True,exist_ok=False)
    torch.set_num_threads(2)
    data=load_cache(args.cache/'test.npz','test',args.split)
    pairs=consecutive_pairs(data);n=len(data['baseline']);runtime={};deltas={'B':np.zeros((n,2),np.float32)}
    summaries=json.loads((args.cache/'summary.json').read_text())
    training=[];validation_curves={};initial_states=[];batch_schedules=[]
    for arm in ['P','T']:
        checkpoint=args.training/(arm+'_best.pt')
        summary=json.loads((args.training/(arm+'_summary.json')).read_text())
        with (args.training/(arm+'_curve.csv')).open() as f:
            curve=list(csv.DictReader(f))
        if [int(r['step']) for r in curve]!=list(range(5001)) or summary['updates']!=5000:
            raise ValueError('not a complete single frozen 5000-update fit')
        saved=torch.load(checkpoint,map_location='cpu',weights_only=True)
        initial_states.append(summary['initial_state_sha256']);batch_schedules.append(summary['batch_schedule_sha256'])
        validation_curves[arm]=[dict(step=int(r['step']),validation_p95_px=float(r['validation_p95']),
                                     loss=float(r['loss']) if r['loss'] else None) for r in curve if r['validation_p95']]
        model=PatchRefiner().to(args.device);model.load_state_dict(saved['state_dict'])
        if args.device.startswith('cuda'):
            torch.cuda.synchronize();torch.cuda.reset_peak_memory_stats()
        started=time.perf_counter();d=predict(model,data,args.device)
        if args.device.startswith('cuda'):torch.cuda.synchronize()
        elapsed=time.perf_counter()-started
        if not np.isfinite(d).all() or np.any(abs(d)>2) or np.any(d[~data['patch_valid']]!=0):
            raise ValueError('invalid model correction')
        deltas[arm]=d
        runtime[arm]=dict(inference_wall_s=elapsed,inference_ms_per_frame=1000*elapsed/len(np.unique(data['frame'])),
                          peak_gpu_memory_mb=torch.cuda.max_memory_allocated()/1024**2 if args.device.startswith('cuda') else None,
                          boundary='cached causal patches + transfer + network; excludes image IO, KLT and patch extraction')
        training.append(dict(arm=arm,updates=5000,best_step=saved['step'],validation_p95_px=saved['validation_p95'],
                             train_frames=sum(s['frames'] for s in summaries if s['role']=='train'),
                             train_valid_labels=sum(s['valid_labels'] for s in summaries if s['role']=='train'),
                             train_valid_tracks=sum(s['valid_tracks'] for s in summaries if s['role']=='train'),
                             train_pairs=summary['valid_training_pairs'],parameters=sum(x.numel() for x in model.parameters()),
                             training_wall_s=summary['wall_s'],checkpoint=str(checkpoint),checkpoint_sha256=file_sha256(checkpoint),
                             curve=str(args.training/(arm+'_curve.csv')),**runtime[arm]))
        del model
    if len(set(initial_states))!=1 or len(set(batch_schedules))!=1:
        raise ValueError('P/T initialization or batch schedule differs')
    rows=[];errors={};temporal={}
    for arm,d in deltas.items():
        error=data['baseline']+d-data['truth'];errors[arm]=error
        temporal[arm]=np.linalg.norm(error[pairs[:,1]]-error[pairs[:,0]],axis=1)
        corrected=data['baseline']+d
        normalized=(corrected-np.array([320.,240.]))/320.
        previous=data['patches'].indices[:,1]
        velocity=normalized-normalized[previous]
        np.savez_compressed(args.artifacts/(arm+'_observations.npz'),id=data['id'],frame=data['frame'],
                            sequence=data['sequence'],q=data['q'],sigma=data['sigma'],pixel=corrected,
                            normalized=normalized,velocity_per_frame=velocity,delta=d)
    for sequence in np.unique(data['sequence']):
        seqmask=data['sequence']==sequence
        groups=[('sequence','all',seqmask)]
        for start in range(0,int(data['frame'][seqmask].max())+1,100):
            groups.append(('block',f'{start}:{start+100}',seqmask & (data['frame']>=start) & (data['frame']<start+100)))
        for lo,hi in [(0,5),(5,15),(15,30),(30,2**31)]:
            groups.append(('age',f'{lo}:{hi if hi<2**31 else "inf"}',seqmask & (data['age']>=lo) & (data['age']<hi)))
        for kind,group,query in groups:
            valid=query & data['label_valid'];pairmask=query[pairs[:,1]]
            for arm,d in deltas.items():
                epe=np.linalg.norm(errors[arm][valid],axis=1);norm=np.linalg.norm(d[query],axis=1)
                rows.append(dict(sequence=sequence,group_type=kind,group=group,arm=arm,observations=int(query.sum()),
                                 valid_labels=int(valid.sum()),valid_tracks=int(len(np.unique(data['id'][valid]))),
                                 invalid_labels=int((query & ~data['label_valid']).sum()),
                                 invalid_reasons=json.dumps(dict(Counter(data['label_reason'][query & ~data['label_valid']].tolist())),sort_keys=True),
                                 epe_median_px=quantile(epe,.5),epe_p90_px=quantile(epe,.9),epe_p95_px=quantile(epe,.95),
                                 over_1px_ratio=float(np.mean(epe>1)) if len(epe) else None,
                                 over_2px_ratio=float(np.mean(epe>2)) if len(epe) else None,
                                 temporal_pairs=int(pairmask.sum()),temporal_error_change_median_px=quantile(temporal[arm][pairmask],.5),
                                 temporal_error_change_p95_px=quantile(temporal[arm][pairmask],.95),
                                 zero_correction_ratio=float(np.mean(np.all(d[query]==0,axis=1))) if query.any() else None,
                                 correction_median_px=quantile(norm,.5),correction_p90_px=quantile(norm,.9),correction_p95_px=quantile(norm,.95),
                                 correction_axis_abs_max_px=float(np.max(abs(d[query]))) if query.any() else None,
                                 patch_unavailable=int((query & ~data['patch_valid']).sum()),
                                 baseline_error_outside_axis_2px=int(np.any(abs(errors['B'][valid])>2,axis=1).sum())))
    overall={r['arm']:r for r in rows if r['group_type']=='sequence'}
    if len(np.unique(data['sequence']))!=1:raise ValueError('v1 gate expects one fixed test sequence')
    b,pred,t=overall['B'],overall['P'],overall['T']
    support=b['valid_tracks']>=100
    block_checks=[]
    for r in [x for x in rows if x['group_type']=='block' and x['arm']=='B']:
        tr=next(x for x in rows if x['group_type']=='block' and x['group']==r['group'] and x['arm']=='T')
        eligible=r['valid_labels']>=100;support &= eligible
        block_checks.append(dict(block=r['group'],support=eligible,
                                 p95_no_regression=bool(eligible and tr['epe_p95_px']<=1.05*r['epe_p95_px']),
                                 over2_no_regression=bool(eligible and tr['over_2px_ratio']-r['over_2px_ratio']<=.01)))
    gates=dict(common_support=bool(support),t_vs_b_p95_20pct=bool(b['epe_p95_px'] and t['epe_p95_px']<=.8*b['epe_p95_px']),
               t_vs_b_over2_no_increase=bool(t['over_2px_ratio']<=b['over_2px_ratio']),
               t_vs_p_temporal_p95_5pct=bool(pred['temporal_error_change_p95_px'] and t['temporal_error_change_p95_px']<=.95*pred['temporal_error_change_p95_px']),
               t_vs_p_epe_p95_no_increase=bool(t['epe_p95_px']<=pred['epe_p95_px']),
               all_fixed_blocks=all(x['p95_no_regression'] and x['over2_no_regression'] for x in block_checks))
    passed=all(gates.values())
    decision=dict(status='MEASUREMENT_COMPLETE_BACKEND_PENDING' if passed else 'COMPLETE',
                  decision=None if passed else ('NO_TEMPORAL_REFINEMENT_GAIN' if support else 'EVALUATION_UNRESOLVED'),
                  dataset='TartanAir V1 generic 3D simulation; not underwater evidence',prior_mimir_decision='SUPERVISION_UNAVAILABLE',
                  training_updates={'P':5000,'T':5000},training_runs={'P':1,'T':1},new_backend_replays=0,
                  backend_gate_passed=passed,gates=gates,block_checks=block_checks,test_summary=overall,training=training,
                  cache_summary=summaries,cache_sha256=file_sha256(args.cache/'test.npz'),
                  initial_state_sha256=initial_states[0],batch_schedule_sha256=batch_schedules[0],
                  validation_curves=validation_curves,
                  p_vs_b_p95_relative_reduction=1-pred['epe_p95_px']/b['epe_p95_px'],
                  t_vs_b_p95_relative_reduction=1-t['epe_p95_px']/b['epe_p95_px'],
                  t_vs_p_temporal_p95_relative_reduction=1-t['temporal_error_change_p95_px']/pred['temporal_error_change_p95_px'],
                  next_step='冻结权重并完成原A02/H02 feature-bag适配与限定系统检查。' if passed else '停止并归档本固定版本；不第二次训练，不进入A02/H02，不据此否定所有学习精化。')
    write_csv(args.paper/'measurement_results.csv',rows);write_csv(args.paper/'training_summary.csv',training)
    (args.paper/'decision.json').write_text(json.dumps(decision,ensure_ascii=False,indent=2)+'\n')
    (args.artifacts/'evaluation.json').write_text(json.dumps(decision,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(dict(decision=decision['decision'],gates=gates,test_summary=overall),ensure_ascii=False,indent=2),flush=True)


if __name__=='__main__':
    main()
