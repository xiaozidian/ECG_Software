---
version: 1
slug: "static-js-report-paper-js"
primary_target: "static/js/report-paper.js"
related_targets: ["static/css/report-paper.css", "static/js/clinical-ui.js", "ecg_core/report_pdf.py"]
---

# Report paper

Scope: final report, report-strip settings, browser print and PDF. Operate / Read; clinicians select evidence and review a literal printable document. User-provided hospital photos pin the output, not patient or institution identities.

## Direction contract

THESIS: One legible A4 clinical document; replace the six-tile evidence dashboard with full-width paper strips.

OWN-WORLD: White paper, black Song-style text, thin rules, grayscale ECG measurement grid. Teal controls remain outside the paper.

STORY: Verify examination and analysis, read hourly counts, inspect selected leads and time context, then save and export.

FIRST VIEWPORT: A centered A4 sheet below lead/time controls; compact examination box and two-column statistics above a generous conclusions area. Save/export stay in the existing toolbar.

FORM: User-pinned photos, no seed roll; summary, hourly table, three-strip sheets and one-sheet twelve-lead evidence. Seven seconds expands to five available beats. No fabricated clinical data or calibration.

FINISH: unreviewed and undocumented is unfinished; this build ends with the finish review, the verdict, DESIGN.md, and every shipping raster carrying its provenance
