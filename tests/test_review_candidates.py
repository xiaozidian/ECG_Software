"""Mathematical fixtures only: exact RR, candidate lifecycle, full raw envelope."""
import copy
import json
from types import SimpleNamespace
import pytest
from ecg_core.clinical_analysis import build_index, query_index
from ecg_core.review_candidates import prepare_candidate, augment_index, rr_distribution, pause_edges
from ecg_core.storage import Storage
from ecg_core.waveform import read_waveform_overview
from test_analysis_provenance import synthetic_case, synthetic_app


def fixture_index():
    rows=[]; sample=100
    for i,rr in enumerate([0,800,2500,3000,4000,4500,800,800,800,800,800]):
        sample+=rr//5
        rows.append(dict(id=f'math:{i}',sample_index=sample,class_code='N',rr_ms=rr,hr=60000/rr if rr else None))
    feed=SimpleNamespace(beats=rows,markers=[],duration=sample/200+2,
        document={'settings':dict(nn_min=300,nn_max=2000,pause=2.5,tachy=120,brady=50)})
    return build_index(feed)


def identity(): return dict(case_id='math-local',analysis_basis='a'*64,analysis_revision=0,beat_revision=0)


def test_mutually_exclusive_boundaries_do_not_change_detector_threshold():
    index=fixture_index(); before=copy.deepcopy(index)
    d=rr_distribution(index['rows'],index['duration_s'])
    assert [b['count'] for b in d['bins']]==[1,1,2]
    assert sum(b['count'] for b in d['bins'])==4
    assert query_index(index,{'category':'pause'})['total']==3  # strict >2500 unchanged
    assert index==before
    custom=rr_distribution(index['rows'],index['duration_s'],[3000,4000,5000])
    assert [b['count'] for b in custom['bins']]==[1,2,0]
    index['rows'][3]['class_code']='X'
    assert [b['count'] for b in rr_distribution(index['rows'],index['duration_s'])['bins']]==[1,0,1]


@pytest.mark.parametrize('value',[[3000,2500,4000],[True,3000,4000],[2500,3000,float('nan')],[2500,3000],[-1,3000,4000]])
def test_bad_statistical_edges_rejected(value):
    with pytest.raises(ValueError): pause_edges(value)


def test_candidate_is_exact_deduplicated_withdrawable_and_source_bound(tmp_path):
    index=fixture_index(); original=copy.deepcopy(index); scope=identity()
    row=index['rows'][4]; request=dict(kind='rr',sample_index=row['sample_index'],rr_ms=row['rr_ms'],population={'origin':'overview-histogram','rr_bounds_ms':[4000,5000]})
    checked=prepare_candidate(index,scope,request)
    assert checked['payload']['rr_start_sample']==index['rows'][3]['sample_index']
    assert checked['payload']['rr_start_id']==index['rows'][3]['id']
    assert checked['payload']['settings']['leads']==['II','V1','V5']
    db=Storage(tmp_path/'local.db'); guard=lambda connection:None
    a=db.save_candidate('math-local',checked,'test',guard)
    b=db.save_candidate('math-local',checked,'test',guard)
    assert a['id']==b['id'] and len(db.list_candidates('math-local'))==1
    assert db.get_review('math-local')['revision']==0
    assert index==original
    augmented=augment_index(copy.deepcopy(index),db.list_candidates('math-local'),scope)
    picked=[e for e in augmented['events'] if e['category']=='rr_candidate'];assert len(picked)==1
    assert picked[0]['evidence_only'] and picked[0]['candidate_context']['rr_ms']==4000
    assert query_index(augmented,{'category':'rr_candidate'})['total']==1
    db.set_candidate_status('math-local',a['id'],'withdrawn','test',guard)
    assert not any(e['category']=='rr_candidate' for e in augment_index(copy.deepcopy(index),db.list_candidates('math-local'),scope)['events'])
    db.set_candidate_status('math-local',a['id'],'active','test',guard)
    assert not any(e['category']=='rr_candidate' for e in augment_index(copy.deepcopy(index),db.list_candidates('math-local'),{**scope,'beat_revision':1})['events'])
    with pytest.raises(Exception): prepare_candidate(index,scope,{**request,'population':{'rr_bounds_ms':[2500,3000]}})
    index['rows'][3]['class_code']='X'
    with pytest.raises(ValueError): prepare_candidate(index,scope,request)


