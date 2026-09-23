# গবেষণা নোট / Research Notes — যমুনারেখা

Running log of design decisions, parameter choices, and results.
**This file feeds the Bengali paper.** Append; do not rewrite history.

Format for each entry:

```
## YYYY-MM-DD — <short title>
**Decision:** what we chose
**Alternatives considered:** what we rejected
**Rationale:** why (this is the sentence that ends up in the paper)
**Evidence / numbers:** metrics, timings, shapes
**Open question:** anything still unresolved
```

---

## 2026-08-29 — Project scaffolding
**Decision:** Repository skeleton created — `CLAUDE.md`, folder tree,
pinned `requirements.txt`, bilingual `README.md`, `.gitignore`.
**Rationale:** The ~30 A100-hour budget means the training loop must be
verified locally before any cloud run, so the repo is organised around
"small local crops first, cloud once".
**Evidence / numbers:** none yet — no pipeline code written.
**Open question:** Python 3.11 not yet installed on the dev machine.

---

## 2026-09-20 — Python 3.11 environment resolved
**Decision:** conda env `jamunarekha` on Python 3.11, geospatial stack from
conda-forge, PyTorch 2.4.1 (CPU) from PyPI.
**Alternatives considered:** system Python (absent); Anaconda base, which is
Python 3.14.6 and too new for the pinned stack.
**Rationale:** the `defaults` channel now prompts for Terms-of-Service
acceptance and stalls a scripted install; `--override-channels -c conda-forge`
avoids it entirely and gives better geospatial wheels.
**Evidence / numbers:** numpy 1.26.4, rasterio, geopandas, pyproj all import.
`torch.cuda.is_available()` is **False** — the development machine has **no
CUDA GPU** and 8 CPU cores. All local work is CPU-bound.
**Open question:** resolved — this was the open question from 2026-08-29.

---

## 2026-09-20 — Acquisition source: Planetary Computer instead of the GEE Code Editor
**Decision:** Stage 1 runs against the **Microsoft Planetary Computer STAC
API** from Python. `gee/01_mndwi_export.js` reproduces identical logic for the
Earth Engine Code Editor and stays version-controlled.
**Alternatives considered:** GEE Code Editor exports to Drive (the original
plan); the USGS M2M API; AWS `s3://usgs-landsat` (requester-pays).
**Rationale:** Planetary Computer serves the *same* USGS Collection 2 product,
needs no interactive Google sign-in, and can therefore be driven from a script
that is resumable, reviewable in git, and re-runnable by an examiner. GEE
exports would be thousands of manual browser tasks with no resume.
**Evidence / numbers:** `landsat-c2-l2` covers 1982-08-22 onward (TM / ETM+ /
OLI); `landsat-c2-l1` covers 1972-07-25 to 2013-01-07 (MSS). Together they span
the full 1972–2024 record.
**Open question:** none.

---

## 2026-09-20 — Canonical analysis grid
**Decision:** EPSG:32645 (UTM 45N), **120 m** square pixels, **512 × 512**
tiles, four tiles covering the study bounding box.
**Alternatives considered:** a single 512 × 512 raster over the whole bounding
box, which gives 434 m × 99 m *non-square* pixels and is fatal for a
displacement metric in metres; 30 m native resolution, which is 7 400 × 1 660 px
and roughly 16× the storage and network for a signal that moves tens to
hundreds of metres per year.
**Rationale:** CLAUDE.md §4 requires Mean Displacement Error in metres, which
requires square metric pixels. 120 m keeps the four tiles at exactly 512 × 512,
matching the model input size in CLAUDE.md §2.
**Evidence / numbers:** the study bounding box projects to **54.7 km × 222.6 km**.
Grid: T00_00 … T03_00, each 61.4 km × 61.4 km, covering 89.34–90.00 °E,
24.41–26.64 °N.
**Open question:** the tiles overshoot the bounding box by about 7 km eastward
because the lattice snaps outward. Harmless — it is floodplain — and it keeps
the grid deterministic across re-runs.

---

## 2026-09-20 — Deviation: no intermediate 60 m to 30 m resample
**Decision:** every sensor is warped **directly** onto the 120 m canonical grid.
**Rationale:** CLAUDE.md §2 says "Resample Landsat-1's 60 m → 30 m to match the
rest of the archive". Going 60 m → 30 m → 120 m passes through a pure upsample
that adds no information and costs 16× the storage. The harmonisation those
words ask for still happens — every mission lands on one shared grid — it just
happens in a single step.
**Evidence / numbers:** MSS reads use COG overview level 0 (60 → 120 m);
TM / ETM+ / OLI use level 1 (30 → 120 m).
**Open question:** none.

---

## 2026-09-20 — COG overview reads: 4–6× faster, no measurable loss
**Decision:** read the pre-built power-of-two overview whose resolution matches
the 120 m target, rather than the full-resolution band.
**Rationale:** a full 1972–2024 pull is on the order of 20 000 windowed asset
reads. Reading 30 m data and letting GDAL downsample costs roughly 4× the
network and CPU.
**Evidence / numbers:** on a March 2023 Landsat-8 scene warped to the tile grid,
full resolution took 1.3 s, `OVERVIEW_LEVEL=0` 0.4 s, `=1` 0.3 s, `=2` 0.2 s.
Mean green reflectance differs by **0.2 %** across levels. Critically,
`QA_PIXEL` overviews are built by **nearest neighbour**, so the bitmask
survives decimation: clear-pixel fraction 0.3748 at full resolution versus
0.3747 at level 1 — identical to four decimal places. The distinct QA values
remain the valid discrete Collection 2 codes (21824, 22280, 22018 and so on),
not averaged nonsense.
**Open question:** none.

---

## 2026-09-20 — Client-side cloud filtering (silent data loss, caught)
**Decision:** filter `eo:cloud_cover` **in Python**, not as a STAC `query`.
**Rationale:** some Landsat 1–3 MSS items carry no `eo:cloud_cover` property at
all. A server-side numeric filter drops them silently, deleting part of the
earliest decade — precisely the period this study exists to reconstruct. A
missing value is now treated as "keep, and let the per-pixel QA mask decide".
**Evidence / numbers:** tile T02_00, 1977: **30** MSS scenes unfiltered versus
**27** with the server-side filter. Small per year, but systematic and
concentrated in the sparsest era.
**Open question:** none.

