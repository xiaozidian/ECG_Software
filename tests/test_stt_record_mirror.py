"""Independent Python/browser parity for stable ST review records, no source IO."""
import copy
import json
from pathlib import Path
import shutil
import subprocess

import pytest

from ecg_core.stt_records import RESULTS, decorate_event, digest

ROOT = Path(__file__).resolve().parents[1]


def browser(payload, script):
    executable = shutil.which('node')
    if not executable:
        pytest.skip('Node is required for browser parity')
    run = subprocess.run([executable, '-e', script], cwd=ROOT,
                         input=json.dumps(payload, ensure_ascii=False), text=True,
                         capture_output=True, timeout=30)
    assert run.returncode == 0, run.stdout + run.stderr


def annotation(code, identifier=1):
    return dict(id=identifier, sample_index=2000, lead='II', label='数学ST-T', note='测量',
                details=dict(kind='ST', end_sample=18000, reviewed=True,
                             result_code=code, status='confirmed',
                             review_leads=['II', 'V5'], physician_note='医生备注',
                             review_scope=dict(case_id='math', analysis_basis='basis',
                                               analysis_revision=4, beat_revision=0),
                             measurement_protocol=dict(measurement_ms=60, extent='whole'),
                             review_extent='whole',
                             stt_event_evidence=dict(scope=dict(analysis_revision=3), tiny=1e-7)))


def test_typed_SHA256_matches_with_tiny_large_unicode_integral_and_zero_values():
    values = ['', {}, 'abc', 'ST/房颤🙂',
              {'b': 20.0, 'a': [1e-7, 1.234e22, -0.0, True, None], '\ue000': 3, '🙂': 4}]
    browser([dict(value=v, expected=digest(v)) for v in values], """
      const fs=require('fs'),assert=require('assert/strict'),crypto=require('crypto');
      const a=require('./static/js/clinical-analysis.js'),rows=JSON.parse(fs.readFileSync(0,'utf8'));
      for(const row of rows){assert.equal(a.sttDigest(row.value),row.expected);
        assert.equal(a.sttDigest(row.value),crypto.createHash('sha256').update(a.sttCanonical(row.value)).digest('hex'));}
    """)


def test_all_seven_review_receipts_and_local_bases_match_python():
    rows = []
    for identifier, code in enumerate(RESULTS, 1):
        item = annotation(code, identifier)
        rows.append(dict(annotation=item, expected=decorate_event({}, item, 'beats')))
    browser(rows, """
      const fs=require('fs'),assert=require('assert/strict'),a=require('./static/js/clinical-analysis.js');
      for(const row of JSON.parse(fs.readFileSync(0,'utf8')))
        assert.deepEqual(a.sttDecorate({},row.annotation,'beats'),row.expected);
    """)


def test_only_own_material_changes_basis_not_unrelated_review_revision():
    original = annotation('no_change')
    variants = [copy.deepcopy(original) for _ in range(4)]
    variants[0]['details']['review_scope']['analysis_revision'] += 1
    variants[0]['details']['stt_event_evidence']['scope']['analysis_revision'] += 1
    variants[1]['details']['result_code'] = 'indeterminate'
    variants[2]['details']['physician_note'] = '修改医生原文'
    variants[3]['details']['end_sample'] += 200
    rows = [original] + variants
    expected = [decorate_event({}, row, 'beats')['basis_version'] for row in rows]
    assert expected[0] == expected[1]
    assert all(value != expected[0] for value in expected[2:])
    browser(dict(rows=rows, expected=expected), """
      const fs=require('fs'),assert=require('assert/strict'),a=require('./static/js/clinical-analysis.js');
      const payload=JSON.parse(fs.readFileSync(0,'utf8'));
      assert.deepEqual(payload.rows.map(row=>a.sttDecorate({},row,'beats').basis_version),payload.expected);
    """)


def test_legacy_mean_protocol_is_preserved_and_unknown_point_is_never_invented():
    rows = []
    for ms in (0, 60, 80, None):
        item = dict(id=ms or 1, sample_index=2000, lead='II', details=dict(kind='ST', status='pending', end_sample=18000))
        if ms is not None:
            item['details']['range_statistics'] = dict(method_profile=dict(
                id='raw-200hz-fixed16s-st-perbeat-mean-v1', measurement_ms=ms, units='source_device_units'))
        expected = decorate_event({}, item, 'beats')
        assert expected['stt_review_receipt']['point_measurement_protocol'] is None
        assert expected['stt_review_state'] == 'unreviewed'
        if ms is None:
            assert expected['stt_review_receipt']['measurement_protocol'] is None
        else:
            assert expected['stt_review_receipt']['measurement_protocol']['measurement_ms'] == ms
        rows.append(dict(annotation=item, expected=expected))
    browser(rows, """
      const fs=require('fs'),assert=require('assert/strict'),a=require('./static/js/clinical-analysis.js');
      for(const row of JSON.parse(fs.readFileSync(0,'utf8')))
        assert.deepEqual(a.sttDecorate({},row.annotation,'beats'),row.expected);
    """)
