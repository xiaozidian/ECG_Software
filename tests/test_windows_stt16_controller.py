"""Pure controller contracts; these checks never claim native Windows success."""
import copy
from hashlib import sha256
from pathlib import Path
import pytest

from scripts.verify_windows_stt_comprehensive_native import compare_api,fingerprint,OLD_APP,NEW_ALGORITHM,LEGACY_DRIVER_SHA
from scripts.verify_windows_stt_independent_upgrade import invalidated_composition


def basis(app,exe):
    engine=dict(app_version=app,artifacts=dict(app=exe))
    row=dict(schema=1,engine=engine,engine_id=fingerprint(engine),inputs={'synthetic_raw':'c'*64})
    row['digest']=fingerprint({k:v for k,v in row.items() if k!='engine'})
    return row


def fixture():
    package=dict(base_exe_sha256='a'*64,new_exe_sha256='b'*64,application_version='new-ST-T-test-engine')
    old_basis=basis(OLD_APP,package['base_exe_sha256']);new_basis=basis(package['application_version'],package['new_exe_sha256'])
    composition=dict(selected_events=[dict(event_id='annotation:1',basis_version='old',leads=['II'],caption='doctor text')],category_reviews={'ST':'old'},diagnosis_blocks=[dict(manual=True,needs_review=False,acknowledged=True,text='original doctor text')])
    proof=dict(kind='st_depression',measurement_protocol={'method_version':'stt-hospital-review-v2'},start_s=1,end_s=121)
    old=dict(status='reviewed',reviewed_by='mathematical-doctor',version=4,review_revision=2,current_analysis_basis=old_basis,analysis_provenance={'basis':old_basis,'signature':'keep'},composition=composition,conclusion='original mathematical conclusion',case_id='math')
    before=dict(report=old,basis={'analysis_basis':old_basis['digest']},beat_editor={'revision':0},annotations={'items':[{'id':1,'details':proof,'stt_review_receipt':{'review_state':'reviewed'}}]},events={'items':[dict(event_id='annotation:1',category='ST',stt_review_state='reviewed',stt_event_evidence=proof)]})
    after=copy.deepcopy(before);after['report'].update(status='draft',reviewed_by='',version=5,review_revision=3,current_analysis_basis=new_basis,composition=invalidated_composition(composition))
    after['basis']['analysis_basis']=new_basis['digest'];after['events']['items'][0].update(stt_review_state='stale',stt_report_eligibility=dict(table=False,text=False,strip=False))
    after['stt']=dict(analysis=dict(algorithm_version=NEW_ALGORITHM,rhythm_policy='independent_of_AF_AFL_reviews',exclusions={'intervals':[]}))
    return before,after,package


def test_valid_pure_upgrade_contract_is_not_a_native_verdict():
    b,a,p=fixture();assert compare_api(b,a,p)['old_provenance_preserved_not_resigned']


@pytest.mark.parametrize('fault',[
    'old_not_approved','new_still_approved','wrong_report_version','wrong_review_revision','resigned_history',
    'edited_conclusion','changed_selected_leads','changed_doctor_text','changed_source_input','moved_beat',
    'edited_annotation','lost_historical_record','old_record_promoted','missing_eligibility','old_evidence_relabelled',
    'old_algorithm','AF_masks_reintroduced','wrong_current_basis',
])
def test_upgrade_comparator_rejects_every_preservation_or_basis_regression(fault):
    b,a,p=fixture()
    if fault=='old_not_approved':b['report']['status']='draft'
    elif fault=='new_still_approved':a['report']['status']='reviewed'
    elif fault=='wrong_report_version':a['report']['version']+=1
    elif fault=='wrong_review_revision':a['report']['review_revision']+=1
    elif fault=='resigned_history':a['report']['analysis_provenance']['signature']='replaced'
    elif fault=='edited_conclusion':a['report']['conclusion']='rewritten'
    elif fault=='changed_selected_leads':a['report']['composition']['selected_events'][0]['leads']=['I']
    elif fault=='changed_doctor_text':a['report']['composition']['diagnosis_blocks'][0]['text']='rewritten'
    elif fault=='changed_source_input':a['report']['current_analysis_basis']['inputs']['synthetic_raw']='d'*64
    elif fault=='moved_beat':a['beat_editor']['revision']=1
    elif fault=='edited_annotation':a['annotations']['items'][0]['details']['end_s']=100
    elif fault=='lost_historical_record':a['events']['items']=[]
    elif fault=='old_record_promoted':a['events']['items'][0]['stt_review_state']='reviewed'
    elif fault=='missing_eligibility':a['events']['items'][0]['stt_report_eligibility']={}
    elif fault=='old_evidence_relabelled':a['events']['items'][0]['stt_event_evidence']['kind']='t_low_flat'
    elif fault=='old_algorithm':a['stt']['analysis']['algorithm_version']='old'
    elif fault=='AF_masks_reintroduced':a['stt']['analysis']['exclusions']['intervals']=[{'kind':'AF'}]
    elif fault=='wrong_current_basis':a['basis']['analysis_basis']='wrong'
    with pytest.raises(AssertionError):compare_api(b,a,p)


def test_old15_visible_driver_is_immutable_and_new_build_includes_ST_help():
    root=Path(__file__).resolve().parents[1]
    assert sha256((root/'scripts/stt16_legacy15_report_evidence_ui.py').read_bytes()).hexdigest()==LEGACY_DRIVER_SHA
    from scripts.windows_doctor_build import ASSET_FILES
    assert 'static/help/stt.html' in ASSET_FILES
