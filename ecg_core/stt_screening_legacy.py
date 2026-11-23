"""Conservative ambulatory ST-T screening with mandatory physician review.

The detector works in the source device scale and emits review candidates,
never a diagnosis. It uses normal-beat blocks, local references, J+60 ms
measurements, persistence rules, and signal/axis-shift quality gates.
"""

from __future__ import annotations

import copy
import math
import mmap
import re
import statistics
import struct
from hashlib import sha256
from collections import OrderedDict
from bisect import bisect_left, insort
from pathlib import Path

import numpy as np

from .config import CHANNEL_COUNT, SAMPLE_RATE
from .source_identity import require_waveform_file, source_read
from .stt_records import RHYTHM_POLICY

ALGORITHM_VERSION = "stt-screening-0.4.0-comprehensive-independent"
LEADS = ("I", "II", "III", "aVR", "aVL", "aVF", "V1", "V2", "V3", "V4", "V5", "V6")
_FRAME = struct.Struct("<8h")
_CACHE: OrderedDict[tuple, dict] = OrderedDict()
_CACHE_LIMIT = 8

DEFAULT_CONFIG = {
    "block_seconds": 16,
    "minimum_normal_beats": 3,
    "maximum_beats_per_block": 7,
    "st_measurement_ms": 60,
    "entry_threshold_units": 50.0,
    "target_threshold_units": 100.0,
    "minimum_target_duration_s": 60,
    "exit_confirmation_s": 30,
    "reference_window_minutes": 20,
    "axis_shift_qrs_fraction": 0.35,
    "t_inversion_minimum_units": 75.0,
    "t_low_maximum_units": 50.0,
    "t_low_r_ratio": 0.10,
    "t_low_minimum_r_units": 200.0,
    "t_biphasic_minimum_units": 50.0,
    "t_noise_multiplier": 3.0,
    "stable_reference_minimum_s": 60.0,
    "maximum_trend_points_per_lead": 720,
}

# These are description contexts, not an inferred diagnosis. In particular a
# continuously negative aVR is not called an inverted T merely for its sign.
T_UPRIGHT_LEADS = frozenset(("I", "II", "V3", "V4", "V5", "V6"))
T_VARIABLE_LEADS = frozenset(("III", "aVL", "aVF", "V1", "V2"))


def t_polarity_context(lead):
    return 'expected_negative' if lead == 'aVR' else 'variable' if lead in T_VARIABLE_LEADS else 'expected_upright'

_ST_T_TERM = re.compile(
    r"(?:(?<![A-Za-z])S\s*[-–—－]?\s*T(?:\s*[-–—－]?\s*T)?(?![A-Za-z])"
    r"|ST段|T波|T倒置|T低平|T\s*[-–—]?\s*wave)", re.IGNORECASE,
)
_SOURCE_FRAGMENT_SPLIT = re.compile(r"(?<=[。！？；!?;])\s*|\n+")
_CASE_AMPLITUDE = re.compile(
    r"(?<![A-Za-z0-9])(?:[+\-−＋－]?\s*\d+(?:\.\d+)?)\s*(?:mV|µV|μV)", re.IGNORECASE,
)


def extract_stt_source_report(conclusion: str) -> dict:
    """Extract ST/T source wording while hiding unverified case amplitudes."""
    if not isinstance(conclusion, str):
        conclusion = ""
    fragments, redacted_any = [], False
    for raw in _SOURCE_FRAGMENT_SPLIT.split(conclusion):
        fragment = raw.strip()
        if not fragment or not _ST_T_TERM.search(fragment):
            continue
        redacted, count = _CASE_AMPLITUDE.subn("【病例幅度已隐藏】", fragment)
        redacted_any = redacted_any or count > 0
        if redacted not in fragments:
            fragments.append(redacted)
    return {
        "origin": "source_report_conclusion", "available": bool(fragments),
        "text": "\n".join(fragments), "fragments": fragments,
        "is_source_excerpt": True, "software_interpretation_added": False,
        "amplitude_values_redacted": redacted_any,
    }


def _median(values, default=0.0) -> float:
    finite = [float(value) for value in values if isinstance(value, (int, float)) and math.isfinite(value)]
    return float(statistics.median(finite)) if finite else float(default)


def _mad(values) -> float:
    center = _median(values)
    return _median(abs(float(value) - center) for value in values)


def _derived(raw: tuple[int, ...]) -> tuple[float, ...]:
    lead_i, lead_ii = raw[0], raw[1]
    return (
        lead_i, lead_ii, lead_ii - lead_i, -(lead_i + lead_ii) / 2,
        lead_i - lead_ii / 2, lead_ii - lead_i / 2,
        raw[2], raw[3], raw[4], raw[5], raw[6], raw[7],
    )


def _read_leads(buffer: mmap.mmap, sample: int, total_samples: int) -> tuple[float, ...]:
    sample = max(0, min(total_samples - 1, sample))
    return _derived(_FRAME.unpack_from(buffer, sample * CHANNEL_COUNT * 2))


def _normalize_records(records) -> list[tuple[int, int, int]]:
    normalized = []
    for row in records:
        if isinstance(row, dict):
            sample, group, rr = row.get("sample_index"), row.get("group", row.get("source_group")), row.get("rr_ms", 0)
        else:
            sample, group, rr = row[0], row[2], row[6]
        if isinstance(sample, int) and isinstance(group, int):
            normalized.append((sample, group, int(rr or 0)))
    return sorted(normalized)


def _evenly(values: list, limit: int) -> list:
    if len(values) <= limit:
        return values
    return [values[round(index * (len(values) - 1) / (limit - 1))] for index in range(limit)]


