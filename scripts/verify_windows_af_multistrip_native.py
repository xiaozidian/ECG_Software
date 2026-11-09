"""Fresh Windows17 PE acceptance and immutable15 ->17 same-workspace upgrade.

Only independent mathematical sources and actual installed system Edge are used.
The old15 approval is created through visible controls. Its old measurement
oracle is extracted from that exact old PE, never replaced by current code.
"""
from __future__ import annotations
import argparse
import asyncio
from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import platform
import re
import sys
import tempfile
import types
from urllib.parse import urlencode, urlsplit

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'scripts')]
OLD_APP='0.12.29-stt-independent.20261104'
NEW_ALGORITHM='stt-screening-0.4.0-comprehensive-independent'
OLD_P01_SHA='e4b05f506a363ae89ee44ab44a9540dbe640848a4e5178a406fc8a023d952462'
LEGACY_DRIVER_SHA='e4162d4f65ec4efec707d2ab6843fe8ade874101769e572f4c3ffc7a1995d422'
READONLY_POSTS={'open','scatter-selection','waveform-strips','event-waveforms','waveform-density','advanced-analysis','rr-locate','stt-range'}


def require(value,message):
    if not value:raise AssertionError(message)


def fingerprint(value):
    return sha256(json.dumps(value,sort_keys=True,ensure_ascii=False,separators=(',',':'),allow_nan=False).encode()).hexdigest()


def exact(left,right,message):require(fingerprint(left)==fingerprint(right),message)


def files(root):return {p.relative_to(root).as_posix():sha256(p.read_bytes()).hexdigest() for p in root.rglob('*') if p.is_file()}


def verify_original15_manifest(root):
    """Old original assets use their immutable manifest, not the new81 list."""
    declared=json.loads((root/'CONTENTS.json').read_text(encoding='utf-8'))
    require(declared['schema_version']==1 and declared['algorithm']=='sha256' and declared['package_kind']=='software_only','Old original manifest contract mismatch')
    actual={p.relative_to(root).as_posix():dict(size_bytes=p.stat().st_size,sha256=sha256(p.read_bytes()).hexdigest())
            for p in root.rglob('*') if p.is_file() and p.name not in ('CONTENTS.json','SHA256SUMS.txt')}
    require(not any(n.startswith('Sources/') for n in actual),'Old15 source-free software unexpectedly bundles source')
    exact(actual,declared['files'],'Original15 full content manifest differs')
    actual['CONTENTS.json']=dict(sha256=sha256((root/'CONTENTS.json').read_bytes()).hexdigest())
    expected=''.join(row['sha256']+'  '+name+'\n' for name,row in sorted(actual.items()))
    require((root/'SHA256SUMS.txt').read_text(encoding='utf-8')==expected,'Original15 SHA sidecar inventory differs')


