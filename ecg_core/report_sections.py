"""Report evidence, never inferred disease diagnoses. See docs/report-analysis-methods.md."""
from collections import Counter
from math import isfinite
from .rr_quality import qrs_rows, interval_mask, finite, rhythm_summary, rhythm_episodes
from .stt_records import protocol as stt_protocol

PAGE_TITLES = dict(cover='封面',summary='首页报告',hourly='小时统计表格',scatter='散点图',st_trend='ST 趋势图',t_trend='T 波趋势图',event_strips='事件图条',st_events='ST 事件',pacing='起搏报告',af='房颤 / 房扑',hrv_time='HRV 时域报告',hrv_frequency='HRV 频域报告',hrv_overview='HRV 概述',hrt='心率震荡 (HRT)',qtd='QT 离散度 (QTd)',vcg='心电向量 (VCG)',dc='心率减速力 (DC)',twa='T 波电交替 (TWA)',vlp='心室晚电位 (VLP)',sap='睡眠窒息 (SAP)')
UNAVAILABLE = dict(vlp='200 Hz 输入不能覆盖晚电位高频带宽；插值无法补足采集信息')
PAGE_TITLES.update(qtd='QT 离散度（研究测量）',vcg='推导心电向量（研究）',twa='T 波电交替（研究测量）',sap='睡眠呼吸暂停相关 ECG 筛查（非诊断）')
PAGE_TITLES.update(st_trend='ST 分析',st_events='ST-T 事件与复核')

def selected_pages(composition):
    if composition.get('page_selection_version') == 1:
        return list(composition.get('included_pages', []))
    return ['summary','hourly','event_strips'] + (['hrv_time','hrv_overview'] if composition.get('include_hrv') else [])


def rhythm_paragraphs(s):
    if not s or not s['denominator_s'] > 0:
        return ['记录时长未提供，无法计算房颤 / 房扑负荷；不以 0 代替缺失数据。']
    out = []
    for key, label in [('confirmed_af', '房颤'), ('confirmed_afl', '房扑')]:
        r = s[key]
        out.append(f"已确认{label}：{r['count']} 段，{r['seconds']:.3f} 秒；占记录时长 {r['pct']:.2f}%。")
    r = s['confirmed_any']
    out.append(f"分母：完整记录 {s['denominator_s']:.3f} 秒；确认房颤 / 房扑合并去重 {r['seconds']:.3f} 秒（{r['pct']:.2f}%）。")
    out.append(f"待复核 {s['pending_any']['count']} 段，不计入确认负荷。同类及合并统计分别按时间并集去重，房颤与房扑时长不能直接相加。")
    return out

