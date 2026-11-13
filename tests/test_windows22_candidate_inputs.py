"""Candidate continuation cannot replace an authenticated original producer."""
from copy import deepcopy
from types import SimpleNamespace
import pytest
from scripts import prepare_windows22_candidate as controller

@pytest.mark.parametrize('changed', [
    {'conclusion':'failure'}, {'status':'in_progress'}, {'head_sha':'b'*40},
    {'name':'unrelated workflow'}, {'event':'push'},
])
def test_refuse_unrelated_or_unaccepted_producer_before_artifact_reads(tmp_path, monkeypatch, changed):
    args=SimpleNamespace(run=77,commit='a'*40,output=tmp_path/'candidate')
    run=dict(status='completed',conclusion='success',head_sha=args.commit,
             name=controller.EXPECTED_WORKFLOW,event='workflow_dispatch')
    run.update(changed)
    reads=[]
    def api(repo,path):
        reads.append(path)
        assert path=='/actions/runs/77'
        return deepcopy(run)
    monkeypatch.setattr(controller,'api',api)
    monkeypatch.setattr(controller,'download',lambda *a:pytest.fail('Unaccepted original producer must never be downloaded'))
    with pytest.raises(AssertionError):controller.prepare(args)
    assert reads==['/actions/runs/77'] and not args.output.exists()
