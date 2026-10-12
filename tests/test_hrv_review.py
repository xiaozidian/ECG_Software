"""Pure mathematical HRV ranges and isolated SQLite review fixtures, no cases."""
import copy
import sqlite3
from types import SimpleNamespace

import pytest

from ecg_core.beat_editor import DEFAULT_SETTINGS
from ecg_core.hrv_analysis import analyze_hrv, analyze_hrv_review
from ecg_core.hrv_review import HrvReviewStore, blank_document, normalize_document, WINDOW_SAMPLES
from ecg_core.review_workflow import ReportConflict


def feed(values, duration=None, excluded=(), start_sample=0):
    rows = [dict(id='b0', sample_index=start_sample, rr_ms=0, class_code='N', hr=0)]
    sample = start_sample
    for i,value in enumerate(values,1):
        sample += round(value/5)
        rows.append(dict(id=f'b{i}', sample_index=sample, rr_ms=value, class_code='N', hr=60000/value))
    return SimpleNamespace(beats=rows, duration=duration if duration is not None else sample/200,
                           document={'settings':dict(DEFAULT_SETTINGS)}, excluded_rhythm_intervals=excluded)


def exclude(a,b,ident='x',reason='数学夹具排除'):
    return dict(id=ident,start_sample=a,end_sample=b,reason=reason)


def test_empty_exclusions_keep_all_legacy_fields_and_unqualified_time_population():
    value = feed([1000]*50,duration=350)
    previous = copy.deepcopy(value.__dict__)
    legacy = analyze_hrv(value,'2026-01-01T08:54:00+08:00')
    result = analyze_hrv_review(value,'2026-01-01T08:54:00+08:00')
    assert result['baseline'] == result['reviewed'] == legacy
    assert result['reviewed']['periods']['full']['nn_count'] == 50
    assert result['reviewed']['periods']['full']['five_minute_blocks'] == 0
    assert len(result['blocks']) == 2
    assert result['blocks'][0]['reviewed']['qualification_reasons'] == ['nn_coverage_below_240s']
    assert result['blocks'][1]['duration_s'] == 50
    assert 'incomplete_300s_block' in result['blocks'][1]['reviewed']['qualification_reasons']
    assert value.__dict__ == previous
    assert result['profile']['eligibility_standard'].startswith('existing engineering')
    assert result['profile']['quality_status'] == 'unknown'


def test_exact_50ms_is_not_counted_and_denominator_remains_consecutive_differences():
    equal = analyze_hrv_review(feed([800,850,900]),None)
    assert equal['reviewed']['periods']['full']['pnn50_pct'] == 0
    assert equal['blocks'][0]['reviewed']['nn50_count'] == 0
    alternating = analyze_hrv_review(feed([800,900,800,900]),None)
    row = alternating['blocks'][0]['reviewed']
    assert row['nn50_count'] == 3
    assert row['consecutive_difference_count'] == 3
    assert row['pnn50_pct'] == 100
    assert row['rmssd_ms'] == 100
    assert row['sdann_ms'] is None
    assert alternating['profile']['pnn50'] == dict(threshold_ms=50,comparison='strictly_greater',denominator='eligible consecutive NN differences',unit='percent')


def test_exclusion_removes_intersecting_whole_nn_without_rejoining_neighbors():
    value = feed([800,800,1000,1200,1200],duration=10)
    result = analyze_hrv_review(value,None,exclusions=[exclude(320,520)])
    row = result['blocks'][0]['reviewed']
    assert row['nn_count'] == 4
    assert row['consecutive_difference_count'] == 2
    assert row['rmssd_ms'] == 0
    assert row['pnn50_pct'] == 0
    assert result['reviewed']['periods']['full']['rmssd_ms'] == 0
    assert result['baseline']['periods']['full']['nn_count'] == 5
    assert value.beats[3]['class_code'] == 'N'


def test_half_open_edges_and_overlap_union_coverage():
    value = feed([1000]*300,duration=300)
    result = analyze_hrv_review(value,None,exclusions=[exclude(200,400,'a'),exclude(300,500,'b')])
    assert result['coverage']['excluded_s'] == 1.5
    assert result['coverage']['retained_s'] == 298.5
    assert result['reviewed']['periods']['full']['nn_count'] == 298
    # Ending at exclusion start and beginning at exclusion end are retained.
    assert result['blocks'][0]['reviewed']['consecutive_difference_count'] == 296
    restored_one = analyze_hrv_review(value,None,exclusions=[exclude(300,500,'b')])
    assert restored_one['coverage']['excluded_s'] == 1
    assert restored_one['reviewed']['periods']['full']['nn_count'] == 298


