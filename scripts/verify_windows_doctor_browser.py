#!/usr/bin/env python3
"""Exercise the unpacked frozen Windows doctor EXE in the installed Microsoft Edge.

Playwright is a CI/development dependency, never a doctor-runtime dependency.
Only the mathematical M01 source is accepted. The output is a safe JSON receipt
and screenshots of that mathematical fixture; databases, sources, downloads and
feedback archives remain in a disposable directory and are not published.
"""
from __future__ import annotations

import argparse
import asyncio
import ctypes
from ctypes import wintypes
from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path, PurePosixPath
import platform
import re
import shutil
import statistics
import struct
import subprocess
import tempfile
import time
import traceback
from urllib.error import URLError
from urllib.parse import urlsplit
from urllib.request import Request, build_opener, ProxyHandler
import zipfile

PROFILE = "cardioinsight-doctor-eval-synthetic-24h-v1"
CASE_ID = "9900000000000001"
LEADS = ["I", "II", "III", "aVR", "aVL", "aVF", "V1", "V2", "V3", "V4", "V5", "V6"]
SOURCE_BYTES = 276480000
TIMEOUT_MS = 120000
REPORT_NOTE = "数学软件验收：仅合成 M01；这是未审核工程练习草稿。"
ANNOTATION_NOTE = "数学软件验收：合成波形人工复核备注；不作临床结论。"
SNAPSHOT_JS = """() => ({
    page:state.currentPage, mode:state.editMode, start:state.editStart,
    duration:state.editDuration, lead:state.editLead,
    selectedClass:state.editSelectedClass,
    selected:[...state.editSelectedSamples].sort((a,b)=>a-b),
    focus:state.editSelectedSample,
    galleryScroll:document.querySelector('#editTemplateGallery')?.scrollTop||0
})"""
OPENER = build_opener(ProxyHandler({}))


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def digest(path):
    value = sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def safe_error(error, private_values=()):
    value = str(error)
    for private in sorted((str(x) for x in private_values if x), key=len, reverse=True):
        value = value.replace(private, "[redacted]")
        value = value.replace(private.replace("\\", "\\\\"), "[redacted]")
    value = re.sub(r"(https?://[^\s?]+)\?[^\s]*", r"\1?[redacted]", value)
    value = re.sub(r"(?i)(token[=:]\s*)[a-f0-9]{32,}", r"\1[redacted]", value)
    # Exceptions must not publish CI/user directory names even if failure occurs
    # while unpacking or shutting down the second program directory.
    value = re.sub(r"""(?i)[a-z]:[\\/][^\s'"><,;\]\)]+""", "[local-path]", value)
    return type(error).__name__ + ": " + value[:1000]


def source_snapshot(package):
    root = package / "Sources" / "M01"
    manifest = json.loads((root / "source-manifest.json").read_text(encoding="utf-8"))
    require(manifest.get("profile") == PROFILE, "Source must use the approved mathematical M01 profile")
    require(manifest.get("kind") == "mathematical_synthetic", "Source must be mathematical synthetic")
    require(manifest.get("wholly_synthetic") is True, "Source provenance must be wholly synthetic")
    require(manifest.get("patient_inputs_read") is False, "Patient input is forbidden in browser verification")
    require(manifest.get("clinical_ground_truth") is False, "Source cannot claim clinical ground truth")
    require(manifest.get("case_id") == CASE_ID and manifest.get("source_id") == "M01", "Unexpected source identity")
    require(manifest.get("duration_seconds") == 86400 and manifest.get("sampling_rate_hz") == 200, "Full 24h at 200Hz is required")
    require(manifest.get("sample_count") == 17280000 and manifest.get("channel_count") == 8, "Full raw sample count is required")
    require(manifest.get("expected_raw_bytes") == SOURCE_BYTES, "Raw data must not be downsampled")
    require(manifest.get("full_24h_fixture") is True, "Short fixtures cannot satisfy this verification")
    entries = manifest.get("files")
    require(isinstance(entries, list) and len(entries) == 4, "Expected DATA, EBI, LPS and mathematical events")
    snapshot = {"source-manifest.json": digest(root / "source-manifest.json")}
    for entry in entries:
        relative = PurePosixPath(entry["path"])
        require(not relative.is_absolute() and ".." not in relative.parts, "Source manifest path escapes M01")
        path = root.joinpath(*relative.parts)
        require(path.is_file() and not path.is_symlink(), "Source member must be an ordinary file")
        require(path.stat().st_size == entry["size_bytes"], "Source member size differs from manifest")
        actual = digest(path)
        require(actual == entry["sha256"], "Source member SHA256 differs from manifest")
        snapshot[relative.as_posix()] = actual
    require(any(name.endswith(".DATA") and (root / name).stat().st_size == SOURCE_BYTES for name in snapshot), "Full raw DATA missing")
    actual_files = {p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file()}
    require(actual_files == set(snapshot), "Unlisted source files are forbidden")
    require({p.name for p in root.parent.iterdir()} == {"M01"}, "Only mathematical M01 is permitted")
    return root, manifest, snapshot


def pe_is_x64(exe):
    with exe.open("rb") as stream:
        require(stream.read(2) == b"MZ", "Expected a frozen Windows PE executable")
        stream.seek(0x3C)
        offset = struct.unpack("<I", stream.read(4))[0]
        stream.seek(offset)
        require(stream.read(4) == b"PE\0\0", "Invalid PE signature")
        return struct.unpack("<H", stream.read(2))[0] == 0x8664


def frozen_environment(home):
    env = dict(os.environ)
    windows = Path(os.environ.get("SystemRoot", r"C:\Windows"))
    env["PATH"] = os.pathsep.join(str(p) for p in [windows / "System32", windows, windows / "System32" / "Wbem"])
    for name in ("PYTHONHOME", "PYTHONPATH", "PYTHONSTARTUP", "VIRTUAL_ENV", "CONDA_PREFIX", "ECG_DOCTOR_EVAL_SOURCE_ROOT"):
        env.pop(name, None)
    env.update(ECG_DOCTOR_EVAL_TESTING="1", ECG_DOCTOR_EVAL_HOME=str(home), ECG_ALLOW_PHI="0")
    require(shutil.which("python", path=env["PATH"]) is None, "Python must not be resolvable in doctor-runtime PATH")
    require(shutil.which("python3", path=env["PATH"]) is None, "Python3 must not be resolvable in doctor-runtime PATH")
    return env


def run_cli(exe, home, *arguments, timeout=180):
    return subprocess.run(
        [str(exe), *arguments], cwd=exe.parent, env=frozen_environment(home),
        stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, encoding="utf-8", errors="replace", timeout=timeout,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )


def process_image(pid):
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
    kernel.QueryFullProcessImageNameW.restype = wintypes.BOOL
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.CloseHandle.restype = wintypes.BOOL
    handle = kernel.OpenProcess(0x1000, False, int(pid))
    require(handle, "Cannot inspect the actual doctor process")
    try:
        buffer = ctypes.create_unicode_buffer(32768)
        length = wintypes.DWORD(len(buffer))
        require(kernel.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(length)), "Cannot resolve doctor executable image")
        return Path(buffer.value).resolve()
    finally:
        kernel.CloseHandle(handle)




