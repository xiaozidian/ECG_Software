"""RR screening quality and preservation contracts, not clinical accuracy."""
import json
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]
PREAMBLE = """
const E=require('./static/js/overview-engine.js');
function rows(duration=120,offset=0,random=true){
  let seed=17,sample=offset*200,out=[{sample_index:sample,time_s:offset,rr_ms:0,class_code:'N'}];
  while(true){seed=(Math.imul(seed,1664525)+1013904223)>>>0;
    const rr=random?500+(seed%130)*5:800;sample+=rr/5;
    if(sample/200>=offset+duration)break;
    out.push({sample_index:sample,time_s:sample/200,rr_ms:rr,class_code:'N'});
  }return out;
}
const document={episodes:[],bookmarks:{}};
const episode=(id,start,end,status='pending',source='rr-irregularity-v1')=>({id,start_s:start,end_s:end,kind:'AF',status,source,note:'retain'});
"""


def node(source):
    return json.loads(subprocess.check_output(['node', '-e', PREAMBLE+source], cwd=ROOT, text=True))


def test_inconsistent_rr_cannot_create_af_from_regular_peak_positions():
    result=node("const r=rows();r.forEach((x,i)=>{x.sample_index=i*160;x.time_s=i*.8});console.log(JSON.stringify(E.screenAFResult(r,120)));")
    assert result['episodes']==[] and result['evaluated_windows']==0
    assert all(w['reason'] for w in result['windows'])


def test_consistent_irregular_rr_still_produces_pending_candidates():
    result=node("console.log(JSON.stringify(E.screenAFResult(rows(),120)));")
    assert result['evaluated_windows']==4 and result['episodes']
    assert all(e['status']=='pending' and e['kind']=='AF' and e['source']=='rr-irregularity-v2' for e in result['episodes'])
    assert all(w['coverage_s']>=25 for w in result['windows'])


def test_display_relative_time_is_never_used_as_measurement_clock():
    result=node("const r=rows(90,600);const before=E.screenAFResult(r,690,600,690);r.forEach(x=>x.time_s=-999);console.log(JSON.stringify({before,after:E.screenAFResult(r,690,600,690)}));")
    assert result['before']==result['after']
    assert result['after']['evaluated_windows']==3
    assert all(e['start_s']>=600 and e['end_s']<=690 for e in result['after']['episodes'])


@pytest.mark.parametrize('kind',['X','S','V'])
def test_artifact_and_ectopic_boundaries_withhold_low_quality_windows(kind):
    result=node(f"const r=rows();r.forEach((x,i)=>{{if(i%8===0)x.class_code={json.dumps(kind)}}});console.log(JSON.stringify(E.screenAFResult(r,120)));")
    assert result['episodes']==[] and result['evaluated_windows']==0


def test_partial_tail_is_not_reported_as_evaluated_or_normal():
    result=node("console.log(JSON.stringify(E.screenAFResult(rows(59),59)));")
    assert result['evaluated_windows']==1 and result['skipped_windows']==1
    assert result['windows'][-1]['reason']=='incomplete_window'
    assert result['windows'][-1]['cv'] is None
    assert all(e['end_s']<=30 for e in result['episodes'])


def test_non_qrs_annotations_do_not_break_or_supply_rr_intervals():
    result=node("const r=rows();const marked=r.flatMap(x=>[x,{...x,class_code:'T'}]);console.log(JSON.stringify({before:E.screenAFResult(r,120),after:E.screenAFResult(marked,120)}));")
    assert result['before']==result['after']


def test_pair_and_turning_features_do_not_bridge_rejected_intervals():
    result=node("const r=rows(30);r[15].class_code='X';console.log(JSON.stringify({rows:r,result:E.screenAFResult(r,30)}));")
    rows=result['rows'];good=[]
    for i in range(1,len(rows)):
        if rows[i]['class_code']==rows[i-1]['class_code']=='N':good.append(i)
    pairs=[(a,b) for a,b in zip(good,good[1:]) if b==a+1]
    triples=[(a,b,c) for a,b,c in zip(good,good[1:],good[2:]) if b==a+1 and c==b+1]
    window=result['result']['windows'][0]
    assert window['evaluated']
    assert window['pair_count']==len(pairs)
    assert window['triple_count']==len(triples)<len(good)-2
    turns=sum((rows[b]['rr_ms']-rows[a]['rr_ms'])*(rows[c]['rr_ms']-rows[b]['rr_ms'])<0 for a,b,c in triples)
    assert window['turning_ratio']==pytest.approx(turns/len(triples))


