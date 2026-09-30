"""Transparent research measurements on original 200 Hz samples, not diagnoses.

No display-filtered/downsampled signal is accepted. Methods and limitations are
documented in docs/advanced-analysis-methods.md. No clinical cutoffs are emitted.
"""
from collections import OrderedDict
from hashlib import sha256
import json
from math import isfinite
from pathlib import Path
from threading import RLock

import numpy as np
from .source_identity import file_signature, require_local_file, require_waveform_file, source_read
from .signal_profile import normalize_voltage_estimate, voltage_estimate_note

FS = 200
LEADS = ('I', 'II', 'V1', 'V2', 'V3', 'V4', 'V5', 'V6')
VERSION = 'research-2-qt-ambiguity'
# Kors regression coefficients, order I, II, V1..V6; see cited primary implementation.
KORS = np.array([[.38, -.07, -.13, .05, -.01, .14, .06, .54],
                 [-.07, .93, .06, -.02, -.05, .06, -.17, .13],
                 [.11, -.23, -.43, -.06, -.14, -.20, -.11, .31]])
_cache = OrderedDict()
_lock = RLock()


def number(value, name, lo, hi):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not isfinite(value) or not lo <= value <= hi:
        raise ValueError(f'{name} 必须为 {lo}–{hi} 范围内的有限数值')
    return float(value)


def normalize_options(value=None):
    value = {} if value is None else value
    if not isinstance(value, dict):
        raise ValueError('研究测量设置必须为对象')
    out = dict(start_s=number(value.get('start_s', 0), '片段起点', 0, 604800),
               duration_s=number(value.get('duration_s', 300), '片段时长', 30, 600),
               sap_start_s=number(value.get('sap_start_s', 0), '筛查起点', 0, 604800),
               sap_end_s=None, standard_leads=False, uv_per_unit=None,
               calibration_note='', voltage_estimate=None, markers={}, marker_basis='')
    if value.get('sap_end_s') is not None:
        out['sap_end_s'] = number(value['sap_end_s'], '筛查终点', 0, 604800)
        if out['sap_end_s'] <= out['sap_start_s']:
            raise ValueError('筛查终点须晚于起点')
    if not isinstance(value.get('standard_leads', False), bool):
        raise ValueError('标准导联确认必须为布尔值')
    out['standard_leads'] = value.get('standard_leads', False)
    note = value.get('calibration_note', '')
    if not isinstance(note, str) or len(note) > 300:
        raise ValueError('校准依据须为不超过 300 字的文本')
    out['calibration_note'] = note.strip()
    if value.get('uv_per_unit') is not None:
        out['uv_per_unit'] = number(value['uv_per_unit'], '统一幅度系数 µV/设备单位', .000001, 10000)
        if not out['calibration_note']:
            raise ValueError('输入电压系数时须填写设备校准依据；不能使用显示增益')
    estimate = normalize_voltage_estimate(value.get('voltage_estimate'))
    if estimate:
        if out['uv_per_unit'] is not None and out['uv_per_unit'] != estimate['uv_per_unit']:
            raise ValueError('估算系数与统一幅度系数不一致')
        out.update(voltage_estimate=estimate, uv_per_unit=estimate['uv_per_unit'],
                   calibration_note=voltage_estimate_note(estimate))
    markers = value.get('markers', {})
    if not isinstance(markers, dict) or any(k not in LEADS for k in markers):
        raise ValueError('QT 人工端点的导联不受支持')
    for lead, m in markers.items():
        if not isinstance(m, dict) or not isinstance(m.get('exclude', False), bool):
            raise ValueError('QT 端点格式错误')
        if m.get('exclude'):
            out['markers'][lead] = {'exclude': True}
            continue
        q = number(m.get('q_ms'), 'QRS 起点（相对 R）', -180, -5)
        t = number(m.get('t_ms'), 'T 波终点（相对 R）', 100, 600)
        if not 200 <= t-q <= 750:
            raise ValueError('QT 端点间距须为 200–750 ms')
        out['markers'][lead] = dict(q_ms=round(q/5)*5, t_ms=round(t/5)*5, exclude=False)
    basis = value.get('marker_basis', '')
    if not isinstance(basis, str) or len(basis) > 80:
        raise ValueError('人工测量依据版本无效')
    out['marker_basis'] = basis
    if out['markers'] and not basis:
        raise ValueError('人工 QT 端点缺少波形依据版本，请重新计算')
    return out


