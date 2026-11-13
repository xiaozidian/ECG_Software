"""Reject misleading compatibility verdicts; actual Windows acceptance runs separately."""
import copy
from pathlib import Path
import pytest
from scripts.verify_windows_screening_quality import (
    APP, BASE_APP, BASE_PE_SHA, metadata_identity, compare_api, compare_nonempty_scopes, fingerprint,
)


def baseline():
    engine = dict(app_version=BASE_APP, artifacts=dict(app=BASE_PE_SHA))
    basis = dict(schema=1, engine=engine, engine_id=fingerprint(engine), inputs={'math': 'c'*64})
    basis['digest'] = fingerprint({k:v for k,v in basis.items() if k!='engine'})
    evidence = {'kind':'t_inversion', 'start_s':60, 'end_s':180, 'measurements':[1,2,3]}
    eligibility = dict(table=True, text=True, strip=True)
    report = dict(status='reviewed', reviewed_by='mathematical-physician', version=5, review_revision=2,
                  current_analysis_basis=basis, current_hrv_reference={'revision':0,'scope':{'analysis_basis':basis['digest']}},
                  conclusion='original authored conclusion', analysis_provenance={'basis':basis,'signature':'original signature'},
                  composition={'selected_events':[{'event_id':'annotation:1','leads':['I','II']}],
                               'stt_report_use':[{'event_id':'annotation:1',**eligibility}]})
    before = dict(report=report, beat_editor={'revision':0}, annotations={'items':[{'id':1,'details':evidence}]},
                  workflow={'steps':{'stt':{'status':'done','actor':'mathematical-physician'}}},
                  events={'items':[{'event_id':'annotation:1','category':'ST','stt_review_state':'reviewed',
                                    'stt_report_eligibility':eligibility,'stt_event_evidence':evidence}]},
                  stt={'analysis':{'algorithm_version':'stt-screening-0.4.0-comprehensive-independent'}})
    before['stt']['analysis'].update(trends={'leads':{'II':[{'time_s':30,'st_level_units':-12.0}]}},quality={'coverage_pct':100})
    before['report_sections']={'st_evaluation':{'algorithm_version':'stt-screening-0.4.0-comprehensive-independent','candidate_count':6}}
    after=copy.deepcopy(before);after['stt']['analysis']['algorithm_version']='stt-screening-0.5.0-morphology-qualified'
    return before, after, dict(base_exe_sha256=BASE_PE_SHA,new_exe_sha256='a'*64)


def test_screening_upgrade_preserves_qualified_review_and_original_signature():
    before,after,package=baseline()
    proof=compare_api(before,after,package)
    assert proof['original_signature_retained_not_resigned']
    assert proof['retained_qualified_STT']==['annotation:1']
    assert proof['original_status']==proof['upgraded_status']=='reviewed'


@pytest.mark.parametrize('fault', ['basis-replaced','draft','reviewer-lost','version-changed','revision-changed',
                                  'conclusion-lost','signature-resigned','selection-lost','HRV-reset','workflow-reset',
                                  'record-stale','table-ineligible','text-ineligible','strip-ineligible',
                                  'annotation-rewritten','proof-relabelled','record-lost','beats-edited','algorithm-changed'])
def test_preservation_verdict_rejects_partial_or_false_upgrade(fault):
    before,after,package=baseline(); report=after['report']; event=after['events']['items'][0]
    if fault=='basis-replaced': report['current_analysis_basis']['engine_id']='new-engine'
    if fault=='draft': report['status']='draft'
    if fault=='reviewer-lost': report['reviewed_by']=''
    if fault=='version-changed': report['version']+=1
    if fault=='revision-changed': report['review_revision']+=1
    if fault=='conclusion-lost': report['conclusion']=''
    if fault=='signature-resigned': report['analysis_provenance']['signature']='new'
    if fault=='selection-lost': report['composition']['selected_events']=[]
    if fault=='HRV-reset': report['current_hrv_reference']['revision']=1
    if fault=='workflow-reset': after['workflow']['steps']['stt']['status']='stale'
    if fault=='record-stale': event['stt_review_state']='stale'
    if fault.endswith('-ineligible'): event['stt_report_eligibility'][fault.split('-')[0]]=False
    if fault=='annotation-rewritten': after['annotations']['items'][0]['details']['start_s']=61
    if fault=='proof-relabelled': event['stt_event_evidence']['end_s']=181
    if fault=='record-lost': after['events']['items']=[]
    if fault=='beats-edited': after['beat_editor']['revision']=1
    if fault=='algorithm-changed': after['stt']['analysis']['algorithm_version']='changed'
    with pytest.raises(AssertionError): compare_api(before,after,package)


