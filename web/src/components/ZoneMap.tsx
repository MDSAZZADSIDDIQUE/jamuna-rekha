"use client";

// Loaded only in the browser, and only when the map scrolls near the view
// (see MapSection): Leaflet touches `window` as soon as it is imported.

import "leaflet/dist/leaflet.css";

import * as L from "leaflet";
import { useEffect, useMemo, useRef, useState } from "react";

import { makeFormatter, type Formatter } from "@/lib/format";
import { dictionaries, type Dictionary } from "@/lib/i18n";
import type { Lang, UnionRow } from "@/lib/types";
import { useTableState } from "@/lib/urlState";
import {
  boundsOf,
  unionsInView,
  zoneCard,
  zoneInView,
  type Bounds,
  type ZoneCollection,
  type ZoneFeature,
  type ZoneProperties,
} from "@/lib/zones";

// OpenStreetMap's own tiles: free for light use like this, with the credit
// shown on the map. A site with heavy traffic should switch to a tile service.
const TILES = "https://tile.openstreetmap.org/{z}/{x}/{y}.png";
const TILE_CREDIT =
  '© <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors';

interface Props {
  lang: Lang;
  rows: UnionRow[];
  zonesUrl: string;
  bbox: Bounds;
}

interface Colours {
  erosion: string;
  accretion: string;
}

const toLatLng = ([west, south, east, north]: Bounds): L.LatLngBoundsExpression => [
  [south, west],
  [north, east],
];

/** The zone colours are the page's CSS tokens, so they follow light/dark mode. */
function readColours(element: HTMLElement): Colours {
  const css = getComputedStyle(element);
  return {
    erosion: css.getPropertyValue("--erosion").trim(),
    accretion: css.getPropertyValue("--accretion").trim(),
  };
}

function styleFor(zone: ZoneProperties, inView: Set<string> | null, colours: Colours, hovered = false): L.PathOptions {
  const colour = zone.k === "e" ? colours.erosion : colours.accretion;
  const shown = zoneInView(zone, inView);
  return {
    color: colour,
    fillColor: colour,
    weight: hovered ? 2.5 : 1,
    opacity: shown ? 0.9 : 0.25,
    fillOpacity: hovered ? 0.8 : shown ? 0.5 : 0.1,
    // A faded zone is context, not a target: the zones in view win the pointer.
    interactive: shown,
  };
}

/** The card, built with text nodes: place names are data, never markup. */
function cardElement(zone: ZoneProperties, row: UnionRow | undefined, lang: Lang, t: Dictionary, fmt: Formatter, colours: Colours) {
  const text = zoneCard(zone, row, lang, t, fmt);
  const root = document.createElement("div");
  root.className = "jr-zone-card";
  const line = (content: string, className: string) => {
    const element = document.createElement("div");
    element.className = className;
    element.textContent = content;
    root.append(element);
    return element;
  };
  line(text.value, "text-base font-semibold");
  const kind = line("", "flex items-center gap-2 text-sm");
  const key = document.createElement("span");
  key.setAttribute("aria-hidden", "true");
  key.style.cssText = `display:inline-block;width:14px;border-top:2px solid ${zone.k === "e" ? colours.erosion : colours.accretion}`;
  const kindLabel = document.createElement("span");
  kindLabel.textContent = text.kind;
  kind.append(key, kindLabel);
  line(text.place, "mt-1 text-sm font-medium");
  if (text.location) line(text.location, "text-xs text-ink-2");
  if (text.totals) line(text.totals, "mt-1 text-xs text-ink-2");
  return root;
}

