"""Frozen pre-optimization functions, for exact differential verification only."""
from ecg_core.stt import _read_leads, _median, _mad, LEADS, SAMPLE_RATE

def _estimate_j_sample(buffer, beats, total_samples) -> tuple[int, float]:
    """Estimate QRS end from multi-beat, multi-lead derivative energy."""
    energies = []
    for offset in range(33):  # R to R+160 ms
        changes = []
        for beat, _group, _rr in beats:
            current = _read_leads(buffer, beat + offset, total_samples)
            previous = _read_leads(buffer, beat + offset - 1, total_samples)
            changes.extend(abs(current[index] - previous[index]) for index in (1, 6, 10))
        energies.append(_median(changes))
    peak_index = max(range(21), key=energies.__getitem__)
    peak, noise = energies[peak_index], _median(energies[-8:])
    threshold = max(2.0, noise * 2.5, peak * 0.12)
    j_sample = 18  # 90 ms fallback
    for index in range(max(8, peak_index + 2), 29):
        if all(value <= threshold for value in energies[index:index + 4]):
            j_sample = index
            break
    confidence = max(0.0, min(1.0, (peak - noise) / max(peak, 1.0)))
    return j_sample, confidence

def _block_measurement(buffer, beats, all_count, total_samples, config) -> dict:
    j_sample, landmark_confidence = _estimate_j_sample(buffer, beats, total_samples)
    st_offset = j_sample + round(config["st_measurement_ms"] * SAMPLE_RATE / 1000)
    values = {lead: {key: [] for key in ("baseline", "st", "t", "qrs", "span")} for lead in LEADS}
    for beat, _group, rr_ms in beats:
        baseline_frames = [_read_leads(buffer, beat + offset, total_samples) for offset in range(-40, -23, 4)]
        st_frames = [_read_leads(buffer, beat + st_offset + offset, total_samples) for offset in range(-2, 3)]
        qrs_frames = [_read_leads(buffer, beat + offset, total_samples) for offset in range(-8, j_sample + 1, 2)]
        rr_samples = max(round(rr_ms * SAMPLE_RATE / 1000), round(0.45 * SAMPLE_RATE))
        t_last = min(j_sample + 72, max(j_sample + 30, round(rr_samples * 0.62)))
        t_frames = [_read_leads(buffer, beat + offset, total_samples) for offset in range(j_sample + 24, t_last + 1, 2)]
        for lead_index, lead in enumerate(LEADS):
            baseline_values = [frame[lead_index] for frame in baseline_frames]
            baseline = _median(baseline_values)
            qrs_values = [frame[lead_index] for frame in qrs_frames]
            t_values = [frame[lead_index] - baseline for frame in t_frames]
            values[lead]["baseline"].append(baseline)
            values[lead]["st"].append(_median(frame[lead_index] for frame in st_frames) - baseline)
            values[lead]["t"].append(max(t_values, key=abs) if t_values else 0.0)
            values[lead]["qrs"].append(max(qrs_values) - min(qrs_values) if qrs_values else 0.0)
            values[lead]["span"].append(max(baseline_values) - min(baseline_values))

    lead_values, lead_scores = {}, []
    for lead, lead_data in values.items():
        qrs = _median(lead_data["qrs"])
        baseline_variation = _mad(lead_data["baseline"]) + _median(lead_data["span"])
        qrs_variation = _mad(lead_data["qrs"]) / max(qrs, 1.0)
        noise_ratio = baseline_variation / max(qrs, 40.0)
        score = max(0.0, min(1.0, 1.0 - min(0.65, noise_ratio) - min(0.35, qrs_variation)))
        lead_scores.append(score)
        lead_values[lead] = {
            "st_level_units": round(_median(lead_data["st"]), 2),
            "t_amplitude_units": round(_median(lead_data["t"]), 2),
            "qrs_amplitude_units": round(qrs, 2), "quality_score": round(score, 3),
        }
    normal_ratio = len(beats) / max(all_count, 1)
    overall = max(0.0, min(1.0, _median(lead_scores) * min(1.0, normal_ratio / 0.6)))
    return {
        "j_offset_ms": round(j_sample * 1000 / SAMPLE_RATE),
        "landmark_confidence": round(landmark_confidence, 3),
        "normal_beat_count": len(beats), "normal_beat_ratio": round(normal_ratio, 3),
        "quality_score": round(overall, 3),
        "eligible": normal_ratio >= 0.35 and overall >= 0.42,
        "leads": lead_values,
    }

def _rolling_reference(values: list[dict], key: str, radius: int) -> list[float | None]:
    result = []
    for index in range(len(values)):
        window = values[max(0, index - radius):min(len(values), index + radius + 1)]
        eligible = [row[key] for row in window if row.get("eligible") and row.get(key) is not None]
        result.append(round(_median(eligible), 2) if eligible else None)
    return result
