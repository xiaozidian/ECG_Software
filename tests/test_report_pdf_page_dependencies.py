"""Export invokes only analysis needed by selected pages; source/ref guards remain real."""
from io import BytesIO
import pytest
from test_analysis_provenance import synthetic_case, synthetic_app

NON_ST = ['cover','summary','hourly','event_strips','scatter','pacing','af','hrt','dc',
          'hrv_time','hrv_frequency','hrv_overview']

@pytest.mark.parametrize('page', NON_ST + ['st_trend','t_trend','st_events'])
def test_native_pdf_loads_st_only_for_selected_st_pages(synthetic_app, monkeypatch, page):
    client=synthetic_app.test_client()
    import app as application
    cid=client.get('/api/cases').json['items'][0]['case_id']
    store=client.application.extensions['storage']
    original=store.get_report(cid,'')
    store.save_report(cid,'engineering test','draft','test',dict(page_selection_version=1,
        included_pages=[page]),expected_version=original['version'])
    original_builder=application.build_stt_review
    calls=[]
    def observe(*args,**kwargs):
        calls.append(1)
        return original_builder(*args,**kwargs)
    monkeypatch.setattr(application,'build_stt_review',observe)
    def forbidden_windows(*args,**kwargs):
        raise AssertionError('unused legacy whole-record HRV windows must not be computed')
    monkeypatch.setattr(application,'hrv_windows',forbidden_windows)
    captured={}
    def pdf(case,metrics,report):
        captured.update(report)
        return BytesIO(b'%PDF-page-dependencies')
    monkeypatch.setattr(application,'build_report_pdf',pdf)
    response=client.get('/api/cases/'+cid+'/report.pdf')
    assert response.status_code==200,response.json
    st=page in ['st_trend','t_trend','st_events']
    if not page.startswith('hrv_'):
        assert bool(calls)==st
    if page in ['scatter','pacing','af','hrt','dc']:
        evidence=captured['section_evidence']
        assert evidence['scatter']['total']>=0
        assert 'af_summary' in evidence and 'hrt' in evidence and 'dc' in evidence
    if page.startswith('hrv_'):
        assert captured['hrv_analysis']['hrv_review']['confirmation']['valid'] is False
        assert 'st_trends' in captured['hrv_analysis']
    if page in ['st_trend','t_trend','st_events']:
        assert 'st_trends' in captured['section_evidence']
        assert 'st_representatives' in captured['section_evidence']