def test_bad_middle_window_breaks_candidate_episode_and_is_not_erased():
    result=node("const r=rows(90);r.forEach(x=>{if(x.time_s>=30&&x.time_s<60)x.class_code='X'});const doc={episodes:[episode('old',0,90)],bookmarks:{}};console.log(JSON.stringify(E.planAFRescreen(r,90,doc)));")
    assert result['windows'][1]['evaluated'] is False
    assert any(e['source']=='rr-irregularity-v1' and e['start_s']==30 and e['end_s']==60 for e in result['document']['episodes'])
    assert all(e['end_s']<=30 or e['start_s']>=60 for e in result['candidates'])


@pytest.mark.parametrize('source',['rr-irregularity-v1','rr-irregularity-v2','manual','source-annotation'])
@pytest.mark.parametrize('status',['confirmed','excluded'])
def test_rescreen_preserves_doctor_decisions_and_does_not_overlap(source,status):
    result=node(f"const old=episode('doctor',20,50,{json.dumps(status)},{json.dumps(source)}),doc={{episodes:[old],bookmarks:{{fastest:10}}}};console.log(JSON.stringify({{old,plan:E.planAFRescreen(rows(90),90,doc)}}));")
    plan=result['plan'];assert result['old'] in plan['document']['episodes']
    assert plan['document']['bookmarks']=={'fastest':10}
    assert all(e['end_s']<=20 or e['start_s']>=50 for e in plan['candidates'])


def test_no_assessable_windows_leave_existing_document_unchanged():
    result=node("const doc={episodes:[episode('old',0,90)],bookmarks:{}};const r=rows(90).map(x=>({...x,class_code:'X'}));console.log(JSON.stringify({doc,result:E.planAFRescreen(r,90,doc)}));")
    assert result['result']['evaluated_windows']==0
    assert result['result']['document']==result['doc']


def test_range_rescreen_replaces_only_pending_algorithm_output_inside_assessed_range():
    result=node("const doc={episodes:[episode('old',0,120),episode('manual',65,70,'pending','manual')],bookmarks:{}};const before=JSON.stringify(doc),r=rows(120),beforeRows=JSON.stringify(r);const result=E.planAFRescreen(r,120,doc,60,90);console.log(JSON.stringify({result,unchanged:before===JSON.stringify(doc)&&beforeRows===JSON.stringify(r)}));")
    assert result['unchanged']
    events=result['result']['document']['episodes']
    assert any(e['start_s']==0 and e['end_s']==60 for e in events)
    assert any(e['start_s']==90 and e['end_s']==120 for e in events)
    assert any(e['id']=='manual' for e in events)
    assert all(60<=e['start_s']<e['end_s']<=90 and (e['end_s']<=65 or e['start_s']>=70) for e in result['result']['candidates'])
    assert len({e['id'] for e in events})==len(events)


@pytest.mark.parametrize('args',['0','120,-1,60','120,60,30','120,0,121','Infinity','120,NaN,60'])
def test_invalid_range_rejected(args):
    assert node(f"try{{E.screenAFResult(rows(),{args});console.log(false)}}catch(e){{console.log(true)}}")


def test_ui_plan_reports_quality_and_refuses_zero_evaluated_windows():
    result=node("""
const fs=require('fs'),vm=require('vm'),src=fs.readFileSync('./static/js/overview-workbench.js','utf8');
const body=src.slice(src.indexOf('  function screenAF(selectedRange='),src.indexOf('  function screenPAC('));
let calls=[],coverage=[];const context={E,ui:{rows:rows(90),rhythm:{document}},coverageRun:0,coverageBusy:false,coverageBasis:()=>({}),publishCoverage:(...args)=>coverage.push(args),duration:()=>90,span:()=>[30,90],formatElapsed:String,confirmRhythm:(...args)=>calls.push(args)};
vm.createContext(context);vm.runInContext(body+';screenAF(true)',context);
context.ui.rows=context.ui.rows.map(x=>({...x,class_code:'X'}));let error='';try{vm.runInContext('screenAF()',context)}catch(e){error=e.message}
console.log(JSON.stringify({calls,error,coverage}));
""")
    assert len(result['calls'])==1
    assert '评估 2 个完整 30 秒窗口' in result['calls'][0][2]
    assert '保留医生已确认／已排除' in result['calls'][0][2]
    assert '未评估不代表正常' in result['error']
    assert len(result['coverage'])==2
    assert result['coverage'][1][0]['evaluated_windows']==0


