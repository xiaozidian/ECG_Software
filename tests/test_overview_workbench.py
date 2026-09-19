"""Functional contracts, not clinical sensitivity/specificity validation."""
import json
import math
import shutil
import struct
import subprocess
from pathlib import Path

import pytest

from ecg_core.overview import RhythmReviewStore, density, validate_document
from ecg_core.storage import Storage
from ecg_core.beat_editor import BeatEditorStore, EditedRecords, blank
from ecg_core.clinical_analysis import build_index

ROOT = Path(__file__).resolve().parents[1]


def node(source):
    binary = shutil.which("node")
    if not binary:
        pytest.skip("Node unavailable")
    return json.loads(subprocess.check_output([binary, "-e", "const E=require('./static/js/overview-engine.js');"+source], cwd=ROOT, text=True))


def episode(**extra):
    return dict(id="one", start_s=10, end_s=40, kind="AF", status="pending", source="manual", note="", **extra)


def test_histograms_and_lorenz_use_actual_adjacent_intervals():
    result=node("const rows=E.decode({rows:[[0,0,'N'],[160,800,'N'],[360,1000,'S'],[500,700,'X'],[700,0,'N'],[880,900,'N'],[1060,900,'N']]});console.log(JSON.stringify({h:E.histogram(rows).bins.reduce((n,b)=>n+b.count,0),ratio:E.histogram(rows,true).bins.filter(b=>b.count).map(b=>[b.start,b.count]),rr:E.pairs(rows).map(r=>[r.x,r.y]),nn:E.pairs(rows,'nn').map(r=>[r.x,r.y])}));")
    assert result["h"] == 4
    assert result["ratio"] == [[100, 1], [125, 1]]
    assert result["rr"] == [[800,1000],[900,900]]
    assert result["nn"] == [[900,900]]


def test_af_screen_does_not_call_regular_alternating_noise_or_short_signal_af():
    result=node("""
    function rows(kind){let t=0,seed=17,out=[];for(let i=0;i<180;i++){seed=(Math.imul(seed,1664525)+1013904223)>>>0;const rr=kind==='random'?500+seed%650:kind==='alternating'?(i%2?600:1000):800;t+=rr/1000;out.push({sample_index:Math.round(t*200),time_s:t,rr_ms:rr,class_code:kind==='noise'?'X':'N'})}return out}
    const out={};for(const type of ['regular','alternating','noise','random'])out[type]=E.screenAF(rows(type),145);out.short=E.screenAF(rows('random').slice(0,10),8);console.log(JSON.stringify(out));
    """)
    assert result["regular"] == result["alternating"] == result["noise"] == result["short"] == []
    assert result["random"] and all(x["status"] == "pending" and x["kind"] == "AF" for x in result["random"])


def test_cut_keeps_outside_segments_and_validates_overlaps():
    result=node("console.log(JSON.stringify(E.cut([{id:'x',start_s:0,end_s:100,kind:'AF',status:'confirmed'}],20,40)));")
    assert [(x["start_s"],x["end_s"]) for x in result] == [(0,20),(40,100)]
    assert len({x["id"] for x in result}) == 2
    for field,value in [("start_s",True),("end_s",math.inf),("end_s",-1),("kind","VT")]:
        item=episode();item[field]=value
        with pytest.raises(ValueError):validate_document(dict(episodes=[item]),100)
    a=episode();a["status"]="confirmed";b={**a,"id":"two","start_s":30,"end_s":50}
    with pytest.raises(ValueError):validate_document(dict(episodes=[a,b]),100)


def test_repeated_disjoint_cuts_keep_bounded_unique_ids():
    result=node("let parts=[{id:'x'.repeat(95),start_s:0,end_s:500,kind:'AF',status:'confirmed'}];for(let i=1;i<120;i++)parts=E.cut(parts,i*4,i*4+1);console.log(JSON.stringify(E.validateDocument({episodes:parts},500)));")
    assert len(result['episodes']) == 120
    assert max(len(x['id']) for x in result['episodes']) <= 100
    assert len({x['id'] for x in result['episodes']}) == 120


