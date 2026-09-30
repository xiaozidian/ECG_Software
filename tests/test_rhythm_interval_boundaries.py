"""Sample-grid oracles for inclusive annotations and half-open analysis spans."""
import copy
import random

import pytest

from ecg_core.overview import episode_annotations, initial_episodes
from ecg_core.rr_quality import annotation_exclusions, interval_mask
from ecg_core.clinical_analysis import build_index, query_index, validate_report
from ecg_core.report_sections import evidence
from ecg_core.beat_editor import edited_hrv
from test_rr_quality import recording, browser, pvc_recording
from test_analysis_provenance import synthetic_app, synthetic_case


def annotation(start, end, kind='AF', status='confirmed'):
    return dict(id=1, sample_index=start, details=dict(kind=kind, status=status, end_sample=end))


@pytest.mark.parametrize('kind', ['AF', 'AFL'])
@pytest.mark.parametrize('status', ['pending', 'confirmed', 'excluded'])
@pytest.mark.parametrize('bounds', [(200, 200), (0, 199), (0, 200), (199, 200), (201, 399), (800, 800)])
def test_inclusive_annotations_match_integer_sample_occupancy(kind, status, bounds):
    f = recording([1000]*4)
    a = annotation(*bounds, kind, status)
    # An annotation contains both end samples; an RR occupies [previous R, R).
    occupied = set(range(bounds[0], bounds[1]+1)) if status != 'excluded' else set()
    expected = [False] + [not occupied.intersection(range(p['sample_index'], r['sample_index']))
                          for p, r in zip(f.beats, f.beats[1:])]
    spans = annotation_exclusions([a])
    assert interval_mask(f.beats, spans) == expected
    assert browser('ECGRRQuality.intervalMask(x.rows,ECGRRQuality.annotationExclusions(x.annotations))',
                   dict(rows=f.beats, annotations=[a])) == expected


def test_random_overlapping_annotations_match_sample_union():
    rng = random.Random(9130)
    f = recording([1000]*40)
    annotations = [annotation(s, s+rng.randrange(0, 300), rng.choice(['AF', 'AFL']),
                              rng.choice(['pending', 'confirmed', 'excluded']))
                   for s in rng.sample(range(8000), 50)]
    occupied = set()
    for a in annotations:
        if a['details']['status'] != 'excluded':
            occupied.update(range(a['sample_index'], a['details']['end_sample']+1))
    expected = [False] + [not occupied.intersection(range(p['sample_index'], r['sample_index']))
                          for p, r in zip(f.beats, f.beats[1:])]
    assert interval_mask(f.beats, annotation_exclusions(annotations)) == expected
    assert browser('ECGRRQuality.intervalMask(x.rows,ECGRRQuality.annotationExclusions(x.annotations))',
                   dict(rows=f.beats, annotations=annotations)) == expected


def test_episode_roundtrip_and_hrv_retain_exact_grid_end():
    f = recording([1000]*40)
    doc = dict(episodes=[dict(id='one-sample', start_s=10, end_s=10.005, kind='AF', status='confirmed')])
    annotations = episode_annotations(doc)
    assert annotations[0]['details']['end_sample'] == 2000
    assert annotation_exclusions(annotations) == [(10, 10.005)]
    assert initial_episodes(f, annotations, f.duration)['episodes'][0]['end_s'] == 10.005
    f.excluded_rhythm_intervals = annotation_exclusions(annotations)
    hrv = edited_hrv(f)
    assert hrv['nn_count'] == 39 and hrv['successive_nn_pairs'] == 37
    assert browser('ECGBeatEngine.hrv(x,x.duration)', vars(f)) == hrv


