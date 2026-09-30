"""Paper controls must preserve curated evidence and agree in SVG / PDF."""
import copy
import json
import re
import subprocess
import xml.etree.ElementTree as ET

import pytest
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfgen.canvas import Canvas

from ecg_core.report_layout import paper_segments
from ecg_core.storage import normalize_report_composition, Storage
from ecg_core.report_paper_pdf import build_paper_pdf
from ecg_core.report_pdf import _register_font, FONT_NAME
from test_paper_geometry import sample_entry, paper, js, ROOT, NS


@pytest.mark.parametrize('value', [None, True, 1, [], {}, 'auto', 'FIXED'])
def test_invalid_time_scale_rejected(value):
    with pytest.raises(ValueError, match='时间标尺'):
        normalize_report_composition({'paper': {'time_scale': value}})


@pytest.mark.parametrize('key', ['show_grid', 'show_labels'])
@pytest.mark.parametrize('value', [None, 1, 'false', []])
def test_invalid_switch_rejected(key, value):
    with pytest.raises(ValueError, match='布尔'):
        normalize_report_composition({'paper': {key: value}})


def test_settings_save_reload_preserves_estimate_and_old_default(tmp_path):
    assert normalize_report_composition({})['paper']['time_scale'] == 'fit'
    settings = dict(paper(), time_scale='fixed', speed='50 mm/s', show_grid=False, show_labels=False)
    store = Storage(tmp_path / 'paper.db')
    saved = store.save_report('synthetic', 'unchanged', 'draft', 'tester', {'paper': settings})
    restored = store.get_report('synthetic', '')
    assert restored['composition'] == saved['composition']
    for k, v in settings.items():
        assert restored['composition']['paper'][k] == v


@pytest.mark.parametrize('speed', [12.5, 25, 50])
@pytest.mark.parametrize('seconds', [1, 7, 7.005, 14, 120])
def test_segment_parity_contiguity_and_boundary_beats(speed, seconds):
    entry = sample_entry(seconds=seconds)
    wave = entry['waveform']; wave['start_s'] = .125
    count = round(seconds * 200)
    wave['beats'] = [{'sample_index': s} for s in range(25, 25 + count, 100)]
    original = copy.deepcopy(entry)
    settings = {'time_scale': 'fixed', 'speed': f'{speed:g} mm/s'}
    result = paper_segments(entry, settings)
    browser = json.loads(js('console.log(JSON.stringify(ECGReportPaper.paperSegments(input.e,input.p)));', {'e': entry, 'p': settings}))
    assert result == browser
    assert entry == original
    assert all(x['waveform'] is wave for x in result)
    segments = [x['paper_segment'] for x in result]
    cursor = 25
    for s in segments:
        assert round(s['start_s'] * 200) == cursor
        cursor += round(s['duration_s'] * 200)
        assert 0 < s['width_mm'] <= 175
        assert s['width_mm'] == pytest.approx(s['duration_s'] * speed)
    assert cursor == 25 + count
    assert sum(s['beat_count'] for s in segments) == len(wave['beats'])
    assert paper_segments(entry, {}) == [entry]


@pytest.mark.parametrize('count', [1, 3, 6, 12])
def test_svg_pdf_share_physical_clip_geometry(monkeypatch, count):
    entry = sample_entry(count)
    output = js('process.stdout.write(ECGReportPaper.stripSvg(input,{}));', entry)
    root = ET.fromstring(output)
    slots = 1 if count <= 3 else 2 if count <= 6 else 3
    assert float(root.attrib['viewBox'].split()[3]) / 4 == slots * 83 - 17
    clips = []
    original = Canvas.clipPath
    def capture(self, path, *a, **kw):
        clips.append(path.getCode()); return original(self, path, *a, **kw)
    monkeypatch.setattr(Canvas, 'clipPath', capture)
    _register_font()
    build_paper_pdf({'case_id': 'synthetic', 'metadata': {}}, {
        'composition': {'page_selection_version': 1, 'included_pages': ['event_strips']},
        'selected_waveforms': [entry]}, FONT_NAME)
    for svg, pdf in zip(root.findall('s:defs/s:clipPath/s:rect', NS), clips):
        x, y, w, h = map(float, re.search(r'([\d.]+) ([\d.]+) ([\d.]+) ([\d.]+) re', pdf).groups())
        assert x / mm == pytest.approx(10 + float(svg.attrib['x']) / 4, abs=.003)
        assert w / mm == pytest.approx(float(svg.attrib['width']) / 4, abs=.003)
        assert h / mm == pytest.approx(float(svg.attrib['height']) / 4, abs=.003)
        # 10 mm page inset + 10 mm strip origin + 9 mm HTML header.
        assert (A4[1] - y - h) / mm == pytest.approx(29 + float(svg.attrib['y']) / 4, abs=.003)


