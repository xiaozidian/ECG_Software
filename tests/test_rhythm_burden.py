"""Saved AF/AFL coverage: independent sample unions, status gates and parity."""
import copy
import random

import pytest

from ecg_core.clinical_analysis import build_index, query_index, validate_report
from ecg_core.overview import episode_annotations, initial_episodes
from ecg_core.report_layout import report_statistics
from ecg_core.report_sections import evidence, rhythm_paragraphs
from ecg_core.report_sections_pdf import documents
from ecg_core.rr_quality import rhythm_summary
from test_rr_quality import browser, recording, OPTS
from test_analysis_provenance import synthetic_app, synthetic_case


def episode(a, b, kind='AF', status='confirmed', id='test'):
    return dict(id=id, start_s=a, end_s=b, kind=kind, status=status)


@pytest.mark.parametrize('lo,hi', [(0, 100), (0, 30), (30, 70), (70, 100), (50, 50)])
def test_random_overlap_against_independent_sample_sets(lo, hi):
    rng = random.Random(930)
    episodes = [episode(a/200, (a+rng.randrange(1, 2000))/200,
                        rng.choice(['AF', 'AFL']), rng.choice(['confirmed', 'pending', 'excluded']))
                for a in rng.sample(range(18000), 70)]
    result = rhythm_summary(episodes, 100, lo, hi)
    assert browser('ECGRRQuality.rhythmSummary(x.episodes,100,x.lo,x.hi)',
                   dict(episodes=episodes, lo=lo, hi=hi)) == result
    for key in ['confirmed_af', 'confirmed_afl', 'confirmed_any', 'pending_any']:
        selected = [e for e in episodes if e['status'] == ('pending' if key == 'pending_any' else 'confirmed')
                    and (key.endswith('any') or e['kind'] == ('AF' if key == 'confirmed_af' else 'AFL'))]
        occupied = set()
        for e in selected:
            occupied.update(range(max(lo*200, round(e['start_s']*200)), min(hi*200, round(e['end_s']*200))))
        assert result[key]['seconds'] == len(occupied)/200
        assert result[key]['count'] == sum(lo <= e['start_s'] < hi for e in selected)
        assert result[key]['pct'] == (round(len(occupied)/200/(hi-lo)*100, 6) if hi>lo else None)


@pytest.mark.parametrize('field,value', [('start_s', True), ('end_s', False), ('kind', 'V'), ('status', 'reviewed'), ('end_s', 0)])
def test_invalid_episode_rejected_on_both_sides(field, value):
    e = {**episode(0, 1), field:value}
    with pytest.raises(ValueError): rhythm_summary([e], 10)
    assert browser("(()=>{try{ECGRRQuality.rhythmSummary([x],10);return false}catch(_){return true}})()", e)


@pytest.mark.parametrize('duration,lo,hi', [(0,0,0), (100,0,100)])
def test_empty_or_missing_duration_is_not_false_normal(duration, lo, hi):
    summary = rhythm_summary([], duration, lo, hi)
    assert summary['confirmed_any']['pct'] == (0 if duration else None)
    lines = rhythm_paragraphs(summary)
    assert browser('ECGReportSections.rhythmParagraphs(x)', summary) == lines
    if not duration: assert '不以 0' in lines[0]
    assert browser('ECGReportSections.rhythmParagraphs(null)', {}) == rhythm_paragraphs(None)


def test_cross_hour_duration_and_start_counts_are_distinct():
    f = recording([1000]*10, duration=4000)
    eps = [episode(20, 90), episode(60, 200, 'AFL', id='flutter'), episode(30, 150, status='pending', id='pending')]
    index = build_index(f, annotations=episode_annotations(dict(episodes=eps)))
    result = report_statistics(index, '2026-09-30 10:59:00', OPTS)
    assert browser("require('./static/js/report-engine.js').statistics(x,'2026-09-30 10:59:00',"+str(OPTS).replace("'", '"')+")", index) == result
    first, second = result['hourly'][:2]
    assert [first['af'], second['af']] == [1, 1]
    assert [first['rhythm']['confirmed_any']['seconds'], second['rhythm']['confirmed_any']['seconds']] == [40, 140]
    assert first['rhythm']['denominator_s'] == 60
    assert result['summary']['rhythm']['confirmed_any']['seconds'] == 180
    assert result['summary']['rhythm']['confirmed_af']['seconds'] == 70
    assert result['summary']['rhythm']['confirmed_afl']['seconds'] == 140


@pytest.mark.parametrize('status', ['confirmed', 'pending', 'excluded'])
@pytest.mark.parametrize('edit_done', [False, True])
def test_episode_decision_independent_of_global_workflow(status, edit_done):
    f = recording([1000]*90)
    eps = [episode(10, 20, status=status)]
    review = dict(steps=dict(edit=dict(status='done' if edit_done else 'pending')))
    annotations = episode_annotations(dict(episodes=eps))
    index = build_index(f, annotations=annotations, review=review)
    assert browser('ECGClinicalAnalysis.buildIndex(x.f,[],x.annotations,x.review)',
                   dict(f=vars(f), annotations=annotations, review=review)) == index
    af = [e for e in index['events'] if e['category']=='AF']
    if status == 'excluded': assert af == []
    else:
        assert af[0]['rhythm_status'] == status
        assert af[0]['diagnosis_status'] == ('confirmed' if edit_done and status=='confirmed' else 'pending')
    result = evidence(index)
    assert result['af_summary']['confirmed_any']['seconds'] == (10 if status == 'confirmed' else 0)
    assert browser('ECGReportSections.evidence(x)', index) == result
    case = dict(case_id='synthetic', metadata={})
    py = documents(case, dict(section_evidence=result), ['af'])[0]['paragraphs']
    js = browser("(require('./static/js/report-paper.js'),ECGReportSections.documents(x,['af'])[0].paragraphs)", dict(case=case,evidence=result))
    assert py == js
    assert '独立状态' in ' '.join(py)


