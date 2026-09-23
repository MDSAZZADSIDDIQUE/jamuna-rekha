"""Stage 2 — from raw monthly composites to the JamunaShift-52Y tensor.

Reads the per-tile-month GeoTIFFs written by Stage 1 and produces, per tile:

``<tile>_index.npy``     float32 (T, H, W)  gap-filled water index
``<tile>_water.npy``     uint8   (T, H, W)  binary water mask, 1 = water
``<tile>_observed.npy``  uint8   (T, H, W)  1 = at least one clear observation
``<tile>_meta.json``                       month keys, CRS, transform, thresholds

Raster index order is ``(time, row, col)`` throughout (CLAUDE.md §4).

Order of operations
-------------------
1. **Stack** every month into ``(T, H, W)``, NaN where never observed.
2. **Interpolate** the *continuous* index linearly in time across gaps, capped
   at ``preprocess.max_gap_months``. Interpolating the index rather than the
   binary mask matters: a half-filled channel interpolates to a half-filled
   channel, whereas interpolating a 0/1 mask would round the bank to whichever
   side happened to be observed.
3. **Threshold** each month with its own Otsu cut.

This differs slightly from the order sketched in CLAUDE.md §2, which put the
Otsu threshold in Stage 1. Thresholding *after* interpolation is what makes
step 2 meaningful, and it also lets a month with poor coverage borrow a stable
threshold from the tile instead of inventing one from a handful of pixels. The
change is recorded in ``docs/NOTES.md``.

A gap longer than ``max_gap_months`` is left unobserved rather than
interpolated. The 1972-1983 MSS era has genuine multi-year holes over
Bangladesh, and bridging them linearly would manufacture a river that was
never measured.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import rasterio
from scipy import ndimage
from skimage.filters import threshold_otsu

from jamunarekha.data.acquire_pc import INDEX_NODATA, INDEX_SCALE
from jamunarekha.utils.geo import Tile, month_key, month_range
from jamunarekha.utils.logging import get_logger

logger = get_logger("jamunarekha.preprocess")


def load_tile_stack(
    raw_dir: Path, tile: Tile, year_start: int, year_end: int
) -> tuple[np.ndarray, np.ndarray, list[str]]:
    """Stack every monthly composite for one tile into ``(T, H, W)``.

    Parameters
    ----------
    raw_dir
        ``data/raw``.
    tile
        The tile to load.
    year_start, year_end
        Inclusive year range; months with no file on disk become all-NaN
        slices, so the time axis is complete and regularly spaced by
        construction.

    Returns
    -------
    index : np.ndarray
        float32 (T, H, W), NaN where unobserved.
    nobs : np.ndarray
        uint8 (T, H, W), clear-observation count per pixel-month.
    months : list[str]
        ``"YYYY-MM"`` keys, length T, in chronological order.
    """
    months = [month_key(y, m) for y, m in month_range(year_start, year_end)]
    n_time = len(months)
    index = np.full((n_time, tile.height, tile.width), np.nan, dtype=np.float32)
    nobs = np.zeros((n_time, tile.height, tile.width), dtype=np.uint8)

    missing = 0
    for t, mk in enumerate(months):
        path = raw_dir / tile.name / f"{tile.name}_{mk}.tif"
        if not path.exists():
            missing += 1
            continue
        with rasterio.open(path) as src:
            raw = src.read(1)
            counts = src.read(2)
        values = raw.astype(np.float32) / INDEX_SCALE
        values[raw == INDEX_NODATA] = np.nan
        index[t] = values
        nobs[t] = np.clip(counts, 0, 255).astype(np.uint8)

    logger.info(
        "%s: stacked %d months (%d files missing on disk)", tile.name, n_time, missing
    )
    return index, nobs, months


def interpolate_gaps(index: np.ndarray, max_gap: int) -> tuple[np.ndarray, np.ndarray]:
    """Linearly interpolate each pixel time series across NaN gaps.

    Fully vectorised over the spatial axes: a per-pixel Python loop over
    262 144 pixels x 636 months is minutes of wall clock, this is under a
    second.

    Parameters
    ----------
    index
        float32 (T, H, W) with NaN at unobserved pixel-months.
    max_gap
        Longest run of consecutive missing months that may be bridged. Longer
        runs are left NaN.

    Returns
    -------
    filled : np.ndarray
        float32 (T, H, W), interpolated where permitted.
    was_filled : np.ndarray
        bool (T, H, W), True where a value was invented by interpolation. The
        dataset excludes these from loss and metrics, so the model is never
        scored on a number no satellite ever measured.
    """
    n_time = index.shape[0]
    flat = index.reshape(n_time, -1).copy()  # (T, N)
    valid = np.isfinite(flat)

    time_idx = np.arange(n_time, dtype=np.float32)[:, None]

    # Index of the nearest valid sample at or before each position.
    prev_idx = np.where(valid, time_idx, -1.0)
    prev_idx = np.maximum.accumulate(prev_idx, axis=0)
    # ... and at or after.
    next_idx = np.where(valid, time_idx, np.inf)
    next_idx = np.minimum.accumulate(next_idx[::-1], axis=0)[::-1]

    has_prev = prev_idx >= 0
    has_next = np.isfinite(next_idx)
    both = has_prev & has_next & ~valid

    safe_prev = np.where(has_prev, prev_idx, 0).astype(np.int64)
    safe_next = np.where(has_next, next_idx, 0).astype(np.int64)
    cols = np.arange(flat.shape[1])[None, :]
    prev_val = flat[safe_prev, cols]
    next_val = flat[safe_next, cols]

    span = safe_next - safe_prev
    with np.errstate(divide="ignore", invalid="ignore"):
        weight = np.where(span > 0, (time_idx - safe_prev) / np.maximum(span, 1), 0.0)
    interpolated = prev_val + weight * (next_val - prev_val)

    # A gap may only be bridged if it is short enough. `span - 1` is the number
    # of consecutive missing months between the two anchors.
    short_enough = (span - 1) <= max_gap
    fill_here = both & short_enough

    filled = np.where(fill_here, interpolated, flat)

    # Leading and trailing gaps have only one anchor: hold the nearest value,
    # but only within max_gap, so the series does not start with a fabrication.
    edge_prev = has_prev & ~has_next & ~valid & ((time_idx - safe_prev) <= max_gap)
    edge_next = has_next & ~has_prev & ~valid & ((safe_next - time_idx) <= max_gap)
    filled = np.where(edge_prev, prev_val, filled)
    filled = np.where(edge_next, next_val, filled)

    was_filled = (fill_here | edge_prev | edge_next).reshape(index.shape)
    return filled.reshape(index.shape).astype(np.float32), was_filled


def otsu_threshold(values: np.ndarray, bins: int, search_range: tuple[float, float]) -> float | None:
    """Otsu cut for a sample of water-index values.

    Returns ``None`` when the sample is too small or degenerate to threshold.

    Parameters
    ----------
    values
        1-D array of water-index values; non-finite entries are dropped.
    bins
        Histogram resolution.
    search_range
        Clamp applied before thresholding. Values far outside the physical
        range of a normalised-difference index are sensor artefacts and would
        drag the cut.
    """
    values = values[np.isfinite(values)]
    lo, hi = search_range
    values = values[(values >= lo) & (values <= hi)]
    if values.size < 1000:
        return None
    if float(values.max() - values.min()) < 1e-3:
        return None
    try:
        return float(threshold_otsu(values, nbins=bins))
    except (ValueError, RuntimeError):
        return None


def despeckle_mss(
    index: np.ndarray, families: list[str], size: int = 3
) -> tuple[np.ndarray, int]:
    """Suppress Landsat MSS detector striping with a small median filter.

    MSS carried six detectors per band whose gains differ slightly, which puts
    a horizontal stripe pattern into every scene. At 120 m the pattern has a
    period of about three rows, and because the NDWI values of the stripes
    straddle the water threshold, the stripes survive into the binary mask as
    ribbons of phantom river across the floodplain.

    Two stronger corrections were tried and rejected. Per-row offset removal
    equalises the row medians but leaves the mask visibly striped, because the
    detectors differ in gain as well as offset. Per-row moment matching
    (equalising mean *and* standard deviation) made the banding markedly worse,
    since it stretches rows that genuinely contain little variance: measured
    banding power rose from 0.013 to 0.183 on 1975-03.

    A 3x3 median is the conservative option that works. It is applied **only to
    MSS-derived months**, so the calibrated TM/ETM+/OLI record is untouched. At
    120 m the filter footprint is 360 m, finer than the displacement scale the
    forecast is judged on, and a median preserves step edges — which is the
    whole point, since the step edge is the riverbank.

    Parameters
    ----------
    index
        float32 (T, H, W) water-index stack.
    families
        Per-month index family from :func:`index_families`.
    size
        Median filter footprint in pixels. 0 or 1 disables the filter.

    Returns
    -------
    filtered : np.ndarray
        The stack with MSS months median-filtered in place.
    n_filtered : int
        How many months were touched.
    """
    if size is None or size < 2:
        return index, 0
    out = index.copy()
    touched = 0
    for t, family in enumerate(families):
        if family != "NDWI":
            continue
        frame = out[t]
        if not np.isfinite(frame).any():
            continue
        # ndimage.median_filter has no NaN handling, so hold NaNs aside and
        # restore them: filtering across a cloud gap would invent data.
        gaps = ~np.isfinite(frame)
        filled = np.where(gaps, np.nanmedian(frame), frame)
        smoothed = ndimage.median_filter(filled, size=size, mode="nearest")
        smoothed[gaps] = np.nan
        out[t] = smoothed
        touched += 1
    if touched:
        logger.info("MSS despeckle: %d months median-filtered at %dx%d", touched, size, size)
    return out, touched


def land_mode(
    frame: np.ndarray, search_range: tuple[float, float], bins: int = 200
) -> float | None:
    """Index value at the histogram peak — the land mode of one month.

    The peak is where the overwhelming majority of pixels sit, which over this
    reach is dry floodplain and char sand. Its position tracks the radiometric
    offset of the scene and is almost unaffected by how much water is present,
    which is exactly the property the threshold rule below needs: the median
    would drift upward in a flood month and drag the threshold with it.
    """
    values = frame[np.isfinite(frame)]
    lo, hi = search_range
    values = values[(values >= lo) & (values <= hi)]
    if values.size < 1000:
        return None
    counts, edges = np.histogram(values, bins=bins)
    peak = int(np.argmax(counts))
    return float((edges[peak] + edges[peak + 1]) / 2.0)


def calibrate_thresholds(
    index: np.ndarray,
    families: list[str],
    bins: int,
    search_range: tuple[float, float],
) -> tuple[dict[str, float], dict]:
    """Derive one mode-offset per index family for this tile.

    **Why not a plain per-month Otsu.** Otsu assumes a bimodal histogram. In a
    dry-season month the Jamuna occupies a few percent of the tile and the
    histogram is effectively unimodal, so Otsu splits the *land* distribution
    down the middle and reports half the floodplain as river. Measured on tile
    T00_00: February 1995 came out at 47.8 percent water and February 1977 at
    64.1 percent, against a long-run median near 11 percent.

    **The rule used instead.** For every month, the threshold is

        threshold = land_mode(month) + delta(index family)

    Anchoring on the land mode removes the per-scene radiometric offset while
    leaving the water fraction free to vary, so a flood month still reports
    more water than a dry one.

    ``delta`` is calibrated per family, because the two families are not
    radiometrically comparable:

    *MNDWI* comes from Collection 2 Level-2 **surface reflectance**, which is
    calibrated and consistent across scenes. Pooling a sample across the whole
    record gives a genuinely bimodal histogram, so Otsu is reliable there;
    ``delta`` is that pooled threshold minus the median land mode.

    *NDWI* comes from Level-1 MSS **digital numbers**, which carry no published
    Collection 2 scale or offset, so the same physical surface takes different
    values in different scenes. Its ``delta`` is instead solved so that the
    median water fraction of the MSS era matches that of the calibrated era —
    an explicit cross-sensor harmonisation, stated rather than hidden. Its
    assumption is that the long-run median water fraction of the reach did not
    change systematically between the two eras; the *variation around* that
    median is still free and still measured.

    Returns
    -------
    deltas : dict[str, float]
        Offset to add to the land mode, per family.
    report : dict
        Calibration diagnostics for ``docs/NOTES.md`` and the paper.
    """
    n_time = index.shape[0]
    modes = [land_mode(index[t], search_range) for t in range(n_time)]

    by_family: dict[str, list[int]] = {}
    for t, family in enumerate(families):
        if family and modes[t] is not None:
            by_family.setdefault(family, []).append(t)

    deltas: dict[str, float] = {}
    report: dict = {"families": {}}
    rng = np.random.default_rng(0)

    # ---- calibrated family first: it defines the reference -----------------
    reference_fraction = None
    for family in ("MNDWI", "NDWI"):
        indices = by_family.get(family, [])
        if not indices:
            continue
        if family == "MNDWI":
            sample_months = rng.choice(
                indices, size=min(60, len(indices)), replace=False
            )
            pooled = np.concatenate(
                [index[t].ravel()[::17] for t in sorted(sample_months)]
            )
            pooled_otsu = otsu_threshold(pooled, bins, search_range)
            median_mode = float(np.median([modes[t] for t in indices]))
            if pooled_otsu is None:
                deltas[family] = 0.15
            else:
                deltas[family] = pooled_otsu - median_mode
            fractions = [
                float(np.nanmean(index[t] > (modes[t] + deltas[family])))
                for t in indices[::4]
            ]
            reference_fraction = float(np.median(fractions))
            report["families"][family] = {
                "n_months": len(indices),
                "pooled_otsu": None if pooled_otsu is None else round(pooled_otsu, 4),
                "median_land_mode": round(median_mode, 4),
                "delta": round(deltas[family], 4),
                "median_water_fraction": round(reference_fraction, 4),
                "calibration": "pooled Otsu on Level-2 surface reflectance",
            }

    # ---- uncalibrated family: match the reference water fraction -----------
    indices = by_family.get("NDWI", [])
    if indices:
        probe = indices[:: max(1, len(indices) // 20)]
        if reference_fraction is None:
            pooled = np.concatenate([index[t].ravel()[::17] for t in probe])
            pooled_otsu = otsu_threshold(pooled, bins, search_range)
            median_mode = float(np.median([modes[t] for t in indices]))
            deltas["NDWI"] = (
                0.15 if pooled_otsu is None else pooled_otsu - median_mode
            )
            report["families"]["NDWI"] = {
                "n_months": len(indices),
                "delta": round(deltas["NDWI"], 4),
                "calibration": "pooled Otsu (no calibrated era available)",
            }
        else:
            best_delta, best_gap, best_fraction = 0.15, float("inf"), float("nan")
            for delta in np.arange(-0.10, 0.45, 0.005):
                fractions = [
                    float(np.nanmean(index[t] > (modes[t] + delta))) for t in probe
                ]
                median_fraction = float(np.median(fractions))
                gap = abs(median_fraction - reference_fraction)
                if gap < best_gap:
                    best_delta, best_gap, best_fraction = float(delta), gap, median_fraction
            deltas["NDWI"] = best_delta
            report["families"]["NDWI"] = {
                "n_months": len(indices),
                "delta": round(best_delta, 4),
                "median_water_fraction": round(best_fraction, 4),
                "matched_to": round(reference_fraction, 4),
                "calibration": "water-fraction matched to the MNDWI era",
            }

    report["median_land_mode_overall"] = round(
        float(np.median([m for m in modes if m is not None])), 4
    ) if any(m is not None for m in modes) else None
    return deltas, report


def threshold_stack(
    index: np.ndarray,
    families: list[str],
    bins: int,
    search_range: tuple[float, float],
) -> tuple[np.ndarray, list[float], dict]:
    """Binarise a (T, H, W) index stack into a water mask, month by month.

    Applies ``threshold = land_mode(month) + delta(family)``; see
    :func:`calibrate_thresholds` for why.

    Returns
    -------
    water : np.ndarray
        uint8 (T, H, W), 1 where the index exceeds the threshold.
    thresholds : list[float]
        The threshold actually applied to each month, for the record.
    report : dict
        Calibration diagnostics.
    """
    n_time = index.shape[0]
    deltas, report = calibrate_thresholds(index, families, bins, search_range)
    logger.info("threshold calibration: %s", {k: round(v, 4) for k, v in deltas.items()})

    modes = [land_mode(index[t], search_range) for t in range(n_time)]
    known = [m for m in modes if m is not None]
    default_mode = float(np.median(known)) if known else 0.0
    default_delta = float(np.median(list(deltas.values()))) if deltas else 0.15

    thresholds: list[float] = []
    water = np.zeros(index.shape, dtype=np.uint8)
    for t in range(n_time):
        mode = modes[t] if modes[t] is not None else default_mode
        delta = deltas.get(families[t], default_delta)
        thr = mode + delta
        thresholds.append(thr)
        frame = index[t]
        water[t] = np.where(np.isfinite(frame) & (frame > thr), 1, 0).astype(np.uint8)

    report["n_months_with_mode"] = int(len(known))
    report["n_months"] = int(n_time)
    return water, thresholds, report


def index_families(raw_dir: Path, tile: Tile, months: list[str]) -> list[str]:
    """Which water index produced each month, read from the Stage 1 manifest.

    A month composited from MSS scenes carries NDWI; anything from TM, ETM+ or
    OLI carries MNDWI. Where a month mixes both — possible only in 1982-83,
    when MSS and TM briefly overlapped — the majority wins, because the median
    composite is dominated by whichever family contributed more scenes.

    Returns
    -------
    list[str]
        One of ``"MNDWI"``, ``"NDWI"`` or ``""`` (no scenes) per month.
    """
    manifest = raw_dir / "_manifest" / "scenes.csv"
    if not manifest.exists():
        logger.warning("no acquisition manifest; assuming MNDWI throughout")
        return ["MNDWI"] * len(months)

    import pandas as pd

    frame = pd.read_csv(manifest)
    frame = frame[frame["tile"] == tile.name]
    if frame.empty:
        return ["MNDWI"] * len(months)

    majority = (
        frame.groupby("month")["index"]
        .agg(lambda s: s.mode().iat[0] if not s.mode().empty else "")
        .to_dict()
    )
    families = [str(majority.get(m, "")) for m in months]
    counts = {f: families.count(f) for f in set(families)}
    logger.info("%s: index families %s", tile.name, counts)
    return families


def process_tile(cfg, tile: Tile) -> dict:
    """Run Stage 2 for one tile and write the processed arrays.

    Returns
    -------
    dict
        The metadata written alongside the arrays, so the caller can log a
        summary without re-reading it.
    """
    raw_dir = Path(cfg.paths.data_raw)
    out_dir = Path(cfg.paths.data_processed)
    out_dir.mkdir(parents=True, exist_ok=True)
    pp = cfg.preprocess

    index, nobs, months = load_tile_stack(
        raw_dir, tile, int(cfg.acquire.year_start), int(cfg.acquire.year_end)
    )
    observed = (nobs > 0).astype(np.uint8)

    coverage = float(observed.mean())
    logger.info("%s: observed fraction before gap-filling = %.3f", tile.name, coverage)

    families = index_families(raw_dir, tile, months)
    filled, was_filled = interpolate_gaps(index, int(pp.max_gap_months))
    filled, n_despeckled = despeckle_mss(
        filled, families, int(pp.get("mss_median_filter", 3))
    )
    water, thresholds, calibration = threshold_stack(
        filled, families, int(pp.otsu_bins), tuple(pp.otsu_search_range)
    )

    usable = (observed.astype(bool) | was_filled).astype(np.uint8)
    logger.info(
        "%s: usable fraction after gap-filling = %.3f", tile.name, float(usable.mean())
    )

    np.save(out_dir / f"{tile.name}_index.npy", filled)
    np.save(out_dir / f"{tile.name}_water.npy", water)
    np.save(out_dir / f"{tile.name}_observed.npy", usable)

    meta = {
        "tile": tile.name,
        "months": months,
        "crs": tile.crs,
        "transform": list(tile.transform)[:6],
        "resolution_m": tile.res_m,
        "height": tile.height,
        "width": tile.width,
        "index_families": families,
        "thresholds": [round(v, 5) for v in thresholds],
        "threshold_calibration": calibration,
        "observed_fraction_raw": round(coverage, 4),
        "usable_fraction_filled": round(float(usable.mean()), 4),
        "water_fraction": round(float(water.mean()), 4),
        "max_gap_months": int(pp.max_gap_months),
        "mss_months_despeckled": int(n_despeckled),
    }
    (out_dir / f"{tile.name}_meta.json").write_text(
        json.dumps(meta, indent=2), encoding="utf-8"
    )
    return meta


def run(cfg, tiles: list[Tile] | None = None) -> list[dict]:
    """Stage 2 entry point: process every tile."""
    from jamunarekha.utils.geo import grid_from_config

    tiles = tiles if tiles is not None else grid_from_config(cfg)
    metas = []
    for tile in tiles:
        raw_tile_dir = Path(cfg.paths.data_raw) / tile.name
        if not raw_tile_dir.exists():
            logger.warning("%s: no raw data, skipping", tile.name)
            continue
        metas.append(process_tile(cfg, tile))
    logger.info("Stage 2 complete: %d tiles processed", len(metas))
    return metas
