"""Protocol/parser tests do not require network, WFDB or clinical raw inputs."""
import pytest
from scripts.validate_qtdb import eligible_reason, metrics, reference_beats, split_for, summarize


def test_reference_parser_uses_wave_number_and_not_u_end():
    symbols = ['(', 'p', ')', '(', 'N', ')', 't', ')', 'u', ')']
    nums = [0, 0, 0, 1, 0, 1, 0, 2, 0, 3]
    beats = reference_beats([0, 5, 10, 20, 30, 40, 70, 90, 110, 130], symbols, nums)
    assert beats == [dict(r_sample=30, q_sample=20, t_sample=90)]


def test_missing_or_ambiguous_reference_stays_missing():
    b = reference_beats([10, 20, 30, 40, 50], ['(', 'N', ')', 't', ')'], [1, 1, 1, 0, 3])
    assert b[0]['t_sample'] is None
    assert eligible_reason(b, 0, 250) == 'missing_reference_endpoints'
    with pytest.raises(ValueError):
        reference_beats([20, 10], ['(', 'N'], [1, 1])


def test_eligibility_reports_edges_sparse_and_fast_references():
    beats = [dict(r_sample=s, q_sample=s-10, t_sample=s+80) for s in [250, 500, 750, 1500]]
    assert eligible_reason(beats, 0, 250) == 'reference_neighbor_unavailable'
    assert eligible_reason(beats, 1, 250) == ''
    assert eligible_reason(beats, 2, 250) == 'sparse_reference_gap'
    beats[2]['r_sample'] = 600
    assert eligible_reason(beats, 1, 250) == 'rr_outside_current_qt_conditions'


def test_error_summary_keeps_rejections_in_denominator_and_no_fake_zero():
    rows = [dict(status='excluded', reason='missing'), dict(status='rejected', reason='quality'),
            dict(status='accepted', reason='', q_error_ms=10, t_error_ms=-60, qt_error_ms=-70)]
    result = summarize(rows)
    assert result['attempted'] == 2 and result['coverage_of_attempts'] == .5
    assert result['t']['over_50ms'] == 1 and result['qt']['bias_ms'] == -70
    assert metrics([])['mae_ms'] is None
    assert metrics([0])['sd_ms'] is None


def test_split_is_record_level_and_deterministic():
    assert split_for('sel100') == split_for('sel100')
    assert {split_for(f'sel{i}') for i in range(100, 150)} == {'development', 'evaluation'}
