/**
 * Build-time data access. Runs only during `next build` (Server Components
 * under a static export), reading the JSON written by scripts/sync_web_data.py.
 */

import { existsSync, readFileSync } from "node:fs";
import path from "node:path";

import { isUnmapped } from "./table";
import type { ForecastData, UnionRow } from "./types";

const SCHEMA = 3;

let cached: ForecastData | null = null;

/**
 * Load and sanity-check forecast.json. A malformed or mismatched file fails
 * the build — publishing a page with wrong numbers is worse than publishing
 * nothing.
 */
export function loadForecast(): ForecastData {
  if (cached) return cached;
  const file = path.join(process.cwd(), "public", "data", "forecast.json");
  const data = JSON.parse(readFileSync(file, "utf8")) as ForecastData;

  if (data.schema !== SCHEMA) {
    throw new Error(
      `forecast.json has schema ${String(data.schema)}; this site reads schema ${SCHEMA}. ` +
        "Re-run scripts/sync_web_data.py, or update src/lib/types.ts to match.",
    );
  }
  if (!Array.isArray(data.rows) || data.rows.length === 0) {
    throw new Error("forecast.json has no rows. Run Stage 4, then scripts/sync_web_data.py.");
  }
  if (!data.map?.file || data.map.bbox?.length !== 4) {
    throw new Error("forecast.json has no map block. Re-run scripts/sync_web_data.py.");
  }
  if (!existsSync(path.join(process.cwd(), "public", "data", data.map.file))) {
    throw new Error(`forecast.json names ${data.map.file}, which is not in public/data.`);
  }
  if (data.rows.length !== data.source.rows) {
    throw new Error(`forecast.json lists ${data.source.rows} rows but contains ${data.rows.length}.`);
  }
  cached = data;
  return data;
}

export interface Summary {
  /** Every union in the table: predicted erosion, accretion, or both. */
  unions: number;
  /** Unions with any predicted erosion. */
  erodingUnions: number;
  /** Summed over the table, i.e. inside Bangladeshi union boundaries only. */
  erosionHa: number;
  accretionHa: number;
  /** A floor, not an estimate: unmapped unions contribute nothing. */
  households: number;
  /** Unions with at least one mapped building in the erosion zone. */
  mappedUnions: number;
  /** Eroding unions with no mapped building in the erosion zone. */
  unmappedUnions: number;
  /** ...of which the whole union is barely mapped (osm_mapping "low"). */
  unmappedLowMapping: number;
  /** Unions shown with a Bengali name. */
  namedUnions: number;
  /** Share of the whole forecast's erosion that falls inside the table. */
  insideShare: number;
}

export function summarise(rows: readonly UnionRow[], totalErosionHa: number): Summary {
  const erosionHa = rows.reduce((sum, row) => sum + row.erosion_ha, 0);
  return {
    unions: rows.length,
    erodingUnions: rows.filter((row) => row.erosion_ha > 0).length,
    erosionHa,
    accretionHa: rows.reduce((sum, row) => sum + row.accretion_ha, 0),
    households: rows.reduce((sum, row) => sum + row.households_est, 0),
    mappedUnions: rows.filter((row) => row.buildings_osm > 0).length,
    unmappedUnions: rows.filter(isUnmapped).length,
    unmappedLowMapping: rows.filter((row) => isUnmapped(row) && row.osm_mapping === "low").length,
    namedUnions: rows.filter((row) => row.union_bn).length,
    insideShare: totalErosionHa > 0 ? erosionHa / totalErosionHa : 0,
  };
}
