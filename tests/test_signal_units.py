"""Raw import units and paper scaling: mathematical fixtures, no patient writes."""
import json
import re
import struct
import subprocess
from pathlib import Path

import pytest

from ecg_core.analysis_provenance import MODULES
from ecg_core.overview import density
from ecg_core.report_paper_pdf import build_paper_pdf
from ecg_core.report_pdf import _register_font, FONT_NAME
from ecg_core.signal_profile import raw_signal_metadata, calibrated_uv_per_unit
from ecg_core.waveform import ALL_LEADS, read_waveform, read_waveform_strips, read_event_waveform
from test_analysis_provenance import synthetic_case, synthetic_app

ROOT = Path(__file__).resolve().parents[1]


def node(program, payload=None):
    return subprocess.check_output(['node', '-e', program], cwd=ROOT, text=True,
                                   input=json.dumps(payload) if payload is not None else None)


def assert_raw(payload):
    for key, expected in raw_signal_metadata().items():
        assert payload[key] == expected
    assert 'µV' not in payload['calibration_note']


def test_profile_is_explicit_detached_and_bound_to_engine():
    a = raw_signal_metadata()
    assert a['signal_profile']['device_verified'] is False
    assert a['signal_profile']['sample_rate_hz'] == 200
    assert len(a['signal_profile']['stored_leads']) == 8
    assert len(a['signal_profile']['derived_leads']) == 4
    assert 'signal_profile' in MODULES
    a['signal_profile']['stored_leads'].clear()
    assert len(raw_signal_metadata()['signal_profile']['stored_leads']) == 8


@pytest.mark.parametrize('filtered', [False, True])
def test_raw_readers_keep_numbers_mapping_times_and_metadata(tmp_path, filtered):
    path = tmp_path/'known.DATA'
    frame = (3, 8, -32768, 32767, -1000, 0, 500, -5)
    path.write_bytes(struct.pack('<8h', *frame)*2000)
    wave = read_waveform(path, .125, 3, ALL_LEADS, 200, filtered)
    assert_raw(wave)
    assert (wave['start_s'], wave['duration_s'], wave['stride'], wave['display_sample_rate_hz']) == (.125, 3, 3, 200/3)
    expected = dict(zip(ALL_LEADS, [3, 8, 5, -5.5, -1, 6.5, -32768, 32767, -1000, 0, 500, -5]))
    for lead, value in expected.items():
        assert wave['leads'][lead] == [0 if filtered else value]*200
    overview = read_event_waveform(path, .125, 3.125, ALL_LEADS, 200)
    assert_raw(overview)
    for lead, value in expected.items():
        assert overview['leads'][lead] == [value]*200
    batch = read_waveform_strips(path, [400], 1.5, 2.5, ALL_LEADS, 800, filtered)
    assert_raw(batch)
    item = batch['items'][0]
    assert_raw(item)
    assert item['anchor_offset_s'] == 1.5
    assert item['leads'] == read_waveform(path, .5, 4, ALL_LEADS, 800, filtered)['leads']
    d = density(path, [400], 'III')
    assert d['units'] == 'device_unit' and d['calibration_verified'] is False
    assert sum(d['bins']) == 200


def test_all_waveform_apis_and_technical_metadata_agree(synthetic_app, synthetic_case):
    client = synthetic_app.test_client()
    base = '/api/cases/'+synthetic_case[1]
    assert_raw(client.get(base).json['technical'])
    for route in ['/waveform?start=1&duration=7', '/event-waveform?start=1&end=8']:
        response = client.get(base+route)
        assert response.status_code == 200, response.json
        assert_raw(response.json)
    batch = client.post(base+'/event-waveforms', json={'ranges':[{'start':1, 'end':8}]}).json
    assert_raw(batch['items'][0])
    strips = client.post(base+'/waveform-strips', json={'sample_indices':[400]}).json
    assert_raw(strips)
    assert_raw(strips['items'][0])
    event = client.get(base+'/report-events?category=fastest').json['items'][0]
    report = client.get(base+'/report-strip', query_string={
        'event_id':event['event_id'], 'basis_version':event['basis_version']})
    assert report.status_code == 200, report.json
    assert_raw(report.json['waveform'])
    if report.json.get('context'):
        assert_raw(report.json['context'])