def test_package_identity_requires_distinct_real_delivered_executables():
    release=dict(packaging_version='1.0.22',app_version=APP,software_version=APP,source_id='P01',source_data_bundled=False)
    previous=dict(packaging_version='1.0.21',app_version=BASE_APP,source_id='P01',source_data_bundled=False)
    shared=dict(core_version='performance-source',ui_version='new-ui')
    old=dict(core_version='old-source',ui_version='old-ui')
    proof=metadata_identity(release,shared,old_release=previous,old_shared=old,new_PE_sha256='a'*64,old_PE_sha256=BASE_PE_SHA)
    assert proof['packaging_version']=='1.0.22'
    with pytest.raises(AssertionError):
        metadata_identity(release,shared,old_release=previous,old_shared=old,new_PE_sha256=BASE_PE_SHA,old_PE_sha256=BASE_PE_SHA)


def test_current_package_requires_screening_policies_and_original21_is_verified(tmp_path):
    import json, shutil
    from tests.test_windows_doctor_build import minimal_package
    from scripts.windows_doctor_build import package_inventory, PackageError
    root=minimal_package(tmp_path)
    policy=root/'_internal/screening-refinement-compatibility.json'
    (root/'RELEASE.json').write_text(json.dumps({'packaging_version':'1.0.22'}))
    package_inventory(root)
    policy.unlink()
    with pytest.raises(PackageError,match='software allowlist'):
        package_inventory(root)
    (root/'_internal/screening-parent-engines.json').unlink()
    (root/'RELEASE.json').write_text(json.dumps({'packaging_version':'1.0.21'}))
    package_inventory(root)


def authored_baseline():
    before, _, _ = baseline()
    before['report']['composition']['selected_events'].append({'event_id':'candidate:1'})
    before['authored_HRV'] = dict(document={'exclusions':[{'id':'x-1','start_sample':28000,'end_sample':30000,'reason':'authored'}]},
        hrv_revision=1, document_stale=False, confirmation={'valid':True,'scope':{'window':0},'note':'original'},
        scope={'analysis_basis':'original'},document_scope={'analysis_basis':'original'})
    before['authored_RR_candidates'] = {'items':[{'id':1,'kind':'rr','status':'active','scope':{'analysis_basis':'original'}}]}
    before['authored_RR_events'] = {'items':[{'event_id':'candidate:1','evidence_ref':{'previous':{'sample_index':100},'terminal':{'sample_index':300}},
        'evidence_review':{'status':'confirmed','actor':'math-reviewer','presentations':[{'start_s':0,'end_s':7}]}}]}
    return before, copy.deepcopy(before)


def test_nonempty_authored_HRV_and_RR_scope_continuity_requires_real_entries():
    before, after = authored_baseline()
    proof = compare_nonempty_scopes(before, after)
    assert proof['HRV_exclusion_count']==proof['RR_active_candidates']==proof['RR_confirmed_report_pairs']==1


@pytest.mark.parametrize('fault',['HRV-empty','HRV-stale','HRV-unconfirmed','HRV-revision-reset','HRV-scope-changed',
                                  'RR-empty','RR-withdrawn','RR-pending','RR-presentation-lost','RR-removed-from-report'])