def test_small_exclusion_cannot_be_interpolated_across_even_below_5s_gap():
    value = feed([1000]*600,duration=600)
    result = analyze_hrv_review(value,None,exclusions=[exclude(30000,30001)])
    block = result['blocks'][0]
    assert block['baseline']['spectral_qualified'] is True
    assert block['reviewed']['qualified'] is True
    assert block['reviewed']['spectral_qualified'] is False
    assert block['reviewed']['spectral_reason'] == 'spectral_interpolation_crosses_exclusion'
    assert result['reviewed']['periods']['full']['spectral_blocks'] == 1
    assert result['blocks'][1]['baseline'] == result['blocks'][1]['reviewed']


def test_af_pending_and_confirmed_keep_existing_exclusion_rules_and_fixed_grid():
    value = feed([1000]*600,duration=600,excluded=((145,155),))
    result = analyze_hrv_review(value,None)
    assert result['baseline'] == analyze_hrv(value,None)
    assert result['blocks'][0]['reviewed']['nn_count'] == 290
    assert result['blocks'][0]['reviewed']['spectral_reason'] == 'spectral_gap_over_5s'
    assert [row['start_s'] for row in result['blocks']] == [0,300]
    assert result['blocks'][0]['reviewed']['sinus_verified'] is False


def test_24h_window_clock_hour_and_short_record_are_distinct():
    value = feed([1000]*310,duration=86710,start_sample=86400*200)
    result = analyze_hrv_review(value,'2026-01-01T08:54:00+08:00',window=1)
    assert result['coverage']['record_end_s'] == 86710
    assert result['coverage']['window_start_s'] == 86400
    assert result['blocks'][0]['start_s'] == 86400
    assert result['blocks'][0]['end_s'] == 86700
    assert result['blocks'][1]['duration_s'] == 10
    assert result['baseline']['hourly'][0]['partial'] is True
    missing = analyze_hrv_review(feed([1000]*10,duration=10),'invalid-clock')
    assert missing['coverage']['clock_available'] is False
    assert missing['baseline']['periods']['day']['mean_nn_ms'] is None
    assert missing['baseline']['periods']['night']['mean_nn_ms'] is None
    assert analyze_hrv_review(feed([],duration=0),None)['blocks'] == []


@pytest.mark.parametrize('item',[exclude(-1,1),exclude(1,201),exclude(5,5),exclude(True,10),exclude(0,1.5)])
def test_compute_rejects_invalid_sample_ranges(item):
    with pytest.raises(ValueError):
        analyze_hrv_review(feed([1000],duration=1),None,exclusions=[item])


class IsolatedStorage:
    def __init__(self,path):
        self.path = path
        with self.connect() as db:
            db.execute('CREATE TABLE global_revision (revision INTEGER NOT NULL)')
            db.execute('INSERT INTO global_revision VALUES(0)')
    def connect(self):
        db = sqlite3.connect(self.path)
        db.row_factory = sqlite3.Row
        return db


@pytest.fixture
def store(tmp_path):
    storage = IsolatedStorage(tmp_path/'isolated-hrv.sqlite')
    return HrvReviewStore(storage),storage


def context(revision=0,**updates):
    return dict(case_id='math-fixture',source_digest='source-1',data_version='data-1',
                analysis_basis='algorithm-source-1',beat_revision=0,analysis_revision=revision,**updates)


def hooks(storage,base=None):
    base = base or context()
    def current(db):
        return {**base,'analysis_revision':db.execute('SELECT revision FROM global_revision').fetchone()[0]}
    def changed(db,case_id,action):
        assert case_id == 'math-fixture'
        assert action in ('hrv_review.changed','hrv_review.confirmed')
        db.execute('UPDATE global_revision SET revision=revision+1')
    return current,changed


def request(current,operation,document=None,window=0):
    payload = dict(scope=current['scope'],expected_hrv_revision=current['hrv_revision'],operation=operation,window=window)
    if document is not None:
        payload['document'] = document
    return payload


def apply_preview(review,preview,current,storage,duration,base=None):
    checker,callback = hooks(storage,base)
    payload = dict(scope=current['scope'],expected_hrv_revision=current['hrv_revision'],
                   preview_token=preview['preview_token'],preview_digest=preview['preview_digest'],confirmed=True)
    return review.apply('math-fixture',payload,'doctor',current['scope'],duration,check_current=checker,on_change=callback)


