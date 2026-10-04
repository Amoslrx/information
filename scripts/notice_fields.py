"""Evidence-bearing notice fields. Empty values are never filled from guesses."""
import copy
import datetime as dt
import hashlib
import json
import re
from urllib.parse import urlsplit
from pathlib import Path

VERSION = 2
KINDS = {'registration_start', 'registration_deadline', 'campus_deadline',
         'official_deadline', 'submission', 'competition', 'other'}
COLLECTIONS = ('competitionNames', 'editions', 'audiences', 'tracks', 'registrationMethods',
               'registrationLinks', 'requiredMaterials', 'timeline', 'contacts', 'groups')
PHONE = re.compile(r'(?<!\d)(?:\+?86[- ]?)?1\d{10}(?!\d)|(?<!\d)0\d{2,3}[- ]?\d{7,8}(?!\d)')
EMAIL = re.compile(r'[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}')
# A single combined pattern avoids counting the month/day inside an explicit year twice.
DATE = re.compile(r'(?<!\d)(?:(?P<year>20\d{2})\s*[年./-]\s*)?'
                  r'(?P<month>\d{1,2})\s*(?(year)[月./-]|[月./])\s*(?P<day>\d{1,2})(?![\d月])\s*日?')
CLOCK = re.compile(r'^\s*(?:北京时间\s*)?(?:[（(][^）)]*[）)]\s*)?(?P<period>上午|下午|晚上|晚间|中午|凌晨|早上|傍晚)?\s*'
                   r'(?P<hour>\d{1,2})\s*(?:[:：]\s*(?P<minute>\d{2})|[时点]\s*(?:(?P<cnminute>\d{1,2})\s*分?|(?P<half>半))?)')


def empty(record):
    return {'schemaVersion': VERSION, 'contentHash': record.get('contentHash', ''),
            'sourceUrl': record['url'], **{key: [] for key in COLLECTIONS},
            'model': {'status': 'disabled', 'error': ''}}


def fact(value, raw, record, location, method='rule', flags=(), track=None):
    return {'value': value, 'raw': raw, 'sourceUrl': record['url'], 'location': location,
            'method': method, 'verification': 'needs_review' if flags else 'source_matched',
            'flags': list(flags), 'trackId': track}


def sources(record):
    """Exact substrings and offsets into cached body; punctuation retains local semantics."""
    body = record.get('body', '')
    for match in re.finditer(r'[^\n。；;]+[。；;]?', body):
        raw = match.group().strip()
        if raw:
            start = match.start() + len(match.group()) - len(match.group().lstrip())
            yield raw, {'type': 'body', 'start': start, 'end': start + len(raw)}


def date_kind(raw, before, after):
    """Classify locally. Submission language takes priority over adjacent registration text."""
    prefix = re.split(r'[，,。；;]', before)[-1]
    suffix = re.split(r'[，,。；;]', after)[0]
    local = prefix + suffix
    if re.search(r'学籍|入学|选课|报到|学费', local):
        return 'other'
    if re.search(r'作品|论文|材料|PPT|报名表|报送|提交|上传|递交', local, re.I):
        return 'submission'
    if re.search(r'报名|注册|登记|申报', local):
        if re.search(r'开始|启动|开放|起|自|从', prefix) and not re.search(r'截止|截至|结束', prefix):
            return 'registration_start'
        if re.search(r'截止|截至|结束|最迟|之前|日前|前完成|前报名', local):
            if re.search(r'校内|本校|学校', local):
                return 'campus_deadline'
            if re.search(r'官方|组委会|全国|大赛官网', local):
                return 'official_deadline'
            return 'registration_deadline'
    if re.search(r'比赛|竞赛|初赛|复赛|决赛|国赛|省赛|选拔赛', local):
        return 'competition'
    return 'other'


