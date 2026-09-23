"""Stage 4c — aggregate predicted erosion to union parishad level.

This is the handoff artefact. Everything upstream exists to produce the table
this module writes: for each union parishad, how much land the Jamuna is
forecast to take in the next three months, and how many homesteads stand on it.

Administrative boundaries come from **GADM 4.1**, where Bangladesh level 4 is
the union parishad (level 1 division, 2 district/zila, 3 upazila).

On the household numbers
------------------------
Two figures are reported and they must not be confused:

``buildings_osm``
    An exact count of OpenStreetMap building centroids inside the predicted
    erosion polygons. This is a **lower bound**. OSM coverage of rural
    Bangladesh is incomplete and char settlements are under-mapped relative to
    mainland villages, so the true count is higher by an unknown factor.

``households_est``
    ``buildings_osm`` divided by an explicit completeness factor, with the
    factor written into the output so nobody has to guess what was assumed.

The distinction is kept in the CSV itself rather than in a footnote, because
this file will be read by people who did not read the paper.
"""

from __future__ import annotations

import io
import zipfile
from pathlib import Path

import geopandas as gpd
import pandas as pd
import requests
import shapely
from shapely.geometry.base import BaseGeometry

from jamunarekha.utils.logging import get_logger

logger = get_logger("jamunarekha.aggregate")

# GADM level-4 attribute names for Bangladesh, mapped to plain English and
# their Bengali administrative equivalents.
GADM_COLUMNS = {
    "NAME_1": "division",
    "NAME_2": "district",
    "NAME_3": "upazila",
    "NAME_4": "union",
    "GID_4": "gid_union",
}


def load_gadm_unions(
    url: str, cache_dir: Path | str, level: int = 4
) -> gpd.GeoDataFrame:
    """Download (once) and load GADM union parishad boundaries for Bangladesh.

    Parameters
    ----------
    url
        GADM zipped GeoJSON URL for the requested level.
    cache_dir
        Where to keep the downloaded archive, normally ``data/interim/gadm``.
    level
        GADM administrative level. 4 is the union parishad in Bangladesh.

    Returns
    -------
    gpd.GeoDataFrame
        Union polygons in EPSG:4326 with renamed, readable columns.
    """
    cache_dir = Path(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)
    local = cache_dir / f"gadm41_BGD_{level}.json"

    if not local.exists():
        logger.info("downloading GADM level %d boundaries", level)
        response = requests.get(url, timeout=300)
        response.raise_for_status()
        with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
            name = next(n for n in archive.namelist() if n.endswith(".json"))
            local.write_bytes(archive.read(name))

    gdf = gpd.read_file(local)
    present = {k: v for k, v in GADM_COLUMNS.items() if k in gdf.columns}
    gdf = gdf.rename(columns=present)
    keep = [v for v in present.values()] + ["geometry"]
    gdf = gdf[keep]
    logger.info("GADM: %d union parishads loaded", len(gdf))
    return gdf.to_crs("EPSG:4326")


def count_buildings_in_polygons(
    polygons: gpd.GeoDataFrame, buildings: gpd.GeoDataFrame
) -> gpd.GeoDataFrame:
    """Attach a building count to every polygon by spatial join.

    Parameters
    ----------
    polygons
        Erosion/accretion polygons in a metric CRS.
    buildings
        Building centroids, any CRS; reprojected to match ``polygons``.

    Returns
    -------
    gpd.GeoDataFrame
        ``polygons`` with an added integer ``buildings_osm`` column.
    """
    out = polygons.copy()
    if out.empty:
        out["buildings_osm"] = []
        return out
    if buildings.empty:
        out["buildings_osm"] = 0
        return out

    points = buildings.to_crs(out.crs)
    joined = gpd.sjoin(points, out[["geometry"]], how="inner", predicate="within")
    counts = joined.groupby("index_right").size()
    out["buildings_osm"] = (
        out.index.to_series().map(counts).fillna(0).astype(int).to_numpy()
    )
    return out


_SOURCE = "_source_polygon"


def _polygonal(geometry: BaseGeometry) -> BaseGeometry:
    """Only the areal parts: a difference can leave slivers of line behind."""
    parts = [g for g in shapely.get_parts(geometry) if g.geom_type in ("Polygon", "MultiPolygon")]
    if not parts:
        return shapely.Polygon()
    return parts[0] if len(parts) == 1 else shapely.union_all(parts)


