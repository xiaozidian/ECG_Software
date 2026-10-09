"""Public artifact contract: manifest software plus newly generated mathematics."""
from __future__ import annotations
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / 'docs/releases/0.12.9-doctor-evaluation.20261009/source-manifest.json'


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build(output: Path) -> None:
    subprocess.run([sys.executable, str(ROOT / 'scripts/build_static_demo.py'), '--output', str(output)], cwd=ROOT, check=True)


def test_static_demo_builder(tmp_path: Path) -> None:
    source = json.loads(MANIFEST.read_text(encoding='utf-8'))
    before = {p: digest(ROOT / p) for p in source['files']}
    output = tmp_path / 'pages'
    build(output)
    receipt = json.loads((output / 'mathematical-source-manifest.json').read_text(encoding='utf-8'))
    assert receipt['release_id'] == source['release_id']
    assert receipt['production_source_sha256'] == source['source_sha256']
    assert receipt['production_files_verified'] == 94
    assert receipt['production_files_modified'] is False
    assert receipt['legacy_demo_inputs_read'] is False
    assert receipt['storage_namespace'] == 'cardioinsight-public-math-4314-v2'
    allowed_software = {p for p in source['files'] if p.startswith('static/') and Path(p).suffix in {'.js', '.css', '.svg'}}
    assert {a['path'] for a in receipt['software_assets']} == allowed_software
    extras = {'index.html', '.nojekyll', '_headers', 'mathematical-source-manifest.json', 'static/js/demo-api.js',
              'static/demo-data/mathematical-4314/case-data.js', 'static/demo-data/mathematical-4314/waveform.bin'}
    actual = {p.relative_to(output).as_posix() for p in output.rglob('*') if p.is_file()}
    assert actual == allowed_software | extras
    assert not any(p.is_symlink() for p in output.rglob('*'))
    for relative in ['index.html', 'mathematical-source-manifest.json', '_headers',
                     'static/demo-data/mathematical-4314/case-data.js']:
        encoded = (output / relative).read_bytes()
        encoded.decode('utf-8')
        assert b'\r\n' not in encoded, f'{relative} must have platform-independent LF bytes'
    for row in receipt['software_assets']:
        assert row['production_sha256'] == before[row['path']]
        assert row['output_sha256'] == digest(output / row['path'])
    math = receipt['mathematical_source']
    assert math['kind'] == 'pure_mathematical'
    assert math['case_id'] == 'math-4314-001'
    assert math['existing_data_read'] is False and math['patient_inputs_read'] is False
    assert math['sample_rate_hz'] == 200 and math['stored_channels'] == 8 and math['duration_seconds'] == 600
    for relative, row in math['assets'].items():
        p = output / 'static/demo-data/mathematical-4314' / relative
        assert p.stat().st_size == row['bytes'] and digest(p) == row['sha256']
    assert math['assets']['waveform.bin']['bytes'] == 600 * 200 * 8 * 2
    js = (output / 'static/demo-data/mathematical-4314/case-data.js').read_text(encoding='utf-8')
    case = json.loads(js.split(' = ', 1)[1].rstrip(';\n'))
    assert case['integrity']['mathematical_fixture'] is True and case['integrity']['raw_patient_data'] is False
    assert case['simulation_profile']['real_patient_inputs_read'] is False
    assert case['simulation_profile']['source_waveform_copied'] is False
    assert case['simulation_profile']['rhythm_candidate_windows_s'] == []
    assert case['report_image_urls'] == []
    assert case['case_id'] == 'math-4314-001' and case['metadata']['patient_id'] == 'MATH-001'
    assert len(case['beats']) == math['beat_count']
    assert len({b['sample_index'] for b in case['beats']}) == math['beat_count']
    assert all(0 <= b['sample_index'] < 600 * 200 for b in case['beats'])
    html = (output / 'index.html').read_text(encoding='utf-8')
    assert 'data-demo-readonly="true"' in html and 'data-allow-phi="false"' in html
    assert '纯数学合成' in html and '修改仅存本浏览器' in html and '不构成疾病金标准' in html
    assert '{{' not in html and '{%' not in html
    assert html.index('mathematical-4314/case-data.js') < html.index('js/demo-api.js') < html.index('js/app.js')
    assert 'id="saveSttAnnotation" class="button primary" type="submit" hidden' not in html
    for relative in re.findall(r'(?:src|href)="(static/[^"?]+)', html):
        assert (output / relative).is_file()
    for relative in ['static/js/app.js', 'static/js/clinical-workflow.js', 'static/js/demo-api.js']:
        subprocess.run(['node', '--check', str(output / relative)], check=True)
    workflow = (output / 'static/js/clinical-workflow.js').read_text(encoding='utf-8')
    assert '__CARDIOINSIGHT_MATHEMATICAL_CASE__' in workflow
    assert '__CARDIOINSIGHT_UPLOADED_CASE__' not in workflow
    app = (output / 'static/js/app.js').read_text(encoding='utf-8')
    assert 'button.disabled=busy||!clinicalWorkflow.writable()||!sttWaveformIsCurrent()' in app
    assert 'submit.disabled=!clinicalWorkflow.writable()||Boolean(state.sttSaving)||!usable' in app
    assert 'if(!state.demoReadonly)' in (output / 'static/js/clinical-ui.js').read_text(encoding='utf-8')
    paper = (output / 'static/css/report-paper.css').read_text(encoding='utf-8')
    assert 'size:A4 portrait' in paper and 'width:210mm;height:297mm' in paper
    headers = (output / '_headers').read_text(encoding='utf-8')
    assert "connect-src 'self'" in headers and "frame-ancestors 'none'" in headers
    assert 'Permissions-Policy:' in headers and 'X-Content-Type-Options: nosniff' in headers
    assert {p: digest(ROOT / p) for p in source['files']} == before


def test_math_payload_is_deterministic_and_output_is_never_overwritten(tmp_path: Path) -> None:
    one, two = tmp_path / 'one', tmp_path / 'two'
    build(one)
    build(two)
    for name in ['waveform.bin', 'case-data.js']:
        relative = Path('static/demo-data/mathematical-4314') / name
        assert (one / relative).read_bytes() == (two / relative).read_bytes()
    marker = one / 'explicitly-preserved.txt'
    marker.write_text('existing output must survive', encoding='utf-8', newline='\n')
    result = subprocess.run([sys.executable, str(ROOT / 'scripts/build_static_demo.py'), '--output', str(one)], capture_output=True, text=True)
    assert result.returncode != 0 and 'Output must be new' in result.stderr
    assert marker.read_text(encoding='utf-8') == 'existing output must survive'
