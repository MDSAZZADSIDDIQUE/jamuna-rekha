"""TimeSformer adapted from video classification to raster-sequence forecasting.

The original TimeSformer (Bertasius, Wang and Torresani, 2021) consumes a video
clip and emits a single class label. Two changes make it a shoreline forecaster:

1. **The classification head is replaced by a pixel-wise CNN decoder.** Instead
   of pooling the token grid into one vector, the tokens are kept as a spatial
   grid and upsampled back to full resolution, so the output is a
   ``crop_size`` x ``crop_size`` sigmoid mask per forecast month.
2. **A temporal projection maps 12 input months to 3 output months.** The
   encoder still attends over the 12 observed frames; a learned linear map over
   the time axis then produces the 3 forecast frames, which keeps the decoder
   shared across horizons instead of training three separate heads.

The encoder keeps TimeSformer's defining feature, **divided space-time
attention**: each block attends over time first (each spatial position looks at
its own history) and then over space (each frame looks at itself). Joint
space-time attention over 12 x 1024 tokens is quadratic in 12288 and does not
fit the GPU budget; divided attention is quadratic in 12 and in 1024
separately, which does.

Shapes throughout: ``(B, T, C, H, W)`` in, ``(B, T_out, C, H, W)`` out, raw
logits (no sigmoid — the loss applies it).
"""

from __future__ import annotations

import math

import torch
from einops import rearrange
from torch import Tensor, nn


class Mlp(nn.Module):
    """Transformer feed-forward block."""

    def __init__(self, dim: int, hidden: int, dropout: float = 0.0) -> None:
        super().__init__()
        self.fc1 = nn.Linear(dim, hidden)
        self.act = nn.GELU()
        self.fc2 = nn.Linear(hidden, dim)
        self.drop = nn.Dropout(dropout)

    def forward(self, x: Tensor) -> Tensor:
        return self.drop(self.fc2(self.drop(self.act(self.fc1(x)))))


