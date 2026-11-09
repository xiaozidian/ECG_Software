"""Mathematical document/render contracts. No PDF, patient file or server IO."""
import copy
import json
import math
from pathlib import Path
import subprocess

import pytest
from reportlab.lib.pagesizes import A4

from ecg_core.report_sections_pdf import documents, make_supplement_pages
from ecg_core.report_sections import evidence as section_evidence, st_report_events, st_summary
from ecg_core.report_paper_pdf import conclusion_text

ROOT=Path(__file__).resolve().parents[1]
LEADS=['I','II','III','aVR','aVL','aVF','V1','V2','V3','V4','V5','V6']


def model():
    rows=[dict(event_id='st:1',basis_version='b1',row_id='st:1:'+lead,lead=lead,kind='st_depression',
        start_s=0,end_s=180,duration_s=180,mean_st_level_units=-1.25,extreme_st_level_units=-8,
        peak_deviation_units=-12,used_beat_count=99,slope=None,label='本段ST压低') for lead in ['II','III']]
    rows.append(dict(event_id='st:2',basis_version='b2',row_id='st:2:V5',lead='V5',kind='st_elevation',
        start_s=300,end_s=420,duration_s=120,mean_st_level_units=7.1,extreme_st_level_units=14,
        peak_deviation_units=9,slope=None,label='本段ST抬高'))
    evidence=dict(st_units='source_device_units',st_calibration_verified=False,st_measurement_protocol={'measurement_ms':60},
        st_trends={lead:[dict(time_s=30,end_s=60,st_level_units=10+i,reference_units=100,
            deviation_units=-90+i,t_amplitude_units=-30+i,eligible=True),
            dict(time_s=90,end_s=120,st_level_units=999,reference_units=100,deviation_units=899,
                 t_amplitude_units=999,eligible=False),
            dict(time_s=150,end_s=180,st_level_units=20+i,reference_units=100,
                 deviation_units=-80+i,t_amplitude_units=-20+i,eligible=True)] for i,lead in enumerate(LEADS)},
        heart_rate_trend=[dict(time_s=30,hr=60),dict(time_s=90,hr=0),dict(time_s=150,hr=80)],
        st_events=rows,t_events=[dict(event_id='t:1',basis_version='tb',lead='V1',kind='t_wave_inversion',
            start_s=60,end_s=180,duration_s=120,mean_t_amplitude_units=-22.5,
            extreme_t_amplitude_units=-40,peak_deviation_units=-60,label='本段T改变')],
        st_review_notes=[dict(event_id='normal',basis_version='nb',start_s=10,end_s=90,
            label='本段未见明确改变',review_state='reviewed',result_code='no_change',note='<保留医师原文>'),
            dict(event_id='unable',basis_version='ub',start_s=200,end_s=220,label='本段无法判读',
                 review_state='reviewed',result_code='uninterpretable')],
        st_summary=dict(confirmed_lead_event_count=3,confirmed_time_group_count=2,confirmed_union_duration_s=300),
        t_summary=dict(confirmed_lead_event_count=1,confirmed_time_group_count=1,confirmed_union_duration_s=120),
        st_representatives=[dict(role='st_min',lead='II',time_s=80,sample_index=16000,
            waveform=dict(start_s=79.75,duration_s=1,sample_rate_hz=200,stride=1,
                leads={'II':[0,1,4,10,2,-5,-1,0]}))])
    composition=dict(stt_report_use=[dict(event_id='st:1',basis_version='b1',table=True,text=False,strip=False),
        dict(event_id='st:2',basis_version='b2',table=False,text=False,strip=True),
        dict(event_id='t:1',basis_version='tb',table=True,text=False,strip=False),
        dict(event_id='normal',basis_version='nb',table=False,text=True,strip=False),
        dict(event_id='unable',basis_version='ub',table=False,text=True,strip=False)],
        selected_events=[dict(event_id='st:2',basis_version='b2',referenced_in_report=True)])
    return dict(case={'case_id':'mathematical-report','metadata':{'start_time':'2026-01-01 08:00:00'},
                     'technical':{'duration_seconds_raw':600}},report={'status':'draft','composition':composition},evidence=evidence)


def py_docs(m,keys):
    return documents(m['case'],{**m['report'],'section_evidence':m['evidence']},keys)


def node(m,expression):
    script="require('./static/js/report-paper.js');const a=require('./static/js/report-sections.js');const m=JSON.parse(require('fs').readFileSync(0,'utf8'));console.log(JSON.stringify("+expression+"));"
    return json.loads(subprocess.check_output(['node','-e',script],input=json.dumps(m),text=True,cwd=ROOT))


@pytest.mark.parametrize('keys',[['st_trend'],['t_trend'],['st_events'],['st_trend','t_trend','st_events']])
def test_hospital_documents_have_identical_browser_and_native_structure(keys):
    m=model()
    assert node(m,'a.documents(m,'+json.dumps(keys)+')')==py_docs(m,keys)


