"""Stage 4d — Bengali names for the administrative units in the DDM table.

GADM spells Bangladeshi place names in English only, and not always the way
the government does (``Bogra`` for Bogura/বগুড়া, ``CharBhurungamari`` run
together). A table for the Department of Disaster Management should name each
union the way the union names itself.

Source
------
No official machine-readable list of union names in Bengali was found: the
BBS/OCHA COD-AB gazetteer on HDX carries English names only. The Bengali names
therefore come from a compilation of the Bangladesh National Portal
(bangladesh.gov.bd), nuhil/bangladesh-geocode (MIT licence), read at a pinned
commit (``risk.bn_names_url``).

The compilation also records each unit's own portal address, and every name
used here is checked against that portal page's title, e.g.
``হোম | হলদিয়া ইউনিয়ন``. Where the live portal spells a name differently, the
portal wins: it is the government's own page for that union.

Matching
--------
GADM and the compilation are two romanisations of one set of Bengali names —
Holdia/Haldia, Rowmari/Raumari, Mohongonj/Mohanganj. Names are matched down
the hierarchy (district; upazila within it; union within the upazila) on a
consonant skeleton that ignores the vowel spellings and digraphs where
romanisations disagree. A match is accepted only when it is exact on the
skeleton, or clearly the best candidate in its upazila; and in both cases the
Bengali name, read back into Latin consonants, must agree with GADM's English
spelling. Anything else keeps its English name. A union shown in English is a
gap; a union shown under another union's name would be an error.

Municipalities (paurashava) are not unions and are not in the compilation.
Their Bengali name is the matched upazila or district name followed by
পৌরসভা, which is how they are named; a GADM name of just "Paurashava" becomes
পৌরসভা alone, exactly what GADM says.
"""

from __future__ import annotations

import hashlib
import html
import json
import re
import ssl
import time
import unicodedata
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path
from typing import Callable

import certifi
import pandas as pd
import requests

from jamunarekha.utils.logging import get_logger

logger = get_logger("jamunarekha.names_bn")

#: Files of the compilation, with their (headerless) columns.
GAZETTEER_FILES = {
    "divisions": ("divisions/divisions.csv", ["id", "name", "bn_name", "url"]),
    "districts": ("districts/districts.csv", ["id", "division_id", "name", "bn_name", "lat", "lon", "url"]),
    "upazilas": ("upazilas/upazilas.csv", ["id", "district_id", "name", "bn_name", "url"]),
    "unions": ("unions/unions.csv", ["id", "upazilla_id", "name", "bn_name", "url"]),
}

#: District renamings of 2018: GADM 4.1 keeps some of the old spellings.
DISTRICT_ALIASES = {
    "Bogra": "Bogura",
    "Chittagong": "Chattogram",
    "Comilla": "Cumilla",
    "Barisal": "Barishal",
    "Jessore": "Jashore",
}

#: A fuzzy match must score at least this on the Latin skeleton...
MIN_KEY_SCORE = 0.75
#: ...beat the runner-up in its upazila by at least this much...
MIN_MARGIN = 0.15
#: ...and every match's Bengali name must read back to the GADM spelling this well.
MIN_BACK_CHECK = 0.6

def _nfc(text: str) -> str:
    return unicodedata.normalize("NFC", text)


# NFC throughout: it keeps য় as য plus a nukta, which a literal typed in an
# editor may not be, and an unnormalised suffix would fail to match itself.
PAURASHAVA_BN = _nfc("পৌরসভা")

#: Suffixes of a portal page title after the unit's name.
_TITLE_SUFFIXES = tuple(_nfc(s) for s in ("ইউনিয়ন পরিষদ", "ইউনিয়ন", "উপজেলা", "জেলা", "বিভাগ"))

USER_AGENT = {
    "User-Agent": (
        "JamunaRekha/1.0 (Jamuna erosion early warning; Bangla Academy research "
        "grant; checking union names against their official portal pages)"
    )
}


# ------------------------------------------------------------------ gazetteer
@dataclass(frozen=True)
class Gazetteer:
    """The compilation's four tables, Bengali names NFC-normalised."""

    divisions: pd.DataFrame
    districts: pd.DataFrame
    upazilas: pd.DataFrame
    unions: pd.DataFrame


