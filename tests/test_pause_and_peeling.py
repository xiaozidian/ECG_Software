"""Long-RR report contracts and reversible morphology partitions, not diagnoses."""
import json
import math
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from ecg_core.clinical_analysis import build_index, query_index
from ecg_core.overview import density_samples, density
from ecg_core.report_layout import resolve_strip, report_statistics
from ecg_core.storage import Storage

ROOT = Path(__file__).resolve().parents[1]


def node(source, payload=None):
    return json.loads(subprocess.check_output(['node', '-e', source], cwd=ROOT, input=json.dumps(payload).encode()))


def pause_feed():
    rows=[]
    sample=0
    for i, rr in enumerate([0, 1000, 2500, 2505, 3000, 3005, 11000, 1000, 1000, 1000, 1000]):
        sample+=rr//5
        rows.append(dict(id=f's:{sample}',sample_index=sample,class_code='N',rr_ms=rr,hr=60000/rr if rr else None))
    return SimpleNamespace(beats=rows,markers=[],duration=sample/200+2,document={'settings':dict(nn_min=300,nn_max=2000,pause=5,tachy=120,brady=50)})


def test_pause_strict_boundaries_fixed_denominator_and_filter_before_pagination():
    index=build_index(pause_feed())
    all_rows=query_index(index,{'category':'pause'})
    assert all_rows['pause_counts']=={'all':4,'over3':2,'2.5to3':2}
    assert [r['rr_ms'] for r in all_rows['items']]==[2505,3000,3005,11000]
    page=query_index(index,{'category':'pause','pause_band':'over3','limit':1,'offset':1})
    assert page['total']==2 and page['items'][0]['rr_ms']==11000
    assert page['category_counts']['pause']==4
    saved=all_rows['items'][0]
    assert query_index(index,{'category':'pause','pause_band':'over3','ids':saved['event_id']})['items']==[saved]
    with pytest.raises(ValueError):query_index(index,{'pause_band':'invalid'})
    feed=pause_feed();feed.beats[3]['class_code']='X'
    assert query_index(build_index(feed),{'category':'pause'})['total']==3


def test_long_pause_strip_includes_both_r_peaks_and_five_beats():
    index=build_index(pause_feed());event=next(e for e in index['events'] if e['category']=='pause' and e['rr_ms']==11000)
    spec=resolve_strip(index,event)
    assert spec['start_s']<event['time_s']-11 and spec['end_s']>event['time_s']
    assert spec['visible_beat_count']>=5 and spec['actual_duration_s']>11
    assert '完整 RR' in spec['warning']
    stats=report_statistics(index,None,pause_feed().document['settings'])
    assert stats['summary']['pause']==4 and stats['summary']['pause_over3']==2
    assert sum(x['pause_over3'] for x in stats['hourly'])==2


def test_pause_python_demo_index_query_strip_and_statistics_parity():
    feed=pause_feed();index=build_index(feed)
    params=[dict(category='pause',pause_band=b,offset=o,limit=1) for b in ('all','over3','2.5to3') for o in (0,1,3)]
    result=node("const A=require('./static/js/clinical-analysis.js'),R=require('./static/js/report-engine.js'),p=JSON.parse(require('fs').readFileSync(0,'utf8')),i=A.buildIndex(p.feed),e=i.events.find(e=>e.category==='pause'&&e.rr_ms===11000);console.log(JSON.stringify({index:i,queries:p.params.map(x=>A.queryIndex(i,x)),strip:R.resolve(i,e),stats:R.statistics(i,null,p.feed.document.settings)}))",dict(feed=vars(feed),params=params))
    assert result['index']==index
    assert result['queries']==json.loads(json.dumps([query_index(index,p) for p in params]))
    event=next(e for e in index['events'] if e['category']=='pause' and e['rr_ms']==11000)
    assert result['strip']==resolve_strip(index,event)
    assert result['stats']==report_statistics(index,None,feed.document['settings'])