def rr_derivatives(rows, excluded=()):
    """Conservative sinus-only HRT and DC research implementation, no risk bands."""
    rows=qrs_rows(rows)
    valid=interval_mask(rows,excluded)
    def normal(i):
        r=rows[i];rr=r.get('rr_ms')
        return valid[i] and rows[i-1]['class_code']=='N' and r['class_code']=='N' and 300<=rr<=2000
    bad=[0];jumps=[0]
    for i in range(len(rows)):
        bad.append(bad[-1]+int(not normal(i)))
        prev=rows[i-1].get('rr_ms') if i else None;current=rows[i].get('rr_ms')
        jumps.append(jumps[-1]+int(finite(prev) and prev>0 and finite(current) and abs(current/prev-1)>.2+1e-12))
    def segment(a,b):
        return bad[b]==bad[a] and jumps[b]==jumps[a+1]
    onsets=[];tachograms=[];source_events=[]
    for i in range(5,len(rows)-21):
        if rows[i]['class_code']!='V' or not segment(i-5,i) or not segment(i+2,i+22):continue
        if rows[i+1]['class_code']!='N' or not valid[i] or not valid[i+1]:continue
        base=sum(rows[k]['rr_ms'] for k in range(i-5,i))/5
        coupling=rows[i].get('rr_ms') or 0;pause=rows[i+1].get('rr_ms') or 0
        if not (300<=coupling<base*.8 and base*1.2<pause<=3000):continue
        # PVC and compensatory pause are not sinus reference intervals.
        sinus=[rows[k]['rr_ms'] for k in list(range(i-5,i))+list(range(i+2,i+22))]
        if any(abs(b-a)>200 for a,b in zip(sinus,sinus[1:])):continue
        if any(abs(v/(sum(sinus[j-5:j])/5)-1)>.2+1e-12 for j,v in enumerate(sinus) if j>=5):continue
        before=rows[i-2]['rr_ms']+rows[i-1]['rr_ms'];after=rows[i+2]['rr_ms']+rows[i+3]['rr_ms']
        onsets.append(100*(after-before)/before)
        tachograms.append([rows[k]['rr_ms'] for k in range(i+2,i+17)])
        # Accepted source beats only; this trace never participates in the
        # eligibility or aggregate calculations. Use the imported 200 Hz
        # sample contract already used by evidence(), not estimated timings.
        source_events.append(dict(sample_index=rows[i]['sample_index'],
            time_s=rows[i]['sample_index']/200,
            start_sample=rows[i-5]['sample_index'],end_sample=rows[i+21]['sample_index'],
            to_pct=round(onsets[-1],4),rr_ms=list(tachograms[-1])))
    average=[sum(x[j] for x in tachograms)/len(tachograms) for j in range(15)] if tachograms else []
    slopes=[sum((j-2)*average[i+j] for j in range(5))/10 for i in range(11)] if average else []
    anchors=[];sums=[0.0]*60
    for i in range(30,len(rows)-29):
        # PRSA L=30, T=1; accepted anchors decelerate by 0–5%. No gaps bridged.
        if not segment(i-30,i+30):continue
        if not 0<rows[i]['rr_ms']/rows[i-1]['rr_ms']-1<=.05+1e-12:continue
        anchors.append(i)
        for j in range(60):sums[j]+=rows[i+j-30]['rr_ms']
    prsa=[v/len(anchors) for v in sums] if anchors else []
    return dict(
        hrt=dict(source_events=source_events,eligible_pvc=len(onsets),to_pct=round(sum(onsets)/len(onsets),4) if len(onsets)>=5 else None,ts_ms_per_rr=round(max(slopes),4) if len(onsets)>=5 else None,tachogram=[dict(x=i+1,y=round(v,4)) for i,v in enumerate(average)],method='HRT 研究性计算：孤立 V，前 5 / 后 20 个正常间期；排除完整间期与房颤/房扑区间的交集、伪差及不连续数据；正常间期相邻差≤200 ms，恢复间期相对前5个正常间期均值偏差≤20%。TO 为逐事件均值，TS 为平均恢复序列前 15 间期内 5 点最大回归斜率。少于 5 个合格事件不报 TO/TS；不输出风险等级。'),
        dc=dict(anchor_count=len(anchors),dc_ms=round((prsa[30]+prsa[31]-prsa[29]-prsa[28])/4,4) if len(anchors)>=20 else None,prsa=[dict(x=i-30,y=round(v,4)) for i,v in enumerate(prsa)],method='DC 研究性 PRSA：T=1，L=30；减速锚点增幅 0–5%，只用连续正常 N-N、排除异常节律区段。DC=(X0+X1-X-1-X-2)/4；少于 20 个锚点不报告值。阈值为软件质量控制，不是诊断标准。'))

from .evaluation_status import stt_status
from .stt import LEADS as ST_LEADS

