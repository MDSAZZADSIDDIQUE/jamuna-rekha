# CLAUDE.md — যমুনারেখা (JamunaRekha)

Orientation file for Claude Code. Read this first in every session.

---

## 1. What this project is

**যমুনারেখা / JamunaRekha** is a neural forecasting system that predicts the
**position of the Jamuna River shoreline 3 months ahead**, so that *char*
dwellers in Bangladesh get early warning before their land erodes.

- **Funder / context:** Bangla Academy research grant, **May–July 2026**.
- **Final deliverable:** a **research paper written in Bengali**, plus a
  working dashboard handed to the Department of Disaster Management (DDM).
- **Success is social, not just metric-driven.** A model that scores well but
  cannot name *which unions lose how many households* has not done the job.

### Study area
Jamuna River, bounding box **24.5–26.5 °N, 89.4–89.9 °E**, years **1972–2024**.

---

## 2. Pipeline architecture (5 stages)

The project is built and run **one stage at a time**. Each stage writes files
that the next stage reads — no stage reaches into another's internals.

```
[1] GEE  ──►  data/raw/        GeoTIFF, 512×512, monthly MNDWI water masks
[2] prep ──►  data/processed/  gap-filled tensor + JamunaShift-52Y Dataset
[3] model──►  outputs/checkpoints/, outputs/predictions/
[4] risk ──►  outputs/tables/  at-risk household counts per union parishad
[5] dash ──►  Streamlit app reading outputs/
```

### Stage 1 — Data acquisition (Google Earth Engine, in the browser)
- Landsat **1 / 5 / 7 / 8 / 9**, 1972–2024.
- **Per-sensor band mapping** — the band names differ per mission and this is
  the single most common source of silent bugs. MSS (Landsat 1) has *no* SWIR,
  so its water index must be handled separately from the TM/ETM+/OLI path.
- Water index: **MNDWI = (Green − SWIR1) / (Green + SWIR1)**.
- Cloud mask → **Otsu threshold** → **monthly median composites**.
- Export **512×512 GeoTIFFs** to `data/raw/`.
- GEE JavaScript lives in `gee/` and is version-controlled even though it runs
  in the Code Editor, not locally.

### Stage 2 — Preprocessing (`rasterio`, `numpy`, `geopandas`)
- Fill cloud-gap months by **linear temporal interpolation**.
- Resample **Landsat-1's 60 m → 30 m** to match the rest of the archive.
- Stack into a time-series tensor.
- Package as a PyTorch `Dataset` named **`JamunaShift-52Y`**.

### Stage 3 — Model (PyTorch Lightning)
- **TimeSformer adapted for raster-sequence prediction**: classification head
  replaced with a **pixel-wise CNN decoder** emitting 512×512 sigmoid masks.
- **Input 12 monthly frames → predict next 3.**
- **Loss = BCE + 0.3 × spatial_gradient_loss** (Sobel-based; keeps bank edges
  sharp — plain BCE blurs the bank, which is exactly the signal we need).
- **Baselines with identical interfaces:** `ConvLSTM`, `persistence`.
  Same `forward()` signature, same LightningModule contract, so the eval
  harness never special-cases a model.
- **Metrics:** IoU, F1 on **bank pixels** (not all pixels — the class balance
  is brutal), and **Mean Displacement Error in metres**.

### Stage 4 — Risk overlay (`geopandas`, Overpass API)
- Vectorize predicted erosion zones → polygons.
- Pull **OSM building footprints** via Overpass.
- Spatial join: count buildings inside each erosion polygon.
- Aggregate to **union parishad** level using **GADM** boundaries.
- Export CSV to `outputs/tables/`.

### Stage 5 — Dashboard (Streamlit + Folium)
- Erosion risk map, colour-coded by severity.
- Sortable at-risk household table, filterable by district.
- **CSV download for the DDM** — this is the handoff artifact.

---

## 3. Stack & constraints

| Item | Value |
|---|---|
| Python | **3.11** (hard requirement) |
| DL | PyTorch + PyTorch Lightning |
| Geo | rasterio, geopandas, shapely, pyproj |
| Dashboard | Streamlit + Folium |
| Config | YAML in `configs/`, loaded with OmegaConf |
| Local dev | **256×256 crops, few epochs, CPU/small GPU** |
| Full training | rented **A100 on Runpod** |
| **GPU budget** | **~30 A100-hours total. This is the binding constraint.** |

### What the GPU budget means in practice
The training loop must be **clean before it ever touches the cloud**. Every
run on Runpod is money. Therefore:

- Every module gets **smoke-tested locally on tiny crops first** — shape
  assertions, one forward pass, one backward pass, a 2-epoch overfit-on-one-batch
  sanity check.
- **Overfit a single batch to ~zero loss** before any full run. If the model
  cannot memorise one batch, it will not learn 52 years of river.
- Checkpoint **every epoch** and make runs **resumable**. A crashed
  un-resumable run is burnt budget.
- Log wall-clock seconds/epoch locally so A100 time can be **estimated before
  booking**, not discovered after.
- No speculative architecture search on the cloud. Ablations are planned on
  paper, run once.

---

## 4. Conventions

### Working agreement
- **Build one module at a time.** The user runs and verifies each piece before
  we move to the next. Do not scaffold ahead into the next stage.
