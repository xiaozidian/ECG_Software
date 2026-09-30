"""Post-hoc evidence integrity and exact frozen-threshold explanations."""
import gzip
import json

import pytest

from scripts import inspect_qrs_localization as audit


@pytest.mark.parametrize('cv,rmssd,turning,expected', [
    (.12,.14,.45,''),(.12,.14,.85,''),(.119,.14,.45,'cv'),
    (.12,.139,.45,'rmssd'),(.12,.14,.449,'turning'),
    (.12,.14,.851,'turning'),(.1,.1,.9,'cv+rmssd+turning')])
def test_threshold_explanation_keeps_inclusive_boundaries(cv,rmssd,turning,expected):
    assert audit.failures(dict(cv=cv,normalized_rmssd=rmssd,turning_ratio=turning))==expected


def test_withheld_is_not_negative():
    assert audit.state(dict(reason='low_quality',candidate=False))=='low_quality'
    assert audit.state(dict(reason=None,candidate=False))=='negative'


def fixture(tmp_path):
    results=tmp_path/'results';prior=tmp_path/'prior';results.mkdir();prior.mkdir()
    manifest=dict(protocol='bounded-qrs-localization-v1',records=['00','05','112'],
        methods=['xqrs_ch0','corrected_ch0','xqrs_ch1','corrected_ch1'],
        results=[],result_sha256={},prior_sha256={},source_sha256={})
    before=dict(start_s=0,end_s=30,reason=None,candidate=True,cv=.2,normalized_rmssd=.2,turning_ratio=.5)
    after=dict(before,candidate=False,turning_ratio=.4)
    def write(root,name,value,key):
        with gzip.open(root/name,'wt') as stream:json.dump(value,stream)
        manifest[key][name]=audit.digest(root/name)
    for r in manifest['records']:
        write(prior,f'{r}-detection.json.gz',[dict(samples=[10,100])]*2,'prior_sha256')
        write(results,f'{r}-correction.json.gz',[dict(samples=[11,101])]*2,'result_sha256')
        for ch in (0,1):
            a=dict(samples=[10,100],af_windows=[before])
            b=dict(samples=[11,101],af_windows=[after])
            write(prior,f'{r}-xqrs_ch{ch}.json.gz',a,'prior_sha256')
            for method,value in [(f'xqrs_ch{ch}',a),(f'corrected_ch{ch}',b)]:
                write(results,f'{r}-{method}.json.gz',value,'result_sha256')
                manifest['results'].append(dict(record=r,method=method))
    (results/'summary.json').write_text(json.dumps(manifest))
    return results,prior,manifest


def test_saved_evidence_check_and_explanation(tmp_path):
    results,prior,_=fixture(tmp_path);output=tmp_path/'transitions.json'
    audit.inspect(results,prior,output)
    value=json.loads(output.read_text())
    assert len(value['transitions'])==6
    assert all(r['candidate_to_negative_thresholds']=={'turning':1} for r in value['transitions'])
    assert value['summary_sha256']==audit.digest(results/'summary.json')
    with pytest.raises(FileExistsError):audit.inspect(results,prior,output)


@pytest.mark.parametrize('fault', ['hash','checkpoint','baseline','duplicate'])
def test_inconsistent_evidence_never_produces_completion(tmp_path,fault):
    results,prior,m=fixture(tmp_path);output=tmp_path/'transitions.json'
    name='00-corrected_ch0.json.gz'
    if fault=='duplicate':m['results'][-1]=m['results'][0]
    else:
        if fault=='baseline':name='00-xqrs_ch0.json.gz'
        value=audit.payload(results/name)
        if fault=='baseline':value['af_windows'][0]['cv']=.3
        else:value['samples']=[12,101]
        with gzip.open(results/name,'wt') as stream:json.dump(value,stream)
        if fault!='hash':m['result_sha256'][name]=audit.digest(results/name)
    (results/'summary.json').write_text(json.dumps(m))
    with pytest.raises(ValueError):audit.inspect(results,prior,output)
    assert not output.exists()