def test_candidate_transaction_rolls_back_when_basis_changes(tmp_path):
    db=Storage(tmp_path/'local.db'); checked=prepare_candidate(fixture_index(),identity(),dict(kind='rr',sample_index=fixture_index()['rows'][4]['sample_index']))
    calls=[]
    def guard(connection):
        calls.append(1)
        if len(calls)>1:raise ValueError('synthetic concurrent basis change')
    with pytest.raises(ValueError): db.save_candidate('math-local',checked,'test',guard)
    assert db.list_candidates('math-local')==[]


def test_full_day_envelope_keeps_last_sample_and_negative_qs_without_big_copy(tmp_path):
    import struct
    path=tmp_path/'sparse-math.DATA'; samples=86400*200
    with path.open('wb') as stream:
        stream.truncate(samples*16)  # sparse mathematical fixture, no patient data
        stream.seek((samples-1)*16);stream.write(struct.pack('<8h',0,-2000,1500,0,0,0,-1200,0))
    before=path.stat()
    result=read_waveform_overview(path,['II','V1','V5'],1000)
    assert result['total_duration_s']==86400 and result['bin_edges_s'][-1]==86400
    assert len(result['leads']['II'])==1000
    assert result['leads']['II'][-1]==[-2000,0]
    assert result['leads']['V1'][-1]==[0,1500]
    assert result['leads']['V5'][-1]==[-1200,0]
    assert result['calibration_verified'] is False
    assert path.stat().st_mtime_ns==before.st_mtime_ns


def test_routes_keep_picks_separate_from_beats_and_report_and_export_exact_range(synthetic_app, synthetic_case):
    from hashlib import sha256
    import subprocess
    _,cid,paths=synthetic_case;client=synthetic_app.test_client();base=f'/api/cases/{cid}'
    hashes={k:sha256(p.read_bytes()).hexdigest() for k,p in paths.items()}
    def ok(response):
        assert response.status_code in (200,201),response.json
        return response.json
    current=ok(client.get(base+'/evidence-candidates'))
    scope={k:current[k] for k in ('case_id','analysis_basis','analysis_revision','beat_revision')}
    payload={**scope,'kind':'rr','sample_index':2000,'rr_ms':1000,'settings':{'leads':['II','V1','V5'],'duration_s':7}}
    report=ok(client.get(base+'/report'))
    first=ok(client.post(base+'/evidence-candidates',json=payload))['item']
    assert ok(client.post(base+'/evidence-candidates',json=payload))['item']['id']==first['id']
    assert ok(client.get(base+'/report'))==report  # no automatic inclusion/version/diagnosis edit
    assert ok(client.get(base+'/evidence-candidates'))['analysis_revision']==scope['analysis_revision']
    candidates=ok(client.get(base+'/report-events?category=rr_candidate'))
    assert candidates['total']==1
    item=candidates['items'][0]
    wave=ok(client.get(base+'/report-strip',query_string={'event_id':item['event_id'],'basis_version':item['basis_version']}))
    assert set(wave['waveform']['leads'])=={'II','V1','V5'}
    assert wave['waveform']['start_s']<=first['payload']['start_s']
    assert wave['waveform']['start_s']+wave['waveform']['duration_s']>first['payload']['end_s']
    assert client.post(base+'/evidence-candidates',json={**payload,'case_id':'other'}).status_code==409
    assert client.post(base+'/evidence-candidates',json={**payload,'beat_revision':999}).status_code==409
    assert client.post(base+'/evidence-candidates',json={**payload,'rr_ms':1100}).status_code==409
    ok(client.patch(base+'/evidence-candidates',json={**scope,'id':first['id'],'status':'withdrawn'}))
    assert ok(client.get(base+'/report-events?category=rr_candidate'))['total']==0
    ok(client.patch(base+'/evidence-candidates',json={**scope,'id':first['id'],'status':'active'}))
    strip={**scope,'kind':'strip','caption':'数学留图回归','settings':{'range_start_s':10,'range_end_s':20,'duration_s':10,'leads':['II','V1','V5']}}
    retained=ok(client.post(base+'/evidence-candidates',json=strip))['item']
    assert ok(client.post(base+'/evidence-candidates',json=strip))['item']['id']==retained['id']
    events=ok(client.get(base+'/report-events?category=other'))['items']
    event=next(e for e in events if e.get('local_candidate_id')==retained['id'])
    selection={'event_id':event['event_id'],'basis_version':event['basis_version'],'caption':'数学留图回归',**event['retained_settings']}
    saved=ok(client.put(base+'/report',json={'expected_version':report['version'],'expected_review_revision':scope['analysis_revision'],
        'status':'draft','conclusion':'数学数据工程验收，不构成诊断','composition':{'included_pages':['summary','event_strips'],'page_selection_version':1,'pause_edges_ms':[2500,3000,4000],'selected_events':[selection]}}))
    assert saved['composition']['selected_events'][0]['range_end_s']==20
    response=client.get(base+'/report.pdf');assert response.status_code==200
    text=subprocess.check_output(['pdftotext','-','-'],input=response.data).decode('utf-8')
    assert '数学留图回归' in text and '互斥统计' in text
    assert {k:sha256(p.read_bytes()).hexdigest() for k,p in paths.items()}==hashes
    envelope=ok(client.get(base+'/waveform-overview?bins=50'))
    assert envelope['total_duration_s']==90 and len(envelope['leads']['II'])==50
    # Saved-work backups recognize and validate the new local evidence ledger.
    from ecg_core.workspace_backup import _check_database
    assert _check_database(synthetic_app.extensions['storage'].path)['tables']['evidence_candidates']==2