def test_nonempty_scope_verdict_rejects_empty_or_changed_authored_history(fault):
    before, after = authored_baseline()
    if fault=='HRV-empty': before['authored_HRV']['document']['exclusions']=[];after=copy.deepcopy(before)
    if fault=='HRV-stale': before['authored_HRV']['document_stale']=True;after=copy.deepcopy(before)
    if fault=='HRV-unconfirmed': before['authored_HRV']['confirmation']['valid']=False;after=copy.deepcopy(before)
    if fault=='HRV-revision-reset': after['authored_HRV']['hrv_revision']=0
    if fault=='HRV-scope-changed': after['authored_HRV']['scope']['analysis_basis']='new'
    if fault=='RR-empty': before['authored_RR_candidates']['items']=[];after=copy.deepcopy(before)
    if fault=='RR-withdrawn': after['authored_RR_candidates']['items'][0]['status']='withdrawn'
    if fault=='RR-pending': after['authored_RR_events']['items'][0]['evidence_review']['status']='pending'
    if fault=='RR-presentation-lost': after['authored_RR_events']['items'][0]['evidence_review']['presentations']=[]
    if fault=='RR-removed-from-report': after['report']['composition']['selected_events']=[{'event_id':'annotation:1'}]
    with pytest.raises(AssertionError): compare_nonempty_scopes(before, after)


@pytest.mark.parametrize('fault',['measurement-trend','quality','signed-screening-presentation','stale-revived'])
def test_screening_verdict_rejects_changed_measurement_or_originally_stale_revival(fault):
    before,after,package=baseline()
    if fault=='measurement-trend':after['stt']['analysis']['trends']['leads']['II'][0]['st_level_units']=-13
    if fault=='quality':after['stt']['analysis']['quality']['coverage_pct']=99
    if fault=='signed-screening-presentation':after['report_sections']['st_evaluation']['candidate_count']=0
    if fault=='stale-revived':
        stale=copy.deepcopy(before['events']['items'][0]);stale.update(event_id='annotation:2',stt_review_state='stale')
        before['events']['items'].append(stale);after['events']['items'].append({**stale,'stt_review_state':'reviewed'})
    with pytest.raises(AssertionError):compare_api(before,after,package)


def test_actual_pdf_content_stream_identity_ignores_metadata_but_detects_changed_text():
    from io import BytesIO
    from reportlab.pdfgen import canvas
    from scripts.verify_windows_screening_quality import pdf_content_identity
    def pdf(text):
        stream=BytesIO();c=canvas.Canvas(stream,pageCompression=1)
        c.drawString(20,20,text);c.save();return stream.getvalue()
    first=pdf('same physician text')
    second=pdf('same physician text')
    assert pdf_content_identity(first)==pdf_content_identity(second)
    assert pdf_content_identity(first)!=pdf_content_identity(pdf('changed physician text'))


def test_unselected_original_stale_records_are_included_in_upgrade_verdict():
    before,after,package=baseline()
    stale={'event_id':'annotation:2','category':'ST','stt_review_state':'stale'}
    before['all_ST_events']={'items':[copy.deepcopy(before['events']['items'][0]),stale]}
    after['all_ST_events']=copy.deepcopy(before['all_ST_events'])
    assert len(before['events']['items'])==1
    assert compare_api(before,after,package)['originally_stale_records_checked']==1


@pytest.mark.parametrize('fault',['revived','lost'])
def test_unselected_original_stale_revival_or_deletion_is_rejected(fault):
    before,after,package=baseline()
    stale={'event_id':'annotation:2','category':'ST','stt_review_state':'stale'}
    before['all_ST_events']={'items':[copy.deepcopy(before['events']['items'][0]),stale]}
    after['all_ST_events']=copy.deepcopy(before['all_ST_events'])
    if fault=='revived':after['all_ST_events']['items'][1]['stt_review_state']='reviewed'
    else:after['all_ST_events']['items'].pop()
    with pytest.raises(AssertionError,match='Originally stale'):
        compare_api(before,after,package)


