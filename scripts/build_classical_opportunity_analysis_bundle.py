#!/usr/bin/env python3
"""Descriptive final evidence bundle; never launches or changes an experiment."""
import csv
import hashlib
import json
import math
from pathlib import Path
import statistics
from collections import Counter

ROOT = Path(__file__).resolve().parents[1]
PAPER = ROOT / 'papers/frontend_classical_opportunity_expansion_v1'
OUT = PAPER / 'analysis-output'
KINDS = ['PRACTICAL_GAIN', 'PRACTICAL_LOSS', 'SMALL_OR_UNCERTAIN', 'FAIL', 'NOT_EVALUABLE']
COLORS = {'PRACTICAL_GAIN': '#0072B2', 'PRACTICAL_LOSS': '#D55E00',
          'SMALL_OR_UNCERTAIN': '#666666', 'FAIL': '#CC79A7', 'NOT_EVALUABLE': '#999999'}
MARKERS = {'PRACTICAL_GAIN': '^', 'PRACTICAL_LOSS': 'v',
           'SMALL_OR_UNCERTAIN': 's', 'FAIL': 'x', 'NOT_EVALUABLE': 'x'}


def read(name):
    with (PAPER / name).open() as f:
        return list(csv.DictReader(f))


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def number(row, key):
    try:
        value = float(row[key])
        return value if math.isfinite(value) else None
    except (KeyError, TypeError, ValueError):
        return None


def fmt(value):
    return 'Not evaluated.' if value is None else '{:.6g}'.format(value)


def triple(row, prefix):
    return ' / '.join(fmt(number(row, prefix + '_' + k)) for k in ['min', 'median', 'max'])


