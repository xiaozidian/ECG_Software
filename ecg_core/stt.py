"""Safety-bounded data contract for manual ST-T review.

This module deliberately does not read waveform samples or derive ST values.  The
current dataset does not provide independently verified voltage calibration,
lead placement, or an ST-analysis filter/landmark pipeline, so automatic case
measurements and diagnostic classifications must remain disabled.
"""

from __future__ import annotations

import re


_ST_T_TERM = re.compile(
    r"(?:"
    r"(?<![A-Za-z])S\s*[-–—－]?\s*T(?:\s*[-–—－]?\s*T)?(?![A-Za-z])"
    r"|ST段|T波|T倒置|T低平|T\s*[-–—]?\s*wave"
    r")",
    re.IGNORECASE,
)
_SOURCE_FRAGMENT_SPLIT = re.compile(r"(?<=[。！？；!?;])\s*|\n+")
_CASE_AMPLITUDE = re.compile(
    r"(?<![A-Za-z0-9])(?:[+-−＋－]?\s*\d+(?:\.\d+)?)\s*(?:mV|µV|μV)",
    re.IGNORECASE,
)


def extract_stt_source_report(conclusion: str) -> dict:
    """Extract ST/T-related source-report wording without exposing amplitudes.

    The returned fragments are source excerpts, not software interpretations.
    Numeric voltage values are intentionally redacted because calibration is not
    verified and the ST-T review endpoint must not publish case measurements.
    """

    if not isinstance(conclusion, str):
        conclusion = ""

    fragments: list[str] = []
    amplitude_values_redacted = False
    for raw_fragment in _SOURCE_FRAGMENT_SPLIT.split(conclusion):
        fragment = raw_fragment.strip()
        if not fragment or not _ST_T_TERM.search(fragment):
            continue
        redacted, replacements = _CASE_AMPLITUDE.subn("【病例幅度已隐藏】", fragment)
        amplitude_values_redacted = amplitude_values_redacted or replacements > 0
        if redacted not in fragments:
            fragments.append(redacted)

    return {
        "origin": "source_report_conclusion",
        "available": bool(fragments),
        "text": "\n".join(fragments),
        "fragments": fragments,
        "is_source_excerpt": True,
        "software_interpretation_added": False,
        "amplitude_values_redacted": amplitude_values_redacted,
    }


def build_stt_review(conclusion: str) -> dict:
    """Return the non-diagnostic protocol contract for the ST-T review UI."""

    return {
        "schema_version": "manual-stt-review-v1",
        "review_mode": "manual_review_only",
        "manual_review_only": True,
        "calibration_unverified": True,
        "measurement_protocol": {
            "default_measurement": "J+60 ms",
            "default_landmark": "ST60",
            "baseline": {
                "preferred": "PR_segment",
                "fallback": "individual_stable_baseline",
                "label": "PR 段/个体稳定基线",
                "requires_manual_confirmation": True,
                "note": "基线必须由复核者结合体位变化、伪差、传导异常及心率变化确认。",
            },
            "landmarks": [
                {
                    "code": "J",
                    "offset_from_j_ms": 0,
                    "label": "J 点",
                    "purpose": "QRS 终点，由复核者人工定位",
                },
                {
                    "code": "ST60",
                    "offset_from_j_ms": 60,
                    "label": "J+60 ms",
                    "purpose": "默认 ST 复核点",
                },
                {
                    "code": "ST80",
                    "offset_from_j_ms": 80,
                    "label": "J+80 ms",
                    "purpose": "备选 ST 复核点，需记录使用理由",
                },
            ],
            "case_amplitude_output": {
                "enabled": False,
                "reason": "原始电压标定和分析链未独立验证，不输出病例 ST 幅度。",
            },
        },
        "lead_system": {
            "status": "unknown",
            "mapping_verified": False,
            "electrode_placement_verified": False,
            "message": "导联体系及采集通道到标准导联的映射未经独立核验。",
        },
        "calibration": {
            "status": "unverified",
            "voltage_gain_verified": False,
            "filter_response_verified_for_st": False,
            "message": "在增益、零线稳定性及 ST 分析滤波响应核验前，仅允许人工定性复核。",
        },
        "automatic_candidates": {
            "enabled": False,
            "reason_code": "measurement_chain_not_validated",
            "reasons": [
                "电压增益与零线标定未独立验证",
                "导联映射与电极位置未独立验证",
                "J 点、基线和 ST 复核点尚无经验证的自动定位算法",
                "动态心电的体位变化、基线漂移与伪差需要人工排除",
            ],
        },
        "reference_thresholds": {
            "enabled": False,
            "reference_only": True,
            "applied_to_case": False,
            "title": "动态心电常用研究筛查参考（未启用）",
            "st_depression_example": {
                "magnitude_mV": 0.10,
                "comparison": "greater_than_or_equal",
                "measurement_landmarks": ["ST60", "ST80"],
                "morphology": ["horizontal", "downsloping"],
                "minimum_duration_s": 60,
                "minimum_episode_separation_s": 60,
            },
            "st_elevation": {
                "configured": False,
                "reason": "阈值依赖导联、电极配置及临床场景，未设置通用自动规则。",
            },
            "t_wave": {
                "configured": False,
                "reason": "T 波形态需与导联、基线、体位及临床背景联合人工解读。",
            },
            "warning": "该参考不是病例判定规则，不得用于自动生成诊断。",
        },
        "source_report": extract_stt_source_report(conclusion),
        "clinical_safety": {
            "diagnosis_generated": False,
            "requires_physician_review": True,
            "statement": "本界面仅用于医师人工复核，不生成缺血诊断或替代临床判断。",
        },
    }