def test_preview_cancel_apply_reopen_undo_redo_reset_preserve_original_parameters(store):
    review,storage = store
    current = review.read('math-fixture',context(),100000)
    document = blank_document()
    document['exclusions'] = [exclude(100,200)]
    preview = review.preview('math-fixture',request(current,'replace',document),context(),100000,actor='doctor')
    assert review.read('math-fixture',context(),100000)['hrv_revision'] == 0
    review.cancel_preview('math-fixture',{**request(current,'replace'),'preview_token':preview['preview_token']},context(),100000)
    with pytest.raises(ReportConflict):
        apply_preview(review,preview,current,storage,100000)
    preview = review.preview('math-fixture',request(current,'replace',document),context(),100000,actor='doctor')
    saved = apply_preview(review,preview,current,storage,100000)
    assert saved['hrv_revision'] == 1 and saved['scope']['analysis_revision'] == 1
    reopened = HrvReviewStore(storage).read('math-fixture',saved['scope'],100000)
    assert reopened['document'] == document and reopened['can_undo'] is True
    assert reopened['confirmation']['valid'] is False
    for operation,expected in [('undo',[]),('redo',document['exclusions']),('reset',[])]:
        preview = review.preview('math-fixture',request(reopened,operation),reopened['scope'],100000,actor='doctor')
        reopened = apply_preview(review,preview,reopened,storage,100000)
        assert reopened['document']['exclusions'] == expected
    assert reopened['hrv_revision'] == 4
    with storage.connect() as db:
        assert db.execute('SELECT COUNT(*) FROM hrv_review_audit').fetchone()[0] == 4


def test_stale_source_beat_global_revision_case_and_tokens_reject_writes(store):
    review,storage = store
    current = review.read('math-fixture',context(),1000)
    document = {**blank_document(),'exclusions':[exclude(10,20)]}
    preview = review.preview('math-fixture',request(current,'replace',document),context(),1000,actor='doctor')
    payload = dict(scope=current['scope'],expected_hrv_revision=0,preview_token=preview['preview_token'],preview_digest=preview['preview_digest'],confirmed=True)
    for field,new in [('source_digest','source-2'),('data_version','data-2'),('analysis_basis','new-engine'),('beat_revision',1),('analysis_revision',1)]:
        changed = {**context(),field:new}
        with pytest.raises(ReportConflict):
            review.apply('math-fixture',payload,'doctor',changed,1000)
    with pytest.raises(ReportConflict):
        review.apply('other-case',payload,'doctor',{**context(),'case_id':'other-case'},1000)
    with pytest.raises(ReportConflict):
        review.apply('math-fixture',{**payload,'preview_digest':'tampered'},'doctor',context(),1000)
    with pytest.raises(ReportConflict):
        review.apply('math-fixture',payload,'other-doctor',context(),1000)
    saved = apply_preview(review,preview,current,storage,1000)
    with pytest.raises(ReportConflict):
        review.apply('math-fixture',{**payload,'scope':saved['scope'],'expected_hrv_revision':1},'doctor',saved['scope'],1000)


def test_preview_expiration_and_source_changed_during_transaction_roll_back(store):
    review,storage = store
    review.clock = lambda: 100
    current = review.read('math-fixture',context(),1000)
    document = {**blank_document(),'exclusions':[exclude(10,20)]}
    preview = review.preview('math-fixture',request(current,'replace',document),context(),1000,actor='doctor')
    review.clock = lambda: 1001
    with pytest.raises(ReportConflict):
        apply_preview(review,preview,current,storage,1000)
    review.clock = lambda: 1100
    preview = review.preview('math-fixture',request(current,'replace',document),context(),1000,actor='doctor')
    payload = dict(scope=current['scope'],expected_hrv_revision=0,preview_token=preview['preview_token'],preview_digest=preview['preview_digest'],confirmed=True)
    checker,callback = hooks(storage)
    calls = 0
    def changing(db):
        nonlocal calls
        calls += 1
        value = checker(db)
        return value if calls == 1 else {**value,'source_digest':'changed-during-save'}
    with pytest.raises(ReportConflict):
        review.apply('math-fixture',payload,'doctor',context(),1000,check_current=changing,on_change=callback)
    assert review.read('math-fixture',context(),1000)['hrv_revision'] == 0
    with storage.connect() as db:
        assert db.execute('SELECT revision FROM global_revision').fetchone()[0] == 0


