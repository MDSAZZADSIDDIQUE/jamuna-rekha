"""Figures for the Bengali paper.

    python scripts/make_figures.py                # everything available
    python scripts/make_figures.py --only 2 4     # selected figures

Writes PNG (300 dpi, for print) and PDF (vector) into ``outputs/figures/``.
Each figure is skipped with a warning if its inputs do not exist yet, so this
can be run at any point during the pipeline.

Figure text is in **English**. The captions in the manuscript are Bengali.
Matplotlib does not perform Indic complex-script shaping — it places glyphs
without reordering conjuncts — so Bengali set inside a figure renders subtly
wrong in a way that is easy to miss on screen and obvious in print. English
labels with Bengali captions is the safe combination, and it matches the
convention in Bangladeshi technical journals.

Colour follows the validated palette in the dataviz reference: categorical
slots for identity (sensor, model), a single-hue blue ramp for magnitude, and
blue/red with a neutral midpoint for the one genuinely diverging quantity —
erosion against accretion. Every categorical figure carries direct value
labels, which is the required relief for the two slots that sit below 3:1
contrast on a light surface.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.colors import ListedColormap
from matplotlib.patches import Patch, Rectangle

from jamunarekha.utils.config import load_config
from jamunarekha.utils.geo import grid_from_config
from jamunarekha.utils.logging import get_logger

logger = get_logger("jamunarekha.figures")

# ---------------------------------------------------------------- palette
SURFACE = "#fcfcfb"
INK = "#0b0b0b"
INK_2 = "#52514e"
INK_MUTED = "#8a8984"
GRID = "#e6e5e1"

CATEGORICAL = {
    "blue": "#2a78d6",
    "orange": "#eb6834",
    "aqua": "#1baf7a",
    "yellow": "#eda100",
}
SENSOR_COLOUR = {
    "MSS": CATEGORICAL["blue"],
    "TM": CATEGORICAL["orange"],
    "ETM+": CATEGORICAL["aqua"],
    "OLI": CATEGORICAL["yellow"],
}
MODEL_COLOUR = {
    "timesformer": CATEGORICAL["blue"],
    "convlstm": CATEGORICAL["orange"],
    "persistence": CATEGORICAL["aqua"],
}
MODEL_LABEL = {
    "timesformer": "TimeSformer",
    "convlstm": "ConvLSTM",
    "persistence": "Persistence",
}
SEQ_BLUE = ["#cde2fb", "#9ec5f4", "#6da7ec", "#3987e5", "#2a78d6", "#1c5cab", "#104281"]
EROSION_RED = "#d03b3b"
ACCRETION_BLUE = "#2a78d6"
NEUTRAL_MID = "#f0efec"
LAND = "#e8e2d6"
WATER = "#2a78d6"


def style() -> None:
    plt.rcParams.update(
        {
            "figure.facecolor": SURFACE,
            "axes.facecolor": SURFACE,
            "savefig.facecolor": SURFACE,
            "font.family": "DejaVu Sans",
            "font.size": 9,
            "axes.titlesize": 10,
            "axes.titleweight": "bold",
            "axes.labelsize": 9,
            "axes.edgecolor": GRID,
            "axes.labelcolor": INK_2,
            "axes.linewidth": 0.8,
            "axes.grid": True,
            "axes.axisbelow": True,
            "grid.color": GRID,
            "grid.linewidth": 0.6,
            "xtick.color": INK_2,
            "ytick.color": INK_2,
            "xtick.labelsize": 8,
            "ytick.labelsize": 8,
            "legend.frameon": False,
            "legend.fontsize": 8,
            "text.color": INK,
        }
    )


def despine(ax, keep=("left", "bottom")) -> None:
    for side, spine in ax.spines.items():
        spine.set_visible(side in keep)


def save(fig, out_dir: Path, name: str) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    for suffix in ("png", "pdf"):
        path = out_dir / f"{name}.{suffix}"
        fig.savefig(path, dpi=300, bbox_inches="tight")
    plt.close(fig)
    logger.info("wrote %s.{png,pdf}", name)


# ====================================================================== fig 1
def figure_study_area(cfg, out_dir: Path) -> None:
    """The reach, the four analysis tiles, and the districts they cross."""
    import geopandas as gpd
    from shapely.geometry import box

    from jamunarekha.risk import aggregate

    interim = Path(cfg.paths.data_interim)
    try:
        unions = aggregate.load_gadm_unions(str(cfg.risk.gadm_url), interim / "gadm", 4)
    except Exception as exc:  # noqa: BLE001
        logger.warning("figure 1 skipped, GADM unavailable: %s", exc)
        return

    tiles = grid_from_config(cfg)
    bbox = box(*cfg.study_area.bbox_wgs84)
    reach = gpd.GeoDataFrame(geometry=[bbox], crs="EPSG:4326")
    touching = gpd.sjoin(unions, reach, how="inner", predicate="intersects")
    districts = touching.dissolve(by="district").reset_index()

    fig, (ax_context, ax_main) = plt.subplots(
        1, 2, figsize=(10.5, 7.2), gridspec_kw={"width_ratios": [1, 1.45]}
    )

    # -- context: Bangladesh, with the study reach marked -------------------
    # Dissolving 5 158 union polygons leaves hairline slivers between
    # neighbours, which plot as a dense mess of internal lines instead of a
    # national outline. A small dilate-then-erode closes them.
    country = unions.dissolve()
    country["geometry"] = country.geometry.buffer(0.01).buffer(-0.01)
    country.boundary.plot(ax=ax_context, color=INK_MUTED, linewidth=0.7)
    country.plot(ax=ax_context, facecolor="#f4f2ed", edgecolor="none", zorder=0)
    reach.boundary.plot(ax=ax_context, color=EROSION_RED, linewidth=1.6)
    ax_context.set_title("Bangladesh — study reach", color=INK)
    ax_context.set_axis_off()
    ax_context.annotate(
        "Jamuna\nstudy reach",
        xy=(89.65, 25.5), xytext=(87.4, 26.6),
        color=EROSION_RED, fontsize=8, fontweight="bold",
        arrowprops=dict(arrowstyle="->", color=EROSION_RED, lw=1.0),
    )

    # -- main: districts + tiles -------------------------------------------
    districts.plot(
        ax=ax_main, facecolor="#f4f2ed", edgecolor=INK_MUTED, linewidth=0.5
    )
    for _, row in districts.iterrows():
        centroid = row.geometry.representative_point()
        ax_main.text(
            centroid.x, centroid.y, row["district"],
            fontsize=7, color=INK_2, ha="center", va="center",
        )

    for tile in tiles:
        min_lon, min_lat, max_lon, max_lat = tile.bounds_wgs84()
        ax_main.add_patch(
            Rectangle(
                (min_lon, min_lat), max_lon - min_lon, max_lat - min_lat,
                fill=False, edgecolor=CATEGORICAL["blue"], linewidth=1.4,
            )
        )
        ax_main.text(
            min_lon + 0.02, max_lat - 0.05, tile.name,
            fontsize=8, fontweight="bold", color=CATEGORICAL["blue"],
        )

    reach.boundary.plot(ax=ax_main, color=EROSION_RED, linewidth=1.4, linestyle="--")
    ax_main.set_xlim(88.9, 90.3)
    ax_main.set_ylim(24.2, 26.9)
    ax_main.set_xlabel("Longitude (°E)")
    ax_main.set_ylabel("Latitude (°N)")
    ax_main.set_title(
        f"Analysis tiles — {cfg.study_area.tile_size}×{cfg.study_area.tile_size} px "
        f"at {cfg.study_area.resolution_m:.0f} m, {cfg.study_area.target_crs}",
        color=INK,
    )
    ax_main.legend(
        handles=[
            Patch(facecolor="none", edgecolor=CATEGORICAL["blue"], label="Analysis tile (61.4 km)"),
            Patch(facecolor="none", edgecolor=EROSION_RED, label="Study bounding box"),
            Patch(facecolor="#f4f2ed", edgecolor=INK_MUTED, label="District (GADM level 2)"),
        ],
        loc="lower left",
    )
    fig.tight_layout()
    save(fig, out_dir, "fig1_study_area")


# ====================================================================== fig 2
def figure_data_availability(cfg, out_dir: Path) -> None:
    """How much satellite there actually is, per year and per sensor."""
    manifest = Path(cfg.paths.data_raw) / "_manifest" / "scenes.csv"
    if not manifest.exists():
        logger.warning("figure 2 skipped, no manifest yet")
        return

    scenes = pd.read_csv(manifest)
    scenes["year"] = scenes["month"].astype(str).str.slice(0, 4).astype(int)
    scenes = scenes.drop_duplicates(subset=["item_id", "tile"])

    counts = (
        scenes.groupby(["year", "instrument"]).size().unstack(fill_value=0)
    )
    order = [s for s in ("MSS", "TM", "ETM+", "OLI") if s in counts.columns]
    counts = counts[order]
    years = np.arange(int(cfg.acquire.year_start), int(cfg.acquire.year_end) + 1)
    counts = counts.reindex(years, fill_value=0)

    fig, (ax_top, ax_bot) = plt.subplots(
        2, 1, figsize=(10.5, 6.4), gridspec_kw={"height_ratios": [2, 1]}, sharex=True
    )

    bottom = np.zeros(len(counts))
    for sensor in order:
        values = counts[sensor].to_numpy()
        ax_top.bar(
            counts.index, values, bottom=bottom, width=0.78,
            color=SENSOR_COLOUR[sensor], label=sensor,
            edgecolor=SURFACE, linewidth=0.7,   # 2px-equivalent surface gap
        )
        bottom += values
    ax_top.set_ylabel("Landsat scenes used")
    ax_top.set_title(
        "Scenes contributing to the monthly composites, by mission and year", color=INK
    )
    # Legend above the plot area: inside it, it collides with the tall OLI-era
    # bars on the right and with the gap shading on the left.
    ax_top.legend(ncol=4, loc="lower left", bbox_to_anchor=(0.0, 1.06))
    despine(ax_top)

    empty_years = counts.index[counts.sum(axis=1) == 0]
    for year in empty_years:
        ax_top.axvspan(year - 0.5, year + 0.5, color=EROSION_RED, alpha=0.10, zorder=0)
    if len(empty_years):
        ax_top.text(
            float(empty_years[len(empty_years) // 2]), ax_top.get_ylim()[1] * 0.80,
            "no usable\ncoverage", color=EROSION_RED, fontsize=7.5,
            ha="center", va="top", fontweight="bold",
        )

    # -- monthly coverage fraction ----------------------------------------
    processed = Path(cfg.paths.data_processed)
    metas = sorted(processed.glob("*_meta.json"))
    if metas:
        fractions = []
        for meta_path in metas:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            months = meta["months"]
            observed = np.load(processed / f"{meta['tile']}_observed.npy", mmap_mode="r")
            fractions.append(np.asarray(observed).mean(axis=(1, 2)))
        coverage = np.mean(fractions, axis=0)
        month_years = np.array([int(m[:4]) + (int(m[5:7]) - 1) / 12 for m in months])
        ax_bot.fill_between(month_years, coverage, color=CATEGORICAL["blue"], alpha=0.25)
        ax_bot.plot(month_years, coverage, color=CATEGORICAL["blue"], linewidth=1.2)
        ax_bot.set_ylim(0, 1.02)
        ax_bot.set_ylabel("Usable pixel\nfraction")
    else:
        # Reindex onto the complete month axis so months with no data become
        # NaN and the line BREAKS there. Plotting only the months that exist
        # draws a straight segment across a multi-year hole, which reads as
        # steady coverage — the exact opposite of the truth.
        monthly = scenes.groupby("month").size()
        all_months = [
            f"{y:04d}-{m:02d}"
            for y in range(int(cfg.acquire.year_start), int(cfg.acquire.year_end) + 1)
            for m in range(1, 13)
        ]
        monthly = monthly.reindex(all_months)
        month_years = np.array([int(m[:4]) + (int(m[5:7]) - 1) / 12 for m in all_months])
        ax_bot.plot(month_years, monthly.to_numpy(), color=CATEGORICAL["blue"], linewidth=0.9)
        ax_bot.set_ylabel("Scenes per\nmonth")

    ax_bot.set_xlabel("Year")
    ax_bot.set_title(
        "Monthly usable fraction after cloud masking and capped gap-filling",
        color=INK,
    )
    despine(ax_bot)

    fig.tight_layout()
    save(fig, out_dir, "fig2_data_availability")


# ====================================================================== fig 3
def figure_water_masks(cfg, out_dir: Path) -> None:
    """The river itself, one frame per decade."""
    processed = Path(cfg.paths.data_processed)
    metas = sorted(processed.glob("*_meta.json"))
    if not metas:
        logger.warning("figure 3 skipped, Stage 2 not run")
        return

    meta = json.loads(metas[len(metas) // 2].read_text(encoding="utf-8"))
    tile = meta["tile"]
    months = meta["months"]
    water = np.load(processed / f"{tile}_water.npy", mmap_mode="r")
    observed = np.load(processed / f"{tile}_observed.npy", mmap_mode="r")

    wanted = ["1975-02", "1985-02", "1995-02", "2005-02", "2015-02", "2023-02"]
    picks = []
    for target in wanted:
        if target in months:
            index = months.index(target)
            if np.asarray(observed[index]).mean() > 0.5:
                picks.append((target, index))
                continue
        # fall back to the nearest well-observed month in the same year
        year = target[:4]
        candidates = [
            (m, i) for i, m in enumerate(months)
            if m.startswith(year) and np.asarray(observed[i]).mean() > 0.5
        ]
        if candidates:
            picks.append(candidates[0])

    if not picks:
        logger.warning("figure 3 skipped, no well-observed months found")
        return

    cmap = ListedColormap([LAND, WATER])
    fig, axes = plt.subplots(1, len(picks), figsize=(2.05 * len(picks), 2.5))
    axes = np.atleast_1d(axes)
    for ax, (month, index) in zip(axes, picks):
        ax.imshow(np.asarray(water[index]), cmap=cmap, vmin=0, vmax=1, interpolation="nearest")
        ax.set_title(month, fontsize=9, color=INK)
        ax.set_xticks([])
        ax.set_yticks([])
        ax.grid(False)
        for spine in ax.spines.values():
            spine.set_edgecolor(GRID)

    scale_px = 10_000.0 / float(cfg.study_area.resolution_m)
    axes[0].plot([12, 12 + scale_px], [meta["height"] - 20] * 2, color=INK, linewidth=2.2)
    axes[0].text(12, meta["height"] - 32, "10 km", fontsize=7, color=INK)

    fig.suptitle(
        f"Tile {tile} — derived water masks across the record "
        f"(land {LAND}, water {WATER})",
        fontsize=10, fontweight="bold", color=INK, y=1.04,
    )
    fig.legend(
        handles=[Patch(facecolor=WATER, label="Water"), Patch(facecolor=LAND, label="Land")],
        loc="lower center", ncol=2, bbox_to_anchor=(0.5, -0.06),
    )
    fig.tight_layout()
    save(fig, out_dir, "fig3_water_masks")


# ====================================================================== fig 4
def _load_metrics(cfg) -> list[dict]:
    records = []
    for path in sorted(Path(cfg.paths.tables).glob("metrics_*.json")):
        records.append(json.loads(path.read_text(encoding="utf-8")))
    return records


def figure_model_comparison(cfg, out_dir: Path) -> None:
    """Three metrics, three panels — never two y-scales on one axis."""
    records = _load_metrics(cfg)
    if not records:
        logger.warning("figure 4 skipped, no metrics files")
        return

    panels = [
        ("test/iou", "IoU (water body)", "higher is better", False),
        ("test/bank_f1", "F1 on bank pixels", "higher is better", False),
        ("test/mde_m", "Mean displacement error (m)", "lower is better", True),
    ]
    fig, axes = plt.subplots(1, 3, figsize=(10.5, 3.6))

    for ax, (key, title, direction, lower_better) in zip(axes, panels):
        names, values, colours = [], [], []
        for record in records:
            value = record["test_metrics"].get(key)
            if value is None or not np.isfinite(value):
                continue
            model = record["model"]
            names.append(MODEL_LABEL.get(model, model))
            values.append(float(value))
            colours.append(MODEL_COLOUR.get(model, CATEGORICAL["blue"]))
        if not names:
            ax.set_axis_off()
            continue

        order = np.argsort(values)[::-1] if lower_better else np.argsort(values)
        names = [names[i] for i in order]
        values = [values[i] for i in order]
        colours = [colours[i] for i in order]

        bars = ax.barh(names, values, color=colours, height=0.58, edgecolor=SURFACE, linewidth=0.8)
        span = max(values) if max(values) > 0 else 1.0
        for bar, value in zip(bars, values):
            label = f"{value:.1f}" if lower_better else f"{value:.3f}"
            ax.text(
                bar.get_width() + span * 0.03, bar.get_y() + bar.get_height() / 2,
                label, va="center", fontsize=8.5, color=INK, fontweight="bold",
            )
        ax.set_xlim(0, span * 1.28)
        ax.set_title(f"{title}\n({direction})", color=INK)
        ax.grid(axis="y", visible=False)
        despine(ax)

    fig.suptitle(
        "Test-split performance, 2018–2024 (unseen years)",
        fontsize=10.5, fontweight="bold", color=INK, y=1.03,
    )
    fig.tight_layout()
    save(fig, out_dir, "fig4_model_comparison")


# ====================================================================== fig 5
def figure_horizon(cfg, out_dir: Path) -> None:
    """Does the forecast decay with lead time?"""
    records = [r for r in _load_metrics(cfg) if r.get("per_horizon")]
    if not records:
        logger.warning("figure 5 skipped, no per-horizon metrics")
        return

    fig, axes = plt.subplots(1, 2, figsize=(9.0, 3.6))
    for ax, (key, title, fmt) in zip(
        axes,
        [("bank_f1", "F1 on bank pixels", "{:.3f}"), ("mde_m", "Mean displacement error (m)", "{:.0f}")],
    ):
        for record in records:
            table = record["per_horizon"]
            horizons = [row["horizon_months"] for row in table]
            values = [row.get(key, np.nan) for row in table]
            model = record["model"]
            ax.plot(
                horizons, values, marker="o", markersize=6, linewidth=2,
                color=MODEL_COLOUR.get(model, CATEGORICAL["blue"]),
                markeredgecolor=SURFACE, markeredgewidth=1.4,
                label=MODEL_LABEL.get(model, model),
            )
            if values and np.isfinite(values[-1]):
                ax.annotate(
                    fmt.format(values[-1]),
                    xy=(horizons[-1], values[-1]), xytext=(6, 0),
                    textcoords="offset points", fontsize=8,
                    color=INK, va="center", fontweight="bold",
                )
        ax.set_xlabel("Forecast lead time (months)")
        ax.set_title(title, color=INK)
        ax.set_xticks([1, 2, 3])
        despine(ax)
    axes[0].legend(loc="best")
    fig.suptitle(
        "Forecast quality against lead time", fontsize=10.5, fontweight="bold",
        color=INK, y=1.03,
    )
    fig.tight_layout()
    save(fig, out_dir, "fig5_horizon")


# ====================================================================== fig 6
def figure_forecast_example(cfg, out_dir: Path) -> None:
    """Last observation, truth, forecast, and the predicted change."""
    example = Path(cfg.paths.predictions) / "forecast_example.npz"
    if not example.exists():
        logger.warning("figure 6 skipped, no forecast_example.npz")
        return

    data = np.load(example)
    last, truth, pred = data["last"], data["truth"], data["pred"]
    resolution = float(cfg.study_area.resolution_m)

    fig, axes = plt.subplots(1, 4, figsize=(11.5, 3.2))
    binary = ListedColormap([LAND, WATER])

    for ax, (array, title) in zip(
        axes[:3],
        [
            (last, f"Last observation\n{str(data.get('last_month', ''))}"),
            (truth, f"Observed\n{str(data.get('target_month', ''))}"),
            (pred, f"Forecast (+3 months)\n{str(data.get('target_month', ''))}"),
        ],
    ):
        ax.imshow(array, cmap=binary, vmin=0, vmax=1, interpolation="nearest")
        ax.set_title(title, fontsize=9, color=INK)
        ax.set_xticks([]); ax.set_yticks([]); ax.grid(False)

    # Panel 4 is the forecast ERROR, not the change.
    #
    # Differencing the forecast against the *last observation* would compare
    # two different points in the seasonal cycle — September against December —
    # so it would show the monsoon receding, not the model being wrong. Against
    # the observed truth for the same month, the two error directions separate
    # cleanly and the panel says what a verification panel should say.
    false_water = (pred > 0.5) & (truth < 0.5)
    false_land = (pred < 0.5) & (truth > 0.5)
    error = np.zeros_like(truth, dtype=float)
    error[false_water] = 1.0
    error[false_land] = -1.0
    axes[3].imshow(
        error, cmap=ListedColormap([ACCRETION_BLUE, NEUTRAL_MID, EROSION_RED]),
        vmin=-1, vmax=1, interpolation="nearest",
    )
    cell_ha = resolution**2 / 10_000.0
    axes[3].set_title("Forecast error vs observed", fontsize=9, color=INK)
    axes[3].set_xticks([]); axes[3].set_yticks([]); axes[3].grid(False)
    axes[3].legend(
        handles=[
            Patch(
                facecolor=EROSION_RED,
                label=f"Predicted water, was land — {false_water.sum() * cell_ha:,.0f} ha",
            ),
            Patch(
                facecolor=ACCRETION_BLUE,
                label=f"Predicted land, was water — {false_land.sum() * cell_ha:,.0f} ha",
            ),
        ],
        loc="lower center", bbox_to_anchor=(0.5, -0.34), ncol=1,
    )
    for ax in axes:
        for spine in ax.spines.values():
            spine.set_edgecolor(GRID)

    fig.suptitle(
        f"Forecast example — tile {str(data.get('tile', ''))}, "
        f"{str(data.get('model', ''))}",
        fontsize=10.5, fontweight="bold", color=INK, y=1.06,
    )
    fig.tight_layout()
    save(fig, out_dir, "fig6_forecast_example")


# ====================================================================== fig 7
def figure_union_risk(cfg, out_dir: Path) -> None:
    """Which unions carry the loss — sequential by magnitude."""
    tables = sorted(Path(cfg.paths.tables).glob("at_risk_households_*.csv"))
    if not tables:
        logger.warning("figure 7 skipped, no risk table")
        return

    table = pd.read_csv(tables[-1])
    month = tables[-1].stem.replace("at_risk_households_", "")
    if table.empty:
        logger.warning("figure 7 skipped, risk table is empty")
        return

    top = table.nlargest(15, "erosion_ha").iloc[::-1]
    # GADM runs multi-word names together (SaheberAlga); split them for reading,
    # as the website does, without changing the spelling.
    from jamunarekha.dashboard.web_export import display_name

    labels = [
        f"{display_name(row['union'])} ({row['district']})" for _, row in top.iterrows()
    ]
    values = top["erosion_ha"].to_numpy()

    # Sequential single-hue ramp: darker = more land lost.
    norm = (values - values.min()) / max(1e-9, values.max() - values.min())
    colours = [SEQ_BLUE[min(len(SEQ_BLUE) - 1, int(v * (len(SEQ_BLUE) - 1)))] for v in norm]

    fig, ax = plt.subplots(figsize=(9.0, 5.6))
    bars = ax.barh(labels, values, color=colours, height=0.62, edgecolor=SURFACE, linewidth=0.8)
    for bar, (_, row) in zip(bars, top.iterrows()):
        buildings = int(row["buildings_osm"])
        ax.text(
            bar.get_width() + values.max() * 0.015,
            bar.get_y() + bar.get_height() / 2,
            f"{row['erosion_ha']:.0f} ha · {buildings} building{'' if buildings == 1 else 's'}",
            va="center", fontsize=8, color=INK,
        )
    ax.set_xlim(0, values.max() * 1.42)
    ax.set_xlabel("Predicted erosion (hectares)")
    ax.set_title(
        f"Union parishads with the greatest forecast land loss — {month}\n"
        "Building counts are OSM lower bounds",
        color=INK,
    )
    ax.grid(axis="y", visible=False)
    despine(ax)
    fig.tight_layout()
    save(fig, out_dir, "fig7_union_risk")


FIGURES = {
    1: figure_study_area,
    2: figure_data_availability,
    3: figure_water_masks,
    4: figure_model_comparison,
    5: figure_horizon,
    6: figure_forecast_example,
    7: figure_union_risk,
}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default=None)
    parser.add_argument("--only", nargs="+", type=int, choices=sorted(FIGURES))
    args = parser.parse_args()

    cfg = load_config(args.config)
    style()
    out_dir = Path(cfg.paths.figures)

    for number in (args.only or sorted(FIGURES)):
        try:
            FIGURES[number](cfg, out_dir)
        except Exception as exc:  # noqa: BLE001 - one bad figure must not stop the rest
            logger.warning("figure %d failed: %s: %s", number, type(exc).__name__, exc)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
