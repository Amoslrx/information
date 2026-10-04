"""Group notice evidence by explicit edition, track and competition phase.

Publication years are never competition years. Unknown identities stay isolated.
Only an explicit, uniquely scoped revision can replace a timeline value.
"""
import copy
import datetime as dt
import hashlib
import re

from notice_fields import fact, rules

TZ = dt.timezone(dt.timedelta(hours=8))
DEADLINES = {'registration_deadline', 'campus_deadline', 'official_deadline'}
FIELDS = ('audiences', 'registrationMethods', 'registrationLinks', 'requiredMaterials', 'contacts', 'groups')
REVISION = re.compile(r'(?:延期|延长|推迟|调整|变更|延)(?:至|到|为)\s*$')
PHASES = (('campus', r'校内选拔|校内赛|校赛|校内初赛|校内决赛'),
          ('provincial', r'省赛|省级赛|省级选拔'), ('national', r'全国赛|国赛|全国总决赛'),
          ('final', r'总决赛|决赛'), ('semifinal', r'复赛'), ('preliminary', r'初赛'))


def stage_in(text, phase):
    match = re.search(r'第([一二三四五六七八九十\d]+)(阶段|轮)', text)
    if match:
        return '第%s%s' % (round_number('第' + match[1] + '届'), match[2])
    if phase in {'campus', 'national', 'provincial'}:
        match = re.search(r'初赛|复赛|决赛', text)
        if match:
            return match.group()
    return None


def identity(notice):
    title = notice['title']
    source = {'url': notice['url']}
    location = {'type': 'title', 'start': 0, 'end': len(title)}
    years = set(re.findall(r'(?<!\d)(20\d{2})(?=年|年度|赛季|\s|第|[“"（(-])', title))
    season = re.search(r'(?<!\d)(20\d{2})\s*[-—–/]\s*(20\d{2})\s*(?:年|赛季)', title)
    if season:
        years = {season[1]}
    rounds = set(re.findall(r'第[一二三四五六七八九十百零〇\d]+届', title))
    # Normalize equivalent Arabic/Chinese round numbers; retain the original label as evidence.
    normalized = {round_number(r): r for r in rounds}
    year = int(next(iter(years))) if len(years) == 1 else None
    edition = next(iter(normalized)) if len(normalized) == 1 else None
    ambiguous = len(years) > 1 or len(normalized) > 1
    phase_matches = [(key, re.search(pattern, title)) for key, pattern in PHASES]
    phase = next((key for key, match in phase_matches if match), None)
    stage = stage_in(title, phase)
    # 校赛决赛 is a campus phase, not the national final.
    phase_evidence = next((fact(match.group(), title, source, location) for key, match in phase_matches if key == phase), None)
    if re.search(r'延期|延长|推迟|延至', title):
        kind = 'postponement'
    elif re.search(r'公示|获奖|结果|名单公布|成绩公布', title):
        kind = 'results'
    elif re.search(r'补充|补报|更正|调整|变更', title):
        kind = 'supplement'
    elif re.search(r'报名|注册|申报|选拔|参赛|组织参加', title):
        kind = 'registration'
    else:
        kind = 'announcement'
    return {'year': year, 'yearEnd': int(season[2]) if season else year, 'edition': edition,
            'editionLabel': next(iter(rounds)) if edition else None, 'ambiguous': ambiguous,
            'phase': phase, 'stage': stage, 'noticeType': kind,
            'evidence': [fact(str(year), title, source, location)] if year else [],
            'editionEvidence': [fact(normalized[edition], title, source, location)] if edition else [],
            'phaseEvidence': phase_evidence,
            'typeEvidence': fact(kind, title, source, location)}


def round_number(label):
    value = label[1:-1]
    if value.isdigit():
        return int(value)
    digits = dict(zip('零〇一二三四五六七八九', [0, 0, 1, 2, 3, 4, 5, 6, 7, 8, 9]))
    total, number = 0, 0
    for char in value:
        if char in digits:
            number = digits[char]
        elif char in {'十', '百'}:
            total += (number or 1) * (10 if char == '十' else 100)
            number = 0
        else:
            return label
    return total + number


