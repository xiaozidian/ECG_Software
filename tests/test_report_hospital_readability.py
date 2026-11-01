"""Readable report geometry from mathematical signals; no patient inputs."""
import json
from pathlib import Path
import subprocess
import xml.etree.ElementTree as ET

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope='module')
def rendered():
    source = r'''
const tools=require('./static/js/clinical-review-tools.js');
const card=require('./static/js/occurrence-card.js');
require('./static/js/report-workspace.js');
const names=['I','II','III','aVR','aVL','aVF','V1','V2','V3','V4','V5','V6'];
const factors=[4,1,.8,.5,.6,.9,.4,.7,1.1,.9,1,.8];
const beats=Array.from({length:15},(_,i)=>({sample_index:2000+i*200+100,class_code:i===7?'S':'N',rr_ms:1000,hr:60}));
const wave={start_s:10,duration_s:15,sample_rate_hz:200,stride:1,filter:'raw',beats,
 leads:Object.fromEntries(names.map((n,j)=>[n,Array.from({length:3000},(_,i)=>{const t=(i%200-100)/200;return 2500+j*400+factors[j]*(70*Math.exp(-((t/.018)**2))-20*Math.exp(-(((t-.04)/.016)**2))+12*Math.exp(-(((t-.25)/.06)**2)));})]))};
const before=JSON.stringify(wave),profile=tools.reportAmplitude(wave),three={...wave,leads:Object.fromEntries(['II','V1','V5'].map(n=>[n,wave.leads[n]]))};
const shifted={...wave,leads:Object.fromEntries(names.map(n=>[n,wave.leads[n].map(v=>v+900000)]))};
const shiftedThree={...shifted,leads:Object.fromEntries(['II','V1','V5'].map(n=>[n,shifted.leads[n]]))};
const opts={width:1450,rowHeight:120,timeAxis:true,displayProfile:profile,inset:0};
const flat={...three,leads:{II:Array(3000).fill(3500),V1:Array(3000).fill(-2000),V5:Array(3000).fill(0)}};
console.log(JSON.stringify({source:wave,unchanged:before===JSON.stringify(wave),profile,
 main:card.svg(three,beats[7],opts),shifted:card.svg(shiftedThree,beats[7],{...opts,displayProfile:tools.reportAmplitude(shifted)}),
 mini:card.svg(three,beats[7],{width:400,height:144,timeAxis:true,annotations:'none',displayProfile:profile,reportPreview:true}),
 twelve:ECGReportWorkspace.reviewWaveSvg(wave,beats[7],{width:1450,displayProfile:profile}),
 magnified:card.svg(three,beats[7],{...opts,pixelGain:3*(120-12)/(2*profile.domain)}),
 flat:card.svg(flat,{}, {...opts,displayProfile:tools.reportAmplitude(flat)})}));
'''
    return json.loads(subprocess.check_output(['node', '-e', source], cwd=ROOT, text=True))


def rows(svg):
    return ET.fromstring(svg).findall('.//g[@data-wave-lead]')


def points(row):
    return [tuple(map(float, p.split(','))) for p in row.find('polyline').attrib['points'].split()]


def test_dc_offset_does_not_flatten_or_move_the_report_trace(rendered):
    assert rendered['unchanged']
    original, shifted = rows(rendered['main']), rows(rendered['shifted'])
    assert len(original) == len(shifted) == 3
    for a, b in zip(original, shifted):
        for p, q in zip(points(a), points(b)):
            assert p == pytest.approx(q, abs=.001)
    assert rendered['profile']['domain'] < 200  # The 2500-u DC is positioning only.


@pytest.mark.parametrize('view,leads', [('main', 3), ('mini', 3), ('twelve', 12), ('magnified', 3)])
def test_real_samples_and_relative_amplitudes_survive_fitting(rendered, view, leads):
    groups = rows(rendered[view])
    assert len(groups) == leads
    assert len({g.attrib['data-wave-scale'] for g in groups}) == 1
    for group in groups:
        data = points(group)
        assert len(data) == 3000
        assert group.find('polyline').attrib['opacity'] == '1'
        assert group.attrib['data-wave-overflow'] == 'false'
        top, bottom = map(float, (group.attrib['data-signal-top'], group.attrib['data-signal-bottom']))
        assert min(y for _, y in data) >= top - .001
        assert max(y for _, y in data) <= bottom + .001
        source = rendered['source']['leads'][group.attrib['data-wave-lead']]
        scale = float(group.attrib['data-wave-scale'])
        # Independent difference invariant: DC positioning cancels out.
        assert data[100][1] - data[108][1] == pytest.approx(-(source[100]-source[108])*scale, abs=.0011)
    ii = next(g for g in groups if g.attrib['data-wave-lead'] == 'II')
    height = max(y for _, y in points(ii)) - min(y for _, y in points(ii))
    assert height > (10 if view == 'mini' else 20)


