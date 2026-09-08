#!/usr/bin/env python3
"""Aggregate the frozen v1 measurements; no inference, tuning, or replay."""
import argparse
from collections import Counter
import csv
import hashlib
import json
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
PAPER = ROOT/'papers/frontend_learned_klt_recovery_v1'


def read_csv(path):
    with path.open() as f:
        return list(csv.DictReader(f))


def write_csv(path, rows):
    fields = list(dict.fromkeys(k for r in rows for k in r))
    with path.open('x', newline='') as f:
        w = csv.DictWriter(f, fields, lineterminator='\n')
        w.writeheader()
        w.writerows(rows)


def total(rows, field):
    return sum(float(r.get(field) or 0) for r in rows)


def yes(value):
    return str(value) == 'True'


def stats(values):
    return dict(n=len(values),median=float(np.median(values)),p95=float(np.percentile(values,95)),
                min=float(min(values)),max=float(max(values))) if len(values) else dict(n=0)


def choose_samples(events):
    selected=[]
    for seq in ['A02','A08','H02']:
        for category in ['L_only','C_only','both_recovered','both_failed']:
            group=[r for r in events if r['stage']=='natural_paired' and r['sequence']==seq
                   and r['arm']=='L' and r['paired_category']==category]
            if not group:
                selected.append(dict(sequence=seq,category=category,event=None,visual_identity='Unknown',note='No event in this group'))
                continue
            def key(r):
                return hashlib.sha256(('{sequence}/{raw_index}/{track_id}'.format(**r)).encode()).hexdigest()
            r=min(group,key=key)
            selected.append(dict(sequence=seq,category=category,event=[int(r['raw_index']),int(r['track_id'])],
                                 sample_hash=key(r),visual_identity='Unknown'))
    return selected


