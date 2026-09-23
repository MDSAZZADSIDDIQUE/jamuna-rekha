import { describe, expect, it } from "vitest";

import { makeFormatter } from "./format";
import { dictionaries } from "./i18n";
import { districtOptions } from "./table";
import type { UnionRow } from "./types";
import { boundsOf, unionsInView, zoneCard, zoneInView, type ZoneFeature } from "./zones";

function row(overrides: Partial<UnionRow> = {}): UnionRow {
  return {
    forecast_month: "2025-03",
    division: "Rangpur",
    district: "Kurigram",
    upazila: "Chilmari",
    union: "AshtamirChar",
    gid_union: "A",
    erosion_ha: 910,
    buildings_osm: 12,
    accretion_ha: 0,
    net_land_change_ha: -910,
    households_est: 12,
    persons_est: 54,
    osm_completeness_assumed: 1,
    osm_buildings_per_km2: 40,
    osm_measured_km2: 30,
    osm_mapping: "medium",
    division_bn: "রংপুর",
    district_bn: "কুড়িগ্রাম",
    upazila_bn: "চিলমারী",
    union_bn: "অষ্টমীর চর",
    union_display: "Ashtamir Char",
    upazila_display: "Chilmari",
    ...overrides,
  };
}

const square = (west: number, south: number, u: string | null, k: "e" | "a" = "e"): ZoneFeature => ({
  type: "Feature",
  properties: { k, ha: 1.4, u },
  geometry: {
    type: "Polygon",
    coordinates: [[[west, south], [west + 0.01, south], [west + 0.01, south + 0.01], [west, south + 0.01], [west, south]]],
  },
});

describe("unionsInView", () => {
  const rows = [row({ gid_union: "A" }), row({ gid_union: "B", district: "Bogra" })];

  it("is null when nothing is filtered: every zone is in view", () => {
    expect(unionsInView(rows, { district: "", query: "", minErosion: 0 })).toBeNull();
  });

  it("keeps the unions the table keeps", () => {
    expect(unionsInView(rows, { district: "Bogra", query: "", minErosion: 0 })).toEqual(new Set(["B"]));
  });
});

describe("zoneInView", () => {
  it("shows every zone, even outside the unions, when nothing is filtered", () => {
    expect(zoneInView({ k: "e", ha: 1, u: null }, null)).toBe(true);
  });

  it("fades zones outside every union once a filter is on", () => {
    const view = new Set(["A"]);
    expect(zoneInView({ k: "e", ha: 1, u: "A" }, view)).toBe(true);
    expect(zoneInView({ k: "e", ha: 1, u: "B" }, view)).toBe(false);
    expect(zoneInView({ k: "e", ha: 1, u: null }, view)).toBe(false);
  });
});

function expectBounds(actual: number[] | null, expected: number[]) {
  expect(actual).not.toBeNull();
  actual!.forEach((value, i) => expect(value).toBeCloseTo(expected[i], 9));
}

describe("boundsOf", () => {
  const zones = [square(89.6, 25.5, "A"), square(89.7, 25.8, "B"), square(89.9, 26.1, null)];

  it("boxes the zones it is asked for", () => {
    expectBounds(boundsOf(zones, (z) => z.u === "A" || z.u === "B"), [89.6, 25.5, 89.71, 25.81]);
  });

  it("walks multipolygons too", () => {
    const multi: ZoneFeature = {
      type: "Feature",
      properties: { k: "a", ha: 3, u: "C" },
      geometry: { type: "MultiPolygon", coordinates: [square(89.4, 24.6, null).geometry.coordinates as never, square(89.5, 24.9, null).geometry.coordinates as never] },
    };
    expectBounds(boundsOf([multi], () => true), [89.4, 24.6, 89.51, 24.91]);
  });

  it("is null when no zone qualifies", () => {
    expect(boundsOf(zones, () => false)).toBeNull();
  });
});

describe("zoneCard", () => {
  const bn = dictionaries.bn;
  const en = dictionaries.en;

  it("leads with the area and names the union in the page's language", () => {
    const card = zoneCard({ k: "e", ha: 742, u: "A" }, row(), "bn", bn, makeFormatter("bn"));
    expect(card.value).toBe("৭৪২ হে.");
    expect(card.kind).toBe(bn.legendErosion);
    expect(card.place).toBe("অষ্টমীর চর");
    expect(card.location).toBe("চিলমারী · কুড়িগ্রাম");
  });

  it("says 'unknown' for households where the erosion zone has no mapped building", () => {
    const unmapped = row({ buildings_osm: 0, households_est: 0 });
    const card = zoneCard({ k: "e", ha: 5, u: "A" }, unmapped, "en", en, makeFormatter("en"));
    expect(card.totals).toBe(en.zoneUnionTotals("910", en.unknown));
  });

  it("says so when a zone lies outside every union", () => {
    const card = zoneCard({ k: "a", ha: 0.3, u: null }, undefined, "en", en, makeFormatter("en"));
    expect(card.value).toBe("<1 ha");
    expect(card.place).toBe(en.zoneOutside);
    expect(card.totals).toBeNull();
  });
});

describe("districtOptions", () => {
  it("lists each district once with its count, labelled and ordered for the page", () => {
    const rows = [
      row({ gid_union: "1", district: "Kurigram", district_bn: "কুড়িগ্রাম" }),
      row({ gid_union: "2", district: "Bogra", district_bn: "বগুড়া" }),
      row({ gid_union: "3", district: "Kurigram", district_bn: "কুড়িগ্রাম" }),
    ];
    expect(districtOptions(rows, "en")).toEqual([
      { value: "Bogra", label: "Bogra", count: 1 },
      { value: "Kurigram", label: "Kurigram", count: 2 },
    ]);
    expect(districtOptions(rows, "bn").map((d) => d.label)).toEqual(["কুড়িগ্রাম", "বগুড়া"]);
  });
});
