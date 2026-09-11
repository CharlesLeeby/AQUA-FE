#!/usr/bin/env python3
"""Single frozen P/T fit on verified prepared observations (no raw-data guessing).

NPZ: patches[N,3,31,31] float32 raw gray/255, history[N,4] original px,
patch_valid[N], baseline[N,2], truth[N,2], label_valid[N], frame[N], id[N],
sequence[N]. Metadata JSON: role, cache_sha256, supervision_checks.
Alternatively patch_bank[N,31,31] plus patch_indices[N,3] stores the exact
same float32 triplets without duplicating reference/previous patches.
"""
from __future__ import annotations
import argparse
import csv
import hashlib
import json
import os
from pathlib import Path
import time
import numpy as np
os.environ.setdefault('CUBLAS_WORKSPACE_CONFIG', ':4096:8')
import torch
from uw_frontend.temporal_refinement import PatchRefiner, paired_loss, require_verified_supervision

SEED = 20260911


class PatchTriplets:
    def __init__(self, bank, indices):
        if bank.ndim != 3 or bank.shape[1:] != (31,31) or indices.ndim != 2 or indices.shape[1] != 3:
            raise ValueError('invalid compact patch bank')
        if indices.size and (indices.min()<0 or indices.max()>=len(bank)):
            raise ValueError('patch reference outside bank')
        self.bank, self.indices = bank, indices
        self.shape = (len(indices),3,31,31)

    def __getitem__(self, index):
        return self.bank[self.indices[index]]


def file_sha256(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024**2),b''):
            digest.update(block)
    return digest.hexdigest()


def load_cache(path, role, split_path=None):
    meta = json.loads(path.with_suffix('.json').read_text())
    require_verified_supervision(meta['supervision_checks'])
    if meta['role'] != role or meta['cache_sha256'] != file_sha256(path):
        raise ValueError('cache role or identity mismatch')
    with np.load(path, allow_pickle=False) as src:
        a = {key: src[key] for key in src.files}
    if 'patch_bank' in a:
        a['patches'] = PatchTriplets(a.pop('patch_bank'),a.pop('patch_indices'))
    n = len(a['baseline'])
    for key, shape in [('patches', (n, 3, 31, 31)), ('history', (n, 4)),
                       ('baseline', (n, 2)), ('truth', (n, 2))]:
        if a[key].shape != shape:
            raise ValueError('invalid cache field: ' + key)
    for key in ['patch_valid', 'label_valid', 'frame', 'id', 'sequence']:
        if a[key].shape != (n,):
            raise ValueError('invalid row mapping: ' + key)
    split_path = split_path or Path(__file__).resolve().parents[1] / 'papers/frontend_temporal_observation_refinement_v1/data_split.json'
    expected = {s['sequence']: s for s in json.loads(split_path.read_text())['sequences'] if s['role'] == role}
    if set(a['sequence']) != set(expected):
        raise ValueError('cache sequences differ from frozen split')
    if not np.issubdtype(a['frame'].dtype, np.integer) or not np.issubdtype(a['id'].dtype, np.integer):
        raise ValueError('frame and ID must retain integer identity')
    for sequence, spec in expected.items():
        frames = a['frame'][a['sequence'] == sequence]
        if np.any(frames < spec['start_index']) or np.any(frames >= spec['end_index']):
            raise ValueError('cache contains observations outside frozen window')
    for key in ['label_valid', 'patch_valid']:
        if not np.isin(a[key], [0, 1]).all():
            raise ValueError('validity flags must be boolean')
        a[key] = a[key].astype(bool)
    if not np.isfinite(a['baseline']).all() or not np.isfinite(a['truth'][a['label_valid'].astype(bool)]).all():
        raise ValueError('nonfinite labeled coordinates')
    return a


def consecutive_pairs(a):
    """Never pair different sequences, IDs, invalid labels or frame gaps."""
    seen, pairs = {}, []
    for i, (seq, identity, frame) in enumerate(zip(a['sequence'], a['id'], a['frame'])):
        key = (str(seq), int(identity), int(frame))
        if key in seen:
            raise ValueError('duplicate observation identity')
        j = seen.get((key[0], key[1], key[2] - 1))
        if j is not None and a['label_valid'][i] and a['label_valid'][j]:
            pairs.append((j, i))
        seen[key] = i
    return np.asarray(pairs, dtype=np.int64).reshape(-1, 2)


