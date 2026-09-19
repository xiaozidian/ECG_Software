---
version: 1
slug: "static-js-report-paper-js"
primary_target: "static/js/report-paper.js"
related_targets: ["static/css/report-paper.css", "static/js/clinical-ui.js", "ecg_core/report_pdf.py"]
---

# Report paper

Scope: final report, report-strip settings, browser print and PDF. Operate / Read; clinicians select evidence and review a literal printable document. User-provided hospital photos pin the output, not patient or institution identities.

Extension 2026-09-19: fastest/slowest selection offers up to 200 actual candidates per RR/NN sequence. Preserve the existing list/detail surface; show rate order, rank, RR and current preview, with 50-row pages and reversible ordering. Defaults are fast-to-slow; no automatic diagnosis, synthetic candidates or changes to source statistics. Selected strips retain seven-second/five-beat behavior.

## Direction contract

THESIS: One legible A4 clinical document; replace the six-tile evidence dashboard with full-width paper strips.

OWN-WORLD: White paper, black Song-style text, thin rules, grayscale ECG measurement grid. Teal controls remain outside the paper.

STORY: Verify examination and analysis, read hourly counts, inspect selected leads and time context, then save and export.

FIRST VIEWPORT: A centered A4 sheet below lead/time controls; compact examination box and two-column statistics above a generous conclusions area. Save/export stay in the existing toolbar.

FORM: User-pinned photos, no seed roll; summary, hourly table, three-strip sheets and one-sheet twelve-lead evidence. Seven seconds expands to five available beats. No fabricated clinical data or calibration.

FINISH: unreviewed and undocumented is unfinished; this build ends with the finish review, the verdict, DESIGN.md, and every shipping raster carrying its provenance

## Implemented candidate selector

Fastest and slowest each retain up to 200 actual candidates from each selected RR/NN sequence; selecting both sequences can therefore show up to 400 candidates in that category. Short recordings show only available candidates. The help text identifies these as single-interval instantaneous rates, not seven-second average rates, and warns that adjacent candidate windows may overlap.

Ranks follow the current filtered and sorted list across 50-row pages. The list footer stays visible within its scroll area and offers previous/next buttons plus direct page selection; changing sort order returns to the first page. The current preview uses a pale teal row and an emphasized time button with `aria-current`, while the separate “入报” checkbox controls report inclusion. Clicking a candidate previews its saved strip settings when already selected, otherwise the new-strip defaults, including the existing seven-second/five-beat window rule. These controls retain the incumbent report list/detail styling and do not introduce global design tokens.

Extension verification attachments are local browser captures: [desktop](../review/rate-candidates/desktop.png), [1280-width](../review/rate-candidates/user-1280.png), [mobile list](../review/rate-candidates/mobile.png), and [mobile detail](../review/rate-candidates/mobile-detail.png). They record verification states, not shipping image assets or clinical validation.