def load_old_oracles(exe):
    """Load the complete old measurement dependency closure from the old PE.

    No current ecg_core config, source guard, status helper or algorithm is
    aliased into this namespace. A missing old dependency fails closed.
    """
    import dis
    import marshal
    from PyInstaller.archive.readers import CArchiveReader
    exe=Path(exe).resolve();old_exe_sha=sha256(exe.read_bytes()).hexdigest()
    require(old_exe_sha=='f5283fc6a670e4d6dd9553797035458f31d0ea059ef81516f06fcc3ea9c24a73','The old measurement oracle requires the exact immutable15 executable')
    reader=CArchiveReader(exe)
    pyzs=[n for n,row in reader.toc.items() if row[-1]=='z'];require(len(pyzs)==1,'Old PE must have one actual embedded PYZ')
    pyz=reader.open_embedded_archive(pyzs[0])
    name='_actual_immutable_windows15';internal=exe.parent/'_internal'
    for key in list(sys.modules):
        if key==name or key.startswith(name+'.'):del sys.modules[key]
    package=types.ModuleType(name);package.__package__=name;package.__path__=[str(internal/'ecg_core')]
    package.__file__=str(internal/'ecg_core/__init__.py');sys.modules[name]=package
    dependencies=('core_contract','config','review_workflow','source_identity','evaluation_status','stt_records','stt','stt_range')
    codes={}
    for short in ('__init__',*dependencies):
        original='ecg_core' if short=='__init__' else 'ecg_core.'+short
        require(original in pyz.toc,'Old actual PE is missing dependency '+original)
        code=pyz.extract(original);require(isinstance(code,types.CodeType),'Old PYZ dependency is not executable code')
        codes[short]=code
    def imports(code):
        instructions=list(dis.get_instructions(code));found=set()
        for index,item in enumerate(instructions):
            if item.opname=='IMPORT_NAME':
                require(item.argval!='ecg_core' and not item.argval.startswith('ecg_core.'),'Old namespace attempted a current ecg_core absolute import')
                if index>=2 and instructions[index-2].opname=='LOAD_CONST' and type(instructions[index-2].argval) is int and instructions[index-2].argval>0:
                    require(instructions[index-2].argval==1 and item.argval,'Unsupported old relative import')
                    found.add(item.argval.split('.')[0])
        for value in code.co_consts:
            if isinstance(value,types.CodeType):found.update(imports(value))
        return found
    closure={short:sorted(imports(code)) for short,code in codes.items()}
    require(set().union(*(set(rows) for rows in closure.values()))<=set(dependencies),'An old relative dependency is missing from the authenticated closure')
    result={};origins={}
    def execute(short):
        code=codes[short];original='ecg_core' if short=='__init__' else 'ecg_core.'+short
        module=package if short=='__init__' else types.ModuleType(name+'.'+short)
        module.__package__=name
        module.__file__=str(internal/'ecg_core'/('__init__.py' if short=='__init__' else short+'.py'))
        sys.modules[module.__name__]=module
        if short!='__init__':setattr(package,short,module)
        code_sha=sha256(marshal.dumps(code)).hexdigest()
        module.__old_PE_origin__=dict(original_module=original,old_exe_sha256=old_exe_sha,code_sha256=code_sha,
                                      filename=module.__file__,relative_dependencies=closure[short])
        exec(code,module.__dict__);origins[original]=module.__old_PE_origin__.copy()
        if short!='__init__':result[short]=module
    # The real old package initializer imports config; load its own constants
    # first, then execute the original initializer and its full ST closure.
    execute('core_contract');execute('config');execute('__init__')
    for short in dependencies[2:]:execute(short)
    require(result['config'].APP_VERSION==OLD_APP and package.APP_VERSION==OLD_APP,'Old oracle config was replaced by current config')
    require(Path(result['config'].resource_root())==internal,'Old oracle assets no longer resolve inside the original bundle')
    require(result['source_identity'].ReportConflict is result['review_workflow'].ReportConflict,'Old source guard imported current review code')
    require(result['stt'].ALGORITHM_VERSION=='stt-screening-0.3.2-independent-rhythm','The authentic old15 oracle was replaced by current code')
    require(result['stt_range'].PROFILE_ID=='raw-200hz-fixed16s-st-perbeat-mean-v2','Old actual range method is wrong')
    require(result['stt_records'].METHOD=='stt-hospital-review-v2','Old actual reviewed-method code is wrong')
    require(result['stt_range']._block_measurement is result['stt']._block_measurement,'Old range imported a new rather than old measurement function')
    require(result['stt'].source_read is result['source_identity'].source_read and
            result['stt_range'].source_read is result['source_identity'].source_read,'Old measurements imported a current source guard')
    proof=dict(status='authentic_old15_dependency_closure_loaded_not_a_native_migration_verdict',old_exe_sha256=old_exe_sha,
               namespace=name,modules=origins,module_count=len(origins),old_resource_root=str(internal),
               algorithm_version=result['stt'].ALGORITHM_VERSION,range_profile=result['stt_range'].PROFILE_ID,
               method=result['stt_records'].METHOD,current_ecg_core_modules_aliased=False)
    destination=os.environ.get('ECG_OLD_ORACLE_PROOF_PATH')
    if destination:
        path=Path(destination);require(not path.exists(),'Preserve original old-oracle dependency evidence')
        path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(proof,ensure_ascii=False,indent=2)+'\n')
    print('ACTUAL_OLD15_ORACLE_DEPENDENCIES_JSON='+json.dumps(proof,ensure_ascii=False))
    return result


