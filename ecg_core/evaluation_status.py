"""Presentation states for research screening; never certify a normal ECG."""
import math


def stt_status(automatic=None):
    automatic = automatic or {}
    quality = automatic.get('quality') or {}
    coverage = quality.get('coverage_pct')
    if isinstance(coverage, bool) or not isinstance(coverage, (int, float)) or not math.isfinite(coverage):
        coverage = None
    if not automatic.get('enabled'):
        code, label = 'not_evaluated', '未评估'
        note = '筛查尚未运行或缺少输入；不能解释为未检出或正常。'
    elif not quality.get('eligible_blocks', 0) or coverage is None or coverage <= 0:
        code, label = 'not_evaluable', '不可评估'
        note = '没有通过质量门槛的可评估数据；零候选不能解释为正常。'
    elif automatic.get('items'):
        code, label = 'pending_review', '事件待复核'
        note = '研究筛查候选须回看原始波形；不生成自动诊断。'
    else:
        code, label = 'no_findings', '已评估范围未检出'
        note = '在通过质量门槛的范围内未检出持续性候选；不代表确认正常。'
    if coverage is not None and coverage < 100 and automatic.get('enabled'):
        note += ' 未覆盖或被排除的区间仍需独立评估。'
    return dict(code=code, label=label, coverage_pct=coverage, note=note,
                can_assert_normal=False)