---

## 2026-09-20 — MSS-era coverage is genuinely gappy (a finding, not a bug)
**Decision:** report the gaps rather than interpolate across them.
**Evidence / numbers:** MSS scenes over tile T02_00 by year — 1972: 10,
1973: 13, **1974: 0**, 1975: 43, 1976: 15, 1977: 30, 1978: 23, 1979: 14,
1980: 6, **1981: 0, 1982: 0, 1983: 0**. Total 1972–1983: **154**. Landsat-5 TM
only begins 1982-08, so there is a real gap of roughly three years (1981–1983)
in the Bangladesh record between the end of routine MSS acquisition and the
start of TM.
**Rationale:** `preprocess.max_gap_months = 6` refuses to bridge it. Linear
interpolation across three years would manufacture a river nobody measured.
**Open question:** the 1981–83 hole must be stated explicitly in the
limitations; windows spanning it are dropped from the dataset.

---

## 2026-09-20 — Deviation: Otsu threshold moved from Stage 1 to Stage 2
**Decision:** Stage 1 stores the **continuous** monthly median water index;
Stage 2 interpolates it in time and *then* applies a per-month Otsu threshold.
**Rationale:** CLAUDE.md §2 puts Otsu in Stage 1. But interpolating a *binary*
mask rounds the bank to whichever side happened to be observed, whereas
interpolating the continuous index lets a half-filled channel stay half-filled.
Thresholding last is what makes the gap-filling meaningful. It also lets a
poorly-covered month borrow a stable threshold from the tile instead of
inventing one from a handful of pixels.
**Evidence / numbers:** raw rasters store index × 10 000 as int16 plus a
per-pixel clear-observation count, about 0.46 MB per tile-month.
**Open question:** none.

---

## 2026-09-20 — Bug caught by test: tile edges were scored as shoreline
**Decision:** `binary_erosion(..., border_value=1)` in `bank_band` and
`boundary_pixels`.
**Rationale:** SciPy defaults to `border_value=0`, treating everything outside
the array as background. The water region therefore erodes away at the array
rim and the *entire tile border* is reported as bank. Those spurious boundary
pixels sit at identical positions in prediction and truth, so they pull every
measured distance towards zero.
**Evidence / numbers:** a straight bank displaced by 2 px at 120 m should score
**240 m**. With the default border handling it scored **79 m** — a threefold
understatement of Mean Displacement Error, in the flattering direction, with
nothing crashing and no warning. Now pinned by
`tests/test_geo_and_metrics.py::test_mde_equals_the_known_shift_in_metres`.
**Open question:** none, but this is the cautionary example for the methods
section on silent geospatial error.

---

## 2026-09-20 — Why the gradient term is 0.3, and what it actually buys
**Decision:** keep `loss = BCE + 0.3 × spatial_gradient_loss`.
**Rationale, now measured rather than asserted.** There are two ways to be
wrong about a shoreline: *blur* it (right place, smeared over six columns) or
*displace* it (perfectly sharp, two pixels off). For a forecast whose entire
job is to name where the bank will be, the displaced answer is the more useful
of the two — it commits to a position.
**Evidence / numbers**, on a 32 × 32 step-edge fixture:

| prediction | BCE | Sobel gradient loss |
|---|---|---|
| blurred bank | 0.133 | 0.129 |
| sharp, displaced 2 px | 0.863 | 0.124 |
| ratio (blur : displaced) | **0.15** | **1.04** |

BCE alone prefers hedging by **6.5×**. The gradient term is almost indifferent
between the two, so adding it removes the incentive to smear. This is the
quantitative justification for the 0.3 term, which previously existed only as a
claim. Pinned by
`tests/test_models.py::test_bce_alone_rewards_hedging_and_the_gradient_term_does_not`.
**Open question:** the value 0.3 itself is still inherited from the proposal
rather than swept. An ablation over {0, 0.1, 0.3, 0.6} is planned on paper and
run once.

---

## 2026-09-20 — Overfit-one-batch gate needed a real signal
**Decision:** the single-batch overfit test uses a **synthetic migrating river**
(`tests/synthetic.py`), not random noise.
**Rationale:** with independent random targets there is no function from input
to output to learn, so the test was measuring raw memorisation capacity and a
small model failed it for the wrong reason. A drifting sinuous channel has the
structure the real task has, so failing it now means something is genuinely
broken.
**Evidence / numbers:** both TimeSformer and ConvLSTM drive the loss below half
its initial value within 60 steps on a 64 × 64 batch. Full suite: 44 passed,
1 skipped.
**Open question:** none.

---

## 2026-09-20 — External data dependencies validated
**Decision:** all three third-party sources confirmed working before the paper
is allowed to depend on them.
**Evidence / numbers:**

- **Planetary Computer STAC** — 15 items for T02_00 in 2023-03, 14 usable,
  valid-pixel fraction 1.000 after compositing. 1977-02 returned 4 MSS scenes,
  also 1.000 after compositing, correctly routed through NDWI.
- **GADM 4.1 level 4** — 5 158 union parishads nationally; **354** intersect the
  study bounding box, across nine districts: Kurigram, Lalmonirhat, Rangpur,
  Gaibandha, Bogra, Sirajganj, Jamalpur, Sherpur and Tangail.
- **Overpass** — initially HTTP 406, because the default `python-requests`
  User-Agent is blocked; then HTTP 504 under load. Fixed with a project
  User-Agent and mirror-rotating retry. A probe over a 7.8 km box at Kazipur
  returned **4 904 building centroids in 7.9 s**, about 80 buildings per km².

**Open question:** OSM building coverage in char areas is the weakest link in
the household estimate. It is reported as a lower bound, never as an estimate.

---

## 2026-09-21 — Stage 1 complete: what the archive actually yielded
**Decision:** full acquisition finished; 1972-2024, four tiles, no gaps in the
tile-month grid.
**Evidence / numbers:** 2 544 tile-month composites written (4 tiles x 636
months), 701 MB. The manifest records **7 511 scene-tile contributions** from
**4 107 unique Landsat scenes**. By instrument: ETM+ 2 789, TM 2 381,
OLI 1 861, MSS 480. By decade:

