"""Non-clinical regression tests for doctor-command data semantics."""
import json
import math
import shutil
import subprocess
from pathlib import Path

import pytest

from ecg_core.beat_editor import (
    TYPES, BeatEditorStore, EditedRecords, apply_operation, blank, edited_hrv,
    materialize, propose_qrs, settings,
)
from ecg_core.ebi import list_events, rr_visuals
from ecg_core.storage import Storage

ROOT=Path(__file__).resolve().parents[1]


def records(samples, groups=None):
    return tuple((s,0,(groups or [1]*len(samples))[i],0,0,0,800) for i,s in enumerate(samples))


def change(source,doc,operation,samples=(),**extra):
    return apply_operation(source,doc,[],dict(operation=operation,selection={"samples":list(samples)},**extra),600)[0]


def test_catalog_uses_hospital_shortcuts_not_wfdb_and_keeps_nonbeats_out():
    assert set("NSVJGPBACFERWOZMHYTX") <= set(TYPES)
    assert {"PA","PV","PD","PF","BL","BR"} <= set(TYPES)
    source=records([100,260,420,580,740])
    for code in ("Y","T","O"):
        doc=change(source,blank(),"relabel",[260],class_code=code)
        beats,markers=materialize(source,doc)
        assert len(beats)==4 and markers[0]["class_code"]==code
        assert beats[1]["rr_ms"]==1600
    # Historical project O meant Other, not the new hospital nonconducted P.
    beats,markers=materialize(source,blank(),[{"sample_index":260,"class_code":"O"}])
    assert len(beats)==5 and not markers and beats[1]["class_code"]=="OTHER"
    assert TYPES["A"]["kind"]=="rhythm" and TYPES["S"]["kind"]=="beat"


def test_edit_delete_insert_move_restore_recomputes_neighbors_and_preserves_source():
    source=records([100,260,420,580]);original=tuple(source)
    doc=change(source,blank(),"delete",[260])
    assert materialize(source,doc)[0][1]["rr_ms"]==1600
    doc=change(source,doc,"insert",positions=[270],class_code="N")
    beats,_=materialize(source,doc)
    assert [r["rr_ms"] for r in beats]==[0,850,750,800]
    doc=change(source,doc,"move",[270],target_sample=280)
    assert [r["rr_ms"] for r in materialize(source,doc)[0]]==[0,900,700,800]
    assert source==original
    with pytest.raises(ValueError):change(source,doc,"move",[280],target_sample=415)
    with pytest.raises(ValueError):change(source,doc,"insert",positions=[420])
    with pytest.raises(ValueError):change(source,doc,"insert",positions=[True])
    with pytest.raises(ValueError):change(source,doc,"insert",positions=[[1]])
    with pytest.raises(ValueError):change(source,doc,"relabel",[999],class_code="N")


def test_reinsert_original_position_never_reuses_moved_beat_id():
    source=records([0,400,800])
    doc=change(source,blank(),"insert",positions=[200],class_code="N")
    doc=change(source,doc,"move",[200],target_sample=240)
    doc=change(source,doc,"insert",positions=[200],class_code="N")
    beats,_=materialize(source,doc)
    assert [(r["id"],r["sample_index"]) for r in beats if r["source_sample"] is None]==[("i:200:1",200),("i:200",240)]
    node=shutil.which("node")
    if node:
        script="""const E=require('./static/js/beat-engine.js'),s=[0,400,800].map(sample_index=>({sample_index,group:1}));let d=E.blank();for(const op of [{operation:'insert',positions:[200],class_code:'N'},{operation:'move',selection:{samples:[200]},target_sample:240},{operation:'insert',positions:[200],class_code:'N'}])d=E.apply(s,d,[],op,600).document;console.log(JSON.stringify(E.materialize(s,d).beats.filter(r=>r.source_sample===null).map(r=>[r.id,r.sample_index])));"""
        assert json.loads(subprocess.check_output([node,"-e",script],cwd=ROOT,text=True))==[["i:200:1",200],["i:200",240]]


def test_nn_successive_differences_do_not_bridge_ectopy_or_noise():
    source=records([0,160,320,480,640,880,1120,1360,1600],[1,1,1,3,1,1,1,34,1])
    feed=EditedRecords(source,blank(),[],600)
    hrv=edited_hrv(feed)
    assert hrv["nn_count"]==4 and hrv["successive_nn_pairs"]==2
    assert hrv["rmssd_ms"]==0 and hrv["pnn50_pct"]==0
    assert rr_visuals(feed)["poincare"]==[[800,800],[1200,1200]]


