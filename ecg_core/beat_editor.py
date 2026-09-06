"""Versioned physician edits and conservative QRS proposals, never a diagnosis engine."""
from __future__ import annotations

import copy
import json
import math
import statistics
from collections import Counter
from bisect import bisect_left
from datetime import datetime, timezone

from . import ebi
from .config import SAMPLE_RATE

# UI shortcuts follow the supplied hospital screenshot, NOT WFDB symbols.
TYPE_ROWS = [
    ("N", "正常", 1, "beat"), ("S", "房性早搏", 2, "beat"),
    ("V", "室性早搏", 3, "beat"), ("J", "交界性早搏", 2, "beat"),
    ("G", "交界性逸搏", 4, "beat"), ("P", "起搏（未细分）", 5, "beat"),
    ("PA", "心房起搏", 5, "beat"), ("PV", "心室起搏", 5, "beat"),
    ("PD", "双腔起搏", 5, "beat"), ("PF", "起搏融合波", 5, "beat"),
    ("B", "束支传导阻滞（未细分）", 6, "beat"),
    ("BL", "左束支传导阻滞", 6, "beat"), ("BR", "右束支传导阻滞", 6, "beat"),
    ("A", "房颤", 4, "rhythm"), ("C", "房扑", 4, "rhythm"),
    ("F", "融合波", 7, "beat"), ("E", "室性逸搏", 7, "beat"),
    ("R", "室内差异性传导", 6, "beat"), ("W", "房性逸搏", 4, "beat"),
    ("O", "房早未下传", 0, "nonbeat"), ("Z", "房早伴室内差异性传导", 2, "beat"),
    ("M", "房颤伴室内差异性传导", 4, "rhythm"),
    ("H", "房扑伴室内差异性传导", 4, "rhythm"),
    ("Y", "P波", 0, "nonbeat"), ("T", "T波", 0, "nonbeat"),
    ("X", "伪差", 34, "artifact"), ("OTHER", "其他／未分类", 8, "beat"),
]
TYPES = {code: dict(code=code, name=name, group=group, kind=kind) for code, name, group, kind in TYPE_ROWS}
DEFAULT_SETTINGS = dict(lead="II", refractory_ms=200, sensitivity=4.0, search_seconds=10,
                        brady=50, tachy=120, pause=2.5, nn_min=300, nn_max=2000)


def blank():
    return dict(changes={}, settings=dict(DEFAULT_SETTINGS), longest_id=None)


def integer(value, label, low=0, high=200_000_000):
    if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
        raise ValueError(f"{label}必须为 {low}–{high} 的整数")
    return value


def settings(values):
    if not isinstance(values, dict) or set(values) - set(DEFAULT_SETTINGS):
        raise ValueError("不支持的设置字段")
    result = {**DEFAULT_SETTINGS, **values}
    if result["lead"] not in ("I", "II", "III", "aVR", "aVL", "aVF", "V1", "V2", "V3", "V4", "V5", "V6"):
        raise ValueError("不支持的分析导联")
    for key, lo, hi in (("refractory_ms",100,500),("sensitivity",1,12),("search_seconds",1,60),
                       ("brady",20,100),("tachy",80,250),("pause",1.5,10),("nn_min",250,1000),("nn_max",1000,5000)):
        value=result[key]
        if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value) or not lo <= value <= hi:
            raise ValueError(f"{key} 必须为 {lo}–{hi} 的有限数值")
    if result["brady"] >= result["tachy"] or result["nn_min"] >= result["nn_max"]:
        raise ValueError("上下限顺序不正确")
    return result


def materialize(source, document, legacy=()):
    rows = {f"s:{r[0]}": dict(id=f"s:{r[0]}", sample_index=r[0], source_sample=r[0],
                source_group=r[2], class_code={1:"N",2:"S",3:"V",34:"X"}.get(r[2],"OTHER"))
            for r in source}
    for item in legacy:
        key=f"s:{item['sample_index']}"
        if key in rows:
            rows[key]["class_code"]="OTHER" if item["class_code"]=="O" else item["class_code"]
    for key, change in document["changes"].items():
        rows[key]={**rows.get(key, dict(id=key, source_sample=None, source_group=None)), **change}
    markers, beats = [], []
    for row in rows.values():
        if row.get("deleted"):
            continue
        kind=TYPES[row["class_code"]]["kind"]
        row={**row, **{k:v for k,v in TYPES[row["class_code"]].items() if k != "code"}}
        row["label"]=row["class_code"];row["time_s"]=row["sample_index"]/SAMPLE_RATE
        row["rr_ms"]=0;row["hr"]=None
        (markers if kind=="nonbeat" else beats).append(row)
    beats.sort(key=lambda r:r["sample_index"])
    previous=None
    for row in beats:
        row["rr_ms"]=(row["sample_index"]-previous["sample_index"])*1000/SAMPLE_RATE if previous and row["group"]!=34 else 0
        row["hr"]=round(60000/row["rr_ms"],1) if row["rr_ms"] else None
        if row["group"]!=34:
            previous=row
        else:
            # Do not report a physiological pause across an explicitly noisy span.
            previous=None
    return beats, sorted(markers,key=lambda r:r["sample_index"])


