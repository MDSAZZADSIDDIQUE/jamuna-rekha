"""Full-tile inference by overlapping sliding window.

The model is trained on crops (256 px locally, 512 on the A100) but the
forecast has to cover a whole 512 px tile, and eventually the whole reach. A
naive grid of non-overlapping crops leaves visible seams exactly where crops
meet — and a seam in an erosion map is indistinguishable from a predicted bank,
which would put a false warning in front of a disaster officer.

So windows overlap and are blended with a cosine taper that falls to zero at
the window edge. Contributions and weights are accumulated separately and
divided at the end, which makes the blend a proper weighted average regardless
of how many windows happen to cover a given pixel.
"""

from __future__ import annotations

import numpy as np
import torch

from jamunarekha.utils.logging import get_logger

logger = get_logger("jamunarekha.predict")


def cosine_window(size: int) -> np.ndarray:
    """2-D cosine taper, 1 at the centre and ~0 at the edges.

    Clipped away from exactly zero so that a pixel covered by only one window
    still receives a non-zero weight and does not divide by zero.
    """
    ramp = np.hanning(size + 2)[1:-1]
    ramp = np.clip(ramp, 1e-3, None)
    return np.outer(ramp, ramp).astype(np.float32)


@torch.no_grad()
def predict_tile(
    model: torch.nn.Module,
    frames: np.ndarray,
    crop_size: int,
    out_frames: int,
    overlap: float = 0.5,
    device: str = "cpu",
    batch_size: int = 1,
) -> np.ndarray:
    """Forecast the next ``out_frames`` months for a full tile.

    Parameters
    ----------
    model
        Any model honouring the project contract:
        ``(B, T_in, 1, H, W) -> (B, T_out, 1, H, W)`` logits.
    frames
        Observed water masks, ``(T_in, H, W)``, values in [0, 1].
    crop_size
        Spatial window the model was trained at.
    out_frames
        Forecast horizon in months.
    overlap
        Fraction of the window shared between neighbours. 0.5 gives a stride of
        half the window.
    device
        Torch device string.
    batch_size
        Windows per forward pass.

    Returns
    -------
    np.ndarray
        float32 ``(out_frames, H, W)`` of probabilities in [0, 1].
    """
    model = model.to(device).eval()
    t_in, height, width = frames.shape

    if height <= crop_size and width <= crop_size:
        batch = torch.from_numpy(frames[None, :, None]).float().to(device)
        return torch.sigmoid(model(batch))[0, :, 0].cpu().numpy()

    stride = max(1, int(crop_size * (1.0 - overlap)))
    rows = list(range(0, max(1, height - crop_size + 1), stride))
    cols = list(range(0, max(1, width - crop_size + 1), stride))
    if rows[-1] != height - crop_size:
        rows.append(height - crop_size)
    if cols[-1] != width - crop_size:
        cols.append(width - crop_size)

    taper = cosine_window(crop_size)
    accumulator = np.zeros((out_frames, height, width), dtype=np.float32)
    weights = np.zeros((1, height, width), dtype=np.float32)

    positions = [(r, c) for r in rows for c in cols]
    logger.info("tile inference: %d windows of %d px", len(positions), crop_size)

    for start in range(0, len(positions), batch_size):
        chunk = positions[start : start + batch_size]
        stack = np.stack(
            [frames[:, r : r + crop_size, c : c + crop_size] for r, c in chunk]
        )
        batch = torch.from_numpy(stack[:, :, None]).float().to(device)
        probs = torch.sigmoid(model(batch))[:, :, 0].cpu().numpy()

        for (r, c), prediction in zip(chunk, probs):
            accumulator[:, r : r + crop_size, c : c + crop_size] += prediction * taper
            weights[:, r : r + crop_size, c : c + crop_size] += taper

    return accumulator / np.maximum(weights, 1e-6)


