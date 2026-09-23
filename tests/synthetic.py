"""A synthetic migrating river, for tests that must not depend on downloaded data.

The real ``JamunaShift-52Y`` tensor is gigabytes and takes hours to acquire.
The unit tests need something with the same *structure* — a sinuous channel
whose banks move steadily from month to month — so that "can this model learn
to forecast a shoreline" is a question with a knowable answer.

This is a test fixture. It never enters the dataset, the training run, or any
number reported in the paper.
"""

from __future__ import annotations

import numpy as np


def river_sequence(
    n_frames: int = 15,
    size: int = 64,
    width: float = 14.0,
    amplitude: float = 6.0,
    wavelength: float = 40.0,
    drift_per_frame: float = 0.8,
    seed: int = 1972,
    noise: float = 0.0,
) -> np.ndarray:
    """A sinuous channel migrating laterally at a constant rate.

    Parameters
    ----------
    n_frames
        Number of monthly frames.
    size
        Frame edge in pixels.
    width
        Channel width in pixels.
    amplitude, wavelength
        Meander geometry, pixels.
    drift_per_frame
        Lateral migration per frame, pixels. This is the signal a forecaster
        has to pick up.
    seed
        Seed for the optional noise.
    noise
        Probability of flipping any given pixel, simulating classification
        error in the water mask. 0 gives a noiseless channel.

    Returns
    -------
    np.ndarray
        float32 ``(n_frames, size, size)`` binary water masks, indexed
        ``(time, row, col)`` like every other raster stack in the project.
    """
    rows = np.arange(size)[:, None]
    cols = np.arange(size)[None, :]
    frames = np.zeros((n_frames, size, size), dtype=np.float32)

    for t in range(n_frames):
        centre = (
            size / 2.0
            + amplitude * np.sin(2.0 * np.pi * rows / wavelength)
            + drift_per_frame * t
        )
        frames[t] = (np.abs(cols - centre) < width / 2.0).astype(np.float32)

    if noise > 0:
        rng = np.random.default_rng(seed)
        flip = rng.random(frames.shape) < noise
        frames = np.where(flip, 1.0 - frames, frames)
    return frames


def river_batch(
    batch: int = 2,
    in_frames: int = 12,
    out_frames: int = 3,
    size: int = 64,
    seed: int = 1972,
):
    """A ``(x, y, valid)`` batch of migrating-river windows, as torch tensors.

    Each element of the batch gets a different meander phase and drift rate, so
    a model cannot pass by memorising one trajectory.

    Returns
    -------
    tuple
        ``x`` ``(B, in_frames, 1, size, size)``, ``y`` ``(B, out_frames, 1, size,
        size)``, ``valid`` of the same shape as ``y``.
    """
    import torch

    rng = np.random.default_rng(seed)
    xs, ys = [], []
    for _ in range(batch):
        sequence = river_sequence(
            n_frames=in_frames + out_frames,
            size=size,
            width=float(rng.uniform(10, 18)),
            amplitude=float(rng.uniform(4, 8)),
            wavelength=float(rng.uniform(30, 50)),
            drift_per_frame=float(rng.uniform(0.5, 1.1)),
        )
        xs.append(sequence[:in_frames])
        ys.append(sequence[in_frames:])

    x = torch.from_numpy(np.stack(xs)).unsqueeze(2)
    y = torch.from_numpy(np.stack(ys)).unsqueeze(2)
    return x, y, torch.ones_like(y)