- Do not silently widen scope. If a stage needs something the plan didn't
  mention, say so and let the user decide.
- Prefer small, runnable scripts with a `if __name__ == "__main__"` entry
  point over notebook-only code. Notebooks are for *looking*, `src/` is for
  *running*.

### Code
- Package root: `src/jamunarekha/`, imported as `jamunarekha.*`.
- Type-hint public functions. Docstrings state units and CRS.
- **Always be explicit about CRS and resolution.** Geospatial bugs are silent.
  State whether a function expects EPSG:4326 (degrees) or a metric CRS
  (**EPSG:32645 / UTM 45N** for the Jamuna) — Mean Displacement Error in
  *metres* is meaningless in a degree CRS.
- Rasters are indexed `(time, band, row, col)`. Say so in docstrings.
- No hard-coded paths. Paths come from `configs/*.yaml`.
- Randomness: seed everything, record the seed in the run config.

### Data hygiene
- `data/` and `outputs/checkpoints/` are **git-ignored**. Never commit imagery
  or weights.
- `data/raw/` is **immutable** — nothing writes back into it.
- `data/interim/` is scratch; `data/processed/` is what the Dataset reads.

### Research notes
- **`docs/NOTES.md` is a running log of design decisions and results**, kept
  in a form the user can lift directly into the Bengali paper.
- Append to it whenever we make a real choice (why 0.3 for the gradient loss
  weight, why this cloud mask, what a metric came out as). Include dates and
  numbers. This is a deliverable, not housekeeping.
- Bengali technical terms should be introduced alongside English on first use,
  since the paper is Bengali but the literature is English.

---

## 5. Repo layout

```
CLAUDE.md            this file
README.md            English + Bengali
requirements.txt     pinned
configs/             YAML run configs
gee/                 Earth Engine JavaScript (runs in browser Code Editor)
src/jamunarekha/
  data/              GEE ingest, preprocessing, JamunaShift-52Y Dataset
  models/            TimeSformer variant, ConvLSTM, persistence, losses
  risk/              vectorization, Overpass, GADM aggregation
  dashboard/         Streamlit app
  utils/             geo helpers, seeding, logging
notebooks/           exploration only
scripts/             stage runners, figures, manuscript build, sync_web_data.py
tests/               pytest
web/                 Next.js static site for the DDM (reads web/public/data/)
data/raw|interim|processed/    git-ignored
outputs/checkpoints|figures|predictions|logs|tables/   mostly git-ignored
docs/NOTES.md        running research log → feeds the Bengali paper
```

---

## 6. Current status

**All five stages implemented and run end to end on real data.**

- **Stage 1 — done.** 2,544 tile-month composites (4 tiles × 636 months,
  1972–2024), 701 MB, from **4,107 unique Landsat scenes**. Acquisition runs
  against the Microsoft Planetary Computer STAC rather than the GEE Code
  Editor — same USGS Collection 2 product, no interactive auth, fully
  scriptable and resumable. `gee/01_mndwi_export.js` reproduces the identical
  logic in Earth Engine for anyone who prefers it.
- **Stage 2 — done.** `JamunaShift-52Y` built for all four tiles. Observed
  fraction 0.536 rises to 0.799 after capped temporal interpolation; mean
  water fraction 0.114.
- **Stage 3 — done.** TimeSformer + pixel decoder, ConvLSTM and persistence,
  all on one LightningModule contract. Trained locally on CPU — **this machine
  has no CUDA device** — at 128 px crops.
- **Stage 4 — done.** Erosion/accretion vectorised, OSM buildings via Overpass,
  aggregated to union parishad on GADM 4.1 boundaries. The table also carries
  each union's OSM mapping density (buildings per km² over the queried area;
  low / medium / high) and Bengali names for every level, matched from a
  National Portal compilation and checked against each unit's official portal
  page (`risk/names_bn.py`; the match record for review is
  `outputs/tables/bn_names_<month>.csv`). The run summary records how many
  Overpass cells answered, so an incomplete building cache is visible.
- **Stage 5 — done.** Bilingual Streamlit dashboard with CSV export for DDM.
  **Web version live at https://jamunarekha.vercel.app** — `web/` is a
  Next.js 16 static export (Bengali at `/`, English at `/en/`), with a Leaflet
  map of the forecast zones (live since 2026-09-22).
  `scripts/sync_web_data.py` copies Stage 4 results into `web/public/data/`;
  the site computes nothing. In `web/`: `npm run build` (writes `web/out/`),
  `npm run lint`, `npm test`. Hosted as Vercel project `jamunarekha` in the
  user's personal scope (`mdsazzadsiddiques-projects`), deployed from `web/`
  with `vercel deploy --prod`. Git auto-deploy is deliberately **not**
  connected: a push does not publish. Each deploy needs the user's go-ahead.
- **Paper — drafted** in `docs/paper/`, assembled into .docx by
  `scripts/build_manuscript.py` with the Bangla Academy typography.

Run the environment with the conda env `jamunarekha` (Python 3.11). On Windows
it needs no `conda activate`: a `sitecustomize.py` in the env registers the
DLL directories, without which numpy's BLAS fails to load and the process dies
with no traceback.

See `docs/NOTES.md` for the decision log, including several silent bugs the
tests caught — tile edges being scored as shoreline, Otsu splitting a unimodal
histogram, and server-side cloud filtering quietly deleting MSS scenes.
