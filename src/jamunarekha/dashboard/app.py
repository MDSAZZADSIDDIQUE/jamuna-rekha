"""Stage 5 — the dashboard handed to the Department of Disaster Management.

    streamlit run src/jamunarekha/dashboard/app.py

Three things, in the order a disaster officer needs them:

1. an erosion risk map, colour-coded by severity;
2. a sortable table of at-risk households, filterable by district;
3. a CSV download — the actual handoff artefact.

The interface is bilingual. A Bengali-only interface excludes the English
technical vocabulary the upazila engineer works in; an English-only one
excludes the union parishad secretary. Both labels appear together.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "src"))

import folium
import geopandas as gpd
import pandas as pd
import streamlit as st
from streamlit_folium import st_folium

from jamunarekha.utils.config import load_config

# Severity bands, in hectares of predicted erosion per union parishad.
SEVERITY_BANDS = [
    (50.0, "অতি উচ্চ / Very high", "#b2182b"),
    (20.0, "উচ্চ / High", "#ef8a62"),
    (5.0, "মাঝারি / Moderate", "#fddbc7"),
    (0.0, "নিম্ন / Low", "#d1e5f0"),
]

JAMUNA_CENTRE = (25.1, 89.7)


def severity_of(erosion_ha: float) -> tuple[str, str]:
    """Map erosion area to a (label, colour) severity band."""
    for threshold, label, colour in SEVERITY_BANDS:
        if erosion_ha >= threshold:
            return label, colour
    return SEVERITY_BANDS[-1][1], SEVERITY_BANDS[-1][2]


@st.cache_data(show_spinner=False)
def find_outputs(tables_dir: str, predictions_dir: str) -> dict:
    """Locate the most recent risk table and its matching polygon layer."""
    tables = sorted(Path(tables_dir).glob("at_risk_households_*.csv"))
    polygons = sorted(Path(predictions_dir).glob("change_polygons_*.geojson"))
    summaries = sorted(Path(tables_dir).glob("risk_summary_*.json"))
    return {
        "tables": [str(p) for p in tables],
        "polygons": [str(p) for p in polygons],
        "summaries": [str(p) for p in summaries],
    }


@st.cache_data(show_spinner=False)
def load_table(path: str) -> pd.DataFrame:
    return pd.read_csv(path)


@st.cache_data(show_spinner=False)
def load_polygons(path: str) -> gpd.GeoDataFrame:
    return gpd.read_file(path)


def build_map(polygons: gpd.GeoDataFrame) -> folium.Map:
    """Erosion and accretion polygons on an OSM base map.

    Polygons are coloured by *kind* rather than by union severity: the change
    polygons are produced before the union overlay, so they carry no union
    attribution. Severity is where it belongs — against the union rows in the
    table beside the map.
    """
    fmap = folium.Map(location=JAMUNA_CENTRE, zoom_start=9, tiles="OpenStreetMap")

    erosion = polygons[polygons["kind"] == "erosion"]
    accretion = polygons[polygons["kind"] == "accretion"]

    erosion_layer = folium.FeatureGroup(name="ভাঙন / Erosion", show=True)
    for _, row in erosion.iterrows():
        folium.GeoJson(
            row.geometry.__geo_interface__,
            style_function=lambda _f: {
                "fillColor": "#b2182b", "color": "#67001f",
                "weight": 1, "fillOpacity": 0.65,
            },
            tooltip=f"ভাঙন / Erosion: {row.get('area_ha', 0):.1f} ha",
        ).add_to(erosion_layer)
    erosion_layer.add_to(fmap)

    accretion_layer = folium.FeatureGroup(name="চর জাগা / Accretion", show=True)
    for _, row in accretion.iterrows():
        folium.GeoJson(
            row.geometry.__geo_interface__,
            style_function=lambda _f: {
                "fillColor": "#2166ac", "color": "#053061",
                "weight": 1, "fillOpacity": 0.5,
            },
            tooltip=f"চর জাগা / Accretion: {row.get('area_ha', 0):.1f} ha",
        ).add_to(accretion_layer)
    accretion_layer.add_to(fmap)

    folium.LayerControl(collapsed=False).add_to(fmap)
    return fmap


def main() -> None:
    st.set_page_config(
        page_title="যমুনারেখা · JamunaRekha", page_icon="🌊", layout="wide"
    )
    cfg = load_config()

    st.title("যমুনারেখা · JamunaRekha")
    st.caption(
        "যমুনা নদীর তীররেখার তিন মাসের পূর্বাভাস ও ভাঙন-ঝুঁকির মানচিত্র  ·  "
        "Three-month Jamuna shoreline forecast and erosion risk map"
    )

    outputs = find_outputs(cfg.paths.tables, cfg.paths.predictions)
    if not outputs["tables"]:
        st.warning(
            "কোনো ফলাফল পাওয়া যায়নি। প্রথমে Stage 4 চালান / "
            "No results found. Run Stage 4 first:\n\n"
            "`python scripts/run_stage4_risk.py --checkpoint <path>`"
        )
        return

    choice = st.sidebar.selectbox(
        "পূর্বাভাসের মাস / Forecast month",
        outputs["tables"],
        format_func=lambda p: Path(p).stem.replace("at_risk_households_", ""),
    )
    table = load_table(choice)
    month = Path(choice).stem.replace("at_risk_households_", "")

    matching = [p for p in outputs["polygons"] if month in p]
    polygons = load_polygons(matching[0]) if matching else None

    summary_files = [p for p in outputs["summaries"] if month in p]
    summary = json.loads(Path(summary_files[0]).read_text(encoding="utf-8")) if summary_files else {}

    # ------------------------------------------------------------ headline
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("ঝুঁকিপূর্ণ ইউনিয়ন / Unions at risk", f"{len(table):,}")
    col2.metric("ভাঙন / Erosion (ha)", f"{table['erosion_ha'].sum():,.0f}")
    col3.metric("চর জাগা / Accretion (ha)", f"{table['accretion_ha'].sum():,.0f}")
    col4.metric(
        "ঝুঁকিপূর্ণ পরিবার / Households", f"{int(table['households_est'].sum()):,}"
    )

    st.warning(
        "**ইউনিয়নের ক্রম নির্ধারণ করুন ভাঙনের হেক্টর দিয়ে, পরিবার-সংখ্যা দিয়ে নয়।** "
        "OpenStreetMap-এ চরাঞ্চলের ভবন-তথ্য কেবল অসম্পূর্ণ নয়, স্থানিকভাবে "
        "পক্ষপাতদুষ্ট: সর্বোচ্চ ঝুঁকির কয়েকটি ইউনিয়নে নথিভুক্ত ভবন শূন্য। "
        "পরিবার-সংখ্যা ধরে সাজালে তা ঝুঁকির ক্রম নয়, মানচিত্রায়ণের ঘনত্বের ক্রম "
        "হয়ে যায়।\n\n"
        "**Rank unions by erosion hectares, not by household count.** OSM "
        "building coverage of the chars is not merely incomplete but "
        "spatially biased — several of the highest-risk unions have zero "
        "mapped buildings. Ordering by households would order by mapping "
        "density, not by risk."
    )

    # ---------------------------------------------------------------- map
    left, right = st.columns([3, 2])
    with left:
        st.subheader("ভাঙন-ঝুঁকির মানচিত্র / Erosion risk map")
        if polygons is not None and not polygons.empty:
            st_folium(build_map(polygons), width=None, height=560)
        else:
            st.write("কোনো পলিগন পাওয়া যায়নি / No polygon layer found.")

    # -------------------------------------------------------------- table
    with right:
        st.subheader("ঝুঁকিপূর্ণ পরিবারের তালিকা / At-risk households")

        districts = sorted(table["district"].dropna().unique()) if "district" in table else []
        picked = st.multiselect("জেলা / District", districts, default=districts)
        view = table[table["district"].isin(picked)] if picked else table

        min_ha = st.slider(
            "সর্বনিম্ন ভাঙন / Minimum erosion (ha)",
            0.0, float(max(1.0, table["erosion_ha"].max())), 0.0,
        )
        view = view[view["erosion_ha"] >= min_ha]

        display = view.copy()
        display["severity"] = display["erosion_ha"].map(lambda v: severity_of(v)[0])
        columns = [
            c for c in (
                "district", "upazila", "union", "erosion_ha", "accretion_ha",
                "buildings_osm", "households_est", "persons_est", "severity",
            ) if c in display.columns
        ]
        st.dataframe(
            display[columns].sort_values("erosion_ha", ascending=False),
            use_container_width=True, height=380,
        )

        st.download_button(
            "⬇ CSV ডাউনলোড / Download CSV (DDM)",
            data=view.to_csv(index=False, encoding="utf-8-sig"),
            file_name=f"jamunarekha_at_risk_{month}.csv",
            mime="text/csv",
            use_container_width=True,
        )

    # ------------------------------------------------------------- footer
    with st.expander("পদ্ধতি ও সীমাবদ্ধতা / Method and limitations"):
        st.markdown(
            f"""
- **উপাত্ত / Data:** Landsat 1–9, {cfg.acquire.year_start}–{cfg.acquire.year_end},
  মাসিক MNDWI/NDWI জলমুখোশ, {cfg.study_area.resolution_m:.0f} m,
  `{cfg.study_area.target_crs}`.
- **মডেল / Model:** `{summary.get('model', 'n/a')}` — ১২ মাস ইনপুট,
  {cfg.data.out_frames} মাস পূর্বাভাস.
- **ভাঙন / Erosion:** এখন স্থল, পূর্বাভাসে জল (সম্ভাবনা >
  {cfg.risk.erosion_prob_threshold}).
- **সীমাবদ্ধতা / Limitations:** পূর্বাভাস মাসিক সংমিশ্রণে সীমিত; OSM ভবন-তথ্য
  অসম্পূর্ণ; {cfg.study_area.resolution_m:.0f} m পিক্সেলের চেয়ে ছোট পরিবর্তন
  ধরা পড়ে না.
            """
        )


if __name__ == "__main__":
    main()