def pe_imports(path):
    """Read direct PE import names without executing/importing a bundled binary."""
    data = Path(path).read_bytes()
    require(data[:2] == b"MZ", "Dependency graph contains a non-PE module")
    pe = struct.unpack_from("<I", data, 0x3C)[0]
    require(data[pe:pe + 4] == b"PE\0\0", "Dependency graph PE signature is invalid")
    sections = struct.unpack_from("<H", data, pe + 6)[0]
    optional_size = struct.unpack_from("<H", data, pe + 20)[0]
    optional = pe + 24
    magic = struct.unpack_from("<H", data, optional)[0]
    directory = optional + (112 if magic == 0x20B else 96)
    import_rva, _ = struct.unpack_from("<II", data, directory + 8)
    if not import_rva:
        return []
    section_rows = []
    for index in range(sections):
        offset = optional + optional_size + 40 * index
        virtual_size, virtual_address, raw_size, raw_start = struct.unpack_from("<IIII", data, offset + 8)
        section_rows.append((virtual_address, max(virtual_size, raw_size), raw_start))
    def file_offset(rva):
        for address, size, raw in section_rows:
            if address <= rva < address + size:
                offset = raw + rva - address
                require(0 <= offset < len(data), "Dependency graph RVA exceeds the module")
                return offset
        require(rva < struct.unpack_from("<I", data, optional + 60)[0], "Dependency graph RVA has no section")
        return rva
    cursor = file_offset(import_rva)
    names = []
    for _ in range(4096):
        descriptor = struct.unpack_from("<IIIII", data, cursor)
        if not any(descriptor):
            return sorted(set(names), key=str.lower)
        start = file_offset(descriptor[3])
        end = data.find(b"\0", start)
        require(end != -1 and end - start < 260, "Invalid dependency DLL name")
        names.append(data[start:end].decode("ascii"))
        cursor += 20
    raise AssertionError("Dependency import table did not terminate")

