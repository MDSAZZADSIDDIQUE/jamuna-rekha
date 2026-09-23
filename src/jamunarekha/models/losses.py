"""Loss functions for Stage 3.

The project loss is

    L = BCE + 0.3 * spatial_gradient_loss

and the 0.3 is the whole point. Binary cross-entropy alone is minimised by a
soft, blurred bank: the river edge is where the model is least certain, and
hedging there costs BCE almost nothing while destroying the only quantity the
forecast exists to produce. The Sobel term penalises a *gradient* mismatch, so
a smeared edge is expensive even when its per-pixel probabilities are close.

Everything here is masked by ``valid``, the flag marking target pixels that
came from a real satellite observation rather than Stage 2 interpolation.
"""

from __future__ import annotations

import torch
import torch.nn.functional as F
from torch import Tensor, nn

# Sobel kernels. Horizontal derivative and its transpose.
_SOBEL_X = torch.tensor(
    [[-1.0, 0.0, 1.0], [-2.0, 0.0, 2.0], [-1.0, 0.0, 1.0]], dtype=torch.float32
) / 8.0
_SOBEL_Y = _SOBEL_X.T.contiguous()


def _flatten_time(x: Tensor) -> tuple[Tensor, int]:
    """Fold ``(B, T, C, H, W)`` into ``(B*T, C, H, W)`` for 2-D convolution."""
    if x.dim() == 5:
        b, t, c, h, w = x.shape
        return x.reshape(b * t, c, h, w), t
    return x, 1


class SpatialGradientLoss(nn.Module):
    """L1 distance between the Sobel gradients of prediction and target.

    Parameters
    ----------
    eps
        Floor inside the gradient-magnitude square root, so the backward pass
        stays finite where the gradient vanishes (which is most of the frame).
    """

    def __init__(self, eps: float = 1e-6) -> None:
        super().__init__()
        self.eps = eps
        self.register_buffer("kx", _SOBEL_X.view(1, 1, 3, 3), persistent=False)
        self.register_buffer("ky", _SOBEL_Y.view(1, 1, 3, 3), persistent=False)

    def _grad(self, x: Tensor) -> tuple[Tensor, Tensor]:
        gx = F.conv2d(x, self.kx, padding=1)
        gy = F.conv2d(x, self.ky, padding=1)
        return gx, gy

    def forward(self, pred: Tensor, target: Tensor, valid: Tensor | None = None) -> Tensor:
        """
        Parameters
        ----------
        pred
            Probabilities in [0, 1], shape ``(B, T, C, H, W)`` or ``(B, C, H, W)``.
        target
            Binary ground truth, same shape.
        valid
            Optional mask, same shape, 1 where the target is a real observation.

        Returns
        -------
        Tensor
            Scalar loss.
        """
        pred_flat, _ = _flatten_time(pred)
        target_flat, _ = _flatten_time(target)

        gx_p, gy_p = self._grad(pred_flat)
        gx_t, gy_t = self._grad(target_flat)

        diff = (gx_p - gx_t).abs() + (gy_p - gy_t).abs()

        # Also match gradient magnitude: penalises an edge in the right place
        # but with the wrong sharpness, which the component terms can cancel.
        mag_p = torch.sqrt(gx_p.pow(2) + gy_p.pow(2) + self.eps)
        mag_t = torch.sqrt(gx_t.pow(2) + gy_t.pow(2) + self.eps)
        diff = diff + (mag_p - mag_t).abs()

        if valid is not None:
            valid_flat, _ = _flatten_time(valid)
            # A gradient at pixel p reads its 8 neighbours, so only score where
            # the whole 3x3 stencil is observed. min-pooling the validity mask
            # with a 3x3 window is exactly that test.
            stencil = -F.max_pool2d(-valid_flat, kernel_size=3, stride=1, padding=1)
            denom = stencil.sum().clamp_min(1.0)
            return (diff * stencil).sum() / denom
        return diff.mean()


class ErosionForecastLoss(nn.Module):
    """``bce_weight * BCE + gradient_weight * SpatialGradientLoss``.

    Parameters
    ----------
    bce_weight
        Weight on the per-pixel term. 1.0 throughout this project.
    gradient_weight
        Weight on the Sobel term. 0.3 — see ``docs/NOTES.md`` for the sweep
        that fixed it.
    pos_weight
        Positive-class weight inside BCE, compensating for water pixels being
        a minority of the frame. ``None`` disables it.
    """

    def __init__(
        self,
        bce_weight: float = 1.0,
        gradient_weight: float = 0.3,
        pos_weight: float | None = None,
    ) -> None:
        super().__init__()
        self.bce_weight = bce_weight
        self.gradient_weight = gradient_weight
        self.gradient = SpatialGradientLoss()
        if pos_weight is not None:
            self.register_buffer(
                "pos_weight", torch.tensor(float(pos_weight)), persistent=False
            )
        else:
            self.pos_weight = None

    def forward(
        self, logits: Tensor, target: Tensor, valid: Tensor | None = None
    ) -> dict[str, Tensor]:
        """
        Parameters
        ----------
        logits
            Raw model output (pre-sigmoid), ``(B, T, C, H, W)``.
        target
            Binary ground truth, same shape.
        valid
            Observation mask, same shape, or None to score every pixel.

        Returns
        -------
        dict
            ``{"loss", "bce", "grad"}`` — the total and its two parts, so the
            balance between them can be logged and audited during training.
        """
        if valid is None:
            valid = torch.ones_like(target)

        bce_map = F.binary_cross_entropy_with_logits(
            logits, target, reduction="none", pos_weight=self.pos_weight
        )
        bce = (bce_map * valid).sum() / valid.sum().clamp_min(1.0)

        probs = torch.sigmoid(logits)
        grad = self.gradient(probs, target, valid)

        total = self.bce_weight * bce + self.gradient_weight * grad
        return {"loss": total, "bce": bce.detach(), "grad": grad.detach()}