@pytest.mark.parametrize('fault',['head','status','conclusion'])
def test_baseline_downloader_rejects_wrong_acceptance_run_before_download(tmp_path,monkeypatch,fault):
    from types import SimpleNamespace
    from scripts import prepare_windows22_baseline as prepare
    run={'head_sha':prepare.HEAD,'status':'completed','conclusion':'success'}
    run[fault if fault!='head' else 'head_sha']='incorrect'
    monkeypatch.setattr(prepare,'api',lambda *_:run)
    monkeypatch.setattr(prepare,'download',lambda *_:pytest.fail('Wrong accepted run must not download'))
    output=tmp_path/'baseline'
    with pytest.raises(AssertionError):prepare.prepare(SimpleNamespace(output=output))
    assert not output.exists()


@pytest.mark.parametrize('fault',['expired','name','size','digest','run','head'])
def test_baseline_downloader_rejects_changed_original_artifact(tmp_path,monkeypatch,fault):
    from types import SimpleNamespace
    from scripts import prepare_windows22_baseline as prepare
    wanted=prepare.ARTIFACTS['p01']
    row=dict(id=wanted['id'],expired=False,name=wanted['name'],size_in_bytes=wanted['bytes'],
             digest='sha256:'+wanted['sha256'],workflow_run={'id':prepare.RUN,'head_sha':prepare.HEAD})
    if fault=='expired':row['expired']=True
    elif fault=='size':row['size_in_bytes']+=1
    elif fault=='run':row['workflow_run']['id']+=1
    elif fault=='head':row['workflow_run']['head_sha']='a'*40
    else:row[fault]='incorrect'
    def api(repo,path):
        assert repo==prepare.REPO
        if path.endswith('/artifacts'):return {'artifacts':[row]}
        return {'head_sha':prepare.HEAD,'status':'completed','conclusion':'success'}
    monkeypatch.setattr(prepare,'api',api)
    monkeypatch.setattr(prepare,'download',lambda *_:pytest.fail('Changed original artifact must not download'))
    with pytest.raises(AssertionError):prepare.prepare(SimpleNamespace(output=tmp_path/'baseline'))


def test_baseline_math_extraction_rejects_path_traversal(tmp_path,monkeypatch):
    import zipfile
    from scripts import prepare_windows22_baseline as prepare
    archive=tmp_path/'math.zip'
    with zipfile.ZipFile(archive,'w') as z:
        for name in ['M01/data','M01/../outside','M01/a','M01/b','M01/c']:z.writestr(name,'math')
    monkeypatch.setattr(prepare,'validate_source',lambda *_:pytest.fail('Unsafe archive must not validate'))
    with pytest.raises(AssertionError):prepare.extract_math(archive,tmp_path/'source')
    assert not (tmp_path/'outside').exists()


def test_cold_restart_requires_persisted_certificate_hit_without_full_recomputation():
    from scripts.verify_windows_screening_quality import require_cached_restart
    first={'continuity_kind':'stt_screening_refinement','full_verification_attempts':1,'verified_certificate_reuses':0}
    restarted={'continuity_kind':'stt_screening_refinement','full_verification_attempts':0,'verified_certificate_reuses':1}
    proof=require_cached_restart(first,restarted)
    assert proof['cold_restart_used_existing_proof_without_full_recomputation']


@pytest.mark.parametrize('fault',['first-not-verified','no-reuse','recomputed','wrong-kind'])
def test_cold_restart_diagnostics_refuse_unproven_or_recomputed_cache(fault):
    from scripts.verify_windows_screening_quality import require_cached_restart
    first={'continuity_kind':'stt_screening_refinement','full_verification_attempts':1,'verified_certificate_reuses':0}
    restarted={'continuity_kind':'stt_screening_refinement','full_verification_attempts':0,'verified_certificate_reuses':1}
    if fault=='first-not-verified':first['full_verification_attempts']=0
    if fault=='no-reuse':restarted['verified_certificate_reuses']=0
    if fault=='recomputed':restarted['full_verification_attempts']=1
    if fault=='wrong-kind':restarted['continuity_kind']='performance'
    with pytest.raises(AssertionError):require_cached_restart(first,restarted)


