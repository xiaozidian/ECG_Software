"""Measured HRV evidence; no automatic risk/diagnosis or extrapolated 24-hour data.

The browser Demo implements the same contract in hrv-analysis.js. Spectra are
averages of eligible 5-minute blocks, NOT a spectrum of a concatenated day.
"""
from bisect import bisect_right
import cmath
import math
import statistics
from datetime import datetime, timedelta
from .clinical_analysis import hrv_windows

METHOD = ('连续 N-N；三角指数箱宽 7.8125 ms。完整 5 分钟段要求 ≥30 个 NN、NN 覆盖 ≥80%；'
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


def spectrum(nn):
    """One 256-second periodogram wholly inside the NN observations."""
    times = [r[2] for r in nn]
    if not times or times[-1] - times[0] < 255.75:
        return None
    start = (times[0] + times[-1] - 255.75) / 2
    values = []
    for i in range(1024):
        t = start + i / 4
        k = max(1, bisect_right(times, t))
        k = min(k, len(times)-1)
        if times[k]-times[k-1] > 5:
            return None
        f = (t-times[k-1])/(times[k]-times[k-1])
        values.append(nn[k-1][3]*(1-f)+nn[k][3]*f)
    avg = mean(values)
    window = [.5-.5*math.cos(2*math.pi*i/1023) for i in range(1024)]
    transformed = fft([(x-avg)*w for x,w in zip(values,window)])
    scale = 4*sum(w*w for w in window)
    return [2*abs(transformed[k])**2/scale for k in range(129)]


def analyze_hrv(feed, start_time, window=0, st_trends=None):
    result = hrv_windows(feed, start_time, window)
    lo, hi = result['start_s'], result['end_s']
    rows, opts = feed.beats, feed.document['settings']
    nn = [(i,a['sample_index']/200,b['sample_index']/200,b['rr_ms'])
          for i,(a,b) in enumerate(zip(rows,rows[1:]))
          if a['class_code'] == b['class_code'] == 'N' and opts['nn_min'] <= b['rr_ms'] <= opts['nn_max']]
    try:
        clock = datetime.fromisoformat(str(start_time).replace('Z','+00:00'))
    except (ValueError,TypeError):
        clock = None
    buckets = {}
    for r in nn:
        bucket = math.floor((r[1]-lo)/300)
        if bucket >= 0 and r[2] <= min(hi,lo+(bucket+1)*300):
            buckets.setdefault(bucket,[]).append(r)
    blocks = []
    for k, chosen in sorted(buckets.items()):
        start, end = lo+k*300, lo+(k+1)*300
        values = [r[3] for r in chosen]
        if end > hi or len(values)<30 or sum(values)/1000<240:
            continue
        blocks.append({'start_s':start,'end_s':end,'mean':mean(values),'sd':sd(values),'psd':spectrum(chosen)})
    def intervals(kind):
        if kind=='full': return [(lo,hi)]
        wanted=[]
        for h in result['hourly']:
            if clock and ((6 <= (clock+timedelta(seconds=h['start_s'])).hour < 22) == (kind=='day')):
                if wanted and wanted[-1][1]==h['start_s']: wanted[-1]=(wanted[-1][0],h['end_s'])
                else: wanted.append((h['start_s'],h['end_s']))
        return wanted
    def extend(target, spans):
        chosen = [r for r in nn if any(r[1]>=a and r[2]<=b for a,b in spans)]
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
