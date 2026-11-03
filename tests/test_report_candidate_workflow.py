"""Mathematical-only RR grouping, saved report compatibility and AF representative clips."""
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path

import pytest

from app import create_app
from ecg_core.analysis_provenance import AnalysisRuntime, MODULES
from ecg_core.clinical_analysis import query_index, normalize_selection, validate_report
from ecg_core.ebi import HEADER_SIZE, RECORD
from ecg_core.report_layout import resolve_strip
from ecg_core.review_candidates import prepare_candidate, augment_index
from ecg_core.review_workflow import ReportConflict
from ecg_core.rr_report import rr_interval_groups, deduplicate_rr_selections
from ecg_core.source_identity import file_signature
from test_review_candidates import fixture_index, identity
from test_analysis_provenance import synthetic_case
from test_rr_quality import recording, browser


def combined_index():
    index = fixture_index()
    candidates = []
    for number, value in enumerate((4000, 800), 1):
        row = next(r for r in index['rows'] if r['rr_ms'] == value)
        item = prepare_candidate(index, identity(), dict(kind='rr', sample_index=row['sample_index']))
        candidates.append({**item, 'id':number, 'status':'active'})
    return augment_index(index, candidates, identity())


def selected(event, **settings):
    return dict(event_id=event['event_id'], basis_version=event['basis_version'],
                caption=event['label'], **settings)


def test_rr_combined_sources_have_stable_aliases_and_original_ids():
    index = combined_index()
    groups = rr_interval_groups(index)
    assert len(groups) == 4  # Three >2.5s events, plus the self-selected 800ms RR.
    group = next(e for e in groups if e['rr_ms'] == 4000)
    assert group['category'] == 'rr_candidate'
    assert group['rr_sources'] == ['auto', 'manual']
    assert len(group['rr_alias_event_ids']) == 2
    assert group['rr_aliases'][0]['category'] == 'rr_candidate'
    for source, total in [('all', 4), ('auto', 3), ('manual', 2)]:
        result = query_index(index, {'category':'rr_interval', 'rr_source':source})
        assert result['total'] == total
        assert result['category_counts']['rr_interval'] == 4
        assert result['rr_source_counts'] == {'all':4, 'auto':3, 'manual':2}
        current = next(e for e in result['items'] if e['rr_ms'] == 4000)
        assert current['event_id'] == group['event_id']
        assert current['rr_aliases'] == group['rr_aliases']
    auto_id = next(a['event_id'] for a in group['rr_aliases'] if a['category']=='pause')
    original = query_index(index, {'ids':auto_id})['items'][0]
    assert original['event_id'] == auto_id and original['category'] == 'pause'
    assert original['basis_version'] == next(e['basis_version'] for e in index['events'] if e['event_id']==auto_id)
    assert original['rr_aliases'] == group['rr_aliases']
    assert query_index(index, {'category':'pause'})['total'] == 3
    assert query_index(index, {'category':'rr_candidate'})['total'] == 2
    with pytest.raises(ValueError, match='RR 来源'):query_index(index, {'category':'rr_interval','rr_source':'unknown'})


@pytest.mark.parametrize('source', ['all', 'auto', 'manual'])
def test_rr_group_query_matches_browser_and_does_not_mutate_index(source):
    index = combined_index();before=deepcopy(index)
    params={'category':'rr_interval','rr_source':source,'sort':'hr_asc'}
    expected=query_index(index,params)
    assert browser('ECGClinicalAnalysis.queryIndex(x.index,x.params)', dict(index=index,params=params)) == json.loads(json.dumps(expected))
    assert index == before


def test_duplicate_rr_keeps_first_settings_and_stale_entries_remain_reconcilable():
    index=combined_index();group=next(e for e in rr_interval_groups(index) if e['rr_ms']==4000)
    auto=next(e for e in index['events'] if e['event_id'] in group['rr_alias_event_ids'] and e['category']=='pause')
    manual=next(e for e in index['events'] if e['event_id']==group['event_id'])
    first=selected(auto,leads=['II'],duration_s=7,range_start_s=3,range_end_s=20,notes='Preserve existing caption/leads/range')
    first['caption']='Existing automatic RR figure'
    second=selected(manual,leads=['V5'],duration_s=12)
    result,merged=deduplicate_rr_selections(index,[first,second])
    assert result == [first] and merged == [second['event_id']]
    old={**first,'basis_version':'stale-earlier-basis'}
    retained,merged=deduplicate_rr_selections(index,[old,second])
    assert retained == [old,second] and not merged
    with pytest.raises(ValueError,match='依据已变化'):
        validate_report(index,normalize_selection({'selected_events':[old,second]}),{},True)
    assert len(validate_report(index,normalize_selection({'selected_events':[first,second]}),{},False))==1
    assert normalize_selection({'category_reviews':{'pause':'old','rr_candidate':'old','rr_interval':'new'}})['category_reviews']=={'pause':'old','rr_candidate':'old','rr_interval':'new'}


