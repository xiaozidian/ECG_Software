"""Independent passed stages cannot be replaced by a partial failed run."""
import copy
import pytest
from scripts import aggregate_windows21_acceptance as a


def metadata(role):
    w = a.STAGES[role]
    run = dict(id=w['run'], head_sha=w['head'], head_branch=w['branch'], status='completed',
        conclusion=w['conclusion'], run_attempt=1, path=a.c.CONTINUATION,
        repository={'full_name':a.c.REPO}, head_repository={'full_name':a.c.REPO})
    if role == 'M01_P01':
        steps = [dict(number=n, name='setup', status='completed', conclusion='success' if n < 14 or n == 22 else 'failure' if n == 14 else 'skipped') for n in range(1,23)]
        steps[11]['name']='Complete original21 M01 three native rounds plus actual draft PDF and HRV operations'
        steps[12]['name']='Actual original21 P01 source save reopen and packaging update'
    else:
        steps = [dict(number=n, name='setup', status='completed', conclusion='success') for n in range(1,13)]
        steps[8]['name']='Bind exact original21 compiled ZIPs and passed producer prerequisites'
        steps[10]['name']=w['business']
    jobs = dict(total_count=1,jobs=[dict(id=131472709504 if role=='M01_P01' else 888,run_id=w['run'],head_sha=w['head'],run_attempt=1,status='completed',conclusion=w['conclusion'],steps=steps)])
    row = dict(id=w.get('id',777),name=w['artifact'],size_in_bytes=w.get('bytes',100),digest='sha256:'+w.get('sha256','a'*64),expired=False,workflow_run={'id':w['run'],'head_sha':w['head']})
    return run,jobs,dict(total_count=1,artifacts=[row])


@pytest.mark.parametrize('role',list(a.STAGES))
def test_actual_passed_scope_retains_separate_execution_identity(role):
    assert a.validate_stage(role,*metadata(role))['name']==a.STAGES[role]['artifact']


@pytest.mark.parametrize('role',list(a.STAGES))
@pytest.mark.parametrize('change',['head','incomplete','artifact_head','failed_business'])
def test_stage_identity_or_incomplete_business_is_refused(role,change):
    run,jobs,arts=copy.deepcopy(metadata(role))
    if change=='head':run['head_sha']='f'*40
    elif change=='incomplete':run['status']='in_progress'
    elif change=='artifact_head':arts['artifacts'][0]['workflow_run']['head_sha']='c'*40
    else:jobs['jobs'][0]['steps'][11 if role=='M01_P01' else 10]['conclusion']='failure'
    with pytest.raises(ValueError):a.validate_stage(role,run,jobs,arts)


def test_original_failed_fresh_stage_must_not_be_claimed_success():
    run,jobs,arts=metadata('M01_P01');run['conclusion']='success'
    with pytest.raises(ValueError):a.validate_stage('M01_P01',run,jobs,arts)


def test_stage1_does_not_claim_skipped_old_upgrade_has_run():
    run,jobs,arts=metadata('M01_P01');jobs['jobs'][0]['steps'][14]['conclusion']='success'
    with pytest.raises(ValueError):a.validate_stage('M01_P01',run,jobs,arts)