def walk_facts(value):
    if isinstance(value, dict):
        if 'verification' in value and 'raw' in value:
            yield value
        else:
            for item in value.values():
                yield from walk_facts(item)
    elif isinstance(value, list):
        for item in value:
            yield from walk_facts(item)


def field_state(values, complete=True):
    facts = list(walk_facts(values))
    if any('conflict' in f.get('flags', []) for f in facts):
        return 'conflict'
    if any(f['verification'] != 'source_matched' for f in facts):
        return 'needs_review'
    return 'confirmed' if facts else ('not_mentioned' if complete else 'needs_review')


def event_context(event):
    raw, date_raw = event['raw'], event.get('dateRaw') or ''
    position = raw.find(date_raw) if date_raw else -1
    if position < 0:
        return raw
    before = re.split(r'[，,。；;\n]', raw[:position])[-1]
    after = re.split(r'[，,。；;\n]', raw[position + len(date_raw):])[0]
    return before + date_raw + after


def phase_for(event, association):
    # Prefer an explicit local phase; otherwise retain the notice's phase.
    return next((key for key, pattern in PHASES if re.search(pattern, event_context(event))), association['phase'])


def revision_target(event):
    raw, date_raw = event.get('raw', ''), event.get('dateRaw') or ''
    position = raw.find(date_raw) if date_raw else -1
    return position >= 0 and bool(REVISION.search(raw[:position]))


def normalized_event(event, revision=False, old=False):
    result = copy.deepcopy(event)
    removable = {'postponed', 'conflict'} if revision or old else set()
    if old:
        removable |= {'before_publication'}
    remaining = [flag for flag in result.get('flags', []) if flag not in removable]
    # OCR, QR and model candidates cannot be promoted through revision resolution.
    if result.get('method') in {'ocr', 'qr', 'model'} or not result.get('value') or remaining:
        return result
    if revision or old:
        result.update(flags=remaining, verification='source_matched', superseded=False)
    return result


def entry_state(entries):
    if any('conflict' in e['event'].get('flags', []) for e in entries):
        return 'conflict'
    confirmed = [e for e in entries if e['event']['verification'] == 'source_matched']
    if len({(e['event']['value'], e['event'].get('time'), e['event'].get('endDate')) for e in confirmed}) > 1:
        return 'conflict'
    if len(confirmed) != len(entries):
        return 'needs_review'
    return 'confirmed' if entries else 'not_mentioned'


