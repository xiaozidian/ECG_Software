"""Synthetic-only AF report state, rendered copy and edit/export lifecycle."""
from copy import deepcopy
from hashlib import sha256
import json
import subprocess

import pytest
from reportlab.pdfgen.canvas import Canvas

from ecg_core.report_layout import strip_review_note
from ecg_core.report_paper_pdf import build_paper_pdf
from ecg_core.report_pdf import _register_font, FONT_NAME
from test_analysis_provenance import synthetic_case, synthetic_app
from test_paper_geometry import sample_entry


def browser(entry, fixed=False):
    code = """
require('./static/js/report-engine.js');require('./static/js/report-paper.js');
require('./static/js/report-workspace.js');global.formatElapsed=String;
const x=JSON.parse(require('fs').readFileSync(0,'utf8'));
const model={case:{case_id:'synthetic',metadata:{}},report:{status:'draft',composition:{paper:{time_scale:x.fixed?'fixed':'fit',speed:'25 mm/s'}}}};
console.log(JSON.stringify({note:ECGReportEngine.reviewNote(x.entry),
  workspace:ECGReportWorkspace.waveContext(x.entry),
  paper:ECGReportPaper.stripPages(model,[x.entry])}));
"""
    return json.loads(subprocess.check_output(['node', '-e', code],
        input=json.dumps(dict(entry=entry, fixed=fixed)), text=True))


@pytest.mark.parametrize('kind', ['AF', 'AFL'])
@pytest.mark.parametrize('status', ['pending', 'confirmed', 'excluded', None, 'unexpected'])
def test_status_copy_uses_episode_not_global_diagnosis(kind, status):
    entry = dict(sample_entry(), category='AF', subtype=kind, rhythm_status=status,
                 diagnosis_status='confirmed', caption='可编辑图注不能覆盖片段状态')
    actual = browser(entry)
    note = strip_review_note(entry)
    assert actual['note'] == note
    assert note in actual['workspace'] and note in actual['paper']
    assert ('片段已确认' in note) is (status == 'confirmed')
    assert ('片段待复核' in note) is (status not in ('confirmed', 'excluded'))
    assert ('房扑' in note) is (kind == 'AFL')
    assert '可编辑图注不能覆盖片段状态' in actual['paper']
    del entry['rhythm_status']
    assert '片段待复核' in browser(entry)['note']


def test_other_categories_do_not_acquire_rhythm_claim():
    entry = dict(sample_entry(), category='V', subtype='single', rhythm_status='confirmed')
    actual = browser(entry)
    assert strip_review_note(entry) == actual['note'] == ''
    assert 'data-rhythm-review-note' not in actual['workspace'] + actual['paper']


@pytest.mark.parametrize('count', [1, 3, 6, 12])
@pytest.mark.parametrize('status', ['pending', 'confirmed'])
@pytest.mark.parametrize('fixed', [False, True])
def test_each_paper_segment_keeps_state_and_existing_notes(count, status, fixed, monkeypatch):
    entry = dict(sample_entry(count, 14), category='AF', subtype='AFL', rhythm_status=status)
    entry['strip']['warning'] = '为包含至少 5 搏，已由 7 秒延长至 14 秒'
    paper = dict(time_scale='fixed' if fixed else 'fit', speed='25 mm/s')
    drawn = []
    original = Canvas.drawString
    def capture(self, x, y, text, *args, **kwargs):
        drawn.append((x, y, text));return original(self, x, y, text, *args, **kwargs)
    monkeypatch.setattr(Canvas, 'drawString', capture)
    _register_font()
    pdf = build_paper_pdf(dict(case_id='synthetic', metadata={}),
        dict(status='draft', composition=dict(page_selection_version=1,
             included_pages=['event_strips'], paper=paper), selected_waveforms=[entry]), FONT_NAME)
    assert pdf.getvalue().startswith(b'%PDF')
    note = strip_review_note(entry)
    assert sum(t == note.replace('·',' / ') for _, _, t in drawn) == (2 if fixed else 1)
    assert any('延长至 14 秒' in t for _, _, t in drawn)
    html = browser(entry, fixed)['paper']
    assert html.count(note) == (2 if fixed else 1)
    assert html.count('data-rhythm-review-note') == (2 if fixed else 1)


