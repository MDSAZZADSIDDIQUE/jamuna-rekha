# যমুনারেখা · JamunaRekha — DDM website

The Stage 5 hand-off for the Department of Disaster Management, as a static
website: the union-parishad erosion forecast, a map of the predicted erosion
and accretion zones, a filterable and sortable table, and the CSV download.
Bengali at `/`, English at `/en/`.

**The site computes nothing.** Every number on it is read, at build time, from
the pipeline's Stage 4 output, and the full CSV download is the pipeline's own
file, byte for byte. A malformed or mismatched data file fails the build
rather than publishing wrong numbers.

## Updating the data

From the repository root, after a Stage 4 run:

```bash
python scripts/sync_web_data.py            # latest month; or --month 2025-03
```

This validates `outputs/tables/at_risk_households_<month>.csv` and writes
`web/public/data/forecast.json`, a byte-identical copy of the CSV, and
`zones_<month>.geojson`, the map's zones compacted from Stage 4's
`outputs/predictions/change_zones_<month>.geojson`. Then rebuild the site.

## Commands

Run these in `web/`:

```bash
npm install
npm run dev        # local preview at http://localhost:3000
npm run build      # static site → out/
npm run lint
npm test           # Vitest: table rules, CSV fidelity, number formatting
```

`out/` can be served by any static file host. To serve it from a sub-path
(GitHub Pages serves a project at `/<repo>/`), build with the prefix:

```bash
NEXT_PUBLIC_BASE_PATH=/jamuna-rekha npm run build
```

## Deploying (Vercel)

The site is live at **https://jamunarekha.vercel.app**, hosted on Vercel as
the project `jamunarekha` (personal scope `mdsazzadsiddiques-projects`). The
project is deliberately not connected to the Git repository, so a push does
not publish anything. After syncing new data and checking the build locally,
from `web/`:

```bash
vercel deploy --prod
```

Vercel builds from the uploaded source (`next build`), so `public/data/` must
be synced before deploying; `.vercelignore` keeps local build output from
being uploaded. Production deployments are public.

## Rules the map follows

- **Red is erosion, blue is accretion**, everywhere on the page (the table's
  erosion bars too): the palette's diverging pair, validated for colour-blind
  readers in both light and dark mode.
- **One filter row scopes map and table.** Zones outside the current filters
  fade rather than vanish, and the map moves to the zones that are left.
- **Hover or tap a zone** for a card led by its area, then its union and that
  union's figures from the table. Place names are inserted as text, never HTML.
- **Loaded only when needed:** Leaflet and the zones file (about 0.5 MB compressed)
  are fetched when the map nears the screen, so the table stays fast.
- **Background tiles** are OpenStreetMap's, credited on the map; fine for light
  traffic. A site with heavy traffic should move to a tile service.

## Rules the table follows

- **Default order is predicted erosion in hectares, largest first.** Household
  counts follow OpenStreetMap coverage, which is far thinner in the southern
  districts, so ranking by them ranks mapping density rather than risk.
- **"Unknown", not zero.** Where erosion is predicted but no building is mapped
  inside the erosion zone, buildings show as "none mapped" and households and
  persons as "unknown". A union listed for accretion alone has no erosion zone,
  so its zero is real and shows as 0.
- **OSM mapping column**: mapped buildings per km² across the whole union
  (where the building query reached), banded low / medium / high. It says how
  far to trust the household count, and whether an empty erosion zone is more
  likely unsettled land (high) or an unmapped village (low).
- **Place names**: the Bengali page shows each union's Bengali name where
  Stage 4 matched one with confidence and checked it against the union's
  official portal page; otherwise GADM's English spelling. Never a guess.
- **Hectares are whole numbers**, with "<1" for a real area that would round
  to 0 (one 120 m pixel is 1.44 ha, so decimals would be false precision).
- **Filters and sort order live in the URL**, so a view can be sent to a
  colleague as a link.
- **A filtered CSV download** has the same columns, order, encoding (UTF-8 with
  a BOM, CRLF) and number formatting as the pipeline's file; it is exactly the
  matching lines of the original. `src/lib/table.test.ts` checks this against
  the real data.

## Layout

```
src/app/(bn)/        Bengali root layout (<html lang="bn">) and page, at /
src/app/(en)/en/     English page, at /en/ (its root layout is src/app/(en)/)
src/app/global-not-found.tsx   bilingual 404
src/components/      Dashboard (server-rendered); Filters, MapSection, ZoneMap
                     (Leaflet, browser-only) and UnionTable (interactive)
src/lib/data.ts      build-time loader and schema check for forecast.json
src/lib/table.ts     filtering, sorting, URL state, CSV — pure functions
src/lib/zones.ts     the map's rules: view, bounds, zone cards — pure functions
src/lib/urlState.ts  the one URL-backed view the filters, map and table share
src/lib/i18n.ts      all interface text, Bengali and English
src/lib/format.ts    numbers and months per language (Bengali digits for bn)
public/data/         written by scripts/sync_web_data.py; do not edit by hand
```

This is Next.js 16, whose APIs differ from older versions; its own docs are in
`node_modules/next/dist/docs/` (see `AGENTS.md`).
