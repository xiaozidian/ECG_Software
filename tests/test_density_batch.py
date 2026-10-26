"""Batch transport retains every selected sample and each exact density bin."""
from copy import deepcopy
import numpy as np
import pytest

from test_analysis_provenance import synthetic_case, synthetic_app


@pytest.mark.parametrize('leads',[['II','V1'],['III','aVR']])
@pytest.mark.parametrize('selection',[{}, {'samples':[200,400,600,800],'exclude_samples':[600]},
                                     {'samples':[400,600,800],'amplitude_limit':1200}])
def test_batch_equals_two_independent_full_results(synthetic_app,synthetic_case,leads,selection):
    _,cid,paths=synthetic_case
    rng=np.random.default_rng(20261023)
    paths['data'].write_bytes(rng.integers(-1600,1601,size=(90*200,8),dtype=np.int16).astype('<i2').tobytes())
    client=synthetic_app.test_client();base=f'/api/cases/{cid}/waveform-density?analysis=edited'
    singles=[client.post(base+'&lead='+lead,json=selection).json for lead in leads]
    result=client.post(base+'&leads='+','.join(leads),json=selection)
    assert result.status_code==200,result.json
    batch=result.json
    for lead,old in zip(leads,singles):
        item=next(x for x in batch['items'] if x['lead']==lead)
        full={**item,**{k:v for k,v in batch.items() if k!='items'}}
        assert full==old
    assert len(result.data)<sum(len(client.post(base+'&lead='+l,json=selection).data) for l in leads)


@pytest.mark.parametrize('leads',['','II,II','II,V1,V5','made-up'])
def test_batch_rejects_invalid_leads(synthetic_app,synthetic_case,leads):
    assert synthetic_app.test_client().post(f'/api/cases/{synthetic_case[1]}/waveform-density?leads={leads}',json={}).status_code==400


def test_mid_batch_revision_change_returns_no_partial_result(synthetic_app,synthetic_case,monkeypatch):
    import app as server
    cid=synthetic_case[1];calls=[];original=server.density
    def racing(*args,**kw):
        result=original(*args,**kw);calls.append(1)
        if len(calls)==1:synthetic_app.extensions['storage'].audit('synthetic','annotation.update',cid)
        return result
    monkeypatch.setattr(server,'density',racing)
    response=synthetic_app.test_client().post(f'/api/cases/{cid}/waveform-density?leads=II,V1&analysis=edited',json={})
    assert response.status_code==409,response.json
    assert 'items' not in response.json