def load_gazetteer(base_url: str, cache_dir: Path | str) -> Gazetteer:
    """Download (once) and read the Bengali-name compilation.

    Parameters
    ----------
    base_url
        Raw-file URL of the compilation at a pinned commit.
    cache_dir
        Where the CSVs are kept, normally ``data/interim/names_bn``.
    """
    cache_dir = Path(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)
    frames = {}
    for key, (relative, columns) in GAZETTEER_FILES.items():
        local = cache_dir / Path(relative).name
        if not local.exists():
            logger.info("downloading %s", relative)
            response = requests.get(f"{base_url.rstrip('/')}/{relative}", timeout=60)
            response.raise_for_status()
            local.write_bytes(response.content)
        frame = pd.read_csv(local, header=None, names=columns, dtype=str, keep_default_na=False)
        # The same cleaning as a portal title: the compilation has a few
        # names with a stray ward number ("১গোপালনগর") or a trailing "ইউনিয়ন".
        frame["bn_name"] = frame["bn_name"].map(clean_unit_name)
        frames[key] = frame
    return Gazetteer(**frames)


# ----------------------------------------------------------------- skeletons
_LATIN_DIGRAPHS = (
    ("chh", "c"), ("ch", "c"), ("sh", "s"), ("kh", "k"), ("gh", "g"), ("jh", "j"),
    ("th", "t"), ("dh", "d"), ("ph", "f"), ("bh", "b"), ("rh", "r"),
)
_LATIN_SINGLE = str.maketrans({"q": "k", "z": "j", "v": "b"})


def latin_key(name: str) -> str:
    """Consonant skeleton of a romanised name.

    Romanisations of Bengali disagree mostly about vowels (the inherent vowel
    is written a or o), aspirate digraphs, and ph/f, bh/v, z/j. Dropping the
    vowels and folding those pairs leaves the part they agree on:
    ``latin_key("Raumari") == latin_key("Rowmari")``.
    """
    s = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", str(name)).lower()
    s = re.sub(r"\(.*?\)", " ", s)
    s = re.sub(r"[^a-z]", "", s)
    for digraph, single in _LATIN_DIGRAPHS:
        s = s.replace(digraph, single)
    s = s.translate(_LATIN_SINGLE)
    s = re.sub(r"[aeiouyw]", "", s)
    return re.sub(r"(.)\1+", r"\1", s)


_BENGALI_CONSONANTS = {
    "ক": "k", "খ": "k", "গ": "g", "ঘ": "g", "ঙ": "ng", "চ": "c", "ছ": "c",
    "জ": "j", "ঝ": "j", "ঞ": "n", "ট": "t", "ঠ": "t", "ড": "d", "ঢ": "d",
    "ণ": "n", "ত": "t", "থ": "t", "দ": "d", "ধ": "d", "ন": "n", "প": "p",
    "ফ": "f", "ব": "b", "ভ": "b", "ম": "m", "য": "j", "র": "r", "ল": "l",
    "শ": "s", "ষ": "s", "স": "s", "হ": "h", "ৎ": "t", "ং": "ng", "ঋ": "r",
    "ৃ": "r",
}
# Applied in order, after NFC. NFC keeps the nukta letters (ড় ঢ় য়)
# decomposed as base letter + nukta, so only that form needs handling. The
# sequences are built from code points because the marks are invisible in an
# editor.
_NUKTA = chr(0x09BC)
_HASANTA = chr(0x09CD)
_BENGALI_SEQUENCES = (
    ("ক" + _HASANTA + "ষ", "ক"),   # ক্ষ reads kh: one k
    (_HASANTA + "য", ""),          # ya-phala is a glide, not a j
    (_HASANTA + "ব", ""),          # ba-phala is mostly silent (স্ব reads sh)
    ("ড" + _NUKTA, "র"),           # ড় reads r
    ("ঢ" + _NUKTA, "র"),           # ঢ় reads r
    ("য" + _NUKTA, ""),            # য় is a vowel glide
)