@pytest.mark.parametrize('kind', ['AF','AFL'])
def test_af_manual_middle_and_end_clips_remain_separate_from_whole_episode(kind):
    from ecg_core.clinical_analysis import build_index
    index=build_index(recording([1000]*400,duration=400))
    event=dict(category='AF',subtype=kind,start_sample=20*200,end_sample=299*200,end_s=300)
    before=deepcopy(event)
    for start,end in [(15,25),(100,107),(294,305)]:
        spec=resolve_strip(index,event,dict(range_start_s=start,range_end_s=end,duration_s=7))
        assert (spec['start_s'],spec['end_s']) == (start,end)
        assert spec['context_start_s'] <= start and spec['context_start_s']+spec['context_duration_s'] >= end
        assert spec['visible_beat_count']>=5
    for start,end in [(0,7),(300,307)]:
        with pytest.raises(ValueError,match='相交'):
            resolve_strip(index,event,dict(range_start_s=start,range_end_s=end))
    with pytest.raises(ValueError,match='至少包含 5'):
        resolve_strip(index,event,dict(range_start_s=100,range_end_s=102))
    assert event==before
    non_af={**event,'category':'V'}
    with pytest.raises(ValueError,match='包含当前事件定位'):
        resolve_strip(index,non_af,dict(range_start_s=100,range_end_s=107))


def test_rr_helper_is_bound_to_running_build_without_mutating_application_files(tmp_path):
    from ecg_core import rr_report
    assert 'rr_report' in MODULES
    runtime=AnalysisRuntime()
    assert 'ecg_core.rr_report' in runtime.manifest['artifacts']
    original=Path(rr_report.__file__).resolve()
    sample=tmp_path/'mathematical-rr-helper.py';sample.write_bytes(original.read_bytes())
    runtime.files[sample]=file_signature(sample)
    runtime.file_names[sample]='ecg_core.rr_report'
    runtime.file_hashes[sample]=runtime.file_hashes[original]
    del runtime.files[original];del runtime.file_names[original];del runtime.file_hashes[original]
    runtime.assert_current()
    sample.write_bytes(sample.read_bytes()+b'\n# synthetic changed build\n')
    with pytest.raises(ReportConflict):runtime.assert_current()


def test_report_put_deduplicates_current_rr_preserves_auto_review_and_saved_settings(synthetic_case,tmp_path):
    root,cid,paths=synthetic_case
    # A real original 4s adjacency in a small generated 90s recording.
    paths['ebi'].write_bytes(bytes(HEADER_SIZE)+b''.join(
        RECORD.pack(i*200,1,1,0,0,0,4000 if i==24 else 1000)
        for i in range(1,90) if not 21<=i<=23))
    app=create_app(data_root=root,db_path=tmp_path/'rr-app.db',testing=True)
    client=app.test_client();base='/api/cases/'+cid;store=app.extensions['storage']
    assert client.get(base+'/report').status_code==200  # Establish the current source basis first.
    for step in ('edit','stt'):
        store.complete_review(cid,dict(step=step,confirmed=True,revision=store.get_review(cid)['revision']),'math-doctor')
    auto=client.get(base+'/report-events?category=pause').json['items'][0]
    initial=client.get(base+'/evidence-candidates').json
    scope={k:initial[k] for k in ('case_id','analysis_basis','analysis_revision','beat_revision')}
    response=client.post(base+'/evidence-candidates',json={**scope,'kind':'rr','sample_index':auto['sample_index'],'caption':'Math manual RR'})
    assert response.status_code==200,response.json
    manual=client.get(base+'/report-events?category=rr_candidate').json['items'][0]
    assert client.get(base+'/report-events?category=rr_interval').json['total']==1
    queried=client.get(base+'/report-events',query_string={'ids':auto['event_id']}).json['items'][0]
    assert queried['category']=='pause' and queried['diagnosis_status']=='confirmed'
    report=client.get(base+'/report').json
    first=selected(auto,leads=['II'],duration_s=7,notes='Existing doctor note')
    first['caption']='Existing original RR caption'
    second=selected(manual,leads=['V5'],duration_s=12)
    composition=dict(page_selection_version=1,included_pages=['event_strips'],selected_events=[first,second])
    legacy=store.save_report(cid,'Legacy mathematical duplicate','draft','fixture',composition,expected_version=report['version'])
    response_get=client.get(base+'/report')
    assert response_get.status_code==200
    assert len(response_get.json['composition']['selected_events'])==2
    assert len(store.get_report(cid,'')['composition']['selected_events'])==2
    assert store.get_report(cid,'')['version']==legacy['version']
    report=response_get.json
    response=client.put(base+'/report',json=dict(conclusion='Mathematical verification',status='draft',composition=composition,
        expected_version=report['version'],expected_review_revision=report['review_revision']))
    assert response.status_code==200,response.json
    saved=response.json
    assert saved['rr_merged_event_ids']==[manual['event_id']]
    assert len(saved['composition']['selected_events'])==1
    kept=saved['composition']['selected_events'][0]
    assert {k:kept[k] for k in ('event_id','caption','leads','duration_s','notes')}=={k:first[k] for k in ('event_id','caption','leads','duration_s','notes')}
    assert len(store.list_candidates(cid))==1
    response=client.put(base+'/report',json=dict(conclusion=saved['conclusion'],status='reviewed',composition=saved['composition'],
        expected_version=saved['version'],expected_review_revision=saved['review_revision']))
    assert response.status_code==200,response.json
