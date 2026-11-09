"""Complete occurrence index shared by diagnostic browsing and report selection.

Pattern flags describe sequences, not new disease diagnoses. Source files stay read-only.
"""
from __future__ import annotations
import json
import copy
import math
import statistics
from .report_layout import strip_settings, resolve_strip, valid_rr_pairs
from .rr_quality import nn_intervals, interval_mask, annotation_exclusions, consistent_rate
from collections import Counter
from datetime import datetime, timedelta

CATEGORIES = [('fastest','最快心率'),('slowest','最慢心率'),('S','房早事件'),('V','室早事件'),('pause','长 RR 候选'),('rr_candidate','自选 RR 候选'),('rate','心率异常'),('AF','房颤事件'),('ST','ST段事件'),('other','其他事件')]
REPORT_CATEGORIES = [(('rr_interval', 'RR 间期') if key == 'pause' else (key, label)) for key, label in CATEGORIES if key != 'rr_candidate']
PATTERNS = [('all','全部'),('single','单发'),('couplet','成对'),('triplet','连续三发'),('run','连续多发'),('tachycardia','心动过速'),('bigeminy','二联律'),('nnp','三联律（NNP）'),('npp','三联律（NPP）'),('quadrigeminy','四联律')]
EXTREME_CANDIDATE_LIMIT = 200
PERIODIC_VERSION = 'periodic-v2'
DATA_VERSION_SUFFIX = '-rr-quality-v3-'+PERIODIC_VERSION+'-af-end-v1-status-v2-no-artifact-v1'


def repeating_spans(codes, cycle):
    """Phase-independent, earliest maximal non-overlapping periodic spans.

    Require two complete cycles before extending the matching tail. These are
    sequence descriptors, not rhythm diagnoses. All non-cycle labels break the
    pattern; no filtering/compression of the timeline is allowed. O(n) for the
    fixed periods (2–4) used here.
    """
    length = len(cycle)
    if not length:
        raise ValueError('A repeating cycle must not be empty')
    rotations = {tuple(cycle[k:]+cycle[:k]) for k in range(length)}
    i = 0
    while i+2*length <= len(codes):
        unit = tuple(codes[i:i+length])
        if unit in rotations and tuple(codes[i+length:i+2*length]) == unit:
            end = i+2*length
            while end < len(codes) and codes[end] == codes[end-length]:
                end += 1
            yield i, end
            i = end
        else:
            i += 1

def fingerprint(text):
    value=2166136261
    # ASCII JSON gives Python and JavaScript identical bytes, including Chinese labels.
    for char in text:
        value=((value ^ ord(char))*16777619)&0xffffffff
    return f'{value:08x}'

def encode(value):
    def integral(v):
        if isinstance(v,float) and v.is_integer():return int(v)
        if isinstance(v,(list,tuple)):return [integral(x) for x in v]
        if isinstance(v,dict):return {k:integral(x) for k,x in v.items()}
        return v
    return json.dumps(integral(value),ensure_ascii=True,separators=(',',':'))

