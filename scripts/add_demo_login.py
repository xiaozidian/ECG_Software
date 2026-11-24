"""Render the shared account-trial interface over a mathematical Pages build."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from urllib.parse import urlencode

from jinja2 import Environment, StrictUndefined, select_autoescape


ROOT = Path(__file__).resolve().parents[1]
PORTAL = 'static/js/demo-account-trial.js'
WORKBENCH = 'static/js/demo-login.js'
LAYOUTS = 'static/js/demo-account-layouts.js'
IDENTITY = 'static/js/shared-source-version.js'
ACCOUNT_SCRIPT = 'static/js/account-trial.js'
ACCOUNT_STYLE = 'static/css/account-trial.css'
ACCOUNTS = {'diag01': ('诊断', '诊断医生（测试）', 'diag-preview'),
            'review01': ('审核', '审核医生（测试）', 'review-preview')}
STATES = {'draft': '诊断草稿', 'pending': '待审核', 'returned': '退回修改',
          'withdrawn': '已撤回', 'signed': '已测试签发'}


def versioned(relative: str, data: bytes) -> str:
    return f'{relative}?v={hashlib.sha256(data).hexdigest()[:12]}'


def replace_once(text: str, marker: str, replacement: str) -> str:
    if text.count(marker) != 1:
        raise ValueError(f'Mathematical demo layout marker changed: {marker}')
    return text.replace(marker, replacement, 1)


def jinja_portal(output: Path, desk: str, assets: dict[str, bytes]) -> Environment:
    def demo_url(endpoint, **params):
        if endpoint == 'static':
            relative = 'static/' + params['filename']
            return versioned(relative, assets.get(relative) or (output / relative).read_bytes())
        if endpoint == 'trial_case':
            return desk
        if endpoint == 'trial_login':
            return 'trial/login'
        if endpoint == 'trial_logout':
            return 'trial/logout'
        if endpoint == 'clinical_workbench':
            return 'workbench.html?' + urlencode({'view': params['view']})
        if endpoint == 'trial_file':
            query = {'view': 'report', 'round': params['round_no'], 'kind': params['kind']}
            if params.get('download'):
                query['download'] = 1
            return 'workbench.html?' + urlencode(query)
        raise ValueError(f'Unsupported demo account URL: {endpoint}')

    env = Environment(autoescape=select_autoescape(['html']), undefined=StrictUndefined)
    env.globals['url_for'] = demo_url
    env.filters['trial_time'] = lambda value: value
    return env


def render_portal(output: Path, assets: dict[str, bytes], role='login', variant='empty') -> str:
    desk = ('review' if role == 'review' else 'diagnosis') + '.html'
    env = jinja_portal(output, desk, assets)
    template = env.from_string((ROOT / 'templates/account-trial.html').read_text(encoding='utf-8'))
    account = 'review01' if role == 'review' else 'diag01'
    status = 'draft' if variant == 'empty' else variant
    active = {'id': 'DEMO_SUBMISSION_ID', 'round_no': 'DEMO_ROUND', 'author': 'diag01', 'reviewer': 'review01',
              'submitted': 'DEMO_SUBMITTED', 'state': status, 'conclusion': 'DEMO_CONCLUSION',
              'reason': 'DEMO_RETURN_REASON', 'signed_at': 'DEMO_SIGNED_AT' if status == 'signed' else ''}
    page = template.render(
        login_page=role == 'login', accounts=ACCOUNTS, account=account, trial_user=ACCOUNTS[account][1],
        config={'TRIAL_SHOWCASE': True, 'TRIAL_SOURCE_LABEL': '数学合成病例',
                'TRIAL_ORIGINAL_URL': 'workbench.html', 'TRIAL_POPUP_REL': 'opener'},
        trial_token='demo-browser', trial_epoch='demo-browser', trial_case_label='M01', trial_case_count=1,
        queue_revision='DEMO_QUEUE_REVISION', cases=[{'label': 'M01', 'state': status}], states=STATES,
        flow={'state': status, 'revision': 'DEMO_REVISION', 'active': active['id']},
        history=[] if variant == 'empty' else [active],
        events=[] if variant == 'empty' else [{'actor': account, 'at': 'DEMO_EVENT_AT', 'action': 'DEMO_EVENT_ACTION'}],
        editable=role == 'diagnosis' and status in ('draft', 'returned'),
        report={'conclusion': 'DEMO_CONCLUSION', 'version': 'DEMO_REPORT_VERSION', 'review_revision': 'DEMO_REVIEW_REVISION'},
        test_pin='135790',
    )
    return replace_once(page, '<html ', f'<html data-demo-portal-page="{role}" ')


def add_login(output: Path) -> None:
    if any((output / name).exists() for name in ('workbench.html', 'diagnosis.html', 'review.html', PORTAL, WORKBENCH, LAYOUTS)):
        raise ValueError('Use a freshly built mathematical demo directory.')
    manifest_path = output / 'mathematical-source-manifest.json'
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    if (manifest.get('python_core_executed_in_browser') is not False
            or manifest.get('capabilities', {}).get('clinical_data') is not False
            or manifest.get('mathematical_source', {}).get('patient_inputs_read') is not False):
        raise ValueError('The account interface requires the verified mathematical demo.')

    assets = {name: (ROOT / 'demo' / name).read_bytes() for name in (PORTAL, WORKBENCH)}
    layouts = {role: {variant: render_portal(output, assets, role, variant)
                      for variant in ('empty', 'draft', 'pending', 'returned', 'signed')}
               for role in ('diagnosis', 'review')}
    assets[LAYOUTS] = ('window.ECGDemoTrialLayouts = ' + json.dumps(layouts, ensure_ascii=False) + ';\n').encode()
    def url(name):
        return versioned(name, assets.get(name) or (output / name).read_bytes())

    def script(name):
        return f'<script src="{url(name)}"></script>'

    index = output / 'index.html'
    workbench = index.read_text(encoding='utf-8')
    workbench = replace_once(workbench, '<html ', '<html data-demo-portal-page="workbench" data-account-trial data-trial-case="math-4314-001" ')
    workbench = replace_once(workbench, script(IDENTITY) + '\n', '')
    head = '\n'.join((f'<meta name="trial-token" content="demo-browser">',
                      f'<link rel="stylesheet" href="{url(ACCOUNT_STYLE)}">',
                      script(IDENTITY), script(PORTAL), script(WORKBENCH),
                      f'<script defer src="{url(ACCOUNT_SCRIPT)}"></script>'))
    workbench = replace_once(workbench, '</head>', head + '\n</head>')
    workbench = replace_once(workbench, '<div class="role-chip">',
                             '<a class="trial-top-link" href="diagnosis.html" data-trial-leave>诊断工作台</a>\n'
                             '      <div class="role-chip">')
    portal_head = '\n'.join(script(name) for name in (IDENTITY, LAYOUTS, PORTAL))
    pages = {name: replace_once(render_portal(output, assets, role), '</head>', portal_head + '\n</head>')
             for name, role in [('index.html', 'login'), ('diagnosis.html', 'diagnosis'), ('review.html', 'review')]}

    for name, data in assets.items():
        (output / name).write_bytes(data)
    (output / 'workbench.html').write_text(workbench, encoding='utf-8', newline='\n')
    for name, html in pages.items():
        (output / name).write_text(html, encoding='utf-8', newline='\n')
    manifest['demo_role_login'] = {'mode': 'browser-only', 'roles': ['diagnosis', 'review'],
                                  'clinical_credentials': False, 'review_access': 'shared-account-trial',
                                  'shared_account_template': hashlib.sha256((ROOT / 'templates/account-trial.html').read_bytes()).hexdigest()}
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    add_login(parser.parse_args().output)


if __name__ == '__main__':
    main()
