"""All-category filtering is a view; source signal and beat locations are preserved."""
import json
import subprocess
from pathlib import Path
from test_analysis_provenance import synthetic_case, synthetic_app


def test_other_aggregate_matches_occurrences_density_and_template_parent(synthetic_app, synthetic_case):
    client=synthetic_app.test_client();cid=synthetic_case[1];base=f'/api/cases/{cid}'
    for sample,code in [(400,'X'),(600,'P'),(800,'S'),(1000,'V')]:
        result=client.put(base+'/beat-overrides',json={'sample_indices':[sample],'class_code':code})
        assert result.status_code==200,result.json
    before=synthetic_case[2]['data'].read_bytes()
    view=client.get(base+'/template-occurrences?class_code=other&mode=all').json
    assert {r['sample_index'] for r in view['items']}=={400,600}
    assert {r['class_code'] for r in view['items']}=={'X','P'} and view['total']==2
    density=client.post(base+'/waveform-density?class_code=other&leads=II,V1',json={})
    assert density.status_code==200,density.json
    assert set(density.json['population_samples'])=={400,600} and density.json['source_total']==2
    payload={'name':'synthetic-other-parent','rhythm_family':'自定义','lead':'II','source_class':'source-other','sample_indices':[400,600]}
    created=client.post(base+'/beat-templates',json=payload)
    assert created.status_code==201,created.json
    assert client.post(base+'/beat-templates',json={**payload,'sample_indices':[400,800]}).status_code==400
    assert synthetic_case[2]['data'].read_bytes()==before


def test_other_aggregate_complete_pagination(synthetic_app,synthetic_case):
    client=synthetic_app.test_client();base=f'/api/cases/{synthetic_case[1]}'
    for sample,code in [(400,'X'),(600,'P')]:
        assert client.put(base+'/beat-overrides',json={'sample_indices':[sample],'class_code':code}).status_code==200
    a=client.get(base+'/template-occurrences?class_code=other&limit=1').json
    b=client.get(base+'/template-occurrences?class_code=other&limit=1&offset=1').json
    assert a['total']==b['total']==2
    assert [a['items'][0]['sample_index'],b['items'][0]['sample_index']]==[400,600]


def test_representative_strip_uses_its_own_sampling_geometry():
    source=(Path(__file__).resolve().parents[1]/'static/js/app.js').read_text()
    body=source.split('function drawEditStrip(',1)[1].split('\nfunction ',1)[0]
    assert 'ECGReviewTools.sampleStride(item)' in body
    assert 'waveform' not in body