def time_value(after):
    match = CLOCK.match(after)
    if not match:
        return None, []
    hour = int(match['hour'])
    minute = int(match['minute'] or match['cnminute'] or (30 if match['half'] else 0))
    period = match['period']
    if period in {'下午', '晚上', '晚间', '傍晚'} and hour < 12:
        hour += 12
    if period == '中午' and hour < 11:
        hour += 12
    if period in {'上午', '凌晨'} and hour == 12:
        hour = 0
    if hour == 24 and minute == 0:
        return '24:00', ['end_of_day']
    if hour > 23 or minute > 59:
        return None, ['invalid_time']
    return '%02d:%02d' % (hour, minute), []


def extract_dates(raw, record, location, track=None):
    out = []
    matches = list(DATE.finditer(raw))
    for i, match in enumerate(matches):
        before, after = raw[:match.start()], raw[match.end():]
        kind = date_kind(raw, before, after)
        if kind == 'other' and i and re.search(r'延期|延至|延长|推迟|调整|变更', re.split(r'[，,]', before)[-1]):
            kind = out[-1]['kind']
        flags = []
        year = int(match['year']) if match['year'] else None
        if year is None:
            flags.append('missing_year')
            try:
                year = dt.date.fromisoformat(record.get('date', '')).year
            except ValueError:
                year = None
        month, day = int(match['month']), int(match['day'])
        value = None
        if year:
            # Only an explicit next-year expression or a crossing range permits a candidate next year.
            if not match['year'] and re.search(r'次年|翌年|明年', before):
                year += 1
                flags.append('cross_year')
            if not match['year'] and i and out[-1]['value']:
                previous = dt.date.fromisoformat(out[-1]['value'])
                bridge = raw[matches[i-1].end():match.start()]
                if re.fullmatch(r'\s*(?:至|到|—|–|-|~|～)\s*', bridge):
                    year = previous.year + (month < previous.month)
                    if year != previous.year:
                        flags.append('cross_year')
            try:
                value = dt.date(year, month, day).isoformat()
            except ValueError:
                flags.append('invalid_date')
        else:
            flags.append('unknown_year')
        # Compare instead of silently assigning the next calendar year.
        if value and value < record.get('date', ''):
            flags.append('before_publication')
            if not match['year']:
                flags.append('possible_cross_year')
        clock, clock_flags = time_value(after)
        flags.extend(clock_flags)
        if 'end_of_day' in flags:
            flags.remove('end_of_day')  # Valid 24:00 is represented explicitly, not discarded.
        if re.search(r'延期|延长|推迟|调整|延至|变更', raw):
            flags.append('postponed')
        if re.search(r'前后|暂定|待定|预计|另行通知|以.*通知为准', raw):
            flags.append('approximate')
        event = fact(value, raw, record, location, flags=flags, track=track)
        event.update(kind=kind, time=clock, timezone='Asia/Shanghai', dateRaw=match.group().strip(),
                     endDate=None, superseded=False)
        # Range endpoints inherit the event type; preserve partial-day endpoints too.
        if i and re.fullmatch(r'\s*(?:至|到|—|–|-|~|～)\s*', raw[matches[i-1].end():match.start()]):
            event['kind'] = out[-1]['kind']
            out[-1]['endDate'] = value
            out[-1]['flags'] = list(dict.fromkeys(out[-1]['flags'] + ['date_range']))
            out[-1]['verification'] = 'needs_review'
            event['flags'].append('range_endpoint')
            event['verification'] = 'needs_review'
        tail = re.match(r'\s*(?:至|到|—|–|-|~|～)\s*(\d{1,2})日', after)
        if tail and value:
            try:
                event['endDate'] = dt.date(year, month, int(tail[1])).isoformat()
            except ValueError:
                event['flags'].append('invalid_date')
            event['flags'].append('date_range')
            event['verification'] = 'needs_review'
        out.append(event)
    # Preserve month-only schedules as evidence without inventing a day.
    month_range = re.compile(r'(20\d{2})[年./-](\d{1,2})月?\s*(?:至|到|—|–|-|~|～)\s*'
                             r'(?:(20\d{2})[年./-])?(\d{1,2})月')
    range_spans = []
    for match in month_range.finditer(raw):
        flags = ['month_precision']
        start_year = int(match[1])
        end_year = int(match[3]) if match[3] else start_year + (int(match[4]) < int(match[2]))
        if end_year != start_year:
            flags.append('cross_year')
        if not (1 <= int(match[2]) <= 12 and 1 <= int(match[4]) <= 12):
            flags.append('invalid_date')
        event = fact(None, raw, record, location, flags=flags, track=track)
        event.update(kind=date_kind(raw, raw[:match.start()], raw[match.end():]), time=None, timezone='Asia/Shanghai',
                     dateRaw=match.group(), endDate=None, superseded=False)
        out.append(event)
        range_spans.append(match.span())
    for match in re.finditer(r'(20\d{2})[年./-](\d{1,2})月(?!\s*\d)', raw):
        if any(start <= match.start() < end for start, end in range_spans):
            continue
        flags = ['month_precision'] + ([] if 1 <= int(match[2]) <= 12 else ['invalid_date'])
        event = fact(None, raw, record, location, flags=flags, track=track)
        event.update(kind=date_kind(raw, raw[:match.start()], raw[match.end():]), time=None, timezone='Asia/Shanghai',
                     dateRaw=match.group(), endDate=None, superseded=False)
        out.append(event)
    return out


