"""Stage 4b — OpenStreetMap building footprints via the Overpass API.

Counting buildings inside a predicted erosion polygon is what turns a raster
forecast into a sentence a disaster officer can act on: *this union loses this
many homesteads*. The footprints come from OSM through Overpass.

Two things keep this honest:

**Centroids, not footprints.** ``out center`` returns one point per building
instead of its full outline. For an inside/outside count a centroid is exactly
the right primitive, and it cuts the response size by an order of magnitude on
a query that already risks timing out.

**Results are cached to disk.** Overpass is a free, shared, volunteer-run
service. Every query is written to ``data/interim/osm/`` and reused, so a
re-run of the risk stage costs the service nothing.

Known limitation, stated plainly because it bounds every number downstream:
**OSM building coverage in rural Bangladesh is incomplete and uneven.** Char
settlements in particular are under-mapped relative to mainland villages. A
building count from OSM is therefore a **lower bound** on households at risk,
not an estimate of them, and it is reported as such in
:mod:`jamunarekha.risk.aggregate` and in the paper.
"""

from __future__ import annotations

import hashlib
import json
import math
import time
from dataclasses import dataclass
from pathlib import Path

import geopandas as gpd
import requests
from shapely.geometry import Point, box
from shapely.geometry.base import BaseGeometry
from shapely.ops import unary_union

from jamunarekha.utils.logging import get_logger

logger = get_logger("jamunarekha.overpass")

# Overpass rejects the default python-requests User-Agent with HTTP 406, and
# its usage policy asks clients to identify themselves and give a contact
# point so an operator can get in touch before blocking a misbehaving script.
USER_AGENT = {
    "User-Agent": (
        "JamunaRekha/1.0 (Jamuna shoreline erosion early warning; "
        "Bangla Academy research grant; +https://github.com/jamuna-rekha)"
    )
}

# Query the two OSM primitives that carry building footprints. Nodes tagged
# building=* exist but are rare and usually duplicates of a way, so including
# them would inflate the count.
QUERY_TEMPLATE = """
[out:json][timeout:{timeout}];
(
  way["building"]({south:.6f},{west:.6f},{north:.6f},{east:.6f});
  relation["building"]({south:.6f},{west:.6f},{north:.6f},{east:.6f});
);
out center tags qt;
"""


#: Public Overpass instances, tried in order. The main endpoint sheds load
#: aggressively (HTTP 504) during European working hours, and a single-endpoint
#: client simply fails the whole risk stage when that happens. The mirrors run
#: the same software over the same planet file.
MIRRORS = (
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
    "https://overpass.osm.jp/api/interpreter",
)


def _post_with_retry(
    query: str, preferred_url: str, timeout_s: int, attempts: int = 2
) -> dict | None:
    """POST a query to Overpass, retrying across mirrors with backoff.

    Returns the parsed JSON, or ``None`` when every endpoint has been tried.
    A failure here degrades the building count, it does not invalidate the
    erosion forecast, so the caller continues rather than aborting.
    """
    endpoints = [preferred_url] + [m for m in MIRRORS if m != preferred_url]
    for attempt in range(attempts):
        for url in endpoints:
            try:
                response = requests.post(
                    url, data={"data": query}, headers=USER_AGENT,
                    # (connect, read). A short connect timeout skips a dead
                    # mirror immediately; the read timeout is the server
                    # budget plus a small margin.
                    timeout=(10, 45),
                )
                if response.status_code in (429, 503, 504):
                    logger.debug("%s busy (%d)", url, response.status_code)
                    continue
                response.raise_for_status()
                return response.json()
            except Exception as exc:  # noqa: BLE001 - try the next mirror
                logger.debug("%s failed: %s", url, exc)
                continue
        if attempt + 1 < attempts:
            backoff = 5 * (attempt + 1)
            logger.info("all Overpass endpoints busy, waiting %ds", backoff)
            time.sleep(backoff)
    return None


def _cache_path(cache_dir: Path, bbox: tuple[float, float, float, float]) -> Path:
    key = hashlib.sha1(
        ("%.6f_%.6f_%.6f_%.6f" % bbox).encode("utf-8")
    ).hexdigest()[:16]
    return cache_dir / f"buildings_{key}.geojson"


