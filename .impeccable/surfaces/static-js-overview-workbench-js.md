---
version: 1
slug: "static-js-overview-workbench-js"
primary_target: "static/js/overview-workbench.js"
related_targets: ["templates/index.html","static/css/overview-workbench.css"]
---

# Overview and AF review

Mode: Operate. Extend the incumbent clinical workbench; hospital screenshots specify chart semantics and actions, not a replacement brand.

## Direction contract

THESIS: One shared time selection connects RR, heart rate, ECG and rhythm episodes.

OWN-WORLD: Existing white/slate clinical surfaces, teal controls, blue HR and green RR traces; density alone uses black/green/yellow/red as requested.

STORY: Scan the whole record, select an interval, inspect beats, and save reversible physician edits.

FIRST VIEWPORT: Full-width histogram above four aligned trend/scatter lanes; waveform below; occurrence rail, Lorenz plot and numerical statistics at right. AF editor uses a full-record strip, event table, four quarter-hour lanes and ECG.

FORM: Screenshot-prescribed workbench; seed key: incumbent-hospital-overview. No independent visual-world tournament.

FINISH: unreviewed and undocumented is unfinished; this build ends with the finish review, the verdict, DESIGN.md, and every shipping raster carrying its provenance
