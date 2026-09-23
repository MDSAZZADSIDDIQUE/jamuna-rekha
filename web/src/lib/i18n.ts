/**
 * Interface text in Bengali and English.
 *
 * Plain module (no server-only imports), so both the server-rendered page and
 * the client-side table import it directly. Parameterised strings are
 * functions, and functions cannot cross the server/client boundary as props —
 * which is why the table imports this module rather than receiving text.
 *
 * Numbers arrive already formatted for the language (see lib/format.ts).
 */

import type { SortKey } from "./table";
import type { Lang, MappingLevel } from "./types";

export interface Dictionary {
  htmlTitle: string;
  htmlDescription: string;
  skipToTable: string;
  project: string;
  heading: string;
  subtitle: (forecastMonth: string, referenceMonth: string) => string;
  switchLanguage: { label: string; href: string; lang: Lang };

  bannerTitle: string;
  bannerRank: string;
  bannerUnmapped: (unmapped: string, eroding: string, lowMapped: string) => string;
  bannerAccuracy: (metres: string) => string;
  bannerNotValidated: string;

  statsHeading: string;
  statUnions: string;
  statErosion: string;
  statErosionNote: (total: string) => string;
  statAccretion: string;
  statAccretionNote: string;
  statHouseholds: string;
  statHouseholdsNote: (mapped: string) => string;
  hectaresShort: string;

  filtersLabel: string;
  mapHeading: string;
  mapIntro: (month: string) => string;
  mapLabel: string;
  legendErosion: string;
  legendAccretion: string;
  legendFaded: string;
  mapLoading: string;
  mapFailed: string;
  zoneOutside: string;
  zoneUnionTotals: (erosion: string, households: string) => string;

  tableHeading: string;
  tableCaption: string;
  filterDistrict: string;
  allDistricts: string;
  filterSearch: string;
  searchPlaceholder: string;
  filterMinErosion: string;
  anyErosion: string;
  atLeast: (hectares: string) => string;
  resetFilters: string;
  showing: (shown: string, total: string) => string;
  sortedBy: (column: string, order: string) => string;
  /** Sort order in words: numbers by size, names by alphabet. */
  orders: { desc: string; asc: string; az: string; za: string };
  downloadAll: (total: string) => string;
  downloadFiltered: (shown: string) => string;
  downloadAllNote: string;
  downloadFilteredNote: string;
  columns: Record<SortKey, string>;
  mappingLevels: Record<MappingLevel, string>;
  perKm2: (density: string) => string;
  noneMapped: string;
  unknown: string;
  locationLine: (upazila: string, district: string) => string;
  footnote: string;
  mappingNote: (low: string, high: string) => string;
  empty: string;

  methodHeading: string;
  methodForecast: string;
  methodForecastValue: (month: string, horizon: string, anchor: string) => string;
  methodReference: string;
  methodReferenceValue: (month: string) => string;
  methodModel: string;
  methodModelValue: (model: string, horizon: string, threshold: string) => string;
  methodAccuracy: string;
  methodAccuracyValue: (metres: string, horizon: string, period: string, windows: string) => string;
  methodTotals: string;
  methodTotalsValue: (total: string, share: string) => string;
  methodHouseholds: string;
  methodHouseholdsValue: (perHousehold: string) => string;
  methodMapping: string;
  methodMappingValue: (low: string, high: string, minArea: string) => string;
  methodNames: string;
  methodNamesValue: (named: string, total: string) => string;
  methodData: string;
  methodDataValue: string;
  methodCaveat: string;

  footerSource: (file: string, hash: string) => string;
  /** Linked to the OpenStreetMap copyright page, as the ODbL asks. */
  attributionOsm: string;
  attributionRest: string;
  footerProject: string;
}