def bengali_key(name: str) -> str:
    """Consonant skeleton of a Bengali name, comparable with :func:`latin_key`.

    ``bengali_key("হলদিয়া") == latin_key("Haldia") == "hld"``. A cross-check,
    not a transliteration: it only has to be close enough to tell the right
    union from the wrong one.
    """
    s = unicodedata.normalize("NFC", str(name))
    for sequence, replacement in _BENGALI_SEQUENCES:
        s = s.replace(sequence, replacement)
    out = "".join(_BENGALI_CONSONANTS.get(ch, "") for ch in s)
    return re.sub(r"(.)\1+", r"\1", out)


def _similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, a, b).ratio() if a and b else 0.0


def back_check(english: str, bengali: str) -> float:
    """How well a Bengali name reads back to an English one, 0 to 1."""
    return _similarity(latin_key(english), bengali_key(bengali))


# ------------------------------------------------------------------ matching
@dataclass(frozen=True)
class Match:
    """One accepted or rejected match of a GADM name to the compilation."""

    row: pd.Series | None
    method: str          # exact | exact-bengali | sadar | fuzzy | rejected | ambiguous | no candidates
    score: float
    margin: float
    back_check: float


def best_match(name: str, candidates: pd.DataFrame) -> Match:
    """Match one GADM name against the compilation rows of its parent unit."""
    if candidates.empty:
        return Match(None, "no candidates", 0.0, 0.0, 0.0)
    key = latin_key(name)
    keys = candidates["name"].map(latin_key)

    exact = candidates[keys == key]
    if len(exact) > 1:
        return Match(None, "ambiguous", 1.0, 0.0, 0.0)
    method = "exact"
    if exact.empty:
        # A union named after its upazila's headquarters is "X Sadar" in the
        # compilation and plain "X" in GADM (Kazipur / Kazipur Sadar).
        exact = candidates[(keys == key + "sdr") | (keys + "sdr" == key)]
        method = "sadar"
    if exact.empty:
        # The compilation's own English is sometimes a poor romanisation
        # ("Mesra" for মেছড়া, Mechhra in GADM) while its Bengali name reads
        # straight back to GADM's spelling. Match on the Bengali too.
        exact = candidates[candidates["bn_name"].map(bengali_key) == key]
        method = "exact-bengali"
        if len(exact) > 1:
            return Match(None, "ambiguous", 1.0, 0.0, 0.0)
    if len(exact) == 1:
        row = exact.iloc[0]
        check = back_check(name, row["bn_name"])
        if check < MIN_BACK_CHECK:
            return Match(None, "rejected", 1.0, 0.0, check)
        return Match(row, method, 1.0, 1.0, check)

    scores = keys.map(lambda k: _similarity(key, k)).sort_values(ascending=False)
    top = float(scores.iloc[0])
    margin = top - (float(scores.iloc[1]) if len(scores) > 1 else 0.0)
    row = candidates.loc[scores.index[0]]
    check = back_check(name, row["bn_name"])
    if top >= MIN_KEY_SCORE and margin >= MIN_MARGIN and check >= MIN_BACK_CHECK:
        return Match(row, "fuzzy", top, margin, check)
    return Match(None, "rejected", top, margin, check)


def _paurashava_of(union: str, upazila: Match, district: Match) -> str | None:
    """Which unit a municipality is named after: "upazila", "district", "" or None.

    "" is a GADM name of just "Paurashava"; None means the prefix matches
    neither unit, so no Bengali name is built.
    """
    prefix = re.sub(r"\s*Paurashava$", "", re.sub(r"(?<=[a-z])(?=[A-Z])", " ", union)).strip()
    if not prefix:
        return ""
    for level, unit in (("upazila", upazila), ("district", district)):
        if unit.row is None:
            continue
        unit_key = latin_key(unit.row["name"])
        if latin_key(prefix) in (unit_key, re.sub(r"sdr$", "", unit_key)):
            return level
    return None


