"""Isolated synthetic HTTP check; never opens the user's data/workspace database."""
import json
import os
from hashlib import sha256
from pathlib import Path
import sys
import tempfile
import threading
from urllib.error import HTTPError
from urllib.request import Request, urlopen

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import create_app
from ecg_core.ebi import HEADER_SIZE, RECORD
from ecg_core.source_identity import file_signature
from waitress import create_server


def validate():
    with tempfile.TemporaryDirectory(prefix='ecg-metadata-http-') as directory:
        root = Path(directory)
        cid = '9999999999999999'
        case = root / 'synthetic' / cid
        data = case / 'data' / f'{cid}.DATA'
        ebi = case / 'DGS' / f'{cid}.EBI'
        lps = case / 'report_image' / f'{cid}_1.LPS'
        for path in (data, ebi, lps):
            path.parent.mkdir(parents=True, exist_ok=True)
        data.write_bytes(bytes(90 * 200 * 8 * 2))
        ebi.write_bytes(bytes(HEADER_SIZE) + b''.join(RECORD.pack(i * 200, 1, 1, 0, 0, 0, 1000) for i in range(1, 90)))
        lps.write_text('<root><PShape>记录时间:2026-01-01 08:00:00</PShape><PShape>总心搏数:89</PShape></root>')
        hashes = [sha256(p.read_bytes()).hexdigest() for p in (data, ebi, lps)]
        app = create_app(data_root=root / 'synthetic', db_path=root / 'isolated.db', testing=True)
        runtime, store = app.extensions['analysis_runtime'], app.extensions['storage']
        source = root / 'synthetic-runtime-artifact.py'
        source.write_text('value = 1\n')
        runtime.files[source] = file_signature(source)
        runtime.file_names[source] = 'synthetic-http-artifact'
        runtime.file_hashes[source] = sha256(source.read_bytes()).hexdigest()
        server = create_server(app, map={}, host='127.0.0.1', port=0, threads=4)
        stopping = threading.Event()
        failures = []
        def run():
            try:
                while not stopping.is_set():
                    server.asyncore.loop(timeout=.1, count=1, map=server._map,
                                         use_poll=server.adj.asyncore_use_poll)
            except Exception as error:
                failures.append(type(error).__name__)
        worker = threading.Thread(target=run, daemon=True)
        worker.start()
        base = f'http://127.0.0.1:{server.effective_port}/api/cases/{cid}'
        def request(route, payload=None):
            req = Request(base + route, data=None if payload is None else json.dumps(payload).encode(),
                          method='GET' if payload is None else 'PUT', headers={'Content-Type': 'application/json'})
            try:
                with urlopen(req, timeout=10) as response:
                    return response.status, json.load(response)
            except HTTPError as error:
                return error.code, json.load(error)
        try:
            assert request('/report')[0] == 200
            # Synthetic fixture approval only, not a doctor acceptance exercise.
            for step in ('edit', 'stt'):
                store.complete_review(cid, {'step': step, 'confirmed': True,
                    'revision': store.get_review(cid)['revision']}, 'synthetic-test')
            saved = store.save_report(cid, 'Synthetic regression fixture', 'draft', 'synthetic-test')
            saved = store.save_report(cid, saved['conclusion'], 'reviewed', 'synthetic-test',
                                      saved['composition'], expected_version=saved['version'])
            audit = store.list_audit()
            routes = ['/report', '/waveform?start=1&duration=7&analysis=edited', '/beat-editor', '/report-events']
            before = [request(route) for route in routes]
            baseline = file_signature(source)
            source.chmod(source.stat().st_mode ^ 0o100)
            assert file_signature(source)[:4] == baseline[:4]
            assert file_signature(source)[4] != baseline[4]
            after = [request(route) for route in routes]
            assert after == before and all(code == 200 for code, _ in after)
            assert store.get_report(cid, '') == saved and store.list_audit() == audit
            source.write_text('value = 2\n')
            os.utime(source, ns=(source.stat().st_atime_ns, baseline[3]))
            blocked = [request('/report'), request('/report.pdf'),
                       request('/report', {'conclusion': 'must not save', 'expected_version': saved['version']})]
            assert all(code == 409 for code, _ in blocked)
            source.write_text('value = 1\n')
            os.utime(source, ns=(source.stat().st_atime_ns, baseline[3]))
            reverted = request('/report')
            assert reverted[0] == 409
            assert store.get_report(cid, '') == saved and store.list_audit() == audit
            assert hashes == [sha256(p.read_bytes()).hexdigest() for p in (data, ebi, lps)]
            return {'synthetic_only': True, 'transport': 'local Waitress HTTP',
                    'metadata_only_statuses': [code for code, _ in after], 'responses_unchanged': True,
                    'content_change_statuses': [code for code, _ in blocked],
                    'reverted_content_status': reverted[0], 'saved_report_and_audit_unchanged': True,
                    'source_bytes_unchanged': True}
        finally:
            # Stop polling before closing sockets; closing from another thread
            # while select() is active can otherwise cause a spurious EBADF.
            stopping.set()
            worker.join(timeout=5)
            assert not worker.is_alive(), 'Synthetic HTTP loop did not stop'
            server.task_dispatcher.shutdown()
            server.close()
            for channel in list(server._map.values()):
                channel.close()
            assert not failures, failures


if __name__ == '__main__':
    print(json.dumps(validate(), ensure_ascii=False, indent=2))
