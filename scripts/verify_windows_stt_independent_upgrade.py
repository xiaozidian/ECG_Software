"""Actual Windows 1.0.13 -> 1.0.14 upgrade: preserve work, invalidate old review.

Both phases run their real x64 PE with bundled Python and system Edge. Only an
independent 600-second mathematical P01 is used. No patient input, printing,
PDF, network download, seeded approval, producer patch or guard bypass occurs.
"""
from __future__ import annotations

import argparse
import asyncio
import copy
from contextlib import closing
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import importlib.util
import json
import marshal
import os
from pathlib import Path
import platform
import re
import sqlite3
import sys
import tempfile
import types
from urllib.parse import urlencode, urlsplit

OLD_APP = '0.12.28-stt-hospital.20261103'
NEW_APP = '0.12.29-stt-independent.20261104'
NEW_ALGORITHM = 'stt-screening-0.3.2-independent-rhythm'
BASE_ARCHIVE_SHA256 = '9189488b0c953381011568a598b75330e2113561ed6755b1c2affb5661c671e5'
ORACLE_SHA256 = 'e326d252c6875acc89d44bcba4294b03a8e0ae951b93a43f6d6203ea162a2e39'
RANGE_ORACLE_SHA256 = 'de50cbc5273533afae4c6a6929ec25823a7ce0dd1afd2e935e484e0f108153f4'
RECORD_ORACLE_SHA256 = '08d004ad730ee08a227d520c3173db67f0505d24eb8f5bf9906caffe27120c8b'
DRIVER_SHA256 = '8ebc77e8b6d49cb133fcd006405be4c283084f5ee9e724b99f9e62bb0f723ca2'
UTILITY_SHA256 = 'cb03c5b188a5b67f5cc61ec7c188d0023ecb360e08f8924da6a5c72a7235d564'
READONLY_POSTS = {'open', 'scatter-selection', 'waveform-strips', 'event-waveforms',
                  'waveform-density', 'advanced-analysis', 'rr-locate', 'stt-range'}
LEDGER_COLUMNS = ['case_id', 'submission_id', 'annotation_id', 'operation', 'request_sha256']


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def fingerprint(value):
    # Match the existing report signing function, not the newer ST-record hash.
    return sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                             separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def exact(left, right, message):
    require(fingerprint(left) == fingerprint(right), message)


def files(root):
    return {p.relative_to(root).as_posix(): sha256(p.read_bytes()).hexdigest()
            for p in root.rglob('*') if p.is_file()}


def safe_error(error):
    value = re.sub(r"(?i)[a-z]:[\\/][^\s'\"><,;\]\)]+", '[local-path]', str(error))
    value = re.sub(r'(https?://[^\s?]+)\?[^\s]*', r'\1?[redacted]', value)
    value = re.sub(r'(?i)(token[=:]\s*)[a-f0-9]{32,}', r'\1[redacted]', value)
    return type(error).__name__ + ': ' + value[:900]


def program_identity(base, new):
    old = json.loads((base / 'RELEASE.json').read_text(encoding='utf-8-sig'))
    release = json.loads((new / 'RELEASE.json').read_text(encoding='utf-8-sig'))
    require(old['packaging_version'] == '1.0.13' and release['packaging_version'] == '1.0.14',
            'Expected verified 1.0.13 base and fresh 1.0.14 build')
    require(old['app_version'] == OLD_APP and release['app_version'] == NEW_APP,
            'Unexpected old/new application engine version')
    require(release['software_version'] == NEW_APP and not release.get('ui_repack_only', False),
            'An algorithm upgrade must not claim unchanged UI-only binary reuse')
    before, after = files(base), files(new)
    require(not any(n.startswith('Sources/') for n in before.keys() | after.keys()),
            'Both software archives must be source-free')
    require(before['CardioInsightDoctorEval.exe'] != after['CardioInsightDoctorEval.exe'],
            'New algorithm release incorrectly reused the old executable')
    for item in (old, release):
        require(item['source_id'] == 'P01' and item['source_data_bundled'] is False,
                'P01 software must use separately registered mathematical data')
        require(item['architecture'] == 'x64' and item['loopback_only'] is True,
                'Unexpected architecture or network profile')
    stamps = [json.loads((p / '_internal/shared-source-build.json').read_text(encoding='utf-8'))
              for p in (base, new)]
    require(stamps[0]['core_version'] != stamps[1]['core_version'],
            'Shared core identity did not change for the algorithm release')
    require(all('ecg_core/stt_records.py' in stamp['files'] for stamp in stamps), 'ST record module missing from old/new common manifest')
    return dict(base_exe_sha256=before['CardioInsightDoctorEval.exe'],
                new_exe_sha256=after['CardioInsightDoctorEval.exe'],
                base_packaging_version='1.0.13', new_packaging_version='1.0.14',
                base_app_version=OLD_APP, new_app_version=NEW_APP,
                base_source_commit=old['source_commit'], new_source_commit=release['source_commit'],
                base_core_version=stamps[0]['core_version'], new_core_version=stamps[1]['core_version'],
                production_source_identity=release['production_source_identity'])


def normalized_code(code):
    if not isinstance(code, types.CodeType):
        return code
    return code.replace(co_filename='<verified-source>',
                        co_consts=tuple(normalized_code(c) for c in code.co_consts))


def embedded_modules(exe, root):
    """Read actual PE/PYZ code and compare all runtime modules to CI source."""
    from PyInstaller.archive.readers import CArchiveReader
    reader = CArchiveReader(exe)
    pyzs = [n for n, row in reader.toc.items() if row[-1] == 'z']
    require(len(pyzs) == 1, 'Expected one embedded Python code archive')
    pyz = reader.open_embedded_archive(pyzs[0])
    paths = [root / 'app.py', root / 'win_doctor_eval.py', *sorted((root / 'ecg_core').glob('*.py'))]
    require(len(paths) == 40, 'Expected all 40 runtime Python files for this release')
    hashes = {}
    for path in paths:
        name = path.relative_to(root).as_posix()
        if name == 'win_doctor_eval.py':
            actual = marshal.loads(reader.extract('win_doctor_eval'))
        else:
            module = name[:-3].replace('/', '.')
            if module.endswith('.__init__'):
                module = module[:-9]
            require(module in pyz.toc, 'Runtime module missing from actual PE: ' + module)
            actual = pyz.extract(module)
        expected = compile(path.read_bytes(), name, 'exec', optimize=0, dont_inherit=True)
        require(normalized_code(actual) == normalized_code(expected),
                'Actual embedded code differs from frozen release source: ' + name)
        hashes[name] = sha256(path.read_bytes()).hexdigest()
    return dict(runtime_python_files_verified=len(hashes), runtime_python_sha256=hashes,
                includes_new_ST_record_module='ecg_core/stt_records.py' in hashes)