def aggregate(group, notices):
    slots, changes = {}, []
    complete = all(bool(n.get('fields')) for n in notices)
    fields = {key: [] for key in FIELDS}
    tracks = {}
    for notice in sorted(notices, key=lambda n: (n['date'], n['url'])):
        association = notice['association']
        source_fields = notice.get('fields') or {}
        for track in source_fields.get('tracks', []):
            if track['verification'] == 'source_matched':
                tracks[track['id']] = track['value']
        for key in FIELDS:
            for item in source_fields.get(key, []):
                fields[key].append({'value': copy.deepcopy(item), 'noticeUrl': notice['url'],
                                    'phase': association['phase'], 'stage': association['stage'], 'noticeType': association['noticeType']})
        events = source_fields.get('timeline', [])
        if association['noticeType'] == 'postponement' and not any(revision_target(e) for e in events):
            changes.append({'kind': None, 'trackId': association.get('resultTrack'), 'phase': association['phase'],
                            'stage': association['stage'],
                            'old': [], 'new': None, 'evidence': association['typeEvidence'], 'status': 'needs_review'})
        for event in events:
            event = copy.deepcopy(event)
            if event.get('kind') == 'other':
                continue
            phase = phase_for(event, association)
            track = event.get('trackId')
            stage = stage_in(event_context(event), phase) or association['stage']
            if len(set(re.findall(r'第[一二三四五六七八九十\d]+(?:阶段|轮)', event['raw']))) > 1:
                event['flags'] = list(dict.fromkeys(event['flags'] + ['scope_ambiguous']))
                event['verification'] = 'needs_review'
            # An unrecognized scope must not join an unrelated track from another source.
            if track and track not in tracks:
                track = notice['url'] + ':' + track
            key = (event['kind'], track, phase, stage)
            slot = slots.setdefault(key, {'kind': key[0], 'trackId': track, 'phase': phase,
                                          'stage': stage,
                                          'entries': [], 'history': [], 'changes': []})
            entry = {'event': copy.deepcopy(event), 'noticeUrl': notice['url'], 'date': notice['date']}
            explicit = revision_target(event)
            # The old value in a "由…延期至…" sentence is history, not a second current deadline.
            sibling_revision = next((e for e in events if e.get('kind') == event['kind'] and
                                     e.get('trackId') == event.get('trackId') and e['raw'] == event['raw'] and
                                     revision_target(e)), None)
            if event.get('superseded') and sibling_revision and not explicit:
                entry['event'] = normalized_event(event, old=True)
                if any(e['event']['value'] == event['value'] and e['event'].get('time') == event.get('time')
                       for e in slot['entries']):
                    slot['history'].append(entry)
                    continue
            if explicit:
                new_event = normalized_event(event, revision=True)
                previous = slot['entries']
                declared_old = [e for e in events if e.get('superseded') and e['raw'] == event['raw'] and
                                e['kind'] == event['kind'] and e.get('trackId') == event.get('trackId')]
                previous_values = {(e['event']['value'], e['event'].get('time')) for e in previous}
                declared_values = {(e['value'], e.get('time')) for e in declared_old}
                ordered = all(e['date'] < notice['date'] or
                              (e['noticeUrl'] == notice['url'] and e['event']['raw'] == event['raw']) for e in previous)
                # A stated old date must agree with the actual node being updated.
                consistent = not declared_values or previous_values == declared_values
                if previous and entry_state(previous) == 'confirmed' and len(previous_values) == 1 and ordered and consistent and new_event['verification'] == 'source_matched':
                    change = {'kind': event['kind'], 'trackId': track, 'phase': phase,
                              'stage': stage,
                              'old': copy.deepcopy(previous), 'new': copy.deepcopy(entry),
                              'evidence': copy.deepcopy(event), 'status': 'applied'}
                    slot['history'].extend(copy.deepcopy(previous))
                    slot['changes'].append(change)
                    changes.append(change)
                    entry['event'] = new_event
                    slot['entries'] = [entry]
                    continue
                entry['event']['flags'] = list(dict.fromkeys(entry['event']['flags'] + ['unresolved_revision']))
                entry['event']['verification'] = 'needs_review'
                change = {'kind': event['kind'], 'trackId': track, 'phase': phase,
                          'stage': stage,
                          'old': copy.deepcopy(previous), 'new': copy.deepcopy(entry),
                          'evidence': copy.deepcopy(event), 'status': 'needs_review'}
                slot['changes'].append(change)
                changes.append(change)
            # Deduplicate identical statements only within the exact source location.
            if not any(e == entry for e in slot['entries']):
                slot['entries'].append(entry)
    for slot in slots.values():
        slot['state'] = entry_state(slot['entries'])
    group.update(fields=fields, fieldStates={key: field_state([e['value'] for e in values], complete)
                                             for key, values in fields.items()},
                 complete=complete, tracks=tracks, timeline=list(slots.values()), changes=changes)
    return group


def event_instant(event):
    value = event.get('value')
    if not value:
        return None
    clock = event.get('time')
    try:
        date = dt.date.fromisoformat(value)
        if clock == '24:00':
            return dt.datetime.combine(date + dt.timedelta(days=1), dt.time(), TZ)
        time = dt.time.fromisoformat(clock) if clock else (dt.time() if event.get('kind') == 'registration_start' else dt.time(23, 59, 59))
        return dt.datetime.combine(date, time, TZ)
    except ValueError:
        return None


