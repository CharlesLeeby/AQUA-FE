"""UWAdapter: a tiny learnable underwater-enhancement front-end for XFeat.

Prepended before a *frozen* XFeat backbone, this module learns a residual
correction on the grayscale input so that underwater-degraded frames are mapped
closer to the in-air distribution XFeat's features were trained on. It is
deliberately small (a few conv layers, initialized near-identity via the
zero-initialized residual head) so it adapts the input without disturbing the
strong pretrained descriptors.

Operates on grayscale tensors ``(B, 1, H, W)`` in ``[0, 1]`` and returns an
enhanced grayscale tensor of the same shape in ``[0, 1]``.
"""

from __future__ import annotations

import torch
import torch.nn as nn


class UWAdapter(nn.Module):
    def __init__(self, width: int = 16) -> None:
        super().__init__()
        self.body = nn.Sequential(
            nn.Conv2d(1, width, 3, padding=1),
            nn.ReLU(inplace=True),
            nn.Conv2d(width, width, 3, padding=1),
            nn.ReLU(inplace=True),
        )
        self.head = nn.Conv2d(width, 1, 3, padding=1)
        # Zero-init the residual head so the adapter starts as identity.
        nn.init.zeros_(self.head.weight)
        nn.init.zeros_(self.head.bias)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        residual = self.head(self.body(x))
        return torch.clamp(x + residual, 0.0, 1.0)


class UWPhysAdapter(nn.Module):
    """Physics-structured underwater enhancement front-end for frozen XFeat.

    Instead of a free-form residual, this module inverts a simplified underwater
    image-formation model on the grayscale input::

        I = J * t + A * (1 - t)   ->   J = (I - A * (1 - t)) / t

    where ``I`` is the observed (degraded) intensity, ``J`` the restored
    (matching-oriented) intensity, ``t`` a learned per-pixel transmission map, and
    ``A`` a learned global ambient / back-scatter level. A small CNN predicts the
    transmission map; ``A`` is predicted from a global descriptor. The module is
    initialized near identity (t -> 1) so training starts from a no-op and is
    driven end-to-end by the XFeat matching loss (via the differentiable forward
    that bypasses XFeat's no_grad input normalization).

    This turns the enhancement into a *physics-prior* module (nameable method +
    interpretable t/A) rather than a generic residual CNN.
    """

    def __init__(self, width: int = 16, t_min: float = 0.1) -> None:
        super().__init__()
        self.t_min = t_min
        self.body = nn.Sequential(
            nn.Conv2d(1, width, 3, padding=1),
            nn.ReLU(inplace=True),
            nn.Conv2d(width, width, 3, padding=1),
            nn.ReLU(inplace=True),
        )
        self.t_head = nn.Conv2d(width, 1, 3, padding=1)      # transmission logits
        self.a_head = nn.Linear(width, 1)                    # global ambient logit
        # Init near identity: t -> 1 (large positive logit), A -> small.
        nn.init.zeros_(self.t_head.weight)
        nn.init.constant_(self.t_head.bias, 4.0)             # sigmoid(4) ~ 0.98
        nn.init.zeros_(self.a_head.weight)
        nn.init.constant_(self.a_head.bias, -2.0)            # sigmoid(-2) ~ 0.12

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        feat = self.body(x)
        # Per-pixel transmission in [t_min, 1].
        t = torch.sigmoid(self.t_head(feat))
        t = self.t_min + (1.0 - self.t_min) * t
        # Global ambient light in [0, 1] from spatial-average descriptor.
        a = torch.sigmoid(self.a_head(feat.mean(dim=(2, 3)))).view(-1, 1, 1, 1)
        # Invert the formation model and restore.
        j = (x - a * (1.0 - t)) / t
        return torch.clamp(j, 0.0, 1.0)
