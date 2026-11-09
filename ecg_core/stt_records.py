"""ST/T review decisions and report use, independent of abnormal-event counts."""
from __future__ import annotations
import copy
import json
import math
import struct
from hashlib import sha256

ST_KINDS = ('ST', 'ST_REVIEW_NOTE')
ST_RESULTS = ('st_depression','st_elevation')
T_RESULTS = ('t_change','t_wave_inversion','t_persistent_inversion','t_low_flat','t_biphasic')
RESULTS = (*ST_RESULTS,*T_RESULTS,'nonspecific','no_change','artifact','indeterminate')
ABNORMAL = (*ST_RESULTS,*T_RESULTS,'nonspecific')
SCHEMA = 'stt-review-record-v2'
METHOD = 'stt-hospital-review-v3'
HISTORICAL_METHODS = ('stt-hospital-review-v2',)
RHYTHM_POLICY = 'independent_of_AF_AFL_reviews'
RANGE_PROFILE = 'raw-200hz-fixed16s-st-perbeat-morphology-v3'
HISTORICAL_RANGE_PROFILES = ('raw-200hz-fixed16s-st-perbeat-mean-v2',)
LEGACY_RANGE_PROFILE = 'raw-200hz-fixed16s-st-perbeat-mean-v1'


def digest(value):
    def canonical(item):
        if type(item) is float:
            if not math.isfinite(item):raise ValueError('ST-T依据不接受非有限数值')
            if item.is_integer() and abs(item)<=9007199254740991:return int(item)
            return ['float64',struct.pack('>d',item).hex()]
        if type(item) is int and abs(item)>9007199254740991:return ['integer',str(item)]
        if isinstance(item,dict):return ['object',[[k,canonical(item[k])] for k in sorted(item)]]
        if isinstance(item,(tuple,list)):return ['array',[canonical(v) for v in item]]
        return item
    return sha256(json.dumps(canonical(value),sort_keys=True,ensure_ascii=False,separators=(',',':'),allow_nan=False).encode()).hexdigest()


def rhythm_exclusions(annotations):
    """Authoritative AF/AFL masks used by range statistics, without user prose."""
    rows=[]
    for annotation in annotations:
        d=annotation.get('details') or {}
        if d.get('kind') not in ('AF','AFL') or d.get('status')=='excluded':continue
        start,end=annotation.get('sample_index'),d.get('end_sample')
        if type(start) is not int or type(end) is not int or start<0 or end<start:raise ValueError('节律排除区间须使用完整原始样本范围')
        rows.append(dict(start_sample=start,end_sample=end+1,reason='rhythm_'+d['kind'],origin='stored_annotation',review_status=str(d.get('status','unclassified'))))
    return sorted(rows,key=lambda r:(r['start_sample'],r['end_sample'],r['reason'],r['review_status']))


def rhythm_scope_digest(annotations,first,end):
    # Fixed-16s J/quality blocks and their source read halos affect the mean.
    # A rhythm edit outside those supports does not invalidate this record.
    return mask_scope_digest(rhythm_exclusions(annotations),first,end)


