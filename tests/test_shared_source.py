"""Source identity, adapter preservation and real static build; no clinical inputs."""
from pathlib import Path
import json
import zipfile

import pytest

from scripts import shared_source as shared
from scripts.build_static_demo import build_shared

ROOT = Path(__file__).resolve().parents[1]


def test_reproducible_bundle_and_byte_identical_demo(tmp_path):
    first, second = tmp_path / 'first.zip', tmp_path / 'second.zip'
    manifest = shared.build(first)
    shared.build(second)
    assert first.read_bytes() == second.read_bytes()
    assert shared.check(first, ROOT)['matches']
    pages = build_shared(tmp_path / 'pages', first)
    receipt = json.loads((pages / 'mathematical-source-manifest.json').read_text())
    assert receipt['core_version'] == manifest['core_version']
    assert receipt['ui_version'] == manifest['ui_version']
    assert receipt['common_ui_bytes_modified'] is False
    assert receipt['python_core_executed_in_browser'] is False
    assert receipt['capabilities']['clinical_data'] is False
    for name, row in manifest['files'].items():
        if row['component'] == 'ui' and name.startswith('static/'):
            assert shared.sha((pages / name).read_bytes()) == row['sha256']
    assert not (pages / 'ecg_core').exists()
    assert receipt['mathematical_source']['patient_inputs_read'] is False
    assert receipt['mathematical_source']['existing_data_read'] is False
    assert receipt['mathematical_source']['assets']['waveform.bin']['bytes'] == 600*200*8*2
    assert 'Python完整算法/真实病例仅在本机运行' in (pages / 'index.html').read_text()


def test_platform_assembly_keeps_adapter_and_rejects_unique_changes(tmp_path):
    bundle = tmp_path / 'common.zip'
    manifest = shared.build(bundle)
    adapter = tmp_path / 'adapter'
    adapter.mkdir()
    for name in json.loads((ROOT / 'shared-source.json').read_text())['adapters']['local']:
        path = adapter / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes((ROOT / name).read_bytes())
    # Existing platform changes stay on the platform side, byte for byte.
    app = adapter / 'app.py'
    app.write_bytes(app.read_bytes() + b'\n# unique platform launcher note\n')
    before = {p.relative_to(adapter).as_posix(): p.read_bytes() for p in adapter.rglob('*') if p.is_file()}
    stage = tmp_path / 'assembled'
    receipt = shared.stage(bundle, adapter, stage, 'local')
    assert shared.check(bundle, stage)['matches']
    assert (stage / 'app.py').read_bytes() == app.read_bytes()
    assert receipt['core_version'] == manifest['core_version']
    assert {p.relative_to(adapter).as_posix(): p.read_bytes() for p in adapter.rglob('*') if p.is_file()} == before
    dirty = adapter / 'static/js/app.js'
    dirty.parent.mkdir(parents=True)
    dirty.write_text('// unique unmerged user modification\n')
    refused = tmp_path / 'refused'
    with pytest.raises(ValueError, match='Unmerged'):
        shared.stage(bundle, adapter, refused, 'local')
    assert not refused.exists()
    base = tmp_path / 'immutable-base.json'
    base.write_text(json.dumps({'revision': 'explicit-test-base', 'files': {'static/js/app.js': shared.git_blob(dirty.read_bytes())}}))
    shared.stage(bundle, adapter, tmp_path / 'explicit-base-assembly', 'local', base)
    assert dirty.read_text() == '// unique unmerged user modification\n'


def test_bundle_tampering_and_path_escape_are_rejected(tmp_path):
    bundle = tmp_path / 'common.zip'
    shared.build(bundle)
    tampered = tmp_path / 'tampered.zip'
    with zipfile.ZipFile(bundle) as src, zipfile.ZipFile(tampered, 'w') as dst:
        for name in src.namelist():
            data = src.read(name)
            dst.writestr(name, data + b'\nmodified' if name == 'static/js/app.js' else data)
    with pytest.raises(ValueError, match='modified'):
        shared.read_bundle(tampered)
    for name in ['../workspace.sqlite3', '/absolute', 'static/../case.DATA', 'a\\b']:
        with pytest.raises(ValueError, match='Unsafe'):
            shared.safe_name(name)


def test_platform_cannot_redefine_sample_contract(tmp_path):
    bundle = tmp_path / 'common.zip'
    shared.build(bundle)
    adapter = tmp_path / 'adapter'
    adapter.mkdir()
    for name in json.loads((ROOT / 'shared-source.json').read_text())['adapters']['local']:
        path = adapter / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes((ROOT / name).read_bytes())
    config = adapter / 'ecg_core/config.py'
    config.write_text(config.read_text() + '\nSAMPLE_RATE = 250\n')
    with pytest.raises(ValueError, match='sample/channel'):
        shared.stage(bundle, adapter, tmp_path / 'invalid-rate', 'local')