def one_union_per_place(pieces: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Give each overlap between union outlines to a single union.

    GADM 4.1's outlines overlap along some shared borders (197 pairs along the
    Jamuna), so a change polygon crossing one is cut into pieces that overlap,
    and summing the pieces counts the overlap in both unions. Within each
    source polygon the named pieces are taken largest first, and each later
    piece loses whatever an earlier one already covers. An overlap therefore
    goes to the union holding the larger share of that zone (ties by GADM id),
    and the pieces of a polygon add up to the polygon again.

    Expects the source polygon's position in a ``_source_polygon`` column and
    a metric CRS. Pieces outside every union (``gid_union`` empty) never
    overlap a named piece and are left alone.
    """
    named = pieces["gid_union"].notna()
    counts = pieces.loc[named, _SOURCE].value_counts()
    shared = counts[counts > 1].index
    if shared.empty:
        return pieces
    out = pieces.copy()
    area = out.geometry.area
    for source in shared:
        rows = out.index[named & (out[_SOURCE] == source)]
        order = sorted(rows, key=lambda i: (-area[i], str(out.at[i, "gid_union"])))
        taken = None
        for i in order:
            geometry = out.at[i, "geometry"]
            if taken is not None and geometry.intersects(taken):
                geometry = _polygonal(geometry.difference(taken))
                out.at[i, "geometry"] = geometry
            taken = geometry if taken is None else taken.union(geometry)
    return out[~out.geometry.is_empty & (out.geometry.area > 0)]


def attribute_to_unions(
    polygons: gpd.GeoDataFrame, unions: gpd.GeoDataFrame
) -> gpd.GeoDataFrame:
    """Split polygons on union boundaries and attach the union attributes.

    An overlay rather than a centroid join: a single erosion polygon can span
    two unions, and assigning the whole thing to whichever union happens to
    contain its centroid would hand one union the other's losses.

    Parameters
    ----------
    polygons
        Erosion/accretion polygons in a metric CRS, with ``buildings_osm``.
    unions
        GADM union polygons, EPSG:4326.

    Returns
    -------
    gpd.GeoDataFrame
        Polygon fragments, one per (polygon, union) intersection, with areas
        recomputed after the split.
    """
    if polygons.empty:
        return polygons.assign(**{v: [] for v in GADM_COLUMNS.values()})

    unions_m = unions.to_crs(polygons.crs)

    # Restrict to the unions that could possibly intersect before overlaying.
    # GADM level 4 is 5 158 polygons for the whole of Bangladesh, and an
    # overlay against all of them costs far more than the roughly 350 that
    # touch the study reach. The clip is by bounding box, so it cannot drop a
    # union that genuinely intersects.
    minx, miny, maxx, maxy = polygons.total_bounds
    nearby = unions_m.cx[minx:maxx, miny:maxy]
    if not nearby.empty:
        logger.info(
            "overlay: %d of %d unions intersect the forecast extent",
            len(nearby), len(unions_m),
        )
        unions_m = nearby

    sourced = polygons.assign(**{_SOURCE: range(len(polygons))})
    pieces = gpd.overlay(sourced, unions_m, how="intersection", keep_geom_type=True)
    if pieces.empty:
        return pieces.drop(columns=_SOURCE)

    pieces = one_union_per_place(pieces).drop(columns=_SOURCE)
    pieces["area_m2"] = pieces.geometry.area
    pieces["area_ha"] = pieces["area_m2"] / 10_000.0
    return pieces


def split_zones_by_union(
    polygons: gpd.GeoDataFrame, unions: gpd.GeoDataFrame
) -> gpd.GeoDataFrame:
    """Every change polygon, cut on union boundaries, for the web map.

    Unlike :func:`attribute_to_unions`, nothing is dropped: the part of a zone
    outside every union (the reach runs into India, and GADM leaves some of the
    river unassigned) is kept with an empty ``gid_union``, so the map shows the
    whole forecast while a zone inside a union can still be named.

    Parameters
    ----------
    polygons
        Erosion/accretion polygons with ``kind``, in a metric CRS.
    unions
        GADM union polygons with ``gid_union``, any CRS.

    Returns
    -------
    gpd.GeoDataFrame
        ``kind``, ``area_ha`` (recomputed per piece, in the metric CRS),
        ``gid_union`` (None outside every union), geometry in EPSG:4326.
    """
    columns = ["kind", "area_ha", "gid_union", "geometry"]
    if polygons.empty:
        return gpd.GeoDataFrame(
            {"kind": [], "area_ha": [], "gid_union": []}, geometry=[], crs="EPSG:4326"
        )[columns]
    unions_m = unions[["gid_union", "geometry"]].to_crs(polygons.crs)
    minx, miny, maxx, maxy = polygons.total_bounds
    nearby = unions_m.cx[minx:maxx, miny:maxy]
    sourced = polygons[["kind", "geometry"]].assign(**{_SOURCE: range(len(polygons))})
    pieces = gpd.overlay(sourced, nearby, how="identity", keep_geom_type=True)
    pieces = one_union_per_place(pieces).drop(columns=_SOURCE)
    pieces["area_ha"] = pieces.geometry.area / 10_000.0
    pieces["gid_union"] = pieces["gid_union"].astype(object).where(pieces["gid_union"].notna(), None)
    return pieces[columns].to_crs("EPSG:4326")


def union_risk_table(
    pieces: gpd.GeoDataFrame,
    buildings: gpd.GeoDataFrame,
    persons_per_household: float = 4.5,
    osm_completeness: float = 1.0,
) -> pd.DataFrame:
    """Aggregate polygon fragments into the per-union risk table.

    Buildings are recounted against the *fragments*, not inherited from the
    parent polygon, so a polygon spanning two unions contributes its buildings
    to whichever union each one actually stands in.

    Parameters
    ----------
    pieces
        Output of :func:`attribute_to_unions`.
    buildings
        Building centroids.
    persons_per_household
        Mean household size. 4.5 is the Bangladesh figure from the 2022
        Population and Housing Census.
    osm_completeness
        Assumed fraction of real buildings present in OSM, in (0, 1]. 1.0
        means "report the raw OSM count and make no correction", which is the
        default because any other value is a guess and would be presented as
        data.

    Returns
    -------
    pd.DataFrame
        One row per union parishad with erosion and accretion columns, sorted
        by households at risk.
    """
    if pieces.empty:
        return pd.DataFrame(
            columns=[
                "division", "district", "upazila", "union", "gid_union",
                "erosion_ha", "accretion_ha", "net_land_change_ha",
                "buildings_osm", "households_est", "persons_est",
                "osm_completeness_assumed",
            ]
        )

    counted = count_buildings_in_polygons(pieces, buildings)
    keys = [c for c in ("division", "district", "upazila", "union", "gid_union")
            if c in counted.columns]

    erosion = counted[counted["kind"] == "erosion"]
    accretion = counted[counted["kind"] == "accretion"]

    erosion_agg = (
        erosion.groupby(keys, dropna=False)
        .agg(erosion_ha=("area_ha", "sum"), buildings_osm=("buildings_osm", "sum"))
        .reset_index()
    )
    accretion_agg = (
        accretion.groupby(keys, dropna=False)
        .agg(accretion_ha=("area_ha", "sum"))
        .reset_index()
    )

    table = erosion_agg.merge(accretion_agg, on=keys, how="outer")
    table[["erosion_ha", "accretion_ha", "buildings_osm"]] = (
        table[["erosion_ha", "accretion_ha", "buildings_osm"]].fillna(0.0)
    )

    table["net_land_change_ha"] = table["accretion_ha"] - table["erosion_ha"]
    factor = max(1e-6, float(osm_completeness))
    table["households_est"] = (table["buildings_osm"] / factor).round().astype(int)
    table["persons_est"] = (
        table["households_est"] * float(persons_per_household)
    ).round().astype(int)
    table["osm_completeness_assumed"] = factor
    table["buildings_osm"] = table["buildings_osm"].astype(int)

    table = table.sort_values(
        ["households_est", "erosion_ha"], ascending=False
    ).reset_index(drop=True)
    return table


#: Values of the ``osm_mapping`` column.
MAPPING_LEVELS = ("low", "medium", "high", "not measured")


def mapping_level(density: float, low_below: float, high_from: float) -> str:
    """Name the band a building density (per km²) falls in; NaN is "not measured"."""
    if pd.isna(density):
        return "not measured"
    if density < low_below:
        return "low"
    if density < high_from:
        return "medium"
    return "high"


def mapping_density(
    unions: gpd.GeoDataFrame,
    buildings: gpd.GeoDataFrame,
    coverage: BaseGeometry | None,
    metric_crs: str = "EPSG:32645",
    min_area_km2: float = 1.0,
    low_below: float = 10.0,
    high_from: float = 100.0,
) -> pd.DataFrame:
    """OSM building density across each union, not just its erosion zone.

    ``buildings_osm`` counts buildings inside the predicted erosion zone, and
    zero there is ambiguous: unsettled char, or a village nobody has mapped.
    Density over the whole union separates the two, because no inhabited
    rural union in Bangladesh has only a handful of buildings per square
    kilometre. It also says how far to trust a non-zero count.

    Density is measured over the part of the union that the Overpass query
    covered, since outside it no building was asked for, and that area is
    reported alongside. The area includes water, so a union that is mostly
    river reads lower than its settled land alone would; the bands are an
    order of magnitude apart so that this rarely changes the band.

    Parameters
    ----------
    unions
        Union polygons (``gid_union``, ``geometry``), any CRS.
    buildings
        Building centroids from the same Overpass query, any CRS.
    coverage
        EPSG:4326 geometry the query covered
        (:func:`jamunarekha.risk.overpass.coverage_for_polygons`), or None.
    metric_crs
        Metric CRS for areas. EPSG:32645 (UTM 45N) for the Jamuna.
    min_area_km2
        Below this measured area the density is not reported.
    low_below, high_from
        Band edges, buildings per km².

    Returns
    -------
    pd.DataFrame
        ``gid_union``, ``osm_buildings_per_km2`` (NaN when not measured),
        ``osm_measured_km2`` and ``osm_mapping`` (one of
        :data:`MAPPING_LEVELS`).
    """
    out = pd.DataFrame({"gid_union": unions["gid_union"].to_numpy()})
    if coverage is None or coverage.is_empty or unions.empty:
        out["osm_buildings_per_km2"] = float("nan")
        out["osm_measured_km2"] = 0.0
        out["osm_mapping"] = "not measured"
        return out[["gid_union", "osm_buildings_per_km2", "osm_measured_km2", "osm_mapping"]]

    coverage_m = gpd.GeoSeries([coverage], crs="EPSG:4326").to_crs(metric_crs).iloc[0]
    measured = unions[["gid_union", "geometry"]].to_crs(metric_crs)
    measured["geometry"] = measured.geometry.intersection(coverage_m)
    measured = measured[~measured.geometry.is_empty]
    area_km2 = pd.Series(measured.geometry.area.to_numpy() / 1e6, index=measured["gid_union"])

    counts = pd.Series(dtype=float)
    if not buildings.empty and not measured.empty:
        joined = gpd.sjoin(
            buildings[["geometry"]].to_crs(metric_crs), measured, how="inner", predicate="within"
        )
        counts = joined.groupby("gid_union").size()

    out["osm_measured_km2"] = out["gid_union"].map(area_km2).fillna(0.0)
    count = out["gid_union"].map(counts).fillna(0.0)
    enough = out["osm_measured_km2"] >= float(min_area_km2)
    out["osm_buildings_per_km2"] = (count / out["osm_measured_km2"]).where(enough)
    out["osm_mapping"] = [
        mapping_level(d, low_below, high_from) for d in out["osm_buildings_per_km2"]
    ]
    # Explicit order: it is the order of the DDM CSV, which the web
    # dashboard reproduces line for line in its filtered downloads.
    return out[["gid_union", "osm_buildings_per_km2", "osm_measured_km2", "osm_mapping"]]


def write_table(table: pd.DataFrame, path: Path | str, forecast_month: str) -> Path:
    """Write the DDM handoff CSV.

    Written with a UTF-8 BOM so that Excel on a Windows machine in a Dhaka
    office opens the Bengali union names correctly instead of as mojibake —
    a small thing that decides whether the file is usable at all.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    out = table.copy()
    out.insert(0, "forecast_month", forecast_month)
    out.to_csv(path, index=False, encoding="utf-8-sig")
    logger.info("wrote %s (%d unions)", path, len(out))
    return path
