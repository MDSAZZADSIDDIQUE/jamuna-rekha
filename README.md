# যমুনারেখা · JamunaRekha

**Forecasting the Jamuna River shoreline three months ahead, so char dwellers
know before the land goes.**

Bangla Academy research grant · May–July 2026

*বাংলা সংস্করণ নিচে দেখুন / Bengali version below*

---

## English

### What this is

Every year the Jamuna River takes land — homesteads, cropland, whole *chars* —
and the people living on it usually find out too late. JamunaRekha is a neural
forecasting system that predicts **where the shoreline will be three months
from now**, and then translates that prediction into the only number that
matters to a disaster officer: **how many households in which union parishad
are about to lose their land.**

- **Study area:** Jamuna River, 24.5–26.5 °N, 89.4–89.9 °E
- **Record:** Landsat 1/5/7/8/9, 1972–2024 (52 years)
- **Task:** 12 monthly water-mask frames in → next 3 predicted
- **Output:** an erosion risk map and a CSV of at-risk households for the
  Department of Disaster Management (DDM)

### Pipeline

| # | Stage | Tools | Produces |
|---|---|---|---|
| 1 | **Data acquisition** | Google Earth Engine (browser) | Monthly MNDWI water masks, 512×512 GeoTIFF → `data/raw/` |
| 2 | **Preprocessing** | rasterio, numpy, geopandas | Gap-filled time-series tensor, `JamunaShift-52Y` PyTorch Dataset |
| 3 | **Model** | PyTorch Lightning | TimeSformer + CNN decoder; ConvLSTM and persistence baselines |
| 4 | **Risk overlay** | geopandas, Overpass API | Household counts per union parishad → `outputs/tables/` |
| 5 | **Dashboard** | Streamlit + Folium | Risk map, sortable table, CSV download |

**Stage 1** builds the water index **MNDWI = (Green − SWIR1)/(Green + SWIR1)**
with per-sensor band mapping across five Landsat missions, cloud masking, an
Otsu threshold, and monthly median composites.

**Stage 3** replaces the TimeSformer classification head with a pixel-wise CNN
decoder producing 512×512 sigmoid masks. The loss is
**BCE + 0.3 × spatial gradient loss** (Sobel-based) — plain BCE blurs the
riverbank, and the bank edge is precisely the thing we are forecasting.
Reported metrics: **IoU**, **F1 on bank pixels**, and
**Mean Displacement Error in metres**.

**Stage 4** vectorizes the predicted erosion zones, pulls OSM building
footprints via Overpass, spatially joins to count buildings inside each zone,
and aggregates to union parishad level using GADM boundaries.

### Requirements

- **Python 3.11**
- A GPU for full training. Local development runs on CPU with 256×256 crops.

### Setup

```bash
python -m venv .venv
```

```bash
pip install -r requirements.txt
```

Activate the environment with `.venv\Scripts\activate` on Windows, or
`source .venv/bin/activate` on Linux and macOS.

On the Runpod A100 image, install with `torch` and `torchvision` removed from
`requirements.txt` — the container already ships a CUDA build, and overwriting
it wastes paid GPU time.

### Repository layout

```
CLAUDE.md            project brief for Claude Code
configs/             YAML run configs — no hard-coded paths anywhere else
gee/                 Earth Engine JavaScript (runs in the browser Code Editor)
src/jamunarekha/
  data/              GEE ingest, preprocessing, JamunaShift-52Y Dataset
  models/            TimeSformer variant, ConvLSTM, persistence, losses
  risk/              vectorization, Overpass, GADM aggregation
  dashboard/         Streamlit app
  utils/             geo helpers, seeding, logging
notebooks/           exploration only
tests/               pytest
data/                raw / interim / processed — git-ignored
outputs/             checkpoints, figures, predictions, logs, tables
docs/NOTES.md        running research log, feeds the Bengali paper
```

### Working method

The GPU budget is roughly **30 A100-hours in total**, so the discipline is:
debug locally on small crops, overfit a single batch to near-zero loss, confirm
the loop is resumable, estimate wall-clock from local timings — and only then
rent the A100. The pipeline is built and verified **one module at a time**.

### Status

Scaffolding. No pipeline code yet — Stage 1 is next.

