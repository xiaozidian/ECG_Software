#!/usr/bin/env python3
"""Build an allowlisted, offline Windows x64 doctor evaluation ZIP.

Only explicit software assets and freshly generated mathematical data are packaged.
Never copy a workspace, source checkout, hospital data, private evidence or database.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from hashlib import sha256
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import zipfile

ASSET_FILES = (
    "static/css/advanced-analysis.css",
    "static/css/app.css",
    "static/css/beat-editor.css",
    "static/css/chart-inspection.css",
    "static/css/clinical-review-tools.css",
    "static/css/clinical-ui.css",
    "static/css/clinical-workflow.css",
    "static/css/dashboard-icons.css",
    "static/css/desktop-workspace.css",
    "static/css/hrv-review-editor.css",
    "static/css/hrv-review-evidence.css",
    "static/css/morphology-workbench.css",
    "static/css/overview-workbench.css",
    "static/css/report-paper.css",
    "static/css/report-workspace.css",
    "static/css/rhythm-range-editor.css",
    "static/css/rr-review-workbench.css",
    "static/css/shared-ui-review.css",
    "static/css/sidebar-workflow.css",
    "static/css/stt-range-review.css",
    "static/css/stt-review-layout.css",
    "static/css/terminology-tree.css",
    "static/css/visual-refresh.css",
    "static/css/voltage-estimate.css",
    "static/icon.svg",
    "static/js/advanced-analysis.js",
    "static/js/af-coverage.js",
    "static/js/analysis-consistency.js",
    "static/js/app.js",
    "static/js/beat-editor-ui.js",
    "static/js/beat-engine.js",
    "static/js/chart-inspection.js",
    "static/js/clinical-analysis.js",
    "static/js/clinical-review-tools.js",
    "static/js/clinical-ui.js",
    "static/js/clinical-workflow.js",
    "static/js/desktop-workspace.js",
    "static/js/hrv-analysis.js",
    "static/js/hrv-report.js",
    "static/js/hrv-review-editor.js",
    "static/js/hrv-review-evidence.js",
    "static/js/linked-selection.js",
    "static/js/morphology-groups.js",
    "static/js/morphology-workbench.js",
    "static/js/occurrence-card.js",
    "static/js/overview-engine.js",
    "static/js/overview-linked-view.js",
    "static/js/overview-workbench.js",
    "static/js/read-requests.js",
    "static/js/report-consistency.js",
    "static/js/report-engine.js",
    "static/js/report-paper.js",
    "static/js/report-range-editor.js",
    "static/js/report-sections.js",
    "static/js/report-workspace.js",
    "static/js/rhythm-range-editor.js",
    "static/js/rr-quality.js",
    "static/js/rr-review-bridge.js",
    "static/js/rr-review-workbench.js",
    "static/js/source-group-evidence.js",
    "static/js/stt-range-bridge.js",
    "static/js/stt-range-review.js",
    "static/js/stt-review-layout.js",
    "static/js/template-linked-view.js",
    "static/js/terminology-tree.js",
    "static/js/voltage-estimate.js",
    "static/js/waveform-loader.js",
    "static/js/workspace-backup.js",
    "static/terminology/builtin-draft-v1.json",
    "templates/index.html",
)
APP_NAME = "CardioInsightDoctorEval"
PACKAGE_NAME = "CardioInsight-DoctorEval-Windows-x64"
CASE_ID = "9900000000000001"
SOURCE_FILES = (
    f"{CASE_ID}/data/{CASE_ID}.DATA",
    f"{CASE_ID}/DGS/{CASE_ID}.EBI",
    f"{CASE_ID}/report_image/{CASE_ID}_1.LPS",
    "events.json",
    "source-manifest.json",
)
ROOT_FILES = frozenset({
    APP_NAME + ".exe", "RELEASE.json", "使用说明.txt", "版本说明.txt",
    "启动医生评估.cmd", "新建评估工作区.cmd", "检查医生评估.cmd",
    "停止医生评估.cmd", "导出诊断反馈.cmd", "CONTENTS.json", "SHA256SUMS.txt",
})
FORBIDDEN_EXTENSIONS = frozenset({".db", ".sqlite", ".sqlite3", ".ecgbackup", ".pdf", ".data", ".ebi", ".lps"})
FORBIDDEN_COMPONENTS = frozenset({"docs", "demo", "tests", "pytest", "playwright", "chromium", "chrome", "electron", "scipy", "pandas", "matplotlib", "ipython"})


class PackageError(ValueError):
    pass


def digest(path):
    value = sha256()
    with Path(path).open("rb") as stream:
        for part in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(part)
    return value.hexdigest()


def write_json(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")


def regular_files(root):
    root = Path(root)
    result = {}
    for path in sorted(root.rglob("*")):
        if path.is_symlink() or (hasattr(path, "is_junction") and path.is_junction()):
            raise PackageError("Package contains a linked entry: " + path.relative_to(root).as_posix())
        if path.is_file():
            result[path.relative_to(root).as_posix()] = path
        elif not path.is_dir():
            raise PackageError("Package contains a non-regular entry.")
    return result


def validate_assets(root):
    root = Path(root)
    for relative in ASSET_FILES:
        path = root / relative
        if not path.is_file() or path.is_symlink():
            raise PackageError("Allowlisted software asset is absent or linked: " + relative)
        if any(parent.is_symlink() for parent in path.parents if parent != root and root in parent.parents):
            raise PackageError("Allowlisted software asset has a linked parent: " + relative)


def validate_source(source):
    source = Path(source)
    actual = regular_files(source)
    if set(actual) != set(SOURCE_FILES):
        raise PackageError("Synthetic source does not contain exactly the approved five files.")
    document = json.loads(actual["source-manifest.json"].read_text(encoding="utf-8"))
    if document.get("wholly_synthetic") is not True:
        raise PackageError("The source is not explicitly wholly synthetic.")
    expected = {
        "schema_version": 1, "source_id": "M01", "case_id": CASE_ID,
        "source_version": "M01-24h-v1",
        "wholly_synthetic": True, "duration_seconds": 86400.0,
        "sampling_rate_hz": 200, "sample_count": 17280000,
        "expected_raw_bytes": 276480000,
        "stored_channels": ["I", "II", "V1", "V2", "V3", "V4", "V5", "V6"],
    }
    for key, value in expected.items():
        if document.get(key) != value:
            raise PackageError("Synthetic source manifest contract is invalid: " + key)
    entries = document.get("files")
    if not isinstance(entries, list) or len(entries) != 4:
        raise PackageError("Synthetic source manifest must describe exactly four payload files.")
    declared = {}
    for entry in entries:
        if not isinstance(entry, dict) or set(entry) != {"path", "size_bytes", "sha256"}:
            raise PackageError("Synthetic file manifest entry is invalid.")
        name = entry["path"]
        if name not in set(SOURCE_FILES) - {"source-manifest.json"} or name in declared:
            raise PackageError("Synthetic file manifest path is invalid or duplicated.")
        path = actual[name]
        if type(entry["size_bytes"]) is not int or entry["size_bytes"] != path.stat().st_size:
            raise PackageError("Synthetic source size does not match its manifest.")
        if entry["sha256"] != digest(path):
            raise PackageError("Synthetic source hash does not match its manifest.")
        declared[name] = entry
    if set(declared) != set(SOURCE_FILES) - {"source-manifest.json"}:
        raise PackageError("Synthetic source file manifest is incomplete.")
    if actual[SOURCE_FILES[0]].stat().st_size != 276480000:
        raise PackageError("The packaged waveform is not one complete 24-hour record.")
    return document


def package_inventory(package, *, with_source=True):
    package = Path(package)
    files = regular_files(package)
    expected_sources = {"Sources/M01/" + name for name in SOURCE_FILES}
    actual_sources = {name for name in files if name.startswith("Sources/")}
    if actual_sources != (expected_sources if with_source else set()):
        raise PackageError("Package source directory is outside the synthetic allowlist.")
    expected_assets = {"_internal/" + name for name in ASSET_FILES}
    actual_assets = {name for name in files if name.startswith(("_internal/static/", "_internal/templates/"))}
    if actual_assets != expected_assets:
        raise PackageError("Bundled application assets differ from the explicit software allowlist.")
    for name, path in files.items():
        if name in expected_sources:
            continue
        parts = name.split("/")
        if len(parts) == 1:
            if name not in ROOT_FILES:
                raise PackageError("Unexpected file in the package root: " + name)
        elif parts[0] != "_internal":
            raise PackageError("Unexpected directory in the package: " + name)
        if path.suffix.lower() in FORBIDDEN_EXTENSIONS or any(part.lower() in FORBIDDEN_COMPONENTS for part in parts):
            raise PackageError("Forbidden runtime data or dependency in the software package: " + name)
    return {name: {"size_bytes": path.stat().st_size, "sha256": digest(path)}
            for name, path in files.items()}


def create_content_manifest(package, *, with_source=True):
    payload = package_inventory(package, with_source=with_source)
    # These two integrity files cannot contain their own hashes. The ZIP itself
    # has a separate SHA256 sidecar covering both of them.
    for name in ("CONTENTS.json", "SHA256SUMS.txt"):
        payload.pop(name, None)
    write_json(Path(package) / "CONTENTS.json", {
        "schema_version": 1, "algorithm": "sha256", "files": payload,
        "package_kind": "full_install" if with_source else "software_only",
        "self_excluded_files": ["CONTENTS.json", "SHA256SUMS.txt"],
    })
    hashes = dict(payload)
    hashes["CONTENTS.json"] = {"sha256": digest(Path(package) / "CONTENTS.json")}
    (Path(package) / "SHA256SUMS.txt").write_text(
        "".join(item["sha256"] + "  " + name + "\n" for name, item in sorted(hashes.items())),
        encoding="utf-8")


def verify_content_manifest(package):
    package = Path(package)
    value = json.loads((package / "CONTENTS.json").read_text(encoding="utf-8"))
    kind = value.get("package_kind")
    if kind not in {"full_install", "software_only"}:
        raise PackageError("Content manifest package kind is invalid.")
    current = package_inventory(package, with_source=kind == "full_install")
    current.pop("CONTENTS.json", None)
    current.pop("SHA256SUMS.txt", None)
    if value.get("schema_version") != 1 or value.get("algorithm") != "sha256" or value.get("files") != current:
        raise PackageError("Package content manifest does not match its full payload.")
    expected = dict(current)
    expected["CONTENTS.json"] = {"sha256": digest(package / "CONTENTS.json")}
    sums = "".join(item["sha256"] + "  " + name + "\n" for name, item in sorted(expected.items()))
    if (package / "SHA256SUMS.txt").read_text(encoding="utf-8") != sums:
        raise PackageError("Package SHA256SUMS file is invalid.")


README = """CardioInsight 医生功能评估便携版（Windows x64）
目标：Windows 10 x64；医院电脑架构及允许运行条件仍需确认。
此包未经过医院 Windows 10 实机验证。具体构建系统见 RELEASE.json。

