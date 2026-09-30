"""Report evidence, never inferred disease diagnoses. See docs/report-analysis-methods.md."""
from collections import Counter
from math import isfinite
from .rr_quality import qrs_rows, interval_mask, finite, rhythm_summary, rhythm_episodes

PAGE_TITLES = dict(cover='封面',summary='首页报告',hourly='小时统计表格',scatter='散点图',st_trend='ST 趋势图',t_trend='T 波趋势图',event_strips='事件图条',st_events='ST 事件',pacing='起搏报告',af='房颤 / 房扑',hrv_time='HRV 时域报告',hrv_frequency='HRV 频域报告',hrv_overview='HRV 概述',hrt='心率震荡 (HRT)',qtd='QT 离散度 (QTd)',vcg='心电向量 (VCG)',dc='心率减速力 (DC)',twa='T 波电交替 (TWA)',vlp='心室晚电位 (VLP)',sap='睡眠窒息 (SAP)')
UNAVAILABLE = dict(vlp='200 Hz 输入不能覆盖晚电位高频带宽；插值无法补足采集信息')
PAGE_TITLES.update(qtd='QT 离散度（研究测量）',vcg='推导心电向量（研究）',twa='T 波电交替（研究测量）',sap='睡眠呼吸暂停相关 ECG 筛查（非诊断）')

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
    onsets=[];tachograms=[]
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
        hrt=dict(eligible_pvc=len(onsets),to_pct=round(sum(onsets)/len(onsets),4) if len(onsets)>=5 else None,ts_ms_per_rr=round(max(slopes),4) if len(onsets)>=5 else None,tachogram=[dict(x=i+1,y=round(v,4)) for i,v in enumerate(average)],method='HRT 研究性计算：孤立 V，前 5 / 后 20 个正常间期；排除完整间期与房颤/房扑区间的交集、伪差及不连续数据；正常间期相邻差≤200 ms，恢复间期相对前5个正常间期均值偏差≤20%。TO 为逐事件均值，TS 为平均恢复序列前 15 间期内 5 点最大回归斜率。少于 5 个合格事件不报 TO/TS；不输出风险等级。'),
        dc=dict(anchor_count=len(anchors),dc_ms=round((prsa[30]+prsa[31]-prsa[29]-prsa[28])/4,4) if len(anchors)>=20 else None,prsa=[dict(x=i-30,y=round(v,4)) for i,v in enumerate(prsa)],method='DC 研究性 PRSA：T=1，L=30；减速锚点增幅 0–5%，只用连续正常 N-N、排除异常节律区段。DC=(X0+X1-X-1-X-2)/4；少于 20 个锚点不报告值。阈值为软件质量控制，不是诊断标准。'))

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
    st=st or {};trends=(st.get('analysis') or {}).get('trends',{}).get('leads',{})
    return dict(sections=[dict(key=k,title=v,available=k not in UNAVAILABLE,reason=UNAVAILABLE.get(k,'')) for k,v in PAGE_TITLES.items()],scatter=dict(points=points[::stride],total=len(points),stride=stride),pacing=dict(counts=dict(counts),total=sum(counts.values()),method='仅统计当前起搏类型标记；不检测夺获失败、感知异常或器械故障。'),af_summary=summary,af=[dict(time_s=e['time_s'],end_s=e['end_s'],label=e['label'],status=e.get('rhythm_status',e['diagnosis_status'])) for e in af],st_trends=trends,st_events=st.get('automatic_candidates',{}).get('items',[]),**derivatives)

def validate_pages(composition):
    pages=selected_pages(composition)
    if not pages:raise ValueError('请至少选择一类报告页')
    for key in pages:
        if key not in PAGE_TITLES:raise ValueError('不支持的报告页')
        if key in UNAVAILABLE:raise ValueError(PAGE_TITLES[key]+'：'+UNAVAILABLE[key])
    return pages
