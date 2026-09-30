import json
import subprocess
import re
from types import SimpleNamespace
import pytest
from ecg_core.clinical_analysis import build_index, query_index
from ecg_core.clinical_analysis import validate_report
from ecg_core.report_sections import rr_derivatives, evidence, validate_pages, selected_pages
from ecg_core.storage import normalize_report_composition
from ecg_core.report_pdf import build_report_pdf


def feed():
    rows=[];sample=0
    for i in range(12000):
        rr=800+(i%7)*5;sample+=round(rr/5)
        rows.append(dict(id=f's:{sample}',sample_index=sample,time_s=sample/200,class_code='S' if i%17==0 else 'N',rr_ms=rr,hr=60000/rr,source_group=1,source_sample=sample))
    return SimpleNamespace(beats=rows,markers=[],duration=sample/200+1,document={'settings':dict(nn_min=300,nn_max=2000,pause=2.5,tachy=120,brady=50)})


def test_clock_hours_and_half_open_filter_keep_histogram():
    index=build_index(feed());index['start_time']='2026-09-28 23:37:00'
    all_data=query_index(index,{'category':'S','mode':'single'})
    assert all_data['time_bins'][0]['end_s']==1380
    assert all_data['time_bins'][1]['label']=='09-29 00:00'
    end=all_data['time_bins'][1]['end_s']
    filtered=query_index(index,{'category':'S','mode':'single','time_start':1380,'time_end':end})
    assert filtered['time_bins']==all_data['time_bins']
    assert filtered['total']==all_data['time_bins'][1]['count']
    assert all(1380<=e['time_s']<end for e in filtered['items'])
    params={'category':'S','mode':'single','time_start':1380,'time_end':end}
    js="const a=require('./static/js/clinical-analysis.js');let p=JSON.parse(require('fs').readFileSync(0,'utf8'));console.log(JSON.stringify(a.queryIndex(p.index,p.params)))"
    result=json.loads(subprocess.check_output(['node','-e',js],input=json.dumps(dict(index=index,params=params)),text=True))
    assert result['time_bins']==filtered['time_bins']
    assert result['items']==filtered['items']
    with pytest.raises(ValueError):query_index(index,dict(time_start=-1,time_end=10))
    with pytest.raises(ValueError):query_index(index,dict(time_start=0,time_end='NaN'))


def test_rr_derivative_formulas_and_browser_parity():
    rows=[];sample=0
    for block in range(6):
        intervals=[800]*10+[500,1100]+[760,770,780,790,800,810,820,830,840,850,860,870,880,890,900]+[800]*30
        for j,rr in enumerate(intervals):
            sample+=round(rr/5);rows.append(dict(sample_index=sample,time_s=sample/200,rr_ms=rr,class_code='V' if j==10 else 'N'))
    data=rr_derivatives(rows)
    assert data['hrt']['eligible_pvc']==6
    assert data['hrt']['to_pct']==pytest.approx(-4.375)
    assert data['hrt']['ts_ms_per_rr']==10
    js="const a=require('./static/js/report-sections.js');const r=JSON.parse(require('fs').readFileSync(0,'utf8'));console.log(JSON.stringify(a.derivatives(r)))"
    other=json.loads(subprocess.check_output(['node','-e',js],input=json.dumps(rows),text=True))
    assert other==data
    excluded=rr_derivatives(rows,[(0,sample/200+1)])
    assert excluded['hrt']['to_pct'] is None and excluded['dc']['dc_ms'] is None


def test_page_selection_migration_gates_and_pdf():
    assert selected_pages({})==['summary','hourly','event_strips']
    composition=normalize_report_composition(dict(page_selection_version=1,included_pages=[]))
    assert composition['included_pages']==[]
    with pytest.raises(ValueError,match='至少'):validate_pages(composition)
    with pytest.raises(ValueError,match='高频'):validate_pages(dict(page_selection_version=1,included_pages=['vlp']))
    case=dict(case_id='report-workspace-test',metadata={},summary={})
    for key in ['cover','summary','hourly','event_strips','scatter','pacing','af','hrt','dc','st_trend','t_trend','st_events']:
        report=dict(status='draft',composition=dict(page_selection_version=1,included_pages=[key]),section_evidence=evidence(build_index(feed())),selected_waveforms=[])
        pdf=build_report_pdf(case,{},report).getvalue()
        assert len(re.findall(rb'/Type\s*/Page\b',pdf))==1,key


def test_print_mode_preserves_curation_and_wave_context():
    script="""
require('./static/js/report-workspace.js');
global.formatElapsed=s=>'D1 '+s.toFixed(3);
const a=global.ECGReportWorkspace;
const selected=[{event_id:'rr',caption:'edited RR',leads:['II'],manual_start_s:3},
                {event_id:'nn',caption:'edited NN',leads:['V1'],manual_start_s:9}];
let c={fast_slow_mode:'both',selected_events:selected};
for(const mode of ['rr','both','nn','both'])c=a.withRateMode(c,mode);
console.log(JSON.stringify({c,same:c.selected_events===selected,
  excluded:a.printEligible({category:'fastest',subtype:'NN'},'rr'),
  restored:a.printEligible({category:'fastest',subtype:'NN'},'both'),
  html:a.waveContext({waveform:{start_s:10,duration_s:7.125},strip:{visible_beat_count:4}})}));
"""
    result=json.loads(subprocess.check_output(['node','-e',script],text=True))
    assert result['same'] and result['c']['selected_events'][1]['caption']=='edited NN'
    assert result['excluded'] is False and result['restored'] is True
    for text in ['7.125 秒','4 搏','不足 5 搏','电压未校准','7.13 s','rw-wave-scroll']:
        assert text in result['html']


@pytest.mark.parametrize('mode',['rr','nn','both'])
def test_print_filter_does_not_block_approval_of_retained_picks(mode):
    review={'steps':{'edit':{'status':'done'},'stt':{'status':'done'}}}
    index=build_index(feed(),review=review)
    picks=[next(e for e in index['events'] if e['category']=='fastest' and e['subtype']==s) for s in ('RR','NN')]
    composition=dict(fast_slow_mode=mode,category_reviews=index['basis_versions'],selected_events=[
        dict(event_id=e['event_id'],basis_version=e['basis_version']) for e in picks])
    result=validate_report(index,composition,review,True)
    assert [r['subtype'] for r in result]==['RR','NN']
    script="require('./static/js/report-engine.js');const a=require('./static/js/clinical-analysis.js');const x=JSON.parse(require('fs').readFileSync(0,'utf8'));console.log(JSON.stringify(a.validateReport(x.i,x.c,x.r,true)))"
    actual=json.loads(subprocess.check_output(['node','-e',script],input=json.dumps(dict(i=index,c=composition,r=review)),text=True))
    assert actual==result
    composition['selected_events'][1]['basis_version']='stale'
    with pytest.raises(ValueError,match='失效'):validate_report(index,composition,review,True)