def test_twelve_leads_share_one_page_and_absolute_ST_is_not_Delta_or_abs():
    m=model();doc=py_docs(m,['st_trend'])[0]
    assert len(py_docs(m,['st_trend']))==1
    assert [r['lead'] for r in doc['trend_rows']]==LEADS
    assert doc['metric']=='st_level_units' and doc['trend_rows'][0]['points'][0]['y']==10
    assert doc['trend_rows'][0]['points'][1]['y']==999
    assert doc['trend_rows'][0]['points'][1]['quality_suspected'] is True
    assert doc['heart_rate'][1]['y'] is None
    m['report']['composition']['stt_trend_metric']='delta'
    delta=py_docs(m,['st_trend'])[0]
    assert delta['metric']=='deviation_units' and delta['trend_rows'][0]['points'][0]['y']==-90
    assert 'ΔST' in delta['paragraphs'][0]
    assert node(m,"a.documents(m,['st_trend'])")==[delta]


def test_report_uses_do_not_change_full_record_statistics_or_force_strip_table_coupling():
    m=model();docs=py_docs(m,['st_events']);st=docs[0]
    assert len(st['table_rows'])==2
    assert all(r['event_id']=='st:1' for r in st['table_rows'])
    assert '导联事件 3，去重时段 2，累计 5 分（300 秒）' in st['paragraphs'][0]
    assert '明细 2 / 3 行' in st['paragraphs'][1]
    assert st['table_rows'][0]['cells'][4]=='-1.25'  # authoritative per-beat mean, not a trend average
    assert st['table_rows'][0]['cells'][-1]=='—'  # a trend slope is never substituted
    assert '180 秒' in st['table_rows'][0]['cells'][3] and '7 秒' not in st['table_rows'][0]['cells'][3]
    assert docs[1]['title']=='T事件明细' and docs[1]['table_rows'][0]['cells'][4]=='-22.5'
    assert docs[-1]['title']=='ST-T复核说明' and any('无法判读' in row for row in docs[-1]['rows'])
    m['report']['composition']['stt_report_use']=[]
    empty=py_docs(m,['st_events'])
    assert len(empty)==1 and empty[0]['table_rows']==[]  # existing strip does not add it back
    assert '导联事件 3' in empty[0]['paragraphs'][0]


def test_legacy_picks_still_print_and_stale_use_cannot_select_a_different_basis():
    m=model();m['report']['composition'].pop('stt_report_use')
    legacy=py_docs(m,['st_events'])
    assert [r['event_id'] for r in legacy[0]['table_rows']]==['st:2']
    m['report']['composition']['stt_report_use']=[dict(event_id='st:1',basis_version='old',table=True,text=True,strip=True)]
    assert py_docs(m,['st_events'])[0]['table_rows']==[]


def test_table_pagination_repeats_headers_without_truncating_event_ranges():
    m=model();first=m['evidence']['st_events'][0]
    m['evidence']['st_events']=[{**first,'row_id':'r:'+str(i),'lead':LEADS[i%12]} for i in range(25)]
    m['report']['composition']['stt_report_use']=[dict(event_id='st:1',basis_version='b1',table=True,text=False,strip=False)]
    docs=py_docs(m,['st_events'])
    assert [len(d['table_rows']) for d in docs]==[24,1]
    assert docs[0]['columns']==docs[1]['columns'] and docs[1]['title'].endswith('（续）')
    assert sum(len(d['table_rows']) for d in docs)==25


def test_browser_paper_preserves_gaps_and_only_draws_source_supplied_representatives():
    m=model();html=node(m,"a.pages(m,['st_trend','t_trend','st_events'])")
    assert html.count('data-stt-lead-count="12"')==2
    assert html.count('data-source-r-sample="16000"')==1
    assert html.count('暂无真实代表搏')==2
    assert '无有效测量' not in html  # each lead has genuine measurements either side of the gap
    assert '&lt;保留医师原文&gt;' in html
    assert 'data-stt-event-id="st:2"' not in html
    assert '平均ST (u)' in html and '最大ΔT (u)' in html
    assert html.count('data-stt-trend-lead="II"')==2
    # Each three-minute trace has two disconnected runs, rather than a zero or a line across the gap.
    first=html.split('data-stt-trend-lead="I"',1)[1].split('</g>',1)[0]
    assert first.split('<path d="',1)[1].split('"',1)[0].count('M')==2


class PathProbe:
    def __init__(self,canvas):self.canvas=canvas
    def moveTo(self,x,y):self.canvas.positions.append((x,y))
    def lineTo(self,x,y):self.canvas.positions.append((x,y))


class CanvasProbe:
    """Records drawing commands without constructing a PDF or touching an export."""
    def __init__(self):self.positions=[];self.texts=[]
    def setFont(self,*a):pass
    def setFillGray(self,*a):pass
    def setStrokeGray(self,*a):pass
    def setLineWidth(self,*a):pass
    def setDash(self,*a):pass
    def drawString(self,x,y,text):self.positions.append((x,y));self.texts.append(text)
    def rect(self,x,y,w,h,**k):self.positions.extend([(x,y),(x+w,y+h)])
    def line(self,x,y,x1,y1):self.positions.extend([(x,y),(x1,y1)])
    def circle(self,x,y,r,**k):self.positions.extend([(x-r,y-r),(x+r,y+r)])
    def beginPath(self):return PathProbe(self)
    def drawPath(self,*a):pass