class Attention(nn.Module):
    """Standard multi-head self-attention over the last-but-one axis."""

    def __init__(self, dim: int, num_heads: int, dropout: float = 0.0) -> None:
        super().__init__()
        if dim % num_heads != 0:
            raise ValueError(f"embed_dim {dim} must be divisible by num_heads {num_heads}")
        self.num_heads = num_heads
        self.scale = (dim // num_heads) ** -0.5
        self.qkv = nn.Linear(dim, dim * 3, bias=True)
        self.proj = nn.Linear(dim, dim)
        self.drop = nn.Dropout(dropout)

    def forward(self, x: Tensor) -> Tensor:
        """``x`` is ``(batch, seq, dim)``; returns the same shape."""
        b, n, d = x.shape
        qkv = self.qkv(x).reshape(b, n, 3, self.num_heads, d // self.num_heads)
        qkv = qkv.permute(2, 0, 3, 1, 4)  # (3, B, heads, seq, head_dim)
        q, k, v = qkv[0], qkv[1], qkv[2]

        attn = (q @ k.transpose(-2, -1)) * self.scale
        attn = attn.softmax(dim=-1)
        attn = self.drop(attn)

        out = (attn @ v).transpose(1, 2).reshape(b, n, d)
        return self.drop(self.proj(out))


class DividedSpaceTimeBlock(nn.Module):
    """One TimeSformer block: temporal attention, then spatial, then MLP.

    The temporal branch is zero-initialised at its output projection so the
    block starts as a pure spatial transformer and *learns* to use time. This
    is the residual-gating trick from the original paper and it matters here:
    with only 12 frames, an untamed temporal branch dominates early training and
    the model collapses to copying the last frame.
    """

    def __init__(self, dim: int, num_heads: int, mlp_ratio: float = 4.0, dropout: float = 0.0) -> None:
        super().__init__()
        self.norm_time = nn.LayerNorm(dim)
        self.attn_time = Attention(dim, num_heads, dropout)
        self.proj_time = nn.Linear(dim, dim)
        nn.init.zeros_(self.proj_time.weight)
        nn.init.zeros_(self.proj_time.bias)

        self.norm_space = nn.LayerNorm(dim)
        self.attn_space = Attention(dim, num_heads, dropout)

        self.norm_mlp = nn.LayerNorm(dim)
        self.mlp = Mlp(dim, int(dim * mlp_ratio), dropout)

    def forward(self, x: Tensor, n_time: int, n_space: int) -> Tensor:
        """``x`` is ``(B, T*N, D)`` with time-major ordering."""
        b = x.shape[0]

        # ---- temporal: every spatial position attends over its own history --
        xt = rearrange(x, "b (t n) d -> (b n) t d", t=n_time, n=n_space)
        xt = self.attn_time(self.norm_time(xt))
        xt = self.proj_time(xt)
        xt = rearrange(xt, "(b n) t d -> b (t n) d", b=b, n=n_space)
        x = x + xt

        # ---- spatial: every frame attends over itself ----------------------
        xs = rearrange(x, "b (t n) d -> (b t) n d", t=n_time, n=n_space)
        xs = self.attn_space(self.norm_space(xs))
        xs = rearrange(xs, "(b t) n d -> b (t n) d", b=b, t=n_time)
        x = x + xs

        return x + self.mlp(self.norm_mlp(x))


class PixelDecoder(nn.Module):
    """Upsample a token grid back to full raster resolution.

    Replaces TimeSformer's classification head. Each stage is
    ``Upsample(2x, nearest) -> Conv3x3 -> GroupNorm -> GELU``. Nearest-neighbour
    upsampling followed by convolution is used instead of a transposed
    convolution because transposed convolutions leave checkerboard artefacts,
    and a checkerboard on a riverbank is indistinguishable from a real
    small-scale bank feature.
    """

    def __init__(self, in_dim: int, channels: list[int], patch_size: int, out_channels: int = 1) -> None:
        super().__init__()
        n_up = int(math.log2(patch_size))
        if 2 ** n_up != patch_size:
            raise ValueError(f"patch_size must be a power of two, got {patch_size}")

        schedule = list(channels)
        # Pad or trim the channel schedule to exactly n_up stages.
        while len(schedule) < n_up:
            schedule.append(max(16, schedule[-1] // 2))
        schedule = schedule[:n_up]

        layers: list[nn.Module] = []
        prev = in_dim
        for width in schedule:
            layers += [
                nn.Upsample(scale_factor=2, mode="nearest"),
                nn.Conv2d(prev, width, kernel_size=3, padding=1),
                nn.GroupNorm(num_groups=min(8, width), num_channels=width),
                nn.GELU(),
            ]
            prev = width
        self.body = nn.Sequential(*layers)
        self.head = nn.Conv2d(prev, out_channels, kernel_size=1)

    def forward(self, x: Tensor) -> Tensor:
        """``(B, D, h, w)`` -> ``(B, out_channels, h*patch, w*patch)``."""
        return self.head(self.body(x))


class TimeSformerForecaster(nn.Module):
    """Predict the next ``out_frames`` water masks from ``in_frames`` observed ones.

    Parameters
    ----------
    in_frames, out_frames
        Sequence lengths in months. 12 and 3 for this project.
    img_size
        Spatial edge of the input crop. Must be divisible by ``patch_size``.
    patch_size
        Token footprint in pixels.
    in_channels
        1 — the binary water mask.
    embed_dim, depth, num_heads
        Encoder width, number of blocks, attention heads.
    decoder_channels
        Channel widths of the upsampling stages.
    dropout
        Applied inside attention and MLP.
    """

    def __init__(
        self,
        in_frames: int = 12,
        out_frames: int = 3,
        img_size: int = 512,
        patch_size: int = 16,
        in_channels: int = 1,
        embed_dim: int = 256,
        depth: int = 6,
        num_heads: int = 8,
        decoder_channels: list[int] | None = None,
        dropout: float = 0.1,
    ) -> None:
        super().__init__()
        if img_size % patch_size != 0:
            raise ValueError(f"img_size {img_size} not divisible by patch_size {patch_size}")

        self.in_frames = in_frames
        self.out_frames = out_frames
        self.patch_size = patch_size
        self.grid = img_size // patch_size
        self.n_space = self.grid * self.grid
        self.embed_dim = embed_dim

        self.patch_embed = nn.Conv2d(
            in_channels, embed_dim, kernel_size=patch_size, stride=patch_size
        )
        self.pos_space = nn.Parameter(torch.zeros(1, self.n_space, embed_dim))
        self.pos_time = nn.Parameter(torch.zeros(1, in_frames, embed_dim))
        nn.init.trunc_normal_(self.pos_space, std=0.02)
        nn.init.trunc_normal_(self.pos_time, std=0.02)

        self.blocks = nn.ModuleList(
            [DividedSpaceTimeBlock(embed_dim, num_heads, dropout=dropout) for _ in range(depth)]
        )
        self.norm = nn.LayerNorm(embed_dim)

        # Learned map from the 12 encoded months to the 3 forecast months.
        self.temporal_head = nn.Linear(in_frames, out_frames)

        self.decoder = PixelDecoder(
            embed_dim, decoder_channels or [128, 64, 32], patch_size, out_channels=1
        )

    def forward(self, x: Tensor) -> Tensor:
        """
        Parameters
        ----------
        x
            ``(B, T_in, C, H, W)`` float tensor of water masks in [0, 1].

        Returns
        -------
        Tensor
            ``(B, T_out, 1, H, W)`` raw logits.
        """
        b, t, c, h, w = x.shape
        if t != self.in_frames:
            raise ValueError(f"expected {self.in_frames} input frames, got {t}")

        tokens = self.patch_embed(rearrange(x, "b t c h w -> (b t) c h w"))
        tokens = rearrange(tokens, "(b t) d gh gw -> b t (gh gw) d", b=b, t=t)

        tokens = tokens + self.pos_space.unsqueeze(1)
        tokens = tokens + self.pos_time.unsqueeze(2)
        tokens = rearrange(tokens, "b t n d -> b (t n) d")

        for block in self.blocks:
            tokens = block(tokens, n_time=t, n_space=self.n_space)
        tokens = self.norm(tokens)

        # (B, T_in, N, D) -> (B, T_out, N, D)
        tokens = rearrange(tokens, "b (t n) d -> b n d t", t=t, n=self.n_space)
        tokens = self.temporal_head(tokens)
        tokens = rearrange(
            tokens, "b (gh gw) d t -> (b t) d gh gw", gh=self.grid, gw=self.grid
        )

        logits = self.decoder(tokens)
        return rearrange(logits, "(b t) c h w -> b t c h w", b=b, t=self.out_frames)
