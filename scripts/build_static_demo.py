"""Build the public mathematical browser Demo from manifest-verified software."""
from __future__ import annotations
import argparse
import hashlib
import json
import re
from pathlib import Path
from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape
from build_math_payload import generate
from verify_public_release import verify

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUTPUT = PROJECT_ROOT / 'build/pages'
MANIFEST = PROJECT_ROOT / 'docs/releases/0.12.9-doctor-evaluation.20261009/source-manifest.json'
ASSET = 'static/demo-data/mathematical-4314'
NAMESPACE = 'cardioinsight-public-math-4314-v2'
sha = lambda b: hashlib.sha256(b).hexdigest()


def build(output: Path) -> Path:
    output = output.resolve()
    if output.exists():
        raise ValueError('Output must be new; preserve or remove only a previous generated output explicitly.')
    verify(PROJECT_ROOT)
    manifest = json.loads(MANIFEST.read_text(encoding='utf-8'))
    output.mkdir(parents=True)
    copied = []
    for relative, row in manifest['files'].items():
        if not relative.startswith('static/') or Path(relative).suffix not in ('.js', '.css', '.svg'):
            continue
        data = original = (PROJECT_ROOT / relative).read_bytes()
        transformations = []
        if relative.endswith('.js'):
            text = data.decode()
            namespaced = text.replace('cardioinsight.', NAMESPACE + '.cardioinsight.')
            if namespaced != text:
                transformations.append('isolated browser storage namespace')
            text = namespaced
            if relative == 'static/js/clinical-workflow.js':
                old = 'Boolean(window.__CARDIOINSIGHT_UPLOADED_CASE__)'
                assert text.count(old) == 1
                text = text.replace(old, 'Boolean(window.__CARDIOINSIGHT_MATHEMATICAL_CASE__?.integrity?.mathematical_fixture)')
                transformations.append('browser-only mathematical write capability')
            if relative == 'static/js/app.js':
                for old, new in [('button.disabled=busy||Boolean(state.demoReadonly)||!sttWaveformIsCurrent()', 'button.disabled=busy||!clinicalWorkflow.writable()||!sttWaveformIsCurrent()'), ('submit.disabled=Boolean(state.demoReadonly)||Boolean(state.sttSaving)||!usable', 'submit.disabled=!clinicalWorkflow.writable()||Boolean(state.sttSaving)||!usable')]:
                    assert text.count(old) == 1
                    text = text.replace(old, new)
                transformations.append('ST browser-only save capability; native and print rules retained')
            data = text.encode()
        target = output / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        copied.append({'path': relative, 'production_sha256': row['sha256'], 'output_sha256': sha(data), 'copy_changed': data != original, 'transformations': transformations})
    payload = generate(output / ASSET, manifest['release_id'])
    api_source = PROJECT_ROOT / 'demo/static/js/demo-api.js'
    (output / 'static/js/demo-api.js').write_bytes(api_source.read_bytes())
    env = Environment(loader=FileSystemLoader(PROJECT_ROOT / 'templates'), autoescape=select_autoescape(['html']), undefined=StrictUndefined)
    env.globals['url_for'] = lambda endpoint, filename: 'static/' + filename
    html = env.get_template('index.html').render(app_name='CardioInsight 数学交互演示', app_version=manifest['release_id'], app_version_short='0.12.9 数学Demo', demo_readonly=True, allow_phi=False)
    html = html.replace('演示分析医生', '数学演示操作者').replace('本地工作站', '浏览器独立数学演示')
    html = html.replace('10 例仅用于功能回归', '纯数学输入仅演示交互')
    html = html.replace('在线 Demo 可体验测量交互，但不会保存复核意见。', '数学 Demo 的人工复核意见仅保存到当前浏览器，不上传。')
    old_st_save = 'id="saveSttAnnotation" class="button primary" type="submit" hidden disabled'
    assert html.count(old_st_save) == 1
    html = html.replace(old_st_save, 'id="saveSttAnnotation" class="button primary" type="submit"')
    anchor = '<script src="static/js/app.js"></script>'
    assert html.count(anchor) == 1
    html = html.replace(anchor, '<script src="' + ASSET + '/case-data.js"></script>\n<script src="static/js/demo-api.js"></script>\n' + anchor)
    html = html.replace('<body>', '<body><aside id="mathematicalDemoBoundary" role="note" style="position:fixed;bottom:0;left:0;right:0;z-index:10000;pointer-events:none;background:#fff4d5;color:#3e2f10;padding:5px 12px;text-align:center">纯数学合成 · 无患者输入 · 修改仅存本浏览器 · 不构成疾病金标准或临床结论</aside>')
    def asset_version(match):
        attribute, relative = match.groups()
        return f'{attribute}="{relative}?v={sha((output / relative).read_bytes())[:12]}"'
    html = re.sub(r'(src|href)="(static/(?:js|css)/[^"]+)"', asset_version, html)
    html = re.sub(r'(?m)^[ \t]+$', '', html)
    (output / 'index.html').write_text(html, encoding='utf-8', newline='\n')
    (output / '.nojekyll').write_text('', encoding='utf-8', newline='\n')
    (output / '_headers').write_text("""/*
  Content-Security-Policy: default-src 'self'; base-uri 'none'; connect-src 'self'; font-src 'self'; form-action 'self'; frame-ancestors 'none'; img-src 'self' data: blob:; object-src 'none'; script-src 'self'; style-src 'self' 'unsafe-inline'
  Permissions-Policy: camera=(), geolocation=(), microphone=()
  Referrer-Policy: no-referrer
  X-Content-Type-Options: nosniff
  X-Frame-Options: DENY
""", encoding='utf-8', newline='\n')
    receipt = {'schema': 1, 'release_id': manifest['release_id'], 'production_source_sha256': manifest['source_sha256'], 'production_files_verified': len(manifest['files']), 'production_files_modified': False, 'storage_namespace': NAMESPACE, 'mathematical_source': payload, 'software_assets': copied, 'demo_api_sha256': sha(api_source.read_bytes()), 'legacy_demo_inputs_read': False, 'scope': 'Browser-only mathematical interaction; no desktop database, native PDF, backup/restore, clinical or hardware validation.'}
    (output / 'mathematical-source-manifest.json').write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + '\n', encoding='utf-8', newline='\n')
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=DEFAULT_OUTPUT)
    print(build(parser.parse_args().output))

if __name__ == '__main__':
    main()
