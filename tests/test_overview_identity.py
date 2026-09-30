"""Overview/AF reads and writes must share the current synthetic evidence."""
import pytest
import subprocess

from test_analysis_provenance import synthetic_case, synthetic_app


@pytest.mark.parametrize('scenario', ['success', 'mixed', 'beat-mismatch', 'final-change', 'retry',
    'late-success', 'late-error', 'wave-refresh', 'wave-mismatch', 'late-wave-failure',
    'same-case-reload', 'save-success', 'save-refresh-error', 'save-reload-error', 'save-not-ready'])
def test_browser_overview_identity(scenario):
    subprocess.run(['node', 'tests/browser_overview_identity.cjs', scenario], check=True, timeout=20)


@pytest.mark.parametrize('endpoint', ['overview', 'rhythm-review'])
@pytest.mark.parametrize('change', ['review', 'raw'])
def test_overview_read_rejects_stale_identity(synthetic_app, synthetic_case, endpoint, change):
    client = synthetic_app.test_client()
    base = '/api/cases/' + synthetic_case[1]
    basis = client.get(base + '/analysis-basis').json
    response = client.get(base + '/' + endpoint, query_string=basis)
    assert response.status_code == 200
    assert all(response.json.get(k) == v for k, v in basis.items())
    if change == 'review':
        synthetic_app.extensions['storage'].audit('test', 'beat_override.editor', synthetic_case[1])
    else:
        path = synthetic_case[2]['data']
        path.write_bytes(b'\1' + path.read_bytes()[1:])
    response = client.get(base + '/' + endpoint, query_string=basis)
    assert response.status_code == 409, response.json


@pytest.mark.parametrize('endpoint', ['overview', 'rhythm-review'])
def test_overview_mid_read_change_is_not_published(synthetic_app, synthetic_case, monkeypatch, endpoint):
    import app as server
    original = server.EditedRecords
    def racing(*args, **kwargs):
        result = original(*args, **kwargs)
        synthetic_app.extensions['storage'].audit('test', 'beat_override.editor', synthetic_case[1])
        return result
    monkeypatch.setattr(server, 'EditedRecords', racing)
    response = synthetic_app.test_client().get('/api/cases/' + synthetic_case[1] + '/' + endpoint)
    assert response.status_code == 409, response.json


@pytest.mark.parametrize('change', ['review', 'raw', 'transaction'])
def test_af_save_rejects_changed_evidence_without_losing_history(synthetic_app, synthetic_case, monkeypatch, change):
    from ecg_core.overview import RhythmReviewStore
    client = synthetic_app.test_client();cid = synthetic_case[1];base = '/api/cases/' + cid
    basis = client.get(base + '/analysis-basis').json
    before = client.get(base + '/rhythm-review').json
    payload = dict(basis, revision=before['revision'], beat_revision=before['beat_revision'],
                   confirmed=True, document=dict(episodes=[], bookmarks={'fastest': 10}))
    if change == 'raw':
        path = synthetic_case[2]['data'];path.write_bytes(b'\1' + path.read_bytes()[1:])
    elif change == 'review':
        synthetic_app.extensions['storage'].audit('test', 'beat_override.editor', cid)
    else:
        original = RhythmReviewStore.commit
        def racing(self, *args, **kwargs):
            self.storage.audit('test', 'beat_override.editor', cid)
            return original(self, *args, **kwargs)
        monkeypatch.setattr(RhythmReviewStore, 'commit', racing)
    response = client.put(base + '/rhythm-review', json=payload)
    assert response.status_code == 409, response.json
    after = client.get(base + '/rhythm-review').json
    assert {k: after[k] for k in ('revision', 'document', 'can_undo', 'can_redo')} == {
        k: before[k] for k in ('revision', 'document', 'can_undo', 'can_redo')}


def test_af_save_and_undo_return_current_readable_evidence(synthetic_app, synthetic_case):
    client = synthetic_app.test_client();base = '/api/cases/' + synthetic_case[1]
    for operation in ('save', 'undo', 'redo'):
        before = client.get(base + '/rhythm-review').json
        basis = client.get(base + '/analysis-basis').json
        response = client.put(base + '/rhythm-review', json=dict(basis,
            revision=before['revision'], beat_revision=before['beat_revision'], confirmed=True,
            operation=operation, document=dict(episodes=[], bookmarks={'fastest': 10})))
        assert response.status_code == 200, response.json
        fresh = client.get(base + '/analysis-basis').json
        assert fresh['analysis_revision'] > basis['analysis_revision']
        for endpoint in ('overview', 'rhythm-review', 'waveform'):
            read = client.get(base + '/' + endpoint, query_string=fresh)
            assert read.status_code == 200, read.json
            assert all(read.json.get(k) == v for k, v in fresh.items())
        assert client.get(base + '/rhythm-review').json['document']['bookmarks'] == (
            {} if operation == 'undo' else {'fastest': 10})
