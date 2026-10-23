"""Conservative target matching; ambiguous evidence goes to review, never signup."""
import csv
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def normalize(text):
    return re.sub(r'[\s“”"（）()·—-]', '', text).casefold()


def catalog():
    with (ROOT / 'data/seed/competitions_master.csv').open(encoding='utf-8-sig') as f:
        rows = list(csv.DictReader(f))
    aliases = json.loads((ROOT / 'data/curated/competition_aliases.json').read_text(encoding='utf-8'))
    return [(r, list(dict.fromkeys([r['竞赛名称'], r.get('西交名单用名', '')] + aliases.get(r['竞赛名称'], [])))) for r in rows]


TYPE_RULES = [('postponement', r'延期|延长.*(?:报名|截止)|(?:报名|截止).*延长|时间调整'),
              ('award', r'获奖|荣获|斩获|喜报|获.*等奖|获.*冠军'),
              ('results', r'结果公示|获奖名单|评审结果|成绩公示'),
              ('recruitment', r'招募|招新|队员选拔'),
              ('training', r'培训|集训|训练营|宣讲'),
              ('registration', r'报名|参赛通知|竞赛通知|大赛通知|比赛通知')]


def classify(record, entries=None):
    entries = entries if entries is not None else catalog()
    title, body = record.get('title', ''), record.get('body', '')
    normalized = normalize(title)
    hits = []
    for row, aliases in entries:
        matched = [a for a in aliases if a and normalize(a) in normalized]
        # Generic robot contest title is shared by several distinct competitions.
        if row['竞赛名称'] == '全国大学生机器人大赛' and re.search(r'robomaster|robotac|robocup', title, re.I):
            matched = [a for a in matched if 'robocon' in a.casefold()]
        if matched:
            hits.append({'name': row['竞赛名称'], 'category': row['西交类别'], 'matchedAlias': max(matched, key=len),
                         'evidence': {'type': 'title', 'raw': title}})
    targets = [h for h in hits if h['category'] in ('A类', 'B类', 'C类')]
    state, reason = 'review', 'insufficient_evidence'
    if len(hits) == 1 and targets:
        state, reason = 'target', 'unique_title_match'
        # The EE list recognizes a particular Blue Bridge track, not every track.
        if '蓝桥杯' in targets[0]['name'] and '智能装备数字化建模' not in title + body:
            state, reason = 'review', 'electrical_c_track_unconfirmed'
    elif len(hits) > 1:
        reason = 'multiple_competitions'
    elif hits:
        state, reason = 'excluded', 'outside_target_catalog'
    elif record.get('status') == 'success' and not re.search(r'竞赛|比赛|大赛|挑战杯|招募|战队|建模|电赛|robot|icpc|蓝桥', title + body, re.I):
        state, reason = 'excluded', 'no_competition_evidence'
    types = []
    for kind, pattern in TYPE_RULES:
        match = re.search(pattern, title)
        if match:
            types.append({'type': kind, 'evidence': {'type': 'title', 'start': match.start(), 'end': match.end(), 'raw': match[0]}})
    primary = types[0]['type'] if types else 'unknown'
    # Results and award reports must never be promoted into registration lists.
    signup = state == 'target' and primary in ('registration', 'recruitment', 'postponement') and not any(t['type'] in ('award', 'results') for t in types)
    return {'state': state, 'reason': reason, 'matches': hits, 'noticeTypes': types,
            'primaryType': primary, 'eligibleForSignup': signup,
            'requiresReview': state == 'review' or primary == 'unknown'}