class EditedRecords:
    def __init__(self, source, document, legacy, duration):
        self.beats, self.markers=materialize(source,document,legacy)
        self.by_sample={row["sample_index"]:row for row in self.beats}
        self.records=tuple((row["sample_index"],0,row["group"],0,0,0,row["rr_ms"]) for row in self.beats)
        self.document=document
        self.duration=duration


def select(rows, payload):
    choice=payload.get("selection", {})
    if not isinstance(choice,dict):
        raise ValueError("selection 必须为对象")
    scope=choice.get("scope","samples")
    if scope=="all":
        selected=list(rows)
    elif scope=="range":
        start=integer(choice.get("start"),"范围起点");end=integer(choice.get("end"),"范围终点")
        if start>end:
            raise ValueError("范围起点不能晚于终点")
        selected=[r for r in rows if start<=r["sample_index"]<=end]
    elif scope=="samples":
        samples=choice.get("samples",payload.get("sample_indices",[]))
        if not isinstance(samples,list) or len(samples)>200000:
            raise ValueError("选区需为最多 200000 个采样点")
        requested={integer(s,"采样点") for s in samples}
        selected=[r for r in rows if r["sample_index"] in requested]
        if len(selected)!=len(requested):
            raise ValueError("选区含已删除或已移动的心搏，请刷新")
    else:
        raise ValueError("不支持的选区范围")
    return selected


def apply_operation(source, document, legacy, payload, duration):
    result=copy.deepcopy(document)
    rows,markers=materialize(source,document,legacy)
    op=payload.get("operation")
    inserted_ids=set()
    chosen=select(rows+markers,payload) if op not in ("settings","insert") else []
    if op not in ("settings","insert") and not chosen:
        raise ValueError("请先选择心搏")
    if op=="settings":
        result["settings"]=settings(payload.get("settings",{}))
        return result,0
    if op=="relabel":
        code=payload.get("class_code")
        if code not in TYPES:
            raise ValueError("未知人工分类")
        for row in chosen:
            result["changes"][row["id"]]={**result["changes"].get(row["id"],{}), "sample_index":row["sample_index"],"class_code":code,"deleted":False}
    elif op=="delete":
        for row in chosen:
            result["changes"][row["id"]]={**row,"deleted":True}
    elif op=="restore":
        for row in chosen:
            if row["source_sample"] is None:
                result["changes"][row["id"]]={**row,"deleted":True}
            else:
                result["changes"][row["id"]]=dict(sample_index=row["source_sample"],
                    class_code={1:"N",2:"S",3:"V",34:"X"}.get(row["source_group"],"OTHER"),deleted=False)
    elif op=="move":
        if len(chosen)!=1:
            raise ValueError("每次只移动一个 QRS")
        row=chosen[0]
        target=integer(payload.get("target_sample"),"目标采样点",0,int(duration*SAMPLE_RATE)-1)
        result["changes"][row["id"]]={**row,"sample_index":target}
    elif op=="insert":
        samples=payload.get("positions",[])
        if not isinstance(samples,list) or not 1<=len(samples)<=500:
            raise ValueError("每次添加 1–500 个不重复的 QRS 位置")
        for sample in samples:integer(sample,"新增采样点",0,int(duration*SAMPLE_RATE)-1)
        if len(set(samples))!=len(samples):raise ValueError("新增位置不能重复")
        code=payload.get("class_code","OTHER")
        if code not in TYPES or TYPES[code]["kind"] not in ("beat",):
            raise ValueError("添加 QRS 必须选择心搏类型")
        for sample in samples:
            integer(sample,"新增采样点",0,int(duration*SAMPLE_RATE)-1)
            if any(r["sample_index"]==sample for r in rows+markers):raise ValueError("目标位置已有标记")
            key=f"i:{sample}"
            suffix=1
            while key in result["changes"]:
                key=f"i:{sample}:{suffix}"
                suffix+=1
            inserted_ids.add(key)
            result["changes"][key]=dict(id=key,sample_index=sample,class_code=code,source_sample=None,source_group=None,deleted=False)
        chosen=samples
    elif op=="longest":
        if len(chosen)!=1 or not chosen[0]["rr_ms"]:
            raise ValueError("请选择具有前一心搏的 RR 间期终点")
        result["longest_id"]=chosen[0]["id"]
    else:
        raise ValueError("不支持的编辑命令")
    # Prevent crossing/duplicating labels. 100 ms is an editing guard, not a clinical definition.
    final,_=materialize(source,result,legacy)
    if op in ("move","insert","restore"):
        valid=[r for r in final if r["group"]!=34]
        affected_ids=inserted_ids if op=="insert" else {r["id"] for r in chosen}
        if any(b["sample_index"]-a["sample_index"]<20 and (a["id"] in affected_ids or b["id"] in affected_ids) for a,b in zip(valid,valid[1:])):
            raise ValueError("目标距另一 QRS 不足 100 ms，或存在重复位置")
    if result["longest_id"] and not any(r["id"]==result["longest_id"] for r in final):
        result["longest_id"]=None
    return result,len(chosen)


