"""Underwater domain-adaptation fine-tuning of XFeat (self-supervised homography).

This mirrors the upstream ``xfeat_synthetic`` training path (self-supervised
homography warps, no GT poses / MegaDepth), but:

  * initializes from the released ``xfeat.pt`` weights instead of scratch,
  * optionally freezes the shallow backbone so only the higher-level features and
    heads adapt (lightweight domain adaptation),
  * injects the physically-motivated :mod:`underwater_degradation` augmentation
    into the augmentation pipe, and
  * saves state-dicts as ``xfeat_uw.pt`` that load directly via
    ``XFeatMatcher(weights=...)``.

Run from the workspace root (so ``uw_frontend`` is importable). Designed for a
single 24GB+ GPU (see uw_frontend/finetune/README.md for the RTX 5090 recipe);
a --dry_run smoke test fits on a 4GB laptop GPU at low resolution.

Example (cloud):
    python3 -m uw_frontend.finetune.finetune_xfeat_uw \
        --img-dir /workspace/uw_frames \
        --init-weights external_tools/accelerated_features/weights/xfeat.pt \
        --ckpt-dir logs/xfeat_uw_ft \
        --n-steps 30000 --batch-size 10 --lr 1e-4 --freeze-shallow
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import torch
import torch.nn.functional as F

from uw_frontend.finetune.underwater_degradation import (
    UnderwaterDegradation,
    UnderwaterDegradationConfig,
)
from uw_frontend.finetune.uw_adapter import UWAdapter, UWPhysAdapter

DEFAULT_REPO = Path("external_tools/accelerated_features")


def _install_alike_stub() -> None:
    """Stub out third_party.alike_wrapper so losses.py imports without ALIKE.

    Upstream ``losses.py`` imports ``extract_alike_kpts`` at module load, and the
    real wrapper instantiates an ALIKE teacher (needs the ALIKE submodule +
    weights). We only need that teacher for keypoint-position distillation, which
    is optional for domain-adaptation fine-tuning. Injecting a stub lets the
    descriptor/reliability losses import; the stub raises only if actually called
    (i.e. only under --use-alike-distill without the submodule installed).
    """
    import types

    if "third_party.alike_wrapper" in sys.modules:
        return
    try:  # if the real wrapper imports cleanly (submodule present), use it.
        import third_party.alike_wrapper  # noqa: F401
        return
    except Exception:
        pass

    stub = types.ModuleType("third_party.alike_wrapper")

    def extract_alike_kpts(*_args, **_kwargs):
        raise RuntimeError(
            "ALIKE teacher not installed. Run with the submodule "
            "(git submodule update --init third_party/ALIKE) to use --use-alike-distill."
        )

    stub.extract_alike_kpts = extract_alike_kpts
    sys.modules["third_party.alike_wrapper"] = stub


def _import_upstream(repo_path: Path):
    repo_str = str(repo_path.resolve())
    if repo_str not in sys.path:
        sys.path.insert(0, repo_str)
    _install_alike_stub()
    from modules.dataset.augmentation import AugmentationPipe
    from modules.model import XFeatModel
    from modules.training.losses import (
        alike_distill_loss,
        coordinate_classification_loss,
        dual_softmax_loss,
        keypoint_loss,
    )
    from modules.training.utils import get_corresponding_pts, make_batch

    return {
        "AugmentationPipe": AugmentationPipe,
        "XFeatModel": XFeatModel,
        "make_batch": make_batch,
        "get_corresponding_pts": get_corresponding_pts,
        "dual_softmax_loss": dual_softmax_loss,
        "coordinate_classification_loss": coordinate_classification_loss,
        "alike_distill_loss": alike_distill_loss,
        "keypoint_loss": keypoint_loss,
    }


# Shallow backbone modules frozen under --freeze-shallow (keep block3/4/5 + heads
# + fusion + fine_matcher trainable for domain adaptation).
FREEZE_PREFIXES = ("block1.", "block2.", "skip1.")


def _xfeat_forward_diff(net, x):
    """XFeatModel.forward WITHOUT the internal no_grad on the input normalization.

    The upstream forward wraps the grayscale + InstanceNorm in ``torch.no_grad()``,
    which severs gradient flow to anything upstream (e.g. a UWAdapter). This mirror
    keeps that path differentiable so an adapter can be trained end-to-end. Output
    is identical numerically; only the graph differs.
    """
    x = x.mean(dim=1, keepdim=True)
    x = net.norm(x)
    x1 = net.block1(x)
    x2 = net.block2(x1 + net.skip1(x))
    x3 = net.block3(x2)
    x4 = net.block4(x3)
    x5 = net.block5(x4)
    x4 = F.interpolate(x4, (x3.shape[-2], x3.shape[-1]), mode="bilinear")
    x5 = F.interpolate(x5, (x3.shape[-2], x3.shape[-1]), mode="bilinear")
    feats = net.block_fusion(x3 + x4 + x5)
    heatmap = net.heatmap_head(feats)
    keypoints = net.keypoint_head(net._unfold2d(x, ws=8))
    return feats, keypoints, heatmap


def _inject_degradation(augmentor, cfg: UnderwaterDegradationConfig) -> None:
    """Append underwater degradation after the stock photometric augmentations."""
    deg = UnderwaterDegradation(cfg).to(augmentor.device)
    original = augmentor.aug_list
    augmentor.aug_list = torch.nn.Sequential(original, deg)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Underwater domain-adaptation fine-tuning of XFeat.")
    p.add_argument("--img-dir", required=True, help="Directory of underwater frames (.jpg/.png) for self-supervision.")
    p.add_argument("--init-weights", default=str(DEFAULT_REPO / "weights" / "xfeat.pt"),
                   help="XFeat weights to initialize from (set to 'none' to train from scratch).")
    p.add_argument("--repo-path", default=str(DEFAULT_REPO), help="Path to the accelerated_features repo.")
    p.add_argument("--ckpt-dir", required=True, help="Where to save checkpoints and the final xfeat_uw.pt.")
    p.add_argument("--n-steps", type=int, default=30_000)
    p.add_argument("--batch-size", type=int, default=10)
    p.add_argument("--lr", type=float, default=1e-4)
    p.add_argument("--gamma-steplr", type=float, default=0.5)
    p.add_argument("--step-size", type=int, default=15_000, help="StepLR step size.")
    p.add_argument("--training-res", type=lambda s: tuple(map(int, s.split(","))), default=(800, 608),
                   help="Training resolution as width,height.")
    p.add_argument("--max-num-imgs", type=int, default=3000, help="Frames cached in RAM by the augmentor.")
    p.add_argument("--difficulty", type=float, default=0.10, help="Homography warp difficulty (upstream default 0.10).")
    p.add_argument("--freeze-shallow", action="store_true", help="Freeze block1/block2/skip1 (domain-adaptation mode).")
    p.add_argument("--no-degradation", action="store_true", help="Disable underwater degradation (ablation).")
    p.add_argument("--drop-degradation", choices=["none", "attenuation", "backscatter", "contrast", "blur"],
                   default="none", help="Leave-one-out: disable a single degradation component (ablation).")
    p.add_argument("--use-alike-distill", action="store_true",
                   help="Enable ALIKE keypoint-position distillation (needs third_party/ALIKE submodule). "
                        "Off by default: keeps stock keypoint detection, adapts descriptors + reliability only.")
    p.add_argument("--use-adapter", action="store_true",
                   help="Prepend a learnable UWAdapter enhancement front-end (saved as uw_adapter.pt). "
                        "Can be combined with --freeze-backbone to train ONLY the adapter.")
    p.add_argument("--freeze-backbone", action="store_true",
                   help="Freeze the entire XFeat backbone (train only the UWAdapter). Implies --use-adapter.")
    p.add_argument("--adapter-type", choices=["residual", "phys"], default="residual",
                   help="UWAdapter variant: 'residual' (generic) or 'phys' (physics-structured image-formation inversion).")
    p.add_argument("--save-every", type=int, default=1000)
    p.add_argument("--device", default="cuda")
    p.add_argument("--dry-run", action="store_true", help="Run a handful of steps at low res for a smoke test.")
    return p.parse_args()


def main() -> None:
    args = parse_args()
    up = _import_upstream(Path(args.repo_path))
    dev = torch.device(args.device if torch.cuda.is_available() or args.device == "cpu" else "cpu")

    if args.dry_run:
        args.n_steps = min(args.n_steps, 5)
        args.batch_size = min(args.batch_size, 2)
        args.training_res = (320, 240)
        args.max_num_imgs = min(args.max_num_imgs, 40)

    ckpt_dir = Path(args.ckpt_dir)
    ckpt_dir.mkdir(parents=True, exist_ok=True)

    # --- Model -----------------------------------------------------------------
    net = up["XFeatModel"]().to(dev)
    if args.init_weights and args.init_weights.lower() != "none":
        state = torch.load(args.init_weights, map_location=dev)
        net.load_state_dict(state)
        print(f"[init] loaded weights from {args.init_weights}")
    else:
        print("[init] training from scratch (no init weights)")

    if args.freeze_backbone:
        args.use_adapter = True
        for param in net.parameters():
            param.requires_grad_(False)
        print("[freeze] froze ENTIRE XFeat backbone (adapter-only training)")
    elif args.freeze_shallow:
        frozen = 0
        for name, param in net.named_parameters():
            if name.startswith(FREEZE_PREFIXES):
                param.requires_grad_(False)
                frozen += 1
        print(f"[freeze] froze {frozen} shallow-backbone tensors ({FREEZE_PREFIXES})")

    # Optional learnable underwater-enhancement front-end.
    adapter = None
    if args.use_adapter:
        adapter = (UWPhysAdapter() if args.adapter_type == "phys" else UWAdapter()).to(dev)
        adapter.train()
        print(f"[adapter] {args.adapter_type} adapter enabled ({sum(p.numel() for p in adapter.parameters())/1e3:.1f}K params)")

    trainable = [p for p in net.parameters() if p.requires_grad]
    if adapter is not None:
        trainable += list(adapter.parameters())
    n_train = sum(p.numel() for p in trainable)
    print(f"[params] trainable: {n_train/1e6:.3f}M / total: {sum(p.numel() for p in net.parameters())/1e6:.3f}M")

    opt = torch.optim.Adam(trainable, lr=args.lr)
    scheduler = torch.optim.lr_scheduler.StepLR(opt, step_size=args.step_size, gamma=args.gamma_steplr)

    # --- Augmentor (self-supervised homography + underwater degradation) -------
    augmentor = up["AugmentationPipe"](
        img_dir=args.img_dir,
        device=dev,
        load_dataset=True,
        batch_size=args.batch_size,
        out_resolution=args.training_res,
        warp_resolution=args.training_res,
        sides_crop=0.1,
        max_num_imgs=args.max_num_imgs,
        num_test_imgs=5,
        photometric=True,
        geometric=True,
        reload_step=4_000,
    )
    if not args.no_degradation:
        deg_cfg = UnderwaterDegradationConfig(
            enable_attenuation=args.drop_degradation != "attenuation",
            enable_backscatter=args.drop_degradation != "backscatter",
            enable_contrast=args.drop_degradation != "contrast",
            enable_blur=args.drop_degradation != "blur",
        )
        _inject_degradation(augmentor, deg_cfg)
        print(f"[aug] underwater degradation injected (drop={args.drop_degradation})")
    else:
        print("[aug] underwater degradation DISABLED (ablation)")

    make_batch = up["make_batch"]
    get_corresponding_pts = up["get_corresponding_pts"]
    dual_softmax_loss = up["dual_softmax_loss"]
    coordinate_classification_loss = up["coordinate_classification_loss"]
    alike_distill_loss = up["alike_distill_loss"]
    keypoint_loss = up["keypoint_loss"]

    # --- Training loop (synthetic-only path from upstream train.py) -------------
    net.train()
    t0 = time.time()
    for i in range(args.n_steps):
        p1s, p2s, H1, H2 = make_batch(augmentor, args.difficulty)
        h_c, w_c = p1s[0].shape[-2] // 8, p1s[0].shape[-1] // 8
        _, positives_c = get_corresponding_pts(p1s, p2s, H1, H2, augmentor, h_c, w_c)

        # RGB -> gray (inputs need no grad; net/adapter params do).
        p1 = p1s.mean(1, keepdim=True)
        p2 = p2s.mean(1, keepdim=True)

        if any(len(p) < 30 for p in positives_c):
            continue  # skip corrupted batch with too few correspondences

        # Optional learnable enhancement front-end (gradients flow into the adapter
        # via the differentiable forward that bypasses XFeat's no_grad input norm).
        if adapter is not None:
            p1 = adapter(p1)
            p2 = adapter(p2)
            feats1, kpts1, hmap1 = _xfeat_forward_diff(net, p1)
            feats2, kpts2, hmap2 = _xfeat_forward_diff(net, p2)
        else:
            feats1, kpts1, hmap1 = net(p1)
            feats2, kpts2, hmap2 = net(p2)

        loss_items = []
        for b in range(len(positives_c)):
            pts1, pts2 = positives_c[b][:, :2], positives_c[b][:, 2:]
            m1 = feats1[b, :, pts1[:, 1].long(), pts1[:, 0].long()].permute(1, 0)
            m2 = feats2[b, :, pts2[:, 1].long(), pts2[:, 0].long()].permute(1, 0)
            h1 = hmap1[b, 0, pts1[:, 1].long(), pts1[:, 0].long()]
            h2 = hmap2[b, 0, pts2[:, 1].long(), pts2[:, 0].long()]
            coords1 = net.fine_matcher(torch.cat([m1, m2], dim=-1))

            loss_ds, conf = dual_softmax_loss(m1, m2)
            loss_coords, _ = coordinate_classification_loss(coords1, pts1, pts2, conf)
            loss_kp = keypoint_loss(h1, conf) + keypoint_loss(h2, conf)

            loss_items += [
                loss_ds.unsqueeze(0),
                loss_coords.unsqueeze(0),
                loss_kp.unsqueeze(0),
            ]

            if args.use_alike_distill:
                loss_kp_pos1, _ = alike_distill_loss(kpts1[b], p1[b])
                loss_kp_pos2, _ = alike_distill_loss(kpts2[b], p2[b])
                loss_items.append(((loss_kp_pos1 + loss_kp_pos2) * 2.0).unsqueeze(0))

        if not loss_items:
            continue

        loss = torch.cat(loss_items, -1).mean()
        loss.backward()
        torch.nn.utils.clip_grad_norm_(trainable, 1.0)
        opt.step()
        opt.zero_grad()
        scheduler.step()

        if (i + 1) % 50 == 0 or args.dry_run:
            rate = (i + 1) / max(1e-6, time.time() - t0)
            print(f"[step {i+1}/{args.n_steps}] loss={loss.item():.4f} lr={scheduler.get_last_lr()[0]:.2e} {rate:.1f} it/s")

        if (i + 1) % args.save_every == 0:
            torch.save(net.state_dict(), ckpt_dir / f"xfeat_uw_{i+1}.pt")
            if adapter is not None:
                torch.save(adapter.state_dict(), ckpt_dir / f"uw_adapter_{i+1}.pt")
            print(f"[ckpt] saved step {i+1}")

    torch.save(net.state_dict(), ckpt_dir / "xfeat_uw.pt")
    if adapter is not None:
        torch.save(adapter.state_dict(), ckpt_dir / "uw_adapter.pt")
        print(f"[done] final weights -> {ckpt_dir/'xfeat_uw.pt'} + {ckpt_dir/'uw_adapter.pt'}")
    else:
        print(f"[done] final weights -> {ckpt_dir/'xfeat_uw.pt'}")


if __name__ == "__main__":
    main()