const bn: Dictionary = {
  htmlTitle: "যমুনারেখা · ইউনিয়নভিত্তিক ভাঙন-পূর্বাভাস",
  htmlDescription:
    "যমুনা নদীর তীরভাঙনের তিন মাস আগাম পূর্বাভাস, ইউনিয়ন পরিষদভিত্তিক তালিকা। গবেষণা-নমুনা।",
  skipToTable: "সরাসরি তালিকায় যান",
  project: "যমুনারেখা · বাংলা একাডেমি গবেষণা-প্রকল্প",
  heading: "যমুনার ভাঙন-পূর্বাভাস: ইউনিয়নভিত্তিক তালিকা",
  subtitle: (forecastMonth, referenceMonth) =>
    `${forecastMonth}-এর তিন মাস আগাম পূর্বাভাস · তুলনার ভিত্তি ${referenceMonth}`,
  switchLanguage: { label: "English", href: "/en/", lang: "en" },

  bannerTitle: "গবেষণা-নমুনা — কার্যকর সতর্কবার্তা নয়",
  bannerRank:
    "ইউনিয়নের ক্রম নির্ধারণ করুন ভাঙনের হেক্টর দিয়ে, পরিবার-সংখ্যা দিয়ে নয়। পরিবার-সংখ্যা নির্ভর করে কোন এলাকা ওপেনস্ট্রিটম্যাপে কতটা মানচিত্রিত তার উপর।",
  bannerUnmapped: (unmapped, eroding, lowMapped) =>
    `ভাঙনের পূর্বাভাস আছে এমন ${eroding}টি ইউনিয়নের মধ্যে ${unmapped}টিতে ভাঙন-অঞ্চলের ভেতরে একটিও ভবন মানচিত্রে নেই, আর তার ${lowMapped}টিতে পুরো ইউনিয়নেই মানচিত্রে ভবন প্রায় নেই। সেখানে পরিবার-সংখ্যা অজানা, শূন্য নয়।`,
  bannerAccuracy: (metres) =>
    `তিন মাসের পূর্বাভাসে তীররেখার অবস্থানে গড় ত্রুটি প্রায় ${metres} মিটার।`,
  bannerNotValidated: "হেক্টর ও পরিবারের পরম সংখ্যা এখনো মাঠপর্যায়ে যাচাই করা হয়নি।",

  statsHeading: "সারসংক্ষেপ",
  statUnions: "প্রভাবিত ইউনিয়ন পরিষদ",
  statErosion: "পূর্বাভাসিত ভাঙন",
  statErosionNote: (total) => `ইউনিয়ন-সীমার ভেতরে · সমগ্র পূর্বাভাসে ${total} হে.`,
  statAccretion: "চর জাগা",
  statAccretionNote: "ইউনিয়ন-সীমার ভেতরে",
  statHouseholds: "পরিবার, অন্তত",
  statHouseholdsNote: (mapped) => `মানচিত্রিত ভবন আছে এমন ${mapped}টি ইউনিয়ন থেকে`,
  hectaresShort: "হে.",

  filtersLabel: "ফিল্টার",
  mapHeading: "মানচিত্র",
  mapIntro: (month) =>
    `${month}-এর পূর্বাভাসিত ভাঙন ও চর জাগার এলাকা। কোনো এলাকায় ক্লিক করলে তার ইউনিয়ন ও আয়তন দেখা যাবে; প্রতিটি ইউনিয়নের সংখ্যা নিচের তালিকায় আছে।`,
  mapLabel: "পূর্বাভাসিত ভাঙন ও চর জাগার মানচিত্র",
  legendErosion: "পূর্বাভাসিত ভাঙন",
  legendAccretion: "চর জাগা",
  legendFaded: "ফিকে: বর্তমান ফিল্টারের বাইরে",
  mapLoading: "মানচিত্র লোড হচ্ছে…",
  mapFailed: "মানচিত্র লোড করা যায়নি। সব সংখ্যা নিচের তালিকায় আছে।",
  zoneOutside: "কোনো ইউনিয়ন-সীমার ভেতরে নয়",
  zoneUnionTotals: (erosion, households) => `পুরো ইউনিয়নে ভাঙন ${erosion} হে. · পরিবার ${households}`,

  tableHeading: "ইউনিয়নভিত্তিক তালিকা",
  tableCaption:
    "ইউনিয়ন পরিষদভিত্তিক পূর্বাভাসিত ভাঙন, চর জাগা, নিট ভূমি-পরিবর্তন, ওপেনস্ট্রিটম্যাপে নথিভুক্ত ভবন, অনুমিত পরিবার ও মানুষের সংখ্যা, এবং ইউনিয়নটি ওপেনস্ট্রিটম্যাপে কতটা মানচিত্রিত।",
  filterDistrict: "জেলা",
  allDistricts: "সব জেলা",
  filterSearch: "ইউনিয়ন বা উপজেলা",
  searchPlaceholder: "যেমন চিলমারী বা Chilmari",
  filterMinErosion: "ন্যূনতম ভাঙন",
  anyErosion: "যেকোনো",
  atLeast: (hectares) => `অন্তত ${hectares} হে.`,
  resetFilters: "ফিল্টার মুছুন",
  showing: (shown, total) => `${total}টির মধ্যে ${shown}টি ইউনিয়ন দেখানো হচ্ছে`,
  sortedBy: (column, order) => `ক্রম: ${column}, ${order}`,
  orders: { desc: "বেশি থেকে কম", asc: "কম থেকে বেশি", az: "বর্ণানুক্রমে", za: "উল্টো বর্ণানুক্রমে" },
  downloadAll: (total) => `CSV ডাউনলোড · সব ${total}টি ইউনিয়ন`,
  downloadFiltered: (shown) => `CSV ডাউনলোড · দেখানো ${shown}টি ইউনিয়ন`,
  downloadAllNote: "পাইপলাইনের মূল ফাইল, দুর্যোগ ব্যবস্থাপনা অধিদপ্তরের জন্য",
  downloadFilteredNote: "দেখানো সারিগুলি, মূল ফাইলের একই কলামে",
  columns: {
    union: "ইউনিয়ন",
    erosion_ha: "ভাঙন (হে.)",
    accretion_ha: "চর জাগা (হে.)",
    net_land_change_ha: "নিট পরিবর্তন (হে.)",
    buildings_osm: "ভবন (ওএসএম)",
    households_est: "পরিবার",
    persons_est: "মানুষ",
    osm_buildings_per_km2: "ওএসএম মানচিত্রায়ণ",
  },
  mappingLevels: { low: "কম", medium: "মাঝারি", high: "বেশি", "not measured": "মাপা হয়নি" },
  perKm2: (density) => `বর্গকিমিতে ${density}`,
  noneMapped: "মানচিত্রে নেই",
  unknown: "অজানা",
  locationLine: (upazila, district) => `${upazila} · ${district}`,
  footnote:
    "“মানচিত্রে নেই”: পূর্বাভাসিত ভাঙন-অঞ্চলের ভেতরে ওপেনস্ট্রিটম্যাপে কোনো ভবন নথিভুক্ত নেই। জমিটি জনবসতিহীন চর হতে পারে, আবার বসতি থাকলেও মানচিত্রে না-ও থাকতে পারে — ওপেনস্ট্রিটম্যাপ এ দুটিকে আলাদা করতে পারে না। তাই সেখানে পরিবার ও মানুষের সংখ্যা “অজানা”।",
  mappingNote: (low, high) =>
    `“ওএসএম মানচিত্রায়ণ”: পুরো ইউনিয়নে, যতটুকু এলাকায় ভবনের খোঁজ করা হয়েছে, প্রতি বর্গকিলোমিটারে ওপেনস্ট্রিটম্যাপে নথিভুক্ত ভবনের সংখ্যা। কম (${low}-এর নিচে): ইউনিয়নটি প্রায় মানচিত্রহীন, তাই পরিবার-সংখ্যা প্রকৃত সংখ্যার চেয়ে অনেক কম। বেশি (${high} বা তার বেশি): ইউনিয়নটি ঘনভাবে মানচিত্রিত, তাই সেখানে ভাঙন-অঞ্চলে ভবন না থাকলে জমিটি জনবসতিহীন হওয়ার সম্ভাবনা বেশি।`,
  empty: "এই ফিল্টারে কোনো ইউনিয়ন নেই।",

  methodHeading: "এই পূর্বাভাস সম্পর্কে",
  methodForecast: "পূর্বাভাস",
  methodForecastValue: (month, horizon, anchor) =>
    `${month}, ${horizon} মাস আগাম (শেষ পর্যবেক্ষণ ${anchor})`,
  methodReference: "তুলনার ভিত্তি",
  methodReferenceValue: (month) =>
    `${month} — এক বছর আগের একই মাস, যাতে বর্ষার মৌসুমি জলমগ্নতা ভাঙন হিসেবে গণ্য না হয়`,
  methodModel: "মডেল",
  methodModelValue: (model, horizon, threshold) =>
    `${model}: ১২ মাসের জলমুখোশ থেকে পরবর্তী ${horizon} মাস · জল-সম্ভাবনার সীমা ${threshold}, যাচাই-উপাত্তে নির্ধারিত`,
  methodAccuracy: "নির্ভুলতা",
  methodAccuracyValue: (metres, horizon, period, windows) =>
    `${horizon} মাসের দিগন্তে তীররেখার গড় স্থানচ্যুতি ${metres} মিটার (${period}, ${windows}টি পরীক্ষা-নমুনা)`,
  methodTotals: "মোট পূর্বাভাস",
  methodTotalsValue: (total, share) =>
    `${total} হেক্টর ভাঙন, যার ${share} বাংলাদেশের ইউনিয়ন-সীমার ভেতরে; তালিকায় কেবল এই অংশ`,
  methodHouseholds: "পরিবার-হিসাব",
  methodHouseholdsValue: (perHousehold) =>
    `নথিভুক্ত ভবনপ্রতি একটি পরিবার, পরিবারপ্রতি ${perHousehold} জন (আদমশুমারি ২০২২)`,
  methodMapping: "মানচিত্রায়ণ-ঘনত্ব",
  methodMappingValue: (low, high, minArea) =>
    `প্রতিটি ইউনিয়নের যতটুকু এলাকায় ভবনের খোঁজ করা হয়েছে (জলাভূমিসহ), সেখানে প্রতি বর্গকিলোমিটারে মানচিত্রিত ভবন: ${low}-এর নিচে কম, ${high} থেকে বেশি; ${minArea} বর্গকিলোমিটারের কম এলাকায় মাপা হয়নি`,
  methodNames: "স্থাননাম",
  methodNamesValue: (named, total) =>
    `${total}টির মধ্যে ${named}টি ইউনিয়নের বাংলা নাম বাংলাদেশ জাতীয় তথ্য বাতায়ন (bangladesh.gov.bd) থেকে নেওয়া, প্রতিটি সংশ্লিষ্ট ইউনিয়নের নিজস্ব পোর্টালে মিলিয়ে দেখা; বাকিগুলো GADM-এর ইংরেজি বানানে`,
  methodData: "উপাত্ত",
  methodDataValue:
    "ল্যান্ডস্যাট ১–৯, ১৯৭২–২০২৪ (কালেকশন ২), ১২০ মিটার বিভেদন · জিএডিএম ৪.১ ইউনিয়ন-সীমানা · ওপেনস্ট্রিটম্যাপ ভবন",
  methodCaveat:
    "মডেলটি সীমিত মাত্রায় প্রশিক্ষিত এবং ফলাফল মাঠপর্যায়ে যাচাই হয়নি। এই তালিকাকে সিদ্ধান্তের একমাত্র ভিত্তি হিসেবে ব্যবহার করবেন না।",

  footerSource: (file, hash) => `উৎস: ${file} · SHA-256 ${hash}`,
  attributionOsm: "ভবন © ওপেনস্ট্রিটম্যাপ অবদানকারীরা (ODbL)",
  attributionRest: "সীমানা: GADM ৪.১ · ল্যান্ডস্যাট চিত্র: ইউএসজিএস · বাংলা স্থাননাম: বাংলাদেশ জাতীয় তথ্য বাতায়ন",
  footerProject: "যমুনারেখা · গবেষণা-নমুনা, কার্যকর সতর্কবার্তা নয়",
};

