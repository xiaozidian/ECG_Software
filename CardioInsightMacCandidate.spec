# -*- mode: python ; coding: utf-8 -*-
"""Mac evaluation bundle: explicit software-only asset allowlist.

Never add data/, demo/, docs/, original databases, report PDFs or screenshots.
"""
from pathlib import Path
import json
from PyInstaller.utils.hooks import collect_all

root = Path(SPECPATH)
release = json.loads((root / 'mac-release-manifest.json').read_text())
assets = [root / 'templates' / 'index.html', root / 'static' / 'icon.svg']
assets += sorted((root / 'static' / 'css').glob('*.css'))
assets += sorted((root / 'static' / 'js').glob('*.js'))
datas = [(str(path), str(path.parent.relative_to(root))) for path in assets]
datas.append((str(root / 'mac-release-manifest.json'), '.'))
reportlab = collect_all('reportlab')
datas += reportlab[0]
a = Analysis([str(root / 'mac_release.py')], pathex=[str(root)], binaries=reportlab[1],
             datas=datas, hiddenimports=reportlab[2], hookspath=[], hooksconfig={},
             runtime_hooks=[], excludes=['pytest', 'IPython', 'matplotlib', 'pandas', 'scipy'],
             noarchive=False, optimize=0)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name='CardioInsightMacCandidate',
          debug=False, bootloader_ignore_signals=False, strip=False, upx=False,
          console=True, disable_windowed_traceback=False, argv_emulation=False,
          target_arch='arm64', codesign_identity=None, entitlements_file=None)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name='CardioInsightMacCandidate')
app = BUNDLE(coll, name='CardioInsightMacCandidate.app', icon=None,
             bundle_identifier='cn.edu.tsinghua.cardioinsight.mac-evaluation',
             info_plist={'CFBundleDisplayName': 'CardioInsight 医生功能评估',
                         'CFBundleShortVersionString': release['app_version'].split('-', 1)[0],
                         'LSMinimumSystemVersion': release['runtime_min_macos'],
                         'LSApplicationCategoryType': 'public.app-category.medical',
                         'NSHighResolutionCapable': True})