def mark_conflicts(events):
    for event in events:
        if event['method'] == 'model' and event['verification'] != 'source_matched':
            continue
        if event['kind'] not in {'registration_deadline', 'campus_deadline', 'official_deadline'}:
            continue
        related = [e for e in events if (e['kind'], e['trackId']) == (event['kind'], event['trackId']) and e['value'] and
                   not (e['method'] == 'model' and e['verification'] != 'source_matched')]
        if len({(e['value'], e['time']) for e in related}) > 1:
            for e in related:
                if 'conflict' not in e['flags']:
                    e['flags'].append('conflict')
                e['verification'] = 'needs_review'
                # Keep both statements as evidence, never pick the latest date by default.
                revision_prefix = event['raw'][:event['raw'].find(event['dateRaw'])]
                if 'postponed' in event['flags'] and re.search(r'延期|延长|推迟|调整|延至|变更', revision_prefix) and e['value'] != event['value']:
                    e['superseded'] = True


def _text_rules(record):
    result = empty(record)
    title = record.get('title', '')
    title_loc = {'type': 'title', 'start': 0, 'end': len(title)}
    # Extract original names, without replacing them with catalogue matches.
    for match in re.finditer(r'(?:第[一二三四五六七八九十百零〇\d]+届)?[^，。；：“”\n]{2,80}(?:竞赛|大赛|挑战赛|世界杯)', title):
        name = re.sub(r'^(?:关于|组织|举办|开展|参加)+', '', match.group()).strip()
        result['competitionNames'].append(fact(name, title, record, title_loc))
    for match in re.finditer(r'第[一二三四五六七八九十百零〇\d]+届', title):
        result['editions'].append(fact(match.group(), title, record, title_loc))
    title_tracks = []
    for pattern in (r'([A-Za-z][A-Za-z0-9]*[\u4e00-\u9fff]{0,12}赛道)',
                    r'[“「《]([^“”「」《》，。；]{1,35}赛道)[”」》]',
                    r'[（(]([^）)，。；]{1,35}赛道)[）)]',
                    r'(?:竞赛|大赛)([^，。；\s—–：:（(“”「」《》]{2,30}(?:赛道|专题赛))',
                    r'(?:—|–|：|:)([^，。；：:]{1,25}赛道)'):
        for match in re.finditer(pattern, title):
            name = match[1].strip()
            if name in title_tracks:
                continue
            title_tracks.append(name)
            track = fact(name, title, record, title_loc)
            track['id'] = 'track-' + hashlib.sha256(name.encode()).hexdigest()[:10]
            result['tracks'].append(track)
    active = result['tracks'][0]['id'] if len(title_tracks) == 1 else None
    pending_contact = None
    body_sources = list(sources(record))
    link_contexts = {}
    scopes = {}
    audience_section = False
    method_section = False
    for raw, loc in body_sources:
        section_heading = bool(re.match(r'^[一二三四五六七八九十\d]+[、.．]\s*[^，。；]{2,18}$', raw))
        if section_heading:
            audience_section = bool(re.search(r'参赛对象|报名对象|参赛资格', raw))
            method_section = bool(re.search(r'报名方式|报名方法|报名流程', raw))
        header = re.fullmatch(r'(?:[一二三四五六七八九十\d]+[、.．)]\s*)?([^，。；：:]{1,35}(?:赛道|组别|赛项))[：:]?', raw)
        if header and not header[1].startswith(('各', '所有', '多个', '比赛')):
            active = 'track-' + hashlib.sha256(header[1].encode()).hexdigest()[:10]
            t = fact(header[1], raw, record, loc)
            t['id'] = active
            if not any(existing['id'] == active for existing in result['tracks']):
                result['tracks'].append(t)
            pending_contact = None
        elif re.match(r'^(?:[一二三四五六七八九十]+[、.．])?(?:共同|通用|其他事项|注意事项|附件)', raw):
            active, pending_contact = None, None
        scopes.setdefault(raw, []).append(active)
        for match in re.finditer(r'第[一二三四五六七八九十百零〇\d]+届', raw):
            field = fact(match.group(), raw, record, loc, track=active)
            if not any(x['value'] == field['value'] for x in result['editions']):
                result['editions'].append(field)
        if not section_heading and (audience_section or re.search(r'参赛对象|报名对象|面向.*(?:学生|本科|研究生)|(?:本科生|研究生|少年班|大一|大二|大三).*可.*(?:报名|参赛)', raw)):
            result['audiences'].append(fact(raw, raw, record, loc, track=active))
        if not section_heading and (method_section or re.search(r'报名方式|报名方法|通过.*报名|填写.*报名|报名.*(?:网站|平台|邮件|提交)|扫描.*报名', raw)) and not DATE.search(raw):
            result['registrationMethods'].append(fact(raw, raw, record, loc, track=active))
        if re.search(r'(?:材料|提交|报送|上传|递交).*(?:报名表|申请表|作品|论文|PPT|身份证|证明|承诺书|材料)', raw, re.I):
            result['requiredMaterials'].append(fact(raw, raw, record, loc, track=active))
        result['timeline'].extend(extract_dates(raw, record, loc, active))
        # Keep each named person and their immediately adjacent details in one record.
        named_pattern = r'(?:联系人|联络人|负责人)[：: \t]*([^，,。；;：:（(、\d\s]{2,25})'
        if PHONE.search(raw) or EMAIL.search(raw) or re.fullmatch(r'[\u4e00-\u9fff]{2,6}老师', raw):
            named_pattern += r'|([\u4e00-\u9fff]{1,6}老师)'
            named_pattern += r'|(?:^|[，,；; \t])((?!电话|手机|联系)[\u4e00-\u9fff]{2,4})(?=[：: \t]*(?:电话[：: \t]*)?(?:1\d{10}|0\d{2,3}[- ]?\d{7,8}))'
        named = list(re.finditer(named_pattern, raw))
        joint_names = re.search(r'(?:联系人|联络人)[：: \t]*([\u4e00-\u9fff]{2,6})[、和及与]([\u4e00-\u9fff]{2,6})(?=[，,：: \t]|$)', raw)
        if joint_names:
            for name in joint_names.groups():
                result['contacts'].append({'name': fact(name, raw, record, loc, track=active),
                                           'phones': [], 'emails': [], 'qq': [], 'trackId': active})
            unassigned = {'name': None, 'phones': [], 'emails': [], 'qq': [], 'trackId': active}
            unassigned['phones'] = [fact(m.group(), raw, record, loc, flags=['relationship_ambiguous'], track=active) for m in PHONE.finditer(raw)]
            unassigned['emails'] = [fact(m.group(), raw, record, loc, flags=['relationship_ambiguous'], track=active) for m in EMAIL.finditer(raw)]
            if unassigned['phones'] or unassigned['emails']:
                result['contacts'].append(unassigned)
            pending_contact = None
            named = []
        if named:
            pending_contact = None
            for index, match in enumerate(named):
                part = raw[match.start():named[index+1].start() if index+1 < len(named) else len(raw)]
                name = next((g for g in match.groups() if g), '')
                name = re.split(r'学院|学部|中心|办公室', name)[-1]
                if not name:
                    continue
                if name in {'联系方式', '邮箱', '电话', '报名', '竞赛'}:
                    continue
                name_field = fact(name, raw, record, loc, track=active)
                person = {'name': name_field, 'phones': [], 'emails': [], 'qq': [], 'trackId': active}
                person['phones'] = [fact(m.group(), raw, record, loc, track=active) for m in PHONE.finditer(part)]
                person['emails'] = [fact(m.group(), raw, record, loc, track=active) for m in EMAIL.finditer(part)]
                result['contacts'].append(person)
                pending_contact = person
        elif re.search(r'^(?:联系)?(?:电话|手机|邮箱|电子邮箱|E-mail|Email|QQ)[：: \t]', raw, re.I):
            if pending_contact is None or pending_contact['trackId'] != active:
                pending_contact = {'name': None, 'phones': [], 'emails': [], 'qq': [], 'trackId': active}
                result['contacts'].append(pending_contact)
            pending_contact['phones'].extend(fact(m.group(), raw, record, loc, track=active) for m in PHONE.finditer(raw))
            pending_contact['emails'].extend(fact(m.group(), raw, record, loc, track=active) for m in EMAIL.finditer(raw))
        elif re.search(r'联系人\s*$|联络人\s*$', raw):
            pending_contact = None
        elif not re.search(r'群|电话|邮箱|联系人', raw):
            pending_contact = None
        group_match = re.search(r'(?:QQ\s*(?:交流|联络|咨询|报名|竞赛)?群|(?:交流|联络|竞赛)QQ群)[号：: \t]*(\d{5,12})', raw, re.I)
        if group_match:
            result['groups'].append({'kind': 'qq', 'number': fact(group_match[1], raw, record, loc, track=active),
                                     'images': [], 'trackId': active})
        else:
            qq_match = re.search(r'QQ[号：: \t]*(\d{5,12})', raw, re.I)
            if qq_match:
                target = pending_contact
                if target is None:
                    target = {'name': None, 'phones': [], 'emails': [], 'qq': [], 'trackId': active}
                    result['contacts'].append(target)
                target['qq'].append(fact(qq_match[1], raw, record, loc, track=active))
        for match in re.finditer(r'https?://[^\s，。；;）)<>]+|www\.[a-zA-Z0-9.-]+(?:/[^\s，。；;）)<>]*)?', raw):
            link_contexts.setdefault(match.group(), []).append((raw, loc, active))
    # Both typed plain-text URLs and HTML anchors are potential entry points; a homepage alone is not a registration entry.
    candidates = list(record.get('links') or []) + [{'url': u, 'text': u} for u in link_contexts]
    seen = set()
    for link in candidates:
        url = link['url']
        contexts = link_contexts.get(url, [])
        context = contexts[0] if contexts else None
        scope_flags = ['scope_ambiguous'] if len({c[2] for c in contexts}) > 1 else []
        if not context:
            context = next(((raw, loc, None) for raw, loc in body_sources if link.get('text') and link['text'] in raw), None)
        if context:
            raw, loc, track = context
            nearby = raw
            # Only a bare URL inherits an immediately preceding instruction.
            if raw.rstrip('。') == url and body_sources.index((raw, loc)):
                nearby += ' ' + body_sources[body_sources.index((raw, loc))-1][0]
        else:
            raw, loc, track, nearby = link.get('text') or url, {'type': 'link', 'url': url}, None, link.get('text', '')
        if not re.search(r'报名|登记|注册|填.*信息|form|signup|register|enroll', nearby + ' ' + url, re.I):
            continue
        full = url if url.startswith(('https://', 'http://')) else 'https://' + url
        if full in seen or not urlsplit(full).hostname:
            continue
        seen.add(full)
        result['registrationLinks'].append(fact(full, raw, record, loc, track=None if scope_flags else track, flags=scope_flags))
    # Image evidence comes from a scoped image caption/context; no OCR guesses.
    for image in record.get('images') or []:
        context = image.get('context') or image.get('alt') or ''
        if not re.search(r'(?:交流|联络|竞赛|QQ|微信).*群|群.*二维码', context, re.I):
            continue
        scoped_tracks = set(scopes.get(context, []))
        track = next(iter(scoped_tracks)) if len(scoped_tracks) == 1 else None
        group = {'kind': 'wechat' if '微信' in context else 'qq' if 'QQ' in context.upper() else 'unknown',
                 'number': None, 'trackId': track, 'images': [fact(image['url'], context, record,
                    {'type': 'image', 'url': image['url']}, flags=['image_requires_review'] +
                    (['scope_ambiguous'] if len(scoped_tracks) > 1 else []), track=track)]}
        result['groups'].append(group)
    mark_conflicts(result['timeline'])
    return result


