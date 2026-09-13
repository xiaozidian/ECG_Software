from __future__ import annotations

import html
from io import BytesIO

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from .config import APP_VERSION

FONT_NAME = "STSong-Light"
REPORT_PAGE_LABELS = {
    "cover": "封面", "summary": "首页报告", "hourly": "小时统计表格", "scatter": "散点图",
    "st_trend": "ST趋势图", "t_trend": "T波趋势图", "event_strips": "事件图条", "st_events": "ST事件",
    "pacing": "起搏报告", "af": "房颤/房扑", "hrv_time": "HRV时域报告", "hrv_frequency": "HRV频域报告",
    "hrv_overview": "HRV概述", "hrt": "心率震荡(HRT)报告", "qtd": "QT离散度(QTd)报告",
    "vcg": "心电向量(VCG)报告", "dc": "心率减速力(DC)报告", "twa": "T波电交替(TWA)报告",
    "vlp": "心室晚电位(VLP)报告", "sap": "睡眠窒息(SAP)报告",
}


def _register_font() -> None:
    try:
        pdfmetrics.getFont(FONT_NAME)
    except KeyError:
        pdfmetrics.registerFont(UnicodeCIDFont(FONT_NAME))


def build_report_pdf(case: dict, calculated: dict, report: dict) -> BytesIO:
    if "selected_waveforms" in report:return build_composed_pdf(case,calculated,report)
    _register_font()
    output = BytesIO()
    doc = SimpleDocTemplate(
        output,
        pagesize=A4,
        leftMargin=18 * mm,
        rightMargin=18 * mm,
        topMargin=15 * mm,
        bottomMargin=16 * mm,
        title=f"{case['case_id']} 心电分析复核报告",
    )
    styles = getSampleStyleSheet()
    title = ParagraphStyle("CJKTitle", parent=styles["Title"], fontName=FONT_NAME, fontSize=18, leading=24, alignment=TA_CENTER, textColor=colors.HexColor("#123047"))
    heading = ParagraphStyle("CJKHeading", parent=styles["Heading2"], fontName=FONT_NAME, fontSize=12, leading=18, textColor=colors.HexColor("#0b7d7b"), spaceBefore=8, spaceAfter=5)
    body = ParagraphStyle("CJKBody", parent=styles["BodyText"], fontName=FONT_NAME, fontSize=9.5, leading=15, textColor=colors.HexColor("#243746"))
    small = ParagraphStyle("CJKSmall", parent=body, fontSize=8, leading=12, textColor=colors.HexColor("#657786"))
    table_cell = ParagraphStyle("CJKTableCell", parent=body, fontSize=8.5, leading=11, wordWrap="CJK", splitLongWords=True)
    warning = ParagraphStyle("CJKWarning", parent=body, backColor=colors.HexColor("#fff4e8"), borderColor=colors.HexColor("#ed8b3a"), borderWidth=0.7, borderPadding=7, textColor=colors.HexColor("#7a3d0b"))

    meta = case["metadata"]
    source = case["summary"]

    def cell(value) -> Paragraph:
        return Paragraph(html.escape(str(value or "")), table_cell)

    story = [
        Paragraph("动态心电分析复核报告", title),
        Paragraph('<font name="Helvetica">CardioInsight Holter</font><font name="STSong-Light"> / 研究演示版</font>', small),
        Spacer(1, 7 * mm),
        Paragraph("使用边界", heading),
        Paragraph("本报告由研究演示软件生成，仅用于软件验证与医生人工复核演示，不构成临床诊断，不替代持证医疗器械、医生判读或医院正式报告。", warning),
        Paragraph("检查信息", heading),
    ]
    meta_rows = [
        [cell("姓名"), cell(meta.get("name", "")), cell("性别/年龄"), cell(f"{meta.get('sex', '')} / {meta.get('age', '')}岁")],
        [cell("患者ID"), cell(meta.get("patient_id", "")), cell("病例目录"), cell(case["case_id"])],
        [cell("记录时间"), cell(meta.get("start_time", "")), cell("记录时长"), cell(meta.get("duration_text", ""))],
        [cell("申请科室"), cell(meta.get("department", "")), cell("临床诊断"), cell(meta.get("clinical_diagnosis", ""))],
    ]
    table = Table(meta_rows, colWidths=[24 * mm, 52 * mm, 28 * mm, 68 * mm])
    table.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, -1), FONT_NAME),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#edf6f6")),
        ("BACKGROUND", (2, 0), (2, -1), colors.HexColor("#edf6f6")),
        ("TEXTCOLOR", (0, 0), (-1, -1), colors.HexColor("#243746")),
        ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#c9d7dd")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    story.extend([table, Paragraph("统计对照", heading)])
    rows = [
        ["指标", "源报告", "本软件结构化复核"],
        ["有效心搏", source.get("total_beats"), calculated.get("valid_beats")],
        ["平均心率", f"{source.get('avg_hr', '')} bpm", f"{calculated.get('avg_hr_from_rr', '')} bpm"],
        ["最长RR", f"{source.get('longest_rr_s', '')} s", f"{(calculated.get('longest_rr_ms') or 0) / 1000:.3f} s"],
        ["室性/室上性心搏", f"{source.get('ventricular_beats', 0)} / {source.get('supraventricular_beats', 0)}", f"{calculated.get('group_counts',{}).get('3',0)} / {calculated.get('group_counts',{}).get('2',0)}"],
    ]
    stats = Table(rows, colWidths=[50 * mm, 55 * mm, 67 * mm], repeatRows=1)
    stats.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, -1), FONT_NAME),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#123047")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#c9d7dd")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    conclusion = html.escape(report.get("conclusion", "")).replace("\n", "<br/>")
    composition = report.get("composition") or {}
    included_pages = [REPORT_PAGE_LABELS[key] for key in composition.get("included_pages", []) if key in REPORT_PAGE_LABELS]
    paper = composition.get("paper") or {}
    story.extend([
        stats,
        Paragraph("报告编排", heading),
        Paragraph(
            "已选页面：" + ("、".join(included_pages) if included_pages else "默认首页报告")
            + f"<br/>页面设置：{html.escape(str(paper.get('size', 'A4')))} / "
            + ("横向" if paper.get("orientation") == "landscape" else "纵向")
            + f" / {html.escape(str(paper.get('speed', '25 mm/s')))} / {html.escape(str(paper.get('gain', '10 mm/mV')))}",
            body,
        ),
        Paragraph("复核结论", heading),
        Paragraph(conclusion or "（未填写）", body),
        Paragraph("流程状态", heading),
        Paragraph(f"状态：{report.get('status', 'draft')}　版本：{report.get('version', 1)}　复核人：{html.escape(report.get('reviewed_by', '') or '未审核')}", body),
        Spacer(1, 8 * mm),
        Paragraph(f"生成依据：200 Hz、8独立通道原始波形；EBI逐搏索引；源报告LPS结构化文本。软件版本 {APP_VERSION}。", small),
    ])

    review = report.get("review_snapshot") or {}
    step_labels = {"review": "波形复核", "edit": "模板编辑", "trends": "趋势与HRV", "stt": "ST-T", "events": "事件复核"}
    story.append(Paragraph("医生复核记录", heading))
    analysis_note=(f"修订版本 r{report.get('analysis_revision',0)}；按修订位置重算 RR 和分类计数，源报告摘要保留不变。" if report.get("edited_analysis") else "统计仍基于源EBI，未随人工改型自动重算。")
    story.append(Paragraph(f"人工修订记录 {report.get('override_count',0)} 项。"+analysis_note+"保留事件是报告证据，不表示自动确诊。",warning))
    for key, label in step_labels.items():
        checkpoint = review.get("steps", {}).get(key, {})
        status = {"done": "已确认", "stale": "修改后待复核"}.get(checkpoint.get("status"), "待确认")
        text = f"{label}：{status}"
        if checkpoint.get("actor"):
            text += " / " + checkpoint["actor"]
        if checkpoint.get("updated_at"):
            text += " / " + checkpoint["updated_at"]
        if checkpoint.get("note"):
            text += "；" + checkpoint["note"]
        story.append(Paragraph(html.escape(text), body))
    retained = [item for item in review.get("events", {}).values() if item.get("status") == "retained"]
    story.append(Paragraph(f"保留的事件定位索引（{len(retained)}项）", heading))
    story.append(Paragraph("按原始200 Hz采样点定位；波形图条请在工作站报告预览中查看。", small))
    for item in sorted(retained, key=lambda value: value["sample_index"]):
        seconds = item["sample_index"] / 200
        day, remainder = divmod(int(seconds), 86400)
        hour, remainder = divmod(remainder, 3600)
        minute, second = divmod(remainder, 60)
        story.append(Paragraph(html.escape(f"{item['type']} / D{day+1} {hour:02}:{minute:02}:{second:02} / sample {item['sample_index']}"), body))

    def footer(canvas, document):
        canvas.saveState()
        canvas.setFont(FONT_NAME, 8)
        canvas.setFillColor(colors.HexColor("#72828d"))
        canvas.drawString(18 * mm, 9 * mm, f"病例 {case['case_id']} / 本地离线生成")
        canvas.drawRightString(192 * mm, 9 * mm, f"第 {document.page} 页")
        canvas.restoreState()

    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    output.seek(0)
    return output


