#!/usr/bin/env python3
"""Smoke-test the frozen Windows package in system Edge using mathematical M01."""
import argparse
import asyncio
import json
import tempfile
from pathlib import Path
from urllib.parse import urlsplit

from verify_windows_doctor_browser import (
    CASE_ID,
    browser_json,
    digest,
    launch,
    manager_page,
    navigate,
    open_case,
    pe_is_x64,
    require,
    safe_error,
    source_snapshot,
    stop,
    two_frames,
)


async def verify(package, result):
    from playwright.async_api import async_playwright

    executable = package / "CardioInsightDoctorEval.exe"
    require(executable.is_file() and pe_is_x64(executable), "Expected a frozen Windows x64 executable")
    metadata = json.loads((package / "RELEASE.json").read_text(encoding="utf-8"))
    require(metadata["packaging_version"] == "1.0.30", "Expected Windows package version 1.0.30")
    source_root, _, source_before = source_snapshot(package)
    result.update(
        packaging_version=metadata["packaging_version"],
        executable_sha256=digest(executable),
        source_sha256=source_before["source-manifest.json"],
        synthetic_m01_only=True,
        case_open_default_overview=False,
        report_checks=[],
        blocked_network=[],
        page_errors=[],
    )
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(
            channel="msedge", headless=True,
            args=["--disable-background-networking", "--disable-component-update", "--disable-sync", "--no-first-run"],
        )
        result["browser"] = {"channel": "msedge", "version": browser.version}
        try:
            with tempfile.TemporaryDirectory(prefix="ecg-win-report-") as directory:
                home = Path(directory)
                state = None
                context = await browser.new_context(
                    viewport={"width": 1440, "height": 1000}, service_workers="block"
                )

                async def local_only(route):
                    path = urlsplit(route.request.url)
                    if path.scheme in ("http", "https") and path.hostname not in ("127.0.0.1", "localhost", "::1"):
                        result["blocked_network"].append("external origin")
                        await route.abort()
                    elif path.path.endswith("/report") and route.request.method not in ("GET", "HEAD"):
                        result["blocked_network"].append("write to report")
                        await route.abort()
                    else:
                        await route.continue_()

                await context.route("**/*", local_only)
                try:
                    state, result["manager_start_seconds"] = await launch(executable, home, source_root)
                    page = await manager_page(context, state)
                    page.on("pageerror", lambda error: result["page_errors"].append(
                        safe_error(error, [package, home, state["token"]])
                    ))
                    async with page.expect_response(lambda response: urlsplit(response.url).path == "/continue") as following:
                        await page.locator("#continueExperience").click()
                    require((await following.value).status == 303, "The frozen app could not open its mathematical workspace")
                    result["case_open_seconds"] = await open_case(page)
                    result["case_open_default_overview"] = True

                    await navigate(page, "report")
                    await page.locator('#reportV2Nav [data-category="final"]').click()
                    await page.wait_for_function("""() => !state.reportEvidenceLoading && !state.reportEvidenceError
                        && !state.reportViewLoading && !state.reportViewError
                        && document.querySelector('#reportV2Content .rw-workspace')""")
                    await page.locator("#reportNoticeRow").wait_for()
                    initial = await browser_json(page, f"/api/cases/{CASE_ID}/report")
                    result["report_checks"].append("native_case_report_load")

                    # The brand-new synthetic report has no pending strips. Supply
                    # mathematical widget inputs in the browser only. Never save.
                    await page.evaluate("""() => {
                        const host = document.querySelector('#reportV2Content');
                        const row = document.querySelector('#reportNoticeRow');
                        state.reportRhythmPending = [0];
                        state.reportEvidencePending = [{status: 'stale'}, {status: 'stale'}];
                        state.reportSTTPending = [];
                        row._syncNotices();
                        const selected = [1, 2].map(i => ({
                            event_id: 'native-smoke-strip-' + i,
                            basis_version: 'math-old',
                            caption: 'M01 UI fixture ' + i,
                            leads: ['II']
                        }));
                        const composition = {
                            ...structuredClone(state.report.composition), selected_events: selected
                        };
                        window.__mathBatchSubmitted = false;
                        ECGReportWorkspace.compose(host, {
                            id: 'native-smoke-report',
                            composition, selected, lookup: new Map(),
                            sections: ECGReportSections.catalog(), inspection: true,
                            onStripRemoveMany: () => { window.__mathBatchSubmitted = true; return false; }
                        });
                    }""")
                    toggle = page.locator("#reportNoticeToggle")
                    require("房颤／房扑 1 段" in await toggle.inner_text(), "Report pending-rhythm badge is missing")
                    require("图条 2 张" in await toggle.inner_text(), "Report pending-strip badge is missing")
                    report = page.locator("#reportV2Content")
                    await two_frames(page)
                    before = await report.bounding_box()
                    await toggle.click()
                    await page.locator("#reportNoticePanel:popover-open").wait_for()
                    await two_frames(page)
                    opened = await report.bounding_box()
                    require(before == opened, "The pending-report popover moved or resized the report panel")
                    await page.keyboard.press("Escape")
                    await page.locator("#reportNoticePanel:popover-open").wait_for(state="detached")
                    result["report_checks"].append("native_edge_report_notice_does_not_reflow")

                    rows = page.locator('[data-rw-batch-pick]')
                    require(await rows.count() == 2, "Batch controls did not mount for both mathematical strips")
                    await rows.first.check()
                    await page.locator('[data-rw-mini="1"]').click(button="right", modifiers=["Control"])
                    require(await rows.last.is_checked(), "Control-right-click did not select the second report strip")
                    await page.locator("[data-rw-batch-remove]").click()
                    dialog = page.locator("dialog.rw-strip-remove-dialog")
                    await dialog.get_by_role("button", name="取消", exact=True).click()
                    await dialog.wait_for(state="detached")
                    require(not await page.evaluate("window.__mathBatchSubmitted"), "Cancel unexpectedly attempted a batch submission")
                    final = await browser_json(page, f"/api/cases/{CASE_ID}/report")
                    require(initial == final, "The native staged report changed during browser verification")
                    result["report_checks"].append("native_edge_batch_multi_select_cancel_without_report_change")
                    require(not result["page_errors"] and not result["blocked_network"], "Unexpected browser error or egress/write attempt")
                finally:
                    try:
                        await context.close()
                    finally:
                        if state is not None or (home / "runtime").exists():
                            await stop(executable, home)
                            result["owned_processes_stopped"] = True
        finally:
            await browser.close()
    _, _, source_after = source_snapshot(package)
    require(source_after == source_before, "The packaged synthetic M01 source changed")
    result["source_preserved"] = True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package-root", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    package = args.package_root.resolve()
    result = {"status": "failed"}
    try:
        asyncio.run(verify(package, result))
        result["status"] = "passed"
    except Exception as error:
        result["error"] = safe_error(error, [package])
    finally:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if result["status"] != "passed":
        raise SystemExit(result.get("error", "Native Windows browser verification failed"))
    print("Windows x64 EXE and Edge report interaction checks passed with mathematical M01.")


if __name__ == "__main__":
    main()