def restart_snapshot():
    return {'recovery_epoch':'original-epoch','tables':{
        'annotations':{'columns':['id','created_at','uuid'],'rows':[{'id':1,'created_at':'old-reviewed-time','uuid':'original'}]},
        'audit_log':{'columns':['id','case_id','actor','action','detail','created_at'],'rows':[
            {'id':1,'case_id':'P01','actor':'original-actor','action':'analysis.screening_refinement_verified','detail':'original-proof-hash','created_at':'first-migration-time'},
            {'id':2,'case_id':'P01','actor':'original-actor','action':'case.open','detail':'','created_at':'original-open-time'}]},
        'analysis_implementation_compatibility':{'columns':['case_id','certificate','created_at'],
            'rows':[{'case_id':'P01','certificate':'original-canonical-certificate','created_at':'first-registration'}]}}}


def restart_pair():
    from datetime import datetime,timezone
    before=restart_snapshot();after=copy.deepcopy(before)
    after['tables']['audit_log']['rows'].append(dict(id=3,case_id='P01',actor='original-actor',
        action='case.open',detail='',created_at='2026-11-13T03:00:01+00:00'))
    context=dict(case_id='P01',started_at=datetime(2026,11,13,3,0,0,tzinfo=timezone.utc),
                 finished_at=datetime(2026,11,13,3,0,2,tzinfo=timezone.utc))
    return before,after,context


def test_cold_restart_compares_full_database_while_naming_only_registration_timestamp_exception():
    from scripts.verify_windows_screening_quality import compare_restart_database
    before,after,context=restart_pair()
    after['tables']['analysis_implementation_compatibility']['rows'][0]['created_at']='second-registration'
    proof=compare_restart_database(before,after,**context)
    assert proof['all_clinical_rows_and_original_complete_audit_exact']
    assert proof['expected_visible_reopen_audit']==after['tables']['audit_log']['rows'][-1]
    assert proof['excluded_nonclinical_registration_fields']==['analysis_implementation_compatibility.created_at']


@pytest.mark.parametrize('fault',['clinical-time','clinical-uuid','audit-time','audit-proof','certificate','extra-certificate','missing-table','epoch'])
def test_cold_restart_rejects_any_clinical_audit_or_certificate_change(fault):
    from scripts.verify_windows_screening_quality import compare_restart_database
    before,after,context=restart_pair();tables=after['tables']
    if fault=='clinical-time':tables['annotations']['rows'][0]['created_at']='rewritten-time'
    if fault=='clinical-uuid':tables['annotations']['rows'][0]['uuid']='rewritten'
    if fault=='audit-time':tables['audit_log']['rows'][0]['created_at']='new-time'
    if fault=='audit-proof':tables['audit_log']['rows'][0]['detail']='new-proof'
    if fault=='certificate':tables['analysis_implementation_compatibility']['rows'][0]['certificate']='new-proof'
    if fault=='extra-certificate':tables['analysis_implementation_compatibility']['rows'].append(dict(tables['analysis_implementation_compatibility']['rows'][0]))
    if fault=='missing-table':tables.pop('annotations')
    if fault=='epoch':after['recovery_epoch']='new-epoch'
    with pytest.raises(AssertionError):compare_restart_database(before,after,**context)


@pytest.mark.parametrize('fault',['absent','two-opens','new-proof','wrong-case','wrong-actor','nonempty-detail','early-time','late-time','no-timezone'])
def test_cold_restart_allows_only_its_one_actual_case_open_append(fault):
    from scripts.verify_windows_screening_quality import compare_restart_database
    before,after,context=restart_pair();audit=after['tables']['audit_log']['rows'];appended=audit[-1]
    if fault=='absent':audit.pop()
    if fault=='two-opens':audit.append({**appended,'id':4})
    if fault=='new-proof':appended['action']='analysis.screening_refinement_verified'
    if fault=='wrong-case':appended['case_id']='other-case'
    if fault=='wrong-actor':appended['actor']='different-actor'
    if fault=='nonempty-detail':appended['detail']='unexpected'
    if fault=='early-time':appended['created_at']='2026-11-13T02:59:59+00:00'
    if fault=='late-time':appended['created_at']='2026-11-13T03:00:03+00:00'
    if fault=='no-timezone':appended['created_at']='2026-11-13T03:00:01'
    with pytest.raises(AssertionError):compare_restart_database(before,after,**context)


