"""Complete occurrence index shared by diagnostic browsing and report selection.

Pattern flags describe sequences, not new disease diagnoses. Source files stay read-only.
"""
from __future__ import annotations
import json
import math
import statistics
from collections import Counter
from datetime import datetime, timedelta

CATEGORIES = [('fastest','最快心率'),('slowest','最慢心率'),('S','房早事件'),('V','室早事件'),('pause','停搏事件'),('rate','心率异常'),('AF','房颤事件'),('ST','ST段事件'),('other','其他事件')]
PATTERNS = [('all','全部'),('single','单发'),('couplet','成对'),('triplet','连续三发'),('run','连续多发'),('tachycardia','心动过速'),('bigeminy','二联律'),('nnp','三联律（NNP）'),('npp','三联律（NPP）'),('quadrigeminy','四联律')]

def fingerprint(text):
    value=2166136261
    # ASCII JSON gives Python and JavaScript identical bytes, including Chinese labels.
    for char in text:
        value=((value ^ ord(char))*16777619)&0xffffffff
    return f'{value:08x}'

def encode(value):
    def integral(v):
        if isinstance(v,float) and v.is_integer():return int(v)
        if isinstance(v,list):return [integral(x) for x in v]
        if isinstance(v,dict):return {k:integral(x) for k,x in v.items()}
        return v
    return json.dumps(integral(value),ensure_ascii=True,separators=(',',':'))

def build_index(feed, templates=(), annotations=(), review=None):
    rows=feed.beats; markers=feed.markers; opts=feed.document['settings']; review=review or {}
    bv=fingerprint('|'.join(f"{r['id']}:{r['sample_index']}:{r['class_code']}" for r in rows+markers)+'|'+encode([[k,opts[k]] for k in sorted(opts)]))
    findings=[a for a in annotations if a.get('details',{}).get('kind') in ('ST','AT','VT','AF','AFL')]
    av=fingerprint(encode([[a['id'],a['sample_index'],a.get('details')] for a in findings]))
    basis={key:bv for key,_ in CATEGORIES}
    for key,kind in [('ST','ST'),('S','AT'),('V','VT'),('AF','AF')]:
        basis[key]=bv+'-'+fingerprint(encode([[a['id'],a['sample_index'],a['details']] for a in findings if a['details']['kind']==kind or (key=='AF' and a['details']['kind']=='AFL')]))
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
            length=len(cycle);i=0
            while i+2*length<=len(rows):
                j=i
                while j+length<=len(rows) and [r['class_code'] for r in rows[j:j+length]]==cycle:j+=length
                if j-i>=2*length:
                    segment=rows[i:j];make(code,kind,label+dict(PATTERNS)[kind],[r for r in segment if r['class_code']==code],segment,True);i=j
                else:i+=1
    valid=[r for r in rows if r['class_code']!='X' and r.get('rr_ms',0)>0]
    nn=[b for a,b in zip(rows,rows[1:]) if a['class_code']==b['class_code']=='N' and opts['nn_min']<=b['rr_ms']<=opts['nn_max']]
    for name,subset in [('RR',valid),('NN',nn)]:
        if subset:
            for key,fn in [('fastest',min),('slowest',max)]:
                r=fn(subset,key=lambda x:x['rr_ms']);make(key,name,name+' '+dict(CATEGORIES)[key]+f" {int(r['hr']) if float(r['hr']).is_integer() else r['hr']} bpm",[r])
    for r in valid:
        if r['rr_ms']>=opts['pause']*1000:make('pause','pause',f"长 RR {r['rr_ms']/1000:.3f} s",[r])
    # Contiguous threshold/rhythm runs; no joining across intervening beats or noise.
    for category,subtype,label,predicate in [
        ('rate','tachy','快心率',lambda r:r['class_code']!='X' and (r.get('hr') or 0)>=opts['tachy']),
        ('rate','brady','慢心率',lambda r:r['class_code']!='X' and 0<(r.get('hr') or 0)<=opts['brady']),
        ('AF','AF','房颤',lambda r:r['class_code'] in ('A','M')),
        ('AF','AFL','房扑',lambda r:r['class_code'] in ('C','H'))]:
        i=0
        while i<len(rows):
            if not predicate(rows[i]):i+=1;continue
            j=i+1
            while j<len(rows) and predicate(rows[j]):j+=1
            make(category,subtype,label,rows[i:j]);i=j
    for r in rows+markers:
        if r['class_code'] not in ('N','S','V','A','M','C','H'):
            make('other',r['class_code'],r.get('name',r['class_code']),[r])
    def kind_not_rhythm(d):return d['kind'] not in ('AF','AFL')
    for a in findings:
        d=a['details']
        if d['kind'] in ('AF','AFL') and d.get('status')=='pending' and any(b['details']['kind']==d['kind'] and b['details'].get('status')=='confirmed' and b['sample_index']==a['sample_index'] and b['details'].get('end_sample')==d.get('end_sample') for b in findings):continue
        if d.get('status')!='confirmed' and kind_not_rhythm(d):continue
        if d.get('status')=='excluded':continue
        kind=d['kind'];cat='AF' if kind in ('AF','AFL') else 'ST' if kind=='ST' else 'S' if kind=='AT' else 'V'
        start=a['sample_index'];end=d.get('end_sample',start)
        target=[r for r in rows if start<=r['sample_index']<=end and (kind in ('ST','AF','AFL') or r['class_code']==cat)]
        segment=[dict(id=f"a:{a['id']}:start",sample_index=start),dict(id=f"a:{a['id']}:end",sample_index=end)]
        item=make(cat,kind if kind in ('ST','AF','AFL') else 'tachycardia',d.get('finding') or ('房速' if kind=='AT' else '室速'),target,segment,kind not in ('ST','AF','AFL'),f"annotation:{a['id']}")
        if d.get('status')!='confirmed':item['diagnosis_status']='pending'
        item['lead']=a.get('lead','全部');item['note']=a.get('note','')
    events.sort(key=lambda x:(x['start_sample'],x['event_id']))
    return dict(events=events,rows=rows+markers,templates=list(templates),basis_versions=basis,data_version=bv+'-'+av,beat_version=bv,duration_s=feed.duration)

