"""Stage 4: vectorisation, spatial joins and the union-level aggregation.

These are the functions that turn a raster forecast into the number a disaster
officer acts on, so the arithmetic has to be right in units as well as in
value: areas in hectares, buildings counted in the union they actually stand
in, and OSM undercounting reported rather than silently corrected.

No network access — Overpass and GADM are represented by small synthetic
layers so the test suite stays runnable offline.
"""

from __future__ import annotations

import geopandas as gpd
import numpy as np
import pytest
from affine import Affine
from shapely.geometry import Point, Polygon

from jamunarekha.risk.aggregate import (
    attribute_to_unions,
    count_buildings_in_polygons,
    union_risk_table,
)
from jamunarekha.risk.overpass import _split_bbox
from jamunarekha.risk.vectorize import change_polygons, mask_to_polygons

UTM45N = "EPSG:32645"
RES = 120.0
# A transform on the canonical grid: 120 m pixels, origin at a plausible
# UTM 45N easting/northing for the Jamuna reach.
TRANSFORM = Affine(RES, 0.0, 740_000.0, 0.0, -RES, 2_800_000.0)


def _block_mask(size: int = 32, block: int = 10) -> np.ndarray:
    mask = np.zeros((size, size), dtype=bool)
    mask[5 : 5 + block, 5 : 5 + block] = True
    return mask


# ------------------------------------------------------------- vectorisation
def test_polygon_area_matches_the_pixel_count_in_square_metres():
    """10x10 pixels at 120 m is 1.44 km^2 = 144 ha. Catches a unit slip."""
    gdf = mask_to_polygons(_block_mask(), TRANSFORM, UTM45N, min_area_m2=0.0, simplify_m=0.0)
    assert len(gdf) == 1
    assert gdf["area_m2"].iloc[0] == pytest.approx(100 * RES * RES)
    assert gdf["area_ha"].iloc[0] == pytest.approx(144.0)


def test_polygons_land_in_the_right_place_on_earth():
    gdf = mask_to_polygons(_block_mask(), TRANSFORM, UTM45N, min_area_m2=0.0, simplify_m=0.0)
    lon, lat = gdf.to_crs("EPSG:4326").geometry.iloc[0].centroid.coords[0]
    assert 89.0 < lon < 90.5
    assert 24.0 < lat < 27.0


def test_small_speckle_is_dropped():
    """A single 120 m pixel is 1.44 ha and must not survive the 1 ha filter
    alone — otherwise every classification error becomes a warning."""
    mask = np.zeros((32, 32), dtype=bool)
    mask[3, 3] = True
    kept = mask_to_polygons(mask, TRANSFORM, UTM45N, min_area_m2=100_000.0)
    assert kept.empty


def test_empty_mask_returns_typed_empty_frame():
    gdf = mask_to_polygons(np.zeros((16, 16), dtype=bool), TRANSFORM, UTM45N)
    assert gdf.empty
    assert gdf.crs is not None
    assert {"kind", "area_m2", "area_ha"} <= set(gdf.columns)


def test_erosion_and_accretion_are_separated_and_labelled():
    now = np.zeros((32, 32), dtype=bool)
    now[:, :10] = True          # river on the left
    later = np.zeros((32, 32), dtype=bool)
    later[:, 4:14] = True       # river shifts right: erodes right, accretes left

    gdf = change_polygons(now, later, TRANSFORM, UTM45N, min_area_m2=0.0, simplify_m=0.0)
    kinds = set(gdf["kind"])
    assert kinds == {"erosion", "accretion"}
    erosion_ha = gdf.loc[gdf["kind"] == "erosion", "area_ha"].sum()
    accretion_ha = gdf.loc[gdf["kind"] == "accretion", "area_ha"].sum()
    # 4 columns x 32 rows of each, at 120 m
    assert erosion_ha == pytest.approx(4 * 32 * RES * RES / 10_000.0)
    assert accretion_ha == pytest.approx(4 * 32 * RES * RES / 10_000.0)


