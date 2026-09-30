"""Sequence flags must not depend on which phase starts a recording/segment."""
from itertools import product
import json
from pathlib import Path
import subprocess
from types import SimpleNamespace

import pytest

from ecg_core.clinical_analysis import build_index, query_index, validate_report
from ecg_core.report_layout import report_statistics
from scripts.validate_mitdb_counts import CYCLES, SETTINGS, adapt, audit, reference_events


def make_feed(text):
    rows = [dict(id=f's:{i}', sample_index=i*200, class_code=c, name=c,
                 rr_ms=1000 if i and c != 'X' and text[i-1] != 'X' else 0,
                 hr=60 if i and c != 'X' and text[i-1] != 'X' else None) for i,c in enumerate(text)]
    return SimpleNamespace(beats=rows, markers=[], duration=len(text), document={'settings': SETTINGS})


ROTATIONS = [(kind, cycle[p:]+cycle[:p]) for kind,cycle in CYCLES.items() for p in range(len(cycle))]


@pytest.mark.parametrize('code', ['S','V'])
@pytest.mark.parametrize('kind,cycle', ROTATIONS)
def test_all_phases_include_valid_trailing_beat(kind, cycle, code):
    text = (cycle*2+cycle[0]).replace('S', code)
    index = build_index(make_feed(text))
    items = query_index(index, {'category':code, 'mode':kind})['items']
    assert len(items) == 1
    assert (items[0]['start_sample'], items[0]['end_sample']) == (0, (len(text)-1)*200)
    assert items[0]['target_samples'] == [i*200 for i,c in enumerate(text) if c == code]
    assert items[0]['pattern_only'] is True
    assert items[0]['diagnosis_status'] == 'pending'


@pytest.mark.parametrize('kind,cycle', list(CYCLES.items()))
def test_two_cycles_required_and_other_types_break_pattern(kind, cycle):
    for separator in ['X','V','A','P','J','Z','B']:
        index = build_index(make_feed(cycle+separator+cycle))
        assert query_index(index, {'category':'S','mode':kind})['total'] == 0
    index = build_index(make_feed((cycle*2)[:-1]))
    assert query_index(index, {'category':'S','mode':kind})['total'] == 0


def brute_spans(text, cycle):
    rotations = [cycle[n:]+cycle[:n] for n in range(len(cycle))]
    # Enumerate all substrings, then independently pick earliest / longest.
    candidates = [(a,b) for a in range(len(text)) for b in range(a+2*len(cycle),len(text)+1)
                  if any(text[a:b] == (unit*((b-a+len(unit)-1)//len(unit)))[:b-a] for unit in rotations)]
    result, cursor = [], 0
    for a,b in sorted(candidates, key=lambda x:(x[0],-x[1])):
        if a >= cursor:
            result.append((a,b))
            cursor = b
    return result


def test_exhaustive_short_sequences_agree_with_enumerated_contract():
    from ecg_core.clinical_analysis import repeating_spans
    # All three-letter sequences through length eight, including gap boundaries.
    for n in range(9):
        for letters in product('NSX', repeat=n):
            text = ''.join(letters)
            for kind,cycle in CYCLES.items():
                expected = brute_spans(text,cycle)
                assert list(repeating_spans(list(text),list(cycle))) == expected
                assert reference_events(list(text),'S')[kind] == expected


def test_periods_are_nonoverlapping_within_each_mode_and_linear_on_long_run():
    from ecg_core.clinical_analysis import repeating_spans
    text = list('SN'*50000+'SS'+'NS'*10)
    spans = list(repeating_spans(text,list('NS')))
    assert spans == [(0,100001),(100001,len(text))]
    assert all(a1 <= b1 <= a2 <= b2 for (a1,b1),(a2,b2) in zip(spans,spans[1:]))


def test_hour_filter_report_counts_and_edit_refresh():
    f = make_feed('SNSNSXNNSSNSS')
    for row in f.beats:
        row['sample_index'] += 179600 # First periodic event crosses 00:00 clock boundary.
    f.duration = 911
    index = build_index(f)
    index['start_time'] = '2000-01-01 23:45:00'
    result = query_index(index, {'category':'S','mode':'bigeminy'})
    assert result['total'] == 1 and [b['count'] for b in result['time_bins']] == [1,0]
    assert query_index(index, {'category':'S','mode':'bigeminy','time_start':900,'time_end':910})['total'] == 0
    stats = report_statistics(index,index['start_time'],SETTINGS)
    assert stats['summary']['S']['bigeminy'] == 1
    assert [h['S']['bigeminy'] for h in stats['hourly']] == [1,0]
    assert sum(h['S']['total'] for h in stats['hourly']) == 7
    f.beats[2]['class_code'] = 'N'
    changed = build_index(f)
    assert query_index(changed, {'category':'S','mode':'bigeminy'})['total'] == 0
    assert changed['basis_versions']['S'] != index['basis_versions']['S']


def test_old_semantic_basis_is_rejected_even_when_event_id_survives():
    review = {'steps':{'edit':{'status':'done'}}}
    index = build_index(make_feed('NSNS'),review=review)
    event = query_index(index, {'category':'S','mode':'bigeminy'})['items'][0]
    assert event['basis_version'].endswith('-periodic-v2')
    old = event['basis_version'].removesuffix('-periodic-v2')
    assert index['data_version'].endswith('-periodic-v2-af-end-v1-status-v2')
    with pytest.raises(ValueError, match='失效'):
        validate_report(index, {'selected_events':[{'event_id':event['event_id'],'basis_version':old}]},review,True)


def test_browser_matches_rotations_and_broken_sequences():
    cases = [make_feed(cycle*2+cycle[0]+'X'+cycle*3) for _,cycle in ROTATIONS]
    cases += [make_feed('VNVNVXNNVVNVV'),make_feed('NSSNSSSNSSNSS')]
    script = "const a=require('./static/js/clinical-analysis.js');const f=JSON.parse(require('fs').readFileSync(0,'utf8'));process.stdout.write(JSON.stringify(f.map(x=>a.buildIndex(x))));"
    actual = json.loads(subprocess.check_output(['node','-e',script],input=json.dumps([vars(x) for x in cases]).encode(),cwd=Path(__file__).parents[1]))
    assert actual == [build_index(x) for x in cases]


def test_wfdb_mapping_does_not_confuse_shortcut_codes_or_bridge_noise():
    f, original = adapt([0,360,720,900,1080,1440,1800,2160,2520],
                        ['N','A','R','x','|','V','a','!','N'],3000,360)
    assert [r['class_code'] for r in f.beats] == ['N','S','BR','X','V','Z','X','N']
    assert f.markers[0]['class_code'] == 'O'
    assert f.beats[4]['rr_ms'] == 0 and f.beats[-1]['rr_ms'] == 0
    assert original == {'over2500':0,'over3000':0}
    assert not audit(f)['errors']


@pytest.mark.parametrize('samples,symbols,fs', [([1,2],['N','N'],360),([0],['?'],360),([0],['N'],200),([10,0],['N','V'],360)])
def test_adapter_rejects_unknown_or_ambiguous_input(samples,symbols,fs):
    with pytest.raises(ValueError):
        adapt(samples,symbols,1000,fs)
