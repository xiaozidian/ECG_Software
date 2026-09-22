---
version: 1
slug: "static-js-clinical-review-tools-js"
primary_target: "static/js/clinical-review-tools.js"
related_targets: ["static/js/clinical-ui.js", "static/js/report-range-editor.js", "static/js/hrv-report.js", "static/css/clinical-review-tools.css", "static/css/report-paper.css", "ecg_core/hrv_report_pdf.py"]
---

# Continuous review and HRV evidence

Mode: Operate. Scoped extension; preserve existing product and A4 report identity.

## Direction contract

THESIS: Browse every occurrence vertically, place an explicit report interval, and export the same measured HRV evidence independently or with the main report.

OWN-WORLD: Existing white clinical workspace, teal controls, translucent pink selected-beat band with short red edge ticks, blue class-label frame and orange draggable interval handles; monochrome A4 output.

STORY: Scroll or jump to a beat, inspect its highlighted class, move interval boundaries, review full/day/night HRV and choose report inclusion.

FIRST VIEWPORT: Compact vertically virtualized card grid without blank filler; HRV has clear export/include controls above three period columns and trend evidence. The report range editor shows one multi-lead waveform with two orange boundary cursors, no duplicate bottom lead and no fill between cursors.

FORM: User-pinned hospital evidence structure; code-led extension, seed key incumbent-continuous-hrv-evidence. Missing/calibration-limited results remain explicit; risk is not automatically diagnosed.

FINISH: unreviewed and undocumented is unfinished; this build ends with the finish review, the verdict, DESIGN.md, and every shipping raster carrying its provenance

This incumbent extension preserves the existing DESIGN.md. Its implementation and finish record belong in this brief; evidence captures are not shipping raster assets.

## Implemented ground truth

Recorded 2026-09-21 from the related source files and finish handoff. This is a local extension of the existing white/teal workstation and monochrome A4 report variant in [DESIGN.md](../../DESIGN.md).

- Occurrences browse vertically in a virtualized grid with 1–6 columns and at most three visible rows. The viewport shrinks to the available rows; its scroll extent represents actual records. Visible-range counts, direct ordinal jump and arrow-key movement support navigation without a fixed empty panel. Opening a card locates its waveform; selecting review targets remains separate from report inclusion.
- The selected beat uses a translucent pink band, two short red horizontal edge ticks and a white class label in a blue frame, following the user's 2026-09-21 reference. No solid vertical focus line crosses the ECG. The band uses multiply blending so dark traces stay dark; it indicates focus, not a measured duration. Canvas labels sit above the plot when the existing top margin permits. N/S/V and other available class letters remain explicit text. The interactive range editor shows only the selected leads once, plus two orange boundary cursors; the duplicate bottom II strip, orange area fill and enclosing horizontal box edges remain removed. Printed report context strips are outside this refinement.
- Either orange boundary can be dragged or adjusted with arrow keys and numeric seconds. Whole-interval dragging was removed with the redundant overlay; the waveform itself remains unobscured. The readout shows start/end, duration, beat count and applied/draft status. Applying is explicit; moving a handle does not save a report. Reset restores the automatic 7-second / at-least-5-beat policy, subject to available data.
- HRV offers a 24-hour window selector, standalone PDF export and inclusion in the main report. Inclusion/window changes are draft composition changes saved from the report workspace. Standalone output is labeled unreviewed; the read-only demo uses the print path.
- The analysis page compares full/day/night periods using spectra, NN metrics and RR histograms, followed by hourly metrics, SDNN versus NN heart-rate groups, a statistical reference with a clinician interpretation field, and frequency-domain totals. The trend page aligns seven trace/count rows with evidence insets and a detailed hourly table; hourly tables continue after 25 rows. Day/night are clock segments (06–22 / 22–06), not sleep classification; unavailable clock data leaves those calculations unavailable.
- A4 paper stays white, black and gray with thin rules and the existing report type treatment; editing controls keep the workstation palette. Missing measurements remain gaps or an em dash. Uncalibrated ST is labeled in device units, and risk/candidate text does not claim an automatic diagnosis. The reviewed PDF's hourly headers, values and date/time lines are 6.3 pt; the SDNN reference includes `ms`.