def process_modules(pid, exe):
    """Read owned process module paths; return safe bundle/System categories."""
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    psapi = ctypes.WinDLL("psapi", use_last_error=True)
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.CloseHandle.restype = wintypes.BOOL
    psapi.EnumProcessModulesEx.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.HMODULE), wintypes.DWORD, ctypes.POINTER(wintypes.DWORD), wintypes.DWORD]
    psapi.EnumProcessModulesEx.restype = wintypes.BOOL
    psapi.GetModuleFileNameExW.argtypes = [wintypes.HANDLE, wintypes.HMODULE, wintypes.LPWSTR, wintypes.DWORD]
    psapi.GetModuleFileNameExW.restype = wintypes.DWORD
    handle = kernel.OpenProcess(0x0400 | 0x0010, False, int(pid))
    require(handle, "Cannot inspect frozen process dependencies")
    try:
        modules = (wintypes.HMODULE * 4096)()
        needed = wintypes.DWORD()
        require(psapi.EnumProcessModulesEx(handle, modules, ctypes.sizeof(modules), ctypes.byref(needed), 3), "Cannot enumerate frozen process dependencies")
        require(needed.value <= ctypes.sizeof(modules), "Frozen process module list exceeded inspection capacity")
        bundle = exe.parent.resolve()
        system = Path(os.environ.get("SystemRoot", r"C:\Windows")).resolve()
        evidence = []
        dependency_graph = []
        required_crt = set()
        bundle_dlls = {path.name.lower(): path for path in bundle.rglob("*.dll")}
        python_found = False
        for module in modules[:needed.value // ctypes.sizeof(wintypes.HMODULE)]:
            name = ctypes.create_unicode_buffer(32768)
            require(psapi.GetModuleFileNameExW(handle, module, name, len(name)), "Cannot inspect a frozen process module")
            path = Path(name.value).resolve()
            lower_name = path.name.lower()
            if path.is_relative_to(bundle):
                category = "bundle"
                relative = path.relative_to(bundle).as_posix()
            elif path.is_relative_to(system):
                category = "Windows"
                relative = path.relative_to(system).as_posix()
            else:
                # Record the category only: host security/graphics software may
                # inject system modules, but Python must still come from bundle.
                category = "host-injected"
                relative = path.name
            if re.fullmatch(r"python\d+(?:_d)?\.dll", lower_name):
                require(category == "bundle" and relative.startswith("_internal/"), "Frozen doctor loaded Python from outside its bundle")
                python_found = True
            if "python" in lower_name or "numpy" in relative.lower() or "vcruntime" in lower_name or "msvcp" in lower_name or lower_name.endswith(".pyd"):
                evidence.append({"category": category, "module": relative})
                if category == "bundle":
                    imports = pe_imports(path)
                    dependency_graph.append({"module": relative, "imports": imports})
                    required_crt.update(name.lower() for name in imports if name.lower().startswith(("vcruntime", "msvcp")))
        require(python_found, "Cannot prove the running doctor loaded bundled Python")
        require(required_crt, "No Microsoft C runtime dependency was observed in bundled modules")
        require(required_crt <= set(bundle_dlls), "A required Microsoft C runtime DLL is absent from the portable bundle")
        return {"python_dll_from_bundle": True, "selected_pe_dependency_graph": dependency_graph, "required_microsoft_crt_dlls_bundled": sorted(required_crt), "selected_modules": sorted(evidence, key=lambda item: (item["category"], item["module"])), "host_security_injections_do_not_establish_clean_machine_acceptance": True}
    finally:
        kernel.CloseHandle(handle)

def health(state):
    port = state.get("port")
    require(type(port) is int and 1 <= port <= 65535, "Invalid manager/workspace port")
    request = Request("http://127.0.0.1:" + str(port) + "/_doctor/health", headers={"X-Doctor-Control": state["token"]})
    with OPENER.open(request, timeout=2) as response:
        require(response.status == 200, "Doctor health request failed")
        return json.load(response)


async def live_state(home, name, exe, timeout=180):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            state = json.loads((home / "runtime" / (name + ".json")).read_text(encoding="utf-8"))
            require(state["role"] == ("manager" if name == "manager" else "workspace"), "Unexpected runtime role")
            require(re.fullmatch(r"[a-f0-9]{64}", state["token"]) is not None, "Invalid runtime control token")
            reply = await asyncio.to_thread(health, state)
            require(reply.get("profile") == "cardioinsight-windows-doctor-eval-v1", "Unexpected doctor runtime profile")
            require(all(reply.get(key) == state.get(key) for key in ("role", "pid", "birth")), "Runtime health does not match the owned process identity")
            actual_image = await asyncio.to_thread(process_image, state["pid"])
            require(os.path.normcase(str(actual_image)) == os.path.normcase(str(exe.resolve())), "Runtime process does not use the frozen doctor EXE")
            return state
        except (OSError, ValueError, KeyError, URLError):
            await asyncio.sleep(0.15)
    raise AssertionError("Frozen doctor service did not become ready")


async def launch(exe, home, source_root=None):
    started = time.perf_counter()
    arguments = ["launch", "--no-browser"]
    if source_root is not None:
        arguments.extend(["--source-root", str(source_root)])
    run = await asyncio.to_thread(run_cli, exe, home, *arguments)
    require(run.returncode == 0, "Frozen doctor launch command failed")
    state = await live_state(home, "manager", exe)
    return state, time.perf_counter() - started


async def stop(exe, home):
    # Hold synchronization handles before shutdown. Socket/state disappearance
    # alone does not prove the Windows process has released its workspace locks.
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel.WaitForSingleObject.restype = wintypes.DWORD
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.CloseHandle.restype = wintypes.BOOL
    handles = []
    try:
        for state_path in (home / "runtime").glob("*.json"):
            try:
                state = json.loads(state_path.read_text(encoding="utf-8"))
                reply = await asyncio.to_thread(health, state)
                require(reply.get("profile") == "cardioinsight-windows-doctor-eval-v1", "Unexpected shutdown owner")
                require(all(reply.get(key) == state.get(key) for key in ("role", "pid", "birth")), "Shutdown owner identity changed")
                require(os.path.normcase(str(await asyncio.to_thread(process_image, state["pid"]))) == os.path.normcase(str(exe.resolve())), "Shutdown owner is not the active doctor EXE")
                handle = kernel.OpenProcess(0x00100000, False, int(state["pid"]))
                require(handle, "Cannot observe owned doctor process exit")
                handles.append(handle)
            except (OSError, ValueError, KeyError, URLError):
                continue
        run = await asyncio.to_thread(run_cli, exe, home, "stop", "--saved-work-acknowledged", timeout=240)
        require(run.returncode == 0, "Graceful doctor stop failed")
        deadline = time.monotonic() + 180
        while time.monotonic() < deadline:
            states = [kernel.WaitForSingleObject(handle, 0) for handle in handles]
            require(all(value in (0, 258) for value in states), "Owned process exit observation failed")
            active = False
            for state_path in (home / "runtime").glob("*.json"):
                try:
                    state = json.loads(state_path.read_text(encoding="utf-8"))
                    await asyncio.to_thread(health, state)
                    active = True
                except (OSError, ValueError, KeyError, URLError):
                    pass
            if not active and all(value == 0 for value in states):
                return
            await asyncio.sleep(0.15)
        raise AssertionError("Owned doctor services did not exit gracefully")
    finally:
        for handle in handles:
            kernel.CloseHandle(handle)


def unpack_software(source_archive, package, destination):
    if source_archive is None:
        shutil.copytree(package, destination, ignore=shutil.ignore_patterns("Sources"))
        return "equivalent-software-directory-copy"
    with zipfile.ZipFile(source_archive) as archive:
        require(archive.testzip() is None, "Software-only ZIP has a corrupt member")
        members = archive.infolist()
        for member in members:
            path = PurePosixPath(member.filename.replace("\\", "/"))
            require(not path.is_absolute() and ".." not in path.parts and not any(":" in part for part in path.parts), "Unsafe software ZIP path")
            require("Sources" not in path.parts, "Software-only update must not contain Sources")
            require((member.external_attr >> 16) & 0o170000 != 0o120000, "Software update cannot contain symbolic links")
        temporary = destination.parent / "software-unpacked"
        archive.extractall(temporary)
    candidates = list(temporary.rglob("CardioInsightDoctorEval.exe"))
    require(len(candidates) == 1, "Expected exactly one doctor EXE in software-only ZIP")
    shutil.move(str(candidates[0].parent), destination)
    return "software-only-zip"



def upgrade_receipt(home, workspace_id, before, after):
    work = home / "workspaces" / workspace_id
    receipt = after.get("last_upgrade")
    require(isinstance(receipt, dict), "Same-schema upgrade did not produce a backup receipt")
    require(receipt["from_packaging_version"] == before["packaging_version"], "Upgrade receipt source version is incorrect")
    require(receipt["to_packaging_version"] == after["packaging_version"], "Upgrade receipt destination version is incorrect")
    require(receipt["from_packaging_version"] != receipt["to_packaging_version"], "Same-version reinstall cannot prove a version upgrade")
    require(receipt["from_version"] == receipt["to_version"], "CI fixture must retain the exact native core version")
    require(receipt["before_schema"] == receipt["after_schema"], "Same-schema fixture unexpectedly changed database schema")
    require(receipt["before_schema"] == before["sqlite_schema"] and receipt["after_schema"] == after["sqlite_schema"], "Upgrade receipt schema differs from workspace metadata")
    require(receipt["snapshot_integrity"] == "ok", "Pre-upgrade SQLite snapshot integrity failed")
    relative = PurePosixPath(receipt["snapshot"])
    require(len(relative.parts) == 1 and not relative.is_absolute() and ".." not in relative.parts, "Upgrade snapshot must use a safe filename")
    snapshot = work / "upgrade-snapshots" / relative.name
    require(snapshot.is_file() and digest(snapshot) == receipt["snapshot_sha256"], "Pre-upgrade snapshot SHA256 verification failed")
    return {"kind": "fixture_same_schema_upgrade", "from_packaging_version": receipt["from_packaging_version"], "to_packaging_version": receipt["to_packaging_version"], "native_core_version_unchanged": True, "schema_fingerprint_unchanged": True, "sqlite_snapshot_integrity": "ok", "snapshot_sha256_verified": True, "snapshot_published": False}

def record(result, name, evidence=None, status="passed"):
    result["checks"].append({"name": name, "status": status, "evidence": evidence or {}})


async def two_frames(page):
    await page.evaluate("() => new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)))")


async def navigate(page, target):
    await page.locator('.nav-item[data-page="' + target + '"]').click()
    await page.wait_for_function("(target) => state.currentPage===target", arg=target)


async def worklist_ready(page):
    await page.wait_for_function("""() => typeof state!=='undefined'
        && !document.querySelector('#openFirstCase').disabled && state.cases?.length===1""")
    require(await page.locator("#metricCases").inner_text() == "1", "Native worklist must contain one mathematical case")


async def open_case(page):
    # The real worklist resumes its pending review step (edit, stt, or report).
    # Do not wait for the overview page or override the physician workflow.
    await worklist_ready(page)
    destination = await page.evaluate("() => state.cases.find(item=>item.case_id==='9900000000000001')?.review_workflow?.next_step||'review'")
    started = time.perf_counter()
    await page.locator("#openFirstCase").click()
    await page.wait_for_function("""(destination) => state.caseId==='9900000000000001'
        && !state.caseLoading && state.caseData?.technical?.duration_seconds_raw===86400
        && state.currentPage===destination""", arg=destination)
    if destination == "edit":
        await wait_edit(page)
    elif destination == "stt":
        await page.wait_for_function("() => state.sttEvidence && document.querySelector('#sttWaveCanvasWrap').dataset.sttWaveState==='ready'")
    elif destination == "report":
        await page.wait_for_function("() => state.report && !state.reportSaving && !state.reportLoading")
    elif destination == "review":
        await page.wait_for_function("() => state.waveform?.leads")
    else:
        require(False, "Unexpected native worklist review destination")
    require(await page.evaluate("() => state.demoReadonly===false && state.includePhi===false"), "Native writable and private doctor mode is required")
    require(await page.evaluate("() => state.caseData.technical.sample_rate_hz") == 200, "Native case must retain 200Hz")
    return time.perf_counter() - started


async def browser_json(page, path):
    return await page.evaluate("""async (path) => {
        const response=await fetch(path,{cache:'no-store'});
        if(!response.ok)throw Error('Native read failed: '+response.status);
        return response.json();
    }""", path)


async def manager_page(context, state):
    page = await context.new_page()
    page.set_default_timeout(TIMEOUT_MS)
    page.set_default_navigation_timeout(TIMEOUT_MS)
    await page.goto("http://127.0.0.1:" + str(state["port"]) + "/_doctor/open?token=" + state["token"], wait_until="domcontentloaded")
    await page.locator("#continueExperience").wait_for(state="visible")
    return page


async def expand_previous(manager):
    details = manager.locator("details").filter(has=manager.locator("#previousWorkspace"))
    require(await details.count() == 1, "Previous-workspace selector is unavailable")
    if not await details.evaluate("(node) => node.open"):
        await details.locator("summary").click()


async def resume(context, manager_state, workspace_id):
    manager = await manager_page(context, manager_state)
    await expand_previous(manager)
    await manager.locator("#previousWorkspace").select_option(workspace_id)
    async with manager.expect_popup() as popup:
        await manager.locator("#resumePrevious").click()
    page = await popup.value
    page.set_default_timeout(TIMEOUT_MS)
    page.set_default_navigation_timeout(TIMEOUT_MS)
    await worklist_ready(page)
    await manager.close()
    return page


async def wait_edit(page):
    await page.wait_for_function("""() => state.currentPage==='edit' && state.editWaveform?.leads
        && Math.abs(state.editWaveform.start_s-state.editStart)<0.006
        && Math.abs(state.editWaveform.duration_s-state.editDuration)<0.006
        && state.editReadIdentity?.analysis_basis && document.querySelector('#editTemplateGallery .occurrence-wave svg')""")
    await two_frames(page)


async def escape_edit(page):
    await page.keyboard.press("Escape")
    await page.wait_for_function("() => !state.waveformExpanded && state.currentPage==='edit' && state.editWaveform?.leads")
    await two_frames(page)


async def full_twelve(page, sample=None):
    await page.wait_for_function("""() => state.waveformExpanded && state.currentPage==='review'
        && state.editFullscreenReturn?.readState==='ready' && Object.keys(state.waveform?.leads||{}).length===12""")
    value = await page.evaluate("""() => ({
        leads:ECGChartInspection.names(state.waveform.leads),start:state.waveform.start_s,
        duration:state.waveform.duration_s,fs:state.waveform.sample_rate_hz,
        target:state.editFullscreenReturn.targetSample,edge:!!state.editFullscreenReturn.edgeClamped,
        focused:state.editSelectedSample,beatPresent:state.waveform.beats?.some(b=>b.sample_index===state.editFullscreenReturn.targetSample)
    })""")
    require(value["leads"] == LEADS and value["fs"] == 200, "Native twelve-lead response is incomplete")
    if sample is not None:
        require(value["target"] == sample and value["focused"] == sample, "Twelve-lead view substituted a different source beat")
        require(value["beatPresent"] is True, "Exact source beat is absent from native twelve-lead response")
        if not value["edge"]:
            require(abs(sample / 200 - value["start"] - value["duration"] / 2) <= 0.006, "Selected source beat is not centred")
    return value


async def editor_round(page, result):
    started = time.perf_counter()
    await navigate(page, "edit")
    await wait_edit(page)
    await page.wait_for_function("""() => [...document.querySelectorAll('#editTemplateGallery .occurrence-tile')].some(n =>
        n.querySelector('.occurrence-wave svg') && n.occurrenceItem?.sample_index/200>state.editDuration/2+1
        && n.occurrenceItem.sample_index/200<state.caseData.technical.duration_seconds_raw-state.editDuration/2-1)""")
    candidate = await page.evaluate("""() => {
        const total=state.caseData.technical.duration_seconds_raw;
        return [...document.querySelectorAll('#editTemplateGallery .occurrence-tile')].map(n=>({
            index:Number(n.dataset.occIndex),sample:n.occurrenceItem?.sample_index,
            top:n.offsetTop,hasWave:!!n.querySelector('.occurrence-wave svg')
        })).find(n=>n.hasWave && n.sample/200>state.editDuration/2+1 && n.sample/200<total-state.editDuration/2-1);
    }""")
    require(candidate is not None, "No non-boundary mathematical source beat is available in the real editor")
    selector = '#editTemplateGallery .occurrence-tile[data-occ-index="' + str(candidate["index"]) + '"]'
    card = page.locator(selector)
    await card.scroll_into_view_if_needed()
    await card.locator(".occurrence-open").click()
    await page.wait_for_function("""(sample) => state.editSelectedSample===sample && state.editWaveform?.leads
        && Math.abs(state.editWaveform.start_s-state.editStart)<0.006
        && Math.abs(state.editWaveform.duration_s-state.editDuration)<0.006""", arg=candidate["sample"])
    await two_frames(page)
    before = await page.evaluate(SNAPSHOT_JS)
    await card.locator(".occurrence-wave svg").dblclick()
    full = await full_twelve(page, candidate["sample"])
    await escape_edit(page)
    after = await page.evaluate(SNAPSHOT_JS)
    require(before == after, "Thumbnail twelve-lead return changed editor window, selection or scroll")
    record(result, "thumbnail-double-click-exact-source-twelve-lead-return", {"edge_clamped": full["edge"], "lead_count": 12})

    canvas = page.locator("#editWaveformCanvas")
    await canvas.click()
    await two_frames(page)
    before = await page.evaluate(SNAPSHOT_JS)
    bottom_leads = await page.evaluate("() => ECGChartInspection.names(state.editWaveform.leads)")
    require(len(bottom_leads) == 3, "Bottom editor waveform must show three actual native leads")
    await canvas.dblclick()
    full = await full_twelve(page)
    require(abs(full["start"] - before["start"]) <= 0.006, "Three-lead expansion changed the source time window")
    await escape_edit(page)
    after = await page.evaluate(SNAPSHOT_JS)
    # A double-click contains normal selection clicks; the view contract preserves
    # the clinical selection collection, window and current source class.
    for key in ("mode", "start", "duration", "lead", "selectedClass", "selected", "galleryScroll"):
        require(before[key] == after[key], "Three-lead return changed editor " + key)
    record(result, "three-lead-double-click-twelve-lead-return", {"bottom_lead_count": len(bottom_leads), "expanded_lead_count": 12})
    return time.perf_counter() - started, selector, candidate["sample"]


async def stt_range(page):
    started = time.perf_counter()
    await navigate(page, "stt")
    await page.wait_for_function("() => state.sttEvidence && document.querySelector('#sttWaveCanvasWrap').dataset.sttWaveState==='ready'")
    await page.locator("[data-sttr-start]").fill("0")
    await page.locator("[data-sttr-end]").fill("60")
    async with page.expect_response(lambda response: urlsplit(response.url).path.endswith("/stt-range") and response.request.method == "POST") as pending:
        await page.locator('[data-sttr-action="calculate"]').click()
    response = await pending.value
    require(response.ok, "Native one-minute ST range request failed")
    native = await response.json()
    await page.wait_for_function("() => document.querySelector('#sttRangeReview')._sttRangeController?.state().result")
    require(native["schema_version"] == "stt-range-mean-v1", "ST mean must come from the native full-input algorithm")
    require(native["range"]["end_sample"] - native["range"]["start_sample"] == 12000, "ST range must cover a complete minute")
    counts = native["counts"]
    require(counts["detected_count"] == counts["used_count"] + counts["excluded_count"] + counts["missing_count"], "ST count accounting failed")
    require(counts["used_count"] > 0, "Mathematical minute has no usable native ST measurements")
    require(native.get("save_receipt", {}).get("kind") == "native-stt-range-hmac-v1", "Native ST receipt missing")
    require(await page.locator("[data-sttr-mean]").count() == len(native["leads"]), "ST UI omitted supplied native leads")
    for row in native["leads"]:
        text = await page.locator('[data-sttr-mean="' + row["lead"] + '"]').inner_text()
        require((text == "—") == (row["mean_units"] is None), "ST missing mean was converted to a numeric value")
        if row["mean_units"] is not None:
            displayed = float(text)
            require(abs(displayed - row["mean_units"]) <= 0.0005001, "ST displayed mean differs from the supplied native measurement")
        require(int(await page.locator('[data-sttr-used="' + row["lead"] + '"]').inner_text()) == row["used_count"], "ST displayed used-beat count differs from native evidence")
    return time.perf_counter() - started, {"duration_s": 60, "lead_count": len(native["leads"]), "counts": counts, "receipt_kind": native["save_receipt"]["kind"]}


async def hrv_round(page):
    started = time.perf_counter()
    await navigate(page, "trends")
    await page.locator("#hrvWindowPanel .hrv-continuous").wait_for(state="visible")
    native = await browser_json(page, "/api/cases/" + CASE_ID + "/hrv-analysis?window=0&analysis=edited")
    require(native["actual_duration_s"] == 86400 and native["start_s"] == 0 and native["end_s"] == 86400, "Native HRV does not cover full 24h")
    require(native["periods"]["full"]["nn_count"] > 0, "Native full-day NN set is empty")
    require(await page.locator("#hrvWindowPanel .hrv-continuous-trends table.hrvp-detail tbody tr").count() == len(native["hourly"]), "Continuous HRV omitted a supplied hourly row")
    paper = page.locator("#hrvWindowPanel details.hrv-paper-preview")
    require(await paper.count() == 1, "A4/PDF entry must occur once")
    require(await paper.evaluate("(node) => !node.open && node===node.parentElement.lastElementChild"), "A4/PDF entry must be folded at the end of continuous HRV")
    content = await page.locator("#hrvWindowPanel .hrv-continuous").inner_text()
    require("LF/HF" in content and "SDNN" in content and "设备单位" in content, "HRV continuous units or interpretation are missing")
    return time.perf_counter() - started, {"actual_duration_s": 86400, "native_hourly_rows": len(native["hourly"]), "rendered_hourly_rows": len(native["hourly"]), "nn_count": native["periods"]["full"]["nn_count"]}


async def report_ready(page):
    await navigate(page, "report")
    await page.locator('#reportV2Nav [data-category="final"]').click()
    await page.wait_for_function("() => !state.reportEvidenceLoading && !state.reportEvidenceError && !state.reportViewLoading && !state.reportViewError")
    await page.locator("#conclusionEditor").wait_for(state="visible")


async def save_math_work(page, result):
    await navigate(page, "stt")
    await page.wait_for_function("() => state.sttEvidence && document.querySelector('#sttWaveCanvasWrap').dataset.sttWaveState==='ready'")
    await page.locator("#sttFinding").select_option("无法判读")
    await page.locator("#sttReviewNote").fill(ANNOTATION_NOTE)
    await page.locator("#sttSignalChecked").check()
    async with page.expect_response(lambda response: urlsplit(response.url).path.endswith("/annotations") and response.request.method == "POST") as pending:
        await page.locator("#saveSttAnnotation").click()
    response = await pending.value
    require(response.ok, "Native mathematical annotation save failed")
    saved_annotation = await response.json()
    require(type(saved_annotation.get("id")) is int, "Native annotation response lacks its saved identity")
    await page.wait_for_function("() => !state.sttSaving")
    annotations = await browser_json(page, "/api/cases/" + CASE_ID + "/annotations")
    matching = [item for item in annotations["items"] if item.get("id") == saved_annotation["id"] and str(item.get("note", "")).endswith(ANNOTATION_NOTE)]
    require(len(matching) == 1, "Saved mathematical annotation is missing or duplicated")
    await report_ready(page)
    version = await page.evaluate("() => state.report.version")
    await page.locator("#conclusionEditor").fill(REPORT_NOTE)
    await page.locator("#saveReport").click()
    await page.wait_for_function("() => !state.reportSaving && !state.reportDirty && state.report.conclusion===" + json.dumps(REPORT_NOTE))
    report = await browser_json(page, "/api/cases/" + CASE_ID + "/report")
    require(report["conclusion"] == REPORT_NOTE and report["status"] == "draft" and report["version"] > version, "Native report draft was not saved")
    await navigate(page, "dashboard")
    await open_case(page)
    await report_ready(page)
    require(await page.locator("#conclusionEditor").input_value() == REPORT_NOTE, "Report draft did not survive reopen")
    record(result, "native-annotation-report-save-and-reopen", {"annotation_count": 1, "draft_version_increased": True, "status": "draft"})
    return saved_annotation["id"]


async def download_pdf(page, result, home):
    await report_ready(page)
    async with page.expect_response(lambda response: urlsplit(response.url).path.endswith("/report.pdf")) as native_pdf:
        async with page.expect_download() as pending:
            await page.locator("#downloadReport").click()
    response = await native_pdf.value
    require(response.ok and "application/pdf" in response.headers.get("content-type", ""), "Native PDF response has the wrong HTTP content type")
    download = await pending.value
    path = home / "temporary-report.pdf"
    await download.save_as(path)
    require(path.read_bytes().startswith(b"%PDF-") and path.stat().st_size > 1000, "Native report export did not produce an actual PDF")
    actual_hash = digest(path)
    require(response.headers.get("x-report-sha256") == actual_hash, "Downloaded PDF differs from the native report integrity header")
    record(result, "native-draft-pdf-download", {"bytes": path.stat().st_size, "sha256": actual_hash, "content_type": response.headers["content-type"], "native_integrity_header_matches": True, "artifact_published": False})
    path.unlink()


async def feedback_check(manager, result, home, states):
    async with manager.expect_request(lambda request: urlsplit(request.url).path == "/feedback" and request.method == "POST") as attachment_request:
        async with manager.expect_download() as pending:
            await manager.locator("#exportFeedback").click()
    download = await pending.value
    request = await attachment_request.value
    path = home / "temporary-feedback.zip"
    await download.save_as(path)
    with zipfile.ZipFile(path) as archive:
        require(archive.testzip() is None, "Feedback ZIP is corrupt")
        require(archive.namelist() == ["diagnostic.json"], "Feedback must contain only safe diagnostic.json")
        payload = archive.read("diagnostic.json")
        decoded = json.loads(payload)
    require(isinstance(decoded, dict), "Feedback diagnostic must be a JSON object")
    prohibited = [str(home), CASE_ID, REPORT_NOTE, ANNOTATION_NOTE] + [state["token"] for state in states]
    for value in prohibited:
        require(value not in payload.decode("utf-8") and value.replace("\\", "\\\\") not in payload.decode("utf-8"), "Feedback leaked source/workspace content or control credentials")
    def inspect(value):
        if isinstance(value, dict):
            for key, child in value.items():
                require(re.fullmatch(r"(?i)(patient.*|case_id|token|path|data_root|workspace_id|hostname|username|conclusion|annotations|raw_data)", str(key)) is None, "Feedback contains a prohibited identity/content field")
                inspect(child)
        elif isinstance(value, list):
            for child in value:
                inspect(child)
    inspect(decoded)
    record(result, "feedback-privacy-inventory", {"members": ["diagnostic.json"], "content_and_token_leaks": 0, "artifact_published": False})
    path.unlink()
    return request


async def persistence_check(page, result, name, annotation_id):
    await open_case(page)
    await report_ready(page)
    report = await browser_json(page, "/api/cases/" + CASE_ID + "/report")
    annotations = await browser_json(page, "/api/cases/" + CASE_ID + "/annotations")
    require(report["conclusion"] == REPORT_NOTE and report["status"] == "draft", "Preserved workspace lost its report draft")
    require(sum(item.get("id") == annotation_id and str(item.get("note", "")).endswith(ANNOTATION_NOTE) for item in annotations["items"]) == 1, "Preserved workspace lost or duplicated its annotation")
    require(await page.locator("#conclusionEditor").input_value() == REPORT_NOTE, "Reopened UI differs from preserved report")
    record(result, name, {"report_preserved": True, "annotation_preserved": True, "source_identity": "M01"})


async def fault_checks(page, result, editor_selector, sample):
    await navigate(page, "edit")
    await wait_edit(page)
    gate = asyncio.Event()
    seen = asyncio.Event()
    finished = asyncio.Event()
    request_terminal = asyncio.Event()
    held_request = {"request": None}
    def terminal(request):
        if request is held_request["request"]:
            request_terminal.set()
    page.on("requestfinished", terminal)
    page.on("requestfailed", terminal)
    async def hold_twelve(route):
        from urllib.parse import parse_qs
        leads = parse_qs(urlsplit(route.request.url).query).get("leads", [""])[0].split(",")
        if len(leads) != 12:
            await route.continue_()
            return
        held_request["request"] = route.request
        # Fetch the genuine native response before delaying delivery. Cancellation
        # therefore exercises a completed, unmodified source response arriving late.
        response = await route.fetch(timeout=TIMEOUT_MS)
        seen.set()
        await gate.wait()
        try:
            await route.fulfill(response=response)
        except Exception:
            pass  # The genuine request can already be aborted by the UI.
        finally:
            finished.set()
    await page.route("**/api/cases/*/waveform?*", hold_twelve)
    try:
        card = page.locator(editor_selector)
        await card.scroll_into_view_if_needed()
        await card.locator(".occurrence-wave svg").dblclick()
        await asyncio.wait_for(seen.wait(), 30)
        await page.wait_for_function("() => state.editFullscreenReturn?.readState==='loading'")
        await escape_edit(page)
        gate.set()
        await asyncio.wait_for(finished.wait(), 30)
        await asyncio.wait_for(request_terminal.wait(), 30)
        await two_frames(page)
        require(await page.evaluate("() => state.currentPage==='edit' && !state.waveformExpanded"), "Cancelled twelve-lead read returned to an obsolete view")
        record(result, "twelve-lead-cancel-real-delayed-request", {"fault": "transport-delay", "fabricated_algorithm_values": False})
    finally:
        gate.set()
        await page.unroute("**/api/cases/*/waveform?*", hold_twelve)
        page.remove_listener("requestfinished", terminal)
        page.remove_listener("requestfailed", terminal)

    aborted = {"value": False}
    async def fail_once(route):
        from urllib.parse import parse_qs
        leads = parse_qs(urlsplit(route.request.url).query).get("leads", [""])[0].split(",")
        if len(leads) == 12 and not aborted["value"]:
            aborted["value"] = True
            await route.abort("failed")
        else:
            await route.continue_()
    await page.route("**/api/cases/*/waveform?*", fail_once)
    try:
        card = page.locator(editor_selector)
        await card.scroll_into_view_if_needed()
        await card.locator(".occurrence-wave svg").dblclick()
        await page.locator("#editTwelveRetry").wait_for(state="visible")
        require(aborted["value"], "Twelve-lead transport fault did not reach the actual native request")
        await page.locator("#editTwelveRetry").click()
        await full_twelve(page, sample)
        await escape_edit(page)
        record(result, "twelve-lead-retry-real-native-response", {"fault": "one-transport-abort", "retry_response": "unmodified-native"})
    finally:
        await page.unroute("**/api/cases/*/waveform?*", fail_once)

    # This explicitly scoped renderer check removes one lead's trend points from
    # a real mathematical response. It does not invent means or diagnoses and is
    # separate from all native-algorithm and performance checks.
    partial = {"done": False}
    async def partial_trend(route):
        response = await route.fetch(timeout=TIMEOUT_MS)
        body = await response.json()
        body["analysis"]["trends"]["leads"]["V6"] = []
        partial["done"] = True
        await route.fulfill(response=response, json=body)
    await page.route("**/api/cases/*/stt-review?*", partial_trend)
    try:
        await navigate(page, "dashboard")
        await open_case(page)
        await navigate(page, "stt")
        await page.wait_for_function("() => state.sttEvidence && document.querySelector('#sttWaveCanvasWrap').dataset.sttWaveState==='ready'")
        require(partial["done"], "Partial-trend rendering fixture was not consumed")
        row = page.locator("#sttTrendRows .stt-trend-row").filter(has=page.locator("strong", has_text=re.compile("^V6$")))
        require("无有效块" in await row.inner_text(), "Missing V6 trend was presented as a normal numeric trend")
        require(await page.locator("#sttTrendRows .stt-trend-row").count() == 12, "Partial response removed another lead's capability row")
        require(await page.locator("#sttMeasurementList").inner_text() != "", "Partial trend response removed manual measurements")
        require(await page.locator("#sttCapabilityBadge").inner_text() == "自动筛查 · 待医生确认", "One missing trend disabled all native screening capability")
        record(result, "stt-partial-lead-rendering-fault-injection", {"injected_change": "V6 trend points removed", "scope": "rendering-only", "native_algorithm_result": False, "diagnosis_values_fabricated": False})
    finally:
        await page.unroute("**/api/cases/*/stt-review?*", partial_trend)
    await navigate(page, "dashboard")
    await open_case(page)
    await navigate(page, "stt")
    await page.wait_for_function("() => state.sttEvidence && document.querySelector('#sttWaveCanvasWrap').dataset.sttWaveState==='ready'")
    require(await page.evaluate("() => (state.sttReview.analysis.trends.leads.V6||[]).length>=2"), "Native response was not restored after rendering fault")


def metric_summary(rounds):
    names = ("manager_start", "case_open", "editor", "stt_60s", "hrv_24h")
    summary = {}
    for mode in ("process_first", "warm"):
        summary[mode] = {}
        for name in names:
            values = [round_[mode][name] for round_ in rounds if name in round_[mode]]
            if values:
                summary[mode][name] = {"samples_seconds": values, "median_seconds": statistics.median(values), "min_seconds": min(values), "max_seconds": max(values)}
    return summary


async def verify(args, receipt):
    from playwright.async_api import async_playwright

    package = args.package_root.resolve()
    original_exe = package / "CardioInsightDoctorEval.exe"
    require(original_exe.is_file() and pe_is_x64(original_exe), "Expected package-root/CardioInsightDoctorEval.exe x64")
    source_root, manifest, initial_sources = source_snapshot(package)
    receipt["source"] = {"source_id": "M01", "version": manifest["source_version"], "wholly_synthetic": True, "duration_seconds": 86400, "sample_rate_hz": 200, "sample_count": 17280000, "raw_bytes": SOURCE_BYTES, "manifest_sha256": initial_sources["source-manifest.json"]}
    receipt["runtime"] = {"frozen_executable": True, "pe_machine": "AMD64", "python_resolvable_in_runtime_path": False, "python_environment_removed": True, "process_images_match_frozen_exe": True}
    screenshots = args.output.parent / "browser-screenshots"
    screenshots.mkdir(parents=True, exist_ok=True)
    rounds = []
    receipt["performance"] = {
        "clock": "time.perf_counter", "unit": "seconds", "required_repeats": args.repeats,
        "rounds": rounds, "summary": {},
        "conditions": {"browser": "installed Microsoft Edge; same viewport; same executable and M01 SHA256", "process_first": "new native workspace process and empty mathematical work database per repeat; OS disk cache not cleared", "warm": "same workspace process; same UI controls, endpoints and ranges after one matching sequence", "sequence": ["case_open", "editor", "stt_60s", "hrv_24h"], "no_algorithm_or_response_replacement": True, "fault_injection_excluded_from_timings": True},
    }
    network = {"external_requests": 0, "external_hosts": [], "resource_failures": [], "page_errors": [], "intentional_transport_faults": 1, "cancelled_fetches": 0, "http_errors": []}
    receipt["network"] = network
    failed_resource_requests = []
    verified_attachment_requests = []
    private_values = [str(package), str(source_root)]
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(
            channel="msedge", headless=True,
            args=["--disable-background-networking", "--disable-component-update", "--disable-sync", "--no-first-run"],
        )
        receipt["browser"] = {"channel": "msedge", "version": browser.version, "installed_system_browser": True, "bundled_browser": False, "viewport": {"width": 1440, "height": 1000}}
        try:
            for iteration in range(args.repeats):
                with tempfile.TemporaryDirectory(prefix="doctor-browser-") as temporary:
                    container = Path(temporary)
                    home = container / "doctor-home"
                    home.mkdir()
                    private_values.append(str(container))
                    active_exe = original_exe
                    context = await browser.new_context(viewport={"width": 1440, "height": 1000}, accept_downloads=True, service_workers="block")
                    async def loopback_only(route):
                        host = urlsplit(route.request.url).hostname
                        if host not in ("127.0.0.1", "localhost", "::1") and urlsplit(route.request.url).scheme in ("http", "https", "ws", "wss"):
                            network["external_requests"] += 1
                            if host not in network["external_hosts"]:
                                network["external_hosts"].append(host)
                            await route.abort("blockedbyclient")
                        else:
                            await route.continue_()
                    await context.route("**/*", loopback_only)
                    def failed(request):
                        error = request.failure or ""
                        if request.resource_type in ("script", "stylesheet", "image", "font", "document"):
                            network["resource_failures"].append({"path": urlsplit(request.url).path, "type": request.resource_type, "error": error})
                            failed_resource_requests.append(request)
                        elif "ERR_ABORTED" in error:
                            network["cancelled_fetches"] += 1
                    def http_response(response):
                        if response.status >= 400:
                            network["http_errors"].append({"path": urlsplit(response.url).path, "status": response.status, "origin": response.request.headers.get("origin"), "fetch_site": response.request.headers.get("sec-fetch-site")})
                    def add_page(page):
                        page.set_default_timeout(TIMEOUT_MS)
                        page.set_default_navigation_timeout(TIMEOUT_MS)
                        page.on("pageerror", lambda error: network["page_errors"].append(safe_error(error, private_values)))
                        page.on("requestfailed", failed)
                        page.on("response", http_response)
                        async def accept_local_dialog(dialog):
                            if dialog.type in ("confirm", "beforeunload"):
                                await dialog.accept()
                            else:
                                await dialog.dismiss()
                        page.on("dialog", accept_local_dialog)
                    context.on("page", add_page)
                    try:
                        manager_state, start_seconds = await launch(active_exe, home, source_root)
                        private_values.append(manager_state["token"])
                        page = await manager_page(context, manager_state)
                        async with page.expect_response(lambda response: urlsplit(response.url).path == "/continue") as entry_request:
                            await page.locator("#continueExperience").click()
                        require((await entry_request.value).status == 303, "Native manager form could not enter the doctor workspace")
                        await worklist_ready(page)
                        catalog = json.loads((home / "catalog.json").read_text(encoding="utf-8"))
                        workspace_id = catalog["selected_workspace"]
                        workspace_state = await live_state(home, workspace_id, active_exe)
                        private_values.append(workspace_state["token"])
                        require(workspace_state["port"] != manager_state["port"], "Workspace API must use its own independent port")
                        module_evidence = await asyncio.to_thread(process_modules, workspace_state["pid"], active_exe)
                        record(receipt, "frozen-process-bundled-dependencies-repeat-" + str(iteration + 1), module_evidence)
                        source_selection_before = (home / "source-selection.json").read_bytes()
                        first = {"manager_start": start_seconds, "case_open": await open_case(page)}
                        first["editor"], selector, sample = await editor_round(page, receipt)
                        first["stt_60s"], stt_evidence = await stt_range(page)
                        record(receipt, "native-one-minute-full-input-stt", stt_evidence)
                        first["hrv_24h"], hrv_evidence = await hrv_round(page)
                        record(receipt, "native-24h-hrv-continuous-and-final-a4", hrv_evidence)

                        round_metrics = {"repeat": iteration + 1, "process_first": first, "warm": {}}
                        rounds.append(round_metrics)
                        receipt["performance"]["summary"] = metric_summary(rounds)
                        await navigate(page, "dashboard")
                        warm = round_metrics["warm"]
                        warm["case_open"] = await open_case(page)
                        warm["editor"], _, _ = await editor_round(page, receipt)
                        warm["stt_60s"], _ = await stt_range(page)
                        warm["hrv_24h"], _ = await hrv_round(page)
                        receipt["performance"]["completed_repeats"] = len(rounds)
                        receipt["performance"]["summary"] = metric_summary(rounds)
                        record(receipt, "frozen-exe-independent-workspace-repeat-" + str(iteration + 1), {"runtime_python_path_absent": True, "manager_and_child_images": "actual-doctor-exe", "full_day": True})

                        if iteration == 0:
                            from verify_lasso_browser import verify_lasso
                            lasso = await verify_lasso(page, source_root, screenshots / "mathematical-free-lasso.png")
                            record(receipt, "native-free-lasso-complete-cohort", lasso)
                            await fault_checks(page, receipt, selector, sample)
                            annotation_id = await save_math_work(page, receipt)
                            await download_pdf(page, receipt, home)
                            await page.screenshot(path=str(screenshots / "mathematical-report-draft.png"), full_page=True)
                            record(receipt, "mathematical-only-screenshot", {"file": "browser-screenshots/mathematical-report-draft.png"})
                            manager = await manager_page(context, manager_state)
                            async with manager.expect_popup() as new_popup:
                                await manager.locator("#newExperience").click()
                            new_page = await new_popup.value
                            await worklist_ready(new_page)
                            new_catalog = json.loads((home / "catalog.json").read_text(encoding="utf-8"))
                            new_workspace_id = new_catalog["selected_workspace"]
                            require(new_workspace_id != workspace_id and workspace_id in new_catalog["workspaces"], "New workspace replaced or removed old work")
                            new_workspace_state = await live_state(home, new_workspace_id, active_exe)
                            private_values.append(new_workspace_state["token"])
                            require(new_workspace_state["port"] not in (manager_state["port"], workspace_state["port"]), "Workspaces shared an API port")
                            require(new_workspace_state["pid"] != workspace_state["pid"], "Workspaces shared a native process")
                            await open_case(new_page)
                            fresh_report = await browser_json(new_page, "/api/cases/" + CASE_ID + "/report")
                            fresh_annotations = await browser_json(new_page, "/api/cases/" + CASE_ID + "/annotations")
                            require(fresh_report["conclusion"] != REPORT_NOTE and not fresh_annotations["items"], "New workspace inherited old doctor's modifications")
                            preserved = await browser_json(page, "/api/cases/" + CASE_ID + "/report")
                            require(preserved["conclusion"] == REPORT_NOTE, "Old tab changed after a new workspace was created")
                            require((home / "workspaces" / workspace_id / "data" / "cardioinsight.db").is_file(), "Old workspace database was removed")
                            record(receipt, "new-workspace-preserves-old-work-and-independent-api", {"independent_ports": True, "independent_processes": True, "old_database_preserved": True, "new_work_clean": True})
                            await manager.reload(wait_until="domcontentloaded")
                            verified_attachment_requests.append(await feedback_check(manager, receipt, home, [manager_state, workspace_state, new_workspace_state]))
                            workspace_before_upgrade = json.loads((home / "workspaces" / workspace_id / "WORKSPACE.json").read_text(encoding="utf-8"))
                            await context.close()
                            await stop(active_exe, home)

                            # Same-schema upgrade: use the software-only delivery in
                            # a second directory and keep this exact user home/source.
                            destination = container / "second-program"
                            delivery = unpack_software(args.software_archive, package, destination)
                            original_release = json.loads((package / "RELEASE.json").read_text(encoding="utf-8"))
                            next_release = json.loads((destination / "RELEASE.json").read_text(encoding="utf-8"))
                            if args.software_archive is not None:
                                require(next_release.get("verification_fixture_only") is True, "Upgrade archive must be explicitly marked as a CI-only fixture")
                                require(tuple(map(int, next_release["packaging_version"].split("."))) > tuple(map(int, original_release["packaging_version"].split("."))), "Expected a newer CI same-core packaging-version fixture")
                                require(original_release["app_version"] == next_release["app_version"], "Upgrade fixture changed the native application version")
                                require(original_release["source_manifest_sha256"] == next_release["source_manifest_sha256"], "Upgrade fixture changed the source manifest")
                            active_exe = destination / "CardioInsightDoctorEval.exe"
                            require(pe_is_x64(active_exe), "Software update must remain x64")
                            require(not (destination / "Sources").exists(), "Software update copied or replaced source data")
                            require(digest(active_exe) == digest(original_exe), "Equivalent-wrapper upgrade must use the exact frozen EXE")
                            context = await browser.new_context(viewport={"width": 1440, "height": 1000}, accept_downloads=True, service_workers="block")
                            context.on("page", add_page)
                            await context.route("**/*", loopback_only)
                            manager_state, _ = await launch(active_exe, home)
                            private_values.append(manager_state["token"])
                            resumed = await resume(context, manager_state, workspace_id)
                            await live_state(home, workspace_id, active_exe)
                            await persistence_check(resumed, receipt, "software-only-same-schema-upgrade-preserves-work", annotation_id)
                            workspace_after_upgrade = json.loads((home / "workspaces" / workspace_id / "WORKSPACE.json").read_text(encoding="utf-8"))
                            if args.software_archive is not None:
                                record(receipt, "fixture-same-schema-upgrade-backup-and-schema-gate", upgrade_receipt(home, workspace_id, workspace_before_upgrade, workspace_after_upgrade))
                            else:
                                record(receipt, "same-version-software-directory-reinstall", {"kind": "same-version-reinstall-only", "upgrade_version_gate_tested": False})
                            _, _, current_sources = source_snapshot(package)
                            require(current_sources == initial_sources, "Source changed during software-only upgrade")
                            require((home / "source-selection.json").read_bytes() == source_selection_before, "Upgrade silently rebound source selection")
                            record(receipt, "software-only-upgrade-source-sha256-unchanged", {"delivery": delivery, "same_schema_only": True, "future_schema_migration_tested": False, "source_copied": False, "source_hashes_unchanged": True, "registered_source_unchanged": True})
                            # Select the upgraded workspace before checking the
                            # older wrapper: the compatibility gate is per workspace.
                            selected_manager = await manager_page(context, manager_state)
                            await expand_previous(selected_manager)
                            await selected_manager.locator("#previousWorkspace").select_option(workspace_id)
                            async with selected_manager.expect_popup() as select_popup:
                                await selected_manager.locator("#resumePrevious").click()
                            selected_page = await select_popup.value
                            await worklist_ready(selected_page)
                            require(json.loads((home / "catalog.json").read_text(encoding="utf-8"))["selected_workspace"] == workspace_id, "Upgraded workspace was not selected for the old-version gate")
                            await context.close()
                            await stop(active_exe, home)
                            if args.software_archive is not None:
                                preserved_metadata = (home / "workspaces" / workspace_id / "WORKSPACE.json").read_bytes()
                                preserved_database = digest(home / "workspaces" / workspace_id / "data" / "cardioinsight.db")
                                rejection = await asyncio.to_thread(run_cli, original_exe, home, "launch", "--no-browser")
                                require(rejection.returncode != 0, "Older wrapper opened a workspace created by a newer package")
                                require((home / "workspaces" / workspace_id / "WORKSPACE.json").read_bytes() == preserved_metadata, "Rejected older wrapper changed workspace metadata")
                                require(digest(home / "workspaces" / workspace_id / "data" / "cardioinsight.db") == preserved_database, "Rejected older wrapper wrote the upgraded database")
                                require((home / "source-selection.json").read_bytes() == source_selection_before, "Rejected older wrapper rebound the registered source")
                                for state_path in (home / "runtime").glob("*.json"):
                                    try:
                                        stale_state = json.loads(state_path.read_text(encoding="utf-8"))
                                        await asyncio.to_thread(health, stale_state)
                                    except (OSError, ValueError, KeyError, URLError):
                                        continue
                                    raise AssertionError("Rejected older wrapper started a native service")
                                record(receipt, "older-wrapper-rejects-newer-workspace-before-write", {"rejected": True, "native_service_started": False, "database_sha256_unchanged": True, "metadata_unchanged": True})

                            context = await browser.new_context(viewport={"width": 1440, "height": 1000}, accept_downloads=True, service_workers="block")
                            context.on("page", add_page)
                            await context.route("**/*", loopback_only)
                            manager_state, _ = await launch(active_exe, home)
                            private_values.append(manager_state["token"])
                            resumed = await resume(context, manager_state, workspace_id)
                            await live_state(home, workspace_id, active_exe)
                            await persistence_check(resumed, receipt, "frozen-exe-stop-relaunch-preserves-work", annotation_id)
                    finally:
                        await context.close()
                        try:
                            await stop(active_exe, home)
                        except Exception as shutdown_error:
                            record(receipt, "graceful-shutdown", {"error": safe_error(shutdown_error, private_values)}, status="failed")
        finally:
            await browser.close()
    _, _, final_sources = source_snapshot(package)
    require(final_sources == initial_sources, "Original mathematical source changed during browser verification")
    require(network["external_requests"] == 0, "The doctor page attempted a non-loopback network request")
    # A native Content-Disposition attachment cancels the document navigation
    # after the browser starts the download. Exempt only the exact request whose
    # downloaded ZIP has already passed CRC, member and privacy verification.
    unexpected_resources = []
    attachment_aborts = []
    require(len(failed_resource_requests) == len(network["resource_failures"]), "Resource observation accounting changed")
    for request, failure in zip(failed_resource_requests, network["resource_failures"]):
        if (failure["type"] == "document" and failure["error"] == "net::ERR_ABORTED"
                and any(request is verified for verified in verified_attachment_requests)):
            attachment_aborts.append({**failure, "download_archive_verified": True})
        else:
            unexpected_resources.append(failure)
    network["verified_attachment_navigation_aborts"] = attachment_aborts
    network["resource_failures"] = unexpected_resources
    require(not network["resource_failures"], "A local browser resource failed to load")
    require(not network["page_errors"], "Uncaught browser page errors occurred")
    require(not network["http_errors"], "A native HTTP request failed")
    require(len(rounds) == args.repeats, "Performance repetition count incomplete")
    receipt["performance"] = {
        "clock": "time.perf_counter", "unit": "seconds", "repeats": args.repeats,
        "conditions": {"browser": "installed Microsoft Edge; same viewport; same executable and M01 SHA256", "process_first": "new native workspace process and empty mathematical work database per repeat; OS disk cache not cleared", "warm": "same workspace process; same UI controls, endpoints and ranges after one matching sequence", "sequence": ["case_open", "editor", "stt_60s", "hrv_24h"], "no_algorithm_or_response_replacement": True, "fault_injection_excluded_from_timings": True},
        "rounds": rounds, "summary": metric_summary(rounds),
    }
    record(receipt, "browser-loopback-only-resources-and-source-integrity", {"external_requests": 0, "local_resource_failures": 0, "page_errors": 0, "source_sha256_unchanged": True})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--software-archive", type=Path, help="Actual software-only ZIP to test in a second program directory")
    parser.add_argument("--repeats", type=int, choices=(3, 4, 5), default=3)
    args = parser.parse_args()
    args.output = args.output.resolve()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    win = platform.win32_ver()
    receipt = {
        "schema_version": 1, "status": "running", "started_utc": datetime.now(timezone.utc).isoformat(),
        "platform": {"system": platform.system(), "release": platform.release(), "version": platform.version(), "machine": platform.machine(), "pointer_bits": struct.calcsize("P") * 8, "windows_release": win[0], "windows_version": win[1], "windows_edition": win[2]},
        "scope": {"mathematical_source_only": True, "native_frozen_runtime": True, "browser_validation": True, "clinical_validation": False, "windows_10_physical_machine_validation": False, "future_database_migrations_verified": False, "clean_windows_without_installed_python_verified": False, "hospital_edr_verified": False, "code_signing_verified": False, "chinese_pdf_glyphs_manually_reviewed": False, "browser_network_observation": "page requests in the instrumented Edge contexts; not all OS network traffic"},
        "limitations": ["Windows 10 compatibility target and actual CI operating system are reported separately.", "Process-first timings do not claim a cleared OS disk cache.", "ST partial-lead fault injection checks rendering only; native ST/HRV measurements use unmodified full mathematical input.", "The upgrade test covers the current same schema and frozen core; it does not prove future migrations.", "The CI machine can have Python and Visual Studio installed: a stripped runtime PATH and bundled DLL observations do not constitute clean Windows 10, hospital EDR or unsigned-executable acceptance.", "PDF download structure is checked; Chinese glyph appearance and physical printing require visual review."],
        "checks": [],
    }
    try:
        require(os.name == "nt" and struct.calcsize("P") * 8 == 64, "This verification requires an actual Windows x64 runner")
        asyncio.run(verify(args, receipt))
        receipt["status"] = "passed" if all(check["status"] == "passed" for check in receipt["checks"]) else "failed"
    except Exception as error:
        receipt["status"] = "failed"
        receipt["failure_location"] = [
            {"file": Path(frame.filename).name, "function": frame.name, "line": frame.lineno}
            for frame in traceback.extract_tb(error.__traceback__)
            if Path(frame.filename).name == Path(__file__).name]
        record(receipt, "browser-verification-completion", {"error": safe_error(error, [str(args.package_root), str(args.output.parent)])}, status="failed")
    finally:
        receipt["completed_utc"] = datetime.now(timezone.utc).isoformat()
        args.output.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("DOCTOR_BROWSER_RECEIPT_JSON=" + json.dumps(receipt, ensure_ascii=False))
    print(json.dumps({"status": receipt["status"], "checks": len(receipt["checks"]), "receipt": args.output.name}, ensure_ascii=False))
    return 0 if receipt["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
