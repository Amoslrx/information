import copy
import unittest

from notice_editions import associate, identity
from notice_fields import rules


def notice(title, body='', date='2026-09-01', url=None, competition='测试竞赛', parsed=True):
    record = {'title': title, 'body': body, 'date': date, 'url': url or 'https://example.edu/' + title,
              'competition': competition, 'contentHash': 'fixture', 'status': 'success'}
    if parsed:
        record['fields'] = rules(record)
    return record


def build(notices, now='2026-10-04T12:00:00'):
    comps = [{'name': '测试竞赛', 'alias': ''}]
    associate(notices, comps, now)
    return comps[0], next((g for g in comps[0]['editions'] if g['id'] == comps[0]['currentEditionId']), None)


class EditionTests(unittest.TestCase):
    def test_old_year_and_unknown_identity_do_not_pollute_current(self):
        notices = [notice('2025年测试竞赛报名', '报名截止2026年12月30日。\n联系人：旧老师 电话：13800138000'),
                   notice('2026年测试竞赛报名', '报名截止2026年11月20日。\n联系人：新老师 电话：13900139000'),
                   notice('测试竞赛延期通知', '报名延期至2026年12月25日。', date='2026-10-01')]
        comp, current = build(notices)
        self.assertEqual(len(comp['editions']), 3)
        self.assertEqual(comp['registration']['nextDeadline']['event']['value'], '2026-11-20')
        self.assertEqual(len(current['fields']['contacts']), 1)
        self.assertNotIn('旧老师', str(current))
        self.assertNotEqual(notices[2]['association']['editionId'], current['id'])

    def test_round_bridge_has_evidence_and_chinese_round_normalizes(self):
        notices = [notice('2026年第十二届测试竞赛报名', '报名截止2026年11月20日。'),
                   notice('第12届测试竞赛补充通知', '报名方式：填写报名表。', date='2026-09-02')]
        comp, current = build(notices)
        self.assertEqual(len(comp['editions']), 1)
        self.assertEqual(current['edition'], 12)
        self.assertEqual(notices[1]['association']['identityMethod'], 'explicit_anchor')
        self.assertTrue(notices[1]['association']['anchorEvidence'])

    def test_ambiguous_round_bridge_does_not_guess_year(self):
        notices = [notice('2025年第十二届测试竞赛'), notice('2026年第十二届测试竞赛'),
                   notice('第十二届测试竞赛补充通知')]
        comp, current = build(notices)
        self.assertEqual(len(comp['editions']), 3)
        self.assertNotEqual(notices[2]['association']['editionId'], current['id'])

    def test_topic_round_is_not_assigned_to_another_topic_and_both_current_groups_remain_visible(self):
        items = [notice('2026年第十三届测试竞赛AI专题赛报名', '报名截止2026年10月20日。'),
                 notice('2026年测试竞赛模拟设计专题赛报名', '报名截止2026年10月22日。')]
        comp, current = build(items)
        self.assertEqual(len(comp['currentEditionIds']), 2)
        self.assertNotEqual(items[0]['association']['editionId'], items[1]['association']['editionId'])
        self.assertEqual(len(comp['registration']['openNodes']), 2)

    def test_publication_date_is_not_a_competition_year(self):
        comp, current = build([notice('测试竞赛报名', '报名截止2026年12月20日。')])
        self.assertIsNone(current)
        self.assertEqual(comp['registration']['status'], 'needs_review')

    def test_future_old_deadline_is_not_current_when_no_current_edition(self):
        comp, current = build([notice('2025年测试竞赛报名', '报名截止2026年12月20日。')])
        self.assertIsNone(current)
        self.assertIsNone(comp['registration']['nextDeadline'])

    def test_cross_year_season_remains_current_with_explicit_range(self):
        comp, current = build([notice('2025-2026年测试竞赛报名', '报名截止2026年12月20日。')])
        self.assertEqual(current['yearEnd'], 2026)
        self.assertEqual(comp['registration']['status'], 'open')

    def test_supplement_literal_name_can_be_associated_without_supplied_catalogue(self):
        item = notice('2026年测试竞赛补充通知', competition='')
        comps = [{'name': '测试竞赛', 'alias': ''}]
        associate([item], comps, '2026-10-04T12:00:00')
        self.assertEqual(item['competition'], '测试竞赛')
        self.assertEqual(item['association']['competitionMethod'], 'literal_title')