@pytest.mark.parametrize('count', [3, 6, 12])
@pytest.mark.parametrize('visible', [True, False])
def test_both_renderers_apply_grid_labels_and_keep_evidence(monkeypatch, count, visible):
    entry = sample_entry(count, 7.005)
    entry['strip'].update(visible_beat_count=1, warning='记录可用心搏不足 5 个，当前仅 1 搏')
    entry['waveform']['beats'] = [{'sample_index': 700, 'class_code': 'V', 'hr': 77, 'rr_ms': 777}]
    settings = dict(paper(), time_scale='fixed', speed='50 mm/s', show_grid=visible, show_labels=visible)
    report = {'composition': {'page_selection_version': 1, 'included_pages': ['event_strips'], 'paper': settings}, 'selected_waveforms': [entry]}
    model = {'case': {'case_id': 'synthetic', 'metadata': {}}, 'report': report}
    html = js('process.stdout.write(ECGReportPaper.stripPages(input.model,input.entries));', {'model': model, 'entries': [entry]})
    texts, grids = [], []
    original_text, original_center, original_line = Canvas.drawString, Canvas.drawCentredString, Canvas.line
    def text(self, x, y, s, *a, **kw):
        texts.append(s); return original_text(self, x, y, s, *a, **kw)
    def line(self, x, y, x2, y2):
        if self._lineWidth in (.18, .35):
            grids.append((x, y, x2, y2))
        return original_line(self, x, y, x2, y2)
    def center(self, x, y, s, *a, **kw):
        texts.append(s); return original_center(self, x, y, s, *a, **kw)
    monkeypatch.setattr(Canvas, 'drawString', text)
    monkeypatch.setattr(Canvas, 'drawCentredString', center)
    monkeypatch.setattr(Canvas, 'line', line)
    _register_font()
    pdf = build_paper_pdf(model['case'], report, FONT_NAME).getvalue()
    expected_pages = (1 if count == 3 else 3) + 1  # 3 segments + full warning page
    assert len(re.findall(rb'/Type\s*/Page\b', pdf)) == expected_pages
    assert html.count('<section class="rp-sheet') == expected_pages
    assert ('>777</text>' in html) is visible
    assert ('777' in texts) is visible
    assert ('stroke="#b9b9b9"' in html) is visible
    assert bool(grids) is visible
    assert html.count('>V</text>') == int(visible)  # boundary appears only in segment 2
    assert '记录可用心搏不足 5 个' in html and any('记录可用心搏不足 5 个' in s for s in texts)
    assert '50 mm/s' in html and any('50.00 mm/s' in s for s in texts)
    for token in ['非设备校准', '连续区间 3/3']:
        assert token in html and any(token in s for s in texts)
    assert '>I</text>' in html and 'I' in texts  # never hide lead identity
    assert '0.005 s' in html and any('0.005 s' in s for s in texts)
    assert 'D1 00:00:03.500' in html and 'D1 00:00:03.500' in texts


def test_segment_trace_uses_original_time_coordinates():
    entry=sample_entry(1,7)
    settings={'time_scale':'fixed','speed':'50 mm/s'}
    second=paper_segments(entry,settings)[1]
    output=js('process.stdout.write(ECGReportPaper.stripSvg(input.e,input.p));',{'e':second,'p':settings})
    root=ET.fromstring(output)
    points=[tuple(map(float,p.split(','))) for p in root.find('s:polyline',NS).attrib['points'].split()]
    # Preserve the interpolation neighbour, not a fabricated boundary sample.
    assert points[0][0]==pytest.approx(41,abs=.01)
    assert points[1][0]==48
    assert points[-1][0]==pytest.approx(741,abs=.01)