def compose_paurashavas(frame: pd.DataFrame) -> pd.DataFrame:
    """Fill ``union_bn`` for municipalities from their (verified) parent names."""
    out = frame.copy()
    for i, row in out[out["method"] == "paurashava"].iterrows():
        of = row["paurashava_of"]
        parent = row[f"{of}_bn"] if of else None
        if of and not parent:
            out.at[i, "union_bn"] = None
            continue
        stem = re.sub(r"\s*সদর$", "", _nfc(parent)).strip() if parent else ""
        out.at[i, "union_bn"] = f"{stem} {PAURASHAVA_BN}".strip()
    return out


def match_units(table: pd.DataFrame, gazetteer: Gazetteer) -> pd.DataFrame:
    """Match every row of the risk table down the administrative hierarchy.

    Returns
    -------
    pd.DataFrame
        One row per ``gid_union``: the Bengali names (None where unmatched),
        how each union was matched, and the portal address to verify against.
    """
    g = gazetteer
    records = []
    for (division, district, upazila), group in table.groupby(
        ["division", "district", "upazila"], sort=False
    ):
        div = best_match(division, g.divisions)
        dis = best_match(DISTRICT_ALIASES.get(district, district), g.districts)
        upa = (
            best_match(upazila, g.upazilas[g.upazilas["district_id"] == dis.row["id"]])
            if dis.row is not None else Match(None, "no candidates", 0.0, 0.0, 0.0)
        )
        unions = (
            g.unions[g.unions["upazilla_id"] == upa.row["id"]]
            if upa.row is not None else g.unions.iloc[0:0]
        )
        for _, row in group.iterrows():
            name = str(row["union"])
            paurashava_of = None
            if name.endswith("Paurashava"):
                paurashava_of = _paurashava_of(name, upa, dis)
                method = "paurashava" if paurashava_of is not None else "rejected"
                uni = Match(None, method, 0.0, 0.0, 0.0)
                bn = None                      # composed after verification
            else:
                uni = best_match(name, unions)
                bn = uni.row["bn_name"] if uni.row is not None else None
            records.append(
                {
                    "gid_union": row["gid_union"],
                    "division": division, "district": district, "upazila": upazila, "union": name,
                    "division_bn": div.row["bn_name"] if div.row is not None else None,
                    "district_bn": dis.row["bn_name"] if dis.row is not None else None,
                    "upazila_bn": upa.row["bn_name"] if upa.row is not None else None,
                    "union_bn": bn,
                    "matched_name": uni.row["name"] if uni.row is not None else None,
                    "method": uni.method,
                    "paurashava_of": paurashava_of,
                    "key_score": round(uni.score, 3),
                    "margin": round(uni.margin, 3),
                    "back_check": round(uni.back_check, 3),
                    "union_portal": uni.row["url"] if uni.row is not None else None,
                    "upazila_portal": upa.row["url"] if upa.row is not None else None,
                    "district_portal": dis.row["url"] if dis.row is not None else None,
                    "division_portal": div.row["url"] if div.row is not None else None,
                }
            )
    return compose_paurashavas(pd.DataFrame.from_records(records))


# -------------------------------------------------------------- verification
def clean_unit_name(name: str) -> str:
    """A unit's bare name from a title-like string.

    ``১নং বঙ্গসোনাহাট ইউনিয়ন পরিষদ`` gives ``বঙ্গসোনাহাট``; anything after a
    comma is a qualifier, not the name (``শ্রীবরদী, সদর ইউনিয়নের`` gives
    ``শ্রীবরদী``, and ``শেরপুর উপজেলা, বগুড়া`` gives ``শেরপুর``).
    """
    name = _nfc(str(name)).split(",")[0].strip()
    for suffix in _TITLE_SUFFIXES:
        if name.endswith(suffix):
            name = name[: -len(suffix)].strip()
            break
    return re.sub(r"^[০-৯0-9]+\s*(নং)?\s*", "", name).strip()


def portal_title_name(page: str) -> str | None:
    """The unit's name from a National Portal page title, e.g.
    ``হোম | হলদিয়া ইউনিয়ন`` gives ``হলদিয়া``."""
    found = re.search(r"<title[^>]*>(.*?)</title>", page, re.S | re.I)
    if not found:
        return None
    title = html.unescape(found.group(1))
    return clean_unit_name(title.split("|")[-1]) or None


