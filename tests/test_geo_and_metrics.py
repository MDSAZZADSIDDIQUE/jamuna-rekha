"""Grid geometry, temporal gap filling, and the metrics that carry units.

Mean Displacement Error is reported in metres in the paper and in the DDM
table. If the pixel-to-metre conversion is wrong, every number downstream is
wrong by the same factor and nothing else in the pipeline will notice. These
tests pin it against displacements whose answer is known by construction.
"""

from __future__ import annotations

import numpy as np
import pytest

from jamunarekha.data.preprocess import interpolate_gaps
from jamunarekha.models.metrics import (
    MetricAccumulator,
    accretion_map,
    bank_band,
    boundary_displacement_m,
    erosion_map,
)
from jamunarekha.utils.geo import bbox_to_crs, month_key, study_grid

JAMUNA_BBOX = (89.4, 24.5, 89.9, 26.5)
UTM45N = "EPSG:32645"


# --------------------------------------------------------------------- grid
def test_projected_bbox_is_metric_and_the_right_size():
    """The study reach is ~55 km wide and ~220 km long. Catches a CRS mix-up."""
    left, bottom, right, top = bbox_to_crs(JAMUNA_BBOX, UTM45N)
    width_km = (right - left) / 1000.0
    height_km = (top - bottom) / 1000.0
    assert 45 < width_km < 70
    assert 200 < height_km < 240


def test_grid_tiles_are_square_and_cover_the_bbox():
    tiles = study_grid(JAMUNA_BBOX, UTM45N, resolution_m=120.0, tile_size=512)
    assert tiles, "grid must not be empty"
    for tile in tiles:
        assert tile.width == tile.height == 512
        left, bottom, right, top = tile.bounds
        assert right - left == pytest.approx(512 * 120.0)
        assert top - bottom == pytest.approx(512 * 120.0)

    covered_left = min(t.bounds.left for t in tiles)
    covered_right = max(t.bounds.right for t in tiles)
    covered_bottom = min(t.bounds.bottom for t in tiles)
    covered_top = max(t.bounds.top for t in tiles)
    bl, bb, br, bt = bbox_to_crs(JAMUNA_BBOX, UTM45N)
    assert covered_left <= bl and covered_right >= br
    assert covered_bottom <= bb and covered_top >= bt


def test_grid_is_deterministic():
    """Re-running the grid must give pixel-identical tiles, or raw data
    acquired on different days would not stack."""
    a = study_grid(JAMUNA_BBOX, UTM45N, 120.0, 512)
    b = study_grid(JAMUNA_BBOX, UTM45N, 120.0, 512)
    assert [t.name for t in a] == [t.name for t in b]
    assert [tuple(t.transform)[:6] for t in a] == [tuple(t.transform)[:6] for t in b]


def test_tile_bounds_round_trip_back_into_the_study_area():
    tiles = study_grid(JAMUNA_BBOX, UTM45N, 120.0, 512)
    for tile in tiles:
        min_lon, min_lat, max_lon, max_lat = tile.bounds_wgs84()
        assert 88.5 < min_lon < 90.5
        assert 24.0 < min_lat < 27.0
        assert max_lon > min_lon and max_lat > min_lat


def test_month_key_format():
    assert month_key(1972, 7) == "1972-07"
    assert month_key(2024, 12) == "2024-12"


# ------------------------------------------------------------ interpolation
def test_interpolation_bridges_a_short_gap_linearly():
    series = np.full((5, 1, 1), np.nan, dtype=np.float32)
    series[0, 0, 0] = 0.0
    series[4, 0, 0] = 1.0
    filled, was_filled = interpolate_gaps(series, max_gap=6)
    assert filled[:, 0, 0] == pytest.approx([0.0, 0.25, 0.5, 0.75, 1.0])
    assert was_filled[1:4, 0, 0].all()
    assert not was_filled[0, 0, 0] and not was_filled[4, 0, 0]


def test_interpolation_refuses_a_gap_longer_than_the_limit():
    """A multi-year hole in the MSS era must stay a hole, not become a river."""
    series = np.full((12, 1, 1), np.nan, dtype=np.float32)
    series[0, 0, 0] = 0.0
    series[11, 0, 0] = 1.0
    filled, was_filled = interpolate_gaps(series, max_gap=3)
    assert np.isnan(filled[5, 0, 0])
    assert not was_filled[5, 0, 0]


def test_interpolation_leaves_observed_values_untouched():
    rng = np.random.default_rng(0)
    series = rng.normal(size=(10, 4, 4)).astype(np.float32)
    observed = series.copy()
    series[3] = np.nan
    filled, was_filled = interpolate_gaps(series, max_gap=6)
    keep = ~was_filled
    assert np.allclose(filled[keep], observed[keep], equal_nan=False)