### Deliverables

1. A research paper **in Bengali** (`docs/NOTES.md` is the running source material)
2. The dashboard and DDM-ready CSV export

---

## বাংলা

### এটি কী

প্রতি বছর যমুনা নদী জমি কেড়ে নেয় — ভিটেমাটি, ফসলের ক্ষেত, গোটা চর — আর যাঁরা
সেখানে বাস করেন তাঁরা সাধারণত জানতে পারেন অনেক দেরিতে। **যমুনারেখা** একটি নিউরাল
পূর্বাভাস ব্যবস্থা, যা অনুমান করে **আজ থেকে তিন মাস পরে নদীতীর কোথায় থাকবে**, এবং
সেই অনুমানকে রূপান্তরিত করে সেই একটিমাত্র সংখ্যায় যা একজন দুর্যোগ কর্মকর্তার কাছে
গুরুত্বপূর্ণ: **কোন ইউনিয়ন পরিষদের কতগুলি পরিবার জমি হারাতে চলেছে।**

- **গবেষণা এলাকা:** যমুনা নদী, ২৪.৫–২৬.৫° উত্তর, ৮৯.৪–৮৯.৯° পূর্ব
- **উপাত্তের সময়কাল:** ল্যান্ডস্যাট ১/৫/৭/৮/৯, ১৯৭২–২০২৪ (৫২ বছর)
- **কাজ:** ১২ মাসের জলমুখোশ (water mask) ইনপুট → পরবর্তী ৩ মাসের পূর্বাভাস
- **ফলাফল:** ভাঙন-ঝুঁকির মানচিত্র এবং দুর্যোগ ব্যবস্থাপনা অধিদপ্তরের (DDM) জন্য
  ঝুঁকিপূর্ণ পরিবারের তালিকা (CSV)

### পাইপলাইন

| ধাপ | বিষয় | সরঞ্জাম | উৎপন্ন ফল |
|---|---|---|---|
| ১ | **উপাত্ত সংগ্রহ** | Google Earth Engine (ব্রাউজার) | মাসভিত্তিক MNDWI জলমুখোশ, ৫১২×৫১২ GeoTIFF → `data/raw/` |
| ২ | **প্রাক-প্রক্রিয়াকরণ** | rasterio, numpy, geopandas | ফাঁক-পূরণ করা কালানুক্রমিক টেনসর, `JamunaShift-52Y` ডেটাসেট |
| ৩ | **মডেল** | PyTorch Lightning | TimeSformer + CNN ডিকোডার; সঙ্গে ConvLSTM ও persistence তুলনামূলক মডেল |
| ৪ | **ঝুঁকি বিশ্লেষণ** | geopandas, Overpass API | ইউনিয়ন পরিষদভিত্তিক পরিবার গণনা → `outputs/tables/` |
| ৫ | **ড্যাশবোর্ড** | Streamlit + Folium | ঝুঁকির মানচিত্র, সাজানো-যোগ্য তালিকা, CSV ডাউনলোড |

**ধাপ ১**-এ পাঁচটি ল্যান্ডস্যাট অভিযানের জন্য পৃথক ব্যান্ড-বিন্যাস ব্যবহার করে
জলসূচক **MNDWI = (সবুজ − SWIR1)/(সবুজ + SWIR1)** নির্ণয় করা হয়, সঙ্গে মেঘ-মুখোশ,
Otsu থ্রেশহোল্ড এবং মাসিক মধ্যক (median) সংমিশ্রণ।

**ধাপ ৩**-এ TimeSformer-এর শ্রেণিবিন্যাস স্তরের বদলে পিক্সেল-ভিত্তিক CNN ডিকোডার
বসানো হয়, যা ৫১২×৫১২ সিগময়েড মুখোশ তৈরি করে। ক্ষতি-অপেক্ষক (loss) হলো
**BCE + ০.৩ × স্থানিক গ্রেডিয়েন্ট ক্ষতি** (Sobel-ভিত্তিক) — শুধু BCE ব্যবহার করলে
নদীতীরের রেখা ঝাপসা হয়ে যায়, অথচ ওই তীররেখাই আমাদের পূর্বাভাসের মূল বিষয়।
পরিমাপক: **IoU**, **তীর-পিক্সেলে F1**, এবং **মিটারে গড় স্থানচ্যুতি ত্রুটি**
(Mean Displacement Error)।