@pytest.mark.parametrize('code', ['A', 'M', 'C', 'H'])
def test_global_edit_approval_cannot_confirm_unreviewed_source_episode(code):
    f = recording([1000]*6, codes=['N', code, code, 'N', 'N', 'N'])
    review = dict(steps=dict(edit=dict(status='done')))
    index = build_index(f, review=review)
    af = [e for e in index['events'] if e['category']=='AF']
    assert len(af) == 1
    assert af[0]['rhythm_status'] == 'pending'
    assert af[0]['diagnosis_status'] == 'pending'
    assert query_index(index, dict(category='AF'))['confirmed_category_counts']['AF'] == 0
    assert evidence(index)['af_summary']['confirmed_any']['seconds'] == 0
    assert browser('ECGClinicalAnalysis.buildIndex(x.f,[],[],x.review)', dict(f=vars(f),review=review)) == index
    selection = dict(selected_events=[dict(event_id=af[0]['event_id'],basis_version=af[0]['basis_version'])],
                     category_reviews=index['basis_versions'])
    with pytest.raises(ValueError, match='房颤／房扑页完成片段诊断确认'):
        validate_report(index, selection, review, approving=True)
    assert browser('(()=>{try{ECGClinicalAnalysis.validateReport(x.index,x.selection,x.review,true);return false}catch(e){return e.message.includes("房颤／房扑页完成片段诊断确认")}})()',
                   dict(index=index,selection=selection,review=review))


def test_source_labels_stay_pending_and_extend_to_next_beat():
    f = recording([1000]*6, codes=['N','A','A','C','N','N'])
    index = build_index(f)
    af = [e for e in index['events'] if e['category']=='AF']
    assert [(e['time_s'], e['end_s'], e['rhythm_status']) for e in af] == [(2,4,'pending'),(4,5,'pending')]
    initial = initial_episodes(f, [], f.duration)
    assert rhythm_summary(initial['episodes'], f.duration) == evidence(index)['af_summary']
    assert browser('ECGClinicalAnalysis.buildIndex(x)', vars(f)) == index


def test_saved_coincident_pending_episode_remains_visible_without_double_burden():
    eps = [episode(10,20),episode(10,20,status='pending',id='pending')]
    f = recording([1000]*30)
    annotations = episode_annotations(dict(episodes=eps))
    annotations.append(dict(id='rhythm-control',sample_index=0,details=dict(rhythm_authoritative=True)))
    index = build_index(f, annotations=annotations)
    assert evidence(index)['af_summary'] == rhythm_summary(eps, f.duration)
    assert evidence(index)['af_summary']['pending_any']['count'] == 1
    assert evidence(index)['af_summary']['confirmed_any']['seconds'] == 10
    assert browser('ECGClinicalAnalysis.buildIndex(x.f,[],x.annotations)', dict(f=vars(f),annotations=annotations)) == index


def test_previous_status_basis_requires_reselection_even_for_confirmed_episode():
    review = dict(steps=dict(edit=dict(status='done')))
    index = build_index(recording([1000]*30), review=review,
                        annotations=episode_annotations(dict(episodes=[episode(10,20)])))
    item = next(e for e in index['events'] if e['category']=='AF')
    assert item['diagnosis_status'] == 'confirmed'
    selection = dict(selected_events=[dict(event_id=item['event_id'],
        basis_version=item['basis_version'].replace('episode-status-v2','episode-status-v1'))])
    assert validate_report(index, selection, review) == []
    with pytest.raises(ValueError, match='失效'):
        validate_report(index, selection, review, approving=True)
    assert browser('(()=>{try{ECGClinicalAnalysis.validateReport(x.index,x.selection,x.review,true);return false}catch(e){return e.message.includes("失效")}})()',
                   dict(index=index,selection=selection,review=review))


def test_saved_confirmation_undo_redo_recomputes_report(synthetic_app, synthetic_case):
    client = synthetic_app.test_client();base = '/api/cases/'+synthetic_case[1]
    review = client.get(base+'/rhythm-review').json
    doc = dict(episodes=[episode(10, 30), episode(40, 50, 'AFL', id='flutter'),
                         episode(10,30,status='pending',id='coincident')])
    def save(operation='save', document=None):
        nonlocal review
        r = client.put(base+'/rhythm-review', json=dict(revision=review['revision'], beat_revision=review['beat_revision'], confirmed=True, operation=operation, document=document))
        assert r.status_code == 200, r.json
        review = r.json
    def summary():
        r = client.get(base+'/report-statistics')
        assert r.status_code == 200, r.json
        return r.json['summary']['rhythm']
    save(document=doc)
    assert summary()['confirmed_any']['seconds'] == 30
    assert summary()['pending_any']['count'] == 1
    pending = copy.deepcopy(doc);pending['episodes'][0]['status']='pending'
    save(document=pending)
    assert summary()['confirmed_any']['seconds'] == 10
    save('undo');assert summary()['confirmed_any']['seconds'] == 30
    save('redo');assert summary()['confirmed_any']['seconds'] == 10
