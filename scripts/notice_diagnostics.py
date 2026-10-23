"""Explain information gaps without claiming that the original omitted a field."""
from collections import Counter

LABELS = {
    'no_notices': '尚未收录相关通知',
    'no_current_notice': '尚未收录本届通知',
    'identity_unknown': '届次尚未确认',
    'identity_conflict': '届次信息冲突',
    'body_pending': '正文待抓取',
    'fetch_failed': '抓取失败',
    'body_empty': '抓取正文为空',
    'fields_pending': '字段待提取',
    'resource_pending': '附件／图片待解析',
    'resource_failed': '附件／图片解析失败',
    'not_extracted': '暂未提取到',
    'needs_review': '待核实',
    'conflict': '信息冲突',
    'confirmed': '已提取',
}
FIELD_KEYS = ('deadline', 'audiences', 'registrationMethods', 'registrationLinks',
              'requiredMaterials', 'contacts', 'groups')
DEADLINES = {'registration_deadline', 'campus_deadline', 'official_deadline'}


def facts(value):
    if isinstance(value, dict):
        if 'raw' in value and 'verification' in value:
            yield value
        else:
            for item in value.values():
                yield from facts(item)
    elif isinstance(value, list):
        for item in value:
            yield from facts(item)


def notice_check(notice):
    status = notice.get('fetchStatus') or notice.get('status')
    if status == 'empty':
        state = 'body_empty'
    elif status == 'failed' or notice.get('fetchError') or notice.get('error'):
        state = 'fetch_failed'
    elif status == 'success':
        state = 'confirmed' if notice.get('fields') else 'fields_pending'
    else:
        state = 'confirmed' if notice.get('fields') else 'body_pending'
    return {'url': notice['url'], 'title': notice['title'], 'date': notice.get('date', ''),
            'state': state, 'fetchStatus': status or 'pending',
            'error': notice.get('fetchError') or notice.get('error') or '',
            'fetchedAt': notice.get('fetchedAt'), 'hasFields': bool(notice.get('fields')),
            'resourceHints': notice.get('resourceHints', []),
            'identityConflicts': notice.get('association', {}).get('identityConflicts', []),
            'editionId': notice.get('association', {}).get('editionId'),
            'identityState': 'confirmed' if not notice.get('association', {}).get('ambiguous') and
                             (notice.get('association', {}).get('year') or
                              notice.get('association', {}).get('identityMethod') in {'explicit_anchor', 'explicit_reference'}) else 'needs_review'}


def diagnose_group(group, checks):
    counts = Counter(check['state'] for check in checks)
    gaps = [key for key in ('fetch_failed', 'body_pending', 'body_empty', 'fields_pending') if counts[key]]
    fallback = gaps[0] if gaps else 'not_extracted'
    states = {}
    for key in FIELD_KEYS:
        unresolved = [h for n in checks for h in n.get('resourceHints', [])
                      if h['state'] != 'parsed' and key in h['fieldKeys']]
        empty_state = fallback if gaps else ('resource_failed' if any(h['state'] == 'resource_failed' for h in unresolved)
                                             else 'resource_pending' if unresolved else fallback)
        if key == 'deadline':
            slots = [s for s in group.get('timeline', []) if s['kind'] in DEADLINES]
            state = ('conflict' if any(s['state'] == 'conflict' for s in slots) else
                     'needs_review' if any(s['state'] == 'needs_review' for s in slots) or
                     any(c['status'] == 'needs_review' for c in group.get('changes', [])) else
                     'confirmed' if slots else empty_state)
        else:
            values = list(facts(group.get('fields', {}).get(key, [])))
            state = ('conflict' if any('conflict' in f.get('flags', []) for f in values) else
                     'needs_review' if any(f['verification'] != 'source_matched' for f in values) else
                     'confirmed' if values else empty_state)
        states[key] = state
    reasons = gaps + [s for s in ('conflict', 'resource_failed', 'resource_pending', 'needs_review', 'not_extracted') if s in states.values()]
    primary = next((s for s in ('conflict', 'fetch_failed', 'body_pending', 'body_empty',
                               'fields_pending', 'resource_failed', 'resource_pending', 'needs_review', 'not_extracted') if s in reasons), 'confirmed')
    return {'primary': primary, 'reasons': reasons, 'fieldStates': states,
            'noticeCounts': dict(counts), 'notices': checks,
            'partial': bool(gaps) and any(s == 'confirmed' for s in states.values())}


