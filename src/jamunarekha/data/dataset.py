"""``JamunaShift-52Y`` — the PyTorch Dataset for Stage 3.

One sample is a sliding window over the monthly water-mask series of one tile:

    x        float32 (T_in,  1, H, W)   12 observed monthly water masks
    y        float32 (T_out, 1, H, W)   the next 3 monthly water masks
    y_valid  float32 (T_out, 1, H, W)   1 where y came from a real observation

``y_valid`` is the honest part. Stage 2 interpolates across cloud gaps, and a
model scored on interpolated targets is being graded against its own input
assumptions. Loss and metrics are masked by ``y_valid``, so the model is only
ever rewarded for predicting something a satellite actually saw.

Arrays are index-ordered ``(time, row, col)`` on disk and memory-mapped, so a
636-month tile costs no resident memory until a window is touched.

Splits are **temporal, not random**: train 1972-2011, validate 2012-2017, test
2018-2024. A random split would leak, because consecutive months of a river are
near-duplicates; a model could memorise 2019-03 from 2019-02 and look
excellent while having learned nothing about forecasting.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import torch
from torch.utils.data import Dataset

from jamunarekha.utils.logging import get_logger

logger = get_logger("jamunarekha.dataset")

SPLITS = ("train", "val", "test")


@dataclass(frozen=True)
class Window:
    """One training sample: a tile, a start month, and a spatial crop origin."""

    tile: str
    t0: int          # index of the first input frame
    row: int         # crop origin, pixels
    col: int


class JamunaShift52Y(Dataset):
    """Monthly Jamuna water masks, 1972-2024, as a sequence-forecasting dataset.

    Parameters
    ----------
    processed_dir
        Directory holding ``<tile>_water.npy`` etc. from Stage 2.
    split
        ``"train"``, ``"val"`` or ``"test"``.
    in_frames, out_frames
        Window lengths in months. Defaults match the proposal: 12 in, 3 out.
    crop_size
        Spatial crop edge in pixels. 512 for the full model, 256 for local
        debugging.
    train_end_year, val_end_year
        Temporal split boundaries, inclusive.
    min_observed
        A window is kept only if this fraction of its *target* frames is real
        observation rather than interpolation. Windows below it are dropped
        entirely rather than down-weighted, which keeps the metric denominators
        interpretable.
    window_stride
        Months between consecutive window start points. Neighbouring windows
        share 11 of their 12 input frames, so a stride of 1 mostly re-presents
        the same sequence and multiplies epoch time for very little extra
        information. 1 on the A100, larger locally. Applied to training only —
        validation and test always use stride 1, so the evaluation set is the
        complete set of forecastable months and the reported metrics are not a
        function of this setting.
    random_crop
        True for training (random crop origin each epoch), False for val/test
        (a fixed grid of crops, so the evaluation set is identical every run).
    seed
        Seed for the crop sampler.
    """

    def __init__(
        self,
        processed_dir: Path | str,
        split: str,
        in_frames: int = 12,
        out_frames: int = 3,
        crop_size: int = 512,
        train_end_year: int = 2011,
        val_end_year: int = 2017,
        min_observed: float = 0.30,
        window_stride: int = 1,
        max_windows: int | None = None,
        random_crop: bool | None = None,
        seed: int = 1972,
    ) -> None:
        if split not in SPLITS:
            raise ValueError(f"split must be one of {SPLITS}, got {split!r}")
        self.dir = Path(processed_dir)
        self.split = split
        self.in_frames = in_frames
        self.out_frames = out_frames
        self.crop_size = crop_size
        self.min_observed = min_observed
        self.window_stride = max(1, int(window_stride)) if split == "train" else 1
        self.random_crop = (split == "train") if random_crop is None else random_crop
        self.rng = np.random.default_rng(seed + SPLITS.index(split))

        self._water: dict[str, np.ndarray] = {}
        self._observed: dict[str, np.ndarray] = {}
        self._meta: dict[str, dict] = {}

        metas = sorted(self.dir.glob("*_meta.json"))
        if not metas:
            raise FileNotFoundError(
                f"no processed tiles in {self.dir}. Run Stage 2 first."
            )
        for meta_path in metas:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            tile = meta["tile"]
            self._meta[tile] = meta
            self._water[tile] = np.load(self.dir / f"{tile}_water.npy", mmap_mode="r")
            self._observed[tile] = np.load(
                self.dir / f"{tile}_observed.npy", mmap_mode="r"
            )

        self.windows = self._build_windows(train_end_year, val_end_year)

        # Validation runs after every epoch, so its cost is multiplied by the
        # epoch count. Capping it keeps that cost bounded; the subsample is
        # drawn with a fixed seed and evenly spaced, so it is identical between
        # runs and still spans the whole validation period. The test split is
        # never capped — it runs once and must be complete.
        if max_windows and split == "val" and len(self.windows) > max_windows:
            step = len(self.windows) / max_windows
            picks = [int(i * step) for i in range(max_windows)]
            self.windows = [self.windows[i] for i in picks]
            logger.info("val split subsampled to %d windows", len(self.windows))

        logger.info(
            "JamunaShift-52Y[%s]: %d windows over %d tiles, crop %d",
            split, len(self.windows), len(self._meta), crop_size,
        )

    # ------------------------------------------------------------------ setup
    def _split_bounds(self, months: list[str], train_end: int, val_end: int) -> tuple[int, int]:
        """Return the (start, stop) month indices belonging to this split."""
        years = np.array([int(m[:4]) for m in months])
        if self.split == "train":
            keep = years <= train_end
        elif self.split == "val":
            keep = (years > train_end) & (years <= val_end)
        else:
            keep = years > val_end
        idx = np.flatnonzero(keep)
        if idx.size == 0:
            return 0, 0
        return int(idx[0]), int(idx[-1]) + 1

    def _build_windows(self, train_end: int, val_end: int) -> list[Window]:
        """Enumerate every usable (tile, start month, crop) combination.

        A window is usable when it fits inside the split, fits inside the tile,
        and its target frames are sufficiently observed.
        """
        span = self.in_frames + self.out_frames
        windows: list[Window] = []

        for tile, meta in self._meta.items():
            months: list[str] = meta["months"]
            start, stop = self._split_bounds(months, train_end, val_end)
            if stop - start < span:
                continue

            observed = self._observed[tile]
            height, width = meta["height"], meta["width"]
            if height < self.crop_size or width < self.crop_size:
                logger.warning(
                    "%s is %dx%d, smaller than crop %d — skipped",
                    tile, height, width, self.crop_size,
                )
                continue

            # Validation and test enumerate a deterministic, half-overlapping
            # crop grid so the evaluation set is byte-identical between runs.
            #
            # Training emits ONE window per start month instead. Its crop
            # origin is redrawn at random in __getitem__ anyway, so listing
            # nine positions would not add data — it would silently multiply
            # the epoch length by nine while presenting the same windows.
            if self.random_crop:
                rows, cols = [0], [0]
            else:
                # Non-overlapping crops. A half-overlapping grid quadruples the
                # evaluation set for no extra information — at crop 128 on a
                # 512 px tile it is 49 crops per window instead of 16, which
                # turns a per-epoch validation pass into the dominant cost of
                # training. Tiling exactly once still covers every pixel.
                stride = self.crop_size
                rows = list(range(0, height - self.crop_size + 1, stride)) or [0]
                cols = list(range(0, width - self.crop_size + 1, stride)) or [0]

            for t0 in range(start, stop - span + 1, self.window_stride):
                target_slice = observed[t0 + self.in_frames : t0 + span]
                if float(np.asarray(target_slice).mean()) < self.min_observed:
                    continue
                for row in rows:
                    for col in cols:
                        windows.append(Window(tile, t0, row, col))
        return windows

    # ------------------------------------------------------------- torch API
    def __len__(self) -> int:
        return len(self.windows)

    def __getitem__(self, index: int) -> dict[str, torch.Tensor]:
        window = self.windows[index]
        meta = self._meta[window.tile]
        size = self.crop_size

        if self.random_crop:
            max_row = meta["height"] - size
            max_col = meta["width"] - size
            row = int(self.rng.integers(0, max_row + 1)) if max_row > 0 else 0
            col = int(self.rng.integers(0, max_col + 1)) if max_col > 0 else 0
        else:
            row, col = window.row, window.col

        t0 = window.t0
        t_mid = t0 + self.in_frames
        t_end = t0 + self.in_frames + self.out_frames

        water = self._water[window.tile]
        observed = self._observed[window.tile]

        x = np.asarray(water[t0:t_mid, row : row + size, col : col + size], dtype=np.float32)
        y = np.asarray(water[t_mid:t_end, row : row + size, col : col + size], dtype=np.float32)
        y_valid = np.asarray(
            observed[t_mid:t_end, row : row + size, col : col + size], dtype=np.float32
        )

        # (T, H, W) -> (T, 1, H, W): an explicit channel axis, because the model
        # contract is (B, T, C, H, W) and a squeezed axis is a silent bug waiting.
        return {
            "x": torch.from_numpy(x).unsqueeze(1),
            "y": torch.from_numpy(y).unsqueeze(1),
            "y_valid": torch.from_numpy(y_valid).unsqueeze(1),
            "tile": window.tile,
            "t0": t0,
            "month": meta["months"][t_mid],
        }

    # ------------------------------------------------------------- utilities
    def positive_weight(self, sample_limit: int = 64) -> float:
        """Estimate ``pos_weight`` for BCE from the class balance of the targets.

        Bank pixels are a small minority of the frame and unweighted BCE
        collapses to "predict land everywhere", so this ratio is what keeps the
        loss honest. Estimated from a sample rather than the full tensor
        because the full tensor is gigabytes.
        """
        if not self.windows:
            return 1.0
        picks = self.rng.choice(
            len(self.windows), size=min(sample_limit, len(self.windows)), replace=False
        )
        total = positives = 0.0
        for i in picks:
            item = self[int(i)]
            valid = item["y_valid"]
            total += float(valid.sum())
            positives += float((item["y"] * valid).sum())
        if positives <= 0:
            return 1.0
        return float((total - positives) / positives)

    def tile_meta(self, tile: str) -> dict:
        """Geo-metadata for one tile: CRS, transform, months, thresholds."""
        return self._meta[tile]

    @property
    def tiles(self) -> list[str]:
        return sorted(self._meta)