def mask_scope_digest(masks,first,end):
    low=(first//3200)*3200-40;high=((end+3199)//3200)*3200+120
    rows=[{key:r[key] for key in ('start_sample','end_sample','reason','origin','review_status') if key in r} for r in masks if r['start_sample']<high and r['end_sample']>low]
    return digest(sorted(rows,key=lambda r:(r['start_sample'],r['end_sample'],r['reason'],r.get('review_status',''))))


def result_code(details):
    if details.get('result_code') in RESULTS:return details['result_code']
    text=str(details.get('finding',''))
    if '未见' in text:return 'no_change'
    if '伪差' in text or '体位' in text:return 'artifact'
    if '无法' in text:return 'indeterminate'
    if '压低' in text:return 'st_depression'
    if '抬高' in text:return 'st_elevation'
    if 'T 波' in text or 'T波' in text or (details.get('stt_event_evidence') or {}).get('kind') in T_RESULTS:return 't_change'
    return 'nonspecific' if details.get('status')=='confirmed' else 'indeterminate'



def result_family(code):
    return 'ST' if code in ST_RESULTS else 'T' if code in T_RESULTS else 'NOTE'


def normalized_findings(details, first, end, leads):
    """Validate doctor findings; end samples use the parent's inclusive contract.

    Evidence and measurements are never accepted inside a client finding.
    A parent identity owns all child findings and all report uses.
    """
    raw=details.get('findings')
    if raw is None:
        return [dict(result_code=result_code(details),leads=list(leads),start_sample=first,end_sample=end)]
    if not isinstance(raw,list) or not 1<=len(raw)<=48:raise ValueError('ST-T复核须有1–48项实际结论')
    result=[];seen=set()
    for child in raw:
        if not isinstance(child,dict) or set(child)-{'result_code','leads','start_sample','end_sample'}:raise ValueError('ST-T子项仅接受结论、导联和范围，测量证据由服务器生成')
        code=child.get('result_code');names=child.get('leads',leads)
        a,b=child.get('start_sample',first),child.get('end_sample',end)
        if code not in RESULTS:raise ValueError('ST-T子项结论无效')
        if not isinstance(names,list) or not names or any(not isinstance(x,str) or x not in leads for x in names) or len(set(names))!=len(names):raise ValueError('子项导联须为本次实际复核导联')
        if type(a) is not int or type(b) is not int or not first<=a<=b<=end:raise ValueError('ST-T子项范围须位于完整复核范围内')
        key=(code,tuple(sorted(names)),a,b)
        if key in seen:raise ValueError('ST-T复核子项重复')
        seen.add(key);result.append(dict(result_code=code,leads=list(names),start_sample=a,end_sample=b))
    if details.get('result_code') not in {r['result_code'] for r in result}:raise ValueError('主要结论须包含在本次复核子项内')
    return result


def evidence_findings(event):
    """Expose stored child proofs without changing historical records."""
    proof=event.get('stt_event_evidence') or {}
    if isinstance(proof.get('findings'),list):return proof['findings']
    return [proof] if proof else []

def protocol(raw=None, *, extent='point'):
    raw=raw or {}
    if not isinstance(raw,dict):raise ValueError('ST-T 测量协议须为对象')
    ms=raw.get('measurement_ms',60)
    if type(ms) is not int or ms not in (0,60,80):raise ValueError('ST-T 测量点须为 J、ST60 或 ST80')
    mode=raw.get('extent',extent)
    if mode not in ('point','whole'):raise ValueError('ST-T 测量作用范围无效')
    baseline=raw.get('baseline_method','pre_qrs_stable')
    if baseline not in ('pre_qrs_stable','manual_iso_point'):raise ValueError('ST-T 基线方法无效')
    if raw.get('method_version',METHOD)!=METHOD or raw.get('rhythm_policy',RHYTHM_POLICY)!=RHYTHM_POLICY:
        raise ValueError('ST-T测量方法已变化，请按当前独立分析方法重新核对')
    return dict(method_version=METHOD,measurement_ms=ms,extent=mode,baseline_method=baseline,
                units='source_device_units',calibration_verified=False,rhythm_policy=RHYTHM_POLICY)


def stored_protocol(raw):
    """Validate geometry without relabelling a historical method or its fields."""
    if not isinstance(raw,dict):return None
    try:protocol({**raw,'method_version':METHOD,'rhythm_policy':RHYTHM_POLICY})
    except (TypeError,ValueError):return None
    return copy.deepcopy(raw)


def current_method(details):
    """An old mask-based record remains readable, but is never silently re-signed."""
    evidence=details.get('stt_event_evidence') or {}
    for raw in (details.get('measurement_protocol'),evidence.get('measurement_protocol')):
        if raw is not None and (stored_protocol(raw) is None or raw.get('method_version') not in (METHOD,*HISTORICAL_METHODS)
                                or raw.get('rhythm_policy')!=RHYTHM_POLICY):return False
    if evidence and (evidence.get('rhythm_policy')!=RHYTHM_POLICY or 'rhythm_exclusions_digest' in evidence):return False
    profiles=[(details.get('range_statistics') or {}).get('method_profile'),
              (evidence.get('measurement_protocol') or {}).get('range_profile')]
    for profile in profiles:
        if profile is not None and (not isinstance(profile,dict) or profile.get('id') not in (RANGE_PROFILE,*HISTORICAL_RANGE_PROFILES)
                                    or profile.get('rhythm_policy')!=RHYTHM_POLICY):return False
    return not details.get('reviewed') or isinstance(details.get('measurement_protocol'),dict)


def status_for(code):
    return 'confirmed' if code in ABNORMAL else 'excluded' if code in ('no_change','artifact') else 'pending'


def saved_protocol(details,evidence):
    if isinstance(evidence.get('measurement_protocol'),dict):return stored_protocol(evidence['measurement_protocol'])
    if isinstance(details.get('measurement_protocol'),dict):return stored_protocol(details['measurement_protocol'])
    profile=(details.get('range_statistics') or {}).get('method_profile')
    if not isinstance(profile,dict) or type(profile.get('measurement_ms')) is not int or profile['measurement_ms'] not in (0,60,80):return None
    # Historical signed means have their own declared method. Neither a
    # default ST60 point nor the new review method may replace that evidence.
    return dict(method_version=profile.get('id'),measurement_ms=profile['measurement_ms'],extent='whole',
        baseline_method='pre_qrs_stable' if profile.get('id') in (LEGACY_RANGE_PROFILE,RANGE_PROFILE,*HISTORICAL_RANGE_PROFILES) else None,
        units=profile.get('units'),calibration_verified=profile.get('calibration_verified') is True,
        range_profile=copy.deepcopy(profile))


def review_metadata(annotation, *, basis_version=None, stale=False):
    d=annotation.get('details') or {};code=result_code(d)
    explicit=d.get('reviewed') is True
    bound=bool(d.get('review_scope') or (d.get('stt_event_evidence') or {}).get('scope'))
    state='reviewed' if explicit or bound and d.get('status') in ('confirmed','excluded') else 'unreviewed'
    if state=='reviewed' and not current_method(d):state='stale'
    if stale:state='stale'
    first=annotation['sample_index'];end=int(d.get('end_sample',first))+1
    findings=normalized_findings(d,first,end-1,d.get('review_leads') or (d.get('stt_event_evidence') or {}).get('leads') or ([annotation['lead']] if annotation.get('lead') not in (None,'','全部') else []))
    codes=list(dict.fromkeys(r['result_code'] for r in findings))
    families={result_family(c) for c in codes}-{"NOTE"}
    family='ST_T' if len(families)>1 else next(iter(families),'NOTE')
    group=family if state=='reviewed' and any(c in ABNORMAL for c in codes) and family!='NOTE' else 'ST_NOTE' if state=='reviewed' else 'pending'
    evidence=d.get('stt_event_evidence') or {}
    extent=d.get('review_extent','whole' if evidence else 'point')
    actual=saved_protocol(d,evidence)
    eligible=state=='reviewed'
    child_proofs=evidence.get('findings') if isinstance(evidence.get('findings'),list) else [evidence]
    table=eligible and extent=='whole' and any(r.get('kind') in (*ST_RESULTS,*T_RESULTS) and r.get('result_code',code) in (*ST_RESULTS,*T_RESULTS) and (r.get('end_s',0)-r.get('start_s',0))>=60-1e-9 for r in child_proofs if isinstance(r,dict))
    return dict(schema_version=SCHEMA,record_id='annotation:'+str(annotation['id']),event_id='annotation:'+str(annotation['id']),
        annotation_id=annotation['id'],record_version=int(d.get('record_version',1)),review_state=state,
        result_code=code,result_codes=codes,findings=copy.deepcopy(findings),result_kind=family,report_group=group,status=d.get('status','pending'),review_extent=extent,
        range=dict(start_sample=first,end_sample=end,start_s=first/200,end_s=end/200,duration_s=(end-first)/200),
        basis_version=basis_version,measurement_protocol=copy.deepcopy(actual),
        point_measurement_protocol=stored_protocol(d.get('measurement_protocol')),
        report_eligibility=dict(table=table,text=eligible,strip=eligible),
        report_use=dict(table=False,text=False,strip=False),source_scope=copy.deepcopy(d.get('review_scope') or evidence.get('scope')),
        finding=d.get('finding',annotation.get('label','')),note=annotation.get('note',''),physician_note=d.get('physician_note'),
        leads=copy.deepcopy(d.get('review_leads') or evidence.get('leads') or ([annotation['lead']] if annotation.get('lead') not in (None,'','全部') else [])),
        legacy=not explicit)


def decorate_event(event, annotation, beat_version):
    d=annotation.get('details') or {}
    scope=d.get('review_scope') or (d.get('stt_event_evidence') or {}).get('scope') or {}
    # Global review revision and unrelated annotations never change this record's identity.
    material=[annotation['id'],annotation['sample_index'],d,annotation.get('lead',''),annotation.get('note',''),annotation.get('label','')]
    material=copy.deepcopy(material)
    for key in ('review_scope','stt_candidate_scope'):
        if isinstance(material[2].get(key),dict):material[2][key].pop('analysis_revision',None)
    proof=material[2].get('stt_event_evidence')
    if isinstance(proof,dict) and isinstance(proof.get('scope'),dict):proof['scope'].pop('analysis_revision',None)
    bv=beat_version+'-stt-record-v1-'+digest(material)[:24]
    receipt=review_metadata(annotation,basis_version=bv)
    event.update(basis_version=bv,stt_review_state=receipt['review_state'],stt_result_code=receipt['result_code'],
        stt_result_kind=receipt['result_kind'],stt_report_group=receipt['report_group'],
        stt_record_version=receipt['record_version'],stt_report_eligibility=receipt['report_eligibility'],
        stt_review_receipt=receipt,stt_source_scope=scope,stt_continuous=receipt['report_eligibility']['table'])
    event['stt_physician_note']=d.get('physician_note',annotation.get('note',''))
    if d.get('withdrawn_report_settings'):event['retained_settings']=copy.deepcopy(d['withdrawn_report_settings'][0])
    event['diagnosis_status']='confirmed' if receipt['review_state']=='reviewed' and any(c in ABNORMAL for c in receipt['result_codes']) else 'pending'
    return event


def mark_stale(event):
    event['diagnosis_status']='pending';event['stt_evidence_stale']=True;event['stt_review_state']='stale';event['stt_report_group']='pending'
    event['stt_report_eligibility']=dict(table=False,text=False,strip=False)
    event['stt_review_receipt'].update(review_state='stale',report_group='pending',report_eligibility=event['stt_report_eligibility'])


def normalized_uses(raw):
    if not isinstance(raw,list) or len(raw)>2000:raise ValueError('ST-T 报告用途须为记录列表')
    result=[];seen=set()
    for row in raw:
        if not isinstance(row,dict) or not all(isinstance(row.get(k),str) and row[k] for k in ('event_id','basis_version')):raise ValueError('ST-T 报告用途缺少记录依据')
        if any(type(row.get(k,False)) is not bool for k in ('table','text','strip')):raise ValueError('ST-T 报告用途须为布尔值')
        if row['event_id'] in seen:raise ValueError('ST-T 报告用途记录重复')
        seen.add(row['event_id']);result.append({k:row.get(k,False) for k in ('event_id','basis_version','table','text','strip')})
    return result


def use_for(composition,event):
    if 'stt_report_use' in composition:
        return next((dict(row) for row in composition['stt_report_use'] if row['event_id']==event['event_id']),
                    dict(event_id=event['event_id'],basis_version=event['basis_version'],table=False,text=False,strip=False))
    # Read-only compatibility projection. Never manufacture an explicit selection on GET.
    pick=next((s for s in composition.get('selected_events',[]) if s['event_id']==event['event_id']),None)
    pages=composition.get('included_pages',['summary','hourly','event_strips'])
    return dict(event_id=event['event_id'],basis_version=pick['basis_version'] if pick else event['basis_version'],
        table=bool(pick and 'st_events' in pages and event.get('stt_report_eligibility',{}).get('table')),
        text=bool(pick and pick.get('referenced_in_report')),strip=bool(pick and pick.get('print_enabled',True) and 'event_strips' in pages))


def interval_union(intervals):
    merged=[]
    for a,b in sorted(intervals):
        if b<=a:continue
        if merged and a<=merged[-1][1]:merged[-1][1]=max(b,merged[-1][1])
        else:merged.append([a,b])
    return merged


def time_groups(events):
    groups=[]
    for e in sorted(events,key=lambda x:(x['start_s'],x['end_s'],x.get('lead',''))):
        compatible=next((g for g in reversed(groups) if e['start_s']<g['end_s'] and e.get('measurement_protocol')==g['measurement_protocol']),None)
        if compatible is None:
            compatible=dict(start_s=e['start_s'],end_s=e['end_s'],events=[],measurement_protocol=e.get('measurement_protocol'));groups.append(compatible)
        compatible['events'].append(e);compatible['end_s']=max(compatible['end_s'],e['end_s'])
    result=[]
    for g in groups:
        children=g.pop('events');intervals=interval_union([(e['start_s'],e['end_s']) for e in children]);ids=sorted({e.get('row_id',e['event_id']) for e in children})
        result.append({**g,'group_id':'stt-time-group:'+digest([ids,g['measurement_protocol']])[:24],
            'child_event_ids':ids,'record_event_ids':sorted({e['event_id'] for e in children}),'leads':sorted({e['lead'] for e in children if e.get('lead')}),
            'directions':sorted({e.get('kind') for e in children}), 'span_s':g['end_s']-g['start_s'],
            'union_duration_s':sum(b-a for a,b in intervals),'support_intervals':intervals})
    return result