def rules(record):
    result = _text_rules(record)
    for resource in record.get('resources', []):
        if resource.get('status') not in {'success', 'partial'}:
            continue
        for chunk in resource.get('chunks', []):
            if not chunk.get('text') or chunk.get('method') not in {'attachment', 'ocr', 'qr'}:
                continue
            subrecord = {'url': resource['url'], 'title': '', 'date': record.get('date', ''), 'body': chunk['text']}
            extracted = _text_rules(subrecord)
            # A QR payload is evidence of its decoded contents, not proof of the purpose of its URL.
            if chunk['method'] == 'qr' and re.fullmatch(r'https?://[^\s]+', chunk['text']):
                extracted['registrationLinks'].append(fact(chunk['text'], chunk['text'], subrecord,
                    {'type': 'body', 'start': 0, 'end': len(chunk['text'])}, flags=['qr_purpose_unverified']))
            for field in all_facts(extracted):
                old = field['location']
                field['location'] = {'type': 'resource', 'resourceId': resource['id'], 'chunkId': chunk['id'],
                                     'page': chunk.get('page'), 'start': old.get('start', 0),
                                     'end': old.get('end', len(chunk['text']))}
                field['method'] = chunk['method']
                if chunk['method'] in {'ocr', 'qr'}:
                    field['flags'] = list(dict.fromkeys(field['flags'] + [chunk['method'] + '_requires_review']))
                    field['verification'] = 'needs_review'
            for collection in COLLECTIONS:
                result[collection].extend(extracted[collection])
    mark_conflicts(result['timeline'])
    return result


