"""Stage 4d: Bengali names for the unions in the DDM table.

The failure that matters is not a missing name — that union is shown in
English — but a wrong one: a union shown under another union's name. These
tests pin the matching rules that prevent it: romanisation variants match,
the wrong candidate is refused even when it is the best on offer, and the
official portal's spelling wins over the compilation's.

No network access: the compilation and the portals are stood in for.
"""

from __future__ import annotations

import unicodedata

import pandas as pd
import pytest

from jamunarekha.risk.names_bn import (
    Gazetteer,
    back_check,
    bengali_key,
    best_match,
    fetch_portal_titles,
    latin_key,
    match_units,
    portal_title_name,
    verify_with_portals,
)


def nfc(text):
    """Compare Bengali text in one normal form: literals may differ from it."""
    return None if text is None else unicodedata.normalize("NFC", text)


def _candidates(*pairs: tuple[str, str]) -> pd.DataFrame:
    return pd.DataFrame(
        [{"id": str(i), "name": name, "bn_name": bn, "url": f"u{i}.example.gov.bd"}
         for i, (name, bn) in enumerate(pairs)]
    )


# ----------------------------------------------------------------- skeletons
@pytest.mark.parametrize(
    "gadm,compiled",
    [
        ("Raumari", "Rowmari"),
        ("Haldia", "Holdia"),
        ("Mohanganj", "Mohongonj"),
        ("Fulchhari", "Phulchari"),
        ("CharBhurungamari", "Char Bhurungamari"),
        ("Bogra", "Bogura"),
    ],
)
def test_romanisation_variants_share_a_skeleton(gadm, compiled):
    assert latin_key(gadm) == latin_key(compiled)


def test_different_names_do_not():
    assert latin_key("Birhati") != latin_key("Gabshara")


@pytest.mark.parametrize(
    "english,bengali",
    [
        ("Haldia", "হলদিয়া"),
        ("Uria", "উড়িয়া"),              # nukta letters
        ("Bidyananda", "বিদ্যানন্দ"),     # ya-phala is not a j
        ("Bangasonahat", "বঙ্গসোনাহাট"),  # ঙ reads ng
        ("Bhangni", "ভাংনী"),             # so does ং
    ],
)
def test_bengali_names_read_back_to_their_english_spelling(english, bengali):
    assert bengali_key(bengali) == latin_key(english)
    assert back_check(english, bengali) == 1.0


# ------------------------------------------------------------------ matching
def test_exact_match_across_romanisations():
    match = best_match("Haldia", _candidates(("Holdia", "হলদিয়া"), ("Varotkhali", "ভরতখালী")))
    assert match.method == "exact"
    assert match.row["bn_name"] == "হলদিয়া"


def test_union_named_after_the_upazila_seat_matches_its_sadar_entry():
    match = best_match("Kazipur", _candidates(("Kazipur Sadar", "কাজিপুর সদর"), ("Tekani", "তেকানী")))
    assert match.method == "sadar"
    assert match.row["name"] == "Kazipur Sadar"


def test_close_but_not_exact_spelling_is_accepted_when_clearly_best():
    match = best_match("UllahPara", _candidates(("Ullapara", "উল্লাপাড়া"), ("Mohonpur", "মোহনপুর")))
    assert match.method == "fuzzy"
    assert match.row["name"] == "Ullapara"


def test_best_candidate_is_refused_when_it_is_a_different_union():
    """Birhati is not in the list. The nearest name on offer must not be
    printed in its place."""
    candidates = _candidates(("Gabshara", "গাবসারা"), ("Nikrail", "নিকরাইল"), ("Gobindashi", "গোবিন্দাসী"))
    match = best_match("Birhati", candidates)
    assert match.row is None
    assert match.method == "rejected"


def test_two_candidates_with_the_same_skeleton_are_ambiguous():
    match = best_match("Haldia", _candidates(("Holdia", "হলদিয়া"), ("Haldiya", "হলদিয়া")))
    assert match.row is None
    assert match.method == "ambiguous"


def test_an_exact_english_match_with_the_wrong_bengali_name_is_refused():
    """The compilation pairs an English and a Bengali name; if the two do not
    agree, the entry itself is wrong and its Bengali name must not be used."""
    match = best_match("Haldia", _candidates(("Holdia", "নিকরাইল")))
    assert match.row is None
    assert match.method == "rejected"


def _gazetteer() -> Gazetteer:
    return Gazetteer(
        divisions=pd.DataFrame([{"id": "2", "name": "Rajshahi", "bn_name": "রাজশাহী", "url": "www.rajshahidiv.gov.bd"}]),
        districts=pd.DataFrame(
            [{"id": "30", "division_id": "2", "name": "Bogura", "bn_name": "বগুড়া",
              "lat": "", "lon": "", "url": "www.bogra.gov.bd"}]
        ),
        upazilas=pd.DataFrame(
            [{"id": "300", "district_id": "30", "name": "Sariakandi", "bn_name": "সারিয়াকান্দি",
              "url": "sariakandi.bogra.gov.bd"}]
        ),
        unions=pd.DataFrame(
            [
                {"id": "1", "upazilla_id": "300", "name": "Chaluabari", "bn_name": "চালুয়াবাড়ী",
                 "url": "chaluabariup.bogra.gov.bd"},
                {"id": "2", "upazilla_id": "300", "name": "Kornibari", "bn_name": "কর্ণিবাড়ী",
                 "url": "kornibariup.bogra.gov.bd"},
            ]
        ),
    )


