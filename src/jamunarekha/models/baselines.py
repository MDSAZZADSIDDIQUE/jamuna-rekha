"""Baselines for Stage 3: ConvLSTM and persistence.

CLAUDE.md §2 requires *"Baselines with identical interfaces: same forward()
signature, same LightningModule contract, so the eval harness never
special-cases a model."* Both classes below therefore take ``(B, T_in, C, H, W)``
and return ``(B, T_out, 1, H, W)`` logits, exactly like
:class:`~jamunarekha.models.timesformer.TimeSformerForecaster`.

Persistence is the baseline that matters. A river is mostly where it was last
month, so "copy the last observed frame" is a genuinely strong forecaster and
the only honest yardstick for whether the neural model has learned anything.
Any headline result that does not beat persistence on **bank F1** and **MDE**
is a result about the Jamuna being large and slow, not about the model.
"""

from __future__ import annotations

import torch
from torch import Tensor, nn


class PersistenceForecaster(nn.Module):
    """Repeat the last observed frame for every forecast month.

    Has no parameters. The single dummy parameter exists so that Lightning,
    optimisers and checkpointing treat it like any other model rather than
    erroring on an empty parameter list — the alternative is a special case in
    the training harness, which is what the shared interface is meant to avoid.

    Parameters
    ----------
    out_frames
        Number of months to emit.
    logit_scale
        The binary input mask is mapped to ``+/- logit_scale`` so that a
        sigmoid recovers a near-binary probability. 8.0 gives ~0.9997, which
        is confident without saturating the BCE to infinity.
    """

    def __init__(self, out_frames: int = 3, logit_scale: float = 8.0, **_: object) -> None:
        super().__init__()
        self.out_frames = out_frames
        self.logit_scale = logit_scale
        self._dummy = nn.Parameter(torch.zeros(1), requires_grad=True)

    def forward(self, x: Tensor) -> Tensor:
        last = x[:, -1:]                                  # (B, 1, C, H, W)
        repeated = last.repeat(1, self.out_frames, 1, 1, 1)
        logits = (repeated * 2.0 - 1.0) * self.logit_scale
        return logits + self._dummy * 0.0                 # keeps it in the graph


class ConvLSTMCell(nn.Module):
    """One ConvLSTM cell (Shi and others, 2015).

    Gates are computed by a single convolution over the concatenated input and
    hidden state, which is both faster and better conditioned than four
    separate convolutions.
    """

    def __init__(self, in_channels: int, hidden_channels: int, kernel_size: int = 3) -> None:
        super().__init__()
        self.hidden_channels = hidden_channels
        padding = kernel_size // 2
        self.conv = nn.Conv2d(
            in_channels + hidden_channels,
            4 * hidden_channels,
            kernel_size=kernel_size,
            padding=padding,
        )
        # Forget-gate bias initialised to 1: the standard LSTM trick that stops
        # the cell forgetting everything before it has learned to remember.
        nn.init.zeros_(self.conv.bias)
        with torch.no_grad():
            self.conv.bias[hidden_channels : 2 * hidden_channels].fill_(1.0)

    def forward(
        self, x: Tensor, state: tuple[Tensor, Tensor] | None = None
    ) -> tuple[Tensor, Tensor]:
        """``x`` is ``(B, C, H, W)``; returns ``(hidden, cell)``."""
        b, _, h, w = x.shape
        if state is None:
            zeros = torch.zeros(
                b, self.hidden_channels, h, w, device=x.device, dtype=x.dtype
            )
            state = (zeros, zeros.clone())
        hidden, cell = state

        gates = self.conv(torch.cat([x, hidden], dim=1))
        i, f, o, g = gates.chunk(4, dim=1)
        i, f, o = torch.sigmoid(i), torch.sigmoid(f), torch.sigmoid(o)
        g = torch.tanh(g)

        cell = f * cell + i * g
        hidden = o * torch.tanh(cell)
        return hidden, cell


class ConvLSTMForecaster(nn.Module):
    """Stacked ConvLSTM encoder with a convolutional forecast head.

    The encoder reads the 12 input months; the final hidden state is decoded
    into ``out_frames`` masks in one shot. Single-shot decoding (rather than
    autoregressive roll-out) is deliberate: it matches the TimeSformer
    contract exactly, so the comparison isolates the encoder rather than
    confounding it with a different decoding strategy.

    Parameters
    ----------
    hidden_channels
        Width of each ConvLSTM layer.
    num_layers
        Depth of the stack.
    """

    def __init__(
        self,
        in_frames: int = 12,
        out_frames: int = 3,
        in_channels: int = 1,
        hidden_channels: int = 64,
        num_layers: int = 2,
        kernel_size: int = 3,
        **_: object,
    ) -> None:
        super().__init__()
        self.in_frames = in_frames
        self.out_frames = out_frames

        cells = []
        width = in_channels
        for _ in range(num_layers):
            cells.append(ConvLSTMCell(width, hidden_channels, kernel_size))
            width = hidden_channels
        self.cells = nn.ModuleList(cells)

        self.head = nn.Sequential(
            nn.Conv2d(hidden_channels, hidden_channels, kernel_size=3, padding=1),
            nn.GroupNorm(min(8, hidden_channels), hidden_channels),
            nn.GELU(),
            nn.Conv2d(hidden_channels, out_frames, kernel_size=1),
        )

    def forward(self, x: Tensor) -> Tensor:
        """``(B, T_in, C, H, W)`` -> ``(B, T_out, 1, H, W)`` logits."""
        b, t, c, h, w = x.shape
        if t != self.in_frames:
            raise ValueError(f"expected {self.in_frames} input frames, got {t}")

        states: list[tuple[Tensor, Tensor] | None] = [None] * len(self.cells)
        hidden = None
        for step in range(t):
            inp = x[:, step]
            for depth, cell in enumerate(self.cells):
                hidden, cell_state = cell(inp, states[depth])
                states[depth] = (hidden, cell_state)
                inp = hidden

        logits = self.head(hidden)                      # (B, T_out, H, W)
        return logits.unsqueeze(2)                      # (B, T_out, 1, H, W)