def test_millisecond_episode_ends_do_not_grow_from_floating_point_roundoff():
    # Include every grid/non-grid millisecond near 10 s and near 24 hours.
    milliseconds = list(range(9900, 10100)) + list(range(86399900, 86400100))
    doc = dict(episodes=[dict(id=str(ms), start_s=(ms-5)/1000, end_s=ms/1000,
                             kind='AF', status='pending') for ms in milliseconds])
    expected = [(ms+4)//5-1 for ms in milliseconds]
    assert [a['details']['end_sample'] for a in episode_annotations(doc)] == expected
    assert browser("require('./static/js/overview-engine.js').annotations(x).filter(a=>!a.internal).map(a=>a.details.end_sample)", doc) == expected


def test_report_hrt_and_dc_use_same_inclusive_rhythm_boundary():
    for f, sample, metric, count in [(pvc_recording(), 1600, 'hrt', 'eligible_pvc'),
                                    (recording(([800]*30+[820]+[800]*29)*20), 0, 'dc', 'anchor_count')]:
        baseline = evidence(build_index(f))[metric][count]
        index = build_index(f, annotations=[annotation(sample, sample)])
        event = next(e for e in index['events'] if e['event_id'] == 'annotation:1')
        assert event['end_sample'] == sample  # Stored endpoint remains inclusive.
        assert event['end_s'] == (sample+1)/200
        result = evidence(index)
        assert result[metric][count] == baseline-1
        assert browser('ECGReportSections.evidence(ECGClinicalAnalysis.buildIndex(x.f,[],x.annotations))',
                       dict(f=vars(f), annotations=[annotation(sample, sample)])) == result


@pytest.mark.parametrize('category', ['fastest', 'slowest'])
def test_boundary_excludes_nn_candidate_but_retains_rr_candidate(category):
    f = recording([1000]*40, duration=40.005)
    index = build_index(f, annotations=[annotation(2000, 2000)])
    assert query_index(index, dict(category=category, fast_slow_mode='nn'))['total'] == 39
    assert query_index(index, dict(category=category, fast_slow_mode='rr'))['total'] == 40
    assert browser('ECGClinicalAnalysis.buildIndex(x.f,[],x.annotations)',
                   dict(f=vars(f), annotations=[annotation(2000, 2000)])) == index


def test_previous_af_duration_basis_cannot_be_approved_without_reselection():
    index = build_index(recording([1000]*40), annotations=[annotation(2000, 2000)])
    event = next(e for e in index['events'] if e['event_id'] == 'annotation:1')
    assert event['basis_version'].endswith('-inclusive-end-v1')
    old = {**event, 'basis_version':event['basis_version'].removesuffix('-inclusive-end-v1')}
    assert validate_report(index, {'selected_events':[old]}, {}) == []
    with pytest.raises(ValueError, match='失效'):
        validate_report(index, {'selected_events':[old]}, {}, approving=True)


@pytest.mark.parametrize('end', [10, 10.005])
def test_saved_review_exclusion_undo_redo_updates_all_hrv_endpoints(synthetic_app, synthetic_case, end):
    client = synthetic_app.test_client()
    base = '/api/cases/'+synthetic_case[1]
    def counts():
        return [client.get(base+path).json[key]['nn_count'] for path, key in
                [('/hrv?analysis=edited', 'calculated'), ('/report-statistics', 'hrv')]] + [
                    client.get(base+'/hrv-windows').json['periods']['full']['nn_count']]
    initial = counts()
    assert initial == [88]*3
    review = client.get(base+'/rhythm-review').json
    doc = dict(episodes=[dict(id='boundary', start_s=round(end-.005, 3), end_s=end, kind='AF', status='pending')])
    def save(operation='save', document=None):
        nonlocal review
        response = client.put(base+'/rhythm-review', json=dict(revision=review['revision'],
            beat_revision=review['beat_revision'], confirmed=True, operation=operation, document=document))
        assert response.status_code == 200, response.json
        review = response.json
    save(document=doc)
    assert counts() == [87]*3
    excluded = copy.deepcopy(doc); excluded['episodes'][0]['status'] = 'excluded'
    save(document=excluded)
    assert counts() == initial
    save('undo')
    assert counts() == [87]*3
    save('redo')
    assert counts() == initial
