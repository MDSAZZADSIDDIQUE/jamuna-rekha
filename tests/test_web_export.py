"""The bridge from the Python pipeline to the web dashboard.

The site computes nothing, so anything wrong in ``forecast.json`` reaches a
disaster officer unchallenged. These tests pin the validation (bad tables are
refused, not published), provenance (the downloadable CSV is the pipeline's own
file) and the name cleanup (readable, but never renamed).
"""

from __future__ import annotations

import json

import pytest
from omegaconf import OmegaConf

from jamunarekha.dashboard.web_export import (
    WebExportError,
    build_payload,
    compact_zones,
    display_name,
    export,
    sha256_of,
)

HEADER = (
    "forecast_month,division,district,upazila,union,gid_union,erosion_ha,"
    "buildings_osm,accretion_ha,net_land_change_ha,households_est,persons_est,"
    "osm_completeness_assumed,osm_buildings_per_km2,osm_measured_km2,osm_mapping,"
    "division_bn,district_bn,upazila_bn,union_bn"
)
ROWS = [
    "2025-03,Rangpur,Kurigram,Bhurungamari,Shilkhuri,BGD.6.3.1.9_1,1735.7640297944888,1206,0.0,-1735.7640297944888,1206,5427,1.0,"
    "171.5,40.2,high,রংপুর,কুড়িগ্রাম,ভূরুঙ্গামারী,শিলখুড়ি",
    "2025-03,Rajshahi,Bogra,Sariakandi,Chaluabari,BGD.5.1.9.3_1,1588.9,1,12.5,-1576.4,1,5,1.0,"
    "0.9,55.1,low,রাজশাহী,বগুড়া,সারিয়াকান্দি,চালুয়াবাড়ী",
    # Not measured, and no confident Bengali name: both empty, both legitimate.
    "2025-03,Rangpur,Kurigram,Chilmari,SaheberAlga,BGD.6.3.2.7_1,1714.2,0,3.0,-1711.2,0,0,1.0,"
    ",0.4,not measured,রংপুর,কুড়িগ্রাম,চিলমারী,",
]
SUMMARY = {
    "forecast_month": "2025-03",
    "model": "convlstm",
    "water_threshold": 0.55,
    "total_erosion_ha": 88820.6,
    "total_accretion_ha": 12945.6,
    "n_polygons": 4647,
    "osm_mapping_bands": {"low_below": 10.0, "high_from": 100.0, "min_area_km2": 1.0},
    "tiles": [
        {"tile": "T00_00", "anchor_month": "2024-12", "forecast_month": "2025-03",
         "reference_month": "2024-03", "seasonally_matched": True},
    ],
}
METRICS = {
    "model": "convlstm",
    "out_frames": 3,
    "n_test_windows": 4480,
    "resolution_m": 120.0,
    "crop_size": 128,
    "test_metrics": {"test/bank_f1": 0.583, "test/mde_m": 696.0},
    "per_horizon": [
        {"horizon_months": 1, "bank_f1": 0.631, "mde_m": 634.3},
        {"horizon_months": 3, "bank_f1": 0.568, "mde_m": 759.6},
    ],
}


def _write_csv(path, rows=ROWS, header=HEADER):
    # Stage 4 writes UTF-8 with a BOM and CRLF, so the fixture does too.
    path.write_bytes(("\ufeff" + "\r\n".join([header, *rows]) + "\r\n").encode("utf-8"))
    return path


def _payload(tmp_path, **overrides):
    csv_path = _write_csv(tmp_path / "at_risk_households_2025-03.csv", **overrides)
    return build_payload(csv_path, SUMMARY, METRICS, 4.5, "jamunarekha_at_risk_2025-03.csv")


# ------------------------------------------------------------ display names
@pytest.mark.parametrize(
    "raw,expected",
    [
        ("CharBhurungamari", "Char Bhurungamari"),
        ("SaheberAlga", "Saheber Alga"),
        ("Sultanganj(Part)", "Sultanganj (Part)"),
        ("Shah-Bandegi", "Shah-Bandegi"),
        ("Kurigram", "Kurigram"),
    ],
)
def test_display_name_splits_gadm_camelcase_only(raw, expected):
    assert display_name(raw) == expected


def test_original_names_are_kept_alongside_display_names(tmp_path):
    row = next(r for r in _payload(tmp_path)["rows"] if r["union"] == "SaheberAlga")
    assert row["union_display"] == "Saheber Alga"
    assert row["union"] == "SaheberAlga"      # still matches GADM and the CSV


# ----------------------------------------------------------------- payload
def test_payload_carries_rows_at_full_precision(tmp_path):
    payload = _payload(tmp_path)
    assert payload["schema"] == 3
    assert payload["source"]["rows"] == 3
    shilkhuri = next(r for r in payload["rows"] if r["union"] == "Shilkhuri")
    assert shilkhuri["erosion_ha"] == 1735.7640297944888   # rounding is the page's job
    assert isinstance(shilkhuri["buildings_osm"], int)


