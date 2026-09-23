/**
 * The whole page, in one language. A Server Component: under a static export
 * it runs once per language at build time, so everything here but the table
 * ships as plain HTML.
 */

import { Filters } from "@/components/Filters";
import { MapSection } from "@/components/MapSection";
import { UnionTable } from "@/components/UnionTable";
import { loadForecast, summarise, type Summary } from "@/lib/data";
import { makeFormatter, roughly, type Formatter } from "@/lib/format";
import { dictionaries } from "@/lib/i18n";
import { withBase } from "@/lib/paths";
import { districtOptions } from "@/lib/table";
import type { Lang } from "@/lib/types";

/** Model names as the paper writes them. */
const MODEL_NAMES: Record<string, string> = {
  convlstm: "ConvLSTM",
  timesformer: "TimeSformer",
  persistence: "Persistence",
};

/** "test 2018-2024" -> "2018–2024" in the reader's digits. */
function testPeriod(split: string, fmt: Formatter): string {
  const years = /(\d{4})\D+(\d{4})/.exec(split);
  return years ? `${fmt.year(Number(years[1]))}–${fmt.year(Number(years[2]))}` : split;
}

export function Dashboard({ lang }: { lang: Lang }) {
  const data = loadForecast();
  const t = dictionaries[lang];
  const fmt = makeFormatter(lang);
  const summary = summarise(data.rows, data.forecast.total_erosion_ha);
  const { forecast, accuracy } = data;

  // Shoreline error is quoted to the nearest 10 m: "about 760 m", not 759.6.
  const errorMetres = fmt.int(roughly(accuracy.mde_m_at_horizon, 10));
  const bands = data.assumptions.osm_mapping_bands;
  const referenceMonth = fmt.month(forecast.reference_months[0]);

  return (
    <>
      <a
        href="#table"
        className="sr-only rounded-md bg-surface-raised px-4 py-2 text-accent-ink focus:not-sr-only focus:absolute focus:top-3 focus:left-3 focus:z-20"
      >
        {t.skipToTable}
      </a>

      <header className="border-b border-rule">
        <div className="mx-auto flex max-w-6xl flex-wrap items-start justify-between gap-x-6 gap-y-3 px-4 pt-6 pb-5 sm:px-6">
          <div className="min-w-0">
            <p className="text-sm text-ink-2">{t.project}</p>
            <h1 className="mt-1 text-2xl font-semibold text-balance sm:text-3xl">{t.heading}</h1>
            <p className="mt-2 text-ink-2">{t.subtitle(fmt.month(forecast.month), referenceMonth)}</p>
          </div>
          <a
            href={withBase(t.switchLanguage.href)}
            lang={t.switchLanguage.lang}
            hrefLang={t.switchLanguage.lang}
            className="inline-flex min-h-10 items-center rounded-md border border-rule px-3 text-sm font-medium text-accent-ink hover:bg-surface-sunken"
          >
            {t.switchLanguage.label}
          </a>
        </div>
      </header>

      <main className="mx-auto max-w-6xl px-4 pb-16 sm:px-6">
        <Banner lang={lang} errorMetres={errorMetres} summary={summary} />

        <section aria-labelledby="stats-heading" className="mt-8">
          <h2 id="stats-heading" className="sr-only">
            {t.statsHeading}
          </h2>
          <dl className="grid grid-cols-1 gap-3 min-[26rem]:grid-cols-2 lg:grid-cols-4">
            <Stat label={t.statUnions} value={fmt.int(summary.unions)} />
            <Stat
              label={t.statErosion}
              value={fmt.int(summary.erosionHa)}
              unit={t.hectaresShort}
              note={t.statErosionNote(fmt.int(forecast.total_erosion_ha))}
            />
            <Stat
              label={t.statAccretion}
              value={fmt.int(summary.accretionHa)}
              unit={t.hectaresShort}
              note={t.statAccretionNote}
            />
            <Stat
              label={t.statHouseholds}
              value={fmt.int(summary.households)}
              note={t.statHouseholdsNote(fmt.int(summary.mappedUnions))}
            />
          </dl>
        </section>

        {/* One row of filters above everything it scopes: map and table. */}
        <div className="mt-10">
          <Filters lang={lang} districts={districtOptions(data.rows, lang)} />
        </div>

        <MapSection
          lang={lang}
          rows={data.rows}
          month={forecast.month}
          zonesUrl={withBase(`/data/${data.map.file}`)}
          bbox={data.map.bbox}
        />

        <section id="table" className="mt-10 scroll-mt-4">
          <UnionTable
            lang={lang}
            rows={data.rows}
            month={forecast.month}
            downloadHref={withBase(`/data/${data.source.download}`)}
            downloadName={data.source.download}
            bands={bands}
          />
        </section>

        <section aria-labelledby="method-heading" className="mt-12 max-w-3xl">
          <h2 id="method-heading" className="text-xl font-semibold">
            {t.methodHeading}
          </h2>
          <dl className="mt-4 grid grid-cols-1 gap-x-6 gap-y-3 sm:grid-cols-[10rem_1fr]">
            <MethodItem term={t.methodForecast}>
              {t.methodForecastValue(
                fmt.month(forecast.month),
                fmt.int(forecast.horizon_months),
                fmt.month(forecast.anchor_months[0]),
              )}
            </MethodItem>
            <MethodItem term={t.methodReference}>{t.methodReferenceValue(referenceMonth)}</MethodItem>
            <MethodItem term={t.methodModel}>
              {t.methodModelValue(
                MODEL_NAMES[forecast.model] ?? forecast.model,
                fmt.int(forecast.horizon_months),
                fmt.fixed2(forecast.water_threshold),
              )}
            </MethodItem>
            <MethodItem term={t.methodAccuracy}>
              {t.methodAccuracyValue(
                errorMetres,
                fmt.int(forecast.horizon_months),
                testPeriod(accuracy.split, fmt),
                fmt.int(accuracy.n_windows),
              )}
            </MethodItem>
            <MethodItem term={t.methodTotals}>
              {t.methodTotalsValue(fmt.int(forecast.total_erosion_ha), fmt.percent(summary.insideShare))}
            </MethodItem>
            <MethodItem term={t.methodHouseholds}>
              {t.methodHouseholdsValue(fmt.decimal(data.assumptions.persons_per_household))}
            </MethodItem>
            <MethodItem term={t.methodMapping}>
              {t.methodMappingValue(
                fmt.int(bands.low_below),
                fmt.int(bands.high_from),
                fmt.decimal(bands.min_area_km2),
              )}
            </MethodItem>
            <MethodItem term={t.methodNames}>
              {t.methodNamesValue(fmt.int(summary.namedUnions), fmt.int(summary.unions))}
            </MethodItem>
            <MethodItem term={t.methodData}>{t.methodDataValue}</MethodItem>
          </dl>
          <p className="mt-5 border-l-4 border-rule pl-4 text-ink-2">{t.methodCaveat}</p>
        </section>
      </main>

      <footer className="border-t border-rule">
        <div className="mx-auto max-w-6xl space-y-1 px-4 py-6 text-sm text-ink-muted sm:px-6">
          <p className="break-words">{t.footerSource(data.source.file, data.source.sha256.slice(0, 12))}</p>
          <p>
            <a
              href="https://www.openstreetmap.org/copyright"
              className="underline underline-offset-4 hover:text-ink"
            >
              {t.attributionOsm}
            </a>
            {" · "}
            {t.attributionRest}
          </p>
          <p>{t.footerProject}</p>
        </div>
      </footer>
    </>
  );
}

