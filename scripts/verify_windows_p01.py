"""Native P01 smoke and retained-work checks using generated math only."""
from pathlib import Path
from urllib.parse import urlsplit
import argparse
import asyncio
import json
import os
import shutil
import tempfile

from playwright.async_api import async_playwright
from generate_doctor_24h import generate_dataset
from deidentify_patient_source import export_case
from windows_deidentified_package import unpack
from windows_doctor_build import create_content_manifest,verify_content_manifest,digest
from ecg_core.repository import CaseRepository
from ecg_core import doctor_source
from verify_windows_doctor_browser import (launch,stop,live_state,manager_page,worklist_ready,
    navigate,wait_edit,editor_round,report_ready,browser_json,resume,run_cli,record)
from verify_lasso_browser import verify_lasso

CASE=doctor_source.CASE_ID
NOTE='P01 mathematical fixture saved-work verification; no patient input.'

async def open_case(page,duration):
    try:await worklist_ready(page)
    except Exception:
        snapshot=await page.evaluate("()=>({page:typeof state==='undefined'?null:state.currentPage,caseCount:typeof state==='undefined'?null:state.cases?.length,title:document.title,body:document.body.innerText.slice(0,700)})")
        raise AssertionError('P01 worklist did not become ready: '+json.dumps(snapshot)) from None
    await page.locator('#openFirstCase').click()
    await page.wait_for_function('(arg)=>state.caseId===arg.id && !state.caseLoading && state.caseData?.technical.duration_seconds_raw===arg.duration',arg={'id':CASE,'duration':duration})
    await navigate(page,'edit');await wait_edit(page)

async def saved_work(page):
    report=await browser_json(page,'/api/cases/'+CASE+'/report')
    annotations=await browser_json(page,'/api/cases/'+CASE+'/annotations')
    assert report['conclusion']==NOTE and any(x.get('note','').endswith(NOTE) for x in annotations['items'])

