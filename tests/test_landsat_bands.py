"""The per-sensor band mapping is the project's most dangerous table.

CLAUDE.md §2 names it "the single most common source of silent bugs": pick the
wrong band for one mission and the water index inverts for that decade, the
Otsu threshold happily adapts, and nothing crashes. These tests are the only
thing standing between that mistake and a published result.
"""

from __future__ import annotations

import numpy as np
import pytest

from jamunarekha.data.landsat import (
    SENSORS,
    cloud_mask,
    spec_for,
    to_reflectance,
    water_index,
    QA_CLOUD,
    QA_CLOUD_SHADOW,
    QA_FILL,
)


def test_every_landsat_mission_is_mapped():
    """Missions 1-9 (there is no Landsat 6 in orbit) all have a spec."""
    expected = {f"landsat-{n}" for n in (1, 2, 3, 4, 5, 7, 8, 9)}
    assert set(SENSORS) == expected


def test_mss_missions_use_ndwi_without_swir():
    """MSS carries no SWIR, so Landsat 1-3 must fall back to NDWI."""
    for platform in ("landsat-1", "landsat-2", "landsat-3"):
        spec = spec_for(platform)
        assert spec.index == "NDWI"
        assert spec.instrument == "MSS"
        assert "swir" not in spec.dark_asset
        assert spec.native_res_m == 60.0


def test_tm_etm_oli_use_mndwi_with_swir1():
    for platform in ("landsat-4", "landsat-5", "landsat-7", "landsat-8", "landsat-9"):
        spec = spec_for(platform)
        assert spec.index == "MNDWI"
        assert spec.dark_asset == "swir16"
        assert spec.native_res_m == 30.0


def test_landsat_5_mss_resolves_to_mss_not_tm():
    """Landsat 4 and 5 flew both instruments; the instrument decides, not the platform.

    This is the specific trap: a Landsat 5 MSS scene looks like a Landsat 5
    scene, and mapping it through the TM spec would request a SWIR band the
    product does not have.
    """
    assert spec_for("landsat-5", ["tm"]).index == "MNDWI"
    assert spec_for("landsat-5", ["mss"]).index == "NDWI"
    assert spec_for("landsat-4", ["mss"]).instrument == "MSS"


def test_unknown_platform_raises_rather_than_guessing():
    with pytest.raises(KeyError):
        spec_for("sentinel-2")


def test_water_index_sign_convention_water_is_positive():
    """Water: high green, low SWIR/NIR. Land: the reverse."""
    spec = spec_for("landsat-8")
    water_pixel = water_index(np.array([[0.09]]), np.array([[0.02]]), spec)
    land_pixel = water_index(np.array([[0.09]]), np.array([[0.25]]), spec)
    assert water_pixel[0, 0] > 0
    assert land_pixel[0, 0] < 0


def test_water_index_is_bounded_and_nan_safe():
    spec = spec_for("landsat-8")
    green = np.array([[0.1, 0.0, np.nan, 1.0]])
    dark = np.array([[0.1, 0.0, 0.2, -1.0]])
    out = water_index(green, dark, spec)
    finite = out[np.isfinite(out)]
    assert np.all(finite >= -1.0) and np.all(finite <= 1.0)
    assert np.isnan(out[0, 2])   # NaN in -> NaN out
    assert np.isnan(out[0, 1])   # zero denominator -> NaN, not inf


def test_level2_scaling_maps_dn_into_reflectance_range():
    spec = spec_for("landsat-8")
    dn = np.array([[7273, 20000]], dtype=np.uint16)  # typical C2 L2 surface values
    out = to_reflectance(dn, spec)
    assert np.all(out > -0.2) and np.all(out < 1.0)


def test_level1_mss_is_left_unscaled():
    """MSS Level-1 has no published C2 scale/offset here; DN passes through."""
    spec = spec_for("landsat-1")
    dn = np.array([[100, 200]], dtype=np.uint16)
    out = to_reflectance(dn, spec)
    assert out.tolist() == [[100.0, 200.0]]


def test_fill_value_zero_becomes_nan_for_both_levels():
    for platform in ("landsat-1", "landsat-8"):
        out = to_reflectance(np.array([[0, 5000]], dtype=np.uint16), spec_for(platform))
        assert np.isnan(out[0, 0])
        assert np.isfinite(out[0, 1])


def test_cloud_mask_rejects_the_right_bits():
    qa = np.array([[0, QA_FILL, QA_CLOUD, QA_CLOUD_SHADOW, 1 << 6]], dtype=np.uint16)
    clear = cloud_mask(qa)
    assert clear[0, 0]        # nothing set -> usable
    assert not clear[0, 1]    # fill
    assert not clear[0, 2]    # cloud
    assert not clear[0, 3]    # cloud shadow
    assert clear[0, 4]        # bit 6 is "clear", not a reject bit