def is_clean_bengali_name(text: str) -> bool:
    """Only Bengali letters and signs, spaces and hyphens: a name, not a sentence."""
    return bool(text) and all(0x0980 <= ord(ch) <= 0x09FF or ch in " -" for ch in text)


#: Zero-width non-joiner and joiner: they change how a word is drawn, not
#: which word it is.
_JOINERS = {0x200C: None, 0x200D: None}


def has_bengali(text: str) -> bool:
    """True if the text contains Bengali letters (U+0980 to U+09FF)."""
    return any(0x0980 <= ord(ch) <= 0x09FF for ch in text)


def _same_name(a: str, b: str) -> bool:
    def squeeze(s: str) -> str:
        s = unicodedata.normalize("NFC", s).translate(_JOINERS)
        return re.sub(r"[\s-]", "", s)
    return squeeze(a) == squeeze(b)


def fetch_portal_titles(
    domains: list[str],
    cache_path: Path | str,
    delay_s: float = 0.5,
    get: Callable[..., requests.Response] = requests.get,
    verify: bool | str = True,
) -> dict[str, str | None]:
    """The title name of each portal, from cache where possible.

    Only a title in Bengali is cached. A portal that was down, or answered
    with an English title or an error page ("Site is not available"), is
    asked again on the next run.

    ``verify`` is passed to ``requests``: True, or the path of a CA bundle
    (see :func:`portal_ca_bundle`). Certificate checking is never switched off.
    """
    cache_path = Path(cache_path)
    cache: dict[str, str] = (
        json.loads(cache_path.read_text(encoding="utf-8")) if cache_path.exists() else {}
    )
    wanted = sorted({d for d in domains if d})
    missing = [d for d in wanted if d not in cache]
    if missing:
        logger.info("checking %d portal pages (%d cached)", len(missing), len(wanted) - len(missing))
    this_run: dict[str, str] = {}
    failures: dict[str, int] = {}
    for i, domain in enumerate(missing, start=1):
        try:
            response = get(
                f"https://{domain}/", headers=USER_AGENT, timeout=(10, 20), verify=verify
            )
            response.raise_for_status()
            # The portal pages are UTF-8. requests assumes ISO-8859-1 when a
            # server sends no charset, which would turn every title to mojibake.
            name = portal_title_name(response.content.decode("utf-8", errors="replace"))
            if name and has_bengali(name):
                cache[domain] = name
            elif name:
                this_run[domain] = name
        except Exception as exc:  # noqa: BLE001 - one dead portal must not stop the stage
            failures[type(exc).__name__] = failures.get(type(exc).__name__, 0) + 1
            logger.debug("%s: %s", domain, exc)
        if i % 25 == 0:
            logger.info("portal pages: %d/%d", i, len(missing))
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            cache_path.write_text(json.dumps(cache, ensure_ascii=False, indent=1), encoding="utf-8")
        time.sleep(delay_s)
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps(cache, ensure_ascii=False, indent=1), encoding="utf-8")
    if failures:
        logger.warning("portal pages not read: %s", failures)
    return {d: cache.get(d, this_run.get(d)) for d in wanted}


def portal_ca_bundle(
    intermediates: list[dict],
    cache_dir: Path | str,
    get: Callable[..., requests.Response] = requests.get,
) -> Path:
    """A CA file of certifi's roots plus pinned intermediate certificates.

    Some portal servers send their own certificate without the intermediate
    that links it to a root. Browsers and Windows fetch the missing link from
    the address inside the certificate; Python does not, and fails the check.
    Adding that intermediate lets the chain be built and verified as usual:
    it must still end at a trusted root, so nothing is trusted that was not
    before. Each download is compared with its pinned SHA-256 and refused if
    it differs.

    Parameters
    ----------
    intermediates
        ``[{"url": ..., "sha256": ...}]``, the fingerprint of the DER encoding.
    cache_dir
        Where the certificates and the bundle are kept.
    """
    cache_dir = Path(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)
    pems = []
    for item in intermediates:
        pinned = str(item["sha256"]).lower()
        local = cache_dir / f"intermediate_{pinned[:16]}.crt"
        if not local.exists():
            response = get(str(item["url"]), timeout=30)
            response.raise_for_status()
            local.write_bytes(response.content)
        raw = local.read_bytes()
        der = ssl.PEM_cert_to_DER_cert(raw.decode("ascii")) if raw.lstrip().startswith(b"-----BEGIN") else raw
        if hashlib.sha256(der).hexdigest() != pinned:
            local.unlink()
            raise ValueError(
                f"certificate from {item['url']} does not match its pinned SHA-256; refusing to trust it"
            )
        pems.append(ssl.DER_cert_to_PEM_cert(der))
    bundle = cache_dir / "portal_ca_bundle.pem"
    roots = Path(certifi.where()).read_text(encoding="utf-8")
    bundle.write_text(roots.rstrip("\n") + "\n" + "".join(pems), encoding="utf-8")
    return bundle