def test_longest_is_bookmark_not_forged_statistic_and_events_are_independent():
    source=records([0,200,400,1000],[1,1,1,3])
    doc=change(source,blank(),"longest",[200])
    feed=EditedRecords(source,doc,[],600)
    assert doc["longest_id"]=="s:200"
    from ecg_core.ebi import metrics
    assert metrics(feed,600)["longest_rr_ms"]==3000
    types={r["type"] for r in list_events(feed)["items"] if r["sample_index"]==1000}
    assert types=={"V","pause","brady"}
    doc=change(source,doc,"relabel",[400],class_code="C")
    assert list_events(EditedRecords(source,doc,[],600),"AFL")["total"]==1


def test_candidate_detector_flat_inverted_and_refractory():
    peaks=[200,400,600,800]
    signal=[sum(1000*math.exp(-((i-p)/3)**2) for p in peaks) for i in range(1000)]
    for direction in (1,-1):
        result=propose_qrs([direction*x for x in signal],0,[200],settings({}))
        assert [r["sample_index"] for r in result]==[400,600,800]
    assert propose_qrs([0]*1000,0,[],settings({}))==[]
    assert propose_qrs([float("nan")]*100,0,[],settings({}))==[]
    with pytest.raises(ValueError):settings({"refractory_ms":False})
    with pytest.raises(ValueError):settings({"brady":100,"tachy":80})


@pytest.mark.parametrize("code",list(TYPES))
def test_each_menu_type_materializes(code):
    source=records([0,200,400])
    doc=change(source,blank(),"relabel",[200],class_code=code)
    beats,markers=materialize(source,doc)
    row=next(r for r in beats+markers if r["sample_index"]==200)
    assert row["class_code"]==code and row["kind"]==TYPES[code]["kind"]


def test_noise_boundary_does_not_create_false_pause():
    feed=EditedRecords(records([0,200,1000,1800],[1,1,34,1]),blank(),[],600)
    assert feed.beats[-1]["rr_ms"]==0
    assert list_events(feed,"pause")["total"]==0


def test_store_atomic_revision_undo_redo_survive_reopen(tmp_path):
    storage=Storage(tmp_path/"editor.db");store=BeatEditorStore(storage);source=records([0,200,400])
    original=store.read("test")
    changed=store.commit("test",0,"test",lambda doc:change(source,doc,"relabel",[200],class_code="V"),"relabel")
    with pytest.raises(ValueError):store.commit("test",0,"test",lambda d:d,"delete")
    with pytest.raises(ValueError):store.commit("test",True,"test",lambda d:d,"delete")
    assert store.read("test")["revision"]==1
    undone=store.commit("test",1,"test",None,"undo")
    assert undone["document"]==original["document"]
    redone=BeatEditorStore(Storage(tmp_path/"editor.db")).commit("test",2,"test",None,"redo")
    assert redone["document"]==changed["document"]
    assert len(storage.get_review("test")["pending_steps"])==5


def test_api_preview_is_read_only_and_edited_views_share_version(client):
    case_id=client.get("/api/cases").json["items"][0]["case_id"];base="/api/cases/"+case_id
    source=client.get(base).json
    snapshot=client.get(base+"/beat-editor").json
    beats=client.get(base+"/beat-editor/beats").json["items"];chosen=beats[20]["sample_index"]
    payload={"operation":"delete","selection":{"samples":[chosen]},"revision":snapshot["revision"]}
    preview=client.post(base+"/beat-editor/preview",json=payload)
    assert preview.status_code==200,preview.json
    assert preview.json["after"]["metrics"]["valid_beats"]==snapshot["metrics"]["valid_beats"]-1
    assert client.get(base+"/beat-editor").json["revision"]==snapshot["revision"]
    assert client.put(base+"/beat-editor",json=payload).status_code==400
    assert client.post(base+"/beat-editor/preview",json={**payload,"revision":False}).status_code==400
    result=client.put(base+"/beat-editor",json={**payload,"confirmed":True})
    assert result.status_code==200,result.json
    assert client.put(base+"/beat-editor",json={**payload,"confirmed":True}).status_code==400
    edited=client.get(base+"?analysis=edited").json
    assert edited["analysis_revision"]==result.json["revision"]
    assert edited["calculated"]==result.json["metrics"]
    assert client.get(base+"/hrv?analysis=edited").json["calculated"]==result.json["hrv"]
    assert client.get(base).json["calculated"]==source["calculated"]
    assert client.get(base).json["summary"]==source["summary"]
    undone=client.put(base+"/beat-editor",json={"operation":"undo","revision":result.json["revision"],"confirmed":True})
    assert undone.json["metrics"]==snapshot["metrics"]
    assert client.post(base+"/beat-editor/preview",json={"operation":"detect","revision":undone.json["revision"],"start_s":0,"duration_s":5}).status_code==200