def safe_deadline(fields):
    eligible = [e for e in fields.get('timeline', []) if e['kind'] in
                {'campus_deadline', 'official_deadline', 'registration_deadline'} and e.get('value') and
                e.get('verification') == 'source_matched' and not e.get('flags') and not e.get('superseded')]
    # A notice with multiple tracks/deadlines cannot be collapsed into one confident date.
    if len({(e['value'], e.get('time'), e.get('trackId')) for e in eligible}) != 1:
        return None
    return eligible[0]


def all_facts(value):
    if isinstance(value, dict):
        if 'verification' in value and 'raw' in value:
            yield value
        else:
            for child in value.values():
                yield from all_facts(child)
    elif isinstance(value, list):
        for child in value:
            yield from all_facts(child)


def check_evidence(field, record):
    if not isinstance(field.get('raw'), str) or not field['raw']:
        raise ValueError('invalid source/empty evidence')
    location = field.get('location', {})
    kind = location.get('type')
    if kind == 'resource':
        resource = next((r for r in record.get('resources', []) if r.get('id') == location.get('resourceId') and
                         r.get('url') == field.get('sourceUrl') and r.get('status') in {'success', 'partial'}), None)
        chunk = next((c for c in resource.get('chunks', []) if c.get('id') == location.get('chunkId')), None) if resource else None
        start, end = location.get('start'), location.get('end')
        if not chunk or chunk.get('page') != location.get('page') or type(start) is not int or type(end) is not int or not (
                0 <= start < end <= len(chunk['text'])) or chunk['text'][start:end] != field['raw']:
            raise ValueError('resource evidence mismatch')
        return
    if field.get('sourceUrl') != record['url']:
        raise ValueError('invalid source URL')
    if kind in {'body', 'title'}:
        source = record.get(kind, '')
        start, end = location.get('start'), location.get('end')
        if type(start) is not int or type(end) is not int or not (0 <= start < end <= len(source)) or source[start:end] != field['raw']:
            raise ValueError('evidence offset/quote mismatch')
    elif kind == 'link':
        if not any(l['url'] == location.get('url') and field['raw'] in {l['url'], l.get('text')} for l in record.get('links', [])):
            raise ValueError('link evidence mismatch')
    elif kind == 'image':
        if not any(i['url'] == location.get('url') and field['raw'] in {i.get('alt'), i.get('context')} for i in record.get('images', [])):
            raise ValueError('image evidence mismatch')
    else:
        raise ValueError('unsupported evidence location')