# ------------------------------------------------------------- spatial joins
def _two_unions() -> gpd.GeoDataFrame:
    """Two adjacent unions split at x = 741200 (pixel column 10)."""
    left = Polygon([(740_000, 2_797_000), (741_200, 2_797_000),
                    (741_200, 2_800_000), (740_000, 2_800_000)])
    right = Polygon([(741_200, 2_797_000), (743_000, 2_797_000),
                     (743_000, 2_800_000), (741_200, 2_800_000)])
    return gpd.GeoDataFrame(
        {
            "division": ["Rangpur", "Rangpur"],
            "district": ["Kurigram", "Kurigram"],
            "upazila": ["Chilmari", "Chilmari"],
            "union": ["Ramna", "Thanahat"],
            "gid_union": ["BGD.1.1.1_1", "BGD.1.1.2_1"],
        },
        geometry=[left, right],
        crs=UTM45N,
    ).to_crs("EPSG:4326")


def test_a_polygon_spanning_two_unions_is_split_not_assigned_whole():
    """The reason overlay is used instead of a centroid join.

    A centroid join would hand one union the other union's land loss, which is
    exactly the error that makes a warning table useless to the people reading
    it.
    """
    mask = np.zeros((32, 32), dtype=bool)
    mask[0:10, 5:15] = True          # straddles the boundary at column 10
    polygons = mask_to_polygons(mask, TRANSFORM, UTM45N, min_area_m2=0.0, simplify_m=0.0)

    pieces = attribute_to_unions(polygons, _two_unions())
    assert len(pieces) == 2
    assert set(pieces["union"]) == {"Ramna", "Thanahat"}
    # The split conserves area.
    assert pieces["area_ha"].sum() == pytest.approx(polygons["area_ha"].sum(), rel=1e-6)


def test_buildings_are_counted_in_the_polygon_they_stand_in():
    polygons = mask_to_polygons(_block_mask(), TRANSFORM, UTM45N, min_area_m2=0.0, simplify_m=0.0)
    inside = Point(740_000 + 8 * RES, 2_800_000 - 8 * RES)
    outside = Point(740_000 + 25 * RES, 2_800_000 - 25 * RES)
    buildings = gpd.GeoDataFrame(
        {"osm_id": [1, 2], "osm_type": ["way", "way"], "building": ["yes", "yes"]},
        geometry=[inside, outside], crs=UTM45N,
    )
    counted = count_buildings_in_polygons(polygons, buildings)
    assert counted["buildings_osm"].sum() == 1


def test_no_buildings_gives_zero_not_nan():
    polygons = mask_to_polygons(_block_mask(), TRANSFORM, UTM45N, min_area_m2=0.0, simplify_m=0.0)
    empty = gpd.GeoDataFrame(
        {"osm_id": [], "osm_type": [], "building": []}, geometry=[], crs="EPSG:4326"
    )
    counted = count_buildings_in_polygons(polygons, empty)
    assert counted["buildings_osm"].tolist() == [0]


# ----------------------------------------------------------- the risk table
def _pieces_and_buildings():
    mask = np.zeros((32, 32), dtype=bool)
    mask[0:10, 5:15] = True
    polygons = mask_to_polygons(mask, TRANSFORM, UTM45N, min_area_m2=0.0, simplify_m=0.0)
    polygons["kind"] = "erosion"
    pieces = attribute_to_unions(polygons, _two_unions())
    buildings = gpd.GeoDataFrame(
        {"osm_id": [1, 2, 3], "osm_type": ["way"] * 3, "building": ["yes"] * 3},
        geometry=[
            Point(740_000 + 7 * RES, 2_800_000 - 5 * RES),   # left union
            Point(740_000 + 8 * RES, 2_800_000 - 6 * RES),   # left union
            Point(740_000 + 12 * RES, 2_800_000 - 5 * RES),  # right union
        ],
        crs=UTM45N,
    )
    return pieces, buildings


def test_risk_table_reports_households_per_union():
    pieces, buildings = _pieces_and_buildings()
    table = union_risk_table(pieces, buildings, persons_per_household=4.5)
    assert set(table["union"]) == {"Ramna", "Thanahat"}
    assert table["buildings_osm"].sum() == 3
    assert (table["persons_est"] == (table["households_est"] * 4.5).round()).all()
    assert table["erosion_ha"].sum() > 0