def predict(model, a, device):
    output = []
    model.eval()
    with torch.no_grad():
        for start in range(0, len(a['baseline']), 256):
            sl = slice(start, start + 256)
            output.append(model(torch.as_tensor(a['patches'][sl], device=device).float(),
                                torch.as_tensor(a['history'][sl], device=device).float(),
                                torch.as_tensor(a['patch_valid'][sl], device=device)).cpu().numpy())
    return np.concatenate(output)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--train', type=Path, required=True)
    parser.add_argument('--validation', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--device', default='cpu')
    parser.add_argument('--split', type=Path, default=None, help='Explicit authorized frozen split; old MIMIR default preserved.')
    args = parser.parse_args()
    train, val = load_cache(args.train, 'train',args.split), load_cache(args.validation, 'validation',args.split)
    if set(train['sequence']) & set(val['sequence']):
        raise ValueError('sequence leakage')
    pairs = consecutive_pairs(train)
    if len(pairs) == 0 or not val['label_valid'].any():
        raise ValueError('no valid training pairs or validation labels')
    # Never overwrite a failed or completed experiment.
    args.output.mkdir(parents=True, exist_ok=False)
    torch.use_deterministic_algorithms(True)
    torch.set_num_threads(2)
    for arm, weight in [('P', 0.), ('T', .5)]:
        torch.manual_seed(SEED)
        rng = np.random.default_rng(SEED)
        model = PatchRefiner().to(args.device)
        initial_digest = hashlib.sha256(b''.join(x.detach().cpu().numpy().tobytes() for x in model.state_dict().values())).hexdigest()
        batch_digest = hashlib.sha256()
        optimizer = torch.optim.Adam(model.parameters(), lr=.001, betas=(.9, .999), eps=1e-8, weight_decay=0)
        best, best_step = float('inf'), None
        started = time.perf_counter()
        with (args.output / (arm + '_curve.csv')).open('w') as stream:
            writer = csv.DictWriter(stream, fieldnames=['arm', 'step', 'loss', 'pointwise', 'temporal', 'validation_p95', 'wall_s'])
            writer.writeheader()
            for step in range(5001):
                metrics = dict(arm=arm, step=step)
                if step:
                    model.train()
                    idx = pairs[rng.integers(len(pairs), size=128)].reshape(-1)
                    batch_digest.update(idx.tobytes())
                    delta = model(torch.as_tensor(train['patches'][idx], device=args.device).float(),
                                  torch.as_tensor(train['history'][idx], device=args.device).float(),
                                  torch.as_tensor(train['patch_valid'][idx], device=args.device)).reshape(-1, 2, 2)
                    baseline = torch.as_tensor(train['baseline'][idx], device=args.device).float().reshape(-1, 2, 2)
                    truth = torch.as_tensor(train['truth'][idx], device=args.device).float().reshape(-1, 2, 2)
                    loss, point, temporal = paired_loss(delta, baseline, truth, weight)
                    if not torch.isfinite(loss):
                        raise ValueError('nonfinite training loss; retain failed run')
                    optimizer.zero_grad()
                    loss.backward()
                    optimizer.step()
                    metrics.update(loss=loss.item(), pointwise=point.item(), temporal=temporal.item())
                if step % 250 == 0:
                    d = predict(model, val, args.device)
                    error = np.linalg.norm(val['baseline'] + d - val['truth'], axis=1)[val['label_valid'].astype(bool)]
                    score = float(np.quantile(error, .95))
                    metrics['validation_p95'] = score
                    if score < best:
                        best, best_step = score, step
                        torch.save(dict(state_dict=model.state_dict(), step=step, arm=arm, seed=SEED,
                                        validation_p95=score), args.output / (arm + '_best.pt'))
                    print(json.dumps(dict(arm=arm,step=step,validation_p95=score,best_step=best_step)),flush=True)
                metrics['wall_s'] = time.perf_counter() - started
                writer.writerow(metrics)
                stream.flush()
        (args.output / (arm + '_summary.json')).write_text(json.dumps(dict(
            arm=arm, updates=5000, best_step=best_step, validation_p95=best,
            initial_state_sha256=initial_digest,batch_schedule_sha256=batch_digest.hexdigest(),
            valid_training_pairs=len(pairs),device=args.device,torch_version=str(torch.__version__),
            wall_s=time.perf_counter() - started), indent=2) + '\n')


if __name__ == '__main__':
    main()