def basis_for(path, rows, excluded, options):
    require_local_file(path)
    raw = [VERSION, str(Path(path).resolve()), file_signature(path),
           [(r['sample_index'], r['class_code'], r.get('rr_ms')) for r in rows], excluded,
           options['start_s'], options['duration_s']]
    return sha256(json.dumps(raw, separators=(',', ':')).encode()).hexdigest()[:24]


def nn_mask(rows, excluded=()):
    times = np.array([r['sample_index']/FS for r in rows])
    rr = np.array([r.get('rr_ms') or np.nan for r in rows], dtype=float)
    normal = np.array([r['class_code'] == 'N' for r in rows], dtype=bool)
    valid = normal & np.roll(normal, 1) & np.isfinite(rr) & (rr >= 300) & (rr <= 2000)
    if len(valid):
        valid[0] = False
    # A true interval must agree with the samples; never bridge edited/deleted beats.
    if len(rr) > 1:
        valid[1:] &= np.abs(np.diff(times)*1000-rr[1:]) <= 10
    for a, b in excluded:
        # RR spans the preceding beat too: reject intervals crossing a boundary.
        valid &= ~((times >= a) & (times-rr/1000 <= b))
    return times, rr, valid


def beat_matrix(raw, samples, before=50, after=130):
    offsets = np.arange(-before, after)
    values = np.asarray(raw[np.asarray(samples)[:, None]+offsets], dtype=float)
    # PR baseline, not a high-pass filter. Preserve sample timing and voltage scale.
    return values - np.median(values[:, 15:25, :], axis=1)[:, None, :]


def delineate(values, rr_ms):
    """Deterministic median-beat amplitude/slope delineator; all points reviewable."""
    y = np.convolve(np.pad(values, (1, 1), mode='edge'), [1/3]*3, mode='valid')
    noise = max(.25, float(np.std(y[15:25])))
    peak = 34+int(np.argmax(np.abs(y[34:67])))
    amp = abs(y[peak])
    if amp < 8*noise:
        return dict(valid=False, reason='QRS 信噪比不足')
    threshold = max(3*noise, amp*.05)
    q = peak
    while q > 18 and (abs(y[q]) > threshold or abs(y[q-1]) > threshold):
        q -= 1
    end = peak
    while end < 80 and (abs(y[end]) > threshold or abs(y[end+1]) > threshold):
        end += 1
    limit = min(169, 50+int(min(600, rr_ms*.7)/5))
    start = max(end+5, 70)
    if start >= limit-6 or not 14 <= q < 50:
        return dict(valid=False, reason='QRS 起点或 QT 窗口不可靠')
    region = np.abs(y[start:limit])
    top = float(np.max(region))
    if top < max(4*noise, amp*.015):
        return dict(valid=False, reason='T 波低幅 / 不可辨识')
    # Preserve bipolar terminal lobes. Multiple same-polarity lobes separated
    # by baseline may be a notched T or a later U/P: require manual endpoints
    # rather than either automatically merging or cutting at this boundary.
    peaks = [i for i in range(start+1, limit-2) if abs(y[i]) >= top*.5 and abs(y[i]) >= abs(y[i-1]) and abs(y[i]) > abs(y[i+1])]
    p = peaks[0] if peaks else start+int(np.argmax(region))
    for later in peaks[1:]:
        quiet = 0
        boundary = None
        for j in range(p+1, later):
            quiet = quiet+1 if abs(y[j]) <= max(3*noise, top*.1) else 0
            if quiet >= 6:  # 30 ms near baseline, not a brief bipolar crossing
                boundary = j+1
                break
        # A depressed ST segment and an opposite-polarity terminal T lobe may
        # have a broad baseline crossing. Do not truncate that terminal lobe.
        if boundary is not None and y[p]*y[later] > 0:
            return dict(valid=False, reason='同向多波瓣间已回基线，T/U 或后续波分界不确定；请人工复核端点')
        p = later
    if p >= limit-2:
        return dict(valid=False, reason='T 波峰落在窗口边缘，缺少完整末支；请换窗或人工复核')
    polarity = 1 if y[p] >= 0 else -1
    slopes = np.diff(y)*polarity
    k = p+int(np.argmin(slopes[p:limit-1]))
    slope = float(slopes[k])
    t = int(round(k-y[k]/(slope*polarity))) if slope < -noise*.1 else limit
    if not p < t < limit or abs(y[limit-1]) > max(3*noise, top*.2):
        return dict(valid=False, reason='T 波终点 / U 波或下一心搏边界不明确')
    qt = (t-q)*5
    if not 200 <= qt <= 750:
        return dict(valid=False, reason='QT 超出软件测量窗口，需人工复核')
    return dict(valid=True, q_ms=(q-50)*5, t_ms=(t-50)*5, qrs_end_ms=(end-50)*5,
                qt_ms=qt, snr=round(amp/noise, 2), reason='自动端点，待人工复核')


