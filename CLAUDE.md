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
tests/               pytest
data/raw|interim|processed/    git-ignored
outputs/checkpoints|figures|predictions|logs|tables/   mostly git-ignored
docs/NOTES.md        running research log → feeds the Bengali paper
```

---

## 6. Current status

Scaffolding only. **No pipeline code written yet.** Next step is Stage 1
(GEE acquisition script), and only after the user has confirmed this skeleton.