def attach_diagnostics(competition, related):
    checks = [notice_check(n) for n in related]
    current_ids = competition.get('currentEditionIds', [])
    current_checks = [n for n in checks if n['editionId'] in current_ids]
    for group in competition.get('editions', []):
        group['diagnostics'] = diagnose_group(group, [n for n in checks if n['editionId'] == group['id']])
        group['fieldStates'].update({k: v for k, v in group['diagnostics']['fieldStates'].items() if k != 'deadline'})
        group['registration']['deadlineState'] = group['diagnostics']['fieldStates']['deadline']
        if not any(s['kind'] in DEADLINES for s in group['timeline']) and not group.get('changes'):
            group['registration']['status'] = group['diagnostics']['fieldStates']['deadline']
    reasons = []
    if not related:
        primary = 'no_notices'
        reasons = [primary]
    elif not current_ids:
        primary = 'no_current_notice'
        reasons = [primary]
        if any(n['identityState'] == 'needs_review' for n in checks):
            reasons.append('identity_unknown')
        if any(n['identityConflicts'] for n in checks):
            reasons.append('identity_conflict')
    else:
        groups = [g['diagnostics'] for g in competition['editions'] if g['id'] in current_ids]
        reasons = list(dict.fromkeys(s for g in groups for s in g['reasons']))
        primary = next((s for s in ('conflict', 'fetch_failed', 'body_pending', 'body_empty',
                                   'fields_pending', 'resource_failed', 'resource_pending', 'needs_review', 'not_extracted') if s in reasons), 'confirmed')
    competition['diagnostics'] = {'primary': primary, 'reasons': reasons,
        'hasRelatedNotice': bool(related), 'hasCurrentNotice': bool(current_ids),
        'noticeCount': len(checks), 'currentNoticeCount': len(current_checks),
        'noticeCounts': dict(Counter(n['state'] for n in checks)),
        'currentNoticeCounts': dict(Counter(n['state'] for n in current_checks)),
        'notices': checks}
    if not current_ids:
        competition['registration']['status'] = primary
        competition['registration']['deadlineState'] = primary
    elif competition['registration']['status'] in {'needs_review', 'not_mentioned'}:
        statuses = {g['registration']['status'] for g in competition['editions'] if g['id'] in current_ids}
        if 'needs_review' not in statuses and 'conflict' not in statuses:
            gap = next((s for s in ('fetch_failed', 'body_pending', 'body_empty', 'fields_pending', 'resource_failed', 'resource_pending', 'not_extracted')
                        if s in statuses), None)
            if gap:
                competition['registration']['status'] = gap
                competition['registration']['deadlineState'] = gap


def coverage(checks):
    counts = Counter(n['fetchStatus'] for n in checks)
    success = counts['success']
    return {'total': len(checks), 'success': success, 'failed': counts['failed'],
            'empty': counts['empty'], 'pending': counts['pending'],
            'withFields': sum(n['hasFields'] for n in checks),
            'successRate': round(success / len(checks), 4) if checks else None}


def report(competitions, year):
    diagnostics = [c['diagnostics'] for c in competitions]
    all_checks = {n['url']: n for d in diagnostics for n in d['notices']}
    current_checks = {n['url']: n for c in competitions for n in c['diagnostics']['notices']
                      if n['editionId'] in c.get('currentEditionIds', [])}
    primary_counts = Counter(d['primary'] for d in diagnostics)
    reason_counts = Counter(s for d in diagnostics for s in d['reasons'])
    return {'schemaVersion': 1, 'year': year, 'total': len(competitions), 'labels': LABELS,
            'primaryCounts': {s: primary_counts[s] for s in LABELS if s != 'identity_unknown'},
            'reasonCounts': {s: reason_counts[s] for s in LABELS if s != 'confirmed'},
            'relatedCoverage': coverage(list(all_checks.values())),
            'currentCoverage': coverage(list(current_checks.values())),
            'competitions': [{'name': c['name'], **c['diagnostics'],
                             'editions': [{'id': g['id'], 'label': g['label'],
                                           'current': g['id'] in c.get('currentEditionIds', []),
                                           'fieldStates': g['diagnostics']['fieldStates'],
                                           'reasons': g['diagnostics']['reasons']}
                                          for g in c.get('editions', [])]} for c in competitions]}
