"""Actual Windows PE UI15-only upgrade preserves an already reviewed math report.

This new15 controller is distinct from preserved historical helper27.
The verification controller may use Python/Playwright. Both application phases
must run the actual x64 PE with bundled Python and installed system Edge. No
producer, executable, provenance guard or clinical database is patched.
"""
from __future__ import annotations
import argparse
import asyncio
from contextlib import closing
from datetime import datetime,timedelta,timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import platform
import re
import sqlite3
import sys
import tempfile
from urllib.parse import urlencode,urlsplit

CORE='0.12.29-stt-independent.20261104'
UI15='0.12.29-ui-source-render.20261108'
READONLY_POSTS={'open','scatter-selection','waveform-strips','event-waveforms','waveform-density',
                'advanced-analysis','rr-locate','stt-range'}


def require(condition,message):
    if not condition:raise AssertionError(message)


def error_summary(error):
    value=re.sub(r"(?i)[a-z]:[\\/][^\s'\"><,;\]\)]+",'[local-path]',str(error))
    value=re.sub(r'(https?://[^\s?]+)\?[^\s]*',r'\1?[redacted]',value)
    value=re.sub(r'(?i)(token[=:]\s*)[a-f0-9]{32,}',r'\1[redacted]',value)
    return type(error).__name__+': '+value[:700]


def fingerprint(value):
    return sha256(json.dumps(value,sort_keys=True,ensure_ascii=False,separators=(',',':'),allow_nan=False).encode()).hexdigest()


async def cleanup_owned(context,browser,active,home,stop,result,primary_error=None,sanitize=error_summary):
    """Attempt every owned cleanup without masking an earlier verification error."""
    failures=[]
    async def close_context():
        if context and (not browser or browser.is_connected()):await context.close()
    async def stop_service():
        result['owned_services_stop_requested']=True
        await stop(active,home)
        result['owned_services_stop_completed']=True
    async def close_browser():
        if browser and browser.is_connected():await browser.close()
    for label,action in [('context.close',close_context),('owned_service.stop',stop_service),('browser.close',close_browser)]:
        try:await action()
        except Exception as error:failures.append(dict(operation=label,error=sanitize(error)))
    result['cleanup_errors']=failures
    if failures:
        result.update(status='failed',native_frozen_runtime=False)
        if primary_error is None:
            result.setdefault('error','Owned native cleanup failed; see cleanup_errors')
            raise RuntimeError('Owned native cleanup failed; see cleanup_errors')
    return failures


def files(root):
    return {p.relative_to(root).as_posix():sha256(p.read_bytes()).hexdigest()
            for p in root.rglob('*') if p.is_file()}


def program_identity(base,new):
    """Content-only comparison, separate from the mandatory native PE gate."""
    left,right=files(base),files(new)
    require(set(left)==set(right),'UI repack added or removed package members')
    require(not any(n.startswith('Sources/') for n in left),'Both archives must be source-free software packages')
    require(left['CardioInsightDoctorEval.exe']==right['CardioInsightDoctorEval.exe'],'UI update rebuilt or changed the executable')
    allowed_root={'RELEASE.json','CONTENTS.json','SHA256SUMS.txt','版本说明.txt'}
    changed=sorted(n for n in left if left[n]!=right[n])
    old_shared=json.loads((base/'_internal/shared-source-build.json').read_text(encoding='utf-8'))
    assets={n for n,row in old_shared['files'].items() if row['component']=='ui'}
    require(len(assets)==80,'Expected exact existing80 UI assets')
    allowed_ui={'_internal/'+n for n in assets}|{'_internal/shared-source-build.json'}
    ui=lambda n:n in allowed_ui
    forbidden=[n for n in changed if not ui(n) and n not in allowed_root]
    require(not forbidden,'Non-UI runtime bytes changed: '+str(forbidden))
    require(any(n.startswith(('_internal/static/','_internal/templates/')) for n in changed),'New package contains no changed UI assets')
    immutable=[n for n in left if n.startswith('_internal/') and not ui(n)]
    require(immutable and all(left[n]==right[n] for n in immutable),'Runtime internals were not preserved')
    old_release=json.loads((base/'RELEASE.json').read_text(encoding='utf-8'))
    release=json.loads((new/'RELEASE.json').read_text(encoding='utf-8'))
    metadata_changes={'packaging_version','release_version','ui_release_id','source_commit','production_source_identity',
        'base_binary_source_commit','base_binary_ci_run','base_binary_ci_conclusion','accepted_base_validation_commit','accepted_base_validation_run',
        'base_binary_exe_sha256','base_archive_sha256','binary_reused_without_rebuild','ui_repack_only','ui_repack_ci_run_url','ci_run_url','release_notes'}
    require({k:v for k,v in old_release.items() if k not in metadata_changes}=={k:v for k,v in release.items() if k not in metadata_changes},'UI15 changed preserved dependency, source-profile or binary-build metadata')
    require(old_release['source_id']==release['source_id']=='P01' and old_release['source_data_bundled'] is release['source_data_bundled'] is False,'Upgrade inputs must be exact source-free P01 profiles')
    require(old_release['packaging_version']=='1.0.14' and release['packaging_version']=='1.0.15','Expected verified base 1.0.14 and UI repack 1.0.15')
    require(old_release['app_version']==release['app_version']==CORE,'UI repack changed the application core version')
    require(release['ui_release_id']==UI15,'Missing independent UI15 release identity')
    require(release.get('binary_reused_without_rebuild') is True and release.get('ui_repack_only') is True,'Missing binary reuse declaration')
    require(release['base_binary_exe_sha256']==left['CardioInsightDoctorEval.exe'],'Declared base executable SHA256 differs')
    require(release['base_binary_source_commit']==old_release['source_commit'],'Declared base binary commit differs')
    require(bool(release.get('base_binary_ci_run')),'Missing independently verified base CI run')
    if 'release_version' in release:require(release['release_version']=='1.0.15','Unexpected UI release version')
    old_shared=json.loads((base/'_internal/shared-source-build.json').read_text(encoding='utf-8'))
    shared=json.loads((new/'_internal/shared-source-build.json').read_text(encoding='utf-8'))
    require(old_shared['core_version']==shared['core_version']=='core-9875ef91ba671541','UI repack changed common core identity')
    require({n for n,row in shared['files'].items() if row['component']=='ui'}==assets,'UI member set changed')
    require(left['CardioInsightDoctorEval.exe']=='f5283fc6a670e4d6dd9553797035458f31d0ea059ef81516f06fcc3ea9c24a73','Not the accepted14 binary')
    require(old_shared['ui_version']!=shared['ui_version'],'UI repack did not change UI identity')
    return dict(exe_sha256=left['CardioInsightDoctorEval.exe'],unchanged_non_ui_internal_count=len(immutable),
        unchanged_non_ui_internal_sha256=fingerprint({n:left[n] for n in immutable}),changed_files=changed,
        base_source_commit=old_release['source_commit'],ui_source_commit=release['source_commit'],
        base_binary_ci_run=release['base_binary_ci_run'],app_version=CORE,ui_release_id=UI15,
        base_packaging_version='1.0.14',new_packaging_version='1.0.15',core_version=shared['core_version'],
        base_ui_version=old_shared['ui_version'],new_ui_version=shared['ui_version'])