@pytest.mark.parametrize('kind', ['AF', 'AFL'])
@pytest.mark.parametrize('change', ['pending', 'bounds', 'excluded', 'delete'])
def test_report_selection_lifecycle_rejects_stale_evidence(synthetic_app, synthetic_case, kind, change):
    client = synthetic_app.test_client();_, cid, paths = synthetic_case
    base = '/api/cases/' + cid;store = synthetic_app.extensions['storage']
    raw_hashes = {k:sha256(p.read_bytes()).hexdigest() for k,p in paths.items()}
    episode = dict(id='lifecycle', start_s=10, end_s=30, kind=kind, status='pending')
    def rhythm(operation='save', document=None):
        current = client.get(base+'/rhythm-review').json
        response = client.put(base+'/rhythm-review', json=dict(operation=operation,
            revision=current['revision'], beat_revision=current['beat_revision'],
            analysis_basis=current['analysis_basis'], analysis_revision=current['analysis_revision'],
            confirmed=True, document=document))
        assert response.status_code == 200, response.json
        return response.json
    def ready():
        for step in ('edit', 'stt'):
            store.complete_review(cid, dict(step=step, confirmed=True,
                revision=store.get_review(cid)['revision']), 'synthetic-doctor')
    def events():return client.get(base+'/report-events?category=AF').json
    def report():return client.get(base+'/report').json
    def save(r, status):
        return client.put(base+'/report', json=dict(status=status, expected_version=r['version'],
            expected_review_revision=r['review_revision'], conclusion=r['conclusion'], composition=r['composition']))
    def select_current():
        data=events();e=data['items'][0];r=report()
        r['conclusion']='数学合成测试：不是患者诊断'
        r['composition'].update(page_selection_version=1, included_pages=['event_strips'],
            category_reviews=data['basis_versions'], selected_events=[dict(event_id=e['event_id'],
                basis_version=e['basis_version'], caption='合成片段，不是患者诊断')])
        result=save(r,'draft');assert result.status_code == 200, result.json
        return result.json, e
    rhythm(document=dict(episodes=[episode]));ready()
    draft, pending = select_current()
    denied=save(draft, 'reviewed')
    assert denied.status_code == 400 and '片段诊断确认' in denied.json['error']
    assert client.get(base+'/report.pdf').status_code == 200 # A clearly marked draft is allowed.
    episode['status']='confirmed';rhythm(document=dict(episodes=[episode]));ready()
    assert client.get(base+'/report.pdf').status_code in (400,409) # Old pending selection is stale.
    draft, confirmed = select_current()
    assert confirmed['basis_version'] != pending['basis_version']
    approved=save(draft, 'reviewed');assert approved.status_code == 200, approved.json
    assert client.get(base+'/report.pdf').status_code == 200
    changed=deepcopy(episode)
    if change=='bounds':changed.update(start_s=20,end_s=40)
    elif change in ('pending','excluded'):changed['status']=change
    rhythm(document=dict(episodes=[] if change=='delete' else [changed]))
    invalid=report()
    assert invalid['status']=='draft'
    assert invalid['composition']['selected_events']==approved.json['composition']['selected_events']
    assert save(approved.json, 'reviewed').status_code == 409
    assert client.get(base+'/report.pdf').status_code in (400,409)
    if change in ('delete','excluded'):assert events()['total']==0
    else:
        current=events()['items'][0]
        assert current['basis_version']!=confirmed['basis_version']
        if change=='bounds':assert (current['time_s'],current['end_s'])==(20,40)
        else:assert current['rhythm_status']=='pending'
    rhythm('undo')
    assert events()['items'][0]['rhythm_status']=='confirmed'
    assert report()['status']=='draft' # Undo must not resurrect approval.
    ready();draft, _ = select_current()
    assert save(draft,'reviewed').status_code == 200
    assert client.get(base+'/report.pdf').status_code == 200
    assert {k:sha256(p.read_bytes()).hexdigest() for k,p in paths.items()}==raw_hashes
