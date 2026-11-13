"""Native-adapter schema lifecycle; all databases and registry rows are mathematical."""
from contextlib import closing
from hashlib import sha256
import json
from pathlib import Path
import sqlite3
from types import SimpleNamespace

import pytest
import win_doctor_eval as doctor
from ecg_core.storage import Storage,IMPLEMENTATION_COMPATIBILITY_DDL

OLD_APP='0.12.32-stt-report-buttons.20261110'
NEW_APP='0.12.33-stt-candidate-quality.20261113'


def rows(path):
    with closing(sqlite3.connect(path)) as db:
        names=[r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
        return {name:db.execute('SELECT * FROM "'+name+'" ORDER BY rowid').fetchall() for name in names}


@pytest.fixture
def late21(tmp_path,monkeypatch):
    folder=tmp_path.resolve()/'math-workspace';folder.mkdir()
    path=folder/'data/cardioinsight.db';storage=Storage(path)
    storage.save_report('mathematical-case','Original mathematical saved text','draft','mathematical-actor')
    with closing(storage.connect()) as db:
        with db:db.execute('DROP TABLE analysis_implementation_compatibility')
    declared=doctor.database_schema(path)
    record=dict(workspace_format=1,software_version=OLD_APP,packaging_version='1.0.21',
        application_initialized=True,sqlite_schema=declared,mathematical_fixture_only=True)
    (folder/'WORKSPACE.json').write_text(json.dumps(record,ensure_ascii=False,indent=2)+'\n')
    original=(folder/'WORKSPACE.json').read_bytes()
    with closing(storage.connect()) as db:
        with db:
            db.execute(IMPLEMENTATION_COMPATIBILITY_DDL)
            db.execute('INSERT INTO analysis_implementation_compatibility VALUES(?,?,?,?,?)',
                ('mathematical-case','e'*64,'b'*64,'{"mathematical_registry_fixture":true,"not_an_authorization":true}','original-registry-time'))
    monkeypatch.setattr(doctor,'_software_version',lambda:NEW_APP)
    monkeypatch.setattr(doctor,'_packaging_version',lambda:'1.0.22')
    return SimpleNamespace(folder=folder,path=path,declared=declared,original=original)


def test_eager_table_exists_before_any_case_read_and_same_version_reopens(tmp_path,monkeypatch):
    folder=tmp_path.resolve()/'fresh';folder.mkdir();path=folder/'data/cardioinsight.db'
    storage=Storage(path);schema=doctor.database_schema(path)
    assert 'analysis_implementation_compatibility' in rows(path)
    assert rows(path)['analysis_implementation_compatibility']==[]
    monkeypatch.setattr(doctor,'_software_version',lambda:NEW_APP)
    monkeypatch.setattr(doctor,'_packaging_version',lambda:'1.0.22')
    record=dict(workspace_format=1,software_version=NEW_APP,packaging_version='1.0.22',application_initialized=True,sqlite_schema=schema)
    (folder/'WORKSPACE.json').write_text(json.dumps(record))
    storage.save_report('mathematical-case','Saved after launch','draft','mathematical-actor')
    assert doctor.database_schema(path)==schema
    Storage(path)
    assert doctor.prepare_upgrade(folder) is None
    assert not (folder/'upgrade-snapshots').exists()


def test_later_certificate_registration_changes_rows_but_never_schema(tmp_path):
    from ecg_core.analysis_provenance import digest
    from ecg_core.beat_editor import BeatEditorStore
    from ecg_core.overview import RhythmReviewStore
    path=tmp_path.resolve()/'data/cardioinsight.db';storage=Storage(path)
    BeatEditorStore(storage);RhythmReviewStore(storage)
    basis={'digest':'mathematical-reference-only'}
    with closing(storage.connect()) as db:
        with db:db.execute('INSERT INTO case_analysis_basis VALUES(?,?,?)',('mathematical-case',json.dumps(basis),'old-time'))
    before=doctor.database_schema(path)
    certificate=dict(reference_basis=basis,review_revision=0,continuity_kind='stt_screening_refinement',
        schema='stt-screening-refinement-continuity-v1',authored_annotations_digest=digest([]),
        beat_revision=0,execution_engine_id='e'*64,execution_basis='b'*64,retained_stt_records=[])
    storage.record_compatible_implementation('mathematical-case',certificate,'mathematical-unit',lambda:None)
    assert doctor.database_schema(path)==before
    assert len(rows(path)['analysis_implementation_compatibility'])==1


def test_exact_released21_late_table_is_backed_up_then_reconciled_without_row_changes(late21):
    f=late21;before=rows(f.path);schema=doctor.database_schema(f.path)
    assert schema!=f.declared
    pending=doctor.prepare_upgrade(f.folder)
    assert pending['known_legacy_ddl_reconciliation']['kind']=='known-legacy-DDL-reconciliation'
    assert pending['known_legacy_ddl_reconciliation']['declared_schema']==f.declared
    assert rows(f.path)==before
    snapshots=f.folder/'upgrade-snapshots'
    backup=snapshots/pending['snapshot'];metadata=snapshots/pending['workspace_snapshot']
    assert pending['snapshot_sha256']==sha256(backup.read_bytes()).hexdigest()
    assert rows(backup)==before and doctor.database_schema(backup)==schema
    assert metadata.read_bytes()==f.original
    assert pending['workspace_snapshot_sha256']==sha256(f.original).hexdigest()
    Storage(f.path)
    doctor.complete_upgrade(f.folder,pending)
    record=doctor._read_json(f.folder/'WORKSPACE.json',required=True)
    assert record['sqlite_schema']==schema
    assert record['last_upgrade']['known_legacy_ddl_reconciliation']['kind']=='known-legacy-DDL-reconciliation'
    assert not record.get('upgrade_pending')
    assert rows(f.path)==before
    assert doctor.prepare_upgrade(f.folder) is None


def test_reconciliation_snapshot_includes_committed_live_WAL(late21):
    f=late21
    with closing(sqlite3.connect(f.path)) as writer:
        writer.execute('PRAGMA journal_mode=WAL')
        writer.execute("UPDATE report_drafts SET conclusion='Mathematical committed WAL text'")
        writer.commit()
        assert Path(str(f.path)+'-wal').stat().st_size>0
        before=rows(f.path)
        pending=doctor.prepare_upgrade(f.folder)
        assert rows(f.folder/'upgrade-snapshots'/pending['snapshot'])==before
        assert rows(f.path)==before


def test_optional_legacy_source_commit_accepts_actual21_compile_not_aggregate_controller(late21):
    f=late21;record=json.loads(f.original)
    record['source_commit']='0c7b634ef77297d388d1e9075b01c58809e0c0aa'
    metadata=(json.dumps(record,ensure_ascii=False,indent=2)+'\n').encode()
    (f.folder/'WORKSPACE.json').write_bytes(metadata)
    pending=doctor.prepare_upgrade(f.folder)
    assert pending['known_legacy_ddl_reconciliation']['released_packaging_version']=='1.0.21'
    assert (f.folder/'upgrade-snapshots'/pending['workspace_snapshot']).read_bytes()==metadata


def test_optional_source_commit_rejects_accepted_aggregate_head_as_false_compile_identity(late21):
    f=late21;record=json.loads(f.original)
    record['source_commit']='93f667edf03db99d281cbc8e1afbaec6a2f463f5'
    (f.folder/'WORKSPACE.json').write_text(json.dumps(record))
    with pytest.raises(doctor.DoctorEvalError) as error:doctor.prepare_upgrade(f.folder)
    assert error.value.code=='workspace_schema_changed'
    assert not (f.folder/'upgrade-snapshots').exists()


@pytest.mark.parametrize('fault',['table','index','trigger','user-version','canonical-column','canonical-spacing','old-app','old-package','declared-version','declared-hash','unknown-commit'])
def test_any_other_schema_or_release_difference_is_refused_without_backup_or_metadata_change(late21,fault):
    f=late21
    if fault in ('old-app','old-package','declared-version','declared-hash','unknown-commit'):
        record=json.loads(f.original)
        if fault=='old-app':record['software_version']='0.12.31-other'
        if fault=='old-package':record['packaging_version']='1.0.20'
        if fault=='declared-version':record['sqlite_schema']['user_version']=1
        if fault=='declared-hash':record['sqlite_schema']['fingerprint']='a'*64
        if fault=='unknown-commit':record['source_commit']='a'*40
        (f.folder/'WORKSPACE.json').write_text(json.dumps(record))
    else:
        with closing(sqlite3.connect(f.path)) as db:
            with db:
                if fault=='table':db.execute('CREATE TABLE unexpected(value TEXT)')
                if fault=='index':db.execute('CREATE INDEX unexpected ON analysis_implementation_compatibility(created_at)')
                if fault=='trigger':db.execute('CREATE TRIGGER unexpected AFTER INSERT ON analysis_implementation_compatibility BEGIN SELECT 1; END')
                if fault=='user-version':db.execute('PRAGMA user_version=1')
                if fault in ('canonical-column','canonical-spacing'):
                    db.execute('DROP TABLE analysis_implementation_compatibility')
                    ddl=IMPLEMENTATION_COMPATIBILITY_DDL.replace('certificate TEXT','certificate BLOB') if fault=='canonical-column' else IMPLEMENTATION_COMPATIBILITY_DDL.replace('case_id TEXT','case_id  TEXT')
                    db.execute(ddl)
    metadata=(f.folder/'WORKSPACE.json').read_bytes();before=rows(f.path)
    with pytest.raises(doctor.DoctorEvalError) as result:doctor.prepare_upgrade(f.folder)
    assert result.value.code=='workspace_schema_changed'
    assert (f.folder/'WORKSPACE.json').read_bytes()==metadata
    assert rows(f.path)==before and not (f.folder/'upgrade-snapshots').exists()


def test_reconciliation_cannot_mark_complete_if_other_schema_changes_after_backup(late21):
    f=late21;pending=doctor.prepare_upgrade(f.folder)
    with closing(sqlite3.connect(f.path)) as db:
        with db:db.execute('CREATE TABLE unexpected(value TEXT)')
    metadata=(f.folder/'WORKSPACE.json').read_bytes()
    with pytest.raises(doctor.DoctorEvalError) as error:doctor.complete_upgrade(f.folder,pending)
    assert error.value.code=='workspace_reconciliation_changed'
    assert (f.folder/'WORKSPACE.json').read_bytes()==metadata


def test_released21_canonical_definition_is_pinned_even_if_future_storage_constant_changes(late21,monkeypatch):
    import ecg_core.storage as storage_module
    f=late21;changed=IMPLEMENTATION_COMPATIBILITY_DDL.replace('case_id TEXT','case_id  TEXT')
    with closing(sqlite3.connect(f.path)) as db:
        with db:
            db.execute('DROP TABLE analysis_implementation_compatibility');db.execute(changed)
    monkeypatch.setattr(storage_module,'IMPLEMENTATION_COMPATIBILITY_DDL',changed)
    assert doctor.known_legacy_ddl_reconciliation(f.path,f.declared,OLD_APP,'1.0.21') is None


@pytest.mark.parametrize('action',['_serve-manager','_serve-workspace'])
def test_native_child_start_failure_returns_2_without_modal_dialog(monkeypatch,action):
    import ctypes
    calls=[]
    monkeypatch.setattr(doctor,'os',SimpleNamespace(name='nt'))
    monkeypatch.setattr(ctypes,'windll',SimpleNamespace(user32=SimpleNamespace(MessageBoxW=lambda *args:calls.append(args))),raising=False)
    def fail(*args):raise doctor.DoctorEvalError('workspace_schema_changed','Mathematical startup refusal')
    monkeypatch.setattr(doctor,'serve_manager',fail)
    monkeypatch.setattr(doctor,'serve_workspace',fail)
    assert doctor.main([action,'--runtime-token','a'*64,'--workspace','b'*32])==2
    assert calls==[]


def test_interactive_user_entry_retains_visible_error_dialog(monkeypatch):
    import ctypes
    calls=[]
    monkeypatch.setattr(doctor,'os',SimpleNamespace(name='nt'))
    monkeypatch.setattr(ctypes,'windll',SimpleNamespace(user32=SimpleNamespace(MessageBoxW=lambda *args:calls.append(args))),raising=False)
    def fail(**kwargs):raise doctor.DoctorEvalError('mathematical-error','Mathematical visible error')
    monkeypatch.setattr(doctor,'ensure_manager',fail)
    assert doctor.main(['launch'])==2
    assert len(calls)==1


def test_explicit_native_math_fixture_and_backup_verifier_are_honestly_labelled(late21):
    from scripts.verify_windows_screening_quality import inject_known_legacy_ddl_fixture,verify_known_legacy_reconciliation
    from scripts.verify_windows_stt_independent_upgrade import database_state
    f=late21
    with closing(sqlite3.connect(f.path)) as db:
        with db:db.execute('DROP TABLE analysis_implementation_compatibility')
    record=json.loads(f.original);record.update(source_kind='mathematical_deidentified_fixture',selected_dataset='P01')
    (f.folder/'WORKSPACE.json').write_text(json.dumps(record))
    fixture=inject_known_legacy_ddl_fixture(f.folder,'mathematical-case')
    assert fixture['status']=='math-injected-known-lazy-DDL-not-actual20-runtime'
    assert fixture['actual20_runtime_executed'] is False
    original=database_state(f.path)
    pending=doctor.prepare_upgrade(f.folder);Storage(f.path);doctor.complete_upgrade(f.folder,pending)
    proof=verify_known_legacy_reconciliation(f.folder,original,fixture)
    assert proof['status']=='passed' and proof['full_original_database_backup_exact']
    assert proof['actual20_runtime_executed'] is False


def test_injected_DDL_fixture_refuses_nonmathematical_source_before_writes(late21):
    from scripts.verify_windows_screening_quality import inject_known_legacy_ddl_fixture
    f=late21;record=json.loads(f.original);record.update(source_kind='deidentified_patient',selected_dataset='P01')
    (f.folder/'WORKSPACE.json').write_text(json.dumps(record));before=rows(f.path)
    with pytest.raises(AssertionError,match='mathematical P01'):
        inject_known_legacy_ddl_fixture(f.folder,'mathematical-case')
    assert rows(f.path)==before


@pytest.mark.parametrize('extra',[[],['--base-software-archive','old21.zip']])
def test_legacy_fixture_CLI_requires_actual21_and_nonempty_scope_flags(tmp_path,monkeypatch,extra):
    import sys
    from scripts import verify_windows_screening_quality as controller
    output=tmp_path/'receipt.json'
    monkeypatch.setattr(sys,'argv',['verify_windows_screening_quality.py','--software-archive','current22.zip',
        '--known-legacy-ddl-fixture','--output',str(output),*extra])
    with pytest.raises(AssertionError,match='requires original21 and nonempty'):
        controller.main()
    assert not output.exists()