1. 将整个 ZIP 解压到自己的普通用户目录。保持 Sources 和 _internal 完整。
2. 双击 CardioInsightDoctorEval.exe，在系统浏览器中使用软件。
    “启动医生评估.cmd”也可用于辅助启动和查看错误。
   仅监听本机回环地址；无需安装 Python、Docker、Chrome 或 Electron。
3. 评估内置 M01 为连续24小时的纯数学合成记录，没有任何患者输入。
   合成情节用于功能体验，不代表临床金标准；电压与设备导联映射尚未独立核验。
4. 保存报告、注释、模板和复核修改后再停止。未提交的网页修改不会自动保存。
   保存工作使用独立用户工作区；软件目录和合成源文件不会被当作工作库。
5. “新建评估工作区.cmd”创建新工作区并保留旧记录。旧网页不能向新工作区提交。
6. “检查医生评估.cmd”用于查看状态。“停止医生评估.cmd”按提示停止本评估服务。
7. “导出诊断反馈.cmd”只在自己明确选择后导出。默认不含合成源文件、数据库、
   患者文件或未保存修改；涉及工作内容时请逐项确认。不会自动上传或发送。
8. 此工程评估包未做 Authenticode 签名。系统拦截时请遵循医院管理员的处理流程。

合成练习定位（软件相对记录时间，不是墙钟时间）：
房早短阵 01:15–01:16:30；室早短阵 05:30–05:31:10。
ST负偏移 07:30–07:34；ST正偏移 10:30–10:35，范围均值至少选择60秒。
房颤样人工标注练习 12:00–12:20；伪差15:30–15:32；零填充缺口19:00–19:00:12。
这些时段为生成器参考情节，不是临床诊断或真实患者记录。

