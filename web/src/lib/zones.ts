/**
 * The web map's zones, and the rules for drawing them: which zones are in the
 * current view, where to zoom, and what a zone's card says.
 *
 * Pure functions, no Leaflet, so the rules can be unit tested.
 */

import type { Formatter } from "./format";
import type { Dictionary } from "./i18n";
import { DEFAULT_STATE, filterRows, isFiltered, isUnmapped, placeNames, type TableState } from "./table";
import type { Lang, UnionRow } from "./types";

/** e = predicted erosion, a = accretion; as written by the Python bridge. */
export type ZoneKind = "e" | "a";

export interface ZoneProperties {
  k: ZoneKind;
  /** Area in hectares, measured before the zone was simplified for the web. */
  ha: number;
  /** GADM id of the union the zone lies in; null outside every union. */
  u: string | null;
}

type Position = [number, number];

export type ZoneGeometry =
  | { type: "Polygon"; coordinates: Position[][] }
  | { type: "MultiPolygon"; coordinates: Position[][][] };

export interface ZoneFeature {
  type: "Feature";
  properties: ZoneProperties;
  geometry: ZoneGeometry;
}

export interface ZoneCollection {
  type: "FeatureCollection";
  features: ZoneFeature[];
}

/** [west, south, east, north] in degrees, EPSG:4326. */
export type Bounds = [number, number, number, number];

/**
 * The unions the current filters keep, or null when nothing is filtered:
 * everything is in view. Sort order is not a filter and plays no part.
 */
export function unionsInView(
  rows: readonly UnionRow[],
  filters: Pick<TableState, "district" | "query" | "minErosion">,
): Set<string> | null {
  const state = { ...DEFAULT_STATE, ...filters };
  if (!isFiltered(state)) return null;
  return new Set(filterRows(rows, state).map((row) => row.gid_union));
}

/**
 * Whether a zone belongs to the current view. A zone outside every union
 * matches no filter, so it is in view only when nothing is filtered.
 */
export function zoneInView(zone: ZoneProperties, inView: Set<string> | null): boolean {
  return inView === null || (zone.u !== null && inView.has(zone.u));
}

/** The box around the zones that `keep` accepts, or null if it accepts none. */
export function boundsOf(features: readonly ZoneFeature[], keep: (zone: ZoneProperties) => boolean): Bounds | null {
  let west = Infinity;
  let south = Infinity;
  let east = -Infinity;
  let north = -Infinity;
  for (const feature of features) {
    if (!keep(feature.properties)) continue;
    const polygons =
      feature.geometry.type === "Polygon" ? [feature.geometry.coordinates] : feature.geometry.coordinates;
    for (const polygon of polygons) {
      for (const ring of polygon) {
        for (const [lon, lat] of ring) {
          if (lon < west) west = lon;
          if (lon > east) east = lon;
          if (lat < south) south = lat;
          if (lat > north) north = lat;
        }
      }
    }
  }
  return Number.isFinite(west) ? [west, south, east, north] : null;
}

export interface ZoneCardText {
  /** The zone's area: the value leads. */
  value: string;
  kind: string;
  /** Union name, or "outside union boundaries". */
  place: string;
  location: string | null;
  /** The whole union's figures, as in the table. */
  totals: string | null;
}

/** What the card for one zone says, in the page's language and digits. */
export function zoneCard(
  zone: ZoneProperties,
  row: UnionRow | undefined,
  lang: Lang,
  t: Dictionary,
  fmt: Formatter,
): ZoneCardText {
  const value = `${fmt.hectares(zone.ha)} ${t.hectaresShort}`;
  const kind = zone.k === "e" ? t.legendErosion : t.legendAccretion;
  if (!row) return { value, kind, place: t.zoneOutside, location: null, totals: null };
  const names = placeNames(row, lang);
  const households = isUnmapped(row) ? t.unknown : fmt.int(row.households_est);
  return {
    value,
    kind,
    place: names.union,
    location: t.locationLine(names.upazila, names.district),
    totals: t.zoneUnionTotals(fmt.int(row.erosion_ha), households),
  };
}
