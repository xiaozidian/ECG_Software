"""Explicit QT shape regressions; not a substitute for real annotation audit."""
import numpy as np
import pytest
from ecg_core.advanced_analysis import delineate


def waves():
    t = (np.arange(180)-50)*5
    qrs = 900*np.exp(-(t/15)**2)-160*np.exp(-((t-30)/18)**2)
    tw = 180*np.exp(-((t-260)/45)**2)
    return t, qrs, tw


@pytest.mark.parametrize('polarity', [1, -1])
def test_separate_u_wave_requires_manual_endpoints_instead_of_extending_qt(polarity):
    t, qrs, tw = waves()
    u = 110*np.exp(-((t-500)/25)**2)
    plain = delineate(polarity*(qrs+tw), 1000)
    with_u = delineate(polarity*(qrs+tw+u), 1000)
    assert plain['valid']
    assert not with_u['valid']
    assert 'T/U' in with_u['reason']
    assert 'qt_ms' not in with_u


@pytest.mark.parametrize('polarity', [1, -1])
def test_connected_biphasic_t_retains_terminal_lobe(polarity):
    t, qrs, _ = waves()
    tw = 180*np.exp(-((t-235)/40)**2)-170*np.exp(-((t-295)/40)**2)
    result = delineate(polarity*(qrs+tw), 1000)
    assert result['valid']
    assert 335 <= result['t_ms'] <= 365


def test_t_peak_at_window_edge_is_rejected_without_exception():
    t, qrs, _ = waves()
    rising = np.maximum(t-120, 0)*2
    result = delineate(qrs+rising, 1000)
    assert not result['valid']


@pytest.mark.parametrize('polarity', [1, -1])
def test_st_depression_does_not_hide_opposite_terminal_t(polarity):
    t, qrs, _ = waves()
    st = -160*np.exp(-((t-125)/35)**2)
    tw = 180*np.exp(-((t-325)/45)**2)
    result = delineate(polarity*(qrs+st+tw), 1000)
    assert result['valid']
    assert 380 <= result['t_ms'] <= 405