def _estimate_j_sample(buffer, beats, total_samples) -> tuple[int, float]:
    """Estimate QRS end from multi-beat, multi-lead derivative energy."""
    # Identical 33 offsets and II/V1/V5 observations, batched without int16
    # overflow. No smoothing, resampling, fewer beats, or changed tie rules.
    if beats:
        positions = np.array([b[0] for b in beats])[:, None] + np.arange(-1, 33)
        np.clip(positions, 0, total_samples - 1, out=positions)
        raw = np.frombuffer(buffer, dtype='<i2').reshape(-1, CHANNEL_COUNT)
        frames = raw[positions][..., [1, 2, 6]].astype(np.float64)
        energies = np.median(np.abs(np.diff(frames, axis=1)), axis=(0, 2)).tolist()
    else:
        energies = [0.0] * 33
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


def _sample_frames(buffer, beats, offsets, total_samples):
    positions = np.array([b[0] for b in beats])[:, None] + np.array(offsets)
    np.clip(positions, 0, total_samples - 1, out=positions)
    raw = np.frombuffer(buffer, dtype='<i2').reshape(-1, CHANNEL_COUNT)
    channels = raw[positions].astype(np.float64)
    a, b = channels[..., 0], channels[..., 1]
    return np.stack((a, b, b-a, -(a+b)/2, a-b/2, b-a/2,
                     *[channels[..., i] for i in range(2, 8)]), axis=-1)


def _beat_measurements(buffer, beats, total_samples, config, *, j_sample=None, next_samples=None, morphology=True):
    """Raw per-beat observations; no average can cancel a biphasic T.

    The short J estimation block is not the event support. All qualified beats
    can be measured using this bounded vectorized batch. next_samples, when
    supplied, are real next R anchors, not neighbours rebuilt after exclusion.
    """
    if not beats:
        return {}
    if j_sample is None:
        j_sample, _ = _estimate_j_sample(buffer, beats, total_samples)
    base_frames = _sample_frames(buffer, beats, range(-40, -23, 4), total_samples)
    baseline = np.median(base_frames, axis=1)
    st_offset = j_sample + round(config["st_measurement_ms"] * SAMPLE_RATE / 1000)
    st = np.median(_sample_frames(buffer, beats, range(st_offset-2, st_offset+3), total_samples), axis=1)-baseline
    qrs_frames = _sample_frames(buffer, beats, range(-8, j_sample+1, 2), total_samples)
    qrs_relative = qrs_frames-baseline[:, None, :]
    qrs = np.max(qrs_frames, axis=1)-np.min(qrs_frames, axis=1)
    r = np.maximum(0., np.max(qrs_relative, axis=1))
    span = np.max(base_frames, axis=1)-np.min(base_frames, axis=1)
    dense_baseline=_sample_frames(buffer,beats,range(-40,-23),total_samples)
    noise = np.maximum(1.,np.maximum(
        1.4826*np.median(np.abs(dense_baseline-baseline[:, None, :]),axis=1),
        np.median(np.abs(np.diff(dense_baseline,axis=1)),axis=1)/math.sqrt(2)))
    st_j = np.median(_sample_frames(buffer, beats, range(j_sample-2, j_sample+3), total_samples), axis=1)-baseline
    st_80 = np.median(_sample_frames(buffer, beats, range(j_sample+14, j_sample+19), total_samples), axis=1)-baseline
    # The exact same candidate T search as before, with an additional real-next
    # QRS guard. Preserve both extrema instead of treating signed cancellation
    # or a negative-dominant biphasic wave as an absent/flat T.
    offsets = np.arange(j_sample+24, j_sample+73, 2)
    rr = np.maximum(np.array([b[2] for b in beats])*SAMPLE_RATE/1000, .45*SAMPLE_RATE)
    last = np.minimum(j_sample+72, np.maximum(j_sample+30, np.rint(rr*.62))).astype(int)
    if next_samples is not None:
        last = np.minimum(last, np.array(next_samples, dtype=int)-np.array([b[0] for b in beats])-8)
    allowed = offsets[None, :] <= last[:, None]
    t_frames = _sample_frames(buffer, beats, offsets, total_samples)-baseline[:, None, :]
    # A flat ST plateau at the beginning of this window is not a negative or
    # positive T lobe. Require a lobe to rise/fall and recover on both sides,
    # either across the entire T window or in a bounded 50ms neighbourhood.
    # Keep signed amplitudes relative to ISO; prominence only establishes that
    # an interior extremum is measurable, not a new voltage baseline.
    last_indices=np.maximum(0,np.count_nonzero(allowed,axis=1)-1)
    first=t_frames[:,0,:]
    final=t_frames[np.arange(len(beats)),last_indices,:]
    floor=np.maximum(2.,config['t_noise_multiplier']*noise)
    pos_candidates=[];neg_candidates=[]
    for k in range(len(offsets)) if morphology else ():
        value=t_frames[:,k,:]
        left=t_frames[:,max(0,k-5):k,:]
        right=t_frames[:,k+1:min(len(offsets),k+6),:]
        left_min=np.min(left,axis=1) if k else value
        left_max=np.max(left,axis=1) if k else value
        if right.shape[1]:
            right_allowed=allowed[:,k+1:min(len(offsets),k+6),None]
            right_min=np.min(np.where(right_allowed,right,np.inf),axis=1)
            right_max=np.max(np.where(right_allowed,right,-np.inf),axis=1)
        else:right_min=right_max=value
        positive_prominence=np.maximum(value-np.maximum(first,final),value-np.maximum(left_min,right_min))
        negative_prominence=np.maximum(np.minimum(first,final)-value,np.minimum(left_max,right_max)-value)
        pos_candidates.append(np.where(allowed[:,k,None]&(positive_prominence>=floor),np.maximum(value,0.),0.))
        neg_candidates.append(np.where(allowed[:,k,None]&(negative_prominence>=floor),np.minimum(value,0.),0.))
    pos_frames=np.stack(pos_candidates,axis=1) if morphology else np.where(allowed[:,:,None],np.maximum(t_frames,0.),0.)
    neg_frames=np.stack(neg_candidates,axis=1) if morphology else np.where(allowed[:,:,None],np.minimum(t_frames,0.),0.)
    positive=np.max(pos_frames,axis=1);negative=np.min(neg_frames,axis=1)
    pos_index=np.argmax(pos_frames,axis=1);neg_index=np.argmin(neg_frames,axis=1)
    dominant=np.where((positive>-negative)|((positive==-negative)&(pos_index<=neg_index)),positive,negative)
    raw_peak=np.max(np.where(allowed[:,:,None],np.abs(t_frames),0.),axis=1)
    unresolved=(positive==0)&(negative==0)&(raw_peak>config['t_low_maximum_units'])
    measurable = np.count_nonzero(allowed, axis=1) >= 3
    dominant[~measurable] = np.nan; positive[~measurable] = np.nan; negative[~measurable] = np.nan
    shape_measurable=measurable[:,None]&~unresolved
    dominant[~shape_measurable]=np.nan;positive[~shape_measurable]=np.nan;negative[~shape_measurable]=np.nan
    return dict(baseline=baseline, st=st, st_j=st_j, st_80=st_80,
                st_slope=(st_80-st_j)/.08, t=dominant, t_positive=positive,
                t_negative=negative, t_peak_to_peak=positive-negative, r=r,
                t_to_r=np.divide(np.maximum(positive,-negative),r,out=np.full_like(r,np.nan),where=r>0),
                noise=noise,qrs=qrs,span=span,t_measurable=measurable,t_shape_measurable=shape_measurable,
                t_window_end_offset=last,source_clipped=np.any((qrs_frames>=32767)|(qrs_frames<=-32768),axis=1))