| decade | MSS | TM | ETM+ | OLI |
|---|---|---|---|---|
| 1970s | 459 | 0 | 0 | 0 |
| 1980s | 21 | 238 | 0 | 0 |
| 1990s | 0 | 1 069 | 23 | 0 |
| 2000s | 0 | 876 | 1 030 | 0 |
| 2010s | 0 | 198 | 1 321 | 893 |
| 2020s | 0 | 0 | 415 | 968 |

The 1980s row is the thin one: MSS acquisition over Bangladesh had largely
stopped and Landsat-5 TM only began in August 1982.
**Open question:** none.

---

## 2026-09-21 — The Otsu failure, and the threshold rule that replaced it
**Decision:** replace per-month Otsu with
``threshold = land_mode(month) + delta(index family)``.
**Rationale:** Otsu assumes a bimodal histogram. In a dry-season month the
Jamuna covers a few percent of a 61 km tile, the histogram is effectively
unimodal, and Otsu splits the *land* distribution in half. It fails silently:
nothing crashes, and the resulting mask looks like a plausible flood.
**Evidence / numbers**, tile T00_00, per-month Otsu versus the new rule:

| month | sensor | water fraction, per-month Otsu | after the fix |
|---|---|---|---|
| 1977-02 | MSS | 0.641 | 0.078 |
| 1995-02 | TM | 0.478 | 0.034 |
| 2005-02 | ETM+ | 0.108 | 0.076 |
| 2023-02 | OLI | 0.161 | 0.084 |

Anchoring on the histogram peak rather than the median matters: the median
drifts upward in a flood month and would drag the threshold with it, flattening
the very seasonality the model has to learn. Calibration for T00_00 —
MNDWI: pooled Otsu -0.2646, median land mode -0.405, **delta +0.140**, median
water fraction 0.103. NDWI: **delta +0.065**, median water fraction 0.098,
matched to the MNDWI era.

**The strongest evidence that this is right is not any single month.** After the
fix, the six wettest months on the tile are 2015-09, 2015-08, 1978-07, 2019-02,
2020-06 and 2001-09 — i.e. the monsoon. The seasonal cycle was never encoded
anywhere in the thresholding rule; it emerged once the rule stopped being wrong.
Water fraction now runs p10 0.024 in the dry season to p90 0.364 in flood.
**Open question:** the NDWI delta assumes the long-run median water fraction of
the reach did not shift systematically between the MSS and TM eras. Stated in
the paper as an assumption, not a result.

---

## 2026-09-21 — MSS striping: partially fixed, honestly reported
**Decision:** 3x3 median filter on MSS-derived months only; the residual is
declared a limitation rather than papered over.
**Alternatives considered and rejected:** per-row offset removal equalises the
row medians but leaves the mask visibly striped, because the six MSS detectors
differ in gain as well as offset. Per-row moment matching (equalising mean and
standard deviation) made it markedly *worse* — banding power rose from 0.013 to
0.183 on 1975-03 — because it stretches rows that genuinely contain little
variance.
**Evidence / numbers:** 54 of 636 months on T00_00 are MSS-derived; across the
archive, 480 of 4 107 scenes. All of them fall in the training split; the test
split (2018-2024) is entirely ETM+/OLI, so the headline metrics are unaffected.
**Open question:** none — but it belongs in the limitations section.

---

## 2026-09-21 — Local compute reality and the A100 estimate
**Decision:** local runs use 128 px crops, patch 8, embed 128, depth 4,
batch 4, window stride 3.
**Rationale:** the development machine has **no CUDA device** and 8 CPU cores,
so the local configuration is sized by what finishes in hours. CLAUDE.md §3
anticipates exactly this and asks that seconds/epoch be measured locally so the
A100 booking can be estimated before it is paid for.
**Evidence / numbers**, measured forward+backward, batch 4 unless noted:

| model | crop | config | params | s/step | s/sample |
|---|---|---|---|---|---|
| TimeSformer | 256 | embed 128, depth 4, patch 16 (batch 2) | 1.44 M | 9.22 | 4.61 |
| TimeSformer | 128 | patch 8 | 1.41 M | 7.45 | 1.86 |
| TimeSformer | 128 | patch 16 | 1.41 M | 1.52 | 0.38 |
| ConvLSTM | 256 | hidden 64, 2 layers (batch 2) | 0.48 M | 89.02 | 44.51 |
| ConvLSTM | 128 | hidden 32, 1 layer | 0.05 M | 3.72 | 0.93 |
| ConvLSTM | 128 | hidden 16, 1 layer | 0.01 M | 1.32 | 0.33 |

ConvLSTM at the full local size is **48x** the cost of TimeSformer per sample,
because it convolves at full resolution for all 12 timesteps while the
transformer reduces to a token grid immediately. That ratio is itself a result
worth reporting: divided space-time attention is not merely more accurate in
the literature, it is what makes this problem tractable at all without a GPU.
**Open question:** none.

---

## 2026-09-21 — Two evaluation-cost bugs caught before they cost anything
**Decision:** (a) training enumerates one window per start month, not one per
crop position; (b) validation and test tile the raster with **non-overlapping**
crops, and validation is capped at 320 windows.
**Rationale:** the training crop origin is redrawn at random in ``__getitem__``,
so listing nine crop positions per window did not add data — it silently
multiplied epoch length ninefold while presenting the same windows. Separately,
a half-overlapping evaluation grid at crop 128 on a 512 px tile gives 49 crops
per window instead of 16; with validation running every epoch that would have
made validation the dominant cost of training.
**Evidence / numbers:** the uncapped validation split would have been roughly
11 000 samples per epoch. It is now 320, evenly spaced with a fixed seed, so it
is identical between runs. The test split is never capped — it runs once and
must be complete.
**Open question:** none.

---

## 2026-09-21 — Erosion must be measured against the same calendar month
**Decision:** Stage 4 differences the forecast month against the **same
calendar month one year earlier**, not against the most recent observation.
**Rationale:** this was very nearly a serious error. The Jamuna floods: between
February and May a large area goes from land to water with no bank having
moved at all. Differencing a May forecast against a February observation
therefore measures *seasonal inundation plus erosion* and reports the sum as
erosion — which would have inflated every household count in the handoff table,
in the alarming direction. Comparing like month with like month cancels the
seasonal term and leaves the year-on-year channel change, which is what the
word erosion means here. It is also why CEGIS compares dry season with dry
season rather than consecutive images (সিইজিআইএস ২০১৮).
**Evidence / numbers:** water fraction on tile T00_00 runs from p10 0.024 in
the dry season to p90 0.364 in flood — a seasonal swing roughly **fifteen
times** the long-run median. Any erosion figure derived from an unmatched pair
of months is dominated by that swing, not by bank retreat.
**Implementation:** the reference index is ``anchor + out_frames - 12``, which
for a three-month horizon is ``anchor - 9`` — inside the observed input window,
so it is a real observation rather than a second forecast. The chosen
reference month is written into the run summary, and a tile without a
year-earlier month falls back with a logged warning.
**Open question:** none, but the limitation of the *previous* definition is
worth stating in the paper: a water-mask forecast measures channel change, and
turning that into erosion requires an explicit seasonal control.