@pytest.mark.parametrize('change',["state.caseId='other'",'ui.revision++','ui.rhythm.revision++',''])
def test_confirmation_counts_excluded_records_and_binds_original_revision(change):
    result=node("""
const fs=require('fs'),vm=require('vm'),src=fs.readFileSync('./static/js/overview-workbench.js','utf8');
const body=src.slice(src.indexOf('  const rhythmBasis='),src.indexOf('  function episodeForm('));
let accept,copy,saved=0;const context={state:{caseId:'c'},ui:{revision:2,rhythm:{revision:3}},esc:String,dialog:(title,text,action)=>{copy=text;accept=action},saveRhythm:()=>saved++,doc:{episodes:[episode('one',0,30),episode('two',30,60,'excluded')]}};
vm.createContext(context);vm.runInContext(body+";confirmRhythm('title',doc,'detail')",context);
"""+f"vm.runInContext({json.dumps(change)},context);"+"""
let error='';try{accept()}catch(e){error=e.message}console.log(JSON.stringify({copy,saved,error}));
""")
    assert '2 条片段记录（含 1 条已排除记录）' in result['copy']
    assert result['saved']==(0 if change else 1)
    assert bool(result['error'])==bool(change)


def edit_form_result(change='', status='pending', source='rr-irregularity-v2'):
    """Execute the shipped form handler; do not duplicate edit semantics."""
    return node("""
const fs=require('fs'),vm=require('vm'),src=fs.readFileSync('./static/js/overview-workbench.js','utf8');
const helpers=src.slice(src.indexOf('  const rhythmBasis='),src.indexOf('  function confirmRhythm('));
const renderer=src.slice(src.indexOf('  // The queue is read-only:'),src.indexOf('  function afMode('));
const nodes=new Map(),qs=key=>{if(!nodes.has(key))nodes.set(key,{});return nodes.get(key)};
let plan,error='',detail='';const original={episodes:[episode('edit',20,50,'pending',SOURCE)],bookmarks:{fastest:10}};
const values=new Map(Object.entries({start:'22',end:'48',kind:'AFL',status:STATUS,note:'doctor boundary review'}));
// The real editor now retains DOM input between queue renders; provide the
// same named controls to the shipped handler instead of stubbing its helpers.
qs('#ovEpisodeForm').elements=Object.fromEntries([...values].map(([k,value])=>[k,{value}]));
const context={E,state:{caseId:'c'},ui:{episode:'edit',revision:2,rhythm:{revision:3,document:original}},qs,
  duration:()=>90,innerWidth:1366,esc:String,formatElapsed:String,formatElapsedPrecise:String,name:String,statusName:String,
  button:()=>'',copy:x=>JSON.parse(JSON.stringify(x)),FormData:function(){return values},
  run:fn=>{try{fn()}catch(e){error=e.message}},confirmRhythm:(title,doc,text)=>{plan=doc;detail=text}};
vm.createContext(context);vm.runInContext('let episodeFilter="all",episodePage=0,episodeNavigation=0,episodeEditor=null;const episodeDrafts=new Map();'+helpers+renderer+';renderEpisodes()',context);
vm.runInContext(CHANGE,context);qs('#ovEpisodeForm').onsubmit({preventDefault(){},target:{}});
const rescreen=plan?E.planAFRescreen(rows(90),90,plan).document:null;
console.log(JSON.stringify({plan,error,detail,original,rescreen}));
""".replace('SOURCE',json.dumps(source)).replace('STATUS',json.dumps(status)).replace('CHANGE',json.dumps(change)))


