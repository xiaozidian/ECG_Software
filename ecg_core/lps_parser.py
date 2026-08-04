from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path


def _after_label(texts: list[str], label: str) -> str:
    pattern = re.compile(rf"^{re.escape(label)}\s*[:：]\s*(.*)$")
    for text in texts:
        match = pattern.match(text)
        if match:
            return match.group(1).strip()
    return ""


def _first_match(texts: list[str], pattern: str, cast=None, default=None):
    regex = re.compile(pattern)
    for text in texts:
        match = regex.search(text)
        if not match:
            continue
        value = match.group(1).strip()
        if cast is None:
            return value
        try:
            return cast(value)
        except (TypeError, ValueError):
            return default
    return default


def _rect(element: ET.Element) -> tuple[int, int, int, int] | None:
    raw = element.attrib.get("CRECT", "")
    try:
        values = tuple(int(value) for value in raw.split(","))
    except ValueError:
        return None
    return values if len(values) == 4 else None


def _duration_seconds(text: str) -> int | None:
    match = re.search(r"(?:(\d+)\s*小时)?\s*(?:(\d+)\s*分钟)?", text)
    if not match or not any(match.groups()):
        return None
    return int(match.group(1) or 0) * 3600 + int(match.group(2) or 0) * 60


def parse_lps(path: Path) -> dict:
    tree = ET.parse(path)
    shapes = [node for node in tree.getroot().iter("PShape")]
    texts = [(node.text or "").strip() for node in shapes if (node.text or "").strip()]

    conclusion_parts: list[tuple[int, int, str]] = []
    for node in shapes:
        text = (node.text or "").strip()
        rect = _rect(node)
        if not text or rect is None:
            continue
        x1, y1, _, _ = rect
        if 2020 < y1 < 3250 and text != "报告结论":
            conclusion_parts.append((y1, x1, text))
    conclusion_parts.sort()
    conclusion = "\n".join(item[2] for item in conclusion_parts)

    start_text = _after_label(texts, "记录时间")
    start_iso = ""
    if start_text:
        try:
            start_iso = datetime.strptime(start_text, "%Y-%m-%d %H:%M:%S").isoformat()
        except ValueError:
            start_iso = start_text

    duration_text = _after_label(texts, "记录时长")
    metadata = {
        "name": _after_label(texts, "姓名"),
        "sex": _after_label(texts, "性别"),
        "age": _first_match(texts, r"年龄\s*[:：]\s*(\d+)", int),
        "patient_id": _after_label(texts, "ID号"),
        "bed": _after_label(texts, "床位"),
        "requesting_physician": _after_label(texts, "申请医生"),
        "department": _after_label(texts, "申请科室"),
        "clinical_diagnosis": _after_label(texts, "临床诊断"),
        "pacemaker": _after_label(texts, "起搏器"),
        "start_time": start_text,
        "start_iso": start_iso,
        "duration_text": duration_text,
        "duration_seconds_reported": _duration_seconds(duration_text),
    }

    summary = {
        "total_beats": _first_match(texts, r"总心搏数\s*[:：]\s*(\d+)", int, 0),
        "ventricular_beats": _first_match(texts, r"室性心搏\s*[:：]\s*(\d+)", int, 0),
        "supraventricular_beats": _first_match(texts, r"室上性心搏\s*[:：]\s*(\d+)", int, 0),
        "min_hr": _first_match(texts, r"最慢心率\s*[:：]\s*(\d+)", int),
        "avg_hr": _first_match(texts, r"平均心率\s*[:：]\s*(\d+)", int),
        "max_hr": _first_match(texts, r"最快心率\s*[:：]\s*(\d+)", int),
        "longest_rr_s": _first_match(texts, r"最长RR间期\s*[:：]\s*([0-9.]+)", float),
        "tachy_beats": _first_match(texts, r"心动过速中的心搏总和\s*[:：]\s*(\d+)", int, 0),
        "brady_beats": _first_match(texts, r"心动过缓中的心搏总和\s*[:：]\s*(\d+)", int, 0),
        "sdnn_ms": _first_match(texts, r"SDNN\s*[:：]\s*([0-9.]+)\s*ms", float),
        "sdann_ms": _first_match(texts, r"SDANN\s*[:：]\s*([0-9.]+)\s*ms", float),
        "sdnn_index_ms": _first_match(texts, r"SDNNIndex\s*[:：]\s*([0-9.]+)\s*ms", float),
        "rmssd_ms": _first_match(texts, r"rMSSD\s*[:：]\s*([0-9.]+)\s*ms", float),
        "pnn50_pct": _first_match(texts, r"pNN50\s*[:：]\s*([0-9.]+)\s*%", float),
        "lf_hf": _first_match(texts, r"LF/HF\s*[:：]\s*([0-9.]+)", float),
        "triangular_index": _first_match(texts, r"三角指数\s*[:：]\s*([0-9.]+)", float),
        "lf": _first_match(texts, r"^LF\s*[:：]\s*([0-9.]+)", float),
        "hf": _first_match(texts, r"^HF\s*[:：]\s*([0-9.]+)", float),
    }
    return {
        "metadata": metadata,
        "summary": summary,
        "conclusion": conclusion,
        "source_text_count": len(texts),
    }