export default function ZoneMap({ lang, rows, zonesUrl, bbox }: Props) {
  const t = dictionaries[lang];
  const fmt = useMemo(() => makeFormatter(lang), [lang]);
  const { district, query, minErosion } = useTableState();
  const inView = useMemo(() => unionsInView(rows, { district, query, minErosion }), [rows, district, query, minErosion]);
  const rowsByGid = useMemo(() => new Map(rows.map((row) => [row.gid_union, row])), [rows]);

  const container = useRef<HTMLDivElement>(null);
  const mapRef = useRef<L.Map | null>(null);
  const layerRef = useRef<L.GeoJSON | null>(null);
  const zonesRef = useRef<ZoneFeature[]>([]);
  const inViewRef = useRef(inView);
  const [status, setStatus] = useState<"loading" | "ready" | "failed">("loading");
  const [scheme, setScheme] = useState(0);

  // Hover and click read these through refs, so the layer is built only once.
  useEffect(() => {
    inViewRef.current = inView;
  }, [inView]);

  useEffect(() => {
    const element = container.current;
    if (!element) return;
    // Canvas draws thousands of zones faster than SVG. A zone traced from one
    // 120 m pixel is a few screen pixels wide; the tolerance widens its hit
    // area a little beyond its edge, but not so far that a neighbour wins.
    const map = L.map(element, {
      attributionControl: false,
      zoomSnap: 0.5,
      renderer: L.canvas({ tolerance: 3 }),
    });
    L.control.attribution({ prefix: false }).addTo(map);
    L.tileLayer(TILES, { maxZoom: 18, attribution: TILE_CREDIT }).addTo(map);
    map.fitBounds(toLatLng(bbox));
    mapRef.current = map;

    const tip = L.tooltip({ direction: "top", offset: [0, -12], opacity: 1 });
    // Above the pointer, unless that would push the card out of the map.
    const placeTip = (latlng: L.LatLng) => {
      const below = map.latLngToContainerPoint(latlng).y < 170;
      tip.options.direction = below ? "bottom" : "top";
      tip.options.offset = L.point(0, below ? 12 : -12);
      tip.setLatLng(latlng);
    };
    let hovered: L.Path | null = null;
    let cancelled = false;

    const colours = () => readColours(element);
    const card = (zone: ZoneProperties) => cardElement(zone, zone.u ? rowsByGid.get(zone.u) : undefined, lang, t, fmt, colours());

    fetch(zonesUrl)
      .then((response) => (response.ok ? response.json() : Promise.reject(new Error(String(response.status)))))
      .then((data: ZoneCollection) => {
        if (cancelled) return;
        zonesRef.current = data.features;
        const layer = L.geoJSON(data as unknown as GeoJSON.FeatureCollection, {
          style: (feature) => styleFor((feature as unknown as ZoneFeature).properties, inViewRef.current, colours()),
        });
        layer.on("mouseover", (event: L.LeafletMouseEvent) => {
          const path = event.propagatedFrom as L.Path & { feature: ZoneFeature };
          if (hovered && hovered !== path) layer.resetStyle(hovered);
          hovered = path;
          path.setStyle(styleFor(path.feature.properties, inViewRef.current, colours(), true));
          tip.setContent(card(path.feature.properties));
          placeTip(event.latlng);
          tip.addTo(map);
        });
        layer.on("mousemove", (event: L.LeafletMouseEvent) => placeTip(event.latlng));
        layer.on("mouseout", () => {
          if (hovered) layer.resetStyle(hovered);
          hovered = null;
          tip.remove();
        });
        // A tap has no hover: the same card opens as a popup.
        layer.on("click", (event: L.LeafletMouseEvent) => {
          const path = event.propagatedFrom as L.Path & { feature: ZoneFeature };
          tip.remove();
          L.popup({ closeButton: true, autoPanPadding: [16, 16] })
            .setLatLng(event.latlng)
            .setContent(card(path.feature.properties))
            .openOn(map);
        });
        layer.addTo(map);
        layerRef.current = layer;
        setStatus("ready");
      })
      .catch(() => {
        if (!cancelled) setStatus("failed");
      });

    // The zone colours follow the reader's light/dark setting.
    const media = window.matchMedia("(prefers-color-scheme: dark)");
    const onScheme = () => setScheme((n) => n + 1);
    media.addEventListener("change", onScheme);

    return () => {
      cancelled = true;
      media.removeEventListener("change", onScheme);
      map.remove();
      mapRef.current = null;
      layerRef.current = null;
    };
  }, [zonesUrl, bbox, rowsByGid, lang, t, fmt]);

  // Restyle when the filters or the colour scheme change: zones outside the
  // current view fade, rather than vanish, so the reader keeps the river.
  useEffect(() => {
    const layer = layerRef.current;
    const element = container.current;
    if (!layer || !element || status !== "ready") return;
    const colours = readColours(element);
    layer.setStyle((feature) => styleFor((feature as unknown as ZoneFeature).properties, inView, colours));
  }, [inView, scheme, status]);

  // Move to the filtered zones; back to the whole reach when filters clear.
  // Waits a moment so typing in the search box does not jerk the map about.
  useEffect(() => {
    const map = mapRef.current;
    if (!map || status !== "ready") return;
    const timer = window.setTimeout(() => {
      const target = inView === null ? bbox : boundsOf(zonesRef.current, (zone) => zoneInView(zone, inView));
      if (target) map.flyToBounds(toLatLng(target), { padding: [24, 24], maxZoom: 12, duration: 0.6 });
    }, 350);
    return () => window.clearTimeout(timer);
  }, [inView, bbox, status]);

  return (
    <>
      <div ref={container} className="jr-map absolute inset-0" aria-label={t.mapLabel} />
      {status !== "ready" && (
        <div className="pointer-events-none absolute inset-0 z-[1000] flex items-center justify-center p-4">
          <p className="rounded-md bg-surface-raised px-3 py-2 text-sm text-ink-2 shadow-sm">
            {status === "loading" ? t.mapLoading : t.mapFailed}
          </p>
        </div>
      )}
    </>
  );
}