def render_samples(selected, events, config):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    import rosbag
    from cv_bridge import CvBridge
    from uw_frontend.ros.export_vins_features import _image_msg_to_gray, _preprocess_gray
    destination=PAPER/'samples'
    destination.mkdir(exist_ok=True)
    for w in config['windows']:
        needed=set()
        for s in selected:
            if s['sequence']==w['sequence'] and s['event'] is not None:
                offset=s['event'][0]-w['raw_start']
                needed.update([offset-1,offset])
        images={}
        bridge=CvBridge()
        with rosbag.Bag(w['input_bag']) as bag:
            for index,(_,message,_) in enumerate(bag.read_messages(topics=[w['image_topic']])):
                if index in needed:
                    images[index]=_preprocess_gray(_image_msg_to_gray(bridge,message),'adaptive_clahe')
                if index>=max(needed,default=-1):
                    break
        assert images.keys()==needed
        fig,axes=plt.subplots(4,3,figsize=(10,12),constrained_layout=True)
        fig.suptitle(w['sequence']+' | fixed paired-B-failure samples | identity: Unknown\n'
                     'Previous point / C current / L current; circle accepted, x rejected; coordinates in raw pixels',fontsize=11)
        for row,s in enumerate(x for x in selected if x['sequence']==w['sequence']):
            if s['event'] is None:
                for ax in axes[row]:
                    ax.text(.1,.5,s['category']+': no event');ax.set_axis_off()
                continue
            raw,tid=s['event']
            pair={r['arm']:r for r in events if r['stage']=='natural_paired' and r['sequence']==w['sequence']
                  and int(r['raw_index'])==raw and int(r['track_id'])==tid}
            offset=raw-w['raw_start']
            previous=np.array([float(pair['C']['previous_x']),float(pair['C']['previous_y'])])
            for col,arm in enumerate(['previous','C','L']):
                ax=axes[row,col]
                e=pair['C'] if col==0 else pair[arm]
                point=previous if col==0 else np.array([float(e['current_x']),float(e['current_y'])]) if e['current_x'] else None
                center=previous if point is None else point
                im=images[offset-1 if col==0 else offset]
                h,width=im.shape
                cx=float(np.clip(center[0],48,width-49));cy=float(np.clip(center[1],48,h-49))
                ax.imshow(im,cmap='gray',vmin=0,vmax=255)
                ax.set_xlim(cx-48,cx+48);ax.set_ylim(cy+48,cy-48)
                if point is not None:
                    ax.plot(point[0],point[1],marker='+' if col==0 else 'o' if yes(e['accepted']) else 'x',
                            color='#F0E442' if col==0 else '#56B4E9' if arm=='C' else '#E69F00',
                            markersize=11,markerfacecolor='none',markeredgewidth=1.4)
                if col==0:
                    title='{} raw {} ID {}\nB failure: {}'.format(s['category'],raw,tid,e['original_failure'])
                else:
                    title='{}: {}\noutputs {} ({})'.format(arm,e['reason'],e['continuation_output_observations'],
                                                            'offline continuation' if yes(e['accepted']) else 'rejected')
                    if point is None:
                        ax.text(.02,.03,'No candidate coordinate',transform=ax.transAxes,color='white',fontsize=8,
                                bbox=dict(facecolor='black',alpha=.6))
                ax.set_title(title,fontsize=8);ax.tick_params(labelsize=7)
        path=destination/(w['sequence']+'_fixed_samples.png')
        if path.exists():
            raise FileExistsError(str(path))
        fig.savefig(path,dpi=120,facecolor='white')
        plt.close(fig)


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--samples',action='store_true')
    args=parser.parse_args()
    config=json.loads((PAPER/'input_manifest.json').read_text())
    runtime=Path(config['runtime'])
    manifest_hash=hashlib.sha256((PAPER/'input_manifest.json').read_bytes()).hexdigest()
    events,results,frames,receipts=[],[],[],[]
    for w in config['windows']:
        seq=w['sequence'];directory=runtime/seq
        receipt=json.loads((directory/'completion.json').read_text())
        assert receipt['status']=='COMPLETE' and receipt['raw_frames']==200
        assert receipt['protocol_manifest_sha256']==manifest_hash
        receipts.append(receipt)
        ee=read_csv(directory/'recovery_events.csv')
        events.extend(ee)
        results.extend(read_csv(directory/'frontend_results.csv'))
        frames.extend(read_csv(directory/(seq+'_natural_frames.csv')))
        # C/L comparisons must contain the exact same B failed event inputs.
        for stage in ['controlled','natural_paired']:
            paired={arm:{(r['raw_index'],r['case'],r['track_id']):r for r in ee if r['stage']==stage and r['arm']==arm} for arm in ['C','L']}
            assert paired['C'].keys()==paired['L'].keys()
            for key,c in paired['C'].items():
                l=paired['L'][key]
                assert all(c[k]==l[k] for k in ['previous_x','previous_y','previous_age','original_failure','stamp_ns'])
        # Independently recount the actual published lifespan of every accepted stream recovery.
        outputs=read_csv(directory/(seq+'_actual_output_tracks.csv'))
        positions={arm:{} for arm in ['B','C','L']}
        for r in outputs:
            assert np.isfinite([float(r['x']),float(r['y'])]).all()
            positions[r['arm']].setdefault(int(r['track_id']),[]).append(int(r['raw_index']))
        for arm in positions:
            for indices in positions[arm].values():
                assert all(b-a==2 for a,b in zip(indices,indices[1:])), 'Public ID gap'
        for r in ee:
            if r['stage']=='natural_stream':
                indices=positions[r['arm']][int(r['track_id'])] if int(r['track_id']) in positions[r['arm']] else []
                count=sum(i>=int(r['raw_index']) for i in indices)
                assert count==int(r['continuation_output_observations'])
    controlled=[r for r in results if r['stage']=='controlled']
    aggregates={}
    for seq in ['ALL','A02','A08','H02']:
        aggregates[seq]={}
        for arm in ['B','C','L']:
            rr=[r for r in controlled if r['arm']==arm and (seq=='ALL' or r['sequence']==seq)]
            aggregates[seq][arm]={k:int(total(rr,k)) for k in ['input_points','visible_input_points','invisible_input_points','accepted','correct','wrong_accepted','invisible_accepted']}
    c,l=aggregates['ALL']['C'],aggregates['ALL']['L']
    controlled_errors={}
    for arm in ['C','L']:
        accepted=[r for r in events if r['stage']=='controlled' and r['arm']==arm and yes(r['accepted'])]
        assert len(accepted)==aggregates['ALL'][arm]['accepted']
        assert sum(yes(r['correct_recovery']) for r in accepted)==aggregates['ALL'][arm]['correct']
        controlled_errors[arm]=stats([float(r['oracle_error_px']) for r in accepted])
    n=l['input_points'];nv=l['visible_input_points'];ni=l['invisible_input_points']
    g=config['frontend_gate']
    observed=dict(visible_B_failures=nv,L_correct_precision=l['correct']/max(1,l['accepted']),
        L_wrong_accept_rate=l['wrong_accepted']/max(1,n),
        L_wrong_accept_rate_increase_vs_C=(l['wrong_accepted']-c['wrong_accepted'])/max(1,n),
        L_invisible_accept_rate=l['invisible_accepted']/max(1,ni),
        correct_increment_count=l['correct']-c['correct'],
        required_correct_increment=max(g['min_correct_increment_count'],nv*g['min_correct_increment_rate']),
        sequences_with_correct_increment=sum(aggregates[s]['L']['correct']>aggregates[s]['C']['correct'] for s in ['A02','A08','H02']))
    stream=[r for r in events if r['stage']=='natural_stream' and r['arm']=='L']
    long=[r for r in stream if int(r['continuation_output_observations'])>=4]
    observed.update(natural_L_stream_chains_ge4_outputs=len(long),
        natural_sequences_with_L_chains_ge4_outputs=len(set(r['sequence'] for r in long)),
        paired_L_only_continuation_chains_ge4_outputs=sum(r['stage']=='natural_paired' and r['arm']=='L'
            and r['paired_category']=='L_only' and int(r['continuation_output_observations'])>=4 for r in events))
    checks=dict(sample_size=nv>=g['min_visible_B_failures'],
        precision=observed['L_correct_precision']>=g['min_L_correct_precision'],
        wrong_accept=observed['L_wrong_accept_rate']<=g['max_L_wrong_accept_rate'],
        wrong_accept_increase=observed['L_wrong_accept_rate_increase_vs_C']<=g['max_L_wrong_accept_rate_increase_vs_C'],
        invisible_accept=observed['L_invisible_accept_rate']<=g['max_L_invisible_accept_rate'],
        correct_increment=observed['correct_increment_count']>=observed['required_correct_increment'],
        increment_sequences=observed['sequences_with_correct_increment']>=g['min_sequences_with_correct_increment'],
        actual_long_chains=len(long)>=g['min_natural_L_stream_chains_ge4_outputs'],
        actual_chain_sequences=observed['natural_sequences_with_L_chains_ge4_outputs']>=g['min_natural_sequences_with_L_chains_ge4_outputs'],
        paired_unique_long_chains=observed['paired_L_only_continuation_chains_ge4_outputs']>=g['min_paired_L_only_continuation_chains_ge4_outputs'],
        input_identity_time_structure=True)
    correctness=all(checks[k] for k in ['sample_size','precision','wrong_accept','wrong_accept_increase','invisible_accept'])
    increment=checks['correct_increment'] and checks['increment_sequences']
    natural_ok=all(checks[k] for k in ['actual_long_chains','actual_chain_sequences','paired_unique_long_chains'])
    passed=all(checks.values())
    decision=None if passed else 'RECOVERY_NOT_ESTABLISHED' if not correctness else 'NO_LEARNED_INCREMENT' if not increment else 'RECOVERY_NOT_ESTABLISHED'
    reason='FRONTEND_GATE_PASSED' if passed else 'CONTROLLED_CORRECTNESS_GATE_FAILED' if not correctness else 'NO_PRACTICAL_INCREMENT_OVER_C' if not increment else 'REAL_RECOVERY_NOT_ESTABLISHED'
    timing={}
    for seq in ['A02','A08','H02']:
        timing[seq]={}
        b_failures={r['raw_index']:int(r['failed']) for r in frames if r['sequence']==seq and r['stage']=='evolving_stream' and r['arm']=='B'}
        for arm in ['B','C','L']:
            ff=[r for r in frames if r['sequence']==seq and r['stage']=='evolving_stream' and r['arm']==arm]
            # If B had no failures, the first shared inference can occur inside
            # actual L.process itself. Remove that cost before adding it once.
            kernel=[float(r['wall_s'])-(float(r['shared_xfeat_s']) if arm=='L' and b_failures[r['raw_index']]==0 else 0.) for r in ff]
            assert min(kernel)>=-1e-6
            timing[seq][arm]=dict(kernel_ms=stats([1000*x for x in kernel]),
                shared_matcher_ms=stats([1000*float(r['shared_xfeat_s']) for r in ff]),
                kernel_plus_shared_matcher_ms=stats([1000*(x+float(r['shared_xfeat_s'])) for x,r in zip(kernel,ff)]),
                kernel_plus_shared_matcher_mean_ms=float(np.mean([1000*(x+float(r['shared_xfeat_s'])) for x,r in zip(kernel,ff)])),
                births=int(total(ff,'births')),failed_events=int(total(ff,'failed')),recovered_events=int(total(ff,'accepted')))
    selected=choose_samples(events)
    if args.samples:
        render_samples(selected,events,config)
    payload=dict(decision=decision,reason=reason,frontend_gate_passed=passed,backend_required=passed,
        failed_gate_reasons=([] if correctness else ['CONTROLLED_CORRECTNESS_GATE_FAILED'])
            +([] if increment else ['NO_PRACTICAL_INCREMENT_OVER_C'])
            +([] if natural_ok else ['REAL_RECOVERY_NOT_ESTABLISHED']),
        new_backend_replays=0,reused_backend_replays=0,backend_status='Not evaluated.',
        freeze_commit='915716d5e4d56bc4663125db061c5acc35ddadf9',
        completed_controlled_pairs=48,completed_natural_frames=600,checks=checks,observed=observed,
        controlled_totals=aggregates,controlled_accepted_error_px=controlled_errors,
        natural_results=[r for r in results if r['stage']!='controlled'],timing=timing,
        natural_paired_rejection_reasons={arm:dict(Counter(r['reason'] for r in events if r['stage']=='natural_paired' and r['arm']==arm)) for arm in ['C','L']},
        selected_samples=selected,run_receipts=receipts,
        evidence_limits=['Controlled warps are synthetic measurement evidence; all windows are development data.',
          'Natural physical identity and per-point correctness are Unknown without independent truth.',
          'Recovery events and overlapping remaining lifetimes are not independent samples or unique tracks.',
          'Paired endpoint continuation is offline ordinary LK; actual evolving stream lifetimes are separate.',
          'Timing is sequential diagnostic wall time on shared hardware; no real-time guarantee.'])
    write_csv(PAPER/'frontend_results.csv',results)
    write_csv(PAPER/'recovery_events.csv',events)
    with (PAPER/'decision.json').open('x') as f:
        json.dump(payload,f,indent=2);f.write('\n')
    print(json.dumps(dict(decision=decision,reason=reason,checks=checks,observed=observed,controlled=aggregates),indent=2))


if __name__=='__main__':
    main()
