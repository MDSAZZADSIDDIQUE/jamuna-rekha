import { readFileSync } from "node:fs";
import path from "node:path";

import { describe, expect, it } from "vitest";

import {
  CSV_COLUMNS,
  DEFAULT_STATE,
  filterRows,
  filteredFileName,
  isFiltered,
  isUnmapped,
  parseState,
  placeNames,
  serialiseState,
  sortRows,
  toCsv,
  type TableState,
} from "./table";
import type { ForecastData, UnionRow } from "./types";

function row(overrides: Partial<UnionRow> = {}): UnionRow {
  return {
    forecast_month: "2025-03",
    division: "Rangpur",
    district: "Kurigram",
    upazila: "Chilmari",
    union: "AshtamirChar",
    gid_union: "BGD.6.3.2.1_1",
    erosion_ha: 100,
    buildings_osm: 10,
    accretion_ha: 0,
    net_land_change_ha: -100,
    households_est: 10,
    persons_est: 45,
    osm_completeness_assumed: 1,
    osm_buildings_per_km2: 171.6,
    osm_measured_km2: 40.2,
    osm_mapping: "high",
    division_bn: "রংপুর",
    district_bn: "কুড়িগ্রাম",
    upazila_bn: "চিলমারী",
    union_bn: "অষ্টমীর চর",
    union_display: "Ashtamir Char",
    upazila_display: "Chilmari",
    ...overrides,
  };
}

const state = (overrides: Partial<TableState> = {}): TableState => ({ ...DEFAULT_STATE, ...overrides });

describe("isUnmapped", () => {
  it("flags erosion with no mapped building: households unknown", () => {
    expect(isUnmapped(row({ erosion_ha: 50, buildings_osm: 0 }))).toBe(true);
  });

  it("does not flag a union with mapped buildings", () => {
    expect(isUnmapped(row({ erosion_ha: 50, buildings_osm: 3 }))).toBe(false);
  });

  it("does not flag a union with no predicted erosion: its zero is real", () => {
    expect(isUnmapped(row({ erosion_ha: 0, buildings_osm: 0, accretion_ha: 12 }))).toBe(false);
  });
});

describe("filterRows", () => {
  const rows = [
    row({ gid_union: "a", district: "Kurigram", erosion_ha: 5 }),
    row({ gid_union: "b", district: "Bogra", erosion_ha: 100, union: "SaheberAlga", union_display: "Saheber Alga" }),
    row({ gid_union: "c", district: "Bogra", erosion_ha: 500, upazila: "Sariakandi", upazila_display: "Sariakandi" }),
  ];
  const ids = (list: UnionRow[]) => list.map((r) => r.gid_union);

  it("keeps everything by default", () => {
    expect(ids(filterRows(rows, state()))).toEqual(["a", "b", "c"]);
  });

  it("filters by exact district", () => {
    expect(ids(filterRows(rows, state({ district: "Bogra" })))).toEqual(["b", "c"]);
  });

  it("treats the minimum erosion as inclusive", () => {
    expect(ids(filterRows(rows, state({ minErosion: 100 })))).toEqual(["b", "c"]);
  });

  it("matches the readable and the original GADM name, ignoring case and padding", () => {
    expect(ids(filterRows(rows, state({ query: "  saheber al " })))).toEqual(["b"]);
    expect(ids(filterRows(rows, state({ query: "saheberalga" })))).toEqual(["b"]);
  });

  it("matches upazila names", () => {
    expect(ids(filterRows(rows, state({ query: "sariakandi" })))).toEqual(["c"]);
  });

  it("matches Bengali names, whatever normal form they were typed in", () => {
    const named = [row({ gid_union: "x", union_bn: "সাহেবের আলগা" }), row({ gid_union: "y", union_bn: null })];
    expect(ids(filterRows(named, state({ query: "সাহেবের" })))).toEqual(["x"]);
    // য় typed as one precomposed character still finds the stored form.
    const precomposed = String.fromCharCode(0x09df);
    const stored = [row({ gid_union: "z", union_bn: "হলদিয়া".normalize("NFC") })];
    expect(ids(filterRows(stored, state({ query: `হলদি${precomposed}া` })))).toEqual(["z"]);
  });
});

