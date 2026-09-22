"""Optimizations must preserve every density bin, selected beat and waveform value."""
import json
import math
import random
import struct
import subprocess
from pathlib import Path

import pytest

from ecg_core.overview import density
from ecg_core.waveform import ALL_LEADS

ROOT = Path(__file__).resolve().parents[1]


def scalar_density(raw, samples, lead, gate, fixed):
    """Pre-optimization scalar contract, retained only as a differential oracle."""
    positions = [s for s in samples if 200 <= s < len(raw)-200]
    def read(s):
        a, b, *chest = raw[s]
        return dict(zip(ALL_LEADS, [a,b,b-a,-(a+b)/2,a-b/2,b-a/2,*chest]))[lead]
    def baseline(s): return sum(read(s+i) for i in range(-40,-20,2))/10
    values = sorted(abs(read(s+i)-baseline(s)) for s in positions[::max(1,math.ceil(len(positions)/1000))] for i in range(-200,200,8))
    limit = round(fixed if fixed is not None else max(100,values[int(len(values)*.995)]*1.15 if values else 100),3)
    bins, selected, clipped = [0]*25600, [], 0
    for s in positions:
        zero, matched = baseline(s), False
        for x, offset in enumerate(range(-200,200,2)):
            amp = read(s+offset)-zero
            y = math.floor((limit-amp)/(2*limit)*128)
            if y < 0 or y >= 128: clipped+=1; continue
            bins[y*200+x]+=1
            if gate and gate[0]<=offset/200<=gate[1] and gate[2]<=amp<=gate[3]: matched=True
        if matched: selected.append(s)
    return bins, selected, clipped, limit


@pytest.mark.parametrize('lead',ALL_LEADS)
@pytest.mark.parametrize('fixed',[None,100])
def test_vector_density_matches_scalar_for_all_leads_clipping_and_gates(tmp_path,lead,fixed):
    rng=random.Random(923)
    raw=[tuple(rng.randrange(-32768,32768) for _ in range(8)) for _ in range(3000)]
    path=tmp_path/'wave.bin';path.write_bytes(b''.join(struct.pack('<8h',*row) for row in raw))
    samples=[0,199,200,401,905,1698,2799,2800,2999];gate=(-.23,.36,-2400,840)
    expected=scalar_density(raw,samples,lead,gate,fixed)
    actual=density(path,samples,lead,gate,fixed)
    assert (actual['bins'],actual['sample_indices'],actual['clipped_points'],actual['amplitude_limit'])==expected
    assert sum(actual['bins'])+actual['clipped_points']==actual['included']*200
    assert actual['population_samples']==samples and actual['skipped_edges']==4


def test_empty_density_and_chunk_boundary_are_complete(tmp_path):
    path=tmp_path/'wave.bin';path.write_bytes(struct.pack('<8h',*([0]*8))*6000)
    empty=density(path,[])
    assert empty['included']==0 and sum(empty['bins'])==0
    samples=list(range(200,5201))
    actual=density(path,samples,'II',(-1,1,0,0))
    assert actual['sample_indices']==samples
    assert sum(actual['bins'])==len(samples)*200 and max(actual['bins'])==len(samples)


def test_batch_waveforms_match_single_requests_and_materialize_once(client,monkeypatch):
    import app as server
    case=client.get('/api/cases').json['items'][0]['case_id'];base=f'/api/cases/{case}'
    ranges=[dict(start=0,end=2.4),dict(start=20.125,end=23.325),dict(start=200,end=380)]
    expected=[client.get(base+'/event-waveform',query_string={**r,'analysis':'edited','leads':'II,III,V1','max_points':1200}).json for r in ranges]
    original=server.EditedRecords;calls=[]
    def counted(*args): calls.append(1);return original(*args)
    monkeypatch.setattr(server,'EditedRecords',counted)
    actual=client.post(base+'/event-waveforms?analysis=edited',json=dict(ranges=ranges,leads=['II','III','V1'],max_points=1200))
    assert actual.status_code==200 and actual.json['items']==expected
    assert len(calls)==1


@pytest.mark.parametrize('payload',[
    {},{'ranges':[]},{'ranges':[{}]}, {'ranges':[dict(start=0,end=3)]*33},
    {'ranges':[dict(start=-1,end=3)]},{'ranges':[dict(start=True,end=3)]},
    {'ranges':[dict(start=3,end=2)]},{'ranges':[dict(start=0,end=3)],'leads':['BAD']},
    {'ranges':[dict(start=0,end=3)],'leads':['II','II']},
    {'ranges':[dict(start=0,end=3)],'max_points':9000},
])
def test_batch_waveforms_validate_before_reading(client,payload):
    case=client.get('/api/cases').json['items'][0]['case_id']
    assert client.post(f'/api/cases/{case}/event-waveforms',json=payload).status_code==400