def _block_measurement(buffer, beats, all_count, total_samples, config, *, normal_count=None, include_morphology=True) -> dict:
    j_sample, landmark_confidence = _estimate_j_sample(buffer, beats, total_samples)
    arrays = _beat_measurements(buffer, beats, total_samples, config, j_sample=j_sample,morphology=include_morphology)
    lead_values, lead_scores = {}, []
    for column, lead in enumerate(LEADS):
        data = {key: value[:,column].tolist() for key,value in arrays.items()
                if isinstance(value,np.ndarray) and value.ndim==2}
        qrs = _median(data.get('qrs',[]))
        baseline_variation = _mad(data.get('baseline',[]))+_median(data.get('span',[]))
        qrs_variation = _mad(data.get('qrs',[]))/max(qrs,1.)
        score = max(0.,min(1.,1.-min(.65,baseline_variation/max(qrs,40.))-min(.35,qrs_variation)))
        lead_scores.append(score)
        clipped = lead in ('I','II','V1','V2','V3','V4','V5','V6') and bool(beats) and bool(np.any(arrays['source_clipped'][:,column]))
        measurable = qrs>0 and not clipped
        lead_values[lead] = dict(
            st_level_units=round(_median(data.get('st',[])),2),
            t_amplitude_units=round(_median(data.get('t',[]),default=float('nan')),2) if any(math.isfinite(v) for v in data.get('t',[])) else None,
            t_positive_units=round(_median(data.get('t_positive',[])),2),
            t_negative_units=round(_median(data.get('t_negative',[])),2),
            r_amplitude_units=round(_median(data.get('r',[])),2),
            noise_units=round(_median(data.get('noise',[])),2),
            st_slope_units_per_s=round(_median(data.get('st_slope',[])),2),
            qrs_amplitude_units=round(qrs,2),quality_score=round(score,3),
            measurable=measurable,eligible=measurable and score>=.42,
            availability_reasons=(['flatline'] if qrs<=0 else [])+(['lead_engineering_quality'] if score<.42 else [])+(['source_clipping'] if clipped else []))
    limb_available=lead_values['I']['measurable'] and lead_values['II']['measurable']
    for lead in ('III','aVR','aVL','aVF'):
        lead_values[lead]['measurable']=limb_available
        lead_values[lead]['eligible']=limb_available and lead_values[lead]['quality_score']>=.42
        lead_values[lead]['availability_reasons']=[] if lead_values[lead]['eligible'] else ['source_limb_unavailable' if not limb_available else 'lead_engineering_quality']
    normal_count = len(beats) if normal_count is None else normal_count
    normal_ratio=normal_count/max(all_count,1)
    overall=max(0.,min(1.,_median(lead_scores)*min(1.,normal_ratio/.6)))
    return dict(j_offset_ms=round(j_sample*1000/SAMPLE_RATE),landmark_confidence=round(landmark_confidence,3),
                normal_beat_count=normal_count,measurement_beat_count=len(beats),normal_beat_ratio=round(normal_ratio,3),
                quality_score=round(overall,3),eligible=normal_ratio>=.35 and overall>=.42,leads=lead_values)


def _rolling_reference(values: list[dict], key: str, radius: int) -> list[float | None]:
    # Retain the exact centered window and finite-value median. Incremental
    # insertion/removal avoids re-reading and re-sorting each overlapping window.
    eligible = []
    for row in values:
        value = row.get(key)
        eligible.append(float(value) if row.get('eligible') and isinstance(value, (int, float)) and math.isfinite(value) else None)
    ordered, left, right, result = [], 0, 0, []
    for index in range(len(values)):
        end = min(len(values), index+radius+1)
        while right < end:
            if eligible[right] is not None: insort(ordered, eligible[right])
            right += 1
        while left < max(0, index-radius):
            if eligible[left] is not None: ordered.pop(bisect_left(ordered, eligible[left]))
            left += 1
        window_has_value = any(row.get('eligible') and row.get(key) is not None for row in values[left:right]) if not ordered else True
        result.append(round(float(statistics.median(ordered)), 2) if ordered else 0.0 if window_has_value else None)
    return result