def qtd_analysis(raw, rows, times, rr, valid, options):
    within = (times >= options['start_s']) & (times < options['start_s']+options['duration_s'])
    good = valid & np.roll(valid, -1)
    if len(good):
        good[-1] = False
    # Fixed 900 ms excerpt must not contain adjacent QRS complexes.
    good &= (rr >= 700) & (np.roll(rr, -1) >= 700)
    good &= np.abs(np.roll(rr, -1)/rr-1) <= .2
    ids = np.flatnonzero(good & within)
    ids = [i for i in ids if 50 <= rows[i]['sample_index'] < len(raw)-130]
    ids = ids[:64]
    result = dict(status='insufficient', beat_count=0, leads=[], qtd_ms=None, qtc_bazett_dispersion_ms=None,
                  qtc_fridericia_dispersion_ms=None, method='同窗正常搏 PR 去基线、中位心搏、QRS 幅值阈值与 T 末支切线；8 个采集导联，不混入代数派生导联。QTc 同时列出 Bazett / Fridericia。200 Hz 时间步长 5 ms；不确定端点可人工调整或排除。')
    if len(ids) < 8:
        result['reason'] = '片段内少于 8 个边界完整、相邻正常且 RR ≥700 ms 的心搏；请换窗'
        return result, None
    matrix = beat_matrix(raw, [rows[i]['sample_index'] for i in ids])
    med = np.median(matrix, axis=0)
    # Reject whole beats with gross deviations; same beat subset across all leads.
    error = np.median(np.abs(matrix-med), axis=(1, 2))
    bound = max(2, float(np.median(error))*3)
    keep = error <= bound
    if int(keep.sum()) < 8:
        result['reason'] = '形态一致的正常搏不足 8 个'
        return result, None
    med = np.median(matrix[keep], axis=0)
    result.update(beat_count=int(keep.sum()), rr_ms=round(float(np.median(rr[np.array(ids)[keep]])), 3),
                  start_s=options['start_s'], end_s=min(len(raw)/FS, options['start_s']+options['duration_s']))
    records = []
    for j, lead in enumerate(LEADS):
        d = delineate(med[:, j], result['rr_ms'])
        source=raw[np.array([rows[i]['sample_index'] for i in ids])[:,None]+np.arange(-50,130),j]
        unusable=bool(np.max(np.abs(source.astype(float))) >= 32760 or np.ptp(med[:, j]) < 2)
        if unusable:
            d = dict(valid=False, reason='采集幅度削顶或近乎平线')
        auto = dict(d)
        override = options['markers'].get(lead)
        if override:
            if override.get('exclude'):
                d = dict(valid=False, reason='人工排除此导联')
            else:
                if unusable:
                    raise ValueError(f'{lead} 为平线或削顶，不能用人工端点绕过采集质量门槛')
                if override['t_ms'] >= min(600, result['rr_ms']*.7):
                    raise ValueError(f'{lead} 人工 T 终点超出本次正常搏的无重叠窗口')
                d.update(valid=True, **override, qt_ms=override['t_ms']-override['q_ms'], reason='人工端点（研究测量）')
        if d['valid']:
            d['qtc_bazett_ms'] = round(d['qt_ms']/np.sqrt(result['rr_ms']/1000), 2)
            d['qtc_fridericia_ms'] = round(d['qt_ms']/(result['rr_ms']/1000)**(1/3), 2)
        records.append(dict(lead=lead, **d, automatic=auto, manual=bool(override), signal_usable=not unusable,
                            points=[dict(x=(i-50)*5, y=round(float(v), 4)) for i, v in enumerate(med[:, j])]))
    good_leads = [r for r in records if r['valid']]
    result.update(leads=records, valid_leads=len(good_leads))
    if len(good_leads) >= 6 and sum(r['lead'].startswith('V') for r in good_leads) >= 3:
        result.update(status='research', reason='自动/人工端点仅用于研究；至少 6 个导联（其中 ≥3 个胸导联）参与离散度')
        for key, source in [('qtd_ms', 'qt_ms'), ('qtc_bazett_dispersion_ms', 'qtc_bazett_ms'), ('qtc_fridericia_dispersion_ms', 'qtc_fridericia_ms')]:
            values = [r[source] for r in good_leads]
            result[key] = round(max(values)-min(values), 2)
    else:
        result['reason'] = '有效导联不足 6 个或胸导联不足 3 个；不报告 QTd，可复核各导联端点'
    return result, med


