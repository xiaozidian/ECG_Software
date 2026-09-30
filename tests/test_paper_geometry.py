"""Synthetic paper coordinates; never use patient data or a calibration claim."""
import json
from pathlib import Path
import re
import subprocess
import xml.etree.ElementTree as ET

import pytest
from reportlab.lib.units import mm
from reportlab.pdfgen.canvas import Canvas

from ecg_core.report_layout import LEADS
from ecg_core.report_paper_pdf import build_paper_pdf
from ecg_core.report_pdf import _register_font, FONT_NAME

ROOT = Path(__file__).resolve().parents[1]
NS = {'s': 'http://www.w3.org/2000/svg'}


def sample_entry(count=3, seconds=7):
    # A large excursion with two distinct out-of-frame samples followed by a
    # normal small pulse. Clamping would replace it with an artificial plateau.
    values = [0] * 200
    values[40:46] = [0, 1500, 3000, 2000, -2500, 0]
    values[120:124] = [0, 500, -200, 0]
    leads = LEADS[:count]
    return {
        'label': '数学合成图条（非患者）', 'caption': '超框裁切与网格验证',
        'strip': {'leads': leads, 'visible_beat_count': 0},
        'waveform': {'start_s': 0, 'duration_s': seconds,
                     'display_sample_rate_hz': len(values) / seconds,
                     'units': 'device_unit', 'calibration_verified': False,
                     'leads': {name: values for name in leads}, 'beats': []},
    }


def paper(gain=10):
    return {'gain': f'{gain} mm/mV', 'voltage_estimate': {
        'mode': 'estimated', 'uv_per_unit': 1, 'calibration_verified': False}}


def js(program, payload):
    return subprocess.check_output(['node', '-e',
        "require('./static/js/voltage-estimate.js');require('./static/js/report-paper.js');"
        "const input=JSON.parse(require('fs').readFileSync(0,'utf8'));" + program],
        input=json.dumps(payload), text=True, cwd=ROOT)


@pytest.mark.parametrize('count', [1, 3, 6, 12])
@pytest.mark.parametrize('gain', [5, 10, 20])
@pytest.mark.parametrize('seconds', [7, 14])
def test_svg_clips_geometry_without_rewriting_samples(count, gain, seconds):
    entry = sample_entry(count, seconds)
    slots = 1 if count <= 3 else 2 if count <= 6 else 3
    output = js('process.stdout.write(ECGReportPaper.stripSvg(input.entry,input.paper,input.height));',
                dict(entry=entry, paper=paper(gain), height=slots * 304 - 28))
    root = ET.fromstring(output)
    paths = root.findall('s:polyline', NS)
    clips = root.findall('s:defs/s:clipPath', NS)
    assert len(paths) == len(clips) == count
    for trace, clip in zip(paths, clips):
        points = [tuple(map(float, p.split(','))) for p in trace.attrib['points'].split()]
        assert len(points) == len(entry['waveform']['leads'][LEADS[0]])
        assert trace.attrib['clip-path'] == f"url(#{clip.attrib['id']})"
        assert clip.attrib['clipPathUnits'] == 'userSpaceOnUse'
        # Four SVG units per mm; distinct 3000u and 2000u stay distinct.
        assert points[42][1] - points[43][1] == pytest.approx(-4 * gain, abs=.02)
        assert points[44][1] - points[0][1] == pytest.approx(10 * gain, abs=.02)
        assert points[120][0] - points[40][0] == pytest.approx(280, abs=.02)
        assert points[0][0] == 48 and points[-1][0] < 748
    assert '非设备校准' in output
    assert 'NaN' not in output and 'Infinity' not in output


def test_multiple_svg_instances_have_independent_clip_ids():
    output = js('console.log(ECGReportPaper.stripSvg(input,{})+ECGReportPaper.stripSvg(input,{}));', sample_entry())
    ids = re.findall(r'<clipPath id="([^"]+)"', output)
    assert len(ids) == len(set(ids)) == 6


@pytest.mark.parametrize('count', [3, 6, 12])
@pytest.mark.parametrize('gain', [5, 10, 20])
def test_pdf_retains_voltage_coordinates_and_uses_clip_viewport(monkeypatch, count, gain):
    clips, traces = [], []
    original_clip, original_draw = Canvas.clipPath, Canvas.drawPath
    def clip(self, path, *args, **kwargs):
        clips.append(path.getCode())
        return original_clip(self, path, *args, **kwargs)
    def draw(self, path, *args, **kwargs):
        if len(re.findall(r'\bl\b', path.getCode())) == 199:
            traces.append(path.getCode())
        return original_draw(self, path, *args, **kwargs)
    monkeypatch.setattr(Canvas, 'clipPath', clip)
    monkeypatch.setattr(Canvas, 'drawPath', draw)
    _register_font()
    entry = sample_entry(count)
    source = json.dumps(entry)
    result = build_paper_pdf({'case_id': 'synthetic', 'metadata': {}}, {
        'composition': {'page_selection_version': 1, 'included_pages': ['event_strips'], 'paper': paper(gain)},
        'selected_waveforms': [entry]}, FONT_NAME)
    assert result.getvalue().startswith(b'%PDF')
    assert json.dumps(entry) == source
    assert len(clips) == len(traces) == count
    for code in traces:
        points = [(float(x), float(y)) for x, y in re.findall(r'(-?[\d.]+) (-?[\d.]+) [ml]\b', code)]
        assert len(points) == 200
        assert points[42][1] - points[43][1] == pytest.approx(gain * mm, abs=.002)
        assert points[44][1] - points[0][1] == pytest.approx(-2.5 * gain * mm, abs=.002)
        assert points[120][0] - points[40][0] == pytest.approx(70 * mm, abs=.002)


def write_validation_artifacts(directory):
    """Create non-patient QA artifacts with the actual production renderers."""
    directory.mkdir(parents=True, exist_ok=True)
    _register_font()
    entries = [sample_entry(3, seconds) for seconds in [7, 14, 7]] + [sample_entry(6), sample_entry(12)]
    report = {'composition': {'page_selection_version': 1, 'included_pages': ['event_strips'], 'paper': paper()},
              'selected_waveforms': entries}
    case = {'case_id': 'synthetic-paper-geometry', 'metadata': {'name': '数学合成（非患者）'}}
    (directory / 'synthetic-paper.pdf').write_bytes(build_paper_pdf(case, report, FONT_NAME).getvalue())
    markup = js('process.stdout.write(ECGReportPaper.stripPages(input.model,input.entries));',
                {'model': {'case': case, 'report': report}, 'entries': entries})
    css = (ROOT / 'static/css/report-paper.css').read_text()
    (directory / 'index.html').write_text('<!doctype html><html lang="zh-CN"><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1"><title>A4 数学验证</title>'
        '<style>body{margin:0}' + css + '</style><main class="rp-pages">' + markup + '</main></html>')


if __name__ == '__main__':
    import sys
    write_validation_artifacts(Path(sys.argv[1]))