def program_identity(old,new):
    from ecg_core.config import APP_VERSION
    from scripts.verify_public_release import verify
    from scripts.shared_source import snapshot
    release=json.loads((new/'RELEASE.json').read_text(encoding='utf-8-sig'))
    shared=json.loads((new/'_internal/shared-source-build.json').read_text(encoding='utf-8-sig'))
    require(release['packaging_version']=='1.0.17' and release['app_version']==release['software_version']==APP_VERSION,'New actual package version mismatch')
    require(not release.get('ui_repack_only',False) and not release.get('binary_reused_without_rebuild',False),'Fresh algorithm release must not reuse the old EXE')
    require(release['production_source_identity']==verify(ROOT),'New package production manifest differs from the committed frozen source')
    require(shared==snapshot(ROOT)[0],'New package shared source stamp differs from the committed frozen source')
    require(release['source_id']=='P01' and release['source_data_bundled'] is False,'Native fixture requires source-free P01 software')
    assets={n:row['sha256'] for n,row in shared['files'].items() if row['component']=='ui'}
    require(assets and all(sha256((new/'_internal'/n).read_bytes()).hexdigest()==h for n,h in assets.items()),'Actual packaged UI differs from declared complete UI files')
    proof=dict(packaging_version='1.0.17',application_version=APP_VERSION,new_exe_sha256=sha256((new/'CardioInsightDoctorEval.exe').read_bytes()).hexdigest(),
               source_commit=release['source_commit'],production_source_identity=release['production_source_identity'],shared_source_fingerprint=shared['source_fingerprint'],packaged_UI_files=len(assets))
    if old is not None:
        previous=json.loads((old/'RELEASE.json').read_text(encoding='utf-8-sig'))
        old_shared=json.loads((old/'_internal/shared-source-build.json').read_text(encoding='utf-8-sig'))
        require(previous['packaging_version']=='1.0.15' and previous['app_version']==OLD_APP,'Exact accepted15 software required')
        require(previous['source_id']=='P01' and previous['source_data_bundled'] is False,'Old package was not source-free P01')
        proof.update(base_exe_sha256=sha256((old/'CardioInsightDoctorEval.exe').read_bytes()).hexdigest(),base_packaging_version='1.0.15',base_app_version=OLD_APP)
        require(proof['base_exe_sha256']!=proof['new_exe_sha256'],'New17 incorrectly reused old15 EXE')
        require(old_shared['core_version']!=shared['core_version'],'Algorithm upgrade did not change shared core identity')
    return proof



def bind_acceptance_provenance(package, *, source_compile_commit, producer_run_id,
                               controller_commit, acceptance_run_id):
    """Bind a later native controller to an immutable, genuinely compiled PE.

    This changes only acceptance provenance; RELEASE.json and all original
    software/source ZIPs keep the producer commit and original byte hashes.
    """
    require(re.fullmatch(r'[0-9a-f]{40}',str(source_compile_commit)) is not None,
            'Source compile commit must be an exact Git commit')
    require(re.fullmatch(r'[0-9a-f]{40}',str(controller_commit)) is not None,
            'Native controller commit must be an exact Git commit')
    require(package['source_commit']==source_compile_commit,
            'Actual original PE source commit differs from the compiled producer')
    require(source_compile_commit!=controller_commit,
            'Native continuation must distinguish source compilation from acceptance')
    require(type(producer_run_id) is int and producer_run_id>0 and
            type(acceptance_run_id) is int and acceptance_run_id>0 and
            producer_run_id!=acceptance_run_id,'Native acceptance run must be distinct from the producer')
    return dict(source_compile_commit=source_compile_commit,producer_run_id=producer_run_id,
                controller_commit=controller_commit,acceptance_run_id=acceptance_run_id,
                original_PE_recompiled=False,original_delivery_ZIPs_repacked=False)