def test_original21_verifier_remains_exact_accepted_source_and_isolates_old_algorithm():
    import ast
    from hashlib import sha256
    from scripts import verify_screening_legacy_ui as legacy
    from scripts import verify_windows_screening_quality as controller
    path=Path(legacy.__file__)
    assert sha256(path.read_bytes()).hexdigest()=='e801afe1503ee970a921960fa0c30188d0b7306e25ea3fad26fef3390244188c'
    source=path.read_text()
    assert 'stt-screening-0.4.0-comprehensive-independent' in source
    assert 'stt-screening-0.5.0-morphology-qualified' not in source
    tree=ast.parse(Path(controller.__file__).read_text())
    aliases={alias.asname:node.module for node in ast.walk(tree) if isinstance(node,ast.ImportFrom) for alias in node.names if alias.asname}
    assert aliases['old_stt_flow']=='scripts.verify_screening_legacy_ui'
    assert aliases['stt_flow']=='scripts.verify_screening_quality_ui'


def test_current_screening_verifier_keeps_final_V6_positive_and_V2_negative_assertions():
    from scripts import verify_screening_quality_ui as quality
    root=Path(quality.__file__).parent
    current=Path(quality.__file__).read_bytes()
    assert current==(root/'verify_stt_comprehensive_ui.py').read_bytes()
    assert b'stt-screening-0.5.0-morphology-qualified' in current
    assert b"('t_persistent_inversion', 'V6')" in current
    assert b'Variable lead negative background is not an abnormal event for sign alone' in current


def test_failed_start_diagnostics_keep_real_popup_API_session_and_source_boundary_without_credentials(tmp_path):
    import asyncio,json
    from types import SimpleNamespace
    from scripts.verify_windows_screening_quality import start_failure_diagnostics
    from scripts.verify_windows_doctor_browser import safe_error
    secret='1234567890abcdef'*4
    source=tmp_path/'original-math';source.mkdir()
    (source/'source-manifest.json').write_text(json.dumps({'kind':'mathematical_deidentified_fixture','patient_inputs_read':False}))
    home=tmp_path/'home';(home/'runtime').mkdir(parents=True)
    (home/'catalog.json').write_text(json.dumps({'profile':'profile','selected_workspace':'owned','workspaces':[{'id':'owned'}]}))
    (home/'source-selection.json').write_text(json.dumps({'profile':'profile','selected_dataset':'P01','data_root':str(source)}))
    (home/'runtime/owned.json').write_text(json.dumps({'profile':'profile','role':'workspace','pid':12,'birth':'birth','port':44001,'workspace_id':'owned','token':secret}))
    class Reply:
        def __init__(self,status,body):self.status=status;self.body=body
        async def json(self):return self.body
    class Requests:
        async def get(self,url,**kwargs):
            if url.endswith('/_doctor/health'):
                assert kwargs['headers']=={'X-Doctor-Control':secret}
                return Reply(200,{'profile':'profile','role':'workspace','pid':12,'token':secret})
            if url.endswith('/api/health'):return Reply(200,{'version':APP,'case_count':1,'screening_continuity':{'verified_certificate_reuses':1,'full_verification_attempts':0}})
            assert url.endswith('/api/dashboard')
            return Reply(409,{'error':'exact-snapshot conflict','code':'analysis_changed'})
    class Page:
        url='http://127.0.0.1:44001/_doctor/open?token='+secret
        def is_closed(self):return False
        async def evaluate(self,_):return {'app':{'page':'dashboard','dashboard_status':'error','dashboard_error':'API 409'},'visible_text':'actual popup: API 409'}
        async def screenshot(self,*,path,full_page):Path(path).write_bytes(b'test-screenshot')
    class Context:
        pages=[Page()];request=Requests()
        async def cookies(self):return [{'name':'doctor_'+secret[:20],'value':secret},{'name':'CardioInsightDoctorEval-owned','value':'session-secret'}]
    result=asyncio.run(start_failure_diagnostics(Context(),home,tmp_path/'diagnostics',sanitize=safe_error,
        expected_source=source,expected_workspace='owned'))
    text= json.dumps(result)
    assert secret not in text and secret[:20] not in text and 'session-secret' not in text
    assert result['pages'][0]['path']=='/_doctor/open'
    assert result['pages'][0]['state']['app']['dashboard_status']=='error'
    assert result['runtime'][0]['control_health_http_status']==200
    assert result['runtime'][0]['apis']['dashboard']['http_status']==409
    assert result['session_cookie_categories']=={'doctor-control':1,'application-session':1}
    assert result['catalog']['selected_matches_requested'] is True
    assert result['source_selection']['same_original_mathematical_source'] is True
    assert (tmp_path/'diagnostics/start-diagnostics.json').is_file()