def test_statistical_bins_and_web_parity_are_exact_and_configurable():
    import subprocess
    index=fixture_index()
    expected=rr_distribution(index['rows'],index['duration_s'],[2500,3000,4000])
    script="const q=require('./static/js/rr-quality.js'),p=JSON.parse(require('fs').readFileSync(0,'utf8'));console.log(JSON.stringify(q.rrDistribution(p.rows,p.duration_s,[2500,3000,4000])));"
    actual=json.loads(subprocess.check_output(['node','-e',script],input=json.dumps(index),text=True))
    assert actual==expected
    assert query_index(index,{'category':'pause','pause_band':'b0'})['total']==0
    assert query_index(index,{'category':'pause','pause_band':'b1'})['total']==1
    assert query_index(index,{'category':'pause','pause_band':'b2'})['total']==2


def test_candidate_writes_keep_live_reads_without_invalidating_reviewed_waveform():
    import subprocess
    script=r"""
const fs=require('fs'),vm=require('vm'),assert=require('node:assert/strict');
let invalidated=0,inspections=0,cleared=0;
const state={caseId:'math',caseRequestId:3,currentPage:'review',workspaceEpoch:'math'};
const context=vm.createContext({state,ECGReadRequests:{clear(){cleared++;}},ecgChartInspection:{invalidate(){inspections++;}},overviewWorkbench:{invalidateAfterWrite(){invalidated++;}},fetch:async()=>({ok:true,headers:{get:()=> 'application/json'},json:async()=>({ok:true})})});
const source=fs.readFileSync('static/js/app.js','utf8');
vm.runInContext(source.slice(source.indexOf('async function api('),source.indexOf('\nfunction toast(')),context);
(async()=>{await context.api('/api/cases/math/evidence-candidates',{method:'POST',body:'{}'});await context.api('/api/cases/math/evidence-candidates',{method:'PATCH',body:'{}'});assert.equal(invalidated,0);assert.equal(inspections,0);assert.equal(cleared,0);await context.api('/api/cases/math/beat-editor',{method:'PUT',body:'{}'});assert.equal(invalidated,1);assert.equal(inspections,2);console.log('exact reviewed wave survives evidence-only writes');})().catch(e=>{console.error(e);process.exitCode=1});
"""
    subprocess.run(['node','-e',script],check=True,timeout=10)
