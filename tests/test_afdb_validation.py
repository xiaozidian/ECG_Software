"""Independent evaluation bookkeeping, not AF detector accuracy assertions."""
import pytest

from scripts.validate_afdb import adapt, aggregate, metrics, rhythm_segments, score, screen, TIME_KEYS


def window(start,end,evaluated=True,candidate=False):
    return dict(start_s=start,end_s=end,evaluated=evaluated,candidate=candidate)


def test_250hz_adapter_uses_timestamp_only_and_explicit_untyped_n():
    rows,error=adapt([1,202,399],['N']*3,500,250)
    assert [r['sample_index'] for r in rows]==[1,162,319]
    assert [r['rr_ms'] for r in rows]==[0,805,785]
    assert error==2 and all(r['class_code']=='N' for r in rows)


@pytest.mark.parametrize('samples,symbols,fs',[
    ([0,1],['N','N'],200),([0,1],['N'],250),([0,1],['N','V'],250),
    ([2,1],['N','N'],250),([2,3],['N','N'],250),([-1],['N'],250),([500],['N'],250)])
def test_adapter_rejects_unsupported_or_non_monotonic_inputs(samples,symbols,fs):
    with pytest.raises(ValueError):adapt(samples,symbols,500,fs)


def test_reference_unknown_prefix_and_true_half_open_boundaries():
    result=rhythm_segments([250,500,750],['(N','(AFIB','(AFL'],1000,250)
    assert result==[
        dict(start_s=0,end_s=1,rhythm='unknown'),dict(start_s=1,end_s=2,rhythm='N'),
        dict(start_s=2,end_s=3,rhythm='AFIB'),dict(start_s=3,end_s=4,rhythm='AFL')]


@pytest.mark.parametrize('samples,labels',[
    ([0],['(SINUS']),([300,200],['(N','(AFIB']),([-1],['(N']),([1000],['(N'])])
def test_invalid_reference_stops_rather_than_becoming_normal(samples,labels):
    with pytest.raises(ValueError):rhythm_segments(samples,labels,1000,250)


def test_mixed_windows_score_exact_seconds_and_do_not_drop_withheld_af():
    refs=rhythm_segments([0,2500,10000,17500,20000],['(N','(AFIB','(AFL','(AFIB','(J'],22500,250)
    result=score([window(0,30,True,True),window(30,60),window(60,90,False)],refs)
    assert result['seconds']==dict(tp_s=20,fn_s=10,fp_s=10,tn_s=20,
                                   withheld_af_s=10,withheld_non_af_s=20,unknown_s=0)
    assert result['metrics']['conditional_sensitivity']==pytest.approx(2/3)
    assert result['metrics']['all_af_candidate_capture']==.5
    assert result['metrics']['evaluated_coverage']==pytest.approx(2/3)
    assert result['by_rhythm']['AFL']==dict(candidate_s=0,negative_s=20,withheld_s=10)
    assert result['windows']=={'mixed_unknown_or_partial':3}


def test_unknown_reference_and_zero_denominators_are_not_true_negatives():
    result=score([window(0,30,True,True)],rhythm_segments([],[],7500,250))
    assert result['seconds']['unknown_s']==30
    assert result['metrics']['known_reference_s']==0
    assert result['metrics']['conditional_sensitivity'] is None
    assert result['metrics']['conditional_specificity'] is None


def test_pure_window_counts_keep_rhythm_and_abstention_separate():
    result=score([window(0,30,False),window(30,60,True,True),window(60,65,False)],
                 rhythm_segments([0,7500],['(AFIB','(AFL'],16250,250))
    assert result['windows']=={'AFIB:withheld':1,'AFL:candidate':1,'mixed_unknown_or_partial':1}
    assert result['metrics']['all_af_candidate_capture']==0
    assert result['metrics']['conditional_sensitivity'] is None


def test_aggregate_weights_seconds_and_keeps_macro_denominators():
    af=score([window(0,30,True,True)],rhythm_segments([0],['(AFIB'],7500,250))
    n=score([window(0,60)],rhythm_segments([0],['(N'],15000,250))
    result=aggregate([af,n])
    assert result['metrics']['reference_af_burden']==pytest.approx(1/3)
    assert result['record_macro']['conditional_sensitivity']==dict(value=1,records=1)
    assert result['record_macro']['conditional_specificity']==dict(value=1,records=1)
    assert sum(result['seconds'][k] for k in TIME_KEYS)==90


def test_subprocess_runs_actual_shipped_screen_without_reference_labels():
    rows,_=adapt(list(range(0,7500,200)),['N']*38,7500,250)
    result=screen(rows,30)
    assert result['evaluated_windows']==1
    assert result['episodes']==[] and result['windows'][0]['candidate'] is False


def test_independent_dense_native_audit_matches_fractional_boundaries():
    from scripts.audit_afdb_scoring import native_seconds
    windows=[window(0,30,True,True),window(30,60),window(60,61.012,False)]
    samples=[2,3101,9257,15001];labels=['(N','(AFIB','(AFL','(AFIB']
    expected=score(windows,rhythm_segments(samples,labels,15253,250))['seconds']
    actual=native_seconds(15253,samples,labels,windows)
    assert actual==pytest.approx(expected,abs=1e-8)


@pytest.mark.parametrize('windows',[[window(0,20)],[window(0,20),window(19,30)]])
def test_independent_audit_rejects_missing_or_overlapping_windows(windows):
    from scripts.audit_afdb_scoring import native_seconds
    with pytest.raises(ValueError):native_seconds(7500,[0],['(N'],windows)
