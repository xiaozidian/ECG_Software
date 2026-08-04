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


def _register_font() -> None:
    try:
        pdfmetrics.getFont(FONT_NAME)
    except KeyError:
        pdfmetrics.registerFont(UnicodeCIDFont(FONT_NAME))


def build_report_pdf(case: dict, calculated: dict, report: dict) -> BytesIO:
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
        Paragraph('<font name="Helvetica">CardioInsight Holter</font><font name="STSong-Light"> · 研究演示版</font>', small),
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
        ["室性/室上性心搏", f"{source.get('ventricular_beats', 0)} / {source.get('supraventricular_beats', 0)}", "导入源分组，须人工复核"],
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
    story.extend([
        stats,
        Paragraph("复核结论", heading),
        Paragraph(conclusion or "（未填写）", body),
        Paragraph("流程状态", heading),
        Paragraph(f"状态：{report.get('status', 'draft')}　版本：{report.get('version', 1)}　复核人：{html.escape(report.get('reviewed_by', '') or '未审核')}", body),
        Spacer(1, 8 * mm),
        Paragraph(f"生成依据：200 Hz、8独立通道原始波形；EBI逐搏索引；源报告LPS结构化文本。软件版本 {APP_VERSION}。", small),
    ])

    def footer(canvas, document):
        canvas.saveState()
        canvas.setFont(FONT_NAME, 8)
        canvas.setFillColor(colors.HexColor("#72828d"))
        canvas.drawString(18 * mm, 9 * mm, f"病例 {case['case_id']} · 本地离线生成")
        canvas.drawRightString(192 * mm, 9 * mm, f"第 {document.page} 页")
        canvas.restoreState()

    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    output.seek(0)
    return output