async def verify(args,result):
    assert os.name=='nt'
    with tempfile.TemporaryDirectory(prefix='p01-native-math-only-') as temporary:
        work=Path(temporary);math=args.math_source_root or work/'math-input'
        if args.math_source_root is None:generate_dataset(math,duration_minutes=1440,seed=20261013)
        origin=json.loads((math/'source-manifest.json').read_text())
        assert origin['wholly_synthetic'] is True and origin['patient_inputs_read'] is False and origin['kind']=='mathematical_synthetic'
        cases,issues=CaseRepository(math).scan_cases();assert len(cases)==1 and not issues
        fixture=work/'source/P01';export_case(cases[0],fixture,mathematical_fixture=True)
        m=doctor_source.validate_source(fixture);assert m['kind']=='mathematical_deidentified_fixture' and m['patient_inputs_read'] is False
        before={p.relative_to(fixture).as_posix():digest(p) for p in fixture.rglob('*') if p.is_file()}
        program=unpack(args.software_archive,work/'original-program');verify_content_manifest(program)
        exe=program/'CardioInsightDoctorEval.exe';active=exe;home=work/'doctor-home';context=None
        async with async_playwright() as p:
            browser=await p.chromium.launch(channel='msedge',headless=True)
            result['edge']=browser.version
            try:
                context=await browser.new_context(viewport={'width':1440,'height':1000},service_workers='block')
                async def local_only(route):
                    parsed=urlsplit(route.request.url)
                    assert parsed.hostname in ('127.0.0.1','localhost','::1') and not parsed.path.lower().endswith('.pdf')
                    await route.continue_()
                await context.route('**/*',local_only)
                manager,_=await launch(exe,home,fixture);page=await manager_page(context,manager)
                async with page.expect_response(lambda r:urlsplit(r.url).path=='/continue'):
                    await page.locator('#continueExperience').click()
                assert urlsplit(page.url).path!='/continue','P01 manager could not start its workspace'
                await open_case(page,m['duration_seconds'])
                record(result,'P01-native-one-case-source-and-private-mode',{'source_kind':m['kind'],'patient_inputs_read':False})
                await editor_round(page,result)
                lasso=await verify_lasso(page,fixture,args.output.parent/'p01-mathematical-lasso.png')
                record(result,'P01-native-full-cohort-lasso',lasso)
                await navigate(page,'stt')
                await page.wait_for_function("()=>state.sttEvidence && document.querySelector('#sttWaveCanvasWrap').dataset.sttWaveState==='ready'")
                await page.locator('#sttFinding').select_option('无法判读');await page.locator('#sttReviewNote').fill(NOTE)
                await page.locator('#sttSignalChecked').check();await page.locator('#saveSttAnnotation').click()
                await page.wait_for_function('()=>!state.sttSaving')
                await navigate(page,'trends');await page.locator('[data-hrv-edit-action="locate"]').first.wait_for()
                record(result,'P01-native-STT-and-HRV-source-read')
                await report_ready(page);await page.locator('#conclusionEditor').fill(NOTE);await page.locator('#saveReport').click()
                await page.wait_for_function('()=>!state.reportSaving && !state.reportDirty')
                await saved_work(page)
                await navigate(page,'dashboard');await open_case(page,m['duration_seconds']);await saved_work(page)
                record(result,'P01-native-report-annotation-save-reopen')
                workspace=json.loads((home/'catalog.json').read_text())['selected_workspace']
                folder=home/'workspaces'/workspace
                meta=json.loads((folder/'WORKSPACE.json').read_text())
                assert meta['selected_dataset']=='P01' and meta['source_kind']==m['kind']
                binding=(home/'source-selection.json').read_bytes()
                await context.close();context=None;await stop(exe,home)
                newer=work/'upgrade-fixture';shutil.copytree(program,newer)
                release=json.loads((newer/'RELEASE.json').read_text());release.update(packaging_version='1.0.5',release_version='1.0.5',verification_fixture_only=True)
                (newer/'RELEASE.json').write_text(json.dumps(release));create_content_manifest(newer,with_source=False)
                active=newer/'CardioInsightDoctorEval.exe'
                manager,_=await launch(active,home)
                context=await browser.new_context(viewport={'width':1440,'height':1000},service_workers='block');await context.route('**/*',local_only)
                page=await resume(context,manager,workspace)
                await open_case(page,m['duration_seconds']);await saved_work(page)
                updated=json.loads((folder/'WORKSPACE.json').read_text());upgrade=updated['last_upgrade']
                assert upgrade['from_packaging_version']=='1.0.4' and upgrade['to_packaging_version']=='1.0.5' and upgrade['snapshot_integrity']=='ok'
                assert digest(folder/'upgrade-snapshots'/upgrade['snapshot'])==upgrade['snapshot_sha256']
                assert (home/'source-selection.json').read_bytes()==binding
                record(result,'P01-same-core-version-upgrade-retains-work-source-and-backup')
                await context.close();context=None;await stop(active,home)
                metadata=(folder/'WORKSPACE.json').read_bytes();database=digest(folder/'data/cardioinsight.db')
                rejected=await asyncio.to_thread(run_cli,exe,home,'launch','--no-browser')
                assert rejected.returncode!=0 and (folder/'WORKSPACE.json').read_bytes()==metadata and digest(folder/'data/cardioinsight.db')==database
                assert before=={p.relative_to(fixture).as_posix():digest(p) for p in fixture.rglob('*') if p.is_file()}
                record(result,'P01-old-wrapper-refuses-newer-work-without-writing')
            finally:
                if context:await context.close()
                await stop(active,home);await browser.close()
    result['status']='passed'

def main():
    p=argparse.ArgumentParser();p.add_argument('--software-archive',type=Path,required=True);p.add_argument('--output',type=Path,required=True);p.add_argument('--math-source-root',type=Path);a=p.parse_args()
    a.output.parent.mkdir(parents=True,exist_ok=True)
    result={'status':'running','checks':[],'patient_inputs_read':False,'kind':'mathematical_deidentified_fixture','pdf_operations':0,'clinical_validation':False}
    try:asyncio.run(verify(a,result))
    except Exception as error:
        result['status']='failed';result['error']=type(error).__name__+': '+str(error);raise
    finally:a.output.write_text(json.dumps(result,indent=2)+'\n');print('P01_NATIVE_RECEIPT_JSON='+json.dumps(result))

if __name__=='__main__':main()