def _support(point, config):
    half = config["block_seconds"] / 2
    return float(point.get("start_s", point.get("time_s", half)-half)), float(point.get("end_s", point.get("time_s", half)+half))


def _finite(value):
    return isinstance(value,(int,float)) and not isinstance(value,bool) and math.isfinite(value)


def _compact_support(points,config):
    result=[]
    for point in points:
        start,end=_support(point,config)
        if result and abs(result[-1]['end_s']-start)<1e-7:result[-1]['end_s']=end
        else:result.append(dict(start_s=start,end_s=end))
    return result


def _episode(points,lead,config,kind,label,peak,*,continuous=None,criteria=()):
    start,end=_support(points[0],config)[0],_support(points[-1],config)[1]
    flags=sorted({reason for p in points for reason in p.get('quality_flags',[])})
    if any(p.get('axis_shift_suspected') for p in points):flags=sorted(set(flags)|{'axis_shift_suspected'})
    if kind=='t_persistent_inversion' and lead in T_VARIABLE_LEADS:flags=sorted(set(flags)|{'normal_polarity_variation_possible'})
    delta=peak.get('deviation_units') if kind.startswith('st_') else (peak.get('t_amplitude_units')-peak.get('t_reference_units') if _finite(peak.get('t_amplitude_units')) and _finite(peak.get('t_reference_units')) else None)
    row=dict(kind=kind,label=label,start_s=round(start,3),end_s=round(end,3),duration_s=round(end-start,3),
        continuous_target_s=round(end-start if continuous is None else continuous,3),
        peak_time_s=round(peak['time_s'],3),peak_deviation_units=round(delta,2) if _finite(delta) else None,
        peak_st_level_units=peak.get('st_level_units'),peak_t_amplitude_units=peak.get('t_amplitude_units'),
        leads=[lead],lead=lead,quality_score=round(_median(p.get('quality_score',0) for p in points),3),
        support_intervals=_compact_support(points,config),axis_shift_suspected='axis_shift_suspected' in flags,
        quality_flags=flags,review_status='pending',diagnosis=None,criteria=list(criteria),
        threshold_scale='uncalibrated_source_device_research_units',measurement_basis='raw_per_beat_iso_and_stable_reference',
        reference_source=copy.deepcopy(peak.get('reference_source')),t_polarity_context=t_polarity_context(lead),
        boundary_resolution_s=max((p.get('boundary_resolution_s',config['block_seconds']) for p in points),default=config['block_seconds']))
    if kind=='t_wave_inversion':
        row['polarity_from']='positive' if peak.get('t_reference_units',0)>0 else 'negative'
        row['polarity_to']='positive' if peak.get('t_amplitude_units',0)>0 else 'negative'
    return row


def _lead_episodes(points: list[dict], lead: str, config: dict) -> list[dict]:
    """Absolute ST level and dynamic deviation in parallel, with one episode.

    Missing observations break continuity. An observed axis shift is retained
    as a quality flag for the doctor, not silently deleted from measurements.
    """
    episodes=[]
    for direction,kind,label in ((-1,'st_depression','ST 段压低候选'),(1,'st_elevation','ST 段抬高候选')):
        active=[];below=strong=longest=0.;last_end=None;criteria=set()
        def score(point):
            values=[direction*point[k] for k in ('st_level_units','deviation_units') if _finite(point.get(k))]
            return max(values) if values else -math.inf
        def finish():
            if active and longest+1e-9>=config['minimum_target_duration_s']:
                peak=max(active,key=score)
                episodes.append(_episode(active,lead,config,kind,label,peak,continuous=longest,criteria=sorted(criteria)))
        for point in points:
            start,end=_support(point,config)
            valid=point.get('eligible') and end>start and any(_finite(point.get(k)) for k in ('st_level_units','deviation_units'))
            if not valid or last_end is not None and abs(start-last_end)>1e-7:
                finish();active=[];below=strong=longest=0.;criteria=set()
            last_end=end
            if not valid:continue
            value=score(point)
            if value>=config['entry_threshold_units']:
                active.append(point);below=0.
                strong=strong+end-start if value>=config['target_threshold_units'] else 0.
                longest=max(longest,strong)
                for key,name in (('st_level_units','absolute_st_level'),('deviation_units','stable_reference_delta_st')):
                    if _finite(point.get(key)) and direction*point[key]>=config['target_threshold_units']:criteria.add(name)
            elif active:
                strong=0.;below+=end-start
                if below+1e-9>=config['exit_confirmation_s']:
                    finish();active=[];below=strong=longest=0.;criteria=set()
        finish()
    return episodes


def _t_conditions(point,lead,config):
    value=point.get('t_amplitude_units');reference=point.get('t_reference_units')
    positive=point.get('t_positive_units',max(0.,value) if _finite(value) else None)
    negative=point.get('t_negative_units',min(0.,value) if _finite(value) else None)
    if not point.get('eligible') or point.get('t_measurable') is False or not all(_finite(v) for v in (value,positive,negative)):
        return set()
    noise=max(1.,point.get('noise_units',1.))
    minimum=max(config['t_inversion_minimum_units'],config['t_noise_multiplier']*noise)
    both=min(positive,-negative)>=max(config['t_biphasic_minimum_units'],config['t_noise_multiplier']*noise)
    result=set()
    if _finite(reference) and abs(value)>=minimum and abs(reference)>=minimum and value*reference<0 and not both:
        result.add('t_wave_inversion')
    if lead!='aVR' and negative<=-minimum and -negative>positive and not both:
        result.add('t_persistent_inversion')
    if both:result.add('t_biphasic')
    r=point.get('r_amplitude_units');amplitude=max(positive,-negative)
    if (_finite(r) and r>=max(config['t_low_minimum_r_units'],noise*10)
            and amplitude<=config['t_low_maximum_units'] and amplitude/r<=config['t_low_r_ratio']
            and noise<=max(2.,config['t_low_maximum_units']/config['t_noise_multiplier'])
            and not both):
        result.add('t_low_flat')
    return result


