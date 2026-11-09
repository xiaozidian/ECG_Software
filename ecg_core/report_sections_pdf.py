"""Optional evidence pages, using the same selection contract as the web preview."""
import math
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from .report_paper_pdf import clock, wrap_text, number
from .report_sections import PAGE_TITLES, rhythm_paragraphs

ST_LEADS=('I','II','III','aVR','aVL','aVF','V1','V2','V3','V4','V5','V6')


def _finite(value):
    return isinstance(value,(int,float)) and not isinstance(value,bool) and math.isfinite(value)


def _st_number(value,digits=2):
    if not _finite(value):return '—'
    scale=10**digits;rounded=math.floor(value*scale+.5)/scale
    return str(int(rounded)) if rounded.is_integer() else f'{rounded:.{digits}f}'.rstrip('0').rstrip('.')


def _duration(value):
    return f'{_st_number(value/60)} 分（{_st_number(value,3)} 秒）' if _finite(value) else '—'


def _st_clock(meta,value):
    result=clock(meta,value if _finite(value) else 0)
    return result[5:] if len(result)>10 and result[4:5]=='-' and result[7:8]=='-' else result


def _st_unit(evidence):
    return evidence['st_units'] if evidence.get('st_units') in ('mV','µV','μV') and evidence.get('st_calibration_verified') is True else 'u'


def _use(composition,row,purpose):
    event=row.get('selection_event_id',row['event_id'])
    if 'stt_report_use' in composition:
        return any(p.get('event_id')==event and p.get('basis_version')==row['basis_version'] and p.get(purpose) is True for p in composition.get('stt_report_use',[]))
    return any(p.get('event_id')==event and p.get('basis_version')==row['basis_version'] and (purpose!='text' or p.get('referenced_in_report') is True) for p in composition.get('selected_events',[]))


def _summary(e,composition,family='ST'):
    all_rows=e.get('t_events' if family=='T' else 'st_events',[]);summary=e.get('t_summary' if family=='T' else 'st_summary',{})
    count=summary.get('confirmed_lead_event_count');count=len(all_rows) if count is None else count
    return [f"{family}全记录已确认：导联事件 {_st_number(count,0)}，去重时段 {_st_number(summary.get('confirmed_time_group_count'),0)}，累计 {_duration(summary.get('confirmed_union_duration_s'))}",
        f"本次选用明细 {sum(_use(composition,row,'table') for row in all_rows)} / {len(all_rows)} 行；统计独立于图条选择。"]


def _protocol(e):
    profile=e.get('st_measurement_protocol') or {};measurement=profile.get('measurement_ms',profile.get('st_measurement_ms'))
    label=('STJ' if measurement==0 else 'ST'+_st_number(measurement)) if _finite(measurement) else '测量点见复核记录'
    return label+' · 逐分钟测量；可疑值标记，缺失处断线'