---

## 2026-09-21 — Overpass bbox splitting emitted sliver tiles
**Decision:** compute sub-tile edges from an index rather than accumulating.
**Rationale:** `lat += 0.1` drifts. For the box 24.5-25.0 the fifth step lands
on 25.000000000000004, which is greater than the north edge, so the loop
emitted an extra row of zero-height slivers — each one a wasted request against
a shared, volunteer-run service.
**Evidence / numbers:** a 0.5 x 0.5 degree box produced **30** sub-queries
instead of 25, a 20 percent overhead. Pinned by
`tests/test_risk.py::test_bbox_splitting_covers_the_whole_extent`.
**Open question:** none.

---

## 2026-09-21 — Correction: the archive gap is seven years, not three
**Decision:** supersedes the figure given in the 2026-09-20 entry "MSS-era
coverage is genuinely gappy". That entry counted scenes over tile T02_00 only,
before the other three tiles had been acquired, and concluded the hole was
1981-1983. With all four tiles in hand the measurement is larger and the
earlier number should not be quoted.
**Evidence / numbers:** counting the full manifest, the years with **zero**
usable Landsat scenes anywhere in the study area are

    1974, and 1981, 1982, 1983, 1984, 1985, 1986

— seven years in total, six of them consecutive. Scene counts across the
transition: 1978: 60 (all MSS), 1979: 35, 1980: 19, **1981-1986: 0**,
1987: 12 (all TM), 1988: 84, 1989: 144. The same seven years are empty on all
four tiles independently, so this is an archive property, not a tiling
artefact.
**Rationale:** routine MSS acquisition over Bangladesh stopped in the early
1980s, and although Landsat-5 TM began in August 1982, many of its South Asian
scenes were held at international ground stations rather than in the USGS
archive. The Landsat Global Archive Consolidation recovered part of that
holding, but coverage over Bangladesh for 1981-1986 remains effectively empty.
**Consequence for the paper:** "a continuous fifty-two-year monthly record" is
not an accurate description and is not claimed. The accurate statement is a
fifty-two-year *span* containing seven entirely absent years, with 53.6 percent
of pixel-months directly observed and 79.9 percent usable after capped
interpolation. Documenting that shortfall precisely is itself one of the
contributions.
**Open question:** none. The gap is wide enough that no training window spans
it — `min_observed` drops those windows automatically.

---

## 2026-09-21 — Results: the learned model wins where it matters, not everywhere
**Decision:** report the horizon breakdown as the headline, not the pooled
average.
**Evidence / numbers**, test split 2018-2024, 4 480 windows, all unseen years:

| model | params | IoU | bank F1 | precision | recall | MDE (m) |
|---|---|---|---|---|---|---|
| ConvLSTM | 0.05 M | **0.406** | **0.583** | 0.546 | 0.625 | **696.0** |
| persistence | 0 | 0.378 | 0.543 | 0.650 | 0.466 | 775.6 |
| TimeSformer | 1.26 M | 0.360 | 0.540 | 0.466 | 0.641 | 925.0 |

Per horizon (bank F1 / MDE in metres):

| model | +1 month | +2 months | +3 months |
|---|---|---|---|
| persistence | **0.647 / 613.4** | 0.549 / 828.0 | 0.494 / 913.7 |
| ConvLSTM | 0.631 / 634.3 | **0.585 / 710.6** | **0.568 / 759.6** |
| TimeSformer | 0.547 / 882.6 | 0.542 / 881.5 | 0.530 / 1024.8 |

**The crossover is the finding.** Persistence is the best forecaster at one
month — a river does not move much in four weeks — and then falls away
steeply. ConvLSTM overtakes it between month one and month two and is clearly
ahead by month three: 15.0 percent better bank F1 and 154 m (16.9 percent)
less displacement error. Three months is also the horizon that preparedness
actually needs. So the learned model earns its keep precisely where it is
needed, and at short range a trivial rule is enough — which is itself worth
knowing, because it says what horizon is worth building a model for.

**TimeSformer under-performs persistence and this is not hidden.** At 1.26 M
parameters it is 25x the size of the ConvLSTM, trained on 473 windows for six
CPU epochs. Its precision/recall split (0.466 / 0.641) is the signature of an
under-trained model over-predicting the positive class. The honest conclusion
is not that the architecture is unsuitable but that at this data volume and
compute budget the small convolutional model is the better match.
**Open question:** whether the ranking survives the full-scale run. That is
what the A100 estimate is for.

---

## 2026-09-21 — A control that bounds what "erosion" can mean here
**Decision:** measure year-on-year change between two **observed** masks, and
report it as the method's noise floor.
**Rationale:** the Stage 4 forecast reports 88 821 ha of erosion across the
four tiles for March 2025. Taken at face value that is 5.9 percent of the
study area lost in a year, which is far above any published Jamuna figure. The
question is how much of it is model error and how much is what this
measurement *always* produces.
**Evidence / numbers**, erosion / accretion in hectares, both masks observed:

| tile | 2022-03 to 2023-03 | 2023-03 to 2024-03 | 2015-03 to 2016-03 |
|---|---|---|---|
| T00_00 | 18 085 / 8 186 | 9 384 / 18 027 | 2 241 / 14 256 |
| T01_00 | 10 025 / 8 199 | 9 135 / 8 712 | 8 826 / 8 510 |
| T02_00 | 8 646 / 9 033 | 8 934 / 7 995 | 7 901 / 6 474 |
| T03_00 | 7 027 / 5 599 | 6 313 / 6 900 | 8 218 / 6 490 |

