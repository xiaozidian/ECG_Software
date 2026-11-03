"""Report-only grouping of the same validated original RR across candidate sources.

Source records and detector thresholds are untouched. Legacy event IDs remain
addressable, so an already selected automatic event keeps its own review proof.
"""
from __future__ import annotations

from .report_layout import valid_rr_pairs, resolve_strip

RR_CATEGORIES = ('pause', 'rr_candidate')


def rr_interval_groups(index):
    events = [e for e in index['events'] if e.get('category') in RR_CATEGORIES]
    if not events:
        return []
    pairs = {b['sample_index']: (a, b) for a, b in valid_rr_pairs(index['rows'], index['duration_s'])}
    grouped = {}
    for event in events:
        pair = pairs.get(event['start_sample'])
        context = event.get('candidate_context') or {}
        if not pair or event.get('rr_ms') != pair[1]['rr_ms']:
            continue
        a, b = pair
        if event['category'] == 'pause' and b['rr_ms'] <= 2500:
            continue
        if event['category'] == 'rr_candidate' and (a['sample_index'] != context.get('rr_start_sample') or b['sample_index'] != context.get('rr_end_sample')):
            continue
        # The current index is case/source scoped by the receiver. beat_version
        # binds its current beat IDs, positions, classes and settings. Only exact
        # current-basis selections are deduplicated below.
        key = f"rr-pair-v1:{index['beat_version']}:{a['sample_index']}:{b['sample_index']}"
        grouped.setdefault(key, []).append(event)
    result = []
    for key, aliases in grouped.items():
        aliases.sort(key=lambda e: (0 if e['category'] == 'rr_candidate' else 1, e['event_id']))
        descriptors = [{k: e[k] for k in ('event_id', 'basis_version', 'category')} for e in aliases]
        result.append({**aliases[0], 'rr_semantic_key': key,
                       'rr_alias_event_ids': [e['event_id'] for e in aliases],
                       'rr_aliases': descriptors,
                       'rr_sources': [source for source, category in [('auto', 'pause'), ('manual', 'rr_candidate')]
                                      if any(e['category'] == category for e in aliases)]})
    return result


def rr_alias_groups(index):
    return {event_id: group for group in rr_interval_groups(index) for event_id in group['rr_alias_event_ids']}


def deduplicate_rr_selections(index, entries):
    """Keep first settings, merging only aliases that are valid in this index.

    Stale/missing events stay in the composition for the existing reconciliation
    and approval checks. A GET may project this result, but never writes it back.
    """
    lookup = {e['event_id']: e for e in index['events']}
    groups = rr_alias_groups(index) if any(lookup.get(entry.get('event_id'), {}).get('category') in RR_CATEGORIES for entry in entries) else {}
    seen, result, merged = set(), [], []
    for entry in entries:
        event = lookup.get(entry.get('event_id'))
        group = groups.get(entry.get('event_id'))
        current = event and event['basis_version'] == entry.get('basis_version')
        key = group['rr_semantic_key'] if group and current else None
        if current and event.get('category') == 'AF':
            try:
                spec = resolve_strip(index,event,entry)
                key = ('af-strip',event['event_id'],event['basis_version'],round(spec['start_s']*200),round(spec['end_s']*200))
            except ValueError:
                # Invalid/stale geometry stays visible for existing recovery.
                key = None
        elif event and event.get('category') != 'AF' and not key:
            key = ('event',event['event_id'])
        if key and key in seen:
            merged.append(entry['event_id'])
            continue
        if key:
            seen.add(key)
        result.append(entry)
    return result, merged
