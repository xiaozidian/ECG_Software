# Windows doctor evaluation: core acceptance follow-up

The 1.0.0 files from [run 38388270486](https://github.com/xiaozidian/ECG_Software/actions/runs/38388270486) remain candidate artifacts. They are not replaced by the supplemental validation changes. The final 1.0.1 below was built only after every mandatory core gate passed, with its own tested commit and archive hashes. Public main, Pages and the original Mac workstation are unchanged.

## Final 1.0.1 delivery and measured acceptance

[Run 38421426571](https://github.com/xiaozidian/ECG_Software/actions/runs/38421426571), tested and packaged commit `eeda28070fa797918016a989ca400dc030e3047f`, completed successfully. All mandatory core gates, the original 18 template checks, all four unchanged day-input assertions, 20 source checks and the final ZIP/native-process checks passed. Actual frozen-program interaction in system Edge passed 38/38 checks. Native version is 0.12.16-platform-perf.20261013; the 112-file production SHA256 is `70192814337757ba9d60bc1289f300a8a6da620966e8b0be51072438d9fc9e39`.

Complete regression retained all original nodes and added 100 passing tests. Baseline: 1960 passed, 84 failed, 3 errors, 1 skipped (2048 total). Candidate: 2145 passed, 2 failed, 0 errors, 1 skipped (2148 total). Strict comparison passed with no missing nodes or new regressions. The two unchanged failures require private frozen AF-development evidence; `full_suite_green=false` and clinical acceptance is not claimed.

[Official delivery artifact](https://github.com/xiaozidian/ECG_Software/actions/runs/38421426571/artifacts/11830512329) contains the three formal ZIPs, their SHA256 sidecars, source manifest and build report. It expires on 2026-10-27. The 1.0.2 same-core upgrade fixture is excluded.

| ZIP | Bytes | SHA256 |
| --- | ---: | --- |
| CardioInsight-DoctorEval-Windows-x64-1.0.1-full.zip | 201973520 | 8f03e1b731010fce3c8fd28cf2973407f3481adcd843e5687410423559876221 |
| CardioInsight-DoctorEval-Windows-x64-1.0.1-software.zip | 38090241 | 0ff88170b7650ba8a1880cc1ccc8a6b4dfc3ff6f407fc49b7aa6be2e7b869c78 |
| CardioInsight-Synthetic-M01-24h-v1.zip | 163882245 | 8dccfd01dd2bd6ca262cf1b295ac69bed03795c42752e5a9d82024dd2421caef |

The outer delivery artifact SHA256 is `fdbf09efdf1d3b369e459bdab18549d4c67fdf1b4f71c12d5dc0f15e12347e3e`. [Public mathematical validation artifact](https://github.com/xiaozidian/ECG_Software/actions/runs/38421426571/artifacts/11830317973), SHA256 `fe0f4ed57fcdd86fb8763416cfff48bfcfa0b642848d927aa73e40fe4f5e76a1`, retains JSON/JUnit/PNG evidence and expires on 2026-10-27. [Machine-readable final summary](releases/0.12.16-platform-perf.20261013/windows-final-acceptance-summary.json) records exact conditions and numbers.

Final same-runner request comparison used one continuous 24-hour M01, a 10-second raw waveform window, all 12 displayed leads and 2000 points per lead, with two warmups per mode followed by three interleaved measurements. No OS disk cache clearing or P95 estimate is claimed.

| Request path | Median seconds | Minimum–maximum | DATA hash calls | DATA hash bytes |
| --- | ---: | --- | ---: | ---: |
| Safe repeated-hash fallback | 5.6011460 | 5.5786161–5.6041532 | 20 | 5529600000 |
| Temporary request lease | 0.5165167 | 0.5156033–0.5176232 | 1 | 276480000 |

The median ratio is 10.8441×. Every optimized sample was below the unchanged one-second limit. Complete diagnostic payloads and independently decoded twelve-lead samples matched. This gain is specific to mutable-source API requests; the managed demonstration source already has a long read lease, so it does not establish a 10.8× startup or whole-UI improvement.

Actual system Edge153.0.4234.48 on Windows Server2025 x64 used the same frozen EXE, source SHA, 1440×1000 viewport and UI sequences for three process-first and three warm rounds. Process-first means a new workspace process and empty mathematical work DB; OS caches were not cleared.

| Native UI operation | Process-first median [min–max], seconds | Warm median [min–max], seconds |
| --- | --- | --- |
| Manager start | 1.465 [1.440–1.882] | Not measured separately |
| Open case | 8.070 [7.804–8.113] | 3.952 [3.820–3.974] |
| Editor and two twelve-lead returns | 4.117 [4.094–4.124] | 5.763 [5.708–5.850] |
| ST 60-second range | 11.191 [11.049–11.229] | 3.253 [3.245–3.306] |
| HRV full 24 hours | 14.820 [14.599–14.994] | 4.906 [4.689–5.034] |

The native ST range returned 12 leads, 68 detected beats, 67 used, one RR-bound exclusion and no missing beats, with native HMAC evidence. Native HRV produced and rendered 24 hourly rows and 98463 NN intervals. Cancellation/retry, save/reopen, PDF download, workspace isolation, feedback privacy and stop/relaunch passed; observed page external requests, resource failures, page errors and HTTP errors were all zero. These are current measurements, not an old/new UI speed claim.

Upgrade acceptance exercises packaging1.0.1→CI-only1.0.2 with identical native core and schema, verified SQLite backup, retained report/annotation and unchanged registered source hashes. It does not prove the actual former native0.12.15/package1.0.0→native0.12.16/package1.0.1 transition or future migrations. The old1.0.0 remains a separate retained candidate.

This final documentation-only record does not alter the tested or packaged source commit, production fingerprint or native bytes. Physical hospital Windows10, a clean no-Python OS, architecture/EDR/unsigned-package acceptance, Chinese PDF glyphs and physical printing remain unverified.

## Measured whole-day source read regression and correction

[Supplemental run 38397857679](https://github.com/xiaozidian/ECG_Software/actions/runs/38397857679), commit a1d5b724, retained every node and byte-verified input. Baseline: 1958 passed, 86 failed, 3 fixture errors, 1 skip (2048 total). Candidate: 2128 passed, 3 failed, 3 fixture errors, 1 skip (2135 total). The strict comparison rejected the changed API failure: baseline passed waveform latency but later failed SDNN by 3.29 ms; candidate waveform took 5.8023502 seconds, exceeding the unchanged <1-second assertion.

The mutable Windows source signature repeatedly hashed the complete 276,480,000-byte DATA during one short waveform request. A case-specific temporary read lease now computes fresh contents once while write/replacement access is denied, reuses that completed SHA and the same content cache key inside the request, then releases every reference at teardown. After the active lease set closes, a later request hashes actual bytes again. Overlapping read leases share the completed byte proof only while write access remains denied. This never relies on timestamps alone, does not change file permissions and retains the existing immutable evaluation-source nonce mode. Source-write denial during export remains a 409 conflict with no successful export audit; unrelated errors retain their original handling.

Native version becomes 0.12.16-platform-perf.20261013 with a new 112-file production fingerprint; packaging1.0.1 is now built and verified in the final run recorded above. The original 1.0.0 is retained. Native diagnostic algorithm files, rules, thresholds, units and waveform samples are unchanged.

Before expensive day regression, Windows CI freshly creates one independent full 24-hour M01 and interleaves the old safe repeated-hash fallback and new request lease on the same app/source. Two warmups and at least three measured requests per mode are recorded. The new path must read DATA once and satisfy <1 second on every sample. Payloads retain analysis basis/revision, all beat/annotation fields and every twelve-lead sample; an independent int16 reader verifies all derivations. JSON records timing median/range and actual hash calls/bytes/time; source and temporary DB are removed, never uploaded. [Run 38409671975](https://github.com/xiaozidian/ECG_Software/actions/runs/38409671975), native commit 297a52f3, passed this gate. With three measured requests per mode after two warmups each, fallback median was 5.6833219 seconds (5.6462443–5.7315731), and the request lease median was 0.5253432 seconds (0.5249954–0.5258691): 10.8183× by the median. DATA hash calls were 20 versus 1; actual bytes read for hashing were 5,529,600,000 versus 276,480,000 per request. Every optimized sample satisfied the original <1-second limit; all diagnostic payload fields and independent twelve-lead samples matched. These are interleaved requests in one app/process with warmed OS caches, not disk-cold startup or whole-UI timing. Full JSON and JUnit are retained in [validation artifact 11823553772](https://github.com/xiaozidian/ECG_Software/actions/runs/38409671975/artifacts/11823553772), SHA256 1e004ba7adf90028dda5ee7dcbb93c7094c90cc3eb306ea70f0999ac7ba45581.


## Default source lease and original late-source race fixture

That same run retained all 2048 baseline and 2147 candidate nodes and verified the same inputs before and after testing. Baseline: 1959 passed, 85 failed, 3 fixture errors, 1 skip. Candidate: 2140 passed, 3 failed, 3 fixture errors, 1 skip. Both original day scopes passed 4/4 unchanged assertions, including waveform latency and source-report SDNN tolerance.

The strict comparator correctly rejected one changed failure: the original same-UUID mean-save race fixture commits its first winner, physically rewrites DATA, records a checkpoint, then calls the second locked reconciliation. The default Windows read lease denied that injected write before the checkpoint, producing a different failure. This is not accepted as a same-baseline success.

Only that disposable fixture's DATA branch now selects the existing safe repeated-byte-hash fallback for its target POST. It retains the actual file mutation, second storage call and every original assertion. A separate Windows default-lease test requires the actual write to be denied, HTTP409/report_conflict, exactly one real committed winner and create audit, unchanged full DB snapshot and all three source hashes, and released handles after request teardown. Both paths run before expensive day generation. Production lease defaults and native bytes are unchanged; the next candidate has 2148 test nodes and remains subject to the same strict comparison. The final run above retained all2148 candidate nodes and passed strict comparison.

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

## Trusted original template contracts restored

The wrapper `tests/test_final_template_linked_contract.py` requires:

- `tests/final_template_linked_math.cjs`: 9 checks
- `tests/final_template_linked_adapter.cjs`: 6 checks
- `tests/final_template_linked_morphadapter.cjs`: 3 checks

None was found in all 48 reachable ancestor trees of e2c31137, two additional PR trees, public refs, tags, Releases or seven public source inventories. The wrapper was introduced in commit `666764f56e5491dcfdaa41dcc4822bd078a1e578`, blob `14292b82c2a8221356faa7700889ea475ffe697d`, without those three scripts. The separately published readiness script is another contract and cannot replace them.

The three original scripts were subsequently restored from a trusted existing production-code snapshot and confirmed against recorded checksums and independent retained code copies. Only pure Node standard-library, in-memory mathematical validation is restored; private validation records, real data and source paths are not published. Exact UTF-8/LF file identities:

| File | Bytes | SHA256 |
| --- | ---: | --- |
| final_template_linked_math.cjs | 4264 | 92a407501539c833550e7950db145074bd698188b385f140c67c5ae7ba40d2c6 |
| final_template_linked_adapter.cjs | 4367 | 33018e100dbb41a289750b9f52026a2ee0f18585087e587fb37f728fd07e1b7c |
| final_template_linked_morphadapter.cjs | 2815 | 914dfbc4d305d88dd22d4a24ea5ff3d47ec1b2040ea420527fea2a4882e72a58 |

The unchanged original wrapper and 18 checks now run before expensive day generation, and remain mandatory before packaging. A preflight rejects missing original assets; core doctor failures also stop before generation. Product JavaScript is retained. Actual Windows Node22 validation passed all18 original checks before day generation in the final run.

## Accuracy and environment limits

Both remaining failures are FileNotFoundError when `frozen_parameters()` opens `docs/validation/af-entropy-20260929/development-v1/summary.json`. The summary and its source-bound development snapshot are required for the independent LTAFDB research workflow:
- `test_candidate_thresholds_match_unchanged_frozen_development` would verify protocol `af-entropy-development-v1` and unchanged `entropy`/`entropy-turning` thresholds of -1.35 against the original snapshot.
- `test_current_workstation_cannot_masquerade_as_frozen_development` would require a source-drift rejection so an evolving workstation cannot claim the frozen build's external-validation result.

Neither assertion can be completed without the private freeze; the missing-file outcome occurs before threshold comparison or source-hash drift rejection. This is an external AF-candidate accuracy/reproducibility and claim-provenance gap, not a completed clinical pass. The native startup and mathematical-source doctor workflows do not import this research evaluator or load its summary. M01 keeps its AF-like section unclassified; physicians can inspect and manually mark ranges under the retained confirmation and saved-evidence protections. Functional mathematical trial is supported by the passed native/core gates; AF diagnostic accuracy on patients is not established. Private freeze inputs are not uploaded, thresholds are not changed, and no replacement summary or validation claim is fabricated.

GitHub Windows Server CI and system Edge are available. Physical hospital Windows 10 hardware, architecture, security software and unsigned-package acceptance remain unverified. Mac access and the original ten-case workstation are outside this environment; saved work has not been switched or modified. The separate Mac archive task owns preserving 1.0.0 artifacts.