def test_demo_metadata_matches_python_and_is_attached_to_each_strip():
    program = r"""const fs=require('fs'),vm=require('vm');
    const s=fs.readFileSync('demo/static/js/demo-api.js','utf8');
    const line=s.split('\n').find(l=>l.includes('const rawSignalMetadata='));
    console.log(vm.runInNewContext('const RATE=200;'+line+'JSON.stringify(rawSignalMetadata())'));
    """
    assert json.loads(node(program)) == raw_signal_metadata()
    source = (ROOT/'demo/static/js/demo-api.js').read_text()
    assert 'Object.assign(item.technical,rawSignalMetadata())' in source
    assert 'stride,...rawSignalMetadata(),filter:' in source
    assert 'return {...wave,...beat,sample_index:sample' in source
    assert 'units:"µV"' not in source


@pytest.mark.parametrize('unit,verified,expected', [
    ('device_unit', True, None), ('µV', False, None), ('mV', False, None),
    ('unknown', True, None), (None, True, None), ([], True, None),
    ('µV', 'true', None), ('µV', 1, None),
    ('µV', True, 1), ('μV', True, 1), ('uV', True, 1), ('mV', True, 1000),
])
def test_voltage_scale_requires_verified_known_unit(unit, verified, expected):
    assert calibrated_uv_per_unit({'units':unit, 'calibration_verified':verified}) == expected


def entry(unit='device_unit', verified=False, divisor=1):
    return {'strip':{'leads':['II'], 'visible_beat_count':5},
            'waveform':{'start_s':0, 'duration_s':7, 'display_sample_rate_hz':200,
                        'units':unit, 'calibration_verified':verified,
                        'leads':{'II':[v/divisor for v in [-1000, 0, 1000, 2000, 0]]}, 'beats':[]}}


def svg(data):
    return node("require('./static/js/report-paper.js');const x=JSON.parse(require('fs').readFileSync(0,'utf8'));process.stdout.write(ECGReportPaper.stripSvg(x));", data)


@pytest.mark.parametrize('unit,verified', [('device_unit', True), ('µV', False), (None, True), ('unknown', True)])
def test_svg_does_not_trust_boolean_without_physical_units(unit, verified):
    output = svg(entry(unit, verified))
    assert '电压未校准' in output and 'mm/mV' not in output
    assert 'NaN' not in output and 'Infinity' not in output


def test_svg_equivalent_mv_uv_have_identical_geometry_and_one_mv_pulse():
    assert svg(entry('µV', True)) == svg(entry('mV', True, 1000))
    assert 'v-40.00h8v40.00' in svg(entry('µV', True))


@pytest.mark.parametrize('unit,verified', [('device_unit', True), ('µV', False), (None, True), ('mV', True)])
def test_pdf_footer_obeys_unit_contract(monkeypatch, unit, verified):
    from reportlab.pdfgen.canvas import Canvas
    drawn = []
    original = Canvas.drawString
    def capture(self, x, y, text, *args, **kwargs):
        drawn.append(text)
        return original(self, x, y, text, *args, **kwargs)
    monkeypatch.setattr(Canvas, 'drawString', capture)
    _register_font()
    data = build_paper_pdf({'case_id':'synthetic', 'metadata':{}}, {
        'composition':{'page_selection_version':1, 'included_pages':['event_strips']},
        'selected_waveforms':[entry(unit, verified, 1000 if unit=='mV' else 1)]}, FONT_NAME)
    assert data.getvalue().startswith(b'%PDF')
    text = '\n'.join(drawn)
    assert ('10 mm/mV' in text) == (unit=='mV' and verified)
    assert ('电压未校准' in text) == (unit!='mV' or not verified)


def test_display_zoom_does_not_claim_physical_gain():
    html = (ROOT/'templates/index.html').read_text()
    select = re.search(r'<select id="gainSelect".*?</select>', html).group()
    assert 'mm/mV' not in select
    assert all(v in select for v in ['0.5×', '1×', '2×'])
    assert re.search(r'<select id="reportPaperGain"[^>]* disabled', html)
    app = (ROOT/'static/js/app.js').read_text()
    assert "+' mV':'1000 u'" in app
    assert 'const millivolts=Number(values[valueIndex]||0)/1000' not in app
    assert '${escapeHtml(state.reportComposition.paper.gain)}' not in app
