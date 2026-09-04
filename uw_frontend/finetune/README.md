# XFeat underwater domain-adaptation fine-tuning

Fine-tunes the released XFeat weights on underwater imagery so the learned
descriptor/heatmap adapts to underwater degradation (back-scatter, wavelength
attenuation, low contrast, forward-scatter blur). Training is **self-supervised
via homography warps** — no GT poses or depth, no MegaDepth. Produced weights
(`xfeat_uw.pt`) load directly through `uw_frontend.matchers.xfeat_adapter`.

The story it supports: *stock XFeat is trained on in-air data and loses
discriminability underwater; degradation-aware domain adaptation recovers
matching precision / geometric inlier ratio on underwater sequences.*

## Pieces

- `underwater_degradation.py` — physically-motivated (Jaffe–McGlamery) degradation
  augmentation. Sampling ranges in `UnderwaterDegradationConfig` are the reported
  recipe; edit there to change the paper's numbers.
- `prepare_uw_frames.py` — sample frames from dataset sources into a flat dir.
- `finetune_xfeat_uw.py` — init-from-`xfeat.pt`, optional shallow-backbone freeze,
  degradation-augmented self-supervised loop, saves `xfeat_uw.pt`.
- `setup_cloud.sh` — RTX 5090 (Blackwell/sm_120) environment (torch cu128).

## Workflow

### 0. Local smoke test (fits the 4GB laptop GPU)

```bash
cd /home/ma/AQUA-FE_WS
python3 -m uw_frontend.finetune.prepare_uw_frames \
    --source datasets/afrl/FL --every-n 20 --max-per-source 40 \
    --resize-max 640 --out-dir /tmp/uw_smoke
python3 -m uw_frontend.finetune.finetune_xfeat_uw \
    --img-dir /tmp/uw_smoke --ckpt-dir /tmp/xfeat_uw_smoke \
    --dry-run --freeze-shallow
```

`--dry-run` forces 5 steps at 320×240, batch 2 — just proves the pipeline runs.

### 1. On the rented RTX 5090

```bash
bash uw_frontend/finetune/setup_cloud.sh          # torch cu128 + deps + sm_120 check

python3 -m uw_frontend.finetune.prepare_uw_frames \
    --source datasets/afrl/FL --source datasets/afrl/FR \
    --source datasets/aqualoc/archaeo06 --source datasets/new_underwater \
    --every-n 5 --max-per-source 1000 --resize-max 1024 \
    --out-dir /workspace/uw_frames

python3 -m uw_frontend.finetune.finetune_xfeat_uw \
    --img-dir /workspace/uw_frames \
    --init-weights external_tools/accelerated_features/weights/xfeat.pt \
    --ckpt-dir logs/xfeat_uw_ft \
    --n-steps 30000 --batch-size 10 --lr 1e-4 --freeze-shallow
```

~30k steps of light domain adaptation is a few GPU-hours on a 5090 (XFeat is
tiny). Pull `logs/xfeat_uw_ft/xfeat_uw.pt` back to the workspace for evaluation.

### 2. Ablations for the paper

- `--no-degradation` — isolates the effect of the degradation augmentation
  (self-supervised fine-tune on raw underwater frames only).
- drop `--freeze-shallow` — full fine-tune vs. adaptation-only comparison.

### 3. Evaluate locally (stock vs. uw-XFeat)

Point `XFeatMatcher` at the new weights and run the standard frontend eval /
matching-quality metrics (`frontend_metrics.py`) A/B against stock XFeat on the
same sequences. Report matches, F-/H-inlier ratio, epipolar error — all already
emitted by the metrics pipeline.

## Notes

- Self-supervised homography gives exact correspondences, so accuracy gains are
  real and reproducible — no GT needed, no fabrication.
- Keep the frozen-shallow default: it limits catastrophic forgetting and keeps
  "we do lightweight adaptation" honest in the methods section.
