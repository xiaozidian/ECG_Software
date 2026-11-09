"""Run the actual ST/T doctor-flow UI on a disposable mathematical workspace.

Uses an ephemeral loopback port and a caller-installed Chromium executable.
No clinical source, workstation database or pre-existing approval is imported.
"""
from __future__ import annotations

import argparse
import asyncio
from hashlib import sha256
import json
import os
from pathlib import Path
import sys
import tempfile
import threading

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))


def run(output: Path) -> dict:
    output=output.resolve()
    output.mkdir(parents=True,exist_ok=True)
    chromium=os.environ.get('ECG_CHROME')
    if not chromium or not Path(chromium).is_file():
        raise RuntimeError('ECG_CHROME must identify the installed Chromium executable; no browser is downloaded by this verifier')
    from scripts.generate_stt_comprehensive_math import generate,CASE_ID
    from scripts.verify_stt_comprehensive_ui import verify
    from playwright.async_api import async_playwright
    with tempfile.TemporaryDirectory(prefix='stt-comprehensive-web-') as temporary:
        workspace=Path(temporary)
        fixture=generate(workspace/'mathematical-source')
        (output/'mathematical-fixture-identity.json').write_text(json.dumps(fixture,ensure_ascii=False,indent=2)+'\n')
        os.environ.update(ECG_DATA_ROOT=str(workspace/'mathematical-source'),
            ECG_APP_DATA_ROOT=str(workspace/'runtime'),ECG_CONFIG_PATH=str(workspace/'unused-config.json'),ECG_ALLOW_PHI='0')
        from app import create_app
        from werkzeug.serving import make_server
        application=create_app(data_root=workspace/'mathematical-source',db_path=workspace/'mathematical-work.sqlite3')
        server=make_server('127.0.0.1',0,application,threaded=True)
        worker=threading.Thread(target=server.serve_forever,daemon=True);worker.start()
        service=dict(temporary_mathematical_service=True,loopback_only=True,port=server.server_port,
            clinical_data_read=False,formal_workspace_touched=False,stopped=False)
        async def verify_browser():
            async with async_playwright() as pw:
                browser=await pw.chromium.launch(executable_path=chromium,headless=True,chromium_sandbox=True)
                context=await browser.new_context(viewport={'width':1440,'height':1000})
                page=await context.new_page();page.set_default_timeout(30000)
                try:
                    await page.goto('http://127.0.0.1:'+str(server.server_port)+'/')
                    result=await verify(page,CASE_ID,output)
                    result.update(browser_version=browser.version,execution_kind='github_actions' if os.environ.get('GITHUB_ACTIONS')=='true' else 'local',
                        fixture_profile=fixture['profile'],fixture_files=fixture['files'],
                        verifier_sha256={name:sha256((ROOT/name).read_bytes()).hexdigest() for name in (
                            'scripts/verify_stt_web.py','scripts/verify_stt_comprehensive_ui.py','scripts/generate_stt_comprehensive_math.py')})
                    return result
                except BaseException as error:
                    await page.screenshot(path=str(output/'failure-mathematical-only.png'),full_page=True)
                    (output/'failure.json').write_text(json.dumps({'error':str(error),'mathematical_only':True},ensure_ascii=False,indent=2)+'\n')
                    raise
                finally:
                    await context.close();await browser.close()
        try:
            result=asyncio.run(verify_browser())
            (output/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
        finally:
            server.shutdown();server.server_close();worker.join(timeout=5)
            service['stopped']=not worker.is_alive()
            (output/'service.json').write_text(json.dumps(service,indent=2)+'\n')
            if not service['stopped']:raise RuntimeError('Temporary mathematical server did not stop')
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,default=ROOT/'build/core-verification/stt-comprehensive-web')
    result=run(parser.parse_args().output)
    print(json.dumps({k:result[k] for k in ('status','primary_checks','clinical_validation','patient_inputs_read')},ensure_ascii=False))
