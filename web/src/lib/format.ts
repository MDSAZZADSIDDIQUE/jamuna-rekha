import type { Lang } from "./types";

/**
 * bn-BD gives Bengali digits and South Asian digit grouping (১,২৩,৪৫৬), which
 * is what a Bangladeshi reader expects. en-GB rather than en-US keeps month
 * names and grouping unambiguous for an international reader.
 */
const LOCALES: Record<Lang, string> = { bn: "bn-BD", en: "en-GB" };

export interface Formatter {
  locale: string;
  /** Whole number: counts, totals. */
  int: (n: number) => string;
  /**
   * Hectares in a table cell: whole numbers, but "<1" for an area that is
   * real yet rounds to 0. One 120 m pixel is 1.44 ha, so decimals would be
   * false precision; a bare 0 beside a non-zero area would be wrong.
   */
  hectares: (n: number) => string;
  /** Whole number with an explicit sign, for net change. */
  signed: (n: number) => string;
  /** Up to one decimal: 4.5 persons per household. */
  decimal: (n: number) => string;
  /**
   * Buildings per km²: one decimal below 10 (0.4, 2.5), whole numbers above,
   * and "<0.1" for a density that is real but rounds to 0 — a union with one
   * mapped building in 60 km² is not the same as one with none.
   */
  density: (n: number) => string;
  /** Two decimals, for probabilities such as the water threshold. */
  fixed2: (n: number) => string;
  /** A year, without digit grouping: 2024, not 2,024. */
  year: (n: number) => string;
  /** 0.64 -> "64%" */
  percent: (fraction: number) => string;
  /** "2025-03" -> "March 2025" / "মার্চ ২০২৫" */
  month: (key: string) => string;
}

export function makeFormatter(lang: Lang): Formatter {
  const locale = LOCALES[lang];
  const whole = new Intl.NumberFormat(locale, { maximumFractionDigits: 0 });
  const signed = new Intl.NumberFormat(locale, {
    maximumFractionDigits: 0,
    signDisplay: "exceptZero",
  });
  const decimal = new Intl.NumberFormat(locale, { maximumFractionDigits: 1 });
  const year = new Intl.NumberFormat(locale, { useGrouping: false });
  const fixed2 = new Intl.NumberFormat(locale, {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
  const percent = new Intl.NumberFormat(locale, { style: "percent", maximumFractionDigits: 0 });
  // UTC on both sides: a month key has no time zone, and formatting it in the
  // reader's local zone can roll "2025-03-01" back into February.
  const month = new Intl.DateTimeFormat(locale, {
    month: "long",
    year: "numeric",
    timeZone: "UTC",
  });

  return {
    locale,
    // `+ 0` turns -0 into 0, so a value that rounds to nothing prints as 0.
    int: (n) => whole.format(Math.round(n) + 0),
    hectares: (n) => (n > 0 && n < 0.5 ? `<${whole.format(1)}` : whole.format(Math.round(n) + 0)),
    signed: (n) => signed.format(Math.round(n) + 0),
    decimal: (n) => decimal.format(n),
    density: (n) =>
      n > 0 && n < 0.05
        ? `<${decimal.format(0.1)}`
        : n < 10 ? decimal.format(n) : whole.format(Math.round(n)),
    fixed2: (n) => fixed2.format(n),
    year: (n) => year.format(n),
    percent: (fraction) => percent.format(fraction),
    month: (key) => {
      const [y, m] = key.split("-").map(Number);
      return month.format(new Date(Date.UTC(y, m - 1, 1)));
    },
  };
}

/** Round to the nearest `step` — "about 760 m", not "759.6 m". */
export function roughly(n: number, step: number): number {
  return Math.round(n / step) * step;
}
