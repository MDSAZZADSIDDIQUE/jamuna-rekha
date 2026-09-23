"""Assemble the Bengali manuscript into a submission-ready .docx.

    python scripts/build_manuscript.py
    python scripts/build_manuscript.py --final   (final-copy typography)

Reads the Markdown parts in ``docs/paper/`` in filename order and writes
``docs/paper/JamunaRekha_gobeshona_probondho.docx``.

Typography follows the Bangla Academy submission guidance exactly. First
submission (three months after the contract) and the final edited copy have
different sizes and line spacing, so both are produced from the same source:

=========================  ==============  ==============
element                    first copy      final copy
=========================  ==============  ==============
title                      17 pt           16 pt
author name                15 pt           14 pt
abstract                   12 pt           11 pt
body text                  14 pt           12 pt
notes / references         12 pt           11 pt
line spacing               1.5             single
=========================  ==============  ==============

Paper size is A4 in both cases.

The font is Nirmala UI, which ships with Windows and shapes Bengali conjuncts
correctly. ``w:cs`` (complex script) attributes are set alongside the Latin
ones, because Word applies the *complex script* size and font to Bengali runs
and silently ignores the Latin ones — the usual reason a Bengali document
prints at the wrong size.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_LINE_SPACING
from docx.oxml.ns import qn
from docx.shared import Cm, Pt

BENGALI_FONT = "Nirmala UI"
LATIN_FONT = "Times New Roman"

PROFILES = {
    "first": {"title": 17, "author": 15, "abstract": 12, "body": 14, "notes": 12, "spacing": 1.5},
    "final": {"title": 16, "author": 14, "abstract": 11, "body": 12, "notes": 11, "spacing": 1.0},
}

BENGALI_RANGE = re.compile(r"[ঀ-৿]")


def set_run_font(run, size_pt: float, bold: bool = False, italic: bool = False) -> None:
    """Apply font, size and style to a run for both Latin and complex script.

    Word chooses the *complex script* (``w:cs``) font and size for Bengali text.
    Setting only ``run.font.size`` leaves Bengali runs at the document default,
    which is the single most common way a Bengali manuscript comes out at the
    wrong point size without anyone noticing on screen.
    """
    run.font.name = LATIN_FONT if not BENGALI_RANGE.search(run.text) else BENGALI_FONT
    run.font.size = Pt(size_pt)
    run.bold = bold
    run.italic = italic

    rpr = run._element.get_or_add_rPr()
    rfonts = rpr.find(qn("w:rFonts"))
    if rfonts is None:
        rfonts = rpr.makeelement(qn("w:rFonts"), {})
        rpr.append(rfonts)
    rfonts.set(qn("w:ascii"), LATIN_FONT)
    rfonts.set(qn("w:hAnsi"), LATIN_FONT)
    rfonts.set(qn("w:cs"), BENGALI_FONT)

    for tag, attr in (("w:szCs", "w:val"),):
        element = rpr.find(qn(tag))
        if element is None:
            element = rpr.makeelement(qn(tag), {})
            rpr.append(element)
        element.set(qn(attr), str(int(size_pt * 2)))  # half-points

    if bold:
        for tag in ("w:bCs",):
            element = rpr.find(qn(tag))
            if element is None:
                element = rpr.makeelement(qn(tag), {})
                rpr.append(element)
    if italic:
        for tag in ("w:iCs",):
            element = rpr.find(qn(tag))
            if element is None:
                element = rpr.makeelement(qn(tag), {})
                rpr.append(element)


_INLINE = re.compile(r"(\*\*[^*]+\*\*|\*[^*]+\*|`[^`]+`)")


def add_rich_paragraph(doc, text: str, size: float, spacing: float, **kwargs):
    """Add a paragraph, honouring ``**bold**``, ``*italic*`` and ``code``.

    Italic matters here beyond decoration: the Bangla Academy style requires
    book, journal and film titles to be set in italic (bnaka horof).
    """
    paragraph = doc.add_paragraph()
    paragraph.alignment = kwargs.pop("alignment", WD_ALIGN_PARAGRAPH.JUSTIFY)
    fmt = paragraph.paragraph_format
    fmt.line_spacing_rule = WD_LINE_SPACING.MULTIPLE
    fmt.line_spacing = spacing
    fmt.space_after = Pt(kwargs.pop("space_after", 6))
    if "space_before" in kwargs:
        fmt.space_before = Pt(kwargs.pop("space_before"))

    for piece in _INLINE.split(text):
        if not piece:
            continue
        if piece.startswith("**") and piece.endswith("**"):
            run = paragraph.add_run(piece[2:-2])
            set_run_font(run, size, bold=True)
        elif piece.startswith("*") and piece.endswith("*"):
            run = paragraph.add_run(piece[1:-1])
            set_run_font(run, size, italic=True)
        elif piece.startswith("`") and piece.endswith("`"):
            run = paragraph.add_run(piece[1:-1])
            set_run_font(run, size)
        else:
            run = paragraph.add_run(piece)
            set_run_font(run, size)
    return paragraph


def add_markdown_table(doc, rows: list[str], size: float) -> None:
    """Render a pipe-delimited Markdown table as a Word table."""
    parsed = []
    for row in rows:
        if re.match(r"^\s*\|[\s:|-]+\|\s*$", row):
            continue
        cells = [c.strip() for c in row.strip().strip("|").split("|")]
        parsed.append(cells)
    if not parsed:
        return

    width = max(len(r) for r in parsed)
    table = doc.add_table(rows=len(parsed), cols=width)
    table.style = "Table Grid"
    for i, cells in enumerate(parsed):
        for j in range(width):
            cell = table.cell(i, j)
            cell.text = ""
            paragraph = cell.paragraphs[0]
            text = cells[j] if j < len(cells) else ""
            for piece in _INLINE.split(text):
                if not piece:
                    continue
                if piece.startswith("**") and piece.endswith("**"):
                    run = paragraph.add_run(piece[2:-2])
                    set_run_font(run, size - 2, bold=True)
                elif piece.startswith("*") and piece.endswith("*"):
                    run = paragraph.add_run(piece[1:-1])
                    set_run_font(run, size - 2, italic=True)
                else:
                    run = paragraph.add_run(piece)
                    set_run_font(run, size - 2, bold=(i == 0))


def build(parts: list[Path], out_path: Path, profile: dict, figures_dir: Path) -> Path:
    doc = Document()

    section = doc.sections[0]
    section.page_width = Cm(21.0)     # A4
    section.page_height = Cm(29.7)
    for attr in ("left_margin", "right_margin"):
        setattr(section, attr, Cm(2.5))
    for attr in ("top_margin", "bottom_margin"):
        setattr(section, attr, Cm(2.5))

    spacing = profile["spacing"]
    seen_title = False
    seen_author = False
    in_references = False
    in_abstract = False
    table_buffer: list[str] = []

    # Markdown paragraph semantics: consecutive non-blank lines are ONE
    # paragraph, and a blank line ends it. The source is hard-wrapped at about
    # 78 columns for readable diffs, so emitting a Word paragraph per source
    # line would turn every wrapped line into its own block — 668 paragraphs
    # for a 7,000-word document, each with its own space-after, which justifies
    # and breaks catastrophically in print.
    text_buffer: list[str] = []

    def flush_text():
        nonlocal text_buffer
        if text_buffer:
            joined = " ".join(text_buffer)
            size = profile["abstract"] if in_abstract else profile["body"]
            if in_references:
                paragraph = add_rich_paragraph(doc, joined, profile["notes"], 1.0, space_after=4)
                paragraph.paragraph_format.left_indent = Cm(0.8)
                paragraph.paragraph_format.first_line_indent = Cm(-0.8)
            else:
                add_rich_paragraph(doc, joined, size, spacing)
            text_buffer = []

    def flush_table():
        nonlocal table_buffer
        if table_buffer:
            flush_text()
            add_markdown_table(doc, table_buffer, profile["body"])
            doc.add_paragraph()
            table_buffer = []

    for part in parts:
        for raw in part.read_text(encoding="utf-8").splitlines():
            line = raw.rstrip()

            if line.strip().startswith("|"):
                table_buffer.append(line)
                continue
            flush_table()

            # A blank line ends the current paragraph; a rule is ignored.
            if not line.strip() or line.strip() == "---":
                flush_text()
                continue

            if line.startswith("# "):
                flush_text()
                if seen_title:
                    continue
                add_rich_paragraph(
                    doc, line[2:].strip(), profile["title"],
                    spacing, alignment=WD_ALIGN_PARAGRAPH.CENTER, space_after=10,
                )
                doc.paragraphs[-1].runs[0].bold = True
                for run in doc.paragraphs[-1].runs:
                    set_run_font(run, profile["title"], bold=True)
                seen_title = True
                continue

            # The first bold-only line after the title is the author byline,
            # which the Bangla Academy guidance sizes separately from the body.
            if seen_title and not seen_author and re.fullmatch(r"\*\*.+\*\*", line.strip()):
                add_rich_paragraph(
                    doc, line.strip()[2:-2], profile["author"], spacing,
                    alignment=WD_ALIGN_PARAGRAPH.CENTER, space_after=4,
                )
                for run in doc.paragraphs[-1].runs:
                    set_run_font(run, profile["author"], bold=True)
                seen_author = True
                continue

            if line.startswith("## "):
                flush_text()
                heading = line[3:].strip()
                in_references = "তথ্যসূত্র" in heading or "গ্রন্থপঞ্জি" in heading
                in_abstract = "সারসংক্ষেপ" in heading or heading.startswith("Abstract")
                add_rich_paragraph(
                    doc, heading, profile["body"] + 1, spacing,
                    alignment=WD_ALIGN_PARAGRAPH.LEFT, space_before=14, space_after=6,
                )
                for run in doc.paragraphs[-1].runs:
                    set_run_font(run, profile["body"] + 1, bold=True)
                continue

            if line.startswith("### "):
                flush_text()
                add_rich_paragraph(
                    doc, line[4:].strip(), profile["body"], spacing,
                    alignment=WD_ALIGN_PARAGRAPH.LEFT, space_before=10, space_after=4,
                )
                for run in doc.paragraphs[-1].runs:
                    set_run_font(run, profile["body"], bold=True)
                continue

            # A figure directive: ![caption](filename)
            image = re.match(r"^!\[(.*?)\]\((.*?)\)$", line.strip())
            if image:
                flush_text()
                caption, filename = image.group(1), image.group(2)
                path = figures_dir / filename
                if path.exists():
                    doc.add_picture(str(path), width=Cm(15.5))
                    doc.paragraphs[-1].alignment = WD_ALIGN_PARAGRAPH.CENTER
                add_rich_paragraph(
                    doc, caption, profile["notes"], 1.0,
                    alignment=WD_ALIGN_PARAGRAPH.CENTER, space_after=10,
                )
                continue

            if line.startswith("**মুখশব্দ") or line.startswith("**Keywords"):
                flush_text()
                add_rich_paragraph(doc, line, profile["abstract"], spacing, space_after=10)
                continue

            # Each reference entry is its own hanging-indent block, so a new
            # one starts wherever the sidenote key appears. Continuation lines
            # of the same entry keep accumulating.
            if in_references and "।।" in line:
                flush_text()

            text_buffer.append(line.strip())

    flush_text()
    flush_table()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    doc.save(out_path)
    return out_path


def count_words(parts: list[Path]) -> int:
    """Word count over the whole manuscript, Markdown syntax removed.

    The Bangla Academy limit of 8 000 words covers *everything* — title,
    abstract, keywords, body, notes, references and captions — so this counts
    the same way.
    """
    total = 0
    for part in parts:
        text = part.read_text(encoding="utf-8")
        text = re.sub(r"!\[.*?\]\(.*?\)", " ", text)
        text = re.sub(r"[#*`|>_\-]", " ", text)
        total += len([w for w in text.split() if w.strip()])
    return total


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--final", action="store_true", help="final-copy typography")
    parser.add_argument("--paper-dir", default="docs/paper")
    parser.add_argument("--figures-dir", default="outputs/figures")
    args = parser.parse_args()

    repo = Path(__file__).resolve().parents[1]
    paper_dir = repo / args.paper_dir
    # Only numbered parts are manuscript sections; README.md and any scratch
    # notes living alongside them are not, and must not be bound into the
    # submitted document or counted against the 8,000-word limit.
    parts = sorted(p for p in paper_dir.glob("*.md") if re.match(r"^\d", p.name))
    if not parts:
        print(f"no manuscript parts in {paper_dir}", file=sys.stderr)
        return 1

    profile = PROFILES["final" if args.final else "first"]
    suffix = "final" if args.final else "first"
    out = paper_dir / f"JamunaRekha_gobeshona_probondho_{suffix}.docx"
    build(parts, out, profile, repo / args.figures_dir)

    words = count_words(parts)
    print(f"parts     : {', '.join(p.name for p in parts)}")
    print(f"word count: {words}  (Bangla Academy limit: 5000-8000, all inclusive)")
    if words > 8000:
        print(f"  OVER by {words - 8000} words")
    elif words < 5000:
        print(f"  UNDER by {5000 - words} words")
    else:
        print("  within limit")
    print(f"wrote     : {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
