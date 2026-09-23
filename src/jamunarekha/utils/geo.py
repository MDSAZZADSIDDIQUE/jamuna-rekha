"""Geospatial helpers: the canonical analysis grid and CRS bookkeeping.

**CRS discipline (CLAUDE.md §4).** The study area is *defined* in EPSG:4326
(degrees) because that is how the proposal states it. Every raster operation
after that happens in ``study_area.target_crs`` — EPSG:32645, UTM zone 45N —
which is metric. Mean Displacement Error is reported in **metres**, and that
number is meaningless in a degree CRS, so the conversion happens once, here,
and never silently anywhere else.

**Raster index order.** All raster stacks in this project are indexed
``(time, band, row, col)``. Single-band stacks are ``(time, row, col)``.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Iterator

from affine import Affine
from pyproj import Transformer
from rasterio.coords import BoundingBox

WGS84 = "EPSG:4326"


@dataclass(frozen=True)
class Tile:
    """One 512x512 analysis tile on the canonical grid.

    Attributes
    ----------
    name
        Stable identifier, e.g. ``"T00_01"`` == (row 0, col 1). Used in every
        filename under ``data/raw/`` so a tile can be traced back to a
        geographic footprint without opening the file.
    col, row
        Tile indices on the lattice, counted from the north-west corner.
    transform
        Affine transform mapping (col, row) pixel indices to ``crs`` coordinates.
    width, height
        Size in pixels. Always ``tile_size`` x ``tile_size``.
    crs
        The metric CRS these coordinates are in, e.g. ``"EPSG:32645"``.
    res_m
        Pixel edge length in metres.
    """

    name: str
    col: int
    row: int
    transform: Affine
    width: int
    height: int
    crs: str
    res_m: float

    @property
    def bounds(self) -> BoundingBox:
        """Tile extent in ``crs`` units (metres): (left, bottom, right, top)."""
        left, top = self.transform @ (0, 0)
        right, bottom = self.transform @ (self.width, self.height)
        return BoundingBox(left, bottom, right, top)

    def bounds_wgs84(self) -> tuple[float, float, float, float]:
        """Tile extent as (min_lon, min_lat, max_lon, max_lat) in degrees.

        Used for STAC queries and Overpass bounding boxes, both of which speak
        EPSG:4326 only.
        """
        tf = Transformer.from_crs(self.crs, WGS84, always_xy=True)
        left, bottom, right, top = self.bounds
        xs, ys = [], []
        for x, y in ((left, bottom), (left, top), (right, bottom), (right, top)):
            lon, lat = tf.transform(x, y)
            xs.append(lon)
            ys.append(lat)
        return min(xs), min(ys), max(xs), max(ys)


def bbox_to_crs(
    bbox_wgs84: tuple[float, float, float, float], target_crs: str
) -> tuple[float, float, float, float]:
    """Project a lon/lat bounding box into ``target_crs``.

    All four corners are transformed (not just two) because the projection is
    not axis-aligned — taking only SW and NE corners silently clips the box.

    Parameters
    ----------
    bbox_wgs84
        ``(min_lon, min_lat, max_lon, max_lat)`` in degrees, EPSG:4326.
    target_crs
        A metric CRS, e.g. ``"EPSG:32645"``.

    Returns
    -------
    tuple
        ``(left, bottom, right, top)`` in ``target_crs`` units (metres).
    """
    min_lon, min_lat, max_lon, max_lat = bbox_wgs84
    tf = Transformer.from_crs(WGS84, target_crs, always_xy=True)
    xs, ys = [], []
    # Sample the edges, not just the corners: the meridian/parallel edges bow
    # under projection and the extreme x/y can sit mid-edge.
    steps = 25
    for i in range(steps + 1):
        f = i / steps
        lon = min_lon + f * (max_lon - min_lon)
        lat = min_lat + f * (max_lat - min_lat)
        for pt in ((lon, min_lat), (lon, max_lat), (min_lon, lat), (max_lon, lat)):
            x, y = tf.transform(*pt)
            xs.append(x)
            ys.append(y)
    return min(xs), min(ys), max(xs), max(ys)


def study_grid(
    bbox_wgs84: tuple[float, float, float, float],
    target_crs: str,
    resolution_m: float,
    tile_size: int,
) -> list[Tile]:
    """Build the canonical tile lattice covering the study bounding box.

    The projected bounding box is snapped *outward* to a whole number of
    ``tile_size`` x ``resolution_m`` tiles, aligned to a lattice anchored on a
    multiple of the tile edge. Snapping outward guarantees full coverage;
    anchoring to a fixed lattice guarantees that re-running with a different
    year range produces pixel-identical grids.

    Parameters
    ----------
    bbox_wgs84
        Study area ``(min_lon, min_lat, max_lon, max_lat)``, degrees.
    target_crs
        Metric CRS for the output grid.
    resolution_m
        Square pixel edge, metres.
    tile_size
        Tile edge, pixels.

    Returns
    -------
    list[Tile]
        Row-major order, north-west first.
    """
    left, bottom, right, top = bbox_to_crs(bbox_wgs84, target_crs)
    tile_m = resolution_m * tile_size

    grid_left = math.floor(left / tile_m) * tile_m
    grid_top = math.ceil(top / tile_m) * tile_m
    n_cols = max(1, math.ceil((right - grid_left) / tile_m))
    n_rows = max(1, math.ceil((grid_top - bottom) / tile_m))

    tiles: list[Tile] = []
    for r in range(n_rows):
        for c in range(n_cols):
            origin_x = grid_left + c * tile_m
            origin_y = grid_top - r * tile_m
            transform = Affine(resolution_m, 0.0, origin_x, 0.0, -resolution_m, origin_y)
            tiles.append(
                Tile(
                    name=f"T{r:02d}_{c:02d}",
                    col=c,
                    row=r,
                    transform=transform,
                    width=tile_size,
                    height=tile_size,
                    crs=target_crs,
                    res_m=resolution_m,
                )
            )
    return tiles


def grid_from_config(cfg) -> list[Tile]:
    """Convenience wrapper: build the grid straight from a loaded config."""
    sa = cfg.study_area
    return study_grid(
        bbox_wgs84=tuple(sa.bbox_wgs84),
        target_crs=sa.target_crs,
        resolution_m=float(sa.resolution_m),
        tile_size=int(sa.tile_size),
    )


def month_range(year_start: int, year_end: int) -> Iterator[tuple[int, int]]:
    """Yield ``(year, month)`` inclusive of both endpoint years."""
    for year in range(year_start, year_end + 1):
        for month in range(1, 13):
            yield year, month


def month_key(year: int, month: int) -> str:
    """Canonical ``"YYYY-MM"`` key used in filenames and dataset indices."""
    return f"{year:04d}-{month:02d}"


def shift_month(key: str, months: int) -> str:
    """Advance (or rewind) a ``"YYYY-MM"`` key by a number of months.

    Needed because a genuine forecast runs *past the end of the data*. Looking
    the horizon up by index into the observed month list silently clamps it to
    the last available month, so a three-month forecast made from December 2024
    would be labelled December 2024 rather than March 2025 — a warning stamped
    with the wrong date, which is worse than no warning.

    Parameters
    ----------
    key
        ``"YYYY-MM"``.
    months
        Offset in months; negative rewinds.

    Returns
    -------
    str
        The shifted ``"YYYY-MM"`` key.
    """
    year, month = int(key[:4]), int(key[5:7])
    index = year * 12 + (month - 1) + months
    return month_key(index // 12, index % 12 + 1)