class RevisionTests(unittest.TestCase):
    def test_explicit_postponement_updates_only_registration_and_preserves_history(self):
        items = [notice('2026年测试竞赛报名', '报名截止2026年10月20日18点。\n作品提交截止2026年11月5日。'),
                 notice('2026年测试竞赛报名延期通知', '报名截止延期至2026年10月30日18点。', date='2026-10-02')]
        original = copy.deepcopy(items[0]['fields'])
        comp, current = build(items)
        deadline = next(s for s in current['timeline'] if s['kind'] == 'registration_deadline')
        self.assertEqual(deadline['entries'][0]['event']['value'], '2026-10-30')
        self.assertEqual(deadline['history'][0]['event']['value'], '2026-10-20')
        self.assertEqual(deadline['changes'][0]['evidence']['sourceUrl'], items[1]['url'])
        self.assertEqual(next(s for s in current['timeline'] if s['kind'] == 'submission')['entries'][0]['event']['value'], '2026-11-05')
        self.assertEqual(comp['registration']['status'], 'open')
        self.assertEqual(items[0]['fields'], original)

    def test_multi_track_and_phase_isolation(self):
        items = [notice('2026年测试竞赛校赛报名', 'A赛道\n报名截止2026年10月20日。\nB赛道\n报名截止2026年10月22日。'),
                 notice('2026年测试竞赛校赛—A赛道报名延期通知', '报名截止延期至2026年10月30日。', date='2026-10-02'),
                 notice('2026年测试竞赛国赛—A赛道报名', '报名截止2026年11月20日。')]
        comp, current = build(items)
        values = {(s['phase'], current['tracks'].get(s['trackId'])): s['entries'][0]['event']['value'] for s in current['timeline']}
        self.assertEqual(values[('campus', 'A赛道')], '2026-10-30')
        self.assertEqual(values[('campus', 'B赛道')], '2026-10-22')
        self.assertEqual(values[('national', 'A赛道')], '2026-11-20')
        self.assertEqual(len(current['changes']), 1)

    def test_unscoped_revision_does_not_overwrite_any_track(self):
        items = [notice('2026年测试竞赛报名', 'A赛道\n报名截止2026年10月20日。\nB赛道\n报名截止2026年10月22日。'),
                 notice('2026年测试竞赛延期通知', '报名截止延期至2026年10月30日。', date='2026-10-02')]
        comp, current = build(items)
        self.assertEqual(comp['registration']['status'], 'needs_review')
        self.assertEqual(current['changes'][0]['status'], 'needs_review')
        self.assertEqual(len(current['timeline']), 3)
        self.assertFalse(any(s['history'] for s in current['timeline']))

    def test_unexplained_different_deadline_is_conflict_not_latest_wins(self):
        items = [notice('2026年测试竞赛报名', '报名截止2026年10月20日。'),
                 notice('2026年测试竞赛补充通知', '报名截止2026年10月30日。', date='2026-10-02')]
        comp, current = build(items)
        self.assertEqual(comp['registration']['status'], 'conflict')
        self.assertEqual(len(current['timeline'][0]['entries']), 2)
        self.assertFalse(current['changes'])

    def test_old_and_new_in_same_sentence_and_sequential_revisions(self):
        items = [notice('2026年测试竞赛延期通知', '报名截止由2026年10月20日延期至2026年10月30日。'),
                 notice('2026年测试竞赛再次延期通知', '报名截止延期至2026年11月5日。', date='2026-10-02')]
        comp, current = build(items)
        self.assertEqual(comp['registration']['nextDeadline']['event']['value'], '2026-11-05')
        self.assertEqual([e['event']['value'] for e in current['timeline'][0]['history']], ['2026-10-20', '2026-10-30'])

    def test_conflicting_declared_old_value_and_same_day_order_remain_pending(self):
        for date, body in [('2026-10-02', '报名截止由2026年10月22日延期至2026年10月30日。'),
                           ('2026-09-01', '报名截止延期至2026年10月30日。')]:
            comp, current = build([notice('2026年测试竞赛报名', '报名截止2026年10月20日。'),
                                   notice('2026年测试竞赛延期通知', body, date=date)])
            self.assertNotEqual(comp['registration']['status'], 'open')
            self.assertTrue(any(c['status'] == 'needs_review' for c in current['changes']))

    def test_missing_year_or_ocr_revision_cannot_become_confirmed(self):
        for body, ocr in [('报名截止延期至10月30日。', False), ('报名截止延期至2026年10月30日。', True)]:
            revision = notice('2026年测试竞赛延期通知', body, date='2026-10-02')
            if ocr:
                revision['fields']['timeline'][0].update(method='ocr', verification='needs_review', flags=['postponed', 'ocr_requires_review'])
            comp, current = build([notice('2026年测试竞赛报名', '报名截止2026年10月20日。'), revision])
            self.assertEqual(comp['registration']['status'], 'needs_review')

    def test_unparsed_extension_blocks_stale_registration(self):
        comp, current = build([notice('2026年测试竞赛报名', '报名截止2026年10月20日。'),
                               notice('2026年测试竞赛延期通知', date='2026-10-02', parsed=False)])
        self.assertEqual(comp['registration']['status'], 'needs_review')
        self.assertFalse(current['complete'])

    def test_complex_multi_stage_revision_never_updates_wrong_stage(self):
        comp, current = build([notice('2026年测试竞赛校赛报名',
                                      '第1阶段报名截止2026年10月20日，第2阶段报名截止延期至2026年10月30日。')])
        self.assertFalse(any(c['status'] == 'applied' for c in current['changes']))
        self.assertNotEqual(comp['registration']['status'], 'open')


