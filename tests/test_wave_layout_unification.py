"""Screen layout preserves source coordinates, labels and recorder clocks."""
import json
from pathlib import Path
import subprocess
import pytest
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]


def test_legacy_two_column_request_is_vertical_and_keeps_all_samples_and_shared_labels():
    result = json.loads(subprocess.check_output(['node', '-e', r'''
require('./static/js/clinical-review-tools.js');const card=require('./static/js/occurrence-card.js');
const names=['I','II','III','aVR','aVL','aVF','V1','V2','V3','V4','V5','V6'];
const values=Array.from({length:3000},(_,i)=>Math.sin(i/15)*30);values[701]=1600;values[1183]=-1500;
const wave={start_s:10,duration_s:15,sample_rate_hz:200,stride:1,filter:'raw',
leads:Object.fromEntries(names.map(n=>[n,[...values]])),beats:[{sample_index:2701,class_code:'V'},{sample_index:3183,class_code:'N'}]};
const source=JSON.stringify(wave),opts={width:1200,height:864,columns:2,timeAxis:true,domain:2000,recordStart:'2026-10-23 23:59:54'};
console.log(JSON.stringify({a:card.svg(wave,{},opts),b:card.svg({...wave,start_s:70}, {}, opts),unchanged:source===JSON.stringify(wave),
meta:ECGReviewTools.waveMeta(wave,opts.recordStart,2000),unknown:ECGReviewTools.waveMeta(wave)}));
'''], cwd=ROOT, text=True))
    assert result['unchanged']
    a, b = [ET.fromstring(result[key]) for key in ('a', 'b')]
    assert a.attrib['data-columns'] == '1'
    assert not a.findall('.//svg')
    assert a.attrib['data-sample-rate'] == '200'
    assert a.attrib['data-stride'] == '1'
    assert a.attrib['data-display-duration'] == b.attrib['data-display-duration'] == '15'
    rows = a.findall('.//g[@data-wave-lead]')
    assert len(rows) == 12 and rows[-1].attrib['data-wave-lead'] == 'V6'
    assert len(a.findall('.//g[@data-fiducial-sample]')) == 2
    assert len(a.findall('.//text[@data-wave-time]')) >= 3
    assert any(x.text == '00:00:04.000' for x in a.findall('.//text[@data-wave-time]'))
    assert '2026-10-24 00:00:04.000' in result['meta']
    assert '200 Hz' in result['meta'] and '±2000 u' in result['meta']
    assert '未校准' in result['meta'] and '纸速未标定' in result['meta']
    assert '记录时钟未提供' in result['unknown']
    assert [row.attrib['data-wave-scale'] for row in rows] == [row.attrib['data-wave-scale'] for row in b.findall('.//g[@data-wave-lead]')]
    for row in rows:
        points = [tuple(map(float, point.split(','))) for point in row.find('polyline').attrib['points'].split()]
        assert len(points) == 3000
        assert points[701][0] == pytest.approx(24 + 701 / 200 / 15 * 1152, abs=.0005)
        assert min(y for _, y in points) >= float(row.attrib['data-signal-top']) - .001
        assert max(y for _, y in points) <= float(row.attrib['data-signal-bottom']) + .001