describe("placeNames", () => {
  it("shows Bengali names on the Bengali page", () => {
    expect(placeNames(row(), "bn")).toEqual({ union: "অষ্টমীর চর", upazila: "চিলমারী", district: "কুড়িগ্রাম" });
  });

  it("falls back to the English spelling where no Bengali name was matched", () => {
    const unmatched = row({ union_bn: null, upazila_bn: null, district_bn: null });
    expect(placeNames(unmatched, "bn")).toEqual({ union: "Ashtamir Char", upazila: "Chilmari", district: "Kurigram" });
  });

  it("always shows English names on the English page", () => {
    expect(placeNames(row(), "en").union).toBe("Ashtamir Char");
  });
});

describe("sortRows", () => {
  const mapped = row({ gid_union: "mapped", erosion_ha: 50, buildings_osm: 40, households_est: 40, persons_est: 180 });
  const small = row({ gid_union: "small", erosion_ha: 10, buildings_osm: 2, households_est: 2, persons_est: 9 });
  const unmapped = row({ gid_union: "unmapped", erosion_ha: 900, buildings_osm: 0, households_est: 0, persons_est: 0 });
  const accretionOnly = row({ gid_union: "accretion", erosion_ha: 0, buildings_osm: 0, households_est: 0, persons_est: 0 });
  const rows = [small, unmapped, accretionOnly, mapped];
  const ids = (list: UnionRow[]) => list.map((r) => r.gid_union);

  it("sorts by erosion, largest first, by default", () => {
    expect(ids(sortRows(rows, DEFAULT_STATE.sort, DEFAULT_STATE.dir))).toEqual([
      "unmapped",
      "mapped",
      "small",
      "accretion",
    ]);
  });

  it("puts unknown household counts last whichever way the column is sorted", () => {
    expect(ids(sortRows(rows, "households_est", "desc"))).toEqual(["mapped", "small", "accretion", "unmapped"]);
    expect(ids(sortRows(rows, "households_est", "asc"))).toEqual(["accretion", "small", "mapped", "unmapped"]);
    expect(ids(sortRows(rows, "persons_est", "asc")).at(-1)).toBe("unmapped");
  });

  it("sorts names by their readable form, ignoring case", () => {
    const named = [
      row({ gid_union: "1", union_display: "char Bhurungamari" }),
      row({ gid_union: "2", union_display: "Bangasonahat" }),
      row({ gid_union: "3", union_display: "Shilkhuri" }),
    ];
    expect(ids(sortRows(named, "union", "asc"))).toEqual(["2", "1", "3"]);
    expect(ids(sortRows(named, "union", "desc"))).toEqual(["3", "1", "2"]);
  });

  it("sorts Bengali names in Bengali order on the Bengali page", () => {
    const named = [
      row({ gid_union: "1", union_bn: "হলদিয়া" }),
      row({ gid_union: "2", union_bn: "অষ্টমীর চর" }),
      row({ gid_union: "3", union_bn: "কাপাসিয়া" }),
    ];
    expect(ids(sortRows(named, "union", "asc", "bn"))).toEqual(["2", "3", "1"]);
  });

  it("puts unions whose mapping was not measured last", () => {
    const mixed = [
      row({ gid_union: "none", osm_buildings_per_km2: null, osm_mapping: "not measured" }),
      row({ gid_union: "sparse", osm_buildings_per_km2: 0.4, osm_mapping: "low" }),
      row({ gid_union: "dense", osm_buildings_per_km2: 171.6, osm_mapping: "high" }),
    ];
    expect(ids(sortRows(mixed, "osm_buildings_per_km2", "asc"))).toEqual(["sparse", "dense", "none"]);
    expect(ids(sortRows(mixed, "osm_buildings_per_km2", "desc"))).toEqual(["dense", "sparse", "none"]);
  });

  it("breaks ties deterministically, whatever the input order", () => {
    const tied = [
      row({ gid_union: "z", accretion_ha: 1, erosion_ha: 5 }),
      row({ gid_union: "y", accretion_ha: 1, erosion_ha: 9 }),
      row({ gid_union: "x", accretion_ha: 1, erosion_ha: 9 }),
    ];
    const expected = ["x", "y", "z"];
    expect(ids(sortRows(tied, "accretion_ha", "desc"))).toEqual(expected);
    expect(ids(sortRows([...tied].reverse(), "accretion_ha", "asc"))).toEqual(expected);
  });

  it("does not reorder its input", () => {
    const input = [...rows];
    sortRows(input, "union", "asc");
    expect(input).toEqual(rows);
  });
});

