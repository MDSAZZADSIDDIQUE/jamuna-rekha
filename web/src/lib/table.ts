/**
 * Filtering, sorting, URL state and CSV export for the union table.
 *
 * Pure functions only — no React, no DOM — so they can be unit tested and so
 * the rules the table follows are written down in one place.
 */

import type { Lang, UnionRow } from "./types";

export type SortKey =
  | "union"
  | "erosion_ha"
  | "accretion_ha"
  | "net_land_change_ha"
  | "buildings_osm"
  | "households_est"
  | "persons_est"
  | "osm_buildings_per_km2";

export type SortDir = "asc" | "desc";

export interface TableState {
  district: string;
  query: string;
  minErosion: number;
  sort: SortKey;
  dir: SortDir;
}

/**
 * Default ordering is predicted erosion, largest first. Household counts are
 * skewed by how well each area is mapped in OpenStreetMap, so ranking by them
 * would rank unions by mapping density rather than by risk.
 */
export const DEFAULT_STATE: TableState = {
  district: "",
  query: "",
  minErosion: 0,
  sort: "erosion_ha",
  dir: "desc",
};

/** Hectare thresholds offered by the minimum-erosion filter. */
export const MIN_EROSION_STEPS = [0, 10, 100, 500] as const;

const SORT_KEYS: readonly SortKey[] = [
  "union",
  "erosion_ha",
  "accretion_ha",
  "net_land_change_ha",
  "buildings_osm",
  "households_est",
  "persons_est",
  "osm_buildings_per_km2",
];

/**
 * Erosion is predicted in this union, but no building is mapped inside the
 * erosion zone.
 *
 * That does not mean nobody lives there. The land may be unsettled char, or
 * the settlement may simply not be in OpenStreetMap — and across the southern
 * districts of the reach most unions are close to unmapped. The household
 * count for such a union is unknown, not zero.
 *
 * A union with no predicted erosion (it appears in the table for accretion
 * alone) has no erosion zone to count buildings in, so its zero households at
 * risk is a real zero.
 */
export function isUnmapped(row: UnionRow): boolean {
  return row.erosion_ha > 0 && row.buildings_osm === 0;
}

export interface PlaceNames {
  union: string;
  upazila: string;
  district: string;
}

/**
 * The names to show for a row. On the Bengali page, the Bengali name where
 * Stage 4 could match one with confidence, otherwise GADM's English spelling;
 * never a guess.
 */
export function placeNames(row: UnionRow, lang: Lang): PlaceNames {
  if (lang === "bn") {
    return {
      union: row.union_bn ?? row.union_display,
      upazila: row.upazila_bn ?? row.upazila_display,
      district: row.district_bn ?? row.district,
    };
  }
  return { union: row.union_display, upazila: row.upazila_display, district: row.district };
}

/**
 * The district filter's options: each district once, with its union count,
 * labelled in the page's language and in that language's alphabetical order.
 * The value stays the GADM name, so a shared link works on either page.
 */
export function districtOptions(
  rows: readonly UnionRow[],
  lang: Lang,
): { value: string; label: string; count: number }[] {
  const byName = new Map<string, { value: string; label: string; count: number }>();
  for (const row of rows) {
    const entry = byName.get(row.district) ?? { value: row.district, label: placeNames(row, lang).district, count: 0 };
    entry.count += 1;
    byName.set(row.district, entry);
  }
  return [...byName.values()].sort((a, b) => a.label.localeCompare(b.label, lang));
}

/** Households and persons are unknown (null) for unmapped unions. */
function sortValue(row: UnionRow, key: SortKey, lang: Lang): number | string | null {
  if (key === "union") return placeNames(row, lang).union;
  if ((key === "households_est" || key === "persons_est") && isUnmapped(row)) return null;
  return row[key];
}

/** Lower-cased and NFC-normalised, so typed Bengali matches stored Bengali. */
function fold(text: string): string {
  return text.normalize("NFC").toLowerCase();
}

export function filterRows(rows: readonly UnionRow[], state: TableState): UnionRow[] {
  const needle = fold(state.query.trim());
  return rows.filter((row) => {
    if (state.district && row.district !== state.district) return false;
    if (row.erosion_ha < state.minErosion) return false;
    if (!needle) return true;
    return [
      row.union_display, row.union, row.union_bn,
      row.upazila_display, row.upazila, row.upazila_bn,
    ].some((name) => name != null && fold(name).includes(needle));
  });
}

/**
 * Sort a copy of `rows`. Unknown values sort last in both directions — an
 * unknown household count is neither the largest nor the smallest. Ties are
 * broken by erosion, then by GADM id, so the order is fully deterministic.
 * Names sort by the names shown, in that language's alphabetical order.
 */