def test_payload_numbers_are_exactly_the_csv_decimals(tmp_path):
    # pandas' default float parser reads both of these one unit in the last
    # place off. The site rebuilds filtered CSVs from forecast.json, and they
    # must match the lines of the original file exactly.
    tail = ",,0.0,not measured,,,,"
    rows = [
        "2025-03,Rangpur,Gaibandha,Gobindaganj,TalukKanupur,BGD.6.2.3.18_1,0.0,0,1.9656597836708474,1.9656597836708474,0,0,1.0" + tail,
        "2025-03,Rangpur,Kurigram,Raumari,Saulmari,BGD.6.3.8.5_1,0.0,0,111.13338633732901,111.13338633732901,0,0,1.0" + tail,
    ]
    accretion = {r["union"]: r["accretion_ha"] for r in _payload(tmp_path, rows=rows)["rows"]}
    assert repr(accretion["TalukKanupur"]) == "1.9656597836708474"
    assert repr(accretion["Saulmari"]) == "111.13338633732901"


def test_empty_density_and_unmatched_names_become_json_null(tmp_path):
    payload = _payload(tmp_path)
    by_union = {r["union"]: r for r in payload["rows"]}
    assert by_union["SaheberAlga"]["osm_buildings_per_km2"] is None
    assert by_union["SaheberAlga"]["osm_mapping"] == "not measured"
    assert by_union["SaheberAlga"]["union_bn"] is None
    assert by_union["Chaluabari"]["osm_buildings_per_km2"] == 0.9
    assert by_union["Chaluabari"]["union_bn"] == "চালুয়াবাড়ী"
    # Must still serialise as strict JSON: NaN is not JSON.
    json.dumps(payload, allow_nan=False)


def test_columns_out_of_order_are_refused(tmp_path):
    names = HEADER.split(",")
    names[13], names[14] = names[14], names[13]
    with pytest.raises(WebExportError, match="order"):
        _payload(tmp_path, header=",".join(names))


def test_unknown_mapping_level_is_refused(tmp_path):
    rows = [ROWS[0].replace(",high,", ",excellent,")]
    with pytest.raises(WebExportError, match="osm_mapping"):
        _payload(tmp_path, rows=rows)


def test_density_without_a_measured_level_is_refused(tmp_path):
    rows = [ROWS[0].replace(",high,", ",not measured,")]
    with pytest.raises(WebExportError, match="exactly where"):
        _payload(tmp_path, rows=rows)


def test_payload_reports_accuracy_at_the_forecast_horizon(tmp_path):
    accuracy = _payload(tmp_path)["accuracy"]
    assert accuracy["mde_m_at_horizon"] == 759.6
    assert accuracy["bank_f1_at_horizon"] == 0.568


def test_payload_records_the_seasonal_reference_month(tmp_path):
    forecast = _payload(tmp_path)["forecast"]
    assert forecast["reference_months"] == ["2024-03"]
    assert forecast["seasonally_matched"] is True


# -------------------------------------------------------------- validation
def test_missing_column_is_refused(tmp_path):
    header = HEADER.replace(",households_est", "")
    rows = [",".join(r.split(",")[:10] + r.split(",")[11:]) for r in ROWS]
    with pytest.raises(WebExportError, match="missing columns"):
        _payload(tmp_path, rows=rows, header=header)


def test_missing_value_is_refused(tmp_path):
    rows = [ROWS[0].replace(",1206,0.0,", ",,0.0,")]
    with pytest.raises(WebExportError, match="missing values"):
        _payload(tmp_path, rows=rows)


def test_duplicate_union_is_refused(tmp_path):
    with pytest.raises(WebExportError, match="more than once"):
        _payload(tmp_path, rows=[ROWS[0], ROWS[0]])


def test_month_mismatch_between_table_and_summary_is_refused(tmp_path):
    csv_path = _write_csv(tmp_path / "at_risk_households_2025-03.csv")
    with pytest.raises(WebExportError, match="risk summary is for"):
        build_payload(csv_path, {**SUMMARY, "forecast_month": "2024-12"}, METRICS, 4.5, "x.csv")


def test_metrics_from_a_different_model_are_refused(tmp_path):
    csv_path = _write_csv(tmp_path / "at_risk_households_2025-03.csv")
    with pytest.raises(WebExportError, match="metrics are for"):
        build_payload(csv_path, SUMMARY, {**METRICS, "model": "timesformer"}, 4.5, "x.csv")


# ------------------------------------------------------------------ export
def test_export_copies_the_csv_byte_for_byte_and_records_its_hash(tmp_path):
    tables = tmp_path / "tables"
    tables.mkdir()
    web = tmp_path / "web"
    source = _write_csv(tables / "at_risk_households_2025-03.csv")
    (tables / "risk_summary_2025-03.json").write_text(json.dumps(SUMMARY), encoding="utf-8")
    (tables / "metrics_convlstm_crop128.json").write_text(json.dumps(METRICS), encoding="utf-8")
    (web).mkdir()
    (web / "jamunarekha_at_risk_2024-12.csv").write_text("stale", encoding="utf-8")

    cfg = _export_cfg(tmp_path, tables, web)
    out = export(cfg)

    copied = web / "jamunarekha_at_risk_2025-03.csv"
    assert copied.read_bytes() == source.read_bytes()
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["source"]["sha256"] == sha256_of(source)
    assert not (web / "jamunarekha_at_risk_2024-12.csv").exists()   # one forecast only


