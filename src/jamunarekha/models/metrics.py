"""Evaluation metrics for Stage 3.

Three numbers, each answering a different question (CLAUDE.md §2):

``IoU``
    Did we get the *water body* right? Computed over all valid pixels. Easy to
    score well on: the Jamuna is a large, mostly-stable object, so IoU is high
    for any sane model and is reported mainly to show nothing is broken.

``bank F1``
    Did we get the *edge* right? Restricted to a narrow band around the
    ground-truth land/water boundary. The class balance over a full frame is
    brutal — bank pixels are a low single-digit percentage — so a whole-frame
    F1 would be dominated by easy interior pixels and would hide exactly the
    failure that matters.

``MDE``
    How far off were we, **in metres**? The symmetric mean boundary distance
    between the predicted and observed shorelines, multiplied by the pixel
    size. This is the number a disaster officer can act on, and it is only
    meaningful because every raster in this project lives in EPSG:32645, a
    metric CRS (CLAUDE.md §4).
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from scipy import ndimage


@dataclass
class MetricAccumulator:
    """Running totals for a whole evaluation split.

    IoU and F1 are accumulated as raw counts and reduced at the end, not
    averaged per batch. A per-batch average silently over-weights crops that
    happen to contain little water, which is a real effect here because the
    tiles include dry floodplain.
    """

    resolution_m: float
    bank_width_px: int = 2

    intersection: float = 0.0
    union: float = 0.0
    tp: float = 0.0
    fp: float = 0.0
    fn: float = 0.0
    displacements: list[float] = field(default_factory=list)
    n_frames: int = 0

    def update(self, pred: np.ndarray, target: np.ndarray, valid: np.ndarray) -> None:
        """Accumulate one batch.

        Parameters
        ----------
        pred
            Binary predictions, shape ``(..., H, W)``. Any leading axes are
            treated as independent frames.
        target
            Binary ground truth, same shape.
        valid
            1 where the target is a real observation, same shape.
        """
        pred = pred.astype(bool)
        target = target.astype(bool)
        valid = valid.astype(bool)

        p = pred & valid
        t = target & valid
        self.intersection += float((p & t).sum())
        self.union += float((p | t).sum())

        frames_pred = pred.reshape(-1, *pred.shape[-2:])
        frames_true = target.reshape(-1, *target.shape[-2:])
        frames_valid = valid.reshape(-1, *valid.shape[-2:])

        for fp_, ft_, fv_ in zip(frames_pred, frames_true, frames_valid):
            self._update_frame(fp_, ft_, fv_)
            self.n_frames += 1

    def _update_frame(self, pred: np.ndarray, target: np.ndarray, valid: np.ndarray) -> None:
        bank = bank_band(target, self.bank_width_px) & valid
        if bank.any():
            p = pred[bank]
            t = target[bank]
            self.tp += float((p & t).sum())
            self.fp += float((p & ~t).sum())
            self.fn += float((~p & t).sum())

        mde = boundary_displacement_m(pred, target, valid, self.resolution_m)
        if mde is not None:
            self.displacements.append(mde)

    # ------------------------------------------------------------------ read
    def compute(self) -> dict[str, float]:
        """Reduce the accumulated counts to the three reported numbers."""
        iou = self.intersection / self.union if self.union > 0 else float("nan")
        precision = self.tp / (self.tp + self.fp) if (self.tp + self.fp) > 0 else 0.0
        recall = self.tp / (self.tp + self.fn) if (self.tp + self.fn) > 0 else 0.0
        f1 = (
            2 * precision * recall / (precision + recall)
            if (precision + recall) > 0
            else 0.0
        )
        mde = float(np.mean(self.displacements)) if self.displacements else float("nan")
        mde_median = (
            float(np.median(self.displacements)) if self.displacements else float("nan")
        )
        return {
            "iou": iou,
            "bank_precision": precision,
            "bank_recall": recall,
            "bank_f1": f1,
            "mde_m": mde,
            "mde_median_m": mde_median,
            "n_frames": float(self.n_frames),
        }


def bank_band(mask: np.ndarray, width: int = 2) -> np.ndarray:
    """Pixels within ``width`` of the land/water boundary of ``mask``.

    Implemented as the difference between a dilation and an erosion of the
    water mask — the morphological gradient, thickened to ``width``. This is
    the region where a forecast can actually be wrong in an interesting way.

    Parameters
    ----------
    mask
        Binary water mask, ``(H, W)``.
    width
        Half-thickness of the band, pixels. At 120 m per pixel, ``width=2``
        is a 480 m-wide corridor around the shoreline.

    Returns
    -------
    np.ndarray
        Boolean ``(H, W)``.
    """
    mask = mask.astype(bool)
    if not mask.any() or mask.all():
        return np.zeros_like(mask, dtype=bool)
    structure = ndimage.generate_binary_structure(2, 1)
    dilated = ndimage.binary_dilation(mask, structure, iterations=width)
    # See boundary_pixels: border_value=1 keeps the tile rim out of the band.
    eroded = ndimage.binary_erosion(
        mask, structure, iterations=width, border_value=1
    )
    return dilated & ~eroded


def boundary_pixels(mask: np.ndarray) -> np.ndarray:
    """One-pixel-wide land/water boundary of a binary mask."""
    mask = mask.astype(bool)
    if not mask.any() or mask.all():
        return np.zeros_like(mask, dtype=bool)
    # border_value=1: the tile edge is an artefact of tiling, not a shoreline.
    # With the default border_value=0 the array border erodes away and the
    # whole tile rim is reported as bank, which drags every displacement
    # measurement towards zero.
    eroded = ndimage.binary_erosion(
        mask, ndimage.generate_binary_structure(2, 1), border_value=1
    )
    return mask & ~eroded


def boundary_displacement_m(
    pred: np.ndarray, target: np.ndarray, valid: np.ndarray, resolution_m: float
) -> float | None:
    """Symmetric mean distance between predicted and observed shorelines.

    For every pixel on the observed shoreline, measure the Euclidean distance
    to the nearest predicted shoreline pixel, and vice versa; average both
    directions and convert pixels to metres. Symmetrising matters: a model
    that predicts *no* bank at all would score perfectly on the one-directional
    version, because the set it is averaged over would be empty.

    Parameters
    ----------
    pred, target
        Binary water masks, ``(H, W)``.
    valid
        Observation mask, ``(H, W)``. Boundary pixels outside it are ignored.
    resolution_m
        Pixel edge length in metres — 120.0 on the canonical grid.

    Returns
    -------
    float or None
        Mean displacement in metres, or ``None`` when either frame has no
        shoreline inside the valid region (an all-water or all-land crop),
        where the quantity is undefined rather than zero.
    """
    pred_edge = boundary_pixels(pred) & valid.astype(bool)
    true_edge = boundary_pixels(target) & valid.astype(bool)
    if not pred_edge.any() or not true_edge.any():
        return None

    # distance_transform_edt measures distance to the nearest ZERO, so invert.
    dist_to_pred = ndimage.distance_transform_edt(~pred_edge)
    dist_to_true = ndimage.distance_transform_edt(~true_edge)

    forward = float(dist_to_pred[true_edge].mean())
    backward = float(dist_to_true[pred_edge].mean())
    return 0.5 * (forward + backward) * resolution_m


def erosion_map(current_water: np.ndarray, future_water: np.ndarray) -> np.ndarray:
    """Pixels that are land now and water in the forecast — i.e. predicted erosion.

    This is the bridge from Stage 3 to Stage 4: the polygons vectorised for the
    risk overlay are the connected components of this mask.

    Parameters
    ----------
    current_water, future_water
        Binary water masks on the same grid, ``(H, W)``.

    Returns
    -------
    np.ndarray
        Boolean ``(H, W)``, True where land becomes water.
    """
    return (~current_water.astype(bool)) & future_water.astype(bool)


def accretion_map(current_water: np.ndarray, future_water: np.ndarray) -> np.ndarray:
    """Pixels that are water now and land in the forecast — char formation.

    Reported alongside erosion because the Jamuna gives land back as well as
    taking it, and a study that counts only loss misstates the net position of
    the people living on it.
    """
    return current_water.astype(bool) & (~future_water.astype(bool))
