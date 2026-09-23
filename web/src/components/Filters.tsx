"use client";

import { useMemo } from "react";

import { makeFormatter } from "@/lib/format";
import { dictionaries } from "@/lib/i18n";
import { DEFAULT_STATE, MIN_EROSION_STEPS, isFiltered, type TableState } from "@/lib/table";
import type { Lang } from "@/lib/types";
import { useTableState, writeState } from "@/lib/urlState";

export interface DistrictOption {
  /** GADM district name: the URL keeps it, so a link works on either page. */
  value: string;
  label: string;
  count: number;
}

/**
 * One row of filters above everything they scope: the map and the table
 * re-render against the same slice, so their numbers always agree.
 */
export function Filters({ lang, districts }: { lang: Lang; districts: DistrictOption[] }) {
  const t = dictionaries[lang];
  const fmt = useMemo(() => makeFormatter(lang), [lang]);
  const state = useTableState();
  const update = (patch: Partial<TableState>) => writeState({ ...state, ...patch });

  return (
    <div role="group" aria-label={t.filtersLabel} className="flex flex-wrap items-end gap-x-4 gap-y-3">
      <label className="flex flex-col gap-1 text-sm text-ink-2">
        {t.filterDistrict}
        <select
          value={state.district}
          onChange={(event) => update({ district: event.target.value })}
          className="min-h-10 rounded-md border border-rule bg-surface-raised px-2 text-base text-ink"
        >
          <option value="">{t.allDistricts}</option>
          {districts.map(({ value, label, count }) => (
            <option key={value} value={value}>
              {label} ({fmt.int(count)})
            </option>
          ))}
        </select>
      </label>

      <label className="flex min-w-0 flex-1 basis-48 flex-col gap-1 text-sm text-ink-2">
        {t.filterSearch}
        <input
          type="search"
          value={state.query}
          onChange={(event) => update({ query: event.target.value })}
          placeholder={t.searchPlaceholder}
          autoComplete="off"
          spellCheck={false}
          className="min-h-10 w-full rounded-md border border-rule bg-surface-raised px-3 text-base text-ink placeholder:text-ink-muted"
        />
      </label>

      <label className="flex flex-col gap-1 text-sm text-ink-2">
        {t.filterMinErosion}
        <select
          value={state.minErosion}
          onChange={(event) => update({ minErosion: Number(event.target.value) })}
          className="min-h-10 rounded-md border border-rule bg-surface-raised px-2 text-base text-ink"
        >
          {MIN_EROSION_STEPS.map((step) => (
            <option key={step} value={step}>
              {step === 0 ? t.anyErosion : t.atLeast(fmt.int(step))}
            </option>
          ))}
        </select>
      </label>

      {isFiltered(state) && (
        <button
          type="button"
          onClick={() => writeState({ ...DEFAULT_STATE, sort: state.sort, dir: state.dir })}
          className="min-h-10 rounded-md px-3 text-sm font-medium text-accent-ink underline underline-offset-4 hover:no-underline"
        >
          {t.resetFilters}
        </button>
      )}
    </div>
  );
}
