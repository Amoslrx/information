"""Conservative edition clues scoped to the named competition, with exact evidence."""
import re

from notice_fields import fact, sources

ROUND = r'第[一二三四五六七八九十百零〇\d]+届'


def identity_sources(record):
    return [{'raw': raw, 'location': loc} for raw, loc in sources(record)
            if re.search(r'20\d{2}|第.*届', raw) and re.search(r'竞赛|大赛|挑战赛', raw)]


def normalize(text):
    return re.sub(r'[\s“”"‘’]', '', text)


def scoped_clues(raw, names):
    """Do not equate a bare deadline, a publication year or a past achievement with an edition."""
    normalized = normalize(raw)
    clues = []
    for name in names:
        name = normalize(name)
        if len(name) < 4:
            continue
        for match in re.finditer(re.escape(name), normalized):
            before = re.split(r'[，,。；;：:《》]', normalized[:match.start()])[-1][-70:]
            after = normalized[match.end():match.end() + 65]
            if re.search(r'往年|往届|上届|回顾|历届|曾于|为迎接|为备战|准备参加', before):
                continue
            round_match = re.search('(' + ROUND + r')[（()）]*$', before)
            prefix = before[:round_match.start()] if round_match else before
            year_match = re.search(r'(?<!\d)(20\d{2})(?:年|年度)?[（()）]*$', prefix)
            if not year_match:
                # "拟定于2026年4月—12月期间举办第八届…" explicitly dates that edition.
                held_before = re.search(r'(20\d{2})年[^。；;，,]{0,28}(?:举办|举行|组织参加)$', prefix)
                if held_before and len(set(re.findall(r'20\d{2}', held_before.group()))) == 1:
                    year_match = held_before
            year_end = None
            season = re.search(r'(20\d{2})[-—–/](20\d{2})(?:年|赛季)?[（()）]*$', prefix)
            if season:
                year, year_end = int(season[1]), int(season[2])
            elif year_match:
                year = int(year_match[1])
            else:
                suffix = re.match(r'[（(](20\d{2})[）)]', after)
                held = re.match(r'(?:将|拟)?(?:定)?于(20\d{2})年[^。；;]{0,30}(?:举办|举行|开展|召开)', after)
                year = int((suffix or held)[1]) if suffix or held else None
            if year or round_match:
                clues.append({'year': year, 'yearEnd': year_end or year,
                              'editionLabel': round_match[1] if round_match else None})
    return clues


def refine_identity(notice, baseline, names, round_number):
    title = notice['title']
    title_clues = scoped_clues(title, names)
    raw_sources = notice.get('identitySources')
    if raw_sources is None:
        raw_sources = identity_sources(notice)
    body_clues = [(clue, source) for source in raw_sources
                  for clue in scoped_clues(source['raw'], names)]
    # A named title can disambiguate multiple competitions mentioned in that same title.
    years = {c['year'] for c in title_clues if c['year']} if title_clues else (
        {baseline['year']} if baseline['year'] else set())
    rounds = {round_number(c['editionLabel']) for c in title_clues if c['editionLabel']} if title_clues else (
        {baseline['edition']} if baseline['edition'] else set())
    year_evidence = list(baseline['evidence']) if not title_clues else []
    round_evidence = list(baseline['editionEvidence']) if not title_clues else []
    for clue in title_clues:
        loc = {'type': 'title', 'start': 0, 'end': len(title)}
        if clue['year']:
            year_evidence.append(fact(str(clue['year']), title, notice, loc))
        if clue['editionLabel']:
            round_evidence.append(fact(clue['editionLabel'], title, notice, loc))
    for clue, source in body_clues:
        if clue['year']:
            years.add(clue['year'])
            year_evidence.append(fact(str(clue['year']), source['raw'], notice, source['location']))
        if clue['editionLabel']:
            rounds.add(round_number(clue['editionLabel']))
            round_evidence.append(fact(clue['editionLabel'], source['raw'], notice, source['location']))
    ambiguous = len(years) > 1 or len(rounds) > 1 or (baseline['ambiguous'] and not title_clues)
    result = {**baseline, 'year': next(iter(years)) if len(years) == 1 else None,
              'edition': next(iter(rounds)) if len(rounds) == 1 else None,
              'ambiguous': ambiguous, 'evidence': year_evidence, 'editionEvidence': round_evidence,
              'identityConflicts': ['year' if len(years) > 1 else '', 'edition' if len(rounds) > 1 else ''] if ambiguous else [],
              'identityMethod': 'title_body' if body_clues else 'title'}
    result['identityConflicts'] = [s for s in result['identityConflicts'] if s]
    if result['year']:
        ends = [c['yearEnd'] for c in title_clues + [c for c, _ in body_clues]
                if c['year'] == result['year'] and c['yearEnd']]
        result['yearEnd'] = max(ends + [result['year']])
    else:
        result['yearEnd'] = None
    return result


def resolve_references(related):
    """Only one explicitly linked, already confirmed edition may supply missing identity."""
    by_url = {n['url']: n for n in related}
    for notice in related:
        a = notice['association']
        if a['ambiguous'] or (a['year'] and a['edition']):
            continue
        candidates = []
        for reference in notice.get('noticeReferences', []):
            target = by_url.get(reference['value'])
            if not target or target is notice:
                continue
            anchor = target['association']
            if anchor['ambiguous'] or not anchor['year']:
                continue
            if re.search(r'历史|往届|上届|去年', reference['raw']) or not re.search(r'通知|本届|本次|延期|补充|根据|参照', reference['raw']):
                continue
            if a['resultTrack'] and anchor['resultTrack'] and a['resultTrack'] != anchor['resultTrack']:
                continue
            candidates.append((anchor, reference))
        identities = {(c['year'], c['edition'], c['yearEnd']) for c, _ in candidates}
        if len(identities) != 1:
            continue
        anchor, reference = candidates[0]
        if (a['year'] and a['year'] != anchor['year']) or (a['edition'] and a['edition'] != anchor['edition']):
            a['ambiguous'] = True
            a['identityConflicts'].append('reference')
            a['referenceEvidence'] = reference
            continue
        a.update(year=anchor['year'], yearEnd=anchor['yearEnd'], edition=anchor['edition'],
                 identityMethod='explicit_reference', referenceEvidence=reference,
                 anchorEvidence=anchor['evidence'] + anchor['editionEvidence'])