def test_paper_ui_change_retains_selection_and_voltage_snapshot():
    source = (ROOT / 'static/js/clinical-ui.js').read_text()
    functions = source[source.index('  function gainHtml()'):source.index('  function stripSettingsHtml(')]
    program = r"""
const assert=require('assert');
let changes=0;const speed={disabled:true};
const state={reportComposition:{paper:{voltage_estimate:{mode:'estimated',uv_per_unit:2,calibration_verified:false}},selected_events:[{event_id:'unchanged'}]}};
const composition=()=>structuredClone(state.reportComposition),dirty=()=>changes++,esc=x=>x;
""" + functions + r"""
const before=JSON.stringify(state.reportComposition.selected_events);
for(const [key,value] of [['time_scale','fixed'],['speed','50 mm/s'],['show_grid',false],['show_labels',false]]){
 assert(changePaperSettings({dataset:{paperSetting:key},value,checked:value,closest:()=>({querySelector:()=>speed})}));
}
assert.equal(speed.disabled,false);assert.equal(changes,4);
assert.equal(state.reportComposition.paper.voltage_estimate.uv_per_unit,2);
assert.equal(JSON.stringify(state.reportComposition.selected_events),before);
assert(!changePaperSettings({dataset:{paperSetting:'speed'},value:'99 mm/s'}));
assert(paperSettingsHtml().includes('固定纸速（连续分段）'));
assert(paperSettingsHtml().includes('心搏类型 / HR / RR 标注'));
console.log('ok');
"""
    assert js(program, {}).strip() == 'ok'


@pytest.mark.parametrize('metadata,expected', [({}, '—'), ({'age': None}, '—'),
    ({'age': 0}, '0 岁'), ({'age': 53}, '53 岁')])
def test_summary_age_matches_browser_without_inventing_missing_value(monkeypatch, metadata, expected):
    case = {'case_id': 'synthetic', 'metadata': metadata}
    report = {'composition': {'page_selection_version': 1, 'included_pages': ['summary']}}
    html = js('process.stdout.write(ECGReportPaper.summary(input));',
              {'case': case, 'report': report, 'statistics': {}})
    assert f'<span>年龄：</span>{expected}</div>' in html
    drawn = []
    original = Canvas.drawString
    def capture(self, x, y, value, *args, **kwargs):
        drawn.append(value)
        return original(self, x, y, value, *args, **kwargs)
    monkeypatch.setattr(Canvas, 'drawString', capture)
    _register_font()
    pdf = build_paper_pdf(case, report, FONT_NAME).getvalue()
    assert pdf.startswith(b'%PDF')
    assert f'年龄：{expected}' in drawn
    assert not any('None' in value or 'undefined' in value for value in drawn)


def write_validation_artifacts(directory):
    directory.mkdir(parents=True, exist_ok=True)
    _register_font()
    entries = [sample_entry(n, 8) for n in [3, 6, 12]]
    for entry in entries:
        entry['waveform']['beats'] = [{'sample_index': s, 'class_code': 'N', 'hr': 60, 'rr_ms': 1000} for s in range(100, 1600, 200)]
        entry['strip'].update(visible_beat_count=8, warning='数学验证：保留完整区间，不是患者数据')
        entry['context'] = dict(entry['waveform'], duration_s=24)
    report = {'composition': {'page_selection_version': 1, 'included_pages': ['event_strips'], 'paper': dict(paper(5), time_scale='fixed', speed='50 mm/s')}, 'selected_waveforms': entries}
    case = {'case_id': 'synthetic-paper-settings', 'metadata': {'name': '数学合成（非患者）'}}
    (directory / 'synthetic-paper.pdf').write_bytes(build_paper_pdf(case, report, FONT_NAME).getvalue())
    html = js('process.stdout.write(ECGReportPaper.stripPages(input.model,input.entries));', {'model': {'case': case, 'report': report}, 'entries': entries})
    (directory / 'index.html').write_text('<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>A4 纸速设置数学验证</title><style>body{margin:0}' + (ROOT / 'static/css/report-paper.css').read_text() + '</style><main class="rp-pages">' + html + '</main></html>')


def test_paper_settings_only_appear_in_global_strip_settings():
    source = (ROOT / 'static/js/clinical-ui.js').read_text()
    function = source[source.index('  function stripSettingsHtml('):source.index('  function changeStripSettings(')]
    program = r"""
const assert=require('assert');
const ECGReportEngine={settings:x=>x,leads:['II','V1','V5']};
const paperSettingsHtml=()=>'<div>paper-controls</div>';
let category='fastest';
""" + function + r"""
const spec={leads:['II','V1','V5'],duration_s:7};
assert(!stripSettingsHtml(spec,'default').includes('paper-controls'));
category='strips';
assert(stripSettingsHtml(spec,'default').includes('paper-controls'));
assert(!stripSettingsHtml(spec,'0').includes('paper-controls'));
console.log('ok');
"""
    assert js(program, {}).strip() == 'ok'


if __name__ == '__main__':
    import sys
    write_validation_artifacts(__import__('pathlib').Path(sys.argv[1]))
