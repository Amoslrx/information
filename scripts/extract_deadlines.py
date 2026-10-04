"""Only explicit, evidenced registration events qualify as page deadlines.

Default execution is offline. Old score-only dates are retained as unverified
history, never projected as registration deadlines.
"""
import argparse
import json
from pathlib import Path
from extract_notice_fields import atomic_json
from notice_fields import VERSION, rules, safe_deadline
from notice_evidence import enrich, load_resources

ROOT = Path(__file__).resolve().parent.parent
SEED = ROOT / 'data' / 'seed'
NOTICES = str(SEED / 'notices.json')
BODIES = str(SEED / 'notice_bodies.json')
DST = str(SEED / 'deadlines.json')
MIN_SCORE = 4  # Kept for compatibility; eligibility now depends on evidence and type.
BODIES_CACHE = {}


def extract(title, date, body):
    event = safe_deadline(rules({'url': '', 'title': title, 'date': date, 'body': body}))
    return (event['value'], MIN_SCORE) if event else (None, 0)


def load_bodies():
    if not Path(BODIES).exists():
        return {}
    with open(BODIES, encoding='utf-8') as f:
        resources = load_resources(Path(BODIES).parent)
        return {r['url']: enrich(r, resources) for r in json.load(f).get('items', [])}


def work(notice, fields=None):
    record = BODIES_CACHE.get(notice['url']) or {}
    if record.get('status') != 'success':
        return {'url': notice['url'], 'deadline': None, 'score': 0,
                'error': record.get('error') or 'body_unavailable', 'schemaVersion': VERSION}
    record = {**notice, **record}
    fields = fields if fields is not None else rules(record)
    event = safe_deadline(fields)
    return {'url': notice['url'], 'title': record.get('title', ''), 'noticeDate': record.get('date', ''),
            'contentHash': record.get('contentHash', ''), 'schemaVersion': VERSION,
            'deadline': event['value'] if event else None, 'score': MIN_SCORE if event else 0,
            'deadlineEvent': event, 'timeline': fields['timeline'], 'bodyLen': len(record.get('body', '')),
            'snippet': record.get('excerpt') or record.get('body', '')[:180]}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--fetch-missing', action='store_true', help='显式联网补抓正文，默认只读取缓存')
    args = ap.parse_args(argv)
    with open(NOTICES, encoding='utf-8') as f:
        notices = json.load(f)['items']
    BODIES_CACHE.clear()
    BODIES_CACHE.update(load_bodies())
    if args.fetch_missing:
        from crawl_notice_bodies import main as crawl
        crawl([])
        BODIES_CACHE.update(load_bodies())
    structured = {}
    if (SEED / 'notice_fields.json').exists():
        with (SEED / 'notice_fields.json').open(encoding='utf-8') as f:
            structured = {r['url']: r for r in json.load(f)['items']}
    old = {}
    if Path(DST).exists():
        with open(DST, encoding='utf-8') as f:
            old = {r['url']: r for r in json.load(f).get('items', [])}
    by_url = {n['url']: n for n in notices}
    for url, record in BODIES_CACHE.items():
        by_url.setdefault(url, record)
    result = []
    for url in sorted(set(old) | set(BODIES_CACHE)):
        fields = structured.get(url, {})
        fields = fields.get('fields') if fields.get('contentHash') == BODIES_CACHE.get(url, {}).get('contentHash') else None
        projected = work(by_url.get(url, {'url': url}), fields)
        if url not in BODIES_CACHE and (old[url].get('deadline') or old[url].get('legacyCandidate')):
            projected['legacyCandidate'] = old[url].get('deadline') or old[url].get('legacyCandidate')
            projected['verification'] = 'needs_review'
        result.append(projected)
    good = sum(bool(r.get('deadline')) for r in result)
    atomic_json(DST, {'schema_version': VERSION, 'source': '统一正文证据', 'method': 'typed-registration-events',
                      'min_score': MIN_SCORE, 'count': len(result), 'with_deadline': good, 'items': result})
    print('时间节点：%d 条通知；可确定的报名截止：%d；历史无证据日期已隔离' % (len(result), good))


if __name__ == '__main__':
    main()
