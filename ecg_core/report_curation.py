"""Local report presentation metadata; never a beat/diagnosis edit."""
from .report_layout import LEADS


def strip_curation(raw):
    result = {}
    if 'print_enabled' in raw:
        if type(raw['print_enabled']) is not bool:
            raise ValueError('图条打印状态必须为布尔值')
        result['print_enabled'] = raw['print_enabled']
    if 'notes' in raw:
        if not isinstance(raw['notes'], str) or len(raw['notes']) > 2000:
            raise ValueError('图条注释最多 2000 字')
        result['notes'] = raw['notes']
    if 'preview_lead' in raw:
        if raw['preview_lead'] not in LEADS:
            raise ValueError('无效的图条预览导联')
        result['preview_lead'] = raw['preview_lead']
    return result


def narrative_templates(raw):
    if raw is None:
        return []
    if not isinstance(raw, list) or len(raw) > 30:
        raise ValueError('综述模板最多 30 个')
    result, seen, defaults = [], set(), 0
    for item in raw:
        if not isinstance(item, dict):
            raise ValueError('无效的综述模板')
        for key, limit in [('id', 80), ('name', 80), ('source', 12000)]:
            if not isinstance(item.get(key), str) or not item[key].strip() or len(item[key]) > limit:
                raise ValueError('综述模板字段无效或过长')
        if item['id'] in seen or type(item.get('is_default', False)) is not bool:
            raise ValueError('综述模板 ID 或默认状态无效')
        seen.add(item['id'])
        defaults += item.get('is_default', False)
        if defaults > 1:
            raise ValueError('只能选择一个默认综述模板')
        # Saved source is inert text. The UI only interprets whitelisted macros;
        # scripts from third-party reference software are never executed.
        result.append({k: item.get(k, False) for k in ('id', 'name', 'source', 'is_default')})
    return result
