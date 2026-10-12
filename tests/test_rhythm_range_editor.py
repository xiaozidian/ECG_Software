"""Manual AF-range UI contracts and an independent integer-sample backend oracle."""
import json
import pathlib
import subprocess

from ecg_core.overview import episode_annotations, validate_document
from ecg_core.rr_quality import annotation_exclusions


ROOT = pathlib.Path(__file__).resolve().parents[1]


def test_manual_af_session_contracts():
    result = subprocess.run(['node', 'tests/browser_rhythm_range_editor.cjs'], cwd=ROOT,
                            text=True, capture_output=True, check=True)
    receipt = json.loads(result.stdout)
    assert receipt['passed'] == 33


def test_manual_af_app_adapter_contracts():
    result = subprocess.run(['node', 'tests/browser_rhythm_range_app.cjs'], cwd=ROOT,
                            text=True, capture_output=True, check=True)
    assert json.loads(result.stdout)['passed'] == 21


def test_manual_sample_grid_roundtrips_without_expanding_inclusive_end():
    # Independent expected inclusive occupancy, including one sample and the
    # recording's final sample. No screen coordinate or implementation rounding.
    pairs = [(0, 1), (2000, 2001), (2010, 2015), (127999, 128000)]
    doc = {'episodes': [dict(id=f'grid-{a}', start_s=a / 200, end_s=b / 200,
                            kind='AF', status='pending', source='manual', note='')
                        for a, b in pairs], 'bookmarks': {'fastest': 12.005}}
    clean = validate_document(doc, 640)
    annotations = episode_annotations(clean)
    assert [(x['sample_index'], x['details']['end_sample']) for x in annotations] == [
        (a, b - 1) for a, b in pairs]
    assert annotation_exclusions(annotations) == [(a / 200, b / 200) for a, b in pairs]
    assert clean['bookmarks'] == doc['bookmarks']
