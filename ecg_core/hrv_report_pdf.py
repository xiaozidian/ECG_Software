"""A4 HRV evidence pages. Consumes computed values only; no clinical inference."""
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from .report_paper_pdf import wrap_text


def make_hrv_pages(c, font, data):
    def n(value): return '—' if value is None else str(round(value,2)) if isinstance(value,(float,int)) else str(value)
    def text(x,y,value,size=7,align='left'):
        c.setFont(font,size);c.setFillGray(0)
        method=c.drawCentredString if align=='center' else c.drawRightString if align=='right' else c.drawString
        method((10+x)*mm,A4[1]-(10+y)*mm-size,str(value).replace('–','-').replace('·','/').replace('²','^2'))
    def line(x,y,x2,y2):
        c.setStrokeGray(.2);c.setLineWidth(.35);c.line((10+x)*mm,A4[1]-(10+y)*mm,(10+x2)*mm,A4[1]-(10+y2)*mm)
    def rect(x,y,w,h,fill=False):
        c.setFillGray(.12);c.setStrokeGray(.3);c.setLineWidth(.3);c.rect((10+x)*mm,A4[1]-(10+y+h)*mm,w*mm,h*mm,fill=int(fill),stroke=int(not fill))
    def prose(x,y,value,width=53,size=6.8,step=3.1):
        for i,row in enumerate(wrap_text(value,width)):text(x,y+i*step,row,size)
    def plot(points,xkey,ykey,x,y,w,h,bars=False,xmax=None,unit=''):
        valid=[p for p in points if isinstance(p.get(ykey),(int,float)) and isinstance(p.get(xkey),(int,float))]
        if not valid: text(x+w/2,y+h/2,'无可用数据',7,'center');return
        lo=min(0,min(p[ykey] for p in valid));hi=max(lo+1,max(p[ykey] for p in valid));xmax=xmax or max(1,max(p[xkey] for p in valid))
        l,t,r,b=9,4,2,5;pw,ph=w-l-r,h-t-b
        xx=lambda v:x+l+v/xmax*pw
        yy=lambda v:y+t+(hi-v)/(hi-lo)*ph
        line(x+l,y+t,x+l,y+h-b);line(x+l,y+h-b,x+w-r,y+h-b)
        text(x,y,unit,5.5);text(x+l-1,y+t,n(hi),5,'right');text(x+l-1,y+h-b-1,n(lo),5,'right');text(x+l,y+h-b+1,'0',5);text(x+w-r,y+h-b+1,n(xmax),5,'right')
        c.setStrokeGray(0);c.setLineWidth(.5)
        if bars:
            bw=max(.15,min(2.4,pw/max(1,len(points))*.8))
            for p in valid:rect(xx(p[xkey])-bw/2,min(yy(0),yy(p[ykey])),bw,max(.08,abs(yy(0)-yy(p[ykey]))),True)
        else:
            path=c.beginPath();pen=False
            for p in points:
                if p.get(ykey) is None:pen=False;continue
                at=((10+xx(p[xkey]))*mm,A4[1]-(10+yy(p[ykey]))*mm)
                if pen:path.lineTo(*at)
                else:path.moveTo(*at)
                pen=True
            c.drawPath(path)
            # Preserve isolated measurements without joining across missing data.
            for i,p in enumerate(points):
                if p.get(ykey) is not None and (i==0 or points[i-1].get(ykey) is None) and (i==len(points)-1 or points[i+1].get(ykey) is None):
                    c.setFillGray(0);c.circle((10+xx(p[xkey]))*mm,A4[1]-(10+yy(p[ykey]))*mm,.65,stroke=0,fill=1)
    def table(rows,columns,x,y,w,rowh=4,size=6.5):
        width=w/len(columns);line(x,y,x+w,y)
        for i,(_,label) in enumerate(columns):text(x+(i+.5)*width,y+.5,label,size,'center')
        line(x,y+rowh,x+w,y+rowh)
        for j,row in enumerate(rows):
            for i,(key,_) in enumerate(columns):text(x+(i+.5)*width,y+(j+1)*rowh+.5,n(row.get(key)),size,'center')
        line(x,y+(len(rows)+1)*rowh,x+w,y+(len(rows)+1)*rowh)
    periods=[data['periods'][key] for key in ('full','day','night')]
    hours=[dict(h,hour=(h['start_s']-data['start_s'])/3600,power=h['frequency']['total_ms2']) for h in data['hourly']]
    limit=data['actual_duration_s']/3600
    def first():
        text(95,9,'心率变异性分析报告',12,'center')
        text(0,16,f"窗口 {data['window_index']+1} / 实际覆盖 {limit:.2f} 小时 / 缺失不补齐",7)
        for i,p in enumerate(periods):
            x=i*190/3;w=190/3;rect(x,22,w,113)
            prose(x+2,24,p['label'],26,7,3)
            plot(p['psd'],'hz','power',x+1,34,w-2,28,xmax=.5,unit='ms²/Hz')
            keys=[('mean_nn_ms','平均 NN ms'),('sdnn_ms','SDNN ms'),('sdann_ms','SDANN ms'),('sdnn_index_ms','SDNN index ms'),('rmssd_ms','rMSSD ms'),('pnn50_pct','pNN50 %'),('triangular_index','三角指数')]
            for j,(k,label) in enumerate(keys):text(x+3,63+j*3.4,label,7);text(x+w-3,63+j*3.4,n(p[k]),7,'right')
            text(x+3,88,f"NN {p['nn_count']} / 频谱 {p['spectral_blocks']} 段",6.5)
            text(x+3,92,f"有效 NN {p['valid_nn_s']/3600:.2f} / 覆盖 {p['coverage_s']/3600:.2f} h",6)
            plot(p['histogram'],'rr_ms','count',x+1,97,w-2,31,True,max(2000,max((v['rr_ms']+8 for v in p['histogram']),default=0)),'个 / RR ms')
            text(x+3,129,f"{p['five_minute_blocks']} 个合格 5 分钟段",6.5)
        rect(0,137,190,79);line(107,137,107,216)
        for j,(key,label) in enumerate([('avg_hr','心率 bpm'),('sdnn_ms','SDNN ms'),('rmssd_ms','rMSSD ms'),('pnn50_pct','pNN50 %')]):plot(hours,'hour',key,1,138+j*19,104,19,key!='avg_hr',limit,label)
        text(148,139,'SDNN 与 NN 心率关系',8,'center')
        table(data['rate_sdnn'],[('hr_range','bpm'),('minute_bins','分钟桶'),('sdnn_ms','SDNN ms')],110,145,77,4.3)
        prose(110,177,'分钟桶为有数据分钟；按分钟平均 NN 心率分组，组内 NN 重算 SDNN。',29,6.5,3)
        text(148,188,f"SDNN {n(data['periods']['full']['sdnn_ms'])} ms",11,'center')
        prose(110,194,'统计参考，不自动分高/中/低风险。结合时长、节律、伪差与临床情况。',29,6.5,3)
        text(110,209,'医生解释：____________________',7)
        table([dict(p['frequency'],label=['全程','日间','夜间'][i]) for i,p in enumerate(periods)],
              [('label','时段'),('total_ms2','总功率 ms²'),('vlf_ms2','VLF ms²'),('lf_ms2','LF ms²'),('hf_ms2','HF ms²'),('lf_hf','LF/HF')],0,221,190,5)
        prose(0,244,data['method']+' — 为数据不足。LF 0.04–0.15 Hz；HF 0.15–0.40 Hz；总功率 0.0033–0.40 Hz。',75,6.5,3)
    def second(rows,continuation=False):
        text(95,9,'记录趋势报告'+('（统计续页）' if continuation else ''),12,'center')
        top=20
        if not continuation:
            minute=[dict(p,hour=(p['time_s']-data['start_s'])/3600) for p in data['trend']]
            st={}
            for series in data.get('st_trends',{}).values():
                for p in series:
                    if not data['start_s']<=p['time_s']<data['end_s'] or p.get('deviation_units') is None:continue
                    k=int((p['time_s']-data['start_s'])/60)
                    if k not in st or abs(p['deviation_units'])>abs(st[k]['value']):st[k]={'hour':k/60,'value':p['deviation_units']}
            st_points=[st.get(k,{'hour':k/60,'value':None}) for k in range(len(minute))]
            charts=[('心率 NN / bpm',minute,'hr',False,'fastest'),('ST 变化 / 设备单位',st_points,'value',False,None),('1分钟 SDNN / ms',minute,'sdnn_ms',False,'hist'),('频域总功率 / ms²',hours,'power',True,'psd'),('室早 / 每小时',hours,'v_count',True,'V'),('房早 / 每小时',hours,'s_count',True,'S'),('长 RR >2.5s / 小时',hours,'pause_count',True,'pause')]
            # Reserve enough paper height for readable 6.3 pt, two-line hourly rows.
            chart_height=16
            for j,(label,points,key,bars,side) in enumerate(charts):
                y=top+j*chart_height;rect(0,y,190,chart_height);text(1,y+6,label,6);line(29,y,29,y+chart_height);line(146,y,146,y+chart_height)
                plot(points,'hour',key,29,y,117,chart_height,bars,limit,'相对小时')
                if side=='hist':plot(periods[0]['histogram'],'rr_ms','count',147,y,42,chart_height,True,2000,'RR ms')
                elif side=='psd':plot(periods[0]['psd'],'hz','power',147,y,42,chart_height,False,.5,'ms²/Hz')
                elif side:
                    targets=['fastest','slowest'] if side=='fastest' else [side]
                    for k,category in enumerate(targets):
                        entry=next((e for e in data.get('representatives',[]) if e['category']==category),None)
                        at=y+k*chart_height/2
                        if not entry:text(148,at+4,'无可用候选',6);continue
                        wave=entry['waveform'];values=wave['leads'].get('II',[])
                        # Small raw trace with its rate; no fabricated calibration.
                        text(148,at,('最快 ' if category=='fastest' else '最慢 ' if category=='slowest' else '')+n(entry.get('hr'))+' bpm',5)
                        if values:
                            peak=max(50,max(abs(v) for v in values));path=c.beginPath()
                            for vi,v in enumerate(values):
                                coords=((158+vi/max(1,len(values)-1)*40)*mm,A4[1]-(10+at+5-v/peak*2)*mm)
                                path.lineTo(*coords) if vi else path.moveTo(*coords)
                            c.setStrokeGray(0);c.setLineWidth(.35);c.drawPath(path)
                else:prose(148,y+2,'跨导联最大绝对偏移\n未标定，非 mV\n缺失不等于正常',18,6,3)
            top=135
        columns=[('label','时间'),('total_beats','心搏'),('avg_hr','平均'),('min_hr','最慢'),('max_hr','最快'),('stI','ΔI'),('stII','ΔII'),('stIII','ΔIII')]
        columns += [(c+key,c+label) for c in ('S','V') for key,label in [('single','单发'),('couplet','成对'),('run','短阵'),('bigeminy','二联'),('trigeminy','三联'),('total','总数')]]
        columns += [('af','房颤/扑'),('block','阻滞'),('pause_count','>2.5s'),('pause_over3','>3s')]
        detail=[]
        for h in rows:
            stats=next((s for s in data.get('event_statistics',{}).get('hourly',[]) if s['start_s']==h['start_s'] and s['end_s']==h['end_s']),{})
            r=dict(h,block=None,af=stats.get('af'))
            for lead in ('I','II','III'):
                values=[p['deviation_units'] for p in data.get('st_trends',{}).get(lead,[]) if h['start_s']<=p['time_s']<h['end_s'] and isinstance(p.get('deviation_units'),(int,float))]
                r['st'+lead]=round(max(values,key=abs),1) if values else None
            for code in ('S','V'):
                for key in ('single','couplet','run','bigeminy','trigeminy','total'):r[code+key]=stats.get(code,{}).get(key)
            detail.append(r)
        # Dense hospital-style hourly table; first column gets date + clock on two lines.
        widths=[14]+[176/(len(columns)-1)]*(len(columns)-1);line(0,top,190,top)
        offset=0
        for (key,label),width in zip(columns,widths):text(offset+width/2,top+1,label,6.3,'center');offset+=width
        line(0,top+5,190,top+5)
        row_height=4.6
        for j,r in enumerate(detail):
            offset=0;y=top+5+j*row_height
            for (key,_),width in zip(columns,widths):
                if key=='label':
                    parts=str(r[key]).split();text(width/2,y,parts[-1],6.3,'center')
                    if len(parts)>1:text(width/2,y+2.3,parts[0],6.3,'center')
                else:text(offset+width/2,y+.5,n(r.get(key)),6.3,'center')
                offset+=width
        end=top+5+len(detail)*row_height;line(0,end,190,end)
        prose(0,end+3,'S 房早 / V 室早。单发、成对、短阵及联律按起点计次，模式可重叠；总数为心搏数。Δ 为每小时最大绝对 ST 偏移，保留正负、设备单位，非 mV。房颤/扑仅计医生确认片段；房室阻滞暂无可靠统计，显示 —。HRV 为 N-N，极值小图为 RR 候选；首尾小时按实际覆盖，候选不等同确诊。',75,6.5,3)
    pages=[first]
    for i in range(0,max(1,len(hours)),25):
        rows=hours[i:i+25];pages.append(lambda rows=rows,continued=i>0:second(rows,continued))
    return pages