def amplitude_unit(options):
    return 'µV（估算，非设备校准）' if options.get('voltage_estimate') else 'µV（按录入校准系数）' if options['uv_per_unit'] else '设备单位'


def vcg_analysis(median, qt, options):
    out = dict(status='insufficient', method='Kors 1990 线性回归：I、II、V1–V6 → XYZ；为推导向量，不等同 Frank 实测。只显示向量轨迹与峰值模长，不推断疾病。', loops=[])
    if not options['standard_leads']:
        return dict(out, reason='须确认 8 通道顺序为 I、II、V1–V6，且为标准电极位置、相同增益；改良 Holter 导联不能直接套用')
    if median is None or any(np.ptp(median[:, i]) < 2 for i in range(8)) or any(not r.get('signal_usable', True) for r in qt.get('leads', [])):
        return dict(out, reason='缺少完整、有效的 8 通道中位心搏')
    xyz = median @ KORS.T
    factor = options['uv_per_unit'] or 1
    xyz *= factor
    out.update(status='research', reason='导联映射由使用者确认；转换与设备校准尚需外部数据验证',
               unit=amplitude_unit(options),
               peak_magnitude=round(float(np.max(np.linalg.norm(xyz, axis=1))), 4))
    for a, b, title in [(0, 1, '额面 X–Y'), (0, 2, '横面 X–Z'), (1, 2, '矢状面 Y–Z')]:
        out['loops'].append(dict(title=title, x_label='XYZ'[a], y_label='XYZ'[b], points=[dict(x=round(float(x), 4), y=round(float(y), 4)) for x, y in xyz[:, [a, b]]]))
    return out


def alternans_spectrum(beats):
    """128 x ST-T samples. Nyquist amplitude normalization recovers A for ±A."""
    n = len(beats)
    centered = beats-np.mean(beats, axis=0)
    power = np.mean(np.abs(np.fft.rfft(centered, axis=0)/n)**2, axis=1)
    freq = np.fft.rfftfreq(n)
    noise = power[(freq >= .431) & (freq <= .460)]
    mean, sd = float(np.mean(noise)), float(np.std(noise, ddof=1))
    excess = float(power[-1])-mean
    return dict(amplitude=round(float(np.sqrt(max(0, excess))), 6), noise=round(float(np.sqrt(mean)), 6),
                k_score=round(excess/sd, 4) if sd > 1e-12 else None,
                spectrum=[dict(x=round(float(f), 6), y=round(float(p), 8)) for f, p in zip(freq, power)])