def _trend_document(case,report,key):
    e=report.get('section_evidence') or {};composition=report.get('composition') or {};meta=case.get('metadata') or {};family='T' if key=='t_trend' else 'ST';unit=_st_unit(e)
    metric='t_amplitude_units' if family=='T' else 'deviation_units' if composition.get('stt_trend_metric')=='delta' else 'st_level_units'
    label='T幅度' if family=='T' else 'ΔST（相对参考）' if metric=='deviation_units' else 'ST电平（相对ISO）'
    trends=e.get('st_trends') or {};rows=[]
    for lead in ST_LEADS:
        source=trends.get(lead,[])
        points=[dict(x=p['time_s']/3600 if _finite(p.get('time_s')) else None,y=p.get(metric) if _finite(p.get(metric)) else None,
            quality_suspected=p.get('eligible') is False or bool(p.get('axis_shift_suspected')) or bool(p.get('quality_flags')),
            coverage_pct=p.get('coverage_pct'),quality_flags=p.get('quality_flags',[])) for p in source]
        rows.append(dict(lead=lead,points=points,valid_minutes=sum(_finite(p['y']) for p in points),total_minutes=len(source)))
    heart=[]
    for p in e.get('heart_rate_trend',[]):
        value=p.get('hr',p.get('bpm'))
        heart.append(dict(x=p['time_s']/3600 if _finite(p.get('time_s')) else None,y=None if p.get('eligible') is False or not _finite(value) or value<=0 else value))
    extent=max([0]+[p.get('end_s') if _finite(p.get('end_s')) else p.get('time_s') if _finite(p.get('time_s')) else 0 for lead in ST_LEADS for p in trends.get(lead,[])]+[p['x']*3600 for p in heart if _finite(p['x'])])
    duration=(case.get('technical') or {}).get('duration_seconds_raw')
    if duration is None:duration=e.get('st_duration_s')
    if duration is None:duration=extent
    xmax=duration/3600 if _finite(duration) and duration>0 else 1
    labels=dict(reference='ΔST参考搏' if metric=='deviation_units' else '实际参考搏',st_min='最深ST电平',st_max='最高ST电平',delta_peak='最大ΔST')
    roles=[] if family=='T' else ['reference','delta_peak'] if metric=='deviation_units' else ['reference','st_min','st_max']
    reps=[]
    for role in roles:
        rep=next((r for r in e.get('st_representatives',[]) if r.get('role')==role and (metric!='deviation_units' or r.get('metric')=='deviation_units')),None)
        reps.append({**rep,'role':role,'label':rep.get('label') or labels[role],'clock':_st_clock(meta,rep.get('time_s')) if _finite(rep.get('time_s')) else '—'} if rep else dict(role=role,label=labels[role],lead=None,time_s=None,clock='—',waveform=None))
    if family=='T':
        reps=[{**rep,'clock':_st_clock(meta,rep.get('time_s')) if _finite(rep.get('time_s')) else '—'} for rep in e.get('t_representatives',[])[:3]]
    ticks=[]
    for i in range(7):
        t=_st_clock(meta,xmax*i/6*3600);ticks.append(dict(x=xmax*i/6,label=t[:-3] if len(t)>=3 and t[-3:-2]==':' else t))
    return dict(key=key,title='十二导联 T 波幅度趋势' if family=='T' else '十二导联 ST 分析',paragraphs=[f"{label} · {unit}"+('（电压未标定）' if unit=='u' else ''),_protocol(e)+'；灰色虚线为可疑测量'],charts=[],rows=[],layout='stt_trend',metric=metric,metric_label=label,unit=unit,x_max=xmax,time_ticks=ticks,trend_rows=rows,heart_rate=heart,summary_lines=_summary(e,composition,family),representatives=reps)


