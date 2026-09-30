"""Explain actual production windows without changing diagnosis or classifier."""
import json
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]


def node(code):
    return json.loads(subprocess.check_output(['node', '-e', "const assert=require('node:assert/strict'),C=require('./static/js/af-coverage.js'),E=require('./static/js/overview-engine.js');" + code], cwd=ROOT, text=True))


def test_snapshot_preserves_exact_values_and_nulls_without_mutation():
    result = node("""
const rows=Array.from({length:120},(_,i)=>({sample_index:i*160,rr_ms:i?800:0,class_code:'N'}));
const r=E.screenAFResult(rows,95),before=JSON.stringify(r),s=C.windowSnapshot(r);
assert.equal(JSON.stringify(r),before);assert.equal(s[0].cv,r.windows[0].cv);
assert.equal(s[3].cv,null);assert.equal(s[3].normalized_rmssd,null);
r.windows[0].cv=9;assert.equal(s[0].cv,0);assert.ok(Object.isFrozen(s[0]));
console.log(JSON.stringify(s.map(w=>w.state)));
""")
    assert result == ['negative', 'negative', 'negative', 'unassessed']


def test_actual_candidate_windows_and_absolute_filtered_indexes():
    result = node("""
let sample=0,seed=17;const rows=[];
while(sample<25000){seed=(seed*1664525+1013904223)>>>0;const step=100+seed%130;sample+=step;rows.push({sample_index:sample,rr_ms:step*5,class_code:sample>=12000&&sample<18000?'X':'N'});}
const r=E.screenAFResult(rows,125),s=C.windowSnapshot(r),p=C.windowPage(s,'candidate');
assert.deepEqual(p.items.map(w=>w.index),r.windows.flatMap((w,i)=>w.candidate?[i]:[]));
assert.equal(p.items.every(w=>w.candidate),true);
console.log(JSON.stringify({count:p.total,unassessed:C.windowPage(s,'unassessed').items.map(w=>w.index)}));
""")
    assert result['count'] > 0
    assert result['unassessed'] == [2, 4]


def test_large_pages_empty_filter_and_record_tail():
    result = node("""
const s=C.windowSnapshot(E.screenAFResult([],86405)),last=C.windowPage(s,'all',9999),none=C.windowPage(s,'candidate');
console.log(JSON.stringify({first:C.windowPage(s).items.length,last,none}));
""")
    assert result['first'] == 20
    assert result['last']['pages'] == 145
    assert result['last']['items'][0]['start_s'] == 86400
    assert result['last']['items'][0]['end_s'] == 86405
    assert result['none']['total'] == 0 and result['none']['pages'] == 1


@pytest.mark.parametrize('mutation', [
    'total_intervals=-1', 'valid_intervals=1.5', 'pair_count=NaN',
    'triple_count=-1', 'valid_intervals=999', 'coverage_s=Infinity',
    'cv=NaN', 'normalized_rmssd=-1', 'turning_ratio=1.1', 'cv=undefined',
])
def test_invalid_measurement_not_rendered_as_zero(mutation):
    assert node("const r=E.screenAFResult([],30);r.windows[0]." + mutation + ";try{C.windowSnapshot(r);console.log(false)}catch(e){console.log(true)}")


@pytest.mark.parametrize('args', ["'normal'", "'all',-1", "'all',1.5", "'all',NaN"])
def test_invalid_filter_page(args):
    assert node("try{C.windowPage([]," + args + ");console.log(false)}catch(e){console.log(true)}")


@pytest.mark.parametrize('scenario', [
    'window-readonly', 'window-empty-filter', 'window-navigation', 'window-stale',
    'window-new-check', 'window-race', 'window-close', 'window-invalid',
    'window-filter-race', 'window-gap-race', 'window-reset', 'window-pages', 'window-other-location', 'window-real-seek',
])
def test_actual_ui_evidence(scenario):
    subprocess.run(['node', str(ROOT/'tests/browser_af_coverage.cjs'), scenario], cwd=ROOT, check=True)