def _split_bbox(
    bbox: tuple[float, float, float, float], max_span_deg: float
) -> list[tuple[float, float, float, float]]:
    """Split a bbox into tiles no larger than ``max_span_deg`` on a side.

    Overpass rejects or times out on large dense areas. Roughly 0.1 degrees
    (~11 km) keeps each request inside the server budget over the Jamuna
    floodplain, which is densely settled.
    """
    west, south, east, north = bbox

    # Cells are snapped to a GLOBAL lattice at multiples of max_span_deg rather
    # than laid out from the corner of this particular bbox. Two reasons:
    #
    # 1. Cache reuse. The cache key is the cell bbox, so a lattice anchored on
    #    the query would shift whenever the query extent changed by a metre —
    #    a second run with slightly different erosion polygons would miss every
    #    cached cell and re-query the whole reach.
    # 2. Determinism. The same ground is always requested as the same cell.
    #
    # Edges are computed from an index, never accumulated: repeatedly adding
    # 0.1 drifts (24.5 + 5 x 0.1 == 25.000000000000004), which used to emit an
    # extra row of zero-height slivers, each one a wasted request.
    def _floor_to(value: float) -> int:
        return math.floor(round(value / max_span_deg, 6))

    def _ceil_to(value: float) -> int:
        return math.ceil(round(value / max_span_deg, 6))

    col0, col1 = _floor_to(west), max(_ceil_to(east), _floor_to(west) + 1)
    row0, row1 = _floor_to(south), max(_ceil_to(north), _floor_to(south) + 1)

    out = []
    for i in range(col0, col1):
        lon0 = round(i * max_span_deg, 6)
        lon1 = round((i + 1) * max_span_deg, 6)
        for j in range(row0, row1):
            lat0 = round(j * max_span_deg, 6)
            lat1 = round((j + 1) * max_span_deg, 6)
            out.append((lon0, lat0, lon1, lat1))
    return out


def query_cells(
    bbox: tuple[float, float, float, float],
    max_span_deg: float = 0.1,
    restrict_to: BaseGeometry | None = None,
) -> list[tuple[float, float, float, float]]:
    """The lattice cells a query over ``bbox`` asks Overpass about.

    The erosion zones form a narrow ribbon along the river, but their overall
    bounding box is the whole 55 x 222 km study area. Tiling that box blindly
    is about 160 sub-queries, most of them over dry floodplain with no
    predicted erosion in them at all. Dropping the cells that do not touch
    ``restrict_to`` cuts the request count by roughly two thirds and is simply
    the polite thing to do to a volunteer-run service.

    Parameters
    ----------
    bbox
        ``(min_lon, min_lat, max_lon, max_lat)`` in EPSG:4326.
    max_span_deg
        Cell size, degrees.
    restrict_to
        Optional EPSG:4326 geometry; only cells that intersect it are kept.

    Returns
    -------
    list of tuple
        Cell bounding boxes, ``(min_lon, min_lat, max_lon, max_lat)``.
    """
    cells = _split_bbox(bbox, max_span_deg)
    if restrict_to is not None:
        keep = [c for c in cells if restrict_to.intersects(box(*c))]
        if keep:
            cells = keep
    return cells


def fetch_buildings(
    bbox: tuple[float, float, float, float],
    cache_dir: Path | str,
    overpass_url: str = "https://overpass-api.de/api/interpreter",
    timeout_s: int = 300,
    max_span_deg: float = 0.1,
    polite_delay_s: float = 2.0,
    restrict_to=None,
) -> gpd.GeoDataFrame:
    """Building centroids inside ``bbox``, from cache where possible.

    Parameters
    ----------
    bbox
        ``(min_lon, min_lat, max_lon, max_lat)`` in EPSG:4326.
    cache_dir
        Directory for cached GeoJSON responses, normally ``data/interim/osm``.
    overpass_url
        Overpass endpoint.
    timeout_s
        Server-side timeout passed into the query.
    max_span_deg
        Sub-tile size for splitting large requests.
    polite_delay_s
        Pause between uncached requests. Overpass is a shared volunteer
        service; hammering it is both rude and self-defeating, since the
        server will start refusing.

    Returns
    -------
    gpd.GeoDataFrame
        Columns ``osm_id``, ``osm_type``, ``building``, ``geometry`` (points),
        CRS EPSG:4326. Empty and correctly typed when nothing is found.
    """
    cache_dir = Path(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)

    frames: list[gpd.GeoDataFrame] = []
    sub_boxes = query_cells(bbox, max_span_deg, restrict_to)

    logger.info("Overpass: %d sub-queries for bbox %s", len(sub_boxes), [round(v, 3) for v in bbox])

    for i, sub in enumerate(sub_boxes, start=1):
        path = _cache_path(cache_dir, sub)
        if path.exists():
            frames.append(gpd.read_file(path))
            continue

        query = QUERY_TEMPLATE.format(
            timeout=timeout_s, west=sub[0], south=sub[1], east=sub[2], north=sub[3]
        )
        payload = _post_with_retry(query, overpass_url, timeout_s)
        if payload is None:
            logger.warning("Overpass sub-query %d/%d gave up", i, len(sub_boxes))
            continue

        gdf = _elements_to_points(payload.get("elements", []))
        gdf.to_file(path, driver="GeoJSON")
        frames.append(gdf)
        logger.info("Overpass %d/%d: %d buildings", i, len(sub_boxes), len(gdf))
        time.sleep(polite_delay_s)

    if not frames:
        return gpd.GeoDataFrame(
            {"osm_id": [], "osm_type": [], "building": []}, geometry=[], crs="EPSG:4326"
        )

    import pandas as pd

    combined = gpd.GeoDataFrame(
        pd.concat(frames, ignore_index=True), crs="EPSG:4326"
    )
    # Sub-tiles share edges, so a building straddling one can appear twice.
    if not combined.empty:
        combined = combined.drop_duplicates(subset=["osm_type", "osm_id"])
    logger.info("Overpass: %d unique buildings", len(combined))
    return combined


