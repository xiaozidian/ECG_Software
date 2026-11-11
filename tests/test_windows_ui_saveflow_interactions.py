"""Fail-closed proof checks for the new Windows19 visible-control harness.

Disposable protocol facts only. These tests do not claim native execution.
"""
from copy import deepcopy
from pathlib import Path
import ast
import pytest
from scripts.verify_ui_saveflow_ui import assert_observation, assert_review_preserved, business_write

ROOT = Path(__file__).resolve().parents[1]


def observed():
    return dict(samples=6, empty_frames=0, max_forms=1, surface_connected=True,
                original_form_connected=True, trend_node_connected=True)


def test_review_measurement_accepts_nonempty_surfaces_and_one_actual_AF_write():
    assert_observation(observed(), [dict(method='PUT', path='/api/cases/math/annotations/1')], 'stt', keep_form=True)
    assert_observation(observed(), [dict(method='PUT', path='/api/cases/math/rhythm-review')], 'af', keep_form=True)


@pytest.mark.parametrize('fault', ['zero-observations', 'blank', 'duplicate-form', 'detached-surface',
                                  'detached-form', 'replaced-trend', 'full-QRS-read', 'ST-reanalysis',
                                  'full-HR-trend', 'missing-AF-write', 'duplicate-AF-write'])
def test_missing_or_changed_proof_never_passes_as_incremental(fault):
    value=observed(); requests=[dict(method='PUT',path='/api/cases/math/rhythm-review')];kind='af'
    if fault=='zero-observations':value['samples']=1
    if fault=='blank':value['empty_frames']=1
    if fault=='duplicate-form':value['max_forms']=2
    if fault=='detached-surface':value['surface_connected']=False
    if fault=='detached-form':value['original_form_connected']=False
    if fault=='replaced-trend':value['trend_node_connected']=False;kind='stt';requests=[]
    if fault=='full-QRS-read':requests.append(dict(method='GET',path='/api/cases/math/overview'))
    if fault=='ST-reanalysis':requests.append(dict(method='GET',path='/api/cases/math/stt-review'))
    if fault=='full-HR-trend':requests.append(dict(method='GET',path='/api/cases/math/trend'))
    if fault=='missing-AF-write':requests=[]
    if fault=='duplicate-AF-write':requests*=2
    with pytest.raises(AssertionError):assert_observation(value,requests,kind,keep_form=True)


@pytest.mark.parametrize('path', ['/waveform-density','/waveform-strips','/rr-review/locate','/event-waveforms'])
def test_real_readonly_POSTs_are_not_classified_as_diagnostic_writes(path):
    assert not business_write('POST','/api/cases/math'+path)


@pytest.mark.parametrize('method,path', [('PUT','/annotations/1'),('POST','/annotations'),
                                        ('PUT','/rhythm-review'),('DELETE','/annotations/1'),('PUT','/report')])
def test_diagnostic_and_report_mutations_are_counted(method,path):
    assert business_write(method,'/api/cases/math'+path)


def review():
    return dict(id=1,details=dict(physician_note='mathematical original'),stt_review_receipt=dict(
        record_version=2,range={'start_sample':100,'end_sample':20000},findings=[{'result_code':'t_low_flat'}],
        result_codes=['t_low_flat'],leads=['V3']))


def test_duplicate_or_changed_medical_content_cannot_pass_one_save_contract():
    before=review();after=deepcopy(before);after['stt_review_receipt']['record_version']+=1
    assert_review_preserved(before,after)
    for key in ('range','findings','result_codes','leads'):
        bad=deepcopy(after);bad['stt_review_receipt'][key]=[]
        with pytest.raises(AssertionError):assert_review_preserved(before,bad)
    after['stt_review_receipt']['record_version']+=1
    with pytest.raises(AssertionError):assert_review_preserved(before,after)


def test_native_helper_uses_visible_actions_and_GET_only_independent_inspection():
    text=(ROOT/'scripts/verify_ui_saveflow_ui.py').read_text();tree=ast.parse(text)
    calls=[n for n in ast.walk(tree) if isinstance(n,ast.Call)]
    request_calls=[n for n in calls if isinstance(n.func,ast.Attribute) and isinstance(n.func.value,ast.Attribute)
                   and n.func.value.attr=='request']
    assert request_calls and all(n.func.attr=='get' for n in request_calls)
    for marker in ('async def verify_legacy(', '.dblclick(delay=40)', "await note.fill(late)",
                   "await page.locator('#saveSttAnnotation').click()", "'data-stt-edit-record'",
                   "'AF-visible-delete-restores-original-episodes-without-broad-reload'",
                   "mode in ('right','button','keyboard')", "len(items)==8", "menus[0]==menus[1]==menus[2]",
                   "await page.keyboard.press('n')", "await page.keyboard.press('v')", "'#beatRelabelMenu'",
                   "assert await read('annotations')==initial"):
        assert marker.replace("'data-stt-edit-record'",'data-stt-edit-record') in text
    assert '.request.post(' not in text and '.request.put(' not in text
    assert 'state.sttReview=' not in text and 'state.sttEditingRecord=' not in text


def test_two_real_candidate_targets_and_no_confirm_bypass_are_native_prerequisites():
    text=(ROOT/'scripts/verify_ui_saveflow_ui.py').read_text()
    continuous=text[text.index('candidates=await page.evaluate'):text.index("result['continuous_STT_candidates']")]
    assert "('st_depression','st_elevation')" in continuous
    assert 'sttReviewHasUnsavedNote()' in continuous
    assert "state.sttSelectedCandidate?.item.id===id" in continuous
    assert "proof['result_codes']==[candidate['kind']]" in continuous
    assert "proof['range']['start_s']-candidate['start_s']" in continuous
    assert "proof['range']['end_s']-candidate['end_s']" in continuous
    assert "await dialog.dismiss()" in text and 'dialog.accept(' not in text
    assert 'assert not unexpected_dialogs' in continuous