Two things follow. First, **gross** land-to-water flux between two real
observations is already 6 000-18 000 ha per tile per year, so the forecast's
88 821 ha across four tiles is roughly 2.6x an observed baseline of about
33 766 ha — over-predicted, but not by the order of magnitude the raw number
suggests. Second, and more important, gross erosion is nearly cancelled by
gross accretion: the **net** is between -1 826 and +12 015 ha, an order of
magnitude smaller. In a braided river the channels trade places constantly.
**Consequence:** the interpretable quantity is net land change, not gross
erosion, and the DDM table reports both plus their difference. Quoting gross
erosion alone would overstate land loss several-fold.
**Open question:** separating true bank retreat from channel switching needs a
persistence criterion — land lost and *not regained* over several years. That
is the natural next refinement.

---

## 2026-09-21 — The decision threshold must be calibrated, not assumed
**Decision:** Stage 4 picks the water-probability cut on the **validation**
split instead of using 0.5.
**Rationale:** `pos_weight` (6.07 here) stops BCE collapsing to "predict land
everywhere", but it also shifts the output distribution upward, so a fixed 0.5
over-predicts water. Erosion is defined as land-becoming-water, so that bias
does not stay inside the model — it inflates every hectare and every household
count in the table handed to the DDM, in the alarming direction.
**Evidence / numbers:** sweeping the validation split gives bank F1 of 0.5759
at 0.30, 0.5897 at 0.40, 0.5977 at 0.50, **0.5985 at 0.55**, 0.5966 at 0.60,
0.5496 at 0.80 — a smooth single peak at **0.55**. The gain over 0.5 is small,
which is itself informative: the final ConvLSTM is close to calibrated. The
absurd figure seen earlier (201 057 ha of erosion) came from an epoch-2
checkpoint, not from the threshold.
**Discipline:** the cut is chosen on validation and applied unchanged to test
and to the operational forecast. Choosing it on test would be tuning the
number being reported.
**Open question:** none.

---

## 2026-09-21 — Overpass: three separate failures, three separate fixes
**Decision:** project User-Agent, mirror rotation, short timeouts, a global
cell lattice, and geometry-restricted cell selection.
**Evidence / numbers, in the order they were hit:**
1. **HTTP 406.** The default `python-requests` User-Agent is blocked. Fixed by
   identifying the project, which the Overpass usage policy asks for anyway.
2. **HTTP 504.** The main endpoint sheds load during European working hours.
   Fixed by rotating over four public mirrors with backoff.
3. **Stalls.** With `timeout_s = 300` the client waited 330 s on a hung mirror,
   so a single bad cell cost five and a half minutes and the stage crawled at
   two cells in five minutes. Cut to a 10 s connect and 80 s read timeout: a
   dead mirror is abandoned almost immediately and throughput rose to roughly
   five cells per minute.

Two further changes reduce the load placed on a volunteer-run service: cells
that do not intersect the forecast geometry are skipped (150 of 161 here — the
erosion ribbon runs the length of the reach, so the saving is modest), and the
cell lattice is snapped to global multiples of 0.1 degrees so the on-disk cache
is reusable across runs instead of shifting whenever the query extent moves.
**Open question:** for an operational system this should run against a private
Overpass instance or a planet extract, not the public API.

---

## 2026-09-21 — The .docx was one paragraph per source line
**Decision:** the manuscript builder now follows Markdown paragraph semantics —
consecutive non-blank lines are one paragraph, a blank line ends it.
**Rationale:** the Markdown source is hard-wrapped at about 78 columns so that
diffs stay readable. The builder was emitting a Word paragraph per *source
line*, so every wrapped line became its own block with its own space-after.
On screen in python-docx it looked fine; in Word it would justify and break
line by line, and the submitted document would have looked unmistakably wrong.
**Evidence / numbers:** the 7,022-word manuscript produced **668** paragraphs
before the fix and **175** after — 161 of them non-empty, which is the right
order for a paper with 12 headings, 8 tables, 6 figures and 33 references. The
abstract is now a single 1,379-character paragraph instead of fourteen
fragments. Reference entries are split on the `।।` sidenote key so each is one
hanging-indent block with its continuation lines joined.
**Pinned by:** `tests/test_manuscript.py`, which also checks the two
typography profiles against the Bangla Academy spec (17/15/12/14 pt at 1.5
spacing for the first copy, 16/14/11/12 pt single-spaced for the final), the
`w:szCs` and `w:rFonts/w:cs` complex-script attributes that Word actually uses
for Bengali, A4 geometry, and that the manuscript stays inside 5,000-8,000
words.
**Open question:** none.

---

## 2026-09-21 — The household count is a *spatially biased* lower bound
**Decision:** rank unions by predicted erosion in hectares, not by household
count, and say so in the paper, the CSV and the dashboard.
**Rationale:** OSM building coverage over the Jamuna floodplain is not merely
incomplete, it is incomplete *in a pattern that tracks exactly the places this
system exists to warn*. The char settlements are the least mapped.
**Evidence / numbers**, from the 2025-03 run (342 unions, 807 418 building
centroids queried):

| district | predicted erosion (ha) | OSM buildings | unions |
|---|---|---|---|
| Kurigram | 22 357 | 9 333 | 68 |
| Gaibandha | 9 738 | 1 023 | 53 |
| Bogra | 8 343 | **35** | 67 |
| Sirajganj | 7 815 | 197 | 36 |
| Jamalpur | 4 530 | 85 | 60 |
| Tangail | 2 657 | **2** | 22 |

Per union it is starker still: Chaluabari (Bogra) 1 589 ha against **one**
mapped building, Bishalpur (Bogra) 1 338 ha against **zero**, Erendabari
(Gaibandha) 1 286 ha against **zero**, Gabsara (Tangail) 1 059 ha against
**two**. Twelve unions with more than 500 ha of predicted erosion have no
mapped buildings at all, and six of the twenty worst-eroding unions have fewer
than ten.
**Consequence:** ordering unions by households at risk produces an ordering by
OSM mapping density, not by risk. For a warning system that is not a harmless
inaccuracy — it would send resources where the data is rather than where the
people are. The table therefore keeps raw building counts and derived
household estimates in separate columns, and the recommended ranking key is
hectares.
**Open question:** the fix is not technical. It needs field enumeration or a
join to the census at mauza level.

---

