"""Explicit import assumptions; never infer ADC gain from a display setting."""
from .config import CHANNEL_COUNT, SAMPLE_RATE


def raw_signal_metadata():
    # DATA has no decoded acquisition/calibration header in this importer.
    # Derived limb leads also remain device units (including half-unit values).
    return {
        'units': 'device_unit',
        'unit_label': '设备单位',
        'calibration_verified': False,
        'calibration_note': 'u = 设备单位，电压未校准；显示放大不等于 mm/mV 标定。',
        'signal_profile': {
            'id': 'data-int16le-8ch-200hz-v1',
            'sample_rate_hz': SAMPLE_RATE,
            'channel_count': CHANNEL_COUNT,
            'sample_format': 'little-endian int16',
            'stored_leads': ['I', 'II', 'V1', 'V2', 'V3', 'V4', 'V5', 'V6'],
            'derived_leads': {'III': 'II-I', 'aVR': '-(I+II)/2',
                              'aVL': 'I-II/2', 'aVF': 'II-I/2'},
            'basis': '当前支持的 DATA 导入格式；采样率与通道映射尚未经设备资料核验',
            'device_verified': False,
        },
    }


def normalize_voltage_estimate(value=None):
    """Explicit assumption only; never upgrades raw acquisition metadata."""
    from math import isfinite
    if value is None:
        return None
    if not isinstance(value, dict) or value.get('mode') != 'estimated':
        raise ValueError('电压估算必须明确标记 estimated')
    factor = value.get('uv_per_unit')
    if isinstance(factor, bool) or not isinstance(factor, (int, float)) or not isfinite(factor) or not .000001 <= factor <= 10000:
        raise ValueError('估算系数须为 0.000001–10000 µV/设备单位的有限数值')
    return {'mode': 'estimated', 'uv_per_unit': float(factor), 'calibration_verified': False}


def voltage_estimate_note(value):
    estimate = normalize_voltage_estimate(value)
    return (f"估算电压：1 u = {estimate['uv_per_unit']:g} µV；假设零点为 0，非设备校准，不能保证临床一致性"
            if estimate else '设备单位，电压未校准')


def paper_uv_per_unit(wave, estimate=None):
    verified = calibrated_uv_per_unit(wave)
    if verified is not None:
        return verified
    value = normalize_voltage_estimate(estimate)
    return value['uv_per_unit'] if value and wave.get('units') == 'device_unit' else None


def calibrated_uv_per_unit(wave):
    """Unit conversion only, NOT a calibration validator or an ADC gain default.

    Current DATA readers never set calibration_verified. This guard prevents
    legacy/foreign payloads with only a boolean from acquiring a 1 mV ruler.
    """
    if wave.get('calibration_verified') is not True:
        return None
    unit = wave.get('units')
    return {'µV': 1.0, 'μV': 1.0, 'uV': 1.0, 'mV': 1000.0}.get(unit) if isinstance(unit, str) else None
