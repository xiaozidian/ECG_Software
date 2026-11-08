"""Supplement native Windows EXE acceptance with independent strict math input.

Run only after building the source-free P01 software archive. Existing full-day
M01, P01 upgrade and final-report protections remain separate required stages.
No source/DB/PDF is published; receipts contain mathematical checks and hashes.
"""
from pathlib import Path
from hashlib import sha256
import argparse
import asyncio
import json
import os
import platform
import tempfile
from urllib.parse import urlsplit
import zipfile

ROOT=Path(__file__).resolve().parents[1]
import sys
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
from playwright.async_api import async_playwright
from generate_report_evidence_math import generate
from verify_report_evidence_ui import verify_report_evidence_ui
from verify_windows_ui_upgrade_native import cleanup_owned
from deidentify_patient_source import export_case
from windows_deidentified_package import unpack
from windows_doctor_build import verify_content_manifest
from verify_windows_doctor_browser import launch,stop,live_state,manager_page,pe_is_x64,safe_error,worklist_ready,process_modules
from ecg_core import doctor_source
from ecg_core.repository import CaseRepository
from ecg_core.ebi import load_records
from ecg_core.stt import build_stt_review
from ecg_core.stt_range import analyze_stt_range
from ecg_core.stt_records import RHYTHM_POLICY


def snapshot(root):return {p.relative_to(root).as_posix():sha256(p.read_bytes()).hexdigest() for p in root.rglob('*') if p.is_file()}


