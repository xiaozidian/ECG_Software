"""Disposed mathematical records: cold/hot reuse must preserve clinical scope."""
from copy import deepcopy
import shutil

import pytest

from test_analysis_provenance import synthetic_case, synthetic_app, replace_preserving_mtime

READS = [('', 'ebi_metrics'), ('/trend', 'heart_rate_trend'),
         ('/scatter', 'scatter_points'), ('/rr-visuals', 'rr_visuals'),
         ('/rr-distribution', 'rr_distribution'), ('/report-statistics', 'report_statistics')]


@pytest.mark.parametrize('suffix,function', READS)
@pytest.mark.parametrize('change', ['source', 'review', 'beat'])
def test_hot_read_reuses_only_the_current_case_source_and_revisions(
        synthetic_app, synthetic_case, monkeypatch, suffix, function, change):
    import app as server
    original = getattr(server, function)
    calls = []
    def counted(*args, **kwargs):
        calls.append(1)
        return original(*args, **kwargs)
    monkeypatch.setattr(server, function, counted)
    _, cid, paths = synthetic_case
    client = synthetic_app.test_client()
    url = f'/api/cases/{cid}{suffix}?analysis=edited'
    first = client.get(url)
    assert first.status_code == 200, first.json
    assert client.get(url).json == first.json
    assert len(calls) == 1
    store = synthetic_app.extensions['storage']
    if change == 'source':
        content = paths['data'].read_bytes()
        replace_preserving_mtime(paths['data'], b'\1' + content[1:])
    elif change == 'review':
        store.audit('mathematical', 'annotation.update', cid)
    else:
        from ecg_core.beat_editor import BeatEditorStore
        editor = BeatEditorStore(store)
        editor.commit(cid, 0, 'mathematical', deepcopy, 'synthetic-read-cache-revision')
    current = client.get(url)
    assert current.status_code == 200, current.json
    assert len(calls) == 2
    assert client.get(url).json == current.json
    assert len(calls) == 2


def test_identical_contents_in_another_case_never_reuse_its_result(synthetic_app, synthetic_case, monkeypatch):
    import app as server
    root, cid, paths = synthetic_case
    other = '9999999999999998'
    for kind, path in paths.items():
        destination = root / other / path.relative_to(root / cid)
        destination = destination.with_name(destination.name.replace(cid, other))
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, destination)
    calls = []
    original = server.heart_rate_trend
    def counted(*args):
        calls.append(1)
        return original(*args)
    monkeypatch.setattr(server, 'heart_rate_trend', counted)
    client = synthetic_app.test_client()
    for case in (cid, other, cid, other):
        assert client.get(f'/api/cases/{case}/trend?analysis=edited').status_code == 200
    assert len(calls) == 2


def test_changed_identity_during_build_never_publishes_or_caches_it(synthetic_app, synthetic_case, monkeypatch):
    import app as server
    original = server.heart_rate_trend
    calls = []
    def racing(*args):
        calls.append(1)
        result = original(*args)
        if len(calls) == 1:
            synthetic_app.extensions['storage'].audit('mathematical', 'annotation.update', synthetic_case[1])
        return result
    monkeypatch.setattr(server, 'heart_rate_trend', racing)
    client = synthetic_app.test_client()
    url = f'/api/cases/{synthetic_case[1]}/trend?analysis=edited'
    assert client.get(url).status_code == 409
    assert client.get(url).status_code == 200
    assert client.get(url).status_code == 200
    assert len(calls) == 2