def test_thumbnail_queue_batches_deduplicates_retries_and_bounds_concurrency():
    script=r"""
const {create}=require('./static/js/waveform-loader.js');
(async()=>{
 let running=0,max=0,calls=[],fail=true;
 const loader=create(async(group,inputs)=>{running++;max=Math.max(max,running);calls.push([group,inputs]);await new Promise(r=>setTimeout(r,2));running--;if(group==='bad'&&fail){fail=false;throw Error('retry')}return inputs.map(x=>group+':'+x)}, {batchSize:3,concurrency:2,cacheSize:5});
 const jobs=Array.from({length:9},(_,i)=>loader.get('a'+i,'a',i));
 const duplicate=loader.get('a0','a',0);if(duplicate!==jobs[0])throw Error('in-flight duplicate');
 const values=await Promise.all(jobs),before=calls.length;
 await loader.get('a8','a',8);const cached=calls.length===before;
 let failed=false;try{await loader.get('bad','bad',1)}catch(e){failed=true}
 await new Promise(r=>setTimeout(r,0));const retry=await loader.get('bad','bad',1);
 loader.clear();await loader.get('a8','a',8);
 console.log(JSON.stringify({max,values,cached,failed,retry,batches:calls.slice(0,3).map(x=>x[1].length),reloaded:calls.length>before+2}));
})().catch(e=>{console.error(e);process.exit(1)});
"""
    result=json.loads(subprocess.check_output(['node','-e',script],cwd=ROOT,text=True))
    assert result==dict(max=2,values=[f'a:{i}' for i in range(9)],cached=True,failed=True,retry='bad:1',batches=[3,3,3],reloaded=True)


def test_static_demo_includes_batch_loader_before_ui():
    html=(ROOT/'templates/index.html').read_text()
    assert html.index("js/waveform-loader.js")<html.index("js/clinical-ui.js")
    assert "action==='event-waveforms'" in (ROOT/'demo/static/js/demo-api.js').read_text()


def test_thumbnail_queue_does_not_replace_report_strip_map():
    script=r"""
const fs=require('fs'),vm=require('vm'),source=fs.readFileSync('static/js/clinical-ui.js','utf8');
// Exercise the actual cache declarations and report reader without mounting DOM.
const setup=source.slice(source.indexOf('  const reportWaveCache='),source.indexOf('  let reportCase='));
const reader=source.slice(source.indexOf('  async function reportStrip('),source.indexOf('  async function selectedReportWaves('));
let reads=0;
vm.runInNewContext(setup+reader+`(async()=>{
 const event={event_id:'e1',basis_version:'v1',label:'candidate'},selection={leads:['II'],duration_s:7};
 const [first,second]=await Promise.all([reportStrip(event,selection),reportStrip(event,selection)]);
 const revised=await reportStrip({...event,basis_version:'v2'},selection);
 console.log(JSON.stringify({first,second,revised,reads:reads()}));
})().catch(e=>{console.error(e);process.exit(1)})`,{
 ECGWaveformLoader:require('./static/js/waveform-loader.js'),ECGReportEngine:{settings:x=>x},state:{caseId:'test'},
 endpoint:async()=>({sequence:++reads}),reads:()=>reads,console,process,setTimeout,Map
});
"""
    result=json.loads(subprocess.check_output(['node','-e',script],cwd=ROOT,text=True))
    assert result['reads']==2
    assert result['first']==result['second']==dict(sequence=1,caption='candidate')
    assert result['revised']==dict(sequence=2,caption='candidate')


def test_readonly_allows_new_computations_but_keeps_write_guard(data_root,tmp_path,monkeypatch):
    from app import create_app
    monkeypatch.setenv('ECG_DEMO_READONLY','true')
    client=create_app(data_root=data_root,db_path=tmp_path/'compute.db',testing=True).test_client()
    case=client.get('/api/cases').json['items'][0]['case_id'];base=f'/api/cases/{case}'
    assert client.post(base+'/event-waveforms',json={'ranges':[dict(start=0,end=3)]}).status_code==200
    assert client.post(base+'/waveform-density?class_code=N&lead=II',json={}).status_code==200
    assert client.post(base+'/annotations',json={}).status_code==403
