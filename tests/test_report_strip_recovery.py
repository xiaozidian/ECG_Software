"""The same saved selection can be reattached only to its own acquisition and samples."""
from copy import deepcopy
from contextlib import closing
import json

import pytest

from ecg_core.analysis_provenance import digest
from ecg_core.report_strip_recovery import candidate_version, install_recovery, source_matches
from ecg_core.review_candidates import canonical
from test_analysis_provenance import synthetic_app, synthetic_case
from test_report_evidence_review import ok, pick, save, scope


def historical_card(app, case_id, event, entry, edit=None):
    store = app.extensions['storage']
    cid = event['local_candidate_id']
    case = app.extensions['case_repository'].get_case(case_id)
    current = app.extensions['analysis_runtime'].basis(case)
    proof = {k: v for k, v in current.items() if k in ('schema', 'inputs', 'recovery_epoch')}
    proof['engine_id'] = 'synthetic-previous-engine'
    old_id = digest(proof)
    candidate = next(c for c in store.list_candidates(case_id) if c['id'] == cid)
    candidate['scope']['analysis_basis'] = old_id
    if edit:
        edit(candidate['payload'])
    with closing(store.connect()) as db, db:
        db.execute('INSERT OR IGNORE INTO report_strip_sources VALUES(?,?,?)',
                   (case_id, old_id, json.dumps(proof)))
        db.execute('UPDATE evidence_candidates SET scope=?,payload=? WHERE id=?',
                   (canonical(candidate['scope']), canonical(candidate['payload']), cid))
    return dict(entry, basis_version=candidate_version(candidate))


def test_partial_recovery_on_original_card_retry_and_withdrawal(synthetic_case, synthetic_app):
    app = synthetic_app
    if "recover_report_strips" not in app.view_functions:
        install_recovery(app)
    _, case_id, _ = synthetic_case
    client = app.test_client()
    path = '/api/cases/' + case_id
    rr, rr_entry = pick(client, path)
    strip, strip_entry = pick(client, path, 'strip')
    # A physician has already saved these specific presentations in the draft.
    assert save(client, path, [strip_entry, rr_entry]).status_code == 200
    rr_entry = historical_card(app, case_id, rr, rr_entry,
                               lambda p: p.update(rr_start_id='different-heartbeat'))
    strip_entry = historical_card(app, case_id, strip, strip_entry)
    store = app.extensions['storage']
    with closing(store.connect()) as db, db:
        current = json.loads(db.execute('SELECT composition FROM report_drafts WHERE case_id=?',
                                        (case_id,)).fetchone()[0])
        current['selected_events'] = [strip_entry, rr_entry]
        db.execute('UPDATE report_drafts SET composition=? WHERE case_id=?',
                   (json.dumps(current), case_id))
    previous = ok(client.get(path + '/report'))
    expected = {**scope(client, path), 'report_version': previous['version']}
    call = lambda data: client.post(path + '/report-strip-recovery', json=data)
    result = ok(call(expected))
    assert result['restored'] == [strip['event_id']]
    assert '相邻两搏' in result['reasons'][rr['event_id']]
    current = ok(client.get(path + '/report'))
    assert current['status'] == 'draft' and current['conclusion'] == previous['conclusion']
    assert current['composition']['selected_events'][1] == previous['composition']['selected_events'][1]
    before, after = previous['composition']['selected_events'][0], current['composition']['selected_events'][0]
    assert before['basis_version'] != after['basis_version']
    assert before == {**after, 'basis_version': before['basis_version']}
    event = ok(client.get(path + '/report-events', query_string={'ids': strip['event_id']}))['items'][0]
    assert event['evidence_review']['status'] == 'pending'
    assert call(expected).status_code == 409
    expected['report_version'] = current['version']
    assert ok(call(expected))['restored'] == []
    with closing(store.connect()) as db, db:
        db.execute("UPDATE evidence_candidates SET status='withdrawn' WHERE id=?", (rr['local_candidate_id'],))
    assert '撤销' in ok(call(expected))['reasons'][rr['event_id']]
    assert ok(client.get(path + '/report'))['version'] == current['version']


def test_changed_sources_and_unknown_history_cannot_recover():
    old = dict(schema=1, engine_id='first', inputs={'data': 'original-bytes'}, recovery_epoch='a')
    current = deepcopy(old)
    current['engine_id'] = 'second'
    source_matches(digest(old), current, old)
    with pytest.raises(ValueError, match='更换'):
        source_matches(digest(old), {**current, 'inputs': {'data': 'changed'}}, old)
    with pytest.raises(ValueError, match='备份'):
        source_matches(digest(old), {**current, 'recovery_epoch': 'b'}, old)
    with pytest.raises(ValueError, match='缺少'):
        source_matches(digest(old), current, None)
    with pytest.raises(ValueError, match='不完整'):
        source_matches(digest(old), current, {**old, 'engine_id': 'unrelated'})


def test_identical_rr_at_another_card_does_not_inherit_confirmation():
    from ecg_core.report_evidence import evidence_descriptor
    from test_review_candidates import fixture_index, identity

    index = fixture_index()
    a, b = index['rows'][3:5]
    event = dict(category='rr_candidate', event_id='local-pick:39',
                 start_sample=b['sample_index'], rr_ms=b['rr_ms'],
                 candidate_context={'rr_start_sample': a['sample_index']})
    descriptor = evidence_descriptor(index, event, identity())
    event['candidate_context']['restored_from'] = 'older presentation'
    restored = evidence_descriptor(index, event, identity())
    assert descriptor['scope'] != restored['scope']
    assert restored['previous'] == descriptor['previous'] and restored['terminal'] == descriptor['terminal']
    assert evidence_descriptor(index, {**event, 'event_id': 'local-pick:40'}, identity()) != restored


def test_missing_one_sample_on_one_print_lead_prevents_recovery():
    from ecg_core.report_strip_recovery import restore_candidate
    from ecg_core.review_candidates import prepare_candidate
    from test_review_candidates import fixture_index, identity

    index = fixture_index()
    candidate = prepare_candidate(index, identity(), dict(kind='strip', time_s=10))
    candidate.update(id=4, status='active')
    entry = dict(candidate['payload']['settings'], event_id='local-pick:4',
                 caption='test', basis_version=candidate_version(candidate))

    def truncated_reader(start, end, leads, points):
        count = round((end - start) * 200)
        return dict(start_s=start, duration_s=end - start, sample_rate_hz=200, stride=1,
                    leads={name: [0] * (count - (name == 'V6')) for name in leads})

    with pytest.raises(ValueError, match='采样或所选导联不完整'):
        restore_candidate(index, {**identity(), 'beat_revision': 1}, candidate, [entry], truncated_reader)