const en: Dictionary = {
  htmlTitle: "JamunaRekha · Union-level erosion forecast",
  htmlDescription:
    "Three-month forecast of Jamuna riverbank erosion, listed by union parishad. Research prototype.",
  skipToTable: "Skip to the table",
  project: "JamunaRekha · Bangla Academy research project",
  heading: "Jamuna erosion forecast by union parishad",
  subtitle: (forecastMonth, referenceMonth) =>
    `Three-month forecast for ${forecastMonth} · compared with ${referenceMonth}`,
  switchLanguage: { label: "বাংলা", href: "/", lang: "bn" },

  bannerTitle: "Research prototype — not an operational warning",
  bannerRank:
    "Rank unions by hectares of erosion, not by household count. Household counts depend on how well each area is mapped in OpenStreetMap.",
  bannerUnmapped: (unmapped, eroding, lowMapped) =>
    `In ${unmapped} of the ${eroding} unions with predicted erosion, no building is mapped inside the erosion zone, and in ${lowMapped} of those hardly any building is mapped in the whole union. Their household count is unknown, not zero.`,
  bannerAccuracy: (metres) =>
    `At three months ahead, the predicted shoreline is off by about ${metres} m on average.`,
  bannerNotValidated: "Absolute hectares and household counts have not been checked in the field.",

  statsHeading: "Summary",
  statUnions: "Union parishads affected",
  statErosion: "Predicted erosion",
  statErosionNote: (total) => `Inside union boundaries · whole forecast ${total} ha`,
  statAccretion: "Accretion",
  statAccretionNote: "Inside union boundaries",
  statHouseholds: "Households, at least",
  statHouseholdsNote: (mapped) => `From the ${mapped} unions with mapped buildings`,
  hectaresShort: "ha",

  filtersLabel: "Filters",
  mapHeading: "Map",
  mapIntro: (month) =>
    `Predicted erosion and accretion zones for ${month}. Click a zone for its union and area; every union's figures are in the table below.`,
  mapLabel: "Map of predicted erosion and accretion",
  legendErosion: "Predicted erosion",
  legendAccretion: "Accretion",
  legendFaded: "Faded: outside the current filters",
  mapLoading: "Loading the map…",
  mapFailed: "The map could not be loaded. Every figure is in the table below.",
  zoneOutside: "Outside union boundaries",
  zoneUnionTotals: (erosion, households) => `Whole union: ${erosion} ha erosion · ${households} households`,

  tableHeading: "Unions",
  tableCaption:
    "Predicted erosion, accretion and net land change by union parishad, with buildings mapped in OpenStreetMap, estimated households and persons, and how densely each union is mapped.",
  filterDistrict: "District",
  allDistricts: "All districts",
  filterSearch: "Union or upazila",
  searchPlaceholder: "e.g. Chilmari",
  filterMinErosion: "Minimum erosion",
  anyErosion: "Any",
  atLeast: (hectares) => `At least ${hectares} ha`,
  resetFilters: "Clear filters",
  showing: (shown, total) => `Showing ${shown} of ${total} unions`,
  sortedBy: (column, order) => `Sorted by ${column}, ${order}`,
  orders: { desc: "largest first", asc: "smallest first", az: "A to Z", za: "Z to A" },
  downloadAll: (total) => `Download CSV · all ${total} unions`,
  downloadFiltered: (shown) => `Download CSV · ${shown} unions shown`,
  downloadAllNote: "The pipeline's original file, for the Department of Disaster Management",
  downloadFilteredNote: "The rows shown, with the same columns as the original file",
  columns: {
    union: "Union",
    erosion_ha: "Erosion (ha)",
    accretion_ha: "Accretion (ha)",
    net_land_change_ha: "Net change (ha)",
    buildings_osm: "Buildings (OSM)",
    households_est: "Households",
    persons_est: "Persons",
    osm_buildings_per_km2: "OSM mapping",
  },
  mappingLevels: { low: "low", medium: "medium", high: "high", "not measured": "not measured" },
  perKm2: (density) => `${density} per km²`,
  noneMapped: "none mapped",
  unknown: "unknown",
  locationLine: (upazila, district) => `${upazila} · ${district}`,
  footnote:
    "“None mapped”: no building is recorded in OpenStreetMap inside the predicted erosion zone. The land may be unsettled char, or a settlement may exist but not be mapped — OpenStreetMap cannot tell the two apart. Households and persons are therefore “unknown”.",
  mappingNote: (low, high) =>
    `“OSM mapping”: buildings mapped in OpenStreetMap per km² across the whole union, where the building query reached. Low (under ${low}): the union is barely mapped and its household count is far too low. High (${high} or more): the union is densely mapped, so an empty erosion zone there is more likely unsettled land.`,
  empty: "No union matches these filters.",

  methodHeading: "About this forecast",
  methodForecast: "Forecast",
  methodForecastValue: (month, horizon, anchor) =>
    `${month}, ${horizon} months ahead (last observation ${anchor})`,
  methodReference: "Compared with",
  methodReferenceValue: (month) =>
    `${month} — the same month a year earlier, so that seasonal monsoon flooding is not counted as erosion`,
  methodModel: "Model",
  methodModelValue: (model, horizon, threshold) =>
    `${model}: 12 monthly water masks in, the next ${horizon} out · water-probability cut ${threshold}, set on validation data`,
  methodAccuracy: "Accuracy",
  methodAccuracyValue: (metres, horizon, period, windows) =>
    `Mean shoreline displacement of ${metres} m at ${horizon} months (${period}, ${windows} test windows)`,
  methodTotals: "Whole forecast",
  methodTotalsValue: (total, share) =>
    `${total} ha of erosion, ${share} of it inside Bangladeshi union boundaries; the table lists only that part`,
  methodHouseholds: "Households",
  methodHouseholdsValue: (perHousehold) =>
    `One household per mapped building, ${perHousehold} persons per household (Census 2022)`,
  methodMapping: "Mapping density",
  methodMappingValue: (low, high, minArea) =>
    `Mapped buildings per km² over each union's queried area, water included: low below ${low}, high from ${high}; not measured where under ${minArea} km² was queried`,
  methodNames: "Place names",
  methodNamesValue: (named, total) =>
    `Bengali names for ${named} of ${total} unions, from the Bangladesh National Portal (bangladesh.gov.bd), each checked against the union's own portal page; the rest keep GADM's English spelling`,
  methodData: "Data",
  methodDataValue:
    "Landsat 1–9, 1972–2024 (Collection 2), 120 m resolution · GADM 4.1 union boundaries · OpenStreetMap buildings",
  methodCaveat:
    "The model was trained at limited scale and the results have not been checked in the field. Do not use this table as the only basis for a decision.",

  footerSource: (file, hash) => `Source: ${file} · SHA-256 ${hash}`,
  attributionOsm: "Buildings © OpenStreetMap contributors (ODbL)",
  attributionRest: "Boundaries: GADM 4.1 · Landsat imagery: USGS · Bengali place names: Bangladesh National Portal",
  footerProject: "JamunaRekha · research prototype, not an operational warning",
};

export const dictionaries: Record<Lang, Dictionary> = { bn, en };