def st_report_events(index, family='ST'):
    result=[]
    for event in index['events']:
        if event.get('category')!='ST' or event.get('stt_review_state','reviewed' if event.get('diagnosis_status')=='confirmed' else 'unreviewed')!='reviewed' or event.get('stt_evidence_stale'):continue
        proof=event.get('stt_event_evidence') or {}
        label=event.get('label','')
        if proof.get('kind') not in (('t_wave_inversion',) if family=='T' else ('st_depression','st_elevation')):continue
        start,end=event['time_s'],event.get('end_s',event['time_s'])
        if end-start<60-1e-9:continue  # Point review is not a duration claim.
        if event.get('stt_result_code') in ('no_change','artifact','indeterminate','nonspecific'):continue
        leads=(event.get('stt_review_receipt') or {}).get('leads') or proof.get('leads') or ([event['lead']] if event.get('lead') in ST_LEADS else [])
        for lead in leads:
            m=next((row for row in proof.get('metrics',[]) if row['lead']==lead),{})
            depressed=proof.get('kind')=='st_depression';extreme=m.get('minimum_st_level_units' if depressed else 'maximum_st_level_units')
            anchor=m.get('minimum_st_sample' if depressed else 'maximum_st_sample')
            result.append(dict(event_id=event['event_id'],record_id=event['event_id'],row_id=event['event_id']+':'+lead,basis_version=event['basis_version'],label=label,
            lead=lead,kind=proof.get('kind'),result_code=event.get('stt_result_code'),review_state='reviewed',
            start_s=start,end_s=end,duration_s=round(end-start,3),leads=[lead],
            peak_deviation_units=proof.get('peak_deviation_units'),peak_time_s=proof.get('peak_time_s'),
            source=proof.get('source','physician_selected_range'),review_status='confirmed',
            continuous_target_s=proof.get('continuous_target_s'),measurement_protocol=proof.get('measurement_protocol'),
            units='source_device_units',slope=None,calibrated_mm=None,mean_st_level_units=m.get('mean_st_level_units'),
            extreme_st_level_units=extreme,extreme_st_time_s=anchor/200 if anchor is not None else None,
            extreme_st_sample=anchor,minimum_st_sample=m.get('minimum_st_sample'),maximum_st_sample=m.get('maximum_st_sample'),
            minimum_st_level_units=m.get('minimum_st_level_units'),maximum_st_level_units=m.get('maximum_st_level_units'),
            reference_sample=m.get('reference_sample'),reference_st_level_units=m.get('reference_st_level_units'),
            mean_t_amplitude_units=m.get('mean_t_amplitude_units'),extreme_t_amplitude_units=m.get('extreme_t_amplitude_units'),
            extreme_t_time_s=m['extreme_t_sample']/200 if m.get('extreme_t_sample') is not None else None,
            t_reference_units=proof.get('t_reference_units'),used_beat_count=m.get('t_used_count' if family=='T' else 'used_count'),
            coverage=proof.get('coverage'),boundary_resolution_s=proof.get('boundary_resolution_s',16)))
    return result

def st_review_notes(index):
    return [dict(event_id=e['event_id'],basis_version=e['basis_version'],label=e.get('label','ST-T 复核'),
        start_s=e['time_s'],end_s=e.get('end_s',e['time_s']),
        review_kind='whole_review' if (e.get('stt_review_receipt') or {}).get('review_extent')=='whole' else 'range_mean' if e.get('range_statistics') else 'point_or_legacy_range',
        review_status=e.get('stt_review_state',e.get('diagnosis_status','pending')),review_state=e.get('stt_review_state'),
        result_code=e.get('stt_result_code'),report_group=e.get('stt_report_group'),note=e.get('note',''),physician_note=e.get('stt_physician_note',e.get('note','')),
        measurement_protocol=(e.get('stt_review_receipt') or {}).get('measurement_protocol')) for e in index['events']
        if e.get('category')=='ST' and not e.get('stt_report_eligibility',{}).get('table')]