软件升级：
先保存并停止评估服务；保留原软件目录、Sources和用户工作区。
把标为software的软件升级ZIP解压到一个新用户目录，不覆盖旧目录。
新程序复用已登记的M01合成来源与已保存工作，不要求重新下载整天数据。
若提示需要明确选择来源，请选择原包的Sources/M01，不选择医院病例目录。
版本迁移会按程序提示备份。保留旧版本与备份；不要用旧程序直接写已升级的数据库。
需要回退时应从备份恢复到新工作区，不能覆盖正在使用的工作库。
首版不提供自动降级恢复按钮；迁移副本需由维护人员核验后恢复至独立工作区。
独立数据ZIP只用于首次布置或恢复缺失的合成来源；其版本和哈希应与RELEASE.json一致。

校验：CONTENTS.json列出全部有效载荷文件的大小与SHA256；
SHA256SUMS.txt同时包含CONTENTS.json的校验值。这两个校验文件自身不互相递归校验。
ZIP旁的.sha256覆盖整个ZIP。校验值用于发现文件变化，不等同于可信数字签名。
"""


def create_build_icon(path):
    """Render the project ECG motif as Windows icon resources, without external assets."""
    from PIL import Image, ImageDraw
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    image = Image.new("RGBA", (256, 256), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((4, 4, 252, 252), radius=58, fill="#17697b")
    points = [(32, 136), (80, 136), (104, 72), (140, 192),
              (168, 116), (188, 136), (224, 136)]
    draw.line(points, fill="white", width=12, joint="curve")
    image.save(path, format="ICO", sizes=[(16, 16), (32, 32), (48, 48),
                                          (64, 64), (128, 128), (256, 256)])
    return path

def add_launchers(package):
    commands = {
        "启动医生评估.cmd": "launch",
        "新建评估工作区.cmd": "new",
        "检查医生评估.cmd": "check",
        "停止医生评估.cmd": "stop",
        "导出诊断反馈.cmd": "feedback",
    }
    for name, command in commands.items():
        text = ('@echo off\r\nsetlocal\r\n'
                '"%~dp0' + APP_NAME + '.exe" ' + command + '\r\n'
                'if errorlevel 1 pause\r\nendlocal\r\n')
        (Path(package) / name).write_bytes(text.encode("ascii"))
    (Path(package) / "使用说明.txt").write_text(README, encoding="utf-8-sig")


def archive_and_extract(package, output, filename, *, with_source=True, verify_subdir=None):
    package, output = Path(package), Path(output)
    archive = output / filename
    with zipfile.ZipFile(archive, "x", compression=zipfile.ZIP_DEFLATED, compresslevel=6, allowZip64=True) as z:
        for name, path in regular_files(package).items():
            z.write(path, arcname=PACKAGE_NAME + "/" + name)
    archive_sha = digest(archive)
    (output / (archive.name + ".sha256")).write_text(archive_sha + "  " + archive.name + "\n", encoding="ascii")
    verify_root = output / (verify_subdir or ("verify-package" if with_source else "verify-software-package"))
    with zipfile.ZipFile(archive) as z:
        for member in z.infolist():
            parts = member.filename.split("/")
            if parts[0] != PACKAGE_NAME or any(part in {"", ".", ".."} for part in parts) or "\\" in member.filename:
                raise PackageError("Archive member path is invalid.")
        if z.testzip() is not None:
            raise PackageError("Archive CRC verification failed.")
        z.extractall(verify_root)
    unpacked = verify_root / PACKAGE_NAME
    verify_content_manifest(unpacked)
    if with_source:
        validate_source(unpacked / "Sources" / "M01")
    return archive, archive_sha, unpacked


def create_source_archive(source, output, version):
    source, output = Path(source), Path(output)
    validate_source(source)
    name = "CardioInsight-Synthetic-" + version + ".zip"
    archive = output / name
    with zipfile.ZipFile(archive, "x", compression=zipfile.ZIP_DEFLATED, compresslevel=6, allowZip64=True) as z:
        for relative, path in regular_files(source).items():
            z.write(path, arcname="M01/" + relative)
    archive_sha = digest(archive)
    (output / (name + ".sha256")).write_text(archive_sha + "  " + name + "\n", encoding="ascii")
    write_json(output / (name + ".manifest.json"), {
        "schema_version": 1, "source_id": "M01", "source_version": version,
        "archive": name, "archive_sha256": archive_sha, "archive_size_bytes": archive.stat().st_size,
        "source_manifest_sha256": digest(source / "source-manifest.json"),
        "files": {relative: {"size_bytes": path.stat().st_size, "sha256": digest(path)}
                  for relative, path in regular_files(source).items()},
        "wholly_synthetic": True, "patient_inputs_read": False,
    })
    with zipfile.ZipFile(archive) as z:
        if z.testzip() is not None:
            raise PackageError("Synthetic source archive CRC verification failed.")
    return archive, archive_sha


def run(command, *, cwd, env=None):
    subprocess.run([str(part) for part in command], cwd=str(cwd), env=env, check=True)


def build(args):
    root = Path(__file__).resolve().parents[1]
    if os.name != "nt" or struct.calcsize("P") != 8:
        raise PackageError("This build requires native 64-bit Windows Python.")
    if not re.fullmatch(r"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)", args.version):
        raise PackageError("Packaging version must contain three nonnegative integer components.")
    if args.verification_upgrade_version == "auto":
        components = list(map(int, args.version.split(".")))
        components[-1] += 1
        args.verification_upgrade_version = ".".join(map(str, components))
    if args.source_version != "M01-24h-v1":
        raise PackageError("This generator and validator currently support M01-24h-v1 only.")
    if not re.fullmatch(r"[0-9a-f]{40}", args.source_commit):
        raise PackageError("A full source commit SHA is required.")
    # A release must identify the bytes actually checked out, not a supplied label.
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()
    if head != args.source_commit:
        raise PackageError("Source commit does not match the release checkout.")
    tracked_inputs = ["app.py", "ecg_core", "templates", "static", "win_doctor_eval.py",
                      "CardioInsightDoctorEval.spec", "requirements-doctor-build.txt",
                      "scripts/windows_doctor_build.py", "scripts/generate_doctor_24h.py",
                      "scripts/verify_doctor_24h.py"]
    dirty = subprocess.run(["git", "diff", "--quiet", "HEAD", "--", *tracked_inputs], cwd=root)
    if dirty.returncode != 0:
        raise PackageError("Release source has uncommitted changes; build a reviewed checkout.")
    output = args.output.resolve()
    if output == root or output in root.parents:
        raise PackageError("Build output must not replace or contain the source checkout.")
    if root in output.parents and output.relative_to(root).parts[0] not in {"build", "dist", "releases"}:
        raise PackageError("In-project build output must use a fresh build, dist or releases subdirectory.")
    if output.exists():
        raise PackageError("Build output must be a new directory.")
    validate_assets(root)
    output.mkdir(parents=True)
    dist, work = output / "build-dist", output / "build-work"
    env = dict(os.environ, PYINSTALLER_CONFIG_DIR=str(output / "pyinstaller-cache"))
    run([sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean",
         "--distpath", dist, "--workpath", work, root / "CardioInsightDoctorEval.spec"], cwd=root, env=env)
    built = dist / APP_NAME
    regular_files(built)  # Reject links before copying; never follow outside data.
    if not (built / (APP_NAME + ".exe")).is_file():
        raise PackageError("PyInstaller did not produce the expected executable.")
    package = output / PACKAGE_NAME
    shutil.copytree(built, package)
    (package / "Sources").mkdir()
    source = package / "Sources" / "M01"
    if args.source_root is None:
        run([sys.executable, root / "scripts" / "generate_doctor_24h.py", "--output", source], cwd=root)
    else:
        reusable = args.source_root.resolve()
        validate_source(reusable)
        shutil.copytree(reusable, source)
    source_manifest = validate_source(source)
    evidence = output / "evidence"
    evidence.mkdir()
    run([sys.executable, root / "scripts" / "verify_doctor_24h.py", "--source-root", source,
         "--output", evidence / "source-validation.json"], cwd=root)
    sys.path.insert(0, str(root))
    from ecg_core.config import APP_VERSION
    from scripts.verify_public_release import verify as verify_production
    production = verify_production(root)
    freeze = subprocess.check_output([sys.executable, "-m", "pip", "freeze", "--all"], text=True).splitlines()
    freeze = sorted(line.strip() for line in freeze if line.strip())
    print("DOCTOR_BUILD_FREEZE_JSON=" + json.dumps(freeze, ensure_ascii=False), flush=True)
    print("DOCTOR_BUILD_PLATFORM_JSON=" + json.dumps({
        "source_commit": args.source_commit, "os": platform.platform(),
        "machine": platform.machine(), "python": sys.version}, ensure_ascii=False), flush=True)
    versions = {name: importlib.metadata.version(name) for name in
                ("Flask", "waitress", "reportlab", "numpy", "pyinstaller")}
    release = {
        "schema_version": 1, "app_version": APP_VERSION, "software_version": APP_VERSION, "packaging_version": args.version,
        "release_version": args.version, "production_source_identity": production,
        "resolved_build_dependency_freeze": freeze,
        "source_commit": args.source_commit, "architecture": "x64", "target_os": "Windows 10",
        "target_os_physically_tested": False, "hospital_architecture_confirmed": False,
        "built_at_utc": datetime.now(timezone.utc).isoformat(),
        "build_os": platform.platform(), "build_python": sys.version,
        "build_machine": platform.machine(),
        "runtime_dependencies": {key: value for key, value in versions.items() if key != "pyinstaller"},
        "build_tools": {"pyinstaller": versions["pyinstaller"]},
        "distribution": "unsigned-portable-onedir", "authenticode_signed": False,
        "offline": True, "loopback_only": True, "bundled_browser": False,
        "source_id": "M01", "source_version": args.source_version,
        "minimum_source_version": args.source_version,
        "source_manifest_sha256": digest(source / "source-manifest.json"),
        "wholly_synthetic": True, "duration_seconds": 86400,
        "raw_waveform_bytes": source_manifest["expected_raw_bytes"],
        "patient_inputs_read": False, "clinical_release": False,
        "ci_run_url": args.ci_run_url,
    }
    write_json(package / "RELEASE.json", release)
    add_launchers(package)
    (package / "版本说明.txt").write_text(args.release_notes + "\n", encoding="utf-8-sig")
    create_content_manifest(package)
    verify_content_manifest(package)
    full_name = PACKAGE_NAME + "-" + args.version + "-full.zip"
    archive, archive_sha, unpacked = archive_and_extract(package, output, full_name)
    software = output / "software-package" / PACKAGE_NAME
    software.mkdir(parents=True)
    for relative, path in regular_files(package).items():
        if relative.startswith("Sources/") or relative in {"CONTENTS.json", "SHA256SUMS.txt"}:
            continue
        target = software / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, target)
    create_content_manifest(software, with_source=False)
    verify_content_manifest(software)
    software_name = PACKAGE_NAME + "-" + args.version + "-software.zip"
    software_archive, software_sha, _ = archive_and_extract(
        software, output, software_name, with_source=False)
    source_archive, source_sha = create_source_archive(source, output, args.source_version)
    upgrade_fixture = None
    if args.verification_upgrade_version:
        if not re.fullmatch(r"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)", args.verification_upgrade_version):
            raise PackageError("Verification fixture packaging version is invalid.")
        if tuple(map(int, args.verification_upgrade_version.split("."))) <= tuple(map(int, args.version.split("."))):
            raise PackageError("Verification fixture must have a newer packaging version.")
        fixture = output / "upgrade-fixture" / PACKAGE_NAME
        shutil.copytree(software, fixture)
        fixture_release = dict(release, packaging_version=args.verification_upgrade_version,
                               release_version=args.verification_upgrade_version,
                               verification_fixture_only=True,
                               verification_scope="same frozen algorithm and schema; packaging version upgrade only")
        write_json(fixture / "RELEASE.json", fixture_release)
        (fixture / "版本说明.txt").write_text(
            "仅CI验收夹具：同一冻结算法和数据库结构，包装版本升级验证；不是第二正式发布。\n",
            encoding="utf-8-sig")
        create_content_manifest(fixture, with_source=False)
        fixture_name = PACKAGE_NAME + "-" + args.verification_upgrade_version + "-upgrade-fixture.zip"
        fixture_archive, fixture_sha, _ = archive_and_extract(
            fixture, output, fixture_name, with_source=False, verify_subdir="verify-upgrade-fixture")
        upgrade_fixture = {
            "archive": fixture_archive.name, "sha256": fixture_sha,
            "from_packaging_version": args.version,
            "to_packaging_version": args.verification_upgrade_version,
            "same_production_source": True, "user_deliverable": False,
            "scope": "fixture_same_schema_upgrade",
        }
    # Run the final unpacked EXE outside the checkout, without build Python on PATH.
    # Windows system components and the user's existing browser remain available.
    system_root = os.environ.get("SystemRoot", r"C:\Windows")
    smoke_env = {key: value for key, value in os.environ.items()
                 if not key.startswith(("PYTHON", "ECG_"))}
    smoke_env["PATH"] = str(Path(system_root) / "System32") + os.pathsep + system_root
    with tempfile.TemporaryDirectory(prefix="doctor-eval-smoke-", dir=output) as isolated:
        exe = unpacked / (APP_NAME + ".exe")
        run([exe, "--self-check"], cwd=isolated, env=smoke_env)
        run([exe, "--smoke-test"], cwd=isolated, env=smoke_env)
    verify_content_manifest(unpacked)
    report = {
        **release, "archive": archive.name, "archive_sha256": archive_sha,
        "software_archive": software_archive.name, "software_archive_sha256": software_sha,
        "software_archive_size_bytes": software_archive.stat().st_size,
        "source_archive": source_archive.name, "source_archive_sha256": source_sha,
        "source_archive_size_bytes": source_archive.stat().st_size,
        "archive_size_bytes": archive.stat().st_size,
        "uncompressed_payload_bytes": sum(item["size_bytes"] for item in package_inventory(package).values()),
        "package_file_count": len(package_inventory(package)),
        "final_zip_crc_and_content_hashes_verified": True,
        "final_unpacked_exe_self_check_passed": True,
        "final_unpacked_exe_process_smoke_passed": True,
        "python_removed_from_runtime_path": True,
        "windows_10_physical_validation": "pending",
        "browser_validation": "separate CI step",
        "verification_upgrade_fixture": upgrade_fixture,
    }
    write_json(output / "build-report.json", report)
    print(json.dumps(report, ensure_ascii=False, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--source-version", default="M01-24h-v1")
    parser.add_argument("--verification-upgrade-version", help="CI-only newer packaging version fixture; never an official deliverable")
    parser.add_argument("--source-root", type=Path, help="Reuse only a fully verified M01-24h-v1 source directory")
    parser.add_argument("--release-notes", default="Windows x64 医生离线评估首版；内置连续24小时纯数学合成 M01；保存工作独立，升级软件不重传合成源。")
    parser.add_argument("--ci-run-url", default="")
    args = parser.parse_args()
    try:
        build(args)
    except (PackageError, ValueError, OSError, subprocess.CalledProcessError) as error:
        parser.exit(2, "Windows doctor package build failed: " + str(error) + "\n")


if __name__ == "__main__":
    main()
