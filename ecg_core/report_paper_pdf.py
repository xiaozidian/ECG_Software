"""Monochrome A4 hospital-style report, matching report-paper.js/CSS."""
from __future__ import annotations

from datetime import datetime, timedelta
from io import BytesIO
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfgen.canvas import Canvas
from .report_layout import DEFAULT_LEADS


def number(x):
    return '—' if x is None else f'{x:g}' if isinstance(x, (int, float)) else str(x)


def wrap_text(text, width=53):
    lines = []
    for source in str(text or '（未填写）').split('\n'):
        line, measure = '', 0
        for ch in source:
            w = 1 if ord(ch) > 255 else .55
            if measure + w > width:
                lines.append(line)
                line, measure = '', 0
            line += ch
            measure += w
        lines.append(line)
    return lines


def clock(meta, seconds=0):
    try:
        dt = datetime.fromisoformat(str(meta.get('start_iso') or meta.get('start_time')).replace('Z', '+00:00'))
        return (dt + timedelta(seconds=seconds)).strftime('%Y-%m-%d %H:%M:%S')
    except (ValueError, TypeError):
        s = int(seconds)
        return f'D{s // 86400 + 1} {s % 86400 // 3600:02}:{s % 3600 // 60:02}:{s % 60:02}'


def build_paper_pdf(case, report, font):
    output = BytesIO()
    c = Canvas(output, pagesize=A4, pageCompression=1)
    c.setTitle(f"{case['case_id']} 心电分析复核报告")
    c.setAuthor('CardioInsight')
    meta, stats = case.get('metadata', {}), report.get('paper_statistics', {})
    summary, hrv = stats.get('summary', {}), stats.get('hrv', {})
    paper = report.get('composition', {}).get('paper', {})
    gain = float(str(paper.get('gain', '10 mm/mV')).split()[0])
    pages = []

    def text(x, y, value, size=9, align='left', gray=0):
        c.setFont(font, size)
        c.setFillGray(gray)
        draw = c.drawCentredString if align == 'center' else c.drawRightString if align == 'right' else c.drawString
        draw((10 + x) * mm, A4[1] - (10 + y) * mm - size, str(value).replace('·',' / ').replace('–','-'))

    def line(x1, y1, x2, y2, gray=0, thickness=.4):
        c.setStrokeGray(gray)
        c.setLineWidth(thickness)
        c.line((10+x1)*mm, A4[1]-(10+y1)*mm, (10+x2)*mm, A4[1]-(10+y2)*mm)

    def box(x, y, w, h, gray=0, fill=None):
        c.setLineWidth(.45)
        c.setStrokeGray(gray)
        if fill is not None:
            c.setFillGray(fill)
        c.rect((10+x)*mm, A4[1]-(10+y+h)*mm, w*mm, h*mm, fill=int(fill is not None), stroke=int(fill is None))

    def lines(x, y, values, size=9, step=4.4):
        for i, value in enumerate(values):
            text(x, y + i*step, value, size)

    def pairs(x, y, values, width=25):
        at = y
        for key, value in values:
            rows = wrap_text(f'{key}：{number(value)}', width)
            lines(x, at, rows, 9, 4.5)
            at += len(rows)*4.5
        return at

    def heading(label, y):
        text(95, y, label, 12, 'center')

    def summary_page(conclusion):
        s, opts = summary, stats.get('settings', {})
        text(95, 9, meta.get('hospital') or '动态心电图检测报告', 17, 'center')
        if meta.get('hospital'):
            text(95, 18, '动态心电图检测报告', 14, 'center')
        heading('检查信息', 26)
        exam = [
            [('姓名',meta.get('name')),('性别',meta.get('sex')),('年龄',str(meta.get('age','—'))+' 岁'),('起搏器',meta.get('pacemaker'))],
            [('ID号',meta.get('patient_id') or case['case_id']),('床位',meta.get('bed')),('记录时间',meta.get('start_time'))],
            [('申请医生',meta.get('requesting_doctor')),('申请科室',meta.get('department')),('记录时长',meta.get('duration_text'))],
            [('临床诊断',meta.get('clinical_diagnosis'))],
        ]
        box(0,33,190,25)
        for i, row in enumerate(exam):
            for j, (key,value) in enumerate(row):
                x = [2,54,97,154][j]
                short = wrap_text(f'{key}：{number(value)}', (190-x)/3.2 if len(row)==1 else 27 if len(row)==3 and j==2 else 24)
                lines(x,34+i*5.5,short,8.5,3)
        heading('分析统计',60)
        box(0,67,190,92)
        line(95,67,95,137)
        line(0,102,190,102)
        line(0,137,190,137)
        hr = lambda p: f"{number(p['hr'])} 次/分（{clock(meta,p['time_s'])[5:]}）" if p else '—'
        text(2,68,'概要',10)
        pairs(2,74,[('总心搏数',str(s.get('total','—'))+' 搏'),('伪差',str(s.get('noise','—'))+' 个'),('室性/室上性心搏',f"{s.get('V',{}).get('total','—')} / {s.get('S',{}).get('total','—')} 搏"),('最长 RR',f"{number(s['longest']['rr_ms']/1000)} 秒" if s.get('longest') else '—'),('发生时间',clock(meta,s['longest']['time_s'])[5:] if s.get('longest') else '—'),('长 RR 候选',f"{s.get('pause','—')} 次（≥{opts.get('pause','—')} s）")],28)
        text(97,68,'心率',10)
        pairs(97,74,[('最慢心率',hr(s.get('slowest'))),('平均心率',str(s.get('avg_hr','—'))+' 次/分'),('最快心率',hr(s.get('fastest'))),('快心率心搏',f"{s.get('tachy_beats','—')} 搏（≥{opts.get('tachy','—')} bpm）"),('慢心率心搏',f"{s.get('brady_beats','—')} 搏（≤{opts.get('brady','—')} bpm）"),('已确认房颤/房扑',str(s.get('af','—'))+' 段')],30)
        for code, x, title in [('V',2,'室性心搏'),('S',97,'室上性心搏')]:
            d = s.get(code,{})
            text(x,103,title,10)
            pairs(x,109,[('总数',f"{d.get('total','—')} 搏（{d.get('pct','—')}%）"),('单发',str(d.get('single','—'))+' 次'),('成对',str(d.get('couplet','—'))+' 对'),('短阵（≥3搏）',str(d.get('run','—'))+' 阵'),('二联律',str(d.get('bigeminy','—'))+' 阵'),('三联律',str(d.get('trigeminy','—'))+' 阵')],28)
        text(2,138,'心率变异性 · 当前修订 N-N',10)
        for i,(name,key,unit) in enumerate([('SDNN','sdnn_ms','ms'),('SDANN','sdann_ms','ms'),('SDNN index','sdnn_index_ms','ms'),('rMSSD','rmssd_ms','ms'),('pNN50','pnn50_pct','%'),('三角指数','triangular_index','')]):
            text(2+i%3*63,144+i//3*4,f'{name}: {number(hrv.get(key))} {unit}',8.5)
        source=case.get('summary',{})
        text(2,153,f"频域（源报告独立对照）：LF/HF {number(source.get('lf_hf'))} · LF {number(source.get('lf'))} · HF {number(source.get('hf'))}；— 表示未提供或样本不足。",7)
        lines(0,160,wrap_text(stats.get('method','当前修订结果，须医生复核。')+' 所有自动结果仍须医生核对。',74),7,3.2)
        heading('报告结论',174)
        box(0,181,190,86)
        lines(2,183,conclusion,10,4.9)
        text(2,261,'审核医生：'+(report.get('reviewed_by') or '未审核'),8)
        text(78,261,f"{'已审核' if report.get('status')=='reviewed' else '草稿'} v{report.get('version',1)}",8)
        text(188,261,'报告日期：'+str(report.get('updated_at') or '未保存')[:10],8,'right')

    blocks=[b.get('text','') for b in report.get('composition',{}).get('diagnosis_blocks',[]) if b.get('text')]
    conclusion=wrap_text((report.get('conclusion') or '（未填写）')+ ('\n图条说明（不替代诊断）：'+'；'.join(blocks) if blocks else ''))
    # Signature space is reserved. Long text always continues; it is never clipped.
    first=conclusion[:15]
    pages.append(lambda first=first:summary_page(first))
    for i in range(15,len(conclusion),48):
        chunk=conclusion[i:i+48]
        def continuation(chunk=chunk):
            heading('报告结论（续）',10)
            lines(2,21,chunk,10,4.9)
        pages.append(continuation)

    def hourly_page(rows, final):
        heading('统计表格',10)
        widths=[14,12,9,9,9]+[8.5]*14+[9,9]
        factor=190/sum(widths)
        widths=[w*factor for w in widths]
        xs=[0]
        for w in widths:xs.append(xs[-1]+w)
        line(0,19,190,19)
        for label,a,b in [('时间',0,1),('心搏数',1,2),('心率 bpm',2,5),('室性心搏',5,12),('室上性心搏',12,19),('房颤/扑',19,20),('长RR',20,21)]:
            text((xs[a]+xs[b])/2,20,label,7,'center')
        names=['','', '最慢','平均','最快']+['单发','成对','短阵','二联律','三联律','总计','%']*2+['段','候选']
        for i,label in enumerate(names):text((xs[i]+xs[i+1])/2,25,label,6.5,'center')
        line(0,30,190,30)
        for ri,r in enumerate(rows+([dict(summary,label='总计')] if final else [])):
            y=32+ri*7.9
            if ri==len(rows):line(0,y-1,190,y-1)
            values=[r.get('label',''),r.get('total'),r.get('min_hr'),r.get('avg_hr'),r.get('max_hr')]
            for code in ['V','S']:values.extend(r.get(code,{}).get(k) for k in ['single','couplet','run','bigeminy','trigeminy','total','pct'])
            values.extend([r.get('af'),r.get('pause')])
            for col,v in enumerate(values):
                if col==0 and ' ' in str(v):
                    date,hour=str(v).split(' ',1)
                    text((xs[0]+xs[1])/2,y,hour,7,'center')
                    text((xs[0]+xs[1])/2,y+3,date,6,'center')
                else:text((xs[col]+xs[col+1])/2,y,number(v),7,'center')
        line(0,32+(len(rows)+int(final))*7.9,190,32+(len(rows)+int(final))*7.9)
        lines(0,250,wrap_text(stats.get('method','')+' 首尾不足一小时按实际覆盖统计；无可用数据以 — 显示。',74),7,3.2)
    hourly=stats.get('hourly',[])
    for i in range(0,max(1,len(hourly)),25):
        rows=hourly[i:i+25]
        pages.append(lambda rows=rows,final=i+25>=len(hourly):hourly_page(rows,final))

    def waveform(entry, top, height):
        wave=entry['waveform'];spec=entry.get('strip',{});names=spec.get('leads') or list(wave.get('leads',{})) or DEFAULT_LEADS
        text(12,top,clock(meta,wave['start_s']),8)
        text(100,top+4.5,entry.get('display_caption') or entry.get('caption') or entry.get('label','心电图条'),9,'center')
        text(187,top,'HR: '+number(entry.get('hr'))+' bpm',8,'right')
        left,w=12,175
        grid_top,grid_bottom=top+18,top+height-14
        row=(grid_bottom-grid_top)/len(names)
        for x in range(176):line(left+x,grid_top,left+x,grid_bottom,.72 if x%5==0 else .9,.35 if x%5==0 else .18)
        for y in range(int(grid_bottom-grid_top)+1):line(left,grid_top+y,left+w,grid_top+y,.72 if y%5==0 else .9,.35 if y%5==0 else .18)
        for beat in wave.get('beats',[]):
            x=left+(beat['sample_index']/200-wave['start_s'])/wave['duration_s']*w
            if left<=x<=left+w:
                text(x,top+10,beat.get('class_code',''),6,'center')
                text(x,top+12.5,number(round(beat['hr'])) if beat.get('hr') else '—',5.5,'center')
                text(x,top+15,number(beat.get('rr_ms')),5.5,'center')
        def trace(values,x,y,width,scale,center,half,sample_rate=None,seconds=None):
            if not values:return False
            path=c.beginPath();clipped=False
            for i,v in enumerate(values):
                dx=i/sample_rate/seconds*width if sample_rate and seconds else i/max(1,len(values)-1)*width
                dy=(v-center)*scale
                lower,upper=half if isinstance(half,tuple) else (half,half)
                clipped |= dy>upper or dy < -lower
                px=(10+x+dx)*mm;py=A4[1]-(10+y-max(-lower,min(upper,dy)))*mm
                (path.moveTo if i==0 else path.lineTo)(px,py)
            c.setStrokeGray(0);c.setLineWidth(.5);c.drawPath(path)
            return clipped
        for j,name in enumerate(names):
            values=wave.get('leads',{}).get(name,[]);base=grid_top+(j+.65)*row
            median=sorted(values)[len(values)//2] if values else 0
            text(0,base-1,name,8)
            calibrated=wave.get('calibration_verified') is True
            per_unit=gain/1000 if calibrated else min(row*.62/max([1]+[v-median for v in values]),row*.32/max([1]+[median-v for v in values]))*.95
            pulse=gain if calibrated else min(5,row*.62*.8)
            for x,y,x2,y2 in [(6,base,7,base),(7,base,7,base-pulse),(7,base-pulse,9,base-pulse),(9,base-pulse,9,base),(9,base,10,base)]:line(x,y,x2,y2,0,.5)
            if not calibrated:text(0,base+2,f'{round(pulse/per_unit)}u',5)
            clipped=trace(values,left,base,w,per_unit,median,(row*.32,row*.62),wave.get('display_sample_rate_hz',200),wave['duration_s'])
            if clipped:text(187,grid_top+j*row,'幅度超框，请降低增益',6,'right')
        amplitude=f'{gain:g} mm/mV' if wave.get('calibration_verified') is True else '逐导联自适应幅度 · u = 设备单位，电压未校准'
        text(left,grid_bottom+.5,f"{w/wave['duration_s']:.2f} mm/s · {amplitude} · {wave['duration_s']:g} s",6.5)
        context=entry.get('context')
        if context:
            cy=grid_bottom+5
            box(left+(wave['start_s']-context['start_s'])/context['duration_s']*w,cy,wave['duration_s']/context['duration_s']*w,5,fill=.87)
            values=context.get('leads',{}).get('II',[]);median=sorted(values)[len(values)//2] if values else 0
            amplitude=max([50]+[abs(v-median) for v in values])
            trace(values,left,cy+2.5,w,2.2/amplitude,median,2.5)
            text(0,cy,'II',6)
            line(left,cy,left+w,cy,.25)
        text(left,top+height-3,spec.get('warning') or f"{spec.get('visible_beat_count',len(wave.get('beats',[])))} 搏 · {' / '.join(names)}",6.5)
    batch=[];units=0
    def flush():
        nonlocal batch,units
        if not batch:return
        captured=list(batch)
        def sheet():
            position=10
            for entry,u in captured:
                waveform(entry,position,u*83-4)
                position+=u*83
        pages.append(sheet);batch=[];units=0
    caption_notes=[]
    for i,original in enumerate(report.get('selected_waveforms',[])):
        entry=dict(original)
        caption=entry.get('caption') or entry.get('label','心电图条')
        caption_lines=wrap_text(caption,46)
        if len(caption_lines)>1:
            entry['display_caption']=f'[图条 {i+1}] {caption_lines[0]}…'
            caption_notes.extend(wrap_text(f'图条 {i+1}：{caption}',53)+[''])
        n=len(entry.get('strip',{}).get('leads') or entry['waveform']['leads'])
        unit=1 if n<=3 else 2 if n<=6 else 3
        if units+unit>3:flush()
        batch.append((entry,unit));units+=unit
        if units==3:flush()
    flush()
    def caption_page(rows):
        heading('图条说明（完整图注）',10)
        lines(0,22,rows,10,5.3)
    for offset in range(0,len(caption_notes),44):
        part=caption_notes[offset:offset+44]
        pages.append(lambda part=part:caption_page(part))
    for i,draw in enumerate(pages):
        text(0,0,'患者 ID：'+str(meta.get('patient_id') or case['case_id']),8)
        text(90,0,'姓名：'+str(meta.get('name') or '—'),8)
        text(190,0,'已审核' if report.get('status')=='reviewed' else '未审核 · 草稿',8,'right')
        line(0,5.5,190,5.5)
        draw()
        text(0,272,'研究与软件验证输出 · 需医生复核，不用于临床决策',7)
        text(190,272,f'第 {i+1} / {len(pages)} 页',7,'right')
        c.showPage()
    c.save();output.seek(0)
    return output