def test_osm_completeness_is_recorded_in_the_table_itself():
    """The assumption travels with the CSV, not in a footnote nobody reads."""
    pieces, buildings = _pieces_and_buildings()
    raw = union_risk_table(pieces, buildings, osm_completeness=1.0)
    scaled = union_risk_table(pieces, buildings, osm_completeness=0.5)

    assert (raw["osm_completeness_assumed"] == 1.0).all()
    assert (scaled["osm_completeness_assumed"] == 0.5).all()
    # Raw OSM counts are never altered; only the derived estimate scales.
    assert raw["buildings_osm"].sum() == scaled["buildings_osm"].sum()
    assert scaled["households_est"].sum() == 2 * raw["households_est"].sum()


def test_risk_table_is_sorted_worst_first():
    pieces, buildings = _pieces_and_buildings()
    table = union_risk_table(pieces, buildings)
    assert table["households_est"].is_monotonic_decreasing


def test_empty_input_gives_an_empty_table_with_the_right_columns():
    empty = gpd.GeoDataFrame(
        {"kind": [], "area_ha": []}, geometry=[], crs=UTM45N
    )
    table = union_risk_table(empty, empty)
    assert table.empty
    for column in ("union", "erosion_ha", "buildings_osm", "households_est"):
        assert column in table.columns


# ----------------------------------------------------------------- overpass
def test_bbox_splitting_covers_the_whole_extent():
    """Overpass times out on large dense areas, so requests are tiled."""
    bbox = (89.4, 24.5, 89.9, 25.0)
    tiles = _split_bbox(bbox, max_span_deg=0.1)
    assert len(tiles) == 25
    assert min(t[0] for t in tiles) <= bbox[0]
    assert max(t[2] for t in tiles) >= bbox[2]
    assert min(t[1] for t in tiles) <= bbox[1]
    assert max(t[3] for t in tiles) >= bbox[3]


def test_bbox_cells_snap_to_a_global_lattice():
    """Cells must not move when the query extent shifts slightly.

    The Overpass cache is keyed on the cell bounding box. If the lattice were
    anchored on each query, a second run whose erosion polygons differed by a
    few metres would miss every cached cell and re-query the entire reach
    against a volunteer-run service.
    """
    a = set(_split_bbox((89.42, 24.51, 89.88, 24.99), max_span_deg=0.1))
    b = set(_split_bbox((89.40, 24.50, 89.90, 25.00), max_span_deg=0.1))
    assert a == b

    for lon0, lat0, lon1, lat1 in a:
        assert lon0 * 10 == pytest.approx(round(lon0 * 10))
        assert lat0 * 10 == pytest.approx(round(lat0 * 10))
        assert lon1 - lon0 == pytest.approx(0.1)
        assert lat1 - lat0 == pytest.approx(0.1)


def test_bbox_splitting_handles_a_degenerate_extent():
    """A single erosion polygon can give a near-zero extent; still one cell."""
    tiles = _split_bbox((89.45, 24.55, 89.45, 24.55), max_span_deg=0.1)
    assert len(tiles) == 1


# ------------------------------------------------------ OSM mapping density
def _square(x0: float, y0: float, side_m: float) -> Polygon:
    return Polygon([(x0, y0), (x0 + side_m, y0), (x0 + side_m, y0 + side_m), (x0, y0 + side_m)])


def _points_in(x0: float, y0: float, width_m: float, height_m: float, n: int) -> list[Point]:
    side = int(np.ceil(np.sqrt(n)))
    step_x, step_y = width_m / (side + 1), height_m / (side + 1)
    pts = [Point(x0 + (i + 1) * step_x, y0 + (j + 1) * step_y) for i in range(side) for j in range(side)]
    return pts[:n]