function Banner({ lang, errorMetres, summary }: { lang: Lang; errorMetres: string; summary: Summary }) {
  const t = dictionaries[lang];
  const fmt = makeFormatter(lang);
  return (
    <section
      aria-labelledby="banner-title"
      className="mt-6 rounded-lg border border-rule border-l-4 border-l-warn bg-surface-raised p-4 sm:p-5"
    >
      <h2 id="banner-title" className="flex items-center gap-2 font-semibold">
        {/* Status colour on the icon only; the title says what it means. */}
        <svg aria-hidden="true" viewBox="0 0 20 20" className="size-5 shrink-0 fill-warn">
          <path
            fillRule="evenodd"
            d="M10 1.5 19 18H1L10 1.5Zm-.9 5.6.2 6h1.4l.2-6H9.1Zm.9 7.4a1 1 0 1 0 0 2 1 1 0 0 0 0-2Z"
          />
        </svg>
        {t.bannerTitle}
      </h2>
      <ul className="mt-2 list-disc space-y-1 pl-7 text-ink-2 marker:text-ink-muted">
        <li>{t.bannerRank}</li>
        <li>
          {t.bannerUnmapped(
            fmt.int(summary.unmappedUnions),
            fmt.int(summary.erodingUnions),
            fmt.int(summary.unmappedLowMapping),
          )}
        </li>
        <li>{t.bannerAccuracy(errorMetres)}</li>
        <li>{t.bannerNotValidated}</li>
      </ul>
    </section>
  );
}

function Stat({ label, value, unit, note }: { label: string; value: string; unit?: string; note?: string }) {
  return (
    <div className="rounded-lg border border-rule bg-surface-raised p-4">
      <dt className="text-sm text-ink-2">{label}</dt>
      <dd className="mt-1">
        <span className="text-3xl font-semibold">{value}</span>
        {unit && <span className="ml-1 text-ink-2">{unit}</span>}
        {note && <span className="mt-1 block text-xs text-ink-muted">{note}</span>}
      </dd>
    </div>
  );
}

function MethodItem({ term, children }: { term: string; children: React.ReactNode }) {
  return (
    <>
      <dt className="font-medium text-ink-2">{term}</dt>
      <dd>{children}</dd>
    </>
  );
}
