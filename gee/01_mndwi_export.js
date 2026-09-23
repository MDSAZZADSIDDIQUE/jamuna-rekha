/**
 * যমুনারেখা / JamunaRekha — Stage 1 in the Earth Engine Code Editor.
 *
 * Paste into https://code.earthengine.google.com and run. This reproduces,
 * band for band, what `src/jamunarekha/data/acquire_pc.py` does against the
 * Microsoft Planetary Computer STAC: same collections, same per-sensor band
 * mapping, same QA bits, same monthly median composite, same output grid.
 *
 * The Python path is the one used for the results in the paper, because it
 * needs no interactive Google sign-in and is therefore scriptable and
 * reproducible from version control. This file exists so the acquisition can
 * be audited or re-run inside GEE by a reviewer who prefers it, and because
 * CLAUDE.md §2 requires the Earth Engine source to be version-controlled even
 * though it runs in a browser.
 *
 * Exports one GeoTIFF per tile-month to Google Drive. Expect several thousand
 * export tasks across 1972–2024; run YEAR_START/YEAR_END in slices.
 */

// ---------------------------------------------------------------------------
// Configuration — keep in step with configs/base.yaml
// ---------------------------------------------------------------------------
var BBOX_WGS84   = [89.4, 24.5, 89.9, 26.5];  // min_lon, min_lat, max_lon, max_lat
var TARGET_CRS   = 'EPSG:32645';              // UTM 45N — metric, see CLAUDE.md §4
var RESOLUTION_M = 120;
var TILE_SIZE    = 512;
var YEAR_START   = 1972;
var YEAR_END     = 2024;
var MAX_CLOUD    = 80;
var DRIVE_FOLDER = 'jamunarekha_raw';

// ---------------------------------------------------------------------------
// Per-sensor band mapping.
//
// This is the table CLAUDE.md §2 calls "the single most common source of
// silent bugs". MSS carries no SWIR at all, so the 1972–1983 era uses NDWI
// (green vs NIR) while everything from Landsat 4 onward uses MNDWI
// (green vs SWIR1). Band NUMBERS differ per mission even where the band
// NAME does not.
// ---------------------------------------------------------------------------
// MSS band numbering changes between missions: Landsat 1-3 carried MSS as
// bands 4-7, Landsat 4-5 renumbered the same detectors as bands 1-4. Getting
// this wrong picks up the red band instead of NIR and quietly inverts NDWI.
var SENSORS = {
  'LANDSAT/LM01/C02/T1': {green: 'B4', dark: 'B7', index: 'NDWI',  res: 60},
  'LANDSAT/LM02/C02/T1': {green: 'B4', dark: 'B7', index: 'NDWI',  res: 60},
  'LANDSAT/LM03/C02/T1': {green: 'B4', dark: 'B7', index: 'NDWI',  res: 60},
  // Landsat 4 and 5 flew BOTH an MSS and a TM. Their MSS scenes live in
  // separate collections and must not be routed through the TM mapping, which
  // would request a SWIR band the MSS product does not have. The acquisition
  // for this study did encounter one such scene, in April 1989.
  'LANDSAT/LM04/C02/T1': {green: 'B1', dark: 'B4', index: 'NDWI',  res: 60},
  'LANDSAT/LM05/C02/T1': {green: 'B1', dark: 'B4', index: 'NDWI',  res: 60},
  'LANDSAT/LT04/C02/T1_L2': {green: 'SR_B2', dark: 'SR_B5', index: 'MNDWI', res: 30},
  'LANDSAT/LT05/C02/T1_L2': {green: 'SR_B2', dark: 'SR_B5', index: 'MNDWI', res: 30},
  'LANDSAT/LE07/C02/T1_L2': {green: 'SR_B2', dark: 'SR_B5', index: 'MNDWI', res: 30},
  'LANDSAT/LC08/C02/T1_L2': {green: 'SR_B3', dark: 'SR_B6', index: 'MNDWI', res: 30},
  'LANDSAT/LC09/C02/T1_L2': {green: 'SR_B3', dark: 'SR_B6', index: 'MNDWI', res: 30}
};

// Collection 2 QA_PIXEL bits: 0 fill, 1 dilated cloud, 2 cirrus, 3 cloud,
// 4 cloud shadow, 5 snow. Identical across L1 and L2 products.
var QA_REJECT_BITS = [0, 1, 2, 3, 4, 5];

function clearMask(image) {
  var qa = image.select('QA_PIXEL');
  var clear = ee.Image(1);
  QA_REJECT_BITS.forEach(function (bit) {
    clear = clear.and(qa.bitwiseAnd(1 << bit).eq(0));
  });
  return clear;
}

/** Scale Collection 2 Level-2 surface reflectance DN to reflectance. */
function scaleL2(image, bands) {
  return image.select(bands).multiply(2.75e-05).add(-0.2);
}

/**
 * Water index for one scene, cloud-masked.
 * Water is positive. MNDWI where SWIR1 exists, NDWI for MSS.
 */
