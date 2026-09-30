"""Optional evidence pages, using the same selection contract as the web preview."""
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from .report_paper_pdf import clock, wrap_text, number
from .report_sections import PAGE_TITLES, rhythm_paragraphs


def documents(case, report, keys):
    e=report.get('section_evidence') or {};d=report.get('hrv_analysis');meta=case.get('metadata',{});out=[]
    def add(key, paragraphs=(), charts=(), rows=()):
        wrapped=[line for row in rows for line in wrap_text(row,70)]
        for i in range(0,max(1,len(wrapped)),28):out.append(dict(title=PAGE_TITLES[key]+('（续）' if i else ''),paragraphs=[] if i else paragraphs,charts=[] if i else charts,rows=wrapped[i:i+28]))
    for key in keys:
        if key in ('qtd','vcg','twa','sap'):
            docs=(e.get('advanced') or {}).get('documents',{}).get(key)
            if not docs:raise ValueError('研究测量尚未计算')
            out.extend(docs)
            continue
        if key=='cover':add(key,['动态心电图检测报告',f"检查记录：{case['case_id']}",f"记录时间：{clock(meta)}",f"记录时长：{meta.get('duration_text','—')}",'研究与软件验证输出。请由医生核对分析统计、原始波形与诊断结论。'])
        if key=='scatter':
            r=e.get('scatter',{});add(key,[f"相邻 RR 配对 {r.get('total',0)} 个；图中等间隔抽取 1/{r.get('stride',1)} 显示，统计保留全量。"],[dict(title='Lorenz RR(i) / RR(i+1) · ms',points=r.get('points',[]),scatter=True)])
        if key=='pacing':
            r=e.get('pacing',{});add(key,[r.get('method','无可用数据')],rows=[f'{k} 起搏标记：{n} 搏' for k,n in r.get('counts',{}).items()]+[f"起搏类型总标记数：{r.get('total',0)} 搏；0 不等同排除起搏器。"])
        if key=='af':add(key,[*rhythm_paragraphs(e.get('af_summary')),'片段确认与报告整体审核是独立状态；自动 RR 不规则筛查不等同房颤诊断。','本页仅汇总已保存片段，不证明全程已评估；无片段或未提示不能排除房颤，未评估时段须回看原始波形。'],rows=[f"{clock(meta,r['time_s'])} · {(r['end_s']-r['time_s'])/60:.2f} 分钟 · {r['label']} · {'医生确认' if r['status']=='confirmed' else '待复核'}" for r in e.get('af',[])])
        if key in ('hrt','dc'):
            r=e.get(key,{})
            stats=f"合格室早 {number(r.get('eligible_pvc'))}；TO {number(r.get('to_pct'))} %；TS {number(r.get('ts_ms_per_rr'))} ms/RR" if key=='hrt' else f"减速锚点 {number(r.get('anchor_count'))}；DC {number(r.get('dc_ms'))} ms"
            add(key,[r.get('method','无可用数据'),stats,'— 表示样本不足或无可用结果，不代表正常。'],[dict(title='平均恢复 RR · ms / 序号' if key=='hrt' else 'PRSA · RR ms / 相对锚点',points=r.get('tachogram' if key=='hrt' else 'prsa',[]))])
        if key in ('st_trend','t_trend'):
            leads=list(e.get('st_trends',{}).items())
            if not leads:add(key,['当前没有可用的 ST-T 研究性测量数据；不能解释为正常。'])
            for i in range(0,len(leads),3):add(key,['设备单位，非 mV；未校准的研究性趋势，空缺不补线，不生成缺血或复极诊断。'],[dict(title=lead+' · '+PAGE_TITLES[key]+' / 相对小时',points=[dict(x=p['time_s']/3600,y=p.get('deviation_units' if key=='st_trend' else 't_amplitude_units')) for p in points]) for lead,points in leads[i:i+3]])
        if key=='st_events':add(key,['ST-T 研究性候选清单，未确认诊断；幅度为设备单位，非 mV。'],rows=[f"{clock(meta,r.get('start_s',0))} · {r.get('type',r.get('label','ST-T 候选'))} · {'/'.join(r.get('leads',[]))} · {number(r.get('duration_s'))} 秒 · 偏移 {number(r.get('peak_deviation_units'))}" for r in e.get('st_events',[])])
        if key in ('hrv_time','hrv_frequency'):
            if not d:raise ValueError('HRV 数据尚未加载')
            periods=[d['periods'][k] for k in ('full','day','night')];rows=[]
            for p in periods:
                rows.append(p['label']);f=p['frequency']
                rows.append(f"NN {p['nn_count']}；SDNN {number(p.get('sdnn_ms'))} ms；SDANN {number(p.get('sdann_ms'))} ms；rMSSD {number(p.get('rmssd_ms'))} ms；pNN50 {number(p.get('pnn50_pct'))} %" if key=='hrv_time' else f"总功率 {number(f['total_ms2'])}；VLF {number(f['vlf_ms2'])}；LF {number(f['lf_ms2'])}；HF {number(f['hf_ms2'])} ms²；LF/HF {number(f['lf_hf'])}")
            add(key,[d['method'],'日间 / 夜间按记录钟点分段，不代表实际清醒 / 睡眠；— 表示数据不足。'],[dict(title=p['label']+(' - RR ms / 频数' if key=='hrv_time' else ' - Hz / ms²/Hz'),xmax=2000 if key=='hrv_time' else .5,bars=key=='hrv_time',points=[dict(x=q['rr_ms' if key=='hrv_time' else 'hz'],y=q['count' if key=='hrv_time' else 'power']) for q in p['histogram' if key=='hrv_time' else 'psd']]) for p in periods],rows)
    return out


