"""A bad GET lead must fail, never silently turn into a lead-II waveform."""
import array

import pytest

from test_analysis_provenance import synthetic_case, synthetic_app
from ecg_core.waveform import ALL_LEADS, read_waveform, read_event_waveform


@pytest.mark.parametrize('endpoint', ['waveform', 'event-waveform', 'report-strip'])
@pytest.mark.parametrize('leads', ['', 'BAD', 'II,BAD', 'II,', ',II', 'II,II'])
def test_bad_get_leads_are_rejected_without_waveform_payload(synthetic_app, synthetic_case, endpoint, leads):
    client = synthetic_app.test_client()
    params = {'leads': leads, 'start': 0, 'end': 4}
    if endpoint == 'report-strip':
        events = client.get(f'/api/cases/{synthetic_case[1]}/report-events').json['items']
        assert events, 'Synthetic fixture must have a current report event'
        params.update(event_id=events[0]['event_id'], basis_version=events[0]['basis_version'])
    response = client.get(f'/api/cases/{synthetic_case[1]}/{endpoint}',
                          query_string=params)
    assert response.status_code == 400
    assert 'error' in response.json and 'leads' not in response.json
    assert '导联' in response.json['error']
    assert response.headers['Cache-Control'] == 'no-store'
    assert response.headers['X-Content-Type-Options'] == 'nosniff'


@pytest.mark.parametrize('endpoint', ['waveform', 'event-waveform'])
@pytest.mark.parametrize('selected', [['II', 'V1', 'V5'], ['aVR', 'III', 'I'], ALL_LEADS])
def test_legal_api_leads_preserve_every_sample_and_formula(synthetic_app, synthetic_case, endpoint, selected):
    # Each stored channel differs, including extreme int16 and fractional
    # derived limb leads. This is a disposable mathematical input.
    frames = array.array('h', [-32768, 32767, 1000, -2000, 3000, 4, 5, 6]) * (90 * 200)
    synthetic_case[2]['data'].write_bytes(frames.tobytes())
    response = synthetic_app.test_client().get(f'/api/cases/{synthetic_case[1]}/{endpoint}',
        query_string={'start': 1, 'duration': 4, 'end': 5, 'max_points': 1200,
                      'filter': 'raw', 'leads': ','.join(selected)})
    assert response.status_code == 200
    expected = (read_waveform(synthetic_case[2]['data'], 1, 4, selected, 1200, False)
                if endpoint == 'waveform' else
                read_event_waveform(synthetic_case[2]['data'], 1, 5, selected, 1200))
    assert response.json['leads'] == expected['leads']
    assert set(response.json['leads']) == set(selected)
    assert response.json['start_s'] == expected['start_s']
    assert response.json['duration_s'] == expected['duration_s']


@pytest.mark.parametrize('endpoint', ['waveform', 'event-waveform'])
def test_omitted_leads_keep_the_legacy_default(synthetic_app, synthetic_case, endpoint):
    client = synthetic_app.test_client()
    url = f'/api/cases/{synthetic_case[1]}/{endpoint}'
    omitted = client.get(url, query_string={'start': 1, 'end': 5, 'duration': 4})
    explicit = client.get(url, query_string={'start': 1, 'end': 5, 'duration': 4,
                                            'leads': 'II,V1,V5'})
    assert omitted.status_code == explicit.status_code == 200
    assert omitted.json['leads'] == explicit.json['leads']
    assert set(omitted.json['leads']) == {'II', 'V1', 'V5'}