def twa_analysis(raw, rows, times, rr, valid, options):
    out = dict(status='insufficient', windows=[], tested_windows=0,
               method='128 个连续正常搏、步长 64 搏；PR 去基线、R 对齐。固定共同 ST-T 窗（R 后 100 ms 至 min(450 ms, 最短 RR×0.6)）；沿心搏轴 FFT，0.5 cycles/beat 与 0.431–0.460 噪声带比较。无插值补搏。形态相关和 RR 稳定性为软件质控，不输出阳性/阴性或风险等级。',
               unit=amplitude_unit(options))
    inside = np.flatnonzero((times >= options['start_s']) & (times < options['start_s']+options['duration_s']))
    if not len(inside):
        return dict(out, reason='所选片段无心搏')
    for i in range(int(inside[0]), int(inside[-1])-126, 64):
        idx = np.arange(i, i+128)
        out['tested_windows'] += 1
        if not np.all(valid[idx]) or np.max(np.abs(np.diff(rr[idx])/rr[idx][:-1])) > .2:
            continue
        if idx[-1]+1 >= len(rows) or not valid[idx[-1]+1] or rr[idx[-1]+1]<400:
            continue
        if rr[idx].min() < 400 or rr[idx].max() > 1500:
            continue
        samples = [rows[k]['sample_index'] for k in idx]
        if samples[0] < 50 or samples[-1]+130 >= len(raw):
            continue
        matrix = beat_matrix(raw, samples)
        clipped=np.any(np.abs(raw[np.array(samples)[:,None]+np.arange(-50,130)].astype(float))>=32760,axis=(0,1))
        end = 50+int(min(450, float(min(rr[idx].min(), rr[idx[-1]+1]))*.6)/5)
        for j, lead in enumerate(LEADS):
            x = matrix[:, :, j]
            template = np.median(x[:, 35:67], axis=0)
            centered = x[:, 35:67]-np.mean(x[:, 35:67], axis=1)[:, None]
            template -= np.mean(template)
            corr = centered @ template / np.maximum(1e-9, np.linalg.norm(centered, axis=1)*np.linalg.norm(template))
            if clipped[j] or np.min(corr) < .9 or np.ptp(template) < 2 or np.max(np.abs(x)) > 32000:
                continue
            st = x[:, 70:end] * (options['uv_per_unit'] or 1)
            # Reject substantial ST-T shape changes, without replacing alternation phase.
            shape = st-np.mean(st, axis=1)[:, None]
            ref = np.median(shape, axis=0)
            correlations = shape @ ref / np.maximum(1e-9, np.linalg.norm(shape, axis=1)*np.linalg.norm(ref))
            if np.min(correlations) < .6 or np.ptp(ref) < .5*(options['uv_per_unit'] or 1):
                continue
            result = alternans_spectrum(st)
            result.update(lead=lead, start_s=float(times[i]), end_s=float(times[i+127]), beat_count=128,
                          even=[dict(x=100+k*5, y=round(float(v), 5)) for k, v in enumerate(st[::2].mean(axis=0))],
                          odd=[dict(x=100+k*5, y=round(float(v), 5)) for k, v in enumerate(st[1::2].mean(axis=0))])
            out['windows'].append(result)
    out['windows'].sort(key=lambda w: -w['amplitude'])
    out.update(status='research' if out['windows'] else 'insufficient',
               reason='按交替幅度从高到低列出窗口/导联；运动、呼吸与电极变化可能产生伪交替，须回看原始波形' if out['windows'] else '没有满足连续 128 搏与形态/节律质控的窗口；不能解释为无 TWA')
    return out


