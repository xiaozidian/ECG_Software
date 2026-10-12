"""Measured HRV evidence; no automatic risk/diagnosis or extrapolated 24-hour data.

The browser Demo implements the same contract in hrv-analysis.js. Spectra are
averages of eligible 5-minute blocks, NOT a spectrum of a concatenated day.
"""
from bisect import bisect_left, bisect_right
import cmath
import math
import statistics
from datetime import datetime, timedelta
from .clinical_analysis import hrv_windows
from .rr_quality import nn_intervals, five_minute_blocks, NNWindowIndex

METHOD = ('连续 N-N，整段排除房颤/房扑确认及待复核区间；三角指数箱宽 7.8125 ms。完整 5 分钟段要求 ≥30 个 NN、NN 覆盖 ≥80%；'
          '频谱以 4 Hz 线性插值、1024 点 Hann 窗、去均值 FFT 估计，超过 5 秒缺口不插值。'
          '显示合格短段平均谱，不是全程 24 小时谱；VLF 仅探索性估计，无 ULF。日夜为钟点代理，非实际睡眠分期。')


def rnd(x):
    return round(x, 4) if x is not None and math.isfinite(x) else None


def mean(x):
    return sum(x) / len(x) if x else None


def sd(x):
    return statistics.stdev(x) if len(x) > 1 else None