def confirm_payload(current,window=0):
    return dict(scope=current['scope'],expected_hrv_revision=current['hrv_revision'],
                expected_document_digest=current['digest'],confirmed=True,
                nn_rhythm_artifact_reviewed=True,note='只确认当前数学夹具窗口',window=window)


def test_doctor_confirmation_is_per_window_and_new_document_invalidates_all(store):
    review,storage = store
    duration = WINDOW_SAMPLES+1000
    checker,callback = hooks(storage)
    current = review.read('math-fixture',context(),duration)
    with pytest.raises(ValueError):
        review.confirm('math-fixture',{**confirm_payload(current),'nn_rhythm_artifact_reviewed':False},'doctor',context(),duration)
    current = review.confirm('math-fixture',confirm_payload(current),'doctor',current['scope'],duration,check_current=checker,on_change=callback)
    assert current['confirmation']['valid'] is True
    assert current['hrv_revision'] == 0
    assert current['confirmation']['clinical_validation'] is False
    assert current['confirmation']['quality_status'] == 'unknown'
    other = review.read('math-fixture',current['scope'],duration,window=1)
    assert other['confirmation']['valid'] is False
    other = review.confirm('math-fixture',confirm_payload(other,1),'doctor',other['scope'],duration,check_current=checker,on_change=callback)
    assert all(entry['valid'] for entry in other['confirmations'].values())
    assert other['confirmation']['end_sample'] == duration
    document = {**blank_document(),'exclusions':[exclude(10,20)]}
    preview = review.preview('math-fixture',request(other,'replace',document,1),other['scope'],duration,actor='doctor')
    saved = apply_preview(review,preview,other,storage,duration)
    assert saved['confirmations'] == {}
    assert saved['confirmation']['valid'] is False


def test_source_reopen_keeps_old_document_stale_until_explicit_rebase(store):
    review,storage = store
    current = review.read('math-fixture',context(),1000)
    document = {**blank_document(),'exclusions':[exclude(10,20)]}
    preview = review.preview('math-fixture',request(current,'replace',document),context(),1000,actor='doctor')
    saved = apply_preview(review,preview,current,storage,1000)
    new = {**saved['scope'],'source_digest':'source-2'}
    reopened = review.read('math-fixture',new,1000)
    assert reopened['document_stale'] is True
    assert reopened['document'] == document
    with pytest.raises(ReportConflict):
        review.confirm('math-fixture',confirm_payload(reopened),'doctor',new,1000)
    preview = review.preview('math-fixture',request(reopened,'replace',document),new,1000,actor='doctor')
    saved = apply_preview(review,preview,reopened,storage,1000,base=new)
    assert saved['document_stale'] is False and saved['hrv_revision'] == 2


@pytest.mark.parametrize('document',[
    {'schema_version':1,'profile':'AR','exclusions':[]},
    {'schema_version':True,'profile':'fixed-300s-fft-compat-v1','exclusions':[]},
    {**blank_document(),'nn_min':250},
    {**blank_document(),'exclusions':[exclude(0,10,reason=' ')]},
    {**blank_document(),'exclusions':[exclude(0,10),exclude(20,30)]},
])
def test_document_strict_schema_and_reason_validation(document):
    with pytest.raises(ValueError):
        normalize_document(document,1000)


def test_noop_apply_rechecks_source_without_changing_document_or_confirmation(store):
    review,storage = store
    current = review.read('math-fixture',context(),1000)
    preview = review.preview('math-fixture',request(current,'reset'),context(),1000,actor='doctor')
    payload = dict(scope=current['scope'],expected_hrv_revision=0,preview_token=preview['preview_token'],
                   preview_digest=preview['preview_digest'],confirmed=True)
    calls = 0
    def changing(db):
        nonlocal calls
        calls += 1
        return context() if calls == 1 else {**context(),'source_digest':'changed-at-noop'}
    with pytest.raises(ReportConflict):
        review.apply('math-fixture',payload,'doctor',context(),1000,check_current=changing)
    assert review.read('math-fixture',context(),1000)['hrv_revision'] == 0
    saved = review.apply('math-fixture',payload,'doctor',context(),1000)
    assert saved['hrv_revision'] == 0 and saved['document'] == blank_document()
    with storage.connect() as db:
        assert db.execute('SELECT COUNT(*) FROM hrv_review_audit').fetchone()[0] == 0