def registration_summary(group, notices, now):
    deadlines = [s for s in group['timeline'] if s['kind'] in DEADLINES]
    for slot in deadlines:
        if any(change['status'] == 'needs_review' and change['kind'] is None and
               (change['phase'], change['trackId'], change['stage']) == (slot['phase'], slot['trackId'], slot['stage']) for change in group['changes']):
            slot['state'] = 'needs_review'
    state = 'conflict' if any(s['state'] == 'conflict' for s in deadlines) else (
        'needs_review' if any(s['state'] == 'needs_review' for s in deadlines) else
        'confirmed' if deadlines else 'not_mentioned' if group['complete'] else 'needs_review')
    if not deadlines and any(c['status'] == 'needs_review' for c in group['changes']):
        state = 'needs_review'
    candidates = []
    for slot in deadlines:
        slot['registrationStatus'] = slot['state']
        if slot['state'] != 'confirmed':
            continue
        entry = slot['entries'][-1]
        instant = event_instant(entry['event'])
        result_notice = next((n for n in notices if n['association']['noticeType'] == 'results' and
                     re.search(r'获奖|成绩|结果', n['title']) and not re.search(r'报名审核|资格审核|初审|拟推荐|候选', n['title']) and
                     n['association']['phase'] == slot['phase'] and
                     n['association']['stage'] == slot['stage'] and
                     n['association'].get('resultTrack') == slot['trackId'] and
                     n['date'] >= entry['date']), None)
        if result_notice:
            slot['closureEvidence'] = result_notice['association']['typeEvidence']
        starts = [s for s in group['timeline'] if s['kind'] == 'registration_start' and
                  (s['trackId'], s['phase'], s['stage']) == (slot['trackId'], slot['phase'], slot['stage'])]
        start_conflict = any(s['state'] != 'confirmed' for s in starts)
        future_start = any(event_instant(e['event']) and event_instant(e['event']) > now for s in starts for e in s['entries'])
        slot['registrationStatus'] = ('needs_review' if start_conflict or instant is None else
                                      'closed' if result_notice or instant <= now else 'not_started' if future_start else 'open')
        if slot['registrationStatus'] == 'open':
            candidates.append({**entry, 'trackId': slot['trackId'], 'phase': slot['phase'], 'stage': slot['stage']})
    if state == 'confirmed':
        statuses = {s['registrationStatus'] for s in deadlines}
        status = 'open' if 'open' in statuses else 'not_started' if statuses == {'not_started'} else (
            'closed' if statuses == {'closed'} else 'needs_review')
    else:
        status = state
    candidates.sort(key=lambda e: event_instant(e['event']))
    return {'status': status, 'deadlineState': state, 'openNodes': candidates,
            'nextDeadline': candidates[0] if candidates and status == 'open' else None}


def link_competition(notice, competitions):
    """Keep supplied catalogue matches; add only unique literal names/aliases."""
    if notice.get('competition'):
        return notice['competition'], 'catalogue_match'
    title = re.sub(r'[\s“”"‘’]', '', notice['title'])
    matches = []
    for competition in competitions:
        names = [competition['name'], competition.get('alias') or '']
        if any(len(name) >= 4 and re.sub(r'[\s“”"‘’]', '', name) in title for name in names):
            matches.append(competition['name'])
    return (matches[0], 'literal_title') if len(matches) == 1 else ('', 'ambiguous' if matches else 'unmatched')