def database_state(path):
    """No row contents/control credentials are emitted into public receipts."""
    with closing(sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True)) as db:
        db.execute('BEGIN');require(db.execute('PRAGMA integrity_check').fetchone()[0]=='ok','Database integrity check failed')
        names=[r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
        result={}
        for name in names:
            require(name.replace('_','').isalnum(),'Unexpected SQL table name')
            columns=[r[1] for r in db.execute('PRAGMA table_info("'+name+'")')]
            rows=sorted(db.execute('SELECT * FROM "'+name+'"').fetchall(),key=repr)
            result[name]=dict(columns=columns,row_count=len(rows),row_sha256=sha256(repr(rows).encode()).hexdigest())
        audit_rows=db.execute('SELECT * FROM audit_log ORDER BY id').fetchall() if 'audit_log' in names else []
        row=db.execute('SELECT epoch FROM workspace_recovery WHERE id=1').fetchone() if 'workspace_recovery' in names else None
        epoch=row[0] if row else ''
    return dict(tables=result,recovery_epoch=epoch,_audit_rows=audit_rows)


def compare_database_states(before,after,case_id,opened_at,opened_by):
    """Exactly one real case-open audit append; every other row is immutable."""
    require(before['recovery_epoch']==after['recovery_epoch'],'Workspace recovery epoch changed')
    left,right=before['tables'],after['tables']
    require(set(left)==set(right) and 'audit_log' in left,'Database table membership changed')
    require(all(left[n]==right[n] for n in left if n!='audit_log'),'A non-audit clinical, version or metadata table changed')
    columns=['id','case_id','actor','action','detail','created_at']
    require(left['audit_log']['columns']==right['audit_log']['columns']==columns,'Audit schema changed')
    old,new=before['_audit_rows'],after['_audit_rows']
    require(len(new)==len(old)+1 and new[:-1]==old,'Audit history changed or append count was not exactly one')
    baseline=[row for row in old if row[1]==case_id and row[3]=='case.open' and row[4]=='']
    actors={row[2] for row in baseline}
    require(len(actors)==1 and isinstance(next(iter(actors)),str) and bool(next(iter(actors))),'No unique baseline case-open actor')
    added=dict(zip(columns,new[-1]));maximum=max((row[0] for row in old),default=0)
    require(type(added['id']) is int and added['id']==maximum+1,'Invalid new audit identity')
    require(added['case_id']==case_id and added['actor']==next(iter(actors)) and added['action']=='case.open' and added['detail']=='','Unexpected audit actor, case, action or detail')
    require(isinstance(added['created_at'],str),'Audit time is not text')
    stamp=datetime.fromisoformat(added['created_at'])
    require(stamp.tzinfo is not None and stamp.isoformat(timespec='seconds')==added['created_at'],'Audit time does not match storage timestamp schema')
    require(opened_at-timedelta(seconds=1)<=stamp<=opened_by+timedelta(seconds=1),'Audit append time is outside the actual case-open interval')
    require(left['audit_log']['row_count']==len(old) and right['audit_log']['row_count']==len(new),'Audit snapshot count mismatch')
    return dict(table='audit_log',reason='The one actual post-upgrade UI open invokes storage.audit(ACTOR, case.open, mathematical_case_id).',
        old_rows_preserved=True,appended_row_count=1,appended_row=added,
        observed_open_interval=dict(start=opened_at.isoformat(),end=opened_by.isoformat()),
        before=left['audit_log'],after=right['audit_log'],all_other_tables_identical=True)


def assert_reviewed(report,basis,events):
    require(report['status']=='reviewed' and bool(report['reviewed_by']),'Report is not reviewed')
    picks=report['composition']['selected_events'];require(len(picks) in (6,7),'Expected complete six/seven-strip reviewed report')
    lookup={e['event_id']:e for e in events['items']}
    require(set(lookup)=={p['event_id'] for p in picks},'Selected event identities are missing')
    for p in picks:
        event=lookup[p['event_id']]
        require(p['basis_version']==event['basis_version'],'Previously selected figure became stale')
        if event.get('category')=='AF':require(event.get('rhythm_status')=='confirmed','AF confirmation did not survive')
        if event.get('evidence_only'):require(event.get('evidence_review',{}).get('status')=='confirmed','Manual figure review did not survive')
        else:require(event['diagnosis_status']=='confirmed','Selected diagnosis status became pending')
    current=report['current_analysis_basis'];proof=report['analysis_provenance']
    require(proof['basis']['digest']==current['digest']==basis['analysis_basis'],'Reviewed report source basis is invalid')
    require(proof['basis']['engine_id']==current['engine_id'],'Reviewed report executing engine changed')
    require(proof['composition_sha256']==fingerprint(report['composition']),'Reviewed report composition integrity changed')
    require(report['review_revision']==basis['analysis_revision']==events['analysis_revision'],'Review revisions differ')
    return dict(engine_id=current['engine_id'],analysis_basis=basis['analysis_basis'],analysis_review_revision=basis['analysis_revision'],
        report_status=report['status'],report_version=report['version'],selected_count=len(picks),
        full_report_json_sha256=fingerprint(report),selected_events_json_sha256=fingerprint(picks),
        selected_event_metadata_sha256=fingerprint(events),composition_provenance_valid=True)


async def get(page,case_id,kind):
    # Preserve the server's JSON numeric representation (20.0 versus 20).
    # Passing a parsed JS object through Playwright loses integral floats and
    # changes the exact Python composition digest signed by the application.
    payload=await page.evaluate("""async p=>{const r=await fetch(p,{cache:'no-store'});if(!r.ok)throw Error('Native GET '+r.status);return r.text()}""",'/api/cases/'+case_id+'/'+kind)
    return json.loads(payload)


async def settled(page):
    await page.wait_for_function("()=>state.report&&!state.reportDirty&&!state.reportSaving&&!state.reportStale&&!state.reportViewLoading&&!state.reportEvidenceLoading")
    await page.wait_for_timeout(350)
    await page.evaluate('()=>new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)))')


async def nav(page,name):
    await page.locator('.nav-item[data-page="'+name+'"]').click()
    await page.wait_for_function('p=>state.currentPage===p',arg=name)
    if name=='report':await settled(page)
    else:await page.wait_for_timeout(350)


async def tab(page,name):
    await page.locator('#reportV2Nav [data-category="'+name+'"]').click()
    await page.wait_for_function('p=>state.reportDisplayedCategory===p&&!state.reportViewLoading&&!state.reportEvidenceLoading',arg=name)
    await settled(page)


async def curate_and_approve(page,case_id,checks):
    """Only visible controls create the reviewed baseline; no seeded approval."""
    await nav(page,'report');await tab(page,'strips')
    report=await get(page,case_id,'report')
    af=[p for p in report['composition']['selected_events'] if p.get('strip_id','').startswith('af-strip:')]
    require(len(af)==4,'Shared native fixture did not create four AF strips')
    for i,pick in enumerate(af[:2]):
        card=page.locator('.rw-strip[data-rw-key="'+pick['strip_id']+'"]')
        await card.locator('[data-rw-tools]>summary').click()
        await page.locator('.rw-strip-contextmenu [role=menuitem]').filter(has_text='编辑图条').click()
        editor=page.locator('.rw-strip-editor-dialog');await editor.wait_for(state='visible')
        await editor.locator('[data-se-caption]').fill('Mathematical reviewed AF curation '+str(i+1))
        await editor.locator('[data-se-notes]').fill('Preserve identifier, range, selected leads and this note across external UI upgrade.')
        if i==0:
            await editor.locator('[data-se-preset="clear"]').click()
            await editor.locator('[data-se-lead][value="II"]').check()
        else:await editor.locator('[data-se-preset="three"]').click()
        await editor.locator('button[type=submit]').click();await editor.wait_for(state='hidden');await settled(page)
    # The shipped14 product requires only the edit checkpoint. ST-T review is
    # per-record/report evidence; its intentionally hidden global button is
    # not a physician checkpoint and must never be forced or marked by API.
    for step in ('edit',):
        workflow=await get(page,case_id,'review-workflow')
        if workflow['steps'].get(step,{}).get('status')=='done':continue
        await nav(page,step)
        await page.locator('#workflowNext').click();dialog=page.locator('#workflowConfirmDialog[open]')
        await dialog.wait_for(state='visible');await page.locator('#workflowConfirmed').check()
        await page.locator('#workflowNote').fill('Independent mathematical software upgrade acceptance; not a clinical diagnosis.')
        await page.locator('#workflowConfirmSubmit').click();await page.locator('#workflowConfirmDialog[open]').wait_for(state='detached')
    workflow=await get(page,case_id,'review-workflow')
    require(workflow['steps'].get('edit',{}).get('status')=='done','Actual required edit checkpoint was not confirmed')
    await nav(page,'stt')
    require(await page.locator('#workflowNext').is_hidden(),'ST-T unexpectedly exposes a global confirmation gate')
    await nav(page,'report');await tab(page,'strips')
    report=await get(page,case_id,'report');ids=list(dict.fromkeys(p['event_id'] for p in report['composition']['selected_events']))
    events=await get(page,case_id,'report-events?'+urlencode(dict(ids='|'.join(ids),limit=2000)))
    for event in events['items']:
        if not event.get('evidence_only'):continue
        pick=next(p for p in report['composition']['selected_events'] if p['event_id']==event['event_id'])
        await nav(page,'report');await tab(page,'strips')
        await page.locator('.rw-strip[data-rw-key="'+(pick.get('strip_id') or pick['event_id'])+'"]').locator('[data-back-event]').click()
        await settled(page);await page.locator('[data-review-rr]').click()
        dialog=page.locator('#reportEvidenceDialog');await dialog.wait_for(state='visible')
        await page.wait_for_function("()=>!document.querySelector('[data-evidence-confirm]').disabled")
        await dialog.locator('[data-evidence-confirm]').click();await dialog.wait_for(state='detached');await settled(page)
    await nav(page,'report');await tab(page,'final')
    if not await page.locator('#conclusionEditor').is_visible():
        await page.locator('.rw-conclusion-disclosure>summary').click()
    await page.locator('#conclusionEditor').fill('Mathematical UI15-only upgrade verification; no clinical conclusion.')
    await page.locator('#conclusionEditor').press('Tab')
    await page.wait_for_function("()=>state.report?.conclusion==='Mathematical UI15-only upgrade verification; no clinical conclusion.'&&!state.reportDirty&&!state.reportSaving")
    await settled(page)
    await page.wait_for_function('()=>!document.querySelector("#approveReport").disabled')
    await page.locator('#approveReport').click();await page.wait_for_function('()=>state.report.status==="reviewed"');await settled(page)
    report=await get(page,case_id,'report');require(len(report['composition']['selected_events'])==6,'Native base fixture selection count changed')
    counts={len(p['leads']) for p in report['composition']['selected_events']}
    require({1,3,12}<=counts,'Baseline did not preserve independent 1/3/12-lead curation')
    checks.append('actual-base-PE-visible-UI-created-reviewed-six-strips-with-four-AF-and-1-3-12-lead-curation')


async def capture(page,case_id):
    basis=await get(page,case_id,'analysis-basis');report=await get(page,case_id,'report')
    ids=list(dict.fromkeys(p['event_id'] for p in report['composition']['selected_events']))
    events=await get(page,case_id,'report-events?'+urlencode(dict(ids='|'.join(ids),limit=2000,**basis)))
    value=dict(basis=basis,report=report,events=events,summary=assert_reviewed(report,basis,events))
    for kind in ('annotations','rhythm-review','review-workflow','report-sections','beat-editor','evidence-candidates','stt-review'):value[kind]=await get(page,case_id,kind)
    uses=report['composition'].get('stt_report_use',[]);require(bool(uses),'Reviewed baseline must contain ST report uses')
    acknowledgements=[b for b in report['composition'].get('diagnosis_blocks',[]) if b.get('manual') and str(b.get('key','')).startswith('ST:review:')]
    require(acknowledgements and all(b.get('acknowledged') is True and b.get('needs_review') is False for b in acknowledgements),'Current ST manual acknowledgement is missing')
    require(any(a.get('stt_review_receipt',{}).get('review_state')=='reviewed' for a in value['annotations']['items']),'Current29 reviewed ST record is missing')
    return value


async def af_geometry(page,case_id):
    """View-only UI15 checks after approval; never apply a range or edit a pick."""
    before=await get(page,case_id,'report');await nav(page,'report');await tab(page,'AF')
    ids=[p['event_id'] for p in before['composition']['selected_events'] if p.get('strip_id','').startswith('af-strip:')]
    require(bool(ids),'Reviewed AF event missing')
    await page.set_viewport_size({'width':1502,'height':1343})
    await page.locator('tr[data-report-event-id="'+ids[0]+'"]').locator('[data-locate]').click()
    await page.wait_for_function("()=>!!document.querySelector('#v2EventWave .report-range-editor')?._rangeReady")
    async def geometry():
        await settled(page)
        return await page.evaluate("""()=>{const s=document.querySelector('#v2EventWave .report-range-stage'),h=s.closest('.report-range-editor'),v=s.querySelector('svg'),r=s.getBoundingClientRect();return {height:r.height,bottom:r.bottom,viewport:innerHeight,svg_height:v.getBoundingClientRect().height,view_height:v.viewBox.baseVal.height,lead_count:v.querySelectorAll('[data-wave-lead]').length,gain:Number(h.dataset.displayGain),state:h._rangeDisplayState(),range:h._rangeRead(),pending:ECGReportRange.pending().length}}""")
    result=[]
    for count in (3,12):
        await page.set_viewport_size({'width':1502,'height':1343})
        await page.locator('#v2EventWave button[data-display-leads="'+str(count)+'"]').click();a=await geometry()
        await page.set_viewport_size({'width':1502,'height':1800});b=await geometry()
        for g in (a,b):
            require(160<=g['height']<=422 and g['bottom']<=g['viewport']+2,'UI15 native stage is not bounded in the tall viewport')
            require(g['lead_count']==count and abs(g['svg_height']-g['view_height'])<=1.1,'UI15 native SVG was vertically rescaled or lost leads')
            require(g['gain']>0 and g['pending']==0,'Display-only geometry created a draft or invalid gain')
        require(abs(a['gain']-b['gain'])<=1e-8 and a['range']==b['range'] and a['state']==b['state'],'Taller viewport changed native gain, range or display state')
        result.append(dict(leads=count,at_1343=a,at_1800=b))
    require(await get(page,case_id,'report')==before,'View-only native geometry changed the reviewed report')
    await page.set_viewport_size({'width':1440,'height':1000})
    return result


async def source_chart_readonly(page,diagnostics=None):
    """Real Shift+Enter opens and visible zoom controls on actual15 assets."""
    results=[]
    progress=dict(status='running',surfaces=[],completed=results,requests=[],active_requests={})
    def persist():
        if diagnostics:
            diagnostics.write_text(json.dumps(progress,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    async def snapshot(selector,phase,record):
        record['phase']=phase
        try:
            value=await page.evaluate("""s=>{
              const c=document.querySelector(s),d=document.querySelector('#chartInspectionDialog'),a=document.activeElement;
              const b=c?.getBoundingClientRect();let current=null,currentError=null;
              try{current=typeof c?._inspectionCurrent==='function'?Boolean(c._inspectionCurrent()):null;}catch(e){currentError=e.name;}
              const m=typeof morphologyWorkbench==='undefined'?null:morphologyWorkbench.privateSnapshot();
              const morph=m?{phase:m.phase,ready:m.ready,partitionGeneration:m.partitionGeneration,viewedScope:m.viewedScope,sourcePopulationCount:m.sourcePopulation?.length??null,linked:m.linked}:null;
              const flags=Object.fromEntries(['caseLoading','editLoading','editDetailLoading','editRrLoading','editTemplateLoading','reportSaving','reportViewLoading','reportEvidenceLoading'].map(k=>[k,k in state?Boolean(state[k]):null]));
              return {page:state.currentPage,mode:state.editMode,active:{id:a?.id||'',tag:a?.tagName||''},source:{connected:!!c?.isConnected,marker:c?.hasAttribute('data-inspection-source')??false,aria:c?.getAttribute('aria-keyshortcuts')??null,current,currentError,managed:!!c?._inspectionManaged,bbox:b?{x:b.x,y:b.y,width:b.width,height:b.height}:null},dialog:{exists:!!d,open:!!d?.open},flags,edit:{requestId:state.editRequestId,stripRequestId:state.editStripRequestId,workspaceRequestId:state.editWorkspaceRequestId,templateStrips:state.editTemplateStrips?.length??null,waveMeta:document.querySelector('#editWaveMeta')?.textContent??null,libraryWaveMeta:document.querySelector('#editLibraryWaveMeta')?.textContent??null},morph,linked:globalThis.ECGTemplateLinkedView?.capturePresentation?.()??null,trace:globalThis.__CI_UI15_INSPECTION_OBSERVER__?.events??[],traceCount:globalThis.__CI_UI15_INSPECTION_OBSERVER__?.count??0};
            }""",selector)
            record.setdefault('snapshots',[]).append(dict(phase=phase,active_requests=list(progress['active_requests'].values()),**value))
        except Exception as error:
            record.setdefault('snapshot_errors',[]).append(dict(phase=phase,error_type=type(error).__name__))
        persist()
    async def inspect_body(selector,record):
        surface=page.locator(selector)
        await surface.wait_for(state='visible')
        await page.wait_for_function("s=>{const c=document.querySelector(s);return c?.hasAttribute('data-inspection-source')&&c.getAttribute('aria-keyshortcuts')==='Shift+Enter';}",arg=selector)
        await snapshot(selector,'registered_before_plain_enter',record)
        before=await page.evaluate("()=>JSON.stringify({start:state.start,editStart:state.editStart,editDuration:state.editDuration,samples:[...state.editSelectedSamples],trace:state.editMorphTraceGeometry,selection:state.editSelection,morph:typeof morphologyWorkbench==='undefined'?null:morphologyWorkbench.privateSnapshot(),linked:globalThis.ECGTemplateLinkedView?.capturePresentation()})")
        await surface.press('Enter')
        require(await page.locator('#chartInspectionDialog[open]').count()==0,'Ordinary Enter unexpectedly opened chart inspection')
        await snapshot(selector,'after_plain_enter_before_shift_enter',record)
        await surface.press('Shift+Enter')
        await snapshot(selector,'after_shift_enter_before_dialog_wait',record)
        dialog=page.locator('#chartInspectionDialog[open]');await dialog.wait_for(state='visible')
        await snapshot(selector,'dialog_visible',record)
        rows=[]
        for factor in ('1','1.5','2','3'):
            await dialog.locator('select').select_option(factor)
            await page.evaluate('()=>new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)))')
            geometry=await dialog.locator('.chart-inspection-copy>canvas').evaluate("""c=>{const b=c.getBoundingClientRect(),d=Number(c.dataset.inspectionDpr);return {width:b.width,height:b.height,backingWidth:c.width,backingHeight:c.height,dpr:d};}""")
            require(geometry['width']>0 and geometry['height']>0 and geometry['dpr']>0,'Actual native copy has no valid source backing store')
            require(geometry['backingWidth']==int(geometry['width']*geometry['dpr']+.5) and geometry['backingHeight']==int(geometry['height']*geometry['dpr']+.5),'Native15 canvas backing store was stretched instead of sized for target geometry')
            rows.append(dict(factor=float(factor),**geometry))
        await dialog.locator('[data-inspection-close]').click();await dialog.wait_for(state='detached')
        after=await page.evaluate("()=>JSON.stringify({start:state.start,editStart:state.editStart,editDuration:state.editDuration,samples:[...state.editSelectedSamples],trace:state.editMorphTraceGeometry,selection:state.editSelection,morph:typeof morphologyWorkbench==='undefined'?null:morphologyWorkbench.privateSnapshot(),linked:globalThis.ECGTemplateLinkedView?.capturePresentation()})")
        require(before==after,'Native inspection changed source position, selection or original morphology hit geometry')
        results.append(dict(surface=selector,zooms=rows,readonly_source_state_identical=True))
    async def inspect(selector):
        record=dict(surface=selector,status='running',phase='entry');progress['surfaces'].append(record);persist()
        try:
            # Observers only read source/dialog attribute transitions. They do
            # not redraw, focus, retry, wait, register renderers, or edit state.
            await page.evaluate("""s=>{
              const c=document.querySelector(s),d=document.querySelector('#chartInspectionDialog');
              const trace={events:[],count:0,observers:[]};globalThis.__CI_UI15_INSPECTION_OBSERVER__=trace;
              const observe=(node,kind)=>{if(!node)return;const observer=new MutationObserver(records=>{for(const r of records){trace.count++;if(trace.events.length<128){let current=null;try{current=typeof c?._inspectionCurrent==='function'?Boolean(c._inspectionCurrent()):null;}catch(_){}trace.events.push({kind,attribute:r.attributeName,oldValue:r.oldValue,open:!!d?.open,sourceCurrent:current,connected:!!c?.isConnected,time:performance.now()});}}});observer.observe(node,{attributes:true,attributeOldValue:true,attributeFilter:kind==='dialog'?['open']:['data-inspection-source','aria-keyshortcuts','tabindex']});trace.observers.push(observer);};
              observe(c,'source');observe(d,'dialog');
            }""",selector)
            await inspect_body(selector,record)
            record['status']='passed'
        except Exception as error:
            record['status']='failed';record['error_type']=type(error).__name__
            await snapshot(selector,'failure',record)
            raise
        finally:
            await snapshot(selector,'finally',record)
            try:
                await page.evaluate("""()=>{const t=globalThis.__CI_UI15_INSPECTION_OBSERVER__;for(const observer of t?.observers||[])observer.disconnect();delete globalThis.__CI_UI15_INSPECTION_OBSERVER__;}""")
            except Exception as error:
                record['observer_cleanup_error_type']=type(error).__name__
            persist()
    def request_started(request):
        path=urlsplit(request.url).path
        if not path.startswith('/api/cases/'):return
        value=dict(method=request.method,path=path,time=datetime.now(timezone.utc).isoformat())
        progress['active_requests'][str(id(request))]=value
        if len(progress['requests'])<256:progress['requests'].append(dict(kind='started',**value))
        persist()
    def request_finished(request,kind='finished'):
        value=progress['active_requests'].pop(str(id(request)),None)
        if value and len(progress['requests'])<256:progress['requests'].append(dict(kind=kind,completed_time=datetime.now(timezone.utc).isoformat(),**value))
        persist()
    def request_failed(request):request_finished(request,'failed')
    for name,handler in [('request',request_started),('requestfinished',request_finished),('requestfailed',request_failed)]:page.on(name,handler)
    try:
        for page_name,selectors in [('review',['#ovHistogram','#ovFullHR','#ovFullRR','#ovHourRR']),('trends',['#trendCanvas','#histogramCanvas','#poincareCanvas']),('edit',['#editTrendCanvas','#editHistogramCanvas','#editScatterCanvas','#editDensityPrimary'])]:
            await nav(page,page_name)
            if page_name=='edit':
                await page.locator('[data-edit-mode="cluster"]').click()
            for selector in selectors:await inspect(selector)
        await page.locator('[data-edit-mode="library"]').click()
        for selector in ('#editLibraryHistogramCanvas','#editLibraryTrendCanvas','#editLibraryScatterCanvas','#editLibraryDensityPrimary'):await inspect(selector)
        await nav(page,'report')
        progress['status']='passed';persist()
        return results
    except Exception:
        progress['status']='failed';persist()
        raise
    finally:
        for name,handler in [('request',request_started),('requestfinished',request_finished),('requestfailed',request_failed)]:page.remove_listener(name,handler)
        persist()


async def verify(args,result):
    require(os.name=='nt' and platform.machine().upper() in ('AMD64','X86_64'),'Actual Windows x64 required; component probes are not native acceptance')
    sys.path[:0]=[str(args.helpers_root.resolve()),str(args.adapter_root.resolve()/'scripts'),str(args.adapter_root.resolve())]
    from playwright.async_api import async_playwright
    from generate_report_evidence_math import generate
    from verify_report_evidence_ui import verify_report_evidence_ui
    from deidentify_patient_source import export_case
    from windows_deidentified_package import unpack
    from windows_doctor_build import verify_content_manifest
    from verify_windows_doctor_browser import launch,stop,live_state,manager_page,resume,worklist_ready,pe_is_x64,process_modules,safe_error
    from ecg_core import doctor_source
    from ecg_core.repository import CaseRepository
    from ecg_core.ebi import load_records
    from ecg_core.stt import build_stt_review
    from ecg_core.stt_range import analyze_stt_range
    with tempfile.TemporaryDirectory(prefix='ui15-actual-PE-upgrade-') as temporary:
        work=Path(temporary);program0=unpack(args.base_software_archive,work/'base');program1=unpack(args.software_archive,work/'ui15')
        for program in (program0,program1):verify_content_manifest(program)
        package=program_identity(program0,program1);exe0=program0/'CardioInsightDoctorEval.exe';exe1=program1/'CardioInsightDoctorEval.exe'
        require(pe_is_x64(exe0) and pe_is_x64(exe1),'Both application executables must be actual x64 PE images')
        origin=work/'independent-math-origin';declaration=generate(origin)
        cases,issues=CaseRepository(origin).scan_cases();require(len(cases)==1 and not issues,'Independent math source is invalid')
        fixture=work/'sources/P01';export_case(cases[0],fixture,mathematical_fixture=True)
        source=doctor_source.validate_source(fixture)
        require(source['kind']=='mathematical_deidentified_fixture' and source['patient_inputs_read'] is False,'Only independent mathematical P01 is allowed')
        source_before=files(fixture)
        expected=build_stt_review('',fixture/doctor_source.PATHS['data'],load_records(str(fixture/doctor_source.PATHS['ebi'])),600,
            analysis_revision='independent-ui-upgrade-oracle')
        def current_oracle(items):return build_stt_review('',fixture/doctor_source.PATHS['data'],load_records(str(fixture/doctor_source.PATHS['ebi'])),600,analysis_revision='independent-ui-upgrade-oracle')
        def range_oracle(first,end,leads,items):return analyze_stt_range(fixture/doctor_source.PATHS['data'],load_records(str(fixture/doctor_source.PATHS['ebi'])),start_sample=first,end_sample=end,leads=leads,measurement_ms=60)
        home=work/'same-doctor-home';browser=None;context=None;page=None;checks=result['checks'];errors=[];blocked=[];after_writes=[]
        private=[str(home),str(fixture)];states=[];active=exe0;after_mode=False;primary_error=None
        try:
            async with async_playwright() as pw:
                browser=await pw.chromium.launch(channel='msedge',headless=True)
                result['browser']=dict(channel='msedge',installed_system_browser=True,version=browser.version)
                async def new_context():
                    c=await browser.new_context(viewport={'width':1440,'height':1000},service_workers='block',accept_downloads=False)
                    def observe_page(p):
                        p.on('pageerror',lambda e:errors.append(safe_error(e,private)))
                        p.on('download',lambda _:blocked.append({'kind':'download'}))
                    c.on('page',observe_page)
                    await c.add_init_script("""(()=>{const blocked=()=>{throw Error('Printing excluded from UI15-only upgrade verification')};window.print=blocked;const d=Object.getOwnPropertyDescriptor(HTMLIFrameElement.prototype,'contentWindow');Object.defineProperty(HTMLIFrameElement.prototype,'contentWindow',{...d,get(){const w=d.get.call(this);if(w)w.print=blocked;return w;}})})()""")
                    async def local_only(route):
                        url=urlsplit(route.request.url);path=url.path.lower()
                        if url.hostname not in ('127.0.0.1','localhost','::1') or path.endswith('.pdf') or '/report/pdf' in path or 'format=pdf' in url.query.lower():
                            blocked.append(dict(kind='external-or-PDF',path=url.path));await route.abort();return
                        if after_mode and '/api/cases/' in path and route.request.method not in ('GET','HEAD'):
                            after_writes.append(dict(method=route.request.method,path=url.path))
                            if not(route.request.method=='POST' and path.rsplit('/',1)[-1] in READONLY_POSTS):
                                blocked.append(dict(kind='clinical-write-after-upgrade',path=url.path));await route.abort();return
                        await route.continue_()
                    await c.route('**/*',local_only)
                    return c
                context=await new_context();manager,_=await launch(exe0,home,fixture);private.append(manager['token'])
                page=await manager_page(context,manager)
                async with page.expect_response(lambda r:urlsplit(r.url).path=='/continue'):await page.locator('#continueExperience').click()
                await worklist_ready(page)
                catalog=json.loads((home/'catalog.json').read_text());workspace=catalog['selected_workspace']
                state0=await live_state(home,workspace,exe0);private.append(state0['token']);states.append(dict(phase='base',pid=state0['pid'],birth=state0['birth']))
                modules0=await asyncio.to_thread(process_modules,state0['pid'],exe0);require(modules0['python_dll_from_bundle'],'Base process did not use bundled Python')
                await page.locator('#openFirstCase').click();await page.wait_for_function('id=>state.caseId===id&&!state.caseLoading',arg=doctor_source.CASE_ID)
                screenshots=args.output.parent/'ui-upgrade-screenshots';screenshots.mkdir(exist_ok=True)
                result['base_ui']=await verify_report_evidence_ui(page,doctor_source.CASE_ID,expected,screenshots,{'checks':[]},expected_for_annotations=current_oracle,range_oracle=range_oracle)
                await curate_and_approve(page,doctor_source.CASE_ID,checks)
                before=await capture(page,doctor_source.CASE_ID)
                await context.close();context=None;await stop(exe0,home)
                database=home/'workspaces'/workspace/'data/cardioinsight.db';db_before=database_state(database)
                ledger=db_before['tables'].get('stt_review_submissions');require(ledger and ledger['row_count']>=2,'Baseline must include nonempty actual UUID submission ledger')
                (args.output.parent/'ui-upgrade-before-report.json').write_text(json.dumps(before['report'],ensure_ascii=False,indent=2)+'\n')
                after_mode=True;active=exe1;context=await new_context();manager,_=await launch(exe1,home,fixture);private.append(manager['token'])
                page=await resume(context,manager,workspace)
                state1=await live_state(home,workspace,exe1);private.append(state1['token']);states.append(dict(phase='UI15',pid=state1['pid'],birth=state1['birth']))
                modules1=await asyncio.to_thread(process_modules,state1['pid'],exe1);require(modules1['python_dll_from_bundle'],'UI15 process did not use bundled Python')
                require((state0['pid'],state0['birth'])!=(state1['pid'],state1['birth']),'Upgrade reused the base workspace process')
                require(json.loads((home/'catalog.json').read_text())['selected_workspace']==workspace,'Upgrade selected a different workspace')
                opened_at=datetime.now(timezone.utc)
                await page.locator('#openFirstCase').click();await page.wait_for_function('id=>state.caseId===id&&!state.caseLoading',arg=doctor_source.CASE_ID)
                opened_by=datetime.now(timezone.utc)
                await nav(page,'report');after=await capture(page,doctor_source.CASE_ID)
                require(before==after,'UI repack changed engine/basis/reviewed report or selected evidence')
                result['geometry']=await af_geometry(page,doctor_source.CASE_ID)
                result['source_chart_inspection']=await source_chart_readonly(page,args.output.parent/'chart-inspection-progress.json')
                after_geometry=await capture(page,doctor_source.CASE_ID);require(before==after_geometry,'View-only geometry changed approved evidence')
                await context.close();context=None;await stop(exe1,home)
                db_after=database_state(database)
                audit_append=compare_database_states(db_before,db_after,doctor_source.CASE_ID,opened_at,opened_by)
                require(source_before==files(fixture),'Independent source mutated during native upgrade')
                require(not errors and not blocked,'Native page error, forbidden request or download occurred')
                (args.output.parent/'ui-upgrade-after-report.json').write_text(json.dumps(after['report'],ensure_ascii=False,indent=2)+'\n')
                checks.extend(['actual-PE-before-and-after-images-proved-by-owned-process-and-bundled-Python',
                    'same-home-source-fixture-workspace-database-and-recovery-epoch',
                    'engine-basis-review-revision-full-reviewed-report-and-all-curation-identical',
                    'all-non-audit-tables-identical-and-all-old-audit-rows-preserved-with-one-exact-case-open-append',
                    'current29-ST-records-report-purposes-manual-acknowledgements-and-nonempty-UUID-ledger-identical',
                    'UI15-native-AF-3-and-12-lead-height-gain-range-stable-at-1343-and-1800',
                    'actual15-15-source-chart-surfaces-ShiftEnter-100-150-200-300-percent-readonly-selection-and-plain-Enter-no-open'])
                result.update(status='passed',native_frozen_runtime=True,package_identity=package,
                    base_archive_sha256=sha256(args.base_software_archive.read_bytes()).hexdigest(),
                    ui_archive_sha256=sha256(args.software_archive.read_bytes()).hexdigest(),
                    fixture_profile=declaration['profile'],source_kind=source['kind'],fixture_sha256=source_before,
                    fixture_path_same=True,workspace_id_same=True,processes=states,reviewed_evidence=after['summary'],
                    existing_UUID_ledger_rows_preserved=ledger['row_count'],database={k:v for k,v in db_after.items() if not k.startswith('_')},metadata_table_exceptions=[audit_append],source_hashes_unchanged=True,
                    after_reopen_requests=after_writes,page_errors=errors,blocked_requests=blocked,
                    bundled_python_proved_both_processes=True,windows_system=platform.system(),windows_release=platform.release(),
                    hospital_physical_windows10_verified=False)
        except Exception as error:
            primary_error=error
            result.update(status='failed',error=safe_error(error,private),page_errors=errors,blocked_requests=blocked)
            if page and not page.is_closed():
                try:await page.screenshot(path=str(args.output.parent/'ui-upgrade-failure.png'))
                except Exception:pass
            raise
        finally:
            await cleanup_owned(context,browser,active,home,stop,result,primary_error,lambda e:safe_error(e,private))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base-software-archive',type=Path,required=True)
    parser.add_argument('--software-archive',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--adapter-root',type=Path,default=Path(__file__).resolve().parents[1])
    parser.add_argument('--helpers-root',type=Path,default=Path(__file__).resolve().parent)
    args=parser.parse_args();require(not args.output.exists(),'Preserve previous native attempts')
    args.output.parent.mkdir(parents=True,exist_ok=True)
    result=dict(status='running',scope='Actual Windows x64 PE base-to-UI15 external-asset upgrade on one independently generated P01 reviewed workspace',
        patient_inputs_read=False,patient_raw_copies=0,pdf_operations=0,print_operations=0,
        clinical_validation=False,native_frozen_runtime=False,checks=[])
    try:asyncio.run(verify(args,result))
    except Exception as error:
        result['status']='failed';result.setdefault('error',error_summary(error));raise
    finally:
        args.output.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
        print('WINDOWS_UI_UPGRADE_NATIVE_JSON='+json.dumps(result,ensure_ascii=False))


if __name__=='__main__':main()