def test_hr_and_rr_are_centered_on_their_source_interval(rendered):
    svg = ET.fromstring(rendered['main'])
    left, width = map(float, (svg.attrib['data-plot-left'], svg.attrib['data-plot-width']))
    groups = svg.findall('.//g[@data-interval-sample]')
    assert len(groups) == 14  # First preceding interval extends outside the window.
    for group in groups:
        start, end = float(group.attrib['data-interval-start']), float(group.attrib['data-interval-end'])
        labels = group.findall('text')
        x = left + ((start+end)/2-10)/15*width
        assert [n.text for n in labels] == ['60', '1000']
        assert all(float(n.attrib['x']) == pytest.approx(x) for n in labels)
    assert svg.findall('.//path[@data-ruler-units]')


def test_flat_source_is_flat_and_gain_is_finite(rendered):
    for group in rows(rendered['flat']):
        values = {y for _, y in points(group)}
        assert len(values) == 1
        assert float(group.attrib['data-wave-scale']) > 0


def test_review_twelve_keeps_original_beat_labels_and_all_leads(rendered):
    svg = ET.fromstring(rendered['twelve'])
    assert [r.attrib['data-wave-lead'] for r in rows(rendered['twelve'])] == list(rendered['source']['leads'])
    assert [int(g.attrib['data-fiducial-sample']) for g in svg.findall('.//g[@data-fiducial-sample]')] == [b['sample_index'] for b in rendered['source']['beats']]
    colored = svg.findall('.//polyline[@data-class-code="S"]')
    assert len(colored) == 12
    assert all(int(p.attrib['data-class-sample']) == rendered['source']['beats'][7]['sample_index'] for p in colored)


@pytest.mark.parametrize('height', [144, 176])
@pytest.mark.parametrize('lead_count', [1, 3, 12])
def test_report_card_fits_all_rows_and_source_peaks_in_one_frame(height, lead_count):
    result = json.loads(subprocess.check_output(['node', '-e', r'''
const tools=require('./static/js/clinical-review-tools.js'),card=require('./static/js/occurrence-card.js');
const names=JSON.parse(process.argv[1]),height=Number(process.argv[2]);
const source=Object.fromEntries(names.map((name,i)=>[name,Array.from({length:200},(_,j)=>5000+i*300+(j===40?-1:j===43?1:0)*(i===0?1200:400))]));
const wave={start_s:0,duration_s:1,sample_rate_hz:200,stride:1,leads:source,beats:[]},before=JSON.stringify(wave);
console.log(JSON.stringify({svg:card.svg(wave,{}, {width:300,height,timeAxis:true,annotations:'none',reportPreview:true,displayProfile:tools.reportAmplitude(wave)}),source,unchanged:JSON.stringify(wave)===before}));
''', json.dumps(['II'] if lead_count == 1 else ['II', 'V1', 'V5'] if lead_count == 3 else ['I', 'II', 'III', 'aVR', 'aVL', 'aVF', 'V1', 'V2', 'V3', 'V4', 'V5', 'V6']), str(height)], cwd=ROOT, text=True))
    svg = ET.fromstring(result['svg'])
    assert result['unchanged']
    assert float(svg.attrib['viewBox'].split()[3]) == height
    groups = rows(result['svg'])
    assert len(groups) == lead_count
    assert len({g.attrib['data-wave-scale'] for g in groups}) == 1
    for group in groups:
        data = points(group)
        source = result['source'][group.attrib['data-wave-lead']]
        baseline, gain = float(group.attrib['data-wave-baseline']), float(group.attrib['data-wave-scale'])
        top, bottom = float(group.attrib['data-signal-top']), float(group.attrib['data-signal-bottom'])
        assert 0 <= top < bottom < height
        assert len(data) == len(source) == 200
        assert group.find('polyline').attrib['opacity'] == '1'
        assert all(top-.001 <= y <= bottom+.001 for _, y in data)
        assert all(y == pytest.approx(baseline-v*gain, abs=.001) for (_, y), v in zip(data, source))
