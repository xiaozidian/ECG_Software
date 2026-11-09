"""Mathematical AF report grouping; not a replacement for the ten-case review."""
from copy import deepcopy
from hashlib import sha256

import pytest
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfgen.canvas import Canvas
from reportlab.lib.units import mm

from ecg_core.report_layout import group_af_report_strips, LEADS
from ecg_core.report_paper_pdf import build_paper_pdf, clock_ms
from ecg_core.report_pdf import _register_font, FONT_NAME
from test_analysis_provenance import synthetic_app, synthetic_case
from test_paper_geometry import sample_entry


def entry(role, start, *, identity='episode-one', basis='current', kind='AF', count=12):
    item = sample_entry(count)
    item.update(event_id=identity, basis_version=basis, category='AF', subtype=kind,
        rhythm_episode_id=identity, rhythm_status='confirmed', start_sample=2025,
        time_s=10.125, end_s=600.875, strip_id=identity + '-' + role,
        representative_role=role, caption='保留医生图注 ' + role,
        notes='保留医生备注', referenced_in_report=True)
    item['strip'].update(start_s=start, end_s=start + 7, actual_duration_s=7)
    item['waveform'].update(start_s=start)
    return item


def test_grouping_is_parent_scoped_chronological_and_readonly():
    first = [entry('end', 590), entry('start', 10), entry('middle', 300)]
    other = dict(sample_entry(), category='ST', event_id='st-one', basis_version='st-current')
    second = entry('middle', 100, identity='episode-two', kind='AFL')
    entries = [first[0], other, first[1], second, first[2]]
    before = deepcopy(entries)
    grouped = group_af_report_strips(entries)
    assert [e.get('strip_id') for e in grouped] == [
        'episode-one-start', 'episode-one-middle', 'episode-one-end', None, 'episode-two-middle']
    assert entries == before
    assert grouped[3] is other
    assert [e['af_report_group']['strip_index'] for e in grouped[:3]] == [1, 2, 3]
    assert {e['af_report_group']['strip_count'] for e in grouped[:3]} == {3}
    assert {e['af_report_group']['episode_number'] for e in grouped[:3]} == {1}
    assert grouped[-1]['af_report_group']['episode_number'] == 2
    for item in grouped[:3]:
        group = item['af_report_group']
        assert (group['episode_start_s'], group['episode_end_s'], group['episode_duration_s']) == (10.125, 600.875, 590.75)
        assert group['strip_end_s'] - group['strip_start_s'] == 7
        original = next(e for e in entries if e.get('strip_id') == item['strip_id'])
        assert {k: v for k, v in item.items() if k != 'af_report_group'} == original


def test_disabled_child_reactivation_and_old_basis_keep_their_own_groups():
    picks = [entry('start', 10), entry('middle', 300), entry('end', 590)]
    picks[1]['print_enabled'] = False
    old = entry('start', 10, basis='previous')
    grouped = group_af_report_strips(picks + [old])
    active = [e for e in grouped if e.get('print_enabled') is not False]
    assert [e['af_report_group']['strip_count'] for e in active] == [2, 2, 1]
    assert [e['af_report_group']['episode_number'] for e in active] == [1, 1, 2]
    assert grouped[2] is picks[1]  # Disabled picks remain intact, without a count claim.
    picks[1]['print_enabled'] = True
    restored = group_af_report_strips(picks)
    assert [e['strip_id'] for e in restored] == [p['strip_id'] for p in picks]
    assert [e['af_report_group']['strip_count'] for e in restored] == [3, 3, 3]
    assert restored[1]['caption'] == picks[1]['caption']


def test_unguarded_legacy_and_non_af_entries_do_not_acquire_an_episode_claim():
    legacy = entry('start', 10)
    del legacy['basis_version']
    unknown_bounds = entry('end', 590)
    del unknown_bounds['end_s']
    st = dict(sample_entry(), category='ST', print_enabled=False)
    result = group_af_report_strips([legacy, unknown_bounds, st])
    assert result == [legacy, unknown_bounds, st]
    assert all('af_report_group' not in e for e in result)


