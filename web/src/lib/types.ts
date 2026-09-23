/**
 * The shape of public/data/forecast.json, written by
 * src/jamunarekha/dashboard/web_export.py. Keep the two in step: the Python
 * side stamps `schema`, and lib/data.ts refuses to build against any other.
 */

export type Lang = "bn" | "en";

/** How densely a union is mapped in OpenStreetMap; see Stage 4's osm_mapping. */
export type MappingLevel = "low" | "medium" | "high" | "not measured";

/** One union parishad. Field names match the Stage 4 DDM CSV exactly. */
export interface UnionRow {
  forecast_month: string;
  division: string;
  district: string;
  upazila: string;
  union: string;
  gid_union: string;
  erosion_ha: number;
  buildings_osm: number;
  accretion_ha: number;
  net_land_change_ha: number;
  households_est: number;
  persons_est: number;
  osm_completeness_assumed: number;
  /**
   * Mapped OSM buildings per km² across the union, over the part the building
   * query covered (water included). Null where that part was too small.
   */
  osm_buildings_per_km2: number | null;
  osm_measured_km2: number;
  osm_mapping: MappingLevel;
  /** Bengali names, checked against each unit's official portal; null where no match was confident. */
  division_bn: string | null;
  district_bn: string | null;
  upazila_bn: string | null;
  union_bn: string | null;
  /** GADM name with CamelCase split for reading; `union` is the original. */
  union_display: string;
  upazila_display: string;
}

export interface ForecastData {
  schema: 3;
  forecast: {
    month: string;
    anchor_months: string[];
    reference_months: string[];
    seasonally_matched: boolean;
    horizon_months: number;
    model: string;
    water_threshold: number;
    /** Includes area outside Bangladeshi union boundaries. */
    total_erosion_ha: number;
    total_accretion_ha: number;
    n_polygons: number;
  };
  accuracy: {
    split: string;
    n_windows: number;
    bank_f1: number;
    mde_m: number;
    bank_f1_at_horizon: number;
    mde_m_at_horizon: number;
    resolution_m: number;
    crop_size: number;
  };
  assumptions: {
    persons_per_household: number;
    osm_completeness: number[];
    /** The band edges Stage 4 applied, in buildings per km². */
    osm_mapping_bands: { low_below: number; high_from: number; min_area_km2: number };
  };
  names: {
    source: string | null;
    unions_named: number;
    portal_checks: Record<string, number> | string | null;
  };
  source: {
    file: string;
    download: string;
    sha256: string;
    rows: number;
    metrics_file: string;
    summary_file: string;
  };
  /** The web map's zones file in public/data, written by the Python bridge. */
  map: {
    file: string;
    features: number;
    /** [west, south, east, north], EPSG:4326. */
    bbox: [number, number, number, number];
    simplify_m: number;
  };
  rows: UnionRow[];
}