def _t_episodes(points: list[dict], lead: str, config: dict) -> list[dict]:
    labels={'t_wave_inversion':'T 波极性反转候选','t_persistent_inversion':'T 波持续倒置候选',
            't_low_flat':'T 波低平候选','t_biphasic':'T 波双相候选'}
    result=[];runs={kind:[] for kind in labels};last_end=None
    def finish(kind):
        run=runs[kind]
        if not run:return
        start,end=_support(run[0],config)[0],_support(run[-1],config)[1]
        if end-start+1e-9<config['minimum_target_duration_s']:return
        if kind=='t_low_flat':peak=min(run,key=lambda p:max(p.get('t_positive_units',max(0.,p['t_amplitude_units'])),-p.get('t_negative_units',min(0.,p['t_amplitude_units']))))
        elif kind=='t_persistent_inversion':peak=min(run,key=lambda p:p.get('t_negative_units',p['t_amplitude_units']))
        elif kind=='t_biphasic':peak=max(run,key=lambda p:min(p.get('t_positive_units',0),-p.get('t_negative_units',0)))
        else:peak=max(run,key=lambda p:abs(p['t_amplitude_units']-p['t_reference_units']))
        label='T 波持续负向候选（导联背景待核对）' if kind=='t_persistent_inversion' and lead in T_VARIABLE_LEADS else labels[kind]
        result.append(_episode(run,lead,config,kind,label,peak,criteria=[kind]))
    for point in points:
        start,end=_support(point,config)
        if last_end is not None and abs(start-last_end)>1e-7:
            for kind in runs:finish(kind);runs[kind]=[]
        conditions=_t_conditions(point,lead,config) if end>start else set()
        for kind in runs:
            if kind in conditions:runs[kind].append(point)
            else:finish(kind);runs[kind]=[]
        last_end=end
    for kind in runs:finish(kind)
    return result


def _stable_reference(points,key,config,*,prefer=None):
    """A recorded stable interval, locked for the recording, never self-drifting.

    A compatible interval is preferred, but an observed stable reference is
    never advertised as clinically normal. Absence remains None, not zero.
    """
    minimum=config['stable_reference_minimum_s'];run=[];fallback=None;previous=None
    for point in points:
        start,end=_support(point,config)
        if (not point.get('eligible') or not _finite(point.get(key)) or point.get('axis_shift_suspected')
                or previous is not None and abs(start-previous)>1e-7):run=[]
        previous=end
        if not point.get('eligible') or not _finite(point.get(key)) or point.get('axis_shift_suspected'):continue
        run.append(point)
        # Keep a bounded trailing window; high rate cannot grow this list for
        # an entire day. A mean alone does not establish stable morphology.
        while len(run)>1 and end-_support(run[1],config)[0]>=minimum:run.pop(0)
        if end-_support(run[0],config)[0]+1e-9<minimum:continue
        if fallback is not None and prefer is not None and not prefer(point[key]):continue
        values=[p[key] for p in run];center=_median(values)
        tolerance=max(5.,config['entry_threshold_units']/2) if key=='st_level_units' else max(5.,config['t_inversion_minimum_units']/2) if key=='t_amplitude_units' else max(5.,abs(center)*.1)
        if _mad(values)>tolerance:continue
        source=dict(method='locked_stable_observed_interval_v1',start_s=_support(run[0],config)[0],end_s=end,
                    metric=key,value=round(center,2),normality_established=False,quality_verified_by_physician=False)
        if fallback is None:fallback=(round(center,2),source)
        if prefer is None or prefer(center):return round(center,2),source
    return fallback if fallback is not None else (None,None)


def _merge_episodes(items: list[dict]) -> list[dict]:
    # Never flatten support from another lead or across an unavailable interval.
    result=sorted(copy.deepcopy(items),key=lambda row:(row['start_s'],row['kind'],LEADS.index(row['leads'][0])))
    for index,item in enumerate(result,1):
        material=[ALGORITHM_VERSION,item['kind'],item['leads'],item['start_s'],item['end_s']]
        item['id'],item['lead_count']='auto-stt-'+sha256(repr(material).encode()).hexdigest()[:24],1
    return result