def build_index(feed, templates=(), annotations=(), review=None):
    rows=feed.beats; markers=feed.markers; opts=feed.document['settings']; review=review or {}
    bv=fingerprint('|'.join(f"{r['id']}:{r['sample_index']}:{r['class_code']}" for r in rows+markers)+'|'+encode([[k,opts[k]] for k in sorted(opts)]))
    from .stt_records import ST_KINDS, decorate_event
    findings=[a for a in annotations if a.get('details',{}).get('kind') in (*ST_KINDS,'AT','VT','AF','AFL','STRIP')]
    av=fingerprint(encode([[a['id'],a['sample_index'],a.get('details')] for a in findings]))
    basis={key:bv for key,_ in CATEGORIES}
    excluded=list(getattr(feed,'excluded_rhythm_intervals',()))+annotation_exclusions(annotations)
    for key in ('fastest','slowest'):
        basis[key]=bv+'-rr-quality-v3-nn-'+fingerprint(encode(excluded))
    # Report long-RR screening has a fixed denominator, independent of the
    # editor's configurable alert threshold. Changing this contract invalidates
    # old pause selections, but leaves other evidence IDs and bases untouched.
    basis['pause']=bv+'-rr-gt2500-v4-r-peaks'
    basis['rate']=bv+'-rr-quality-v3'
    for key,kind in [('ST','ST'),('S','AT'),('V','VT'),('AF','AF'),('other','STRIP')]:
        basis[key]=bv+'-'+fingerprint(encode([[a['id'],a['sample_index'],a['details']] for a in findings if a['details']['kind']==kind or (key=='AF' and a['details']['kind']=='AFL')]))
    basis['AF'] += '-episode-status-v2-inclusive-end-v1'
    for key in ('S','V'):
        basis[key]+='-'+PERIODIC_VERSION
    by_template={}
    for t in templates:
        for s in t.get('sample_indices',[]): by_template.setdefault(s,[]).append({'id':str(t['id']),'name':t['name']})
    events=[]
    def make(category,subtype,label,targets,segment=None,pattern=False,identifier=None):
        segment=segment or targets
        if not segment:return None
        first,last=segment[0],segment[-1]; start,end=first['sample_index'],last['sample_index']
        names={t['id']:t for r in targets for t in by_template.get(r['sample_index'],[])}
        item=dict(event_id=identifier or f"{category}:{subtype}:{first['id']}:{last['id']}",category=category,subtype=subtype,label=label,
                  sample_index=start,start_sample=start,end_sample=end,time_s=start/200,end_s=end/200,
                  target_samples=[r['sample_index'] for r in targets],beat_count=len(targets),templates=list(names.values()),
                  hr=first.get('hr'),rr_ms=first.get('rr_ms'),basis_version=basis.get(category,bv),pattern_only=pattern,
                  diagnosis_status='confirmed' if review.get('steps',{}).get('stt' if category=='ST' else 'edit',{}).get('status')=='done' else 'pending')
        events.append(item);return item
    codes=[r['class_code'] for r in rows]
    for code in ('S','V'):
        label='房早' if code=='S' else '室早'; i=0
        while i<len(rows):
            if rows[i]['class_code']!=code:i+=1;continue
            j=i+1
            while j<len(rows) and rows[j]['class_code']==code:j+=1
            count=j-i; kind='single' if count==1 else 'couplet' if count==2 else 'triplet' if count==3 else 'run'
            title={'single':'单发','couplet':'成对','triplet':'连续三发','run':'连续多发'}[kind]+label
            make(code,kind,title,rows[i:j]);i=j
        for kind,cycle in [('bigeminy',['N',code]),('nnp',['N','N',code]),('npp',['N',code,code]),('quadrigeminy',['N','N','N',code])]:
            for i,j in repeating_spans(codes,cycle):
                segment=rows[i:j]
                make(code,kind,label+dict(PATTERNS)[kind],[r for r in segment if r['class_code']==code],segment,True)
    pairs=valid_rr_pairs(rows,feed.duration)
    valid=[end for _,end in pairs]
    rate_ids={id(r) for r in valid if consistent_rate(r)}
    nn_valid=interval_mask(rows,excluded)
    nn=[b for i,b in enumerate(rows) if nn_valid[i] and rows[i-1]['class_code']==b['class_code']=='N' and opts['nn_min']<=b['rr_ms']<=opts['nn_max']]
    # IDs remain stable; the versioned basis requires old selections to be reviewed.
    # Do not manufacture candidates or suppress nearby beats.
    for name,subset in [('RR',valid),('NN',nn)]:
        usable=[r for r in subset if id(r) in rate_ids]
        for key,direction in [('fastest',1),('slowest',-1)]:
            ranked=sorted(usable,key=lambda r:(direction*r['rr_ms'],r['sample_index'],r['id']))[:EXTREME_CANDIDATE_LIMIT]
            for rank,r in enumerate(ranked,1):
                item=make(key,name,name+' '+dict(CATEGORIES)[key]+f" {math.floor(r['hr']+0.5)} bpm",[r])
                item['candidate_rank']=rank
    for previous,r in pairs:
        if r['rr_ms']>2500:
            item=make('pause','pause',f"长 RR {r['rr_ms']/1000:.3f} s",[r])
            item.update(rr_start_sample=previous['sample_index'],rr_end_sample=r['sample_index'])
    # Once the episode review is saved, its intervals supersede source rhythm runs.
    rhythm_authoritative = any(a.get('details',{}).get('rhythm_authoritative') for a in annotations)
    # Contiguous threshold/rhythm runs; no joining across intervening beats or noise.
    for category,subtype,label,predicate in [
        ('rate','tachy','快心率',lambda r:id(r) in rate_ids and r['hr']>=opts['tachy']),
        ('rate','brady','慢心率',lambda r:id(r) in rate_ids and r['hr']<=opts['brady']),
        ('AF','AF','房颤',lambda r:r['class_code'] in ('A','M') and not rhythm_authoritative),
        ('AF','AFL','房扑',lambda r:r['class_code'] in ('C','H') and not rhythm_authoritative)]:
        i=0
        while i<len(rows):
            if not predicate(rows[i]):i+=1;continue
            j=i+1
            while j<len(rows) and predicate(rows[j]):j+=1
            item = make(category,subtype,label,rows[i:j])
            if category == 'AF':
                item['end_s'] = rows[j]['sample_index']/200 if j < len(rows) else feed.duration
                item['rhythm_episode_id'] = 'beat-' + str(rows[i]['sample_index'])
                item['rhythm_status'] = 'pending'  # Beat labels do not confirm episode bounds.
                item['diagnosis_status'] = 'pending'  # Whole-editor approval cannot confirm a source run.
            i=j
    for r in rows+markers:
        if r['class_code'] not in ('N','S','V','A','M','C','H','X'):
            make('other',r['class_code'],r.get('name',r['class_code']),[r])
    def kind_not_rhythm(d):return d['kind'] not in ('AF','AFL')
    for a in findings:
        d=a['details']
        if not rhythm_authoritative and d['kind'] in ('AF','AFL') and d.get('status')=='pending' and any(b['details']['kind']==d['kind'] and b['details'].get('status')=='confirmed' and b['sample_index']==a['sample_index'] and b['details'].get('end_sample')==d.get('end_sample') for b in findings):continue
        st_record=d['kind'] in ST_KINDS
        if not st_record and d.get('status')!='confirmed' and kind_not_rhythm(d):continue
        if not st_record and d.get('status')=='excluded':continue
        kind=d['kind'];cat='AF' if kind in ('AF','AFL') else 'ST' if st_record else 'S' if kind=='AT' else 'other' if kind=='STRIP' else 'V'
        start=a['sample_index'];end=d.get('end_sample',start)
        target=[r for r in rows if start<=r['sample_index']<=end and (st_record or kind in ('AF','AFL','STRIP') or r['class_code']==cat)]
        segment=[dict(id=f"a:{a['id']}:start",sample_index=start),dict(id=f"a:{a['id']}:end",sample_index=end)]
        default_label={'ST':'ST 改变','ST_REVIEW_NOTE':'ST-T 复核记录','AF':'房颤','AFL':'房扑','AT':'房速','VT':'室速','STRIP':'人工图条'}[kind]
        item=make(cat,'ST' if st_record else kind if kind in ('AF','AFL','STRIP') else 'tachycardia',d.get('finding') or default_label,target,segment,not st_record and kind not in ('AF','AFL','STRIP'),f"annotation:{a['id']}")
        if cat == 'AF':
            item['end_s'] = (end+1)/200  # Stored end_sample remains inclusive.
            item['rhythm_status'] = d.get('status', 'pending')
            annotation_id = str(a['id'])
            item['rhythm_episode_id'] = annotation_id[3:] if annotation_id.startswith('af:') else 'source-' + annotation_id
        if d.get('status')!='confirmed':item['diagnosis_status']='pending'
        item['lead']=a.get('lead','全部');item['note']=a.get('note','')
        if st_record:
            item['diagnosis_status']='confirmed' if d.get('status')=='confirmed' else 'pending'
            item['end_s']=(end+1)/200
            if isinstance(d.get('stt_event_evidence'),dict):item['stt_event_evidence']=copy.deepcopy(d['stt_event_evidence'])
            decorate_event(item,a,bv)
        if st_record and isinstance(d.get('range_statistics'), dict):
            # Saved measurement evidence, separate from the physician's label.
            item['range_statistics'] = copy.deepcopy(d['range_statistics'])
            item['end_s'] = (end + 1) / 200  # New range statistics use [start, end+1).
    # A report strip owns one rhythm episode. Other saved AF/AFL episodes may
    # alter aggregate burden/NN derivatives, but do not change this strip's
    # waveform bounds or physician decision. Keep the full-category basis for
    # browsing while giving each selected strip its own guarded evidence basis.
    for item in events:
        if item['category'] == 'AF':
            item['basis_version'] = bv+'-'+fingerprint(encode([
                item['event_id'], item['start_sample'], item['end_sample'],
                item['end_s'], item['subtype'], item['rhythm_status'], item['label'],
                item.get('lead', ''), item.get('note', '')
            ]))+'-episode-local-v1-episode-status-v2-inclusive-end-v1'
    events.sort(key=lambda x:(x['start_sample'],x['event_id']))
    return dict(quality_control=dict(artifact_count=sum(r['class_code']=='X' for r in rows+markers),artifact_samples=[r['sample_index'] for r in rows+markers if r['class_code']=='X'],role='quality_control_only'),events=events,rows=rows+markers,templates=list(templates),basis_versions=basis,data_version=bv+'-'+av+DATA_VERSION_SUFFIX,beat_version=bv,duration_s=feed.duration)

