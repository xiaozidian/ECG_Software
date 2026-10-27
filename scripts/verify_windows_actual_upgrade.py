"""Save synthetic work in the actual 1.0.2 EXE and reopen it in actual 1.0.3."""
import argparse,asyncio,json,os,tempfile
from pathlib import Path,PurePosixPath
from urllib.parse import urlsplit
from playwright.async_api import async_playwright
from verify_windows_doctor_browser import (launch,stop,source_snapshot,manager_page,worklist_ready,
    open_case,save_math_work,persistence_check,resume,live_state,run_cli,digest,record)

async def verify(args,receipt):
 previous=args.previous.resolve();current=args.current.resolve()
 source,manifest,before_source=source_snapshot(previous)
 old=previous/'CardioInsightDoctorEval.exe';new=current/'CardioInsightDoctorEval.exe'
 old_release=json.loads((previous/'RELEASE.json').read_text());new_release=json.loads((current/'RELEASE.json').read_text())
 assert old_release['packaging_version']=='1.0.2' and new_release['packaging_version']=='1.0.3'
 assert old_release['software_version']!=new_release['software_version']
 async with async_playwright() as p:
  browser=await p.chromium.launch(channel='msedge',headless=True)
  receipt['browser']=browser.version
  with tempfile.TemporaryDirectory(prefix='doctor-actual-upgrade-') as temporary:
   home=Path(temporary);active=old;context=None
   try:
    context=await browser.new_context(viewport={'width':1440,'height':1000},service_workers='block')
    async def only_local(route):
     url=urlsplit(route.request.url)
     assert url.hostname in ('127.0.0.1','localhost','::1') and not url.path.lower().endswith('.pdf')
     await route.continue_()
    await context.route('**/*',only_local)
    manager,_=await launch(old,home,source);page=await manager_page(context,manager)
    async with page.expect_response(lambda r:urlsplit(r.url).path=='/continue'):
     await page.locator('#continueExperience').click()
    await worklist_ready(page);await open_case(page)
    annotation=await save_math_work(page,receipt)
    workspace=json.loads((home/'catalog.json').read_text())['selected_workspace']
    folder=home/'workspaces'/workspace
    old_metadata=json.loads((folder/'WORKSPACE.json').read_text())
    binding=(home/'source-selection.json').read_bytes()
    await context.close();context=None;await stop(old,home)
    active=new;manager,_=await launch(new,home)
    context=await browser.new_context(viewport={'width':1440,'height':1000},service_workers='block')
    await context.route('**/*',only_local)
    page=await resume(context,manager,workspace);await live_state(home,workspace,new)
    await persistence_check(page,receipt,'actual-1.0.2-to-1.0.3-preserves-report-and-annotation',annotation)
    new_metadata=json.loads((folder/'WORKSPACE.json').read_text());upgrade=new_metadata['last_upgrade']
    assert upgrade['from_packaging_version']=='1.0.2' and upgrade['to_packaging_version']=='1.0.3'
    assert upgrade['from_version']==old_release['software_version'] and upgrade['to_version']==new_release['software_version']
    assert upgrade['snapshot_integrity']=='ok' and new_metadata['application_initialized'] is True
    relative=PurePosixPath(upgrade['snapshot']);assert len(relative.parts)==1 and '..' not in relative.parts
    assert digest(folder/'upgrade-snapshots'/relative.name)==upgrade['snapshot_sha256']
    assert (home/'source-selection.json').read_bytes()==binding
    assert source_snapshot(previous)[2]==before_source
    record(receipt,'actual-cross-core-upgrade-backup-and-source-retention',{
     'from_packaging':'1.0.2','to_packaging':'1.0.3','from_core':upgrade['from_version'],'to_core':upgrade['to_version'],
     'sqlite_snapshot_integrity':'ok','snapshot_sha256_verified':True,'source_selection_unchanged':True,
     'source_file_hashes_unchanged':True,'clinical_data_used':False})
    await context.close();context=None;await stop(new,home)
    metadata=(folder/'WORKSPACE.json').read_bytes();database=digest(folder/'data/cardioinsight.db')
    rejected=await asyncio.to_thread(run_cli,old,home,'launch','--no-browser')
    assert rejected.returncode!=0
    assert (folder/'WORKSPACE.json').read_bytes()==metadata and digest(folder/'data/cardioinsight.db')==database
    record(receipt,'actual-old-1.0.2-refuses-upgraded-workspace-without-writing')
   finally:
    if context:await context.close()
    await stop(active,home)
    await browser.close()
 receipt['status']='passed'

def main():
 p=argparse.ArgumentParser();p.add_argument('--previous',type=Path,required=True);p.add_argument('--current',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
 result={'status':'running','checks':[],'source_kind':'mathematical_synthetic','pdf_operations':0,'clinical_validation':False}
 try:
  assert os.name=='nt';asyncio.run(verify(a,result))
 except Exception as e:
  from verify_windows_doctor_browser import safe_error
  result['status']='failed';result['error']=safe_error(e);raise
 finally:
  a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n');print(json.dumps(result,ensure_ascii=False))
if __name__=='__main__':main()
