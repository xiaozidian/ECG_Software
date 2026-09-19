from __future__ import annotations

import re

from ecg_core.clinical_analysis import CATEGORIES
from ecg_core.report_pdf import build_report_pdf


def _event(index: int) -> dict:
    start = 60.0 + index * 10
    values = [0, 8, -4, 18, 90, -25, 5, 22, 4, 0] * 24
    return {
        "caption": f"单发室早 {index + 1}",
        "beat_count": 1,
        "target_samples": [int((start + 0.8) * 200)],
        "waveform": {
            "start_s": start,
            "duration_s": 2.4,
            "leads": {"II": values, "V1": [-value for value in values], "V5": values},
        },
    }


def _report(event_count: int) -> dict:
    empty_counts = {key: 0 for key, _ in CATEGORIES}
    period = {
        "label": "当前记录（不足24小时）",
        "sdnn_ms": 70.0,
        "rmssd_ms": 60.0,
        "pnn50_pct": 15.0,
        "mean_nn_ms": 644.0,
        "nn_count": 500,
        "coverage_s": 600.0,
        "valid_nn_s": 322.0,
    }
    return {
        "status": "draft",
        "version": 1,
        "reviewed_by": "",
        "conclusion": "供医生复核。",
        "composition": {
            "paper": {"size": "A4", "orientation": "portrait"},
            "diagnosis_blocks": [],
        },
        "event_statistics": {
            "confirmed_category_counts": empty_counts,
            "confirmed_beat_counts": empty_counts,
        },
        "hrv_windows": {
            "window_index": 0,
            "actual_duration_s": 600.0,
            "method": "修订后连续 N-N。",
            "periods": {"full": period, "day": {**period, "label": "日间"}, "night": {**period, "label": "夜间"}},
            "hourly": [{**period, "label": "00:00"}],
        },
        "selected_waveforms": [_event(index) for index in range(event_count)],
    }


def test_composed_pdf_places_three_full_width_strips_on_each_paper_page() -> None:
    case = {
        "case_id": "paper-layout-test",
        "metadata": {"name": "测试病例", "start_time": "2026-09-15 08:00:00"},
        "summary": {"total_beats": 500, "avg_hr": 70, "sdnn_ms": 70},
    }
    page_pattern = re.compile(rb"/Type\s*/Page\b")
    summary_pages = len(page_pattern.findall(build_report_pdf(case, {}, _report(0)).getvalue()))
    six_pages = len(page_pattern.findall(build_report_pdf(case, {}, _report(6)).getvalue()))
    seven_pages = len(page_pattern.findall(build_report_pdf(case, {}, _report(7)).getvalue()))

    assert six_pages == summary_pages + 2
    assert seven_pages == summary_pages + 3


def test_twelve_lead_strip_uses_a_full_a4_page():
    from ecg_core.report_layout import LEADS
    report = _report(2)
    report['selected_waveforms'][1]['waveform']['leads'] = {lead:[0,10,100,-20,0]*300 for lead in LEADS}
    case = {'case_id':'paper-test','metadata':{},'summary':{}}
    data = build_report_pdf(case, {}, report).getvalue()
    assert len(re.findall(rb'/Type\s*/Page\b', data)) == 4


def test_long_conclusion_gets_continuation_pages():
    report = _report(0)
    report['conclusion'] = '\n'.join(f'第 {i} 条验证文字。' for i in range(100))
    case = {'case_id':'paper-test','metadata':{},'summary':{}}
    assert len(re.findall(rb'/Type\s*/Page\b', build_report_pdf(case,{},report).getvalue())) == 4


def test_long_caption_is_preserved_on_its_own_notes_page():
    from ecg_core.report_paper_pdf import wrap_text
    report=_report(1)
    caption='长图注完整性验证。'*40
    report['selected_waveforms'][0]['caption']=caption
    case={'case_id':'paper-test','metadata':{},'summary':{}}
    assert len(re.findall(rb'/Type\s*/Page\b',build_report_pdf(case,{},report).getvalue()))==4
    assert ''.join(wrap_text(caption,46))==caption