def event_time_bins(index, items, params, time_of=None):
    """Clock-aligned half-open buckets; histogram precedes the time filter."""
    duration=index['duration_s']
    try:clock=datetime.fromisoformat(str(index.get('start_time')).replace('Z','+00:00'))
    except (ValueError,TypeError):clock=None
    bins=[];start=0
    while start<duration:
        dt=clock+timedelta(seconds=start) if clock else None
        seconds=dt.minute*60+dt.second+dt.microsecond/1e6 if dt else start%3600
        end=min(duration,start+3600-seconds)
        bins.append(dict(start_s=start,end_s=end,label=dt.strftime('%m-%d %H:%M') if dt else f'+{int(start//3600)}h',count=0))
        start=end
    origin=(clock.minute*60+clock.second+clock.microsecond/1e6) if clock else 0
    time_of = time_of or (lambda e: e['time_s'])
    for e in items:
        n=int((origin+time_of(e))//3600)
        if 0<=n<len(bins):bins[n]['count']+=1
    bounds=None
    if 'time_start' in params or 'time_end' in params:
        try:a=float(params['time_start']);b=float(params['time_end'])
        except (KeyError,ValueError,TypeError):raise ValueError('请同时提供有效的起止时间')
        if not (math.isfinite(a) and math.isfinite(b) and 0<=a<b<=duration):raise ValueError('时间筛选超出记录范围')
        bounds=[a,b]
    return bins,bounds

def occurrence_item(row, index, code, template):
    """Materialize a displayed beat only; the retained source row is read-only."""
    sample = row['sample_index']
    edited = (row.get('source_sample') != sample or row['class_code'] !=
              {1:'N',2:'S',3:'V',34:'X'}.get(row.get('source_group'),'OTHER'))
    return dict(event_id='beat:'+row['id'],category=code,subtype='beat',class_code=row['class_code'],
                label=row.get('name',row['class_code']),sample_index=sample,
                start_sample=sample,end_sample=sample,time_s=sample/200,end_s=sample/200,
                target_samples=[sample],beat_count=1,hr=row.get('hr'),rr_ms=row.get('rr_ms'),
                basis_version=index['beat_version'],
                templates=[{'id':str(template['id']),'name':template['name']}] if template else [],
                diagnosis_status='edited' if edited else 'pending')

def query_index(index,params,occurrences=False):
    category=params.get('category','all');mode=params.get('mode','all');code=params.get('class_code','S');template_id=str(params.get('template_id','all'))
    mode={'NPN':'nnp','NNP':'nnp','NPP':'npp','三联律(NPN)':'nnp','三联律(NNP)':'nnp','三联律(NPP)':'npp'}.get(mode,mode)
    offset=max(0,int(params.get('offset',0)));limit=max(1,min(200,int(params.get('limit',100))))
    template=next((t for t in index['templates'] if str(t['id'])==template_id),None)
    if template_id!='all' and template is None:raise ValueError('模板不存在，请刷新')
    samples=set(template['sample_indices']) if template else None
    events=index['events']; fast=params.get('fast_slow_mode','rr').upper()
    from .rr_report import rr_interval_groups
    rr_groups = rr_interval_groups(index)
    rr_source = params.get('rr_source', 'all')
    if rr_source not in ('all', 'auto', 'manual'):raise ValueError('无效的 RR 来源筛选')
    rr_aliases = {event_id: group for group in rr_groups for event_id in group['rr_alias_event_ids']}
    selected_ids=set(str(params.get('ids','')).split('|')) if params.get('ids') else None
    raw_occurrences = occurrences and mode=='all'
    if raw_occurrences:
        # Filter/sort references first. A 24-card page must not allocate a rich
        # event object for each of the roughly 100,000 beats in a daily record.
        items=[r for r in index['rows'] if (code=='all' or (r['class_code'] not in ('N','S','V') if code=='other' else r['class_code']==code))
               and (samples is None or r['sample_index'] in samples)]
    else:
        items=[e for e in events if (selected_ids is not None and e['event_id'] in selected_ids) or (selected_ids is None and (e['category']==('AF' if code in ('A','M','C','H') else code) if occurrences else category=='all' or e['category']==category) and (e['subtype']==mode if mode!='all' else not e['pattern_only']) and (e['category'] not in ('fastest','slowest') or fast=='BOTH' or e['subtype']==fast))]
        if samples is not None:items=[e for e in items if any(s in samples for s in e['target_samples'])]
    if not occurrences and selected_ids is None and category == 'rr_interval':
        items = [e for e in rr_groups if rr_source == 'all' or rr_source in e['rr_sources']]
    elif not occurrences:
        items = [{**e, **{k: rr_aliases[e['event_id']][k] for k in ('rr_semantic_key', 'rr_alias_event_ids', 'rr_aliases', 'rr_sources')}} if e['event_id'] in rr_aliases else e for e in items]
    stt_group=params.get('stt_group','all')
    if stt_group not in ('all','ST','T','ST_T','ST_NOTE','pending'):raise ValueError('ST-T 复核分组无效')
    def in_stt_group(event,key):
        actual=event.get('stt_report_group')
        return actual==key or actual=='ST_T' and key in ('ST','T')
    stt_counts={key:sum(e.get('category')=='ST' and in_stt_group(e,key) for e in events) for key in ('ST','T','ST_T','ST_NOTE','pending')}
    if category=='ST' and selected_ids is None and stt_group!='all':items=[e for e in items if in_stt_group(e,stt_group)]
    pause_band=params.get('pause_band','all')
    if pause_band not in ('all','over3','2.5to3','b0','b1','b2'):raise ValueError('无效的长 RR 筛选范围')
    pauses=[e for e in events if e['category']=='pause']
    pause_counts={'all':len(pauses),'over3':sum(e['rr_ms']>3000 for e in pauses),'2.5to3':sum(e['rr_ms']<=3000 for e in pauses)}
    from .review_candidates import rr_distribution
    pause_distribution=rr_distribution(index['rows'],index['duration_s'],params.get('pause_edges_ms'))
    if not occurrences and category=='pause' and selected_ids is None and pause_band!='all':
        if pause_band.startswith('b'):
            bucket=pause_distribution['bins'][int(pause_band[1])]
            items=[e for e in items if e['rr_ms']>=bucket['lower_ms'] and (bucket['upper_ms'] is None or e['rr_ms']<bucket['upper_ms'])]
        else:items=[e for e in items if (e['rr_ms']>3000 if pause_band=='over3' else e['rr_ms']<=3000)]
    rate_candidates=not occurrences and category in ('fastest','slowest') and selected_ids is None
    raw_spacing=params.get('candidate_spacing_s',0)
    if isinstance(raw_spacing,bool) or not isinstance(raw_spacing,(str,int,float)) or raw_spacing not in (0,7,30,60,'0','7','30','60'):
        raise ValueError('候选定位点间隔须为 0、7、30 或 60 秒')
    spacing=int(raw_spacing) if rate_candidates else 0
    sort_order=params.get('sort','hr_asc') if category in ('rr_candidate','rr_interval') else params.get('sort','hr_desc') if rate_candidates else 'time'
    if sort_order not in ('hr_desc','hr_asc','time'):raise ValueError('无效的候选排序方式')
    if raw_occurrences:
        items.sort(key=lambda r:(r['sample_index'],r['id']))
    else:
        items.sort(key=lambda e:((e['rr_ms'] if sort_order=='hr_desc' else -e['rr_ms']),e['start_sample'],e['event_id']) if sort_order!='time' else (e['start_sample'],e['event_id']))
    counts={key:sum(not e['pattern_only'] and e['category']==key and (key not in ('fastest','slowest') or fast=='BOTH' or e['subtype']==fast) for e in events) for key,_ in CATEGORIES}
    counts['rr_interval'] = len(rr_groups)
    rr_source_counts = {'all':len(rr_groups), **{source:sum(source in e['rr_sources'] for e in rr_groups) for source in ('auto', 'manual')}}
    subtypes=Counter(e['subtype'] for e in events if e['category']==(('AF' if code in ('A','M','C','H') else code) if occurrences else category) and (samples is None or any(s in samples for s in e['target_samples'])))
    beats=Counter(r['class_code'] for r in index['rows'])
    confirmed={key:[e for e in events if e['category']==key and not e['pattern_only'] and e['diagnosis_status']=='confirmed' and (key not in ('fastest','slowest') or fast=='BOTH' or e['subtype']==fast)] for key,_ in CATEGORIES}
    confirmed_counts={key:len(rows) for key,rows in confirmed.items()}
    confirmed_beats={key:len({s for e in rows for s in e['target_samples']}) for key,rows in confirmed.items()}
    confirmed_ids = {e['event_id'] for e in events if e['diagnosis_status'] == 'confirmed'}
    confirmed_rr = [e for e in rr_groups if confirmed_ids.intersection(e['rr_alias_event_ids'])]
    confirmed_counts['rr_interval'] = len(confirmed_rr)
    confirmed_beats['rr_interval'] = len({sample for e in confirmed_rr for sample in e['target_samples']})
    time_of=(lambda r:r['sample_index']/200) if raw_occurrences else (lambda e:e['time_s'])
    time_counts=Counter(int(time_of(e)//3600) for e in items)
    time_bins,bounds=event_time_bins(index,items,params,time_of);unfiltered_total=len(items)
    if bounds:items=[e for e in items if bounds[0]<=time_of(e)<bounds[1]]
    unspaced_total=len(items)
    if spacing:
        # View-only thinning inside the existing top-200 set, after time filtering.
        # Rank is extreme-first even when the display is sorted the other way.
        kept=[]
        for e in sorted(items,key=lambda e:(e['candidate_rank'],e['start_sample'],e['event_id'])):
            if all(e['subtype']!=other['subtype'] or abs(e['start_sample']-other['start_sample'])>=spacing*200 for other in kept):
                kept.append(e)
        ids={e['event_id'] for e in kept}
        items=[e for e in items if e['event_id'] in ids]
    focus = {}
    if 'near_sample' in params:
        raw = params['near_sample']
        if not occurrences or isinstance(raw, bool) or not isinstance(raw, (int, str)) or not str(raw).isascii() or not str(raw).isdigit() or int(raw)>9007199254740991:
            raise ValueError('附近定位仅支持心搏记录的非负整数采样位置')
        sample = int(raw)
        # The old ordinal is not a stable identity after edits. Seek in the
        # filtered, time-ordered collection; only materialize the returned page.
        position = lambda e:e['sample_index'] if raw_occurrences else e['start_sample']
        lo,hi = 0,len(items)
        while lo<hi:
            mid=(lo+hi)//2
            if position(items[mid])<sample:lo=mid+1
            else:hi=mid
        target = min(lo,len(items)-1) if items else None
        offset = target//limit*limit if target is not None else 0
        focus = dict(resume_index=target,resume_sample=position(items[target]) if target is not None else None,
                     resume_exact=target is not None and position(items[target])==sample)
    if params.get('locate_event'):
        if occurrences or selected_ids is not None:raise ValueError('精确定位仅支持报告候选列表')
        target=None;target_basis=None
        for i,event in enumerate(items):
            alias=next((a for a in event.get('rr_aliases',[]) if a['event_id']==params['locate_event']),None) if category=='rr_interval' else None
            if alias is not None or event['event_id']==params['locate_event']:
                target=i;target_basis=alias['basis_version'] if alias is not None else event['basis_version'];break
        if target is None:raise ValueError('目标事件已失效或不在当前筛选内，请重新选择；未跳转到其他事件')
        if params.get('locate_basis') != target_basis:raise ValueError('目标事件依据已变化，请重新选择')
        offset = target//limit*limit
        focus = dict(focus_index=target)
    # These parent-episode facts use explicit whole-rhythm confirmation. They
    # are independent of the global EDIT checkpoint and of figure adoption.
    page=items[offset:offset+limit]
    if raw_occurrences:page=[occurrence_item(r,index,code,template) for r in page]
    return dict(**focus,stt_group=stt_group,stt_counts=stt_counts,rr_source=rr_source,rr_source_counts=rr_source_counts,candidate_spacing_s=spacing,candidate_unspaced_total=unspaced_total,candidate_hidden_count=unspaced_total-len(items),time_bins=time_bins,time_filter=bounds,unfiltered_total=unfiltered_total,pause_counts=pause_counts,pause_distribution=pause_distribution,pause_band=pause_band,sort_order=sort_order,candidate_limit=EXTREME_CANDIDATE_LIMIT if rate_candidates else None,confirmed_category_counts=confirmed_counts,confirmed_beat_counts=confirmed_beats,af_confirmed_subtype_counts={kind:sum(e['category']=='AF' and e.get('rhythm_status')=='confirmed' and e['subtype']==kind for e in events) for kind in ('AF','AFL')},time_counts=dict(time_counts),items=page,total=len(items),offset=offset,limit=limit,category_counts=counts,subtype_counts=dict(subtypes),beat_counts=dict(beats),basis_versions=index['basis_versions'],data_version=index['data_version'])

def hrv_windows(feed,start_time,window=0):
    """NN intervals must lie wholly inside a statistical window; gaps break differences."""
    opts=feed.document['settings']; rows=feed.beats; duration=feed.duration
    try:clock=datetime.fromisoformat(str(start_time).replace('Z','+00:00'))
    except (ValueError,TypeError):clock=None
    window=max(0,min(int(window),max(0,math.ceil(duration/86400)-1))); lo=window*86400;hi=min(duration,lo+86400)
    nn=nn_intervals(feed)
    from .rr_quality import NNWindowIndex
    nn_windows=NNWindowIndex(nn)
    def period(name,intervals):
        merged=[]
        for a,b in intervals:
            if merged and abs(merged[-1][1]-a)<1e-6:merged[-1]=(merged[-1][0],b)
            else:merged.append((a,b))
        intervals=merged
        chosen=nn_windows.contained(intervals)
        values=[x[3] for x in chosen];diffs=[b[3]-a[3] for a,b in zip(chosen,chosen[1:]) if b[0]==a[0]+1 and any(a[1]>=s and b[2]<=e for s,e in intervals)]
        rnd=lambda x:round(x,2) if x is not None else None
        return dict(label=name,nn_count=len(values),coverage_s=round(sum(b-a for a,b in intervals),3),valid_nn_s=round(sum(values)/1000,3),mean_nn_ms=rnd(statistics.mean(values)) if values else None,sdnn_ms=rnd(statistics.stdev(values)) if len(values)>=3 else None,rmssd_ms=rnd(math.sqrt(statistics.mean(v*v for v in diffs))) if diffs else None,pnn50_pct=rnd(100*sum(abs(v)>50 for v in diffs)/len(diffs)) if diffs else None)
    day=[];night=[];hourly=[];t=lo
    while t<hi:
        dt=clock+timedelta(seconds=t) if clock else None
        length=min(hi-t,3600-((dt.minute*60+dt.second+dt.microsecond/1e6) if dt else t%3600))
        end=t+length; interval=(t,end)
        if dt:(day if 6<=dt.hour<22 else night).append(interval)
        item=period(dt.strftime('%m-%d %H:%M') if dt else f'+{t/3600:g}h',[interval]);item.update(start_s=t,end_s=end,partial=length<3600);hourly.append(item);t=end
    return dict(window_index=window,window_count=max(1,math.ceil(duration/86400)),start_s=lo,end_s=hi,actual_duration_s=hi-lo,clock_available=clock is not None,periods={'full':period('24小时窗口' if hi-lo==86400 else '当前记录（不足24小时）',[(lo,hi)]),'day':period('日间 06:00–22:00（清醒代理）',day),'night':period('夜间 22:00–06:00',night)},hourly=hourly,method='修订后连续 N-N；窗口内直接计算；缺失时段留空；日间是清醒时段代理')

def normalize_selection(raw):
    from .report_curation import strip_curation
    if not isinstance(raw,dict):raise ValueError('报告选择必须为对象')
    result={'schema_version':2,'selected_events':[],'category_reviews':{},'diagnosis_blocks':[]}
    entries=raw.get('selected_events',[])
    if not isinstance(entries,list) or len(entries)>2000:raise ValueError('报告图条最多2000项')
    seen=set();strip_owners={}
    for entry in entries:
        if not isinstance(entry,dict) or not isinstance(entry.get('event_id'),str) or not 1<=len(entry['event_id'])<=240:raise ValueError('无效事件标识')
        strip_id = entry.get('strip_id')
        role = entry.get('representative_role')
        if strip_id is not None and (not isinstance(strip_id,str) or not 1<=len(strip_id)<=100):raise ValueError('无效图条标识')
        if strip_id and strip_id in strip_owners and strip_owners[strip_id]!=entry['event_id']:raise ValueError('同一图条标识不能属于不同事件')
        if strip_id:strip_owners[strip_id]=entry['event_id']
        if role is not None and role not in ('start','middle','end','manual','custom'):raise ValueError('无效代表图条位置')
        selection_key = (entry['event_id'],strip_id or '')
        if selection_key in seen:continue
        seen.add(selection_key)
        for field in ('basis_version','caption'):
            if not isinstance(entry.get(field,''),str) or len(entry.get(field,''))>500:raise ValueError('无效图条字段')
        result['selected_events'].append({**{k:entry.get(k,'') for k in ('event_id','basis_version','caption')},
            **({'strip_id':strip_id} if strip_id else {}), **({'representative_role':role} if role else {}),
            **strip_settings(entry), **strip_curation(entry)})
    if raw.get('schema_version')==3 or any(e.get('strip_id') for e in result['selected_events']):result['schema_version']=3
    result['strip_defaults'] = strip_settings(raw.get('strip_defaults'))
    if 'strip_category_defaults' in raw:
        defaults=raw['strip_category_defaults']
        if not isinstance(defaults,dict) or any(k not in {**dict(CATEGORIES),'rr_interval':'RR 间期'} for k in defaults):raise ValueError('无效类别图条设置')
        result['strip_category_defaults']={key:strip_settings(value) for key,value in defaults.items()}
    reviews=raw.get('category_reviews',{})
    if not isinstance(reviews,dict) or any(k not in {**dict(CATEGORIES), 'rr_interval':'RR 间期'} or not isinstance(v,str) or len(v)>100 for k,v in reviews.items()):raise ValueError('无效分类筛选状态')
    result['category_reviews']=dict(reviews)
    blocks=raw.get('diagnosis_blocks',[])
    if not isinstance(blocks,list) or len(blocks)>100:raise ValueError('无效诊断文字块')
    for b in blocks:
        if not isinstance(b,dict) or any(not isinstance(b.get(k,''),str) or len(b.get(k,''))>2000 for k in ('key','text')):raise ValueError('无效诊断文字')
        result['diagnosis_blocks'].append({k:b.get(k,False if k in ('manual','needs_review','acknowledged') else '') for k in ('key','text','manual','needs_review','acknowledged')})
    from .review_candidates import pause_edges
    result['pause_edges_ms']=pause_edges(raw.get('pause_edges_ms'))
    return result

def validate_report(index,composition,review,approving=False):
    from .report_curation import strip_curation
    from .report_evidence import evidence_confirmed, assert_caption, used_in_output
    from .rr_report import deduplicate_rr_selections
    entries, _ = deduplicate_rr_selections(index, composition.get('selected_events', []))
    lookup={e['event_id']:e for e in index['events']};selected=[]
    from .stt_records import normalized_uses
    from .report_sections import selected_pages
    pages=selected_pages(composition)
    for use in normalized_uses(composition.get('stt_report_use',[])):
        pick=next((s for s in composition.get('selected_events',[]) if s['event_id']==use['event_id']),None)
        active=dict(table=use['table'] and 'st_events' in pages,text=use['text'],strip=use['strip'] and 'event_strips' in pages and (pick is None or pick.get('print_enabled',True)))
        if not approving or not any(active.values()):continue
        if active['strip'] and pick is None:raise ValueError('采用的ST-T代表图条不存在，请重新选择图条')
        event=lookup.get(use['event_id'])
        if event is None or event['basis_version']!=use['basis_version']:raise ValueError('采用的ST-T复核依据已变化，请重新核对本条')
        if event.get('category')!='ST' or event.get('stt_review_state')!='reviewed':raise ValueError('采用的ST-T记录尚未完成本条复核或已失效')
        if any(active[k] and not event.get('stt_report_eligibility',{}).get(k) for k in ('table','text','strip')):raise ValueError('该ST-T复核结果不支持所选报告用途')
    for number, entry in enumerate(entries, 1):
        e=lookup.get(entry['event_id'])
        used=used_in_output(composition, entry, e)
        if entry['event_id'].startswith('other:X:') or (e and e.get('category')=='other' and e.get('subtype')=='X'):
            if approving and used:raise ValueError('伪差仅用于质控，请移除历史伪差图条后再审核')
            continue
        if e is None or e['basis_version']!=entry['basis_version']:
            if approving and used:raise ValueError(f'第 {number} 条图条依据已变化（失效），请重新核对或移出本次报告')
            continue
        # RR/NN is an output filter, not a destructive change to curated picks.
        # All retained picks still undergo the normal staleness/review checks.
        if approving and used and e['category']=='AF' and e.get('rhythm_status')!='confirmed':
            raise ValueError('所选房颤／房扑片段尚未确认；请在报告候选区确认本段，或从报告中移除该图条。')
        if approving and used:
            if e.get('evidence_only'):
                if not evidence_confirmed(index,e,entry):
                    raise ValueError(f'第 {number} 条人工图条待核对，请在报告中“确认本条”或移出本次报告')
            elif e.get('category')=='ST':
                if e.get('stt_review_state')!='reviewed':raise ValueError('请先完成本条ST-T复核，或移出本次报告')
            elif e['diagnosis_status']!='confirmed':raise ValueError('请先完成编辑／ST-T诊断确认')
            assert_caption(index,e,entry)
        spec=strip_settings(entry)
        if 'range_start_s' in spec:
            try:resolve_strip(index,e,spec)
            except ValueError:
                if used:raise
                continue
        selected.append({**e,'caption':entry.get('caption') or e['label'], **spec, **strip_curation(entry),
            **{k:entry[k] for k in ('strip_id','representative_role') if k in entry}})
    if approving:
        # Report reviewers decide inclusion directly; visiting every category is not an approval gate.
        if any(b.get('needs_review') for b in composition.get('diagnosis_blocks',[])):raise ValueError('请核对保留的人工诊断文字')
    return selected