**ধাপ ৪**-এ পূর্বাভাসকৃত ভাঙন-অঞ্চলকে ভেক্টরে রূপান্তর করা হয়, Overpass API থেকে
OSM ভবনের রূপরেখা আনা হয়, স্থানিক সংযোগের (spatial join) মাধ্যমে প্রতিটি অঞ্চলের
ভেতরের ভবন গোনা হয়, এবং GADM সীমানা ব্যবহার করে ইউনিয়ন পরিষদ পর্যায়ে সমষ্টি
করা হয়।

### প্রয়োজনীয়তা

- **পাইথন ৩.১১**
- পূর্ণ প্রশিক্ষণের জন্য GPU। স্থানীয় উন্নয়ন CPU-তে ২৫৬×২৫৬ ছোট অংশ নিয়ে চলে।

### প্রস্তুতি

```bash
python -m venv .venv
```

```bash
pip install -r requirements.txt
```

উইন্ডোজে `.venv\Scripts\activate`, আর লিনাক্স বা ম্যাকওএসে
`source .venv/bin/activate` দিয়ে পরিবেশটি সক্রিয় করতে হবে।

Runpod-এর A100 ইমেজে `requirements.txt` থেকে `torch` ও `torchvision` বাদ দিয়ে
ইনস্টল করতে হবে — কনটেইনারে আগে থেকেই CUDA সংস্করণ থাকে, সেটি মুছে নতুন করে
বসালে অর্থমূল্যের GPU সময় নষ্ট হয়।

### ভান্ডারের বিন্যাস

```
CLAUDE.md            Claude Code-এর জন্য প্রকল্প-পরিচিতি
configs/             YAML কনফিগ — অন্য কোথাও কোনো স্থির পথ (path) লেখা হবে না
gee/                 Earth Engine জাভাস্ক্রিপ্ট (ব্রাউজারের Code Editor-এ চলে)
src/jamunarekha/
  data/              GEE উপাত্ত গ্রহণ, প্রাক-প্রক্রিয়াকরণ, JamunaShift-52Y ডেটাসেট
  models/            TimeSformer রূপান্তর, ConvLSTM, persistence, ক্ষতি-অপেক্ষক
  risk/              ভেক্টরকরণ, Overpass, GADM সমষ্টিকরণ
  dashboard/         Streamlit অ্যাপ
  utils/             ভূস্থানিক সহায়ক, বীজ (seed), লগিং
notebooks/           শুধু অনুসন্ধানের জন্য
tests/               pytest
data/                raw / interim / processed — গিটে রাখা হয় না
outputs/             চেকপয়েন্ট, চিত্র, পূর্বাভাস, লগ, সারণি
docs/NOTES.md        চলমান গবেষণা-নোট, যা বাংলা প্রবন্ধের কাঁচামাল
```

### কাজের পদ্ধতি

GPU-এর বাজেট সব মিলিয়ে প্রায় **৩০ A100-ঘণ্টা**, তাই নিয়ম হলো: ছোট অংশ নিয়ে
স্থানীয়ভাবে ত্রুটি সারানো, একটিমাত্র ব্যাচে মডেলকে প্রায় শূন্য ক্ষতিতে
অতি-অভিযোজিত (overfit) করে দেখা, প্রশিক্ষণ-চক্র পুনরারম্ভযোগ্য কি না নিশ্চিত করা,
স্থানীয় সময়-মাপ থেকে মোট সময় আন্দাজ করা — এবং কেবল তারপরেই A100 ভাড়া নেওয়া।
পাইপলাইন **একবারে একটি অংশ** করে তৈরি ও যাচাই করা হয়।

### বর্তমান অবস্থা

কাঠামো তৈরি হয়েছে। এখনো কোনো পাইপলাইন কোড লেখা হয়নি — পরবর্তী ধাপ হলো ধাপ ১।

### প্রদেয়

১. **বাংলা ভাষায়** গবেষণা প্রবন্ধ (`docs/NOTES.md` তার চলমান উৎস-উপাদান)
২. ড্যাশবোর্ড এবং DDM-এর উপযোগী CSV রপ্তানি