def compare_api(before,after,package):
    from verify_windows_stt_independent_upgrade import current_basis,invalidated_composition
    old,new=before['report'],after['report'];b0,b1=old['current_analysis_basis'],new['current_analysis_basis']
    current_basis(b0,OLD_APP,package['base_exe_sha256']);current_basis(b1,package['application_version'],package['new_exe_sha256'])
    require(b0['engine_id']!=b1['engine_id'] and b0['digest']!=b1['digest'],'Actual new engine did not get a new analysis basis')
    exact(b0['inputs'],b1['inputs'],'Mathematical raw source changed during upgrade')
    require(old['status']=='reviewed' and old['reviewed_by'],'Old baseline was not visibly reviewed')
    require(new['status']=='draft' and not new['reviewed_by'] and new['version']==old['version']+1,'New engine must invalidate old report once, without claiming new approval')
    require(new['review_revision']==old['review_revision']+1,'Unexpected current review revision')
    allowed={'current_analysis_basis','current_hrv_reference','review_revision','reviewed_by','status','updated_at','version','composition'}
    exact({k:v for k,v in old.items() if k not in allowed},{k:v for k,v in new.items() if k not in allowed},'Historical proof, conclusion or report identity changed')
    exact(new['composition'],invalidated_composition(old['composition']),'Old selections, curation, original text or unrelated composition changed')
    exact(new['analysis_provenance'],old['analysis_provenance'],'Old clinical approval was re-signed by new algorithm')
    require(new['analysis_provenance']['basis']['digest']==b0['digest']!=b1['digest'],'Historical signed proof silently adopted new engine')
    require(after['basis']['analysis_basis']==b1['digest'],'Current linked read basis differs')
    require(before['beat_editor']['revision']==after['beat_editor']['revision'],'Upgrade edited source beats')
    for key in ('annotations',):
        def stored(rows):return [{k:v for k,v in r.items() if k!='stt_review_receipt'} for r in rows['items']]
        exact(stored(before[key]),stored(after[key]),'Old stored annotation/protocol/wording was rewritten')
    prior={e['event_id']:e for e in before['events']['items']};current={e['event_id']:e for e in after['events']['items']}
    st=[eid for eid,e in prior.items() if e['category']=='ST'];require(len(st)==1,'Expected one actually reviewed old scoped ST proof')
    for eid in st:
        require(eid in current,'Historical reviewed ST record disappeared')
        e=current[eid]
        require(e['stt_review_state']=='stale' and e['stt_report_eligibility']==dict(table=False,text=False,strip=False),'Old source-basis ST proof was silently promoted as new-method evidence')
        exact(e['stt_event_evidence'],prior[eid]['stt_event_evidence'],'Old v2 evidence was relabelled as a new subtype or method')
    analysis=after['stt']['analysis']
    require(analysis['algorithm_version']==NEW_ALGORITHM and analysis['rhythm_policy']=='independent_of_AF_AFL_reviews' and analysis['exclusions']['intervals']==[],'New actual PE is not executing independent comprehensive ST-T')
    return dict(status='passed',old_engine_id=b0['engine_id'],new_engine_id=b1['engine_id'],old_report_version=old['version'],new_report_version=new['version'],
                selected_strips_preserved=len(old['composition']['selected_events']),old_provenance_preserved_not_resigned=True,old_ST_records_visible_stale=st,
                new_algorithm=NEW_ALGORITHM)


