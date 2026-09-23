"""Per-sensor Landsat band mapping and water indices.

CLAUDE.md §2 calls this out explicitly:

    *"Per-sensor band mapping — the band names differ per mission and this is
    the single most common source of silent bugs. MSS (Landsat 1) has no SWIR,
    so its water index must be handled separately from the TM/ETM+/OLI path."*

So the mapping lives in exactly one place — :data:`SENSORS` — and is covered by
``tests/test_landsat_bands.py``. Nothing else in the project is allowed to
guess a band name.

Two water indices are used, chosen by what the instrument actually carries:

======================  ==========  =======================================
Instrument              Missions    Index
======================  ==========  =======================================
MSS (no SWIR)           1, 2, 3,    NDWI  = (Green - NIR)   / (Green + NIR)
                        4, 5        McFeeters (1996)
TM / ETM+ / OLI         4, 5, 7,    MNDWI = (Green - SWIR1) / (Green + SWIR1)
                        8, 9        Xu (2006)
======================  ==========  =======================================

MNDWI is the primary index for this project; NDWI is the documented fallback
for the 1972-1983 MSS era, which has no SWIR channel at all. The two indices
are not numerically identical, which is why Stage 2 thresholds each monthly
composite with its own Otsu threshold rather than one fixed cut.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

# Landsat Collection 2 Level-2 surface-reflectance DN -> reflectance.
# Constant across TM / ETM+ / OLI in Collection 2 (USGS, 2021).
C2_L2_SCALE = 2.75e-05
C2_L2_OFFSET = -0.2


@dataclass(frozen=True)
class SensorSpec:
    """How to build a water index for one Landsat instrument family.

    Attributes
    ----------
    instrument
        ``"MSS"``, ``"TM"``, ``"ETM+"`` or ``"OLI"``.
    collection
        Planetary Computer STAC collection id holding this instrument.
    green_asset
        STAC asset key for the green band.
    dark_asset
        STAC asset key for the band in which water is *darkest* — SWIR1 where
        it exists, otherwise the longest NIR band.
    index
        ``"MNDWI"`` or ``"NDWI"``.
    level
        ``"L2"`` (surface reflectance, scaled) or ``"L1"`` (quantised DN).
    native_res_m
        Native ground sample distance, metres. MSS is 60 m and is resampled to
        the 30 m archive standard during acquisition (CLAUDE.md §2).
    """

    instrument: str
    collection: str
    green_asset: str
    dark_asset: str
    index: str
    level: str
    native_res_m: float


# Keyed by STAC `platform` property, which is "landsat-1" ... "landsat-9".
SENSORS: dict[str, SensorSpec] = {
    # ---- MSS era: no SWIR anywhere, 60 m, Level-1 only -------------------
    "landsat-1": SensorSpec("MSS", "landsat-c2-l1", "green", "nir09", "NDWI", "L1", 60.0),
    "landsat-2": SensorSpec("MSS", "landsat-c2-l1", "green", "nir09", "NDWI", "L1", 60.0),
    "landsat-3": SensorSpec("MSS", "landsat-c2-l1", "green", "nir09", "NDWI", "L1", 60.0),
    # ---- TM / ETM+ / OLI: SWIR1 present, 30 m, Level-2 SR ----------------
    "landsat-4": SensorSpec("TM", "landsat-c2-l2", "green", "swir16", "MNDWI", "L2", 30.0),
    "landsat-5": SensorSpec("TM", "landsat-c2-l2", "green", "swir16", "MNDWI", "L2", 30.0),
    "landsat-7": SensorSpec("ETM+", "landsat-c2-l2", "green", "swir16", "MNDWI", "L2", 30.0),
    "landsat-8": SensorSpec("OLI", "landsat-c2-l2", "green", "swir16", "MNDWI", "L2", 30.0),
    "landsat-9": SensorSpec("OLI", "landsat-c2-l2", "green", "swir16", "MNDWI", "L2", 30.0),
}

# Landsat 4 and 5 also flew an MSS. Those scenes live in landsat-c2-l1 and must
# use the MSS spec, not the TM spec — resolved by `spec_for()`, which looks at
# the instrument as well as the platform.
_MSS_SPEC = SENSORS["landsat-1"]


def spec_for(platform: str, instruments: list[str] | None = None) -> SensorSpec:
    """Resolve the :class:`SensorSpec` for a STAC item.

    Parameters
    ----------
    platform
        STAC ``platform`` property, e.g. ``"landsat-5"``.
    instruments
        STAC ``instruments`` property, e.g. ``["tm"]`` or ``["mss"]``. Needed
        because Landsat 4 and 5 carried *both* MSS and TM, and the correct
        index depends on which one produced the scene.

    Raises
    ------
    KeyError
        If the platform is not a known Landsat mission — better to fail loudly
        than to silently map the wrong band.
    """
    platform = platform.lower().strip()
    if instruments and any("mss" in i.lower() for i in instruments):
        return _MSS_SPEC
    if platform not in SENSORS:
        raise KeyError(
            f"unknown Landsat platform {platform!r}; known: {sorted(SENSORS)}. "
            "Refusing to guess a band mapping."
        )
    return SENSORS[platform]


def to_reflectance(dn: np.ndarray, spec: SensorSpec) -> np.ndarray:
    """Convert raw DN to (approximate) reflectance for the given sensor.

    Level-2 products use the published Collection 2 scale and offset. Level-1
    MSS products are returned as float DN: the per-composite Otsu threshold
    applied in Stage 2 re-derives the land/water split for every month, so it
    absorbs the missing radiometric rescaling. This approximation is recorded
    as a known limitation in ``docs/NOTES.md``.

    Parameters
    ----------
    dn
        Raw band array, any shape. Zero is the Collection 2 fill value and
        becomes NaN.
    spec
        The sensor spec that produced ``dn``.

    Returns
    -------
    np.ndarray
        float32 array, same shape, fill pixels set to NaN.
    """
    out = dn.astype(np.float32)
    out[dn == 0] = np.nan  # Collection 2 fill value for both L1 and L2
    if spec.level == "L2":
        out = out * C2_L2_SCALE + C2_L2_OFFSET
    return out


def water_index(green: np.ndarray, dark: np.ndarray, spec: SensorSpec) -> np.ndarray:
    """Normalised-difference water index for one scene.

    Computes ``(green - dark) / (green + dark)`` — MNDWI when ``dark`` is
    SWIR1, NDWI when ``dark`` is NIR. Water is **positive**, land negative.

    Parameters
    ----------
    green, dark
        Reflectance arrays of identical shape, already passed through
        :func:`to_reflectance`.
    spec
        Sensor spec, used only to label which index this is.

    Returns
    -------
    np.ndarray
        float32 in [-1, 1], NaN where either input is NaN or the denominator
        vanishes. Values are clipped to [-1, 1]: surface-reflectance noise can
        push the ratio outside that range where the denominator is near zero.
    """
    green = green.astype(np.float32)
    dark = dark.astype(np.float32)
    denom = green + dark
    with np.errstate(divide="ignore", invalid="ignore"):
        idx = (green - dark) / denom
    idx[~np.isfinite(idx)] = np.nan
    idx[np.abs(denom) < 1e-6] = np.nan
    return np.clip(idx, -1.0, 1.0)


# ---------------------------------------------------------------------------
# Collection 2 QA_PIXEL bit flags (identical across L1 and L2 products)
# ---------------------------------------------------------------------------
QA_FILL = 1 << 0
QA_DILATED_CLOUD = 1 << 1
QA_CIRRUS = 1 << 2
QA_CLOUD = 1 << 3
QA_CLOUD_SHADOW = 1 << 4
QA_SNOW = 1 << 5

#: Any of these bits set means the pixel is unusable for water mapping.
QA_REJECT = QA_FILL | QA_DILATED_CLOUD | QA_CIRRUS | QA_CLOUD | QA_CLOUD_SHADOW | QA_SNOW


def cloud_mask(qa_pixel: np.ndarray) -> np.ndarray:
    """Boolean mask of *usable* pixels from a Collection 2 ``QA_PIXEL`` band.

    Parameters
    ----------
    qa_pixel
        The QA band as unsigned integers, same shape as the reflectance bands.

    Returns
    -------
    np.ndarray
        Boolean array, True where the pixel is clear land or clear water.
    """
    qa = qa_pixel.astype(np.uint16)
    return (qa & QA_REJECT) == 0