_LEVELS = (
    ("union", "union_bn", "union_portal"),
    ("upazila", "upazila_bn", "upazila_portal"),
    ("district", "district_bn", "district_portal"),
    ("division", "division_bn", "division_portal"),
)


def verify_with_portals(matches: pd.DataFrame, titles: dict[str, str | None]) -> pd.DataFrame:
    """Check each name against its official portal page title.

    Adds ``<level>_check``: ``verified`` (same name), ``portal`` (the portal
    spells it differently and that spelling is used), ``unreachable``,
    ``no Bengali title`` or ``unclear title`` (kept as compiled, unverified:
    the page could not be read, its title is English or an error message, or
    it is more than a bare name), or ``none`` (nothing to check). A differing portal name is used only if it too reads back to
    the GADM spelling; otherwise the portal address is suspect and the
    compiled name is kept.
    """
    out = matches.copy()
    for level, column, portal_column in _LEVELS:
        checks = []
        for i, row in out.iterrows():
            compiled, domain = row[column], row[portal_column]
            if row.get("method") == "paurashava" and level == "union":
                checks.append("composed")
                continue
            if not compiled or not domain:
                checks.append("none")
                continue
            live = titles.get(domain)
            if live is not None:
                live = clean_unit_name(live)      # also cleans titles cached earlier
            if live is None:
                checks.append("unreachable")
            elif not has_bengali(live):
                checks.append("no Bengali title")
            elif not is_clean_bengali_name(live):
                checks.append("unclear title")
            elif _same_name(live, compiled):
                checks.append("verified")
            elif back_check(str(row[level]), live) >= MIN_BACK_CHECK:
                out.at[i, column] = live
                checks.append("portal")
            else:
                checks.append("suspect portal")
        out[f"{level}_check"] = checks
    return out


def bengali_names(
    table: pd.DataFrame,
    gazetteer: Gazetteer,
    cache_dir: Path | str,
    verify: bool = True,
    delay_s: float = 0.5,
    ca_bundle: Path | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Bengali names for every union in the risk table.

    ``ca_bundle`` is the CA file from :func:`portal_ca_bundle`, for portals
    whose servers send an incomplete certificate chain.

    Returns
    -------
    names : pd.DataFrame
        ``gid_union``, ``division_bn``, ``district_bn``, ``upazila_bn``,
        ``union_bn`` — None where no name could be matched with confidence.
    review : pd.DataFrame
        The full match record, for a person to read: method, scores, portal
        addresses and what each portal said.
    """
    review = match_units(table, gazetteer)
    if verify:
        domains = [
            d for column in ("union_portal", "upazila_portal", "district_portal", "division_portal")
            for d in review[column].dropna().tolist()
        ]
        titles = fetch_portal_titles(
            domains, Path(cache_dir) / "portal_titles.json", delay_s,
            verify=str(ca_bundle) if ca_bundle else True,
        )
        review = compose_paurashavas(verify_with_portals(review, titles))
    matched = review["union_bn"].notna().sum()
    logger.info(
        "Bengali union names: %d of %d matched (%s)",
        matched, len(review), review["method"].value_counts().to_dict(),
    )
    names = review[["gid_union", "division_bn", "district_bn", "upazila_bn", "union_bn"]]
    return names, review