def st_summary(rows):
    from .stt_records import time_groups,interval_union
    groups=time_groups(rows);union=interval_union([(r['start_s'],r['end_s']) for r in rows])
    return dict(confirmed_lead_event_count=len(rows),confirmed_record_count=len({r['event_id'] for r in rows}),
        confirmed_time_group_count=len(groups),confirmed_union_duration_s=sum(b-a for a,b in union),
        groups=groups,denominator='full_record_confirmed_events_not_report_selection',clinical_episode_count=None)


def report_heart_rate(rows,duration_s):
    """Current detected non-artifact anchors; missing bins break the line."""
    from math import ceil
    duration=max(0,float(duration_s));counts=[0]*ceil(duration/60)
    for row in rows:
        if row.get('class_code')=='X':continue
        time=row['sample_index']/200
        if 0<=time<duration:counts[int(time//60)]+=1
    return [dict(start_s=i*60,end_s=min(duration,(i+1)*60),time_s=(i*60+min(duration,(i+1)*60))/2,
        detected_beat_count=n,hr=round(n*60/(min(duration,(i+1)*60)-i*60),2) if n else None) for i,n in enumerate(counts)]

def evidence(index, st=None):
    rows=sorted(qrs_rows(index['rows']),key=lambda r:r['sample_index'])
    rows=[dict(r,time_s=r['sample_index']/200) for r in rows]
    af=[e for e in index['events'] if e['category']=='AF']
    summary = rhythm_summary(rhythm_episodes(af), index['duration_s']) if index.get('duration_s', 0) > 0 else None
    derivatives=rr_derivatives(rows,[(e['time_s'],e['end_s']) for e in af])
    points=[]
    valid=interval_mask(rows)
    for i in range(1,len(rows)):
        if valid[i-1] and valid[i]:points.append(dict(x=rows[i-1]['rr_ms'],y=rows[i]['rr_ms']))
    stride=max(1,(len(points)+7999)//8000)
    counts=Counter(r['class_code'] for r in rows if r['class_code'] in ('P','PA','PV','PD','PF'))
    st=st or {};raw_trends=(st.get('analysis') or {}).get('trends',{}).get('leads',{})
    trends={lead:[{**p,**({key:None for key in ('st_level_units','reference_units','deviation_units','t_amplitude_units','t_reference_units')} if p.get('eligible') is False or p.get('axis_shift_suspected') else {})} for p in raw_trends.get(lead,[])] for lead in ST_LEADS}
    return dict(st_evaluation=stt_status(st.get('automatic_candidates')),sections=[dict(key=k,title=v,available=k not in UNAVAILABLE,reason=UNAVAILABLE.get(k,'')) for k,v in PAGE_TITLES.items()],scatter=dict(points=points[::stride],total=len(points),stride=stride),pacing=dict(counts=dict(counts),total=sum(counts.values()),method='仅统计当前起搏类型标记；不检测夺获失败、感知异常或器械故障。'),af_summary=summary,af=[dict(time_s=e['time_s'],end_s=e['end_s'],label=e['label'],status=e.get('rhythm_status',e['diagnosis_status'])) for e in af],st_trends=trends,st_events=st_report_events(index),t_events=st_report_events(index,'T'),st_summary=st_summary(st_report_events(index)),t_summary=st_summary(st_report_events(index,'T')),st_representatives=[],st_review_notes=st_review_notes(index),st_measurement_protocol=stt_protocol(dict(measurement_ms=60,extent='whole')),units='source_device_units',st_trend_resolution_s=60,heart_rate_trend=report_heart_rate(rows,index['duration_s']),heart_rate_method='current_detected_nonartifact_beats_per_actual_60s_bin_support',**derivatives)

def validate_pages(composition):
    pages=selected_pages(composition)
    if not pages:raise ValueError('请至少选择一类报告页')
    for key in pages:
        if key not in PAGE_TITLES:raise ValueError('不支持的报告页')
        if key in UNAVAILABLE:raise ValueError(PAGE_TITLES[key]+'：'+UNAVAILABLE[key])
    return pages
