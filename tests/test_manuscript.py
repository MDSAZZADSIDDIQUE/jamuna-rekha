"""The manuscript builder: typography and paragraph structure.

These checks exist because both classes of bug here are invisible on screen
and obvious in print, and the document is a submission with fixed formatting
requirements.

*Typography.* Word applies the **complex script** font and size to Bengali
runs and ignores the Latin ones. Setting only ``run.font.size`` produces a
document that looks right in python-docx and prints at the wrong point size.

*Paragraphs.* The Markdown source is hard-wrapped for readable diffs. Emitting
one Word paragraph per source line turns every wrapped line into its own
block — which justifies and breaks wrongly, and inflated a 7,000-word document
to 668 paragraphs before it was caught.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

from docx import Document
from docx.oxml.ns import qn

REPO = Path(__file__).resolve().parents[1]

_spec = importlib.util.spec_from_file_location(
    "build_manuscript", REPO / "scripts" / "build_manuscript.py"
)
build_manuscript = importlib.util.module_from_spec(_spec)
sys.modules["build_manuscript"] = build_manuscript
_spec.loader.exec_module(build_manuscript)


SAMPLE = """# একটি শিরোনাম

**লেখকের নাম**

## সারসংক্ষেপ

এই অনুচ্ছেদটি উৎসে তিনটি লাইনে ভাগ করা,
কিন্তু ওয়ার্ড নথিতে এটি একটিমাত্র
অনুচ্ছেদ হওয়া উচিত।

**মুখশব্দ:** ক, খ, গ

## ১. ভূমিকা

প্রথম অনুচ্ছেদ, দুই লাইনে
লেখা হয়েছে।

দ্বিতীয় অনুচ্ছেদ আলাদা।

| ক | খ |
|---|---|
| ১ | ২ |

## তথ্যসূত্র ও গ্রন্থপঞ্জি

অটসু ১৯৭৯।। Nobuyuki Otsu, ‘A Threshold Selection Method’,
*IEEE Transactions*, vol. 9, pp. 62–66।

জু ২০০৬।। Hanqiu Xu, ‘Modification of NDWI’, *IJRS*, vol. 27।
"""


@pytest.fixture
def built(tmp_path):
    source = tmp_path / "01_sample.md"
    source.write_text(SAMPLE, encoding="utf-8")
    out = tmp_path / "out.docx"
    build_manuscript.build(
        [source], out, build_manuscript.PROFILES["first"], tmp_path
    )
    return Document(out)


def _texts(doc):
    return [p.text for p in doc.paragraphs if p.text.strip()]


# ------------------------------------------------------------- paragraphs
def test_wrapped_lines_join_into_one_paragraph(built):
    """Three source lines, one Word paragraph — blank lines are the separator."""
    joined = [t for t in _texts(built) if t.startswith("এই অনুচ্ছেদটি")]
    assert len(joined) == 1
    assert "একটিমাত্র" in joined[0]
    assert "অনুচ্ছেদ হওয়া উচিত।" in joined[0]


def test_blank_line_starts_a_new_paragraph(built):
    texts = _texts(built)
    assert any(t.startswith("প্রথম অনুচ্ছেদ") for t in texts)
    assert any(t.startswith("দ্বিতীয় অনুচ্ছেদ") for t in texts)
    first = next(t for t in texts if t.startswith("প্রথম"))
    assert "দ্বিতীয়" not in first


def test_document_is_not_one_paragraph_per_source_line(built):
    """The regression guard: 7 prose lines must not become 7 paragraphs."""
    prose = [
        t for t in _texts(built)
        if not t.startswith(("একটি শিরোনাম", "লেখকের", "সারসংক্ষেপ", "মুখশব্দ", "১.", "তথ্যসূত্র"))
    ]
    assert len(prose) <= 6


# -------------------------------------------------------------- typography
@pytest.mark.parametrize(
    "index,expected_pt",
    [(0, 17), (1, 15), (4, 12)],   # title, author byline, abstract body
)
def test_element_sizes_match_the_submission_spec(built, index, expected_pt):
    paragraph = [p for p in built.paragraphs if p.text.strip() and p.runs][index]
    assert paragraph.runs[0].font.size.pt == expected_pt


def test_complex_script_attributes_are_set(built):
    """Bengali takes w:szCs and w:rFonts/w:cs, not the Latin size and font."""
    paragraph = [p for p in built.paragraphs if p.text.strip() and p.runs][0]
    rpr = paragraph.runs[0]._element.rPr
    assert rpr.find(qn("w:szCs")) is not None
    assert int(rpr.find(qn("w:szCs")).get(qn("w:val"))) == 34   # 17 pt in half-points
    assert rpr.find(qn("w:rFonts")).get(qn("w:cs")) == build_manuscript.BENGALI_FONT


def test_final_profile_uses_the_smaller_typography(tmp_path):
    source = tmp_path / "01_sample.md"
    source.write_text(SAMPLE, encoding="utf-8")
    out = tmp_path / "final.docx"
    build_manuscript.build(
        [source], out, build_manuscript.PROFILES["final"], tmp_path
    )
    doc = Document(out)
    paragraphs = [p for p in doc.paragraphs if p.text.strip() and p.runs]
    assert paragraphs[0].runs[0].font.size.pt == 16
    assert paragraphs[4].paragraph_format.line_spacing == 1.0


def test_page_is_a4(built):
    section = built.sections[0]
    assert round(section.page_width.cm, 1) == 21.0
    assert round(section.page_height.cm, 1) == 29.7


# --------------------------------------------------------------- structure
def test_tables_are_rendered_as_tables(built):
    assert len(built.tables) == 1
    assert built.tables[0].cell(0, 0).text.strip() == "ক"


def test_each_reference_entry_is_its_own_hanging_indent_block(built):
    """Entries are split on the ।। sidenote key, and continuation lines join."""
    refs = [p for p in built.paragraphs if "।।" in p.text]
    assert len(refs) == 2
    assert "IEEE Transactions" in refs[0].text      # continuation line joined
    assert refs[0].paragraph_format.first_line_indent.cm < 0   # hanging indent


def test_unnumbered_files_are_excluded_from_the_word_count():
    """README.md and scratch notes must not count against the 8,000-word limit."""
    parts = sorted(
        p for p in (REPO / "docs" / "paper").glob("*.md") if p.name[0].isdigit()
    )
    assert parts, "manuscript parts not found"
    assert all(p.name[0].isdigit() for p in parts)
    assert not any(p.name == "README.md" for p in parts)


def test_real_manuscript_is_inside_the_word_limit():
    parts = sorted(
        p for p in (REPO / "docs" / "paper").glob("*.md") if p.name[0].isdigit()
    )
    words = build_manuscript.count_words(parts)
    assert 5000 <= words <= 8000, f"manuscript is {words} words"