@torch.no_grad()
def calibrate_threshold(
    model: torch.nn.Module,
    dataset,
    device: str = "cpu",
    max_batches: int = 40,
    batch_size: int = 4,
    grid: tuple[float, ...] = (0.3, 0.35, 0.4, 0.45, 0.5, 0.55, 0.6, 0.65, 0.7, 0.75, 0.8),
) -> tuple[float, dict]:
    """Pick the probability cut that maximises bank F1 on the validation split.

    **Why 0.5 is the wrong default here.** The loss uses ``pos_weight`` to stop
    binary cross-entropy collapsing to "predict land everywhere" — water is a
    minority class. That weighting does its job during training, but it also
    shifts the model's output distribution upward, so thresholding at 0.5
    systematically over-predicts water. Downstream that is not a cosmetic
    problem: erosion is *land now, water later*, so an over-predicted water
    mask inflates every hectare and every household count in the table handed
    to the Department of Disaster Management, in the alarming direction.

    The threshold is therefore chosen on **validation** data and then applied
    unchanged to test and to the operational forecast. Choosing it on the test
    split would be fitting the number being reported.

    Parameters
    ----------
    model
        A trained forecaster.
    dataset
        The validation ``JamunaShift52Y``.
    max_batches
        Cap on batches used, so calibration stays cheap on CPU.
    grid
        Candidate thresholds.

    Returns
    -------
    threshold : float
        The best cut.
    report : dict
        Bank F1 at every candidate, for the record.
    """
    from torch.utils.data import DataLoader

    from jamunarekha.models.metrics import MetricAccumulator

    model = model.to(device).eval()
    loader = DataLoader(dataset, batch_size=batch_size, shuffle=False)

    probs_all, target_all, valid_all = [], [], []
    for i, batch in enumerate(loader):
        if i >= max_batches:
            break
        probs = torch.sigmoid(model(batch["x"].to(device))).cpu().numpy()
        probs_all.append(probs)
        target_all.append(batch["y"].numpy())
        valid_all.append(batch["y_valid"].numpy())

    if not probs_all:
        return 0.5, {}

    probs = np.concatenate(probs_all)
    target = np.concatenate(target_all) > 0.5
    valid = np.concatenate(valid_all) > 0.5

    resolution = float(getattr(dataset, "resolution_m", 120.0))
    report: dict[str, float] = {}
    best_threshold, best_f1 = 0.5, -1.0
    for cut in grid:
        acc = MetricAccumulator(resolution_m=resolution)
        acc.update(probs > cut, target, valid)
        f1 = acc.compute()["bank_f1"]
        report[f"{cut:.2f}"] = round(float(f1), 4)
        if f1 > best_f1:
            best_threshold, best_f1 = float(cut), float(f1)

    logger.info(
        "threshold calibration on validation: best %.2f (bank F1 %.4f); grid %s",
        best_threshold, best_f1, report,
    )
    return best_threshold, report


def load_checkpoint(checkpoint_path, cfg, device: str = "cpu") -> torch.nn.Module:
    """Rebuild a model from a Lightning checkpoint.

    The architecture is rebuilt from ``cfg`` rather than from the checkpoint's
    stored hyperparameters, so that a checkpoint trained at one crop size can
    be applied at another — the transformer is fully convolutional in its
    decoder and its positional embeddings are interpolated by
    :func:`_resize_positional_embedding` when the token grid differs.
    """
    from jamunarekha.models.lit_module import build_model

    model = build_model(cfg)
    state = torch.load(checkpoint_path, map_location=device, weights_only=False)
    weights = state.get("state_dict", state)
    weights = {k[len("model.") :]: v for k, v in weights.items() if k.startswith("model.")}
    weights = _resize_positional_embedding(weights, model)
    missing, unexpected = model.load_state_dict(weights, strict=False)
    if missing:
        logger.warning("missing keys when loading checkpoint: %s", missing)
    if unexpected:
        logger.warning("unexpected keys when loading checkpoint: %s", unexpected)
    return model.to(device).eval()


def _resize_positional_embedding(weights: dict, model: torch.nn.Module) -> dict:
    """Bilinearly resize ``pos_space`` when inference uses a different crop size.

    The spatial positional embedding is one vector per token, laid out on a
    square grid. Changing the crop size changes the grid, so the embedding is
    reshaped to that grid, interpolated, and flattened back.
    """
    key = "pos_space"
    if key not in weights or not hasattr(model, "pos_space"):
        return weights

    saved = weights[key]
    target = model.pos_space
    if saved.shape == target.shape:
        return weights

    old_n, dim = saved.shape[1], saved.shape[2]
    new_n = target.shape[1]
    old_grid, new_grid = int(round(old_n**0.5)), int(round(new_n**0.5))
    if old_grid * old_grid != old_n or new_grid * new_grid != new_n:
        logger.warning("cannot resize pos_space %s -> %s", saved.shape, target.shape)
        return weights

    grid = saved.reshape(1, old_grid, old_grid, dim).permute(0, 3, 1, 2)
    grid = torch.nn.functional.interpolate(
        grid, size=(new_grid, new_grid), mode="bicubic", align_corners=False
    )
    weights[key] = grid.permute(0, 2, 3, 1).reshape(1, new_n, dim)
    logger.info("resized pos_space from %d to %d tokens", old_n, new_n)
    return weights
