#!/usr/bin/env python3
"""Build the explicitly allowlisted Mac evaluation package after source freeze.

This script never installs dependencies or changes quarantine/Gatekeeper settings.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from hashlib import sha256
import importlib.metadata
import json
import os
from pathlib import Path
import plistlib
import re
import shutil
import subprocess
import sys
import tempfile

MAGICS = {b'\xfe\xed\xfa\xce', b'\xce\xfa\xed\xfe', b'\xfe\xed\xfa\xcf', b'\xcf\xfa\xed\xfe',
          b'\xca\xfe\xba\xbe', b'\xbe\xba\xfe\xca', b'\xca\xfe\xba\xbf', b'\xbf\xba\xfe\xca'}
COMMANDS = ['初始化Mac评估版.command', '启动Mac评估版.command', '检查Mac评估版.command',
            '停止Mac评估版.command', '恢复Mac评估工作.command']


def _run(argv, **kwargs):
    return subprocess.run([str(value) for value in argv], check=True, **kwargs)


def _hash(path):
    digest = sha256()
    with open(path, 'rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def software_files(root):
    files = [root / 'app.py', root / 'mac_release.py', root / 'CardioInsightMacCandidate.spec',
             root / 'templates' / 'index.html', root / 'static' / 'icon.svg']
    files += sorted((root / 'ecg_core').glob('*.py'))
    files += [root / 'scripts' / name for name in ('mac_release_runtime.py', 'mac_release_synthetic.py',
                                                  'serve_local_review.py', 'mac_release_command.sh')]
    files += [root / name for name in COMMANDS]
    files += sorted((root / 'static' / 'css').glob('*.css'))
    files += sorted((root / 'static' / 'js').glob('*.js'))
    files += [root / 'static' / 'terminology' / 'builtin-draft-v1.json']
    if any(not path.is_file() or path.is_symlink() for path in files):
        raise ValueError('软件白名单缺文件或包含链接，构建停止。')
    return sorted(files)


def source_snapshot(root):
    files = {str(path.relative_to(root)): _hash(path) for path in software_files(root)}
    digest = sha256(json.dumps(files, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    return dict(source_sha256=digest, files=files)


def verify_production_freeze(root, path):
    frozen = json.loads(Path(path).read_text())
    for name, expected in frozen['files'].items():
        current = root / name
        if not current.is_file() or _hash(current) != expected['sha256'] or current.stat().st_size != expected['bytes']:
            raise ValueError('生产冻结文件改变，停止构建：' + name)
    return frozen


def macho(path):
    if not path.is_file():
        return False
    with open(path, 'rb') as stream:
        return stream.read(4) in MAGICS


def macho_facts(path):
    archs = _run(['/usr/bin/lipo', '-archs', path], capture_output=True, text=True).stdout.strip().split()
    loads = _run(['/usr/bin/otool', '-l', path], capture_output=True, text=True).stdout
    versions = re.findall(r'^\s*minos\s+([0-9.]+)\s*$', loads, re.M)
    versions += re.findall(r'cmd LC_VERSION_MIN_MACOSX\s+cmdsize\s+\d+\s+version\s+([0-9.]+)', loads)
    deps = _run(['/usr/bin/otool', '-L', path], capture_output=True, text=True).stdout.splitlines()[1:]
    return dict(architectures=archs, min_macos=sorted(set(versions)),
                dependencies=[line.strip().split(' (')[0] for line in deps if line.strip()])


def version_tuple(value):
    return tuple(int(part) for part in value.split('.'))


def _write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def copy_build_bytes(source, target):
    """Reconstruct our new build without Finder/FileProvider resource metadata.

    Existing inputs are unchanged. If quarantine exists it is preserved; this
    operation never clears quarantine or changes system execution policy.
    """
    source, target = Path(source), Path(target)
    if source.is_symlink():
        target.symlink_to(os.readlink(source))
    elif source.is_dir():
        target.mkdir(mode=source.stat().st_mode & 0o777)
        for child in sorted(source.iterdir()):
            copy_build_bytes(child, target / child.name)
    else:
        shutil.copyfile(source, target)
        os.chmod(target, source.stat().st_mode & 0o777)
    options = ['-px'] + (['-s'] if source.is_symlink() else [])
    attribute = subprocess.run(['/usr/bin/xattr', *options, 'com.apple.quarantine', str(source)],
                               capture_output=True, text=True)
    if attribute.returncode == 0:
        value = ''.join(attribute.stdout.split())
        options = ['-wx'] + (['-s'] if target.is_symlink() else [])
        _run(['/usr/bin/xattr', *options, 'com.apple.quarantine', value, target],
             capture_output=True, text=True)
    elif 'No such xattr' not in attribute.stderr and not source.is_symlink():
        raise ValueError('无法核查新构建的 quarantine 元数据，停止复制：' + str(source))


def build(args):
    root, evidence = args.candidate.resolve(), args.evidence.resolve()
    if sys.platform != 'darwin':
        raise ValueError('本构建只支持 macOS。')
    if not args.frozen:
        raise ValueError('必须由集成者确认生产源码冻结后传入 --frozen；未启动构建。')
    evidence.mkdir(parents=True, exist_ok=True)
    before = source_snapshot(root)
    frozen = verify_production_freeze(root, args.production_freeze)
    if args.expected_source_sha and before['source_sha256'] != args.expected_source_sha:
        raise ValueError('生产软件白名单摘要与冻结值不同，构建停止。')
    probe = _run([args.python, '-c',
                  'import sys,json,platform,importlib.metadata;print(json.dumps(dict(executable=sys.executable,base_prefix=sys.base_prefix,python=sys.version,platform=platform.platform(),versions={k:importlib.metadata.version(k) for k in ("Flask","waitress","reportlab","numpy","PyInstaller")})))'],
                 capture_output=True, text=True)
    environment = json.loads(probe.stdout)
    python_min = macho_facts(Path(args.python).resolve())['min_macos']
    minimum = max(python_min, key=version_tuple) if python_min else '11.0'
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    release_id = frozen['identity']
    release = dict(schema=1, release_id=release_id, app_version=frozen['version'],
                   built_at_utc=stamp, source_sha256=frozen['source_sha256'],
                   build_input_sha256=before['source_sha256'],
                   runtime_min_macos=minimum, architecture='arm64', intended_use='doctor_functional_evaluation',
                   clinical_release=False, bundled_patient_data=False, bundled_work_database=False,
                   synthetic_generation='explicit-first-run-only', independent_device_mapping_verified=False,
                   voltage_calibrated=False, physician_gold_standard=False,
                   distribution='ad-hoc-signed-not-developer-id-not-notarized', runtime_versions=environment['versions'])
    _write(root / 'mac-release-manifest.json', release)
    _write(evidence / 'source-freeze.json', before)
    _write(evidence / 'build-environment.json', environment)
    dist = evidence / 'build-dist'
    work = args.reuse_work.resolve() if args.reuse_work else evidence / 'build-work'
    cache = args.reuse_cache.resolve() if args.reuse_cache else evidence / 'pyinstaller-private-cache'
    build_environment = dict(os.environ, PYINSTALLER_CONFIG_DIR=str(cache))
    free=shutil.disk_usage(evidence).free
    if free < 3_500_000_000: raise ValueError('构建预估峰值1.5GB并保留2GB基本余量；空间不足，未启动构建。')
    _write(evidence / 'build-space-and-cache.json',dict(free_bytes=free,estimated_peak_bytes=1_500_000_000,work=str(work),cache=str(cache),reuse_work=bool(args.reuse_work),reuse_cache=bool(args.reuse_cache)))
    with open(evidence / 'pyinstaller.log', 'w') as log:
        _run([args.python, '-m', 'PyInstaller', '--noconfirm', '--distpath', dist,
              '--workpath', work, root / 'CardioInsightMacCandidate.spec'], cwd=root,
             env=build_environment, stdout=log, stderr=subprocess.STDOUT)
    if source_snapshot(root) != before:
        raise ValueError('构建过程中生产源码改变，产物不能作为冻结交付。')
    verify_production_freeze(root, args.production_freeze)
    app = dist / 'CardioInsightMacCandidate.app'
    inventory, seen = {}, set()
    for path in sorted(app.rglob('*')):
        if path.is_file() and path.resolve() not in seen and macho(path):
            seen.add(path.resolve())
            facts = macho_facts(path)
            if facts['architectures'] != ['arm64']:
                raise ValueError('产物不是纯 arm64：' + str(path.relative_to(app)))
            inventory[str(path.relative_to(app))] = facts
    versions = [value for facts in inventory.values() for value in facts['min_macos']]
    if not versions:
        raise ValueError('产物没有可核查的 macOS 最低版本，停止交付。')
    minimum = max(versions, key=version_tuple)
    release['runtime_min_macos'] = minimum
    release['macho_count'] = len(inventory)
    _write(root / 'mac-release-manifest.json', release)
    for path in (app / 'Contents' / 'Resources' / 'mac-release-manifest.json',
                 app / 'Contents' / 'Frameworks' / 'mac-release-manifest.json'):
        if path.exists():
            _write(path.resolve(), release)
    plist_path = app / 'Contents' / 'Info.plist'
    with open(plist_path, 'rb') as stream:
        plist = plistlib.load(stream)
    plist['LSMinimumSystemVersion'] = minimum
    parts = frozen['version'].split('-', 1)[0].split('.')
    plist['CFBundleVersion'] = f'{int(parts[1])}.{int(parts[2])}.8'
    with open(plist_path, 'wb') as stream:
        plistlib.dump(plist, stream)
    external = sorted({dependency for facts in inventory.values() for dependency in facts['dependencies']
                       if dependency.startswith('/') and not dependency.startswith(('/System/Library/', '/usr/lib/'))})
    # The dylib's own install ID may be absolute, but other external dependencies
    # would make this package nonportable. Preserve the full evidence for review.
    _write(evidence / 'macho-inventory.json', dict(minimum_macos=minimum, architecture='arm64',
                                                 files=inventory, absolute_non_system_entries=external))
    if any(str(root) in value or '.venv/' in value for value in external):
        raise ValueError('Mach-O 依赖仍绑定原源码/venv目录，停止交付。')
    # Desktop's cloud FileProvider attaches FinderInfo to .app directories,
    # invalidating strict signature verification. Keep the clean install copy
    # on local /tmp and publish a durable ZIP created from that verified copy.
    release_container = Path(tempfile.mkdtemp(prefix='CardioInsightMacRelease-' + frozen['source_sha256'][:16] + '-', dir='/tmp'))
    package = release_container / release_id
    package.mkdir()
    with tempfile.TemporaryDirectory(prefix='cardioinsight-sign-', dir='/tmp') as temporary:
        clean_app = Path(temporary) / app.name
        copy_build_bytes(app, clean_app)
        with open(evidence / 'codesign.txt', 'w') as log:
            _run(['/usr/bin/codesign', '--force', '--deep', '--sign', '-', clean_app], stdout=log, stderr=subprocess.STDOUT)
            _run(['/usr/bin/codesign', '--verify', '--deep', '--strict', '--verbose=2', clean_app], stdout=log, stderr=subprocess.STDOUT)
            _run(['/usr/bin/codesign', '-dv', '--verbose=4', clean_app], stdout=log, stderr=subprocess.STDOUT)
            copy_build_bytes(clean_app, package / app.name)
            _run(['/usr/bin/codesign', '--verify', '--deep', '--strict', '--verbose=2', package / app.name], stdout=log, stderr=subprocess.STDOUT)
    (package / 'scripts').mkdir()
    shutil.copy2(root / 'scripts' / 'mac_release_command.sh', package / 'scripts' / 'mac_release_command.sh')
    for name in COMMANDS:
        shutil.copy2(root / name, package / name)
    shutil.copy2(root / 'docs' / 'mac-release-20261008' / 'INSTALL.md', package / 'INSTALL.md')
    _write(package / 'RELEASE.json', release)
    package_files = sorted(path for path in package.rglob('*') if path.is_file() and not path.is_symlink())
    forbidden = [str(path.relative_to(package)) for path in package_files
                 if path.suffix.lower() in ('.data', '.ebi', '.lps', '.db', '.sqlite3', '.pdf', '.ecgbackup')
                 or '/docs/' in str(path.relative_to(package)) or '/demo/' in str(path.relative_to(package))]
    if forbidden:
        raise ValueError('包内发现非白名单病例/数据库/导出资源，停止交付：' + repr(forbidden))
    hashes = {str(path.relative_to(package)): _hash(path) for path in package_files}
    _write(evidence / 'package-files.json', dict(release_id=release_id, count=len(hashes), files=hashes,
                                                forbidden_files=forbidden, included_patient_files=False))
    (package / 'SHA256SUMS.txt').write_text('\n'.join(digest + '  ' + name for name, digest in hashes.items()) + '\n')
    archive_folder = evidence / 'release'
    archive_folder.mkdir(exist_ok=True)
    archive = archive_folder / (release_id + '.zip')
    _run(['/usr/bin/ditto', '-c', '-k', '--sequesterRsrc', '--keepParent', package, archive])
    result = dict(release_id=release_id, package=str(package), archive=str(archive), distribution_archive=str(archive), archive_sha256=_hash(archive),
                  archive_bytes=archive.stat().st_size, runtime_min_macos=minimum, macho_count=len(inventory),
                  architecture='arm64', source_sha256=frozen['source_sha256'],
                  build_input_sha256=before['source_sha256'], clinical_release=False,
                  another_mac_tested=False, notarized=False, package_is_local_temporary_install=True,
                  durable_delivery='archive', install_location='local non-FileProvider directory')
    _write(evidence / 'BUILD.json', result)
    print(json.dumps(result, ensure_ascii=False, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--candidate', type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('--evidence', type=Path, required=True)
    parser.add_argument('--python', required=True)
    parser.add_argument('--frozen', action='store_true')
    parser.add_argument('--reuse-work',type=Path)
    parser.add_argument('--reuse-cache',type=Path)
    parser.add_argument('--expected-source-sha')
    parser.add_argument('--production-freeze', type=Path, required=True)
    args = parser.parse_args()
    build(args)


if __name__ == '__main__':
    main()
