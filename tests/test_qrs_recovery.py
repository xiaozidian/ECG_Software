"""Independent finite matching oracle and leakage-free input geometry."""
from functools import lru_cache
import random

import pytest

from scripts.audit_qrs_recovery import positions, match_positions, match_summary, chunks, detected_rows


@pytest.mark.parametrize('seed', range(16))
def test_greedy_match_count_equals_exhaustive_oracle(seed):
    rng = random.Random(seed)
    for _ in range(25):
        ref = sorted(rng.sample(range(30),rng.randrange(7)))
        det = sorted(rng.sample(range(30),rng.randrange(7)))
        tolerance = rng.randrange(6)
        @lru_cache(None)
        def oracle(i,j):
            if i == len(ref) or j == len(det):return 0
            best = max(oracle(i+1,j),oracle(i,j+1))
            if abs(ref[i]-det[j]) <= tolerance:best=max(best,1+oracle(i+1,j+1))
            return best
        result = match_positions(ref,det,30,tolerance)
        assert len(result) == oracle(0,0)
        assert len({r for r,d in result}) == len({d for r,d in result}) == len(result)
        assert all(abs(r-d)<=tolerance for r,d in result)


@pytest.mark.parametrize('values', [[-1],[30],[0,0],[1,0],[True],[1.5],
    [float('nan')],[float('inf')],[float('-inf')],['1'],[None]])
def test_invalid_positions_are_not_repaired(values):
    with pytest.raises(ValueError):positions(values,30)


@pytest.mark.parametrize('length', [False,0,-1,1.5,float('inf')])
def test_invalid_record_length_is_rejected_even_without_peaks(length):
    with pytest.raises(ValueError):positions([],length)


def test_native_numpy_positions_remain_exact_and_boolean_is_rejected():
    import numpy as np
    assert positions(np.array([0,128,257],dtype=np.int64),np.int64(258)) == [0,128,257]
    with pytest.raises(ValueError):positions([np.bool_(True)],30)


def test_source_snapshot_is_available_before_analysis_and_verifies_copied_bytes(tmp_path,monkeypatch):
    import scripts.audit_qrs_recovery as audit
    source=tmp_path/'source';source.mkdir()
    (source/'algorithm.js').write_text('original')
    monkeypatch.setattr(audit.base,'ROOT',source)
    hashes={'algorithm.js':audit.base.digest(source/'algorithm.js')}
    output=tmp_path/'run'
    audit.snapshot_sources(output,hashes)
    assert (output/'snapshot/algorithm.js').read_text() == 'original'
    assert not (output/'summary.json').exists()
    original_copy=audit.shutil.copy2
    def corrupt(src,dst):
        original_copy(src,dst)
        dst.write_text('corrupt copy')
    monkeypatch.setattr(audit.shutil,'copy2',corrupt)
    with pytest.raises(ValueError,match='Source changed before audit'):
        audit.snapshot_sources(tmp_path/'failed',hashes)


@pytest.mark.parametrize('tolerance', [-1,False,1.2])
def test_invalid_matching_tolerance(tolerance):
    with pytest.raises(ValueError):match_positions([],[],30,tolerance)


def test_tolerance_edge_and_global_matching_across_core_boundary():
    ref, det = [100,200,300], [112,212,313]
    pairs = match_positions(ref,det,400,12)
    assert pairs == [(100,112),(200,212)]
    whole = match_summary(ref,det,pairs,0,400)
    assert whole['fp'] == whole['fn'] == 1
    left=match_summary(ref,det,pairs,0,110)
    right=match_summary(ref,det,pairs,110,400)
    assert left['matched_reference']==1 and left['matched_detection']==0
    assert left['ppv'] is None
    assert right['matched_reference']==1 and right['matched_detection']==2
    for key in ('reference_beats','detected_beats','matched_reference','matched_detection','fn','fp'):
        assert left[key]+right[key] == whole[key]


@pytest.mark.parametrize('length', [1,9,10,11,21])
def test_core_partition_covers_each_sample_once_without_context_leakage(length):
    parts = chunks(length,core=10,pad=3)
    assert [s for a,b,lo,hi in parts for s in range(a,b)] == list(range(length))
    assert all(0<=lo<=a<b<=hi<=length for a,b,lo,hi in parts)
    assert parts[0][2]==0 and parts[-1][3]==length


def test_no_reference_is_used_to_fill_missing_signal_or_assign_beat_type():
    rows, details = detected_rows([0,128,256,640,768],[(256,640)],1024)
    assert [r['sample_index'] for r in rows] == [0,200,400,1000,1200]
    assert [r['class_code'] for r in rows] == ['N']*5  # Explicit research proxy.
    assert [r['rr_valid'] for r in rows] == [False,True,False,False,False]
    assert details['barriers']==2