def _st_event_documents(case,report):
    e=report.get('section_evidence') or {};composition=report.get('composition') or {};meta=case.get('metadata') or {};unit=_st_unit(e);docs=[]
    for family in ('ST','T'):
        source=e.get('st_events' if family=='ST' else 't_events',[]);chosen=[r for r in source if _use(composition,r,'table')]
        if family=='T' and not chosen:continue
        columns=['导联','类型','起止时间','持续时间',f'平均{family} ({unit})',f'极值{family} ({unit})',f"最大{'ΔST' if family=='ST' else 'ΔT'} ({unit})"]+(['斜率'] if family=='ST' else [])
        rows=[]
        for row in chosen:
            kind=dict(st_depression='ST压低',st_elevation='ST抬高',t_wave_inversion='T极性反转',t_change='T改变（未细分）',t_persistent_inversion='T持续倒置',t_low_flat='T低平',t_biphasic='双相T').get(row.get('kind',row.get('result_kind')),'T改变' if family=='T' else 'ST改变')
            cells=[row.get('lead') or '/'.join(row.get('leads',[])) or '—',kind,_st_clock(meta,row.get('start_s'))+'\n'+_st_clock(meta,row.get('end_s')),_duration(row.get('duration_s')),
                _st_number(row.get('mean_st_level_units' if family=='ST' else 'mean_t_amplitude_units')),_st_number(row.get('extreme_st_level_units' if family=='ST' else 'extreme_t_amplitude_units')),_st_number(row.get('peak_deviation_units'))]
            if family=='ST':cells.append(_st_number(row['slope'])+' '+row['slope_unit'] if _finite(row.get('slope')) and row.get('slope_unit') else '—')
            rows.append(dict(event_id=row['event_id'],basis_version=row['basis_version'],row_id=row.get('row_id',row['event_id']),cells=cells))
        for i in range(0,max(1,len(rows)),24):
            part=rows[i:i+24]
            docs.append(dict(key='st_events',title=family+'事件明细'+('（续）' if i else ''),paragraphs=[*_summary(e,composition,family),f"完整事件起止独立于代表图条；幅度 {unit}"+('，非mV' if unit=='u' else '')+'；— 表示未提供测量；低平T极值为最小绝对幅度。'],charts=[],rows=[' · '.join(r['cells']) for r in part] if part else [f'当前没有选用的已确认{family}事件；不表示正常或已排除。'],layout='stt_table',columns=columns,table_rows=part))
    records={}
    for row in e.get('st_review_notes',[])+e.get('st_events',[])+e.get('t_events',[]):records.setdefault((row['event_id'],row['basis_version']),row)
    notes=[r for r in records.values() if _use(composition,r,'text')]
    lines=[]
    for row in notes:
        text=_st_clock(meta,row.get('start_s'))+' — '+_st_clock(meta,row.get('end_s'))+' · '+row.get('label','ST-T复核')
        note=row.get('physician_note',row.get('note'))
        if note:text+=' · '+note
        if row.get('range_statistics') or row.get('review_kind')=='range_mean':text+=' · 范围均值；此范围不证明连续ST事件。'
        elif not row.get('stt_event_evidence') and row.get('review_kind')=='point_or_legacy_range':text+=' · 点复核／旧范围；此范围不证明连续ST事件。'
        lines.extend(wrap_text(text,70))
    for i in range(0,len(lines),28):docs.append(dict(key='st_events',title='ST-T复核说明'+('（续）' if i else ''),paragraphs=[] if i else ['本次采用的复核意见；未见改变、伪差及无法判读不计入已确认异常事件。'],charts=[],rows=lines[i:i+28]))
    return docs


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
            r=e.get('scatter',{});add(key,[f"相邻 RR 配对 {number(r.get('total'))} 个；图中等间隔抽取 1/{number(r.get('stride'))} 显示，统计保留全量。"],[dict(title='Lorenz RR(i) / RR(i+1) · ms',points=r.get('points',[]),scatter=True)])
        if key=='pacing':
            r=e.get('pacing',{});add(key,[r.get('method','无可用数据')],rows=[f'{k} 起搏标记：{number(n)} 搏' for k,n in r.get('counts',{}).items()]+[f"起搏类型总标记数：{number(r.get('total'))} 搏；0 不等同排除起搏器。"])
        if key=='af':add(key,[*rhythm_paragraphs(e.get('af_summary')),'片段确认与报告整体审核是独立状态；自动 RR 不规则筛查不等同房颤诊断。','本页仅汇总已保存片段，不证明全程已评估；无片段或未提示不能排除房颤，未评估时段须回看原始波形。'],rows=[f"{clock(meta,r['time_s'])} · {(r['end_s']-r['time_s'])/60:.2f} 分钟 · {r['label']} · {'医生确认' if r['status']=='confirmed' else '待复核'}" for r in e.get('af',[])])
        if key in ('hrt','dc'):
            r=e.get(key,{})
            stats=f"合格室早 {number(r.get('eligible_pvc'))}；TO {number(r.get('to_pct'))} %；TS {number(r.get('ts_ms_per_rr'))} ms/RR" if key=='hrt' else f"减速锚点 {number(r.get('anchor_count'))}；DC {number(r.get('dc_ms'))} ms"
            add(key,[r.get('method','无可用数据'),stats,'— 表示样本不足或无可用结果，不代表正常。'],[dict(title='平均恢复 RR · ms / 序号' if key=='hrt' else 'PRSA · RR ms / 相对锚点',points=r.get('tachogram' if key=='hrt' else 'prsa',[]))])
        if key in ('st_trend','t_trend'):out.append(_trend_document(case,report,key))
        if key=='st_events':out.extend(_st_event_documents(case,report))
        if key in ('hrv_time','hrv_frequency'):
            if not d:raise ValueError('HRV 数据尚未加载')
            periods=[d['periods'][k] for k in ('full','day','night')];rows=[]
            for p in periods:
                rows.append(p['label']);f=p['frequency']
                rows.append(f"NN {p['nn_count']}；SDNN {number(p.get('sdnn_ms'))} ms；SDANN {number(p.get('sdann_ms'))} ms；rMSSD {number(p.get('rmssd_ms'))} ms；pNN50 {number(p.get('pnn50_pct'))} %" if key=='hrv_time' else f"总功率 {number(f['total_ms2'])}；VLF {number(f['vlf_ms2'])}；LF {number(f['lf_ms2'])}；HF {number(f['hf_ms2'])} ms²；LF/HF {number(f['lf_hf'])}")
            review=d.get('hrv_review');proof=[]
            if review:
                status='医生已声明核实本窗口节律与伪差' if review['confirmation'].get('valid') else '本窗口窦性与信号质量尚未核实'
                proof=[f"fixed-300s-fft-compat-v1 / HRV r{review['hrv_revision']} / {review['digest'][:12]} / {status}"]
            add(key,[d['method'],*proof,'日间 / 夜间按记录钟点分段，不代表实际清醒 / 睡眠；— 表示数据不足。'],[dict(title=p['label']+(' - RR ms / 频数' if key=='hrv_time' else ' - Hz / ms²/Hz'),xmax=2000 if key=='hrv_time' else .5,bars=key=='hrv_time',points=[dict(x=q['rr_ms' if key=='hrv_time' else 'hz'],y=q['count' if key=='hrv_time' else 'power']) for q in p['histogram' if key=='hrv_time' else 'psd']]) for p in periods],rows)
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
    def stt_trend(doc):
        text(0,9,doc['title'],12)
        for i,p in enumerate(doc['paragraphs']):text(0,17+i*4,p,7)
        left,right,top,hr_height,row_height=15,190,29,13,10.5
        xmax=doc['x_max'];width=right-left
        bound=max([1]+[abs(p['y']) for row in doc['trend_rows'] for p in row['points'] if _finite(p.get('y'))])
        hr_bound=max([200]+[p['y'] for p in doc['heart_rate'] if _finite(p.get('y'))])
        px=lambda x:(10+left+x/xmax*width)*mm
        py=lambda y:A4[1]-(10+y)*mm
        def row(label,points,y0,height,lo,hi):
            value_y=lambda value:y0+height-1-(value-lo)/(hi-lo)*(height-2)
            c.setStrokeGray(.35);c.setLineWidth(.35);c.rect(px(0),py(y0+height),width*mm,height*mm,stroke=1,fill=0)
            text(0,y0+height/2-1,label,8)
            text(8,y0+.3,_st_number(hi),5.5);text(8,y0+height-2.5,_st_number(lo),5.5)
            c.setStrokeGray(.78);c.setLineWidth(.25)
            for tick in doc['time_ticks']:c.line(px(tick['x']),py(y0),px(tick['x']),py(y0+height))
            if lo<=0<=hi:
                c.setStrokeGray(.65);c.setDash(1,1);c.line(px(0),py(value_y(0)),px(xmax),py(value_y(0)));c.setDash()
            normal=c.beginPath();suspect=c.beginPath();previous=None;valid=[]
            for point in points:
                if not _finite(point.get('x')) or not _finite(point.get('y')):previous=None;continue
                if previous is not None:
                    path=suspect if point.get('quality_suspected') or previous.get('quality_suspected') else normal
                    path.moveTo(px(previous['x']),py(value_y(previous['y'])))
                    path.lineTo(px(point['x']),py(value_y(point['y'])))
                previous=point;valid.append(point)
            c.setStrokeGray(0);c.setLineWidth(.45);c.drawPath(normal)
            c.setStrokeGray(.5);c.setDash(1,1);c.drawPath(suspect);c.setDash()
            if len(valid)==1:c.circle(px(valid[0]['x']),py(value_y(valid[0]['y'])),.3*mm,stroke=0,fill=1)
            if not valid:text(left+3,y0+height/2-1,'无有效测量',6)
        row('心率',doc['heart_rate'],top,hr_height,0,hr_bound)
        for i,r in enumerate(doc['trend_rows']):row(r['lead'],r['points'],top+hr_height+i*row_height,row_height,-bound,bound)
        y=top+hr_height+len(doc['trend_rows'])*row_height
        for i,tick in enumerate(doc['time_ticks']):
            label=tick['label'];x=left+tick['x']/xmax*width
            if i==len(doc['time_ticks'])-1:x-=len(label)*1.05
            elif i:x-=len(label)*.5
            text(x,y+1,label,6)
        y+=9
        for line in doc['summary_lines']:text(0,y,line,7);y+=4.5
        reps=doc['representatives']
        if not reps:return
        y+=2;cell=190/len(reps)
        for i,rep in enumerate(reps):
            x0=i*cell;c.setStrokeGray(.35);c.setLineWidth(.4);c.rect((10+x0)*mm,py(y+38),cell*mm,38*mm,stroke=1,fill=0)
            text(x0+2,y+1,rep['label'],8);text(x0+2,y+6,(rep.get('lead') or '—')+' · '+rep['clock']+' · '+doc['unit'],6)
            wave=rep.get('waveform') or {};lead=rep.get('lead') or next(iter(wave.get('leads',{})),None);values=wave.get('leads',{}).get(lead,[]);valid=[v for v in values if _finite(v)]
            if len(valid)<2 or not _finite(wave.get('start_s')) or not _finite(wave.get('duration_s')) or wave['duration_s']<=0:
                text(x0+5,y+22,'暂无真实代表搏',7);continue
            low,high=min(valid),max(valid);span=max(1,high-low);path=c.beginPath();pen=False
            for j,value in enumerate(values):
                if not _finite(value):pen=False;continue
                x=(10+x0+2+j/max(1,len(values)-1)*(cell-4))*mm;yy=py(y+34-(value-low)/span*20)
                (path.lineTo if pen else path.moveTo)(x,yy);pen=True
            c.setStrokeGray(0);c.setLineWidth(.5);c.drawPath(path)
            if _finite(rep.get('time_s')):
                anchor=(rep['time_s']-wave['start_s'])/wave['duration_s']
                if 0<=anchor<=1:
                    x=(10+x0+2+anchor*(cell-4))*mm;c.setStrokeGray(.5);c.setDash(1,1);c.line(x,py(y+12),x,py(y+35));c.setDash()
    def stt_table(doc):
        text(0,9,doc['title'],12);y=18
        for paragraph in doc['paragraphs']:
            for line in wrap_text(paragraph,85):text(0,y,line,7);y+=4
        y+=3
        widths=[10,16,39,27]+[98/(len(doc['columns'])-4)]*(len(doc['columns'])-4)
        xs=[0]
        for width in widths:xs.append(xs[-1]+width)
        def cells(values,top,height,header=False):
            c.setStrokeGray(.4);c.setLineWidth(.35)
            for i,value in enumerate(values):
                c.rect((10+xs[i])*mm,A4[1]-(10+top+height)*mm,widths[i]*mm,height*mm,stroke=1,fill=0)
                lines=str(value).split('\n')
                if i!=2:lines=[line for source in lines for line in wrap_text(source,max(4,int(widths[i]/2.15)))]
                for j,line in enumerate(lines[:3]):text(xs[i]+.8,top+.7+j*2.6,line,6.4 if i==2 else 6.8 if header else 6.5)
        cells(doc['columns'],y,11,True);y+=11
        for record in doc['table_rows']:cells(record['cells'],y,8.3);y+=8.3
        if not doc['table_rows']:text(0,y+3,doc['rows'][0],8)
    def draw(doc):
        if doc.get('layout')=='stt_trend':return stt_trend(doc)
        if doc.get('layout')=='stt_table':return stt_table(doc)
        text(0,10,doc['title'],13);y=20
        for paragraph in doc['paragraphs']:
            for row in wrap_text(paragraph,74):text(0,y,row,7);y+=4
            y+=2
        for chart in doc['charts']:y+=plot(chart,y)
        for row in doc['rows']:text(0,y,row,8);y+=5
    return [lambda doc=doc:draw(doc) for doc in documents(case,report,keys)]