def associate(notices, competitions, now=None):
    now = now or dt.datetime.now(TZ)
    if isinstance(now, str):
        now = dt.datetime.fromisoformat(now).replace(tzinfo=TZ)
    by_name = {}
    for notice in notices:
        name, method = link_competition(notice, competitions)
        notice['competition'] = name
        if not name:
            notice['association'] = {'competitionMethod': method, 'editionId': None}
            continue
        notice['association'] = {**identity(notice), 'competitionMethod': method, 'editionId': None}
        title_fields = notice.get('fields') or rules({'url': notice['url'], 'title': notice['title'], 'body': '', 'date': notice['date']})
        title_tracks = [t['id'] for t in title_fields.get('tracks', [])
                        if t['verification'] == 'source_matched' and t['location']['type'] == 'title']
        notice['association']['resultTrack'] = title_tracks[0] if len(title_tracks) == 1 else (
            'ambiguous:' + notice['url'] if title_tracks else None)
        if name:
            by_name.setdefault(name, []).append(notice)
    for competition in competitions:
        related = by_name.get(competition['name'], [])
        # A bridge requires an explicit notice containing both year and edition.
        anchors = {(n['association']['year'], n['association']['edition'], n['association']['resultTrack']) for n in related
                   if n['association']['year'] and n['association']['edition'] and not n['association']['ambiguous']}
        groups = {}
        for notice in related:
            a = notice['association']
            year, edition = a['year'], a['edition']
            bridge = None
            if not a['ambiguous']:
                matches = [pair[:2] for pair in anchors if (year is None or pair[0] == year) and
                           (edition is None or pair[1] == edition) and pair[2] == a['resultTrack']] if year or edition else []
                matches = list(set(matches))
                if len(matches) == 1:
                    bridge = matches[0]
                    year, edition = bridge
            key = ('unknown', notice['url']) if a['ambiguous'] or (not year and not edition) else (year, edition)
            if key not in groups:
                edition_id = hashlib.sha256((competition['name'] + repr(key)).encode()).hexdigest()[:16]
                label = ('%s 年' % year if year else '') + (' · 第%s届' % edition if edition else '')
                groups[key] = {'id': edition_id, 'year': year, 'yearEnd': a['yearEnd'] or year,
                               'edition': edition, 'label': label.strip(' ·') or '届次待核实',
                               'identityState': 'confirmed' if year and not a['ambiguous'] else 'needs_review', 'notices': []}
            group = groups[key]
            group['yearEnd'] = max(group['yearEnd'] or 0, a['yearEnd'] or 0) or None
            a['editionId'] = group['id']
            a['identityMethod'] = 'explicit_anchor' if bridge and (a['year'], a['edition']) != bridge else 'title'
            if a['identityMethod'] == 'explicit_anchor':
                anchor = next(n for n in related if (n['association']['year'], n['association']['edition']) == bridge and
                              n['association']['resultTrack'] == a['resultTrack'])
                a['anchorEvidence'] = anchor['association']['evidence'] + anchor['association']['editionEvidence']
            group['notices'].append(notice)
        editions = []
        for group in groups.values():
            members = group.pop('notices')
            if group['yearEnd'] and group['year'] and group['yearEnd'] > group['year']:
                group['label'] = group['label'].replace('%s 年' % group['year'], '%s–%s 年' % (group['year'], group['yearEnd']))
            for member in members:
                member['association']['editionLabelResolved'] = group['label']
            aggregate(group, members)
            group['registration'] = registration_summary(group, members, now)
            group['notices'] = [{'url': n['url'], 'title': n['title'], 'date': n['date'],
                                 'hasBody': bool(n.get('fields'))} for n in
                                sorted(members, key=lambda n: (n['date'], n['url']), reverse=True)]
            editions.append(group)
        editions.sort(key=lambda g: (g['year'] or 0, g['edition'] if isinstance(g['edition'], int) else 0,
                                     g['notices'][0]['date']), reverse=True)
        current = [g for g in editions if g['identityState'] == 'confirmed' and g['year'] and g['year'] <= now.year <= (g['yearEnd'] or g['year'])]
        # Keep simultaneous current-year rounds distinct; the first id is a compatibility reference.
        chosen = current[0] if current else None
        competition['editions'] = editions
        competition['currentEditionId'] = chosen['id'] if chosen else None
        competition['currentEditionIds'] = [g['id'] for g in current]
        missing_state = 'needs_review' if any(g['identityState'] != 'confirmed' for g in editions) else 'not_mentioned'
        competition['registration'] = {'status': missing_state,
            'deadlineState': missing_state, 'openNodes': [], 'nextDeadline': None}
        if current:
            statuses = {g['registration']['status'] for g in current}
            nodes = [{**node, 'editionId': g['id'], 'editionLabel': g['label']} for g in current
                     if g['registration']['status'] == 'open' for node in g['registration']['openNodes']]
            nodes.sort(key=lambda e: event_instant(e['event']))
            status = ('open' if nodes else 'conflict' if 'conflict' in statuses else 'needs_review' if 'needs_review' in statuses else
                      'closed' if statuses == {'closed'} else 'not_started' if statuses == {'not_started'} else 'not_mentioned')
            competition['registration'] = {'status': status, 'deadlineState': 'confirmed' if nodes else status,
                                           'openNodes': nodes, 'nextDeadline': nodes[0] if nodes else None}
    return by_name
