"""Conservative display deduplication; original records and evidence stay intact."""
import re


def title_key(title):
    title = re.sub(r'^\s*(?:【转载】|\[转载\]|转载[:：])\s*', '', title)
    return re.sub(r'[\s“”"‘’]', '', title)


def prepare_display(notices, competitions):
    groups = {}
    for n in notices:
        a = n.get('association') or {}
        # Missing edition stays URL-isolated. Missing date cannot prove a repost.
        edition = a.get('editionId') if a.get('year') or a.get('edition') else n['url']
        fingerprint = n.get('contentHash') or n.get('fields', {}).get('contentHash')
        proof = ('body', fingerprint) if fingerprint else ('date', n.get('date') or n['url'])
        key = (n.get('competition') or n['url'], edition, a.get('resultTrack'), a.get('phase'),
               a.get('stage'), title_key(n['title']), proof)
        groups.setdefault(key, []).append(n)
    for members in groups.values():
        members.sort(key=lambda n: (not bool(n.get('fields')), n.get('date') or '9999', n['url']))
        representative = members[0]
        sources = [{'url': n['url'], 'date': n.get('date', ''), 'sourceLabel': n.get('sourceLabel') or n.get('site', '')}
                   for n in members]
        sources = list({s['url']: s for s in sources}.values())
        for n in members:
            n['displayGroupUrl'] = representative['url']
            n['repostSources'] = sources
            n['revisionLinks'] = []
    by_url = {n['url']: n for n in notices}
    for c in competitions:
        for edition in c.get('editions', []):
            for change in edition.get('changes', []):
                new = change.get('new') or {}
                url = new.get('noticeUrl')
                if url not in by_url:
                    continue
                for old in change.get('old', []):
                    old_url = old.get('noticeUrl')
                    if old_url and old_url != url:
                        link = {'url': old_url, 'title': by_url.get(old_url, {}).get('title', '原通知'),
                                'status': change['status']}
                        if link not in by_url[url]['revisionLinks']:
                            by_url[url]['revisionLinks'].append(link)