def test_mapping_density_is_per_square_kilometre_of_the_part_that_was_queried():
    from jamunarekha.risk.aggregate import mapping_density

    x0, y0 = 740_000.0, 2_790_000.0
    unions = gpd.GeoDataFrame(
        {"gid_union": ["A", "B", "C"]},
        geometry=[
            _square(x0, y0, 2_000),            # 4 km2, fully queried
            _square(x0 + 2_000, y0, 2_000),    # 4 km2, left half queried
            _square(x0 + 10_000, y0, 2_000),   # never queried
        ],
        crs=UTM45N,
    )
    covered = Polygon([(x0, y0), (x0 + 3_000, y0), (x0 + 3_000, y0 + 2_000), (x0, y0 + 2_000)])
    coverage = gpd.GeoSeries([covered], crs=UTM45N).to_crs("EPSG:4326").iloc[0]
    buildings = gpd.GeoDataFrame(
        geometry=_points_in(x0, y0, 2_000, 2_000, 400)                 # A: 100 per km2
        + _points_in(x0 + 2_000, y0, 1_000, 2_000, 10),               # B, queried half: 5 per km2
        crs=UTM45N,
    ).to_crs("EPSG:4326")

    out = mapping_density(unions, buildings, coverage, metric_crs=UTM45N)
    assert list(out.columns) == ["gid_union", "osm_buildings_per_km2", "osm_measured_km2", "osm_mapping"]
    out = out.set_index("gid_union")
    assert out.loc["A", "osm_measured_km2"] == pytest.approx(4.0, rel=1e-3)
    assert out.loc["A", "osm_buildings_per_km2"] == pytest.approx(100.0, rel=1e-3)
    assert out.loc["A", "osm_mapping"] == "high"
    # B is measured only over the half Overpass was asked about.
    assert out.loc["B", "osm_measured_km2"] == pytest.approx(2.0, rel=1e-3)
    assert out.loc["B", "osm_buildings_per_km2"] == pytest.approx(5.0, rel=1e-3)
    assert out.loc["B", "osm_mapping"] == "low"
    assert np.isnan(out.loc["C", "osm_buildings_per_km2"])
    assert out.loc["C", "osm_mapping"] == "not measured"


def test_mapping_density_is_not_reported_over_a_sliver():
    from jamunarekha.risk.aggregate import mapping_density

    x0, y0 = 740_000.0, 2_790_000.0
    unions = gpd.GeoDataFrame({"gid_union": ["A"]}, geometry=[_square(x0, y0, 2_000)], crs=UTM45N)
    sliver = gpd.GeoSeries([_square(x0, y0, 500)], crs=UTM45N).to_crs("EPSG:4326").iloc[0]   # 0.25 km2
    buildings = gpd.GeoDataFrame(geometry=[Point(x0 + 100, y0 + 100)], crs=UTM45N)
    out = mapping_density(unions, buildings, sliver, metric_crs=UTM45N, min_area_km2=1.0)
    assert np.isnan(out["osm_buildings_per_km2"].iloc[0])
    assert out["osm_mapping"].iloc[0] == "not measured"


def test_mapping_bands_have_inclusive_upper_edges():
    from jamunarekha.risk.aggregate import mapping_level

    assert mapping_level(9.99, 10, 100) == "low"
    assert mapping_level(10.0, 10, 100) == "medium"
    assert mapping_level(99.9, 10, 100) == "medium"
    assert mapping_level(100.0, 10, 100) == "high"
    assert mapping_level(float("nan"), 10, 100) == "not measured"