def test_groups_conserve_full_population_disjoint_append_restore_and_undo():
    result=node("const {Groups}=require('./static/js/morphology-groups.js'),g=new Groups([1,2,3,4,5,6]);g.move(6,[1,2]);g.move(7,[3]);g.move(6,[4]);const moved=JSON.parse(JSON.stringify({slots:g.slots,remaining:g.remaining()}));let invalid=false;try{g.move(8,[2])}catch(e){invalid=true}g.restore(6);const restored=g.remaining();g.undo();const undone=g.remaining();g.undo();console.log(JSON.stringify({moved,invalid,restored,undone,last:g.remaining()}))")
    assert result['moved']=={'slots':{'6':[1,2,4],'7':[3],'8':[],'9':[]},'remaining':[5,6]}
    assert result['invalid'] and result['restored']==[1,2,4,5,6]
    assert result['undone']==[5,6] and result['last']==[4,5,6]


def test_every_slot_and_shortcut_ignores_modifiers_and_repeat():
    result=node("const E=require('./static/js/morphology-groups.js'),g=new E.Groups([1,2,3,4]);E.slots.forEach((n,i)=>g.move(n,[i+1]));console.log(JSON.stringify({slots:g.slots,remaining:g.remaining(),keys:[{key:'6'},{key:'9'},{key:'8',ctrlKey:true},{key:'7',repeat:true},{key:'a'}].map(e=>E.shortcut(e))}))")
    assert result['remaining']==[] and result['slots']=={'6':[1],'7':[2],'8':[3],'9':[4]}
    assert result['keys']==[6,9,None,None,None]


@pytest.mark.parametrize('payload',[{'samples':[99]},{'samples':[True]},{'samples':[1,1]},{'exclude_samples':[0]},{'samples':'bad'},{'samples':None}])
def test_density_membership_rejects_invalid_or_stale_samples(payload):
    with pytest.raises(ValueError):density_samples([1,2,3],payload)


def test_density_membership_empty_include_is_empty_and_demo_matches():
    source=list(range(800));payloads=[{},dict(samples=[]),dict(samples=[1,2,3],exclude_samples=[2]),dict(exclude_samples=[1,2])]
    expected=[density_samples(source,p) for p in payloads]
    actual=node("const E=require('./static/js/overview-engine.js'),p=JSON.parse(require('fs').readFileSync(0,'utf8'));console.log(JSON.stringify(p.payloads.map(x=>E.densitySamples(p.source,x))))",dict(source=source,payloads=payloads))
    assert actual==expected and expected[1]==[]


def test_template_retains_more_than_five_hundred_beats(tmp_path):
    samples=list(range(601))
    store=Storage(tmp_path/'templates.db')
    result=store.create_beat_template('test',dict(name='整组',rhythm_family='自定义',lead='V2',sample_indices=samples),'test')
    assert result['beat_count']==601 and store.get_beat_template(result['id'])['sample_indices']==samples


def test_density_filter_api_revision_group_and_two_leads(client):
    case=client.get('/api/cases').json['items'][0]['case_id'];base=f'/api/cases/{case}'
    overview=client.get(base+'/overview').json
    samples=[r[0] for r in overview['rows'] if r[2]=='N'][20:32]
    payload=dict(samples=samples,revision=overview['revision'])
    for lead in ('II','V1'):
        result=client.post(base+'/waveform-density?class_code=N&lead='+lead,json=payload)
        assert result.status_code==200 and result.json['total']==12
        assert result.json['population_samples']==samples
        subgroup=client.post(base+'/waveform-density?class_code=N&lead='+lead,json={**payload,'exclude_samples':samples[:5],'amplitude_limit':result.json['amplitude_limit']})
        assert subgroup.json['population_samples']==samples[5:]
    assert client.post(base+'/waveform-density',json={**payload,'revision':-1}).status_code==400
    assert client.post(base+'/waveform-density',json={'samples':[True]}).status_code==400
    assert client.post(base+'/waveform-density',json={'amplitude_limit':-1}).status_code==400
    whole=[r[0] for r in overview['rows'] if r[2]=='N'][20:621]
    created=client.post(base+'/beat-templates',json=dict(name='全组测试',lead='V1',source_class='source-N',sample_indices=whole,revision=overview['revision']))
    assert created.status_code==201 and created.json['beat_count']==601
    assert client.post(base+'/beat-templates',json=dict(name='过期',sample_indices=whole,revision=-1)).status_code==400
