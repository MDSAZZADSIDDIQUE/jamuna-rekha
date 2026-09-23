"use client";

import dynamic from "next/dynamic";
import { useEffect, useMemo, useRef, useState } from "react";

import { makeFormatter } from "@/lib/format";
import { dictionaries } from "@/lib/i18n";
import type { Lang, UnionRow } from "@/lib/types";
import type { Bounds } from "@/lib/zones";

// Leaflet and the zones are fetched only when the map comes near the screen,
// so a reader who only wants the table never downloads them.
const ZoneMap = dynamic(() => import("./ZoneMap"), { ssr: false });

interface Props {
  lang: Lang;
  rows: UnionRow[];
  month: string;
  zonesUrl: string;
  bbox: Bounds;
}

export function MapSection({ lang, rows, month, zonesUrl, bbox }: Props) {
  const t = dictionaries[lang];
  const fmt = useMemo(() => makeFormatter(lang), [lang]);
  const box = useRef<HTMLDivElement>(null);
  const [near, setNear] = useState(false);

  useEffect(() => {
    const element = box.current;
    if (!element) return;
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries.some((entry) => entry.isIntersecting)) {
          setNear(true);
          observer.disconnect();
        }
      },
      { rootMargin: "300px" },
    );
    observer.observe(element);
    return () => observer.disconnect();
  }, []);

  return (
    <section aria-labelledby="map-heading" className="mt-8">
      <h2 id="map-heading" className="text-xl font-semibold">
        {t.mapHeading}
      </h2>
      <p className="mt-1 max-w-3xl text-sm text-ink-2">{t.mapIntro(fmt.month(month))}</p>

      {/* The legend mirrors the marks: filled areas with their own edge. */}
      <ul className="mt-3 flex flex-wrap gap-x-5 gap-y-1 text-sm text-ink-2">
        <li className="flex items-center gap-2">
          <span aria-hidden="true" className="inline-block size-3.5 rounded-sm border border-erosion bg-erosion/50" />
          {t.legendErosion}
        </li>
        <li className="flex items-center gap-2">
          <span aria-hidden="true" className="inline-block size-3.5 rounded-sm border border-accretion bg-accretion/50" />
          {t.legendAccretion}
        </li>
        <li className="flex items-center gap-2">
          <span aria-hidden="true" className="inline-block size-3.5 rounded-sm border border-erosion/25 bg-erosion/10" />
          {t.legendFaded}
        </li>
      </ul>

      {/* Fixed height, so nothing below moves when the map arrives. On a phone
          it stays near half the screen, leaving room for a finger to scroll
          the page past it instead of panning the map. */}
      <div
        ref={box}
        className="relative mt-3 h-[max(20rem,52vh)] overflow-hidden rounded-lg border border-rule bg-surface-sunken sm:h-[min(75vh,44rem)]"
      >
        {near ? (
          <ZoneMap lang={lang} rows={rows} zonesUrl={zonesUrl} bbox={bbox} />
        ) : (
          <p className="flex h-full items-center justify-center p-4 text-sm text-ink-2">{t.mapLoading}</p>
        )}
      </div>
    </section>
  );
}
