#!/usr/bin/env python3
"""Final integrity check and compact receipt export, without new replays."""
import csv
import fcntl
import json
from pathlib import Path
from collections import Counter

from run_classical_opportunity_expansion import ROOT, PAPER, RUNTIME, sha, verify
from run_additive_budget_backend import config_contract
from classical_opportunity_py38 import load_analysis


def main():
    controller = (RUNTIME / 'controller.lock').open('r')
    fcntl.flock(controller, fcntl.LOCK_EX | fcntl.LOCK_NB)
    source = verify()
    analysis = load_analysis()
    decision = json.loads((PAPER / 'decision.json').read_text())
    assert decision['status'] == 'COMPLETE'
    output = PAPER / 'final_integrity_audit.json'
    assert not output.exists(), 'Keep prior audit; explicitly version any correction'
    execution = json.loads((PAPER / 'backend_execution_lock_v2.json').read_text())
    with (PAPER / 'case_registry.csv').open() as f:
        cases = {r['window_id']: r for r in csv.DictReader(f)}
    with (PAPER / 'backend_results.csv').open() as f:
        back = list(csv.DictReader(f))
    export = PAPER / 'run_receipts'
    assert not export.exists()
    export.mkdir()
    checked = {}
    failures = []
    audited = []

    def check(path, wanted):
        path = Path(path)
        actual = checked.get(str(path))
        if actual is None:
            actual = sha(path) if path.is_file() else 'MISSING'
            checked[str(path)] = actual
        if actual != wanted:
            failures.append({'path': str(path), 'expected': wanted, 'actual': actual})

    def receipt(path, dest):
        obj = json.loads(path.read_text())
        for key in ['artifacts', 'input_hashes']:
            for p, h in obj.get(key, {}).items():
                check(p, h)
        target = export / dest
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open('xb') as f:
            f.write(path.read_bytes())
        return obj

    for p, h in json.loads((PAPER / 'evaluation_lock.json').read_text()).items():
        check(ROOT / p, h)
    replay_count = 0
    for w in sorted(source['windows'], key=lambda w: (w['batch'], int(w['batch_order']))):
        slug = w['run_slug']
        c = cases[w['window_id']]
        if w['batch'] not in decision['activated_batches']:
            assert c['classification'] == 'NOT_ACTIVATED'
            assert not list((RUNTIME / 'backend' / slug).glob('*/repeat*/receipt.json'))
            continue
        row = {'window_id': w['window_id'], 'classification': c['classification'],
               'formal_receipts': 0, 'valid_accuracy_comparison': c['classification'] in ['PRACTICAL_GAIN', 'PRACTICAL_LOSS', 'SMALL_OR_UNCERTAIN']}
        front_path = RUNTIME / 'frontend' / slug / 'receipt.json'
        if front_path.exists():
            fr = receipt(front_path, Path(slug) / 'frontend.json')
            prepared = receipt(RUNTIME / 'prepared' / slug / 'receipt.json', Path(slug) / 'prepared.json')
            assert prepared['input_bag_sha256'] == fr['input_bag_sha256']
            check(w['input_bag'], fr['input_bag_sha256'])
            receipt(RUNTIME / 'baseline' / slug / 'receipt.json', Path(slug) / 'baseline.json')
            for arm in ['B', 'C-all']:
                check(fr['arms'][arm]['feature_bag'], fr['arms'][arm]['sha256'])
            dr = receipt(RUNTIME / 'frontend' / slug / 'independent_delivery_receipt.json', Path(slug) / 'independent_delivery.json')
            check(RUNTIME / 'frontend' / slug / 'independent_frame_audit.csv', dr['frame_audit_sha256'])
            assert dr['status'] == 'PASS' and dr['backbone_serialized_exact'] and dr['float32_ID_exact'] and dr['source_coordinates_q_velocity_exact']
            row['independent_delivery_status'] = dr['status']
        for arm in ['B', 'C-all']:
            for rep in [1, 2, 3]:
                target = RUNTIME / 'backend' / slug / arm / ('repeat' + str(rep))
                rp = target / 'receipt.json'
                if not rp.exists():
                    continue
                r = receipt(rp, Path(slug) / arm / ('repeat' + str(rep) + '.json'))
                row['formal_receipts'] += 1
                replay_count += 1
                assert r['run_slug'] == slug and r['arm'] == arm and r['repeat'] == rep
                check(r['feature_bag'], r['feature_bag_sha256'])
                check(execution['binary'], r['binary_sha256'])
                check(target / 'vins.yaml', r['config_sha256'])
                check(w['backend_config_source'], r['canonical_source_sha256'])
                check(PAPER / 'backend_execution_lock_v2.json', r['backend_lock_sha256'])
                assert config_contract((target / 'vins.yaml').read_text()) == config_contract(Path(w['backend_config_source']).read_text())
                br = next(b for b in back if b['window_id'] == c['window_id'] and b['arm'] == arm and int(b['repeat']) == rep)
                actual_receipts = analysis.per_id_receipts(r['feature_bag'], target)
                assert str(actual_receipts) == br['received_per_id_exact']
                assert r['status'] == br['status']
                if br['runability'] == 'PASS':
                    assert actual_receipts and float(br['max_actual_eligible']) <= execution['capacity']
        assert row['formal_receipts'] == int(c['backend_attempted'])
        support = PAPER / 'common_support' / slug / 'C-all_vs_B'
        ep = support / 'evaluation_receipt.json'
        if ep.exists():
            receipt(ep, Path(slug) / 'evaluation.json')
        if row['valid_accuracy_comparison']:
            s = json.loads((support / 'common_support_summary.json').read_text())['support']
            assert s['ape_valid'] and s['rpe_valid'] and s['matched_count'] >= 30 and s['common_span_s'] >= 10 and s['common_coverage'] >= .7 and s['rpe_pairs'] >= 10
            evo = json.loads((support / 'evo_crosscheck.json').read_text())
            diffs = [m[k] for arm in evo['arms'].values() for m in arm.values() for k in ['ape_abs_diff_m', 'rpe_abs_diff_m']]
            assert max(diffs) <= 1e-6
            row['evo_max_abs_diff_m'] = max(diffs)
            row['common_support'] = s
            metrics = [[float(b[metric]) for b in back if b['window_id'] == c['window_id'] and b['arm'] == arm] for metric, arm in [('APE', 'B'), ('APE', 'C-all'), ('RPE', 'B'), ('RPE', 'C-all')]]
            cl = analysis.classify(*metrics)
            assert cl['practical_classification'] == c['classification'] and str(cl['severe_regression']) == c['severe_regression']
            # The frozen descriptor may demote robust when new reset/failure logs occur.
            if cl['positive_level'] == 'ROBUST_PRACTICAL_GAIN':
                for key in ['reset_count_proxy', 'failure_detection_count']:
                    sums = {arm: sum(float(b[key]) for b in back if b['window_id'] == c['window_id'] and b['arm'] == arm) for arm in ['B', 'C-all']}
                    if sums['C-all'] > sums['B']:
                        cl['positive_level'] = 'PRACTICAL_GAIN'
            assert cl['positive_level'] == c['positive_level']
        else:
            assert not c.get('B_APE_median') and not c.get('C-all_APE_median')
            row['accuracy_reason'] = c['reason']
        audited.append(row)
    assert replay_count == decision['backend_attempted']
    assert Counter(r['classification'] for r in audited) == Counter(decision['classification_counts'])
    assert len(audited) == decision['physical_windows_planned']
    result = {'status': 'PASS' if not failures else 'INTEGRITY_FAILURE',
              'formal_replay_count': replay_count, 'physical_window_count': len(audited),
              'unique_artifact_hashes_checked': len(checked), 'windows': audited,
              'hash_mismatches': failures, 'source_locks_verified': True,
              'classification_recalculation': 'same frozen function; exact match for all valid comparisons',
              'foreign_host_exclusivity': 'Unknown; prestart process/port checks only, no claim of continuous host exclusivity',
              'script_sha256': sha(Path(__file__))}
    output.write_text(json.dumps(result, indent=2) + '\n')
    print('FINAL_INTEGRITY_AUDIT', result['status'], replay_count, len(audited))
    assert not failures, 'Preserve audit and diagnose mismatches before final publication'


if __name__ == '__main__':
    main()