def test_owned_process_inventory_uses_exact_executable_and_never_records_command_credentials(tmp_path,monkeypatch):
    import sys
    from types import SimpleNamespace
    from scripts.verify_windows_screening_quality import owned_processes
    exe=tmp_path/'owned/CardioInsightDoctorEval.exe';exe.parent.mkdir();exe.write_bytes(b'owned-test')
    entries=[SimpleNamespace(info={'pid':4,'ppid':3,'exe':str(exe),'create_time':10.0,'cmdline':'must-not-be-exposed'}),
             SimpleNamespace(info={'pid':5,'ppid':3,'exe':str(tmp_path/'other/CardioInsightDoctorEval.exe'),'create_time':11.0})]
    psutil=SimpleNamespace(process_iter=lambda _:entries,NoSuchProcess=ProcessLookupError,AccessDenied=PermissionError)
    monkeypatch.setitem(sys.modules,'psutil',psutil)
    assert owned_processes(exe)==[{'pid':4,'parent_pid':3,'birth':10.0}]


def test_old_candidate_probe_reaches_validator_only_with_real_native_UI_write_context():
    import threading
    from flask import Flask,jsonify,request,abort
    import win_doctor_eval as doctor
    from scripts.verify_windows_screening_quality import annotation_probe_headers
    context=dict(profile=doctor.PROFILE,role='workspace',pid=1,birth='math',token='a'*64,
                 cookie_name='doctor_'+'a'*20,port=45555,software_version=APP,packaging_version='1.0.22',shutdown=threading.Event())
    app=Flask('mathematical-native-probe-boundary');doctor._install_guards(app,context)
    reached=[]
    @app.post('/api/cases/math/annotations')
    def annotations():
        if request.headers.get('X-CardioInsight-Request')!='1' or request.headers.get('X-CardioInsight-Workspace')!='math-epoch':abort(403)
        reached.append(request.get_json())
        return jsonify(error='deliberately obsolete mathematical candidate',code='report_conflict'),409
    client=app.test_client();origin='http://127.0.0.1:45555'
    assert client.get('/_doctor/open?token='+'a'*64,base_url=origin).status_code==303
    # APIRequestContext's bare POST cannot reach the candidate version check.
    assert client.post('/api/cases/math/annotations',base_url=origin,json={'old':True}).status_code==403
    assert reached==[]
    headers=annotation_probe_headers('math-epoch');assert 'Origin' not in headers
    headers['Origin']=origin  # The browser supplies this, never the helper.
    response=client.post('/api/cases/math/annotations',base_url=origin,json={'old':True},headers=headers)
    assert response.status_code==409 and reached==[{'old':True}]


def test_annotation_attempt_uses_browser_fetch_and_preserves_rejection_response():
    import asyncio
    from scripts.verify_windows_screening_quality import browser_annotation_attempt
    calls=[]
    class Page:
        async def evaluate(self,script,args=None):
            if args is None:return 'actual-browser-workspace-epoch'
            calls.append((script,args))
            return {'status':409,'payload':{'error':'obsolete candidate','code':'report_conflict'}}
    response=asyncio.run(browser_annotation_attempt(Page(),'math-case',{'deliberately_old':True}))
    assert response=={'status':409,'payload':{'error':'obsolete candidate','code':'report_conflict'}}
    script,args=calls[0]
    assert "fetch('/api/cases/'" in script and "credentials:'same-origin'" in script
    assert args['case_id']=='math-case' and args['body']=={'deliberately_old':True}
    assert args['headers']['X-CardioInsight-Request']=='1'
    assert args['headers']['X-CardioInsight-Workspace']=='actual-browser-workspace-epoch'
    assert 'Origin' not in args['headers']