def propose_qrs(values, start_sample, existing, options):
    """Derivative-energy local candidates + MAD threshold; explicit confirmation required."""
    opts=settings(options);n=len(values)
    if n<40 or any(not math.isfinite(v) for v in values):
        return []
    derivative=[0]+[float(values[i])-float(values[i-1]) for i in range(1,n)]
    energy=[x*x for x in derivative];width=16;total=0;smoothed=[]
    for i,value in enumerate(energy):
        total+=value
        if i>=width:total-=energy[i-width]
        smoothed.append(total/min(i+1,width))
    median=statistics.median(smoothed);mad=statistics.median(abs(x-median) for x in smoothed)
    threshold=median+opts["sensitivity"]*max(mad,median*.15,1e-6)
    candidates=[]
    for i in range(20,n-20):
        if smoothed[i]>threshold and smoothed[i]>=smoothed[i-1] and smoothed[i]>smoothed[i+1]:
            lo=max(0,i-20);hi=min(n,i+5)
            base=statistics.median(values[lo:hi])
            peak=max(range(lo,hi),key=lambda j:abs(values[j]-base))
            candidates.append((smoothed[i],peak))
    gap=round(opts["refractory_ms"]*SAMPLE_RATE/1000);selected=[];existing=sorted(existing)
    for strength,peak in sorted(candidates,reverse=True):
        absolute=start_sample+peak
        index=bisect_left(existing,absolute)
        if all(abs(absolute-x)>=gap for x in existing[max(0,index-1):index+1]) and all(abs(peak-x[1])>=gap for x in selected):
            selected.append((strength,peak))
    return [dict(sample_index=start_sample+peak,time_s=(start_sample+peak)/SAMPLE_RATE,
                 score=round(strength/max(threshold,1e-6),2),label="QRS候选，未分类")
            for strength,peak in sorted(selected,key=lambda x:x[1])][:500]


