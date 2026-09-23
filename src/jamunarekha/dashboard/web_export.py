"""Stage 5 bridge — package the pipeline's outputs for the static web dashboard.

The Next.js site under ``web/`` computes nothing. It renders what the Python
pipeline has already written, so this module is the single place where the two
halves meet. It reads three Stage 4 / Stage 3 artefacts:

``outputs/tables/at_risk_households_<month>.csv``   the DDM handoff table
``outputs/tables/risk_summary_<month>.json``        forecast provenance
``outputs/tables/metrics_<model>_*.json``           test-split accuracy
``outputs/predictions/change_zones_<month>.geojson`` forecast zones, cut on unions

and writes, into ``paths.web_data`` (``web/public/data/``):

``forecast.json``                     everything the page renders
``jamunarekha_at_risk_<month>.csv``   the DDM CSV, copied byte for byte
``zones_<month>.geojson``             the zones, compacted for the web map

The CSV is copied rather than regenerated so that the file an officer
downloads from the site is *the same file* the pipeline produced — its SHA-256
is recorded in ``forecast.json`` and printed in the page footer.

Values keep full source precision. Rounding is a presentation decision and
belongs in the page, not in the data.

The output is deterministic (no timestamps), so it can be committed and the
site can be built on a host that has Node but no Python.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import shutil
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import shapely
from shapely.geometry import mapping

from jamunarekha.utils.logging import get_logger

logger = get_logger("jamunarekha.web_export")

#: Bump when the shape of forecast.json changes; the site refuses to build
#: against a schema it does not know. 2: OSM mapping density and Bengali
#: names. 3: the map (``map`` block and the zones file).
SCHEMA_VERSION = 3

#: Columns of the Stage 4 table, in the order Stage 4 writes them.
REQUIRED_COLUMNS = (
    "forecast_month",
    "division",
    "district",
    "upazila",
    "union",
    "gid_union",
    "erosion_ha",
    "buildings_osm",
    "accretion_ha",
    "net_land_change_ha",
    "households_est",
    "persons_est",
    "osm_completeness_assumed",
    "osm_buildings_per_km2",
    "osm_measured_km2",
    "osm_mapping",
    "division_bn",
    "district_bn",
    "upazila_bn",
    "union_bn",
)
_INTEGER_COLUMNS = ("buildings_osm", "households_est", "persons_est")
_FLOAT_COLUMNS = (
    "erosion_ha",
    "accretion_ha",
    "net_land_change_ha",
    "osm_completeness_assumed",
    "osm_measured_km2",
)
#: May legitimately be empty: density where it was not measured, a Bengali
#: name where no match was confident. Everything else must be present.
_NULLABLE_COLUMNS = ("osm_buildings_per_km2", "division_bn", "district_bn", "upazila_bn", "union_bn")
_TEXT_COLUMNS = ("forecast_month", "division", "district", "upazila", "union", "gid_union", "osm_mapping")
MAPPING_LEVELS = ("low", "medium", "high", "not measured")

#: Web map zones: simplified by this many metres in the metric CRS (the
#: zones are traced from 120 m pixels, so 30 m loses nothing visible) and
#: coordinates rounded to this many decimals of a degree (about a metre).
ZONE_SIMPLIFY_M = 30.0
ZONE_DIGITS = 5
_KIND_CODES = {"erosion": "e", "accretion": "a"}
_MONTH = re.compile(r"(\d{4}-\d{2})")


class WebExportError(ValueError):
    """The pipeline outputs are missing or inconsistent; refuse to publish them."""


def display_name(name: str) -> str:
    """Make a GADM place name readable without changing its spelling.

    GADM joins multi-word union names in CamelCase (``CharBhurungamari``,
    ``SaheberAlga``) and glues qualifiers on (``Sultanganj(Part)``). A space is
    inserted at each lower-to-upper boundary and before an opening bracket.
    Nothing else is touched — the original name stays in ``union`` and in the
    CSV, so it still matches GADM and the Stage 4 table exactly.
    """
    spaced = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", name)
    spaced = re.sub(r"(?<=\S)\(", " (", spaced)
    return re.sub(r"\s+", " ", spaced).strip()


def month_of(path: Path) -> str:
    """``YYYY-MM`` from a Stage 4 file name, e.g. ``at_risk_households_2025-03.csv``."""
    match = _MONTH.search(path.stem)
    if not match:
        raise WebExportError(f"no YYYY-MM month in file name {path.name!r}")
    return match.group(1)


def latest_table(tables_dir: Path) -> Path:
    """The most recent forecast table, by the month in its file name."""
    tables = sorted(tables_dir.glob("at_risk_households_*.csv"), key=month_of)
    if not tables:
        raise WebExportError(
            f"no at_risk_households_*.csv in {tables_dir} — run Stage 4 first"
        )
    return tables[-1]


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 16), b""):
            digest.update(block)
    return digest.hexdigest()


def load_rows(csv_path: Path) -> list[dict]:
    """Read and validate the Stage 4 table.

    Raises
    ------
    WebExportError
        On a missing column, a missing value, a duplicated union, a negative
        count, an unknown mapping level, or a row from a different forecast
        month. Each of these would otherwise reach a disaster officer as a
        wrong number with no warning.
    """
    # round_trip: pandas' default float parser is fast but not exact — on the
    # 2025-03 table it misread 102 values by one unit in the last place. Stage 4
    # writes shortest round-trip decimals, so the exact parse recovers exactly
    # the numbers it computed, and the site's filtered CSVs match the original.
    frame = pd.read_csv(
        csv_path, encoding="utf-8-sig", dtype={"gid_union": str}, float_precision="round_trip"
    )

    missing = [c for c in REQUIRED_COLUMNS if c not in frame.columns]
    if missing:
        raise WebExportError(f"{csv_path.name}: missing columns {missing}")
    # The site rebuilds filtered downloads in exactly this order, so a table
    # with its columns in any other order would make them disagree with it.
    if list(frame.columns) != list(REQUIRED_COLUMNS):
        raise WebExportError(
            f"{csv_path.name}: columns are not in the order the site reproduces: {list(frame.columns)}"
        )
    required = [c for c in REQUIRED_COLUMNS if c not in _NULLABLE_COLUMNS]
    if frame[required].isna().any().any():
        bad = [c for c in required if frame[c].isna().any()]
        raise WebExportError(f"{csv_path.name}: missing values in {bad}")
    unknown = set(frame["osm_mapping"]) - set(MAPPING_LEVELS)
    if unknown:
        raise WebExportError(f"{csv_path.name}: unknown osm_mapping values {sorted(unknown)}")
    measured = frame["osm_mapping"] != "not measured"
    if (frame["osm_buildings_per_km2"].isna() & measured).any() or (
        frame["osm_buildings_per_km2"].notna() & ~measured
    ).any():
        raise WebExportError(
            f"{csv_path.name}: osm_buildings_per_km2 must be given exactly where osm_mapping is measured"
        )
    if (frame["osm_buildings_per_km2"].dropna() < 0).any():
        raise WebExportError(f"{csv_path.name}: negative mapping density")
    if frame["gid_union"].duplicated().any():
        raise WebExportError(f"{csv_path.name}: a union appears more than once")
    if (frame[list(_INTEGER_COLUMNS)] < 0).any().any():
        raise WebExportError(f"{csv_path.name}: negative building or household count")
    months = frame["forecast_month"].astype(str).unique().tolist()
    if len(months) != 1 or months[0] != month_of(csv_path):
        raise WebExportError(
            f"{csv_path.name}: forecast_month values {months} do not match the file name"
        )

    rows = []
    for record in frame.to_dict(orient="records"):
        row = {column: record[column] for column in REQUIRED_COLUMNS}
        for column in _INTEGER_COLUMNS:
            row[column] = int(row[column])
        for column in _FLOAT_COLUMNS:
            value = float(row[column])
            if not math.isfinite(value):
                raise WebExportError(f"{csv_path.name}: non-finite {column}")
            row[column] = value
        for column in _TEXT_COLUMNS:
            row[column] = str(row[column])
        # JSON has no NaN: an empty cell becomes null.
        density = row["osm_buildings_per_km2"]
        row["osm_buildings_per_km2"] = None if pd.isna(density) else float(density)
        for column in ("division_bn", "district_bn", "upazila_bn", "union_bn"):
            value = row[column]
            row[column] = None if pd.isna(value) or not str(value).strip() else str(value)
        row["union_display"] = display_name(row["union"])
        row["upazila_display"] = display_name(row["upazila"])
        rows.append(row)
    return rows


def pick_metrics(tables_dir: Path, model: str) -> tuple[Path, dict]:
    """The test-split metrics file for the model that made this forecast."""
    candidates = sorted(tables_dir.glob(f"metrics_{model}_*.json"))
    if not candidates:
        raise WebExportError(f"no metrics_{model}_*.json in {tables_dir}")
    if len(candidates) > 1:
        logger.warning(
            "several metrics files for %s; using %s", model, candidates[-1].name
        )
    path = candidates[-1]
    return path, json.loads(path.read_text(encoding="utf-8"))


def build_payload(
    csv_path: Path,
    summary: dict,
    metrics: dict,
    persons_per_household: float,
    download_name: str,
) -> dict:
    """Assemble ``forecast.json`` from the validated pipeline outputs."""
    rows = load_rows(csv_path)
    month = month_of(csv_path)
    if summary.get("forecast_month") != month:
        raise WebExportError(
            f"risk summary is for {summary.get('forecast_month')}, table is for {month}"
        )
    if not summary.get("osm_mapping_bands"):
        raise WebExportError(
            "risk summary does not record the OSM mapping bands — re-run Stage 4"
        )
    if metrics.get("model") != summary.get("model"):
        raise WebExportError(
            f"metrics are for {metrics.get('model')}, forecast used {summary.get('model')}"
        )

    tiles = summary.get("tiles", [])
    reference_months = sorted({t.get("reference_month") for t in tiles if t.get("reference_month")})
    anchor_months = sorted({t.get("anchor_month") for t in tiles if t.get("anchor_month")})

    horizons = metrics.get("per_horizon", [])
    at_horizon = {int(h["horizon_months"]): h for h in horizons}
    out_frames = int(metrics.get("out_frames", 3))
    final = at_horizon.get(out_frames, {})

    return {
        "schema": SCHEMA_VERSION,
        "forecast": {
            "month": month,
            "anchor_months": anchor_months,
            "reference_months": reference_months,
            "seasonally_matched": all(t.get("seasonally_matched") for t in tiles) if tiles else False,
            "horizon_months": out_frames,
            "model": summary.get("model"),
            "water_threshold": summary.get("water_threshold"),
            # Totals over the whole forecast, INCLUDING area outside Bangladeshi
            # union boundaries (the reach runs into India). The page's own totals
            # are summed from `rows`, which cover only union parishads.
            "total_erosion_ha": summary.get("total_erosion_ha"),
            "total_accretion_ha": summary.get("total_accretion_ha"),
            "n_polygons": summary.get("n_polygons"),
        },
        "accuracy": {
            "split": "test 2018-2024",
            "n_windows": metrics.get("n_test_windows"),
            "bank_f1": metrics.get("test_metrics", {}).get("test/bank_f1"),
            "mde_m": metrics.get("test_metrics", {}).get("test/mde_m"),
            "bank_f1_at_horizon": final.get("bank_f1"),
            "mde_m_at_horizon": final.get("mde_m"),
            "resolution_m": metrics.get("resolution_m"),
            "crop_size": metrics.get("crop_size"),
        },
        "assumptions": {
            "persons_per_household": persons_per_household,
            "osm_completeness": sorted({r["osm_completeness_assumed"] for r in rows}),
            # The band edges Stage 4 applied, from its own summary: the page
            # states them, and the config may have changed since the run.
            "osm_mapping_bands": summary.get("osm_mapping_bands"),
        },
        "names": {
            "source": (summary.get("bn_names") or {}).get("source"),
            "unions_named": sum(1 for r in rows if r["union_bn"]),
            "portal_checks": (summary.get("bn_names") or {}).get("portal_checks"),
        },
        "source": {
            "file": csv_path.name,
            "download": download_name,
            "sha256": sha256_of(csv_path),
            "rows": len(rows),
        },
        "rows": rows,
    }


def compact_zones(
    zones_path: Path,
    known_unions: set[str],
    metric_crs: str,
    simplify_m: float = ZONE_SIMPLIFY_M,
    digits: int = ZONE_DIGITS,
) -> tuple[str, dict]:
    """The Stage 4 map zones as compact GeoJSON text for the web map.

    Properties are shortened to ``k`` (``e`` erosion / ``a`` accretion),
    ``ha`` (Stage 4's area, measured before simplification, to 0.1 ha) and
    ``u`` (the union's GADM id, or null outside every union). A 4.6 MB layer
    comes to about 2.3 MB, 0.5 MB compressed as the site serves it.

    Raises
    ------
    WebExportError
        If the zones are not in EPSG:4326, carry an unknown kind, or name a
        union that is not in the table — the map and the table must agree.
    """
    zones = gpd.read_file(zones_path)
    if zones.crs is None or zones.crs.to_epsg() != 4326:
        raise WebExportError(f"{zones_path.name}: expected EPSG:4326, found {zones.crs}")
    unknown = set(zones["kind"]) - set(_KIND_CODES)
    if unknown:
        raise WebExportError(f"{zones_path.name}: unknown zone kinds {sorted(unknown)}")
    stray = set(zones["gid_union"].dropna()) - known_unions
    if stray:
        raise WebExportError(
            f"{zones_path.name}: zones name {len(stray)} unions that are not in the table"
        )

    metric = zones.to_crs(metric_crs)
    metric["geometry"] = metric.geometry.simplify(simplify_m, preserve_topology=True)
    metric = metric[~metric.geometry.is_empty]
    wgs84 = metric.to_crs("EPSG:4326")
    geometries = shapely.transform(wgs84.geometry.to_numpy(), lambda xy: np.round(xy, digits))

    features = []
    for (kind, area, gid), geometry in zip(
        wgs84[["kind", "area_ha", "gid_union"]].itertuples(index=False), geometries
    ):
        features.append(
            {
                "type": "Feature",
                "properties": {
                    "k": _KIND_CODES[kind],
                    "ha": round(float(area), 1),
                    "u": None if pd.isna(gid) else str(gid),
                },
                "geometry": mapping(geometry),
            }
        )
    minx, miny, maxx, maxy = (round(float(v), 4) for v in wgs84.total_bounds)
    text = json.dumps({"type": "FeatureCollection", "features": features}, separators=(",", ":"))
    return text, {"features": len(features), "bbox": [minx, miny, maxx, maxy], "simplify_m": simplify_m}


def export(cfg, month: str | None = None) -> Path:
    """Write ``forecast.json`` and the CSV copy into ``paths.web_data``.

    Parameters
    ----------
    cfg
        Loaded project config; paths come from it (CLAUDE.md §4).
    month
        ``YYYY-MM`` to export. Defaults to the most recent Stage 4 table.

    Returns
    -------
    Path
        The written ``forecast.json``.
    """
    tables_dir = Path(cfg.paths.tables)
    out_dir = Path(cfg.paths.web_data)

    csv_path = tables_dir / f"at_risk_households_{month}.csv" if month else latest_table(tables_dir)
    if not csv_path.exists():
        raise WebExportError(f"{csv_path} does not exist")
    month = month_of(csv_path)

    summary_path = tables_dir / f"risk_summary_{month}.json"
    if not summary_path.exists():
        raise WebExportError(f"{summary_path.name} missing — re-run Stage 4 for {month}")
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    metrics_path, metrics = pick_metrics(tables_dir, str(summary.get("model")))

    download_name = f"jamunarekha_at_risk_{month}.csv"
    payload = build_payload(
        csv_path,
        summary,
        metrics,
        persons_per_household=float(cfg.risk.persons_per_household),
        download_name=download_name,
    )
    payload["source"]["metrics_file"] = metrics_path.name
    payload["source"]["summary_file"] = summary_path.name

    zones_path = Path(cfg.paths.predictions) / f"change_zones_{month}.geojson"
    if not zones_path.exists():
        raise WebExportError(f"{zones_path.name} missing — re-run Stage 4 for {month}")
    zones_text, zones_stats = compact_zones(
        zones_path, {r["gid_union"] for r in payload["rows"]}, str(cfg.study_area.target_crs)
    )
    zones_name = f"zones_{month}.geojson"
    payload["map"] = {"file": zones_name, **zones_stats}

    out_dir.mkdir(parents=True, exist_ok=True)
    # Remove files from earlier months so the site never ships two forecasts.
    for pattern, keep in (("jamunarekha_at_risk_*.csv", download_name), ("zones_*.geojson", zones_name)):
        for stale in out_dir.glob(pattern):
            if stale.name != keep:
                stale.unlink()
    shutil.copyfile(csv_path, out_dir / download_name)
    (out_dir / zones_name).write_text(zones_text, encoding="utf-8")

    out_path = out_dir / "forecast.json"
    out_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
    )
    logger.info(
        "wrote %s (%d unions, forecast %s) and %s",
        out_path, payload["source"]["rows"], month, download_name,
    )
    return out_path