## 2026-09-21 — What the absolute numbers are and are not
**Decision:** report the Stage 4 figures as a demonstration of the mechanism,
not as an operational warning, and state that in the paper.
**Evidence / numbers:** the 2025-03 forecast gives 88 820.6 ha erosion against
12 945.6 ha accretion — a net of **-75 875 ha**. The control in the previous
entry shows that between two *observed* masks the net is close to zero
(-1 826 to +12 015 ha across tiles and year-pairs). A net loss of that size is
therefore not signal; it is the model's water over-prediction, the same bias
visible in its test precision/recall split. The threshold calibration (0.55)
reduces but does not remove it, because the residual is in the model, not the
cut.
**What is demonstrated:** the pipeline runs end to end on real data; the
learned model beats persistence on shoreline position at the three-month
horizon; and the forecast can be carried through to named union parishads.
**What is not demonstrated:** absolute hectares and absolute household counts.
Those wait on the full-scale training run and on field validation.

---

## 2026-09-22 — The DDM dashboard as a static website
**Decision:** publish the Stage 5 hand-off as a static website (স্থির ওয়েবসাইট)
built with Next.js 16 (`output: "export"`) in `web/`. The site computes nothing:
`scripts/sync_web_data.py` copies the Stage 4 results into
`web/public/data/forecast.json`, and the CSV a DDM officer downloads is the
pipeline's own file, copied byte for byte. The Streamlit app stays as the
analyst's tool.
**Alternatives considered:** Streamlit alone (needs a Python server running for
as long as the page is up); a server-rendered Next.js app (nothing on the page
varies per request, so a server would only add cost and a failure point);
a table library such as TanStack Table (342 rows do not need one).
**Rationale:** the reader is a disaster-management officer on a phone, often on
a weak connection. A static page loads fast, can be hosted for nothing, and
cannot drift from the pipeline, because every number on it is read from the
pipeline's output at build time and a malformed file fails the build.
**Evidence / numbers:** one page per language (`/` Bengali, `/en/` English),
each with its own `<html lang>`; all 342 rows are in the prerendered HTML
(about 36 KB gzipped), so the table is readable before any script runs.
Filters and sort order live in the URL, so a view can be sent to a colleague.
The served CSV's SHA-256 (`51d4615c…`) matches the Stage 4 file. Checked at
360 px width: the page never scrolls sideways; the table scrolls inside its
own box with the union column pinned. 31 web tests (Vitest) and 17 bridge
tests (pytest).
**Open question:** where to host it — a decision for the project, not the code.
Union and upazila names are shown in GADM's English spelling on both pages;
Bengali place names need an authoritative source (BBS geocodes) and have not
been added.

---

## 2026-09-22 — "Unknown", not zero: what an empty erosion zone means
**Decision:** where erosion is predicted in a union but no building is mapped
inside the erosion zone, the dashboard shows buildings as "none mapped"
(মানচিত্রে নেই) and households and persons as "unknown" (অজানা), never as 0.
A union in the table for accretion alone has no erosion zone, so its 0 is a
real zero and is shown as one.
**Alternatives considered:** printing the CSV's 0 (reads as "nobody at risk");
hiding those unions (hides 20 403 ha of predicted erosion).
**Rationale:** OpenStreetMap cannot tell unsettled char from an unmapped
village. Whole-union building density (মানচিত্রায়ণ-ঘনত্ব) can: no inhabited
rural union has only a handful of buildings per square kilometre.
**Evidence / numbers** (2025-03 forecast; GADM 4.1 unions, areas in
EPSG:32645, cached Overpass cells): 342 unions in the table, 305 with
predicted erosion, 37 with accretion only. Of the 305, **200** have no mapped
building in the erosion zone. Of those 200:

| whole-union OSM density | unions | reading |
|---|---|---|
| < 10 buildings/km² | **130** | settlement not mapped |
| 10–100 buildings/km² | 38 | ambiguous |
| ≥ 100 buildings/km² | 32 | mapped; zone probably unsettled |

The 130 carry 14 444 of those unions' 20 403 ha of predicted erosion. The
median density by district runs from 0.4/km² (Sirajganj), 1.0 (Tangail) and
1.9 (Bogra) in the south to 158.9 (Rangpur) and 171.6 (Kurigram) in the
north — a gap of more than four hundred times along one river. The 10 846
households on the page are therefore a floor, summed over the 105 unions with
mapped buildings.
**Open question:** as in the 2026-09-21 entry on spatial bias — only field
enumeration or a mauza-level census join closes this. A per-union density
column in the Stage 4 CSV would carry the distinction to the DDM file itself;
not yet added.

---

## 2026-09-22 — pandas' default float parser is not exact
**Decision:** read the Stage 4 table with `float_precision="round_trip"` in
the bridge to the website.
**Rationale:** the website rebuilds filtered CSV downloads from
`forecast.json`, and a filtered file should be exactly the matching lines of
the original. A test that rebuilt the whole file from the site data failed.
**Evidence / numbers:** pandas' default (fast) parser misread 102 of the
table's floats by one unit in the last place (e.g. 1.9656597836708474 read as
…476). The exact parser misreads none. The size is ~10⁻¹⁶ relative, so no
reported number changes; the property is now tested on the real table.
**Open question:** other scripts that read pipeline CSVs still use the default
parser. At this magnitude it cannot affect any figure in the paper.

---

## 2026-09-22 — Correction: the first 2025-03 table was built on an incomplete building set
**Decision:** re-run Stage 4 for 2025-03 on the complete Overpass cache, and
make every run record how many of its query cells actually answered.
**Rationale:** the figures quoted so far came from a run that counted 807 418
buildings in the queried cells. The Stage 4 log shows two runs finishing
within seconds of each other on 2026-09-21, and the one whose outputs
survived had read the cache while cells over northern Kurigram were still
missing. Nothing flagged the gap: a cell that never answered simply
contributed no buildings. Stage 4 now logs and stores
`osm_cells_answered` / `osm_cells_requested`, so an incomplete cache is
visible in the run summary.
**Evidence / numbers:** the forecast is unchanged (88 820.6 ha erosion,
12 945.6 ha accretion, 4 647 polygons; identical union by union). With all
150 query cells answered there are 908 886 buildings. Buildings inside the
predicted erosion zones rise from 10 846 to **20 755**, so households (one per
building) from 10 846 to **20 755** and persons from 48 797 to **93 386**. The
change is confined to 19 unions in Kurigram (district total 9 333 → 19 164;
Bhurungamari 40 → 2 583, Shilkhuri 1 206 → 3 266, Paiker Chhara 872 → 2 621),
Bogra (35 → 77) and Gaibandha (1 023 → 1 059). Eroding unions with no mapped
building in the zone: 200 → 195; with mapped buildings: 105 → 110. Unchanged:
twelve unions above 500 ha with no mapped building, and six of the twenty
worst-eroding unions with fewer than ten.
**Consequence:** the household figures in the entry "The household count is a
*spatially biased* lower bound" (2026-09-21), in the paper draft
(`04_body_part3.md`, `04z_body_part4.md`) and in README are superseded by
these. The argument of that entry stands, and the north–south contrast is
sharper: Kurigram 19 164 buildings against 22 357 ha, Bogra 77 against
8 343 ha, Tangail 2 against 2 657 ha.
**Open question:** the paper text still carries the old figures.

