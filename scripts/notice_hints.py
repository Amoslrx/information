"""Expose unread assets and exact references; never infer their unseen contents."""
import re

from notice_fields import fact, sources

ALL_FIELDS = ['deadline', 'audiences', 'registrationMethods', 'registrationLinks', 'requiredMaterials', 'contacts', 'groups']


def topics(text):
    keys = []
    for pattern, fields in [(r'时间|日期|截止|安排', ['deadline']),
                            (r'报名|注册|登记', ['registrationMethods', 'registrationLinks']),
                            (r'参赛对象|参赛资格|报名对象', ['audiences']),
                            (r'联系|咨询电话|电子邮箱', ['contacts']),
                            (r'进群|加群|交流群|QQ群|微信群|群二维码|群号', ['groups']),
                            (r'材料|报名表|申请表|承诺书', ['requiredMaterials'])]:
        if re.search(pattern, text, re.I):
            keys.extend(fields)
    return list(dict.fromkeys(keys)) or list(ALL_FIELDS)


def resource_hints(record):
    body_sources = list(sources(record))
    cues = [(raw, loc) for raw, loc in body_sources if re.search(
        r'(?:见|查看|参见|参考|详见|下载).{0,20}(?:附件|附表)|(?:附件|附表).{0,20}(?:见|安排)|'
        r'(?:扫码|扫描|识别).{0,12}(?:报名|二维码|进群|加群)|报名二维码|群二维码|二维码.*(?:报名|进群)', raw)]
    cached = {r['url']: r for r in record.get('resources', [])}
    hints = []
    for kind, assets in [('attachment', record.get('attachments', [])), ('image', record.get('images', []))]:
        for asset in assets:
            text = asset.get('text') or asset.get('context') or asset.get('alt') or ''
            evidence = None
            matching = next(((raw, loc) for raw, loc in cues if text and text in raw), None)
            if matching:
                text = matching[0]
                evidence = fact(text, text, record, matching[1])
            elif kind == 'attachment':
                evidence = fact(asset['url'], asset.get('text') or asset['url'], record, {'type': 'link', 'url': asset['url']})
            elif text:
                evidence = fact(asset['url'], text, record, {'type': 'image', 'url': asset['url']})
            resource = cached.get(asset['url'], {})
            status = resource.get('status', 'pending')
            # Empty OCR/QR or partial extraction cannot establish an absence of information.
            state = 'parsed' if status == 'success' and resource.get('chunks') else (
                'resource_failed' if status == 'failed' else 'resource_pending')
            hints.append({'kind': kind, 'url': asset['url'], 'name': asset.get('text') or asset.get('alt') or
                          ('附件原件' if kind == 'attachment' else '图片原件'),
                          'state': state, 'resourceStatus': status, 'error': resource.get('error', ''),
                          'fieldKeys': topics(text), 'evidence': evidence})
    for raw, loc in cues:
        keys = topics(raw)
        if any(h['evidence'] and h['evidence']['raw'] == raw for h in hints):
            continue
        kind = 'attachment' if re.search(r'附件|附表', raw) else 'image'
        relevant = [h for h in hints if h['kind'] == kind]
        for hint in relevant:
            hint['fieldKeys'] = list(dict.fromkeys(hint['fieldKeys'] + keys))
        hints.append({'kind': 'reference', 'url': record['url'], 'name': '原网页中的附件／二维码提示',
                      'state': 'parsed' if relevant and all(h['state'] == 'parsed' for h in relevant) else 'resource_pending',
                      'resourceStatus': 'reference', 'error': '' if relevant else 'referenced_asset_not_collected',
                      'fieldKeys': keys, 'evidence': fact(raw, raw, record, loc)})
    return hints
