"""Physically-motivated underwater degradation augmentation.

Implements a simplified Jaffe--McGlamery underwater image formation model as a
differentiable, batched ``nn.Module`` operating on RGB tensors in ``[0, 1]`` with
shape ``(B, 3, H, W)``:

    I_c(x) = J_c(x) * t_c  +  B_c * (1 - t_c) * v(x)

where ``J`` is the clean (in-air) radiance, ``t_c = exp(-beta_c * d)`` is the
per-channel transmission (red is absorbed fastest, so ``t_R < t_G, t_B``), ``B_c``
is the bluish-green veiling (back-scatter) light, and ``v(x)`` is a smooth
spatial gradient that makes the haze depth-dependent. A mild contrast
compression and forward-scatter blur complete the model.

Parameters are sampled independently per batch element so a single mini-batch
spans a range of turbidity / distance conditions. The sampling ranges below are
the values reported in the paper's "degradation-aware fine-tuning" recipe --
change them here and they change everywhere.
"""

from __future__ import annotations

from dataclasses import dataclass

import torch
import torch.nn as nn
import torch.nn.functional as F


@dataclass
class UnderwaterDegradationConfig:
    # Per-channel transmission t_c (fraction of radiance surviving to camera).
    # Red attenuates fastest underwater -> smallest transmission.
    t_red: tuple[float, float] = (0.45, 0.85)
    t_green: tuple[float, float] = (0.70, 0.95)
    t_blue: tuple[float, float] = (0.72, 0.96)
    # Veiling / back-scatter light color B_c (bluish-green, low red).
    b_red: tuple[float, float] = (0.05, 0.25)
    b_green: tuple[float, float] = (0.30, 0.60)
    b_blue: tuple[float, float] = (0.30, 0.65)
    # Strength of the smooth spatial haze gradient v(x) in [1 - amp, 1].
    haze_gradient_amp: tuple[float, float] = (0.0, 0.4)
    # Multiplicative global contrast compression around the mean.
    contrast: tuple[float, float] = (0.6, 1.0)
    # Forward-scatter Gaussian blur sigma (0 disables). Applied with prob blur_prob.
    blur_sigma: tuple[float, float] = (0.0, 1.6)
    blur_prob: float = 0.5
    # Probability the whole degradation is applied to the batch.
    apply_prob: float = 0.9
    # Per-component toggles (for leave-one-out degradation ablation).
    enable_attenuation: bool = True
    enable_backscatter: bool = True
    enable_contrast: bool = True
    enable_blur: bool = True


def _rand(lo: float, hi: float, shape, device) -> torch.Tensor:
    return torch.empty(shape, device=device).uniform_(lo, hi)


class UnderwaterDegradation(nn.Module):
    """Apply randomized underwater degradation to a batch of RGB images."""

    def __init__(self, config: UnderwaterDegradationConfig | None = None) -> None:
        super().__init__()
        self.cfg = config or UnderwaterDegradationConfig()

    @torch.no_grad()
    def forward(self, x: torch.Tensor) -> torch.Tensor:
        if x.ndim != 4 or x.shape[1] != 3:
            # Silently pass through non-RGB batches (keeps the pipe robust).
            return x
        if torch.rand(()) > self.cfg.apply_prob:
            return x

        cfg = self.cfg
        b, _, h, w = x.shape
        dev = x.device

        # Per-channel transmission, shape (B, 3, 1, 1).
        t = torch.stack(
            [
                _rand(*cfg.t_red, (b,), dev),
                _rand(*cfg.t_green, (b,), dev),
                _rand(*cfg.t_blue, (b,), dev),
            ],
            dim=1,
        ).view(b, 3, 1, 1)

        # Veiling light color, shape (B, 3, 1, 1).
        bl = torch.stack(
            [
                _rand(*cfg.b_red, (b,), dev),
                _rand(*cfg.b_green, (b,), dev),
                _rand(*cfg.b_blue, (b,), dev),
            ],
            dim=1,
        ).view(b, 3, 1, 1)

        # Smooth vertical haze gradient v(x) in [1 - amp, 1] (nearer top = clearer).
        amp = _rand(*cfg.haze_gradient_amp, (b, 1, 1, 1), dev)
        ramp = torch.linspace(0.0, 1.0, steps=h, device=dev).view(1, 1, h, 1)
        veil = (1.0 - amp) + amp * ramp  # (B, 1, H, W-broadcast)

        # Underwater image formation, with per-component toggles for leave-one-out
        # ablation. Full model: I = J*t + B*(1-t)*veil.
        if cfg.enable_attenuation and cfg.enable_backscatter:
            out = x * t + bl * (1.0 - t) * veil          # full physical model
        elif cfg.enable_attenuation:
            out = x * t                                   # wavelength attenuation only
        elif cfg.enable_backscatter:
            out = x + bl * (1.0 - t) * veil               # additive veiling haze only
        else:
            out = x
        out = out.clamp(0.0, 1.0)

        # Global contrast compression around per-image mean.
        if cfg.enable_contrast:
            c = _rand(*cfg.contrast, (b, 1, 1, 1), dev)
            mean = out.mean(dim=(2, 3), keepdim=True)
            out = ((out - mean) * c + mean).clamp(0.0, 1.0)

        # Forward-scatter blur.
        if cfg.enable_blur and cfg.blur_sigma[1] > 0 and torch.rand(()) < cfg.blur_prob:
            sigma = float(_rand(*cfg.blur_sigma, (), dev).item())
            if sigma > 1e-3:
                out = _gaussian_blur(out, sigma)

        return out.clamp(0.0, 1.0)


def _gaussian_blur(x: torch.Tensor, sigma: float) -> torch.Tensor:
    radius = max(1, int(round(3.0 * sigma)))
    ksize = 2 * radius + 1
    coords = torch.arange(ksize, device=x.device, dtype=x.dtype) - radius
    g = torch.exp(-(coords**2) / (2.0 * sigma * sigma))
    g = (g / g.sum()).view(1, 1, 1, ksize)
    c = x.shape[1]
    kx = g.expand(c, 1, 1, ksize)
    ky = g.transpose(2, 3).expand(c, 1, ksize, 1)
    x = F.conv2d(x, kx, padding=(0, radius), groups=c)
    x = F.conv2d(x, ky, padding=(radius, 0), groups=c)
    return x