def fft(values):
    n = len(values)
    a = [complex(x) for x in values]
    j = 0
    for i in range(1, n):
        bit = n >> 1
        while j & bit:
            j ^= bit
            bit >>= 1
        j ^= bit
        if i < j:
            a[i], a[j] = a[j], a[i]
    size = 2
    while size <= n:
        step = cmath.exp(-2j * math.pi / size)
        for start in range(0, n, size):
            w = 1
            for k in range(size // 2):
                even, odd = a[start+k], w*a[start+k+size//2]
                a[start+k], a[start+k+size//2] = even+odd, even-odd
                w *= step
        size *= 2
    return a


def spectrum(nn, excluded=()):
    """One 256-second periodogram wholly inside the NN observations."""
    times = [r[2] for r in nn]
    if (len(times)<2 or any(not math.isfinite(r[2]) or not math.isfinite(r[3]) for r in nn)
            or any(b<=a for a,b in zip(times,times[1:])) or times[-1] - times[0] < 255.75):
        return None
    start = (times[0] + times[-1] - 255.75) / 2
    values = []
    for i in range(1024):
        t = start + i / 4
        k = max(1, bisect_right(times, t))
        k = min(k, len(times)-1)
        if times[k]-times[k-1] > 5 or any(a<times[k] and b>times[k-1] for a,b in excluded):
            return None
        f = (t-times[k-1])/(times[k]-times[k-1])
        values.append(nn[k-1][3]*(1-f)+nn[k][3]*f)
    avg = mean(values)
    window = [.5-.5*math.cos(2*math.pi*i/1023) for i in range(1024)]
    transformed = fft([(x-avg)*w for x,w in zip(values,window)])
    scale = 4*sum(w*w for w in window)
    return [(1 if k == 0 else 2)*abs(transformed[k])**2/scale for k in range(129)]


def analyze_hrv(feed, start_time, window=0, st_trends=None):
    result = hrv_windows(feed, start_time, window)
    lo, hi = result['start_s'], result['end_s']
    rows, opts = feed.beats, feed.document['settings']
    nn = nn_intervals(feed)
    nn_windows = NNWindowIndex(nn)
    row_times = [r['sample_index']/200 for r in rows]
    ordered_rows = all(a <= b for a, b in zip(row_times, row_times[1:]))
    try:
        clock = datetime.fromisoformat(str(start_time).replace('Z','+00:00'))
    except (ValueError,TypeError):
        clock = None
    blocks = []
    for start, end, chosen in five_minute_blocks(nn, hi, lo):
        values = [r[3] for r in chosen]
        blocks.append({'start_s':start,'end_s':end,'mean':mean(values),'sd':sd(values),'psd':spectrum(chosen,getattr(feed,'excluded_rhythm_intervals',()))})
    def intervals(kind):
        if kind=='full': return [(lo,hi)]
        wanted=[]
        for h in result['hourly']:
            if clock and ((6 <= (clock+timedelta(seconds=h['start_s'])).hour < 22) == (kind=='day')):
                if wanted and wanted[-1][1]==h['start_s']: wanted[-1]=(wanted[-1][0],h['end_s'])
                else: wanted.append((h['start_s'],h['end_s']))
        return wanted
    def extend(target, spans):
        chosen = nn_windows.contained(spans)
        valid_blocks = [b for b in blocks if any(b['start_s']>=a and b['end_s']<=z for a,z in spans)]
        # Sparse histogram keeps every NN, including configured NN bounds >2 s.
        bins={}
        for r in chosen:
            k=math.floor(r[3]/7.8125);bins[k]=bins.get(k,0)+1
        psds=[b['psd'] for b in valid_blocks if b['psd'] is not None]
        psd=[mean([p[k] for p in psds]) for k in range(129)] if psds else []
        def band(a,b): return rnd(sum(p*4/1024 for k,p in enumerate(psd) if a<=k*4/1024<b)) if psd else None
        lf,hf=band(.04,.15),band(.15,.4)
        target.update(sdann_ms=rnd(sd([b['mean'] for b in valid_blocks])),sdnn_index_ms=rnd(mean([b['sd'] for b in valid_blocks])),
                      triangular_index=rnd(len(chosen)/max(bins.values())) if bins else None,
                      histogram=[{'rr_ms':rnd(k*7.8125),'count':v} for k,v in sorted(bins.items())],
                      psd=[{'hz':k*4/1024,'power':rnd(p)} for k,p in enumerate(psd)],
                      frequency={'total_ms2':band(.0033,.4),'vlf_ms2':band(.0033,.04),'lf_ms2':lf,'hf_ms2':hf,'lf_hf':rnd(lf/hf) if hf else None},
                      five_minute_blocks=len(valid_blocks),spectral_blocks=len(psds),spectral_coverage_s=len(psds)*256,
                      spectral_reason='' if psds else '无满足覆盖/连续性条件的完整 5 分钟段，频谱不可估计')
    for key,period in result['periods'].items(): extend(period,intervals(key))
    for hour in result['hourly']:
        extend(hour,[(hour['start_s'],hour['end_s'])])
        if ordered_rows:
            selected=rows[bisect_left(row_times, hour['start_s']):bisect_left(row_times, hour['end_s'])]
        else:
            selected=[r for r in rows if hour['start_s'] <= r['sample_index']/200 < hour['end_s']]
        valid=[r for r in selected if r['class_code'] not in ('X','O','Y','T')]
        rates=[r['hr'] for r in valid if (r.get('hr') or 0)>0 and (r.get('rr_ms') or 0)>0]
        hour.update(total_beats=len(valid),v_count=sum(r['class_code']=='V' for r in valid),s_count=sum(r['class_code']=='S' for r in valid),
                    pause_count=sum(r.get('rr_ms',0)>2500 for r in valid),pause_over3=sum(r.get('rr_ms',0)>3000 for r in valid),
                    min_hr=min(rates) if rates else None,max_hr=max(rates) if rates else None,
                    avg_hr=rnd(60000/mean([r['rr_ms'] for r in valid if (r.get('hr') or 0)>0 and (r.get('rr_ms') or 0)>0])) if rates else None)
    minute_buckets={}
    for r in nn:
        if lo <= r[1] and r[2] <= hi: minute_buckets.setdefault(int((r[2]-lo)/60),[]).append(r[3])
    trend=[]; ranges=[(170,float('inf'),'≥170'),(140,170,'140–169'),(110,140,'110–139'),(80,110,'80–109'),(50,80,'50–79'),(0,50,'≤49')]
    rate_groups=[[] for _ in ranges]; counts=[0]*6
    for k in range(math.ceil((hi-lo)/60)):
        values=minute_buckets.get(k,[]);rate=60000/mean(values) if values else None
        trend.append({'time_s':lo+k*60,'hr':rnd(rate),'sdnn_ms':rnd(sd(values))})
        if rate is not None:
            for i,(a,b,_) in enumerate(ranges):
                if a<=rate<b: rate_groups[i].extend(values);counts[i]+=1;break
    result.update(method=METHOD,trend=trend,rate_sdnn=[{'hr_range':label,'minute_bins':counts[i],'sdnn_ms':rnd(sd(rate_groups[i]))} for i,(_,_,label) in enumerate(ranges)],
                  st_trends=st_trends or {},st_units='device',st_calibrated=False,
                  risk_note='SDNN 仅为统计参考，不单独给出高/中/低风险或诊断；须结合记录时长、节律、伪差及临床情况。',
                  schema_version='hrv-evidence-v1')
    return result


# This is a compatibility profile, not a clinical eligibility standard.  Keep the
# unedited analyze_hrv contract above byte-for-byte in its existing math/fields.
HRV_REVIEW_PROFILE = {
    'id': 'fixed-300s-fft-compat-v1',
    'sample_rate_hz': 200,
    'block_seconds': 300,
    'minimum_nn_count': 30,
    'minimum_nn_coverage_s': 240,
    'eligibility_basis': 'existing N labels, saved NN bounds and rhythm exclusions; sinus origin and signal quality are not automatically verified',
    'quality_status': 'unknown',
    'eligibility_standard': 'existing engineering compatibility protocol, not a universal guideline',
    'pnn50': {'threshold_ms': 50, 'comparison': 'strictly_greater',
              'denominator': 'eligible consecutive NN differences', 'unit': 'percent'},
    'sdnn': {'unit': 'ms', 'variance_ddof': 1, 'minimum_count': 3},
    'spectrum': {'method': 'FFT', 'resample_hz': 4, 'samples': 1024,
                 'window': 'symmetric Hann', 'density_unit': 'ms²/Hz',
                 'band_unit': 'ms²', 'gap_limit_s': 5,
                 'aggregation': 'mean of qualified fixed-grid short-segment spectra',
                 'vlf_interpretation': 'exploratory', 'ulf_available': False,
                 'lf_hf_ratio': 'ratio of bands rounded to 4 decimals; null when rounded HF is zero'},
    'exclusion_interval': 'half-open sample intervals; preserve original NN adjacency and the 300-second grid',
    'confirmation_scope': 'physician review declaration for one current 24-hour window; not clinical validation or a sinus-rhythm gold standard',
}


def _review_spans(exclusions, duration):
    """Validate public sample ranges; never clamp or infer out-of-recording data."""
    limit = int(math.floor(duration * 200 + 1e-7))
    spans = []
    for item in exclusions:
        if not isinstance(item, dict):
            raise ValueError('HRV 排除区间必须为对象')
        a, b = item.get('start_sample'), item.get('end_sample')
        if type(a) is not int or type(b) is not int or not 0 <= a < b <= limit:
            raise ValueError('HRV 排除区间须为记录内半开的整数采样范围')
        spans.append((a / 200, b / 200))
    merged = []
    for a, b in sorted(spans):
        if merged and a <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(b, merged[-1][1]))
        else:
            merged.append((a, b))
    return merged


def _span_seconds(spans, start, end):
    return sum(max(0, min(b, end) - max(a, start)) for a, b in spans)


class _HrvExcludedFeed:
    """Overlay exclusions without modifying the feed, labels, settings or samples."""
    def __init__(self, feed, spans):
        self._feed = feed
        self.excluded_rhythm_intervals = tuple(getattr(feed, 'excluded_rhythm_intervals', ())) + tuple(spans)

    def __getattr__(self, name):
        return getattr(self._feed, name)


def _review_time_metrics(chosen, start, end):
    values = [r[3] for r in chosen]
    diffs = [b[3] - a[3] for a, b in zip(chosen, chosen[1:])
             if b[0] == a[0] + 1 and a[1] >= start and b[2] <= end]
    bins = {}
    for value in values:
        k = math.floor(value / 7.8125)
        bins[k] = bins.get(k, 0) + 1
    # Match hrv_windows rounding and sample SDNN threshold; do not normalize to
    # an external library's >=50/fraction or total-NN denominator convention.
    two = lambda x: round(x, 2) if x is not None else None
    return dict(nn_count=len(values), coverage_s=round(end-start, 3),
                valid_nn_s=round(sum(values)/1000, 3),
                mean_nn_ms=two(mean(values)), sdnn_ms=two(sd(values)) if len(values) >= 3 else None,
                rmssd_ms=two(math.sqrt(mean([v*v for v in diffs]))) if diffs else None,
                pnn50_pct=two(100*sum(abs(v)>50 for v in diffs)/len(diffs)) if diffs else None,
                nn50_count=sum(abs(v)>50 for v in diffs), consecutive_difference_count=len(diffs),
                sdann_ms=None, sdnn_index_ms=rnd(sd(values)) if len(values) >= 30 and sum(values) >= 240000 and end-start == 300 else None,
                triangular_index=rnd(len(values)/max(bins.values())) if bins else None,
                histogram=[{'rr_ms':rnd(k*7.8125), 'count':v} for k,v in sorted(bins.items())])


def _review_spectral_reason(chosen, excluded):
    times = [r[2] for r in chosen]
    if len(times) < 2:
        return 'too_few_nn_observations'
    if (any(not math.isfinite(r[2]) or not math.isfinite(r[3]) for r in chosen)
            or any(b <= a for a,b in zip(times,times[1:]))):
        return 'invalid_nn_time_order'
    if times[-1]-times[0] < 255.75:
        return 'insufficient_spectral_observation_span'
    start = (times[0]+times[-1]-255.75)/2
    for i in range(1024):
        t = start+i/4
        k = min(max(1,bisect_right(times,t)),len(times)-1)
        if times[k]-times[k-1] > 5:
            return 'spectral_gap_over_5s'
        if any(a < times[k] and b > times[k-1] for a,b in excluded):
            return 'spectral_interpolation_crosses_exclusion'
    return ''


def _review_block(chosen, start, end, grid_end, excluded):
    out = _review_time_metrics(chosen, start, end)
    reasons = []
    if end < grid_end:
        reasons.append('incomplete_300s_block')
    if len(chosen) < 30:
        reasons.append('nn_count_below_30')
    if sum(r[3] for r in chosen) < 240000:
        reasons.append('nn_coverage_below_240s')
    qualified = not reasons
    reason = _review_spectral_reason(chosen, excluded) if qualified else 'block_not_qualified'
    psd = spectrum(chosen, excluded) if qualified and not reason else None
    if psd is None and not reason:
        reason = 'spectrum_unavailable'
    def band(a,b):
        return rnd(sum(p*4/1024 for k,p in enumerate(psd) if a <= k*4/1024 < b)) if psd is not None else None
    lf,hf = band(.04,.15),band(.15,.4)
    out.update(qualified=qualified, qualification_reasons=reasons,
               spectral_qualified=psd is not None, spectral_reason=reason,
               psd=[{'hz':k*4/1024,'power':rnd(p)} for k,p in enumerate(psd)] if psd is not None else [],
               frequency={'total_ms2':band(.0033,.4),'vlf_ms2':band(.0033,.04),
                          'lf_ms2':lf,'hf_ms2':hf,'lf_hf':rnd(lf/hf) if hf else None},
               five_minute_blocks=int(qualified), spectral_blocks=int(psd is not None),
               spectral_coverage_s=256 if psd is not None else 0,
               nn_eligible_count=len(chosen), quality_status='unknown', sinus_verified=False)
    return out


def analyze_hrv_review(feed, start_time, window=0, exclusions=()):
    """Expose all fixed-grid blocks and a strict-NN exclusion-only comparison.

    baseline is always the same strict analyzer without HRV edits.  Unqualified
    blocks remain in the default time-domain NN population.  Existing coverage_s
    continues to mean recording-range coverage; retained range coverage is
    separately exposed so it is never confused with measured signal quality.
    """
    import copy
    spans = _review_spans(exclusions, feed.duration)
    baseline = analyze_hrv(feed, start_time, window)
    projected = _HrvExcludedFeed(feed, spans) if spans else feed
    reviewed = analyze_hrv(projected, start_time, window) if spans else copy.deepcopy(baseline)
    lo,hi = baseline['start_s'],baseline['end_s']
    nn = nn_intervals(feed)
    reviewed_nn = nn_intervals(projected) if spans else nn
    original_index,review_index = NNWindowIndex(nn),NNWindowIndex(reviewed_nn)
    original_excluded = tuple(getattr(feed,'excluded_rhythm_intervals',()))
    reviewed_excluded = tuple(getattr(projected,'excluded_rhythm_intervals',()))
    blocks = []
    for k in range(math.ceil((hi-lo)/300)):
        start,grid_end = lo+k*300,lo+(k+1)*300
        end = min(hi,grid_end)
        original = _review_block(original_index.contained([(start,end)]),start,end,grid_end,original_excluded)
        changed = _span_seconds(spans,start,end)
        current = _review_block(review_index.contained([(start,end)]),start,end,grid_end,reviewed_excluded) if changed else copy.deepcopy(original)
        blocks.append(dict(id=f'5m-{round(start*200)}-{round(grid_end*200)}',
                           window_index=baseline['window_index'],grid_index=k,
                           start_sample=round(start*200),end_sample=round(end*200),grid_end_sample=round(grid_end*200),
                           start_s=start,end_s=end,duration_s=end-start,complete=end == grid_end,
                           excluded_s=round(changed,6),retained_s=round(end-start-changed,6),
                           baseline=original,reviewed=current,
                           hour_overlaps=[i for i,h in enumerate(baseline['hourly']) if h['start_s'] < end and h['end_s'] > start]))
    coverage = dict(record_start_s=0,record_end_s=feed.duration,window_start_s=lo,window_end_s=hi,
                    excluded_s=round(_span_seconds(spans,lo,hi),6),
                    retained_s=round(hi-lo-_span_seconds(spans,lo,hi),6),
                    clock_available=baseline['clock_available'],
                    hourly=[dict(start_s=h['start_s'],end_s=h['end_s'],partial=h['partial']) for h in baseline['hourly']])
    return dict(baseline=baseline,reviewed=reviewed,blocks=blocks,coverage=coverage,
                profile=copy.deepcopy(HRV_REVIEW_PROFILE),exclusions=copy.deepcopy(list(exclusions)))