def test_export_output_is_deterministic(tmp_path):
    """No timestamps: the file can be committed without churn."""
    tables = tmp_path / "tables"
    tables.mkdir()
    _write_csv(tables / "at_risk_households_2025-03.csv")
    (tables / "risk_summary_2025-03.json").write_text(json.dumps(SUMMARY), encoding="utf-8")
    (tables / "metrics_convlstm_crop128.json").write_text(json.dumps(METRICS), encoding="utf-8")
    cfg = _export_cfg(tmp_path, tables, tmp_path / "web")
    first = export(cfg).read_bytes()
    second = export(cfg).read_bytes()
    assert first == second


# --------------------------------------------------------------------- map
def _zones(path, rows):
    """A tiny Stage 4 zones file: EPSG:4326 squares near Chilmari."""
    import geopandas as gpd
    from shapely.geometry import box

    frame = gpd.GeoDataFrame(
        [{"kind": k, "area_ha": a, "gid_union": u} for k, a, u, _ in rows],
        geometry=[box(*b) for *_, b in rows],
        crs="EPSG:4326",
    )
    frame.to_file(path, driver="GeoJSON")
    return path


_ZONE_ROWS = [
    ("erosion", 1735.76, "BGD.6.3.1.9_1", (89.6, 25.5, 89.612345678, 25.51)),
    ("accretion", 12.34, None, (89.7, 25.6, 89.705, 25.605)),       # outside every union
]


def _export_cfg(tmp_path, tables, web):
    predictions = tmp_path / "predictions"
    predictions.mkdir(exist_ok=True)
    rows = [("erosion", 1735.76, "BGD.6.3.1.9_1", (89.6, 25.5, 89.61, 25.51))]
    _zones(predictions / "change_zones_2025-03.geojson", rows)
    return OmegaConf.create(
        {"paths": {"tables": str(tables), "web_data": str(web), "predictions": str(predictions)},
         "risk": {"persons_per_household": 4.5},
         "study_area": {"target_crs": "EPSG:32645"}}
    )


def test_zones_are_compacted_for_the_map(tmp_path):
    path = _zones(tmp_path / "z.geojson", _ZONE_ROWS)
    text, stats = compact_zones(path, {"BGD.6.3.1.9_1"}, "EPSG:32645")
    data = json.loads(text)
    assert stats["features"] == 2 == len(data["features"])
    first, second = data["features"]
    assert first["properties"] == {"k": "e", "ha": 1735.8, "u": "BGD.6.3.1.9_1"}
    assert second["properties"] == {"k": "a", "ha": 12.3, "u": None}
    xs = [x for ring in first["geometry"]["coordinates"] for x, _ in ring]
    assert all(round(x, 5) == x for x in xs)                   # about a metre
    assert " " not in text                                     # no whitespace to ship
    assert stats["bbox"][0] == 89.6 and stats["bbox"][3] == 25.605


def test_zones_naming_a_union_missing_from_the_table_are_refused(tmp_path):
    path = _zones(tmp_path / "z.geojson", _ZONE_ROWS)
    with pytest.raises(WebExportError, match="not in the table"):
        compact_zones(path, {"BGD.9.9.9.9_1"}, "EPSG:32645")


def test_zones_of_an_unknown_kind_are_refused(tmp_path):
    rows = [("flood", 1.0, None, (89.6, 25.5, 89.61, 25.51))]
    path = _zones(tmp_path / "z.geojson", rows)
    with pytest.raises(WebExportError, match="unknown zone kinds"):
        compact_zones(path, set(), "EPSG:32645")


def test_export_writes_the_zones_and_describes_them(tmp_path):
    tables = tmp_path / "tables"
    tables.mkdir()
    web = tmp_path / "web"
    web.mkdir()
    _write_csv(tables / "at_risk_households_2025-03.csv")
    (tables / "risk_summary_2025-03.json").write_text(json.dumps(SUMMARY), encoding="utf-8")
    (tables / "metrics_convlstm_crop128.json").write_text(json.dumps(METRICS), encoding="utf-8")
    (web / "zones_2024-12.geojson").write_text("{}", encoding="utf-8")

    payload = json.loads(export(_export_cfg(tmp_path, tables, web)).read_text(encoding="utf-8"))
    assert payload["schema"] == 3
    assert payload["map"]["file"] == "zones_2025-03.geojson"
    assert payload["map"]["features"] == 1
    assert (web / "zones_2025-03.geojson").exists()
    assert not (web / "zones_2024-12.geojson").exists()        # one forecast only