def test_detector_chunk_is_reference_blind_and_keeps_core_only(monkeypatch):
    import sys
    from types import SimpleNamespace
    import numpy as np
    import scripts.audit_qrs_recovery as audit
    calls=[]
    def read(path,sampfrom,sampto,physical):
        assert physical
        return SimpleNamespace(p_signal=np.zeros((sampto-sampfrom,2)))
    def detect(signal,fs,learn,verbose):
        calls.append((len(signal),fs,learn,verbose))
        return np.arange(len(signal),dtype=int)
    monkeypatch.setitem(sys.modules,'wfdb',SimpleNamespace(rdrecord=read))
    monkeypatch.setitem(sys.modules,'wfdb.processing',SimpleNamespace(xqrs_detect=detect))
    monkeypatch.setattr(audit,'chunks',lambda length:chunks(length,10,3))
    result=audit.detect_record(__import__('pathlib').Path('/unused'),'synthetic',SimpleNamespace(sig_len=21))
    assert len(calls)==6 and all(c[1:]==(128,True,False) for c in calls)
    assert result[0]['samples']==result[1]['samples']==list(range(21))


def test_nonfinite_chunk_withheld_not_interpolated(monkeypatch):
    import sys
    from types import SimpleNamespace
    import numpy as np
    import scripts.audit_qrs_recovery as audit
    def read(*args,**kwargs):
        signal=np.zeros((10,2));signal[0,0]=np.nan
        return SimpleNamespace(p_signal=signal)
    def detect(signal,**kwargs):
        assert np.isfinite(signal).all()
        return [2,6]
    monkeypatch.setitem(sys.modules,'wfdb',SimpleNamespace(rdrecord=read))
    monkeypatch.setitem(sys.modules,'wfdb.processing',SimpleNamespace(xqrs_detect=detect))
    result=audit.detect_record(__import__('pathlib').Path('/unused'),'synthetic',SimpleNamespace(sig_len=10))
    assert result[0]['samples']==[] and result[0]['gaps']==[(0,10)]
    assert result[0]['chunks'][0]['status']=='withheld_nonfinite'
    assert result[1]['samples']==[2,6] and result[1]['gaps']==[]


@pytest.mark.parametrize('fail_scoring', [False,True])
def test_evaluation_preserves_reference_blind_checkpoint_and_only_marks_success_at_end(tmp_path,monkeypatch,fail_scoring):
    import gzip
    import json
    import sys
    from types import SimpleNamespace
    import scripts.audit_qrs_recovery as audit
    folder=tmp_path/'inputs';folder.mkdir()
    output=tmp_path/'results'
    catalog={}
    for record in audit.RECORDS:
        for ext in ('hea','dat','qrs','atr'):
            name=record+'.'+ext
            (folder/name).write_text('synthetic fixture '+name)
            catalog[name]=audit.base.digest(folder/name)
    (folder/'SHA256SUMS.txt').write_text(''.join(f'{v}  {k}\n' for k,v in catalog.items()))
    samples=list(range(128,128*120,128))
    reference_read=set()
    def detect(folder,record,header):
        assert record not in reference_read
        assert (output/'inputs.json').exists()
        assert (output/'snapshot/scripts/audit_qrs_recovery.py').exists()
        return [dict(samples=samples,gaps=[],chunks=[]) for _ in range(2)]
    def annotations(path,extension):
        record=path.rsplit('/',1)[-1]
        # Both reference and original-QRS reads must follow saved detection.
        with gzip.open(output/f'{record}-detection.json.gz','rt') as stream:
            assert json.load(stream)[0]['samples']==samples
        if extension=='atr':
            reference_read.add(record)
            return SimpleNamespace(sample=[0]+samples,symbol=['+']+['N']*len(samples),aux_note=['(N']+['']*len(samples))
        return SimpleNamespace(sample=samples,symbol=['N']*len(samples),aux_note=['']*len(samples))
    monkeypatch.setitem(sys.modules,'wfdb',SimpleNamespace(__version__='4.3.1',
        rdheader=lambda _:SimpleNamespace(fs=128,n_sig=2,units=['mV','mV'],sig_len=128*120),
        rdann=annotations))
    # Detector is stubbed here: no SciPy computation occurs. Actual XQRS is
    # evaluated only in the separate version-pinned public-data environment.
    monkeypatch.setitem(sys.modules,'scipy',SimpleNamespace(__version__='synthetic-test-stub'))
    monkeypatch.setattr(audit,'detect_record',detect)
    if fail_scoring:
        def fail(*args,**kwargs):raise RuntimeError('injected downstream failure')
        monkeypatch.setattr(audit.base,'screen',fail)
        with pytest.raises(RuntimeError,match='injected downstream failure'):
            audit.evaluate(folder,output)
        assert not (output/'summary.json').exists()
        assert (output/'00-detection.json.gz').exists()
        assert (output/'inputs.json').exists()
        return
    audit.evaluate(folder,output)
    summary=json.loads((output/'summary.json').read_text())
    assert len(summary['results'])==9
    assert summary['input_sha256']==catalog
    for result in summary['results']:
        assert result['qrs_match']['12']['fp']==result['qrs_match']['12']['fn']==0
        assert sum(result['af_seconds'].values())==120
        assert result['af_events']['all']['events']==0
    for name,checksum in summary['source_sha256'].items():
        assert audit.base.digest(output/'snapshot'/name)==checksum
    with pytest.raises(FileExistsError):audit.evaluate(folder,output)