---

## 2026-09-22 — OSM mapping density is now a column of the DDM table
**Decision:** Stage 4 writes, for each union, `osm_buildings_per_km2` — mapped
buildings per km² (মানচিত্রায়ণ-ঘনত্ব, mapping density) over the part of the
union the Overpass query covered, areas in EPSG:32645, water included —
together with `osm_measured_km2` (that area) and `osm_mapping`: **low** below
10, **medium** 10–100, **high** from 100 buildings/km², **not measured** where
less than 1 km² was covered.
**Alternatives considered:** density over the whole GADM union (counts ground
that was never queried as empty); density over land only (needs a water mask
for every union, and the bands are an order of magnitude apart, so it moves
few unions between them); a completeness factor applied to the counts (a
guess presented as data).
**Rationale:** the column tells a DDM officer how far to trust a union's
household count, and whether an empty erosion zone is more likely unsettled
char (high) or an unmapped village (low). Measuring only where the query
reached is what keeps a failed Overpass cell from reading as "no buildings".
Including water makes river-heavy unions read lower than their settled land
would; that errs towards caution, since a lower band means less trust in an
empty zone.
**Evidence / numbers** (2025-03; 150 of 150 cells answered): 163 unions low,
71 medium, 107 high, 1 not measured. Of the 195 eroding unions with no mapped
building in the zone, **129 are low**, 37 medium and 29 high; together they
hold 19 048 ha of predicted erosion, 14 052 ha of it in the low group.
District medians (buildings/km²): Sirajganj 0.4, Tangail 1.0, Bogra 1.9,
Sherpur 5.3, Jamalpur 7.9, Gaibandha 29.2, Lalmonirhat 120.8, Rangpur 158.9,
Kurigram 171.6 — more than four hundred times from south to north. These
figures supersede the first density check in this log (200 unions, 130 below
10/km², 14 444 of 20 403 ha), which used the incomplete table.
**Open question:** the band edges are order-of-magnitude judgements, not
calibrated against a field count.

---

## 2026-09-22 — Bengali place names, checked against each union's own portal
**Decision:** Stage 4 adds `division_bn`, `district_bn`, `upazila_bn` and
`union_bn` (স্থাননাম, place names) to the DDM table. The names come from
nuhil/bangladesh-geocode (MIT licence), a compilation of the Bangladesh
National Portal (বাংলাদেশ জাতীয় তথ্য বাতায়ন, bangladesh.gov.bd), read at a
pinned commit (`5622f68`). Every matched name is then checked against the
title of that unit's own official portal page, and where the live portal
spells it differently, the portal's spelling is used.
**Alternatives considered:** the BBS/OCHA COD-AB gazetteer on HDX (the most
authoritative source, but its alternate-name fields are empty: English only);
the geo-vault dataset (a copy of the same compilation with coordinates
added); transliterating GADM's English into Bengali (a guess, and the page
would present guesses as names).
**Rationale:** a table for Bengali-reading officers should name each union as
the union names itself. GADM and the compilation are two romanisations of the
same names (Holdia / Haldia, Rowmari / Raumari), so names are matched down the
hierarchy on a consonant skeleton that ignores vowel spellings and digraphs.
A match is accepted only if it is exact on that skeleton (or on the Bengali
name read back into Latin consonants), or clearly the best candidate in its
upazila (score ≥ 0.75, margin ≥ 0.15); and in every case the Bengali name must
read back to GADM's spelling (≥ 0.6). Otherwise the union keeps its English
name: a gap is visible, a wrong name is not.
**Evidence / numbers** (2025-03, 342 unions): 302 exact, 6 exact on the
Bengali name (Mechhra/মেছড়া, which the compilation romanises "Mesra"), 11
fuzzy, 2 "X Sadar" unions, 16 municipalities (পৌরসভা) named from their
upazila or district, **5 refused** (Birhati, Dhanbari, Fulbari,
KhurdaKamarpur, Sultanganj (Part)). Of the 337 named: **312 confirmed by
their portal**, 4 corrected by it (দরবস্ত for the compiled "দরবস্ত ইয়নিয়ন",
হাটিকুমরুল for "হটিকুমরুল"), 16 composed, and 5 unverified because the portal
answered with an English title or an error page. Two upazila spellings were
corrected (ভূঞাপুর, ভূরুঙ্গামারী); all district and division names were
confirmed. Two practical findings: portal servers in five districts send an
incomplete certificate chain, fixed by adding the missing Sectigo
intermediate (pinned by SHA-256, verification still on), not by switching
verification off; and titles carry qualifiers after a comma
("শ্রীবরদী, সদর ইউনিয়নের"), which are cut. The full match record is
`outputs/tables/bn_names_2025-03.csv`.
**Open question:** the five refused unions and five unverified names need a
local check, and the names a native reader's eye before the table goes to
the DDM.

---