@pytest.mark.parametrize('fixed', [False, True])
def test_pdf_repeats_episode_on_each_page_and_preserves_every_twelve_lead(fixed, monkeypatch):
    picks = [entry('end', 590), entry('start', 10), entry('middle', 300)]
    before = deepcopy(picks)
    drawn, traces = [], []
    original_text, original_center, original_path = Canvas.drawString, Canvas.drawCentredString, Canvas.drawPath

    def capture_text(self, x, y, text, *args, **kwargs):
        drawn.append((self._pageNumber, x, y, str(text), self._fontsize))
        return original_text(self, x, y, text, *args, **kwargs)

    def capture_path(self, path, *args, **kwargs):
        if kwargs.get('stroke', 1) == 1 and self._lineWidth == .5:
            traces.append((self._pageNumber, path.getCode()))
        return original_path(self, path, *args, **kwargs)

    def capture_center(self, x, y, text, *args, **kwargs):
        drawn.append((self._pageNumber, x, y, str(text), self._fontsize))
        return original_center(self, x, y, text, *args, **kwargs)

    monkeypatch.setattr(Canvas, 'drawString', capture_text)
    monkeypatch.setattr(Canvas, 'drawCentredString', capture_center)
    monkeypatch.setattr(Canvas, 'drawPath', capture_path)
    _register_font()
    report = dict(status='draft', composition=dict(page_selection_version=1,
        included_pages=['event_strips'], paper=dict(time_scale='fixed' if fixed else 'fit', speed='50 mm/s')),
        selected_waveforms=picks)
    pdf = build_paper_pdf(dict(case_id='mathematical-only', metadata={}), report, FONT_NAME)
    assert pdf.getvalue().startswith(b'%PDF') and picks == before
    # A 7-second figure at 50 mm/s occupies two continuous paper segments.
    page_count = 6 if fixed else 3
    headers = [(page, text) for page, _, _, text, _ in drawn if text.startswith('房颤片段 1')]
    assert len(headers) == page_count
    assert len({page for page, _ in headers}) == page_count
    for page, _ in headers:
        texts = [text for p, _, _, text, _ in drawn if p == page]
        assert any('D1 00:00:10.125' in t and 'D1 00:10:00.875' in t and '590.75 秒' in t for t in texts)
        assert sum(t in LEADS for t in texts) == 12
        assert any(t.startswith('图 ') and '/3' in t for t in texts)
        assert any('保留医生图注' in t for t in texts)
    normalized = [' '.join(t.split()) for _, _, _, t, _ in drawn]
    assert any('图 1/3 / 起始' in t for t in normalized)
    assert any('图 2/3 / 中间' in t for t in normalized)
    assert any('图 3/3 / 末尾' in t for t in normalized)
    assert len(traces) == page_count * 12
    for _, x, _, text, size in drawn:
        if text.startswith(('房颤片段', '整段 ', '图 ')):
            assert x + pdfmetrics.stringWidth(text, FONT_NAME, size) <= 200 * mm


def test_heading_clock_preserves_fraction_and_calendar_boundary():
    assert clock_ms({}, 86400.005) == 'D2 00:00:00.005'
    assert clock_ms(dict(start_time='2026-01-01 23:59:59.990'), .015) == '2026-01-02 00:00:00.005'


def test_native_api_three_figures_stay_one_episode_after_remove_reopen(synthetic_app, synthetic_case, monkeypatch):
    _, cid, paths = synthetic_case
    client = synthetic_app.test_client()
    base = '/api/cases/' + cid
    hashes = {key: sha256(path.read_bytes()).hexdigest() for key, path in paths.items()}
    rhythm = client.get(base + '/rhythm-review').json
    response = client.put(base + '/rhythm-review', json=dict(
        **{key: rhythm[key] for key in ('case_id', 'analysis_basis', 'analysis_revision', 'beat_revision')},
        revision=rhythm['revision'], confirmed=True, operation='save',
        document=dict(episodes=[dict(id='math-multistrip', kind='AF', start_s=8, end_s=85,
            status='confirmed', source='manual', note='Mathematical test identity, not a patient')], bookmarks={})))
    assert response.status_code == 200, response.json
    events = client.get(base + '/report-events?category=AF').json
    assert events['total'] == 1
    event = events['items'][0]
    summary = client.get(base + '/report-sections').json['af_summary']
    assert summary['confirmed_af']['count'] == 1
    assert summary['confirmed_af']['seconds'] == 77
    picks = [dict(event_id=event['event_id'], basis_version=event['basis_version'],
        strip_id='math-' + role, representative_role=role, range_start_s=start,
        range_end_s=start + 7, duration_s=7, leads=LEADS,
        caption='Keep caption ' + role, notes='Keep clinical note')
        for role, start in [('end', 78), ('start', 8), ('middle', 45)]]

    def save(entries):
        report = client.get(base + '/report').json
        report['composition'].update(page_selection_version=1, included_pages=['event_strips'], selected_events=entries)
        result = client.put(base + '/report', json=dict(status='draft', conclusion='Mathematical test only',
            expected_version=report['version'], expected_review_revision=report['review_revision'],
            composition=report['composition']))
        assert result.status_code == 200, result.json
        assert result.json['composition']['selected_events'] == client.get(base + '/report').json['composition']['selected_events']
        return result.json

    saved = save(picks)
    assert len(saved['composition']['selected_events']) == 3
    seen = []
    original = Canvas.drawString

    def capture(self, x, y, text, *args, **kwargs):
        seen.append(str(text))
        return original(self, x, y, text, *args, **kwargs)

    monkeypatch.setattr(Canvas, 'drawString', capture)
    assert client.get(base + '/report.pdf').status_code == 200
    assert sum(t.startswith('房颤片段 1') and '3 张代表图' in t for t in seen) == 3
    assert sum(t.startswith('图 ') and '/3' in t for t in seen) == 3
    assert client.get(base + '/report-events?category=AF').json['total'] == 1
    save([picks[0], picks[2]])
    seen.clear()
    assert client.get(base + '/report.pdf').status_code == 200
    assert sum(t.startswith('房颤片段 1') and '2 张代表图' in t for t in seen) == 2
    save(picks)
    restored = client.get(base + '/report').json['composition']['selected_events']
    assert [e['strip_id'] for e in restored] == [e['strip_id'] for e in saved['composition']['selected_events']]
    assert client.get(base + '/report-sections').json['af_summary'] == summary
    assert {key: sha256(path.read_bytes()).hexdigest() for key, path in paths.items()} == hashes