def test_all_nan_pixel_stays_nan():
    series = np.full((6, 2, 2), np.nan, dtype=np.float32)
    filled, was_filled = interpolate_gaps(series, max_gap=6)
    assert np.isnan(filled).all()
    assert not was_filled.any()


# ----------------------------------------------------------------- metrics
def _half_water(width: int, edge: int) -> np.ndarray:
    """A frame that is water to the left of column ``edge``."""
    frame = np.zeros((width, width), dtype=bool)
    frame[:, :edge] = True
    return frame


def test_mde_of_an_identical_frame_is_zero():
    frame = _half_water(64, 30)
    valid = np.ones_like(frame)
    assert boundary_displacement_m(frame, frame, valid, 120.0) == pytest.approx(0.0)


@pytest.mark.parametrize("shift,resolution", [(1, 120.0), (3, 120.0), (5, 30.0)])
def test_mde_equals_the_known_shift_in_metres(shift, resolution):
    """A straight bank moved N pixels must report N * resolution metres."""
    truth = _half_water(64, 30)
    pred = _half_water(64, 30 + shift)
    valid = np.ones_like(truth)
    mde = boundary_displacement_m(pred, truth, valid, resolution)
    assert mde == pytest.approx(shift * resolution, rel=0.02)


def test_mde_is_undefined_not_zero_for_a_frame_with_no_bank():
    """An all-land prediction must not score a perfect displacement."""
    truth = _half_water(32, 16)
    all_land = np.zeros((32, 32), dtype=bool)
    valid = np.ones_like(truth)
    assert boundary_displacement_m(all_land, truth, valid, 120.0) is None


def test_bank_band_is_a_corridor_around_the_shoreline():
    frame = _half_water(64, 32)
    band = bank_band(frame, width=2)
    assert band.any()
    assert band[:, 32].all()          # the shoreline itself is in the band
    assert not band[:, 0].any()       # deep water is not
    assert not band[:, -1].any()      # far land is not
    assert band.mean() < 0.15         # it is a corridor, not the whole frame


def test_erosion_and_accretion_are_complementary():
    now = _half_water(32, 16)
    later = _half_water(32, 20)       # river widens: land becomes water
    eroded = erosion_map(now, later)
    accreted = accretion_map(now, later)
    assert eroded[:, 16:20].all()
    assert not accreted.any()
    assert not (eroded & accreted).any()


def test_accumulator_iou_and_f1_on_a_known_case():
    truth = _half_water(32, 16)[None, ...]
    pred = _half_water(32, 18)[None, ...]
    valid = np.ones_like(truth)
    acc = MetricAccumulator(resolution_m=120.0)
    acc.update(pred, truth, valid)
    out = acc.compute()
    # 18 predicted water columns, 16 true: intersection 16, union 18.
    assert out["iou"] == pytest.approx(16 / 18, rel=1e-6)
    assert 0.0 <= out["bank_f1"] <= 1.0
    assert out["mde_m"] == pytest.approx(2 * 120.0, rel=0.05)


def test_accumulator_ignores_unobserved_pixels():
    """Pixels that were interpolated must not enter the score.

    A model scored on Stage 2's own interpolation is being graded against its
    input assumptions, so an all-unobserved frame must contribute nothing at
    all rather than counting as a perfect or a failed prediction.
    """
    truth = _half_water(32, 16)[None, ...]
    pred = np.zeros_like(truth)       # completely wrong
    valid = np.zeros_like(truth)      # ...but nothing was observed
    acc = MetricAccumulator(resolution_m=120.0)
    acc.update(pred, truth, valid)
    out = acc.compute()
    assert acc.union == 0.0           # nothing entered the IoU denominator
    assert np.isnan(out["iou"])       # undefined, not zero and not one
    assert out["bank_f1"] == 0.0
    assert acc.tp == acc.fp == acc.fn == 0.0
    assert not acc.displacements      # no displacement was recorded either


# --------------------------------------------------------- calendar shifting
@pytest.mark.parametrize(
    "key,offset,expected",
    [
        ("2024-12", 3, "2025-03"),    # a forecast past the end of the record
        ("2024-12", -9, "2024-03"),   # the seasonally matched reference month
        ("2024-01", -1, "2023-12"),
        ("1972-07", 12, "1973-07"),
        ("1972-01", 0, "1972-01"),
    ],
)
def test_shift_month_crosses_year_boundaries(key, offset, expected):
    """A three-month forecast from December must land in March of the NEXT year.

    Looking the horizon up by index into the observed month list clamps it to
    the last available month, which stamps a warning with the wrong date.
    """
    from jamunarekha.utils.geo import shift_month

    assert shift_month(key, offset) == expected


def test_shift_month_round_trips():
    from jamunarekha.utils.geo import shift_month

    for key in ("1972-01", "1999-06", "2024-12"):
        for offset in (-24, -13, -1, 1, 7, 15):
            assert shift_month(shift_month(key, offset), -offset) == key
