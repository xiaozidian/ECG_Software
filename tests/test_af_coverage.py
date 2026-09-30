"""Production coverage presentation: abstention is not a negative diagnosis."""
import json
import subprocess
from pathlib import Path

import pytest

ROOT=Path(__file__).parents[1]


def node(code):
    preamble="const C=require('./static/js/af-coverage.js'), E=require('./static/js/overview-engine.js');"
    return json.loads(subprocess.check_output(['node','-e',preamble+code],cwd=ROOT,text=True))


def test_actual_screen_duration_not_window_count_and_merging():
    result=node("""
const r=E.screenAFResult([],95);const before=JSON.stringify(r);
console.log(JSON.stringify({s:C.summarize(r,0,95),unchanged:before===JSON.stringify(r)}));
""")
    s=result['s']
    assert result['unchanged']
    assert (s['assessed_s'],s['skipped_s'],s['coverage_pct'])==(0,95,0)
    assert s['gaps']==[
        dict(start_s=0,end_s=90,reason='insufficient_intervals',windows=3),
        dict(start_s=90,end_s=95,reason='incomplete_window',windows=1)]


def test_mixed_coverage_nonzero_absolute_scope():
    result=node("""
const rows=Array.from({length:120},(_,i)=>({sample_index:120000+i*160,rr_ms:i?800:0,class_code:i>=38&&i<75?'X':'N'}));
console.log(JSON.stringify(C.summarize(E.screenAFResult(rows,695,600,695),600,695)));
""")
    assert result['start_s']==600 and result['end_s']==695
    assert result['assessed_s']==60 and result['skipped_s']==35
    assert result['coverage_pct']==pytest.approx(60/95*100)
    assert result['candidate_s']==0
    assert [g['start_s'] for g in result['gaps']]==[630,690]


@pytest.mark.parametrize('mutation',[
    'r.windows=[]', 'r.windows[0].start_s=1', 'r.windows[1].start_s=29',
    'r.windows[0].end_s=31', 'r.windows[1].end_s=59',
    "r.windows[0].reason='unknown'",'r.windows[0].candidate=true',
    'r.windows[0].evaluated=1','r.skipped_windows=1',
    'r.evaluated_windows=1','r.windows[0].end_s=NaN',
    'r.windows[0].evaluated=true',
])
def test_incomplete_or_contradictory_coverage_rejected(mutation):
    assert node("const r=E.screenAFResult([],60);"+mutation+";try{C.summarize(r,0,60);console.log(false)}catch(e){console.log(true)}")


def test_large_gap_list_has_bounded_pages_and_does_not_merge_across_reasons():
    result=node("""
const r=E.screenAFResult([],86400);r.windows.forEach((w,i)=>{w.reason=i%2?'low_quality':'insufficient_intervals'});
const s=C.summarize(r,0,86400);console.log(JSON.stringify({count:s.gaps.length,first:C.page(s),last:C.page(s,9999)}));
""")
    assert result['count']==2880
    assert len(result['first']['items'])==len(result['last']['items'])==20
    assert result['last']['pages']==144 and result['last']['index']==143
    assert result['last']['items'][-1]['end_s']==86400


@pytest.mark.parametrize('scenario',[
    'readonly','empty','short','stale-case','stale-revision','stale-rows',
    'stale-token','stale-source','cancel','gap','gap-stale','gap-invalid',
    'screen-zero','render-pages','load-failure','load-success',
])
def test_shipped_ui_coverage_lifecycle(scenario):
    subprocess.run(['node',str(ROOT/'tests/browser_af_coverage.cjs'),scenario],cwd=ROOT,check=True)


def test_af_report_disclaimer_matches_web_and_pdf_even_without_episodes():
    from ecg_core.report_sections_pdf import documents
    py=documents({'metadata':{}},{'section_evidence':{'af':[]}},['af'])[0]
    js=node("require('./static/js/report-sections.js');console.log(JSON.stringify(global.ECGReportSections.documents({evidence:{af:[]},case:{metadata:{}}},['af'])[0]));")
    assert js['paragraphs']==py['paragraphs']
    assert any('不证明全程已评估' in p and '未评估时段须回看原始波形' in p for p in py['paragraphs'])
    assert '不以 0 代替缺失数据' in py['paragraphs'][0]