def sap_analysis(times, rr, valid, duration, options):
    start = options['sap_start_s']
    end = min(duration, options['sap_end_s'] if options['sap_end_s'] is not None else duration)
    out = dict(status='insufficient', start_s=start, end_s=end, windows=[], candidate_windows=0, valid_minutes=0,
               method='ECG 周期性 RR 变化研究筛查（非 ACAT 复现）：不重叠 5 分钟窗、正常 NN ≥95%、最大间隙 ≤3 s；1 Hz 插值、线性去趋势、5 s 平滑；25–130 s 周期自相关 ≥0.5、该频带功率占比 ≥0.6、RR P95−P5 ≥80 ms 时列为候选。阈值为未验证工程阈值，不是呼吸事件判据。',
               reason='无呼吸/血氧与睡眠分期；不输出 AHI、呼吸暂停次数、睡眠时长或确诊结论。阴性结果不能排除睡眠呼吸暂停。')
    for a in np.arange(start, end-299.999, 300):
        l, r = np.searchsorted(times, [a, a+300])
        t, v, ok = times[l:r], rr[l:r], valid[l:r]
        item = dict(start_s=float(a), end_s=float(a+300), valid=False, candidate=False)
        if len(t) < 100 or ok.mean() < .95 or np.count_nonzero(ok) < 100:
            out['windows'].append(dict(item, reason='正常 NN 比例 / 数量不足'))
            continue
        t, v = t[ok], v[ok]
        if max(t[0]-a, a+300-t[-1], float(np.max(np.diff(t)))) > 3:
            out['windows'].append(dict(item, reason='缺口超过 3 秒，不跨缺口筛查'))
            continue
        x = np.interp(np.arange(300)+a, t, v)
        x -= np.polyval(np.polyfit(np.arange(300), x, 1), np.arange(300))
        x = np.convolve(np.pad(x, (2, 2), mode='edge'), np.ones(5)/5, mode='valid')
        power = np.abs(np.fft.rfft(x*np.hanning(300)))**2
        freq = np.fft.rfftfreq(300)
        band = (freq >= 1/130) & (freq <= 1/25)
        fraction = float(power[band].sum()/max(1e-9, power[1:].sum()))
        correlations = [float(np.dot(x[:-lag], x[lag:])/max(1e-9, np.linalg.norm(x[:-lag])*np.linalg.norm(x[lag:]))) for lag in range(25, 131)]
        period = 25+int(np.argmax(correlations))
        excursion = float(np.percentile(x, 95)-np.percentile(x, 5))
        candidate = max(correlations) >= .5 and fraction >= .6 and excursion >= 80
        item.update(valid=True, candidate=bool(candidate), period_s=period, autocorrelation=round(max(correlations), 4), band_fraction=round(fraction, 4), excursion_ms=round(excursion, 3))
        out['windows'].append(item)
        out['valid_minutes'] += 5
        out['candidate_windows'] += int(candidate)
    if out['valid_minutes']:
        out['status'] = 'research'
    return out


