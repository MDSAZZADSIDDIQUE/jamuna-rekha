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