def test_native_drawing_commands_fit_A4_and_retain_twelve_leads_without_PDF_generation():
    m=model();canvas=CanvasProbe();report={**m['report'],'section_evidence':m['evidence']}
    draws=make_supplement_pages(canvas,'probe',m['case'],report,['st_trend','t_trend','st_events'])
    for draw in draws:draw()
    assert all(math.isfinite(x) and math.isfinite(y) and 0<=x<=A4[0]+.1 and 0<=y<=A4[1]+.1 for x,y in canvas.positions)
    assert sum(t=='II' for t in canvas.texts)>=2
    assert '最深ST电平' in canvas.texts and '暂无真实代表搏' in canvas.texts
    assert '本段无法判读' in ''.join(canvas.texts)


def test_browser_evidence_mirrors_native_per_lead_measurements_and_group_ids():
    protocol=dict(measurement_ms=60,extent='whole',baseline_method='pre_qrs_stable')
    def event(identity,start,end,leads,kind='st_depression',ms=60):
        return dict(event_id=identity,basis_version='依据-'+identity,category='ST',time_s=start,end_s=end,
            diagnosis_status='confirmed',stt_review_state='reviewed',stt_result_code='t_change' if kind=='t_wave_inversion' else kind,
            stt_report_eligibility={'table':True},stt_review_receipt={'leads':leads},label='数学证据 '+identity,
            stt_event_evidence=dict(kind=kind,leads=leads,measurement_protocol={**protocol,'measurement_ms':ms},
                peak_deviation_units=-20,peak_time_s=start+1,continuous_target_s=end-start,
                metrics=[dict(lead=lead,mean_st_level_units=-12,minimum_st_level_units=-20,maximum_st_level_units=-2,
                    minimum_st_sample=int((start+2)*200),maximum_st_sample=int((start+3)*200),reference_sample=int((start+4)*200),
                    reference_st_level_units=-12,used_count=140,mean_t_amplitude_units=-22,
                    extreme_t_amplitude_units=-40,extreme_t_sample=int((start+5)*200),t_used_count=130) for lead in leads]))
    index=dict(events=[event('中文',0,180,['II','III','aVF']),event('overlap',120,300,['V5']),
        event('different-protocol',130,200,['I'],ms=80),event('touching',300,360,['II']),
        event('T',30,90,['V1'],'t_wave_inversion'),
        dict(event_id='normal',basis_version='normal-basis',category='ST',time_s=20,end_s=40,
             diagnosis_status='pending',stt_review_state='reviewed',stt_result_code='no_change',
             stt_report_group='ST_NOTE',note='医生原文')],rows=[],duration_s=0)
    st=dict(analysis={'trends':{'leads':{'II':[dict(time_s=30,eligible=False,st_level_units=100,
        reference_units=1,deviation_units=99,t_amplitude_units=2,t_reference_units=3)]}}})
    payload=dict(index=index,st=st)
    actual=node(payload,'a.evidence(m.index,m.st)');expected=section_evidence(index,st)
    for key in ('st_events','t_events','st_summary','t_summary','st_review_notes','st_trends','st_measurement_protocol','units'):
        assert actual[key]==expected[key],key
    rows=st_report_events(index)
    assert actual['st_summary']==st_summary(rows)
    assert actual['st_summary']['confirmed_time_group_count']==3
    assert actual['st_summary']['confirmed_lead_event_count']==6
    assert len(actual['st_summary']['groups'][0]['child_event_ids'])==4
    assert actual['st_summary']['confirmed_union_duration_s']==360


def test_reference_near_mean_is_not_relabelled_as_Delta_reference_or_a_synthetic_average():
    m=model();m['evidence']['st_representatives'].append(dict(role='reference',label='范围均值附近实际参考搏',
        metric='st_level',lead='II',time_s=20,waveform=None,reference_method='nearest_valid_beat_to_event_mean_st_level'))
    assert py_docs(m,['st_trend'])[0]['representatives'][0]['label']=='范围均值附近实际参考搏'
    m['report']['composition']['stt_trend_metric']='delta'
    doc=py_docs(m,['st_trend'])[0]
    assert doc['representatives'][0]['waveform'] is None and doc['representatives'][0]['label']=='ΔST参考搏'
    assert node(m,"a.documents(m,['st_trend'])")==[doc]


def test_ST_review_narrative_has_its_own_heading_without_rewriting_physician_conclusion():
    report=dict(conclusion='医生最终结论原文',composition={'diagnosis_blocks':[
        dict(key='ST:review:normal',text='本段未见明确动态ST-T改变'),
        dict(key='other',text='原有图条说明')]})
    expected='医生最终结论原文\n图条说明（不替代诊断）：原有图条说明\nST-T复核记录：本段未见明确动态ST-T改变'
    assert conclusion_text(report)==expected
    assert node(report,'ECGReportPaper.conclusionText(m)')==expected