function waterIndex(image, spec, isLevel2) {
  var bands = [spec.green, spec.dark];
  var reflectance = isLevel2 ? scaleL2(image, bands) : image.select(bands).toFloat();
  var green = reflectance.select(spec.green);
  var dark = reflectance.select(spec.dark);
  var index = green.subtract(dark).divide(green.add(dark)).rename('index');
  return index.updateMask(clearMask(image)).clamp(-1, 1);
}

/** Every scene from every mission overlapping `region` in one month. */
function monthlyScenes(region, year, month) {
  var start = ee.Date.fromYMD(year, month, 1);
  var end = start.advance(1, 'month');
  var merged = ee.ImageCollection([]);

  Object.keys(SENSORS).forEach(function (collectionId) {
    var spec = SENSORS[collectionId];
    var isLevel2 = collectionId.indexOf('_L2') > -1;
    var collection = ee.ImageCollection(collectionId)
      .filterBounds(region)
      .filterDate(start, end)
      .filter(ee.Filter.lt('CLOUD_COVER', MAX_CLOUD))
      .map(function (image) {
        return waterIndex(image, spec, isLevel2)
          .set('system:time_start', image.get('system:time_start'));
      });
    merged = merged.merge(collection);
  });
  return merged;
}

// ---------------------------------------------------------------------------
// Canonical tile lattice — must match utils/geo.py:study_grid exactly, so that
// a GEE export and a Planetary Computer export land on the same pixels.
// ---------------------------------------------------------------------------
function studyTiles() {
  var region = ee.Geometry.Rectangle(BBOX_WGS84, null, false);
  var projected = region.transform(TARGET_CRS, 1).bounds().coordinates().get(0);
  var coords = ee.List(projected);
  var xs = coords.map(function (p) { return ee.List(p).get(0); });
  var ys = coords.map(function (p) { return ee.List(p).get(1); });

  var tileM = RESOLUTION_M * TILE_SIZE;
  var left = ee.Number(xs.reduce(ee.Reducer.min())).divide(tileM).floor().multiply(tileM);
  var top = ee.Number(ys.reduce(ee.Reducer.max())).divide(tileM).ceil().multiply(tileM);
  var right = ee.Number(xs.reduce(ee.Reducer.max()));
  var bottom = ee.Number(ys.reduce(ee.Reducer.min()));

  var nCols = right.subtract(left).divide(tileM).ceil().max(1);
  var nRows = top.subtract(bottom).divide(tileM).ceil().max(1);

  var tiles = [];
  for (var r = 0; r < nRows.getInfo(); r++) {
    for (var c = 0; c < nCols.getInfo(); c++) {
      var originX = left.add(c * tileM);
      var originY = top.subtract(r * tileM);
      tiles.push({
        name: 'T' + ('0' + r).slice(-2) + '_' + ('0' + c).slice(-2),
        // GEE crsTransform: [xScale, xShear, xOrigin, yShear, yScale, yOrigin]
        crsTransform: [RESOLUTION_M, 0, originX.getInfo(),
                       0, -RESOLUTION_M, originY.getInfo()],
        geometry: ee.Geometry.Rectangle(
          [originX.getInfo(), originY.subtract(tileM).getInfo(),
           originX.add(tileM).getInfo(), originY.getInfo()],
          TARGET_CRS, false)
      });
    }
  }
  return tiles;
}

// ---------------------------------------------------------------------------
// Export loop
// ---------------------------------------------------------------------------
var tiles = studyTiles();
print('Tiles on the canonical grid:', tiles.length);

tiles.forEach(function (tile) {
  for (var year = YEAR_START; year <= YEAR_END; year++) {
    for (var month = 1; month <= 12; month++) {
      var scenes = monthlyScenes(tile.geometry, year, month);

      // Median over the month: rejects the residual bright cloud edges that
      // slip past the QA bitmask. With one scene the median is that scene.
      var index = scenes.median().select('index');
      var nobs = scenes.count().rename('nobs').unmask(0);

      var composite = index.multiply(10000).toInt16()
        .addBands(nobs.toInt16())
        .rename(['water_index_x10000', 'n_clear_observations']);

      var monthKey = year + '-' + ('0' + month).slice(-2);
      Export.image.toDrive({
        image: composite,
        description: tile.name + '_' + monthKey,
        folder: DRIVE_FOLDER,
        fileNamePrefix: tile.name + '_' + monthKey,
        crs: TARGET_CRS,
        crsTransform: tile.crsTransform,
        dimensions: TILE_SIZE + 'x' + TILE_SIZE,
        maxPixels: 1e9,
        fileFormat: 'GeoTIFF',
        formatOptions: {cloudOptimized: true}
      });
    }
  }
});

// Quick visual check before launching thousands of tasks.
Map.centerObject(ee.Geometry.Rectangle(BBOX_WGS84, null, false), 8);
Map.addLayer(
  monthlyScenes(ee.Geometry.Rectangle(BBOX_WGS84, null, false), 2023, 3).median(),
  {min: -0.5, max: 0.5, palette: ['brown', 'white', 'blue']},
  'MNDWI 2023-03'
);
