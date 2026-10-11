#!/usr/bin/env python3
"""Install one verified software-only archive into a NEW user release directory.

Never replace config, a workspace, another version, system apps, or OS policy.
"""
from __future__ import annotations
import argparse
from hashlib import sha256
import json
import os
from pathlib import Path, PurePosixPath
import subprocess
import tempfile
import zipfile


def install(archive, expected_sha, install_base, evidence):
    archive, install_base, evidence = Path(archive), Path(install_base), Path(evidence)
    digest = sha256(archive.read_bytes()).hexdigest()
    if digest != expected_sha:
        raise ValueError('软件包 ZIP 摘要与已验证交付值不同；未安装。')
    with zipfile.ZipFile(archive) as source:
        for entry in source.infolist():
            path = PurePosixPath(entry.filename)
            if path.is_absolute() or '..' in path.parts:
                raise ValueError('软件 ZIP 包含非相对路径；未安装。')
        manifests = [name for name in source.namelist() if name.count('/') == 1 and name.endswith('/RELEASE.json')]
        if len(manifests) != 1:
            raise ValueError('软件 ZIP 版本清单不唯一；未安装。')
        release = json.loads(source.read(manifests[0]))
        release_id = release['release_id']
        if manifests[0].split('/')[0] != release_id or Path(release_id).name != release_id:
            raise ValueError('软件 ZIP 版本目录与标识不匹配；未安装。')
    destination = install_base / release_id
    if destination.exists() or destination.is_symlink():
        raise ValueError('新版本安装目录已经存在；不会覆盖任何现有版本或工作。')
    install_base.mkdir(mode=0o700, parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.cardioinsight-software-install-', dir=install_base) as folder:
        subprocess.run(['/usr/bin/ditto', '-x', '-k', str(archive), folder], check=True)
        staged = Path(folder) / release_id
        # Reject every symlink that leaves this new software package.
        for path in staged.rglob('*'):
            if path.is_symlink() and staged.resolve() not in path.resolve().parents:
                raise ValueError('软件包包含目录外的链接；未安装。')
        for line in (staged / 'SHA256SUMS.txt').read_text().splitlines():
            expected, relative = line.split('  ', 1)
            selected = staged / relative
            if staged.resolve() not in selected.resolve().parents or sha256(selected.read_bytes()).hexdigest() != expected:
                raise ValueError('解压后的软件文件摘要不符；未安装。')
        app = staged / 'CardioInsightMacCandidate.app'
        evidence.mkdir(parents=True, exist_ok=True)
        with open(evidence / 'verified-local-install-codesign.txt', 'w') as log:
            subprocess.run(['/usr/bin/codesign', '--verify', '--deep', '--strict', '--verbose=2', str(app)],
                           stdout=log, stderr=subprocess.STDOUT, check=True)
            # rename refuses an existing nonempty release; preexisting versions
            # have already been rejected above, and no workspace lives here.
            os.rename(staged, destination)
            subprocess.run(['/usr/bin/codesign', '--verify', '--deep', '--strict', '--verbose=2',
                            str(destination / app.name)], stdout=log, stderr=subprocess.STDOUT, check=True)
    receipt = dict(release_id=release_id, archive_sha256=digest, verified_local_install=str(destination),
                   executable=str(destination / 'CardioInsightMacCandidate.app' / 'Contents' / 'MacOS' / 'CardioInsightMacCandidate'),
                   strict_signature_verified=True, config_overwritten=False, workspace_overwritten=False,
                   other_versions_overwritten=False, system_install=False, autostart=False,
                   security_settings_changed=False, quarantine_removed=False)
    (evidence / 'verified-local-install.json').write_text(json.dumps(receipt, ensure_ascii=False, indent=2)+'\n')
    print(json.dumps(receipt, ensure_ascii=False, indent=2))
    return receipt


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--archive', type=Path, required=True)
    parser.add_argument('--expected-sha', required=True)
    parser.add_argument('--install-base', type=Path, required=True)
    parser.add_argument('--evidence', type=Path, required=True)
    args = parser.parse_args()
    install(args.archive, args.expected_sha, args.install_base, args.evidence)
