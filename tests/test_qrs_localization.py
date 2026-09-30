"""Reference-blind peak correction against a direct local-mean oracle."""
import sys
from types import SimpleNamespace

import numpy as np
import pytest

from scripts import audit_qrs_localization as audit


def oracle(signal, peaks, radius, window):
    half = window//2
    residual = [abs(float(v)-sum(signal[max(0,i-half):i+half+1])/len(signal[max(0,i-half):i+half+1]))
                for i,v in enumerate(signal)]
    result = []
    for i,p in enumerate(peaks):
        allowed = [s for s in range(len(signal)) if abs(s-p)<=radius
                   and (i==0 or s>(peaks[i-1]+p)//2)
                   and (i==len(peaks)-1 or s<=(p+peaks[i+1])//2)]
        result.append(min(allowed,key=lambda s:(-residual[s],abs(s-p),s)))
    return result


@pytest.mark.parametrize('seed',range(16))
def test_matches_direct_mean_oracle_and_preserves_identity(seed):
    rng=np.random.default_rng(seed)
    for _ in range(20):
        length=int(rng.integers(1,200))
        signal=rng.integers(-100,101,length).astype(float)
        peaks=sorted(rng.choice(length,size=int(rng.integers(0,length+1)),replace=False).tolist())
        radius=int(rng.integers(0,20));window=int(rng.integers(0,15))*2+1
        result=audit.correct_peaks(signal,peaks,radius,window)
        assert result==oracle(signal,peaks,radius,window)
        assert len(result)==len(peaks)==len(set(result))
        assert result==sorted(result)
        assert all(abs(a-b)<=radius for a,b in zip(result,peaks))
        assert audit.correct_peaks(-signal,peaks,radius,window)==result


@pytest.mark.parametrize('signal', [[], [[1]], [0,np.nan], [np.inf], [-np.inf]])
def test_reject_nonfinite_or_malformed_input(signal):
    with pytest.raises(ValueError,match='Signal'):audit.correct_peaks(signal,[])


@pytest.mark.parametrize('radius,window', [(-1,19),(True,19),(1.1,19),(13,0),(13,2),(13,True),(13,1.5)])
def test_invalid_geometry(radius,window):
    with pytest.raises(ValueError,match='geometry'):audit.correct_peaks([0,1],[],radius,window)


@pytest.mark.parametrize('peaks', [[1,1],[2,1],[-1],[3],[False],[1.5]])
def test_does_not_silently_repair_bad_detection_input(peaks):
    with pytest.raises(ValueError):audit.correct_peaks([0,1,0],peaks)


def test_record_ends_inclusive_radius_and_short_constant_signal():
    x=np.zeros(100);x[0]=10;x[-1]=-10
    assert audit.correct_peaks(x,[13,86])==[0,99]
    for length in (1,2,18,19,20):
        assert audit.correct_peaks(np.full(length,17.),range(length))==list(range(length))
    assert audit.correct_peaks([100.],[0])==[0]


def test_ties_nearest_then_earlier_and_midpoint_owned_by_previous():
    x=np.zeros(101);x[40]=10;x[60]=-10
    assert audit.correct_peaks(x,[50])==[40]
    assert audit.correct_peaks(x,[51])==[60]
    x[:]=0;x[50]=100
    result=audit.correct_peaks(x,[49,51])
    assert result[0]==50 and result[1]>50
    assert len(result)==2


def test_offset_and_gain_do_not_change_positions():
    x=np.zeros(200);x[[25,75,125,175]]=[1,-2,3,-4]
    peaks=[30,70,130,170]
    assert audit.correct_peaks(x,peaks)==[25,75,125,175]
    assert audit.correct_peaks(3*x+7,peaks)==[25,75,125,175]


def test_overflow_refused_without_losing_or_synthesizing_beats():
    with pytest.raises(ValueError,match='residual'):
        audit.correct_peaks(np.full(30,1e308),[10])


def mock_wave_reader(monkeypatch,signal):
    calls=[]
    def rdrecord(path,*,sampfrom,sampto,physical):
        assert physical is True
        calls.append((sampfrom,sampto))
        return SimpleNamespace(p_signal=signal[sampfrom:sampto])
    monkeypatch.setitem(sys.modules,'wfdb',SimpleNamespace(rdrecord=rdrecord))
    return calls


def channels(peaks,gaps=None):
    return [dict(samples=list(peaks),gaps=gaps or [],chunks=[dict(detected_beats=len(peaks))]) for _ in (0,1)]


def test_chunk_ownership_uses_original_peak_not_shifted_peak(tmp_path,monkeypatch):
    x=np.zeros(150);x[[2,38,102,148]]=[1,-2,3,-4]
    peaks=[1,42,98,149]
    calls=mock_wave_reader(monkeypatch,np.column_stack((x,-x)))
    chunks=audit.qrs.chunks
    monkeypatch.setattr(audit.qrs,'chunks',lambda n:chunks(n,core=40,pad=25))
    result=audit.correct_record(tmp_path,'test',SimpleNamespace(sig_len=len(x)),channels(peaks))
    expected=oracle(x,peaks,13,19)
    for c in result:
        assert c['samples']==expected==[2,38,102,148]
        assert [b['beats'] for b in c['chunks']]==[1,1,1,1]
        assert sum(b['beats'] for b in c['chunks'])==len(peaks)
    assert calls==[(0,65),(15,105),(55,145),(95,150)]


def test_inconsistent_nonfinite_input_fails_without_reference_read(tmp_path,monkeypatch):
    x=np.zeros((100,2));x[30,0]=np.nan
    mock_wave_reader(monkeypatch,x)
    with pytest.raises(ValueError,match='conflicts'):
        audit.correct_record(tmp_path,'test',SimpleNamespace(sig_len=100),channels([25]))


def test_existing_nonfinite_gap_is_preserved_not_bridged(tmp_path,monkeypatch):
    x=np.zeros((100,2));x[30,:]=np.nan
    mock_wave_reader(monkeypatch,x)
    result=audit.correct_record(tmp_path,'test',SimpleNamespace(sig_len=100),channels([],[[0,100]]))
    for c in result:
        assert c['gaps']==[[0,100]] and c['samples']==[]
        assert c['chunks'][0]['status']=='withheld_nonfinite'


def test_saved_counts_and_file_changes_are_rejected(tmp_path,monkeypatch):
    cs=channels([20]);cs[0]['chunks'][0]['detected_beats']=2
    with pytest.raises(ValueError,match='counts'):
        audit.correct_record(tmp_path,'test',SimpleNamespace(sig_len=100),cs)
    f=tmp_path/'evidence';f.write_text('old')
    hashes={'evidence':audit.qrs.base.digest(f)}
    audit.check_hashes(tmp_path,hashes)
    f.write_text('new')
    with pytest.raises(ValueError,match='Changed'):audit.check_hashes(tmp_path,hashes)


def test_displacement_count_conservation_and_edges():
    assert audit.displacement([0,20,50],[0,33,37])==dict(beats=3,unchanged=1,
        at_radius=2,histogram_samples={-13:1,0:1,13:1},max_absolute_samples=13)
    with pytest.raises(ValueError):audit.displacement([0],[])