def test_rhythm_review_atomic_revision_history_and_report_authority(tmp_path):
    storage=Storage(tmp_path/"state.db");BeatEditorStore(storage);store=RhythmReviewStore(storage)
    initial=dict(episodes=[episode()],bookmarks={})
    assert store.public(store.read("c",initial))["can_undo"] is False
    payload=dict(confirmed=True,revision=0,beat_revision=0,document=dict(episodes=[],bookmarks={}))
    saved=store.commit("c",payload,100,initial,"test",0)
    assert saved["revision"] == 1 and saved["can_undo"]
    with pytest.raises(ValueError):store.commit("c",payload,100,initial,"test",0)
    restored=store.commit("c",dict(payload,revision=1,operation="undo"),100,initial,"test",0)
    assert restored["document"] == initial and restored["can_redo"]
    removed=store.commit("c",dict(payload,revision=2,operation="redo"),100,initial,"test",0)
    assert removed["document"]["episodes"] == []
    records=tuple((s,0,1,0,0,0,800) for s in [0,160,320,480])
    doc=blank();doc["changes"]={"s:160":{"class_code":"A"},"s:320":{"class_code":"A"}}
    feed=EditedRecords(records,doc,[],100)
    assert any(x["category"]=="AF" for x in build_index(feed)["events"])
    assert not any(x["category"]=="AF" for x in build_index(feed,annotations=storage.list_annotations("c"))["events"])


def test_density_counts_every_complete_beat_and_gate_python_js_parity(tmp_path):
    path=tmp_path/"data.bin";length=12000
    signal=[round(200*math.sin(i*.08)+700*math.exp(-((i%200-100)/5)**2)) for i in range(length)]
    path.write_bytes(b"".join(struct.pack('<8h',*([v]*8)) for v in signal))
    samples=list(range(100,length,200));gate=(-.1,.1,-200,500)
    result=density(path,samples,"II",gate)
    assert result["total"]==60 and result["included"]==58 and result["skipped_edges"]==2
    assert sum(result["bins"])+result["clipped_points"] == 58*200
    js=node("const fs=require('fs'),b=fs.readFileSync("+json.dumps(str(path))+"),samples="+json.dumps(samples)+";E.density(samples,b.length/16,s=>b.readInt16LE(s*16),'II',[-.1,.1,-200,500]).then(r=>console.log(JSON.stringify(r)));")
    assert js["bins"] == result["bins"]
    assert js["sample_indices"] == result["sample_indices"]


def test_manual_report_strip_and_af_are_same_in_python_and_demo():
    records=tuple((s,0,1,0,0,0,800) for s in [0,160,320,480,640])
    feed=EditedRecords(records,blank(),[],10)
    annotations=[dict(id=12,sample_index=160,details=dict(kind="STRIP",status="confirmed",end_sample=500,finding="人工图条"))]
    py=build_index(feed,annotations=annotations)
    js=node("const B=require('./static/js/beat-engine.js'),A=require('./static/js/clinical-analysis.js');const feed=B.materialize([0,160,320,480,640].map(sample_index=>({sample_index,group:1})),B.blank());feed.document=B.blank();feed.duration=10;console.log(JSON.stringify(A.buildIndex(feed,[],"+json.dumps(annotations)+").events));")
    item=next(x for x in py["events"] if x["event_id"]=="annotation:12")
    assert item["category"]=="other" and item["subtype"]=="STRIP" and item["target_samples"]==[160,320,480]
    assert next(x for x in js if x["event_id"]=="annotation:12")["basis_version"] == item["basis_version"]


def test_live_overview_and_episode_endpoints_are_validated(client):
    case=client.get('/api/cases').get_json()['items'][0]['case_id'];base='/api/cases/'+case
    overview=client.get(base+'/overview').get_json();rhythm=client.get(base+'/rhythm-review').get_json()
    assert overview['rows'] and overview['columns']==['sample_index','rr_ms','class_code']
    assert overview['revision']==rhythm['beat_revision']
    payload=dict(confirmed=True,revision=rhythm['revision'],beat_revision=overview['revision'],document=dict(episodes=[episode()],bookmarks={}))
    assert client.put(base+'/rhythm-review',json=payload).status_code==200
    assert client.put(base+'/rhythm-review',json=payload).status_code==400
    assert client.get(base+'/waveform-density?class_code=invalid').status_code==400
