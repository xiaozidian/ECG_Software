"""Synthetic-only current-edit reads; no patient files or server writes.

Run from the repository: .venv/bin/python scripts/benchmark_editor_snapshot.py
The legacy projection is the same read used by the application before this change.
"""
import argparse
import gc
import json
from pathlib import Path
import statistics
import sys
import tempfile
import time
import tracemalloc

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ecg_core.beat_editor import BeatEditorStore, blank
from ecg_core.storage import Storage


def legacy_snapshot(store, case_id):
    value = store.read(case_id)
    return dict(revision=value['revision'], document=value['document'],
                can_undo=bool(value['undo']), can_redo=bool(value['redo']))


def measure(read, repeats):
    read()  # Warm filesystem and SQLite; not a cold-start benchmark.
    times = []
    for _ in range(repeats):
        gc.collect()
        start = time.perf_counter()
        result = read()
        times.append((time.perf_counter() - start) * 1000)
        del result
    gc.collect()
    tracemalloc.start()
    result = read()
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    return dict(median_ms=round(statistics.median(times), 3),
                python_peak_mib=round(peak / 1024**2, 3))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--edits', type=int, default=10000)
    parser.add_argument('--repeats', type=int, default=7)
    args = parser.parse_args()
    if not 1 <= args.edits <= 100000 or not 1 <= args.repeats <= 30:
        parser.error('edits: 1–100000; repeats: 1–30')
    output = []
    with tempfile.TemporaryDirectory(prefix='ecg-edit-snapshot-') as directory:
        store = BeatEditorStore(Storage(Path(directory) / 'synthetic.db'))
        document = blank()
        document['changes'] = {f's:{i * 200}': dict(sample_index=i * 200,
            class_code='V' if i % 2 else 'N', deleted=False) for i in range(args.edits)}
        for history_count in (0, 1, 6):
            history = [document] * history_count
            encoded = json.dumps(history)
            with store.storage.connect() as db:
                db.execute('INSERT OR REPLACE INTO beat_edit_documents VALUES(?,?,?,?,?)',
                           ('synthetic', 7, json.dumps(document), encoded, '[]'))
            old = lambda: legacy_snapshot(store, 'synthetic')
            row = dict(edits=args.edits, history_documents=history_count,
                       history_bytes=len(encoded.encode()), legacy=measure(old, args.repeats))
            if hasattr(store, 'snapshot'):
                new = lambda: store.snapshot('synthetic')
                assert new() == old(), 'Current document, revision or history availability changed'
                row['snapshot'] = measure(new, args.repeats)
                row['equal'] = True
            output.append(row)
    print(json.dumps(output, indent=2))


if __name__ == '__main__':
    main()