def query_index(index,params,occurrences=False):
    category=params.get('category','all');mode=params.get('mode','all');code=params.get('class_code','S');template_id=str(params.get('template_id','all'))
    mode={'NPN':'nnp','NNP':'nnp','NPP':'npp','三联律(NPN)':'nnp','三联律(NNP)':'nnp','三联律(NPP)':'npp'}.get(mode,mode)
    offset=max(0,int(params.get('offset',0)));limit=max(1,min(200,int(params.get('limit',100))))
    template=next((t for t in index['templates'] if str(t['id'])==template_id),None)
    if template_id!='all' and template is None:raise ValueError('模板不存在，请刷新')
    samples=set(template['sample_indices']) if template else None
    events=index['events']; fast=params.get('fast_slow_mode','rr').upper()
    selected_ids=set(str(params.get('ids','')).split('|')) if params.get('ids') else None
    if occurrences and mode=='all':
        items=[]
        for r in index['rows']:
            if code!='all' and r['class_code']!=code:continue
            if samples is not None and r['sample_index'] not in samples:continue
            items.append(dict(event_id='beat:'+r['id'],category=code,subtype='beat',label=r.get('name',r['class_code']),sample_index=r['sample_index'],start_sample=r['sample_index'],end_sample=r['sample_index'],time_s=r['sample_index']/200,end_s=r['sample_index']/200,target_samples=[r['sample_index']],beat_count=1,hr=r.get('hr'),rr_ms=r.get('rr_ms'),basis_version=index['beat_version'],templates=[{'id':str(template['id']),'name':template['name']}] if template else [],diagnosis_status='edited' if r.get('source_sample')!=r['sample_index'] or r['class_code']!={1:'N',2:'S',3:'V',34:'X'}.get(r.get('source_group'),'OTHER') else 'pending'))
    else:
        items=[e for e in events if (selected_ids is not None and e['event_id'] in selected_ids) or (selected_ids is None and (e['category']==('AF' if code in ('A','M','C','H') else code) if occurrences else category=='all' or e['category']==category) and (e['subtype']==mode if mode!='all' else not e['pattern_only']) and (e['category'] not in ('fastest','slowest') or fast=='BOTH' or e['subtype']==fast))]
        if samples is not None:items=[e for e in items if any(s in samples for s in e['target_samples'])]
    items=sorted(items,key=lambda e:(e['start_sample'],e['event_id']))
    counts={key:sum(not e['pattern_only'] and e['category']==key and (key not in ('fastest','slowest') or fast=='BOTH' or e['subtype']==fast) for e in events) for key,_ in CATEGORIES}
    subtypes=Counter(e['subtype'] for e in events if e['category']==(('AF' if code in ('A','M','C','H') else code) if occurrences else category) and (samples is None or any(s in samples for s in e['target_samples'])))
    beats=Counter(r['class_code'] for r in index['rows'])
    confirmed={key:[e for e in events if e['category']==key and not e['pattern_only'] and e['diagnosis_status']=='confirmed' and (key not in ('fastest','slowest') or fast=='BOTH' or e['subtype']==fast)] for key,_ in CATEGORIES}
    confirmed_counts={key:len(rows) for key,rows in confirmed.items()}
    confirmed_beats={key:len({s for e in rows for s in e['target_samples']}) for key,rows in confirmed.items()}
    time_counts=Counter(int(e["time_s"]//3600) for e in items)
    return dict(confirmed_category_counts=confirmed_counts,confirmed_beat_counts=confirmed_beats,time_counts=dict(time_counts),items=items[offset:offset+limit],total=len(items),offset=offset,limit=limit,category_counts=counts,subtype_counts=dict(subtypes),beat_counts=dict(beats),basis_versions=index['basis_versions'],data_version=index['data_version'])

def hrv_windows(feed,start_time,window=0):
    """NN intervals must lie wholly inside a statistical window; gaps break differences."""
    opts=feed.document['settings']; rows=feed.beats; duration=feed.duration
    try:clock=datetime.fromisoformat(str(start_time).replace('Z','+00:00'))
    except (ValueError,TypeError):clock=None
    window=max(0,min(int(window),max(0,math.ceil(duration/86400)-1))); lo=window*86400;hi=min(duration,lo+86400)
    nn=[(i,a['sample_index']/200,b['sample_index']/200,b['rr_ms']) for i,(a,b) in enumerate(zip(rows,rows[1:])) if a['class_code']==b['class_code']=='N' and opts['nn_min']<=b['rr_ms']<=opts['nn_max']]
    def period(name,intervals):
        merged=[]
        for a,b in intervals:
            if merged and abs(merged[-1][1]-a)<1e-6:merged[-1]=(merged[-1][0],b)
            else:merged.append((a,b))
        intervals=merged
        chosen=[x for x in nn if any(x[1]>=a and x[2]<=b for a,b in intervals)]
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
    if not isinstance(raw,dict):raise ValueError('报告选择必须为对象')
    result={'schema_version':2,'selected_events':[],'category_reviews':{},'diagnosis_blocks':[]}
    entries=raw.get('selected_events',[])
    if not isinstance(entries,list) or len(entries)>2000:raise ValueError('报告图条最多2000项')
    seen=set()
    for entry in entries:
        if not isinstance(entry,dict) or not isinstance(entry.get('event_id'),str) or not 1<=len(entry['event_id'])<=240:raise ValueError('无效事件标识')
        if entry['event_id'] in seen:continue
        seen.add(entry['event_id'])
        for field in ('basis_version','caption'):
            if not isinstance(entry.get(field,''),str) or len(entry.get(field,''))>500:raise ValueError('无效图条字段')
        result['selected_events'].append({k:entry.get(k,'') for k in ('event_id','basis_version','caption')})
    reviews=raw.get('category_reviews',{})
    if not isinstance(reviews,dict) or any(k not in dict(CATEGORIES) or not isinstance(v,str) or len(v)>100 for k,v in reviews.items()):raise ValueError('无效分类筛选状态')
    result['category_reviews']=dict(reviews)
    blocks=raw.get('diagnosis_blocks',[])
    if not isinstance(blocks,list) or len(blocks)>100:raise ValueError('无效诊断文字块')
    for b in blocks:
        if not isinstance(b,dict) or any(not isinstance(b.get(k,''),str) or len(b.get(k,''))>2000 for k in ('key','text')):raise ValueError('无效诊断文字')
        result['diagnosis_blocks'].append({k:b.get(k,False if k in ('manual','needs_review','acknowledged') else '') for k in ('key','text','manual','needs_review','acknowledged')})
    return result

def validate_report(index,composition,review,approving=False):
    lookup={e['event_id']:e for e in index['events']};selected=[]
    for entry in composition.get('selected_events',[]):
        e=lookup.get(entry['event_id'])
        if e is None or e['basis_version']!=entry['basis_version']:
            if approving:raise ValueError('已选图条因诊断修订失效，请重新筛选')
            continue
        if approving and e['category'] in ('fastest','slowest') and composition.get('fast_slow_mode','rr').upper() not in ('BOTH',e['subtype']):raise ValueError('极值图条与 RR/NN 选择不一致')
        if approving and e['diagnosis_status']!='confirmed':raise ValueError('请先完成编辑／ST-T诊断确认')
        selected.append({**e,'caption':entry.get('caption') or e['label']})
    if approving:
        counts=query_index(index,{'fast_slow_mode':composition.get('fast_slow_mode','rr')})['category_counts']
        missing=[label for key,label in CATEGORIES if counts[key] and composition.get('category_reviews',{}).get(key)!=index['basis_versions'][key]]
        if missing:raise ValueError('请完成报告分类筛选：'+'、'.join(missing))
        if any(b.get('needs_review') for b in composition.get('diagnosis_blocks',[])):raise ValueError('请核对保留的人工诊断文字')
    return selected