def test_coverage_leaves_out_cells_overpass_never_answered(tmp_path):
    """A cell that failed on every mirror has no cached answer. Measuring
    density over it would count its buildings as zero and call the union
    unmapped, so it must not be part of the coverage."""
    from jamunarekha.risk.overpass import _cache_path, _query_extent, coverage_for_polygons, query_cells

    erosion = gpd.GeoDataFrame(
        {"kind": ["erosion"]}, geometry=[_square(740_000.0, 2_790_000.0, 30_000)], crs=UTM45N
    )
    bbox, footprint = _query_extent(erosion, 500.0)
    cells = query_cells(bbox, 0.1, footprint)
    assert len(cells) >= 4
    answered = cells[: len(cells) // 2]
    for cell in answered:
        _cache_path(tmp_path, cell).write_text('{"type": "FeatureCollection", "features": []}')

    coverage = coverage_for_polygons(erosion, tmp_path, buffer_m=500.0)
    assert coverage.cells_requested == len(cells)
    assert coverage.cells_answered == len(answered)
    missing = cells[-1]
    centre = Point((missing[0] + missing[2]) / 2, (missing[1] + missing[3]) / 2)
    assert not coverage.geometry.contains(centre)


# ------------------------------------------------------------- map zones
def test_zones_are_cut_on_union_boundaries_and_nothing_is_dropped():
    """A zone half inside a union and half outside every union becomes two
    pieces: the inside one names its union, the outside one is kept unnamed,
    and together they still cover the whole zone."""
    from jamunarekha.risk.aggregate import split_zones_by_union

    x0, y0 = 740_000.0, 2_790_000.0
    zone = gpd.GeoDataFrame({"kind": ["erosion"]}, geometry=[_square(x0, y0, 2_000)], crs=UTM45N)
    union = gpd.GeoDataFrame(
        {"gid_union": ["BGD.1.1.1.1_1"]}, geometry=[_square(x0 - 1_000, y0 - 1_000, 2_000)], crs=UTM45N
    ).to_crs("EPSG:4326")

    pieces = split_zones_by_union(zone, union)
    assert pieces.crs.to_string() == "EPSG:4326"
    assert list(pieces.columns) == ["kind", "area_ha", "gid_union", "geometry"]
    assert pieces["area_ha"].sum() == pytest.approx(400.0, rel=1e-3)        # 2 km x 2 km
    inside = pieces[pieces["gid_union"] == "BGD.1.1.1.1_1"]
    assert inside["area_ha"].sum() == pytest.approx(100.0, rel=1e-3)         # the 1 km x 1 km overlap
    assert pieces["gid_union"].isna().any()                                  # the rest is kept, unnamed
    assert set(pieces["kind"]) == {"erosion"}


# ------------------------------------------------ overlapping union outlines
def _overlapping_unions(x0, y0):
    """A and B overlap in a 200 m strip, as GADM's neighbours sometimes do."""
    return gpd.GeoDataFrame(
        {"division": ["D", "D"], "district": ["X", "X"], "upazila": ["U", "U"],
         "union": ["A", "B"], "gid_union": ["G.A", "G.B"]},
        geometry=[Polygon([(x0, y0), (x0 + 1_200, y0), (x0 + 1_200, y0 + 1_000), (x0, y0 + 1_000)]),
                  Polygon([(x0 + 1_000, y0), (x0 + 3_000, y0), (x0 + 3_000, y0 + 1_000), (x0 + 1_000, y0 + 1_000)])],
        crs=UTM45N,
    ).to_crs("EPSG:4326")


def test_an_overlap_between_unions_is_counted_once_in_the_table():
    x0, y0 = 740_000.0, 2_790_000.0
    zone = gpd.GeoDataFrame(
        {"kind": ["erosion"]},
        geometry=[Polygon([(x0, y0), (x0 + 3_000, y0), (x0 + 3_000, y0 + 1_000), (x0, y0 + 1_000)])],
        crs=UTM45N,
    )
    pieces = attribute_to_unions(zone, _overlapping_unions(x0, y0))
    # 300 ha of erosion, not 320: the 20 ha strip belongs to one union only...
    assert pieces["area_ha"].sum() == pytest.approx(300.0, rel=1e-3)
    by_union = pieces.groupby("gid_union")["area_ha"].sum()
    # ...the one holding the larger share of the zone (B: 200 ha against 120 ha).
    assert by_union["G.B"] == pytest.approx(200.0, rel=1e-3)
    assert by_union["G.A"] == pytest.approx(100.0, rel=1e-3)

    # And a building standing in the strip is counted once.
    building = gpd.GeoDataFrame(geometry=[Point(x0 + 1_100, y0 + 500)], crs=UTM45N)
    table = union_risk_table(pieces, building)
    assert int(table["buildings_osm"].sum()) == 1


def test_an_overlap_is_drawn_once_on_the_map():
    from jamunarekha.risk.aggregate import split_zones_by_union

    x0, y0 = 740_000.0, 2_790_000.0
    zone = gpd.GeoDataFrame(
        {"kind": ["erosion"]},
        geometry=[Polygon([(x0, y0), (x0 + 4_000, y0), (x0 + 4_000, y0 + 1_000), (x0, y0 + 1_000)])],
        crs=UTM45N,
    )
    pieces = split_zones_by_union(zone, _overlapping_unions(x0, y0))
    assert pieces["area_ha"].sum() == pytest.approx(400.0, rel=1e-3)   # the zone, exactly
    assert pieces["gid_union"].isna().sum() == 1                       # the last 1 km lies outside both