def minute_trends(points, duration_s, config):
    """Minute display and continuous-event evidence have separate eligibility.

    measured_* is finite only for a fully measurable metric across the minute,
    including observations carrying quality warnings. partial_* is a partial
    summary, never permission to connect a line across a true missing interval.
    """
    result=[];cursor=0
    keys=('st_level_units','reference_units','deviation_units','t_amplitude_units','t_reference_units',
          't_positive_units','t_negative_units','r_amplitude_units','noise_units','st_slope_units_per_s')
    for start in range(0,math.ceil(duration_s),60):
        end=min(duration_s,start+60);valid_covered=0.;sums={k:0. for k in keys};covered={k:0. for k in keys};reasons=set();flags=set();quality=[]
        while cursor<len(points) and _support(points[cursor],config)[1]<=start:cursor+=1
        j=cursor
        while j<len(points) and _support(points[j],config)[0]<end:
            point=points[j];a,b=_support(point,config);overlap=max(0.,min(end,b)-max(start,a))
            measurable=point.get('measurable',point.get('eligible',False))
            if measurable:
                for key in keys:
                    if _finite(point.get(key)):
                        sums[key]+=point[key]*overlap;covered[key]+=overlap
            if point.get('eligible') and all(_finite(point.get(k)) for k in ('st_level_units','t_amplitude_units')):
                valid_covered+=overlap;quality.append(point.get('quality_score',0))
            elif overlap:
                reasons.update(point.get('availability_reasons',[]) or ['quality_or_missing'])
            if point.get('axis_shift_suspected'):flags.add('axis_shift_suspected')
            flags.update(point.get('quality_flags',[]));j+=1
        if valid_covered+1e-7<end-start:reasons.add('incomplete_support')
        complete=valid_covered+1e-7>=end-start and not reasons
        row=dict(start_s=float(start),end_s=end,time_s=(start+end)/2,duration_s=end-start,
            eligible=complete,valid_duration_s=round(valid_covered,3),coverage_pct=round(valid_covered/(end-start)*100,2),
            quality_score=round(_median(quality),3),quality_reasons=sorted(reasons),quality_flags=sorted(flags|reasons),
            axis_shift_suspected='axis_shift_suspected' in flags,lead_availability='available' if complete else 'unavailable',quality_verified_by_physician=False,
            metric_coverage_pct={k:round(v/(end-start)*100,2) for k,v in covered.items()})
        for key in keys:
            mean=round(sums[key]/covered[key],2) if covered[key] else None
            full=covered[key]+1e-7>=end-start
            row[key]=mean if full else None;row['measured_'+key]=row[key];row['partial_'+key]=mean
        result.append(row)
    return result


def _screening_masks(intervals,total_samples):
    result=set()
    for row in intervals:
        if not isinstance(row,dict) or any(type(row.get(k)) is not int for k in ('start_sample','end_sample')):raise ValueError('ST-T节律排除须使用原始整数样本范围')
        start,end=row['start_sample'],row['end_sample'];reason=row.get('reason','stored_rhythm_exclusion')
        if not 0<=start<end<=total_samples or not isinstance(reason,str) or not reason or len(reason)>200:raise ValueError('ST-T节律排除范围无效')
        result.add((start,end,reason))
    return tuple(sorted(result))