def _table(*unions: str) -> pd.DataFrame:
    return pd.DataFrame(
        [{"division": "Rajshahi", "district": "Bogra", "upazila": "Sariakandi", "union": u,
          "gid_union": f"BGD.5.1.9.{i}_1"} for i, u in enumerate(unions)]
    )


def test_units_are_matched_down_the_hierarchy_under_the_old_district_spelling():
    out = match_units(_table("Chaluabari", "Birhati"), _gazetteer()).set_index("union")
    assert out.loc["Chaluabari", "district_bn"] == "বগুড়া"
    assert out.loc["Chaluabari", "upazila_bn"] == "সারিয়াকান্দি"
    assert out.loc["Chaluabari", "union_bn"] == "চালুয়াবাড়ী"
    assert out.loc["Chaluabari", "union_portal"] == "chaluabariup.bogra.gov.bd"
    assert out.loc["Birhati", "union_bn"] is None or pd.isna(out.loc["Birhati", "union_bn"])


def test_municipalities_are_named_from_the_unit_they_are_named_after():
    out = match_units(_table("SariakandiPaurashava", "Paurashava", "ElsewherePaurashava"), _gazetteer())
    out = out.set_index("union")
    assert nfc(out.loc["SariakandiPaurashava", "union_bn"]) == nfc("সারিয়াকান্দি পৌরসভা")
    assert nfc(out.loc["Paurashava", "union_bn"]) == nfc("পৌরসভা")     # GADM gives no name either
    assert pd.isna(out.loc["ElsewherePaurashava", "union_bn"])


# -------------------------------------------------------------- verification
@pytest.mark.parametrize(
    "title,name",
    [
        ("<title>হোম | হলদিয়া ইউনিয়ন</title>", "হলদিয়া"),
        ("<title>\n হোম | ১নং বঙ্গসোনাহাট ইউনিয়ন পরিষদ </title>", "বঙ্গসোনাহাট"),
        ("<title>হোম | উলিপুর উপজেলা</title>", "উলিপুর"),
        ("<title>হোম | কুড়িগ্রাম জেলা</title>", "কুড়িগ্রাম"),
        ("<title>হোম | শ্রীবরদী, সদর ইউনিয়নের</title>", "শ্রীবরদী"),    # qualifier after a comma
        ("<title>হোম | শেরপুর উপজেলা, বগুড়া</title>", "শেরপুর"),
        ("<html>no title here</html>", None),
    ],
)
def test_portal_title_gives_the_units_own_name(title, name):
    assert portal_title_name(title) == nfc(name)


def _one_union(compiled: str, english: str = "Chaluabari") -> pd.DataFrame:
    return pd.DataFrame(
        [{"gid_union": "g", "division": "Rajshahi", "district": "Bogra", "upazila": "Sariakandi",
          "union": english, "method": "exact", "paurashava_of": None,
          "division_bn": None, "district_bn": None, "upazila_bn": None, "union_bn": compiled,
          "union_portal": "x.gov.bd", "upazila_portal": None, "district_portal": None,
          "division_portal": None}]
    )


def test_portal_confirms_the_compiled_name():
    out = verify_with_portals(_one_union("চালুয়াবাড়ী"), {"x.gov.bd": "চালুয়াবাড়ী"})
    assert out["union_check"].iloc[0] == "verified"


def test_portal_spelling_wins_when_it_differs():
    out = verify_with_portals(_one_union("চালুয়াবারী"), {"x.gov.bd": "চালুয়াবাড়ী"})
    assert out["union_check"].iloc[0] == "portal"
    assert out["union_bn"].iloc[0] == "চালুয়াবাড়ী"


def test_a_portal_naming_some_other_place_is_not_trusted():
    out = verify_with_portals(_one_union("চালুয়াবাড়ী"), {"x.gov.bd": "নিকরাইল"})
    assert out["union_check"].iloc[0] == "suspect portal"
    assert out["union_bn"].iloc[0] == "চালুয়াবাড়ী"


def test_an_unreachable_portal_leaves_the_compiled_name_marked_unverified():
    out = verify_with_portals(_one_union("চালুয়াবাড়ী"), {"x.gov.bd": None})
    assert out["union_check"].iloc[0] == "unreachable"
    assert out["union_bn"].iloc[0] == "চালুয়াবাড়ী"


class _Response:
    def __init__(self, body: str | None):
        self.body = body

    def raise_for_status(self):
        if self.body is None:
            raise OSError("portal down")

    @property
    def content(self) -> bytes:
        return (self.body or "").encode("utf-8")