@pytest.mark.parametrize('source',['rr-irregularity-v1','rr-irregularity-v2','source-annotation'])
@pytest.mark.parametrize('status',['pending','confirmed','excluded'])
def test_explicit_doctor_edit_is_manual_and_retains_review_status(source,status):
    result=edit_form_result(status=status,source=source)
    item=result['plan']['episodes'][0]
    assert item==dict(id='edit',start_s=22,end_s=48,kind='AFL',status=status,
                      source='manual',note='doctor boundary review')
    assert item in result['rescreen']['episodes']
    assert all(x['id']=='edit' or x['end_s']<=22 or x['start_s']>=48 for x in result['rescreen']['episodes'])
    assert result['original']['episodes'][0]['source']==source
    assert result['original']['episodes'][0]['start_s']==20
    assert '自动重分析不会替换' in result['detail']
    assert not result['error']


@pytest.mark.parametrize('change',["state.caseId='other'",'ui.revision++','ui.rhythm.revision++',
                                  'ui.rhythm.document.episodes=[]'])
def test_stale_rendered_episode_form_cannot_prepare_a_new_confirmation(change):
    result=edit_form_result(change)
    assert result.get('plan') is None and result['rescreen'] is None
    assert result['error']


@pytest.mark.parametrize('whole',[False,True])
@pytest.mark.parametrize('change',["state.caseId='other'",'ui.revision++','ui.rhythm.revision++',''])
def test_add_or_whole_record_dialog_binds_original_case_and_revision(change,whole):
    result=node("""
const fs=require('fs'),vm=require('vm'),src=fs.readFileSync('./static/js/overview-workbench.js','utf8');
const helpers=src.slice(src.indexOf('  const rhythmBasis='),src.indexOf('  function confirmRhythm('));
const form=src.slice(src.indexOf('  function episodeForm('),src.indexOf('  function renderEpisodes('));
let accept,saved=null;const original={episodes:[episode('keep',50,60)],bookmarks:{}};
const context={E,crypto,state:{caseId:'c'},ui:{revision:2,rhythm:{revision:3,document:original}},
  span:()=>[0,30],duration:()=>90,name:String,copy:x=>JSON.parse(JSON.stringify(x)),
  dialog:(title,text,action)=>accept=action,saveRhythm:doc=>saved=doc};
vm.createContext(context);vm.runInContext(helpers+form+';episodeForm("AF",WHOLE)',context);
vm.runInContext(CHANGE,context);let error='';try{accept(new Map(Object.entries({start:'0',end:END,kind:'AF',status:'pending',note:''})))}catch(e){error=e.message}
console.log(JSON.stringify({saved,error,original}));
""".replace('WHOLE',json.dumps(whole)).replace('CHANGE',json.dumps(change)).replace('END',json.dumps('90' if whole else '30')))
    if change:
        assert result['saved'] is None and result['error']
    else:
        assert len(result['saved']['episodes'])==(1 if whole else 2)
        assert result['saved']['episodes'][-1]['source']=='manual'
        assert not result['error']
    assert len(result['original']['episodes'])==1


def test_doctor_edited_pending_episode_survives_storage_rescreen_and_undo(tmp_path):
    from ecg_core.beat_editor import BeatEditorStore
    from ecg_core.overview import RhythmReviewStore
    from ecg_core.storage import Storage

    storage=Storage(tmp_path/'review.db');BeatEditorStore(storage);store=RhythmReviewStore(storage)
    result=edit_form_result();initial=result['original']
    def save(revision,document=None,operation='save'):
        return store.commit('c',dict(confirmed=True,revision=revision,beat_revision=0,
                                    document=document,operation=operation),90,initial,'test',0)
    edited=save(0,result['plan'])
    reloaded=store.read('c')['document']
    assert reloaded==edited['document'] and reloaded['episodes'][0]['source']=='manual'
    plan=node('console.log(JSON.stringify(E.planAFRescreen(rows(90),90,'+json.dumps(reloaded)+').document));')
    rescanned=save(1,plan)
    assert reloaded['episodes'][0] in rescanned['document']['episodes']
    assert save(2,operation='undo')['document']==reloaded
    assert save(3,operation='undo')['document']==initial
    assert save(4,operation='redo')['document']==reloaded