@source_read
def analyze_stt(waveform_path: str | Path, records, duration_s: float | None = None, *, analysis_revision=None, config=None,excluded_intervals=(),project=None) -> dict:
    """Analyze a recording and return automatic review candidates and trends."""
    path, settings = Path(waveform_path), {**DEFAULT_CONFIG, **(config or {})}
    stat, normalized = require_waveform_file(path), _normalize_records(records)
    total_samples = stat.st_size // (CHANNEL_COUNT * 2)
    duration = min(float(duration_s or total_samples / SAMPLE_RATE), total_samples / SAMPLE_RATE)
    masks=_screening_masks(excluded_intervals,total_samples)
    # Revisions can be equal in separate workspaces. Bind every normalized
    # record, including middle edits, rather than only the count and endpoints.
    signature = (sha256(repr(normalized).encode("ascii")).hexdigest(), analysis_revision)
    from .source_identity import file_signature
    cache_key = (str(path.resolve()), file_signature(path), signature, duration, tuple(sorted(settings.items())),masks)
    if cache_key in _CACHE:
        _CACHE.move_to_end(cache_key)
        value = _CACHE[cache_key]
        return copy.deepcopy(project(value) if project is not None else value)
    block_samples = int(settings["block_seconds"] * SAMPLE_RATE)
    block_count=math.ceil(duration/settings['block_seconds']);masked_blocks=set()
    # The same source supports used for baseline/J/ST/T must be outside a saved
    # rhythm exclusion. A conservative full-block break prevents gap bridging.
    for start,end,_ in masks:
        masked_blocks.update(range(max(0,(start-120)//block_samples),min(block_count-1,(end+40-1)//block_samples)+1))
    by_block: dict[int, list[tuple[int, int, int]]] = {}
    for row in normalized:
        if 0 <= row[0] < total_samples:
            by_block.setdefault(row[0] // block_samples, []).append(row)
    blocks=[]
    next_anchors={row[0]:normalized[i+1][0] if i+1<len(normalized) else None for i,row in enumerate(normalized)}
    with path.open("rb") as stream,mmap.mmap(stream.fileno(),0,access=mmap.ACCESS_READ) as buffer:
        for block_index in range(block_count):
            rows=by_block.get(block_index,[]);usable=[]
            for index,row in enumerate(rows):
                sample,group,rr=row
                previous_group=rows[index-1][1] if index else None
                following_group=rows[index+1][1] if index+1<len(rows) else None
                if group==1 and previous_group not in {3,34} and following_group not in {3,34} and 350<=rr<=2000 and sample>=50 and sample+120<total_samples:
                    usable.append(row)
            selected=_evenly(usable,settings['maximum_beats_per_block'])
            all_count=sum(row[1]!=34 for row in rows)
            start=block_index*settings['block_seconds'];end=min(duration,start+settings['block_seconds'])
            base=dict(time_s=(start+end)/2,start_s=start,end_s=end,rows=rows,eligible=False,
                      quality_score=0.,j_offset_ms=None,landmark_confidence=0.,leads={},observations={},usable=usable,
                      normal_beat_count=len(usable),measurement_beat_count=len(usable),normal_beat_ratio=round(len(usable)/max(1,all_count),3))
            if block_index in masked_blocks:
                base['availability_reasons']=['explicit_measurement_exclusion'];blocks.append(base);continue
            if len(selected)<settings['minimum_normal_beats']:
                base['availability_reasons']=['insufficient_j_representatives'];blocks.append(base);continue
            measured=_block_measurement(buffer,selected,all_count,total_samples,settings,normal_count=len(usable),include_morphology=False)
            # J and engineering quality are estimated on the bounded 16s
            # representative set; event support uses every qualified real R.
            j=round(measured['j_offset_ms']*SAMPLE_RATE/1000)
            nexts=[next_anchors[r[0]] if next_anchors[r[0]] is not None else r[0] for r in usable]
            observations=_beat_measurements(buffer,usable,total_samples,settings,j_sample=j,next_samples=nexts)
            base.update(measured);base['measurement_beat_count']=len(usable);base['observations']=observations
            base['observation_index']={r[0]:i for i,r in enumerate(usable)}
            blocks.append(base)

    lead_points,episodes={},[]
    for column,lead in enumerate(LEADS):
        points=[]
        for block in blocks:
            measure=block['leads'].get(lead,{})
            observations=block['observations'];positions=block.get('observation_index',{})
            for row in block['rows']:
                sample,group,rr=row;next_sample=next_anchors[sample]
                if next_sample is None:continue  # no invented source-tail interval
                start,end=sample/SAMPLE_RATE,min(duration,next_sample/SAMPLE_RATE)
                if start>=duration or end<=start:continue
                index=positions.get(sample)
                observed=index is not None and bool(observations) and measure.get('measurable',False)
                source_fault=None
                if observed:
                    if lead in ('III','aVR','aVL','aVF'):
                        projection_available=bool(observations['qrs'][index,0]>0 and observations['qrs'][index,1]>0)
                    else:projection_available=bool(observations['qrs'][index,column]>0)
                    clipped=bool(observations['source_clipped'][index,column]) if lead in ('I','II','V1','V2','V3','V4','V5','V6') else bool(observations['source_clipped'][index,0] or observations['source_clipped'][index,1])
                    source_fault='flatline' if not projection_available else 'source_clipping' if clipped else None
                    observed=observed and source_fault is None
                # 350 milliseconds, not samples. At 200Hz a qualified interval
                # has 70..400 samples; any real longer gap breaks the evidence.
                interval_ok=70<=next_sample-sample<=400
                flags=[]
                if not block['eligible']:flags.append('engineering_block_quality')
                if measure and not measure.get('eligible'):flags.append('lead_engineering_quality')
                if not interval_ok:flags.append('rr_support_gap')
                p=dict(time_s=start,start_s=start,end_s=end,boundary_resolution_s=(next_sample-sample)/SAMPLE_RATE,
                    source_sample=sample,next_source_sample=next_sample,measurable=observed,
                    eligible=observed and interval_ok and block['eligible'] and measure.get('eligible',False),
                    quality_score=measure.get('quality_score',0),quality_flags=flags,
                    availability_reasons=block.get('availability_reasons',measure.get('availability_reasons',[]) or (['beat_not_qualified'] if not observed else [])),
                    j_offset_ms=block['j_offset_ms'],landmark_confidence=block['landmark_confidence'],
                    t_polarity_context=t_polarity_context(lead))
                if source_fault:p['availability_reasons']=[source_fault]
                mappings={'st_level_units':'st','t_amplitude_units':'t','t_positive_units':'t_positive','t_negative_units':'t_negative',
                          'qrs_amplitude_units':'qrs','r_amplitude_units':'r','noise_units':'noise','st_slope_units_per_s':'st_slope'}
                for key,source in mappings.items():
                    value=float(observations[source][index,column]) if observed else None
                    p[key]=round(value,3) if _finite(value) else None
                p['t_measurable']=bool(observed and observations['t_shape_measurable'][index,column])
                if observed and not p['t_measurable']:p['quality_flags'].append('t_window_overlap_or_unavailable')
                # Real missing/unmeasurable observations remain null. A low
                # quality measured value is preserved independently of eligibility.
                if not observed:
                    p['st_level_units']=p['t_amplitude_units']=None
                points.append(p)
        qrs_ref,qrs_source=_stable_reference(points,'qrs_amplitude_units',settings)
        for point in points:
            qrs=point.get('qrs_amplitude_units')
            change=abs(qrs-qrs_ref)/max(abs(qrs_ref),1.) if _finite(qrs) and _finite(qrs_ref) else None
            point['qrs_change_fraction']=round(change,3) if change is not None else None
            point['axis_shift_suspected']=bool(change is not None and change>=settings['axis_shift_qrs_fraction'])
        st_ref,st_source=_stable_reference(points,'st_level_units',settings,prefer=lambda v:abs(v)<settings['entry_threshold_units'])
        t_ref,t_source=_stable_reference(points,'t_amplitude_units',settings,prefer=lambda v:v>=settings['t_inversion_minimum_units'] if lead in T_UPRIGHT_LEADS else True)
        for point in points:
            point['reference_units']=st_ref;point['t_reference_units']=t_ref
            point['reference_source']=dict(st=st_source,t=t_source,qrs=qrs_source)
            point['deviation_units']=round(point['st_level_units']-st_ref,3) if _finite(point.get('st_level_units')) and _finite(st_ref) else None
        episodes.extend(_lead_episodes(points,lead,settings));episodes.extend(_t_episodes(points,lead,settings))
        lead_points[lead]=minute_trends(points,duration,settings)

    candidates = _merge_episodes(episodes)
    eligible_blocks = sum(block["eligible"] for block in blocks)
    result = {
        "algorithm_version": ALGORITHM_VERSION, "analysis_revision": analysis_revision, "status": "completed", "rhythm_policy":RHYTHM_POLICY,
        "sample_rate_hz": SAMPLE_RATE, "units": "source_device_units", "unit_label": "设备原始单位",
        "calibration_status": "unverified", "parameters": copy.deepcopy(settings),
        "quality": {"total_blocks": len(blocks), "eligible_blocks": eligible_blocks,
                    "coverage_pct": round(eligible_blocks * 100 / max(1, len(blocks)), 1),
                    "analyzed_duration_s": round(min(duration, len(blocks) * settings["block_seconds"]), 1),
                    "excluded_blocks": len(blocks) - eligible_blocks,
                    "gate": "source beat qualification, actual neighbouring R support and per-lead measurability; AF/AFL annotations never mask data; suspicious measured values retained separately; J and axis flags require physician review"},
        "exclusions":dict(intervals=[dict(start_sample=a,end_sample=b,reason=r) for a,b,r in masks],support_halo_samples=[-40,120],
            rule='explicit_quality_support_intersection_breaks_measurement_and_continuity',rhythm_policy=RHYTHM_POLICY),
        "summary": {"candidate_count": len(candidates),
                    "st_depression_count": sum(item["kind"] == "st_depression" for item in candidates),
                    "st_elevation_count": sum(item["kind"] == "st_elevation" for item in candidates),
                    "t_wave_count": sum(item["kind"].startswith("t_") for item in candidates),
                    "by_kind":{kind:sum(item["kind"]==kind for item in candidates) for kind in sorted({item["kind"] for item in candidates})}},
        "candidates": candidates, "trends": {"block_seconds": 60, "measurement_block_seconds":settings["block_seconds"], "aggregation":"per_beat_duration_weighted_minute_separate_measurability_quality", "leads": lead_points},
    }
    _CACHE[cache_key] = copy.deepcopy(result); _CACHE.move_to_end(cache_key)
    while len(_CACHE) > _CACHE_LIMIT:
        _CACHE.popitem(last=False)
    return copy.deepcopy(project(result)) if project is not None else result


def build_stt_review(conclusion: str, waveform_path=None, records=None, duration_s=None, *, analysis_revision=None, config=None,excluded_intervals=()) -> dict:
    """Build the ST-T workbench contract with optional automatic analysis."""
    analysis = None
    if waveform_path is not None and records is not None:
        analysis = analyze_stt(waveform_path, records, duration_s, analysis_revision=analysis_revision, config=config,excluded_intervals=excluded_intervals)
    automatic = {
        "enabled": analysis is not None, "algorithm_version": ALGORITHM_VERSION,
        "role": "screening_candidates_only", "review_status": "pending_physician_review",
        "items": analysis["candidates"] if analysis else [],
        "summary": analysis["summary"] if analysis else {"candidate_count": 0, "st_depression_count": 0, "st_elevation_count": 0, "t_wave_count": 0},
        "quality": analysis["quality"] if analysis else None,
        "reason_code": None if analysis else "waveform_not_supplied",
        "reasons": [] if analysis else ["未向筛查引擎提供原始波形与心搏定位数据"],
    }
    from .evaluation_status import stt_status
    automatic["evaluation"] = stt_status(automatic)
    return {
        "schema_version": "stt-screening-review-v2",
        "review_mode": "automatic_screening_with_physician_review" if analysis else "manual_review_only",
        "manual_review_only": analysis is None, "calibration_unverified": True,
        "measurement_protocol": {
            "default_measurement": "J+60 ms", "default_landmark": "ST60",
            "baseline": {"preferred": "PR_segment", "implemented_surrogate": "pre-QRS stable baseline (-200 to -120 ms)",
                         "fallback": "individual_stable_baseline", "label": "PR 段优先 / QRS 前稳定基线替代",
                         "requires_manual_confirmation": True,
                         "note": "医师需核对 P/QRS/T 分界、体位变化、伪差、传导异常及心率变化。"},
            "landmarks": [
                {"code": "J", "offset_from_j_ms": 0, "label": "J 点", "purpose": "多导联导数能量估计 QRS 终点，需人工确认"},
                {"code": "ST60", "offset_from_j_ms": 60, "label": "J+60 ms", "purpose": "默认 ST 筛查点"},
                {"code": "ST80", "offset_from_j_ms": 80, "label": "J+80 ms", "purpose": "人工备选复核点"},
            ],
            "case_amplitude_output": {"enabled": analysis is not None, "unit": "source_device_units", "mV_conversion_enabled": False,
                                      "reason": "仅显示设备原始尺度相对值；计量溯源前禁止解释为临床 mV 阈值。"},
        },
        "lead_system": {"status": "mapping_from_source_channels_unverified", "mapping_verified": False,
                        "electrode_placement_verified": False,
                        "message": "12 导联由 8 个源通道按现有映射派生；电极位置与导联映射尚需独立核验。"},
        "calibration": {"status": "unverified", "voltage_gain_verified": False, "filter_response_verified_for_st": False,
                        "analysis_filter": "raw source samples; block median; no 0.5 Hz display high-pass",
                        "message": "已开启自动筛查候选；幅值仅以设备原始单位表示，不直接换算 mV。"},
        "automatic_candidates": automatic, "analysis": analysis,
        "reference_thresholds": {
            "enabled": analysis is not None, "reference_only": True, "applied_as_research_screen": analysis is not None,
            "applied_to_case": analysis is not None,
            "title": "动态 ST-T 研究筛查协议（非诊断阈值）",
            "st_change": {"entry_units": DEFAULT_CONFIG["entry_threshold_units"],
                          "target_units": DEFAULT_CONFIG["target_threshold_units"], "measurement_landmark": "ST60",
                          "minimum_target_duration_s": DEFAULT_CONFIG["minimum_target_duration_s"],
                          "exit_confirmation_s": DEFAULT_CONFIG["exit_confirmation_s"]},
            "warning": "阈值应用于未溯源的设备原始尺度，只用于排列复核优先级，不得自动生成诊断。",
        },
        "source_report": extract_stt_source_report(conclusion),
        "clinical_safety": {"diagnosis_generated": False, "automatic_interpretation_generated": analysis is not None,
                            "requires_physician_review": True, "acute_care_rule_out_supported": False,
                            "statement": "软件仅生成 ST-T 自动筛查候选，医师必须回看原始波形、修正或排除后才可进入报告。"},
    }
