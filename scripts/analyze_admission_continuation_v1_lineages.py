#!/usr/bin/env python3
"""Compact per-lineage evidence; distinguish observed publication from VINS use."""
from collections import defaultdict
import json

import run_frontend_admission_continuation_v1 as run
import audit_frontend_protected_prefill_slot_v1 as common


def main():
    run.configure()
    windows = run.base.read_csv(run.PAPER / 'development_windows.csv')
    arms = run.base.read_csv(run.PAPER / 'arms.csv')
    rows = []
    for window in windows:
        baseline = common.load_frames(run.run_dir(window, arms[0]) / 'features.bag')
        for arm in arms[1:]:
            directory = run.run_dir(window, arm)
            if not (directory / 'frontend_receipt.json').exists():
                raise RuntimeError('Complete all frontend cells before the lineage summary')
            events = run.base.read_csv(directory / 'lifecycle_events.csv')
            output = common.load_frames(directory / 'features.bag')
            if len(baseline) != len(output):
                raise RuntimeError('Different baseline/output frame counts')
            capacity_frames = {int(r['selected_feature_index']) for r in events
                               if r['reason'] == 'no_newborn_or_vacant_capacity'}
            seen_classical = set()
            capacity_evidence = {}
            for frame, (b, o) in enumerate(zip(baseline, output)):
                base_ids = {int(t) for t in b['ids']}
                carried = {int(t) for t, s in zip(b['ids'], b['sources']) if int(s) != 2}
                if frame in capacity_frames:
                    hidden_carried = carried - seen_classical
                    capacity_evidence[frame] = dict(
                        terminal_mirror_carried_count=len(carried),
                        terminal_mirror_carried_never_public_count=len(hidden_carried),
                        terminal_mirror_carried_never_public_ids_json=json.dumps(sorted(hidden_carried)),
                        terminal_capacity_under_frozen_mirror_rule=350-len(carried),
                        terminal_capacity_if_only_previously_public_classical_protected=350-len(base_ids & seen_classical),
                        capacity_boundary='Alternative protection is a hypothetical policy, not tested and not no-harm; it would withhold more baseline observations.')
                seen_classical.update(int(t) for t, learned in zip(o['ids'], o['learned']) if not learned)
            groups = defaultdict(list)
            for event in events:
                groups[(event['raw_id'], event['public_id'])].append(event)
            for (raw_id, public_id), history in groups.items():
                published = [r for r in history if r['event'] in ('admit', 'continue')]
                frames = [int(r['selected_feature_index']) for r in published]
                if not frames:
                    raise RuntimeError('Termination without any actual public admission')
                last = history[-1]
                streak = longest = 1
                for left, right in zip(frames, frames[1:]):
                    streak = streak + 1 if right == left + 1 else 1
                    longest = max(longest, streak)
                terminal = last['event'] == 'terminate'
                rows.append(dict(
                    row_type='learned_lineage', window_id=window['window_id'], run_slug=window['run_slug'], arm=arm['arm'],
                    raw_id=raw_id, public_id=public_id, first_published_output_frame=min(frames),
                    last_published_output_frame=max(frames), published_observations=len(frames),
                    longest_consecutive_publication=longest, publication_frames_json=json.dumps(frames),
                    internal_birth_frame='Unknown', internal_death_frame='Unknown',
                    raw_age_at_first_publication=published[0]['raw_age'],
                    raw_age_at_last_publication=published[-1]['raw_age'],
                    last_recorded_stage_frame=last['selected_feature_index'],
                    raw_age_at_last_record=last['raw_age'], source_at_last_record=last['source'],
                    termination_reason=last['reason'] if terminal else 'window_end_while_publicly_active',
                    last_fb=last['fb'], last_ncc=last['ncc'], last_quality=last['quality'],
                    backend_received_observations='Unknown', backend_residual_observations='Unknown',
                    at_least_four_published_observations=len(frames) >= 4,
                    four_observation_note='Count-only diagnostic; not proof of triangulation or residual use.',
                    events_path=str(directory / 'lifecycle_events.csv'),
                    events_sha256=run.base.sha256(directory / 'lifecycle_events.csv'),
                    **capacity_evidence.get(int(last['selected_feature_index']), {}) if last['reason']=='no_newborn_or_vacant_capacity' else {}))
            if window['run_slug'] == 'a02_0_900' and arm['arm'] == 'continuation_xfeat':
                old_frames = [f for f, row in enumerate(baseline) if 377 in row['ids']]
                new_frames = [f for f, row in enumerate(output) if 377 in row['ids']]
                missing = sorted(set(old_frames) - set(new_frames))
                rows.append(dict(row_type='historical_donor_377_probe', window_id=window['window_id'],
                                 run_slug=window['run_slug'], arm=arm['arm'], public_id=377,
                                 baseline_observations=len(old_frames), current_observations=len(new_frames),
                                 missing_observations=len(missing), missing_frames_json=json.dumps(missing),
                                 same_id_reappearance_after_first_missing=next((f for f in new_frames if missing and f>missing[0]), 'Not applicable'),
                                 future_baseline_lifetime_used_online=False))
    target = run.PAPER / 'lineage_diagnostic.csv'
    if target.exists():
        raise RuntimeError('Refusing to overwrite completed lineage analysis')
    common.write_csv(target, rows)
    learned = [r for r in rows if r['row_type']=='learned_lineage']
    print('LINEAGES', len(learned), 'PUBLISHED_OBSERVATIONS', sum(r['published_observations'] for r in learned))


if __name__ == '__main__':
    main()
