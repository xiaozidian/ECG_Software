"""Display-only partial evidence; never promote it to continuous event proof."""
import copy
import json
import os
from pathlib import Path
import subprocess

import pytest
from reportlab.lib.units import mm

from ecg_core.stt import minute_trends, DEFAULT_CONFIG, _lead_episodes
from ecg_core.report_sections_pdf import documents, make_supplement_pages
from test_stt_hospital_report_output import model, node, CanvasProbe

ROOT=Path(__file__).resolve().parents[1]


def partial_model(value=12.5,coverage=75):
    m=model()
    partial=dict(time_s=30,start_s=0,end_s=60,eligible=False,coverage_pct=0,
        st_level_units=None,measured_st_level_units=None,partial_st_level_units=value,
        t_amplitude_units=None,measured_t_amplitude_units=None,partial_t_amplitude_units=-25,
        metric_coverage_pct={'st_level_units':coverage,'t_amplitude_units':40},quality_flags=['incomplete_support'])
    m['evidence']['st_trends']={'I':[partial,
        dict(time_s=90,st_level_units=10,eligible=True),
        dict(time_s=150,st_level_units=None,partial_st_level_units=None,eligible=False),
        dict(time_s=210,st_level_units=15,eligible=True),
        dict(time_s=270,st_level_units=20,eligible=True)]}
    m['evidence']['st_representatives']=[]
    return m


@pytest.mark.parametrize('key',['st_trend','t_trend'])
def test_partial_observation_is_identical_in_native_browser_and_demo_models(key):
    m=partial_model();before=copy.deepcopy(m)
    native=documents(m['case'],{**m['report'],'section_evidence':m['evidence']},[key])
    assert node(m,'a.documents(m,'+json.dumps([key])+')')==native
    point=native[0]['trend_rows'][0]['points'][0]
    assert point['partial'] is True and point['y']==(12.5 if key=='st_trend' else -25)
    assert point['metric_coverage_pct']==(75 if key=='st_trend' else 40)
    assert point['coverage_pct']==0  # engineering quality is a different quantity
    assert point['quality_suspected'] is True
    assert '部分实测' in native[0]['paragraphs'][1]
    assert ('75%' if key=='st_trend' else '40%') in native[0]['partial_coverage_lines'][0]
    assert m==before


@pytest.mark.parametrize('value,coverage',[(0,20),(-1.25,72.47),(3,None)])
def test_zero_negative_and_unknown_coverage_are_not_erased_or_relabelled_full(value,coverage):
    m=partial_model(value,coverage)
    doc=documents(m['case'],{**m['report'],'section_evidence':m['evidence']},['st_trend'])[0]
    p=doc['trend_rows'][0]['points'][0]
    assert p['y']==value and p['partial'] is True and p['metric_coverage_pct']==coverage
    assert node(m,"a.documents(m,['st_trend'])")==[doc]
    html=node(m,"a.pages(m,['st_trend'])")
    assert 'data-stt-partial="true"' in html
    assert ('未提供' if coverage is None else str(coverage)+'%') in html


def test_partial_is_never_connected_across_missing_or_promoted_to_complete_minute():
    pts=[dict(start_s=0,end_s=15,time_s=0,measurable=False,eligible=False),
         dict(start_s=15,end_s=60,time_s=15,measurable=True,eligible=False,
              st_level_units=-150,t_amplitude_units=-180,quality_flags=['suspect'])]
    minute=minute_trends(pts,60,DEFAULT_CONFIG)[0]
    assert minute['st_level_units'] is None and minute['measured_st_level_units'] is None
    assert minute['partial_st_level_units']==-150 and minute['metric_coverage_pct']['st_level_units']==75
    assert not minute['eligible']
    assert _lead_episodes(pts,'II',DEFAULT_CONFIG)==[]
    m=partial_model();html=node(m,"a.pages(m,['st_trend'])")
    first=html.split('data-stt-trend-lead="I"',1)[1].split('</g>',1)[0]
    assert first.count('data-stt-partial="true"')==1
    # The only continuous solid segment is the last two complete minutes.
    path=first.split('<path d="',1)[1].split('"',1)[0]
    assert path.count('M')==2 and path.count('L')==1
    assert 'data-stt-coverage="75"' in first and '实测覆盖 75%' in first


def test_measured_full_warning_stays_complete_and_missing_is_not_zero():
    m=partial_model();p=m['evidence']['st_trends']['I'][0]
    p['measured_st_level_units']=-12;p['partial_st_level_units']=99;p['metric_coverage_pct']['st_level_units']=100
    doc=documents(m['case'],{**m['report'],'section_evidence':m['evidence']},['st_trend'])[0]
    row=doc['trend_rows'][0]['points']
    assert row[0]['partial'] is False and row[0]['y']==-12 and row[0]['quality_suspected']
    assert row[2]['y'] is None and row[2]['partial'] is False
    assert node(m,"a.documents(m,['st_trend'])")==[doc]


class DrawingProbe(CanvasProbe):
    def __init__(self):super().__init__();self.paths=[];self.circles=[]
    def beginPath(self):
        path=[];self.paths.append(path)
        class Path:
            def moveTo(_,x,y):path.append(('M',x,y))
            def lineTo(_,x,y):path.append(('L',x,y))
        return Path()
    def circle(self,x,y,r,**kwargs):self.circles.append((r,kwargs));super().circle(x,y,r,**kwargs)


def test_native_draws_independent_hollow_partial_and_actual_coverage_summary():
    m=partial_model();c=DrawingProbe();report={**m['report'],'section_evidence':m['evidence']}
    for draw in make_supplement_pages(c,'probe',m['case'],report,['st_trend']):draw()
    assert sum(abs(r-.4*mm)<1e-8 and k.get('stroke')==1 and k.get('fill')==1 for r,k in c.circles)==1
    assert max(sum(cmd[0]=='L' for cmd in path) for path in c.paths)==1
    assert any('部分实测覆盖率：I 75%（1点）' in text for text in c.texts)
    assert not any('mV' in text for text in c.texts)


def test_actual_chromium_workstation_and_demo_partial_display(tmp_path):
    env={**os.environ,'ECG_STT_PARTIAL_EVIDENCE':str(tmp_path)}
    result=subprocess.run(['node','tests/browser_stt_partial_display.cjs'],cwd=ROOT,env=env,capture_output=True,text=True,timeout=90)
    assert result.returncode==0,result.stdout+result.stderr
    proof=json.loads((tmp_path/'partial-display.json').read_text())
    assert proof['status']=='passed' and len(proof['checks'])==5
    assert proof['point']['partial']==12.5 and proof['point']['metric_coverage_pct']==75
    assert proof['network_requests']==0 and proof['source_DTO_unchanged'] is True