def table(path, rows):
    fields = list(dict.fromkeys(k for row in rows for k in row))
    with path.open('w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=fields, lineterminator='\n')
        writer.writeheader()
        writer.writerows(rows)


def main():
    decision = json.loads((PAPER / 'decision.json').read_text())
    assert decision['status'] == 'COMPLETE', 'Do not generate final analysis from a partial matrix'
    assert (PAPER / 'case_supplement_receipt.json').is_file(), 'Complete case timing/provenance first'
    assert not OUT.exists(), 'Preserve existing final analysis; use an explicit version for any correction'
    cases = [r for r in read('case_registry.csv') if r['batch'] in decision['activated_batches']]
    back = [r for r in read('backend_results.csv') if r['status'] != 'Not evaluated.']
    old = read('old_positive_comparison_reference.csv')
    assert len(cases) == decision['physical_windows_planned']
    assert len(back) == decision['backend_attempted']
    assert all(r['classification'] in KINDS for r in cases)
    assert Counter(r['classification'] for r in cases) == Counter(decision['classification_counts'])
    for c in cases:
        rr = [r for r in back if r['window_id'] == c['window_id']]
        assert len(rr) == int(c['backend_attempted'])
        if c['classification'] in KINDS[:3]:
            assert len(rr) == 6
            assert all(r['runability'] == 'PASS' and r['received_per_id_exact'] == 'True' for r in rr)
            for arm in ['B', 'C-all']:
                for metric in ['APE', 'RPE']:
                    vals = [float(r[metric]) for r in rr if r['arm'] == arm]
                    assert len(vals) == 3
                    for stat, value in [('min', min(vals)), ('median', statistics.median(vals)), ('max', max(vals))]:
                        assert math.isclose(value, float(c[arm + '_' + metric + '_' + stat]), rel_tol=1e-12, abs_tol=1e-12)
    OUT.mkdir()
    figures = OUT / 'figures'
    figures.mkdir()
    inputs = ['decision.json', 'case_registry.csv', 'backend_results.csv', 'window_outcomes.csv',
              'old_positive_comparison_reference.csv', 'case_supplement_receipt.json',
              'preregistration.md', 'source_and_backend_lock.json', 'backend_execution_lock_v2.json',
              'evaluation_lock.json', 'broader_history_exposure_audit.csv']
    provenance = {'analysis_unit': 'physical window; technical repeats describe solver variation only',
                  'primary_comparison': 'frozen C-all versus fresh complete KLT B, own six-trajectory support',
                  'primary_metric': 'fixed-scale proper SE(3) APE RMSE, lower is better',
                  'guardrail': 'strict aligned-global positional-delta translational RPE RMSE at 1 s',
                  'reference': 'COLMAP/proxy; not independent GT',
                  'script_sha256': digest(__file__),
                  'inputs': {name: digest(PAPER / name) for name in inputs},
                  'classification_changes': False}
    (OUT / 'provenance.json').write_text(json.dumps(provenance, indent=2) + '\n')
    numeric = []
    for c in cases:
        r = {k: c[k] for k in ['window_id', 'sequence', 'batch', 'classification', 'positive_level', 'severe_regression']}
        for metric in ['APE', 'RPE']:
            for arm in ['B', 'C-all']:
                rr = [number(b, metric) for b in back if b['window_id'] == c['window_id'] and b['arm'] == arm]
                rr = [v for v in rr if v is not None]
                r[arm + '_' + metric + '_n_technical'] = len(rr)
                r[arm + '_' + metric + '_mean'] = statistics.mean(rr) if rr else 'Not evaluated.'
                r[arm + '_' + metric + '_sample_sd'] = statistics.stdev(rr) if len(rr) > 1 else 'Not evaluated.'
                for stat in ['min', 'median', 'max']:
                    r[arm + '_' + metric + '_' + stat] = c.get(arm + '_' + metric + '_' + stat, 'Not evaluated.')
            for suffix in ['delta_m', 'delta_pct', 'repeat_range_threshold']:
                r[metric + '_' + suffix] = c.get(metric + '_' + suffix, 'Not evaluated.')
        numeric.append(r)
    table(OUT / 'exact_numeric_summary.csv', numeric)

    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib.lines import Line2D
    plt.rcParams.update({'font.family': 'DejaVu Sans', 'font.size': 9, 'svg.fonttype': 'none'})
    fig, axes = plt.subplots(2, 1, figsize=(max(11, len(cases) * .65), 8), sharex=True, constrained_layout=True)
    for ax, metric in zip(axes, ['APE', 'RPE']):
        for i, c in enumerate(cases):
            for arm, offset, color, marker in [('B', -.14, '#444444', 'o'),
                                               ('C-all', .14, COLORS[c['classification']], MARKERS[c['classification']])]:
                low, med, high = [number(c, arm + '_' + metric + '_' + k) for k in ['min', 'median', 'max']]
                if med is None:
                    continue
                assert low > 0, 'Log axis cannot represent a zero RMSE; review plotting only'
                ax.errorbar(i + offset, med, yerr=[[med-low], [high-med]], fmt=marker,
                            color=color, capsize=3, markersize=5, linewidth=1.2)
        ax.set_yscale('log')
        ax.set_ylabel(metric + ' RMSE (m; log scale)')
        ax.grid(axis='y', alpha=.25)
        ax.set_xlim(-.65, len(cases)-.35)
    labels = [c['sequence'] + '/' + c['batch'] + ('*' if c['severe_regression'] == 'True' else '') +
              ('\n' + c['classification'] if c['classification'] in KINDS[3:] else '') for c in cases]
    axes[1].set_xticks(range(len(cases)))
    axes[1].set_xticklabels(labels, rotation=45, ha='right')
    axes[0].set_title('Frozen C-all vs complete KLT: per-window median and full technical-repeat range')
    legend = [Line2D([0], [0], marker='o', color='#444444', label='B: complete KLT', linestyle='')]
    for k in KINDS[:3]:
        legend.append(Line2D([0], [0], marker=MARKERS[k], color=COLORS[k], label='C: ' + k, linestyle=''))
    axes[0].legend(handles=legend, ncol=2, fontsize=8)
    axes[1].set_xlabel('Physical window (sequence / batch); * severe regression. Missing metrics are retained without plotted accuracy.')
    for ext in ['png', 'svg']:
        fig.savefig(figures / ('figure-01-repeat-ranges.' + ext), dpi=220, facecolor='white')
    plt.close(fig)

    fig, axes = plt.subplots(1, 2, figsize=(12, 5.5), constrained_layout=True)
    for c in cases:
        delta = number(c, 'APE_delta_m')
        dose = number(c, 'candidate_published_count')
        life = number(c, 'candidate_lifetime_median')
        cb = number(c, 'C-all_first_pose_delay_from_reference_start_s_median')
        bb = number(c, 'B_first_pose_delay_from_reference_start_s_median')
        points = [(dose, delta), (life, cb-bb if cb is not None and bb is not None else None)]
        for panel, (ax, (x, y)) in enumerate(zip(axes, points)):
            if x is None or y is None:
                continue
            ax.scatter(x, y, color=COLORS[c['classification']], marker=MARKERS[c['classification']], s=42)
            # Separate coincident descriptors without jittering measured values.
            if panel == 1 and c['sequence'] in ['H04', 'H05']:
                continue  # H01/H04/H05 have exactly the same displayed coordinates.
            offsets = {'A05': (-35, 35), 'A10': (-35, -30),
                       'H01': (18, 23), 'H03': (32, -2), 'A07': (20, -27)} if panel == 1 else {'H04': (-40, 24), 'H05': (14, 17), 'A10': (25, -22)}
            offset = offsets.get(c['sequence'], (4, 4))
            label = 'H01/H04/H05 (A)' if panel == 1 and c['sequence'] == 'H01' else c['sequence'] + '/' + c['batch']
            ax.annotate(label, (x, y), xytext=offset,
                        textcoords='offset points', fontsize=7,
                        arrowprops={'arrowstyle': '-', 'color': '#999999', 'lw': .5} if c['sequence'] in offsets else None)
    for c in old:
        label = 'old A02' if c['window_id'].startswith('a02') else 'old Bus'
        points = [(float(c['total_published']), float(c['C-all_APE_median']) - float(c['B_APE_median'])),
                  (float(c['lifetime_median']), float(c['C-all_first_pose_delay_from_reference_start_s_median']) - float(c['B_first_pose_delay_from_reference_start_s_median']))]
        for panel, (ax, (x, y)) in enumerate(zip(axes, points)):
            ax.scatter(x, y, facecolors='none', edgecolors='#000000', marker='D', s=55)
            ax.annotate(label, (x, y), xytext=(-32, -17) if panel == 1 and label == 'old Bus' else (4, -11), textcoords='offset points', fontsize=8)
    for ax in axes:
        ax.axhline(0, color='#777777', linewidth=.8, linestyle='--')
        ax.grid(alpha=.2)
        ax.margins(.18)
    axes[0].set_xlabel('C candidate published observations (not independent constraints)')
    axes[0].set_ylabel('Median APE delta: C - B (m; symlog)')
    axes[0].set_yscale('symlog', linthresh=.01)
    axes[0].set_title('Dose and accuracy association')
    axes[0].legend(handles=[Line2D([0], [0], marker=MARKERS[k], color=COLORS[k],
                          label=k, linestyle='') for k in KINDS[:3]], loc='upper left', fontsize=7)
    axes[1].set_xlabel('Median public-ID lifetime (observations)')
    axes[1].set_ylabel('Median first-pose delay delta: C - B (s)')
    axes[1].set_title('Lifetime and initialization timing association')
    fig.suptitle('Case descriptors; old outcome-known controls are hollow diamonds. No causal fit.')
    for ext in ['png', 'svg']:
        fig.savefig(figures / ('figure-02-case-context.' + ext), dpi=220, facecolor='white')
    plt.close(fig)

    countline = ', '.join(k + '=' + str(decision['classification_counts'].get(k, 0)) for k in KINDS)
    md = ['# Classical opportunity expansion — strict descriptive analysis', '',
          'Status: COMPLETE. Question: does frozen C-all improve fresh complete KLT outside the six development windows under the preregistered fixed-backend contract?', '',
          'Confirmed fact. Executed denominator: {} physical windows; {} technical replay attempts. {}.'.format(len(cases), len(back), countline),
          'ROBUST_PRACTICAL_GAIN={}; severe regression={}; practical-positive sequences={}.'.format(decision['robust_practical_gain_count'], decision['severe_regression_count'], decision['practical_positive_sequences']),
          'Registered decision: **{}**. Expansion status: **{}**.'.format(decision['scientific_decision'], decision['expansion_status']), '',
          'The unit is a physical window, not a solver repeat. Fixed start/stride, shared sensor families, proxy reference, broader project exposure and the conditional second stage limit transfer claims. No population natural-positive-rate estimate is made.', '',
          '| Window | Class / tier | B APE min/median/max (m) | C APE min/median/max (m) | B RPE min/median/max (m) | C RPE min/median/max (m) | APE delta (m) | RPE delta (m) |',
          '|---|---|---|---|---|---|---|---|']
    for c in cases:
        md.append('| {} | {} / {} | {} | {} | {} | {} | {} | {} |'.format(c['window_id'], c['classification'], c['positive_level'], triple(c, 'B_APE'), triple(c, 'C-all_APE'), triple(c, 'B_RPE'), triple(c, 'C-all_RPE'), fmt(number(c, 'APE_delta_m')), fmt(number(c, 'RPE_delta_m'))))
    md += ['', '![Per-window complete repeat ranges](figures/figure-01-repeat-ranges.png)', '',
           'Figure 1 preserves the active denominator and displays min/median/max of three technical repeats per arm. Classification remains the frozen rule, including its repeat-range and RPE conditions; visual direction alone is insufficient. Log axes display different error magnitudes without normalizing away failures. No confidence intervals are implied.', '',
           '![Case context](figures/figure-02-case-context.png)', '',
           'Figure 2 places candidate dose and lifetime beside set-level accuracy and initialization differences. Old A02/Bus use their own six-trajectory supports and remain development controls. These descriptors can identify mechanism cases, but do not establish candidate utility or an initialization-mediated causal explanation.', '',
           '## Claim candidates', '',
           '- Claim: the registered fixed-C decision within this roster is ' + decision['scientific_decision'] + '.',
           '  - Source evidence: decision.json, case_registry.csv, backend_results.csv and own-support common_support summaries, pinned in provenance.json.',
           '  - Allowed wording: report exact counts and limits within this prospective comparison outside six development windows.',
           '  - Forbidden stronger wording: population efficacy, independent GT, globally unseen data, C-all as final AQUA-FE innovation.',
           '  - Uncertainty: broader generalization, causal mechanisms and per-feature utility are Unknown.',
           '  - Next check: observation-utility / risk mechanism analysis using retained cases; no automatic C-all tuning.',
           '  - Decision: keep within preregistered scope.', '',
           '- Claim: retained cases provide set-level examples for mechanism research.',
           '  - Source evidence: positive_cases.csv, neutral_cases.csv, negative_cases.csv, failure_cases.csv and candidate_lifecycle.csv.',
           '  - Allowed wording: whole candidate-set outcome conditional on this cold-start input and fixed evaluation contract.',
           '  - Forbidden stronger wording: each candidate in a positive/negative window is useful/harmful.',
           '  - Uncertainty: candidate-specific causal labels are Not evaluated.',
           '  - Next check: separate mechanism research; preserve all failures and old conclusions.',
           '  - Decision: keep as a case registry, not a feature-label dataset.', '']
    (OUT / 'analysis-report.md').write_text('\n'.join(md))
    stats = ['# Statistical appendix', '',
             '- Primary contrast: C-all minus B in fixed-scale proper SE(3) APE RMSE; strict 1 s translational RPE is the frozen guardrail. Lower is better.',
             '- Physical-window count: {}; technical attempts: {}; repeats intended per arm per executable window: 3.'.format(len(cases), len(back)),
             '- Full case classes: ' + countline + '.',
             '- Descriptives: exact_numeric_summary.csv gives all valid per-arm min/median/max and supplementary mean/sample SD. Mean/SD describe technical dispersion and do not replace the median decision.',
             '- Effect sizes: raw median C-B difference (metres) and percentage relative to B per valid window. No scale-aligned primary score, pooled heterogeneous error score or standardized population effect is substituted.',
             '- Intervals: full observed min–max technical ranges; not 95% confidence intervals. Population CI is Not evaluated. because deterministic selection, technical repeats and adaptive batch inclusion do not justify independent sampling assumptions.',
             '- Significance tests: Not evaluated. No t-test, rank test or solver-repeat bootstrap is used to manufacture sample size. Normality testing on three technical repeats is not informative for population inference.',
             '- Multiplicity: one frozen B/C contrast per window and one frozen batch/final rule. Counts describe that complete denominator, not multiplicity-adjusted population discoveries. No post-hoc threshold or subset search.',
             '- Missing evidence: FAIL/NOT_EVALUABLE retained without unmatched APE/RPE. Exact reasons are in window_outcomes.csv; frozen inactive B windows remain NOT_ACTIVATED.',
             '- Proxy and timing: COLMAP is not independent GT. Sensor first-pose delay, reference-relative delay and logged ROS initialization clock are distinct measurements. Candidate residual blocks may reuse observations across optimization calls.',
             '- Reproducibility: provenance.json pins all numerical inputs; common_support outputs retain the evaluator and evo checks; case_supplement_receipt.json verifies labels were not changed.', '']
    (OUT / 'stats-appendix.md').write_text('\n'.join(stats))
    catalog = ['# Figure catalog', '',
               '## figure-01-repeat-ranges.png / .svg', '',
               '- Purpose: show full technical-repeat ranges for both primary accuracy and the guardrail across every activated window.',
               '- Source: case_registry.csv and backend_results.csv, validated against exact per-repeat values before plotting.',
               '- Caption: paired B/C medians with min–max bars, three technical repeats per arm; log metre axes; * denotes severe regression; absent invalid metrics are not zero.',
               '- Key observation: read every outcome and range from the exact numeric table; the robust subset is determined by its registered condition.',
               '- Interpretation: stable separation, guardrail conflict and instability identify distinct mechanism cases; they do not yield a population confidence interval.',
               '- QA: verify labels, log scale, full denominator, no clipped ranges, and missing-case labels.', '',
               '## figure-02-case-context.png / .svg', '',
               '- Purpose: compare dose/lifetime and initialization timing descriptors with old A02/Bus controls.',
               '- Source: case_registry.csv and old_positive_comparison_reference.csv, each with its own frozen common support.',
               '- Caption: left published observations versus median APE C-B (symlog); right lifetime in published observations versus reference-relative first-pose delay C-B. Hollow diamonds are old outcome-known controls. No regression fit or causal inference.',
               '- Key observation: use labeled cases to contrast positive, neutral and negative sets, including cases with different initialization timing.',
               '- Interpretation: motivates case-specific utility/risk analysis, not a dose threshold or admission rule.',
               '- QA: old controls remain outside new counts, lifetime units are observations, initialization clocks are not mixed, and unplottable cases remain in the registry.', '',
               '## Unplottable cases', '']
    for c in cases:
        if number(c, 'APE_delta_m') is None:
            catalog.append('- {}: {}; {}. Accuracy absent by contract, not deleted.'.format(c['window_id'], c['classification'], c.get('not_evaluable_reason_detail') or c['reason']))
    catalog.append('')
    (OUT / 'figure-catalog.md').write_text('\n'.join(catalog))
    print('DESCRIPTIVE_ANALYSIS_COMPLETE', json.dumps(decision['classification_counts']))


if __name__ == '__main__':
    main()