@source_read
def analyze(path, index, options=None):
    options = normalize_options(options)
    rows = sorted(index['rows'], key=lambda x: x['sample_index'])
    excluded = [(e['time_s'], e['end_s']) for e in index['events'] if e['category'] == 'AF']
    basis = basis_for(path, rows, excluded, options)
    if options['markers'] and options['marker_basis'] != basis:
        raise ValueError('QT 人工端点依据已失效（心搏、原数据或片段已变化）；请重新计算自动端点后复核')
    key = basis+json.dumps(options, sort_keys=True)
    with _lock:
        if key in _cache:
            _cache.move_to_end(key)
            return json.loads(_cache[key])
    size = require_waveform_file(path).st_size
    raw = np.memmap(path, dtype='<i2', mode='r', shape=(size//16, 8))
    duration = len(raw)/FS
    if options['start_s'] >= duration or options['sap_start_s'] >= duration:
        raise ValueError('测量或筛查起点超出记录范围')
    times, rr, valid = nn_mask(rows, excluded)
    qt, median = qtd_analysis(raw, rows, times, rr, valid, options)
    result = dict(version=VERSION, basis=basis, options=options, sample_rate_hz=FS, duration_s=duration,
                  calibration=voltage_estimate_note(options['voltage_estimate']) if options['voltage_estimate'] else '按使用者录入系数换算，非软件验证' if options['uv_per_unit'] else '未校准设备单位',
                  calibration_verified=False,
                  qtd=qt, vcg=vcg_analysis(median, qt, options),
                  twa=twa_analysis(raw, rows, times, rr, valid, options),
                  sap=sap_analysis(times, rr, valid, duration, options),
                  vlp=dict(status='unsupported', reason='当前采集为 200 Hz（Nyquist 100 Hz），不能覆盖常用晚电位 40–250 Hz 带宽。插值不能恢复未采集的高频信息；需要足够带宽、高采样率、校准与低噪声信号平均输入。'))
    del raw
    encoded = json.dumps(result, allow_nan=False)
    with _lock:
        _cache[key] = encoded
        while len(_cache) > 8:
            _cache.popitem(last=False)
    return json.loads(encoded)


def report_documents(result):
    """One evidence model for browser preview and server PDF, with bounded pages."""
    from .report_sections import PAGE_TITLES
    from .report_paper_pdf import wrap_text
    output = {}
    options = result['options']
    def value(v):
        return '—' if v is None else str(v)
    def add(key, paragraphs=(), charts=(), rows=()):
        lines=[line for row in rows for line in wrap_text(row, 65)]
        # A chart page reserves its own body. Tables continue on separate pages.
        base=dict(key=key,title=PAGE_TITLES[key],paragraphs=list(paragraphs),charts=list(charts),rows=[])
        output.setdefault(key,[]).append(base)
        capacity=12 if charts else 24
        base['rows']=lines[:capacity]
        for i in range(capacity,len(lines),28):
            output[key].append(dict(key=key,title=PAGE_TITLES[key]+'（续）',paragraphs=[],charts=[],rows=lines[i:i+28]))
    common=f"研究算法 {result['version']} · 依据 {result['basis']} · 200 Hz / 5 ms。结果未经临床验证，不用于独立诊断。"
    if options.get('voltage_estimate'):
        common += voltage_estimate_note(options['voltage_estimate']) + '。'
    q=result['qtd']
    rows=[f"{r['lead']} · QT {value(r.get('qt_ms'))} · QTcB {value(r.get('qtc_bazett_ms'))} · QTcF {value(r.get('qtc_fridericia_ms'))} ms · {r['reason']}" for r in q['leads']]
    add('qtd',[common,q['method'],q['reason'],f"片段：记录后 {options['start_s']}–{min(result['duration_s'],options['start_s']+options['duration_s'])} s；参与 {q['beat_count']} 搏；有效导联 {q.get('valid_leads',0)}。",f"QTd {value(q['qtd_ms'])} ms；QTcB 离散度 {value(q['qtc_bazett_dispersion_ms'])} ms；QTcF 离散度 {value(q['qtc_fridericia_dispersion_ms'])} ms。"],rows=rows)
    for i in range(0,len(q['leads']),2):
        leads=q['leads'][i:i+2]
        add('qtd',['中位心搏 · 相对 R 峰时间（ms） / 未校准设备单位；竖标为测量端点，不是诊断。'],
            [dict(title=r['lead']+' · '+r['reason'],points=r['points'],markers=[r['q_ms'],r['t_ms']] if r['valid'] else []) for r in leads])
    v=result['vcg']
    add('vcg',[common,v['method'],v['reason'],f"幅度：{v.get('unit','—')}；峰值模长 {value(v.get('peak_magnitude'))}。",f"校准依据：{options['calibration_note'] or '未提供；不报告 mV / µV'}"],
        [dict(title=p['title']+' · '+v['unit'],points=p['points'],xy=True) for p in v['loops']])
    t=result['twa'];w=t['windows']
    add('twa',[common,t['method'],t['reason'],f"分析所选 {options['duration_s']} s 片段；检查 {t['tested_windows']} 个窗口，有效窗口/导联组合 {len(w)}；幅度单位 {t['unit']}。K 为频谱比值，不是患病概率；— 表示噪声方差不足。"],
        rows=[f"{r['lead']} · 记录后 {r['start_s']}–{r['end_s']} s · A={r['amplitude']} · 噪声={r['noise']} · K={value(r['k_score'])}" for r in w])
    if w:
        r=w[0]
        add('twa',[f"最大幅度组合 {r['lead']} / 记录后 {r['start_s']}–{r['end_s']} s；未作多重比较校正，不按此值判阳性。"],
            [dict(title='频谱 · cycles/beat / '+t['unit']+'²',points=r['spectrum']),
             dict(title='偶数搏均值 · 相对 R ms / '+t['unit'],points=r['even']),
             dict(title='奇数搏均值 · 相对 R ms / '+t['unit'],points=r['odd'])])
    s=result['sap']
    add('sap',[common,s['method'],s['reason'],f"分析范围：记录后 {s['start_s']}–{s['end_s']} s（不假定睡眠）；可分析 {s['valid_minutes']} 分钟；周期性变化候选 {s['candidate_windows']} 个 5 分钟窗。尾部不足 5 分钟不分析。"],
        [dict(title='候选时段 · 相对记录小时 / 0 否、1 候选、空缺不可分析',bars=True,points=[dict(x=r['start_s']/3600,y=int(r['candidate']) if r['valid'] else None) for r in s['windows']])],
        [f"记录后 {r['start_s']}–{r['end_s']} s · "+(f"{'候选' if r['candidate'] else '未达工程阈值'} · 周期 {r['period_s']} s · 自相关 {r['autocorrelation']} · 频带占比 {r['band_fraction']}" if r['valid'] else r['reason']) for r in s['windows']])
    return output
