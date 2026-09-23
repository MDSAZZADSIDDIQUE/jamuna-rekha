"use client";

import { useId, useMemo } from "react";

import { makeFormatter, type Formatter } from "@/lib/format";
import { dictionaries, type Dictionary } from "@/lib/i18n";
import {
  filterRows,
  filteredFileName,
  isFiltered,
  isUnmapped,
  placeNames,
  sortRows,
  toCsv,
  type SortKey,
  type TableState,
} from "@/lib/table";
import type { Lang, UnionRow } from "@/lib/types";
import { useTableState, writeState } from "@/lib/urlState";

// ------------------------------------------------------------- columns

const COLUMNS: readonly SortKey[] = [
  "union",
  "erosion_ha",
  "accretion_ha",
  "net_land_change_ha",
  "buildings_osm",
  "households_est",
  "persons_est",
  "osm_buildings_per_km2",
];

function saveCsv(text: string, fileName: string): void {
  const url = URL.createObjectURL(new Blob([text], { type: "text/csv;charset=utf-8" }));
  const link = document.createElement("a");
  link.href = url;
  link.download = fileName;
  document.body.append(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

interface Props {
  lang: Lang;
  rows: UnionRow[];
  month: string;
  /** The pipeline's own CSV, served unchanged from public/data. */
  downloadHref: string;
  downloadName: string;
  /** OSM mapping density band edges Stage 4 applied, buildings per km². */
  bands: { low_below: number; high_from: number };
}

export function UnionTable({ lang, rows, month, downloadHref, downloadName, bands }: Props) {
  const t = dictionaries[lang];
  const fmt = useMemo(() => makeFormatter(lang), [lang]);
  const ids = useId();

  const state = useTableState();
  const update = (patch: Partial<TableState>) => writeState({ ...state, ...patch });

  // Bars are scaled to the largest union in the whole table, not the
  // filtered view, so a bar means the same length for the same hectares
  // whatever filter is on.
  const maxErosion = useMemo(() => Math.max(...rows.map((row) => row.erosion_ha)), [rows]);

  const shown = useMemo(
    () => sortRows(filterRows(rows, state), state.sort, state.dir, lang),
    [rows, state, lang],
  );
  const filtered = isFiltered(state);

  const order =
    state.sort === "union"
      ? state.dir === "asc" ? t.orders.az : t.orders.za
      : state.dir === "desc" ? t.orders.desc : t.orders.asc;

  function toggleSort(key: SortKey) {
    if (key === state.sort) {
      update({ dir: state.dir === "asc" ? "desc" : "asc" });
    } else {
      // Names read naturally A to Z; numbers are asked about largest first.
      update({ sort: key, dir: key === "union" ? "asc" : "desc" });
    }
  }

  const headingId = `${ids}-heading`;
  const statusId = `${ids}-status`;

  return (
    <div>
      <h2 id={headingId} className="text-xl font-semibold">
        {t.tableHeading}
      </h2>

      <div className="mt-4 flex flex-wrap items-center justify-between gap-x-6 gap-y-3">
        <p id={statusId} role="status" className="text-sm text-ink-2">
          {t.showing(fmt.int(shown.length), fmt.int(rows.length))} ·{" "}
          {t.sortedBy(t.columns[state.sort], order)}
        </p>

        <div className="flex flex-col items-start gap-1 sm:items-end">
          {filtered ? (
            <button
              type="button"
              disabled={shown.length === 0}
              onClick={() => saveCsv(toCsv(shown), filteredFileName(month, state))}
              className="min-h-10 rounded-md bg-accent-ink px-4 text-sm font-semibold text-white underline-offset-4 hover:underline disabled:cursor-not-allowed disabled:opacity-50 disabled:hover:no-underline dark:text-surface-sunken"
            >
              {t.downloadFiltered(fmt.int(shown.length))}
            </button>
          ) : (
            <a
              href={downloadHref}
              download={downloadName}
              className="inline-flex min-h-10 items-center rounded-md bg-accent-ink px-4 text-sm font-semibold text-white underline-offset-4 hover:underline dark:text-surface-sunken"
            >
              {t.downloadAll(fmt.int(rows.length))}
            </a>
          )}
          <span className="text-xs text-ink-muted">
            {filtered ? t.downloadFilteredNote : t.downloadAllNote}
          </span>
        </div>
      </div>

      {/* A table this wide cannot fit a phone; it scrolls inside its own box
          (keyboard-scrollable, hence the tabIndex) while the union name
          column stays pinned, and the page itself never scrolls sideways. */}
      <div
        role="region"
        aria-labelledby={headingId}
        tabIndex={0}
        className="mt-4 overflow-x-auto rounded-lg border border-rule bg-surface-raised"
      >
        <table className="w-full min-w-[60rem] border-collapse text-sm">
          <caption className="sr-only">{t.tableCaption}</caption>
          <thead>
            <tr className="border-b border-rule bg-surface-sunken text-ink-2">
              {COLUMNS.map((key) => {
                const active = key === state.sort;
                const numeric = key !== "union";
                return (
                  <th
                    key={key}
                    scope="col"
                    aria-sort={active ? (state.dir === "asc" ? "ascending" : "descending") : undefined}
                    className={`px-3 py-2 font-medium ${numeric ? "text-right" : "sticky left-0 z-10 bg-surface-sunken text-left"}`}
                  >
                    <button
                      type="button"
                      onClick={() => toggleSort(key)}
                      className={`inline-flex items-center gap-1 rounded-sm whitespace-nowrap hover:text-ink ${active ? "text-ink" : ""} ${numeric ? "flex-row-reverse" : ""}`}
                    >
                      <span>{t.columns[key]}</span>
                      <span aria-hidden="true" className={`w-3 text-xs ${active ? "" : "opacity-0"}`}>
                        {active && state.dir === "asc" ? "▲" : "▼"}
                      </span>
                    </button>
                  </th>
                );
              })}
            </tr>
          </thead>
          <tbody>
            {shown.length === 0 ? (
              <tr>
                <td colSpan={COLUMNS.length} className="px-3 py-8 text-center text-ink-2">
                  {t.empty}
                </td>
              </tr>
            ) : (
              shown.map((row) => (
                <Row key={row.gid_union} row={row} lang={lang} t={t} fmt={fmt} maxErosion={maxErosion} />
              ))
            )}
          </tbody>
        </table>
      </div>

      <div className="mt-3 max-w-3xl space-y-2 text-sm text-ink-2">
        <p>{t.footnote}</p>
        <p>{t.mappingNote(fmt.int(bands.low_below), fmt.int(bands.high_from))}</p>
      </div>
    </div>
  );
}

interface RowProps {
  row: UnionRow;
  lang: Lang;
  t: Dictionary;
  fmt: Formatter;
  maxErosion: number;
}

function Row({ row, lang, t, fmt, maxErosion }: RowProps) {
  const names = placeNames(row, lang);
  const unmapped = isUnmapped(row);
  const share = maxErosion > 0 ? row.erosion_ha / maxErosion : 0;
  const cell = "px-3 py-2 text-right tabular-nums";
  const unknown = <span className="text-ink-muted">{t.unknown}</span>;

  return (
    <tr className="border-b border-rule last:border-b-0">
      <th scope="row" className="sticky left-0 z-10 bg-surface-raised px-3 py-2 text-left font-normal">
        <span className="block font-medium text-ink">{names.union}</span>
        <span className="block text-xs text-ink-muted">
          {t.locationLine(names.upazila, names.district)}
        </span>
      </th>
      <td className={cell}>
        <span className="block">{fmt.hectares(row.erosion_ha)}</span>
        {/* Decorative: the number beside it carries the value. */}
        <span aria-hidden="true" className="mt-1 ml-auto block h-1.5 w-24 rounded-full bg-erosion-track">
          <span
            className="block h-full rounded-full bg-erosion"
            style={{ width: `${Math.max(share * 100, row.erosion_ha > 0 ? 2 : 0)}%` }}
          />
        </span>
      </td>
      <td className={cell}>{fmt.hectares(row.accretion_ha)}</td>
      <td className={cell}>{fmt.signed(row.net_land_change_ha)}</td>
      <td className={cell}>
        {unmapped ? <span className="text-ink-muted">{t.noneMapped}</span> : fmt.int(row.buildings_osm)}
      </td>
      <td className={cell}>{unmapped ? unknown : fmt.int(row.households_est)}</td>
      <td className={cell}>{unmapped ? unknown : fmt.int(row.persons_est)}</td>
      <td className={cell}>
        <span className={`block ${row.osm_buildings_per_km2 === null ? "text-ink-muted" : ""}`}>
          {t.mappingLevels[row.osm_mapping]}
        </span>
        {row.osm_buildings_per_km2 !== null && (
          <span className="block text-xs text-ink-muted">
            {t.perKm2(fmt.density(row.osm_buildings_per_km2))}
          </span>
        )}
      </td>
    </tr>
  );
}