def build_composed_pdf(case, calculated, report):
    """V2 renders the same resolved selection, figures and tables as the print view."""
    from reportlab.lib.pagesizes import A3, landscape
    from reportlab.platypus import KeepTogether
    from reportlab.graphics.shapes import Drawing, PolyLine, String, Line
    _register_font()
    output=BytesIO();composition=report['composition'];paper=composition.get('paper',{})
    size=A3 if paper.get('size')=='A3' else A4
    if paper.get('orientation')=='landscape':size=landscape(size)
    doc=SimpleDocTemplate(output,pagesize=size,leftMargin=15*mm,rightMargin=15*mm,topMargin=15*mm,bottomMargin=15*mm)
    width=size[0]-30*mm
    style=ParagraphStyle('composed',fontName=FONT_NAME,fontSize=10,leading=16)
    title=ParagraphStyle('composed-title',parent=style,fontSize=18,leading=26,spaceAfter=12)
    para=lambda text:Paragraph(html.escape(str(text).replace('·',' / ').replace('–','-').replace('—','-')).replace('\n','<br/>'),style)
    def table(rows):
        columns=len(rows[0]);widths=([width*.23]+[width*.77/(columns-1)]*(columns-1)) if columns>3 else [width/columns]*columns
        t=Table([[para(v if v is not None else '—') for v in row] for row in rows],colWidths=widths,repeatRows=1)
        t.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,0),colors.HexColor('#edf5f6')),('GRID',(0,0),(-1,-1),.3,colors.HexColor('#c6d7dc')),('VALIGN',(0,0),(-1,-1),'TOP'),('LEFTPADDING',(0,0),(-1,-1),5),('TOPPADDING',(0,0),(-1,-1),5),('BOTTOMPADDING',(0,0),(-1,-1),5)]));return t
    story=[Paragraph('动态心电分析报告',title),para(f"{case['case_id']} · {case['metadata'].get('name','')} · {case['metadata'].get('start_time','')}"),para(f"{report['status']} v{report['version']} · {report.get('reviewed_by','') or '未审核'}"),Spacer(1,10),para(report.get('conclusion',''))]
    story += [para(b['text']) for b in composition.get('diagnosis_blocks',[])]
    from .clinical_analysis import CATEGORIES
    data=report['event_statistics']
    story += [Spacer(1,12),para('全部已确认结果统计（图条选择不改变统计）'),table([['分类','事件次数','心搏数量']]+[[label,data['confirmed_category_counts'][k],data['confirmed_beat_counts'].get(k,'—')] for k,label in CATEGORIES])]
    h=report['hrv_windows'];story += [Spacer(1,12),para(f"HRV 第{h['window_index']+1}窗口 · 实际覆盖 {h['actual_duration_s']/3600:.2f}小时"),para(h['method'])]
    rows=[['时段','SDNN ms','RMSSD ms','pNN50 %','平均NN ms','有效NN','覆盖 / 有效NN秒']]
    rows += [[r['label'],r['sdnn_ms'],r['rmssd_ms'],r['pnn50_pct'],r['mean_nn_ms'],r['nn_count'],f"{r['coverage_s']} / {r['valid_nn_s']}"] for r in list(h['periods'].values())+h['hourly']]
    trend=Drawing(width,100);valid=[r['sdnn_ms'] for r in h['hourly'] if r['sdnn_ms'] is not None];maximum=max([1]+valid)
    previous=None
    for i,r in enumerate(h['hourly']):
        if r['sdnn_ms'] is None:previous=None;continue
        xy=(20+i*(width-40)/max(1,len(h['hourly'])-1),15+r['sdnn_ms']/maximum*70)
        if previous:trend.add(Line(*previous,*xy,strokeColor=colors.HexColor('#0b7d7b')))
        trend.add(String(xy[0],xy[1]+3,str(r['sdnn_ms']),fontName='Helvetica',fontSize=7));previous=xy
    story += [trend,table(rows)]
    for i,event in enumerate(report.get('selected_waveforms',[])):
        wave=event['waveform'];leads=list(wave['leads'].items());row_height=72;d=Drawing(width,row_height*len(leads))
        for j,(lead,values) in enumerate(leads):
            base=(len(leads)-j-.5)*row_height;magnitude=max([50]+[abs(v) for v in values]);points=[]
            for x,v in enumerate(values):points += [x/max(1,len(values)-1)*width,base-v/magnitude*row_height*.4]
            if len(points)>=4:d.add(PolyLine(points,strokeColor=colors.HexColor('#244f59'),strokeWidth=.5))
            d.add(String(2,(len(leads)-j)*row_height-10,lead,fontName='Helvetica',fontSize=8))
        for sample in event['target_samples']:
            x=(sample/200-wave['start_s'])/wave['duration_s']*width
            if 0<=x<=width:d.add(Line(x,0,x,d.height,strokeColor=colors.HexColor('#debdad'),strokeWidth=.25))
        story += [Spacer(1,14),KeepTogether([para(f"{i+1}. {event['caption']}"),d,para(f"{wave['start_s']:.3f}–{wave['start_s']+wave['duration_s']:.3f}秒 · 原始设备波形，自适应幅度 · 目标 {event['beat_count']} 搏")])]
    story += [Spacer(1,12),para('源报告作为独立对照，未参与本页修订后统计。'),para(f"源报告摘要：有效心搏 {case.get('summary',{}).get('total_beats','—')} · 平均心率 {case.get('summary',{}).get('avg_hr','—')} bpm · SDNN {case.get('summary',{}).get('sdnn_ms','—')} ms"),para('研究演示输出 · 原始电压标定未建立计量学溯源。')]
    def footer(canvas,document):
        canvas.setFont(FONT_NAME,8);canvas.drawRightString(size[0]-15*mm,8*mm,f"第 {document.page} 页")
    doc.build(story,onFirstPage=footer,onLaterPages=footer);output.seek(0);return output
