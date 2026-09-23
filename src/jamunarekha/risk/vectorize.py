"""Stage 4a — turn a predicted erosion raster into polygons.

The model emits a probability mask per forecast month. Erosion is the set of
pixels that are **land now and water in the forecast**; accretion is the
reverse. Both are vectorised, because a union parishad that gains a char and
one that loses a village should not be reported as the same event.

Everything here stays in the metric CRS (EPSG:32645) so that areas come out in
square metres without a projection step. The conversion to EPSG:4326 happens
once, at the end, only for the Folium map and the Overpass query, both of which
speak degrees.
"""

from __future__ import annotations

import numpy as np
import geopandas as gpd
from affine import Affine
from rasterio import features
from shapely.geometry import shape

from jamunarekha.utils.logging import get_logger

logger = get_logger("jamunarekha.vectorize")


def mask_to_polygons(
    mask: np.ndarray,
    transform: Affine,
    crs: str,
    min_area_m2: float = 10_000.0,
    simplify_m: float = 30.0,
    label: str = "erosion",
) -> gpd.GeoDataFrame:
    """Vectorise a boolean raster mask into polygons.

    Parameters
    ----------
    mask
        Boolean ``(H, W)``. True pixels become polygon interiors.
    transform
        Affine transform of the raster, in ``crs``.
    crs
        Metric CRS of the raster, e.g. ``"EPSG:32645"``.
    min_area_m2
        Polygons smaller than this are dropped. The default of 10 000 m²
        (1 hectare) removes single-pixel speckle: at 120 m a lone pixel is
        14 400 m², so this keeps isolated pixels only where they cluster.
    simplify_m
        Douglas-Peucker tolerance in metres. A quarter of a pixel — enough to
        drop the staircase edge without moving the bank.
    label
        Value written to the ``kind`` column.

    Returns
    -------
    gpd.GeoDataFrame
        Columns ``kind``, ``area_m2``, ``area_ha``, ``geometry``. Empty (but
        correctly typed and projected) when nothing survives the filters.
    """
    mask = np.asarray(mask, dtype=bool)
    if not mask.any():
        return gpd.GeoDataFrame(
            {"kind": [], "area_m2": [], "area_ha": []},
            geometry=[],
            crs=crs,
        )

    shapes = features.shapes(
        mask.astype(np.uint8), mask=mask, transform=transform, connectivity=8
    )
    geometries = []
    for geom, value in shapes:
        if value != 1:
            continue
        polygon = shape(geom)
        if simplify_m > 0:
            polygon = polygon.simplify(simplify_m, preserve_topology=True)
        if polygon.is_empty or not polygon.is_valid:
            polygon = polygon.buffer(0)
        if polygon.is_empty:
            continue
        if polygon.area < min_area_m2:
            continue
        geometries.append(polygon)

    gdf = gpd.GeoDataFrame(
        {"kind": [label] * len(geometries)}, geometry=geometries, crs=crs
    )
    if not gdf.empty:
        gdf["area_m2"] = gdf.geometry.area
        gdf["area_ha"] = gdf["area_m2"] / 10_000.0
    else:
        gdf["area_m2"] = []
        gdf["area_ha"] = []

    logger.info(
        "%s: %d polygons, %.1f ha total",
        label, len(gdf), float(gdf["area_ha"].sum()) if not gdf.empty else 0.0,
    )
    return gdf


def change_polygons(
    current_water: np.ndarray,
    future_water: np.ndarray,
    transform: Affine,
    crs: str,
    min_area_m2: float = 10_000.0,
    simplify_m: float = 30.0,
) -> gpd.GeoDataFrame:
    """Erosion and accretion polygons from a pair of water masks.

    Parameters
    ----------
    current_water, future_water
        Binary water masks on the same grid, ``(H, W)``. ``current`` is the
        last observed month, ``future`` is the forecast.
    transform, crs
        Georeferencing of both rasters.
    min_area_m2, simplify_m
        Passed through to :func:`mask_to_polygons`.

    Returns
    -------
    gpd.GeoDataFrame
        Erosion and accretion polygons stacked, with a ``kind`` column
        distinguishing them.
    """
    from jamunarekha.models.metrics import accretion_map, erosion_map

    erosion = mask_to_polygons(
        erosion_map(current_water, future_water),
        transform, crs, min_area_m2, simplify_m, label="erosion",
    )
    accretion = mask_to_polygons(
        accretion_map(current_water, future_water),
        transform, crs, min_area_m2, simplify_m, label="accretion",
    )
    combined = gpd.GeoDataFrame(
        __import__("pandas").concat([erosion, accretion], ignore_index=True),
        crs=crs,
    )
    return combined
