# Windows doctor evaluation: core acceptance follow-up

The 1.0.0 files from [run 38388270486](https://github.com/xiaozidian/ECG_Software/actions/runs/38388270486) remain candidate artifacts. They are not replaced by the supplemental validation changes. The next packaging version is 1.0.1, with a new source commit and new archive hashes only after every mandatory core gate passes. Public main, Pages and the original Mac workstation are unchanged.

## Measured whole-day source read regression and correction

[Supplemental run 38397857679](https://github.com/xiaozidian/ECG_Software/actions/runs/38397857679), commit a1d5b724, retained every node and byte-verified input. Baseline: 1958 passed, 86 failed, 3 fixture errors, 1 skip (2048 total). Candidate: 2128 passed, 3 failed, 3 fixture errors, 1 skip (2135 total). The strict comparison rejected the changed API failure: baseline passed waveform latency but later failed SDNN by 3.29 ms; candidate waveform took 5.8023502 seconds, exceeding the unchanged <1-second assertion.

The mutable Windows source signature repeatedly hashed the complete 276,480,000-byte DATA during one short waveform request. A case-specific temporary read lease now computes fresh contents once while write/replacement access is denied, reuses that completed SHA and the same content cache key inside the request, then releases every reference at teardown. The next request hashes actual bytes again. This never relies on timestamps alone, does not change file permissions and retains the existing immutable evaluation-source nonce mode. Source-write denial during export remains a 409 conflict with no successful export audit; unrelated errors retain their original handling.

Native version becomes 0.12.16-platform-perf.20261013 with a new 112-file production fingerprint; packaging remains the not-yet-built 1.0.1. The original 1.0.0 is retained. Native diagnostic algorithm files, rules, thresholds, units and waveform samples are unchanged.

Before expensive day regression, Windows CI freshly creates one independent full 24-hour M01 and interleaves the old safe repeated-hash fallback and new request lease on the same app/source. Two warmups and at least three measured requests per mode are recorded. The new path must read DATA once and satisfy <1 second on every sample. Payloads retain analysis basis/revision, all beat/annotation fields and every twelve-lead sample; an independent int16 reader verifies all derivations. JSON records timing median/range and actual hash calls/bytes/time; source and temporary DB are removed, never uploaded. Actual results remain pending until that CI gate completes.

## Minimum platform corrections

- Export both `ECG_CHROME` and `ECG_CHROME_PATH` as the existing system Edge executable. The original report gesture fixture previously selected a Mac-only fallback.
- Check out `.cjs` with LF and normalize CRLF before splitting the existing saved-ST mathematical fixture. The boundary assertion is retained.
- Use `Path(path).name` in the QRS test stub on Windows. The assertions that detection is persisted before references are read, and that downstream failures cannot create a success summary, remain unchanged.
- Run original report-range and saved-ST pointer tests, plus QRS checkpoint tests, before expensive regression and packaging. Their actual assertions must pass independently of baseline classification.

These corrections do not change diagnostic algorithms, thresholds, labels, units, raw samples or saved physician work.

## Strict short and whole-day regression scopes

The frozen baseline and candidate share the same runner, dependencies and byte-verified synthetic inputs, while their work directories and databases remain isolated.

The frozen legacy generator renders ten independent 30-minute profiles; its unchanged waveform/beat engine renders ten independent 24-hour profiles with corrected fictional NN references, seed 20260812. Each day-long DATA is 276,480,000 bytes; ten total 2,764,800,000 bytes. It renders every absolute sample; no waveform tiling, padding or label rewriting is performed.

Four existing tests require day-long inputs: raw/report duration, EBI count and RR timing, the 3600-second twelve-lead window, and the waveform/events/trend/HRV endpoint contract. They run once against genuine day inputs. All other nodes run once against the short inputs. All original assertions remain unchanged. The JUnit merger rejects missing, duplicated, misrouted or collection-error nodes and preserves failed/error outcomes; both baseline and candidate include every original node. SHA256 inventories are verified before and after each full run.

The old fictional LPS generator counted intervals ending at N even when they began at S/V/noise. Default source HRV requires both endpoints N. Only the synthetic generator's SDNN/rMSSD/pNN50 reference population is corrected; native algorithms and the original API tolerance remain unchanged. An independent hand example has NN [800,900,1000,800,900], sample variance 7000 and SDNN 83.67; the old one-endpoint population gives 287.85.

Before new day generation, the frozen and corrected generators build the same ten one-minute profiles. DATA and EBI hashes must match exactly; all XML report content except those three HRV reference text values must match. ASTs outside the reference statistics function must also be identical. Every new whole-day profile then must have all three reported reference metrics equal to unchanged native source HRV. The old running CI source cannot be changed or reused through the available tools; the new commit generates fresh inputs and retains the old run's results.

The continuous M01 doctor source is a separate profile with unclassified AF-like segments. Its labels are retained. It is not substituted for the legacy ten-case label and SDNN contracts.

## Trusted original template contract gap

The wrapper `tests/test_final_template_linked_contract.py` requires:

- `tests/final_template_linked_math.cjs`: 9 checks
- `tests/final_template_linked_adapter.cjs`: 6 checks
- `tests/final_template_linked_morphadapter.cjs`: 3 checks

None was found in all 48 reachable ancestor trees of e2c31137, two additional PR trees, public refs, tags, Releases or seven public source inventories. The wrapper was introduced in commit `666764f56e5491dcfdaa41dcc4822bd078a1e578`, blob `14292b82c2a8221356faa7700889ea475ffe697d`, without those three scripts. The separately published readiness script is another contract and cannot replace them.

The original wrapper is a mandatory gate before building or uploading the next verified package. A baseline-existing fixture error does not satisfy core doctor acceptance. Restore the exact original files from a trusted private code snapshot when the owning environment is available; do not fabricate equivalent scripts or adjust expected check counts.

## Accuracy and environment limits

The two AF research tests require an absent frozen development summary and its bound source snapshot. Private AF validation inputs are not uploaded to public CI. A same-baseline failure remains a documented accuracy-validation gap, never clinical acceptance. No diagnostic rule changes or expanded clinical research are included.

GitHub Windows Server CI and system Edge are available. Physical hospital Windows 10 hardware, architecture, security software and unsigned-package acceptance remain unverified. Mac access and the original ten-case workstation are outside this environment; saved work has not been switched or modified. The separate Mac archive task owns preserving 1.0.0 artifacts.
