"""Auditable mapping from the 27 scoped competitions to configured crawlers."""
import csv
import json
from pathlib import Path
from crawl_xjtu_notices import SOURCES, API_SOURCES, EXTRA_SOURCES

ROOT = Path(__file__).resolve().parents[1]
RULES = [
    ('国际大学生创新', ['pec', 'jwc_jsdc', 'jwc_jsap', 'tuanwei']),
    ('挑战杯', ['tuanwei', 'jwc_jsdc', 'ee_bks']),
    ('数学建模', ['pec', 'jwc_jsap']),
    ('电子设计', ['ee_bks', 'ee_yjs', 'pec', 'jwc_jsap']),
    ('智能汽车', ['pec', 'ee_bks']),
    ('节能减排', ['epe_competitions', 'epe_notices', 'tuanwei', 'pec']),
    ('全国大学生机器人大赛', ['robocon', 'robocon_team', 'pec_teams', 'tuanwei']),
    ('RoboCup', ['robocup', 'pec', 'jwc_jsap']),
    ('机器人及人工智能', ['ee_bks', 'ee_yjs', 'pec']),
    ('物联网', ['pec', 'ee_bks', 'ee_yjs']),
    ('Robomasters', ['robomaster', 'pec_teams', 'tuanwei', 'xjtu_news_teams']),
    ('ACM', ['acm_vjudge', 'acm_luogu']),
    ('机械创新', ['pec', 'ee_bks']),
    ('年会展示', ['pec_projects', 'jwc_dcxm', 'jwc_jsdc']),
    ('蓝桥杯', ['ee_bks', 'ee_yjs']),
    ('周培源', ['pec', 'jwc_jsap']),
    ('睿抗', ['ee_bks', 'ee_yjs']),
    ('研究生创新', ['gs_competitions', 'ee_yjs']),
    ('物理学术', ['pec', 'jwc_jsap']),
    ('航空航天模型', ['xjtu_news_teams', 'tuanwei']),
    ('青少年科技创新', ['tuanwei', 'jwc_jsap', 'electrical_modeling', 'ces']),
    ('临床技能', ['medical_teaching', 'medical_hospital']),
    ('电工数学', ['electrical_modeling']),
    ('高压等离子体', ['ces', 'xjtu_news_teams', 'ee_bks']),
    ('电气电子工程创新', ['ee_bks', 'ces']),
]


def main():
    sources = {s['key']: s for s in SOURCES + API_SOURCES + EXTRA_SOURCES}
    status_file = ROOT / 'data/seed/source_status.json'
    statuses = {s['key']: s for s in json.loads(status_file.read_text(encoding='utf-8'))['sources']}
    with (ROOT / 'data/seed/competitions_master.csv').open(encoding='utf-8-sig') as f:
        comps = [c for c in csv.DictReader(f) if c['西交类别'] in ('A类', 'B类', 'C类')]
    records = []
    for comp in comps:
        keys = []
        for keyword, matching in RULES:
            if keyword in comp['竞赛名称'] and (keyword != '全国大学生机器人大赛' or keyword == comp['竞赛名称']):
                keys.extend(matching)
        keys = list(dict.fromkeys(keys))
        assert keys, comp['竞赛名称']
        records.append({'competition': comp['竞赛名称'], 'category': comp['西交类别'],
                        'sources': [{'key': k, 'label': sources[k]['label'],
                                     'url': sources[k].get('url', sources[k].get('base', 'https://tuanwei.xjtu.edu.cn/catalog?id=9')),
                                     'lastRun': statuses.get(k)} for k in keys]})
    (ROOT / 'data/seed/competition_source_coverage.json').write_text(
        json.dumps({'scope': '12A + 7B + 8电气C', 'competitions': records}, ensure_ascii=False, indent=2), encoding='utf-8')
    lines = ['# A/B/电气C类通知来源接入表', '', '每个来源已纳入默认爬虫。状态反映最近一次实抓；配置接入不等于每个来源都有当前报名通知。', '',
             '|类别|竞赛|抓取来源|', '|---|---|---|']
    for r in records:
        links = ['[%s](%s)' % (s['label'], s['url']) for s in r['sources']]
        lines.append('|%s|%s|%s|' % (r['category'], r['competition'], '；'.join(links)))
    lines.extend(['', '## 补充来源最近抓取状态', '', '|来源|状态|条数|缺少发布时间|', '|---|---|---|---|'])
    for key, s in statuses.items():
        lines.append('|%s|%s|%s|%s|' % (sources[key]['label'], s['state'], s['count'], s['missingDates']))
    lines.extend(['', '说明：ok_no_matching_notices 表示栏目可解析，但本次抓取页内没有匹配赛事的通知。partial 表示部分记录缺日期或存在请求失败；needs_adapter_or_unavailable 表示没有成功取得通知，需查看 source_status.json 中的原因。',
                  '', 'VJudge 团队创建时间、比赛起止时间不作为公告发布时间。洛谷本机抓取遇到重定向循环，已保留来源配置，后续常规更新会重试。队伍介绍与获奖报道只作为线索，不能等同报名通知。',
                  '', '蓝桥杯电气C认定范围为智能装备数字化建模专项；目录沿用现有父赛事名称，认定不扩大到全部蓝桥杯赛道。'])
    (ROOT / '竞赛来源接入表_2026-10-05.md').write_text('\n'.join(lines), encoding='utf-8')


if __name__ == '__main__':
    main()