def _elements_to_points(elements: list[dict]) -> gpd.GeoDataFrame:
    """Convert an Overpass ``out center`` response to a point GeoDataFrame."""
    records, geometries = [], []
    for element in elements:
        centre = element.get("center") or (
            {"lat": element.get("lat"), "lon": element.get("lon")}
            if element.get("lat") is not None
            else None
        )
        if not centre or centre.get("lat") is None:
            continue
        tags = element.get("tags", {}) or {}
        records.append(
            {
                "osm_id": element.get("id"),
                "osm_type": element.get("type"),
                "building": tags.get("building", "yes"),
            }
        )
        geometries.append(Point(float(centre["lon"]), float(centre["lat"])))

    if not records:
        return gpd.GeoDataFrame(
            {"osm_id": [], "osm_type": [], "building": []}, geometry=[], crs="EPSG:4326"
        )
    return gpd.GeoDataFrame(records, geometry=geometries, crs="EPSG:4326")


def buildings_for_polygons(
    polygons: gpd.GeoDataFrame,
    cache_dir: Path | str,
    overpass_url: str,
    timeout_s: int = 300,
    buffer_m: float = 500.0,
) -> gpd.GeoDataFrame:
    """Fetch buildings covering the extent of a polygon layer.

    Only the neighbourhood of the predicted erosion zones is queried, rather
    than the whole 61 km tile, which is what keeps the request inside the
    Overpass budget.

    Parameters
    ----------
    polygons
        Erosion or accretion polygons in a metric CRS.
    buffer_m
        Margin added around the polygons before querying, metres. A building
        just outside a predicted zone still matters for the warning, and the
        forecast itself has a displacement error of order a few hundred
        metres, so a hard edge would be false precision.

    Returns
    -------
    gpd.GeoDataFrame
        Building centroids in EPSG:4326.
    """
    if polygons.empty:
        return gpd.GeoDataFrame(
            {"osm_id": [], "osm_type": [], "building": []}, geometry=[], crs="EPSG:4326"
        )

    bbox, restrict_to = _query_extent(polygons, buffer_m)
    return fetch_buildings(
        bbox,
        cache_dir=cache_dir,
        overpass_url=overpass_url,
        timeout_s=timeout_s,
        restrict_to=restrict_to,
    )


def _query_extent(
    polygons: gpd.GeoDataFrame, buffer_m: float
) -> tuple[tuple[float, float, float, float], BaseGeometry]:
    """Bounding box and footprint (EPSG:4326) of the buffered polygons."""
    buffered = polygons.copy()
    buffered["geometry"] = buffered.geometry.buffer(buffer_m)
    buffered = buffered.to_crs("EPSG:4326")
    bbox = tuple(float(v) for v in buffered.total_bounds)  # (minx, miny, maxx, maxy)
    return bbox, buffered.geometry.union_all()


@dataclass(frozen=True)
class Coverage:
    """The ground Overpass has actually answered for.

    ``geometry`` is the union of the query cells with a stored response, in
    EPSG:4326, or ``None`` when no cell answered. A cell that failed on every
    mirror is not cached, so it is not in ``geometry``: a density measured
    over it would count its buildings as zero.
    """

    geometry: BaseGeometry | None
    cells_answered: int
    cells_requested: int


def coverage_for_polygons(
    polygons: gpd.GeoDataFrame,
    cache_dir: Path | str,
    buffer_m: float = 500.0,
    max_span_deg: float = 0.1,
) -> Coverage:
    """Which cells of :func:`buildings_for_polygons`'s query have an answer.

    Makes no request: it reads only the cache that
    :func:`buildings_for_polygons` fills, so call it after that.

    Parameters
    ----------
    polygons
        The same polygons, in a metric CRS, and the same ``buffer_m`` and
        ``max_span_deg`` as the building query.
    cache_dir
        The building query's cache directory.
    """
    if polygons.empty:
        return Coverage(None, 0, 0)
    bbox, restrict_to = _query_extent(polygons, buffer_m)
    cells = query_cells(bbox, max_span_deg, restrict_to)
    answered = [c for c in cells if _cache_path(Path(cache_dir), c).exists()]
    geometry = unary_union([box(*c) for c in answered]) if answered else None
    if len(answered) < len(cells):
        logger.warning(
            "Overpass answered %d of %d cells; mapping density is measured "
            "only where it answered", len(answered), len(cells),
        )
    return Coverage(geometry, len(answered), len(cells))
