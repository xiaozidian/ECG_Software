"""Read-only global AF/AFL subtype facts for retained adopted report text."""
from copy import deepcopy
from hashlib import sha256

from test_analysis_provenance import synthetic_app, synthetic_case


def test_confirmed_subtype_facts_ignore_page_filters_and_retire_with_diagnosis(synthetic_app, synthetic_case):
    _, cid, paths = synthetic_case
    client = synthetic_app.test_client()
    base = '/api/cases/' + cid
    hashes = {key: sha256(path.read_bytes()).hexdigest() for key, path in paths.items()}

    def counts(expected):
        for params in ({'category': 'AF'}, {'category': 'fastest', 'limit': 1},
                       {'category': 'AF', 'mode': 'AF', 'offset': 50}, {'category': 'ST'}):
            response = client.get(base + '/report-events', query_string=params)
            assert response.status_code == 200, response.json
            assert response.json['af_confirmed_subtype_counts'] == expected
            # Preserve the existing global-EDIT-gated category field exactly.
            assert response.json['confirmed_category_counts']['AF'] == 0

    def save(episodes):
        current = client.get(base + '/rhythm-review').json
        response = client.put(base + '/rhythm-review', json=dict(
            **{key: current[key] for key in ('case_id', 'analysis_basis', 'analysis_revision', 'beat_revision')},
            revision=current['revision'], confirmed=True, operation='save',
            document=dict(episodes=episodes, bookmarks={})))
        assert response.status_code == 200, response.json

    episodes = [dict(id=key, kind=kind, status=status, start_s=a, end_s=b,
                     note='Mathematical test only, not a patient diagnosis') for key, kind, status, a, b in (
        ('af-confirmed', 'AF', 'confirmed', 5, 15), ('af-pending', 'AF', 'pending', 16, 25),
        ('afl-confirmed', 'AFL', 'confirmed', 30, 40), ('afl-pending', 'AFL', 'pending', 41, 50),
        ('af-excluded', 'AF', 'excluded', 55, 60))]
    counts(dict(AF=0, AFL=0))
    save(episodes)
    counts(dict(AF=1, AFL=1))
    # A subtype change withdraws the old AF fact; a retained old text block
    # cannot cite the other subtype's confirmed episode as its evidence.
    changed = deepcopy(episodes)
    changed[0]['kind'] = 'AFL'
    save(changed)
    counts(dict(AF=0, AFL=2))
    changed[0]['status'] = 'pending'
    save(changed)
    counts(dict(AF=0, AFL=1))
    changed[2]['status'] = 'excluded'
    save(changed)
    counts(dict(AF=0, AFL=0))
    before = deepcopy(client.get(base + '/rhythm-review').json)
    counts(dict(AF=0, AFL=0))
    assert client.get(base + '/rhythm-review').json == before
    assert {key: sha256(path.read_bytes()).hexdigest() for key, path in paths.items()} == hashes