describe("URL state", () => {
  it("writes nothing for the default view", () => {
    expect(serialiseState(DEFAULT_STATE)).toBe("");
    expect(parseState("")).toEqual(DEFAULT_STATE);
  });

  it("round-trips a full view", () => {
    const view = state({ district: "Bogra", query: "char", minErosion: 100, sort: "households_est", dir: "asc" });
    expect(parseState(`?${serialiseState(view)}`)).toEqual(view);
  });

  it("keeps a trailing space while the reader is typing a second word", () => {
    const typing = state({ query: "Char " });
    expect(parseState(serialiseState(typing)).query).toBe("Char ");
  });

  it("does not write a search of only spaces", () => {
    expect(serialiseState(state({ query: "   " }))).toBe("");
  });

  it("ignores values it does not recognise", () => {
    expect(parseState("?sort=bogus&dir=up&min=7")).toEqual(DEFAULT_STATE);
  });

  it("counts filters, not sort order, as filtering", () => {
    expect(isFiltered(state({ sort: "union", dir: "asc" }))).toBe(false);
    expect(isFiltered(state({ minErosion: 10 }))).toBe(true);
    expect(isFiltered(state({ query: "  " }))).toBe(false);
  });
});

describe("toCsv", () => {
  it("writes a BOM, CRLF line endings and the Stage 4 header", () => {
    const csv = toCsv([row()]);
    expect(csv.startsWith("\uFEFF")).toBe(true);
    expect(csv.endsWith("\r\n")).toBe(true);
    expect(csv.split("\r\n")[0]).toBe(`\uFEFF${CSV_COLUMNS.join(",")}`);
  });

  it("writes whole-valued float columns the way pandas does", () => {
    const line = toCsv([row({ erosion_ha: 0, accretion_ha: 1.44, osm_completeness_assumed: 1 })]).split("\r\n")[1];
    const cells = Object.fromEntries(line.split(",").map((cell, i) => [CSV_COLUMNS[i], cell]));
    expect(cells.erosion_ha).toBe("0.0");
    expect(cells.accretion_ha).toBe("1.44");
    expect(cells.osm_completeness_assumed).toBe("1.0");
    expect(cells.buildings_osm).toBe("10");
  });

  it("writes a missing value as an empty cell, as pandas does", () => {
    const line = toCsv([row({ osm_buildings_per_km2: null, osm_mapping: "not measured", union_bn: null })]).split("\r\n")[1];
    const cells = Object.fromEntries(line.split(",").map((cell, i) => [CSV_COLUMNS[i], cell]));
    expect(cells.osm_buildings_per_km2).toBe("");
    expect(cells.osm_mapping).toBe("not measured");
    expect(cells.union_bn).toBe("");
    expect(cells.upazila_bn).toBe("চিলমারী");
  });

  it("defuses text that a spreadsheet would run as a formula, and quotes commas", () => {
    const line = toCsv([row({ union: "=HYPERLINK(1)", upazila: 'Sadar, "North"' })]).split("\r\n")[1];
    expect(line).toContain(",'=HYPERLINK(1),");
    expect(line).toContain(',"Sadar, ""North""",');
  });

  it("reproduces the pipeline's CSV byte for byte from the site data", () => {
    const dir = path.join(process.cwd(), "public", "data");
    const data = JSON.parse(readFileSync(path.join(dir, "forecast.json"), "utf8")) as ForecastData;
    const original = readFileSync(path.join(dir, data.source.download), "utf8");
    expect(toCsv(data.rows)).toBe(original);
  });
});

describe("filteredFileName", () => {
  it("names the district when one is chosen", () => {
    expect(filteredFileName("2025-03", state({ district: "Bogra" }))).toBe(
      "jamunarekha_at_risk_2025-03_Bogra_filtered.csv",
    );
    expect(filteredFileName("2025-03", state({ minErosion: 10 }))).toBe("jamunarekha_at_risk_2025-03_filtered.csv");
  });
});
