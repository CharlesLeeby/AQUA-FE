#!/usr/bin/env python3
"""Summarize immutable source streams; no candidate or execution changes."""
from collections import Counter
import csv
import json
import numpy as np
from run_additive_budget_v1 import PAPER, RUNTIME, sha
from analyze_additive_budget_v1 import table, verify_artifacts


def main():
    weights, sources, gates, windows = [], [], [], []
    lock = json.loads((PAPER/'source_and_backend_lock.json').read_text())
    for w in lock['windows']:
        slug = w['run_slug']
        root = RUNTIME/'frontend'/slug
        if not (root/'receipt.json').exists():
            continue
        receipt = json.loads((root/'receipt.json').read_text())
        verify_artifacts(receipt)
        windows.append(dict(run_slug=slug, raw_frames=receipt['raw_frames'],
            output_messages=receipt['arms']['B']['feature_messages'],
            image_height=receipt['image_shape'][0], image_width=receipt['image_shape'][1],
            generation_wall_s=receipt['generation_wall_s'],
            generation_raw_fps=receipt['raw_frames']/receipt['generation_wall_s'],
            total_with_merges_wall_s=receipt['total_wall_s'],
            peak_process_rss_mib=receipt['peak_rss_kib']/1024,
            **receipt['timings']))
        for source in ['xfeat', 'classical_gftt']:
            path = root/(source+'_source.jsonl')
            q, raw, rejected, reasons = [], [], Counter(), Counter()
            eligible_frames = pool_frames = pool_generation_frames = 0
            previous_limit = 0
            for line in path.open():
                row = json.loads(line)
                rejected.update(row['rejected'])
                reasons[str(row['geometry_reason'])] += 1
                eligible_frames += bool(row['observations'])
                q.extend(o['quality'] for o in row['observations'])
                raw.extend(o['raw_quality'] for o in row['observations'])
                current_limit = row['counters'].get('generator_pool_limit', 0)
                pool_generation_frames += current_limit > previous_limit
                previous_limit = current_limit
            counters = receipt['source_counters'][source]
            sources.append(dict(run_slug=slug, source=source, source_sha256=sha(path),
                eligible_frames=eligible_frames,
                output_intervals_with_pool_limit_increment=pool_generation_frames,
                **counters))
            weights.append(dict(run_slug=slug, source=source, observations=len(q),
                backend_q_min=min(q) if q else 'Unknown',
                backend_q_median=float(np.median(q)) if q else 'Unknown',
                backend_q_mean=float(np.mean(q)) if q else 'Unknown',
                backend_q_max=max(q) if q else 'Unknown',
                raw_quality_mean=float(np.mean(raw)) if raw else 'Unknown',
                source_sha256=sha(path)))
            for reason, count in rejected.items():
                gates.append(dict(run_slug=slug, source=source, scope='eligibility_observations', reason=reason, count=count))
            for reason, count in reasons.items():
                gates.append(dict(run_slug=slug, source=source, scope='geometry_frame_status', reason=reason, count=count))
            for reason, count in counters.items():
                if reason.endswith('_fail') or reason.startswith('seed_') or reason.startswith('generator_'):
                    gates.append(dict(run_slug=slug, source=source, scope='generation_or_tracking_cumulative', reason=reason, count=count))
        events = Counter()
        for row in csv.DictReader((root/'candidate_lifecycle.csv').open()):
            events[(row['arm'], row['event'], row['reason'])] += 1
        for (arm, event, reason), count in events.items():
            gates.append(dict(run_slug=slug, source=arm, scope='publication_'+event, reason=reason, count=count))
    table(PAPER/'source_weight_audit.csv', weights)
    table(PAPER/'source_supply.csv', sources)
    table(PAPER/'rejection_summary.csv', gates)
    table(PAPER/'frontend_window_resources.csv', windows)
    print('SOURCE_SUMMARIES', len(windows), 'windows')


if __name__ == '__main__':
    main()