## Finish evidence

- Finish review: initial `fix` for missing `ms` on average NN, SDNN, SDANN, SDNN index and rMSSD, and small PDF hourly text; both findings were corrected. The follow-up verdict is `ship`, covering the two scored fixes.
- Browser recaptures are in [hrv-continuous](../review/hrv-continuous/): [desktop](../review/hrv-continuous/desktop-recapture.jpg) at CSS width 1366, [wide desktop](../review/hrv-continuous/user-2048-recapture.jpg) at 2048, [mobile](../review/hrv-continuous/mobile-recapture.jpg) at 390, plus [HRV desktop](../review/hrv-continuous/hrv-desktop-recapture.jpg) and [range editor](../review/hrv-continuous/report-range-recapture.jpg). Images were uniformly scaled for capture delivery; their raster dimensions are not CSS viewport dimensions.
- The final reviewed PDF render is [analysis page](../review/hrv-continuous/ecg-hrv-reviewed-1.png) and [trend page](../review/hrv-continuous/ecg-hrv-reviewed-2.png), showing the two-page A4 verification sample. These local captures are review evidence, not product imagery or clinical validation.
- Detector ran once: 0 primary findings and 17 advisory findings. Red/blue peak annotations, orange interval controls and the monochrome print palette are deliberate scoped roles; no new raster assets ship.
- Validation supplied by the finish handoff: 18 targeted tests passed after the two PDF corrections, followed by the final full run of 203 tests passing in 103.48 seconds. `git diff --check` also passed.

### Cursor-only refinement · 2026-09-21

- User-requested local distillation: remove the duplicate bottom lead and the orange filled range, retaining the two boundary cursors, exact numeric input, keyboard adjustment, explicit apply/reset and red/blue peak annotation. No printed-report layout changes.
- Bounded browser check at 1366 × 900 and 390 × 844: one waveform with II/V1/V5, two cursors, no filled interval; keyboard changed the start by 5 ms, pointer dragging changed the end, and numeric inputs restored the original candidate. No report was saved during this browser check; the temporary viewport override was reset. No browser console errors were observed.
- Local polish verdict: `ship` for this narrow refinement. Node syntax check, 19 review/HRV/range tests and 1 static-demo-builder test passed; `git diff --check` passed. The new regression test covers one waveform, two handles, absence of the old strip/overlay, both drag boundaries, keyboard/numeric drafts and explicit apply/reset callbacks.
- Rebuilt `docs/demo` from the shared template; the copied editor and CSS match the sources byte-for-byte. The demo waveform SHA-256 remains `2896758a256a50670f464a33d280d23b763cb8746236da5e115b2f519899f4ff`. No new raster assets ship. README now describes the cursor-only editor.

Global `PRODUCT.md`, `DESIGN.md`, `.impeccable/design.json` and other surface briefs are unchanged by this refinement.

### Focus-band refinement · 2026-09-21

- User reference supersedes the earlier red through-wave focus line: the shared Canvas/SVG marker now uses a 14% pink band with multiply blending, short red edge ticks and the existing blue class box. In the continuous editor the label uses the top margin, avoiding the ECG plot. Overview focus skips its ordinary through-wave beat line and avoids painting the same scatter target twice.
- The same shared marker covers continuous review, selected strip/card previews, ST-T beat focus and report-range preview. ST-T measurement cursors and orange report boundaries are unchanged; no waveform samples, classifications or report data were modified.
- Bounded local browser review at 1366 × 900 and 390 × 844 verified a click selects the nearest beat, the pink band/blue label identifies it without a red vertical line, and the waveform remains visible. Canvas continuous waveforms and SVG occurrence cards were visually checked; no browser console errors were observed. Local polish verdict: `ship` for this marker refinement.
- Validation: 22 review/HRV/range tests plus 1 Demo-builder test passed, including N/S/V SVG geometry and Canvas calls that reject through-wave line drawing. Node syntax and `git diff --check` passed. Demo shared JS copies are byte-identical to the source; the original waveform SHA-256 remains unchanged. No new product raster assets or remote publication.
