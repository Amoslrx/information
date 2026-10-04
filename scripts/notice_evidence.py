"""Join cached resource evidence without mixing assets from different notices."""
import hashlib
import json
from pathlib import Path


def load_resources(seed):
    path = Path(seed) / 'notice_resources.json'
    if not path.exists():
        return []
    with path.open(encoding='utf-8') as f:
        return json.load(f).get('items', [])


def enrich(record, resources):
    allowed = {r['url'] for r in record.get('attachments', []) + record.get('images', [])}
    joined = [r for r in resources if r.get('noticeUrl') == record['url'] and r.get('url') in allowed]
    if not joined:
        return record
    canonical = [{'id': r['id'], 'url': r['url'], 'sha256': r.get('download', {}).get('sha256'),
                  'status': r.get('status'), 'parserVersion': r.get('parserVersion'),
                  'chunks': [{k: c.get(k) for k in ('id', 'page', 'text', 'method', 'textHash')} for c in r.get('chunks', [])]}
                 for r in sorted(joined, key=lambda r: r['id'])]
    hasher = hashlib.sha256(json.dumps({'bodyHash': record.get('contentHash'), 'resources': canonical},
                                      sort_keys=True, ensure_ascii=False).encode('utf-8'))
    return {**record, 'bodyContentHash': record.get('contentHash'), 'contentHash': hasher.hexdigest(), 'resources': joined}
