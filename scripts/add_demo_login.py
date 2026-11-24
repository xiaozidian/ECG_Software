"""Install the role selection pages over the generated mathematical demo."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from jinja2 import Environment, StrictUndefined, select_autoescape


ROOT = Path(__file__).resolve().parents[1]
ASSETS = ('static/css/demo-login.css', 'static/js/demo-login.js')


def versioned(relative: str, data: bytes) -> str:
    return f'{relative}?v={hashlib.sha256(data).hexdigest()[:12]}'


def replace_once(text: str, marker: str, replacement: str) -> str:
    if text.count(marker) != 1:
        raise ValueError(f'Mathematical demo layout marker changed: {marker}')
    return text.replace(marker, replacement, 1)


def add_login(output: Path) -> None:
    if any((output / name).exists() for name in ('workbench.html', 'review.html', *ASSETS)):
        raise ValueError('Use a freshly built mathematical demo directory.')
    manifest_path = output / 'mathematical-source-manifest.json'
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    if (manifest.get('python_core_executed_in_browser') is not False
            or manifest.get('capabilities', {}).get('clinical_data') is not False
            or manifest.get('mathematical_source', {}).get('patient_inputs_read') is not False):
        raise ValueError('Login pages require the verified public mathematical demo.')

    assets = {name: (ROOT / 'demo' / name).read_bytes() for name in ASSETS}
    css, script = (versioned(name, assets[name]) for name in ASSETS)
    identity = 'static/js/shared-source-version.js'
    identity_url = versioned(identity, (output / identity).read_bytes())
    index = output / 'index.html'
    workbench = index.read_text(encoding='utf-8')
    workbench = replace_once(workbench, '<html ', '<html data-demo-portal-page="workbench" ')
    workbench = replace_once(workbench, '</head>',
                             f'  <link rel="stylesheet" href="{css}">\n'
                             f'  <script src="{script}"></script>\n</head>')
    workbench = replace_once(workbench, '<div class="role-chip">',
                             '<div id="demoAccountActions" class="demo-account-actions"></div>\n'
                             '      <div class="role-chip">')

    template_source = (ROOT / 'demo/templates/demo-login.html').read_text(encoding='utf-8')
    template_source = replace_once(template_source, 'static/css/demo-login.css', css)
    template_source = replace_once(template_source, 'static/js/demo-login.js', script)
    template_source = replace_once(template_source, identity, identity_url)
    env = Environment(autoescape=select_autoescape(['html']), undefined=StrictUndefined)
    template = env.from_string(template_source)
    login_html = template.render(page='login')
    review_html = template.render(page='review')

    for name, data in assets.items():
        (output / name).write_bytes(data)
    (output / 'workbench.html').write_text(workbench, encoding='utf-8', newline='\n')
    (output / 'review.html').write_text(review_html, encoding='utf-8', newline='\n')
    index.write_text(login_html, encoding='utf-8', newline='\n')
    manifest['demo_role_login'] = {'mode': 'browser-only', 'roles': ['diagnosis', 'review'],
                                   'clinical_credentials': False, 'review_access': 'read-only',
                                   'report_storage_namespace_unchanged': True}
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    add_login(parser.parse_args().output)


if __name__ == '__main__':
    main()