export function sortRows(
  rows: readonly UnionRow[],
  key: SortKey,
  dir: SortDir,
  lang: Lang = "en",
): UnionRow[] {
  const sign = dir === "asc" ? 1 : -1;
  return [...rows].sort((a, b) => {
    const va = sortValue(a, key, lang);
    const vb = sortValue(b, key, lang);
    if (va === null && vb !== null) return 1;
    if (vb === null && va !== null) return -1;
    if (va !== null && vb !== null && va !== vb) {
      const order =
        typeof va === "string" && typeof vb === "string"
          ? va.localeCompare(vb, lang, { sensitivity: "base" })
          : (va as number) - (vb as number);
      if (order !== 0) return sign * order;
    }
    if (a.erosion_ha !== b.erosion_ha) return b.erosion_ha - a.erosion_ha;
    return a.gid_union.localeCompare(b.gid_union);
  });
}

/** True when the current filters hide at least one row. */
export function isFiltered(state: TableState): boolean {
  return Boolean(state.district || state.query.trim() || state.minErosion > 0);
}

// ------------------------------------------------------------- URL state

/** Read table state from a query string, ignoring anything invalid. */
export function parseState(search: string): TableState {
  const params = new URLSearchParams(search);
  const state: TableState = { ...DEFAULT_STATE };

  const district = params.get("district");
  if (district) state.district = district;

  const query = params.get("q");
  if (query) state.query = query;

  const min = Number(params.get("min"));
  if ((MIN_EROSION_STEPS as readonly number[]).includes(min)) state.minErosion = min;

  const sort = params.get("sort") as SortKey | null;
  if (sort && SORT_KEYS.includes(sort)) state.sort = sort;

  const dir = params.get("dir");
  if (dir === "asc" || dir === "desc") state.dir = dir;

  return state;
}

/**
 * Write only what differs from the default, so a clean view has a clean URL.
 *
 * The search text is written untrimmed: the search box reads its value back
 * from the URL, and trimming here would delete the space between two words
 * as it is typed. Matching trims instead (see filterRows).
 */
export function serialiseState(state: TableState): string {
  const params = new URLSearchParams();
  if (state.district) params.set("district", state.district);
  if (state.query.trim()) params.set("q", state.query);
  if (state.minErosion > 0) params.set("min", String(state.minErosion));
  if (state.sort !== DEFAULT_STATE.sort) params.set("sort", state.sort);
  if (state.dir !== DEFAULT_STATE.dir) params.set("dir", state.dir);
  return params.toString();
}

// ------------------------------------------------------------------ CSV

/** Columns of the Stage 4 DDM CSV, in the order Stage 4 writes them. */
export const CSV_COLUMNS = [
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
] as const satisfies readonly (keyof UnionRow)[];

/**
 * Columns Stage 4 writes as floats. pandas prints a whole-valued float as
 * "1.0" where JavaScript prints "1"; following it keeps a filtered file
 * line-for-line identical to the matching lines of the full one.
 */
const FLOAT_COLUMNS: ReadonlySet<string> = new Set([
  "erosion_ha",
  "accretion_ha",
  "net_land_change_ha",
  "osm_completeness_assumed",
  "osm_buildings_per_km2",
  "osm_measured_km2",
]);

function csvCell(value: string | number | null, column: string): string {
  // pandas writes a missing value as an empty cell.
  if (value === null) return "";
  if (typeof value === "number") {
    if (!Number.isFinite(value)) return "";
    return FLOAT_COLUMNS.has(column) && Number.isInteger(value) ? value.toFixed(1) : String(value);
  }
  // A text cell beginning with one of these is run as a formula by
  // spreadsheet software. Place names never legitimately start with them.
  let text = /^[=+\-@\t\r]/.test(value) ? `'${value}` : value;
  if (/[",\r\n]/.test(text)) text = `"${text.replace(/"/g, '""')}"`;
  return text;
}

/**
 * A CSV of the given rows with the same columns and column order as the
 * pipeline's DDM file, so a filtered download can be read by anything that
 * reads the full one.
 *
 * UTF-8 with a byte-order mark and CRLF line endings, like the Stage 4 file:
 * without the BOM, Excel on Windows mis-decodes the text.
 */
export function toCsv(rows: readonly UnionRow[]): string {
  const lines = [CSV_COLUMNS.join(",")];
  for (const row of rows) {
    lines.push(CSV_COLUMNS.map((column) => csvCell(row[column], column)).join(","));
  }
  return `\uFEFF${lines.join("\r\n")}\r\n`;
}

/** File name for a filtered download, e.g. jamunarekha_at_risk_2025-03_Kurigram_filtered.csv */
export function filteredFileName(month: string, state: TableState): string {
  const parts = [`jamunarekha_at_risk_${month}`];
  if (state.district) parts.push(state.district.replace(/[^A-Za-z0-9-]+/g, "_"));
  parts.push("filtered");
  return `${parts.join("_")}.csv`;
}
