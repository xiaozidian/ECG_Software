---
version: 1
slug: "static-js-morphology-workbench-js"
primary_target: "static/js/morphology-workbench.js"
related_targets: ["static/css/morphology-workbench.css","templates/index.html"]
---

# Dual-lead morphology peeling

Mode: Operate. Scoped extension of the existing clinician workbench.

## Direction contract

THESIS: Compare the same remaining beat population in two leads, then separate a selected morphology into reversible groups.

OWN-WORLD: Existing clinical white/slate surfaces and teal controls; black density fields retain green–yellow–red frequency encoding.

STORY: Choose leads, box-select either left plot, press 6–9, inspect a right group and explicitly save its template.

FIRST VIEWPORT: Two equal left plots beside four numbered right plots. Selection count, source remainder and per-group totals are visible. Each plot has lead and time axes; group actions and undo sit directly below.

FORM: User-specified paired-lead / four-slot composition; seed key: incumbent-dual-lead-peeling. No identity change.

FINISH: unreviewed and undocumented is unfinished; this build ends with the finish review, the verdict, DESIGN.md, and every shipping raster carrying its provenance

## Implementation and verification — 2026-09-20

This ordinary extension is complete within the template editor. The incumbent [DESIGN.md](../../DESIGN.md) remains the visual authority; this surface note records the built composition and behavior. Global design tokens and `.impeccable/design.json` were preserved.

### Built surface

- Two equally tall source density plots occupy the left column; four groups numbered 6–9 occupy the right column. The source plots have independent lead selectors, initially II and V1. A third selector sets the lead used by all four group plots, initially II.
- Both source plots represent one remaining beat population. A rectangular selection in either plot can be moved with the corresponding 6–9 key or visible “移入” button. Groups are disjoint; each move subtracts the selected sample indices from both source plots across the full source population. The remaining/total badge, plotted counts, selection count, group totals, and status text expose the current state.
- “归还” returns a complete group to the shared remainder; “撤销剥离” restores the preceding grouping state. Groups remain in the current page session. “设为模板” opens the name/family form and explicitly saves the group to the template library. Saved templates survive grouping undo or return. These actions preserve the original heartbeats and their classifications.
- Density fields retain the black background and green → yellow → red logarithmic frequency encoding. The plots align on R at 0 with a ±1 s window. The method text identifies fixed-baseline removal, device-unit amplitude, and absent clinical voltage calibration. Beats without enough edge context remain in population counts and are reported separately from plotted beats.
- The source canvases support pointer selection and cancellation. The expandable percentage-range form provides a keyboard selection path. Buttons have visible focus treatment; status feedback uses a polite live region. Number shortcuts are guarded while inputs, selectors, editable text, or dialogs have focus.
- At widths up to 820 px, the surrounding editor stacks vertically. The two-source/four-group comparison stays paired and the page scrolls to its actions. The final narrow-screen correction lets the heading take its natural height without flex shrink; at widths up to 480 px, its single-column grid puts the remainder badge on a separate row above the lead controls.

Implementation sources: [workbench behavior](../../static/js/morphology-workbench.js), [group partition and shortcuts](../../static/js/morphology-groups.js), [scoped styles](../../static/css/morphology-workbench.css), and [template editor markup](../../templates/index.html).

### Verification and review outcome

The completed implementation handoff records 162 tests passing before the final CSS correction and 15 targeted tests passing after it. Browser verification covered independent source leads, the shared remainder, box selection followed by keys/buttons 6–9, disjoint groups and full-population subtraction in both source plots, a 779-beat template saved and reloaded with original classifications unchanged, undo/return, and the input-focus shortcut guard. A local case with a 101,109-beat source population loaded successfully. The Demo was rebuilt, and the original waveform hash remained unchanged.

The finish review found one material defect: the narrow heading's remainder badge overlapped the lead-control row. The natural-height, non-shrinking heading and separate narrow badge row resolved that defect. The follow-up verdict is **resolved / ship for the scored heading-flow fix**, with no remaining items from that fix review. The final CSS correction was followed by targeted tests and the confirmation captures below; the 162-test suite result predates that correction.

### Screenshot provenance

