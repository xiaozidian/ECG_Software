"""Create one deterministic mathematical case; never consume existing datasets."""
from pathlib import Path
import hashlib
import importlib.util
import json
import sys


def generate(output: Path, release_id: str) -> dict:
    root = Path(__file__).resolve().parent.parent
    path = root / 'scripts/generate_synthetic_demo.py'
    spec = importlib.util.spec_from_file_location('public_math_generator', path)
    g = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = g
    spec.loader.exec_module(g)
    case_id = 'math-4314-001'
    duration = 600
    beats = g._build_beats(duration * g.SAMPLE_RATE, 64, 1, .731)
    profile = g.CaseProfile(1, case_id, 64, .731, beats)
    output.mkdir(parents=True, exist_ok=False)
    waveform = output / 'waveform.bin'
    g._write_waveform(waveform, profile, duration * g.SAMPLE_RATE)
    stats = g._statistics_for(beats, duration)
    summary = {**stats, 'ventricular_beats': stats['v_beats'], 'supraventricular_beats': stats['s_beats']}
    case = {
        'software_release_id': release_id, 'case_id': case_id, 'display_case_id': 'M01', 'active': True, 'phi_masked': True,
        'metadata': {'name': '数学演示病例', 'patient_id': 'MATH-001', 'sex': '未设置', 'age': None,
                     'start_time': '2026-01-02 08:00:00', 'start_iso': '2026-01-02T08:00:00',
                     'duration_text': '10分钟', 'source_record_duration_text': '10分钟数学合成记录',
                     'clinical_diagnosis': '纯数学函数生成，不对应任何患者', 'source_clinical_diagnosis': '',
                     'pacemaker': '未设置', 'department': '', 'requesting_physician': '', 'bed': ''},
        'technical': {'duration_seconds_raw': duration, 'sample_rate_hz': 200, 'independent_channels': 8,
                      'data_bytes': waveform.stat().st_size, 'report_pages': 0},
        'summary': summary, 'source_report_summary': summary,
        'conclusion': '纯数学合成波形，仅演示软件交互，不对应真实患者，不构成疾病金标准或临床结论。',
        'beats': [{'sample_index': b.sample_index, 'time_s': b.sample_index / 200, 'group': b.group,
                   'label': {1: 'N', 2: 'S', 3: 'V', 34: '噪声'}[b.group], 'rr_ms': b.rr_ms,
                   'hr': round(60000 / b.rr_ms, 1) if b.rr_ms else None} for b in beats],
        'integrity': {'mathematical_fixture': True, 'raw_patient_data': False, 'manifest_available': True,
                      'algorithm': 'SHA-256', 'file_count': 2},
        'simulation_profile': {'kind': 'pure-mathematical-formulas', 'real_patient_inputs_read': False,
                               'source_waveform_copied': False, 'rhythm_candidate_windows_s': []},
        'report_image_urls': [], 'generated_report_url': '#mathematical-demo',
    }
    js = output / 'case-data.js'
    js.write_text('"use strict";\nwindow.__CARDIOINSIGHT_MATHEMATICAL_CASE__ = ' + json.dumps(case, ensure_ascii=False, separators=(',', ':')) + ';\n', encoding='utf-8')
    return {'release_id': release_id, 'kind': 'pure_mathematical', 'case_id': case_id, 'duration_seconds': duration,
            'sample_rate_hz': 200, 'stored_channels': 8, 'beat_count': len(beats), 'seed_parameters': {'base_hr': 64, 'phase': .731, 'case_number': 1},
            'existing_data_read': False, 'patient_inputs_read': False,
            'generator_sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
            'payload_generator_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            'assets': {p.name: {'bytes': p.stat().st_size, 'sha256': hashlib.sha256(p.read_bytes()).hexdigest()} for p in [waveform, js]}}
