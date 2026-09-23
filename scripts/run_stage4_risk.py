"""Stage 4 entry point — turn a forecast into the DDM handoff table.

    python scripts/run_stage4_risk.py --checkpoint outputs/checkpoints/timesformer_crop256/last.ckpt
    python scripts/run_stage4_risk.py --checkpoint ... --no-osm   (skip Overpass)
    python scripts/run_stage4_risk.py --checkpoint ... --no-name-check   (skip the portal check)

Pipeline: forecast the next three months for every tile, take the third month
as the horizon, difference it against the **same calendar month one year
earlier**, vectorise the change, count OSM buildings, split on union parishad
boundaries, and write ``outputs/tables/at_risk_households_<month>.csv``.

The year-earlier reference is the important detail. The Jamuna floods, so
differencing the forecast against the most recent observation would measure
seasonal inundation plus erosion and label the sum "erosion". Comparing like
month with like month cancels the seasonal term and leaves the year-on-year
channel change.

That CSV is the deliverable the Department of Disaster Management receives.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import geopandas as gpd
import numpy as np
import pandas as pd
from affine import Affine

from jamunarekha.data.dataset import JamunaShift52Y
from jamunarekha.models.predict import calibrate_threshold, load_checkpoint, predict_tile
from jamunarekha.risk import aggregate, names_bn, overpass, vectorize
from jamunarekha.utils.config import load_config
from jamunarekha.utils.geo import shift_month
from jamunarekha.utils.logging import get_logger
from jamunarekha.utils.seed import seed_everything


def forecast_all_tiles(cfg, model, logger) -> tuple[gpd.GeoDataFrame, str, dict]:
    """Forecast every tile and vectorise the predicted change."""
    processed = Path(cfg.paths.data_processed)
    in_frames = int(cfg.data.in_frames)
    out_frames = int(cfg.data.out_frames)
    crs = str(cfg.study_area.target_crs)

    layers: list[gpd.GeoDataFrame] = []
    forecast_month = ""
    stats: dict = {"tiles": []}
    Path(cfg.paths.predictions).mkdir(parents=True, exist_ok=True)

    for meta_path in sorted(processed.glob("*_meta.json")):
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        tile = meta["tile"]
        water = np.load(processed / f"{tile}_water.npy", mmap_mode="r")
        observed = np.load(processed / f"{tile}_observed.npy", mmap_mode="r")

        # Anchor on the last month with real observations, not merely the last
        # month in the array: forecasting forward from an interpolated frame
        # would compound Stage 2's guess into Stage 4's warning.
        coverage = np.asarray(observed).mean(axis=(1, 2))
        usable = np.flatnonzero(coverage > 0.5)
        if usable.size == 0 or usable[-1] < in_frames - 1:
            logger.warning("%s: not enough observed months, skipping", tile)
            continue
        anchor = int(usable[-1])

        frames = np.asarray(water[anchor - in_frames + 1 : anchor + 1], dtype=np.float32)
        probs = predict_tile(
            model, frames,
            crop_size=int(cfg.data.crop_size),
            out_frames=out_frames,
            device="cpu",
        )

        future = probs[out_frames - 1] > float(cfg.risk.erosion_prob_threshold)

        # Seasonally matched reference, not simply "last month".
        #
        # The Jamuna floods. Between February and May a large area goes from
        # land to water with no bank having moved at all, so differencing the
        # forecast against the most recent observation measures *inundation*
        # plus erosion and reports the sum as erosion. Comparing the forecast
        # month against the SAME CALENDAR MONTH one year earlier cancels the
        # seasonal term and leaves the year-on-year channel change, which is
        # what erosion means here. This is also why CEGIS compares dry season
        # with dry season rather than consecutive images.
        #
        # The reference index is (anchor + out_frames) - 12, which for a
        # 3-month horizon is anchor - 9 — inside the observed input window, so
        # it is a real observation and not a second forecast.
        reference_index = anchor + out_frames - 12
        seasonally_matched = reference_index >= 0
        if seasonally_matched:
            current = np.asarray(water[reference_index]) > 0.5
        else:
            current = frames[-1] > 0.5
            logger.warning(
                "%s: no month one year before the horizon; falling back to the "
                "last observation, which mixes seasonal inundation into erosion",
                tile,
            )

        # A worked example for the paper's forecast figure, from the first tile
        # so the figure is deterministic across runs.
        #
        # This is a HINDCAST, not the operational forecast above. The
        # operational forecast targets a month that has not happened yet, so
        # there is nothing to compare it against. Backing the anchor up by the
        # horizon gives a forecast whose target month *was* observed, which is
        # the only version of this figure that shows anything: prediction
        # beside the truth it can be checked against.
        if not stats["tiles"] and anchor - out_frames >= in_frames - 1:
            hindcast_anchor = anchor - out_frames
            hindcast_frames = np.asarray(
                water[hindcast_anchor - in_frames + 1 : hindcast_anchor + 1],
                dtype=np.float32,
            )
            hindcast_probs = predict_tile(
                model, hindcast_frames,
                crop_size=int(cfg.data.crop_size),
                out_frames=out_frames,
                device="cpu",
            )
            np.savez_compressed(
                Path(cfg.paths.predictions) / "forecast_example.npz",
                last=(hindcast_frames[-1] > 0.5).astype(np.uint8),
                truth=(np.asarray(water[anchor]) > 0.5).astype(np.uint8),
                pred=(
                    hindcast_probs[out_frames - 1]
                    > float(cfg.risk.erosion_prob_threshold)
                ).astype(np.uint8),
                prob=hindcast_probs[out_frames - 1].astype(np.float32),
                tile=tile,
                model=str(cfg.model.name),
                last_month=meta["months"][hindcast_anchor],
                target_month=meta["months"][anchor],
            )
            logger.info(
                "%s hindcast example: %s -> %s (observed truth available)",
                tile, meta["months"][hindcast_anchor], meta["months"][anchor],
            )

        transform = Affine(*meta["transform"])
        polygons = vectorize.change_polygons(
            current, future, transform, crs,
            min_area_m2=float(cfg.risk.min_polygon_area_m2),
            simplify_m=float(cfg.risk.simplify_tolerance_m),
        )
        if not polygons.empty:
            polygons["tile"] = tile
            layers.append(polygons)

        months = meta["months"]
        anchor_month = months[anchor]
        # Computed calendrically, not by index: a real forecast runs past the
        # end of the observed record, and indexing would clamp it to the last
        # observed month and mislabel the warning.
        forecast_month = shift_month(anchor_month, out_frames)
        stats["tiles"].append(
            {
                "tile": tile,
                "anchor_month": anchor_month,
                "forecast_month": forecast_month,
                "reference_month": months[reference_index] if seasonally_matched else anchor_month,
                "seasonally_matched": bool(seasonally_matched),
                "erosion_ha": float(
                    polygons.loc[polygons["kind"] == "erosion", "area_ha"].sum()
                ) if not polygons.empty else 0.0,
                "accretion_ha": float(
                    polygons.loc[polygons["kind"] == "accretion", "area_ha"].sum()
                ) if not polygons.empty else 0.0,
            }
        )
        logger.info(
            "%s anchor=%s -> forecast=%s | %d polygons",
            tile, anchor_month, forecast_month, len(polygons),
        )

    if not layers:
        return gpd.GeoDataFrame(geometry=[], crs=crs), forecast_month, stats
    return gpd.GeoDataFrame(pd.concat(layers, ignore_index=True), crs=crs), forecast_month, stats


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default="local.yaml")
    parser.add_argument("--checkpoint", required=True)
    parser.add_argument("--model", default=None)
    parser.add_argument("--no-osm", action="store_true", help="skip the Overpass query")
    parser.add_argument(
        "--no-name-check", action="store_true",
        help="use the compiled Bengali names without checking them against the official portals",
    )
    parser.add_argument("--osm-completeness", type=float, default=1.0)
    parser.add_argument(
        "--no-calibrate", action="store_true",
        help="skip validation threshold calibration and use the configured cut",
    )
    args = parser.parse_args()

    cfg = load_config(args.config)
    if args.model:
        cfg.model.name = args.model
    logger = get_logger("jamunarekha.stage4", cfg.paths.logs)
    seed_everything(int(cfg.project.seed))

    model = load_checkpoint(args.checkpoint, cfg)
    logger.info("loaded %s from %s", cfg.model.name, args.checkpoint)

    # Calibrate the water-probability cut on the VALIDATION split before
    # forecasting. pos_weight pushes the model's outputs upward, so a fixed 0.5
    # over-predicts water, and erosion is defined as land-becoming-water — the
    # error propagates straight into the household counts. See
    # jamunarekha.models.predict.calibrate_threshold.
    threshold_report: dict = {}
    if not args.no_calibrate:
        validation = JamunaShift52Y(
            processed_dir=cfg.paths.data_processed,
            split="val",
            in_frames=int(cfg.data.in_frames),
            out_frames=int(cfg.data.out_frames),
            crop_size=int(cfg.data.crop_size),
            train_end_year=int(cfg.data.split.train_end_year),
            val_end_year=int(cfg.data.split.val_end_year),
            max_windows=int(cfg.data.get("max_val_windows", 0)) or None,
            seed=int(cfg.project.seed),
        )
        validation.resolution_m = float(cfg.study_area.resolution_m)
        best, threshold_report = calibrate_threshold(model, validation)
        cfg.risk.erosion_prob_threshold = best
    logger.info(
        "water probability threshold: %.2f", float(cfg.risk.erosion_prob_threshold)
    )

    polygons, forecast_month, stats = forecast_all_tiles(cfg, model, logger)
    if polygons.empty:
        logger.error("no change polygons produced — nothing to aggregate")
        return 1

    erosion_ha = float(polygons.loc[polygons["kind"] == "erosion", "area_ha"].sum())
    accretion_ha = float(polygons.loc[polygons["kind"] == "accretion", "area_ha"].sum())
    logger.info(
        "forecast %s: %.1f ha erosion, %.1f ha accretion across %d polygons",
        forecast_month, erosion_ha, accretion_ha, len(polygons),
    )

    interim = Path(cfg.paths.data_interim)
    if args.no_osm:
        buildings = gpd.GeoDataFrame(
            {"osm_id": [], "osm_type": [], "building": []}, geometry=[], crs="EPSG:4326"
        )
        logger.info("Overpass skipped (--no-osm)")
    else:
        buildings = overpass.buildings_for_polygons(
            polygons[polygons["kind"] == "erosion"],
            cache_dir=interim / "osm",
            overpass_url=str(cfg.risk.overpass_url),
            timeout_s=int(cfg.risk.overpass_timeout_s),
        )
    logger.info("%d OSM building centroids", len(buildings))

    unions = aggregate.load_gadm_unions(
        str(cfg.risk.gadm_url), interim / "gadm", level=int(cfg.risk.gadm_level)
    )
    pieces = aggregate.attribute_to_unions(polygons, unions)
    table = aggregate.union_risk_table(
        pieces, buildings,
        persons_per_household=float(cfg.risk.persons_per_household),
        osm_completeness=float(args.osm_completeness),
    )

    # How well each union is mapped in OSM, measured over the ground the
    # building query actually covered: it says how far to trust the count,
    # and whether an empty erosion zone is unsettled or merely unmapped.
    coverage = (
        overpass.Coverage(None, 0, 0) if args.no_osm
        else overpass.coverage_for_polygons(
            polygons[polygons["kind"] == "erosion"], cache_dir=interim / "osm"
        )
    )
    density = aggregate.mapping_density(
        unions[unions["gid_union"].isin(table["gid_union"])],
        buildings,
        coverage.geometry,
        metric_crs=str(cfg.study_area.target_crs),
        min_area_km2=float(cfg.risk.osm_density_min_area_km2),
        low_below=float(cfg.risk.osm_density_low_below),
        high_from=float(cfg.risk.osm_density_high_from),
    )
    table = table.merge(density, on="gid_union", how="left")
    logger.info(
        "OSM mapping: %s (Overpass answered %d of %d cells)",
        table["osm_mapping"].value_counts().to_dict(),
        coverage.cells_answered, coverage.cells_requested,
    )

    # Bengali names, checked against each unit's official portal page.
    gazetteer = names_bn.load_gazetteer(str(cfg.risk.bn_names_url), interim / "names_bn")
    ca_bundle = (
        None if args.no_name_check
        else names_bn.portal_ca_bundle(list(cfg.risk.bn_portal_intermediates), interim / "names_bn")
    )
    names, name_review = names_bn.bengali_names(
        table, gazetteer, interim / "names_bn",
        verify=not args.no_name_check,
        delay_s=float(cfg.risk.bn_portal_delay_s),
        ca_bundle=ca_bundle,
    )
    table = table.merge(names, on="gid_union", how="left")

    out_csv = Path(cfg.paths.tables) / f"at_risk_households_{forecast_month}.csv"
    aggregate.write_table(table, out_csv, forecast_month)
    review_csv = Path(cfg.paths.tables) / f"bn_names_{forecast_month}.csv"
    name_review.to_csv(review_csv, index=False, encoding="utf-8-sig")
    logger.info("wrote %s (for a person to check the name matching)", review_csv)

    geo_path = Path(cfg.paths.predictions) / f"change_polygons_{forecast_month}.geojson"
    geo_path.parent.mkdir(parents=True, exist_ok=True)
    polygons.to_crs("EPSG:4326").to_file(geo_path, driver="GeoJSON")
    logger.info("wrote %s", geo_path)

    # The same zones cut on union boundaries, for the web map: a zone inside a
    # union can then be named, and nothing outside the unions is dropped.
    zones = aggregate.split_zones_by_union(polygons, unions)
    zones_path = Path(cfg.paths.predictions) / f"change_zones_{forecast_month}.geojson"
    zones.to_file(zones_path, driver="GeoJSON")
    logger.info("wrote %s (%d zones)", zones_path, len(zones))

    stats.update(
        {
            "forecast_month": forecast_month,
            "total_erosion_ha": erosion_ha,
            "total_accretion_ha": accretion_ha,
            "n_polygons": int(len(polygons)),
            "n_buildings_osm": int(len(buildings)),
            "n_unions_affected": int(len(table)),
            "osm_cells_requested": int(coverage.cells_requested),
            "osm_cells_answered": int(coverage.cells_answered),
            "osm_mapping": {k: int(v) for k, v in table["osm_mapping"].value_counts().items()},
            "osm_mapping_bands": {
                "low_below": float(cfg.risk.osm_density_low_below),
                "high_from": float(cfg.risk.osm_density_high_from),
                "min_area_km2": float(cfg.risk.osm_density_min_area_km2),
            },
            "bn_names": {
                "unions_named": int(table["union_bn"].notna().sum()),
                "methods": {k: int(v) for k, v in name_review["method"].value_counts().items()},
                "portal_checks": (
                    {k: int(v) for k, v in name_review["union_check"].value_counts().items()}
                    if "union_check" in name_review else "not run"
                ),
                "source": str(cfg.risk.bn_names_url),
            },
            "water_threshold": float(cfg.risk.erosion_prob_threshold),
            "threshold_calibration": threshold_report,
            "model": str(cfg.model.name),
            "checkpoint": str(args.checkpoint),
        }
    )
    (Path(cfg.paths.tables) / f"risk_summary_{forecast_month}.json").write_text(
        json.dumps(stats, indent=2), encoding="utf-8"
    )

    if not table.empty:
        logger.info("--- top unions by households at risk ---")
        for _, row in table.head(10).iterrows():
            logger.info(
                "%-28s %-18s erosion=%7.1f ha  buildings=%4d",
                str(row.get("union", "?")), str(row.get("district", "?")),
                row["erosion_ha"], int(row["buildings_osm"]),
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