These existing local browser captures show the rebuilt Demo after the heading correction. They are verification attachments; the density visuals in the product are rendered on Canvas. Dimensions below are PNG pixel dimensions. Each capture is a scrolled view of this surface, with the lower actions recorded separately on mobile.

| Evidence | PNG dimensions | Observed state |
| --- | --- | --- |
| [desktop.png](../review/pause-peeling/desktop.png) | 1429 × 992 | II and V2 source plots, group 7 populated, shared remainder, and adjacent waveform review. |
| [mobile.png](../review/pause-peeling/mobile.png) | 379 × 820 | Remainder badge on its own row, visible lead selectors, paired source plots and groups 6–9. |
| [mobile-controls.png](../review/pause-peeling/mobile-controls.png) | 379 × 820 | Lower group actions, selection status, undo/reload controls, keyboard-range disclosure, and method text reached by scrolling. |
| [user-1280.png](../review/pause-peeling/user-1280.png) | 1269 × 714 | Source/group comparison beside the existing waveform context at the intermediate desktop size. |

The recorded verification applies to this extension and its final heading fix. No additional shipping raster assets were introduced.

## Compact layout and measured loading — 2026-09-21

The user's hospital reference makes waveform review primary and density a supporting panel. This refinement preserves the existing clinical identity, two-source/four-slot topology, color meanings and full-population selection. It does not replace DESIGN.md.

- Desktop left column is now `clamp(320px, 27vw, 440px)` rather than the previous 38vw/620px maximum. The two-source/four-group plot grid is 320px high instead of 580px. At the tested 1366px viewport the density panel measured 368.8px wide; at 1920px it measured 440px. The complete panel was about 590px high with disclosures closed.
- Four 6–9 groups remain simultaneously visible. The repeated per-card template/return footers are replaced by a single explicitly labelled active-group toolbar. Group headers remain at least 28px high; source canvases retain about 133px height on desktop, compact group canvases about 46px, with reduced internal axis padding rather than clipped content.
- Selection state, remainder, boundary exclusions, undo and reload remain visible. Keyboard-range and statistical-method details are disclosed on demand. At a 390px viewport (379px content width), the 285px panel and all four slots fit without horizontal document overflow; the panel becomes about 635px high with wrapped text.
- Full-population density uses bounded 2048-beat NumPy blocks; independent source leads load concurrently. The browser coalesces redraws, reuses per-revision lead results and avoids redundant representative-waveform requests. Thumbnail reads are deduplicated and batched (24 per batch, two in flight) with indexed beat lookup; report-strip cache remains a separate Map.

### Evidence and finish verdict

- Same local 101,109-beat population, with 101,108 drawable beats: previous sequential II/V1 requests took 7.227s + 6.434s; optimized repeated parallel requests took 0.630s. First optimized II request took 0.992s and the following V1 request 0.378s. These are local API timings, not browser end-to-end or cross-device guarantees.
- The same 24 thumbnail ranges took 4.609s as individual requests versus 0.207s in one batch; response values were identical. The source population and all density bins are retained, not replaced by representative sampling.
- Final full regression: **247 passed**. New tests cover all 12 lead derivations against the scalar density oracle, clipping/gates/edge and chunk boundaries, batch/single waveform equivalence, bounded queue concurrency/deduplication/retry, report-cache isolation and read-only compute guards. JavaScript checks, shell syntax and `git diff --check` passed. Layout detector returned `[]`.
- Browser round covered 1366×900 and 1920×1080 desktop views plus 390×844 narrow Demo. A 2,826-beat selection moved via key 7; both source plots decremented, switching V1 to V2 retained the group, the correct template form opened, and return restored the original population. No template or beat edit was saved. Jumping to occurrence 5000 loaded 36 nearby SVG thumbnails without a console error. Final Demo report range preview also rendered with no console errors after cache isolation.
- `docs/demo` was rebuilt from shared sources. Original waveform SHA-256 remains `2896758a256a50670f464a33d280d23b763cb8746236da5e115b2f519899f4ff`. No private data, config or new raster assets were published; no Git push was performed.

Verdict: **pass for this scoped compact-layout/loading refinement**. Observed captures are the browser tool's inline verification images in the current task, not new shipping assets. Windows runtime and physical low-end mobile performance were not exercised; speed figures apply only to the tested local macOS setup.