def test_portable_engine_matches_python_operations_hrv_events_and_qrs():
    node=shutil.which("node")
    if not node:pytest.skip("Node required for portable-engine parity")
    source=records([0,160,320,480,640,880,1120,1360,1600],[1,1,1,3,1,1,1,34,1])
    operations=[
        {"operation":"relabel","selection":{"samples":[480]},"class_code":"N"},
        {"operation":"move","selection":{"samples":[640]},"target_sample":660},
        {"operation":"delete","selection":{"samples":[880]}},
        {"operation":"insert","positions":[900],"class_code":"PV"},
        {"operation":"relabel","selection":{"samples":[320]},"class_code":"T"},
    ]
    doc=blank()
    for op in operations:doc=apply_operation(source,doc,[],op,600)[0]
    feed=EditedRecords(source,doc,[],600)
    signal=[1000*math.exp(-((i-100)/3)**2)+700*math.exp(-((i-300)/3)**2) for i in range(500)]
    payload={"source":[{"sample_index":r[0],"group":r[2]} for r in source],"operations":operations,"signal":signal}
    script="""const E=require('./static/js/beat-engine.js');let p=JSON.parse(process.argv[1]),d=E.blank();for(const op of p.operations)d=E.apply(p.source,d,[],op,600).document;const f=E.materialize(p.source,d);console.log(JSON.stringify({beats:f.beats.map(r=>[r.sample_index,r.class_code,r.rr_ms]),markers:f.markers.map(r=>[r.sample_index,r.class_code]),hrv:E.hrv(f,600),events:E.events(f).summary,qrs:E.detect(p.signal,0,[],E.defaults)}));"""
    result=json.loads(subprocess.check_output([node,"-e",script,json.dumps(payload)],cwd=ROOT,text=True))
    assert result["beats"]==[[r["sample_index"],r["class_code"],r["rr_ms"]] for r in feed.beats]
    assert result["markers"]==[[r["sample_index"],r["class_code"]] for r in feed.markers]
    assert result["hrv"]==edited_hrv(feed)
    assert result["events"]==list_events(feed)["summary"]
    assert result["qrs"]==propose_qrs(signal,0,[],settings({}))


def test_template_membership_follows_stable_beat_id_after_move_and_undo(client):
    case_id=client.get("/api/cases").json["items"][0]["case_id"];base="/api/cases/"+case_id
    item=client.get(base+"/beat-editor/beats").json["items"][20];sample=item["sample_index"]
    template=client.post(base+"/beat-templates?analysis=edited",json={"name":"修订跟随测试","rhythm_family":"自定义","lead":"II","sample_indices":[sample]})
    assert template.status_code==201,template.json
    result=client.put(base+"/beat-editor",json={"operation":"move","selection":{"samples":[sample]},"target_sample":sample+1,"revision":0,"confirmed":True})
    assert result.status_code==200,result.json
    assert client.get(base+"/beat-templates?analysis=edited").json["items"][0]["sample_indices"]==[sample+1]
    assert client.put(base+"/beat-editor",json={"operation":"undo","revision":1,"confirmed":True}).status_code==200
    assert client.get(base+"/beat-templates?analysis=edited").json["items"][0]["sample_indices"]==[sample]