def edited_hrv(feed):
    opts=feed.document["settings"];nn=[]
    for i in range(1,len(feed.beats)):
        a,b=feed.beats[i-1:i+1]
        if a["class_code"]==b["class_code"]=="N" and opts["nn_min"]<=b["rr_ms"]<=opts["nn_max"]:
            nn.append((i,b["sample_index"],b["rr_ms"]))
    values=[x[2] for x in nn]
    if len(values)<3:return dict(nn_count=len(values),method="修订版严格相邻 N-N；样本不足")
    # Never subtract NN intervals separated by an ectopic beat or excluded gap.
    diffs=[b[2]-a[2] for a,b in zip(nn,nn[1:]) if b[0]==a[0]+1]
    blocks={}
    for _,sample,value in nn:
        key=int(sample//60000)
        if (key+1)*300<=feed.duration:blocks.setdefault(key,[]).append(value)
    groups=[g for g in blocks.values() if len(g)>=30]
    means=[statistics.mean(g) for g in groups];hist=Counter(math.floor(x/7.8125) for x in values)
    return dict(nn_count=len(values),successive_nn_pairs=len(diffs),mean_nn_ms=round(statistics.mean(values),2),
        sdnn_ms=round(statistics.stdev(values),2),sdann_ms=round(statistics.stdev(means),2) if len(means)>1 else None,
        sdnn_index_ms=round(statistics.mean(statistics.stdev(g) for g in groups),2) if groups else None,
        rmssd_ms=round(math.sqrt(statistics.mean(x*x for x in diffs)),2) if diffs else None,
        pnn50_pct=round(100*sum(abs(x)>50 for x in diffs)/len(diffs),2) if diffs else None,
        triangular_index=round(len(values)/max(hist.values()),2),
        method="修订版：连续 N-N，差分不跨异位/伪差；完整5分钟块且至少30个NN；7.8125ms箱宽。短记录仅供研究。",
        completed_five_minute_blocks=len(groups))


def edited_events(feed, event_type="all", offset=0, limit=200):
    """Independent beat-type and interval candidates; not episode diagnosis."""
    events=[];counts=Counter();opts=feed.document["settings"]
    for row in feed.beats:
        kinds=[];code=row["class_code"];rr=row["rr_ms"]
        if row["group"]==34:kinds.append(("noise","伪差 / 待确认","low"))
        elif row["kind"]=="rhythm":
            kinds.append(("AF" if code in ("A","M") else "AFL","人工逐搏节律："+row["name"],"medium"))
        elif row["group"] in (2,3):
            kinds.append(("S" if row["group"]==2 else "V",row["name"]+"（待复核）","medium"))
        elif code!="N":kinds.append(("manual","人工分类："+row["name"],"low"))
        if row["group"]!=34 and rr:
            if rr>=opts["pause"]*1000:kinds.append(("pause",f"长 RR {rr/1000:.3f} s","high"))
            if row["hr"]>=opts["tachy"]:kinds.append(("tachy",f"快心率候选 {row['hr']} bpm","medium"))
            elif row["hr"]<=opts["brady"]:kinds.append(("brady",f"慢心率候选 {row['hr']} bpm","medium"))
        for kind,label,severity in kinds:
            counts[kind]+=1
            if event_type in ("all",kind):events.append({**row,"type":kind,"label":label,"severity":severity,"review_status":"待复核"})
    return dict(summary=dict(counts),total=len(events),offset=offset,limit=limit,items=events[offset:offset+limit],
                analysis="edited",definition="独立逐搏分类及 RR 阈值候选；不是发作次数或自动疾病诊断")


class BeatEditorStore:
    def __init__(self, storage):
        self.storage=storage
        with storage.connect() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS beat_edit_documents
                (case_id TEXT PRIMARY KEY, revision INTEGER NOT NULL, document TEXT NOT NULL,
                 undo TEXT NOT NULL, redo TEXT NOT NULL)""")
            db.execute("""CREATE TABLE IF NOT EXISTS beat_edit_template_refs
                (template_id INTEGER PRIMARY KEY, case_id TEXT NOT NULL, beat_ids TEXT NOT NULL)""")

    def read(self, case_id, db=None):
        if db is None:
            with self.storage.connect() as connection:return self.read(case_id,connection)
        row=db.execute("SELECT * FROM beat_edit_documents WHERE case_id=?",(case_id,)).fetchone()
        return dict(revision=row["revision"],document=json.loads(row["document"]),undo=json.loads(row["undo"]),redo=json.loads(row["redo"])) if row else dict(revision=0,document=blank(),undo=[],redo=[])

    def commit(self, case_id, revision, actor, transform, action):
        integer(revision,"编辑版本")
        with self.storage.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            value=self.read(case_id,db)
            if value["revision"]!=revision:raise ValueError("编辑版本已变化，请刷新预览")
            before=copy.deepcopy(value["document"])
            if action in ("undo","redo"):
                origin=value[action]
                if not origin:raise ValueError("没有可撤销／重做的操作")
                value["redo" if action=="undo" else "undo"].append(before)
                value["document"]=origin.pop()
            else:
                value["document"]=transform(before)
                value["undo"]=(value["undo"]+[before])[-20:];value["redo"]=[]
            # Bound large batch histories while keeping the latest undo available.
            for stack in ("undo","redo"):
                while len(value[stack])>1 and len(json.dumps(value[stack]))>8_000_000:
                    value[stack].pop(0)
            value["revision"]+=1
            db.execute("""INSERT INTO beat_edit_documents VALUES(?,?,?,?,?) ON CONFLICT(case_id) DO UPDATE SET
                revision=excluded.revision,document=excluded.document,undo=excluded.undo,redo=excluded.redo""",
                (case_id,value["revision"],json.dumps(value["document"],ensure_ascii=False),json.dumps(value["undo"]),json.dumps(value["redo"])))
            self.storage.invalidate_review(db,case_id,"beat_override.editor")
            db.execute("INSERT INTO audit_log(case_id,actor,action,detail,created_at) VALUES(?,?,?,?,?)",
                (case_id,actor,"beat_editor."+action,f"revision={value['revision']}",datetime.now(timezone.utc).isoformat()))
        return value
