from __future__ import annotations

import math
import sys
from array import array
from pathlib import Path

from .config import CHANNEL_COUNT, SAMPLE_RATE

ALL_LEADS = ["I", "II", "III", "aVR", "aVL", "aVF", "V1", "V2", "V3", "V4", "V5", "V6"]


def _display_filter(values: list[float], sample_rate: int) -> list[float]:
    if not values:
        return values
    highpass_decay = math.exp(-2 * math.pi * 0.5 / sample_rate)
    lowpass_mix = 1 - math.exp(-2 * math.pi * 40 / sample_rate)
    baseline = values[0]
    low = 0.0
    output: list[float] = []
    for value in values:
        baseline = highpass_decay * baseline + (1 - highpass_decay) * value
        high = value - baseline
        low += lowpass_mix * (high - low)
        output.append(round(low, 2))
    return output


def _derive(channels: list[list[int]]) -> dict[str, list[float]]:
    lead_i, lead_ii = channels[0], channels[1]
    result: dict[str, list[float]] = {
        "I": lead_i,
        "II": lead_ii,
        "III": [b - a for a, b in zip(lead_i, lead_ii)],
        "aVR": [-(a + b) / 2 for a, b in zip(lead_i, lead_ii)],
        "aVL": [a - b / 2 for a, b in zip(lead_i, lead_ii)],
        "aVF": [b - a / 2 for a, b in zip(lead_i, lead_ii)],
    }
    for index, name in enumerate(("V1", "V2", "V3", "V4", "V5", "V6"), start=2):
        result[name] = channels[index]
    return result


def read_waveform(
    path: Path,
    start_s: float,
    duration_s: float,
    leads: list[str] | None = None,
    max_points: int = 4000,
    apply_filter: bool = True,
) -> dict:
    start_s = max(0.0, float(start_s))
    duration_s = max(1.0, min(float(duration_s), 120.0))
    total_samples = path.stat().st_size // (CHANNEL_COUNT * 2)
    start_sample = min(int(start_s * SAMPLE_RATE), max(total_samples - 1, 0))
    requested = int(duration_s * SAMPLE_RATE)
    sample_count = min(requested, total_samples - start_sample)
    byte_count = sample_count * CHANNEL_COUNT * 2
    with path.open("rb") as stream:
        stream.seek(start_sample * CHANNEL_COUNT * 2)
        raw = stream.read(byte_count)
    samples = array("h")
    samples.frombytes(raw)
    if sys.byteorder != "little":
        samples.byteswap()
    channels = [list(samples[index::CHANNEL_COUNT]) for index in range(CHANNEL_COUNT)]
    derived = _derive(channels)
    selected = [lead for lead in (leads or ["II", "V1", "V5"]) if lead in ALL_LEADS]
    if not selected:
        selected = ["II"]
    stride = max(1, math.ceil(sample_count / max(200, min(int(max_points), 12000))))
    output = {}
    for lead in selected:
        values = derived[lead]
        if apply_filter:
            values = _display_filter(values, SAMPLE_RATE)
        output[lead] = values[::stride]
    return {
        "start_s": round(start_sample / SAMPLE_RATE, 3),
        "duration_s": round(sample_count / SAMPLE_RATE, 3),
        "sample_rate_hz": SAMPLE_RATE,
        "display_sample_rate_hz": SAMPLE_RATE / stride,
        "stride": stride,
        "units": "µV",
        "leads": output,
        "total_duration_s": round(total_samples / SAMPLE_RATE, 3),
        "filter": "0.5–40 Hz display filter" if apply_filter else "raw",
        "calibration_note": "设备原始标度；本演示版未建立计量学溯源",
    }