def validate_model(candidate, record):
    """Validate structure, exact evidence and semantics. Model claims cannot self-verify."""
    validate_shape(candidate)
    if not isinstance(candidate, dict) or set(candidate) != set(empty(record)):
        raise ValueError('invalid top-level fields')
    if candidate['schemaVersion'] != VERSION or candidate['sourceUrl'] != record['url'] or candidate['contentHash'] != record.get('contentHash', ''):
        raise ValueError('schema/source/hash mismatch')
    if any(not isinstance(candidate[k], list) for k in COLLECTIONS):
        raise ValueError('collections must be arrays')
    result = copy.deepcopy(candidate)
    track_ids = {t.get('id') for t in result['tracks'] if isinstance(t, dict)}
    rule = rules(record)
    field_collections = {id(f): key for key in COLLECTIONS for f in all_facts(result[key])}
    allowed_keys = set(fact('', '', record, {}))
    for key in COLLECTIONS:
        for item in result[key]:
            if not isinstance(item, dict):
                raise ValueError('collection item must be object')
            if key == 'contacts':
                if set(item) != {'name', 'phones', 'emails', 'qq', 'trackId'} or any(not isinstance(item[k], list) for k in ('phones', 'emails', 'qq')):
                    raise ValueError('invalid contact shape')
            elif key == 'groups':
                if set(item) != {'kind', 'number', 'images', 'trackId'} or item['kind'] not in {'qq', 'wechat', 'unknown'} or not isinstance(item['images'], list):
                    raise ValueError('invalid group shape')
            elif key == 'timeline':
                if set(item) != allowed_keys | {'kind', 'time', 'timezone', 'dateRaw', 'endDate', 'superseded'} or item['kind'] not in KINDS:
                    raise ValueError('invalid event shape')
            elif set(item) != allowed_keys | ({'id'} if key == 'tracks' else set()):
                raise ValueError('invalid field shape')
    for field in all_facts(result):
        check_evidence(field, record)
        if field.get('trackId') is not None and field['trackId'] not in track_ids:
            raise ValueError('unknown track')
        if not isinstance(field.get('flags'), list) or any(not isinstance(f, str) for f in field['flags']):
            raise ValueError('invalid flags')
        value = field.get('value')
        if value is not None and not isinstance(value, str):
            raise ValueError('field value must be string or null')
        # Matching a quote alone does not prove relationships, date type, or normalization.
        rule_facts = list(all_facts(rule[field_collections[id(field)]]))
        matches = [r for r in rule_facts if r['value'] == value and r['raw'] == field['raw'] and
                   r['location'] == field['location'] and r.get('kind') == field.get('kind') and r.get('trackId') == field.get('trackId')]
        if 'kind' in field:
            matches = [r for r in matches if r.get('time') == field.get('time') and r.get('endDate') == field.get('endDate')
                       and r.get('dateRaw') == field.get('dateRaw')]
            if value:
                dt.date.fromisoformat(value)
        elif value and value not in field['raw'] and not matches:
            raise ValueError('value unsupported by quote')
        field['method'] = matches[0]['method'] if matches and field['method'] == matches[0]['method'] else 'model'
        field['verification'] = 'source_matched' if matches and matches[0]['verification'] == 'source_matched' else 'needs_review'
        field['flags'] = list(dict.fromkeys(field['flags'] + (matches[0]['flags'] if matches else ['model_requires_review'])))
        if field['flags']:
            field['verification'] = 'needs_review'
    # Name/phone/email pairing and group/track assignment must match an entire rule object.
    for key in ('contacts', 'groups'):
        for item in result[key]:
            def signature(obj):
                if isinstance(obj, dict):
                    return {k: signature(v) for k, v in obj.items() if k not in {'method', 'verification', 'flags'}}
                return [signature(v) for v in obj] if isinstance(obj, list) else obj
            if not any(signature(item) == signature(r) for r in rule[key]):
                for field in all_facts(item):
                    field['verification'] = 'needs_review'
                    field['flags'] = list(dict.fromkeys(field['flags'] + ['relationship_requires_review']))
    mark_conflicts(result['timeline'])
    return result