def test_static_demo_edit_pipeline_and_storage_failure(tmp_path):
    node=shutil.which("node")
    if not node:pytest.skip("Node required for Demo regression")
    from scripts.build_static_demo import build
    output=build(tmp_path/"demo")
    script=r"""
const fs=require("fs"),path=require("path"),E=require("./static/js/beat-engine.js");
const store=new Map();let quota=false;
global.document={addEventListener(){}};
global.location={href:"https://demo.invalid/"};
global.localStorage={getItem:k=>store.get(k)||null,setItem:(k,v)=>{if(quota)throw Error("quota");store.set(k,v)}};
global.window={fetch:async p=>new Response(fs.readFileSync(path.join(process.cwd(),"static/demo-data/uploaded-sim-af-001/waveform.bin")))};
require("./static/demo-data/uploaded-sim-af-001/case-data.js");require("./static/js/demo-api.js");
const id=window.__CARDIOINSIGHT_UPLOADED_CASE__.case_id,base="/api/cases/"+id;
async function req(path,method="GET",body){const r=await window.fetch(base+path,{method,body:body?JSON.stringify(body):undefined});return {status:r.status,data:await r.json()}}
function check(ok,msg){if(!ok)throw Error(msg)}
(async()=>{
 const original=(await req("")).data,initial=(await req("/beat-editor")).data;
 const all=(await req("/beat-editor/beats")).data.items,sample=all.find(r=>r.class_code==="N"&&r.sample_index>200).sample_index;
 const payload={operation:"relabel",selection:{samples:[sample]},class_code:"Y",revision:0};
 const preview=await req("/beat-editor/preview","POST",payload);
 check(preview.status===200&&preview.data.after.metrics.valid_beats===initial.metrics.valid_beats-1,"preview statistics");
 check((await req("/beat-editor")).data.revision===0,"preview mutated");
 check((await req("/beat-editor","PUT",payload)).status===400,"confirmation guard");
 const saved=await req("/beat-editor","PUT",{...payload,confirmed:true});
 check(saved.data.markers.length===1&&saved.data.revision===1,"marker persistence");
 const detail=(await req("?analysis=edited")).data;
 check(detail.calculated.valid_beats===initial.metrics.valid_beats-1,"edited metrics");
 check(JSON.stringify((await req("/hrv?analysis=edited")).data.calculated)===JSON.stringify(saved.data.hrv),"HRV mismatch");
 check((await req("")).data.calculated.valid_beats===original.calculated.valid_beats,"source changed");
 check((await req("/beat-editor","PUT",{...payload,confirmed:true})).status===400,"stale revision");
 const undone=await req("/beat-editor","PUT",{operation:"undo",revision:1,confirmed:true});
 check(undone.data.metrics.valid_beats===initial.metrics.valid_beats,"undo");
 const restored=JSON.stringify((await req("/beat-editor")).data);
 quota=true;
 check((await req("/beat-editor","PUT",{...payload,revision:2,confirmed:true})).status===400,"quota accepted");
 quota=false;
 check(JSON.stringify((await req("/beat-editor")).data)===restored,"quota did not roll back");
 const candidates=await req("/beat-editor/preview","POST",{operation:"detect",revision:2,start_s:0,duration_s:10});
 check(candidates.status===200&&Array.isArray(candidates.data.candidates),"detector");
 check((await req("/beat-editor")).data.revision===2,"detector persisted");
 const p=(await req("/beat-editor/beats")).data.items[10].sample_index;
 const template=await req("/beat-templates?analysis=edited","POST",{name:"test","rhythm_family":"自定义",lead:"II",sample_indices:[p]});
 check(template.status===201,"template create");
 const moved=await req("/beat-editor","PUT",{operation:"move",selection:{samples:[p]},target_sample:p+1,revision:2,confirmed:true});
 check(moved.status===200,"move");
 check((await req("/beat-templates?analysis=edited")).data.items[0].sample_indices[0]===p+1,"template membership lost");
 const deleted=await req("/beat-editor","PUT",{operation:"delete",selection:{scope:"all"},revision:3,confirmed:true});
 check(deleted.status===200&&deleted.data.metrics.valid_beats===0,"delete all");
 const empty=await req("?analysis=edited");
 check(empty.status===200&&empty.data.calculated.valid_beats===0,"empty edited case");
 check((await req("/hrv?analysis=edited")).status===200,"empty HRV");
 check((await req("/beat-editor","PUT",{operation:"undo",revision:4,confirmed:true})).data.metrics.valid_beats===initial.metrics.valid_beats,"undo all");
 console.log("Demo edit, preview, RR/HRV, undo, stale revision, quota rollback, QRS and template tracking passed");
})().catch(e=>{console.error(e);process.exitCode=1});
"""
    result=subprocess.run([node,"-e",script],cwd=output,capture_output=True,text=True)
    assert result.returncode==0,result.stderr