def policy_pair_copy(tmp_path):
    import shutil
    from scripts import verify_windows_screening_quality as controller
    source=tmp_path/'frozen-source';packaged=tmp_path/'actual-package';source.mkdir();packaged.mkdir()
    for name in ('performance-compatibility.json','performance-parent-engines.json','screening-refinement-compatibility.json','screening-parent-engines.json'):
        shutil.copyfile(controller.ROOT/name,source/name)
        shutil.copyfile(controller.ROOT/name,packaged/name)
    return source,packaged


def test_C34_requires_both_independent_policy_and_parent_sets(tmp_path):
    from scripts.verify_windows_screening_quality import verify_policy_pair,PERFORMANCE_PARENT,SCREENING_PARENTS
    source,packaged=policy_pair_copy(tmp_path)
    result=verify_policy_pair(source,packaged)
    assert APP=='0.12.34-stt-candidate-performance.20261113'
    assert result['performance']['parent_engine_ids']==[PERFORMANCE_PARENT]
    assert result['screening']['parent_engine_ids']==sorted(SCREENING_PARENTS)
    assert PERFORMANCE_PARENT not in SCREENING_PARENTS


def test_performance_parent_build_input_is_not_required_when_actual_policy_contains_exact_manifest(tmp_path):
    from scripts.verify_windows_screening_quality import verify_policy_pair,PERFORMANCE_PARENT
    source,packaged=policy_pair_copy(tmp_path)
    (packaged/'performance-parent-engines.json').unlink()
    result=verify_policy_pair(source,packaged)
    assert result['performance']['parent_engine_ids']==[PERFORMANCE_PARENT]
    assert result['performance']['actual_parent_manifests_verified_from']=='packaged-policy.parent_engines'
    assert result['performance']['separate_parent_resource_present'] is False
    assert result['screening']['separate_parent_resource_present'] is True


def test_missing_separate_parent_input_never_allows_tampered_actual_performance_policy(tmp_path):
    import json
    from scripts.verify_windows_screening_quality import verify_policy_pair
    source,packaged=policy_pair_copy(tmp_path)
    (packaged/'performance-parent-engines.json').unlink()
    path=packaged/'performance-compatibility.json';value=json.loads(path.read_text())
    value['parent_engines'][0]['app_version']='unapproved-parent'
    path.write_text(json.dumps(value))
    with pytest.raises(AssertionError):verify_policy_pair(source,packaged)


@pytest.mark.parametrize('fault',['packaged-performance-policy','packaged-screening-parents','performance-add-fbaa','screening-alias-performance','unknown-performance-parent'])
def test_dual_policy_verdict_rejects_missing_mismatched_or_broadened_authority(tmp_path,fault):
    import json
    from scripts.verify_windows_screening_quality import verify_policy_pair
    source,packaged=policy_pair_copy(tmp_path)
    if fault=='packaged-performance-policy':
        path=packaged/'performance-compatibility.json';value=json.loads(path.read_text());value['schema']='different';path.write_text(json.dumps(value))
    elif fault=='packaged-screening-parents':
        (packaged/'screening-parent-engines.json').write_text('[]')
    else:
        for root in (source,packaged):
            name='screening-refinement-compatibility.json' if fault=='screening-alias-performance' else 'performance-compatibility.json'
            path=root/name;value=json.loads(path.read_text())
            if fault=='performance-add-fbaa':value['parent_engine_ids'].append('f1a6856075c041df55f179ddd6b9cf959763ad9bd66838b6ed04f23f8f16025e')
            elif fault=='screening-alias-performance':value['schema']='performance-evidence-continuity-v1'
            else:value['parent_engine_ids']=['a'*64]
            path.write_text(json.dumps(value))
    with pytest.raises(AssertionError):verify_policy_pair(source,packaged)