def validate_shape(value):
    """Enforce our JSON Schema subset without adding a runtime dependency."""
    schema = json.loads((Path(__file__).resolve().parent.parent / 'data/schemas/notice_fields.schema.json').read_text(encoding='utf-8'))
    def check(item, spec):
        if '$ref' in spec:
            return check(item, schema['$defs'][spec['$ref'].split('/')[-1]])
        for union in ('anyOf', 'oneOf'):
            if union in spec:
                matches = 0
                for choice in spec[union]:
                    try:
                        check(item, choice)
                        matches += 1
                    except ValueError:
                        pass
                if not matches or union == 'oneOf' and matches != 1:
                    raise ValueError('schema union mismatch')
                return
        type_map = {'string': lambda: isinstance(item, str), 'null': lambda: item is None,
                    'integer': lambda: type(item) is int, 'boolean': lambda: type(item) is bool,
                    'array': lambda: isinstance(item, list), 'object': lambda: isinstance(item, dict)}
        kinds = spec.get('type')
        if kinds and not any(type_map[k]() for k in (kinds if isinstance(kinds, list) else [kinds])):
            raise ValueError('schema type mismatch')
        if 'const' in spec and (item != spec['const'] or type(item) is not type(spec['const'])) or 'enum' in spec and item not in spec['enum']:
            raise ValueError('schema enum mismatch')
        if isinstance(item, dict) and spec.get('type') == 'object':
            if any(k not in item for k in spec.get('required', [])) or spec.get('additionalProperties') is False and set(item) - set(spec['properties']):
                raise ValueError('schema missing/unknown properties')
            for k, v in item.items():
                check(v, spec['properties'][k])
        elif isinstance(item, list) and 'items' in spec:
            for child in item:
                check(child, spec['items'])
        elif isinstance(item, str) and len(item) < spec.get('minLength', 0):
            raise ValueError('schema string too short')
        elif type(item) is int and item < spec.get('minimum', item):
            raise ValueError('schema integer too small')
    check(value, schema)