class StatusTests(unittest.TestCase):
    def test_precise_time_and_24_hour_deadline(self):
        item = notice('2026年测试竞赛报名', '报名截止2026年10月4日18点。')
        self.assertEqual(build([copy.deepcopy(item)], '2026-10-04T17:59:00')[0]['registration']['status'], 'open')
        self.assertEqual(build([copy.deepcopy(item)], '2026-10-04T18:00:00')[0]['registration']['status'], 'closed')
        item = notice('2026年测试竞赛报名', '报名截止2026年10月4日24:00。')
        self.assertEqual(build([copy.deepcopy(item)], '2026-10-04T23:59:00')[0]['registration']['status'], 'open')
        self.assertEqual(build([copy.deepcopy(item)], '2026-10-05T00:00:00')[0]['registration']['status'], 'closed')

    def test_future_start_and_result_phase_scope(self):
        items = [notice('2026年测试竞赛校赛报名', '报名开始2026年10月10日。\n报名截止2026年10月20日。')]
        self.assertEqual(build(items)[0]['registration']['status'], 'not_started')
        items = [notice('2026年测试竞赛校赛报名', '报名截止2026年10月20日。'),
                 notice('2026年测试竞赛国赛报名', '报名截止2026年11月20日。'),
                 notice('2026年测试竞赛校赛结果公示', date='2026-10-02')]
        comp, current = build(items)
        statuses = {s['phase']: s['registrationStatus'] for s in current['timeline']}
        self.assertEqual(statuses, {'campus': 'closed', 'national': 'open'})

    def test_second_stage_results_do_not_close_first_stage_or_another_track(self):
        items = [notice('2026年测试竞赛校赛第一阶段—A赛道报名', '报名截止2026年10月20日。'),
                 notice('2026年测试竞赛校赛第二阶段—A赛道结果公示', date='2026-10-02', parsed=False)]
        comp, current = build(items)
        self.assertEqual(comp['registration']['status'], 'open')
        self.assertEqual(current['timeline'][0]['stage'], '第1阶段')
        items[1]['title'] = '2026年测试竞赛校赛第一阶段—B赛道结果公示'
        self.assertEqual(build(items)[0]['registration']['status'], 'open')

    def test_missing_and_incomplete_are_distinct(self):
        comp, current = build([notice('2026年测试竞赛报名', '报名截止2026年10月20日。')])
        self.assertEqual(current['fieldStates']['requiredMaterials'], 'not_mentioned')
        comp, current = build([notice('2026年测试竞赛报名', parsed=False)])
        self.assertEqual(current['fieldStates']['requiredMaterials'], 'needs_review')

    def test_registration_review_publicity_does_not_close_registration(self):
        comp, current = build([notice('2026年测试竞赛报名', '报名截止2026年10月20日。'),
                               notice('2026年测试竞赛报名审核结果公示', date='2026-10-02')])
        self.assertEqual(comp['registration']['status'], 'open')


if __name__ == '__main__':
    unittest.main()
