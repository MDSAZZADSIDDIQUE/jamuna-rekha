# গবেষণা-প্রবন্ধ / The manuscript

Source for the Bengali research paper submitted under the Bangla Academy
three-month research fellowship (third phase), entry 10.

> **Note on the build.** `build_manuscript.py` reads the `*.md` files whose
> names begin with a digit, **in filename order** — so the numeric prefixes are
> the running order of the paper, not decoration. Files without a numeric
> prefix (this README, any scratch notes) are skipped, so they are neither
> bound into the document nor counted against the word limit.

## Parts

| file | sections |
|---|---|
| `01_front_matter.md` | title, byline, Bengali abstract, English abstract, keywords |
| `02_body_part1.md` | ১ ভূমিকা · ২ উদ্দেশ্য, সমস্যা ও প্রাসঙ্গিকতা |
| `03_body_part2.md` | ৩ সাহিত্য-পর্যালোচনা · ৪ গবেষণাপদ্ধতি ও ক্ষেত্রপরিচয় |
| `04_body_part3.md` | ৫.১–৫.৭ মূল আলোচনা ও বিশ্লেষণ |
| `04z_body_part4.md` | ৫.৮ সীমাবদ্ধতা · ৬ সিদ্ধান্ত ও উপসংহার |
| `05_notes.md` | টীকা ও ব্যাখ্যা (includes the required AI-use disclosure) |
| `06_references.md` | তথ্যসূত্র ও গ্রন্থপঞ্জি |

## Building

```bash
python scripts/build_manuscript.py            # first submission typography
python scripts/build_manuscript.py --final    # final edited copy typography
```

Both write a `.docx` next to these files and print the running word count.

## The two typographies

The Bangla Academy guidance specifies different settings for the copy
submitted three months after the contract and for the final edited copy. Both
are produced from this same source:

| element | first copy | final copy |
|---|---|---|
| শিরোনাম | ১৭ পয়েন্ট | ১৬ পয়েন্ট |
| প্রাবন্ধিকের নাম | ১৫ পয়েন্ট | ১৪ পয়েন্ট |
| সারসংক্ষেপ | ১২ পয়েন্ট | ১১ পয়েন্ট |
| মূল পাঠ | ১৪ পয়েন্ট | ১২ পয়েন্ট |
| টীকা, তথ্যসূত্র, গ্রন্থপঞ্জি | ১২ পয়েন্ট | ১১ পয়েন্ট |
| লাইন স্পেস | ১.৫ | সিঙ্গেল |
| কাগজ | A4 | A4 |
| বাঁধাই | স্পাইরাল, ২ সেট | এক কোণায় স্টাপলড, ২ সেট |

The font is **Nirmala UI**, set through Word's *complex script* attributes
(`w:cs`, `w:szCs`). Setting only the Latin font and size leaves Bengali runs at
the document default — the usual reason a Bengali manuscript prints at the
wrong point size without anyone noticing on screen.

## Word limit

Total must be **5,000–8,000 words**, and that ceiling covers everything:
title, abstract, keywords, body, notes, references and captions. The build
script counts on the same basis and warns if the manuscript falls outside it.

## Numbers in the text

No figure in the results section is typed by hand. `scripts/report_results.py`
renders the comparison, per-horizon and compute tables straight from the JSON
that the pipeline runs actually wrote, with Bengali numerals, ready to paste.
Re-running the pipeline regenerates those tables rather than inviting a manual
edit that silently disagrees with the data.

## Figures

Figure directives are written as `![caption](filename.png)` and resolved
against `outputs/figures/`. Figure text is English, captions are Bengali:
matplotlib does not perform Indic complex-script shaping, so Bengali set
*inside* a figure renders with mis-ordered conjuncts — subtle on screen and
obvious in print.

## AI-use disclosure

The Bangla Academy stylesheet (§৪.১) does not accept text written by AI as
research work, but does permit AI assistance for **data analysis and for
producing figures, diagrams and conceptual models**, provided the use is
disclosed. Note ৬ in `05_notes.md` carries that disclosure. The prose here is
a working draft: it must be rewritten in the author's own voice before
submission.