## 2026-09-22 — The DDM website is live
**Decision:** host the static site on Vercel (project `jamunarekha`, the
user's personal scope), deployed from `web/` with the Vercel CLI:
**https://jamunarekha.vercel.app** (Bengali), `/en/` (English).
**Alternatives considered:** deploying on every push through Vercel's GitHub
integration (the CLI connected it unasked; it was disconnected, because a
push would then publish unreviewed changes, and with the repository root as
the build root every push would have failed); GitHub Pages (would need the
sub-path build).
**Rationale:** each deployment is a deliberate act after the data have been
synced and the build checked locally, which suits a table that a disaster
office may act on.
**Evidence / numbers:** Vercel built the upload in 26 s; the live pages carry
`lang="bn"` and `lang="en"`, all 342 rows, and the corrected totals (20 755
households); the served CSV (86 156 bytes) has the SHA-256 the footer states;
unknown paths return the bilingual 404; at 360 px the page does not scroll
sideways; no console errors. The footer credits OpenStreetMap contributors
(ODbL), GADM, USGS and the National Portal.
**Open question:** none.

---

## 2026-09-22 — The erosion map on the website
**Decision:** add a map (মানচিত্র) of the forecast zones to the website, above
the table and under one shared filter row. Stage 4 now also writes the zones
cut on union boundaries (`change_zones_<month>.geojson`); the Python bridge
compacts them for the web (simplified by 30 m in EPSG:32645, coordinates to
five decimals, properties shortened), and the page draws them with Leaflet
over OpenStreetMap's tiles.
**Alternatives considered:** a vector-tile map library (heavier to download on
a weak connection, for 5 520 polygons that a canvas draws easily); drawing
GADM's union outlines (GADM's licence forbids redistributing its boundaries,
and a website would); a union-level choropleth (the zones are the forecast;
colouring whole unions would suggest the whole union erodes).
**Rationale:** the table says how much each union stands to lose; the map says
where along the bank. Erosion and accretion are drawn as the palette's
diverging pair, red for land lost and blue for land gained, validated in both
modes (colour-blind separation ΔE 21.6 light / 19.2 dark), and the table's
erosion bars turned from blue to the same red so that a colour means one thing
on the page. Filters sit above map and table and scope both: zones outside the
current view fade rather than vanish, so the reader keeps the river, and the
map moves to what is left. Hover (or tap) shows a card led by the zone's area,
then its union and that union's figures from the table; the table remains the
full, accessible view of every number.
**Evidence / numbers:** 5 520 zones (3 367 erosion, 2 153 accretion; 2 772
outside every union, mostly across the border). The web file is 2.3 MB,
about 0.4 MB compressed, fetched only when the map nears the screen. Checked in
a headless Chrome driven over the DevTools protocol, because the automation
tab in the desktop browser was hidden: load in 0.9–1.2 s, the Kurigram filter
flies the map there (68 unions in the table), the hover card and tap popup name
Shilkhuri with its table figures, dark mode, English page, 390 px phone (no
sideways scroll; map at about half the screen so a finger can still scroll the
page), no console errors.
**Finding on the way:** merged into one shape, the erosion zones measure
exactly the forecast's 88 820.6 ha, but cut on union boundaries they sum to
88 975.9 ha. GADM 4.1's outlines overlap between 197 neighbouring union
pairs, and a zone piece in an overlap is counted in both. Inside unions the
table's erosion sums to 56 815.5 ha against 56 660.2 ha without the double
count — 0.27 % high. Buildings in the overlaps are counted twice in the same
way.
**Open question:** whether to make the union layer a clean partition before
the overlay (each overlap given to one union), which would lower the table's
totals by that 0.27 %.

---

## 2026-09-22 — Overlapping union outlines resolved; map live
**Decision:** where GADM's outlines overlap, Stage 4 now gives each overlap to
one union: within every forecast zone, the pieces are taken largest first and
each later piece loses what an earlier one already covers, so the overlap goes
to the union holding the larger share of that zone (ties by GADM id). Applied
to the table's pieces and the map's alike.
**Alternatives considered:** repairing the GADM layer itself (the same result,
but polygon operations on GADM's detailed outlines took over ten minutes for
the reach, against seconds for the forecast zones); splitting each overlap
between the two unions (no clean geometric rule, and a half-assignment is
still a guess).
**Evidence / numbers** (2025-03): erosion inside unions 56 815.5 → **56 660.2
ha**, accretion 4 674.2 → 4 667.8 ha; buildings in the zones 20 755 →
**20 712** (43 had been counted in two unions), persons 93 386 → 93 193.
Kurigram's buildings 19 164 → 19 132; Bogra 77 and Tangail 2 unchanged. The
map's erosion now sums to exactly the forecast's 88 820.6 ha. 146 unions move
slightly; none is lost, and the counts of unknown-household unions (195),
mapping bands and Bengali names are unchanged. These figures supersede the
household and building totals in the earlier entries of today.
Deployed to https://jamunarekha.vercel.app with the map: the live data and the
served CSV (byte-identical to Stage 4's) carry these figures, and the headless
browser checks passed against the live site. The map's zones travel at 495 KB
compressed, not the 0.4 MB estimated in the entry above.
**Open question:** the paper draft still carries the first run's figures.

---

## 2026-09-22 — Paper draft brought up to the corrected figures
**Decision:** replace the first run's Stage 4 figures in the paper draft with
the corrected run's, numbers only, and regenerate figure 7. No sentence was
rewritten or added: the Bangla Academy stylesheet (§৪.১) does not accept
AI-written text as research, so the prose stays the author's.
**Evidence / numbers:** `04_body_part3.md` — buildings queried 8,07,418 →
9,08,886; households 10,846 → 20,712; persons 48,797 → 93,193; Chaluabari
1,589 → 1,588 ha, Bishalpur 1,338 → 1,337 ha, Erendabari 1,286 → 1,284 ha
(each still with 0–1 mapped buildings); the district table (Kurigram 22,308 ha
and 19,132 buildings; Gaibandha 9,714 / 1,056; Bogra 8,321 / 77; Sirajganj
7,789 / 190; Jamalpur 4,513 / 85; Tangail 2,647 / 2). `04z_body_part4.md` —
the same Bogra, Tangail and Kurigram figures and the 20,712 households.
Unchanged and re-checked: 342 unions; twelve unions above 500 ha with no mapped
building; six of the twenty worst-eroding with fewer than ten; Gabsara 1,059 ha
with two. Figure 7 regenerated from the corrected table, with GADM names split
for reading (Saheber Alga) and "1 building" singular. Both .docx versions
rebuilt (7,502 words, inside 5,000–8,000); the manuscript tests pass, and the
.docx files carry every new figure and none of the old.
**Open question:** the results section says the zones are cut on union
boundaries but not how overlapping outlines are handled (each overlap given to
the union holding the larger share of the zone); that sentence is for the
author to write.