def database_state(path):
    # A sqlite connection context manager commits; closing() actually releases
    # Windows file handles before the temporary workspace is removed.
    with closing(sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True)) as db:
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA query_only=ON'); db.execute('PRAGMA trusted_schema=OFF'); db.execute('BEGIN')
        require(db.execute('PRAGMA integrity_check').fetchone()[0] == 'ok', 'Database integrity failed')
        require(db.execute('PRAGMA foreign_key_check').fetchone() is None, 'Database foreign-key integrity failed')
        names = [r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
        tables = {}
        for name in names:
            require(re.fullmatch('[A-Za-z_][A-Za-z0-9_]*', name), 'Unexpected SQL table identifier')
            columns = [r[1] for r in db.execute('PRAGMA table_info("' + name + '")')]
            rows = [dict(r) for r in db.execute('SELECT * FROM "' + name + '"')]
            tables[name] = dict(columns=columns, rows=sorted(rows, key=fingerprint))
        epochs = tables.get('workspace_recovery', {}).get('rows', [])
        epoch = next((r['epoch'] for r in epochs if r['id'] == 1), '')
    return dict(tables=tables, recovery_epoch=epoch)


def public_database(snapshot):
    return dict(recovery_epoch=snapshot['recovery_epoch'], tables={n: dict(columns=t['columns'],
        row_count=len(t['rows']), rows_sha256=fingerprint(t['rows'])) for n, t in snapshot['tables'].items()})


def one_case(snapshot, table, case_id):
    rows = snapshot['tables'][table]['rows']
    matches = [r for r in rows if r['case_id'] == case_id]
    require(len(matches) == 1 and len(rows) == 1, 'Expected one independent mathematical case in ' + table)
    return matches[0]


def current_basis(basis, app_version, exe_sha256):
    require(basis['schema'] == 1 and basis['engine']['app_version'] == app_version,
            'Unexpected current source-basis schema or engine version')
    require(basis['engine']['artifacts']['app'] == exe_sha256, 'Running engine is not bound to this actual PE')
    require(basis['engine_id'] == fingerprint(basis['engine']), 'Engine manifest identity is invalid')
    require(basis['digest'] == fingerprint({k: v for k, v in basis.items() if k not in ('digest', 'engine')}),
            'Source-basis digest is invalid')


def invalidated_composition(composition):
    result = copy.deepcopy(composition); result['category_reviews'] = {}
    for block in result.get('diagnosis_blocks', []):
        if block.get('manual'):
            block.update(needs_review=True, acknowledged=False)
    return result


def valid_timestamp(value, first, last):
    require(isinstance(value, str), 'Timestamp is not text')
    stamp = datetime.fromisoformat(value)
    require(stamp.tzinfo is not None and stamp.isoformat(timespec='seconds') == value,
            'Timestamp does not follow storage schema')
    require(first - timedelta(seconds=1) <= stamp <= last + timedelta(seconds=1),
            'Timestamp is outside actual native-upgrade interval')


def compare_database(before, after, case_id, first, last, old_basis, new_basis):
    left, right = before['tables'], after['tables']
    require(before['recovery_epoch'] == after['recovery_epoch'], 'Recovery epoch changed')
    require(set(right)==set(left), 'Database upgrade added/removed unexpected tables')
    require(left['stt_review_submissions']['columns']==LEDGER_COLUMNS
            and len(left['stt_review_submissions']['rows'])>=2,
            'Old visible ST create/update did not produce the real nonempty UUID ledger')
    exact(left['stt_review_submissions'],right['stt_review_submissions'],
          'Previously committed ST UUID submissions changed')
    mutable = {'case_analysis_basis', 'case_review', 'report_drafts', 'audit_log'}
    for name in left:
        exact(left[name]['columns'], right[name]['columns'], 'Existing SQL schema changed: ' + name)
        if name not in mutable:
            exact(left[name], right[name], 'Unexpected clinical/metadata/history mutation: ' + name)
    old, new = one_case(before, 'case_analysis_basis', case_id), one_case(after, 'case_analysis_basis', case_id)
    exact(json.loads(old['basis']), old_basis, 'Old stored basis differs from actual before engine')
    exact(json.loads(new['basis']), new_basis, 'New stored basis differs from actual after engine')
    expected = {**old, 'basis': new['basis'], 'updated_at': new['updated_at']}
    exact(new, expected, 'Unexpected basis row mutation'); valid_timestamp(new['updated_at'], first, last)
    old_review, new_review = one_case(before, 'case_review', case_id), one_case(after, 'case_review', case_id)
    expected = copy.deepcopy(old_review); expected['revision'] += 1
    steps = json.loads(expected['steps'])
    require(steps.get('edit',{}).get('status')=='done','Base edit workflow was not actually completed')
    for name in ('edit', 'stt'):
        if name in steps:steps[name].update(status='stale', reason='analysis.basis_changed')
    events = json.loads(expected['events'])
    for event in events.values():
        event['status'] = 'pending'
    expected['steps'] = new_review['steps']; expected['events'] = new_review['events']
    exact(json.loads(new_review['steps']), steps, 'Workflow invalidation changed unrelated fields')
    exact(json.loads(new_review['events']), events, 'Event invalidation changed unrelated fields')
    exact(new_review, expected, 'Unexpected review revision/row mutation')
    old_report, new_report = one_case(before, 'report_drafts', case_id), one_case(after, 'report_drafts', case_id)
    expected = {**old_report, 'status': 'draft', 'reviewed_by': '', 'version': old_report['version'] + 1,
                'composition': new_report['composition'], 'updated_at': new_report['updated_at']}
    exact(json.loads(new_report['composition']), invalidated_composition(json.loads(old_report['composition'])),
          'Report composition changed beyond existing acknowledgement invalidation')
    exact(new_report, expected, 'Conclusion, old provenance, selection or report history changed')
    valid_timestamp(new_report['updated_at'], first, last)
    audit0 = sorted(left['audit_log']['rows'], key=lambda r: r['id'])
    audit1 = sorted(right['audit_log']['rows'], key=lambda r: r['id'])
    exact(audit1[:len(audit0)], audit0, 'Old audit rows changed')
    added = audit1[len(audit0):]
    require(len(added) == 2, 'Expected exactly basis invalidation and actual case-open audit appends')
    actors = {r['actor'] for r in audit0 if r['case_id'] == case_id and r['action'] == 'case.open' and r['detail'] == ''}
    require(len(actors) == 1, 'Expected unique baseline case-open actor'); actor = next(iter(actors))
    for i, (row, action, detail) in enumerate(zip(added, ('analysis.basis_changed', 'case.open'),
                (old_basis['digest'] + ' -> ' + new_basis['digest'], ''))):
        require(set(row) == {'id', 'case_id', 'actor', 'action', 'detail', 'created_at'}, 'Audit columns changed')
        require(row['id'] == max((r['id'] for r in audit0), default=0) + i + 1 and row['case_id'] == case_id
                and row['actor'] == actor and row['action'] == action and row['detail'] == detail,
                'Unexpected audit append identity, action, actor or detail')
        valid_timestamp(row['created_at'], first, last)
    return dict(status='passed', existing_UUID_ledger_rows_preserved=len(left['stt_review_submissions']['rows']),
                invalidated_tables=sorted(mutable - {'audit_log'}), exact_preserved_tables=sorted(set(left) - mutable),
                audit_old_rows_preserved=True, audit_appended_actions=[r['action'] for r in added],
                old_provenance_preserved=True, original_conclusion_preserved=True,
                selected_events_and_curation_preserved=True, recovery_epoch_preserved=True)


def compare_api(before, after, package):
    old, new = before['report'], after['report']
    b0, b1 = old['current_analysis_basis'], new['current_analysis_basis']
    current_basis(b0, OLD_APP, package['base_exe_sha256']); current_basis(b1, NEW_APP, package['new_exe_sha256'])
    require(b0['engine_id'] != b1['engine_id'] and b0['digest'] != b1['digest'], 'New algorithm retained old engine/source basis')
    exact(b0['inputs'], b1['inputs'], 'The independent source changed during upgrade')
    require(b0.get('recovery_epoch', '') == b1.get('recovery_epoch', ''), 'Source-basis recovery epoch changed')
    require(all('ecg_core.stt_records' in b['engine']['artifacts'] for b in (b0,b1)),
            'Old/new executing engines did not bind the ST record module')
    for module in ('ecg_core.stt', 'ecg_core.stt_range', 'ecg_core.stt_records', 'ecg_core.storage'):
        require(b0['engine']['artifacts'][module] != b1['engine']['artifacts'][module], 'Expected actual module change missing: ' + module)
    require(old['status'] == 'reviewed' and old['reviewed_by'], 'Baseline report was not genuinely reviewed')
    require(before['workflow'].get('steps',{}).get('edit',{}).get('status')=='done',
            'Baseline edit checkpoint was not visibly completed')
    require(new['status'] == 'draft' and new['reviewed_by'] == '' and new['version'] == old['version'] + 1,
            'New engine did not invalidate the old report exactly once')
    require(new['review_revision'] == old['review_revision'] + 1, 'Unexpected analysis review revision')
    allowed = {'current_analysis_basis', 'current_hrv_reference', 'review_revision', 'reviewed_by', 'status', 'updated_at', 'version', 'composition'}
    exact({k: v for k, v in new.items() if k not in allowed}, {k: v for k, v in old.items() if k not in allowed},
          'Original conclusion, case identity or historic report proof changed')
    exact(new['composition'], invalidated_composition(old['composition']), 'Selected strip settings or unrelated report settings changed')
    exact(new['analysis_provenance'], old['analysis_provenance'], 'Old approval was rewritten or re-signed')
    require(new['analysis_provenance']['basis']['digest'] == b0['digest'] != b1['digest'], 'Old proof was silently re-signed')
    require(after['basis']['analysis_basis'] == b1['digest'] and after['basis']['analysis_revision'] == new['review_revision'],
            'New linked-read identity does not match report basis')
    r0,r1=before['beat_editor'].get('revision'),after['beat_editor'].get('revision')
    require(type(r0) is int and r0>=0 and type(r1) is int and r1>=0,
            'Actual beat-editor revision is missing or invalid')
    require(r0==r1, 'Upgrade modified the beat editor')
    h0,h1=old['current_hrv_reference'],new['current_hrv_reference']
    for reference,revision in ((h0,r0),(h1,r1)):
        linked=reference['scope'].get('beat_revision')
        require(type(linked) is int and linked>=0 and linked==revision,
                'Actual beat-editor revision differs from linked HRV scope')
    exact({k:v for k,v in h0.items() if k!='scope'},{k:v for k,v in h1.items() if k!='scope'},
          'Upgrade modified the HRV document, revision, window or profile')
    exact({k:v for k,v in h0['scope'].items() if k not in ('analysis_basis','analysis_revision')},
          {k:v for k,v in h1['scope'].items() if k not in ('analysis_basis','analysis_revision')},
          'Upgrade changed the HRV source or beat identity')
    require(h1['scope']['analysis_basis']==b1['digest'] and h1['scope']['analysis_revision']==new['review_revision'],
            'Current HRV reference did not adopt the new linked-read identity')
    require(after['workflow']['steps'].get('edit',{}).get('status')=='stale',
            'Old edit workflow remained confirmed')
    for name in ('edit','stt'):
        previous=before['workflow'].get('steps',{}).get(name)
        current=after['workflow']['steps'].get(name)
        if previous is None:require(current is None,'Upgrade invented a missing review checkpoint')
        else:exact(current,{**previous,'status':'stale','reason':'analysis.basis_changed'},
                   'Workflow invalidation changed more than its current status')
    require(after['workflow']['report_status'] == 'draft', 'Workflow still presents reviewed report')
    def stored(rows):
        result=[]
        for row in rows:
            value=copy.deepcopy(row);value.pop('stt_review_receipt',None);result.append(value)
        return result
    exact(stored(after['annotations']['items']),stored(before['annotations']['items']),
          'Stored annotation, range or old proof changed')
    picks = old['composition']['selected_events']; require(len(picks) == 6, 'Expected complete reviewed six-strip baseline')
    old_events = {e['event_id']: e for e in before['events']['items']}
    new_events = {e['event_id']: e for e in after['events']['items']}
    require(set(new_events) <= {p['event_id'] for p in picks}, 'Post-upgrade lookup substituted unrelated evidence')
    st_ids = [e['event_id'] for e in old_events.values() if e['category'] == 'ST']
    require(len(st_ids) == 1, 'Baseline must contain one scoped saved ST proof')
    for event_id in st_ids:
        event = new_events.get(event_id); require(event is not None, 'Historic scoped ST record disappeared')
        require(event['stt_review_state'] == 'stale' and event['stt_report_group'] == 'pending'
                and event['stt_report_eligibility'] == dict(table=False, text=False, strip=False)
                and event['diagnosis_status'] == 'pending', 'Old scoped ST record remained report-eligible')
        exact(event['stt_event_evidence'], old_events[event_id]['stt_event_evidence'], 'Old ST proof or complete range changed')
        old_row=next(a for a in before['annotations']['items'] if 'annotation:'+str(a['id'])==event_id)
        new_row=next(a for a in after['annotations']['items'] if 'annotation:'+str(a['id'])==event_id)
        require(old_row['stt_review_receipt']['review_state']=='reviewed', 'Old ST record was never genuinely reviewed')
        require(new_row['stt_review_receipt']['review_state']=='stale'
                and not any(new_row['stt_review_receipt']['report_eligibility'].values()),
                'Old-method ST annotation receipt stayed eligible')
        allowed_receipt={'review_state','report_group','report_eligibility'}
        exact({k:v for k,v in old_row['stt_review_receipt'].items() if k not in allowed_receipt},
              {k:v for k,v in new_row['stt_review_receipt'].items() if k not in allowed_receipt},
              'Old ST receipt identity, range, prose, protocol or intended report use changed')
        exact(old_row['stt_review_receipt']['measurement_protocol'],new_row['stt_review_receipt']['measurement_protocol'],
              'Historical whole method was relabelled')
        exact(old_row['stt_review_receipt']['point_measurement_protocol'],new_row['stt_review_receipt']['point_measurement_protocol'],
              'Historical point method was relabelled')
        require(old_row['stt_review_receipt']['measurement_protocol']['method_version']=='stt-hospital-review-v1',
                'Expected authentic old13 ST v1 reviewed evidence')
    require(after['stt']['analysis']['algorithm_version'] == NEW_ALGORITHM
            and after['stt']['analysis']['rhythm_policy']=='independent_of_AF_AFL_reviews'
            and after['stt']['analysis']['exclusions']['intervals']==[],
            'Actual new PE is not running independent ST 0.3.2')
    require(len(after['stt']['review_records']) >= 1, 'Historic ST record is absent from the new review queue')
    return dict(status='passed', base_engine_id=b0['engine_id'], new_engine_id=b1['engine_id'],
                base_analysis_basis=b0['digest'], new_analysis_basis=b1['digest'],
                base_report_version=old['version'], new_report_version=new['version'],
                old_reviewed_selected_count=6, preserved_selected_sha256=fingerprint(picks),
                preserved_original_conclusion_sha256=fingerprint(old['conclusion']),
                old_provenance_preserved_not_resigned=True, scoped_ST_records_ineligible=st_ids,
                new_ST_algorithm=NEW_ALGORITHM)


async def capture(page, case_id, get, *, after=False):
    report = await get(page, case_id, 'report')
    ids = list(dict.fromkeys(p['event_id'] for p in report['composition']['selected_events']))
    value = dict(report=report, basis=await get(page, case_id, 'analysis-basis'),
                 beat_editor=await get(page, case_id, 'beat-editor'),
                 events=await get(page, case_id, 'report-events?' + urlencode(dict(ids='|'.join(ids), limit=2000))),
                 annotations=await get(page, case_id, 'annotations'), workflow=await get(page, case_id, 'review-workflow'))
    if after:
        value['stt'] = await get(page, case_id, 'stt-review')
    return value


def load_legacy_oracles(helpers,adapter_root):
    """Load authentic old13 measurement code in a separate relative-import package."""
    package_name='_cardioinsight_upgrade_old13'
    package=types.ModuleType(package_name);package.__path__=[str(adapter_root/'ecg_core')]
    sys.modules[package_name]=package
    modules={}
    for name,filename,expected in (
            ('stt_records','stt_records_baseline_0_3_1.py',RECORD_ORACLE_SHA256),
            ('stt','stt_baseline_0_3_1.py',ORACLE_SHA256),
            ('stt_range','stt_range_baseline_0_3_1.py',RANGE_ORACLE_SHA256)):
        path=helpers/filename
        require(sha256(path.read_bytes()).hexdigest()==expected,'Authentic old13 measurement code changed: '+filename)
        spec=importlib.util.spec_from_file_location(package_name+'.'+name,path)
        module=importlib.util.module_from_spec(spec);sys.modules[spec.name]=module;spec.loader.exec_module(module)
        modules[name]=module
    require(modules['stt'].ALGORITHM_VERSION=='stt-screening-0.3.1-hospital-records-rhythm-masks'
            and modules['stt_range'].PROFILE_ID=='raw-200hz-fixed16s-st-perbeat-mean-v1'
            and modules['stt_records'].METHOD=='stt-hospital-review-v1',
            'The old13 oracle was replaced by a newer algorithm')
    require(modules['stt_range']._block_measurement is modules['stt']._block_measurement,
            'Old range oracle imported current rather than authentic old measurement code')
    require(modules['stt'].SAMPLE_RATE==200 and modules['stt'].CHANNEL_COUNT==8,'Old source geometry changed')
    return modules['stt'],modules['stt_range'],modules['stt_records']


def cleanup_temporary(temporary, result, primary_error=None):
    try:
        temporary.cleanup()
    except Exception as error:
        result.setdefault('cleanup_errors', []).append(dict(operation='temporary_workspace.cleanup', error=safe_error(error)))
        result.update(status='failed', native_frozen_runtime=False, native_upgrade_verified=False)
        if primary_error is None:
            raise


async def curate_old13_and_approve(page,case_id,checks):
    """Only visible controls create the reviewed baseline; no seeded approval."""
    from verify_windows_ui_upgrade_native import get,nav,tab,settled
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
    for step in ('edit',):
        workflow=await get(page,case_id,'review-workflow')
        if workflow['steps'].get(step,{}).get('status')=='done':continue
        await nav(page,step)
        if step=='stt':await page.wait_for_function('()=>sttWaveformIsCurrent()')
        await page.locator('#workflowNext').click();dialog=page.locator('#workflowConfirmDialog[open]')
        await dialog.wait_for(state='visible');await page.locator('#workflowConfirmed').check()
        await page.locator('#workflowNote').fill('Independent mathematical software upgrade acceptance; not a clinical diagnosis.')
        await page.locator('#workflowConfirmSubmit').click();await page.locator('#workflowConfirmDialog[open]').wait_for(state='detached')
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
    await page.locator('#conclusionEditor').fill('Mathematical ST-method upgrade verification; no clinical conclusion.')
    await page.locator('#conclusionEditor').press('Tab')
    await page.wait_for_function("()=>state.report?.conclusion==='Mathematical ST-method upgrade verification; no clinical conclusion.'&&!state.reportDirty&&!state.reportSaving")
    await settled(page)
    await page.wait_for_function('()=>!document.querySelector("#approveReport").disabled')
    await page.locator('#approveReport').click();await page.wait_for_function('()=>state.report.status==="reviewed"');await settled(page)
    report=await get(page,case_id,'report');require(len(report['composition']['selected_events'])==6,'Native base fixture selection count changed')
    counts={len(p['leads']) for p in report['composition']['selected_events']}
    require({1,3,12}<=counts,'Baseline did not preserve independent 1/3/12-lead curation')
    checks.append('actual-base-PE-visible-UI-created-reviewed-six-strips-with-four-AF-and-1-3-12-lead-curation')


async def verify(args, result):
    require(os.name == 'nt' and platform.machine().upper() in ('AMD64', 'X86_64'),
            'Actual Windows x64 PE is mandatory; pure probes are not native acceptance')
    require(sha256(args.base_software_archive.read_bytes()).hexdigest() == BASE_ARCHIVE_SHA256,
            'Old P01 archive does not match verified immutable 1.0.13 bytes')
    sys.path[:0] = [str(args.helpers_root.resolve()), str(args.adapter_root.resolve() / 'scripts'), str(args.adapter_root.resolve())]
    for name, expected in [('stt_baseline_0_3_1.py', ORACLE_SHA256),
                           ('stt_range_baseline_0_3_1.py',RANGE_ORACLE_SHA256),
                           ('stt_records_baseline_0_3_1.py',RECORD_ORACLE_SHA256),
                           ('legacy13_report_evidence_ui.py', DRIVER_SHA256)]:
        require(sha256((args.helpers_root / name).read_bytes()).hexdigest() == expected, 'Authentic old oracle/driver changed: ' + name)
    utility_spec=importlib.util.find_spec('verify_windows_ui_upgrade_native')
    require(utility_spec is not None and sha256(Path(utility_spec.origin).read_bytes()).hexdigest()==UTILITY_SHA256,
            'Reliable raw-JSON/cleanup/base-curation helper changed')
    from playwright.async_api import async_playwright
    from generate_report_evidence_math import generate
    from legacy13_report_evidence_ui import verify_report_evidence_ui
    from deidentify_patient_source import export_case
    from windows_deidentified_package import unpack
    from windows_doctor_build import verify_content_manifest
    from verify_windows_doctor_browser import launch, stop, live_state, manager_page, resume, worklist_ready, pe_is_x64, process_modules
    from verify_windows_ui_upgrade_native import get, cleanup_owned, assert_reviewed
    from ecg_core import doctor_source
    from ecg_core.repository import CaseRepository
    from ecg_core.ebi import load_records
    oracle,range_engine,record_engine=load_legacy_oracles(args.helpers_root,args.adapter_root)
    temporary = tempfile.TemporaryDirectory(prefix='stt14-actual-PE-upgrade-'); primary_error = None
    try:
        work = Path(temporary.name); old_program = unpack(args.base_software_archive, work / 'old'); new_program = unpack(args.software_archive, work / 'new')
        for program in (old_program, new_program):
            verify_content_manifest(program)
        package = program_identity(old_program, new_program)
        exe0, exe1 = old_program / 'CardioInsightDoctorEval.exe', new_program / 'CardioInsightDoctorEval.exe'
        require(pe_is_x64(exe0) and pe_is_x64(exe1), 'Both images must be actual Windows x64 PE executables')
        result['embedded_new_runtime'] = embedded_modules(exe1, args.adapter_root)
        origin = work / 'independent-math-origin'; declaration = generate(origin)
        cases, issues = CaseRepository(origin).scan_cases(); require(len(cases) == 1 and not issues, 'Independent 600s mathematical source is invalid')
        fixture = work / 'sources/P01'; export_case(cases[0], fixture, mathematical_fixture=True)
        source = doctor_source.validate_source(fixture)
        require(source['kind'] == 'mathematical_deidentified_fixture' and source['patient_inputs_read'] is False, 'Only independent mathematical P01 is permitted')
        source_before = files(fixture)
        raw=fixture/doctor_source.PATHS['data'];records=load_records(str(fixture/doctor_source.PATHS['ebi']))
        def expected_for_annotations(items):
            return oracle.build_stt_review('',raw,records,600,analysis_revision='authentic-old-1.0.13-upgrade-oracle',
                                           excluded_intervals=record_engine.rhythm_exclusions(items))
        def range_oracle(first,end,leads,items):
            return range_engine.analyze_stt_range(raw,records,start_sample=first,end_sample=end,leads=leads,
                                                  measurement_ms=60,exclusions=record_engine.rhythm_exclusions(items))
        expected=expected_for_annotations([])
        home = work / 'same-home'; browser = context = page = None; active = exe0; after_mode = False
        errors, blocked, after_requests = [], [], []; checks = result['checks']; owned_error = None
        async with async_playwright() as pw:
            try:
                browser = await pw.chromium.launch(channel='msedge', headless=True)
                result['browser'] = dict(channel='msedge', installed_system_browser=True, version=browser.version)
                async def make_context():
                    c = await browser.new_context(viewport={'width': 1440, 'height': 1000}, service_workers='block', accept_downloads=False)
                    def observe(p):
                        p.set_default_timeout(90000); p.set_default_navigation_timeout(90000)
                        p.on('pageerror', lambda e: errors.append(safe_error(e)))
                        p.on('download', lambda _: blocked.append(dict(kind='download')))
                    c.on('page', observe)
                    await c.add_init_script("""(()=>{const deny=()=>{throw Error('Printing excluded from mathematical native upgrade verification')};window.print=deny;const d=Object.getOwnPropertyDescriptor(HTMLIFrameElement.prototype,'contentWindow');Object.defineProperty(HTMLIFrameElement.prototype,'contentWindow',{...d,get(){const w=d.get.call(this);if(w)w.print=deny;return w;}})})()""")
                    async def local_only(route):
                        parsed = urlsplit(route.request.url); path = parsed.path.lower(); method = route.request.method
                        if parsed.hostname not in ('127.0.0.1', 'localhost', '::1') or path.endswith('.pdf') or '/report/pdf' in path or 'format=pdf' in parsed.query.lower():
                            blocked.append(dict(kind='external-or-PDF', path=parsed.path)); await route.abort(); return
                        if after_mode and '/api/cases/' in path and method not in ('GET', 'HEAD'):
                            after_requests.append(dict(method=method, path=parsed.path))
                            if not (method == 'POST' and path.rsplit('/', 1)[-1] in READONLY_POSTS):
                                blocked.append(dict(kind='clinical-write-after-upgrade', path=parsed.path)); await route.abort(); return
                        await route.continue_()
                    await c.route('**/*', local_only); return c
                context = await make_context(); manager, _ = await launch(exe0, home, fixture)
                page = await manager_page(context, manager)
                async with page.expect_response(lambda r: urlsplit(r.url).path == '/continue'):
                    await page.locator('#continueExperience').click()
                await worklist_ready(page)
                workspace = json.loads((home / 'catalog.json').read_text())['selected_workspace']
                state0 = await live_state(home, workspace, exe0)
                module0 = await asyncio.to_thread(process_modules, state0['pid'], exe0)
                require(module0['python_dll_from_bundle'], 'Old actual process did not use bundled Python')
                await page.locator('#openFirstCase').click()
                await page.wait_for_function('id=>typeof state!=="undefined"&&state.caseId===id&&!state.caseLoading', arg=doctor_source.CASE_ID)
                shots = args.output.parent / 'stt-upgrade-screenshots'; shots.mkdir(exist_ok=True)
                result['old_native_ui'] = await verify_report_evidence_ui(page, doctor_source.CASE_ID, expected, shots, {'checks': []},
                    expected_for_annotations=expected_for_annotations,range_oracle=range_oracle)
                require(result['old_native_ui']['status'] == 'passed' and len(result['old_native_ui']['checks']) == 12,
                        'Complete authentic old13 twelve-check fixture did not pass')
                await curate_old13_and_approve(page, doctor_source.CASE_ID, checks)
                before = await capture(page, doctor_source.CASE_ID, get)
                result['before_reviewed'] = assert_reviewed(before['report'], before['basis'], before['events'])
                await context.close(); context = None; await stop(exe0, home)
                database = home / 'workspaces' / workspace / 'data/cardioinsight.db'; db0 = database_state(database)
                (args.output.parent / 'stt-upgrade-before-report.json').write_text(json.dumps(before['report'], ensure_ascii=False, indent=2) + '\n')
                after_mode = True; active = exe1; first = datetime.now(timezone.utc)
                context = await make_context(); manager, _ = await launch(exe1, home, fixture)
                page = await resume(context, manager, workspace)
                state1 = await live_state(home, workspace, exe1)
                module1 = await asyncio.to_thread(process_modules, state1['pid'], exe1)
                require(module1['python_dll_from_bundle'], 'New actual process did not use bundled Python')
                require((state0['pid'], state0['birth']) != (state1['pid'], state1['birth']), 'Upgrade reused the old process')
                require(json.loads((home / 'catalog.json').read_text())['selected_workspace'] == workspace, 'Upgrade switched the doctor workspace')
                await page.locator('#openFirstCase').click()
                await page.wait_for_function('id=>typeof state!=="undefined"&&state.caseId===id&&!state.caseLoading', arg=doctor_source.CASE_ID)
                after = await capture(page, doctor_source.CASE_ID, get, after=True)
                api_proof = compare_api(before, after, package)
                # Read-only repetition cannot re-sign, approve, or increment a revision.
                again = await capture(page, doctor_source.CASE_ID, get, after=True)
                exact(after, again, 'Repeated read-only inspection changed current evidence')
                await context.close(); context = None; await stop(exe1, home); last = datetime.now(timezone.utc)
                db1 = database_state(database)
                db_proof = compare_database(db0, db1, doctor_source.CASE_ID, first, last,
                                            before['report']['current_analysis_basis'], after['report']['current_analysis_basis'])
                require(source_before == files(fixture), 'Independent source bytes changed')
                require(not errors and not blocked, 'Page error, forbidden request, clinical write, print or download occurred')
                (args.output.parent / 'stt-upgrade-after-report.json').write_text(json.dumps(after['report'], ensure_ascii=False, indent=2) + '\n')
                checks.extend(['actual-old-1.0.13-and-new-1.0.14-x64-PE-with-bundled-Python-and-system-Edge',
                    'new-actual-40-module-code-matches-current-frozen-release-source',
                    'same-mathematical-source-home-workspace-database-and-recovery-epoch',
                    'engine-and-source-basis-change-invalidates-old-reviewed-report-without-re-signing',
                    'old-six-picks-all-curation-annotations-proof-and-original-conclusion-preserved',
                    'old-scoped-ST-visible-stale-and-ineligible-for-all-three-uses',
                    'existing-nonempty-UUID-ledger-and-clinical-rows-exact-with-only-basis-review-report-invalidation-and-two-audits',
                    'repeated-readonly-inspection-never-adds-a-review-or-clinical-write'])
                result.update(package_identity=package, base_archive_sha256=BASE_ARCHIVE_SHA256,
                    new_archive_sha256=sha256(args.software_archive.read_bytes()).hexdigest(), fixture_profile=declaration['profile'],
                    fixture_sha256=source_before, source_kind=source['kind'], source_hashes_unchanged=True,
                    actual_processes=[dict(phase='old1.0.13', pid=state0['pid'], birth=state0['birth']), dict(phase='new1.0.14', pid=state1['pid'], birth=state1['birth'])],
                    bundled_python_proved_both_processes=True, api_upgrade=api_proof, database_upgrade=db_proof,
                    database_before=public_database(db0), database_after=public_database(db1),
                    after_reopen_requests=after_requests, page_errors=errors, blocked_requests=blocked,
                    windows_system=platform.system(), windows_release=platform.release(), hospital_physical_windows10_verified=False)
            except Exception as error:
                owned_error = error
                if page and not page.is_closed():
                    try:
                        await page.screenshot(path=str(args.output.parent / 'stt-upgrade-failure.png'))
                    except Exception:
                        pass
                raise
            finally:
                await cleanup_owned(context, browser, active, home, stop, result, owned_error, safe_error)
    except Exception as error:
        primary_error = error
        result.update(status='failed', native_frozen_runtime=False, native_upgrade_verified=False, error=safe_error(error))
        raise
    finally:
        cleanup_temporary(temporary, result, primary_error)
    result.update(status='passed', native_frozen_runtime=True, native_upgrade_verified=True)


def probe_comparators():
    """Independent fabricated receipts; never substitute this for actual PE CI."""
    case = 'math-probe'; old_stamp = '2026-01-01T08:00:00+00:00'; stamp = '2026-01-01T09:00:00+00:00'
    first = datetime.fromisoformat(stamp); last = first + timedelta(seconds=10)
    package = dict(base_exe_sha256='a' * 64, new_exe_sha256='b' * 64)
    def basis(app, executable, new=False):
        artifacts = {'app': executable, **{n: ('d' if new else 'c') * 64 for n in
            ('ecg_core.stt', 'ecg_core.stt_range', 'ecg_core.storage', 'ecg_core.stt_records')}}
        engine = dict(app_version=app, artifacts=artifacts, dependencies={'python': 'probe-only'}, sample_rate_hz=200, channels=8)
        body = dict(schema=1, engine_id=fingerprint(engine), recovery_epoch='same-epoch',
                    inputs={'data': dict(bytes=1920000, sha256='f' * 64)})
        return {**body, 'digest': fingerprint(body), 'engine': engine}
    b0, b1 = basis(OLD_APP, package['base_exe_sha256']), basis(NEW_APP, package['new_exe_sha256'], True)
    picks = [dict(event_id='annotation:1', basis_version='old-ST', caption='数学旧图注', leads=['II'], duration_s=7.0),
             dict(event_id='local-pick:1', basis_version='old-other', caption='保留附注', leads=['II','V1','V5'], duration_s=7)]
    picks += [dict(event_id='annotation:AF', basis_version='old-AF', strip_id='af:' + str(i),
                   leads=['I','II','III','aVR','aVL','aVF','V1','V2','V3','V4','V5','V6'],
                   range_start_s=20.0 + i * 50, range_end_s=27.0 + i * 50, duration_s=7) for i in range(4)]
    composition = dict(selected_events=picks, category_reviews={'ST':'old-ST'},
        diagnosis_blocks=[dict(key='manual-note', text='医生原文', manual=True, needs_review=False, acknowledged=True)])
    old_protocol=dict(method_version='stt-hospital-review-v1',measurement_ms=60,extent='whole',
                      baseline_method='pre_qrs_stable',units='source_device_units',calibration_verified=False)
    point_protocol={**old_protocol,'extent':'point','baseline_method':'manual_iso_point'}
    proof = dict(kind='st_depression', duration_s=240, start_s=112, end_s=352,measurement_protocol=old_protocol,
                 scope=dict(case_id=case, analysis_basis=b0['digest'], beat_revision=0))
    annotation = dict(id=1, case_id=case, sample_index=22400, lead='II', note='原始复核',
                      details=dict(kind='ST', status='confirmed',reviewed=True,measurement_protocol=point_protocol,
                                   end_sample=70399, stt_event_evidence=proof))
    receipt=dict(review_state='reviewed',measurement_protocol=old_protocol,point_measurement_protocol=point_protocol,
                 report_eligibility=dict(table=True,text=True,strip=True))
    annotated0={**annotation,'stt_review_receipt':receipt}
    annotated1={**annotation,'stt_review_receipt':{**receipt,'review_state':'stale',
                 'report_eligibility':dict(table=False,text=False,strip=False)}}
    report0 = dict(case_id=case, status='reviewed', reviewed_by='math-doctor', version=7,
        review_revision=3, updated_at=old_stamp, conclusion='数学原结论', composition=composition,
        analysis_provenance=dict(basis=b0, composition_sha256=fingerprint(composition)),
        current_analysis_basis=b0, current_hrv_reference=dict(hrv_revision=0,document_digest='same-HRV',profile='same-profile',window_index=0,
            scope=dict(case_id=case,source_digest='same-source',data_version='same-beats',beat_revision=0,analysis_basis=b0['digest'],analysis_revision=3)))
    report1 = {**copy.deepcopy(report0), 'status':'draft', 'reviewed_by':'', 'version':8,
               'review_revision':4, 'updated_at':stamp, 'composition':invalidated_composition(composition),
               'current_analysis_basis':b1, 'current_hrv_reference':{**report0['current_hrv_reference'],
                   'scope':{**report0['current_hrv_reference']['scope'],'analysis_basis':b1['digest'],'analysis_revision':4}}}
    events0 = [dict(event_id='annotation:1', category='ST', stt_event_evidence=proof),
               dict(event_id='local-pick:1', category='other'), dict(event_id='annotation:AF', category='AF')]
    events1 = [dict(event_id='annotation:1', category='ST', stt_event_evidence=proof,
                   stt_review_state='stale', stt_report_group='pending', diagnosis_status='pending',
                   stt_report_eligibility=dict(table=False,text=False,strip=False)), events0[-1]]
    steps=dict(edit=dict(status='done',actor='math-doctor'))
    after_steps={k:{**v,'status':'stale','reason':'analysis.basis_changed'} for k,v in steps.items()}
    api0 = dict(report=report0, basis=dict(analysis_basis=b0['digest'], analysis_revision=3),beat_editor=dict(revision=0),
                events={'items':events0}, annotations={'items':[annotated0]}, workflow=dict(steps=copy.deepcopy(steps),report_status='reviewed'))
    api1 = dict(report=report1, basis=dict(analysis_basis=b1['digest'], analysis_revision=4),beat_editor=dict(revision=0),
        events={'items':events1}, annotations={'items':[annotated1]},
        workflow=dict(steps=after_steps,report_status='draft'),
        stt=dict(analysis={'algorithm_version':NEW_ALGORITHM,'rhythm_policy':'independent_of_AF_AFL_reviews',
                          'exclusions':{'intervals':[]}},review_records=[annotated1]))
    review_events = {'V:200':dict(status='retained',note='保留原文')}
    def table(columns, rows):
        return dict(columns=columns.split(), rows=rows)
    report_row = {k:report0[k] for k in ('case_id','conclusion','status','version','reviewed_by','updated_at')}
    report_row.update(composition=json.dumps(composition,ensure_ascii=False), analysis_provenance=json.dumps(report0['analysis_provenance'],ensure_ascii=False))
    audit = [dict(id=1,case_id=case,actor='math-doctor',action='case.open',detail='',created_at=old_stamp)]
    db0 = dict(recovery_epoch='same-epoch', tables={
        'annotations':table('id case_id sample_index details', [dict(id=1,case_id=case,sample_index=22400,details=json.dumps(annotation['details']))]),
        'case_analysis_basis':table('case_id basis updated_at',[dict(case_id=case,basis=json.dumps(b0),updated_at=old_stamp)]),
        'case_review':table('case_id revision steps events',[dict(case_id=case,revision=3,steps=json.dumps(steps),events=json.dumps(review_events))]),
        'report_drafts':table('case_id conclusion composition status version reviewed_by updated_at analysis_provenance',[report_row]),
        'audit_log':table('id case_id actor action detail created_at',audit),
        'stt_review_submissions':dict(columns=LEDGER_COLUMNS,rows=[
            dict(case_id=case,submission_id='00000000-0000-4000-8000-000000000001',annotation_id=1,operation='create',request_sha256='a'*64),
            dict(case_id=case,submission_id='00000000-0000-4000-8000-000000000002',annotation_id=1,operation='update',request_sha256='b'*64)]),
        'report_evidence_reviews':table('case_id descriptor status',[dict(case_id=case,descriptor='old-proof',status='confirmed')]),
        'workspace_recovery':table('id epoch',[dict(id=1,epoch='same-epoch')])})
    db1 = copy.deepcopy(db0); t = db1['tables']
    t['case_analysis_basis']['rows'][0].update(basis=json.dumps(b1),updated_at=stamp)
    for value in steps.values(): value.update(status='stale',reason='analysis.basis_changed')
    for value in review_events.values(): value['status']='pending'
    t['case_review']['rows'][0].update(revision=4,steps=json.dumps(steps),events=json.dumps(review_events))
    t['report_drafts']['rows'][0].update(status='draft',reviewed_by='',version=8,updated_at=stamp,
        composition=json.dumps(invalidated_composition(composition),ensure_ascii=False))
    t['audit_log']['rows'] += [dict(id=2,case_id=case,actor='math-doctor',action='analysis.basis_changed',detail=b0['digest']+' -> '+b1['digest'],created_at=stamp),
                             dict(id=3,case_id=case,actor='math-doctor',action='case.open',detail='',created_at=stamp)]
    checks=[]
    compare_api(api0,api1,package); checks.append('valid-new-engine-invalidation-and-preserved-six-picks')
    requested=[]
    async def mathematical_get(page, requested_case, kind):
        require(requested_case==case, 'Capture substituted a different case')
        requested.append(kind)
        key={'report':'report','analysis-basis':'basis','beat-editor':'beat_editor',
             'annotations':'annotations','review-workflow':'workflow'}.get(kind)
        if kind.startswith('report-events?'):
            key='events'
        require(key is not None, 'Unexpected endpoint in read-only capture probe')
        return copy.deepcopy(api0[key])
    captured=asyncio.run(capture(None,case,mathematical_get))
    exact(captured,api0,'Read-only capture changed the actual endpoint envelopes')
    require(requested.count('beat-editor')==1 and set(captured['basis'])=={'analysis_basis','analysis_revision'},
            'Capture did not read the real beat-editor endpoint separately')
    checks.append('capture-uses-real-two-field-basis-and-separate-readonly-beat-editor')
    compare_database(db0,db1,case,first,last,b0,b1); checks.append('valid-exact-nonempty-UUID-ledger-preservation-and-two-audit-appends')
    def reject_api(name, mutation):
        value=copy.deepcopy(api1);mutation(value)
        try:compare_api(api0,value,package)
        except AssertionError:checks.append(name);return
        raise AssertionError('Comparator accepted '+name)
    reject_api('reject-report-left-reviewed',lambda x:x['report'].update(status='reviewed',reviewed_by='math-doctor'))
    reject_api('reject-original-conclusion-change',lambda x:x['report'].update(conclusion='tampered'))
    reject_api('reject-selected-lead-change',lambda x:x['report']['composition']['selected_events'][0].update(leads=['V5']))
    reject_api('reject-old-proof-re-signing',lambda x:x['report']['analysis_provenance'].update(basis=b1))
    reject_api('reject-old-ST-still-table-eligible',lambda x:x['events']['items'][0]['stt_report_eligibility'].update(table=True))
    reject_api('reject-old-annotation-receipt-stays-reviewed',lambda x:x['annotations']['items'][0]['stt_review_receipt'].update(review_state='reviewed'))
    reject_api('reject-old-point-method-relabelled',lambda x:x['annotations']['items'][0]['stt_review_receipt']['point_measurement_protocol'].update(method_version='stt-hospital-review-v2'))
    reject_api('reject-old-whole-method-relabelled',lambda x:x['annotations']['items'][0]['stt_review_receipt']['measurement_protocol'].update(method_version='stt-hospital-review-v2'))
    reject_api('reject-old-receipt-extra-or-changed-prose',lambda x:x['annotations']['items'][0]['stt_review_receipt'].update(note='tampered'))
    reject_api('reject-new-AF-cross-mask',lambda x:x['stt']['analysis']['exclusions']['intervals'].append({'reason':'rhythm_AF'}))
    reject_api('reject-invented-global-ST-checkpoint',lambda x:x['workflow']['steps'].update(stt={'status':'stale'}))
    reject_api('reject-old-ST-disappears',lambda x:x['events']['items'].pop(0))
    reject_api('reject-record-proof-range-change',lambda x:x['annotations']['items'][0]['details']['stt_event_evidence'].update(end_s=353))
    reject_api('reject-unchanged-beat-revision-violation',lambda x:x['beat_editor'].update(revision=1))
    reject_api('reject-missing-actual-beat-editor-revision',lambda x:x['beat_editor'].pop('revision'))
    reject_api('reject-boolean-actual-beat-editor-revision',lambda x:x['beat_editor'].update(revision=False))
    reject_api('reject-negative-actual-beat-editor-revision',lambda x:x['beat_editor'].update(revision=-1))
    reject_api('reject-missing-linked-HRV-beat-revision',lambda x:x['report']['current_hrv_reference']['scope'].pop('beat_revision'))
    reject_api('reject-mismatched-linked-HRV-beat-revision',lambda x:x['report']['current_hrv_reference']['scope'].update(beat_revision=1))
    reject_api('reject-boolean-linked-HRV-beat-revision',lambda x:x['report']['current_hrv_reference']['scope'].update(beat_revision=False))
    reject_api('reject-HRV-document-change',lambda x:x['report']['current_hrv_reference'].update(document_digest='tampered'))
    def reject_db(name, mutation):
        value=copy.deepcopy(db1);mutation(value)
        try:compare_database(db0,value,case,first,last,b0,b1)
        except AssertionError:checks.append(name);return
        raise AssertionError('Comparator accepted '+name)
    reject_db('reject-unexpected-empty-table',lambda x:x['tables'].update(extra=table('id',[])))
    reject_db('reject-UUID-ledger-row-growth',lambda x:x['tables']['stt_review_submissions']['rows'].append({'case_id':case}))
    reject_db('reject-UUID-ledger-deletion',lambda x:x['tables']['stt_review_submissions']['rows'].clear())
    reject_db('reject-UUID-ledger-content-change',lambda x:x['tables']['stt_review_submissions']['rows'][0].update(request_sha256='0'*64))
    reject_db('reject-new-table-schema-change',lambda x:x['tables']['stt_review_submissions']['columns'].append('extra'))
    reject_db('reject-annotation-history-edit',lambda x:x['tables']['annotations']['rows'][0].update(sample_index=22500))
    reject_db('reject-confirmation-history-edit',lambda x:x['tables']['report_evidence_reviews']['rows'][0].update(status='pending'))
    reject_db('reject-report-original-conclusion-edit',lambda x:x['tables']['report_drafts']['rows'][0].update(conclusion='tampered'))
    reject_db('reject-report-original-proof-edit',lambda x:x['tables']['report_drafts']['rows'][0].update(analysis_provenance='{}'))
    reject_db('reject-report-version-jump',lambda x:x['tables']['report_drafts']['rows'][0].update(version=9))
    reject_db('reject-review-revision-jump',lambda x:x['tables']['case_review']['rows'][0].update(revision=5))
    reject_db('reject-old-audit-modification',lambda x:x['tables']['audit_log']['rows'][0].update(detail='tampered'))
    reject_db('reject-extra-audit-action',lambda x:x['tables']['audit_log']['rows'][-1].update(action='report.reviewed'))
    reject_db('reject-three-audit-appends',lambda x:x['tables']['audit_log']['rows'].append({**x['tables']['audit_log']['rows'][-1],'id':4}))
    reject_db('reject-wrong-case-audit',lambda x:x['tables']['audit_log']['rows'][-1].update(case_id='other-math'))
    reject_db('reject-wrong-audit-actor',lambda x:x['tables']['audit_log']['rows'][-1].update(actor='other'))
    reject_db('reject-out-of-window-invalidation-time',lambda x:x['tables']['case_analysis_basis']['rows'][0].update(updated_at=old_stamp))
    reject_db('reject-recovery-epoch-change',lambda x:x.update(recovery_epoch='different'))
    require(fingerprint({'中文':20.0})!=fingerprint({'中文':20}), 'Existing signing must retain original JSON numeric form')
    checks.append('existing-report-signature-does-not-normalize-floats-or-Chinese')
    class BadTemporary:
        def cleanup(self):raise RuntimeError('mathematical cleanup error')
    result={};primary=ValueError('mathematical primary error')
    try:
        try:raise primary
        finally:cleanup_temporary(BadTemporary(),result,primary)
    except ValueError as error:require(error is primary, 'Cleanup masked primary error')
    require(len(result['cleanup_errors'])==1 and result['status']=='failed', 'Cleanup error was swallowed')
    checks.append('temporary-cleanup-keeps-primary-and-records-secondary')
    try:cleanup_temporary(BadTemporary(),{})
    except RuntimeError:checks.append('cleanup-only-failure-is-fatal')
    else:raise AssertionError('Cleanup-only failure was accepted')
    with tempfile.TemporaryDirectory(prefix='stt-upgrade-probe-') as tmp:
        path=Path(tmp)/'math.sqlite3'
        with closing(sqlite3.connect(path)) as db:db.execute('CREATE TABLE math(id INTEGER)');db.commit()
        require(database_state(path)['tables']['math']['rows']==[], 'Read-only snapshot mismatch')
        path.unlink()
    checks.append('read-only-SQLite-snapshot-explicitly-closes-owned-connection')
    import __future__
    sample = b'value: MissingType = 1\n'
    inherited = compile(sample, 'math.py', 'exec', optimize=0)
    independent = compile(sample, 'math.py', 'exec', optimize=0, dont_inherit=True)
    require(inherited.co_flags & __future__.annotations.compiler_flag,
            'Compiler-context negative probe no longer inherits this helper future flag')
    require(not independent.co_flags & __future__.annotations.compiler_flag,
            'Standalone source compilation inherited the helper future flag')
    require(normalized_code(inherited) != normalized_code(independent),
            'Embedded comparison must still reject a future-flag difference')
    checks.append('standalone-compile-rejects-inherited-caller-future-flags')
    explicit = compile(b'from __future__ import annotations\n' + sample, 'math.py',
                       'exec', optimize=0, dont_inherit=True)
    require(explicit.co_flags & __future__.annotations.compiler_flag,
            'Independent compilation lost a future flag explicitly declared by the source')
    checks.append('standalone-compile-retains-source-declared-future-flags')
    tampered = compile(b'value: MissingType = 2\n', 'math.py', 'exec',
                       optimize=0, dont_inherit=True)
    require(normalized_code(independent) != normalized_code(tampered),
            'Embedded comparison accepted modified source constants')
    checks.append('standalone-compile-still-rejects-source-code-tampering')
    if os.name!='nt':
        try:asyncio.run(verify(argparse.Namespace(),{}))
        except AssertionError as error:require('Actual Windows x64 PE' in str(error),'Platform gate changed')
        else:raise AssertionError('Actual-native platform gate was bypassed')
        checks.append('non-Windows-controller-cannot-claim-native-acceptance')
    return dict(status='passed',scope='pure fabricated comparator and lifecycle probes only',
                passed=len(checks),checks=checks,native_frozen_runtime=False,native_upgrade_verified=False,
                patient_inputs_read=False,network=False,server_started=False,pdf_operations=0,print_operations=0)


def probe_legacy_oracles(helpers,adapter_root):
    """Independent formula input checks the authentic old modules, not a new detector."""
    import numpy as np
    stt,ranges,records=load_legacy_oracles(Path(helpers),Path(adapter_root))
    duration=320;raw=np.zeros((duration*200,8),dtype='<i2');beats=[]
    for second in range(1,duration):
        sample=second*200;raw[sample:sample+4]=np.array([900,600,250,80])[:,None]
        raw[sample+18:sample+45]=130 if 120<=second<205 else -13
        raw[sample+55:sample+63]=180
        beats.append(dict(sample_index=sample,group=1,rr_ms=1000))
    mean=ranges.calculate_stt_range(raw,beats,start_sample=0,end_sample=12000,leads=['II'],measurement_ms=60)
    require(mean['leads'][0]['used_count']==59 and mean['leads'][0]['mean_units']==-13,
            'Old range oracle failed independent fixed-offset arithmetic input')
    masks=records.rhythm_exclusions([dict(sample_index=0,details=dict(kind='AF',status='pending',end_sample=11999))])
    masked=ranges.calculate_stt_range(raw,beats,start_sample=0,end_sample=12000,leads=['II'],measurement_ms=60,exclusions=masks)
    require(masked['counts']['used_count']==0 and masked['leads'][0]['mean_units'] is None,
            'Authentic old13 range oracle no longer applies its old pending AF mask')
    with tempfile.TemporaryDirectory(prefix='authentic-old13-formula-') as temp:
        path=Path(temp)/'formula.DATA';path.write_bytes(raw.tobytes())
        before=stt.build_stt_review('',path,beats,duration)
        after=stt.build_stt_review('',path,beats,duration,excluded_intervals=masks)
        require(before['analysis']['exclusions']['intervals']==[]
                and after['analysis']['exclusions']['intervals']!=[],
                'Authentic old screening oracle lost the old mask contract')
        require(before['analysis']['trends']!=after['analysis']['trends'],
                'Old13 screening fixture failed to expose mask-sensitive minutes')
    return dict(status='passed',scope='authentic SHA-bound old13 modules on independent formula arrays only',
        checks=['old13-three-module-loader-hashes-and-relative-algorithm-links-exact',
                'old13-range-mean-equals-independent-minus13-formula',
                'old13-pending-AF-mask-still-removes-range-observations',
                'old13-screening-minute-evidence-still-reflects-real-old-mask-method'],
        native_frozen_runtime=False,native_upgrade_verified=False,patient_inputs_read=False,server_started=False)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base-software-archive', type=Path, required=True)
    parser.add_argument('--software-archive', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--adapter-root', type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('--helpers-root', type=Path, default=Path(__file__).resolve().parent)
    args = parser.parse_args(); require(not args.output.exists(), 'Preserve previous actual native attempts')
    args.output.parent.mkdir(parents=True, exist_ok=True)
    result = dict(status='running', scope='Actual Windows x64 P01 same-workspace reviewed-report upgrade from 1.0.13 APP28 to fresh 1.0.14 APP29',
                  patient_inputs_read=False, patient_raw_copies=0, pdf_operations=0, print_operations=0,
                  clinical_validation=False, native_frozen_runtime=False, native_upgrade_verified=False, checks=[])
    try:
        asyncio.run(verify(args, result))
    except Exception as error:
        result.update(status='failed', native_frozen_runtime=False, native_upgrade_verified=False)
        result.setdefault('error', safe_error(error)); raise
    finally:
        args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
        print('WINDOWS_STT_HOSPITAL_UPGRADE_JSON=' + json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    main()