def make_supplement_pages(c,font,case,report,keys):
    def text(x,y,s,size=8):
        c.setFont(font,size);c.setFillGray(0);c.drawString((10+x)*mm,A4[1]-(10+y)*mm-size,str(s).replace('²','^2').replace('–','-').replace('·','-'))
    def plot(chart,top):
        points=chart['points'];valid=[p for p in points if isinstance(p.get('y'),(int,float))];height=160 if chart.get('scatter') else 60 if chart.get('xy') else 43
        text(0,top,chart['title'],8)
        if not valid:text(75,top+20,'无可用数据');return height+9
        lo=min(0,min(p['x'] for p in valid));hi=chart.get('xmax',max(lo+1e-6,max(p['x'] for p in valid)));yl=min(0,min(p['y'] for p in valid));yh=max(yl+1,max(p['y'] for p in valid))
        if chart.get('scatter'):lo=yl=0;hi=yh=max(2000,hi,yh)
        if chart.get('xy'):
            bound=max(abs(lo),abs(hi),abs(yl),abs(yh));lo=yl=-bound;hi=yh=bound
        pw=160 if chart.get('scatter') else 50 if chart.get('xy') else 172;ph=height-10
        px=lambda v:(22+(v-lo)/(hi-lo)*pw)*mm
        py=lambda v:A4[1]-(10+top+height-(v-yl)/(yh-yl)*ph)*mm
        c.setStrokeGray(.4);c.setLineWidth(.4);c.line(px(lo),py(yh),px(lo),py(yl));c.line(px(lo),py(yl),px(hi),py(yl));text(0,top+8,number(round(yh,2)),6);text(12,top+height+1,number(round(lo,2)),6);text(pw,top+height+1,number(round(hi,2)),6)
        c.setStrokeGray(0);c.setFillGray(0);c.setLineWidth(.6)
        if chart.get('scatter'):
            for p in valid:c.circle(px(p['x']),py(p['y']),.18*mm,stroke=0,fill=1)
        elif chart.get('bars'):
            bw=max(.18,min(2,172/max(1,len(points))*.8))*mm
            for p in valid:c.rect(px(p['x'])-bw/2,min(py(0),py(p['y'])),bw,max(.15,abs(py(p['y'])-py(0))),stroke=0,fill=1)
        else:
            path=c.beginPath();pen=False
            for p in points:
                if not isinstance(p.get('y'),(int,float)):pen=False;continue
                (path.lineTo if pen else path.moveTo)(px(p['x']),py(p['y']));pen=True
            c.drawPath(path)
        for m in chart.get('markers',[]):
            if lo<=m<=hi:
                c.setStrokeGray(.5);c.setDash(2,2);c.line(px(m),py(yl),px(m),py(yh));c.setDash()
        return height+9
    def draw(doc):
        text(0,10,doc['title'],13);y=20
        for paragraph in doc['paragraphs']:
            for row in wrap_text(paragraph,74):text(0,y,row,7);y+=4
            y+=2
        for chart in doc['charts']:y+=plot(chart,y)
        for row in doc['rows']:text(0,y,row,8);y+=5
    return [lambda doc=doc:draw(doc) for doc in documents(case,report,keys)]