async def verify(args,result):
    assert os.name=='nt' and platform.machine().upper() in ('AMD64','X86_64'), 'Native Windows x64 required; local prechecks cannot satisfy this receipt'
    with tempfile.TemporaryDirectory(prefix='report29-native-mathematics-') as tmp:
        work=Path(tmp);origin=work/'new-mathematics';declaration=generate(origin)
        cases,issues=CaseRepository(origin).scan_cases();assert len(cases)==1 and not issues
        fixture=work/'sources/P01';export_case(cases[0],fixture,mathematical_fixture=True)
        manifest=doctor_source.validate_source(fixture)
        assert manifest['kind']=='mathematical_deidentified_fixture' and manifest['patient_inputs_read'] is False
        before=snapshot(fixture)
        raw=fixture/doctor_source.PATHS['data'];ebi=fixture/doctor_source.PATHS['ebi']
        records=load_records(str(ebi))
        expected=build_stt_review('',raw,records,600,analysis_revision='independent-native-fixture')
        assert expected['analysis']['algorithm_version']=='stt-screening-0.3.2-independent-rhythm'
        assert any(c['kind'] in ('st_depression','st_elevation') and len(c['leads'])==1 and c['duration_s']>=60 for c in expected['automatic_candidates']['items'])
        def current_oracle(items):return build_stt_review('',raw,records,600,analysis_revision='independent-native-fixture')
        def range_oracle(first,end,leads,items):return analyze_stt_range(raw,records,start_sample=first,end_sample=end,leads=leads,measurement_ms=60)
        program=unpack(args.software_archive,work/'program');verify_content_manifest(program)
        exe=program/'CardioInsightDoctorEval.exe';assert pe_is_x64(exe)
        release=json.loads((program/'RELEASE.json').read_text())
        shared=json.loads((program/'_internal/shared-source-build.json').read_text())
        from scripts.verify_public_release import verify as verify_source
        from scripts.shared_source import snapshot as software_snapshot
        assert release['app_version']=='0.12.29-stt-independent.20261104' and release['packaging_version']=='1.0.15'
        assert release['production_source_identity']==verify_source(Path(__file__).resolve().parents[1])
        assert shared==software_snapshot(Path(__file__).resolve().parents[1])[0]
        new_assets=['static/js/report-wave-menu.js','static/css/report-wave-menu.css']
        for name in new_assets:
            data=(program/'_internal'/name).read_bytes()
            assert name in shared['files'] and sha256(data).hexdigest()==shared['files'][name]['sha256']
        result.update(source_commit=release['source_commit'],application_version=release['app_version'],
            packaging_version=release['packaging_version'],exe_sha256=sha256(exe.read_bytes()).hexdigest(),
            archive_sha256=sha256(args.software_archive.read_bytes()).hexdigest(),
            common_source_fingerprint=shared['source_fingerprint'],fixture_profile=declaration['profile'],
            source_kind=manifest['kind'],fixture_sha256=before)
        home=work/'doctor-home';browser=None;context=None;page=None
        errors=[];blocked=[];responses=[];guards=[]
        async with async_playwright() as pw:
            primary_error=None
            try:
                browser=await pw.chromium.launch(channel='msedge',headless=True)
                result['browser']={'channel':'msedge','installed_system_browser':True,'version':browser.version}
                context=await browser.new_context(viewport={'width':1440,'height':1000},service_workers='block')
                async def local_only(route):
                    url=urlsplit(route.request.url)
                    if url.hostname not in ('127.0.0.1','localhost','::1') or url.path.lower().endswith('.pdf'):
                        blocked.append({'path':url.path,'kind':'external-or-PDF'});await route.abort();return
                    await route.continue_()
                await context.route('**/*',local_only)
                manager,_=await launch(exe,home,fixture);page=await manager_page(context,manager)
                page.on('pageerror',lambda e:errors.append({'kind':'pageerror','message':str(e)}))
                page.on('download',lambda _:blocked.append({'kind':'download'}))
                async def response_seen(response):
                    path=urlsplit(response.url).path
                    row={'path':path,'status':response.status,'method':response.request.method}
                    responses.append(row)
                    if response.status>=400:
                        try: message=(await response.json()).get('error','')
                        except Exception: message=''
                        if response.status==409 and response.request.method=='GET' and path.endswith('/overview') and message=='波形或事件依据已变化，请重新加载后复核':
                            guards.append({'path':path,'index':len(responses)-1})
                        else: errors.append({**row,'kind':'http','message':message})
                page.on('response',response_seen)

                async with page.expect_response(lambda r:urlsplit(r.url).path=='/continue'):
                    await page.locator('#continueExperience').click()
                await worklist_ready(page)
                catalog=json.loads((home/'catalog.json').read_text());workspace=catalog['selected_workspace']
                live=await live_state(home,workspace,exe)
                modules=await asyncio.to_thread(process_modules,live['pid'],exe)
                assert modules['python_dll_from_bundle']
                result['bundled_python_proved']=True
                await page.locator('#openFirstCase').click()
                await page.wait_for_function('id=>state.caseId===id&&!state.caseLoading&&state.caseData.technical.duration_seconds_raw===600',arg=doctor_source.CASE_ID)
                served_assets=await page.evaluate("""async names=>{const out={};for(const n of names){const r=await fetch('/'+n,{cache:'no-store'});if(!r.ok)throw Error(n+': '+r.status);out[n]=Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',await r.arrayBuffer()))).map(x=>x.toString(16).padStart(2,'0')).join('');}return out;}""",new_assets)
                assert all(served_assets[name]==shared['files'][name]['sha256'] for name in new_assets)
                result['new_menu_packaged_and_served_assets']=served_assets
                screenshots=args.output.parent/'report-evidence-screenshots';screenshots.mkdir(exist_ok=True)
                result['ui']={'status':'running','checks':[]}
                result['ui']=await verify_report_evidence_ui(page,doctor_source.CASE_ID,expected,screenshots,result['ui'],expected_for_annotations=current_oracle,range_oracle=range_oracle)
                assert len(result['ui']['checks'])==14 and result['ui']['actual_UI_checks']==12 and result['ui']['actual_PE_API_lifecycle_checks']==2
                assert result['ui']['ST_rhythm_independence']['lifecycle_operations']==12
                await page.wait_for_timeout(250)
                assert all(any(r['path']==g['path'] and r['status']==200 for r in responses[g['index']+1:]) for g in guards),'Stale overview guard did not recover'
                assert errors==[] and blocked==[]
                assert before==snapshot(fixture),'Generated source mutated'
                await context.close();context=None
                await stop(exe,home)
                result.update(status='passed',native_frozen_runtime=True,source_hashes_unchanged=True,
                    page_errors=errors,blocked_requests=blocked,expected_basis_rejections=guards,windows_system=platform.system(),
                    windows_release=platform.release(),hospital_physical_windows10_verified=False)
            except Exception as error:
                primary_error=error
                if page and not page.is_closed():
                    try:await page.screenshot(path=str(args.output.parent/'report-evidence-native-failure.png'))
                    except Exception:pass
                result.update(status='failed',error=safe_error(error),page_errors=errors,blocked_requests=blocked)
                raise
            finally:
                await cleanup_owned(context,browser,exe,home,stop,result,primary_error,sanitize=safe_error)



def main():
    parser=argparse.ArgumentParser();parser.add_argument('--software-archive',type=Path,required=True);parser.add_argument('--output',type=Path,required=True);args=parser.parse_args()
    assert not args.output.exists(),'Preserve prior native attempts'
    args.output.parent.mkdir(parents=True,exist_ok=True)
    result={'status':'running','scope':'independent600s mathematical input against actual packaged Windows EXE and installed Edge',
        'patient_inputs_read':False,'pdf_operations':0,'clinical_validation':False,'unchanged_24h_M01_acceptance_required_separately':True}
    try:asyncio.run(verify(args,result))
    except Exception as e:
        result['status']='failed';result.setdefault('error',safe_error(e));raise
    finally:
        args.output.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
        print('REPORT_EVIDENCE_NATIVE_JSON='+json.dumps(result,ensure_ascii=False))


if __name__=='__main__':main()