def test_portal_pages_are_fetched_once_and_failures_retried(tmp_path):
    calls: list[str] = []
    pages = {"https://up.gov.bd/": "<title>হোম | হলদিয়া ইউনিয়ন</title>", "https://down.gov.bd/": None}

    def fake_get(url, **_):
        calls.append(url)
        return _Response(pages[url])

    cache = tmp_path / "titles.json"
    first = fetch_portal_titles(["up.gov.bd", "down.gov.bd"], cache, delay_s=0.0, get=fake_get)
    assert first == {"up.gov.bd": nfc("হলদিয়া"), "down.gov.bd": None}
    calls.clear()
    fetch_portal_titles(["up.gov.bd", "down.gov.bd"], cache, delay_s=0.0, get=fake_get)
    assert calls == ["https://down.gov.bd/"]     # the good page came from cache


def test_bengali_name_is_a_second_route_to_an_exact_match():
    """The compilation romanises মেছড়া as "Mesra"; GADM's "Mechhra" reads
    straight off the Bengali, so the match is exact after all."""
    match = best_match("Mechhra", _candidates(("Mesra", "মেছড়া"), ("Songacha", "ছোনগাছা")))
    assert match.method == "exact-bengali"
    assert match.row["name"] == "Mesra"


def test_an_english_or_error_title_does_not_count_as_the_portals_spelling():
    for title in ("Jatrapur Union", "Site is not available: x.gov.bd"):
        out = verify_with_portals(_one_union("চালুয়াবাড়ী"), {"x.gov.bd": title})
        assert out["union_check"].iloc[0] == "no Bengali title"
        assert out["union_bn"].iloc[0] == "চালুয়াবাড়ী"


def test_english_titles_are_not_cached(tmp_path):
    calls: list[str] = []

    def fake_get(url, **_):
        calls.append(url)
        return _Response("<title>Home | Jatrapur Union</title>")

    cache = tmp_path / "titles.json"
    assert fetch_portal_titles(["en.gov.bd"], cache, delay_s=0.0, get=fake_get) == {"en.gov.bd": "Home | Jatrapur Union".split("|")[-1].strip()}
    fetch_portal_titles(["en.gov.bd"], cache, delay_s=0.0, get=fake_get)
    assert len(calls) == 2          # asked again: it may be in Bengali next time


def _a_real_certificate() -> bytes:
    """Any certificate will do; take one from certifi's bundle, as DER."""
    import re
    import ssl

    import certifi

    pem = re.search(
        r"-----BEGIN CERTIFICATE-----.+?-----END CERTIFICATE-----",
        open(certifi.where(), encoding="utf-8").read(), re.S,
    ).group(0)
    return ssl.PEM_cert_to_DER_cert(pem)


class _Bytes:
    def __init__(self, content: bytes):
        self.content = content

    def raise_for_status(self):
        pass


def test_pinned_intermediate_is_added_to_the_trusted_bundle(tmp_path):
    import hashlib

    from jamunarekha.risk.names_bn import portal_ca_bundle

    der = _a_real_certificate()
    item = {"url": "http://ca.example/int.crt", "sha256": hashlib.sha256(der).hexdigest()}
    bundle = portal_ca_bundle([item], tmp_path, get=lambda url, **_: _Bytes(der))
    text = bundle.read_text(encoding="utf-8")
    assert text.count("BEGIN CERTIFICATE") > 100          # certifi's roots are still there
    import ssl
    assert ssl.DER_cert_to_PEM_cert(der).strip() in text  # and the intermediate is added


def test_an_intermediate_that_does_not_match_its_pin_is_refused(tmp_path):
    from jamunarekha.risk.names_bn import portal_ca_bundle

    der = _a_real_certificate()
    item = {"url": "http://ca.example/int.crt", "sha256": "0" * 64}
    with pytest.raises(ValueError, match="pinned SHA-256"):
        portal_ca_bundle([item], tmp_path, get=lambda url, **_: _Bytes(der))
    assert not list(tmp_path.glob("intermediate_*.crt"))  # the bad download is not kept


def test_compiled_names_are_cleaned_like_titles():
    from jamunarekha.risk.names_bn import clean_unit_name

    assert clean_unit_name("১গোপালনগর") == nfc("গোপালনগর")          # stray ward number
    assert clean_unit_name("দরবস্ত ইউনিয়ন") == nfc("দরবস্ত")
    assert clean_unit_name("কাজিপুর সদর") == nfc("কাজিপুর সদর")      # সদর is part of the name


def test_a_portal_name_that_is_more_than_a_name_is_not_used():
    out = verify_with_portals(_one_union("চালুয়াবাড়ী"), {"x.gov.bd": "চালুয়াবাড়ী (নতুন) 2024"})
    assert out["union_check"].iloc[0] == "unclear title"
    assert out["union_bn"].iloc[0] == "চালুয়াবাড়ী"
