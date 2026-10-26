"""Full-width 12-lead screen geometry with shared timing and label provenance."""
import json
from pathlib import Path
import subprocess
import xml.etree.ElementTree as ET

import pytest

ROOT = Path(__file__).resolve().parents[1]


def test_twelve_rows_have_one_time_axis_and_unchanged_samples_gain_and_annotations():
    result = json.loads(subprocess.check_output(['node', '-e', r'''
require('./static/js/clinical-review-tools.js');require('./static/js/occurrence-card.js');
require('./static/js/report-workspace.js');const workspace=globalThis.ECGReportWorkspace;
const names=['I','II','III','aVR','aVL','aVF','V1','V2','V3','V4','V5','V6'];
const values=[0,-1200,1300,-700,0],wave={start_s:10,duration_s:15,sample_rate_hz:200,stride:1,
 beats:[{sample_index:2001,class_code:'V'},{sample_index:2002,class_code:'N'}],
 leads:Object.fromEntries(names.map((n,i)=>[n,i%2?values.map(x=>-x):values]))};
const before=JSON.stringify(wave),options={width:895,height:360,domain:1500};
console.log(JSON.stringify({a:workspace.reviewWaveSvg(wave,null,options),
 b:workspace.reviewWaveSvg({...wave,start_s:70},null,options),unchanged:before===JSON.stringify(wave)}));
'''], cwd=ROOT, text=True))
    assert result['unchanged']
    a, b = map(ET.fromstring, (result['a'], result['b']))
    assert a.attrib['data-columns'] == '1'
    assert len(a.findall('.//svg')) == 0
    assert float(a.attrib['viewBox'].split()[3]) >= 720
    assert float(a.attrib['data-plot-width']) > 840
    assert a.attrib['data-display-duration'] == b.attrib['data-display-duration'] == '15'
    leads = a.findall('.//g[@data-wave-lead]')
    assert [g.attrib['data-wave-lead'] for g in leads] == ['I','II','III','aVR','aVL','aVF','V1','V2','V3','V4','V5','V6']
    baselines = [float(g.attrib['data-wave-baseline']) for g in leads]
    assert all(y-x >= 56 for x,y in zip(baselines,baselines[1:]))
    assert len({g.attrib['data-wave-scale'] for g in leads}) == 1
    assert [g.attrib['data-wave-scale'] for g in leads] == [g.attrib['data-wave-scale'] for g in b.findall('.//g[@data-wave-lead]')]
    assert len(a.findall('.//g[@data-fiducial-sample]')) == 2
    for lead in leads:
        y = [float(p.split(',')[1]) for p in lead.find('polyline').attrib['points'].split()]
        assert min(y) >= float(lead.attrib['data-signal-top'])-.001
        assert max(y) <= float(lead.attrib['data-signal-bottom'])+.001
