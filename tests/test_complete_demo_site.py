"""Both static hosts build the same complete site without clinical inputs."""
from pathlib import Path
import hashlib
import json
import re
import subprocess
import sys

import pytest

from scripts import shared_source
from scripts.add_demo_login import add_login
from scripts.build_static_demo import HEADERS, build_shared, build_site


ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / 'scripts/build_static_demo.py'


@pytest.fixture(scope='module')
def complete_site(tmp_path_factory):
    root = tmp_path_factory.mktemp('complete-site')
    output, bundle = root / 'pages', root / 'shared-source.zip'
    subprocess.run([sys.executable, str(CLI), '--output', str(output),
                    '--save-shared-bundle', str(bundle)], cwd=ROOT, check=True)
    return output, bundle


def test_default_cli_builds_login_and_both_desks_from_verified_source(complete_site):
    output, bundle = complete_site
    manifest = json.loads((output / 'mathematical-source-manifest.json').read_text())
    source, payload = shared_source.read_bundle(bundle)
    assert manifest['source_fingerprint'] == source['source_fingerprint']
    assert manifest['shared_bundle_sha256'] == hashlib.sha256(bundle.read_bytes()).hexdigest()
    assert manifest['common_ui_bytes_modified'] is False
    assert manifest['python_core_executed_in_browser'] is False
    assert manifest['capabilities']['clinical_data'] is False
    assert manifest['mathematical_source']['patient_inputs_read'] is False
    assert manifest['demo_role_login']['roles'] == ['diagnosis', 'review']
    assert manifest['demo_role_login']['mode'] == 'browser-only'
    for name, role in [('index.html', 'login'), ('diagnosis.html', 'diagnosis'),
                       ('review.html', 'review'), ('workbench.html', 'workbench')]:
        html = (output / name).read_text()
        assert f'data-demo-portal-page="{role}"' in html
        assert '{{' not in html and '{%' not in html
        for relative in re.findall(r'(?:src|href)="(static/[^"?]+)', html):
            assert (output / relative).is_file(), (name, relative)
    for name, row in source['files'].items():
        if row['component'] == 'ui' and name.startswith('static/'):
            assert (output / name).read_bytes() == payload[name]
    for name, digest in manifest['demo_role_login']['adapter_sha256'].items():
        assert (output / name).read_bytes() == payload['demo/' + name]
        assert hashlib.sha256((output / name).read_bytes()).hexdigest() == digest
    assert (output / '_headers').read_text() == HEADERS
    assert not (output / 'ecg_core').exists()
    assert not any(p.suffix == '.zip' for p in output.rglob('*'))


def test_explicit_bundle_remains_ui_only_and_login_rejects_other_source(complete_site, tmp_path):
    _, bundle = complete_site
    output = tmp_path / 'ui-only'
    subprocess.run([sys.executable, str(CLI), '--shared-bundle', str(bundle),
                    '--output', str(output)], cwd=ROOT, check=True)
    assert not (output / 'review.html').exists()
    assert not (output / 'workbench.html').exists()
    assert (output / '_headers').read_text() == HEADERS
    receipt = output / 'mathematical-source-manifest.json'
    manifest = json.loads(receipt.read_text())
    manifest['source_fingerprint'] = 'different-source'
    receipt.write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match='Login package differs'):
        add_login(output, shared_bundle=bundle)
    assert not (output / 'workbench.html').exists()


@pytest.mark.parametrize('relative', [
    'scripts/add_demo_login.py',
    'demo/static/js/demo-account-trial.js',
    'demo/static/js/demo-login.js',
])
def test_login_dependency_changes_are_in_shared_fingerprint(monkeypatch, relative):
    original, _ = shared_source.snapshot(ROOT)
    source_bytes = shared_source.source_bytes
    monkeypatch.setattr(shared_source, 'source_bytes',
                        lambda root, name: source_bytes(root, name) + (b'\n' if name == relative else b''))
    changed, _ = shared_source.snapshot(ROOT)
    assert changed['source_fingerprint'] != original['source_fingerprint']
    assert changed['core_version'] == original['core_version']
    assert changed['ui_version'] == original['ui_version']


def test_default_preserves_outputs_and_source_packages(complete_site, tmp_path):
    output, bundle = complete_site
    before = {p.relative_to(output): p.read_bytes() for p in output.rglob('*') if p.is_file()}
    with pytest.raises(ValueError, match='Output must be new'):
        build_site(output)
    assert {p.relative_to(output): p.read_bytes() for p in output.rglob('*') if p.is_file()} == before
    previous = bundle.read_bytes()
    fresh = tmp_path / 'fresh'
    with pytest.raises(ValueError, match='Output already exists'):
        build_site(fresh, bundle)
    assert bundle.read_bytes() == previous and not fresh.exists()
    with pytest.raises(ValueError, match='outside the published output'):
        build_site(fresh, fresh / 'source.zip')
    assert not fresh.exists()


def test_cli_modes_cannot_silently_discard_bundle_output(tmp_path):
    result = subprocess.run([sys.executable, str(CLI), '--legacy-frozen',
                             '--save-shared-bundle', str(tmp_path / 'bundle.zip')],
                            capture_output=True, text=True)
    assert result.returncode == 2
    assert 'only to the default complete website build' in result.stderr


def test_github_uses_the_same_default_entry_point():
    workflow = (ROOT / '.github/workflows/pages.yml').read_text()
    assert 'python scripts/build_static_demo.py --save-shared-bundle build/shared-source.zip' in workflow
    assert 'python scripts/add_demo_login.py' not in workflow
    assert 'python scripts/shared_source.py build' not in workflow
    assert 'path: build/shared-source.zip' in workflow
