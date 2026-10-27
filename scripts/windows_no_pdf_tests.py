"""Scoped release-test policy: no PDF opening, rendering, printing or export."""
import inspect
import json
import os
from pathlib import Path


def pytest_configure(config):
    import app
    def forbidden(*args, **kwargs):
        raise AssertionError('PDF generation is forbidden in this packaging verification')
    app.build_report_pdf = forbidden


def pytest_collection_modifyitems(config, items):
    kept, omitted = [], []
    for item in items:
        source = inspect.getsource(item.function).lower()
        if any(word in source for word in ('pdf', 'print_', 'print(', 'window.print')):
            omitted.append(item)
        else:
            kept.append(item)
    items[:] = kept
    config.hook.pytest_deselected(items=omitted)
    target = os.environ.get('ECG_WINDOWS_TEST_SCOPE_RECEIPT')
    if target:
        path = Path(target);path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({'scope':'related application, packaging and Windows protection tests',
            'pdf_operations_permitted':False,'full_repository_suite_run':False,
            'selected':[item.nodeid for item in kept],
            'not_run_for_pdf_instruction':[item.nodeid for item in omitted]},indent=2)+'\n')