async def run(args,result):
    require(os.name=='nt' and platform.machine().upper() in ('AMD64','X86_64'),'Actual native Windows x64 is mandatory')
    from playwright.async_api import async_playwright
    from windows_deidentified_package import unpack
    from windows_doctor_build import verify_content_manifest
    from verify_windows_doctor_browser import launch,stop,live_state,manager_page,resume,worklist_ready,pe_is_x64,process_modules,safe_error
    from verify_windows_ui15_upgrade import cleanup_owned,get
    from verify_windows_stt_independent_upgrade import embedded_modules,database_state,public_database,compare_database,capture,curate_old13_and_approve
    from ecg_core import doctor_source
    from ecg_core.repository import CaseRepository
    from ecg_core.ebi import load_records
    from deidentify_patient_source import export_case
    checks=result['checks']
    with tempfile.TemporaryDirectory(prefix='af17-actual-PE-') as temporary:
        work=Path(temporary);new=unpack(args.software_archive,work/'new');verify_content_manifest(new)
        old=None
        if args.base_software_archive:
            require(sha256(args.base_software_archive.read_bytes()).hexdigest()==OLD_P01_SHA,'Old15 immutable original P01 ZIP mismatch')
            old=unpack(args.base_software_archive,work/'old');verify_original15_manifest(old)
        package=program_identity(old,new);result['package_identity']=package
        if getattr(args,'source_compile_commit',None) is not None:
            result['acceptance_provenance']=bind_acceptance_provenance(package,source_compile_commit=args.source_compile_commit,producer_run_id=args.producer_run_id,controller_commit=args.controller_commit,acceptance_run_id=args.acceptance_run_id)
            require(os.environ.get('GITHUB_SHA')==args.controller_commit and os.environ.get('GITHUB_RUN_ID')==str(args.acceptance_run_id),'Native continuation CI identity differs from the actual controller invocation')
        exe=new/'CardioInsightDoctorEval.exe';require(pe_is_x64(exe),'New actual EXE is not AMD64 PE')
        result['embedded_new_runtime']=embedded_modules(exe,ROOT)
        if old is None:
            from generate_stt_comprehensive_math import generate
            declaration=generate(work/'math');case_duration=900
        else:
            from generate_report_evidence_math import generate
            declaration=generate(work/'math');case_duration=600
        cases,issues=CaseRepository(work/'math').scan_cases();require(len(cases)==1 and not issues,'Independent mathematical case scan failed')
        fixture=work/'sources/P01';export_case(cases[0],fixture,mathematical_fixture=True)
        source=doctor_source.validate_source(fixture);require(source['kind']=='mathematical_deidentified_fixture' and source['patient_inputs_read'] is False,'Only independent mathematical source permitted')
        source_before=files(fixture);home=work/'same-home';browser=context=page=None;errors=[];blocked=[];after_mode=False;active=exe;primary_error=None
        result.update(fixture_profile=declaration['profile'],source_kind=source['kind'],source_sha256=source_before,new_archive_sha256=sha256(args.software_archive.read_bytes()).hexdigest())
        async with async_playwright() as pw:
            try:
                browser=await pw.chromium.launch(channel='msedge',headless=True)
                result['browser']=dict(channel='msedge',installed_system_browser=True,version=browser.version)
                async def new_context():
                    c=await browser.new_context(viewport={'width':1440,'height':1000},service_workers='block',accept_downloads=False)
                    def observe(p):
                        p.set_default_timeout(90000);p.set_default_navigation_timeout(90000)
                        p.on('pageerror',lambda e:errors.append(safe_error(e)))
                        p.on('download',lambda _:blocked.append(dict(kind='download')))
                    c.on('page',observe)
                    async def local_only(route):
                        url=urlsplit(route.request.url);path=url.path.lower()
                        if url.hostname not in ('127.0.0.1','localhost','::1') or path.endswith('.pdf') or '/report/pdf' in path:
                            blocked.append(dict(kind='external-or-PDF',path=url.path));await route.abort();return
                        if after_mode and '/api/cases/' in path and route.request.method not in ('GET','HEAD'):
                            if not(route.request.method=='POST' and path.rsplit('/',1)[-1] in READONLY_POSTS):
                                blocked.append(dict(kind='clinical-write-after-upgrade',path=url.path));await route.abort();return
                        await route.continue_()
                    await c.route('**/*',local_only);return c
                if old is None:
                    from verify_stt_comprehensive_ui import verify
                    from verify_af_multistrip_ui import verify as verify_af
                    context=await new_context();manager,_=await launch(exe,home,fixture);page=await manager_page(context,manager)
                    async with page.expect_response(lambda r:urlsplit(r.url).path=='/continue'):await page.locator('#continueExperience').click()
                    await worklist_ready(page);workspace=json.loads((home/'catalog.json').read_text())['selected_workspace']
                    state=await live_state(home,workspace,exe);modules=await asyncio.to_thread(process_modules,state['pid'],exe)
                    require(modules['python_dll_from_bundle'],'Actual fresh PE workspace did not load bundled Python')
                    result['ui']=await verify(page,doctor_source.CASE_ID,args.output.parent/'comprehensive-ui')
                    result['actual_processes']=[dict(phase='fresh17',pid=state['pid'],birth=state['birth'])]
                    result['bundled_python_modules']=modules
                    checks.extend(['fresh17-real-PYZ-runtime-matches-frozen-source','system-Edge-and-actual-bundled-Python',*result['ui']['checks']])
                    result['af_multistrip_ui']=await verify_af(page,doctor_source.CASE_ID,args.output.parent/'af-multistrip-ui',episode_start_s=120,episode_duration_s=300,note='Windows17 native mathematical AF multistrip',source_kind='mathematical_synthetic')
                    checks.extend('AF-multistrip:'+check for check in result['af_multistrip_ui']['checks'])
                else:
                    require(sha256((ROOT/'scripts/stt16_legacy15_report_evidence_ui.py').read_bytes()).hexdigest()==LEGACY_DRIVER_SHA,'Immutable old15 visible baseline driver changed')
                    from stt16_legacy15_report_evidence_ui import verify_report_evidence_ui
                    old_exe=old/'CardioInsightDoctorEval.exe';require(pe_is_x64(old_exe),'Old15 source is not a real x64 PE')
                    oracle=load_old_oracles(old_exe);raw=fixture/doctor_source.PATHS['data'];records=load_records(str(fixture/doctor_source.PATHS['ebi']))
                    expected=oracle['stt'].build_stt_review('',raw,records,600,analysis_revision='authentic-actual15-PE')
                    def current_oracle(items):return expected
                    def range_oracle(first,end,leads,items):return oracle['stt_range'].analyze_stt_range(raw,records,start_sample=first,end_sample=end,leads=leads,measurement_ms=60)
                    active=old_exe;context=await new_context();manager,_=await launch(old_exe,home,fixture);page=await manager_page(context,manager)
                    async with page.expect_response(lambda r:urlsplit(r.url).path=='/continue'):await page.locator('#continueExperience').click()
                    await worklist_ready(page);workspace=json.loads((home/'catalog.json').read_text())['selected_workspace']
                    state0=await live_state(home,workspace,old_exe);module0=await asyncio.to_thread(process_modules,state0['pid'],old_exe);require(module0['python_dll_from_bundle'],'Old15 did not load bundled Python')
                    await page.locator('#openFirstCase').click();await page.wait_for_function('id=>state.caseId===id&&!state.caseLoading',arg=doctor_source.CASE_ID)
                    shots=args.output.parent/'upgrade-before-screenshots';shots.mkdir(exist_ok=True)
                    result['old15_baseline_ui']=await verify_report_evidence_ui(page,doctor_source.CASE_ID,expected,shots,{'checks':[]},expected_for_annotations=current_oracle,range_oracle=range_oracle)
                    await curate_old13_and_approve(page,doctor_source.CASE_ID,checks)
                    before=await capture(page,doctor_source.CASE_ID,get)
                    await context.close();context=None;await stop(old_exe,home)
                    database=home/'workspaces'/workspace/'data/cardioinsight.db';db0=database_state(database)
                    (args.output.parent/'upgrade-before-report.json').write_text(json.dumps(before['report'],ensure_ascii=False,indent=2)+'\n')
                    after_mode=True;active=exe;first=datetime.now(timezone.utc);context=await new_context();manager,_=await launch(exe,home,fixture)
                    page=await resume(context,manager,workspace);state1=await live_state(home,workspace,exe)
                    module1=await asyncio.to_thread(process_modules,state1['pid'],exe);require(module1['python_dll_from_bundle'],'New17 did not load bundled Python')
                    require((state0['pid'],state0['birth'])!=(state1['pid'],state1['birth']),'Upgrade reused old15 process')
                    require(json.loads((home/'catalog.json').read_text())['selected_workspace']==workspace,'Upgrade switched doctor workspace')
                    await page.locator('#openFirstCase').click();await page.wait_for_function('id=>state.caseId===id&&!state.caseLoading',arg=doctor_source.CASE_ID)
                    after=await capture(page,doctor_source.CASE_ID,get,after=True)
                    result['api_upgrade']=compare_api(before,after,package)
                    for _ in range(3):exact(after,await capture(page,doctor_source.CASE_ID,get,after=True),'Repeated read-only GET mutated the new-basis report or history')
                    await context.close();context=None;await stop(exe,home);last=datetime.now(timezone.utc)
                    db1=database_state(database);result['database_upgrade']=compare_database(db0,db1,doctor_source.CASE_ID,first,last,before['report']['current_analysis_basis'],after['report']['current_analysis_basis'])
                    result['database_before']=public_database(db0);result['database_after']=public_database(db1)
                    (args.output.parent/'upgrade-after-report.json').write_text(json.dumps(after['report'],ensure_ascii=False,indent=2)+'\n')
                    result['actual_processes']=[dict(phase='old15',pid=state0['pid'],birth=state0['birth']),dict(phase='fresh17',pid=state1['pid'],birth=state1['birth'])]
                    checks.extend(['exact-original15-ZIP-not-repacked-and-distinct-fresh17-EXE','authentic-old15-PE-measurement-oracles-and-visible-reviewed-baseline',
                                   'same-source-home-workspace-database-and-recovery-epoch','new-engine-invalidates-current-report-once-with-old-signature-intact',
                                   'annotations-UUID-ledger-curation-and-original-conclusion-unchanged','old-ST-records-readable-stale-never-relabelled-as-new-subtypes','three-repeat-GETs-idempotent-with-no-clinical-writes'])
                require(source_before==files(fixture),'Generated mathematical source mutated')
                require(not errors and not blocked,'Page errors, external requests, clinical writes or downloads occurred')
                result.update(status='passed',native_frozen_runtime=True,primary_checks=len(checks),source_hashes_unchanged=True,bundled_python_proved=True,
                              page_errors=errors,blocked_requests=blocked,windows_system=platform.system(),windows_release=platform.release())
            except Exception as error:
                primary_error=error;result.update(status='failed',error=safe_error(error),page_errors=errors,blocked_requests=blocked)
                if page and not page.is_closed():
                    try:await page.screenshot(path=str(args.output.parent/'native-failure.png'))
                    except Exception:pass
                raise
            finally:await cleanup_owned(context,browser,active,home,stop,result,primary_error,sanitize=safe_error)


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--software-archive',type=Path,required=True)
    p.add_argument('--base-software-archive',type=Path);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--source-compile-commit');p.add_argument('--producer-run-id',type=int)
    p.add_argument('--controller-commit');p.add_argument('--acceptance-run-id',type=int)
    a=p.parse_args()
    provenance=(a.source_compile_commit,a.producer_run_id,a.controller_commit,a.acceptance_run_id)
    require(not any(v is not None for v in provenance) or all(v is not None for v in provenance),'Native continuation requires complete producer and acceptance identities')
    require(not a.output.exists(),'Preserve original native attempts');a.output.parent.mkdir(parents=True,exist_ok=True)
    result=dict(status='running',mode='actual15-to17-upgrade' if a.base_software_archive else 'actual-fresh17-comprehensive-STT-and-AF-multistrip-doctor-flow',checks=[],
                patient_inputs_read=False,clinical_validation=False,pdf_operations=0,physical_hospital_Windows10_verified=False)
    try:asyncio.run(run(a,result))
    except Exception as error:
        result['status']='failed';result.setdefault('error',type(error).__name__);raise
    finally:
        a.output.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n');print('WINDOWS_AF17_NATIVE_JSON='+json.dumps(result,ensure_ascii=False))


if __name__=='__main__':main()
